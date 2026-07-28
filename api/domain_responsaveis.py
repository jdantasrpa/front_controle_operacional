# INSERIR EM: api/domain_responsaveis.py
"""Regras puras dos responsáveis pela conciliação de cada convênio.

Cada vínculo convênio × originadora tem um **titular** (o colaborador dono
da carteira) e, opcionalmente, um **substituto** temporário (férias,
afastamento) com uma data de fim. Quem responde *agora* é o **responsável
efetivo**, calculado — nunca reescrito em massa:

* substituto vigente (hoje ≤ fim, e ainda ativo) responde no lugar do
  titular; passada a data, a carteira volta sozinha ao titular;
* titular desligado (ou ausente) cai para ``Usuário Não Cadastrado`` — o
  convênio fica disponível até alguém assumir, sem precisar varrer e
  reescrever todos os convênios do colaborador desligado.

Assim o desligamento e a devolução automática são consequência do cálculo,
não de um processo em lote. Este módulo não faz I/O: função pura sobre
dicionários.
"""

from __future__ import annotations

# --- stdlib ---
from datetime import datetime
from enum import Enum
from typing import Any, Iterable, Mapping

# --- locais ---
from api.domain import texto

FORMATO_DATA_ISO = '%Y-%m-%d'

# Convênio sem titular ativo: fica disponível até alguém assumir.
USUARIO_NAO_CADASTRADO = 'Usuário Não Cadastrado'


class StatusColaborador(str, Enum):
    """Situação de um colaborador no cadastro de responsáveis."""

    ATIVO = 'ATIVO'
    DESLIGADO = 'DESLIGADO'


STATUS_COLABORADOR_VALIDOS = tuple(s.value for s in StatusColaborador)


def data_iso_valida(valor: Any) -> bool:
    """Diz se o valor é uma data de calendário no formato ``AAAA-MM-DD``.

    Args:
        valor: Texto informado como data; vazio devolve ``False``.

    Returns:
        True quando é uma data real.

    Example:
        >>> data_iso_valida('2026-07-05')
        True
        >>> data_iso_valida('')
        False
    """
    try:
        datetime.strptime(texto(valor), FORMATO_DATA_ISO)
        return True
    except ValueError:
        return False


def _substituicao_vigente(estado: Mapping[str, Any], hoje: str) -> bool:
    """Diz se há substituto respondendo na data de hoje.

    Fim vazio conta como substituição aberta (sem data de retorno).
    """
    substituto = texto(estado.get('substituto'))
    if not substituto:
        return False

    fim = texto(estado.get('substituicao_fim'))
    return not fim or texto(hoje) <= fim


def responsavel_efetivo(
    estado: Mapping[str, Any],
    colaboradores_ativos: Iterable[str],
    hoje: str,
) -> dict[str, str]:
    """Calcula quem responde pelo convênio agora.

    Args:
        estado: ``{titular, substituto, substituicao_fim}`` do vínculo.
        colaboradores_ativos: Nomes de colaboradores com status ATIVO.
        hoje: Data ``AAAA-MM-DD`` de referência.

    Returns:
        ``{responsavel, origem}`` — ``origem`` é ``substituto``,
        ``titular`` ou ``nao_cadastrado``.

    Example:
        >>> responsavel_efetivo(
        ...     {'titular': 'Ana', 'substituto': 'Beto',
        ...      'substituicao_fim': '2026-07-31'},
        ...     ['Ana', 'Beto'], '2026-07-10',
        ... )
        {'responsavel': 'Beto', 'origem': 'substituto'}
        >>> responsavel_efetivo(
        ...     {'titular': 'Ana', 'substituto': 'Beto',
        ...      'substituicao_fim': '2026-07-31'},
        ...     ['Ana', 'Beto'], '2026-08-05',
        ... )
        {'responsavel': 'Ana', 'origem': 'titular'}
        >>> responsavel_efetivo({'titular': 'Ana'}, [], '2026-08-05')
        {'responsavel': 'Usuário Não Cadastrado', 'origem': 'nao_cadastrado'}
    """
    ativos = set(colaboradores_ativos)
    substituto = texto(estado.get('substituto'))
    titular = texto(estado.get('titular'))

    if _substituicao_vigente(estado, hoje) and substituto in ativos:
        return {'responsavel': substituto, 'origem': 'substituto'}

    if titular and titular in ativos:
        return {'responsavel': titular, 'origem': 'titular'}

    return {'responsavel': USUARIO_NAO_CADASTRADO, 'origem': 'nao_cadastrado'}


def validar_substituicao(dados: Mapping[str, Any]) -> list[str]:
    """Lista o que impede uma substituição de ser gravada.

    Exige o substituto; a data de fim é opcional (substituição aberta),
    mas, se vier, tem de ser ``AAAA-MM-DD``.

    Args:
        dados: ``{substituto, substituicao_fim}``.

    Returns:
        Mensagens de erro; lista vazia quando válido.

    Example:
        >>> validar_substituicao({'substituto': 'Beto'})
        []
        >>> validar_substituicao({'substituto': ''})
        ['Informe o substituto.']
        >>> validar_substituicao(
        ...     {'substituto': 'Beto', 'substituicao_fim': '31/07'}
        ... )
        ["Data de fim inválida: '31/07'. Use AAAA-MM-DD."]
    """
    fim = texto(dados.get('substituicao_fim'))

    return [
        *([] if texto(dados.get('substituto')) else ['Informe o substituto.']),
        *(
            [f'Data de fim inválida: {fim!r}. Use AAAA-MM-DD.']
            if fim and not data_iso_valida(fim)
            else []
        ),
    ]


def anexar_historico(
    historico: Iterable[Mapping[str, Any]], evento: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Acrescenta um evento ao histórico, sem tocar na lista original.

    Args:
        historico: Eventos já registrados.
        evento: Novo evento (ação, ator, carimbo etc.).

    Returns:
        Nova lista com o evento no fim.

    Example:
        >>> anexar_historico([], {'acao': 'titular'})
        [{'acao': 'titular'}]
    """
    return [*[dict(item) for item in historico], dict(evento)]
