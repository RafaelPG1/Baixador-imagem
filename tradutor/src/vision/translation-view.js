import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const posix = (p) => p.split(path.sep).join('/');

async function readJson(file, required = true) {
  try {
    return JSON.parse(await readFile(file, 'utf8'));
  } catch (err) {
    if (err.code === 'ENOENT' && !required) return null;
    throw new Error(err.code === 'ENOENT' ? `Não achei ${file}.` : `Não consegui ler ${file}: ${err.message}`);
  }
}

// Junta o resultado da Etapa 3 (páginas, balões, textos), a tradução da 4b e, se existir, a leitura da 4a, tudo por página.
// A ligação fala → página é pelo nome do arquivo; fala → balão pelo balloonId. O que não casar vira aviso, nunca é escondido.
export function buildView({ results, translation, ocr = null, results3Dir, outDir }) {
  const warnings = [];
  const ocrById = new Map((ocr?.pages ?? []).flatMap((p) => p.units).map((u) => [u.id, u]));
  const pages = results.pages.map((p, index) => ({
    index,
    number: p.number,
    file: p.file,
    error: p.error ?? null,
    original: p.original ? posix(path.relative(outDir, path.resolve(results3Dir, p.original))) : null,
    width: p.width,
    height: p.height,
    balloons: (p.balloons ?? []).map(({ id, kind, certainty, bbox, polygon }) => ({ id, kind, certainty, bbox, polygon })),
    units: [],
  }));
  const byFile = new Map(pages.map((p) => [p.file, p]));
  // translation.units já vem na ordem de leitura da 4b; a ordem dentro da página é mantida.
  for (const [order, u] of translation.units.entries()) {
    const page = byFile.get(u.file);
    if (!page) {
      warnings.push(`Fala ${u.id}: a página ${u.file} não está no resultado da Etapa 3.`);
      continue;
    }
    if (u.balloonId != null && !page.balloons.some((b) => b.id === u.balloonId)) warnings.push(`Fala ${u.id}: balão ${u.balloonId} não existe na página ${page.number}.`);
    const o = ocrById.get(u.id);
    page.units.push({
      id: u.id, order: order + 1, balloonId: u.balloonId, textIds: u.textIds, bbox: u.bbox,
      source: u.source, translation: u.translation, status: u.status, error: u.error ?? null, mode: u.mode, glossary: u.glossary ?? [],
      ocr: o ? { status: o.status, engine: o.engine, confidence: o.confidence, edited: o.edited, joinedWith: o.joinedWith } : null,
    });
  }
  const counts = translation.units.reduce((m, u) => ({ ...m, [u.status]: (m[u.status] ?? 0) + 1 }), {});
  return { generatedAt: translation.generatedAt, engine: translation.engine, provider: translation.provider, counts, warnings, pages };
}

export async function writeView({ results3, translationFile, ocrFile, outDir }) {
  const results = await readJson(results3);
  const translation = await readJson(translationFile);
  const ocr = await readJson(ocrFile, false);
  await mkdir(outDir, { recursive: true });
  const view = buildView({ results, translation, ocr, results3Dir: path.dirname(results3), outDir });
  await writeFile(path.join(outDir, 'view.json'), JSON.stringify(view));
  const n = view.pages.reduce((s, p) => s + p.units.length, 0);
  console.log(`${n} falas em ${view.pages.length} páginas${view.warnings.length ? `; ${view.warnings.length} aviso(s)` : ''}`);
  return view;
}
