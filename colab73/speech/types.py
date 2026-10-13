"""Speech contracts without model or GPU dependencies."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass
class AudioChunk:
    pcm: bytes  # 48 kHz, stereo, signed little-endian 16-bit PCM
    seconds: float
    generation_seconds: float
    peak_memory_mb: float = 0


class SpeechEngine(Protocol):
    def load(self, model_path: str) -> dict: ...
    def prepare_voice(self, audio_path: str, text: str = "") -> None: ...
    def synthesize(self, text: str) -> AudioChunk: ...
    def close(self) -> None: ...


class Synthesizer(Protocol):
    async def synthesize(self, text: str) -> AudioChunk: ...


class AudioPlayer(Protocol):
    async def play(self, audio: AudioChunk, on_first_packet: Callable[[float], None]) -> None: ...
    def stop(self) -> None: ...


