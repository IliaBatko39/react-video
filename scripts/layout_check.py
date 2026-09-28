#!/usr/bin/env python3
"""Проверка вёрстки ролика: безопасная зона и скорость чтения по сценам таймлайна.

  layout_check.py [--dir .] [--page index.html] [--timeline timeline.json]
                  [--selector "[data-check]"] [--read "[data-read]"] [--safe 220,1500,940] [--wps 3.5]

В устоявшийся момент каждой сцены (t0 + min(1.4, 0.8·(t1 − t0))) рамки видимых элементов --selector
(непрозрачность ≥ 0,5 с учётом родителей, не hidden) сверяются с безопасной зоной Reels: y от 220 до 1500,
x не правее 940 (справа кнопки и подпись). --safe none — только границы кадра (16:9, 1:1).
Чтение: слова видимого текста --read за сцену (объединение по моментам сцены) / длительность ≤ --wps.
Текст на canvas: страница может отдать window.layoutBoxes(t) → [{name, x0, y0, x1, y1, words}] —
рамки проверяются так же, words идут в чтение. Код выхода 1 при нарушениях.
"""
import argparse
import functools
import http.server
import json
import os
import re
import socketserver
import sys
import threading

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

DOM_JS = r'''([sel, rsel]) => {
  const W = innerWidth, H = innerHeight;
  const vis = el => {
    let op = 1;
    for (let v = el; v && v.nodeType === 1; v = v.parentElement) {
      const cs = getComputedStyle(v);
      if (cs.display === 'none') return 0;
      if (v === el && cs.visibility !== 'visible') return 0;
      op *= +cs.opacity;
    }
    return op;
  };
  const box = el => { const r = el.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; };
  const name = el => el.dataset.check || el.id || (el.className && String(el.className).split(' ')[0]) || el.tagName.toLowerCase();
  const onScreen = b => b[2] > 0 && b[0] < W && b[3] > 0 && b[1] < H && b[2] - b[0] > 1;
  const boxes = [], texts = [];
  for (const el of document.querySelectorAll(sel)) {
    const b = box(el); if (!onScreen(b) || vis(el) < .5) continue;
    boxes.push({name: name(el), x0: b[0], y0: b[1], x1: b[2], y1: b[3]});
  }
  for (const el of document.querySelectorAll(rsel)) {
    const b = box(el); if (!onScreen(b) || vis(el) < .5) continue;
    texts.push(el.innerText || el.textContent || '');
  }
  return {boxes, texts, W, H};
}'''

WORD = re.compile(r'[0-9A-Za-zА-Яа-яЁё]')


def count_words(text):
    return sum(1 for w in text.replace(' ', ' ').replace(' ', ' ').split() if WORD.search(w))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_page_args(ap)
    ap.add_argument('--timeline', default='timeline.json', help='таймлайн со scenes (путь от --dir или абсолютный)')
    ap.add_argument('--selector', default='[data-check]', help='какие элементы проверять на зону')
    ap.add_argument('--read', default='[data-read]', help='какие элементы считать текстом для чтения')
    ap.add_argument('--safe', default='220,1500,940', help='y_верх,y_низ,x_право безопасной зоны или none')
    ap.add_argument('--wps', type=float, default=3.5, help='норма чтения, слов в секунду (по умолчанию 3,5)')
    ap.add_argument('--samples', type=int, default=8, help='моментов на сцену для подсчёта слов (по умолчанию 8)')
    a = ap.parse_args()
    tl_path = a.timeline
    if not os.path.isabs(tl_path) and os.path.exists(os.path.join(a.dir, tl_path)):
        tl_path = os.path.join(a.dir, tl_path)
    tl = read_json(tl_path)
    scenes = tl.get('scenes') or []
    if not scenes:
        die('%s: нет scenes [{id, t0, t1}]' % tl_path)
    safe = None
    if a.safe.lower() != 'none':
        try:
            y0, y1, x1 = [float(x) for x in a.safe.split(',')]
            safe = (y0, y1, x1)
        except ValueError:
            die('--safe пишется как 220,1500,940 или none')

    n_bad = 0
    with Page(a) as page:
        has_hook = page.pg.evaluate('typeof window.layoutBoxes === "function"')
        print('страница %s, %dx%d, сцен %d, холст-хук layoutBoxes: %s' % (a.page, page.w, page.h, len(scenes), 'да' if has_hook else 'нет'))
        if safe:
            print('безопасная зона: y %g…%g, x ≤ %g' % safe)

        def sample(t):
            page.render(t, t)
            r = page.pg.evaluate(DOM_JS, [a.selector, a.read])
            boxes, texts = r['boxes'], r['texts']
            if has_hook:
                for b in page.pg.evaluate('t => window.layoutBoxes(t) || []', t):
                    boxes.append(b)
                    if b.get('words'):
                        texts.append(str(b['words']))
            return boxes, texts

        for s in scenes:
            t0, t1 = float(s['t0']), float(s['t1'])
            ts = t0 + min(1.4, 0.8 * (t1 - t0))
            boxes, _ = sample(ts)
            print('== сцена %s  %.2f–%.2f, проверка в %.2f с' % (s.get('id', '?'), t0, t1, ts))
            if not boxes:
                print('   (нет видимых элементов)')
            for b in boxes:
                bad = []
                if b['x0'] < -0.5 or b['y0'] < -0.5 or b['x1'] > page.w + .5 or b['y1'] > page.h + .5:
                    bad.append('за кадром')
                if safe:
                    if b['y0'] < safe[0] - .5:
                        bad.append('y<%d' % round(safe[0]))
                    if b['y1'] > safe[1] + .5:
                        bad.append('y>%d' % round(safe[1]))
                    if b['x1'] > safe[2] + .5:
                        bad.append('x>%d' % round(safe[2]))
                n_bad += bool(bad)
                print('   %-18s x %4d–%4d  y %4d–%4d%s' % (str(b.get('name', '?'))[:18], round(b['x0']), round(b['x1']),
                                                          round(b['y0']), round(b['y1']), ('   НАРУШЕНИЕ: ' + ' '.join(bad)) if bad else ''))
            # чтение: всё, что было видно за сцену (текст появляется по долям — один момент его не покрывает)
            seen = {}
            k = max(2, a.samples)
            for j in range(k):
                for txt in sample(t0 + (t1 - t0) * (j + .5) / k)[1]:
                    txt = ' '.join(re.sub(r'(\w)-\s*\n\s*', r'\1-', txt).split())   # перенос «react-⏎video» — одно слово
                    if txt:
                        seen[txt] = count_words(txt)
            words = sum(seen.values())
            rate = words / (t1 - t0)
            flag = rate > a.wps
            n_bad += flag
            print('   чтение: %d слов за %.2f с = %.2f сл/с%s%s' % (words, t1 - t0, rate,
                  '   НАРУШЕНИЕ: норма %.1f' % a.wps if flag else '', ('  [' + ' | '.join(seen) + ']') if seen else ''))
    print('нарушений: %d' % n_bad)
    sys.exit(1 if n_bad else 0)


if __name__ == '__main__':
    main()
