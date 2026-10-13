"""Behavior and integration checks for the package boundaries."""
import asyncio
import importlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import zipfile

import pytest

from colab73.application import LaunchOptions, NotebookApplication
from colab73.controller import Controller
from colab73.contracts import RuntimePaths
from colab73.engine import AudioChunk
from colab73.locking import RuntimeLock
from colab73.metrics import Metrics
from colab73.notebook_ui import show_panel
from colab73.runtime import execution
from colab73.runtime.state import StateFile
from colab73.session import session_voice
from tools.build_colab_bundle import build_bundle
from tests.test_session_ui import recording

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("old,new,names", [
    ("config", "storage.store", ["Store", "DEFAULT_SETTINGS"]),
    ("engine", "speech.types", ["AudioChunk", "SpeechEngine"]),
    ("engine", "speech.qwen", ["QwenEngine"]),
    ("worker", "speech.worker", ["WorkerClient", "WorkerFailure"]),
    ("discord_bot", "transport.bot", ["ColabBot"]),
    ("discord_bot", "transport.commands", ["ReadingCommands"]),
    ("discord_bot", "transport.audio", ["PCMSource", "DiscordPlayer", "MeasuredVoiceClient"]),
    ("notebook_ui", "ui.panel", ["NotebookPanel", "show_panel"]),
    ("runner", "runtime.execution", ["main", "run", "cancellable_main"]),
])
def test_existing_imports_are_the_same_classes_and_functions(old, new, names):
    old_module = importlib.import_module("colab73." + old)
    new_module = importlib.import_module("colab73." + new)
    for name in names:
        assert getattr(old_module, name) is getattr(new_module, name)


def test_cold_notebook_and_worker_imports_do_not_load_gpu_or_discord():
    # A fresh process prevents already imported dependencies from hiding a leak.
    code = """
import importlib.abc
import sys
class BlockHeavyImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'torchaudio', 'qwen_tts', 'numpy', 'discord'}:
            raise AssertionError('Unexpected heavy import: ' + fullname)
sys.meta_path.insert(0, BlockHeavyImports())
from colab73.controller import Controller
from colab73.notebook_ui import show_panel
from colab73.setup import prepare_environment
from colab73.runner import run
from colab73.reader import GuildReader
from colab73.worker import WorkerClient
"""
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True, capture_output=True)


def test_bundle_imports_and_cli_work_without_repository_on_path(tmp_path):
    bundle = build_bundle(tmp_path)
    code = """
import sys
sys.path.insert(0, sys.argv[1])
from colab73.controller import Controller
from colab73.notebook_ui import show_panel
from colab73.worker import WorkerClient
from colab73.discord_bot import ColabBot
from colab73.engine import QwenEngine
import colab73
assert sys.argv[1] in colab73.__file__
assert sys.argv[1] in sys.modules[WorkerClient.__module__].__file__
import runpy
sys.argv = ['colab73.runner', '--help']
runpy.run_module('colab73.runner', run_name='__main__')
"""
    result = subprocess.run([sys.executable, "-I", "-c", code, str(bundle)],
                            cwd=tmp_path, capture_output=True, text=True, check=True)
    assert "--mode" in result.stdout and "--store" in result.stdout
    with zipfile.ZipFile(bundle) as archive:
        expected = {p.relative_to(ROOT).as_posix() for p in (ROOT / "colab73").rglob("*.py")}
        assert expected <= set(archive.namelist())


@pytest.fixture
def ready_controller(tmp_path):
    controller = Controller(tmp_path / "data", tmp_path / "runtime")
    session_voice(controller).upload("voice.wav", recording())
    return controller


def options(**changes):
    return LaunchOptions(**{"start": 0, "end": 10, "transcript": "", "volume": 1,
                            "dictionary": "{}", "text": "こんにちは。", **changes})


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"volume": 3}, {"dictionary": "[]"}, {"dictionary": "invalid json"}])
async def test_invalid_launch_settings_do_not_change_voice_or_request_token(ready_controller, changes):
    token = Mock()
    application = NotebookApplication(ready_controller, token_provider=token)
    previous = ready_controller.store.settings()
    source = application.voice.preset["audio_path"]
    ready_controller.start = Mock()
    with pytest.raises(ValueError):
        await application.prepare_launch("bot", options(transcript="変更されない文章", **changes))
    assert ready_controller.store.settings() == previous
    assert application.voice.preset["audio_path"] == source
    token.assert_not_called()
    ready_controller.start.assert_not_called()


@pytest.mark.asyncio
async def test_token_is_requested_only_for_bot_and_not_saved(ready_controller):
    import threading
    notebook_thread = threading.get_ident()
    def get_token():
        assert threading.get_ident() == notebook_thread
        return "synthetic-test-value"
    token = Mock(side_effect=get_token)
    application = NotebookApplication(ready_controller, token_provider=token)
    ready_controller.start = Mock()
    await application.start(await application.prepare_launch("preview", options()))
    await application.start(await application.prepare_launch("benchmark", options()))
    token.assert_not_called()
    prepared = await application.prepare_launch("bot", options())
    assert "synthetic-test-value" not in repr(prepared)
    await application.start(prepared)
    token.assert_called_once_with()
    ready_controller.start.assert_called_with("bot", token="synthetic-test-value", text="こんにちは。")
    assert "synthetic-test-value" not in (ready_controller.store.root / "settings.json").read_text()
    assert application.voice.preset["text"] == ""


def test_report_download_excludes_reference_and_requires_stopped_process(ready_controller):
    application = NotebookApplication(ready_controller)
    with pytest.raises(ValueError, match="測定結果がありません"):
        application.reports_archive()
    report = ready_controller.store.root / "reports" / "run" / "summary.json"
    report.parent.mkdir(parents=True)
    report.write_text('{"count": 1}')
    with RuntimeLock(ready_controller.paths.lock):
        with pytest.raises(RuntimeError):
            application.reports_archive()
    with zipfile.ZipFile(application.reports_archive()) as archive:
        assert archive.namelist() == ["run/summary.json"]
        assert json.loads(archive.read("run/summary.json")) == {"count": 1}


@pytest.mark.asyncio
async def test_repeated_panel_display_keeps_exactly_one_monitor_and_voice(ready_controller):
    panel = show_panel(ready_controller)
    try:
        original_monitor = panel.monitor
        original_voice = panel.voice
        for _ in range(3):
            assert show_panel(ready_controller) is panel
        assert panel.monitor is original_monitor and not original_monitor.done()
        assert panel.voice is original_voice
        original_monitor.cancel()
        await asyncio.gather(original_monitor, return_exceptions=True)
        assert show_panel(ready_controller).monitor is not original_monitor
        assert panel.voice is original_voice
    finally:
        panel.monitor.cancel()
        await asyncio.gather(panel.monitor, return_exceptions=True)


class RuntimeWorker:
    def __init__(self):
        self.info = {}
        self.started = 0
        self.closed = False
        self.fail = False

    async def start(self, path, preset):
        self.started += 1
        self.info = {"gpu": "test-double"}

    async def synthesize(self, text):
        if self.fail:
            raise RuntimeError("synthetic generation failure")
        return AudioChunk(bytes(3840), .02, .1)

    async def close(self):
        self.closed = True


@pytest.fixture
def runtime_setup(ready_controller, monkeypatch):
    worker = RuntimeWorker()
    monkeypatch.setattr(execution, "WorkerClient", lambda: worker)
    monkeypatch.setattr(execution, "prepare_model", lambda *args: Path("fake-model"))
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    ready_controller.paths.preview_text.write_text("こんにちは。", encoding="utf-8")
    return ready_controller, worker


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["preview", "benchmark"])
async def test_modes_share_cleanup_state_and_report_format(runtime_setup, monkeypatch, mode):
    controller, worker = runtime_setup
    async def fake_benchmark(actual, folder):
        assert actual is worker
        return {"synthetic": True}
    monkeypatch.setattr(execution, "benchmark", fake_benchmark)
    await execution.run(SimpleNamespace(store=controller.store.root, local_root=controller.local_root, mode=mode))
    state = controller.status()
    assert state["phase"] == "終了" and state["mode"] == mode
    assert not state["process_running"]
    assert worker.started == 1 and worker.closed
    summary = controller.store.root / "reports" / state["run_id"] / "summary.json"
    assert json.loads(summary.read_text())["environment"]["gpu"] == "test-double"
    if mode == "preview":
        assert Path(state["audio"]).is_file()
        assert json.loads(summary.read_text())["generation_seconds"]["count"] == 1
    else:
        assert state["benchmark"] == {"synthetic": True}


@pytest.mark.asyncio
async def test_runtime_generation_failure_stops_worker_and_records_error(runtime_setup):
    controller, worker = runtime_setup
    worker.fail = True
    with pytest.raises(RuntimeError, match="generation failure"):
        await execution.run(SimpleNamespace(store=controller.store.root, local_root=controller.local_root, mode="preview"))
    state = controller.status()
    assert worker.closed and not state["process_running"]
    assert state["phase"] == "エラー"
    assert (controller.store.root / "reports" / state["run_id"] / "summary.json").is_file()


@pytest.mark.asyncio
async def test_shutdown_failure_still_stops_worker_monitor_and_writes_report(tmp_path):
    paths = RuntimePaths(tmp_path / "runtime")
    state = StateFile(paths)
    folder = paths.run("synthetic")
    metrics = Metrics(folder)
    worker = RuntimeWorker()
    bot = SimpleNamespace(close=AsyncMock(side_effect=RuntimeError("private details")))
    monitor = asyncio.create_task(asyncio.sleep(60))
    status = {"phase": "終了", "mode": "bot"}
    destination = tmp_path / "reports"
    with pytest.raises(RuntimeError):
        await execution.finish_run(worker, bot, monitor, metrics, state, status, folder, destination)
    assert worker.closed and monitor.cancelled()
    assert state.read()["phase"] == "エラー"
    assert "private details" not in state.read()["error"]
    assert (destination / "summary.json").is_file()


@pytest.mark.asyncio
async def test_bot_cancellation_disconnects_and_releases_runtime_lock(runtime_setup, monkeypatch):
    controller, worker = runtime_setup
    entered = asyncio.Event()
    bot = SimpleNamespace(close=AsyncMock(), snapshot=lambda: {"connected": True})
    async def run_bot(actual, token):
        assert actual is bot and token == "synthetic-test-value"
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setitem(sys.modules, "colab73.transport.bot", SimpleNamespace(ColabBot=lambda *args: bot))
    monkeypatch.setattr(execution, "run_discord", run_bot)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "synthetic-test-value")
    task = asyncio.create_task(execution.run(SimpleNamespace(
        store=controller.store.root, local_root=controller.local_root, mode="bot")))
    await asyncio.wait_for(entered.wait(), timeout=3)
    assert controller.status()["process_running"]
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    bot.close.assert_awaited_once()
    assert worker.closed and not controller.status()["process_running"]
    assert controller.status()["phase"] == "停止"
