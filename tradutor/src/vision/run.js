// Etapa 3: detecta balões e regiões de texto nas páginas de uma pasta. Não traduz, não faz OCR, não altera as imagens.
// Uso: node src/vision/run.js [pasta das páginas] [pasta de saída]
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import sharp from 'sharp';
import { detectPage, loadCv } from './detect.js';
import { listPages } from './pages.js';
import { bandRows, joinSeam, relinkEdgeTexts } from './seams.js';
import { progresso } from '../progresso.js';

const MAX_PIXELS = 3.5e6; // resolução de trabalho; acima disso a página é reduzida só para detectar
const sha = async (file) => createHash('sha256').update(await readFile(file)).digest('hex');

const scale = (page, k) => {
  if (k === 1) return page;
  const s = (v) => Math.round(v / k);
  for (const b of page.balloons) {
    b.bbox = b.bbox.map(s);
    b.polygon = b.polygon.map(([x, y]) => [s(x), s(y)]);
  }
  for (const t of page.texts) t.bbox = t.bbox.map(s);
  return page;
};

export async function analyze(cv, file) {
  const meta = await sharp(file).metadata();
  const w = meta.autoOrient?.width ?? meta.width;
  const h = meta.autoOrient?.height ?? meta.height;
  const k = Math.min(1, Math.sqrt(MAX_PIXELS / (w * h)));
  let img = sharp(file).flatten({ background: '#fff' }).greyscale();
  if (k < 1) img = img.resize(Math.round(w * k), Math.round(h * k), { kernel: 'area' });
  const { data, info } = await img.raw().toBuffer({ resolveWithObject: true });
  const page = detectPage(cv, data, info.width, info.height);
  scale(page, info.width / w);
  return { ...page, width: w, height: h };
}

export async function run(inDir, outDir) {
  const { pages, warnings } = await listPages(inDir);
  if (!pages.length) throw new Error(`Nenhuma imagem com número no início do nome em "${inDir}".`);
  const before = await Promise.all(pages.map((p) => sha(p.path)));
  await mkdir(outDir, { recursive: true });
  const cv = await loadCv();
  const analyzed = [];
  for (const [i, p] of pages.entries()) {
    const t0 = Date.now();
    try {
      analyzed.push({ page: await analyze(cv, p.path), ms: Date.now() - t0 });
    } catch (err) {
      analyzed.push({ error: String(err.message ?? err) });
    }
    progresso({ etapa: 'etapa3', feitas: i + 1, total: pages.length });
  }
  // texto cortado pela emenda entre páginas consecutivas: completa os dois lados
  const band = async (file, w, h, top) => {
    const rows = Math.min(h, bandRows(w));
    const raw = await sharp(file).flatten({ background: '#fff' }).greyscale()
      .extract({ left: 0, top: top ? 0 : h - rows, width: w, height: rows }).raw().toBuffer();
    return raw;
  };
  for (const a of analyzed) if (a.page) relinkEdgeTexts(a.page);
  let joined = 0;
  for (let i = 0; i + 1 < pages.length; i++) {
    const a = analyzed[i].page;
    const b = analyzed[i + 1].page;
    if (!a || !b || a.width !== b.width) continue;
    joined += joinSeam(cv, a, b, await band(pages[i].path, a.width, a.height, false), await band(pages[i + 1].path, b.width, b.height, true));
  }
  const results = [];
  for (const [i, p] of pages.entries()) {
    const num = String(p.number).padStart(3, '0');
    const base = `${num}_${i + 1}`;
    const { page, error, ms } = analyzed[i];
    let entry;
    try {
      if (error) throw new Error(error);
      entry = { number: p.number, file: p.file, original: path.relative(outDir, p.path).split(path.sep).join('/'), ...page, ms };
    } catch (err) {
      entry = { number: p.number, file: p.file, error: String(err.message ?? err), balloons: [], texts: [] };
    }
    entry.base = base;
    results.push(entry);
    console.log(`${num}  ${p.file}  ${entry.error ? `ERRO: ${entry.error}` : `${entry.balloons.length} balões, ${entry.texts.length} textos`}`);
  }
  if (joined) console.log(`\nTextos cortados na emenda e completados: ${joined}`);
  const after = await Promise.all(pages.map((p) => sha(p.path)));
  const intact = before.every((h, i) => h === after[i]);
  const out = { generatedAt: new Date().toISOString(), input: inDir, warnings, originalsIntact: intact, pages: results };
  await writeFile(path.join(outDir, 'results.json'), JSON.stringify(out, null, 2));
  for (const w of warnings) console.warn(`AVISO: ${w}`);
  console.log(`Originais intactos: ${intact ? 'sim' : 'NÃO (confira!)'}`);
  return out;
}
