"""Deterministic page assembly and Japanese lettering; no diffusion for text."""
import base64
from functools import lru_cache
from html import escape
import io
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, PngImagePlugin
from .schema import pixel_box

VERTICAL = str.maketrans({'、': '︑', '。': '︒', '「': '﹁', '」': '﹂', '『': '﹃', '』': '﹄',
                          '（': '︵', '）': '︶', '【': '︻', '】': '︼', 'ー': '︱', '―': '︱', '…': '︙'})
NO_LINE_START = set('、。，．？！!?」』）】〉》〕〗ぁぃぅぇぉっゃゅょァィゥェォッャュョー')
NO_LINE_END = set('「『（【〈《〔〖')


def vertical_lines(paragraph, capacity):
    if not paragraph:
        return ['']
    lines = []
    while len(paragraph) > capacity:
        end = capacity
        # Basic Japanese line breaking: keep closing marks with their preceding character.
        while end > 1 and (paragraph[end] in NO_LINE_START or paragraph[end-1] in NO_LINE_END):
            end -= 1
        lines.append(paragraph[:end])
        paragraph = paragraph[end:]
    return lines + [paragraph]


@lru_cache(maxsize=128)
def font(path, size):
    return ImageFont.truetype(str(path), size)


def fit(image, size):
    return ImageOps.fit(image.convert('RGB'), size, method=Image.Resampling.LANCZOS)


def clean_page(page, store):
    w, h = page['width'], page['height']
    canvas = Image.new('RGB', (w, h), 'white')
    if page.get('background'):
        with Image.open(store.asset_path(page['background'])) as im:
            canvas.paste(fit(im, (w, h)))
    draw = ImageDraw.Draw(canvas)
    for panel in page['panels']:
        b = pixel_box(panel['box'], w, h)
        asset = page['panel_images'].get(panel['id'])
        if asset:
            with Image.open(store.asset_path(asset)) as im:
                canvas.paste(fit(im, (b[2]-b[0], b[3]-b[1])), b[:2])
            draw.rectangle(b, outline='black', width=max(1, round(w/550)))
        elif not page.get('background'):
            draw.rectangle(b, fill='#f0f1f3', outline='#88909c', width=max(1, round(w/550)))
    return canvas


def lettering(bubble, page, font_path):
    x0, y0, x1, y1 = pixel_box(bubble['box'], page['width'], page['height'])
    padding = 0.19 if bubble['shape'] == 'ellipse' else 0.09
    inset_x, inset_y = (x1-x0)*padding, (y1-y0)*padding
    aw, ah = x1-x0-2*inset_x, y1-y0-2*inset_y
    requested = max(8, round(bubble['size'] * page['width'] / 1152))
    content = bubble['text'].replace('\r', '')
    for size in range(requested, 7, -1):
        f = font(str(font_path), size)
        step = size*1.22
        lines = []
        if bubble['direction'] == 'vertical':
            capacity = max(1, int(ah // step))
            for line in content.split('\n'):
                lines.extend(vertical_lines(line, capacity))
            if len(lines)*step > aw or size > ah:
                continue
            points = []
            right = x0+(x1-x0)/2 + (len(lines)-1)*step/2
            for c, line in enumerate(lines):
                top = y0+(y1-y0-len(line)*step)/2
                for r, ch in enumerate(line.translate(VERTICAL)):
                    points.append((right-c*step, top+r*step+step/2, ch))
        else:
            for paragraph in content.split('\n'):
                line = ''
                for ch in paragraph:
                    if line and f.getlength(line+ch) > aw:
                        lines.append(line)
                        line = ''
                    line += ch
                lines.append(line)
            if len(lines)*step > ah or any(f.getlength(l) > aw for l in lines):
                continue
            top = y0+(y1-y0-len(lines)*step)/2
            points = [(x0+(x1-x0)/2, top+i*step+step/2, line) for i, line in enumerate(lines)]
        return [x0, y0, x1, y1], size, points
    raise ValueError('セリフが吹き出しに収まりません。範囲を広げるか、文章を短くしてください。')


def png_page(project, page, store, font_path):
    canvas = clean_page(page, store)
    draw = ImageDraw.Draw(canvas)
    for bubble in page['bubbles']:
        b, size, points = lettering(bubble, page, font_path)
        stroke = max(1, round(page['width']/550))
        if bubble['shape'] == 'ellipse':
            draw.ellipse(b, fill='white', outline='black', width=stroke)
        elif bubble['shape'] == 'rect':
            draw.rounded_rectangle(b, radius=size/3, fill='white', outline='black', width=stroke)
        f = font(str(font_path), size)
        for x, y, text in points:
            draw.text((x, y), text, font=f, fill='black', anchor='mm')
    stream = io.BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('moss_studio', json.dumps({'project_id': project['id'], 'page': page}, ensure_ascii=False))
    canvas.save(stream, format='PNG', pnginfo=metadata)
    return stream.getvalue()


def svg_page(project, page, store, font_path, embed=False):
    w, h = page['width'], page['height']
    if embed:
        font_url = 'data:font/otf;base64,' + base64.b64encode(Path(font_path).read_bytes()).decode()
    else:
        font_url = '/studio/font.otf'
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
           f'<style>@font-face{{font-family:MossJP;src:url("{font_url}")}}text{{font-family:MossJP,sans-serif;fill:#000}}</style>',
           f'<rect width="{w}" height="{h}" fill="white"/>']
    if embed:
        out.append('<metadata>' + escape((Path(font_path).parent / 'OFL.txt').read_text(encoding='utf-8')) + '</metadata>')
    def image_tag(key, b, clip_id):
        url = ('data:image/png;base64,' + base64.b64encode(store.asset_path(key).read_bytes()).decode()) if embed else f'/studio/api/assets/{key}'
        x0, y0, x1, y1 = b
        return (f'<defs><clipPath id="{clip_id}"><rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}"/></clipPath></defs>'
                f'<image href="{url}" x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" preserveAspectRatio="xMidYMid slice" clip-path="url(#{clip_id})"/>')
    if page.get('background'):
        out.append(image_tag(page['background'], [0, 0, w, h], 'background'))
    for i, panel in enumerate(page['panels']):
        b = pixel_box(panel['box'], w, h)
        asset = page['panel_images'].get(panel['id'])
        if asset:
            out.append(image_tag(asset, b, f'panel{i}'))
        if asset or not page.get('background'):
            fill = 'none' if asset else '#f0f1f3'
            out.append(f'<rect x="{b[0]}" y="{b[1]}" width="{b[2]-b[0]}" height="{b[3]-b[1]}" fill="{fill}" stroke="#333" stroke-width="{w/550}"/>')
    for bubble in page['bubbles']:
        b, size, points = lettering(bubble, page, font_path)
        x0, y0, x1, y1 = b
        if bubble['shape'] == 'ellipse':
            out.append(f'<ellipse cx="{(x0+x1)/2}" cy="{(y0+y1)/2}" rx="{(x1-x0)/2}" ry="{(y1-y0)/2}" fill="white" stroke="black" stroke-width="{w/550}"/>')
        elif bubble['shape'] == 'rect':
            out.append(f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" rx="{size/3}" fill="white" stroke="black" stroke-width="{w/550}"/>')
        for x, y, content in points:
            # SVG remains editable text; the embedded font makes downloads portable.
            out.append(f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="middle" dominant-baseline="central">{escape(content)}</text>')
    out.append('</svg>')
    return ''.join(out).encode('utf-8')
