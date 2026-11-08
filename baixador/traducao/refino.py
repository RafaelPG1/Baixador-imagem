"""Refinamento em segundo plano (modo híbrido): o Hy-MT2 reescreve, balão a balão, a tradução rápida do Argos que já está no leitor.

Regras de segurança (nada aqui pode piorar o que já existe):
- só troca por resposta validada, não vazia, que não seja cópia do original; qualquer problema = a tradução atual fica;
- troca "compare-and-set" sob a trava do traducao.json: se o usuário editou o balão (ou ele veio da memória de correções)
  enquanto o Hy trabalhava, o texto do usuário vence e a resposta do Hy é descartada;
- a posição, o tamanho e o balão em si não são tocados: só o texto traduzido (o leitor reencaixa as linhas sozinho);
- o texto original (`original`) nunca é alterado; cancelar interrompe na hora, inclusive no meio de uma fala.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from baixador.nucleo.erros import Cancelado
from baixador.traducao import inteligencia as ia
from baixador.traducao.hymt import IndisponivelHy, RespostaInvalida, TradutorHy
from baixador.traducao.ocr_texto import dividir_traducao
from baixador.traducao.trava import TRAVA_JSON

NOME = "traducao.json"
ATIVOS = ("pendente", "refinando")


def _ler(pasta: Path) -> Optional[Dict[str, Any]]:
    try:
        dados = json.loads((Path(pasta) / NOME).read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) and isinstance(dados.get("imagens"), dict) else None
    except (OSError, ValueError):
        return None


def _escrever(pasta: Path, dados: Dict[str, Any]) -> None:
    arquivo = Path(pasta) / NOME
    temporario = arquivo.with_name(arquivo.name + ".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temporario, arquivo)


def estado(pasta: Path) -> str:
    with TRAVA_JSON:
        d = _ler(pasta)
    r = d.get("refino") if d else None
    return r.get("estado", "") if isinstance(r, dict) else ""


def marcar(pasta: Path, novo: str, so_se: Tuple[str, ...] = (), **extra: Any) -> None:
    """Grava `refino.estado` (e campos extras). `so_se`: só muda se o estado atual for um destes (vazio = sempre)."""
    try:
        with TRAVA_JSON:
            d = _ler(pasta)
            if d is None:
                return
            r = d.get("refino") if isinstance(d.get("refino"), dict) else {}
            if so_se and r.get("estado") not in so_se:
                return
            r.update({"estado": novo, "ts": int(time.time()), **extra})
            d["refino"] = r
            _escrever(pasta, d)
    except OSError:
        pass


def _eleger(d: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Grupos de balões que ainda valem refinar (todos os membros: tradução do Argos, não editada nem da memória)."""
    grupos: Dict[Tuple[str, Any], Dict[str, Any]] = {}
    ordem: List[Tuple[str, Any]] = []
    for nome, info in d["imagens"].items():
        blocos = info.get("blocos") if isinstance(info, dict) else None
        if not isinstance(blocos, list):
            continue
        for i, b in enumerate(blocos):
            if not isinstance(b, dict):
                continue
            g = b.get("grupo")
            chave = (nome, g if isinstance(g, int) and g >= 0 else f"s{i}")
            if chave not in grupos:
                grupos[chave] = {"img": nome, "idx": [], "orig": [], "arg": [], "ok": True}
                ordem.append(chave)
            gr = grupos[chave]
            gr["idx"].append(i)
            gr["orig"].append(str(b.get("original", "")))
            gr["arg"].append(str(b.get("traduzido", "")))
            if b.get("manual") or b.get("origem_tr") in ("memoria", "hy", "gemini", "openrouter") or not b.get("traduzido") or not b.get("original"):
                gr["ok"] = False
    return [grupos[c] for c in ordem if grupos[c]["ok"]]


def pendentes(pasta: Path) -> int:
    """Quantas falas/frases do capítulo (traduzido pelo Argos) ainda podem ser refinadas. 0 = nada a fazer."""
    with TRAVA_JSON:
        d = _ler(pasta)
    return len(_eleger(d)) if d else 0


def _aplicar(pasta: Path, gr: Dict[str, Any], partes: List[str], original: str, final: str, de: str, para: str) -> bool:
    """Troca por compare-and-set. False = alguém mexeu no balão no meio do caminho (nada é gravado)."""
    with TRAVA_JSON:
        d = _ler(pasta)
        if d is None:
            return False
        info = d["imagens"].get(gr["img"])
        blocos = info.get("blocos") if isinstance(info, dict) else None
        if not isinstance(blocos, list) or max(gr["idx"]) >= len(blocos):
            return False
        for i, o, a in zip(gr["idx"], gr["orig"], gr["arg"]):
            b = blocos[i]
            if (not isinstance(b, dict) or b.get("manual") or b.get("origem_tr") in ("memoria", "hy", "gemini", "openrouter")
                    or b.get("original") != o or b.get("traduzido") != a):
                return False
        conf = min(float(blocos[i].get("confianca", 1.0)) for i in gr["idx"])
        for k, (i, parte) in enumerate(zip(gr["idx"], partes)):
            blocos[i]["traduzido"] = parte
            blocos[i]["origem_tr"] = "hy"
            blocos[i]["alertas"] = ia.revisar(original, final, de, para, conf) if k == 0 else []
        r = d.get("refino") if isinstance(d.get("refino"), dict) else {}
        r.update({"estado": "refinando", "ts": int(time.time())})
        d["refino"] = r
        _escrever(pasta, d)
        return True


def refinar_pasta(
    pasta: Path, hy: TradutorHy, de: str = "en", para: str = "pt", parar: Optional[threading.Event] = None,
    informar: Callable[[str], None] = lambda _m: None, progresso: Callable[[int, int], None] = lambda _a, _b: None,
) -> Dict[str, int]:
    """Refina o capítulo com o Hy-MT2. Levanta Cancelado (estado fica `cancelado`) ou IndisponivelHy (estado `indisponivel`)."""
    from baixador.traducao.pipeline import _quase_igual

    pasta = Path(pasta)
    with TRAVA_JSON:
        d = _ler(pasta)
    if d is None:
        return {"refinados": 0, "mantidos": 0, "total": 0}
    grupos = _eleger(d)
    r = {"refinados": 0, "mantidos": 0, "total": len(grupos)}
    if not grupos:
        marcar(pasta, "concluido", feitas=0, total=0)
        return r
    ctx = ia.contexto_da_pasta(pasta, de, para)
    ctx.anteriores = []                                                   # sem contexto longo: só a fala (e o glossário, se aparecer nela)
    ctx.memoria = {}
    marcar(pasta, "refinando", feitas=0, total=len(grupos))
    progresso(0, len(grupos))
    try:
        for n, gr in enumerate(grupos, 1):
            if parar is not None and parar.is_set():
                raise Cancelado("Refinamento cancelado.")
            original = " ".join(gr["orig"])
            try:
                final = ia.refinar(original, hy.traduzir_uma(original, ctx), ctx)
            except RespostaInvalida:
                r["mantidos"] += 1
                progresso(n, len(grupos))
                continue
            pesos = [max(1, len(o.split())) for o in gr["orig"]]
            partes = dividir_traducao(final, pesos) if len(pesos) > 1 else [final]
            if (not final.strip() or any(not p.strip() for p in partes) or _quase_igual(final, original)
                    or [p for p in partes] == gr["arg"]):
                r["mantidos"] += 1
            elif _aplicar(pasta, gr, partes, original, final, de, para):
                r["refinados"] += 1
            else:
                r["mantidos"] += 1
            progresso(n, len(grupos))
            if n % 5 == 0:
                marcar(pasta, "refinando", so_se=ATIVOS, feitas=n, total=len(grupos))
    except Cancelado:
        marcar(pasta, "cancelado", so_se=ATIVOS, **r)
        raise
    except IndisponivelHy:
        marcar(pasta, "indisponivel", so_se=ATIVOS, **r)
        raise
    except BaseException:
        marcar(pasta, "falhou", so_se=ATIVOS, **r)
        raise
    marcar(pasta, "concluido", so_se=ATIVOS, **r)
    informar(f"{pasta.name}: {r['refinados']} balão(ões)/frase(s) refinado(s) pelo Hy-MT2, {r['mantidos']} mantido(s) como estava.")
    return r
