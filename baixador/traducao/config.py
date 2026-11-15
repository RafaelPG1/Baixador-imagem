"""Configuração da tradução (arquivo `dados/traducao.json`): qual motor usar e, no motor local, qual modelo do Ollama.

Os motores são os do projeto Tradução. A escolha é sempre explícita e fica gravada aqui; nada troca de motor sozinho.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict

from baixador import configuracao

ARQUIVO = configuracao.DADOS / "traducao.json"
MOTOR_PADRAO = "local"
MOTORES = {
    "local": "TranslateGemma via Ollama (local, grátis) — padrão",
    "deepl": "DeepL (na nuvem; envia só o texto; exige DEEPL_API_KEY no .env)",
    "gemini": "Gemini (na nuvem; envia só o texto; exige GEMINI_API_KEY no .env)",
    "mymemory": "MyMemory (na nuvem, grátis; tradução literal, qualidade básica)",
}
MODELO_PADRAO = "translategemma:4b"
MODELOS = {                                                  # só vale para o motor local (baixe com `ollama pull <nome>`)
    MODELO_PADRAO: "TranslateGemma 4B (padrão)",
    "translategemma:12b": "TranslateGemma 12B (melhor, mas bem mais lento e pesado)",
}
# Variáveis do .env que o sistema de tradução lê (as demais do .env não são passadas para ele).
VARIAVEIS_ENV = ("DEEPL_API_KEY", "GEMINI_API_KEY", "GEMINI_MODEL", "MYMEMORY_EMAIL", "OLLAMA_URL")
_trava = threading.Lock()


def ler() -> Dict[str, Any]:
    """Configuração atual, sempre válida (arquivo ausente, corrompido ou de versão antiga = padrões)."""
    dados: Dict[str, Any] = {}
    try:
        lido = json.loads(ARQUIVO.read_text(encoding="utf-8"))
        dados = lido if isinstance(lido, dict) else {}
    except (OSError, ValueError):
        pass
    motor, modelo = dados.get("motor"), dados.get("modelo")
    return {
        "motor": motor if motor in MOTORES else MOTOR_PADRAO,
        "modelo": modelo if modelo in MODELOS else MODELO_PADRAO,
    }


def motor() -> str:
    return ler()["motor"]


def salvar(motor_novo: Any = None, modelo: Any = None) -> Dict[str, Any]:
    """Grava só o que veio e é válido; devolve a configuração resultante."""
    with _trava:
        atual = ler()
        if motor_novo is not None:
            if motor_novo not in MOTORES:
                raise ValueError("Motor de tradução desconhecido.")
            atual["motor"] = motor_novo
        if modelo is not None:
            if modelo not in MODELOS:
                raise ValueError("Modelo desconhecido. Use um dos oferecidos na lista.")
            atual["modelo"] = modelo
        try:
            ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
            temporario = ARQUIVO.with_suffix(".tmp")
            temporario.write_text(json.dumps(atual, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(temporario, ARQUIVO)
        except OSError as erro:
            raise ValueError(f"Não foi possível gravar a configuração: {erro}") from None
        return atual
