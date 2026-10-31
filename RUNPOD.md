# Podを起動してURLを開くだけで使う

現在使えている **CUDA版PyTorch 2.9以上 / Python 3.12** のイメージをそのまま使えます。新しいDockerイメージのビルドは不要です。以下をRunPodのテンプレートに一度保存してください。repoの更新だけでは、RunPodの起動設定は変わりません。

| 項目 | 設定 |
|---|---|
| Container Image | 現在のPyTorchイメージを継続 |
| Container Start Command | 下記の1行 |
| Expose HTTP Ports | `7860,8888` |
| Volume mount path | `/workspace` |
| Volume Disk | 100GB以上を目安に、既存の学習モデル分も確保 |
| `HF_TOKEN` | 設定済みのHugging Faceシークレット（`uwgm/Moss` の読み取り権限） |
| `MOSS_PASSWORD` | 自分で決めたログイン用パスワード。英数字・記号で12文字以上を推奨 |

**Container Start Command**（ターミナルではなくテンプレートの起動コマンド欄に保存）:

```text
bash -lc 'set -e; mkdir -p /workspace; if [ -d /workspace/MossImage/.git ]; then git -C /workspace/MossImage pull --ff-only; else git clone https://github.com/grawthings-beep/MossImage.git /workspace/MossImage; fi; exec bash /workspace/MossImage/runpod_start.sh'
```

同じ内容を [runpod-start-command.txt](runpod-start-command.txt) に置いています。稼働中Podの設定変更は再起動を伴う場合があるため、進行中の生成・学習が終了してから適用します。

次回からは **Podを起動 → Connectの7860を開く → ログイン**。ユーザー名は `moss`、パスワードは設定した `MOSS_PASSWORD`。準備画面で待つと、通常生成・キャラ参照・画像編集のモデル取得後、通常のComfyUIへ移ります。失敗時は画面に停止状態が出て、修正後に「準備を再試行」から再開できます。詳細はRunPodのLogsで確認できます。

- ComfyUIの **Workflows** に `MOSS_01`～`MOSS_04` を配置します。紅蓮・マリアン・キャラ参照・画像編集の4種類です。[各ワークフローの操作](WORKFLOWS.md)。
- 通常生成とキャラ参照は **1152×1536・25ステップ**。編集は元画像の比率を保つ約1MP・25ステップです。
- 漫画スタジオ・独自の画像生成画面は廃止。旧 `/studio/`、`/studio/image` はComfyUIへ転送します。保存済みの画像とファイルは維持します。
- ファイル: イメージにJupyterLabがあれば8888も自動起動します。新たに起動したJupyterのログイントークンは `MOSS_PASSWORD` と同じです。既存の8888サービスは停止・置き換えしません。

既存のローカルLoRAはファイル構造・サイズが完全なら再ダウンロードしません。紅蓮のファイル名は `MossImage_scarlet_goddeath.safetensors`、トリガーは `sc4rl3tg0d`。マリアンのトリガーは `m4r14nqu33n2`。非公開LoRAはPodのHF_TOKENで取得し、ブラウザーには渡しません。

LoRA学習がGPUを使用中なら、起動画面で学習の終了を待ちます。学習を勝手に中断しません。生成から学習へ切り替える既存の `background.sh --stop` も使用できます。

`MOSS_PASSWORD` 未設定の場合は従来どおり保存済み `login.json` を使い、なければランダムなパスワードを作ります。設定した場合は環境変数が優先されます。HTTPサービスの認証は無効化しません。

RunPod公式: [テンプレートの自動起動](https://docs.runpod.io/pods/templates/create-custom-template)、[HTTPポート公開](https://docs.runpod.io/pods/configuration/expose-ports)。
