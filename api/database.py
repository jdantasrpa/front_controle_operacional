# INSERIR EM: api/database.py
"""Acesso de baixo nível ao SQLite — conexões e migração idempotente.

Todo I/O de banco passa por aqui. As camadas de repositório recebem uma
conexão já configurada (``row_factory`` em ``sqlite3.Row``) e não sabem
onde o arquivo mora.
"""

from __future__ import annotations

# --- stdlib ---
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

logger = logging.getLogger(__name__)

TEMPO_LIMITE_SEGUNDOS = 10.0

# Colunas de contato que o formulário do front já coletava e que a versão
# original de tabela_cobranca_caso não previa.
COLUNAS_CONTATO_CASO = (
    ('contato_nome', 'TEXT'),
    ('contato_telefone', 'TEXT'),
    ('contato_email', 'TEXT'),
)


class BancoIndisponivelError(RuntimeError):
    """Sinaliza que o arquivo SQLite configurado não pôde ser aberto."""


@contextmanager
def conectar(
    caminho: Path, *, somente_leitura: bool = False
) -> Iterator[sqlite3.Connection]:
    """Abre uma conexão SQLite como context manager.

    Args:
        caminho: Arquivo .db a abrir.
        somente_leitura: Quando ``True``, abre em modo ``ro`` via URI.

    Yields:
        Conexão com ``row_factory`` em ``sqlite3.Row``.

    Raises:
        BancoIndisponivelError: Se o arquivo não existir ou não abrir.

    Example:
        >>> from pathlib import Path
        >>> with conectar(Path('doc/convenios_mock_layout.db')) as conn:
        ...     isinstance(conn, sqlite3.Connection)
        True
    """
    if not caminho.exists():
        logger.error('Banco não encontrado: %s', caminho)
        raise BancoIndisponivelError(f'Banco não encontrado: {caminho}')

    try:
        if somente_leitura:
            conexao = sqlite3.connect(
                f'file:{caminho.as_posix()}?mode=ro',
                uri=True,
                timeout=TEMPO_LIMITE_SEGUNDOS,
            )
        else:
            conexao = sqlite3.connect(caminho, timeout=TEMPO_LIMITE_SEGUNDOS)
    except sqlite3.Error as exc:
        logger.error('Falha ao abrir %s: %s', caminho, exc)
        raise BancoIndisponivelError(
            f'Falha ao abrir {caminho}: {exc}'
        ) from exc

    conexao.row_factory = sqlite3.Row
    conexao.execute('PRAGMA foreign_keys = ON')

    try:
        yield conexao
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise
    finally:
        conexao.close()


def consultar(
    conexao: sqlite3.Connection,
    sql: str,
    parametros: Sequence[Any] = (),
) -> list[dict[str, Any]]:
    """Executa um SELECT e devolve as linhas como dicionários.

    Args:
        conexao: Conexão SQLite ativa.
        sql: Comando SELECT parametrizado.
        parametros: Valores dos placeholders.

    Returns:
        Lista de dicionários (uma entrada por linha).

    Example:
        >>> ...  # doctest: +SKIP
    """
    return [dict(linha) for linha in conexao.execute(sql, parametros)]


def tabela_existe(conexao: sqlite3.Connection, tabela: str) -> bool:
    """Informa se uma tabela existe no banco conectado.

    Args:
        conexao: Conexão SQLite ativa.
        tabela: Nome da tabela procurada.

    Returns:
        ``True`` quando a tabela existe.

    Example:
        >>> ...  # doctest: +SKIP
    """
    linha = conexao.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (tabela,),
    ).fetchone()
    return linha is not None


def _colunas_da_tabela(conexao: sqlite3.Connection, tabela: str) -> set[str]:
    """Devolve o conjunto de colunas existentes na tabela."""
    return {
        linha['name']
        for linha in conexao.execute(f'PRAGMA table_info({tabela})')
    }


def migrar_colunas_contato(conexao: sqlite3.Connection) -> tuple[str, ...]:
    """Adiciona as colunas de contato em ``tabela_cobranca_caso``.

    O formulário de cobrança do front já coletava nome, telefone e e-mail
    do contato; a tabela original não os previa. A migração é idempotente
    e pode rodar a cada inicialização.

    Args:
        conexao: Conexão SQLite ativa no banco de cobrança.

    Returns:
        Tupla com os nomes das colunas efetivamente criadas.

    Example:
        >>> ...  # doctest: +SKIP
    """
    if not tabela_existe(conexao, 'tabela_cobranca_caso'):
        logger.warning('tabela_cobranca_caso ausente — migração ignorada.')
        return ()

    existentes = _colunas_da_tabela(conexao, 'tabela_cobranca_caso')
    faltantes = [
        (nome, tipo)
        for nome, tipo in COLUNAS_CONTATO_CASO
        if nome not in existentes
    ]

    for nome, tipo in faltantes:
        conexao.execute(
            f'ALTER TABLE tabela_cobranca_caso ADD COLUMN {nome} {tipo}'
        )
        logger.info('Coluna %s criada em tabela_cobranca_caso.', nome)

    return tuple(nome for nome, _ in faltantes)
