"""Tradução com IA na web (ChatGPT, Gemini, Claude...), feita à mão: sem API, sem chave e sem modelo local.

Fluxo: o motor "web" do tradutor (Node) lê as falas de cada capítulo e grava `traducao.nova/web/textos.json`; aqui os textos viram
TXT (um arquivo ou vários) para copiar/baixar; a tradução que volta é validada e gravada em `traducao.nova/web/importadas.json`;
quando todas as falas de um capítulo têm tradução, o tradutor termina o capítulo (limpeza, leitor).

Cada linha exportada é `[codigo:id] texto`. `codigo` (8 hex) identifica o capítulo, `id` a fala (página e balão). A associação é SEMPRE
por esse par, nunca pela ordem. Uma tradução só vale se o texto original da fala ainda for o mesmo (hash).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import threading
import unicodedata
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from baixador.biblioteca import acervo, capitulo
from baixador.biblioteca import organizacao as org
from baixador.biblioteca.capitulo import _subpastas
from baixador.nucleo.erros import ErroBaixador
from baixador.traducao import edicoes

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


_CACHE: Dict[tuple, Any] = {}


def _lembrar(chave: tuple, assinaturas: tuple, calcular: Any) -> Any:
    """Resultado guardado enquanto os arquivos (data+tamanho) não mudam: a aba consulta isto a cada poucos segundos, para centenas de capítulos."""
    guardado = _CACHE.get(chave)
    if guardado and guardado[0] == assinaturas:
        return guardado[1]
    valor = calcular()
    if len(_CACHE) > 4000:
        _CACHE.clear()
    _CACHE[chave] = (assinaturas, valor)
    return valor


def _assin(arquivo: Path) -> Any:
    try:
        st = arquivo.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def ler_textos(pasta: Path) -> Optional[Dict[str, Any]]:
    """`textos.json` do capítulo, só se estiver no formato esperado (o arquivo é dado, não é confiável). O resultado é compartilhado: só leia."""
    arquivo = _dir_web(pasta) / "textos.json"
    return _lembrar(("t", str(arquivo)), (_assin(arquivo),), lambda: _ler_textos(arquivo))


def _ler_textos(arquivo: Path) -> Optional[Dict[str, Any]]:
    d = _json(arquivo)
    if not isinstance(d, dict) or not isinstance(d.get("codigo"), str) or not _CODIGO.match(d["codigo"]) or not isinstance(d.get("unidades"), list):
        return None
    unidades = [u for u in d["unidades"] if isinstance(u, dict) and all(isinstance(u.get(k), str) for k in ("id", "fonte", "hash")) and _LINHA.match(f"[{d['codigo']}:{u['id']}]")]
    if len(unidades) != len(d["unidades"]):
        return None
    return {"codigo": d["codigo"], "unidades": unidades}


def ler_importadas(pasta: Path, textos: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """Traduções já importadas que ainda valem (mesmo código e mesmo texto original). Devolve uma cópia: pode ser alterada."""
    arquivo = _dir_web(pasta) / "importadas.json"
    return dict(_lembrar(("i", str(arquivo), textos["codigo"], len(textos["unidades"])), (_assin(arquivo), _assin(_dir_web(pasta) / "textos.json")), lambda: _ler_importadas(arquivo, textos)))


def _ler_importadas(arquivo: Path, textos: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    d = _json(arquivo)
    if not isinstance(d, dict) or d.get("codigo") != textos["codigo"] or not isinstance(d.get("traducoes"), dict):
        return {}
    hashes = {u["id"]: u["hash"] for u in textos["unidades"]}
    return {i: r for i, r in d["traducoes"].items() if isinstance(r, dict) and isinstance(r.get("t"), str) and r["t"].strip() and r.get("h") == hashes.get(i)}


def _capitulos_da_biblioteca(raiz: Path) -> List[Dict[str, Any]]:
    """Capítulos (pastas `Obra/Cap`) que têm textos preparados para a IA na web."""
    achados = []
    for obra in _subpastas(Path(raiz)):
        for cap in _subpastas(obra):
            if not (_dir_web(cap) / "textos.json").is_file():       # barato: a maioria dos capítulos não tem textos preparados
                continue
            textos = ler_textos(cap)
            if textos:
                d = org.descrever_capitulo(cap, obra.name)
                achados.append({"pasta": cap, "rel": f"{obra.name}/{cap.name}", "obra": d["obra"] or obra.name, "numero": d["numero"], "titulo": d["titulo"], "textos": textos})
    return achados


def _ordem(c: Dict[str, Any]) -> tuple:
    return org.chave_ordem(c["numero"], c["titulo"])


def _todos(raiz: Path) -> List[Dict[str, Any]]:
    """Todos os capítulos da biblioteca (pela listagem em cache da própria biblioteca, que é barata de repetir)."""
    return [{**c, "pasta": Path(raiz) / c["rel"], "obra": o["nome"]} for o in acervo.listar(Path(raiz))["obras"] for c in o["capitulos"]]


def _concluido(c: Dict[str, Any]) -> bool:
    """Tradução de verdade concluída (traducao.json válido, nenhuma fala com erro): não pode ser preparada de novo."""
    return bool(c.get("traduzido")) and not c.get("incompleta")


def estado_dos_capitulos(raiz: Path, obra: str) -> List[Dict[str, Any]]:
    """Capítulos da obra que ainda precisam de tradução, com quantos textos foram preparados e quantos já voltaram.
    Os que já têm tradução concluída não entram. Pendente, incompleto (falas com erro) e preparado entram."""
    chave = org._chave(obra)
    saida = []
    for c in sorted((c for c in _todos(raiz) if org._chave(c["obra"] or "") == chave), key=_ordem):
        if _concluido(c):
            continue
        textos = ler_textos(c["pasta"])
        n = len(textos["unidades"]) if textos else 0
        feitas = len(ler_importadas(c["pasta"], textos)) if textos else 0
        saida.append({"rel": c["rel"], "rotulo": org.rotulo_capitulo(c["numero"], c["titulo"]), "numero": c["numero"], "textos": n, "importados": feitas,
                      "completo": n > 0 and feitas == n, "incompleta": c.get("incompleta", 0),
                      "situacao": "nao_preparado" if not n else "completo" if feitas == n else "parcial" if feitas else "preparado"})
    return saida


def aplicados(raiz: Path, rels: Iterable[str]) -> Dict[str, bool]:
    """rel → a tradução está de fato aplicada (traducao.json concluído, sem falas com erro, e a pasta de textos já foi encerrada)."""
    pedidos = set(rels)
    return {c["rel"]: _concluido(c) and ler_textos(c["pasta"]) is None for c in _todos(raiz) if c["rel"] in pedidos}


def ja_concluidos(raiz: Path, rels: Iterable[str]) -> List[str]:
    pedidos = set(rels)
    return [c["rel"] for c in _todos(raiz) if c["rel"] in pedidos and _concluido(c)]


def aguardando_da_biblioteca(raiz: Path) -> List[Dict[str, Any]]:
    """Capítulos com textos preparados para a IA e ainda sem tradução concluída. Vêm do disco, então não somem entre lotes nem ao reabrir o programa."""
    prontos = {c["rel"] for c in _capitulos_da_biblioteca(Path(raiz))}
    return [{"rel": c["rel"], "nome": f"{c['obra']} · {org.rotulo_capitulo(c['numero'], c['titulo'])}"} for c in sorted(_todos(raiz), key=lambda c: (c["obra"] or "", _ordem(c)))
            if c["rel"] in prontos and not _concluido(c)]


def conferir_mesma_obra(novos: Iterable[str], existentes: Iterable[str]) -> Optional[str]:
    """Uma preparação é de UMA obra só. `novos`/`existentes` são `rel` (`Obra/Cap`). Devolve a mensagem de bloqueio, ou None se pode."""
    def obras(rels: Iterable[str]) -> Dict[str, str]:
        return {org._chave(r.split("/", 1)[0]): r.split("/", 1)[0] for r in rels}
    novas, atuais = obras(novos), obras(existentes)
    if len(novas) > 1:
        return "Não é permitido misturar obras na mesma preparação. Os capítulos escolhidos são de: " + ", ".join(sorted(novas.values())) + ". Prepare uma obra de cada vez."
    if atuais and not set(novas) <= set(atuais):
        return (f"Não é permitido misturar obras na mesma preparação: já há capítulos preparados de “{', '.join(sorted(atuais.values()))}” e você escolheu “{', '.join(novas.values())}”. "
                "Conclua ou apague a tradução desses capítulos antes de preparar outra obra.")
    return None


# --------------------------------------------------------------------------- exportar

def _nome_seguro(texto: str) -> str:
    s = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()[:40] or "obra"


def exportar(raiz: Path, obra: str, rels: Iterable[str], introducao: bool = True, dividir: bool = False, limite: int = LIMITE_PADRAO, somente_pendentes: bool = False) -> List[Dict[str, Any]]:
    """TXT(s) com as falas dos capítulos pedidos (só os que têm textos preparados). Devolve [{nome, conteudo, textos, capitulos, caracteres}].

    `somente_pendentes`: deixa de fora as falas que já têm tradução importada válida. O glossário da obra (se houver) entra na introdução."""
    pedidos = set(rels)
    chave = org._chave(obra)
    caps = sorted((c for c in _capitulos_da_biblioteca(raiz) if c["rel"] in pedidos and org._chave(c["obra"]) == chave), key=_ordem)
    if not caps:
        raise ValueError("Nenhum dos capítulos escolhidos tem textos preparados. Use “Preparar textos” antes de exportar.")
    feitas = {c["rel"]: ler_importadas(c["pasta"], c["textos"]) for c in caps} if somente_pendentes else {}
    linhas = [(f"[{c['textos']['codigo']}:{u['id']}] {u['fonte']}", c["rel"]) for c in caps for u in c["textos"]["unidades"] if u["id"] not in feitas.get(c["rel"], {})]
    if not linhas:
        if somente_pendentes:
            raise ValueError("Não há falas pendentes: todas já têm tradução importada.")
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
    try:
        gloss = edicoes.bloco_glossario(edicoes.ler_glossario(raiz, caps[0]["rel"].split("/")[0]))
    except ErroBaixador:
        gloss = ""
    for i, parte in enumerate(partes, 1):
        corpo = "\n".join(l for l, _ in parte) + "\n"
        cabeca = ""
        if introducao:
            cabeca = INTRODUCAO.replace("\n\nTextos a traduzir", "\n\n" + gloss + "Textos a traduzir") + ("\n" if len(partes) == 1 else f"\n(Esta é a parte {i} de {len(partes)}; traduza só as linhas desta parte.)\n") + "\n"
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


def _normal(t: str) -> str:
    return " ".join(re.sub(r"[*_`#>]+", " ", t).casefold().split())


def _solto(t: str) -> str:
    """Só letras e números, sem caixa: para comparar a fala recebida com o original."""
    return "".join(ch for ch in t.casefold() if ch.isalnum())


_INTRO_N = _normal(INTRODUCAO)
_INTRO_LINHAS = {_normal(l) for l in INTRODUCAO.splitlines() if l.strip()}
_PARTE = re.compile(r"^\(?\s*esta é a parte \d+ de \d+")


def _e_introducao(s: str) -> bool:
    """Linha da introdução de instruções (colada de volta junto com a resposta): nunca é fala nem erro de estrutura."""
    n = _normal(s)
    return bool(n) and (n in _INTRO_LINHAS or bool(_PARTE.match(n)) or (len(n) >= 12 and n in _INTRO_N))


LIMITE_IGUAIS = 0.6          # fração das falas (com letras) que voltou igual ao original: aí o texto colado não é uma tradução


def _amostra(itens: Iterable[str], n: int = 12) -> List[str]:
    lista = list(itens)
    return lista[:n] + ([f"… e mais {len(lista) - n}"] if len(lista) > n else [])


def analisar(raiz: Path, conteudos: List[str]) -> Dict[str, Any]:
    """Confere o texto colado/lido contra os textos exportados. Não grava nada.

    Uma tradução é ACEITA só se: o código é de um capítulo preparado, o id existe nele, o texto não está vazio, a linha não foi
    quebrada, e o id não aparece duas vezes com traduções diferentes. Tudo o mais é relatado e ignorado."""
    registros, estranhas, intro = [], [], 0
    for conteudo in conteudos:
        anterior = None
        for n, bruta in enumerate(str(conteudo).splitlines(), 1):
            s = bruta.strip()
            if not s or _DIVISOR.match(s):
                anterior = None
                continue
            if _e_introducao(s) and not _LINHA.match(s):
                intro += 1                                     # instrução da introdução: reconhecida e ignorada de propósito
                continue
            lida = _ler_linha(s)
            if lida:
                anterior = {"codigo": lida[0], "id": lida[1], "texto": lida[2], "linha": n, "quebrada": False}
                registros.append(anterior)
            elif anterior is not None:
                anterior["quebrada"] = True                    # texto solto colado logo abaixo de uma fala: estrutura alterada
            else:
                estranhas.append(s[:80])
    grupos: Dict[str, List[Dict[str, Any]]] = {}
    for c in _capitulos_da_biblioteca(raiz):
        grupos.setdefault(c["textos"]["codigo"], []).append(c)
    por_codigo = {k: v[0] for k, v in grupos.items() if len(v) == 1}
    ambiguos = {k: [c["rel"] for c in v] for k, v in grupos.items() if len(v) > 1 and any(r["codigo"] == k for r in registros)}   # mesmo código em dois capítulos: não dá para saber de quem é a fala
    codigos_desconhecidos = sorted({r["codigo"] for r in registros if r["codigo"] not in grupos})
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
        novas, desconhecidos, duplicados, quebrados, vazios, repetidos_iguais, iguais, com_letras = {}, [], [], [], [], 0, [], 0
        validas, mantidas = [], []
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
            validas.append(i)
            if i in ja:
                if ja[i]["t"] != rs[0]["texto"]:
                    mantidas.append(i)                         # já tinha tradução válida: a primeira vale, nunca é sobrescrita
                continue
            novas[i] = {"t": rs[0]["texto"], "h": esperados[i]["hash"]}
        for i in novas:
            if any(ch.isalpha() for ch in esperados[i]["fonte"]):
                com_letras += 1
                if _solto(novas[i]["t"]) == _solto(esperados[i]["fonte"]):
                    iguais.append(i)
        original_reenviado = bool(com_letras) and len(iguais) / com_letras >= LIMITE_IGUAIS
        if original_reenviado:
            novas, validas = {}, []                            # o texto original voltou sem tradução: nada deste capítulo entra
        cobertos = set(ja) | set(novas)
        faltam = [i for i in esperados if i not in cobertos]
        rotulo = org.rotulo_capitulo(cap["numero"], cap["titulo"])
        mensagem = f"{rotulo}: {len(esperados)} identificadores esperados. {len(cobertos & set(esperados))} traduções válidas ({len(validas)} recebidas agora). " + (
            f"{len(faltam)} identificador(es) ausente(s)." if faltam else "Nenhum ausente.")
        capitulos[cap["rel"]] = {
            "rel": cap["rel"], "rotulo": rotulo, "codigo": codigo, "mensagem": mensagem, "recebidas": len(validas), "mantidas": mantidas, "esperados": len(esperados), "ja_importados": len(ja), "novas": len(novas),
            "faltam": faltam, "desconhecidos": desconhecidos, "duplicados": duplicados, "quebrados": quebrados, "vazios": vazios, "repetidos_iguais": repetidos_iguais,
            "original_reenviado": original_reenviado, "iguais_ao_original": iguais,
            "completo": not faltam, "_novas": novas, "_pasta": cap["pasta"], "_textos": cap["textos"],
        }
    return {"capitulos": capitulos, "linhas": len(registros), "linhas_fora_da_estrutura": _amostra(estranhas), "total_fora": len(estranhas), "codigos_desconhecidos": codigos_desconhecidos, "codigos_ambiguos": ambiguos, "introducao_ignorada": intro}


_TRAVA_GRAVAR = threading.Lock()


def gravar(analise: Dict[str, Any]) -> List[str]:
    """Grava as traduções aceitas (somando às já importadas). Devolve os `rel` dos capítulos que ficaram completos."""
    completos = []
    for c in analise["capitulos"].values():
        pasta, textos = c["_pasta"], c["_textos"]
        if c["novas"]:
            with _TRAVA_GRAVAR:                                # duas importações ao mesmo tempo não perdem traduções uma da outra
                antigas = ler_importadas(pasta, textos)
                todas = {**antigas, **{i: v for i, v in c["_novas"].items() if i not in antigas}}   # tradução válida já importada nunca é sobrescrita
                alvo = _dir_web(pasta) / "importadas.json"
                tmp = alvo.with_suffix(".json.tmp")
                tmp.write_text(json.dumps({"versao": 1, "codigo": textos["codigo"], "traducoes": todas}, ensure_ascii=False, indent=1), encoding="utf-8")
                os.replace(tmp, alvo)
            shutil.rmtree(Path(pasta) / "traducao.nova" / "etapa4b", ignore_errors=True)   # a etapa de tradução precisa refazer com o que chegou
        if c["completo"]:
            completos.append(c["rel"])
    return completos


def relatorio(analise: Dict[str, Any]) -> Dict[str, Any]:
    """A análise sem os campos internos, pronta para JSON. Ausentes, desconhecidos e duplicados vêm COMPLETOS (a pessoa precisa ver exatamente quais)."""
    completas = ("faltam", "desconhecidos", "duplicados")
    caps = [{k: (v if k in completas else _amostra(v) if k in ("quebrados", "vazios", "iguais_ao_original", "mantidas") else v) for k, v in c.items() if not k.startswith("_")}
            | {"qtd_faltam": len(c["faltam"]), "ausentes": [f"[{c['codigo']}:{i}]" for i in c["faltam"]]}
            for c in analise["capitulos"].values()]
    return {"capitulos": caps, "linhas": analise["linhas"], "linhas_fora_da_estrutura": analise["linhas_fora_da_estrutura"], "total_fora": analise["total_fora"],
            "codigos_desconhecidos": analise["codigos_desconhecidos"], "codigos_ambiguos": analise["codigos_ambiguos"], "introducao_ignorada": analise["introducao_ignorada"]}


# --------------------------------------------------------------------------- revisão por IA (só falas "revisar"/"erro")

INTRODUCAO_REVISAO = """Você é revisor profissional de tradução de mangá, manhwa e quadrinhos (inglês → português brasileiro, PT-BR).

Cada linha tem o formato:
[IDENTIFICADOR] texto original ::: tradução atual

Regras:
1. Corrija ou refaça a tradução atual (que pode estar vazia ou errada), mantendo o sentido do original e a linguagem natural de quadrinhos.
2. Mantenha os identificadores entre colchetes exatamente como estão.
3. Devolva uma linha para cada linha de entrada, no formato [IDENTIFICADOR] tradução corrigida, sem o original e sem ":::".
4. Retorne somente o resultado: sem introdução, comentários, blocos de código ou markdown.

{glossario}Falas para revisar (começam na próxima linha):"""
_REVISAR = ("revisar", "erro")


def _codigo_rev(rel: str) -> str:
    return hashlib.sha1(rel.encode("utf-8")).hexdigest()[:8]


def _para_revisar(raiz: Path, obra: str) -> List[Dict[str, Any]]:
    chave, achados = org._chave(obra), []
    for c in sorted(_todos(raiz), key=_ordem):
        if org._chave(c["obra"]) != chave or not c.get("traduzido") or not (c.get("revisar") or c.get("incompleta")):
            continue
        d = capitulo._ler_traducao(c["pasta"]) or {}
        falas = [u for p in d.get("pages", []) for u in p.get("units", []) if u.get("status") in _REVISAR and u.get("source")]
        if falas:
            achados.append({"rel": c["rel"], "pasta": c["pasta"], "falas": falas, "codigo": _codigo_rev(c["rel"])})
    return achados


def exportar_revisao(raiz: Path, obra: str) -> Dict[str, Any]:
    """TXT com original + tradução atual + id das falas marcadas `revisar`/`erro` (as demais nem aparecem)."""
    caps = _para_revisar(raiz, obra)
    if not caps:
        raise ValueError("Nenhuma fala marcada para revisão nesta obra.")
    try:
        gloss = edicoes.bloco_glossario(edicoes.ler_glossario(raiz, caps[0]["rel"].split("/")[0]))
    except ErroBaixador:
        gloss = ""
    linhas = [f"[{c['codigo']}:{u['id']}] {' '.join(str(u['source']).split())} ::: {' '.join(str(u.get('translation') or '').split())}" for c in caps for u in c["falas"]]
    texto = INTRODUCAO_REVISAO.format(glossario=gloss) + "\n" + "\n".join(linhas) + "\n"
    return {"nome": f"{_nome_seguro(obra)}-revisao.txt", "conteudo": texto, "textos": len(linhas), "capitulos": len(caps)}


def importar_revisao(raiz: Path, obra: str, conteudos: List[str], gravar: bool) -> Dict[str, Any]:
    """Lê a resposta da IA e (se `gravar`) atualiza SÓ as falas que ainda estão `revisar`/`erro`. Reaproveita a leitura de linhas da importação."""
    por_codigo = {c["codigo"]: c for c in _para_revisar(raiz, obra)}
    pedidos: Dict[str, Dict[str, str]] = {}
    desconhecidas = 0
    for texto in conteudos:
        for bruta in texto.splitlines():
            r = _ler_linha(bruta)
            if not r:
                continue
            codigo, id_, t = r
            if codigo not in por_codigo:
                desconhecidas += 1
                continue
            if ":::" in t:
                t = t.rsplit(":::", 1)[1].strip()
            pedidos.setdefault(codigo, {})[id_] = t
    resultado: Dict[str, Any] = {"alteradas": 0, "ignoradas": [], "desconhecidas": desconhecidas, "capitulos": []}
    for codigo, mud in pedidos.items():
        c = por_codigo[codigo]
        if gravar:
            r = edicoes.aplicar(c["pasta"], mud, estados=_REVISAR)
        else:
            marcadas = {u["id"] for u in c["falas"]}
            r = {"alteradas": [i for i in mud if i in marcadas], "ignoradas": [{"id": i, "motivo": "a fala não está marcada para revisão"} for i in mud if i not in marcadas]}
        resultado["alteradas"] += len(r["alteradas"])
        resultado["ignoradas"] += [{"rel": c["rel"], **x} for x in r["ignoradas"]]
        if r["alteradas"]:
            resultado["capitulos"].append(c["rel"])
    resultado["aplicado"] = bool(gravar)
    return resultado
