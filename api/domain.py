# INSERIR EM: api/domain.py
"""Regras puras de tradução entre o banco e o contrato consumido pelo front.

Nenhuma função deste módulo toca I/O: recebem dicionários vindos do
repositório e devolvem novas estruturas no formato que o JavaScript já
espera hoje. Isso mantém a tela intacta e concentra a conversão em um
único ponto testável.
"""

from __future__ import annotations

# --- stdlib ---
import re
from typing import Any, Iterable, Mapping

# Competência exibida no front: MM/AAAA. No banco COFCT o campo
# mes_referencia_conciliacao vem como AAAA-MM.
PADRAO_MES_REFERENCIA = re.compile(r'^(\d{4})-(\d{2})$')
PADRAO_COMPETENCIA = re.compile(r'^(\d{2})/(\d{4})$')
PADRAO_DATA_ISO = re.compile(r'^(\d{4})-(\d{2})-(\d{2})')
PADRAO_DATA_BR = re.compile(r'^(\d{2})/(\d{2})/(\d{4})')

# Status do front. O banco carrega variações históricas ('OK',
# 'DIVERGENTE') que precisam cair no domínio das três opções do painel.
STATUS_CONCILIACAO_VALIDOS = (
    'CONCILIADO',
    'CONCILIADO (PARCIAL)',
    'PENDENTE',
)
STATUS_CONCILIACAO_PADRAO = 'PENDENTE'
SINONIMOS_STATUS_CONCILIACAO = {
    'OK': 'CONCILIADO',
    'CONCILIADA': 'CONCILIADO',
    'DIVERGENTE': 'CONCILIADO (PARCIAL)',
    'PARCIAL': 'CONCILIADO (PARCIAL)',
}

# Cenário e observação ainda não existem em tabela_concilicacao_convenio;
# entram como default até a migração da etapa 2.
CENARIO_CONCILIACAO_PADRAO = 'Repasse único (valor total)'

# Valores aceitos pelo módulo de Cobrança do front (front/js/cobranca.js).
STATUS_COBRANCA_VALIDOS = (
    'pendente',
    'em_negociacao',
    'agendado',
    'resolvido',
    'sem_sucesso',
)
STATUS_COBRANCA_PADRAO = 'pendente'

CANAIS_VALIDOS = ('telefone', 'whatsapp', 'email', 'presencial')
RESULTADOS_VALIDOS = (
    'sem_resposta',
    'contato_efetivo',
    'retornar',
    'recusado',
    'regularizou',
)


def texto(valor: Any) -> str:
    """Normaliza qualquer entrada para string sem espaços nas pontas.

    Args:
        valor: Valor bruto vindo do banco (pode ser ``None``).

    Returns:
        String normalizada; string vazia quando o valor é nulo.

    Example:
        >>> texto('  FCT ')
        'FCT'
        >>> texto(None)
        ''
    """
    return '' if valor is None else str(valor).strip()


def numero(valor: Any) -> float:
    """Converte valores monetários do banco para float seguro.

    Args:
        valor: Número, string numérica ou ``None``.

    Returns:
        O valor como float; ``0.0`` quando nulo ou inconversível.

    Example:
        >>> numero(None)
        0.0
        >>> numero('1234.56')
        1234.56
    """
    if valor is None:
        return 0.0
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


def mes_referencia_para_competencia(mes_referencia: Any) -> str:
    """Converte ``AAAA-MM`` (banco) para ``MM/AAAA`` (front).

    Args:
        mes_referencia: Mês de referência da conciliação.

    Returns:
        Competência no formato ``MM/AAAA``; vazio quando irreconhecível.

    Example:
        >>> mes_referencia_para_competencia('2025-07')
        '07/2025'
    """
    bruto = texto(mes_referencia)

    casado = PADRAO_MES_REFERENCIA.match(bruto)
    if casado:
        ano, mes = casado.groups()
        return f'{mes}/{ano}'

    return bruto if PADRAO_COMPETENCIA.match(bruto) else ''


def competencia_para_mes_referencia(competencia: Any) -> str:
    """Converte ``MM/AAAA`` (front) para ``AAAA-MM`` (banco).

    Args:
        competencia: Competência informada pelo front.

    Returns:
        Mês de referência ``AAAA-MM``; vazio quando irreconhecível.

    Example:
        >>> competencia_para_mes_referencia('07/2025')
        '2025-07'
    """
    bruto = texto(competencia)

    casado = PADRAO_COMPETENCIA.match(bruto)
    if casado:
        mes, ano = casado.groups()
        return f'{ano}-{mes}'

    return bruto if PADRAO_MES_REFERENCIA.match(bruto) else ''


def data_para_br(valor: Any) -> str:
    """Converte data ``AAAA-MM-DD`` (banco) para ``DD/MM/AAAA`` (front).

    Args:
        valor: Data do banco, já em BR ou irreconhecível.

    Returns:
        Data em ``DD/MM/AAAA``; string vazia quando não há data.

    Example:
        >>> data_para_br('2025-07-19')
        '19/07/2025'
        >>> data_para_br('19/07/2025')
        '19/07/2025'
        >>> data_para_br(None)
        ''
    """
    bruto = texto(valor)

    casado = PADRAO_DATA_ISO.match(bruto)
    if casado:
        ano, mes, dia = casado.groups()
        return f'{dia}/{mes}/{ano}'

    return bruto if PADRAO_DATA_BR.match(bruto) else ''


def dia_do_vencimento(valor: Any) -> str:
    """Extrai o dia (``DD``) da data de vencimento.

    O dia separa os vencimentários de uma mesma competência: um convênio
    pode ter mais de uma data de vencimento no mesmo mês de referência.

    Args:
        valor: Data de vencimento em ``AAAA-MM-DD`` ou ``DD/MM/AAAA``.

    Returns:
        Dia com dois dígitos; string vazia quando não há data.

    Example:
        >>> dia_do_vencimento('2025-07-19')
        '19'
        >>> dia_do_vencimento('')
        ''
    """
    data_br = data_para_br(valor)
    return data_br[:2] if data_br else ''


def normalizar_status_conciliacao(status: Any) -> str:
    """Traz o status do banco para o domínio das três opções do painel.

    Args:
        status: Status gravado em ``tabela_concilicacao_convenio``.

    Returns:
        Um dos valores de ``STATUS_CONCILIACAO_VALIDOS``.

    Example:
        >>> normalizar_status_conciliacao('OK')
        'CONCILIADO'
        >>> normalizar_status_conciliacao('DIVERGENTE')
        'CONCILIADO (PARCIAL)'
        >>> normalizar_status_conciliacao('')
        'PENDENTE'
    """
    bruto = texto(status).upper()

    if bruto in STATUS_CONCILIACAO_VALIDOS:
        return bruto

    return SINONIMOS_STATUS_CONCILIACAO.get(bruto, STATUS_CONCILIACAO_PADRAO)


def linha_para_vencimentario(linha: Mapping[str, Any]) -> dict[str, Any]:
    """Traduz uma linha da conciliação no vencimentário que o front espera.

    Cada linha de ``tabela_concilicacao_convenio`` é um vencimentário:
    a competência (``mes_referencia_conciliacao``) somada à data de
    vencimento daquele ciclo.

    Args:
        linha: Registro de ``tabela_concilicacao_convenio``.

    Returns:
        Vencimentário no contrato de ``front/js/data.js``.

    Example:
        >>> venc = linha_para_vencimentario({
        ...     'id': 1, 'mes_referencia_conciliacao': '2025-07',
        ...     'data_vencimento': '2025-07-19', 'status_conciliacao': 'OK',
        ... })
        >>> venc['competencia'], venc['dia_vencimento']
        ('07/2025', '19')
    """
    status = normalizar_status_conciliacao(linha.get('status_conciliacao'))

    return {
        'id': texto(linha.get('id')),
        'competencia': mes_referencia_para_competencia(
            linha.get('mes_referencia_conciliacao')
        ),
        'dia_vencimento': dia_do_vencimento(linha.get('data_vencimento')),
        'conciliacao': {
            'data_vencimento': data_para_br(linha.get('data_vencimento')),
            'data_baixa': data_para_br(linha.get('data_sla_concilicacao')),
            'qtd_dias_inadimplencia': texto(
                linha.get('qtd_dias_sla_pagamento')
            ),
            'data_corte': data_para_br(linha.get('data_corte')),
            'valor_remessa': numero(linha.get('valor_remessa')),
            'valor_retorno': numero(linha.get('valor_retorno')),
            'valor_repasse': numero(linha.get('valor_repasse')),
            'porcentagem_inadimplencia': numero(
                linha.get('porcentagem_inadimplencia')
            ),
            'qtd_contratos': texto(linha.get('qtd_contratos')),
            'status_conciliacao': status,
            # Sem coluna no banco ainda (etapa 2): entra no default até
            # a migração. 'Conciliado' o front deriva do status.
            'cenario_conciliacao': (
                texto(linha.get('cenario_conciliacao'))
                or CENARIO_CONCILIACAO_PADRAO
            ),
            'motivo_falta_conciliacao': texto(
                linha.get('motivo_falta_conciliacao')
            ),
            'observacao': texto(linha.get('observacao')),
        },
        # Preenchidos pelo repositório a partir do banco de cobrança.
        'financeiro': [],
        'cobranca_historico': [],
    }


def resumo_competencia(vencimentarios: Iterable[Mapping[str, Any]]) -> dict:
    """Agrega os vencimentários de uma competência para o Sintético.

    Args:
        vencimentarios: Vencimentários já traduzidos, todos da mesma
            competência.

    Returns:
        Resumo com status consolidado, dias de vencimento e piores
        indicadores de inadimplência.

    Example:
        >>> resumo_competencia([
        ...     {'dia_vencimento': '05',
        ...      'conciliacao': {'status_conciliacao': 'CONCILIADO',
        ...                      'data_baixa': '', 'data_corte': '',
        ...                      'qtd_dias_inadimplencia': '2',
        ...                      'porcentagem_inadimplencia': 1.0}},
        ... ])['status_conciliacao']
        'CONCILIADO'
    """
    itens = list(vencimentarios)
    statuses = {v['conciliacao']['status_conciliacao'] for v in itens}

    if statuses == {'CONCILIADO'}:
        status = 'CONCILIADO'
    elif statuses == {'PENDENTE'}:
        status = 'PENDENTE'
    else:
        status = 'CONCILIADO (PARCIAL)'

    cortes = [v['conciliacao']['data_corte'] for v in itens]
    motivos = {v['conciliacao']['motivo_falta_conciliacao'] for v in itens}

    return {
        'status_conciliacao': status,
        'qtd_vencimentarios': len(itens),
        'dias_venc': ' / '.join(v['dia_vencimento'] for v in itens),
        # O filtro de motivo do Sintético roda no cliente.
        'motivos': sorted(m for m in motivos if m),
        'data_baixa': itens[0]['conciliacao']['data_baixa'] if itens else '',
        'data_corte': ' / '.join(c for c in cortes if c),
        'qtd_dias_inadimplencia': max(
            (
                numero(v['conciliacao']['qtd_dias_inadimplencia'])
                for v in itens
            ),
            default=0.0,
        ),
        'porcentagem_inadimplencia': max(
            (
                numero(v['conciliacao']['porcentagem_inadimplencia'])
                for v in itens
            ),
            default=0.0,
        ),
    }


def linha_para_registro_retorno(
    linha: Mapping[str, Any],
) -> dict[str, Any]:
    """Traduz uma linha da conciliação em um registro de Retorno BPO.

    Args:
        linha: Registro de ``tabela_concilicacao_convenio``.

    Returns:
        Registro no formato consumido por ``front/js/app.js``.

    Example:
        >>> linha_para_registro_retorno(
        ...     {'nome_convenio': 'X', 'mes_referencia_conciliacao': '2025-07',
        ...      'valor_retorno': 9.0}
        ... )['valor']
        9.0
    """
    mes_referencia = linha.get('mes_referencia_conciliacao')

    return {
        'convenio': texto(linha.get('nome_convenio')),
        'competencia': mes_referencia_para_competencia(mes_referencia),
        'valor': numero(linha.get('valor_retorno')),
        'originador': texto(linha.get('originador')),
        'numeroConvenio': texto(linha.get('numero_convenio')),
        'cnpjConvenio': texto(linha.get('cnpj_convenio')),
    }


def normalizar_status_cobranca(status: Any) -> str:
    """Garante que o status gravado pertence ao domínio do front.

    Args:
        status: Status recebido do banco ou do formulário.

    Returns:
        Status válido; ``'pendente'`` quando desconhecido.

    Example:
        >>> normalizar_status_cobranca('RESOLVIDO')
        'resolvido'
    """
    bruto = texto(status).lower()
    return (
        bruto if bruto in STATUS_COBRANCA_VALIDOS else STATUS_COBRANCA_PADRAO
    )


def _tentativa_para_dto(tentativa: Mapping[str, Any]) -> dict[str, Any]:
    """Traduz uma tentativa de contato para o formato do front."""
    return {
        'id': texto(tentativa.get('id')),
        'dataHora': texto(tentativa.get('data_hora')),
        'canal': texto(tentativa.get('canal')),
        'resultado': texto(tentativa.get('resultado')),
        'observacao': texto(tentativa.get('observacao')),
    }


def _agendamento_para_dto(agendamento: Mapping[str, Any]) -> dict[str, Any]:
    """Traduz um agendamento para o formato do front."""
    return {
        'id': texto(agendamento.get('id')),
        'dataHora': texto(agendamento.get('data_hora')),
        'assunto': texto(agendamento.get('assunto')),
        'observacao': texto(agendamento.get('observacao')),
        'concluido': bool(agendamento.get('concluido')),
    }


def caso_para_dto(
    caso: Mapping[str, Any],
    tentativas: Iterable[Mapping[str, Any]],
    agendamentos: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Monta o caso de cobrança no formato que ``cobranca.js`` já consome.

    Args:
        caso: Registro de ``tabela_cobranca_caso``.
        tentativas: Registros de ``tabela_cobranca_tentativa`` do caso.
        agendamentos: Registros de ``tabela_cobranca_agendamento`` do caso.

    Returns:
        Caso completo, com listas aninhadas de tentativas e agendamentos.

    Example:
        >>> caso_para_dto(
        ...     {'id': 1, 'nome_convenio': 'X'}, [], []
        ... )['empresa']
        'X'
    """
    return {
        'id': texto(caso.get('id')),
        'empresa': texto(caso.get('nome_convenio')),
        'cnpj': texto(caso.get('cnpj_convenio')),
        'contato': texto(caso.get('contato_nome')),
        'telefone': texto(caso.get('contato_telefone')),
        'email': texto(caso.get('contato_email')),
        'competencia': mes_referencia_para_competencia(
            caso.get('mes_referencia')
        ),
        'valorDivergente': numero(caso.get('valor_em_aberto')),
        'status': normalizar_status_cobranca(caso.get('status_cobranca')),
        'observacao': texto(caso.get('observacao')),
        'origem': texto(caso.get('motivo')) or 'manual',
        'originador': texto(caso.get('originador')),
        'numeroConvenio': texto(caso.get('numero_convenio')),
        'criadoEm': texto(caso.get('criado_em')),
        'atualizadoEm': texto(caso.get('atualizado_em')),
        'tentativas': [_tentativa_para_dto(t) for t in tentativas],
        'agendamentos': [_agendamento_para_dto(a) for a in agendamentos],
    }
