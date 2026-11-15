import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

// OpenCV compilado para WebAssembly (pacote npm, sem instalação no sistema).
let cvReady;
export const loadCv = () =>
  (cvReady ??= (async () => {
    const mod = require('@techstark/opencv-js');
    if (mod instanceof Promise) return await mod;
    if (mod.Mat) return mod;
    return new Promise((resolve) => {
      mod.onRuntimeInitialized = () => resolve(mod);
    });
  })());

// Todos os limites são relativos ao tamanho da página (S = raiz da área), para servir a qualquer resolução.
const P = {
  minBubbleArea: 0.0012, // fração da área da página
  maxBubbleArea: 0.3,
  minSolidity: 0.55, // balão pontudo (grito) chega perto disso
  inkLevel: 140, // abaixo disso é tinta (texto) dentro do balão
  minInk: 0.004, // fração do balão coberta de tinta; sem texto não é balão
  maxInk: 0.5,
  maxCharToBubble: 0.45, // letra não pode ser maior que isso do balão (senão é mancha)
  freeInk: 110, // tinta para texto fora de balão
  freeMinChar: 0.009, // altura mínima/máxima de uma letra de texto livre, em S
  freeMaxChar: 0.1,
  freeMaxCandidates: 3000,
};

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const median = (a) => {
  const s = [...a].sort((x, y) => x - y);
  return s.length ? s[s.length >> 1] : 0;
};

function percentile(data, p) {
  const hist = new Uint32Array(256);
  for (let i = 0; i < data.length; i++) hist[data[i]]++;
  let acc = 0;
  const target = data.length * p;
  for (let v = 0; v < 256; v++) {
    acc += hist[v];
    if (acc >= target) return v;
  }
  return 255;
}

// Componentes conexos (tinta) de uma máscara 8-bit já pronta: [{x,y,w,h,area,cx,cy}]
export function components(cv, mask, minArea = 1) {
  const labels = new cv.Mat();
  const stats = new cv.Mat();
  const cent = new cv.Mat();
  const n = cv.connectedComponentsWithStats(mask, labels, stats, cent, 8);
  const out = [];
  for (let i = 1; i < n; i++) {
    const area = stats.intAt(i, cv.CC_STAT_AREA);
    if (area < minArea) continue;
    out.push({
      x: stats.intAt(i, cv.CC_STAT_LEFT),
      y: stats.intAt(i, cv.CC_STAT_TOP),
      w: stats.intAt(i, cv.CC_STAT_WIDTH),
      h: stats.intAt(i, cv.CC_STAT_HEIGHT),
      area,
      cx: cent.doubleAt(i, 0),
      cy: cent.doubleAt(i, 1),
    });
  }
  labels.delete();
  stats.delete();
  cent.delete();
  return { list: out, count: n };
}

const unionBox = (items) => {
  const x0 = Math.min(...items.map((c) => c.x));
  const y0 = Math.min(...items.map((c) => c.y));
  const x1 = Math.max(...items.map((c) => c.x + c.w));
  const y1 = Math.max(...items.map((c) => c.y + c.h));
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
};

// Máscara preenchida (com buracos do texto tapados) de um contorno, em um retângulo local.
function fillContour(cv, contour, x, y, w, h, pad) {
  const mask = cv.Mat.zeros(h + 2 * pad, w + 2 * pad, cv.CV_8UC1);
  const vec = new cv.MatVector();
  vec.push_back(contour);
  cv.drawContours(mask, vec, 0, new cv.Scalar(255), cv.FILLED, cv.LINE_8, new cv.Mat(), 0, new cv.Point(pad - x, pad - y));
  vec.delete();
  return mask;
}

function polygonOf(cv, contour) {
  const approx = new cv.Mat();
  cv.approxPolyDP(contour, approx, 0.008 * cv.arcLength(contour, true), true);
  const pts = [];
  for (let i = 0; i < approx.data32S.length; i += 2) pts.push([approx.data32S[i], approx.data32S[i + 1]]);
  approx.delete();
  return pts;
}

// Balões colados (um sobre o outro) saem como UMA região branca. Acha o centro de cada um pela
// transformada de distância e reparte os pixels pelo centro mais próximo (ponderado pelo raio).
function splitMerged(cv, maskMat) {
  const w = maskMat.cols;
  const h = maskMat.rows;
  const dt = new cv.Mat();
  cv.distanceTransform(maskMat, dt, cv.DIST_L2, 3);
  const d = dt.data32F;
  let max = 0;
  for (let i = 0; i < d.length; i++) if (d[i] > max) max = d[i];
  const minPeak = Math.max(0.3 * max, 4);
  const peaks = [];
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const v = d[y * w + x];
      if (v < minPeak) continue;
      let top = true;
      for (let dy = -1; dy <= 1 && top; dy++) for (let dx = -1; dx <= 1; dx++) if (d[(y + dy) * w + x + dx] > v) { top = false; break; }
      if (top) peaks.push({ x, y, r: v });
    }
  }
  peaks.sort((a, b) => b.r - a.r);
  const centers = [];
  for (const p of peaks) if (!centers.some((c) => Math.hypot(c.x - p.x, c.y - p.y) < Math.max(c.r, p.r))) centers.push(p);
  // Sem "pescoço" entre dois centros (a distância não cai ao ligá-los), é o mesmo balão.
  const group = centers.map((_, i) => i);
  const find = (i) => (group[i] === i ? i : (group[i] = find(group[i])));
  for (let i = 0; i < centers.length; i++) {
    for (let j = i + 1; j < centers.length; j++) {
      const a = centers[i];
      const b = centers[j];
      const steps = Math.ceil(Math.hypot(a.x - b.x, a.y - b.y));
      let low = Infinity;
      for (let s = 0; s <= steps; s++) {
        const x = Math.round(a.x + ((b.x - a.x) * s) / steps);
        const y = Math.round(a.y + ((b.y - a.y) * s) / steps);
        low = Math.min(low, d[y * w + x]);
      }
      if (low >= 0.9 * Math.min(a.r, b.r)) group[find(j)] = find(i);
    }
  }
  const ids = [...new Set(centers.map((_, i) => find(i)))];
  dt.delete();
  if (ids.length < 2) return [maskMat.clone()];
  const parts = ids.map(() => cv.Mat.zeros(h, w, cv.CV_8UC1));
  const m = maskMat.data;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      if (!m[y * w + x]) continue;
      let best = 0;
      let bestV = Infinity;
      centers.forEach((c, i) => {
        const v = Math.hypot(c.x - x, c.y - y) - c.r;
        const g = ids.indexOf(find(i));
        if (v < bestV) { bestV = v; best = g; }
      });
      parts[best].data[y * w + x] = 255;
    }
  }
  return parts;
}

// Texto dentro de um balão: agrupa a tinta em blocos e diz se é horizontal ou vertical.
function textBlocks(cv, ink, minArea) {
  // linhas diagonais de hachura preenchem pouco a própria caixa; letras, bastante
  const chars = components(cv, ink, minArea).list.filter((c) => c.area / (c.w * c.h) >= 0.15 && Math.max(c.w, c.h) <= 8 * Math.min(c.w, c.h));
  if (!chars.length) return [];
  const size = median(chars.filter((c) => c.area >= 6).map((c) => Math.max(c.w, c.h))) || median(chars.map((c) => Math.max(c.w, c.h)));
  const k = Math.max(3, Math.round(1.0 * size) | 1);
  const grow = new cv.Mat();
  cv.dilate(ink, grow, cv.getStructuringElement(cv.MORPH_ELLIPSE, new cv.Size(k, k)));
  const labels = new cv.Mat();
  const n = cv.connectedComponents(grow, labels, 8, cv.CV_32S);
  const byLabel = new Map();
  for (const c of chars) {
    const l = labels.intAt(Math.round(c.cy), Math.round(c.cx));
    if (!l) continue;
    if (!byLabel.has(l)) byLabel.set(l, []);
    byLabel.get(l).push(c);
  }
  grow.delete();
  labels.delete();
  void n;
  const blocks = [];
  for (const items of byLabel.values()) {
    const box = unionBox(items);
    // orientação: o vizinho mais próximo de cada letra fica ao lado (horizontal) ou acima/abaixo (vertical)
    let side = 0;
    let stack = 0;
    for (const c of items) {
      let best = Infinity;
      let dx = 0;
      let dy = 0;
      for (const o of items) {
        if (o === c) continue;
        const d = Math.hypot(o.cx - c.cx, o.cy - c.cy);
        if (d < best) { best = d; dx = Math.abs(o.cx - c.cx); dy = Math.abs(o.cy - c.cy); }
      }
      if (best < Infinity) (dx >= dy ? side++ : stack++);
    }
    blocks.push({ ...box, chars: items.length, orientation: stack > side ? 'vertical' : 'horizontal' });
  }
  return blocks;
}

export function detectPage(cv, grayData, W, H) {
  const keep = [];
  const mat = (m) => (keep.push(m), m);
  try {
    const S = Math.sqrt(W * H);
    const pageArea = W * H;
    const gray = mat(cv.matFromArray(H, W, cv.CV_8UC1, grayData));
    const smooth = mat(new cv.Mat());
    cv.medianBlur(gray, smooth, 3);

    // 1) regiões claras (papel/balão), separadas por contornos escuros
    const paper = percentile(smooth.data, 0.95);
    const white = mat(new cv.Mat());
    cv.threshold(smooth, white, clamp(paper - 30, 170, 225), 255, cv.THRESH_BINARY);
    const eroded = mat(new cv.Mat());
    cv.erode(white, eroded, cv.getStructuringElement(cv.MORPH_ELLIPSE, new cv.Size(3, 3))); // fecha vazamentos pelo contorno fino
    // abertura: corta ligações finas (cauda do balão, vazamento por fresta no contorno) que fundiriam o balão com o fundo
    const ko = Math.max(5, Math.round(0.006 * S)) | 1;
    cv.morphologyEx(eroded, eroded, cv.MORPH_OPEN, cv.getStructuringElement(cv.MORPH_ELLIPSE, new cv.Size(ko, ko)));
    const contours = mat(new cv.MatVector());
    const hier = mat(new cv.Mat());
    cv.findContours(eroded, contours, hier, cv.RETR_CCOMP, cv.CHAIN_APPROX_SIMPLE);
    // CCOMP: contornos de nível superior (pai = -1) são os limites externos de cada região branca, inclusive ilhas dentro de buracos

    const pad = 3;
    const balloons = [];
    for (let i = 0; i < contours.size(); i++) {
      if (hier.intAt(0, i * 4 + 3) >= 0) continue; // buraco, não região branca
      const c = contours.get(i);
      const area = cv.contourArea(c);
      if (area < P.minBubbleArea * pageArea || area > P.maxBubbleArea * pageArea) { c.delete(); continue; }
      const r = cv.boundingRect(c);
      const hull = new cv.Mat();
      cv.convexHull(c, hull, false, true);
      const solidity = area / Math.max(1, cv.contourArea(hull));
      hull.delete();
      if (solidity < P.minSolidity) { c.delete(); continue; }
      const filled = fillContour(cv, c, r.x, r.y, r.width, r.height, pad);
      cv.dilate(filled, filled, cv.getStructuringElement(cv.MORPH_ELLIPSE, new cv.Size(3, 3)));
      const rect = cv.minAreaRect(c);
      const rectangularity = area / Math.max(1, rect.size.width * rect.size.height);
      // balão convexo: usa o casco, que ignora os recortes que as letras encostadas na borda abrem no contorno
      let poly;
      if (solidity >= 0.88) {
        const h = new cv.Mat();
        cv.convexHull(c, h, false, true);
        poly = polygonOf(cv, h);
        h.delete();
      } else poly = polygonOf(cv, c);
      c.delete();

      const parts = splitMerged(cv, filled);
      const union = cv.Mat.zeros(filled.rows, filled.cols, cv.CV_8UC1);
      for (const q of parts) cv.bitwise_or(union, q, union);
      for (const part of parts) {
        const partArea = cv.countNonZero(part);
        if (partArea < P.minBubbleArea * pageArea) { part.delete(); continue; }
        // tinta (texto) dentro do balão, longe da borda
        const core = new cv.Mat();
        cv.erode(part, core, cv.getStructuringElement(cv.MORPH_ELLIPSE, new cv.Size(3, 3)));
        const ink = cv.Mat.zeros(part.rows, part.cols, cv.CV_8UC1);
        const ox = r.x - pad;
        const oy = r.y - pad;
        let inkPx = 0;
        for (let y = 0; y < part.rows; y++) {
          const gy = y + oy;
          if (gy < 0 || gy >= H) continue;
          for (let x = 0; x < part.cols; x++) {
            const gx = x + ox;
            if (gx < 0 || gx >= W || !core.data[y * part.cols + x]) continue;
            if (smooth.data[gy * W + gx] < P.inkLevel) { ink.data[y * part.cols + x] = 255; inkPx++; }
          }
        }
        core.delete();
        const frac = inkPx / partArea;
        const blocks = frac >= P.minInk && frac <= P.maxInk ? textBlocks(cv, ink, 2) : [];
        const chars = blocks.reduce((s, b) => s + b.chars, 0);
        const side = Math.sqrt(partArea);
        const tooBig = blocks.some((b) => Math.max(b.w, b.h) > P.maxCharToBubble * side * 3);
        ink.delete();
        if (!blocks.length || tooBig) { part.delete(); continue; }
        const pc = components(cv, part);
        const b = pc.list.length ? unionBox(pc.list) : { x: 0, y: 0, w: part.cols, h: part.rows };
        const split = partArea < area * 0.98; // veio de uma divisão
        balloons.push({
          mask: part,
          ox,
          oy,
          bbox: { x: b.x + ox, y: b.y + oy, w: b.w, h: b.h },
          area: partArea,
          solidity: Number(solidity.toFixed(3)),
          rectangular: !split && rectangularity >= 0.92 && poly.length <= 8,
          polygon: split ? null : poly,
          chars,
          blocks: blocks.map((t) => ({ ...t, x: Math.max(0, t.x + ox - 2), y: Math.max(0, t.y + oy - 2), w: Math.min(W - Math.max(0, t.x + ox - 2), t.w + 4), h: Math.min(H - Math.max(0, t.y + oy - 2), t.h + 4) })),
        });
      }
      union.delete();
      filled.delete();
    }

    // ordem de leitura aproximada para numerar: de cima para baixo, esquerda para direita
    const band = 0.04 * H;
    balloons.sort((a, b) => Math.round(a.bbox.y / band) - Math.round(b.bbox.y / band) || a.bbox.x - b.bbox.x);

    const outBalloons = [];
    const outTexts = [];
    balloons.forEach((b, i) => {
      const id = i + 1;
      let polygon = b.polygon;
      if (!polygon) {
        const cnts = new cv.MatVector();
        const hh = new cv.Mat();
        cv.findContours(b.mask, cnts, hh, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE);
        let best = 0;
        for (let k = 1; k < cnts.size(); k++) if (cv.contourArea(cnts.get(k)) > cv.contourArea(cnts.get(best))) best = k;
        polygon = cnts.size() ? polygonOf(cv, cnts.get(best)).map(([x, y]) => [x + b.ox - 0, y + b.oy - 0]) : [];
        cnts.delete();
        hh.delete();
      }
      outBalloons.push({
        id,
        kind: b.rectangular ? 'narration' : 'balloon',
        certainty: b.solidity >= 0.85 && b.chars >= 3 ? 'alta' : b.solidity < 0.75 ? 'baixa' : 'média',
        bbox: [b.bbox.x, b.bbox.y, b.bbox.w, b.bbox.h],
        polygon,
        textIds: [],
      });
      b.id = id;
    });

    // 2) texto dentro dos balões (ligado ao balão)
    for (const b of balloons) {
      for (const t of b.blocks) {
        const id = outTexts.length + 1;
        outTexts.push({
          id,
          kind: b.rectangular ? 'narration' : 'balloon_text',
          certainty: t.chars >= 3 ? 'alta' : 'média',
          orientation: t.orientation,
          bbox: [t.x, t.y, t.w, t.h],
          balloonId: b.id,
        });
        outBalloons[b.id - 1].textIds.push(id);
      }
    }

    // 3) texto fora de balões: letras escuras do tamanho de texto, alinhadas em fila (efeito sonoro, legenda)
    const layer = mat(cv.Mat.zeros(H, W, cv.CV_8UC1));
    for (const b of balloons) {
      const roi = layer.roi(new cv.Rect(Math.max(0, b.ox), Math.max(0, b.oy), Math.min(W, b.ox + b.mask.cols) - Math.max(0, b.ox), Math.min(H, b.oy + b.mask.rows) - Math.max(0, b.oy)));
      const sx = Math.max(0, -b.ox);
      const sy = Math.max(0, -b.oy);
      const src = b.mask.roi(new cv.Rect(sx, sy, roi.cols, roi.rows));
      const grown = new cv.Mat();
      cv.dilate(src, grown, cv.getStructuringElement(cv.MORPH_ELLIPSE, new cv.Size(9, 9)));
      cv.bitwise_or(roi, grown, roi); // OR: recortes de balões vizinhos se sobrepõem
      grown.delete();
      src.delete();
      roi.delete();
    }
    const dark = mat(new cv.Mat());
    cv.threshold(smooth, dark, P.freeInk, 255, cv.THRESH_BINARY_INV);
    const free = mat(new cv.Mat());
    cv.bitwise_not(layer, layer);
    cv.bitwise_and(dark, layer, free);
    const hMin = P.freeMinChar * S;
    const hMax = P.freeMaxChar * S;
    const cands = components(cv, free, 20).list.filter((c) => {
      const fill = c.area / (c.w * c.h);
      const ar = c.w / c.h;
      return c.h >= hMin && c.h <= hMax && c.w <= hMax * 2.2 && ar >= 0.12 && ar <= 2.8 && fill >= 0.12 && fill <= 0.9;
    });
    if (cands.length && cands.length <= P.freeMaxCandidates) {
      const parent = cands.map((_, i) => i);
      const find = (i) => (parent[i] === i ? i : (parent[i] = find(parent[i])));
      for (let i = 0; i < cands.length; i++) {
        for (let j = i + 1; j < cands.length; j++) {
          const a = cands[i];
          const b = cands[j];
          const big = Math.max(a.h, b.h);
          const ratio = a.h / b.h;
          if (ratio < 0.6 || ratio > 1.67) continue;
          const gapX = Math.max(a.x, b.x) - Math.min(a.x + a.w, b.x + b.w);
          const gapY = Math.max(a.y, b.y) - Math.min(a.y + a.h, b.y + b.h);
          const inRow = Math.abs(a.cy - b.cy) <= 0.45 * big && gapX <= 0.9 * big;
          const inCol = Math.abs(a.cx - b.cx) <= 0.45 * Math.max(a.w, b.w) + 0.2 * big && gapY <= 0.6 * big;
          if (inRow || inCol) parent[find(j)] = find(i);
        }
      }
      const groups = new Map();
      cands.forEach((c, i) => {
        const r = find(i);
        if (!groups.has(r)) groups.set(r, []);
        groups.get(r).push(c);
      });
      const refChar = median(balloons.flatMap((b) => b.blocks.map((t) => Math.min(t.w, t.h)))) ;
      for (const items of groups.values()) {
        if (items.length < 3) continue;
        const box = unionBox(items);
        const fill = items.reduce((s, c) => s + c.area, 0) / (box.w * box.h);
        if (fill < 0.1) continue;
        const h = median(items.map((c) => c.h));
        const big = h >= 0.045 * S || (refChar && h >= 2.3 * refChar * 0.6 && h >= 0.03 * S);
        const id = outTexts.length + 1;
        outTexts.push({
          id,
          kind: big ? 'sfx' : 'free_text',
          certainty: big ? 'baixa' : items.length >= 4 ? 'média' : 'baixa',
          orientation: box.h > box.w * 1.4 ? 'vertical' : 'horizontal',
          bbox: [box.x, box.y, box.w, box.h],
          balloonId: null,
        });
      }
    }

    return { width: W, height: H, balloons: outBalloons, texts: outTexts };
  } finally {
    // (as máscaras de cada balão também precisam ser liberadas)
    for (const m of keep) m.delete();
  }
}
