"""Exporta capítulos da biblioteca para um único ZIP que o app Android (APK) importa e lê sem internet.

Formato (versão 1), tudo SEM compressão (imagens já são comprimidas; o app lê sem biblioteca externa):
    baixador-export.json                  {"formato": 1, "gerado": ..., "obras": [{"nome", "capa"}], "capitulos": [...]}
    c0/capitulo.json                      os mesmos dados que o leitor usa (imagens, medidas e trechos traduzidos)
    c0/img/001.jpg ...                    as imagens originais do capítulo
    capas/o0.jpg                          capa da obra (se houver)
Só lê a biblioteca: nada é alterado nem apagado.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Tuple
from urllib.parse import quote

from baixador.biblioteca import acervo, organizacao

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


MAX_CAPITULOS = 500


def selecionar(raiz: Path, rels: List[str], obra: str = "") -> List[Tuple[str, Dict[str, Any]]]:
    """Capítulos da biblioteca pedidos por caminho (`rels`) ou por obra inteira, em ordem estável: [(nome da obra, capítulo)]."""
    pedidos = {r[:300] for r in rels}
    obra = obra[:120]
    todos = [
        (o["nome"], c) for o in acervo.listar(raiz)["obras"]
        if not obra or organizacao._chave(o["nome"]) == organizacao._chave(obra)
        for c in o["capitulos"] if (not pedidos or c["rel"] in pedidos)
    ]
    todos.sort(key=lambda x: (x[0].casefold(), x[1].get("numero") is None, str(x[1].get("numero") or ""), x[1]["rel"]))
    return todos[:MAX_CAPITULOS]


def zip_temporario(raiz: Path, rels: List[str], obra: str = "") -> Optional[Tuple[BinaryIO, int, str]]:
    """Monta o ZIP num arquivo temporário (não na memória). Devolve (arquivo posicionado no início, tamanho, nome sugerido)
    ou None se não houver nada para exportar. Quem recebe o arquivo deve fechá-lo."""
    todos = selecionar(raiz, rels, obra)
    if not todos:
        return None
    arquivo = tempfile.TemporaryFile()
    try:
        resumo = gerar_zip(raiz, [c for _, c in todos], arquivo)
        if not resumo["capitulos"]:
            arquivo.close()
            return None
        tamanho = arquivo.seek(0, os.SEEK_END)
        arquivo.seek(0)
    except BaseException:
        arquivo.close()
        raise
    unico = len({n for n, _ in todos}) == 1
    return arquivo, tamanho, (obra or (todos[0][0] if unico else "baixador")) + ".zip"


def transmitir(handler: Any, arquivo: BinaryIO, tamanho: int, nome: str, extras: Optional[Dict[str, str]] = None,
               tipo: str = "application/zip") -> None:
    """Envia o ZIP em pedaços como download (`handler` é um BaseHTTPRequestHandler)."""
    seguro = "".join(ch if ch.isalnum() or ch in " ._-" else "_" for ch in nome).strip() or "baixador.zip"
    try:
        handler.send_response(200)
        for k, v in (extras or {}).items():
            handler.send_header(k, v)
        handler.send_header("Content-Type", tipo)
        handler.send_header("Content-Length", str(tamanho))
        handler.send_header("Content-Disposition", f"attachment; filename=\"{seguro}\"; filename*=UTF-8''{quote(nome)}")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-Content-Type-Options", "nosniff")
        cors = getattr(handler, "_cabecalhos_cors", None)          # só o servidor do celular tem (liberação do app Android)
        if cors is not None:
            cors()
        handler.end_headers()
        while True:
            pedaco = arquivo.read(1024 * 256)
            if not pedaco:
                break
            handler.wfile.write(pedaco)
    except (ConnectionError, TimeoutError):
        pass                                                  # o cliente cancelou o download
