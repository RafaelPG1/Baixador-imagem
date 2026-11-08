"""Modo manual: o navegador abre visível, o usuário prepara a página e escolhe as imagens.

Fluxo: abrir o site → o usuário faz o que for preciso na janela (login, cliques, esperar)
→ "procurar imagens" lê o que a página mostra naquele momento → o usuário marca as
desejadas → "baixar marcadas" grava no disco.

Por que uma thread dedicada: o Playwright (API síncrona) só pode ser usado pela thread que o
criou. Todo o trabalho com o navegador acontece numa thread própria que recebe comandos por
uma fila; o servidor da interface só enfileira comandos e lê o estado.

As imagens encontradas ficam só na memória (com limite) até serem gravadas ou descartadas.
"""

from __future__ import annotations

import hashlib
import re
import queue
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from baixador.nucleo import seguranca
from baixador.nucleo.sequencia import dimensoes_suspeitas, numeros_ausentes
from baixador.navegador.captura import Capturador, _resumo
from baixador.nucleo.erros import (
    ArquivoGrande,
    Cancelado,
    ErroBaixador,
    ErroDeRede,
    ErroHttp,
)
from baixador.nucleo.imagens import decodificar_data_uri, detectar_formato, nome_arquivo, preparar_pasta
from baixador.nucleo.imagens import salvar as gravar_arquivo

MAX_CANDIDATAS = 200                  # imagens na lista ao mesmo tempo
LIMITE_MEMORIA = 300 * 1024 * 1024    # total de bytes mantidos na lista
LIMITE_IMAGEM = 20 * 1024 * 1024      # tamanho máximo de cada imagem
MAX_PRINTS_POR_BUSCA = 15             # capturas de tela de elementos por busca
MAX_RESPOSTAS_GUARDADAS = 5000
MAX_SONDAS = 40                       # tentativas de obter números que faltam numa sequência
MODOS_BUSCA = ("carregamento", "rapido")   # B (cuidadosa) e C (rápida e adaptativa, a padrão)
MAX_LINHAS_LOG = 2000
TEMPO_ABERTURA_MS = 30_000

# Imagens com endereço que ainda não terminaram de carregar.
_JS_PENDENTES = "() => [...document.images].filter(i => (i.currentSrc || i.src) && !i.complete).length"

# Imagens "lazy" do navegador passam a carregar já; devolve quantas ainda não carregaram.
_JS_PREPARAR_LAZY = """
() => {
  document.querySelectorAll('img[loading="lazy"]').forEach(i => { i.loading = 'eager'; });
  return [...document.images].filter(i => !(i.complete && i.naturalWidth > 0)).length;
}
"""

# Leva à tela a próxima imagem ainda não carregada (dispara carregadores baseados em rolagem).
_JS_MOSTRAR_PROXIMA = """
() => {
  const vistos = (window.__baixadorVistos = window.__baixadorVistos || new WeakSet());
  const alvo = [...document.images].find(i => !(i.complete && i.naturalWidth > 0) && !vistos.has(i));
  if (!alvo) return false;
  vistos.add(alvo);
  alvo.scrollIntoView({block: 'center'});
  return true;
}
"""

# Uma nova tentativa (só uma) nas imagens que falharam ao carregar.
_JS_REINTENTAR = """
() => {
  let n = 0;
  for (const i of document.images) {
    const s = i.getAttribute('src');
    if (s && i.complete && i.naturalWidth === 0 && !i.dataset.baixadorRetry) {
      i.dataset.baixadorRetry = '1';
      i.removeAttribute('src');
      i.setAttribute('src', s);
      n++;
    }
  }
  return n;
}
"""

# Lê as imagens da página. Com `ignorar`, descarta as de comentários e avatares:
#  1) dentro de um bloco cujo id/classe indica comentário, avatar, emoji, resposta...;
#  2) abaixo de um título "Comentários" que esteja na parte de baixo da página.
# Blocos que contêm a maior parte das imagens da página (um contêiner geral) nunca valem.
_JS_COLETAR = """
(opcoes) => {
  const imgs = [...document.images];
  const total = imgs.length;
  const limite = Math.max(2, Math.ceil(total * 0.6));
  const SEL = [
    '[id*="comment" i]', '[class*="comment" i]', '[id*="coment" i]', '[class*="coment" i]',
    '[id*="disqus" i]', '[class*="disqus" i]', '[id="respond"]', '[id*="reply" i]', '[class*="reply" i]',
    '[class*="avatar" i]', '[class*="gravatar" i]', '[class*="emoji" i]', '[class*="reaction" i]',
    '[data-testid*="comment" i]', '[aria-label*="coment" i]', '[aria-label*="comment" i]'
  ].join(',');
  const marcadas = new Set();
  if (opcoes.ignorar) {
    for (const img of imgs) {
      if (img.matches(SEL)) { marcadas.add(img); continue; }
      let el = img.parentElement;
      while (el && el !== document.body && el !== document.documentElement) {
        if (el.matches(SEL) && el.querySelectorAll('img').length <= limite) { marcadas.add(img); break; }
        el = el.parentElement;
      }
    }
    const alturaDoc = Math.max(document.documentElement.scrollHeight, 1);
    const topo = (e) => e.getBoundingClientRect().top + window.scrollY;
    const TITULO = /^\\s*(\\d+\\s*)?(coment[aá]rios?|comments?|discuss[aã]o|deixe\\s+(um\\s+)?coment[aá]rio|leave\\s+a\\s+(comment|reply))\\b[\\s\\S]{0,15}$/i;
    let vistos = 0;
    const candidatos = document.querySelectorAll('h1,h2,h3,h4,h5,h6,[role="heading"],summary,legend,div,span,p,strong,b,a,button');
    for (const e of candidatos) {
      if (++vistos > 30000) break;
      if (e.children.length > 2) continue;
      const texto = (e.textContent || '').trim();
      if (texto.length > 40 || !TITULO.test(texto) || e.getClientRects().length === 0) continue;
      const y = topo(e);
      if (y < alturaDoc * 0.4) continue;           // menu ou aba no alto da página: não é a seção
      let regiao = e.parentElement;
      for (let n = 0; regiao && n < 4; n++, regiao = regiao.parentElement) {
        const dentro = [...regiao.querySelectorAll('img')];
        if (dentro.length === 0) continue;
        if (dentro.length <= limite && dentro.every(i => topo(i) >= y - 8)) dentro.forEach(i => marcadas.add(i));
        break;
      }
    }
  }
  const lista = [];
  let pendentes = 0, quebradas = 0, ignoradas = 0;
  for (const i of imgs) {
    const url = i.currentSrc || i.src;
    if (!url) continue;
    if (!i.complete) { pendentes++; continue; }
    if (i.naturalWidth === 0) { quebradas++; continue; }
    if (i.naturalWidth <= 1 && i.naturalHeight <= 1) continue;   // pixel de rastreamento
    if (marcadas.has(i)) { ignoradas++; continue; }
    lista.push({url: url, w: i.naturalWidth, h: i.naturalHeight});
  }
  return {lista: lista, pendentes: pendentes, quebradas: quebradas, ignoradas: ignoradas, total: total};
}
"""
# Sinais de "carregando" (spinner, esqueleto, barra de progresso) visíveis perto da tela.
_JS_CARREGANDO = """
() => {
  const SEL = '[class*="spinner" i],[class*="loading" i],[class*="loader" i],[class*="skeleton" i],' +
              '[class*="shimmer" i],[aria-busy="true"],[role="progressbar"],progress';
  const H = innerHeight, alturaDoc = Math.max(document.documentElement.scrollHeight, 1);
  const saida = [];
  for (const e of document.querySelectorAll(SEL)) {
    if (e === document.body || e === document.documentElement) continue;
    const r = e.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) continue;
    if (r.bottom < -H * 0.15 || r.top > H * 1.15) continue;    // fora da tela
    if (r.height > alturaDoc * 0.5) continue;                   // contêiner geral, não um indicador
    const cs = getComputedStyle(e);
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) < 0.05) continue;
    const classe = (e.className && e.className.baseVal !== undefined) ? e.className.baseVal : String(e.className || '');
    saida.push(e.tagName.toLowerCase() + '.' + classe.trim().slice(0, 50));
    if (saida.length >= 20) break;
  }
  return saida;
}
"""

# Tamanho real de uma imagem, carregada pela própria página.
_JS_DIMENSOES = """
(url) => new Promise((resolve) => {
  const i = new Image();
  i.onload = () => resolve([i.naturalWidth, i.naturalHeight]);
  i.onerror = () => resolve([0, 0]);
  setTimeout(() => resolve([0, 0]), 8000);
  i.src = url;
})
"""
# [imagens ainda carregando perto da tela, total de imagens já carregadas] (sinais de progresso).
_JS_ESTADO = """
() => {
  const H = innerHeight;
  let perto = 0, completas = 0;
  for (const i of document.images) {
    if (i.complete && i.naturalWidth > 0) { completas++; continue; }
    if (!(i.currentSrc || i.src) || i.complete) continue;     // sem endereço ou já falhou: não há o que esperar
    const r = i.getBoundingClientRect();
    if (r.bottom > -H * 0.6 && r.top < H * 1.6) perto++;
  }
  return [perto, completas];
}
"""
_JS_MARCAR = """
(url) => {
  const i = [...document.images].find(x => (x.currentSrc || x.src) === url);
  if (!i) return false;
  i.setAttribute('data-baixador-alvo', '1');
  return true;
}
"""
_JS_DESMARCAR = (
    "() => document.querySelectorAll('[data-baixador-alvo]')"
    ".forEach(e => e.removeAttribute('data-baixador-alvo'))"
)

# Procura, na página, o controle que leva ao PRÓXIMO capítulo (link rel=next, botão "Próximo", "Next chapter",
# "›", "»"…). Ignora "anterior", controles ocultos e o que fica nos comentários. Marca o melhor candidato com um
# atributo para o Playwright clicar nele (clique real: funciona em sites que trocam de capítulo por JavaScript).
SELETOR_CAPA = ".poster img, [class*=poster] img, img[srcset*='/covers/'], img[src*='/covers/']"
JS_CAPA = r"""
() => {
  const q = (s) => document.querySelector(s);
  const im = q('.poster img') || q('[class*="poster"] img') || q('img[srcset*="/covers/"]') || q('img[src*="/covers/"]');
  if (!im) { const og = q('meta[property="og:image"]'); return og && og.content ? {src: og.content, base: location.href} : null; }
  return {srcset: im.getAttribute('srcset') || im.getAttribute('data-srcset') || '', src: im.getAttribute('src') || im.getAttribute('data-src') || '',
          atual: im.currentSrc || '', base: location.href};
}
"""
JS_PROXIMO = r"""
() => {
  document.querySelectorAll('[data-baixador-prox]').forEach(e => e.removeAttribute('data-baixador-prox'));
  const NEG = /(anterior|previous|prev\b|voltar|back\b|\bprev\.?\s|«|‹|←|primeir|first|último|ultimo|last)/i;
  const POS = /(pr[óo]xim|next|seguinte|avan[çc]ar|continuar|siguiente|suivant)/i;
  const SETA = /^\s*(›|»|→|>|>>|▶|►|❯|⟩)\s*$/;
  const CAP = /(cap[íi]tulo|cap\.|chapter|ch\.|epis[óo]dio|ep\.|episode|volume|vol\.)/i;
  const visivel = e => {
    const r = e.getBoundingClientRect(), st = getComputedStyle(e);
    return r.width > 4 && r.height > 4 && st.visibility !== 'hidden' && st.display !== 'none' && st.opacity !== '0'
      && !e.closest('[hidden],[aria-hidden=true]');
  };
  const lista = [...document.querySelectorAll('a[href], link[rel~=next], button, [role=button], [role=link]')];
  let melhor = null, nota = 0;
  for (const e of lista) {
    if (e.tagName === 'LINK') {
      if (e.href && nota < 40) { melhor = {href: e.href, el: null}; nota = 40; }
      continue;
    }
    if (!visivel(e) || e.disabled || e.getAttribute('aria-disabled') === 'true') continue;
    if (e.closest('#comments, .comments, .comment, #disqus_thread, [class*=comment], [id*=comment], footer nav[class*=social]')) continue;
    const texto = (e.innerText || e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 80);
    const rotulo = ((e.getAttribute('aria-label') || '') + ' ' + (e.title || '') + ' ' + texto).trim();
    const marca = ((e.id || '') + ' ' + (typeof e.className === 'string' ? e.className : '') + ' ' + (e.getAttribute('rel') || '') + ' ' + (e.getAttribute('data-action') || '')).toLowerCase();
    if (NEG.test(rotulo) && !POS.test(rotulo)) continue;
    if (/(^|[\s_-])(prev|previous|anterior)([\s_-]|$)/.test(marca) && !/next/.test(marca)) continue;
    let n = 0;
    if (/(^|\s)next(\s|$)/i.test(e.getAttribute('rel') || '')) n += 60;
    if (POS.test(rotulo)) n += 40;
    if (SETA.test(texto)) n += 30;
    if (/(^|[\s_-])next([\s_-]|$)|proximo|proxima/.test(marca)) n += 25;
    if (!n) continue;
    if (CAP.test(rotulo) || CAP.test(marca)) n += 15;
    if (texto.length > 40) n -= 20;                          // links longos costumam ser títulos de artigos
    const y = e.getBoundingClientRect().top + scrollY, alt = document.documentElement.scrollHeight;
    if (y > alt * 0.5) n += 5;                               // navegação de capítulo costuma ficar no fim
    if (e.closest('nav, .nav, .navigation, .pagination, [class*=chapter], [class*=reader], [class*=pager]')) n += 5;
    if (n > nota) { melhor = {href: e.href || e.getAttribute('data-href') || '', el: e, texto: rotulo.slice(0, 60)}; nota = n; }
  }
  if (!melhor) return null;
  if (melhor.el) melhor.el.setAttribute('data-baixador-prox', '1');
  return {href: melhor.href || '', texto: melhor.texto || '', marcado: !!melhor.el, nota};
}
"""

LIMITE_CAPITULOS_AUTO = 300
ESTADOS_ATIVOS = ("abrindo", "aguardando", "procurando")


# --------------------------------------------------------------------------- coleção

@dataclass
class Candidata:
    id: int
    url: str
    largura: int = 0
    altura: int = 0
    dados: Optional[bytes] = None
    formato: Optional[str] = None
    origem: str = "navegador"      # "navegador" (arquivo original) ou "print" (captura de tela)
    erro: Optional[str] = None
    salva: Optional[str] = None    # nome do arquivo gravado


_RE_TAMANHO_NO_NOME = re.compile(r"-\d{2,4}x\d{2,4}(?=\.[A-Za-z0-9]{2,5}$)")


def _chave_de_variante(url: str) -> Optional[str]:
    """Endereço sem consulta e sem sufixo de tamanho (-300x200), para achar versões da mesma imagem."""
    if not url.lower().startswith(("http://", "https://")):
        return None
    try:
        partes = urlsplit(url)
    except ValueError:
        return None
    return f"{partes.netloc.lower()}{_RE_TAMANHO_NO_NOME.sub('', partes.path)}"


def _url_para_tela(url: str) -> str:
    """Nunca manda um data: URI gigante para a interface."""
    if url.lower().startswith("data:"):
        return "(imagem embutida na página)"
    return url if len(url) <= 300 else url[:297] + "..."


class Colecao:
    """Lista de imagens encontradas, com limite de memória e sem repetição de conteúdo."""

    def __init__(self, limite_memoria: int = LIMITE_MEMORIA, max_itens: int = MAX_CANDIDATAS):
        self._lock = threading.Lock()
        self._itens: Dict[int, Candidata] = {}
        self._por_url: Dict[str, int] = {}
        self._hashes: Dict[str, int] = {}
        self._memoria = 0
        self._proximo_id = 1          # nunca reinicia: miniaturas antigas não se confundem com novas
        self._contador_arquivos = 1
        self._limite_memoria = limite_memoria
        self._max_itens = max_itens
        self.versao = 0

    def precisa_tentar(self, url: str) -> bool:
        """True se a URL é nova ou se a tentativa anterior falhou (vale tentar de novo)."""
        with self._lock:
            id_ = self._por_url.get(url)
            return id_ is None or self._itens[id_].dados is None

    def cheia(self) -> bool:
        with self._lock:
            return len(self._itens) >= self._max_itens

    def adicionar(
        self, url: str, largura: int, altura: int, dados: Optional[bytes] = None,
        formato: Optional[str] = None, origem: str = "navegador", erro: Optional[str] = None,
    ) -> str:
        """Devolve 'nova', 'duplicada', 'erro' ou 'limite'."""
        with self._lock:
            existente = self._por_url.get(url)
            if existente is None and len(self._itens) >= self._max_itens:
                return "limite"

            assinatura = None
            if dados is not None:
                assinatura = hashlib.sha256(dados).hexdigest()
                igual = self._hashes.get(assinatura)
                if igual is not None and igual != existente and igual in self._itens:
                    return "duplicada"
                if self._memoria + len(dados) > self._limite_memoria:
                    dados, formato = None, None
                    erro = "Limite de memória da lista atingido: baixe as marcadas e use 'Limpar lista'."

            if existente is None:
                item = Candidata(id=self._proximo_id, url=url)
                self._proximo_id += 1
                self._itens[item.id] = item
                self._por_url[url] = item.id
            else:
                item = self._itens[existente]
                if item.dados is not None:
                    self._memoria -= len(item.dados)

            item.largura, item.altura = largura, altura
            item.dados, item.formato, item.origem = dados, formato, origem
            item.erro = None if dados is not None else (erro or "Não foi possível obter a imagem.")
            if dados is not None:
                self._memoria += len(dados)
                self._hashes[assinatura] = item.id  # type: ignore[index]
            self.versao += 1
            return "nova" if dados is not None else "erro"

    def limpar(self, reiniciar_numeracao: bool = False) -> None:
        with self._lock:
            self._itens.clear()
            self._por_url.clear()
            self._hashes.clear()
            self._memoria = 0
            if reiniciar_numeracao:
                self._contador_arquivos = 1
            self.versao += 1

    def para_tela(self) -> List[Dict[str, Any]]:
        with self._lock:
            principais: Dict[str, Candidata] = {}
            for i in self._itens.values():
                chave = _chave_de_variante(i.url) if i.dados is not None else None
                if chave is None:
                    continue
                atual = principais.get(chave)
                if atual is None or (i.largura * i.altura, len(i.dados or b"")) > (
                    atual.largura * atual.altura, len(atual.dados or b"")
                ):
                    principais[chave] = i
            resultado = []
            for i in self._itens.values():
                chave = _chave_de_variante(i.url) if i.dados is not None else None
                principal = principais.get(chave) if chave else None
                resultado.append({
                    "id": i.id, "url": _url_para_tela(i.url), "largura": i.largura, "altura": i.altura,
                    "bytes": len(i.dados) if i.dados is not None else 0, "formato": i.formato,
                    "origem": i.origem, "erro": i.erro, "salva": i.salva,
                    "variante_de": principal.id if principal is not None and principal.id != i.id else None,
                })
            return resultado

    def reordenar(self, urls_em_ordem: List[str]) -> None:
        """Põe as imagens que estão na página na ordem em que a página as mostra.

        As que não estão mais na página (outra tela, lista virtual) ficam onde estavam; as presentes
        se reorganizam só entre as posições que já ocupavam.
        """
        with self._lock:
            ids_atuais = list(self._itens)
            na_pagina: List[int] = []
            vistos = set()
            for url in urls_em_ordem:
                id_ = self._por_url.get(url)
                if id_ is not None and id_ in self._itens and id_ not in vistos:
                    vistos.add(id_)
                    na_pagina.append(id_)
            posicoes = [k for k, id_ in enumerate(ids_atuais) if id_ in vistos]
            nova = list(ids_atuais)
            for k, id_ in zip(posicoes, na_pagina):
                nova[k] = id_
            if nova != ids_atuais:
                itens = self._itens
                self._itens = {id_: itens[id_] for id_ in nova}
                self.versao += 1

    def dados_de(self, id_: int) -> Optional[Tuple[bytes, str]]:
        with self._lock:
            item = self._itens.get(id_)
            if item is None or item.dados is None or item.formato is None:
                return None
            return item.dados, item.formato

    def salvar(self, ids: List[int], pasta: Path) -> Tuple[List[str], List[Tuple[str, str]], int]:
        """Grava as marcadas. Devolve (nomes gravados, falhas (url, motivo), quantas já estavam salvas)."""
        salvos: List[str] = []
        falhas: List[Tuple[str, str]] = []
        ja_salvas = 0
        with self._lock:
            pedidas = set(ids)
            ordem = [id_ for id_ in self._itens if id_ in pedidas]
        for id_ in ordem:
            with self._lock:
                item = self._itens.get(id_)
                if item is None:
                    continue
                if item.salva:
                    ja_salvas += 1
                    continue
                if item.dados is None or item.formato is None:
                    falhas.append((_url_para_tela(item.url), item.erro or "Sem dados para gravar."))
                    continue
                numero = self._contador_arquivos
                self._contador_arquivos += 1
                nome = nome_arquivo(
                    item.url, numero, item.formato, "_captura" if item.origem == "print" else ""
                )
                dados = item.dados
            try:
                caminho = gravar_arquivo(pasta, nome, dados)
            except ErroBaixador as erro:
                falhas.append((_url_para_tela(item.url), str(erro)))
                continue
            with self._lock:
                item.salva = caminho.name
                self.versao += 1
            salvos.append(caminho.name)
        return salvos, falhas, ja_salvas


# --------------------------------------------------------------------------- rede do navegador

def buscar_pelo_contexto(contexto, url: str, limite: int, timeout_s: float, referer: str = "") -> bytes:
    """Baixa `url` com os cookies da sessão do navegador (necessário em sites com login).

    Os redirecionamentos são seguidos à mão para revalidar cada destino: as requisições da API
    do Playwright não passam pelo filtro de rede interna do navegador.
    """
    from playwright.sync_api import Error as ErroPlaywright

    atual = url
    for _ in range(6):
        seguranca.validar_url(atual)
        try:
            resposta = contexto.request.get(
                atual, max_redirects=0, timeout=timeout_s * 1000, fail_on_status_code=False,
                headers={"Referer": referer} if referer else None,
            )
        except ErroPlaywright as erro:
            raise ErroDeRede(f"Falha ao baixar: {_resumo(erro)}") from None
        if resposta.status in (301, 302, 303, 307, 308):
            destino = resposta.headers.get("location")
            if not destino:
                raise ErroDeRede("Redirecionamento sem destino.")
            atual = urljoin(atual, destino)
            continue
        if resposta.status >= 400:
            raise ErroHttp(resposta.status)
        declarado = resposta.headers.get("content-length", "")
        if declarado.isdigit() and int(declarado) > limite:
            raise ArquivoGrande(f"O arquivo ultrapassa o limite de {limite // 1024 // 1024} MB.")
        corpo = resposta.body()
        if len(corpo) > limite:
            raise ArquivoGrande(f"O arquivo ultrapassa o limite de {limite // 1024 // 1024} MB.")
        return corpo
    raise ErroDeRede("Redirecionamentos demais.")


# --------------------------------------------------------------------------- sessão

def dominio_base(host: str) -> str:
    """Domínio "registrável" aproximado (www.x.com e cdn.x.com → x.com; x.co.uk → x.co.uk)."""
    partes = [p for p in (host or "").lower().strip(".").split(".") if p]
    if len(partes) <= 2:
        return ".".join(partes)
    if len(partes[-1]) == 2 and partes[-2] in ("co", "com", "org", "net", "gov", "ac"):
        return ".".join(partes[-3:])
    return ".".join(partes[-2:])


def mesmo_site(url_a: str, url_b: str) -> bool:
    from urllib.parse import urlsplit

    try:
        return dominio_base(urlsplit(url_a).hostname or "") == dominio_base(urlsplit(url_b).hostname or "")
    except ValueError:
        return False


class SessaoManual:
    def __init__(self, fabrica: Callable[..., Capturador] = Capturador, timeout: float = 20.0):
        self._fabrica = fabrica
        self._timeout = timeout
        self._lock = threading.RLock()
        self._fila: "queue.Queue[Tuple[str, Dict[str, Any]]]" = queue.Queue()
        self._capas: Dict[str, bytes] = {}      # página da obra → bytes da capa achada (para gravar ao lado dos capítulos)
        self._capas_tentadas: Dict[str, Tuple[int, float]] = {}   # obra → (tentativas, quando pode tentar de novo)
        self._aba_propria = False                 # True enquanto o programa abre uma aba por conta própria
        self._abas_proprias: List[Any] = []
        self._capas_pedidas: set = set()
        self._capa_manual = threading.Lock()    # um "Baixar capa" por vez
        self._thread: Optional[threading.Thread] = None
        self._cancelar = threading.Event()
        self._fechar = threading.Event()
        self._varrer = False
        self.automatico_ativo = False
        self.pagina_info: Dict[str, str] = {"titulo": "", "url": ""}   # aba que o usuário está vendo
        self.url_pedida = ""
        self._info_em = 0.0
        self.continuar_ativo = False                      # avançar para os próximos capítulos (pode mudar com o automático rodando)
        self._organizar_auto = False
        self._ao_concluir: Optional[Callable[[List[Path]], None]] = None   # tradução automática ao fim de todos os downloads
        self.aviso = ""                                  # parada do automático em vários capítulos (mostrada ao usuário)
        self._resultado_proximo: Optional[Tuple[bool, str]] = None
        self._principal = None
        self._salvando = threading.Lock()
        self.colecao = Colecao()
        self.estado = "ocioso"   # ocioso | abrindo | aguardando | procurando | fechado | erro
        self.erro: Optional[str] = None
        self.log: List[str] = []
        self.execucao = 0
        self.pasta: Optional[Path] = None
        self.salvando = False

    # ------------------------------------------------------------ estado e log

    def _definir(self, estado: str, erro: Optional[str] = None) -> None:
        with self._lock:
            self.estado, self.erro = estado, erro
        if estado == "erro":
            print(f"[erro] {erro}", file=sys.stderr, flush=True)  # também no terminal, para facilitar achar o problema

    def _registrar(self, mensagem: str) -> None:
        with self._lock:
            if len(self.log) < MAX_LINHAS_LOG:
                self.log.append(mensagem)
            elif len(self.log) == MAX_LINHAS_LOG:
                self.log.append("(mensagens seguintes omitidas)")

    def instantaneo(self, execucao_cliente: int, desde_log: int, versao_cliente: int) -> Dict[str, Any]:
        with self._lock:
            reiniciar = execucao_cliente != self.execucao
            if reiniciar:
                desde_log = 0
            enviar_itens = reiniciar or versao_cliente != self.colecao.versao
            return {
                "estado": self.estado, "erro": self.erro, "execucao": self.execucao,
                "reiniciar": reiniciar, "salvando": self.salvando, "automatico": self.automatico_ativo,
                "pagina": dict(self.pagina_info), "aviso": self.aviso, "continuar": self.continuar_ativo,
                "log": self.log[desde_log:], "log_total": len(self.log),
                "versao": self.colecao.versao,
                "itens": self.colecao.para_tela() if enviar_itens else None,
            }

    # ------------------------------------------------------------ comandos (chamados pelo servidor)

    def abrir(
        self, url: str, navegador: str = "auto", caminho: Optional[str] = None, perfil: str = "proprio",
        bloquear_abas: bool = True,
    ) -> None:
        from baixador.navegador import navegadores

        if perfil not in ("proprio", "temporario"):
            raise ValueError("Perfil desconhecido.")
        url = seguranca.validar_url(url)
        navegadores.tentativas(navegador, caminho)  # valida a escolha antes de abrir qualquer coisa
        with self._lock:
            antiga = self._thread
            if antiga is not None and antiga.is_alive():
                if self.estado in ESTADOS_ATIVOS:
                    raise RuntimeError("Já existe um navegador aberto. Feche-o antes de abrir outro site.")
        if antiga is not None and antiga.is_alive():
            self._fechar.set()
            antiga.join(12)
            if antiga.is_alive():
                with self._lock:
                    encerrada = self.estado not in ESTADOS_ATIVOS
                if not encerrada:
                    raise RuntimeError("O navegador anterior ainda está encerrando; tente de novo em instantes.")
                # a sessão já terminou (fechada/erro) e só a limpeza do navegador morto ficou pendente: segue sem esperar
        with self._lock:
            self.execucao += 1
            self.log = []
            self.aviso = ""
            self.colecao.limpar(reiniciar_numeracao=True)
            self.pasta = None                    # novo site: o capítulo anterior não conta como "em andamento"
            self.pagina_info = {"titulo": "", "url": ""}   # nada da aba/endereço anterior
            self.url_pedida = url                # endereço informado agora: único ponto de partida do capítulo
            self._cancelar.clear()
            self._fechar.clear()
            self._fila = queue.Queue()
            self._definir("abrindo")
            self._thread = threading.Thread(
                target=self._trabalhar, args=(url, navegador, caminho, perfil == "proprio", bool(bloquear_abas)), daemon=True
            )
            self._thread.start()

    def procurar(self, ignorar_comentarios: bool = True, espera: int = 30, modo: str = "rapido") -> None:
        """Enfileira uma busca. `espera` = segundos máximos esperando as imagens carregarem.

        modo: 'rapido' (C: desce rápido e se adapta; freia e espera quando a página está carregando) ou
        'carregamento' (B: desce devagar esperando sinais de carregamento). Os dois conferem a sequência no fim.
        """
        if modo not in MODOS_BUSCA:
            raise ValueError("Modo de busca desconhecido.")
        with self._lock:
            if self.estado == "procurando":
                raise RuntimeError("Já existe uma busca em andamento.")
            if self.estado != "aguardando":
                raise RuntimeError("Abra o site no navegador primeiro.")
            self._cancelar.clear()
            self._definir("procurando")
        self._fila.put((
            "procurar",
            {"ignorar": bool(ignorar_comentarios), "espera": max(5, min(int(espera), 300)), "modo": modo},
        ))

    def baixar_capa(self, pasta_obra: Path, url_obra: str, substituir: bool = False, espera_s: float = 75.0) -> Tuple[bool, str]:
        """"Baixar capa" manual: pega a capa na página da obra usando o navegador já aberto (com a sessão/verificação dele).

        Roda na thread do navegador (o Playwright só pode ser usado lá). Nunca levanta erro e nunca mexe nos capítulos:
        devolve (ok, mensagem). Sem `substituir`, uma capa existente não é trocada.
        """
        with self._lock:
            ativo = self._thread is not None and self._thread.is_alive()
            estado = self.estado
        if not ativo or estado not in ("aguardando", "procurando"):
            return False, "Abra o site da obra no navegador (aba Baixar) para eu poder baixar a capa com a sua sessão."
        if estado == "procurando":
            return False, "O navegador está procurando imagens. Espere terminar e tente de novo."
        if not self._capa_manual.acquire(blocking=False):
            return False, "Já estou baixando uma capa. Espere um instante."
        try:
            pedido: Dict[str, Any] = {
                "pasta": Path(pasta_obra), "url": url_obra, "substituir": bool(substituir),
                "fim": threading.Event(), "resultado": None,
            }
            self._fila.put(("capa", pedido))
            if not pedido["fim"].wait(espera_s):
                pedido["abandonado"] = True
                return False, "A página da obra demorou demais para responder. Tente de novo."
            return pedido["resultado"] or (False, "Não consegui baixar a capa.")
        finally:
            self._capa_manual.release()

    def _candidatas_pela_aba(self, contexto, url_obra: str) -> List[str]:
        """Abre a página da obra numa aba do próprio navegador (com login, cookies e verificações do site), espera a capa
        aparecer e lê no DOM a `<img>` de `.poster` (ou de `/covers/`). Devolve os endereços, da maior resolução para a menor."""
        from baixador.biblioteca import capa
        from playwright.sync_api import Error as ErroPlaywright

        seguranca.validar_url(url_obra)
        pagina = next((p for p in contexto.pages if not p.is_closed() and p.url.split('#')[0].split('?')[0].rstrip('/') == url_obra.rstrip('/')), None)
        criada = pagina is None
        if criada:
            self._aba_propria = True
            try:
                pagina = contexto.new_page()
                self._abas_proprias.append(pagina)
            finally:
                self._aba_propria = False
        try:
            if criada:
                pagina.goto(url_obra, wait_until="domcontentloaded", timeout=self._timeout * 1500)
            try:
                pagina.wait_for_selector(SELETOR_CAPA, timeout=15000, state="attached")
            except ErroPlaywright:
                pass                                           # sem a imagem: o og:image/HTML bruto ainda podem servir
            info = pagina.evaluate(JS_CAPA)
        finally:
            if criada:
                try:
                    pagina.close()
                except Exception:
                    pass
                if pagina in self._abas_proprias:
                    self._abas_proprias.remove(pagina)
        return capa.candidatas_do_dom(info, url_obra) if isinstance(info, dict) else []

    def navegador_pronto(self) -> bool:
        """True se há um navegador aberto e livre (pode receber o comando de baixar capa)."""
        with self._lock:
            return self._thread is not None and self._thread.is_alive() and self.estado in ("aguardando", "procurando")

    def _capa(self, contexto, pedido: Dict[str, Any]) -> None:
        from baixador.biblioteca import capa

        try:
            if pedido.get("abandonado"):
                return
            url = pedido["url"]
            buscar = lambda u, limite: buscar_pelo_contexto(contexto, u, limite, self._timeout, referer=url)  # noqa: E731
            dados, motivo = None, ""
            try:
                candidatas = self._candidatas_pela_aba(contexto, url)
            except Exception as erro:
                candidatas = []
                motivo = f"Não consegui abrir a página da obra no navegador ({str(erro)[:100]})."
            if candidatas:
                dados, motivo = capa.baixar_primeira(candidatas, buscar)
            elif not motivo:
                motivo = "A página da obra abriu, mas não achei a imagem da capa nela (`.poster img`)."
            if not dados:                                      # plano B: o HTML bruto da página, com os cookies do navegador
                dados2, motivo2 = capa.procurar(url, buscar)
                dados, motivo = dados2, ("" if dados2 else (motivo or motivo2))
            if not dados:
                pedido["resultado"] = (False, motivo or "Não consegui baixar a capa.")
            elif capa.gravar(pedido["pasta"], dados, pedido["substituir"]) is None:
                pedido["resultado"] = (False, "Já existe uma capa; ela não foi trocada." if capa.achar(pedido["pasta"]) and not pedido["substituir"]
                                       else "Baixei a imagem, mas não consegui salvá-la na pasta da obra.")
            else:
                pedido["resultado"] = (True, "Capa baixada e salva na pasta da obra.")
            self._registrar(pedido["resultado"][1])
        except Exception as erro:
            pedido["resultado"] = (False, f"Erro ao baixar a capa ({erro.__class__.__name__}).")
        finally:
            pedido["fim"].set()

    def automatico(
        self, url: str, pasta: str, navegador: str = "auto", caminho: Optional[str] = None, perfil: str = "proprio",
        bloquear_abas: bool = True, espera: int = 30, ignorar_comentarios: bool = True,
        organizar: Optional[Dict[str, Any]] = None, continuar: bool = False, modo_busca: str = "rapido",
        ao_concluir: Optional[Callable[[List[Path]], None]] = None, pular_primeiro: bool = False,
    ) -> None:
        """Faz sozinho o que o modo manual faz com "Automático B": abre, procura, baixa tudo e fecha.

        `pular_primeiro` ("Atualizar"): o capítulo aberto é o último já salvo; não é baixado, o programa só aperta em "próximo".

        `organizar` ({obra, numero, titulo}): `pasta` é a base e o capítulo é guardado em Obra/Cap NNN - Nome;
        o que o usuário deixar em branco é identificado pelo título da aba (ou, se faltar, pelo endereço).
        """
        if not pasta or len(pasta) > 400:
            raise ValueError("Informe a pasta de destino.")
        self.abrir(url, navegador, caminho, perfil, bloquear_abas)
        with self._lock:
            self.automatico_ativo = True
            self._organizar_auto = organizar is not None
            self.continuar_ativo = bool(continuar) and organizar is not None
            # só existe tradução automática junto com a continuação automática
            self._ao_concluir = ao_concluir if self.continuar_ativo else None
        threading.Thread(
            target=self._coordenar_automatico, args=(pasta, int(espera), bool(ignorar_comentarios), organizar, modo_busca if modo_busca in MODOS_BUSCA else "rapido", bool(pular_primeiro) and organizar is not None), daemon=True
        ).start()

    def _esperar_estado(self, saem: tuple, limite_s: float) -> str:
        """Espera o estado sair do conjunto `saem` (ou o navegador ser fechado); devolve o estado final."""
        fim = time.monotonic() + limite_s
        while time.monotonic() < fim and not self._fechar.is_set():
            with self._lock:
                estado = self.estado
            if estado not in saem:
                return estado
            time.sleep(0.2)
        with self._lock:
            return self.estado

    def _identificar_auto(self, base: str, organizar: Dict[str, Any]) -> Tuple[str, Optional[str], str, Dict[str, Any], Optional[str]]:
        """Obra, número, nome e endereço do capítulo aberto; a obra é trocada pela já existente na biblioteca quando é a mesma
        (nome do site errado) e uma única serve. Devolve também o caminho do capítulo, se ele já estiver salvo."""
        from baixador.biblioteca import acervo, organizacao as org

        self._atualizar_info_por_comando()
        with self._lock:
            info = dict(self.pagina_info)
        achado = org.extrair_capitulo(info.get("titulo", ""), info.get("url", ""))
        obra = org.limpar_nome(organizar.get("obra") or "", 80) or achado["obra"] or ""
        numero = org.normalizar_numero(organizar.get("numero")) or achado["numero"]
        titulo = org.limpar_nome(organizar.get("titulo") or "", 80) or achado["titulo"] or ""
        try:
            r = acervo.resolver_obra(Path(base).expanduser(), obra, info.get("url", ""))
            if r["existente"] and r["obra"] != obra:
                self._registrar(f"Obra “{obra}” reconhecida como a que você já tem: “{r['obra']}”.")
                obra = r["obra"]
            existente = acervo.capitulo_existente(Path(base).expanduser(), obra, numero, titulo, info.get("url", ""))
        except Exception:
            existente = None                                   # a checagem é uma proteção extra: nunca derruba o download
        info_cap = {"obra": obra, "numero": numero, "titulo": titulo, "url": info.get("url", "") or self.url_pedida}
        return obra, numero, titulo, info_cap, existente

    def _baixar_capitulo_auto(
        self, base: str, espera: int, ignorar: bool, organizar: Optional[Dict[str, Any]], modo: str = "rapido", pular: bool = False,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Procura (Automático B ou C) e baixa o capítulo aberto. Devolve (deu certo, motivo se não, dados do capítulo)."""
        info_cap: Dict[str, Any] = {}
        if organizar is not None:                              # capítulo que já está na biblioteca não é baixado de novo
            from baixador.biblioteca import organizacao as org

            obra, numero, titulo, info_cap, existente = self._identificar_auto(base, organizar)
            if pular:                                          # Atualizar: este é o último capítulo salvo; só avançar
                self._registrar("Atualizar: abri o último capítulo salvo" + (f" ({org.rotulo_capitulo(numero, titulo)} de “{obra}”)" if numero is not None else "") + ". Não vou baixá-lo; apertando em “próximo”…")
                info_cap["ja_existia"] = True
                return True, "", info_cap
            if existente:
                self._registrar(f"{org.rotulo_capitulo(numero, titulo)} de “{obra}” já existe na biblioteca ({existente}); não baixei de novo.")
                info_cap["ja_existia"] = True
                return True, "", info_cap
        self.procurar(ignorar, espera, modo)
        estado = self._esperar_estado(("procurando",), 3600)
        if estado != "aguardando" or self._fechar.is_set():
            return False, "a busca de imagens foi interrompida; nada foi baixado.", info_cap
        ids = [
            i["id"] for i in self.colecao.para_tela()
            if not i.get("erro") and i.get("bytes", 0) > 0 and not i.get("salva")
        ]
        if not ids:
            return False, "nenhuma imagem encontrada para baixar neste capítulo.", info_cap
        pasta, meta = base, None
        if organizar is not None:
            from baixador.biblioteca import organizacao as org
            from baixador.nucleo.imagens import pasta_do_conjunto

            obra, numero, titulo, info_cap, _ = self._identificar_auto(base, organizar)
            if self.continuar_ativo and (not obra or numero is None):
                return False, (
                    "não consegui identificar a obra e o número deste capítulo pela aba/link; "
                    "para não misturar capítulos, parei antes de baixar."
                ), info_cap
            rel = org.caminho_relativo(obra, numero, titulo)
            pasta = pasta_do_conjunto(base, rel)
            meta = {"obra": obra, "numero": numero, "titulo": titulo, "url": info_cap.get("url", "")}
            self._registrar(
                f"Capítulo identificado: {org.rotulo_capitulo(numero, titulo or '')} — obra “{obra or 'sem obra'}” ({rel or 'pasta base'})."
            )
        r = self.baixar(ids, pasta, meta)
        self._registrar(
            f"Capítulo baixado: {len(r['salvos'])} imagem(ns) salva(s)"
            + (f", {len(r['falhas'])} falha(s)" if r["falhas"] else "") + "."
        )
        if not r["salvos"]:
            return False, "nenhuma imagem deste capítulo pôde ser salva.", info_cap
        info_cap["salvos"] = len(r["salvos"])
        info_cap["pasta"] = str(pasta)
        return True, "", info_cap

    def definir_continuar(self, ativo: bool) -> None:
        """Liga/desliga, mesmo com o automático rodando, o avanço para os próximos capítulos.

        Desligar não interrompe o capítulo em andamento: ele termina de baixar e o processo para ali (sem avançar).
        """
        with self._lock:
            self.continuar_ativo = bool(ativo) and self._organizar_auto
            if self.automatico_ativo:
                self._registrar(
                    "Continuar nos próximos capítulos: LIGADO." if self.continuar_ativo else
                    "Continuar nos próximos capítulos: DESLIGADO. Termino o capítulo atual e paro, sem avançar."
                )

    def _coordenar_automatico(
        self, pasta: str, espera: int, ignorar: bool, organizar: Optional[Dict[str, Any]] = None,
        modo: str = "rapido", pular_primeiro: bool = False,
    ) -> None:
        manter_aberto = False
        try:
            estado = self._esperar_estado(("abrindo",), 180)
            if estado != "aguardando" or self._fechar.is_set():
                return
            self._registrar(
                "Modo automático (opção C, teste): descer rápido e frear quando a página estiver carregando…"
                if modo == "rapido" else
                "Modo automático: procurando com o Automático B (descer devagar e esperar carregar)…"
            )
            from baixador.biblioteca import organizacao as org

            organizar = dict(organizar) if organizar is not None else None
            visitados: set = set()
            feitos: List[str] = []
            pastas_feitas: List[Path] = []
            ultimo = ""
            while len(feitos) < LIMITE_CAPITULOS_AUTO:
                with self._lock:
                    url_atual = self.pagina_info.get("url", "")
                if self.continuar_ativo and feitos and url_atual in visitados:
                    manter_aberto = True
                    return self._parar_aviso(
                        f"voltei a uma página já baixada ({url_atual[:100]}); parei para não repetir. Confira o site.", feitos
                    )
                visitados.add(url_atual)
                if feitos and organizar is not None:
                    organizar["numero"], organizar["titulo"] = "", ""           # só o 1º capítulo usa o que o usuário digitou
                ok, motivo, cap = self._baixar_capitulo_auto(pasta, espera, ignorar, organizar, modo, pular=pular_primeiro and not feitos)
                if not ok:
                    if self.continuar_ativo or feitos:
                        manter_aberto = not self._fechar.is_set()
                        return self._parar_aviso(motivo, feitos, parou_em=ultimo)
                    self._registrar(f"Modo automático: {motivo}")
                    return
                if organizar is not None:
                    organizar["obra"] = cap.get("obra") or organizar.get("obra", "")
                ultimo = org.rotulo_capitulo(cap.get("numero"), cap.get("titulo") or "") if organizar is not None else "capítulo"
                feitos.append(ultimo)
                if cap.get("pasta"):
                    pastas_feitas.append(Path(cap["pasta"]))
                if self._fechar.is_set():
                    return
                if not self.continuar_ativo:                                 # desligado (ou nunca ligado): termina aqui
                    self._registrar(
                        "Modo automático concluído." if len(feitos) == 1 else
                        f"Continuação desligada: parei depois de {ultimo}. {len(feitos)} capítulo(s) baixado(s)."
                    )
                    return
                self._registrar(f"Tentando avançar para o próximo capítulo (depois de {ultimo})…")
                self._resultado_proximo = None
                try:
                    self.proximo_capitulo()
                except RuntimeError as erro:
                    manter_aberto = True
                    return self._parar_aviso(f"não consegui pedir o próximo capítulo ({erro}).", feitos, parou_em=ultimo)
                estado = self._esperar_estado(("procurando",), 60)
                if self._fechar.is_set():
                    return
                resultado = self._resultado_proximo
                if estado != "aguardando" or not resultado or not resultado[0]:
                    manter_aberto = True
                    detalhe = resultado[1] if resultado else "o navegador não respondeu."
                    self._parar_aviso(
                        f"não consegui avançar para o próximo capítulo depois de {ultimo}: {detalhe} "
                        "Isso pode ser o último capítulo OU um erro; confira no navegador.", feitos, parou_em=ultimo,
                    )
                    # fim da sequência: nada mais está sendo baixado, então a tradução pode começar
                    return self._traduzir_ao_final(pastas_feitas)
                time.sleep(1.0)                                                # deixa o título da aba atualizar
            manter_aberto = True
            self._parar_aviso(f"atingi o limite de {LIMITE_CAPITULOS_AUTO} capítulos numa execução.", feitos, parou_em=ultimo)
        except Exception as erro:
            manter_aberto = self.continuar_ativo and not self._fechar.is_set()
            self._registrar(f"Modo automático parou: {erro}")
            if self.continuar_ativo:
                self._definir_aviso(f"O modo automático parou por um erro ({erro.__class__.__name__}). Veja o andamento.")
        finally:
            with self._lock:
                self.automatico_ativo = False
                self.continuar_ativo = False
            if not manter_aberto:
                self.fechar_navegador()

    def _traduzir_ao_final(self, pastas: List[Path]) -> None:
        """Chama a tradução automática, só se a continuação continua ligada e o navegador não foi fechado/cancelado."""
        with self._lock:
            chamar, ligado = self._ao_concluir, self.continuar_ativo
        if chamar is None or not ligado or self._fechar.is_set() or not pastas:
            return
        try:
            chamar(list(pastas))
            self._registrar(f"Downloads concluídos: tradução automática iniciada ({len(pastas)} capítulo(s)).")
        except Exception as erro:
            self._registrar(f"Downloads concluídos, mas a tradução automática não iniciou: {erro}")

    def _definir_aviso(self, texto: str) -> None:
        with self._lock:
            self.aviso = texto

    def _parar_aviso(self, motivo: str, feitos: List[str], parou_em: str = "") -> None:
        """Interrompe o automático multi-capítulo SEM dizer que a obra acabou: só relata onde parou e por quê."""
        feito = f"{len(feitos)} capítulo(s) baixado(s)" + (f" (último: {parou_em})" if parou_em else "")
        texto = f"Parei: {motivo} {feito}. O navegador continua aberto onde parou."
        self._registrar(texto)
        self._definir_aviso(texto)

    def proximo_capitulo(self) -> None:
        """Enfileira a tentativa de passar para o próximo capítulo (o navegador precisa estar aguardando)."""
        with self._lock:
            if self.estado == "procurando":
                raise RuntimeError("Espere a busca terminar (ou cancele) antes de passar o capítulo.")
            if self.estado != "aguardando":
                raise RuntimeError("Abra o site no navegador primeiro.")
            self._cancelar.clear()
            self._resultado_proximo = None
            self._definir("procurando")
        self._fila.put(("proximo", {}))

    def cancelar_busca(self) -> None:
        self._cancelar.set()

    def fechar_navegador(self) -> None:
        self._fechar.set()
        self._cancelar.set()

    def encerrar(self, espera: float = 15.0) -> None:
        self.fechar_navegador()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(espera)

    def limpar_lista(self) -> None:
        self.colecao.limpar()
        self.pasta = None

    def limpar_tudo(self) -> None:
        """Zera os dados temporários da operação (lista de imagens, andamento, última pasta, capa em memória, aba lembrada).

        Não apaga nada da biblioteca/disco. Recusa se o navegador está aberto, se há salvamento ou se o automático roda:
        assim um endereço novo nunca se mistura com a operação anterior.
        """
        with self._lock:
            if self.salvando or self.automatico_ativo or self.estado in ESTADOS_ATIVOS:
                raise RuntimeError("Feche o navegador (e espere qualquer download terminar) antes de limpar tudo.")
            self.execucao += 1                      # o app reinicia a tela dele (galeria e andamento)
            self.log, self.aviso, self.pasta = [], "", None
            self.pagina_info = {"titulo": "", "url": ""}
            self._resultado_proximo = None
            self._capas.clear()
            self._capas_pedidas.clear()
            self._capas_tentadas.clear()
            self.colecao.limpar(reiniciar_numeracao=True)
            self.estado, self.erro = "ocioso", None

    def baixar(self, ids: List[int], pasta: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self._salvando.acquire(blocking=False):
            raise RuntimeError("Já existe um salvamento em andamento.")
        try:
            with self._lock:
                self.salvando = True
            destino = preparar_pasta(pasta)
            with self._lock:
                self.pasta = destino
            destino_img = destino
            if meta and meta.get("obra"):                                  # capítulo da biblioteca: imagens em Capítulo/img, .json na raiz do capítulo
                destino_img = preparar_pasta(str(destino / "img"))
            salvos, falhas, ja = self.colecao.salvar(ids, destino_img)
            if salvos:
                try:
                    from baixador.biblioteca import organizacao

                    if meta and meta.get("obra"):
                        organizacao.gravar_meta(
                            destino, str(meta.get("obra", "")), meta.get("numero"), str(meta.get("titulo", "")),
                            str(meta.get("url", "")),
                        )
                        pasta_obra = organizacao.caminho_relativo(str(meta.get("obra", "")), meta.get("numero"), str(meta.get("titulo", ""))).split("/")[0]
                        if destino.parent.name == pasta_obra:           # só no layout Obra/Capítulo; nunca numa pasta qualquer
                            from baixador.biblioteca import obra as dados_obra

                            dados_obra.gravar(destino.parent, str(meta.get("obra", "")), str(meta.get("url", "")))
                            self._gravar_capa(destino.parent, str(meta.get("url", "")))
                except Exception:
                    pass  # gravar os dados do capítulo é um extra: não pode atrapalhar o salvamento
            for nome in salvos:
                self._registrar(f"Salva: {nome}")
            for url, motivo in falhas:
                self._registrar(f"Não salva: {url} — {motivo}")
            if ja:
                self._registrar(f"{ja} imagem(ns) marcada(s) já tinha(m) sido salva(s) e foi(ram) ignorada(s).")
            return {
                "salvos": salvos, "ja_salvas": ja,
                "falhas": [{"url": u, "motivo": m} for u, m in falhas],
            }
        finally:
            with self._lock:
                self.salvando = False
            self._salvando.release()

    def salvando_neste_destino(self, destino: Path) -> bool:
        """True se este capítulo já está sendo salvo em partes nesta lista (vários "Baixar marcadas" no mesmo capítulo é normal)."""
        with self._lock:
            atual = self.pasta
        try:
            return atual is not None and Path(atual).resolve() == Path(destino).expanduser().resolve()
        except OSError:
            return False

    def pasta_destino(self) -> Optional[Path]:
        with self._lock:
            return self.pasta

    # ------------------------------------------------------------ thread do navegador

    def _trabalhar(
        self, url: str, navegador: str, caminho: Optional[str], perfil_proprio: bool, bloquear_abas: bool = True
    ) -> None:
        capturador = None
        try:
            capturador = self._fabrica(
                self._timeout, mostrar=True, parar=self._cancelar,
                navegador=navegador, caminho_navegador=caminho, perfil_persistente=perfil_proprio,
            )
            self._registrar("Abrindo o navegador…")
            contexto, pagina = capturador.nova_pagina(javascript=True, janela_real=True)
            from playwright.sync_api import Error as ErroPlaywright

            respostas: Dict[str, Any] = {}

            def ao_responder(resposta) -> None:
                try:
                    tipo = (resposta.headers.get("content-type") or "").lower()
                    if (
                        resposta.status == 200 and tipo.startswith("image/")
                        and len(respostas) < MAX_RESPOSTAS_GUARDADAS
                    ):
                        respostas[resposta.url] = resposta
                except Exception:
                    pass

            contexto.on("response", ao_responder)

            rede: Dict[str, Any] = {"em_voo": set()}   # requisições de imagem em andamento

            def ao_pedir(requisicao) -> None:
                try:
                    if requisicao.resource_type == "image":
                        rede["em_voo"].add(requisicao)
                except Exception:
                    pass

            def ao_terminar(requisicao) -> None:
                rede["em_voo"].discard(requisicao)

            def ao_abrir_aba(nova) -> None:
                """Anúncios que abrem outra aba: fecha a aba nova e devolve o foco ao site."""
                if not bloquear_abas or nova is pagina or pagina.is_closed() or self._aba_propria or nova in self._abas_proprias:
                    return                                     # a aba aberta pelo próprio programa (ex.: página da obra) não é anúncio
                try:
                    endereco = nova.url or "(carregando)"
                    nova.close()
                    self._registrar(f"Aba nova bloqueada (provável anúncio): {endereco[:120]}")
                    pagina.bring_to_front()
                except Exception:
                    pass

            contexto.on("page", ao_abrir_aba)
            self._varrer, self._principal = bloquear_abas, pagina
            if bloquear_abas:
                # abas restauradas do perfil, páginas de boas-vindas de extensões etc.
                for outra in list(contexto.pages):
                    if outra is not pagina:
                        try:
                            outra.close()
                        except Exception:
                            pass

                def guarda(rota) -> None:
                    """Navegação do documento principal para OUTRO site (anúncio redirecionando a aba): aborta."""
                    try:
                        req = rota.request
                        if (
                            req.is_navigation_request() and req.frame.parent_frame is None
                            and req.frame.page is pagina and not mesmo_site(req.url, url)
                            and req.url.startswith(("http://", "https://"))
                        ):
                            self._registrar(f"Redirecionamento para outro site bloqueado: {req.url[:120]}")
                            rota.abort()
                            return
                    except Exception:
                        pass
                    rota.fallback()

                contexto.route("**/*", guarda)
            contexto.on("request", ao_pedir)
            contexto.on("requestfinished", ao_terminar)
            contexto.on("requestfailed", ao_terminar)
            try:
                pagina.goto(url, wait_until="commit", timeout=TEMPO_ABERTURA_MS)
            except ErroPlaywright as erro:
                self._registrar(f"Aviso: a página demorou a responder ({_resumo(erro)}). Continue pelo navegador.")
            self._definir("aguardando")
            self._registrar(
                "Navegador aberto. Faça o que for preciso nele (entrar na conta, clicar, esperar o conteúdo "
                "carregar). Quando estiver pronto, clique em “Procurar imagens na página”."
            )
            self._laco(capturador, contexto, respostas, rede)
            self._registrar("Navegador fechado.")
            self._definir("fechado")
        except ErroBaixador as erro:
            self._registrar(str(erro))
            self._definir("erro", str(erro))
        except Exception as erro:  # defesa final: a interface não pode ficar presa
            fechado_pelo_usuario = self._fechar.is_set() or (capturador is not None and not capturador.conectado())
            if fechado_pelo_usuario:                     # navegador fechado na janela: não é erro do programa
                self._registrar("Navegador fechado.")
                self._definir("fechado")
            else:
                mensagem = f"Erro inesperado ({erro.__class__.__name__})."
                self._registrar(mensagem)
                self._definir("erro", mensagem)
        finally:
            with self._lock:
                self.pagina_info = {"titulo": "", "url": ""}   # sem navegador não há aba: nada de dados da sessão anterior
                self._abas_proprias.clear()
            if capturador is not None:                   # fechar um navegador já morto pode travar: com tempo limite, em outra thread
                fechador = threading.Thread(target=capturador.fechar, daemon=True)
                fechador.start()
                fechador.join(8)

    def _laco(self, capturador: Capturador, contexto, respostas: Dict[str, Any], rede: Dict[str, Any]) -> None:
        from playwright.sync_api import Error as ErroPlaywright

        while not self._fechar.is_set():
            if not capturador.conectado():
                return
            paginas = [p for p in contexto.pages if not p.is_closed()]
            if not paginas:
                return
            if self._varrer and len(paginas) > 1:
                principal = paginas[0] if self._principal is None or self._principal.is_closed() else self._principal
                for extra in paginas:
                    if extra is not principal:
                        try:
                            extra.close()
                            self._registrar("Aba extra fechada (só o site escolhido fica aberto).")
                        except Exception:
                            pass
                continue
            try:
                comando, args = self._fila.get_nowait()
            except queue.Empty:
                try:  # deixa o Playwright processar eventos (respostas de rede, fechamento de abas)
                    paginas[0].wait_for_timeout(120)
                except ErroPlaywright:
                    pass
                self._atualizar_info(contexto)
                continue
            if comando == "capa":
                self._capa(contexto, args)
            elif comando == "proximo":
                self._proximo(contexto)
            elif comando == "procurar":
                self._procurar(
                    capturador, contexto, respostas, rede, args["ignorar"], args["espera"], args.get("modo", "rapido"),
                )

    def _proximo(self, contexto) -> None:
        """Acha e aciona o controle de "próximo capítulo". Se a página mudar, a lista de imagens é zerada."""
        from playwright.sync_api import Error as ErroPlaywright

        try:
            pagina = self._pagina_ativa(contexto)
            antes = pagina.url
            achado = pagina.evaluate(JS_PROXIMO)
            if not achado:
                return self._resultado(False, "Não encontrei o botão de próximo capítulo nesta página. Passe pelo navegador mesmo.")
            href = achado.get("href") or ""
            self._registrar(f"Controle encontrado: “{achado.get('texto') or href[:80]}”. Passando de capítulo…")
            if href and not href.startswith(("http://", "https://")):
                href = ""
            if href and not mesmo_site(href, antes):
                return self._resultado(False, "O botão leva para outro site; não segui (proteção contra anúncios).")
            if achado.get("marcado"):
                try:
                    pagina.locator("[data-baixador-prox]").first.click(timeout=4000)
                except ErroPlaywright:
                    if href:                                   # clique barrado (sobreposição): vai direto ao endereço
                        pagina.goto(href, wait_until="commit", timeout=TEMPO_ABERTURA_MS)
            elif href:
                pagina.goto(href, wait_until="commit", timeout=TEMPO_ABERTURA_MS)
            fim = time.monotonic() + 10
            while time.monotonic() < fim and pagina.url == antes and not self._fechar.is_set():
                pagina.wait_for_timeout(200)
            if pagina.url == antes:
                return self._resultado(False, "Cliquei, mas a página não mudou. Pode ser o último capítulo ou o site pede outra ação.")
            try:
                pagina.wait_for_load_state("domcontentloaded", timeout=8000)
            except ErroPlaywright:
                pass
            self.colecao.limpar(reiniciar_numeracao=True)
            self.pasta = None
            self._resultado(True, f"Novo capítulo aberto: {pagina.url[:120]}. Lista de imagens zerada; clique em Procurar.")
        except ErroPlaywright as erro:
            self._resultado(False, f"Não consegui passar o capítulo ({_resumo(erro)}).")
        except Exception as erro:
            self._resultado(False, f"Erro ao passar o capítulo ({erro.__class__.__name__}).")
        finally:
            with self._lock:
                if self.estado == "procurando":
                    self._definir("aguardando")

    def _resultado(self, ok: bool, mensagem: str) -> None:
        """Registra no andamento e guarda o resultado de "passar o capítulo" (o automático consulta isto)."""
        self._registrar(mensagem)
        self._resultado_proximo = (ok, mensagem)

    def _atualizar_info_por_comando(self, espera_s: float = 2.5) -> None:
        """Espera o laço do navegador renovar o título da aba (a leitura só pode ser feita naquela thread)."""
        fim = time.monotonic() + espera_s
        antes = self._info_em
        while time.monotonic() < fim and self._info_em == antes and not self._fechar.is_set():
            time.sleep(0.1)

    def _atualizar_info(self, contexto, forcar: bool = False) -> None:
        """Guarda o título e o endereço da aba visível (no máximo 1x por segundo) para identificar obra e capítulo."""
        agora = time.monotonic()
        if not forcar and agora - self._info_em < 1.0:
            return
        self._info_em = agora
        try:
            pagina = self._pagina_ativa(contexto)
            info = {"titulo": (pagina.title() or "")[:300], "url": pagina.url[:2048]}
        except Exception:
            return
        with self._lock:
            if info != self.pagina_info:
                self.pagina_info = info
        self._buscar_capa(contexto, info["url"])

    def _buscar_capa(self, contexto, url: str) -> None:
        """Na página da obra (endereço do capítulo cortado até o nome da obra), pega a capa — até 3 tentativas por obra, espaçadas."""
        from baixador.biblioteca import capa

        obra = capa.url_da_obra(url)
        if not obra or obra in self._capas or len(self._capas_tentadas) >= 20:
            return
        tentativas, quando = self._capas_tentadas.get(obra, (0, 0.0))
        if tentativas >= 3 or time.monotonic() < quando:
            return
        self._capas_tentadas[obra] = (tentativas + 1, time.monotonic() + 30.0)
        dados, motivo = capa.procurar(obra, lambda u, limite: buscar_pelo_contexto(contexto, u, limite, self._timeout, referer=obra))
        if dados:
            self._capas[obra] = dados
            self._registrar("Capa da obra encontrada na página dela.")
        elif tentativas == 2:
            self._registrar(f"Capa não encontrada automaticamente: {motivo} Use “Baixar capa” na biblioteca.")

    def _gravar_capa(self, pasta_obra: Path, url_capitulo: str) -> None:
        """Depois de salvar um capítulo: grava a capa já achada; se ainda não há capa, pede a busca pela aba do navegador."""
        from baixador.biblioteca import capa

        obra = capa.url_da_obra(url_capitulo)
        dados = self._capas.get(obra) if obra else None
        if dados and capa.gravar(pasta_obra, dados):
            self._registrar("Capa da obra salva.")
        elif obra and capa.achar(pasta_obra) is None and obra not in self._capas_pedidas and self.estado in ESTADOS_ATIVOS:
            self._capas_pedidas.add(obra)                      # uma vez por obra
            if self.automatico_ativo:                          # no automático o navegador fecha logo depois: espera a capa aqui
                ok, mensagem = self.baixar_capa(Path(pasta_obra), obra, False, espera_s=60.0)
                if not ok:
                    self._registrar(f"Capa não baixada: {mensagem} Use “Baixar capa” na biblioteca.")
            else:                                              # manual: não prende o “Baixar marcadas”; o resultado vai para o andamento
                threading.Thread(target=self.baixar_capa, args=(Path(pasta_obra), obra, False, 60.0), daemon=True).start()

    def _pagina_ativa(self, contexto):
        from playwright.sync_api import Error as ErroPlaywright

        paginas = [p for p in contexto.pages if not p.is_closed()]
        for pagina in reversed(paginas):  # abas novas primeiro
            try:
                if pagina.evaluate("document.visibilityState") == "visible":
                    return pagina
            except ErroPlaywright:
                continue
        return paginas[-1]

    def _imagens_em_voo(self, rede: Dict[str, Any], pagina) -> int:
        """Requisições de imagem ainda em andamento nesta aba."""
        n = 0
        for requisicao in list(rede["em_voo"]):
            try:
                if requisicao.frame.page is pagina:
                    n += 1
            except Exception:
                pass
        return n

    def _esperar_pagina(
        self, capturador, pagina, rede: Dict[str, Any], parado_s: float, c: Dict[str, Any],
        indicadores: bool = True, teto_s: float = 300.0, rapido: bool = False,
    ) -> bool:
        """Espera as imagens perto da tela (e os sinais de 'carregando') terminarem.

        Não desiste por tempo total, e sim por falta de progresso: enquanto algo continuar carregando
        (imagens concluindo, requisições em andamento), segue esperando. Só para se nada mudar por
        `parado_s` segundos (ou ao passar do teto de segurança). Devolve False se desistiu.
        """
        from playwright.sync_api import Error as ErroPlaywright

        inicio = ultima_mudanca = ultimo_aviso = time.monotonic()
        assinatura = None
        estavel = 0
        notou_carregando = False
        while True:
            capturador.checar()
            try:
                perto, completas = pagina.evaluate(_JS_ESTADO)
                sinais = [s for s in pagina.evaluate(_JS_CARREGANDO) if s not in c["sinais_fixos"]] if indicadores else []
            except ErroPlaywright:
                return True
            em_voo = self._imagens_em_voo(rede, pagina)
            espera_algo = perto + em_voo + len(sinais)
            if espera_algo and not notou_carregando:
                notou_carregando = True
                c["esperou"] = c.get("esperou", 0) + 1          # a opção C usa isto para frear
            nova = (completas, em_voo, perto, tuple(sinais))
            agora = time.monotonic()
            if nova != assinatura:
                assinatura, ultima_mudanca = nova, agora
            if espera_algo == 0:
                estavel += 1
                if estavel >= 2:
                    return True
            else:
                estavel = 0
                if agora - ultima_mudanca >= parado_s or agora - inicio >= teto_s:
                    motivo = "nada novo carregou" if agora - ultima_mudanca >= parado_s else "tempo máximo do passo"
                    self._registrar(
                        f"Parei de esperar ({motivo}): {perto} imagem(ns) perto da tela e {em_voo} em andamento"
                        + (f"; indicador: {sinais[0]}" if sinais else "") + "."
                    )
                    for s in sinais:       # só vira "decoração" depois de travar duas vezes
                        c["travas"][s] = c["travas"].get(s, 0) + 1
                        if c["travas"][s] >= 2:
                            c["sinais_fixos"].add(s)
                    return False
                if agora - ultimo_aviso >= 10:
                    ultimo_aviso = agora
                    self._registrar(f"Aguardando carregar: {perto + em_voo} imagem(ns)… (já carregadas: {completas})")
            pagina.wait_for_timeout((70 if estavel else 130) if rapido else (150 if estavel else 300))

    def _forcar_carga(self, capturador, pagina, c: Dict[str, Any]) -> int:
        """Leva à tela cada imagem que ainda não carregou, para disparar carregadores baseados em rolagem."""
        from playwright.sync_api import Error as ErroPlaywright

        try:
            faltam = int(pagina.evaluate(_JS_PREPARAR_LAZY))
        except ErroPlaywright:
            return 0
        if not faltam:
            return 0
        self._registrar(f"{faltam} imagem(ns) ainda sem carregar; levando cada uma à tela para disparar o carregamento…")
        fim = time.monotonic() + 300.0
        for _ in range(min(faltam, 1500)):
            capturador.checar()
            if time.monotonic() > fim:
                break
            if not pagina.evaluate(_JS_MOSTRAR_PROXIMA):
                break
            pagina.wait_for_timeout(250)
        pagina.evaluate("window.scrollTo(0, 0)")
        return faltam

    # ------------------------------------------------------------ busca

    def _ingerir(self, capturador, pagina, contexto, respostas, itens, c: Dict[str, Any]) -> bool:
        """Obtém as imagens ainda desconhecidas de `itens`. Devolve False se a lista encheu."""
        from playwright.sync_api import Error as ErroPlaywright

        for item in itens:
            capturador.checar()
            url = str(item["url"]).split("#")[0]
            if url in c["tentadas"]:
                continue
            c["tentadas"].add(url)
            minuscula = url.lower()
            if not minuscula.startswith(("http://", "https://", "data:image/")):
                c["outros"] += 1  # blob:, about: etc.
                continue
            if not self.colecao.precisa_tentar(url):
                continue
            if self.colecao.cheia():
                self._registrar(f"Limite de {MAX_CANDIDATAS} imagens na lista atingido; as demais foram ignoradas.")
                return False

            largura, altura = int(item["w"]), int(item["h"])
            try:
                dados = self._obter(contexto, respostas, url)
                formato = detectar_formato(dados)
                resultado = self.colecao.adicionar(url, largura, altura, dados, formato)
            except Cancelado:
                raise
            except ErroBaixador as erro:
                motivo = str(erro)
                resultado = "erro"
                if c["prints"] < MAX_PRINTS_POR_BUSCA and not minuscula.startswith("data:"):
                    c["prints"] += 1
                    try:
                        png = self._print_do_elemento(pagina, url)
                        resultado = self.colecao.adicionar(url, largura, altura, png, "png", origem="print")
                        self._registrar(f"Não foi possível baixar o arquivo ({motivo}); salvei um print da imagem.")
                    except Cancelado:
                        raise
                    except (ErroBaixador, ErroPlaywright) as erro_print:
                        detalhe = erro_print if isinstance(erro_print, ErroBaixador) else _resumo(erro_print)
                        motivo = f"{motivo} | print: {detalhe}"
                if resultado == "erro":
                    self.colecao.adicionar(url, largura, altura, erro=motivo)
                    c["falhou"].add(url)
            if resultado == "nova":
                c["novas"] += 1
            elif resultado == "duplicada":
                c["duplicadas"] += 1
            elif resultado == "erro":
                c["falhas"] += 1
            elif resultado == "limite":
                return False
        return True

    def _descer(
        self, capturador, pagina, contexto, respostas, rede, c: Dict[str, Any],
        ignorar: bool, parado_s: int, detectar: bool, fator: float, rapido: bool = False,
    ) -> Tuple[bool, int]:
        """Desce a página aos poucos, lendo as imagens a cada passo. Devolve (chegou ao fim, ignoradas).

        Não tem limite de tempo fixo: em cada passo espera enquanto houver progresso no carregamento,
        e a descida só termina no fim da página (ou ao ser cancelada).
        """
        limite = time.monotonic() + 3 * 3600.0
        estavel = 0
        parado = 0
        ignoradas = 0
        chegou = False
        pagina.evaluate("window.scrollTo(0, 0)")
        pagina.wait_for_timeout(120 if rapido else 300)
        calmos = 0                                    # (opção C) passos seguidos em que nada estava carregando
        for passo in range(1, 20000):
            capturador.checar()
            if time.monotonic() > limite:
                break
            y_antes = pagina.evaluate("window.scrollY")
            pagina.evaluate(_JS_PREPARAR_LAZY)
            pagina.evaluate("(f) => window.scrollBy(0, Math.max(innerHeight * f, 250))", fator)
            pagina.wait_for_timeout(120 if rapido else 300)
            inicio_espera = time.monotonic()
            self._esperar_pagina(
                capturador, pagina, rede, float(parado_s), c, indicadores=detectar,
                teto_s=max(120.0, 4.0 * parado_s), rapido=rapido,
            )
            if rapido:       # adapta o passo pelo QUANTO a página demorou: espera longa → freia; tudo rápido → acelera
                demora = time.monotonic() - inicio_espera
                if demora > 1.2:
                    calmos = 0
                    fator = max(0.5, fator * 0.75)
                elif demora < 0.7:
                    calmos += 1
                    if calmos >= 2:
                        fator = min(0.95, fator * 1.2)
            leitura = pagina.evaluate(_JS_COLETAR, {"ignorar": ignorar})
            ignoradas = max(ignoradas, int(leitura["ignoradas"]))
            if not self._ingerir(capturador, pagina, contexto, respostas, leitura["lista"], c):
                break
            if passo % 10 == 0:
                self._registrar(
                    f"Descendo{' (C, passo ' + format(fator, '.2f') + ' da tela)' if rapido else ''}… passo {passo}, {len(self.colecao.para_tela())} imagem(ns) na lista "
                    f"(posição {int(pagina.evaluate('window.scrollY'))} de {int(pagina.evaluate('document.documentElement.scrollHeight'))} px)."
                )
            y_depois = pagina.evaluate("window.scrollY")
            no_fim = pagina.evaluate(
                "window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2"
            )
            parado = parado + 1 if (y_depois <= y_antes and not no_fim) else 0
            if no_fim:
                estavel += 1
                if estavel >= 2:
                    chegou = True
                    break
                pagina.wait_for_timeout(500 if rapido else 1200)   # chance de aparecer mais conteúdo no fim
            else:
                estavel = 0
                if parado >= 5:
                    self._registrar("A página parou de rolar antes do fim; seguindo para a conferência.")
                    break
        pagina.evaluate("window.scrollTo(0, 0)")
        return chegou, ignoradas

    def _sondar_ausentes(self, capturador, pagina, contexto, respostas, c: Dict[str, Any]) -> int:
        """Tenta obter os números que faltam numa sequência (p-004 entre p-003 e p-005)."""
        urls = [i["url"] for i in self.colecao.para_tela() if not i.get("erro")]
        achadas = 0
        for url in numeros_ausentes(urls)[:MAX_SONDAS]:
            capturador.checar()
            if url in c["tentadas"] or self.colecao.cheia():
                continue
            c["tentadas"].add(url)
            try:
                dados = self._obter(contexto, respostas, url)
                formato = detectar_formato(dados)
            except Cancelado:
                raise
            except ErroBaixador:
                continue
            try:
                largura, altura = pagina.evaluate(_JS_DIMENSOES, url)
            except Exception:
                largura = altura = 0
            if self.colecao.adicionar(url, int(largura), int(altura), dados, formato, origem="sequencia") == "nova":
                achadas += 1
                self._registrar(f"Imagem que faltava na sequência encontrada: {url.rsplit('/', 1)[-1]}")
        return achadas

    def _procurar(
        self, capturador, contexto, respostas, rede, ignorar: bool, espera: int, modo: str = "rapido",
    ) -> None:
        from playwright.sync_api import Error as ErroPlaywright

        c: Dict[str, Any] = {
            "novas": 0, "duplicadas": 0, "falhas": 0, "outros": 0, "prints": 0,
            "tentadas": set(), "falhou": set(), "sinais_fixos": set(), "travas": {},
        }
        ignoradas = 0
        try:
            pagina = self._pagina_ativa(contexto)
            abertas = [p for p in contexto.pages if not p.is_closed()]
            if len(abertas) > 1:
                self._registrar(
                    f"Há {len(abertas)} abas abertas; lendo a mais recente que está visível: {pagina.url[:120]}. "
                    "Feche as outras (ou ative o bloqueio de abas novas) se não for a certa."
                )
            rapido = modo == "rapido"
            self._registrar(
                "Descendo rápido; se a página estiver carregando, freio e espero…" if rapido else
                "Descendo a página devagar, esperando o carregamento terminar a cada passo…"
            )
            chegou, ignoradas = self._descer(
                capturador, pagina, contexto, respostas, rede, c, ignorar, espera, True, 0.9 if rapido else 0.6, rapido,
            )
            if not chegou:
                self._registrar("Aviso: a descida terminou antes do fim da página (lista cheia, rolagem travada ou limite).")

            # Conferência: repete (até 4 voltas) enquanto houver imagens por carregar E o número de
            # pendentes estiver diminuindo. Cada volta lê a página de novo e guarda o que já chegou.
            leitura: Dict[str, Any] = {"lista": [], "pendentes": 0, "quebradas": 0, "ignoradas": 0}
            anterior = None
            for volta in range(1, 5):
                capturador.checar()
                c["tentadas"] -= c["falhou"]          # o que falhou antes pode funcionar agora
                self._forcar_carga(capturador, pagina, c)
                if not self._esperar_pagina(capturador, pagina, rede, float(espera), c, indicadores=True, rapido=rapido):
                    self._registrar("O carregamento parou de avançar; conferindo o que já chegou.")
                tentadas = pagina.evaluate(_JS_REINTENTAR)
                if tentadas:
                    self._registrar(f"Tentando de novo {tentadas} imagem(ns) que falharam ao carregar…")
                    self._esperar_pagina(capturador, pagina, rede, min(float(espera), 20.0), c, indicadores=False)
                leitura = pagina.evaluate(_JS_COLETAR, {"ignorar": ignorar})
                ignoradas = max(ignoradas, int(leitura["ignoradas"]))
                self._registrar(f"Volta {volta}: a página mostra {len(leitura['lista'])} imagem(ns) prontas; obtendo as novas…")
                if not self._ingerir(capturador, pagina, contexto, respostas, leitura["lista"], c):
                    break
                faltam = int(leitura["pendentes"])
                if faltam == 0 or (anterior is not None and faltam >= anterior):
                    break
                anterior = faltam
            self.colecao.reordenar([str(i["url"]).split("#")[0] for i in leitura["lista"]])

            self._conferir_sequencia(capturador, pagina, contexto, respostas, rede, c, ignorar, espera)

            partes = [f"{c['novas']} nova(s)"]
            if c["duplicadas"]:
                partes.append(f"{c['duplicadas']} cópia(s) idêntica(s) ignorada(s)")
            if c["falhas"]:
                partes.append(f"{c['falhas']} sem acesso")
            if c["outros"]:
                partes.append(f"{c['outros']} do tipo blob:/outro ignorada(s)")
            if ignoradas:
                partes.append(f"{ignoradas} de comentários/avatares ignorada(s)")
            self._registrar("Busca concluída: " + ", ".join(partes) + ".")

            esperadas = len(leitura["lista"]) + int(leitura["pendentes"]) + int(leitura["quebradas"])
            tenho = {i["url"] for i in self.colecao.para_tela() if not i.get("erro")}
            na_lista = sum(1 for it in leitura["lista"] if _url_para_tela(str(it["url"]).split("#")[0]) in tenho)
            self._registrar(
                f"Conferência: a página tem {esperadas} imagem(ns) (sem comentários); {na_lista} estão na lista. "
                + ("Tudo certo." if na_lista + c["duplicadas"] >= esperadas and not leitura["pendentes"] else
                   f"Faltam {max(esperadas - na_lista - c['duplicadas'], 0)}: "
                   f"{leitura['pendentes']} ainda carregando, {leitura['quebradas']} com erro na própria página, "
                   f"{c['falhas']} sem acesso.")
            )
            if leitura["pendentes"]:
                self._registrar(
                    f"Atenção: {leitura['pendentes']} imagem(ns) ainda não terminaram de carregar. "
                    "Espere mais no navegador e procure de novo (ou aumente o tempo de espera)."
                )
            if self.colecao.cheia():
                self._registrar(f"A lista está no limite de {MAX_CANDIDATAS} imagens; baixe as marcadas e limpe a lista.")
        except Cancelado:
            self._registrar("Busca cancelada. O que já foi encontrado continua na lista.")
        except ErroPlaywright as erro:
            self._registrar(f"A busca falhou: {_resumo(erro)}")
        except Exception as erro:
            self._registrar(f"A busca falhou ({erro.__class__.__name__}).")
        finally:
            self._cancelar.clear()
            with self._lock:
                if self.estado == "procurando":
                    self.estado = "aguardando"

    def _conferir_sequencia(self, capturador, pagina, contexto, respostas, rede, c, ignorar: bool, espera: int) -> None:
        """Modo B: confere números pulados e imagens estranhamente pequenas numa sequência numerada."""
        ausentes = numeros_ausentes(i["url"] for i in self.colecao.para_tela() if not i.get("erro"))
        if ausentes and not self.colecao.cheia():
            self._registrar(f"Faltam {len(ausentes)} número(s) numa sequência de imagens. Segunda passada, mais devagar…")
            self._descer(capturador, pagina, contexto, respostas, rede, c, ignorar, espera, True, 0.3)
        achadas = self._sondar_ausentes(capturador, pagina, contexto, respostas, c)
        restantes = numeros_ausentes(i["url"] for i in self.colecao.para_tela() if not i.get("erro"))
        if restantes:
            nomes = ", ".join(u.rsplit("/", 1)[-1] for u in restantes[:8])
            self._registrar(
                f"Atenção: {len(restantes)} imagem(ns) da sequência continuam faltando (ex.: {nomes}). "
                "Podem não existir no site ou estar bloqueadas."
            )
        if achadas:
            self._registrar(f"{achadas} imagem(ns) que faltavam foram obtidas pelo padrão do nome.")
        pequenas = dimensoes_suspeitas(
            (i["url"], i["largura"], i["altura"]) for i in self.colecao.para_tela() if not i.get("erro")
        )
        if pequenas:
            nomes = ", ".join(u.rsplit("/", 1)[-1] for u in pequenas[:8])
            self._registrar(
                f"Atenção: {len(pequenas)} imagem(ns) bem menores que as outras da sequência "
                f"(cortadas ou ainda de carregamento?): {nomes}."
            )

    def _obter(self, contexto, respostas: Dict[str, Any], url: str) -> bytes:
        """Bytes da imagem: da própria resposta do navegador; senão, baixa com os cookies dele."""
        from playwright.sync_api import Error as ErroPlaywright

        if url.lower().startswith("data:"):
            return decodificar_data_uri(url, LIMITE_IMAGEM)
        resposta = respostas.get(url)
        if resposta is not None:
            try:
                conteudo = resposta.body()
                if len(conteudo) > LIMITE_IMAGEM:
                    raise ArquivoGrande(f"O arquivo ultrapassa o limite de {LIMITE_IMAGEM // 1024 // 1024} MB.")
                return conteudo
            except ErroPlaywright:
                pass  # corpo já descartado pelo navegador: baixa de novo abaixo
        return buscar_pelo_contexto(contexto, url, LIMITE_IMAGEM, self._timeout)

    def _print_do_elemento(self, pagina, url: str) -> bytes:
        """Print só do elemento <img>, para imagens cujo arquivo não pôde ser obtido."""
        if not pagina.evaluate(_JS_MARCAR, url):
            raise ErroBaixador("a imagem não está mais na página")
        try:
            png = pagina.locator("[data-baixador-alvo]").first.screenshot(type="png", timeout=10_000)
        finally:
            try:
                pagina.evaluate(_JS_DESMARCAR)
            except Exception:
                pass
        if len(png) > LIMITE_IMAGEM:
            raise ArquivoGrande("O print ultrapassa o limite de tamanho.")
        return png
