"""Histórico de leitura do notebook, sincronizável com o celular/app: posição em cada capítulo, capítulos lidos e estado das obras.

Arquivo `dados/historico.json`. Cada item leva o instante da última mudança (`t`, ms): na sincronização, o mais novo vence por item,
então um aparelho com dados velhos nunca sobrescreve o que foi feito depois em outro.
- posicoes: {Obra/Cap: {p: página, n: total de páginas, f: fração da página (0–1), t}}
- lidos:    {Obra/Cap: {v: bool, t}}   (o conjunto de `lidos.json` continua sendo o que a biblioteca consulta)
- estados:  {Obra: {e: "quero"|"lendo"|"concluida"|"", t}}   (estado da OBRA; não confundir com lido/não lido do capítulo)
- obras:    {id: ficha da obra} — histórico das obras, INDEPENDENTE da biblioteca (excluir a obra do disco não toca aqui). Não é sincronizado.
    id (chave do nome, fixa), nome, url (página da obra), site, encontrado/baixado/traduzido/lido (números de capítulo),
    pos {n: capítulo, p: página, t: de páginas, f: fração}, conhecidos {número: url do capítulo},
    t_lido, t_atualizado, t_descoberta (ms), situacao "andamento"|"concluida"|"pausada" (+ t_situacao).
  Regras: números só sobem (encontrado/baixado/traduzido), o mais novo vence (leitura e situação), campo vazio nunca apaga o cheio, e
  terminar de ler os capítulos disponíveis NUNCA muda a situação: só a pessoa marca "concluida" (`definir_situacao`).
  Não confundir com `estados` acima (quero ler/lendo/concluída = a leitura da pessoa, não o andamento da obra no site).
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
SITUACOES = ("andamento", "concluida", "pausada")
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
    return {"posicoes": {}, "lidos": {}, "estados": {}, "obras": {}}


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
    return {"posicoes": d["posicoes"], "lidos": marcas, "estados": d["estados"], "ultima": ultima(d), "obras": {i: _para_sincronia(f) for i, f in d["obras"].items()}}


def mesclar(cliente: Any, resolver: Any = None) -> Dict[str, Any]:
    """Junta o histórico enviado por um aparelho com o do notebook (item a item, o mais novo vence) e devolve o resultado.
    `resolver(rel)` → pasta do capítulo (ou None): com ele, a leitura vinda do aparelho também atualiza a ficha da obra no notebook."""
    cliente = cliente if isinstance(cliente, dict) else {}
    with _TRAVA:
        d = ler()
        mudou = False
        leituras = []                                               # (rel, posição, lido) aceitos agora, para a ficha da obra
        for rel, v in (cliente.get("posicoes") or {}).items() if isinstance(cliente.get("posicoes"), dict) else []:
            novo = _pos(v.get("p"), v.get("n"), v.get("f"), v.get("t")) if isinstance(v, dict) and _rel_ok(rel) else None
            if novo and novo["t"] > d["posicoes"].get(rel, {}).get("t", 0):
                d["posicoes"][rel] = novo
                leituras.append((rel, novo))
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
        fichas = cliente.get("obras")
        for v in fichas.values() if isinstance(fichas, dict) else []:
            mudou = _mesclar_obra(d["obras"], v) or mudou
        if mudou:
            _gravar(d)
        for rel, pos in leituras if callable(resolver) else []:
            try:
                pasta = resolver(rel)
                if pasta:
                    anotar_capitulo(pasta, lido=True, pos={"p": pos["p"], "t": pos["n"], "f": pos["f"]}, t=pos["t"])
            except Exception:
                pass                                                 # a ficha é um extra: a posição já foi salva
    return resumo()


# ---- histórico das obras ------------------------------------------------------------------------------------------------------------

MAX_CONHECIDOS = 5000


def _num(n: Any) -> Optional[str]:
    from baixador.biblioteca import organizacao

    return organizacao.normalizar_numero(n)


def _maior(a: Optional[str], b: Optional[str]) -> Optional[str]:
    return b if a is None or (b is not None and float(b) > float(a)) else a


def _site(url: str) -> str:
    from urllib.parse import urlsplit

    try:
        return (urlsplit(url).hostname or "").removeprefix("www.")
    except ValueError:
        return ""


def _achar_obra(obras: Dict[str, Any], nome: str, url: str) -> Optional[str]:
    """Id da ficha da mesma obra: primeiro pela página da obra, depois pelo nome sem acento/pontuação (o mesmo critério da biblioteca)."""
    from baixador.biblioteca import organizacao

    if url:
        achada = next((i for i, f in obras.items() if f.get("url") == url), None)
        if achada:
            return achada
    chave = organizacao._chave(nome)
    return next((i for i, f in obras.items() if chave and organizacao._chave(f.get("nome", "")) == chave), None)


def registrar_obra(nome: str = "", url: str = "", *, encontrado: Any = None, baixado: Any = None, traduzido: Any = None, lido: Any = None,
                   pos: Optional[Dict[str, Any]] = None, conhecidos: Optional[Dict[str, str]] = None, descoberta: bool = False, t: Any = None) -> bool:
    """Cria ou completa a ficha da obra. Nunca apaga nem rebaixa nada: ver as regras no topo do arquivo. True se gravou."""
    from baixador.biblioteca import capa, organizacao

    url = (capa.url_da_obra(url) or "") if url else ""
    nome_url = organizacao._titulo_de_slug(url.rstrip("/").rsplit("/", 1)[-1]) if url else ""
    nome = organizacao.limpar_nome(nome, 80) if nome else ""
    if not (nome or nome_url):
        return False
    agora = _t(t) or _agora()
    with _TRAVA:
        d = ler()
        obras = d["obras"]
        id_ = _achar_obra(obras, nome or nome_url, url)
        antes = json.dumps(obras.get(id_), sort_keys=True) if id_ else ""
        if id_ is None:
            id_ = organizacao._chave(nome or nome_url) or _site(url) or "obra"
            while id_ in obras:                                 # id já usado por outra obra: nunca sobrescreve a ficha
                id_ += "-2"
            obras[id_] = {"id": id_, "nome": nome or nome_url, "nome_auto": not nome, "url": "", "site": "", "situacao": "andamento", "conhecidos": {}}
        f = obras[id_]
        if nome and (not f.get("nome") or f.get("nome_auto")):
            f["nome"], f["nome_auto"] = nome, False             # o nome tirado do endereço cede ao nome de verdade
        if url and not f.get("url"):
            f["url"], f["site"] = url, _site(url)
        for campo, valor in (("encontrado", encontrado), ("baixado", baixado), ("traduzido", traduzido)):
            n = _num(valor)
            if n is not None:
                f[campo] = _maior(_num(f.get(campo)), n)
        if isinstance(conhecidos, dict):
            c = f.setdefault("conhecidos", {})
            for k, v in conhecidos.items():
                k = _num(k)
                if k is not None and (len(c) < MAX_CONHECIDOS or k in c) and (k not in c or (not c[k] and v)):
                    c[k] = str(v or "")[:300]
        n = _num(lido)
        if n is not None and agora >= f.get("t_lido", 0):        # leitura: o mais novo vence (reler um capítulo antigo é leitura mais nova)
            f["lido"], f["t_lido"] = n, agora
            if isinstance(pos, dict) and _pos(pos.get("p"), pos.get("t"), pos.get("f"), agora):
                f["pos"] = {"n": n, "p": int(pos["p"]), "t": int(pos["t"]), "f": round(float(pos["f"]), 3)}
            elif f.get("pos", {}).get("n") != n:
                f.pop("pos", None)
        if descoberta:
            f["t_descoberta"] = agora
        if json.dumps(f, sort_keys=True) != antes:
            f["t_atualizado"] = max(f.get("t_atualizado", 0), agora)
            _gravar(d)
            return True
        return False


def ficha(nome: str, url: str = "") -> Optional[Dict[str, Any]]:
    """Ficha da obra (cópia) pelo endereço ou pelo nome; None se ainda não existe."""
    obras = ler()["obras"]
    id_ = _achar_obra(obras, nome, url)
    return dict(obras[id_]) if id_ else None


def definir_situacao(obra: str, situacao: str, t: Any = None) -> bool:
    """Marca a obra como andamento/concluída/pausada (decisão da pessoa; nada é deduzido da leitura). `obra` = nome ou id."""
    if situacao not in SITUACOES or not isinstance(obra, str):
        return False
    with _TRAVA:
        d = ler()
        id_ = obra if obra in d["obras"] else _achar_obra(d["obras"], obra, "")
        agora = _t(t) or _agora()
        if id_ is None or agora < d["obras"][id_].get("t_situacao", 0) or d["obras"][id_].get("situacao") == situacao:
            return False
        d["obras"][id_].update(situacao=situacao, t_situacao=agora, t_atualizado=max(d["obras"][id_].get("t_atualizado", 0), agora))
        _gravar(d)
        return True


def obras() -> list:
    """Fichas das obras, as lidas há menos tempo primeiro."""
    return sorted(ler()["obras"].values(), key=lambda f: -max(f.get("t_lido", 0), f.get("t_atualizado", 0)))


def da_pasta(pasta: Path) -> Optional[Dict[str, Any]]:
    """(nome, número, url do capítulo, url da obra) de uma pasta de capítulo da biblioteca; None se não der para saber a obra."""
    from baixador.biblioteca import capa, obra as dados_obra, organizacao

    pasta = Path(pasta)
    c = organizacao.descrever_capitulo(pasta, pasta.parent.name)
    if not c["obra"]:
        return None
    url_cap = str(organizacao.ler_meta(pasta, copiar=False).get("url") or "")
    return {"nome": c["obra"], "numero": c["numero"], "url_cap": url_cap, "url": dados_obra.url_principal(pasta.parent) or capa.url_da_obra(url_cap) or ""}


def anotar_capitulo(pasta: Path, **campos: Any) -> bool:
    """Ponte para quem só tem a pasta do capítulo (download, tradução, leitura): `baixado=True`, `traduzido=True` ou `lido=True` (+ `pos`, `t`)."""
    try:
        c = da_pasta(pasta)
        if c is None or c["numero"] is None:
            return False
        extra = {k: c["numero"] for k in ("baixado", "traduzido", "lido") if campos.pop(k, False)}
        conhecidos = {c["numero"]: c["url_cap"]}
        return registrar_obra(c["nome"], c["url"], conhecidos=conhecidos, **extra, **campos)
    except Exception:
        return False                                              # o histórico é um extra: nunca atrapalha baixar, traduzir ou ler


def sincronizar_biblioteca(raiz: Path) -> int:
    """Passa para o histórico o que a biblioteca já tem (obras de antes deste recurso, pastas copiadas de fora). Só acrescenta. Devolve quantas fichas mudaram."""
    from baixador.biblioteca import acervo

    mudou = 0
    posicoes = ler()["posicoes"]
    for o in acervo.listar(Path(raiz))["obras"]:
        caps = [c for c in o["capitulos"] if c["numero"] is not None]
        feitos = lambda campo: max((c["numero"] for c in caps if c[campo]), key=float, default=None)   # noqa: E731
        baixados = [c["numero"] for c in caps if not c["baixa_incompleta"] and not c["incompleta"]]
        lida = max((c for c in caps if c["rel"] in posicoes), key=lambda c: posicoes[c["rel"]].get("t", 0), default=None)
        extra: Dict[str, Any] = {}
        if lida:
            v = posicoes[lida["rel"]]
            extra = {"lido": lida["numero"], "pos": {"p": v.get("p"), "t": v.get("n"), "f": v.get("f")}, "t": v.get("t")}
        mudou += registrar_obra(o["nome"], o.get("url") or "", baixado=max(baixados, key=float, default=None), traduzido=feitos("traduzido"),
                                conhecidos={c["numero"]: "" for c in caps}, **extra)
    return mudou


# ---- sincronia da ficha das obras ---------------------------------------------------------------------------------------------------

def _para_sincronia(f: Dict[str, Any]) -> Dict[str, Any]:
    """Ficha como vai pela rede: `conhecidos` vira texto compacto de faixas ("1-120,121.5"), sem as URLs (o notebook já as tem)."""
    nums = sorted(f.get("conhecidos", {}), key=float)
    ints = sorted(int(n) for n in nums if n.isdigit())
    faixas, i = [], 0
    while i < len(ints):
        j = i
        while j + 1 < len(ints) and ints[j + 1] == ints[j] + 1:
            j += 1
        faixas.append(str(ints[i]) if i == j else f"{ints[i]}-{ints[j]}")
        i = j + 1
    return {**f, "conhecidos": ",".join(faixas + [n for n in nums if not n.isdigit()])}


def _de_faixas(texto: Any) -> list:
    saida: list = []
    for parte in str(texto or "").split(",")[:MAX_CONHECIDOS]:
        a, _, b = parte.strip().partition("-")
        if b.isdigit() and a.isdigit() and 0 <= int(b) - int(a) < MAX_CONHECIDOS:
            saida += range(int(a), int(b) + 1)
        elif _num(parte.strip()) is not None:
            saida.append(parte.strip())
    return [n for n in map(_num, saida) if n is not None][:MAX_CONHECIDOS]


def _mesclar_obra(obras: Dict[str, Any], v: Any) -> bool:
    """Junta a ficha de um aparelho com a do notebook, campo a campo e SEM apagar nada: números só sobem, o mais novo vence (leitura, situação),
    conhecidos se somam, campo vazio nunca apaga o cheio. Idempotente: receber de volta o que acabou de mandar não muda nada (sem ciclos).
    Só lê os campos conhecidos (e valida cada um): lixo na rede não vira dado."""
    from baixador.biblioteca import capa, organizacao

    if not isinstance(v, dict):
        return False
    url = (capa.url_da_obra(str(v.get("url") or "")) or "")
    nome = organizacao.limpar_nome(str(v.get("nome") or ""), 80)
    auto = bool(v.get("nome_auto"))
    if not (nome or url):
        return False
    id_ = _achar_obra(obras, nome, url)
    novo = id_ is None
    if novo:
        id_ = organizacao._chave(nome) or _site(url) or "obra"
        while id_ in obras:
            id_ += "-2"
        obras[id_] = {"id": id_, "nome": nome or organizacao._titulo_de_slug(url.rstrip("/").rsplit("/", 1)[-1]), "nome_auto": auto or not nome,
                      "url": "", "site": "", "situacao": "andamento", "conhecidos": {}}
    f = obras[id_]
    antes = json.dumps(f, sort_keys=True)
    if nome and (not f.get("nome") or (f.get("nome_auto") and not auto)):
        f["nome"], f["nome_auto"] = nome, auto
    if url and not f.get("url"):
        f["url"], f["site"] = url, _site(url)
    for campo in ("encontrado", "baixado", "traduzido"):
        n = _num(v.get(campo))
        if n is not None:
            f[campo] = _maior(_num(f.get(campo)), n)
    c = f.setdefault("conhecidos", {})
    for n in _de_faixas(v.get("conhecidos")):
        if n not in c and len(c) < MAX_CONHECIDOS:
            c[n] = ""
    tl, lido = _t(v.get("t_lido")), _num(v.get("lido"))
    if lido is not None and tl > f.get("t_lido", 0):
        f["lido"], f["t_lido"] = lido, tl
        p = v.get("pos") if isinstance(v.get("pos"), dict) else {}
        if _num(p.get("n")) == lido and _pos(p.get("p"), p.get("t"), p.get("f"), tl):
            f["pos"] = {"n": lido, "p": int(p["p"]), "t": int(p["t"]), "f": round(float(p["f"]), 3)}
        else:
            f.pop("pos", None)
    for campo in ("t_descoberta", "t_atualizado"):
        if _t(v.get(campo)) > f.get(campo, 0):
            f[campo] = _t(v.get(campo))
    ts = _t(v.get("t_situacao"))
    if v.get("situacao") in SITUACOES and ts > f.get("t_situacao", 0):
        f["situacao"], f["t_situacao"] = v["situacao"], ts
    return novo or json.dumps(f, sort_keys=True) != antes
