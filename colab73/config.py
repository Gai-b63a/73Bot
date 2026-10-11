"""Persistent, model-independent voice presets and administrator settings."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid
import wave

MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
DEFAULT_SETTINGS = {"version": 1, "preset_id": None, "volume": 1.0, "dictionary": {}}


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"設定ファイルの形式が不正です: {path.name}")
    return value


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
        source = Path(source).expanduser().resolve(strict=True)
        start = float(start)
        end = float(end) if end is not None else None
        if not math.isfinite(start) or start < 0 or (end is not None and (not math.isfinite(end) or end <= start)):
            raise ValueError("開始・終了秒を確認してください。")
        if end is not None and end - start > 30:
            raise ValueError("声の見本は30秒以内に切り出してください（5〜15秒推奨）。")
        with tempfile.TemporaryDirectory(prefix="73bot-reference-") as temporary:
            output = Path(temporary) / "reference.wav"
            duration = end - start if end is not None else 31
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-ss", str(start), "-i", str(source), "-t", str(duration),
                "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(output),
            ], check=True, capture_output=True, timeout=60)
            with wave.open(str(output), "rb") as wav:
                seconds = wav.getnframes() / wav.getframerate()
                samples = wav.readframes(wav.getnframes())
            if not 3 <= seconds <= 30:
                raise ValueError("見本の長さは3〜30秒にしてください（5〜15秒推奨）。")
            import array
            if not samples or max(abs(n) for n in array.array("h", samples)) < 32:
                raise ValueError("音声が無音、または小さすぎます。別の区間を選んでください。")
            preset_id = uuid.uuid4().hex
            folder = self.root / "presets" / preset_id
            folder.mkdir(parents=True)
            shutil.copyfile(output, folder / "reference.wav")
            value = {"version": 1, "id": preset_id, "name": name.strip(),
                     "text": text.strip(), "duration_seconds": seconds}
            write_json(folder / "preset.json", value)
        return self.preset(preset_id)
