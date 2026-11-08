"""Tradução do texto que aparece dentro das imagens (balões de mangá/webtoon, legendas...).

Tudo gratuito e local: o texto é lido por OCR (RapidOCR, com os modelos já embutidos no pacote) e
traduzido por Argos Translate (modelos abertos, baixados UMA vez e depois usados sem internet).
Nenhuma imagem e nenhum texto saem do computador. A única conexão externa é o download único do
modelo de idioma, que só acontece quando você pede a tradução.

O resultado é gravado em `traducao.json` dentro da pasta do conjunto; o leitor global (`web/leitor/`)
mostra o texto traduzido por cima da imagem, sobre um fundo da cor do local, com um botão para
alternar com o original. As imagens originais nunca são alteradas.

Dependências opcionais (veja requirements-traducao.txt): rapidocr-onnxruntime e argostranslate.
Este módulo só as importa quando a tradução é de fato usada.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Tuple

from baixador.traducao import config, gemini, hymt, openrouter, refino
from baixador.traducao.numerada import registrar_tempo
from baixador.traducao import inteligencia as ia
from baixador.traducao.ocr_texto import continua_no_seguinte, dividir_traducao

from baixador.nucleo.erros import Cancelado, ErroBaixador
from baixador.biblioteca.capitulo import NOME_TRADUCAO, listar_imagens, pasta_imagens

IDIOMAS_ORIGEM = ("en", "es", "fr", "it", "de", "pt")      # o OCR embutido lê escrita latina
IDIOMAS_DESTINO = ("pt",)                                  # o destino é sempre o português; nada o deduz nem o troca
MIN_CONFIANCA = 0.5                                        # confiança mínima da linha âncora de um bloco
MIN_CONFIANCA_LINHA = 0.3                                  # confiança mínima das demais linhas do bloco
MAX_LADO_FATIA = 1500                                      # altura máxima de cada pedaço lido pelo OCR
SOBREPOSICAO = 120                                         # pixels repetidos entre pedaços
MAX_BLOCOS_POR_IMAGEM = 80
MAX_TEXTO_BLOCO = 600


class ErroTraducao(ErroBaixador):
    """Falta de dependência opcional, idioma indisponível ou imagem ilegível."""


# --------------------------------------------------------------------------- disponibilidade

def disponibilidade() -> Dict[str, bool]:
    """Quais dependências opcionais estão instaladas (sem importá-las)."""
    def existe(nome: str) -> bool:
        try:
            return importlib.util.find_spec(nome) is not None
        except (ImportError, ValueError):
            return False

    return {"ocr": existe("rapidocr_onnxruntime") and existe("cv2"), "traducao": existe("argostranslate")}


def exigir_dependencias(motor: str = "argos") -> None:
    """`motor`: 'argos' exige OCR + Argos; 'ocr' só o OCR."""
    d = disponibilidade()
    pedidos = [("rapidocr-onnxruntime", d["ocr"])]
    if motor == "argos":
        pedidos.append(("argostranslate", d["traducao"]))
    faltam = [n for n, ok in pedidos if not ok]
    if faltam:
        raise ErroTraducao(
            "A tradução precisa de pacotes opcionais que não estão instalados: " + ", ".join(faltam)
            + ". Instale com: pip install -r requirements-traducao.txt"
        )


# --------------------------------------------------------------------------- estruturas

@dataclass
class Linha:
    x0: float
    y0: float
    x1: float
    y1: float
    texto: str
    confianca: float = 1.0

    @property
    def altura(self) -> float:
        return max(self.y1 - self.y0, 1.0)

    @property
    def largura(self) -> float:
        return max(self.x1 - self.x0, 1.0)


@dataclass
class Bloco:
    x: float
    y: float
    w: float
    h: float
    original: str
    linhas: int = 1
    traduzido: str = ""
    fundo: str = "#ffffff"
    cor_texto: str = "#111111"
    caixa_original: Optional[Tuple[float, float, float, float]] = None   # x, y, w, h do texto lido (sem folga)
    confianca: float = 1.0                                                # média das linhas lidas pelo OCR
    alertas: List[str] = field(default_factory=list)
    livre: Optional[Tuple[float, float, float, float]] = None             # x, y, w, h do miolo livre do balão (onde o texto pode crescer)
    referencia: float = 0.0                                               # altura de uma linha do texto original, em px da imagem
    grupo: int = -1                                                       # balões da mesma frase contínua partilham o número
    origem: str = ""                                                      # "memoria" (correção do usuário) | "argos" | "hy"


# --------------------------------------------------------------------------- agrupamento (puro Python)

def _util(texto: str) -> bool:
    """Descarta ruído do OCR: precisa de ao menos 2 caracteres, um deles letra ou número."""
    t = texto.strip()
    return len(t) >= 2 and any(c.isalnum() for c in t)


def _mesmo_bloco(a: Linha, b: Linha) -> bool:
    """Duas linhas de texto pertencem ao mesmo balão se estão coladas, alinhadas e com letras de tamanho parecido."""
    razao = a.altura / b.altura
    if not 0.5 <= razao <= 2.0:
        return False
    if b.y0 < a.y0:
        a, b = b, a
    folga_vertical = b.y0 - a.y1
    menor = min(a.altura, b.altura)
    if folga_vertical > 1.2 * menor:
        return False
    sobreposicao = min(a.x1, b.x1) - max(a.x0, b.x0)
    if sobreposicao >= 0.3 * min(a.largura, b.largura):
        return True
    # texto centralizado (comum em balões): linhas curtas e longas compartilham o mesmo centro
    centro_a, centro_b = (a.x0 + a.x1) / 2, (b.x0 + b.x1) / 2
    return abs(centro_a - centro_b) <= 0.3 * max(a.largura, b.largura) and folga_vertical <= 0.8 * menor


def agrupar_linhas(linhas: List[Linha], ancora: float = MIN_CONFIANCA) -> List[Bloco]:
    """Junta as linhas lidas pelo OCR em blocos de texto (um por balão/legenda), na ordem de leitura."""
    # Linhas de baixa confiança (itálico, negrito, letra estilizada) só entram se estiverem coladas em
    # alguma linha confiável: o bloco precisa de pelo menos uma âncora.
    linhas = [l for l in linhas if _util(l.texto) and l.confianca >= MIN_CONFIANCA_LINHA]
    n = len(linhas)
    pai = list(range(n))

    def achar(i: int) -> int:
        while pai[i] != i:
            pai[i] = pai[pai[i]]
            i = pai[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if _mesmo_bloco(linhas[i], linhas[j]):
                pai[achar(i)] = achar(j)

    grupos: Dict[int, List[Linha]] = {}
    for i, linha in enumerate(linhas):
        grupos.setdefault(achar(i), []).append(linha)

    blocos: List[Bloco] = []
    for membros in grupos.values():
        membros.sort(key=lambda l: (round(l.y0), l.x0))
        partes: List[str] = []
        for l in membros:
            t = " ".join(l.texto.split())
            if partes and partes[-1].endswith("-") and t[:1].isalpha():
                partes[-1] = partes[-1][:-1] + t      # palavra quebrada no fim da linha
            else:
                partes.append(t)
        texto = " ".join(partes)[:MAX_TEXTO_BLOCO]
        x0, y0 = min(l.x0 for l in membros), min(l.y0 for l in membros)
        x1, y1 = max(l.x1 for l in membros), max(l.y1 for l in membros)
        if max(l.confianca for l in membros) < ancora:
            continue                                   # só linhas incertas: provavelmente ruído
        media = sum(l.confianca for l in membros) / len(membros)
        blocos.append(Bloco(x0, y0, x1 - x0, y1 - y0, texto, linhas=len(membros), confianca=media))
    blocos.sort(key=lambda b: (round(b.y / 40), b.x))
    return blocos[:MAX_BLOCOS_POR_IMAGEM]


# --------------------------------------------------------------------------- caixa baixa / alta

def _maioria_maiuscula(texto: str) -> bool:
    return ia.maioria_maiuscula(texto)


# --------------------------------------------------------------------------- imagem (precisa de numpy/cv2)

def carregar_imagem(caminho: Path):
    import cv2
    import numpy as np

    try:
        bruto = np.fromfile(str(caminho), dtype=np.uint8)
        imagem = cv2.imdecode(bruto, cv2.IMREAD_COLOR)
    except (OSError, ValueError):
        imagem = None
    if imagem is None:
        raise ErroTraducao(f"Não consegui abrir a imagem '{caminho.name}' para ler o texto.")
    return imagem


def cor_do_fundo(imagem, bloco: Bloco) -> Tuple[str, str]:
    """Cor predominante ao redor do texto (o balão ou o fundo) e uma cor de letra que contraste com ela."""
    import numpy as np

    alt, larg = imagem.shape[:2]
    folga = int(max(3, min(bloco.h * 0.25, 18)))
    x0, y0 = max(int(bloco.x) - folga, 0), max(int(bloco.y) - folga, 0)
    x1, y1 = min(int(bloco.x + bloco.w) + folga, larg), min(int(bloco.y + bloco.h) + folga, alt)
    regiao = imagem[y0:y1, x0:x1].copy()
    if regiao.size == 0:
        return "#ffffff", "#111111"
    # só a moldura ao redor do texto: o miolo tem as letras, que sujariam a cor
    dentro_x0, dentro_y0 = int(bloco.x) - x0, int(bloco.y) - y0
    dentro_x1, dentro_y1 = int(bloco.x + bloco.w) - x0, int(bloco.y + bloco.h) - y0
    mascara = np.ones(regiao.shape[:2], dtype=bool)
    mascara[max(dentro_y0, 0):max(dentro_y1, 0), max(dentro_x0, 0):max(dentro_x1, 0)] = False
    pixels = regiao[mascara] if mascara.any() else regiao.reshape(-1, 3)
    if pixels.size == 0:
        pixels = regiao.reshape(-1, 3)
    quantizado = (pixels // 32).astype(np.int32)
    chaves = quantizado[:, 0] * 64 + quantizado[:, 1] * 8 + quantizado[:, 2]
    mais_comum = np.bincount(chaves).argmax()
    escolhidos = pixels[chaves == mais_comum]
    b, g, r = (int(v) for v in escolhidos.mean(axis=0))
    luminancia = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return f"#{r:02x}{g:02x}{b:02x}", ("#111111" if luminancia > 0.55 else "#ffffff")


def fatias(altura: int, largura: int) -> List[Tuple[int, int, int, int]]:
    """Pedaços (inicio_lido, fim_lido, inicio_dono, fim_dono) para ler imagens muito compridas (webtoon).

    Cada linha de texto é atribuída ao pedaço "dono" do seu centro, e o pedaço lido tem folga em volta,
    para que nenhuma linha seja lida cortada ao meio.
    """
    limite = max(MAX_LADO_FATIA, int(largura * 1.6))
    if altura <= limite * 1.15:
        return [(0, altura, 0, altura)]
    passo = limite - 2 * SOBREPOSICAO
    resultado = []
    inicio = 0
    while inicio < altura:
        fim_dono = min(inicio + passo, altura)
        resultado.append((max(inicio - SOBREPOSICAO, 0), min(fim_dono + SOBREPOSICAO, altura), inicio, fim_dono))
        inicio = fim_dono
    return resultado


# --------------------------------------------------------------------------- OCR

class MotorOCR(Protocol):
    def __call__(self, imagem) -> List[Linha]: ...


_ocr_lock = threading.Lock()
_ocr_instancia: Any = None


def motor_ocr_padrao() -> MotorOCR:
    """RapidOCR (modelos embutidos). Uma instância só, reaproveitada."""
    global _ocr_instancia
    exigir_dependencias()
    with _ocr_lock:
        if _ocr_instancia is None:
            from rapidocr_onnxruntime import RapidOCR

            _ocr_instancia = RapidOCR()
        motor = _ocr_instancia

    def ler(imagem) -> List[Linha]:
        resultado, _ = motor(imagem)
        linhas: List[Linha] = []
        for caixa, texto, confianca in resultado or []:
            xs, ys = [p[0] for p in caixa], [p[1] for p in caixa]
            linhas.append(Linha(float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)), str(texto), float(confianca)))
        return linhas

    return ler


def ler_linhas(imagem, motor: MotorOCR) -> List[Linha]:
    """Roda o OCR na imagem inteira, em pedaços se for muito comprida."""
    altura, largura = imagem.shape[:2]
    todas: List[Linha] = []
    for ini_lido, fim_lido, ini_dono, fim_dono in fatias(altura, largura):
        for l in motor(imagem[ini_lido:fim_lido]):
            centro = (l.y0 + l.y1) / 2 + ini_lido
            if not (ini_dono <= centro < fim_dono or (fim_dono == altura and centro >= ini_dono)):
                continue
            todas.append(Linha(l.x0, l.y0 + ini_lido, l.x1, l.y1 + ini_lido, l.texto, l.confianca))
    return todas


# --------------------------------------------------------------------------- tradução

class Tradutor(Protocol):
    def __call__(self, textos: List[str]) -> List[str]: ...


def instalar_idioma(de: str, para: str, informar: Callable[[str], None] = lambda _m: None) -> None:
    """Baixa (uma vez) o modelo Argos do par de idiomas, se ainda não estiver instalado."""
    exigir_dependencias()
    import argostranslate.package as pacote
    import argostranslate.translate as traducao

    def pronto() -> bool:
        idiomas = {i.code: i for i in traducao.get_installed_languages()}
        origem, destino = idiomas.get(de), idiomas.get(para)
        return bool(origem and destino and origem.get_translation(destino))

    if pronto():
        return
    informar(
        f"Baixando o modelo de tradução {de}→{para} (só desta vez, algumas centenas de MB; "
        "depois funciona sem internet)…"
    )
    try:
        ok = pacote.install_package_for_language_pair(de, para)
    except Exception as erro:  # rede, disco...
        raise ErroTraducao(f"Não foi possível baixar o modelo de tradução {de}→{para}: {erro}") from None
    if ok is False or not pronto():
        raise ErroTraducao(f"O par de idiomas {de}→{para} não está disponível no Argos Translate.")


class TradutorArgos:
    """Tradutor offline (Argos). Entende nomes próprios e termos fixos do glossário; não usa contexto de página."""

    def __init__(self, de: str, para: str) -> None:
        exigir_dependencias("argos")
        import argostranslate.translate as traducao

        self._traducao, self.de, self.para = traducao, de, para
        self._es_pt_indisponivel = False

    def _forcar_portugues(self, texto: str, fixos: Optional[List[str]] = None) -> str:
        """Segunda tradução: se o resultado ainda traz palavras do espanhol, passa por es→pt e fica com o melhor.

        O destino é sempre o português. A detecção de idioma só decide se vale a segunda passada; nunca muda o destino.
        """
        if self.para != "pt" or self.de == "es" or not ia.vazou_espanhol(texto):
            return texto
        for _ in range(2):
            antes = ia.vazou_espanhol(texto)
            if not antes:
                break
            novo = self._es_para_pt(texto)
            if not novo or ia.vazou_espanhol(novo) >= antes:
                break
            if any(f and f.lower() in texto.lower() and f.lower() not in novo.lower() for f in (fixos or [])):
                break                                          # a segunda passada estragou um nome/termo fixo: descarta
            texto = novo
        return texto

    def _es_para_pt(self, texto: str) -> Optional[str]:
        if self._es_pt_indisponivel:
            return None
        try:
            instalar_idioma("es", "pt")
            return self._traducao.translate(texto, "es", "pt")
        except Exception:                                      # sem o modelo es→pt (ou sem rede): mantém o resultado e o alerta
            self._es_pt_indisponivel = True
            return None

    def _uma(self, texto: str) -> str:
        try:
            return self._traducao.translate(texto, self.de, self.para)
        except Exception as erro:
            raise ErroTraducao(f"A tradução falhou: {erro}") from None

    def __call__(self, textos: List[str]) -> List[str]:
        return self.traduzir_pagina(textos, None)

    def traduzir_pagina(self, textos: List[str], ctx: Optional[ia.Contexto] = None) -> List[str]:
        nomes = list(ctx.nomes) if ctx else []
        termos = dict(ctx.termos) if ctx else {}
        saida: List[str] = []
        for texto in textos:
            texto = ia.corrigir_ocr(texto, nomes, self.de)
            alta = _maioria_maiuscula(texto)
            entrada = ia.frase_natural(texto, nomes) if alta else texto
            marcas: Dict[str, str] = {}
            for k, (termo, fixo) in enumerate(termos.items()):          # termo fixo: troca por uma palavra-código
                codigo = f"Zq{chr(97 + k % 26)}{chr(97 + k // 26 % 26)}x"
                novo = re.sub(r"(?<![\w-])" + re.escape(termo) + r"(?![\w-])", codigo, entrada, flags=re.I)
                if novo != entrada:
                    marcas[codigo], entrada = fixo, novo
            resultado = self._uma(entrada)
            for codigo, fixo in marcas.items():
                resultado = re.sub(re.escape(codigo), fixo, resultado, flags=re.I)
            resultado = self._forcar_portugues(resultado, list(marcas.values()) + nomes)
            saida.append(resultado.upper() if alta else resultado)
        return saida


def criar_motor_traducao(
    de: str, para: str, informar: Callable[[str], None] = lambda _m: None,
) -> Tradutor:
    """Cria o tradutor (Argos, local), baixando o modelo do par de idiomas se ainda não existir."""
    exigir_dependencias("argos")
    instalar_idioma(de, para, informar)
    return TradutorArgos(de, para)


# --------------------------------------------------------------------------- pipeline

def _hex_para_bgr(cor: str) -> Tuple[int, int, int]:
    return int(cor[5:7], 16), int(cor[3:5], 16), int(cor[1:3], 16)


def cor_da_tinta(imagem, bloco: Bloco, fundo: str) -> Optional[str]:
    """Cor predominante das letras do texto original (ex.: vermelho), ou None se não der para saber."""
    import numpy as np

    alt, larg = imagem.shape[:2]
    x0, y0 = max(int(bloco.x), 0), max(int(bloco.y), 0)
    x1, y1 = min(int(bloco.x + bloco.w), larg), min(int(bloco.y + bloco.h), alt)
    regiao = imagem[y0:y1, x0:x1].reshape(-1, 3).astype(np.int32)
    if regiao.size == 0:
        return None
    distancia = np.abs(regiao - np.array(_hex_para_bgr(fundo))).sum(axis=1)
    tinta = regiao[distancia > 150]
    if len(tinta) < 12:
        return None
    q = tinta // 32
    chaves = q[:, 0] * 64 + q[:, 1] * 8 + q[:, 2]
    escolhidos = tinta[chaves == np.bincount(chaves).argmax()]
    b, g, r = (int(v) for v in escolhidos.mean(axis=0))
    lum = lambda rr, gg, bb: (0.299 * rr + 0.587 * gg + 0.114 * bb) / 255
    fb, fg, fr = _hex_para_bgr(fundo)
    if abs(lum(r, g, b) - lum(fr, fg, fb)) < 0.25:
        return None                                          # sem contraste: não vale copiar a cor
    return f"#{r:02x}{g:02x}{b:02x}"


def ajustar_ao_balao(imagem, bloco: Bloco, outros: Sequence[Tuple[float, float, float, float]] = ()) -> Bloco:
    """Define fundo, cor da letra e a caixa final do texto traduzido, respeitando o balão.

    Parte da caixa do texto lido. Acha a área "de fundo" que cerca o texto (o interior do balão) e:
    - inclui na caixa qualquer tinta solta perto do texto dentro do balão (linha que o OCR perdeu), para
      não sobrar rastro do original;
    - só aumenta a folga onde ainda é fundo, então a caixa nunca atravessa a borda do balão.
    - `outros`: caixas do texto lido dos demais balões da página; letra de outro balão (balões colados formam um só
      "interior") nunca é puxada para esta caixa.
    Se o fundo não for uniforme (desenho, degradê), cai numa folga fixa pequena.
    """
    import cv2
    import numpy as np

    alt, larg = imagem.shape[:2]
    if bloco.caixa_original is None:
        bloco.caixa_original = (bloco.x, bloco.y, bloco.w, bloco.h)
    ox, oy, ow, oh = bloco.caixa_original
    bloco.x, bloco.y, bloco.w, bloco.h = ox, oy, ow, oh
    bloco.livre = None
    bloco.referencia = round(max(oh / max(bloco.linhas, 1), 0.0), 1)
    bloco.fundo, bloco.cor_texto = cor_do_fundo(imagem, bloco)
    tinta = cor_da_tinta(imagem, bloco, bloco.fundo)
    if tinta:
        bloco.cor_texto = tinta

    x0, y0 = max(int(ox), 0), max(int(oy), 0)
    x1, y1 = min(int(ox + ow), larg), min(int(oy + oh), alt)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return _expandir(bloco, larg, alt)
    linha_h = max(oh / max(bloco.linhas, 1), 8.0)
    mx, my = int(max(ow * 0.3, 24)), int(max(oh * 0.8, 24))
    wx0, wy0, wx1, wy1 = max(x0 - mx, 0), max(y0 - my, 0), min(x1 + mx, larg), min(y1 + my, alt)
    janela = imagem[wy0:wy1, wx0:wx1].astype(np.int16)
    fundo_bgr = np.array(_hex_para_bgr(bloco.fundo), dtype=np.int16)
    perto = (np.abs(janela - fundo_bgr).sum(axis=2) <= 90).astype(np.uint8)
    altura_j, largura_j = perto.shape
    _, rotulos = cv2.connectedComponents(perto, connectivity=4)
    anel = np.zeros_like(perto, dtype=bool)
    ax0, ay0, ax1, ay1 = max(x0 - 3 - wx0, 0), max(y0 - 3 - wy0, 0), min(x1 + 3 - wx0, largura_j), min(y1 + 3 - wy0, altura_j)
    anel[ay0:ay1, ax0:ax1] = True
    anel[max(y0 - wy0, 0):max(y1 - wy0, 0), max(x0 - wx0, 0):max(x1 - wx0, 0)] = False
    candidatos = rotulos[anel & (perto == 1)]
    candidatos = candidatos[candidatos > 0]
    if candidatos.size == 0:
        return _expandir(bloco, larg, alt)
    interior = rotulos == np.bincount(candidatos).argmax()
    if interior.mean() < 0.25:
        return _expandir(bloco, larg, alt)           # fundo irregular: não dá para confiar na máscara

    # "buracos": o que não é fundo mas está cercado por ele (letras e, às vezes, linhas que o OCR perdeu)
    n, rot, est, _ = cv2.connectedComponentsWithStats((~interior).astype(np.uint8), connectivity=8)
    buracos = []
    for i in range(1, n):
        l, t, w, h, area = (int(v) for v in est[i])
        if (l <= 0 and wx0 > 0) or (t <= 0 and wy0 > 0) or (l + w >= largura_j and wx1 < larg) or (t + h >= altura_j and wy1 < alt):
            continue                                  # encosta na borda da janela: é a borda do balão ou arte
        if h > linha_h * 3 or w > ow * 1.3 + mx:
            continue
        if area < 6:
            continue                                  # pontinho solto (ruído do JPEG, serrilhado da borda): não é letra nem pontuação
        cx_b, cy_b = l + wx0 + w / 2, t + wy0 + h / 2
        if any(ox - 4 <= cx_b <= ox + ow_ + 4 and oy - 4 <= cy_b <= oy + oh_ + 4 for ox, oy, ow_, oh_ in outros):
            continue                                  # é letra de outro balão
        buracos.append((i, l + wx0, t + wy0, w, h))
    ux0, uy0, ux1, uy1 = x0, y0, x1, y1
    incluidos = set()
    for _ in range(3):
        mudou = False
        for i, l, t, w, h in buracos:
            if i in incluidos:
                continue
            folga = linha_h * (1.8 if (h <= linha_h * 0.9 and w <= linha_h * 2.5) else 1.0)   # pontuação/acento solto vai mais longe
            pequeno = h <= linha_h * 0.9 and w <= linha_h * 2.5
            rx0, ry0, rx1, ry1 = (x0, y0, x1, y1) if pequeno else (ux0, uy0, ux1, uy1)   # pontuação solta mede a distância do texto lido, não da caixa que já cresceu (senão uma "corrente" de pontos vai longe)
            if l + w >= rx0 - folga and l <= rx1 + folga and t + h >= ry0 - folga and t <= ry1 + folga:
                incluidos.add(i)
                nx0, ny0, nx1, ny1 = min(ux0, l - 2), min(uy0, t - 2), max(ux1, l + w + 2), max(uy1, t + h + 2)   # +2px: halo do anti-serrilhado
                if (nx0, ny0, nx1, ny1) != (ux0, uy0, ux1, uy1):
                    ux0, uy0, ux1, uy1 = nx0, ny0, nx1, ny1
                    mudou = True
        if not mudou:
            break
    ok = interior.copy()
    for i, *_ in buracos:
        if i in incluidos:
            ok |= rot == i
    # uma tira de folga ao redor, só onde ainda é fundo
    folga_x, folga_y = int(5 + 0.04 * (ux1 - ux0)), int(4 + 0.08 * (uy1 - uy0))

    def tira_ok(a0: int, b0: int, a1: int, b1: int) -> bool:
        a0, b0, a1, b1 = a0 - wx0, b0 - wy0, a1 - wx0, b1 - wy0
        if a0 < 0 or b0 < 0 or a1 > largura_j or b1 > altura_j or a1 <= a0 or b1 <= b0:
            return False
        return float(ok[b0:b1, a0:a1].mean()) >= 0.97

    for _ in range(folga_x):
        if tira_ok(ux0 - 1, uy0, ux0, uy1):
            ux0 -= 1
        else:
            break
    for _ in range(folga_x):
        if tira_ok(ux1, uy0, ux1 + 1, uy1):
            ux1 += 1
        else:
            break
    for _ in range(folga_y):
        if tira_ok(ux0, uy0 - 1, ux1, uy0):
            uy0 -= 1
        else:
            break
    for _ in range(folga_y):
        if tira_ok(ux0, uy1, ux1, uy1 + 1):
            uy1 += 1
        else:
            break
    bloco.x, bloco.y, bloco.w, bloco.h = float(ux0), float(uy0), float(ux1 - ux0), float(uy1 - uy0)
    bloco.livre = _miolo_livre(janela, fundo_bgr, (wx0, wy0), (ux0, uy0, ux1, uy1), ok, cv2, np)
    return bloco


def _miolo_livre(janela, fundo_bgr, origem, caixa, ok, cv2, np) -> Optional[Tuple[float, float, float, float]]:
    """Maior retângulo (crescendo a partir da caixa) que ainda é fundo liso do balão: o espaço onde a tradução pode "respirar".

    Cada lado só avança enquanto a faixa nova for fundo quase idêntico ao do balão (nunca atravessa borda, cauda ou arte).
    """
    wx0, wy0 = origem
    altura_j, largura_j = janela.shape[:2]
    liso = (np.abs(janela - fundo_bgr).sum(axis=2) <= 36) | ok
    a0, b0, a1, b1 = caixa[0] - wx0, caixa[1] - wy0, caixa[2] - wx0, caixa[3] - wy0
    lim_x, lim_y = int((a1 - a0) * 0.45), int((b1 - b0) * 0.6)
    gx = gy = 0

    def faixa(x0: int, y0: int, x1: int, y1: int) -> bool:
        if x0 < 0 or y0 < 0 or x1 > largura_j or y1 > altura_j or x1 <= x0 or y1 <= y0:
            return False
        return bool(liso[y0:y1, x0:x1].all())

    for _ in range(max(lim_x, lim_y)):
        mexeu = False
        if gx < lim_x and faixa(a0 - 1, b0, a0, b1):
            a0 -= 1; gx += 1; mexeu = True
        if gx < lim_x and faixa(a1, b0, a1 + 1, b1):
            a1 += 1; gx += 1; mexeu = True
        if gy < lim_y and faixa(a0, b0 - 1, a1, b0):
            b0 -= 1; gy += 1; mexeu = True
        if gy < lim_y and faixa(a0, b1, a1, b1 + 1):
            b1 += 1; gy += 1; mexeu = True
        if not mexeu:
            break
    if (a1 - a0) <= (caixa[2] - caixa[0]) + 2 and (b1 - b0) <= (caixa[3] - caixa[1]) + 2:
        return None                                    # não sobrou espaço: nada a oferecer
    return (float(a0 + wx0), float(b0 + wy0), float(a1 - a0), float(b1 - b0))


def _expandir(bloco: Bloco, largura: int, altura: int) -> Bloco:
    """Aumenta um pouco a caixa para o fundo cobrir o texto original por inteiro."""
    folga_x = 6 + bloco.w * 0.05
    folga_y = 5 + bloco.h * 0.10
    x0, y0 = max(bloco.x - folga_x, 0), max(bloco.y - folga_y, 0)
    x1, y1 = min(bloco.x + bloco.w + folga_x, largura), min(bloco.y + bloco.h + folga_y, altura)
    bloco.x, bloco.y, bloco.w, bloco.h = x0, y0, x1 - x0, y1 - y0
    return bloco


def _altura_media_linha(b: Bloco) -> float:
    return b.h / max(b.linhas, 1)


def _tinta_na_faixa(imagem, x0: int, y0: int, x1: int, y1: int) -> float:
    """Fração de pixels da faixa que não têm a cor de fundo dela (indício de texto no meio)."""
    import numpy as np

    faixa = imagem[max(y0, 0):max(y1, 0), max(x0, 0):max(x1, 0)]
    if faixa.size == 0:
        return 0.0
    pixels = faixa.reshape(-1, 3).astype(np.int32)
    quant = pixels // 32
    chaves = quant[:, 0] * 64 + quant[:, 1] * 8 + quant[:, 2]
    fundo = pixels[chaves == np.bincount(chaves).argmax()].mean(axis=0)
    distancia = np.abs(pixels - fundo).sum(axis=1)
    return float((distancia > 150).mean())


def recuperar_linhas_perdidas(imagem, linhas: List[Linha], motor: MotorOCR) -> List[Linha]:
    """Procura texto que o OCR deixou passar entre dois blocos do mesmo balão (ex.: uma linha em itálico).

    Onde há um vão grande demais entre dois blocos alinhados e o vão tem "tinta", lê de novo só aquele
    pedaço, ampliado. O que for achado entra na lista de linhas (e o agrupamento junta tudo de novo).
    """
    import cv2

    blocos = agrupar_linhas(linhas)
    alt, larg = imagem.shape[:2]
    novas: List[Linha] = []
    ordenados = sorted(blocos, key=lambda b: b.y)
    tentativas = 0
    for a in ordenados:
        for b in ordenados:
            if b.y <= a.y + a.h * 0.5 or tentativas >= 6:
                continue
            href = min(_altura_media_linha(a), _altura_media_linha(b))
            vao = b.y - (a.y + a.h)
            if not (0.9 * href <= vao <= 3.2 * href):
                continue
            sobre = min(a.x + a.w, b.x + b.w) - max(a.x, b.x)
            centro_a, centro_b = a.x + a.w / 2, b.x + b.w / 2
            if sobre < 0.4 * min(a.w, b.w) and abs(centro_a - centro_b) > 0.3 * max(a.w, b.w):
                continue
            # só o vizinho imediato: se há outro bloco no meio, não é um vão
            if any(c is not a and c is not b and a.y + a.h <= c.y < b.y for c in ordenados):
                continue
            x0, x1 = int(min(a.x, b.x)) - 10, int(max(a.x + a.w, b.x + b.w)) + 10
            y0, y1 = int(a.y + a.h), int(b.y)
            if _tinta_na_faixa(imagem, x0, y0, x1, y1) < 0.04:
                continue
            tentativas += 1
            cy0, cy1 = max(int(y0 - 0.35 * href), 0), min(int(y1 + 0.35 * href), alt)
            cx0, cx1 = max(x0, 0), min(x1, larg)
            recorte = imagem[cy0:cy1, cx0:cx1]
            if recorte.size == 0:
                continue
            ampliado = cv2.resize(recorte, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            for l in motor(ampliado):
                nova = Linha(l.x0 / 2 + cx0, l.y0 / 2 + cy0, l.x1 / 2 + cx0, l.y1 / 2 + cy0, l.texto, l.confianca)
                centro_y = (nova.y0 + nova.y1) / 2
                if y0 - 0.2 * href <= centro_y <= y1 + 0.2 * href and l.confianca >= MIN_CONFIANCA_LINHA and _util(l.texto):
                    novas.append(nova)
    return linhas + novas


def _quase_igual(a: str, b: str) -> bool:
    limpo = lambda t: re.sub(r"[\W_]+", "", t).lower()
    return limpo(a) == limpo(b)


def _sem_duplicadas(linhas: List[Linha]) -> List[Linha]:
    """Tira leituras repetidas do mesmo trecho (a releitura ampliada pode devolver a mesma linha de novo, com lixo, ex.: "SIR...!" e "I7....").
    Fica a de maior confiança; uma linha cuja área está ≥ 50% coberta por outra já mantida é descartada."""
    mantidas: List[Linha] = []
    for l in sorted(linhas, key=lambda x: -x.confianca):
        area = max(1.0, (l.x1 - l.x0) * (l.y1 - l.y0))
        coberta = False
        for m in mantidas:
            inter = max(0.0, min(l.x1, m.x1) - max(l.x0, m.x0)) * max(0.0, min(l.y1, m.y1) - max(l.y0, m.y0))
            if inter >= 0.5 * area:
                coberta = True
                break
        if not coberta:
            mantidas.append(l)
    ids = {id(l) for l in mantidas}
    return [l for l in linhas if id(l) in ids]


MAX_PALAVRAS_EFEITO = 2                                    # efeito sonoro (VROOM, TAP TAP, AHH): no máximo 2 palavras...
MAX_LETRAS_EFEITO = 16                                     # ...e poucas letras
UNIFORME_MIN = 0.8                                         # fração do entorno com a mesma cor para valer como balão/legenda lisa


def _efeito_sonoro(imagem, b: Bloco, outros: Sequence[Bloco]) -> bool:
    """Efeito sonoro/onomatopeia (VROOM, TAP, FLASH, AHH): texto curto, grande e SOBRE A ARTE (sem balão nem caixa lisa por trás).

    Fala em balão, legenda lisa e frase com 3+ palavras nunca contam como efeito; na dúvida, o texto é traduzido."""
    import numpy as np

    palavras = re.findall(r"[^\W\d_]+", b.original)
    letras = sum(len(p) for p in palavras)
    if not palavras or len(palavras) > MAX_PALAVRAS_EFEITO or letras > MAX_LETRAS_EFEITO:
        return False
    alturas = sorted(_altura_media_linha(o) for o in outros if o is not b and o.linhas >= 1)
    larg = imagem.shape[1]
    if alturas:
        if _altura_media_linha(b) < 1.2 * alturas[len(alturas) // 2]:
            return False                                   # letra do tamanho das falas: é fala
    elif _altura_media_linha(b) < 0.06 * larg:
        return False
    alt, larg = imagem.shape[:2]
    m = int(max(6, 0.35 * _altura_media_linha(b)))
    x0, y0, x1, y1 = int(b.x), int(b.y), int(b.x + b.w), int(b.y + b.h)
    X0, Y0, X1, Y1 = max(x0 - m, 0), max(y0 - m, 0), min(x1 + m, larg), min(y1 + m, alt)
    anel = imagem[Y0:Y1, X0:X1].mean(axis=2)
    mascara = np.ones(anel.shape, bool)
    mascara[max(y0 - Y0, 0):y1 - Y0, max(x0 - X0, 0):x1 - X0] = False
    pix = anel[mascara]
    if pix.size < 20:
        return False
    uniforme = float((np.abs(pix - np.median(pix)) <= 22).mean())
    return uniforme < UNIFORME_MIN


def _sem_efeitos(imagem, blocos: List[Bloco]) -> List[Bloco]:
    try:
        return [b for b in blocos if not _efeito_sonoro(imagem, b, blocos)]
    except Exception:
        return blocos                                       # é um extra: na dúvida, mantém tudo


def ler_blocos(imagem, motor: MotorOCR) -> List[Bloco]:
    """OCR + recuperação de linhas perdidas + agrupamento em balões (sem traduzir)."""
    linhas = ler_linhas(imagem, motor)
    try:
        linhas = _sem_duplicadas(recuperar_linhas_perdidas(imagem, linhas, motor))
    except Exception:
        pass  # a recuperação é um extra: se falhar, segue com o que o OCR leu
    return _sem_efeitos(imagem, agrupar_linhas(linhas))


def _motor_de(traduzir: Any) -> Any:
    """Aceita tanto um motor com `traduzir_pagina` quanto uma função simples `(textos) -> textos`."""
    if hasattr(traduzir, "traduzir_pagina"):
        return traduzir

    class _Simples:
        def traduzir_pagina(self, textos: List[str], ctx: Optional[ia.Contexto] = None) -> List[str]:
            return traduzir(textos)

    return _Simples()


def _continua(a: Bloco, b: Bloco) -> bool:
    """Dois balões seguidos são uma frase só quando o texto pede (ocr_texto.continua_no_seguinte) E a geometria confirma:
    `b` logo abaixo de `a`, alinhados e com letra do mesmo tamanho."""
    if not continua_no_seguinte(a.original, b.original):
        return False
    la, lb = _altura_media_linha(a), _altura_media_linha(b)
    if la <= 0 or lb <= 0 or not 0.7 <= la / lb <= 1.4:
        return False
    folga = b.y - (a.y + a.h)
    sobra = min(a.x + a.w, b.x + b.w) - max(a.x, b.x)
    return -0.3 * la <= folga <= 2.5 * la and sobra >= 0.4 * min(a.w, b.w)


def _agrupar_continuacoes(pendentes: List[Bloco]) -> List[List[Bloco]]:
    grupos: List[List[Bloco]] = []
    for b in pendentes:
        if grupos and len(grupos[-1]) < 3 and _continua(grupos[-1][-1], b):
            grupos[-1].append(b)
        else:
            grupos.append([b])
    return grupos


def _dividir(traducao: str, grupo: List[Bloco]) -> List[str]:
    if len(grupo) == 1:
        return [traducao]
    pesos = [max(1, len(re.findall(r"\S+", b.original))) for b in grupo]
    return dividir_traducao(traducao, pesos)


def traduzir_blocos(blocos: List[Bloco], traduzir: Any, ctx: Optional[ia.Contexto], de: str = "en", para: str = "pt") -> None:
    """Traduz os balões de uma página (memória de correções primeiro, depois o motor) e calcula os alertas."""
    ctx = ctx or ia.Contexto(de=de, para=para)
    pendentes = []
    for b in blocos:
        lembrada = ia.procurar_memoria(ctx.memoria, b.original)
        if lembrada:
            b.traduzido, b.origem = lembrada, "memoria"
        else:
            pendentes.append(b)
    if pendentes:
        grupos = _agrupar_continuacoes(pendentes) if ctx.de == "en" else [[b] for b in pendentes]
        juntos = [" ".join(b.original for b in g) for g in grupos]
        textos = [ia.corrigir_ocr(t, ctx.nomes, ctx.de) for t in juntos]
        motor = _motor_de(traduzir)
        origem = getattr(motor, "origem", "argos")
        inicio_t = time.time()
        traducoes = motor.traduzir_pagina(textos, ctx)
        registrar_tempo(getattr(motor, "nome_motor", "Argos"), len(textos), time.time() - inicio_t, getattr(motor, "refeitos", None))
        if len(traducoes) != len(grupos):
            raise ErroTraducao("O tradutor devolveu uma quantidade diferente de textos.")
        id_grupo = 1 + max([b.grupo for b in blocos] + [0])
        for g, original, t in zip(grupos, juntos, traducoes):
            final = ia.refinar(original, t, ctx)
            partes = _dividir(final, g)
            for b, parte in zip(g, partes):
                b.traduzido, b.origem = parte, origem
                b.grupo = id_grupo
            id_grupo += 1
            g[0].alertas = ia.revisar(original, final, ctx.de, ctx.para, min(b.confianca for b in g))
            for b in g[1:]:
                b.alertas = []
    ctx.anteriores = (ctx.anteriores + [(b.original, b.traduzido) for b in blocos if b.traduzido])[-8:]


def _caixa(b: Bloco) -> Tuple[float, float, float, float]:
    return (b.x, b.y, b.w, b.h)


def separar_sobrepostos(blocos: List[Bloco]) -> None:
    """Nenhuma caixa de tradução pode cobrir outra. Quando duas se cruzam (balões colados, caixa que cresceu demais),
    o corte passa no meio do vão entre os textos originais; cada caixa continua contendo o seu texto original."""
    for _ in range(3):
        mexeu = False
        for i, a in enumerate(blocos):
            for b in blocos[i + 1:]:
                ax, ay, aw, ah = _caixa(a)
                bx, by, bw, bh = _caixa(b)
                pw = min(ax + aw, bx + bw) - max(ax, bx)
                ph = min(ay + ah, by + bh) - max(ay, by)
                if pw <= 1 or ph <= 1:
                    continue
                ca = a.caixa_original or _caixa(a)
                cb = b.caixa_original or _caixa(b)
                # separação possível em cada eixo: (primeiro, segundo, folga entre os textos originais)
                vert = (a, b, cb[1] - (ca[1] + ca[3])) if ca[1] + ca[3] <= cb[1] else (b, a, ca[1] - (cb[1] + cb[3])) if cb[1] + cb[3] <= ca[1] else None
                hor = (a, b, cb[0] - (ca[0] + ca[2])) if ca[0] + ca[2] <= cb[0] else (b, a, ca[0] - (cb[0] + cb[2])) if cb[0] + cb[2] <= ca[0] else None
                if vert and (not hor or ph <= pw):
                    cima, baixo, _ = vert
                    cc = cima.caixa_original or _caixa(cima)
                    cbx = baixo.caixa_original or _caixa(baixo)
                    corte = (cc[1] + cc[3] + cbx[1]) / 2
                    cima.h = min(cima.y + cima.h, corte) - cima.y
                    novo = max(baixo.y, corte)
                    baixo.h, baixo.y = baixo.y + baixo.h - novo, novo
                elif hor:
                    esq, dir_, _ = hor
                    ce = esq.caixa_original or _caixa(esq)
                    cd = dir_.caixa_original or _caixa(dir_)
                    corte = (ce[0] + ce[2] + cd[0]) / 2
                    esq.w = min(esq.x + esq.w, corte) - esq.x
                    novo = max(dir_.x, corte)
                    dir_.w, dir_.x = dir_.x + dir_.w - novo, novo
                else:
                    continue                                    # os textos originais já se tocam: não há como separar
                mexeu = True
                for blo in (a, b):
                    if blo.livre:
                        lx, ly, lw, lh = blo.livre
                        x0, y0 = max(lx, blo.x), max(ly, blo.y)
                        x1, y1 = min(lx + lw, blo.x + blo.w), min(ly + lh, blo.y + blo.h)
                        blo.livre = (x0, y0, max(0.0, x1 - x0), max(0.0, y1 - y0)) if x1 > x0 and y1 > y0 else None
        if not mexeu:
            break


def finalizar_blocos(imagem, blocos: List[Bloco]) -> Dict[str, Any]:
    """Escolhe os trechos úteis, ajusta cada caixa ao balão e monta o dicionário da imagem."""
    altura, largura = imagem.shape[:2]
    # Tradução igual ao original (nome próprio, ou lixo do OCR que o tradutor devolveu como veio):
    # não vale cobrir a imagem com um texto que não adiciona nada.
    uteis = [b for b in blocos if b.traduzido and not _quase_igual(b.traduzido, b.original)]
    caixas = [(id(b), (b.x, b.y, b.w, b.h)) for b in blocos]
    for bloco in uteis:
        ajustar_ao_balao(imagem, bloco, [c for i, c in caixas if i != id(bloco)])
    separar_sobrepostos(uteis)
    return {"w": int(largura), "h": int(altura), "blocos": [bloco_para_dict(b) for b in uteis]}


def processar_imagem(
    caminho: Path, motor: MotorOCR, traduzir: Any, ctx: Optional[ia.Contexto] = None
) -> Dict[str, Any]:
    imagem = carregar_imagem(caminho)
    blocos = ler_blocos(imagem, motor)
    if blocos:
        traduzir_blocos(blocos, traduzir, ctx)
    return finalizar_blocos(imagem, blocos)


RODADAS_ADIADAS = 3                                        # quantas vezes volta às páginas adiadas por instabilidade do tradutor
MIN_CONFIANCA_AREA = 0.3                                   # numa área escolhida pelo usuário, aceita-se leitura mais incerta


def bloco_para_dict(b: Bloco) -> Dict[str, Any]:
    return {
        "x": round(b.x, 1), "y": round(b.y, 1), "w": round(b.w, 1), "h": round(b.h, 1),
        "original": b.original, "traduzido": b.traduzido,
        "fundo": b.fundo, "cor": b.cor_texto, "linhas": b.linhas,
        "orig_caixa": [round(v, 1) for v in (b.caixa_original or (b.x, b.y, b.w, b.h))],
        "confianca": round(b.confianca, 2), "alertas": list(b.alertas),
        "livre": [round(v, 1) for v in b.livre] if b.livre else None, "refer": round(b.referencia, 1),
        **({"grupo": b.grupo} if b.grupo >= 0 else {}), **({"origem_tr": b.origem} if b.origem else {}),
    }


def traduzir_area(
    imagem, x: float, y: float, w: float, h: float, motor: MotorOCR, traduzir: Any, texto: Optional[str] = None,
    ctx: Optional[ia.Contexto] = None,
) -> List[Dict[str, Any]]:
    """Lê e traduz só um retângulo da imagem (coordenadas em pixels da imagem original).

    Sem `texto`, o OCR relê o recorte ampliado 2× (letras pequenas saem melhor) e aceita leituras mais
    incertas, já que o usuário garante que há texto ali. Com `texto`, usa o que foi digitado como original.
    """
    import cv2

    altura, largura = imagem.shape[:2]
    x0, y0 = max(int(x), 0), max(int(y), 0)
    x1, y1 = min(int(x + w), largura), min(int(y + h), altura)
    if x1 - x0 < 8 or y1 - y0 < 8:
        raise ErroTraducao("A área escolhida é pequena demais.")
    if texto is not None and texto.strip():
        bloco = Bloco(x0, y0, x1 - x0, y1 - y0, " ".join(texto.split())[:MAX_TEXTO_BLOCO], linhas=1)
        blocos = [bloco]
    else:
        margem = 10
        cx0, cy0, cx1, cy1 = max(x0 - margem, 0), max(y0 - margem, 0), min(x1 + margem, largura), min(y1 + margem, altura)
        recorte = imagem[cy0:cy1, cx0:cx1]
        ampliado = cv2.resize(recorte, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        linhas = [
            Linha(l.x0 / 2 + cx0, l.y0 / 2 + cy0, l.x1 / 2 + cx0, l.y1 / 2 + cy0, l.texto, l.confianca)
            for l in ler_linhas(ampliado, motor)
        ]

        def dentro(l: Linha) -> bool:
            return x0 - 6 <= (l.x0 + l.x1) / 2 <= x1 + 6 and y0 - 6 <= (l.y0 + l.y1) / 2 <= y1 + 6

        linhas = [l for l in linhas if dentro(l)]
        try:
            linhas = [l for l in recuperar_linhas_perdidas(imagem, linhas, motor) if dentro(l)]
        except Exception:
            pass
        blocos = agrupar_linhas(linhas, ancora=MIN_CONFIANCA_AREA)
        if not blocos:
            raise ErroTraducao(
                "Não encontrei texto nessa área. Digite o texto original no campo e traduza mesmo assim."
            )
    traduzir_blocos(blocos, traduzir, ctx)
    for bloco in blocos:
        if bloco.traduzido:
            ajustar_ao_balao(imagem, bloco)
    return [bloco_para_dict(b) for b in blocos if b.traduzido]


class Motores:
    """Guarda o OCR e os tradutores já carregados (carregar leva segundos): usado pela edição no leitor."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ocr: Optional[MotorOCR] = None
        self._trad: Dict[Tuple[str, str, str, str], Any] = {}
        self.trabalho = threading.Lock()                       # uma edição de cada vez

    def ocr(self) -> MotorOCR:
        with self._lock:
            if self._ocr is None:
                exigir_dependencias("ocr")
                self._ocr = motor_ocr_padrao()
            return self._ocr

    def tradutor(self, de: str, para: str, informar: Callable[[str], None] = lambda _m: None) -> Any:
        chave = (de, para)
        with self._lock:
            if chave not in self._trad:
                self._trad[chave] = criar_motor_traducao(de, para, informar)
            return self._trad[chave]


@dataclass
class ResultadoTraducao:
    revisar: int = 0
    imagens: int = 0
    com_texto: int = 0
    blocos: int = 0
    falhas: List[Tuple[str, str]] = field(default_factory=list)
    arquivo: Optional[Path] = None


def _contar_blocos(arquivo: Path) -> Optional[int]:
    """Quantos trechos traduzidos há num traducao.json (None = ilegível)."""
    try:
        dados = json.loads(Path(arquivo).read_text(encoding="utf-8"))
        return sum(len(i.get("blocos", [])) for i in dados["imagens"].values())
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        return None


NOME_PARCIAL = "traducao.parcial.json"      # progresso salvo página a página (retomada)
NOME_ANTERIOR = "traducao.anterior.json"    # tradução antiga guardada enquanto a nova roda (volta se a nova falhar)
NOME_AVISO = "traducao.aviso.json"          # páginas que ficaram sem tradução (capítulo "incompleto")


def _gravar_json(destino: Path, dados: Dict[str, Any]) -> None:
    temp = destino.with_name(destino.name + ".tmp")
    temp.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temp, destino)


def _ler_json(arquivo: Path) -> Optional[Dict[str, Any]]:
    try:
        d = json.loads(arquivo.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and isinstance(d.get("imagens"), dict) else None
    except (OSError, ValueError):
        return None


def faltas_do_aviso(pasta: Path) -> List[str]:
    """Nomes das páginas sem tradução registradas para o capítulo (vazio se ele está completo)."""
    try:
        d = json.loads((Path(pasta) / NOME_AVISO).read_text(encoding="utf-8"))
        return [str(f["imagem"]) for f in d.get("falhas", []) if isinstance(f, dict) and "imagem" in f]
    except (OSError, ValueError, AttributeError):
        return []


def apagar_residuos(pasta: Path) -> None:
    """Remove progresso parcial, backup e aviso (ao excluir a tradução do capítulo)."""
    for n in (NOME_PARCIAL, NOME_ANTERIOR, NOME_AVISO):
        try:
            (Path(pasta) / n).unlink()
        except OSError:
            pass


def traduzir_pasta(
    pasta: Path,
    de: str = "en",
    para: str = "pt",
    informar: Callable[[str], None] = lambda _m: None,
    parar: Optional[threading.Event] = None,
    motor: Optional[MotorOCR] = None,
    traduzir: Optional[Any] = None,
    progresso: Callable[[int, int], None] = lambda _i, _n: None,
    refinar: bool = False,
    completar: bool = False,
) -> ResultadoTraducao:
    """Lê o texto de todas as imagens da pasta, traduz com contexto e grava `traducao.json` (e o leitor).

    Retomada: o progresso vai sendo salvo em `traducao.parcial.json`; se a execução for interrompida (cancelar, erro,
    fechar o programa), a próxima começa de onde parou (mesmo motor e idiomas). A tradução antiga fica guardada em
    `traducao.anterior.json` e só é apagada quando a nova é gravada; se a nova falhar, a antiga volta.
    `completar=True` refaz só as páginas que ficaram sem tradução, mantendo as demais.

    Duas fases: (1) OCR de todas as páginas; (2) com o capítulo inteiro em mãos, detecta nomes próprios
    (glossário automático) e traduz página a página, passando as falas anteriores como contexto.
    """
    if de not in IDIOMAS_ORIGEM or para not in IDIOMAS_DESTINO or de == para:
        raise ErroTraducao("Escolha idiomas de origem e de destino diferentes e suportados.")
    pasta = Path(pasta)
    if not pasta.is_dir():
        raise ErroTraducao(f"A pasta '{pasta}' não existe.")
    nomes = listar_imagens(pasta)
    if not nomes:
        raise ErroTraducao("Não há imagens nessa pasta.")

    if motor is None:
        exigir_dependencias("ocr" if traduzir is not None else "argos")
    if traduzir is None:
        traduzir = criar_motor_traducao(de, para, informar)
    if motor is None:
        informar("Carregando o leitor de texto (OCR)…")
        motor = motor_ocr_padrao()

    resultado = ResultadoTraducao()
    total = len(nomes) * 2
    destino = pasta / NOME_TRADUCAO
    parcial_arq, anterior_arq = pasta / NOME_PARCIAL, pasta / NOME_ANTERIOR
    origem_motor = getattr(traduzir, "origem", "argos")

    # ---- o que já está pronto: retomada de uma execução interrompida (ou, em "completar", as páginas já boas)
    prontas: Dict[str, Any] = {}                       # página -> info (já traduzida, inclusive as sem texto)
    sem_texto: set = set()
    base = None
    if completar:
        base = _ler_json(destino)
        faltas = set(faltas_do_aviso(pasta))
        if base is None or not faltas:
            raise ErroTraducao("Não há páginas sem tradução para completar neste capítulo.")
        for n in nomes:
            if n not in faltas:
                sem_texto.add(n)
        prontas = {n: v for n, v in base["imagens"].items() if n in nomes and n not in faltas}
        informar(f"Completando {len(faltas & set(nomes))} página(s) sem tradução; as outras ficam como estão.")
    else:
        sobra = _ler_json(parcial_arq)
        if sobra and sobra.get("de") == de and sobra.get("para") == para and sobra.get("motor") == origem_motor:
            feitas = [n for n in sobra.get("feitas", []) if n in nomes]
            if feitas:
                prontas = {n: v for n, v in sobra["imagens"].items() if n in feitas}
                sem_texto = {n for n in feitas if n not in prontas}
                informar(f"Retomando de onde parou: {len(feitas)} de {len(nomes)} página(s) já estavam traduzidas.")
        elif sobra is not None:
            informar("Havia um progresso parcial de outro motor/idioma; ele foi descartado.")
            parcial_arq.unlink(missing_ok=True)
    ja = set(prontas) | sem_texto

    if not completar and destino.is_file():                                   # traduzir de novo: a antiga sai do ar agora, mas fica guardada até a nova terminar
        try:
            os.replace(destino, anterior_arq)
            from baixador.biblioteca import acervo

            acervo.esquecer_versao()
            informar("Tradução anterior guardada; ela some quando a nova terminar (e volta se a nova falhar).")
        except OSError as erro:
            raise ErroTraducao(f"Não foi possível guardar a tradução anterior: {erro}") from None

    try:
        return _traduzir_paginas(pasta, nomes, de, para, informar, parar, motor, traduzir, progresso, refinar, resultado, total,
                                 destino, parcial_arq, origem_motor, prontas, sem_texto, ja, base, completar)
    except BaseException:
        if not completar and anterior_arq.is_file() and not destino.is_file():
            try:
                os.replace(anterior_arq, destino)
                from baixador.biblioteca import acervo

                acervo.esquecer_versao()
                informar("A tradução anterior foi restaurada.")
            except OSError:
                pass
        raise


def _traduzir_paginas(pasta, nomes, de, para, informar, parar, motor, traduzir, progresso, refinar, resultado, total,
                      destino, parcial_arq, origem_motor, prontas, sem_texto, ja, base, completar) -> ResultadoTraducao:
    lidas: Dict[str, List[Bloco]] = {}

    # ---- fase 1: ler o texto das páginas que ainda faltam
    for i, nome in enumerate(nomes, 1):
        if parar is not None and parar.is_set():
            raise Cancelado("Tradução cancelada.")
        progresso(i - 1, total)
        if nome in ja:
            continue
        try:
            lidas[nome] = ler_blocos(carregar_imagem(pasta_imagens(pasta) / nome), motor)
        except Cancelado:
            raise
        except Exception as erro:
            motivo = str(erro) if isinstance(erro, ErroTraducao) else erro.__class__.__name__
            resultado.falhas.append((nome, motivo))
            informar(f"[{i}/{len(nomes)}] {nome}: não consegui ler ({motivo}).")
            continue
        informar(f"[{i}/{len(nomes)}] {nome}: {len(lidas[nome])} trecho(s) de texto lido(s).")

    # ---- glossário automático (nomes próprios) + glossário e memória do usuário
    ctx = ia.contexto_da_pasta(pasta, de, para)
    todos = [b.original for bs in lidas.values() for b in bs]
    novos = ia.detectar_nomes(todos, de, sonda=None if getattr(traduzir, "lento", False) else traduzir)
    if novos:
        informar("Nomes detectados (serão mantidos): " + ", ".join(novos[:20]) + ("…" if len(novos) > 20 else ""))
        ia.salvar_nomes_auto(pasta, novos)
    ctx.nomes = sorted(set(ctx.nomes) | set(novos))

    # ---- fase 2: traduzir página a página, com contexto
    dados: Dict[str, Any] = {"versao": 1, "de": de, "para": para, "motor": origem_motor, "imagens": {}}
    if completar and base is not None:
        dados["motor"] = base.get("motor", origem_motor)
        if base.get("refino"):
            dados["refino"] = base["refino"]
    if refinar and not completar:
        dados["refino"] = {"estado": "pendente", "ts": int(time.time())}      # o leitor passa a acompanhar as trocas do Hy-MT2
    feitas_lista: List[str] = []
    for n in nomes:                                                           # restaura o que já estava pronto (na ordem das páginas)
        if n in prontas:
            dados["imagens"][n] = prontas[n]
            resultado.imagens += 1
            resultado.com_texto += 1
            resultado.blocos += len(prontas[n].get("blocos", []))
            feitas_lista.append(n)
        elif n in sem_texto:
            resultado.imagens += 1
            feitas_lista.append(n)
    ultimas = [(b.get("original", ""), b.get("traduzido", "")) for n in nomes if n in prontas for b in prontas[n].get("blocos", [])]
    ctx.anteriores = [(o, t) for o, t in ultimas if o and t][-8:]

    def salvar_parcial() -> None:
        if completar:
            return
        try:
            _gravar_json(parcial_arq, {**{k: v for k, v in dados.items() if k != "refino"}, "feitas": feitas_lista})
        except OSError:
            pass

    revisar = 0
    pendentes = [(i, n) for i, n in enumerate(nomes, 1) if n not in ja]
    rodada = 0
    while pendentes:
        adiadas: List[Tuple[int, str]] = []
        for i, nome in pendentes:
            if parar is not None and parar.is_set():
                raise Cancelado("Tradução cancelada.")
            progresso(len(nomes) + i - 1, total)
            blocos = lidas.get(nome)
            if blocos is None:
                continue
            try:
                if blocos:
                    traduzir_blocos(blocos, traduzir, ctx)
                info = finalizar_blocos(carregar_imagem(pasta_imagens(pasta) / nome), blocos)
            except hymt.MotorSobrecarregado as erro:                   # instabilidade passageira: não perde o capítulo, tenta a página de novo depois
                adiadas.append((i, nome))
                informar(f"[{i}/{len(nomes)}] {nome}: {erro} A página fica para uma nova tentativa.")
                continue
            except (Cancelado, hymt.IndisponivelMotor):
                raise
            except ErroTraducao as erro:
                resultado.falhas.append((nome, str(erro)))
                informar(f"[{i}/{len(nomes)}] {nome}: {erro}")
                continue
            except Exception as erro:
                resultado.falhas.append((nome, erro.__class__.__name__))
                informar(f"[{i}/{len(nomes)}] {nome}: falhou ({erro.__class__.__name__}).")
                continue
            resultado.imagens += 1
            if info["blocos"]:
                resultado.com_texto += 1
                resultado.blocos += len(info["blocos"])
                revisar += sum(1 for b in info["blocos"] if b.get("alertas"))
                dados["imagens"][nome] = info
            feitas_lista.append(nome)
            salvar_parcial()
            informar(f"[{i}/{len(nomes)}] {nome}: {len(info['blocos'])} trecho(s) traduzido(s).")
        if not adiadas:
            break
        rodada += 1
        if rodada > RODADAS_ADIADAS:
            for i, nome in adiadas:
                resultado.falhas.append((nome, "o tradutor ficou instável"))
            informar(f"{len(adiadas)} página(s) ficaram sem tradução porque o tradutor continuou instável. Use \"Completar páginas\" mais tarde.")
            break
        espera = 20 * rodada
        informar(f"{len(adiadas)} página(s) adiadas; nova tentativa em {espera} s…")
        if parar is not None and parar.wait(espera):
            raise Cancelado("Tradução cancelada.")
        pendentes = adiadas
    progresso(total, total)
    if revisar:
        informar(f"{revisar} trecho(s) merecem revisão (marcados no leitor, em Editar tradução).")
    resultado.revisar = revisar

    if resultado.falhas and resultado.blocos == 0:
        raise ErroTraducao(f"Nenhuma imagem foi traduzida ({len(resultado.falhas)} com falha); nada foi gravado. Tente de novo.")
    try:
        texto = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
        temporario = destino.with_name(destino.name + ".tmp")           # grava inteiro, confere e só então publica
        temporario.write_text(texto, encoding="utf-8")
        if _contar_blocos(temporario) != resultado.blocos:
            temporario.unlink(missing_ok=True)
            raise ErroTraducao("A nova tradução não passou na conferência e não foi gravada.")
        os.replace(temporario, destino)
        for n in (NOME_PARCIAL, NOME_ANTERIOR):                           # nova gravada: a antiga e o progresso parcial já não servem
            (pasta / n).unlink(missing_ok=True)
        if resultado.falhas:                                              # capítulo incompleto: a Biblioteca avisa e dá para completar
            _gravar_json_livre(pasta / NOME_AVISO, {"falhas": [{"imagem": n, "motivo": m} for n, m in resultado.falhas]})
        else:
            (pasta / NOME_AVISO).unlink(missing_ok=True)
    except OSError as erro:
        raise ErroTraducao(f"Não foi possível gravar a tradução: {erro}") from None
    resultado.arquivo = destino
    return resultado


def _gravar_json_livre(destino: Path, dados: Dict[str, Any]) -> None:
    destino.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------- tarefa em segundo plano (interface)

class _Parada:
    """Evento de parada composto: vale o cancelamento geral OU o do capítulo em andamento (cancelar um capítulo da fila)."""

    def __init__(self, geral: threading.Event, item: threading.Event) -> None:
        self._g, self._i = geral, item

    def is_set(self) -> bool:
        return self._g.is_set() or self._i.is_set()

    def wait(self, tempo: Optional[float] = None) -> bool:
        fim = None if tempo is None else time.monotonic() + tempo
        while not self.is_set():
            restante = None if fim is None else fim - time.monotonic()
            if restante is not None and restante <= 0:
                return False
            self._g.wait(0.1 if restante is None else min(0.1, restante))
        return True


class TarefaTraducao:
    """Uma tradução por vez, em thread própria, com andamento para a interface."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._parar = threading.Event()
        self._parar_item = threading.Event()
        self._pulados: set = set()
        self.estado = "ocioso"          # ocioso | executando | concluido | erro
        self.log: List[str] = []
        self.feitas = 0
        self.total = 0
        self.pasta: Optional[Path] = None
        self.erro: Optional[str] = None
        self.resumo: Optional[Dict[str, Any]] = None
        self.prontos = 0                # capítulos do lote já traduzidos, salvos e liberados para leitura
        self.capitulos = 0              # capítulos do lote
        self.itens: List[Dict[str, Any]] = []   # fila mostrada na aba Traduções: {nome, estado, feitas, total}
        self.inicio = 0.0               # quando a tradução atual começou (epoch) e quando terminou (0 enquanto roda)
        self.fim = 0.0
        self.modo = ""                  # motor escolhido ao iniciar (hibrido | argos | hy); mudar a configuração depois só vale na próxima
        self.fase = "traducao"          # traducao | refino (Hy-MT2 melhorando, em segundo plano, o que já pode ser lido)
        self.avisos: List[str] = []     # avisos para o usuário (ex.: Hy-MT2 indisponível, refinamento cancelado)
        self.refino_feitas = 0
        self.refino_total = 0

    @property
    def bloqueia_edicao(self) -> bool:
        """Editar no leitor só fica travado enquanto o Argos traduz; no refinamento, a edição do usuário sempre vence (CAS)."""
        return self.estado == "executando" and self.fase != "refino"

    def _zerar_modo(self, ganchos: Dict[str, Any]) -> Dict[str, Any]:
        """Chamado com a trava tomada: fixa o motor desta execução e limpa o andamento do refinamento."""
        ganchos = dict(ganchos)
        self.modo = ganchos.pop("modo", None) or config.motor()
        self.fase, self.avisos, self.refino_feitas, self.refino_total = "traducao", [], 0, 0
        return ganchos

    def iniciar(self, pasta: Path, de: str, para: str, **ganchos: Any) -> None:
        with self._lock:
            if self.estado == "executando":
                raise RuntimeError("Já existe uma tradução em andamento.")
            self.estado, self.log, self.feitas, self.total = "executando", [], 0, 0
            ganchos = self._zerar_modo(ganchos)
            self.prontos, self.capitulos = 0, 1
            self._abrir_fila([Path(pasta)])
            self.erro, self.resumo, self.pasta = None, None, Path(pasta)
            self._parar = threading.Event()
            self._parar_item, self._pulados = threading.Event(), set()
            self._thread = threading.Thread(target=self._rodar, args=(Path(pasta), de, para, ganchos, self.modo), daemon=True)
            self._thread.start()

    def iniciar_lote(self, pastas: List[Path], de: str, para: str, **ganchos: Any) -> None:
        """Traduz vários conjuntos em sequência, carregando os modelos uma única vez."""
        if not pastas:
            raise ErroTraducao("Nenhum conjunto para traduzir.")
        with self._lock:
            if self.estado == "executando":
                raise RuntimeError("Já existe uma tradução em andamento.")
            self.estado, self.log, self.feitas, self.total = "executando", [], 0, 0
            ganchos = self._zerar_modo(ganchos)
            self.prontos, self.capitulos = 0, len(pastas)
            self._abrir_fila([Path(p) for p in pastas])
            self.erro, self.resumo, self.pasta = None, None, Path(pastas[0])
            self._parar = threading.Event()
            self._parar_item, self._pulados = threading.Event(), set()
            self._thread = threading.Thread(
                target=self._rodar_lote, args=([Path(p) for p in pastas], de, para, ganchos, self.modo), daemon=True
            )
            self._thread.start()

    def iniciar_refino(self, pastas: List[Path], de: str = "en", para: str = "pt") -> int:
        """Botão "Refinar": melhora com o Hy-MT2 capítulos que já têm tradução (do Argos). Devolve quantos capítulos entram."""
        estado = hymt.verificar()
        if not estado["pronto"]:
            raise ErroTraducao(estado["mensagem"])
        alvos = [Path(p) for p in pastas if refino.pendentes(Path(p)) > 0]
        if not alvos:
            raise ErroTraducao("Nenhum capítulo traduzido precisa de refinamento.")
        with self._lock:
            if self.estado == "executando":
                raise RuntimeError("Já existe uma tradução em andamento.")
            self.estado, self.log, self.feitas, self.total = "executando", [], 0, 0
            self.modo, self.fase, self.avisos, self.refino_feitas, self.refino_total = "refino", "refino", [], 0, len(alvos)
            self.prontos, self.capitulos = len(alvos), len(alvos)
            self._abrir_fila(alvos)
            for it in self.itens:
                it["estado"] = "pronto"
            self.erro, self.resumo, self.pasta = None, None, alvos[0]
            self._parar = threading.Event()
            self._parar_item, self._pulados = threading.Event(), set()
            self._thread = threading.Thread(target=self._rodar_so_refino, args=(alvos, de, para), daemon=True)
            self._thread.start()
        return len(alvos)

    def _rodar_so_refino(self, pastas: List[Path], de: str, para: str) -> None:
        try:
            self._fase_refino(pastas, list(range(len(pastas))), de, para)
            with self._lock:
                self.estado, self.fase = "concluido", "traducao"
                self.resumo = {"imagens": 0, "com_texto": 0, "blocos": 0, "falhas": []}
        except Exception as erro:
            mensagem = f"Erro inesperado no refinamento ({erro.__class__.__name__})."
            with self._lock:
                self.estado, self.erro, self.fase = "erro", mensagem, "traducao"
            self._registrar(mensagem)
        finally:
            self._limpar_pendentes(pastas)

    @staticmethod
    def _nome_item(pasta: Path) -> str:
        return f"{pasta.parent.name} · {pasta.name}" if pasta.parent.name and pasta.parent != pasta else pasta.name

    def _abrir_fila(self, pastas: List[Path]) -> None:
        """Chamado com a trava já tomada: zera o cronômetro e monta a lista de capítulos da aba Traduções."""
        self.itens = [{"nome": self._nome_item(p), "rel": f"{p.parent.name}/{p.name}", "estado": "fila", "feitas": 0, "total": 0} for p in pastas]
        self.inicio, self.fim = time.time(), 0.0

    def _item(self, indice: int, **campos: Any) -> None:
        with self._lock:
            if 0 <= indice < len(self.itens):
                self.itens[indice].update(campos)

    def _encerrar_fila(self, pendente: str) -> None:
        """Fim da execução (qualquer desfecho): o que não chegou a ser traduzido fica com o estado `pendente`."""
        with self._lock:
            for it in self.itens:
                if it["estado"] in ("fila", "traduzindo"):
                    it["estado"] = pendente
            self.fim = time.time()

    def _preparar_modo(self, modo: str, ganchos: Dict[str, Any], de: str = "en", para: str = "pt") -> bool:
        """Confere o Ollama conforme o modo. Devolve se haverá refinamento pelo Hy-MT2.

        - somente Hy-MT2: indisponível = erro claro (não há plano B silencioso) e o Hy vira o tradutor principal;
        - híbrido: indisponível = aviso, e o Argos segue sozinho (o leitor não fica sem tradução);
        - somente Argos: o Ollama nem é consultado.
        """
        if modo == "argos":
            return False
        if modo == "gemini":
            g = gemini.verificar()
            if not g["pronto"]:
                raise ErroTraducao(g["mensagem"])
            ganchos["traduzir"] = gemini.TradutorGemini(de, para, parar=self.parada)
            return False
        if modo == "openrouter":
            o = openrouter.verificar()
            if not o["pronto"]:
                raise ErroTraducao(o["mensagem"])
            ganchos["traduzir"] = openrouter.TradutorOpenRouter(de, para, parar=self.parada)
            return False
        estado = hymt.verificar()
        if modo in ("hy", "hy_pagina"):
            if not estado["pronto"]:
                raise ErroTraducao(estado["mensagem"])
            classe = hymt.TradutorHyPagina if modo == "hy_pagina" else hymt.TradutorHy
            ganchos["traduzir"] = classe(de, para, parar=self.parada)
            return False
        if not estado["pronto"]:
            self._aviso(f"Híbrido sem o Hy-MT2: {estado['mensagem']} A tradução do Argos foi feita normalmente.")
            return False
        return True

    def _aviso(self, texto: str) -> None:
        with self._lock:
            if texto not in self.avisos:
                self.avisos.append(texto)
        self._registrar(texto)

    def _fase_refino(self, pastas: List[Path], indices: List[int], de: str, para: str) -> None:
        """Hy-MT2 melhora, capítulo a capítulo, o que o Argos já entregou. Nunca derruba a tradução rápida."""
        if not pastas:
            return
        with self._lock:
            self.fase, self.refino_feitas, self.refino_total = "refino", 0, len(pastas)
            self.fim = 0.0
            for k in indices:
                self.itens[k]["refino"] = "fila"
        self._registrar("Refinando com o Hy-MT2 em segundo plano (você já pode ler a tradução do Argos)…")
        hy = hymt.TradutorHy(de, para, parar=self._parar)
        for n, (pasta, k) in enumerate(zip(pastas, indices)):
            try:
                if self._parar.is_set():
                    raise Cancelado("Refinamento cancelado.")
                self._item(k, refino="refinando")
                refino.refinar_pasta(
                    pasta, hy, de, para, parar=self._parar, informar=self._registrar,
                    progresso=lambda f, t, k=k: self._item(k, rfeitas=f, rtotal=t),
                )
                self._item(k, refino="pronto")
                with self._lock:
                    self.refino_feitas = n + 1
            except Cancelado:
                for kk in indices[n:]:
                    self._item(kk, refino="cancelado")
                self._aviso("Refinamento cancelado: a tradução do Argos foi mantida onde o Hy-MT2 ainda não tinha chegado.")
                break
            except hymt.IndisponivelHy as erro:
                for kk in indices[n:]:
                    self._item(kk, refino="indisponivel")
                self._aviso(f"Refinamento interrompido: {erro} A tradução do Argos foi mantida.")
                break
            except Exception as erro:
                self._item(k, refino="falhou")
                self._registrar(f"Refinamento de {pasta.name} falhou ({erro.__class__.__name__}); a tradução do Argos foi mantida.")
        with self._lock:
            self.fim = time.time()

    def _rodar_lote(self, pastas: List[Path], de: str, para: str, ganchos: Dict[str, Any], modo: str = "argos") -> None:
        try:
            refinar = self._preparar_modo(modo, ganchos, de, para)
            motor, traduzir = ganchos.get("motor"), ganchos.get("traduzir")
            if motor is None:
                exigir_dependencias("ocr" if traduzir is not None else "argos")
            if traduzir is None:
                traduzir = criar_motor_traducao(de, para, self._registrar)
            if motor is None:
                self._registrar("Carregando o leitor de texto (OCR)…")
                motor = motor_ocr_padrao()
            contagens = [len(listar_imagens(p)) for p in pastas]
            contagens = [2 * c for c in contagens]               # duas fases por imagem (ler e traduzir)
            total, base = sum(contagens), 0
            imagens = com_texto = blocos = 0
            falhas: List[Dict[str, str]] = []
            prontas: List[Path] = []
            indices: List[int] = []
            for indice, (pasta, n) in enumerate(zip(pastas, contagens)):
                if self._parar.is_set():
                    raise Cancelado("Tradução cancelada.")
                with self._lock:
                    if indice in self._pulados:                   # cancelado da fila antes de começar
                        base += n
                        continue
                    self._parar_item.clear()
                self._registrar(f"== {pasta.name} ({n // 2} imagem(ns)) ==")
                if n == 0:
                    self._item(indice, estado="pronto")
                    continue
                self._item(indice, estado="traduzindo", total=n)
                try:
                    r = traduzir_pasta(
                        pasta, de, para, informar=self._registrar, parar=self.parada, motor=motor,
                        traduzir=traduzir, refinar=refinar,
                        progresso=lambda i, _t, b=base, k=indice: (self._progresso(b + i, total), self._item(k, feitas=i)),
                    )
                except Cancelado:
                    if self._parar.is_set():
                        raise
                    self._registrar(f"{pasta.name}: cancelado; a fila continua.")        # só este capítulo
                    self._item(indice, estado="cancelado")
                    with self._lock:
                        self.capitulos = max(0, self.capitulos - 1)
                    self._parar_item.clear()
                    base += n
                    continue
                except ErroTraducao as erro:
                    self._registrar(f"{pasta.name}: {erro}")
                    falhas.append({"imagem": pasta.name, "motivo": str(erro)})
                    self._item(indice, estado="falhou", motivo=str(erro))
                    base += n
                    continue
                base += n
                self._item(indice, estado="pronto", feitas=n)
                self._liberar(pasta)                         # este capítulo já pode ser lido; os próximos seguem em segundo plano
                prontas.append(pasta)
                indices.append(indice)
                imagens, com_texto, blocos = imagens + r.imagens, com_texto + r.com_texto, blocos + r.blocos
                falhas += [{"imagem": f"{pasta.name}/{a}", "motivo": m} for a, m in r.falhas]
            self._progresso(total, total)
            self._encerrar_fila("cancelado")
            if refinar:
                self._fase_refino(prontas, indices, de, para)
            with self._lock:
                self.estado = "concluido"
                self.fase = "traducao"
                self.resumo = {"imagens": imagens, "com_texto": com_texto, "blocos": blocos, "falhas": falhas}
            self._registrar(f"Concluído: {blocos} trecho(s) traduzido(s) em {com_texto} imagem(ns), {len(pastas)} conjunto(s).")
        except Cancelado:
            self._encerrar_fila("cancelado")
            with self._lock:
                self.estado, self.erro = "erro", "Tradução cancelada."
        except ErroBaixador as erro:
            self._encerrar_fila("falhou")
            with self._lock:
                self.estado, self.erro = "erro", str(erro)
            self._registrar(str(erro))
        except hymt.IndisponivelMotor as erro:
            self._encerrar_fila("falhou")
            with self._lock:
                self.estado, self.erro = "erro", str(erro)
            self._registrar(str(erro))
        except Exception as erro:
            self._encerrar_fila("falhou")
            mensagem = f"Erro inesperado ({erro.__class__.__name__})."
            with self._lock:
                self.estado, self.erro = "erro", mensagem
            self._registrar(mensagem)
        finally:
            self._limpar_pendentes(pastas)

    @staticmethod
    def _limpar_pendentes(pastas: List[Path]) -> None:
        """Nenhum capítulo fica marcado como "refinando" depois que a execução acaba (o leitor para de esperar)."""
        for p in pastas:
            refino.marcar(p, "cancelado", so_se=refino.ATIVOS)

    def _liberar(self, pasta: Path) -> None:
        """Capítulo traduzido e salvo: a biblioteca (notebook e celular) passa a vê-lo agora, sem esperar o resto do lote."""
        from baixador.biblioteca import acervo as biblioteca

        biblioteca.esquecer_versao()
        with self._lock:
            self.prontos += 1
            prontos, total = self.prontos, self.capitulos
        self._registrar(f"✔ {pasta.name} traduzido e liberado para leitura ({prontos}/{total}).")

    def parar(self) -> None:
        self._parar.set()

    @property
    def parada(self) -> "_Parada":
        return _Parada(self._parar, self._parar_item)

    def cancelar_item(self, rel: str) -> str:
        """Cancela SÓ um capítulo da fila: "fila" (nunca começa) ou "traduzindo" (para este e segue para o próximo).
        Devolve "fila", "andamento" ou "" (não está na fila / já terminou / execução de refino)."""
        with self._lock:
            if self.estado != "executando" or self.fase != "traducao" or self._parar.is_set():
                return ""
            for k, it in enumerate(self.itens):
                if it.get("rel") != rel:
                    continue
                if it["estado"] == "fila":
                    it["estado"] = "cancelado"
                    self._pulados.add(k)
                    self.capitulos = max(0, self.capitulos - 1)
                    return "fila"
                if it["estado"] == "traduzindo" and len(self.itens) > 1:
                    self._parar_item.set()
                    return "andamento"
        return ""

    def _registrar(self, mensagem: str) -> None:
        with self._lock:
            if len(self.log) < 2000:
                self.log.append(mensagem)
        if mensagem.startswith(("Erro", "A tradução", "Não foi possível")):
            print(f"[tradução] {mensagem}", file=sys.stderr, flush=True)

    def _progresso(self, feitas: int, total: int) -> None:
        with self._lock:
            self.feitas, self.total = feitas, total

    def _rodar(self, pasta: Path, de: str, para: str, ganchos: Dict[str, Any], modo: str = "argos") -> None:
        try:
            refinar = self._preparar_modo(modo, ganchos, de, para)
            self._item(0, estado="traduzindo")
            r = traduzir_pasta(
                pasta, de, para, informar=self._registrar, parar=self._parar, refinar=refinar,
                progresso=lambda i, t: (self._progresso(i, t), self._item(0, feitas=i, total=t)), **ganchos,
            )
            resumo = {
                "imagens": r.imagens, "com_texto": r.com_texto, "blocos": r.blocos,
                "falhas": [{"imagem": n, "motivo": m} for n, m in r.falhas],
            }
            self._liberar(pasta)
            self._item(0, estado="pronto")
            self._encerrar_fila("pronto")
            if refinar:
                self._fase_refino([pasta], [0], de, para)
            with self._lock:
                self.estado, self.resumo, self.fase = "concluido", resumo, "traducao"
            self._registrar(f"Concluído: {r.blocos} trecho(s) traduzido(s) em {r.com_texto} imagem(ns).")
        except Cancelado:
            self._encerrar_fila("cancelado")
            with self._lock:
                self.estado, self.erro = "erro", "Tradução cancelada."
        except ErroBaixador as erro:
            self._encerrar_fila("falhou")
            with self._lock:
                self.estado, self.erro = "erro", str(erro)
            self._registrar(str(erro))
        except hymt.IndisponivelMotor as erro:
            self._encerrar_fila("falhou")
            with self._lock:
                self.estado, self.erro = "erro", str(erro)
            self._registrar(str(erro))
        except ModuleNotFoundError as erro:
            mensagem = (
                f"Falta o pacote Python '{erro.name}'. Com o .venv ativado, rode: "
                "pip install -r requirements-traducao.txt"
            )
            with self._lock:
                self.estado, self.erro = "erro", mensagem
            self._registrar(mensagem)
        except Exception as erro:
            traceback.print_exc()
            mensagem = f"Erro inesperado ({erro.__class__.__name__}: {str(erro)[:160]})."
            self._encerrar_fila("falhou")
            with self._lock:
                self.estado, self.erro = "erro", mensagem
            self._registrar(mensagem)
        finally:
            self._limpar_pendentes([pasta])

    def instantaneo(self, desde_log: int = 0) -> Dict[str, Any]:
        with self._lock:
            return {
                "estado": self.estado, "erro": self.erro, "feitas": self.feitas, "total": self.total,
                "log": self.log[desde_log:], "log_total": len(self.log), "resumo": self.resumo,
                "prontos": self.prontos, "capitulos": self.capitulos,
                "modo": self.modo, "fase": self.fase, "cancelando": self.estado == "executando" and self._parar.is_set(), "avisos": list(self.avisos),
                "refino_feitas": self.refino_feitas, "refino_total": self.refino_total,
                "itens": [dict(i) for i in self.itens], "inicio": self.inicio, "fim": self.fim, "agora": time.time(),
                "dependencias": disponibilidade(),
            }
