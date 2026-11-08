"""A biblioteca: obras e capítulos guardados em `obras/`, vistos como "linhas" (obra) e "estações" (capítulos).

Este módulo só lê e reorganiza pastas dentro da raiz da biblioteca. É compartilhado pelo app do notebook
(que também reorganiza) e pelo servidor do celular (que só usa `listar` e `versao`).
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from baixador.biblioteca import capa, obra as dados_obra, organizacao as org
from baixador.nucleo.erros import ErroBaixador
from baixador.biblioteca.capitulo import NOME_AVISO, NOME_IMG, NOME_TRADUCAO, _varrer

CORES_DE_LINHA = 6          # o app associa cada obra a uma de 6 cores de linha (índice estável)
MAX_FALTANDO = 400          # não lista "faltando" de séries com saltos absurdos (ex.: capítulos 1 e 9999)


def _indice_de_cor(nome: str) -> int:
    return int(hashlib.sha1(org._chave(nome).encode("utf-8")).hexdigest()[:6], 16) % CORES_DE_LINHA


def _faltando(numeros: List[str]) -> List[int]:
    """Números inteiros que faltam entre o menor e o maior capítulo (ignora capítulos extras como 12.5)."""
    inteiros = sorted({int(n) for n in numeros if n is not None and n.isdigit()})
    if len(inteiros) < 2 or inteiros[-1] - inteiros[0] > MAX_FALTANDO * 3:
        return []
    presentes = set(inteiros)
    return [n for n in range(inteiros[0], inteiros[-1] + 1) if n not in presentes][:MAX_FALTANDO]


def _ultima_url(raiz: Path, caps: List[Dict[str, Any]]) -> str:
    """Endereço (do `capitulo.json`) do capítulo mais novo que tem um: de onde o botão "Atualizar" parte."""
    for c in reversed(caps):                                   # `caps` está em ordem crescente
        url = str(org.ler_meta(raiz / c["rel"]).get("url", "")) if not c["antigo"] else ""
        if url.startswith(("http://", "https://")):
            return url
    return ""


def listar(raiz: Path) -> Dict[str, Any]:
    """Todas as obras, cada uma com seus capítulos em ordem numérica, os números que faltam e a cor da linha."""
    grupos: Dict[str, Dict[str, Any]] = {}
    for c in _varrer(Path(raiz)):
        obra = c["obra"] or "Sem obra"
        g = grupos.setdefault(org._chave(obra) or "sem-obra", {"nome": obra, "capitulos": [], "quando": 0.0})
        g["capitulos"].append(c)
        g["quando"] = max(g["quando"], c["quando"])
    obras = []
    for g in sorted(grupos.values(), key=lambda x: -x["quando"]):
        g["capitulos"].sort(key=lambda c: org.chave_ordem(c["numero"], c["titulo"]))
        caps = [
            {
                "rel": c["rel"], "numero": c["numero"], "titulo": c["titulo"],
                "rotulo": org.rotulo_capitulo(c["numero"], c["titulo"]) if c["numero"] is not None or not c["antigo"] else c["rel"],
                "imagens": len(c["nomes"]), "traduzido": c["traduzido"], "incompleta": c["incompleta"], "antigo": c["antigo"],
                "capa": c["nomes"][0], "quando": c["quando"],
            }
            for c in g["capitulos"]
        ]
        pasta = next((c["rel"].split("/")[0] for c in caps if "/" in c["rel"]), None)   # pasta da obra (onde fica a capa)
        arquivo_capa = capa.achar(Path(raiz) / pasta) if pasta else None
        obras.append({
            "nome": g["nome"], "cor": _indice_de_cor(g["nome"]), "capitulos": caps,
            "pasta": pasta, "url": dados_obra.url_principal(Path(raiz) / pasta) if pasta else "",
            "ultima_url": _ultima_url(Path(raiz), caps),
            "capa": arquivo_capa.name if arquivo_capa else None,
            "capa_v": int(_mtime(arquivo_capa)) if arquivo_capa else 0,
            "traduzidos": sum(1 for c in caps if c["traduzido"]),
            "faltando": _faltando([c["numero"] for c in caps]),
            "quando": g["quando"],
        })
    return {"obras": obras, "versao": versao(raiz)}


# ----------------------------------------------------------------------------- versão (sincronização)

_cache_versao: Dict[str, Any] = {"raiz": None, "quando": 0.0, "valor": ""}
_trava_versao = threading.Lock()


def _mtime(caminho: Path) -> int:
    try:
        return caminho.stat().st_mtime_ns
    except OSError:
        return 0


def _subpastas(pasta: Path) -> List[Path]:
    try:
        return sorted(p for p in pasta.iterdir() if p.is_dir() and not p.is_symlink() and not p.name.startswith(".") and p.name != NOME_IMG)
    except OSError:
        return []


def versao(raiz: Path, validade: float = 1.0) -> str:
    """Impressão digital barata do estado da biblioteca: muda quando chega imagem, tradução ou reorganização.

    Só olha datas de pastas e de dois arquivos por capítulo (não lê imagens), então pode ser consultada a cada
    poucos segundos pelo celular. O resultado vale por `validade` segundos para vários clientes não repetirem a varredura.
    """
    raiz = Path(raiz)
    with _trava_versao:
        agora = time.monotonic()
        if _cache_versao["raiz"] == str(raiz) and agora - _cache_versao["quando"] < validade:
            return _cache_versao["valor"]
        h = hashlib.sha1()
        for nivel1 in _subpastas(raiz):
            h.update(f"{nivel1.name}|{_mtime(nivel1)}|{_mtime(nivel1 / NOME_TRADUCAO)}|{_mtime(nivel1 / org.NOME_META)};".encode("utf-8", "replace"))
            for nivel2 in _subpastas(nivel1):
                h.update(
                    f"{nivel1.name}/{nivel2.name}|{_mtime(nivel2)}|{_mtime(nivel2 / NOME_TRADUCAO)}|{_mtime(nivel2 / NOME_AVISO)}|{_mtime(nivel2 / NOME_IMG)}|{_mtime(nivel2 / org.NOME_META)};"
                    .encode("utf-8", "replace")
                )
        valor = h.hexdigest()[:16]
        _cache_versao.update(raiz=str(raiz), quando=agora, valor=valor)
        return valor


def esquecer_versao() -> None:
    with _trava_versao:
        _cache_versao["quando"] = 0.0


# ----------------------------------------------------------------------------- organizar (só no notebook)

def _dentro(raiz: Path, alvo: Path) -> bool:
    try:
        r = raiz.resolve()
        a = alvo.resolve()
        return a != r and a.is_relative_to(r)
    except OSError:
        return False


def _achar(raiz: Path, rel: str) -> Optional[Dict[str, Any]]:
    return next((c for c in _varrer(raiz) if c["rel"] == rel), None)


def reorganizar_capitulo(raiz: Path, rel: str, obra: str, numero: Any, titulo: str) -> str:
    """Muda obra, número e/ou nome de um capítulo: move a pasta para `Obra/Cap NNN - Nome` e atualiza `capitulo.json`.

    Devolve o novo caminho relativo. Recusa se o destino já existe, se faltar obra/número ou se sair da biblioteca.
    """
    raiz = Path(raiz)
    obra = org.limpar_nome(obra or "", 80)
    titulo = (titulo or "").strip()[:120]
    num = org.normalizar_numero(numero)
    if not obra:
        raise ErroBaixador("Informe a obra.")
    if num is None and not titulo:
        raise ErroBaixador("Informe o número do capítulo (ou o nome dele).")
    achado = _achar(raiz, rel)
    if achado is None:
        raise ErroBaixador("Capítulo não encontrado na biblioteca.")
    origem: Path = achado["pasta"]
    novo_rel = org.caminho_relativo(obra, num, titulo)
    destino = raiz / novo_rel
    if not _dentro(raiz, origem) or not _dentro(raiz, destino):
        raise ErroBaixador("Destino fora da biblioteca.")
    mesmo = os.path.normcase(str(origem.resolve())) == os.path.normcase(str(destino.resolve(strict=False)))
    if not mesmo:
        if destino.exists() and os.path.normcase(str(destino)) != os.path.normcase(str(origem)):
            raise ErroBaixador(f"Já existe um capítulo em “{novo_rel}”. Escolha outro número ou nome.")
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(origem), str(destino))
        pai = origem.parent
        if pai != raiz and _dentro(raiz, pai):
            try:
                pai.rmdir()                       # a pasta da obra antiga some se ficou vazia
            except OSError:
                pass
    antigo = org.ler_meta(destino)
    org.gravar_meta(destino, obra, num, titulo, str(antigo.get("url", "")))
    esquecer_versao()
    return novo_rel


def _normalizar_url(url: str) -> str:
    """Endereço sem esquema, `www.`, parâmetros, âncora nem barra final (para comparar endereços do mesmo capítulo/obra)."""
    try:
        d = urlsplit(str(url or "").strip())
    except ValueError:
        return ""
    host = (d.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    return f"{host}{d.path.rstrip('/')}".lower() if host else ""


def _palavras(texto: str) -> List[str]:
    return [p for p in re.split(r"[^a-z0-9]+", org._sem_acento(texto or "").lower()) if p]


def resolver_obra(raiz: Path, nome: str = "", url: str = "") -> Dict[str, Any]:
    """Descobre se a obra do link já existe na biblioteca, mesmo com o nome do site errado (ex.: "eieom One Piece").

    Ordem de confiança: 1) endereço da obra (`obra.json`); 2) nome igual depois de normalizar (acentos, espaços,
    símbolos); 3) nome contido no outro (todas as palavras da obra existente aparecem no nome novo, ou vice-versa) ou
    muito parecido. Só associa quando **uma única** obra serve; com duas ou mais devolve `candidatas` para o usuário escolher.
    Devolve {"obra": nome final, "existente": bool, "candidatas": [nomes], "motivo": texto}.
    """
    nome = org.limpar_nome(nome or "", 80)
    resultado: Dict[str, Any] = {"obra": nome, "existente": False, "candidatas": [], "motivo": ""}
    raiz = Path(raiz)
    if not raiz.is_dir():
        return resultado
    obras = listar(raiz)["obras"]
    if not obras:
        return resultado
    principal = capa.url_da_obra(url or "")
    nome_url = org.obra_da_url(url or "") if url else ""

    def escolher(achadas: List[Dict[str, Any]], motivo: str) -> Optional[Dict[str, Any]]:
        if len(achadas) == 1:
            resultado.update(obra=achadas[0]["nome"], existente=True, candidatas=[], motivo=motivo)
            return resultado
        if len(achadas) > 1:
            resultado.update(candidatas=[o["nome"] for o in achadas], motivo="Há mais de uma obra parecida: escolha qual é.")
            return resultado
        return None

    if principal:                                                       # 1) endereço da obra
        alvo = _normalizar_url(principal)
        slug = alvo.rsplit("/", 1)[-1]
        por_url = [o for o in obras if o.get("url") and _normalizar_url(o["url"]) == alvo]
        if not por_url and len(slug) >= 6:                              # mesmo nome no endereço, site com outro domínio
            por_url = [o for o in obras if o.get("url") and _normalizar_url(o["url"]).rsplit("/", 1)[-1] == slug]
        r = escolher(por_url, "Reconhecida pelo endereço da obra.")
        if r:
            return r
    chaves = {org._chave(x) for x in (nome, nome_url) if x}
    exatas = [o for o in obras if org._chave(o["nome"]) in chaves]      # 2) nome igual
    r = escolher(exatas, "Já existe uma obra com esse nome.")
    if r:
        return r
    parecidas: List[Dict[str, Any]] = []                                # 3) contida ou muito parecida
    for o in obras:
        pe = set(_palavras(o["nome"]))
        for candidato in (nome, nome_url):
            pn = set(_palavras(candidato))
            if not pe or not pn:
                continue
            menor = pe if len(pe) <= len(pn) else pn
            if menor <= (pn if menor is pe else pe) and len(org._chave(" ".join(menor))) >= 6:
                parecidas.append(o); break
            if difflib.SequenceMatcher(None, org._chave(o["nome"]), org._chave(candidato)).ratio() >= 0.88:
                parecidas.append(o); break
    r = escolher(parecidas, "Parece ser uma obra que você já tem.")
    if r:
        return r
    if not nome and nome_url:
        resultado["obra"] = org.limpar_nome(nome_url, 80)
    return resultado


def capitulo_existente(raiz: Path, obra: str, numero: Any, titulo: str = "", url: str = "") -> Optional[str]:
    """Caminho relativo do capítulo, se ele já está salvo na biblioteca (traduzido ou não); senão None.

    Vale: o mesmo endereço de capítulo (`capitulo.json`), ou a mesma obra com o mesmo número (sem número: o mesmo nome),
    ou a pasta de destino que o programa usaria já ter imagens. Capítulos diferentes da mesma obra não contam.
    """
    raiz = Path(raiz)
    if not raiz.is_dir():
        return None
    num = org.normalizar_numero(numero)
    chave_obra, chave_tit = org._chave(obra or ""), org._chave(titulo or "")
    alvo_url = _normalizar_url(url)
    destino = org.caminho_relativo(obra, num, titulo)
    for c in _varrer(raiz):
        if alvo_url and _normalizar_url(str(org.ler_meta(c["pasta"]).get("url", ""))) == alvo_url:
            return c["rel"]
        mesma_obra = chave_obra and org._chave(c["obra"] or "") == chave_obra
        if mesma_obra and num is not None and c["numero"] == num:
            return c["rel"]
        if mesma_obra and num is None and chave_tit and org._chave(c["titulo"] or "") == chave_tit:
            return c["rel"]
        if destino and c["rel"].lower() == destino.lower():
            return c["rel"]
    return None


def renomear_obra(raiz: Path, antiga: str, nova: str) -> int:
    """Renomeia (ou funde em outra) uma obra. Devolve quantos capítulos passaram a ter o novo nome.

    Renomear: a pasta da obra inteira é renomeada (a capa e o `obra.json` vão junto) e o nome é corrigido em `obra.json`
    e em cada `capitulo.json`. Se a nova obra já existe, os capítulos são movidos para ela (a capa e o endereço da
    antiga só são aproveitados se a nova não tiver). Recusa sem alterar nada se algum capítulo colidir.
    """
    raiz = Path(raiz)
    nova = org.limpar_nome(nova or "", 80)
    if not nova:
        raise ErroBaixador("Informe o novo nome da obra.")
    chave = org._chave(antiga)
    caps = [c for c in _varrer(raiz) if org._chave(c["obra"] or "Sem obra") == chave]
    if not caps:
        raise ErroBaixador("Obra não encontrada.")
    pastas_antigas = {c["pasta"].parent for c in caps if not c["antigo"] and c["pasta"].parent != raiz}
    alvo = next((p for p in _subpastas(raiz) if org._chave(p.name) == org._chave(nova)), None)
    # 1) obra com pasta própria que será só renomeada (nome novo livre, ou só maiúsculas/acentos diferentes da própria pasta)
    if len(pastas_antigas) == 1 and not any(c["antigo"] for c in caps):
        pasta = next(iter(pastas_antigas))
        if alvo is None or alvo == pasta:
            destino = raiz / nova
            if pasta.name != nova:
                if not _dentro(raiz, pasta) or not _dentro(raiz, destino):
                    raise ErroBaixador("Destino fora da biblioteca.")
                if destino.exists() and os.path.normcase(str(destino)) != os.path.normcase(str(pasta)):
                    raise ErroBaixador(f"Já existe “{nova}”. Nada foi alterado.")
                provisoria = pasta.with_name(f".renomeando-{os.getpid()}-{pasta.name}")
                os.rename(pasta, provisoria)                                    # também serve para trocar só maiúsculas no Windows
                os.rename(provisoria, destino)
            for sub in _subpastas(destino):
                meta = org.ler_meta(sub)
                if meta or _tem_imagens(sub):
                    org.gravar_meta(sub, nova, org.normalizar_numero(meta.get("numero")), str(meta.get("titulo", "")), str(meta.get("url", "")))
            dados = dados_obra.ler(destino)
            if dados:
                dados["nome"] = nova
                _regravar_json(destino / dados_obra.NOME_ARQUIVO, dados)
            esquecer_versao()
            return len(caps)
    # 2) fusão (ou capítulos em formato antigo): move capítulo a capítulo, com planejamento prévio
    for c in caps:
        destino = raiz / org.caminho_relativo(nova, c["numero"], c["titulo"])
        if destino.exists() and os.path.normcase(str(destino.resolve())) != os.path.normcase(str(c["pasta"].resolve())):
            raise ErroBaixador(f"“{nova}” já tem um capítulo igual a “{c['rel']}”. Nada foi alterado.")
    for c in caps:
        reorganizar_capitulo(raiz, c["rel"], nova, c["numero"], c["titulo"])
    novo_dir = next((p for p in _subpastas(raiz) if org._chave(p.name) == org._chave(nova)), None)
    for pasta in pastas_antigas:                                                # capa/obra.json da obra antiga
        if novo_dir is None or pasta == novo_dir or not pasta.is_dir():
            continue
        antiga_capa = capa.achar(pasta)
        if antiga_capa is not None and capa.achar(novo_dir) is None:
            shutil.move(str(antiga_capa), str(novo_dir / antiga_capa.name))
        url_antiga = dados_obra.url_principal(pasta)
        dados_obra.gravar(novo_dir, nova, url_antiga)
        restos = [e for e in pasta.iterdir() if not (e.name == dados_obra.NOME_ARQUIVO or e.stem.lower() == "capa" or e.name.startswith("."))]
        if not restos:
            _apagar_arvore(pasta)
    if novo_dir is not None:
        dados = dados_obra.ler(novo_dir)
        if dados.get("nome") and dados["nome"] != nova and org._chave(dados["nome"]) != org._chave(nova):
            dados["nome"] = nova
            _regravar_json(novo_dir / dados_obra.NOME_ARQUIVO, dados)
    esquecer_versao()
    return len(caps)


def _tem_imagens(pasta: Path) -> bool:
    from baixador.biblioteca.capitulo import listar_imagens
    return bool(listar_imagens(pasta))


def _regravar_json(caminho: Path, dados: Dict[str, Any]) -> None:
    tmp = caminho.with_name("." + caminho.name + ".tmp")
    try:
        tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, caminho)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass


def _apagar_arvore(pasta: Path) -> None:
    """rmtree que também apaga arquivos somente-leitura (Windows)."""
    def _forcar(funcao, caminho, _info):
        try:
            os.chmod(caminho, 0o700)
            funcao(caminho)
        except OSError:
            raise

    shutil.rmtree(pasta, onerror=_forcar)


def excluir_obra(raiz: Path, nome: str) -> Dict[str, Any]:
    """Apaga do disco uma obra da biblioteca (capítulos, traduções, capa e `obra.json`). As outras obras não são tocadas.

    Só apaga pastas que o programa enxerga como capítulos desta obra dentro da biblioteca (nunca segue atalhos, nunca sai da
    raiz). Devolve {"capitulos": n, "pastas": [...]}.
    """
    raiz = Path(raiz)
    chave = org._chave(nome or "")
    if not chave:
        raise ErroBaixador("Informe a obra.")
    caps = [c for c in _varrer(raiz) if org._chave(c["obra"] or "Sem obra") == chave]
    if not caps:
        raise ErroBaixador("Obra não encontrada.")
    for c in caps:
        if not _dentro(raiz, c["pasta"]) or c["pasta"].is_symlink():
            raise ErroBaixador("Uma das pastas da obra está fora da biblioteca. Nada foi apagado.")
        if c["antigo"] and any(listar_imagens_em(sub) for sub in _subpastas(c["pasta"])):
            raise ErroBaixador(f"A pasta “{c['rel']}” também guarda outros capítulos em subpastas. Nada foi apagado.")
    pais = set()
    for c in caps:
        _apagar_arvore(c["pasta"])
        if not c["antigo"]:
            pais.add(c["pasta"].parent)
    for pai in pais:                                      # sobrou só capa/obra.json/pastas vazias? então a pasta da obra também some
        if pai == raiz or not pai.is_dir() or not _dentro(raiz, pai):
            continue
        if _varrer_pasta_tem_capitulos(pai):
            continue
        restos = [e for e in pai.iterdir() if not (e.is_dir() and not any(e.iterdir()))]
        if all(e.name == "obra.json" or e.name.startswith(".") or (e.stem.lower() == "capa") for e in restos):
            _apagar_arvore(pai)
    esquecer_versao()
    return {"capitulos": len(caps), "pastas": sorted({c["rel"] for c in caps})}


def listar_imagens_em(pasta: Path) -> List[str]:
    from baixador.biblioteca.capitulo import listar_imagens
    return listar_imagens(pasta)


def _varrer_pasta_tem_capitulos(pasta: Path) -> bool:
    return any(listar_imagens_em(sub) for sub in _subpastas(pasta))


def excluir_tudo(raiz: Path) -> Dict[str, Any]:
    """Apaga TODA a biblioteca: todas as obras (capítulos, traduções, capas, `obra.json`) e pastas de obra que sobraram vazias.

    Só mexe no que o programa reconhece como obra/capítulo; outras pastas que você tenha colocado em `obras/` ficam.
    """
    raiz = Path(raiz)
    nomes = [o["nome"] for o in listar(raiz)["obras"]]
    capitulos = 0
    for nome in nomes:
        capitulos += excluir_obra(raiz, nome)["capitulos"]
    sobras = 0
    for pasta in _subpastas(raiz):
        if _varrer_pasta_tem_capitulos(pasta) or [n for n in listar_imagens_em(pasta) if Path(n).stem.lower() != "capa"]:
            continue
        itens = list(pasta.iterdir())
        if all(e.name == dados_obra.NOME_ARQUIVO or e.stem.lower() == "capa" or e.name.startswith(".") or (e.is_dir() and not any(e.iterdir())) for e in itens):
            _apagar_arvore(pasta)
            sobras += 1
    esquecer_versao()
    return {"obras": len(nomes), "capitulos": capitulos, "pastas_vazias": sobras}
