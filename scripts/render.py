#!/usr/bin/env python3
"""Рендер ролика из веб-страницы: кадр = window.render(t) в headless Chromium → снимок → ffmpeg.

  render.py stills 0.5,2.6,4.0 [--blur N] [--out-dir stills]      → stills/t_00.50.jpg …
  render.py video out.mp4 [--blur N] [--poster T] [--from A --to B] [--remap timeline_long.json] [--crf 16]

Общие флаги: --dir . --page index.html --size 1080x1920 --fps 30 --gpu --timeout 90
Размер и fps по умолчанию — из window.T, иначе 1080x1920 @30. WebGL — через SwiftShader (без видеокарты).
"""
import argparse
import functools
import http.server
import io
import json
import os
import socketserver
import subprocess
import sys
import threading
import time

import numpy as np
from PIL import Image

# --- общая механика (та же копия в render.py и layout_check.py: скрипты самодостаточны) ---
DEFAULT_W, DEFAULT_H, DEFAULT_FPS = 1080, 1920, 30

SWIFTSHADER_ARGS = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']
FONT_ARGS = ['--font-render-hinting=none', '--disable-lcd-text']


def die(msg):
    print('ошибка: ' + msg, file=sys.stderr)
    raise SystemExit(2)


class _Quiet(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json',
                      '.woff2': 'font/woff2', '.wasm': 'application/wasm', '.svg': 'image/svg+xml'}

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.split('?')[0] == '/favicon.ico' and not os.path.exists(os.path.join(self.directory, 'favicon.ico')):
            self.send_response(204)
            self.end_headers()
            return
        super().do_GET()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(directory):
    """Отдаёт папку по http://127.0.0.1:<порт>/ (ES-модули и fetch с file:// не работают)."""
    if not os.path.isdir(directory):
        die('нет папки %s' % directory)
    srv = _Server(('127.0.0.1', 0), functools.partial(_Quiet, directory=os.path.abspath(directory)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def parse_size(s):
    try:
        w, h = s.lower().split('x')
        return int(w), int(h)
    except Exception:
        die('размер пишется как 1080x1920, получено %r' % s)


def read_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        die('нет файла %s' % path)
    except json.JSONDecodeError as e:
        die('%s: битый JSON (%s)' % (path, e))


def add_page_args(ap):
    ap.add_argument('--dir', default='.', help='папка, которую отдаёт HTTP-сервер (по умолчанию текущая)')
    ap.add_argument('--page', default='index.html', help='страница внутри --dir (по умолчанию index.html)')
    ap.add_argument('--size', help='размер кадра ШxВ; по умолчанию из window.T, иначе 1080x1920')
    ap.add_argument('--fps', type=float, help='кадров в секунду; по умолчанию из window.T, иначе 30')
    ap.add_argument('--gpu', action='store_true', help='WebGL на видеокарте, без SwiftShader')
    ap.add_argument('--timeout', type=float, default=90, help='сколько секунд ждать sceneReady (по умолчанию 90)')


def check_remap(points, where='remap'):
    """Точки [[новое, старое], ...]: новое строго растёт с 0, старое не убывает (равные — стоп-кадр)."""
    if not isinstance(points, list) or len(points) < 2:
        die('%s: нужно минимум две точки [новое, старое]' % where)
    try:
        pts = [[float(a), float(b)] for a, b in points]
    except Exception:
        die('%s: точка должна быть парой чисел [новое, старое]' % where)
    if pts[0][0] != 0:
        die('%s: первая точка должна начинаться с нового времени 0, а не %g' % (where, pts[0][0]))
    for (n0, o0), (n1, o1) in zip(pts, pts[1:]):
        if n1 <= n0:
            die('%s: новое время должно строго расти (%g → %g)' % (where, n0, n1))
        if o1 < o0:
            die('%s: старое время не может убывать (%g → %g)' % (where, o0, o1))
        if o0 < 0:
            die('%s: отрицательное время %g' % (where, o0))
    return pts


def fmap(points, tau):
    """Новое время → старое, кусочно-линейно; за краями — крайние значения."""
    if not points:
        return tau
    if tau <= points[0][0]:
        return points[0][1]
    for (n0, o0), (n1, o1) in zip(points, points[1:]):
        if tau <= n1:
            return o0 + (o1 - o0) * (tau - n0) / (n1 - n0)
    return points[-1][1]


def finv(points, old):
    """Старое время → новое (обратная карта). На стоп-кадре (старое стоит) — начало удержания."""
    if old <= points[0][1]:
        return points[0][0]
    for (n0, o0), (n1, o1) in zip(points, points[1:]):
        if old <= o1:
            if o1 == o0:
                return n0
            return n0 + (n1 - n0) * (old - o0) / (o1 - o0)
    return points[-1][0] + (old - points[-1][1])


class Page:
    """Одна страница в одном Chromium. Использовать как контекстный менеджер."""

    def __init__(self, args):
        self.args = args
        self.errs = []
        self._pw = self._browser = self._srv = None

    def __enter__(self):
        try:
            return self._open()
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _open(self):
        from playwright.sync_api import sync_playwright
        a = self.args
        page_path = os.path.join(a.dir, a.page)
        if not os.path.isfile(page_path):
            die('нет страницы %s (папка --dir %s, страница --page %s)' % (page_path, a.dir, a.page))
        # размер окна до загрузки: --size, иначе timeline.json рядом со страницей, иначе 1080x1920
        w, h = DEFAULT_W, DEFAULT_H
        if a.size:
            w, h = parse_size(a.size)
        else:
            tl_path = os.path.join(a.dir, 'timeline.json')
            if os.path.isfile(tl_path):
                tl = read_json(tl_path)
                w, h = int(tl.get('width', w)), int(tl.get('height', h))
        self._srv = serve(a.dir)
        self.url = 'http://127.0.0.1:%d/%s' % (self._srv.server_address[1], a.page)
        self._pw = sync_playwright().start()
        flags = FONT_ARGS + (['--ignore-gpu-blocklist'] if a.gpu else SWIFTSHADER_ARGS)
        try:
            self._browser = self._pw.chromium.launch(args=flags)
        except Exception as e:
            die('Chromium не запустился: %s\nпроверьте окружение: python3 scripts/check_env.py' % str(e).splitlines()[0])
        self.pg = self._browser.new_page(viewport={'width': w, 'height': h}, device_scale_factor=1)
        self.pg.on('pageerror', lambda e: self.errs.append('pageerror: %s' % e))
        self.pg.on('console', lambda m: m.type == 'error' and self.errs.append('console.error: %s' % m.text))
        self.pg.on('requestfailed', lambda r: self.errs.append('не загрузилось: %s (%s)' % (r.url, r.failure)))
        self._load()
        T = self.pg.evaluate('window.T')
        if not isinstance(T, dict) or 'end' not in T:
            die('страница не выставила window.T с полем end (длительность, с)')
        self.T = T
        if not a.size and ('width' in T or 'height' in T):
            tw, th = int(T.get('width', w)), int(T.get('height', h))
            if (tw, th) != (w, h):          # таймлайн страницы задаёт другой размер — перезагрузить в нём
                self.pg.set_viewport_size({'width': tw, 'height': th})
                self._load()
                w, h = tw, th
        self.w, self.h = w, h
        self.fps = float(a.fps or T.get('fps') or DEFAULT_FPS)
        self.end = float(T['end'])
        return self

    def _load(self):
        self.errs.clear()
        self.pg.goto(self.url, wait_until='load')
        try:
            self.pg.wait_for_function('window.sceneReady === true', timeout=self.args.timeout * 1000)
        except Exception:
            die('страница не выставила window.sceneReady = true за %g с%s' % (
                self.args.timeout, ('; ошибки:\n  ' + '\n  '.join(self.errs)) if self.errs else ''))
        bad = self.pg.evaluate('''() => ({
            img: [...document.images].filter(i => !i.complete || !i.naturalWidth).map(i => i.currentSrc || i.src),
            font: [...document.fonts].filter(f => f.status === 'error').map(f => f.family + ' ' + f.weight),
            render: typeof window.render})''')
        if bad['render'] != 'function':
            die('на странице нет функции window.render(t, gt)')
        if bad['img']:
            self.errs.append('не загрузились картинки: %s' % ', '.join(bad['img']))
        if bad['font']:
            self.errs.append('не загрузились шрифты: %s' % ', '.join(bad['font']))
        self.check()

    def check(self):
        if self.errs:
            die('ошибки на странице:\n  ' + '\n  '.join(self.errs))

    def render(self, t, gt=None):
        self.pg.evaluate('([t, g]) => window.render(t, g)', [t, t if gt is None else gt])
        self.check()

    def shot(self):
        # animations='allow' (по умолчанию): 'disabled' доматывает CSS-анимации до конца и ломает перемотку через WAAPI
        return self.pg.screenshot(type='jpeg', quality=95, caret='hide')

    def __exit__(self, *exc):
        try:
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()
            if self._srv:
                self._srv.shutdown()
                self._srv.server_close()
        return False
# --- конец общей механики ---


def decode(jpg):
    return np.asarray(Image.open(io.BytesIO(jpg)).convert('RGB'))


class Shooter:
    def __init__(self, page, remap, n_blur):
        self.p, self.remap, self.nb = page, remap, max(1, n_blur)
        self.t_max = remap[-1][0] if remap else page.end

    def one(self, tau):
        """Снимок в новом времени tau: страница получает render(f(tau), tau)."""
        self.p.render(fmap(self.remap, tau), tau)
        return self.p.shot()

    def frame(self, tau, blur=True):
        """Кадр как массив HxWx3 uint8 (и исходный JPEG, если размытия нет)."""
        nb = self.nb if blur else 1
        if nb <= 1:
            jpg = self.one(tau)
            return decode(jpg), jpg
        # затвор 180°: nb подкадров равномерно в [tau − ¼ кадра, tau + ¼ кадра], каждый через карту времени
        acc = None
        for k in range(nb):
            tk = tau + ((k + .5) / nb - .5) * (.5 / self.p.fps)
            a = decode(self.one(min(max(0.0, tk), self.t_max))).astype(np.float32)
            acc = a if acc is None else acc + a
        return np.clip(acc / nb + .5, 0, 255).astype(np.uint8), None


def load_remap(args):
    if not args.remap:
        return None
    path = args.remap if os.path.isabs(args.remap) or os.path.exists(args.remap) else os.path.join(args.dir, args.remap)
    tl = read_json(path)
    if 'remap' not in tl:
        die('%s: нет поля remap (сделайте его через scripts/remap.py)' % path)
    return check_remap(tl['remap'], path)


def cmd_stills(args, page, remap):
    try:
        times = [float(x) for x in args.times.split(',') if x.strip()]
    except ValueError:
        die('времена пишутся через запятую: 0.5,2.6,4.0')
    os.makedirs(args.out_dir, exist_ok=True)
    sh = Shooter(page, remap, args.blur)
    for t in times:
        arr, jpg = sh.frame(t)
        path = os.path.join(args.out_dir, 't_%05.2f.jpg' % t)
        if jpg is not None:
            with open(path, 'wb') as f:
                f.write(jpg)
        else:
            Image.fromarray(arr).save(path, quality=95)
        print(path)
    print('stills ok: %d кадров, %dx%d' % (len(times), page.w, page.h))


def cmd_video(args, page, remap):
    fps = page.fps
    end = remap[-1][0] if remap else page.end
    t_from = args.t_from if args.t_from is not None else 0.0
    t_to = args.t_to if args.t_to is not None else end
    i0, i1 = int(round(t_from * fps)), int(round(t_to * fps))
    if i1 <= i0:
        die('пустой отрезок: --from %g --to %g' % (t_from, t_to))
    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    fps_s = ('%g' % fps)
    ff = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                           '-s', '%dx%d' % (page.w, page.h), '-framerate', fps_s, '-i', '-',
                           '-c:v', 'libx264', '-preset', 'slow', '-crf', str(args.crf), '-pix_fmt', 'yuv420p',
                           '-r', fps_s, '-movflags', '+faststart', args.out], stdin=subprocess.PIPE)
    sh = Shooter(page, remap, args.blur)
    started = time.time()
    try:
        for i in range(i0, i1):
            poster = (i == 0 and args.poster is not None)
            tau = args.poster if poster else i / fps          # кадр 0 — постер: замена, не добавление
            arr, _ = sh.frame(tau, blur=not poster)
            if arr.shape[:2] != (page.h, page.w):
                die('снимок %dx%d, ждали %dx%d' % (arr.shape[1], arr.shape[0], page.w, page.h))
            ff.stdin.write(arr.tobytes())
            done = i - i0 + 1
            if done % int(round(fps)) == 0 or i == i1 - 1:
                el = time.time() - started
                print('кадр %d/%d  (%.1f с видео)  %.0f с, осталось ~%.0f с' % (
                    done, i1 - i0, done / fps, el, el / done * (i1 - i0 - done)), flush=True)
    except BaseException:
        ff.kill()
        raise
    ff.stdin.close()
    if ff.wait() != 0:
        die('ffmpeg завершился с ошибкой')
    el = time.time() - started
    print('video ok: %s — %d кадров (%d…%d), %dx%d @%s, blur %d, %.0f с (%.2f с/кадр)' % (
        args.out, i1 - i0, i0, i1 - 1, page.w, page.h, fps_s, max(1, args.blur), el, el / (i1 - i0)))


def main():
    common = argparse.ArgumentParser(add_help=False)
    add_page_args(common)
    common.add_argument('--blur', type=int, metavar='N', default=1, help='подкадров размытия движения на кадр (затвор 180°); 1 — без размытия')
    common.add_argument('--remap', metavar='TIMELINE', help='таймлайн с полем remap (scripts/remap.py): версия другой длины')
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='mode', required=True)
    s = sub.add_parser('stills', parents=[common], help='стоп-кадры в JPEG')
    s.add_argument('times', help='времена через запятую, с: 0.5,2.6,4.0')
    s.add_argument('--out-dir', default='stills', help='куда класть кадры (по умолчанию stills)')
    v = sub.add_parser('video', parents=[common], help='видео H.264 (yuv420p, faststart)')
    v.add_argument('out', help='выходной .mp4')
    v.add_argument('--poster', type=float, metavar='T', help='время кадра, который станет кадром 0 (постер)')
    v.add_argument('--from', dest='t_from', type=float, metavar='A', help='начало куска, с (кадры round(A·fps)…)')
    v.add_argument('--to', dest='t_to', type=float, metavar='B', help='конец куска, с (…round(B·fps)−1)')
    v.add_argument('--crf', type=int, default=16, help='качество x264 (меньше — лучше; по умолчанию 16)')
    args = ap.parse_args()
    remap = load_remap(args)
    with Page(args) as page:
        if args.mode == 'stills':
            cmd_stills(args, page, remap)
        else:
            cmd_video(args, page, remap)


if __name__ == '__main__':
    main()
