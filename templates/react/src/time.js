// Время кадра → значения. Всё — чистые функции t: никаких useEffect, таймеров, requestAnimationFrame и Math.random.

export const clamp = (x, a = 0, b = 1) => (x < a ? a : x > b ? b : x);
// Прогресс 0…1 на отрезке [start, start + dur].
export const progress = (t, start, dur) => clamp((t - start) / dur);
export const lerp = (a, b, x) => a + (b - a) * x;

export const ease = {
  linear: (x) => x,
  outCubic: (x) => 1 - Math.pow(1 - x, 3),
  inCubic: (x) => x * x * x,
  inOutCubic: (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2),
  outExpo: (x) => (x >= 1 ? 1 : 1 - Math.pow(2, -10 * x)),
  inExpo: (x) => (x <= 0 ? 0 : Math.pow(2, 10 * x - 10)),
  outBack: (x, s = 1.70158) => 1 + (s + 1) * Math.pow(x - 1, 3) + s * Math.pow(x - 1, 2),
};

// tween(t, 1.0, 0.4, 0, 100, ease.outExpo) — значение от 0 до 100 между 1,0 и 1,4 с.
export const tween = (t, start, dur, from, to, fn = ease.outCubic) => lerp(from, to, fn(progress(t, start, dur)));

// Вход и выход элемента: 0 → 1 → 0. Удобно для opacity.
export const inOut = (t, a, b, dIn = 0.4, dOut = 0.25, fn = ease.outExpo) =>
  fn(progress(t, a, dIn)) * (1 - ease.inCubic(progress(t, b - dOut, dOut)));

// Номер кадра выдачи: сидировать им зерно (gt — время кадра выдачи, при перекарте отличается от t).
export const frameOf = (gt, fps = 30) => Math.round(gt * fps);

// Число с неразрывными пробелами между разрядами: 12480 → «12 480».
export const fmt = (n) => Math.round(n).toLocaleString('ru-RU');
