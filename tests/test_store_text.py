import array
import json
import math
import wave

import pytest

from colab73.config import Store
from colab73.locking import RuntimeLock
from colab73.metrics import summarize
from colab73.text import normalize, split_text


@pytest.fixture
def recording(tmp_path):
    path = tmp_path / "source.wav"
    samples = array.array("h", [int(8000 * math.sin(i * math.tau * 440 / 24000)) for i in range(6 * 24000)])
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(samples.tobytes())
    return path


@pytest.mark.parametrize("transcript", ["テスト用の録音です。", "", " \n\t "])
def test_registration_survives_source_deletion_and_new_session(tmp_path, recording, transcript):
    store = Store(tmp_path / "drive")
    preset = store.register(recording, "自分", transcript, 1, 5)
    store.save_settings({"preset_id": preset["id"], "volume": .8, "dictionary": {"BOT": "ボット"},
                         "DISCORD_BOT_TOKEN": "must-not-persist"})
    recording.unlink()
    restored = Store(store.root)
    assert restored.preset()["text"] == transcript.strip()
    with wave.open(restored.preset()["audio_path"], "rb") as wav:
        assert wav.getnframes() / wav.getframerate() == 4
    assert "must-not-persist" not in (store.root / "settings.json").read_text(encoding="utf-8")
    assert restored.settings()["dictionary"] == {"BOT": "ボット"}


def test_registration_without_transcript_argument(tmp_path, recording):
    store = Store(tmp_path / "drive")
    preset = store.register(recording, "録音のみ", start=1, end=5)
    assert Store(store.root).preset(preset["id"])["text"] == ""


def test_bad_presets_and_missing_audio_are_rejected(tmp_path, recording):
    store = Store(tmp_path / "drive")
    with pytest.raises(ValueError, match="名前"):
        store.register(recording, "", "")
    with pytest.raises(ValueError, match="書き起こし"):
        store.register(recording, "自分", 123)
    with pytest.raises(ValueError, match="3〜30秒"):
        store.register(recording, "自分", "短い", 0, 1)
    with pytest.raises(ValueError):
        store.preset("../../outside")
    with pytest.raises(ValueError):
        store.save_settings({"volume": float("nan")})
    with pytest.raises(ValueError):
        store.save_settings({"dictionary": {"": "空キー"}})


def test_text_cleaning_and_longest_non_recursive_dictionary():
    text = "太郎さん ```python\nprint('secret')\n``` https://example.com/a <:smile:123> HP回復 HP <@123>"
    result = normalize(text, {"HP回復": "体力回復", "HP": "エイチピー", "体力": "変更されない"})
    assert result == "太郎さん URL smile 体力回復 エイチピー"
    assert "secret" not in result
    assert normalize("```unfinished", {}) == ""


def test_split_preserves_contents_and_bounds():
    text = "了解。" + "あ" * 97 + "！次の文章です。"
    chunks = split_text(text)
    assert "".join(chunks) == text
    assert all(0 < len(c) <= 40 for c in chunks)
    assert chunks[0] == "了解。"


def test_os_lock_is_exclusive_and_reusable(tmp_path):
    path = tmp_path / "runtime.lock"
    with RuntimeLock(path):
        with pytest.raises(RuntimeError, match="実行中"):
            with RuntimeLock(path):
                pass
    with RuntimeLock(path):
        pass


def test_latency_report_keeps_slow_outlier():
    result = summarize([1.0] * 19 + [6.0])
    assert result["p95"] == 1
    assert result["max"] == 6
    assert result["all_within_5s"] is False
    assert summarize([])["all_within_5s"] is None
