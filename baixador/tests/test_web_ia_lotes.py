"""IA web: ids ausentes, importação parcial, sem duplicar capítulos, vários capítulos/lotes sem mistura, mesma obra por preparação."""
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from baixador.biblioteca import acervo
from baixador.servidor.notebook import Manipulador
from baixador.traducao import executor, web_ia


def _png() -> bytes:
    def bloco(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    return b"\x89PNG\r\n\x1a\n" + bloco(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + bloco(b"IDAT", zlib.compress(b"\x00\xff\xff\xff")) + bloco(b"IEND", b"")


def criar(raiz: Path, obra: str, numero: int, codigo: str, n: int = 20, preparado: bool = True) -> str:
    pasta = raiz / obra / f"Capitulo {numero}"
    (pasta / "img").mkdir(parents=True, exist_ok=True)
    (pasta / "img" / "001.png").write_bytes(_png())
    if preparado:
        _textos(pasta, numero, codigo, n)
    acervo.esquecer_versao()
    return f"{obra}/Capitulo {numero}"


def _textos(pasta: Path, numero: int, codigo: str, n: int = 20) -> None:
    web = pasta / "traducao.nova" / "web"
    web.mkdir(parents=True)
    unidades = [{"id": f"p{i:03d}-b1", "fonte": f"Hello {numero}-{i}", "hash": f"h{codigo}{i}"} for i in range(1, n + 1)]
    (web / "textos.json").write_text(json.dumps({"codigo": codigo, "unidades": unidades}), encoding="utf-8")


def linhas(codigo: str, numero: int, ids, prefixo="PT") -> str:
    return "\n".join(f"[{codigo}:p{i:03d}-b1] {prefixo} {numero}-{i}" for i in ids)


class IaWeb(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.raiz = Path(self._t.name)
        self.addCleanup(self._t.cleanup)
        self.c1 = criar(self.raiz, "Obra A", 1, "aaaaaaa1")
        self.c2 = criar(self.raiz, "Obra A", 2, "aaaaaaa2")
        self.c3 = criar(self.raiz, "Obra A", 3, "aaaaaaa3")

    # 1, 2, 3, 10
    def test_varios_capitulos_na_mesma_colagem_sem_mistura(self):
        misturado = "\n".join(sum(([linhas("aaaaaaa2", 2, [i]), linhas("aaaaaaa1", 1, [i]), linhas("aaaaaaa3", 3, [i])] for i in range(20, 0, -1)), []))
        a = web_ia.analisar(self.raiz, [misturado])
        self.assertEqual({c["rel"] for c in a["capitulos"].values() if c["completo"]}, {self.c1, self.c2, self.c3})
        self.assertEqual(web_ia.gravar(a).sort() or 0, 0)
        for numero, rel in ((1, self.c1), (2, self.c2), (3, self.c3)):
            pasta = self.raiz / rel
            imp = web_ia.ler_importadas(pasta, web_ia.ler_textos(pasta))
            self.assertEqual(len(imp), 20)
            self.assertTrue(all(v["t"].startswith(f"PT {numero}-") for v in imp.values()), "tradução de outro capítulo")

    def test_id_de_um_capitulo_com_codigo_de_outro_nao_entra(self):
        a = web_ia.analisar(self.raiz, [linhas("aaaaaaa1", 1, range(1, 21)) + "\n[aaaaaaa2:p999-b1] x"])
        self.assertEqual(a["capitulos"][self.c1]["novas"], 20)
        self.assertEqual(a["capitulos"][self.c2]["desconhecidos"], ["p999-b1"])
        self.assertEqual(a["capitulos"][self.c2]["novas"], 0)

    def test_codigo_repetido_em_dois_capitulos_nao_importa_nada(self):
        criar(self.raiz, "Obra A", 4, "aaaaaaa1")
        a = web_ia.analisar(self.raiz, [linhas("aaaaaaa1", 1, range(1, 21))])
        self.assertEqual(a["capitulos"], {})
        self.assertEqual(sorted(a["codigos_ambiguos"]["aaaaaaa1"]), ["Obra A/Capitulo 1", "Obra A/Capitulo 4"])

    # 5, 6
    def test_ausentes_exatos_e_importacao_parcial_depois_completa(self):
        faltam = [3, 7, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]                     # 12 ausentes: mais que a amostra antiga
        ids = [i for i in range(1, 21) if i not in faltam]
        a = web_ia.analisar(self.raiz, [linhas("aaaaaaa1", 1, ids) + "\n" + linhas("aaaaaaa1", 1, [3]).replace("PT 1-3", "")])  # linha vazia do id 3
        c = web_ia.relatorio(a)["capitulos"][0]
        self.assertEqual(c["ausentes"], [f"[aaaaaaa1:p{i:03d}-b1]" for i in faltam])
        self.assertEqual(c["vazios"], ["p003-b1"])
        self.assertIn("20 identificadores esperados", c["mensagem"])
        self.assertIn("8 traduções válidas", c["mensagem"])
        self.assertIn("12 identificador(es) ausente(s)", c["mensagem"])
        self.assertEqual(web_ia.gravar(a), [], "capítulo parcial não é concluído")
        pasta = self.raiz / self.c1
        self.assertEqual(len(web_ia.ler_importadas(pasta, web_ia.ler_textos(pasta))), 8)
        self.assertEqual([c["situacao"] for c in web_ia.estado_dos_capitulos(self.raiz, "Obra A")], ["parcial", "preparado", "preparado"])
        # depois: só as que faltaram, mais uma tradução DIFERENTE de uma já importada (não pode sobrescrever)
        b = web_ia.analisar(self.raiz, [linhas("aaaaaaa1", 1, faltam) + "\n[aaaaaaa1:p001-b1] OUTRA"])
        r = b["capitulos"][self.c1]
        self.assertEqual((r["novas"], r["mantidas"], r["completo"]), (12, ["p001-b1"], True))
        self.assertEqual(web_ia.gravar(b), [self.c1])
        imp = web_ia.ler_importadas(pasta, web_ia.ler_textos(pasta))
        self.assertEqual((len(imp), imp["p001-b1"]["t"]), (20, "PT 1-1"))

    def test_duplicado_com_textos_diferentes_e_id_modificado(self):
        a = web_ia.analisar(self.raiz, [linhas("aaaaaaa1", 1, range(1, 19)) + "\n[aaaaaaa1:p019-b1] A\n[aaaaaaa1:p019-b1] B\n[aaaaaaa1:p020-bX] Z"])
        c = a["capitulos"][self.c1]
        self.assertEqual((c["duplicados"], c["desconhecidos"], c["faltam"]), (["p019-b1"], ["p020-bX"], ["p019-b1", "p020-b1"]))

    # 9
    def test_situacoes(self):
        web_ia.gravar(web_ia.analisar(self.raiz, [linhas("aaaaaaa2", 2, range(1, 21)), linhas("aaaaaaa3", 3, range(1, 5))]))
        self.assertEqual([c["situacao"] for c in web_ia.estado_dos_capitulos(self.raiz, "Obra A")], ["preparado", "completo", "parcial"])

    # 8
    def test_mesma_obra(self):
        self.assertIsNone(web_ia.conferir_mesma_obra(["Obra A/Capitulo 4"], ["Obra A/Capitulo 1"]))
        self.assertIn("misturar obras", web_ia.conferir_mesma_obra(["Obra B/Capitulo 1"], ["Obra A/Capitulo 1"]))
        self.assertIn("misturar obras", web_ia.conferir_mesma_obra(["Obra B/Capitulo 1", "Obra A/Capitulo 4"], []))


class Fila(unittest.TestCase):
    """Executor + rota /api/traduzir (a mesma que o servidor usa), com o Node trocado por um dublê."""

    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.raiz = Path(self._t.name)
        self.addCleanup(self._t.cleanup)
        self.rels = {n: criar(self.raiz, "Obra A", n, f"aaaaaaa{n}", preparado=False) for n in (1, 2, 3, 4, 5)}
        self.b1 = criar(self.raiz, "Obra B", 1, "bbbbbbb1", preparado=False)
        self.tarefa = executor.TarefaTraducao()
        self.chamadas = []
        for p in (mock.patch.object(executor, "disponibilidade", return_value={"pronto": True}), mock.patch.object(executor, "ambiente_do_node", return_value={}),
                  mock.patch.object(executor.config, "ler", return_value={"motor": "web"}), mock.patch.object(self.tarefa, "_liberar"),
                  mock.patch.object(self.tarefa, "_capitulo", side_effect=self._capitulo)):
            p.start(); self.addCleanup(p.stop)
        self.stub = SimpleNamespace(server=SimpleNamespace(raiz=self.raiz, traducao=self.tarefa), respostas=[])
        self.stub._negar = lambda cod, msg: self.stub.respostas.append((cod, msg))
        self.stub._json = lambda cod, d: self.stub.respostas.append((cod, d))

    def _capitulo(self, indice, pasta, env):
        self.chamadas.append(pasta.name)
        if web_ia.ler_textos(pasta) is None:                                                  # o Node prepararia os textos aqui
            _textos(pasta, int(pasta.name.split()[-1]), ("bbbbbbb" if "B" in pasta.parent.name else "aaaaaaa") + pasta.name.split()[-1])
        concluido = web_ia.ler_importadas(pasta, web_ia.ler_textos(pasta)) and len(web_ia.ler_importadas(pasta, web_ia.ler_textos(pasta))) == 20
        return ("pronto", {}) if concluido else ("aguardando", {"textos": 20})

    def preparar(self, *rels):
        self.stub.respostas.clear()
        Manipulador._traduzir(self.stub, {"motor": "web", "rels": list(rels)})
        t = self.tarefa._thread
        if t:
            t.join(10)
        return self.stub.respostas[-1]

    def rels_itens(self):
        return [i["rel"] for i in self.tarefa.itens]

    # 1, 7
    def test_preparar_varios_e_adicionar_mais_sem_perder_nem_refazer(self):
        self.assertEqual(self.preparar(*[self.rels[n] for n in (1, 2, 3)])[0], 200)
        self.assertEqual(self.rels_itens(), [self.rels[n] for n in (1, 2, 3)])
        self.chamadas.clear()
        self.assertEqual(self.preparar(self.rels[4], self.rels[5], self.rels[2])[0], 200)      # 2 já preparado: não volta à fila
        self.assertEqual(self.rels_itens(), [self.rels[n] for n in (1, 2, 3, 4, 5)])
        self.assertEqual(self.chamadas, ["Capitulo 4", "Capitulo 5"])
        self.assertEqual({i["estado"] for i in self.tarefa.itens}, {"aguardando"})

    # 8
    def test_outra_obra_bloqueada_no_servidor_sem_mexer_em_nada(self):
        self.preparar(self.rels[1])
        antes = [dict(i) for i in self.tarefa.itens]
        cod, msg = self.preparar(self.b1)
        self.assertEqual(cod, 422)
        self.assertIn("misturar obras", msg)
        self.assertEqual(self.tarefa.itens, antes)
        cod, msg = self.preparar(self.rels[4], self.b1)                                       # mistura no mesmo pedido
        self.assertEqual(cod, 422)
        self.assertEqual(self.tarefa.itens, antes)
        self.assertFalse((self.raiz / self.rels[4] / "traducao.nova").exists(), "nada foi preparado")

    def test_outra_obra_bloqueada_mesmo_depois_de_reiniciar_o_programa(self):
        self.preparar(self.rels[1])
        self.tarefa.itens, self.tarefa._pastas = [], []                                       # memória perdida: o disco ainda tem os textos
        self.assertEqual(self.preparar(self.b1)[0], 422)

    # 3, 4, 7 (causa da duplicação)
    def test_importar_atualiza_o_registro_original_sem_duplicar(self):
        self.preparar(*[self.rels[n] for n in (1, 2, 3)])
        self.assertEqual(self.tarefa.estado, "concluido")                                       # lote terminou: só "aguardando"
        a = web_ia.analisar(self.raiz, [linhas("aaaaaaa1", 1, range(1, 21))])
        completos = web_ia.gravar(a)
        self.chamadas.clear()
        self.assertEqual(self.tarefa.iniciar_ou_enfileirar_web([self.raiz / r for r in completos]), 1)
        self.tarefa._thread.join(10)
        self.assertEqual(self.rels_itens(), [self.rels[n] for n in (1, 2, 3)], "nenhuma entrada nova nem reordenada")
        self.assertEqual([i["estado"] for i in self.tarefa.itens], ["pronto", "aguardando", "aguardando"])
        self.assertEqual(self.chamadas, ["Capitulo 1"], "só o capítulo importado é processado")
        self.assertEqual(self.tarefa.aguardando, 2)

    def test_importar_durante_preparacao_nao_duplica_item_em_fila(self):
        t = self.tarefa
        with t._lock:
            t.estado, t._cfg, t._fechada = "executando", {"motor": "web"}, False
            t.itens = [{"nome": "x", "rel": self.rels[n], "estado": e, "etapa": "", "feitas": 0, "total": 1} for n, e in ((1, "aguardando"), (2, "fila"), (3, "fila"))]
            t._pastas = [self.raiz / self.rels[n] for n in (1, 2, 3)]
            t.aguardando, t.capitulos = 1, 2
        t.iniciar_ou_enfileirar_web([self.raiz / self.rels[1], self.raiz / self.rels[3]])
        self.assertEqual(len(t.itens), 3)
        self.assertEqual([(i["estado"], bool(i.get("prio"))) for i in t.itens], [("fila", True), ("fila", False), ("fila", True)])
        self.assertEqual((t.aguardando, t.capitulos), (0, 3))

    def test_cap_parcial_nao_e_enfileirado_e_outro_capitulo_nao_e_afetado(self):
        self.preparar(*[self.rels[n] for n in (1, 2)])
        a = web_ia.analisar(self.raiz, [linhas("aaaaaaa1", 1, range(1, 20)) + "\n" + linhas("aaaaaaa2", 2, range(1, 21))])
        self.assertEqual(web_ia.gravar(a), [self.rels[2]])
        self.tarefa.iniciar_ou_enfileirar_web([self.raiz / self.rels[2]])
        self.tarefa._thread.join(10)
        self.assertEqual([i["estado"] for i in self.tarefa.itens], ["aguardando", "pronto"])
        self.assertEqual(len(web_ia.ler_importadas(self.raiz / self.rels[1], web_ia.ler_textos(self.raiz / self.rels[1]))), 19)


if __name__ == "__main__":
    unittest.main()
