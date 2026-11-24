/* Baixador Leitor (app Android, Capacitor). Fala com o notebook pelo HTTPS privado do Tailscale, lista as obras que
   estão lá, baixa capítulos para ler offline (guardados no próprio celular) ou salva ZIPs em Download/Baixador/<obra>/.
   Nenhuma chave de API entra aqui: só a chave de pareamento do notebook, guardada neste aparelho. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  function el(tag, classe, texto) { var e = document.createElement(tag); if (classe) e.className = classe; if (texto != null) e.textContent = texto; return e; }
  function guardar(k, v) { try { localStorage.setItem(k, v); } catch (_) {} }
  function lembrar(k) { try { return localStorage.getItem(k); } catch (_) { return null; } }
  function esquecer(k) { try { localStorage.removeItem(k); } catch (_) {} }
  var tempo = null;
  function aviso(t) { var a = $('toast'); a.textContent = t; a.hidden = false; clearTimeout(tempo); tempo = setTimeout(function () { a.hidden = true; }, 4500); }
  function mensagemErro(e) { return e && e.name === 'QuotaExceededError' ? 'sem espaço no celular (apague capítulos que já leu)' : (e && e.message) || String(e); }
  var nativo = !!(window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform());
  function plugin(nome) {
    if (!nativo) return null;
    var C = window.Capacitor;
    if (C.Plugins && C.Plugins[nome]) return C.Plugins[nome];        // sem bundler, a ponte nativa expõe os plugins aqui
    return typeof C.registerPlugin === 'function' ? C.registerPlugin(nome) : null;
  }

  /* ---------------- banco local (obras baixadas) ---------------- */
  var _bd = null;
  function bd() {
    if (!_bd) _bd = new Promise(function (ok, err) {
      var r = indexedDB.open('baixador-leitor', 1);
      r.onupgradeneeded = function () { var d = r.result; d.createObjectStore('obras', { keyPath: 'nome' }); d.createObjectStore('caps', { keyPath: 'id' }); d.createObjectStore('imgs', { keyPath: 'chave' }); };
      r.onsuccess = function () { ok(r.result); }; r.onerror = function () { err(r.error); };
    });
    return _bd;
  }
  function pedido(r) { return new Promise(function (ok, err) { r.onsuccess = function () { ok(r.result); }; r.onerror = function () { err(r.error); }; }); }
  function concluida(t) { return new Promise(function (ok, err) { t.oncomplete = ok; t.onerror = function () { err(t.error); }; t.onabort = function () { err(t.error || new Error('Operação cancelada.')); }; }); }
  async function todos(loja, faixa) { var d = await bd(); return pedido(d.transaction(loja).objectStore(loja).getAll(faixa)); }
  async function obter(loja, chave) { var d = await bd(); return pedido(d.transaction(loja).objectStore(loja).get(chave)); }
  var faixaCap = function (id) { return IDBKeyRange.bound(id + '|', id + '|￿'); };
  async function apagarCapitulo(id) {
    var d = await bd(), t = d.transaction(['caps', 'imgs'], 'readwrite');
    t.objectStore('imgs').delete(faixaCap(id)); t.objectStore('caps').delete(id);
    await concluida(t);
  }
  async function limparObrasVazias() {
    var caps = await todos('caps'), obras = await todos('obras'), usadas = {};
    caps.forEach(function (c) { usadas[c.obra] = 1; });
    var d = await bd(), t = d.transaction('obras', 'readwrite'), lj = t.objectStore('obras');   // lê tudo ANTES: await dentro da transação a encerra
    obras.forEach(function (o) { if (!usadas[o.nome]) lj.delete(o.nome); });
    await concluida(t);
  }

  /* ---------------- ZIP do notebook -> armazenamento local ---------------- */
  var TIPOS = { jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', webp: 'image/webp', gif: 'image/gif', avif: 'image/avif', bmp: 'image/bmp' };
  var tipoDe = function (nome) { return TIPOS[(nome.split('.').pop() || '').toLowerCase()] || 'application/octet-stream'; };

  async function importarUm(arquivo) {
    var z = await LerZip.abrir(arquivo);
    if (!z.tem('baixador-export.json')) throw new Error('não é um arquivo exportado pelo Baixador.');
    var man = JSON.parse(await z.texto('baixador-export.json'));
    if (man.formato !== 1) throw new Error('formato de exportação desconhecido (' + man.formato + '); atualize o app.');
    var capas = {};
    for (var i = 0; i < man.obras.length; i++) {
      var o = man.obras[i];
      capas[o.nome] = o.capa && z.tem(o.capa) ? await z.blob(o.capa, tipoDe(o.capa)) : null;
    }
    var n = 0;
    for (var k = 0; k < man.capitulos.length; k++) {
      var c = man.capitulos[k], nomeObra = man.obras[c.obra].nome;
      var dados = JSON.parse(await z.texto(c.dir + '/capitulo.json'));
      var pares = [];
      for (var j = 0; j < dados.imagens.length; j++) {
        var im = dados.imagens[j];
        if (z.tem(c.dir + '/img/' + im.arq)) pares.push({ chave: c.id + '|' + im.arq, blob: await z.blob(c.dir + '/img/' + im.arq, tipoDe(im.arq)) });
        if (im.patch && z.tem(c.dir + '/limpeza/' + im.patch)) pares.push({ chave: c.id + '|limpeza/' + im.patch, blob: await z.blob(c.dir + '/limpeza/' + im.patch, 'image/png') });   // texto original apagado
      }
      var d = await bd(), t = d.transaction(['caps', 'imgs', 'obras'], 'readwrite');
      t.objectStore('imgs').delete(faixaCap(c.id));
      pares.forEach(function (p) { t.objectStore('imgs').put(p); });
      t.objectStore('caps').put({
        id: c.id, obra: nomeObra, rotulo: c.rotulo, numero: c.numero, titulo: c.titulo, paginas: dados.imagens.length, traduzido: !!c.traduzido,
        dados: { titulo: dados.titulo, imagens: dados.imagens }, importado: Date.now(),
      });
      var atual = await pedido(t.objectStore('obras').get(nomeObra));
      t.objectStore('obras').put({ nome: nomeObra, capa: capas[nomeObra] || (atual && atual.capa) || null });
      await concluida(t);
      n++;
    }
    return n;
  }
  async function importarArquivos(arquivos) {
    var feitos = 0, falhas = [];
    for (var a = 0; a < arquivos.length; a++) {
      try { feitos += await importarUm(arquivos[a]); } catch (e) { falhas.push(arquivos[a].name + ': ' + mensagemErro(e)); }
    }
    aviso(falhas.length ? 'Importação com problema — ' + falhas[0] : feitos + ' capítulo(s) importado(s).');
    rotear();
  }

  /* ---------------- conexão com o notebook ---------------- */
  var CHAVE_CFG = 'baixador-conexao';
  function cfg() {
    try { var c = JSON.parse(lembrar(CHAVE_CFG) || 'null'); return c && c.base && c.chave ? c : null; } catch (_) { return null; }
  }
  function nomeHost(base) { return String(base).replace(/^https?:\/\//, ''); }
  /* A conexão fica em dois lugares: localStorage e SharedPreferences nativo (o WebView pode perder o localStorage). Uma cópia refaz a outra. */
  function nativoRede() { return semNativo ? null : plugin('SalvarZip'); }
  var semNativo = false;                                        // plugin antigo (APK sem os métodos novos): cai no fetch do WebView
  function guardarCfg(c) {
    var j = JSON.stringify(c); guardar(CHAVE_CFG, j);
    var S = nativoRede(); if (S) S.guardarConfig({ valor: j }).catch(function () {});
  }
  function esquecerCfg() { esquecer(CHAVE_CFG); var S = nativoRede(); if (S) S.apagarConfig().catch(function () {}); }
  async function restaurarCfg() {
    var S = nativoRede(); if (!S) return;
    try {
      var r = await S.lerConfig(), nativa = r && r.valor;
      if (!cfg() && nativa) guardar(CHAVE_CFG, nativa);          // o WebView perdeu: volta do nativo, sem parear de novo
      else if (cfg() && !nativa) S.guardarConfig({ valor: lembrar(CHAVE_CFG) }).catch(function () {});
    } catch (_) { semNativo = true; }
  }
  function setEstado(ok, texto) { var e = $('estado'); e.className = 'estado ' + (ok ? 'ok' : 'ruim'); e.textContent = texto; }

  /* Aceita o endereço completo do QR (https://nome.ts.net/?k=CHAVE) ou "nome.ts.net CHAVE". */
  function lerPareamento(texto) {
    texto = (texto || '').trim(); var base, chave;
    if (!texto) throw new Error('Escaneie o QR ou cole o código que aparece no notebook.');
    if (/^https?:\/\//i.test(texto)) {
      var u; try { u = new URL(texto); } catch (_) { throw new Error('Código inválido.'); }
      if (u.protocol !== 'https:') throw new Error('O endereço precisa ser HTTPS (o do Tailscale, terminado em .ts.net).');
      base = u.origin; chave = u.searchParams.get('k');
    } else {
      var p = texto.split(/[\s|;,]+/);
      if (p.length < 2) throw new Error('Código inválido: falta a chave.');
      base = 'https://' + p[0].replace(/\/.*$/, ''); chave = p[1];
    }
    if (!chave) throw new Error('O código não tem a chave (parte “?k=…”).');
    return { base: base, chave: chave };
  }

  /* Diagnóstico por etapa: sem chave (um 401 já prova que o notebook foi alcançado) e com a chave. Mostra o código real da falha. A chave nunca é mostrada. */
  async function diagnosticar(c) {
    var linhas = [], via = nativoRede() ? 'nativo' : 'WebView';
    async function etapa(nome, comChave) {
      var t0 = Date.now();
      try {
        var x = await umaTentativa(comChave ? c : { base: c.base, chave: '-' }, '/api/app/ping', { limite: 10000 });
        linhas.push(nome + ': HTTP ' + x.status + ' (' + (Date.now() - t0) + ' ms)');
      } catch (e) { linhas.push(nome + ': ' + (e.codigo || 'erro') + ' — ' + e.message); }
    }
    await etapa('1 alcança o notebook', false);
    await etapa('2 chave aceita', true);
    return 'Via ' + via + '\n' + linhas.join('\n');
  }

  /* ---- rede: HTTP nativo quando há (sem CORS/regras de rede local do WebView) e fetch como reserva ---- */
  var ESPERA = function (ms, sinal) { return new Promise(function (ok, err) { var t = setTimeout(ok, ms); if (sinal) sinal.addEventListener('abort', function () { clearTimeout(t); var e = new Error('Cancelado.'); e.name = 'AbortError'; err(e); }); }); };
  function falha(codigo, base, detalhe) {
    var host = nomeHost(base), m;
    if (codigo === 'DNS') m = 'O celular não achou “' + host + '”. O Tailscale está ligado no celular? Confira também se o nome .ts.net salvo no notebook é este.';
    else if (codigo === 'TIMEOUT') m = 'O notebook não respondeu a tempo. Ele pode estar desligado, dormindo ou sem internet; com o Tailscale ligado nos dois, tente de novo.';
    else if (codigo === 'RECUSADA') m = 'A conexão com o notebook foi recusada. No notebook, ligue “Leitura pelo celular” e rode o comando “tailscale serve” mostrado lá.';
    else if (codigo === 'SEM_ROTA') m = 'Sem caminho até o notebook. Ligue o Tailscale no celular e no notebook.';
    else if (codigo === 'SSL') m = 'O certificado HTTPS do Tailscale não foi aceito. No painel do Tailscale, ative “HTTPS Certificates” e rode “tailscale serve” de novo no notebook.';
    else if (codigo === 'BAD_GATEWAY') m = 'O Tailscale respondeu, mas o programa do notebook não. Confira se “Leitura pelo celular” está ligada e se a porta do “tailscale serve” é a mostrada lá.';
    else if (codigo === 'FETCH') m = 'O WebView bloqueou a chamada ao notebook (' + (detalhe || 'Failed to fetch') + '). Atualize o app; se continuar, confira o Tailscale nos dois aparelhos.';
    else m = 'Falha de rede ao falar com o notebook' + (detalhe ? ' (' + detalhe + ')' : '') + '.';
    var e = new Error(m); e.codigo = codigo; return e;
  }
  function erroNativo(e, base) {                                // erro do plugin (e.code) -> mensagem específica
    var k = e && e.code;
    if (/^HTTP_40[13]$/.test(k)) return Object.assign(new Error('Chave ou endereço recusado pelo notebook. Use “Parear de novo”.'), { codigo: 'CHAVE' });
    if (/^HTTP_5/.test(k)) return falha('BAD_GATEWAY', base);
    if (k === 'INCOMPLETO') return Object.assign(new Error('Download incompleto; tente de novo.'), { codigo: k });
    return k ? falha(k, base, e.message) : e;
  }
  var TRANSITORIOS = { TIMEOUT: 1, REDE: 1, RECUSADA: 1, BAD_GATEWAY: 1, FETCH: 1 };
  async function umaTentativa(c, caminho, o) {
    var S = nativoRede(), cab = { Authorization: 'Bearer ' + c.chave };
    if (S) {
      try {
        var r = await S.requisitar({ url: c.base + caminho, headers: cab, limite: o.limite, binario: !!o.binario });
        return { status: r.status, corpo: r.corpo, tipo: r.tipo, binario: !!o.binario };
      } catch (e) {
        if (e && e.code === 'UNIMPLEMENTED') semNativo = true;
        else throw falha(e && e.code, c.base, e && e.message);
      }
    }
    var ctl = new AbortController(), estourou = false, fim = o.limite > 0 ? setTimeout(function () { estourou = true; ctl.abort(); }, o.limite) : null;
    if (o.signal) o.signal.addEventListener('abort', function () { ctl.abort(); });
    try {
      var f = await fetch(c.base + caminho, { headers: cab, signal: ctl.signal, cache: 'no-store' });
      return { status: f.status, resposta: f, binario: !!o.binario };
    } catch (e) { throw falha(estourou ? 'TIMEOUT' : 'FETCH', c.base, e && e.message); }
    finally { if (fim) clearTimeout(fim); }
  }
  function enxergar(x) {
    return {
      status: x.status, ok: x.status >= 200 && x.status < 300,
      json: function () { return x.resposta ? x.resposta.json() : Promise.resolve(JSON.parse(x.corpo || 'null')); },
      blob: function () {
        if (x.resposta) return x.resposta.blob();
        var bin = atob(x.corpo || ''), v = new Uint8Array(bin.length); for (var i = 0; i < bin.length; i++) v[i] = bin.charCodeAt(i);
        return Promise.resolve(new Blob([v], { type: x.tipo || 'application/octet-stream' }));
      },
      bruto: x.resposta,
    };
  }

  /* Até 3 tentativas (1 s, 2 s) só para falha transitória; erro de chave/endereço (401/403/429) não repete. Nunca é infinito. */
  async function fetchAuth(caminho, opcoes) {
    opcoes = opcoes || {};
    var c = opcoes.cfg || cfg(); if (!c) throw new Error('Conecte ao notebook primeiro.');
    var limite = opcoes.limite == null ? 20000 : opcoes.limite, tentativas = opcoes.tentativas || 3, x, erro;
    for (var n = 0; n < tentativas; n++) {
      if (opcoes.signal && opcoes.signal.aborted) { var ab = new Error('Cancelado.'); ab.name = 'AbortError'; throw ab; }
      try {
        x = await umaTentativa(c, caminho, { limite: limite, signal: opcoes.signal, binario: opcoes.binario });
        if (x.status === 502 || x.status === 503 || x.status === 504) throw falha('BAD_GATEWAY', c.base);
        erro = null; break;
      } catch (e) {
        if (e && e.name === 'AbortError') throw e;
        erro = e;
        if (!TRANSITORIOS[e.codigo] || n === tentativas - 1) break;
        await ESPERA(1000 * Math.pow(2, n), opcoes.signal);
      }
    }
    if (erro) { setEstado(false, 'sem conexão'); throw erro; }
    var r = enxergar(x);
    if (r.status === 401) { setEstado(false, 'chave recusada'); throw Object.assign(new Error('Chave recusada: o notebook gerou outra chave. No notebook, abra “Leitura pelo celular”, copie o QR atual e use “Parear de novo”.'), { codigo: 'CHAVE' }); }
    if (r.status === 403) { setEstado(false, 'recusado'); throw Object.assign(new Error('O notebook recusou o endereço. Confira se o nome .ts.net foi salvo na aba Leitura pelo celular e se o comando “tailscale serve” foi executado.'), { codigo: 'HOST' }); }
    if (r.status === 429) throw Object.assign(new Error('Muitas tentativas erradas. Aguarde um minuto.'), { codigo: 'BLOQUEIO' });
    if (!r.ok) { setEstado(false, 'erro ' + r.status); throw new Error('O notebook respondeu erro ' + r.status + '.'); }
    setEstado(true, 'notebook conectado');
    return r;
  }

  async function baixarBlob(caminho, aoProgredir, signal) {
    var S = nativoRede(), c = cfg();
    if (S && c && S.baixarParaCache) {                           // nativo: grava em arquivo e o WebView lê de lá (nada inteiro na memória do JS)
      progressoNativo = aoProgredir; garantirOuvinte(S); var caminhoArq = null;
      try {
        var dl = await S.baixarParaCache({ url: c.base + caminho, headers: { Authorization: 'Bearer ' + c.chave }, id: caminho });
        caminhoArq = dl.caminho;
        var rr = await fetch(window.Capacitor.convertFileSrc('file://' + caminhoArq));
        if (!rr.ok) throw new Error('Não consegui ler o download guardado.');
        setEstado(true, 'notebook conectado');
        return await rr.blob();
      } catch (e) {
        if (signal && signal.aborted) { var ab = new Error('Cancelado.'); ab.name = 'AbortError'; throw ab; }
        if (e && e.code === 'UNIMPLEMENTED') semNativo = true;
        else { setEstado(false, 'sem conexão'); throw erroNativo(e, c.base); }
      } finally { progressoNativo = null; if (caminhoArq) S.apagarCache({ caminho: caminhoArq }).catch(function () {}); }
    }
    var r0 = await fetchAuth(caminho, { limite: 0, signal: signal, tentativas: 1 }), r = r0.bruto;
    if (!r) return r0.blob();
    var total = parseInt(r.headers.get('Content-Length') || '0', 10);
    if (!r.body || !r.body.getReader) return r.blob();
    var leitor = r.body.getReader(), partes = [], recebido = 0;
    for (;;) {
      var passo = await leitor.read();
      if (passo.done) break;
      partes.push(passo.value); recebido += passo.value.length;
      if (aoProgredir) aoProgredir(recebido, total);
    }
    if (total && recebido !== total) throw new Error('Download incompleto; tente de novo.');
    return new Blob(partes, { type: 'application/zip' });
  }

  var scannerProntoTentado = false;
  async function escanearQR() {
    var BS = plugin('BarcodeScanner');
    if (!BS) throw new Error('O leitor de QR só funciona no app instalado. Cole o código.');
    var r;
    try { r = await BS.scan({ formats: ['QR_CODE'] }); }
    catch (e) {
      var msg = (e && e.message) || '';
      if (/cancel/i.test(msg)) return '';
      if (/not available|module/i.test(msg) && !scannerProntoTentado) {
        scannerProntoTentado = true; aviso('Preparando o leitor de QR do Google (só na primeira vez)…');
        await new Promise(function (ok, err) {
          var fim = setTimeout(function () { err(new Error('O leitor de QR não terminou de instalar. Tente de novo ou cole o código.')); }, 120000);
          BS.addListener('googleBarcodeScannerModuleInstallProgress', function (ev) {
            if (ev.state === 4) { clearTimeout(fim); ok(); } else if (ev.state === 3 || ev.state === 5) { clearTimeout(fim); err(new Error('Não consegui instalar o leitor de QR. Cole o código.')); }
          }).then(function () { return BS.installGoogleBarcodeScannerModule(); }).catch(function (x) { clearTimeout(fim); err(x); });
        });
        r = await BS.scan({ formats: ['QR_CODE'] });
      } else throw e;
    }
    var b = r && r.barcodes && r.barcodes[0];
    return (b && (b.rawValue || b.displayValue)) || '';
  }

  /* ---------------- util de telas ---------------- */
  var urls = [];
  function soltarUrls() { urls.forEach(function (u) { URL.revokeObjectURL(u); }); urls = []; }
  function url(blob) { var u = URL.createObjectURL(blob); urls.push(u); return u; }
  var num = function (c) { var v = parseFloat(c.numero); return isNaN(v) ? null : v; };
  function ordenar(caps) {
    return caps.slice().sort(function (a, b) {
      var x = num(a), y = num(b);
      if (x !== null && y !== null && x !== y) return x - y;
      return String(a.rotulo).localeCompare(String(b.rotulo), 'pt', { numeric: true });
    });
  }
  function vazio(titulo, texto) { var v = el('div', 'vazio'); v.append(el('strong', '', titulo), el('span', '', texto)); return v; }
  function sair() { soltarUrls(); document.body.classList.remove('leitor', 'original', 'conectar'); window.onscroll = null; }
  function marcarAba(nome) {
    document.querySelectorAll('#abas a').forEach(function (a) { if (a.dataset.aba === nome) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  }
  var rotaAtual = 0;
  var vivo = function (eu) { return eu === rotaAtual; };
  var enc = encodeURIComponent;

  /* ---------------- tela: conectar ---------------- */
  function telaConectar() {
    var tela = $('tela'); document.body.classList.add('conectar'); marcarAba(''); tela.replaceChildren();
    tela.append(el('h1', '', 'Conectar ao notebook'));
    tela.append(el('p', 'nota', 'No notebook, abra a aba “Leitura pelo celular” do programa: lá aparece o QR do app. O Tailscale precisa estar ligado nos dois aparelhos.'));
    var acoes = el('div', 'acoes-col');
    var scan = el('button', 'btn principal grande', 'Escanear QR do notebook'); scan.type = 'button';
    var campo = el('textarea', 'campo-texto'); campo.placeholder = 'Ou cole aqui o código (https://….ts.net/?k=…)'; campo.rows = 3; campo.spellcheck = false; campo.autocapitalize = 'off'; campo.setAttribute('aria-label', 'Código de pareamento');
    var ir = el('button', 'btn grande', 'Conectar com o código'); ir.type = 'button';
    var msg = el('p', 'msg'); msg.setAttribute('role', 'alert');
    async function conectarCom(texto) {
      msg.className = 'msg'; msg.textContent = 'Testando conexão…'; scan.disabled = ir.disabled = true;
      try {
        var c = lerPareamento(texto);
        var t0 = Date.now(), r = await fetchAuth('/api/app/ping', { cfg: c, limite: 15000, tentativas: 2 }), j = await r.json();
        guardarCfg(c); cacheOnline = null; try { sessionStorage.removeItem('baixador-online'); } catch (_) {}
        aviso('Conectado ao notebook (' + (Date.now() - t0) + ' ms).'); location.hash = '#/';
      } catch (e) {
        msg.className = 'msg'; msg.textContent = mensagemErro(e);
        try { var c2 = lerPareamento(texto); msg.textContent += '\n\nDiagnóstico…'; var d = await diagnosticar(c2); msg.style.whiteSpace = 'pre-wrap'; msg.textContent = mensagemErro(e) + '\n\nDiagnóstico:\n' + d; } catch (_) { }
      } finally { scan.disabled = ir.disabled = false; }
    }
    scan.addEventListener('click', async function () {
      msg.textContent = '';
      try { var v = await escanearQR(); if (v) await conectarCom(v); } catch (e) { msg.textContent = mensagemErro(e); }
    });
    ir.addEventListener('click', function () { conectarCom(campo.value); });
    acoes.append(scan, campo, ir, msg);
    tela.append(acoes);
    if (cfg()) { var v = el('a', 'btn', 'Cancelar'); v.href = '#/ajustes'; tela.append(v); }
    else { var b = el('a', 'btn', 'Ver obras já baixadas'); b.href = '#/baixadas'; tela.append(b); }
  }

  /* ---------------- tela: obras no notebook (online) ---------------- */
  var cacheOnline = null;
  async function carregarOnline() {
    var r = await fetchAuth('/api/biblioteca'); cacheOnline = await r.json();
    try { sessionStorage.setItem('baixador-online', JSON.stringify(cacheOnline)); } catch (_) {}
    return cacheOnline;
  }
  try { cacheOnline = JSON.parse(sessionStorage.getItem('baixador-online') || 'null'); } catch (_) { cacheOnline = null; }   // voltar do leitor não refaz a espera

  function erroOnline(tela, e) {
    tela.replaceChildren();
    var v = vazio('Não deu para ver as obras do notebook', mensagemErro(e));
    var acoes = el('div', 'acoes-col');
    var de_novo = el('button', 'btn principal grande', 'Tentar de novo'); de_novo.type = 'button'; de_novo.addEventListener('click', rotear);
    var off = el('a', 'btn grande', 'Ver obras baixadas'); off.href = '#/baixadas';
    var rec = el('a', 'btn', 'Reconectar'); rec.href = '#/conectar';
    acoes.append(de_novo, off, rec); tela.append(v, acoes);
  }

  var atualizacaoVerificada = false;
  function avisoAtualizacao(eu, tela) {                         // uma conferência por abertura do app; só aparece se houver versão nova de verdade
    function pintar() {
      if (!atualizacaoNova || !vivo(eu) || tela.querySelector('.aviso-atualizar')) return;
      var a = el('a', 'btn principal aviso-atualizar', 'Atualização disponível (versão ' + atualizacaoNova.versao + '). Toque para instalar.'); a.href = '#/ajustes'; tela.prepend(a);
    }
    if (atualizacaoVerificada) { pintar(); return; }
    atualizacaoVerificada = true;
    verificarAtualizacao().then(pintar, function () {});
  }
  async function telaOnline(eu) {
    var tela = $('tela'); marcarAba('online');
    if (!cfg()) { location.hash = '#/conectar'; return; }
    tela.replaceChildren(el('p', 'nota', 'Conectando ao notebook…'));
    var dados; try { dados = await carregarOnline(); } catch (e) { if (vivo(eu)) erroOnline(tela, e); return; }
    if (!vivo(eu)) return;
    var locais = await todos('caps'); if (!vivo(eu)) return;
    tela.replaceChildren();
    avisoAtualizacao(eu, tela);
    if (!dados.obras.length) { tela.append(vazio('O notebook ainda não tem obras', 'Baixe capítulos no programa e volte aqui.')); return; }
    var grade = el('div', 'capas');
    dados.obras.forEach(function (o) {
      var meus = locais.filter(function (c) { return c.obra === o.nome; }).length;
      var a = el('a', 'capa'); a.href = '#/online/' + enc(o.nome);
      var img = el('div', 'capa-img'); img.append(el('span', 'capa-inicial', (o.nome.trim()[0] || '?').toUpperCase()));
      a.append(img, el('span', 'capa-nome', o.nome), el('span', 'capa-sub', o.capitulos.length + ' cap.' + (meus ? ' · ' + meus + ' baixado' + (meus === 1 ? '' : 's') : '')));
      grade.append(a);
      if (o.pasta && o.capa) {                                // capa, carregada depois (não trava a lista)
        fetchAuth('/api/capa?p=' + enc(o.pasta) + '&v=' + (o.capa_v || 0), { binario: true, tentativas: 1 }).then(function (r) { return r.blob(); }).then(function (b) {
          if (!vivo(eu)) return; var i = el('img'); i.alt = ''; i.src = url(b); img.replaceChildren(i);
        }).catch(function () {});
      }
    });
    tela.append(grade);
  }

  async function telaOnlineObra(eu, nome) {
    var tela = $('tela'); marcarAba('online');
    if (!cfg()) { location.hash = '#/conectar'; return; }
    var dados = cacheOnline;
    if (!dados) { tela.replaceChildren(el('p', 'nota', 'Conectando ao notebook…')); try { dados = await carregarOnline(); } catch (e) { if (vivo(eu)) erroOnline(tela, e); return; } }
    if (!vivo(eu)) return;
    var obra = dados.obras.find(function (o) { return o.nome === nome; });
    if (!obra) { aviso('Obra não encontrada no notebook.'); location.hash = '#/'; return; }
    var locais = {}; (await todos('caps')).forEach(function (c) { locais[c.id] = c; });
    if (!vivo(eu)) return;
    var caps = obra.capitulos.slice().reverse();               // mais novo primeiro
    var sel = new Set();
    tela.replaceChildren();
    var cab = el('div', 'barra-obra'); cab.append(el('h1', '', obra.nome));
    var voltar = el('a', 'btn', '‹ Obras'); voltar.href = '#/'; cab.append(voltar);
    var barra = el('div', 'barra-sel'); var contador = el('span', 'nota');
    var bTodos = el('button', 'btn', 'Todos'), bNovos = el('button', 'btn', 'Não baixados'), bLimpar = el('button', 'btn', 'Limpar');
    [bTodos, bNovos, bLimpar].forEach(function (b) { b.type = 'button'; });
    barra.append(contador, bTodos, bNovos, bLimpar);
    var ul = el('ul', 'lista'); var caixas = {}, titulos = {};
    function pintarTag(c) {                                     // "baixado" / "tradução nova" ao lado do nome
      var t = titulos[c.rel], velha = t.querySelector('.tag'), loc = locais[c.rel]; if (velha) velha.remove();
      if (loc) { var novo = !(loc.traduzido || !c.traduzido); t.append(el('span', novo ? 'tag novo' : 'tag ok', novo ? 'tradução nova' : 'baixado')); }
    }
    caps.forEach(function (c) {
      var li = el('li', 'linha-sel'), marca = el('label', 'marca-cap');
      var cx = el('input'); cx.type = 'checkbox'; cx.setAttribute('aria-label', 'Selecionar ' + (c.rotulo || c.rel)); caixas[c.rel] = cx; marca.append(cx);
      var lab = el('a', 'cap'); lab.href = 'leitor.html?c=' + enc(c.rel); lab.setAttribute('aria-label', 'Ler ' + (c.rotulo || c.rel));
      var t = el('span', 'cap-t', c.rotulo || c.rel); titulos[c.rel] = t; pintarTag(c);
      var s = el('span', 'cap-s' + (c.traduzido ? ' ok' : ''), c.imagens + ' pág. · ' + (c.traduzido ? (c.incompleta ? 'tradução incompleta' : 'traduzido') : 'só original'));
      lab.append(t, s); li.append(marca, lab); ul.append(li);
      cx.addEventListener('change', function () { if (cx.checked) sel.add(c.rel); else sel.delete(c.rel); atualizar(); });
    });
    var fixa = el('div', 'fixa-baixo');
    var bOff = el('button', 'btn principal grande'), bZip = el('button', 'btn grande');
    bOff.type = bZip.type = 'button';
    var bCancelar = el('button', 'btn perigo', 'Cancelar'); bCancelar.type = 'button'; bCancelar.hidden = true;
    var prog = el('progress'); prog.hidden = true; prog.max = 1; prog.value = 0;
    var txt = el('div', 'progresso-txt'); txt.setAttribute('role', 'status');
    fixa.append(bOff, bZip, prog, txt, bCancelar);
    function atualizar() {
      var n = sel.size; contador.textContent = n + ' de ' + caps.length + ' selecionado' + (n === 1 ? '' : 's');
      bOff.textContent = 'Baixar para ler offline' + (n ? ' (' + n + ')' : ''); bZip.textContent = 'Salvar ZIP no celular' + (n ? ' (' + n + ')' : '');
      bOff.disabled = bZip.disabled = !n || !!ctlAtual;
    }
    function marcar(fn) { caps.forEach(function (c) { var m = fn(c); caixas[c.rel].checked = m; if (m) sel.add(c.rel); else sel.delete(c.rel); }); atualizar(); }
    bTodos.addEventListener('click', function () { marcar(function () { return true; }); });
    bNovos.addEventListener('click', function () { marcar(function (c) { var l = locais[c.rel]; return !l || (c.traduzido && !l.traduzido); }); });
    bLimpar.addEventListener('click', function () { marcar(function () { return false; }); });
    var ctlAtual = null;
    function escolhidos() { return caps.filter(function (c) { return sel.has(c.rel); }).reverse(); }   // do mais antigo para o mais novo
    async function rodar(fazer) {
      var lista = escolhidos(); if (!lista.length || ctlAtual) return;
      ctlAtual = new AbortController(); bCancelar.hidden = false; prog.hidden = false; atualizar(); var feitos = 0, falhas = [];
      try {
        for (var i = 0; i < lista.length; i++) {
          if (ctlAtual.signal.aborted) break;
          var c = lista[i]; txt.textContent = (i + 1) + '/' + lista.length + ' · ' + c.rotulo; prog.value = 0; prog.max = 1;
          try { await fazer(c, ctlAtual.signal, function (rec, tot) { prog.max = tot || 1; prog.value = tot ? rec : 0; }); feitos++; }
          catch (e) { if (e && e.name === 'AbortError') break; falhas.push(c.rotulo + ': ' + mensagemErro(e)); }
        }
      } finally { var cancelou = ctlAtual.signal.aborted; ctlAtual = null; bCancelar.hidden = true; prog.hidden = true; atualizar();
        txt.textContent = (cancelou ? 'Cancelado. ' : '') + feitos + ' de ' + lista.length + ' concluído(s).' + (falhas.length ? ' Falhou: ' + falhas[0] : ''); }
      return feitos;
    }
    bCancelar.addEventListener('click', function () { if (ctlAtual) ctlAtual.abort(); });
    bOff.addEventListener('click', async function () {
      var f = await rodar(async function (c, sinal, prg) {
        var blob = await baixarBlob('/api/app/exportar?rel=' + enc(c.rel), prg, sinal);
        txt.textContent += ' · guardando…'; await importarUm(blob); locais[c.rel] = await obter('caps', c.rel); pintarTag(c);
      });
      if (f) aviso(f + ' capítulo(s) baixado(s). Já dá para ler sem internet na aba Baixadas.');
    });
    bZip.addEventListener('click', async function () {
      var f = await rodar(async function (c, sinal, prg) { await salvarZip(obra, c, sinal, prg); });
      if (f) aviso(f + ' ZIP(s) salvo(s) em Download/Baixador/' + obra.nome + '.');
    });
    tela.append(cab, el('p', 'nota', 'Toque no capítulo para ler agora (direto do notebook, sem baixar). Use as caixas para baixar ou salvar ZIP.'), barra, ul, fixa); atualizar();
  }

  /* Um ZIP por capítulo, em Download/Baixador/<obra>/ (nativo: direto no armazenamento, sem passar pela memória). */
  var ouvindoProgresso = false, progressoNativo = null;
  function garantirOuvinte(SZ) { if (!ouvindoProgresso) { ouvindoProgresso = true; SZ.addListener('progresso', function (ev) { if (progressoNativo) progressoNativo(ev.recebido, ev.total); }); } }
  async function salvarZip(obra, c, sinal, prg) {
    var conf = cfg(), nome = (obra.nome + ' - ' + (c.rotulo || 'capitulo') + '.zip');
    var SZ = plugin('SalvarZip');
    if (SZ) {
      garantirOuvinte(SZ);
      progressoNativo = prg;
      try { await SZ.salvar({ url: conf.base + '/api/app/exportar?rel=' + enc(c.rel), headers: { Authorization: 'Bearer ' + conf.chave }, pasta: obra.nome, nome: nome, id: c.rel }); }
      finally { progressoNativo = null; }
      return;
    }
    var blob = await baixarBlob('/api/app/exportar?rel=' + enc(c.rel), prg, sinal);     // fora do app (teste no navegador): download comum
    var a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = nome; document.body.append(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 10000);
  }

  /* ---------------- telas: obras baixadas (offline) ---------------- */
  async function telaBaixadas(eu) {
    var tela = $('tela'); marcarAba('baixadas');
    var obras = await todos('obras'), caps = await todos('caps'); if (!vivo(eu)) return;
    tela.replaceChildren();
    if (!obras.length) {
      tela.append(vazio('Nada baixado ainda', 'Na aba Notebook, abra uma obra, marque os capítulos e toque em “Baixar para ler offline”.'));
      return;
    }
    obras.sort(function (a, b) { return a.nome.localeCompare(b.nome, 'pt', { sensitivity: 'base' }); });
    var grade = el('div', 'capas');
    obras.forEach(function (o) {
      var meus = caps.filter(function (c) { return c.obra === o.nome; });
      var a = el('a', 'capa'); a.href = '#/obra/' + enc(o.nome);
      var img = el('div', 'capa-img');
      if (o.capa) { var i = el('img'); i.alt = ''; i.src = url(o.capa); img.append(i); } else img.append(el('span', 'capa-inicial', (o.nome.trim()[0] || '?').toUpperCase()));
      a.append(img, el('span', 'capa-nome', o.nome), el('span', 'capa-sub', meus.length + ' capítulo' + (meus.length === 1 ? '' : 's') + ' · ' + meus.reduce(function (s, c) { return s + c.paginas; }, 0) + ' pág.'));
      grade.append(a);
    });
    tela.append(grade);
  }

  async function telaObra(eu, nome) {
    var tela = $('tela'); marcarAba('baixadas');
    var caps = ordenar((await todos('caps')).filter(function (c) { return c.obra === nome; })).reverse(); if (!vivo(eu)) return;
    tela.replaceChildren();
    if (!caps.length) { location.hash = '#/baixadas'; return; }
    var cab = el('div', 'barra-obra'); cab.append(el('h1', '', nome));
    var voltar = el('a', 'btn', '‹ Baixadas'); voltar.href = '#/baixadas';
    var excluir = el('button', 'btn perigo', 'Excluir obra'); excluir.type = 'button';
    excluir.addEventListener('click', async function () {
      if (!confirm('Excluir “' + nome + '” do celular? Só as cópias baixadas são apagadas; o notebook não é afetado.')) return;
      for (var i = 0; i < caps.length; i++) await apagarCapitulo(caps[i].id);
      await limparObrasVazias(); aviso('Obra excluída do celular.'); location.hash = '#/baixadas';
    });
    var g = el('div', 'topo-acoes'); g.append(voltar, excluir); cab.append(g);
    var ul = el('ul', 'lista');
    caps.forEach(function (c) {
      var li = el('li'); var a = el('a', 'cap'); a.href = 'leitor.html?c=' + enc(c.id);
      var pos = lembrar('pos:' + c.id);
      a.append(el('span', 'cap-t', c.rotulo || c.id), el('span', 'cap-s' + (c.traduzido ? ' ok' : ''), c.paginas + ' pág. · ' + (c.traduzido ? 'traduzido' : 'só original') + (pos ? ' · parou na pág. ' + (Number(pos) + 1) : '')));
      var x = el('button', 'x', '✕'); x.type = 'button'; x.setAttribute('aria-label', 'Excluir ' + (c.rotulo || c.id)); x.title = 'Excluir este capítulo do celular';
      x.addEventListener('click', async function () {
        if (!confirm('Excluir “' + (c.rotulo || c.id) + '” do celular?')) return;
        await apagarCapitulo(c.id); await limparObrasVazias(); aviso('Capítulo excluído.'); rotear();
      });
      li.append(a, x); ul.append(li);
    });
    tela.append(cab, ul);
  }

  /* ---------------- atualização do app (o notebook busca o APK novo no GitHub e entrega; o Android pede a confirmação) ---------------- */
  var atualizacaoNova = null;                                   // {versao, nome, tamanho} quando há APK mais novo que este
  function versaoInstalada() { var m = /(\d+)\s*$/.exec(String(window.APP_VERSAO || '')); return m ? parseInt(m[1], 10) : null; }
  async function verificarAtualizacao() {
    var r = await fetchAuth('/api/app/atualizacao', { limite: 45000 }), j = await r.json(), atual = versaoInstalada();
    if (!j.disponivel) return { novo: false, motivo: j.motivo || 'Sem informação de atualização.' };
    var novo = atual !== null && j.versao > atual;
    atualizacaoNova = novo ? j : null;
    return { novo: novo, info: j, atual: atual };
  }
  async function instalarAtualizacao(aoProgredir) {
    var SZ = plugin('SalvarZip'), conf = cfg();
    if (!SZ || !SZ.instalarApk) throw new Error('A instalação só funciona no app instalado no celular.');
    garantirOuvinte(SZ); progressoNativo = aoProgredir;
    try { await SZ.instalarApk({ url: conf.base + '/api/app/apk', headers: { Authorization: 'Bearer ' + conf.chave }, id: 'apk' }); }
    catch (e) {
      if (e && (e.message === 'permissao' || e === 'permissao')) throw new Error('Libere “Instalar apps desconhecidos” para o Baixador Leitor na tela que abriu, volte ao app e toque em Baixar e instalar de novo.');
      throw e;
    } finally { progressoNativo = null; }
  }
  function blocoAtualizacao() {
    var b = el('section', 'bloco'); b.append(el('h2', '', 'Atualização do app'));
    var inst = versaoInstalada();
    b.append(el('p', 'nota', 'Versão instalada: ' + (inst === null ? 'de desenvolvimento' : window.APP_VERSAO) + '. Para ter uma versão nova: compile no GitHub (Actions → Compilar APK) e depois toque aqui. O notebook precisa estar ligado e com internet.'));
    var res = el('p', 'msg'); res.setAttribute('role', 'status');
    var linha = el('div', 'linha'), procurar = el('button', 'btn', 'Procurar atualização'); procurar.type = 'button';
    var instalar = el('button', 'btn principal', 'Baixar e instalar'); instalar.type = 'button'; instalar.hidden = true;
    var prog = el('progress'); prog.hidden = true; prog.max = 1; prog.value = 0;
    function mostrarNova(j) { instalar.hidden = false; instalar.textContent = 'Baixar e instalar a versão ' + j.versao + (j.tamanho ? ' (' + mb(j.tamanho) + ')' : ''); res.className = 'msg ok'; res.textContent = 'Há uma versão nova: ' + (j.nome || j.versao) + '.'; }
    if (atualizacaoNova) mostrarNova(atualizacaoNova);
    procurar.addEventListener('click', async function () {
      if (!cfg()) { res.className = 'msg'; res.textContent = 'Conecte ao notebook primeiro.'; return; }
      procurar.disabled = true; instalar.hidden = true; res.className = 'msg'; res.textContent = 'Perguntando ao notebook (ele consulta o GitHub)…';
      try {
        var r = await verificarAtualizacao();
        if (r.novo) mostrarNova(r.info);
        else if (r.motivo) { res.textContent = r.motivo; }
        else { res.className = 'msg ok'; res.textContent = r.atual === null ? 'Versão de desenvolvimento: não dá para comparar. Última no GitHub: ' + r.info.nome + '.' : 'Você já está na versão mais recente (' + r.info.nome + ').'; }
      } catch (e) { res.className = 'msg'; res.textContent = mensagemErro(e); } finally { procurar.disabled = false; }
    });
    instalar.addEventListener('click', async function () {
      procurar.disabled = instalar.disabled = true; prog.hidden = false; prog.value = 0; res.className = 'msg'; res.textContent = 'O notebook está buscando o APK no GitHub (só na primeira vez) e enviando ao celular…';
      try {
        await instalarAtualizacao(function (rec, tot) { prog.max = tot || 1; prog.value = tot ? rec : 0; res.textContent = 'Baixando… ' + (tot ? Math.round(rec / tot * 100) + '%' : mb(rec)); });
        res.className = 'msg ok'; res.textContent = 'Pronto: confirme “Atualizar” na tela do Android. Suas obras baixadas continuam no celular.';
      } catch (e) { res.className = 'msg'; res.textContent = mensagemErro(e); } finally { procurar.disabled = instalar.disabled = false; prog.hidden = true; }
    });
    linha.append(procurar, instalar); b.append(res, prog, linha);
    return b;
  }

  /* ---------------- tela: ajustes ---------------- */
  function mb(n) { return n >= 1e9 ? (n / 1e9).toFixed(1) + ' GB' : Math.round(n / 1e6) + ' MB'; }
  async function telaAjustes(eu) {
    var tela = $('tela'); marcarAba('ajustes'); tela.replaceChildren(el('h1', '', 'Ajustes'));
    var c = cfg();
    var bConexao = el('section', 'bloco'); bConexao.append(el('h2', '', 'Notebook'));
    bConexao.append(el('p', 'nota', c ? 'Conectado a ' + nomeHost(c.base) : 'Não conectado.'));
    var res = el('p', 'msg'); res.setAttribute('role', 'status');
    var linha = el('div', 'linha');
    if (c) {
      var testar = el('button', 'btn', 'Testar conexão'); testar.type = 'button';
      testar.addEventListener('click', async function () {
        testar.disabled = true; res.className = 'msg'; res.textContent = 'Testando…'; var t0 = Date.now();
        try { var r = await fetchAuth('/api/app/ping', { limite: 15000 }), j = await r.json(); res.className = 'msg ok'; res.textContent = 'OK: notebook respondeu em ' + (Date.now() - t0) + ' ms.'; }
        catch (e) { res.className = 'msg'; res.textContent = mensagemErro(e); } finally { testar.disabled = false; }
      });
      var desc = el('button', 'btn perigo', 'Desconectar'); desc.type = 'button';
      desc.addEventListener('click', function () { if (!confirm('Desconectar deste notebook? As obras já baixadas continuam no celular.')) return; esquecerCfg(); cacheOnline = null; try { sessionStorage.removeItem('baixador-online'); } catch (_) {} setEstado(false, ''); aviso('Desconectado.'); rotear(); });
      linha.append(testar, desc);
    }
    var par = el('a', 'btn' + (c ? '' : ' principal'), c ? 'Parear de novo' : 'Conectar'); par.href = '#/conectar'; linha.append(par);
    bConexao.append(res, linha);

    var bArm = el('section', 'bloco'); bArm.append(el('h2', '', 'Armazenamento'));
    var uso = el('p', 'nota', 'Calculando…'); bArm.append(uso);
    try { var e = navigator.storage && navigator.storage.estimate ? await navigator.storage.estimate() : null; uso.textContent = e ? 'Em uso pelo app: ' + mb(e.usage) + '.' : 'O sistema não informa o uso.'; } catch (_) { uso.textContent = 'O sistema não informa o uso.'; }

    var bDados = el('section', 'bloco'); bDados.append(el('h2', '', 'Obras baixadas'));
    var l2 = el('div', 'linha');
    var imp = el('button', 'btn', 'Importar ZIP do celular'); imp.type = 'button'; imp.title = 'Para ZIPs salvos em Download/Baixador (ou enviados por outro meio)';
    imp.addEventListener('click', function () { $('arquivos').click(); });
    var apagar = el('button', 'btn perigo', 'Apagar todas as baixadas'); apagar.type = 'button';
    apagar.addEventListener('click', async function () {
      if (!confirm('Apagar TODAS as obras baixadas deste celular? O notebook não é afetado.')) return;
      var d = await bd(), t = d.transaction(['obras', 'caps', 'imgs'], 'readwrite');
      ['obras', 'caps', 'imgs'].forEach(function (n) { t.objectStore(n).clear(); }); await concluida(t); aviso('Tudo apagado.'); rotear();
    });
    l2.append(imp, apagar); bDados.append(el('p', 'nota', 'Os ZIPs salvos em Download/Baixador não são apagados por aqui.'), l2);

    var bSobre = el('section', 'bloco'); bSobre.append(el('h2', '', 'Sobre'));
    bSobre.append(el('p', 'nota', 'Versão ' + (window.APP_VERSAO === '__VERSAO__' ? 'de desenvolvimento' : window.APP_VERSAO) + '.'));
    bSobre.append(el('p', 'nota', 'Fora de casa: deixe o Tailscale ligado no celular e o notebook ligado, conectado e sem suspender.'));
    if (vivo(eu)) tela.append(bConexao, blocoAtualizacao(), bArm, bDados, bSobre);
  }

  /* ---------------- rotas ---------------- */
  async function rotear() {
    var eu = ++rotaAtual; sair();
    var h = decodeURIComponent((location.hash || '#/').slice(1)), p = h.split('/'), resto = p.slice(2).join('/');
    try {
      if (p[1] === 'conectar') telaConectar();
      else if (p[1] === 'online' && resto) await telaOnlineObra(eu, resto);
      else if (p[1] === 'baixadas') await telaBaixadas(eu);
      else if (p[1] === 'obra' && resto) await telaObra(eu, resto);
      else if (p[1] === 'ler' && resto) { location.replace('leitor.html?c=' + enc(resto)); return; }   // rota antiga: o leitor agora é a página leitor.html
      else if (p[1] === 'ajustes') await telaAjustes(eu);
      else if (!cfg()) { var n = (await todos('caps')).length; location.hash = n ? '#/baixadas' : '#/conectar'; }
      else if (navigator.onLine === false) { location.hash = '#/baixadas'; }
      else await telaOnline(eu);
    } catch (e) { if (vivo(eu)) $('tela').replaceChildren(vazio('Algo deu errado', mensagemErro(e))); }
    if (vivo(eu) && p[1] !== 'ler') window.scrollTo(0, 0);
  }
  window.addEventListener('hashchange', rotear);
  $('arquivos').addEventListener('change', function (ev) {
    var lista = Array.prototype.slice.call(ev.target.files || []); ev.target.value = '';
    if (lista.length) { aviso('Importando… não feche o app.'); importarArquivos(lista); }
  });
  window.addEventListener('beforeunload', soltarUrls);
  /* Botão voltar do celular: sobe um nível (obra -> lista, abas -> início) e só no início fecha o app. Sem este tratamento o Android fecha o app direto. */
  var nativoApp = plugin('App');
  if (nativoApp && nativoApp.addListener) nativoApp.addListener('backButton', function () {
    var h = location.hash || '#/';
    if (h === '#/' || h === '#/conectar') { nativoApp.exitApp(); return; }
    var pai = h.indexOf('#/obra/') === 0 ? '#/baixadas' : '#/';
    location.replace(location.pathname + location.search + pai);                  // replace: não deixa voltas extras no histórico
  });
  /* O leitor (cópia da web) manda para "/leitor?c=…" e "/?obra=…": no app, a primeira é a página leitor.html e a segunda, a tela da obra. */
  (function () {
    var q = new URLSearchParams(location.search);
    if (location.pathname === '/leitor') { location.replace('leitor.html' + location.search); return; }
    if (q.get('obra')) {
      history.replaceState(null, '', location.pathname);
      location.hash = (cfg() && navigator.onLine !== false ? '#/online/' : '#/obra/') + encodeURIComponent(q.get('obra'));
    }
  })();
  /* Recuperação sem laço: ao voltar para o app ou quando a rede volta, se a conexão estava ruim, tenta UMA vez (no máximo a cada 5 s). */
  var ultimaRecuperacao = 0;
  function recuperar() {
    var e = $('estado'), agora = Date.now();
    if (!cfg() || !e || !/ruim/.test(e.className) || agora - ultimaRecuperacao < 5000) return;
    if (/^#\/(conectar|ajustes|ler|obra|baixadas)/.test(location.hash || '')) return;
    ultimaRecuperacao = agora; rotear();
  }
  window.addEventListener('online', recuperar);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) recuperar(); });
  restaurarCfg().then(rotear, rotear);
})();
