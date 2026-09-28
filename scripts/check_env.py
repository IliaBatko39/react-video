#!/usr/bin/env python3
"""Проверка окружения react-video: Python-модули, Chromium для Playwright, ffmpeg с нужными фильтрами, Node.js.

  check_env.py [--gl]     --gl — ещё проверить WebGL через SwiftShader (3D без видеокарты)

Node.js проверяется как предупреждение: он нужен только для React-шаблона.
На каждую проблему печатает команду установки. Код выхода 1, если что-то не так (Node на код не влияет).
"""
import argparse
import importlib
import os
import platform
import re
import shutil
import subprocess
import sys

MODULES = [('playwright', 'playwright'), ('numpy', 'numpy'), ('PIL', 'pillow'), ('scipy', 'scipy'),
           ('soundfile', 'soundfile')]
REQUIREMENTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'requirements.txt')
problems = []
warnings = []


def ok(msg):
    print('  ок   ' + msg)


def bad(msg, fix):
    print('  НЕТ  ' + msg)
    problems.append((msg, fix))


def warn(msg, fix):
    print('  ВНИМ ' + msg)
    warnings.append((msg, fix))


def ffmpeg_hint():
    s = platform.system()
    if s == 'Darwin':
        return 'brew install ffmpeg'
    if s == 'Windows':
        return 'winget install Gyan.FFmpeg'
    return 'sudo apt install ffmpeg   (Fedora: sudo dnf install ffmpeg, Arch: sudo pacman -S ffmpeg)'


def check_python():
    print('Python %s' % platform.python_version())
    if sys.version_info < (3, 10):
        bad('Python 3.10 или новее (нужен numpy 2.2+, pillow 12+)', 'поставьте Python 3.10+')
    for mod, pkg in MODULES:
        try:
            m = importlib.import_module(mod)
            ver = getattr(m, '__version__', None)
            if ver is None:
                try:
                    from importlib.metadata import version
                    ver = version(pkg)
                except Exception:
                    ver = '?'
            ok('%s %s' % (pkg, ver))
        except Exception as e:
            bad('модуль %s (%s)' % (pkg, e.__class__.__name__), 'python3 -m pip install -r "%s"   (или: python3 -m pip install %s)' % (REQUIREMENTS, pkg))


def check_ffmpeg():
    print('ffmpeg')
    for tool in ('ffmpeg', 'ffprobe'):
        if not shutil.which(tool):
            bad(tool + ' в PATH', ffmpeg_hint())
            return
    ver = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True).stdout.splitlines()[0]
    ok(ver)
    filters = subprocess.run(['ffmpeg', '-hide_banner', '-filters'], capture_output=True, text=True).stdout
    encoders = subprocess.run(['ffmpeg', '-hide_banner', '-encoders'], capture_output=True, text=True).stdout
    names_f = {ln.split()[1] for ln in filters.splitlines() if len(ln.split()) > 2}
    names_e = {ln.split()[1] for ln in encoders.splitlines() if len(ln.split()) > 2}
    for f in ('alimiter', 'ebur128', 'apad', 'concat', 'trim'):
        if f in names_f:
            ok('фильтр ' + f)
        else:
            bad('фильтр ' + f, 'нужен полный ffmpeg: ' + ffmpeg_hint())
    for e in ('libx264', 'aac'):
        if e in names_e:
            ok('кодер ' + e)
        else:
            bad('кодер ' + e, 'нужен ffmpeg с libx264 (сборка из репозитория ОС): ' + ffmpeg_hint())


NODE_FIX = 'Node.js 20.19+ или 22.12+ (Node 21 не подходит): https://nodejs.org или nvm install 22'


def check_node():
    print('Node.js (только для React-шаблона)')
    node = shutil.which('node')
    if not node:
        warn('нет node в PATH — без него работает только HTML-шаблон', NODE_FIX)
        return
    try:
        out = subprocess.run([node, '--version'], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception as e:
        warn('node --version не отработал (%s)' % e.__class__.__name__, NODE_FIX)
        return
    m = re.match(r'v?(\d+)\.(\d+)\.(\d+)', out)
    if not m:
        warn('непонятная версия Node: %r' % out, NODE_FIX)
        return
    v = tuple(int(x) for x in m.groups())
    # Vite 8: ^20.19.0 || >=22.12.0
    if (v[0] == 20 and v >= (20, 19, 0)) or v >= (22, 12, 0):
        ok('Node.js %s' % out)
    else:
        warn('Node.js %s — Vite 8 нужен 20.19+ или 22.12+' % out, NODE_FIX)


GL_JS = '''() => {
  const c = document.createElement('canvas'); const gl = c.getContext('webgl2') || c.getContext('webgl');
  if (!gl) return null;
  const d = gl.getExtension('WEBGL_debug_renderer_info');
  return {v: gl.getParameter(gl.VERSION), r: d ? gl.getParameter(d.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER)};
}'''


def check_chromium(gl):
    print('Chromium (Playwright)')
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        bad('Playwright не импортируется — Chromium не проверить', 'python3 -m pip install playwright')
        return
    install = 'python3 -m playwright install chromium' + (
        '   (не хватает системных библиотек: sudo python3 -m playwright install-deps chromium)' if platform.system() == 'Linux' else '')
    args = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist',
            '--font-render-hinting=none', '--disable-lcd-text']
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(args=args)
            try:
                pg = b.new_page(viewport={'width': 320, 'height': 240})
                pg.set_content('<canvas></canvas>')
                ok('Chromium %s запускается' % b.version)
                if gl:
                    info = pg.evaluate(GL_JS)
                    if not info:
                        bad('WebGL через SwiftShader недоступен', install + '; для 3D на видеокарте — render.py --gpu')
                    elif 'swiftshader' not in (info['r'] or '').lower():
                        ok('WebGL есть (%s), но рендерер не SwiftShader: %s' % (info['v'], info['r']))
                    else:
                        ok('WebGL через SwiftShader: %s / %s' % (info['v'], info['r']))
            finally:
                b.close()
    except Exception as e:
        bad('Chromium не запускается: %s' % str(e).strip().splitlines()[0], install)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--gl', action='store_true', help='проверить WebGL через SwiftShader')
    a = ap.parse_args()
    check_python()
    check_ffmpeg()
    check_chromium(a.gl)
    check_node()
    print()
    if warnings:
        print('Предупреждений: %d (на код выхода не влияют):' % len(warnings))
        for msg, fix in warnings:
            print('  - %s:\n      %s' % (msg, fix))
    if problems:
        print('Проблем: %d. Что сделать:' % len(problems))
        for msg, fix in problems:
            print('  - %s:\n      %s' % (msg, fix))
        sys.exit(1)
    print('Окружение готово.')


if __name__ == '__main__':
    main()
