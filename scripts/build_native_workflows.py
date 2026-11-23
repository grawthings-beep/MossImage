"""Rebuild native ComfyUI workflows (stdlib only; no model execution)."""
import json
from copy import deepcopy
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'workflows'


def node(key, kind, title, position, size, inputs=(), outputs=(), widgets=()):
    return {'id': key, 'type': kind, 'title': title, 'pos': position, 'size': size,
            'flags': {}, 'order': key-1, 'mode': 0,
            'inputs': [{'name': n, 'type': t, 'link': None} for n, t in inputs],
            'outputs': [{'name': n, 'type': t, 'links': [], 'slot_index': i} for i, (n, t) in enumerate(outputs)],
            'properties': {'Node name for S&R': kind}, 'widgets_values': list(widgets)}


def write(data, filename):
    data['id'] = str(uuid.uuid5(uuid.NAMESPACE_URL, 'grawthings-beep/MossImage/'+filename))
    data['last_node_id'] = max(n['id'] for n in data['nodes'])
    data['last_link_id'] = max(link[0] for link in data['links'])
    for n in data['nodes']:
        for output in n['outputs']:
            output['links'] = []
    by_id = {n['id']: n for n in data['nodes']}
    for link_id, source, slot, target, target_slot, kind in data['links']:
        by_id[source]['outputs'][slot]['links'].append(link_id)
        by_id[target]['inputs'][target_slot]['link'] = link_id
    data['extra'] = {'ds': {'scale': .8, 'offset': [100, 150]}}
    (FOLDER / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def model_metadata(pin):
    return {'name': pin['file'], 'directory': Path(pin['destination']).parent.as_posix(),
            'url': f"https://huggingface.co/{pin['repo']}/resolve/{pin['revision']}/{pin['file']}"}


def write_variant(data, filename, width, height, prefix, instructions):
    nodes = {n['id']: n for n in data['nodes']}
    nodes[6].update(title=f'生成サイズ：{width} × {height}', widgets_values=[width, height, 1])
    nodes[9].update(title='元画像を保存', pos=[1790, 375], size=[330, 460], widgets_values=[prefix + '/base'])
    nodes[15]['widgets_values'] = [
        f'{instructions}\n'
        f'{width}×{height}で生成し、latentを1.5倍に拡大。2段目で8 steps描き込み、'
        f'{width*3//2}×{height*3//2}の仕上げ版を保存します。\n'
        '顔が変わりすぎるときは2段目のdenoiseを下げます。元画像だけを試すときは「仕上げ版を保存」をミュート。']
    data['nodes'].extend([
        node(19, 'LatentUpscaleBy', '2段目：latent拡大', [1790, 210], [300, 110],
             [('samples', 'LATENT')], [('LATENT', 'LATENT')], ['bislerp', 1.5]),
        node(21, 'KSampler', '2段目：高解像度で描き込む', [2190, 80], [350, 485],
             [('model', 'MODEL'), ('positive', 'CONDITIONING'), ('negative', 'CONDITIONING'),
              ('latent_image', 'LATENT')], [('LATENT', 'LATENT')],
             [43, 'fixed', 8, 1.0, 'er_sde', 'simple', 0.55]),
        node(22, 'VAEDecode', '仕上げ版を画像に変換', [2640, 80], [250, 70],
             [('samples', 'LATENT'), ('vae', 'VAE')], [('IMAGE', 'IMAGE')]),
        node(23, 'SaveImage', '仕上げ版を保存', [2980, 80], [420, 520],
             [('images', 'IMAGE')], widgets=[prefix + '/final']),
    ])
    connections = [(7, 0, 19, 0, 'LATENT'), (11, 0, 21, 0, 'MODEL'),
                   (4, 0, 21, 1, 'CONDITIONING'), (5, 0, 21, 2, 'CONDITIONING'),
                   (19, 0, 21, 3, 'LATENT'), (21, 0, 22, 0, 'LATENT'),
                   (3, 0, 22, 1, 'VAE'), (22, 0, 23, 0, 'IMAGE')]
    first = max(link[0] for link in data['links']) + 1
    for link_id, connection in enumerate(connections, first):
        data['links'].append([link_id, *connection])
    write(data, filename)


def write_pair(slug, name, version, trigger, folder, lora, prompt=None):
    template = json.loads(Path(__file__).with_name('marciana_base.json').read_text(encoding='utf-8'))
    nodes = {n['id']: n for n in template['nodes']}
    if prompt is not None:
        nodes[4]['widgets_values'] = [prompt]
    nodes[10].update(title=f'{name} LoRA（{version}）', widgets_values=[lora['file'], 1.0])
    nodes[10]['properties']['models'] = [model_metadata(lora)]
    instructions = f'{name}。緑の欄で {trigger} を残してRun。'
    for number, mode, width, height in [('10', 'Fast', 864, 1152), ('08', 'Quality', 1152, 1536)]:
        filename = f'MOSS_{number}_{mode}_Hires_{slug}.json'
        write_variant(deepcopy(template), filename, width, height, f'MOSS/{folder}/{mode}', instructions)


if __name__ == '__main__':
    pins = json.loads((ROOT / 'studio/models.json').read_text(encoding='utf-8'))
    write_pair('marciana_marine_study_30_v1', 'マルチャーナ：マリンスタディ', '30枚版 v1',
               'm4rc14n4m4r1ne', 'Marciana', pins['marciana_marine_study'])
    write_pair('marciana_marine_study_original_33', 'マルチャーナ：マリンスタディ', '元の33枚版',
               'm4rc14n4m4r1ne', 'Marciana/Original33', pins['marciana_marine_study_original'])
    write_pair('marian_last_affection2_3k', 'マリアン：ラストアフェクション', '3000ステップ',
               'm4r14nl4st2', 'Marian/LastAffection', pins['marian_last_affection2_3k'],
               'masterpiece, best quality, highres, m4r14nl4st2, an anime illustration. '
               'A bride pauses on the stone steps of a chapel at dusk and smiles over her shoulder. '
               'She lifts the ruffled train of her white wedding dress with one gloved hand. '
               'The breeze draws her translucent veil to one side, revealing her lavender hair ribbon. '
               'Her blue pendant catches the last light. Full-length three-quarter view.')
