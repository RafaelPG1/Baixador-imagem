// Etapa 7: balão cortado entre duas imagens cuja metade de baixo a Etapa 3 não detectou (pedaço fino sobre fundo branco
// da página). Parte da emenda: o miolo do balão em cima, na cor do fundo dele, continua embaixo até o contorno.
// Devolve { bbox, polygon } da metade de baixo (envoltória convexa do miolo achado) ou null se não for um balão fechado.
const median = (a) => { const s = Float64Array.from(a).sort(); return s.length ? s[s.length >> 1] : 255; };

function hull(pts) {
  const p = [...pts].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const half = (arr) => { const h = []; for (const q of arr) { while (h.length >= 2 && cross(h[h.length - 2], h[h.length - 1], q) <= 0) h.pop(); h.push(q); } h.pop(); return h; };
  return [...half(p), ...half([...p].reverse())];
}

// grayA/grayB: luminância W×HA e W×HB. balloonA: { bbox, polygon } na página de cima.
export function lowerHalf(grayA, grayB, W, HA, HB, balloonA) {
  const edge = balloonA.polygon.filter(([, y]) => y >= HA - 6).map(([x]) => x);
  if (edge.length < 2) return null;
  const x0 = Math.min(...edge), x1 = Math.max(...edge);
  if (x1 - x0 < 20) return null;
  const inner = [Math.round(x0 + 0.15 * (x1 - x0)), Math.round(x1 - 0.15 * (x1 - x0))]; // sem o contorno nas pontas
  const near = [];
  for (let y = HA - 8; y < HA - 1; y++) for (let x = inner[0]; x < inner[1]; x++) near.push(grayA[y * W + x]);
  const bg = median(near.filter((l) => (median(near) >= 128 ? l >= 128 : l < 128)));
  const maxRows = Math.min(HB, Math.round(1.2 * balloonA.bbox[3]) + 40);
  const same = (l) => Math.abs(l - bg) <= 40;
  const seen = new Uint8Array(W * maxRows);
  const st = [];
  for (let x = inner[0]; x < inner[1]; x++) if (same(grayB[x]) && !seen[x]) { seen[x] = 1; st.push(x); }
  let n = 0, leak = false;
  while (st.length) {
    const i = st.pop(), x = i % W, y = (i - x) / W;
    n++;
    if (x === 0 || x === W - 1 || y === maxRows - 1) { leak = true; break; } // vazou para fora do balão: não há contorno fechado
    for (const j of [i - 1, i + 1, i + W, y > 0 ? i - W : -1]) if (j >= 0 && !seen[j] && same(grayB[j])) { seen[j] = 1; st.push(j); }
  }
  if (leak || n < 150) return null;
  const rows = [];
  for (let y = 0; y < maxRows; y++) { let a = -1, b = -1; for (let x = 0; x < W; x++) if (seen[y * W + x]) { if (a < 0) a = x; b = x; } if (a >= 0) rows.push([y, a, b]); }
  const pts = []; const step = Math.max(1, Math.floor(rows.length / 30));
  rows.forEach(([y, a, b], k) => { if (k % step === 0 || k === rows.length - 1) pts.push([a, y], [b + 1, y + 1]); });
  const polygon = hull(pts);
  const xs = polygon.map((p) => p[0]), ys = polygon.map((p) => p[1]);
  return { bbox: [Math.min(...xs), 0, Math.max(...xs) - Math.min(...xs), Math.max(...ys)], polygon };
}
