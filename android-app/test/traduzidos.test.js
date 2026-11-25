import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const T = createRequire(import.meta.url)('../www/traduzidos.js');
const cap = (rel, traduzido, incompleta = 0) => ({ rel, traduzido, incompleta });

test('estado separa concluído, parcial e só original', () => {
  assert.equal(T.estado(cap('a', true, 0)), 'concluido');
  assert.equal(T.estado(cap('a', true, 3)), 'incompleto');
  assert.equal(T.estado(cap('a', false, 0)), 'original');
});

test('plano de download: só concluídos; parcial e original ficam de fora', () => {
  const caps = [cap('c1', true), cap('c2', true, 2), cap('c3', false), cap('c4', true), cap('c5', true)];
  const locais = { c1: { traduzido: true, traducaoCompleta: true }, c4: { traduzido: true }, c5: { traduzido: false } };
  const off = T.plano(caps, locais, 'offline');
  assert.deepEqual(off.baixar.map((c) => c.rel), ['c4', 'c5']);        // c4: cópia antiga sem marca; c5: cópia só do original
  assert.deepEqual(off.jaNoCelular.map((c) => c.rel), ['c1']);
  assert.deepEqual(off.incompletos.map((c) => c.rel), ['c2']);
  assert.deepEqual(off.semTraducao.map((c) => c.rel), ['c3']);
  const zip = T.plano(caps, locais, 'zip');
  assert.deepEqual(zip.baixar.map((c) => c.rel), ['c1', 'c4', 'c5']);
});
