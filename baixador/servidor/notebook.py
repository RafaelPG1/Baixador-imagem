"""App do notebook: servidor local com as telas Baixar, Biblioteca e Celular.

Como funciona: um servidor HTTP mínimo (biblioteca padrão) escuta SÓ em 127.0.0.1, numa porta aleatória, e abre
a página no navegador padrão. O acesso do celular (somente leitura) é outro servidor, em `celular.py`, ligado por aqui.

Segurança do servidor local:
- só aceita conexões do próprio computador;
- todo acesso exige um token aleatório gerado a cada execução (vai na URL aberta);
- confere o cabeçalho Host (contra DNS rebinding) e o Origin dos POSTs (contra CSRF);
- só entrega imagens que o próprio programa salvou (por número, nunca por caminho);
- o texto vindo de sites (URLs, erros) é exibido sempre como texto, nunca como HTML.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import subprocess
import sys
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, unquote, urlsplit

from baixador.biblioteca import acervo as biblioteca
from baixador.traducao import config, edicao, gemini, hymt, inteligencia as ia, openrouter, refino
from baixador.navegador import navegadores
from baixador.biblioteca import capa as capa_obra, estrutura, exportar, obra as dados_obra, organizacao
from baixador.servidor.base import (
    CSS, ESTATICOS_EDICAO, ESTATICOS_LEITOR, JS, ServidorSilencioso, ler_capa, ler_web, pagina_leitor,
)
from baixador.servidor import celular as celular_servidor
from baixador.servidor.celular import ControleCelular
from baixador.nucleo.erros import ErroBaixador
from baixador.configuracao import ARQUIVO_CELULAR, PASTA_PADRAO, migrar_dados_antigos, migrar_pasta_biblioteca
from baixador.nucleo.imagens import pasta_do_conjunto
from baixador.biblioteca.capitulo import dados_do_capitulo, listar_imagens
from baixador.navegador.manual import ESTADOS_ATIVOS, SessaoManual
from baixador.traducao import pipeline
from baixador.traducao.pipeline import IDIOMAS_DESTINO, IDIOMAS_ORIGEM, Motores, TarefaTraducao

PAGINA = "notebook/app.html"
ESTATICOS = {
    "/estatico/base.css": ("compartilhado/base.css", CSS),
    "/estatico/diagrama.js": ("compartilhado/diagrama.js", JS),
    "/estatico/qrcode.js": ("compartilhado/qrcode.js", JS),
    "/estatico/comum.js": ("notebook/comum.js", JS),
    "/estatico/baixar.js": ("notebook/baixar.js", JS),
    "/estatico/traducoes.js": ("notebook/traducoes.js", JS),
    "/estatico/biblioteca.js": ("notebook/biblioteca.js", JS),
    "/estatico/celular.js": ("notebook/celular.js", JS),
    **ESTATICOS_LEITOR,
    **ESTATICOS_EDICAO,
}
TIPOS_IMAGEM = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".bmp": "image/bmp",
}
MAX_CORPO = 16 * 1024
TIPOS_LEITOR = {                                          # só imagens: nenhuma página HTML é entregue de dentro da biblioteca
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".avif": "image/avif", ".bmp": "image/bmp",
}
ID_BIBLIOTECA = "b"          # identificador fixo da biblioteca: imagens em /ler/b/<Obra>/<Capítulo>/<imagem>

CSP_PAGINA = (
    "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)


def _abrir_no_sistema(caminho: Path) -> None:
    """Abre uma pasta no explorador de arquivos do sistema (sem passar por shell)."""
    if hasattr(os, "startfile"):  # Windows
        os.startfile(str(caminho))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(caminho)])
    else:
        subprocess.Popen(["xdg-open", str(caminho)])


class Manipulador(BaseHTTPRequestHandler):
    server_version = "Baixador"
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args) -> None:  # sem log de acesso no console
        pass

    # ------------------------------------------------------------ utilidades

    def _enviar(
        self, status: int, tipo: str, corpo: bytes, cache: str = "no-store", extras: Optional[Dict[str, str]] = None
    ) -> None:
        try:
            self.send_response(status)
            for chave, valor in (extras or {}).items():
                self.send_header(chave, valor)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if self.close_connection:
                self.send_header("Connection", "close")
            if tipo.startswith("text/html"):
                self.send_header("Content-Security-Policy", CSP_PAGINA)
            self.end_headers()
            self.wfile.write(corpo)
        except (ConnectionError, TimeoutError):
            pass  # o navegador fechou a aba no meio da resposta

    def _json(self, status: int, objeto: Any) -> None:
        self._enviar(status, "application/json; charset=utf-8", json.dumps(objeto).encode("utf-8"))

    def _negar(self, status: int = 403, mensagem: str = "Acesso negado.") -> None:
        self._json(status, {"erro": mensagem})

    def _autorizado(self, consulta: Dict[str, List[str]], metodo_post: bool) -> bool:
        if self.headers.get("Host", "") not in self.server.hosts:  # type: ignore[attr-defined]
            return False
        token = (consulta.get("t") or [""])[0]
        if not hmac.compare_digest(token.encode(), self.server.token.encode()):  # type: ignore[attr-defined]
            return False
        if metodo_post:
            origem = self.headers.get("Origin")
            if origem is not None and origem not in self.server.origens:  # type: ignore[attr-defined]
                return False
        return True

    # ------------------------------------------------------------ GET

    @staticmethod
    def _conjunto_dos_dados(dados: Dict[str, Any]) -> str:
        """Caminho relativo do capítulo: 'Obra/Cap 005 - Nome' (campos novos) ou o nome simples antigo (`conjunto`)."""
        if "obra" in dados:
            return organizacao.caminho_relativo(
                str(dados.get("obra", ""))[:120], organizacao.normalizar_numero(dados.get("numero")),
                str(dados.get("titulo", ""))[:120],
            )
        return str(dados.get("conjunto", ""))[:200]

    @staticmethod
    def _capitulo_duplicado(base: Path, obra: str, numero: Any, titulo: str, url: str) -> Optional[str]:
        """Caminho do capítulo na biblioteca, se esse capítulo já foi salvo (a obra é reconhecida mesmo com o nome do site errado)."""
        if not base.is_dir():
            return None
        nome = obra
        if obra.strip():
            r = biblioteca.resolver_obra(base, obra, url)
            nome = r["obra"] if r["existente"] else obra
        return biblioteca.capitulo_existente(base, nome, organizacao.normalizar_numero(numero), titulo, url)

    def _pasta_do_leitor(self, caminho: str) -> Optional[Path]:
        """`/ler/<id>/sub/pasta/` → pasta real, só se estiver dentro de uma raiz que o usuário abriu."""
        pedacos = caminho.split("/")
        if len(pedacos) < 3 or pedacos[0] != "" or pedacos[1] != "ler":
            return None
        raiz = self.server.leitores.get(pedacos[2])  # type: ignore[attr-defined]
        if raiz is None:
            return None
        try:
            raiz = raiz.resolve(strict=True)
            alvo = (raiz / unquote("/".join(pedacos[3:])).lstrip("/\\")).resolve(strict=True)
        except (OSError, ValueError, RuntimeError):
            return None
        return alvo if alvo == raiz or alvo.is_relative_to(raiz) else None

    def _token_do_leitor(self, consulta: Dict[str, List[str]]) -> Optional[Tuple[str, bool]]:
        """Token da URL (`?t=`) ou do cookie `bt`. Devolve (token, veio_na_url) se for o token certo; senão None."""
        token = (consulta.get("t") or [""])[0]
        veio_na_url = bool(token)
        if not token:
            for parte in self.headers.get("Cookie", "").split(";"):
                nome, _, valor = parte.strip().partition("=")
                if nome == "bt":
                    token = valor.strip()
        if not hmac.compare_digest(token.encode(), self.server.token.encode()):  # type: ignore[attr-defined]
            return None
        return token, veio_na_url

    def _servir_leitor(self, partes, consulta: Dict[str, List[str]]) -> None:
        """Imagens da biblioteca (`/ler/<id>/<Obra>/<Capítulo>/<imagem>`) para o leitor. Só lê, e só imagens."""
        if self.headers.get("Host", "") not in self.server.hosts:  # type: ignore[attr-defined]
            return self._negar()
        autorizado = self._token_do_leitor(consulta)
        if autorizado is None:
            return self._negar()
        token, veio_na_url = autorizado
        alvo = self._pasta_do_leitor(partes.path)
        if alvo is None or not alvo.is_file() or alvo.suffix.lower() not in TIPOS_LEITOR or alvo.name.startswith("."):
            return self._negar(404, "Arquivo não encontrado.")
        try:
            corpo = alvo.read_bytes()
        except OSError:
            return self._negar(404, "Arquivo não encontrado.")
        extras = {"Set-Cookie": f"bt={token}; Path=/ler/; HttpOnly; SameSite=Strict"} if veio_na_url else {}
        return self._enviar(200, TIPOS_LEITOR[alvo.suffix.lower()], corpo, cache="private, max-age=300", extras=extras)

    def _servir_pagina_leitor(self, consulta: Dict[str, List[str]]) -> None:
        """O leitor global (uma só página para todas as obras e capítulos). Entrega o token do notebook à página."""
        if self.headers.get("Host", "") not in self.server.hosts:  # type: ignore[attr-defined]
            return self._negar()
        autorizado = self._token_do_leitor(consulta)
        if autorizado is None:
            return self._negar()
        token, veio_na_url = autorizado
        extras = {"Set-Cookie": f"bt={token}; Path=/ler/; HttpOnly; SameSite=Strict"} if veio_na_url else {}
        meta = f'<meta name="baixador-token" content="{self.server.token}">'.encode()  # type: ignore[attr-defined]
        return self._enviar(200, "text/html; charset=utf-8", pagina_leitor(meta), extras=extras)

    def _dados_da_leitura(self, consulta: Dict[str, List[str]]) -> None:
        """`/api/leitura?c=<Obra/Capítulo>[&r=<id da raiz>]`: título, imagens e trechos traduzidos de um capítulo."""
        identificador = (consulta.get("r") or [ID_BIBLIOTECA])[0][:40]
        raiz = self.server.leitores.get(identificador)  # type: ignore[attr-defined]
        dados = dados_do_capitulo(raiz, (consulta.get("c") or [""])[0]) if raiz is not None else None
        if dados is None:
            return self._negar(404, "Capítulo não encontrado.")
        base = f"/ler/{quote(identificador)}/" + "/".join(quote(p) for p in dados["rel"].split("/")) + "/"
        return self._json(200, {**dados, "base": base})

    @staticmethod
    def _numero(consulta: Dict[str, List[str]], nome: str, padrao: int) -> int:
        try:
            return max(int((consulta.get(nome) or [str(padrao)])[0]), -1)
        except ValueError:
            return padrao

    def do_GET(self) -> None:
        partes = urlsplit(self.path)
        consulta = parse_qs(partes.query)
        if partes.path.startswith("/ler/"):
            return self._servir_leitor(partes, consulta)
        if partes.path == "/leitor":
            return self._servir_pagina_leitor(consulta)
        if partes.path == "/favicon.ico":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if partes.path in ESTATICOS:                       # arquivos da própria interface (nada de segredo neles)
            if self.headers.get("Host", "") not in self.server.hosts:  # type: ignore[attr-defined]
                return self._negar()
            nome, tipo = ESTATICOS[partes.path]
            try:
                return self._enviar(200, tipo, ler_web(nome), cache="no-cache")
            except OSError:
                return self._negar(404, "Arquivo da interface não encontrado.")
        if not self._autorizado(consulta, metodo_post=False):
            return self._negar()
        caminho = partes.path
        manual: SessaoManual = self.server.manual  # type: ignore[attr-defined]
        raiz: Path = self.server.raiz  # type: ignore[attr-defined]

        if caminho == "/":
            try:
                return self._enviar(200, "text/html; charset=utf-8", ler_web(PAGINA))
            except OSError:
                return self._negar(500, "Arquivo da interface não encontrado.")

        if caminho == "/api/navegadores":
            return self._json(200, {"opcoes": navegadores.opcoes(), "padrao": navegadores.padrao()})

        if caminho == "/api/config":
            return self._json(200, {"pasta_padrao": str(PASTA_PADRAO), "id_biblioteca": ID_BIBLIOTECA})

        if caminho == "/api/capitulo":
            aba = (consulta.get("aba") or [""])[0][:300]
            url = (consulta.get("url") or [""])[0][:2048]
            base = (consulta.get("pasta") or [""])[0].strip()[:400]
            achado = organizacao.extrair_capitulo(aba, url)
            pasta = Path(base).expanduser() if base else raiz
            achado["existente"], achado["candidatas"], achado["motivo_obra"] = False, [], ""
            if pasta.is_dir():                             # reconhece a obra que você já tem (sem duplicar); em dúvida, só sugere
                r = biblioteca.resolver_obra(pasta, str(achado["obra"] or ""), url)
                achado["obra"] = r["obra"] or achado["obra"]
                achado["existente"], achado["candidatas"], achado["motivo_obra"] = r["existente"], r["candidatas"], r["motivo"]
            return self._json(200, achado)

        if caminho == "/api/capitulo/previa":
            def campo(nome: str) -> str:
                return (consulta.get(nome) or [""])[0][:200]
            base = campo("pasta").strip()
            obra_prev = campo("obra")
            if obra_prev.strip() and base and Path(base).expanduser().is_dir():          # mostra o destino real (obra já existente)
                r = biblioteca.resolver_obra(Path(base).expanduser(), obra_prev, (consulta.get("url") or [""])[0][:2048])
                obra_prev = r["obra"] if r["existente"] else obra_prev
            rel = organizacao.caminho_relativo(obra_prev, organizacao.normalizar_numero(campo("numero")), campo("titulo"))
            existe = self._capitulo_duplicado(Path(base).expanduser() if base else raiz, campo("obra"), campo("numero"), campo("titulo"), (consulta.get("url") or [""])[0][:2048])
            return self._json(200, {"rel": rel, "existe": existe, "sem_numero": bool(campo("obra").strip()) and not organizacao.normalizar_numero(campo("numero")) and not campo("titulo").strip()})

        if caminho == "/api/leitura":
            return self._dados_da_leitura(consulta)

        if caminho == "/api/exportar":                         # ZIP para o app do celular: ?rel=Obra/Cap (repetível) ou ?obra=Nome
            return self._exportar(consulta)

        if caminho == "/api/capa":                             # capa da obra (imagem), pela pasta da obra
            achada = ler_capa(raiz, (consulta.get("p") or [""])[0])
            if achada is None:
                return self._json(404, {"erro": "Sem capa."})
            return self._enviar(200, achada[1], achada[0], cache="private, max-age=300")
        if caminho == "/api/biblioteca":
            return self._json(200, biblioteca.listar(raiz) if raiz.is_dir() else {"obras": [], "versao": ""})

        if caminho == "/api/versao":
            return self._json(200, {"versao": biblioteca.versao(raiz) if raiz.is_dir() else ""})

        if caminho == "/api/celular/estado":
            return self._json(200, self.server.celular.estado())  # type: ignore[attr-defined]

        if caminho == "/api/traducao/estado":
            tarefa: TarefaTraducao = self.server.traducao  # type: ignore[attr-defined]
            return self._json(200, tarefa.instantaneo(max(self._numero(consulta, "log", 0), 0)))

        if caminho == "/api/traducao/config":
            return self._json(200, {**config.ler(), "motores": config.MOTORES})

        if caminho == "/api/refinar/pendentes":
            alvos = self._alvos_refino({})
            return self._json(200, {"capitulos": len(alvos)})

        if caminho == "/api/manual/estado":
            return self._json(200, manual.instantaneo(
                self._numero(consulta, "ex", -1), max(self._numero(consulta, "log", 0), 0), self._numero(consulta, "cv", -1)
            ))

        if caminho.startswith("/api/manual/imagem/"):
            texto = caminho[len("/api/manual/imagem/"):]
            achado = manual.colecao.dados_de(int(texto)) if texto.isdigit() else None
            if achado is None:
                return self._negar(404, "Imagem não encontrada.")
            dados, formato = achado
            tipo = TIPOS_IMAGEM.get("." + formato)
            if tipo is None:
                return self._negar(404, "Imagem não encontrada.")
            # ids nunca se repetem durante a execução, então a miniatura pode ficar em cache.
            return self._enviar(200, tipo, dados, cache="private, max-age=3600")

        return self._negar(404, "Endereço desconhecido.")

    # ------------------------------------------------------------ POST

    def do_POST(self) -> None:
        partes = urlsplit(self.path)
        self.close_connection = True   # recusas abaixo não leem o corpo: não reaproveitar a conexão
        if not self._autorizado(parse_qs(partes.query), metodo_post=True):
            return self._negar()
        if not (self.headers.get("Content-Type", "").lower().startswith("application/json")):
            return self._negar(415, "Use application/json.")
        try:
            tamanho = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._negar(400, "Requisição inválida.")
        if not 0 <= tamanho <= MAX_CORPO:
            return self._negar(413, "Requisição grande demais.")
        self.close_connection = False
        try:
            dados = json.loads(self.rfile.read(tamanho) or b"{}")
            if not isinstance(dados, dict):
                raise ValueError
        except ValueError:
            return self._negar(400, "JSON inválido.")

        manual: SessaoManual = self.server.manual  # type: ignore[attr-defined]
        raiz: Path = self.server.raiz  # type: ignore[attr-defined]
        caminho = partes.path

        if caminho == "/api/traduzir":
            return self._traduzir(dados)

        if caminho == "/api/traducao/reajustar":
            return self._reajustar(dados)

        if caminho == "/api/traducao/config":
            try:
                nova = config.salvar(dados.get("motor"), dados.get("modelo"))
            except ValueError as erro:
                return self._negar(400, str(erro))
            return self._json(200, {**nova, "motores": config.MOTORES})

        if caminho == "/api/refinar":
            alvos = self._alvos_refino(dados)
            try:
                n = self.server.traducao.iniciar_refino(alvos)  # type: ignore[attr-defined]
            except ErroBaixador as erro:
                return self._negar(422, str(erro))
            except RuntimeError as erro:
                return self._negar(409, str(erro))
            return self._json(200, {"ok": True, "capitulos": n})

        if caminho == "/api/traducao/openrouter":
            return self._json(200, openrouter.verificar())
        if caminho == "/api/traducao/gemini":
            return self._json(200, gemini.verificar())

        if caminho == "/api/traducao/excluir":
            if self.server.traducao.estado == "executando":  # type: ignore[attr-defined]
                return self._negar(409, "Há uma tradução em andamento. Espere terminar ou cancele antes de excluir traduções.")
            obra, rel = str(dados.get("obra", ""))[:120], str(dados.get("rel", ""))[:300]
            if not obra and not rel:
                return self._negar(400, "Informe o capítulo ou a obra.")
            alvos = [
                raiz / c["rel"] for o in biblioteca.listar(raiz)["obras"]
                if not obra or organizacao._chave(o["nome"]) == organizacao._chave(obra)
                for c in o["capitulos"] if c["traduzido"] and (not rel or c["rel"] == rel)
            ]
            apagadas = 0
            try:
                for alvo in alvos:
                    arquivo = alvo / "traducao.json"
                    if arquivo.is_file() and not arquivo.is_symlink():
                        arquivo.unlink()
                        apagadas += 1
                    pipeline.apagar_residuos(alvo)
            except OSError as erro:
                return self._negar(500, f"Não foi possível apagar a tradução: {erro}")
            if not apagadas:
                return self._negar(404, "Não há tradução para excluir.")
            biblioteca.esquecer_versao()
            return self._json(200, {"ok": True, "traducoes": apagadas})

        if caminho == "/api/traducao/hy":
            return self._json(200, hymt.verificar(str(dados.get("modelo") or "") or None))

        if caminho == "/api/traducao/cancelar":
            self.server.traducao.parar()  # type: ignore[attr-defined]
            return self._json(200, {"ok": True})

        if caminho == "/api/traducao/cancelar-item":
            r = self.server.traducao.cancelar_item(str(dados.get("rel") or ""))  # type: ignore[attr-defined]
            if not r:
                return self._negar(409, "Esse capítulo não está mais na fila (ou use Cancelar para parar tudo).")
            return self._json(200, {"ok": True, "onde": r})

        if caminho == "/api/traducao/abrir-leitor":
            return self._abrir_leitor(self.server.traducao.pasta)  # type: ignore[attr-defined]

        if caminho.startswith("/api/bloco/"):
            return self._editar_bloco(caminho, dados)

        if caminho.startswith("/api/manual/"):
            return self._post_manual(manual, caminho[len("/api/manual/"):], dados)

        if caminho == "/api/biblioteca/capitulo":
            try:
                novo = biblioteca.reorganizar_capitulo(
                    raiz, str(dados.get("rel", ""))[:300], str(dados.get("obra", ""))[:120],
                    dados.get("numero"), str(dados.get("titulo", ""))[:120],
                )
            except ErroBaixador as erro:
                return self._negar(422, str(erro))
            except OSError as erro:
                return self._negar(500, f"Não foi possível mover a pasta: {erro}")
            return self._json(200, {"ok": True, "rel": novo})

        if caminho == "/api/biblioteca/obra":
            try:
                n = biblioteca.renomear_obra(raiz, str(dados.get("obra", ""))[:120], str(dados.get("novo", ""))[:120])
            except ErroBaixador as erro:
                return self._negar(422, str(erro))
            except OSError as erro:
                return self._negar(500, f"Não foi possível mover as pastas: {erro}")
            return self._json(200, {"ok": True, "capitulos": n})

        if caminho == "/api/biblioteca/obra/excluir":
            if self.server.traducao.estado == "executando":  # type: ignore[attr-defined]
                return self._negar(409, "Há uma tradução em andamento. Espere terminar ou cancele antes de excluir.")
            if manual.salvando:
                return self._negar(409, "Há imagens sendo salvas agora. Espere terminar antes de excluir.")
            try:
                r = biblioteca.excluir_obra(raiz, str(dados.get("obra", ""))[:120])
            except ErroBaixador as erro:
                return self._negar(422, str(erro))
            except OSError as erro:
                return self._negar(500, f"Não foi possível apagar tudo: {erro}")
            return self._json(200, {"ok": True, **r})

        if caminho == "/api/biblioteca/excluir-tudo":
            if str(dados.get("confirmacao", "")) != "APAGAR TUDO":
                return self._negar(400, "Confirmação ausente: nada foi apagado.")
            if self.server.traducao.estado == "executando":  # type: ignore[attr-defined]
                return self._negar(409, "Há uma tradução em andamento. Espere terminar ou cancele antes de apagar.")
            if manual.salvando:
                return self._negar(409, "Há imagens sendo salvas agora. Espere terminar antes de apagar.")
            try:
                r = biblioteca.excluir_tudo(raiz)
            except ErroBaixador as erro:
                return self._negar(422, str(erro))
            except OSError as erro:
                return self._negar(500, f"Não foi possível apagar tudo: {erro}")
            return self._json(200, {"ok": True, **r})

        if caminho == "/api/capa/baixar":
            return self._baixar_capa(manual, raiz, dados)

        if caminho == "/api/biblioteca/abrir-pasta":
            alvo = raiz
            rel = str(dados.get("rel", ""))[:300]
            if rel:
                achado = next((c for c in biblioteca.listar(raiz)["obras"] for c in c["capitulos"] if c["rel"] == rel), None)
                if achado is None:
                    return self._negar(404, "Capítulo não encontrado.")
                alvo = raiz / rel
            if not alvo.is_dir():
                return self._negar(404, "A pasta ainda não existe.")
            try:
                _abrir_no_sistema(alvo)
            except OSError as erro:
                return self._negar(500, f"Não foi possível abrir a pasta: {erro}")
            return self._json(200, {"ok": True})

        if caminho in ("/api/celular/ligar", "/api/celular/desligar", "/api/celular/trocar-chave"):
            celular: ControleCelular = self.server.celular  # type: ignore[attr-defined]
            lembrar = dados.get("lembrar")
            lembrar = lembrar if isinstance(lembrar, bool) else None
            try:
                if caminho.endswith("/ligar"):
                    celular.ligar(lembrar)
                elif caminho.endswith("/desligar"):
                    celular.desligar(lembrar)
                else:
                    celular.trocar_chave()
            except RuntimeError as erro:
                return self._negar(409, str(erro))
            return self._json(200, celular.estado())

        if caminho == "/api/celular/tailscale":              # nome *.ts.net deste notebook (digitado ou detectado)
            celular = self.server.celular  # type: ignore[attr-defined]
            try:
                if dados.get("detectar"):
                    achado = celular_servidor.detectar_tailscale()
                    if not achado:
                        return self._negar(404, "Não consegui perguntar ao Tailscale. Ele está instalado e conectado neste notebook? Você pode digitar o nome à mão.")
                    celular.definir_tailscale(achado)
                else:
                    celular.definir_tailscale(str(dados.get("host", "")))
            except ValueError as erro:
                return self._negar(400, str(erro))
            return self._json(200, celular.estado())

        return self._negar(404, "Endereço desconhecido.")

    def _baixar_capa(self, manual: SessaoManual, raiz: Path, dados: Dict[str, Any]) -> None:
        """Botão "Baixar capa" / "Atualizar capa": busca na página da obra, com o navegador aberto. Falha não toca na biblioteca."""
        pasta = str(dados.get("pasta", ""))
        if not pasta or "/" in pasta or "\\" in pasta or pasta in (".", "..") or pasta.startswith("."):
            return self._negar(400, "Obra inválida.")
        pasta_obra = raiz / pasta
        if not pasta_obra.is_dir() or pasta_obra.is_symlink() or pasta_obra.parent.resolve() != raiz.resolve():
            return self._negar(404, "Pasta da obra não encontrada.")
        url = dados_obra.url_principal(pasta_obra) or dados_obra.url_dos_capitulos(pasta_obra) or ""
        if not url:
            return self._negar(422, "Não sei o endereço da página desta obra. Baixe um capítulo dela de novo pelo programa para eu guardar o endereço.")
        substituir = bool(dados.get("substituir"))
        if substituir is False and capa_obra.achar(pasta_obra) is not None:
            return self._negar(409, "Esta obra já tem capa. Use “Atualizar capa” para trocar.")

        def salvar_capa(imagem: bytes, origem: str) -> Optional[str]:
            if capa_obra.gravar(pasta_obra, imagem, substituir) is None:
                return None
            dados_obra.gravar(pasta_obra, pasta, url)
            biblioteca.esquecer_versao()
            return origem

        # 1) direto, sem abrir nada (funciona em sites sem verificação)
        if not manual.navegador_pronto():
            imagem, motivo = capa_obra.procurar(url, capa_obra.baixar_direto)
            if imagem and salvar_capa(imagem, ""):
                return self._json(200, {"ok": True, "mensagem": "Capa baixada e salva na pasta da obra."})
        # 2) pelo navegador: usa o que já está aberto; senão abre sozinho a página da obra (com login/verificação do site)
        aberto_por_nos = False
        if not manual.navegador_pronto():
            if manual.estado in ESTADOS_ATIVOS or manual.automatico_ativo or manual.salvando:
                return self._negar(409, "O navegador está ocupado (abrindo ou baixando). Espere terminar e tente de novo.")
            try:
                manual.abrir(url, str(dados.get("navegador", "auto")), str(dados.get("caminho", "")) or None,
                             str(dados.get("perfil", "proprio")) if str(dados.get("perfil", "proprio")) in ("proprio", "temporario") else "proprio",
                             bloquear_abas=bool(dados.get("bloquear_abas", True)))
            except (RuntimeError, ValueError, ErroBaixador) as erro:
                return self._negar(422, f"Não consegui abrir o navegador: {erro}")
            aberto_por_nos = True
            fim = time.monotonic() + 60
            while time.monotonic() < fim and manual.estado == "abrindo":
                time.sleep(0.3)
            if manual.estado != "aguardando":
                return self._negar(422, f"O navegador não abriu ({manual.erro or manual.estado}).")
        ok, mensagem = manual.baixar_capa(pasta_obra, url, substituir)
        if ok:
            dados_obra.gravar(pasta_obra, pasta, url)
            biblioteca.esquecer_versao()
            if aberto_por_nos:
                manual.fechar_navegador()                      # só fecha o que nós abrimos, e só quando deu certo
            return self._json(200, {"ok": True, "mensagem": mensagem})
        extra = " O navegador ficou aberto na página da obra: resolva o login/verificação nela e clique de novo." if aberto_por_nos else ""
        return self._negar(422, mensagem + extra)

    def _traduzir(self, dados: Dict[str, Any]) -> None:
        tarefa = self.server.traducao  # type: ignore[attr-defined]
        raiz: Path = self.server.raiz  # type: ignore[attr-defined]
        de, para = str(dados.get("de", "en")), str(dados.get("para", "pt"))
        if de not in IDIOMAS_ORIGEM or para not in IDIOMAS_DESTINO or de == para:
            return self._negar(400, "O destino da tradução é sempre o português; escolha um idioma de origem diferente.")
        lote = str(dados.get("lote", ""))
        try:
            if lote in ("todos", "pendentes"):
                obra = str(dados.get("obra", ""))[:120]
                lista = [
                    raiz / c["rel"] for o in biblioteca.listar(raiz)["obras"]
                    if not obra or organizacao._chave(o["nome"]) == organizacao._chave(obra)
                    for c in o["capitulos"] if lote == "todos" or not c["traduzido"]
                ]
                if not lista:
                    return self._negar(404, "Nenhum capítulo para traduzir.")
                tarefa.iniciar_lote(lista, de, para)
                return self._json(200, {"ok": True, "conjuntos": len(lista)})
            if isinstance(dados.get("rels"), list):                      # capítulos escolhidos à mão (retraduzir)
                pedidos = {str(r)[:300] for r in dados["rels"]}
                lista = [raiz / c["rel"] for o in biblioteca.listar(raiz)["obras"] for c in o["capitulos"] if c["rel"] in pedidos]
                if not lista:
                    return self._negar(404, "Nenhum dos capítulos escolhidos foi encontrado.")
                tarefa.iniciar_lote(lista, de, para)
                return self._json(200, {"ok": True, "conjuntos": len(lista)})
            achado = next((c for o in biblioteca.listar(raiz)["obras"] for c in o["capitulos"] if c["rel"] == str(dados.get("rel", ""))), None)
            if achado is None:
                return self._negar(404, "Capítulo não encontrado. Baixe as imagens antes de traduzir.")
            if dados.get("completar"):
                if not achado.get("incompleta"):
                    return self._negar(409, "Este capítulo não tem páginas sem tradução para completar.")
                tarefa.iniciar(raiz / achado["rel"], de, para, completar=True)
            else:
                tarefa.iniciar(raiz / achado["rel"], de, para)
        except RuntimeError as erro:
            return self._negar(409, str(erro))
        return self._json(200, {"ok": True})

    def _alvos_refino(self, dados: Dict[str, Any]) -> List[Path]:
        """Capítulos traduzidos (opcionalmente de uma obra ou um só) que ainda têm o que refinar."""
        raiz: Path = self.server.raiz  # type: ignore[attr-defined]
        obra, rel = str(dados.get("obra", ""))[:120], str(dados.get("rel", ""))[:300]
        lista = [
            raiz / c["rel"] for o in biblioteca.listar(raiz)["obras"]
            if not obra or organizacao._chave(o["nome"]) == organizacao._chave(obra)
            for c in o["capitulos"] if c["traduzido"] and (not rel or c["rel"] == rel)
        ]
        return [p for p in lista if refino.pendentes(p) > 0]

    def _exportar(self, consulta: Dict[str, List[str]]) -> None:
        """Monta o ZIP num arquivo temporário (não na memória) e o envia como download. Só lê a biblioteca."""
        raiz: Path = self.server.raiz  # type: ignore[attr-defined]
        rels, obra = consulta.get("rel", []), (consulta.get("obra") or [""])[0]
        if not (rels or obra):
            return self._negar(400, "Escolha capítulos (rel=) ou uma obra (obra=) para exportar.")
        pronto = exportar.zip_temporario(raiz, rels, obra)
        if pronto is None:
            return self._negar(404, "Nenhum capítulo encontrado para exportar.")
        arquivo, tamanho, nome = pronto
        with arquivo:
            exportar.transmitir(self, arquivo, tamanho, nome)

    def _reajustar(self, dados: Dict[str, Any]) -> None:
        raiz: Path = self.server.raiz  # type: ignore[attr-defined]
        if self.server.traducao.bloqueia_edicao:  # type: ignore[attr-defined]
            return self._negar(409, "Há uma tradução em andamento; espere terminar.")
        obra = str(dados.get("obra", ""))[:120]
        rel = str(dados.get("rel", ""))[:300]
        rels = {str(r)[:300] for r in dados["rels"]} if isinstance(dados.get("rels"), list) else None
        alvos = [
            raiz / c["rel"] for o in biblioteca.listar(raiz)["obras"]
            if not obra or organizacao._chave(o["nome"]) == organizacao._chave(obra)
            for c in o["capitulos"]
            if c["traduzido"] and (not rel or c["rel"] == rel) and (rels is None or c["rel"] in rels)
        ]
        alvos = [a for a in alvos if (a / "traducao.json").is_file()]
        if not alvos:
            return self._negar(404, "Não há tradução feita para reajustar.")
        total = {"imagens": 0, "trechos": 0}
        try:
            for alvo in alvos:
                r = edicao.reajustar_pasta(alvo)
                total["imagens"] += r["imagens"]
                total["trechos"] += r["trechos"]
        except ErroBaixador as erro:
            return self._negar(422, str(erro))
        total["conjuntos"] = len(alvos)
        return self._json(200, total)

    def _editar_bloco(self, caminho: str, dados: Dict[str, Any]) -> None:
        pasta = self._pasta_do_leitor(str(dados.get("base", ""))[:400])
        if pasta is None or not pasta.is_dir():
            return self._negar(404, "Conjunto não encontrado. Reabra o leitor pelo programa.")
        if self.server.traducao.bloqueia_edicao:  # type: ignore[attr-defined]
            return self._negar(409, "Há uma tradução em andamento; espere terminar para editar.")
        if caminho == "/api/bloco/capitulo":
            try:
                antigo = json.loads((pasta / "traducao.json").read_text(encoding="utf-8"))
                de, para = antigo.get("de", "en"), "pt"          # destino sempre português, mesmo em traduções antigas
            except (OSError, ValueError, AttributeError):
                de, para = "en", "pt"
            if de not in IDIOMAS_ORIGEM or de == para:
                de, para = "en", "pt"
            try:
                self.server.traducao.iniciar(pasta, de, para)  # type: ignore[attr-defined]
            except RuntimeError as erro:
                return self._negar(409, str(erro))
            return self._json(200, {"ok": True})
        try:
            resultado = edicao.editar(pasta, caminho[len("/api/bloco/"):], dados, self.server.motores)  # type: ignore[attr-defined]
        except ErroBaixador as erro:
            return self._negar(422, str(erro))
        except ModuleNotFoundError as erro:
            traceback.print_exc()
            return self._negar(
                500,
                f"Falta o pacote Python '{erro.name}' neste ambiente. Com o .venv ativado, rode: "
                "pip install -r requirements-traducao.txt (e reinicie o programa).",
            )
        except Exception as erro:
            traceback.print_exc()
            return self._negar(500, f"Erro inesperado ({erro.__class__.__name__}: {str(erro)[:160]}). Detalhes no terminal.")
        return self._json(200, resultado)


    def _abrir_leitor(self, pasta: Optional[Path]) -> None:
        """Abre no navegador padrão o leitor global no capítulo da `pasta` (que precisa ter imagens)."""
        if pasta is None or not listar_imagens(pasta):
            return self._negar(404, "Ainda não há imagens salvas para ler.")
        try:
            leitores = self.server.leitores  # type: ignore[attr-defined]
            raiz, rel = pasta.parent, pasta.name         # pasta de fora da biblioteca: o pai dela vira uma "raiz" só para leitura
            try:
                rp, rb = pasta.resolve(), PASTA_PADRAO.resolve()
                if rp != rb and rp.is_relative_to(rb):   # dentro da biblioteca: usa a biblioteca (navegação entre capítulos)
                    raiz, rel = rb, rp.relative_to(rb).as_posix()
            except OSError:
                pass
            identificador = next((k for k, v in leitores.items() if v == raiz), None)
            if identificador is None:
                identificador = secrets.token_urlsafe(6)
                leitores[identificador] = raiz
            numero = self.server.server_address[1]  # type: ignore[attr-defined]
            endereco = (
                f"http://127.0.0.1:{numero}/leitor?c={quote(rel, safe='')}&r={quote(identificador, safe='')}"
                f"&t={self.server.token}"  # type: ignore[attr-defined]
            )
            if not webbrowser.open(endereco):
                return self._negar(500, "Não foi possível abrir o navegador padrão.")
        except OSError as erro:
            return self._negar(500, f"Não foi possível abrir a página: {erro}")
        return self._json(200, {"ok": True})

    def _post_manual(self, manual: SessaoManual, acao: str, dados: Dict[str, Any]) -> None:
        try:
            if acao == "abrir":
                url = str(dados.get("url", "")).strip()
                if not url or len(url) > 2048:
                    return self._negar(400, "Informe a URL do site.")
                if "://" not in url:
                    url = "https://" + url
                perfil = str(dados.get("perfil", "proprio"))
                if perfil not in ("proprio", "temporario"):
                    return self._negar(400, "Perfil inválido.")
                manual.abrir(
                    url, str(dados.get("navegador", "auto")), str(dados.get("caminho", "")) or None, perfil,
                    bloquear_abas=bool(dados.get("bloquear_abas", True)),
                )
            elif acao == "automatico":
                url = str(dados.get("url", "")).strip()
                pasta = str(dados.get("pasta", "")).strip()
                if not url or len(url) > 2048:
                    return self._negar(400, "Informe a URL do site.")
                if not pasta or len(pasta) > 400:
                    return self._negar(400, "Informe a pasta de destino.")
                if "://" not in url:
                    url = "https://" + url
                perfil = str(dados.get("perfil", "proprio"))
                if perfil not in ("proprio", "temporario"):
                    return self._negar(400, "Perfil inválido.")
                espera = dados.get("espera", 30)
                if isinstance(espera, bool) or not isinstance(espera, (int, float)):
                    return self._negar(400, "O tempo de espera deve ser um número.")
                organizar = None
                if "obra" in dados:                       # organização por obra: capítulo identificado pela aba
                    organizar = {
                        "obra": str(dados.get("obra", ""))[:120], "numero": str(dados.get("numero", ""))[:10],
                        "titulo": str(dados.get("titulo", ""))[:120],
                    }
                ao_concluir: Optional[Callable[[List[Path]], None]] = None
                if bool(dados.get("traduzir", False)) and bool(dados.get("continuar", False)) and organizar is not None:
                    de, para = str(dados.get("trad_de", "en")), str(dados.get("trad_para", "pt"))
                    if de not in IDIOMAS_ORIGEM or para not in IDIOMAS_DESTINO or de == para:
                        return self._negar(400, "Escolha idiomas de origem e de destino diferentes para a tradução automática.")
                    tarefa = self.server.traducao  # type: ignore[attr-defined]

                    ao_concluir = lambda pastas, tarefa=tarefa, de=de, para=para: tarefa.iniciar_lote(pastas, de, para)  # noqa: E731

                manual.automatico(
                    url, pasta if organizar is not None else pasta_do_conjunto(pasta, self._conjunto_dos_dados(dados)),
                    str(dados.get("navegador", "auto")), str(dados.get("caminho", "")) or None, perfil,
                    bloquear_abas=bool(dados.get("bloquear_abas", True)),
                    espera=max(5, min(int(espera), 300)),
                    ignorar_comentarios=bool(dados.get("ignorar_comentarios", True)),
                    organizar=organizar,
                    continuar=bool(dados.get("continuar", False)) and organizar is not None,
                    modo_busca="carregamento" if str(dados.get("modo_busca", "")) == "carregamento" else "rapido",
                    ao_concluir=ao_concluir,
                    pular_primeiro=bool(dados.get("atualizar", False)),
                )
            elif acao == "continuar":
                manual.definir_continuar(bool(dados.get("ativo", False)))
            elif acao == "procurar":
                espera = dados.get("espera", 30)
                if isinstance(espera, bool) or not isinstance(espera, (int, float)):
                    return self._negar(400, "O tempo de espera deve ser um número.")
                espera = max(5, min(int(espera), 300))
                modo = str(dados.get("modo", "rapido"))
                if modo not in ("carregamento", "rapido"):
                    return self._negar(400, "Modo de busca inválido.")
                manual.procurar(bool(dados.get("ignorar_comentarios", True)), espera, modo)
            elif acao == "proximo":
                manual.proximo_capitulo()
            elif acao == "cancelar":
                manual.cancelar_busca()
            elif acao == "fechar":
                manual.fechar_navegador()
            elif acao == "limpar":
                manual.limpar_lista()
            elif acao == "limpar-tudo":
                manual.limpar_tudo()
            elif acao == "baixar":
                ids = dados.get("indices")
                pasta = str(dados.get("pasta", "")).strip()
                if (
                    not isinstance(ids, list) or not ids or len(ids) > 500
                    or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids)
                ):
                    return self._negar(400, "Marque ao menos uma imagem.")
                if not pasta or len(pasta) > 400:
                    return self._negar(400, "Informe a pasta de destino.")
                base_dir = Path(pasta).expanduser()
                if "obra" in dados and str(dados.get("obra", "")).strip() and base_dir.is_dir():   # obra já existente: nada de pasta duplicada
                    r = biblioteca.resolver_obra(base_dir, str(dados.get("obra", ""))[:120], str((dados.get("meta") or {}).get("url", ""))[:500] if isinstance(dados.get("meta"), dict) else "")
                    if r["existente"]:
                        dados = {**dados, "obra": r["obra"]}
                        if isinstance(dados.get("meta"), dict):
                            dados["meta"] = {**dados["meta"], "obra": r["obra"]}
                conjunto = self._conjunto_dos_dados(dados)
                meta = dados.get("meta")
                if isinstance(meta, dict) and str(meta.get("obra", "")).strip():
                    meta = {
                        "obra": str(meta.get("obra", ""))[:120], "numero": str(meta.get("numero", ""))[:10],
                        "titulo": str(meta.get("titulo", ""))[:120], "url": str(meta.get("url", ""))[:500],
                    }
                else:
                    meta = None
                destino = pasta_do_conjunto(pasta, conjunto)
                if meta is not None and "obra" in dados:
                    existente = self._capitulo_duplicado(base_dir, meta["obra"], meta["numero"], meta["titulo"], meta["url"])
                    if existente and not manual.salvando_neste_destino(Path(destino)):
                        return self._negar(409, f"Este capítulo já existe na biblioteca ({existente}). Não baixei de novo para não duplicar.")
                return self._json(200, manual.baixar(ids, destino, meta))
            elif acao == "abrir-leitor":
                return self._abrir_leitor(manual.pasta_destino())
            elif acao == "abrir-pasta":
                pasta_destino = manual.pasta_destino()
                if pasta_destino is None or not pasta_destino.is_dir():
                    return self._negar(404, "A pasta ainda não existe.")
                try:
                    _abrir_no_sistema(pasta_destino)
                except OSError as erro:
                    return self._negar(500, f"Não foi possível abrir a pasta: {erro}")
            else:
                return self._negar(404, "Endereço desconhecido.")
        except (ValueError, ErroBaixador) as erro:
            return self._negar(400, str(erro))
        except RuntimeError as erro:
            return self._negar(409, str(erro))
        return self._json(200, {"ok": True})


def criar_servidor(
    token: str, porta: int = 0, manual: Optional[SessaoManual] = None, raiz: Optional[Path] = None,
    celular: Optional[ControleCelular] = None,
) -> ThreadingHTTPServer:
    """Cria o servidor preso a 127.0.0.1 (porta 0 = escolhe uma livre)."""
    servidor = ServidorSilencioso(("127.0.0.1", porta), Manipulador)
    servidor.daemon_threads = True
    numero = servidor.server_address[1]
    servidor.raiz = Path(raiz) if raiz is not None else PASTA_PADRAO  # type: ignore[attr-defined]
    servidor.manual = manual if manual is not None else SessaoManual()  # type: ignore[attr-defined]
    servidor.traducao = TarefaTraducao()  # type: ignore[attr-defined]
    servidor.motores = Motores()  # type: ignore[attr-defined]
    servidor.celular = celular if celular is not None else ControleCelular(servidor.raiz)  # type: ignore[attr-defined]
    servidor.leitores = {ID_BIBLIOTECA: servidor.raiz}  # type: ignore[attr-defined]
    servidor.token = token  # type: ignore[attr-defined]
    servidor.hosts = {f"127.0.0.1:{numero}", f"localhost:{numero}"}  # type: ignore[attr-defined]
    servidor.origens = {f"http://{h}" for h in servidor.hosts}  # type: ignore[attr-defined]
    return servidor


def abrir_interface(abrir_navegador: bool = True) -> int:
    aviso_pasta = migrar_pasta_biblioteca()
    if aviso_pasta:
        print(aviso_pasta)
    PASTA_PADRAO.mkdir(parents=True, exist_ok=True)
    migrar_dados_antigos()
    try:                                                  # leva capítulos antigos para obras/Obra/Capítulo (só move, nunca apaga)
        relatorio = estrutura.normalizar(PASTA_PADRAO)
        if relatorio["movidos"]:
            print(f"Biblioteca organizada em Obra/Capítulo: {len(relatorio['movidos'])} pasta(s) movida(s).")
        for erro in relatorio["erros"]:
            print(f"Aviso (biblioteca): {erro}")
    except Exception as erro:
        print(f"Aviso: não consegui organizar a biblioteca antiga ({erro.__class__.__name__}); nada foi perdido.")
    try:                                                  # imagens de cada capítulo em Capítulo/img (os .json ficam na raiz do capítulo)
        relatorio = estrutura.mover_imagens_para_img(PASTA_PADRAO)
        if relatorio["capitulos"]:
            print(f"Biblioteca: imagens de {len(relatorio['capitulos'])} capítulo(s) movidas para a subpasta img/ (os .json ficam na pasta do capítulo).")
        for erro in relatorio["erros"]:
            print(f"Aviso (biblioteca): {erro}")
    except Exception as erro:
        print(f"Aviso: não consegui mover as imagens para img/ ({erro.__class__.__name__}); nada foi perdido e o leitor continua achando.")
    try:                                                  # glossários antigos de cada capítulo -> um só na pasta da obra
        relatorio = ia.migrar_glossarios(PASTA_PADRAO)
        if relatorio["obras"]:
            print(f"Glossário: unificado por obra em {len(relatorio['obras'])} obra(s): {', '.join(relatorio['obras'])}.")
        for erro in relatorio["erros"]:
            print(f"Aviso (glossário): {erro}")
    except Exception as erro:
        print(f"Aviso: não consegui unificar os glossários ({erro.__class__.__name__}); nada foi perdido.")
    token = secrets.token_urlsafe(24)
    servidor = criar_servidor(token, celular=ControleCelular(PASTA_PADRAO, ARQUIVO_CELULAR))
    endereco = f"http://127.0.0.1:{servidor.server_address[1]}/?t={token}"
    if servidor.celular.ligar_ao_abrir:  # type: ignore[attr-defined]
        try:
            servidor.celular.ligar()  # type: ignore[attr-defined]
        except RuntimeError as erro:
            print(f"Aviso: {erro}")
    print("Baixador de Imagens em:")
    print(f"  {endereco}")
    print("Se a página não abrir sozinha, copie o endereço acima no navegador.")
    print("Este endereço só funciona neste computador. Pressione Ctrl+C aqui para encerrar.")
    if abrir_navegador:
        try:
            webbrowser.open(endereco)
        except Exception:
            pass
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando...")
    finally:
        servidor.celular.desligar()  # type: ignore[attr-defined]
        servidor.manual.encerrar()  # type: ignore[attr-defined]
        servidor.traducao.parar()  # type: ignore[attr-defined]
        servidor.server_close()
    return 0
