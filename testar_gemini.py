"""Teste isolado do Gemini: python testar_gemini.py  (não mostra a chave)."""
import json, time, urllib.request, urllib.error
from baixador.traducao import ambiente
from baixador.traducao.gemini import MODELO_GEMINI, URL_BASE

chave = ambiente.chave_gemini()
if not chave:
    raise SystemExit('Sem chave: preencha key_gemini = "..." no .env')


def chamar(nome, url, corpo=None, limite=30):
    t = time.time()
    req = urllib.request.Request(url, json.dumps(corpo).encode() if corpo else None, {"Content-Type": "application/json", "x-goog-api-key": chave}, method="POST" if corpo else "GET")
    try:
        with urllib.request.urlopen(req, timeout=limite) as r:
            d = json.load(r)
        print(f"[{nome}] OK em {time.time() - t:.1f}s"); return d
    except urllib.error.HTTPError as e:
        m = e.read().decode("utf-8", "replace").replace(chave, "***")[:400]
        print(f"[{nome}] ERRO HTTP {e.code} em {time.time() - t:.1f}s: {m}")
    except Exception as e:
        print(f"[{nome}] FALHOU em {time.time() - t:.1f}s: {type(e).__name__}: {e}")


d = chamar("listar modelos", f"{URL_BASE}/models?pageSize=200")
if d:
    nomes = [m["name"].split("/")[-1] for m in d.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]
    print("modelos disponíveis p/ sua chave:", ", ".join(nomes))
    print("modelo configurado:", MODELO_GEMINI, "->", "EXISTE" if MODELO_GEMINI in nomes else "NÃO EXISTE")
r = chamar("tradução curta", f"{URL_BASE}/models/{MODELO_GEMINI}:generateContent", {"contents": [{"parts": [{"text": "Traduza para português do Brasil, só a frase: Hello, little guy!"}]}]}, 60)
if r:
    print("resposta:", r["candidates"][0]["content"]["parts"][0]["text"])

# 3) o caminho real do programa: página inteira em JSON estruturado, com contexto
from baixador.traducao.gemini import TradutorGemini
from baixador.traducao import inteligencia as ia
t0 = time.time()
try:
    g = TradutorGemini()
    r = g.traduzir_pagina(["WHAT ARE YOU DOING HERE, LITTLE GUY?", "I CAME TO SEE YOU.", "A FEW MOMENTS LATER."], ia.Contexto(anteriores=[("WHERE IS HE?", "Onde ele está?")]))
    print(f"[página inteira] OK em {time.time() - t0:.1f}s | modelo: {g.modelo} | JSON estruturado: {'sim' if g._json else 'NÃO (caiu na lista numerada)'} | balões refeitos: {g.refeitos}")
    for x in r:
        print("  ->", x)
except Exception as e:
    print(f"[página inteira] FALHOU em {time.time() - t0:.1f}s: {type(e).__name__}: {e}")
