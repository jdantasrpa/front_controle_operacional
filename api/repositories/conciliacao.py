# INSERIR EM: api/repositories/conciliacao.py
"""Leitura do banco de conciliação (COFCT) — fonte de Extrato e Retorno.

Somente SELECT: a escrita nesse banco é responsabilidade do writer que
consome a fila de comandos (ver ``main.py``). Aqui isolamos o side effect
de I/O e delegamos toda a tradução para ``api.domain``.
"""

from __future__ import annotations

# --- stdlib ---
import logging
from pathlib import Path
from typing import Any

# --- locais ---
from api.database import BancoIndisponivelError, conectar, consultar
from api.domain import linha_para_registro_retorno, texto

logger = logging.getLogger(__name__)

TABELA_CONCILIACAO = 'tabela_concilicacao_convenio'
TABELA_CONTATO = 'tabela_contato'

SQL_CONCILIACAO = f"""
    SELECT
        id,
        originador,
        mes_referencia_conciliacao,
        numero_convenio,
        nome_convenio,
        cnpj_convenio,
        data_vencimento,
        data_corte,
        valor_remessa,
        valor_retorno,
        valor_repasse,
        status_conciliacao,
        motivo_falta_conciliacao
    FROM {TABELA_CONCILIACAO}
    WHERE COALESCE(TRIM(nome_convenio), '') <> ''
    ORDER BY mes_referencia_conciliacao, nome_convenio
"""

SQL_CONTATOS_ATIVOS = f"""
    SELECT
        numero_convenio,
        nome,
        telefone,
        email
    FROM {TABELA_CONTATO}
    WHERE UPPER(COALESCE(status, '')) = 'ATIVO'
    ORDER BY id DESC
"""


def listar_linhas(caminho_banco: Path) -> list[dict[str, Any]]:
    """Lê as linhas brutas da tabela de conciliação.

    Args:
        caminho_banco: Arquivo SQLite do COFCT.

    Returns:
        Lista de registros da conciliação.

    Raises:
        BancoIndisponivelError: Se o banco não puder ser aberto.

    Example:
        >>> ...  # doctest: +SKIP
    """
    with conectar(caminho_banco, somente_leitura=True) as conexao:
        return consultar(conexao, SQL_CONCILIACAO)


def listar_retorno(caminho_banco: Path) -> list[dict[str, Any]]:
    """Monta os registros de Retorno BPO a partir da conciliação.

    Args:
        caminho_banco: Arquivo SQLite do COFCT.

    Returns:
        Registros no contrato consumido pelo front.

    Example:
        >>> ...  # doctest: +SKIP
    """
    return [
        linha_para_registro_retorno(l) for l in listar_linhas(caminho_banco)
    ]


def mapear_contatos_por_convenio(
    caminho_banco: Path,
) -> dict[str, dict[str, str]]:
    """Indexa o contato ATIVO mais recente de cada convênio.

    Usado para pré-preencher nome, telefone e e-mail ao gerar casos de
    cobrança a partir das divergências — evita redigitação pelo operador.

    Args:
        caminho_banco: Arquivo SQLite do COFCT.

    Returns:
        Dicionário ``numero_convenio -> {contato, telefone, email}``.
        Vazio quando a tabela de contatos não existe no banco.

    Example:
        >>> ...  # doctest: +SKIP
    """
    try:
        with conectar(caminho_banco, somente_leitura=True) as conexao:
            linhas = consultar(conexao, SQL_CONTATOS_ATIVOS)
    except BancoIndisponivelError:
        logger.warning('Contatos indisponíveis em %s.', caminho_banco)
        return {}

    contatos: dict[str, dict[str, str]] = {}
    for linha in linhas:
        convenio = texto(linha.get('numero_convenio'))
        if convenio and convenio not in contatos:
            contatos[convenio] = {
                'contato': texto(linha.get('nome')),
                'telefone': texto(linha.get('telefone')),
                'email': texto(linha.get('email')),
            }
    return contatos
