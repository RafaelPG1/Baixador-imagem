"""Capítulos DO SITE: a lista oficial, qual capítulo está aberto e qual é o próximo, sem adivinhar.

Antes, "passar de capítulo" era só achar um botão "próximo" na página e apertá-lo. Isso não sabe se o capítulo seguinte existe:
um botão que leva a uma página "não encontrada" ou "em breve" era seguido do mesmo jeito, e a nova página era tratada como um
capítulo novo (o que acontece com o último capítulo de muitos sites, ou quando o título da aba ainda mostra o capítulo anterior).

Aqui o programa lê a lista de capítulos que o próprio site publica (página da obra, menu de capítulos), decide o próximo a partir
dela e confere, ao chegar, se a página é mesmo o capítulo esperado. Nada aqui usa o navegador: são só regras sobre endereços,
números e textos, para poderem ser testadas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Optional, Pattern, Tuple
from urllib.parse import parse_qsl, urljoin, urlsplit

from baixador.biblioteca import organizacao as org

MIN_ITENS_CONFIAVEL = 3            # menos que isso não é "uma lista de capítulos": pode ser só um link solto
MAX_ITENS = 5000
_PALAVRA_CAP = re.compile(r"(chapter|chap|capitulo|cap[íi]tulo|ch|ep|episode|episodio|epis[óo]dio|c)[-_./ ]*$", re.I)
_NUM_NO_CAMINHO = re.compile(r"(?<![\d.])(\d{1,4})(?:[-._](\d{1,2}))?(?!\d)")


def _valor(numero: Optional[str]) -> Optional[Decimal]:
    try:
        return Decimal(str(numero)) if numero not in (None, "") else None
    except InvalidOperation:
        return None


def _numero(inteiro: str, fracao: Optional[str]) -> Optional[str]:
    return org.normalizar_numero(f"{inteiro}.{fracao}" if fracao else inteiro)


def normalizar_url(url: str) -> str:
    """Endereço sem enfeites para comparar: minúsculas no site, sem # e sem barra final."""
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return url
    return f"{p.scheme.lower()}://{p.netloc.lower()}{p.path.rstrip('/') or '/'}" + (f"?{p.query}" if p.query else "")


# ----------------------------------------------------------------------------------------------- endereço → número

@dataclass(frozen=True)
class Modelo:
    """Como o endereço de um capítulo deste site é escrito (descoberto a partir de UM endereço de capítulo)."""

    host: str
    regex: Pattern[str]
    na_consulta: bool = False         # o número está em `?chapter=55` em vez de no caminho
    com_palavra: bool = False         # o número vem logo depois de "chapter", "capítulo", "ch", "ep"...: aí o endereço é fonte segura do número

    def numero(self, url: str) -> Optional[str]:
        try:
            p = urlsplit(url)
        except ValueError:
            return None
        if (p.netloc or "").lower() != self.host:
            return None
        alvo = p.query if self.na_consulta else p.path
        m = self.regex.fullmatch(alvo) if not self.na_consulta else self.regex.search(alvo)
        return _numero(m.group(1), m.group(2)) if m else None


def modelo_url(url: str) -> Optional[Modelo]:
    """Descobre onde fica o número do capítulo no endereço: "/manga/obra/chapter-55" → "/manga/obra/chapter-(N)"."""
    try:
        p = urlsplit(url)
    except ValueError:
        return None
    host = (p.netloc or "").lower()
    if not host:
        return None
    achados = list(_NUM_NO_CAMINHO.finditer(p.path))
    if achados:
        com_palavra = next((a for a in reversed(achados) if _PALAVRA_CAP.search(p.path[:a.start()][-14:])), None)
        m = com_palavra or achados[-1]
        antes, depois = p.path[: m.start()], p.path[m.end():]
        padrao = re.compile(re.escape(antes) + r"(\d{1,4})(?:[-._](\d{1,2}))?" + re.escape(depois), re.I)
        return Modelo(host, padrao, com_palavra=com_palavra is not None)
    q = next(((k, v) for k, v in parse_qsl(p.query) if re.fullmatch(r"\d{1,4}(?:[.,]\d{1,2})?", v) and re.search(r"cap|ch|ep|chapter", k, re.I)), None)
    if q:
        return Modelo(host, re.compile(r"(?:^|&)" + re.escape(q[0]) + r"=(\d{1,4})(?:[.,_-](\d{1,2}))?(?:&|$)", re.I), na_consulta=True, com_palavra=True)
    return None


# ----------------------------------------------------------------------------------------------- lista do site

@dataclass(frozen=True)
class Item:
    numero: str
    url: str
    rotulo: str = ""


class _Coletor(HTMLParser):
    """Junta, do HTML bruto de uma página, os links (`<a href>`) e as opções de menu (`<option value>`) com seu texto."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pares: List[Tuple[str, str]] = []
        self._abertos: List[List[Any]] = []       # [href, texto] dos <a>/<option> abertos

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        d = dict(attrs)
        if tag == "a" and d.get("href"):
            self._abertos.append([d["href"] or "", ""])
        elif tag == "option" and (d.get("value") or d.get("data-href") or d.get("data-url")):
            self._abertos.append([d.get("value") or d.get("data-href") or d.get("data-url") or "", ""])

    def handle_data(self, data: str) -> None:
        for item in self._abertos:
            item[1] += data

    def handle_endtag(self, tag: str) -> None:
        if tag in ("a", "option") and self._abertos:
            href, texto = self._abertos.pop()
            self.pares.append((href, " ".join(texto.split())[:120]))


def itens_de_pares(pares: Iterable[Tuple[str, str]], base: str, modelo: Optional[Modelo]) -> List[Item]:
    """Pares (endereço, texto) → capítulos. Só entram endereços escritos como os de capítulo deste site (o `modelo`)."""
    if modelo is None:
        return []
    achados: Dict[str, Item] = {}
    for href, texto in pares:
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        try:
            completo = urljoin(base, href.strip()).split("#")[0]
        except ValueError:
            continue
        numero = modelo.numero(completo)
        if numero is None:
            continue
        atual = achados.get(numero)
        if atual is None or len(completo) < len(atual.url):          # o mesmo número com dois endereços: fica o mais curto
            achados[numero] = Item(numero, completo, texto)
        if len(achados) >= MAX_ITENS:
            break
    return list(achados.values())


def itens_do_html(html: str, base: str, modelo: Optional[Modelo]) -> List[Item]:
    coletor = _Coletor()
    try:
        coletor.feed(html[:3_000_000])
        coletor.close()
    except Exception:
        pass
    return itens_de_pares(coletor.pares, base, modelo)


class IndiceSite:
    """Os capítulos que o site realmente publica, em ordem numérica."""

    def __init__(self, itens: Iterable[Item], origem: str = "", url_obra: str = "") -> None:
        por_numero: Dict[str, Item] = {}
        for it in itens:
            por_numero.setdefault(it.numero, it)
        self.itens: List[Item] = sorted(por_numero.values(), key=lambda i: _valor(i.numero) or Decimal(0))
        self._por_numero = {i.numero: i for i in self.itens}
        self._por_url = {normalizar_url(i.url): i for i in self.itens}
        self.origem = origem
        self.url_obra = url_obra

    def __len__(self) -> int:
        return len(self.itens)

    @property
    def confiavel(self) -> bool:
        return len(self.itens) >= MIN_ITENS_CONFIAVEL

    @property
    def maior(self) -> Optional[Item]:
        return self.itens[-1] if self.itens else None

    @property
    def menor(self) -> Optional[Item]:
        return self.itens[0] if self.itens else None

    def por_url(self, url: str) -> Optional[Item]:
        return self._por_url.get(normalizar_url(url))

    def por_numero(self, numero: Optional[str]) -> Optional[Item]:
        return self._por_numero.get(numero or "")

    def proximo_de(self, numero: str) -> Optional[Item]:
        v = _valor(numero)
        return next((i for i in self.itens if v is not None and (_valor(i.numero) or Decimal(0)) > v), None)

    def unir(self, outro: "IndiceSite") -> "IndiceSite":
        return IndiceSite([*self.itens, *outro.itens], origem="+".join(x for x in (self.origem, outro.origem) if x), url_obra=self.url_obra or outro.url_obra)


# ----------------------------------------------------------------------------------------------- capítulo aberto

@dataclass
class Atual:
    numero: Optional[str]
    fonte: str                       # "lista" | "endereço" | "título" | ""
    aviso: str = ""
    item: Optional[Item] = None


def identificar_atual(url: str, titulo: str, modelo: Optional[Modelo], indice: Optional[IndiceSite]) -> Atual:
    """Número do capítulo aberto, com a fonte mais confiável: a lista do site > o endereço > o título da aba.

    O título da aba é o menos confiável: em sites feitos com JavaScript ele muda depois da página, e por um instante ainda mostra o
    capítulo anterior. O endereço não tem esse problema.
    """
    n_titulo = org.extrair_capitulo(titulo or "", "")["numero"]
    if indice is not None and indice.confiavel:
        item = indice.por_url(url)
        if item:
            aviso = f"o título da aba diz capítulo {n_titulo}, mas a lista do site diz {item.numero}; usei a lista." if n_titulo and n_titulo != item.numero else ""
            return Atual(item.numero, "lista", aviso, item)
    n_url = modelo.numero(url) if modelo else None
    if n_url and modelo is not None and not modelo.com_palavra and n_titulo:
        n_url = None                      # número solto no endereço ("/obra/55/pagina/1"): na dúvida vale o título da aba
    if n_url:
        aviso = f"o título da aba diz capítulo {n_titulo}, mas o endereço diz {n_url}; usei o endereço." if n_titulo and n_titulo != n_url else ""
        return Atual(n_url, "endereço", aviso)
    if n_titulo:
        return Atual(n_titulo, "título")
    return Atual(None, "")


# ----------------------------------------------------------------------------------------------- decidir o próximo

@dataclass
class Decisao:
    tipo: str                        # "lista" (ir ao endereço da lista) | "fim" | "fora-da-lista" | "botao" (sem lista confiável)
    item: Optional[Item] = None
    mensagem: str = ""
    aviso: str = ""


def decidir_proximo(indice: Optional[IndiceSite], atual: Atual) -> Decisao:
    if indice is None or not indice.confiavel or atual.numero is None:
        return Decisao("botao")
    maior, valor = indice.maior, _valor(atual.numero)
    if atual.item is None and maior is not None and valor is not None and valor > (_valor(maior.numero) or Decimal(0)):
        return Decisao(
            "fora-da-lista",
            mensagem=f"O capítulo {atual.numero} não consta na lista de capítulos do site: o último que o site tem é o {maior.numero}. Não avancei.",
        )
    proximo = indice.proximo_de(atual.numero)
    if proximo is None:
        return Decisao("fim", mensagem=f"Já está atualizado: o último capítulo do site é o {atual.numero}.")
    aviso = ""
    if valor is not None and (_valor(proximo.numero) or Decimal(0)) - valor > 1:
        aviso = f"o site não tem os capítulos entre {atual.numero} e {proximo.numero}; o próximo que ele publica é o {proximo.numero}."
    return Decisao("lista", proximo, aviso=aviso)


# ----------------------------------------------------------------------------------------------- conferir a chegada

def validar_chegada(
    atual_numero: Optional[str], destino_url: str, novo_url: str, novo: Atual, indice: Optional[IndiceSite],
    status: int = 0, esperado: Optional[Item] = None, nao_capitulo: Iterable[str] = (),
) -> Tuple[bool, str]:
    """Depois de ir para o "próximo": a página aberta é mesmo o capítulo seguinte? Devolve (ok, motivo se não).

    `nao_capitulo`: endereços que nunca são capítulo (a página da obra, a inicial do site): é para onde sites costumam mandar quando
    o "próximo" não existe.
    """
    if status >= 400:
        return False, f"o site respondeu {status} (página inexistente) ao abrir {destino_url[:100] or novo_url[:100]}; o capítulo seguinte não existe."
    if normalizar_url(novo_url) in {normalizar_url(u) for u in nao_capitulo if u}:
        return False, f"o site levou para a página da obra ou a inicial ({novo_url[:100]}), não para um capítulo: não há capítulo seguinte."
    if esperado is not None:
        if normalizar_url(novo_url) != normalizar_url(esperado.url) and (novo.item is None or novo.item.numero != esperado.numero):
            return False, f"esperava o capítulo {esperado.numero}, mas o site abriu outro endereço ({novo_url[:100]})."
        if novo.numero and novo.numero != esperado.numero:
            return False, f"esperava o capítulo {esperado.numero}, mas a página aberta é o capítulo {novo.numero}."
        return True, ""
    # sem lista: confere só o número. Tem de ser maior e no máximo 1 acima (nunca pular um capítulo)
    va, vn = _valor(atual_numero), _valor(novo.numero)
    if vn is None:
        return True, ""                   # nada permite conferir o número (endereço e título sem número): vale a conferência das imagens
    if va is not None and vn <= va:
        return False, f"o botão levou ao capítulo {novo.numero}, que não vem depois do {atual_numero}."
    if va is not None and vn - va > 1:
        return False, f"o botão levou do capítulo {atual_numero} ao {novo.numero}: isso pularia capítulo(s). Parei para você conferir no site."
    if indice is not None and indice.confiavel and indice.por_numero(novo.numero) is None:
        return False, f"o capítulo {novo.numero} não consta na lista de capítulos do site."
    return True, ""
