# react-video — ролики из веб-страниц для Claude Code

<p align="center"><img src="docs/demo.gif" width="300" alt="Демо-ролик из шаблона скилла: кинетический заголовок, запрос в чате Claude Code и готовый mp4, 3D-сцена, CSS-анимация, финальная карточка с адресом репозитория"></p>

Скилл для [Claude Code](https://claude.com/claude-code). Просите «сделай промо-ролик по этой презентации», и Claude собирает сцену на React или HTML, рендерит её покадрово в headless Chromium, синтезирует музыку и эффекты под ту же сетку времени и отдаёт готовый mp4 для Reels, Shorts и Telegram.

Без съёмки, без облачных рендеров и без платных фреймворков: Playwright, ffmpeg и numpy.

## Что умеет

- промо и объясняющие ролики с диктором, шоурилы под музыку, ролики по презентации или лендингу;
- 3D на сервере без видеокарты: three.js через SwiftShader;
- размытие движения подкадрами — картинка выглядит как из студии, а не как запись экрана;
- музыку и эффекты синтезом по таймлайну, приседание музыки под голос, мастер −14 LUFS;
- проверки до рендера: безопасная зона Reels, скорость чтения, лист кадров;
- правку куска без полного перерендера и версию другой длины без перерисовки сцен.

Главное в скилле — не скрипты, а порядок работы: раскадровка и согласование до рендера, ролик читается без звука, цифры только проверенные, рецензент-придира до показа. Эти правила выросли из реальных роликов для малого бизнеса.

## Установка

Как плагин — в Claude Code:

```
/plugin marketplace add IliaBatko39/react-video
/plugin install react-video@react-video
```

Или вручную, как обычный скилл:

```bash
git clone https://github.com/IliaBatko39/react-video ~/.claude/skills/react-video
```

Зависимости для рендера. Команды работают из любой папки:

```bash
python3 -m pip install "playwright>=1.59" "numpy>=2.2" "pillow>=12.1" "scipy>=1.15" "soundfile>=0.13"
python3 -m playwright install chromium
sudo apt install ffmpeg        # macOS: brew install ffmpeg
```

На Ubuntu 23.04+ и Debian 12 системный pip закрыт (ошибка `externally-managed-environment`). Поставьте пакеты в venv и запускайте Claude Code из него:

```bash
python3 -m venv ~/.venvs/react-video
source ~/.venvs/react-video/bin/activate
python3 -m pip install "playwright>=1.59" "numpy>=2.2" "pillow>=12.1" "scipy>=1.15" "soundfile>=0.13"
python3 -m playwright install chromium
claude
```

Нужны Python 3.10+ и ffmpeg; для React-шаблона — ещё Node.js 20.19+ или 22.12+.

Проверить окружение — вызовите скилл командой в Claude Code:

```
/react-video:react-video проверь окружение
```

При ручной установке команда короче: `/react-video проверь окружение`. Из клона репозитория — `python3 scripts/check_env.py --gl`. Скрипт проверит Python-модули, Chromium, ffmpeg, WebGL и Node и подскажет, чего не хватает. Первым шагом каждого ролика скилл проверяет окружение и сам.

## Как пользоваться

Попросите Claude обычными словами:

- «Сделай 20-секундный ролик по этой презентации, вертикальный»
- «Промо-ролик для лендинга с диктором»
- «Шоурил под музыку по нашим услугам»

Если Claude не подхватил скилл сам, вызовите его явно: `/react-video:react-video` и задача следом (при ручной установке — `/react-video`).

Скилл ведёт по шагам: раскадровка → ваше «ок» → сцена → рендер → звук → проверка → выдача. На выходе — оригинал, лёгкая копия для мессенджеров, постер и лист кадров.

Собрать демо из шаблона руками:

```bash
mkdir -p /tmp/demo && cp -R templates/html/. /tmp/demo/
python3 scripts/render.py video /tmp/demo/raw.mp4 --dir /tmp/demo --blur 4 --poster 10.8
python3 scripts/audio_bed.py --timeline /tmp/demo/timeline.json --out /tmp/demo/mix.wav --stems /tmp/demo/stems
bash scripts/finalize.sh /tmp/demo/raw.mp4 /tmp/demo/mix.wav /tmp/demo/out/demo
```

## Как устроено

```
timeline.json ──► страница: window.render(t) ──► Chromium + Playwright ──► кадры ──► ffmpeg ──► raw.mp4 ─┐
      │                                                                                                  ├─► finalize.sh ──► mp4 + лёгкая копия + постер
      └──────────► audio_bed.py: музыка и эффекты по сетке ──► vo_mix.py: голос ──► mix.wav ───────────────┘
```

- **Кадр — чистая функция времени.** Страница рисует любой момент `t` без часов браузера, поэтому рендер детерминирован, а размытие движения честное.
- **`timeline.json` — одно время на картинку и звук.** Сцены, секции музыки и звуковые события лежат в одном файле: сдвинул удар — он сдвинулся и в кадре, и в звуке.

## Что внутри

| Путь | Что это |
|---|---|
| `SKILL.md` | порядок работы для Claude |
| `reference/` | контракт страницы, приёмы сцены, жанры, звук и голос, проверка и сдача |
| `scripts/render.py` | рендер: стоп-кадры, видео, размытие движения, постер, куски, перекарта времени |
| `scripts/layout_check.py` | безопасная зона и скорость чтения до рендера |
| `scripts/splice.py` | вставка перерендеренного куска в готовое видео |
| `scripts/remap.py` | версия другой длины без перерисовки сцен |
| `scripts/audio_bed.py` | музыка и эффекты синтезом по таймлайну |
| `scripts/vo_mix.py` | голос по плану фраз, приседание музыки, мастер |
| `scripts/finalize.sh` | сборка выдачи и замеры |
| `scripts/sheet.py` | лист кадров |
| `scripts/check_env.py` | проверка окружения |
| `templates/html/` | шаблон без сборки: canvas, DOM, CSS, three.js |
| `templates/react/` | шаблон на React и Vite |

## Благодарности

Идея конвейера «HTML-сцена → Chromium → ffmpeg» — из скилла `/brag-slim` проекта [latent-spaces/brag](https://github.com/latent-spaces/brag). Здесь она выросла в отдельный скилл со своими скриптами, шаблонами и правилами.

## Лицензия

MIT — см. [LICENSE](LICENSE). Шрифты в шаблонах — SIL Open Font License 1.1, файлы лицензий лежат рядом со шрифтами. three.js подключается с CDN, лицензия MIT.

---

## English

**react-video** is a Claude Code skill that turns a web page into a motion video. The scene is built with React or plain HTML, where every frame is a pure function of time (`window.render(t)`). Headless Chromium captures it frame by frame with Playwright, ffmpeg encodes it, and a numpy synth builds music and sound effects on the same timeline. Output: an mp4 for Reels, Shorts or Telegram, a light copy, a poster and a contact sheet. No filming, no cloud rendering, no paid frameworks.

Install as a plugin:

```
/plugin marketplace add IliaBatko39/react-video
/plugin install react-video@react-video
```

Or clone into `~/.claude/skills/react-video`. Then install the dependencies (works from any folder):

```bash
python3 -m pip install "playwright>=1.59" "numpy>=2.2" "pillow>=12.1" "scipy>=1.15" "soundfile>=0.13"
python3 -m playwright install chromium
sudo apt install ffmpeg        # macOS: brew install ffmpeg
```

On Ubuntu 23.04+ and Debian 12 the system pip is locked (`externally-managed-environment`). Install into a venv and start Claude Code from it: `python3 -m venv ~/.venvs/react-video && source ~/.venvs/react-video/bin/activate`, then the commands above, then `claude`.

You need Python 3.10+ and ffmpeg; the React template also needs Node.js 20.19+ or 22.12+. To check your setup, run `/react-video:react-video check the environment` in Claude Code (`/react-video …` for a manual install), or `python3 scripts/check_env.py --gl` from a clone. If Claude doesn't pick up the skill on its own, call it the same way with your task.

The skill instructions are written in Russian; Claude follows them in any language you use.
