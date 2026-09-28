#!/usr/bin/env python3
"""Вставка перерендеренных кусков в готовое видео без полного рендера.

  splice.py base.mp4 out.mp4 part.mp4:A:B [part2.mp4:C:D ...] [--fps 30]

Кусок делается так: render.py video part.mp4 --from A --to B [--blur N] [--remap ...] — это кадры
round(A·fps)…round(B·fps)−1. Всё видео перекодируется один раз (x264 slow, crf 15 — на ступень лучше
рендера, чтобы второе поколение сжатия не было заметно). Число кадров сверяется на входе и выходе.
"""
import argparse
import subprocess
import sys


def count_frames(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
                        '-show_entries', 'stream=nb_read_frames', '-of', 'csv=p=0', path],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip().isdigit():
        sys.exit('ошибка: не прочитать %s: %s' % (path, r.stderr.strip() or r.stdout.strip()))
    return int(r.stdout.strip())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('base', help='исходное видео')
    ap.add_argument('out', help='выходное видео')
    ap.add_argument('parts', nargs='+', help='куски в виде файл.mp4:с:по (секунды)')
    ap.add_argument('--fps', type=float, default=30, help='кадров в секунду (по умолчанию 30)')
    ap.add_argument('--crf', type=int, default=15, help='качество x264 при перекодировании (по умолчанию 15)')
    a = ap.parse_args()
    fps = a.fps
    parts = []
    for s in a.parts:
        try:
            f, t0, t1 = s.rsplit(':', 2)
            parts.append((f, int(round(float(t0) * fps)), int(round(float(t1) * fps))))
        except ValueError:
            sys.exit('ошибка: кусок пишется как файл.mp4:с:по, получено %r' % s)
    parts.sort(key=lambda p: p[1])
    n = count_frames(a.base)
    inputs, chains, labels, pos = ['-i', a.base], [], [], 0
    for k, (f, i0, i1) in enumerate(parts, 1):
        m = count_frames(f)
        if m != i1 - i0:
            sys.exit('ошибка: %s — %d кадров, а отрезок требует %d (%d…%d)' % (f, m, i1 - i0, i0, i1 - 1))
        if i0 < pos:
            sys.exit('ошибка: куски пересекаются (кадр %d)' % i0)
        if i1 > n:
            sys.exit('ошибка: кусок %s выходит за конец видео (%d > %d кадров)' % (f, i1, n))
        inputs += ['-i', f]
        if i0 > pos:
            chains.append('[0:v]trim=start_frame=%d:end_frame=%d,setpts=PTS-STARTPTS[b%d]' % (pos, i0, k))
            labels.append('[b%d]' % k)
        chains.append('[%d:v]setpts=PTS-STARTPTS[p%d]' % (k, k))
        labels.append('[p%d]' % k)
        pos = i1
    if pos < n:
        chains.append('[0:v]trim=start_frame=%d,setpts=PTS-STARTPTS[tail]' % pos)
        labels.append('[tail]')
    fc = ';'.join(chains) + ';' + ''.join(labels) + 'concat=n=%d:v=1:a=0[v]' % len(labels)
    fps_s = '%g' % fps
    r = subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', *inputs, '-filter_complex', fc, '-map', '[v]',
                        '-c:v', 'libx264', '-preset', 'slow', '-crf', str(a.crf), '-pix_fmt', 'yuv420p', '-r', fps_s,
                        '-movflags', '+faststart', a.out])
    if r.returncode != 0:
        sys.exit('ошибка: ffmpeg не собрал %s' % a.out)
    m = count_frames(a.out)
    if m != n:
        sys.exit('ошибка: на выходе %d кадров, было %d' % (m, n))
    print('splice ok: %s — %d кадров; заменены кадры %s' % (
        a.out, m, ', '.join('%d–%d' % (i0, i1 - 1) for _, i0, i1 in parts)))


if __name__ == '__main__':
    main()
