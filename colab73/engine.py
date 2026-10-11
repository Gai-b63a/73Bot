"""Qwen adapter. Imported inside the sole GPU-owning child process."""
from __future__ import annotations

from dataclasses import dataclass
import gc
import importlib.metadata
import subprocess
import sys
import time
from typing import Protocol


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


class QwenEngine:
    def __init__(self):
        self.model = None
        self.prompt = None

    def load(self, model_path: str) -> dict:
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("GPUがありません。ColabのランタイムをGPUに変更してください。")
        from qwen_tts import Qwen3TTSModel
        # Do not emulate BF16 on pre-Ampere GPUs such as T4.
        bf16 = torch.cuda.get_device_capability()[0] >= 8 and torch.cuda.is_bf16_supported()
        dtype = torch.bfloat16 if bf16 else torch.float32
        self.model = Qwen3TTSModel.from_pretrained(
            model_path, device_map="cuda:0", dtype=dtype, attn_implementation="sdpa",
        )
        return {"gpu": torch.cuda.get_device_name(), "dtype": str(dtype), "attention": "sdpa",
                "python": sys.version.split()[0], "torch": torch.__version__,
                "qwen_tts": importlib.metadata.version("qwen-tts")}

    def prepare_voice(self, audio_path: str, text: str = "") -> None:
        text = text.strip()
        self.prompt = self.model.create_voice_clone_prompt(
            ref_audio=audio_path, ref_text=text or None, x_vector_only_mode=not bool(text),
        )

    def synthesize(self, text: str) -> AudioChunk:
        import numpy as np
        import torch
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
        started = time.monotonic()
        wavs, sample_rate = self.model.generate_voice_clone(
            text=text, language="Japanese", voice_clone_prompt=self.prompt,
            max_new_tokens=512,
        )
        torch.cuda.synchronize()
        audio = np.asarray(wavs[0], dtype="<f4").reshape(-1)
        if not audio.size or not np.isfinite(audio).all():
            raise RuntimeError("有効な音声を生成できませんでした。Colabから再起動してください。")
        conversion = subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "f32le", "-ar", str(sample_rate), "-ac", "1", "-i", "pipe:0",
            "-f", "s16le", "-ar", "48000", "-ac", "2", "pipe:1",
        ], input=audio.tobytes(), capture_output=True, check=True, timeout=15)
        return AudioChunk(conversion.stdout, len(conversion.stdout) / 192000,
                          time.monotonic() - started,
                          torch.cuda.max_memory_allocated() / 1024**2)

    def close(self) -> None:
        self.prompt = self.model = None
        gc.collect()
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
