"""Navegador headless (Playwright): captura de tela e coleta de imagens dinâmicas.

Estratégia de uso de recursos: o navegador só é iniciado quando necessário, é
reutilizado entre as operações e fechado ao final. Prefere o Microsoft Edge (já
instalado no Windows) e o Chrome; só usa o Chromium do Playwright se nenhum dos
dois existir.
"""

from __future__ import annotations

import threading
from functools import lru_cache
from typing import List, Optional
from urllib.parse import urlsplit

from baixador.navegador import navegadores
from baixador.nucleo import seguranca
from baixador.nucleo.erros import Cancelado, CapturaIndisponivel, ErroBaixador

_ESQUEMAS_LOCAIS = ("data:", "blob:", "about:")


# Imagens realmente exibidas e já carregadas, com tamanho relevante.
@lru_cache(maxsize=256)
def _host_liberado(host: str) -> bool:
    try:
        seguranca.verificar_host_publico(host)
        return True
    except ErroBaixador:
        return False


def _requisicao_permitida(url: str) -> bool:
    if url.lower().startswith(_ESQUEMAS_LOCAIS):
        return True
    try:
        partes = urlsplit(url)
        return partes.scheme.lower() in seguranca.ESQUEMAS_PERMITIDOS and bool(
            partes.hostname and _host_liberado(partes.hostname)
        )
    except ValueError:
        return False


def _filtrar(rota) -> None:
    """Aborta qualquer requisição do navegador para rede interna ou esquema inseguro."""
    if _requisicao_permitida(rota.request.url):
        rota.continue_()
    else:
        rota.abort()


class Capturador:
    """Gerenciador de contexto que abre o navegador sob demanda.

    mostrar:   abre a janela do navegador de verdade (em vez de headless).
    parar:     Event; quando acionado, a operação em curso levanta `Cancelado`.
    """

    def __init__(
        self,
        timeout: float,
        mostrar: bool = False,
        parar: Optional[threading.Event] = None,
        navegador: str = "auto",
        caminho_navegador: Optional[str] = None,
        perfil_persistente: bool = False,
        args_extras: Optional[List[str]] = None,
    ):
        self._timeout_ms = int(timeout * 1000)
        self._mostrar = mostrar
        self._parar = parar
        self._escolha = navegador
        self._caminho = caminho_navegador
        self._perfil = perfil_persistente
        self._args_extras = list(args_extras or [])
        self._pw = None
        self._navegador = None
        self._contexto_persistente = None
        self._contexto_fechado = False

    def __enter__(self) -> "Capturador":
        return self

    def __exit__(self, *_exc) -> None:
        self.fechar()

    def fechar(self) -> None:
        alvos = ((self._contexto_persistente, "close"), (self._navegador, "close"), (self._pw, "stop"))
        for objeto, metodo in alvos:
            if objeto is not None:
                try:
                    getattr(objeto, metodo)()
                except Exception:
                    pass
        self._navegador = self._pw = self._contexto_persistente = None

    # ------------------------------------------------------------------ infraestrutura

    def checar(self) -> None:
        if self._parar is not None and self._parar.is_set():
            raise Cancelado("Operação cancelada pelo usuário.")

    def _iniciar_playwright(self):
        """Inicia o Playwright e devolve (classe de erro, lista de tentativas de abertura)."""
        try:
            from playwright.sync_api import Error as ErroPlaywright
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise CapturaIndisponivel(
                "O Playwright não está instalado. Na pasta do projeto, rode: python -m pip install -r requirements.txt"
            ) from None

        try:
            opcoes = navegadores.tentativas(self._escolha, self._caminho)
        except ValueError as erro:
            raise CapturaIndisponivel(str(erro)) from None

        if self._pw is None:
            try:
                self._pw = sync_playwright().start()
            except Exception as erro:
                raise CapturaIndisponivel(f"Não foi possível iniciar o Playwright: {erro}") from None
        return ErroPlaywright, opcoes

    def _falha_ao_abrir(self, ultimo_erro: str) -> CapturaIndisponivel:
        self.fechar()
        if self._escolha == "auto":
            return CapturaIndisponivel(
                "Nenhum navegador compatível encontrado (Edge, Chrome, Brave ou Chromium do Playwright). "
                "Instale um deles ou rode: python -m playwright install chromium"
            )
        nome = navegadores.NOMES[self._escolha]
        dica = " Se esse perfil estiver aberto em outra janela do programa, feche-a." if self._perfil else ""
        return CapturaIndisponivel(
            f"Não foi possível abrir o navegador escolhido ({nome}): {ultimo_erro}.{dica}"
        )

    def iniciar(self) -> None:
        """Abre o navegador (perfil temporário). Com perfil próprio, quem abre é `nova_pagina`."""
        if self._navegador is not None or self._contexto_persistente is not None:
            return
        ErroPlaywright, opcoes = self._iniciar_playwright()
        ultimo_erro = ""
        for argumentos in opcoes:
            try:
                self._navegador = self._pw.chromium.launch(
                    headless=not self._mostrar, args=self._args_extras or None, **argumentos
                )
                return
            except ErroPlaywright as erro:
                ultimo_erro = _resumo(erro)
        raise self._falha_ao_abrir(ultimo_erro)

    def conectado(self) -> bool:
        """False se o navegador foi fechado (por exemplo, pelo usuário, na janela)."""
        try:
            if self._contexto_persistente is not None:
                return not self._contexto_fechado
            return self._navegador is not None and self._navegador.is_connected()
        except Exception:
            return False

    def _abrir_com_perfil(self, javascript: bool):
        """Abre o navegador com um perfil próprio e persistente do programa.

        Diferente do perfil temporário, este carrega extensões instaladas, mantém logins e as
        configurações do navegador (como o bloqueador de anúncios do Brave). Para isso são
        liberados três parâmetros que o Playwright desliga por padrão: as extensões e as
        atualizações em segundo plano (listas de bloqueio e extensões).
        """
        ErroPlaywright, opcoes = self._iniciar_playwright()
        ultimo_erro = ""
        for argumentos in opcoes:
            try:
                pasta = navegadores.pasta_do_perfil(argumentos)
                contexto = self._pw.chromium.launch_persistent_context(
                    str(pasta),
                    headless=not self._mostrar,
                    no_viewport=True,
                    java_script_enabled=javascript,
                    accept_downloads=False,
                    service_workers="block",
                    args=self._args_extras or None,
                    ignore_default_args=[
                        "--disable-extensions",
                        "--disable-component-update",
                        "--disable-background-networking",
                    ],
                    **argumentos,
                )
            except (ErroPlaywright, OSError) as erro:
                ultimo_erro = _resumo(erro) if isinstance(erro, ErroPlaywright) else str(erro)
                continue
            self._contexto_persistente = contexto
            contexto.on("close", lambda *_: setattr(self, "_contexto_fechado", True))
            return contexto
        raise self._falha_ao_abrir(ultimo_erro)

    def nova_pagina(self, javascript: bool, janela_real: bool = False):
        """Cria um contexto com uma página.

        Perfil temporário (padrão): contexto isolado, sem cookies nem extensões, descartado ao fechar.
        Perfil próprio (`perfil_persistente`): ver `_abrir_com_perfil`.
        janela_real: sem tamanho fixo de viewport, para a janela visível poder ser redimensionada.
        """
        if self._perfil:
            contexto = self._abrir_com_perfil(javascript)
            contexto.route("**/*", _filtrar)
            contexto.set_default_timeout(self._timeout_ms)
            paginas = [p for p in contexto.pages if not p.is_closed()]
            return contexto, (paginas[0] if paginas else contexto.new_page())

        self.iniciar()
        tamanho = {"no_viewport": True} if janela_real else {"viewport": {"width": 1280, "height": 800}}
        contexto = self._navegador.new_context(
            **tamanho,
            java_script_enabled=javascript,
            accept_downloads=False,
            service_workers="block",
        )
        contexto.route("**/*", _filtrar)
        contexto.set_default_timeout(self._timeout_ms)
        return contexto, contexto.new_page()


def _resumo(erro: Exception) -> str:
    """Primeira linha da mensagem do Playwright (as demais são logs longos)."""
    linhas = str(erro).strip().splitlines()
    return linhas[0] if linhas else erro.__class__.__name__
