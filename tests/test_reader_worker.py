import asyncio
from pathlib import Path
import time

import pytest

from colab73.engine import AudioChunk
from colab73.metrics import Metrics
from colab73.reader import GuildReader, Job
from colab73.worker import WorkerClient, WorkerFailure


async def until(predicate, timeout=3):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.005)


class ControlledEngine:
    def __init__(self):
        self.calls = []
        self.gates = {}

    async def synthesize(self, text):
        self.calls.append(text)
        if text in self.gates:
            await self.gates[text].wait()
        return AudioChunk(text.encode(), 1, .1)


class ControlledPlayer:
    def __init__(self):
        self.played = []
        self.gates = []

    async def play(self, audio, callback):
        self.played.append(audio.pcm.decode())
        gate = asyncio.Event()
        self.gates.append(gate)
        callback(time.monotonic())
        await gate.wait()

    def stop(self):
        if self.gates:
            self.gates[-1].set()


def job(number, *chunks):
    return Job(number, list(chunks), time.monotonic(), True)


@pytest.fixture
def setup_reader(tmp_path):
    def make():
        engine, player, errors = ControlledEngine(), ControlledPlayer(), []

        async def error(message):
            errors.append(message)

        reader = GuildReader(engine, player, Metrics(tmp_path), error)
        return reader, engine, player, errors
    return make


@pytest.mark.asyncio
async def test_fifo_and_one_segment_lookahead(setup_reader):
    reader, engine, player, _ = setup_reader()
    try:
        reader.submit(job(1, "a", "b", "c"))
        reader.submit(job(2, "d"))
        await until(lambda: len(engine.calls) == 2)
        assert player.played == ["a"]
        await asyncio.sleep(.03)
        assert engine.calls == ["a", "b"]  # no third segment retained/generated
        player.stop()
        await until(lambda: player.played == ["a", "b"])
        player.stop()
        await until(lambda: player.played == ["a", "b", "c"])
        player.stop()
        await until(lambda: player.played == ["a", "b", "c", "d"])
    finally:
        await reader.close()


@pytest.mark.asyncio
async def test_skip_while_generation_pending_never_plays_stale_audio(setup_reader):
    reader, engine, player, _ = setup_reader()
    engine.gates["old"] = asyncio.Event()
    try:
        reader.submit(job(1, "old", "old-tail"))
        reader.submit(job(2, "new"))
        await until(lambda: "old" in engine.calls)
        reader.skip()
        engine.gates["old"].set()
        await until(lambda: bool(player.played))
        assert player.played == ["new"]
        assert "old-tail" not in engine.calls
    finally:
        await reader.close()


@pytest.mark.asyncio
async def test_clear_keeps_current_post_and_removes_waiting(setup_reader):
    reader, engine, player, _ = setup_reader()
    try:
        reader.submit(job(1, "a", "b"))
        reader.submit(job(2, "discard"))
        await until(lambda: bool(player.played))
        assert reader.clear() == 1
        player.stop()
        await until(lambda: player.played == ["a", "b"])
        player.stop()
        await until(lambda: reader.is_idle)
        assert "discard" not in engine.calls
    finally:
        await reader.close()


@pytest.mark.asyncio
async def test_leave_during_generation_and_capacity(setup_reader):
    reader, engine, player, _ = setup_reader()
    engine.gates["old"] = asyncio.Event()
    for i in range(100):
        assert reader.submit(job(i, "old"))
    assert not reader.submit(job(100, "overflow"))
    await until(lambda: bool(engine.calls))
    await reader.close()
    engine.gates["old"].set()
    await asyncio.sleep(.01)
    assert not player.played
    assert reader.queue.empty()
    assert not reader.submit(job(101, "later"))


class ProcessEngine:
    """Picklable fake backend: exercises real child process + timeout handling."""
    def load(self, path):
        if path == "fail":
            raise RuntimeError("GPU unavailable")
        return {"gpu": "test-double"}

    def prepare_voice(self, *args):
        pass

    def synthesize(self, text):
        if text == "slow":
            time.sleep(.4)
        if text == "oom":
            raise RuntimeError("CUDA out of memory")
        return AudioChunk(text.encode(), 1, .1)

    def close(self):
        pass


@pytest.mark.asyncio
async def test_worker_cancelled_reply_cannot_be_used_for_next_request():
    worker = WorkerClient(engine_factory=ProcessEngine, timeout=3)
    try:
        await worker.start(Path("fake"), {"audio_path": "fake", "text": "fake"})
        first = asyncio.create_task(worker.synthesize("slow"))
        await until(lambda: worker.busy)
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        result = await worker.synthesize("correct")
        assert result.pcm == b"correct"
    finally:
        await worker.close()
    assert not worker.process.is_alive()


@pytest.mark.asyncio
@pytest.mark.parametrize("utterance,timeout,pattern", [("slow", .1, "超え"), ("oom", 3, "メモリ")])
async def test_worker_fatal_failure_stops_gpu_and_pending_requests(utterance, timeout, pattern):
    worker = WorkerClient(engine_factory=ProcessEngine, timeout=timeout)
    try:
        await worker.start(Path("fake"), {"audio_path": "fake", "text": "fake"})
        with pytest.raises(WorkerFailure, match=pattern):
            await worker.synthesize(utterance)
        await until(lambda: not worker.process.is_alive())
        with pytest.raises(WorkerFailure):
            await worker.synthesize("later")
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_worker_startup_failure_cleans_up():
    worker = WorkerClient(engine_factory=ProcessEngine)
    with pytest.raises(WorkerFailure):
        await worker.start(Path("fail"), {"audio_path": "fake", "text": "fake"})
    assert not worker.process.is_alive()


@pytest.mark.asyncio
async def test_idle_worker_death_is_detected_without_another_message():
    worker = WorkerClient(engine_factory=ProcessEngine)
    failures = []
    worker.on_failure = failures.append
    try:
        await worker.start(Path("fake"), {"audio_path": "fake", "text": "fake"})
        worker.process.terminate()
        await until(lambda: bool(failures), timeout=4)
        assert worker.failed
    finally:
        await worker.close()
