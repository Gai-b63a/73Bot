"""Check the Git publication candidates, including untracked non-ignored files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import subprocess

PRIVATE_DIRS = {
    ".cache", ".venv", "venv", "env", "__pycache__", ".pytest_cache", "dist",
    ".ipynb_checkpoints", "presets", "models", "reports", "runs", "speaker_info",
    "73bot-runtime", "73bot-data",
}
PRIVATE_NAMES = {
    "settings.json", "user_settings.json", "preset.json", "state.json", "model.json",
    "preview-text.txt", "credentials.json", "summary.json",
}
PRIVATE_SUFFIXES = {
    ".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".mp4", ".webm",
    ".safetensors", ".pt", ".pth", ".ckpt", ".onnx", ".bin", ".h5", ".hdf5",
    ".npy", ".npz", ".pkl", ".pickle", ".pem", ".key", ".p12", ".log", ".jsonl",
    ".zip", ".tar", ".gz", ".7z", ".pyc",
}
MAX_TEXT_BYTES = 1024 * 1024


def candidate_files(root: Path) -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=root,
    )
    paths = []
    for name in sorted(set(output.decode("utf-8").split("\0")) - {""}):
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"公開対象にシンボリックリンクを含められません: {name}")
        if path.is_file():  # Tracked deletions are not part of the new tree.
            paths.append(path)
    return paths


def private_path(name: str) -> bool:
    path = PurePosixPath(name.lower())
    return (any(part in PRIVATE_DIRS for part in path.parts)
            or path.name in PRIVATE_NAMES or path.suffix in PRIVATE_SUFFIXES
            or any(part == ".env" or part.startswith(".env.") for part in path.parts)
            or (path.name.startswith("service-account") and path.suffix == ".json"))


def has_widget_state(value) -> bool:
    if isinstance(value, dict):
        return any(key in {"widgets", "widget_state", "application/vnd.jupyter.widget-state+json"}
                   or has_widget_state(item) for key, item in value.items())
    return isinstance(value, list) and any(has_widget_state(item) for item in value)


def check_content(name: str, data: bytes) -> list[str]:
    errors = []
    if private_path(name):
        errors.append("録音・設定・重み・秘密情報・実行生成物のファイルです")
    if len(data) > MAX_TEXT_BYTES:
        return errors + ["公開ソースの上限1MiBを超えています"]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return errors + ["公開ソースはUTF-8のテキストのみ対応しています"]
    if "\0" in text:
        errors.append("バイナリデータを含んでいます")
    if name.endswith(".ipynb"):
        try:
            notebook = json.loads(text)
            if not isinstance(notebook, dict) or not isinstance(notebook.get("cells"), list):
                raise ValueError("invalid notebook")
            if has_widget_state(notebook):
                errors.append("ウィジェットの保存状態を含んでいます")
            for cell in notebook["cells"]:
                if not isinstance(cell, dict):
                    raise ValueError("invalid cell")
                if cell.get("outputs") or cell.get("execution_count") is not None or cell.get("attachments"):
                    errors.append("ノートブックに実行結果・添付データがあります")
                    break
        except (ValueError, TypeError, KeyError):
            errors.append("ノートブックの形式が不正です")
    return errors


def check_repository(root: Path) -> list[str]:
    errors = []
    for path in candidate_files(root):
        name = path.relative_to(root).as_posix()
        # Read at most one byte beyond the size limit; never load a model file.
        with path.open("rb") as source:
            data = source.read(MAX_TEXT_BYTES + 1)
        errors.extend(f"{name}: {message}" for message in check_content(name, data))
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        errors = check_repository(root)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"公開対象の検査を実行できません: {type(exc).__name__}")
        return 2
    for error in errors:
        print(error)
    if not errors:
        print("公開対象ファイルの検査: OK")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
