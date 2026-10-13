"""Shared execution modes, model identifier and filesystem layout."""
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict

MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
RunMode = Literal["bot", "preview", "benchmark"]
RUN_MODES = frozenset({"bot", "preview", "benchmark"})


class RuntimeStatus(TypedDict, total=False):
    mode: RunMode
    phase: str
    voice: str
    run_id: str
    audio: str
    error: str | None
    process_running: bool
    exit_code: int | None
    environment: dict
    benchmark: dict
    connected: bool
    generating: bool
    guilds: dict


@dataclass(frozen=True)
class RuntimePaths:
    root: Path

    @property
    def lock(self) -> Path:
        return self.root / "runtime.lock"

    @property
    def state(self) -> Path:
        return self.root / "state.json"

    @property
    def console(self) -> Path:
        return self.root / "console.log"

    @property
    def preview_text(self) -> Path:
        return self.root / "preview-text.txt"

    @property
    def uploads(self) -> Path:
        return self.root / "uploads"

    @property
    def setup_log(self) -> Path:
        return self.root / "setup.log"

    @property
    def reports_archive(self) -> Path:
        return self.root / "73Bot_reports.zip"

    def run(self, run_id: str) -> Path:
        return self.root / "runs" / run_id


def validate_mode(mode: str) -> RunMode:
    if mode not in RUN_MODES:
        raise ValueError("実行モードが不正です。")
    return mode
