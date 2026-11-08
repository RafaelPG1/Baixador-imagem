"""Organização por obra: identifica obra, número e nome do capítulo e guarda isso junto das imagens.

Estrutura em disco:  <pasta de saída>/<Obra>/<Cap 005 - Nome do capítulo>/imagens...
A obra (o "conjunto") já identifica a história; por isso a pasta do capítulo não repete o nome dela.

Tudo aqui é Python puro (sem navegador nem OCR) para poder ser testado sozinho.
"""

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlsplit

NOME_META = "capitulo.json"

_PALAVRA_CAP = r"(?:cap[ií]tulo|cap\.?|chapter|chap\.?|ch\.?|epis[óo]dio|episode|ep\.?)"
# "Capítulo 12", "Chapter 12.5", "Cap. 12", "Ch 12", "Ep. 3" (o número não pode colar em outra palavra)
_RE_CAP = re.compile(rf"(?<![\w]){_PALAVRA_CAP}\s*[#:.\-]?\s*(\d{{1,4}}(?:[.,]\d{{1,2}})?)(?![\d])", re.IGNORECASE)
_RE_CAP_SLUG = re.compile(
    r"(?:^|[-_/])(?:cap[ií]tulo|capitulo|cap|chapter|chap|ch|epis[óo]dio|episodio|episode|ep)[-_]?(\d{1,4})(?:[-_](\d{1,2}))?(?=$|[-_/.])",
    re.IGNORECASE,
)
_RE_HASH = re.compile(r"#\s*(\d{1,4}(?:[.,]\d{1,2})?)(?!\d)")
_SEPARADOR = re.compile(r"\s+[|–—·•\-:]\s+|\s*[|·•]\s*")
_GENERICAS_URL = {
    "manga", "manhwa", "manhua", "webtoon", "webtoons", "series", "serie", "read", "ler", "title", "titles",
    "comic", "comics", "obra", "obras", "chapter", "chapters", "capitulo", "capitulos", "novel", "view", "p", "c", "m", "s", "a",
}
_SITE_NO_FIM = re.compile(r"(scans?|toons?|mangas?|manhwas?|manhuas?|comics?|webtoons?|hub|reader|leitor|online|scanlation|novels?)$")
_FILLER = re.compile(
    r"^(?:ler\s+online|read\s+online|online|gr[áa]tis|free|scan|scans|manga|manhwa|manhua|webtoon|leitura|reader|home|in[íi]cio)$",
    re.IGNORECASE,
)


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def _chave(texto: str) -> str:
    """Só letras e números, minúsculos e sem acento (para comparar nomes de jeitos diferentes)."""
    return re.sub(r"[^a-z0-9]+", "", _sem_acento(texto).lower())


def normalizar_numero(bruto: Any) -> Optional[str]:
    """'005' → '5'; '12,5' → '12.5'; vazio/inválido → None."""
    texto = str(bruto or "").strip().replace(",", ".")
    if not re.fullmatch(r"\d{1,4}(?:\.\d{1,2})?", texto):
        return None
    inteiro, _, frac = texto.partition(".")
    inteiro = str(int(inteiro))
    frac = frac.rstrip("0")
    return f"{inteiro}.{frac}" if frac else inteiro


def _titulo_de_slug(slug: str) -> str:
    palavras = [p for p in re.split(r"[-_+\s]+", unquote(slug)) if p]
    return " ".join(p.capitalize() if p.islower() else p for p in palavras)


def _partes_do_caminho(url: str) -> List[str]:
    try:
        return [unquote(p) for p in urlsplit(url or "").path.split("/") if p]
    except ValueError:
        return []


def _host_chave(url: str) -> str:
    try:
        host = (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        return ""
    rotulos = [r for r in host.split(".") if r and r not in ("www", "com", "net", "org", "br", "io", "co", "to", "me", "app")]
    return _chave("".join(rotulos))


def numero_da_url(url: str) -> Optional[str]:
    """Número do capítulo pelo endereço: .../chapter-12, .../cap-12-5, .../capitulo/12 ou um último trecho só numérico."""
    caminho = "/" + "/".join(_partes_do_caminho(url))
    m = _RE_CAP_SLUG.search(caminho)
    if m:
        return normalizar_numero(m.group(1) + ("." + m.group(2) if m.group(2) else ""))
    partes = _partes_do_caminho(url)
    # "/capitulo/12": palavra num trecho e o número no seguinte
    for anterior, atual in zip(partes, partes[1:]):
        if re.fullmatch(r"(?:cap[ií]tulos?|chapters?|episodes?|epis[óo]dios?|ch|cap|ep)", anterior, re.IGNORECASE):
            n = normalizar_numero(atual)
            if n:
                return n
    if partes and re.fullmatch(r"\d{1,4}", partes[-1]) and not 1900 <= int(partes[-1]) <= 2100:
        return normalizar_numero(partes[-1])
    return None


def obra_da_url(url: str) -> str:
    """Nome da obra pelo endereço: o trecho do caminho que parece o nome (ex.: /manga/solo-leveling/chapter-12)."""
    partes = _partes_do_caminho(url)
    candidatos = []
    for p in partes:
        if _RE_CAP_SLUG.search("/" + p) or re.fullmatch(r"\d+", p):
            break
        if _chave(p) in _GENERICAS_URL or len(_chave(p)) < 3:
            continue
        candidatos.append(p)
    return _titulo_de_slug(candidatos[-1]) if candidatos else ""


def _titulo_da_url(url: str) -> str:
    """Nome do capítulo pelo endereço, quando o último trecho é 'chapter-12-o-encontro'."""
    partes = _partes_do_caminho(url)
    if not partes:
        return ""
    m = re.search(
        r"(?:cap[ií]tulo|capitulo|cap|chapter|chap|ch|epis[óo]dio|episodio|episode|ep)[-_]?\d{1,4}(?:[-_]\d{1,2})?[-_]+([a-zA-ZÀ-ÿ][\w\-]*)$",
        partes[-1], re.IGNORECASE,
    )
    return _titulo_de_slug(m.group(1)) if m else ""


def extrair_capitulo(titulo_aba: str, url: str = "", tira_site: bool = True) -> Dict[str, Optional[str]]:
    """Obra, número e nome do capítulo. Prioridade: título da aba do site; o que faltar vem do endereço.

    Devolve {"obra", "numero", "titulo", "origem"} (campos vazios = não identificado; o usuário corrige à mão).
    """
    texto = re.sub(r"\s+", " ", (titulo_aba or "")).strip()
    host = _host_chave(url)
    partes = [p.strip(" -–—|:·•") for p in _SEPARADOR.split(texto)] if texto else []
    partes = [p for p in partes if p]
    # tira o nome do site (parte que é o próprio domínio) e enchimentos como "Ler online"
    uteis = []
    for p in partes:
        c = _chave(p)
        if _FILLER.match(p.strip()):
            continue
        if tira_site and len(partes) > 1 and len(p.split()) <= 3 and _SITE_NO_FIM.search(c) and not _RE_CAP.search(p):
            continue                                        # "NexusToons", "Asura Scans", "Mangá Hub": nome do site
        if host and len(c) >= 4 and (c == host or c in host or host in c) and len(partes) > 1:
            continue
        uteis.append(p)
    if not uteis and partes:
        uteis = partes[:1]

    numero: Optional[str] = None
    indice_cap = -1
    antes = depois = ""
    for i, p in enumerate(uteis):
        m = _RE_CAP.search(p)
        if m:
            numero = normalizar_numero(m.group(1))
            indice_cap, antes, depois = i, p[: m.start()].strip(" -–—|:·•,"), p[m.end():].strip(" -–—|:·•,.")
            break
    if numero is None:
        for i, p in enumerate(uteis):
            m = _RE_HASH.search(p)
            if m:
                numero = normalizar_numero(m.group(1))
                indice_cap, antes, depois = i, p[: m.start()].strip(" -–—|:·•,"), p[m.end():].strip(" -–—|:·•,.")
                break
    origem = "aba" if numero is not None else ""
    if numero is None:
        numero = numero_da_url(url)
        if numero is not None:
            origem = "link"

    obra_url = obra_da_url(url)
    chave_obra_url = _chave(obra_url)
    outras = [p for i, p in enumerate(uteis) if i != indice_cap]
    obra = ""
    # a obra é a parte que bate com o nome no endereço; senão o texto antes de "Capítulo N"; senão a primeira outra parte
    if chave_obra_url:
        for p in ([antes] if antes else []) + outras:
            if _chave(p) and (_chave(p) == chave_obra_url or chave_obra_url in _chave(p) or _chave(p) in chave_obra_url):
                obra = p
                break
    if not obra and antes:
        obra = antes
    if not obra and indice_cap >= 0 and indice_cap > 0:
        obra = uteis[0]
    if not obra and indice_cap == -1 and len(uteis) == 1 and numero is None:
        obra = uteis[0]
    if not obra and outras and indice_cap >= 0 and indice_cap == 0 and len(outras) >= 1 and not depois:
        obra = outras[0]                                    # "Capítulo 12 - Nome da obra"
    if not obra and not texto:
        obra = obra_url
    if not obra and obra_url:
        obra = obra_url

    resto = [p for p in outras if p != obra]
    titulo_cap = depois
    if not titulo_cap and resto:
        titulo_cap = resto[0] if indice_cap >= 0 or len(uteis) > 1 else ""
    if not titulo_cap:
        titulo_cap = _titulo_da_url(url)
    if titulo_cap and _chave(titulo_cap) == _chave(obra):
        titulo_cap = ""
    if titulo_cap and re.fullmatch(rf"{_PALAVRA_CAP}\s*\d+", titulo_cap, re.IGNORECASE):
        titulo_cap = ""
    return {
        "obra": limpar_nome(obra), "numero": numero, "titulo": limpar_nome(titulo_cap),
        "origem": origem or ("link" if obra_url else ""),
    }


def limpar_nome(texto: str, limite: int = 60) -> str:
    texto = re.sub(r"\s+", " ", str(texto or "")).strip(" -–—|:·•,.")
    return texto[:limite].strip()


def formatar_numero(numero: Optional[str], largura: int = 3) -> str:
    n = normalizar_numero(numero)
    if n is None:
        return ""
    inteiro, _, frac = n.partition(".")
    return inteiro.zfill(largura) + ("." + frac if frac else "")


SEM_OBRA = "Sem obra"
SEM_NUMERO = "Sem número"


def nome_pasta_capitulo(numero: Optional[str], titulo: Optional[str]) -> str:
    """'Cap 005 - Nome do capítulo' (sem repetir a obra). Sem número e sem nome: 'Sem número'."""
    n = formatar_numero(numero)
    t = limpar_nome(titulo or "", 50)
    if n and t:
        return f"Cap {n} - {t}"
    if n:
        return f"Cap {n}"
    return t or SEM_NUMERO


def caminho_relativo(obra: Optional[str], numero: Optional[str], titulo: Optional[str]) -> str:
    """Sempre 'Obra/Cap 005 - Nome': dois níveis, mesmo com um capítulo só. Faltou a obra: 'Sem obra/...'.

    Só devolve '' quando nada foi informado (o usuário escolheu uma pasta e não identificou obra nem capítulo).
    """
    obra = limpar_nome(obra or "", 80)
    if not obra and not formatar_numero(numero) and not limpar_nome(titulo or "", 50):
        return ""
    return f"{obra or SEM_OBRA}/{nome_pasta_capitulo(numero, titulo)}"


def gravar_meta(pasta: Path, obra: str, numero: Optional[str], titulo: str, url: str = "") -> None:
    dados = {"obra": limpar_nome(obra, 80), "numero": normalizar_numero(numero), "titulo": limpar_nome(titulo, 80)}
    if url:
        dados["url"] = str(url)[:500]
    try:
        (Path(pasta) / NOME_META).write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass                                                 # extra: não pode atrapalhar o download


def ler_meta(pasta: Path) -> Dict[str, Any]:
    try:
        dados = json.loads((Path(pasta) / NOME_META).read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def descrever_capitulo(pasta: Path, obra_da_pasta: Optional[str] = None) -> Dict[str, Any]:
    """obra / número / nome de uma pasta de capítulo: do `capitulo.json`, ou deduzidos do nome da pasta."""
    pasta = Path(pasta)
    meta = ler_meta(pasta)
    numero = normalizar_numero(meta.get("numero")) if meta else None
    titulo = limpar_nome(meta.get("titulo", "")) if meta else ""
    obra = limpar_nome(meta.get("obra", ""), 80) if meta else ""
    if not meta:
        m = re.match(r"^Cap (\d{1,4}(?:\.\d{1,2})?)(?: - (.*))?$", pasta.name)
        if m:                                               # pasta criada pelo programa, sem o arquivo de dados
            numero, titulo = normalizar_numero(m.group(1)), limpar_nome(m.group(2) or "")
            obra = obra_da_pasta or ""
        else:                                               # pasta antiga ("nexustoons - capítulo 12")
            achado = extrair_capitulo(pasta.name, "", tira_site=False)
            obra, numero, titulo = achado["obra"] or "", achado["numero"], achado["titulo"] or ""
            if numero is None:
                obra, titulo = obra_da_pasta or "", pasta.name
    if obra_da_pasta and not obra:
        obra = obra_da_pasta
    return {"obra": obra, "numero": numero, "titulo": titulo}


def chave_ordem(numero: Optional[str], titulo: str = "") -> tuple:
    try:
        return (0, float(numero), titulo.lower()) if numero is not None else (1, 0.0, titulo.lower())
    except ValueError:
        return (1, 0.0, titulo.lower())


def rotulo_capitulo(numero: Optional[str], titulo: str = "") -> str:
    """'Capítulo 5 · O encontro' (o nome da obra fica de fora de propósito)."""
    n = normalizar_numero(numero)
    if n and titulo:
        return f"Capítulo {n} · {titulo}"
    if n:
        return f"Capítulo {n}"
    return titulo or "Sem número"
