import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import sharp from 'sharp';
import { analyze, run } from '../src/vision/run.js';
import { detectPage, loadCv } from '../src/vision/detect.js';
import { listPages } from '../src/vision/pages.js';

// Página sintética sem fontes: balões = elipses com contorno preto; "letras" = retângulos pretos em linhas.
const letters = (x, y, cols, rows) => {
  let s = '';
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) s += `<rect x="${x + c * 16}" y="${y + r * 30}" width="10" height="18" fill="#111"/>`;
  return s;
};
const ellipse = (cx, cy, rx, ry) => `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="#fff" stroke="#000" stroke-width="4"/>`;
const BOXES = [[60, 60, 300, 180], [440, 300, 300, 180]]; // x, y, w, h de cada balão
async function fixture(file) {
  const [a, b] = BOXES;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#d9d9d9"/>
    ${ellipse(a[0] + 150, a[1] + 90, 150, 90)}${letters(a[0] + 80, a[1] + 55, 8, 3)}
    ${ellipse(b[0] + 150, b[1] + 90, 150, 90)}${letters(b[0] + 80, b[1] + 55, 8, 3)}
    <rect x="30" y="500" width="400" height="14" fill="#111"/></svg>`;
  await sharp(Buffer.from(svg)).png().toFile(file);
}
const iou = ([ax, ay, aw, ah], [bx, by, bw, bh]) => {
  const w = Math.min(ax + aw, bx + bw) - Math.max(ax, bx);
  const h = Math.min(ay + ah, by + bh) - Math.max(ay, by);
  const i = w > 0 && h > 0 ? w * h : 0;
  return i / (aw * ah + bw * bh - i);
};
const sha = async (f) => createHash('sha256').update(await readFile(f)).digest('hex');

test('ordem das páginas usa só os 3 primeiros dígitos; ignora e avisa o que foge da regra', async () => {
  const dir = await mkdtemp(path.join(tmpdir(), 'pages-'));
  for (const f of ['010_zeta.webp', '002_b.png', '002_a.png', '100_x.jpg', 'capa.png', 'notas.txt', '003.webp']) await writeFile(path.join(dir, f), 'x');
  const { pages, warnings } = await listPages(dir);
  assert.deepEqual(pages.map((p) => p.number), [2, 2, 3, 10, 100]);
  assert.ok(warnings.some((w) => w.includes('capa.png')));
  assert.ok(warnings.some((w) => w.includes('Número repetido 002')));
  assert.ok(!warnings.some((w) => w.includes('notas.txt')));
});

test('detecta os dois balões da página sintética e liga o texto a cada um', async () => {
  const dir = await mkdtemp(path.join(tmpdir(), 'vis-'));
  const file = path.join(dir, '001_a.png');
  await fixture(file);
  const page = await analyze(await loadCv(), file);
  assert.equal(page.balloons.length, 2);
  for (const box of BOXES) assert.ok(page.balloons.some((b) => iou(b.bbox, box) > 0.8), `sem balão em ${box}`);
  for (const b of page.balloons) {
    assert.ok(b.textIds.length >= 1);
    for (const id of b.textIds) assert.equal(page.texts[id - 1].balloonId, b.id);
  }
  assert.equal(page.texts.filter((t) => t.balloonId).length, page.texts.filter((t) => t.kind === 'balloon_text').length);
});

test('página sem balões não gera balões', async () => {
  const gray = Buffer.alloc(400 * 300, 120);
  const page = detectPage(await loadCv(), gray, 400, 300);
  assert.equal(page.balloons.length, 0);
});

test('run grava resultados e não altera os originais', async () => {
  const dir = await mkdtemp(path.join(tmpdir(), 'in-'));
  const out = await mkdtemp(path.join(tmpdir(), 'out-'));
  await fixture(path.join(dir, '002_b.png'));
  await fixture(path.join(dir, '001_a.png'));
  const before = await sha(path.join(dir, '001_a.png'));
  const res = await run(dir, out);
  assert.deepEqual(res.pages.map((p) => p.number), [1, 2]);
  assert.equal(res.originalsIntact, true);
  assert.equal(await sha(path.join(dir, '001_a.png')), before);
  const json = JSON.parse(await readFile(path.join(out, 'results.json'), 'utf8'));
  assert.equal(json.pages.length, 2);
  assert.deepEqual((await import('node:fs/promises').then((fs) => fs.readdir(out))).sort(), ['results.json']); // sem overlays de diagnóstico, sem viewer
});

test('linha de texto cortada pela emenda é completada nos dois lados sem duplicar', async () => {
  const dir = await mkdtemp(path.join(tmpdir(), 'seam-'));
  const out = await mkdtemp(path.join(tmpdir(), 'seam-out-'));
  const row = (y) => Array.from({ length: 10 }, (_, c) => `<rect x="${300 + c * 20}" y="${y}" width="12" height="30" fill="none" stroke="#111" stroke-width="4"/>`).join('');
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="800" height="760"><rect width="800" height="760" fill="#d9d9d9"/>
    ${row(335)}</svg>`; // linha de letras em y 335-365: a emenda (350) passa no meio (texto solto, sem balão)
  const whole = await sharp(Buffer.from(svg)).png().toBuffer();
  await sharp(whole).extract({ left: 0, top: 0, width: 800, height: 350 }).png().toFile(path.join(dir, '001_a.png'));
  await sharp(whole).extract({ left: 0, top: 350, width: 800, height: 410 }).png().toFile(path.join(dir, '002_b.png'));
  const res = await run(dir, out);
  const [a, b] = res.pages;
  const cut = a.texts.find((t) => t.continues === 'next');
  const rest = b.texts.find((t) => t.continues === 'prev');
  assert.ok(cut && rest, 'linha cortada não foi ligada');
  assert.ok(cut.bbox[1] + cut.bbox[3] <= a.height && rest.bbox[1] >= 0 && rest.bbox[1] + rest.bbox[3] <= b.height);
  assert.ok(cut.bbox[1] + cut.bbox[3] >= a.height - 1 && rest.bbox[1] <= 1, 'região não chega à emenda');
  assert.deepEqual(a.texts.map((t) => t.id), a.texts.map((_, i) => i + 1));
  assert.equal(a.texts.filter((t) => t.bbox[1] + t.bbox[3] >= a.height - 1).length, 1, 'texto duplicado na emenda');
});
