"""Peças comuns aos dois servidores (notebook e celular): servidor silencioso, arquivos da web e página do leitor."""

from __future__ import annotations

import sys
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Optional, Tuple

from baixador.biblioteca import capa
from baixador.configuracao import WEB
from baixador.nucleo.erros import ErroBaixador
from baixador.nucleo.imagens import detectar_formato

CSS = "text/css; charset=utf-8"
JS = "text/javascript; charset=utf-8"

# URL pública → (arquivo dentro de web/, tipo). Nada de segredo nesses arquivos; só o que está aqui é entregue.
ESTATICOS_LEITOR: Dict[str, Tuple[str, str]] = {
    "/estatico/leitor.css": ("leitor/leitor.css", CSS),
    "/estatico/leitor.js": ("leitor/leitor.js", JS),
}
ESTATICOS_EDICAO: Dict[str, Tuple[str, str]] = {          # só o servidor do notebook entrega (edição é do notebook)
    "/estatico/edicao.css": ("leitor/edicao.css", CSS),
    "/estatico/edicao.js": ("leitor/edicao.js", JS),
}

TIPOS_IMAGEM = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".gif": "image/gif", ".avif": "image/avif", ".bmp": "image/bmp",
}


def ler_web(relativo: str) -> bytes:
    """Lê um arquivo de `web/` (levanta OSError se não existir)."""
    return (WEB / relativo).read_bytes()


def ler_capa(raiz: Path, pasta: str) -> Optional[Tuple[bytes, str]]:
    """Bytes e tipo da capa da obra guardada em `raiz/<pasta>/capa.*`. `pasta` é um único nome de pasta (nada de caminhos)."""
    if not pasta or pasta.startswith(".") or "/" in pasta or "\\" in pasta or "\0" in pasta:
        return None
    try:
        base = Path(raiz).resolve(strict=True)
        pasta_obra = (base / pasta).resolve(strict=True)
        arquivo = capa.achar(pasta_obra)
        if pasta_obra.parent != base or arquivo is None or arquivo.stat().st_size > capa.LIMITE_CAPA:
            return None
        dados = arquivo.read_bytes()
    except (OSError, ValueError, RuntimeError):
        return None
    try:
        tipo = TIPOS_IMAGEM.get("." + detectar_formato(dados))
    except ErroBaixador:
        return None
    return (dados, tipo) if tipo else None


def pagina_leitor(meta: bytes = b"") -> bytes:
    """O leitor global: a mesma página para todas as obras e capítulos. `meta` entra antes de `</head>`."""
    return ler_web("leitor/leitor.html").replace(b"</head>", meta + b"</head>", 1)


class ServidorSilencioso(ThreadingHTTPServer):
    """Servidor HTTP que não imprime traceback quando o cliente some no meio (celular que bloqueia a tela, troca de
    rede ou cancela a página: ConnectionResetError/WinError 10054, 10053, BrokenPipe). Outros erros continuam visíveis."""

    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        erro = sys.exc_info()[1]
        if isinstance(erro, (ConnectionError, TimeoutError)):
            return
        if isinstance(erro, OSError) and getattr(erro, "winerror", None) in (10053, 10054, 10058, 10060):
            return
        super().handle_error(request, client_address)
