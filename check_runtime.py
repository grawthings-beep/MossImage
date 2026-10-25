"""Check the existing CUDA stack before downloading any model weights."""
import argparse
import importlib.metadata
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--constraints", type=Path)
    parser.add_argument("--imports", action="store_true")
    args = parser.parse_args()
    import torch

    version = tuple(int(p) for p in torch.__version__.split("+")[0].split(".")[:2])
    if version < (2, 9):
        raise SystemExit("MOSS-Image requires PyTorch >= 2.9. Use a newer RunPod PyTorch image.")
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is unavailable. Check that this is a GPU Pod with a CUDA PyTorch image.")
    if not torch.cuda.is_bf16_supported():
        raise SystemExit("This kit uses BF16. Select an Ampere-or-newer NVIDIA GPU.")
    x = torch.ones((128, 128), device="cuda", dtype=torch.bfloat16)
    y = x @ x
    torch.cuda.synchronize()
    if not torch.isfinite(y).all().item() or float(y[0, 0]) != 128.0:
        raise SystemExit("CUDA BF16 matrix multiplication failed.")
    gpu = torch.cuda.get_device_properties(0)
    print(json.dumps({"torch": torch.__version__, "cuda": torch.version.cuda,
                      "gpu": gpu.name, "vram_gib": round(gpu.total_memory / 2**30, 1)}, indent=2))
    if args.constraints:
        constraints = []
        for dist in importlib.metadata.distributions():
            name = dist.metadata.get("Name", "")
            if name.lower() in {"torch", "torchvision", "torchaudio", "triton"} or name.lower().startswith("nvidia-"):
                constraints.append(f"{name}=={dist.version}")
        args.constraints.write_text("\n".join(sorted(set(constraints))) + "\n", encoding="utf-8")
    if args.imports:
        from diffusers import AutoencoderKLFlux2, DiffusionPipeline
        from transformers import AutoModel, AutoTokenizer, Qwen3_5Model
        import accelerate
        import gradio
        import safetensors
        print("MOSS dependencies and Qwen3.5 imports: OK")


if __name__ == "__main__":
    main()
