# INSERIR EM: api/repositories/cobranca.py
"""Persistência do módulo Cobrança PJ em ``bd_cobranca_financeiro.db``.

Substitui o ``localStorage`` que o front usava: casos, tentativas de
contato e agendamentos passam a viver no banco do projeto, com auditoria
de autor e carimbo de atualização.
"""

from __future__ import annotations

# --- stdlib ---
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

# --- locais ---
from api.database import conectar, consultar, migrar_colunas_contato
from api.domain import (
    caso_para_dto,
    mes_referencia_para_competencia,
    normalizar_status_cobranca,
    numero,
    texto,
)

logger = logging.getLogger(__name__)

STATUS_FINAIS = ('resolvido', 'sem_sucesso')
ORIGEM_PADRAO = 'manual'

SQL_CASOS = """
    SELECT *
    FROM tabela_cobranca_caso
    ORDER BY COALESCE(atualizado_em, criado_em) DESC, id DESC
"""

SQL_TENTATIVAS = """
    SELECT id, id_caso, data_hora, canal, resultado, observacao
    FROM tabela_cobranca_tentativa
    ORDER BY data_hora DESC, id DESC
"""

SQL_AGENDAMENTOS = """
    SELECT id, id_caso, data_hora, assunto, observacao, concluido
    FROM tabela_cobranca_agendamento
    ORDER BY data_hora ASC, id ASC
"""

# OR IGNORE: a UNIQUE (originador, numero_convenio, mes_referencia)
# absorve regerações a partir da mesma conciliação sem duplicar casos.
SQL_INSERIR_CASO = """
    INSERT OR IGNORE INTO tabela_cobranca_caso (
        originador, numero_convenio, nome_convenio, cnpj_convenio,
        contato_nome, contato_telefone, contato_email,
        mes_referencia, valor_em_aberto, status_cobranca, motivo,
        responsavel, observacao, criado_em, atualizado_em
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

SQL_INSERIR_TENTATIVA = """
    INSERT INTO tabela_cobranca_tentativa (
        id_caso, data_hora, canal, resultado, contato_nome,
        observacao, ator, criado_em
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

SQL_INSERIR_AGENDAMENTO = """
    INSERT INTO tabela_cobranca_agendamento (
        id_caso, data_hora, assunto, observacao, concluido,
        ator, criado_em, atualizado_em
    )
    VALUES (?, ?, ?, ?, 0, ?, ?, ?)
"""


class CasoNaoEncontradoError(LookupError):
    """Sinaliza operação sobre um caso de cobrança inexistente."""


def _agora() -> str:
    """Carimbo de tempo no formato adotado pelas demais tabelas."""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _ou_nulo(valor: Any) -> str | None:
    """Converte string vazia em ``None``.

    Preserva a UNIQUE ``(originador, numero_convenio, mes_referencia)``:
    em SQLite vários NULL coexistem, mas várias strings vazias colidem —
    o que impediria mais de um registro manual por competência.
    """
    limpo = texto(valor)
    return limpo or None


def _agrupar_por_caso(
    linhas: Iterable[Mapping[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    """Indexa filhos (tentativas/agendamentos) pelo ``id_caso``."""
    agrupado: dict[int, list[dict[str, Any]]] = {}
    for linha in linhas:
        agrupado.setdefault(int(linha['id_caso']), []).append(dict(linha))
    return agrupado


def listar_casos(caminho_banco: Path) -> list[dict[str, Any]]:
    """Lê todos os casos com suas tentativas e agendamentos aninhados.

    Args:
        caminho_banco: Arquivo SQLite de cobrança/financeiro.

    Returns:
        Casos no contrato consumido por ``front/js/cobranca.js``.

    Raises:
        BancoIndisponivelError: Se o banco não puder ser aberto.

    Example:
        >>> ...  # doctest: +SKIP
    """
    with conectar(caminho_banco) as conexao:
        migrar_colunas_contato(conexao)
        casos = consultar(conexao, SQL_CASOS)
        tentativas = _agrupar_por_caso(consultar(conexao, SQL_TENTATIVAS))
        agendamentos = _agrupar_por_caso(consultar(conexao, SQL_AGENDAMENTOS))

    return [
        caso_para_dto(
            caso,
            tentativas.get(int(caso['id']), []),
            agendamentos.get(int(caso['id']), []),
        )
        for caso in casos
    ]


def _obter_caso(conexao: sqlite3.Connection, id_caso: int) -> dict[str, Any]:
    """Carrega um caso ou levanta ``CasoNaoEncontradoError``."""
    linha = conexao.execute(
        'SELECT * FROM tabela_cobranca_caso WHERE id = ?', (id_caso,)
    ).fetchone()

    if linha is None:
        raise CasoNaoEncontradoError(f'Caso de cobrança {id_caso} não existe.')
    return dict(linha)


def _montar_dto(conexao: sqlite3.Connection, id_caso: int) -> dict[str, Any]:
    """Recarrega um caso completo após uma escrita."""
    caso = _obter_caso(conexao, id_caso)
    tentativas = consultar(
        conexao,
        'SELECT id, id_caso, data_hora, canal, resultado, observacao'
        ' FROM tabela_cobranca_tentativa WHERE id_caso = ?'
        ' ORDER BY data_hora DESC, id DESC',
        (id_caso,),
    )
    agendamentos = consultar(
        conexao,
        'SELECT id, id_caso, data_hora, assunto, observacao, concluido'
        ' FROM tabela_cobranca_agendamento WHERE id_caso = ?'
        ' ORDER BY data_hora ASC, id ASC',
        (id_caso,),
    )
    return caso_para_dto(caso, tentativas, agendamentos)


def _parametros_do_caso(
    dados: Mapping[str, Any], ator: str, agora: str
) -> tuple[Any, ...]:
    """Traduz o payload do front para a ordem de ``SQL_INSERIR_CASO``."""
    return (
        _ou_nulo(dados.get('originador')),
        _ou_nulo(dados.get('numeroConvenio')),
        texto(dados.get('empresa')),
        texto(dados.get('cnpj')),
        texto(dados.get('contato')),
        texto(dados.get('telefone')),
        texto(dados.get('email')),
        mes_referencia_para_competencia(dados.get('competencia')),
        numero(dados.get('valorDivergente')),
        normalizar_status_cobranca(dados.get('status')),
        texto(dados.get('origem')) or ORIGEM_PADRAO,
        ator,
        texto(dados.get('observacao')),
        agora,
        agora,
    )


def inserir_casos(
    caminho_banco: Path,
    casos: Iterable[Mapping[str, Any]],
    ator: str,
) -> list[dict[str, Any]]:
    """Insere casos de cobrança, ignorando duplicidades por competência.

    A UNIQUE ``(originador, numero_convenio, mes_referencia)`` faz a
    deduplicação no próprio banco: gerar duas vezes a partir da mesma
    conciliação não cria casos repetidos.

    Args:
        caminho_banco: Arquivo SQLite de cobrança/financeiro.
        casos: Payloads no formato do front.
        ator: Usuário responsável pelo registro.

    Returns:
        Os casos efetivamente criados, já no contrato do front.

    Example:
        >>> ...  # doctest: +SKIP
    """
    agora = _agora()
    criados: list[int] = []

    with conectar(caminho_banco) as conexao:
        migrar_colunas_contato(conexao)

        for dados in casos:
            if not texto(dados.get('empresa')):
                logger.warning('Caso sem empresa ignorado: %s', dados)
                continue

            cursor = conexao.execute(
                SQL_INSERIR_CASO,
                _parametros_do_caso(dados, ator, agora),
            )
            if cursor.rowcount:
                criados.append(int(cursor.lastrowid))

        return [_montar_dto(conexao, id_caso) for id_caso in criados]


def atualizar_status(
    caminho_banco: Path, id_caso: int, status: str
) -> dict[str, Any]:
    """Altera o status de um caso.

    Args:
        caminho_banco: Arquivo SQLite de cobrança/financeiro.
        id_caso: Identificador do caso.
        status: Novo status (validado contra o domínio do front).

    Returns:
        O caso atualizado.

    Raises:
        CasoNaoEncontradoError: Se o caso não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    with conectar(caminho_banco) as conexao:
        migrar_colunas_contato(conexao)
        _obter_caso(conexao, id_caso)

        conexao.execute(
            'UPDATE tabela_cobranca_caso'
            ' SET status_cobranca = ?, atualizado_em = ?'
            ' WHERE id = ?',
            (normalizar_status_cobranca(status), _agora(), id_caso),
        )
        return _montar_dto(conexao, id_caso)


def excluir_caso(caminho_banco: Path, id_caso: int) -> None:
    """Remove um caso e, por cascata, tentativas e agendamentos.

    Args:
        caminho_banco: Arquivo SQLite de cobrança/financeiro.
        id_caso: Identificador do caso.

    Raises:
        CasoNaoEncontradoError: Se o caso não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    with conectar(caminho_banco) as conexao:
        _obter_caso(conexao, id_caso)
        conexao.execute(
            'DELETE FROM tabela_cobranca_caso WHERE id = ?', (id_caso,)
        )
        logger.info('Caso de cobrança %s excluído.', id_caso)


def _status_apos_tentativa(status_atual: str, resultado: str) -> str:
    """Aplica a regra de transição já usada hoje pelo front.

    Regularizou encerra o caso; a primeira tentativa em um caso pendente
    o move para negociação. Demais situações preservam o status.
    """
    if resultado == 'regularizou':
        return 'resolvido'
    if status_atual == 'pendente':
        return 'em_negociacao'
    return status_atual


def registrar_tentativa(
    caminho_banco: Path,
    id_caso: int,
    dados: Mapping[str, Any],
    ator: str,
) -> dict[str, Any]:
    """Registra uma tentativa de contato e reavalia o status do caso.

    Args:
        caminho_banco: Arquivo SQLite de cobrança/financeiro.
        id_caso: Identificador do caso.
        dados: Payload com ``dataHora``, ``canal``, ``resultado`` e
            ``observacao``.
        ator: Usuário que registrou a tentativa.

    Returns:
        O caso atualizado, com a nova tentativa no histórico.

    Raises:
        CasoNaoEncontradoError: Se o caso não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    agora = _agora()

    with conectar(caminho_banco) as conexao:
        migrar_colunas_contato(conexao)
        caso = _obter_caso(conexao, id_caso)

        resultado = texto(dados.get('resultado'))
        conexao.execute(
            SQL_INSERIR_TENTATIVA,
            (
                id_caso,
                texto(dados.get('dataHora')),
                texto(dados.get('canal')),
                resultado,
                texto(caso.get('contato_nome')),
                texto(dados.get('observacao')),
                ator,
                agora,
            ),
        )

        status_atual = normalizar_status_cobranca(caso.get('status_cobranca'))
        if status_atual not in STATUS_FINAIS:
            conexao.execute(
                'UPDATE tabela_cobranca_caso'
                ' SET status_cobranca = ?, atualizado_em = ?'
                ' WHERE id = ?',
                (
                    _status_apos_tentativa(status_atual, resultado),
                    agora,
                    id_caso,
                ),
            )

        return _montar_dto(conexao, id_caso)


def agendar_conversa(
    caminho_banco: Path,
    id_caso: int,
    dados: Mapping[str, Any],
    ator: str,
) -> dict[str, Any]:
    """Agenda uma conversa de negociação para o caso.

    Args:
        caminho_banco: Arquivo SQLite de cobrança/financeiro.
        id_caso: Identificador do caso.
        dados: Payload com ``dataHora``, ``assunto`` e ``observacao``.
        ator: Usuário que criou o agendamento.

    Returns:
        O caso atualizado, com o agendamento na agenda.

    Raises:
        CasoNaoEncontradoError: Se o caso não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    agora = _agora()

    with conectar(caminho_banco) as conexao:
        migrar_colunas_contato(conexao)
        caso = _obter_caso(conexao, id_caso)

        conexao.execute(
            SQL_INSERIR_AGENDAMENTO,
            (
                id_caso,
                texto(dados.get('dataHora')),
                texto(dados.get('assunto')) or 'Conversa de negociação',
                texto(dados.get('observacao')),
                ator,
                agora,
                agora,
            ),
        )

        if (
            normalizar_status_cobranca(caso.get('status_cobranca'))
            not in STATUS_FINAIS
        ):
            conexao.execute(
                'UPDATE tabela_cobranca_caso'
                " SET status_cobranca = 'agendado', atualizado_em = ?"
                ' WHERE id = ?',
                (agora, id_caso),
            )

        return _montar_dto(conexao, id_caso)


def concluir_agendamento(
    caminho_banco: Path, id_caso: int, id_agendamento: int
) -> dict[str, Any]:
    """Marca um agendamento como concluído e reavalia o status do caso.

    Sem agendamentos abertos, um caso "agendado" volta para negociação —
    mesma regra que o front aplicava localmente.

    Args:
        caminho_banco: Arquivo SQLite de cobrança/financeiro.
        id_caso: Identificador do caso.
        id_agendamento: Identificador do agendamento.

    Returns:
        O caso atualizado.

    Raises:
        CasoNaoEncontradoError: Se o caso não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    agora = _agora()

    with conectar(caminho_banco) as conexao:
        migrar_colunas_contato(conexao)
        caso = _obter_caso(conexao, id_caso)

        conexao.execute(
            'UPDATE tabela_cobranca_agendamento'
            ' SET concluido = 1, atualizado_em = ?'
            ' WHERE id = ? AND id_caso = ?',
            (agora, id_agendamento, id_caso),
        )

        abertos = conexao.execute(
            'SELECT COUNT(*) FROM tabela_cobranca_agendamento'
            ' WHERE id_caso = ? AND concluido = 0',
            (id_caso,),
        ).fetchone()[0]

        status_atual = normalizar_status_cobranca(caso.get('status_cobranca'))
        if abertos == 0 and status_atual == 'agendado':
            conexao.execute(
                'UPDATE tabela_cobranca_caso'
                " SET status_cobranca = 'em_negociacao', atualizado_em = ?"
                ' WHERE id = ?',
                (agora, id_caso),
            )

        return _montar_dto(conexao, id_caso)
