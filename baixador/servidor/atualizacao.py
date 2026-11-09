"""Atualização do app Android pelo próprio app.

O APK novo é compilado pelo GitHub Actions e publicado na release "apk-latest". O app não fala com o GitHub: pergunta ao
notebook (pelo mesmo caminho privado do Tailscale), e o notebook busca a release, guarda o APK em dados/apk/ e o entrega.
Assim funciona também com repositório PRIVADO (token opcional no .env, nunca em código, log ou mensagem) e o celular não
precisa de acesso ao GitHub.

Repositório: lido de `github_repo` no .env ("dono/repo") ou do `.git/config` da pasta do projeto.
Token (só para repositório privado): `github_token` no .env.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import urlsplit

from baixador.traducao import ambiente

TAG = "apk-latest"
NOME_APK = "BaixadorLeitor.apk"
_REPO = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_REMOTO = re.compile(r"github\.com[:/]+([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?\s*$")
_HOSTS_OK = ("api.github.com", "github.com")
USER_AGENT = "baixador-leitor-atualizacao"


class _SemAuthEntreHosts(urllib.request.HTTPRedirectHandler):
    """Ao seguir um redirecionamento para OUTRO site (o GitHub manda o APK para um armazenamento de arquivos), o token não vai junto."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        novo = super().redirect_request(req, fp, code, msg, headers, newurl)
        if novo is not None and urlsplit(newurl).netloc != urlsplit(req.full_url).netloc:
            novo.remove_header("Authorization")
        return novo


def _abrir_padrao(req: urllib.request.Request, timeout: float):
    return urllib.request.build_opener(_SemAuthEntreHosts).open(req, timeout=timeout)


def repo_do_git(raiz_projeto: Path) -> str:
    """'dono/repo' do remote origin em .git/config ('' se não houver)."""
    try:
        texto = (Path(raiz_projeto) / ".git" / "config").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for bloco in re.split(r"(?m)^\[", texto):
        if bloco.startswith('remote "origin"'):
            m = re.search(r"(?m)^\s*url\s*=\s*(.+?)\s*$", bloco)
            if m:
                achado = _REMOTO.search(m.group(1))
                if achado:
                    return f"{achado.group(1)}/{achado.group(2)}"
    return ""


def numero_da_versao(nome: str) -> Optional[int]:
    """'Baixador Leitor 1.0.12' -> 12 (o número da execução do fluxo). None se não achar."""
    m = re.search(r"(\d+)\s*$", (nome or "").strip())
    return int(m.group(1)) if m else None


class Atualizador:
    def __init__(self, raiz_projeto: Path, pasta_cache: Path, env: Optional[Path] = None,
                 abrir: Optional[Callable[..., Any]] = None):
        self.raiz_projeto = Path(raiz_projeto)
        self.pasta = Path(pasta_cache)
        self.env = env
        self._abrir = abrir or _abrir_padrao
        self._trava = threading.Lock()
        self._trava_dl = threading.Lock()
        self._release: Optional[Dict[str, Any]] = None
        self._release_em = 0.0

    # ---- configuração (lida a cada uso: editar o .env vale sem reiniciar)
    def _variaveis(self) -> Dict[str, str]:
        return ambiente.ler_env(self.env)

    def repo(self) -> str:
        valor = self._variaveis().get("github_repo", "").strip().strip("/")
        if valor.startswith("https://github.com/"):
            valor = valor[len("https://github.com/"):]
        if valor.endswith(".git"):
            valor = valor[:-4]
        if valor:
            return valor if _REPO.match(valor) else ""
        return repo_do_git(self.raiz_projeto)

    def _token(self) -> str:
        return self._variaveis().get("github_token", "").strip()

    # ---- GitHub
    def _pedir(self, url: str, aceita: str, timeout: float = 20):
        host = urlsplit(url).netloc
        if urlsplit(url).scheme != "https" or host not in _HOSTS_OK:
            raise ValueError("endereço fora do GitHub")
        cab = {"User-Agent": USER_AGENT, "Accept": aceita, "X-GitHub-Api-Version": "2022-11-28"}
        token = self._token()
        if token:
            cab["Authorization"] = "Bearer " + token
        return self._abrir(urllib.request.Request(url, headers=cab), timeout)

    def consultar(self, agora: float = 0.0, forcar: bool = False) -> Dict[str, Any]:
        """{disponivel, versao, nome, tamanho} ou {disponivel: False, motivo}. Guarda a resposta por 60 s."""
        import time
        agora = agora or time.monotonic()
        with self._trava:
            if not forcar and self._release is not None and agora - self._release_em < 60:
                return dict(self._release)
        resp = self._consultar_github()
        with self._trava:
            self._release, self._release_em = resp, agora
        return dict(resp)

    def _consultar_github(self) -> Dict[str, Any]:
        repo = self.repo()
        if not repo:
            return {"disponivel": False, "motivo": "O notebook não sabe qual é o repositório do GitHub. Coloque github_repo=dono/repositório no arquivo .env."}
        try:
            with self._pedir(f"https://api.github.com/repos/{repo}/releases/tags/{TAG}", "application/vnd.github+json") as r:
                dados = json.loads(r.read(2_000_000).decode("utf-8"))
        except urllib.error.HTTPError as erro:
            if erro.code == 404:
                if self._token():
                    return {"disponivel": False, "motivo": "Não achei a release do APK. Compile o app no GitHub (Actions → Compilar APK) ou confira github_repo/github_token no .env."}
                return {"disponivel": False, "motivo": "Não achei a release do APK. Se o repositório for privado, coloque github_token no .env; senão, compile o app no GitHub."}
            if erro.code in (401, 403):
                return {"disponivel": False, "motivo": "O GitHub recusou o acesso (limite de consultas ou token inválido)."}
            return {"disponivel": False, "motivo": f"O GitHub respondeu erro {erro.code}."}
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            return {"disponivel": False, "motivo": "O notebook não conseguiu falar com o GitHub (sem internet?)."}
        asset = next((a for a in dados.get("assets", []) if a.get("name") == NOME_APK), None)
        versao = numero_da_versao(str(dados.get("name") or ""))
        if not asset or versao is None:
            return {"disponivel": False, "motivo": "A release do GitHub não tem o APK esperado."}
        return {"disponivel": True, "versao": versao, "nome": str(dados.get("name")), "tamanho": int(asset.get("size") or 0),
                "_url": str(asset.get("browser_download_url") or ""), "_api": str(asset.get("url") or "")}

    # ---- o arquivo
    def arquivo_apk(self) -> Tuple[Optional[Path], str]:
        """(caminho, "") do APK da última release, baixando-o do GitHub se ainda não estiver em dados/apk/; (None, motivo) se falhar."""
        info = self.consultar()
        if not info.get("disponivel"):
            return None, str(info.get("motivo") or "Sem atualização disponível.")
        destino = self.pasta / f"BaixadorLeitor-{int(info['versao'])}.apk"
        with self._trava_dl:                                       # um download por vez; o segundo pedido reaproveita o arquivo
            if destino.is_file() and (not info["tamanho"] or destino.stat().st_size == info["tamanho"]):
                return destino, ""
            return self._baixar(info, destino)

    def _baixar(self, info: Dict[str, Any], destino: Path) -> Tuple[Optional[Path], str]:
        # Com token, a rota da API (Accept: octet-stream) serve repositório privado; sem token, o link público.
        url, aceita = (info["_api"], "application/octet-stream") if self._token() and info.get("_api") else (info["_url"], "application/octet-stream")
        parcial = destino.with_suffix(".part")
        try:
            self.pasta.mkdir(parents=True, exist_ok=True)
            with self._pedir(url, aceita, timeout=120) as r, open(parcial, "wb") as f:
                while True:
                    pedaco = r.read(1024 * 256)
                    if not pedaco:
                        break
                    f.write(pedaco)
            if info["tamanho"] and parcial.stat().st_size != info["tamanho"]:
                parcial.unlink(missing_ok=True)
                return None, "O download do APK veio incompleto. Tente de novo."
            parcial.replace(destino)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            try:
                parcial.unlink(missing_ok=True)
            except OSError:
                pass
            return None, "O notebook não conseguiu baixar o APK do GitHub. Tente de novo."
        for velho in self.pasta.glob("BaixadorLeitor-*.apk"):      # guarda só a versão atual
            if velho != destino:
                try:
                    velho.unlink()
                except OSError:
                    pass
        return destino, ""

    def para_o_app(self) -> Dict[str, Any]:
        """A resposta de consultar() sem os campos internos (endereços do GitHub)."""
        return {k: v for k, v in self.consultar().items() if not k.startswith("_")}
