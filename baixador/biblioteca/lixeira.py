"""Lixeira da biblioteca: excluir obra/capítulo MOVE para `<biblioteca>/.lixeira/<id>/` em vez de apagar.

Cada entrada guarda a árvore original (`dados/<Obra>/<Capítulo>/…`, mais `obra.json` e capa quando a obra inteira saiu) e um `meta.json`
com a data. Dá para restaurar (sem sobrescrever nada que exista), apagar de vez ou esperar a limpeza automática (14 dias).
A pasta começa com ponto: a biblioteca não a enxerga como obra nem como capítulo.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from baixador.nucleo.erros import ErroBaixador

NOME = ".lixeira"
DIAS = 14


def _pasta(raiz: Path) -> Path:
    return Path(raiz) / NOME


def _apagar_arvore(pasta: Path) -> None:
    def _forcar(funcao, caminho, _info):
        os.chmod(caminho, 0o700)                      # arquivo somente-leitura (Windows)
        funcao(caminho)

    shutil.rmtree(pasta, onerror=_forcar)


def _tamanho(pasta: Path) -> int:
    return sum(f.stat().st_size for f in pasta.rglob("*") if f.is_file() and not f.is_symlink())


def _rel(raiz: Path, caminho: Path) -> str:
    return Path(caminho).resolve().relative_to(Path(raiz).resolve()).as_posix()


def _gravar_meta(entrada: Path, meta: Dict[str, Any]) -> None:
    tmp = entrada / "meta.json.tmp"
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, entrada / "meta.json")


def enviar(raiz: Path, capitulos: Iterable[Path], obra: str, tipo: str, extras: Iterable[Path] = ()) -> Optional[str]:
    """Move as pastas de capítulo (e, se pedido, os arquivos soltos da obra) para uma entrada nova. Devolve o id (None se não havia nada).

    Se algo falhar no meio, o que já foi movido volta ao lugar original: nunca fica metade na lixeira e metade fora.
    """
    raiz = Path(raiz)
    caps, ext = [Path(c) for c in capitulos], [Path(e) for e in extras]
    if not caps and not ext:
        return None
    id_ = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    entrada = _pasta(raiz) / id_
    dados = entrada / "dados"
    movidos: List[tuple] = []
    meta = {"id": id_, "quando": time.time(), "tipo": tipo, "obra": obra, "capitulos": [], "extras": [], "bytes": 0}
    try:
        for alvo, lista in ((caps, "capitulos"), (ext, "extras")):
            for origem in alvo:
                rel = _rel(raiz, origem)
                destino = dados / rel
                destino.parent.mkdir(parents=True, exist_ok=True)
                meta["bytes"] += _tamanho(origem) if origem.is_dir() else origem.stat().st_size
                shutil.move(str(origem), str(destino))
                movidos.append((destino, origem))
                meta[lista].append(rel)
        _gravar_meta(entrada, meta)
    except Exception:
        for destino, origem in reversed(movidos):         # desfaz: o conteúdo continua onde estava
            try:
                origem.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(destino), str(origem))
            except OSError:
                pass
        shutil.rmtree(entrada, ignore_errors=True)
        raise
    return id_


def _meta(entrada: Path) -> Optional[Dict[str, Any]]:
    try:
        m = json.loads((entrada / "meta.json").read_text(encoding="utf-8"))
        return m if isinstance(m, dict) and m.get("id") == entrada.name else None
    except (OSError, ValueError):
        return None


def listar(raiz: Path) -> List[Dict[str, Any]]:
    """Entradas da lixeira, a mais recente primeiro, com os dias que faltam para a limpeza automática."""
    base, saida = _pasta(raiz), []
    if not base.is_dir():
        return saida
    agora = time.time()
    for e in base.iterdir():
        m = _meta(e) if e.is_dir() else None
        if m:
            m["dias_restantes"] = max(0, int(DIAS - (agora - m["quando"]) // 86400))
            saida.append(m)
    return sorted(saida, key=lambda m: m["quando"], reverse=True)


def _entrada(raiz: Path, id_: str) -> Path:
    if not id_ or id_ != Path(id_).name or id_.startswith("."):
        raise ErroBaixador("Item da lixeira inválido.")
    entrada = _pasta(raiz) / id_
    if not entrada.is_dir() or not _meta(entrada):
        raise ErroBaixador("Item não encontrado na lixeira.")
    return entrada


def restaurar(raiz: Path, id_: str) -> Dict[str, Any]:
    """Devolve os capítulos ao lugar original. O que já existe no destino NÃO é sobrescrito: fica na lixeira e é listado em `conflitos`."""
    raiz = Path(raiz)
    entrada = _entrada(raiz, id_)
    meta = _meta(entrada) or {}
    dados = entrada / "dados"
    restaurados, conflitos, resto = [], [], []
    for rel in meta.get("capitulos", []):
        origem, destino = dados / rel, raiz / rel
        if not origem.exists():
            continue
        if destino.exists():
            conflitos.append(rel)
            resto.append(rel)
            continue
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(origem), str(destino))
        restaurados.append(rel)
    for rel in meta.get("extras", []):                    # obra.json e capa: só voltam se a obra não tiver os dela
        origem, destino = dados / rel, raiz / rel
        if origem.exists() and not destino.exists():
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(origem), str(destino))
    if resto:
        meta.update(capitulos=resto)
        _gravar_meta(entrada, meta)
    else:
        _apagar_arvore(entrada)
    return {"restaurados": restaurados, "conflitos": conflitos}


def apagar(raiz: Path, id_: str) -> None:
    _apagar_arvore(_entrada(raiz, id_))


def esvaziar(raiz: Path) -> int:
    itens = listar(raiz)
    for m in itens:
        _apagar_arvore(_pasta(raiz) / m["id"])
    return len(itens)


def limpar_vencidos(raiz: Path, agora: Optional[float] = None) -> int:
    """Apaga de vez o que está há mais de `DIAS` dias na lixeira. Pastas sem `meta.json` legível nunca são tocadas."""
    agora = time.time() if agora is None else agora
    n = 0
    for m in listar(raiz):
        if agora - m["quando"] > DIAS * 86400:
            _apagar_arvore(_pasta(raiz) / m["id"])
            n += 1
    return n
