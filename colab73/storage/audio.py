"""FFmpeg reference cropping and validation, independent of preset storage."""
from contextlib import contextmanager
import math
from pathlib import Path
import subprocess
import tempfile
import wave


@contextmanager
def reference_audio(source, start=0, end=None):
    source = Path(source).expanduser().resolve(strict=True)
    start = float(start)
    end = float(end) if end is not None else None
    if not math.isfinite(start) or start < 0 or (end is not None and (not math.isfinite(end) or end <= start)):
        raise ValueError("開始・終了秒を確認してください。")
    if end is not None and end - start > 30:
        raise ValueError("声の見本は30秒以内に切り出してください（5〜15秒推奨）。")
    with tempfile.TemporaryDirectory(prefix="73bot-reference-") as temporary:
        output = Path(temporary) / "reference.wav"
        duration = end - start if end is not None else 31
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-ss", str(start), "-i", str(source), "-t", str(duration),
            "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(output),
        ], check=True, capture_output=True, timeout=60)
        with wave.open(str(output), "rb") as wav:
            seconds = wav.getnframes() / wav.getframerate()
            samples = wav.readframes(wav.getnframes())
        if not 3 <= seconds <= 30:
            raise ValueError("見本の長さは3〜30秒にしてください（5〜15秒推奨）。")
        import array
        if not samples or max(abs(n) for n in array.array("h", samples)) < 32:
            raise ValueError("音声が無音、または小さすぎます。別の区間を選んでください。")
        yield output, seconds
