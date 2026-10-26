"""Supply missing torchvision in the training venv without replacing CUDA torch."""
import importlib.util
import subprocess
import sys


# Exact stable pairs/builds published at https://pytorch.org/get-started/previous-versions/
# Fail closed for unknown versions; never ask pip to resolve a replacement torch stack.
WHEELS = {
    "2.9.0": ("0.24.0", {"cpu", "cu126", "cu128", "cu130"}),
    "2.9.1": ("0.24.1", {"cpu", "cu126", "cu128", "cu130"}),
    "2.10.0": ("0.25.0", {"cpu", "cu126", "cu128", "cu130"}),
    "2.11.0": ("0.26.0", {"cpu", "cu126", "cu128", "cu130"}),
    "2.12.0": ("0.27.0", {"cpu", "cu126", "cu130", "cu132"}),
    "2.12.1": ("0.27.1", {"cpu", "cu126", "cu130", "cu132"}),
    "2.13.0": ("0.28.0", {"cpu", "cu126", "cu130", "cu132"}),
}

VERIFY = """
import torch
import torchvision
from PIL import Image
from torchvision.transforms import functional as TF
image = TF.pil_to_tensor(Image.new('RGB', (8, 6), (20, 40, 60)))
assert image.shape == (3, 6, 8) and image.dtype == torch.uint8
assert image[:, 0, 0].tolist() == [20, 40, 60]
# Exercise the compiled CPU extension to catch torch/torchvision ABI mismatches.
boxes = torch.tensor([[0., 0., 2., 2.], [0., 0., 2., 2.]])
assert torchvision.ops.nms(boxes, torch.tensor([0.9, 0.8]), 0.5).tolist() == [0]
print(f'torchvision {torchvision.__version__}: transforms and CPU extension OK', flush=True)
"""


def wheel_for(torch_version, cuda_version):
    version, _, suffix = torch_version.partition("+")
    build = "cu" + cuda_version.replace(".", "") if cuda_version else "cpu"
    pair = WHEELS.get(version)
    if not pair or build not in pair[1] or (suffix and suffix != build):
        raise RuntimeError(
            f"No verified torchvision wheel for torch {torch_version}, CUDA {cuda_version}. "
            "The existing PyTorch stack was not changed. Install a matching torchvision "
            "wheel in this training venv, then resume."
        )
    return f"torchvision=={pair[0]}+{build}", f"https://download.pytorch.org/whl/{build}"


def ensure(torch_version, cuda_version):
    if importlib.util.find_spec("torchvision") is None:
        if sys.prefix == sys.base_prefix:
            raise RuntimeError("Missing torchvision: automatic installation requires a training venv.")
        package, index = wheel_for(torch_version, cuda_version)
        print(f"Installing missing {package}; keeping the existing PyTorch stack.", flush=True)
        subprocess.run([
            sys.executable, "-m", "pip", "install", "--no-deps", "--only-binary=:all:",
            "--index-url", index, package,
        ], check=True)
    # A fresh process avoids cached availability flags after installation. Existing
    # installations are checked, not overwritten if incompatible or broken.
    subprocess.run([sys.executable, "-c", VERIFY], check=True)


if __name__ == "__main__":
    import torch
    ensure(str(torch.__version__), torch.version.cuda)
