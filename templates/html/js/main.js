// Демо react-video: 8 с, 1080×1920, 120 BPM (доля 0,5 с). Кадр = window.render(t, gt) — чистая функция времени.
//   0–2   кинетический заголовок на canvas, по слову на долю
//   2–4,5 three.js: столбики с тенями, волны на долях
//   4,5–6,5 DOM + CSS @keyframes, перемотанные на t через Web Animations API
//   6,5–8 финальная карточка: контурный текст без линий внутри букв
import { P, E, FPS, frameOf, shake, font, fitFont, alignLeft, textBox, rrect, grain, flash, setFps } from './util.js';
import { cleanOutline } from './outline.js';
import { makeThree } from './three-scene.js';

const T = await (await fetch('timeline.json')).json();
window.T = T;
setFps(T.fps || 30);
const W = T.width || 1080, H = T.height || 1920;
const SAFE = { x0: 80, x1: 940, y0: 220, y1: 1500, cx: 510 };      // Reels: справа кнопки, снизу подпись
const INK = '#f2efe8', DIM = '#8c8a85', ACC = '#ff5b2e';

// Шрифты — до sceneReady, с кириллицей: иначе первые кадры уйдут системным шрифтом.
const CYR = 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя';
await Promise.all([
  "900 100px 'Unbounded'", "800 100px 'Manrope'", "700 100px 'Manrope'", "600 100px 'Manrope'"
].map(f => document.fonts.load(f, CYR + 'Reactvido-0123456789')));
await document.fonts.ready;

const c2 = document.getElementById('c2').getContext('2d');
const fx = document.getElementById('fx').getContext('2d');
const three = makeThree(document.getElementById('gl'), W, H, ACC);
const layer = id => document.getElementById(id);
const L3 = layer('three'), LC = layer('css'), LF = layer('final');

// дорожка сцены CSS: отметки долей
for (let k = 0; k <= 4; k++) {
  const m = document.createElement('div'); m.className = 'beat'; m.style.left = `calc(${k * 25}% - 2px)`;
  document.querySelector('.track').prepend(m);
}

// Рамки текста на canvas для layout_check.py (заполняются при каждом render)
let BOXES = [];
const box = (name, b, words = '', alpha = 1) => { if (alpha >= .5) BOXES.push({ name, ...b, words }); };
window.layoutBoxes = () => BOXES;

// ---------- сцена 1: «Ролик из веб-страницы» ----------
function reveal(ctx, t, tb, draw, top, bottom) {        // слово поднимается из-под своей базовой линии
  const p = E.outExpo(P(t, tb - .04, .42)); if (p <= 0) return 0;
  ctx.save(); ctx.beginPath(); ctx.rect(0, top - 20, W, bottom - top + 40); ctx.clip();
  ctx.translate(0, (1 - p) * (bottom - top + 30)); draw(); ctx.restore();
  return p;
}
function title(ctx, t) {
  if (t >= 2.0) return;
  const out = E.inExpo(P(t, 1.75, .25));                 // whoosh: верх уезжает вверх, низ — вниз
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  // верх бутерброда: «Ролик» — прописные упираются в y = 250
  const s1 = fitFont(ctx, 'Ролик', 900, 'Unbounded', SAFE.x1 - SAFE.x0, 270);
  ctx.font = font(900, s1, 'Unbounded');
  const x1w = alignLeft(ctx, 'Ролик', SAFE.x0), y1 = 250 + ctx.measureText('Ролик').actualBoundingBoxAscent;
  const b1 = textBox(ctx, 'Ролик', x1w, y1);
  ctx.save(); ctx.translate(0, -1100 * out);
  const a1 = reveal(ctx, t, 0.0, () => { ctx.fillStyle = INK; ctx.fillText('Ролик', x1w, y1); }, b1.y0, b1.y1);
  if (a1 > .5 && !out) box('Ролик', b1, 'Ролик');
  ctx.font = font(800, 118, 'Manrope');
  const x2 = alignLeft(ctx, 'из', SAFE.x0), y2 = b1.y1 + 150, b2 = textBox(ctx, 'из', x2, y2);
  const a2 = reveal(ctx, t, 0.5, () => { ctx.fillStyle = ACC; ctx.fillText('из', x2, y2); }, b2.y0, b2.y1);
  if (a2 > .5 && !out) box('из', b2, 'из');
  ctx.restore();

  // низ бутерброда: «веб-страницы» в две строки, нижний край текста — y = 1490
  const s3 = fitFont(ctx, 'страницы', 900, 'Unbounded', SAFE.x1 - SAFE.x0, 200);
  ctx.font = font(900, s3, 'Unbounded');
  const d3 = ctx.measureText('страницы').actualBoundingBoxDescent, y4 = 1490 - d3, y3 = y4 - s3 * 1.02;
  const x3 = alignLeft(ctx, 'веб-', SAFE.x0), x4 = alignLeft(ctx, 'страницы', SAFE.x0);
  const b3 = textBox(ctx, 'веб-', x3, y3), b4 = textBox(ctx, 'страницы', x4, y4);
  ctx.save(); ctx.translate(0, 1100 * out);
  const a3 = reveal(ctx, t, 1.0, () => { ctx.fillStyle = INK; ctx.fillText('веб-', x3, y3); }, b3.y0, b3.y1);
  const a4 = reveal(ctx, t, 1.06, () => { ctx.fillStyle = INK; ctx.fillText('страницы', x4, y4); }, b4.y0, b4.y1);
  if (a3 > .5 && a4 > .5 && !out) box('веб-страницы', { x0: b3.x0, y0: b3.y0, x1: Math.max(b3.x1, b4.x1), y1: b4.y1 }, 'веб-страницы');
  ctx.restore();

  // в середине — окно браузера рисует себя (1,0–1,45), кнопка «play» — на долю 1,5 (click)
  const top = b2.y1 + 90, bot = b3.y0 - 90, x0 = SAFE.x0, x1 = SAFE.x1;
  const draw = E.outQ(P(t, 0.95, .5)); if (draw <= 0) return;
  ctx.save();
  const zc = [(x0 + x1) / 2, (top + bot) / 2 + 30], z = 1 + 5 * out;
  ctx.translate(zc[0], zc[1]); ctx.scale(z, z); ctx.translate(-zc[0], -zc[1]);
  ctx.globalAlpha = 1 - out;
  const per = 2 * (x1 - x0 + bot - top);
  ctx.lineWidth = 6; ctx.strokeStyle = INK; ctx.lineJoin = 'round';
  ctx.setLineDash([per * draw, per]); rrect(ctx, x0 + 3, top, x1 - x0 - 6, bot - top, 34); ctx.stroke();
  ctx.setLineDash([]);
  const bar = E.outQ(P(t, 1.2, .3));
  if (bar > 0) {
    ctx.globalAlpha = (1 - out) * bar;
    ctx.beginPath(); ctx.moveTo(x0 + 3, top + 84); ctx.lineTo(x0 + 3 + (x1 - x0 - 6) * bar, top + 84); ctx.stroke();
    [0, 1, 2].forEach(k => { ctx.beginPath(); ctx.arc(x0 + 50 + k * 42, top + 42, 11, 0, 7); ctx.fillStyle = k ? DIM : ACC; ctx.fill(); });
  }
  const pp = E.outBack(P(t, 1.46, .3), 2.2);
  if (pp > 0) {
    const cx = zc[0] + 12, cy = zc[1], r = 110 * pp;
    ctx.globalAlpha = 1 - out; ctx.fillStyle = ACC;
    ctx.beginPath(); ctx.moveTo(cx - r * .8, cy - r); ctx.lineTo(cx + r, cy); ctx.lineTo(cx - r * .8, cy + r); ctx.closePath();
    ctx.lineJoin = 'round'; ctx.lineWidth = 26 * pp; ctx.strokeStyle = ACC; ctx.stroke(); ctx.fill();
  }
  ctx.restore();
  if (!out) box('окно', { x0, y0: top - 3, x1, y1: bot + 3 });
}

// ---------- сцена 2: подписи поверх three.js ----------
function sceneThree(t) {
  const on = t >= 2.0 && t < 4.5;
  L3.style.visibility = on ? 'visible' : 'hidden';
  if (!on) return;
  const inK = E.outExpo(P(t, 2.25, .5)), inC = E.outExpo(P(t, 2.45, .55)), out = E.inExpo(P(t, 4.25, .25));
  const k = L3.querySelector('.kicker'), c = L3.querySelector('.caption');
  k.style.opacity = inK * (1 - out); k.style.transform = `translateY(${(1 - inK) * 30}px)`;
  c.style.opacity = inC * (1 - out); c.style.transform = `translateY(${(1 - inC) * 60 + out * 80}px)`;
}

// ---------- сцена 3: DOM + CSS @keyframes, перемотанные на t ----------
function sceneCss(t) {
  const on = t >= 4.5 && t < 6.25;
  LC.style.visibility = on ? 'visible' : 'hidden';
  // все CSS-анимации страницы (у них animation-delay 4.5s) — на паузу и в момент t
  for (const a of document.getAnimations()) { a.pause(); a.currentTime = t * 1000; }
  if (!on) return;
  const inn = E.outExpo(P(t, 4.5, .45)), col = E.inExpo(P(t, 5.95, .3));    // вход; схлопывание под riser
  LC.style.opacity = 1 - col;
  LC.style.transform = `translateY(${(1 - inn) * 120}px) scale(${1 - .8 * col})`;
  LC.style.transformOrigin = `${SAFE.cx}px 960px`;
  // число — по номеру кадра: подкадры размытия движения видят одно и то же значение, цифры не «мылятся»
  document.getElementById('tval').textContent = `${Math.round(frameOf(t) / FPS * 1000).toLocaleString('ru-RU')} мс`;
}

// ---------- сцена 4: финальная карточка ----------
function finale(ctx, t) {
  const on = t >= 6.5;
  LF.style.visibility = on ? 'visible' : 'hidden';
  if (!on) return;
  const sub = LF.querySelector('.sub'), ps = E.outExpo(P(t, 6.85, .6));
  sub.style.opacity = ps; sub.style.transform = `translateY(${(1 - ps) * 50}px)`;

  const lines = ['react-', 'video'];
  const s = fitFont(ctx, lines[0], 900, 'Unbounded', (SAFE.x1 - SAFE.x0) / 1.04, 230);   // запас под наезд 1,035
  ctx.font = font(900, s, 'Unbounded'); ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  const drift = 1 + .035 * E.outQ(P(t, 6.5, 1.5));
  const ys = [720 + s * .75, 720 + s * .75 + s * 1.04];
  const xs = lines.map(w => SAFE.cx - ctx.measureText(w).width / 2);
  ctx.save();
  ctx.translate(SAFE.cx, 900); ctx.scale(drift, drift); ctx.translate(-SAFE.cx, -900);
  ctx.lineWidth = 5; ctx.strokeStyle = ACC;
  // буквы влетают с шагом 30 мс после boom; контур без линий внутри букв (outline.js)
  cleanOutline(ctx, (g, m) => {
    let n = 0;
    lines.forEach((w, li) => {
      let x = xs[li];
      for (const ch of w) {
        const p = E.outExpo(P(t, 6.5 + n++ * .03, .55)), dy = (1 - p) * 90;
        if (p > 0) m === 'stroke' ? g.strokeText(ch, x, ys[li] + dy) : g.fillText(ch, x, ys[li] + dy);
        x += g.measureText(ch).width;
      }
    });
  });
  // акцентная черта под словом
  const u = E.outExpo(P(t, 6.8, .6));
  ctx.fillStyle = ACC; ctx.fillRect(SAFE.cx - 60 * u, ys[1] + s * .38, 120 * u, 8);
  ctx.restore();
  const sc = (b) => ({ x0: SAFE.cx + (b.x0 - SAFE.cx) * drift, x1: SAFE.cx + (b.x1 - SAFE.cx) * drift,
                       y0: 900 + (b.y0 - 900) * drift, y1: 900 + (b.y1 - 900) * drift });   // рамка — с учётом наезда
  if (P(t, 6.5, .55) > .6) lines.forEach((w, i) => box(w, sc(textBox(ctx, w, xs[i], ys[i])), i ? '' : 'react-video'));
}

window.render = (t, gt = t) => {
  BOXES = [];
  for (const c of [c2, fx]) { c.setTransform(1, 0, 0, 1, 0, 0); c.globalAlpha = 1; c.clearRect(0, 0, W, H); }
  if (t >= 2.0 && t < 4.5) three.draw(t); else three.clear();

  // толчок на ударах: сдвигаем всю страницу — canvas, WebGL и DOM вместе
  const [sx, sy] = t < 4.5 ? shake(t, 2.0, 10, .25) : shake(t, 6.5, 22, .4);
  document.body.style.transform = `translate(${sx.toFixed(2)}px, ${sy.toFixed(2)}px)`;
  title(c2, t);
  sceneThree(t);
  sceneCss(t);
  finale(c2, t);

  flash(fx, t, 2.0, .18, '242,239,232', .45);
  flash(fx, t, 4.5, .18, '242,239,232', .35);
  flash(fx, t, 6.5, .4, '255,91,46', .45);
  grain(fx, gt, .045);
};

window.sceneReady = true;
