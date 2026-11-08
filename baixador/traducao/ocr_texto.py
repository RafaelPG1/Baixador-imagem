"""Conserto do texto lido pelo OCR ANTES de traduzir (o `original` guardado nunca é alterado).

- palavras coladas ("THEENEMY" -> "THE ENEMY"): só separa quando a palavra não existe e TODAS as partes são palavras
  comuns do inglês (lista embutida em dados/en_palavras.txt); nunca troca nem acrescenta letras;
- palavra cortada na quebra de linha ("UN- BELIEVABLE" -> "UNBELIEVABLE"): só se a junção é palavra conhecida;
- frase que continua no balão seguinte: `continua_no_seguinte` (só com evidência) e `dividir_traducao`.
"""

from __future__ import annotations

import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

ARQUIVO = Path(__file__).with_name("dados") / "en_palavras.txt"
LIM_CURTA, LIM_LONGA = 1.0e-5, 4.0e-6            # frequência mínima de uma parte (curtas até 4 letras exigem mais)
LIM_COMUM = 2.5e-4                               # ao menos uma parte tem de ser palavra MUITO comum (the, to, my...): compostos reais (gatekeeper) ficam
PENA_PARTE = 6.0                                 # prefere menos pedaços
MAX_PARTES = 4


@lru_cache(maxsize=1)
def _freq() -> Dict[str, float]:
    saida: Dict[str, float] = {}
    try:
        for linha in ARQUIVO.read_text(encoding="utf-8").splitlines():
            palavra, _, n = linha.partition("\t")
            if palavra and n.isdigit():
                saida[palavra] = int(n) / 1e9
    except OSError:
        pass                                      # sem a lista, nada é separado (comportamento antigo)
    return saida


def _parte_ok(p: str, f: Dict[str, float]) -> bool:
    if len(p) == 1:
        return p in ("a", "i")
    return f.get(p, 0.0) >= (LIM_CURTA if len(p) <= 4 else LIM_LONGA)


def separar_palavra(palavra: str) -> Optional[List[int]]:
    """Posições de corte (em `palavra`) se ela é uma colagem de palavras comuns; None caso contrário."""
    f = _freq()
    p = palavra.lower()
    if len(p) < 5 or not p.isalpha() or not f or p in f:
        return None
    n = len(p)
    melhor: List[Optional[tuple]] = [None] * (n + 1)      # (custo, anterior, partes)
    melhor[0] = (0.0, -1, 0)
    for fim in range(1, n + 1):
        for ini in range(max(0, fim - 14), fim):
            if melhor[ini] is None or melhor[ini][2] >= MAX_PARTES:
                continue
            parte = p[ini:fim]
            if not _parte_ok(parte, f):
                continue
            custo = melhor[ini][0] - math.log(f.get(parte, 1e-3)) + PENA_PARTE
            if melhor[fim] is None or custo < melhor[fim][0]:
                melhor[fim] = (custo, ini, melhor[ini][2] + 1)
    if melhor[n] is None or melhor[n][2] < 2:
        return None
    cortes, i = [], n
    while i > 0:
        i = melhor[i][1]  # type: ignore[index]
        if i > 0:
            cortes.append(i)
    cortes = sorted(cortes)
    pontos = [0] + cortes + [n]
    if not any(f.get(p[a:b], 0.0) >= LIM_COMUM for a, b in zip(pontos, pontos[1:])):
        return None
    return cortes


_RUN = re.compile(r"(?<![A-Za-z'’-])[A-Za-z]{5,}(?![A-Za-z]|['’-][A-Za-z])")


def _separar_run(m: "re.Match[str]", nomes: set) -> str:
    palavra = m.group(0)
    if palavra.lower() in nomes or not (palavra.isupper() or palavra.islower() or palavra.istitle()):
        return palavra                            # nome do glossário ou camelCase ("KyuYoung"): não mexe
    cortes = separar_palavra(palavra)
    if not cortes:
        return palavra
    partes, ant = [], 0
    for c in cortes + [len(palavra)]:
        partes.append(palavra[ant:c]); ant = c
    return " ".join(partes)


def consertar_texto(texto: str, nomes: Iterable[str] = ()) -> str:
    """Palavras coladas e palavras cortadas por hífen no fim da linha (inglês)."""
    if not _freq():
        return texto
    f = _freq()
    conhecidos = {n.lower() for n in nomes if n}
    # "UN- BELIEVABLE" / "EN-\nERGY": junta só se a junção é palavra e não são duas palavras comuns (SELF- ESTEEM fica)
    def junta(m: "re.Match[str]") -> str:
        a, b = m.group(1), m.group(2)
        j = (a + b).lower()
        if j in f and not (f.get(a.lower(), 0) >= LIM_LONGA and len(a) >= 3 and f.get(b.lower(), 0) >= LIM_LONGA and len(b) >= 3):
            return a + b
        return m.group(0)
    texto = re.sub(r"\b([A-Za-z]{1,12})-\s+([A-Za-z]{2,12})\b", junta, texto)
    return " ".join(_RUN.sub(lambda m: _separar_run(m, conhecidos), texto).split())


# --------------------------------------------------------------------------- frase dividida entre balões

PENDENTES = frozenset(          # palavras que dificilmente terminam uma fala: pedem complemento
    "a an the to of in on at for with by from and or but if as than because my your his her its our their which whose".split()
)
PARTICULAS = frozenset("out up down off on in away back over through about around along ahead apart together".split())
FIM_DE_FRASE = re.compile(r"[.!?…:;\"”»)\]]\s*$")


def _palavras(t: str) -> List[str]:
    return re.findall(r"[A-Za-z']+", t)


def continua_no_seguinte(a: str, b: str) -> bool:
    """Evidência textual de que `b` continua a frase de `a`: `a` não termina a frase E (termina em palavra que pede complemento
    OU `b` começa com partícula/minúscula). Sem isso, balões vizinhos continuam separados."""
    a, b = a.strip(), b.strip()
    pa, pb = _palavras(a), _palavras(b)
    if len(pa) < 2 or len(pb) < 2 or FIM_DE_FRASE.search(a):
        return False
    if b[:1].islower():
        return True
    ultima, primeira = pa[-1].lower(), pb[0].lower()
    if ultima in PENDENTES or primeira in PARTICULAS:
        return True
    return False


def dividir_traducao(traducao: str, pesos: Sequence[int]) -> List[str]:
    """Reparte a tradução de uma frase contínua entre os balões, em proporção ao tamanho do original,
    cortando em fronteira de palavra (de preferência depois de pontuação) e sem deixar artigo/preposição pendurado no fim."""
    palavras = traducao.split()
    n = len(pesos)
    if n <= 1 or len(palavras) < n:
        return [traducao] + [""] * (n - 1) if n > 1 else [traducao]
    total, acumulado, cortes, ant = float(sum(pesos)), 0, [], 0
    liga = {"a", "o", "as", "os", "um", "uma", "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas", "por", "pra", "para", "com", "que", "e", "ou", "se", "me", "te", "lhe", "meu", "minha", "seu", "sua"}
    for k in range(n - 1):
        acumulado += pesos[k]
        alvo = max(ant + 1, min(len(palavras) - (n - 1 - k), round(len(palavras) * acumulado / total)))
        cand = list(range(ant + 1, len(palavras) - (n - 2 - k)))
        def nota(c: int) -> float:
            pen = abs(c - alvo)
            if palavras[c - 1].lower().strip(",.;:!?…") in liga:
                pen += 2.5                       # não termina o balão em "de", "o", "que"...
            if palavras[c - 1][-1:] in ",;:.!?…":
                pen -= 1.0
            return pen
        c = min(cand, key=nota)
        cortes.append(c); ant = c
    partes, ini = [], 0
    for c in cortes + [len(palavras)]:
        partes.append(" ".join(palavras[ini:c])); ini = c
    return partes
