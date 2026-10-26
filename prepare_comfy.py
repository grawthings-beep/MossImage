"""Download the requested weights and install the ready-to-use workflow."""
import argparse
import getpass
import json
import os
from pathlib import Path
import shutil
import struct
import sys

from huggingface_hub import HfApi, hf_hub_download
from huggingface_hub.errors import HfHubHTTPError
from characters import CHARACTERS

KIT = Path(__file__).resolve().parent


def valid_weights(path):
    try:
        with path.open("rb") as file:
            length = struct.unpack("<Q", file.read(8))[0]
            if not 2 <= length <= 100_000_000:
                return False
            header = json.loads(file.read(length))
        tensors = [v for k, v in header.items() if k != "__metadata__"]
        return bool(tensors) and path.stat().st_size == (
            8 + length + max(t["data_offsets"][1] for t in tensors)
        )
    except (OSError, ValueError, KeyError, TypeError, struct.error):
        return False


def download_lora(models, pins):
    destination = models / "loras" / pins["lora_file"]
    if valid_weights(destination):
        print(f"LoRA: {destination.name} is complete.")
        return
    token = os.environ.get("HF_TOKEN") or None
    try:
        path = hf_hub_download(
            pins["lora_id"], pins["lora_file"],
            local_dir=destination.parent, token=token,
        )
    except HfHubHTTPError as error:
        if error.response.status_code not in (401, 403, 404):
            raise
        if token or not sys.stdin.isatty():
            raise SystemExit(
                f"LoRA access failed. Set HF_TOKEN with read access to {pins['lora_id']}, "
                f"or upload the saved LoRA to {destination}. The token is not printed."
            ) from None
        print(f"LoRA repository requires access: {pins['lora_id']}")
        token = getpass.getpass("Hugging Face read token (hidden, not saved): ").strip()
        if not token:
            raise SystemExit(f"Upload the saved LoRA to {destination}, then run start.sh again.")
        try:
            path = hf_hub_download(
                pins["lora_id"], pins["lora_file"],
                local_dir=destination.parent, token=token,
            )
        except HfHubHTTPError:
            raise SystemExit(
                f"LoRA access failed. Check token access to {pins['lora_id']}, "
                f"or upload the saved file to {destination}."
            ) from None
    if not valid_weights(Path(path)):
        raise SystemExit(f"LoRA download is incomplete: {path}")


def install_workflow(comfy, pins):
    destination = comfy / "user" / "default" / "workflows" / pins["workflow_file"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copyfile(KIT / "workflows" / pins["workflow_file"], destination)
    print(f"Workflow: {destination} (existing edits are preserved)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True, type=Path)
    args = parser.parse_args()
    pins = json.loads((KIT / "comfy-revisions.json").read_text(encoding="utf-8"))
    comfy = args.runtime / "ComfyUI"
    models = comfy / "models"
    models.mkdir(parents=True, exist_ok=True)

    # Resolve private-file access before downloading the much larger public models.
    download_lora(models, pins)
    for character in CHARACTERS.values():
        if character['file'] != pins['lora_file']:
            download_lora(models, {'lora_id': character['repo'], 'lora_file': character['file']})
    info = HfApi(token=False).model_info(
        pins["model_id"], revision=pins["model_revision"], files_metadata=True,
    )
    sizes = {f.rfilename: f.size for f in info.siblings}
    missing = [name for name in pins["model_files"] if not valid_weights(models / name)]
    needed = sum(sizes[name] for name in missing) + 2 * 2**30
    free = shutil.disk_usage(models).free
    if missing and free < needed:
        raise SystemExit(
            f"Need {needed / 2**30:.1f} GiB free for pending downloads; "
            f"have {free / 2**30:.1f} GiB."
        )
    for name in pins["model_files"]:
        if name not in missing:
            print(f"Already downloaded: {name}")
            continue
        path = hf_hub_download(
            pins["model_id"], name, revision=pins["model_revision"],
            local_dir=models, token=False,
        )
        if not valid_weights(Path(path)):
            raise SystemExit(f"Model download is incomplete: {path}")
    install_workflow(comfy, pins)
    for character in CHARACTERS.values():
        install_workflow(comfy, {'workflow_file': character['workflow']})
    print("MOSS-Image Base + Marian Queen / Scarlet Goddeath LoRAs are ready.")


if __name__ == "__main__":
    main()

