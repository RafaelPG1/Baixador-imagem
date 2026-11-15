import test from 'node:test';
import assert from 'node:assert/strict';
import { cleanUnit, dilate, erode, fillPolygon } from '../src/vision/clean.js';
import { createRequire } from 'node:module';

// O encaixe de texto é o mesmo código que o leitor do Baixador usa no navegador (web/leitor/layout.js).
const { fitText, wrap } = createRequire(import.meta.url)('../../web/leitor/layout.js');

const W = 400, H = 300;
const ellipse = (cx, cy, rx, ry, n = 48) => Array.from({ length: n }, (_, i) => [cx + rx * Math.cos((2 * Math.PI * i) / n), cy + ry * Math.sin((2 * Math.PI * i) / n)]);
const rect = (rgb, x, y, w, h, c) => { for (let j = y; j < y + h; j++) for (let i = x; i < x + w; i++) rgb.set(c, (j * W + i) * 3); };

// página: fundo azul, balão (cor própria) com contorno preto de 4 px e três "linhas de texto" (retângulos)
function scene({ balloon, text, outline = [0, 0, 0] }) {
  const rgb = new Uint8Array(W * H * 3);
  for (let i = 0; i < W * H; i++) rgb.set([120, 160, 220], i * 3);
  const poly = ellipse(200, 150, 150, 100);
  const fill = fillPolygon(poly, W, H);
  const inner = erode(fill, W, H, 4);
  for (let i = 0; i < W * H; i++) { if (inner[i]) rgb.set(balloon, i * 3); else if (fill[i]) rgb.set(outline, i * 3); }
  const lines = [[120, 120, 160, 12], [130, 145, 140, 12], [140, 170, 120, 12]];
  for (const l of lines) rect(rgb, ...l, text);
  return { rgb, poly, lines, bbox: [120, 120, 160, 62], inner: fillPolygon(poly, W, H), fill };
}

test('cleanUnit: apaga o texto com a cor real do balão, sem tocar no contorno nem fora do balão', () => {
  const { rgb, poly, lines, bbox, fill } = scene({ balloon: [255, 247, 214], text: [0, 0, 0] });
  const patch = new Uint8Array(W * H * 4);
  const r = cleanUnit({ rgb, W, H, polygon: poly, bbox, patch });
  assert.equal(r.bg, '#fff7d6');
  assert.equal(r.ink, '#000000');
  assert.equal(r.lines, 3);
  const safe = erode(fill, W, H, 3);
  let painted = 0;
  for (let i = 0; i < W * H; i++) if (patch[i * 4 + 3]) { painted++; assert.ok(safe[i], `pixel ${i} fora do interior do balão`); assert.deepEqual([...patch.slice(i * 4, i * 4 + 3)], [255, 247, 214]); }
  assert.ok(painted > 0);
  for (const [x, y, w, h] of lines) for (let j = y; j < y + h; j++) for (let i = x; i < x + w; i++) assert.equal(patch[(j * W + i) * 4 + 3], 255, `texto não coberto em ${i},${j}`);
  // a caixa da tradução cabe inteira no balão e contém o centro do texto
  const [bx, by, bw, bh] = r.box;
  for (const [x, y] of [[bx, by], [bx + bw, by], [bx, by + bh], [bx + bw, by + bh]]) assert.ok(safe[Math.min(H - 1, y) * W + Math.min(W - 1, x)], `canto ${x},${y} fora`);
  assert.ok(bw >= bbox[2] * 0.9 && bh >= bbox[3] * 0.9);
});

test('cleanUnit: balão escuro com texto claro (polaridade invertida)', () => {
  const { rgb, poly, bbox } = scene({ balloon: [32, 32, 40], text: [250, 250, 250], outline: [250, 250, 250] });
  const patch = new Uint8Array(W * H * 4);
  const r = cleanUnit({ rgb, W, H, polygon: poly, bbox, patch });
  assert.equal(r.bg, '#202028');
  assert.equal(r.ink, '#fafafa');
  assert.ok(patch.some((v, i) => i % 4 === 3 && v));
});

test('cleanUnit: sem texto no balão devolve empty e não pinta nada', () => {
  const { rgb, poly } = scene({ balloon: [255, 255, 255], text: [255, 255, 255] });
  const patch = new Uint8Array(W * H * 4);
  assert.equal(cleanUnit({ rgb, W, H, polygon: poly, bbox: [120, 120, 160, 62], patch }).empty, true);
  assert.ok(patch.every((v) => v === 0));
});

test('dilate/erode: crescem e encolhem na medida certa', () => {
  const m = new Uint8Array(25); m[12] = 1;
  assert.equal(dilate(m, 5, 5, 1).reduce((a, b) => a + b), 9);
  assert.equal(erode(dilate(m, 5, 5, 1), 5, 5, 1).reduce((a, b) => a + b), 1);
});

// medida falsa: 10 px por letra por 10 px de tamanho de fonte (largura = letras × tamanho)
const measure = (t, size) => t.length * size;

test('fitText: escolhe o maior tamanho que cabe e quebra em linhas centradas na caixa', () => {
  const f = fitText(measure, 'um texto bem comprido para caber', [0, 0, 200, 100], { fontMax: 40, fontMin: 8 });
  assert.ok(f.size > 8 && f.size <= 40 && !f.overflow);
  assert.ok(f.lines.length >= 2);
  for (const l of f.lines) assert.ok(measure(l, f.size) <= 200);
  assert.ok(f.lines.length * f.size * f.lineHeight <= 100);
  assert.equal(f.lines.join(' '), 'um texto bem comprido para caber'); // nada perdido, nada repetido
  assert.equal(fitText(measure, 'oi', [0, 0, 200, 100], { fontMax: 20 }).size, 20); // não passa do máximo
});

test('fitText: palavra gigante reduz a fonte; texto impossível sinaliza overflow no tamanho mínimo', () => {
  const f = fitText(measure, 'incompreensivelmente', [0, 0, 100, 100], { fontMax: 40, fontMin: 4 });
  assert.ok(measure('incompreensivelmente', f.size) <= 100);
  const o = fitText(measure, 'muitas palavras num espaço minúsculo demais', [0, 0, 30, 10], { fontMax: 20, fontMin: 8 });
  assert.equal(o.overflow, true);
  assert.equal(o.size, 8);
  assert.deepEqual(wrap(measure, ['a', 'b'], 10, 1000), ['a b']);
});

test('cleanUnit: espinhos do contorno dentro do polígono não entram na caixa da tradução', () => {
  const { rgb, poly, bbox } = scene({ balloon: [255, 255, 255], text: [0, 0, 0] });
  // espinhos pretos de 30 px saindo do contorno para dentro, na altura do texto
  for (let y = 100; y < 200; y += 4) { rect(rgb, 52, y, 30, 2, [0, 0, 0]); rect(rgb, 318, y, 30, 2, [0, 0, 0]); }
  const c = cleanUnit({ rgb, W, H, polygon: poly, bbox: [60, 100, 280, 100], patch: new Uint8Array(W * H * 4) });
  assert.ok(c.box[0] >= 80 && c.box[0] + c.box[2] <= 320, `caixa ${c.box} invade os espinhos`);
});

test('balloonPairs: balão colado na base de A e no topo de B vira par; larguras diferentes não', async () => {
  const { balloonPairs } = await import('../src/vision/ocr.js');
  const A = { width: 800, height: 1000, balloons: [{ id: 1, bbox: [100, 900, 500, 100] }], texts: [{ balloonId: 1, kind: 'balloon_text' }] };
  const B = { width: 800, height: 1000, balloons: [{ id: 7, bbox: [110, 0, 480, 150] }], texts: [] };
  const p = balloonPairs([A, B]);
  assert.equal(p.get('0:1')?.balloon.id, 7);
  assert.equal(balloonPairs([A, { ...B, width: 700 }]).size, 0);
});

test('cleanFree: fundo liso é apagado com a cor do fundo; texto colorido sobre a arte fica como está', async () => {
  const { cleanFree } = await import('../src/vision/clean-free.js');
  const mk = (bg, text) => { const rgb = new Uint8Array(W * H * 3); for (let i = 0; i < W * H; i++) rgb.set(bg, i * 3); rect(rgb, 150, 140, 100, 12, text); rect(rgb, 160, 160, 80, 12, text); return rgb; };
  const flat = mk([255, 255, 255], [0, 0, 0]);
  const patch = new Uint8Array(W * H * 4);
  const c = cleanFree({ rgb: flat, W, H, bbox: [150, 140, 100, 32], patch });
  assert.equal(c.flat, true);
  assert.equal(patch[(145 * W + 200) * 4 + 3], 255); // pixel de letra apagado
  assert.equal(patch[(100 * W + 50) * 4 + 3], 0); // longe do texto, intacto
  const art = mk([60, 90, 140], [200, 60, 60]); // letra vermelha sobre arte azul: placa, não fala
  assert.equal(cleanFree({ rgb: art, W, H, bbox: [150, 140, 100, 32], patch: new Uint8Array(W * H * 4) }).empty, true);
});

test('lowerHalf: acha a metade de baixo de um balão fechado e recusa fundo aberto', async () => {
  const { lowerHalf } = await import('../src/vision/seam.js');
  const W2 = 300, HA = 100, HB = 200;
  const A = new Uint8Array(W2 * HA).fill(255);
  const ball = { bbox: [50, 20, 200, 80], polygon: [[50, 90], [250, 90], [240, 100], [60, 100], [150, 20]] };
  const closed = new Uint8Array(W2 * HB).fill(255);
  for (let y = 0; y < HB; y++) for (let x = 0; x < W2; x++) if (y === 40 || x === 50 && y < 40 || x === 250 && y < 40) closed[y * W2 + x] = 0; // contorno fechado
  const half = lowerHalf(A, closed, W2, HA, HB, ball);
  assert.ok(half && half.bbox[3] <= 40 && half.bbox[3] > 30, JSON.stringify(half?.bbox));
  assert.equal(lowerHalf(A, new Uint8Array(W2 * HB).fill(255), W2, HA, HB, ball), null); // página branca: vaza
});

test('cleanUnit: texto encostado na borda da imagem fora do polígono do balão também é apagado', () => {
  const { rgb } = scene({ balloon: [255, 255, 255], text: [0, 0, 0] });
  const poly = ellipse(200, 20, 150, 60).filter(([, y]) => y >= 14); // polígono "comeu" o topo, onde o texto toca a borda
  rect(rgb, 100, 0, 200, 60, [255, 255, 255]); // balão branco colado no topo
  rect(rgb, 130, 0, 140, 12, [0, 0, 0]); // linha de texto na borda superior (y 0..11)
  rect(rgb, 130, 30, 140, 12, [0, 0, 0]);
  const patch = new Uint8Array(W * H * 4);
  const r = cleanUnit({ rgb, W, H, polygon: poly, bbox: [130, 0, 140, 42], patch });
  assert.ok(!r.empty);
  for (const y of [1, 5, 10, 35]) assert.equal(patch[(y * W + 200) * 4 + 3], 255, `linha y=${y} não apagada`);
});
