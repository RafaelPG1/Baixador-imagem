// Apagar texto sem deixar fantasma: parte de uma máscara inicial (sementes), reconstrói o fundo por difusão, compara com o
// que está de fato na imagem e cobre o que ainda destoa (letra fraca, ponta de letra, acento, texto que passou da caixa lida
// pelo OCR). Repete até não achar mais nada; se a tinta encostar na borda da zona, a zona cresce. Nunca pinta o contorno
// do balão (`protegido`) nem fora de `permitido`.
import { dilate } from './clean.js';
import { inpaint } from './clean-free.js';

const maxDiff = (a, b, i) => Math.max(Math.abs(a[i * 3] - b[i * 3]), Math.abs(a[i * 3 + 1] - b[i * 3 + 1]), Math.abs(a[i * 3 + 2] - b[i * 3 + 2]));

// reg: RGB da região (rw×rh). seed/zone/permitido/protegido: máscaras rw×rh (0/1). `lado` (opcional): 1 = dentro do balão.
// A máscara cresce a partir das sementes: a cada passada entra todo TRAÇO (letra, por black-hat/top-hat, que não depende da cor do
// fundo nem do degradê) que esteja a até 10 px do que já foi coberto ou dentro da zona inicial. Assim, letra que o OCR não pegou
// (caixa curta, ponta, acento, texto que passou do balão) entra, e o fundo liso em volta não.
// Devolve { mask, fill, passes } — fill é o fundo reconstruído (Float64 RGB) para pintar onde mask vale 1.
export function apagar({ reg, rw, rh, seed, zone, permitido, protegido, fonteRuim = null, lado = null, limiar = 30, passes = 8 }) {
  const n = rw * rh;
  const livre = (i) => permitido[i] && !protegido[i];
  const luma = new Float64Array(n);
  for (let i = 0; i < n; i++) luma[i] = (299 * reg[i * 3] + 587 * reg[i * 3 + 1] + 114 * reg[i * 3 + 2]) / 1000;
  const tr = tracos(luma, rw, rh, limiar);
  let mask = dilate(seed, rw, rh, 2).map((v, i) => (v && livre(i) ? 1 : 0));
  let feitas = 0;
  for (let p = 0; p < passes; p++) {
    const alcance = dilate(mask, rw, rh, 10);
    const novo = new Uint8Array(n);
    let achou = 0, area = 0;
    for (let i = 0; i < n; i++) {
      const a = alcance[i] || zone[i];
      if (a) area++;
      if (a && tr[i] && livre(i) && !mask[i]) { novo[i] = 1; achou++; }
    }
    feitas++;
    if (!achou || achou > 0.5 * area) break; // nada novo; ou "traço" demais = arte, não letra
    const add = dilate(novo, rw, rh, 1);
    for (let i = 0; i < n; i++) if (add[i] && livre(i)) mask[i] = 1;
  }
  mask = dilate(mask, rw, rh, 1).map((v, i) => (v && livre(i) ? 1 : 0)); // borda suave da letra (antialias)
  const base = mask.map((v, i) => (v || protegido[i] || (fonteRuim && fonteRuim[i]) ? 1 : 0)); // fonteRuim (contorno): não empresta cor ao fundo refeito
  const fill = inpaint(reg, rw, rh, base);
  if (lado) { // dentro do balão só vale a cor de dentro; fora, a de fora (senão o branco do balão "vaza" em halo sobre a arte)
    const dentro = inpaint(reg, rw, rh, base.map((v, i) => (v || !lado[i] ? 1 : 0)));
    const fora = inpaint(reg, rw, rh, base.map((v, i) => (v || lado[i] ? 1 : 0)));
    for (let i = 0; i < n; i++) if (mask[i]) { const f = lado[i] ? dentro : fora; for (let c = 0; c < 3; c++) fill[i * 3 + c] = f[i * 3 + c]; }
  }
  return { mask, fill, passes: feitas };
}

// Traços finos (letra) sobre fundo qualquer: black-hat (escuro) e top-hat (claro) com núcleo k. Serve onde não há "cor do balão".
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
export function tracos(luma, rw, rh, limiar = 38, ks = [11, 17, 25]) {
  const t = new Uint8Array(rw * rh);
  for (const k of ks) {
    const fechado = filtro(filtro(luma, rw, rh, k, Math.max), rw, rh, k, Math.min);
    const aberto = filtro(filtro(luma, rw, rh, k, Math.min), rw, rh, k, Math.max);
    for (let i = 0; i < t.length; i++) if (Math.max(fechado[i] - luma[i], luma[i] - aberto[i]) > limiar) t[i] = 1;
  }
  return t;
}
