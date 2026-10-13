"""Model-independent presets and administrator settings."""
from __future__ import annotations

import math
from pathlib import Path
import shutil
import uuid

from .audio import reference_audio
from .json import read_json, write_json

DEFAULT_SETTINGS = {"version": 1, "preset_id": None, "volume": 1.0, "dictionary": {}}


class Store:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def settings(self) -> dict:
        path = self.root / "settings.json"
        return self.validate_settings(read_json(path) if path.exists() else dict(DEFAULT_SETTINGS))

    @staticmethod
    def validate_settings(value: dict) -> dict:
        if value.get("version", 1) != 1:
            raise ValueError("未対応の設定バージョンです。")
        volume = float(value.get("volume", 1))
        if not math.isfinite(volume) or not 0 <= volume <= 2:
            raise ValueError("音量は0〜2で指定してください。")
        dictionary = value.get("dictionary", {})
        if not isinstance(dictionary, dict) or any(
            not isinstance(k, str) or not k or not isinstance(v, str)
            for k, v in dictionary.items()
        ):
            raise ValueError('読み辞書は {"単語": "読み方"} の形式で指定してください。')
        preset_id = value.get("preset_id")
        if preset_id is not None and (not isinstance(preset_id, str) or
                                      len(preset_id) != 32 or
                                      any(c not in "0123456789abcdef" for c in preset_id)):
            raise ValueError("音声プリセットIDが不正です。")
        # Only known fields are saved. In particular, never persist bot credentials.
        return {"version": 1, "preset_id": preset_id, "volume": volume, "dictionary": dictionary}

    def save_settings(self, value: dict) -> dict:
        value = self.validate_settings(value)
        if value["preset_id"]:
            self.preset(value["preset_id"])
        write_json(self.root / "settings.json", value)
        return value

    def preset(self, preset_id: str | None = None) -> dict:
        preset_id = preset_id or self.settings()["preset_id"]
        if not preset_id:
            raise ValueError("音声プリセットを登録・選択してから実行してください。")
        self.validate_settings({"preset_id": preset_id})
        folder = self.root / "presets" / preset_id
        value = read_json(folder / "preset.json")
        name, text = value.get("name", ""), value.get("text", "")
        if (value.get("id") != preset_id or not isinstance(name, str) or not name.strip()
                or not isinstance(text, str)):
            raise ValueError("音声プリセットの内容が不正です。")
        audio = folder / "reference.wav"
        if not audio.is_file():
            raise ValueError("保存済みの参照音声が見つかりません。再登録してください。")
        return {**value, "text": text.strip(), "audio_path": str(audio)}

    def presets(self) -> list[dict]:
        return [self.preset(p.parent.name) for p in sorted((self.root / "presets").glob("*/preset.json"))]

    def register(self, source: str | Path, name: str, text: str = "",
                 start: float = 0, end: float | None = None) -> dict:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("声の名前を入力してください。")
        if not isinstance(text, str):
            raise ValueError("書き起こしは文章または空欄で指定してください。")
        with reference_audio(source, start, end) as (output, seconds):
            preset_id = uuid.uuid4().hex
            folder = self.root / "presets" / preset_id
            folder.mkdir(parents=True)
            shutil.copyfile(output, folder / "reference.wav")
            value = {"version": 1, "id": preset_id, "name": name.strip(),
                     "text": text.strip(), "duration_seconds": seconds}
            write_json(folder / "preset.json", value)
        return self.preset(preset_id)
