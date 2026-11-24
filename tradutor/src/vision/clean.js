// Etapa 6: apaga o texto original dentro dos balões e diz onde a tradução cabe. NÃO altera as imagens originais:
// gera, por página, um PNG transparente do mesmo tamanho que só tem pintados os pixels do texto (na cor real do
// fundo do balão). O leitor põe esse PNG por cima do original e escreve a tradução na caixa calculada aqui.
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { progresso } from '../progresso.js';
import sharp from 'sharp';
import { cleanFree, cleanForce, inpaint } from './clean-free.js';
import { apagar, tracos } from './apagar.js';
import { isWord } from '../ocr/lexicon.js';

const median = (a) => { const s = Float64Array.from(a).sort(); return s.length ? s[s.length >> 1] : 0; };
const lumaOf = (c) => (299 * c[0] + 587 * c[1] + 114 * c[2]) / 1000;
const hex = ([r, g, b]) => `#${[r, g, b].map((v) => Math.round(v).toString(16).padStart(2, '0')).join('')}`;

// Preenche o polígono (regra par-ímpar, linha a linha) numa máscara w×h.
export function fillPolygon(poly, w, h) {
  const m = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    const xs = [];
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [x1, y1] = poly[j], [x2, y2] = poly[i];
      if ((y1 <= y + 0.5) !== (y2 <= y + 0.5)) xs.push(x1 + ((y + 0.5 - y1) * (x2 - x1)) / (y2 - y1));
    }
    xs.sort((a, b) => a - b);
    for (let k = 0; k + 1 < xs.length; k += 2) {
      for (let x = Math.max(0, Math.ceil(xs[k] - 0.5)); x < Math.min(w, Math.ceil(xs[k + 1] - 0.5)); x++) m[y * w + x] = 1;
    }
  }
  return m;
}

// Dilatação/erosão com quadrado de lado 2r+1, em duas passadas (horizontal e vertical).
function morph(mask, w, h, r, grow) {
  const pass = (src, horizontal) => {
    const out = new Uint8Array(w * h);
    const n = horizontal ? w : h, lines = horizontal ? h : w;
    for (let l = 0; l < lines; l++) {
      for (let i = 0; i < n; i++) {
        let hit = grow ? 0 : 1;
        for (let d = -r; d <= r; d++) {
          const k = i + d;
          const v = k < 0 || k >= n ? 0 : src[horizontal ? l * w + k : k * w + l]; // fora da imagem conta como vazio
          if (grow ? v : !v) { hit = grow ? 1 : 0; break; }
        }
        out[horizontal ? l * w + i : i * w + l] = hit;
      }
    }
    return out;
  };
  return pass(pass(mask, true), false);
}
export const dilate = (m, w, h, r) => morph(m, w, h, r, true);
export const erode = (m, w, h, r) => morph(m, w, h, r, false);

// Texto solto só é escrito por cima se foi lido como inglês de verdade: 2+ palavras e 80% delas no léxico.
export function legivel(text = '') {
  const w = text.match(/[A-Za-z']{2,}/g) ?? [];
  return w.length >= 2 && w.filter((x) => isWord(x.toLowerCase())).length >= 0.8 * w.length;
}

// Maior caixa, centrada, de w0×h0 até kw×kh vezes isso, para a qual fits(w, h) é verdade (passo de 0,1).
export function bestBox(fits, w0, h0, maxKw, maxKh) {
  let best = { w: w0, h: h0 };
  for (let kw = 1; kw <= maxKw + 0.0001; kw += 0.1) for (let kh = 1; kh <= maxKh + 0.0001; kh += 0.1) {
    if (kw * w0 * kh * h0 > best.w * best.h && fits(kw * w0, kh * h0)) best = { w: kw * w0, h: kh * h0 };
  }
  return best;
}

// rgb: pixels da página (3 bytes cada, W×H). polygon e bbox em coordenadas da página. patch: RGBA W×H×4, recebe o apagado.
// Devolve { bg, ink, box, lines, fontMax, covered } ou { empty: true } se não achou texto no balão.
// `polygons` (opcional) = vários polígonos que formam um balão só (balão cortado entre duas imagens, com as páginas
// empilhadas em rgb); sem ele vale `polygon`.
export function cleanUnit({ rgb, W, H, polygon, polygons = [polygon], bbox, patch }) {
  const touchesEdge = bbox[1] <= 2 || bbox[1] + bbox[3] >= H - 2;
  const m0 = Math.max(6, Math.round(0.18 * Math.min(bbox[2], bbox[3])));
  const pts = [...polygons.flat(), [bbox[0] - m0 - 5, bbox[1] - m0 - 5], [bbox[0] + bbox[2] + m0 + 5, bbox[1] + bbox[3] + m0 + 5]]; // a região cobre o texto mesmo fora do polígono (texto que passa do balão, texto na borda)
  const rx = Math.max(0, Math.floor(Math.min(...pts.map((p) => p[0]))));
  const ry = Math.max(0, Math.floor(Math.min(...pts.map((p) => p[1]))));
  const rw = Math.min(W, Math.ceil(Math.max(...pts.map((p) => p[0])))) - rx;
  const rh = Math.min(H, Math.ceil(Math.max(...pts.map((p) => p[1])))) - ry;
  if (rw < 4 || rh < 4) return { empty: true };
  const filled = new Uint8Array(rw * rh);
  for (const poly of polygons) fillPolygon(poly.map(([x, y]) => [x - rx, y - ry]), rw, rh).forEach((v, i) => { if (v) filled[i] = 1; });
  // balão cortado na borda da imagem: o texto que encosta nela às vezes fica fora do polígono (virou "contorno"); o retângulo do texto é do balão
  let edgeRect = null;
  if (touchesEdge) {
    edgeRect = [Math.max(0, Math.floor(bbox[0] - rx) - 2), Math.max(0, Math.floor(bbox[1] - ry)), Math.min(rw, Math.ceil(bbox[0] + bbox[2] - rx) + 2), Math.min(rh, Math.ceil(bbox[1] + bbox[3] - ry))];
    for (let y = edgeRect[1]; y < edgeRect[3]; y++) for (let x = edgeRect[0]; x < edgeRect[2]; x++) filled[y * rw + x] = 1;
  }
  const interior = erode(filled, rw, rh, 3); // o contorno do balão fica de fora
  // a borda da imagem não é contorno: no retângulo do texto o erode não vale
  if (edgeRect) for (let y = edgeRect[1]; y < edgeRect[3]; y++) for (let x = edgeRect[0]; x < edgeRect[2]; x++) interior[y * rw + x] = 1;
  const luma = new Float64Array(rw * rh);
  for (let y = 0; y < rh; y++) for (let x = 0; x < rw; x++) {
    const o = ((ry + y) * W + rx + x) * 3;
    luma[y * rw + x] = (299 * rgb[o] + 587 * rgb[o + 1] + 114 * rgb[o + 2]) / 1000;
  }
  const inside = [];
  for (let i = 0; i < interior.length; i++) if (interior[i]) inside.push(luma[i]);
  if (inside.length < 30) return { empty: true };
  const med = median(inside);
  const darkInk = med >= 110; // texto escuro em fundo claro; o contrário em balão escuro
  // Balão de grito: os espinhos do contorno entram no polígono e parecem tinta. Tira do interior a tinta ligada ao
  // contorno (só até 12% do menor lado, para não comer texto que encosta na borda).
  {
    const isInk = (i) => (darkInk ? luma[i] < med - 70 : luma[i] > med + 70);
    const maxD = Math.round(0.12 * Math.min(rw, rh));
    const dist = new Int32Array(rw * rh).fill(-1);
    let q = [];
    // borda da imagem não é contorno: balão cortado tem texto encostado nela (a emenda), e ele não é espinho
    const seam = (i) => { const y = ry + Math.floor(i / rw); return y < 4 || y >= H - 4; };
    for (let i = 0; i < filled.length; i++) if (filled[i] && !interior[i] && !seam(i) && isInk(i)) { dist[i] = 0; q.push(i); }
    for (let d = 0; q.length && d < maxD; d++) {
      const nq = [];
      for (const i of q) for (const j of [i - 1, i + 1, i - rw, i + rw]) {
        if (j < 0 || j >= dist.length || dist[j] >= 0 || !interior[j] || !isInk(j)) continue;
        if ((j === i - 1 && i % rw === 0) || (j === i + 1 && j % rw === 0)) continue;
        dist[j] = d + 1; nq.push(j);
      }
      q = nq;
    }
    for (let i = 0; i < interior.length; i++) if (dist[i] > 0) interior[i] = 0;
  }
  // retângulo do texto (com folga), em coordenadas da região
  const tx0 = Math.max(0, Math.floor(bbox[0] - rx - 5)), ty0 = Math.max(0, Math.floor(bbox[1] - ry - 5));
  const tx1 = Math.min(rw, Math.ceil(bbox[0] + bbox[2] - rx + 5)), ty1 = Math.min(rh, Math.ceil(bbox[1] + bbox[3] - ry + 5));
  const ink = new Uint8Array(rw * rh);
  let nInk = 0, ix0 = rw, iy0 = rh, ix1 = 0, iy1 = 0;
  for (let y = ty0; y < ty1; y++) for (let x = tx0; x < tx1; x++) {
    const i = y * rw + x;
    if (interior[i] && (darkInk ? luma[i] < med - 70 : luma[i] > med + 70)) {
      ink[i] = 1; nInk++;
      if (x < ix0) ix0 = x; if (x >= ix1) ix1 = x + 1; if (y < iy0) iy0 = y; if (y >= iy1) iy1 = y + 1;
    }
  }
  if (nInk < 8) return { empty: true };

  // cor do fundo: mediana dos pixels do balão perto do texto que não são tinta
  const near = dilate(ink, rw, rh, 3);
  const rgbAt = (i) => { const o = ((ry + Math.floor(i / rw)) * W + rx + (i % rw)) * 3; return [rgb[o], rgb[o + 1], rgb[o + 2]]; };
  const pick = (filter) => { const ch = [[], [], []]; for (let y = ty0; y < ty1; y++) for (let x = tx0; x < tx1; x++) { const i = y * rw + x; if (filter(i)) rgbAt(i).forEach((v, c) => ch[c].push(v)); } return ch; };
  let ch = pick((i) => interior[i] && !near[i]);
  if (ch[0].length < 20) ch = pick((i) => interior[i] && !ink[i]);
  const bg = ch[0].length ? ch.map(median) : darkInk ? [255, 255, 255] : [0, 0, 0];
  // cor da tinta: mediana dos 40% de pixels mais extremos do texto
  const inkPx = []; for (let i = 0; i < ink.length; i++) if (ink[i]) inkPx.push(i);
  inkPx.sort((a, b) => (darkInk ? luma[a] - luma[b] : luma[b] - luma[a]));
  const core = inkPx.slice(0, Math.max(1, Math.floor(inkPx.length * 0.4)));
  const inkRgb = [0, 1, 2].map((c) => median(core.map((i) => rgbAt(i)[c])));

  // Cobertura: parte da tinta achada e deixa `apagar` reconstruir o fundo e cobrir o que ainda destoa (letra fraca, ponta que o OCR
  // não pegou, texto que passou do balão). O contorno do balão fica protegido; o fundo vem da difusão das cores vizinhas, então
  // balão com degradê ou textura não ganha "mancha" de cor chapada.
  // Contorno protegido = faixa junto da borda do polígono QUE TEM A COR DO CONTORNO (o resto da faixa — fundo do balão, ponta de letra —
  // é pintável). A cor do contorno é a dos pixels da faixa que mais se afastam do fundo do balão.
  const faixa = new Uint8Array(rw * rh);
  for (let i = 0; i < faixa.length; i++) if (filled[i] && !interior[i]) faixa[i] = 1;
  if (edgeRect) for (let y = edgeRect[1]; y < edgeRect[3]; y++) for (let x = edgeRect[0]; x < edgeRect[2]; x++) faixa[y * rw + x] = 0;
  const idxFaixa = []; for (let i = 0; i < faixa.length; i++) if (faixa[i]) idxFaixa.push(i);
  idxFaixa.sort((a, b) => Math.abs(luma[b] - med) - Math.abs(luma[a] - med));
  const corCont = idxFaixa.length >= 12 ? [0, 1, 2].map((c) => median(idxFaixa.slice(0, Math.max(6, Math.floor(idxFaixa.length * 0.35))).map((i) => rgb[((ry + Math.floor(i / rw)) * W + rx + (i % rw)) * 3 + c]))) : null;
  const rgbR = (i) => { const o = ((ry + Math.floor(i / rw)) * W + rx + (i % rw)) * 3; return [rgb[o], rgb[o + 1], rgb[o + 2]]; };
  const protegido = new Uint8Array(rw * rh);
  if (!corCont) { for (const i of idxFaixa) protegido[i] = 1; }
  else if (Math.abs(lumaOf(corCont) - med) > 40) { for (const i of idxFaixa) if (Math.max(...rgbR(i).map((v, c) => Math.abs(v - corCont[c]))) < 45) protegido[i] = 1; }
  // texto que passou do polígono: tinta fora do balão, junto da caixa lida, também é do texto
  const seed = Uint8Array.from(ink);
  const fora = tracos(luma, rw, rh);
  for (let y = ty0; y < ty1; y++) for (let x = tx0; x < tx1; x++) {
    const i = y * rw + x;
    if (!filled[i] && fora[i]) seed[i] = 1;
    else if (faixa[i] && !protegido[i] && (darkInk ? luma[i] < med - 70 : luma[i] > med + 70)) seed[i] = 1; // ponta de letra na faixa do contorno que não tem a cor dele
  }
  const zone = new Uint8Array(rw * rh), margem = Math.max(6, Math.round(0.18 * Math.min(bbox[2], bbox[3])));
  for (let y = Math.max(0, ty0 - margem); y < Math.min(rh, ty1 + margem); y++) for (let x = Math.max(0, tx0 - margem); x < Math.min(rw, tx1 + margem); x++) zone[y * rw + x] = 1;
  // Junto do contorno (5 px de cada lado) só vale cobrir o que tem cor de TINTA e não de contorno: o contorno inteiro (com antialias)
  // é traço também, e crescer por ele o roeria até virar fio.
  const miolo5 = erode(filled, rw, rh, 5);
  const anel = dilate(filled, rw, rh, 5).map((v, i) => (v && !miolo5[i] ? 1 : 0));
  const permitido = new Uint8Array(rw * rh).fill(1);
  {
    const sp = [...seed.keys()].filter((i) => seed[i] && interior[i]);
    const corT = sp.length ? [0, 1, 2].map((c) => median(sp.map((i) => rgbR(i)[c]))) : null;
    const dc = (i, cor) => Math.max(...rgbR(i).map((v, k) => Math.abs(v - cor[k])));
    for (let i = 0; i < anel.length; i++) {
      if (!anel[i]) continue;
      if (edgeRect && (i % rw) >= edgeRect[0] && (i % rw) < edgeRect[2] && Math.floor(i / rw) >= edgeRect[1] && Math.floor(i / rw) < edgeRect[3]) continue;
      permitido[i] = corT && dc(i, corT) < 110 && (!corCont || dc(i, corCont) >= 45) ? 1 : 0;
    }
  }
  const reg = new Uint8Array(rw * rh * 3);
  for (let y = 0; y < rh; y++) reg.set(rgb.subarray(((ry + y) * W + rx) * 3, ((ry + y) * W + rx + rw) * 3), y * rw * 3);
  const ap = apagar({ reg, rw, rh, seed, zone, permitido, protegido, fonteRuim: anel, lado: filled });
  // Letra que atravessa o contorno: o vão que ela abriu no contorno (fecho morfológico) é refeito só com as cores do contorno.
  const fecho = erode(dilate(protegido, rw, rh, 4), rw, rh, 4), vao = new Uint8Array(rw * rh);
  let nVao = 0;
  for (let i = 0; i < vao.length; i++) if (fecho[i] && !protegido[i] && ap.mask[i]) { vao[i] = 1; nVao++; }
  const contorno = nVao ? inpaint(reg, rw, rh, Uint8Array.from(protegido, (v) => (v ? 0 : 1))) : null;
  let covered = 0;
  for (let y = 0; y < rh; y++) for (let x = 0; x < rw; x++) {
    const i = y * rw + x;
    if (!ap.mask[i]) continue;
    const o = ((ry + y) * W + rx + x) * 4, f = vao[i] ? contorno : ap.fill;
    patch[o] = Math.round(f[i * 3]); patch[o + 1] = Math.round(f[i * 3 + 1]); patch[o + 2] = Math.round(f[i * 3 + 2]); patch[o + 3] = 255;
    covered++;
  }

  // linhas de texto: faixas de linhas de pixels com tinta, juntando vãos pequenos (pingo do "i", acentos)
  const rows = []; for (let y = iy0; y < iy1; y++) { let any = false; for (let x = ix0; x < ix1 && !any; x++) any = ink[y * rw + x] === 1; rows.push(any); }
  const runs = []; rows.forEach((v, k) => { if (v) (runs.length && runs[runs.length - 1][1] === k ? (runs[runs.length - 1][1] = k + 1) : runs.push([k, k + 1])); });
  const tall = Math.max(...runs.map(([a, b]) => b - a));
  const lineRuns = runs.reduce((acc, r) => (acc.length && r[0] - acc[acc.length - 1][1] < 0.25 * tall ? (acc[acc.length - 1][1] = r[1], acc) : [...acc, [...r]]), []);
  const lines = lineRuns.length;
  const inkH = iy1 - iy0;
  const fontMax = Math.round(Math.min(80, Math.max(10, lines > 1 ? (inkH / lines) * 0.95 : inkH * 1.35)));

  // caixa da tradução: a maior caixa, centrada no texto, que cabe inteira no balão (largura até 1,6×, altura até 2,2×)
  const cx = (ix0 + ix1) / 2, cy = (iy0 + iy1) / 2, w0 = ix1 - ix0, h0 = iy1 - iy0;
  const fits = (w, h) => {
    const x0 = Math.round(cx - w / 2), x1 = Math.round(cx + w / 2), y0 = Math.round(cy - h / 2), y1 = Math.round(cy + h / 2);
    if (x0 < 0 || y0 < 0 || x1 > rw || y1 > rh) return false;
    for (let x = x0; x < x1; x += 3) if (!interior[y0 * rw + x] || !interior[(y1 - 1) * rw + x]) return false;
    for (let y = y0; y < y1; y += 3) if (!interior[y * rw + x0] || !interior[y * rw + x1 - 1]) return false;
    return interior[y0 * rw + x0] && interior[y0 * rw + x1 - 1] && interior[(y1 - 1) * rw + x0] && interior[(y1 - 1) * rw + x1 - 1] === 1;
  };
  const best = bestBox(fits, w0, h0, 1.6, 2.2);
  const bw = best.w * 0.96, bh = best.h * 0.96;
  // perfil do balão: para cada faixa de linhas, de onde a onde vai o miolo (sem contorno) em volta do centro. O encaixe do texto usa isto
  // para respeitar balão redondo, que não é retângulo.
  const perfil = [], passo = Math.max(2, Math.ceil(rh / 70)), cxi = Math.round(cx);
  const corre = (y) => {
    let x = cxi;
    for (let d = 0; d < 10 && !interior[y * rw + x]; d++) x = cxi + (d % 2 ? -((d + 1) >> 1) : (d >> 1) + 1);
    if (x < 0 || x >= rw || !interior[y * rw + x]) return null;
    let l = x, r = x;
    while (l > 0 && interior[y * rw + l - 1]) l--;
    while (r < rw - 1 && interior[y * rw + r + 1]) r++;
    return r - l >= 8 ? [l + 2, r - 2] : null;
  };
  for (const dir of [-1, 1]) for (let y = Math.round(cy); y >= 0 && y < rh; y += dir * passo) { const r = corre(y); if (!r) break; perfil.push([ry + y, rx + r[0], rx + r[1]]); }
  perfil.sort((a, b) => a[0] - b[0]);
  return { bg: hex(bg), ink: hex(inkRgb), lines, fontMax, covered, perfil, box: [Math.round(rx + cx - bw / 2), Math.round(ry + cy - bh / 2), Math.round(bw), Math.round(bh)] };
}

const upperRatio = (s) => { const l = s.replace(/[^\p{L}]/gu, ''); return l ? [...l].filter((c) => c === c.toUpperCase() && c !== c.toLowerCase()).length / l.length : 0; };

async function readJson(file) { return JSON.parse(await readFile(file, 'utf8')); }

// Balão cortado entre duas imagens: empilha as duas páginas (a de baixo logo depois da de cima, como no leitor), limpa
// o balão inteiro de uma vez e devolve cada metade para o patch da sua página. A caixa da tradução sai em coordenadas
// da página de cima e pode passar da borda dela (o leitor deixa o texto atravessar a emenda).
function cleanJoint({ A, B, bA, bB, patches }) {
  const rgb = Buffer.concat([A.rgb, B.rgb]);
  const stacked = new Uint8Array(A.W * (A.H + B.H) * 4);
  // 1 px de sobreposição na emenda para os dois polígonos formarem uma região só
  const polyA = bA.polygon.map(([x, y]) => [x, y >= A.H - 2 ? A.H + 1 : y]);
  const polyB = bB.polygon.map(([x, y]) => [x, A.H + (y <= 2 ? -1 : y)]);
  const x0 = Math.min(bA.bbox[0], bB.bbox[0]), x1 = Math.max(bA.bbox[0] + bA.bbox[2], bB.bbox[0] + bB.bbox[2]);
  const y0 = bA.bbox[1], y1 = A.H + bB.bbox[1] + bB.bbox[3];
  const c = cleanUnit({ rgb, W: A.W, H: A.H + B.H, polygons: [polyA, polyB], bbox: [x0, y0, x1 - x0, y1 - y0], patch: stacked }); // todo o texto do balão, inclusive a linha da emenda
  if (c.empty) return c;
  const row = A.W * 4;
  const pa = (patches.get(A.file) ?? patches.set(A.file, new Uint8Array(A.H * row)).get(A.file));
  const pb = (patches.get(B.file) ?? patches.set(B.file, new Uint8Array(B.H * row)).get(B.file));
  for (let y = 0; y < A.H + B.H; y++) {
    const dst = y < A.H ? pa : pb, base = (y < A.H ? y : y - A.H) * row;
    for (let i = 0; i < row; i += 4) if (stacked[y * row + i + 3]) for (let k = 0; k < 4; k++) dst[base + i + k] = stacked[y * row + i + k];
  }
  return c;
}

// Lê 3 (balões), 4a (tipo da região) e 4b (tradução). Não refaz OCR nem tradução. Grava em outDir:
// render.json (o que fazer em cada fala) e limpeza/<página>.png (pixels apagados).
export async function cleanChapter({ results3, ocrFile, translationFile, outDir, log = console.log }) {
  const results = await readJson(results3);
  const ocr = await readJson(ocrFile);
  const translation = await readJson(translationFile);
  const base = path.dirname(results3);
  const ocrById = new Map(ocr.pages.flatMap((p) => p.units).map((u) => [u.id, u]));
  const trByFile = new Map();
  for (const u of translation.units) trByFile.set(u.file, [...(trByFile.get(u.file) ?? []), u]);
  await mkdir(path.join(outDir, 'limpeza'), { recursive: true });
  const stats = { units: 0, cleaned: 0, joined: 0, tooltip: 0, flagged: 0, forced: 0 };

  const loaded = new Map(); // só as últimas páginas ficam na memória
  const load = async (page) => {
    if (!loaded.has(page.file)) {
      loaded.size > 2 && loaded.delete(loaded.keys().next().value);
      let r = null;
      if (!page.error && page.original) {
        const x = await sharp(path.resolve(base, page.original)).flatten({ background: '#fff' }).removeAlpha().raw().toBuffer({ resolveWithObject: true });
        if (x.info.width === page.width && x.info.height === page.height) r = { file: page.file, rgb: x.data, W: x.info.width, H: x.info.height };
      }
      loaded.set(page.file, r);
    }
    return loaded.get(page.file);
  };
  const patches = new Map(); // arquivo da página → RGBA; a página de baixo de um balão cortado recebe pixels antes da sua vez
  const pages = [];
  for (const [pi, page] of results.pages.entries()) {
    const out = { number: page.number, file: page.file, patch: null, units: [] };
    pages.push(out);
    for (const t of trByFile.get(page.file) ?? []) {
      stats.units++;
      const o = ocrById.get(t.id);
      const flag = t.status === 'erro' ? 'erro' : t.status === 'revisar' || o?.status === 'revisar' ? 'revisar' : 'ok';
      if (flag !== 'ok') stats.flagged++;
      const tooltip = (reason) => { stats.tooltip++; out.units.push({ id: t.id, mode: 'tooltip', flag, reason }); };
      if (t.status === 'copiado') { out.units.push({ id: t.id, mode: 'nenhum', flag }); continue; }
      if (t.status === 'erro' || !t.translation) { tooltip('erro'); continue; }
      // Toda fala com tradução aparece na imagem. Se a limpeza "bonita" não se aplica (balão cortado sem par, texto fora de
      // balão, balão sem tinta achada...), escreve mesmo assim sobre a região lida (cleanForce); o leitor deixa o texto vazar.
      const force = async (reason) => {
        const A = await load(page);
        const patch = A && (patches.get(page.file) ?? patches.set(page.file, new Uint8Array(A.W * A.H * 4)).get(page.file));
        const c = A && o?.bbox && cleanForce({ rgb: A.rgb, W: A.W, H: A.H, bbox: o.bbox, patch, lineHint: String(o.text ?? '').split('\n').filter(Boolean).length || 1 });
        if (!c || c.empty) return tooltip(reason);
        stats.cleaned++; stats.forced++;
        out.units.push({ id: t.id, mode: 'texto', flag, join: null, reason, box: c.box, bg: c.bg, ink: c.ink, stroke: c.stroke, fontMax: c.fontMax, lines: c.lines, upper: upperRatio(t.source) >= 0.8 });
      };
      if (o?.kind === 'free_text' && o.balloonId == null && legivel(o.text) && ['ok', 'revisar'].includes(o.status)) {
        // texto solto lido com confiança: escreve no lugar dele (fundo liso) ou sobre a arte (só texto de sobreposição)
        const A = await load(page);
        const patch = A && (patches.get(page.file) ?? patches.set(page.file, new Uint8Array(A.W * A.H * 4)).get(page.file));
        const c = A && cleanFree({ rgb: A.rgb, W: A.W, H: A.H, bbox: o.bbox, patch });
        if (c && !c.empty) {
          stats.cleaned++; stats.free = (stats.free ?? 0) + 1;
          out.units.push({ id: t.id, mode: 'texto', flag, join: null, box: c.box, bg: c.bg, ink: c.ink, stroke: c.stroke, fontMax: c.fontMax, lines: c.lines, upper: upperRatio(t.source) >= 0.8 });
          continue;
        }
        await force(c?.reason ?? 'fora-de-balao'); continue;
      }
      if (!o || !['balloon', 'narration'].includes(o.kind) || o.balloonId == null) { await force('fora-de-balao'); continue; }
      const balloon = page.balloons.find((b) => b.id === o.balloonId);
      const A = await load(page);
      if (!balloon || !A) { await force('sem-balao'); continue; }
      let c, join = null;
      if (o.joinedWith) {
        // balão cortado: a outra metade tem de ser o balão da página seguinte, com a mesma largura
        const next = results.pages[pi + 1];
        const bId = o.joinedWith.balloonId ?? next?.texts?.find((x) => x.id === o.joinedWith.textId)?.balloonId;
        const bB = next?.number === o.joinedWith.page && (o.joinedWith.polygon ? { id: bId, polygon: o.joinedWith.polygon, bbox: o.joinedWith.bbox } : next.balloons.find((b) => b.id === bId));
        const B = bB && (await load(next));
        if (!B || B.W !== A.W) { await force('emenda'); continue; }
        c = cleanJoint({ A, B, bA: balloon, bB, patches });
        join = { file: next.file, balloonId: bB.id };
      } else {
        const patch = patches.get(page.file) ?? patches.set(page.file, new Uint8Array(A.W * A.H * 4)).get(page.file);
        c = cleanUnit({ rgb: A.rgb, W: A.W, H: A.H, polygon: balloon.polygon, bbox: o.bbox, patch });
      }
      if (c.empty) { await force('sem-tinta'); continue; }
      stats.cleaned++;
      if (join) stats.joined++;
      out.units.push({ id: t.id, mode: o.kind === 'narration' ? 'narracao' : 'balao', flag, join, box: c.box, perfil: c.perfil, bg: c.bg, ink: c.ink, fontMax: c.fontMax, lines: c.lines, upper: upperRatio(t.source) >= 0.8 });
    }
    // a página só recebe pixels de si mesma e da anterior; ao terminar esta, o patch dela está completo
    const patch = patches.get(page.file);
    if (patch && patch.some((v, i) => i % 4 === 3 && v)) {
      const A = await load(page);
      out.patch = `${page.base}.png`;
      await sharp(Buffer.from(patch.buffer), { raw: { width: A.W, height: A.H, channels: 4 } }).png({ compressionLevel: 9 }).toFile(path.join(outDir, 'limpeza', out.patch));
    }
    patches.delete(page.file);
    progresso({ etapa: 'etapa6', feitas: pi + 1, total: results.pages.length });
  }
  const doc = { generatedAt: new Date().toISOString(), stats, pages };
  await writeFile(path.join(outDir, 'render.json'), JSON.stringify(doc, null, 2));
  log(`${stats.units} falas: ${stats.cleaned} escritas (${stats.joined} balões cortados entre imagens, ${stats.free ?? 0} textos soltos, ${stats.forced} escritas à força), ${stats.tooltip} só com tooltip, ${stats.flagged} marcadas (revisar/erro) → ${path.join(outDir, 'render.json')}`);
  return doc;
}
