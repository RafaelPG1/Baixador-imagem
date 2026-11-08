"""Validação de URLs: só http/https e só hosts públicos.

Bloqueia endereços de rede interna (localhost, 192.168.x.x, 10.x.x.x,
169.254.x.x etc.) para que um site malicioso não consiga usar o baixador
para acessar serviços da sua própria máquina ou rede (SSRF).

Limitação conhecida: a checagem resolve o DNS antes da conexão; um servidor
DNS hostil que mude a resposta entre a checagem e a conexão (DNS rebinding)
não é coberto.
"""

from __future__ import annotations

import ipaddress
import socket
from functools import lru_cache
from urllib.parse import urlsplit

from baixador.nucleo.erros import ErroDeRede, UrlInvalida

ESQUEMAS_PERMITIDOS = ("http", "https")


@lru_cache(maxsize=256)
def verificar_host_publico(host: str) -> None:
    """Levanta erro se o host não resolve ou resolve para endereço não público."""
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        raise ErroDeRede(f"Não foi possível resolver o endereço '{host}'.") from None

    for info in infos:
        texto = info[4][0].split("%")[0]
        ip = ipaddress.ip_address(texto)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise UrlInvalida(
                f"O endereço '{host}' aponta para a rede interna ({ip}); "
                "por segurança, só sites públicos são aceitos."
            )


def validar_url(url: str) -> str:
    """Valida e normaliza uma URL. Devolve a URL limpa ou levanta UrlInvalida."""
    url = (url or "").strip()
    try:
        partes = urlsplit(url)
        host = partes.hostname
    except ValueError:
        raise UrlInvalida("A URL informada é inválida.") from None

    if partes.scheme.lower() not in ESQUEMAS_PERMITIDOS:
        raise UrlInvalida("Só são aceitas URLs http:// ou https://.")
    if not host:
        raise UrlInvalida("A URL informada não tem um endereço de site.")
    if partes.username or partes.password:
        raise UrlInvalida("URLs com usuário e senha embutidos não são aceitas.")

    verificar_host_publico(host)
    return partes.geturl()
