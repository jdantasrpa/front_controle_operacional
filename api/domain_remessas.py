# INSERIR EM: api/domain_remessas.py
"""Regras puras do rastreio de envio de remessa por vencimento.

Cada vencimento de um convênio numa competência tem uma **situação de
remessa** — pendente ou enviada — com data de envio, usuário responsável e
observação. A *regra* de envio (dias antes da remessa, SLA, corte) mora no
controle da gerência (:mod:`api.domain_conciliacao_gerencia`) e já se
replica; aqui é só o **acompanhamento** do envio e a sua auditoria.

Este módulo não faz I/O: função pura sobre dicionários.
"""

from __future__ import annotations

# --- stdlib ---
from datetime import datetime
from typing import Any, Mapping

# --- locais ---
from api.domain import texto

FORMATO_DATA_ISO = '%Y-%m-%d'

SITUACAO_PENDENTE = 'PENDENTE'
SITUACAO_ENVIADA = 'ENVIADA'
SITUACOES_VALIDAS = (SITUACAO_PENDENTE, SITUACAO_ENVIADA)


def data_iso_valida(valor: Any) -> bool:
    """Diz se o valor é uma data de calendário ``AAAA-MM-DD``.

    Example:
        >>> data_iso_valida('2026-07-02')
        True
        >>> data_iso_valida('')
        False
    """
    try:
        datetime.strptime(texto(valor), FORMATO_DATA_ISO)
        return True
    except ValueError:
        return False


def situacao_normalizada(valor: Any) -> str:
    """Normaliza a situação; cai para PENDENTE quando ausente/invalida."""
    bruto = texto(valor).upper()

    return bruto if bruto in SITUACOES_VALIDAS else SITUACAO_PENDENTE


def validar_remessa(dados: Mapping[str, Any]) -> list[str]:
    """Lista o que impede um registro de envio de ser gravado.

    Enviada exige data de envio; a data, quando informada, é ``AAAA-MM-DD``.

    Args:
        dados: ``situacao``, ``data_envio`` e ``observacao``.

    Returns:
        Mensagens de erro; lista vazia quando válido.

    Example:
        >>> validar_remessa({'situacao': 'PENDENTE'})
        []
        >>> validar_remessa({'situacao': 'ENVIADA'})
        ['Informe a data de envio para marcar como enviada.']
        >>> validar_remessa({'situacao': 'ENVIADA', 'data_envio': '02/07'})
        ["Data de envio inválida: '02/07'. Use AAAA-MM-DD."]
    """
    situacao = situacao_normalizada(dados.get('situacao'))
    envio = texto(dados.get('data_envio'))

    return [
        *(
            [f'Data de envio inválida: {envio!r}. Use AAAA-MM-DD.']
            if envio and not data_iso_valida(envio)
            else []
        ),
        *(
            ['Informe a data de envio para marcar como enviada.']
            if situacao == SITUACAO_ENVIADA and not envio
            else []
        ),
    ]


def montar_registro(
    dados: Mapping[str, Any],
    data_vencimento: str,
    usuario: str,
    agora: str,
) -> dict[str, Any]:
    """Normaliza o payload de envio num registro de remessa.

    O ``usuario`` é o responsável pelo envio/edição (auditoria); pendente
    zera a data de envio.

    Args:
        dados: Payload do formulário de envio.
        data_vencimento: Vencimento ``AAAA-MM-DD`` que o registro descreve.
        usuario: Quem registrou o envio/edição.
        agora: Carimbo da edição.

    Returns:
        Registro pronto para gravar.

    Example:
        >>> r = montar_registro(
        ...     {'situacao': 'ENVIADA', 'data_envio': '2026-07-02'},
        ...     '2026-07-05', 'joao', '2026-07-02T09:00:00',
        ... )
        >>> r['situacao'], r['usuario'], r['data_vencimento']
        ('ENVIADA', 'joao', '2026-07-05')
    """
    situacao = situacao_normalizada(dados.get('situacao'))
    envio = (
        texto(dados.get('data_envio')) if situacao == SITUACAO_ENVIADA else ''
    )

    return {
        'data_vencimento': texto(data_vencimento),
        'situacao': situacao,
        'data_envio': envio,
        'usuario': texto(usuario),
        'observacao': texto(dados.get('observacao')),
        'atualizado_em': texto(agora),
    }
