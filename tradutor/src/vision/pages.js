import { readdir } from 'node:fs/promises';
import { join } from 'node:path';

const IMAGE = /\.(webp|png|jpe?g|bmp)$/i;

// Ordem das páginas: SOMENTE o número que abre o nome (001_..., 2.png, 0003.webp). O resto do nome não conta.
// Arquivos sem número no início são ignorados e avisados. Números repetidos ficam na ordem em que o
// sistema de arquivos os lista (sort estável), e também são avisados.
export async function listPages(dir) {
  const files = await readdir(dir);
  const pages = [];
  const ignored = [];
  for (const file of files) {
    if (!IMAGE.test(file)) continue;
    const m = /^(\d+)/.exec(file);
    if (m) pages.push({ number: Number(m[1]), file, path: join(dir, file) });
    else ignored.push(file);
  }
  pages.sort((a, b) => a.number - b.number);
  const warnings = ignored.map((f) => `Ignorado (não começa com número): ${f}`);
  for (let i = 1; i < pages.length; i++) {
    if (pages[i].number === pages[i - 1].number) warnings.push(`Número repetido ${String(pages[i].number).padStart(3, '0')}: ${pages[i - 1].file} e ${pages[i].file}`);
  }
  return { pages, warnings };
}
