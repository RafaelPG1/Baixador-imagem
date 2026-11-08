"""Configuração do motor de tradução (arquivo `dados/traducao.json`): híbrido (padrão), só Argos ou só Hy-MT2."""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict

from baixador import configuracao

ARQUIVO = configuracao.DADOS / "traducao.json"
MOTORES = {
    "hibrido": "Híbrido (recomendado): Argos primeiro, Hy-MT2 refinando em segundo plano",
    "argos": "Somente Argos",
    "hy": "Somente Hy-MT2 — Modo A (balão por balão)",
    "hy_pagina": "Somente Hy-MT2 — Modo B (página inteira com contexto)",
    "gemini": "Gemini (página inteira, na nuvem; envia só o texto)",
    "openrouter": "OpenRouter (página inteira, na nuvem; envia só o texto)",
}
MODELO_PADRAO = "hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M"
_trava = threading.Lock()


def ler() -> Dict[str, Any]:
    """Configuração atual, sempre válida (arquivo ausente/corrompido = padrões)."""
    dados: Dict[str, Any] = {}
    try:
        lido = json.loads(ARQUIVO.read_text(encoding="utf-8"))
        dados = lido if isinstance(lido, dict) else {}
    except (OSError, ValueError):
        pass
    motor = dados.get("motor")
    modelo = dados.get("modelo")
    return {
        "motor": motor if motor in MOTORES else "hibrido",
        "modelo": modelo.strip()[:200] if isinstance(modelo, str) and modelo.strip() else MODELO_PADRAO,
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
            if not isinstance(modelo, str) or not modelo.strip() or len(modelo) > 200 or any(c.isspace() for c in modelo.strip()):
                raise ValueError("Nome de modelo inválido.")
            atual["modelo"] = modelo.strip()
        try:
            ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
            temporario = ARQUIVO.with_suffix(".tmp")
            temporario.write_text(json.dumps(atual, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(temporario, ARQUIVO)
        except OSError as erro:
            raise ValueError(f"Não foi possível gravar a configuração: {erro}") from None
        return atual
