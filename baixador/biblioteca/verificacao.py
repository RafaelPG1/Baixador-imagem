"""Verificação de capítulos novos: só DESCOBRE e mostra. Nunca baixa, traduz, apaga nem altera nada da biblioteca.

Para cada obra lê a página da obra (HTTP direto, sem navegador, com pausa entre pedidos ao mesmo site), tira dela a lista de capítulos
com as mesmas regras do download manual (`capitulos_site`) e compara com o histórico das obras (`historico`):
- "novos"  = capítulos que o site publica e que NÃO estavam no histórico (nem na biblioteca) na verificação anterior. Ficam na lista
             até a pessoa baixá-los ou dispensá-los. Capítulo apagado da biblioteca de propósito já está no histórico: não volta como novo.
- "fora da biblioteca" = tudo que o site publica e a biblioteca não tem agora (inclui os novos).
A primeira verificação de uma obra só cria a base (o que o site já tinha não vira "novidade").

Dados em `dados/verificacao.json`: configuração (periódica, intervalo, obras desligadas), último resultado por obra e histórico das verificações.
Limitação: só funciona em site que entrega a lista de capítulos no HTML da página da obra e aceita acesso sem navegador.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from baixador import configuracao
from baixador.biblioteca import acervo, capa, historico, obra as dados_obra, organizacao
from baixador.navegador import capitulos_site as cs
from baixador.nucleo.erros import ErroBaixador

ARQUIVO = configuracao.DADOS / "verificacao.json"
INTERVALOS_H = (1, 3, 6, 12, 24)
ESPERA_MESMO_SITE_S = 3.0            # pausa entre dois pedidos ao mesmo site
RECENTE_S = 300                      # obra verificada há menos que isso (sem erro) não é pedida de novo, a menos que se force
MAX_HISTORICO = 50
MAX_LISTA = 300                      # capítulos listados por obra (o total real vai no contador)
_TRAVA = threading.RLock()
_EXECUCAO = threading.Lock()         # uma verificação por vez
_andamento: Dict[str, Any] = {"rodando": False}


def _vazio() -> Dict[str, Any]:
    return {"config": {"periodica": False, "intervalo_h": 6, "desligadas": []}, "ultima": 0, "obras": {}, "historico": []}


def ler() -> Dict[str, Any]:
    base = _vazio()
    try:
        d = json.loads(ARQUIVO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return base
    if isinstance(d, dict):
        for k in base:
            if isinstance(d.get(k), type(base[k])):
                base[k] = d[k]
        base["config"] = {**_vazio()["config"], **base["config"]}
    return base


def _gravar(d: Dict[str, Any]) -> None:
    ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
    tmp = ARQUIVO.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, ARQUIVO)                                  # troca atômica: queda no meio não corrompe


def definir_config(periodica: Any = None, intervalo_h: Any = None, desligadas: Any = None) -> Dict[str, Any]:
    with _TRAVA:
        d = ler()
        c = d["config"]
        if isinstance(periodica, bool):
            c["periodica"] = periodica
        if intervalo_h in INTERVALOS_H:
            c["intervalo_h"] = intervalo_h
        if isinstance(desligadas, list):
            c["desligadas"] = sorted({str(n)[:120] for n in desligadas if isinstance(n, str)})[:1000]
        _gravar(d)
        return c


def dispensar(nome: str, numeros: Any = None) -> bool:
    """A pessoa viu os novos e não quer mais o aviso (todos ou só os `numeros`). Não baixa nem apaga nada."""
    with _TRAVA:
        d = ler()
        r = d["obras"].get(nome)
        if not r:
            return False
        quais = {str(n) for n in numeros} if isinstance(numeros, list) else None
        r["novos"] = [c for c in r.get("novos", []) if quais is not None and c["numero"] not in quais]
        _gravar(d)
        return True


def _numeros_da_biblioteca(o: Dict[str, Any]) -> set:
    return {c["numero"] for c in o["capitulos"] if c["numero"] is not None}


def _url_de_amostra(raiz: Path, o: Dict[str, Any], ficha: Optional[Dict[str, Any]]) -> str:
    """Endereço de UM capítulo desta obra: é dele que se descobre como o site escreve os endereços dos capítulos."""
    for u in (ficha or {}).get("conhecidos", {}).values():
        if u and cs.modelo_url(u):
            return u
    for c in o["capitulos"]:
        u = str(organizacao.ler_meta(Path(raiz) / c["rel"], copiar=False).get("url") or "")
        if u and cs.modelo_url(u):
            return u
    return ""


def _item(i: "cs.Item") -> Dict[str, str]:
    return {"numero": i.numero, "url": i.url, "rotulo": i.rotulo}


def _verificar_obra(raiz: Path, o: Dict[str, Any], buscar: Callable[[str, int], bytes], anterior: Dict[str, Any], agora: float) -> Dict[str, Any]:
    pasta = Path(raiz) / (o.get("pasta") or "")
    url = (dados_obra.url_principal(pasta) or dados_obra.url_dos_capitulos(pasta) or "") if o.get("pasta") else ""
    base = {"nome": o["nome"], "t": int(agora * 1000), "url": url, "novos": anterior.get("novos", []), "novos_agora": 0}
    if not url:
        return {**base, "status": "sem_url", "erro": "Não sei o endereço da página desta obra (baixe um capítulo dela pelo programa)."}
    ficha = historico.ficha(o["nome"], url)
    amostra = _url_de_amostra(raiz, o, ficha)
    modelo = cs.modelo_url(amostra) if amostra else None
    if modelo is None:
        return {**base, "status": "sem_lista", "erro": "Não achei um capítulo desta obra com endereço que eu consiga reconhecer."}
    indice = cs.IndiceSite(cs.itens_do_html(buscar(url, capa.LIMITE_PAGINA).decode("utf-8", "replace"), url, modelo), "página da obra", url)
    if not indice.confiavel:
        return {**base, "status": "sem_lista", "erro": "A página da obra não traz a lista de capítulos (site que carrega por script ou exige navegador)."}
    na_biblioteca = _numeros_da_biblioteca(o)
    conhecidos = set((ficha or {}).get("conhecidos", {})) | na_biblioteca
    primeira = not (ficha or {}).get("t_descoberta")
    achados = [i for i in indice.itens if i.numero not in conhecidos] if not primeira else []
    novos = {c["numero"]: c for c in base["novos"] if c["numero"] not in na_biblioteca}
    for i in achados:
        novos[i.numero] = _item(i)
    fora = [_item(i) for i in indice.itens if i.numero not in na_biblioteca]
    historico.registrar_obra(o["nome"], url, encontrado=indice.maior.numero, descoberta=True, conhecidos={i.numero: i.url for i in indice.itens})
    return {**base, "status": "ok", "erro": "", "primeira": primeira, "novos": sorted(novos.values(), key=lambda c: float(c["numero"]))[:MAX_LISTA],
            "novos_agora": len(achados), "total_site": len(indice), "ultimo_site": indice.maior.numero,
            "fora_total": len(fora), "fora": fora[:MAX_LISTA]}


def _bloqueio(erro: Exception) -> bool:
    return any(f"respondeu {c}" in str(erro) for c in (403, 429, 500, 502, 503, 504))


def verificar(raiz: Path, so: Optional[List[str]] = None, forcar: bool = False, buscar: Optional[Callable[[str, int], bytes]] = None,
              espera: float = ESPERA_MESMO_SITE_S, dormir: Callable[[float], None] = time.sleep) -> Dict[str, Any]:
    """Verifica as obras escolhidas (`so`) ou todas as ligadas. Uma por vez; erro de uma obra/site não derruba as outras."""
    if not _EXECUCAO.acquire(blocking=False):
        return {"rodando": True, "mensagem": "Já há uma verificação em andamento."}
    inicio = time.time()
    buscar = buscar or capa.baixar_direto
    try:
        with _TRAVA:
            d = ler()
        desligadas = set(d["config"]["desligadas"])
        obras = [o for o in acervo.listar(Path(raiz))["obras"] if (o["nome"] in so if so is not None else o["nome"] not in desligadas)]
        _andamento.update(rodando=True, feitas=0, total=len(obras), obra="")
        resultados: Dict[str, Dict[str, Any]] = {}
        ultimo_pedido: Dict[str, float] = {}
        bloqueados: set = set()
        for o in obras:
            _andamento.update(obra=o["nome"])
            anterior = d["obras"].get(o["nome"], {})
            host = (o.get("url") or "").split("/")[2] if (o.get("url") or "").count("/") >= 2 else ""
            if not forcar and anterior.get("status") == "ok" and time.time() - anterior.get("t", 0) / 1000 < RECENTE_S:
                resultados[o["nome"]] = {**anterior, "novos_agora": 0}          # verificada agora há pouco: não insiste no site
            elif host in bloqueados:
                resultados[o["nome"]] = {**anterior, "nome": o["nome"], "status": "adiada", "erro": "O site pediu para esperar (limite de acessos); tente mais tarde.", "novos_agora": 0}
            else:
                falta = espera - (time.time() - ultimo_pedido.get(host, 0))
                if host and falta > 0:
                    dormir(falta)
                try:
                    resultados[o["nome"]] = _verificar_obra(Path(raiz), o, buscar, anterior, time.time())
                except Exception as erro:                                       # site fora do ar, bloqueio, página estranha: só esta obra falha
                    if _bloqueio(erro):
                        bloqueados.add(host)
                    resultados[o["nome"]] = {**anterior, "nome": o["nome"], "t": int(time.time() * 1000), "status": "erro", "novos_agora": 0,
                                             "erro": str(erro)[:200] if isinstance(erro, ErroBaixador) else f"Falha ao verificar ({erro.__class__.__name__})."}
                ultimo_pedido[host] = time.time()
            _andamento["feitas"] += 1
        with _TRAVA:
            d = ler()
            d["obras"].update(resultados)
            d["ultima"] = int(time.time() * 1000)
            resumo = {"t": d["ultima"], "verificadas": len(resultados), "com_novos": sum(1 for r in resultados.values() if r.get("novos_agora")),
                      "novos": sum(r.get("novos_agora", 0) for r in resultados.values()), "erros": sum(1 for r in resultados.values() if r["status"] in ("erro", "sem_lista", "sem_url", "adiada")),
                      "segundos": round(time.time() - inicio, 1)}
            resumo["obras"] = [{"nome": n, "novos": r["novos_agora"]} for n, r in resultados.items() if r.get("novos_agora")]
            d["historico"] = ([resumo] + d["historico"])[:MAX_HISTORICO]
            _gravar(d)
        return {"rodando": False, **resumo}
    finally:
        _andamento.update(rodando=False, obra="")
        _EXECUCAO.release()


def painel(raiz: Path) -> Dict[str, Any]:
    """O que a tela mostra: obras da biblioteca com o último resultado, filtrado pelo que a biblioteca tem AGORA (baixou? some da lista)."""
    d = ler()
    desligadas = set(d["config"]["desligadas"])
    saida = []
    for o in acervo.listar(Path(raiz))["obras"]:
        r = d["obras"].get(o["nome"], {})
        tem = _numeros_da_biblioteca(o)
        saida.append({"nome": o["nome"], "ligada": o["nome"] not in desligadas, "status": r.get("status", "nunca"), "t": r.get("t", 0), "erro": r.get("erro", ""),
                      "novos": [c for c in r.get("novos", []) if c["numero"] not in tem], "fora": [c for c in r.get("fora", []) if c["numero"] not in tem],
                      "fora_total": max(0, r.get("fora_total", 0) - len([c for c in r.get("fora", []) if c["numero"] in tem])),
                      "total_site": r.get("total_site", 0), "ultimo_site": r.get("ultimo_site"), "primeira": r.get("primeira", False)})
    saida.sort(key=lambda x: (-len(x["novos"]), x["nome"].lower()))
    return {"config": d["config"], "ultima": d["ultima"], "andamento": dict(_andamento), "obras": saida, "historico": d["historico"]}


_periodico: Dict[str, Any] = {"thread": None, "raiz": None}


def iniciar_periodico(raiz: Path, passo_s: float = 60.0) -> None:
    """Liga (uma vez) o relógio da verificação periódica: de `passo_s` em `passo_s` vê se está ligada e vencida. Sem baixar nem traduzir."""
    _periodico["raiz"] = Path(raiz)
    if _periodico["thread"] is not None:
        return

    def laco() -> None:
        while True:
            time.sleep(passo_s)
            try:
                d = ler()
                if d["config"]["periodica"] and time.time() * 1000 - d["ultima"] >= d["config"]["intervalo_h"] * 3600_000:
                    verificar(_periodico["raiz"])
            except Exception:
                pass                                              # o relógio nunca morre por causa de uma falha

    _periodico["thread"] = threading.Thread(target=laco, daemon=True, name="verificacao-periodica")
    _periodico["thread"].start()
