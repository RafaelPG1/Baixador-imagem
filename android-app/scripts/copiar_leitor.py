"""Copia o leitor da web (web/leitor) para o app, para os dois lerem do MESMO jeito (botões, atalhos, barra de progresso).

Roda antes de `npx cap sync android` (o fluxo do GitHub já faz isso). Gera em www/: leitor.html, leitor.js, leitor.css.
Esses três arquivos são cópias: não edite aqui, edite em web/leitor/ (ficam fora do Git, ver .gitignore).
O que é específico do app (ler online com a chave, ler as obras baixadas, links) fica em www/leitor-app.js, que entra
ANTES do leitor.js.
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
ORIGEM = RAIZ / "web" / "leitor"
DESTINO = Path(__file__).resolve().parent.parent / "www"


def trocar(texto: str, antigo: str, novo: str) -> str:
    if texto.count(antigo) != 1:
        sys.exit(f"ERRO: o leitor da web mudou; não achei (ou achei mais de um) trecho esperado: {antigo!r}")
    return texto.replace(antigo, novo)


def main() -> None:
    html = (ORIGEM / "leitor.html").read_text(encoding="utf-8")
    html = trocar(html, 'href="/estatico/leitor.css"', 'href="leitor.css"')
    html = trocar(html, '<script src="/estatico/leitor.js"></script>', '<script src="leitor-app.js"></script>\n<script src="leitor.js"></script>')
    (DESTINO / "leitor.html").write_text(html, encoding="utf-8")
    for nome in ("leitor.js", "leitor.css"):
        (DESTINO / nome).write_text((ORIGEM / nome).read_text(encoding="utf-8"), encoding="utf-8")
    print("Leitor da web copiado para o app: leitor.html, leitor.js, leitor.css.")


if __name__ == "__main__":
    main()
