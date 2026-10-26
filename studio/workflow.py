"""Build native ComfyUI API graphs, without custom nodes or model patches."""
from .schema import NEGATIVE


def build_graph(page, prompt, width, height, seed, prefix, reference=None, edit=False):
    graph = {}
    def add(kind, **inputs):
        key = str(len(graph) + 1)
        graph[key] = {'class_type': kind, 'inputs': inputs}
        return [key, 0]
    model_name = 'moss_image_sft_bf16.safetensors' if edit or page['route'] == 'sft' else 'moss_image_base_bf16.safetensors'
    model = add('UNETLoader', unet_name=model_name, weight_dtype='default')
    clip = add('CLIPLoader', clip_name='qwen3.5_9b_bf16.safetensors', type='moss_image', device='default')
    vae = add('VAELoader', vae_name='flux2-vae.safetensors' if page['vae'] == 'full' else 'flux2-vae_small.safetensors')
    if edit:
        model = add('LoraLoaderModelOnly', model=model, lora_name='moss_edit_armV6.safetensors', strength_model=1.0)
    elif page['route'] == 'marian':
        model = add('LoraLoaderModelOnly', model=model, lora_name='mossimage_lora_marian_queen2.safetensors', strength_model=page['lora_strength'])
    elif page['route'] == 'reference':
        model = add('LoraLoaderModelOnly', model=model, lora_name='moss_image_charref_v2.safetensors', strength_model=1.0)
    if not edit and page['hires'] and width * height >= 3_900_000:
        model = add('LoraLoaderModelOnly', model=model, lora_name='moss_hires_lora_test_v0.4.safetensors', strength_model=page['hires_strength'])
    # Editing/CharRef use their documented 50-step settings, independent of the T2I selector.
    quality = edit or page['route'] == 'reference' or page['sampling'] == 'quality'
    model = add('SkipLayerGuidanceDiTSimple', model=model, double_layers='', single_layers='22',
                start_percent=0.0, end_percent=1.0 if quality else 0.5)
    if reference:
        image = add('LoadImage', image=reference)
        # Uploaded references are resized to approximately 1MP by the server before encoding.
        kwargs = {'clip': clip, 'vae': vae, 'edit_format': 'ai-toolkit', 'images.image_0': image, 'image_strength': 1.0}
        positive = add('TextEncodeMOSSImageEdit', prompt=prompt, **kwargs)
        negative = add('TextEncodeMOSSImageEdit', prompt='', **kwargs)
    else:
        if edit or page['route'] == 'reference':
            raise ValueError('参照画像を選んでください。')
        positive = add('CLIPTextEncode', clip=clip, text=prompt)
        negative = add('CLIPTextEncode', clip=clip, text=NEGATIVE)
    latent = add('EmptyFlux2LatentImage', width=width, height=height, batch_size=1)
    samples = add('KSampler', model=model, positive=positive, negative=negative, latent_image=latent,
                  seed=seed, steps=50 if quality else 25, cfg=3.0 if quality else 2.5,
                  sampler_name='euler' if quality else 'er_sde', scheduler='sgm_uniform' if quality else 'simple', denoise=1.0)
    image = add('VAEDecode', samples=samples, vae=vae)
    output = add('SaveImage', images=image, filename_prefix=prefix)
    return graph, output[0]
