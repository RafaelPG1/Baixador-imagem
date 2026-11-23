import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { progresso } from '../progresso.js';
import { run as detect } from '../vision/run.js';
import { ocrChapter } from '../vision/ocr.js';
import { translateChapter } from '../vision/translate.js';
import { translateWeb } from '../vision/web.js';
import { writeView } from '../vision/translation-view.js';
import { cleanChapter } from '../vision/clean.js';
import { detectText } from '../vision/textstage.js';
import { PIPELINE_VERSION, STAGES, chapterState, manifestFile } from './chapters.js';

const REAL = { detect, refine: detectText, ocr: ocrChapter, translate: translateChapter, translateWeb, view: writeView, clean: cleanChapter };

// Roda as etapas 3, 8, 4a, 4b, 4c e 6 de um capítulo, cada uma na sua pasta (<outDir>/etapaX/), e monta o
// leitor.json consolidado em <outDir>/leitor/. Etapa já pronta (mesmas imagens) é pulada; `refazer` roda tudo.
// A 4b tem cache próprio por lote, então refazer não traduz de novo o que não mudou.
// `deps` existe para teste: troca as etapas por falsas.
// `ate: 'etapa4a'` para depois do OCR (motor "web": as falas são exportadas e a tradução volta de fora).
export async function processChapter(chapter, { engine, refazer = false, log = console.log, deps = REAL, ate = null } = {}) {
  const st = await chapterState(chapter);
  if (!st.pages.length) throw new Error(`Capítulo "${chapter.id}": nenhuma imagem com número no início do nome em ${chapter.imagesDir}.`);
  const out = chapter.outDir;
  const at = (stage) => path.join(out, stage.dir);
  const file = (stage) => path.join(at(stage), stage.file);
  const [s3, s8, s4a, s4b, s4c, s6, leitor] = STAGES;
  const manifest = { version: PIPELINE_VERSION, signature: st.signature, stages: st.manifest?.stages ?? {}, stageVersions: st.manifest?.stageVersions ?? {} };
  const save = async () => {
    await mkdir(out, { recursive: true });
    await writeFile(manifestFile(chapter), JSON.stringify({ ...manifest, updatedAt: new Date().toISOString() }, null, 2));
  };
  // etapa nova depois de uma alterada: tudo que vem depois deixa de valer
  let stale = refazer || !st.manifest;
  const step = async (stage, work) => {
    if (!stale && st.done[stage.id]) { progresso({ evento: 'etapa', etapa: stage.id, estado: 'pulada' }); return log(`[${chapter.id}] ${stage.id}: pronta, pulada`); }
    stale = true;
    log(`[${chapter.id}] ${stage.id}: processando...`);
    progresso({ evento: 'etapa', etapa: stage.id, estado: 'inicio' });
    await work();
    manifest.stages[stage.id] = new Date().toISOString();
    manifest.stageVersions[stage.id] = PIPELINE_VERSION;
    await save();
    progresso({ evento: 'etapa', etapa: stage.id, estado: 'fim' });
  };
  if (stale) { manifest.stages = {}; manifest.stageVersions = {}; }

  await step(s3, () => deps.detect(chapter.imagesDir, at(s3)));
  await step(s8, () => (deps.refine ?? detectText)(file(s3), at(s8), { log }));
  await step(s4a, () => deps.ocr(file(s8), at(s4a), { log }));
  if (ate === s4a.id) return { id: chapter.id, pages: st.pages.length, parcial: true };
  await step(s4b, () => (engine === 'web' ? deps.translateWeb ?? translateWeb : deps.translate)(file(s4a), at(s4b), { engine, log }));
  let view;
  await step(s4c, async () => {
    view = await deps.view({ results3: file(s8), translationFile: file(s4b), ocrFile: file(s4a), outDir: at(s4c) });
  });
  await step(s6, () => deps.clean({ results3: file(s8), ocrFile: file(s4a), translationFile: file(s4b), outDir: at(s6), log }));
  await step(leitor, async () => {
    view ??= JSON.parse(await readFile(file(s4c), 'utf8'));
    const render = JSON.parse(await readFile(file(s6), 'utf8'));
    const byId = new Map(render.pages.flatMap((r) => r.units).map((r) => [r.id, r]));
    const patchOf = new Map(render.pages.map((r) => [r.file, r.patch]));
    await mkdir(at(leitor), { recursive: true });
    // páginas, balões e falas com os ids originais; a imagem original é a do Baixador (img/<arquivo>), não é copiada
    const pages = view.pages.map(({ original, index, ...p }) => ({ ...p, patch: patchOf.get(p.file) ?? null, units: p.units.map((u) => ({ ...u, render: byId.get(u.id) ?? null })) }));
    await writeFile(file(leitor), JSON.stringify({ formato: 2, generatedAt: view.generatedAt, engine: view.engine ?? engine ?? null, provider: view.provider, counts: view.counts, warnings: view.warnings, pages }));
  });
  return { id: chapter.id, pages: st.pages.length };
}

