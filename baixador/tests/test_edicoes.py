"""Glossário por obra, só pendentes, revisão por IA e edição de falas."""
import json
import tempfile
import unittest
from pathlib import Path

from baixador.biblioteca import acervo
from baixador.nucleo.erros import ErroBaixador
from baixador.tests.test_web_ia_lotes import _png, criar
from baixador.traducao import edicoes, web_ia


def traduzido(raiz: Path, obra: str, numero: int, status):
    pasta = raiz / obra / f"Capitulo {numero}"
    (pasta / "img").mkdir(parents=True, exist_ok=True)
    (pasta / "img" / "001.png").write_bytes(_png())
    unidades = [{"id": f"p001-b{i}", "source": f"Hello {i}", "translation": (None if s == "erro" else f"Oi {i}"), "status": s} for i, s in enumerate(status, 1)]
    cont = {}
    for s in status:
        cont[s] = cont.get(s, 0) + 1
    (pasta / "traducao.json").write_text(json.dumps({"formato": 2, "counts": cont, "pages": [{"file": "001.png", "number": 1, "width": 400, "height": 600, "units": unidades}]}), encoding="utf-8")
    acervo.esquecer_versao()
    return pasta


class Edicoes(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.raiz = Path(self._t.name)
        self.addCleanup(self._t.cleanup)

    def test_glossario_por_obra_e_na_introducao(self):
        rel = criar(self.raiz, "Obra A", 1, "aaaaaaa1", n=3)
        criar(self.raiz, "Obra B", 1, "bbbbbbb1", n=3)
        edicoes.gravar_glossario(self.raiz, "Obra A", {"Sensei": "Mestre", " ": "x", "Vazio": ""})
        self.assertEqual(edicoes.ler_glossario(self.raiz, "Obra A"), {"Sensei": "Mestre"})
        self.assertEqual(edicoes.ler_glossario(self.raiz, "Obra B"), {})
        a = web_ia.exportar(self.raiz, "Obra A", [rel])[0]["conteudo"]
        b = web_ia.exportar(self.raiz, "Obra B", ["Obra B/Capitulo 1"])[0]["conteudo"]
        self.assertIn("Sensei = Mestre", a)
        self.assertNotIn("Glossário", b)
        self.assertLess(a.index("Sensei = Mestre"), a.index("[aaaaaaa1:"))
        with self.assertRaises(ErroBaixador):
            edicoes.gravar_glossario(self.raiz, "Obra A", {"manter": "x"})
        edicoes.gravar_glossario(self.raiz, "Obra A", {})
        self.assertFalse((self.raiz / "Obra A" / "glossario.json").exists())

    def test_somente_pendentes(self):
        rel = criar(self.raiz, "Obra A", 1, "aaaaaaa1", n=4)
        a = web_ia.analisar(self.raiz, ["[aaaaaaa1:p001-b1] PT 1\n[aaaaaaa1:p002-b1] PT 2"])
        web_ia.gravar(a)
        txt = web_ia.exportar(self.raiz, "Obra A", [rel], introducao=False, somente_pendentes=True)[0]["conteudo"]
        self.assertNotIn("p001-b1", txt)
        self.assertNotIn("p002-b1", txt)
        self.assertIn("p003-b1", txt)
        self.assertIn("p001-b1", web_ia.exportar(self.raiz, "Obra A", [rel], introducao=False)[0]["conteudo"])

    def test_revisao_exporta_so_marcadas_e_importa_so_marcadas(self):
        pasta = traduzido(self.raiz, "Obra A", 1, ["ok", "revisar", "erro", "ok"])
        arq = web_ia.exportar_revisao(self.raiz, "Obra A")
        self.assertEqual(arq["textos"], 2)
        self.assertIn("Hello 2 ::: Oi 2", arq["conteudo"])
        self.assertNotIn("Hello 1", arq["conteudo"].split("começam na próxima linha):")[1])
        cod = web_ia._codigo_rev("Obra A/Capitulo 1")
        resp = f"[{cod}:p001-b2] Olá 2\n[{cod}:p001-b3] Olá 3\n[{cod}:p001-b1] INTRUSA\n[{cod}:p001-b4] INTRUSA"
        seco = web_ia.importar_revisao(self.raiz, "Obra A", [resp], gravar=False)
        self.assertEqual((seco["alteradas"], len(seco["ignoradas"])), (2, 2))
        self.assertIn("Oi 2", (pasta / "traducao.json").read_text(encoding="utf-8"))   # sem gravar: nada muda
        r = web_ia.importar_revisao(self.raiz, "Obra A", [resp], gravar=True)
        self.assertEqual(r["alteradas"], 2)
        doc = json.loads((pasta / "traducao.json").read_text(encoding="utf-8"))
        u = {x["id"]: x for x in doc["pages"][0]["units"]}
        self.assertEqual((u["p001-b2"]["translation"], u["p001-b2"]["status"]), ("Olá 2", "ok"))
        self.assertEqual(u["p001-b1"]["translation"], "Oi 1")          # não marcada: intocada
        self.assertEqual(u["p001-b4"]["translation"], "Oi 4")
        self.assertEqual(doc["counts"], {"ok": 4})
        self.assertEqual([x["id"] for x in doc["pages"][0]["units"]], ["p001-b1", "p001-b2", "p001-b3", "p001-b4"])   # ids e posições
        with self.assertRaises(ValueError):
            web_ia.exportar_revisao(self.raiz, "Obra A")                # nada mais a revisar

    def test_edicao_persiste_em_edicoes_json_e_traducao_json(self):
        pasta = traduzido(self.raiz, "Obra A", 1, ["ok", "ok"])
        r = edicoes.aplicar(pasta, {"p001-b1": "  Novo   texto ", "zzz": "x", "p001-b2": ""})
        self.assertEqual(r["alteradas"], ["p001-b1"])
        self.assertEqual(len(r["ignoradas"]), 2)
        self.assertEqual(json.loads((pasta / "edicoes.json").read_text(encoding="utf-8")), {"p001-b1": "Novo texto"})
        u = json.loads((pasta / "traducao.json").read_text(encoding="utf-8"))["pages"][0]["units"][0]
        self.assertEqual((u["translation"], u["editada"]), ("Novo texto", True))
        self.assertEqual(edicoes.aplicar(pasta, {"p001-b1": "Novo texto"})["alteradas"], [])


if __name__ == "__main__":
    unittest.main()
