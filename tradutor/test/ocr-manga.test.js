import test from 'node:test';
import assert from 'node:assert/strict';
import { fixWord, isWord } from '../src/ocr/lexicon.js';
import { readWords, hasText, toResult } from '../src/ocr/manga.js';
import { buildUnits } from '../src/vision/ocr.js';

const HEAD = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n';
const row = (conf, text) => `5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t${conf}\t${text}\n`;
const tsv = (...ws) => HEAD + ws.map(([c, t]) => row(c, t)).join('');

test('fixWord: troca confusões de letra, mas mantém palavra válida e nomes', () => {
  assert.equal(fixWord('W0RLD', 50), 'WORLD');
  assert.equal(fixWord('|', 50), 'I');
  assert.equal(fixWord('STRONG', 95), 'STRONG');
  assert.ok(isWord("DON'T"));
});

test('readWords: descarta fragmentos de contorno, guarda pontuação e "I"', () => {
  const w = readWords(tsv([40, 'ye'], [95, 'WAIT'], [90, '?!'], [80, 'I'], [30, 'x']));
  assert.deepEqual(w.map((x) => x.text), ['ye', 'WAIT', '?!', 'I']);
});

test('hasText / toResult: ruído vira "vazio"; texto com palavra desconhecida vira "revisar"', () => {
  assert.equal(toResult(readWords(tsv([60, 'LLLINTI'], [55, 'BN']))).status, 'vazio');
  assert.equal(hasText(readWords(tsv([95, 'HE'], [95, 'IS'], [95, 'STRONG']))), true);
  const r = toResult(readWords(tsv([95, 'HE'], [95, 'IS'], [95, 'STRONG'], [40, 'ZXQVN'])));
  assert.equal(r.status, 'revisar');
  assert.deepEqual(r.doubtful, ['ZXQVN']);
});

test('buildUnits: falas do mesmo balão viram uma unidade; emenda entre páginas une as duas metades', () => {
  const page = (number, texts) => ({ number, file: `${number}.png`, texts });
  const t = (id, balloonId, bbox, continues) => ({ id, balloonId, bbox, kind: balloonId ? 'balloon_text' : 'free_text', orientation: 'horizontal', continues });
  const pages = [
    page(1, [t(1, 1, [10, 10, 50, 20]), t(2, 1, [10, 40, 50, 20]), t(3, null, [100, 900, 60, 20], 'next')]),
    page(2, [t(1, null, [105, 0, 60, 15], 'prev')]),
  ];
  const units = buildUnits(pages);
  assert.equal(units.length, 2); // balão 1 (2 falas) + texto da emenda (1 unidade, sem duplicar)
  assert.deepEqual(units[0].textIds, [1, 2]);
  assert.equal(units[1].join.page, 2);
});

test('groupLines: linhas empilhadas viram um bloco; balões separados e alturas diferentes não se juntam', async () => {
  const { groupLines } = await import('../src/vision/ocr.js');
  const L = (x, y, w, h = 24) => ({ bbox: [x, y, w, h] });
  const g = groupLines([L(100, 100, 200), L(110, 130, 180), L(120, 160, 160), L(100, 400, 200), L(110, 430, 180), L(500, 100, 40, 6)]);
  assert.deepEqual(g.map((x) => x.length).sort(), [1, 2, 3]);
});

test('mergeOverlapping: pedaços que cresceram até o mesmo texto viram uma unidade só', async () => {
  const { mergeOverlapping } = await import('../src/vision/ocr.js');
  const u = (id, bbox) => ({ id, kind: 'free_text', pageIndex: 0, join: null, textIds: [id], bbox });
  const out = mergeOverlapping([u(1, [100, 100, 100, 50]), u(2, [105, 105, 95, 45]), u(3, [400, 100, 50, 20])]);
  assert.equal(out.length, 2);
  assert.deepEqual(out[0].textIds, [1, 2]);
});

test('mergeDetections: cobertas somem, parciais completam o texto, novas entram no balão ou como texto solto/efeito', async () => {
  const { mergeDetections } = await import('../src/vision/textmerge.js');
  const page = {
    height: 1280,
    balloons: [{ id: 1, kind: 'balloon', polygon: [[0, 0], [300, 0], [300, 200], [0, 200]] }],
    texts: [{ id: 1, kind: 'balloon_text', balloonId: 1, bbox: [50, 100, 120, 25] }, { id: 2, kind: 'free_text', bbox: [400, 500, 40, 25] }],
  };
  const d = (x, y, w, h, score = 0.9) => ({ bbox: [x, y, w, h], score });
  const { texts, stats } = mergeDetections(page, [
    d(50, 100, 120, 25), // já coberta
    d(50, 60, 120, 25), // linha de cima, dentro do balão → entra na fala do balão
    d(380, 495, 120, 35), // cobre o texto solto 2 e passa dele → ele cresce
    d(600, 900, 200, 90), // alta, fora de balão → efeito
    d(600, 700, 80, 30), // texto solto novo
    d(700, 300, 6, 6), // pequena demais
    d(650, 400, 80, 30, 0.3), // pouca confiança
  ]);
  assert.equal(stats.covered, 1);
  assert.equal(stats.extended, 1);
  assert.equal(stats.added, 3);
  assert.equal(stats.discarded, 2);
  const byBox = (x, y) => texts.find((t) => t.bbox[0] === x && t.bbox[1] === y);
  assert.equal(byBox(50, 60).kind, 'balloon_text');
  assert.equal(byBox(50, 60).balloonId, 1);
  assert.equal(byBox(600, 900).kind, 'sfx');
  assert.equal(byBox(600, 700).kind, 'free_text');
  assert.deepEqual(texts.find((t) => t.id === 2).bbox, [380, 495, 120, 35]);
  assert.equal(page.texts.length, 2); // a página original não é alterada
});

test('mergeDetections: linha acima de uma fala de balão cortado entra no balão mesmo fora do polígono; espinho não', async () => {
  const { mergeDetections } = await import('../src/vision/textmerge.js');
  const page = {
    balloons: [{ id: 1, kind: 'balloon', bbox: [100, -1, 260, 130], polygon: [[110, 40], [350, 40], [350, 120], [110, 120]] }],
    texts: [{ id: 1, kind: 'balloon_text', balloonId: 1, bbox: [160, 60, 150, 27] }],
  };
  const { texts } = mergeDetections(page, [{ bbox: [140, 5, 180, 27], score: 0.99 }, { bbox: [330, 2, 20, 12], score: 0.9 }]);
  assert.equal(texts.find((t) => t.bbox[1] === 5).balloonId, 1);
  assert.equal(texts.find((t) => t.bbox[0] === 330).balloonId, undefined); // sem alinhamento: texto solto
});

test('mergeDetections: texto solto alinhado com a fala de um balão é religado a ele', async () => {
  const { mergeDetections } = await import('../src/vision/textmerge.js');
  const page = {
    balloons: [{ id: 1, kind: 'balloon', bbox: [100, -1, 260, 130], polygon: [[110, 60], [350, 60], [350, 120], [110, 120]] }],
    texts: [{ id: 1, kind: 'balloon_text', balloonId: 1, bbox: [160, 60, 150, 27] }, { id: 2, kind: 'free_text', bbox: [140, 5, 180, 27] }, { id: 3, kind: 'free_text', bbox: [600, 5, 80, 27] }],
  };
  const { texts, stats } = mergeDetections(page, []);
  assert.equal(stats.attached, 1);
  assert.equal(texts.find((t) => t.id === 2).balloonId, 1);
  assert.equal(texts.find((t) => t.id === 3).balloonId, undefined);
});

test('mergeDetections: caixa do detector que esticaria demais uma fala de balão é ignorada', async () => {
  const { mergeDetections } = await import('../src/vision/textmerge.js');
  const page = { balloons: [{ id: 1, kind: 'balloon', polygon: [[0, 0], [500, 0], [500, 200], [0, 200]] }], texts: [{ id: 1, kind: 'balloon_text', balloonId: 1, bbox: [100, 50, 120, 25] }] };
  const { texts } = mergeDetections(page, [{ bbox: [60, 40, 260, 60], score: 0.9 }]);
  assert.deepEqual(texts[0].bbox, [100, 50, 120, 25]);
});
