"""Exporta capítulos da biblioteca para um único ZIP que o app do celular (PWA) importa e lê sem internet.

Formato (versão 1), tudo SEM compressão (imagens já são comprimidas; o app lê sem biblioteca externa):
    baixador-export.json                  {"formato": 1, "gerado": ..., "obras": [{"nome", "capa"}], "capitulos": [...]}
    c0/capitulo.json                      os mesmos dados que o leitor usa (imagens, medidas e trechos traduzidos)
    c0/img/001.jpg ...                    as imagens originais do capítulo
    capas/o0.jpg                          capa da obra (se houver)
Só lê a biblioteca: nada é alterado nem apagado.
"""

from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path
from typing import Any, BinaryIO, Dict, List

from baixador.biblioteca.capa import achar as achar_capa
from baixador.biblioteca.capitulo import dados_do_capitulo, pasta_do_capitulo, pasta_imagens

FORMATO = 1


def gerar_zip(raiz: Path, caps: List[Dict[str, Any]], saida: BinaryIO) -> Dict[str, int]:
    """Grava em `saida` o ZIP dos capítulos `caps` (itens de `acervo.listar`, com `rel`, `numero`, `titulo`, `rotulo`).
    Capítulo que sumiu ou ficou sem imagens é ignorado. Devolve {"capitulos": n, "imagens": n}."""
    raiz = Path(raiz)
    obras: List[Dict[str, Any]] = []
    indice_obra: Dict[str, int] = {}
    capitulos: List[Dict[str, Any]] = []
    imagens = 0
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
        for c in caps:
            dados = dados_do_capitulo(raiz, c["rel"])
            pasta = pasta_do_capitulo(raiz, c["rel"])
            if dados is None or pasta is None:
                continue
            nome_obra = dados.get("obra") or pasta.parent.name
            if nome_obra not in indice_obra:
                capa_arq = achar_capa(pasta.parent) if pasta.parent != Path(raiz).resolve() else None
                caminho_capa = None
                if capa_arq is not None and capa_arq.is_file() and not capa_arq.is_symlink():
                    caminho_capa = f"capas/o{len(obras)}{capa_arq.suffix.lower()}"
                    z.write(capa_arq, caminho_capa)
                indice_obra[nome_obra] = len(obras)
                obras.append({"nome": nome_obra, "capa": caminho_capa})
            d = f"c{len(capitulos)}"
            origem = pasta_imagens(pasta)
            for im in dados["imagens"]:
                arquivo = origem / im["arq"]
                if arquivo.is_file() and not arquivo.is_symlink():
                    z.write(arquivo, f"{d}/img/{im['arq']}")
                    imagens += 1
            leitura = {k: dados[k] for k in ("rel", "obra", "rotulo", "titulo", "imagens")}
            z.writestr(f"{d}/capitulo.json", json.dumps(leitura, ensure_ascii=False))
            capitulos.append({
                "id": dados["rel"], "dir": d, "obra": indice_obra[nome_obra], "rotulo": dados["rotulo"],
                "numero": c.get("numero"), "titulo": c.get("titulo") or "", "paginas": len(dados["imagens"]),
                "traduzido": bool(c.get("traduzido")),
            })
        z.writestr("baixador-export.json", json.dumps({
            "formato": FORMATO, "gerado": time.strftime("%Y-%m-%dT%H:%M:%S"), "obras": obras, "capitulos": capitulos,
        }, ensure_ascii=False))
    return {"capitulos": len(capitulos), "imagens": imagens}
