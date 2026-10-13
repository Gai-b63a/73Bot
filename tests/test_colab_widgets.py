"""Regressions observed in Colab with already-loaded ipywidgets 7."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import ipywidgets as widgets
import pytest
from traitlets import Bool, Bytes, Dict, Int, List, observe

from colab73.controller import Controller
from colab73.notebook_ui import NotebookPanel
from colab73.ui.colab import ColabRefresh
from colab73.ui.uploads import uploaded_file
from tests.test_session_ui import recording


class LegacyUpload(widgets.DOMWidget):
    """Widgets 7's upload contract, including its read-only computed value."""
    value = Dict(read_only=True)
    data = List(Bytes())
    metadata = List(Dict())
    disabled = Bool(False)
    _counter = Int(0)

    @observe("_counter")
    def update_value(self, change):
        self.set_trait("value", {item["name"]: {"metadata": item, "content": content}
                                 for item, content in zip(self.metadata, self.data)})


@pytest.mark.parametrize("value", [
    {"voice.wav": {"metadata": {"name": "voice.wav"}, "content": b"audio"}},
    ({"name": "voice.wav", "content": memoryview(b"audio")},),
])
def test_uploaded_filename_and_content_work_for_both_versions(value):
    file = uploaded_file(value)
    assert file["name"] == "voice.wav" and bytes(file["content"]) == b"audio"


@pytest.mark.asyncio
@pytest.mark.parametrize("silent", [False, True])
async def test_legacy_upload_finishes_unlocks_and_preserves_original_error(tmp_path, silent):
    controller = Controller(tmp_path / "data", tmp_path / "runtime")
    panel = NotebookPanel(controller)
    legacy = LegacyUpload()
    panel.editable[panel.editable.index(panel.upload)] = legacy
    panel.upload = legacy
    legacy.observe(panel.upload_changed, names="value")
    legacy.data = [recording(silent=silent)]
    legacy.metadata = [{"name": "voice.wav"}]
    legacy._counter = 1
    await panel.operation
    assert not panel.busy and not legacy.disabled
    assert legacy.value == {} and legacy.data == [] and legacy.metadata == []
    assert legacy._counter == 0
    if silent:
        assert "無音" in panel.message.value and "read-only" not in panel.message.value
        assert panel.voice.preset is None
    else:
        assert panel.voice.preset is not None
        assert "音声の準備ができました" in panel.message.value
        assert not panel.preview.disabled and not panel.launch_bot.disabled
        assert panel.reference.outputs[1]["data"]["text/html"].find("<audio") >= 0
        # Uploading the same file again still triggers a fresh operation.
        old = panel.operation
        legacy.data = [recording()]
        legacy.metadata = [{"name": "voice.wav"}]
        legacy._counter = 1
        await panel.operation
        assert panel.operation is not old and panel.voice.preset is not None


@pytest.mark.asyncio
async def test_widgets8_upload_releases_bytes_and_outputs_audio(tmp_path):
    panel = NotebookPanel(Controller(tmp_path / "data", tmp_path / "runtime"))
    data = recording()
    panel.upload.value = ({"name": "voice.wav", "type": "audio/wav", "size": len(data),
                           "content": memoryview(data), "last_modified": datetime.now(timezone.utc)},)
    await panel.operation
    assert not panel.busy and not panel.preview.disabled
    assert panel.upload.value == ()
    assert len(panel.reference.outputs) == 2


def test_colab_requests_deliver_enabled_controls_and_do_not_resend_recording(tmp_path):
    panel = NotebookPanel(Controller(tmp_path / "data", tmp_path / "runtime"))
    output = SimpleNamespace(register_callback=Mock(), eval_js=Mock())
    bridge = ColabRefresh(panel, output)
    bridge.attach()
    first_generation = bridge.generation
    panel.upload.send_state = Mock()
    panel.preview.send_state = Mock()
    panel.reference.send_state = Mock()
    panel.reference.outputs = ({"output_type": "stream", "name": "stdout", "text": "reference"},)
    panel.reference.send_state.reset_mock()
    assert bridge.refresh(first_generation).data == {"active": True}
    assert panel.preview.send_state.call_args.args == ("disabled",)
    assert "value" not in panel.upload.send_state.call_args.args[0]
    assert "data" not in panel.upload.send_state.call_args.args[0]
    panel.reference.send_state.assert_called_once_with("outputs")
    bridge.refresh(first_generation)
    assert panel.reference.send_state.call_count == 1
    panel.reference.outputs = ()
    panel.reference.send_state.reset_mock()
    bridge.refresh(first_generation)
    panel.reference.send_state.assert_called_once_with("outputs")
    bridge.attach()
    panel.preview.send_state.reset_mock()
    assert bridge.refresh(first_generation).data == {"active": False}
    panel.preview.send_state.assert_not_called()
    assert bridge.refresh(bridge.generation).data == {"active": True}
    output.register_callback.assert_called_once()
    script = output.eval_js.call_args.args[0]
    assert "await google.colab.kernel.invokeFunction" in script
    assert ".active === false" in script
