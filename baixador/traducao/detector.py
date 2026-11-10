"""Detector de balões (opcional): acha balões de fala, texto em balão e texto livre na página.

Modelo: RT-DETR v2 em ONNX, `ogkalu/comic-text-and-bubble-detector` (licença Apache-2.0), treinado em ~11 mil páginas de
mangá, webtoon, manhua e quadrinho ocidental. Baixado UMA vez para `dados/modelos/` na primeira tradução; depois roda offline.

Tudo aqui é um extra: qualquer falha (sem internet, sem onnxruntime, modelo corrompido, saída inesperada) devolve lista
vazia e a tradução segue com o método por cor de fundo de sempre. Desligar: `detector_balao=0` no .env.
"""

from __future__ import annotations

import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from baixador import configuracao
from baixador.traducao import ambiente

ARQUIVO = "detector_int8.onnx"                               # 43,8 MB (a versão float32 tem 168 MB)
URL = "https://huggingface.co/ogkalu/comic-text-and-bubble-detector/resolve/main/" + ARQUIVO
PASTA = configuracao.DADOS / "modelos"
CLASSES = {0: "balao", 1: "texto_balao", 2: "texto_livre"}
LIMIAR = 0.35
LADO = 640                                                   # tamanho de treino do modelo
REPETIR_APOS = 600.0                                         # depois de uma falha, só tenta de novo daqui a 10 min

_trava = threading.Lock()
_sessao: Optional["Detector"] = None
_falhou_em = 0.0
ultimo_erro = ""                                             # texto curto, nunca com segredo


def ativo() -> bool:
    return ambiente.ler_env().get("detector_balao", "1").strip().lower() not in ("0", "nao", "não", "off", "false", "desligado")


def _baixar(destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_suffix(".part")
    try:
        with urllib.request.urlopen(URL, timeout=60) as r, open(parcial, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            while True:
                pedaco = r.read(1 << 20)
                if not pedaco:
                    break
                f.write(pedaco)
        if parcial.stat().st_size < 1_000_000 or (total and parcial.stat().st_size != total):
            raise OSError("download incompleto")
        parcial.replace(destino)
    finally:
        parcial.unlink(missing_ok=True)


def decodificar(saidas: Dict[str, Any], W: int, H: int, limiar: float = LIMIAR, tamanho_dado: bool = True) -> List[Dict[str, Any]]:
    """Saída crua do ONNX -> [{classe, box:[x0,y0,x1,y1], score}] em pixels. Aceita (labels, boxes, scores) ou (logits, pred_boxes)."""
    import numpy as np

    nomes = {k.lower(): np.asarray(v) for k, v in saidas.items()}
    if {"labels", "boxes", "scores"} <= set(nomes):
        labels = nomes["labels"].reshape(-1)
        scores = nomes["scores"].reshape(-1)
        boxes = nomes["boxes"].reshape(-1, 4).astype(np.float32)
        if not tamanho_dado:
            if boxes.size and boxes.max() <= 1.5:
                boxes = boxes * np.array([W, H, W, H], dtype=np.float32)
            else:
                boxes = boxes * np.array([W / LADO, H / LADO, W / LADO, H / LADO], dtype=np.float32)
    elif "logits" in nomes and "pred_boxes" in nomes:
        logits = nomes["logits"]
        p = 1.0 / (1.0 + np.exp(-logits.reshape(-1, logits.shape[-1])))
        scores, labels = p.max(1), p.argmax(1)
        cx, cy, w, h = nomes["pred_boxes"].reshape(-1, 4).T
        boxes = np.stack([(cx - w / 2) * W, (cy - h / 2) * H, (cx + w / 2) * W, (cy + h / 2) * H], 1)
    else:
        raise RuntimeError("formato de saída do detector desconhecido: " + ", ".join(f"{k}{tuple(v.shape)}" for k, v in nomes.items()))
    saida = []
    for lab, sc, b in zip(labels, scores, boxes):
        if float(sc) < limiar or int(lab) not in CLASSES:
            continue
        x0, x1 = (max(0.0, min(float(W), float(v))) for v in (b[0], b[2]))
        y0, y1 = (max(0.0, min(float(H), float(v))) for v in (b[1], b[3]))
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        saida.append({"classe": CLASSES[int(lab)], "box": [x0, y0, x1, y1], "score": round(float(sc), 3)})
    return saida


def _iou(a: List[float], b: List[float]) -> float:
    iw, ih = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def _sem_repetidas(itens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pedaços vizinhos se sobrepõem: a mesma caixa aparece duas vezes; fica a de maior confiança."""
    mantidos: List[Dict[str, Any]] = []
    for it in sorted(itens, key=lambda i: -i["score"]):
        if not any(m["classe"] == it["classe"] and _iou(m["box"], it["box"]) > 0.5 for m in mantidos):
            mantidos.append(it)
    return mantidos


def pedacos(altura: int, largura: int) -> List[int]:
    """Início (y) de cada pedaço. Página alta (webtoon) é fatiada na vertical, como no treino do modelo; 15% de sobreposição.
    shortcut: o tamanho do pedaço (1,5x a largura) é palpite; ajuste se cortar balões demais."""
    alto = int(largura * 1.5)
    if altura <= alto * 1.2:
        return [0]
    passo = int(alto * 0.85)
    inicios = list(range(0, altura - alto, passo))
    inicios.append(altura - alto)
    return inicios


class Detector:
    def __init__(self, caminho: Path) -> None:
        import onnxruntime as ort

        self.sess = ort.InferenceSession(str(caminho), providers=["CPUExecutionProvider"])
        self.entradas = self.sess.get_inputs()
        self.saidas = [o.name for o in self.sess.get_outputs()]
        self.tem_tamanho = any("size" in i.name.lower() for i in self.entradas)

    def _um(self, rgb) -> List[Dict[str, Any]]:
        import cv2
        import numpy as np

        H, W = rgb.shape[:2]
        feed: Dict[str, Any] = {}
        for inp in self.entradas:
            if "size" in inp.name.lower():
                tipo = np.int64 if "int64" in inp.type else (np.int32 if "int32" in inp.type else np.float32)
                feed[inp.name] = np.array([[W, H]], dtype=tipo)
            else:
                forma = inp.shape
                lh = forma[2] if len(forma) == 4 and isinstance(forma[2], int) else LADO
                lw = forma[3] if len(forma) == 4 and isinstance(forma[3], int) else LADO
                x = cv2.resize(rgb, (lw, lh), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255.0
                feed[inp.name] = x.transpose(2, 0, 1)[None]
        return decodificar(dict(zip(self.saidas, self.sess.run(None, feed))), W, H, LIMIAR, self.tem_tamanho)

    def detectar(self, imagem_bgr) -> List[Dict[str, Any]]:
        rgb = imagem_bgr[:, :, ::-1]
        altura, largura = rgb.shape[:2]
        todos: List[Dict[str, Any]] = []
        alto = int(largura * 1.5)
        for y in pedacos(altura, largura):
            corte = rgb[y:y + alto] if altura > alto * 1.2 else rgb
            for it in self._um(corte.copy()):
                it["box"][1] += y
                it["box"][3] += y
                todos.append(it)
        return _sem_repetidas(todos)


def _carregar() -> Optional[Detector]:
    global _sessao, _falhou_em, ultimo_erro
    with _trava:
        if _sessao is not None:
            return _sessao
        if _falhou_em and time.monotonic() - _falhou_em < REPETIR_APOS:
            return None
        try:
            caminho = PASTA / ARQUIVO
            if not (caminho.is_file() and caminho.stat().st_size > 1_000_000):
                _baixar(caminho)
            try:
                _sessao = Detector(caminho)
            except Exception:
                caminho.unlink(missing_ok=True)              # arquivo corrompido: baixa de novo na próxima vez
                raise
            ultimo_erro = ""
        except Exception as erro:  # noqa: BLE001 - extra opcional: nunca derruba a tradução
            _falhou_em = time.monotonic()
            ultimo_erro = f"{type(erro).__name__}: {str(erro)[:160]}"
            return None
        return _sessao


def detectar(imagem_bgr) -> List[Dict[str, Any]]:
    """Caixas encontradas na página ([] se desligado ou se algo falhar)."""
    if not ativo():
        return []
    det = _carregar()
    if det is None:
        return []
    try:
        return det.detectar(imagem_bgr)
    except Exception as erro:  # noqa: BLE001
        global ultimo_erro
        ultimo_erro = f"{type(erro).__name__}: {str(erro)[:160]}"
        return []
