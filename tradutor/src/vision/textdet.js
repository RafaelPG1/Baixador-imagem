// Etapa 8: detector de texto por modelo (PP-OCRv4 "det", rede DB, ~4,7 MB, ONNX na CPU). Acha onde há texto sem depender de
// balão, contorno ou cor: letra fina, com contorno, estilizada, sobre arte. O modelo vem no pacote opcional
// @gutenye/ocr-models (o mesmo da reserva de OCR); sem ele, createTextDetector() devolve null e a Etapa 8 é pulada.
import { createRequire } from 'node:module';
import path from 'node:path';
import sharp from 'sharp';

const require = createRequire(import.meta.url);
const BIN_THRESH = 0.3; // probabilidade mínima para um pixel contar como texto
const BOX_THRESH = 0.5; // média de probabilidade mínima de uma região (letra estilizada/fina rende média baixa; o OCR recusa o que não é texto)
const UNCLIP = 0.9; // o modelo devolve o miolo do texto; a caixa cresce só um pouco (o padrão do DB, 1,6, traz arte para o recorte do OCR)
const MAX_SIDE = 1600;
const OVERLAP = 160;

// Página mais alta/larga que MAX_SIDE encolheria o texto até sumir (tira de webtoon). Fatias com sobreposição, na escala 1.
export function fatias(len, side = MAX_SIDE, overlap = OVERLAP) {
  if (len <= side) return [[0, len]];
  const out = [];
  for (let a = 0; ; a += side - overlap) { const b = Math.min(len, a + side); out.push([a, b]); if (b >= len) break; }
  return out;
}
// Mesma região vista em duas fatias: fica a maior caixa (a outra é a mesma linha cortada na emenda).
export function dedupe(dets) {
  const out = [];
  for (const d of [...dets].sort((a, b) => b.bbox[2] * b.bbox[3] - a.bbox[2] * a.bbox[3])) {
    const [x, y, w, h] = d.bbox;
    const dup = out.some((o) => {
      const iw = Math.min(x + w, o.bbox[0] + o.bbox[2]) - Math.max(x, o.bbox[0]), ih = Math.min(y + h, o.bbox[1] + o.bbox[3]) - Math.max(y, o.bbox[1]);
      return iw > 0 && ih > 0 && (iw * ih) / (w * h) >= 0.7;
    });
    if (!dup) out.push(d);
  }
  return out;
}

// Componentes conexas (4-vizinhos) de prob > BIN_THRESH → [{ x0, y0, x1, y1, n, sum }] em coordenadas do mapa.
export function components(prob, w, h, thresh = BIN_THRESH) {
  const seen = new Uint8Array(w * h);
  const out = [];
  for (let s = 0; s < prob.length; s++) {
    if (seen[s] || prob[s] <= thresh) continue;
    const c = { x0: w, y0: h, x1: 0, y1: 0, n: 0, sum: 0 };
    const st = [s]; seen[s] = 1;
    while (st.length) {
      const i = st.pop(), x = i % w, y = (i - x) / w;
      c.n++; c.sum += prob[i];
      if (x < c.x0) c.x0 = x; if (x >= c.x1) c.x1 = x + 1; if (y < c.y0) c.y0 = y; if (y >= c.y1) c.y1 = y + 1;
      for (const j of [x > 0 ? i - 1 : -1, x < w - 1 ? i + 1 : -1, y > 0 ? i - w : -1, y < h - 1 ? i + w : -1]) if (j >= 0 && !seen[j] && prob[j] > thresh) { seen[j] = 1; st.push(j); }
    }
    out.push(c);
  }
  return out;
}

// Mapa de probabilidade → caixas [x, y, w, h] na escala (sx, sy) da página, já com o crescimento do DB.
export function boxesFromMap(prob, w, h, sx, sy, W, H) {
  const out = [];
  for (const c of components(prob, w, h)) {
    const bw = c.x1 - c.x0, bh = c.y1 - c.y0;
    if (Math.min(bw, bh) < 3 || c.n < 12) continue;
    const score = c.sum / c.n;
    if (score < BOX_THRESH) continue;
    const d = (c.n * UNCLIP) / (2 * (bw + bh)); // distância de crescimento do DB: área × razão / perímetro
    const x0 = Math.max(0, Math.floor((c.x0 - d) * sx)), y0 = Math.max(0, Math.floor((c.y0 - d) * sy));
    const x1 = Math.min(W, Math.ceil((c.x1 + d) * sx)), y1 = Math.min(H, Math.ceil((c.y1 + d) * sy));
    out.push({ bbox: [x0, y0, x1 - x0, y1 - y0], score: Math.round(score * 100) / 100 });
  }
  return out;
}

export async function createTextDetector() {
  let ort, modelPath;
  try {
    ort = require('onnxruntime-node');
    modelPath = path.join(path.dirname(require.resolve('@gutenye/ocr-models/node')), 'assets', 'ch_PP-OCRv4_det_infer.onnx');
  } catch {
    return null;
  }
  let session;
  try {
    session = await ort.InferenceSession.create(modelPath, { executionProviders: ['cpu'], graphOptimizationLevel: 'all' });
  } catch {
    return null;
  }
  return {
    name: 'PP-OCRv4-det',
    // rgb: W×H×3. Devolve [{ bbox, score }] em pixels da página.
    async detect(rgb, W, H) {
      if (Math.max(W, H) <= MAX_SIDE) return one(rgb, W, H);
      const all = [];
      for (const [y0, y1] of fatias(H)) for (const [x0, x1] of fatias(W)) {
        const w = x1 - x0, h = y1 - y0, tile = Buffer.alloc(w * h * 3);
        for (let y = 0; y < h; y++) rgb.copy ? rgb.copy(tile, y * w * 3, ((y0 + y) * W + x0) * 3, ((y0 + y) * W + x1) * 3) : tile.set(rgb.subarray(((y0 + y) * W + x0) * 3, ((y0 + y) * W + x1) * 3), y * w * 3);
        for (const d of await one(tile, w, h)) all.push({ ...d, bbox: [d.bbox[0] + x0, d.bbox[1] + y0, d.bbox[2], d.bbox[3]] });
      }
      return dedupe(all);
    },
    async close() { await session.release?.(); },
  };
  async function one(rgb, W, H) {
    {
      const k = Math.min(1, MAX_SIDE / Math.max(W, H));
      const rw = Math.max(32, Math.ceil((W * k) / 32) * 32), rh = Math.max(32, Math.ceil((H * k) / 32) * 32);
      const { data } = await sharp(rgb, { raw: { width: W, height: H, channels: 3 } }).resize({ width: rw, height: rh, fit: 'fill', kernel: 'lanczos3' }).raw().toBuffer({ resolveWithObject: true });
      const mean = [0.485, 0.456, 0.406], std = [0.229, 0.224, 0.225];
      const input = new Float32Array(3 * rw * rh);
      for (let i = 0; i < rw * rh; i++) for (let c = 0; c < 3; c++) input[c * rw * rh + i] = (data[i * 3 + c] / 255 - mean[c]) / std[c];
      const out = await session.run({ [session.inputNames[0]]: new ort.Tensor('float32', input, [1, 3, rh, rw]) });
      const prob = out[session.outputNames[0]].data;
      return boxesFromMap(prob, rw, rh, W / rw, H / rh, W, H);
    }
  }
}
