import asyncio
import io
import json
import hashlib
from pathlib import Path
import subprocess
import struct
import zlib
from types import SimpleNamespace
from unittest.mock import Mock
import wave

import pytest

from colab73.controller import Controller
from colab73.notebook_ui import NotebookPanel, show_panel
from colab73.session import session_voice
from colab73 import setup
from tools.check_public_files import check_content

ROOT = Path(__file__).resolve().parents[1]


def recording(seconds=5, silent=False):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        # A synthetic waveform avoids using private or downloaded recordings.
        wav.writeframes((b"\0\0" if silent else b"\xe8\x03\x18\xfc") * (24000 * seconds // (1 if silent else 2)))
    return output.getvalue()


@pytest.fixture
def controller(tmp_path):
    return Controller(tmp_path / "data", tmp_path / "runtime")


def test_upload_defaults_selects_and_reuses_voice(controller):
    voice = session_voice(controller)
    first = voice.upload("voice.wav", recording(12))
    assert first["duration_seconds"] == 10
    assert first["text"] == ""
    assert controller.store.preset()["id"] == first["id"]
    assert session_voice(controller) is voice
    assert voice.prepare()["id"] == first["id"]
    short = voice.upload("short.wav", recording(5))
    assert short["duration_seconds"] == 5
    assert voice.source.is_relative_to(controller.local_root)


def test_new_session_requires_upload_even_if_old_data_exists(controller):
    session_voice(controller).upload("voice.wav", recording())
    new = Controller(controller.store.root, controller.local_root)
    with pytest.raises(ValueError, match="アップロード"):
        session_voice(new).prepare()


def test_failed_upload_clears_selection_and_can_correct_crop(controller):
    voice = session_voice(controller)
    voice.upload("valid.wav", recording())
    with pytest.raises(ValueError, match="無音"):
        voice.upload("silence.wav", recording(silent=True))
    assert controller.store.settings()["preset_id"] is None
    assert voice.preset is None
    with pytest.raises(ValueError, match="3〜30秒"):
        voice.prepare(0, 2)
    preset = voice.upload("long.wav", recording(35))
    cropped = voice.apply(5, 12, "こんにちは", .6, {"BOT": "ボット"})
    assert cropped["id"] != preset["id"]
    assert cropped["duration_seconds"] == 7 and cropped["text"] == "こんにちは"
    assert controller.store.settings()["volume"] == .6
    assert not Path(preset["audio_path"]).exists()


@pytest.mark.parametrize("name,data", [("empty.wav", b""), ("file.exe", b"x")])
def test_invalid_upload_rejected(controller, name, data):
    with pytest.raises(ValueError):
        session_voice(controller).upload(name, data)
    assert session_voice(controller).source is None


@pytest.mark.asyncio
async def test_ui_reexecution_stop_restart_and_locked_controls(controller, monkeypatch):
    panel = show_panel(controller)
    try:
        assert show_panel(controller) is panel
        assert panel.preview.disabled
        await panel.accept_upload({"name": "voice.wav", "content": recording()})
        panel.refresh()
        voice_id = panel.voice.preset["id"]
        running = {"value": False}
        controller.status = lambda: {"process_running": running["value"], "phase": "稼働中" if running["value"] else "停止"}
        def start(*args, **kwargs):
            controller.require_stopped()
            running["value"] = True
            controller.process = SimpleNamespace(poll=lambda: None if running["value"] else 0)
        controller.start = Mock(side_effect=start)
        controller.stop = Mock(side_effect=lambda: running.update(value=False))
        panel.volume.value = .7
        panel.dictionary.value = '{"BOT":"ボット"}'
        await panel.launch("preview")
        panel.refresh()
        assert all(item.disabled for item in panel.editable)
        assert not panel.stop.disabled
        with pytest.raises(RuntimeError):
            panel.voice.upload("other.wav", recording())
        assert show_panel(controller) is panel
        await panel.stop_process()
        panel.refresh()
        assert not panel.upload.disabled
        panel.dictionary.value = '[]'
        with pytest.raises(ValueError, match="読み辞書"):
            await panel.launch("preview")
        assert controller.start.call_count == 1
        panel.dictionary.value = '{"BOT":"ボット"}'
        await panel.launch("preview")
        assert panel.voice.preset["id"] == voice_id
        assert controller.start.call_count == 2
        assert controller.store.settings()["dictionary"] == {"BOT": "ボット"}
        await panel.stop_process()
    finally:
        panel.monitor.cancel()
        await asyncio.gather(panel.monitor, return_exceptions=True)


@pytest.mark.asyncio
async def test_upload_error_guides_crop_and_stale_preview_is_not_restored(controller, tmp_path):
    panel = NotebookPanel(controller)
    panel.schedule(lambda: panel.accept_upload({"name": "silent.wav", "content": recording(silent=True)}))
    await panel.operation
    assert "区間を調整" in panel.message.value and not panel.busy
    assert controller.store.settings()["preset_id"] is None
    old = tmp_path / "old.wav"
    old.write_bytes(recording())
    controller.status = lambda: {"process_running": False, "phase": "終了", "mode": "preview", "audio": str(old)}
    await panel.accept_upload({"name": "valid.wav", "content": recording()})
    panel.refresh()
    assert panel.last_audio == str(old)
    new = tmp_path / "new.wav"
    new.write_bytes(recording())
    controller.status = lambda: {"process_running": False, "phase": "終了", "mode": "preview", "audio": str(new)}
    panel.refresh()
    assert panel.last_audio == str(new)
    assert "試聴が完了" in panel.state.value


def test_setup_missing_gpu_stops_before_installing(controller, monkeypatch):
    calls = []
    def fail(command, **kwargs):
        calls.append(command)
        kwargs["stdout"].write("GPU unavailable\n")
        raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(setup.subprocess, "run", fail)
    with pytest.raises(RuntimeError, match="GPUが使えません"):
        setup.prepare_environment(ROOT, controller.local_root, progress=lambda text: None)
    assert len(calls) == 1
    assert "GPU unavailable" in (controller.local_root / "setup.log").read_text()


def test_setup_progress_is_quiet_and_requirements_are_verified(controller, monkeypatch):
    calls, messages = [], []
    monkeypatch.setattr(setup.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs)))
    setup.prepare_environment(ROOT, controller.local_root, progress=messages.append)
    assert len(messages) == 3
    assert all(call[1]["stdout"].name.endswith("setup.log") and call[1]["stderr"] == subprocess.STDOUT for call in calls)
    assert any("ffmpeg" in call[0] and "libopus0" in call[0] for call in calls)
    assert "davey" in calls[-1][0][-1]


def test_one_hidden_preparation_cell_has_no_source_or_drive_inputs():
    notebook = json.loads((ROOT / "notebooks/73Bot_Colab.ipynb").read_text(encoding="utf-8"))
    cells = [c for c in notebook["cells"] if c["cell_type"] == "code"]
    assert len(cells) == 1 and cells[0]["metadata"]["cellView"] == "form"
    code = "".join(cells[0]["source"])
    assert "#@title 準備して操作画面を開く" in code
    assert "#@param" not in code and "drive.mount" not in code and "ZIP_PATH" not in code
    assert 'if "controller" not in globals()' in code
    assert '"master"' in code and "Gai-b63a/73Bot.git" in code
    assert "setup.log" in code


def test_preparation_cell_rerun_does_not_install_or_replace_controller(controller, monkeypatch):
    import colab73.notebook_ui
    show = Mock()
    monkeypatch.setattr(colab73.notebook_ui, "show_panel", show)
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=AssertionError("unexpected setup")))
    notebook = json.loads((ROOT / "notebooks/73Bot_Colab.ipynb").read_text(encoding="utf-8"))
    code = "".join(next(c for c in notebook["cells"] if c["cell_type"] == "code")["source"])
    scope = {"controller": controller}
    exec(compile(code, "preparation", "exec"), scope)
    exec(compile(code, "preparation", "exec"), scope)
    assert scope["controller"] is controller
    assert show.call_count == 2
    subprocess.run.assert_not_called()


@pytest.mark.asyncio
async def test_busy_ui_does_not_accept_a_second_operation(controller):
    panel = NotebookPanel(controller)
    entered, finish = asyncio.Event(), asyncio.Event()
    second = Mock()
    async def work():
        entered.set()
        await finish.wait()
    panel.schedule(work)
    await entered.wait()
    assert panel.busy and panel.upload.disabled
    panel.schedule(second)
    finish.set()
    await panel.operation
    second.assert_not_called()
    assert not panel.busy


def test_registered_image_with_private_metadata_is_rejected(tmp_path, monkeypatch):
    from tools import check_public_files
    data = (ROOT / "docs/images/token.png").read_bytes()
    body = b"comment\0hidden data"
    kind = b"tEXt"
    chunk = struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    modified = data[:-12] + chunk + data[-12:]
    manifest = json.loads((ROOT / "docs/images/manifest.json").read_text())
    manifest["images"]["token.png"]["sha256"] = hashlib.sha256(modified).hexdigest()
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(check_public_files, "MANIFEST", path)
    assert check_content("docs/images/token.png", modified)


def test_guide_images_only_exact_registered_png_without_metadata():
    images = list((ROOT / "docs/images").glob("*.png"))
    assert len(images) == 6
    for path in images:
        data = path.read_bytes()
        assert not check_content("docs/images/" + path.name, data)
        assert check_content("elsewhere/" + path.name, data)
        assert check_content("docs/images/unknown.png", data)
        assert check_content("docs/images/" + path.name, data + b"hidden private data")
    notebook = (ROOT / "notebooks/73Bot_Colab.ipynb").read_text(encoding="utf-8")
    for path in images:
        assert "master/docs/images/" + path.name in notebook
