# INSERIR EM: api/domain_geracao.py
"""Regras puras da geração de vencimentários de uma competência.

Um **vencimentário** é uma linha de ``tabela_concilicacao_convenio``: a
competência (``mes_referencia_conciliacao``) somada a uma data de
vencimento daquele ciclo. Um convênio costuma ter mais de um vencimento
por mês (GOV. GOIÁS e AERONÁUTICA vencem dia 05 e 20), então cada
competência de um convênio guarda um ou mais vencimentários.

Este módulo responde três necessidades do negócio, todas com função pura
sobre dicionários — nada de I/O:

* **Clonar o mês anterior** — o esqueleto do mês seguinte nasce copiando
  os dias de vencimento, o SLA e o corte do mês anterior, com os valores
  zerados e status ``PENDENTE``. É o "gerar competência" massivo: o
  operador vê a competência nova na hora e a automação do Datacob só
  completa os saldos depois.
* **Vencimentário avulso** — quando é um convênio só, o operador informa
  todos os campos à mão; aqui montamos e validamos o registro.
* **Solicitação de geração** — o ticket que o painel deixa na fila para a
  automação do Datacob preencher os valores do mês recém-clonado.

A chave que distingue dois vencimentários de um mesmo convênio numa
competência é a **data de vencimento**: é por ela que a exclusão mira um
vencimento específico. O ``id`` é apenas um identificador opaco, único no
histórico do convênio, que o front usa para saber qual vencimentário
está aberto.
"""

from __future__ import annotations

# --- stdlib ---
import calendar
import re
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping

# --- locais ---
from api.domain import numero, texto
from api.domain_convenios import (
    MESES_NO_ANO,
    competencia_valida,
    deslocar_competencia,
)

PADRAO_DATA_ISO = re.compile(r'^(\d{4})-(\d{2})-(\d{2})$')

# Campos de um registro de vencimentário, na ordem gravada no .txt do
# banco de arquivos (ver banco/DADOS/tabela_concilicacao_convenio).
CAMPOS_VENCIMENTARIO = (
    'id',
    'originador',
    'mes_referencia_conciliacao',
    'numero_convenio',
    'nome_convenio',
    'cnpj_convenio',
    'data_vencimento',
    'data_env_remessa',
    'data_sla_concilicacao',
    'qtd_dias_sla_pagamento',
    'data_corte',
    'valor_remessa',
    'valor_retorno',
    'valor_repasse',
    'status_conciliacao',
    'motivo_falta_conciliacao',
    'porcentagem_inadimplencia',
    'criado_em',
    'atualizado_em',
)

# Datas do ciclo que acompanham o dia do vencimento ao trocar de mês.
# ``qtd_dias_sla_pagamento`` fica de fora de propósito: é uma duração
# (número de dias), não uma data, e não desloca.
CAMPOS_DATA_DO_CICLO = (
    'data_vencimento',
    'data_env_remessa',
    'data_sla_concilicacao',
    'data_corte',
)

# Valores zerados no esqueleto: o mês nasce sem saldo, aguardando o
# Datacob (massivo) ou o operador (avulso).
STATUS_INICIAL = 'PENDENTE'
VALOR_ZERADO = 0.0

STATUS_CONCILIACAO_VALIDOS = (
    'CONCILIADO',
    'CONCILIADO (PARCIAL)',
    'PENDENTE',
)

TIPO_SOLICITACAO_GERACAO = 'GERAR_COMPETENCIA'


# =====================================================================
# Datas: mover o dia de um mês para o outro
# =====================================================================
def mudar_competencia_da_data(data_iso: Any, competencia_destino: str) -> str:
    """Reposiciona uma data ``AAAA-MM-DD`` noutra competência, mantendo o dia.

    É o coração da clonagem: o dia 05 de julho vira o dia 05 de agosto. Um
    dia que não existe no mês de destino (31 num mês de 30) é ancorado no
    último dia do mês, para nunca gerar data inválida.

    Args:
        data_iso: Data de origem em ``AAAA-MM-DD``; vazia devolve vazio.
        competencia_destino: Competência ``AAAA-MM`` de destino.

    Returns:
        A data no mês de destino, em ``AAAA-MM-DD``; vazio quando a data
        de origem ou a competência é inválida.

    Example:
        >>> mudar_competencia_da_data('2026-07-05', '2026-08')
        '2026-08-05'
        >>> mudar_competencia_da_data('2026-01-31', '2026-02')
        '2026-02-28'
        >>> mudar_competencia_da_data('', '2026-08')
        ''
    """
    casado = PADRAO_DATA_ISO.match(texto(data_iso))
    if not casado or not competencia_valida(competencia_destino):
        return ''

    ano, mes = (int(parte) for parte in competencia_destino.split('-'))
    dia = int(casado.group(3))
    ultimo_dia = calendar.monthrange(ano, mes)[1]

    return f'{ano:04d}-{mes:02d}-{min(dia, ultimo_dia):02d}'


def data_na_competencia(competencia: str, dia: Any) -> str:
    """Monta a data ``AAAA-MM-DD`` de um dia dentro de uma competência.

    Ancora o dia no último dia do mês quando ele não existe (dia 30 em
    fevereiro vira 28/29), para nunca gerar data inválida.

    Args:
        competencia: Competência ``AAAA-MM``.
        dia: Dia do mês (1 a 31); inválido devolve vazio.

    Returns:
        A data ``AAAA-MM-DD``; vazio quando a competência ou o dia é
        inválido.

    Example:
        >>> data_na_competencia('2026-08', 5)
        '2026-08-05'
        >>> data_na_competencia('2026-02', 30)
        '2026-02-28'
        >>> data_na_competencia('2026-08', 0)
        ''
    """
    try:
        numero_dia = int(dia)
    except (TypeError, ValueError):
        return ''

    if not competencia_valida(competencia) or numero_dia < 1:
        return ''

    ano, mes = (int(parte) for parte in competencia.split('-'))
    ultimo_dia = calendar.monthrange(ano, mes)[1]

    return f'{ano:04d}-{mes:02d}-{min(numero_dia, ultimo_dia):02d}'


def deslocar_dias(data_iso: Any, dias: int) -> str:
    """Anda ``dias`` para frente (ou para trás) a partir de uma data.

    Args:
        data_iso: Data base ``AAAA-MM-DD``; inválida devolve vazio.
        dias: Deslocamento em dias; negativo anda para trás.

    Returns:
        A nova data ``AAAA-MM-DD``; vazio se a base for inválida.

    Example:
        >>> deslocar_dias('2026-08-05', -3)
        '2026-08-02'
        >>> deslocar_dias('2026-08-05', 17)
        '2026-08-22'
        >>> deslocar_dias('', 3)
        ''
    """
    casado = PADRAO_DATA_ISO.match(texto(data_iso))
    if not casado:
        return ''

    base = datetime(
        int(casado.group(1)), int(casado.group(2)), int(casado.group(3))
    )

    return (base + timedelta(days=int(dias))).strftime('%Y-%m-%d')


def dia_do_vencimento(data_iso: Any) -> str:
    """Extrai o dia (``DD``) de uma data de vencimento ``AAAA-MM-DD``.

    Args:
        data_iso: Data de vencimento; vazia devolve vazio.

    Returns:
        Dia com dois dígitos; string vazia quando não há data válida.

    Example:
        >>> dia_do_vencimento('2026-08-05')
        '05'
        >>> dia_do_vencimento('')
        ''
    """
    casado = PADRAO_DATA_ISO.match(texto(data_iso))
    return casado.group(3) if casado else ''


def dias_de_vencimento(
    registros: Iterable[Mapping[str, Any]],
) -> list[str]:
    """Lista os dias de vencimento distintos de um conjunto de registros.

    Alimenta a solicitação de geração: é o padrão de dias (``['05',
    '20']``) que a automação do Datacob usa para saber quantos
    vencimentos o mês tem.

    Args:
        registros: Vencimentários de uma competência.

    Returns:
        Dias com dois dígitos, únicos e ordenados.

    Example:
        >>> dias_de_vencimento(
        ...     [{'data_vencimento': '2026-07-20'},
        ...      {'data_vencimento': '2026-07-05'}]
        ... )
        ['05', '20']
    """
    dias = {
        dia_do_vencimento(registro.get('data_vencimento'))
        for registro in registros
    }
    return sorted(dia for dia in dias if dia)


# =====================================================================
# Identificador do vencimentário
# =====================================================================
def proximo_id(ids_existentes: Iterable[Any]) -> int:
    """Escolhe o próximo ``id`` inteiro, acima de todos os já usados.

    O front identifica o vencimentário aberto pelo ``id`` sobre a lista
    achatada de todas as competências do convênio, então o id precisa ser
    único no histórico inteiro dele — não basta ser único no mês.

    Args:
        ids_existentes: Ids já gravados para o convênio, em qualquer
            competência.

    Returns:
        ``max(ids) + 1``; ``1`` quando não há nenhum id aproveitável.

    Example:
        >>> proximo_id([47, 48, '93'])
        94
        >>> proximo_id([])
        1
    """
    numericos = [
        int(bruto)
        for bruto in (texto(item) for item in ids_existentes)
        if bruto.isdigit()
    ]
    return max(numericos, default=0) + 1


# =====================================================================
# Clonagem do mês anterior (geração massiva)
# =====================================================================
def clonar_vencimentario(
    registro: Mapping[str, Any],
    competencia_destino: str,
    novo_id: int,
    agora: str,
) -> dict[str, Any]:
    """Copia um vencimentário para a competência seguinte, zerado.

    Mantém a identidade do convênio e o desenho do ciclo (dias de
    vencimento, remessa, SLA e corte), desloca todas as datas para o mês
    de destino e zera os saldos: o mês nasce ``PENDENTE``, à espera do
    Datacob.

    Args:
        registro: Vencimentário do mês anterior.
        competencia_destino: Competência ``AAAA-MM`` de destino.
        novo_id: Id único a atribuir ao clone.
        agora: Carimbo de criação/atualização.

    Returns:
        Novo vencimentário — ``registro`` não é modificado.

    Example:
        >>> clone = clonar_vencimentario(
        ...     {'originador': 'Alvo Card', 'numero_convenio': '00011ALV',
        ...      'data_vencimento': '2026-07-05', 'valor_retorno': 100.0,
        ...      'qtd_dias_sla_pagamento': '17'},
        ...     '2026-08', 94, '2026-07-23',
        ... )
        >>> clone['data_vencimento'], clone['valor_retorno'], clone['id']
        ('2026-08-05', 0.0, 94)
        >>> clone['qtd_dias_sla_pagamento']
        '17'
    """
    datas = {
        campo: mudar_competencia_da_data(
            registro.get(campo), competencia_destino
        )
        for campo in CAMPOS_DATA_DO_CICLO
    }

    return {
        'id': novo_id,
        'originador': texto(registro.get('originador')),
        'mes_referencia_conciliacao': competencia_destino,
        'numero_convenio': texto(registro.get('numero_convenio')),
        'nome_convenio': texto(registro.get('nome_convenio')),
        'cnpj_convenio': texto(registro.get('cnpj_convenio')),
        **datas,
        'qtd_dias_sla_pagamento': texto(
            registro.get('qtd_dias_sla_pagamento')
        ),
        'valor_remessa': VALOR_ZERADO,
        'valor_retorno': VALOR_ZERADO,
        'valor_repasse': VALOR_ZERADO,
        'status_conciliacao': STATUS_INICIAL,
        'motivo_falta_conciliacao': '',
        'porcentagem_inadimplencia': VALOR_ZERADO,
        'criado_em': texto(agora),
        'atualizado_em': texto(agora),
    }


def _inteiro_ou_none(valor: Any) -> int | None:
    """Converte para inteiro; ``None`` quando vazio ou não numérico."""
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def montar_vencimentario_do_controle(
    ficha: Mapping[str, Any],
    competencia: str,
    controle: Mapping[str, Any],
    novo_id: int,
    agora: str,
) -> dict[str, Any]:
    """Monta o vencimentário único da competência a partir do controle.

    É o caminho da geração quando o vínculo tem um **controle de
    vencimento** cadastrado na gerência: o mês nasce com um vencimento só,
    replicando o dia e os offsets (remessa, SLA, corte). Offset em branco
    deixa a data vazia. Valores zerados e status ``PENDENTE`` — a automação
    do Datacob completa os saldos.

    Args:
        ficha: Identidade do convênio (originadora, número, nome, CNPJ).
        competencia: Competência ``AAAA-MM`` de destino.
        controle: ``dia_vencimento`` e os offsets ``dias_antes_remessa``,
            ``qtd_dias_sla_pagamento`` e ``dias_antes_corte``.
        novo_id: Id único a atribuir ao vencimentário.
        agora: Carimbo de criação/atualização.

    Returns:
        Vencimentário pronto para gravar.

    Example:
        >>> v = montar_vencimentario_do_controle(
        ...     {'originador': 'Alvo Card', 'numero_convenio': '00001ALV'},
        ...     '2026-09',
        ...     {'dia_vencimento': 5, 'dias_antes_remessa': 3,
        ...      'qtd_dias_sla_pagamento': 17},
        ...     10, '2026-07-23',
        ... )
        >>> v['data_vencimento'], v['data_env_remessa']
        ('2026-09-05', '2026-09-02')
        >>> v['data_sla_concilicacao'], v['qtd_dias_sla_pagamento']
        ('2026-09-22', '17')
    """
    venc = data_na_competencia(competencia, controle.get('dia_vencimento'))
    remessa = _inteiro_ou_none(controle.get('dias_antes_remessa'))
    sla = _inteiro_ou_none(controle.get('qtd_dias_sla_pagamento'))
    corte = _inteiro_ou_none(controle.get('dias_antes_corte'))

    return {
        'id': novo_id,
        'originador': texto(ficha.get('originador')),
        'mes_referencia_conciliacao': competencia,
        'numero_convenio': texto(ficha.get('numero_convenio')),
        'nome_convenio': texto(ficha.get('nome_convenio')),
        'cnpj_convenio': texto(ficha.get('cnpj_convenio')),
        'data_vencimento': venc,
        'data_env_remessa': (
            deslocar_dias(venc, -remessa) if remessa is not None else ''
        ),
        'data_sla_concilicacao': (
            deslocar_dias(venc, sla) if sla is not None else ''
        ),
        'qtd_dias_sla_pagamento': '' if sla is None else str(sla),
        'data_corte': (
            deslocar_dias(venc, -corte) if corte is not None else ''
        ),
        'valor_remessa': VALOR_ZERADO,
        'valor_retorno': VALOR_ZERADO,
        'valor_repasse': VALOR_ZERADO,
        'status_conciliacao': STATUS_INICIAL,
        'motivo_falta_conciliacao': '',
        'porcentagem_inadimplencia': VALOR_ZERADO,
        'criado_em': texto(agora),
        'atualizado_em': texto(agora),
    }


def clonar_competencia(
    registros: Iterable[Mapping[str, Any]],
    competencia_destino: str,
    id_inicial: int,
    agora: str,
) -> list[dict[str, Any]]:
    """Clona todos os vencimentários de um convênio para o mês seguinte.

    Preserva a ordem dos vencimentos do mês anterior e numera os clones a
    partir de ``id_inicial``, um id por vencimentário.

    Args:
        registros: Vencimentários do mês anterior, na ordem desejada.
        competencia_destino: Competência ``AAAA-MM`` de destino.
        id_inicial: Primeiro id a atribuir; os demais seguem em sequência.
        agora: Carimbo de criação/atualização.

    Returns:
        Vencimentários clonados; lista vazia quando não há origem.

    Example:
        >>> clones = clonar_competencia(
        ...     [{'data_vencimento': '2026-07-05'},
        ...      {'data_vencimento': '2026-07-20'}],
        ...     '2026-08', 94, '2026-07-23',
        ... )
        >>> [c['id'] for c in clones]
        [94, 95]
    """
    return [
        clonar_vencimentario(
            registro, competencia_destino, id_inicial + i, agora
        )
        for i, registro in enumerate(registros)
    ]


# =====================================================================
# Vencimentário avulso (preenchido pelo operador)
# =====================================================================
def validar_vencimentario_manual(
    dados: Mapping[str, Any], competencia: str
) -> list[str]:
    """Lista o que impede um vencimentário avulso de ser gravado.

    Devolve a lista inteira — em vez de estourar no primeiro erro — para
    o painel apontar tudo de uma vez.

    Args:
        dados: Payload do formulário de vencimentário.
        competencia: Competência ``AAAA-MM`` em que ele nasce.

    Returns:
        Mensagens de erro; lista vazia quando o registro é válido.

    Example:
        >>> validar_vencimentario_manual(
        ...     {'data_vencimento': '2026-08-05'}, '2026-08'
        ... )
        []
        >>> validar_vencimentario_manual(
        ...     {'data_vencimento': '2026-07-05'}, '2026-08'
        ... )
        ["A data de vencimento '2026-07-05' não pertence à competência 2026-08."]
    """
    data = texto(dados.get('data_vencimento'))
    casado = PADRAO_DATA_ISO.match(data)
    status = texto(dados.get('status_conciliacao')) or STATUS_INICIAL

    erros = [
        *(
            []
            if competencia_valida(competencia)
            else [f'Competência inválida: {competencia!r}. Use AAAA-MM.']
        ),
        *(
            []
            if casado
            else ['Informe a data de vencimento no formato AAAA-MM-DD.']
        ),
    ]

    if casado and competencia_valida(competencia):
        mes_da_data = f'{casado.group(1)}-{casado.group(2)}'
        if mes_da_data != competencia:
            erros.append(
                f'A data de vencimento {data!r} não pertence à '
                f'competência {competencia}.'
            )

    if status not in STATUS_CONCILIACAO_VALIDOS:
        erros.append(f'Status de conciliação inválido: {status!r}.')

    return erros + _erros_valores(dados)


def _erros_valores(dados: Mapping[str, Any]) -> list[str]:
    """Recusa valores monetários negativos no vencimentário avulso."""
    rotulos = {
        'valor_remessa': 'Valor remessa',
        'valor_retorno': 'Valor retorno',
        'valor_repasse': 'Valor repasse',
    }
    return [
        f'{rotulo} não pode ser negativo.'
        for campo, rotulo in rotulos.items()
        if numero(dados.get(campo)) < 0
    ]


def montar_vencimentario_manual(
    dados: Mapping[str, Any],
    competencia: str,
    novo_id: int,
    agora: str,
) -> dict[str, Any]:
    """Normaliza o payload do operador num registro de vencimentário.

    A competência do registro vem do parâmetro, não do payload: ela é o
    contexto em que o operador está trabalhando, e prende o vencimentário
    ao mês certo mesmo que a tela mande outra coisa.

    Args:
        dados: Payload do formulário de vencimentário.
        competencia: Competência ``AAAA-MM`` em que ele nasce.
        novo_id: Id único a atribuir.
        agora: Carimbo de criação/atualização.

    Returns:
        Registro pronto para gravar — ``dados`` não é modificado.

    Example:
        >>> registro = montar_vencimentario_manual(
        ...     {'originador': 'Alvo Card', 'numero_convenio': '00011ALV',
        ...      'data_vencimento': '2026-08-05', 'valor_retorno': 100.0},
        ...     '2026-08', 94, '2026-07-23',
        ... )
        >>> registro['mes_referencia_conciliacao'], registro['id']
        ('2026-08', 94)
    """
    status = texto(dados.get('status_conciliacao')) or STATUS_INICIAL

    return {
        'id': novo_id,
        'originador': texto(dados.get('originador')),
        'mes_referencia_conciliacao': competencia,
        'numero_convenio': texto(dados.get('numero_convenio')),
        'nome_convenio': texto(dados.get('nome_convenio')),
        'cnpj_convenio': texto(dados.get('cnpj_convenio')),
        'data_vencimento': texto(dados.get('data_vencimento')),
        'data_env_remessa': texto(dados.get('data_env_remessa')),
        'data_sla_concilicacao': texto(dados.get('data_sla_concilicacao')),
        'qtd_dias_sla_pagamento': texto(dados.get('qtd_dias_sla_pagamento')),
        'data_corte': texto(dados.get('data_corte')),
        'valor_remessa': numero(dados.get('valor_remessa')),
        'valor_retorno': numero(dados.get('valor_retorno')),
        'valor_repasse': numero(dados.get('valor_repasse')),
        'status_conciliacao': status,
        'motivo_falta_conciliacao': texto(
            dados.get('motivo_falta_conciliacao')
        ),
        'porcentagem_inadimplencia': numero(
            dados.get('porcentagem_inadimplencia')
        ),
        'criado_em': texto(agora),
        'atualizado_em': texto(agora),
    }


# =====================================================================
# Solicitação de geração (ticket para a automação do Datacob)
# =====================================================================
def _linha_de_vinculo(vinculo: Mapping[str, Any]) -> dict[str, Any]:
    """Reduz um vínculo ao que a automação do Datacob precisa saber."""
    return {
        'originador': texto(vinculo.get('originador')),
        'numero_convenio': texto(vinculo.get('numero_convenio')),
        'nome_convenio': texto(vinculo.get('nome_convenio')),
        'cnpj_convenio': texto(vinculo.get('cnpj_convenio')),
        'dias_vencimento': list(vinculo.get('dias_vencimento') or []),
    }


def montar_solicitacao_geracao(
    competencia: str,
    competencia_origem: str,
    vinculos: Iterable[Mapping[str, Any]],
    ator: str,
    id_ticket: str,
    agora: str,
) -> dict[str, Any]:
    """Monta o ticket que a fila entrega à automação do Datacob.

    O ticket descreve **o que** preencher (a competência recém-clonada e
    os convênios dela, com os dias de vencimento de cada um), sem dizer
    **como**: a leitura do Datacob e a conversão em saldos é da
    automação, não do painel.

    Args:
        competencia: Competência ``AAAA-MM`` a preencher.
        competencia_origem: Competência de onde o esqueleto foi clonado.
        vinculos: Convênios da competência, cada um com
            ``dias_vencimento``.
        ator: Quem solicitou a geração, para auditoria.
        id_ticket: Identificador único do ticket (também o nome do
            arquivo na fila).
        agora: Carimbo da solicitação.

    Returns:
        Ticket serializável, pronto para a fila.

    Example:
        >>> ticket = montar_solicitacao_geracao(
        ...     '2026-08', '2026-07',
        ...     [{'originador': 'Alvo Card', 'numero_convenio': '00011ALV',
        ...       'dias_vencimento': ['05', '20']}],
        ...     'joao', 'abc', '23-07-2026 14:00:00',
        ... )
        >>> ticket['tipo'], ticket['competencia'], len(ticket['vinculos'])
        ('GERAR_COMPETENCIA', '2026-08', 1)
    """
    return {
        'id': texto(id_ticket),
        'tipo': TIPO_SOLICITACAO_GERACAO,
        'competencia': texto(competencia),
        'competencia_origem': texto(competencia_origem),
        'solicitado_em': texto(agora),
        'ator': texto(ator),
        'status': STATUS_INICIAL,
        'vinculos': [_linha_de_vinculo(vinculo) for vinculo in vinculos],
    }


def competencia_anterior(competencia: str) -> str:
    """Devolve a competência imediatamente anterior.

    Args:
        competencia: Competência ``AAAA-MM``.

    Returns:
        Competência anterior ``AAAA-MM``; vazio se a entrada for inválida.

    Example:
        >>> competencia_anterior('2026-01')
        '2025-12'
    """
    return deslocar_competencia(competencia, -1)


def _distancia_em_meses(inicio: str, fim: str) -> int:
    """Conta os meses de ``inicio`` a ``fim`` (ambos ``AAAA-MM`` válidos)."""
    ano_i, mes_i = (int(parte) for parte in inicio.split('-'))
    ano_f, mes_f = (int(parte) for parte in fim.split('-'))

    return (ano_f * MESES_NO_ANO + mes_f) - (ano_i * MESES_NO_ANO + mes_i)


def competencias_no_intervalo(inicio: str, fim: str) -> list[str]:
    """Lista as competências de ``inicio`` a ``fim``, inclusive, ascendente.

    É o intervalo que a geração por período percorre: cada mês é gerado a
    partir do anterior, então a ordem crescente importa. Intervalo com
    limite inválido, ou fim anterior ao início, devolve vazio — quem chama
    trata como período inválido.

    Args:
        inicio: Competência ``AAAA-MM`` inicial.
        fim: Competência ``AAAA-MM`` final.

    Returns:
        Competências ``AAAA-MM`` em ordem crescente; vazio se inválido.

    Example:
        >>> competencias_no_intervalo('2026-01', '2026-03')
        ['2026-01', '2026-02', '2026-03']
        >>> competencias_no_intervalo('2026-03', '2026-01')
        []
        >>> competencias_no_intervalo('2026-05', '2026-05')
        ['2026-05']
    """
    if not (competencia_valida(inicio) and competencia_valida(fim)):
        return []
    if fim < inicio:
        return []

    total = _distancia_em_meses(inicio, fim)

    return [deslocar_competencia(inicio, passo) for passo in range(total + 1)]
