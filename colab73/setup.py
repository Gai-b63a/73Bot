"""Prepare the isolated Colab environment with quiet, staged progress."""
from pathlib import Path
import subprocess
import sys

from .locking import RuntimeLock
from .contracts import RuntimePaths


def prepare_environment(project, root="/content/73bot-runtime", progress=print):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    paths = RuntimePaths(root)
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("ランタイムのタイプを変更し、Python 3.12の過去のランタイム（2026.07等）を選んでください。")
    runtime_python = Path("/content/73bot-env/bin/python")
    with RuntimeLock(paths.lock), paths.setup_log.open("a", encoding="utf-8") as log:
        def run(command):
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1200)

        progress("GPUを確認しています…")
        try:
            run([sys.executable, "-c", "import torch; assert torch.cuda.is_available(), 'GPU unavailable'"])
        except subprocess.CalledProcessError:
            raise RuntimeError("GPUが使えません。「ランタイム → ランタイムのタイプを変更」でGPUを選び、再実行してください。") from None
        progress("音声再生に必要な環境を準備しています…")
        run(["apt-get", "update", "-qq"])
        run(["apt-get", "install", "-y", "-qq", "ffmpeg", "libopus0", "libsodium23", "sox"])
        run([sys.executable, "-m", "pip", "install", "-q", "virtualenv", "ipywidgets>=8.1,<9"])
        if not runtime_python.exists():
            run([sys.executable, "-m", "virtualenv", "--system-site-packages", "/content/73bot-env"])
        progress("読み上げ用のライブラリを準備しています…")
        run([str(runtime_python), "-m", "pip", "install", "-q", "-r", str(Path(project) / "requirements-colab.txt")])
        run([str(runtime_python), "-c", "import torch,torchaudio,qwen_tts,discord,davey; assert torch.cuda.is_available(); assert torch.__version__.split('+')[0] == torchaudio.__version__.split('+')[0]"])
    return runtime_python
