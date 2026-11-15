import { components } from './detect.js';

// Páginas de webtoon são fatias de uma tira contínua: uma linha de texto pode ser cortada ao meio pela emenda.
// Aqui só se olha a faixa colada (fim da página N + começo da N+1). Balões, caixas dos outros textos e coordenadas
// de cada página ficam como estão; só a região de texto cortada é completada nos dois lados.
export const bandRows = (w) => Math.round(0.15 * w);

const INK = 128;
const KIND_RANK = { balloon_text: 3, narration: 2, sfx: 1, free_text: 0 };
const hit = (a, b) => a[0] < b[0] + b[2] && b[0] < a[0] + a[2] && a[1] < b[1] + b[3] && b[1] < a[1] + a[3];
const union = (boxes) => {
  const x = Math.min(...boxes.map((b) => b[0]));
  const y = Math.min(...boxes.map((b) => b[1]));
  return [x, y, Math.max(...boxes.map((b) => b[0] + b[2])) - x, Math.max(...boxes.map((b) => b[1] + b[3])) - y];
};
const inside = (poly, x, y) => {
  let c = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) c = !c;
  }
  return c;
};

// A máscara do balão perde a margem branca fina entre as letras e a borda da página, então texto colado na borda sai
// "solto" mesmo estando dentro do balão. Religa esse texto ao balão: pelo polígono, ou pela linha de um texto de balão vizinho.
export function relinkEdgeTexts(page) {
  const edge = 0.1 * page.width;
  const near = (t) => t.bbox[1] < edge || t.bbox[1] + t.bbox[3] > page.height - edge;
  for (const t of page.texts) {
    if (t.kind !== 'free_text' || !near(t)) continue;
    const [x, y, w, h] = t.bbox;
    const inBalloon = page.balloons.find((b) => inside(b.polygon, x + w / 2, y + h / 2));
    const mate = page.texts.find((o) => {
      if (o === t || o.kind !== 'balloon_text') return false;
      const [ox, oy, ow, oh] = o.bbox;
      const rows = Math.min(y + h, oy + oh) - Math.max(y, oy);
      const gap = Math.max(x, ox) - Math.min(x + w, ox + ow);
      return rows >= 0.5 * Math.min(h, oh) && gap <= Math.max(h, oh);
    });
    const id = inBalloon?.id ?? mate?.balloonId;
    if (!id) continue;
    t.kind = 'balloon_text';
    t.balloonId = id;
    t.certainty = 'média';
    if (mate && !inBalloon) {
      // mesma linha de texto, partida em duas: vira uma região só
      mate.bbox = union([mate.bbox, t.bbox]);
      page.texts = page.texts.filter((q) => q !== t);
    }
  }
  page.texts.forEach((t, i) => (t.id = i + 1));
  for (const b of page.balloons) b.textIds = page.texts.filter((t) => t.balloonId === b.id).map((t) => t.id);
}

// Letras cortadas pela emenda: componentes de tinta que tocam a última linha de cima e a primeira de baixo.
function crossingGroups(cv, bandPrev, bandNext, W) {
  const hp = bandPrev.length / W;
  const hn = bandNext.length / W;
  const gray = cv.matFromArray(hp + hn, W, cv.CV_8UC1, [...bandPrev, ...bandNext]);
  const ink = new cv.Mat();
  cv.threshold(gray, ink, INK, 255, cv.THRESH_BINARY_INV);
  const max = 0.1 * W; // massa preta maior que uma letra é arte, não texto
  const cross = components(cv, ink, 4).list
    .filter((c) => c.y <= hp - 1 && c.y + c.h - 1 >= hp && c.w <= max && c.h <= max)
    .sort((a, b) => a.x - b.x);
  gray.delete();
  ink.delete();
  const groups = [];
  for (const c of cross) {
    const g = groups.at(-1);
    const gap = g ? c.x - (g.x + g.w) : 0;
    if (g && gap <= 0.6 * Math.max(g.h, c.h)) {
      const x2 = Math.max(g.x + g.w, c.x + c.w);
      const y1 = Math.min(g.y, c.y);
      g.h = Math.max(g.y + g.h, c.y + c.h) - y1;
      g.y = y1;
      g.w = x2 - g.x;
    } else groups.push({ x: c.x, y: c.y, w: c.w, h: c.h });
  }
  return { groups, hp };
}

// Substitui, na página, os textos que tocam `box` por uma só região (na posição do primeiro).
function merge(page, box, donor) {
  const old = page.texts.filter((t) => hit(t.bbox, box));
  const best = old.toSorted((a, b) => KIND_RANK[b.kind] - KIND_RANK[a.kind])[0];
  let { kind, balloonId, orientation, certainty } = best ?? donor;
  // arte (traços de cabelo, fumaça) costuma cruzar a emenda: só cria região nova se o outro lado é texto de balão
  if (!best && !(donor.kind === 'balloon_text' || donor.kind === 'narration')) return null;
  if (!best) {
    // sem texto aqui ainda: usa o balão da página que contém o centro da região
    const cx = box[0] + box[2] / 2;
    const cy = box[1] + box[3] / 2;
    const b = page.balloons.find((q) => inside(q.polygon, cx, cy));
    balloonId = b ? b.id : null;
    kind = b ? (b.kind === 'narration' ? 'narration' : 'balloon_text') : donor.kind === 'balloon_text' ? 'free_text' : donor.kind;
    certainty = 'média';
  }
  const next = { id: 0, kind, certainty, orientation, bbox: union([box, ...old.map((t) => t.bbox)]), balloonId };
  const at = old.length ? page.texts.indexOf(old[0]) : page.texts.length;
  page.texts = page.texts.filter((t) => !old.includes(t));
  page.texts.splice(Math.min(at, page.texts.length), 0, next);
  page.texts.forEach((t, i) => (t.id = i + 1));
  for (const b of page.balloons) b.textIds = page.texts.filter((t) => t.balloonId === b.id).map((t) => t.id);
  return next;
}

// Devolve quantas linhas de texto foram completadas. Só age quando já havia texto detectado em uma das páginas.
export function joinSeam(cv, prev, next, bandPrev, bandNext) {
  if (prev.width !== next.width) return 0;
  const { groups, hp } = crossingGroups(cv, bandPrev, bandNext, prev.width);
  let done = 0;
  for (const g of groups) {
    const up = [g.x, prev.height - hp + g.y, g.w, hp - g.y];
    const down = [g.x, 0, g.w, g.y + g.h - hp];
    const a = prev.texts.find((t) => hit(t.bbox, up));
    const b = next.texts.find((t) => hit(t.bbox, down));
    if (!a && !b) continue; // sem âncora: pode ser só arte
    const left = merge(prev, up, b ?? a);
    const right = merge(next, down, left ?? a ?? b);
    if (left && right) {
      left.continues = 'next';
      right.continues = 'prev';
      done++;
    }
  }
  return done;
}
