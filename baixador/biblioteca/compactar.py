"""Versão compacta das imagens de um capítulo para o celular (~1080 px de largura, WebP). OPCIONAL: o padrão continua sendo o original.

As cópias ficam em `dados/cache_compacto/<hash do capítulo>/` e são refeitas só quando a imagem original muda (tamanho + data). Os originais
nunca são alterados. Quem converte é o `sharp` do tradutor (Node); se ele faltar ou falhar, a imagem vai no original (nada quebra).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

from baixador import configuracao

CACHE = configuracao.DADOS / "cache_compacto"
LARGURA, QUALIDADE = 1080, 80
SCRIPT = Path(__file__).resolve().parents[2] / "tradutor" / "src" / "compactar-imagens.js"


def _pasta(rel: str) -> Path:
    return CACHE / hashlib.sha1(rel.encode("utf-8")).hexdigest()[:16]


def _carimbo(arq: Path) -> str:
    st = arq.stat()
    return f"{st.st_size}:{st.st_mtime_ns}:{LARGURA}:{QUALIDADE}"


def _node_sharp(itens: List[Dict[str, str]]) -> Dict[str, object]:
    import shutil
    node = shutil.which("node")
    if not node or not SCRIPT.is_file():
        return {"ok": [], "falhas": [{"erro": "Node ou script ausente"}]}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump({"largura": LARGURA, "qualidade": QUALIDADE, "itens": itens}, f)
    try:
        r = subprocess.run([node, str(SCRIPT), f.name], capture_output=True, text=True, timeout=900, cwd=str(SCRIPT.parents[1]),
                           **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
        return json.loads((r.stdout or "{}").strip().splitlines()[-1])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return {"ok": [], "falhas": [{"erro": "falha ao executar o sharp"}]}
    finally:
        os.unlink(f.name)


def preparar(rel: str, pasta_imagens: Path, arquivos: List[str], converter: Optional[Callable[[List[Dict[str, str]]], Dict[str, object]]] = None) -> Dict[str, Path]:
    """{nome original: caminho da cópia compacta} só para o que ficou pronto. Cache por capítulo, imagem a imagem."""
    pasta = _pasta(rel)
    manifesto_arq = pasta / "manifesto.json"
    try:
        manifesto = json.loads(manifesto_arq.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifesto = {}
    pronto: Dict[str, Path] = {}
    faltam: List[Dict[str, str]] = []
    for nome in arquivos:
        origem = Path(pasta_imagens) / nome
        try:
            carimbo = _carimbo(origem)
        except OSError:
            continue
        destino = pasta / (Path(nome).stem + ".webp")
        if manifesto.get(nome) == carimbo and destino.is_file():
            pronto[nome] = destino
        else:
            faltam.append({"de": str(origem), "para": str(destino), "_nome": nome, "_carimbo": carimbo})
    if faltam:
        r = (converter or _node_sharp)([{"de": x["de"], "para": x["para"]} for x in faltam])
        feitos = set(r.get("ok") or [])
        for x in faltam:
            if x["para"] in feitos and Path(x["para"]).is_file():
                pronto[x["_nome"]] = Path(x["para"])
                manifesto[x["_nome"]] = x["_carimbo"]
        pasta.mkdir(parents=True, exist_ok=True)
        tmp = manifesto_arq.with_suffix(".tmp")
        tmp.write_text(json.dumps(manifesto), encoding="utf-8")
        os.replace(tmp, manifesto_arq)
    return pronto
