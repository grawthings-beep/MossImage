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

次回からは **Podを起動 → Connectの7860を開く → ログイン**。ユーザー名は `moss`、パスワードは設定した `MOSS_PASSWORD`。準備画面で待つと、モデルと2種類のLoRAの取得後、画像生成画面へ自動的に移ります。途中でSafariを離れても準備は続きます。失敗時は画面に停止状態が出て、修正後に画面の「準備を再試行」から再開できます。詳細はRunPodのLogsで確認でき、ターミナルを開く必要はありません。

- 画像生成: 紅蓮：神殺 / マリアン：クイーン、既定 **1152×1536・25ステップ**。キャラを選び、プロンプトを入力して生成します。完成PNGは履歴から保存できます。
- 漫画: 画像生成画面の「漫画スタジオ」。新しい作品は同じ解像度・25ステップ。既存作品の保存済み設定は保持します。50ステップは画面で選択できます。
- ComfyUI: 漫画スタジオのComfyUIリンク（`/?comfy=1`）。両キャラの1152×1536・25ステップ用ワークフローも配置されます。
- ファイル: イメージにJupyterLabがあれば8888も自動起動します。新たに起動したJupyterのログイントークンは `MOSS_PASSWORD` と同じです。既存の8888サービスは停止・置き換えしません。

既存のローカルLoRAはファイル構造・サイズが完全なら再ダウンロードしません。紅蓮のファイル名は `MossImage_scarlet_goddeath.safetensors`、トリガーは `sc4rl3tg0d`。マリアンのトリガーは `m4r14nqu33n2`。非公開LoRAはPodのHF_TOKENで取得し、ブラウザーには渡しません。

LoRA学習がGPUを使用中なら、起動画面で学習の終了を待ちます。学習を勝手に中断しません。生成から学習へ切り替える既存の `background.sh --stop` も使用できます。

`MOSS_PASSWORD` 未設定の場合は従来どおり保存済み `login.json` を使い、なければランダムなパスワードを作ります。設定した場合は環境変数が優先されます。HTTPサービスの認証は無効化しません。

RunPod公式: [テンプレートの自動起動](https://docs.runpod.io/pods/templates/create-custom-template)、[HTTPポート公開](https://docs.runpod.io/pods/configuration/expose-ports)。
