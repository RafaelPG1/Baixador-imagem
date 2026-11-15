"""Testes do lado Python da tradução: arquivos antigos, configuração, dados do leitor (usuário x administrador),
estado da biblioteca e exportação. Rodar: python -m unittest discover -s tests -v"""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from baixador.biblioteca import acervo, exportar
from baixador.biblioteca.capitulo import dados_do_capitulo
from baixador.traducao import config, legado

FIXTURES = Path(__file__).parent / "fixtures"
EXEMPLO = json.loads((FIXTURES / "traducao_exemplo.json").read_text(encoding="utf-8"))

# campos que só existem na leitura da biblioteca (verificação)
CAMPOS_ADMIN = {"original", "estado", "status", "conferencia", "baloes", "verificacao", "erro", "regiao", "ocr", "motivo", "glossario"}


def chaves(obj, acumulado=None):
    acumulado = set() if acumulado is None else acumulado
    if isinstance(obj, dict):
        for k, v in obj.items():
            acumulado.add(k)
            chaves(v, acumulado)
    elif isinstance(obj, list):
        for v in obj:
            chaves(v, acumulado)
    return acumulado


class Biblioteca(unittest.TestCase):
    def setUp(self) -> None:
        self.raiz = Path(tempfile.mkdtemp(prefix="obras-"))
        self.addCleanup(shutil.rmtree, self.raiz, ignore_errors=True)
        self.cap = self.raiz / "Obra Teste" / "Capitulo 001"
        (self.cap / "img").mkdir(parents=True)
        shutil.copy(FIXTURES / "pagina_baloes.png", self.cap / "img" / "001_a.png")

    def traduzido(self, dados=None) -> None:
        (self.cap / "traducao.json").write_text(json.dumps(dados or EXEMPLO), encoding="utf-8")
        (self.cap / "traducao" / "limpeza").mkdir(parents=True, exist_ok=True)
        patch = (dados or EXEMPLO)["pages"][0]["patch"]
        if "/" not in patch:
            (self.cap / "traducao" / "limpeza" / patch).write_bytes(b"\x89PNG\r\n\x1a\n")


class TestLegado(Biblioteca):
    def test_remove_so_o_antigo_e_preserva_o_novo(self) -> None:
        obra = self.raiz / "Obra Teste"
        (self.cap / "traducao.json").write_text(json.dumps({"versao": 1, "imagens": {}}), encoding="utf-8")
        for nome in ("traducao.parcial.json", "traducao.anterior.json", "traducao.aviso.json"):
            (self.cap / nome).write_text("{}", encoding="utf-8")
        (obra / "glossario.json").write_text(json.dumps({"manter": ["Naruto"], "auto": [], "termos": {"a": "b"}}), encoding="utf-8")
        (obra / "memoria_traducao.json").write_text("{}", encoding="utf-8")
        (obra / "memoria_termos.json").write_text("{}", encoding="utf-8")
        (obra / "obra.json").write_text("{}", encoding="utf-8")
        r = legado.limpar(self.raiz)
        self.assertEqual(len(r["apagados"]), 7)
        self.assertEqual(r["erros"], [])
        self.assertEqual(sorted(p.name for p in self.cap.iterdir()), ["img"])
        self.assertTrue((obra / "obra.json").exists())
        self.assertTrue((self.cap / "img" / "001_a.png").exists())

    def test_formato_novo_e_glossario_novo_sao_preservados(self) -> None:
        self.traduzido()
        glossario = self.raiz / "Obra Teste" / "glossario.json"
        glossario.write_text(json.dumps({"PROTECT": "proteger"}), encoding="utf-8")
        r = legado.limpar(self.raiz)
        self.assertEqual(r["apagados"], [])
        self.assertTrue((self.cap / "traducao.json").exists())
        self.assertTrue(glossario.exists())

    def test_raiz_inexistente_nao_quebra(self) -> None:
        self.assertEqual(legado.limpar(self.raiz / "nao-existe"), {"apagados": [], "erros": []})


class TestConfig(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.original = config.ARQUIVO
        config.ARQUIVO = self.tmp / "traducao.json"
        self.addCleanup(setattr, config, "ARQUIVO", self.original)

    def test_padrao_e_valores_antigos_voltam_ao_padrao(self) -> None:
        self.assertEqual(config.ler(), {"motor": "local", "modelo": "translategemma:4b"})
        config.ARQUIVO.write_text(json.dumps({"motor": "openrouter", "modelo": "gemma4:e4b"}), encoding="utf-8")
        self.assertEqual(config.ler(), {"motor": "local", "modelo": "translategemma:4b"})
        config.ARQUIVO.write_text("{quebrado", encoding="utf-8")
        self.assertEqual(config.ler()["motor"], "local")

    def test_so_os_quatro_motores_do_tradutor(self) -> None:
        self.assertEqual(set(config.MOTORES), {"local", "deepl", "gemini", "mymemory"})
        for motor in config.MOTORES:
            self.assertEqual(config.salvar(motor)["motor"], motor)
        for ruim in ("argos", "hibrido", "hy", "openrouter", ""):
            with self.assertRaises(ValueError):
                config.salvar(ruim)
        with self.assertRaises(ValueError):
            config.salvar(None, "gemma4:e4b")
        self.assertEqual(config.salvar(None, "translategemma:12b")["modelo"], "translategemma:12b")


class TestLeitura(Biblioteca):
    def test_sem_traducao(self) -> None:
        d = dados_do_capitulo(self.raiz, "Obra Teste/Capitulo 001")
        self.assertFalse(d["traduzido"])
        self.assertEqual(d["imagens"][0]["falas"], [])
        self.assertIsNone(d["imagens"][0]["patch"])

    def test_formato_antigo_nao_e_lido(self) -> None:
        (self.cap / "traducao.json").write_text(json.dumps({"versao": 1, "imagens": {"001_a.png": {"w": 10, "h": 10, "blocos": []}}}), encoding="utf-8")
        self.assertFalse(dados_do_capitulo(self.raiz, "Obra Teste/Capitulo 001")["traduzido"])

    def test_usuario_so_recebe_o_traduzido(self) -> None:
        self.traduzido()
        d = dados_do_capitulo(self.raiz, "Obra Teste/Capitulo 001")
        self.assertFalse(d["admin"])
        im = d["imagens"][0]
        self.assertEqual(im["medidas"], [800, 1100])
        self.assertEqual(len(im["falas"]), 3)
        self.assertEqual(im["patch"], EXEMPLO["pages"][0]["patch"])
        self.assertEqual(d["subLimpeza"], "traducao/limpeza/")
        self.assertEqual(d["sub"], "img/")
        textos = " ".join(f["texto"] for f in im["falas"])
        self.assertIn("NÃO ACREDITO", textos)
        vazamentos = chaves(d) & CAMPOS_ADMIN
        self.assertEqual(vazamentos, set(), f"dados de verificação vazaram para o usuário: {vazamentos}")
        self.assertNotIn("BELIEVE", json.dumps(d, ensure_ascii=False))           # nenhum texto original

    def test_administrador_recebe_a_conferencia(self) -> None:
        self.traduzido()
        d = dados_do_capitulo(self.raiz, "Obra Teste/Capitulo 001", admin=True)
        self.assertTrue(d["admin"])
        im = d["imagens"][0]
        self.assertEqual(len(im["falas"]), 3)                                     # o que é desenhado é igual nos dois modos
        self.assertEqual(len(im["conferencia"]), 3)
        self.assertEqual(len(im["baloes"]), 3)
        c = next(f for f in im["conferencia"] if "BELIEVE" in f["original"])
        self.assertEqual(c["estado"], "ok")
        self.assertEqual(c["ocr"]["motor"], "Tesseract")
        self.assertEqual(c["modo"], "balao")
        self.assertEqual(len(c["regiao"]), 4)
        self.assertIn("translategemma", d["verificacao"]["provedor"])
        self.assertEqual(d["verificacao"]["contagens"]["ok"], 3)
        sem_admin = dados_do_capitulo(self.raiz, "Obra Teste/Capitulo 001")["imagens"][0]["falas"]
        self.assertEqual(im["falas"], sem_admin)

    def test_json_adulterado_e_saneado(self) -> None:
        d = json.loads(json.dumps(EXEMPLO))
        u = d["pages"][0]["units"]
        u[0]["render"]["ink"] = "url(javascript:alert(1))"
        u[0]["render"]["fontMax"] = float("inf") if False else 1e9
        u[1]["render"]["box"] = [0, 0, -5, 10]
        u[2]["render"]["box"] = [10, 10, 1e12, 10]
        u[2]["translation"] = "x" * 5000
        d["pages"][0]["patch"] = "../../../etc/passwd"
        self.traduzido(d)
        im = dados_do_capitulo(self.raiz, "Obra Teste/Capitulo 001")["imagens"][0]
        self.assertIsNone(im["patch"])
        self.assertEqual(len(im["falas"]), 1)                                     # só a fala com caixa válida
        f = im["falas"][0]
        self.assertEqual(f["tinta"], "#111111")
        self.assertLessEqual(f["fonteMax"], 40.0)
        self.assertLessEqual(len(f["texto"]), 1200)

    def test_balao_so_com_tooltip_nao_vai_para_o_usuario(self) -> None:
        d = json.loads(json.dumps(EXEMPLO))
        d["pages"][0]["units"][0]["render"]["mode"] = "tooltip"
        d["pages"][0]["units"][1]["status"] = "erro"
        d["pages"][0]["units"][1]["render"]["flag"] = "erro"
        self.traduzido(d)
        user = dados_do_capitulo(self.raiz, "Obra Teste/Capitulo 001")["imagens"][0]
        adm = dados_do_capitulo(self.raiz, "Obra Teste/Capitulo 001", admin=True)["imagens"][0]
        self.assertEqual(len(user["falas"]), 2)
        self.assertEqual(len(adm["conferencia"]), 3)                              # o administrador vê todas, inclusive as marcadas


class TestAcervo(Biblioteca):
    def test_estado_do_capitulo(self) -> None:
        cap = lambda: acervo.listar(self.raiz)["obras"][0]["capitulos"][0]  # noqa: E731
        self.assertFalse(cap()["traduzido"])
        self.traduzido()
        c = cap()
        self.assertTrue(c["traduzido"])
        self.assertEqual((c["incompleta"], c["revisar"]), (0, 0))
        d = json.loads(json.dumps(EXEMPLO))
        d["counts"] = {"ok": 1, "revisar": 1, "erro": 1}
        self.traduzido(d)
        acervo.esquecer_versao()
        c = cap()
        self.assertEqual((c["incompleta"], c["revisar"]), (1, 1))

    def test_assinatura_muda_quando_a_traducao_chega(self) -> None:
        antes = acervo.versao(self.raiz, validade=0)
        self.traduzido()
        self.assertNotEqual(antes, acervo.versao(self.raiz, validade=0))

    def test_resultado_antigo_nao_conta_como_traduzido(self) -> None:
        (self.cap / "traducao.json").write_text(json.dumps({"versao": 1, "imagens": {}}), encoding="utf-8")
        self.assertFalse(acervo.listar(self.raiz)["obras"][0]["capitulos"][0]["traduzido"])


class TestExportacao(Biblioteca):
    def gerar(self) -> zipfile.ZipFile:
        caps = [c for o in acervo.listar(self.raiz)["obras"] for c in o["capitulos"]]
        buf = io.BytesIO()
        exportar.gerar_zip(self.raiz, caps, buf)
        return zipfile.ZipFile(io.BytesIO(buf.getvalue()))

    def test_zip_leva_limpeza_e_so_a_leitura_do_usuario(self) -> None:
        self.traduzido()
        z = self.gerar()
        nomes = z.namelist()
        patch = EXEMPLO["pages"][0]["patch"]
        self.assertIn(f"c0/limpeza/{patch}", nomes)
        self.assertIn("c0/img/001_a.png", nomes)
        cap = json.loads(z.read("c0/capitulo.json"))
        self.assertEqual(cap["subLimpeza"], "limpeza/")
        self.assertEqual(chaves(cap) & CAMPOS_ADMIN, set())
        self.assertEqual(len(cap["imagens"][0]["falas"]), 3)
        self.assertEqual(json.loads(z.read("baixador-export.json"))["formato"], 1)

    def test_png_ausente_exporta_a_pagina_sem_traducao(self) -> None:
        self.traduzido()
        for f in (self.cap / "traducao" / "limpeza").iterdir():
            f.unlink()
        cap = json.loads(self.gerar().read("c0/capitulo.json"))
        self.assertIsNone(cap["imagens"][0]["patch"])
        self.assertEqual(cap["imagens"][0]["falas"], [])


if __name__ == "__main__":
    unittest.main()
