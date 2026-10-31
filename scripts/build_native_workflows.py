"""Rebuild the four native ComfyUI workflows (stdlib only; no model execution)."""
import copy
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


def reference_workflow(base, edit=False):
    data = copy.deepcopy(base)
    nodes = {n['id']: n for n in data['nodes']}
    nodes[1]['widgets_values'][0] = 'moss_image_sft_bf16.safetensors' if edit else 'moss_image_base_bf16.safetensors'
    nodes[1]['title'] = 'MOSS-Image SFT' if edit else 'MOSS-Image Base'
    nodes[1]['properties'].pop('models', None)
    nodes[10]['widgets_values'] = ['moss_edit_armV5.safetensors' if edit else 'moss_image_charref_v2.safetensors', 1.0]
    nodes[10]['title'] = 'Edit HQ v5' if edit else 'CharRef v2（キャラLoRA不要）'
    nodes[10]['properties'].pop('models', None)
    prompt = ('Change her outfit to a black evening dress. Keep her face, hair, pose, background and composition unchanged.' if edit else
              'Same character and art style as Picture 1. Preserve her face, eye color and hairstyle. '
              'She wears a black evening dress and sits sideways on a balcony, looking back toward the viewer. '
              'Night city lights, wind-blown hair, cinematic lighting. One complete illustration.')
    for key, positive in [(4, True), (5, False)]:
        nodes[key] = node(key, 'TextEncodeMOSSImageEdit', '② 変更したい内容' if edit and positive else '② 新しい衣装・ポーズ・場面' if positive else 'Negative（空欄のまま）',
                          [800, 350 if positive else 700], [520, 290 if positive else 180],
                          [('clip', 'CLIP'), ('images.image_0', 'IMAGE'), ('images.image_1', 'IMAGE'), ('vae', 'VAE')],
                          [('CONDITIONING', 'CONDITIONING')], [prompt if positive else '', 'ai-toolkit', 1.0])
        nodes[key]['inputs'][2]['shape'] = 7
        nodes[key]['inputs'][3]['shape'] = 7
    nodes[12] = node(12, 'LoadImage', '① 元画像をアップロード', [0, 760], [350, 420], outputs=[('IMAGE', 'IMAGE'), ('MASK', 'MASK')], widgets=['', 'image'])
    nodes[13] = node(13, 'ImageScaleToTotalPixels', '参照画像を約1MP・16px単位に調整', [400, 760], [350, 130],
                     [('image', 'IMAGE')], [('IMAGE', 'IMAGE')], ['lanczos', 1.0, 16])
    positions = {1:[0,100],2:[0,320],3:[0,560],10:[400,100],11:[800,100],6:[1400,800],7:[1400,200],8:[1800,220],9:[2100,200]}
    for key, pos in positions.items(): nodes[key]['pos'] = pos
    nodes[9]['widgets_values'] = ['MOSS/EditHQ_v5' if edit else 'MOSS/CharRef']
    nodes[7]['title'] = '③ Runで生成（25ステップ）'
    nodes[6]['title'] = '出力：元画像の比率・約1MP' if edit else '出力：1152 × 1536'
    nodes[4]['color'], nodes[4]['bgcolor'] = '#232', '#353'
    nodes[12]['color'], nodes[12]['bgcolor'] = '#223', '#335'
    def connect(source, slot, target, target_slot, kind):
        data['links'].append([max(x[0] for x in data['links'])+1, source, slot, target, target_slot, kind])
    connect(12,0,13,0,'IMAGE')
    for target in (4,5):
        connect(13,0,target,1,'IMAGE')
        connect(3,0,target,3,'VAE')
    if edit:
        nodes[14] = node(14, 'GetImageSize', '元画像の縦横比を保持', [800,1000], [310,100], [('image','IMAGE')], [('width','INT'),('height','INT'),('batch_size','INT')])
        nodes[6]['inputs'] = [{'name':key,'type':'INT','widget':{'name':key},'link':None} for key in ('width','height')]
        connect(13,0,14,0,'IMAGE');connect(14,0,6,0,'INT');connect(14,1,6,1,'INT')
    note = ('画像編集：①画像を選択 → ②変更内容を記入 → Run。元画像の縦横比で約1MPに調整して編集します。'
            if edit else 'キャラ参照：①画像を選択 → ②新しい服・ポーズ・行動を記入 → Run。出力は1152×1536。')
    note += '\n25ステップが初期値。作者の比較用設定：50 steps / CFG 3 / euler / sgm_uniform、SLG end_percent 1.0。\n正負両方の参照画像接続と ai-toolkit は維持してください。顔や髪の完全一致は保証されません。'
    nodes[15] = node(15, 'Note', '使い方', [0,-230], [740,220], widgets=[note])
    data['nodes'] = list(nodes.values())
    return data


def main():
    for name, number in [('scarlet_goddeath',1), ('marian_queen2',2)]:
        data=json.loads((FOLDER/f'moss_{name}_1152x1536_25.json').read_text(encoding='utf-8'))
        by_id={n['id']:n for n in data['nodes']}
        by_id[6]['title']='画像サイズ：1152 × 1536'
        by_id[7]['title']='生成設定：25 steps / CFG 2.5'
        by_id[11]['title']='SLG：22 / 前半50%'
        write(data,f'MOSS_0{number}_{name}_1152x1536_25.json')
        if number==1: base=copy.deepcopy(data)
    write(reference_workflow(base), 'MOSS_03_CharRef_1152x1536_25.json')
    write(reference_workflow(base,edit=True), 'MOSS_04_EditHQ_v5_25.json')


if __name__=='__main__':main()
