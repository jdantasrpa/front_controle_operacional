# INSERIR EM: api/config.py
"""Resolução das fontes de dados e parâmetros de execução da API.

A configuração vem de ``config_projeto.ini``. Caminhos relativos são
resolvidos a partir da raiz do projeto, de modo que o mesmo .ini funcione
em qualquer máquina do time.
"""

from __future__ import annotations

# --- stdlib ---
import configparser
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

RAIZ_PROJETO = Path(__file__).resolve().parents[1]
PASTA_FRONT = RAIZ_PROJETO / 'front'

# COFC_CONFIG permite apontar outro .ini (homologação, testes) sem editar
# o do projeto. Mesma variável reconhecida pelo main.py.
VARIAVEL_CONFIG = 'COFC_CONFIG'


def caminho_config_padrao() -> Path:
    """Resolve o .ini a usar, honrando ``COFC_CONFIG``.

    Returns:
        Caminho do arquivo de configuração.

    Example:
        >>> caminho_config_padrao().suffix
        '.ini'
    """
    return Path(
        os.getenv(VARIAVEL_CONFIG) or (RAIZ_PROJETO / 'config_projeto.ini')
    )


SECAO_FRONT = 'FRONT'
SECAO_DIRETORIOS = 'DIRETORIOS'

BANCO_CONCILIACAO_PADRAO = 'doc/convenios_mock_layout.db'
BANCO_COBRANCA_PADRAO = 'banco/COBRANCA_FINANCEIRO/bd_cobranca_financeiro.db'
PASTA_BANCO_PADRAO = 'banco/DADOS'
HOST_PADRAO = '127.0.0.1'
PORTA_PADRAO = 8000

MARCADOR_USERNAME = '[USERNAME]'


@dataclass(frozen=True)
class Configuracao:
    """Parâmetros imutáveis de execução da API.

    Attributes:
        banco_conciliacao: SQLite legado, ainda usado por /api/retorno e
            /api/contatos (telas antigas, fora do painel atual).
        banco_cobranca: SQLite com as tabelas ``tabela_cobranca_*``.
        pasta_fila_entrada: Fila de comandos do writer (auditoria).
        host: Endereço de escuta do servidor.
        porta: Porta de escuta do servidor.
        pasta_banco: Raiz do banco de arquivos — fonte do Sintético e do
            Analítico (ver ``api.arquivos``).
        pasta_fila_geracao: Fila onde o painel deposita os tickets de
            geração de competência que a automação do Datacob consome.
    """

    banco_conciliacao: Path
    banco_cobranca: Path
    pasta_fila_entrada: Path | None
    host: str
    porta: int
    pasta_banco: Path = RAIZ_PROJETO / PASTA_BANCO_PADRAO
    pasta_fila_geracao: Path = (
        RAIZ_PROJETO / PASTA_BANCO_PADRAO / '_fila_geracao'
    )


def expandir_username(valor: str) -> str:
    """Substitui o marcador ``[USERNAME]`` pelo usuário logado.

    Args:
        valor: Texto bruto lido do .ini.

    Returns:
        Texto com o marcador resolvido.

    Example:
        >>> expandir_username('C:/Users/[USERNAME]/x') != ''
        True
    """
    if MARCADOR_USERNAME not in valor:
        return valor
    return valor.replace(MARCADOR_USERNAME, os.getenv('USERNAME', ''))


def resolver_caminho(valor: str, raiz: Path = RAIZ_PROJETO) -> Path:
    """Resolve um caminho do .ini contra a raiz do projeto.

    Args:
        valor: Caminho absoluto, UNC ou relativo à raiz.
        raiz: Diretório base para caminhos relativos.

    Returns:
        Caminho absoluto correspondente.

    Example:
        >>> resolver_caminho('doc/x.db').is_absolute()
        True
    """
    caminho = Path(expandir_username(valor.strip()))
    return caminho if caminho.is_absolute() else (raiz / caminho).resolve()


def _ler_ini(caminho: Path) -> configparser.ConfigParser:
    """Lê o .ini de configuração; devolve vazio quando ausente.

    Usa ``utf-8-sig``: .ini salvo pelo Bloco de Notas vem com BOM, e com
    ``utf-8`` puro o BOM gruda no primeiro cabeçalho de seção. A seção
    [FRONT] some, a API cai no banco padrão e ninguém percebe.
    """
    parser = configparser.ConfigParser()
    if caminho.exists():
        parser.read(caminho, encoding='utf-8-sig')
    else:
        logger.warning('config_projeto.ini não encontrado em %s', caminho)
    return parser


def _valor(
    parser: configparser.ConfigParser,
    secao: str,
    chave: str,
    padrao: str,
) -> str:
    """Lê uma chave do .ini com fallback explícito."""
    if parser.has_option(secao, chave):
        bruto = parser.get(secao, chave).strip()
        if bruto:
            return bruto
    return padrao


def carregar_configuracao(
    caminho_config: Path | None = None,
) -> Configuracao:
    """Monta a configuração da API a partir do .ini do projeto.

    Args:
        caminho_config: Caminho do .ini; ``None`` resolve em tempo de
            chamada via :func:`caminho_config_padrao`.

    Returns:
        Instância imutável de :class:`Configuracao`.

    Raises:
        ValueError: Se a porta configurada não for um inteiro válido.

    Example:
        >>> carregar_configuracao().host
        '127.0.0.1'
    """
    parser = _ler_ini(caminho_config or caminho_config_padrao())

    banco_conciliacao = resolver_caminho(
        _valor(
            parser, SECAO_FRONT, 'banco_conciliacao', BANCO_CONCILIACAO_PADRAO
        )
    )
    banco_cobranca = resolver_caminho(
        _valor(parser, SECAO_FRONT, 'banco_cobranca', BANCO_COBRANCA_PADRAO)
    )

    fila_bruta = _valor(parser, SECAO_DIRETORIOS, 'pasta_fila_entrada', '')
    pasta_fila = Path(expandir_username(fila_bruta)) if fila_bruta else None

    pasta_banco = resolver_caminho(
        _valor(parser, SECAO_FRONT, 'pasta_banco', PASTA_BANCO_PADRAO)
    )
    # Sem chave própria no .ini, a fila de geração nasce dentro do banco,
    # para o painel funcionar numa instalação nova sem configuração extra.
    fila_geracao_bruta = _valor(
        parser, SECAO_DIRETORIOS, 'pasta_fila_geracao', ''
    )
    pasta_fila_geracao = (
        Path(expandir_username(fila_geracao_bruta))
        if fila_geracao_bruta
        else pasta_banco / '_fila_geracao'
    )

    porta_bruta = _valor(parser, SECAO_FRONT, 'porta', str(PORTA_PADRAO))
    try:
        porta = int(porta_bruta)
    except ValueError as exc:
        logger.error('Porta inválida em [%s] porta: %s', SECAO_FRONT, exc)
        raise ValueError(f'Porta inválida no .ini: {porta_bruta!r}') from exc

    return Configuracao(
        banco_conciliacao=banco_conciliacao,
        banco_cobranca=banco_cobranca,
        pasta_fila_entrada=pasta_fila,
        host=_valor(parser, SECAO_FRONT, 'host', HOST_PADRAO),
        porta=porta,
        pasta_banco=pasta_banco,
        pasta_fila_geracao=pasta_fila_geracao,
    )


@lru_cache(maxsize=1)
def obter_configuracao() -> Configuracao:
    """Devolve a configuração da API (memoizada por processo).

    Returns:
        Instância única de :class:`Configuracao`.

    Example:
        >>> obter_configuracao() is obter_configuracao()
        True
    """
    return carregar_configuracao()
