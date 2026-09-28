# Шаблон: React + Vite

Демо 5 с, 1080×1920, 30 к/с: заголовок → живая карточка метрики (обычный React-компонент, значения из `t`) → финальная карточка. Скрипты лежат в `scripts/` папки скилла.

```bash
cp -r templates/react ./video && cd video
npm install
npm run dev                                       # посмотреть в браузере: в консоли window.render(2.5)
npm run build                                     # → dist/
cd .. && python3 scripts/layout_check.py --dir video/dist
python3 scripts/render.py stills 0.5,2.9,4.7 --dir video/dist
python3 scripts/render.py video out.mp4 --dir video/dist --poster 4.5
```

- `src/main.jsx` — контракт: `window.render = t => flushSync(() => root.render(<Video t={t} />))`, `sceneReady` после шрифтов.
- `src/Video.jsx` — сцены; `src/time.js` — `tween`, `progress`, `ease` (чистые функции `t`); `public/timeline.json` — таймлайн.
- Внутри `Video` никаких `useEffect`, таймеров и `Math.random`: кадр зависит только от `t`.
- Рендер всегда из `dist/` (после `npm run build`); `vite.config.js` с `base: './'` делает пути относительными.
- Шрифты Manrope и Unbounded — OFL 1.1, лицензии в `src/fonts/`.
