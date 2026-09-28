// Демо: 5 с, 1080×1920, 120 BPM. Весь ролик — функция t: <Video t={t} /> рисует ровно один кадр.
//   0–1,5   заголовок по слову на долю
//   1,5–3,5 «живой» компонент продукта: карточка метрики со счётчиком и растущим графиком
//   3,5–5   финальная карточка
import { progress, tween, inOut, ease, frameOf, fmt } from './time.js';

// Обычный продуктовый компонент: пропсы на входе, разметка на выходе. В ролик он попадает как есть —
// меняется только то, что значения приходят из t, а не из API.
export function MetricCard({ label, value, delta, bars, grow, badge }) {
  const days = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'];
  return (
    <div className="card">
      <div className="card-head">
        <span className="card-label" data-read="">{label}</span>
        <span className="badge" style={{ opacity: badge, transform: `scale(${0.6 + 0.4 * badge})` }}>+{delta}&nbsp;%</span>
      </div>
      <div className="card-value-row">
        <div className="card-value">{fmt(value)}</div>
        {/* цифра выдуманная — подпись обязательна (reference/genres.md); в чтение не входит, в безопасную зону — да */}
        <span className="demo-note" data-check="">демо-данные</span>
      </div>
      <div className="chart">
        {bars.map((h, k) => (
          <div className="col" key={k}>
            <div className={k === bars.length - 1 ? 'bar bar-acc' : 'bar'} style={{ height: `${h * grow[k]}%` }} />
            <span>{days[k]}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Title({ t }) {
  if (t >= 1.5) return null;
  const w1 = ease.outExpo(progress(t, -0.04, 0.45)), w2 = ease.outExpo(progress(t, 0.46, 0.45));
  const out = ease.inExpo(progress(t, 1.25, 0.25));          // whoosh: уезжает влево
  return (
    <div className="scene" style={{ transform: `translateX(${-1100 * out}px)` }}>
      <div className="kicker title-kicker" data-check="" data-read="" style={{ opacity: w1 }}>React <b>·</b> Vite</div>
      <div className="title" data-check="">
        <div className="mask"><div data-read="" style={{ transform: `translateY(${(1 - w1) * 110}%)` }}>Интерфейс</div></div>
        <div className="mask"><div data-read="" className="acc" style={{ transform: `translateY(${(1 - w2) * 110}%)` }}>в&nbsp;кадре</div></div>
      </div>
    </div>
  );
}

function Metric({ t }) {
  if (t < 1.5 || t >= 3.5) return null;
  const a = ease.outExpo(progress(t, 1.5, 0.5)), out = ease.inCubic(progress(t, 3.2, 0.25));
  const bars = [42, 55, 48, 63, 71, 66, 92];
  const grow = bars.map((_, k) => ease.outBack(progress(t, 2.0 + k * 0.125, 0.35), 1.4));   // tick на каждом столбике
  return (
    <div className="scene" style={{ opacity: 1 - out, transform: `translateY(${(1 - a) * 220}px) scale(${1 - 0.08 * out})` }}>
      <div className="kicker metric-kicker" data-check="" data-read="">Компонент <b>·</b> props</div>
      <div className="card-wrap" data-check="card">
        <MetricCard label="Активные пользователи" value={tween(t, 1.6, 1.5, 0, 12480, ease.outCubic)} delta={18}
                    bars={bars} grow={grow} badge={ease.outBack(progress(t, 2.9, 0.3))} />
      </div>
      <div className="caption" data-check="" data-read="" style={{ opacity: inOut(t, 1.75, 3.5, 0.5, 0.3) }}>
        Настоящий <span className="nowrap">React-компонент</span>
      </div>
    </div>
  );
}

function Final({ t }) {
  if (t < 3.5) return null;
  const a = ease.outExpo(progress(t, 3.5, 0.6)), s = ease.outExpo(progress(t, 3.85, 0.6));
  return (
    <div className="scene">
      <div className="logo" style={{ opacity: a, transform: `scale(${1.18 - 0.18 * a + 0.03 * progress(t, 3.5, 1.5)})` }}>
        <span data-check="logo" data-read="">react<span className="acc">-</span><br />video</span>
      </div>
      <div className="sub" data-check="" data-read="" style={{ opacity: s, transform: `translateY(${(1 - s) * 50}px)` }}>
        скилл для&nbsp;Claude&nbsp;Code
      </div>
    </div>
  );
}

// Затухающий толчок после удара: детерминированный, от номера кадра.
function shake(t, t0, amp, dur, f) {
  const p = progress(t, t0, dur);
  if (p <= 0 || p >= 1) return [0, 0];
  const h = (n) => { const x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };
  const k = amp * (1 - p) * (1 - p);
  return [(h(f * 1.7) - 0.5) * 2 * k, (h(f * 3.1 + 5) - 0.5) * 2 * k];
}

export default function Video({ t, gt = t, T }) {
  const f = frameOf(gt, T.fps || 30);
  const [sx, sy] = shake(t, 3.5, 18, 0.35, f);
  const flash = (t0, dur, a0) => (t >= t0 ? a0 * (1 - ease.outCubic(progress(t, t0, dur))) : 0);
  return (
    <div className="frame" style={{ width: T.width, height: T.height }}>
      <div className="stage" style={{ transform: `translate(${sx}px, ${sy}px)` }}>
        <Title t={t} />
        <Metric t={t} />
        <Final t={t} />
      </div>
      <div className="flash" style={{ opacity: Math.max(flash(1.5, 0.18, 0.3), flash(3.5, 0.4, 0.35)) }} />
      {/* зерно: seed — номер кадра выдачи, у каждого кадра своё, и при перекарте времени оно не «замирает» */}
      <svg className="grain" width={T.width} height={T.height}>
        <filter id="g"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed={f % 997} /></filter>
        <rect width="100%" height="100%" filter="url(#g)" />
      </svg>
    </div>
  );
}
