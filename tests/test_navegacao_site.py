"""Atualização/navegação entre capítulos com o navegador de verdade contra um site local falso (veja sitefalso.py).

Confere que o programa: usa a lista de capítulos do site, não avança para capítulo inexistente, não pula capítulo, não se engana
com o título da aba atrasado e conta só o que baixou. Precisa de um navegador (Edge, Chrome ou o Chromium do Playwright);
sem ele os testes são ignorados. Rodam sem janela (headless).
Rodar: python -m unittest tests.test_navegacao_site -v"""

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict

from baixador.nucleo import seguranca
from baixador.navegador import captura
from baixador.navegador.captura import Capturador
from baixador.navegador.manual import SessaoManual
from tests.sitefalso import Site


def _sem_janela(timeout: float, **kw: Any) -> Capturador:
    return Capturador(timeout, **{**kw, "mostrar": False})


class Navegacao(unittest.TestCase):
    def setUp(self) -> None:
        # o site de teste é local (127.0.0.1): libera só durante o teste
        original = (seguranca.verificar_host_publico, captura._host_liberado)
        seguranca.verificar_host_publico = lambda host: None                      # type: ignore[assignment]
        captura._host_liberado = lambda host: True                                # type: ignore[assignment]
        self.addCleanup(lambda: (setattr(seguranca, "verificar_host_publico", original[0]), setattr(captura, "_host_liberado", original[1])))
        self.base = Path(tempfile.mkdtemp(prefix="lib-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.sites: list = []
        self.addCleanup(lambda: [s.parar() for s in self.sites])

    def site(self, **kw: Any) -> Site:
        s = Site(**kw)
        self.sites.append(s)
        return s

    def atualizar(self, site: Site, inicio: int, pular: bool = True, limite_s: float = 150.0) -> Dict[str, Any]:
        sessao = SessaoManual(fabrica=_sem_janela)
        linhas: list = []
        registrar = sessao._registrar
        sessao._registrar = lambda m: (linhas.append(m), registrar(m))            # type: ignore[assignment]
        sessao.automatico(
            site.url(inicio), str(self.base), navegador="auto", perfil="temporario", bloquear_abas=True, espera=10,
            organizar={"obra": "Obra X", "numero": "", "titulo": ""}, continuar=True, modo_busca="rapido", pular_primeiro=pular,
        )
        t0 = time.monotonic()
        while time.monotonic() - t0 < limite_s:
            with sessao._lock:
                ativo, estado = sessao.automatico_ativo, sessao.estado
            if not ativo and estado in ("aguardando", "fechado", "erro", "ocioso"):
                break
            time.sleep(0.25)
        aviso = sessao.aviso or ""
        estado_final = sessao.estado
        sessao.encerrar()
        if estado_final == "erro" and any("navegador" in m.lower() and "não consegui" in m.lower() for m in linhas):
            self.skipTest("nenhum navegador disponível para o teste")
        return {"aviso": aviso, "linhas": linhas, "pastas": sorted(p.name for p in self.base.glob("*/*") if p.is_dir())}

    # ------------------------------------------------------------------------------------------------------------------------

    def test_atualiza_ate_o_ultimo_capitulo_e_termina_sem_erro(self) -> None:
        site = self.site(ultimo=55)                       # o botão Next não existe no último capítulo
        r = self.atualizar(site, 53)
        self.assertEqual(r["pastas"], ["Cap 054", "Cap 055"])
        self.assertIn("Já está atualizado: o último capítulo do site é o 55", r["aviso"])
        self.assertIn("2 capítulo(s) baixado(s)", r["aviso"])

    def test_botao_next_quebrado_no_ultimo_capitulo_nao_e_seguido(self) -> None:
        site = self.site(ultimo=55, com_proximo_no_ultimo=True)     # o Next do 55 leva ao 56, que dá 404
        r = self.atualizar(site, 53)
        self.assertEqual(r["pastas"], ["Cap 054", "Cap 055"])
        self.assertIn("Já está atualizado", r["aviso"])
        self.assertFalse([p for p in site.paginas_pedidas() if p.endswith("chapter-56")], "nem chegou a abrir o capítulo 56")

    def test_capitulo_56_que_nao_existe_de_verdade_nao_avanca_para_o_57(self) -> None:
        site = self.site(ultimo=55, placeholder=56)                 # o /chapter-56 abre ("em breve"), mas o site só lista até o 55
        r = self.atualizar(site, 56)
        self.assertEqual(r["pastas"], [])                           # nada foi baixado
        self.assertIn("não consta na lista de capítulos do site", r["aviso"])
        self.assertIn("é o 55", r["aviso"])
        self.assertIn("0 capítulo(s) baixado(s)", r["aviso"])        # e não "1 capítulo baixado (56)"
        self.assertFalse([p for p in site.paginas_pedidas() if p.endswith("chapter-57")], "não tentou abrir o 57")

    def test_lista_do_site_manda_mais_que_um_botao_que_pula_capitulo(self) -> None:
        site = self.site(ultimo=55, pula={52: 54})                  # o botão do 52 leva ao 54, mas a lista tem o 53
        r = self.atualizar(site, 51)
        self.assertEqual(r["pastas"], ["Cap 052", "Cap 053", "Cap 054", "Cap 055"])

    def test_sem_lista_um_botao_que_pula_capitulo_e_recusado(self) -> None:
        site = self.site(ultimo=55, lista_na_serie=False, pula={52: 54})
        r = self.atualizar(site, 51)
        self.assertEqual(r["pastas"], ["Cap 052"])                  # parou: não baixou o 54 pulando o 53
        self.assertIn("pularia capítulo", r["aviso"])
        self.assertIn("1 capítulo(s) baixado(s)", r["aviso"])

    def test_sem_lista_pagina_inexistente_depois_do_ultimo_e_recusada(self) -> None:
        site = self.site(ultimo=55, lista_na_serie=False, com_proximo_no_ultimo=True)
        r = self.atualizar(site, 54)
        self.assertEqual(r["pastas"], ["Cap 055"])
        self.assertIn("404", r["aviso"])
        self.assertIn("1 capítulo(s) baixado(s)", r["aviso"])
        self.assertTrue(any("Voltei ao capítulo anterior" in m for m in r["linhas"]))

    def test_titulo_da_aba_atrasado_nao_confunde_o_capitulo(self) -> None:
        site = self.site(ultimo=55, titulo_atrasado=True)           # a aba mostra "Chapter N-1" por 1,5 s
        r = self.atualizar(site, 52)
        self.assertEqual(r["pastas"], ["Cap 053", "Cap 054", "Cap 055"])


if __name__ == "__main__":
    unittest.main()
