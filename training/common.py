"""Small, dependency-free bundle and job contract shared by Windows and Linux."""
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import struct
import tarfile

HERE = Path(__file__).resolve().parent
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_FILE = 256 * 1024**2
MAX_TOTAL = 20 * 1024**3


def digest(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def valid_name(name):
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_]{0,63}", name):
        raise ValueError("Job name must use lowercase letters, digits and underscores (1-64 chars).")
    return name


def recipe_checked(recipe):
    defaults = read_json(HERE / "recipe.json")
    if not isinstance(recipe, dict) or set(recipe) != set(defaults):
        raise ValueError("Recipe keys must match training/recipe.json.")
    for key in defaults:
        value = recipe[key]
        if key == "lr_scheduler":
            if value not in {"constant", "cosine", "linear"}:
                raise ValueError("Unsupported LR scheduler")
        elif key == "lr":
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 0.01:
                raise ValueError("Invalid learning rate")
        elif type(value) is not int or value < (0 if key == "warmup_steps" else 1):
            raise ValueError(f"Invalid integer setting: {key}")
    if recipe["resolution"] not in (512, 768, 1024, 1280, 1536):
        raise ValueError("Supported resolutions: 512, 768, 1024, 1280, 1536")
    if recipe["max_side"] < recipe["resolution"] or recipe["max_side"] % 16:
        raise ValueError("max_side must be >= resolution and a multiple of 16")
    if recipe["warmup_steps"] >= recipe["total_steps"]:
        raise ValueError("warmup_steps must be less than total_steps")
    return recipe


def validate_pairs(files, trigger):
    """files: mapping of a flat, exact filename to bytes; never rewrite captions."""
    if not isinstance(trigger, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,100}", trigger):
        raise ValueError("Trigger must be one ASCII alphanumeric/underscore token.")
    images, captions, folded = {}, set(), set()
    for name, data in files.items():
        p = PurePosixPath(name)
        if (len(p.parts) != 1 or "\\" in name or ":" in name or p.name != name
                or name.startswith(".") or p.stem.startswith("_") or len(data) > MAX_FILE):
            raise ValueError(f"Unsupported dataset filename/size: {name}")
        if name.casefold() in folded:
            raise ValueError(f"Case-insensitive duplicate: {name}")
        folded.add(name.casefold())
        suffix = p.suffix.lower()
        if suffix in IMAGE_EXTS:
            if p.stem in images:
                raise ValueError(f"Duplicate image stem: {p.stem}")
            images[p.stem] = name
            valid = ((suffix == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n"))
                     or (suffix in {".jpg", ".jpeg"} and data.startswith(b"\xff\xd8\xff"))
                     or (suffix == ".webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP"))
            if not valid:
                raise ValueError(f"Invalid image signature: {name}")
        elif p.suffix == ".txt":
            captions.add(p.stem)
            caption = data.decode("utf-8-sig").strip()
            # The upstream reader does not strip a BOM; reject instead of altering the dataset.
            if data.startswith(b"\xef\xbb\xbf") or not re.search(
                    rf"(?<![A-Za-z0-9_]){re.escape(trigger)}(?![A-Za-z0-9_])", caption):
                raise ValueError(f"Caption missing trigger (or has UTF-8 BOM): {name}")
        else:
            raise ValueError(f"Only images and matching .txt captions are supported: {name}")
    if not images or set(images) != captions:
        raise ValueError("Every image must have an exact matching .txt caption; orphan captions are rejected.")
    if any(s.endswith(("_before", "_after")) for s in images):
        raise ValueError("This launcher is for normal character LoRAs; before/after edit datasets are not supported.")
    return len(images)


def validate_job(job):
    if not isinstance(job, dict) or set(job) != {"schema", "name", "trigger", "images", "recipe", "files"}:
        raise ValueError("Unexpected job manifest fields")
    if job["schema"] != 1:
        raise ValueError("Unsupported job schema")
    valid_name(job["name"])
    recipe_checked(job["recipe"])
    if type(job["images"]) is not int or not 1 <= job["images"] <= 10000:
        raise ValueError("Invalid image count")
    if not isinstance(job["files"], dict) or len(job["files"]) != job["images"] * 2:
        raise ValueError("Manifest file count mismatch")
    for info in job["files"].values():
        if (not isinstance(info, dict) or set(info) != {"sha256", "bytes"}
                or not re.fullmatch(r"[0-9a-f]{64}", str(info["sha256"]))
                or type(info["bytes"]) is not int or not 0 < info["bytes"] <= MAX_FILE):
            raise ValueError("Invalid manifest file entry")
    return job


def read_bundle(archive, expected_sha):
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha) or digest(archive) != expected_sha:
        raise ValueError("Bundle SHA256 mismatch; nothing was extracted.")
    files, job, total = {}, None, 0
    with tarfile.open(archive, "r:gz") as source:
        seen = set()
        for m in source:
            p = PurePosixPath(m.name)
            if (not m.isfile() or m.name in seen or "\\" in m.name or ":" in m.name
                    or ".." in p.parts or p.is_absolute() or str(p) != m.name
                    or not 0 < m.size <= MAX_FILE):
                raise ValueError(f"Unsafe or duplicate bundle member: {m.name}")
            seen.add(m.name)
            total += m.size
            if total > MAX_TOTAL or len(seen) > 20001:
                raise ValueError("Bundle too large")
            if m.name != "job.json" and not (len(p.parts) == 2 and p.parts[0] == "train"):
                raise ValueError(f"Unexpected bundle member: {m.name}")
            data = source.extractfile(m).read()
            if m.name == "job.json":
                job = validate_job(json.loads(data))
            else:
                files[p.name] = data
    if job is None or set(job["files"]) != set(files):
        raise ValueError("Bundle manifest and dataset do not match")
    for name, data in files.items():
        if job["files"][name] != {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}:
            raise ValueError(f"Dataset checksum mismatch: {name}")
    if validate_pairs(files, job["trigger"]) != job["images"]:
        raise ValueError("Image count mismatch")
    return job, files


def verify_dataset(path, job):
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Dataset directory missing or symlinked")
    actual = {p.name for p in path.iterdir()}
    if actual != set(job["files"]):
        raise ValueError("Existing dataset differs; use a new job name")
    for name, info in job["files"].items():
        p = path / name
        if p.is_symlink() or not p.is_file() or p.stat().st_size != info["bytes"] or digest(p) != info["sha256"]:
            raise ValueError(f"Existing dataset modified: {name}; nothing was overwritten")


def weights_header(path):
    with Path(path).open("rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        if not 2 <= n <= min(100_000_000, path.stat().st_size - 8):
            raise ValueError("Invalid safetensors header length")
        header = json.loads(f.read(n))
    tensors = [v for k, v in header.items() if k != "__metadata__"]
    if not tensors or path.stat().st_size != 8 + n + max(v["data_offsets"][1] for v in tensors):
        raise ValueError("Truncated safetensors output")
    return header


def verify_final(path, job):
    header = weights_header(path)
    meta = header.get("__metadata__", {})
    if int(meta.get("ss_steps", -1)) != job["recipe"]["total_steps"]:
        raise ValueError("Final LoRA step count does not match the requested job")
    if (meta.get("project_name") != job["name"] or meta.get("trigger_word") != job["trigger"]
            or meta.get("ss_sd_model_name") != "MOSS-Image-Base"
            or int(meta.get("ss_network_dim", -1)) != job["recipe"]["lora_rank"]):
        raise ValueError("Final LoRA identity/base model/rank differs from this job")
    if not any(k.startswith("diffusion_model.layers.") and k.endswith(".lora_A.weight") for k in header):
        raise ValueError("Output is not a native MOSS LoRA")
    return header
