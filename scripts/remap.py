#!/usr/bin/env python3
"""Версия ролика другой длины без перерисовки сцен: перекарта времени.

  remap.py timeline.json points.json -o timeline_long.json
  remap.py timeline.json --points "0:0,2:2,3.15:3,10:8" -o timeline_long.json

Точки — пары [новое, старое] (в JSON: список пар или {"remap": [...]}; в --points: новое:старое через запятую).
Между точками время кусочно-линейное: наклон < 1 — замедление, старое стоит — стоп-кадр.
render.py video out.mp4 --remap timeline_long.json рисует кадр τ как render(f(τ), τ).
Пишет: remap, новый end, cues (t, dur, шаг серии — по местному наклону), scenes (t0, t1), секции music — в новом времени.
"""
import argparse
import json
import os
import sys

def die(msg):
    print('ошибка: ' + msg, file=sys.stderr)
    raise SystemExit(2)


def read_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        die('нет файла %s' % path)
    except json.JSONDecodeError as e:
        die('%s: битый JSON (%s)' % (path, e))


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


def parse_points(s):
    try:
        return [[float(x) for x in p.split(':')] for p in s.split(',') if p.strip()]
    except ValueError:
        die('--points пишутся как новое:старое через запятую: "0:0,2:2,3.15:3"')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('timeline', help='исходный timeline.json')
    ap.add_argument('points_file', nargs='?', help='JSON с точками [[новое, старое], ...] или {"remap": [...]}')
    ap.add_argument('--points', help='точки строкой: "0:0,2:2,3.15:3"')
    ap.add_argument('-o', '--out', required=True, help='выходной таймлайн')
    a = ap.parse_args()
    if bool(a.points_file) == bool(a.points):
        die('нужен ровно один источник точек: файл или --points')
    if a.points:
        pts = parse_points(a.points)
    else:
        raw = read_json(a.points_file)
        pts = raw['remap'] if isinstance(raw, dict) else raw
    pts = check_remap(pts, a.points or a.points_file)

    tl = read_json(a.timeline)
    if 'remap' in tl:
        die('%s уже перекартирован — берите исходный таймлайн' % a.timeline)
    end_old = float(tl['end'])
    if pts[-1][1] > end_old + 1e-9:
        die('точки уходят за конец исходного ролика: %g > end %g' % (pts[-1][1], end_old))
    if pts[-1][1] < end_old - 1e-9:
        print('внимание: карта кончается на старом %g с, хвост %g…%g с в новую версию не попадёт' % (
            pts[-1][1], pts[-1][1], end_old))
    g = lambda old: finv(pts, old)
    r4 = lambda x: round(x, 4)

    out = dict(tl)
    out['end'] = r4(pts[-1][0])
    out['remap'] = [[r4(n), r4(o)] for n, o in pts]
    out['remap_source'] = {'file': os.path.basename(a.timeline), 'end': end_old}
    cues = []
    for c in tl.get('cues', []):
        if float(c['t']) > pts[-1][1] + 1e-9:
            continue
        n = dict(c)
        t = g(float(c['t']))
        n['t'] = r4(t)
        if 'dur' in c:
            n['dur'] = r4(g(float(c['t']) + float(c['dur'])) - t)
        if 'step' in c and 'n' in c and int(c['n']) > 1:
            k = int(c['n']) - 1                     # шаг — по местному наклону: последняя доля серии встаёт на своё событие
            n['step'] = r4((g(float(c['t']) + k * float(c['step'])) - t) / k)
        cues.append(n)
    out['cues'] = cues
    if 'scenes' in tl:
        out['scenes'] = [dict(s, t0=r4(g(float(s['t0']))), t1=r4(g(float(s['t1'])))) for s in tl['scenes']]
    if isinstance(tl.get('music'), dict):
        out['music'] = {k: [r4(g(float(v[0]))), r4(g(float(v[1])))] if isinstance(v, list) and len(v) == 2 else v
                        for k, v in tl['music'].items()}
    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('remap ok: %s — %.2f с → %.2f с, точек %d, cues %d' % (a.out, end_old, out['end'], len(pts), len(cues)))
    for s in out.get('scenes', []):
        print('  сцена %-10s %6.3f – %6.3f' % (s.get('id', '?'), s['t0'], s['t1']))
    for c in cues:
        print('  %6.3f %-7s %s' % (c['t'], c['type'], {k: v for k, v in c.items() if k not in ('t', 'type')}))


if __name__ == '__main__':
    main()
