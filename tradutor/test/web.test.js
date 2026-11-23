import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { hashFonte, prepararTextos, situacao, translateWeb } from '../src/vision/web.js';
import { processChapter } from '../src/obra/pipeline.js';

const unit = (id, file, text, y = 0) => ({ id, page: 1, file, balloonId: 1, textIds: [], bbox: [0, y, 10, 10], text, status: 'ok' });
async function trabalho(units) {
  const work = await mkdtemp(path.join(tmpdir(), 'web-'));
  await mkdir(path.join(work, 'etapa4a'), { recursive: true });
  const ocrFile = path.join(work, 'etapa4a', 'ocr.json');
  await writeFile(ocrFile, JSON.stringify({ pages: [{ file: '001.png', units }] }));
  return { work, ocrFile, outDir: path.join(work, 'etapa4b') };
}
const importar = (work, codigo, textos, traducoes) => mkdir(path.join(work, 'web'), { recursive: true }).then(() => writeFile(path.join(work, 'web', 'importadas.json'),
  JSON.stringify({ codigo, traducoes: Object.fromEntries(Object.entries(traducoes).map(([id, t]) => [id, { t, h: textos.unidades.find((u) => u.id === id).hash }])) })));
const lerTextos = async (work) => JSON.parse(await readFile(path.join(work, 'web', 'textos.json'), 'utf8'));

test('prepararTextos lista só falas com letras, numa linha, com id, página e hash; o código é estável', async () => {
  const t = await trabalho([unit('p001-b1', '001.png', 'Hello\n  there', 0), unit('p001-b2', '001.png', '139', 50), unit('p001-b3', '001.png', 'Run!', 100)]);
  const a = await prepararTextos({ ocrFile: t.ocrFile, work: t.work });
  assert.equal(a.textos, 2);
  const textos = await lerTextos(t.work);
  assert.deepEqual(textos.unidades.map((u) => [u.id, u.arquivo, u.fonte]), [['p001-b1', '001.png', 'Hello there'], ['p001-b3', '001.png', 'Run!']]);
  assert.equal(textos.unidades[0].hash, hashFonte('Hello there'));
  const b = await prepararTextos({ ocrFile: t.ocrFile, work: t.work });
  assert.equal(b.codigo, a.codigo, 'mesmas falas: mesmo código');
  await writeFile(t.ocrFile, JSON.stringify({ pages: [{ file: '001.png', units: [unit('p001-b1', '001.png', 'Hello there changed')] }] }));
  assert.notEqual((await prepararTextos({ ocrFile: t.ocrFile, work: t.work })).codigo, a.codigo, 'falas mudaram: código novo');
});

test('situacao: só conta tradução do mesmo código e do mesmo texto; completo só com todas', async () => {
  const t = await trabalho([unit('p001-b1', '001.png', 'Hello', 0), unit('p001-b2', '001.png', 'Bye', 50)]);
  const p = await prepararTextos({ ocrFile: t.ocrFile, work: t.work });
  assert.equal(p.completo, false);
  const textos = await lerTextos(t.work);
  await importar(t.work, textos.codigo, textos, { 'p001-b1': 'Olá' });
  assert.deepEqual(await situacao(t.work), { importadas: 1, completo: false });
  await importar(t.work, 'outro-codigo', textos, { 'p001-b1': 'Olá', 'p001-b2': 'Tchau' });
  assert.deepEqual(await situacao(t.work), { importadas: 0, completo: false }, 'código de outra exportação é ignorado');
  await importar(t.work, textos.codigo, textos, { 'p001-b1': 'Olá', 'p001-b2': 'Tchau' });
  assert.deepEqual(await situacao(t.work), { importadas: 2, completo: true });
});

test('translateWeb liga a tradução à fala pelo ID (ordem não importa) e nunca usa tradução de texto que mudou', async () => {
  const t = await trabalho([unit('p001-b1', '001.png', 'Hello', 0), unit('p001-b2', '001.png', '139', 50), unit('p001-b3', '001.png', 'Bye', 100)]);
  await prepararTextos({ ocrFile: t.ocrFile, work: t.work });
  const textos = await lerTextos(t.work);
  await importar(t.work, textos.codigo, textos, { 'p001-b3': 'Tchau', 'p001-b1': 'Olá' });   // fora de ordem
  const doc = await translateWeb(t.ocrFile, t.outDir, { log: () => {} });
  const por = Object.fromEntries(doc.units.map((u) => [u.id, u]));
  assert.equal(por['p001-b1'].translation, 'Olá');
  assert.equal(por['p001-b3'].translation, 'Tchau');
  assert.equal(por['p001-b2'].status, 'copiado');
  assert.equal(por['p001-b1'].bbox[1], 0); assert.equal(por['p001-b3'].bbox[1], 100);   // posição da fala original
  assert.equal(doc.engine, 'web');
  // o texto da fala muda (ex.: correcoes.json): a tradução antiga não pode ser aplicada
  await writeFile(path.join(t.work, 'etapa4a', 'correcoes.json'), JSON.stringify({ 'p001-b1': 'Hello again' }));
  const doc2 = await translateWeb(t.ocrFile, t.outDir, { log: () => {} });
  const u1 = doc2.units.find((u) => u.id === 'p001-b1');
  assert.equal(u1.status, 'erro'); assert.equal(u1.translation, null);
  assert.equal(doc2.units.find((u) => u.id === 'p001-b3').translation, 'Tchau');
});

test('processChapter com ate:"etapa4a" para depois do OCR e não roda 4b/6', async () => {
  const dir = await mkdtemp(path.join(tmpdir(), 'cap-'));
  await mkdir(path.join(dir, 'img'), { recursive: true });
  await writeFile(path.join(dir, 'img', '001_a.webp'), 'x');
  const chapter = { id: 'cap', imagesDir: path.join(dir, 'img'), outDir: path.join(dir, 'traducao.nova') };
  const calls = [];
  const w = (n, f) => async (i, o) => { calls.push(n); await mkdir(o, { recursive: true }); await writeFile(path.join(o, f), '{}'); };
  const deps = { detect: w('3', 'results.json'), refine: w('8', 'results.json'), ocr: w('4a', 'ocr.json'), translate: async () => { calls.push('4b'); }, translateWeb: async () => { calls.push('web'); } };
  const r = await processChapter(chapter, { engine: 'web', deps, log: () => {}, ate: 'etapa4a' });
  assert.equal(r.parcial, true);
  assert.deepEqual(calls, ['3', '8', '4a']);
});
