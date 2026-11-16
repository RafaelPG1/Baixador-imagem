// "Toda fala com tradução aparece na imagem": quando a limpeza bonita não se aplica, a tradução é escrita mesmo assim
// (cleanForce) e o leitor deixa o texto vazar do balão (fitFlexible).
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import sharp from 'sharp';
import { cleanForce } from '../src/vision/clean-free.js';
import { cleanChapter } from '../src/vision/clean.js';

const { fitText, fitFlexible } = createRequire(import.meta.url)('../../web/leitor/layout.js');
const W = 400, H = 300;
const paint = (rgb, x, y, w, h, c) => { for (let j = y; j < y + h; j++) for (let i = x; i < x + w; i++) rgb.set(c, (j * W + i) * 3); };
// "letras": barras finas (4 px) como os traços de uma fonte, em vez de retângulos maciços
const glyphs = (rgb, x, y, w, h, c) => { for (let i = 0; i < w; i += 8) paint(rgb, x + i, y, 4, h, c); };
const page = (bg) => { const rgb = new Uint8Array(W * H * 3); for (let i = 0; i < W * H; i++) rgb.set(bg, i * 3); return rgb; };
const alpha = (patch, x, y) => patch[(y * W + x) * 4 + 3];

test('cleanForce: fundo liso apaga só as letras, com a cor do fundo, e escolhe a cor da letra pelo contraste', () => {
  const rgb = page([250, 240, 200]);
  paint(rgb, 150, 140, 100, 12, [10, 10, 10]); paint(rgb, 160, 160, 80, 12, [10, 10, 10]);
  const patch = new Uint8Array(W * H * 4);
  const c = cleanForce({ rgb, W, H, bbox: [150, 140, 100, 32], patch });
  assert.equal(c.flat, true);
  assert.equal(c.bg, '#faf0c8');
  assert.equal(c.ink, '#000000');
  assert.equal(c.stroke, null);
  assert.equal(alpha(patch, 200, 145), 255); // letra apagada
  assert.equal(alpha(patch, 20, 20), 0); // longe do texto
  assert.equal(c.lines, 2);
  assert.equal(alpha(patch, 20, 20), 0);
  assert.ok(c.box[0] <= 150 && c.box[1] <= 140 && c.box[2] >= 100 && c.box[3] >= 32, 'a caixa cobre o texto lido, com folga');
});

test('cleanForce: texto claro sobre arte irregular também é apagado e escrito, com contorno', () => {
  const rgb = page([60, 90, 140]);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) rgb.set(x % 4 < 3 ? [60, 90, 140] : [170, 190, 220], (y * W + x) * 3); // arte listrada: fundo irregular
  glyphs(rgb, 150, 140, 100, 12, [255, 255, 255]); glyphs(rgb, 160, 160, 80, 12, [255, 255, 255]);
  const patch = new Uint8Array(W * H * 4);
  const c = cleanForce({ rgb, W, H, bbox: [150, 140, 100, 32], patch });
  assert.ok(!c.empty);
  assert.equal(c.flat, false);
  assert.equal(c.ink, '#ffffff'); // arte escura: letra clara
  assert.equal(c.stroke, '#000000'); // com contorno escuro para ler sobre a arte
  assert.equal(alpha(patch, 198, 145), 255, 'letra apagada');
  assert.equal(alpha(patch, 20, 20), 0);
});

test('cleanForce: região com dois fundos (arte + interior branco de balão) apaga só as letras e preserva o resto', () => {
  const rgb = page([70, 100, 150]);                                       // arte azul
  paint(rgb, 200, 100, 150, 100, [255, 255, 255]);                         // interior branco de um balão que não foi detectado
  glyphs(rgb, 215, 120, 110, 10, [0, 0, 0]); glyphs(rgb, 215, 150, 90, 10, [0, 0, 0]);   // 2 linhas de texto preto no branco
  const patch = new Uint8Array(W * H * 4);
  const c = cleanForce({ rgb, W, H, bbox: [150, 110, 250, 60], patch, lineHint: 2 }); // a região lida pegou arte + balão
  assert.ok(!c.empty);
  assert.equal(c.flat, false);
  assert.equal(alpha(patch, 265, 125), 255, 'letra apagada');
  assert.equal(alpha(patch, 265, 155), 255, 'letra da 2ª linha apagada');
  assert.equal(alpha(patch, 300, 140), 0, 'branco do balão entre as linhas preservado');
  assert.equal(alpha(patch, 170, 140), 0, 'arte ao lado preservada');
  assert.equal(c.ink, '#000000', 'letra escura: o fundo sob o texto é o branco do balão');
  assert.equal(c.stroke, '#ffffff', 'contorno claro');
});

test('cleanForce: sem letra achada cobre o retângulo do texto; região inválida ou enorme é a única que recusa', () => {
  const rgb = page([255, 255, 255]);
  const patch = new Uint8Array(W * H * 4);
  const c = cleanForce({ rgb, W, H, bbox: [100, 100, 80, 20], patch });
  assert.ok(!c.empty);
  assert.equal(alpha(patch, 140, 110), 255); // retângulo coberto (sistema antigo)
  assert.equal(alpha(patch, 140, 200), 0);
  assert.equal(cleanForce({ rgb, W, H, bbox: [10, 10, 2, 2], patch: new Uint8Array(W * H * 4) }).empty, true);
  assert.equal(cleanForce({ rgb, W, H, bbox: [0, 0, W, H], patch: new Uint8Array(W * H * 4) }).empty, true);
});

test('cleanForce: texto colado na borda da imagem não sai dela', () => {
  const rgb = page([255, 255, 255]);
  paint(rgb, 300, 286, 100, 14, [0, 0, 0]);
  const c = cleanForce({ rgb, W, H, bbox: [300, 286, 100, 14], patch: new Uint8Array(W * H * 4) });
  assert.ok(!c.empty);
  assert.ok(c.box[0] + c.box[2] <= W && c.box[1] + c.box[3] <= H, JSON.stringify(c.box));
});

const medida = (t, s) => t.length * s * 0.5;

test('fitFlexible: cabendo na caixa nada muda; sem caber, a caixa cresce antes de a letra encolher (e nunca sai da imagem)', () => {
  const curto = fitFlexible(medida, 'OI TUDO BEM', [100, 100, 200, 60], { fontMax: 30 });
  assert.deepEqual(curto.caixa, [100, 100, 200, 60]);
  assert.equal(curto.size, fitText(medida, 'OI TUDO BEM', [100, 100, 200, 60], { fontMax: 30 }).size);

  const longo = 'NÃO ACREDITO QUE VOCÊ FEZ ISSO COMIGO DEPOIS DE TUDO QUE EU FIZ POR VOCÊ';
  const caixa = [100, 100, 120, 40];
  const rigido = fitText(medida, longo, caixa, { fontMax: 30 });
  const flex = fitFlexible(medida, longo, caixa, { fontMax: 30 });
  assert.ok(flex.size > rigido.size, `${flex.size} > ${rigido.size}`);
  assert.ok(flex.caixa[2] > caixa[2] && flex.caixa[3] > caixa[3], 'a caixa cresceu');
  assert.ok(flex.caixa[2] <= caixa[2] * 2 + 1e-6 && flex.caixa[3] <= caixa[3] * 2 + 1e-6, 'no máximo o dobro');
  const cx = flex.caixa[0] + flex.caixa[2] / 2, cy = flex.caixa[1] + flex.caixa[3] / 2;
  assert.ok(Math.abs(cx - 160) < 1e-6 && Math.abs(cy - 120) < 1e-6, 'cresce a partir do centro');

  const naBorda = fitFlexible(medida, longo, [0, 0, 120, 40], { fontMax: 30, limites: [130, 50] });
  assert.ok(naBorda.caixa[0] >= 0 && naBorda.caixa[1] >= 0 && naBorda.caixa[0] + naBorda.caixa[2] <= 130 && naBorda.caixa[1] + naBorda.caixa[3] <= 50);
});

test('fitFlexible: caixa que já passa da imagem (balão cortado, texto atravessa a emenda) não é encolhida pelos limites', () => {
  const caixa = [100, 260, 120, 60]; // termina em y=320, a imagem tem 300 de altura
  const r = fitFlexible(medida, 'NÃO ACREDITO QUE VOCÊ FEZ ISSO COMIGO DEPOIS DE TUDO', caixa, { fontMax: 30, limites: [400, 300] });
  assert.ok(r.caixa[1] + r.caixa[3] >= 320 - 1e-6, JSON.stringify(r.caixa));
});

test('fitFlexible: texto absurdo ainda devolve algo desenhável (vaza no tamanho mínimo)', () => {
  const r = fitFlexible(medida, 'PALAVRA '.repeat(200), [10, 10, 30, 10], { fontMax: 30 });
  assert.ok(r.lines.length > 0 && r.size >= 8);
  assert.equal(r.overflow, true);
});

// ---- Etapa 6 completa: nenhuma fala com tradução fica só em tooltip
test('cleanChapter: balão sem par, sem balão, sem tinta e texto sobre a arte são escritos à força; só "erro" fica sem escrita', async () => {
  const dir = await mkdtemp(path.join(tmpdir(), 'force-'));
  const rgb = page([255, 255, 255]);
  paint(rgb, 20, 20, 120, 12, [0, 0, 0]);                                 // u1: texto preto sem balão detectado
  paint(rgb, 20, 60, 120, 12, [0, 0, 0]);                                 // u2: balão 99 não existe
  paint(rgb, 20, 100, 120, 12, [0, 0, 0]);                                // u3: balão cortado sem par
  paint(rgb, 200, 20, 150, 100, [90, 120, 170]);                          // arte
  paint(rgb, 220, 40, 100, 12, [210, 70, 60]);                            // u5: texto colorido sobre a arte
  await sharp(Buffer.from(rgb), { raw: { width: W, height: H, channels: 3 } }).png().toFile(path.join(dir, '001.png'));
  const balloon = { id: 1, polygon: [[20, 200], [140, 200], [140, 280], [20, 280]], bbox: [20, 200, 120, 80], kind: 'balloon' }; // balão vazio (sem tinta)
  const results = { pages: [{ number: 1, file: '001.png', base: '001', width: W, height: H, original: '001.png', balloons: [balloon], texts: [] }] };
  const unit = (id, over) => ({ id, kind: 'balloon', balloonId: null, bbox: [20, 20, 120, 12], text: 'TEXTO', status: 'ok', ...over });
  const ocr = { pages: [{ units: [
    unit('u1', { bbox: [20, 20, 120, 12] }),
    unit('u2', { bbox: [20, 60, 120, 12], balloonId: 99 }),
    unit('u3', { bbox: [20, 100, 120, 12], balloonId: 1, joinedWith: { page: 2, textId: 'x' } }),
    unit('u4', { bbox: [30, 210, 100, 20], balloonId: 1 }),
    unit('u5', { kind: 'free_text', bbox: [220, 40, 100, 12], text: 'WATCH OUT BEHIND YOU' }),
    unit('u6', { bbox: [20, 150, 50, 10] }),
  ] }] };
  const tr = (id, over) => ({ id, file: '001.png', source: 'TEXT', translation: 'TEXTO TRADUZIDO', status: 'ok', ...over });
  const translation = { units: [tr('u1'), tr('u2'), tr('u3'), tr('u4'), tr('u5'), tr('u6', { status: 'erro', translation: '' })] };
  const files = { r: path.join(dir, 'results.json'), o: path.join(dir, 'ocr.json'), t: path.join(dir, 'traducao.json') };
  await writeFile(files.r, JSON.stringify(results)); await writeFile(files.o, JSON.stringify(ocr)); await writeFile(files.t, JSON.stringify(translation));
  const outDir = path.join(dir, 'etapa6');
  const doc = await cleanChapter({ results3: files.r, ocrFile: files.o, translationFile: files.t, outDir, log() {} });
  const by = Object.fromEntries(doc.pages[0].units.map((u) => [u.id, u]));
  for (const id of ['u1', 'u2', 'u3', 'u4', 'u5']) {
    assert.equal(by[id].mode, 'texto', `${id}: ${JSON.stringify(by[id])}`);
    assert.ok(by[id].box.length === 4 && by[id].fontMax >= 10, id);
  }
  assert.deepEqual(['u1', 'u2', 'u3', 'u4', 'u5'].map((id) => by[id].reason), ['fora-de-balao', 'sem-balao', 'emenda', 'sem-tinta', 'sem-tinta']);
  assert.equal(by.u5.ink, '#ffffff'); // fundo médio-escuro: letra clara
  assert.equal(by.u6.mode, 'tooltip');
  assert.equal(by.u6.reason, 'erro');
  assert.equal(doc.stats.forced, 5);
  assert.ok((await stat(path.join(outDir, 'limpeza', '001.png'))).size > 0);
  const png = await sharp(path.join(outDir, 'limpeza', '001.png')).raw().toBuffer({ resolveWithObject: true });
  const a = (x, y) => png.data[(y * W + x) * 4 + 3];
  assert.equal(a(60, 26), 255, 'u1 apagado');
  assert.equal(a(60, 106), 255, 'u3 apagado');
  assert.equal(a(250, 46), 255, 'u5 apagado');
  assert.equal(a(380, 280), 0, 'o resto da página fica intacto');
});
