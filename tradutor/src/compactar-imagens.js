// Compacta imagens para o celular: largura máx. N px (nunca amplia), WebP. Não toca nos originais.
//   node src/compactar-imagens.js <entrada.json>      entrada: { largura, qualidade, itens: [{ de, para }] }
// Imprime um JSON { ok: [para...], falhas: [{ para, erro }] } (sempre exit 0 se conseguiu ler a entrada).
import { mkdir, readFile, rename, rm } from 'node:fs/promises';
import path from 'node:path';
import sharp from 'sharp';

const { largura = 1080, qualidade = 80, itens = [] } = JSON.parse(await readFile(process.argv[2], 'utf8'));
const ok = [], falhas = [];
for (const { de, para } of itens) {
  const tmp = `${para}.tmp`;
  try {
    await mkdir(path.dirname(para), { recursive: true });
    await sharp(de, { limitInputPixels: 268402689 }).rotate().resize({ width: largura, withoutEnlargement: true }).webp({ quality: qualidade, effort: 4 }).toFile(tmp);
    await rename(tmp, para);
    ok.push(para);
  } catch (err) {
    await rm(tmp, { force: true });
    falhas.push({ para, erro: err.message });
  }
}
console.log(JSON.stringify({ ok, falhas }));
