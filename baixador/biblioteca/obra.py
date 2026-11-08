"""Dados da obra: `obra.json` dentro da pasta da obra (ao lado dos capítulos e da capa).

Guarda o nome e a **URL principal** da obra no site (`https://site/title/nome-da-obra/`), nunca o endereço de um capítulo.
O `capitulo.json` de cada capítulo continua guardando o endereço específico daquele capítulo.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from baixador.biblioteca import capa

NOME_ARQUIVO = "obra.json"


def ler(pasta_obra: Path) -> Dict[str, Any]:
    try:
        dados = json.loads((Path(pasta_obra) / NOME_ARQUIVO).read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def url_principal(pasta_obra: Path) -> str:
    """URL principal salva da obra ('' se não houver). Só vale se tiver o formato de página de obra."""
    url = str(ler(pasta_obra).get("url") or "")
    return url if capa.url_da_obra(url) == url else ""


def gravar(pasta_obra: Path, nome: str = "", url_capitulo_ou_obra: str = "", substituir_url: bool = False) -> bool:
    """Cria/atualiza o `obra.json`. A URL é sempre reduzida à página da obra; uma URL já salva só muda se `substituir_url`.

    Devolve True se gravou. Falhas de disco não podem atrapalhar download nenhum (devolve False).
    """
    pasta_obra = Path(pasta_obra)
    dados = ler(pasta_obra)
    novo = dict(dados)
    if nome and not novo.get("nome"):
        novo["nome"] = nome[:120]
    principal = capa.url_da_obra(url_capitulo_ou_obra) if url_capitulo_ou_obra else None
    if principal and (substituir_url or not url_principal(pasta_obra)):
        novo["url"] = principal
    if novo == dados or not pasta_obra.is_dir():
        return False
    tmp = pasta_obra / ".obra.tmp"
    try:
        tmp.write_text(json.dumps(novo, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, pasta_obra / NOME_ARQUIVO)
        return True
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False


def url_dos_capitulos(pasta_obra: Path) -> Optional[str]:
    """Para obras antigas (sem `obra.json`): a página da obra deduzida do endereço guardado em algum `capitulo.json`."""
    from baixador.biblioteca import organizacao

    try:
        subs = sorted(p for p in Path(pasta_obra).iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return None
    for sub in subs:
        achada = capa.url_da_obra(str(organizacao.ler_meta(sub).get("url") or ""))
        if achada:
            return achada
    return None
