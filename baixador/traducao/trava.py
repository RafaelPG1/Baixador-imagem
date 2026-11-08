"""Trava única para ler-alterar-gravar o `traducao.json` de um capítulo (edição do usuário e refinamento em segundo plano)."""
import threading

TRAVA_JSON = threading.Lock()
