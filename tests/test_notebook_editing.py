import json
from pathlib import Path
import zipfile

import pytest

from tools.build_colab_bundle import build_bundle

ROOT = Path(__file__).resolve().parents[1]


def test_direct_colab_edits_are_packaged_without_regeneration(tmp_path):
    notebook = json.loads((ROOT / "notebooks/73Bot_Colab.ipynb").read_text(encoding="utf-8"))
    notebook["cells"][0]["source"] = ["# 自分で編集した案内\n", "Colabで直接修正できます。\n"]
    notebook["cells"][0]["metadata"]["colab_type"] = "text"
    path = tmp_path / "edited.ipynb"
    path.write_text(json.dumps(notebook, ensure_ascii=False), encoding="utf-8")
    before = path.read_bytes()
    bundle = build_bundle(tmp_path / "bundle", notebook_path=path)
    assert path.read_bytes() == before
    with zipfile.ZipFile(bundle) as archive:
        assert archive.read("notebooks/73Bot_Colab.ipynb") == before


def test_zip_creation_rejects_saved_audio_output(tmp_path):
    notebook = json.loads((ROOT / "notebooks/73Bot_Colab.ipynb").read_text(encoding="utf-8"))
    cell = next(c for c in notebook["cells"] if c["cell_type"] == "code")
    cell["outputs"] = [{"output_type": "display_data", "data": {"audio/wav": "private"}}]
    path = tmp_path / "executed.ipynb"
    path.write_text(json.dumps(notebook), encoding="utf-8")
    with pytest.raises(ValueError, match="実行結果"):
        build_bundle(tmp_path, notebook_path=path)
    assert not (tmp_path / "dist/73Bot_Colab.zip").exists()
