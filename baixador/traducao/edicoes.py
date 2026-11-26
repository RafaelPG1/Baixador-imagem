"""Glossário por obra e edição de falas traduzidas.

Glossário: `<obra>/glossario.json` ({"TERMO": "tradução"}), o mesmo arquivo que o tradutor (Node) já lê.
Edições: `<capítulo>/edicoes.json` ({"id da fala": "texto"}) é a fonte da verdade; o `traducao.json` do capítulo é atualizado na hora
(mesmos ids e posições) e o tradutor reaplica `edicoes.json` toda vez que refaz o capítulo, então a edição sobrevive a reimportar/reprocessar.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from baixador.nucleo.erros import ErroBaixador

MAX_TERMOS, MAX_TEXTO = 500, 2000
_TRAVA = threading.Lock()
_RESERVADAS = ("manter", "auto", "termos")        # chaves do glossário antigo, que o legado apaga: não podem ser termo


def _atomico(arquivo: Path, dados: Any, indent: Optional[int] = 1) -> None:
    tmp = arquivo.with_name(arquivo.name + ".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=indent), encoding="utf-8")
    os.replace(tmp, arquivo)


def _ler(arquivo: Path) -> Dict[str, str]:
    try:
        d = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): v for k, v in d.items() if isinstance(v, str)} if isinstance(d, dict) else {}


def _linha(t: Any) -> str:
    return " ".join(str(t or "").split())


# --------------------------------------------------------------------------- glossário

def _pasta_obra(raiz: Path, obra: str) -> Path:
    if not obra or obra != Path(obra).name or obra.startswith("."):
        raise ErroBaixador("Obra inválida.")
    p = Path(raiz) / obra
    if not p.is_dir():
        raise ErroBaixador("Obra não encontrada.")
    return p


def ler_glossario(raiz: Path, obra: str) -> Dict[str, str]:
    d = _ler(_pasta_obra(raiz, obra) / "glossario.json")
    return {k: v for k, v in d.items() if k not in _RESERVADAS}


def gravar_glossario(raiz: Path, obra: str, termos: Any) -> Dict[str, str]:
    """Substitui o glossário da obra. Termos vazios somem; chaves reservadas e excesso são recusados."""
    if not isinstance(termos, dict):
        raise ErroBaixador("Glossário inválido.")
    limpo: Dict[str, str] = {}
    for k, v in termos.items():
        k, v = _linha(k)[:120], _linha(v)[:200]
        if not k or not v:
            continue
        if k.casefold() in _RESERVADAS:
            raise ErroBaixador(f"“{k}” é um nome reservado; escolha outro termo.")
        limpo[k] = v
    if len(limpo) > MAX_TERMOS:
        raise ErroBaixador(f"Máximo de {MAX_TERMOS} termos por obra.")
    arquivo = _pasta_obra(raiz, obra) / "glossario.json"
    with _TRAVA:
        if limpo:
            _atomico(arquivo, limpo)
        elif arquivo.is_file():
            arquivo.unlink()
    return limpo


def bloco_glossario(termos: Dict[str, str]) -> str:
    """Texto para a introdução enviada à IA. Vazio se não houver termos."""
    if not termos:
        return ""
    return "Glossário (use SEMPRE estas traduções):\n" + "\n".join(f"- {k} = {v}" for k, v in termos.items()) + "\n\n"


# --------------------------------------------------------------------------- edição de falas

def aplicar(cap: Path, mudancas: Dict[str, str], estados: Optional[tuple] = None) -> Dict[str, Any]:
    """Grava as edições em `edicoes.json` e no `traducao.json` do capítulo. `estados`: só altera falas que estejam nesses status.

    Devolve {"alteradas": [ids], "ignoradas": [{"id", "motivo"}]}. Nada é gravado se nenhuma fala valer.
    """
    cap = Path(cap)
    arq = cap / "traducao.json"
    with _TRAVA:
        try:
            doc = json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ErroBaixador("Este capítulo não tem tradução para editar.")
        unidades = {u.get("id"): u for p in doc.get("pages", []) for u in p.get("units", []) if isinstance(u, dict)}
        alteradas: List[str] = []
        ignoradas: List[Dict[str, str]] = []
        validas: Dict[str, str] = {}
        for i, t in mudancas.items():
            t = _linha(t)
            u = unidades.get(i)
            if u is None:
                ignoradas.append({"id": i, "motivo": "fala não existe neste capítulo"})
            elif not t or len(t) > MAX_TEXTO:
                ignoradas.append({"id": i, "motivo": "texto vazio ou longo demais"})
            elif estados and u.get("status") not in estados:
                ignoradas.append({"id": i, "motivo": "a fala não está marcada para revisão"})
            elif t == u.get("translation"):
                ignoradas.append({"id": i, "motivo": "igual ao que já estava"})
            else:
                validas[i] = t
        if not validas:
            return {"alteradas": [], "ignoradas": ignoradas}
        salvas = _ler(cap / "edicoes.json")
        salvas.update(validas)
        _atomico(cap / "edicoes.json", salvas)
        for i, t in validas.items():
            u = unidades[i]
            u.update(translation=t, status="ok", error=None, glossary=[], editada=True)
            alteradas.append(i)
        contagens: Dict[str, int] = {}
        for u in unidades.values():
            contagens[u.get("status")] = contagens.get(u.get("status"), 0) + 1
        doc["counts"] = contagens
        _atomico(arq, doc, indent=None)
    return {"alteradas": alteradas, "ignoradas": ignoradas}
