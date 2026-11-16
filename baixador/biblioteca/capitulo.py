"""Capítulos da biblioteca: varredura das pastas e os dados que o leitor global precisa para mostrar um capítulo.

O programa NÃO gera mais um `leitor.html` por capítulo. Existe um único leitor (`web/leitor/`) que pede ao servidor
os dados do capítulo escolhido (`dados_do_capitulo`) e monta a página no navegador.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from baixador.biblioteca import organizacao as org
from baixador.nucleo.imagens import detectar_formato
from baixador.traducao import legado

NOME_TRADUCAO = "traducao.json"
PASTA_LIMPEZA = "traducao/limpeza/"                   # PNG (por página) com o texto original apagado, dentro do capítulo
NOME_IMG = "img"                                     # as imagens do capítulo ficam em Capítulo/img/; os .json ficam na raiz do capítulo
EXTENSOES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp"}
MAX_IMAGENS = 5000
MAX_FALAS_POR_IMAGEM = 200
MAX_BALOES_POR_IMAGEM = 200


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


_CONTAGENS = re.compile(rb'"counts"\s*:\s*(\{[^{}]*\})')


def _contagens(pasta: Path) -> Dict[str, int]:
    """{"ok": n, "revisar": n, "erro": n, ...} do traducao.json novo, lendo só o começo do arquivo (o campo vem antes das páginas)."""
    try:
        with (pasta / NOME_TRADUCAO).open("rb") as f:
            achado = _CONTAGENS.search(f.read(8192))
        bruto = json.loads(achado.group(1)) if achado else {}
        return {str(k): int(v) for k, v in bruto.items() if isinstance(v, (int, float))}
    except (OSError, ValueError, TypeError):
        return {}


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
        a["traduzido"] = legado.traducao_nova(a["pasta"] / NOME_TRADUCAO)       # só o formato novo conta como traduzido
        c = _contagens(a["pasta"]) if a["traduzido"] else {}
        a["incompleta"] = c.get("erro", 0)                    # falas que o motor não conseguiu traduzir
        a["revisar"] = c.get("revisar", 0)                    # falas que a tradução ou o OCR marcaram para revisão
        try:
            a["quando"] = a["pasta"].stat().st_mtime
        except OSError:
            a["quando"] = 0.0
    return achados


# --------------------------------------------------------------------------- dados para o leitor global

_COR = re.compile(r"^#[0-9a-fA-F]{6}$")
_PNG = re.compile(r"^[A-Za-z0-9_.-]{1,80}\.png$")
MODOS_ESCRITOS = ("balao", "narracao", "texto")              # falas que o sistema reescreveu na imagem (as demais só têm tooltip)


def _ler_traducao(pasta: Path) -> Optional[Dict[str, Any]]:
    """Lê traducao.json (gerado pelo tradutor em Node). Arquivo ausente, antigo ou quebrado = sem tradução."""
    arquivo = pasta / NOME_TRADUCAO
    try:
        if not legado.traducao_nova(arquivo):
            return None
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return dados if isinstance(dados, dict) and isinstance(dados.get("pages"), list) else None


def _num(v: Any, minimo: float, maximo: float, padrao: float = 0.0) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return padrao
    return n if n == n and minimo <= n <= maximo else padrao        # n == n: descarta NaN


def _cor(v: Any, padrao: Optional[str]) -> Optional[str]:
    return v if isinstance(v, str) and _COR.match(v) else padrao


def _caixa(v: Any, largura: float, altura: float) -> Optional[List[float]]:
    """[x, y, w, h] em px da imagem, validado (o JSON em disco é dado, não confiável)."""
    if not isinstance(v, (list, tuple)) or len(v) != 4:
        return None
    try:
        x, y, w, h = (float(n) for n in v)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(n) for n in (x, y, w, h)) or w <= 0 or h <= 0 or w > 4 * largura or h > 4 * altura:
        return None
    return [round(x, 1), round(y, 1), round(w, 1), round(h, 1)]


def _falas_usuario(pagina: Dict[str, Any], largura: float, altura: float) -> List[Dict[str, Any]]:
    """Leitura do USUÁRIO: só o necessário para desenhar a tradução (caixa, cor, fonte, texto). Nada de original, status ou alerta."""
    saida: List[Dict[str, Any]] = []
    for u in (pagina.get("units") or [])[:MAX_FALAS_POR_IMAGEM]:
        if not isinstance(u, dict) or not isinstance(u.get("render"), dict):
            continue
        r, texto = u["render"], u.get("translation")
        caixa = _caixa(r.get("box"), largura, altura)
        if r.get("mode") not in MODOS_ESCRITOS or not isinstance(texto, str) or not texto.strip() or caixa is None:
            continue
        saida.append({
            "modo": r["mode"], "caixa": caixa, "tinta": _cor(r.get("ink"), "#111111"), "contorno": _cor(r.get("stroke"), None), "fundo": _cor(r.get("bg"), None),
            "fonteMax": round(_num(r.get("fontMax"), 4, 600, 40.0), 1), "maiuscula": bool(r.get("upper")), "texto": texto[:1200],
        })
    return saida


def _falas_admin(pagina: Dict[str, Any], largura: float, altura: float) -> List[Dict[str, Any]]:
    """Leitura da BIBLIOTECA (verificação): tudo que serve para conferir cada fala (original, status, OCR, região, motivo)."""
    saida: List[Dict[str, Any]] = []
    for u in (pagina.get("units") or [])[:MAX_FALAS_POR_IMAGEM]:
        if not isinstance(u, dict):
            continue
        r = u["render"] if isinstance(u.get("render"), dict) else {}
        ocr = u["ocr"] if isinstance(u.get("ocr"), dict) else {}
        saida.append({
            "id": str(u.get("id", ""))[:40], "ordem": int(_num(u.get("order"), 0, 100000)),
            "estado": r.get("flag") if r.get("flag") in ("ok", "revisar", "erro") else "ok",
            "status": str(u.get("status", ""))[:20], "erro": str(u.get("error") or "")[:300],
            "original": str(u.get("source") or "")[:1200], "texto": str(u.get("translation") or "")[:1200],
            "regiao": _caixa(u.get("bbox"), largura, altura), "balaoId": u.get("balloonId") if isinstance(u.get("balloonId"), int) else None,
            "modo": str(r.get("mode") or "nenhum")[:12], "motivo": str(r.get("reason") or "")[:30],
            "tradModo": str(u.get("mode") or "")[:12], "glossario": [str(g)[:60] for g in (u.get("glossary") or [])[:10]],
            "ocr": {
                "status": str(ocr.get("status", ""))[:12], "motor": str(ocr.get("engine", ""))[:20],
                "confianca": round(_num(ocr.get("confidence"), 0, 100, 0.0), 1), "editado": bool(ocr.get("edited")),
            } if ocr else None,
            "junta": bool(r.get("join")),
        })
    return saida


def _baloes_admin(pagina: Dict[str, Any]) -> List[Dict[str, Any]]:
    saida: List[Dict[str, Any]] = []
    for b in (pagina.get("balloons") or [])[:MAX_BALOES_POR_IMAGEM]:
        try:
            poligono = [[round(float(x), 1), round(float(y), 1)] for x, y in b["polygon"][:300]]
            saida.append({
                "id": int(b["id"]), "tipo": str(b.get("kind", ""))[:20], "certeza": str(b.get("certainty", ""))[:12], "poligono": poligono,
            })
        except (KeyError, TypeError, ValueError):
            continue
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


def dados_do_capitulo(raiz: Path, rel: str, admin: bool = False) -> Optional[Dict[str, Any]]:
    """Tudo que o leitor global precisa de um capítulo.

    `admin=False` (leitura do usuário: celular, app e exportação): para cada imagem só a tradução já pronta para desenhar.
    `admin=True` (leitura da biblioteca, no notebook): além disso, regiões, balões, texto original, status e informações
    do processamento. Os dois modos nunca se misturam: o modo do usuário não carrega nenhum dado de verificação.
    """
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
    por_arquivo = {p["file"]: p for p in (traducao or {}).get("pages", []) if isinstance(p, dict) and isinstance(p.get("file"), str)}
    imagens = []
    for n, nome in enumerate(nomes, 1):
        pagina = por_arquivo.get(nome)
        largura, altura = (_num(pagina.get("width"), 1, 100000), _num(pagina.get("height"), 1, 100000)) if pagina else (0.0, 0.0)
        item: Dict[str, Any] = {"n": n, "arq": nome, "medidas": None, "patch": None, "falas": []}
        if pagina and largura and altura:
            item["medidas"] = [round(largura), round(altura)]
            if isinstance(pagina.get("patch"), str) and _PNG.match(pagina["patch"]):
                item["patch"] = pagina["patch"]
            item["falas"] = _falas_usuario(pagina, largura, altura)      # o que é desenhado: idêntico nos dois modos
            if admin:
                item["conferencia"] = _falas_admin(pagina, largura, altura)
                item["baloes"] = _baloes_admin(pagina)
                item["erro"] = str(pagina.get("error") or "")[:300]
        imagens.append(item)
    dados: Dict[str, Any] = {
        "rel": "/".join(partes), "obra": nome_obra, "rotulo": rotulo,
        "titulo": f"{nome_obra} — {rotulo}" if nome_obra else rotulo or pasta.name,
        "imagens": imagens, "admin": bool(admin), "traduzido": traducao is not None,
        "sub": NOME_IMG + "/" if pasta_imagens(pasta) != pasta else "",     # prefixo das imagens dentro de `base`
        "subLimpeza": PASTA_LIMPEZA,                                          # prefixo dos PNG de limpeza dentro de `base`
    }
    if admin and traducao is not None:
        dados["verificacao"] = {
            "motor": str(traducao.get("engine") or "")[:20], "provedor": str(traducao.get("provider") or "")[:60],
            "gerado": str(traducao.get("generatedAt") or "")[:30],
            "contagens": {str(k)[:12]: int(v) for k, v in (traducao.get("counts") or {}).items() if isinstance(v, (int, float))},
            "avisos": [str(a)[:200] for a in (traducao.get("warnings") or [])[:20]],
        }
    return dados
