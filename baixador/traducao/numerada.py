"""Tradução da PÁGINA INTEIRA numa só chamada (Hy-MT2 modo B e Gemini): balões numerados em ordem de leitura -> lista numerada.

Garantia central: texto e balão nunca se desalinham. A resposta só é aceita item a item quando a lista volta com
EXATAMENTE os números 1..N, em ordem; item vazio/inválido é refeito sozinho (um balão por chamada); qualquer divergência na
quantidade/numeração desconfia da lista toda e refaz todos os balões um a um (nunca "chuta" qual item é de qual balão).
"""

from __future__ import annotations

import re
import sys
import time
from typing import List, Optional

from baixador.nucleo.erros import Cancelado
from baixador.traducao import hymt
from baixador.traducao import inteligencia as ia

INSTRUCAO = (
    "You are translating ONE page of a manga/manhwa. Below are ALL the speech balloons of the page, numbered in reading order. "
    "Translate every balloon into natural, informal Brazilian Portuguese (pt-BR), the way people really talk in a manga. "
    "Use 'você' (never 'tu'); keep the numbers exactly as they are; leave NO English words behind - nicknames such as "
    "'little guy' must be translated naturally (e.g. 'carinha', 'baixinho'); keep names unchanged; keep meaning, tone and "
    "personality, adding or omitting nothing. Use the whole page as context so the dialogue flows between balloons. "
    "Reply ONLY with the numbered list: same numbers, one line per balloon, nothing else (no comments, no explanations)."
)
_ITEM = re.compile(r"^\s*(\d{1,3})\s*[.)\]:]\s*(.*)$")


def montar_prompt(entradas: List[str], extra: str = "") -> str:
    lista = "\n".join(f"{i}. {t}" for i, t in enumerate(entradas, 1))
    return f"{INSTRUCAO}{extra}\n\nBalloons:\n{lista}"


def interpretar(resposta: str, n: int) -> Optional[List[str]]:
    """Lista de n textos (possivelmente vazios) ou None se a numeração não for exatamente 1..n em ordem."""
    t = re.sub(r"<think>.*?</think>", "", resposta, flags=re.S | re.I)
    t = re.sub(r"```[a-z]*", "", t)
    itens: List[str] = []
    numeros: List[int] = []
    for linha in t.splitlines():
        m = _ITEM.match(linha)
        if m:
            numeros.append(int(m.group(1)))
            itens.append(m.group(2).strip())
        elif itens and linha.strip():
            itens[-1] = (itens[-1] + " " + linha.strip()).strip()          # item que o modelo quebrou em duas linhas
    if numeros != list(range(1, n + 1)):
        return None
    return [" ".join(i.split()) for i in itens]


class TradutorNumerado:
    """Base: subclasses dão `_pedir(prompt, n)` (a chamada de rede) e `_um(texto, ctx)` (refazer um balão sozinho)."""

    lento = True                                       # nunca usado como "sonda" de palavras soltas
    nome_motor = "página inteira"
    origem = "hy"

    def __init__(self, de: str = "en", para: str = "pt") -> None:
        self.de, self.para = de, para
        self.refeitos = 0
        self.ultima_chamada = ""

    def _pedir(self, prompt: str, n: int) -> str:
        raise NotImplementedError

    def _um(self, texto: str, ctx: Optional[ia.Contexto]) -> str:
        raise NotImplementedError

    def _extra(self, textos: List[str], ctx: Optional[ia.Contexto]) -> str:
        if ctx is None:
            return ""
        junto = "\n".join(textos)
        achar = lambda t: re.search(r"(?<![\w-])" + re.escape(t) + r"(?![\w-])", junto, re.I)
        termos = [f"{t} => {f}" for t, f in ctx.termos.items() if achar(t)]
        nomes = [n for n in ctx.nomes if achar(n)]
        extra = ""
        if termos:
            extra += "\n\nTerminology (use exactly):\n" + "\n".join(termos)
        if nomes:
            extra += "\n\nKeep these names unchanged: " + ", ".join(nomes)
        return extra

    def _lista(self, entradas: List[str], limpos: List[str], ctx: Optional[ia.Contexto]) -> Optional[List[str]]:
        """Traduz a página numa chamada. Subclasses podem trocar o formato (ex.: Gemini com JSON estruturado)."""
        return interpretar(self._pedir(montar_prompt(entradas, self._extra(limpos, ctx)), len(entradas)), len(entradas))

    def traduzir_pagina(self, textos: List[str], ctx: Optional[ia.Contexto] = None) -> List[str]:
        if not textos:
            return []
        nomes = list(ctx.nomes) if ctx else []
        limpos = [ia.corrigir_ocr(t, nomes, self.de) for t in textos]
        altas = [t.isupper() or sum(c.isupper() for c in t) > 0.6 * max(1, sum(c.isalpha() for c in t)) for t in limpos]
        entradas = [" ".join((ia.frase_natural(t, nomes) if a else t).split()) for t, a in zip(limpos, altas)]
        saida: List[Optional[str]] = [None] * len(textos)
        if len(textos) > 1:
            try:
                lista = self._lista(entradas, limpos, ctx)
            except hymt.RespostaInvalida:
                lista = None
            if lista is not None:
                for i, item in enumerate(lista):
                    try:
                        saida[i] = hymt.validar(limpos[i], item) if item else None
                    except hymt.RespostaInvalida:
                        saida[i] = None
        for i, valor in enumerate(saida):                                   # só os balões com problema (ou todos, se a lista falhou)
            if valor is None:
                self.refeitos += 1
                try:
                    saida[i] = self._um(limpos[i], ctx)
                except hymt.RespostaInvalida:
                    saida[i] = limpos[i]                                    # sem resposta válida: fica o original (o leitor não cobre o balão)
        return [(s.upper() if a else s) if s is not limpos[i] else limpos[i] for i, (s, a) in enumerate(zip(saida, altas))]  # type: ignore[union-attr]

    def __call__(self, textos: List[str]) -> List[str]:
        return self.traduzir_pagina(textos, None)


def registrar_tempo(nome: str, balões: int, segundos: float, refeitos: Optional[int] = None) -> None:
    extra = f", {refeitos} refeito(s) um a um" if refeitos else ""
    print(f"[tempo] {nome}: {balões} balão(ões) em {segundos:.1f} s ({segundos / max(1, balões):.1f} s/balão{extra})", file=sys.stderr, flush=True)


__all__ = ["TradutorNumerado", "montar_prompt", "interpretar", "registrar_tempo", "Cancelado", "time"]
