"""Piloto automático: nasce desligado, só obras escolhidas, não duplica, não sobrescreve, convive com o manual, sobrevive a reinício e falhas."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from baixador.biblioteca import acervo, historico, lidos, obra as dados_obra, organizacao, piloto, verificacao
from baixador.navegador.manual import SessaoManual
from baixador.nucleo.erros import ErroBaixador
from baixador.tests.test_verificacao import Site, pagina, arvore
from baixador.tests.test_web_ia_lotes import criar
from baixador.traducao import executor

NOVO = json.dumps({"formato": 2, "counts": {}, "pages": []})


class ManualFalso:
    """Mesma superfície que o piloto usa em SessaoManual. `baixa` simula o que o navegador faria (cria os capítulos)."""
    def __init__(self, base):
        self.base, self.estado, self.automatico_ativo, self.salvando, self.execucao, self.aviso, self.chamadas = base, "ocioso", False, False, 0, "", []
        self.baixa = None
        self.continuar = None

    def automatico(self, url, pasta, **k):
        self.chamadas.append((url, k))
        self.execucao += 1
        self.automatico_ativo = True

    def concluir(self, numeros, host="site.com", obra="Obra A"):
        for n in numeros:
            self.base.cap(obra, n, host)
        self.automatico_ativo = False

    def definir_continuar(self, v): self.continuar = v
    def cancelar_busca(self): self.automatico_ativo = False
    def fechar_navegador(self): self.estado = "fechado"


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.dir = Path(t.name)
        self.raiz = self.dir / "obras"
        self.raiz.mkdir()
        for alvo, nome in ((historico, "historico.json"), (lidos, "lidos.json"), (verificacao, "verificacao.json"), (piloto, "piloto.json")):
            p = mock.patch.object(alvo, "ARQUIVO", self.dir / nome)
            p.start()
            self.addCleanup(p.stop)
        for p in (mock.patch.object(executor, "disponibilidade", return_value={"pronto": True}), mock.patch.object(executor, "ambiente_do_node", return_value={}),
                  mock.patch.object(piloto, "disponibilidade", return_value={"pronto": True}),
                  mock.patch.object(piloto.config_traducao, "ler", return_value={"motor": "local", "modelo": "x"}),
                  mock.patch.object(executor.config, "ler", return_value={"motor": "local", "modelo": "x"})):
            p.start(); self.addCleanup(p.stop)
        lidos._cache.update(assinatura=None, lidos=frozenset())
        self.site = Site()
        self.manual = ManualFalso(self)
        self.trad = executor.TarefaTraducao()
        self.trad.usar_arquivo_fila(self.dir / "fila.json", self.raiz)
        self.addCleanup(lambda: self.trad.parar())
        self.agora = [1_000_000.0]
        self.p = self.novo()

    def novo(self):
        return piloto.Piloto(self.raiz, self.manual, self.trad, verificar=lambda raiz, so=None, **k: verificacao.verificar(raiz, so=so, forcar=True, buscar=self.site, espera=0, dormir=lambda s: None),
                             agora=lambda: self.agora[0])

    def obra(self, nome="Obra A", host="site.com", caps=(1, 2, 3)):
        url = f"https://{host}/title/{nome.lower().replace(' ', '-')}/"
        for n in caps:
            self.cap(nome, n, host)
        dados_obra.gravar(self.raiz / nome, nome, url)
        self.site.paginas[url] = pagina(host, max(caps), slug=nome.lower().replace(" ", "-"))
        self.url_site = (url, host, nome.lower().replace(" ", "-"))
        return url

    def publicar(self, ate):
        """O site passa a ter capítulos até `ate`; a próxima rodada do piloto (7 h depois) os vê como novos."""
        url, host, slug = self.url_site
        self.site.paginas[url] = pagina(host, ate, slug=slug)
        self.agora[0] += 7 * 3600

    def linha_de_base(self, ate=5):
        """1ª verificação de uma obra só registra o que o site já tinha (nada é "novo"); depois o site publica 4 e 5."""
        self.p.ciclo()
        self.publicar(ate)

    def cap(self, nome, n, host="site.com"):
        rel = criar(self.raiz, nome, n, f"{n:08x}", preparado=False)
        organizacao.gravar_meta(self.raiz / rel, nome, str(n), "", f"https://{host}/title/{nome.lower().replace(' ', '-')}/chapter-{n}/")
        acervo.esquecer_versao()

    def ligar(self, **k):
        c = dict(ativo=True, obras=["Obra A"], etapas={"verificar": True, "baixar": True, "traduzir": True}, limite_baixar=5, limite_traduzir=5)
        c.update(k)
        self.p.configurar(**c)

    def tarefas(self):
        return {t["id"]: t["estado"] for t in self.p.painel()["tarefas"]}

    def traduzir_ok(self, rel):
        (self.raiz / rel / "traducao.json").write_text(NOVO, encoding="utf-8")
        acervo.esquecer_versao()


class Regras(Base):
    def test_nasce_desligado_e_nao_faz_nada(self):
        self.obra()
        self.assertEqual(self.p.painel()["estado"], "desativado")
        self.assertEqual(self.p.ciclo(), "inativo")
        self.assertEqual(self.site.pedidos, [])
        self.assertEqual(self.manual.chamadas, [])

    def test_ativado_sem_obras_escolhidas_nao_toca_em_nada(self):
        self.obra()
        self.ligar(obras=[])
        self.assertEqual(self.p.ciclo(), "nada")
        self.assertEqual(self.site.pedidos, [])

    def test_so_processa_obras_escolhidas(self):
        a, b = self.obra("Obra A"), self.obra("Obra B", host="outro.com")
        self.ligar(obras=["Obra A"])
        self.p.ciclo()
        self.assertEqual(self.site.pedidos, [a])
        self.assertTrue(all(i.split(":")[1] == "obra a" or "obra-a" in i or "a" for i in self.tarefas()))
        self.assertFalse([t for t in self.p.painel()["tarefas"] if t["obra"] == "Obra B"])
        self.assertNotIn(b, self.site.pedidos)

    def test_verificar_baixar_traduzir_de_ponta_a_ponta(self):
        self.obra()
        self.ligar()
        self.linha_de_base()
        self.assertIn("baixar", self.p.ciclo())
        self.assertEqual(len(self.manual.chamadas), 1)
        url, k = self.manual.chamadas[0]
        self.assertTrue(url.endswith("chapter-4/"))
        self.assertEqual((k["limite"], k["continuar"]), (2, True))
        self.assertEqual(set(self.tarefas().values()), {"executando"})
        self.manual.concluir([4, 5])
        with mock.patch.object(self.trad, "_capitulo", side_effect=lambda i, pasta, env: (self.traduzir_ok(f"{pasta.parent.name}/{pasta.name}") or ("pronto", {"falas": 1, "contagens": {}}))):
            self.assertIn("traduzir", self.p.ciclo())
            self.esperar_traducao()
            self.p.ciclo()
        estados = self.tarefas()
        self.assertEqual(set(estados.values()), {"feito"}, estados)
        self.assertEqual(len(estados), 4)

    def esperar_traducao(self):
        t = self.trad._thread if hasattr(self.trad, "_thread") else None
        for _ in range(100):
            if self.trad.estado != "executando":
                return
            threading.Event().wait(0.05)

    def test_nao_duplica_nem_rebaixa_o_que_ja_existe(self):
        self.obra()
        self.ligar(etapas={"verificar": True, "baixar": True, "traduzir": False})
        self.linha_de_base()
        self.p.ciclo()
        self.manual.concluir([4, 5])
        self.p.ciclo()                                     # reconcilia: feitas
        self.agora[0] += 7 * 3600                           # nova rodada: a verificação já não acha nada novo
        self.site.pedidos.clear()
        self.p.ciclo()
        self.assertEqual(len(self.manual.chamadas), 1)
        self.assertEqual(len([t for t in self.p.painel()["tarefas"] if t["tipo"] == "baixar"]), 2)

    def test_capitulo_baixado_a_mao_antes_do_piloto_nao_e_rebaixado(self):
        self.obra()
        self.ligar(etapas={"verificar": True, "baixar": True, "traduzir": False})
        self.linha_de_base()
        self.p._iniciar_execucao(self.p.painel()["config"])        # tarefas 4 e 5 criadas, ainda não lançadas
        self.assertEqual(set(self.tarefas().values()), {"pendente"})
        self.cap("Obra A", 4)                               # a pessoa baixa o 4 antes de o piloto agir
        self.cap("Obra A", 5)
        self.p.ciclo()
        self.assertEqual(self.manual.chamadas, [])
        self.assertEqual(set(self.tarefas().values()), {"feito"})

    def test_nunca_sobrescreve_traducao_existente(self):
        self.obra()
        self.ligar(etapas={"verificar": False, "baixar": False, "traduzir": True})
        self.traduzir_ok("Obra A/Capitulo 1")
        antes = arvore(self.raiz)
        with self.p._trava:
            d = self.p._ler()
            d["tarefas"].append({"id": "traduzir:obraa:1", "tipo": "traduzir", "obra": "Obra A", "numero": "1", "url": "", "rel": "Obra A/Capitulo 1", "estado": "pendente", "tentativas": 0, "erro": "", "t": 0})
            self.p._gravar(d)
        with mock.patch.object(self.trad, "adicionar") as adic:
            self.p.ciclo()
        adic.assert_not_called()
        self.assertEqual(self.tarefas()["traduzir:obraa:1"], "feito")
        self.assertEqual(arvore(self.raiz), antes)

    def test_verificacao_nao_altera_a_biblioteca(self):
        self.obra()
        antes = arvore(self.raiz)
        self.ligar(etapas={"verificar": True, "baixar": False, "traduzir": False})
        self.p.ciclo()
        self.assertEqual(arvore(self.raiz), antes)


class Convivencia(Base):
    def setUp(self):
        super().setUp()
        self.obra()
        self.ligar()
        self.linha_de_base()

    def test_download_manual_ativo_o_piloto_espera_e_nao_mexe(self):
        self.manual.estado, self.manual.automatico_ativo = "procurando", True
        self.p.ciclo()
        self.assertEqual(self.manual.chamadas, [])
        self.assertIsNone(self.manual.continuar)
        self.assertEqual(set(self.tarefas().values()), {"pendente"})
        self.manual.estado, self.manual.automatico_ativo = "ocioso", False   # manual terminou: agora pode
        self.p.ciclo()
        self.assertEqual(len(self.manual.chamadas), 1)

    def test_sessao_manual_nao_e_cancelada_nem_freada_pelo_piloto(self):
        self.manual.estado, self.manual.automatico_ativo, self.manual.execucao = "procurando", True, 9
        self.p.cancelar_tarefas()
        self.p.pausar()
        self.p.configurar(ativo=False)
        self.assertTrue(self.manual.automatico_ativo)
        self.assertIsNone(self.manual.continuar)

    def test_traducao_manual_em_andamento_o_piloto_nao_baixa(self):
        with self.trad._lock:
            self.trad.estado = "executando"
        self.p.ciclo()
        self.assertEqual(self.manual.chamadas, [])
        with self.trad._lock:
            self.trad.estado = "ocioso"

    def test_cancelar_so_cancela_o_que_e_do_piloto(self):
        self.p.ciclo()
        self.assertEqual(self.p.cancelar_tarefas(), 2)
        self.assertEqual(set(self.tarefas().values()), {"cancelada"})
        self.assertFalse(self.manual.automatico_ativo)       # era do piloto (execucao dele)
        self.assertTrue((self.raiz / "Obra A" / "Capitulo 1").is_dir())

    def test_pausar_freia_so_o_download_do_piloto(self):
        self.p.ciclo()
        self.p._sessao = {"execucao": self.manual.execucao, "fechar": True}
        self.p.pausar()
        self.assertIs(self.manual.continuar, False)
        self.assertEqual(self.p.ciclo(), "pausado")

    def test_notebook_sobrecarregado_o_piloto_espera(self):
        with mock.patch.object(piloto.Piloto, "_sobrecarregado", return_value=True):
            self.p.ciclo()
        self.assertEqual(self.manual.chamadas, [])
        self.assertEqual(set(self.tarefas().values()), {"pendente"})

    def test_uma_etapa_pesada_por_vez(self):
        self.p.ciclo()
        self.manual.concluir([4, 5])
        with mock.patch.object(self.trad, "adicionar") as adic:
            self.manual.automatico_ativo = True              # outro download manual começou entre os ciclos
            self.p.ciclo()
            adic.assert_not_called()


class Falhas(Base):
    def setUp(self):
        super().setUp()
        self.obra()

    def ligar(self, **k):
        super().ligar(**k)
        self.linha_de_base()

    def test_falha_ao_abrir_navegador_vira_erro_apos_tentativas_e_pode_tentar_de_novo(self):
        self.ligar(etapas={"verificar": True, "baixar": True, "traduzir": False})
        with mock.patch.object(self.manual, "automatico", side_effect=ErroBaixador("sem navegador")):
            for _ in range(piloto.MAX_TENTATIVAS):
                self.p.ciclo()
                self.agora[0] += 3600                           # espera entre tentativas (10 min × nº de tentativas)
        e = self.tarefas()
        self.assertEqual(set(e.values()), {"erro"}, e)
        self.assertTrue(self.p.painel()["atencao"])
        self.assertEqual(self.p.tentar_de_novo(), 2)
        self.assertEqual(set(self.tarefas().values()), {"pendente"})
        self.p.ciclo()
        self.assertEqual(len(self.manual.chamadas), 1)

    def test_download_termina_sem_o_capitulo_vira_falha_registrada(self):
        self.ligar(etapas={"verificar": True, "baixar": True, "traduzir": False})
        self.p.ciclo()
        self.manual.concluir([])                             # o navegador acabou e nada apareceu
        self.p.ciclo()
        self.assertTrue(any("não apareceu" in h["texto"] for h in self.p.painel()["historico"]))
        n = len(self.manual.chamadas)
        self.p.ciclo()                                       # logo em seguida: respeita a espera, não insiste
        self.assertEqual(len(self.manual.chamadas), n)

    def test_falha_de_traducao_registra_e_permite_retry_sem_refazer_prontos(self):
        self.ligar()
        self.p.ciclo()
        self.manual.concluir([4, 5])
        def capitulo(i, pasta, env):
            if pasta.name.endswith("4"):
                return ("falhou", {"mensagem": "Ollama fora do ar"})
            self.traduzir_ok(f"{pasta.parent.name}/{pasta.name}")
            return ("pronto", {"falas": 1, "contagens": {}})
        with mock.patch.object(self.trad, "_capitulo", side_effect=capitulo):
            self.p.ciclo()
            self.esperar()
            self.p.ciclo()
        e = self.tarefas()
        self.assertEqual(e["traduzir:obraa:5"], "feito")
        self.assertEqual(e["traduzir:obraa:4"], "pendente")
        self.assertTrue(any("Ollama" in h["texto"] for h in self.p.painel()["historico"]))

    def esperar(self):
        for _ in range(100):
            if self.trad.estado != "executando":
                return
            threading.Event().wait(0.05)

    def test_motor_web_so_prepara_e_deixa_em_atencao(self):
        self.ligar()
        self.p.ciclo()
        self.manual.concluir([4, 5])
        with mock.patch.object(piloto.config_traducao, "ler", return_value={"motor": "web"}), mock.patch.object(executor.config, "ler", return_value={"motor": "web"}), \
                mock.patch.object(self.trad, "_capitulo", side_effect=lambda i, pasta, env: ("aguardando", {"textos": 3, "importadas": 0})):
            self.p.ciclo()
            self.esperar()
            self.p.ciclo()
        self.assertEqual({v for k, v in self.tarefas().items() if k.startswith("traduzir")}, {"atencao"})
        self.assertTrue(self.p.painel()["atencao"])

    def test_motor_indisponivel_vira_atencao_sem_rodar(self):
        self.ligar()
        self.p.ciclo()
        self.manual.concluir([4, 5])
        with mock.patch.object(piloto, "disponibilidade", return_value={"pronto": False, "mensagem": "Falta npm install"}), mock.patch.object(self.trad, "adicionar") as adic:
            self.p.ciclo()
        adic.assert_not_called()
        self.assertEqual({v for k, v in self.tarefas().items() if k.startswith("traduzir")}, {"atencao"})

    def test_site_fora_do_ar_nao_derruba_e_nao_cria_tarefa(self):
        url = "https://site.com/title/obra-a/"
        self.ligar()
        self.site.paginas[url] = ErroBaixador("site fora")
        self.p.ciclo()
        self.assertEqual(self.p.painel()["tarefas"], [])
        self.assertEqual(self.manual.chamadas, [])


class Reinicio(Base):
    def test_reinicio_no_meio_do_download_recupera_sem_duplicar(self):
        self.obra()
        self.ligar(etapas={"verificar": True, "baixar": True, "traduzir": False})
        self.linha_de_base()
        self.p.ciclo()
        self.manual.concluir([4])                            # caiu no meio: só o 4 chegou
        self.manual.base = self
        p2 = self.novo()                                    # programa reaberto: estado vem do disco
        self.assertEqual(p2.painel()["config"]["ativo"], True)
        p2.ciclo()
        e = {t["id"]: t["estado"] for t in p2.painel()["tarefas"]}
        self.assertEqual(sorted(e.values()), ["executando", "feito"], e)
        self.assertEqual({t["tentativas"] for t in p2.painel()["tarefas"]}, {0})
        self.assertEqual(len(self.manual.chamadas), 2)       # só o 5 é pedido de novo
        self.assertTrue(self.manual.chamadas[1][0].endswith("chapter-5/"))

    def test_gravacao_atomica_arquivo_nunca_fica_corrompido(self):
        self.obra()
        self.ligar()
        self.linha_de_base()
        self.p.ciclo()
        json.loads(piloto.ARQUIVO.read_text(encoding="utf-8"))
        self.assertFalse(piloto.ARQUIVO.with_suffix(".tmp").exists())

    def test_arquivo_corrompido_volta_ao_padrao_desligado(self):
        piloto.ARQUIVO.write_text("{ruim", encoding="utf-8")
        self.assertEqual(self.p.painel()["estado"], "desativado")


class ServicosReais(Base):
    def test_sessao_manual_real_ociosa_conta_como_livre(self):
        p = piloto.Piloto(self.raiz, SessaoManual(), self.trad)
        self.assertTrue(p._manual_livre())
        self.assertTrue(p._traducao_livre())

    def test_atributos_que_o_piloto_le_existem_nos_servicos_reais(self):
        m = SessaoManual()
        for atributo in ("estado", "automatico_ativo", "salvando", "execucao", "aviso"):
            self.assertTrue(hasattr(m, atributo), atributo)
        for metodo in ("automatico", "definir_continuar", "cancelar_busca", "fechar_navegador"):
            self.assertTrue(callable(getattr(m, metodo)), metodo)
        for metodo in ("adicionar", "preparar_web", "parar", "cancelar_item", "rels_ativos", "rels_em_preparacao", "itens_por_rel"):
            self.assertTrue(callable(getattr(self.trad, metodo)), metodo)

    def test_rotas_http_exigem_token_validam_e_controlam(self):
        import urllib.request, urllib.error
        from baixador.servidor.notebook import criar_servidor
        srv = criar_servidor("tok", raiz=self.raiz, manual=self.manual)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        base = f"http://127.0.0.1:{srv.server_address[1]}"

        def chamar(rota, corpo=None, token="tok"):
            req = urllib.request.Request(f"{base}{rota}?t={token}", data=None if corpo is None else json.dumps(corpo).encode(), headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, None
        self.assertEqual(chamar("/api/piloto", token="errado")[0], 403)
        self.assertEqual(chamar("/api/piloto/config", {"ativo": True}, token="errado")[0], 403)
        st, d = chamar("/api/piloto")
        self.assertEqual((st, d["estado"]), (200, "desativado"))
        self.assertEqual(chamar("/api/piloto/config", {"limite_baixar": 99})[0], 400)
        self.assertEqual(chamar("/api/piloto/config", {"ativo": "sim"})[0], 400)
        self.assertEqual(chamar("/api/piloto/xyz", {})[0], 404)
        st, d = chamar("/api/piloto/config", {"ativo": True, "obras": ["Obra A"]})
        self.assertEqual((st, d["config"]["ativo"]), (200, True))
        self.assertEqual(chamar("/api/piloto/pausar", {"pausado": True})[0], 200)
        self.assertEqual(chamar("/api/piloto")[1]["estado"], "pausado")
        self.assertEqual(chamar("/api/piloto/cancelar", {})[0], 200)


class Validacao(unittest.TestCase):
    def test_validar_config(self):
        v = piloto.validar_config
        self.assertEqual(v({"ativo": True, "obras": ["A"], "limite_baixar": 3, "intervalo_min": 60, "etapas": {"baixar": True}}), "")
        for ruim in ({"ativo": "sim"}, {"obras": "A"}, {"obras": [1]}, {"limite_baixar": 0}, {"limite_baixar": 99}, {"limite_baixar": True},
                     {"intervalo_min": 7}, {"etapas": {"x": True}}, {"etapas": {"baixar": 1}}, []):
            self.assertTrue(v(ruim), ruim)


if __name__ == "__main__":
    unittest.main()
