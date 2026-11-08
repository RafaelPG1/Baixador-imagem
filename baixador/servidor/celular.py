"""Servidor SOMENTE LEITURA para o celular, na rede local (Wi-Fi de casa).

Princípios (nada aqui escreve em disco nem muda o estado do programa):
- só atende GET; qualquer outro método recebe 405;
- exige uma chave longa e aleatória (QR code); a chave vira cookie e sai da URL;
- só aceita clientes de endereços privados/locais (10.x, 172.16-31.x, 192.168.x, 169.254.x, 127.x);
- confere o cabeçalho Host (contra DNS rebinding);
- só entrega a página do leitor global, os dados de capítulo (JSON) e imagens de dentro da biblioteca, nunca por
  caminho fora dela;
- o leitor chega sem o token do notebook e sem o editor de tradução (nem os arquivos dele são entregues).
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

from baixador.biblioteca import acervo as biblioteca
from baixador.biblioteca.capitulo import dados_do_capitulo
from baixador.servidor.base import CSS, ESTATICOS_LEITOR, JS, TIPOS_IMAGEM, ServidorSilencioso, ler_capa, ler_web, pagina_leitor

PORTA_PADRAO = 8765
TIPOS = TIPOS_IMAGEM                                      # o servidor do celular só entrega imagens da biblioteca
ESTATICOS = {
    "/estatico/base.css": ("compartilhado/base.css", CSS),
    "/estatico/diagrama.js": ("compartilhado/diagrama.js", JS),
    "/estatico/leitura.js": ("celular/leitura.js", JS),
    **ESTATICOS_LEITOR,
}
CSP = (
    "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
MAX_ERROS = 8
BLOQUEIO_S = 60


def chave_nova() -> str:
    return secrets.token_urlsafe(24)


def ip_local() -> Optional[str]:
    """Endereço do notebook na rede (não envia nada: só pergunta ao sistema qual interface sairia para a rede)."""
    for destino in ("10.255.255.255", "192.168.255.255"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((destino, 9))
                ip = s.getsockname()[0]
                if ip and not ip.startswith("127."):
                    return ip
        except OSError:
            continue
    try:
        ip = socket.gethostbyname(socket.gethostname())
        return None if ip.startswith("127.") else ip
    except OSError:
        return None


def endereco_local(texto: str) -> bool:
    """True para IP privado/local (ou localhost). Nome de host qualquer só passa se for o do próprio computador."""
    try:
        ip = ipaddress.ip_address(texto.split("%")[0])
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def host_aceito(cabecalho: str) -> bool:
    host = cabecalho.strip().lower()
    if host.startswith("["):                              # [::1]:porta
        nome = host[1:].split("]")[0]
    else:
        nome = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    if nome in ("localhost", socket.gethostname().lower(), socket.gethostname().lower() + ".local"):
        return True
    return endereco_local(nome)


class _Manipulador(BaseHTTPRequestHandler):
    server_version = "Leitura"
    protocol_version = "HTTP/1.1"
    timeout = 30          # conexão ociosa (celular que dormiu) é encerrada em vez de prender uma thread para sempre

    def log_message(self, *_args) -> None:
        pass

    # ---- resposta
    def _enviar(self, status: int, tipo: str, corpo: bytes, cache: str = "no-store", extras: Optional[Dict[str, str]] = None) -> None:
        try:
            self.send_response(status)
            for k, v in (extras or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if self.close_connection:                      # avisa o cliente: sem isso ele tenta reusar a conexão e toma um reset
                self.send_header("Connection", "close")
            if tipo.startswith("text/html"):
                self.send_header("Content-Security-Policy", CSP)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(corpo)
        except (ConnectionError, TimeoutError):
            pass

    def _json(self, status: int, objeto: Any) -> None:
        self._enviar(status, "application/json; charset=utf-8", json.dumps(objeto).encode("utf-8"))

    def _pagina_erro(self, status: int, texto: str) -> None:
        corpo = (
            '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Leitura</title><body style="font:16px system-ui;margin:2rem;color:#222"><h1 style="font-size:1.25rem">{texto}</h1>'
            "<p>Abra o QR code que aparece na aba “Celular” do programa, no notebook.</p></body>"
        ).encode("utf-8")
        self._enviar(status, "text/html; charset=utf-8", corpo)

    # ---- métodos de escrita: nenhum existe
    def _recusar(self) -> None:
        self.close_connection = True
        self._enviar(405, "application/json; charset=utf-8", b'{"erro":"Somente leitura."}', extras={"Allow": "GET, HEAD"})

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _recusar  # type: ignore[assignment]

    # ---- autenticação
    def _chave_do_cookie(self) -> str:
        """Lê só o cookie `bk`. Leitura manual: outros cookies do mesmo IP (outras portas compartilham cookies) com
        valores fora do padrão fariam o `SimpleCookie` descartar o cabeçalho inteiro, inclusive a nossa chave."""
        for parte in self.headers.get("Cookie", "").split(";"):
            nome, _, valor = parte.strip().partition("=")
            if nome == "bk":
                return valor.strip().strip('"')
        return ""

    def _liberado(self, consulta: Dict[str, List[str]]) -> Optional[Dict[str, str]]:
        """None = negado (já respondeu). Dict = cabeçalhos extras (cookie novo) para a resposta."""
        servidor: ServidorCelular = self.server  # type: ignore[assignment]
        cliente = self.client_address[0]
        if not endereco_local(cliente) or not host_aceito(self.headers.get("Host", "")):
            self._pagina_erro(403, "Acesso negado")
            return None
        if servidor.bloqueado(cliente):
            self._pagina_erro(429, "Muitas tentativas. Aguarde um minuto.")
            return None
        chave = (consulta.get("k") or [""])[0]
        origem_cookie = False
        if not chave:
            chave = self._chave_do_cookie()
            origem_cookie = True
        if not chave or not hmac.compare_digest(chave.encode(), servidor.chave.encode()):
            if chave:
                servidor.registrar_erro(cliente)
            self._pagina_erro(401, "Chave inválida ou ausente")
            return None
        return {} if origem_cookie else {"Set-Cookie": f"bk={chave}; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000"}

    # ---- rotas (todas GET)
    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        servidor: ServidorCelular = self.server  # type: ignore[assignment]
        partes = urlsplit(self.path)
        consulta = parse_qs(partes.query)
        extras = self._liberado(consulta)
        if extras is None:
            return
        caminho = partes.path
        if "k" in consulta and caminho == "/":
            # Página inicial aberta pelo QR: responde direto (sem redirecionar), já com o cookie. A chave sai da barra
            # de endereço por script. Um redirecionamento aqui dependia de o cookie voltar na requisição seguinte.
            corpo = ler_web("celular/leitura.html").replace(
                b"</head>", b"<script>history.replaceState(null,'','/')</script></head>", 1)
            return self._enviar(200, "text/html; charset=utf-8", corpo, extras=extras)
        if "k" in consulta:                                    # outros caminhos: tira a chave do endereço
            resto = {k: v for k, v in consulta.items() if k != "k"}
            destino = caminho + (("?" + urlencode(resto, doseq=True)) if resto else "")
            self.close_connection = True
            return self._enviar(303, "text/plain; charset=utf-8", b"", extras={**extras, "Location": destino})

        if caminho == "/":
            return self._enviar(200, "text/html; charset=utf-8", ler_web("celular/leitura.html"))
        if caminho in ESTATICOS:
            nome, tipo = ESTATICOS[caminho]
            return self._enviar(200, tipo, ler_web(nome), cache="no-cache")
        if caminho == "/leitor":                               # o leitor global: a mesma página para qualquer capítulo
            return self._enviar(200, "text/html; charset=utf-8", pagina_leitor())
        if caminho == "/api/leitura":
            dados = dados_do_capitulo(servidor.raiz, (consulta.get("c") or [""])[0])
            if dados is None:
                return self._json(404, {"erro": "Capítulo não encontrado."})
            return self._json(200, {**dados, "base": "/ler/" + "/".join(quote(p) for p in dados["rel"].split("/")) + "/"})
        if caminho == "/api/capa":                             # capa da obra (imagem), pela pasta da obra
            achada = ler_capa(servidor.raiz, (consulta.get("p") or [""])[0])
            if achada is None:
                return self._json(404, {"erro": "Sem capa."})
            return self._enviar(200, achada[1], achada[0], cache="private, max-age=300")
        if caminho == "/api/biblioteca":
            return self._json(200, biblioteca.listar(servidor.raiz))
        if caminho == "/api/versao":
            return self._json(200, {"versao": biblioteca.versao(servidor.raiz)})
        if caminho.startswith("/ler/"):
            return self._servir_arquivo(caminho[len("/ler/"):])
        self._json(404, {"erro": "Endereço desconhecido."})

    def _servir_arquivo(self, relativo: str) -> None:
        servidor: ServidorCelular = self.server  # type: ignore[assignment]
        try:
            raiz = servidor.raiz.resolve(strict=True)
            alvo = (raiz / unquote(relativo).lstrip("/\\")).resolve(strict=True)
        except (OSError, ValueError, RuntimeError):
            return self._json(404, {"erro": "Arquivo não encontrado."})
        tipo = TIPOS.get(alvo.suffix.lower())
        if (
            tipo is None or not alvo.is_file() or alvo.name.startswith(".")
            or alvo == raiz or not alvo.is_relative_to(raiz)
        ):
            return self._json(404, {"erro": "Arquivo não encontrado."})
        try:
            corpo = alvo.read_bytes()
        except OSError:
            return self._json(404, {"erro": "Arquivo não encontrado."})
        self._enviar(200, tipo, corpo, cache="private, max-age=300")


class ServidorCelular(ServidorSilencioso):
    allow_reuse_address = False

    def __init__(self, raiz: Path, chave: str, porta: int = PORTA_PADRAO, endereco: str = "0.0.0.0"):
        self.raiz = Path(raiz)
        self.chave = chave
        self._erros: Dict[str, List[float]] = {}
        self._trava = threading.Lock()
        super().__init__((endereco, porta), _Manipulador)

    @property
    def porta(self) -> int:
        return self.server_address[1]

    def bloqueado(self, cliente: str) -> bool:
        with self._trava:
            agora = time.monotonic()
            recentes = [t for t in self._erros.get(cliente, []) if agora - t < BLOQUEIO_S]
            self._erros[cliente] = recentes
            return len(recentes) >= MAX_ERROS

    def registrar_erro(self, cliente: str) -> None:
        with self._trava:
            self._erros.setdefault(cliente, []).append(time.monotonic())


class ControleCelular:
    """Liga/desliga o servidor do celular e guarda a chave. É o único ponto que o app do notebook usa."""

    def __init__(self, raiz: Path, arquivo: Optional[Path] = None):
        self.raiz = Path(raiz)
        self.arquivo = arquivo
        self._servidor: Optional[ServidorCelular] = None
        self._thread: Optional[threading.Thread] = None
        self._trava = threading.Lock()
        dados = self._ler()
        self.chave: str = dados.get("chave") or chave_nova()
        self.porta: int = int(dados.get("porta") or PORTA_PADRAO)
        self.ligar_ao_abrir: bool = bool(dados.get("ligar_ao_abrir", False))
        self.erro: str = ""
        self._gravar()

    def _ler(self) -> Dict[str, Any]:
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8")) if self.arquivo else {}
            return dados if isinstance(dados, dict) else {}
        except (OSError, ValueError):
            return {}

    def _gravar(self) -> None:
        if self.arquivo is None:
            return
        try:
            self.arquivo.parent.mkdir(parents=True, exist_ok=True)
            self.arquivo.write_text(
                json.dumps({"chave": self.chave, "porta": self.porta, "ligar_ao_abrir": self.ligar_ao_abrir}, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    @property
    def ligado(self) -> bool:
        return self._servidor is not None

    def ligar(self, lembrar: Optional[bool] = None) -> None:
        with self._trava:
            if lembrar is not None:
                self.ligar_ao_abrir = lembrar
            if self._servidor is None:
                self.erro = ""
                servidor = None
                for porta in (self.porta, 0):               # se a porta preferida estiver ocupada, usa outra livre
                    try:
                        servidor = ServidorCelular(self.raiz, self.chave, porta)
                        break
                    except OSError as erro:
                        self.erro = f"A porta {porta} não está disponível ({erro.strerror or erro})."
                if servidor is None:
                    raise RuntimeError(self.erro or "Não foi possível ligar o acesso do celular.")
                self.erro = ""
                self.porta = servidor.porta
                self._servidor = servidor
                self._thread = threading.Thread(target=servidor.serve_forever, daemon=True, kwargs={"poll_interval": 0.3})
                self._thread.start()
            self._gravar()

    def desligar(self, lembrar: Optional[bool] = None) -> None:
        with self._trava:
            if lembrar is not None:
                self.ligar_ao_abrir = lembrar
            servidor, self._servidor = self._servidor, None
            if servidor is not None:
                servidor.shutdown()
                servidor.server_close()
            self._gravar()

    def trocar_chave(self) -> None:
        """Gera outra chave: o QR antigo e os celulares já autorizados (cookie) deixam de funcionar na hora."""
        with self._trava:
            self.chave = chave_nova()
            if self._servidor is not None:
                self._servidor.chave = self.chave
            self._gravar()

    def estado(self) -> Dict[str, Any]:
        ip = ip_local()
        url = f"http://{ip}:{self.porta}/?k={self.chave}" if (ip and self.ligado) else ""
        return {
            "ligado": self.ligado, "ip": ip, "porta": self.porta, "url": url, "erro": self.erro,
            "ligar_ao_abrir": self.ligar_ao_abrir,
        }
