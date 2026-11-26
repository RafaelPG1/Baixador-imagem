import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from baixador.biblioteca import acervo, armazenamento, lixeira
from baixador.tests.test_web_ia_lotes import criar


def _obra(raiz: Path, nome="Obra A", caps=(1, 2, 3)):
    rels = [criar(raiz, nome, n, f"{n:08x}", preparado=False) for n in caps]
    (raiz / nome / "obra.json").write_text(json.dumps({"nome": nome}), encoding="utf-8")
    (raiz / nome / "capa.jpg").write_bytes(b"capa")
    acervo.esquecer_versao()
    return rels


def _caps(raiz):
    return sorted(c["rel"] for o in acervo.listar(raiz)["obras"] for c in o["capitulos"])


class Lixeira(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.raiz = Path(self._t.name)
        self.addCleanup(self._t.cleanup)

    def test_excluir_capitulo_vai_para_lixeira_e_volta(self):
        rels = _obra(self.raiz)
        (self.raiz / rels[0] / "traducao.json").write_text("{}", encoding="utf-8")
        r = acervo.excluir_capitulos(self.raiz, "Obra A", [rels[0]])
        self.assertEqual((r["apagados"], r["erros"]), ([rels[0]], []))
        self.assertEqual(_caps(self.raiz), rels[1:])
        itens = lixeira.listar(self.raiz)
        self.assertEqual((len(itens), itens[0]["dias_restantes"], itens[0]["capitulos"]), (1, 14, [rels[0]]))
        out = lixeira.restaurar(self.raiz, itens[0]["id"])
        acervo.esquecer_versao()
        self.assertEqual((out["restaurados"], out["conflitos"]), ([rels[0]], []))
        self.assertEqual(_caps(self.raiz), rels)
        self.assertTrue((self.raiz / rels[0] / "traducao.json").is_file(), "traduções voltam junto")
        self.assertEqual(lixeira.listar(self.raiz), [])

    def test_excluir_obra_guarda_obra_json_e_capa_e_restaura_inteira(self):
        rels = _obra(self.raiz)
        acervo.excluir_obra(self.raiz, "Obra A")
        self.assertFalse((self.raiz / "Obra A").exists())
        self.assertEqual(_caps(self.raiz), [])
        (item,) = lixeira.listar(self.raiz)
        self.assertEqual((item["tipo"], sorted(item["extras"])), ("obra", ["Obra A/capa.jpg", "Obra A/obra.json"]))
        lixeira.restaurar(self.raiz, item["id"])
        acervo.esquecer_versao()
        self.assertEqual(_caps(self.raiz), rels)
        self.assertEqual((self.raiz / "Obra A" / "capa.jpg").read_bytes(), b"capa")
        self.assertTrue((self.raiz / "Obra A" / "obra.json").is_file())

    def test_restaurar_nao_sobrescreve_existente(self):
        rels = _obra(self.raiz)
        acervo.excluir_capitulos(self.raiz, "Obra A", [rels[0]])
        criar(self.raiz, "Obra A", 1, "ffffffff", preparado=False)                      # outro capítulo ocupa o lugar
        (self.raiz / rels[0] / "img" / "marca.txt").write_text("novo")
        (item,) = lixeira.listar(self.raiz)
        out = lixeira.restaurar(self.raiz, item["id"])
        self.assertEqual((out["restaurados"], out["conflitos"]), ([], [rels[0]]))
        self.assertTrue((self.raiz / rels[0] / "img" / "marca.txt").is_file(), "o que existia continua intacto")
        self.assertEqual(len(lixeira.listar(self.raiz)), 1, "o conflito continua na lixeira")

    def test_limpeza_automatica_e_manual_e_ids_invalidos(self):
        rels = _obra(self.raiz)
        acervo.excluir_capitulos(self.raiz, "Obra A", [rels[0]])
        acervo.excluir_capitulos(self.raiz, "Obra A", [rels[1]])
        a, b = lixeira.listar(self.raiz)
        n = lixeira.limpar_vencidos(self.raiz, agora=time.time() + 13 * 86400)
        self.assertEqual(n, 0)
        n = lixeira.limpar_vencidos(self.raiz, agora=time.time() + 15 * 86400)
        self.assertEqual((n, lixeira.listar(self.raiz)), (2, []))
        acervo.excluir_capitulos(self.raiz, "Obra A", [rels[2]])
        (c,) = lixeira.listar(self.raiz)
        for ruim in ("../x", "", ".lixeira", "nao-existe"):
            with self.assertRaises(Exception):
                lixeira.apagar(self.raiz, ruim)
        lixeira.apagar(self.raiz, c["id"])
        self.assertEqual(lixeira.listar(self.raiz), [])

    def test_lixeira_nao_aparece_como_obra_nem_conta_na_biblioteca(self):
        rels = _obra(self.raiz)
        acervo.excluir_capitulos(self.raiz, "Obra A", [rels[0]])
        self.assertEqual(_caps(self.raiz), rels[1:])
        self.assertTrue(all(o["nome"] != ".lixeira" for o in acervo.listar(self.raiz)["obras"]))

    def test_falha_no_meio_desfaz_tudo(self):
        rels = _obra(self.raiz)
        from unittest import mock
        real = lixeira.shutil.move
        chamadas = []

        def falha(a, b):
            chamadas.append(a)
            if len(chamadas) == 2 and "Capitulo" in str(a) and "dados" not in str(a):
                raise OSError("disco")
            return real(a, b)
        with mock.patch.object(lixeira.shutil, "move", side_effect=falha):
            r = acervo.excluir_capitulos(self.raiz, "Obra A", rels[:2])
        self.assertTrue(r["erros"])
        self.assertEqual(_caps(self.raiz), rels, "nada ficou pela metade")
        self.assertEqual(lixeira.listar(self.raiz), [])


class Espaco(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.raiz = Path(self._t.name)
        self.addCleanup(self._t.cleanup)

    def test_tamanho_por_obra_com_cache_que_acompanha_mudancas(self):
        _obra(self.raiz, "Obra A", (1,))
        _obra(self.raiz, "Obra B", (1, 2))
        t = armazenamento.tamanhos(self.raiz)
        self.assertGreater(t["obras"]["Obra B"], t["obras"]["Obra A"])
        self.assertIs(armazenamento.tamanhos(self.raiz), t)
        _obra(self.raiz, "Obra A", (1, 2, 3, 4))
        self.assertGreater(armazenamento.tamanhos(self.raiz)["obras"]["Obra A"], t["obras"]["Obra A"])

    def test_orfaos_so_o_que_e_resto_seguro(self):
        rels = _obra(self.raiz, "Obra A", (1, 2, 3, 4))
        concluido, retomavel, preparado, em_uso = (self.raiz / r for r in rels)
        for p in (concluido, retomavel, preparado, em_uso):
            (p / "traducao.nova" / "etapa4a").mkdir(parents=True)
            (p / "traducao.nova" / "etapa4a" / "x.json").write_text("{}")
        # traducao.json válido (formato 2) só no "concluido" e no "em_uso"
        for p in (concluido, em_uso):
            (p / "traducao.json").write_text(json.dumps({"formato": 2, "paginas": []}))
        (preparado / "traducao.nova" / "web").mkdir()
        (preparado / "traducao.nova" / "web" / "textos.json").write_text("{}")
        velho = self.raiz / "Obra A" / "lixo.json.tmp"
        velho.write_text("x"); os.utime(velho, (1, 1))
        recente = self.raiz / "Obra A" / "agora.json.tmp"
        recente.write_text("x")
        acervo.esquecer_versao()
        achados = {a["caminho"] for a in armazenamento.orfaos(self.raiz, {rels[3]})}
        self.assertIn("Obra A/Capitulo 1/traducao.nova", achados, "capítulo concluído: o que sobrou da execução é resto")
        self.assertNotIn("Obra A/Capitulo 2/traducao.nova", achados, "trabalho retomável não é resto")
        self.assertNotIn("Obra A/Capitulo 3/traducao.nova", achados, "preparação da IA web não é resto")
        self.assertNotIn("Obra A/Capitulo 4/traducao.nova", achados, "capítulo em uso não é tocado")
        self.assertIn("Obra A/lixo.json.tmp", achados)
        self.assertNotIn("Obra A/agora.json.tmp", achados, ".tmp recente pode ser gravação em andamento")
        antes = {p.relative_to(self.raiz).as_posix() for p in self.raiz.rglob("*") if p.is_file()}
        r = armazenamento.limpar_orfaos(self.raiz, {rels[3]})
        depois = {p.relative_to(self.raiz).as_posix() for p in self.raiz.rglob("*") if p.is_file()}
        self.assertTrue(all("/img/" not in p for p in antes - depois), "imagens nunca são removidas")
        self.assertEqual(len(armazenamento.orfaos(self.raiz, {rels[3]})), 0)
        self.assertTrue((retomavel / "traducao.nova" / "etapa4a" / "x.json").is_file())
        self.assertTrue((preparado / "traducao.nova" / "web" / "textos.json").is_file())
        self.assertTrue((em_uso / "traducao.nova" / "etapa4a" / "x.json").is_file())


if __name__ == "__main__":
    unittest.main()
