"""Compara tradutores EN -> PT-BR com os MESMOS textos. Fica fora do projeto: não altera nada nele.

Uso (PowerShell, na pasta do projeto, com o .venv ativado):
  python comparar_traducao.py                                  # frases de teste embutidas
  python comparar_traducao.py --capitulo "saida\\Obra\\Cap 001"  # usa os balões reais do capítulo (traducao.json)
  python comparar_traducao.py --modelo hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M --max 20
Gera comparacao.md (tabela para você dar nota) e comparacao.csv. O Ollama precisa estar aberto (localhost:11434).
"""
import argparse, csv, json, re, sys, time, urllib.request
from pathlib import Path

EMBUTIDOS = [  # 1-3: reconstruídos do trecho das suas imagens (o original em inglês não estava nelas: confira)
    "How did you know he was the enemy?",
    "He's using the same modified radio as the guys on the second floor.",
    "So it was this guy who was talking to us...",
    "Are you out of your mind?! We're going to die here!",
    "Don't tell me you actually believed that guy.",
    "I'll never forgive you. Not after what you did to her.",
    "What the hell is that thing?",
    "Hey, did you eat yet? Let's grab something.",
    "Damn it, he got away again!",
    "You're late. The boss has been waiting for an hour.",
    "I'm fine. It's just a scratch.",
    "Stop messing around and get over here!",
]
GLOSSARIO = {"Hunter": "Caçador", "Gate": "Portal"}   # exemplo; no projeto vem do glossario.json

# ---------- experimento: o quanto um pós-processamento barato (PT-PT -> PT-BR) resolveria
def _gerundio(inf):
    irreg = {"pôr": "pondo", "por": "pondo", "ter": "tendo", "vir": "vindo", "ver": "vendo", "ir": "indo", "rir": "rindo", "ser": "sendo"}
    return irreg.get(inf, inf[:-1] + "ndo")
TROCAS = [(r"\bconnosco\b", "com a gente"), (r"\bconosco\b", "com a gente"), (r"\bsabias\b", "você sabia"), (r"\btipos\b", "caras"),
          (r"\btipo\b", "cara"), (r"\brapariga\b", "garota"), (r"\bmiúdo\b", "moleque"), (r"\becrã\b", "tela"), (r"\btelemóvel\b", "celular"),
          (r"\bautocarro\b", "ônibus"), (r"\bgajo\b", "cara"), (r"\bfixe\b", "legal"), (r"\bpequeno-almoço\b", "café da manhã")]
def regras_ptbr(t):
    t = re.sub(r"\b(estou|está|estás|estamos|estão|estava|estavam|estive|esteve|ando|anda) a ([a-zçãõáéíóúâêô]+[aeiô]r)\b",
               lambda m: f"{m.group(1)} {_gerundio(m.group(2))}", t, flags=re.I)
    for pad, rep in TROCAS:
        t = re.sub(pad, lambda m, r=rep: r.capitalize() if m.group(0)[0].isupper() else r, t, flags=re.I)
    return t

MARCAS_PT = [r"\b(estou|está|estás|estamos|estão|estava|estavam) a [a-zçãõáéíóúâêô]+r\b", r"\bconnosco\b", r"\bsabias\b", r"\bfizeste\b", r"\bpodes\b",
             r"\bquerias\b", r"\bvocês?\s+têm\b", r"\btipos?\b", r"\brapariga\b", r"\bmiúdo\b", r"\bgajo\b", r"\bpá\b", r"\bfixe\b", r"\bditoso\b", r"\bdeste tipo\b"]
def marcas(t): return sum(len(re.findall(p, t, flags=re.I)) for p in MARCAS_PT)

# ---------- motores
def carregar_argos():
    import argostranslate.translate as tr
    langs = {l.code: l for l in tr.get_installed_languages()}
    t = langs["en"].get_translation(langs["pt"])
    return lambda s: t.translate(s)

def ollama(modelo, prompt, system=None, host="http://localhost:11434"):
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    corpo = {"model": modelo, "messages": msgs, "stream": False, "think": False,
             "options": {"temperature": 0.7, "top_p": 0.6, "top_k": 20, "repeat_penalty": 1.05, "num_ctx": 4096, "num_predict": 300}}
    req = urllib.request.Request(host + "/api/chat", json.dumps(corpo).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.load(r)["message"]["content"].strip()

SIMPLES = "Translate the following text into Portuguese (Brazil), without additional explanation.\n\n{t}"
def prompt_rico(t, anteriores):
    g = "\n".join(f"{a} -> {b}" for a, b in GLOSSARIO.items())
    ctx = "\n".join(anteriores[-3:]) or "(início do capítulo)"
    return ("Traduza o texto abaixo do inglês para o português do Brasil (pt-BR), como diálogo natural de mangá/manhwa. "
            "Use 'você', gerúndio ('está usando'), vocabulário brasileiro; nunca português de Portugal. Preserve o sentido, o tom e a personalidade; "
            "não acrescente nem omita nada. Responda somente com a tradução.\n\n"
            f"Glossário (use exatamente):\n{g}\n\nBalões anteriores (só contexto, não traduza):\n{ctx}\n\nTexto:\n{t}")

def textos_do_capitulo(pasta):
    d = json.loads((Path(pasta) / "traducao.json").read_text(encoding="utf-8"))
    return [b["original"] for im in d["imagens"].values() for b in im["blocos"] if b.get("original")]

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--capitulo"); ap.add_argument("--modelo", default="hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M")
    ap.add_argument("--max", type=int, default=15); ap.add_argument("--sem-ollama", action="store_true"); ap.add_argument("--sem-contexto", action="store_true")
    a = ap.parse_args()
    textos = (textos_do_capitulo(a.capitulo) if a.capitulo else EMBUTIDOS)[:a.max]
    try: argos = carregar_argos()
    except Exception as e: print("Argos indisponível:", e); argos = None
    linhas, ant = [], []
    for i, t in enumerate(textos, 1):
        l = {"original": t}
        for nome, f in (("argos", argos),):
            t0 = time.time(); l[nome] = f(t) if f else ""; l[nome + "_s"] = round(time.time() - t0, 2)
        l["argos_regras"] = regras_ptbr(l["argos"])
        if not a.sem_ollama:
            try:
                t0 = time.time(); l["hy_simples"] = ollama(a.modelo, SIMPLES.format(t=t)); l["hy_simples_s"] = round(time.time() - t0, 1)
                if not a.sem_contexto:
                    t0 = time.time(); l["hy_contexto"] = ollama(a.modelo, prompt_rico(t, ant)); l["hy_contexto_s"] = round(time.time() - t0, 1)
                    ant.append(f"{t} => {l['hy_contexto']}")
            except Exception as e:
                print("Ollama falhou:", e); a.sem_ollama = True
        for k in ("argos", "argos_regras", "hy_simples", "hy_contexto"):
            if k in l: l[k + "_ptpt"] = marcas(l[k])
        linhas.append(l); print(f"[{i}/{len(textos)}] {t[:60]}")
    cols = ["original", "argos", "argos_regras", "hy_simples", "hy_contexto"]
    with open("comparacao.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=sorted({k for l in linhas for k in l}, key=lambda k: (k.split("_")[0] != "original", k))); w.writeheader(); w.writerows(linhas)
    with open("comparacao.md", "w", encoding="utf-8") as f:
        f.write("| # | " + " | ".join(cols) + " |\n|" + "---|" * (len(cols) + 1) + "\n")
        for i, l in enumerate(linhas, 1):
            f.write(f"| {i} | " + " | ".join(l.get(c, "").replace("|", "/").replace("\n", " ") for c in cols) + " |\n")
        f.write("\n**Marcas de PT-PT por motor (menos é melhor):** ")
        f.write(", ".join(f"{k}={sum(l.get(k + '_ptpt', 0) for l in linhas)}" for k in cols[1:]) + "\n\n**Tempo médio por balão (s):** ")
        f.write(", ".join(f"{k}={sum(l.get(k + '_s', 0) for l in linhas) / max(len(linhas), 1):.1f}" for k in ("argos", "hy_simples", "hy_contexto")) + "\n")
    print("Pronto: comparacao.md e comparacao.csv")
if __name__ == "__main__": main()
