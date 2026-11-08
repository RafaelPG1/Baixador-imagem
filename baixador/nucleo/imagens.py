"""Validação do conteúdo baixado e gravação segura no disco."""

from __future__ import annotations

import base64
import binascii
import posixpath
import re
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlsplit

from baixador.nucleo.erros import ArquivoGrande, ErroBaixador, FormatoIncompativel

_TAMANHOS_CABECALHO_BMP = (12, 40, 52, 56, 108, 124)


def detectar_formato(dados: bytes) -> str:
    """Identifica a imagem pelos primeiros bytes (não confia em extensão nem Content-Type).

    Formatos aceitos: png, jpg, gif, webp, bmp, avif.
    SVG é recusado de propósito: pode conter scripts.
    """
    if dados.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if dados.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if dados.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if dados[:4] == b"RIFF" and dados[8:12] == b"WEBP":
        return "webp"
    if dados[4:8] == b"ftyp" and dados[8:12] in (b"avif", b"avis"):
        return "avif"
    if (
        dados[:2] == b"BM"
        and len(dados) > 18
        and int.from_bytes(dados[14:18], "little") in _TAMANHOS_CABECALHO_BMP
    ):
        return "bmp"

    inicio = dados[:512].lstrip().lower()
    if inicio.startswith((b"<svg", b"<?xml")) and b"<svg" in dados[:2048].lower():
        raise FormatoIncompativel(
            "SVG não é suportado (pode conter scripts); o arquivo não foi salvo."
        )
    if inicio.startswith((b"<!doctype html", b"<html")):
        raise FormatoIncompativel("O endereço devolveu uma página HTML, não uma imagem.")
    raise FormatoIncompativel("O conteúdo não é uma imagem em formato suportado.")


def decodificar_data_uri(uri: str, limite_bytes: int) -> bytes:
    """Decodifica `data:image/...;base64,XXXX` respeitando o limite de tamanho."""
    cabecalho, _, corpo = uri.partition(",")
    if not corpo:
        raise FormatoIncompativel("Imagem embutida (data URI) vazia ou malformada.")
    if ";base64" not in cabecalho.lower():
        raise FormatoIncompativel("Só imagens embutidas em base64 são suportadas.")
    if len(corpo) * 3 // 4 > limite_bytes + 3:
        raise ArquivoGrande("A imagem embutida ultrapassa o limite de tamanho.")
    try:
        return base64.b64decode(corpo, validate=False)
    except (binascii.Error, ValueError):
        raise FormatoIncompativel("Imagem embutida (data URI) corrompida.") from None


def nome_arquivo(url: str, indice: int, extensao: str, sufixo: str = "") -> str:
    """Gera um nome seguro: `001_nome-original.ext`. O prefixo numérico evita colisões."""
    if url.lower().startswith("data:"):
        radical = "embutida"
    else:
        base = posixpath.basename(unquote(urlsplit(url).path))
        radical = posixpath.splitext(base)[0]
    radical = re.sub(r"[^\w\-.]+", "_", radical, flags=re.UNICODE).strip("._")[:60]
    return f"{indice:03d}_{radical or 'imagem'}{sufixo}.{extensao}"


_RESERVADOS_WINDOWS = {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)), *(f"lpt{n}" for n in range(1, 10))}


def nome_do_conjunto(texto: Optional[str]) -> Optional[str]:
    """Nome seguro para uma subpasta (um único componente de caminho), ou None se ficar vazio."""
    limpo = re.sub(r"[^\w\- .]+", "_", (texto or "").strip(), flags=re.UNICODE)
    limpo = re.sub(r"\s+", " ", limpo).strip(" ._")[:80].strip(" ._")
    if not limpo:
        return None
    if limpo.lower() in _RESERVADOS_WINDOWS:
        limpo = "_" + limpo
    return limpo


def pasta_do_conjunto(base: str, conjunto: Optional[str]) -> str:
    """`base` com a subpasta do conjunto no final. Aceita 'Obra/Cap 005' (até 2 níveis); cada nível é higienizado."""
    pedacos = [nome_do_conjunto(p) for p in re.split(r"[/\\]", conjunto or "")]
    pedacos = [p for p in pedacos if p][:2]
    destino = Path(base).expanduser()
    for p in pedacos:
        destino = destino / p
    return str(destino) if pedacos else base


def preparar_pasta(caminho: str) -> Path:
    """Cria (se preciso) e devolve a pasta de destino já resolvida."""
    pasta = Path(caminho).expanduser()
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        pasta = pasta.resolve(strict=True)
    except OSError as erro:
        raise ErroBaixador(f"Não foi possível usar a pasta '{caminho}': {erro}") from None
    if not pasta.is_dir():
        raise ErroBaixador(f"'{caminho}' não é uma pasta.")
    return pasta


def salvar(pasta: Path, nome: str, dados: bytes) -> Path:
    """Grava sem nunca sobrescrever: se o nome existir, acrescenta _2, _3..."""
    nome = Path(nome).name  # descarta qualquer componente de diretório
    radical, ponto, extensao = nome.rpartition(".")
    for tentativa in range(1, 1000):
        candidato = nome if tentativa == 1 else f"{radical}_{tentativa}{ponto}{extensao}"
        destino = pasta / candidato
        try:
            with open(destino, "xb") as arquivo:  # "x": falha se já existir
                arquivo.write(dados)
            return destino
        except FileExistsError:
            continue
        except OSError as erro:
            raise ErroBaixador(f"Falha ao gravar '{candidato}': {erro}") from None
    raise ErroBaixador(f"Muitos arquivos com o nome '{nome}' na pasta.")
