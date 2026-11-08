"""Edição de trechos já traduzidos: retraduzir um bloco, corrigir o texto, remover ou reler uma área.

Mexe só em `traducao.json` da pasta do conjunto ; as imagens nunca são alteradas.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List

from baixador.traducao import inteligencia as ia
from baixador.biblioteca.acervo import esquecer_versao
from baixador.biblioteca.capitulo import NOME_TRADUCAO, listar_imagens, pasta_imagens
from baixador.traducao.pipeline import (
    IDIOMAS_DESTINO, IDIOMAS_ORIGEM, MAX_BLOCOS_POR_IMAGEM, MAX_TEXTO_BLOCO, ErroTraducao, carregar_imagem,
    cor_do_fundo, processar_imagem, traduzir_area, Bloco,
)

from baixador.traducao.trava import TRAVA_JSON as _TRAVA
_COR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _carregar(pasta: Path, de: str, para: str) -> Dict[str, Any]:
    arquivo = pasta / NOME_TRADUCAO
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        if not isinstance(dados, dict) or not isinstance(dados.get("imagens"), dict):
            raise ValueError
    except FileNotFoundError:
        dados = {"versao": 1, "de": de, "para": para, "imagens": {}}
    except (OSError, ValueError):
        raise ErroTraducao("O arquivo traducao.json está ilegível.") from None
    if dados.get("de") not in IDIOMAS_ORIGEM or dados.get("para") not in IDIOMAS_DESTINO:
        dados["de"], dados["para"] = de, para
    return dados


def _gravar(pasta: Path, dados: Dict[str, Any]) -> None:
    arquivo = pasta / NOME_TRADUCAO
    temporario = arquivo.with_suffix(".tmp")
    try:
        temporario.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(temporario, arquivo)
    except OSError as erro:
        raise ErroTraducao(f"Não foi possível gravar a tradução: {erro}") from None
    esquecer_versao()                       # o leitor lê o traducao.json na hora; a biblioteca só precisa notar a mudança


def _numero(valor: Any, nome: str) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or valor != valor or abs(valor) > 1e6:
        raise ErroTraducao(f"Valor inválido: {nome}.")
    return float(valor)


def _texto(valor: Any, vazio_ok: bool = False) -> str:
    if not isinstance(valor, str):
        raise ErroTraducao("Texto inválido.")
    texto = " ".join(valor.split())[:MAX_TEXTO_BLOCO]
    if not texto and not vazio_ok:
        raise ErroTraducao("O texto não pode ficar vazio.")
    return texto


def _imagem(pasta: Path, nome: Any) -> str:
    if not isinstance(nome, str) or nome not in listar_imagens(pasta):
        raise ErroTraducao("Imagem desconhecida.")
    return nome


def _info(dados: Dict[str, Any], pasta: Path, nome: str, criar: bool = False) -> Dict[str, Any]:
    info = dados["imagens"].get(nome)
    if isinstance(info, dict) and isinstance(info.get("blocos"), list):
        return info
    if not criar:
        raise ErroTraducao("Essa imagem ainda não tem tradução.")
    imagem = carregar_imagem(pasta_imagens(pasta) / nome)
    info = {"w": int(imagem.shape[1]), "h": int(imagem.shape[0]), "blocos": []}
    dados["imagens"][nome] = info
    return info


def _indice(info: Dict[str, Any], indice: Any) -> int:
    if isinstance(indice, bool) or not isinstance(indice, int) or not 0 <= indice < len(info["blocos"]):
        raise ErroTraducao("Trecho desconhecido (a página mudou?). Recarregue o leitor.")
    return indice


def _aprender(pasta: Path, original: str, antes: str, depois: str, motor_traducao: Any) -> None:
    """Aprende termos da correção; qualquer falha aqui nunca atrapalha o salvamento do usuário."""
    def palavra(w: str) -> str:
        return motor_traducao().traduzir_pagina([w], None)[0]
    try:
        ia.aprender_correcao(pasta, original, antes, depois, palavra)
    except Exception:
        pass


def _traduzir_texto(motor_argos: Any, original: str, ctx: ia.Contexto) -> str:
    """"Traduzir de novo" respeita o motor escolhido: Hy-MT2 (somente Hy) quando disponível; senão, o Argos."""
    from baixador.traducao import config, hymt

    if config.motor() == "hy" and hymt.verificar()["pronto"]:
        try:
            return hymt.TradutorHy(ctx.de, ctx.para).traduzir_uma(original, ctx)
        except (hymt.IndisponivelHy, hymt.RespostaInvalida):
            pass                                              # cai para o Argos em vez de falhar a edição
    return motor_argos().traduzir_pagina([ia.corrigir_ocr(original, ctx.nomes, ctx.de)], ctx)[0]


def reajustar_pasta(pasta: Path) -> Dict[str, int]:
    """Recalcula caixa, fundo e cor da letra de todos os trechos já traduzidos, SEM ler nem traduzir de novo.

    Serve para capítulos feitos por versões antigas: usa o texto e a tradução já gravados e refaz só o
    desenho (respeitar o balão, cobrir texto solto, copiar a cor da letra).
    """
    from baixador.traducao.pipeline import Bloco, ajustar_ao_balao, separar_sobrepostos

    pasta = Path(pasta)
    with _TRAVA:
        dados = _carregar(pasta, "en", "pt")
        mudados = imagens = 0
        for nome in listar_imagens(pasta):
            info = dados["imagens"].get(nome)
            if not isinstance(info, dict) or not info.get("blocos"):
                continue
            imagem = carregar_imagem(pasta_imagens(pasta) / nome)
            imagens += 1
            pares: List[Any] = []                              # (dict gravado, Bloco recalculável)
            fixas: List[Any] = []                              # caixas que não mudam (manuais): só servem de vizinhas
            for b in info["blocos"]:
                try:
                    if b.get("manual"):
                        fixas.append((b["x"], b["y"], b["w"], b["h"]))
                        continue                              # o usuário definiu à mão: não mexer
                    caixa = b.get("orig_caixa")
                    if isinstance(caixa, list) and len(caixa) == 4:
                        x, y, w, h = (float(v) for v in caixa)
                    else:  # capítulo antigo: encolhe a caixa gravada (que tinha folga) para aproximar o texto
                        dx, dy = min(8.0, b["w"] * 0.1), min(6.0, b["h"] * 0.12)
                        x, y, w, h = b["x"] + dx, b["y"] + dy, b["w"] - 2 * dx, b["h"] - 2 * dy
                    bloco = Bloco(x, y, w, h, str(b.get("original", "")), int(b.get("linhas", 1)), str(b["traduzido"]))
                    bloco.caixa_original = (x, y, w, h)
                    pares.append((b, bloco))
                except (KeyError, TypeError, ValueError):
                    continue
            if not pares:
                continue
            for b, bloco in pares:
                outros = fixas + [o.caixa_original for _, o in pares if o is not bloco]
                try:
                    ajustar_ao_balao(imagem, bloco, outros)
                except (KeyError, TypeError, ValueError):
                    bloco.fundo = None
            separar_sobrepostos([bl for _, bl in pares])
            for b, bloco in pares:
                if bloco.fundo is None and not bloco.cor_texto:
                    continue
                b.update({
                    "x": round(bloco.x, 1), "y": round(bloco.y, 1), "w": round(bloco.w, 1), "h": round(bloco.h, 1),
                    "fundo": bloco.fundo, "cor": bloco.cor_texto, "orig_caixa": [round(v, 1) for v in bloco.caixa_original],
                    "livre": [round(v, 1) for v in bloco.livre] if bloco.livre else None, "refer": round(bloco.referencia, 1),
                })
                mudados += 1
        if mudados:
            _gravar(pasta, dados)
        return {"imagens": imagens, "trechos": mudados}


def editar(pasta: Path, acao: str, dados_req: Dict[str, Any], motores: Any, de: str = "en", para: str = "pt") -> Dict[str, Any]:
    """Executa uma edição e devolve `{w, h, blocos}` atualizados da imagem."""
    pasta = Path(pasta)
    with _TRAVA:
        dados = _carregar(pasta, de, para)
        nome = _imagem(pasta, dados_req.get("imagem"))
        de, para = dados["de"], dados["para"]
        ctx = ia.contexto_da_pasta(pasta, de, para)

        def motor_traducao():
            return motores.tradutor(de, para)

        if acao == "retraduzir":
            info = _info(dados, pasta, nome)
            i = _indice(info, dados_req.get("indice"))
            original = _texto(dados_req.get("original"))
            ctx.memoria = {}                                   # "traduzir de novo" = tradução nova, não a lembrada
            ctx.anteriores = [(b.get("original", ""), b.get("traduzido", "")) for k, b in enumerate(info["blocos"]) if k < i][-6:]
            bloco = info["blocos"][i]
            bloco["original"] = original
            bloco["traduzido"] = ia.refinar(original, _traduzir_texto(motor_traducao, original, ctx), ctx)
            bloco["alertas"] = ia.revisar(original, bloco["traduzido"], de, para, float(bloco.get("confianca", 1.0)))
            bloco.pop("manual_texto", None)
        elif acao == "salvar":
            info = _info(dados, pasta, nome)
            i = _indice(info, dados_req.get("indice"))
            novo = _texto(dados_req.get("traduzido"))
            bloco = info["blocos"][i]
            if novo != bloco.get("traduzido"):
                ia.lembrar(pasta, str(bloco.get("original", "")), novo)
                _aprender(pasta, str(bloco.get("original", "")), str(bloco.get("traduzido", "")), novo, motor_traducao)
            bloco["traduzido"], bloco["alertas"] = novo, []
        elif acao == "remover":
            info = _info(dados, pasta, nome)
            del info["blocos"][_indice(info, dados_req.get("indice"))]
        elif acao == "geometria":
            info = _info(dados, pasta, nome)
            b = info["blocos"][_indice(info, dados_req.get("indice"))]
            x, y = _numero(dados_req.get("x"), "x"), _numero(dados_req.get("y"), "y")
            w, h = _numero(dados_req.get("w"), "w"), _numero(dados_req.get("h"), "h")
            if w < 4 or h < 4 or x < -50 or y < -50 or x + w > info["w"] + 50 or y + h > info["h"] + 50:
                raise ErroTraducao("A caixa saiu da imagem ou ficou pequena demais.")
            for chave in ("fundo", "cor"):
                valor = dados_req.get(chave)
                if valor is not None:
                    if not isinstance(valor, str) or not _COR.match(valor):
                        raise ErroTraducao("Cor inválida.")
                    b[chave] = valor.lower()
            fonte = dados_req.get("fonte")
            if fonte in (None, 0):
                b.pop("fonte", None)
            else:
                b["fonte"] = _numero(fonte, "fonte")
                if not 4 <= b["fonte"] <= 600:
                    raise ErroTraducao("Tamanho de letra inválido.")
            if "traduzido" in dados_req:
                novo = _texto(dados_req.get("traduzido"))
                if novo != b.get("traduzido"):
                    ia.lembrar(pasta, str(b.get("original", "")), novo)
                    _aprender(pasta, str(b.get("original", "")), str(b.get("traduzido", "")), novo, motor_traducao)
                b["traduzido"], b["alertas"] = novo, []
            b.update({"x": round(x, 1), "y": round(y, 1), "w": round(w, 1), "h": round(h, 1), "manual": True})
            b.pop("livre", None)                              # a caixa agora é escolha do usuário: sem crescer sozinha
        elif acao == "imagem":
            imagem_pronta = processar_imagem(pasta_imagens(pasta) / nome, motores.ocr(), motor_traducao(), ctx)
            info = imagem_pronta
            dados["imagens"][nome] = info
        elif acao == "area":
            x, y = _numero(dados_req.get("x"), "x"), _numero(dados_req.get("y"), "y")
            w, h = _numero(dados_req.get("w"), "w"), _numero(dados_req.get("h"), "h")
            manual = dados_req.get("texto")
            manual = _texto(manual, vazio_ok=True) if manual is not None else ""
            pronta = dados_req.get("traduzido")
            pronta = _texto(pronta, vazio_ok=True) if pronta is not None else ""
            imagem = carregar_imagem(pasta_imagens(pasta) / nome)
            if pronta:
                # criação totalmente manual: a caixa é exatamente o que o usuário desenhou
                x0, y0 = max(int(x), 0), max(int(y), 0)
                x1, y1 = min(int(x + w), imagem.shape[1]), min(int(y + h), imagem.shape[0])
                if x1 - x0 < 8 or y1 - y0 < 8:
                    raise ErroTraducao("A área escolhida é pequena demais.")
                bloco = Bloco(x0, y0, x1 - x0, y1 - y0, manual or "(digitado)", 1, pronta)
                fundo, cor = cor_do_fundo(imagem, bloco)
                novos = [{
                    "x": float(x0), "y": float(y0), "w": float(x1 - x0), "h": float(y1 - y0), "original": bloco.original,
                    "traduzido": pronta, "fundo": fundo, "cor": cor, "linhas": 1, "manual": True, "alertas": [],
                }]
                if manual:
                    ia.lembrar(pasta, manual, pronta)
            else:
                antes = _info(dados, pasta, nome, criar=True)["blocos"]
                ctx.anteriores = [(b.get("original", ""), b.get("traduzido", "")) for b in antes if b.get("y", 0) < y][-6:]
                novos = traduzir_area(
                    imagem, x, y, w, h, motores.ocr() if not manual else None, motor_traducao(), manual or None, ctx
                )
            info = _info(dados, pasta, nome, criar=True)
            info["w"], info["h"] = int(imagem.shape[1]), int(imagem.shape[0])

            def cobre(b: Dict[str, Any]) -> bool:
                """O bloco antigo é substituído se a área escolhida cobre boa parte dele."""
                ix = min(x + w, b["x"] + b["w"]) - max(x, b["x"])
                iy = min(y + h, b["y"] + b["h"]) - max(y, b["y"])
                return ix > 0 and iy > 0 and ix * iy >= 0.3 * b["w"] * b["h"]

            info["blocos"] = [b for b in info["blocos"] if not cobre(b)] + novos
            info["blocos"].sort(key=lambda b: (round(b["y"] / 40), b["x"]))
            del info["blocos"][MAX_BLOCOS_POR_IMAGEM:]
        else:
            raise ErroTraducao("Ação desconhecida.")
        _gravar(pasta, dados)
        return {"w": info["w"], "h": info["h"], "blocos": info["blocos"]}
