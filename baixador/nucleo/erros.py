"""Erros do baixador, todos com mensagens prontas para o usuário."""


class ErroBaixador(Exception):
    """Base de todos os erros esperados."""


class UrlInvalida(ErroBaixador):
    """URL malformada, com esquema não suportado ou apontando para rede interna."""


class ErroDeRede(ErroBaixador):
    """Falha de conexão, DNS, tempo esgotado ou erro TLS."""


class ErroHttp(ErroDeRede):
    """O servidor respondeu, mas com status de erro (403, 404, 500...)."""

    def __init__(self, status: int):
        super().__init__(f"O servidor respondeu com erro HTTP {status}.")
        self.status = status


class ArquivoGrande(ErroBaixador):
    """O conteúdo excede o limite de tamanho configurado."""


class FormatoIncompativel(ErroBaixador):
    """O conteúdo baixado não é uma imagem em formato suportado."""


class Cancelado(ErroBaixador):
    """O usuário pediu para interromper a operação."""


class CapturaIndisponivel(ErroBaixador):
    """Não foi possível usar o navegador para a captura de tela."""
