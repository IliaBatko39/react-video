// Демо react-video: 12 с, 1080×1920, 120 BPM (доля 0,5 с). Кадр = window.render(t, gt) — чистая функция времени.
//   0–2     кинетический заголовок на canvas, по слову на долю
//   2–5     чат Claude: запрос печатается по буквам → рендер по кадрам → готовый promo.mp4
//   5–7,5   three.js: столбики с тенями, волны на долях
//   7,5–9,5 DOM + CSS @keyframes, перемотанные на t через Web Animations API; пауза 9,25–9,5 — стоп-кадр с притемнением
//   9,5–12  финальная карточка: контурный текст без линий внутри букв
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
const L3 = layer('three'), LC = layer('css'), LF = layer('final'), LCH = layer('chat');
// Сцены — из timeline.json: сдвинул сцену в таймлайне — сдвинулась картинка (звук читает тот же файл)
const S = Object.fromEntries(T.scenes.map(s => [s.id, s]));

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

// ---------- сцена «чат»: запрос словами → готовый mp4 ----------
const PROMPT = 'сделай промо-ролик по лендингу';
const $ = id => document.getElementById(id);
function sceneChat(t) {
  const s = S.chat, u = t - s.t0, d = s.t1 - s.t0, on = u >= 0 && u < d;
  LCH.style.visibility = on ? 'visible' : 'hidden';
  if (!on) return;
  const uq = frameOf(t) / FPS - s.t0;                    // буквы и цифры — по номеру кадра: подкадры размытия видят одно и то же
  const inn = E.outExpo(P(u, 0, .45)), out = E.inExpo(P(u, d - .25, .25));
  const term = LCH.querySelector('.term');
  term.style.opacity = inn * (1 - out);
  term.style.transform = `translateY(${(1 - inn) * 160 - out * 260}px)`;
  // печать по буквам: 0,25–1,25 с сцены (tick-серия в timeline.json); ненапечатанное прозрачно — строки не прыгают
  const n = Math.round(PROMPT.length * P(uq, .25, 1.0));
  $('typed').textContent = PROMPT.slice(0, n); $('rest').textContent = PROMPT.slice(n);
  const typing = uq >= .25 && uq < 1.25;
  $('caret').style.visibility = uq >= 1.25 ? 'hidden' : typing || Math.floor(uq * 4) % 2 === 0 ? 'visible' : 'hidden';
  // Enter (click на 1,25) → рендер по кадрам → результат на долю 2,0 (hit)
  const pr = E.inOutC(P(uq, 1.3, .65));
  $('prog').style.opacity = E.outQ(P(u, 1.25, .15));
  $('pfill').style.transform = `scaleX(${pr})`;
  $('pnum').textContent = `кадр ${Math.round(360 * pr)} / 360`;
  const r = E.outExpo(P(u, 1.96, .35));
  $('res').style.opacity = r; $('res').style.transform = `translateY(${(1 - r) * 40}px)`;
  $('chk').style.transform = `scale(${E.outBack(P(u, 1.98, .35), 2.2)})`;
  $('thumb').style.transform = `scale(${E.outBack(P(u, 2.08, .4), 1.6)})`;
}

// ---------- сцена 3D: подписи поверх three.js ----------
function sceneThree(t) {
  const s = S.three, u = t - s.t0, d = s.t1 - s.t0, on = u >= 0 && u < d;
  L3.style.visibility = on ? 'visible' : 'hidden';
  if (!on) return;
  const inK = E.outExpo(P(u, .25, .5)), inC = E.outExpo(P(u, .45, .55)), out = E.inQ(P(u, d - .3, .2));   // подпись уходит раньше наезда камеры
  const k = L3.querySelector('.kicker'), c = L3.querySelector('.caption');
  k.style.opacity = inK * (1 - out); k.style.transform = `translateY(${(1 - inK) * 30}px)`;
  c.style.opacity = inC * (1 - out); c.style.transform = `translateY(${(1 - inC) * 60 + out * 80}px)`;
}

// ---------- сцена CSS: DOM + @keyframes, перемотанные на t ----------
// Перед финальным ударом (секция gap) сцена замирает и темнеет: тишина в звуке, но не чёрный экран.
const GAP = (T.music && T.music.gap) || [S.css.t1 - .25, S.css.t1];
document.documentElement.style.setProperty('--css-t0', `${S.css.t0}s`);
function sceneCss(t) {
  const s = S.css, on = t >= s.t0 && t < s.t1;
  LC.style.visibility = on ? 'visible' : 'hidden';
  const tf = Math.min(t, GAP[0]);                        // стоп-кадр в паузе
  // все CSS-анимации страницы (их animation-delay = начало сцены) — на паузу и в момент t
  for (const a of document.getAnimations()) { a.pause(); a.currentTime = tf * 1000; }
  if (!on) return;
  // вход снизу; под riser сцена медленно поднимается (без масштаба: всё и так во всю ширину безопасной зоны)
  const inn = E.outExpo(P(t, s.t0, .45)), rise = E.inQ(P(tf, GAP[0] - .5, .5));
  LC.style.transform = `translateY(${(1 - inn) * 120 - 36 * rise}px)`;
  document.getElementById('tval').textContent = `${Math.round(frameOf(tf) / FPS * 1000).toLocaleString('ru-RU')} мс`;
}
function dimGap(ctx, t) {                                // притемнение до ~35 % яркости на время паузы
  if (t < GAP[0] || t >= GAP[1]) return;
  ctx.save(); ctx.fillStyle = `rgba(13,14,17,${.65 * E.outQ(P(t, GAP[0], .06))})`; ctx.fillRect(0, 0, W, H); ctx.restore();
}

// ---------- финальная карточка ----------
function finale(ctx, t) {
  const s = S.final, F0 = s.t0, on = t >= F0;
  LF.style.visibility = on ? 'visible' : 'hidden';
  if (!on) return;
  const sub = LF.querySelector('.sub'), url = LF.querySelector('.url');
  const ps = E.outExpo(P(t, F0 + .35, .6)), pu = E.outExpo(P(t, F0 + .6, .6));
  sub.style.opacity = ps; sub.style.transform = `translateY(${(1 - ps) * 50}px)`;
  url.style.opacity = pu; url.style.transform = `translateY(${(1 - pu) * 40}px)`;

  const lines = ['react-', 'video'], LW = 5, DRIFT = .035;
  // запас под наезд и под штрих: (ширина + 2·штрих)·(1 + DRIFT) ≤ ширины безопасной зоны
  const s0 = fitFont(ctx, lines[0], 900, 'Unbounded', (SAFE.x1 - SAFE.x0) / (1 + DRIFT) - 2 * LW - 4, 230);
  ctx.font = font(900, s0, 'Unbounded'); ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  const drift = 1 + DRIFT * E.outQ(P(t, F0, s.t1 - F0));
  const ys = [720 + s0 * .75, 720 + s0 * .75 + s0 * 1.04];
  // центр — по видимым глифам, а не по ширине с полями букв
  const xs = lines.map(w => { const b = textBox(ctx, w, 0, 0); return SAFE.cx - (b.x0 + b.x1) / 2; });
  ctx.save();
  ctx.translate(SAFE.cx, 900); ctx.scale(drift, drift); ctx.translate(-SAFE.cx, -900);
  ctx.lineWidth = LW; ctx.strokeStyle = ACC;
  // буквы влетают с шагом 30 мс после boom; контур без линий внутри букв (outline.js)
  cleanOutline(ctx, (g, m) => {
    let n = 0;
    lines.forEach((w, li) => {
      let x = xs[li];
      for (const ch of w) {
        const p = E.outExpo(P(t, F0 + n++ * .03, .55)), dy = (1 - p) * 90;
        if (p > 0) m === 'stroke' ? g.strokeText(ch, x, ys[li] + dy) : g.fillText(ch, x, ys[li] + dy);
        x += g.measureText(ch).width;
      }
    });
  });
  const ul = E.outExpo(P(t, F0 + .3, .6));               // акцентная черта под словом
  ctx.fillStyle = ACC; ctx.fillRect(SAFE.cx - 60 * ul, ys[1] + s0 * .38, 120 * ul, 8);
  ctx.restore();
  const sc = b => ({ x0: SAFE.cx + (b.x0 - LW - SAFE.cx) * drift, x1: SAFE.cx + (b.x1 + LW - SAFE.cx) * drift,
                     y0: 900 + (b.y0 - LW - 900) * drift, y1: 900 + (b.y1 + LW - 900) * drift });   // рамка — со штрихом и наездом
  if (P(t, F0, .55) > .6) lines.forEach((w, i) => box(w, sc(textBox(ctx, w, xs[i], ys[i])), i ? '' : 'react-video'));
}

window.render = (t, gt = t) => {
  BOXES = [];
  for (const c of [c2, fx]) { c.setTransform(1, 0, 0, 1, 0, 0); c.globalAlpha = 1; c.clearRect(0, 0, W, H); }
  if (t >= S.three.t0 && t < S.three.t1) three.draw(t - S.three.t0, S.three.t1 - S.three.t0); else three.clear();

  // толчок на ударах: сдвигаем всю страницу — canvas, WebGL и DOM вместе
  const hits = [[S.chat.t0, 8, .25], [S.chat.t0 + 2, 6, .2], [S.three.t0, 10, .25], [S.css.t0, 8, .25], [S.final.t0, 22, .4]];
  let sx = 0, sy = 0;
  for (const [t0, a, d] of hits) { const [x, y] = shake(t, t0, a, d); sx += x; sy += y; }
  document.body.style.transform = `translate(${sx.toFixed(2)}px, ${sy.toFixed(2)}px)`;
  title(c2, t);
  sceneChat(t);
  sceneThree(t);
  sceneCss(t);
  finale(c2, t);

  dimGap(fx, t);
  flash(fx, t, S.chat.t0, .18, '242,239,232', .3);
  flash(fx, t, S.chat.t0 + 2, .2, '255,91,46', .15);
  flash(fx, t, S.three.t0, .18, '242,239,232', .35);
  flash(fx, t, S.css.t0, .18, '242,239,232', .3);
  flash(fx, t, S.final.t0, .4, '255,91,46', .45);
  grain(fx, gt, .045);
};

window.sceneReady = true;
