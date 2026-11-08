"""Partes "inteligentes" da tradução, sem dependências: normalização do texto lido, nomes próprios
(glossário automático), memória de correções do usuário e alertas de revisão.

Tudo aqui é Python puro para poder ser testado sem OCR nem modelos.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from baixador.configuracao import PASTA_PADRAO

NOME_GLOSSARIO = "glossario.json"
NOME_MEMORIA = "memoria_traducao.json"
NOME_REGRAS = "memoria_termos.json"        # termos aprendidos das correções: {termo de origem: {forma errada: forma certa}}
MAX_REGRAS = 400
MAX_MEMORIA = 5000
_TRAVA_ARQUIVOS = threading.Lock()

NOMES_IDIOMAS = {"en": "inglês", "pt": "português", "es": "espanhol", "fr": "francês", "it": "italiano", "de": "alemão"}


@dataclass
class Contexto:
    """O que o tradutor sabe além do texto do balão."""
    de: str = "en"
    para: str = "pt"
    nomes: Sequence[str] = ()                                     # nomes que devem ser mantidos
    termos: Dict[str, str] = field(default_factory=dict)          # termo de origem -> tradução obrigatória
    memoria: Dict[str, str] = field(default_factory=dict)         # correções do usuário (chave normalizada)
    anteriores: List[Tuple[str, str]] = field(default_factory=list)   # (original, tradução) recentes, em ordem
    regras: Dict[str, Dict[str, str]] = field(default_factory=dict)   # termos aprendidos das correções do usuário


# --------------------------------------------------------------------------- texto lido pelo OCR

def corrigir_ocr(texto: str, nomes: Iterable[str] = (), idioma: str = "en") -> str:
    """Conserta confusões comuns do OCR em texto de quadrinhos (conservador): caracteres trocados e, em inglês,
    palavras coladas/cortadas (só quando todas as partes são palavras comuns; nada é inventado)."""
    t = texto.replace("|", "I")
    t = re.sub(r"(?<=[A-Z])0(?=[A-Z])", "O", t)       # D0G -> DOG
    t = re.sub(r"(?<=[A-Z])1(?=[A-Z])", "I", t)       # W1LL -> WILL
    t = re.sub(r"(?<=[A-Z])5(?=[A-Z])", "S", t)
    t = re.sub(r"\s+([,.!?…])", r"\1", t)              # "WORD ." -> "WORD."
    t = " ".join(t.split())
    if idioma == "en":
        from baixador.traducao.ocr_texto import consertar_texto
        t = consertar_texto(t, nomes)
    return t


def _titulo(nome: str) -> str:
    return "-".join(p[:1].upper() + p[1:].lower() for p in nome.split("-"))


def frase_natural(texto: str, nomes: Iterable[str] = ()) -> str:
    """TEXTO EM CAIXA ALTA -> frase em caixa baixa com iniciais de frase e nomes próprios com inicial maiúscula.

    Tradutores automáticos entendem muito melhor "Cheon So-seon" do que "cheon so-seon" (que vira palavras).
    """
    t = texto.lower()
    t = re.sub(r"(^|[.!?…]+[\"')\]]*\s+)([a-zà-ÿ])", lambda m: m.group(1) + m.group(2).upper(), t)
    t = re.sub(r"\bi\b", "I", t)
    for nome in sorted({n for n in nomes if n}, key=len, reverse=True):
        padrao = r"(?<![\w-])" + re.escape(nome.lower()) + r"(?![\w-])"
        t = re.sub(padrao, _titulo(nome), t)
    return t


def maioria_maiuscula(texto: str) -> bool:
    letras = [c for c in texto if c.isalpha()]
    return len(letras) >= 4 and sum(c.isupper() for c in letras) / len(letras) >= 0.8


# --------------------------------------------------------------------------- idioma por palavras comuns

_PALAVRAS = {
    "en": "the and you is are this that with for what not have it i we they will can do don't he she my your to of in on at be was but just why how who there here from me him her his its our their would could should been were".split(),
    "pt": "o os as no na nos nas lo um uma uns umas não você vocês está estão isso esse essa este esta com para por mais muito também são ele ela eles elas vai vão então pelo pela mas seu sua nós aqui porque é foi ser ter tem tinha já só quando como onde quem nada tudo ainda depois antes sempre nunca obrigado".split(),
    "es": "el los las un una unos unas no usted ustedes está están eso ese esa este esta con para por más muy también son él ella ellos ellas va van entonces pero su nosotros aquí porque es fue ser tener tiene tenía ya solo cuando cómo dónde quién nada todo todavía después antes siempre nunca gracias yo tú y lo del".split(),
    "fr": "le la les des une est pas vous je tu nous ils elles que qui dans pour avec sur ce cette mais et ne il elle suis sont être avoir avait très aussi comme quand où rien tout encore après avant toujours jamais merci mon ma mes ton".split(),
    "it": "il lo gli una che non sono per con come di è questo questa ma anche io noi voi cosa qui dove perché molto più sei siamo stato ancora dopo prima sempre mai grazie mio mia tuo".split(),
    "de": "der die das und ist nicht ich du wir sie ein eine mit für auf was wie aber auch hier zu sind war haben hat noch nach vor immer nie danke mein dein sehr jetzt".split(),
}


def _palavras_exclusivas() -> Dict[str, Set[str]]:
    conjuntos = {l: set(p) for l, p in _PALAVRAS.items()}
    saida = {}
    for l, s in conjuntos.items():
        outros: Set[str] = set()
        for l2, s2 in conjuntos.items():
            if l2 != l:
                outros |= s2
        saida[l] = s - outros
    return saida


_EXCLUSIVAS = _palavras_exclusivas()


def pontuar_idiomas(texto: str) -> Dict[str, int]:
    palavras = re.findall(r"[a-zà-ÿ']+", texto.lower().replace("’", "'"))
    return {l: sum(1 for p in palavras if p in s) for l, s in _EXCLUSIVAS.items()}


def vazou_espanhol(texto: str) -> int:
    """Quantas palavras só do espanhol aparecem num texto que deveria estar em português (0 = limpo)."""
    pontos = pontuar_idiomas(texto)
    return pontos["es"] if pontos["es"] > pontos["pt"] else 0


# --------------------------------------------------------------------------- nomes próprios (glossário automático)

_COMUNS_EN = set(
    """the and you your yours are was were been being this that these those with from have has had will would could should can cannot
    not but for what when where who whom whose why how there here then than them they their theirs she her hers his him its our ours
    just only also very much more most some any all one two three four five six seven eight nine ten first second last next now
    again still even ever never always already yet too out off over under into onto about after before because while until since
    like make made take took give gave come came goes going gone went know knew think thought want need see saw look looks tell told
    say said says let lets get got getting find found keep kept feel felt try tried call called leave left help hold held put run ran
    stop move people man men woman women child children kid kids boy girl life world time day days night year years way thing things
    something nothing anything everything someone anyone everyone good bad great big small little old new young long right wrong
    sure okay yes dont doesnt didnt isnt arent wasnt werent wont cant couldnt wouldnt shouldnt ill ive id im youre youll youve
    hes shes its theyre theyll theyve weve were whats thats theres heres lets must may might shall does did done doing being
    sorry please thank thanks hello hey fine fight kill die dead death save must child souls soul over there own other another
    each every both either neither many few less least enough such same different important able back down away home place""".split()
)


def _sem_acentos_pontuacao(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", t.lower())


def detectar_nomes(
    textos: Iterable[str], de: str = "en", sonda: Optional[Callable[[List[str]], List[str]]] = None,
    minimo: int = 2,
) -> List[str]:
    """Nomes próprios prováveis: palavras que se repetem no capítulo e não são palavras comuns.

    `sonda` (opcional) traduz uma lista de palavras soltas; palavras que o tradutor devolve iguais são
    tratadas como nomes (o tradutor "não conhece" a palavra). Sem sonda, exige mais repetições.
    """
    contagem: Dict[str, int] = {}
    for texto in textos:
        for p in re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'-]*[A-Za-zÀ-ÿ]|[A-Za-zÀ-ÿ]", texto):
            chave = p.upper().strip("-'")
            if len(chave) >= 3:
                contagem[chave] = contagem.get(chave, 0) + 1
    minimo_real = minimo if sonda is not None else minimo + 1
    candidatos = []
    for palavra, n in contagem.items():
        if n < minimo_real:
            continue
        simples = _sem_acentos_pontuacao(palavra)
        if de == "en" and (simples in _COMUNS_EN or palavra.lower().replace("'", "") in _COMUNS_EN):
            continue
        if "'" in palavra and de == "en":
            continue                                  # contrações (DON'T, I'M)
        candidatos.append(palavra)
    candidatos.sort(key=lambda p: (-contagem[p], p))
    candidatos = candidatos[:150]
    if sonda is not None and candidatos:
        try:
            saida = sonda([_titulo(c) for c in candidatos])
        except Exception:
            saida = []
        if len(saida) == len(candidatos):
            candidatos = [c for c, s in zip(candidatos, saida) if _sem_acentos_pontuacao(c) == _sem_acentos_pontuacao(s)]
        else:
            candidatos = []
    return sorted(candidatos)


# --------------------------------------------------------------------------- alertas de revisão

def revisar(original: str, traduzido: str, de: str, para: str, confianca: float = 1.0) -> List[str]:
    """Motivos para o usuário olhar este trecho (lista vazia = nada suspeito)."""
    alertas: List[str] = []
    if confianca < 0.6:
        alertas.append("leitura da imagem incerta")
    palavras_o = re.findall(r"[^\W\d_]+", original)
    letras = sum(len(p) for p in palavras_o)
    sem_espaco = len(re.sub(r"\s", "", original))
    if sem_espaco >= 6 and (letras / max(sem_espaco, 1) < 0.55 or (palavras_o and sum(1 for p in palavras_o if not re.search(r"[aeiouyàáâãéêíóôõúü]", p.lower())) / len(palavras_o) > 0.6 and len(palavras_o) >= 2)):
        alertas.append("texto lido parece truncado ou estranho")
    n_palavras_t = len(re.findall(r"[^\W\d_]+", traduzido))
    if n_palavras_t >= 3:
        pontos = pontuar_idiomas(traduzido)
        melhor = max(pontos, key=lambda l: pontos[l])
        if melhor != para and pontos[melhor] >= 2 and pontos[melhor] > pontos.get(para, 0):
            if melhor == de:
                alertas.append("parece não traduzido")
            else:
                alertas.append(f"parece estar em {NOMES_IDIOMAS.get(melhor, melhor)}")
    lo, lt = len(original), len(traduzido)
    if lo > 12 and (lt > lo * 2.6 or lt < lo * 0.4):
        alertas.append("tamanho muito diferente do original")
    palavras_t = [p.lower() for p in re.findall(r"[^\W\d_]+", traduzido)]
    if palavras_t and max(palavras_t.count(p) for p in set(palavras_t)) >= 4 and len(palavras_t) >= 5:
        alertas.append("palavra repetida demais")
    return alertas


# --------------------------------------------------------------------------- arquivos: glossário e memória

def pasta_de_dados(pasta: Path) -> Path:
    """Onde ficam glossário e memória compartilhados: a pasta da obra (ou da biblioteca, `obras/`) ou a própria pasta."""
    pasta = Path(pasta)
    try:
        pai = pasta.resolve().parent
        if pai == PASTA_PADRAO.resolve():
            return pai
        if pai.parent == PASTA_PADRAO.resolve():          # capítulo dentro de uma obra: glossário e memória da obra
            return pai
    except OSError:
        pass
    return pasta


def _ler_json(caminho: Path) -> dict:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def _gravar_json(caminho: Path, dados: dict) -> None:
    temporario = caminho.with_suffix(".tmp")
    try:
        temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temporario, caminho)
    except OSError:
        pass                                          # extra: não pode derrubar a tradução


def carregar_glossario(pasta: Path) -> Tuple[List[str], Dict[str, str]]:
    """Nomes a manter e termos fixos, juntando o glossário da biblioteca e o do capítulo."""
    nomes: Set[str] = set()
    termos: Dict[str, str] = {}
    for base in {pasta_de_dados(pasta), Path(pasta)}:
        d = _ler_json(base / NOME_GLOSSARIO)
        for chave in ("manter", "auto"):
            for n in d.get(chave, []) if isinstance(d.get(chave), list) else []:
                if isinstance(n, str) and 0 < len(n) <= 60:
                    nomes.add(n.strip())
        if isinstance(d.get("termos"), dict):
            for k, v in d["termos"].items():
                if isinstance(k, str) and isinstance(v, str) and 0 < len(k) <= 60 and 0 < len(v) <= 100:
                    termos[k.strip()] = v.strip()
    return sorted(nomes), termos


def salvar_nomes_auto(pasta: Path, nomes: List[str]) -> None:
    """Junta os nomes detectados ao glossário ÚNICO da obra (um só para todos os capítulos).

    Só acrescenta (nomes de capítulos anteriores continuam), preserva `manter`/`termos` escritos à mão e
    incorpora o `auto` de glossários antigos por capítulo, que deixam de ser gravados."""
    with _TRAVA_ARQUIVOS:
        base = pasta_de_dados(pasta)
        caminho = base / NOME_GLOSSARIO
        dados = _ler_json(caminho)
        atuais = [n for n in dados.get("auto", []) if isinstance(n, str)] if isinstance(dados.get("auto"), list) else []
        antigo = Path(pasta) / NOME_GLOSSARIO
        if antigo != caminho:
            velho = _ler_json(antigo).get("auto", [])
            atuais += [n for n in velho if isinstance(n, str)] if isinstance(velho, list) else []
        vistos = {n.casefold() for n in dados.get("manter", []) if isinstance(n, str)}
        final: List[str] = []
        for n in atuais + list(nomes):
            n = n.strip()
            if n and n.casefold() not in vistos:
                vistos.add(n.casefold())
                final.append(n)
        dados["auto"] = sorted(final)
        dados.setdefault("manter", [])
        dados.setdefault("termos", {})
        _gravar_json(caminho, dados)
        if antigo != caminho and antigo.exists():
            d = _ler_json(antigo)
            if d.get("manter") or d.get("termos"):
                d.pop("auto", None)                           # o que o usuário escreveu no capítulo continua valendo
                _gravar_json(antigo, d)
            else:
                try:
                    antigo.unlink()
                except OSError:
                    pass


def migrar_glossarios(raiz: Path) -> Dict[str, List[str]]:
    """Leva os `glossario.json` que ficaram dentro de cada capítulo para o glossário único da obra.

    Junta `auto`, `manter` e `termos` (em conflito de termo, vale o que já estava na obra) e só apaga o arquivo do
    capítulo depois de confirmar que o da obra foi gravado com tudo. Devolve {"obras": [...], "erros": [...]}."""
    relatorio: Dict[str, List[str]] = {"obras": [], "erros": []}
    raiz = Path(raiz)
    try:
        obras = sorted(p for p in raiz.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return relatorio
    with _TRAVA_ARQUIVOS:
        for obra in obras:
            try:
                caps = sorted(c for c in obra.iterdir() if c.is_dir() and not c.name.startswith(".") and (c / NOME_GLOSSARIO).is_file())
            except OSError:
                continue
            if not caps:
                continue
            destino = obra / NOME_GLOSSARIO
            dados = _ler_json(destino)
            listas = {k: [n for n in dados.get(k, []) if isinstance(n, str)] if isinstance(dados.get(k), list) else [] for k in ("auto", "manter")}
            termos = dict(dados["termos"]) if isinstance(dados.get("termos"), dict) else {}
            for cap in caps:
                d = _ler_json(cap / NOME_GLOSSARIO)
                for k in ("auto", "manter"):
                    if isinstance(d.get(k), list):
                        listas[k] += [n for n in d[k] if isinstance(n, str)]
                if isinstance(d.get("termos"), dict):
                    for t, v in d["termos"].items():
                        termos.setdefault(t, v)
            vistos: Set[str] = set()
            final: Dict[str, List[str]] = {}
            for k in ("manter", "auto"):                      # o que o usuário escreveu tem prioridade sobre o detectado
                final[k] = []
                for n in listas[k]:
                    n = n.strip()
                    if n and n.casefold() not in vistos:
                        vistos.add(n.casefold())
                        final[k].append(n)
            final["auto"].sort()
            novo = {**dados, "manter": final["manter"], "auto": final["auto"], "termos": termos}
            _gravar_json(destino, novo)
            if _ler_json(destino) != novo:
                relatorio["erros"].append(f"{obra.name}: não consegui gravar o glossário da obra; os dos capítulos ficaram como estavam.")
                continue
            for cap in caps:
                try:
                    (cap / NOME_GLOSSARIO).unlink()
                except OSError as erro:
                    relatorio["erros"].append(f"{obra.name}/{cap.name}: {erro}")
            relatorio["obras"].append(f"{obra.name} ({len(caps)} capítulo(s))")
    return relatorio


def chave_memoria(texto: str) -> str:
    return re.sub(r"[\W_]+", " ", texto.casefold()).strip()


def carregar_memoria(pasta: Path) -> Dict[str, str]:
    d = _ler_json(pasta_de_dados(pasta) / NOME_MEMORIA)
    return {k: v for k, v in d.items() if isinstance(k, str) and isinstance(v, str)}


def lembrar(pasta: Path, original: str, traducao: str) -> None:
    """Guarda uma correção feita pelo usuário para reaplicá-la quando o mesmo balão aparecer de novo."""
    chave = chave_memoria(original)
    if len(chave) < 2 or not traducao.strip():
        return
    with _TRAVA_ARQUIVOS:
        caminho = pasta_de_dados(pasta) / NOME_MEMORIA
        dados = carregar_memoria(pasta)
        dados.pop(chave, None)
        dados[chave] = traducao.strip()[:600]
        while len(dados) > MAX_MEMORIA:
            dados.pop(next(iter(dados)))
        _gravar_json(caminho, dados)


def contexto_da_pasta(pasta: Path, de: str, para: str) -> Contexto:
    nomes, termos = carregar_glossario(pasta)
    return Contexto(de=de, para=para, nomes=nomes, termos=termos, memoria=carregar_memoria(pasta), regras=carregar_regras(pasta))


# --------------------------------------------------------------------------- texto final: espaçamento e consistência

def polir_espacos(texto: str) -> str:
    """Normaliza espaços e pontuação do texto traduzido (sem mexer nas palavras)."""
    t = texto.replace("\u00a0", " ")
    t = re.sub(r"\s*\n\s*", " ", t)
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r"\s+([,.;:!?…%)\]»”])", r"\1", t)                  # "palavra ." -> "palavra."
    t = re.sub(r"([(\[«“])\s+", r"\1", t)                          # "( texto" -> "(texto"
    t = re.sub(r"([,;:!?])(?=[^\W\d_])", r"\1 ", t)                 # "oi,mundo" -> "oi, mundo" (não mexe em 10:30 nem 3,5)
    t = re.sub(r"([.!?…])(?=[A-ZÀ-Ý][a-zà-ÿ])", r"\1 ", t)            # "fim.Ele" -> "fim. Ele"
    t = re.sub(r"\.{4,}", "...", t)
    t = re.sub(r"!{4,}", "!!!", t)
    t = re.sub(r"\?{4,}", "???", t)
    return t.strip()


def _com_caixa(modelo: str, novo: str) -> str:
    if len(modelo) > 1 and modelo.isupper():
        return novo.upper()
    if modelo[:1].isupper():
        return novo[:1].upper() + novo[1:]
    return novo


def harmonizar_nomes(traduzido: str, nomes: Iterable[str]) -> str:
    """Nomes do glossário sempre com a grafia exata do glossário (ex.: "jin-woo" -> "Jin-Woo")."""
    for nome in nomes:
        if len(nome) < 3:
            continue
        padrao = re.compile(r"(?<![\w-])" + re.escape(nome) + r"(?![\w-])", re.I)
        # em texto todo em caixa alta o nome fica em caixa alta também
        traduzido = padrao.sub(lambda m: nome.upper() if len(m.group(0)) > 2 and m.group(0).isupper() and traduzido.isupper() else nome, traduzido)
    return traduzido


_PALAVRAS_FRACAS = frozenset(
    "the and for you your with that this have from they will what when where who how not but are was were been has had his her its our them then than "
    "there here just like into out over only very can could would should about all any one two get got let say said now yes".split()
)


def _palavras(texto: str) -> List[str]:
    return re.findall(r"[^\W\d_][\w'’-]*", texto)


def carregar_regras(pasta: Path) -> Dict[str, Dict[str, str]]:
    d = _ler_json(pasta_de_dados(pasta) / NOME_REGRAS)
    saida: Dict[str, Dict[str, str]] = {}
    for gatilho, pares in d.items():
        if isinstance(gatilho, str) and isinstance(pares, dict):
            validos = {e: c for e, c in pares.items() if isinstance(e, str) and isinstance(c, str) and e.strip() and c.strip()}
            if validos:
                saida[gatilho] = validos
    return saida


def _trocas_da_correcao(antes: str, depois: str) -> List[Tuple[str, str]]:
    """Pares (forma que o tradutor deu, forma que o usuário escolheu) em trocas pequenas, palavra por palavra."""
    import difflib

    a, b = _palavras(antes), _palavras(depois)
    if not a or not b or len(a) > 40 or len(b) > 40:
        return []
    pares: List[Tuple[str, str]] = []
    for op, i0, i1, j0, j1 in difflib.SequenceMatcher(a=[w.casefold() for w in a], b=[w.casefold() for w in b], autojunk=False).get_opcodes():
        if op != "replace" or i1 - i0 > 3 or j1 - j0 > 3:
            continue
        errada, certa = " ".join(a[i0:i1]), " ".join(b[j0:j1])
        if len(errada) >= 3 and len(certa) >= 2 and errada.casefold() != certa.casefold():
            pares.append((errada, certa))
    return pares


def _gatilhos(original: str, errada: str, traduzir_palavra: Optional[Callable[[str], str]]) -> List[str]:
    """Palavras do original que explicam a forma errada: a que o tradutor, sozinho, traduz como a errada,
    ou (nomes e termos parecidos) a que se parece com ela. Sem explicação clara, não se aprende nada."""
    import difflib

    candidatas = []
    for w in _palavras(original):
        c = w.casefold().strip("'’-")
        if len(c) >= 3 and c not in _PALAVRAS_FRACAS and c not in candidatas:
            candidatas.append(c)
    achadas = []
    for c in candidatas[:12]:
        if difflib.SequenceMatcher(None, c, errada.casefold()).ratio() >= 0.7:
            achadas.append(c)
        elif traduzir_palavra is not None:
            try:
                if traduzir_palavra(c).strip().casefold() == errada.casefold():
                    achadas.append(c)
            except Exception:
                pass
    return achadas


def aprender_correcao(pasta: Path, original: str, antes: str, depois: str, traduzir_palavra: Optional[Callable[[str], str]] = None) -> int:
    """Aprende termos a partir de uma correção (tradução automática `antes` -> a que o usuário escolheu `depois`).

    A regra só vale quando o termo de origem aparece de novo no balão e a forma errada está no resultado,
    então traduções corretas nunca são alteradas. Devolve quantas regras novas foram gravadas.
    """
    if not antes.strip() or not depois.strip() or chave_memoria(antes) == chave_memoria(depois):
        return 0
    novas: Dict[str, Dict[str, str]] = {}
    for errada, certa in _trocas_da_correcao(antes, depois):
        for gatilho in _gatilhos(original, errada, traduzir_palavra)[:2]:
            novas.setdefault(gatilho, {})[errada.casefold()] = certa
    if not novas:
        return 0
    with _TRAVA_ARQUIVOS:
        regras = carregar_regras(pasta)
        total = 0
        for g, pares in novas.items():
            for e, c in pares.items():
                if regras.get(g, {}).get(e) != c:
                    regras.setdefault(g, {})[e] = c
                    total += 1
        while sum(len(v) for v in regras.values()) > MAX_REGRAS:
            regras.pop(next(iter(regras)))
        _gravar_json(pasta_de_dados(pasta) / NOME_REGRAS, regras)
    return total


def aplicar_regras(original: str, traduzido: str, regras: Dict[str, Dict[str, str]]) -> str:
    """Reaplica termos aprendidos: só troca a palavra inteira, só se o termo de origem estiver no balão."""
    if not regras or not traduzido:
        return traduzido
    palavras = {w.casefold().strip("'’-") for w in _palavras(original)}
    for gatilho, pares in regras.items():
        if gatilho not in palavras:
            continue
        for errada, certa in pares.items():
            if re.search(r"(?<![\w-])" + re.escape(certa) + r"(?![\w-])", traduzido, re.I):
                continue                                        # já está certo
            traduzido = re.sub(r"(?<![\w-])" + re.escape(errada) + r"(?![\w-])", lambda m, c=certa: _com_caixa(m.group(0), c), traduzido, flags=re.I)
    return traduzido


def procurar_memoria(memoria: Dict[str, str], original: str) -> Optional[str]:
    """Correção já feita para este balão: igual, ou igual depois de consertar o OCR, ou quase igual (OCR um pouco diferente)."""
    if not memoria:
        return None
    for texto in (original, corrigir_ocr(original)):
        achada = memoria.get(chave_memoria(texto))
        if achada:
            return achada
    chave = chave_memoria(corrigir_ocr(original))
    if len(chave) < 18 or chave.count(" ") < 2:
        return None                                             # curto demais: parecido não basta
    import difflib

    melhor, nota = None, 0.0
    for k, v in memoria.items():
        if abs(len(k) - len(chave)) > max(3, len(chave) // 12) or k[:1] != chave[:1]:
            continue
        m = difflib.SequenceMatcher(None, chave, k, autojunk=False)
        if m.real_quick_ratio() < 0.93 or m.quick_ratio() < 0.93:
            continue
        r = m.ratio()
        if r > nota:
            melhor, nota = v, r
    return melhor if nota >= 0.94 else None


def refinar(original: str, traduzido: str, ctx: "Contexto") -> str:
    """Acabamento do texto traduzido: nomes com a grafia do glossário, termos aprendidos e espaçamento limpo."""
    return polir_espacos(aplicar_regras(original, harmonizar_nomes(traduzido.strip(), ctx.nomes), ctx.regras))
