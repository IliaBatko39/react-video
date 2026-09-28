#!/usr/bin/env python3
"""Голос диктора поверх подложки из audio_bed.py (numpy + scipy + soundfile, ffmpeg в PATH).

  python3 vo_mix.py plan.json [--dry-run]

План (JSON, пути — относительно файла плана):
  timeline           — тот же timeline.json, что у audio_bed.py (нужен end)
  bed.stems          — папка стемов audio_bed.py; bed.music — стемы, которые приседают на duck_db,
                       bed.sfx — стемы, которые приседают на duck_sfx_db
  phrases[]          — t (с, где начинается голос), take (файл дубля), span [a, b] (голос в секундах дубля),
                       text (для отчёта); по желанию duck_db, duck_sfx_db — свои для фразы
  voice_hp_hz, duck_db, duck_sfx_db, voice_over_bed_db, max_tempo, out, lufs; last_end — докуда может
                       звучать последняя фраза (по умолчанию end − 0,25 с)

Фраза не успевает до следующей (зазор 60 мс) — ускоряется ffmpeg atempo (тон не меняется), но не больше
max_tempo; иначе ошибка. Голос: срез низа, компрессия 3:1, мягкие края. Подложка приседает под голос
(атака ~60 мс, отпускание ~250 мс). Голос встаёт на voice_over_bed_db над присевшей подложкой
(K-взвешенный RMS в окнах фраз). Мастер: lufs (по умолчанию −14), true peak <= −1 dBTP, длина ровно по end.
Выход рядом с out: vo_mix.wav (24 бит), vo_voice.wav (голос, float32, до лимитера), vo_report.txt.
--dry-run — только проверка плана и таблица «фраза → окно → нужен ли atempo».
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np
import soundfile as sf
from scipy.io import wavfile
from scipy.ndimage import minimum_filter1d, uniform_filter1d
from scipy.signal import butter, lfilter, resample_poly, sosfilt

SR = 48000
EPS = 1e-12
PRE, TAIL = 0.03, 0.08        # запас перед голосом и после него при вырезке из дубля, с
MIN_GAP = 0.06                # минимальный зазор до следующей фразы, с
RIDE_DB = 6.0                 # насколько можно подстроить громкость отдельной фразы к цели, дБ
DEFAULTS = {'voice_hp_hz': 90, 'duck_db': -7, 'duck_sfx_db': -3, 'voice_over_bed_db': 9,
            'max_tempo': 1.12, 'out': 'vo_mix.wav', 'lufs': -14}


def ns(sec): return int(round(sec * SR))


def fail(msg):
    sys.exit('ошибка: ' + msg)


# ============================ ffmpeg ============================
def ffmpeg(args, data=None):
    try:
        r = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', *args], input=data,
                           capture_output=True)
    except FileNotFoundError:
        fail('ffmpeg не найден в PATH')
    if r.returncode:
        fail('ffmpeg: ' + r.stderr.decode('utf-8', 'replace').strip()[:400])
    return r.stdout


def read_mono(path):
    """любой аудиофайл -> моно float64, 48 кГц"""
    raw = ffmpeg(['-i', path, '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'])
    return np.frombuffer(raw, np.float32).astype(np.float64)


def atempo(x, tempo):
    """ускорение без смены тона (ffmpeg atempo, 0.5…2.0)"""
    raw = ffmpeg(['-f', 'f32le', '-ar', str(SR), '-ac', '1', '-i', '-', '-af', f'atempo={tempo:.5f}',
                  '-f', 'f32le', '-'], np.asarray(x, np.float32).tobytes())
    return np.frombuffer(raw, np.float32).astype(np.float64)


def probe_duration(path):
    try:
        r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
                           capture_output=True, text=True)
        return float(r.stdout.strip())
    except (FileNotFoundError, ValueError):
        return None


# ============================ план ============================
def load_plan(path):
    try:
        plan = json.load(open(path, encoding='utf-8'))
    except (OSError, ValueError) as e:
        fail(f'не прочитан план {path}: {e}')
    base = os.path.dirname(os.path.abspath(path))
    P = dict(DEFAULTS, **plan)
    P['base'] = base
    rel = lambda p: p if os.path.isabs(p) else os.path.join(base, p)
    P['timeline_path'] = rel(plan.get('timeline', 'timeline.json'))
    try:
        tl = json.load(open(P['timeline_path'], encoding='utf-8'))
    except (OSError, ValueError) as e:
        fail(f'не прочитан таймлайн {P["timeline_path"]}: {e}')
    if 'end' not in tl: fail('в таймлайне нет end')
    P['end'] = float(tl['end']); P['N'] = ns(P['end'])
    bed = plan.get('bed', {})
    P['stems_dir'] = rel(bed.get('stems', 'stems'))
    P['bed_music'] = bed.get('music', ['drums', 'bass', 'music'])
    P['bed_sfx'] = bed.get('sfx', ['sfx'])
    P['out_path'] = rel(P['out'])
    P['last_end'] = float(plan.get('last_end', P['end'] - 0.25))
    ph = plan.get('phrases') or fail('в плане нет phrases')
    errs = []
    for k, p in enumerate(ph):
        tag = f'фраза {k + 1}'
        try:
            p['t'] = float(p['t']); a, b = map(float, p['span']); p['span'] = [a, b]
        except (KeyError, TypeError, ValueError):
            errs.append(f'{tag}: нужны t (с) и span [a, b] (с)'); continue
        if b <= a: errs.append(f'{tag}: span {p["span"]} — конец не больше начала')
        if not 0 <= p['t'] < P['end']: errs.append(f'{tag}: t={p["t"]} вне ролика 0…{P["end"]}')
        if k and p['t'] <= ph[k - 1].get('t', -1): errs.append(f'{tag}: t должны расти по порядку фраз')
        p['take_path'] = rel(p.get('take', ''))
        if not os.path.isfile(p['take_path']): errs.append(f'{tag}: нет файла дубля {p.get("take")}')
        p.setdefault('text', '')
    for s in P['bed_music'] + P['bed_sfx']:
        f = os.path.join(P['stems_dir'], s + '.wav')
        if not os.path.isfile(f): errs.append(f'нет стема {f} (сначала audio_bed.py)')
        elif sf.info(f).frames != P['N']:
            errs.append(f'стем {s}.wav: {sf.info(f).frames} сэмплов, а по таймлайну {P["N"]} — пересобери audio_bed.py')
    if errs: fail('план не прошёл проверку:\n  ' + '\n  '.join(errs))
    P['phrases'] = ph
    return P


def fit_phrases(P):
    """окно каждой фразы и нужный темп; фразы, которым не хватает max_tempo — в ошибки"""
    ph = P['phrases']; rows = []; errs = []
    for k, p in enumerate(ph):
        lim = ph[k + 1]['t'] - MIN_GAP if k + 1 < len(ph) else P['last_end']
        d = p['span'][1] - p['span'][0]
        room = lim - p['t']
        need = d / room if room > 0 else float('inf')
        tempo = max(float(p.get('tempo', 1.0)), need, 1.0)
        rows.append(dict(k=k, t=p['t'], lim=lim, room=room, dur=d, tempo=tempo))
        if tempo > P['max_tempo'] + 1e-9:
            errs.append('фраза %d «%s»: голос %.2f с, окно %.2f…%.2f (%.2f с) — нужен темп ×%.2f, а max_tempo ×%.2f. '
                        'Сократи фразу или раздвинь время (сдвинь t следующей фразы / удлини сцену).' % (
                            k + 1, p['text'], d, p['t'], lim, max(room, 0), tempo, P['max_tempo']))
    return rows, errs


def print_table(P, rows):
    print('%3s %6s %14s %7s %7s %7s  %s' % ('№', 't', 'окно', 'голос', 'темп', 'atempo', 'текст'))
    for r in rows:
        p = P['phrases'][r['k']]
        flag = 'нет' if r['tempo'] <= 1.0 + 1e-9 else ('да' if r['tempo'] <= P['max_tempo'] + 1e-9 else 'НЕ ВЛЕЗАЕТ')
        print('%3d %6.2f %6.2f…%6.2f %6.2fс %6.3f  %-6s  %s' % (
            r['k'] + 1, r['t'], r['t'], r['lim'], r['dur'], r['tempo'], flag, p['text']))


# ============================ голос ============================
def cut(x, a, b):
    """голос a…b (с) из дубля с запасом и мягкими краями (12 мс)"""
    a0, b0 = max(0.0, a - PRE), min(len(x) / SR, b + TAIL)
    seg = x[ns(a0):ns(b0)].copy()
    f = min(ns(0.012), len(seg) // 2)
    if f:
        seg[:f] *= np.linspace(0, 1, f); seg[-f:] *= np.linspace(1, 0, f)
    return seg, a - a0


def compress(v, ratio=3.0, below_db=8.0):
    """компрессор по огибающей 1 мс: порог на below_db ниже громких мест голоса, атака 5 мс, отпускание 80 мс"""
    n = len(v); blk = SR // 1000; nb = n // blk
    if nb == 0: return v
    lvl = 20 * np.log10(np.sqrt(np.mean(v[:nb * blk].reshape(nb, blk) ** 2, axis=1)) + 1e-9)
    loud = lvl[lvl > lvl.max() - 30]
    thr = np.percentile(loud, 90) - below_db
    aa, ar = np.exp(-1 / 5), np.exp(-1 / 80)
    env = np.empty(nb); cur = -120.0
    for i, x in enumerate(lvl.tolist()):
        c = aa if x > cur else ar
        cur = c * cur + (1 - c) * x; env[i] = cur
    gr = np.minimum(0.0, (thr - env) * (1 - 1 / ratio))
    return v * np.interp(np.arange(n), np.arange(nb) * blk + blk / 2, 10 ** (gr / 20))


def duck_env(P, spans, key, N):
    """огибающая приседания в дБ: цель на окнах фраз, атака ~60 мс, отпускание ~250 мс (шаг 1 мс)"""
    nb = N // 48 + 1
    tgt = np.zeros(nb)
    for (a, b), p in zip(spans, P['phrases']):
        d = float(p.get(key, P[key]))
        i0, i1 = max(0, int((a - 0.10) * 1000)), min(nb, int((b + 0.06) * 1000))
        tgt[i0:i1] = np.minimum(tgt[i0:i1], d)
    da, dr = np.exp(-1 / 60), np.exp(-1 / 250)
    out = np.empty(nb); cur = 0.0
    for i, x in enumerate(tgt.tolist()):
        c = da if x < cur else dr
        cur = c * cur + (1 - c) * x; out[i] = cur
    return np.interp(np.arange(N), np.arange(nb) * 48 + 24, out)


# ============================ мастер (как в audio_bed.py) ============================
KB1, KA1 = [1.53512485958697, -2.69169618940638, 1.19839281085285], [1.0, -1.69065929318241, 0.73248077421585]
KB2, KA2 = [1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621]


def kweight(x): return lfilter(KB2, KA2, lfilter(KB1, KA1, x, axis=-1), axis=-1)


def lufs(x):
    """интегральная громкость BS.1770-4: окна 400 мс, гейты −70 и −10"""
    p = (kweight(x) ** 2).sum(axis=0); cs = np.concatenate([[0], np.cumsum(p)])
    b, h = ns(0.4), ns(0.1); st = np.arange(0, len(p) - b + 1, h)
    z = (cs[st + b] - cs[st]) / b
    z = z[-0.691 + 10 * np.log10(z + EPS) > -70]
    if not len(z): return -120.0
    rel = -0.691 + 10 * np.log10(z.mean()) - 10
    z = z[-0.691 + 10 * np.log10(z) > rel]
    return -0.691 + 10 * np.log10(z.mean())


def tp_env(x):
    n = x.shape[1]; up = resample_poly(x, 4, 1, axis=1)
    a = np.abs(up).max(axis=0)[:4 * n].reshape(-1, 4).max(axis=1)
    return np.maximum(a, np.abs(x).max(axis=0))


def true_peak_db(x): return 20 * np.log10(tp_env(x).max() + EPS)


def limiter(x, ceil_db, look=0.004, rel=0.09):
    c = 10 ** (ceil_db / 20); n = x.shape[1]
    g = np.minimum(1.0, c / np.maximum(tp_env(x), EPS)); L = ns(look)
    g2 = uniform_filter1d(minimum_filter1d(g, 2 * L + 1), L + 1)
    a = 1 - np.exp(-1 / (rel * SR)); out = np.empty(n); cur = 1.0
    for i, v in enumerate(g2.tolist()):
        cur = v if v < cur else cur + (v - cur) * a
        out[i] = cur
    return x * out


def master(pre, target):
    gain, ceil = 10 ** ((target - lufs(pre)) / 20), -1.25
    for _ in range(8):
        y = limiter(pre * gain, ceil)
        L, tp = lufs(y), true_peak_db(y)
        if abs(L - target) < 0.05 and tp <= -1.0: break
        gain *= 10 ** ((target - L) / 20)
        if tp > -1.05: ceil -= (tp + 1.05) + 0.05
    return y, gain


def kpow_db(x, mask):
    """K-взвешенная средняя мощность (дБ) на отсчётах mask; x (ch, n) — каналы суммируются, как в BS.1770"""
    y = kweight(np.atleast_2d(x))
    return 10 * np.log10((y[:, mask] ** 2).sum(axis=0).mean() + EPS)


# ============================ главный поток ============================
def main():
    ap = argparse.ArgumentParser(description='Голос по плану поверх стемов audio_bed.py -> vo_mix.wav + отчёт.')
    ap.add_argument('plan', help='план фраз (JSON)')
    ap.add_argument('--dry-run', action='store_true', help='только проверить план и показать окна фраз')
    args = ap.parse_args()

    P = load_plan(args.plan)
    rows, errs = fit_phrases(P)
    if args.dry_run:
        for p in P['phrases']:
            d = probe_duration(p['take_path'])
            if d is not None and p['span'][1] > d + 0.01:
                errs.append(f'«{p["text"]}»: span {p["span"]} за концом дубля ({d:.2f} с)')
        print('план %s: %d фраз, ролик %.2f с, max_tempo ×%.2f' % (args.plan, len(rows), P['end'], P['max_tempo']))
        print_table(P, rows)
        if errs: fail('\n  ' + '\n  '.join(errs))
        print('план в порядке')
        return
    if errs: fail('\n  ' + '\n  '.join(errs))

    N = P['N']; R = []
    def rep(*a):
        s = ' '.join(str(v) for v in a); print(s, flush=True); R.append(s)

    # ---------- 1. фразы на таймлайн ----------
    takes = {}; voice = np.zeros(N); spans = []
    for r in rows:
        p = P['phrases'][r['k']]
        if p['take_path'] not in takes: takes[p['take_path']] = read_mono(p['take_path'])
        x = takes[p['take_path']]
        if p['span'][1] > len(x) / SR + 0.01:
            fail(f'«{p["text"]}»: span {p["span"]} за концом дубля ({len(x) / SR:.2f} с)')
        seg, pre = cut(x, *p['span'])
        if r['tempo'] > 1.0 + 1e-9:
            seg = atempo(seg, r['tempo']); pre /= r['tempo']
        dur = (p['span'][1] - p['span'][0]) / r['tempo']
        a = ns(p['t'] - pre)
        if a < 0: seg = seg[-a:]; a = 0
        seg = seg[:N - a]
        voice[a:a + len(seg)] += seg
        spans.append((p['t'], p['t'] + dur))
        r['dur_out'] = dur

    # ---------- 2. голос: срез низа, компрессия ----------
    voice = sosfilt(butter(2, float(P['voice_hp_hz']), 'hp', fs=SR, output='sos'), voice)
    voice = compress(voice, 3.0)

    # ---------- 3. подложка и приседание ----------
    rd = lambda s: sf.read(os.path.join(P['stems_dir'], s + '.wav'), dtype='float64', always_2d=True)[0].T
    bed = sum(rd(s) for s in P['bed_music']) if P['bed_music'] else np.zeros((2, N))
    sfx = sum(rd(s) for s in P['bed_sfx']) if P['bed_sfx'] else np.zeros((2, N))
    if bed.shape[0] == 1: bed = np.vstack([bed, bed])
    if sfx.shape[0] == 1: sfx = np.vstack([sfx, sfx])
    bed_d = bed * 10 ** (duck_env(P, spans, 'duck_db', N) / 20)
    sfx_d = sfx * 10 ** (duck_env(P, spans, 'duck_sfx_db', N) / 20)
    under = bed_d + sfx_d

    # ---------- 4. уровень голоса: общий, затем подстройка фраз в пределах ±RIDE_DB ----------
    masks = []
    for a, b in spans:
        m = np.zeros(N, bool); m[ns(a):min(N, ns(b))] = True; masks.append(m)
    allm = np.any(masks, axis=0)
    target = float(P['voice_over_bed_db'])
    vst = lambda v: np.vstack([v, v])            # голос в центре: в оба канала, мощность — как у BS.1770
    voice *= 10 ** ((kpow_db(under, allm) + target - kpow_db(vst(voice), allm)) / 20)
    gains = np.ones(N); fr = ns(0.03)
    for (a, b), m in zip(spans, masks):
        corr = np.clip(kpow_db(under, m) + target - kpow_db(vst(voice), m), -RIDE_DB, RIDE_DB)
        i0, i1 = max(0, ns(a - PRE - 0.02)), min(N, ns(b + TAIL + 0.02))
        g = np.full(i1 - i0, 10 ** (corr / 20))
        gains[i0:i1] = g
    gains = uniform_filter1d(gains, fr)          # без ступенек между фразами
    voice *= gains
    v2 = np.vstack([voice, voice])
    excess = [kpow_db(v2, m) - kpow_db(under, m) for m in masks]

    # ---------- 5. мастер ----------
    pre = sosfilt(butter(4, 24, 'hp', fs=SR, output='sos'), under + v2, axis=-1)
    y, gain = master(pre, float(P['lufs']))
    y[:, -1] = 0.0
    out = P['out_path']; odir = os.path.dirname(out)
    os.makedirs(odir, exist_ok=True)
    sf.write(out, y.T, SR, subtype='PCM_24')
    vpath = os.path.join(odir, 'vo_voice.wav')
    wavfile.write(vpath, SR, (voice * gain).astype(np.float32))

    # ---------- 6. отчёт ----------
    rep('vo_mix.py — отчёт по плану %s' % os.path.basename(args.plan))
    rep('ролик %.3f с, стемы %s (приседают на %s дБ: %s; на %s дБ: %s)' % (
        P['end'], os.path.relpath(P['stems_dir'], P['base']), P['duck_db'], '+'.join(P['bed_music']),
        P['duck_sfx_db'], '+'.join(P['bed_sfx'])))
    rep('')
    rep('%3s %6s %6s %6s %6s %9s  %s' % ('№', 't', 'конец', 'длина', 'темп', 'голос/подл', 'текст'))
    for r, (a, b), e in zip(rows, spans, excess):
        rep('%3d %6.2f %6.2f %5.2fс ×%.3f %+8.1f дБ  %s' % (r['k'] + 1, a, b, b - a, r['tempo'], e, P['phrases'][r['k']]['text']))
    rep('превышение голоса над присевшей подложкой (K-взвеш. RMS в окнах фраз): цель %+.1f дБ, по фразам %+.1f…%+.1f, среднее %+.1f' % (
        target, min(excess), max(excess), float(np.mean(excess))))
    rep('')
    info = sf.info(out)
    rep('мастер: I=%.2f LUFS (цель %.1f), TP=%.2f dBTP, frames=%d (ожидается %d), %d Гц, %s' % (
        lufs(y), float(P['lufs']), true_peak_db(y), info.frames, N, info.samplerate, info.subtype))
    eb = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', out, '-af', 'ebur128=peak=true', '-f', 'null', '-'],
                        capture_output=True, text=True).stderr
    rep('ffmpeg ebur128: ' + ' | '.join(l.strip() for l in eb[eb.rfind('Summary:'):].splitlines()[1:]
                                        if l.strip().startswith(('I:', 'LRA:', 'Peak:'))))
    rep('файлы: %s, %s' % (out, vpath))
    open(os.path.join(odir, 'vo_report.txt'), 'w', encoding='utf-8').write('\n'.join(R) + '\n')


if __name__ == '__main__':
    main()
