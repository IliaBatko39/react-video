// Контурный текст без линий внутри букв.
//
// Глифы многих шрифтов (Unbounded, Manrope и др.) собраны из перекрывающихся контуров, и strokeText честно
// обводит их пересечения — внутри букв появляются лишние линии. Поэтому штрих ДВОЙНОЙ толщины рисуем на
// отдельном холсте, а заливка тех же букв вырезает (destination-out) его внутреннюю половину вместе
// с пересечениями. Снаружи остаётся ровно ctx.lineWidth.
//
// draw(g, mode) рисует буквы на холсте g: mode === 'stroke' → g.strokeText(...), 'fill' → g.fillText(...).
// Толщина, цвет, пунктир, шрифт и трансформация берутся из ctx; прозрачность (globalAlpha) — у ctx при переносе.
//
//   ctx.font = "900 160px 'Unbounded'"; ctx.lineWidth = 4; ctx.strokeStyle = '#ff5b2e';
//   cleanOutline(ctx, (g, m) => m === 'stroke' ? g.strokeText('контур', x, y) : g.fillText('контур', x, y));

let OC = null;
export function cleanOutline(ctx, draw) {
  const W = ctx.canvas.width, H = ctx.canvas.height;
  if (!OC || OC.width !== W || OC.height !== H) { OC = document.createElement('canvas'); OC.width = W; OC.height = H; }
  const g = OC.getContext('2d');
  g.setTransform(1, 0, 0, 1, 0, 0); g.clearRect(0, 0, W, H); g.setTransform(ctx.getTransform());
  g.font = ctx.font; g.textAlign = ctx.textAlign; g.textBaseline = ctx.textBaseline;
  g.letterSpacing = ctx.letterSpacing || '0px';
  g.lineJoin = 'round'; g.lineCap = 'round';
  g.lineWidth = ctx.lineWidth * 2; g.strokeStyle = ctx.strokeStyle;
  g.setLineDash(ctx.getLineDash()); g.lineDashOffset = ctx.lineDashOffset;
  g.globalCompositeOperation = 'source-over'; draw(g, 'stroke');
  g.globalCompositeOperation = 'destination-out'; draw(g, 'fill');
  g.globalCompositeOperation = 'source-over';
  ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.drawImage(OC, 0, 0); ctx.restore();
}

// Контур одной строки текста: outlineText(ctx, 'react-video', x, y).
export function outlineText(ctx, text, x, y) {
  cleanOutline(ctx, (g, m) => m === 'stroke' ? g.strokeText(text, x, y) : g.fillText(text, x, y));
}
