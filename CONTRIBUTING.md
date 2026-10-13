# 開発・不具合報告・変更提案

## 不具合を報告する

[Issues](https://github.com/Gai-b63a/73Bot/issues)に、行った操作、期待した結果、実際の結果、GPU名、Pythonのバージョンを記載してください。
エラーは必要な部分だけを抜き出し、送信前に内容を確認してください。
**トークン、録音、書き起こし、音声プリセット、投稿本文、Driveの共有リンクは添付しないでください。**
秘密情報や脆弱性の扱いは[SECURITY](SECURITY.md)を参照してください。

## 開発環境とテスト

Python 3.12とFFmpegを用意し、GitHubからcloneしたリポジトリのルートで実行します。
BOT用のGPU環境とは別に、CPUだけで確認できます。配布ZIPは開発用のコード一式で、開発用の検査ツールやテストは含みません。

```sh
python -m venv .venv
# Linux / macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pytest -q
python tools/check_public_files.py
```

テストではDiscordに接続せず、モデルもダウンロードしません。
実GPUでの生成やColab上の確認を行った場合は、環境・測定条件・未検証の範囲を検証記録に残してください。

## ノートブックとZIPの更新

ノートブックは `tools/build_colab_notebook.py` を編集して再生成します。実行済みのノートブックをそのままコミットしないでください。

```sh
python tools/build_colab_notebook.py
python -m pytest -q
python tools/check_public_files.py
```

生成される `notebooks/73Bot_Colab.ipynb` は公開対象、`dist/73Bot_Colab.zip` はローカルの配布物です。
ZIPはGitに追加しません。内部にはライセンスを含め、必要なファイルだけを同梱します。

通常のColab起動はGitHubの `master` に固定し、Drive ZIPの起動経路は用意していません。
ZIPはコード・ノートブック・文書・案内画像・ライセンスを取り出す開発用です。
テストや検査ツールが必要な開発ではリポジトリをcloneしてください。

案内画像は `docs/images/` のPNGのみを公開できます。実画面から必要箇所を切り出し、
トークン・アカウント・登録済みシークレット・他のBOTやサーバー情報がないことを目視確認します。
`manifest.json` のSHA-256と寸法は、確認済みの最終PNGに合わせて更新してください。
画像の変更は検査で拒否されますが、ハッシュの登録は秘密情報がないことの自動判定を意味しません。
画像を含む差分は必ず公開前に人が確認してください。

## 秘密情報の検査

Gitleaks 8.30.1を使用します。次の取得スクリプトはWindows x64 / Linux x64に対応し、公式アーカイブのSHA-256を確認してからローカルキャッシュに展開します。

```sh
python tools/install_gitleaks.py
# Linux
python tools/check_secrets.py --gitleaks .cache/gitleaks/gitleaks
# Windows
python tools/check_secrets.py --gitleaks .cache/gitleaks/gitleaks.exe
```

その他の環境では[公式配布](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1)を用意し、実行ファイルを `--gitleaks` に指定します。
検査はローカルにある全Git履歴と、現在の追跡対象・無視されていない未追跡ファイルを対象にします。
浅いcloneでは失敗するため、公開前は完全な履歴を取得してください。無視される録音・キャッシュを検査対象へコピーする必要はありません。
検出した値は出力せず、ファイル・行・検出ルール・コミットだけを報告します。

## 変更を提案する

変更の目的、利用者から見た動作、確認したテストをPull Requestに記載してください。
依存パッケージやモデルの変更では、Colabで使えることと生成結果への影響も確認します。
本体への貢献は[MITライセンス](LICENSE)で提供できるコードに限り、外部から取り込む場合は出典と利用条件を明記してください。

GitHub Actionsではテスト・公開ファイル検査・秘密情報検査を実行します。実機の速度や音質の合格を意味するものではありません。
公開前には[公開準備の記録](docs/publication.md)も確認してください。
