"""Build the single-cell Colab notebook and the developer distribution bundle."""
import argparse
import json
from pathlib import Path
import zipfile

REPO = Path(__file__).resolve().parents[1]
GITHUB = "https://github.com/Gai-b63a/73Bot"
RAW = "https://raw.githubusercontent.com/Gai-b63a/73Bot/master/"


def markdown(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.strip().splitlines(keepends=True)}


def code(text):
    return {"cell_type": "code", "metadata": {"cellView": "form"}, "execution_count": None,
            "outputs": [], "source": text.strip().splitlines(keepends=True)}


guide = (REPO / "docs" / "discord-setup.md").read_text(encoding="utf-8")
guide = guide.replace("(images/", "(" + RAW + "docs/images/")
cells = [
    markdown("""
# 73Bot — アップロードした声でDiscordを読み上げ

**初回：下の画像付き案内でDiscord BOTとトークンを準備します。**
通常は **GPUを選ぶ → 準備セルの▶を押す → 音声をアップロード → 試聴 → BOTを起動** で使えます。
Google Driveへの接続や保存先の設定は不要です。新しいColabセッションでは音声を再アップロードします。

必要時に手動起動する検証用です。無料ColabのGPU割り当て・稼働時間は保証されません。
5秒目標は未達で、本人の声を使ったColab・Discord VCの通し検証は未実施です。
[検証記録](https://github.com/Gai-b63a/73Bot/blob/master/docs/validation.md)
"""),
    markdown(guide),
    markdown("""
## 2. GPUを選んで準備

「ランタイム → ランタイムのタイプを変更」でGPUを選びます。Python 3.12を使います。
必要なら「過去のランタイム」でPython 3.12の版（2026.07等）を選んでください。

![GPUを選択する場所](https://raw.githubusercontent.com/Gai-b63a/73Bot/master/docs/images/gpu.png)

下の **「準備して操作画面を開く」左の▶** を押してください。初回は数分かかります。
コードの編集は不要です。準備が終わると音声のアップロードと起動ボタンが表示されます。
"""),
    code('''
#@title 準備して操作画面を開く
from pathlib import Path
import html
import subprocess
import sys
from IPython.display import HTML, display

# Keep the same controller and panel when this cell is re-executed.
try:
    if "controller" not in globals():
        project = Path("/content/73Bot")
        runtime_root = Path("/content/73bot-runtime")
        runtime_root.mkdir(parents=True, exist_ok=True)
        print("73Botを準備しています…")
        with (runtime_root / "setup.log").open("w", encoding="utf-8") as setup_log:
            if not project.exists():
                subprocess.run(["git", "clone", "--branch", "master", "--single-branch", "--",
                                "https://github.com/Gai-b63a/73Bot.git", str(project)],
                               stdout=setup_log, stderr=subprocess.STDOUT, check=True, timeout=180)
            subprocess.run(["git", "-C", str(project), "fetch", "origin", "master"],
                           stdout=setup_log, stderr=subprocess.STDOUT, check=True, timeout=180)
            subprocess.run(["git", "-C", str(project), "checkout", "--detach", "FETCH_HEAD"],
                           stdout=setup_log, stderr=subprocess.STDOUT, check=True, timeout=30)
        if str(project) not in sys.path:
            sys.path.insert(0, str(project))
        from colab73.setup import prepare_environment
        runtime_python = prepare_environment(project, runtime_root)
        from colab73.controller import Controller
        controller = Controller("/content/73bot-data", local_root=runtime_root, python=runtime_python)
        print("準備ができました。音声をアップロードしてください。")
    from colab73.notebook_ui import show_panel
    show_panel(controller)
except Exception as exc:
    print("準備を完了できませんでした。GPU・ネット接続を確認して、もう一度▶を押してください。")
    if not isinstance(exc, subprocess.SubprocessError):
        print(str(exc))
    log_path = Path("/content/73bot-runtime/setup.log")
    details = log_path.read_text(encoding="utf-8", errors="replace")[-16000:] if log_path.exists() else "ログはありません。"
    display(HTML("<details><summary>エラーの詳細</summary><pre style='white-space:pre-wrap'>"
                 + html.escape(details) + "</pre></details>"))
'''),
    markdown("""
## 3. 音声をアップロードして起動

1. ノイズの少ない録音をアップロードします。先頭10秒を見本に使い、短い録音は全体を使います（3〜30秒）。
2. 「試聴」を押し、完了後に自動表示される音声を聞きます。
3. 「BOTを起動」を押します。「BOT稼働中」になったらDiscordでVCへ入り、読むテキストチャンネルで `/join`。
4. 終わったら「停止」。同じセッションでは音声を再アップロードせずに再起動できます。

切り出し区間、任意の書き起こし、音量、読み辞書、測定は「詳細設定・測定・ログ」にあります。
録音・設定・モデル・測定結果はColabの一時領域にあります。セッションが削除されると失われます。
残したい測定結果は停止後に「測定結果をダウンロード」で保存してください。

Discordの操作は `/join` `/leave` `/skip` `/clear` `/status`。声を変更できるのはColabの操作者のみです。
停止ボタンが使えない場合は「ランタイム → 実行を中断」を試し、停止できなければ「ランタイム → 接続を解除して削除」を使います。

[詳しい使い方・トラブル対応](https://github.com/Gai-b63a/73Bot/blob/master/docs/colab.md)
本体はMIT License、Copyright (c) 2026 guy7cc。モデル・依存ライブラリにはそれぞれのライセンスが適用されます。
"""),
]

notebook = {"nbformat": 4, "nbformat_minor": 5,
            "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                         "language_info": {"name": "python", "version": "3.12"},
                         "colab": {"name": "73Bot_Colab.ipynb"}, "accelerator": "GPU"},
            "cells": cells}
for index, cell in enumerate(cells):
    cell["id"] = f"73bot-{index:02d}"
parser = argparse.ArgumentParser()
parser.add_argument("--output-dir", type=Path, default=REPO)
output_root = parser.parse_args().output_dir.resolve()
path = output_root / "notebooks" / "73Bot_Colab.ipynb"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(notebook, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

bundle = output_root / "dist" / "73Bot_Colab.zip"
bundle.parent.mkdir(parents=True, exist_ok=True)
files = [*sorted((REPO / "colab73").glob("*.py")), REPO / "requirements-colab.txt",
         *[REPO / name for name in ("README.md", "LICENSE", "THIRD_PARTY.md", "SECURITY.md", "CONTRIBUTING.md", "CONTEXT.md")],
         *sorted((REPO / "docs").glob("*.md")), *sorted((REPO / "docs" / "images").glob("*.png")),
         REPO / "docs" / "images" / "manifest.json"]
with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
    archive.write(path, "notebooks/73Bot_Colab.ipynb")
    for file in files:
        archive.write(file, file.relative_to(REPO).as_posix())
