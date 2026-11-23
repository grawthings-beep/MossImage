"""Rebuild native ComfyUI workflows (stdlib only; no model execution)."""
import json
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


def write_marciana(filename, width, height, output_folder, pin):
    data = json.loads(Path(__file__).with_name('marciana_base.json').read_text(encoding='utf-8'))
    nodes = {n['id']: n for n in data['nodes']}
    nodes[6].update(title=f'生成サイズ：{width} × {height}', widgets_values=[width, height, 1])
    prefix = f'MOSS/Marciana/{output_folder}'
    nodes[9].update(title='元画像を保存', pos=[1790, 375], size=[330, 460], widgets_values=[prefix + '/base'])
    nodes[15]['widgets_values'] = [
        f'マルチャーナ：マリンスタディ。緑の欄で m4rc14n4m4r1ne を残してRun。\n'
        f'{width}×{height}・12 stepsで生成し、{width*2}×{height*2}の仕上げ版も保存します。\n'
        '候補だけを作るときは「仕上げ版を保存」をミュート。細い線を戻すには「元画像を混ぜる割合」を上げます。']
    loader = node(20, 'UpscaleModelLoader', '軽量2倍モデル', [2140, 380], [350, 65],
                  outputs=[('UPSCALE_MODEL', 'UPSCALE_MODEL')], widgets=[pin['file']])
    loader['properties']['models'] = [{
        'name': pin['file'], 'directory': 'upscale_models',
        'url': f"https://huggingface.co/{pin['repo']}/resolve/{pin['revision']}/{pin['file']}",
    }]
    data['nodes'].extend([
        loader,
        node(19, 'ImageBlur', '拡大前の粒状感を抑える（半径0でオフ）', [2140, 90], [350, 115],
             [('image', 'IMAGE')], [('IMAGE', 'IMAGE')], [1, 0.7]),
        node(21, 'ImageUpscaleWithModel', '2倍に拡大', [2540, 230], [250, 85],
             [('upscale_model', 'UPSCALE_MODEL'), ('image', 'IMAGE')], [('IMAGE', 'IMAGE')]),
        node(22, 'ImageBlend', '元画像を混ぜる割合', [2860, 90], [290, 130],
             [('image1', 'IMAGE'), ('image2', 'IMAGE')], [('IMAGE', 'IMAGE')], [0.25, 'normal']),
        node(23, 'SaveImage', '仕上げ版を保存（2倍）', [3230, 75], [420, 520],
             [('images', 'IMAGE')], widgets=[prefix + '/final']),
    ])
    connections = [(8, 0, 19, 0, 'IMAGE'), (20, 0, 21, 0, 'UPSCALE_MODEL'), (19, 0, 21, 1, 'IMAGE'),
                   (21, 0, 22, 0, 'IMAGE'), (8, 0, 22, 1, 'IMAGE'), (22, 0, 23, 0, 'IMAGE')]
    first = max(link[0] for link in data['links']) + 1
    for link_id, connection in enumerate(connections, first):
        data['links'].append([link_id, *connection])
    write(data, filename)


if __name__ == '__main__':
    pin = json.loads((ROOT / 'studio/models.json').read_text(encoding='utf-8'))['upscale_2x']
    write_marciana('MOSS_10_Fast2x_marciana_marine_study.json', 864, 1152, 'Fast', pin)
    write_marciana('MOSS_08_Quality2x_marciana_marine_study.json', 1152, 1536, 'Quality', pin)
