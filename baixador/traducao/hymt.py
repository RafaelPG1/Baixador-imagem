"""Hy-MT2-7B (Tencent) rodando local pelo Ollama: tradução EN -> PT-BR de uma fala por vez, sem contexto longo.

- nunca baixa nada: se o Ollama ou o modelo não estiverem lá, explica o que fazer (`IndisponivelHy`);
- toda resposta é validada (vazia, em outro idioma, absurda em tamanho, eco do prompt) e, se inválida, NÃO é usada;
- a geração é lida em fluxo (stream), então cancelar interrompe na hora, inclusive no meio de uma fala.
"""

from __future__ import annotations

import json
import os
import queue
import re
import socket
import threading
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from baixador.nucleo.erros import Cancelado
from baixador.traducao import config
from baixador.traducao import inteligencia as ia

TEMPO_LIMITE = 600                                   # segundos por fala (CPU lenta + carregamento do modelo)
PARAMETROS = {"temperature": 0.7, "top_p": 0.6, "top_k": 20, "repeat_penalty": 1.05, "num_ctx": 2048, "num_predict": 400}
INSTRUCAO = (
    "Translate the following text into Brazilian Portuguese (pt-BR), as natural spoken dialogue from a manga/manhwa. "
    "Use 'você' (never 'tu'), Brazilian vocabulary and the gerund ('está usando'), never European Portuguese. "
    "Keep the meaning, tone and personality; do not add or omit anything. Output only the translation."
)
_PT = frozenset("de que o a e é não um uma você para com se em eu ele ela os as do da no na isso mas meu minha seu sua foi são já vai vou mais como tem ter está estou era nos me te lhe por ao nem só aqui muito bem então".split())


_EN = frozenset("the and is are you to of in that it this with for was be have has not what i we they he she his her my your our will can would just don't i'm it's".split())


def _parece_ingles(r: str) -> bool:
    """Inglês devolvido sem tradução: tem palavras comuns do inglês e nenhuma marca do português."""
    palavras = re.findall(r"[a-zà-ÿ']+", r.lower())
    if not palavras or re.search(r"[ãõçáéíóúâêô]", r.lower()) or set(palavras) & _PT:
        return False
    return sum(p in _EN for p in palavras) >= max(2, len(palavras) // 3)


class IndisponivelMotor(Exception):
    """Motor de tradução (Ollama/Hy-MT2 ou Gemini) fora do ar ou mal configurado: a mensagem já é para o usuário."""


class MotorSobrecarregado(IndisponivelMotor):
    """Falha passageira (sobrecarga, limite, sem resposta): a página pode ser tentada de novo mais tarde."""


class IndisponivelHy(IndisponivelMotor):
    """Ollama fechado/ausente, modelo não instalado ou resposta de erro do servidor (mensagem pronta para o usuário)."""


class RespostaInvalida(Exception):
    """O modelo respondeu algo que não serve como tradução (a tradução existente é mantida)."""


def endereco(host: Optional[str] = None) -> str:
    h = (host or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").strip()
    if not re.match(r"^https?://", h):
        h = "http://" + h
    return h.rstrip("/") if re.search(r":\d+$", h.rstrip("/")) or h.count(":") > 1 else h.rstrip("/") + ":11434"


def _nome_igual(a: str, b: str) -> bool:
    a, b = a.lower(), b.lower()
    return a == b or a + ":latest" == b or a == b + ":latest"


def verificar(modelo: Optional[str] = None, host: Optional[str] = None, timeout: float = 3.0, abrir: Callable[..., Any] = urllib.request.urlopen) -> Dict[str, Any]:
    """{ollama: bool, modelo: bool, mensagem: str, pronto: bool}: consulta rápida (lista de modelos), sem carregar o modelo."""
    modelo = modelo or config.ler()["modelo"]
    base = endereco(host)
    try:
        with abrir(urllib.request.Request(base + "/api/tags"), timeout=timeout) as r:
            nomes = [m.get("name", "") for m in json.load(r).get("models", []) if isinstance(m, dict)]
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return {"ollama": False, "modelo": False, "pronto": False, "nome": modelo,
                "mensagem": "O Ollama não está respondendo. Instale e abra o Ollama (ollama.com) e tente de novo."}
    if not any(_nome_igual(modelo, n) for n in nomes):
        return {"ollama": True, "modelo": False, "pronto": False, "nome": modelo,
                "mensagem": f"O modelo {modelo} não está instalado. Baixe uma vez no terminal: ollama pull {modelo}"}
    return {"ollama": True, "modelo": True, "pronto": True, "nome": modelo, "mensagem": "Ollama e modelo disponíveis."}


def exigir(modelo: Optional[str] = None, host: Optional[str] = None, **k: Any) -> None:
    estado = verificar(modelo, host, **k)
    if not estado["pronto"]:
        raise IndisponivelHy(estado["mensagem"])


def limpar_resposta(bruta: str) -> str:
    t = re.sub(r"<think>.*?</think>", "", bruta, flags=re.S | re.I).strip()
    t = re.sub(r"^```[a-z]*\n?|\n?```$", "", t).strip()
    t = re.sub(r"^(tradução|traducao|translation)\s*:\s*", "", t, flags=re.I)
    if len(t) > 2 and t[0] in "\"“«" and t[-1] in "\"”»" and t.count(t[0]) == 1:
        t = t[1:-1].strip()
    return " ".join(t.split())


def validar(fonte: str, resposta: str) -> str:
    """Devolve a resposta limpa ou levanta RespostaInvalida."""
    r = limpar_resposta(resposta)
    if not r:
        raise RespostaInvalida("resposta vazia")
    if re.search(r"[぀-ヿ㐀-鿿가-힯Ѐ-ӿ]", r) and not re.search(r"[぀-ヿ㐀-鿿가-힯Ѐ-ӿ]", fonte):
        raise RespostaInvalida("resposta em outro alfabeto")
    if re.match(r"^(translate |traduza |here is|here's|sure|claro)", r, re.I):
        raise RespostaInvalida("o modelo respondeu com explicação, não com a tradução")
    n_f, n_r = len(fonte.strip()), len(r)
    if n_f >= 12 and (n_r < 0.25 * n_f or n_r > 4 * n_f + 20):
        raise RespostaInvalida("tamanho incompatível com o original")
    if n_r >= 15 and _parece_ingles(r):
        raise RespostaInvalida("a resposta não parece português")
    return r


class TradutorHy:
    """Mesma interface do TradutorArgos (`traduzir_pagina`), mais `traduzir_uma` para o refinamento."""

    lento = True                     # ~10 s por fala em CPU: o pipeline evita usá-lo como "sonda" de palavras soltas
    origem = "hy"
    nome_motor = "Hy-MT2 modo A (balão a balão)"

    def __init__(self, de: str = "en", para: str = "pt", modelo: Optional[str] = None, host: Optional[str] = None,
                 parar: Optional[threading.Event] = None, chamar: Optional[Callable[[Dict[str, Any], Optional[threading.Event]], str]] = None) -> None:
        self.de, self.para = de, para
        self.modelo = modelo or config.ler()["modelo"]
        self.base = endereco(host)
        self.parar = parar
        self._chamar = chamar or self._http
        self.invalidas = 0

    # ---- rede
    def _http(self, corpo: Dict[str, Any], parar: Optional[threading.Event]) -> str:
        """Pedido em outra thread: o cancelamento vale na hora, mesmo enquanto o Ollama ainda carrega o modelo (sem nenhum byte)."""
        fila: "queue.Queue[Any]" = queue.Queue()
        conexao: Dict[str, Any] = {}
        encerrar = threading.Event()

        def trabalhar() -> None:
            req = urllib.request.Request(self.base + "/api/chat", json.dumps(corpo).encode(), {"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=TEMPO_LIMITE) as r:
                    conexao["r"] = r
                    for linha in r:
                        if encerrar.is_set():
                            return
                        if not linha.strip():
                            continue
                        pedaco = json.loads(linha)
                        if pedaco.get("error"):
                            raise IndisponivelHy(f"O Ollama devolveu um erro: {str(pedaco['error'])[:200]}")
                        fila.put(("txt", pedaco.get("message", {}).get("content", "")))
                        if pedaco.get("done"):
                            break
                fila.put(("fim", None))
            except urllib.error.HTTPError as erro:
                detalhe = ""
                try:
                    detalhe = erro.read().decode("utf-8", "replace")[:200]
                except Exception:
                    pass
                fila.put(("erro", IndisponivelHy(f"O Ollama respondeu com erro {erro.code} (modelo sem memória ou ainda carregando?). {detalhe}".strip())))
            except IndisponivelHy as erro:
                fila.put(("erro", erro))
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as erro:
                if not encerrar.is_set():
                    fila.put(("erro", IndisponivelHy(f"Não consegui falar com o Ollama ({erro.__class__.__name__}). Ele continua aberto?")))
            except ValueError:
                fila.put(("erro", IndisponivelHy("O Ollama devolveu uma resposta ilegível.")))

        threading.Thread(target=trabalhar, daemon=True).start()
        partes: List[str] = []
        while True:
            if parar is not None and parar.is_set():
                encerrar.set()
                try:                                        # derruba a conexão: o Ollama para de gerar
                    conexao["r"].fp.raw._sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                raise Cancelado("Tradução cancelada.")
            try:
                tipo, valor = fila.get(timeout=0.2)
            except queue.Empty:
                continue
            if tipo == "txt":
                partes.append(valor)
            elif tipo == "erro":
                raise valor
            else:
                return "".join(partes)

    # ---- tradução
    def _glossario(self, texto: str, ctx: Optional[ia.Contexto]) -> str:
        if ctx is None:
            return ""
        linhas = [f"{t} => {f}" for t, f in ctx.termos.items() if re.search(r"(?<![\w-])" + re.escape(t) + r"(?![\w-])", texto, re.I)]
        manter = [n for n in ctx.nomes if re.search(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])", texto, re.I)]
        extra = ""
        if linhas:
            extra += "\n\nTerminology (use exactly):\n" + "\n".join(linhas)
        if manter:
            extra += "\n\nKeep these names unchanged: " + ", ".join(manter)
        return extra

    def traduzir_uma(self, texto: str, ctx: Optional[ia.Contexto] = None) -> str:
        nomes = list(ctx.nomes) if ctx else []
        limpo = ia.corrigir_ocr(texto, nomes, self.de)
        alta = limpo.isupper() or sum(c.isupper() for c in limpo) > 0.6 * max(1, sum(c.isalpha() for c in limpo))
        entrada = ia.frase_natural(limpo, nomes) if alta else limpo
        corpo = {"model": self.modelo, "stream": True, "keep_alive": "30m", "think": False, "options": PARAMETROS,
                 "messages": [{"role": "user", "content": f"{INSTRUCAO}{self._glossario(limpo, ctx)}\n\nText:\n{entrada}"}]}
        ultimo: Optional[RespostaInvalida] = None
        for _ in range(2):                                           # uma nova tentativa para resposta inválida
            if self.parar is not None and self.parar.is_set():
                raise Cancelado("Tradução cancelada.")
            try:
                r = validar(limpo, self._chamar(corpo, self.parar))
                return r.upper() if alta else r
            except RespostaInvalida as erro:
                ultimo = erro
        self.invalidas += 1
        raise ultimo or RespostaInvalida("resposta inválida")

    def traduzir_pagina(self, textos: List[str], ctx: Optional[ia.Contexto] = None) -> List[str]:
        """Modo "Somente Hy-MT2": fala inválida não vira texto lixo: fica o original (o leitor não cobre o balão)."""
        saida = []
        for t in textos:
            try:
                saida.append(self.traduzir_uma(t, ctx))
            except RespostaInvalida:
                saida.append(t)
        return saida

    def __call__(self, textos: List[str]) -> List[str]:
        return self.traduzir_pagina(textos, None)


class TradutorHyPagina(TradutorHy):
    """Modo B: a página inteira (balões numerados, em ordem de leitura) numa única chamada ao Hy-MT2.

    Item vazio/inválido, ou lista com quantidade/numeração diferente, volta para o Modo A (um balão por chamada)."""

    nome_motor = "Hy-MT2 modo B (página inteira)"

    def __init__(self, *a: Any, **k: Any) -> None:
        super().__init__(*a, **k)
        self.refeitos = 0
        from baixador.traducao.numerada import TradutorNumerado

        outer = self

        class _B(TradutorNumerado):
            def _pedir(self, prompt: str, n: int) -> str:
                corpo = {"model": outer.modelo, "stream": True, "keep_alive": "30m", "think": False,
                         "options": {**PARAMETROS, "num_ctx": 4096, "num_predict": 200 + 120 * n},
                         "messages": [{"role": "user", "content": prompt}]}
                return outer._chamar(corpo, outer.parar)

            def _um(self, texto: str, ctx: Optional[ia.Contexto]) -> str:
                return outer.traduzir_uma(texto, ctx)                       # Modo A, sem alterar sua lógica

        self._b = _B(self.de, self.para)

    def traduzir_pagina(self, textos: List[str], ctx: Optional[ia.Contexto] = None) -> List[str]:
        r = self._b.traduzir_pagina(textos, ctx)
        self.refeitos = self._b.refeitos
        return r
