"""Capítulos da biblioteca: varredura das pastas e os dados que o leitor global precisa para mostrar um capítulo.

O programa NÃO gera mais um `leitor.html` por capítulo. Existe um único leitor (`web/leitor/`) que pede ao servidor
os dados do capítulo escolhido (`dados_do_capitulo`) e monta a página no navegador.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from baixador.biblioteca import organizacao as org
from baixador.nucleo.imagens import detectar_formato

NOME_TRADUCAO = "traducao.json"
NOME_AVISO = "traducao.aviso.json"
NOME_IMG = "img"                                     # as imagens do capítulo ficam em Capítulo/img/; os .json ficam na raiz do capítulo
EXTENSOES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp"}
MAX_IMAGENS = 5000
MAX_BLOCOS_POR_IMAGEM = 200


def _natural(nome: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", nome)]


def pasta_imagens(pasta: Path) -> Path:
    """Onde estão as imagens do capítulo: `pasta/img` (padrão) ou, em pastas antigas ainda não migradas, a própria pasta."""
    pasta = Path(pasta)
    sub = pasta / NOME_IMG
    return sub if sub.is_dir() and not sub.is_symlink() else pasta


def listar_imagens(pasta: Path) -> List[str]:
    """Nomes das imagens do capítulo (em `img/`, ou na própria pasta no formato antigo), em ordem natural (001, 002, ..., 010).
    Confere o conteúdo, não só a extensão. Os arquivos estão em `pasta_imagens(pasta) / nome`."""
    nomes: List[str] = []
    try:
        entradas = list(pasta_imagens(pasta).iterdir())
    except OSError:
        return []
    for entrada in entradas:
        if entrada.suffix.lower() not in EXTENSOES or entrada.is_symlink():
            continue
        try:
            if not entrada.is_file():
                continue
            with open(entrada, "rb") as arquivo:
                cabecalho = arquivo.read(32)
            detectar_formato(cabecalho)
        except Exception:
            continue
        nomes.append(entrada.name)
    nomes.sort(key=_natural)
    return nomes[:MAX_IMAGENS]


def _subpastas(pasta: Path) -> List[Path]:
    try:
        return sorted(p for p in pasta.iterdir() if p.is_dir() and not p.is_symlink() and not p.name.startswith(".") and p.name != NOME_IMG)
    except OSError:
        return []


def _paginas_sem_traducao(pasta: Path) -> int:
    """Quantas páginas ficaram sem tradução na última tradução do capítulo (0 = completo)."""
    try:
        d = json.loads((pasta / NOME_AVISO).read_text(encoding="utf-8"))
        return len({str(f["imagem"]) for f in d.get("falhas", []) if isinstance(f, dict) and "imagem" in f})
    except (OSError, ValueError, AttributeError, TypeError):
        return 0


def _varrer(raiz: Path) -> List[Dict[str, Any]]:
    """Capítulos da biblioteca: pastas com imagens direto na raiz (formato antigo) e dentro de obras (raiz/Obra/Cap)."""
    raiz = Path(raiz)
    achados: List[Dict[str, Any]] = []
    for sub in _subpastas(raiz):
        nomes = [n for n in listar_imagens(sub) if Path(n).stem.lower() != "capa"]   # `capa.*` é a capa da obra, não uma página
        if nomes:                                            # conjunto no formato antigo (um capítulo por pasta)
            d = org.descrever_capitulo(sub)
            achados.append({"pasta": sub, "rel": sub.name, "nomes": nomes, "antigo": True, **d})
            continue
        for cap in _subpastas(sub):
            nomes = listar_imagens(cap)
            if nomes:
                d = org.descrever_capitulo(cap, sub.name)
                d["obra"] = d["obra"] or sub.name
                achados.append({"pasta": cap, "rel": f"{sub.name}/{cap.name}", "nomes": nomes, "antigo": False, **d})
    for a in achados:
        a["traduzido"] = (a["pasta"] / NOME_TRADUCAO).is_file()
        a["incompleta"] = _paginas_sem_traducao(a["pasta"]) if a["traduzido"] else 0
        try:
            a["quando"] = a["pasta"].stat().st_mtime
        except OSError:
            a["quando"] = 0.0
    return achados


# --------------------------------------------------------------------------- dados para o leitor global

def refinando(pasta: Path) -> bool:
    """O Hy-MT2 ainda está melhorando a tradução deste capítulo? (o leitor consulta de novo enquanto for verdade)"""
    try:
        r = json.loads((pasta / NOME_TRADUCAO).read_text(encoding="utf-8")).get("refino")
        return isinstance(r, dict) and r.get("estado") in ("pendente", "refinando")
    except (OSError, ValueError, AttributeError):
        return False


def _ler_traducao(pasta: Path) -> dict:
    """Lê traducao.json (gerado por traducao/pipeline.py). Qualquer problema no arquivo = sem tradução."""
    try:
        dados = json.loads((pasta / NOME_TRADUCAO).read_text(encoding="utf-8"))
        imagens = dados["imagens"]
        return imagens if isinstance(imagens, dict) else {}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


_COR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _blocos(info: object) -> List[Dict[str, Any]]:
    """Trechos traduzidos de uma imagem, validados (o JSON em disco é dado, não confiável). Posições em % da imagem."""
    try:
        largura, altura = float(info["w"]), float(info["h"])  # type: ignore[index]
        blocos = info["blocos"]  # type: ignore[index]
        if largura <= 0 or altura <= 0 or not isinstance(blocos, list):
            return []
    except (KeyError, TypeError, ValueError):
        return []
    saida: List[Dict[str, Any]] = []
    for indice, b in enumerate(blocos[:MAX_BLOCOS_POR_IMAGEM]):
        try:
            x, y, w, h = (float(b[k]) for k in ("x", "y", "w", "h"))
            texto = str(b["traduzido"])[:1200]
            fundo = b["fundo"] if isinstance(b.get("fundo"), str) and _COR.match(b["fundo"]) else "#ffffff"
            cor = b["cor"] if isinstance(b.get("cor"), str) and _COR.match(b["cor"]) else "#111111"
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if w <= 0 or h <= 0 or not texto.strip():
            continue
        try:
            fonte = float(b["fonte"]) if b.get("fonte") else 0.0
        except (TypeError, ValueError):
            fonte = 0.0
        alertas = b.get("alertas")
        livre = None
        try:                                                   # miolo livre do balão (px da imagem → %), só se contiver a caixa
            lv = [float(v) for v in b["livre"]] if isinstance(b.get("livre"), list) and len(b["livre"]) == 4 else None
            if lv and lv[2] > 0 and lv[3] > 0 and lv[0] <= x + 1 and lv[1] <= y + 1 and lv[0] + lv[2] >= x + w - 1 and lv[1] + lv[3] >= y + h - 1:
                livre = [round(lv[0] / largura * 100, 3), round(lv[1] / altura * 100, 3), round(lv[2] / largura * 100, 3), round(lv[3] / altura * 100, 3)]
        except (TypeError, ValueError):
            livre = None
        try:
            refer = float(b.get("refer") or 0)
        except (TypeError, ValueError):
            refer = 0.0
        saida.append({
            "i": indice,
            "x": round(x / largura * 100, 3), "y": round(y / altura * 100, 3),
            "w": round(w / largura * 100, 3), "h": round(h / altura * 100, 3),
            "fundo": fundo, "cor": cor, "texto": texto, "original": str(b.get("original", ""))[:600],
            "fonte": round(fonte, 1) if 4 <= fonte <= 600 else 0,
            "livre": livre, "refer": round(refer, 1) if 3 <= refer <= 600 else 0,
            "alerta": "; ".join(str(a)[:80] for a in alertas[:5]) if isinstance(alertas, list) and alertas else "",
        })
    return saida


def pasta_do_capitulo(raiz: Path, rel: str) -> Optional[Path]:
    """`Obra/Cap 001` → pasta real, só se for um capítulo (pasta com imagens) dentro da biblioteca."""
    if not rel or len(rel) > 400 or "\x00" in rel:
        return None
    try:
        raiz = Path(raiz).resolve(strict=True)
        pasta = (raiz / rel.strip("/\\")).resolve(strict=True)
    except (OSError, ValueError, RuntimeError):
        return None
    if pasta == raiz or not pasta.is_relative_to(raiz) or not pasta.is_dir() or pasta.name.startswith("."):
        return None
    return pasta


def dados_do_capitulo(raiz: Path, rel: str) -> Optional[Dict[str, Any]]:
    """Tudo que o leitor global precisa de um capítulo: título e, para cada imagem, nome, medidas e trechos traduzidos."""
    pasta = pasta_do_capitulo(raiz, rel)
    if pasta is None:
        return None
    nomes = listar_imagens(pasta)
    if not nomes:
        return None
    raiz_r = Path(raiz).resolve()
    partes = pasta.relative_to(raiz_r).parts
    obra = partes[0] if len(partes) == 2 else None
    d = org.descrever_capitulo(pasta, obra)
    rotulo = org.rotulo_capitulo(d["numero"], d["titulo"])
    nome_obra = d["obra"] or obra or ""
    traducao = _ler_traducao(pasta)
    imagens = []
    for n, nome in enumerate(nomes, 1):
        info = traducao.get(nome)
        blocos = _blocos(info) if info else []
        medidas = None
        if blocos:
            try:
                medidas = [round(float(info["w"])), round(float(info["h"]))]  # type: ignore[index]
            except (KeyError, TypeError, ValueError):
                blocos = []
        imagens.append({"n": n, "arq": nome, "medidas": medidas, "blocos": blocos})
    return {
        "rel": "/".join(partes), "obra": nome_obra, "rotulo": rotulo,
        "titulo": f"{nome_obra} — {rotulo}" if nome_obra else rotulo or pasta.name,
        "imagens": imagens, "refinando": refinando(pasta),
        "sub": NOME_IMG + "/" if pasta_imagens(pasta) != pasta else "",     # prefixo das imagens dentro de `base`
    }
