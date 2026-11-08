"""Lê o arquivo `.env` da raiz do projeto (sem dependências). A chave do Gemini NUNCA é escrita em código, log ou mensagem de erro."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict

from baixador import configuracao

ARQUIVO_ENV = configuracao.RAIZ / ".env"
_LINHA = re.compile(r"""^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$""")


def ler_env(arquivo: Path = None) -> Dict[str, str]:  # type: ignore[assignment]
    """{nome: valor} do .env (aspas simples/duplas removidas; comentários `#` ignorados). Arquivo ausente = {}."""
    arquivo = arquivo or ARQUIVO_ENV
    saida: Dict[str, str] = {}
    try:
        texto = arquivo.read_text(encoding="utf-8-sig")
    except (OSError, ValueError):
        return saida
    for linha in texto.splitlines():
        if linha.lstrip().startswith("#"):
            continue
        m = _LINHA.match(linha)
        if not m:
            continue
        valor = m.group(2)
        if valor[:1] in "\"'" and valor.count(valor[0]) >= 2:
            valor = valor[1:valor.index(valor[0], 1)]
        else:
            valor = valor.split(" #", 1)[0].strip()
        saida[m.group(1)] = valor.strip()
    return saida


def chave_openrouter() -> str:
    """A chave do OpenRouter (pode ser vazia), lida a cada chamada como a do Gemini."""
    return ler_env().get("key_openrouter", "").strip()


def chave_gemini() -> str:
    """A chave (pode ser vazia). Lida a cada chamada: editar o .env vale sem reiniciar o programa."""
    return ler_env().get("key_gemini", "").strip()
