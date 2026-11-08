"""Escolha do navegador que o Playwright vai abrir (Brave, Edge, Chrome, Chromium ou outro).

O Brave (e qualquer navegador baseado em Chromium) é aberto pelo caminho do executável.
Edge e Chrome são abertos pelo "canal" do Playwright, que os localiza sozinho.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from baixador.nucleo.erros import CapturaIndisponivel

NOMES: Dict[str, str] = {
    "auto": "Automático (Edge, Chrome, Brave ou Chromium)",
    "brave": "Brave",
    "edge": "Microsoft Edge",
    "chrome": "Google Chrome",
    "chromium": "Chromium do Playwright",
    "outro": "Outro (informar o caminho do programa)",
}

# Nomes de executável aceitos em "Outro": evita que a interface execute qualquer arquivo.
EXECUTAVEIS_PERMITIDOS = {
    "brave.exe", "brave", "brave-browser", "brave-browser-stable", "brave browser",
    "chrome.exe", "chrome", "google-chrome", "google-chrome-stable", "google chrome",
    "msedge.exe", "msedge", "microsoft-edge", "microsoft-edge-stable", "microsoft edge",
    "chromium", "chromium-browser", "chromium.exe",
}


def _bases_windows() -> List[Path]:
    chaves = ("PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "LOCALAPPDATA")
    return [Path(valor) for chave in chaves if (valor := os.environ.get(chave))]


def _caminhos_possiveis(escolha: str) -> List[Path]:
    caminhos: List[Path] = []
    windows = sys.platform.startswith("win")
    mac = sys.platform == "darwin"

    if escolha == "brave":
        if windows:
            caminhos += [b / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe" for b in _bases_windows()]
        elif mac:
            sufixo = Path("Applications/Brave Browser.app/Contents/MacOS/Brave Browser")
            caminhos += [Path("/") / sufixo, Path.home() / sufixo]
        else:
            caminhos += [Path(p) for n in ("brave-browser", "brave-browser-stable", "brave") if (p := shutil.which(n))]
            caminhos += [Path("/opt/brave.com/brave/brave")]
    elif escolha == "edge":
        if windows:
            caminhos += [b / "Microsoft" / "Edge" / "Application" / "msedge.exe" for b in _bases_windows()]
        elif mac:
            caminhos += [Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")]
        else:
            caminhos += [Path(p) for n in ("microsoft-edge", "microsoft-edge-stable") if (p := shutil.which(n))]
    elif escolha == "chrome":
        if windows:
            caminhos += [b / "Google" / "Chrome" / "Application" / "chrome.exe" for b in _bases_windows()]
        elif mac:
            caminhos += [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
        else:
            caminhos += [Path(p) for n in ("google-chrome", "google-chrome-stable") if (p := shutil.which(n))]
    return caminhos


def detectar(escolha: str) -> Optional[Path]:
    """Caminho do executável se o navegador estiver instalado em um local conhecido."""
    for caminho in _caminhos_possiveis(escolha):
        try:
            if caminho.is_file():
                return caminho
        except OSError:
            continue
    return None


def validar_caminho(caminho: Optional[str]) -> Path:
    """Aceita só o executável de um navegador conhecido, que exista de fato."""
    texto = (caminho or "").strip().strip('"')
    if not texto:
        raise CapturaIndisponivel("Informe o caminho do programa do navegador.")
    arquivo = Path(texto).expanduser()
    try:
        existe = arquivo.is_file()
    except OSError:
        existe = False
    if not existe:
        raise CapturaIndisponivel(f"O arquivo '{texto}' não existe.")
    if arquivo.name.lower() not in EXECUTAVEIS_PERMITIDOS:
        raise CapturaIndisponivel(
            f"'{arquivo.name}' não parece um navegador compatível (esperado: brave.exe, chrome.exe, "
            "msedge.exe, chromium...)."
        )
    return arquivo


def tentativas(escolha: str, caminho_outro: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lista de argumentos para `chromium.launch()`, na ordem em que devem ser tentados."""
    if escolha not in NOMES:
        raise ValueError(f"Navegador desconhecido: '{escolha}'.")

    if escolha == "auto":
        lista: List[Dict[str, Any]] = [{"channel": "msedge"}, {"channel": "chrome"}]
        brave = detectar("brave")
        if brave:
            lista.append({"executable_path": str(brave)})
        lista.append({})  # Chromium do Playwright
        return lista
    if escolha == "brave":
        brave = detectar("brave")
        if brave is None:
            procurados = "; ".join(str(c) for c in _caminhos_possiveis("brave")) or "locais padrão"
            raise CapturaIndisponivel(
                "Brave não encontrado. Procurei em: " + procurados + ". "
                "Se ele está em outro lugar, escolha 'Outro' e informe o caminho do brave.exe."
            )
        return [{"executable_path": str(brave)}]
    if escolha == "edge":
        return [{"channel": "msedge"}]
    if escolha == "chrome":
        return [{"channel": "chrome"}]
    if escolha == "chromium":
        return [{}]
    return [{"executable_path": str(validar_caminho(caminho_outro))}]  # "outro"


def pasta_perfis() -> Path:
    """Onde ficam os perfis próprios do programa (fora da pasta do projeto)."""
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / "BaixadorImagens" / "perfis"


def chave_do_navegador(argumentos: Dict[str, Any]) -> str:
    """Nome da pasta de perfil: um perfil por navegador, para versões diferentes não se misturarem."""
    exe = argumentos.get("executable_path")
    if exe:
        nome = Path(exe).stem.lower()
        chave = nome if nome == "brave" else f"{nome}-exe"
    else:
        chave = argumentos.get("channel") or "chromium"
    return "".join(c for c in chave if c.isalnum() or c in "-_") or "navegador"


def pasta_do_perfil(argumentos: Dict[str, Any]) -> Path:
    pasta = pasta_perfis() / chave_do_navegador(argumentos)
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def apagar_perfis() -> Path:
    """Apaga todos os perfis próprios (extensões, logins e configurações guardados)."""
    import shutil

    pasta = pasta_perfis()
    if pasta.exists():
        shutil.rmtree(pasta)
    return pasta


def opcoes() -> List[Dict[str, Any]]:
    """Lista para a interface: id, nome e se foi encontrado no computador."""
    resultado = []
    for id_, nome in NOMES.items():
        encontrado: Optional[bool] = None
        if id_ in ("brave", "edge", "chrome"):
            encontrado = detectar(id_) is not None
        resultado.append({"id": id_, "nome": nome, "encontrado": encontrado})
    return resultado


def padrao() -> str:
    """Brave, se estiver instalado; senão, automático."""
    return "brave" if detectar("brave") else "auto"
