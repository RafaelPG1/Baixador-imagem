// Etapa 4a: lê o texto de cada região detectada na Etapa 3. Não traduz e não altera as páginas.
import { refineBlock } from './refine.js';
import { lowerHalf } from './seam.js';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import sharp from 'sharp';
import { createMangaReader } from '../ocr/manga.js';
import { isWord } from '../ocr/lexicon.js';
import { createPaddle } from '../ocr/paddle.js';
import { components, loadCv } from './detect.js';
import { erode, fillPolygon } from './clean.js';
import { progresso } from '../progresso.js';

const PAD = 3; // margem em volta do texto: mais que isso traz contorno do balão e piora a leitura (CER 11% → 6%)
const MAX_WIDTH = 2400;

const union = (boxes) => {
  const x = Math.min(...boxes.map((b) => b[0]));
  const y = Math.min(...boxes.map((b) => b[1]));
  return [x, y, Math.max(...boxes.map((b) => b[0] + b[2])) - x, Math.max(...boxes.map((b) => b[1] + b[3])) - y];
};
const overlapX = (a, b) => Math.min(a[0] + a[2], b[0] + b[2]) - Math.max(a[0], b[0]);

const BALLOON_TEXT = ['balloon_text', 'narration'];

// Balão cortado entre duas imagens: o de baixo de uma página encosta na borda inferior e o de cima da seguinte na
// borda superior, na mesma faixa horizontal. Devolve Map "índice:id do balão" → { index, balloon } (par da página seguinte).
// Só pareia balão que tenha texto na página de cima. Uma ligação por balão, a de maior sobreposição.
export function balloonPairs(pages) {
  const pairs = new Map();
  for (let i = 0; i + 1 < pages.length; i++) {
    const A = pages[i], B = pages[i + 1];
    if (!A.balloons?.length || !B.balloons?.length || A.width !== B.width) continue;
    const cand = [];
    for (const a of A.balloons) {
      if (a.bbox[1] + a.bbox[3] < A.height - 3 || !A.texts.some((t) => t.balloonId === a.id && BALLOON_TEXT.includes(t.kind))) continue;
      for (const b of B.balloons) {
        const o = overlapX(a.bbox, b.bbox);
        if (b.bbox[1] <= 2 && o >= 0.5 * Math.min(a.bbox[2], b.bbox[2])) cand.push({ a, b, o });
      }
    }
    const usedA = new Set(), usedB = new Set();
    for (const { a, b } of cand.sort((x, y) => y.o - x.o)) {
      if (usedA.has(a.id) || usedB.has(b.id)) continue;
      usedA.add(a.id); usedB.add(b.id);
      pairs.set(`${i}:${a.id}`, { index: i + 1, balloon: b });
    }
  }
  return pairs;
}

// Balão que termina na base da página, com fala, sem par na seguinte: tenta achar a metade de baixo na emenda e a
// acrescenta (em memória, com virtual: true) às balões da página seguinte, para o pareamento normal tratar.
export async function completePairs(pages, load) {
  const paired = balloonPairs(pages);
  const gray = async (i) => { const r = await (await load(i)).clone().greyscale().raw().toBuffer({ resolveWithObject: true }); return r; };
  for (let i = 0; i + 1 < pages.length; i++) {
    const A = pages[i], B = pages[i + 1];
    if (A.width !== B.width) continue;
    for (const a of A.balloons) {
      if (paired.has(`${i}:${a.id}`) || a.bbox[1] + a.bbox[3] < A.height - 3 || !A.texts.some((t) => t.balloonId === a.id && BALLOON_TEXT.includes(t.kind))) continue;
      if (B.balloons.some((b) => b.bbox[1] <= 2 && overlapX(a.bbox, b.bbox) > 0)) continue; // a seguinte já tem um balão ali
      const ga = await gray(i), gb = await gray(i + 1);
      const half = lowerHalf(ga.data, gb.data, ga.info.width, ga.info.height, gb.info.height, a);
      if (half) B.balloons.push({ id: 9000 + a.id, kind: 'balloon', certainty: 'baixa', virtual: true, ...half });
    }
  }
}

// Blocos de texto solto cuja caixa cresceu até se sobrepor (pedaços do mesmo texto) viram um só.
export function mergeOverlapping(units) {
  const out = [];
  for (const u of units) {
    const a = u.bbox;
    const twin = u.kind === 'free_text' && !u.join && out.find((o) => o.kind === 'free_text' && !o.join && o.pageIndex === u.pageIndex && Math.max(0, overlapX(o.bbox, a)) * Math.max(0, Math.min(o.bbox[1] + o.bbox[3], a[1] + a[3]) - Math.max(o.bbox[1], a[1])) > 0.4 * Math.min(o.bbox[2] * o.bbox[3], a[2] * a[3]));
    if (!twin) { out.push(u); continue; }
    twin.textIds = [...twin.textIds, ...u.textIds];
    twin.bbox = union([twin.bbox, a]);
  }
  return out;
}

// Texto solto (sem balão detectado: balão tracejado de pensamento, legenda sobre a arte) vem da Etapa 3 uma caixa por linha.
// Linhas empilhadas ou lado a lado, de mesma altura, formam um bloco só: uma fala lida e traduzida inteira.
export function groupLines(items) {
  const parent = items.map((_, i) => i);
  const root = (i) => (parent[i] === i ? i : (parent[i] = root(parent[i])));
  const near = ([ax, ay, aw, ah], [bx, by, bw, bh]) => {
    const h = Math.min(ah, bh);
    if (Math.max(ah, bh) > 2 * h || h < 6) return false;
    const gapY = Math.max(ay, by) - Math.min(ay + ah, by + bh);
    const gapX = Math.max(ax, bx) - Math.min(ax + aw, bx + bw);
    const ox = overlapX([ax, ay, aw, ah], [bx, by, bw, bh]);
    if (gapY <= 0.9 * h && gapY >= -0.5 * h && (ox >= 0.25 * Math.min(aw, bw) || Math.abs(ax + aw / 2 - bx - bw / 2) <= 0.35 * Math.max(aw, bw))) return true; // linha de baixo
    return gapY < -0.5 * h && gapX <= 1.5 * h; // mesma linha, pedaços separados
  };
  for (let i = 0; i < items.length; i++) for (let j = i + 1; j < items.length; j++) if (near(items[i].bbox, items[j].bbox)) parent[root(i)] = root(j);
  const groups = new Map();
  items.forEach((it, i) => groups.set(root(i), [...(groups.get(root(i)) ?? []), it]));
  return [...groups.values()].map((g) => g.sort((a, b) => a.bbox[1] - b.bbox[1] || a.bbox[0] - b.bbox[0]));
}

// Caixa "texto solto" que na verdade é a franja do contorno de um balão já lido (espinhos de grito): descarta.
const insideReadBalloon = (p, t) => {
  if (!p.balloons) return false;
  const cx = t.bbox[0] + t.bbox[2] / 2, cy = t.bbox[1] + t.bbox[3] / 2;
  return p.balloons.some((b) => cx >= b.bbox[0] && cx <= b.bbox[0] + b.bbox[2] && cy >= b.bbox[1] && cy <= b.bbox[1] + b.bbox[3] && p.texts.some((o) => o.balloonId === b.id && BALLOON_TEXT.includes(o.kind)));
};

// Unidades de leitura de uma página: uma por balão (todas as falas dentro dele, juntas) e uma por texto solto/efeito.
// Texto cortado pela emenda (continues "next"/"prev") vira uma unidade só, lida numa imagem costurada.
export function buildUnits(pages) {
  const units = [];
  const pairs = balloonPairs(pages);
  const inPair = new Set([...pairs].flatMap(([k, v]) => [k, `${v.index}:${v.balloon.id}`])); // balões que são metade de um balão cortado
  const shared = new Set(); // "página:textId" da metade que continua da página anterior (não vira unidade própria)
  for (const [i, p] of pages.entries()) {
    for (const t of p.texts) {
      if (t.continues !== 'next' || inPair.has(`${i}:${t.balloonId}`)) continue; // balão cortado já se junta pelo balão inteiro
      const next = pages[i + 1];
      const partner = next?.texts.filter((q) => q.continues === 'prev' && !inPair.has(`${i + 1}:${q.balloonId}`)).sort((a, b) => overlapX(b.bbox, t.bbox) - overlapX(a.bbox, t.bbox))[0];
      if (partner && overlapX(partner.bbox, t.bbox) > 0) {
        t.partner = { index: i + 1, text: partner };
        shared.add(`${i + 1}:${partner.id}`);
      }
    }
  }
  for (const [i, p] of pages.entries()) {
    const num = String(p.number).padStart(3, '0');
    const byBalloon = new Map();
    const loose = [];
    for (const t of p.texts) {
      if (shared.has(`${i}:${t.id}`)) continue;
      if ((p.balloons ?? []).some((b) => b.virtual && t.bbox[0] + t.bbox[2] / 2 >= b.bbox[0] && t.bbox[0] + t.bbox[2] / 2 <= b.bbox[0] + b.bbox[2] && t.bbox[1] + t.bbox[3] / 2 <= b.bbox[3])) continue; // pedaço do texto na metade de baixo achada na emenda
      if (t.kind === 'free_text' && !t.balloonId && !t.continues) { if (!insideReadBalloon(p, t)) loose.push(t); continue; }
      if (BALLOON_TEXT.includes(t.kind) && t.balloonId && [...pairs].some(([k, v]) => v.index === i && v.balloon.id === t.balloonId)) continue; // metade de baixo: vai na unidade da página de cima
      const solo = !t.balloonId || !['balloon_text', 'narration'].includes(t.kind);
      const key = solo ? `t${t.id}` : `b${t.balloonId}`;
      if (!byBalloon.has(key)) byBalloon.set(key, []);
      byBalloon.get(key).push(t);
    }
    for (const g of groupLines(loose.map((t) => ({ bbox: t.bbox, t })))) byBalloon.set(`t${Math.min(...g.map((x) => x.t.id))}`, g.map((x) => x.t));
    for (const [key, ts] of byBalloon) {
      const first = ts[0];
      const link = ts.find((t) => t.partner);
      const pair = key.startsWith('b') ? pairs.get(`${i}:${first.balloonId}`) : null;
      const lowerText = pair ? pages[pair.index].texts.find((t) => t.balloonId === pair.balloon.id && BALLOON_TEXT.includes(t.kind)) : null;
      units.push({
        id: `p${num}-${key}`,
        pageIndex: i,
        page: p.number,
        file: p.file,
        kind: key.startsWith('b') ? (first.kind === 'narration' ? 'narration' : 'balloon') : first.kind,
        balloonId: first.balloonId ?? null,
        textIds: ts.map((t) => t.id),
        detOnly: ts.every((t) => t.detector === 'det' && t.kind !== 'balloon_text' && t.kind !== 'narration'), // achado só pelo detector da Etapa 8
        bbox: union(ts.map((t) => t.bbox)),
        orientation: first.orientation,
        regionCertainty: first.certainty,
        join: pair
          ? { page: pages[pair.index].number, textId: lowerText?.id ?? null, balloonId: pair.balloon.id, bbox: pair.balloon.bbox, balloon: true, ...(pair.balloon.virtual ? { virtual: true, polygon: pair.balloon.polygon } : {}) }
          : link ? { page: pages[link.partner.index].number, textId: link.partner.text.id, bbox: link.partner.text.bbox } : null,
        joinIndex: pair ? pair.index : link ? link.partner.index : null,
      });
    }
  }
  // texto que continua da página anterior mas sem par na etapa de unidades mantém a unidade própria (ver "shared")
  return units;
}

const clampBox = ([x, y, w, h], W, H) => {
  const left = Math.max(0, x - PAD);
  const top = Math.max(0, y - PAD);
  return { left, top, width: Math.max(1, Math.min(W, x + w + PAD) - left), height: Math.max(1, Math.min(H, y + h + PAD) - top) };
};

// Balão cortado entre duas imagens: junta as duas metades (a de baixo logo depois da de cima) e apaga de branco tudo o que
// está fora do interior dos balões (contorno, rabinho, arte), então o recorte só tem texto, inclusive a linha que
// cai bem na emenda e que nenhuma das duas páginas detecta sozinha.
async function cropBalloonPair(unit, pages, load) {
  const A = pages[unit.pageIndex], B = pages[unit.joinIndex];
  const bA = A.balloons.find((b) => b.id === unit.balloonId);
  const bB = B.balloons.find((b) => b.id === unit.join.balloonId);
  const x0 = Math.max(0, Math.floor(Math.min(bA.bbox[0], bB.bbox[0])));
  const w = Math.min(A.width, Math.ceil(Math.max(bA.bbox[0] + bA.bbox[2], bB.bbox[0] + bB.bbox[2]))) - x0;
  const topA = Math.max(0, Math.floor(bA.bbox[1]));
  const grab = async (idx, top, bottom) => (await (await load(idx)).clone().extract({ left: x0, top, width: w, height: bottom - top }).greyscale().raw().toBuffer());
  const upH = A.height - topA, lowH = Math.min(B.height, Math.ceil(bB.bbox[1] + bB.bbox[3]));
  const data = Buffer.concat([await grab(unit.pageIndex, topA, A.height), await grab(unit.joinIndex, 0, lowH)]);
  const h = upH + lowH;
  // máscara do interior feita com as duas metades já empilhadas (1 px de sobreposição), senão a erosão abre uma faixa branca na emenda
  const polyA = bA.polygon.map(([x, y]) => [x - x0, (y >= A.height - 2 ? A.height + 1 : y) - topA]);
  const polyB = bB.polygon.map(([x, y]) => [x - x0, upH + (y <= 2 ? -1 : y)]);
  const filled = fillPolygon(polyA, w, h);
  fillPolygon(polyB, w, h).forEach((v, i) => { if (v) filled[i] = 1; });
  const inside = erode(filled, w, h, 3);
  for (let i = 0; i < data.length; i++) if (!inside[i]) data[i] = 255;
  let x1 = w, y1 = h, x2 = -1, y2 = -1;
  for (let i = 0; i < data.length; i++) if (data[i] < 140) { const x = i % w, y = (i / w) | 0; if (x < x1) x1 = x; if (x > x2) x2 = x; if (y < y1) y1 = y; if (y > y2) y2 = y; }
  const raw = sharp(data, { raw: { width: w, height: h, channels: 1 } });
  if (x2 < 0) return raw.png().toBuffer(); // sem tinta: devolve o recorte todo (a leitura sai vazia)
  const left = Math.max(0, x1 - PAD), top = Math.max(0, y1 - PAD);
  return raw.extract({ left, top, width: Math.min(w, x2 + PAD + 1) - left, height: Math.min(h, y2 + PAD + 1) - top }).png().toBuffer();
}

// Recorte da unidade em tons originais (uma região ou duas costuradas pela emenda).
export async function cropUnit(unit, pages, load) {
  const img = await load(unit.pageIndex);
  const meta = await img.metadata();
  if (!unit.join) return img.clone().extract(clampBox(unit.bbox, meta.width, meta.height)).png().toBuffer();
  if (unit.join.balloon) return cropBalloonPair(unit, pages, load);
  const other = await load(unit.joinIndex);
  const om = await other.metadata();
  const x0 = Math.min(unit.bbox[0], unit.join.bbox[0]);
  const x1 = Math.max(unit.bbox[0] + unit.bbox[2], unit.join.bbox[0] + unit.join.bbox[2]);
  const left = Math.max(0, x0 - PAD);
  const width = Math.min(meta.width, om.width, x1 + PAD) - left;
  const top = Math.max(0, unit.bbox[1] - PAD);
  const upper = await img.clone().extract({ left, top, width, height: meta.height - top }).png().toBuffer();
  const lowerH = Math.min(om.height, unit.join.bbox[1] + unit.join.bbox[3] + PAD);
  const lower = await other.clone().extract({ left, top: 0, width, height: lowerH }).png().toBuffer();
  const heights = [meta.height - top, lowerH];
  return sharp({ create: { width, height: heights[0] + heights[1], channels: 3, background: '#fff' } })
    .composite([{ input: upper, top: 0, left: 0 }, { input: lower, top: heights[0], left: 0 }])
    .png().toBuffer();
}

// Ajustes para o Tesseract: cinza, contraste, ampliação (letra pequena lê pior) e margem branca.
export async function prepare(png, boost = 0) {
  const meta = await sharp(png).metadata();
  const scale = Math.min(boost || (meta.height < 45 ? 3 : 2), MAX_WIDTH / meta.width);
  const { data, info } = await sharp(png).flatten({ background: '#fff' }).greyscale()
    .resize({ width: Math.max(1, Math.round(meta.width * scale)), kernel: 'lanczos3' }).raw().toBuffer({ resolveWithObject: true });
  // Esticar o contraste à mão (percentis 1–99, como o normalise do sharp): o .normalise() quebra no libvips do Windows
  // ("colourspace: parameter space not set").
  const hist = new Array(256).fill(0);
  for (const v of data) hist[v]++;
  const cut = (frac) => { let acc = 0; for (let i = 0; i < 256; i++) if ((acc += hist[i]) >= frac * data.length) return i; return 255; };
  const lo = cut(0.01), hi = Math.max(cut(0.99), lo + 1);
  const out = Buffer.from(data.map((v) => Math.max(0, Math.min(255, Math.round(((v - lo) * 255) / (hi - lo))))));
  return sharp(out, { raw: { width: info.width, height: info.height, channels: 1 } })
    .extend({ top: 24, bottom: 24, left: 24, right: 24, background: '#fff' }).png().toBuffer();
}

// Letra com contorno grosso sobre arte (preta com borda branca, ou branca com borda preta) confunde o Tesseract. Isola uma das
// cores: "dark" deixa só o escuro (letra preta), "light" só o claro (letra branca); o resto vira fundo branco.
export async function isolate(png, mode) {
  const { data, info } = await sharp(png).flatten({ background: '#fff' }).greyscale().raw().toBuffer({ resolveWithObject: true });
  const [lo, hi] = mode === 'dark' ? [60, 140] : [120, 200];
  const out = Buffer.from(data.map((l) => { const t = Math.max(0, Math.min(1, (l - lo) / (hi - lo))); return Math.round((mode === 'dark' ? t : 1 - t) * 255); }));
  return sharp(out, { raw: { width: info.width, height: info.height, channels: 1 } }).png().toBuffer();
}
// Fração de palavras (2+ letras) que existem em inglês: separa leitura de verdade de lixo com confiança alta.
const realWords = (text = '') => { const w = text.match(/[A-Za-z']{2,}/g) ?? []; return w.length ? w.filter((x) => isWord(x.toLowerCase())).length / w.length : 0; };
const believable = (r) => r.status === 'ok' || (realWords(r.text) >= 0.6 && (r.text.match(/[A-Za-z]/g) ?? []).length >= 3);
export const quality = (r) => (r.status === 'ok' ? 1000 : 0) + 600 * realWords(r.text) + 0.3 * (r.confidence ?? 0) - 20 * (r.doubtful?.length ?? 0);

// Balão só de reticências ("......"): o Tesseract não lê pontos. Vários pontos redondos do mesmo tamanho = "." repetido.
export async function readDots(cv, png) {
  const { data, info } = await sharp(png).flatten({ background: '#fff' }).greyscale().raw().toBuffer({ resolveWithObject: true });
  const gray = cv.matFromArray(info.height, info.width, cv.CV_8UC1, [...data]);
  const ink = new cv.Mat();
  cv.threshold(gray, ink, 128, 255, cv.THRESH_BINARY_INV);
  const { list } = components(cv, ink, 6);
  gray.delete();
  ink.delete();
  const round = list.every((c) => c.w / c.h > 0.7 && c.w / c.h < 1.4 && c.area / (c.w * c.h) > 0.55);
  const sizes = list.map((c) => Math.max(c.w, c.h));
  return list.length >= 2 && round && Math.max(...sizes) <= 1.8 * Math.min(...sizes) ? '.'.repeat(list.length) : '';
}

export async function ocrChapter(resultsFile, outDir, { reader = createMangaReader(), paddle, log = console.log } = {}) {
  const results = JSON.parse(await readFile(resultsFile, 'utf8'));
  const base = path.dirname(resultsFile);
  const pages = results.pages.filter((p) => !p.error);
  await mkdir(outDir, { recursive: true });
  let fixes = {};
  try {
    fixes = JSON.parse(await readFile(path.join(outDir, 'correcoes.json'), 'utf8'));
  } catch {} // sem correções ainda
  const cache = new Map();
  const load = async (i) => {
    if (!cache.has(i)) {
      cache.size > 3 && cache.delete(cache.keys().next().value); // só as últimas páginas ficam na memória
      cache.set(i, sharp(path.resolve(base, pages[i].original)).flatten({ background: '#fff' }));
    }
    return cache.get(i);
  };
  await completePairs(pages, load);
  let units = buildUnits(pages);
  paddle ??= await createPaddle();
  if (!paddle) log('Segundo OCR (PaddleOCR) não instalado: leitura só com Tesseract.');
  const cv = await loadCv();
  const t0 = Date.now();
  let peak = 0;
  const out = [];
  try {
    // texto solto: completa a caixa se a Etapa 3 só achou pedaços, e junta blocos que passaram a ser o mesmo texto
    let gray = { index: -1 };
    for (const u of units) {
      if (u.kind !== 'free_text' || u.join) continue;
      if (gray.index !== u.pageIndex) { const r = await (await load(u.pageIndex)).clone().greyscale().raw().toBuffer({ resolveWithObject: true }); gray = { index: u.pageIndex, data: r.data, W: r.info.width, H: r.info.height }; }
      u.bbox = refineBlock(gray.data, gray.W, gray.H, u.bbox);
    }
    units = mergeOverlapping(units);
    for (const u of units) {
      const t1 = Date.now();
      const crop = await cropUnit(u, pages, load);
      let r = await reader.read(await prepare(crop));
      r.engine = 'Tesseract';
      let triedPaddle = false;
      if (u.kind === 'free_text' && r.status !== 'ok') { // texto solto duvidoso: variantes que isolam a cor da letra + Paddle; fica a leitura com mais palavras reais
        for (const mode of ['dark', 'light']) {
          const alt = await reader.read(await prepare(await isolate(crop, mode)));
          alt.engine = 'Tesseract';
          if (believable(alt) && quality(alt) > quality(r)) r = alt;
        }
        const alt = await paddle?.read(crop);
        triedPaddle = true;
        if (alt?.text) { const p = { text: alt.text, status: 'revisar', confidence: alt.confidence, doubtful: [], engine: paddle.name }; if (believable(p) && quality(p) > quality(r)) r = p; }
      }
      if (r.status === 'vazio') {
        const dots = await readDots(cv, crop);
        const alt = dots || triedPaddle ? null : await paddle?.read(crop);
        if (dots) Object.assign(r, { text: dots, status: 'revisar', confidence: 0, doubtful: [dots], engine: 'pontos' });
        else if (alt?.text) Object.assign(r, { text: alt.text, status: 'revisar', confidence: alt.confidence, doubtful: [], engine: paddle.name });
      }
      if (u.kind === 'free_text' && r.status !== 'ok' && (r.text.match(/[A-Za-z]/g) ?? []).length <= 3 && realWords(r.text) < 0.6) r = { text: '', status: 'vazio', confidence: 0, doubtful: [], engine: r.engine }; // 'roo', 'ANE': ruído, não texto
      if (u.detOnly && r.status !== 'ok' && !(believable(r) && (r.confidence ?? 0) >= 55)) r = { text: '', status: 'vazio', confidence: 0, doubtful: [], engine: r.engine }; // região do detector sem texto legível: arte, não fala
      peak = Math.max(peak, process.memoryUsage().rss);
      const entry = {
        id: u.id, page: u.page, file: u.file, kind: u.kind, balloonId: u.balloonId, textIds: u.textIds, bbox: u.bbox, source: u.detOnly ? 'etapa8' : 'etapa3',
        orientation: u.orientation, joinedWith: u.join ? { page: u.join.page, textId: u.join.textId, ...(u.join.balloon ? { balloonId: u.join.balloonId } : {}), ...(u.join.virtual ? { polygon: u.join.polygon, bbox: u.join.bbox } : {}) } : null,
        text: r.text, ocrText: r.text, status: r.status, engine: r.engine, confidence: r.confidence, doubtful: r.doubtful ?? [], edited: false,
        ms: Date.now() - t1,
      };
      if (fixes[u.id] !== undefined) Object.assign(entry, { text: fixes[u.id], status: 'editado', edited: true });
      out.push(entry);
      progresso({ etapa: 'etapa4a', feitas: out.length, total: units.length });
    }
  } finally {
    await reader.close();
  }
  const byPage = results.pages.map((p) => ({ number: p.number, file: p.file, units: out.filter((o) => o.page === p.number && o.file === p.file) }));
  const stats = { units: out.length, ms: Date.now() - t0, peakRssMB: Math.round(peak / 1048576), byStatus: out.reduce((m, o) => ({ ...m, [o.status]: (m[o.status] ?? 0) + 1 }), {}) };
  const doc = { generatedAt: new Date().toISOString(), source: path.relative(outDir, resultsFile).split(path.sep).join('/'), stats, pages: byPage };
  await writeFile(path.join(outDir, 'ocr.json'), JSON.stringify(doc, null, 2));
  log(`${out.length} regiões lidas em ${(stats.ms / 1000).toFixed(1)} s; pico de memória ${stats.peakRssMB} MB; ${JSON.stringify(stats.byStatus)}`);
  return doc;
}
