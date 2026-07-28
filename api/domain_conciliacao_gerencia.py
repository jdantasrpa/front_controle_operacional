# INSERIR EM: api/domain_conciliacao_gerencia.py
"""Regras puras do estado de gerência de convênios pela Conciliação.

A Conciliação mantém, para cada vínculo convênio × originadora, um estado
**próprio** — separado do cadastro que a Gestão de Convênios controla:

* ``em_conciliacao_ativa`` — o liga/desliga da mesa de conciliação. Um
  vínculo desligado não entra na geração de competência.
* O **controle de vencimento** do convênio naquela originadora, que a
  geração **replica** em cada competência nova:

  - ``dia_vencimento`` — o dia do mês do vencimento (1 a 30, teto da regra
    de valor presente / mês comercial de 30 dias). É o que dispara a
    geração pelo cadastro.
  - ``dias_antes_remessa`` — quantos dias antes do vencimento sai a
    remessa (``data_env_remessa = vencimento − N``).
  - ``qtd_dias_sla_pagamento`` — o SLA em dias; a data de SLA da
    conciliação nasce em ``vencimento + N``.
  - ``dias_antes_corte`` — quantos dias antes do vencimento é o corte.

O controle é **por originadora**: a mesma AERONÁUTICA pode vencer num dia
na Alvo Card e noutro em outra originadora. Alterar o controle vale só
para as competências **novas** — as já geradas guardam o que tinham (cada
competência é um arquivo à parte, e a geração é idempotente). Os campos de
controle além do dia são **opcionais**: em branco, a geração deixa a data
correspondente vazia para o Datacob preencher.

Ausência de registro conta como **ligado** e sem controle — assim a base
já existente não deixa de gerar competência só porque ninguém registrou o
estado ainda. É o mesmo princípio da vigência aberta de
:func:`api.domain_convenios.esta_vigente`.

Este módulo não faz I/O: tudo é função pura sobre dicionários.
"""

from __future__ import annotations

# --- stdlib ---
from typing import Any, Mapping

# --- locais ---
from api.domain import texto

# Vínculo sem estado registrado conta como ligado (ver docstring do módulo).
LIGADO_PADRAO = True

# Teto de dias pela regra de valor presente (mês comercial de 30 dias).
DIA_VENCIMENTO_MIN = 1
DIA_VENCIMENTO_MAX = 30

CAMPO_ATIVA = 'em_conciliacao_ativa'
CAMPO_DIA_VENCIMENTO = 'dia_vencimento'
CAMPO_DIAS_ANTES_REMESSA = 'dias_antes_remessa'
CAMPO_QTD_DIAS_SLA = 'qtd_dias_sla_pagamento'
CAMPO_DIAS_ANTES_CORTE = 'dias_antes_corte'

# Campos de controle opcionais (inteiros >= 0). O dia tem regra própria.
CAMPOS_CONTROLE_OPCIONAIS = (
    CAMPO_DIAS_ANTES_REMESSA,
    CAMPO_QTD_DIAS_SLA,
    CAMPO_DIAS_ANTES_CORTE,
)

# Rótulos para as mensagens de validação.
ROTULO_CONTROLE = {
    CAMPO_DIAS_ANTES_REMESSA: 'Dias antes da remessa',
    CAMPO_QTD_DIAS_SLA: 'Qtd de dias de SLA de pagamento',
    CAMPO_DIAS_ANTES_CORTE: 'Dias antes do corte',
}


def dia_vencimento_valido(valor: Any) -> bool:
    """Diz se o valor é um dia de vencimento válido (inteiro de 1 a 30).

    Args:
        valor: Dia informado; texto ou número.

    Returns:
        True quando é um inteiro entre 1 e 30.

    Example:
        >>> dia_vencimento_valido(5)
        True
        >>> dia_vencimento_valido(31)
        False
        >>> dia_vencimento_valido('abc')
        False
    """
    try:
        dia = int(valor)
    except (TypeError, ValueError):
        return False

    return DIA_VENCIMENTO_MIN <= dia <= DIA_VENCIMENTO_MAX


def inteiro_nao_negativo(valor: Any) -> bool:
    """Diz se o valor é um inteiro maior ou igual a zero.

    Args:
        valor: Valor informado; texto ou número.

    Returns:
        True quando converte para inteiro >= 0.

    Example:
        >>> inteiro_nao_negativo(0)
        True
        >>> inteiro_nao_negativo(-1)
        False
    """
    try:
        return int(valor) >= 0
    except (TypeError, ValueError):
        return False


def _normalizar_inteiro(valor: Any) -> Any:
    """Converte para inteiro; mantém vazio como vazio e inválido cru.

    Vazio (``''``/``None``) vira ``''``. Valor conversível vira ``int``.
    Valor inválido é devolvido como veio, de propósito, para que
    :func:`validar_estado` o reprove com uma mensagem clara.
    """
    if valor in ('', None):
        return ''
    try:
        return int(valor)
    except (TypeError, ValueError):
        return valor


def esta_ligado(estado: Mapping[str, Any]) -> bool:
    """Diz se o vínculo está ligado na Conciliação.

    Estado ausente, ou sem a chave, conta como ligado — é o default que
    mantém a base existente entrando na geração.

    Args:
        estado: Registro de estado do vínculo; pode vir vazio.

    Returns:
        True quando o vínculo deve ser acompanhado pela Conciliação.

    Example:
        >>> esta_ligado({})
        True
        >>> esta_ligado({'em_conciliacao_ativa': False})
        False
    """
    if CAMPO_ATIVA not in estado:
        return LIGADO_PADRAO

    return bool(estado.get(CAMPO_ATIVA))


def estado_padrao() -> dict[str, Any]:
    """Estado de um vínculo que a Conciliação ainda não tratou.

    Returns:
        Dicionário com o vínculo ligado e sem controle de vencimento.

    Example:
        >>> estado_padrao()['em_conciliacao_ativa']
        True
    """
    return {
        CAMPO_ATIVA: LIGADO_PADRAO,
        CAMPO_DIA_VENCIMENTO: '',
        CAMPO_DIAS_ANTES_REMESSA: '',
        CAMPO_QTD_DIAS_SLA: '',
        CAMPO_DIAS_ANTES_CORTE: '',
    }


def aplicar_estado(
    atual: Mapping[str, Any], alteracoes: Mapping[str, Any]
) -> dict[str, Any]:
    """Aplica uma alteração parcial sobre o estado atual.

    Campo ausente (``None``) no payload preserva o que está gravado — o
    front manda só o que mudou. Nem ``atual`` nem ``alteracoes`` são
    modificados.

    Args:
        atual: Estado como está gravado (pode vir vazio).
        alteracoes: Campos a alterar; ``None`` em um campo o preserva.

    Returns:
        Novo estado normalizado.

    Example:
        >>> aplicar_estado({}, {'dia_vencimento': 5})['dia_vencimento']
        5
        >>> aplicar_estado({}, {'em_conciliacao_ativa': False})[
        ...     'em_conciliacao_ativa'
        ... ]
        False
    """
    ativa = alteracoes.get(CAMPO_ATIVA)
    resultado: dict[str, Any] = {
        CAMPO_ATIVA: (esta_ligado(atual) if ativa is None else bool(ativa)),
    }
    for campo in (CAMPO_DIA_VENCIMENTO, *CAMPOS_CONTROLE_OPCIONAIS):
        valor = alteracoes.get(campo)
        resultado[campo] = (
            atual.get(campo, '')
            if valor is None
            else _normalizar_inteiro(valor)
        )

    return resultado


def validar_estado(estado: Mapping[str, Any]) -> list[str]:
    """Lista o que impede um estado de gerência de ser gravado.

    O dia de vencimento, quando informado, é inteiro de 1 a 30; os demais
    campos de controle, quando informados, são inteiros >= 0. Todos podem
    ficar vazios (ainda não definidos).

    Args:
        estado: Estado já mesclado, pronto para gravar.

    Returns:
        Mensagens de erro; lista vazia quando o estado é válido.

    Example:
        >>> validar_estado({'dia_vencimento': ''})
        []
        >>> validar_estado({'dia_vencimento': 31})
        ['Dia de vencimento deve ser um inteiro de 1 a 30 (recebido: 31).']
        >>> validar_estado({'dias_antes_remessa': -2})
        ['Dias antes da remessa deve ser um inteiro >= 0 (recebido: -2).']
    """
    dia = estado.get(CAMPO_DIA_VENCIMENTO)
    erros = []
    if dia not in ('', None) and not dia_vencimento_valido(dia):
        erros.append(
            'Dia de vencimento deve ser um inteiro de 1 a 30 '
            f'(recebido: {dia!r}).'
        )

    for campo in CAMPOS_CONTROLE_OPCIONAIS:
        valor = estado.get(campo)
        if valor not in ('', None) and not inteiro_nao_negativo(valor):
            erros.append(
                f'{ROTULO_CONTROLE[campo]} deve ser um inteiro >= 0 '
                f'(recebido: {valor!r}).'
            )

    return erros
