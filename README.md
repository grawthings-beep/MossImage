# MOSS-Image + LoRA on RunPod

RunPodで **マリアン：ラストアフェクション** と **マルチャーナ：マリンスタディ**（元の33枚版・30枚版 v1）を生成するComfyUIキットです。各ワークフローにはキャラLoRAが設定されており、1回のRunで元画像と、高解像度でもう一度描き込んだ仕上げ版を保存します。

**毎回コマンドを入力せずに使う:** [RunPodテンプレートの自動起動設定](RUNPOD.md)を一度保存してください。以降はPod起動後に **Connect → 7860** を開くだけ。準備中も同じURLに状態を表示し、取得完了後に通常のComfyUIへ移ります。`MOSS_PASSWORD` を設定すれば、ログからパスワードを探す必要もありません。

**操作はComfyUIのノードで行います。** 漫画スタジオと独自の画像生成画面は廃止しました。旧URLもComfyUIへ移動します。実行中のノード・ステップ進捗はComfyUI標準表示を使い、軽量な途中プレビューを起動時に有効にします。

**MOSS_10 Fast Hires** は864×1152で生成し、1296×1728に仕上げます。顔が小さい全身絵には **MOSS_08 Quality Hires**（1152×1536 → 1728×2304）を使えます。[ワークフローと描き込みの調整](WORKFLOWS.md)

**LoRA学習**は学習専用テンプレートで起動できます。PCからの受信、またはJupyterLabでのファイル投入後、キャッシュ作成・学習・保存まで自動で進みます。[学習テンプレートの設定](TRAINING.md)

## 1. Podを用意

- RunPodのCUDA版 **PyTorch 2.9以上 / Python 3.12** のテンプレートを使用。
- **HTTP Port 7860** を公開。JupyterLabを使う場合は8888も公開。
- /workspaceの保存容量は **100GB**、RAMは64GB以上を目安にする。
- BF16対応GPUを1枚。48GB級が余裕を持たせた目安。ComfyUIがメモリに応じてオフロードします。GPU別の速度・最大解像度は未計測です。
- Podの環境変数 **HF_TOKEN** に `uwgm/Moss` のCottonMossとキャラLoRAを読めるシークレットを割り当てます。

## 2. 最初の起動

PodのTerminalで、この1行を実行します。

```bash
cd /workspace && git clone https://github.com/grawthings-beep/MossImage.git && cd MossImage && bash background.sh
```

Hugging FaceでCottonMossの読み取り権限・ファイル名・サイズ・SHA256を確認 → CUDA実演算の確認 → MOSS対応ComfyUIの固定版を取得 → 依存の確認 → LoRAとモデルの取得 → ログイン付きComfyUI起動、の順で進みます。HF_TOKEN未設定・未展開・認証拒否・配信エラーは準備画面に表示します。初回はCottonMoss Turbo INT8、MOSS-Image Base BF16、MOSS-Image SFT BF16、キャラLoRA 3種、Qwenテキストエンコーダー、small VAEをダウンロードします。

この起動方法はバックグラウンドで動くため、iPhoneのSafariやターミナルを閉じてもセットアップ・生成が続きます。**HF_TOKENを設定済み**、またはLoRAを配置済みで使用してください。初回の進行とログイン情報を表示:

```bash
tail -n 80 -f /workspace/moss-image-runtime/logs/background.log
```

ログの **Login user / Login password** を使い、RunPodの **Connect → HTTP Service 7860** を開きます。`tail`の終了はCtrl+Cで、サーバーは継続します。

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

キャラLoRAの配置先です。既存ファイルはサイズとSHA256を確認して再利用します。

```text
/workspace/moss-image-runtime/ComfyUI/models/loras/mossimage_lora_marciana_marine_study_30_v1.safetensors
/workspace/moss-image-runtime/ComfyUI/models/loras/mossimage_lora_marciana_marine_study.safetensors
/workspace/moss-image-runtime/ComfyUI/models/loras/mossimage_lora_marian_last_affection2_3k.safetensors
```

配置後、start.shを実行してください。完全なファイルがあれば再取得しません。学習画像・LoRA本体・トークンはこのGitHubリポジトリに含めていません。

## 3. 生成する

1. **Connect → 7860** で通常のComfyUIを開く。
2. **Workflows** で使いたいキャラの **MOSS_10 Fast Hires** または **MOSS_08 Quality Hires** を選ぶ。
3. 緑の欄でトリガー（マリアンは `m4r14nl4st2`、マルチャーナは `m4rc14n4m4r1ne`）を残し、プロンプトを変更する。
4. **Run** を押す。元画像と、高解像度でもう一度描き込んだ仕上げ版がそれぞれ **Save Image** に表示され、PNGが自動保存される。

既存Podを更新すると、以前同梱していたワークフローは `ComfyUI/user/default/moss-workflow-archive/` に退避します。生成済みのPNGやLoRAはそのまま使えます。

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
