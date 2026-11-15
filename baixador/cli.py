"""Interface de linha de comando."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from baixador.nucleo.erros import ErroBaixador


def _criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m baixador",
        description="Baixador de Imagens: abre o app (Baixar, Biblioteca e Celular) no navegador. Sem opções, só isso.",
    )
    parser.add_argument(
        "--sem-navegador", action="store_true",
        help="não abre o navegador sozinho (o endereço aparece no terminal)",
    )
    parser.add_argument(
        "--traduzir", metavar="PASTA",
        help="traduz as imagens da PASTA (um capítulo) com o motor escolhido na aba Traduções; o resultado fica na própria pasta",
    )
    parser.add_argument(
        "--apagar-perfil", action="store_true",
        help="apaga o perfil próprio do navegador (extensões, logins e configurações guardados)",
    )
    return parser


def principal(argv: Optional[List[str]] = None) -> int:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(errors="replace")  # evita travar em consoles sem UTF-8
        except AttributeError:
            pass

    args = _criar_parser().parse_args(argv)
    if args.traduzir:
        from baixador.traducao import executor  # só carrega se for usado

        try:
            r = executor.traduzir_pasta_cli(Path(args.traduzir).expanduser(), informar=print)
        except ErroBaixador as erro:
            print(f"Erro: {erro}", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print("\nInterrompido.", file=sys.stderr)
            return 130
        print(f"\nConcluído: {r['falas']} fala(s) traduzida(s). Para ler: abra o programa (python -m baixador) e use a Biblioteca.")
        return 0
    if args.apagar_perfil:
        from baixador.navegador import navegadores

        pasta = navegadores.pasta_perfis()
        resposta = input(f"Apagar {pasta} (extensões e logins guardados)? [s/N] ").strip().lower()
        if resposta not in ("s", "sim"):
            print("Nada foi apagado.")
            return 0
        try:
            navegadores.apagar_perfis()
        except OSError as erro:
            print(f"Não foi possível apagar: {erro} (feche o navegador aberto pelo programa e tente de novo).")
            return 1
        print("Perfil apagado.")
        return 0
    from baixador.servidor.notebook import abrir_interface  # só carrega o servidor local se for usado

    return abrir_interface(abrir_navegador=not args.sem_navegador)
