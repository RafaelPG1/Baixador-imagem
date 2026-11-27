"""Verificação de capítulos novos: descobre e mostra, nunca baixa/traduz/altera a biblioteca."""
import hashlib
import json
import shutil
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from baixador.biblioteca import acervo, historico, lidos, obra as dados_obra, organizacao, verificacao
from baixador.nucleo.erros import ErroBaixador
from baixador.tests.test_web_ia_lotes import criar


def pagina(site, ate, de=1, slug="obra-a"):
    links = "".join(f'<li><a href="https://{site}/title/{slug}/chapter-{n}/">Chapter {n}</a></li>' for n in range(de, ate + 1))
    return f"<html><body><ul>{links}</ul></body></html>".encode()


class Site:
    """Site falso: `paginas[url_da_obra]` = bytes ou exceção. Conta os pedidos."""

    def __init__(self):
        self.paginas, self.pedidos = {}, []

    def __call__(self, url, limite):
        self.pedidos.append(url)
        r = self.paginas[url]
        if isinstance(r, Exception):
            raise r
        return r


def arvore(raiz):
    return {str(p.relative_to(raiz)): (p.stat().st_mtime_ns, p.stat().st_size) for p in sorted(Path(raiz).rglob("*")) if p.is_file()}


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.dir = Path(t.name)
        self.raiz = self.dir / "obras"
        self.raiz.mkdir()
        for alvo, nome in ((historico, "historico.json"), (lidos, "lidos.json"), (verificacao, "verificacao.json")):
            p = mock.patch.object(alvo, "ARQUIVO", self.dir / nome)
            p.start()
            self.addCleanup(p.stop)
        lidos._cache.update(assinatura=None, lidos=frozenset())
        self.site = Site()
        self.nada = lambda s: None                         # sem pausa de verdade nos testes
        
    def obra(self, nome="Obra A", host="site.com", caps=(1, 2, 3)):
        url = f"https://{host}/title/{nome.lower().replace(' ', '-')}/"
        for n in caps:
            self.cap(nome, n, host)
        dados_obra.gravar(self.raiz / nome, nome, url)
        return url

    def cap(self, nome, n, host="site.com"):
        rel = criar(self.raiz, nome, n, f"{n:08x}", preparado=False)
        organizacao.gravar_meta(self.raiz / rel, nome, str(n), "", f"https://{host}/title/{nome.lower().replace(' ', '-')}/chapter-{n}/")
        acervo.esquecer_versao()

    def rodar(self, **k):
        return verificacao.verificar(self.raiz, buscar=self.site, espera=0, dormir=self.nada, **k)

    def da_obra(self, nome="Obra A"):
        return next(o for o in verificacao.painel(self.raiz)["obras"] if o["nome"] == nome)


class Verificacao(Base):
    def test_primeira_cria_base_depois_acha_novos_e_nao_confunde(self):
        url = self.obra()
        self.site.paginas[url] = pagina("site.com", 5)
        r = self.rodar()
        o = self.da_obra()
        self.assertEqual((r["novos"], o["status"], o["primeira"], [c["numero"] for c in o["novos"]]), (0, "ok", True, []))   # o que já existia não é novidade
        self.assertEqual([c["numero"] for c in o["fora"]], ["4", "5"])                                                         # mas não está na biblioteca
        self.site.paginas[url] = pagina("site.com", 7)
        r = self.rodar(forcar=True)
        o = self.da_obra()
        self.assertEqual((r["novos"], r["com_novos"]), (2, 1))
        self.assertEqual([c["numero"] for c in o["novos"]], ["6", "7"])
        self.assertEqual(o["novos"][0]["url"], "https://site.com/title/obra-a/chapter-6/")
        self.assertEqual((o["fora_total"], o["total_site"], o["ultimo_site"]), (4, 7, "7"))
        self.assertEqual(historico.ficha("Obra A")["encontrado"], "7")                                                         # histórico atualizado

    def test_sem_novidades_e_repeticao_nao_duplicam(self):
        url = self.obra()
        self.site.paginas[url] = pagina("site.com", 4)
        self.rodar()
        self.site.paginas[url] = pagina("site.com", 6)
        self.rodar(forcar=True)
        n = len(self.site.pedidos)
        r = self.rodar()                                                       # logo depois: não insiste no site
        self.assertEqual((len(self.site.pedidos), r["novos"]), (n, 0))
        r = self.rodar(forcar=True)                                            # forçada: vai ao site, mas os mesmos novos não se repetem
        self.assertEqual((len(self.site.pedidos), r["novos"], [c["numero"] for c in self.da_obra()["novos"]]), (n + 1, 0, ["5", "6"]))
        self.assertEqual(len(verificacao.ler()["historico"]), 4)

    def test_conhecidos_baixados_e_apagados_nao_sao_novos(self):
        url = self.obra()
        self.site.paginas[url] = pagina("site.com", 4)
        self.rodar()                                                           # base: 1-4 conhecidos
        shutil.rmtree(self.raiz / "Obra A" / "Capitulo 2")                      # apagado de propósito
        acervo.esquecer_versao()
        self.site.paginas[url] = pagina("site.com", 6)
        self.rodar(forcar=True)
        o = self.da_obra()
        self.assertEqual([c["numero"] for c in o["novos"]], ["5", "6"])        # o 2 apagado e o 4 nunca baixado: antigos, não novos
        self.assertIn("2", [c["numero"] for c in o["fora"]])                   # mas aparecem como "fora da biblioteca"
        self.cap("Obra A", 5)                                                  # a pessoa baixa o 5: some da lista sozinho
        self.assertEqual([c["numero"] for c in self.da_obra()["novos"]], ["6"])

    def test_nao_mexe_na_biblioteca(self):
        url = self.obra()
        self.site.paginas[url] = pagina("site.com", 5)
        antes = arvore(self.raiz)
        self.rodar()
        self.site.paginas[url] = pagina("site.com", 9)
        self.rodar(forcar=True)
        depois = {k: v for k, v in arvore(self.raiz).items()}
        self.assertEqual(antes, depois)                                         # nenhum arquivo criado, alterado ou apagado
        self.assertFalse(any((self.raiz / "Obra A" / f"Capitulo {n}").exists() for n in range(4, 10)))

    def test_site_fora_do_ar_isola_o_erro_e_respeita_limite(self):
        ua, ub = self.obra("Obra A", "a.com"), self.obra("Obra B", "a.com")
        uc = self.obra("Obra C", "c.com")
        self.site.paginas[ua] = ErroBaixador("O site respondeu 429.")
        self.site.paginas[ub] = ErroBaixador("O site respondeu 429.")
        self.site.paginas[uc] = pagina("c.com", 5, slug="obra-c")
        self.rodar()
        s = {o["nome"]: o["status"] for o in verificacao.painel(self.raiz)["obras"]}
        self.assertEqual((sorted([s["Obra A"], s["Obra B"]]), s["Obra C"]), (["adiada", "erro"], "ok"))   # o 2º do site que pediu calma espera; o outro site segue
        self.assertEqual(len([u for u in self.site.pedidos if "a.com" in u]), 1)               # não insistiu no site que recusou
        self.site.paginas[ua] = self.site.paginas[ub] = ConnectionResetError("x")
        self.rodar(forcar=True)
        self.assertEqual(self.da_obra()["status"], "erro")
        self.assertIn("ConnectionResetError", self.da_obra()["erro"])                      # erro inesperado também não derruba

    def test_erro_nao_apaga_novos_ja_achados(self):
        url = self.obra()
        self.site.paginas[url] = pagina("site.com", 3)
        self.rodar()
        self.site.paginas[url] = pagina("site.com", 5)
        self.rodar(forcar=True)
        self.site.paginas[url] = ErroBaixador("Falha de conexão (timeout).")
        self.rodar(forcar=True)
        o = self.da_obra()
        self.assertEqual((o["status"], [c["numero"] for c in o["novos"]]), ("erro", ["4", "5"]))

    def test_pagina_sem_lista(self):
        url = self.obra()
        self.site.paginas[url] = b"<html><body>carregando por script</body></html>"
        self.rodar()
        self.assertEqual(self.da_obra()["status"], "sem_lista")

    def test_escolha_de_obras_e_uma_por_vez(self):
        ua, ub = self.obra("Obra A"), self.obra("Obra B", "b.com")
        self.site.paginas[ua], self.site.paginas[ub] = pagina("site.com", 4), pagina("b.com", 4, slug="obra-b")
        verificacao.definir_config(desligadas=["Obra B"])
        self.rodar()
        self.assertEqual(self.site.pedidos, [ua])                                         # desligada não é verificada
        self.rodar(so=["Obra B"], forcar=True)                                           # escolhida à mão vale mesmo desligada
        self.assertEqual(self.site.pedidos, [ua, ub])
        parar, dentro = threading.Event(), threading.Event()

        def lento(url, limite):
            dentro.set()
            parar.wait(5)
            return pagina("site.com", 4)

        t = threading.Thread(target=lambda: verificacao.verificar(self.raiz, buscar=lento, espera=0, dormir=self.nada, forcar=True))
        t.start()
        dentro.wait(5)
        self.assertTrue(verificacao.verificar(self.raiz, buscar=self.site)["rodando"])      # segunda ao mesmo tempo: recusada, nada duplicado
        self.assertTrue(verificacao.painel(self.raiz)["andamento"]["rodando"])
        parar.set()
        t.join(10)
        self.assertFalse(verificacao.painel(self.raiz)["andamento"]["rodando"])

    def test_config_dispensar_e_pausa_entre_pedidos_do_mesmo_site(self):
        self.assertFalse(verificacao.ler()["config"]["periodica"])
        c = verificacao.definir_config(periodica=True, intervalo_h=99)                      # intervalo inválido é ignorado
        self.assertEqual((c["periodica"], c["intervalo_h"]), (True, 6))
        self.assertEqual(verificacao.definir_config(intervalo_h=12)["intervalo_h"], 12)
        ua, ub = self.obra("Obra A"), self.obra("Obra B")
        self.site.paginas[ua], self.site.paginas[ub] = pagina("site.com", 3), pagina("site.com", 3, slug="obra-b")
        esperas = []
        verificacao.verificar(self.raiz, buscar=self.site, espera=3.0, dormir=esperas.append)
        self.assertEqual(len(esperas), 1)                                                   # 2 obras do mesmo site: 1 pausa
        self.assertTrue(0 < esperas[0] <= 3.0)
        self.site.paginas[ua] = pagina("site.com", 5)
        verificacao.verificar(self.raiz, buscar=self.site, espera=0, dormir=self.nada, forcar=True)
        self.assertTrue(verificacao.dispensar("Obra A", ["4"]))
        self.assertEqual([c["numero"] for c in self.da_obra()["novos"]], ["5"])
        self.assertTrue(verificacao.dispensar("Obra A"))
        self.assertEqual(self.da_obra()["novos"], [])
        self.assertFalse(verificacao.dispensar("Nada"))

    def test_persiste_apos_reinicio_e_arquivo_corrompido_nao_quebra(self):
        url = self.obra()
        self.site.paginas[url] = pagina("site.com", 3)
        self.rodar()
        self.assertEqual(json.loads(verificacao.ARQUIVO.read_text(encoding="utf-8"))["historico"][0]["verificadas"], 1)
        verificacao.ARQUIVO.write_text("{quebrado", encoding="utf-8")
        self.assertEqual(verificacao.ler()["historico"], [])                                # ilegível: volta ao padrão, sem exceção
        self.assertEqual(verificacao.painel(self.raiz)["obras"][0]["status"], "nunca")


class Rotas(Base):
    def setUp(self):
        super().setUp()
        from baixador.servidor.notebook import criar_servidor

        self.srv = criar_servidor("tok", 0, raiz=self.raiz)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.srv.shutdown(), self.srv.server_close()))
        self.porta = self.srv.server_address[1]

    def chamar(self, caminho, corpo=None, token="tok"):
        r = urllib.request.Request(f"http://127.0.0.1:{self.porta}{caminho}?t={token}", data=None if corpo is None else json.dumps(corpo).encode(),
                                   headers={"Content-Type": "application/json", "Host": f"127.0.0.1:{self.porta}"})
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, json.load(resp)
        except urllib.error.HTTPError as e:
            return e.code, {}

    def test_rotas(self):
        url = self.obra()
        self.assertEqual(self.chamar("/api/verificacao", token="errado")[0], 403)
        self.assertEqual(self.chamar("/api/verificacao/iniciar", {}, token="errado")[0], 403)
        s, p = self.chamar("/api/verificacao")
        self.assertEqual((s, [o["nome"] for o in p["obras"]], p["ultima"]), (200, ["Obra A"], 0))
        self.assertEqual(self.chamar("/api/verificacao/config", {"periodica": True, "intervalo_h": 3})[1]["config"]["intervalo_h"], 3)
        self.assertEqual(self.chamar("/api/verificacao/config", {"intervalo_h": 5})[0], 400)
        chamadas = []
        feito = threading.Event()
        with mock.patch.object(verificacao, "verificar", lambda *a, **k: (chamadas.append((a, k)), feito.set())):
            self.assertEqual(self.chamar("/api/verificacao/iniciar", {"obras": ["Obra A"], "forcar": True})[0], 200)
            feito.wait(5)
        self.assertEqual(chamadas[0][1], {"so": ["Obra A"], "forcar": True})
        self.assertEqual(self.chamar("/api/verificacao/iniciar", {"obras": "x"})[0], 400)
        with mock.patch.dict(verificacao._andamento, {"rodando": True}):
            self.assertEqual(self.chamar("/api/verificacao/iniciar", {})[0], 409)
        self.assertEqual(self.chamar("/api/verificacao/dispensar", {"obra": "Nada"})[0], 404)


if __name__ == "__main__":
    unittest.main()
