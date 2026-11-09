"""Gera UMA VEZ a chave que assina o APK, para que as próximas versões sejam instaladas por cima (sem apagar as obras baixadas).

Uso (PowerShell, na pasta android-app):   pip install cryptography   e depois   python scripts/gerar_chave_apk.py
Cria `chave-apk.base64.txt` (NÃO envie ao GitHub nem a ninguém: o .gitignore já bloqueia). Abra o arquivo, copie TODO o texto e
cadastre em GitHub > Settings > Secrets and variables > Actions > New repository secret, com o nome KEYSTORE_BASE64.
Depois guarde o arquivo num lugar seguro (backup) e apague-o da pasta do projeto. Se perder a chave, é só gerar outra
e desinstalar o app antes de instalar o novo (as obras baixadas no celular se perdem).
"""
import base64
import datetime
import sys
from pathlib import Path

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID
except ImportError:
    sys.exit("Falta a biblioteca: rode  pip install cryptography  e tente de novo.")

# Valores que o Gradle espera da chave de debug: alias androiddebugkey, senhas "android".
ALIAS, SENHA = b"androiddebugkey", b"android"


def main() -> None:
    saida = Path("chave-apk.base64.txt")
    if saida.exists():
        sys.exit(f"{saida} já existe: não vou sobrescrever. Apague-o se quiser gerar outra chave.")
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Baixador Leitor"), x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Pessoal")])
    agora = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(nome).issuer_name(nome).public_key(chave.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(agora - datetime.timedelta(days=1))
        .not_valid_after(agora + datetime.timedelta(days=365 * 30)).sign(chave, hashes.SHA256())
    )
    p12 = pkcs12.serialize_key_and_certificates(ALIAS, chave, cert, None, serialization.BestAvailableEncryption(SENHA))
    saida.write_text(base64.b64encode(p12).decode("ascii"), encoding="utf-8")
    print(f"Pronto: {saida}\nAgora copie o conteúdo para o segredo KEYSTORE_BASE64 no GitHub (veja as instruções no topo deste script).")


if __name__ == "__main__":
    main()
