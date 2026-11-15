import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { chapterState, STAGES, PIPELINE_VERSION } from '../src/obra/chapters.js';
import { processChapter } from '../src/obra/pipeline.js';

// Capítulo no formato do Baixador: <capítulo>/img/001_x.webp; o trabalho vai para <capítulo>/traducao.nova.
async function capitulo(files = ['002_b.webp', '001_a.webp', '10_z.webp', 'notas.txt']) {
  const dir = await mkdtemp(path.join(tmpdir(), 'cap-'));
  await mkdir(path.join(dir, 'img'), { recursive: true });
  for (const f of files) await writeFile(path.join(dir, 'img', f), 'x');
  return { id: 'cap', imagesDir: path.join(dir, 'img'), outDir: path.join(dir, 'traducao.nova') };
}

test('imagens ordenadas pelo número do prefixo (2 antes de 10); arquivo sem número é ignorado', async () => {
  const chapter = await capitulo();
  const st = await chapterState(chapter);
  assert.deepEqual(st.pages.map((p) => p.file), ['001_a.webp', '002_b.webp', '10_z.webp']);
  assert.equal(st.processed, false);
});

const fakeDeps = (calls) => ({
  detect: async (i, o) => { calls.push('3'); await mkdir(o, { recursive: true }); await writeFile(path.join(o, 'results.json'), '{}'); },
  refine: async (i, o) => { calls.push('8'); await mkdir(o, { recursive: true }); await writeFile(path.join(o, 'results.json'), '{}'); },
  ocr: async (i, o) => { calls.push('4a'); await mkdir(o, { recursive: true }); await writeFile(path.join(o, 'ocr.json'), '{}'); },
  translate: async (i, o) => { calls.push('4b'); await mkdir(o, { recursive: true }); await writeFile(path.join(o, 'traducao.json'), '{}'); },
  clean: async ({ outDir }) => {
    calls.push('6');
    await mkdir(outDir, { recursive: true });
    await writeFile(path.join(outDir, 'render.json'), JSON.stringify({ pages: [{ file: '001_a.webp', patch: '001_1.png', units: [{ id: 'p001-b1', mode: 'balao', box: [0, 0, 5, 5] }] }] }));
  },
  view: async ({ outDir }) => {
    calls.push('4c');
    await mkdir(outDir, { recursive: true });
    const view = { generatedAt: 't', engine: 'local', provider: 'P', counts: { ok: 1 }, warnings: [], pages: [{ index: 0, number: 1, file: '001_a.webp', original: '../x', width: 10, height: 20, balloons: [], units: [{ id: 'p001-b1', translation: 'oi' }] }] };
    await writeFile(path.join(outDir, 'view.json'), JSON.stringify(view));
    return view;
  },
});

test('processChapter: roda as etapas em pastas separadas, pula as prontas e refaz tudo se as imagens mudam', async () => {
  const chapter = await capitulo(['001_a.webp']);
  const calls = [];
  const opts = { log() {}, deps: fakeDeps(calls) };
  await processChapter(chapter, opts);
  assert.deepEqual(calls, ['3', '8', '4a', '4b', '4c', '6']);
  for (const s of STAGES) assert.ok((await chapterState(chapter)).done[s.id], s.id);
  const leitor = JSON.parse(await readFile(path.join(chapter.outDir, 'leitor', 'leitor.json'), 'utf8'));
  assert.equal(leitor.formato, 2);
  assert.equal(leitor.engine, 'local');
  assert.equal(leitor.pages[0].original, undefined); // caminho de arquivo não vai para o leitor
  assert.equal(leitor.pages[0].units[0].translation, 'oi');
  assert.equal(leitor.pages[0].units[0].render.mode, 'balao'); // instruções da Etapa 6 ligadas à fala pelo id
  assert.equal(leitor.pages[0].patch, '001_1.png');

  calls.length = 0;
  await processChapter(chapter, opts);
  assert.deepEqual(calls, []); // tudo pronto

  await writeFile(path.join(chapter.imagesDir, '0002_n.png'), 'xx'); // capítulo ganhou uma imagem
  await processChapter(chapter, opts);
  assert.deepEqual(calls, ['3', '8', '4a', '4b', '4c', '6']);
});

test('processChapter: falha numa etapa guarda as anteriores e retoma dali', async () => {
  const chapter = await capitulo(['001_a.webp']);
  const calls = [];
  const deps = fakeDeps(calls);
  const ok = deps.translate;
  deps.translate = async () => { throw new Error('Ollama fora do ar'); };
  await assert.rejects(processChapter(chapter, { log() {}, deps }), /Ollama/);
  deps.translate = ok;
  calls.length = 0;
  await processChapter(chapter, { log() {}, deps });
  assert.deepEqual(calls, ['4b', '4c', '6']);
});

test('pasta sem imagem numerada é recusada com mensagem clara', async () => {
  const chapter = await capitulo(['notas.txt']);
  await assert.rejects(processChapter(chapter, { log() {}, deps: fakeDeps([]) }), /nenhuma imagem com número/);
});

test('capítulo feito por versão antiga refaz só as etapas novas ou mudadas, não a detecção da Etapa 3', async () => {
  assert.ok(PIPELINE_VERSION >= 4);
  const chapter = await capitulo(['001_a.webp']);
  const calls = [];
  const opts = { log() {}, deps: fakeDeps(calls) };
  await processChapter(chapter, opts);
  const mf = path.join(chapter.outDir, 'manifest.json');
  const m = JSON.parse(await readFile(mf, 'utf8'));
  delete m.stageVersions; m.version = 3; delete m.stages.etapa8; // como um manifest da versão 3 (sem etapa 8)
  await writeFile(mf, JSON.stringify(m));
  calls.length = 0;
  await processChapter(chapter, opts);
  assert.deepEqual(calls, ['8', '4a', '4b', '4c', '6']);
});
