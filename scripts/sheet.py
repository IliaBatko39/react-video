#!/usr/bin/env python3
"""Лист кадров (контактный лист) для быстрой проверки ролика глазами.

  sheet.py out.jpg --video final.mp4 --times 0.5,1.2,3.0
  sheet.py out.jpg --video final.mp4 --timeline timeline.json   # устоявшийся момент каждой сцены
  sheet.py out.jpg stills/t_*.jpg                               # готовые кадры
  общие: --cols 6 --scale 0.25

Кадры берутся из ГОТОВОГО видео — это то, что увидит зритель. Устоявшийся момент сцены:
t0 + min(1.4, 0.8·(t1 − t0)). Подпись — время кадра.
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

FONT_PATHS = ['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf',
              '/Library/Fonts/DejaVuSans-Bold.ttf', 'DejaVuSans-Bold.ttf']


def settle(t0, t1):
    return t0 + min(1.4, 0.8 * (t1 - t0))


def grab(video, t):
    r = subprocess.run(['ffmpeg', '-v', 'error', '-ss', '%.4f' % t, '-i', video, '-frames:v', '1',
                        '-f', 'image2pipe', '-c:v', 'png', '-'], capture_output=True)
    if r.returncode != 0 or not r.stdout:
        sys.exit('ошибка: не взять кадр %.2f с из %s: %s' % (t, video, r.stderr.decode(errors='replace').strip()))
    return Image.open(io.BytesIO(r.stdout)).convert('RGB')


def get_font(size):
    for p in FONT_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', help='выходной .jpg')
    ap.add_argument('frames', nargs='*', help='файлы кадров (если нет --video)')
    ap.add_argument('--video', help='готовое видео')
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--times', help='времена через запятую, с')
    g.add_argument('--timeline', help='timeline.json: по кадру на устоявшийся момент каждой сцены')
    ap.add_argument('--cols', type=int, default=6, help='колонок (по умолчанию 6)')
    ap.add_argument('--scale', type=float, default=0.25, help='масштаб кадра (по умолчанию 0.25)')
    a = ap.parse_args()

    items = []   # (подпись, картинка)
    if a.video:
        if a.frames:
            sys.exit('ошибка: либо --video, либо файлы кадров')
        if a.times:
            times = [float(x) for x in a.times.split(',') if x.strip()]
        elif a.timeline:
            with open(a.timeline, encoding='utf-8') as f:
                tl = json.load(f)
            if not tl.get('scenes'):
                sys.exit('ошибка: в %s нет scenes' % a.timeline)
            times = [settle(float(s['t0']), float(s['t1'])) for s in tl['scenes']]
        else:
            sys.exit('ошибка: с --video нужен --times или --timeline')
        for t in times:
            items.append(('%.2f с' % t, grab(a.video, t)))
    elif a.frames:
        for p in a.frames:
            m = re.search(r't_(\d+(?:\.\d+)?)', os.path.basename(p))
            items.append(('%s с' % m.group(1) if m else os.path.basename(p), Image.open(p).convert('RGB')))
    else:
        sys.exit('ошибка: нужны --video или файлы кадров')

    fw, fh = items[0][1].size
    tw, th = max(1, int(fw * a.scale)), max(1, int(fh * a.scale))
    cols = max(1, min(a.cols, len(items)))
    rows = (len(items) + cols - 1) // cols
    pad, lab = 8, 30
    sheet = Image.new('RGB', (cols * (tw + pad) + pad, rows * (th + pad + lab) + pad), (28, 28, 32))
    d, font = ImageDraw.Draw(sheet), get_font(20)
    for k, (label, im) in enumerate(items):
        r, c = divmod(k, cols)
        x, y = pad + c * (tw + pad), pad + r * (th + pad + lab)
        sheet.paste(im.resize((tw, th), Image.LANCZOS), (x, y))
        d.text((x + 4, y + th + 4), label, fill=(240, 240, 240), font=font)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    sheet.save(a.out, quality=90)
    print('sheet ok: %s — %d кадров, %dx%d' % (a.out, len(items), *sheet.size))


if __name__ == '__main__':
    main()
