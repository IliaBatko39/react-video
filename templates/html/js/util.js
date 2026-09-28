// Помощники: всё — чистые функции времени. Никаких Date.now(), requestAnimationFrame и Math.random():
// кадр t должен выглядеть одинаково, в каком бы порядке и сколько бы раз его ни рисовали.

export let FPS = 30;
export const setFps = f => { FPS = f; };

export const clamp = (x, a = 0, b = 1) => x < a ? a : x > b ? b : x;
// Прогресс 0…1 отрезка [a, a + d]: P(t, 1.0, .4) — от 1,0 до 1,4 с.
export const P = (t, a, d) => clamp((t - a) / d);
export const lerp = (a, b, x) => a + (b - a) * x;

// Изинги: x 0…1 → 0…1.
export const E = {
  linear: x => x,
  inQ: x => x * x, outQ: x => 1 - (1 - x) * (1 - x),
  inOutQ: x => x < .5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2,
  inC: x => x * x * x, outC: x => 1 - Math.pow(1 - x, 3),
  inOutC: x => x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2,
  outQuint: x => 1 - Math.pow(1 - x, 5),
  inOutQuint: x => x < .5 ? 16 * x ** 5 : 1 - Math.pow(-2 * x + 2, 5) / 2,
  inExpo: x => x <= 0 ? 0 : Math.pow(2, 10 * x - 10),
  outExpo: x => x >= 1 ? 1 : 1 - Math.pow(2, -10 * x),
  inOutExpo: x => x <= 0 ? 0 : x >= 1 ? 1 : x < .5 ? Math.pow(2, 20 * x - 10) / 2 : (2 - Math.pow(2, -20 * x + 10)) / 2,
  outBack: (x, s = 1.70158) => 1 + (s + 1) * Math.pow(x - 1, 3) + s * Math.pow(x - 1, 2),
  outElastic: x => x <= 0 ? 0 : x >= 1 ? 1 : Math.pow(2, -10 * x) * Math.sin((x * 10 - .75) * 2 * Math.PI / 3) + 1,
  outBounce: x => {
    const n = 7.5625, d = 2.75;
    if (x < 1 / d) return n * x * x;
    if (x < 2 / d) return n * (x -= 1.5 / d) * x + .75;
    if (x < 2.5 / d) return n * (x -= 2.25 / d) * x + .9375;
    return n * (x -= 2.625 / d) * x + .984375;
  }
};

// Детерминированный «шум» 0…1 от числа.
export function hash(n) { const x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); }
// Генератор случайных чисел с зерном (mulberry32): rng(42)() → 0…1, всегда одна и та же последовательность.
export function rng(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6D2B79F5) >>> 0; let t = s;
    t = Math.imul(t ^ t >>> 15, t | 1); t ^= t + Math.imul(t ^ t >>> 7, t | 61);
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}
// Номер кадра: общий для всех подкадров размытия движения (зерно и дрожание не «мылятся»).
export const frameOf = t => Math.round(t * FPS);

// Затухающее дрожание после удара в t0: смещение [dx, dy] в px.
export function shake(t, t0, amp = 14, dur = .28) {
  const p = P(t, t0, dur); if (p <= 0 || p >= 1) return [0, 0];
  const f = frameOf(t), a = amp * Math.pow(1 - p, 2);
  return [(hash(f * 1.7 + t0) - .5) * 2 * a, (hash(f * 3.1 + t0 * 7) - .5) * 2 * a];
}

// CSS-шрифт для canvas: font(900, 120, 'Unbounded') → "900 120px 'Unbounded'".
export const font = (weight, size, family) => `${weight} ${size}px '${family}'`;
// Кегль, при котором text влезает в maxW (но не больше maxSize).
// Меряется видимая ширина глифов (actualBoundingBox), а не ширина с полями букв.
export function fitFont(ctx, text, weight, family, maxW, maxSize) {
  ctx.font = font(weight, 100, family);
  const m = ctx.measureText(text), w = m.actualBoundingBoxLeft + m.actualBoundingBoxRight;
  return Math.min(maxSize, 100 * maxW / w);
}
// x для fillText с textAlign 'left', при котором видимый левый край глифа встаёт ровно в x0.
export const alignLeft = (ctx, text, x0) => x0 + ctx.measureText(text).actualBoundingBoxLeft;
// Точная рамка текста, нарисованного fillText(text, x, y) с текущими ctx.font/textAlign/textBaseline.
export function textBox(ctx, text, x, y) {
  const m = ctx.measureText(text);
  return { x0: x - m.actualBoundingBoxLeft, x1: x + m.actualBoundingBoxRight, y0: y - m.actualBoundingBoxAscent, y1: y + m.actualBoundingBoxDescent };
}
export function rrect(ctx, x, y, w, h, r) {
  r = Math.min(r, w / 2, h / 2);
  ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}
// x-позиции букв с кернингом шрифта — для побуквенной анимации.
export function letterXs(ctx, text) {
  const xs = []; for (let i = 0; i < text.length; i++) xs.push(ctx.measureText(text.slice(0, i)).width);
  return xs;
}

// Плёночное зерно поверх кадра, сидированное номером кадра выдачи (gt), а не временем сцены t.
let grainTiles = null;
export function grain(ctx, gt, alpha = .05) {
  if (!grainTiles) {
    grainTiles = [0, 1, 2].map(k => {
      const c = document.createElement('canvas'); c.width = c.height = 256;
      const g = c.getContext('2d'), id = g.createImageData(256, 256), r = rng(1000 + k);
      for (let i = 0; i < id.data.length; i += 4) { const v = r() * 255; id.data[i] = id.data[i + 1] = id.data[i + 2] = v; id.data[i + 3] = 255; }
      g.putImageData(id, 0, 0); return c;
    });
  }
  const f = frameOf(gt), pat = ctx.createPattern(grainTiles[((f % 3) + 3) % 3], 'repeat');
  // зерно 2×2 px: мельче — поток x264 раздувается в разы, а глазу на телефоне разница не видна
  pat.setTransform(new DOMMatrix().translate(Math.floor(hash(f) * 512), Math.floor(hash(f + .5) * 512)).scale(2));
  ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = alpha;
  ctx.fillStyle = pat; ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height); ctx.restore();
}

// Вспышка на ударе: полупрозрачная заливка, гаснет за dur.
export function flash(ctx, t, t0, dur, rgb, a0 = .8) {
  const p = P(t, t0, dur); if (p <= 0 || p >= 1) return;
  ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = `rgba(${rgb},${a0 * (1 - E.outQ(p))})`; ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height);
  ctx.restore();
}
