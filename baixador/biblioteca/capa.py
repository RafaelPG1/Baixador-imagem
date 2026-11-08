"""Capa da obra: `capa.jpg` (ou .png/.webp/…) dentro da pasta da obra, ao lado dos capítulos.

Duas origens: o usuário coloca o arquivo à mão (nome `capa`), ou o programa a pega sozinho na página da obra do site,
a partir do endereço do capítulo (`…/title/nome-da-obra/123-capitulo` → `…/title/nome-da-obra/`). Nunca sobrescreve
uma capa que já exista, e qualquer falha só significa "sem capa" (a biblioteca mostra uma inicial no lugar).
"""

from __future__ import annotations

import os
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from baixador.nucleo.erros import ErroBaixador
from baixador.nucleo.imagens import detectar_formato

EXTENSOES = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif")
LIMITE_PAGINA = 3 * 1024 * 1024
LIMITE_CAPA = 6 * 1024 * 1024
# pasta de "página da obra" nos endereços de capítulo: /title/<obra>/<capítulo>
SECOES_DA_OBRA = {"title", "titles", "series", "manga", "manhwa", "manhua", "comic", "comics", "book", "obra", "titulo"}
_MINIATURA = re.compile(r"@\d+(\.\w+)(?=$|\?)")
_FORMATO_EXT = {"jpeg": ".jpg", "jpg": ".jpg", "png": ".png", "webp": ".webp", "avif": ".avif", "gif": ".gif"}


def _extensao(dados: bytes) -> Optional[str]:
    try:
        return _FORMATO_EXT.get(detectar_formato(dados))
    except ErroBaixador:
        return None


def achar(pasta_obra: Path) -> Optional[Path]:
    """A capa já existente na pasta da obra (`capa.<ext>`), se houver."""
    for ext in EXTENSOES:
        p = Path(pasta_obra) / ("capa" + ext)
        try:
            if p.is_file() and not p.is_symlink():
                return p
        except OSError:
            continue
    return None


def url_da_obra(url: str) -> Optional[str]:
    """`https://site/title/13ne-reincarnated-murim-lord/11316059-chapter-137` → `https://site/title/13ne-reincarnated-murim-lord/`."""
    try:
        d = urlsplit(url or "")
    except ValueError:
        return None
    if d.scheme not in ("http", "https") or not d.netloc:
        return None
    partes = [p for p in d.path.split("/") if p]
    for i, p in enumerate(partes[:-1]):
        if p.lower() in SECOES_DA_OBRA:
            return f"{d.scheme}://{d.netloc}/{partes[i]}/{partes[i + 1]}/"
    return None


_VAZIAS = {"img", "meta", "br", "link", "input", "hr", "source", "area", "base", "col", "embed", "param", "track", "wbr"}


class _Imagens(HTMLParser):
    """Lista as `<img>` da página e marca as que estão dentro de um elemento de classe "poster" (a capa nos sites de obras)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.imgs: List[dict] = []
        self.og: Optional[str] = None
        self._pilha: List[Tuple[str, bool]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "img":
            a["_poster"] = "1" if any(f for _, f in self._pilha) or "poster" in a.get("class", "").lower().split() else ""
            self.imgs.append(a)
        elif tag == "meta" and a.get("property", "").lower() == "og:image" and a.get("content") and self.og is None:
            self.og = a["content"]
        if tag not in _VAZIAS:
            self._pilha.append((tag, "poster" in a.get("class", "").lower().split()))

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self._pilha) - 1, -1, -1):
            if self._pilha[i][0] == tag:
                del self._pilha[i:]
                break


def _maior_do_srcset(srcset: str) -> Optional[str]:
    melhor, peso = None, -1.0
    for item in srcset.split(","):
        partes = item.strip().split()
        if not partes:
            continue
        w = 0.0
        if len(partes) > 1:
            try:
                w = float(partes[1].rstrip("wx"))
            except ValueError:
                w = 0.0
        if w >= peso:
            melhor, peso = partes[0], w
    return melhor


def candidatas_da_pagina(html: str, base: str) -> List[str]:
    """Endereços possíveis da capa dentro da página da obra, da maior resolução para a menor.

    A `<img>` de `/covers/` (ou de classe "cover"): a maior do `srcset`, a versão sem o sufixo de miniatura (`@280`) e o `src`.
    Sem essa imagem, o `og:image`.
    """
    p = _Imagens()
    try:
        p.feed(html)
    except Exception:
        pass
    achadas: List[str] = []

    def somar(u: Optional[str]) -> None:
        if u and not u.startswith("data:"):
            completa = urljoin(base, u.strip())
            if completa not in achadas:
                achadas.append(completa)

    def da_capa(a: dict) -> bool:
        src, srcset = a.get("src", ""), a.get("srcset", "")
        return "/covers/" in src or "/covers/" in srcset or "cover" in a.get("class", "").lower()

    for escolhida in ([a for a in p.imgs if a.get("_poster")], [a for a in p.imgs if da_capa(a)]):   # `.poster img` primeiro
        if escolhida:
            a = escolhida[0]
            src, srcset = a.get("src", ""), a.get("srcset", "") or a.get("data-srcset", "")
            if srcset:
                somar(_maior_do_srcset(srcset))
            somar(_MINIATURA.sub(r"\1", src))
            somar(src)
            somar(a.get("data-src"))
            break
    if not achadas and p.og:
        somar(p.og)
    return achadas


def capa_da_pagina(html: str, base: str) -> Optional[str]:
    achadas = candidatas_da_pagina(html, base)
    return achadas[0] if achadas else None


def gravar(pasta_obra: Path, dados: bytes, substituir: bool = False) -> Optional[Path]:
    """Grava `capa.<ext>` se for imagem de verdade. Sem `substituir`, nunca troca uma capa existente."""
    pasta_obra = Path(pasta_obra)
    antiga = achar(pasta_obra)
    if (antiga is not None and not substituir) or not dados or len(dados) > LIMITE_CAPA:
        return None
    ext = _extensao(dados)
    if ext is None or not pasta_obra.is_dir():
        return None
    destino, tmp = pasta_obra / ("capa" + ext), pasta_obra / ".capa.tmp"
    try:
        tmp.write_bytes(dados)
        os.replace(tmp, destino)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return None
    if antiga is not None and antiga != destino:                      # a capa nova já está salva: só então some a antiga
        try:
            antiga.unlink()
        except OSError:
            pass
    return destino


Buscador = Callable[[str, int], bytes]


def baixar_primeira(candidatas: List[str], buscar_url: Buscador) -> Tuple[Optional[bytes], str]:
    """Tenta cada endereço (maior resolução primeiro) e devolve a primeira que for imagem de verdade."""
    ultimo = "Não achei a imagem de capa na página da obra."
    for url in candidatas:
        try:
            dados = buscar_url(url, LIMITE_CAPA)
        except Exception as erro:
            ultimo = f"Não consegui baixar a imagem da capa ({str(erro)[:120] or erro.__class__.__name__})."
            continue
        if _extensao(dados):
            return dados, ""
        ultimo = "O endereço da capa não devolveu uma imagem."
    return None, ultimo


def procurar(url_obra: str, buscar_url: Buscador) -> Tuple[Optional[bytes], str]:
    """Pega a capa na página da obra (HTML bruto). Devolve (bytes da imagem, "") ou (None, motivo legível)."""
    try:
        html = buscar_url(url_obra, LIMITE_PAGINA).decode("utf-8", "replace")
    except Exception as erro:
        return None, f"Não consegui abrir a página da obra ({str(erro)[:120] or erro.__class__.__name__})."
    candidatas = candidatas_da_pagina(html, url_obra)
    if not candidatas:
        return None, "Não achei a imagem de capa na página da obra."
    return baixar_primeira(candidatas, buscar_url)


def buscar(url_capitulo: str, buscar_url: Buscador) -> Optional[Tuple[str, bytes]]:
    """Atalho: a capa a partir do endereço de um capítulo (corta até a página da obra)."""
    obra = url_da_obra(url_capitulo)
    if not obra:
        return None
    dados, _ = procurar(obra, buscar_url)
    return (obra, dados) if dados else None


def candidatas_do_dom(info: dict, base: str) -> List[str]:
    """Mesma escolha, a partir do que o navegador leu na página já renderizada: {"srcset", "src", "atual", "base"}.

    A maior do `srcset` vem primeiro, depois a versão sem `@280`, depois o `src`/`currentSrc`. URLs relativas são
    resolvidas pelo endereço da página (`info["base"]`), senão pela URL principal da obra.
    """
    ref = str(info.get("base") or base)
    achadas: List[str] = []

    def somar(u: Optional[str]) -> None:
        if u and not str(u).startswith("data:"):
            completa = urljoin(ref, str(u).strip())
            if completa.startswith(("http://", "https://")) and completa not in achadas:
                achadas.append(completa)

    srcset = str(info.get("srcset") or "")
    if srcset:
        somar(_maior_do_srcset(srcset))
    for chave in ("src", "atual"):
        valor = str(info.get(chave) or "")
        somar(_MINIATURA.sub(r"\1", valor))
        somar(valor)
    return achadas


def baixar_direto(url: str, limite: int, tempo: float = 20.0) -> bytes:
    """Baixa `url` sem navegador (sites sem proteção): só http(s) públicos, redirecionamentos revalidados à mão."""
    import urllib.error
    import urllib.request

    from baixador.nucleo import seguranca

    class _SemRedirecionar(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    abridor = urllib.request.build_opener(_SemRedirecionar)
    atual = url
    for _ in range(6):
        seguranca.validar_url(atual)
        pedido = urllib.request.Request(atual, headers={"User-Agent": "Mozilla/5.0 (compatible; BaixadorDeImagens)", "Accept": "*/*"})
        try:
            with abridor.open(pedido, timeout=tempo) as resposta:
                corpo = resposta.read(limite + 1)
        except urllib.error.HTTPError as erro:
            if erro.code in (301, 302, 303, 307, 308) and erro.headers.get("Location"):
                atual = urljoin(atual, erro.headers["Location"])
                continue
            raise ErroBaixador(f"O site respondeu {erro.code}.") from None
        except (urllib.error.URLError, OSError, ValueError) as erro:
            raise ErroBaixador(f"Falha de conexão ({str(getattr(erro, 'reason', erro))[:80]}).") from None
        if len(corpo) > limite:
            raise ErroBaixador("O arquivo é grande demais.")
        return corpo
    raise ErroBaixador("Redirecionamentos demais.")
