"""Compactação de imagens para o celular: cache, fallback e originais intactos (a conversão real usa `sharp`; aqui um conversor Pillow faz o papel)."""
import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image

from baixador.biblioteca import acervo, compactar, exportar
from baixador.tests.test_edicoes import traduzido


def com_pillow(itens):
    ok = []
    for x in itens:
        Path(x["para"]).parent.mkdir(parents=True, exist_ok=True)
        im = Image.open(x["de"])
        im.thumbnail((compactar.LARGURA, 99999))
        im.save(x["para"], "WEBP", quality=compactar.QUALIDADE)
        ok.append(x["para"])
    return {"ok": ok, "falhas": []}


class Compactar(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.raiz = Path(t.name) / "lib"
        p = mock.patch.object(compactar, "CACHE", Path(t.name) / "cache")
        p.start()
        self.addCleanup(p.stop)
        self.pasta = traduzido(self.raiz, "Obra A", 1, ["ok"])
        Image.new("RGB", (2160, 3000), "white").save(self.pasta / "img" / "001.png")           # imagem larga: deve encolher
        acervo.esquecer_versao()
        self.caps = [c for o in acervo.listar(self.raiz)["obras"] for c in o["capitulos"]]

    def zip(self, **kw):
        buf = io.BytesIO()
        exportar.gerar_zip(self.raiz, self.caps, buf, **kw)
        return zipfile.ZipFile(io.BytesIO(buf.getvalue()))

    def test_compacto_gera_webp_menor_sem_tocar_no_original(self):
        orig = self.pasta / "img" / "001.png"
        antes = hashlib.sha1(orig.read_bytes()).hexdigest()
        with mock.patch.object(compactar, "_node_sharp", com_pillow):
            z = self.zip(compacto=True)
        nomes = z.namelist()
        self.assertIn("c0/img/001.webp", nomes)
        self.assertNotIn("c0/img/001.png", nomes)
        self.assertIn('"001.webp"', z.read("c0/capitulo.json").decode())
        w, h = Image.open(io.BytesIO(z.read("c0/img/001.webp"))).size
        self.assertEqual((w, round(h / w, 3)), (1080, round(3000 / 2160, 3)))                  # largura 1080, mesma proporção
        self.assertEqual(antes, hashlib.sha1(orig.read_bytes()).hexdigest())                    # original intacto
        self.assertLess(z.getinfo("c0/img/001.webp").file_size, orig.stat().st_size)
        self.assertIn("c0/img/001.png", self.zip().namelist())                                  # padrão continua sendo o original

    def test_cache_so_refaz_se_o_original_mudou_e_falha_cai_no_original(self):
        chamadas = []

        def conv(itens):
            chamadas.append(len(itens))
            return com_pillow(itens)

        arqs = ["001.png"]
        compactar.preparar("Obra A/Capitulo 1", self.pasta / "img", arqs, conv)
        compactar.preparar("Obra A/Capitulo 1", self.pasta / "img", arqs, conv)
        self.assertEqual(chamadas, [1])                                                         # segunda vez: cache
        Image.new("RGB", (1500, 2000), "black").save(self.pasta / "img" / "001.png")
        compactar.preparar("Obra A/Capitulo 1", self.pasta / "img", arqs, conv)
        self.assertEqual(chamadas, [1, 1])                                                      # original mudou: refaz
        falha = compactar.preparar("Outro/1", self.pasta / "img", arqs, lambda i: {"ok": [], "falhas": [{"erro": "x"}]})
        self.assertEqual(falha, {})                                                             # sem conversão: nada no mapa → exporta o original


if __name__ == "__main__":
    unittest.main()
