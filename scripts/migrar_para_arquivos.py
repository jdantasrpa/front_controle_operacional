# INSERIR EM: scripts/migrar_para_arquivos.py
"""Exporta o SQLite do COFCT para o banco em árvore de arquivos.

Lê as tabelas do .db e escreve a estrutura descrita em ``api.arquivos``:
pasta = tabela, subpasta = competência (quando a tabela tiver), um
``.txt`` por convênio com os registros daquele convênio em JSON.

A migração é idempotente: rodar de novo sobre a mesma origem reescreve
os mesmos arquivos com o mesmo conteúdo.

Uso:
    python scripts/migrar_para_arquivos.py --origem doc/amostra_2anos.db
    python scripts/migrar_para_arquivos.py --destino banco/DADOS --limpar
"""

from __future__ import annotations

# --- stdlib ---
import argparse
import logging
import shutil
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

# --- locais ---
from api.arquivos import caminho_registro, gravar_arquivo, montar_documento

logger = logging.getLogger(__name__)

RAIZ_PROJETO = Path(__file__).resolve().parents[1]
ORIGEM_PADRAO = RAIZ_PROJETO / 'doc' / 'amostra_2anos.db'
DESTINO_PADRAO = RAIZ_PROJETO / 'banco' / 'DADOS'

COLUNA_COMPETENCIA = 'mes_referencia_conciliacao'

# Tabela -> coluna de competência (None = compartilhada, sem subpasta).
TABELAS = {
    'gestao_convenios_originador': None,
    'tabela_concilicacao_convenio': COLUNA_COMPETENCIA,
    'tabela_particularidade': None,
    'tabela_conta_conv': None,
    'tabela_contato': None,
}

# Sem tabela de origem: a aba Secretaria nasce vazia e é preenchida no
# painel (não existe equivalente no COFCT).
TABELAS_SEM_ORIGEM = ('tabela_secretaria_conv',)


def _tabela_existe(conexao: sqlite3.Connection, tabela: str) -> bool:
    """Informa se a tabela existe no banco de origem."""
    linha = conexao.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (tabela,),
    ).fetchone()

    return linha is not None


def ler_tabela(
    conexao: sqlite3.Connection, tabela: str
) -> list[dict[str, Any]]:
    """Lê a tabela inteira como lista de dicionários.

    Args:
        conexao: Conexão SQLite ativa.
        tabela: Tabela a exportar.

    Returns:
        Registros da tabela; vazio quando a tabela não existe.

    Example:
        >>> ...  # doctest: +SKIP
    """
    if not _tabela_existe(conexao, tabela):
        logger.warning('Tabela %s ausente na origem — ignorada.', tabela)
        return []

    return [
        dict(linha) for linha in conexao.execute(f'SELECT * FROM {tabela}')
    ]


def agrupar_por_arquivo(
    registros: Iterable[Mapping[str, Any]], coluna_competencia: str | None
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    """Agrupa registros na chave que vira um arquivo.

    Args:
        registros: Linhas lidas da tabela.
        coluna_competencia: Coluna que separa competências; ``None``
            quando a tabela é compartilhada.

    Returns:
        Dicionário ``(originador, numero_convenio, competencia) ->
        registros``. Competência vazia significa tabela compartilhada.

    Example:
        >>> agrupar_por_arquivo(
        ...     [{'originador': 'A', 'numero_convenio': '1'}], None
        ... )
        {('A', '1', ''): [{'originador': 'A', 'numero_convenio': '1'}]}
    """
    agrupado: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(
        list
    )

    for registro in registros:
        chave = (
            str(registro.get('originador') or '').strip(),
            str(registro.get('numero_convenio') or '').strip(),
            str(registro.get(coluna_competencia) or '').strip()
            if coluna_competencia
            else '',
        )
        agrupado[chave].append(dict(registro))

    return dict(agrupado)


def migrar(
    origem: Path, destino: Path, limpar: bool = False
) -> dict[str, int]:
    """Exporta o SQLite inteiro para a árvore de arquivos.

    Args:
        origem: Arquivo .db do COFCT.
        destino: Raiz do banco de arquivos a criar.
        limpar: Quando ``True``, apaga o destino antes de escrever.

    Returns:
        Dicionário ``tabela -> arquivos gravados``.

    Raises:
        FileNotFoundError: Se o banco de origem não existir.
        sqlite3.Error: Propaga falha de leitura após log.

    Example:
        >>> ...  # doctest: +SKIP
    """
    if not origem.is_file():
        raise FileNotFoundError(f'Banco de origem não encontrado: {origem}')

    if limpar and destino.exists():
        logger.warning('Limpando destino: %s', destino)
        shutil.rmtree(destino)

    contagem: dict[str, int] = {}

    try:
        with sqlite3.connect(origem) as conexao:
            conexao.row_factory = sqlite3.Row
            for tabela, coluna_competencia in TABELAS.items():
                grupos = agrupar_por_arquivo(
                    ler_tabela(conexao, tabela), coluna_competencia
                )
                contagem[tabela] = _gravar_grupos(destino, tabela, grupos)
    except sqlite3.Error as exc:
        logger.error('Falha ao ler %s: %s', origem, exc)
        raise

    for tabela in TABELAS_SEM_ORIGEM:
        (destino / tabela).mkdir(parents=True, exist_ok=True)
        contagem[tabela] = 0

    logger.info('Banco de arquivos gravado em %s: %s', destino, contagem)
    return contagem


def _gravar_grupos(
    destino: Path,
    tabela: str,
    grupos: Mapping[tuple[str, str, str], list[dict[str, Any]]],
) -> int:
    """Grava um arquivo por grupo e devolve quantos foram escritos."""
    for (originador, numero, competencia), registros in grupos.items():
        if not numero:
            logger.warning(
                '%s: registro sem numero_convenio ignorado.', tabela
            )
            continue

        caminho = caminho_registro(
            destino, tabela, originador, numero, competencia or None
        )
        # Sem versão esperada: carga inicial sobrescreve por definição.
        gravar_arquivo(
            caminho,
            montar_documento(
                tabela, originador, numero, registros, competencia or None
            ),
        )

    return len([chave for chave in grupos if chave[1]])


def _argumentos() -> argparse.Namespace:
    """Lê os argumentos de linha de comando."""
    analisador = argparse.ArgumentParser(
        description='Migra o SQLite do COFCT para o banco de arquivos.'
    )
    analisador.add_argument(
        '--origem',
        type=Path,
        default=ORIGEM_PADRAO,
        help=f'Banco .db de origem (padrão: {ORIGEM_PADRAO}).',
    )
    analisador.add_argument(
        '--destino',
        type=Path,
        default=DESTINO_PADRAO,
        help=f'Raiz do banco de arquivos (padrão: {DESTINO_PADRAO}).',
    )
    analisador.add_argument(
        '--limpar',
        action='store_true',
        help='Apaga o destino antes de migrar.',
    )
    return analisador.parse_args()


def main() -> None:
    """Ponto de entrada de linha de comando."""
    logging.basicConfig(
        level=logging.INFO, format='%(levelname)-8s | %(message)s'
    )
    argumentos = _argumentos()

    contagem = migrar(argumentos.origem, argumentos.destino, argumentos.limpar)

    print(f'Banco de arquivos criado em: {argumentos.destino}')
    for tabela, arquivos in contagem.items():
        print(f'  {tabela}: {arquivos} arquivo(s)')
    print(
        '\nPara usar no painel, aponte o config_projeto.ini:\n'
        f'  [FRONT]\n  pasta_banco = '
        f'{argumentos.destino.relative_to(RAIZ_PROJETO).as_posix()}'
    )


if __name__ == '__main__':
    main()
