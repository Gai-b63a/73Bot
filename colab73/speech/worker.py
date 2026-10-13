"""Async requests to a single GPU process; cancelled replies are drained."""
from __future__ import annotations

import asyncio
import multiprocessing as mp
from pathlib import Path
import queue
import time

from .qwen import QwenEngine
from .process import _worker_main


class WorkerFailure(RuntimeError):
    pass


class WorkerClient:
    def __init__(self, timeout=60.0, startup_timeout=300.0, engine_factory=QwenEngine):
        self.timeout = timeout
        self.startup_timeout = startup_timeout
        self.engine_factory = engine_factory
        self.process = None
        self.incoming = self.outgoing = None
        self.pending = asyncio.Queue()
        self.pump = None
        self.busy = False
        self.failed = None
        self.closed = False
        self.info = {}
        self.on_failure = None

    async def start(self, model_path: Path, preset: dict):
        ctx = mp.get_context("spawn")
        self.incoming, self.outgoing = ctx.Queue(), ctx.Queue()
        self.process = ctx.Process(target=_worker_main,
                                   args=(self.incoming, self.outgoing, str(model_path), preset, self.engine_factory),
                                   daemon=True)
        self.process.start()
        try:
            kind, data = await self._receive(self.startup_timeout)
            if kind != "ready":
                raise WorkerFailure(data)
            self.info = data
            self.pump = asyncio.create_task(self._pump())
            return data
        except BaseException:
            await self.close()
            raise

    async def _receive(self, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                return self.outgoing.get_nowait()
            except queue.Empty:
                if not self.process.is_alive():
                    # Queue feeder may finish shortly after process exit.
                    await asyncio.sleep(0.05)
                    try:
                        return self.outgoing.get_nowait()
                    except queue.Empty:
                        raise WorkerFailure("音声ワーカーが終了しました。Colabから再起動してください。")
                await asyncio.sleep(0.02)
        raise WorkerFailure(f"音声処理が{timeout:g}秒を超えました。Colabから再起動してください。")

    async def synthesize(self, text):
        if self.closed or self.failed:
            raise WorkerFailure(self.failed or "音声ワーカーは停止しています。")
        future = asyncio.get_running_loop().create_future()
        await self.pending.put((text, future))
        # Cancelling the consumer cancels only its future; the pump drains the
        # response before sending another request, avoiding response mix-ups.
        return await future

    async def _pump(self):
        active = None
        try:
            while True:
                try:
                    text, active = await asyncio.wait_for(self.pending.get(), timeout=1)
                except asyncio.TimeoutError:
                    if not self.process.is_alive():
                        raise WorkerFailure("音声ワーカーが終了しました。Colabから再起動してください。")
                    continue
                if active.cancelled():
                    continue
                self.busy = True
                self.incoming.put(text)
                kind, data = await self._receive(self.timeout)
                if kind != "audio":
                    raise WorkerFailure(data)
                if not active.done():
                    active.set_result(data)
                self.busy = False
        except WorkerFailure as exc:
            self.failed = str(exc)
            if active is not None and not active.done():
                active.set_exception(exc)
            self._fail_pending(exc)
            await self._stop_process()
            if self.on_failure:
                self.on_failure(self.failed)
        finally:
            self.busy = False
            if active is not None and not active.done():
                active.cancel()

    def _fail_pending(self, exc):
        while not self.pending.empty():
            _, future = self.pending.get_nowait()
            if not future.done():
                future.set_exception(exc)

    async def _stop_process(self):
        if self.process is not None:
            if self.process.is_alive():
                self.incoming.put(None)
                await asyncio.to_thread(self.process.join, 1)
            if self.process.is_alive():
                self.process.terminate()
                await asyncio.to_thread(self.process.join, 3)
            if self.process.is_alive():
                self.process.kill()
                await asyncio.to_thread(self.process.join, 3)

    async def close(self):
        self.closed = True
        if self.pump is not None:
            self.pump.cancel()
            await asyncio.gather(self.pump, return_exceptions=True)
        self._fail_pending(WorkerFailure("音声ワーカーを停止しました。"))
        await self._stop_process()
        for pipe in (self.incoming, self.outgoing):
            if pipe is not None:
                pipe.cancel_join_thread()
                pipe.close()
