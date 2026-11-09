/* Leitor mínimo de ZIP (sem bibliotecas): lê o diretório central e extrai entradas sem compressão (o que o
   programa gera) ou "deflate" (via DecompressionStream do navegador). Trabalha sobre um File/Blob, sem carregá-lo inteiro. */
(function () {
  'use strict';
  var U16 = function (v, o) { return v.getUint16(o, true); }, U32 = function (v, o) { return v.getUint32(o, true); };
  async function abrir(arquivo) {
    var fim = Math.max(0, arquivo.size - 70000);
    var cauda = new DataView(await arquivo.slice(fim).arrayBuffer());
    var e = -1;
    for (var i = cauda.byteLength - 22; i >= 0; i--) { if (U32(cauda, i) === 0x06054b50) { e = i; break; } }
    if (e < 0) throw new Error('Este arquivo não é um ZIP válido.');
    var total = U16(cauda, e + 10), tamCD = U32(cauda, e + 12), offCD = U32(cauda, e + 16);
    if (total === 0xffff || tamCD === 0xffffffff || offCD === 0xffffffff) throw new Error('ZIP grande demais (zip64). Exporte menos capítulos de uma vez.');
    var cd = new DataView(await arquivo.slice(offCD, offCD + tamCD).arrayBuffer());
    var dec = new TextDecoder('utf-8'), entradas = new Map(), p = 0;
    for (var n = 0; n < total; n++) {
      if (p + 46 > cd.byteLength || U32(cd, p) !== 0x02014b50) throw new Error('ZIP danificado.');
      var nomeLen = U16(cd, p + 28), extra = U16(cd, p + 30), com = U16(cd, p + 32);
      var nome = dec.decode(new Uint8Array(cd.buffer, cd.byteOffset + p + 46, nomeLen));
      entradas.set(nome, { metodo: U16(cd, p + 10), comp: U32(cd, p + 20), tam: U32(cd, p + 24), off: U32(cd, p + 42) });
      p += 46 + nomeLen + extra + com;
    }
    async function blob(nome, tipo) {
      var en = entradas.get(nome); if (!en) throw new Error('Falta no ZIP: ' + nome);
      var loc = new DataView(await arquivo.slice(en.off, en.off + 30).arrayBuffer());
      var ini = en.off + 30 + U16(loc, 26) + U16(loc, 28);
      var dados = arquivo.slice(ini, ini + en.comp, tipo || '');
      if (en.metodo === 0) return dados;
      if (en.metodo === 8 && typeof DecompressionStream === 'function') {
        var b = await new Response(dados.stream().pipeThrough(new DecompressionStream('deflate-raw'))).blob();
        return tipo ? b.slice(0, b.size, tipo) : b;
      }
      throw new Error('Compressão não suportada neste navegador.');
    }
    return {
      nomes: function () { return Array.from(entradas.keys()); },
      tem: function (nome) { return entradas.has(nome); },
      blob: blob,
      texto: async function (nome) { return (await blob(nome)).text(); },
    };
  }
  window.LerZip = { abrir: abrir };
})();
