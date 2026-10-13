"""Cache model weights directly on the session's temporary disk."""
from pathlib import Path

from .contracts import MODEL_ID
from .storage.json import read_json, write_json


def prepare_model(store_root: Path, local_root: Path) -> Path:
    from huggingface_hub import HfApi, snapshot_download
    lock_path = store_root / "model.json"
    if lock_path.exists():
        config = read_json(lock_path)
        if config.get("id") != MODEL_ID:
            raise ValueError("初版で対応するモデルはQwen3-TTS 0.6B Baseのみです。")
        revision = config["revision"]
    else:
        revision = HfApi().model_info(MODEL_ID).sha
        write_json(lock_path, {"id": MODEL_ID, "revision": revision})
    if not isinstance(revision, str) or len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise ValueError("モデルの保存バージョンが不正です。")
    cached = store_root / "models" / revision
    if not (cached / ".73bot-complete.json").exists():
        print("モデルをダウンロードしています。このセッションの初回は時間がかかります。", flush=True)
        snapshot_download(MODEL_ID, revision=revision, local_dir=str(cached))
        write_json(cached / ".73bot-complete.json", {"revision": revision})
    return cached
