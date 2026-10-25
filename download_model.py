"""Download one pinned official bundle directly into persistent storage."""
import argparse
import json
import shutil
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True, type=Path)
    args = parser.parse_args()
    pins = json.loads(Path(__file__).with_name("revisions.json").read_text(encoding="utf-8"))
    destination = args.runtime / "models" / "MOSS-Image-SFT"
    destination.mkdir(parents=True, exist_ok=True)
    info = HfApi().model_info(pins["model_id"], revision=pins["model_revision"], files_metadata=True)
    pending = sum(
        max(0, (file.size or 0) - ((destination / file.rfilename).stat().st_size
            if (destination / file.rfilename).is_file() else 0))
        for file in info.siblings
    )
    free = shutil.disk_usage(destination).free
    if free < pending + 5 * 2**30:
        raise SystemExit(f"Need {(pending / 2**30) + 5:.1f} GiB free; have {free / 2**30:.1f} GiB.")
    snapshot_download(
        pins["model_id"], revision=pins["model_revision"],
        local_dir=str(destination), max_workers=4,
    )
    (destination / ".moss-revision").write_text(pins["model_revision"] + "\n", encoding="utf-8")
    print(f"Pinned model downloaded: {destination}")


if __name__ == "__main__":
    main()
