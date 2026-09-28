# react-video — репозиторий скилла

## Что это и кто пользуется
Публичный скилл для Claude Code: моушн-ролик из веб-страницы (React или HTML → headless Chromium → ffmpeg, звук синтезом). Ставят как плагин из этого репозитория или копируют папку в `~/.claude/skills/react-video`. Пользователи — авторы роликов и разработчики, в основном русскоязычные.

## Где что лежит
- `SKILL.md` — порядок работы, грузится при вызове скилла. Держать коротким, подробности — в `reference/`.
- `reference/` — контракт страницы, приёмы сцены, жанры, звук, проверка.
- `scripts/` — рендер, проверки, звук, выдача. Каждый скрипт самодостаточен (без импортов друг из друга), `--help` по-русски.
- `templates/html`, `templates/react` — демо-ролики, они же витрина в README (`docs/`).
- `.claude-plugin/plugin.json` и `marketplace.json` — один репозиторий = маркетплейс + плагин + скилл в корне (`"skills": ["./"]`, `"source": "./"`).

## Команды
```bash
python3 scripts/check_env.py --gl                                   # окружение
claude plugin validate --strict . && claude plugin validate --strict .claude-plugin/plugin.json
cp -r templates/html /tmp/t && python3 scripts/layout_check.py --dir /tmp/t
python3 scripts/render.py stills 0.5,3,5.5,7.6 --dir /tmp/t          # смотреть глазами
```
Релиз: поднять `version` в `plugin.json`, `claude plugin tag . --push`.

## Стоп-краны
- В SKILL.md пути к своим файлам — только через `${CLAUDE_SKILL_DIR}`; в `reference/` — относительно папки скилла.
- Никаких личных данных, путей конкретной машины, токенов, названий чужих компаний и роликов заказчиков.
- В шаблонах — только свободные ассеты (шрифты OFL с файлом лицензии рядом). Музыку без лицензии не класть.
- Тяжёлое (`node_modules`, кадры, wav, mp4) — в `.gitignore`; в `docs/` только лёгкая витрина.
- Один Chromium за раз: 3D-рендер с размытием ест до 2,5 ГБ памяти.

## Открытые решения
- Английская версия SKILL.md — по спросу.

## Порядок сессии
Прочитать этот файл → `git log -5` → правка → `validate` + рендер шаблона → коммит.
