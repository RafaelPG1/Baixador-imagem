"""Histórico de leitura: posição, estado das obras, sincronização com regra de conflito."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from baixador.biblioteca import historico, lidos


class Historico(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        d = Path(t.name)
        for alvo, nome in ((historico, "historico.json"), (lidos, "lidos.json")):
            p = mock.patch.object(alvo, "ARQUIVO", d / nome)
            p.start()
            self.addCleanup(p.stop)
        lidos._cache.update(assinatura=None, lidos=frozenset())

    def test_posicao_so_grava_se_mudou_e_se_for_mais_nova(self):
        agora = int(time.time() * 1000)
        self.assertTrue(historico.salvar_posicao("O/C1", 3, 10, 0.5, agora))
        self.assertFalse(historico.salvar_posicao("O/C1", 3, 10, 0.505, agora + 10))     # mesma página, quase mesma fração: sem escrita
        self.assertFalse(historico.salvar_posicao("O/C1", 5, 10, 0.1, agora - 5000))      # mais velha
        self.assertTrue(historico.salvar_posicao("O/C1", 5, 10, 0.1, agora + 20))
        self.assertEqual(historico.ler()["posicoes"]["O/C1"]["p"], 5)
        for ruim in (("O/C1", 0, 10, 0), ("O/C1", 11, 10, 0), ("O/C1", 1, 10, 2), ("../x", 1, 2, 0), ("O/C1", "a", 2, 0)):
            self.assertFalse(historico.salvar_posicao(*ruim))

    def test_ultima_ignora_capitulo_terminado(self):
        agora = int(time.time() * 1000)
        historico.salvar_posicao("O/C1", 4, 10, 0.2, agora - 100)
        historico.salvar_posicao("O/C2", 10, 10, 0.9, agora)                               # chegou ao fim
        self.assertEqual(historico.ultima()["rel"], "O/C1")

    def test_sincronia_mais_novo_vence_nos_dois_sentidos(self):
        agora = int(time.time() * 1000)
        historico.salvar_posicao("O/C1", 7, 10, 0.3, agora)                                # notebook leu depois
        r = historico.mesclar({"posicoes": {"O/C1": {"p": 2, "n": 10, "f": 0.1, "t": agora - 60000},          # app mandou dado velho
                                            "O/C2": {"p": 4, "n": 9, "f": 0.0, "t": agora - 1000}}})
        self.assertEqual(r["posicoes"]["O/C1"]["p"], 7)                                    # não foi sobrescrito
        self.assertEqual(r["posicoes"]["O/C2"]["p"], 4)                                    # item novo entrou
        r = historico.mesclar({"posicoes": {"O/C1": {"p": 9, "n": 10, "f": 0.0, "t": agora + 5000}}})
        self.assertEqual(r["posicoes"]["O/C1"]["p"], 9)                                    # dado mais novo vence

    def test_lidos_e_estado_da_obra_sincronizam_sem_voltar_no_tempo(self):
        agora = int(time.time() * 1000)
        lidos.marcar("O/C1", True)
        historico.marcar_lido("O/C1", True, agora)
        historico.mesclar({"lidos": {"O/C1": {"v": False, "t": agora - 1000}, "O/C2": {"v": True, "t": agora}}})
        self.assertIn("O/C1", lidos.todos())                                               # desmarcar velho foi ignorado
        self.assertIn("O/C2", lidos.todos())
        historico.mesclar({"lidos": {"O/C1": {"v": False, "t": agora + 1000}}})
        self.assertNotIn("O/C1", lidos.todos())
        self.assertTrue(historico.definir_estado("Obra", "lendo", agora))
        r = historico.mesclar({"estados": {"Obra": {"e": "quero", "t": agora - 1}, "Outra": {"e": "concluida", "t": agora}, "X": {"e": "lixo", "t": agora}}})
        self.assertEqual((r["estados"]["Obra"]["e"], r["estados"]["Outra"]["e"], "X" in r["estados"]), ("lendo", "concluida", False))

    def test_relogio_no_futuro_nao_trava_o_item(self):
        historico.mesclar({"posicoes": {"O/C1": {"p": 1, "n": 5, "f": 0, "t": 99999999999999}}})
        self.assertLess(historico.ler()["posicoes"]["O/C1"]["t"], time.time() * 1000 + 90_000_000)


if __name__ == "__main__":
    unittest.main()


class SincroniaCelular(unittest.TestCase):
    def setUp(self):
        import http.client
        import threading
        from baixador.servidor.celular import ServidorCelular
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        d = Path(t.name)
        for alvo, nome in ((historico, "historico.json"), (lidos, "lidos.json")):
            p = mock.patch.object(alvo, "ARQUIVO", d / nome)
            p.start()
            self.addCleanup(p.stop)
        lidos._cache.update(assinatura=None, lidos=frozenset())
        self.srv = ServidorCelular(d, "chave-de-teste-1234567890", 0, "127.0.0.1")
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.http = http.client

    def post(self, caminho, corpo, chave="chave-de-teste-1234567890"):
        c = self.http.HTTPConnection("127.0.0.1", self.srv.porta, timeout=5)
        cab = {"Content-Type": "application/json"}
        if chave:
            cab["Authorization"] = "Bearer " + chave
        c.request("POST", caminho, body=corpo if isinstance(corpo, bytes) else __import__("json").dumps(corpo), headers=cab)
        r = c.getresponse()
        out = (r.status, r.read())
        c.close()
        return out

    def test_sincronia_exige_chave_e_so_esse_caminho_aceita_post(self):
        import json
        agora = int(time.time() * 1000)
        self.assertEqual(self.post("/api/app/sincronia", {}, chave="")[0], 401)
        self.assertEqual(self.post("/api/app/sincronia", {}, chave="errada" * 4)[0], 401)
        self.assertEqual(self.post("/api/biblioteca", {})[0], 405)               # o resto continua somente leitura
        self.assertEqual(self.post("/api/app/sincronia", b"{nao json")[0], 400)
        self.assertEqual(self.post("/api/app/sincronia", b"x" * 300000)[0], 400)
        st, corpo = self.post("/api/app/sincronia", {"posicoes": {"O/C1": {"p": 2, "n": 8, "f": 0.4, "t": agora}}, "estados": {"O": {"e": "lendo", "t": agora}}})
        r = json.loads(corpo)
        self.assertEqual((st, r["posicoes"]["O/C1"]["p"], r["estados"]["O"]["e"], r["ultima"]["rel"]), (200, 2, "lendo", "O/C1"))
        self.assertEqual(historico.ler()["posicoes"]["O/C1"]["p"], 2)             # ficou no notebook
