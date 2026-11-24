// Etapa 8: junta as caixas do detector de texto (textdet.js) com os textos que a Etapa 3 já achou. Regras:
//  - caixa já coberta por um texto da Etapa 3 (≥60% da área) → descartada (sem duplicar);
//  - caixa que contém ou cobre em parte um texto existente → esse texto cresce até a caixa (mantém id, tipo e balão);
//  - caixa sem nada embaixo → texto novo: dentro de um balão detectado vira fala desse balão (a unidade do balão passa a ter
//    todas as linhas); muito alta vira efeito sonoro; o resto é texto solto.
// Não decide o que é fala: o OCR e a limpeza das etapas seguintes recusam o que não é texto legível.
const MIN_SCORE = 0.5; // igual ao BOX_THRESH do detector
const MIN_SIDE = 10;
const SFX_HEIGHT = 60; // linha de fala tem 20–40 px; letra de efeito sonoro, bem mais
const SOLID = ['free_text', 'balloon_text', 'narration', 'sfx'];

const area = (b) => b[2] * b[3];
const inter = (a, b) => Math.max(0, Math.min(a[0] + a[2], b[0] + b[2]) - Math.max(a[0], b[0])) * Math.max(0, Math.min(a[1] + a[3], b[1] + b[3]) - Math.max(a[1], b[1]));
const union = (boxes) => {
  const x0 = Math.min(...boxes.map((b) => b[0])), y0 = Math.min(...boxes.map((b) => b[1]));
  return [x0, y0, Math.max(...boxes.map((b) => b[0] + b[2])) - x0, Math.max(...boxes.map((b) => b[1] + b[3])) - y0];
};
export function inPolygon([px, py], poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if (yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
// Balão cortado ou de contorno irregular pode não conter a linha no polígono. Vale se a caixa está dentro do balão e é uma linha
// colada, alinhada, a um texto que o balão já tem (espinho do contorno não fica alinhado a uma fala).
export function alignedLine(balloon, texts, box) {
  if (!balloon.bbox) return false;
  const [bx, by, bw, bh] = balloon.bbox;
  const c = [box[0] + box[2] / 2, box[1] + box[3] / 2];
  if (c[0] < bx || c[0] > bx + bw || c[1] < by || c[1] > by + bh) return false;
  return texts.some((t) => t.balloonId === balloon.id && Math.min(t.bbox[0] + t.bbox[2], box[0] + box[2]) - Math.max(t.bbox[0], box[0]) >= 0.4 * Math.min(t.bbox[2], box[2])
    && Math.max(t.bbox[1], box[1]) - Math.min(t.bbox[1] + t.bbox[3], box[1] + box[3]) <= 1.2 * Math.max(t.bbox[3], box[3]));
}

const rank = (t) => (t.balloonId ? 2 : t.kind === 'free_text' ? 1 : 0); // quem fica quando vários textos viram um só

// page: página da Etapa 3 { texts, balloons, height }. dets: [{ bbox, score }]. Devolve { texts, stats } sem alterar `page`.
export function mergeDetections(page, dets) {
  let texts = page.texts.map((t) => ({ ...t }));
  let nextId = Math.max(0, ...texts.map((t) => t.id)) + 1;
  const stats = { detected: dets.length, covered: 0, extended: 0, added: 0, inBalloon: 0, discarded: 0, attached: 0 };
  // Texto solto da Etapa 3 que na verdade é linha de um balão (alinhado com a fala dele): passa a fazer parte do balão.
  for (const t of texts) {
    if (t.kind !== 'free_text' || t.balloonId) continue;
    const b = page.balloons.find((x) => alignedLine(x, texts, t.bbox));
    if (b) { t.kind = b.kind === 'narration' ? 'narration' : 'balloon_text'; t.balloonId = b.id; t.detector = 'attach'; stats.attached++; }
  }
  for (const d of [...dets].sort((a, b) => a.bbox[1] - b.bbox[1] || a.bbox[0] - b.bbox[0])) {
    const [, , w, h] = d.bbox;
    if (d.score < MIN_SCORE || w < MIN_SIDE || h < MIN_SIDE || w * h < 200) { stats.discarded++; continue; }
    const a = area(d.bbox);
    const host = texts.find((t) => inter(d.bbox, t.bbox) / a >= 0.6);
    if (host) { // já achada; mas a caixa do detector é mais justa nas pontas (o 'S' de "THAT'S" ficava 3 px fora): acerta a coordenada
      const grown = union([host.bbox, d.bbox]);
      if (SOLID.includes(host.kind) && area(grown) <= (host.balloonId ? 1.6 : 6) * area(host.bbox)) { if (grown.some((v, i) => v !== host.bbox[i])) { host.bbox = grown; host.detector ??= 'det'; } }
      stats.covered++;
      continue;
    }
    const mine = texts.filter((t) => SOLID.includes(t.kind) && (inter(d.bbox, t.bbox) / area(t.bbox) >= 0.5 || inter(d.bbox, t.bbox) / a > 0.1));
    if (mine.length) {
      const keep = [...mine].sort((p, q) => rank(q) - rank(p) || area(q.bbox) - area(p.bbox))[0];
      const grown = union([d.bbox, ...mine.map((t) => t.bbox)]);
      // fala de balão só cresce um pouco (a caixa do detector sobre espinhos do contorno traria lixo); texto solto pode crescer mais
      // exceção: crescer na horizontal (mesma linha, altura ≤1.8×) é a linha inteira, não lixo de espinho
      const sameRow = grown[3] <= 1.8 * keep.bbox[3] && grown[2] <= 6 * keep.bbox[2];
      if (area(grown) > (keep.balloonId && !sameRow ? 1.6 : 6) * area(keep.bbox)) { stats.discarded++; continue; }
      keep.bbox = grown;
      keep.detector = 'det';
      texts = texts.filter((t) => t === keep || !mine.includes(t));
      stats.extended++;
      continue;
    }
    const c = [d.bbox[0] + w / 2, d.bbox[1] + h / 2];
    const balloon = page.balloons.find((b) => inPolygon(c, b.polygon)) ?? page.balloons.find((b) => alignedLine(b, texts, d.bbox));
    const kind = balloon ? (balloon.kind === 'narration' ? 'narration' : 'balloon_text') : h >= SFX_HEIGHT ? 'sfx' : 'free_text';
    texts.push({ id: nextId++, kind, certainty: 'média', orientation: 'horizontal', bbox: d.bbox, ...(balloon ? { balloonId: balloon.id } : {}), detector: 'det', score: d.score });
    stats.added++;
    if (balloon) stats.inBalloon++;
  }
  return { texts, stats };
}
