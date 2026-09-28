// Вход рендера: window.T, window.render(t, gt), window.sceneReady (контракт react-video).
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import './fonts/fonts.css';
import './style.css';
import Video from './Video.jsx';

const CYR = 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя';

async function boot() {
  const T = await (await fetch('./timeline.json')).json();
  window.T = T;
  const root = createRoot(document.getElementById('root'));
  // flushSync: React обновляет DOM синхронно, и снимок видит именно кадр t, а не предыдущий
  window.render = (t, gt = t) => flushSync(() => root.render(<Video t={t} gt={gt} T={T} />));

  // шрифты с кириллицей — до sceneReady, иначе первые кадры уйдут системным шрифтом
  await Promise.all(["900 100px 'Unbounded'", "800 100px 'Manrope'", "700 100px 'Manrope'", "600 100px 'Manrope'"]
    .map((f) => document.fonts.load(f, CYR + 'react-video 0123456789')));
  await document.fonts.ready;
  window.render(0);
  window.sceneReady = true;
}

boot();
