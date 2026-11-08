"""Análise de imagens em sequência (página-001.jpg, página-002.jpg...): números pulados e tamanhos estranhos.

Só olha os nomes e as dimensões das imagens já encontradas; não faz nenhuma requisição.
"""

from __future__ import annotations

import re
from collections import defaultdict
from statistics import median
from typing import Dict, Iterable, List, Tuple
from urllib.parse import urlsplit, urlunsplit

_PADRAO = re.compile(r"^(?P<pre>.*?)(?P<num>\d+)(?P<suf>(?:[-_.]?[A-Za-z]{0,8})?\.[A-Za-z0-9]{2,5})$")

MIN_NA_SEQUENCIA = 4        # menos que isso não é considerado uma sequência
MAX_AUSENTES = 40           # sequência com mais buracos que isso é tratada como coincidência
MAX_INTERVALO = 1000


def _chave(url: str):
    """(grupo, número, tamanho do preenchimento, consulta) ou None se o nome não termina em número."""
    try:
        partes = urlsplit(url)
    except ValueError:
        return None
    if partes.scheme not in ("http", "https") or not partes.netloc:
        return None
    pasta, _, arquivo = partes.path.rpartition("/")
    encontrado = _PADRAO.match(arquivo)
    if not encontrado:
        return None
    grupo = (partes.scheme, partes.netloc, pasta, encontrado["pre"], encontrado["suf"])
    return grupo, int(encontrado["num"]), encontrado["num"], partes.query


def agrupar(urls: Iterable[str]) -> Dict[tuple, List[Tuple[int, str, str]]]:
    grupos: Dict[tuple, List[Tuple[int, str, str]]] = defaultdict(list)
    for url in urls:
        chave = _chave(url)
        if chave:
            grupo, numero, texto, consulta = chave
            grupos[grupo].append((numero, texto, consulta))
    return {g: sorted(set(v)) for g, v in grupos.items() if len({n for n, _, _ in v}) >= MIN_NA_SEQUENCIA}


def _montar(grupo: tuple, numero: int, largura: int, consulta: str) -> str:
    esquema, rede, pasta, pre, suf = grupo
    nome = f"{pre}{str(numero).zfill(largura)}{suf}"
    return urlunsplit((esquema, rede, f"{pasta}/{nome}", consulta, ""))


def numeros_ausentes(urls: Iterable[str]) -> List[str]:
    """URLs prováveis das imagens que faltam entre a menor e a maior de cada sequência."""
    ausentes: List[str] = []
    for grupo, itens in agrupar(urls).items():
        numeros = {n for n, _, _ in itens}
        menor, maior = min(numeros), max(numeros)
        if maior - menor > MAX_INTERVALO:
            continue
        faltam = [n for n in range(menor, maior + 1) if n not in numeros]
        if not faltam or len(faltam) > MAX_AUSENTES or len(faltam) > len(numeros):
            continue
        preenchido = any(t.startswith("0") and len(t) > 1 for _, t, _ in itens)
        largura = max(len(t) for _, t, _ in itens) if preenchido else 0
        consulta = itens[0][2]
        ausentes += [_montar(grupo, n, largura, consulta) for n in faltam]
    return ausentes


def dimensoes_suspeitas(imagens: Iterable[Tuple[str, int, int]]) -> List[str]:
    """URLs de imagens bem menores que as outras da mesma sequência (cortadas ou ainda 'de mentira')."""
    imagens = [(u, w, h) for u, w, h in imagens if w > 0 and h > 0]
    por_url = {u: (w, h) for u, w, h in imagens}
    suspeitas: List[str] = []
    for grupo, itens in agrupar(u for u, _, _ in imagens).items():
        membros = [u for u in por_url if (c := _chave(u)) and c[0] == grupo]
        if len(membros) < MIN_NA_SEQUENCIA:
            continue
        mw = median(por_url[u][0] for u in membros)
        mh = median(por_url[u][1] for u in membros)
        suspeitas += [u for u in membros if por_url[u][0] < mw * 0.5 or por_url[u][1] < mh * 0.25]
    return suspeitas
