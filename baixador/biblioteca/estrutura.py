"""Estrutura única da biblioteca: `obras/Obra/Capítulo/imagens`.

Bibliotecas antigas têm capítulos soltos na raiz (`obras/nexustoons - capítulo 12/…`) ou imagens direto na pasta da obra
(`obras/Obra/001.jpg`). `normalizar` leva tudo para `Obra/Capítulo` **só movendo** (nunca apaga, nunca sobrescreve, nunca perde
arquivo); o que não puder ser movido fica onde está e o leitor continua achando.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, List

from baixador.biblioteca import obra as dados_obra, organizacao as org
from baixador.biblioteca.capitulo import _subpastas, _varrer
from baixador.biblioteca import capitulo as _cap

_FICA_NA_OBRA = {"obra.json"}


def _unico(pai: Path, nome: str) -> Path:
    destino = pai / nome
    n = 2
    while destino.exists():
        destino = pai / f"{nome} ({n})"
        n += 1
    return destino


def _fica(entrada: Path) -> bool:
    """Arquivos que pertencem à obra (capa, obra.json, temporários) e subpastas normais (outros capítulos) não se movem."""
    if entrada.name in _FICA_NA_OBRA or entrada.name.startswith((".capa.tmp", ".obra.tmp")):
        return True
    if entrada.is_dir():
        return not entrada.name.startswith(".")
    return entrada.stem.lower() == "capa" and entrada.suffix.lower() in _cap.EXTENSOES


def _mover_conteudo(obra_dir: Path, destino: Path) -> None:
    destino.mkdir()
    for entrada in sorted(obra_dir.iterdir()):
        if entrada == destino or _fica(entrada):
            continue
        shutil.move(str(entrada), str(destino / entrada.name))


def normalizar(raiz: Path) -> Dict[str, List[str]]:
    """Leva a biblioteca para `Obra/Capítulo`. Devolve {"movidos": [...], "erros": [...]} (mensagens legíveis)."""
    raiz = Path(raiz)
    relatorio: Dict[str, List[str]] = {"movidos": [], "erros": []}
    if not raiz.is_dir():
        return relatorio
    antigos = [c for c in _varrer(raiz) if c["antigo"]]
    # 1º: imagens direto na pasta da obra (a pasta já é a obra); 2º: capítulos soltos com outro nome
    for etapa in ("obra", "solto"):
        for c in antigos:
            pasta: Path = c["pasta"]
            obra_nome = org.limpar_nome(c["obra"] or "", 80) or org.limpar_nome(pasta.name, 80) or org.SEM_OBRA
            eh_obra = org._chave(obra_nome) == org._chave(pasta.name)
            if (etapa == "obra") != eh_obra or not pasta.is_dir():
                continue
            titulo = c["titulo"]
            if c["numero"] is None and org._chave(titulo or "") == org._chave(pasta.name):
                titulo = ""                                   # o "nome" era só o da pasta antiga: sem número, sem nome
            cap_nome = org.nome_pasta_capitulo(c["numero"], titulo)
            meta_antiga = org.ler_meta(pasta)
            try:
                if eh_obra:
                    obra_dir = pasta
                    destino = _unico(obra_dir, cap_nome)
                    _mover_conteudo(obra_dir, destino)
                else:
                    obra_dir = next((p for p in _subpastas(raiz) if org._chave(p.name) == org._chave(obra_nome)), raiz / org.limpar_nome(obra_nome, 80))
                    if obra_dir.exists() and [n for n in _cap.listar_imagens(obra_dir) if Path(n).stem.lower() != "capa"]:
                        relatorio["erros"].append(f"“{pasta.name}”: a pasta “{obra_dir.name}” ainda tem imagens soltas; não mexi para não misturar.")
                        continue
                    obra_dir.mkdir(exist_ok=True)
                    destino = _unico(obra_dir, cap_nome)
                    shutil.move(str(pasta), str(destino))
                org.gravar_meta(destino, obra_nome, c["numero"], titulo, str(meta_antiga.get("url", "")))
                relatorio["movidos"].append(f"{pasta.name} → {obra_dir.name}/{destino.name}")
            except (OSError, shutil.Error) as erro:
                relatorio["erros"].append(f"“{pasta.name}”: {erro}")
    completar_obras(raiz)
    return relatorio


def mover_imagens_para_img(raiz: Path) -> Dict[str, List[str]]:
    """Leva as imagens soltas de cada capítulo (`Obra/Capítulo/001.jpg`) para `Obra/Capítulo/img/`. Os `.json` ficam onde estão.

    Só move (nunca apaga nem sobrescreve): se já existir um arquivo com o mesmo nome em `img/`, o solto fica onde está.
    Devolve {"capitulos": [...], "erros": [...]}."""
    relatorio: Dict[str, List[str]] = {"capitulos": [], "erros": []}
    for obra in _subpastas(Path(raiz)):
        for cap in _subpastas(obra):
            try:
                soltas = [e for e in cap.iterdir() if e.is_file() and not e.is_symlink() and e.suffix.lower() in _cap.EXTENSOES and not e.name.startswith(".")]
            except OSError:
                continue
            if not soltas:
                continue
            try:
                destino = cap / _cap.NOME_IMG
                destino.mkdir(exist_ok=True)
                movidas = 0
                for e in soltas:
                    alvo = destino / e.name
                    if alvo.exists():
                        relatorio["erros"].append(f"{obra.name}/{cap.name}/{e.name}: já existe em img/; deixei onde estava.")
                        continue
                    shutil.move(str(e), str(alvo))
                    movidas += 1
                if movidas:
                    relatorio["capitulos"].append(f"{obra.name}/{cap.name}")
            except (OSError, shutil.Error) as erro:
                relatorio["erros"].append(f"{obra.name}/{cap.name}: {erro}")
    return relatorio


def completar_obras(raiz: Path) -> int:
    """Cria o `obra.json` das obras que já têm capítulos com endereço salvo (a página da obra sai do endereço do capítulo)."""
    feitos = 0
    for pasta in _subpastas(Path(raiz)):
        if dados_obra.url_principal(pasta):
            continue
        url = dados_obra.url_dos_capitulos(pasta)
        if url and dados_obra.gravar(pasta, pasta.name, url):
            feitos += 1
    return feitos


__all__ = ["normalizar", "completar_obras", "mover_imagens_para_img"]
