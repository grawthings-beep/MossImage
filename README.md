# MOSS-Image + LoRA on RunPod

このrepoを起動すると、MOSS対応版ComfyUI・MOSS-Image Base・マリアン：クイーンLoRA・生成ワークフローをまとめて準備します。追加のComfyUIテンプレートは不要です。

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

1. 左側の **Workflows** から **moss_marian_queen2** を開く。
2. 初期プロンプトは「白いセーター＋ジーンズ、公園」。**Run** を押す。
3. 着せ替えるときは「ここで衣装・背景を変更」の文章を編集。トリガー **m4r14nqu33n2** は残す。
4. 生成画像は画面から保存でき、Podにも自動保存される。

ワークフローが一覧に出ない場合は、[同梱JSON](workflows/moss_marian_queen2.json)をダウンロードして画面へドラッグします。

初期値は学習と同じ **MOSS-Image Base（BF16）**、テキストエンコーダーBF16、LoRA強度1.0、832×1248、50 steps、CFG 3、Euler / sgm_uniform、shift 5、SLG layer 22です。seedは比較用に42で固定しています。別構図を出すときはseedを変更するかrandomizeにします。

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
