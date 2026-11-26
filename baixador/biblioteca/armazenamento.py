"""Espaço em disco da biblioteca: tamanho por obra (em cache) e limpeza segura de restos.

"Resto" é só o que comprovadamente não serve a mais nada: pastas `traducao.nova`/`traducao.velha` de capítulo que já tem tradução
concluída e não está sendo processado agora, e arquivos `.tmp` antigos. Nunca mexe em imagens, `traducao.json`, preparações da IA web,
trabalho que uma tradução interrompida ainda pode retomar, nem fora da biblioteca.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Set

from baixador.biblioteca import acervo, lixeira, organizacao as org
from baixador.biblioteca.capitulo import _varrer

_cache: Dict[str, Any] = {"chave": None, "valor": None}
_trava = threading.Lock()
IDADE_TMP = 3600.0                                    # só .tmp com mais de 1 h (gravação em andamento nunca é tocada)


def _bytes(pasta: Path) -> int:
    total = 0
    for atual, _dirs, arquivos in os.walk(pasta):
        for nome in arquivos:
            try:
                total += os.lstat(os.path.join(atual, nome)).st_size
            except OSError:
                pass
    return total


def tamanhos(raiz: Path) -> Dict[str, Any]:
    """{"obras": {nome: bytes}, "lixeira": bytes, "total": bytes}. Refeito só quando a biblioteca muda (mesma impressão digital da listagem)."""
    raiz = Path(raiz)
    chave = (str(raiz), acervo.versao(raiz), len(lixeira.listar(raiz)))
    with _trava:
        if _cache["chave"] == chave:
            return _cache["valor"]
    obras: Dict[str, int] = {}
    for c in _varrer(raiz):
        nome = c["obra"] or "Sem obra"
        obras[nome] = obras.get(nome, 0) + _bytes(c["pasta"])
    lx = _bytes(raiz / lixeira.NOME) if (raiz / lixeira.NOME).is_dir() else 0
    valor = {"obras": obras, "lixeira": lx, "total": sum(obras.values()) + lx}
    with _trava:
        _cache.update(chave=chave, valor=valor)
    return valor


def orfaos(raiz: Path, em_uso: Set[str], agora: float = 0.0) -> List[Dict[str, Any]]:
    """Restos seguros de apagar. `em_uso`: `rel` dos capítulos que uma tradução processa ou aguarda agora (nunca entram)."""
    raiz, agora, achados = Path(raiz), agora or time.time(), []
    for c in _varrer(raiz):
        pasta, rel = c["pasta"], c["rel"]
        if rel in em_uso or pasta.is_symlink():
            continue
        concluido = bool(c.get("traduzido")) and not c.get("incompleta")
        nova, velha = pasta / "traducao.nova", pasta / "traducao.velha"
        if concluido and (pasta / "traducao.json").is_file():
            if nova.is_dir() and not nova.is_symlink() and not (nova / "web" / "textos.json").is_file():
                achados.append({"tipo": "restos de tradução", "caminho": nova, "rel": rel})
            if velha.is_dir() and not velha.is_symlink() and not nova.exists():
                achados.append({"tipo": "tradução antiga substituída", "caminho": velha, "rel": rel})
        for pai in (pasta, pasta.parent):
            try:
                for e in pai.iterdir():
                    if e.is_file() and not e.is_symlink() and e.suffix == ".tmp" and agora - e.stat().st_mtime > IDADE_TMP:
                        achados.append({"tipo": "arquivo temporário", "caminho": e, "rel": rel})
            except OSError:
                pass
    vistos, unicos = set(), []
    for a in achados:
        if a["caminho"] not in vistos:
            vistos.add(a["caminho"])
            unicos.append(a)
    for a in unicos:
        a["bytes"] = _bytes(a["caminho"]) if a["caminho"].is_dir() else a["caminho"].stat().st_size
        a["caminho"] = a["caminho"].resolve().relative_to(raiz.resolve()).as_posix()
    return unicos


def limpar_orfaos(raiz: Path, em_uso: Set[str], caminhos: List[str] = ()) -> Dict[str, Any]:
    """Apaga restos (todos ou só os `caminhos` pedidos), conferindo DE NOVO cada um agora: o que deixou de ser resto fica."""
    raiz = Path(raiz)
    atuais = {a["caminho"]: a for a in orfaos(raiz, em_uso)}
    alvos = [atuais[c] for c in (caminhos or atuais) if c in atuais]
    liberados, apagados = 0, 0
    for a in alvos:
        p = raiz / a["caminho"]
        if p.is_dir():
            lixeira._apagar_arvore(p)
        else:
            p.unlink(missing_ok=True)
        liberados += a["bytes"]
        apagados += 1
    acervo.esquecer_versao()
    return {"apagados": apagados, "bytes": liberados}
