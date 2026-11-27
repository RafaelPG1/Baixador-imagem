"""Os testes nunca escrevem no `dados/` de verdade: o histórico (que recebe dados de download/tradução/leitura) vai para uma pasta temporária."""
import atexit
import shutil
import tempfile
from pathlib import Path

from baixador.biblioteca import historico, verificacao

_tmp = tempfile.mkdtemp(prefix="baixador-testes-")
atexit.register(shutil.rmtree, _tmp, True)
historico.ARQUIVO = Path(_tmp) / "historico.json"
verificacao.ARQUIVO = Path(_tmp) / "verificacao.json"
