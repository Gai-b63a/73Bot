from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from colab73.cache import prepare_model
from colab73.config import MODEL_ID, read_json
from colab73.controller import Controller
from colab73.locking import RuntimeLock


def test_cache_pins_revision_and_retries_incomplete_download(tmp_path, monkeypatch):
    revision = "a" * 40
    calls = []
    drive, local = tmp_path / "drive", tmp_path / "local"

    def download(model_id, revision, local_dir):
        calls.append((model_id, revision))
        folder = Path(local_dir)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "config.json").write_text("{}")
        if len(calls) == 1:
            raise OSError("interrupted")
        (folder / "model.safetensors").write_bytes(b"complete weights")

    api = SimpleNamespace(model_info=lambda model: SimpleNamespace(sha=revision))
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(HfApi=lambda: api, snapshot_download=download))
    with pytest.raises(OSError):
        prepare_model(drive, local)
    assert read_json(drive / "model.json") == {"id": MODEL_ID, "revision": revision}
    assert not (drive / "models" / revision / ".73bot-complete.json").exists()
    ready = prepare_model(drive, local)
    assert (ready / "model.safetensors").read_bytes() == b"complete weights"
    assert len(calls) == 2
    other = prepare_model(drive, tmp_path / "other-session")
    assert (other / "model.safetensors").read_bytes() == b"complete weights"
    assert len(calls) == 2


def test_controller_detects_other_runtime_and_blocks_settings(tmp_path):
    controller = Controller(tmp_path / "drive", tmp_path / "local")
    with RuntimeLock(controller.local_root / "runtime.lock"):
        assert controller.status()["process_running"] is True
        with pytest.raises(RuntimeError):
            controller.save_settings({"volume": .5})
        with pytest.raises(RuntimeError):
            controller.stop()
    assert controller.status()["process_running"] is False


def test_controller_rejects_missing_voice_and_invalid_mode(tmp_path):
    controller = Controller(tmp_path / "drive", tmp_path / "local")
    with pytest.raises(ValueError, match="プリセット"):
        controller.start("bot", token="not-used")
    with pytest.raises(ValueError, match="モード"):
        controller.start("invalid")


def test_controller_rejects_missing_token_before_starting(tmp_path, monkeypatch):
    controller = Controller(tmp_path / "drive", tmp_path / "local")
    monkeypatch.setattr(controller.store, "preset", lambda: {"name": "登録済みの声"})
    with pytest.raises(ValueError, match="トークン"):
        controller.start("bot")
    assert controller.process is None
