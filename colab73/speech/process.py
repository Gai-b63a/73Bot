"""Entry point for the sole GPU-owning child process."""
import multiprocessing as mp
import os
import queue
import signal
import sys


def _worker_main(incoming, outgoing, model_path, preset, engine_factory):
    # A notebook/BOT force-stop must not leave an orphan holding the GPU.
    if sys.platform == "linux":
        import ctypes
        parent = os.getppid()
        ctypes.CDLL(None).prctl(1, signal.SIGTERM)
        if os.getppid() != parent:
            return
    engine = engine_factory()
    try:
        info = engine.load(model_path)
        engine.prepare_voice(preset["audio_path"], preset["text"])
        info["reference_mode"] = "audio_and_transcript" if preset["text"].strip() else "audio_only"
        engine.synthesize("読み上げの準備ができました。")
        outgoing.put(("ready", info))
        while True:
            try:
                message = incoming.get(timeout=1)
            except queue.Empty:
                parent = mp.parent_process()
                if parent is not None and not parent.is_alive():
                    return
                continue
            if message is None:
                return
            outgoing.put(("audio", engine.synthesize(message)))
    except Exception as exc:
        # No credentials, reference transcript or user message is logged here.
        message = "GPUメモリが不足しています。" if "out of memory" in str(exc).lower() else f"音声生成に失敗しました ({type(exc).__name__})。"
        outgoing.put(("error", message + " Colabの停止ボタンで停止し、再起動してください。"))
        print(message, flush=True)
    finally:
        engine.close()


