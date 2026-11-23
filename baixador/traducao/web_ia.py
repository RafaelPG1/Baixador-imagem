"""Tradução com IA na web (ChatGPT, Gemini, Claude...), feita à mão: sem API, sem chave e sem modelo local.

Fluxo: o motor "web" do tradutor (Node) lê as falas de cada capítulo e grava `traducao.nova/web/textos.json`; aqui os textos viram
TXT (um arquivo ou vários) para copiar/baixar; a tradução que volta é validada e gravada em `traducao.nova/web/importadas.json`;
quando todas as falas de um capítulo têm tradução, o tradutor termina o capítulo (limpeza, leitor).

Cada linha exportada é `[codigo:id] texto`. `codigo` (8 hex) identifica o capítulo, `id` a fala (página e balão). A associação é SEMPRE
por esse par, nunca pela ordem. Uma tradução só vale se o texto original da fala ainda for o mesmo (hash).
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import unicodedata
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from baixador.biblioteca import organizacao as org
from baixador.biblioteca.capitulo import _subpastas

LIMITE_PADRAO = 12000                    # caracteres de texto por arquivo quando a exportação é dividida
LIMITE_MINIMO, LIMITE_MAXIMO = 2000, 100000
MAX_IMPORTACAO = 8 * 1024 * 1024
_CODIGO = re.compile(r"^[0-9a-f]{8}$")
_LINHA = re.compile(r"^\[\s*([0-9A-Fa-f]{8})\s*:\s*([A-Za-z0-9_.-]{1,40})\s*\]\s*(.*)$")
_ENFEITE = re.compile(r"^[\s>*\-•`_\d.)]*$")          # o que uma IA costuma pôr antes do [id]: marcador de lista, negrito, número
_DIVISOR = re.compile(r"^(?:`{3}.*|[-=_*#\s]{3,})$")  # cerca de código ou linha divisória: não conta como conteúdo

INTRODUCAO = """Você é tradutor profissional de mangá, manhwa e quadrinhos. Traduza as falas abaixo do inglês para o português brasileiro (PT-BR).

Cada linha tem o formato:
[IDENTIFICADOR] texto em inglês

Regras:
1. Traduza para português brasileiro (PT-BR), com linguagem natural de quadrinhos.
2. Preserve o contexto e o sentido original. Use as falas vizinhas para entender quem fala e o tom.
3. Não resuma, não omita e não acrescente informações, explicações ou comentários.
4. Mantenha TODOS os identificadores entre colchetes exatamente como estão: não altere, não traduza, não renumere e não remova.
5. Preserve a estrutura: uma linha de saída para cada linha de entrada, na mesma ordem, no formato [IDENTIFICADOR] tradução. Não una nem divida linhas.
6. Retorne somente o resultado traduzido: sem introdução, sem despedida, sem comentários, sem blocos de código e sem markdown.

Textos a traduzir (começam na próxima linha):"""


# --------------------------------------------------------------------------- arquivos do capítulo

def _dir_web(pasta: Path) -> Path:
    return Path(pasta) / "traducao.nova" / "web"


def _json(arquivo: Path) -> Any:
    try:
        return json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def ler_textos(pasta: Path) -> Optional[Dict[str, Any]]:
    """`textos.json` do capítulo, só se estiver no formato esperado (o arquivo é dado, não é confiável)."""
    d = _json(_dir_web(pasta) / "textos.json")
    if not isinstance(d, dict) or not isinstance(d.get("codigo"), str) or not _CODIGO.match(d["codigo"]) or not isinstance(d.get("unidades"), list):
        return None
    unidades = [u for u in d["unidades"] if isinstance(u, dict) and all(isinstance(u.get(k), str) for k in ("id", "fonte", "hash")) and _LINHA.match(f"[{d['codigo']}:{u['id']}]")]
    if len(unidades) != len(d["unidades"]):
        return None
    return {"codigo": d["codigo"], "unidades": unidades}


def ler_importadas(pasta: Path, textos: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """Traduções já importadas que ainda valem (mesmo código e mesmo texto original)."""
    d = _json(_dir_web(pasta) / "importadas.json")
    if not isinstance(d, dict) or d.get("codigo") != textos["codigo"] or not isinstance(d.get("traducoes"), dict):
        return {}
    hashes = {u["id"]: u["hash"] for u in textos["unidades"]}
    return {i: r for i, r in d["traducoes"].items() if isinstance(r, dict) and isinstance(r.get("t"), str) and r["t"].strip() and r.get("h") == hashes.get(i)}


def _capitulos_da_biblioteca(raiz: Path) -> List[Dict[str, Any]]:
    """Capítulos (pastas `Obra/Cap`) que têm textos preparados para a IA na web."""
    achados = []
    for obra in _subpastas(Path(raiz)):
        for cap in _subpastas(obra):
            textos = ler_textos(cap)
            if textos:
                d = org.descrever_capitulo(cap, obra.name)
                achados.append({"pasta": cap, "rel": f"{obra.name}/{cap.name}", "obra": d["obra"] or obra.name, "numero": d["numero"], "titulo": d["titulo"], "textos": textos})
    return achados


def _ordem(c: Dict[str, Any]) -> tuple:
    return org.chave_ordem(c["numero"], c["titulo"])


def estado_dos_capitulos(raiz: Path, obra: str) -> List[Dict[str, Any]]:
    """Para a janela da obra: cada capítulo preparado, com quantos textos tem e quantos já foram importados."""
    chave = org._chave(obra)
    saida = []
    for c in sorted((c for c in _capitulos_da_biblioteca(raiz) if org._chave(c["obra"]) == chave), key=_ordem):
        n, feitas = len(c["textos"]["unidades"]), len(ler_importadas(c["pasta"], c["textos"]))
        saida.append({"rel": c["rel"], "rotulo": org.rotulo_capitulo(c["numero"], c["titulo"]), "textos": n, "importados": feitas, "completo": feitas == n})
    return saida


# --------------------------------------------------------------------------- exportar

def _nome_seguro(texto: str) -> str:
    s = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()[:40] or "obra"


def exportar(raiz: Path, obra: str, rels: Iterable[str], introducao: bool = True, dividir: bool = False, limite: int = LIMITE_PADRAO) -> List[Dict[str, Any]]:
    """TXT(s) com as falas dos capítulos pedidos (só os que têm textos preparados). Devolve [{nome, conteudo, textos, capitulos, caracteres}]."""
    pedidos = set(rels)
    chave = org._chave(obra)
    caps = sorted((c for c in _capitulos_da_biblioteca(raiz) if c["rel"] in pedidos and org._chave(c["obra"]) == chave), key=_ordem)
    if not caps:
        raise ValueError("Nenhum dos capítulos escolhidos tem textos preparados. Use “Preparar textos” antes de exportar.")
    linhas = [(f"[{c['textos']['codigo']}:{u['id']}] {u['fonte']}", c["rel"]) for c in caps for u in c["textos"]["unidades"]]
    if not linhas:
        raise ValueError("Os capítulos escolhidos não têm nenhuma fala com texto para traduzir.")
    limite = max(LIMITE_MINIMO, min(LIMITE_MAXIMO, int(limite or LIMITE_PADRAO)))
    partes: List[List[tuple]] = [[]]
    if not dividir:
        partes[0] = linhas
    else:
        usado = 0
        for item in linhas:
            if partes[-1] and usado + len(item[0]) + 1 > limite:
                partes.append([]); usado = 0
            partes[-1].append(item); usado += len(item[0]) + 1
    base, saida = _nome_seguro(obra), []
    for i, parte in enumerate(partes, 1):
        corpo = "\n".join(l for l, _ in parte) + "\n"
        cabeca = ""
        if introducao:
            cabeca = INTRODUCAO + ("\n" if len(partes) == 1 else f"\n(Esta é a parte {i} de {len(partes)}; traduza só as linhas desta parte.)\n") + "\n"
        nome = f"{base}.txt" if len(partes) == 1 else f"{base}-parte-{i:02d}-de-{len(partes):02d}.txt"
        saida.append({"nome": nome, "conteudo": cabeca + corpo, "textos": len(parte), "capitulos": len({r for _, r in parte}), "caracteres": len(cabeca + corpo)})
    return saida


def zip_dos_arquivos(arquivos: List[Dict[str, Any]], pasta: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for a in arquivos:
            z.writestr(f"{pasta}/{a['nome']}", a["conteudo"])
    return buf.getvalue()


# --------------------------------------------------------------------------- importar

def _ler_linha(s: str) -> Optional[tuple]:
    """(codigo, id, texto) de uma linha `[codigo:id] texto`, tolerando enfeites de markdown antes e `**` em volta."""
    s = s.replace("\\[", "[").replace("\\]", "]")
    k = s.find("[")
    if k < 0 or not _ENFEITE.match(s[:k]):
        return None
    m = _LINHA.match(s[k:])
    if not m:
        return None
    texto = m.group(3).strip()
    if "**" in s[:k] and texto.endswith("**"):
        texto = texto[:-2].rstrip()
    return m.group(1).lower(), m.group(2), " ".join(texto.split())


def _amostra(itens: Iterable[str], n: int = 12) -> List[str]:
    lista = list(itens)
    return lista[:n] + ([f"… e mais {len(lista) - n}"] if len(lista) > n else [])


def analisar(raiz: Path, conteudos: List[str]) -> Dict[str, Any]:
    """Confere o texto colado/lido contra os textos exportados. Não grava nada.

    Uma tradução é ACEITA só se: o código é de um capítulo preparado, o id existe nele, o texto não está vazio, a linha não foi
    quebrada, e o id não aparece duas vezes com traduções diferentes. Tudo o mais é relatado e ignorado."""
    registros, estranhas = [], []
    for conteudo in conteudos:
        anterior = None
        for n, bruta in enumerate(str(conteudo).splitlines(), 1):
            s = bruta.strip()
            if not s or _DIVISOR.match(s):
                anterior = None
                continue
            lida = _ler_linha(s)
            if lida:
                anterior = {"codigo": lida[0], "id": lida[1], "texto": lida[2], "linha": n, "quebrada": False}
                registros.append(anterior)
            elif anterior is not None:
                anterior["quebrada"] = True                    # texto solto colado logo abaixo de uma fala: estrutura alterada
            else:
                estranhas.append(s[:80])
    por_codigo = {c["textos"]["codigo"]: c for c in _capitulos_da_biblioteca(raiz)}
    codigos_desconhecidos = sorted({r["codigo"] for r in registros if r["codigo"] not in por_codigo})
    capitulos: Dict[str, Dict[str, Any]] = {}
    for codigo, cap in por_codigo.items():
        esperados = {u["id"]: u for u in cap["textos"]["unidades"]}
        deles = [r for r in registros if r["codigo"] == codigo]
        if not deles:
            continue
        ja = ler_importadas(cap["pasta"], cap["textos"])
        ocorrencias: Dict[str, List[Dict[str, Any]]] = {}
        for r in deles:
            ocorrencias.setdefault(r["id"], []).append(r)
        novas, desconhecidos, duplicados, quebrados, vazios, repetidos_iguais = {}, [], [], [], [], 0
        for i, rs in ocorrencias.items():
            if i not in esperados:
                desconhecidos.append(i); continue
            if len({r["texto"] for r in rs}) > 1:
                duplicados.append(i); continue                 # duas traduções diferentes para a mesma fala: não dá para escolher
            repetidos_iguais += len(rs) - 1
            if any(r["quebrada"] for r in rs):
                quebrados.append(i); continue
            if not rs[0]["texto"]:
                vazios.append(i); continue
            if ja.get(i, {}).get("t") == rs[0]["texto"]:
                continue                                       # já importada igual: não conta de novo
            novas[i] = {"t": rs[0]["texto"], "h": esperados[i]["hash"]}
        cobertos = set(ja) | set(novas)
        faltam = [i for i in esperados if i not in cobertos]
        capitulos[cap["rel"]] = {
            "rel": cap["rel"], "rotulo": org.rotulo_capitulo(cap["numero"], cap["titulo"]), "esperados": len(esperados), "ja_importados": len(ja), "novas": len(novas),
            "faltam": faltam, "desconhecidos": desconhecidos, "duplicados": duplicados, "quebrados": quebrados, "vazios": vazios, "repetidos_iguais": repetidos_iguais,
            "completo": not faltam, "_novas": novas, "_pasta": cap["pasta"], "_textos": cap["textos"],
        }
    return {"capitulos": capitulos, "linhas": len(registros), "linhas_fora_da_estrutura": _amostra(estranhas), "total_fora": len(estranhas), "codigos_desconhecidos": codigos_desconhecidos}


def gravar(analise: Dict[str, Any]) -> List[str]:
    """Grava as traduções aceitas (somando às já importadas). Devolve os `rel` dos capítulos que ficaram completos."""
    completos = []
    for c in analise["capitulos"].values():
        pasta, textos = c["_pasta"], c["_textos"]
        if c["novas"]:
            todas = {**ler_importadas(pasta, textos), **c["_novas"]}
            alvo = _dir_web(pasta) / "importadas.json"
            tmp = alvo.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"versao": 1, "codigo": textos["codigo"], "traducoes": todas}, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, alvo)
            shutil.rmtree(Path(pasta) / "traducao.nova" / "etapa4b", ignore_errors=True)   # a etapa de tradução precisa refazer com o que chegou
        if c["completo"]:
            completos.append(c["rel"])
    return completos


def relatorio(analise: Dict[str, Any]) -> Dict[str, Any]:
    """A análise sem os campos internos, pronta para JSON."""
    caps = [{k: (_amostra(v) if k in ("faltam", "desconhecidos", "duplicados", "quebrados", "vazios") else v) for k, v in c.items() if not k.startswith("_")} | {"qtd_faltam": len(c["faltam"])}
            for c in analise["capitulos"].values()]
    return {"capitulos": caps, "linhas": analise["linhas"], "linhas_fora_da_estrutura": analise["linhas_fora_da_estrutura"], "total_fora": analise["total_fora"], "codigos_desconhecidos": analise["codigos_desconhecidos"]}
