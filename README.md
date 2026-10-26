# MOSS-Image + LoRA on RunPod

このrepoを起動すると、MOSS対応版ComfyUI・MOSS-Image Base・マリアン：クイーンと紅蓮：神殺のLoRA・生成画面をまとめて準備します。画像生成の既定は **1152×1536・25ステップ** です。

**毎回コマンドを入力せずに使う:** [RunPodテンプレートの自動起動設定](RUNPOD.md)を一度保存してください。以降はPod起動後に **Connect → 7860** を開くだけ。準備中も同じURLに状態を表示し、取得完了後に画像生成画面へ移ります。`MOSS_PASSWORD` を設定すれば、ログからパスワードを探す必要もありません。

**漫画を作る場合:** 起動後のURLの末尾に **`/studio/`** を付けると、同じログインで「漫画スタジオ」を使えます。コマ割りを公式形式のJSONに変換し、全体生成／コマ別生成、参照画像、部分修正、日本語の縦書き、PNG・SVG保存に対応。[使い方とモデル構成](MANGA.md)。

**LoRAを作る場合:** [PCから送信してRunPodで自動学習する手順](TRAINING.md)。画像とキャプションをまとめて送り、Podに1行貼ると受信・Pre-Cache・学習・保存までバックグラウンドで進みます。

## 1. Podを用意

- RunPodのCUDA版 **PyTorch 2.9以上 / Python 3.12** のテンプレートを使用。
- **HTTP Port 7860** を公開。JupyterLabを使う場合は8888も公開。
- /workspaceの保存容量は **100GB**、RAMは64GB以上を目安にする。
- BF16対応GPUを1枚。48GB級が余裕を持たせた目安。ComfyUIがメモリに応じてオフロードします。GPU別の速度・最大解像度は未計測です。
- LoRAの保存先は非公開のため、Podの環境変数 **HF_TOKEN** に、uwgm/Mossを読めるHugging Faceトークンを設定できます。設定しなくても初回のターミナルで非表示入力できます。

## 2. 最初の起動

PodのTerminalで、この1行を実行します。

```bash
cd /workspace && git clone https://github.com/grawthings-beep/MossImage.git && cd MossImage && bash background.sh
```

CUDA実演算の確認 → MOSS対応ComfyUIの固定版を取得 → 依存の確認 → LoRAとモデルの取得 → ログイン付きComfyUI起動、の順で進みます。モデルは合計約30GBです。初回はダウンロードに時間がかかります。

この起動方法はバックグラウンドで動くため、iPhoneのSafariやターミナルを閉じてもセットアップ・生成が続きます。**HF_TOKENを設定済み**、またはLoRAを配置済みで使用してください。初回の進行とログイン情報を表示:

```bash
tail -n 80 -f /workspace/moss-image-runtime/logs/background.log
```

ログの **Login user / Login password** を使い、RunPodの **Connect → HTTP Service 7860** を開きます。漫画スタジオはそのURLの末尾に **`/studio/`** を付けて開きます。`tail`の終了はCtrl+Cで、サーバーは継続します。対話的なトークン入力が必要な場合は、従来どおり `bash start.sh` を使えます。

すでにこのrepoを取得している場合は、停止してから更新します。

```bash
cd /workspace/MossImage && git pull --ff-only && bash background.sh
```

バックグラウンドで稼働中なら、生成が終わってから次の1行で更新・再起動できます。このキットの同じ保存先を使う生成サーバーだけを停止し、モデル・作品・ログイン情報を保持します。

```bash
cd /workspace/MossImage && git pull --ff-only && bash background.sh --restart
```

通常の再起動・ダウンロード中断後の再開:

```bash
cd /workspace/MossImage && bash background.sh
```

### LoRAをPCからアップロードする場合

トークンを使わず、保存済みのファイルを次の場所に置いても使えます。

```text
/workspace/moss-image-runtime/ComfyUI/models/loras/mossimage_lora_marian_queen2.safetensors
```

配置後、start.shを実行してください。完全なファイルがあれば再取得しません。学習画像・LoRA本体・トークンはこのGitHubリポジトリに含めていません。

## 3. 生成する

1. **Connect → 7860** の画像生成画面で、紅蓮：神殺／マリアン：クイーンを選ぶ。
2. 場面・ポーズ・衣装・演出のプロンプトを編集して **画像を生成**。キャラのトリガーと基本の外見は自動で追加される。
3. 生成履歴で画像を確認し、**PNGを保存**。設定・プロンプトも取得できる。
4. 漫画は右上の **漫画スタジオ** へ。ComfyUIのノードを直接操作する場合は、そこから **ComfyUI** を開く。

ComfyUIには [マリアン用JSON](workflows/moss_marian_queen2_1152x1536_25.json) と [紅蓮用JSON](workflows/moss_scarlet_goddeath_1152x1536_25.json) を配置します。以前の保存済みワークフローは上書きせず残します。

初期値は学習と同じ **MOSS-Image Base（BF16）**、テキストエンコーダーBF16、LoRA強度1.0、**1152×1536、25 steps、CFG 2.5、er_sde / simple、SLG layer 22を前半50%に適用**。seedは比較用に42です。別構図を出すときは「シードを変更」を使います。

これらは初期値です。顔・衣装の再現品質を保証するものではなく、実際の生成結果で確認します。

## 保存先

| 内容 | 場所 |
|---|---|
| ComfyUIとモデル | /workspace/moss-image-runtime/ComfyUI/ |
| 生成画像 | /workspace/moss-image-runtime/ComfyUI/output/MOSS/ |
| ワークフロー | /workspace/moss-image-runtime/ComfyUI/user/default/workflows/ |
| ログイン情報 | /workspace/moss-image-runtime/login.json |
| セットアップログ | /workspace/moss-image-runtime/logs/comfy-setup.log |
| UIログ | /workspace/moss-image-runtime/logs/comfy-ui.log |
| 漫画の作品・生成キュー・画像・フォント | /workspace/moss-image-runtime/studio/ |
| バックグラウンド起動ログ | /workspace/moss-image-runtime/logs/background.log |

作業後はPodをStopします。Podの停止・削除と、Safariを閉じる操作は別です。必要な画像・作品ZIPはストレージ削除前に保存してください。稼働中の旧サーバーは `git pull` だけでは更新されません。生成の完了後に旧プロセスを止め、更新したコードで起動してください。

## 実装と検証

- `comfy-revisions.json` でMOSS対応ComfyUIと公開モデルのリビジョンを固定。
- 専用venvを使い、既存のCUDA PyTorch / torchvision / torchaudio / Triton / NVIDIA依存を制約ファイルで保護。
- 起動前にCUDA BF16演算と実際のMOSSノードを確認。カスタムノード追加は不要。
- ComfyUI本体は内部ポートで起動し、7860を同じログインで保護。生成進捗・プレビューのWebSocketも中継。
- 再起動時、利用者が編集した保存済みワークフローは上書きしない。
- ポート変更: `bash start.sh --port 8188`。保存先変更: `MOSS_HOME=/workspace/別フォルダ bash start.sh`。
- 従来の公式Gradio版（SFT単体）は `bash start-gradio.sh` で起動可能。LoRA生成は既定のComfyUI版を使用。
- 検証結果は [VALIDATION.md](VALIDATION.md)。**RunPodのGPUでの実画像生成は未検証です。**

このrepoは、公式コードとモデルを取得する起動キットです。

参照: [ComfyUI](https://github.com/Comfy-Org/ComfyUI)、[MOSSモデル](https://huggingface.co/Comfy-Org/MOSS-Image)、[OpenMOSS](https://github.com/OpenMOSS/MOSS-Image)。
