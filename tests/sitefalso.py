"""Site de mangá falso para testar a navegação entre capítulos: página da obra (lista de capítulos), capítulos com imagens e
botões próximo/anterior, páginas "em breve" e botões que levam a páginas inexistentes ou que pulam capítulo."""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Tuple

IMAGENS = Path(__file__).parent / "fixtures" / "jpg"
SLUG = "obra-x"


class Site:
    def __init__(
        self, ultimo: int = 55, paginas: int = 4, latencia: float = 0.0, placeholder: Optional[int] = None,
        com_proximo_no_ultimo: bool = False, titulo_atrasado: bool = False, lista_na_serie: bool = True, pula: Optional[Dict[int, int]] = None,
    ) -> None:
        self.ultimo, self.paginas, self.latencia = ultimo, paginas, latencia
        self.placeholder = placeholder                   # página "em breve": existe, mas sem imagens
        self.com_proximo_no_ultimo = com_proximo_no_ultimo   # o último capítulo tem um botão Next que leva a uma página 404
        self.titulo_atrasado = titulo_atrasado           # o título da aba só se atualiza 1,5 s depois (sites feitos com JavaScript)
        self.lista_na_serie = lista_na_serie
        self.pula = pula or {}                           # {n: m}: o botão Next do capítulo n leva ao m
        self.pedidos: List[Tuple[float, str]] = []
        site = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a: object) -> None:
                pass

            def _enviar(self, corpo: bytes | str, tipo: str = "text/html; charset=utf-8", status: int = 200) -> None:
                corpo = corpo.encode("utf-8") if isinstance(corpo, str) else corpo
                self.send_response(status)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)

            def do_GET(self) -> None:
                site.pedidos.append((time.time(), self.path))
                if self.path.startswith("/img/"):
                    _, _, cap, k = self.path.split("?")[0].split("/")
                    return self._enviar((IMAGENS / f"{int(k.split('.')[0]) % 10}.jpg").read_bytes(), "image/jpeg")
                time.sleep(site.latencia)
                if self.path == "/":
                    return self._enviar("<h1>Site</h1>")
                if self.path == "/favicon.ico":
                    return self._enviar(b"", "image/x-icon", 404)
                if self.path.rstrip("/") == f"/manga/{SLUG}":
                    return self._enviar(site.serie())
                prefixo = f"/manga/{SLUG}/chapter-"
                if self.path.startswith(prefixo):
                    try:
                        n = int(self.path[len(prefixo):].split("?")[0])
                    except ValueError:
                        return self._enviar("não existe", status=404)
                    if n == site.placeholder:
                        return self._enviar(site.pagina(n, placeholder=True))
                    if n < 1 or n > site.ultimo:
                        return self._enviar("<h1>Capítulo não encontrado</h1>", status=404)
                    return self._enviar(site.pagina(n))
                return self._enviar("<h1>Página não encontrada</h1>", status=404)

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.http.daemon_threads = True
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.http.server_address[1]}"

    def url(self, n: int) -> str:
        return f"{self.base}/manga/{SLUG}/chapter-{n}"

    def parar(self) -> None:
        self.http.shutdown()
        self.http.server_close()

    def paginas_pedidas(self) -> List[str]:
        return [p for _, p in self.pedidos if not p.startswith("/img/")]

    def serie(self) -> str:
        itens = "".join(f'<li><a href="/manga/{SLUG}/chapter-{n}">Chapter {n}</a></li>' for n in range(self.ultimo, 0, -1)) if self.lista_na_serie else ""
        return f"<html><head><title>Obra X - Read Obra X Online | Site Scans</title></head><body><h1>Obra X</h1><ul>{itens}</ul></body></html>"

    def pagina(self, n: int, placeholder: bool = False) -> str:
        ant = f'<a rel="prev" href="/manga/{SLUG}/chapter-{n - 1}">Previous Chapter</a>' if n > 1 else ""
        tem_prox = n < self.ultimo or placeholder or self.com_proximo_no_ultimo
        prox = f'<a rel="next" class="next" href="/manga/{SLUG}/chapter-{self.pula.get(n, n + 1)}">Next Chapter</a>' if tem_prox else ""
        imgs = "" if placeholder else "".join(f'<img src="/img/{n}/{k}.jpg" width="700" height="1000">' for k in range(self.paginas))
        titulo = f"Obra X Chapter {n} - Site Scans"
        inicial = f"Obra X Chapter {max(1, n - 1)} - Site Scans" if self.titulo_atrasado else titulo
        script = f"<script>setTimeout(()=>{{document.title={titulo!r}}}, 1500)</script>" if self.titulo_atrasado else ""
        corpo = "<p>Este capítulo sai em breve.</p>" if placeholder else ""
        return (f"<html><head><title>{inicial}</title></head><body>{script}<h1>Obra X Chapter {n}</h1><nav>{ant} "
                f'<a href="/manga/{SLUG}/">All chapters</a> {prox}</nav><div class="reader">{imgs}{corpo}</div><nav>{ant} {prox}</nav></body></html>')
