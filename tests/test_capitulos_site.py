"""Lógica dos capítulos do site: lista oficial, capítulo aberto, próximo e conferência da chegada (sem navegador)."""

from __future__ import annotations

import unittest

from baixador.navegador import capitulos_site as cs

BASE = "https://site.exemplo/manga/obra-x/"
URL = lambda n: f"{BASE}chapter-{n}"  # noqa: E731


def serie_html(numeros, extras=""):
    itens = "".join(f'<li><a href="/manga/obra-x/chapter-{str(n).replace(".", "-")}">Chapter {n}</a></li>' for n in numeros)
    return f"<html><body><a href='/'>Início</a><a href='/manga/outra-obra/chapter-9'>Outra obra</a><ul>{itens}</ul>{extras}</body></html>"


class TestModelo(unittest.TestCase):
    def test_numero_pelo_endereco(self) -> None:
        m = cs.modelo_url(URL(55))
        self.assertEqual(m.numero(URL(54)), "54")
        self.assertEqual(m.numero(URL("54-5")), "54.5")
        self.assertEqual(m.numero(URL("007")), "7")
        self.assertIsNone(m.numero(BASE))                                              # a página da obra não é capítulo
        self.assertIsNone(m.numero("https://site.exemplo/manga/outra-obra/chapter-9"))  # outra obra
        self.assertIsNone(m.numero("https://outro.site/manga/obra-x/chapter-9"))        # outro site

    def test_escolhe_o_numero_do_capitulo_e_nao_o_da_obra_nem_o_da_pagina(self) -> None:
        self.assertEqual(cs.modelo_url("https://s.com/manga/obra-2/chapter-55").numero("https://s.com/manga/obra-2/chapter-12"), "12")
        self.assertEqual(cs.modelo_url("https://s.com/read/obra/chapter-55/page-3").numero("https://s.com/read/obra/chapter-56/page-3"), "56")
        self.assertEqual(cs.modelo_url("https://s.com/ler/obra/capitulo/56").numero("https://s.com/ler/obra/capitulo/57"), "57")

    def test_so_confia_no_numero_do_endereco_quando_ha_palavra_de_capitulo(self) -> None:
        self.assertTrue(cs.modelo_url(URL(55)).com_palavra)
        self.assertTrue(cs.modelo_url("https://s.com/ler/obra/ep-55").com_palavra)
        self.assertFalse(cs.modelo_url("https://s.com/manga/obra/55").com_palavra)             # número solto
        self.assertFalse(cs.modelo_url("https://s.com/manga/obra/55/pagina/1").com_palavra)    # o último número é o da página

    def test_numero_solto_no_endereco_nao_vence_o_titulo(self) -> None:
        # /obra/55/pagina/1: o "número do endereço" seria 1 em todo capítulo; o título da aba é quem sabe
        m = cs.modelo_url("https://s.com/manga/obra/55/pagina/1")
        a = cs.identificar_atual("https://s.com/manga/obra/55/pagina/1", "Obra X Chapter 55 - Site", m, None)
        self.assertEqual((a.numero, a.fonte), ("55", "título"))
        # sem título com número, o do endereço ainda serve
        self.assertEqual(cs.identificar_atual("https://s.com/manga/obra/55", "Obra X", cs.modelo_url("https://s.com/manga/obra/55"), None).numero, "55")

    def test_numero_na_consulta(self) -> None:
        m = cs.modelo_url("https://s.com/reader?series=3&chapter=55")
        self.assertEqual(m.numero("https://s.com/reader?series=3&chapter=54"), "54")
        self.assertIsNone(cs.modelo_url("https://s.com/obra/sem-numero"))


class TestIndice(unittest.TestCase):
    def indice(self, numeros):
        m = cs.modelo_url(URL(1))
        return cs.IndiceSite(cs.itens_do_html(serie_html(numeros), BASE, m), "serie", BASE)

    def test_extrai_so_capitulos_desta_obra_em_ordem(self) -> None:
        idx = self.indice(range(55, 0, -1))                          # a página lista do mais novo para o mais antigo
        self.assertEqual(len(idx), 55)
        self.assertEqual((idx.menor.numero, idx.maior.numero), ("1", "55"))
        self.assertTrue(idx.confiavel)
        self.assertEqual(idx.por_url(URL(10)).numero, "10")
        self.assertEqual(idx.por_url(URL(10) + "/").numero, "10")      # barra final e # não atrapalham
        self.assertEqual(idx.por_url(URL(10) + "#comments").numero, "10")

    def test_menu_de_opcoes_e_duplicados(self) -> None:
        extra = '<select><option value="/manga/obra-x/chapter-3">Chapter 3</option><option value="/manga/obra-x/chapter-4">Chapter 4</option></select><a href="/manga/obra-x/chapter-3">Read first</a>'
        m = cs.modelo_url(URL(1))
        idx = cs.IndiceSite(cs.itens_do_html(serie_html([1, 2], extra), BASE, m))
        self.assertEqual([i.numero for i in idx.itens], ["1", "2", "3", "4"])

    def test_poucos_links_nao_formam_uma_lista_confiavel(self) -> None:
        self.assertFalse(self.indice([54, 55]).confiavel)
        self.assertFalse(cs.IndiceSite([]).confiavel)

    def test_proximo_com_decimal_e_buraco(self) -> None:
        idx = self.indice([1, 2, 2.5, 3, 5])
        self.assertEqual(idx.proximo_de("2").numero, "2.5")
        self.assertEqual(idx.proximo_de("3").numero, "5")             # o 4 não existe no site
        self.assertIsNone(idx.proximo_de("5"))


class TestAtual(unittest.TestCase):
    def test_titulo_atrasado_nao_engana(self) -> None:
        m = cs.modelo_url(URL(1))
        a = cs.identificar_atual(URL(52), "Obra X Chapter 51 - Site", m, None)       # a aba ainda mostra o capítulo anterior
        self.assertEqual((a.numero, a.fonte), ("52", "endereço"))
        self.assertIn("usei o endereço", a.aviso)

    def test_lista_tem_prioridade(self) -> None:
        m = cs.modelo_url(URL(1))
        idx = cs.IndiceSite(cs.itens_do_html(serie_html(range(1, 10)), BASE, m))
        a = cs.identificar_atual(URL(7), "Obra X Chapter 99", m, idx)
        self.assertEqual((a.numero, a.fonte), ("7", "lista"))
        self.assertIn("usei a lista", a.aviso)

    def test_sem_endereco_numerado_usa_o_titulo(self) -> None:
        a = cs.identificar_atual("https://s.com/obra/abc123", "Obra X Chapter 12 - Site", None, None)
        self.assertEqual((a.numero, a.fonte), ("12", "título"))
        self.assertIsNone(cs.identificar_atual("https://s.com/obra/abc123", "Obra X", None, None).numero)


class TestDecisao(unittest.TestCase):
    def setUp(self) -> None:
        m = cs.modelo_url(URL(1))
        self.m = m
        self.idx = cs.IndiceSite(cs.itens_do_html(serie_html(range(1, 56)), BASE, m))

    def atual(self, n):
        return cs.identificar_atual(URL(n), "", self.m, self.idx)

    def test_avanca_pela_lista(self) -> None:
        d = cs.decidir_proximo(self.idx, self.atual(54))
        self.assertEqual((d.tipo, d.item.numero, d.item.url), ("lista", "55", URL(55)))

    def test_ultimo_capitulo_e_fim_nao_erro(self) -> None:
        d = cs.decidir_proximo(self.idx, self.atual(55))
        self.assertEqual(d.tipo, "fim")
        self.assertIn("último capítulo do site é o 55", d.mensagem)

    def test_capitulo_56_que_nao_existe_na_lista_nao_avanca_para_o_57(self) -> None:
        d = cs.decidir_proximo(self.idx, self.atual(56))
        self.assertEqual(d.tipo, "fora-da-lista")
        self.assertIn("não consta na lista", d.mensagem)
        self.assertIn("é o 55", d.mensagem)
        self.assertIsNone(d.item)

    def test_buraco_na_numeracao_do_site_e_avisado(self) -> None:
        idx = cs.IndiceSite([cs.Item(str(n), URL(n)) for n in (1, 2, 3, 5, 6)])
        d = cs.decidir_proximo(idx, cs.identificar_atual(URL(3), "", self.m, idx))
        self.assertEqual((d.tipo, d.item.numero), ("lista", "5"))
        self.assertIn("não tem os capítulos entre 3 e 5", d.aviso)

    def test_sem_lista_cai_no_botao(self) -> None:
        self.assertEqual(cs.decidir_proximo(None, cs.Atual("5", "endereço")).tipo, "botao")
        self.assertEqual(cs.decidir_proximo(cs.IndiceSite([]), cs.Atual("5", "endereço")).tipo, "botao")
        self.assertEqual(cs.decidir_proximo(self.idx, cs.Atual(None, "")).tipo, "botao")


class TestChegada(unittest.TestCase):
    def setUp(self) -> None:
        self.m = cs.modelo_url(URL(1))
        self.idx = cs.IndiceSite(cs.itens_do_html(serie_html(range(1, 56)), BASE, self.m))
        self.esperado = self.idx.por_numero("55")

    def chegou(self, url, status=200, indice=True, esperado=True, de="54", titulo=""):
        novo = cs.identificar_atual(url, titulo, self.m, self.idx if indice else None)
        return cs.validar_chegada(de, URL(55), url, novo, self.idx if indice else None, status, self.esperado if esperado else None)

    def test_chegada_certa(self) -> None:
        self.assertEqual(self.chegou(URL(55)), (True, ""))

    def test_404_nao_e_capitulo(self) -> None:
        ok, motivo = self.chegou(URL(57), status=404)
        self.assertFalse(ok)
        self.assertIn("404", motivo)

    def test_redirecionou_para_outro_lugar(self) -> None:
        ok, motivo = self.chegou(BASE)
        self.assertFalse(ok)
        self.assertIn("outro endereço", motivo)

    def test_outro_capitulo_que_nao_o_esperado(self) -> None:
        ok, motivo = self.chegou(URL(56))
        self.assertFalse(ok)

    def test_sem_lista_nunca_pula_nem_repete(self) -> None:
        self.assertEqual(self.chegou(URL(55), indice=False, esperado=False), (True, ""))
        ok, motivo = self.chegou(URL(57), indice=False, esperado=False, de="55")
        self.assertFalse(ok)
        self.assertIn("pularia", motivo)
        ok, motivo = self.chegou(URL(54), indice=False, esperado=False, de="54")
        self.assertFalse(ok)
        self.assertIn("não vem depois", motivo)
        # sem número descobrível em lugar nenhum: não dá para conferir, vale a conferência das imagens (como sempre foi)
        self.assertTrue(cs.validar_chegada("54", "", "https://s.com/x/abc", cs.Atual(None, ""), None, 200)[0])

    def test_pagina_da_obra_ou_inicial_nunca_e_capitulo(self) -> None:
        novo = cs.identificar_atual(BASE, "", self.m, None)
        ok, motivo = cs.validar_chegada("55", "", BASE, novo, None, 200, nao_capitulo=(BASE.rstrip("/"), "https://site.exemplo/"))
        self.assertFalse(ok)
        self.assertIn("página da obra ou a inicial", motivo)
        ok, _ = cs.validar_chegada("55", "", "https://site.exemplo/", cs.Atual(None, ""), None, 200, nao_capitulo=(BASE, "https://site.exemplo/"))
        self.assertFalse(ok)

    def test_sem_lista_meio_capitulo_e_aceito(self) -> None:
        self.assertTrue(self.chegou(URL("54-5"), indice=False, esperado=False, de="54")[0])
        self.assertTrue(self.chegou(URL(55), indice=False, esperado=False, de="54.5")[0])


if __name__ == "__main__":
    unittest.main()
