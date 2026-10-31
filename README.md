# MOSS-Image + LoRA on RunPod

このrepoを起動すると、MOSS対応版ComfyUI・MOSS-Image Base・マリアン：クイーンと紅蓮：神殺のLoRA・キャラ参照・画像編集をまとめて準備します。通常生成とキャラ参照の既定は **1152×1536・25ステップ** です。

**毎回コマンドを入力せずに使う:** [RunPodテンプレートの自動起動設定](RUNPOD.md)を一度保存してください。以降はPod起動後に **Connect → 7860** を開くだけ。準備中も同じURLに状態を表示し、取得完了後に通常のComfyUIへ移ります。`MOSS_PASSWORD` を設定すれば、ログからパスワードを探す必要もありません。

**操作はComfyUIのノードで行います。** 漫画スタジオと独自の画像生成画面は廃止しました。旧URLもComfyUIへ移動します。実行中のノード・ステップ進捗はComfyUI標準表示を使い、軽量な途中プレビューを起動時に有効にします。

用意済みの4つのJSONと使い方は [WORKFLOWS.md](WORKFLOWS.md)。既存の画像・保存データは削除しません。

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

CUDA実演算の確認 → MOSS対応ComfyUIの固定版を取得 → 依存の確認 → LoRAとモデルの取得 → ログイン付きComfyUI起動、の順で進みます。通常生成用の約30GBに加え、参照・編集用に約10.8GB取得します。初回はダウンロードに時間がかかります。

この起動方法はバックグラウンドで動くため、iPhoneのSafariやターミナルを閉じてもセットアップ・生成が続きます。**HF_TOKENを設定済み**、またはLoRAを配置済みで使用してください。初回の進行とログイン情報を表示:

```bash
tail -n 80 -f /workspace/moss-image-runtime/logs/background.log
```

ログの **Login user / Login password** を使い、RunPodの **Connect → HTTP Service 7860** を開きます。`tail`の終了はCtrl+Cで、サーバーは継続します。対話的なトークン入力が必要な場合は、従来どおり `bash start.sh` を使えます。

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

1. **Connect → 7860** で通常のComfyUIを開く。
2. **Workflows** から `MOSS_01`～`MOSS_04` のいずれかを開く。
3. テキストノードでプロンプトを変更。参照・編集の場合は **Load Image** で画像をアップロード。
4. **Run / Queue** で実行。**Save Image** に完成画像が表示され、PNGが自動保存される。

通常生成2種類・CharRef・Edit HQ v5のワークフローを自動配置します。参照・編集用の追加モデルも起動時に取得します（追加約10.8GB）。以前の保存済みワークフローは上書きせず残します。

通常生成の初期値は学習と同じ **MOSS-Image Base（BF16）**、テキストエンコーダーBF16、LoRA強度1.0、**1152×1536、25 steps、CFG 2.5、er_sde / simple、SLG layer 22を前半50%に適用**。seedは比較用に42です。別の候補を出すときはKSamplerのseedを変更します。画像編集はSFT＋Edit HQ v5で、元画像の縦横比を保つ約1MP出力です。

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
| 旧画面の保存データ（保持） | /workspace/moss-image-runtime/studio/ |
| バックグラウンド起動ログ | /workspace/moss-image-runtime/logs/background.log |

作業後はPodをStopします。必要な画像・ワークフローはストレージ削除前に保存してください。稼働中の旧サーバーは `git pull` だけでは更新されません。生成の完了後に更新・再起動してください。

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
