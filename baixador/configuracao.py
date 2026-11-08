"""Caminhos do projeto num só lugar: pasta da biblioteca, arquivos da interface web e dados persistentes."""

from __future__ import annotations

import shutil
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent          # pasta do projeto (onde ficam LEIA-ME.md, web/, obras/...)
PASTA_PADRAO = RAIZ / "obras"                          # a biblioteca: Obra/Capítulo/imagens
WEB = RAIZ / "web"                                     # frontend: notebook/, celular/, leitor/, compartilhado/
DADOS = RAIZ / "dados"                                 # configurações e dados persistentes do programa
ARQUIVO_CELULAR = DADOS / "celular.json"               # chave, porta e opção do acesso pelo celular


def migrar_pasta_biblioteca() -> str:
    """A biblioteca antes se chamava `saida/`; agora é `obras/`. Se só existe a antiga, ela é renomeada (mesmo disco, nada é copiado nem apagado).

    Devolve uma mensagem para o console ("" quando não há nada a dizer)."""
    antiga = RAIZ / "saida"
    if not antiga.is_dir() or antiga.is_symlink():
        return ""
    if PASTA_PADRAO.exists():
        try:
            if any(antiga.iterdir()):
                return "Aviso: existem as pastas `saida` e `obras`; o programa usa só `obras`. Mova à mão o que quiser de `saida`."
        except OSError:
            pass
        return ""
    try:
        antiga.rename(PASTA_PADRAO)
        return "Biblioteca: a pasta `saida` agora se chama `obras` (renomeada automaticamente)."
    except OSError as erro:
        return f"Aviso: não consegui renomear `saida` para `obras` ({erro.__class__.__name__}); renomeie à mão."


def migrar_dados_antigos() -> None:
    """Versões anteriores guardavam `celular.json` na raiz do projeto: leva para `dados/` (sem sobrescrever)."""
    antigo = RAIZ / "celular.json"
    if antigo.is_file() and not ARQUIVO_CELULAR.exists():
        try:
            DADOS.mkdir(parents=True, exist_ok=True)
            shutil.move(str(antigo), str(ARQUIVO_CELULAR))
        except OSError:
            pass
