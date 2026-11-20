"""Remove, uma vez, os arquivos do sistema de tradução antigo (Argos/Hy-MT2/Gemini/OpenRouter) das obras.

Só apaga nomes exatos e só quando são mesmo do formato antigo; o `traducao.json` novo (campo "formato": 2) nunca é tocado.
Imagens, capas, `obra.json` e tudo o mais ficam como estão.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List

from baixador.nucleo.cache_arquivos import CachePorData

NOMES_CAPITULO = ("traducao.parcial.json", "traducao.anterior.json", "traducao.aviso.json")
NOMES_OBRA = ("memoria_traducao.json", "memoria_termos.json")
_FORMATO_NOVO = re.compile(rb'"formato"\s*:\s*2\b')


_CACHE_FORMATO = CachePorData(maximo=20000)


def _formato_novo_no_disco(arquivo: Path) -> bool:
    try:
        with arquivo.open("rb") as f:
            return bool(_FORMATO_NOVO.search(f.read(120)))
    except OSError:
        return False


def traducao_nova(arquivo: Path) -> bool:
    """O `traducao.json` é do formato novo? Lê só o começo do arquivo (o campo "formato" é o primeiro). Guardado até o arquivo mudar."""
    return _CACHE_FORMATO.obter(arquivo, lambda: _formato_novo_no_disco(arquivo))


def _glossario_antigo(arquivo: Path) -> bool:
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(dados, dict) and any(k in dados for k in ("manter", "auto", "termos"))


def _apagar(arquivo: Path, relatorio: Dict[str, List[str]], erros: List[str]) -> None:
    if not arquivo.is_file() or arquivo.is_symlink():
        return
    try:
        arquivo.unlink()
        relatorio["apagados"].append(arquivo.name)
    except OSError as erro:
        erros.append(f"{arquivo}: {erro}")


def limpar(raiz: Path) -> Dict[str, object]:
    """Percorre `raiz/Obra/Capítulo`. Devolve {"apagados": [...nomes], "erros": [...]}."""
    relatorio: Dict[str, List[str]] = {"apagados": []}
    erros: List[str] = []
    if not raiz.is_dir():
        return {"apagados": [], "erros": []}
    _apagar_glossario_e_memorias(raiz, relatorio, erros)
    for obra in sorted(p for p in raiz.iterdir() if p.is_dir()):
        _apagar_glossario_e_memorias(obra, relatorio, erros)
        for cap in sorted(p for p in obra.iterdir() if p.is_dir()):
            for nome in NOMES_CAPITULO:
                _apagar(cap / nome, relatorio, erros)
            _apagar_glossario_e_memorias(cap, relatorio, erros)
            antigo = cap / "traducao.json"
            if antigo.is_file() and not traducao_nova(antigo):
                _apagar(antigo, relatorio, erros)
    return {"apagados": relatorio["apagados"], "erros": erros}


def _apagar_glossario_e_memorias(pasta: Path, relatorio: Dict[str, List[str]], erros: List[str]) -> None:
    for nome in NOMES_OBRA:
        _apagar(pasta / nome, relatorio, erros)
    glossario = pasta / "glossario.json"
    if glossario.is_file() and _glossario_antigo(glossario):   # um glossário novo ({"TERMO": "tradução"}) é preservado
        _apagar(glossario, relatorio, erros)
