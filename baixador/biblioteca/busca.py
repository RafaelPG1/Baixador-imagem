"""Pesquisa no texto traduzido (SQLite FTS5, local, sem dependências). Índice em `dados/busca.db`; os `traducao.json` nunca são alterados.

O índice é incremental: cada capítulo guarda (mtime, tamanho) do `traducao.json` quando foi indexado. `sincronizar` só relê os que
mudaram (importação, correção, edição) e remove os que sumiram (exclusão/lixeira). Pesquisar não reconstrói nada: só confere esses carimbos.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from baixador import configuracao

ARQUIVO = configuracao.DADOS / "busca.db"
_TRAVA = threading.RLock()
_ESQUEMA = """
CREATE TABLE IF NOT EXISTS capitulos (rel TEXT PRIMARY KEY, carimbo TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS falas USING fts5(texto, rel UNINDEXED, obra UNINDEXED, pagina UNINDEXED, fid UNINDEXED, tokenize='unicode61 remove_diacritics 2');
"""


def todos(raiz: Path) -> List[Dict[str, Any]]:
    from baixador.biblioteca import acervo
    return [{**c, "pasta": Path(raiz) / c["rel"], "obra": o["nome"]} for o in acervo.listar(Path(raiz))["obras"] for c in o["capitulos"]]


def _abrir() -> sqlite3.Connection:
    ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(ARQUIVO), timeout=10)
    con.executescript(_ESQUEMA)
    return con


def _carimbo(arq: Path) -> str:
    st = arq.stat()
    return f"{st.st_mtime_ns}:{st.st_size}"


def _falas(arq: Path):
    try:
        d = json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for p in d.get("pages", []) if isinstance(d, dict) else []:
        for u in p.get("units", []):
            t = u.get("translation")
            if isinstance(t, str) and t.strip() and u.get("status") != "copiado":
                yield p.get("number") or 1, str(u.get("id", "")), t


def sincronizar(raiz: Path, capitulos: List[Dict[str, Any]]) -> Dict[str, int]:
    """Atualiza o índice só do que mudou. `capitulos`: itens da biblioteca (rel, obra, pasta, traduzido)."""
    atuais = {c["rel"]: c for c in capitulos if c.get("traduzido") and (Path(c["pasta"]) / "traducao.json").is_file()}
    novos = alterados = removidos = 0
    with _TRAVA, _abrir() as con:
        guardados = dict(con.execute("SELECT rel, carimbo FROM capitulos"))
        for rel in set(guardados) - set(atuais):
            con.execute("DELETE FROM falas WHERE rel = ?", (rel,))
            con.execute("DELETE FROM capitulos WHERE rel = ?", (rel,))
            removidos += 1
        for rel, c in atuais.items():
            arq = Path(c["pasta"]) / "traducao.json"
            try:
                carimbo = _carimbo(arq)
            except OSError:
                continue
            if guardados.get(rel) == carimbo:
                continue
            con.execute("DELETE FROM falas WHERE rel = ?", (rel,))
            con.executemany("INSERT INTO falas(texto, rel, obra, pagina, fid) VALUES (?,?,?,?,?)", [(t, rel, c["obra"], pg, fid) for pg, fid, t in _falas(arq)])
            con.execute("INSERT OR REPLACE INTO capitulos(rel, carimbo) VALUES (?,?)", (rel, carimbo))
            alterados += 1 if rel in guardados else 0
            novos += 0 if rel in guardados else 1
    return {"novos": novos, "alterados": alterados, "removidos": removidos}


def _consulta(q: str) -> Optional[str]:
    palavras = re.findall(r"\w+", q, flags=re.UNICODE)[:12]
    if not palavras:
        return None
    return " ".join(f'"{p}"' for p in palavras[:-1]) + (" " if len(palavras) > 1 else "") + f'"{palavras[-1]}"*'   # a última palavra vale como prefixo


def pesquisar(q: str, obra: Optional[str] = None, limite: int = 50) -> List[Dict[str, Any]]:
    expr = _consulta(q or "")
    if not expr:
        return []
    sql = "SELECT rel, obra, pagina, fid, snippet(falas, 0, '[', ']', '…', 12) FROM falas WHERE falas MATCH ?"
    args: List[Any] = [expr]
    if obra:
        sql += " AND obra = ?"
        args.append(obra)
    sql += " ORDER BY rank LIMIT ?"
    args.append(max(1, min(int(limite), 200)))
    with _TRAVA, _abrir() as con:
        return [{"rel": r, "obra": o, "pagina": int(p), "id": f, "trecho": s} for r, o, p, f, s in con.execute(sql, args)]
