import io
import json
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit

import pytest
import yaml

from tools.check_public_files import candidate_files, check_content, check_repository
from tools import check_secrets, install_gitleaks

ROOT = Path(__file__).resolve().parents[1]


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root)


@pytest.mark.parametrize("name", [".env", ".env.local", "voices/reference.wav", "voices/VOICE.WAV",
    "recording.flac", "weights/model.safetensors", "presets/person/preset.json", "reports/run/events.jsonl",
    "user_settings.json", "runtime/preview-text.txt", "keys/private.pem", "dist/73Bot_Colab.zip"])
def test_private_files_cannot_be_published_even_as_text(name):
    assert check_content(name, b"not a real private value")


def test_gitignore_and_forced_private_file_detection(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_bytes((ROOT / ".gitignore").read_bytes())
    (tmp_path / "README.md").write_text("public", encoding="utf-8")
    (tmp_path / ".env.local").write_text("placeholder", encoding="utf-8")
    (tmp_path / "reference.wav").write_bytes(b"private recording")
    names = {p.name for p in candidate_files(tmp_path)}
    assert names == {".gitignore", "README.md"}
    git(tmp_path, "add", "-f", ".env.local", "reference.wav")
    errors = check_repository(tmp_path)
    assert any(".env.local" in error for error in errors)
    assert any("reference.wav" in error for error in errors)
    assert all("placeholder" not in error for error in errors)
    (tmp_path / "reference.wav").unlink()
    assert "reference.wav" not in {p.name for p in candidate_files(tmp_path)}


@pytest.mark.parametrize("change", ["output", "count", "attachment", "widgets", "cell_widgets"])
def test_saved_notebook_data_is_rejected(change):
    notebook = json.loads((ROOT / "notebooks/73Bot_Colab.ipynb").read_text(encoding="utf-8"))
    assert check_content("notebook.ipynb", json.dumps(notebook).encode()) == []
    cell = next(c for c in notebook["cells"] if c["cell_type"] == "code")
    if change == "output":
        cell["outputs"] = [{"output_type": "stream", "text": "private"}]
    elif change == "count":
        cell["execution_count"] = 1
    elif change == "attachment":
        notebook["cells"][0]["attachments"] = {"recording": {"audio/wav": "data"}}
    elif change == "widgets":
        notebook["metadata"]["widgets"] = {"saved_upload": "data"}
    else:
        cell["metadata"]["widget_state"] = {"saved_upload": "data"}
    assert check_content("notebook.ipynb", json.dumps(notebook).encode())


def test_public_tree_and_relative_document_links():
    assert check_repository(ROOT) == []
    for path in candidate_files(ROOT):
        if path.suffix != ".md":
            continue
        for link in re.findall(r"\[[^\]]*\]\(([^\s)]+)\)", path.read_text(encoding="utf-8")):
            parsed = urlsplit(link)
            if not parsed.scheme and parsed.path:
                target = (path.parent / unquote(parsed.path)).resolve()
                assert target.is_relative_to(ROOT) and target.exists(), (path.name, link)


def test_gitleaks_failure_output_never_contains_matched_value(tmp_path, monkeypatch, capsys):
    report = tmp_path / "report.json"
    secret = "do-not-expose-this-value"
    report.write_text(json.dumps([{"File": "example.txt", "StartLine": 4, "RuleID": "example",
                                   "Commit": "abc", "Secret": secret, "Match": secret}]))
    monkeypatch.setattr(check_secrets.subprocess, "run",
                        lambda *a, **kw: SimpleNamespace(returncode=1, stdout=secret, stderr=secret))
    assert check_secrets.scan("tool", "dir", tmp_path, tmp_path / "config", report) == 1
    output = capsys.readouterr().out
    assert "example.txt" in output and secret not in output


def test_gitleaks_download_hash_mismatch_never_installs(tmp_path, monkeypatch):
    monkeypatch.setattr(install_gitleaks.platform, "system", lambda: "Linux")
    monkeypatch.setattr(install_gitleaks.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(install_gitleaks.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(b"corrupt"))
    with pytest.raises(RuntimeError, match="SHA-256"):
        install_gitleaks.install(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_ci_uses_read_only_permissions_pinned_actions_and_full_secret_history():
    workflow = yaml.safe_load((ROOT / ".github/workflows/checks.yml").read_text(encoding="utf-8"))
    assert workflow["permissions"] == {"contents": "read"}
    assert "pull_request_target" not in workflow["on"]
    for job in workflow["jobs"].values():
        assert not job.get("permissions")
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", step["uses"])
            if step.get("uses", "").startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] is False
    checkout = workflow["jobs"]["secrets"]["steps"][0]
    assert checkout["with"]["fetch-depth"] == 0
