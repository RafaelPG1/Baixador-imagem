// O onnxruntime-node traz binários de todas as plataformas (~290 MB). Fica só a do seu sistema, dentro de node_modules.
// Se algo falhar aqui, nada quebra: só sobra espaço em disco.
import { existsSync, readdirSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const bin = join(fileURLToPath(new URL('..', import.meta.url)), 'node_modules', 'onnxruntime-node', 'bin', 'napi-v6');
try {
  if (existsSync(bin)) {
    for (const os of readdirSync(bin)) {
      if (os !== process.platform) rmSync(join(bin, os), { recursive: true, force: true });
      else for (const arch of readdirSync(join(bin, os))) if (arch !== process.arch) rmSync(join(bin, os, arch), { recursive: true, force: true });
    }
  }
} catch {}
