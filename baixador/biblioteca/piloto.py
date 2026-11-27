"""Piloto automático: acompanha obras escolhidas e leva os capítulos novos até a tradução, sem tirar o controle da pessoa.

NÃO cria fila nem motor próprios. Cada etapa chama o serviço que já existe:
  verificar → `verificacao.verificar`          baixar → `SessaoManual.automatico` (o mesmo do "Atualizar" da aba Baixar)
  traduzir  → `TarefaTraducao.adicionar` / `preparar_web` (a fila de tradução existente)
O piloto só guarda um REGISTRO das tarefas dele (`dados/piloto.json`) e consulta o estado dos serviços.

Regras que o código garante:
- nasce desligado; só mexe em obras escolhidas; só baixa capítulos que a verificação achou como NOVOS (nunca os antigos/apagados);
- só traduz capítulos que ELE baixou e que ainda não têm tradução (nunca sobrescreve, nunca refaz); não duplica (cada capítulo = uma tarefa);
- só começa uma etapa pesada quando o navegador manual e a fila de tradução estão livres (tarefa manual tem prioridade e nunca é tocada);
  uma etapa pesada por vez (download OU tradução); com o notebook sobrecarregado (load médio alto) espera;
- cancelar/pausar mexe apenas no que o próprio piloto iniciou; nada é apagado;
- falha vira tarefa "erro" (até 3 tentativas automáticas, depois "precisa de atenção"); a pessoa pode tentar de novo;
- motor de tradução "IA na web" é manual por natureza: o piloto só PREPARA os textos e deixa a tarefa em "atenção" (colar e importar é com a pessoa).
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from baixador import configuracao
from baixador.biblioteca import acervo, organizacao, verificacao
from baixador.traducao import config as config_traducao
from baixador.traducao.executor import disponibilidade

ARQUIVO = configuracao.DADOS / "piloto.json"
INTERVALOS_MIN = (30, 60, 180, 360, 720, 1440)
MAX_TENTATIVAS = 3
MAX_TAREFAS = 500
MAX_HISTORICO = 300
PASSO_S = 30.0
TERMINAIS = ("feito", "cancelada")


def _padrao() -> Dict[str, Any]:
    return {"config": {"ativo": False, "pausado": False, "obras": [], "etapas": {"verificar": True, "baixar": False, "traduzir": False},
                       "limite_baixar": 3, "limite_traduzir": 3, "intervalo_min": 360},
            "tarefas": [], "historico": [], "ultima_execucao": 0}


def _chave(nome: str) -> str:
    return organizacao._chave(nome)


def validar_config(c: Any) -> str:
    """Mensagem de erro (ou "") para o que chega pela rede: tipos e limites; o que não é reconhecido é recusado."""
    if not isinstance(c, dict):
        return "Corpo inválido."
    for k in ("ativo", "pausado"):
        if k in c and not isinstance(c[k], bool):
            return f"“{k}” deve ser verdadeiro ou falso."
    if "obras" in c and not (isinstance(c["obras"], list) and len(c["obras"]) <= 1000 and all(isinstance(n, str) for n in c["obras"])):
        return "Lista de obras inválida."
    if "etapas" in c and not (isinstance(c["etapas"], dict) and all(k in ("verificar", "baixar", "traduzir") and isinstance(v, bool) for k, v in c["etapas"].items())):
        return "Etapas inválidas."
    for k in ("limite_baixar", "limite_traduzir"):
        if k in c and not (isinstance(c[k], int) and not isinstance(c[k], bool) and 1 <= c[k] <= 20):
            return "O limite por execução vai de 1 a 20."
    if "intervalo_min" in c and c["intervalo_min"] not in INTERVALOS_MIN:
        return "Intervalo inválido."
    return ""


class Piloto:
    def __init__(self, raiz: Path, manual: Any, traducao: Any, verificar: Optional[Callable[..., Any]] = None, agora: Callable[[], float] = time.time) -> None:
        self.raiz, self.manual, self.traducao, self._agora = Path(raiz), manual, traducao, agora
        self._verificar = verificar or verificacao.verificar
        self._trava = threading.RLock()
        self._ciclo = threading.Lock()                      # um ciclo por vez (o relógio e o botão "Executar agora" não se atropelam)
        self._sessao: Optional[Dict[str, Any]] = None       # download iniciado pelo piloto: {execucao, ids}
        self._thread: Optional[threading.Thread] = None

    # ---- persistência (troca atômica: parar no meio não corrompe) ------------------------------------------------------------------
    def _ler(self) -> Dict[str, Any]:
        base = _padrao()
        try:
            d = json.loads(ARQUIVO.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return base
        if isinstance(d, dict):
            for k in base:
                if isinstance(d.get(k), type(base[k])):
                    base[k] = d[k]
            base["config"] = {**_padrao()["config"], **base["config"]}
            base["config"]["etapas"] = {**_padrao()["config"]["etapas"], **(base["config"]["etapas"] if isinstance(base["config"]["etapas"], dict) else {})}
        return base

    def _gravar(self, d: Dict[str, Any]) -> None:
        ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
        tmp = ARQUIVO.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, ARQUIVO)

    def _log(self, d: Dict[str, Any], nivel: str, texto: str, obra: str = "") -> None:
        d["historico"] = ([{"t": int(self._agora() * 1000), "nivel": nivel, "obra": obra, "texto": texto}] + d["historico"])[:MAX_HISTORICO]

    # ---- configuração e controles ---------------------------------------------------------------------------------------------------
    def configurar(self, **c: Any) -> Dict[str, Any]:
        with self._trava:
            d = self._ler()
            cfg = d["config"]
            for k in ("ativo", "pausado"):
                if isinstance(c.get(k), bool):
                    cfg[k] = c[k]
            if isinstance(c.get("obras"), list):
                cfg["obras"] = sorted({str(n)[:120] for n in c["obras"] if isinstance(n, str)})[:1000]
            if isinstance(c.get("etapas"), dict):
                for k in ("verificar", "baixar", "traduzir"):
                    if isinstance(c["etapas"].get(k), bool):
                        cfg["etapas"][k] = c["etapas"][k]
            for k, maximo in (("limite_baixar", 20), ("limite_traduzir", 20)):
                if isinstance(c.get(k), int) and not isinstance(c[k], bool) and 1 <= c[k] <= maximo:
                    cfg[k] = c[k]
            if c.get("intervalo_min") in INTERVALOS_MIN:
                cfg["intervalo_min"] = c["intervalo_min"]
            self._log(d, "info", "Configuração alterada" + (": piloto ATIVADO." if c.get("ativo") is True else ": piloto DESATIVADO." if c.get("ativo") is False else "."))
            self._gravar(d)
        if cfg["pausado"] or not cfg["ativo"]:
            self._frear_download()
        return cfg

    def pausar(self, pausado: bool = True) -> None:
        self.configurar(pausado=pausado)

    def _frear_download(self) -> None:
        """Pausa/desativa: o capítulo que o piloto está baixando termina e para ali (não avança). Nunca mexe em sessão que não é dele."""
        if self._sessao and self.manual.automatico_ativo and self.manual.execucao == self._sessao["execucao"]:
            self.manual.definir_continuar(False)

    def cancelar_tarefas(self) -> int:
        """Cancela as tarefas DO PILOTO (pendentes e em andamento). Trabalho manual não é tocado."""
        n = 0
        with self._trava:
            d = self._ler()
            meus = [t for t in d["tarefas"] if t["estado"] in ("pendente", "executando", "atencao")]
            if self._sessao and self.manual.automatico_ativo and self.manual.execucao == self._sessao["execucao"]:
                self.manual.cancelar_busca()
            rels = {t["rel"] for t in meus if t["tipo"] == "traduzir" and t["estado"] == "executando" and t.get("rel")}
            if rels:
                ativos = self.traducao.rels_ativos()
                if ativos and ativos <= rels:
                    self.traducao.parar()
                else:
                    for r in rels:
                        self.traducao.cancelar_item(r)
            for t in meus:
                t["estado"], t["erro"], t["t"] = "cancelada", "Cancelada pelo piloto a pedido.", int(self._agora() * 1000)
                n += 1
            self._log(d, "info", f"{n} tarefa(s) do piloto cancelada(s).")
            self._gravar(d)
        return n

    def tentar_de_novo(self, id_: str = "") -> int:
        with self._trava:
            d = self._ler()
            n = 0
            for t in d["tarefas"]:
                if t["estado"] in ("erro", "cancelada") and (not id_ or t["id"] == id_):
                    t.update(estado="pendente", tentativas=0, erro="", t=int(self._agora() * 1000))
                    n += 1
            if n:
                self._log(d, "info", f"{n} tarefa(s) voltaram para a fila do piloto.")
                self._gravar(d)
            return n

    def executar_agora(self) -> None:
        with self._trava:
            d = self._ler()
            d["ultima_execucao"] = 0
            self._gravar(d)

    # ---- estado dos serviços --------------------------------------------------------------------------------------------------------
    def _manual_livre(self) -> bool:
        m = self.manual
        return m.estado in ("ocioso", "fechado", "erro") and not m.automatico_ativo and not m.salvando

    def _traducao_livre(self) -> bool:
        return self.traducao.estado != "executando"

    @staticmethod
    def _sobrecarregado() -> bool:
        try:
            return os.getloadavg()[0] > (os.cpu_count() or 1) * 1.5
        except (OSError, AttributeError):
            return False                                   # Windows: sem load médio

    def _biblioteca(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """{chave da obra: {número: capítulo}} do que existe AGORA."""
        acervo.esquecer_versao()
        return {_chave(o["nome"]): {c["numero"]: {**c, "obra": o["nome"]} for c in o["capitulos"] if c["numero"] is not None} for o in acervo.listar(self.raiz)["obras"]}

    # ---- ciclo ----------------------------------------------------------------------------------------------------------------------
    def ciclo(self) -> str:
        """Um passo do piloto. Devolve o que fez (para o relógio e para os testes)."""
        if not self._ciclo.acquire(blocking=False):
            return "ocupado"
        try:
            with self._trava:
                d = self._ler()
            cfg = d["config"]
            if not cfg["ativo"] or cfg["pausado"]:
                return "inativo" if not cfg["ativo"] else "pausado"
            self._reconciliar()
            fez = []
            with self._trava:
                d = self._ler()
            vencida = self._agora() * 1000 - d["ultima_execucao"] >= cfg["intervalo_min"] * 60_000
            if vencida and cfg["obras"] and (cfg["etapas"]["verificar"] or cfg["etapas"]["baixar"]):
                self._iniciar_execucao(cfg)
                fez.append("execucao")
            if not self._sobrecarregado():
                for etapa, acao in (("baixar", self._lancar_download), ("traduzir", self._lancar_traducao)):
                    if cfg["etapas"][etapa] and acao(cfg):
                        fez.append(etapa)
                        break                                # uma etapa pesada por vez
            return "+".join(fez) or "nada"
        finally:
            self._ciclo.release()

    def _iniciar_execucao(self, cfg: Dict[str, Any]) -> None:
        selecionadas = [n for n in cfg["obras"]]
        if cfg["etapas"]["verificar"]:
            r = self._verificar(self.raiz, so=selecionadas)
            with self._trava:
                d = self._ler()
                self._log(d, "info", "Verificação: " + ("já havia uma em andamento." if r.get("rodando") else f"{r.get('verificadas', 0)} obra(s), {r.get('novos', 0)} capítulo(s) novo(s), {r.get('erros', 0)} com problema."))
                self._gravar(d)
        with self._trava:
            d = self._ler()
            d["ultima_execucao"] = int(self._agora() * 1000)
            if cfg["etapas"]["baixar"]:
                self._planejar(d, cfg)
            self._gravar(d)

    def _planejar(self, d: Dict[str, Any], cfg: Dict[str, Any]) -> None:
        """Cria tarefas de download só para capítulos NOVOS (verificação) de obras escolhidas, sem repetir o que já é tarefa (qualquer estado)."""
        existentes = {t["id"] for t in d["tarefas"]}
        escolhidas = {_chave(n) for n in cfg["obras"]}
        criadas = 0
        for o in verificacao.painel(self.raiz)["obras"]:
            if _chave(o["nome"]) not in escolhidas or o["status"] != "ok":
                continue
            for c in sorted(o["novos"], key=lambda c: float(c["numero"])):
                id_ = f"baixar:{_chave(o['nome'])}:{c['numero']}"
                if id_ in existentes or criadas >= cfg["limite_baixar"]:
                    continue
                d["tarefas"].append({"id": id_, "tipo": "baixar", "obra": o["nome"], "numero": c["numero"], "url": c["url"], "rel": "", "estado": "pendente",
                                     "tentativas": 0, "erro": "", "t": int(self._agora() * 1000)})
                existentes.add(id_)
                criadas += 1
        if criadas:
            self._log(d, "info", f"{criadas} capítulo(s) novo(s) entraram na fila do piloto para baixar.")
        d["tarefas"] = d["tarefas"][-MAX_TAREFAS:]

    def _marcar(self, d: Dict[str, Any], t: Dict[str, Any], estado: str, erro: str = "") -> None:
        t["estado"], t["erro"], t["t"] = estado, erro[:300], int(self._agora() * 1000)
        nivel = "info" if estado in ("feito", "executando", "pendente") else "erro" if estado == "erro" else "atencao"
        self._log(d, nivel, {"feito": "concluído", "erro": f"falhou: {erro}", "atencao": f"precisa de atenção: {erro}", "executando": "em andamento",
                            "pendente": "voltou para a fila"}.get(estado, estado) + (f" ({erro[:120]})" if estado == "pendente" and erro else "") + f" — {t['tipo']} cap. {t['numero']}", t["obra"])

    def _falhar(self, d: Dict[str, Any], t: Dict[str, Any], erro: str) -> None:
        t["tentativas"] = t.get("tentativas", 0) + 1
        self._marcar(d, t, "pendente" if t["tentativas"] < MAX_TENTATIVAS else "erro", erro)

    # ---- reconciliação com a realidade (também recupera o que ficou no meio quando o programa foi fechado) -----------------------------
    def _reconciliar(self) -> None:
        lib = self._biblioteca()
        itens = self.traducao.itens_por_rel()
        with self._trava:
            d = self._ler()
            for t in d["tarefas"]:
                if t["estado"] not in ("executando", "atencao"):
                    continue
                cap = lib.get(_chave(t["obra"]), {}).get(t["numero"])
                if t["tipo"] == "baixar":
                    if self._sessao and self.manual.automatico_ativo and self.manual.execucao == self._sessao["execucao"]:
                        continue                              # ainda baixando
                    if cap and not cap["baixa_incompleta"]:
                        t["rel"] = cap["rel"]
                        self._marcar(d, t, "feito")
                        self._tarefa_de_traducao(d, t)
                    elif self._sessao is None and t["estado"] == "executando" and not self._manual_em_uso_pelo_piloto():
                        self._marcar(d, t, "pendente")              # o programa foi fechado no meio: volta para a fila, sem contar como falha
                    else:
                        self._falhar(d, t, (self.manual.aviso or "o capítulo não apareceu na biblioteca depois do download.")[:200] if cap is None else "download incompleto.")
                else:
                    if cap and cap["traduzido"] and not cap["incompleta"]:
                        self._marcar(d, t, "feito")
                        continue
                    it = itens.get(t["rel"])
                    if t["estado"] == "atencao":
                        continue                              # IA web: espera a pessoa
                    if it and it["estado"] in ("fila", "traduzindo"):
                        continue
                    if it and it["estado"] == "aguardando":
                        self._marcar(d, t, "atencao", "textos preparados: cole a tradução da IA na web e importe (o piloto não faz essa parte).")
                    elif it and it["estado"] == "interrompido":
                        self._marcar(d, t, "atencao", "interrompida ao fechar o programa: retome ou remova na aba Traduções.")
                    elif it and it["estado"] in ("falhou", "cancelado"):
                        self._falhar(d, t, str(it.get("motivo") or self.traducao.erro or "a tradução não terminou."))
                    else:
                        t["estado"] = "pendente"              # sumiu da fila (programa fechado no meio): volta, sem repetir o que já está pronto
            if self._sessao and not self.manual.automatico_ativo:
                if self._sessao.get("fechar") and self.manual.execucao == self._sessao["execucao"]:
                    self.manual.fechar_navegador()            # o piloto fecha só o navegador que ele mesmo abriu
                self._sessao = None
            self._gravar(d)

    def _manual_em_uso_pelo_piloto(self) -> bool:
        return bool(self._sessao) and self.manual.automatico_ativo and self.manual.execucao == self._sessao["execucao"]

    def _vencida(self, t: Dict[str, Any]) -> bool:
        """Tarefa que falhou espera (10 min × tentativas) antes de tentar de novo: não insiste no site nem no motor."""
        return self._agora() * 1000 - t.get("t", 0) >= t.get("tentativas", 0) * 600_000

    def _tarefa_de_traducao(self, d: Dict[str, Any], t: Dict[str, Any]) -> None:
        if not d["config"]["etapas"]["traduzir"]:
            return
        id_ = f"traduzir:{_chave(t['obra'])}:{t['numero']}"
        if all(x["id"] != id_ for x in d["tarefas"]):
            d["tarefas"].append({"id": id_, "tipo": "traduzir", "obra": t["obra"], "numero": t["numero"], "url": "", "rel": t["rel"], "estado": "pendente",
                                 "tentativas": 0, "erro": "", "t": int(self._agora() * 1000)})

    # ---- lançar etapas pesadas ------------------------------------------------------------------------------------------------------
    def _lancar_download(self, cfg: Dict[str, Any]) -> bool:
        with self._trava:
            d = self._ler()
            if any(t["tipo"] == "baixar" and t["estado"] == "executando" for t in d["tarefas"]):
                return False
            pend = [t for t in d["tarefas"] if t["tipo"] == "baixar" and t["estado"] == "pendente" and self._vencida(t) and _chave(t["obra"]) in {_chave(n) for n in cfg["obras"]}]
            if not pend or not self._manual_livre() or not self._traducao_livre():
                return False                                  # tarefa manual tem prioridade: o piloto espera
            obra = pend[0]["obra"]
            grupo = sorted([t for t in pend if t["obra"] == obra], key=lambda t: float(t["numero"]))[:cfg["limite_baixar"]]
            lib = self._biblioteca().get(_chave(obra), {})
            for t in grupo[:]:
                if t["numero"] in lib and not lib[t["numero"]]["baixa_incompleta"]:     # já está na biblioteca (baixado à mão): não duplica
                    t["rel"] = lib[t["numero"]]["rel"]
                    self._marcar(d, t, "feito")
                    self._tarefa_de_traducao(d, t)
                    grupo.remove(t)
            if not grupo:
                self._gravar(d)
                return False
            try:
                self.manual.automatico(grupo[0]["url"], str(self.raiz), organizar={"obra": obra, "numero": grupo[0]["numero"], "titulo": ""},
                                       continuar=len(grupo) > 1, limite=len(grupo), espera=30)
            except Exception as erro:
                for t in grupo:
                    self._falhar(d, t, f"não consegui abrir o navegador: {erro}")
                self._gravar(d)
                return False
            self._sessao = {"execucao": self.manual.execucao, "fechar": True}
            for t in grupo:
                self._marcar(d, t, "executando")
            self._gravar(d)
            return True

    def _lancar_traducao(self, cfg: Dict[str, Any]) -> bool:
        with self._trava:
            d = self._ler()
            if any(t["tipo"] == "traduzir" and t["estado"] == "executando" for t in d["tarefas"]):
                return False
            pend = [t for t in d["tarefas"] if t["tipo"] == "traduzir" and t["estado"] == "pendente" and self._vencida(t)]
            if not pend or not self._manual_livre() or not self._traducao_livre():
                return False
            lib = self._biblioteca()
            obra = pend[0]["obra"]
            alvo, pastas = [], []
            em_uso = self.traducao.rels_em_preparacao()
            for t in [x for x in pend if x["obra"] == obra][:cfg["limite_traduzir"]]:
                cap = lib.get(_chave(obra), {}).get(t["numero"])
                if cap is None:
                    self._marcar(d, t, "erro", "o capítulo não está mais na biblioteca.")
                elif cap["traduzido"] and not cap["incompleta"]:
                    self._marcar(d, t, "feito")                    # já tem tradução: nunca sobrescreve
                elif cap["incompleta"] or cap["rel"] in em_uso:
                    self._marcar(d, t, "atencao", "já tem tradução parcial ou está numa fila manual; o piloto não mexe.")
                else:
                    t["rel"] = cap["rel"]
                    alvo.append(t)
                    pastas.append(self.raiz / cap["rel"])
            if not alvo:
                self._gravar(d)
                return False
            try:
                if config_traducao.ler()["motor"] != "web" and not disponibilidade()["pronto"]:
                    for t in alvo:
                        self._marcar(d, t, "atencao", disponibilidade()["mensagem"])
                    self._gravar(d)
                    return False
                if config_traducao.ler()["motor"] == "web":
                    self.traducao.preparar_web(pastas)
                    for t in alvo:
                        self._marcar(d, t, "executando")        # vira "atenção" quando os textos ficarem prontos (reconciliação)
                else:
                    self.traducao.adicionar(pastas)
                    for t in alvo:
                        self._marcar(d, t, "executando")
            except Exception as erro:
                for t in alvo:
                    self._falhar(d, t, str(erro))
                self._gravar(d)
                return False
            self._gravar(d)
            return True

    # ---- leitura para a interface ---------------------------------------------------------------------------------------------------
    def painel(self) -> Dict[str, Any]:
        with self._trava:
            d = self._ler()
        cfg = d["config"]
        tarefas = d["tarefas"]
        ativas = [t for t in tarefas if t["estado"] not in TERMINAIS]
        estado = "desativado" if not cfg["ativo"] else "pausado" if cfg["pausado"] else "executando" if any(t["estado"] == "executando" for t in tarefas) else "ativo"
        escolhidas = set(cfg["obras"])
        return {"estado": estado, "config": cfg, "ultima_execucao": d["ultima_execucao"],
                "proxima_execucao": max(d["ultima_execucao"] + cfg["intervalo_min"] * 60_000, int(self._agora() * 1000)) if cfg["ativo"] and not cfg["pausado"] else 0,
                "tarefas": ativas + [t for t in tarefas if t["estado"] in TERMINAIS][-30:],
                "atencao": [t for t in tarefas if t["estado"] in ("erro", "atencao")],
                "historico": d["historico"][:100], "motor": config_traducao.ler()["motor"], "manual_livre": self._manual_livre(), "traducao_livre": self._traducao_livre(),
                "obras": [{"nome": o["nome"], "escolhida": o["nome"] in escolhidas} for o in acervo.listar(self.raiz)["obras"]]}

    # ---- relógio --------------------------------------------------------------------------------------------------------------------
    def iniciar(self, passo_s: float = PASSO_S) -> None:
        if self._thread is not None:
            return

        def laco() -> None:
            while True:
                time.sleep(passo_s)
                try:
                    self.ciclo()
                except Exception as erro:                     # o relógio nunca morre; o erro vai para o histórico
                    try:
                        with self._trava:
                            d = self._ler()
                            self._log(d, "erro", f"falha inesperada no piloto: {erro.__class__.__name__}: {str(erro)[:150]}")
                            self._gravar(d)
                    except Exception:
                        pass

        self._thread = threading.Thread(target=laco, daemon=True, name="piloto")
        self._thread.start()
