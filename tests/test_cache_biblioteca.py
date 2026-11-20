"""Cache da biblioteca: consultas repetidas não reabrem as imagens, mas qualquer mudança aparece."""

from __future__ import annotations

import builtins
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from baixador.biblioteca import acervo, capitulo, organizacao as org

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40


def envelhecer(*caminhos: Path, segundos: int = 3600) -> None:
    """Datas antigas: só coisa "estável" (não mexida há alguns segundos) entra no cache."""
    t = time.time() - segundos
    for c in caminhos:
        os.utime(c, (t, t))


class Cache(unittest.TestCase):
    def setUp(self) -> None:
        self.raiz = Path(tempfile.mkdtemp(prefix="bib-"))
        self.addCleanup(shutil.rmtree, self.raiz, ignore_errors=True)

    def capitulo(self, obra: str, numero: int, imagens: int = 3, url: str = "") -> Path:
        cap = self.raiz / obra / f"Cap {numero:03d}"
        img = cap / "img"
        img.mkdir(parents=True)
        for k in range(imagens):
            (img / f"{k:03d}_{k}.jpg").write_bytes(JPEG)
        org.gravar_meta(cap, obra, str(numero), "", url or f"https://s.com/manga/{obra}/chapter-{numero}")
        return cap

    def envelhecer_tudo(self) -> None:
        for p in sorted(self.raiz.rglob("*"), key=lambda p: -len(p.parts)):
            envelhecer(p)
        envelhecer(self.raiz)

    def contar_aberturas(self, funcao):
        abertas = []
        original = builtins.open

        def contando(arquivo, modo="r", *a, **k):
            if "b" in modo and str(arquivo).endswith(".jpg"):
                abertas.append(str(arquivo))
            return original(arquivo, modo, *a, **k)

        builtins.open = contando                                   # type: ignore[assignment]
        try:
            resultado = funcao()
        finally:
            builtins.open = original                               # type: ignore[assignment]
        return resultado, len(abertas)

    def test_segunda_consulta_nao_reabre_as_imagens(self) -> None:
        for n in range(1, 6):
            self.capitulo("Obra A", n)
        self.envelhecer_tudo()
        primeira, abertas1 = self.contar_aberturas(lambda: acervo.listar(self.raiz))
        segunda, abertas2 = self.contar_aberturas(lambda: acervo.listar(self.raiz))
        self.assertEqual(abertas1, 15)
        self.assertEqual(abertas2, 0)
        self.assertEqual(len(primeira["obras"][0]["capitulos"]), len(segunda["obras"][0]["capitulos"]))
        _, abertas3 = self.contar_aberturas(lambda: acervo.capitulo_existente(self.raiz, "Obra A", "3", "", ""))
        self.assertEqual(abertas3, 0)

    def test_imagem_nova_ou_apagada_aparece(self) -> None:
        cap = self.capitulo("Obra A", 1, imagens=3)
        self.envelhecer_tudo()
        self.assertEqual(len(capitulo.listar_imagens(cap)), 3)
        (cap / "img" / "009_9.jpg").write_bytes(JPEG)               # chega uma imagem (a pasta img/ muda agora)
        self.assertEqual(len(capitulo.listar_imagens(cap)), 4)
        self.envelhecer_tudo()
        self.assertEqual(len(capitulo.listar_imagens(cap)), 4)
        (cap / "img" / "000_0.jpg").unlink()
        self.assertEqual(len(capitulo.listar_imagens(cap)), 3)

    def test_mudanca_recente_nunca_e_guardada(self) -> None:
        cap = self.capitulo("Obra A", 1, imagens=2)                # acabou de ser criado: datas "de agora"
        self.assertEqual(len(capitulo.listar_imagens(cap)), 2)
        (cap / "img" / "005_5.jpg").write_bytes(JPEG)               # outra mudança no mesmo instante
        self.assertEqual(len(capitulo.listar_imagens(cap)), 3)

    def test_capitulo_novo_e_achado_logo(self) -> None:
        for n in range(1, 4):
            self.capitulo("Obra A", n)
        self.envelhecer_tudo()
        self.assertIsNone(acervo.capitulo_existente(self.raiz, "Obra A", "4", "", "https://s.com/manga/Obra A/chapter-4"))
        self.capitulo("Obra A", 4)
        self.assertIsNotNone(acervo.capitulo_existente(self.raiz, "Obra A", "4", "", "https://s.com/manga/Obra A/chapter-4"))

    def test_meta_devolve_copia_e_acompanha_o_arquivo(self) -> None:
        cap = self.capitulo("Obra A", 1)
        self.envelhecer_tudo()
        a = org.ler_meta(cap)
        a["url"] = "mexido por quem recebeu"
        self.assertNotEqual(org.ler_meta(cap)["url"], "mexido por quem recebeu")
        org.gravar_meta(cap, "Obra A", "1", "", "https://s.com/novo")
        self.assertEqual(org.ler_meta(cap)["url"], "https://s.com/novo")

    def test_resultado_igual_com_e_sem_cache(self) -> None:
        for n in range(1, 4):
            cap = self.capitulo("Obra A", n)
            (cap / "traducao.json").write_text('{"formato":2,"counts":{"ok":2,"revisar":1,"erro":0},"pages":[]}', encoding="utf-8")
        self.envelhecer_tudo()
        com = acervo.listar(self.raiz)
        com2 = acervo.listar(self.raiz)
        from baixador.nucleo import cache_arquivos

        antigo = cache_arquivos.ESTAVEL_S
        cache_arquivos.ESTAVEL_S = 10 ** 9                          # nunca estável = nunca usa cache
        try:
            sem = acervo.listar(self.raiz)
        finally:
            cache_arquivos.ESTAVEL_S = antigo
        for outro in (com2, sem):
            self.assertEqual([(c["rel"], c["imagens"], c["traduzido"], c["revisar"]) for c in com["obras"][0]["capitulos"]],
                             [(c["rel"], c["imagens"], c["traduzido"], c["revisar"]) for c in outro["obras"][0]["capitulos"]])


if __name__ == "__main__":
    unittest.main()
