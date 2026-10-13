"""Operator logs reveal receipt and health without retaining Discord content."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import sys

import pytest

from colab73.controller import Controller
from colab73.runtime import activity
from colab73.transport.bot import ColabBot
from colab73.ui.panel import NotebookPanel
from colab73.ui.colab import ColabRefresh
from colab73 import setup


@pytest.fixture
def activity_file(tmp_path):
    path = tmp_path / "activity.log"
    activity.configure(path)
    yield path
    for handler in list(activity.log.handlers):
        activity.log.removeHandler(handler)
        handler.close()


def test_log_tail_rotation_and_escaping(activity_file, tmp_path):
    for index in range(105):
        activity.log.info("受信 %s", index)
    lines = activity.read(activity_file).splitlines()
    assert len(lines) == 100 and lines[0].endswith("受信 5")
    assert len(lines[0].split()[0]) == 8
    controller = Controller(tmp_path / "data", tmp_path / "runtime")
    controller.paths.activity.write_text("<script>test</script>", encoding="utf-8")
    panel = NotebookPanel(controller)
    assert panel.activity in panel.widget.children
    assert panel.activity not in panel.details.children[0].children
    assert "&lt;script&gt;" in panel.activity.value
    changed = Mock()
    panel.activity.observe(changed, names="value")
    panel.refresh()
    changed.assert_not_called()
    assert controller.activity_logs() == "<script>test</script>"
    for _ in range(1500):
        activity.log.info("受信 " + "x" * 100)
    assert activity_file.stat().st_size < 128_000
    assert activity_file.with_name("activity.log.1").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("case,expected", [
    ("accepted", "読み上げ受付"), ("full", "待ち行列が満杯"),
    ("empty", "本文なし"), ("disconnected", "VC未接続"),
    ("stopped", "読み上げ停止中"), ("failed", "読み上げ停止中"),
    ("other", None), ("bot", None), ("dm", None),
])
async def test_receipt_results_and_private_content(activity_file, tmp_path, case, expected):
    worker = SimpleNamespace(on_failure=None, busy=False, pending=asyncio.Queue(), failed=None)
    bot = ColabBot(worker, {"volume": 1, "dictionary": {}}, {"name": "voice"}, Mock())
    reader = SimpleNamespace(closed=case == "stopped", is_idle=True,
                             submit=Mock(return_value=case != "full"), close=AsyncMock())
    bot.readers[1] = reader
    bot.monitored[1] = 2
    if case == "failed":
        bot.reading_error = "private failure"
    message = SimpleNamespace(
        guild=None if case == "dm" else SimpleNamespace(id=1, voice_client=SimpleNamespace(is_connected=lambda: case != "disconnected")),
        author=SimpleNamespace(bot=case == "bot", name="private-user"),
        channel=SimpleNamespace(id=4 if case == "other" else 2, send=AsyncMock()),
        clean_content="```code```" if case == "empty" else "private-message", id=55,
    )
    try:
        await bot.on_message(message)
        result = activity_file.read_text(encoding="utf-8")
        assert (expected in result) if expected else result == ""
        assert "private" not in result and "55" not in result.split(" ", 1)[-1]
        assert reader.submit.call_count == (1 if case in {"accepted", "full"} else 0)
    finally:
        await bot.close()


@pytest.mark.asyncio
async def test_failure_keeps_monitored_target_for_receipt_logging(activity_file):
    worker = SimpleNamespace(on_failure=None, busy=False, pending=asyncio.Queue(), failed=None)
    bot = ColabBot(worker, {"volume": 1, "dictionary": {}}, {"name": "voice"}, Mock())
    bot.readers[1] = SimpleNamespace(close=AsyncMock())
    bot.monitored[1] = 2
    try:
        await bot.reader_error(1, "private-error")
        assert bot.monitored == {1: 2}
        bot.worker_failed("private-error")
        await asyncio.gather(*list(bot._background))
        assert bot.monitored == {1: 2} and not bot.readers
        assert "private" not in activity.read(activity_file)
    finally:
        await bot.close()


def test_bridge_only_resends_activity_on_changes(tmp_path):
    controller = Controller(tmp_path / "data", tmp_path / "runtime")
    panel = NotebookPanel(controller)
    bridge = ColabRefresh(panel, SimpleNamespace(register_callback=Mock(), eval_js=Mock()))
    panel.activity.send_state = Mock()
    bridge.refresh(0)
    bridge.refresh(0)
    assert panel.activity.send_state.call_count == 1
    controller.paths.activity.write_text("受信", encoding="utf-8")
    bridge.refresh(0)
    assert panel.activity.send_state.call_count >= 2
    count = panel.activity.send_state.call_count
    bridge.refresh(0)
    assert panel.activity.send_state.call_count == count


def test_notebook_has_observed_colab_runtime_pin():
    root = Path(__file__).resolve().parents[1]
    metadata = json.loads((root / "notebooks/73Bot_Colab.ipynb").read_text(encoding="utf-8"))["metadata"]
    assert metadata["colab"]["runtime_attributes"] == {"runtime_version": "2026.07"}
    assert metadata["colab"]["gpuType"] == "T4" and metadata["accelerator"] == "GPU"


def test_wrong_python_stops_before_installs(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.sys, "version_info", (3, 13, 0))
    run = Mock()
    monkeypatch.setattr(setup.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="2026.07"):
        setup.prepare_environment(tmp_path, tmp_path / "runtime")
    run.assert_not_called()


def test_start_resets_activity_but_stop_preserves_it(tmp_path, monkeypatch):
    controller = Controller(tmp_path / "data", tmp_path / "runtime")
    monkeypatch.setattr(controller.store, "preset", lambda: {})
    process = Mock()
    process.poll.return_value = None
    monkeypatch.setattr("colab73.controller.subprocess.Popen", lambda *args, **kwargs: process)
    controller.paths.activity.write_text("old", encoding="utf-8")
    controller.start("preview")
    assert controller.activity_logs() == ""
    controller.paths.activity.write_text("received", encoding="utf-8")
    controller.stop()
    assert controller.activity_logs() == "received"


def test_qwen_load_uses_sdpa_without_flash_attention(monkeypatch):
    from colab73.speech.qwen import QwenEngine
    cuda = SimpleNamespace(is_available=lambda: True, get_device_capability=lambda: (7, 5),
                           is_bf16_supported=lambda: False, get_device_name=lambda: "test GPU")
    torch = SimpleNamespace(cuda=cuda, float32="FP32", bfloat16="BF16", __version__="test")
    model = SimpleNamespace(from_pretrained=Mock(return_value=Mock()))
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "qwen_tts", SimpleNamespace(Qwen3TTSModel=model))
    monkeypatch.setattr("colab73.speech.qwen.importlib.metadata.version", lambda name: "0.1.1")
    info = QwenEngine().load("fake-model")
    assert model.from_pretrained.call_args.kwargs["attn_implementation"] == "sdpa"
    assert info["attention"] == "sdpa" and info["dtype"] == "FP32"


def test_rotated_activity_is_not_a_public_file():
    from tools.check_public_files import private_path
    assert private_path("activity.log.1")
