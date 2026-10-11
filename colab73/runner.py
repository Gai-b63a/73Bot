"""Shared entry point for preview, benchmark and Discord modes."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import shutil
import signal
import sys
import uuid

from .benchmark import benchmark, save_pcm
from .cache import prepare_model
from .config import MODEL_ID, Store, write_json
from .locking import RuntimeLock
from .metrics import Metrics
from .text import split_text
from .worker import WorkerClient


async def run(args):
    root = Path(args.local_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    store = Store(args.store)
    settings = store.settings()
    preset = store.preset()
    # Validate configuration and token before downloading/loading a model.
    token = os.environ.pop("DISCORD_BOT_TOKEN", "") if args.mode == "bot" else ""
    if args.mode == "bot" and not token:
        raise ValueError("DISCORD_BOT_TOKENをColabのシークレットに登録してください。")
    with RuntimeLock(root / "runtime.lock"):
        worker = None
        bot = None
        state_task = None
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        folder = root / "runs" / run_id
        metrics = Metrics(folder)
        status = {"mode": args.mode, "phase": "準備中", "voice": preset["name"], "run_id": run_id}
        write_json(root / "state.json", status)
        try:
            # CUDA is checked in a short process so the controller never owns a
            # CUDA context. The only long-lived CUDA process is WorkerClient.
            import subprocess
            check = await asyncio.to_thread(subprocess.run, [sys.executable, "-c",
                "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)"], capture_output=True)
            if check.returncode:
                raise RuntimeError("GPUが利用できません。セットアップとGPUランタイムを確認してください。")
            model_path = await asyncio.to_thread(prepare_model, store.root, root)
            worker = WorkerClient()
            print("音声モデルを準備しています。初回のウォームアップをお待ちください。", flush=True)
            await worker.start(model_path, preset)
            worker.info.update(model_id=MODEL_ID, model_revision=model_path.name)
            status.update(phase="準備完了", environment=worker.info)
            write_json(root / "state.json", status)
            if args.mode == "preview":
                preview_text = (root / "preview-text.txt").read_text(encoding="utf-8")
                pcm = []
                for segment in split_text(preview_text):
                    audio = await worker.synthesize(segment)
                    pcm.append(audio.pcm)
                    metrics.add(event="generation", generation_seconds=audio.generation_seconds,
                                peak_memory_mb=audio.peak_memory_mb, audio_seconds=audio.seconds)
                if not pcm:
                    raise ValueError("試聴する文章が空です。")
                save_pcm(folder / "preview.wav", b"".join(pcm))
                status["audio"] = str(folder / "preview.wav")
            elif args.mode == "benchmark":
                status["benchmark"] = await benchmark(worker, folder / "benchmark")
            else:
                from .discord_bot import ColabBot
                bot = ColabBot(worker, settings, preset, metrics)

                async def report_state():
                    while True:
                        write_json(root / "state.json", {**status, **bot.snapshot(), "phase": "稼働中"})
                        await asyncio.sleep(2)

                state_task = asyncio.create_task(report_state())
                async with bot:
                    await bot.start(token)
            status["phase"] = "終了"
        except asyncio.CancelledError:
            status["phase"] = "停止"
            raise
        except Exception as exc:
            status.update(phase="エラー", error=str(exc).replace(token, "[TOKEN]") if token else str(exc))
            print(f"エラー: {status['error']}", flush=True)
            raise
        finally:
            if state_task:
                state_task.cancel()
                await asyncio.gather(state_task, return_exceptions=True)
            if bot:
                await bot.close()
            if worker:
                await worker.close()
            metrics.finish(worker.info if worker else {})
            write_json(root / "state.json", status)
            destination = store.root / "reports" / run_id
            try:
                await asyncio.to_thread(shutil.copytree, folder, destination, dirs_exist_ok=True)
            except OSError:
                print("レポートをDriveへ保存できませんでした。一時ディスクのrunsフォルダに残っています。", flush=True)


async def cancellable_main(args):
    task = asyncio.create_task(run(args))
    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, task.cancel)
    try:
        await task
    except asyncio.CancelledError:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", required=True)
    parser.add_argument("--local-root", default="/content/73bot-runtime")
    parser.add_argument("--mode", choices=["bot", "preview", "benchmark"], required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    try:
        asyncio.run(cancellable_main(args))
    except Exception as exc:
        # Avoid dumping credentials or a transcript through dependency tracebacks.
        print(f"起動・実行を終了しました ({type(exc).__name__})。上の状態表示を確認してください。", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
