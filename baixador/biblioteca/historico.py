"""Histórico de leitura do notebook, sincronizável com o celular/app: posição em cada capítulo, capítulos lidos e estado das obras.

Arquivo `dados/historico.json`. Cada item leva o instante da última mudança (`t`, ms): na sincronização, o mais novo vence por item,
então um aparelho com dados velhos nunca sobrescreve o que foi feito depois em outro.
- posicoes: {Obra/Cap: {p: página, n: total de páginas, f: fração da página (0–1), t}}
- lidos:    {Obra/Cap: {v: bool, t}}   (o conjunto de `lidos.json` continua sendo o que a biblioteca consulta)
- estados:  {Obra: {e: "quero"|"lendo"|"concluida"|"", t}}   (estado da OBRA; não confundir com lido/não lido do capítulo)
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from baixador import configuracao
from baixador.biblioteca import lidos

ARQUIVO = configuracao.DADOS / "historico.json"
ESTADOS = ("", "quero", "lendo", "concluida")
MAX_POSICOES = 2000
_TRAVA = threading.RLock()


def _agora() -> int:
    return int(time.time() * 1000)


def _t(v: Any) -> int:
    """Instante válido (ms). Futuro distante é cortado: um relógio errado não pode travar o item para sempre."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 0
    return max(0, min(n, _agora() + 86_400_000))


def _rel_ok(rel: Any) -> bool:
    return isinstance(rel, str) and 0 < len(rel) <= 300 and ".." not in rel.split("/") and not rel.startswith(("/", "."))


def _vazio() -> Dict[str, Dict[str, Any]]:
    return {"posicoes": {}, "lidos": {}, "estados": {}}


def ler() -> Dict[str, Dict[str, Any]]:
    try:
        d = json.loads(ARQUIVO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _vazio()
    base = _vazio()
    if isinstance(d, dict):
        for k in base:
            if isinstance(d.get(k), dict):
                base[k] = d[k]
    return base


def _gravar(d: Dict[str, Dict[str, Any]]) -> None:
    if len(d["posicoes"]) > MAX_POSICOES:                       # guarda as mais recentes
        for rel, _ in sorted(d["posicoes"].items(), key=lambda kv: kv[1].get("t", 0))[: len(d["posicoes"]) - MAX_POSICOES]:
            del d["posicoes"][rel]
    ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
    tmp = ARQUIVO.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, ARQUIVO)


def _pos(p: Any, n: Any, f: Any, t: Any) -> Optional[Dict[str, Any]]:
    try:
        p, n, f = int(p), int(n), float(f)
    except (TypeError, ValueError):
        return None
    if not (1 <= p <= n <= 5000) or not 0 <= f <= 1:
        return None
    return {"p": p, "n": n, "f": round(f, 3), "t": _t(t) or _agora()}


def salvar_posicao(rel: str, p: Any, n: Any, f: Any, t: Any = None) -> bool:
    """True se gravou. Só grava se for mais novo que o guardado e se mudou de verdade (poupa disco: a leitura manda posições o tempo todo)."""
    novo = _pos(p, n, f, t)
    if not _rel_ok(rel) or novo is None:
        return False
    with _TRAVA:
        d = ler()
        antigo = d["posicoes"].get(rel)
        if antigo and (antigo.get("t", 0) >= novo["t"] or (antigo.get("p") == novo["p"] and abs(antigo.get("f", 0) - novo["f"]) < 0.01 and antigo.get("n") == novo["n"])):
            return False
        d["posicoes"][rel] = novo
        _gravar(d)
        return True


def marcar_lido(rel: str, lido: bool, t: Any = None) -> None:
    """Registra QUANDO um capítulo foi marcado/desmarcado (o conjunto em si fica em lidos.json)."""
    if not _rel_ok(rel):
        return
    with _TRAVA:
        d = ler()
        d["lidos"][rel] = {"v": bool(lido), "t": _t(t) or _agora()}
        _gravar(d)


def definir_estado(obra: str, estado: str, t: Any = None) -> bool:
    if not (isinstance(obra, str) and 0 < len(obra) <= 200 and "/" not in obra and not obra.startswith(".")) or estado not in ESTADOS:
        return False
    with _TRAVA:
        d = ler()
        if d["estados"].get(obra, {}).get("e", "") == estado:
            return False
        d["estados"][obra] = {"e": estado, "t": _t(t) or _agora()}
        _gravar(d)
        return True


def ultima(d: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Capítulo em que a pessoa parou por último (posição mais recente que ainda não chegou ao fim)."""
    d = d or ler()
    abertas = [(rel, v) for rel, v in d["posicoes"].items() if isinstance(v, dict) and v.get("p", 0) < v.get("n", 0)]
    if not abertas:
        return None
    rel, v = max(abertas, key=lambda kv: kv[1].get("t", 0))
    return {"rel": rel, **v}


def resumo() -> Dict[str, Any]:
    d = ler()
    lidos_atuais = lidos.todos()
    marcas = {rel: {"v": rel in lidos_atuais, "t": d["lidos"].get(rel, {}).get("t", 0)} for rel in set(lidos_atuais) | set(d["lidos"])}
    return {"posicoes": d["posicoes"], "lidos": marcas, "estados": d["estados"], "ultima": ultima(d)}


def mesclar(cliente: Any) -> Dict[str, Any]:
    """Junta o histórico enviado por um aparelho com o do notebook (item a item, o mais novo vence) e devolve o resultado."""
    cliente = cliente if isinstance(cliente, dict) else {}
    with _TRAVA:
        d = ler()
        mudou = False
        for rel, v in (cliente.get("posicoes") or {}).items() if isinstance(cliente.get("posicoes"), dict) else []:
            novo = _pos(v.get("p"), v.get("n"), v.get("f"), v.get("t")) if isinstance(v, dict) and _rel_ok(rel) else None
            if novo and novo["t"] > d["posicoes"].get(rel, {}).get("t", 0):
                d["posicoes"][rel] = novo
                mudou = True
        atuais = lidos.todos()
        for rel, v in (cliente.get("lidos") or {}).items() if isinstance(cliente.get("lidos"), dict) else []:
            if not (isinstance(v, dict) and _rel_ok(rel)) or not _t(v.get("t")):
                continue
            t, lido = _t(v.get("t")), bool(v.get("v"))
            if t > d["lidos"].get(rel, {}).get("t", 0):
                d["lidos"][rel] = {"v": lido, "t": t}
                if (rel in atuais) != lido:
                    lidos.marcar(rel, lido)
                mudou = True
        for obra, v in (cliente.get("estados") or {}).items() if isinstance(cliente.get("estados"), dict) else []:
            if isinstance(v, dict) and v.get("e") in ESTADOS and _t(v.get("t")) > d["estados"].get(obra, {}).get("t", 0) and "/" not in str(obra) and 0 < len(str(obra)) <= 200:
                d["estados"][obra] = {"e": v["e"], "t": _t(v.get("t"))}
                mudou = True
        if mudou:
            _gravar(d)
    return resumo()
