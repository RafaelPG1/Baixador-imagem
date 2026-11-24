// Etapa 7: texto fora de balão detectado (pensamento em balão tracejado, fala solta sobre a arte). Mesmo contrato da
// Etapa 6: só gera pixels num patch transparente, nunca toca no original.
//  - fundo liso ao redor (balão tracejado, página branca): pinta a tinta com a cor do fundo, como nos balões;
//  - fundo de arte: só mexe se o texto for de sobreposição (branco ou preto com contorno) e preenche por difusão
//    das cores vizinhas; texto colorido dentro da cena (placas, logos) fica como está, só com tooltip.
import { dilate, bestBox } from './clean.js';
import { apagar } from './apagar.js';

const median = (a) => { const s = Float64Array.from(a).sort(); return s.length ? s[s.length >> 1] : 0; };
const hex = ([r, g, b]) => `#${[r, g, b].map((v) => Math.round(v).toString(16).padStart(2, '0')).join('')}`;
const lumaOf = (r, g, b) => (299 * r + 587 * g + 114 * b) / 1000;

// Preenche os pixels de `mask` (w×h) com a média das cores conhecidas vizinhas, camada por camada, e suaviza.
export function inpaint(rgb, w, h, mask) {
  const out = Float64Array.from(rgb);
  const known = Uint8Array.from(mask, (v) => (v ? 0 : 1));
  let todo = [];
  for (let i = 0; i < mask.length; i++) if (mask[i]) todo.push(i);
  const nb = (i) => [i % w ? i - 1 : -1, i % w < w - 1 ? i + 1 : -1, i >= w ? i - w : -1, i < w * (h - 1) ? i + w : -1];
  while (todo.length) {
    const layer = [], rest = [];
    for (const i of todo) {
      let n = 0; const s = [0, 0, 0];
      for (const j of nb(i)) if (j >= 0 && known[j]) { n++; for (let c = 0; c < 3; c++) s[c] += out[j * 3 + c]; }
      if (n) { layer.push([i, s.map((v) => v / n)]); } else rest.push(i);
    }
    if (!layer.length) break; // máscara sem nenhum pixel conhecido
    for (const [i, c] of layer) { known[i] = 1; for (let k = 0; k < 3; k++) out[i * 3 + k] = c[k]; }
    todo = rest;
  }
  for (let pass = 0; pass < 4; pass++) {
    const prev = Float64Array.from(out);
    for (let i = 0; i < mask.length; i++) {
      if (!mask[i]) continue;
      let n = 1; const s = [prev[i * 3], prev[i * 3 + 1], prev[i * 3 + 2]];
      for (const j of nb(i)) if (j >= 0) { n++; for (let c = 0; c < 3; c++) s[c] += prev[j * 3 + c]; }
      for (let c = 0; c < 3; c++) out[i * 3 + c] = s[c] / n;
    }
  }
  return out;
}


// Texto sobre arte: a máscara das letras cresce por traços vizinhos (acento, ponta, contorno fraco) para não sobrar fantasma.
// shortcut: 3 passadas, no máximo 6 px além da máscara; arte muito rendilhada perto do texto pode perder um pouco de detalhe.
function apagarLivre(reg, rw, rh, mask, zone) {
  const permitido = dilate(mask, rw, rh, 6); // cresce no máximo 6 px além das letras achadas
  const r = apagar({ reg, rw, rh, seed: mask, zone, permitido, protegido: new Uint8Array(rw * rh), passes: 3 });
  return r;
}

// Devolve { bg, ink, stroke, box, lines, fontMax, flat } ou { empty: true, reason }.
export function cleanFree({ rgb, W, H, bbox, patch }) {
  const [bx, by, bw, bh] = bbox;
  if (bw * bh > 0.25 * W * H || bw < 8 || bh < 8) return { empty: true, reason: 'tamanho' };
  const m = Math.max(10, Math.round(bh * 0.5)); // folga ao redor do bloco, onde também se procura o fundo
  const rx = Math.max(0, bx - m), ry = Math.max(0, by - m), rw = Math.min(W, bx + bw + m) - rx, rh = Math.min(H, by + bh + m) - ry;
  const px = (x, y) => ((ry + y) * W + rx + x) * 3;
  const luma = new Float64Array(rw * rh);
  for (let y = 0; y < rh; y++) for (let x = 0; x < rw; x++) { const o = px(x, y); luma[y * rw + x] = lumaOf(rgb[o], rgb[o + 1], rgb[o + 2]); }
  const tx0 = bx - rx, ty0 = by - ry; // caixa do texto na região
  const inBox = (x, y, g) => x >= tx0 - g && x < tx0 + bw + g && y >= ty0 - g && y < ty0 + bh + g;
  // fundo: anel de 4 a 9 px em volta da caixa
  const ring = [];
  for (let y = 0; y < rh; y++) for (let x = 0; x < rw; x++) if (inBox(x, y, 9) && !inBox(x, y, 3)) ring.push(y * rw + x);
  if (ring.length < 40) return { empty: true, reason: 'sem-fundo' };
  const bgRgb = [0, 1, 2].map((c) => median(ring.map((i) => rgb[px(i % rw, Math.floor(i / rw)) + c])));
  const bgL = lumaOf(...bgRgb);
  const dev = ring.map((i) => Math.abs(luma[i] - bgL)).sort((a, b) => a - b);
  const flat = dev[Math.floor(dev.length * 0.8)] < 18; // 80% do anel quase igual à mediana (tracejado do balão não conta)
  const textZone = new Uint8Array(rw * rh);
  for (let y = 0; y < rh; y++) for (let x = 0; x < rw; x++) if (inBox(x, y, 2)) textZone[y * rw + x] = 1;
  const ink = new Uint8Array(rw * rh);
  let nInk = 0, extreme = 0;
  for (let i = 0; i < ink.length; i++) {
    if (!textZone[i]) continue;
    const l = luma[i];
    if (flat ? Math.abs(l - bgL) > 60 : l >= 232 || l <= 35 || Math.abs(l - bgL) > 90) { ink[i] = 1; nInk++; if (l >= 232 || l <= 35) extreme++; }
  }
  if (nInk < 12) return { empty: true, reason: 'sem-tinta' };
  if (!flat && extreme < 0.5 * nInk) return { empty: true, reason: 'texto-da-cena' }; // colorido: placa, logo, roupa
  if (!flat && nInk > 0.6 * bw * bh) return { empty: true, reason: 'texto-da-cena' }; // fundo todo "claro/escuro": não é traço de letra
  const cover = dilate(ink, rw, rh, flat ? 3 : 4);
  const mask = cover.map((v, i) => (v && textZone[i] ? 1 : 0));
  if (flat) { // halo de compressão em volta das letras: diferença pequena do fundo, perto da tinta
    const near = dilate(ink, rw, rh, 7);
    for (let i = 0; i < mask.length; i++) if (!mask[i] && near[i] && textZone[i] && Math.abs(luma[i] - bgL) > 10) mask[i] = 1;
  }
  // linhas de texto (para o tamanho máximo da fonte): corridas de linhas com tinta. Com contorno grosso uma das cores
  // (a do contorno) é contínua entre as linhas; a outra (o miolo das letras) separa, então vale o maior número achado.
  const countLines = (isInk) => {
    const cnt = [];
    for (let y = 0; y < rh; y++) { let n = 0; for (let x = 0; x < rw; x++) if (textZone[y * rw + x] && isInk(y * rw + x)) n++; cnt.push(n); }
    const thr = 0.3 * Math.max(...cnt); // linha de texto = fileira com pelo menos 30% do máximo (ruído e traço inclinado ficam abaixo)
    const runs = [];
    cnt.forEach((n, y) => { if (n > 0 && n >= thr) (runs.length && runs[runs.length - 1][1] === y ? (runs[runs.length - 1][1] = y + 1) : runs.push([y, y + 1])); });
    if (!runs.length) return 0;
    const tall = Math.max(...runs.map(([a, b]) => b - a));
    return runs.reduce((acc, r) => (acc.length && r[0] - acc[acc.length - 1][1] < 0.25 * tall ? (acc[acc.length - 1][1] = r[1], acc) : [...acc, [...r]]), []).length;
  };
  const lines = flat ? countLines((i) => ink[i]) : Math.max(countLines((i) => luma[i] >= 232), countLines((i) => luma[i] <= 35), 1);
  let fontMax = Math.round(Math.min(80, Math.max(10, lines > 1 ? (bh / lines) * 0.95 : bh * 1.3)));

  let inkColor, stroke = null, box;
  if (flat) {
    for (let i = 0; i < mask.length; i++) if (mask[i]) { const o = ((ry + Math.floor(i / rw)) * W + rx + (i % rw)) * 4; patch[o] = bgRgb[0]; patch[o + 1] = bgRgb[1]; patch[o + 2] = bgRgb[2]; patch[o + 3] = 255; }
    const core = [...ink.keys()].filter((i) => ink[i]).sort((a, b) => (bgL >= 128 ? luma[a] - luma[b] : luma[b] - luma[a])).slice(0, Math.max(1, Math.floor(nInk * 0.4)));
    inkColor = [0, 1, 2].map((c) => median(core.map((i) => rgb[px(i % rw, Math.floor(i / rw)) + c])));
    // caixa: maior retângulo centrado no texto dentro do fundo liso que o cerca (para no tracejado do balão)
    const free = new Uint8Array(rw * rh);
    for (let i = 0; i < free.length; i++) free[i] = Math.abs(luma[i] - bgL) <= 30 || mask[i] ? 1 : 0;
    const cx = tx0 + bw / 2, cy = ty0 + bh / 2;
    const fits = (w, h) => {
      const x0 = Math.round(cx - w / 2), x1 = Math.round(cx + w / 2), y0 = Math.round(cy - h / 2), y1 = Math.round(cy + h / 2);
      if (x0 < 0 || y0 < 0 || x1 > rw || y1 > rh) return false;
      for (let x = x0; x < x1; x += 2) if (!free[y0 * rw + x] || !free[(y1 - 1) * rw + x]) return false;
      for (let y = y0; y < y1; y += 2) if (!free[y * rw + x0] || !free[y * rw + x1 - 1]) return false;
      return true;
    };
    const best = bestBox(fits, bw, bh, 1.3, 1.6);
    box = [Math.round(rx + cx - best.w / 2), Math.round(ry + cy - best.h / 2), Math.round(best.w), Math.round(best.h)];
  } else {
    const reg = new Uint8Array(rw * rh * 3);
    for (let y = 0; y < rh; y++) reg.set(rgb.subarray(px(0, y), px(0, y) + rw * 3), y * rw * 3);
    const ap = apagarLivre(reg, rw, rh, mask, textZone);
    for (let i = 0; i < ap.mask.length; i++) if (ap.mask[i]) { const o = ((ry + Math.floor(i / rw)) * W + rx + (i % rw)) * 4; for (let c = 0; c < 3; c++) patch[o + c] = Math.round(ap.fill[i * 3 + c]); patch[o + 3] = 255; }
    const light = bgL < 128; // sobre arte escura: letra branca com contorno escuro; sobre clara, o contrário
    inkColor = light ? [255, 255, 255] : [0, 0, 0];
    stroke = light ? '#000000' : '#ffffff';
    fontMax = Math.min(fontMax, Math.round(0.5 * bh)); // sem saber as linhas ao certo, não deixa a fonte passar de metade da altura
    const gx = Math.round(bw * 0.1), gy = Math.round(bh * 0.1);
    box = [Math.max(0, bx - gx), Math.max(0, by - gy), Math.min(W, bw + 2 * gx), Math.min(H, bh + 2 * gy)];
  }
  return { bg: hex(bgRgb), ink: hex(inkColor), stroke, box, lines, fontMax, flat };
}

// ---- filtros de mínimo/máximo (separáveis) para achar traços finos: black-hat (letra escura) e top-hat (letra clara)
function filtro(src, w, h, k, pick) {
  const r = k >> 1, tmp = new Float64Array(w * h), out = new Float64Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    let v = src[y * w + x];
    for (let i = Math.max(0, x - r); i <= Math.min(w - 1, x + r); i++) v = pick(v, src[y * w + i]);
    tmp[y * w + x] = v;
  }
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    let v = tmp[y * w + x];
    for (let j = Math.max(0, y - r); j <= Math.min(h - 1, y + r); j++) v = pick(v, tmp[j * w + x]);
    out[y * w + x] = v;
  }
  return out;
}
const minF = (a, w, h, k) => filtro(a, w, h, k, Math.min);
const maxF = (a, w, h, k) => filtro(a, w, h, k, Math.max);

// Último recurso: o texto foi lido e traduzido, mas nenhuma limpeza "bonita" se aplicou (balão cortado sem par, texto fora de
// balão sobre a arte, balão sem tinta achada...). A tradução TEM que aparecer, então apaga o que der onde o texto está e deixa
// o leitor escrever por cima, mesmo que passe do balão.
//  - fundo liso (anel ao redor da região): pinta só as letras com a cor do fundo;
//  - fundo misto (arte, borda de balão cortado...): acha só os TRAÇOS finos (black-hat/top-hat, que separam letra de fundo mesmo
//    com dois fundos diferentes na mesma região) e preenche esses pixels pelas cores vizinhas, preservando o resto;
//  - se não achar traço nenhum, cobre o retângulo todo do texto (como o sistema antigo);
//  - letra escura em fundo claro e o contrário; sobre fundo misto, com contorno para continuar legível.
// Devolve { bg, ink, stroke, box, lines, fontMax, covered } ou { empty: true, reason } (só se a região for inválida).
export function cleanForce({ rgb, W, H, bbox, patch, lineHint = 1 }) {
  let [bx, by, bw, bh] = bbox.map((v) => Math.round(v));
  bx = Math.max(0, bx); by = Math.max(0, by); bw = Math.min(bw, W - bx); bh = Math.min(bh, H - by);
  if (!(bw >= 6 && bh >= 6)) return { empty: true, reason: 'tamanho' };
  if (bw * bh > 0.6 * W * H) return { empty: true, reason: 'tamanho' };
  const m = Math.max(8, Math.round(bh * 0.4));
  const rx = Math.max(0, bx - m), ry = Math.max(0, by - m), rw = Math.min(W, bx + bw + m) - rx, rh = Math.min(H, by + bh + m) - ry;
  const px = (x, y) => ((ry + y) * W + rx + x) * 3;
  const luma = new Float64Array(rw * rh);
  for (let y = 0; y < rh; y++) for (let x = 0; x < rw; x++) { const o = px(x, y); luma[y * rw + x] = lumaOf(rgb[o], rgb[o + 1], rgb[o + 2]); }
  const tx0 = bx - rx, ty0 = by - ry;
  const inBox = (x, y, g) => x >= tx0 - g && x < tx0 + bw + g && y >= ty0 - g && y < ty0 + bh + g;
  const idx = (pred) => { const a = []; for (let y = 0; y < rh; y++) for (let x = 0; x < rw; x++) if (pred(x, y)) a.push(y * rw + x); return a; };
  const colorOf = (list) => [0, 1, 2].map((c) => median(list.map((i) => rgb[px(i % rw, Math.floor(i / rw)) + c])));
  const ring = idx((x, y) => inBox(x, y, m) && !inBox(x, y, 2));
  const inside = idx((x, y) => inBox(x, y, 0));
  const ref = ring.length >= 30 ? ring : inside; // sem anel (texto colado nas bordas da imagem): usa a própria caixa
  const ringRgb = colorOf(ref);
  const ringL = lumaOf(...ringRgb);
  const dev = ref.map((i) => Math.abs(luma[i] - ringL)).sort((a, b) => a - b);
  const flat = ring.length >= 30 && dev[Math.floor(dev.length * 0.8)] < 18;
  const zone = new Uint8Array(rw * rh);
  for (let y = 0; y < rh; y++) for (let x = 0; x < rw; x++) if (inBox(x, y, 2)) zone[y * rw + x] = 1;
  const ink = new Uint8Array(rw * rh);
  let nInk = 0;
  if (flat) {
    for (let i = 0; i < ink.length; i++) if (zone[i] && Math.abs(luma[i] - ringL) > 45) { ink[i] = 1; nInk++; }
  } else {
    // traço = o que sobressai do fundo LOCAL: black-hat (escuro) e top-hat (claro). O kernel precisa ser um pouco maior que a
    // espessura da letra; como ela não é conhecida, tenta kernels crescentes e fica com o primeiro que acha traço suficiente
    // (kernel grande demais também pegaria cunhas finas de fundo junto da borda do balão).
    for (const k of [11, 17, 25]) {
      const closed = minF(maxF(luma, rw, rh, k), rw, rh, k), opened = maxF(minF(luma, rw, rh, k), rw, rh, k);
      ink.fill(0); nInk = 0;
      for (let i = 0; i < ink.length; i++) if (zone[i] && Math.max(closed[i] - luma[i], luma[i] - opened[i]) > 38) { ink[i] = 1; nInk++; }
      if (nInk >= 0.015 * bw * bh) break;
    }
  }
  const letters = nInk >= 12 && nInk <= 0.9 * bw * bh;
  let mask;
  if (letters) mask = dilate(ink, rw, rh, flat ? 3 : 2).map((v, i) => (v && zone[i] ? 1 : 0));
  else { mask = new Uint8Array(rw * rh); for (let y = 0; y < rh; y++) for (let x = 0; x < rw; x++) if (inBox(x, y, 1)) mask[y * rw + x] = 1; }
  // fundo de referência: liso = o anel; misto = o que NÃO é traço dentro da região (é o fundo sob as letras, ex.: o branco do balão)
  const underText = flat ? null : idx((x, y) => inBox(x, y, 0) && !mask[y * rw + x]);
  const bgRgb = flat || !underText || underText.length < 30 ? ringRgb : colorOf(underText);
  const bgL = lumaOf(...bgRgb);
  let covered = 0;
  const setPx = (i, c) => { const o = ((ry + Math.floor(i / rw)) * W + rx + (i % rw)) * 4; patch[o] = c[0]; patch[o + 1] = c[1]; patch[o + 2] = c[2]; patch[o + 3] = 255; covered++; };
  if (flat) {
    for (let i = 0; i < mask.length; i++) if (mask[i]) setPx(i, ringRgb);
  } else {
    const reg = new Uint8Array(rw * rh * 3);
    for (let y = 0; y < rh; y++) reg.set(rgb.subarray(px(0, y), px(0, y) + rw * 3), y * rw * 3);
    const ap = letters ? apagarLivre(reg, rw, rh, mask, zone) : { mask, fill: inpaint(reg, rw, rh, mask) };
    for (let i = 0; i < ap.mask.length; i++) if (ap.mask[i]) setPx(i, [0, 1, 2].map((c) => Math.round(ap.fill[i * 3 + c])));
  }
  // cor da letra e contorno: contraste com o fundo sob o texto; sobre fundo misto, contorno da cor oposta
  const light = bgL < 128;
  const inkRgb = light ? [255, 255, 255] : [0, 0, 0];
  const stroke = flat ? null : light ? '#000000' : '#ffffff';
  // linhas e tamanho máximo da fonte: corridas de linhas com tinta (ou a dica do OCR quando não achou letra)
  let lines = Math.max(1, lineHint);
  if (letters) {
    const cnt = [];
    for (let y = 0; y < rh; y++) { let n = 0; for (let x = 0; x < rw; x++) if (ink[y * rw + x]) n++; cnt.push(n); }
    const thr = 0.3 * Math.max(...cnt);
    const runs = [];
    cnt.forEach((n, y) => { if (n > 0 && n >= thr) (runs.length && runs[runs.length - 1][1] === y ? (runs[runs.length - 1][1] = y + 1) : runs.push([y, y + 1])); });
    if (runs.length) {
      const tall = Math.max(...runs.map(([a, b]) => b - a));
      lines = runs.reduce((acc, r) => (acc.length && r[0] - acc[acc.length - 1][1] < 0.25 * tall ? (acc[acc.length - 1][1] = r[1], acc) : [...acc, [...r]]), []).length;
    }
  }
  const fontMax = Math.round(Math.min(80, Math.max(10, lines > 1 ? (bh / lines) * 0.95 : bh * 1.2)));
  // caixa do texto: a região lida com folga; pode passar do que havia (o leitor deixa vazar), nunca da imagem
  const gx = Math.round(bw * 0.12), gy = Math.round(bh * 0.12);
  const x0 = Math.max(0, bx - gx), y0 = Math.max(0, by - gy);
  const box = [x0, y0, Math.min(W, bx + bw + gx) - x0, Math.min(H, by + bh + gy) - y0];
  return { bg: hex(bgRgb), ink: hex(inkRgb), stroke, box, lines, fontMax, covered, flat };
}
