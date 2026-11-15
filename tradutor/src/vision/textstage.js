// Etapa 8 como estágio do capítulo: lê a saída da Etapa 3, roda o detector de texto em cada página e grava, em pasta própria,
// um results.json com o mesmo formato (mais os textos que faltavam). As etapas seguintes leem este arquivo. A Etapa 3 e o
// original ficam intactos. Sem o modelo instalado, o arquivo sai igual ao da Etapa 3 (detector: null).
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { progresso } from '../progresso.js';
import sharp from 'sharp';
import { createTextDetector } from './textdet.js';
import { mergeDetections } from './textmerge.js';

export async function detectText(results3, outDir, { detector, log = console.log } = {}) {
  const results = JSON.parse(await readFile(results3, 'utf8'));
  const base = path.dirname(results3);
  detector = detector === undefined ? await createTextDetector() : detector;
  if (!detector) log('Detector de texto (PP-OCRv4) não instalado: a Etapa 8 repete a detecção da Etapa 3.');
  const t0 = Date.now();
  const total = { detected: 0, covered: 0, extended: 0, added: 0, inBalloon: 0, discarded: 0, attached: 0 };
  const pages = [];
  try {
    for (const [i, p] of results.pages.entries()) {
      progresso({ etapa: 'etapa8', feitas: i, total: results.pages.length });
      if (!detector || p.error || !p.original) { pages.push(p); continue; }
      const { data, info } = await sharp(path.resolve(base, p.original)).flatten({ background: '#fff' }).removeAlpha().raw().toBuffer({ resolveWithObject: true });
      if (info.width !== p.width || info.height !== p.height) { pages.push(p); continue; }
      const { texts, stats } = mergeDetections(p, await detector.detect(data, info.width, info.height));
      for (const k of Object.keys(total)) total[k] += stats[k];
      pages.push({ ...p, texts, detection: stats });
    }
  } finally {
    await detector?.close?.();
  }
  await mkdir(outDir, { recursive: true });
  const doc = { ...results, generatedAt: new Date().toISOString(), source: path.relative(outDir, results3).split(path.sep).join('/'), detector: detector?.name ?? null, stats: { ...total, ms: Date.now() - t0 }, pages };
  await writeFile(path.join(outDir, 'results.json'), JSON.stringify(doc, null, 2));
  log(detector ? `${total.detected} regiões do detector: ${total.covered} já achadas, ${total.attached} soltos religados a um balão, ${total.extended} completaram texto existente, ${total.added} novas (${total.inBalloon} em balão), ${total.discarded} descartadas — ${((Date.now() - t0) / 1000).toFixed(1)} s` : 'Etapa 8 sem detector.');
  return doc;
}
