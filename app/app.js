/* Leitor offline (PWA). As obras ficam no armazenamento do próprio celular (IndexedDB); nada vai para a internet.
   O app é só código: as obras entram por "Importar", com o ZIP gerado no notebook (Biblioteca → Exportar para o app). */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  function el(tag, classe, texto) { var e = document.createElement(tag); if (classe) e.className = classe; if (texto != null) e.textContent = texto; return e; }
  function guardar(k, v) { try { localStorage.setItem(k, v); } catch (_) {} }
  function lembrar(k) { try { return localStorage.getItem(k); } catch (_) { return null; } }
  var tempo = null;
  function aviso(t) { var a = $('toast'); a.textContent = t; a.hidden = false; clearTimeout(tempo); tempo = setTimeout(function () { a.hidden = true; }, 4200); }

  /* ---------------- banco local ---------------- */
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

  /* ---------------- importar o ZIP do notebook ---------------- */
  var TIPOS = { jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', webp: 'image/webp', gif: 'image/gif', avif: 'image/avif', bmp: 'image/bmp' };
  var tipoDe = function (nome) { return TIPOS[(nome.split('.').pop() || '').toLowerCase()] || 'application/octet-stream'; };

  async function importar(arquivos) {
    var botao = $('importar'); botao.disabled = true;
    var feitos = 0, falhas = [];
    try {
      for (var a = 0; a < arquivos.length; a++) {
        var f = arquivos[a];
        try { feitos += await importarUm(f); }
        catch (e) { falhas.push(f.name + ': ' + mensagemErro(e)); }
      }
    } finally { botao.disabled = false; }
    if (feitos) { pedirArmazenamentoPermanente(); }
    aviso(falhas.length ? 'Importação com problema — ' + falhas[0] : feitos + ' capítulo(s) importado(s).');
    rotear();
  }
  function mensagemErro(e) { return e && e.name === 'QuotaExceededError' ? 'sem espaço no celular (apague capítulos que já leu)' : (e && e.message) || String(e); }

  async function importarUm(arquivo) {
    var z = await LerZip.abrir(arquivo);
    if (!z.tem('baixador-export.json')) throw new Error('não é um arquivo exportado pelo Baixador.');
    var man = JSON.parse(await z.texto('baixador-export.json'));
    if (man.formato !== 1) throw new Error('formato de exportação desconhecido (' + man.formato + '); atualize o app.');
    var progresso = $('progresso-import');
    var capas = {};
    for (var i = 0; i < man.obras.length; i++) {
      var o = man.obras[i];
      capas[o.nome] = o.capa && z.tem(o.capa) ? await z.blob(o.capa, tipoDe(o.capa)) : null;
    }
    var n = 0;
    for (var k = 0; k < man.capitulos.length; k++) {
      var c = man.capitulos[k], nomeObra = man.obras[c.obra].nome;
      if (progresso) { progresso.max = man.capitulos.length; progresso.value = k; }
      var dados = JSON.parse(await z.texto(c.dir + '/capitulo.json'));
      var pares = [];
      for (var j = 0; j < dados.imagens.length; j++) {
        var im = dados.imagens[j];
        if (z.tem(c.dir + '/img/' + im.arq)) pares.push({ chave: c.id + '|' + im.arq, blob: await z.blob(c.dir + '/img/' + im.arq, tipoDe(im.arq)) });
      }
      var d = await bd(), t = d.transaction(['caps', 'imgs', 'obras'], 'readwrite');
      t.objectStore('imgs').delete(faixaCap(c.id));
      pares.forEach(function (p) { t.objectStore('imgs').put(p); });
      t.objectStore('caps').put({
        id: c.id, obra: nomeObra, rotulo: c.rotulo, numero: c.numero, titulo: c.titulo, paginas: pares.length, traduzido: !!c.traduzido,
        dados: { titulo: dados.titulo, imagens: dados.imagens }, importado: Date.now(),
      });
      var atual = await pedido(t.objectStore('obras').get(nomeObra));
      t.objectStore('obras').put({ nome: nomeObra, capa: capas[nomeObra] || (atual && atual.capa) || null });
      await concluida(t);
      n++;
    }
    return n;
  }
  async function pedirArmazenamentoPermanente() {
    try { if (navigator.storage && navigator.storage.persist) await navigator.storage.persist(); } catch (_) {}
  }

  /* ---------------- telas ---------------- */
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
  function sair() { soltarUrls(); document.body.classList.remove('leitor', 'original'); window.onscroll = null; }

  async function telaObras() {
    var tela = $('tela'), obras = await todos('obras'), caps = await todos('caps');
    tela.replaceChildren();
    if (!obras.length) {
      tela.append(vazio('Nenhuma obra aqui ainda', 'No notebook: Biblioteca → abra a obra → Mais ações → Exportar para o app… Depois toque em Importar e escolha o arquivo ZIP.'));
      return;
    }
    obras.sort(function (a, b) { return a.nome.localeCompare(b.nome, 'pt', { sensitivity: 'base' }); });
    var grade = el('div', 'capas');
    obras.forEach(function (o) {
      var meus = caps.filter(function (c) { return c.obra === o.nome; });
      var a = el('a', 'capa'); a.href = '#/obra/' + encodeURIComponent(o.nome);
      var img = el('div', 'capa-img');
      if (o.capa) { var i = el('img'); i.alt = ''; i.src = url(o.capa); img.append(i); } else img.append(el('span', 'capa-inicial', (o.nome.trim()[0] || '?').toUpperCase()));
      a.append(img, el('span', 'capa-nome', o.nome), el('span', 'capa-sub', meus.length + ' capítulo' + (meus.length === 1 ? '' : 's') + ' · ' + meus.reduce(function (s, c) { return s + c.paginas; }, 0) + ' pág.'));
      grade.append(a);
    });
    tela.append(grade);
  }

  async function telaObra(nome) {
    var tela = $('tela'), caps = ordenar((await todos('caps')).filter(function (c) { return c.obra === nome; })).reverse();
    tela.replaceChildren();
    if (!caps.length) { location.hash = '#/'; return; }
    var cab = el('div', 'barra-obra'); cab.append(el('h1', '', nome));
    var voltar = el('a', 'btn', '‹ Obras'); voltar.href = '#/';
    var excluir = el('button', 'btn perigo', 'Excluir obra'); excluir.type = 'button';
    excluir.addEventListener('click', async function () {
      if (!confirm('Excluir “' + nome + '” do celular? As imagens e traduções importadas serão apagadas daqui (o notebook não é afetado).')) return;
      for (var i = 0; i < caps.length; i++) await apagarCapitulo(caps[i].id);
      await limparObrasVazias(); aviso('Obra excluída do celular.'); location.hash = '#/';
    });
    var g = el('div', 'topo-acoes'); g.append(voltar, excluir); cab.append(g);
    var ul = el('ul', 'lista');
    caps.forEach(function (c) {
      var li = el('li'); var a = el('a', 'cap'); a.href = '#/ler/' + encodeURIComponent(c.id);
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

  async function telaLeitor(id) {
    var tela = $('tela'), cap = await obter('caps', id);
    if (!cap) { aviso('Capítulo não encontrado.'); location.hash = '#/'; return; }
    var irmaos = ordenar((await todos('caps')).filter(function (c) { return c.obra === cap.obra; })), pos = irmaos.findIndex(function (c) { return c.id === id; });
    var ant = irmaos[pos - 1], prox = irmaos[pos + 1];
    var blobs = {}; (await todos('imgs', faixaCap(id))).forEach(function (r) { blobs[r.chave] = r.blob; });
    document.body.classList.add('leitor'); document.body.classList.toggle('original', lembrar('idioma') === 'original');
    document.title = cap.obra + ' — ' + cap.rotulo;
    tela.replaceChildren();
    var paginas = el('div', 'paginas'); var figuras = [], carregadas = [];
    cap.dados.imagens.forEach(function (im) {
      var blob = blobs[id + '|' + im.arq]; if (!blob) return;
      var fig = el('figure'); fig.dataset.n = String(figuras.length);
      if (im.medidas && im.blocos.length) { fig.className = 'com-medidas'; fig.style.aspectRatio = im.medidas[0] + '/' + im.medidas[1]; fig.dataset.w = im.medidas[0]; fig.dataset.h = im.medidas[1]; }
      var img = el('img'); img.alt = 'Página ' + (figuras.length + 1); img.decoding = 'async'; img.src = url(blob);
      carregadas.push(new Promise(function (ok) { img.onload = img.onerror = ok; }));
      fig.append(img);
      im.blocos.forEach(function (b) {
        var t = el('div', 'tr'); t.title = b.original || '';
        t.style.left = b.x + '%'; t.style.top = b.y + '%'; t.style.width = b.w + '%'; t.style.height = b.h + '%'; t.style.background = b.fundo; t.style.color = b.cor;
        if (b.fonte > 0) t.dataset.f = b.fonte; if (b.refer > 0) t.dataset.r = b.refer; if (b.livre) t.dataset.lv = JSON.stringify(b.livre);
        t.textContent = b.texto; fig.append(t);
      });
      paginas.append(fig); figuras.push(fig);
    });
    var barra = el('nav', 'leitor-barra'); barra.hidden = true; barra.setAttribute('aria-label', 'Controles do leitor');
    var esq = el('div', 'grupo'), dir = el('div', 'grupo');
    var obraB = el('a', 'btn', '‹ Obra'); obraB.href = '#/obra/' + encodeURIComponent(cap.obra);
    var idioma = el('button', 'btn', 'Original'); idioma.type = 'button'; idioma.setAttribute('aria-pressed', String(document.body.classList.contains('original')));
    idioma.disabled = !cap.traduzido; idioma.title = 'Alternar entre a tradução e a imagem original';
    idioma.addEventListener('click', function () { var o = document.body.classList.toggle('original'); idioma.setAttribute('aria-pressed', String(o)); guardar('idioma', o ? 'original' : 'traduzido'); });
    var link = function (txt, c, rot) { var a = el('a', 'btn', txt); a.setAttribute('aria-label', rot); if (c) a.href = '#/ler/' + encodeURIComponent(c.id); else a.setAttribute('aria-disabled', 'true'); return a; };
    var ind = el('span', 'pos', '1/' + figuras.length);
    esq.append(obraB, idioma); dir.append(link('‹', ant, 'Capítulo anterior'), ind, link('›', prox, 'Próximo capítulo'));
    barra.append(esq, dir);
    var fim = el('p', 'fim', 'Fim de “' + cap.dados.titulo + '” — ' + figuras.length + ' página(s).');
    var nav = el('nav', 'navcap'); nav.setAttribute('aria-label', 'Capítulos');
    var v = el('a', 'btn', '‹ Obra'); v.href = obraB.getAttribute('href'); nav.append(v);
    if (prox) { var p = el('a', 'btn principal', 'Próximo ›'); p.href = '#/ler/' + encodeURIComponent(prox.id); nav.append(p); }
    tela.append(barra, paginas, fim, nav);
    if (window.AjusteTexto) window.AjusteTexto.ajustarTudo();
    if ('ResizeObserver' in window) new ResizeObserver(function () { window.AjusteTexto.ajustarTudo(); }).observe(paginas);
    paginas.addEventListener('dblclick', function () { barra.hidden = !barra.hidden; });
    var atual = 0, agendado = false;
    function marcar() {
      agendado = false; var ref = window.innerHeight * 0.3, k = 0;
      for (var i = 0; i < figuras.length; i++) { if (figuras[i].getBoundingClientRect().top <= ref) k = i; else break; }
      if (k !== atual || !ind.dataset.ok) { atual = k; ind.dataset.ok = '1'; ind.textContent = (k + 1) + '/' + figuras.length; guardar('pos:' + id, String(k)); }
    }
    window.onscroll = function () { if (!agendado) { agendado = true; requestAnimationFrame(marcar); } };
    var salvo = parseInt(lembrar('pos:' + id), 10);
    if (salvo > 0 && salvo < figuras.length) {          // volta de onde parou, depois que as imagens de cima têm altura
      Promise.race([Promise.all(carregadas.slice(0, salvo + 1)), new Promise(function (ok) { setTimeout(ok, 4000); })]).then(function () {
        window.AjusteTexto.ajustarTudo(); figuras[salvo].scrollIntoView(); marcar();
      });
    } else window.scrollTo(0, 0);
  }

  async function telaAjustes() {
    var tela = $('tela'); tela.replaceChildren(el('h1', '', 'Ajustes'));
    var blocoApp = el('section', 'bloco'); blocoApp.append(el('h2', '', 'Aplicativo'));
    var versao = el('p', 'nota', 'Versão: …'); var estado = el('p', 'nota', '');
    var linha = el('div', 'linha');
    var verificar = el('button', 'btn', 'Verificar atualização'); verificar.type = 'button';
    var aplicar = el('button', 'btn principal', 'Atualizar agora'); aplicar.type = 'button'; aplicar.hidden = !esperando;
    var reinstalar = el('button', 'btn', 'Reinstalar o app'); reinstalar.type = 'button'; reinstalar.title = 'Apaga só o código guardado do app e baixa de novo. Suas obras não são apagadas.';
    verificar.addEventListener('click', async function () { verificar.disabled = true; estado.textContent = 'Verificando…'; estado.textContent = await verificarAtualizacao(); aplicar.hidden = !esperando; verificar.disabled = false; });
    aplicar.addEventListener('click', aplicarAtualizacao);
    reinstalar.addEventListener('click', async function () {
      if (!confirm('Reinstalar o app? Precisa de internet. Suas obras importadas continuam no celular.')) return;
      try { var rs = await navigator.serviceWorker.getRegistrations(); await Promise.all(rs.map(function (r) { return r.unregister(); })); var ks = await caches.keys(); await Promise.all(ks.filter(function (k) { return k.indexOf('baixador-app-') === 0; }).map(function (k) { return caches.delete(k); })); } catch (_) {}
      location.reload();
    });
    linha.append(verificar, aplicar, reinstalar); blocoApp.append(versao, estado, linha);
    versaoDoApp().then(function (v) { versao.textContent = 'Versão: ' + v; });

    var blocoArm = el('section', 'bloco'); blocoArm.append(el('h2', '', 'Armazenamento'));
    var uso = el('p', 'nota', 'Calculando…'); var perm = el('p', 'nota', '');
    blocoArm.append(uso, perm);
    try {
      var e = navigator.storage && navigator.storage.estimate ? await navigator.storage.estimate() : null;
      uso.textContent = e ? 'Em uso: ' + mb(e.usage) + ' de aproximadamente ' + mb(e.quota) + ' disponíveis.' : 'O navegador não informa o uso.';
      var p = navigator.storage && navigator.storage.persisted ? await navigator.storage.persisted() : false;
      perm.textContent = p ? 'Armazenamento permanente: o celular não apaga suas obras sozinho.' : 'Armazenamento não permanente: se faltar espaço, o celular pode apagar os dados do app. Instalar o app na tela inicial ajuda.';
      if (!p && navigator.storage && navigator.storage.persist) {
        var pedir = el('button', 'btn', 'Pedir armazenamento permanente'); pedir.type = 'button';
        pedir.addEventListener('click', async function () { var r = await navigator.storage.persist(); aviso(r ? 'Armazenamento permanente concedido.' : 'O navegador não concedeu (instale o app na tela inicial e tente de novo).'); telaAjustes(); });
        var l2 = el('div', 'linha'); l2.append(pedir); blocoArm.append(l2);
      }
    } catch (_) { uso.textContent = 'O navegador não informa o uso.'; }

    var blocoDados = el('section', 'bloco'); blocoDados.append(el('h2', '', 'Obras no celular'));
    var apagar = el('button', 'btn perigo', 'Apagar todas as obras do celular'); apagar.type = 'button';
    apagar.addEventListener('click', async function () {
      if (!confirm('Apagar TODAS as obras importadas deste celular? O notebook não é afetado.')) return;
      var d = await bd(), t = d.transaction(['obras', 'caps', 'imgs'], 'readwrite');
      ['obras', 'caps', 'imgs'].forEach(function (n) { t.objectStore(n).clear(); }); await concluida(t); aviso('Tudo apagado.'); telaAjustes();
    });
    var l3 = el('div', 'linha'); l3.append(apagar); blocoDados.append(el('p', 'nota', 'Importadas por você a partir do notebook; apagar aqui não mexe na biblioteca do notebook.'), l3);
    tela.append(blocoApp, blocoArm, blocoDados);
  }
  function mb(n) { return n >= 1e9 ? (n / 1e9).toFixed(1) + ' GB' : Math.round(n / 1e6) + ' MB'; }

  /* ---------------- atualização do app (service worker) ---------------- */
  var reg = null, esperando = null, tinhaControlador = false, recarregando = false;
  function nova(w) { esperando = w; $('atualiza').hidden = false; }
  function aplicarAtualizacao() { if (esperando) esperando.postMessage('PULAR_ESPERA'); }
  async function registrar() {
    if (!('serviceWorker' in navigator)) return;
    tinhaControlador = !!navigator.serviceWorker.controller;
    navigator.serviceWorker.addEventListener('controllerchange', function () { if (tinhaControlador && !recarregando) { recarregando = true; location.reload(); } });
    try {
      reg = await navigator.serviceWorker.register('./sw.js');
      if (reg.waiting && navigator.serviceWorker.controller) nova(reg.waiting);
      reg.addEventListener('updatefound', function () {
        var w = reg.installing; if (!w) return;
        w.addEventListener('statechange', function () { if (w.state === 'installed' && navigator.serviceWorker.controller) nova(w); });
      });
      if (navigator.onLine) reg.update().catch(function () {});
    } catch (_) { /* sem service worker (ex.: http fora do localhost): o app funciona, só não fica offline */ }
  }
  async function verificarAtualizacao() {
    if (!reg) return 'Este navegador não permite o modo offline/atualização do app (precisa de HTTPS).';
    if (!navigator.onLine) return 'Sem internet agora: não dá para verificar.';
    try { await reg.update(); } catch (_) { return 'Não consegui consultar o servidor. Tente de novo com internet.'; }
    var w = reg.installing;
    if (w) await new Promise(function (ok) { var t = setTimeout(ok, 20000); w.addEventListener('statechange', function () { if (w.state === 'installed' || w.state === 'redundant') { clearTimeout(t); ok(); } }); });
    if (reg.waiting && navigator.serviceWorker.controller) { nova(reg.waiting); return 'Há uma versão nova pronta. Toque em “Atualizar agora”.'; }
    return 'Você já está na versão mais recente.';
  }
  function versaoDoApp() {
    return new Promise(function (ok) {
      var c = navigator.serviceWorker && navigator.serviceWorker.controller; if (!c) return ok('sem modo offline');
      var canal = new MessageChannel(); canal.port1.onmessage = function (e) { ok(e.data === '__VERSAO__' ? 'desenvolvimento' : e.data); };
      c.postMessage('VERSAO', [canal.port2]); setTimeout(function () { ok('desconhecida'); }, 1500);
    });
  }

  /* ---------------- rotas ---------------- */
  var emRota = 0;
  async function rotear() {
    var eu = ++emRota; sair();
    var h = decodeURIComponent((location.hash || '#/').slice(1)), partes = h.split('/');
    try {
      if (partes[1] === 'obra' && partes[2]) await telaObra(partes.slice(2).join('/'));
      else if (partes[1] === 'ler' && partes[2]) await telaLeitor(partes.slice(2).join('/'));
      else if (partes[1] === 'ajustes') await telaAjustes();
      else await telaObras();
    } catch (e) { if (eu === emRota) $('tela').replaceChildren(vazio('Algo deu errado', mensagemErro(e))); }
    if (eu === emRota && partes[1] !== 'ler') window.scrollTo(0, 0);
  }
  window.addEventListener('hashchange', rotear);
  $('importar').addEventListener('click', function () { $('arquivos').click(); });
  $('arquivos').addEventListener('change', async function (ev) {
    var lista = Array.prototype.slice.call(ev.target.files || []); ev.target.value = '';
    if (!lista.length) return;
    var tela = $('tela'), p = el('progress'); p.id = 'progresso-import'; p.value = 0; p.max = 1; tela.prepend(p); aviso('Importando… não feche o app.');
    await importar(lista);
  });
  $('atualiza-ok').addEventListener('click', aplicarAtualizacao);
  document.addEventListener('visibilitychange', function () { if (!document.hidden && reg && navigator.onLine) reg.update().catch(function () {}); });
  document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') { var b = document.querySelector('.leitor-barra'); if (b) b.hidden = true; } });
  window.addEventListener('beforeunload', soltarUrls);
  registrar(); rotear();
})();
