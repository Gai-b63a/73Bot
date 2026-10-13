# 73Bot

[![Colabで開く](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Gai-b63a/73Bot/blob/master/notebooks/73Bot_Colab.ipynb)

**[▶ Google Colabで73Botを開く](https://colab.research.google.com/github/Gai-b63a/73Bot/blob/master/notebooks/73Bot_Colab.ipynb)**

GitHub上の最新版（`master`）のノートブックを開きます。[初回セットアップの手順はこちら](docs/colab.md)。

アップロードした録音に似た声で、Discordの投稿を読み上げるBOTです。
Qwen3-TTS 0.6B Baseによる音声生成とDiscordへの接続・再生を、同じGoogle Colab内で動かします。

**現在は検証段階です。読み上げ開始まで5秒の目標は未達で、本人の声を使った無料Colab・Discord VCでの通し検証も未実施です。**
ローカルGPUでの測定条件・結果と残っている確認事項は[検証記録](docs/validation.md)に掲載しています。

## できること

- 全員の投稿を共通の1種類の声で読み上げ。声を選べるのはColabを操作する管理者のみ。
- 録音から声を登録。書き起こしは任意で、空欄なら録音だけを使います。
- 新しいColabセッションごとに音声をアップロード。同じセッションでは停止・再起動しても再利用。
- 投稿順に再生し、長い文章は区切って次の区間を先読み。URL・コードブロック・メンションを整形。
- 試聴、20例×3回の測定、待ち時間の記録、無人時の自動退出。

## 必要なもの

- GPUを割り当てられるGoogle Colab。Python 3.12を使用します。
- Discord BOTのトークンと、BOTを導入できるDiscordサーバー。
- 自分の録音、または声の再現に使う許可を得た録音。見本は3〜30秒、5〜15秒を推奨します。

モデルの重みはセッションの初回にHugging Faceから一時ディスクへ取得します。録音やモデル重みはこのリポジトリに含まれていません。
無料ColabのGPU確保や連続稼働時間は保証されません。管理者が必要なときに手動で起動する使い方を想定しています。

## はじめる

1. [画像付きのDiscord BOT準備案内](docs/discord-setup.md)で、BOTとColabのシークレットを準備します。
2. 上の「Colabで開く」からノートブックを開き、GPUを選びます。
3. 「準備して操作画面を開く」の▶を押します。取得やインストールは自動です。
4. 音声をアップロードして「試聴」、その後「BOTを起動」を押します。
5. DiscordでVCに入り、読むテキストチャンネルで `/join` を実行します。

取得先はこのリポジトリの `master` に固定しています。Drive接続や保存操作は不要です。
音声を変えるときは「停止 → 別の音声をアップロード → 試聴 → 再起動」です。
録音・設定・モデル・測定結果は一時領域にあり、セッションの削除で失われます。
[詳しい手順・トラブル対応](docs/colab.md)も参照してください。
ノートブックの置き場所は自由です。配布ZIPは[開発用途](CONTRIBUTING.md#ノートブックとzipの更新)に残しています。

## Discordの操作

| コマンド | 動作 |
|---|---|
| `/join` | 実行者のVCに参加し、そのテキストチャンネルを読む |
| `/leave` | 読み上げと待ち行列を終了して退出 |
| `/skip` | 現在の投稿の残りをスキップ |
| `/clear` | 待っている投稿を削除。現在の投稿は読み続ける |
| `/status` | 接続、選択中の声、待ち件数、生成状態を確認 |

再生操作はBOTと同じVCの参加者に限定します。Discord側で声を変更するコマンドはありません。

## 開発・報告

[開発と変更提案](CONTRIBUTING.md)に、GPUを使わないテスト、配布ファイルの生成、公開前の検査をまとめています。
内部構成は[開発者向け概要](CONTEXT.md)を参照してください。
不具合は[Issues](https://github.com/Gai-b63a/73Bot/issues)へ、使用環境・再現手順・期待した動作を添えて報告できます。
**トークン、本人の録音、書き起こし、Driveの共有リンクは添付しないでください。**
秘密情報や脆弱性に関する報告は[セキュリティ方針](SECURITY.md)を確認してください。

現在の構成はColab版のみです。従来のDocker／COEIROINK版はGit履歴から参照できます。

## ライセンス

本体コードは[MIT License](LICENSE)、`Copyright (c) 2026 guy7cc`です。
モデル、依存ライブラリ、録音の権利は本体のライセンスと別に扱います。[外部ソフトウェアとモデル](THIRD_PARTY.md)を参照してください。
