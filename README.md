# 73Bot

[![Colabで開く](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Gai-b63a/73Bot/blob/master/notebooks/73Bot_Colab.ipynb)

アップロードした録音に似た声でDiscordの投稿を読み上げます。Qwen3-TTS 0.6B BaseとBOTをGoogle Colab内で動かします。

**[▶ Colabで73Botを開く](https://colab.research.google.com/github/Gai-b63a/73Bot/blob/master/notebooks/73Bot_Colab.ipynb)**

Discord BOTの準備、画像付き案内、起動手順、コマンド、トラブル対応はノートブック内にあります。
通常は「GPUを選ぶ → 準備セルを実行 → 音声をアップロード → 試聴 → BOT起動」で使えます。
書き起こしは任意です。全員の投稿を共通の声で読み、声を変更できるのはColabの操作者のみです。
新しいセッションでは音声を再アップロードします。同じセッションの停止・再起動では再利用できます。
無料Colabで必要時に手動起動する前提で、GPU確保や連続稼働時間は保証されません。

**5秒目標は未達で、本人の録音を使った無料Colab・Discord VCの通し検証は未実施です。** [検証記録](docs/validation.md)

ノートブックはColabで直接編集できます。保存・開発・テストについては[CONTRIBUTING](CONTRIBUTING.md)を参照してください。
不具合は[Issues](https://github.com/Gai-b63a/73Bot/issues)へ。トークンや本人の録音を添付しないでください。
秘密情報の報告は[SECURITY](SECURITY.md)を参照してください。

本体は[MIT License](LICENSE)、Copyright (c) 2026 guy7cc。
モデル・依存ライブラリ・録音の権利は別に扱います。[外部ソフトウェアとモデル](THIRD_PARTY.md)
