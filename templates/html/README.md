# Шаблон: HTML без сборки

Демо 8 с, 1080×1920, 30 к/с, 120 BPM: кинетический заголовок на canvas → three.js с тенями → DOM и CSS-анимации, перемотанные на `t` → контурный текст. Скрипты лежат в `scripts/` папки скилла.

```bash
cp -r templates/html ./video                      # своя копия
python3 scripts/check_env.py --gl                 # окружение
python3 scripts/layout_check.py --dir video       # безопасная зона и скорость чтения
python3 scripts/render.py stills 0.5,3.2,5.5,7.6 --dir video
python3 scripts/render.py video raw.mp4 --dir video --blur 4 --poster 7.2
```

- `timeline.json` — длительность, сцены, доли и звуковые события; `js/main.js` — сцены, `window.render(t, gt)`.
- `js/util.js` — изинги, `hash`, `rng`, `frameOf`, `shake`, `fitFont`, зерно; `js/outline.js` — контур без линий внутри букв.
- three.js грузится с jsDelivr (точная версия в importmap `index.html`) — нужен интернет. Без сети скачайте `three.module.js` и `three.core.js` той же версии в `lib/` и поправьте importmap.
- Шрифты Manrope и Unbounded — OFL 1.1, лицензии в `fonts/`.
