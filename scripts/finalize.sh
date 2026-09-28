#!/usr/bin/env bash
# Сборка выдачи ролика.
#   finalize.sh video_raw.mp4 [mix.wav] out/name
# → out/name.mp4        видео как есть (-c:v copy) + звук AAC 256k 48 кГц;
#   out/name_light.mp4  лёгкая копия (crf 20, потолок 5,6 Мбит/с — с запасом до 6: VBV на коротком ролике перебирает) — для Telegram-бота с лимитом 50 МБ и чатов;
#   out/name.jpg        постер = кадр 0 (render.py video --poster T кладёт туда нужный момент);
#   в конце — ffprobe и громкость ebur128 (I, LRA, Peak).
# Звук: alimiter −2 dBFS ПЕРЕД AAC — кодер добавляет к пику до +0,5 дБ, так true peak остаётся ≤ −1 dBTP.
# Длина звука подгоняется к видео: короткий дополняется тишиной, длинный обрезается.
set -euo pipefail

usage() { echo "использование: $0 video_raw.mp4 [mix.wav] out/name" >&2; exit 2; }
[ $# -eq 2 ] || [ $# -eq 3 ] || usage
VIDEO=$1
if [ $# -eq 3 ]; then AUDIO=$2; OUT=$3; else AUDIO=""; OUT=$2; fi
[ -f "$VIDEO" ] || { echo "ошибка: нет файла $VIDEO" >&2; exit 2; }
[ -z "$AUDIO" ] || [ -f "$AUDIO" ] || { echo "ошибка: нет файла $AUDIO" >&2; exit 2; }
OUT=${OUT%.mp4}
mkdir -p "$(dirname "$OUT")"

DUR=$(ffprobe -v error -select_streams v:0 -show_entries format=duration -of csv=p=0 "$VIDEO")

if [ -n "$AUDIO" ]; then
  ffmpeg -y -loglevel error -i "$VIDEO" -i "$AUDIO" -map 0:v:0 -map 1:a:0 -c:v copy \
    -af "apad,alimiter=limit=0.79:attack=1:release=60:level=false" \
    -c:a aac -b:a 256k -ar 48000 -t "$DUR" -movflags +faststart "$OUT.mp4"
  ACOPY=(-c:a copy)
else
  ffmpeg -y -loglevel error -i "$VIDEO" -map 0:v:0 -c:v copy -movflags +faststart "$OUT.mp4"
  ACOPY=()
fi
ffmpeg -y -loglevel error -i "$OUT.mp4" -map 0 -c:v libx264 -preset slow -crf 20 -maxrate 5600k -bufsize 8M \
  -pix_fmt yuv420p ${ACOPY[@]+"${ACOPY[@]}"} -movflags +faststart "${OUT}_light.mp4"
ffmpeg -y -loglevel error -i "$OUT.mp4" -frames:v 1 -q:v 2 "$OUT.jpg"

for f in "$OUT.mp4" "${OUT}_light.mp4"; do
  echo "== $f"
  ffprobe -v error -show_entries stream=codec_type,codec_name,width,height,r_frame_rate,pix_fmt,nb_frames,sample_rate,bit_rate \
    -show_entries format=duration,size,bit_rate -of compact "$f"
done
ls -l "$OUT.mp4" "${OUT}_light.mp4" "$OUT.jpg"
if [ -n "$AUDIO" ]; then
  echo "== громкость $OUT.mp4"
  ffmpeg -hide_banner -nostats -i "$OUT.mp4" -map 0:a:0 -af ebur128=peak=true -f null - 2>&1 \
    | grep -E '^\s+(I|LRA|Peak):' | tail -3
fi
