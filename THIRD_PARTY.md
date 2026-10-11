# 外部ソフトウェアとモデル

73Bot本体の[MITライセンス](LICENSE)は、外部モデル・依存ライブラリ・利用者の録音に新たな利用許可を与えるものではありません。
以下は主要な利用先です。間接的な依存関係も含め、それぞれの配布物のライセンスが適用されます。

| 利用先 | 用途 | ライセンス・参照先 |
|---|---|---|
| Qwen3-TTS / qwen-tts | 音声合成 | [公式リポジトリとライセンス](https://github.com/QwenLM/Qwen3-TTS)（Apache-2.0） |
| Qwen3-TTS-12Hz-0.6B-Base | 声の再現に使うモデル | [公式モデルカード](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base)（Apache-2.0） |
| discord.py | Discord接続・音声送信 | [公式ライセンス](https://github.com/Rapptz/discord.py/blob/master/LICENSE)（MIT） |
| PyTorch | GPUでの推論 | [公式ライセンス](https://github.com/pytorch/pytorch/blob/main/LICENSE) |
| FFmpeg | 録音の変換・切り出し、PCM変換 | [公式ライセンス案内](https://ffmpeg.org/legal.html)。ビルド構成により条件が異なります |
| Gitleaks | 開発時の秘密情報検査 | [公式リポジトリとライセンス](https://github.com/gitleaks/gitleaks)（MIT） |

配布ZIPに含むのは73Botのコード・文書・ノートブックです。
依存ライブラリはセットアップ時にインストールし、モデル重みはHugging FaceからDriveへ取得します。
第三者のソフトウェアやモデルを再配布する場合は、実際の配布物に含まれるライセンス・NOTICEを確認してください。

自分の録音、または声の再現に使う許可を得た録音を使ってください。
声のプリセットと生成音声はGitや配布ZIPに含めず、利用者のDriveで管理します。
