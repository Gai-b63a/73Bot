"""FIFO playback with exactly one generated segment of lookahead per guild."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .speech.types import AudioPlayer, Synthesizer


@dataclass
class Job:
    message_id: int
    chunks: list[str]
    received_at: float
    idle: bool
    cancelled: bool = False
    sent: bool = False


class GuildReader:
    def __init__(self, engine: Synthesizer, player: AudioPlayer, metrics, on_error, max_pending=100):
        self.engine, self.player, self.metrics = engine, player, metrics
        self.on_error = on_error
        self.queue = asyncio.Queue(maxsize=max_pending)
        self.current = None
        self.closed = False
        self.task = asyncio.create_task(self._run())

    @property
    def is_idle(self):
        return self.current is None and self.queue.empty()

    def submit(self, job: Job) -> bool:
        if self.closed:
            return False
        try:
            self.queue.put_nowait(job)
            return True
        except asyncio.QueueFull:
            return False

    def clear(self):
        count = 0
        while not self.queue.empty():
            self.queue.get_nowait()
            count += 1
        return count

    def skip(self):
        if self.current is not None:
            self.current.cancelled = True
            self.player.stop()

    async def close(self):
        self.closed = True
        self.clear()
        self.skip()
        self.task.cancel()
        if self.task is not asyncio.current_task():
            await asyncio.gather(self.task, return_exceptions=True)

    def _first_packet(self, job: Job, at: float):
        if not self.closed and not job.cancelled and not job.sent:
            job.sent = True
            self.metrics.add(event="first_packet", message_id=job.message_id,
                             latency_seconds=at - job.received_at, idle=job.idle)

    async def _render(self, text):
        audio = await self.engine.synthesize(text)
        self.metrics.add(event="generation", generation_seconds=audio.generation_seconds,
                         audio_seconds=audio.seconds, peak_memory_mb=audio.peak_memory_mb)
        return audio

    async def _read(self, job):
        next_audio = None
        playing = None
        try:
            audio = await self._render(job.chunks[0])
            for index in range(len(job.chunks)):
                if self.closed or job.cancelled:
                    return
                # Playback is begun before one following segment is requested.
                playing = asyncio.create_task(self.player.play(audio, lambda at: self._first_packet(job, at)))
                if index + 1 < len(job.chunks):
                    next_audio = asyncio.create_task(self._render(job.chunks[index + 1]))
                await playing
                playing = None
                if self.closed or job.cancelled:
                    return
                if next_audio is not None:
                    audio = await next_audio
                    next_audio = None
        finally:
            for task in (next_audio, playing):
                if task is not None:
                    task.cancel()
            await asyncio.gather(*(t for t in (next_audio, playing) if t is not None), return_exceptions=True)

    async def _run(self):
        try:
            while True:
                job = await self.queue.get()
                self.current = job
                try:
                    await self._read(job)
                finally:
                    self.current = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.closed = True
            self.clear()
            self.player.stop()
            await self.on_error(str(exc))
