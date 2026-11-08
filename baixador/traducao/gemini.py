"""Gemini (Google) lendo o texto da página inteira numa só chamada. Envia SÓ texto extraído (nunca imagem).

A chave vem do `.env` (key_gemini) e só trafega no cabeçalho `x-goog-api-key`: não aparece em URL, log nem mensagem de erro.
"""

from __future__ import annotations

import json
import threading
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from baixador.nucleo.erros import Cancelado
from baixador.traducao import ambiente, hymt
from baixador.traducao import inteligencia as ia
from baixador.traducao.numerada import TradutorNumerado, interpretar, montar_prompt

MODELO_GEMINI = "gemini-3.5-flash"                 # <- troque o modelo aqui (ex.: "gemini-3.5-flash-lite")
MODELOS_RESERVA = ("gemini-3.1-flash-lite", "gemini-3.6-flash", "gemini-3.7-flash")   # usados se o principal estiver sobrecarregado/sem resposta
URL_BASE = "https://generativelanguage.googleapis.com/v1beta"
TEMPO_LIMITE = 90
TENTATIVAS = 3                                     # 429/5xx: espera curta e tenta de novo (cancelável)
ESPERA = (4.0, 12.0)
MSG_SEM_CHAVE = "A chave do Gemini não foi configurada. Abra o arquivo .env na raiz do projeto, preencha key_gemini = \"sua-chave\" e tente de novo."


SISTEMA = (
    "You are a professional manga/manhwa translator. You receive ONE page: the `segments` are ALL its speech balloons, numbered "
    "with `id` in reading order, and `context` holds the previous lines of the story (original + translation).\n"
    "Translation requirements:\n"
    "- Translate every segment into natural, informal Brazilian Portuguese (pt-BR), the way people really talk in a manga. "
    "Use 'você' (never 'tu'); keep numbers exactly as they are.\n"
    "- Preserve meaning, character voice, emotional tone and emphasis; localize idioms and sound effects naturally, "
    "concise enough for a speech bubble. Nicknames such as 'little guy' become natural words ('carinha', 'baixinho').\n"
    "- Leave NO English words behind (names stay unchanged). Never include notes, explanations or alternatives.\n"
    "- Use the other segments and the context only to disambiguate and keep the dialogue flowing; NEVER merge, split, omit, "
    "duplicate or add segments, and never translate or return the context.\n"
    "Output: only a JSON object whose `translations` array has one object {id, text} for EVERY input segment, each id copied exactly once."
)


def esquema_saida(n: int) -> Dict[str, Any]:
    return {"type": "object", "required": ["translations"], "additionalProperties": False, "properties": {"translations": {
        "type": "array", "minItems": n, "maxItems": n, "items": {"type": "object", "required": ["id", "text"], "additionalProperties": False,
        "properties": {"id": {"type": "integer", "minimum": 0, "maximum": max(0, n - 1)}, "text": {"type": "string"}}}}}}


def ler_json(texto: str, n: int) -> Optional[List[str]]:
    """Lista de n textos na ordem dos ids; item ausente vira "" (só esse balão é refeito). JSON inválido -> RespostaInvalida."""
    try:
        itens = json.loads(texto.strip())["translations"]
        achados: Dict[int, str] = {}
        for it in itens:
            i = int(str(it["id"]).strip())
            if 0 <= i < n and i not in achados and isinstance(it["text"], str):
                achados[i] = " ".join(it["text"].split())
    except (ValueError, KeyError, TypeError):
        raise hymt.RespostaInvalida("resposta do Gemini não é o JSON esperado") from None
    return [achados.get(i, "") for i in range(n)]


def verificar() -> Dict[str, Any]:
    """Sem rede: só confere se há chave. {pronto, mensagem, nome}."""
    if not ambiente.chave_gemini():
        return {"pronto": False, "mensagem": MSG_SEM_CHAVE, "nome": MODELO_GEMINI}
    return {"pronto": True, "mensagem": f"Chave encontrada no .env. Modelo: {MODELO_GEMINI}. O Gemini recebe só o texto extraído, nunca a imagem.", "nome": MODELO_GEMINI}


class TradutorGemini(TradutorNumerado):
    nome_motor = f"Gemini ({MODELO_GEMINI})"
    origem = "gemini"

    def __init__(self, de: str = "en", para: str = "pt", parar: Optional[threading.Event] = None,
                 abrir: Any = urllib.request.urlopen, modelo: Optional[str] = None) -> None:
        super().__init__(de, para)
        self._chave = ambiente.chave_gemini()
        if not self._chave:
            raise hymt.IndisponivelMotor(MSG_SEM_CHAVE)
        self.modelo = modelo or MODELO_GEMINI
        self.nome_motor = f"Gemini ({self.modelo})"
        self.parar = parar
        self._abrir = abrir
        self._raciocinio = True
        self._json = True

    def _limpar(self, texto: str) -> str:
        return texto.replace(self._chave, "***")

    def _config(self) -> Dict[str, Any]:
        config: Dict[str, Any] = {"temperature": 0.3}
        if self._raciocinio:                            # tradução não precisa "pensar" muito: bem mais rápido
            config["thinkingConfig"] = {"thinkingLevel": "low"}
        return config

    def _corpo_texto(self, prompt: str) -> Dict[str, Any]:
        return {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": self._config()}

    def _corpo_json(self, entrada: str, n: int, extra: str) -> Dict[str, Any]:
        config = self._config()
        config["responseMimeType"] = "application/json"
        config["responseJsonSchema"] = esquema_saida(n)
        return {"systemInstruction": {"parts": [{"text": SISTEMA + extra}]},
                "contents": [{"role": "user", "parts": [{"text": entrada}]}], "generationConfig": config}

    def _uma_chamada(self, corpo: Dict[str, Any]) -> str:
        req = urllib.request.Request(
            f"{URL_BASE}/models/{self.modelo}:generateContent", json.dumps(corpo).encode(),
            {"Content-Type": "application/json", "x-goog-api-key": self._chave}, method="POST",
        )
        with self._abrir(req, timeout=TEMPO_LIMITE) as r:
            dados = json.load(r)
        if (dados.get("promptFeedback") or {}).get("blockReason"):
            raise hymt.RespostaInvalida("o Gemini recusou o conteúdo")
        try:
            partes = dados["candidates"][0]["content"]["parts"]
            return self._limpar("".join(p.get("text", "") for p in partes))
        except (KeyError, IndexError, TypeError):
            raise hymt.RespostaInvalida("resposta do Gemini sem texto") from None

    def _detalhe(self, erro: urllib.error.HTTPError) -> str:
        """Mensagem curta que o Google devolveu (sem a chave), para diagnosticar."""
        try:
            m = json.loads(erro.read().decode("utf-8", "replace")).get("error", {}).get("message", "")
        except Exception:
            return ""
        return " Google: " + self._limpar(" ".join(str(m).split())[:200]) if m else ""

    def _pedir(self, prompt: str, n: int) -> str:
        return self._executar(lambda: self._corpo_texto(prompt))

    def _lista(self, entradas: List[str], limpos: List[str], ctx: Optional[ia.Contexto]) -> Optional[List[str]]:
        """Página inteira em JSON estruturado: o Gemini é obrigado a devolver um item por balão, com o id de cada um."""
        if not self._json:
            return super()._lista(entradas, limpos, ctx)
        n = len(entradas)
        entrada = json.dumps({"context": [{"original": o, "translation": t} for o, t in (ctx.anteriores[-6:] if ctx else []) if o and t],
                              "segments": [{"id": i, "text": t} for i, t in enumerate(entradas)]}, ensure_ascii=False)
        try:
            texto = self._executar(lambda: self._corpo_json(entrada, n, self._extra(limpos, ctx)), esquema=True)
            return ler_json(texto, n)
        except hymt.RespostaInvalida:                   # esquema recusado ou JSON ruim: cai no formato de lista numerada
            return super()._lista(entradas, limpos, ctx)

    def _executar(self, fazer_corpo: Any, esquema: bool = False) -> str:
        ultimo = ""
        reservas = [m for m in MODELOS_RESERVA if m != self.modelo]
        tentados = {self.modelo}
        listou = [False]
        tentativa = -1

        def reescolher() -> None:
            """404: consulta quais modelos a chave tem e monta a fila só com eles (preferidos primeiro)."""
            if listou[0]:
                return
            listou[0] = True
            livres = self.modelos_disponiveis()
            if not livres:
                return
            preferidos = [m for m in (MODELO_GEMINI, *MODELOS_RESERVA, "gemini-flash-latest") if m in livres]
            outros = sorted(m for m in livres if "flash" in m and "lite" not in m and "image" not in m and "tts" not in m and m not in preferidos)
            reservas[:] = [m for m in (*preferidos, *outros) if m not in tentados]
            print(f"[gemini] modelo indisponível para a chave; candidatos: {', '.join(reservas) or 'nenhum'}", file=sys.stderr)

        def trocar() -> bool:
            if not reservas:
                return False
            self.modelo = reservas.pop(0)
            tentados.add(self.modelo)
            self.nome_motor = f"Gemini ({self.modelo})"
            print(f"[gemini] modelo sobrecarregado/sem resposta; usando {self.modelo}", file=sys.stderr)
            return True

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
                if erro.code == 400 and self._raciocinio:    # o modelo pode não aceitar o ajuste de raciocínio: tenta sem ele
                    self._raciocinio = False
                    continue
                if erro.code == 400 and esquema and self._json:      # o modelo pode não aceitar o esquema JSON: usa a lista numerada
                    self._json = False
                    raise hymt.RespostaInvalida("esquema JSON recusado") from None
                if erro.code in (400, 401, 403):
                    raise hymt.IndisponivelMotor("O Gemini recusou a chave (key_gemini no .env) ou o pedido. Confira a chave e o nome do modelo." + self._detalhe(erro)) from None
                if erro.code in (429, 500, 502, 503, 504):
                    ultimo = "O limite de uso do Gemini foi atingido; tente de novo em alguns instantes." if erro.code == 429 else f"O Gemini está instável (erro {erro.code})."
                    if tentativa < TENTATIVAS - 1:
                        if self.parar is not None and self.parar.wait(ESPERA[min(tentativa, len(ESPERA) - 1)]):
                            raise Cancelado("Tradução cancelada.")
                        continue
                    if trocar():
                        tentativa = -1
                        continue
                    raise hymt.MotorSobrecarregado(ultimo) from None
                if erro.code == 404:
                    reescolher()
                if erro.code == 404 and trocar():            # modelo que a chave não enxerga: tenta o próximo
                    tentativa = -1
                    continue
                if erro.code == 404:
                    raise hymt.IndisponivelMotor(f"O Gemini não encontrou o modelo “{self.modelo}” (erro 404). Ele pode ter sido desativado: e nenhum outro modelo Flash está liberado para esta chave; confira a chave no Google AI Studio ou troque MODELO_GEMINI em baixador/traducao/gemini.py." + self._detalhe(erro)) from None
                raise hymt.IndisponivelMotor(f"O Gemini respondeu com erro {erro.code}." + self._detalhe(erro)) from None
            if isinstance(erro, (urllib.error.URLError, ConnectionError, TimeoutError, OSError)):
                if tentativa >= 1 and trocar():
                    tentativa = -1
                    continue
                if tentativa < 1:
                    continue
                raise hymt.MotorSobrecarregado(f"O Gemini não respondeu ({erro.__class__.__name__}).") from None
            raise hymt.IndisponivelMotor(f"Falha inesperada ao chamar o Gemini ({erro.__class__.__name__}).") from None
        raise hymt.IndisponivelMotor(ultimo or "O Gemini não respondeu.")

    def modelos_disponiveis(self) -> List[str]:
        """Modelos que ESTA chave enxerga e aceitam generateContent (consulta única por tradutor; [] se não der para listar)."""
        achados: List[str] = []
        token = ""
        try:
            for _ in range(5):
                url = f"{URL_BASE}/models?pageSize=200" + (f"&pageToken={token}" if token else "")
                req = urllib.request.Request(url, headers={"x-goog-api-key": self._chave})
                with self._abrir(req, timeout=20) as r:
                    d = json.loads(r.read().decode("utf-8", "replace"))
                for m in d.get("models", []):
                    if "generateContent" in (m.get("supportedGenerationMethods") or []):
                        achados.append(str(m.get("name", "")).split("/")[-1])
                token = str(d.get("nextPageToken") or "")
                if not token:
                    break
        except Exception:                                   # sem rede/permissão: segue com a lista fixa
            return []
        return [a for a in achados if a]

    def _um(self, texto: str, ctx: Optional[ia.Contexto]) -> str:
        nomes = list(ctx.nomes) if ctx else []
        alta = texto.isupper()
        entrada = " ".join((ia.frase_natural(texto, nomes) if alta else texto).split())
        prompt = montar_prompt([entrada], self._extra([texto], ctx))
        lista = interpretar(self._pedir(prompt, 1), 1)
        if not lista:
            raise hymt.RespostaInvalida("resposta fora do formato")
        r = hymt.validar(texto, lista[0])
        return r.upper() if alta else r


__all__: List[str] = ["TradutorGemini", "MODELO_GEMINI", "verificar"]
