# Шаблон: HTML без сборки

Демо 12 с, 1080×1920, 30 к/с, 120 BPM, склейки на доли. Скрипты лежат в `scripts/` папки скилла.

| Время | Сцена |
|---|---|
| 0–2 с | кинетический заголовок на canvas, по слову на долю |
| 2–5 с | чат Claude Code: запрос печатается по буквам → рендер по кадрам → готовый `promo.mp4` |
| 5–7,5 с | three.js с тенями, SwiftShader — «3D на сервере без видеокарты» |
| 7,5–9,5 с | DOM и CSS @keyframes, перемотанные на `t`; 9,25–9,5 — стоп-кадр с притемнением (пауза перед ударом) |
| 9,5–12 с | финальная карточка: контурный текст, адрес репозитория |

Время сцен main.js берёт из `timeline.json` (`scenes`, `music.gap`) — тот же файл читает звук.

```bash
cp -r templates/html ./video                      # своя копия
python3 scripts/check_env.py --gl                 # окружение
python3 scripts/layout_check.py --dir video       # безопасная зона и скорость чтения
python3 scripts/render.py stills 1,3.5,6.2,8.5,10.8 --dir video
python3 scripts/render.py video raw.mp4 --dir video --blur 4 --poster 10.8
```

- `timeline.json` — длительность, сцены, доли и звуковые события; `js/main.js` — сцены, `window.render(t, gt)`.
- `js/util.js` — изинги, `hash`, `rng`, `frameOf`, `shake`, `fitFont`, зерно; `js/outline.js` — контур без линий внутри букв; `js/three-scene.js` — 3D-сцена по местному времени.
- three.js грузится с jsDelivr (точная версия в importmap `index.html`) — нужен интернет. Без сети скачайте `three.module.js` и `three.core.js` той же версии в `lib/` и поправьте importmap.
- Шрифты Manrope и Unbounded — OFL 1.1, лицензии в `fonts/`.
