import test from 'node:test';
import assert from 'node:assert/strict';
import { applyEdits } from '../src/vision/translate.js';

test('edição manual vale sobre a tradução (inclusive fala com erro) e não mexe nas outras', () => {
  const r = applyEdits([{ id: 'a', translation: null, status: 'erro', error: 'x' }, { id: 'b', translation: 'x', status: 'revisar' }], { a: ' oi ', c: 'nada' });
  assert.deepEqual([r[0].translation, r[0].status, r[0].editada, r[0].glossary], ['oi', 'ok', true, []]);
  assert.deepEqual(r[1], { id: 'b', translation: 'x', status: 'revisar' });
});

test('sem edições ou com texto vazio: nada muda', () => {
  const u = [{ id: 'a', translation: 'x', status: 'ok' }];
  assert.deepEqual(applyEdits(u, {}), u);
  assert.deepEqual(applyEdits(u, { a: '   ' }), u);
  assert.deepEqual(applyEdits(u, null), u);
});
