# INSERIR EM: api/domain_confronto.py
"""Regras puras do confronto financeiro por vencimento.

O **status do financeiro é automático**: sai da diferença entre o que o
extrato mostra (``valor_recebido``) e o que o convênio deveria pagar —
o retorno do BPO **mais o custo** da originadora (``esperado = retorno +
custo``). O custo entra porque ele faz parte do que o convênio deve.

Régua (por convênio e mês):

* **Conciliado** — diferença menor que 1 centavo.
* **Conciliado a maior** — extrato acima do esperado, dentro de 5%.
* **Conciliado a menor** — extrato abaixo do esperado, dentro de 5%.
* **Divergente** — diferença acima de 5%.
* **Sem Extrato** — BPO informou (há retorno), mas não há valor recebido.
* **Sem Retorno** — há valor recebido, mas o BPO não informou retorno.

Este módulo não faz I/O: função pura sobre números. Quem calcula o custo
é :func:`api.domain_convenios.calcular_custo`; aqui só se classifica.
"""

from __future__ import annotations

# --- stdlib ---
from typing import Any

# --- locais ---
from api.domain import numero

LIMITE_CENTAVO = 0.01
LIMITE_PERCENTUAL = 5.0

STATUS_CONCILIADO = 'Conciliado'
STATUS_A_MAIOR = 'Conciliado a maior'
STATUS_A_MENOR = 'Conciliado a menor'
STATUS_DIVERGENTE = 'Divergente'
STATUS_SEM_EXTRATO = 'Sem Extrato'
STATUS_SEM_RETORNO = 'Sem Retorno'

STATUS_CONFRONTO = (
    STATUS_CONCILIADO,
    STATUS_A_MAIOR,
    STATUS_A_MENOR,
    STATUS_DIVERGENTE,
    STATUS_SEM_EXTRATO,
    STATUS_SEM_RETORNO,
)


def classificar_confronto(
    valor_retorno: Any, valor_recebido: Any, custo: Any
) -> dict[str, Any]:
    """Classifica o status do financeiro a partir dos valores e do custo.

    Args:
        valor_retorno: O que o BPO informou (retorno da folha).
        valor_recebido: O que o extrato mostra (repasse recebido).
        custo: O custo da originadora já calculado para a competência.

    Returns:
        ``{status, esperado, custo, recebido, devendo, diferenca,
        percentual}`` — ``devendo`` = esperado − recebido; ``diferenca`` =
        recebido − esperado (positivo = a maior).

    Example:
        >>> c = classificar_confronto(1000, 1020, 0)
        >>> c['status'], c['devendo']
        ('Conciliado a maior', -20.0)
        >>> classificar_confronto(1000, 900, 50)['status']
        'Divergente'
        >>> classificar_confronto(1000, 0, 20)['status']
        'Sem Extrato'
        >>> classificar_confronto(0, 500, 0)['status']
        'Sem Retorno'
    """
    retorno = round(numero(valor_retorno), 2)
    recebido = round(numero(valor_recebido), 2)
    valor_custo = round(numero(custo), 2)
    esperado = round(retorno + valor_custo, 2)

    base = {
        'esperado': esperado,
        'custo': valor_custo,
        'recebido': recebido,
        'devendo': round(esperado - recebido, 2),
        'diferenca': round(recebido - esperado, 2),
        'percentual': 0.0,
    }

    if retorno > 0 and recebido <= 0:
        return {**base, 'status': STATUS_SEM_EXTRATO}
    if recebido > 0 and retorno <= 0:
        return {**base, 'status': STATUS_SEM_RETORNO}

    return {**base, **_classificar_diferenca(base['diferenca'], esperado)}


def _classificar_diferenca(
    diferenca: float, esperado: float
) -> dict[str, Any]:
    """Aplica a régua de 1 centavo / 5% sobre a diferença."""
    if abs(diferenca) < LIMITE_CENTAVO:
        return {'status': STATUS_CONCILIADO, 'percentual': 0.0}

    percentual = (
        round(abs(diferenca) / esperado * 100, 2) if esperado else 100.0
    )
    if percentual <= LIMITE_PERCENTUAL:
        status = STATUS_A_MAIOR if diferenca > 0 else STATUS_A_MENOR
    else:
        status = STATUS_DIVERGENTE

    return {'status': status, 'percentual': percentual}
