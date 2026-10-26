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

# Manga Studio — 2026-10-27

Added `/studio/` behind the existing login, a server-owned persistent queue, official-format layout prompts, whole-page/per-panel generation, optional high-resolution LoHa, CharRef, SFT-based Edit HQ, Japanese lettering, portable SVG/PNG/ZIP exports, and `background.sh` for detached startup.

Verified locally:

- **29 unit/integration tests passed**, including all 16 existing generation/training tests. New coverage includes authenticated Studio APIs, same-origin mutation checks, chunked uploads, optimistic revisions, idempotent job creation, browser-independent execution, reopening the database and rejoining a running prompt, recovery from a saved output without Comfy history, targeted cancellation and concurrent resume, preservation of completed panels, crop-edit pixels outside the rectangle, and Japanese PNG/SVG/ZIP exports.
- The pinned **real ComfyUI validator accepted 18 graph variants**: four character/backbone modes, two sampling presets, both VAE choices, high-resolution adapter combinations, and edit graphs. Temporary empty files supplied model **names only**; no full model weights were loaded.
- Executed the **real native `TextEncodeMOSSImageEdit` node** with CPU tensors and stub CLIP/VAE objects. Verified expansion of `images.image_0`, reference vision downscaling, and `index_timestep_zero_isolated` latent conditioning. This tests wiring, not learned inference.
- Read only public safetensors headers and checked native loader keys/shapes against a meta-device MOSS model: HiRes v0.4 **120** adapters, CharRef v2 **252**, Edit HQ armV6 **252**. All mapped to native patches. This is separate from the earlier Marian LoRA's 252-adapter check.
- Started the actual ComfyUI on CPU via `launch_comfy.py`. Authenticated ComfyUI, `/studio/`, Studio bootstrap, MOSS edit-node discovery, saved workflows, WebSocket status and process shutdown passed.
- Headless Chrome at **1440px desktop and 390px iPhone width**: editing and autosave/reload, vertical Japanese preview, PNG download, page and sequential panel jobs, closing the page while generation continued, reconnecting to results, adopting panels with clean gutters, crop-edit controls and saved targets passed. Extra browser checks covered reference upload, loss of the HTTP response after job acceptance followed by an idempotent retry, and drag-to-move persistence. **Images in these UI tests were synthetic fixtures, not MOSS-generated manga.** No JavaScript page errors or mobile horizontal overflow were detected. Preview/export screenshots were visually inspected.
- Downloaded and SHA256-verified the pinned Japanese Noto font and OFL license. SVGs embed the font/license; ZIPs also include `OFL.txt`. Python/JavaScript/Bash syntax and `git diff --check` passed.

Reproduce the native graph check:

```bash
python tests/validate_comfy_studio.py --comfy /workspace/moss-image-runtime/ComfyUI
```

To include the Japanese rendering integration in the unit suite, set `MOSS_TEST_FONT` to the downloaded `studio/fonts/NotoSansCJKjp-Regular.otf`, with `OFL.txt` beside it. That one test is skipped if the font is not provided; the other tests do not download anything.

Not verified: actual iOS Safari/WebKit, Linux/RunPod process detachment, RunPod external proxy behavior, full download of optional weights, full-weight CUDA generation/editing, model combinations' visual quality, identity consistency across manga panels, VRAM or speed. The high-resolution adapter and CharRef/Edit HQ are optional tools, not evidence that a first generation will achieve final artwork quality. No paid Pod was created or used for this implementation.

## Reverse-proxy write rejection fix — 2026-10-27

The original Studio guard compared the browser's `Origin` directly with the upstream `Host`. A reverse proxy that rewrites the host could therefore reject legitimate saves and generation requests with “同じ画面から操作してください。” Replaced that comparison with a per-server, cryptographically random CSRF token delivered through the authenticated bootstrap. Mutations require the token; Studio does not enable CORS. The browser refreshes an expired token and retries once, before any mutation has been executed. Login protection is unchanged.

- **33 tests passed**, including public-Origin/internal-Host writes, refusal of absent/incorrect tokens even with forged forwarding headers, lack of cross-origin read/preflight permission, and scoped restart process selection with PID-reuse checks.
- Browser integration through a middleware that rewrites `Host` passed autosave, image upload and generation submission. Forced stale tokens recovered automatically for both JSON and Blob requests; JSON was not double encoded and no page JavaScript errors occurred. Generated pixels remained synthetic fixtures.
- Added `bash background.sh --restart` for updating an already running instance. It selects only this checkout's launcher with the matching runtime and that runtime's ComfyUI backend, excludes PID 1 and unrelated training jobs, rechecks process identity before signalling, and waits for the runtime lock to be released before starting. Process selection/signalling were tested with a simulated `/proc` and mocked signals; an actual Linux/RunPod restart remains unverified here.

Added `bash background.sh --stop` for switching the same Pod to LoRA training. Three lifecycle tests passed, including a stop-only test verifying runtime-lock release without relaunching the generation server. The existing process-selection/PID-reuse protections are shared with restart. The stop operation does not stop other training jobs or claim that the GPU is otherwise idle.

## Missing torchvision in a torch-only Pod — 2026-10-27

The user's RunPod log confirmed successful CUDA checks on torch 2.9.1+cu128 / RTX PRO 6000 Blackwell, then failed at the trainer's torchvision import. The training setup now supplies a missing torchvision from the exact official version/build pair inside its existing venv, using `--no-deps --only-binary=:all:`. It checks existing installations without replacing them, and stops for unknown repair pairs or failed transforms/extension checks. This check also runs when the venv already has a ready marker. Venv identity and received datasets are unchanged; failed setup jobs can use `train.sh resume`.

- **41 unit/integration tests passed**, including missing-package repair arguments, refusal to modify system Python, unknown/mismatched-build refusal, preservation of existing installations, and setup ordering with/without a ready marker.
- Executed real Pillow-to-tensor conversion and the compiled CPU NMS operation with torch 2.9.1+cpu / torchvision 0.24.1+cpu in the local test environment.
- Downloaded the official Linux CPython 3.12 wheel `torchvision-0.24.1+cu128-cp312-cp312-manylinux_2_28_x86_64.whl` (8,049,914 bytes), verified its published SHA256 `cf84eae1d2d12a7d261a7496eca00dd927b71792011b1e84d4162c950eb3201d`, and inspected metadata requiring `torch==2.9.1`. Compatibility reference: [PyTorch previous versions](https://pytorch.org/get-started/previous-versions/).
- `git diff --check` passed. The actual Linux CUDA wheel installation and resumed GPU pre-cache/training remain to be confirmed on the user's Pod; local CPU checks do not establish GPU training success.
