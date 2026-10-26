"""Pack an existing captioned train directory. No image or caption transformations."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile

from common import HERE, MAX_FILE, MAX_TOTAL, digest, read_bundle, read_json, recipe_checked, valid_name, validate_pairs, write_json


def build(dataset, name, trigger, output, recipe=None):
    valid_name(name)
    recipe = recipe_checked(recipe or read_json(HERE / "recipe.json"))
    dataset = Path(dataset).resolve()
    files = {}
    total = 0
    for p in sorted(dataset.iterdir()):
        if p.is_symlink() or not p.is_file():
            raise ValueError(f"Dataset must be a flat folder of images and captions: {p.name}")
        total += p.stat().st_size
        if p.stat().st_size > MAX_FILE or total > MAX_TOTAL:
            raise ValueError("Dataset/file too large")
        files[p.name] = p.read_bytes()
    if sum(map(len, files.values())) > MAX_TOTAL:
        raise ValueError("Dataset too large")
    count = validate_pairs(files, trigger)
    job = {"schema": 1, "name": name, "trigger": trigger, "images": count, "recipe": recipe,
           "files": {n: {"sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)} for n, b in files.items()}}
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    bundle = output / f"moss_{name}_run.tar.gz"
    with tempfile.TemporaryDirectory(dir=output) as tmp:
        staged = Path(tmp) / bundle.name
        with staged.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as zipped:
            with tarfile.open(fileobj=zipped, mode="w") as tar:
                members = {"job.json": (json.dumps(job, sort_keys=True) + "\n").encode(),
                           **{f"train/{n}": b for n, b in files.items()}}
                for name_in_tar, data in members.items():
                    info = tarfile.TarInfo(name_in_tar)
                    info.size, info.mode, info.mtime = len(data), 0o600, 0
                    tar.addfile(info, io.BytesIO(data))
        sha = digest(staged)
        read_bundle(staged, sha)
        if bundle.exists():
            if digest(bundle) != sha:
                raise ValueError("A different bundle already exists under this name; choose a new job name.")
        else:
            staged.rename(bundle)
    report = {"name": name, "bundle": str(bundle), "sha256": sha, "bytes": bundle.stat().st_size,
              "images": count, "steps": recipe["total_steps"], "trigger": trigger}
    report_path = output / f"moss_{name}_validation.json"
    write_json(report_path, report)
    return report_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path, help="Folder containing image/.txt pairs")
    parser.add_argument("--name", required=True)
    parser.add_argument("--trigger", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("training-bundles"))
    parser.add_argument("--recipe", type=Path, help="Optional full replacement for training/recipe.json")
    args = parser.parse_args()
    report = build(args.dataset, args.name, args.trigger, args.output_dir,
                   read_json(args.recipe) if args.recipe else None)
    print(f"READY: {report}")
    print(json.dumps(read_json(report), indent=2))


if __name__ == "__main__":
    main()
