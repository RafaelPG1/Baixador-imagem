"""Ponte entre o Baixador e o sistema de tradução em Node.js (pasta `tradutor/`).

Toda a tradução (balões, OCR, motor, limpeza do texto original) roda no Node. Este módulo só: acha o Node, chama
`tradutor/src/processar-capitulo.js` um capítulo por vez, lê as linhas de progresso que ele escreve e mostra o andamento
para a interface. O resultado (`traducao.json` + `traducao/limpeza/*.png`) é gravado pelo próprio Node dentro do capítulo.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

from baixador import configuracao
from baixador.nucleo import ambiente
from baixador.nucleo.erros import ErroBaixador
from baixador.traducao import config

TRADUTOR = configuracao.RAIZ / "tradutor"
ENTRADA = TRADUTOR / "src" / "processar-capitulo.js"
NODE_MINIMO = (22, 9)
IDIOMAS = "en → pt-BR"                                   # por enquanto só inglês para português

# Quanto cada etapa pesa na barra de progresso de um capítulo (soma 1).
PESOS = {"etapa3": 0.15, "etapa8": 0.05, "etapa4a": 0.30, "etapa4b": 0.35, "etapa4c": 0.0, "etapa6": 0.10, "leitor": 0.05}
ROTULOS = {
    "etapa3": "Achando balões", "etapa8": "Achando textos", "etapa4a": "Lendo o texto (OCR)",
    "etapa4b": "Traduzindo", "etapa4c": "Montando", "etapa6": "Limpando o texto original", "leitor": "Finalizando",
}
ESCALA = 1000                                            # feitas/total de um capítulo vão de 0 a 1000


class ErroTraducao(ErroBaixador):
    """Falha esperada da tradução, com mensagem pronta para o usuário."""


class _AbortarFila(Exception):
    """O motor (ou o Node) não está utilizável: continuar só repetiria o erro nos capítulos seguintes."""


# ------------------------------------------------------------------ Node

def _opcoes_processo() -> Dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _matar(proc: "subprocess.Popen[str]") -> None:
    """Encerra o Node e tudo que ele abriu (o Tesseract roda em worker próprio)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=15,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        try:
            proc.kill()
        except OSError:
            pass


_NODE_OK: List[str] = []                                  # só o sucesso fica em cache: instalar o Node depois vale sem reiniciar


def _node() -> Tuple[Optional[str], str]:
    """(caminho do Node, mensagem de problema). Mensagem vazia = tudo certo."""
    if _NODE_OK:
        return _NODE_OK[0], ""
    caminho = shutil.which("node")
    if not caminho:
        return None, "O Node.js não foi encontrado. Instale a versão LTS em https://nodejs.org e reabra o programa."
    try:
        saida = subprocess.run([caminho, "--version"], capture_output=True, text=True, timeout=15,
                               **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {})).stdout
        m = re.match(r"v(\d+)\.(\d+)", saida.strip())
        versao = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    except (OSError, subprocess.SubprocessError):
        return None, "Não consegui executar o Node.js. Reinstale a versão LTS em https://nodejs.org."
    if versao < NODE_MINIMO:
        return None, f"O Node.js {saida.strip()} é antigo demais; o tradutor pede {NODE_MINIMO[0]}.{NODE_MINIMO[1]} ou mais novo."
    _NODE_OK.append(caminho)
    return caminho, ""


def disponibilidade() -> Dict[str, Any]:
    """Para a aba Traduções: o sistema de tradução está instalado? `pronto` falso traz a `mensagem` com o que fazer."""
    caminho, problema = _node()
    if caminho is None:
        return {"pronto": False, "mensagem": problema}
    if not ENTRADA.is_file():
        return {"pronto": False, "mensagem": "A pasta tradutor/ do projeto está incompleta. Reinstale o programa."}
    if not (TRADUTOR / "node_modules" / "sharp").is_dir():
        return {"pronto": False, "mensagem": "Falta instalar o tradutor. Abra um terminal na pasta tradutor do projeto e rode: npm install"}
    return {"pronto": True, "mensagem": ""}


def ambiente_do_node(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Ambiente do processo Node: o do sistema + as chaves do .env que a tradução usa + o motor/modelo escolhidos."""
    cfg = cfg or config.ler()
    env = dict(os.environ)
    lido = ambiente.ler_env()
    for nome in config.VARIAVEIS_ENV:
        if lido.get(nome, "").strip():
            env[nome] = lido[nome].strip()
    env["TRANSLATION_ENGINE"] = cfg["motor"]
    env["LOCAL_MODEL"] = cfg["modelo"]
    env["TRADUTOR_EVENTOS"] = "1"
    env["NO_COLOR"] = "1"
    return env


def _comando(*args: str) -> List[str]:
    caminho, _ = _node()
    return [str(caminho), str(ENTRADA), *args]


def verificar(motor: Optional[str] = None, modelo: Optional[str] = None) -> Dict[str, Any]:
    """Botão "Verificar": o motor escolhido está pronto? Quem responde é o próprio Node (a mesma checagem que ele faz ao traduzir)."""
    cfg = config.ler()
    if motor in config.MOTORES:
        cfg["motor"] = motor
    if modelo in config.MODELOS:
        cfg["modelo"] = modelo
    d = disponibilidade()
    if not d["pronto"]:
        return {"pronto": False, "mensagem": d["mensagem"], "motor": cfg["motor"]}
    try:
        r = subprocess.run(_comando("--verificar", "--motor", cfg["motor"]), cwd=TRADUTOR, env=ambiente_do_node(cfg),
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                           **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
        resposta = json.loads(r.stdout.strip().splitlines()[-1])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return {"pronto": False, "mensagem": "Não consegui conferir o motor de tradução.", "motor": cfg["motor"]}
    if resposta.get("ok"):
        return {"pronto": True, "mensagem": f"Pronto: {resposta.get('nome', cfg['motor'])}.", "motor": cfg["motor"]}
    return {"pronto": False, "mensagem": str(resposta.get("mensagem") or "Motor indisponível."), "motor": cfg["motor"]}


def apagar_traducao(pasta: Path) -> int:
    """Apaga a tradução de um capítulo (resultado, limpeza e restos de execução interrompida). Devolve 1 se havia resultado."""
    achou = 0
    arquivo = pasta / "traducao.json"
    if arquivo.is_file() and not arquivo.is_symlink():
        arquivo.unlink()
        achou = 1
    for nome in ("traducao", "traducao.nova", "traducao.velha"):
        alvo = pasta / nome
        if alvo.is_dir() and not alvo.is_symlink():
            shutil.rmtree(alvo)
            achou = achou or 1
    (pasta / "traducao.json.tmp").unlink(missing_ok=True)
    return achou


# ------------------------------------------------------------------ tarefa

class TarefaTraducao:
    """Uma tradução (um ou vários capítulos, em sequência) por vez, em thread própria, com andamento para a interface."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._parar = threading.Event()
        self._parar_item = threading.Event()
        self._pulados: set = set()
        self.estado = "ocioso"          # ocioso | executando | concluido | erro
        self.log: List[str] = []
        self.feitas = 0
        self.total = 0
        self.pasta: Optional[Path] = None
        self.erro: Optional[str] = None
        self.resumo: Optional[Dict[str, Any]] = None
        self.prontos = 0                # capítulos do lote já traduzidos, salvos e liberados para leitura
        self.aguardando = 0             # motor "web": capítulos com os textos prontos, esperando a tradução importada
        self.capitulos = 0              # capítulos do lote
        self._guardados: List[Dict[str, Any]] = []      # "aguardando" de lotes anteriores (motor web): continuam na lista até serem aplicados
        self.itens: List[Dict[str, Any]] = []   # fila mostrada na aba Traduções: {nome, rel, estado, etapa, feitas, total}
        self.inicio = 0.0
        self.fim = 0.0
        self.modo = ""                  # motor escolhido ao iniciar; mudar a configuração depois só vale na próxima
        self.avisos: List[str] = []
        self._cfg: Dict[str, Any] = {}  # configuração da última tarefa (motor/modelo): a nova tentativa reaproveita
        self._pastas: List[Path] = []   # pasta de cada item de `itens` (mesmo índice)
        self._fechada = True            # a fila já terminou de ser percorrida: não aceita mais itens

    # -- início
    def iniciar(self, pasta: Path, cfg: Optional[Dict[str, Any]] = None) -> None:
        self.iniciar_lote([pasta], cfg=cfg)

    def iniciar_lote(self, pastas: List[Path], *_ignorados: Any, cfg: Optional[Dict[str, Any]] = None, **__ignorados: Any) -> None:
        """Traduz os capítulos em sequência. Quem chama escolheu traduzir estes capítulos, então eles são refeitos do zero.
        `cfg`: motor/modelo a usar (padrão: a configuração atual); a nova tentativa passa a da tarefa original."""
        if not pastas:
            raise ErroTraducao("Nenhum conjunto para traduzir.")
        with self._lock:
            if self.estado == "executando":
                raise RuntimeError("Já existe uma tradução em andamento.")
            cfg = dict(cfg) if cfg else config.ler()
            novos = {f"{Path(p).parent.name}/{Path(p).name}" for p in pastas}
            atuais = {it["rel"] for it in self.itens if not it.get("oculto")}
            antigos = {it["rel"]: it for it in [*(g for g in self._guardados if g["rel"] not in atuais), *self.itens] if it["estado"] == "aguardando" and not it.get("oculto") and it["rel"] not in novos}
            self._guardados = [dict(it) for it in antigos.values()]    # preparar outro capítulo não pode esconder os já preparados
            self.estado, self.log, self.feitas, self.total = "executando", [], 0, ESCALA
            self.modo, self.avisos = cfg["motor"], []
            self.prontos, self.capitulos, self.aguardando = 0, len(pastas), 0
            lista = [Path(p) for p in pastas]
            self.itens = [
                {"nome": self._nome_item(p), "rel": f"{p.parent.name}/{p.name}", "estado": "fila", "etapa": "", "feitas": 0, "total": ESCALA}
                for p in lista
            ]
            self.inicio, self.fim = time.time(), 0.0
            self.erro, self.resumo, self.pasta = None, None, lista[0]
            self._cfg, self._pastas, self._fechada = cfg, lista, False
            self._parar, self._parar_item, self._pulados = threading.Event(), threading.Event(), set()
            self._thread = threading.Thread(target=self._rodar, args=(lista, cfg), daemon=True)   # `lista` é a mesma de `_pastas`: pode crescer
            self._thread.start()

    def iniciar_ou_enfileirar_web(self, pastas: List[Path]) -> int:
        """Motor web: capítulos com todas as traduções importadas. Sem tarefa rodando, começa uma; com uma preparação web em andamento,
        entram no fim da fila dela (sem repetir quem já está lá). Com outro motor rodando, levanta RuntimeError: o motor errado não pode pegá-los."""
        with self._lock:
            if self.estado == "executando" and self._cfg.get("motor") == "web" and not self._fechada and not self._parar.is_set():
                ativos = {it["rel"] for it in self.itens if it["estado"] in ("fila", "traduzindo")}
                novos = [Path(p) for p in pastas if f"{Path(p).parent.name}/{Path(p).name}" not in ativos]
                for p in novos:
                    self.itens.append({"nome": self._nome_item(p), "rel": f"{p.parent.name}/{p.name}", "estado": "fila", "etapa": "", "feitas": 0, "total": ESCALA})
                    self._pastas.append(p)
                    self.capitulos += 1
                return len(pastas)
        self.iniciar_lote(pastas, cfg={**config.ler(), "motor": "web"})
        return len(pastas)

    @staticmethod
    def _nome_item(pasta: Path) -> str:
        return f"{pasta.parent.name} · {pasta.name}" if pasta.parent.name and pasta.parent != pasta else pasta.name

    # -- controle
    def parar(self) -> None:
        self._parar.set()

    def cancelar_item(self, rel: str) -> str:
        """Cancela SÓ um capítulo da fila: "fila" (nunca começa) ou "andamento" (para este e segue para o próximo).
        Devolve "" se não está na fila, já terminou ou é a única tradução (use Cancelar)."""
        with self._lock:
            if self.estado != "executando" or self._parar.is_set():
                return ""
            for k, it in enumerate(self.itens):
                if it.get("rel") != rel:
                    continue
                if it["estado"] == "fila":
                    it["estado"] = "cancelado"
                    self._pulados.add(k)
                    self.capitulos = max(0, self.capitulos - 1)
                    return "fila"
                if it["estado"] == "traduzindo" and len(self.itens) > 1:
                    self._parar_item.set()
                    return "andamento"
        return ""

    def tentar_novamente(self, rel: str = "") -> int:
        """Refaz os capítulos da tarefa que terminaram cancelados ou com erro (só o `rel`, se informado). Devolve quantos.

        Reaproveita a pasta de cada item e o motor/modelo da tarefa original. Com uma tradução em andamento, os capítulos
        entram no fim da fila dela (nada que está rodando é interrompido); sem tradução em andamento, começa uma nova só com eles.
        Um capítulo que já está na fila ou sendo traduzido nunca entra duas vezes."""
        with self._lock:
            ativos = {it["rel"] for it in self.itens if it["estado"] in ("fila", "traduzindo")}
            novos: List[Tuple[int, Path]] = []
            for k, it in enumerate(self.itens):
                if it["estado"] not in ("cancelado", "falhou") or it.get("oculto") or (rel and it["rel"] != rel):
                    continue
                if it["rel"] in ativos or not self._pastas[k].is_dir():
                    continue
                ativos.add(it["rel"])
                novos.append((k, self._pastas[k]))
            if not novos:
                raise ErroTraducao("Não há capítulo cancelado ou com erro para tentar de novo.")
            if self.estado == "executando":
                if self._fechada or self._parar.is_set():
                    raise RuntimeError("A tradução está terminando ou sendo cancelada. Tente de novo em instantes.")
                for k, pasta in novos:
                    if self.itens[k]["estado"] == "cancelado":
                        self.capitulos += 1                        # o cancelamento tinha tirado este capítulo da conta
                    self.itens[k]["estado"] = "refeito"            # fica no histórico, mas não volta a ser oferecido
                    self.itens.append({"nome": self._nome_item(pasta), "rel": self.itens[k]["rel"], "estado": "fila", "etapa": "", "feitas": 0, "total": ESCALA})
                    self._pastas.append(pasta)
                return len(novos)
            cfg, pastas = dict(self._cfg), [p for _, p in novos]
        self.iniciar_lote(pastas, cfg=cfg)                          # outra tarefa pode ter começado agora: levanta RuntimeError (409)
        return len(pastas)

    def limpar_registros(self, estados: Any) -> int:
        """Tira da lista os registros já encerrados em `estados` ("cancelado", "pronto"). Devolve quantos.

        Só esconde registros: nenhum arquivo é tocado, e itens na fila, em andamento ou com erro nunca saem. Os itens ficam
        na memória (marcados `oculto`) para não deslocar os índices que a tarefa em andamento usa; a tarefa já terminada, sem
        mais nada para mostrar, volta ao estado "ocioso"."""
        validos = {"cancelado", "pronto"} & set(estados or [])
        if not validos:
            raise ErroTraducao("Escolha o que limpar: cancelados ou traduzidos.")
        with self._lock:
            n = 0
            for it in self.itens:
                if it["estado"] in validos and not it.get("oculto"):
                    it["oculto"] = True
                    n += 1
            if self.estado != "executando" and all(it.get("oculto") or it["estado"] == "refeito" for it in self.itens):
                self.itens, self._pastas = [], []
                self.estado, self.erro, self.resumo = "ocioso", None, None
                self.feitas = self.total = self.prontos = self.capitulos = 0
            return n

    # -- andamento
    def _registrar(self, mensagem: str) -> None:
        with self._lock:
            if len(self.log) < 2000:
                self.log.append(mensagem)
        if mensagem.startswith(("Erro", "O Ollama", "O modelo", "A tradução", "Não foi possível")):
            print(f"[tradução] {mensagem}", file=sys.stderr, flush=True)

    def _item(self, indice: int, **campos: Any) -> None:
        with self._lock:
            if 0 <= indice < len(self.itens):
                self.itens[indice].update(campos)

    def _atualizar_global(self, indice: int, fracao: float) -> None:
        with self._lock:
            ativos = [i for i in self.itens if i["estado"] not in ("cancelado", "refeito")]
            if not ativos:
                return
            soma = 0.0
            for k, it in enumerate(self.itens):
                if it["estado"] in ("cancelado", "refeito"):
                    continue
                soma += 1.0 if it["estado"] in ("pronto", "falhou", "aguardando") else (fracao if k == indice else it["feitas"] / ESCALA)
            self.feitas = int(ESCALA * soma / len(ativos))

    def _encerrar_fila(self, pendente: str) -> None:
        with self._lock:
            self._fechada = True
            for it in self.itens:
                if it["estado"] in ("fila", "traduzindo"):
                    it["estado"] = pendente
            self.fim = time.time()

    def _liberar(self, pasta: Path) -> None:
        """Capítulo traduzido e salvo: a biblioteca (notebook e celular) passa a vê-lo agora, sem esperar o resto do lote."""
        from baixador.biblioteca import acervo as biblioteca

        biblioteca.esquecer_versao()
        with self._lock:
            self.prontos += 1
            prontos, total = self.prontos, self.capitulos
        self._registrar(f"✔ {pasta.name} traduzido e liberado para leitura ({prontos}/{total}).")

    # -- execução
    def _rodar(self, pastas: List[Path], cfg: Dict[str, Any]) -> None:
        falas = revisar = erros = 0
        falhas: List[Dict[str, str]] = []
        try:
            d = disponibilidade()
            if not d["pronto"]:
                raise ErroTraducao(d["mensagem"])
            env = ambiente_do_node(cfg)
            self._registrar(f"Motor: {config.MOTORES[cfg['motor']]} ({IDIOMAS}).")
            indice = -1
            while True:
                with self._lock:
                    indice += 1
                    if indice >= len(pastas):                      # a lista pode crescer (nova tentativa): fecha sob a trava
                        self._fechada = True
                        break
                pasta = pastas[indice]
                if self._parar.is_set():
                    raise ErroTraducao("Tradução cancelada.")
                with self._lock:
                    if indice in self._pulados:                    # cancelado da fila antes de começar
                        continue
                    self._parar_item.clear()
                self._registrar(f"== {pasta.name} ==")
                self._item(indice, estado="traduzindo", etapa="Preparando")
                desfecho, dados = self._capitulo(indice, pasta, env)
                if desfecho == "cancelado":
                    if self._parar.is_set():
                        raise ErroTraducao("Tradução cancelada.")
                    self._registrar(f"{pasta.name}: cancelado; a fila continua. O que já foi feito fica salvo e a próxima tradução retoma dali.")
                    self._item(indice, estado="cancelado", etapa="")
                    with self._lock:
                        self.capitulos = max(0, self.capitulos - 1)
                    self._parar_item.clear()
                    continue
                if desfecho == "aguardando":                       # motor "web": textos prontos, a tradução vem de fora
                    self._registrar(f"{pasta.name}: {dados.get('textos', 0)} texto(s) prontos para levar à IA na web ({dados.get('importadas', 0)} já importados).")
                    self._item(indice, estado="aguardando", etapa="", feitas=ESCALA)
                    with self._lock:
                        self.aguardando += 1
                        self.capitulos = max(0, self.capitulos - 1)       # não conta como "pronto para ler"
                    self._atualizar_global(indice, 1.0)
                    continue
                if desfecho == "falhou":
                    self._registrar(f"{pasta.name}: {dados['mensagem']}")
                    falhas.append({"imagem": pasta.name, "motivo": dados["mensagem"]})
                    self._item(indice, estado="falhou", etapa="", motivo=dados["mensagem"], feitas=ESCALA)
                    if dados.get("abortar"):
                        raise _AbortarFila(dados["mensagem"])
                    continue
                falhas[:] = [f for f in falhas if f["imagem"] != pasta.name]     # tentou de novo e deu certo: não é mais falha
                self._item(indice, estado="pronto", etapa="", feitas=ESCALA)
                self._atualizar_global(indice, 1.0)
                self._liberar(pasta)
                c = dados.get("contagens") or {}
                falas += int(dados.get("falas") or 0)
                revisar += int(c.get("revisar") or 0)
                erros += int(c.get("erro") or 0)
            if falhas and self.prontos == 0 and not self.aguardando:                       # nenhum capítulo ficou pronto: isso é erro, não "concluído"
                raise ErroTraducao(falhas[0]["motivo"] if len(falhas) == 1 else f"Nenhum capítulo foi traduzido. {falhas[0]['motivo']}")
            self._encerrar_fila("cancelado")
            with self._lock:
                self.estado, self.feitas = "concluido", ESCALA
                self.resumo = {"capitulos": self.prontos, "falas": falas, "revisar": revisar, "erros": erros, "falhas": falhas, "aguardando": self.aguardando}
            self._registrar(f"Concluído: {falas} fala(s) em {self.prontos} capítulo(s); {revisar} para revisar, {erros} com erro."
                            + (f" {self.aguardando} capítulo(s) esperam a tradução da IA na web." if self.aguardando else ""))
        except _AbortarFila as erro:
            self._encerrar_fila("cancelado")
            with self._lock:
                self.estado, self.erro = "erro", str(erro)
        except ErroTraducao as erro:
            self._encerrar_fila("cancelado")
            with self._lock:
                self.estado, self.erro = "erro", str(erro)
            self._registrar(str(erro))
        except Exception as erro:  # noqa: BLE001 — a thread nunca morre calada
            import traceback

            traceback.print_exc()
            self._encerrar_fila("falhou")
            mensagem = f"Erro inesperado ({erro.__class__.__name__}: {str(erro)[:160]})."
            with self._lock:
                self.estado, self.erro = "erro", mensagem
            self._registrar(mensagem)

    def _capitulo(self, indice: int, pasta: Path, env: Dict[str, str]) -> Tuple[str, Dict[str, Any]]:
        """Roda o Node num capítulo. Devolve ("pronto" | "cancelado" | "falhou", dados)."""
        fracoes: Dict[str, float] = {k: 0.0 for k in PESOS}
        # caminho absoluto: o Node roda dentro de tradutor/, então um caminho relativo apontaria para o lugar errado
        comando = _comando("--capitulo", str(Path(pasta).resolve()), "--motor", env["TRANSLATION_ENGINE"], "--refazer")
        proc = subprocess.Popen(
            comando, cwd=TRADUTOR, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1, **_opcoes_processo(),
        )
        fim = threading.Event()

        def vigiar() -> None:                                 # cancelar = encerrar o Node; o que já foi feito fica no disco
            while not fim.wait(0.2):
                if self._parar.is_set() or self._parar_item.is_set():
                    _matar(proc)
                    return

        threading.Thread(target=vigiar, daemon=True).start()
        pronto: Dict[str, Any] = {}
        aguardando: Optional[Dict[str, Any]] = None
        erro_evento: Optional[Dict[str, Any]] = None
        ultimas: Deque[str] = deque(maxlen=8)
        try:
            assert proc.stdout is not None
            for linha in proc.stdout:
                linha = linha.rstrip("\r\n")
                if not linha.startswith("@@"):
                    if linha.strip():
                        self._registrar(linha)
                        ultimas.append(linha)
                    continue
                try:
                    ev = json.loads(linha[2:])
                except ValueError:
                    continue
                if ev.get("evento") == "pronto":
                    pronto = ev
                elif ev.get("evento") == "aguardando":
                    aguardando = ev
                elif ev.get("evento") == "erro":
                    erro_evento = ev
                self._evento(indice, ev, fracoes)
            proc.wait()
        finally:
            fim.set()
            if proc.poll() is None:
                _matar(proc)
                proc.wait()
            if proc.stdout is not None:
                proc.stdout.close()
        if self._parar.is_set() or self._parar_item.is_set():
            return "cancelado", {}
        if proc.returncode == 0 and aguardando is not None and erro_evento is None:
            return "aguardando", aguardando
        if proc.returncode == 0 and (pronto or erro_evento is None):
            return "pronto", pronto
        mensagem = (erro_evento or {}).get("mensagem") or (ultimas[-1] if ultimas else f"O tradutor terminou com erro (código {proc.returncode}).")
        return "falhou", {"mensagem": str(mensagem), "abortar": bool((erro_evento or {}).get("abortar"))}

    def _evento(self, indice: int, ev: Dict[str, Any], fracoes: Dict[str, float]) -> None:
        etapa = ev.get("etapa")
        if ev.get("evento") == "etapa" and etapa in PESOS:
            if ev.get("estado") in ("fim", "pulada"):
                fracoes[etapa] = 1.0
            elif ev.get("estado") == "inicio":
                self._item(indice, etapa=ROTULOS[etapa])
        elif "feitas" in ev and etapa in PESOS and ev.get("total"):
            fracoes[etapa] = min(1.0, max(0.0, float(ev["feitas"]) / float(ev["total"])))
            self._item(indice, etapa=f"{ROTULOS[etapa]} ({int(ev['feitas'])}/{int(ev['total'])})")
        else:
            return
        fracao = sum(PESOS[e] * f for e, f in fracoes.items())
        self._item(indice, feitas=int(ESCALA * fracao))
        self._atualizar_global(indice, fracao)

    def instantaneo(self, desde_log: int = 0) -> Dict[str, Any]:
        with self._lock:
            return {
                "estado": self.estado, "erro": self.erro, "feitas": self.feitas, "total": self.total,
                "log": self.log[desde_log:], "log_total": len(self.log), "resumo": self.resumo,
                "prontos": self.prontos, "capitulos": self.capitulos, "aguardando": self.aguardando, "modo": self.modo,
                "cancelando": self.estado == "executando" and self._parar.is_set(), "avisos": list(self.avisos),
                "itens": [dict(i) for i in self.itens if not i.get("oculto")] + [dict(i) for i in self._guardados if not any(i["rel"] == j["rel"] and not j.get("oculto") for j in self.itens)], "inicio": self.inicio, "fim": self.fim, "agora": time.time(),
                "dependencias": disponibilidade(),
            }


def traduzir_pasta_cli(pasta: Path, informar: Any = print) -> Dict[str, Any]:
    """`python -m baixador --traduzir PASTA`: traduz um capítulo e mostra o andamento no terminal."""
    tarefa = TarefaTraducao()
    tarefa.iniciar(pasta)
    visto = 0
    try:
        while True:
            foto = tarefa.instantaneo(visto)
            for linha in foto["log"]:
                informar(linha)
            visto = foto["log_total"]
            if foto["estado"] != "executando":
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        tarefa.parar()
        raise
    if foto["estado"] == "erro":
        raise ErroTraducao(foto["erro"] or "A tradução falhou.")
    if (foto["resumo"] or {}).get("falhas"):
        raise ErroTraducao(foto["resumo"]["falhas"][0]["motivo"])
    return {"falas": int((foto["resumo"] or {}).get("falas") or 0)}
