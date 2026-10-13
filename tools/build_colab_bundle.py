"""Package the editable Colab notebook without generating or changing it."""
from __future__ import annotations

import argparse
from pathlib import Path
import zipfile

try:
    from tools.check_public_files import check_content
except ModuleNotFoundError:
    from check_public_files import check_content

REPO = Path(__file__).resolve().parents[1]


def build_bundle(output_root: Path, notebook_path: Path | None = None) -> Path:
    notebook_path = notebook_path or REPO / "notebooks/73Bot_Colab.ipynb"
    notebook = notebook_path.read_bytes()
    errors = check_content("notebooks/73Bot_Colab.ipynb", notebook)
    if errors:
        raise ValueError("公開前にノートブックを確認してください: " + " / ".join(errors))
    files = [*sorted((REPO / "colab73").rglob("*.py")), REPO / "requirements-colab.txt",
             *[REPO / name for name in ("README.md", "LICENSE", "THIRD_PARTY.md", "SECURITY.md", "CONTRIBUTING.md")],
             *sorted((REPO / "docs").glob("*.md")), *sorted((REPO / "docs/images").glob("*.png")),
             REPO / "docs/images/manifest.json"]
    payloads = [("notebooks/73Bot_Colab.ipynb", notebook)]
    for file in files:
        name, data = file.relative_to(REPO).as_posix(), file.read_bytes()
        errors = check_content(name, data)
        if errors:
            raise ValueError(f"{name}: " + " / ".join(errors))
        payloads.append((name, data))
    bundle = output_root / "dist/73Bot_Colab.zip"
    bundle.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in payloads:
            archive.writestr(name, data)
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=REPO)
    args = parser.parse_args()
    build_bundle(args.output_dir.resolve())


if __name__ == "__main__":
    main()
