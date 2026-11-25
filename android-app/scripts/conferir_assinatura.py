"""Depois de compilar o APK, mostra com qual chave ele foi assinado e FALHA se não for a chave esperada.

Sem isso, um build sem o segredo KEYSTORE_BASE64 sai assinado com uma chave aleatória do servidor do GitHub e o Android recusa
a atualização ("conflito com um pacote já existente"). Uso no fluxo, depois do build:
    python android-app/scripts/conferir_assinatura.py caminho/app-debug.apk
Variável opcional KEYSTORE_SHA256 (Settings > Secrets and variables > Actions > Variables): impressão digital esperada, a mesma
que gerar_chave_apk.py mostra. Precisa do apksigner (Android build-tools; já vem no ambiente do GitHub: ANDROID_HOME).
"""
import os
import re
import subprocess
import sys
from pathlib import Path


def impressao(saida: str) -> str:
    achados = re.findall(r"certificate SHA-256 digest:\s*([0-9A-Fa-f]{64})", saida)
    if len(achados) != 1:
        sys.exit(f"ERRO: esperava 1 assinante no APK, achei {len(achados)}.")
    return achados[0].upper()


def apksigner() -> str:
    base = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or ""
    achados = sorted(Path(base, "build-tools").glob("*/apksigner")) if base else []
    if not achados:
        sys.exit("ERRO: não achei o apksigner (defina ANDROID_HOME).")
    return str(achados[-1])


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("uso: conferir_assinatura.py caminho/do.apk")
    r = subprocess.run([apksigner(), "verify", "--print-certs", sys.argv[1]], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("ERRO: o APK não passou na verificação de assinatura:\n" + r.stdout + r.stderr)
    atual = impressao(r.stdout)
    esperado = re.sub(r"[^0-9A-Fa-f]", "", os.environ.get("KEYSTORE_SHA256", "")).upper()
    print(f"Assinatura do APK (SHA-256): {atual}")
    if not esperado:
        print("AVISO: KEYSTORE_SHA256 não definida; não dá para saber se é a mesma chave das versões anteriores.")
    elif esperado != atual:
        sys.exit(f"ERRO: o APK foi assinado com OUTRA chave.\n  esperada: {esperado}\n  do APK:   {atual}\nConfira o segredo KEYSTORE_BASE64: sem a chave original o Android não atualiza o app instalado.")
    else:
        print("OK: mesma chave esperada; o Android aceita como atualização.")


if __name__ == "__main__":
    main()
