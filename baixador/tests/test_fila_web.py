"""Traduções importadas furam a fila de preparação do lote, sem interromper o capítulo que está sendo preparado."""
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from baixador.traducao import executor


class FilaWeb(unittest.TestCase):
    def test_importado_roda_antes_dos_que_ainda_nao_foram_preparados(self):
        ordem, solta, comecou = [], threading.Event(), threading.Event()
        t = executor.TarefaTraducao()

        def capitulo(indice, pasta, env):
            ordem.append(pasta.name)
            if pasta.name == "c3":                                   # primeiro capítulo do lote ainda em preparação
                comecou.set()
                solta.wait(5)
            return ("aguardando", {"textos": 1}) if pasta.name.startswith("c") else ("pronto", {})

        pastas = [Path("/x/obra") / n for n in ("c3", "c4", "c5", "c6")]
        with mock.patch.object(executor, "disponibilidade", return_value={"pronto": True}), \
                mock.patch.object(executor, "ambiente_do_node", return_value={"TRANSLATION_ENGINE": "web"}), \
                mock.patch.object(t, "_capitulo", side_effect=capitulo), mock.patch.object(t, "_liberar"):
            t.iniciar_lote(pastas, cfg={"motor": "web"})
            self.assertTrue(comecou.wait(5))
            # c1 e c2 já estavam preparados; a tradução deles chega com c3 ainda rodando e c4..c6 na fila
            self.assertEqual(t.iniciar_ou_enfileirar_web([Path("/x/obra/p1"), Path("/x/obra/p2")]), 2)
            solta.set()
            t._thread.join(10)
        self.assertEqual(ordem, ["c3", "p1", "p2", "c4", "c5", "c6"])
        self.assertEqual(len(ordem), len(set(ordem)), "ninguém roda duas vezes")


if __name__ == "__main__":
    unittest.main()
