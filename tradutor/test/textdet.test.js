import test from 'node:test';
import assert from 'node:assert/strict';
import { fatias, dedupe, boxesFromMap } from '../src/vision/textdet.js';

test('fatias cobre a página inteira com sobreposição', () => {
  assert.deepEqual(fatias(1000), [[0, 1000]]);
  const f = fatias(5000);
  assert.equal(f[0][0], 0); assert.equal(f.at(-1)[1], 5000);
  f.slice(1).forEach((s, i) => assert.ok(s[0] < f[i][1]));
});
test('dedupe junta a mesma linha vista em duas fatias', () => {
  const r = dedupe([{ bbox: [10, 100, 80, 30], score: 0.9 }, { bbox: [10, 110, 80, 20], score: 0.8 }, { bbox: [200, 10, 50, 20], score: 0.7 }]);
  assert.equal(r.length, 2);
  assert.deepEqual(r[0].bbox, [10, 100, 80, 30]);
});
test('região de média 0.52 (letra estilizada) passa; 0.4 não', () => {
  const mk = (p) => { const w = 64, h = 64, m = new Float32Array(w * h); for (let y = 20; y < 36; y++) for (let x = 10; x < 50; x++) m[y * w + x] = p; return boxesFromMap(m, w, h, 1, 1, w, h); };
  assert.equal(mk(0.52).length, 1);
  assert.equal(mk(0.4).length, 0);
});
