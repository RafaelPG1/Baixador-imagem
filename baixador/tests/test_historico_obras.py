"""Histórico das obras: independente da biblioteca, só acrescenta, sobrevive a exclusão e reinício."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from baixador.biblioteca import acervo, historico, lidos, obra as dados_obra
from baixador.tests.test_web_ia_lotes import criar

URL = "https://site.com/title/minha-obra/"


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.dir = Path(t.name)
        self.raiz = self.dir / "obras"
        self.raiz.mkdir()
        for alvo, nome in ((historico, "historico.json"), (lidos, "lidos.json")):
            p = mock.patch.object(alvo, "ARQUIVO", self.dir / nome)
            p.start()
            self.addCleanup(p.stop)
        lidos._cache.update(assinatura=None, lidos=frozenset())

    def ficha(self, nome="Minha Obra"):
        return next(f for f in historico.ler()["obras"].values() if f["nome"] == nome)

    def cap(self, n, nome="Minha Obra"):
        rel = criar(self.raiz, nome, n, f"{n:08x}", preparado=False)
        acervo.esquecer_versao()
        return self.raiz / rel


class HistoricoObras(Base):
    def test_cadastro_pelo_obra_json(self):
        self.cap(1)
        dados_obra.gravar(self.raiz / "Minha Obra", "Minha Obra", URL + "123-chapter-1")
        f = self.ficha()
        self.assertEqual((f["url"], f["site"], f["situacao"]), (URL, "site.com", "andamento"))

    def test_descoberta_download_traducao_leitura(self):
        historico.registrar_obra("Minha Obra", URL, encontrado=50, descoberta=True, conhecidos={"49": "u49", "50": "u50"})
        pasta = self.cap(3)
        historico.anotar_capitulo(pasta, baixado=True)
        historico.anotar_capitulo(pasta, traduzido=True)
        historico.anotar_capitulo(pasta, lido=True, pos={"p": 4, "t": 10, "f": 0.5})
        f = self.ficha()
        self.assertEqual((f["encontrado"], f["baixado"], f["traduzido"], f["lido"]), ("50", "3", "3", "3"))
        self.assertEqual(f["pos"], {"n": "3", "p": 4, "t": 10, "f": 0.5})
        self.assertTrue(f["t_descoberta"] and f["t_lido"] and f["t_atualizado"])
        self.assertEqual(set(f["conhecidos"]), {"3", "49", "50"})
        self.assertEqual(f["conhecidos"]["50"], "u50")

    def test_nunca_rebaixa_nem_apaga(self):
        historico.registrar_obra("Minha Obra", URL, encontrado=50, baixado=10, conhecidos={"1": "u1"})
        historico.registrar_obra("Minha Obra", "", encontrado=20, baixado="2", conhecidos={"1": ""})     # menor e vazio
        f = self.ficha()
        self.assertEqual((f["encontrado"], f["baixado"], f["url"], f["conhecidos"]["1"]), ("50", "10", URL, "u1"))

    def test_leitura_mais_nova_vence_mesmo_voltando_capitulo(self):
        agora = int(time.time() * 1000)
        historico.registrar_obra("Minha Obra", URL, lido=9, t=agora)
        historico.registrar_obra("Minha Obra", URL, lido=2, t=agora - 5000)         # velha: ignorada
        self.assertEqual(self.ficha()["lido"], "9")
        historico.registrar_obra("Minha Obra", URL, lido=2, t=agora + 5)            # releitura mais nova
        self.assertEqual(self.ficha()["lido"], "2")

    def test_sem_duplicata_por_url_ou_nome(self):
        historico.registrar_obra("", URL, encontrado=5)                              # só pelo endereço: nome vem do slug
        historico.registrar_obra("Minha Obra", URL)                                  # nome de verdade completa a mesma ficha
        historico.registrar_obra("minha  obra!", "", baixado=1)                      # mesmo nome sem acento/pontuação
        obras = historico.ler()["obras"]
        self.assertEqual(len(obras), 1)
        self.assertEqual(self.ficha()["nome"], "Minha Obra")
        self.assertEqual(self.ficha()["baixado"], "1")

    def test_ler_tudo_nao_conclui_a_obra(self):
        historico.registrar_obra("Minha Obra", URL, encontrado=3, baixado=3)
        for n in (1, 2, 3):
            historico.registrar_obra("Minha Obra", URL, lido=n, pos={"p": 5, "t": 5, "f": 1})
        self.assertEqual(self.ficha()["situacao"], "andamento")                       # leitura em dia, obra continua em andamento
        self.assertTrue(historico.definir_situacao("Minha Obra", "pausada"))
        self.assertFalse(historico.definir_situacao("Minha Obra", "inventada"))
        self.assertEqual(self.ficha()["situacao"], "pausada")
        historico.registrar_obra("Minha Obra", URL, encontrado=4, descoberta=True)    # nova descoberta não muda a situação
        self.assertEqual(self.ficha()["situacao"], "pausada")

    def test_excluir_obra_da_biblioteca_mantem_historico(self):
        pasta = self.cap(1)
        self.cap(2)
        dados_obra.gravar(self.raiz / "Minha Obra", "Minha Obra", URL + "x-1")
        historico.anotar_capitulo(pasta, baixado=True, lido=True, pos={"p": 2, "t": 8, "f": 0.4})
        acervo.excluir_obra(self.raiz, "Minha Obra")
        acervo.esquecer_versao()
        self.assertEqual(acervo.listar(self.raiz)["obras"], [])
        f = self.ficha()                                                              # a ficha sobrevive, inclusive posição exata
        self.assertEqual((f["baixado"], f["lido"], f["pos"]["p"], f["url"]), ("1", "1", 2, URL))
        self.assertEqual(self.ficha()["id"], historico.ler()["obras"][f["id"]]["id"])

    def test_reinicio_le_do_disco_e_arquivo_antigo_continua_valido(self):
        historico.registrar_obra("Minha Obra", URL, baixado=7)
        bruto = json.loads(historico.ARQUIVO.read_text(encoding="utf-8"))             # o que sobra no disco após fechar o programa
        self.assertEqual(list(bruto["obras"].values())[0]["baixado"], "7")
        historico.ARQUIVO.write_text(json.dumps({"posicoes": {"O/C1": {"p": 1, "n": 2, "f": 0.1, "t": 5}}, "lidos": {}, "estados": {}}), encoding="utf-8")
        d = historico.ler()                                                           # arquivo de antes do recurso
        self.assertEqual((d["obras"], d["posicoes"]["O/C1"]["p"]), ({}, 1))
        self.assertEqual(historico.resumo()["obras"], {})
        self.assertTrue(historico.registrar_obra("Minha Obra", URL))
        self.assertIn("O/C1", historico.ler()["posicoes"])                           # seções antigas preservadas na escrita

    def test_sincronizar_biblioteca_importa_obras_existentes(self):
        pasta = self.cap(1)
        self.cap(2)
        dados_obra.gravar(self.raiz / "Minha Obra", "Minha Obra", URL)
        historico.ARQUIVO.unlink()
        historico.salvar_posicao("Minha Obra/" + pasta.name, 3, 9, 0.2)
        self.assertEqual(historico.sincronizar_biblioteca(self.raiz), 1)
        f = self.ficha()
        self.assertEqual((f["baixado"], f["lido"], f["pos"]["p"], f["url"]), ("2", "1", 3, URL))
        self.assertEqual(historico.sincronizar_biblioteca(self.raiz), 0)              # repetir não duplica nem regrava

    def test_ruins_nao_quebram(self):
        self.assertFalse(historico.registrar_obra("", ""))
        self.assertFalse(historico.anotar_capitulo(self.dir / "nao-existe", baixado=True))
        self.assertFalse(historico.definir_situacao("Nada", "pausada"))


if __name__ == "__main__":
    unittest.main()


import json as _json
import shutil
import subprocess
import threading

from baixador.servidor.celular import ServidorCelular

NODE = shutil.which("node")
CLIENTE = Path(__file__).with_name("sincronia_cliente.mjs")
CHAVE = "chave-de-teste-1234567890"


class Fusao(Base):
    """Regras de junção de fichas (sem rede). Herda o setUp com arquivos temporários."""

    def ficha_de(self, **o):
        return {"nome": "Minha Obra", "url": URL, **o}

    def test_junta_campo_a_campo_sem_apagar(self):
        historico.registrar_obra("Minha Obra", URL, encontrado=50, baixado=10, conhecidos={"1": "u1", "2": "u2"})
        historico.mesclar({"obras": {"x": self.ficha_de(encontrado="30", baixado="12", traduzido="4", conhecidos="2-3", situacao="pausada", t_situacao=5000)}})
        f = self.ficha()
        self.assertEqual((f["encontrado"], f["baixado"], f["traduzido"], f["situacao"]), ("50", "12", "4", "pausada"))
        self.assertEqual((set(f["conhecidos"]), f["conhecidos"]["1"]), ({"1", "2", "3"}, "u1"))      # união; URL do notebook preservada
        self.assertEqual(len(historico.ler()["obras"]), 1)                                              # mesma obra: sem duplicata

    def test_situacao_e_leitura_mais_nova_vencem(self):
        agora = int(time.time() * 1000)
        historico.registrar_obra("Minha Obra", URL, lido=5, pos={"p": 2, "t": 9, "f": 0.5}, t=agora)
        historico.definir_situacao("Minha Obra", "pausada", agora)
        velha = self.ficha_de(lido="1", t_lido=agora - 9000, pos={"n": "1", "p": 1, "t": 3, "f": 0}, situacao="concluida", t_situacao=agora - 9000)
        historico.mesclar({"obras": {"x": velha}})
        f = self.ficha()
        self.assertEqual((f["lido"], f["pos"]["p"], f["situacao"]), ("5", 2, "pausada"))
        historico.mesclar({"obras": {"x": self.ficha_de(lido="7", t_lido=agora + 9, pos={"n": "7", "p": 3, "t": 8, "f": 0.1}, situacao="andamento", t_situacao=agora + 9)}})
        f = self.ficha()
        self.assertEqual((f["lido"], f["pos"]["p"], f["situacao"]), ("7", 3, "andamento"))

    def test_idempotente_e_sem_escrita_repetida(self):
        historico.registrar_obra("Minha Obra", URL, encontrado=5, conhecidos={"1": ""}, lido=2)
        ficha = historico.resumo()["obras"]
        antes = historico.ARQUIVO.read_text(encoding="utf-8")
        historico.mesclar({"obras": ficha})                                                              # o aparelho devolve o que recebeu
        self.assertEqual(historico.ARQUIVO.read_text(encoding="utf-8"), antes)                          # nada mudou: sem ciclo de regravação

    def test_lixo_na_rede_e_ignorado(self):
        antes = historico.ler()
        historico.mesclar({"obras": {"a": "texto", "b": {"nome": ""}, "c": {"nome": "X", "baixado": "abc", "situacao": "hack", "extra": "<script>", "conhecidos": "9999999-1,x"}}})
        obras = historico.ler()["obras"]
        self.assertEqual([f["nome"] for f in obras.values()], ["X"])
        f = next(iter(obras.values()))
        self.assertNotIn("extra", f)
        self.assertEqual((f.get("baixado"), f["situacao"], f["conhecidos"]), (None, "andamento", {}))
        self.assertEqual(antes["posicoes"], historico.ler()["posicoes"])

    def test_conhecidos_compactos_na_rede(self):
        historico.registrar_obra("Minha Obra", URL, conhecidos={str(n): "u" for n in range(1, 401)} | {"12.5": ""})
        self.assertEqual(historico.resumo()["obras"]["minhaobra"]["conhecidos"], "1-400,12.5")


@unittest.skipUnless(NODE, "precisa do node")
class SincroniaReal(Base):
    """Troca REAL: servidor do notebook (HTTP + chave) ↔ cliente JS do app (o mesmo sincronia.js), com desconexões e conflitos."""

    def setUp(self):
        super().setUp()
        self.rels = [criar(self.raiz, "Minha Obra", n, f"{n:08x}", preparado=False) for n in (1, 2, 3, 4)]
        acervo.esquecer_versao()
        dados_obra.gravar(self.raiz / "Minha Obra", "Minha Obra", URL)
        self.srv = ServidorCelular(self.raiz, CHAVE, 0, "127.0.0.1")
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.srv.shutdown(), self.srv.server_close()))
        self.base = f"http://127.0.0.1:{self.srv.porta}"
        self.fone = str(self.dir / "fone.json")

    def celular(self, acao, base=None, chave=CHAVE, **x):
        r = subprocess.run([NODE, str(CLIENTE), self.fone, base or self.base, chave, acao, _json.dumps(x)], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return _json.loads(r.stdout)

    def agora(self, delta=0):
        return int(time.time() * 1000) + delta

    def test_celular_para_notebook_e_de_volta(self):
        t = self.agora(-1000)
        self.celular("posicao", rel=self.rels[1], p=4, n=9, f=0.4, t=t)
        r = self.celular("sync")
        self.assertEqual(r["estados"][-2:], ["sincronizando", "sincronizado"])
        self.assertEqual(historico.ler()["posicoes"][self.rels[1]]["p"], 4)                             # celular → notebook (posição)
        f = self.ficha()
        self.assertEqual((f["lido"], f["pos"]["p"], f["pos"]["t"]), ("2", 4, 9))                      # …e a ficha da obra acompanhou
        self.assertEqual(r["hist"]["obras"]["minhaobra"]["lido"], "2")                                  # …voltou ao celular
        historico.anotar_capitulo(self.raiz / self.rels[2], lido=True, pos={"p": 1, "t": 5, "f": 0.1}, t=self.agora(1000))
        historico.salvar_posicao(self.rels[2], 1, 5, 0.1, self.agora(1000))
        historico.registrar_obra("Minha Obra", URL, encontrado=80, baixado=3, traduzido=2)
        r = self.celular("sync")                                                                         # notebook → celular
        o = r["hist"]["obras"]["minhaobra"]
        self.assertEqual((o["lido"], o["encontrado"], o["baixado"], o["traduzido"]), ("3", "80", "3", "2"))
        self.assertEqual(r["hist"]["posicoes"][self.rels[2]]["p"], 1)

    def test_conflito_o_mais_novo_vence_por_obra_e_capitulo(self):
        self.celular("posicao", rel=self.rels[0], p=2, n=9, f=0.2, t=self.agora(-5000))                # celular, offline, antigo
        historico.salvar_posicao(self.rels[3], 6, 9, 0.5, self.agora(-1000))                            # notebook, depois
        historico.anotar_capitulo(self.raiz / self.rels[3], lido=True, pos={"p": 6, "t": 9, "f": 0.5}, t=self.agora(-1000))
        r = self.celular("sync")
        self.assertEqual(self.ficha()["lido"], "4")                                                      # a leitura mais nova da obra é a do notebook
        self.assertEqual({k: v["p"] for k, v in historico.ler()["posicoes"].items()}, {self.rels[0]: 2, self.rels[3]: 6})   # por capítulo: as duas ficam
        self.assertEqual(r["hist"]["obras"]["minhaobra"]["lido"], "4")
        self.celular("posicao", rel=self.rels[0], p=9, n=9, f=1, t=self.agora(5000))                    # celular relê o cap 1, agora mais novo
        self.celular("sync")
        self.assertEqual((self.ficha()["lido"], historico.ler()["posicoes"][self.rels[0]]["p"]), ("1", 9))

    def test_desconexao_nao_perde_nem_corrompe_e_reconecta(self):
        self.celular("posicao", rel=self.rels[1], p=3, n=9, f=0.3, t=self.agora(-100))
        r = self.celular("sync", base="http://127.0.0.1:1")                                              # notebook fora do ar
        self.assertEqual((r["estados"][-1], bool(r["erro"])), ("aguardando", True))
        self.assertEqual(r["hist"]["posicoes"][self.rels[1]]["p"], 3)                                    # nada se perdeu no celular
        self.assertEqual(historico.ler()["obras"], {"minhaobra": historico.ler()["obras"]["minhaobra"]})
        self.assertNotIn(self.rels[1], historico.ler()["posicoes"])
        r = self.celular("sync", cortar=True)                                                            # envio interrompido no meio
        self.assertTrue(r["erro"])
        self.assertNotIn(self.rels[1], historico.ler()["posicoes"])                                      # nada pela metade no notebook
        self.assertEqual(self.celular("ler")["hist"]["posicoes"][self.rels[1]]["p"], 3)
        self.celular("sync")                                                                             # volta a conexão: a alteração pendente chega
        self.assertEqual(historico.ler()["posicoes"][self.rels[1]]["p"], 3)

    def test_obra_removida_da_biblioteca_continua_no_historico_dos_dois_lados(self):
        historico.registrar_obra("Minha Obra", URL, baixado=4, traduzido=4, lido=4, encontrado=90, t=self.agora(-100))
        self.celular("sync")
        acervo.excluir_obra(self.raiz, "Minha Obra")
        acervo.esquecer_versao()
        self.celular("posicao", rel=self.rels[0], p=1, n=3, f=0.5, t=self.agora(100))                   # celular ainda lê a cópia baixada
        r = self.celular("sync")
        self.assertEqual(historico.ler()["obras"]["minhaobra"]["baixado"], "4")                          # ficha do notebook sobreviveu e não foi alterada por rel sem pasta
        self.assertEqual(r["hist"]["obras"]["minhaobra"]["encontrado"], "90")
        self.assertEqual(historico.ler()["posicoes"][self.rels[0]]["p"], 1)                              # a posição do celular não se perde

    def test_celular_altera_situacao_e_notebook_responde_sem_ciclo(self):
        historico.registrar_obra("Minha Obra", URL, baixado=1)
        self.celular("sync")
        self.celular("situacao", id="minhaobra", situacao="pausada", t=self.agora(500))
        self.celular("sync")
        self.assertEqual(self.ficha()["situacao"], "pausada")
        antes = historico.ARQUIVO.read_text(encoding="utf-8")
        for _ in range(3):
            self.celular("sync")
        self.assertEqual(historico.ARQUIVO.read_text(encoding="utf-8"), antes)                           # repetir não muda nada
        self.assertEqual(self.celular("ler")["hist"]["obras"]["minhaobra"]["situacao"], "pausada")

    def test_sem_chave_certa_nada_entra_nem_sai(self):
        self.celular("posicao", rel=self.rels[0], p=2, n=9, f=0.2, t=self.agora(-100))
        r = self.celular("sync", chave="errada")
        self.assertIn("401", r["erro"])
        self.assertEqual(historico.ler()["posicoes"], {})
        self.assertEqual(r["hist"]["obras"], {})
