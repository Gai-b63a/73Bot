"""Mode-specific work, separate from preparation and resource ownership."""
from pathlib import Path

from ..benchmark import save_pcm
from ..contracts import RuntimePaths
from ..text import split_text


async def run_preview(worker, paths: RuntimePaths, folder: Path, metrics) -> str:
    text = paths.preview_text.read_text(encoding="utf-8")
    pcm = []
    for segment in split_text(text):
        audio = await worker.synthesize(segment)
        pcm.append(audio.pcm)
        metrics.add(event="generation", generation_seconds=audio.generation_seconds,
                    peak_memory_mb=audio.peak_memory_mb, audio_seconds=audio.seconds)
    if not pcm:
        raise ValueError("試聴する文章が空です。")
    output = folder / "preview.wav"
    save_pcm(output, b"".join(pcm))
    return str(output)


async def run_discord(bot, token: str) -> None:
    async with bot:
        await bot.start(token)
