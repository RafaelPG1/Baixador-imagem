import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const S = createRequire(import.meta.url)('../../web/compartilhado/sincronia.js');
const mem = () => { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k), get length() { return m.size; }, key: (i) => [...m.keys()][i] }; };

test('mais novo vence nos dois sentidos (posição, estado e lido)', () => {
  const st = mem(), h = S.criar(st);
  h.gravar({ posicoes: { 'O/1': { p: 5, n: 9, f: 0.2, t: 2000 } }, lidos: { 'O/1': { v: true, t: 2000 } }, estados: { O: { e: 'lendo', t: 2000 } } });
  st.setItem('lido:O/1', '1');
  h.mesclar({ posicoes: { 'O/1': { p: 1, n: 9, f: 0, t: 1000 }, 'O/2': { p: 3, n: 4, f: 0.5, t: 500 } }, lidos: { 'O/1': { v: false, t: 1500 } }, estados: { O: { e: 'quero', t: 1999 } } });
  const r = h.ler();
  assert.equal(r.posicoes['O/1'].p, 5);            // dado velho do notebook não sobrescreve
  assert.equal(r.posicoes['O/2'].p, 3);            // item novo entra
  assert.equal(r.estados.O.e, 'lendo');
  assert.equal(st.getItem('lido:O/1'), '1');
  h.mesclar({ lidos: { 'O/1': { v: false, t: 3000 } } });
  assert.equal(st.getItem('lido:O/1'), null);      // decisão mais nova vale e a lista (lido:) acompanha
});

test('lido: antigo sem data vai com t=1 e perde para decisão datada', () => {
  const st = mem(), h = S.criar(st);
  st.setItem('lido:O/7', '1');
  assert.equal(h.payload().lidos['O/7'].t, 1);
});

test('última leitura ignora capítulo terminado; sincronizar não roda em paralelo nem em rajada', async () => {
  const st = mem(), h = S.criar(st);
  h.gravar({ posicoes: { 'O/1': { p: 9, n: 9, f: 1, t: 9 }, 'O/2': { p: 2, n: 9, f: 0.1, t: 5 } }, lidos: {}, estados: {} });
  assert.equal(h.ultima().rel, 'O/2');
  let n = 0; const enviar = async () => { n++; return {}; };
  await Promise.all([h.sincronizar(enviar, true), h.sincronizar(enviar, true)]);
  assert.equal(n, 1);
  assert.equal(await h.sincronizar(enviar), null);
  assert.equal(n, 1);
});

test('estado inválido é recusado', () => {
  const h = S.criar(mem()); h.definirEstado('O', 'lixo'); assert.equal(h.estadoDaObra('O'), '');
  h.definirEstado('O', 'lendo'); assert.equal(h.estadoDaObra('O'), 'lendo');
});
