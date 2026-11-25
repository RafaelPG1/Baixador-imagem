"""Ajusta o projeto Android gerado por `npx cap add android` (a pasta android/ não fica no repositório).

- assinatura do APK pela chave do fluxo (~/.android/debug.keystore), declarada no build.gradle;
- minSdk 29 (o plugin SalvarZip grava em Download/ pelo MediaStore, sem pedir permissão de armazenamento);
- versão do app = número da execução do fluxo (VERSION_CODE / VERSION_NAME);
- sem backup automático do Android (a chave de pareamento não deve ir para a nuvem) e sem tráfego sem HTTPS.
Cada troca confere que o texto esperado existe; se o modelo do Capacitor mudar, o fluxo falha em vez de gerar um app errado.
"""
import os
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent / "android"


def trocar(arquivo: Path, padrao: str, novo: str) -> None:
    texto = arquivo.read_text(encoding="utf-8")
    resultado, n = re.subn(padrao, novo, texto, count=1)
    if n != 1:
        sys.exit(f"ERRO: não achei o trecho esperado em {arquivo.name}: {padrao}")
    arquivo.write_text(resultado, encoding="utf-8")


def main() -> None:
    codigo = os.environ.get("VERSION_CODE", "1")
    nome = os.environ.get("VERSION_NAME", "1.0")
    if not codigo.isdigit() or not re.fullmatch(r"[0-9A-Za-z.\-]+", nome):
        sys.exit("ERRO: VERSION_CODE/VERSION_NAME inválidos.")
    trocar(RAIZ / "variables.gradle", r"minSdkVersion\s*=\s*\d+", "minSdkVersion = 29")
    app = RAIZ / "app" / "build.gradle"
    trocar(app, r"versionCode\s+\d+", f"versionCode {codigo}")
    trocar(app, r'versionName\s+"[^"]*"', f'versionName "{nome}"')
    # Chave de assinatura explícita (a que o fluxo grava em ~/.android/debug.keystore): não depende de onde o Gradle procura a chave de debug.
    trocar(app, r"(?m)^android\s*\{", """android {
    signingConfigs {
        debug {
            storeFile file(System.getProperty('user.home') + '/.android/debug.keystore')
            storePassword 'android'
            keyAlias 'androiddebugkey'
            keyPassword 'android'
        }
    }""")
    manifesto = RAIZ / "app" / "src" / "main" / "AndroidManifest.xml"
    trocar(manifesto, r'android:allowBackup="true"', 'android:allowBackup="false"\n        android:usesCleartextTraffic="false"')
    print(f"Projeto Android ajustado: versão {nome} (código {codigo}), minSdk 29.")


if __name__ == "__main__":
    main()
