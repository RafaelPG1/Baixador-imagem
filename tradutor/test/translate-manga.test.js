import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { TranslationError } from '../src/errors.js';
import { collectUnits, makeBatches, buildBatchText, parseBatch, translateBatch, translateChapter, glossaryMisses } from '../src/vision/translate.js';

const u = (id, text, y = 0, x = 0, extra = {}) => ({ id, page: 1, file: 'a.png', balloonId: 1, textIds: [1], bbox: [x, y, 50, 20], text, status: 'ok', ...extra });
const ocr = (...units) => ({ pages: [{ number: 1, file: 'a.png', units }] });
// Motor falso: devolve "PT:" + cada linha, preservando a numeração
const fake = (calls = []) => async (text) => {
  calls.push(text);
  return { translation: text.split('\n').map((l) => l.replace(/^(\[\d+\] )?/, '$1PT:')).join('\n') };
};

test('collectUnits: ordem de leitura, correção manual vence, região vazia e correção vazia saem', () => {
  const units = collectUnits(
    ocr(u('b', 'SECOND', 300), u('a2', 'RIGHT', 10, 200), u('a1', 'LEFT', 30, 10), u('v', '', 5, 0, { status: 'vazio' }), u('d', 'DROP ME', 400)),
    { b: 'FIXED', d: '' },
  );
  assert.deepEqual(units.map((x) => [x.id, x.source]), [['a1', 'LEFT'], ['a2', 'RIGHT'], ['b', 'FIXED']]);
});

test('makeBatches: tamanho, contexto das falas anteriores, nada pulado ou repetido; sem letras não vai ao motor', () => {
  const units = collectUnits(ocr(...Array.from({ length: 10 }, (_, i) => u(`u${i}`, `LINE ${i}`, i * 100)), u('n', '139', 2000)));
  const batches = makeBatches(units, { size: 4, context: 2 });
  assert.deepEqual(batches.map((b) => b.units.length), [4, 4, 2]);
  assert.deepEqual(batches[1].context.map((x) => x.id), ['u2', 'u3']);
  assert.deepEqual(batches.flatMap((b) => b.units.map((x) => x.id)), Array.from({ length: 10 }, (_, i) => `u${i}`));
  assert.equal(makeBatches(units, { maxChars: 10 }).every((b) => b.units.length >= 1), true);
});

test('parseBatch: aceita linha quebrada; rejeita falta, sobra e duplicata', () => {
  assert.deepEqual(parseBatch('[1] Oi\n[2] tudo\nbem?', 2), ['Oi', 'tudo bem?']);
  for (const bad of ['[1] Oi', '[1] Oi\n[2] a\n[3] b', '[1] Oi\n[1] Oi\n[2] a', '[1] Oi\n[2] ', 'só texto']) {
    assert.throws(() => parseBatch(bad, 2), (e) => e.code === 'BAD_BATCH', bad);
  }
});

test('translateBatch: associa cada tradução à fala certa (contexto descartado)', async () => {
  const [batch] = makeBatches(collectUnits(ocr(u('a', 'ONE', 0), u('b', 'TWO', 100), u('c', 'THREE', 200))), { size: 2, context: 1 });
  const [, second] = makeBatches(collectUnits(ocr(u('a', 'ONE', 0), u('b', 'TWO', 100), u('c', 'THREE', 200))), { size: 2, context: 1 });
  assert.equal(buildBatchText(second), '[1] TWO\n[2] THREE');
  const r = await translateBatch(batch, 'x', fake());
  assert.equal(r.mode, 'lote');
  assert.deepEqual(r.results, [{ id: 'a', translation: 'PT:ONE' }, { id: 'b', translation: 'PT:TWO' }]);
});

test('translateBatch: resposta inválida → cada fala sozinha, sem trocar traduções', async () => {
  const [batch] = makeBatches(collectUnits(ocr(u('a', 'ONE', 0), u('b', 'TWO', 100))));
  const fn = async (t) => ({ translation: t.includes('[1]') ? '[1] só uma' : `PT:${t}` });
  const r = await translateBatch(batch, 'x', fn);
  assert.equal(r.mode, 'individual');
  assert.deepEqual(r.results, [{ id: 'a', translation: 'PT:ONE' }, { id: 'b', translation: 'PT:TWO' }]);
});

test('translateBatch: fala que falha sozinha vira erro; Ollama fora do ar aborta', async () => {
  const [batch] = makeBatches(collectUnits(ocr(u('a', 'ONE', 0), u('b', 'TWO', 100))));
  const bad = async (t) => {
    if (t.includes('[1]')) return { translation: 'lixo' };
    if (t === 'TWO') throw new TranslationError('EMPTY_RESPONSE', 'vazio', 502);
    return { translation: 'UM' };
  };
  const r = await translateBatch(batch, 'x', bad);
  assert.equal(r.results[0].translation, 'UM');
  assert.match(r.results[1].error, /vazio/);
  await assert.rejects(translateBatch(batch, 'x', async () => { throw new TranslationError('UPSTREAM_UNREACHABLE', 'off', 502); }), (e) => e.code === 'UPSTREAM_UNREACHABLE');
});

test('glossaryMisses: marca fala que não usou o termo do glossário', () => {
  assert.deepEqual(glossaryMisses('THE JIANGHU IS BIG', 'O mundo é grande', { JIANGHU: 'Jianghu' }), ['JIANGHU']);
  assert.deepEqual(glossaryMisses('THE JIANGHU', 'O Jianghu', { JIANGHU: 'Jianghu' }), []);
});

test('translateChapter: grava traduções com ids originais e retoma pelo cache sem chamar o motor', async () => {
  const dir = await mkdtemp(path.join(tmpdir(), 'tr4b-'));
  const file = path.join(dir, 'ocr.json');
  await writeFile(file, JSON.stringify(ocr(u('a', 'HELLO', 0), u('b', 'WORLD', 100), u('n', '139', 200))));
  await writeFile(path.join(dir, 'correcoes.json'), JSON.stringify({ b: 'EARTH' }));
  const calls = [];
  const out = path.join(dir, 'out');
  const quiet = { engine: 'local', log() {}, translateFn: fake(calls) };
  const doc = await translateChapter(file, out, quiet);
  assert.deepEqual(doc.units.map((x) => [x.id, x.source, x.translation, x.status]), [['a', 'HELLO', 'PT:HELLO', 'ok'], ['b', 'EARTH', 'PT:EARTH', 'ok'], ['n', '139', '139', 'copiado']]);
  assert.equal(calls.length, 1);
  const again = await translateChapter(file, out, { ...quiet, translateFn: async () => { throw new Error('não deveria chamar'); } });
  assert.equal(again.stats.cached, 1);
  assert.equal((await readdir(path.join(out, 'cache'))).length, 1);
  assert.equal(JSON.parse(await readFile(path.join(out, 'traducao.json'), 'utf8')).units.length, 3);
});
