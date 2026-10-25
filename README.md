# MOSS-Image on RunPod

MOSS-Image-SFTをRunPodで使うための起動キットです。公式Gradio画面でプロンプトを入力して生成します。

## 1. Podを用意

- NVIDIA GPUを1枚。24GB級ではCPUオフロード、48GB級ではGPU常駐が初期設定です。
- RAMは64GB以上、`/workspace` のVolume Diskは80GB以上を目安にしてください。
- PyTorch **2.9以上**、CUDA対応のRunPod PyTorchイメージを使用してください。
  - RunPod公式ドキュメント掲載例: `runpod/pytorch:1.0.3-cu1281-torch291-ubuntu2404`
- Expose HTTP Portsに **7860** を追加。JupyterLabを使う場合は **8888** も追加します。
- GPUは起動時に自動判定します。BF16対応のAmpere以降が対象です。

モデルは約27.2GB（25.4GiB）。初回にRunPodへダウンロードします。GPU種類ごとの速度・最大解像度は未計測です。

## 2. 最初の起動

PodのWeb Terminal、JupyterLabのTerminal、またはSSHで次の1行を実行します。

```bash
cd /workspace && git clone https://github.com/grawthings-beep/MossImage.git && cd MossImage && bash start.sh
```

依存の確認 → 公式コードの取得 → UIの組み立て確認 → モデルの取得 → Web UI起動の順で進みます。
初回のダウンロード中は待ってください。中断した場合は下の「再起動」コマンドで取得を再開できます。

最後に表示される `Login user` / `Login password` を使い、RunPodの **Connect → HTTP Service 7860** を開きます。
この起動方法ではターミナルを開いたまま使います。終了は `Ctrl+C` です。

### 再起動

```bash
cd /workspace/MossImage && bash start.sh
```

### ターミナルを閉じても動かす

初回の起動確認後、`Ctrl+C`で止めてから:

```bash
cd /workspace/MossImage && nohup bash start.sh > /workspace/moss-image-start.log 2>&1 &
```

ログの表示は `tail -f /workspace/moss-image-start.log` です。こちらの`Ctrl+C`はログ表示だけを止めます。
ログイン情報は `/workspace/moss-image-runtime/login.json` に保存されます。

## 3. 画像生成

1. プロンプトを入力（英語の文章が推奨。初期状態にアニメ背景向けの例文があります）。
2. 最初は **1024×1024、50 steps、CFG 3、Shift 5、1枚** のまま実行。
3. `Generate`を押します。初回はモデル読み込みにも時間がかかります。
4. 画像をダウンロードします。画像と生成条件はPodにも自動保存されます。

メモリ不足ならAdvanced settingsのMemory modeを `Component`、さらに不足するなら `Sequential` に変更し、解像度を下げてください。Sequentialは遅くなります。Compileは初期状態でオフです。

例:

```text
A detailed anime illustration of an adult traveler wearing a green cloak, standing on a stone bridge above a quiet forest stream. Soft morning sunlight filters through the leaves. Moss-covered rocks, clear water, delicate line art, rich natural colors, peaceful atmosphere.
```

必要ならNegative promptに `worst quality, bad anatomy, watermark, jpeg artifact` を使えます。
テキスト描画や配置指定は公式の[ユーザーガイド](https://github.com/OpenMOSS/MOSS-Image/blob/main/USERGUIDE.md)を参照してください。

## 保存先と確認

| 内容 | Pod内の場所 |
|---|---|
| 生成PNGとparameters.json | `/workspace/moss-image-runtime/generated/` |
| 公式モデル | `/workspace/moss-image-runtime/models/MOSS-Image-SFT/` |
| セットアップログ | `/workspace/moss-image-runtime/logs/setup.log` |
| UIログ（ログイン情報を含む） | `/workspace/moss-image-runtime/logs/ui.log` |
| ログイン情報 | `/workspace/moss-image-runtime/login.json` |
| 実際に使用したライブラリ一覧 | `/workspace/moss-image-runtime/installed-packages.txt` |

Podのストレージを削除する前に必要な画像を保存してください。作業後はRunPodでPodをStopしてください。

UIを起動する代わりに、1024px・50 stepsの1枚を保存して終了する動作確認:

```bash
cd /workspace/MossImage && bash start.sh --smoke
```

## 実装と検証範囲

- 公式コードとモデルは `revisions.json` のリビジョンに固定しています。
- PodのCUDA版PyTorchを使い、専用venvに依存を追加します。PyTorch / torchvision / torchaudio / Triton / NVIDIA依存の既存バージョンを制約ファイルで保護します。
- PyTorchが古い場合は止めます。別用途のSDXL/Anima学習環境にはインストールせず、MOSS専用Podを使ってください。
- 起動前にCUDA BF16演算、実インポート、UI構築を検査します。
- ローカル検証の結果は `VALIDATION.md` を参照。**RunPod GPUでのモデル読込・画像生成は未検証です。**
- 保存先変更: `MOSS_HOME=/workspace/別フォルダ bash start.sh`
- 初期Memory modeの指定: `bash start.sh --profile 24gb` / `--profile 48gb`

このリポジトリはOpenMOSS公式リポジトリではありません。公式モデルとコードを取得して起動する補助キットです。

参考: [OpenMOSS/MOSS-Image](https://github.com/OpenMOSS/MOSS-Image)、[公式モデル](https://huggingface.co/OpenMOSS-Team/MOSS-Image-SFT)、[RunPodの接続方法](https://docs.runpod.io/pods/connect-to-a-pod)、[RunPod公式イメージ例](https://docs.runpod.io/runpodctl/reference/runpodctl-pod)。
