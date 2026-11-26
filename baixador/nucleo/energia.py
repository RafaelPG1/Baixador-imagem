"""Impede que o Windows suspenda o notebook enquanto uma tarefa longa (tradução, download) roda.

Usa `SetThreadExecutionState`, que vale por THREAD: cada tarefa pede dentro da própria thread e devolve no `finally`, então a
suspensão volta ao normal ao terminar, cancelar ou falhar (e, se a thread morrer, o Windows também desfaz). Ocioso = não impede nada.
A tela pode apagar normalmente (só `ES_SYSTEM_REQUIRED`). Fora do Windows não faz nada.
"""

from __future__ import annotations

import sys
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Optional

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

_local = threading.local()
_api: Optional[Any] = None                        # troca nos testes; no Windows é `kernel32`


def _kernel() -> Optional[Any]:
    global _api
    if _api is None and sys.platform == "win32":
        import ctypes

        _api = ctypes.windll.kernel32
    return _api


@contextmanager
def acordado() -> Iterator[None]:
    """`with acordado(): …` — dentro do bloco o sistema não suspende. Pode aninhar na mesma thread."""
    k = _kernel()
    nivel = getattr(_local, "nivel", 0)
    if k is not None and nivel == 0:
        try:
            k.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        except Exception:  # noqa: BLE001 — não conseguir pedir nunca derruba a tarefa
            k = None
    _local.nivel = nivel + 1
    try:
        yield
    finally:
        _local.nivel = nivel
        if nivel == 0 and k is not None:
            try:
                k.SetThreadExecutionState(ES_CONTINUOUS)          # devolve o comportamento normal
            except Exception:  # noqa: BLE001
                pass
