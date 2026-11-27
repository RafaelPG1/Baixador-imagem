"""Histórico das obras: independente da biblioteca, só acrescenta, sobrevive a exclusão e reinício."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from baixador.biblioteca import acervo, historico, lidos, obra as dados_obra
from baixador.tests.test_web_ia_lotes import criar

URL = "https://site.com/title/minha-obra/"


class HistoricoObras(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.dir = Path(t.name)
        self.raiz = self.dir / "obras"
        self.raiz.mkdir()
        for alvo, nome in ((historico, "historico.json"), (lidos, "lidos.json")):
            p = mock.patch.object(alvo, "ARQUIVO", self.dir / nome)
            p.start()
            self.addCleanup(p.stop)
        lidos._cache.update(assinatura=None, lidos=frozenset())

    def ficha(self, nome="Minha Obra"):
        return next(f for f in historico.ler()["obras"].values() if f["nome"] == nome)

    def cap(self, n, nome="Minha Obra"):
        rel = criar(self.raiz, nome, n, f"{n:08x}", preparado=False)
        acervo.esquecer_versao()
        return self.raiz / rel

    def test_cadastro_pelo_obra_json(self):
        self.cap(1)
        dados_obra.gravar(self.raiz / "Minha Obra", "Minha Obra", URL + "123-chapter-1")
        f = self.ficha()
        self.assertEqual((f["url"], f["site"], f["situacao"]), (URL, "site.com", "andamento"))

    def test_descoberta_download_traducao_leitura(self):
        historico.registrar_obra("Minha Obra", URL, encontrado=50, descoberta=True, conhecidos={"49": "u49", "50": "u50"})
        pasta = self.cap(3)
        historico.anotar_capitulo(pasta, baixado=True)
        historico.anotar_capitulo(pasta, traduzido=True)
        historico.anotar_capitulo(pasta, lido=True, pos={"p": 4, "t": 10, "f": 0.5})
        f = self.ficha()
        self.assertEqual((f["encontrado"], f["baixado"], f["traduzido"], f["lido"]), ("50", "3", "3", "3"))
        self.assertEqual(f["pos"], {"n": "3", "p": 4, "t": 10, "f": 0.5})
        self.assertTrue(f["t_descoberta"] and f["t_lido"] and f["t_atualizado"])
        self.assertEqual(set(f["conhecidos"]), {"3", "49", "50"})
        self.assertEqual(f["conhecidos"]["50"], "u50")

    def test_nunca_rebaixa_nem_apaga(self):
        historico.registrar_obra("Minha Obra", URL, encontrado=50, baixado=10, conhecidos={"1": "u1"})
        historico.registrar_obra("Minha Obra", "", encontrado=20, baixado="2", conhecidos={"1": ""})     # menor e vazio
        f = self.ficha()
        self.assertEqual((f["encontrado"], f["baixado"], f["url"], f["conhecidos"]["1"]), ("50", "10", URL, "u1"))

    def test_leitura_mais_nova_vence_mesmo_voltando_capitulo(self):
        agora = int(time.time() * 1000)
        historico.registrar_obra("Minha Obra", URL, lido=9, t=agora)
        historico.registrar_obra("Minha Obra", URL, lido=2, t=agora - 5000)         # velha: ignorada
        self.assertEqual(self.ficha()["lido"], "9")
        historico.registrar_obra("Minha Obra", URL, lido=2, t=agora + 5)            # releitura mais nova
        self.assertEqual(self.ficha()["lido"], "2")

    def test_sem_duplicata_por_url_ou_nome(self):
        historico.registrar_obra("", URL, encontrado=5)                              # só pelo endereço: nome vem do slug
        historico.registrar_obra("Minha Obra", URL)                                  # nome de verdade completa a mesma ficha
        historico.registrar_obra("minha  obra!", "", baixado=1)                      # mesmo nome sem acento/pontuação
        obras = historico.ler()["obras"]
        self.assertEqual(len(obras), 1)
        self.assertEqual(self.ficha()["nome"], "Minha Obra")
        self.assertEqual(self.ficha()["baixado"], "1")

    def test_ler_tudo_nao_conclui_a_obra(self):
        historico.registrar_obra("Minha Obra", URL, encontrado=3, baixado=3)
        for n in (1, 2, 3):
            historico.registrar_obra("Minha Obra", URL, lido=n, pos={"p": 5, "t": 5, "f": 1})
        self.assertEqual(self.ficha()["situacao"], "andamento")                       # leitura em dia, obra continua em andamento
        self.assertTrue(historico.definir_situacao("Minha Obra", "pausada"))
        self.assertFalse(historico.definir_situacao("Minha Obra", "inventada"))
        self.assertEqual(self.ficha()["situacao"], "pausada")
        historico.registrar_obra("Minha Obra", URL, encontrado=4, descoberta=True)    # nova descoberta não muda a situação
        self.assertEqual(self.ficha()["situacao"], "pausada")

    def test_excluir_obra_da_biblioteca_mantem_historico(self):
        pasta = self.cap(1)
        self.cap(2)
        dados_obra.gravar(self.raiz / "Minha Obra", "Minha Obra", URL + "x-1")
        historico.anotar_capitulo(pasta, baixado=True, lido=True, pos={"p": 2, "t": 8, "f": 0.4})
        acervo.excluir_obra(self.raiz, "Minha Obra")
        acervo.esquecer_versao()
        self.assertEqual(acervo.listar(self.raiz)["obras"], [])
        f = self.ficha()                                                              # a ficha sobrevive, inclusive posição exata
        self.assertEqual((f["baixado"], f["lido"], f["pos"]["p"], f["url"]), ("1", "1", 2, URL))
        self.assertEqual(self.ficha()["id"], historico.ler()["obras"][f["id"]]["id"])

    def test_reinicio_le_do_disco_e_arquivo_antigo_continua_valido(self):
        historico.registrar_obra("Minha Obra", URL, baixado=7)
        bruto = json.loads(historico.ARQUIVO.read_text(encoding="utf-8"))             # o que sobra no disco após fechar o programa
        self.assertEqual(list(bruto["obras"].values())[0]["baixado"], "7")
        historico.ARQUIVO.write_text(json.dumps({"posicoes": {"O/C1": {"p": 1, "n": 2, "f": 0.1, "t": 5}}, "lidos": {}, "estados": {}}), encoding="utf-8")
        d = historico.ler()                                                           # arquivo de antes do recurso
        self.assertEqual((d["obras"], d["posicoes"]["O/C1"]["p"]), ({}, 1))
        self.assertNotIn("obras", historico.resumo())                                 # sincronização com o celular não muda
        self.assertTrue(historico.registrar_obra("Minha Obra", URL))
        self.assertIn("O/C1", historico.ler()["posicoes"])                           # seções antigas preservadas na escrita

    def test_sincronizar_biblioteca_importa_obras_existentes(self):
        pasta = self.cap(1)
        self.cap(2)
        dados_obra.gravar(self.raiz / "Minha Obra", "Minha Obra", URL)
        historico.ARQUIVO.unlink()
        historico.salvar_posicao("Minha Obra/" + pasta.name, 3, 9, 0.2)
        self.assertEqual(historico.sincronizar_biblioteca(self.raiz), 1)
        f = self.ficha()
        self.assertEqual((f["baixado"], f["lido"], f["pos"]["p"], f["url"]), ("2", "1", 3, URL))
        self.assertEqual(historico.sincronizar_biblioteca(self.raiz), 0)              # repetir não duplica nem regrava

    def test_ruins_nao_quebram(self):
        self.assertFalse(historico.registrar_obra("", ""))
        self.assertFalse(historico.anotar_capitulo(self.dir / "nao-existe", baixado=True))
        self.assertFalse(historico.definir_situacao("Nada", "pausada"))


if __name__ == "__main__":
    unittest.main()
