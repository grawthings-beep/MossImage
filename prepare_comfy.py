"""Download the requested weights and install the ready-to-use workflow."""
import argparse
import json
from pathlib import Path
import shutil
import struct

from huggingface_hub import HfApi, hf_hub_download

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


RETIRED_WORKFLOWS = (
    'moss_marian_queen2.json',
    'moss_marian_queen2_1152x1536_25.json',
    'moss_scarlet_goddeath_1152x1536_25.json',
    'MOSS_01_scarlet_goddeath_1152x1536_25.json',
    'MOSS_02_marian_queen2_1152x1536_25.json',
    'MOSS_03_CharRef_1152x1536_25.json',
    'MOSS_04_EditHQ_v5_25.json',
    'MOSS_05_CottonMoss_1152x1536_12.json',
    'MOSS_06_CottonMoss_marian_queen2_1152x1536_12.json',
    'MOSS_07_CottonMoss_scarlet_goddeath_1152x1536_12.json',
    'MOSS_08_CottonMoss_marciana_marine_study_1152x1536_12.json',
    'MOSS_09_CottonMoss_realskin_1152x1536_12.json',
    'MOSS_08_Quality2x_marciana_marine_study.json',
    'MOSS_10_Fast2x_marciana_marine_study.json',
    'MOSS_08_Quality2x_marciana_marine_study_original_33.json',
    'MOSS_08_Quality2x_marciana_marine_study_30_v1.json',
    'MOSS_08_Quality2x_marian_last_affection2_3k.json',
    'MOSS_10_Fast2x_marciana_marine_study_original_33.json',
    'MOSS_10_Fast2x_marciana_marine_study_30_v1.json',
    'MOSS_10_Fast2x_marian_last_affection2_3k.json',
)


def install_workflows(comfy):
    profile = comfy / 'user/default'
    folder = profile / 'workflows'
    folder.mkdir(parents=True, exist_ok=True)
    for source in sorted((KIT / 'workflows').glob('*.json')):
        destination = folder / source.name
        if not destination.exists():
            temporary = folder / ('.' + source.name + '.installing')
            shutil.copyfile(source, temporary)
            temporary.replace(destination)
    archive = profile / 'moss-workflow-archive'
    for name in RETIRED_WORKFLOWS:
        previous = folder / name
        if not previous.is_file():
            continue
        archive.mkdir(exist_ok=True)
        target = archive / name
        index = 1
        while target.exists():
            target = archive / f'{previous.stem}-{index}.json'
            index += 1
        previous.rename(target)


def prepare_generation_model(runtime):
    from studio.assets import Downloads
    downloads = Downloads(runtime)
    for name, label in [('cottonmoss', 'CottonMoss Turbo INT8'),
                        ('sft', 'MOSS-Image SFT BF16'),
                        ('marciana_marine_study', 'マルチャーナの30枚版LoRA'),
                        ('marciana_marine_study_original', 'マルチャーナの元の33枚版LoRA'),
                        ('marian_last_affection2_3k', 'マリアンのラストアフェクションLoRA')]:
        print(f'MOSS_STAGE={label}を準備しています', flush=True)
        downloads.ensure(name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True, type=Path)
    args = parser.parse_args()
    pins = json.loads((KIT / "comfy-revisions.json").read_text(encoding="utf-8"))
    comfy = args.runtime / "ComfyUI"
    models = comfy / "models"
    models.mkdir(parents=True, exist_ok=True)

    prepare_generation_model(args.runtime)
    missing = [name for name in pins["model_files"] if not valid_weights(models / name)]
    if missing:
        info = HfApi(token=False).model_info(
            pins["model_id"], revision=pins["model_revision"], files_metadata=True,
        )
        sizes = {f.rfilename: f.size for f in info.siblings}
        needed = sum(sizes[name] for name in missing) + 2 * 2**30
        free = shutil.disk_usage(models).free
        if free < needed:
            raise SystemExit(
                f"Need {needed / 2**30:.1f} GiB free for pending downloads; "
                f"have {free / 2**30:.1f} GiB."
            )
    for name in missing:
        path = hf_hub_download(
            pins["model_id"], name, revision=pins["model_revision"],
            local_dir=models, token=False,
        )
        if not valid_weights(Path(path)):
            raise SystemExit(f"Model download is incomplete: {path}")
    install_workflows(comfy)
    print("MOSS_STAGE=マリアンとマルチャーナの高速版・高精細版ワークフローを配置しました")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(f'MOSS_ERROR={error}', flush=True)
        raise SystemExit(1) from None

