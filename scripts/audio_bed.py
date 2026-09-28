#!/usr/bin/env python3
"""Музыкальная подложка и звуковые эффекты по timeline.json — только синтез (numpy + scipy).

  python3 audio_bed.py [--timeline timeline.json] [--out mix.wav] [--stems stems]
                       [--key Am] [--seed 1] [--lufs -14] [--style drive|calm]

Музыка идёт по сетке bpm: барабаны, бас по корням аккордов, пэд и арпеджио в тональности
(минор i–VI–III–VII, мажор I–V–vi–IV). Секции music: intro — мягкий вход, main — основная часть,
gap — тишина музыки перед главным ударом, outro — финальный аккорд с хвостом.
Эффекты по cues: hit, boom, tick, click — атака ровно в t; riser, swell — заканчиваются в t + dur;
whoosh — пик в середине dur.

Выход: mix.wav (48 кГц, 24 бит, стерео, длина ровно round(end * 48000) сэмплов, -14 LUFS,
true peak <= -1 dBTP), stems/{drums,bass,music,sfx}.wav (float32, до лимитера, с общим усилением —
для vo_mix.py), audio_report.txt рядом с mix.wav. Один --seed — один и тот же файл.
Нужны numpy, scipy, soundfile и ffmpeg в PATH (ffmpeg — только для сверки громкости в отчёте).
"""
import argparse
import json
import os
import re
import subprocess
import sys

import numpy as np
import soundfile as sf
from scipy.io import wavfile
from scipy.ndimage import minimum_filter1d, uniform_filter1d
from scipy.signal import butter, lfilter, oaconvolve, resample_poly, sosfilt, sosfiltfilt, istft, stft

SR = 48000
EPS = 1e-12
CUE_TYPES = ('hit', 'boom', 'whoosh', 'riser', 'tick', 'click', 'swell')
CUE_DEFAULTS = {'whoosh': {'dur': 0.4}, 'riser': {'dur': 1.0}, 'swell': {'dur': 1.0},
                'tick': {'n': 1, 'step': 0.25}}
SECTION_KEYS = ('intro', 'main', 'gap', 'outro')


def warn(msg):
    print('ВНИМАНИЕ: ' + msg, file=sys.stderr, flush=True)


# ============================ базовые блоки ============================
def ns(sec): return int(round(sec * SR))
def tt(n): return np.arange(n) / SR
def midi(m): return 440.0 * 2 ** ((m - 69) / 12)


def _sos(kind, fc, order):
    if kind == 'band':
        lo, hi = fc
        return butter(order, [lo, min(hi, SR / 2 * 0.95)], 'band', fs=SR, output='sos')
    return butter(order, min(fc, SR / 2 * 0.95), kind, fs=SR, output='sos')
def lp(x, fc, order=2): return sosfilt(_sos('low', fc, order), x, axis=-1)
def hp(x, fc, order=2): return sosfilt(_sos('high', fc, order), x, axis=-1)
def bp(x, lo, hi, order=2): return sosfilt(_sos('band', (lo, hi), order), x, axis=-1)


def fades(x, a=0.001, r=0.004):
    """короткие входной и выходной фейды — без щелчков на краях"""
    x = np.array(x, dtype=float); n = x.shape[-1]
    na, nr = min(ns(a), n), min(ns(r), n)
    if na: x[..., :na] *= np.linspace(0, 1, na, endpoint=False)
    if nr: x[..., n - nr:] *= np.linspace(1, 0, nr)
    return x


def sine_glide(f):
    """синус по массиву мгновенных частот (Гц на сэмпл)"""
    return np.sin(2 * np.pi * np.cumsum(f) / SR)


def saw_blep(freq, n, ph0=0.0):
    """пила с polyBLEP — без алиасинга на высоких нотах"""
    inc = np.broadcast_to(np.asarray(freq, float) / SR, (n,))
    ph = (ph0 + np.cumsum(inc)) % 1.0
    y = 2 * ph - 1
    m = ph < inc; t = ph[m] / inc[m]; y[m] -= t + t - t * t - 1
    m = ph > 1 - inc; t = (ph[m] - 1) / inc[m]; y[m] -= t * t + t + t + 1
    return y


def supersaw(freq, n, rng, voices=5, spread=14):
    """несколько расстроенных пил, разложенных по стерео"""
    L, R = np.zeros(n), np.zeros(n)
    for i, d in enumerate(np.linspace(-spread, spread, voices)):
        v = saw_blep(np.asarray(freq) * 2 ** (d / 1200), n, rng.random())
        w = i / (voices - 1)
        L += v * np.cos(w * np.pi / 2); R += v * np.sin(w * np.pi / 2)
    return np.array([L, R]) / np.sqrt(voices / 2)


def tv_filter(x, fc_fn, kind='lp', q=0.6, order=2):
    """фильтр с меняющейся частотой через STFT (гладкая АЧХ, без звона); fc_fn(t с от начала x)"""
    nper, hop = 1024, 256
    n = x.shape[-1]
    if n < nper:
        x = np.pad(x, [(0, 0)] * (x.ndim - 1) + [(0, nper - n)])
    f, tf, Z = stft(x, fs=SR, nperseg=nper, noverlap=nper - hop)
    F = np.maximum(f[:, None], 1.0); FC = np.maximum(np.asarray(fc_fn(tf), float)[None, :], 10.0)
    if kind == 'lp': G = 1 / np.sqrt(1 + (F / FC) ** (2 * order))
    elif kind == 'hp': G = 1 / np.sqrt(1 + (FC / F) ** (2 * order))
    else: G = np.exp(-0.5 * (np.log2(F / FC) / q) ** 2)
    _, y = istft(Z * G, fs=SR, nperseg=nper, noverlap=nper - hop)
    y = y[..., :n]
    if y.shape[-1] < n: y = np.pad(y, [(0, 0)] * (y.ndim - 1) + [(0, n - y.shape[-1])])
    return y


def add(buf, x, t0, gain=1.0, pan=0.0):
    """вписать x (моно (n,) или стерео (2,n)) в buf с отсчёта round(t0*SR); панорама постоянной мощности"""
    N = buf.shape[1]
    i = ns(t0)
    x = np.asarray(x, float)
    if x.ndim == 1:
        l, r = np.cos((pan + 1) * np.pi / 4) * 1.41421356, np.sin((pan + 1) * np.pi / 4) * 1.41421356
        x = np.array([x * l, x * r])
    elif pan:
        x = x * np.array([[min(1, 1 - pan)], [min(1, 1 + pan)]])
    j0 = max(0, -i); i = max(0, i)
    if i >= N or j0 >= x.shape[1]: return
    x = x[:, j0:j0 + N - i]
    buf[:, i:i + x.shape[1]] += x * gain


# ============================ таймлайн и гармония ============================
NOTE_PC = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
PC_NAME = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']


def parse_key(s):
    """'Am', 'C', 'F#m', 'Ebm', 'Bb' -> (тоника 0..11, минор?)"""
    m = re.fullmatch(r'\s*([A-G])([#b]?)\s*(m|min|minor|maj|major)?\s*', str(s))
    if not m:
        sys.exit(f'ошибка: тональность «{s}» не разобрана — пример: Am, C, F#m, Ebm')
    pc = (NOTE_PC[m.group(1)] + {'#': 1, 'b': -1, '': 0}[m.group(2)]) % 12
    return pc, m.group(3) in ('m', 'min', 'minor')


def parse_sections(tl, end):
    """music -> {'intro': [(a,b)], 'main': [...], 'gap': [...], 'outro': [...]}; чужие ключи — предупреждение"""
    mus = tl.get('music')
    sec = {k: [] for k in SECTION_KEYS}
    if not isinstance(mus, dict) or not mus:
        sec['main'] = [(0.0, end)]
        return sec
    for k, v in mus.items():
        if k not in SECTION_KEYS:
            warn(f'music.{k}: неизвестная секция — пропущена (понимаю {", ".join(SECTION_KEYS)})')
            continue
        items = v if (isinstance(v, list) and v and isinstance(v[0], (list, tuple))) else [v]
        for it in items:
            try:
                a, b = float(it[0]), float(it[1])
            except (TypeError, ValueError, IndexError):
                warn(f'music.{k}: ожидаю [t0, t1], получено {it!r} — пропущено'); continue
            a, b = max(0.0, a), min(end, b)
            if b - a > 1e-6: sec[k].append((a, b))
    if not any(sec[k] for k in ('intro', 'main', 'outro')):
        warn('в music нет intro/main/outro — вся длина считается main')
        sec['main'] = [(0.0, end)]
    return sec


def build_context(tl, key, style, seed):
    """всё, что нужно блокам рендера: длины, сетка, секции, аккорды, генератор случайных чисел"""
    c = argparse.Namespace()
    c.end = float(tl['end'])
    c.N = ns(c.end)
    c.bpm = float(tl.get('bpm') or 120)
    c.beat = 60.0 / c.bpm; c.bar = 4 * c.beat; c.s16 = c.beat / 4
    c.style = style
    c.rng = np.random.default_rng(seed)
    c.seed = seed
    c.sec = parse_sections(tl, c.end)
    c.origin = c.sec['main'][0][0] if c.sec['main'] else 0.0
    c.tonic, c.minor = parse_key(key)
    c.key_name = PC_NAME[c.tonic] + ('m' if c.minor else '')
    # прогрессия: (ступень в полутонах от тоники, минорное трезвучие?)
    c.prog = [(0, True), (8, False), (3, False), (10, False)] if c.minor else \
             [(0, False), (7, False), (9, True), (5, False)]
    c.bass_tonic = 28 + (c.tonic - 28) % 12                      # E1..D#2
    # отрезки: границы секций, gap, такты main
    bounds = {0.0, c.end}
    for k in SECTION_KEYS:
        for a, b in c.sec[k]: bounds |= {a, b}
    for a, b in c.sec['main']:
        bounds |= set(grid_times(c, a, b, c.bar))
    bounds = sorted(x for x in bounds if 0 <= x <= c.end)
    c.segs = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        if b - a < 1e-6: continue
        s = section_at(c, (a + b) / 2)
        if s == 'gap': continue
        c.segs.append((a, b, s, chord_at(c, (a + b) / 2)))
    c.cues = []
    for q in sorted(tl.get('cues', []), key=lambda q: float(q.get('t', 0))):
        if q.get('type') not in CUE_TYPES:
            warn(f'cue {q!r}: тип не из {CUE_TYPES} — пропущен'); continue
        q = dict(CUE_DEFAULTS.get(q['type'], {}), **q)
        q['t'] = float(q['t'])
        c.cues.append(q)
    return c


def section_at(c, t):
    for k in ('gap', 'outro', 'intro', 'main'):
        if any(a - 1e-9 <= t < b - 1e-9 for a, b in c.sec[k]): return k
    return 'main'


def in_gap(c, t): return section_at(c, t) == 'gap'


def grid_times(c, t0, t1, step):
    """точки сетки origin + k*step в [t0, t1)"""
    k0 = int(np.ceil((t0 - c.origin) / step - 1e-9))
    out = []
    while True:
        t = c.origin + k0 * step
        if t >= t1 - 1e-9: break
        out.append(t); k0 += 1
    return out


def beat_index(c, t, step): return int(round((t - c.origin) / step))


def chord_at(c, t):
    """(ноты пэда MIDI, корень баса MIDI, имя) для момента t"""
    s = section_at(c, t)
    if s == 'outro':
        third = 3 if c.minor else 4
        ivs, root, name = [0, third, 7, 14], 0, PC_NAME[c.tonic] + ('m' if c.minor else '') + 'add9'
    else:
        k = 0 if s == 'intro' else int(np.floor((t - c.origin) / c.bar + 1e-9)) % 4
        root, mn = c.prog[k]
        ivs = [0, 3 if mn else 4, 7, 12]
        name = PC_NAME[(c.tonic + root) % 12] + ('m' if mn else '')
    rpc = c.tonic + root
    notes = []
    for iv in ivs:                                   # каждая нота — в октаве ближе к E4 (64), октава/нона выше
        p = rpc + iv
        centre = 64 if iv < 12 else 71
        p += 12 * int(np.round((centre - p) / 12))
        notes.append(p)
    notes = sorted(set(notes))
    bass = 28 + (rpc - 28) % 12
    return notes, bass, name


# ============================ инструменты ============================
def kick(c, gain_click=0.2):
    n = ns(0.40); t = tt(n)
    f_end = midi(c.bass_tonic)                         # бочка настроена в тонику
    f = f_end + (165 - f_end) * np.exp(-t * 36) + 260 * np.exp(-t * 420)
    amp = np.where(t < 0.04, 1.0, np.exp(-(t - 0.04) * 15.0))
    body = np.tanh(1.8 * sine_glide(f) * amp) / np.tanh(1.8)
    click = bp(c.rng.standard_normal(n), 1500, 6000) * np.exp(-t * 280) * gain_click
    return fades(body + click, 0.0004, 0.015)


def clap(c):
    n = ns(0.36); t = tt(n)
    e = sum((t >= o) * np.exp(-np.maximum(t - o, 0) * 170) for o in (0, 0.0085, 0.018))
    e = e + (t >= 0.027) * np.exp(-np.maximum(t - 0.027, 0) * 15) * 0.7
    x = np.array([bp(c.rng.standard_normal(n), 900, 6500), bp(c.rng.standard_normal(n), 900, 6500)]) * e * 0.55
    return fades(lp(x, 9000), 0.0003, 0.02)


def snare_soft(c):
    """мягкий рим/снейр для спокойного стиля"""
    n = ns(0.25); t = tt(n)
    body = sine_glide(np.full(n, 220.0) * (1 + 0.5 * np.exp(-t * 80))) * np.exp(-t * 30)
    nz = bp(c.rng.standard_normal(n), 1500, 7000) * np.exp(-t * 28)
    return fades(lp(0.6 * body + 0.5 * nz, 8000), 0.0003, 0.02)


F808 = [205.3, 304.4, 369.6, 522.7, 540.0, 800.0]


def hat(c, open_=False):
    n = ns(0.32 if open_ else 0.07); t = tt(n)
    sq = sum(np.sign(np.sin(2 * np.pi * f * 2.05 * t + c.rng.random() * 6)) for f in F808) / 6
    x = bp(0.55 * sq + 0.6 * c.rng.standard_normal(n), 6800, 11500, 2)
    x = lp(x, 11000, 2) * np.exp(-t * (9 if open_ else 60))
    return fades(x, 0.0005, 0.01)


def crash(c, dur=2.4):
    n = ns(dur); t = tt(n)
    sq = sum(np.sign(np.sin(2 * np.pi * f * 3.1 * t + c.rng.random() * 6)) for f in F808) / 6
    x = np.array([bp(0.4 * sq + c.rng.standard_normal(n), 3200, 11000),
                  bp(0.4 * sq + c.rng.standard_normal(n), 3200, 11000)])
    x = lp(x, 10500) * (np.exp(-t * 2.4) * 0.8 + np.exp(-t * 18) * 0.5)
    return fades(x, 0.0008, 0.05)


def sub_note(m, dur, rel=0.03, att=0.004):
    n = ns(dur + rel); t = tt(n)
    ph = 2 * np.pi * midi(m) * t
    x = np.sin(ph) + 0.12 * np.sin(2 * ph)
    e = np.minimum(1, t / att) * np.clip((dur + rel - t) / rel, 0, 1)
    return x * e


def mid_bass(m, dur=0.22):
    n = ns(dur + 0.02); t = tt(n)
    f = midi(m + 12)
    x = 0.5 * saw_blep(f * 0.997, n, 0.1) + 0.5 * saw_blep(f * 1.003, n, 0.6) + 0.4 * np.sin(2 * np.pi * f * t)
    dark, bright = lp(x, 380, 2), lp(x, 1900, 2)
    y = dark + (bright - dark) * np.exp(-t * 28)
    return fades(y * np.exp(-t * 4), 0.002, 0.02)


def pluck(f, dur=0.32, bright=1.0):
    n = ns(dur); t = tt(n); x = np.zeros(n)
    for k in range(1, 12):
        if f * k > 9000: break
        x += np.sin(2 * np.pi * f * k * t + k * 0.7) * np.exp(-t * (7 + 10 * k / bright)) / k
    return fades(x, 0.001, 0.01)


def bell(f, dur=1.4, dec=2.6):
    n = ns(dur); t = tt(n); x = np.zeros(n)
    for r, a, d in [(1, 1, 1), (2.0, .5, 1.6), (2.76, .32, 2.3), (5.4, .16, 3.6), (8.93, .07, 5.5)]:
        if f * r < 7000: x += a * np.sin(2 * np.pi * f * r * t) * np.exp(-t * dec * d)
    return fades(x, 0.0008, 0.02)


def low_hit(c, f_hi, f_lo, dec, drive=1.6, dur=0.5):
    n = ns(dur); t = tt(n)
    f = f_lo + (f_hi - f_lo) * np.exp(-t * 40)
    return fades(np.tanh(drive * sine_glide(f) * np.exp(-t * dec)) / np.tanh(drive), 0.0004, 0.01)


def click_burst(c, n_ms=3, lo=1500, hi=6000, dec=700):
    n = ns(n_ms / 1000 + 0.02); t = tt(n)
    return fades(bp(c.rng.standard_normal(n), lo, hi) * np.exp(-t * dec), 0.0002, 0.003)


def noise_sweep(c, n, f0, f1, q=0.5, shape=None):
    """стерео шум полосой, центр ползёт f0 -> f1 (экспоненциально по доле длины)"""
    d = n / SR
    shape = shape or (lambda p: p)
    return tv_filter(c.rng.standard_normal((2, n)), lambda tf: f0 * (f1 / f0) ** shape(np.clip(tf / d, 0, 1)), 'bp', q=q)


def pan_move(x, p0, p1):
    n = x.shape[-1]; p = np.linspace(p0, p1, n)
    m = x if x.ndim == 1 else x.mean(axis=0)
    return np.array([m * np.cos((p + 1) * np.pi / 4), m * np.sin((p + 1) * np.pi / 4)]) * 1.41421356


# ============================ рендер: ударные ============================
def render_drums(c):
    """бочка/клэп/хэты по сетке; возвращает (стем, список бочек для сайдчейна)"""
    drums = np.zeros((2, c.N)); kicks = []
    K = kick(c); CL = clap(c); SN = snare_soft(c)
    HC = [hat(c) for _ in range(4)]; HO = [hat(c, True) for _ in range(2)]
    calm = c.style == 'calm'

    def put_kick(t, g):
        if in_gap(c, t): return
        add(drums, K, t, g * 0.85); kicks.append((t, g))

    for a, b in c.sec['intro']:                  # мягкий вход: хэты 8-ми нарастают, без бочки
        for t in grid_times(c, a, b, c.beat / 2):
            if in_gap(c, t): continue
            p = (t - a) / max(b - a, 1e-6)
            k = beat_index(c, t, c.beat / 2)
            add(drums, HC[k % 4], t, (0.04 + 0.16 * p ** 2) * (0.6 if calm else 1.0), 0.2 if k % 2 else -0.2)

    for a, b in c.sec['main']:
        add(drums, crash(c, 2.4), a, 0.14 if calm else 0.26)
        for t in grid_times(c, a, b, c.beat):
            k = beat_index(c, t, c.beat) % 4
            if calm:
                if k == 0: put_kick(t, 0.75)
                if k == 2: add(drums, SN, t, 0.28, 0.05)
            else:
                put_kick(t, 1.0 if k == 0 else 0.9)
                if k % 2 == 1 and not in_gap(c, t): add(drums, CL, t, 0.42, 0.05)
        if calm:                                  # бочка ещё на «и» третьей доли
            for t in grid_times(c, a, b, c.beat / 2):
                if beat_index(c, t, c.beat / 2) % 8 == 5: put_kick(t, 0.5)
            for t in grid_times(c, a, b, c.beat / 2):
                if in_gap(c, t): continue
                k = beat_index(c, t, c.beat / 2)
                add(drums, HC[k % 4], t, 0.10 if k % 2 else 0.14, -0.2 if k % 2 else 0.2)
        else:                                     # хэты 16-ми, открытые на офф-битах 8-х
            for t in grid_times(c, a, b, c.s16):
                if in_gap(c, t): continue
                k = beat_index(c, t, c.s16); pos = k % 4
                if pos == 2: add(drums, HO[k // 4 % 2], t, 0.30 * 0.55, 0.25)
                else: add(drums, HC[k % 4], t, 0.30 * [0.55, 0.3, 0.8, 0.38][pos], -0.2 if pos % 2 else 0.2)

    for a, b in c.sec['outro']:                  # удар на входе и лёгкий затухающий грув в первый такт
        put_kick(a, 0.55 if calm else 0.8)
        add(drums, crash(c, 3.0), a, 0.18 if calm else 0.30)
        if not calm:
            for t in grid_times(c, a, min(b, a + c.bar), c.beat / 2):
                k = beat_index(c, t, c.beat / 2); p = (t - a) / c.bar
                add(drums, HO[0] if k % 2 else HC[1], t, (0.12 if k % 2 else 0.1) * (1 - 0.7 * p), 0.2)
    return drums, kicks


# ============================ рендер: бас ============================
def render_bass(c):
    bass = np.zeros((2, c.N)); exempt = np.zeros((2, c.N))
    calm = c.style == 'calm'
    for a, b, s, (notes, root, name) in c.segs:
        if s == 'main':
            add(bass, sub_note(root, b - a - 0.02, att=0.004 if not calm else 0.03), a, 0.30 if calm else 0.34)
            for t in grid_times(c, a, b, c.beat / 2):
                k = beat_index(c, t, c.beat / 2)
                if in_gap(c, t) or t + 0.22 > b + 1e-6 and in_gap(c, b + 1e-4): continue
                if calm:
                    if k % 8 == 0: add(bass, mid_bass(root, 0.5), t, 0.16)
                elif k % 2 == 1:
                    add(bass, mid_bass(root), t, 0.36)
        elif s == 'outro':
            if a in [x for x, _ in c.sec['outro']]:
                L = c.end - a
                x = sub_note(root, L - 0.02, rel=0.02, att=0.01) * np.exp(-tt(ns(L)) * 0.9)
                add(exempt, x, a, 0.40)
                add(bass, mid_bass(root, 0.5), a, 0.22)
    return bass, exempt


# ============================ рендер: музыка ============================
def render_music(c):
    """пэд по отрезкам аккордов + арпеджио; финальный аккорд в outro"""
    music = np.zeros((2, c.N))
    calm = c.style == 'calm'
    intro_ends = [b for _, b in c.sec['intro']]

    def pad_fc(t):
        for a, b in c.sec['intro']:
            if a <= t < b: return 300 + 1500 * ((t - a) / (b - a)) ** 2
        for a, b in c.sec['outro']:
            if t >= a: return 2200 * np.exp(-(t - a) * 0.35) + 500
        return 1300 if calm else 1800
    pad_fc_v = np.vectorize(pad_fc)

    for k, (a, b, s, (notes, root, name)) in enumerate(c.segs):
        last = b >= c.end - 1e-6
        followed_by_gap = in_gap(c, b + 1e-4)
        rel = (c.end - b + 0.01) if last else (0.004 if followed_by_gap else 0.25)
        if s == 'intro': att, g = max(0.05, min(1.5, 0.7 * (b - a))), 0.15
        elif s == 'outro': att, g = 0.02, 0.17
        else: att, g = 0.02, (0.14 if calm else 0.09)
        if s == 'main' and any(abs(a - e) < 1e-6 for e in intro_ends): att = 0.02
        n = ns(b - a + rel); t = tt(n)
        x = np.zeros((2, n))
        for m in notes: x += supersaw(midi(m), n, c.rng, 5, 18)
        x = tv_filter(x / len(notes) ** 0.5, lambda tf, a=a: pad_fc_v(a + tf), 'lp', order=2)
        e = np.minimum(1, t / att) * np.clip((b - a + rel - t) / rel, 0, 1)
        add(music, hp(x, 150) * e, a, g)

    pat = [0, 2, 1, 3, 2, 1, 3, 2]
    for a, b in c.sec['main']:                   # арпеджио: со второго такта main
        step = c.beat / 2 if calm else c.s16
        for t in grid_times(c, a + (c.bar if b - a > 2 * c.bar else 0), b, step):
            if in_gap(c, t) or in_gap(c, t + 0.05): continue
            k = beat_index(c, t, step)
            notes = [m + 12 for m in chord_at(c, t)[0]]
            m = notes[pat[k % 8] % len(notes)]
            v = 1.0 if k % 4 == 0 else 0.6
            add(music, pluck(midi(m), 0.3, 0.7 if calm else 0.9), t, (0.07 if calm else 0.05) * v,
                0.45 if k % 2 else -0.45)
    for a, b in c.sec['outro']:                  # финальный аккорд колоколом поверх пэда
        notes = chord_at(c, a + 1e-4)[0]
        for j, m in enumerate(notes):
            add(music, bell(midi(m + 12), min(3.0, c.end - a), 1.4), a + 0.012 * j, 0.05, -0.4 + 0.8 * j / max(1, len(notes) - 1))
    return music


# ============================ сайдчейн ============================
def duck_curve(c, kicks, depth, rel):
    d = np.ones(c.N); L = ns(rel); tx = tt(L)
    shape = 1 - depth * (1 - np.clip(tx / rel, 0, 1) ** 1.6) * np.minimum(1, tx / 0.002 + 0.6)
    for t, g in kicks:
        i = ns(t); j = min(c.N, i + L)
        if j > i: d[i:j] = np.minimum(d[i:j], 1 - (1 - shape[:j - i]) * min(1, g))
    return d


# ============================ эффекты ============================
def fx_hit(c, q):
    """средний удар: низ с глиссандо, щелчок, короткий шум"""
    n = ns(0.6); t = tt(n)
    x = low_hit(c, 150, midi(c.bass_tonic + 12), 9, 2.0, 0.6)
    x = x + lp(c.rng.standard_normal(n), 2500) * np.exp(-t * 45) * 0.4
    ck = click_burst(c, 2, 800, 5000, 500); x[:len(ck)] += ck * 0.6
    return [(q['t'], fades(x, 0.0003, 0.02), 0.55, 0.0)]


def fx_boom(c, q):
    """большой удар: суб с глиссандо вниз, панч, тарелка, звон в тонике"""
    dur = 3.0; n = ns(dur); t = tt(n)
    boom = low_hit(c, 110, midi(c.bass_tonic), 2.4, 1.8, dur)
    punch = bp(c.rng.standard_normal(n), 70, 500) * np.exp(-t * 22) * 0.6
    cr = np.array([bp(c.rng.standard_normal(n), 1800, 9000), bp(c.rng.standard_normal(n), 1800, 9000)]) * \
        (np.exp(-t * 4.0) * 0.3 + np.exp(-t * 30) * 0.5)
    ring = sum(a * np.sin(2 * np.pi * midi(c.bass_tonic + 12) * r * t + r)
               for r, a in [(1, .5), (2.01, .3), (3.97, .18), (5.43, .1)]) * np.exp(-t * 2.0) * 0.25
    x = np.array([boom + punch + ring] * 2) + cr
    ck = click_burst(c, 3, 700, 5000, 400); x[:, :len(ck)] += ck * 0.6
    return [(q['t'], fades(x, 0.0003, 0.1), 0.8, 0.0)]


def fx_whoosh(c, q):
    """пролёт: шум полосой 300 -> 4000 Гц, пик огибающей ровно в середине dur, панорама справа налево"""
    d = float(q['dur']); n = ns(q['t'] + d) - ns(q['t']); p = np.arange(n) / max(1, n - 1)
    f0, f1 = 300.0, 4000.0
    x = noise_sweep(c, n, f0, f1, 0.5)
    x = x * np.sqrt(f0 / (f0 * (f1 / f0) ** p))          # полоса шире на верху — выравниваем мощность
    env = (1 - np.abs(2 * p - 1)) ** 2.5                  # симметричная огибающая с острым пиком в середине
    x = pan_move(x * env, 0.5, -0.5)
    return [(q['t'], fades(x, 0.001, 0.002), 0.32, 0.0)]


def fx_riser(c, q):
    """подъём: шум полосой вверх + тон с глиссандо на октаву; обрыв ровно в t + dur"""
    d = float(q['dur']); n = ns(q['t'] + d) - ns(q['t']); t = tt(n)
    nz = noise_sweep(c, n, 300, 6000, 0.55)
    root = 48 + (c.tonic - 48) % 12 + 12
    tone = lp(supersaw(midi(root) * 2 ** (t / d), n, c.rng, 5, 20), 3500)
    x = (lp(nz, 7500) * 0.8 + tone * 0.35) * (t / d) ** 2
    return [(q['t'], fades(x, 0.01, 0.0015), 0.24, 0.0)]


def fx_swell(c, q):
    """нарастание: «обратная тарелка» + аккорд тоники, крещендо к t + dur, там же обрыв"""
    d = float(q['dur']); n = ns(q['t'] + d) - ns(q['t']); t = tt(n)
    cym = crash(c, d * 1.6)[:, :n][:, ::-1]
    cym = lp(cym, 8000) * (t / d) ** 1.5
    notes = chord_at(c, q['t'] + d + 1e-4)[0] if not in_gap(c, q['t'] + d + 1e-4) else chord_at(c, q['t'])[0]
    pad = sum(np.sin(2 * np.pi * midi(m) * t) for m in notes) / len(notes) * (t / d) ** 2.5 * 0.35
    x = cym + pad
    return [(q['t'], fades(x, 0.01, 0.0015), 0.30, 0.0)]


def tick_one(c, f):
    n = ns(0.03); t = tt(n)
    x = bp(c.rng.standard_normal(n), 2000, 5000) * np.exp(-t * 900) + 0.5 * np.sin(2 * np.pi * f * t) * np.exp(-t * 350)
    return fades(x, 0.0002, 0.004)


def fx_tick(c, q):
    """серия тиков: n штук с шагом step, чередование высоты и сторон"""
    hi = midi(84 + (c.tonic - 84) % 12 + 12); lo = hi * 2 ** (-5 / 12)
    return [(q['t'] + i * float(q['step']), tick_one(c, hi if i % 2 == 0 else lo), 0.18, 0.3 if i % 2 else -0.3)
            for i in range(int(q['n']))]


def fx_click(c, q):
    """клик интерфейса: короткий щелчок + тональный «тук»"""
    n = ns(0.05); t = tt(n)
    x = click_burst(c, 2, 2000, 8000, 900)[:n]
    x = np.pad(x, (0, n - len(x)))
    x = x + 0.4 * np.sin(2 * np.pi * 1800 * t) * np.exp(-t * 180)
    return [(q['t'], fades(x, 0.0002, 0.005), 0.22, 0.1)]


FX = {'hit': fx_hit, 'boom': fx_boom, 'whoosh': fx_whoosh, 'riser': fx_riser,
      'swell': fx_swell, 'tick': fx_tick, 'click': fx_click}
SWEEP_END = {'riser', 'swell'}      # у этих контрольная точка — конец
SWEEP_PEAK = {'whoosh'}             # у этого — пик в середине


def render_sfx(c):
    sfx = np.zeros((2, c.N)); events = []
    for q in c.cues:
        ev = FX[q['type']](c, q)
        events.append((q, ev))
        for t, x, g, p in ev: add(sfx, x, t, g, p)
    return sfx, events


# ============================ пространство и тишина gap ============================
def make_ir(c, rt=1.6, pre=0.018):
    n = ns(rt * 1.1); t = tt(n); out = []
    for k in (11, 23):
        w = np.random.default_rng([c.seed, k]).standard_normal(n)
        ir = lp(w, 3000) * np.exp(-t * 6.91 / rt) + 0.7 * hp(w, 3000) * np.exp(-t * 6.91 / (rt * 0.45))
        ir = lp(ir, 8500) * np.minimum(1, t / 0.012)
        out.append(np.concatenate([np.zeros(ns(pre)), ir]))
    ir = np.array(out)
    return ir / np.sqrt((ir ** 2).sum(axis=1, keepdims=True))


def gap_masks(c):
    """1 вне gap, 0 внутри; хвосты до gap обрываются (фейд 4 мс), после gap — свои"""
    keep = np.ones(c.N)
    for a, b in c.sec['gap']:
        i0, i1 = ns(a), ns(b); fr = min(ns(0.004), i0)
        keep[i0 - fr:i0] = np.minimum(keep[i0 - fr:i0], np.linspace(1, 0, fr))
        keep[i0:i1] = 0
    return keep


def space(c, x, send, ir, keep):
    """реверб с гейтом по gap: каждый отрезок между gap звучит со своим хвостом, в gap — тишина"""
    x = x * keep
    if send == 0: return x
    out = x.copy()
    edges = [0] + [ns(b) for _, b in sorted(c.sec['gap'])] + [c.N]
    stops = [ns(a) for a, _ in sorted(c.sec['gap'])] + [c.N]
    for s0, s1, stop in zip(edges[:-1], edges[1:], stops):
        seg = np.zeros_like(x); seg[:, s0:s1] = x[:, s0:s1]
        wet = np.array([oaconvolve(hp(seg[ch], 250) * send, ir[ch])[:c.N] for ch in range(2)])
        m = np.zeros(c.N); m[s0:c.N] = 1
        m *= keep if stop < c.N else 1
        if stop < c.N: m[stop:] = 0
        out += wet * m
    return out


def mono_low(x):
    """ниже ~120 Гц — моно: из стороны вычитаем низ"""
    m, s = (x[0] + x[1]) / 2, (x[0] - x[1]) / 2
    s = hp(s, 120, 2)
    return np.array([m + s, m - s])


# ============================ мастер ============================
KB1, KA1 = [1.53512485958697, -2.69169618940638, 1.19839281085285], [1.0, -1.69065929318241, 0.73248077421585]
KB2, KA2 = [1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621]


def momentary(x, blk=0.4, hop=0.1):
    """мощность в окнах 400 мс по BS.1770 (K-фильтр, сумма каналов)"""
    y = lfilter(KB2, KA2, lfilter(KB1, KA1, x, axis=-1), axis=-1)
    p = (y ** 2).sum(axis=0); cs = np.concatenate([[0], np.cumsum(p)])
    b, h = ns(blk), ns(hop); st = np.arange(0, len(p) - b + 1, h)
    return st / SR, (cs[st + b] - cs[st]) / b


def lufs(x):
    """интегральная громкость BS.1770-4: абсолютный гейт -70, относительный -10"""
    _, z = momentary(x)
    z = z[-0.691 + 10 * np.log10(z + EPS) > -70]
    if not len(z): return -120.0
    rel = -0.691 + 10 * np.log10(z.mean()) - 10
    z = z[-0.691 + 10 * np.log10(z) > rel]
    return -0.691 + 10 * np.log10(z.mean())


def tp_env(x):
    """огибающая true peak: оверсэмплинг x4"""
    n = x.shape[1]; up = resample_poly(x, 4, 1, axis=1)
    a = np.abs(up).max(axis=0)[:4 * n].reshape(-1, 4).max(axis=1)
    return np.maximum(a, np.abs(x).max(axis=0))


def true_peak_db(x): return 20 * np.log10(tp_env(x).max() + EPS)


def limiter(x, ceil_db, look=0.004, rel=0.09):
    """лимитер с просмотром вперёд по true peak: мгновенная атака, экспоненциальное отпускание"""
    c = 10 ** (ceil_db / 20); n = x.shape[1]
    g = np.minimum(1.0, c / np.maximum(tp_env(x), EPS)); L = ns(look)
    g2 = uniform_filter1d(minimum_filter1d(g, 2 * L + 1), L + 1)
    a = 1 - np.exp(-1 / (rel * SR)); out = np.empty(n); cur = 1.0
    gl = g2.tolist()
    for i in range(n):
        v = gl[i]
        cur = v if v < cur else cur + (v - cur) * a
        out[i] = cur
    return x * out, out


def master(pre, target):
    """громкость в target LUFS и true peak <= -1 dBTP; возвращает (mix, gain, кривая лимитера, потолок)"""
    gain, ceil = 10 ** ((target - lufs(pre)) / 20), -1.25
    for _ in range(8):
        y, gr = limiter(pre * gain, ceil)
        L, tp = lufs(y), true_peak_db(y)
        if abs(L - target) < 0.05 and tp <= -1.0: break
        gain *= 10 ** ((target - L) / 20)
        if tp > -1.05: ceil -= (tp + 1.05) + 0.05
    return y, gain, gr, ceil


def write_float_wav(path, x):
    """float32 WAV без PEAK-чанка (у libsndfile в нём время записи — ломает побайтовый детерминизм)"""
    wavfile.write(path, SR, np.ascontiguousarray(np.asarray(x, np.float32).T))


def ffmpeg_ebur128(path):
    try:
        eb = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', path, '-af', 'ebur128=peak=true',
                             '-f', 'null', '-'], capture_output=True, text=True).stderr
    except FileNotFoundError:
        return 'ffmpeg не найден в PATH — сверка пропущена'
    lines = [l.strip() for l in eb[eb.rfind('Summary:'):].splitlines()[1:] if l.strip().startswith(('I:', 'LRA:', 'Peak:'))]
    return ' | '.join(lines) if lines else 'нет Summary в выводе ffmpeg'


# ============================ проверка синхрона ============================
def event_band(x):
    """полоса, где сосредоточена энергия первых 15 мс события"""
    x = np.asarray(x); x = x.mean(axis=0) if x.ndim == 2 else x
    x = x[:ns(0.015)]; S = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2; f = np.fft.rfftfreq(len(x), 1 / SR)
    cs = np.cumsum(S) / max(S.sum(), EPS)
    lo, hi = f[np.searchsorted(cs, 0.2)], f[min(len(f) - 1, np.searchsorted(cs, 0.8))]
    return max(30.0, lo * 0.7), min(16000.0, max(hi * 1.4, lo * 2.5))


def attack_time(sm, N, t, win, band):
    """онсет в стеме около t: максимальный прирост огибающей 1 мс к предыдущим 3–12 мс, затем точка 50% подъёма"""
    a, b = max(0, ns(t - 0.3)), min(N, ns(t + 0.3))
    seg = sosfiltfilt(butter(2, [band[0], band[1]], 'band', fs=SR, output='sos'), sm[a:b])
    env = np.sqrt(uniform_filter1d(seg ** 2, ns(0.002)))[::ns(0.001)]
    off = a / SR
    k0 = max(0, int(round((t - win - off) * 1000))); k1 = min(len(env) - 1, int(round((t + win - off) * 1000)))
    best, kb = -1e9, k0
    for k in range(k0, k1 + 1):
        prev = env[max(0, k - 12):max(1, k - 3)].mean() if k >= 4 else 0.0
        d = 20 * np.log10(env[k] + 1e-7) - 20 * np.log10(prev + 1e-7)
        if d > best: best, kb = d, k
    pre_l = env[max(0, kb - 8):max(1, kb - 3)].mean() if kb >= 4 else 0.0
    pk = env[kb:kb + 25].max()
    thr = pre_l + 0.5 * (pk - pre_l)
    k = kb - 4
    while k < kb + 25 and env[max(k, 0)] < thr: k += 1
    return off + max(k, 0) / 1000.0


def sync_report(c, sfx_stem, events, P):
    sm = sfx_stem.mean(axis=0); alld = []; bad = []
    P('%-7s %-7s %-7s %8s  %s' % ('t', 'type', 'метка', 'откл,мс', 'прим.'))
    for q, ev in events:
        if q['type'] in SWEEP_END | SWEEP_PEAK:
            t_s, x, g, p = ev[0]
            xa = np.abs(np.asarray(x)).max(axis=0)
            if q['type'] in SWEEP_END:
                last = np.nonzero(xa > xa.max() * 10 ** (-50 / 20))[0][-1]
                got, want, kind = t_s + (last + 1) / SR, q['t'] + float(q['dur']), 'конец'
            else:
                # согласованный фильтр: сдвиг мощности события относительно формы огибающей (пик на шумовом
                # сигнале по argmax прыгает на ±15 мс от случайности, по корреляции — нет)
                pw = (np.asarray(x) ** 2).mean(axis=0); n = len(pw); p = np.arange(n) / max(1, n - 1)
                tpl = (1 - np.abs(2 * p - 1)) ** 5
                L = ns(0.05); pad = np.pad(pw, L)
                lags = np.arange(-L, L + 1)
                cc = [np.dot(pad[L + g:L + g + n], tpl) for g in lags]
                got, want, kind = t_s + ((n - 1) / 2 + lags[int(np.argmax(cc))]) / SR, q['t'] + float(q['dur']) / 2, 'пик'
            devs = [(got - want) * 1000]
            note = '%s %.4f (цель %.4f), по сигналу события' % (kind, got, want)
        else:
            subs = sorted({round(t, 6): x for t, x, g, p in ev}.items())
            ts = [t for t, _ in subs]
            step = np.diff(ts).min() if len(ts) > 1 else 1.0
            win = min(0.04, step / 2 * 0.9)
            devs = [(attack_time(sm, c.N, t, win, event_band(x)) - t) * 1000 for t, x in subs if t < c.end]
            kind = 'атака'
            note = ('%d атак: ' % len(devs) + ' '.join('%+.0f' % d for d in devs)) if len(devs) > 1 else 'по стему sfx'
        if not devs: continue
        mx = max(devs, key=abs); alld += [abs(d) for d in devs]
        P('%-7.3f %-7s %-7s %+8.1f  %s' % (q['t'], q['type'], kind, mx, note))
        if abs(mx) > 15: bad.append((q['t'], q['type'], round(mx, 1)))
    if alld:
        P('ИТОГО по %d точкам: макс |откл| = %.1f мс, среднее = %.1f мс; > 15 мс: %s' % (
            len(alld), max(alld), np.mean(alld), bad if bad else 'нет'))
    return bad


# ============================ главный поток ============================
def main():
    ap = argparse.ArgumentParser(description='Музыкальная подложка и эффекты по timeline.json -> mix.wav + stems/ + отчёт.')
    ap.add_argument('--timeline', default='timeline.json', help='таймлайн ролика (по умолчанию timeline.json)')
    ap.add_argument('--out', default='mix.wav', help='итоговый файл (48 кГц, 24 бит, стерео)')
    ap.add_argument('--stems', default='stems', help='папка стемов drums/bass/music/sfx (float32, до лимитера)')
    ap.add_argument('--key', default=None, help='тональность: Am, C, F#m… (по умолчанию из таймлайна, иначе Am)')
    ap.add_argument('--seed', type=int, default=1, help='зерно случайности; один seed — один и тот же файл')
    ap.add_argument('--lufs', type=float, default=-14.0, help='целевая интегральная громкость, LUFS')
    ap.add_argument('--style', choices=('drive', 'calm'), default='drive',
                    help='drive — бочка на каждую долю; calm — спокойнее, бочка реже, без клэпа')
    args = ap.parse_args()

    try:
        tl = json.load(open(args.timeline, encoding='utf-8'))
    except (OSError, ValueError) as e:
        sys.exit(f'ошибка: не прочитан таймлайн {args.timeline}: {e}')
    if 'end' not in tl:
        sys.exit('ошибка: в таймлайне нет поля end (длина ролика, с)')
    key = args.key or tl.get('key') or 'Am'
    c = build_context(tl, key, args.style, args.seed)

    drums, kicks = render_drums(c)
    bass, bass_exempt = render_bass(c)
    music = render_music(c)
    deep = c.style == 'calm'
    bass = bass * duck_curve(c, kicks, 0.6 if deep else 0.9, 0.23) + bass_exempt
    music = music * duck_curve(c, kicks, 0.25 if deep else 0.45, 0.26) * 10 ** (6 / 20)
    sfx, events = render_sfx(c)

    ir = make_ir(c); keep = gap_masks(c)
    drums = space(c, drums, 0.10, ir, keep)
    bass = space(c, bass, 0.0, ir, keep)
    music = space(c, music, 0.30, ir, keep)
    sfx = sfx + np.array([oaconvolve(hp(sfx[ch], 250) * 0.28, ir[ch])[:c.N] for ch in range(2)])
    stems = {k: mono_low(x) for k, x in (('drums', drums), ('bass', bass), ('music', music), ('sfx', sfx))}
    for k in ('drums', 'bass', 'music'):          # хвост фильтра не должен протекать в gap
        stems[k] *= np.where(keep > 0, 1.0, 0.0) if c.sec['gap'] else 1.0

    pre = hp(sum(stems.values()), 24, 4)
    fade = min(ns(0.5), c.N // 10)
    if fade:
        fcurve = np.cos(np.linspace(0, np.pi / 2, fade)) ** 2
        pre[:, -fade:] *= fcurve
        for k in stems: stems[k][:, -fade:] *= fcurve
    y, gain, gr, ceil = master(pre, args.lufs)
    y[:, -1] = 0.0

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True); os.makedirs(args.stems, exist_ok=True)
    sf.write(args.out, y.T, SR, subtype='PCM_24')
    for k, x in stems.items():
        write_float_wav(os.path.join(args.stems, k + '.wav'), x * gain)

    # ---------- отчёт ----------
    R = []
    def P(*a):
        s = ' '.join(str(v) for v in a); print(s, flush=True); R.append(s)
    P('audio_bed.py — отчёт')
    P('timeline: %s  end=%.3f с, bpm=%g (доля %.3f с, такт %.3f с), cues=%d, style=%s, seed=%d, key=%s' % (
        os.path.basename(args.timeline), c.end, c.bpm, c.beat, c.bar, len(c.cues), c.style, c.seed, c.key_name))
    P('секции:', ', '.join('%s %.3f–%.3f' % (k, a, b) for k in SECTION_KEYS for a, b in c.sec[k]))
    P('аккорды:', ' | '.join('%.2f–%.2f %s' % (a, b, ch[2]) for a, b, s, ch in c.segs))
    P('')
    P('== 1. Длина ==')
    info = sf.info(args.out)
    P('mix: frames=%d (ожидается %d), %d Гц, %d кан., %s' % (info.frames, c.N, info.samplerate, info.channels, info.subtype))
    for k in stems:
        P('  stem %-5s frames=%d' % (k, sf.info(os.path.join(args.stems, k + '.wav')).frames))
    P('')
    P('== 2. Громкость ==')
    P('свой замер: I=%.2f LUFS (цель %.1f), TP=%.2f dBTP, общий gain %.2f дБ, потолок лимитера %.2f dBTP' % (
        lufs(y), args.lufs, true_peak_db(y), 20 * np.log10(gain), ceil))
    P('ffmpeg ebur128: ' + ffmpeg_ebur128(args.out))
    grdb = 20 * np.log10(gr + EPS)
    P('лимитер: макс. подавление %.1f дБ @ %.3f с; время с подавлением >1 дБ: %.1f%%' % (
        -grdb.min(), grdb.argmin() / SR, 100 * np.mean(grdb < -1)))
    for k, x in stems.items():
        P('  %-5s %.1f LUFS, пик %.1f dBFS' % (k, lufs(x * gain), 20 * np.log10(np.abs(x * gain).max() + EPS)))
    P('')
    P('== 3. Синхрон эффектов (атаки — детектор онсетов по стему sfx; riser/swell/whoosh — по сигналу события) ==')
    sync_report(c, stems['sfx'] * gain, events, P)
    P('')
    P('== 4. Тишина музыки в gap ==')
    if not c.sec['gap']: P('  gap не задан')
    for a, b in c.sec['gap']:
        x = (stems['drums'] + stems['bass'] + stems['music'])[:, ns(a):ns(b)] * gain
        P('  %.3f–%.3f: музыка RMS %.1f dBFS, пик %.1f dBFS' % (
            a, b, 20 * np.log10(np.sqrt((x ** 2).mean()) + EPS), 20 * np.log10(np.abs(x).max() + EPS)))
    x = y[:, -ns(0.01):]
    P('  хвост mix, последние 10 мс: RMS %.1f dBFS' % (20 * np.log10(np.sqrt((x ** 2).mean()) + EPS)))
    rep = os.path.join(out_dir, 'audio_report.txt')
    open(rep, 'w', encoding='utf-8').write('\n'.join(R) + '\n')
    print('отчёт:', rep)


if __name__ == '__main__':
    main()
