import { readFile, stat } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { listPages } from '../vision/pages.js';

// Capítulo = { id, imagesDir, outDir }. As imagens ficam onde o Baixador as guarda (obras/<Obra>/<Capítulo>/img/) e nunca
// são copiadas nem alteradas; tudo que o processamento gera vai para `outDir`.

// Etapas na ordem. Cada uma grava o seu arquivo principal na própria pasta: <outDir>/<pasta>/<arquivo>.
export const STAGES = [
  { id: 'etapa3', dir: 'etapa3', file: 'results.json', since: 1 },
  { id: 'etapa8', dir: 'etapa8', file: 'results.json', since: 4 },
  { id: 'etapa4a', dir: 'etapa4a', file: 'ocr.json', since: 4 },
  { id: 'etapa4b', dir: 'etapa4b', file: 'traducao.json', since: 4 },
  { id: 'etapa4c', dir: 'etapa4c', file: 'view.json', since: 4 },
  { id: 'etapa6', dir: 'etapa6', file: 'render.json', since: 4 },
  { id: 'leitor', dir: 'leitor', file: 'leitor.json', since: 4 },
];

// Sobe quando uma etapa muda de jeito que invalida resultados antigos. Cada etapa tem `since`: a versão a partir da qual o
// resultado dela vale. Capítulo feito por versão mais velha refaz só as etapas com `since` maior (a etapa 3 não é refeita);
// a 4b reaproveita o cache dos lotes que não mudaram.
export const PIPELINE_VERSION = 4;

// Assinatura das imagens (nome + tamanho): se mudar, os resultados guardados já não valem.
export async function imageSignature(pages) {
  const h = createHash('sha256');
  for (const p of pages) h.update(`${p.file}:${(await stat(p.path)).size}\n`);
  return h.digest('hex');
}

const readJson = async (file) => {
  try {
    return JSON.parse(await readFile(file, 'utf8'));
  } catch (err) {
    if (err.code === 'ENOENT') return null;
    throw err;
  }
};

export const manifestFile = (chapter) => path.join(chapter.outDir, 'manifest.json');

// Quais etapas estão prontas para as imagens de hoje. Pronta = manifest com a mesma assinatura + arquivo existente.
export async function chapterState(chapter) {
  const { pages, warnings } = await listPages(chapter.imagesDir);
  const signature = await imageSignature(pages);
  const manifest = await readJson(manifestFile(chapter));
  const valid = manifest?.signature === signature;
  const done = {};
  for (const s of STAGES) {
    const exists = await stat(path.join(chapter.outDir, s.dir, s.file)).then(() => true, () => false);
    const v = manifest?.stageVersions?.[s.id] ?? manifest?.version ?? 0; // versão com que a etapa foi feita
    done[s.id] = Boolean(valid && manifest.stages?.[s.id] && exists && v >= s.since);
  }
  return { pages, warnings, signature, manifest: valid ? manifest : null, done, processed: STAGES.every((s) => done[s.id]) };
}
