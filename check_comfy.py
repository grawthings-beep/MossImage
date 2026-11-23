"""Import the actual MOSS loader and every node used by the bundled workflow."""
import argparse
import asyncio
import importlib
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--comfy", required=True, type=Path)
    parser.add_argument("--cpu", action="store_true", help="For local import checks only")
    args = parser.parse_args()
    sys.path.insert(0, str(args.comfy.resolve()))
    sys.argv = ["comfy-check"] + (["--cpu"] if args.cpu else [])
    import comfy.options
    comfy.options.enable_args_parsing()
    import nodes
    from comfy.sd import CLIPType
    assert hasattr(CLIPType, "MOSS_IMAGE"), "ComfyUI has no native MOSS support."
    assert "moss_image" in nodes.CLIPLoader.INPUT_TYPES()["required"]["type"][0]

    for module_name in ("comfy_extras.nodes_flux", "comfy_extras.nodes_slg",
                        "comfy_extras.nodes_post_processing", "comfy_extras.nodes_upscale_model"):
        module = importlib.import_module(module_name)
        extension = asyncio.run(module.comfy_entrypoint())
        for node in asyncio.run(extension.get_node_list()):
            nodes.NODE_CLASS_MAPPINGS[node.define_schema().node_id] = node
    for path in (Path(__file__).parent / "workflows").glob("*.json"):
        workflow = json.loads(path.read_text(encoding="utf-8"))
        for node in workflow["nodes"]:
            if node["type"] != "Note":
                assert node["type"] in nodes.NODE_CLASS_MAPPINGS, node["type"]
    print("Native MOSS loaders and all workflow nodes: OK")


if __name__ == "__main__":
    main()

