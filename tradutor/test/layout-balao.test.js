import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const L = createRequire(import.meta.url)('../../web/leitor/layout.js');
const medir = (t, s) => t.length * s * 0.62; // largura fixa por letra: basta para testar o encaixe
const elipse = (cx, cy, rx, ry, tira = 6) => { const p = []; for (let y = Math.ceil(cy - ry + tira); y <= cy + ry - tira; y += 3) { const k = Math.sqrt(Math.max(0, 1 - ((y - cy) / ry) ** 2)); p.push([y, cx - (rx - tira) * k, cx + (rx - tira) * k]); } return p; };

test('fitBalao: cada linha cabe na largura do balão redondo na sua altura', () => {
  const perfil = elipse(150, 100, 100, 90);
  const r = L.fitBalao(medir, 'DUQUE, COMO ESTÁ SE SENTINDO? ESTÁ TUDO BEM?', [90, 50, 120, 100], { fontMax: 34, perfil });
  const lh = r.size * r.lineHeight, top = r.caixa[1] + r.caixa[3] / 2 - (lh * r.lines.length) / 2;
  r.lines.forEach((l, i) => {
    const y0 = top + i * lh, y1 = y0 + lh;
    const w = perfil.filter((f) => f[0] >= y0 - 1 && f[0] <= y1 + 1).reduce((m, f) => Math.min(m, 2 * Math.min(150 - f[1], f[2] - 150)), 1e9);
    assert.ok(medir(l, r.size) <= w + 0.5, `linha ${i} passa do balão`);
  });
  assert.ok(!r.overflow && r.size >= 34 * 0.55);
});

test('fitPagina: duas falas coladas não se sobrepõem', () => {
  const res = L.fitPagina(medir, [
    { texto: 'VOCÊS TAMBÉM NÃO SE MACHUCARAM EM LUGAR NENHUM', caixa: [20, 40, 260, 70], fonteMax: 30 },
    { texto: 'MAS IMAGINEI QUE ESTIVESSEM TERRIVELMENTE ASSUSTADOS', caixa: [20, 100, 260, 70], fonteMax: 30 },
  ], [300, 300]);
  assert.equal(L.colisoes(res.map((x) => L.retangulos(medir, x, 0))).length, 0);
});
