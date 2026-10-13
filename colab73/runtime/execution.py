"""Shared entry point for preview, benchmark and Discord modes."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import AsyncExitStack
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import shutil
import signal
import sys
import uuid

from ..benchmark import benchmark
from ..cache import prepare_model
from ..contracts import MODEL_ID, RUN_MODES, RuntimePaths, RuntimeStatus, validate_mode
from ..storage.store import Store
from .state import StateFile
from .modes import run_preview, run_discord
from .activity import configure as configure_activity, log as activity
from ..locking import RuntimeLock
from ..metrics import Metrics
from ..speech.worker import WorkerClient


async def report_discord_state(bot, state_file, status):
    while True:
        state_file.write({**status, **bot.snapshot(), "phase": "稼働中"})
        await asyncio.sleep(2)


async def finish_run(worker, bot, state_task, metrics, state_file, status,
                     folder: Path, destination: Path):
    """Attempt every resource cleanup, even when a previous close fails."""
    try:
        async with AsyncExitStack() as cleanup:
            if worker:
                cleanup.push_async_callback(worker.close)
            if bot:
                cleanup.push_async_callback(bot.close)
            if state_task:
                state_task.cancel()
                await asyncio.gather(state_task, return_exceptions=True)
    except Exception as exc:
        status.update(phase="エラー", error=f"終了処理に失敗しました ({type(exc).__name__})。Colabから再起動してください。")
        activity.error("終了処理に失敗しました。状態欄と詳細ログを確認してください。")
        raise
    finally:
        metrics.finish(worker.info if worker else {})
        state_file.write(status)
        try:
            await asyncio.to_thread(shutil.copytree, folder, destination, dirs_exist_ok=True)
        except OSError:
            print("レポートの整理に失敗しました。一時ディスクのrunsフォルダに残っています。", flush=True)


async def run(args):
    root = Path(args.local_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    validate_mode(args.mode)
    paths = RuntimePaths(root)
    state_file = StateFile(paths)
    store = Store(args.store)
    settings = store.settings()
    preset = store.preset()
    # Validate configuration and token before downloading/loading a model.
    token = os.environ.pop("DISCORD_BOT_TOKEN", "") if args.mode == "bot" else ""
    if args.mode == "bot" and not token:
        raise ValueError("DISCORD_BOT_TOKENをColabのシークレットに登録してください。")
    with RuntimeLock(paths.lock):
        configure_activity(paths.activity)
        activity.info("モデル準備を開始します。")
        worker = None
        bot = None
        state_task = None
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        folder = paths.run(run_id)
        metrics = Metrics(folder)
        status: RuntimeStatus = {"mode": args.mode, "phase": "準備中", "voice": preset["name"], "run_id": run_id}
        state_file.write(status)
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
            activity.info("音声モデル準備完了（SDPA／FlashAttentionの追加インストール不要）。")
            activity.info("実行環境：Python %s／PyTorch %s／GPU %s", worker.info.get("python", "不明"), worker.info.get("torch", "不明"), worker.info.get("gpu", "不明"))
            worker.info.update(model_id=MODEL_ID, model_revision=model_path.name)
            status.update(phase="準備完了", environment=worker.info)
            state_file.write(status)
            if args.mode == "preview":
                status["audio"] = await run_preview(worker, paths, folder, metrics)
            elif args.mode == "benchmark":
                status["benchmark"] = await benchmark(worker, folder / "benchmark")
            else:
                from ..transport.bot import ColabBot
                bot = ColabBot(worker, settings, preset, metrics)

                state_task = asyncio.create_task(report_discord_state(bot, state_file, status))
                await run_discord(bot, token)
            status["phase"] = "終了"
            activity.info("処理が終了しました。")
        except asyncio.CancelledError:
            status["phase"] = "停止"
            activity.info("停止しました。")
            raise
        except Exception as exc:
            status.update(phase="エラー", error=str(exc).replace(token, "[TOKEN]") if token else str(exc))
            activity.error("実行エラー（%s）。状態欄と詳細ログを確認してください。", type(exc).__name__)
            print(f"エラー: {status['error']}", flush=True)
            raise
        finally:
            await finish_run(worker, bot, state_task, metrics, state_file, status,
                             folder, store.root / "reports" / run_id)


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
    parser.add_argument("--mode", choices=sorted(RUN_MODES), required=True)
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
