# ComfyUI版の検証記録

検証日: 2026-10-25（日本時間）。

## 確認済み

- 固定したComfyUI: 19ae172bff6c9e4c738e7f2e00fe087f5b5b46ab（起動時バージョン表示0.42.0）。
- 公開モデル: Comfy-Org/MOSS-Image、revision 24147db865fcdc207270f844777587223fed8d6e。Base BF16・Qwen3.5-9B BF16・flux2-vae_smallの存在を確認。
- Python構文解析、起動スクリプト4本のBash構文、git diff --check。
- 実際のComfyUIでMOSSのCLIPLoader・UNETLoader・VAE・SLG・Flux2 latent等をインポート。
- 同梱ワークフローをComfyUI実装のprompt validatorが受理。モデル名の照合には検証専用の空ファイルを使用し、重み実行はしていない。
- 利用者の保存済みLoRAの全252アダプター / 756テンソルが、ネイティブMOSSモデルのキーと形状に一致。モデルはmeta deviceで構築し、大型の本体重みは読み込んでいない。
- 新しいlaunch_comfy.pyから実際のComfyUIをCPUモードで起動。未認証401、認証後のフロントエンドとAPI、MOSS対応のobject_info、保存済みワークフロー一覧、WebSocket status、子プロセス終了を確認。
- 自動テスト5件: HTTP/WS認証、APIリクエスト・プレビュー転送、途中ダウンロードの拒否、既存のログイン情報とワークフロー編集の保持。

ローカル検証環境: Windows、Python 3.12.12、PyTorch 2.9.1+cpu、ComfyUI frontend 1.57.1、aiohttp 3.14.5、huggingface_hub 1.33.0。これはCPUでの配線・起動検証であり、GPU生成品質の検証ではない。

自動テストの再実行（ComfyUIの依存が入ったPythonで）:

```bash
python -m unittest discover -s tests -v
```

## 未確認

- RunPod/Linuxでのセットアップ全体、HF_TOKENを使用した利用者の非公開LoRAの取得。
- 約30GBのモデル全量ダウンロード。
- CUDA上でのモデル読み込み・画像生成、顔や衣装の再現品質、速度・VRAM。
- RunPod外部HTTPプロキシ経由のブラウザー接続。

実Podでは起動時にCUDA BF16演算と実ノードのインポートを検査し、ダウンロード後にファイル構造・サイズを確認する。GPUでの最初の生成は、同梱ワークフローを開いてRunを押して確認する。

旧Gradio版の検証記録は [VALIDATION-gradio.md](VALIDATION-gradio.md)。
# MOSS LoRA one-command training launcher — 2026-10-26

Added `train.sh`, Windows dataset packaging/sending, and a detached RunPod worker.

Verified locally:

- 16 unit/integration tests passed (11 training contract tests and the 5 existing generation tests).
- Bundle round-trip preserves images/captions byte for byte. Missing captions/triggers, duplicate stems, traversal, symlinks, unexpected executable files, changed datasets/settings and damaged bundles are rejected.
- Detached process arguments and inherited job lock tested with mocks; duplicate starts do not launch another worker. A zero trainer exit without a valid final file is not reported as success.
- The existing Marian Queen dataset packaged successfully: 35 PNG + 35 TXT, 62,501,504-byte bundle, SHA256 `6bb725cf60466b7d416f5097fc06ac935c78d5012ca585c6eddea41753aa7ebb`. Windows sender `-CheckOnly` passed. No sender was started.
- Downloaded the exact 10 upstream trainer/source/license files and verified their normalized-LF SHA256 values against `training/revisions.json`.
- Installed the pinned Python dependencies in a local scratch environment; imported real Qwen3.5, Flux2 VAE, PEFT and bitsandbytes modules.
- Executed the actual upstream pre-cache/training modules without invoking their main GPU jobs. Both resolved the job-specific configuration, model, cache and output paths correctly, and found all 35 samples. All 35 images passed actual Pillow verification/decoding.
- Ran forward, backward and an AdamW update on a **small random MOSS model on CPU**, using the upstream model, gradient checkpointing and PEFT. Exported via the real upstream LoRA export function and validated its native MOSS keys/metadata. This is an API compatibility test, not a trained character LoRA.
- Python compilation, PowerShell parsing, Bash syntax (`train.sh`, updated `start.sh`) and `git diff --check` passed.

Not performed: live PC→RunPod transfer, Linux process detachment/flock on a real Pod, full model download, CUDA NF4 computation, GPU pre-cache/training, or output-quality assessment. The launcher runs CUDA BF16 and NF4 forward/backward checks before downloading weights on the Pod. GPU setup failures stop the job and retain a log; they are not retried automatically.

The source is pinned to AcademiaSD commit `a5751f9cb051399c4ccf1152ce095c95b8f246f1`, with model revision `ae628cc6ea7186ce8d1d4b4c20295a0573be4905`. Generated datasets, transfer codes, tokens and model weights are excluded from the public repository.

---
