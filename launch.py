"""Run the official UI with persistent output and per-Pod login credentials."""
import argparse
import json
import os
from pathlib import Path
import secrets
import sys


def credentials(path):
    if not path.exists():
        value = {"username": "moss", "password": secrets.token_urlsafe(18)}
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(value, file)
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, default=Path(os.getenv("MOSS_HOME", "/workspace/moss-image-runtime")))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "7860")))
    parser.add_argument("--profile", choices=["auto", "16gb", "24gb", "48gb"], default="auto")
    parser.add_argument("--smoke", action="store_true", help="Generate and save one 1024px / 50-step image, then exit")
    parser.add_argument("--check-ui", action="store_true", help="Build the UI without weights or GPU execution")
    args = parser.parse_args()
    root = args.runtime.resolve()
    root.mkdir(parents=True, exist_ok=True)
    source = root / "upstream"
    sys.path.insert(0, str(source))
    from gradio_app import EXAMPLES, UI_ASSETS, GenerationConfig, ModelRunner, build_app, is_model_bundle, profile_defaults

    model = root / "models" / "MOSS-Image-SFT"
    output = root / "generated"
    output.mkdir(exist_ok=True)
    pins = json.loads(Path(__file__).with_name("revisions.json").read_text(encoding="utf-8"))
    if not args.check_ui:
        revision_file = model / ".moss-revision"
        if not is_model_bundle(model) or not revision_file.is_file() or revision_file.read_text().strip() != pins["model_revision"]:
            raise SystemExit("Model bundle incomplete or revision differs. Run setup-gradio.sh first.")
    if args.smoke:
        runner = ModelRunner(output, local_files_only=True)
        config = GenerationConfig(
            prompt="A small wooden cabin beside a clear forest stream, moss-covered stones, warm morning sunlight, detailed anime background illustration.",
            height=1024, width=1024, steps=50, cfg=3.0, shift=5.0, seed=42,
            offload=profile_defaults(args.profile)[0],
        )
        images, metadata, message = runner.generate(str(model), config)
        print(message)
        print(json.dumps({"images": images, "parameters": metadata}, indent=2))
        runner.unload()
        return
    app = build_app(
        model_root=model.parent,
        profile=args.profile,
        model=str(model) if not args.check_ui else pins["model_id"],
        output_dir=output,
        prompt_defaults=Path(__file__).with_name("prompt_defaults.txt"),
        local_files_only=True,
    )
    if args.check_ui:
        print("Official Gradio UI construction: OK (no model loaded)")
        app.close()
        return
    login = credentials(root / "login.json")
    print(f"Login user: {login['username']}\nLogin password: {login['password']}", flush=True)
    print(f"Images and parameters: {output}", flush=True)
    if os.getenv("RUNPOD_POD_ID"):
        print(f"Open: https://{os.environ['RUNPOD_POD_ID']}-{args.port}.proxy.runpod.net", flush=True)
    app.launch(
        server_name=args.host, server_port=args.port, share=False,
        auth=(login["username"], login["password"]),
        allowed_paths=[str(output), str(EXAMPLES.resolve()), str(UI_ASSETS.resolve())],
    )


if __name__ == "__main__":
    main()
