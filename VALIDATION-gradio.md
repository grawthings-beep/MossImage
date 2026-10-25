# 検証記録

検証日: 2026-10-25（日本時間）。

## 確認済み

- Pythonファイルの構文解析。
- `setup.sh` / `start.sh` の `bash -n` 構文確認。
- 独立したWindows / Python 3.12.12環境で依存をインストール。
- 公式モデル `pipeline_moss_image.py`、Qwen3.5、FLUX.2 VAE等の実インポート。
- 固定した公式コードのGradio UIを、同梱例と独自の初期プロンプトを使って構築。
- モデルID、モデルリビジョン、ファイル構成、約27.2GBのサイズをHugging Faceの公開メタデータで確認。

検証に使った主要バージョン:

| ライブラリ | バージョン |
|---|---|
| PyTorch（ローカル検証のみCPU版） | 2.9.1+cpu |
| Diffusers | 0.38.0 |
| Transformers | 5.3.0 |
| Accelerate | 1.10.1 |
| safetensors | 0.8.0 |
| Gradio | 6.30.0 |
| huggingface_hub | 1.33.0 |
| tokenizers | 0.22.2 |
| Pillow | 12.3.0 |

Diffusers 0.38.0はsafetensors >=0.8.0rc0を必要とするため、安定版0.8.0に固定しました。
日本語Windowsで公式サンプルJSONを読む際の文字コード問題を避けるため、起動スクリプトは `PYTHONUTF8=1` を設定します。

## 未確認

- RunPod/Linuxでのセットアップ全体、CUDA演算とGPUへのモデル読み込み。
- モデル全量のダウンロード、実画像生成、速度、ピークVRAM、RunPod HTTPプロキシ経由の接続。

この時点ではPodは未作成です。ローカルではモデル重みをダウンロードしていません。
RunPodでは起動時にGPU実演算を検査します。初回の画像生成確認には `bash start-gradio.sh --smoke` を使えます。
