// Etapa 7: a Etapa 3 às vezes acha só pedaços de um texto solto com contorno grosso (letra preta com contorno branco, ou o
// contrário), sobretudo sobre a arte. Aqui a caixa cresce até o conjunto de letras ligadas pela cor do contorno.
// Conservador: se o crescimento for grande demais ou o "contorno" ocupar a região toda (página branca, céu), mantém a original.
import { dilate, erode } from './clean.js';

// gray: luminância W×H (1 byte). Devolve [x, y, w, h].
export function refineBlock(gray, W, H, bbox) {
  const [bx, by, bw, bh] = bbox;
  if (bw < 6 || bh < 6) return bbox;
  const g = Math.round(0.6 * bh) + 8;
  const wx = Math.max(0, bx - g), wy = Math.max(0, by - g), ww = Math.min(W, bx + bw + g) - wx, wh = Math.min(H, by + bh + g) - wy;
  const rc = Math.max(3, Math.round(Math.min(bh, 40) * 0.18)); // fecha o vão entre letras
  let best = null;
  for (const white of [true, false]) {
    const m = new Uint8Array(ww * wh);
    let count = 0;
    for (let y = 0; y < wh; y++) for (let x = 0; x < ww; x++) { const l = gray[(wy + y) * W + wx + x]; if (white ? l >= 232 : l <= 40) { m[y * ww + x] = 1; count++; } }
    if (count > 0.45 * ww * wh) continue; // cor dominante da região: fundo, não contorno
    const closed = erode(dilate(m, ww, wh, rc), ww, wh, rc);
    const lab = new Int32Array(ww * wh).fill(-1);
    const comps = [];
    for (let s = 0; s < lab.length; s++) {
      if (!closed[s] || lab[s] >= 0) continue;
      const id = comps.length, c = { n: 0, hit: 0, x0: ww, y0: wh, x1: 0, y1: 0 };
      const st = [s]; lab[s] = id;
      while (st.length) {
        const i = st.pop(), x = i % ww, y = (i - x) / ww;
        c.n++; if (x < c.x0) c.x0 = x; if (x >= c.x1) c.x1 = x + 1; if (y < c.y0) c.y0 = y; if (y >= c.y1) c.y1 = y + 1;
        if (x + wx >= bx && x + wx < bx + bw && y + wy >= by && y + wy < by + bh) c.hit++;
        for (const j of [x > 0 ? i - 1 : -1, x < ww - 1 ? i + 1 : -1, y > 0 ? i - ww : -1, y < wh - 1 ? i + ww : -1]) if (j >= 0 && closed[j] && lab[j] < 0) { lab[j] = id; st.push(j); }
      }
      comps.push(c);
    }
    const use = comps.filter((c) => c.hit >= 0.1 * bw * bh);
    if (!use.length) continue;
    const hit = use.reduce((a, c) => a + c.hit, 0);
    const box = [Math.min(...use.map((c) => c.x0)) + wx, Math.min(...use.map((c) => c.y0)) + wy, 0, 0];
    box[2] = Math.max(...use.map((c) => c.x1)) + wx - box[0]; box[3] = Math.max(...use.map((c) => c.y1)) + wy - box[1];
    if (!best || hit > best.hit) best = { hit, box };
  }
  if (!best) return bbox;
  const [x, y, w, h] = best.box;
  const grew = (w * h) / (bw * bh);
  if (grew < 1 || grew > 3 || x < wx || y < wy) return bbox;
  // nunca encolhe a caixa original: une as duas
  const x0 = Math.min(x, bx), y0 = Math.min(y, by);
  return [x0, y0, Math.max(x + w, bx + bw) - x0, Math.max(y + h, by + bh) - y0];
}
