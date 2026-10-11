"""Download a pinned official Gitleaks binary and verify its archive SHA-256."""
import argparse
import hashlib
import io
from pathlib import Path
import platform
import tarfile
import urllib.request
import zipfile

VERSION = "8.30.1"
# From the official gitleaks_8.30.1_checksums.txt release asset.
ARCHIVES = {
    "Linux": ("linux_x64.tar.gz", "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"),
    "Windows": ("windows_x64.zip", "d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e"),
}


def install(output: Path) -> Path:
    system = platform.system()
    if system not in ARCHIVES or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("自動取得はWindows x64 / Linux x64に対応しています。公式バイナリを指定してください。")
    suffix, expected = ARCHIVES[system]
    name = f"gitleaks_{VERSION}_{suffix}"
    output.mkdir(parents=True, exist_ok=True)
    archive_path = output / name
    if archive_path.exists():
        data = archive_path.read_bytes()
    else:
        url = f"https://github.com/gitleaks/gitleaks/releases/download/v{VERSION}/{name}"
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise RuntimeError("GitleaksアーカイブのSHA-256が一致しません。実行を中止します。")
    archive_path.write_bytes(data)
    executable = "gitleaks.exe" if system == "Windows" else "gitleaks"
    # Extract only the named executable, never arbitrary archive paths.
    if system == "Windows":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            binary = archive.read(executable)
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            member = archive.getmember(executable)
            if not member.isfile():
                raise RuntimeError("Gitleaks実行ファイルの形式が不正です。")
            binary = archive.extractfile(member).read()
    target = output / executable
    target.write_bytes(binary)
    target.chmod(0o755)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / ".cache/gitleaks")
    args = parser.parse_args()
    print(install(args.output.resolve()))
