"""Run against the pinned ComfyUI checkout: no model inference or weight downloads.

python tests/validate_comfy_studio.py --comfy /path/to/ComfyUI
"""
import argparse
import asyncio
import importlib
from pathlib import Path
import sys
import tempfile

parser=argparse.ArgumentParser()
parser.add_argument('--comfy',required=True,type=Path)
args=parser.parse_args()
sys.path.insert(0,str(args.comfy.resolve()))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.argv=['studio-validation','--cpu']
import comfy.options
comfy.options.enable_args_parsing()
import nodes
import folder_paths
import execution
import torch
from comfy_api.latest import _io
from PIL import Image
from studio.schema import default_project,compile_prompt
from studio.workflow import build_graph
from studio.assets import PINS


async def main():
    for name in ('comfy_extras.nodes_flux','comfy_extras.nodes_slg','comfy_extras.nodes_moss_image'):
        extension=await importlib.import_module(name).comfy_entrypoint()
        for cls in await extension.get_node_list():
            nodes.NODE_CLASS_MAPPINGS[cls.define_schema().node_id]=cls
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        files=['diffusion_models/moss_image_base_bf16.safetensors','text_encoders/qwen3.5_9b_bf16.safetensors',
               'vae/flux2-vae_small.safetensors','loras/mossimage_lora_marian_queen2.safetensors',
               *[p['destination'] for p in PINS.values()]]
        for file in files:
            path=root/file; path.parent.mkdir(parents=True,exist_ok=True); path.touch()
            folder_paths.add_model_folder_path(file.split('/')[0],str(path.parent))
        folder_paths.set_input_directory(str(root/'input')); (root/'input').mkdir()
        Image.new('RGB',(512,768),'white').save(root/'input/reference.png')
        count=0
        for route in ('marian','reference','base','sft'):
            for sampling in ('quality','comfy'):
                for full in (False,True):
                    project=default_project(); page=project['pages'][0]
                    page.update(route=route,sampling=sampling,vae='full' if full else 'small',hires=full,
                                width=1664 if full else 1152,height=2496 if full else 1728)
                    graph,_=build_graph(page,compile_prompt(project,page),page['width'],page['height'],42,'test',
                                        reference='reference.png' if route=='reference' else None)
                    result=await execution.validate_prompt('studio-validation',graph,None)
                    assert result[0],(route,sampling,full,result)
                    count+=1
        for full in (False,True):
            page=default_project()['pages'][0]; page['vae']='full' if full else 'small'
            graph,_=build_graph(page,'Change her expression.',512,768,42,'test','reference.png',edit=True)
            result=await execution.validate_prompt('studio-edit-validation',graph,None)
            assert result[0],result
            count+=1
        print(f'PASS: {count} Studio graph variants accepted by native ComfyUI. Names/schema only; no weights executed.')
        # Exercise the real edit node's dynamic input expansion and reference conditioning on CPU.
        encoder=nodes.NODE_CLASS_MAPPINGS['TextEncodeMOSSImageEdit']
        class Clip:
            def tokenize(self,prompt,images):
                assert prompt.startswith('Picture 1: <|vision_start|>')
                assert len(images)==1 and images[0].shape[1]*images[0].shape[2] <= 150000
                return {'prompt':prompt}
            def encode_from_tokens_scheduled(self,tokens):
                return [[torch.zeros(1,1,1),{}]]
        class Vae:
            def encode(self,image):
                assert image.shape==(1,512,768,3)
                return torch.zeros(1,128,32,48)
        flat={'clip':Clip(),'prompt':'Same character and art style as Picture 1.', 'vae':Vae(),
              'edit_format':'ai-toolkit','images.image_0':torch.zeros(1,512,768,3),'image_strength':1.0}
        _,_,dynamic=_io.get_finalized_class_inputs(encoder.INPUT_TYPES(),flat)
        nested=_io.build_nested_inputs(flat,dynamic)
        assert nested['images']['image_0'].shape==(1,512,768,3)
        result=encoder.execute(**nested)
        condition=result.result[0][0][1]
        assert condition['reference_latents_method']=='index_timestep_zero_isolated'
        assert len(condition['reference_latents'])==1
        print('PASS: real native MOSS edit node expands image input and produces vision/reference conditioning on CPU (stub CLIP/VAE).')


asyncio.run(main())
