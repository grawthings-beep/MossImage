"""Validate editable pages and compile official MOSS layout prompts."""
import copy
import json
import math
import re
import uuid

NEGATIVE = 'nsfw, worst quality, bad anatomy, watermark, jpeg artifact'
CHARACTER = ('An adult woman, Marian: Queen, with red eyes, long silver-white hair, black bangs and dark inner hair. '
             'She wears a black crystalline spiked crown with a black bow, a violet jewel at her collar, '
             'a dark sheer bodysuit with glossy black crossed filigree panels, short pleated black hip frills, '
             'black elbow-length fingerless gloves, patterned dark tights and black heels.')
STYLES = {
    'color': 'A finished Japanese color manga page, expressive acting, precise ink contours, layered cel shading, consistent character design, detailed environments, deliberate cinematic composition.',
    'mono': 'A finished black-and-white Japanese manga page, confident ink contours, expressive acting, solid black shapes, fine screentones, controlled hatching, dramatic light and shadow, consistent character design. No color.',
}


def ident(value):
    value = str(value)
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', value):
        raise ValueError('IDの形式が不正です。')
    return value


def text(value, limit=12000):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f'文章は{limit}文字以内で入力してください。')
    return value


def number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'数値は{low}～{high}で指定してください。')
    return value


def box(value):
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError('範囲は x, y, 幅, 高さ の4値で指定してください。')
    x, y, w, h = [number(v, 0, 1000) for v in value]
    if w < 5 or h < 5 or x + w > 1000 or y + h > 1000:
        raise ValueError('範囲がページの外に出ています。')
    return [x, y, w, h]


def dimensions(w, h):
    for v in (w, h):
        number(v, 256, 4096)
        if int(v) != v or v % 16:
            raise ValueError('画像サイズは16の倍数で指定してください。')
    if w * h > 9_500_000:
        raise ValueError('1枚の画像は9.5MP以内で指定してください。')
    return int(w), int(h)


def default_project():
    return {
        'id': uuid.uuid4().hex, 'revision': 0, 'title': 'マリアン：クイーン',
        'character': CHARACTER, 'trigger': 'm4r14nqu33n2', 'reference': '',
        'pages': [{
            'id': uuid.uuid4().hex, 'title': '第1ページ', 'width': 1152, 'height': 1728,
            'style': 'color', 'scene': 'A ruined cathedral at dusk. Dust floats through shafts of crimson light. Quiet tension builds as Marian notices a distant presence.',
            'route': 'marian', 'sampling': 'quality', 'seed': 42, 'lora_strength': 1.0,
            'hires': False, 'hires_strength': 1.0, 'vae': 'small', 'reference': '',
            'panels': [
                {'id': 'p1', 'box': [35, 30, 930, 330], 'caption': 'Establishing wide shot from a low angle. Marian stands beneath the towering broken arches, small against the vast cathedral. Her hair and hip frills drift in the wind.'},
                {'id': 'p2', 'box': [520, 380, 445, 230], 'caption': 'Close-up of Marian turning her head. A slight widening of her red eyes and a lifted eyebrow convey sudden recognition. Three-quarter view, crown and collar jewel visible.'},
                {'id': 'p3', 'box': [35, 380, 465, 230], 'caption': 'Insert shot of her black-gloved hand tightening against the stone railing. Small fragments of stone fall into deep shadow.'},
                {'id': 'p4', 'box': [35, 630, 930, 340], 'caption': 'Dramatic medium shot. Marian steps toward the unseen visitor, her expression now composed and resolute. Her silhouette is rim-lit by the crimson light, with layered ruined arches behind her.'},
            ],
            'bubbles': [], 'background': '', 'panel_images': {},
        }],
    }


def validate_project(data):
    p = copy.deepcopy(data)
    p['id'] = ident(p['id'])
    p['revision'] = int(number(p.get('revision', 0), 0, 2**31))
    p['title'] = text(p.get('title', ''), 160)
    p['character'] = text(p.get('character', ''))
    p['trigger'] = text(p.get('trigger', ''), 128)
    p['reference'] = ident(p['reference']) if p.get('reference') else ''
    if not isinstance(p.get('pages'), list) or not 1 <= len(p['pages']) <= 32:
        raise ValueError('1作品につき1～32ページです。')
    seen = set()
    for page in p['pages']:
        page['id'] = ident(page['id'])
        if page['id'] in seen:
            raise ValueError('ページIDが重複しています。')
        seen.add(page['id'])
        page['title'] = text(page.get('title', ''), 160)
        page['width'], page['height'] = dimensions(page['width'], page['height'])
        page['scene'] = text(page.get('scene', ''))
        if page.get('style') not in STYLES or page.get('route') not in ('marian', 'reference', 'base', 'sft'):
            raise ValueError('画風または生成モードが不正です。')
        if page.get('sampling') not in ('quality', 'comfy') or page.get('vae') not in ('small', 'full'):
            raise ValueError('生成設定が不正です。')
        page['seed'] = int(number(page.get('seed', 42), 0, 2**53 - 1))
        page['lora_strength'] = number(page.get('lora_strength', 1), 0, 2)
        page['hires_strength'] = number(page.get('hires_strength', 1), 0, 2)
        page['hires'] = bool(page.get('hires', False))
        if page['hires'] and page['width'] * page['height'] < 3_900_000:
            raise ValueError('高解像度LoHaは約4MP以上のページで使用してください。')
        for key in ('reference', 'background'):
            page[key] = ident(page[key]) if page.get(key) else ''
        panels = page.get('panels', [])
        if not isinstance(panels, list) or not 1 <= len(panels) <= 12:
            raise ValueError('1ページにつき1～12コマです。')
        ids = set()
        for panel in panels:
            panel['id'] = ident(panel['id'])
            if panel['id'] in ids:
                raise ValueError('コマIDが重複しています。')
            ids.add(panel['id'])
            panel['box'] = box(panel['box'])
            panel['caption'] = text(panel.get('caption', ''), 6000)
        page['panel_images'] = {ident(k): ident(v) for k, v in page.get('panel_images', {}).items() if k in ids and v}
        bubbles = page.get('bubbles', [])
        if not isinstance(bubbles, list) or len(bubbles) > 40:
            raise ValueError('セリフは1ページ40個以内です。')
        bubble_ids = set()
        for bubble in bubbles:
            bubble['id'] = ident(bubble['id'])
            if bubble['id'] in bubble_ids:
                raise ValueError('セリフIDが重複しています。')
            bubble_ids.add(bubble['id'])
            bubble['box'] = box(bubble['box'])
            bubble['text'] = text(bubble.get('text', ''), 1000)
            bubble['size'] = number(bubble.get('size', 32), 12, 120)
            if bubble.get('direction') not in ('vertical', 'horizontal') or bubble.get('shape') not in ('ellipse', 'rect', 'none'):
                raise ValueError('セリフの設定が不正です。')
        page['panels'], page['bubbles'] = panels, bubbles
    return p


def pixel_box(b, width, height):
    x, y, w, h = b
    return [round(x * width / 1000), round(y * height / 1000),
            round((x + w) * width / 1000), round((y + h) * height / 1000)]


def compile_prompt(project, page, panel=None):
    character = project['character'].strip()
    if page['route'] == 'marian':
        character = project['trigger'].strip() + ', ' + character
    reference = 'Same character and art style as Picture 1. ' if page['route'] == 'reference' else ''
    style = STYLES[page['style']]
    if panel:
        return reference + style.replace('page', 'panel') + ' ' + character + '\n' + page['scene'] + '\n' + panel['caption'] + '\nOne single panel, no lettering, no speech bubbles, no panel borders.'
    summary = (reference + style + '\n' + page['scene'] + '\nCharacter design: ' + character +
               '\nRead from right to left, top to bottom in the specified panel order. Distinct rectangular panels, clean white gutters and black ink borders. '
               'Each panel depicts its own moment and camera view. Do not merge panels. No lettering or speech bubbles; dialogue is added separately.')
    items = []
    for i, part in enumerate(page['panels']):
        x0, y0, x1, y1 = pixel_box(part['box'], page['width'], page['height'])
        items.append({'label': 'object', 'caption': f'Manga panel {i + 1}. {part["caption"]} Character design when visible: {character}',
                      'bbox': [y0-page['height']//2, x0-page['width']//2, y1-page['height']//2, x1-page['width']//2]})
    return json.dumps({'summary': {'meta': ['manga'], 'canvas': 'multi_panel', 'caption': summary},
                       'items': items, 'bbox_coord_space': 'abs_centralized', 'bbox_format': 'yxyx'},
                      ensure_ascii=False, separators=(',', ':'))


def panel_dimensions(panel, page):
    b = panel['box']
    ratio = (b[2] * page['width']) / (b[3] * page['height'])
    w = max(256, min(4096, round(math.sqrt(1024**2 * ratio) / 16) * 16))
    h = max(256, min(4096, round(w / ratio / 16) * 16))
    return w, h
