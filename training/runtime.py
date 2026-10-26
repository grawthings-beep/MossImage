"""Provision a pinned MOSS trainer without changing the system CUDA environment."""
import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request

from common import HERE, digest, read_json, weights_header, write_json

KIT = HERE.parent


def receiver(root):
    installed = shutil.which("runpodctl")
    if installed and subprocess.run([installed, "receive", "--help"], stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=15).returncode == 0:
        return installed
    if platform.machine() not in {"x86_64", "AMD64"}:
        raise RuntimeError("Install a runpodctl version with the receive command for this CPU architecture.")
    target = root / "bin" / "runpodctl-2.14.0"
    expected = "2e0fd370a52a0fc7e43a6434a209348a4f6836fcdf1ad2b093b609e938138be9"
    if target.exists() and digest(target) == expected:
        return str(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    url = "https://github.com/runpod/runpodctl/releases/download/v2.14.0/runpodctl-linux-amd64"
    with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
        staged = Path(tmp) / "runpodctl"
        with urllib.request.urlopen(url, timeout=90) as response, staged.open("wb") as out:
            shutil.copyfileobj(response, out)
        if digest(staged) != expected:
            raise ValueError("runpodctl download checksum mismatch")
        staged.chmod(0o700)
        staged.replace(target)
    return str(target)


def pins():
    return read_json(HERE / "revisions.json")


def canonical_source(data):
    return data.replace(b"\r\n", b"\n").rstrip() + b"\n"


def sources(root):
    pin = pins()
    source = root / "sources" / pin["trainer_revision"]
    for name, expected in pin["files"].items():
        path = source / name
        if path.exists():
            if path.is_symlink() or digest(path) != expected:
                raise ValueError(f"Trainer source modified: {path}")
            continue
        url = f"https://raw.githubusercontent.com/{pin['trainer_repository']}/{pin['trainer_revision']}/{name}"
        with urllib.request.urlopen(url, timeout=90) as response:
            data = canonical_source(response.read())
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"Trainer download checksum mismatch: {name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
    return source


def check_imports(gpu=True):
    import torch
    import torchvision.transforms.functional
    from transformers import Qwen3_5Model, AutoTokenizer
    from diffusers import AutoencoderKLFlux2, FlowMatchEulerDiscreteScheduler
    from peft import LoraConfig, get_peft_model
    from bitsandbytes.nn import Linear4bit
    from safetensors.torch import load_file
    if gpu:
        # Verify the actual quantized training kernel, not just a successful import.
        layer = Linear4bit(64, 64, bias=False, compute_dtype=torch.bfloat16, quant_type="nf4").to("cuda")
        layer.requires_grad_(False)
        x = torch.randn(2, 64, device="cuda", dtype=torch.bfloat16, requires_grad=True)
        y = layer(x)
        y.float().square().mean().backward()
        torch.cuda.synchronize()
        if not torch.isfinite(y).all() or x.grad is None or not torch.isfinite(x.grad).all():
            raise RuntimeError("NF4 forward/backward test failed")
    print("MOSS imports and" + (" CUDA NF4 forward/backward" if gpu else " CPU import") + " check: OK", flush=True)


def setup(root):
    root.mkdir(parents=True, exist_ok=True)
    constraints = root / "cuda-constraints.txt"
    subprocess.run([sys.executable, str(KIT / "check_runtime.py"), "--constraints", str(constraints)], check=True)
    identity = hashlib.sha256((HERE / "requirements.txt").read_bytes() + constraints.read_bytes()
                              + (HERE / "revisions.json").read_bytes()).hexdigest()[:16]
    venv = root / "venvs" / identity
    python = venv / "bin" / "python"
    if not python.exists():
        subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", str(venv)], check=True)
    ready = venv / "moss-ready.json"
    if not ready.exists():
        subprocess.run([str(python), "-m", "pip", "install", "--constraint", str(constraints),
                        "-r", str(HERE / "requirements.txt")], check=True)
    # Check again even if the environment was prepared in a previous session.
    subprocess.run([str(python), str(KIT / "check_runtime.py")], check=True)
    subprocess.run([str(python), str(Path(__file__)), "check"], check=True)
    source = sources(root)
    with (venv / "installed-packages.txt").open("w") as out:
        subprocess.run([str(python), "-m", "pip", "freeze"], stdout=out, check=True)
    write_json(ready, {"identity": identity, "trainer_revision": pins()["trainer_revision"]})
    write_json(root / "runtime.json", {"python": str(python), "source": str(source)})


def prepare_job(root, job_dir, job):
    runtime = read_json(root / "runtime.json")
    source = Path(runtime["source"])
    # Copy, do not symlink: upstream project_layout derives the job root from __file__.
    for name, expected in pins()["files"].items():
        target = job_dir / name
        if target.exists():
            if target.is_symlink() or digest(target) != expected:
                raise ValueError(f"Job trainer source changed: {target}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)
    cfg = configurations(root, job_dir, job)
    for relative, value in cfg.items():
        path = job_dir / relative
        if path.exists() and read_json(path) != value:
            raise ValueError(f"Existing settings changed: {path}; choose a new job name")
        write_json(path, value)
    return runtime


def configurations(root, job_dir, job):
    name, trigger, r = job["name"], job["trigger"], job["recipe"]
    shared = {"project_name": name, "trigger_word": trigger,
              "model_id": str(root / "Models" / pins()["model_revision"]),
              "dataset_path": str(job_dir / "train"),
              "cache_dir": f"./Cache_Data/cached_data_mossimage_{name}"}
    pre = {**shared, "target_area": r["resolution"] ** 2, "max_side": r["max_side"],
           "multiple": 16, "text_encoder": "BF16_offload", "lora_type": "normal", "preview_custom_prompt": ""}
    train = {**shared, **{k: v for k, v in r.items() if k not in {"resolution", "max_side"}},
             "output_dir": f"./Outputs/mossimage_lora_output_{name}", "base_model": "base",
             "use_rslora": False, "use_loraplus": False, "use_lokr": False, "use_turbo": False,
             "timestep_sampling": "moss", "preview_every": 0, "weight_decay": 0.0, "max_grad_norm": 1.0}
    return {"settings/pre_cache_settings_mossimage.json": pre,
            "settings/train_settings_mossimage.json": train,
            f"Cache_Data/cached_data_mossimage_{name}/pre_cache_settings_{name}.json": pre,
            f"Outputs/mossimage_lora_output_{name}/train_settings_{name}.json": train}


def validate_images(job_dir, job):
    from PIL import Image
    for name in job["files"]:
        if name.endswith(".txt"):
            continue
        path = job_dir / "train" / name
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            im.load()
            if min(im.size) < 16 or getattr(im, "n_frames", 1) != 1:
                raise ValueError(f"Image too small or animated: {name}")
    print(f"Image decode check: {job['images']} OK", flush=True)


def download_models(root):
    from huggingface_hub import HfApi, snapshot_download
    import fnmatch
    pin = pins()
    model = root / "Models" / pin["model_revision"]
    model.mkdir(parents=True, exist_ok=True)
    patterns = ["transformer/*", "text_encoder_BF16/*", "tokenizer/*", "vae/*", "model_index.json", "LICENSE", "NOTICE.md"]
    info = HfApi().model_info(pin["model_repository"], revision=pin["model_revision"], files_metadata=True)
    wanted = {f.rfilename: f.size for f in info.siblings if any(fnmatch.fnmatch(f.rfilename, p) for p in patterns)}
    needed = sum(n for name, n in wanted.items() if not (model / name).exists()
                 or (model / name).stat().st_size != n)
    if shutil.disk_usage(root).free < needed + 8 * 1024**3:
        raise RuntimeError(f"Need {needed / 1024**3 + 8:.1f} GiB free for models/cache/checkpoints.")
    snapshot_download(pin["model_repository"], revision=pin["model_revision"], local_dir=model,
                      allow_patterns=patterns, max_workers=2)
    for name, size in wanted.items():
        path = model / name
        if not path.is_file() or path.stat().st_size != size:
            raise ValueError(f"Incomplete model download: {name}")
        if name.endswith(".safetensors"):
            weights_header(path)
    write_json(model / "moss-download-complete.json", {"revision": pin["model_revision"], "files": wanted})
    print("Pinned MOSS Base NF4, Qwen BF16 and VAE downloads: OK", flush=True)


def output_dir(job_dir, job):
    return job_dir / "Outputs" / f"mossimage_lora_output_{job['name']}"


def validate_resume(job_dir, job):
    import torch
    from safetensors.torch import load_file
    out = output_dir(job_dir, job)
    required = [out / "current_step.txt", out / "optimizer.pt",
                out / "resume_checkpoint/adapter_model.safetensors", out / "resume_checkpoint/adapter_config.json"]
    if not any(p.exists() for p in required):
        return
    if not all(p.is_file() for p in required):
        raise ValueError("Incomplete resume checkpoint; preserve it and use a new job name for a fresh run.")
    step = int(required[0].read_text().strip())
    if not 0 < step <= job["recipe"]["total_steps"]:
        raise ValueError("Invalid resume step")
    config = read_json(required[3])
    if (config.get("r"), config.get("lora_alpha")) != (job["recipe"]["lora_rank"], job["recipe"]["lora_alpha"]):
        raise ValueError("Resume rank/alpha mismatch")
    weights = load_file(str(required[2]), device="cpu")
    if not weights or not all(torch.isfinite(v).all() for v in weights.values()):
        raise ValueError("Invalid resume weights")
    state = torch.load(required[1], map_location="cpu", weights_only=True)
    if not state.get("param_groups") or not state.get("state"):
        raise ValueError("Invalid optimizer checkpoint")
    print(f"Resume checkpoint verified: step {step}", flush=True)


def validate_cache(job_dir, job):
    import torch
    cache = job_dir / "Cache_Data" / f"cached_data_mossimage_{job['name']}"
    stems = {Path(n).stem for n in job["files"] if not n.endswith(".txt")}
    if {p.name[:-10] for p in cache.glob("*_latent.pt")} != stems:
        raise ValueError("Cache image count/stems mismatch")
    for stem in stems:
        latent = torch.load(cache / f"{stem}_latent.pt", map_location="cpu", weights_only=True)
        embed = torch.load(cache / f"{stem}_embed.pt", map_location="cpu", weights_only=True)
        if (latent.ndim != 4 or latent.shape[:2] != (1, 128) or min(latent.shape[-2:]) < 1
                or embed.ndim != 2 or embed.shape[1] != 4096 or embed.shape[0] < 1
                or not torch.isfinite(latent).all() or not torch.isfinite(embed).all()):
            raise ValueError(f"Invalid cached tensors: {stem}")
    print(f"Cache tensors verified: {len(stems)}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["setup", "check", "images", "models", "cache", "resume"])
    parser.add_argument("--root", type=Path)
    parser.add_argument("--job", type=Path)
    args = parser.parse_args()
    if args.action == "setup":
        setup(args.root)
    elif args.action == "check":
        check_imports()
    elif args.action == "models":
        download_models(args.root)
    else:
        job = read_json(args.job / "job.json")
        {"images": validate_images, "cache": validate_cache, "resume": validate_resume}[args.action](args.job, job)


if __name__ == "__main__":
    main()
