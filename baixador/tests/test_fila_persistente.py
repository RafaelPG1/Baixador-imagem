import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from baixador.nucleo import energia
from baixador.tests.test_web_ia_lotes import criar
from baixador.traducao import executor


class FilaPersistente(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.raiz = Path(self._t.name) / "obras"
        self.arq = Path(self._t.name) / "dados" / "fila.json"
        self.addCleanup(self._t.cleanup)
        self.rels = [criar(self.raiz, "Obra A", n, f"{n:08x}", preparado=False) for n in (1, 2, 3)]
        self.t = executor.TarefaTraducao()
        self.t.usar_arquivo_fila(self.arq, self.raiz)
        for p in (mock.patch.object(executor, "disponibilidade", return_value={"pronto": True}), mock.patch.object(executor, "ambiente_do_node", return_value={}),
                  mock.patch.object(executor.config, "ler", return_value={"motor": "local", "modelo": "translategemma:4b"}), mock.patch.object(self.t, "_liberar")):
            p.start(); self.addCleanup(p.stop)
        self.chamadas = []

    def _rodar_com(self, ret):
        def capitulo(indice, pasta, env):
            self.chamadas.append(pasta.name)
            return ret(pasta)
        return mock.patch.object(self.t, "_capitulo", side_effect=capitulo)

    def test_fila_grava_so_o_pendente_e_some_ao_terminar(self):
        parado = __import__("threading").Event()

        def lento(pasta):
            parado.wait(5)
            return ("pronto", {"falas": 1, "contagens": {}})
        with self._rodar_com(lento):
            self.t.adicionar([self.raiz / r for r in self.rels])
            time.sleep(0.2)
            salvo = json.loads(self.arq.read_text())
            self.assertEqual([i["rel"] for i in salvo["itens"]], self.rels)
            self.assertEqual((salvo["motor"], "tokens" in json.dumps(salvo)), ("local", False))
            parado.set()
            self.t._thread.join(5)
        self.assertFalse(self.arq.exists(), "fila vazia = arquivo removido")

    def test_reabrir_recupera_como_interrompido_sem_rodar_sozinho_e_retoma_sem_duplicar(self):
        self.arq.parent.mkdir(parents=True)
        self.arq.write_text(json.dumps({"versao": 1, "motor": "local", "modelo": "translategemma:4b", "itens": [{"rel": self.rels[0]}, {"rel": self.rels[1]}, {"rel": self.rels[1]}, {"rel": "Obra A/Fantasma"}, {"rel": "../x"}]}))
        novo = executor.TarefaTraducao()
        self.assertEqual(novo.usar_arquivo_fila(self.arq, self.raiz), 2)
        self.assertEqual([(i["rel"], i["estado"]) for i in novo.itens], [(self.rels[0], "interrompido"), (self.rels[1], "interrompido")])
        self.assertEqual((novo.estado, self.chamadas), ("ocioso", []), "nada executa sozinho")
        self.assertTrue(self.arq.exists(), "o arquivo continua até a pessoa decidir")
        self.t = novo
        with mock.patch.object(novo, "_liberar"), self._rodar_com(lambda p: ("pronto", {"falas": 1, "contagens": {}})):
            self.assertEqual(novo.remover_interrompido(self.rels[1]), True)
            self.assertEqual(novo.retomar(), 1)
            novo._thread.join(5)
        self.assertEqual(self.chamadas, ["Capitulo 1"])
        self.assertEqual([i["estado"] for i in novo.instantaneo()["itens"]], ["pronto"])
        self.assertFalse(self.arq.exists())

    def test_pedir_capitulo_interrompido_reusa_o_registro(self):
        self.arq.parent.mkdir(parents=True)
        self.arq.write_text(json.dumps({"versao": 1, "motor": "local", "itens": [{"rel": self.rels[0]}]}))
        self.t.usar_arquivo_fila(self.arq, self.raiz)
        with self._rodar_com(lambda p: ("pronto", {"falas": 1, "contagens": {}})):
            self.t.adicionar([self.raiz / self.rels[0], self.raiz / self.rels[2]])
            self.t._thread.join(5)
        self.assertEqual(sorted(self.chamadas), ["Capitulo 1", "Capitulo 3"])
        self.assertEqual(len([i for i in self.t.itens if i["rel"] == self.rels[0]]), 1, "sem entrada duplicada")

    def test_arquivo_corrompido_nao_derruba(self):
        self.arq.parent.mkdir(parents=True)
        self.arq.write_text("{ruim")
        self.assertEqual(executor.TarefaTraducao().usar_arquivo_fila(self.arq, self.raiz), 0)

    def test_cancelar_limpa_o_arquivo_e_estimativa_usa_historico(self):
        parar = __import__("threading").Event()
        with self._rodar_com(lambda p: (parar.wait(5), ("pronto", {"falas": 1, "contagens": {}}))[1]):
            self.t._duracoes["local"] = [10.0, 30.0, 20.0]
            self.t.adicionar([self.raiz / r for r in self.rels])
            time.sleep(0.2)
            eta = self.t.instantaneo()["eta"]
            self.assertTrue(40 <= eta <= 60, eta)                                    # mediana 20 s × (2 na fila + o atual quase inteiro)
            self.t._encerrar_fila("cancelado")
            self.assertFalse(self.arq.exists())
            parar.set()


class Energia(unittest.TestCase):
    def test_pede_e_devolve_mesmo_com_excecao_e_aninhado(self):
        chamadas = []
        falso = mock.Mock(SetThreadExecutionState=lambda f: chamadas.append(f))
        with mock.patch.object(energia, "_api", falso):
            with self.assertRaises(ValueError):
                with energia.acordado():
                    with energia.acordado():
                        pass
                    self.assertEqual(len(chamadas), 1, "o aninhado não devolve antes da hora")
                    raise ValueError
        self.assertEqual(chamadas, [energia.ES_CONTINUOUS | energia.ES_SYSTEM_REQUIRED, energia.ES_CONTINUOUS])

    def test_ocioso_nao_pede_nada_e_falha_do_sistema_nao_derruba(self):
        ruim = mock.Mock(SetThreadExecutionState=mock.Mock(side_effect=OSError))
        with mock.patch.object(energia, "_api", ruim):
            with energia.acordado():
                pass

    def test_tarefa_roda_dentro_do_bloco(self):
        t = executor.TarefaTraducao()
        vistos = []
        with mock.patch.object(executor.energia, "acordado", side_effect=lambda: (vistos.append("entrou"), __import__("contextlib").nullcontext())[1]), mock.patch.object(t, "_rodar_fila"):
            t._rodar([], {})
        self.assertEqual(vistos, ["entrou"])


if __name__ == "__main__":
    unittest.main()
