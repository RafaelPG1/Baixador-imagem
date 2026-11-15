import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { buildView, writeView } from '../src/vision/translation-view.js';
import { writeFile } from 'node:fs/promises';

const page = (number, file, balloonIds = [1]) => ({
  number, file, original: `../orig/${file}`, width: 800, height: 1000,
  balloons: balloonIds.map((id) => ({ id, kind: 'balloon', certainty: 'alta', bbox: [0, 0, 10, 10], polygon: [[0, 0], [10, 0], [10, 10]], textIds: [id] })),
  texts: [],
});
const unit = (id, file, o = {}) => ({ id, page: 1, file, balloonId: 1, textIds: [1], bbox: [1, 2, 3, 4], source: 'HI', translation: 'OI', status: 'ok', mode: 'lote', batch: 1, glossary: [], ...o });
const base = { results: { pages: [page(1, 'a.webp'), page(2, 'b.webp', [1, 2]), { number: 3, file: 'c.webp', error: 'quebrada', balloons: [], texts: [] }] }, results3Dir: path.resolve('/x/etapa3'), outDir: path.resolve('/x/etapa4c') };

test('buildView: fala vai para a página do seu arquivo, na ordem da 4b, com ids e caixas originais', () => {
  const translation = { provider: 'P', units: [unit('b1', 'b.webp'), unit('a1', 'a.webp'), unit('b2', 'b.webp', { balloonId: 2, status: 'revisar' }), unit('x', 'a.webp', { status: 'erro', translation: null, error: 'falhou' })] };
  const v = buildView({ ...base, translation });
  assert.deepEqual(v.pages.map((p) => p.units.map((u) => u.id)), [['a1', 'x'], ['b1', 'b2'], []]);
  assert.deepEqual(v.pages[1].units.map((u) => u.order), [1, 3]);
  assert.deepEqual(v.pages[0].units[0].bbox, [1, 2, 3, 4]);
  assert.deepEqual(v.counts, { ok: 2, revisar: 1, erro: 1 });
  assert.equal(v.pages[0].units[1].error, 'falhou');
  assert.equal(v.pages[0].original, '../orig/a.webp'); // relativo à pasta da 4c
  assert.deepEqual(v.warnings, []);
});

test('buildView: página inexistente e balão inexistente viram aviso, sem sumir nem trocar de página', () => {
  const translation = { units: [unit('z', 'nao-existe.webp'), unit('q', 'a.webp', { balloonId: 9 })] };
  const v = buildView({ ...base, translation });
  assert.equal(v.warnings.length, 2);
  assert.match(v.warnings[0], /z/);
  assert.match(v.warnings[1], /balão 9/);
  assert.deepEqual(v.pages[0].units.map((u) => u.id), ['q']);
});

test('buildView: junta dados do OCR por id quando existem', () => {
  const ocr = { pages: [{ units: [{ id: 'a1', status: 'revisar', engine: 'Tesseract', confidence: 70, edited: false, joinedWith: { page: 2, textId: 1 } }] }] };
  const v = buildView({ ...base, translation: { units: [unit('a1', 'a.webp'), unit('a2', 'a.webp')] }, ocr });
  assert.equal(v.pages[0].units[0].ocr.joinedWith.page, 2);
  assert.equal(v.pages[0].units[1].ocr, null);
});

test('writeView: grava view.json (sem viewer); falta de arquivo dá erro claro', async () => {
  const dir = await mkdtemp(path.join(tmpdir(), 'v4c-'));
  const r3 = path.join(dir, 'etapa3', 'results.json');
  const tr = path.join(dir, 'traducao.json');
  await import('node:fs/promises').then((fs) => fs.mkdir(path.dirname(r3), { recursive: true }));
  await writeFile(r3, JSON.stringify(base.results));
  await writeFile(tr, JSON.stringify({ generatedAt: 't', units: [unit('a1', 'a.webp')] }));
  const out = path.join(dir, 'out');
  await writeView({ results3: r3, translationFile: tr, ocrFile: path.join(dir, 'sem-ocr.json'), outDir: out });
  const view = JSON.parse(await readFile(path.join(out, 'view.json'), 'utf8'));
  assert.equal(view.pages[0].units[0].id, 'a1');
  assert.deepEqual((await import('node:fs/promises').then((fs) => fs.readdir(out))), ['view.json']); // nada de viewer.html nem data.js
  await assert.rejects(writeView({ results3: r3, translationFile: path.join(dir, 'nao.json'), outDir: out }), /Não achei/);
});
