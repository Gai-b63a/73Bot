"""Rebuild the checked-in notebook using only the standard library."""
import argparse
import json
from pathlib import Path
import zipfile


def markdown(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.strip().splitlines(keepends=True)}


def code(text):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": text.strip().splitlines(keepends=True)}


cells = [
    markdown("""
# 73Bot — 保存した自分の声でDiscordを読み上げ

**ランタイム → ランタイムのタイプを変更 → GPU** を選び、上から順に実行します。
初回のみ声を登録。次回はDrive接続後、保存済みの声で起動できます。
書き起こしは任意です。空欄なら録音だけで声を再現し、入力すると対応する文章も利用します。

事前にDiscord Developer PortalでBOTを作成し、**Message Content Intent**を有効にしてください。
招待には `bot` と `applications.commands`、チャンネルの閲覧・メッセージ送信・VC接続・発言権限が必要です。
左の鍵アイコン「シークレット」に `DISCORD_BOT_TOKEN` を登録し、このノートブックからのアクセスを許可します。
録音・書き起こし・トークンをコードセルに書かないでください。

必要時に手動起動する検証用です。無料ColabのGPU割り当て・稼働時間は保証されません。
ローカルGPU試験では5秒目標は未達です。本人の声を使ったColab・Discord VCでの通し検証は未実施です。
詳細は[利用手順](https://github.com/Gai-b63a/73Bot/blob/master/docs/colab.md)と
[検証記録](https://github.com/Gai-b63a/73Bot/blob/master/docs/validation.md)を参照してください。
本体はMIT License、Copyright (c) 2026 guy7cc。モデル・依存ライブラリにはそれぞれのライセンスが適用されます。
"""),
    code('''
# 1. プロジェクト取得（GitHub または Driveに保存した配布ZIP）
from pathlib import Path
import subprocess
import sys

SOURCE = "GitHub" #@param ["GitHub", "DriveのZIP"]
REPOSITORY = "https://github.com/Gai-b63a/73Bot.git" #@param {type:"string"}
REVISION = "master" #@param {type:"string"}
ZIP_PATH = "/content/drive/MyDrive/73Bot/73Bot_Colab.zip" #@param {type:"string"}
PROJECT = Path("/content/73Bot")

if "controller" in globals():
    controller.require_stopped()
    del controller
for module in list(sys.modules):
    if module == "colab73" or module.startswith("colab73."):
        del sys.modules[module]
if SOURCE == "DriveのZIP":
    from google.colab import drive
    import zipfile
    drive.mount("/content/drive")
    PROJECT.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP_PATH) as archive:
        for item in archive.infolist():
            if not (PROJECT / item.filename).resolve().is_relative_to(PROJECT.resolve()):
                raise ValueError("ZIP内のパスが不正です。")
        archive.extractall(PROJECT)
else:
    if not PROJECT.exists():
        subprocess.run(["git", "clone", "--", REPOSITORY, str(PROJECT)], check=True)
    subprocess.run(["git", "-C", str(PROJECT), "fetch", "origin", REVISION], check=True)
    subprocess.run(["git", "-C", str(PROJECT), "checkout", "--detach", "FETCH_HEAD"], check=True)
if not (PROJECT / "requirements-colab.txt").is_file():
    raise RuntimeError("Colab版が含まれないブランチです。実装を反映したREVISIONを指定してください。")
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))
print("プロジェクトを準備しました。")
'''),
    code('''
# 2. 実行環境の準備（初回・新しいセッションごと）
import subprocess
import sys
from pathlib import Path
from colab73.locking import RuntimeLock

if "controller" in globals():
    controller.require_stopped()
if sys.version_info[:2] != (3, 12):
    raise RuntimeError("Python 3.12を想定しています。Colabの過去のランタイム（2026.07等）を選択してください。")

# Use an isolated environment so Qwen's pinned Transformers does not alter
# the notebook kernel or Colab's own packages. Reuse the GPU PyTorch pair.
with RuntimeLock(Path("/content/73bot-runtime/runtime.lock")):
    subprocess.run(["apt-get", "update", "-qq"], check=True)
    subprocess.run(["apt-get", "install", "-y", "-qq", "ffmpeg", "libopus0", "libsodium23", "sox"], check=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "virtualenv", "ipywidgets>=8.1,<9"], check=True)
    RUNTIME_PYTHON = Path("/content/73bot-env/bin/python")
    if not RUNTIME_PYTHON.exists():
        subprocess.run([sys.executable, "-m", "virtualenv", "--system-site-packages", "/content/73bot-env"], check=True)
    subprocess.run([str(RUNTIME_PYTHON), "-c", "import torch,torchaudio; assert torch.cuda.is_available(), 'GPUを選択してください'; assert torch.__version__.split('+')[0] == torchaudio.__version__.split('+')[0], 'torchとtorchaudioのバージョンが一致しません'"], check=True)
    subprocess.run([str(RUNTIME_PYTHON), "-m", "pip", "install", "-q", "-r", str(PROJECT / "requirements-colab.txt")], check=True)
    subprocess.run([str(RUNTIME_PYTHON), "-c", "import torch,torchaudio,qwen_tts,discord,davey; print('GPU:', torch.cuda.get_device_name()); print('discord.py:', discord.__version__)"], check=True)
print("セットアップ完了。次へ進んでください。")
'''),
    code('''
# 3. Driveの接続と保存先の指定
from google.colab import drive
from colab73.controller import Controller

drive.mount("/content/drive")
STORE_ROOT = "/content/drive/MyDrive/73Bot" #@param {type:"string"}

# Keep the same controller on cell re-execution so its process remains stoppable.
if "controller" not in globals():
    controller = Controller(STORE_ROOT, python=RUNTIME_PYTHON)
elif str(controller.store.root) != str(Path(STORE_ROOT).resolve()):
    controller.require_stopped()
    controller = Controller(STORE_ROOT, python=RUNTIME_PYTHON)
print("保存先:", controller.store.root)
'''),
    code('''
# 4. 管理画面（声の変更は停止中のみ）
from colab73.notebook_ui import show_panel
show_panel(controller)
'''),
    markdown("""
## 通常の使い方

1. 保存済みの声を選び、必要なら音量・読み辞書を変更して「設定を保存」。
2. 「試聴」または「20例×3回の測定」を実行。「状態・ログを確認」で結果を表示。
3. 試聴が終了してから「BOTを起動」。準備完了後、DiscordでVCに入り `/join`。
4. 終わったら「停止」。声を変える場合も停止後に選択・保存して再起動。

Discord側の操作は `/join` `/leave` `/skip` `/clear` `/status` です。`/voice` はありません。
`/clear` は現在の投稿を最後まで読み、待っている投稿のみを消します。
試聴・測定・BOTの同時起動はできません。モデルを保持するのは1ワーカーだけです。

測定結果と音声はDriveの `73Bot/reports` に保存されます。試聴の測定にはDiscord通信は含まれません。
BOTの `idle_first_packet_seconds` が待ち行列なしの送信開始測定です。耳で聞こえるまでの時間とは区別してください。
"""),
    code('''
# 5. 停止ボタンを使えない場合の停止用セル
# 終了するときだけ実行します。
controller.stop()
print(controller.status())
'''),
]

notebook = {"nbformat": 4, "nbformat_minor": 5,
            "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                         "language_info": {"name": "python", "version": "3.12"},
                         "colab": {"name": "73Bot_Colab.ipynb"}, "accelerator": "GPU"},
            "cells": cells}
for index, cell in enumerate(cells):
    cell["id"] = f"73bot-{index:02d}"
repo = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--output-dir", type=Path, default=repo)
output_root = parser.parse_args().output_dir.resolve()
path = output_root / "notebooks" / "73Bot_Colab.ipynb"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(notebook, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# Select distribution files explicitly; never bundle local recordings, tokens,
# caches, environments or notebook output.
bundle = output_root / "dist" / "73Bot_Colab.zip"
bundle.parent.mkdir(parents=True, exist_ok=True)
files = [*sorted((repo / "colab73").glob("*.py")),
         repo / "requirements-colab.txt", repo / "README.md",
         repo / "LICENSE", repo / "THIRD_PARTY.md", repo / "SECURITY.md",
         repo / "CONTRIBUTING.md", repo / "CONTEXT.md",
         repo / "docs" / "colab.md", repo / "docs" / "validation.md", repo / "docs" / "publication.md"]
with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
    archive.write(path, "notebooks/73Bot_Colab.ipynb")
    for file in files:
        archive.write(file, file.relative_to(repo).as_posix())
