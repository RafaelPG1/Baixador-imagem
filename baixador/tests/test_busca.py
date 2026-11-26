"""Pesquisa FTS5: incremental, filtro por obra, acentos, sem alterar os traducao.json."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from baixador.biblioteca import busca
from baixador.tests.test_edicoes import traduzido
from baixador.traducao import edicoes


def sha(p):
    return hashlib.sha1(Path(p).read_bytes()).hexdigest()


class Busca(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.raiz = Path(t.name) / "lib"
        p = mock.patch.object(busca, "ARQUIVO", Path(t.name) / "busca.db")
        p.start()
        self.addCleanup(p.stop)

    def idx(self):
        return busca.sincronizar(self.raiz, busca.todos(self.raiz))

    def test_incremental_filtro_acento_e_remocao(self):
        a = traduzido(self.raiz, "Obra A", 1, ["ok", "ok"])
        traduzido(self.raiz, "Obra B", 1, ["ok"])
        antes = sha(a / "traducao.json")
        self.assertEqual(self.idx(), {"novos": 2, "alterados": 0, "removidos": 0})
        self.assertEqual(self.idx(), {"novos": 0, "alterados": 0, "removidos": 0})            # nada mudou: nada reindexado
        r = busca.pesquisar("oi 2")
        self.assertEqual([(x["rel"], x["pagina"], x["id"]) for x in r], [("Obra A/Capitulo 1", 1, "p001-b2")])
        self.assertEqual(len(busca.pesquisar("oi")), 3)
        self.assertEqual(len(busca.pesquisar("oi", obra="Obra B")), 1)
        edicoes.aplicar(a, {"p001-b1": "Coração partido"})                                    # edição → só esse capítulo é reindexado
        self.assertEqual(self.idx(), {"novos": 0, "alterados": 1, "removidos": 0})
        self.assertEqual(len(busca.pesquisar("coracao")), 1)                                  # sem acento acha com acento
        self.assertEqual(len(busca.pesquisar("cora")), 1)                                     # prefixo
        import shutil
        shutil.rmtree(self.raiz / "Obra B")
        from baixador.biblioteca import acervo
        acervo.esquecer_versao()
        self.assertEqual(self.idx()["removidos"], 1)
        self.assertEqual(busca.pesquisar("oi", obra="Obra B"), [])
        self.assertNotEqual(antes, sha(a / "traducao.json"))                                  # (a edição mudou, a busca em si nunca grava)

    def test_consulta_maliciosa_nao_quebra(self):
        traduzido(self.raiz, "Obra A", 1, ["ok"])
        self.idx()
        for q in ('"', "a OR b", "oi AND", "* ^ (", "NEAR(", "x" * 500, ""):
            busca.pesquisar(q)


if __name__ == "__main__":
    unittest.main()
