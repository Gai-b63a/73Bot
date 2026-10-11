"""Download once to Drive, use local files for inference."""
from pathlib import Path
import shutil

from .config import MODEL_ID, read_json, write_json


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
        print("モデルをDriveへ保存しています。初回は時間がかかります。", flush=True)
        snapshot_download(MODEL_ID, revision=revision, local_dir=str(cached))
        write_json(cached / ".73bot-complete.json", {"revision": revision})
    local = local_root / "models" / revision
    if not (local / ".73bot-complete.json").exists():
        print("モデルをColabの一時ディスクへコピーしています。", flush=True)
        local.mkdir(parents=True, exist_ok=True)
        # Copy the completion marker last, so an interrupted copy is retried.
        shutil.copytree(cached, local, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".cache", ".73bot-complete.json"))
        write_json(local / ".73bot-complete.json", {"revision": revision})
    return local
