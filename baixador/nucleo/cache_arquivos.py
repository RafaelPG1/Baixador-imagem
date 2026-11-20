"""Cache de leituras do disco, validado pela data de modificação.

A biblioteca é consultada o tempo todo (interface, celular, modo automático de download). Abrir milhares de imagens e arquivos
`capitulo.json` a cada consulta custa segundos em bibliotecas grandes (no Windows, com antivírus, muito mais). Aqui o resultado
de cada leitura fica guardado e só é refeito quando a data do arquivo ou da pasta muda.

Regra de segurança: uma data muito recente (menos de `ESTAVEL_S` segundos) NÃO é confiável (o sistema de arquivos pode ter
granularidade grossa e uma segunda mudança no mesmo instante passaria despercebida), então coisas mexidas agora são sempre relidas.
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

ESTAVEL_S = 2.0


class CachePorData:
    """Guarda `calcular(caminho)` por caminho; vale enquanto (data de modificação, tamanho) do `alvo` não mudar."""

    def __init__(self, maximo: int = 20000) -> None:
        self._dados: "OrderedDict[str, Tuple[Tuple[int, int], Any]]" = OrderedDict()
        self._trava = threading.Lock()
        self._maximo = maximo

    def obter(self, chave: Path, calcular: Callable[[], Any], alvo: Optional[Path] = None) -> Any:
        """`alvo`: arquivo ou pasta cuja data decide se o cache vale (padrão: a própria `chave`)."""
        try:
            st = os.stat(alvo or chave)
        except OSError:
            return calcular()                                   # ausente: nada para guardar
        assinatura = (st.st_mtime_ns, st.st_size)
        estavel = time.time_ns() - st.st_mtime_ns > int(ESTAVEL_S * 1e9)
        nome = str(chave)
        if estavel:
            with self._trava:
                achado = self._dados.get(nome)
                if achado and achado[0] == assinatura:
                    self._dados.move_to_end(nome)
                    return achado[1]
        valor = calcular()
        if estavel:
            with self._trava:
                self._dados[nome] = (assinatura, valor)
                self._dados.move_to_end(nome)
                while len(self._dados) > self._maximo:
                    self._dados.popitem(last=False)
        return valor

    def limpar(self) -> None:
        with self._trava:
            self._dados.clear()
