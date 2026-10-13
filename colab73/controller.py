"""Notebook-side controller. Does not import torch or hold GPU memory."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from typing import TYPE_CHECKING

from .contracts import RuntimePaths, RuntimeStatus, validate_mode
from .runtime.state import StateFile
from .storage.store import Store
from .locking import RuntimeLock

if TYPE_CHECKING:
    from .session import SessionVoice
    from .ui.panel import NotebookPanel


class Controller:
    def __init__(self, store_root, local_root="/content/73bot-runtime", python=None):
        self.store = Store(store_root)
        self.local_root = Path(local_root).resolve()
        self.local_root.mkdir(parents=True, exist_ok=True)
        self.paths = RuntimePaths(self.local_root)
        self.state_file = StateFile(self.paths)
        self.session_voice: SessionVoice | None = None
        self.panel: NotebookPanel | None = None
        self.python = str(python or sys.executable)
        self.process = None
        self.log_file = None

    def require_stopped(self):
        with RuntimeLock(self.paths.lock):
            if self.process and self.process.poll() is None:
                raise RuntimeError("起動処理またはBOTが実行中です。先に停止してください。")

    def save_settings(self, value):
        self.require_stopped()
        return self.store.save_settings(value)

    def register(self, *args, **kwargs):
        self.require_stopped()
        return self.store.register(*args, **kwargs)

    def start(self, mode, token=None, text="こんにちは。読み上げのテストです。"):
        validate_mode(mode)
        self.require_stopped()
        self.store.preset()
        if mode == "preview" and not text.strip():
            raise ValueError("試聴する文章を入力してください。")
        if mode == "bot" and not token:
            raise ValueError("BOTトークンをColabのシークレットに登録してください。")
        self.paths.preview_text.write_text(text, encoding="utf-8")
        self.log_file = self.paths.console
        self.state_file.write({"mode": mode, "phase": "起動中"})
        env = os.environ.copy()
        env.pop("DISCORD_BOT_TOKEN", None)
        if mode == "bot":
            env["DISCORD_BOT_TOKEN"] = token
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONUTF8"] = "1"
        env["HF_HUB_DISABLE_TELEMETRY"] = "1"
        repo = Path(__file__).resolve().parent.parent
        with self.log_file.open("w", encoding="utf-8") as output:
            self.process = subprocess.Popen([
                self.python, "-m", "colab73.runner", "--store", str(self.store.root),
                "--local-root", str(self.local_root), "--mode", mode,
            ], cwd=repo, env=env, stdout=output, stderr=subprocess.STDOUT,
               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        elif self._locked():
            raise RuntimeError("別の管理画面で起動した処理です。起動元の停止ボタンを使ってください。")

    def _locked(self):
        try:
            with RuntimeLock(self.paths.lock):
                return False
        except RuntimeError:
            return True

    def status(self) -> RuntimeStatus:
        value = self.state_file.read()
        value["process_running"] = (self.process is not None and self.process.poll() is None) or self._locked()
        if self.process is not None:
            value["exit_code"] = self.process.poll()
        return value

    def logs(self):
        path = self.paths.console
        if not path.exists():
            return "まだログはありません。"
        with path.open("rb") as file:
            file.seek(max(0, path.stat().st_size - 16000))
            return file.read().decode("utf-8", errors="replace")
