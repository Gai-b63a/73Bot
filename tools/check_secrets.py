"""Run Gitleaks on all local history and current publication candidates."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

try:
    from .check_public_files import candidate_files
except ImportError:
    from check_public_files import candidate_files


def scan(executable: str, mode: str, source: Path, config: Path, report: Path) -> int:
    command = [executable, mode, str(source), "--config", str(config), "--redact=100",
               "--report-format=json", "--report-path", str(report), "--no-banner"]
    if mode == "git":
        command.append("--log-opts=--all")
    result = subprocess.run(command, capture_output=True, timeout=180)
    # Do not print raw tool output or matched content, even on tool failure.
    if result.returncode not in (0, 1):
        print(f"Gitleaks {mode}: 検査を実行できませんでした（終了コード{result.returncode}）")
        return 2
    if not report.is_file():
        print(f"Gitleaks {mode}: 検査レポートがありません")
        return 2
    findings = json.loads(report.read_text(encoding="utf-8"))
    for finding in findings:
        safe = {key: finding.get(key) for key in ("File", "StartLine", "RuleID", "Commit")}
        print(json.dumps(safe, ensure_ascii=False))
    if findings or result.returncode:
        print(f"Gitleaks {mode}: {len(findings)}件の検出。値は表示しません。")
        return 1
    print(f"Gitleaks {mode}: OK（検出0件）")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gitleaks", default="gitleaks")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    executable = shutil.which(args.gitleaks)
    if not executable:
        print("Gitleaksがありません。取得後、--gitleaks で実行ファイルを指定してください。")
        return 2
    try:
        shallow = subprocess.check_output(["git", "rev-parse", "--is-shallow-repository"], cwd=root, text=True).strip()
        if shallow != "false":
            print("全履歴の検査には完全なcloneが必要です。浅いcloneでは検査を完了できません。")
            return 2
        with tempfile.TemporaryDirectory(prefix="73bot-secrets-") as temporary:
            folder = Path(temporary)
            config = root / ".gitleaks.toml"
            history = scan(executable, "git", root, config, folder / "history.json")
            snapshot = folder / "current"
            snapshot.mkdir()
            for path in candidate_files(root):
                target = snapshot / path.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
            current = scan(executable, "dir", snapshot, config, folder / "current.json")
            return max(history, current)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"秘密情報の検査に失敗しました: {type(exc).__name__}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
