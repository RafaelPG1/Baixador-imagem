"""OpenRouter (API compatível com OpenAI) lendo o texto da página inteira numa só chamada. Envia SÓ texto extraído (nunca imagem).

A chave vem do `.env` (key_openrouter) e só trafega no cabeçalho Authorization: não aparece em URL, log nem mensagem de erro.
O modelo vem de `modelo_openrouter` no `.env` (ou da constante abaixo) — troque sem mexer no código.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from baixador.nucleo.erros import Cancelado
from baixador.traducao import ambiente, hymt
from baixador.traducao import inteligencia as ia
from baixador.traducao.gemini import SISTEMA, esquema_saida, ler_json
from baixador.traducao.numerada import TradutorNumerado, interpretar, montar_prompt

MODELO_OPENROUTER = "nvidia/nemotron-3.5-super-vl:free"   # <- ou defina modelo_openrouter = "fornecedor/modelo:free" no .env
URL_BASE = "https://openrouter.ai/api/v1"
TEMPO_LIMITE = 90
TENTATIVAS = 3                                              # 429/5xx: espera e tenta de novo (cancelável)
ESPERA = (5.0, 15.0)
MSG_SEM_CHAVE = "A chave do OpenRouter não foi configurada. Abra o arquivo .env na raiz do projeto, preencha key_openrouter = \"sua-chave\" e tente de novo."


def modelo_configurado() -> str:
    return ambiente.ler_env().get("modelo_openrouter", "").strip() or MODELO_OPENROUTER


MSG_SO_GRATIS = "Só modelos gratuitos são aceitos (o id termina em “:free”), para nunca gastar créditos. Ajuste modelo_openrouter no .env; ids em openrouter.ai/models."


def gratis(modelo: str) -> bool:
    return modelo.endswith(":free")


def max_tokens(n: int) -> int:
    """Teto de saída proporcional à página. Sem teto o OpenRouter reserva o máximo do modelo (ex.: 131072) e recusa com 402 por falta de saldo."""
    return min(8192, 1024 + 300 * max(1, n))


def verificar() -> Dict[str, Any]:
    """Sem rede: só confere chave e modelo. {pronto, mensagem, nome}."""
    modelo = modelo_configurado()
    if not gratis(modelo):
        return {"pronto": False, "mensagem": f"O modelo “{modelo}” não é gratuito. " + MSG_SO_GRATIS, "nome": modelo}
    if not ambiente.chave_openrouter():
        return {"pronto": False, "mensagem": MSG_SEM_CHAVE, "nome": modelo}
    return {"pronto": True, "mensagem": f"Chave encontrada no .env. Modelo: {modelo}. O OpenRouter recebe só o texto extraído, nunca a imagem.", "nome": modelo}


class TradutorOpenRouter(TradutorNumerado):
    origem = "openrouter"

    def __init__(self, de: str = "en", para: str = "pt", parar: Optional[threading.Event] = None,
                 abrir: Any = urllib.request.urlopen, modelo: Optional[str] = None) -> None:
        super().__init__(de, para)
        self._chave = ambiente.chave_openrouter()
        if not self._chave:
            raise hymt.IndisponivelMotor(MSG_SEM_CHAVE)
        self.modelo = modelo or modelo_configurado()
        if not gratis(self.modelo):
            raise hymt.IndisponivelMotor(f"O modelo “{self.modelo}” não é gratuito. " + MSG_SO_GRATIS)
        self.nome_motor = f"OpenRouter ({self.modelo})"
        self.parar = parar
        self._abrir = abrir
        self._json = True

    def _limpar(self, texto: str) -> str:
        return texto.replace(self._chave, "***")

    def _corpo(self, sistema: str, usuario: str, n: int = 0) -> Dict[str, Any]:
        corpo: Dict[str, Any] = {"model": self.modelo, "temperature": 0.3, "max_tokens": max_tokens(n or 1),
                                 "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]}
        if n and self._json:
            corpo["response_format"] = {"type": "json_schema", "json_schema": {"name": "traducoes", "strict": True, "schema": esquema_saida(n)}}
        return corpo

    def _uma_chamada(self, corpo: Dict[str, Any]) -> str:
        req = urllib.request.Request(
            f"{URL_BASE}/chat/completions", json.dumps(corpo).encode(),
            {"Content-Type": "application/json", "Authorization": f"Bearer {self._chave}", "X-Title": "Baixador de Imagens"}, method="POST",
        )
        with self._abrir(req, timeout=TEMPO_LIMITE) as r:
            dados = json.load(r)
        try:
            texto = dados["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise hymt.RespostaInvalida("resposta do OpenRouter sem texto") from None
        if not isinstance(texto, str) or not texto.strip():
            raise hymt.RespostaInvalida("resposta do OpenRouter vazia")
        return self._limpar(texto)

    def _detalhe(self, erro: urllib.error.HTTPError) -> str:
        try:
            m = json.loads(erro.read().decode("utf-8", "replace")).get("error", {}).get("message", "")
        except Exception:
            return ""
        return " OpenRouter: " + self._limpar(" ".join(str(m).split())[:200]) if m else ""

    def _pedir(self, prompt: str, n: int) -> str:
        return self._executar(lambda: self._corpo("You translate manga text. Follow the user's instructions exactly.", prompt))

    def _lista(self, entradas: List[str], limpos: List[str], ctx: Optional[ia.Contexto]) -> Optional[List[str]]:
        """Página inteira em JSON estruturado (um item por balão, com id); se o modelo não aceitar, cai na lista numerada."""
        if not self._json:
            return super()._lista(entradas, limpos, ctx)
        n = len(entradas)
        entrada = json.dumps({"context": [{"original": o, "translation": t} for o, t in (ctx.anteriores[-6:] if ctx else []) if o and t],
                              "segments": [{"id": i, "text": t} for i, t in enumerate(entradas)]}, ensure_ascii=False)
        try:
            texto = self._executar(lambda: self._corpo(SISTEMA + self._extra(limpos, ctx), entrada, n), esquema=True)
            return ler_json(texto, n)
        except hymt.RespostaInvalida:
            return super()._lista(entradas, limpos, ctx)

    def _executar(self, fazer_corpo: Any, esquema: bool = False) -> str:
        ultimo = ""
        tentativa = -1
        while True:
            tentativa += 1
            resultado: Dict[str, Any] = {}

            def trabalhar() -> None:
                try:
                    resultado["ok"] = self._uma_chamada(fazer_corpo())
                except BaseException as erro:               # a thread nunca deixa exceção solta
                    resultado["erro"] = erro

            fio = threading.Thread(target=trabalhar, daemon=True)
            fio.start()
            while fio.is_alive():
                if self.parar is not None and self.parar.is_set():
                    raise Cancelado("Tradução cancelada.")
                fio.join(0.2)
            erro = resultado.get("erro")
            if erro is None:
                return resultado["ok"]
            if isinstance(erro, hymt.RespostaInvalida):
                raise erro
            if isinstance(erro, urllib.error.HTTPError):
                if erro.code == 400 and esquema and self._json:        # o modelo pode não aceitar esquema JSON: usa a lista numerada
                    self._json = False
                    raise hymt.RespostaInvalida("esquema JSON recusado") from None
                if erro.code == 401:
                    raise hymt.IndisponivelMotor("O OpenRouter recusou a chave (key_openrouter no .env). Confira se está correta e ativa." + self._detalhe(erro)) from None
                if erro.code == 402:
                    raise hymt.IndisponivelMotor("O OpenRouter pediu créditos (erro 402): saldo insuficiente para esse modelo. Use um modelo “:free” em modelo_openrouter no .env (o programa só aceita modelos gratuitos)." + self._detalhe(erro)) from None
                if erro.code in (400, 403, 404):
                    raise hymt.IndisponivelMotor(f"O OpenRouter recusou o pedido (erro {erro.code}). Confira o modelo “{self.modelo}” (modelo_openrouter no .env; ids em openrouter.ai/models)." + self._detalhe(erro)) from None
                if erro.code in (408, 429, 500, 502, 503, 504):
                    ultimo = "O limite de uso do OpenRouter foi atingido (modelos “:free” têm limite diário baixo); tente depois ou adicione créditos." if erro.code == 429 else f"O OpenRouter está instável (erro {erro.code})."
                    if tentativa < TENTATIVAS - 1:
                        espera = ESPERA[min(tentativa, len(ESPERA) - 1)]
                        try:
                            espera = min(60.0, max(espera, float(erro.headers.get("Retry-After", 0))))
                        except (TypeError, ValueError, AttributeError):
                            pass
                        if self.parar is not None and self.parar.wait(espera):
                            raise Cancelado("Tradução cancelada.")
                        continue
                    raise hymt.MotorSobrecarregado(ultimo) from None
                raise hymt.IndisponivelMotor(f"O OpenRouter respondeu com erro {erro.code}." + self._detalhe(erro)) from None
            if isinstance(erro, (urllib.error.URLError, ConnectionError, TimeoutError, OSError)):
                if tentativa < 1:
                    continue
                raise hymt.MotorSobrecarregado(f"O OpenRouter não respondeu ({erro.__class__.__name__}).") from None
            raise hymt.IndisponivelMotor(f"Falha inesperada ao chamar o OpenRouter ({erro.__class__.__name__}).") from None

    def _um(self, texto: str, ctx: Optional[ia.Contexto]) -> str:
        nomes = list(ctx.nomes) if ctx else []
        alta = texto.isupper()
        entrada = " ".join((ia.frase_natural(texto, nomes) if alta else texto).split())
        lista = interpretar(self._pedir(montar_prompt([entrada], self._extra([texto], ctx)), 1), 1)
        if not lista:
            raise hymt.RespostaInvalida("resposta fora do formato")
        r = hymt.validar(texto, lista[0])
        return r.upper() if alta else r


__all__: List[str] = ["TradutorOpenRouter", "MODELO_OPENROUTER", "verificar"]
