"""Integração REAL: o Python (TarefaTraducao) chamando o tradutor em Node (OCR, detecção e limpeza de verdade) com um Ollama
falso que responde no formato do TranslateGemma. Precisa de Node 22.9+ e de `npm install` em tradutor/ (senão é ignorado).
Rodar: python -m unittest tests.test_integracao_node -v"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List

from baixador.biblioteca import acervo
from baixador.biblioteca.capitulo import dados_do_capitulo
from baixador.traducao import config, executor

FIXTURES = Path(__file__).parent / "fixtures"
TRAD = [(re.compile(r"CAN'?T BELIEVE", re.I), "NÃO ACREDITO QUE VOCÊ FEZ ISSO!"), (re.compile(r"HAVE TO LEAVE", re.I), "TEMOS QUE SAIR ANTES QUE ELES CHEGUEM."),
        (re.compile(r"WORRY", re.I), "NÃO SE PREOCUPE. EU VOU PROTEGER VOCÊ.")]


def traduz(s: str) -> str:
    return next((t for r, t in TRAD if r.search(s)), f"(traduzido) {s}")


class OllamaFalso:
    def __init__(self) -> None:
        self.lento = False
        self.chamadas = 0
        estado = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                pass

            def do_GET(self) -> None:
                corpo = json.dumps({"models": [{"name": "translategemma:4b"}]}).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(corpo))); self.end_headers(); self.wfile.write(corpo)

            def do_POST(self) -> None:
                dados = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                estado.chamadas += 1
                if estado.lento:
                    time.sleep(25)
                texto = dados["messages"][0]["content"].split("Please translate the following English text into Portuguese:\n\n\n")[1]
                saida = "\n".join(
                    (f"[{m.group(1)}] {traduz(m.group(2))}" if (m := re.match(r"^\[(\d+)\]\s*(.*)$", l)) else traduz(l)) for l in texto.split("\n")
                )
                corpo = (json.dumps({"message": {"content": saida}}) + "\n" + json.dumps({"done": True, "message": {"content": ""}}) + "\n").encode()
                self.send_response(200); self.send_header("Content-Length", str(len(corpo))); self.end_headers(); self.wfile.write(corpo)

        self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.servidor.daemon_threads = True
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.servidor.server_address[1]}"

    def parar(self) -> None:
        self.servidor.shutdown()


def esperar(tarefa: executor.TarefaTraducao, ate: float = 240) -> Dict[str, Any]:
    fim = time.time() + ate
    while time.time() < fim:
        f = tarefa.instantaneo(0)
        if f["estado"] != "executando":
            return f
        time.sleep(0.3)
    tarefa.parar()
    raise AssertionError("a tradução não terminou a tempo")


def node_pronto() -> bool:
    return executor.disponibilidade()["pronto"]


@unittest.skipUnless(node_pronto(), "Node.js 22.9+ e `npm install` em tradutor/ são necessários")
class Integracao(unittest.TestCase):
    def setUp(self) -> None:
        self.raiz = Path(tempfile.mkdtemp(prefix="obras-"))
        self.addCleanup(shutil.rmtree, self.raiz, ignore_errors=True)
        self.ollama = OllamaFalso()
        self.addCleanup(self.ollama.parar)
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self._cfg = config.ARQUIVO
        config.ARQUIVO = tmp / "traducao.json"
        self.addCleanup(setattr, config, "ARQUIVO", self._cfg)
        self._env = executor.ambiente.ler_env
        executor.ambiente.ler_env = lambda *a, **k: {"OLLAMA_URL": self.ollama.url}      # type: ignore[assignment]
        self.addCleanup(setattr, executor.ambiente, "ler_env", self._env)

    def capitulo(self, nome: str = "Capitulo 001") -> Path:
        cap = self.raiz / "Obra Teste" / nome
        (cap / "img").mkdir(parents=True)
        shutil.copy(FIXTURES / "pagina_baloes.png", cap / "img" / "001_a.png")
        return cap

    def test_traduz_capitulo_de_ponta_a_ponta(self) -> None:
        cap = self.capitulo()
        tarefa = executor.TarefaTraducao()
        tarefa.iniciar_lote([cap])
        vistos: List[int] = []
        fim = time.time() + 240
        while time.time() < fim:
            f = tarefa.instantaneo(0)
            vistos.append(f["feitas"])
            if f["estado"] != "executando":
                break
            time.sleep(0.2)
        self.assertEqual(f["estado"], "concluido", f.get("erro"))
        self.assertEqual(f["resumo"]["falas"], 3)
        self.assertEqual(f["feitas"], f["total"])
        self.assertEqual(vistos, sorted(vistos), "a barra de progresso nunca volta")
        self.assertTrue(any(0 < v < f["total"] for v in vistos), "a barra passa por valores intermediários")
        self.assertEqual(f["itens"][0]["estado"], "pronto")
        self.assertTrue(any(l.startswith("Motor:") for l in f["log"]))
        self.assertEqual(sorted(p.name for p in cap.iterdir()), ["img", "traducao", "traducao.json"])
        c = acervo.listar(self.raiz)["obras"][0]["capitulos"][0]
        self.assertTrue(c["traduzido"])
        d = dados_do_capitulo(self.raiz, "Obra Teste/Capitulo 001")
        self.assertEqual(len(d["imagens"][0]["falas"]), 3)
        self.assertTrue((cap / "traducao" / "limpeza" / d["imagens"][0]["patch"]).is_file())

    def test_ollama_fora_do_ar_falha_logo_e_sem_trocar_de_motor(self) -> None:
        cap = self.capitulo()
        executor.ambiente.ler_env = lambda *a, **k: {"OLLAMA_URL": "http://127.0.0.1:1"}  # type: ignore[assignment]
        tarefa = executor.TarefaTraducao()
        tarefa.iniciar_lote([cap])
        f = esperar(tarefa, 60)
        self.assertEqual(f["estado"], "erro")
        self.assertIn("Ollama não está rodando", f["erro"])
        self.assertEqual(sorted(p.name for p in cap.iterdir()), ["img"])
        self.assertEqual(f["modo"], "local")

    def test_motor_de_nuvem_sem_chave_pede_a_chave(self) -> None:
        cap = self.capitulo()
        config.salvar("gemini")
        tarefa = executor.TarefaTraducao()
        tarefa.iniciar_lote([cap])
        f = esperar(tarefa, 60)
        self.assertEqual(f["estado"], "erro")
        self.assertIn("GEMINI_API_KEY", f["erro"])
        self.assertEqual(sorted(p.name for p in cap.iterdir()), ["img"])

    def test_capitulo_inexistente_e_erro_e_nao_concluido(self) -> None:
        tarefa = executor.TarefaTraducao()
        tarefa.iniciar_lote([self.raiz / "Obra Teste" / "Nao Existe"])
        f = esperar(tarefa, 60)
        self.assertEqual(f["estado"], "erro")
        self.assertIn("não encontrado", f["erro"])
        self.assertEqual(f["itens"][0]["estado"], "falhou")
        with self.assertRaises(executor.ErroTraducao):
            executor.traduzir_pasta_cli(self.raiz / "Obra Teste" / "Nao Existe", informar=lambda *_: None)

    def test_caminho_relativo_funciona(self) -> None:
        import os

        cap = self.capitulo()
        antes = os.getcwd()
        os.chdir(self.raiz)                                   # o Node roda em tradutor/: o Python precisa resolver o caminho antes
        self.addCleanup(os.chdir, antes)
        r = executor.traduzir_pasta_cli(Path("Obra Teste") / "Capitulo 001", informar=lambda *_: None)
        self.assertEqual(r["falas"], 3)
        self.assertTrue((cap / "traducao.json").is_file())

    def test_cancelar_encerra_o_node_e_a_retomada_pula_o_que_ja_foi_feito(self) -> None:
        cap = self.capitulo()
        self.ollama.lento = True
        tarefa = executor.TarefaTraducao()
        tarefa.iniciar_lote([cap])
        fim = time.time() + 120
        while time.time() < fim and "Traduzindo" not in (tarefa.instantaneo(0)["itens"][0].get("etapa") or ""):
            time.sleep(0.3)
        self.assertIn("Traduzindo", tarefa.instantaneo(0)["itens"][0]["etapa"])
        tarefa.parar()
        f = esperar(tarefa, 30)
        self.assertEqual(f["estado"], "erro")
        self.assertEqual(f["erro"], "Tradução cancelada.")
        self.assertTrue((cap / "traducao.nova").is_dir())
        self.assertFalse((cap / "traducao.json").exists())
        time.sleep(1)
        vivos = subprocess.run(["ps", "-eo", "pid,stat,args"], capture_output=True, text=True).stdout.splitlines()
        vivos = [l for l in vivos if "processar-capitulo.js" in l and "ps -eo" not in l]
        self.assertEqual(vivos, [], "o Node não pode ficar rodando depois de cancelar")

        self.ollama.lento = False
        tarefa2 = executor.TarefaTraducao()
        tarefa2.iniciar_lote([cap])
        f2 = esperar(tarefa2)
        self.assertEqual(f2["estado"], "concluido", f2.get("erro"))
        self.assertTrue(any("etapa3: pronta, pulada" in l for l in f2["log"]))
        self.assertTrue((cap / "traducao.json").is_file())
        self.assertFalse((cap / "traducao.nova").exists())

    def test_cancelar_so_um_capitulo_da_fila_e_seguir(self) -> None:
        a, b = self.capitulo("Capitulo 001"), self.capitulo("Capitulo 002")
        self.ollama.lento = True
        tarefa = executor.TarefaTraducao()
        tarefa.iniciar_lote([a, b])
        fim = time.time() + 120
        while time.time() < fim and "Traduzindo" not in (tarefa.instantaneo(0)["itens"][0].get("etapa") or ""):
            time.sleep(0.3)
        self.ollama.lento = False
        self.assertEqual(tarefa.cancelar_item("Obra Teste/Capitulo 001"), "andamento")
        f = esperar(tarefa)
        self.assertEqual(f["estado"], "concluido", f.get("erro"))
        self.assertEqual([i["estado"] for i in f["itens"]], ["cancelado", "pronto"])
        self.assertFalse((a / "traducao.json").exists())
        self.assertTrue((b / "traducao.json").is_file())
        self.assertEqual(f["prontos"], 1)

    def test_traduzir_de_novo_troca_so_no_fim(self) -> None:
        cap = self.capitulo()
        t1 = executor.TarefaTraducao(); t1.iniciar_lote([cap]); self.assertEqual(esperar(t1)["estado"], "concluido")
        antiga = (cap / "traducao.json").read_text(encoding="utf-8")
        self.ollama.lento = True
        t2 = executor.TarefaTraducao(); t2.iniciar_lote([cap])
        fim = time.time() + 120
        while time.time() < fim and "Traduzindo" not in (t2.instantaneo(0)["itens"][0].get("etapa") or ""):
            time.sleep(0.3)
        t2.parar(); esperar(t2, 30)
        self.assertEqual((cap / "traducao.json").read_text(encoding="utf-8"), antiga, "a tradução anterior continua valendo")
        self.assertTrue((cap / "traducao" / "limpeza").is_dir())
        self.assertTrue(acervo.listar(self.raiz)["obras"][0]["capitulos"][0]["traduzido"])


if __name__ == "__main__":
    unittest.main()
