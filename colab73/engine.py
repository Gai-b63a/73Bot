"""Compatibility imports for the speech backend and contracts."""
from .speech.types import AudioChunk, SpeechEngine
from .speech.qwen import QwenEngine

__all__ = ["AudioChunk", "SpeechEngine", "QwenEngine"]
