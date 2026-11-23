"""Capítulos já lidos no notebook: um conjunto de caminhos relativos (`Obra/Cap 001`) em `dados/lidos.json`.

Fica em arquivo, não no navegador: a página do notebook usa uma porta nova a cada abertura, então o LocalStorage dela
seria perdido ao fechar o programa. O celular tem porta fixa e guarda o seu próprio histórico no LocalStorage.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Set

from baixador import configuracao

ARQUIVO = configuracao.DADOS / "lidos.json"
_trava = threading.Lock()
_cache = {"assinatura": None, "lidos": frozenset()}


def _assinatura() -> object:
    try:
        st = os.stat(ARQUIVO)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _ler() -> Set[str]:
    try:
        dados = json.loads(ARQUIVO.read_text(encoding="utf-8"))
        return {r for r in dados if isinstance(r, str)} if isinstance(dados, list) else set()
    except (OSError, ValueError):
        return set()                                             # ausente ou corrompido = nada lido (nunca derruba a biblioteca)


def todos() -> frozenset:
    """Conjunto atual; só relê o arquivo quando ele muda (a biblioteca consulta isto a cada atualização da lista)."""
    with _trava:
        ass = _assinatura()
        if ass != _cache["assinatura"]:
            _cache.update(assinatura=ass, lidos=frozenset(_ler()))
        return _cache["lidos"]  # type: ignore[return-value]


def _gravar(lidos: Set[str]) -> None:
    ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
    tmp = ARQUIVO.with_suffix(".tmp")
    tmp.write_text(json.dumps(sorted(lidos), ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, ARQUIVO)                                     # troca atômica: queda no meio da gravação não perde o histórico


def marcar(rel: str, lido: bool) -> None:
    with _trava:
        atual = _ler()
        (atual.add if lido else atual.discard)(rel)
        _gravar(atual)
        _cache["assinatura"] = None


def esquecer(rels: list) -> None:
    """Capítulos apagados do disco saem do histórico."""
    with _trava:
        atual = _ler()
        if atual & set(rels):
            _gravar(atual - set(rels))
            _cache["assinatura"] = None


def mover(antigo: str, novo: str) -> None:
    """Capítulo (ou obra inteira) renomeado: o histórico acompanha o novo caminho."""
    if antigo == novo:
        return
    with _trava:
        atual = _ler()
        mudou = {novo + r[len(antigo):] for r in atual if r == antigo or r.startswith(antigo + "/")}
        if not mudou:
            return
        _gravar({r for r in atual if not (r == antigo or r.startswith(antigo + "/"))} | mudou)
        _cache["assinatura"] = None
