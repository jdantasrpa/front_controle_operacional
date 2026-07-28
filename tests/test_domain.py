"""Testes das regras puras de tradução banco -> contrato do front."""

# --- stdlib ---
import sys
from pathlib import Path

# --- terceiros ---
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# --- locais ---
from api.domain import (  # noqa: E402
    caso_para_dto,
    competencia_para_mes_referencia,
    data_para_br,
    dia_do_vencimento,
    linha_para_registro_retorno,
    linha_para_vencimentario,
    mes_referencia_para_competencia,
    normalizar_status_conciliacao,
    resumo_competencia,
)


# =========================================================
# mes_referencia_para_competencia
# =========================================================
@pytest.mark.parametrize(
    'entrada, esperado',
    [
        ('2025-07', '07/2025'),
        ('2025-12', '12/2025'),
        ('07/2025', '07/2025'),
        (' 2025-08 ', '08/2025'),
    ],
)
def test_mes_referencia_para_competencia_converte(entrada, esperado):
    assert mes_referencia_para_competencia(entrada) == esperado


@pytest.mark.parametrize('entrada', [None, '', '   ', 'lixo', '2025'])
def test_mes_referencia_para_competencia_invalido_retorna_vazio(entrada):
    assert mes_referencia_para_competencia(entrada) == ''


# =========================================================
# competencia_para_mes_referencia
# =========================================================
@pytest.mark.parametrize(
    'entrada, esperado',
    [
        ('07/2025', '2025-07'),
        ('2025-07', '2025-07'),
        (None, ''),
        ('lixo', ''),
    ],
)
def test_competencia_para_mes_referencia(entrada, esperado):
    assert competencia_para_mes_referencia(entrada) == esperado


# =========================================================
# data_para_br / dia_do_vencimento
# =========================================================
@pytest.mark.parametrize(
    'entrada, esperado',
    [
        ('2025-07-19', '19/07/2025'),
        ('2025-07-19 00:00:00', '19/07/2025'),
        ('19/07/2025', '19/07/2025'),
        (None, ''),
        ('lixo', ''),
    ],
)
def test_data_para_br(entrada, esperado):
    assert data_para_br(entrada) == esperado


@pytest.mark.parametrize(
    'entrada, esperado',
    [('2025-07-05', '05'), ('19/07/2025', '19'), ('', '')],
)
def test_dia_do_vencimento(entrada, esperado):
    assert dia_do_vencimento(entrada) == esperado


# =========================================================
# normalizar_status_conciliacao
# =========================================================
@pytest.mark.parametrize(
    'entrada, esperado',
    [
        ('CONCILIADO', 'CONCILIADO'),
        ('ok', 'CONCILIADO'),
        ('DIVERGENTE', 'CONCILIADO (PARCIAL)'),
        ('CONCILIADO (PARCIAL)', 'CONCILIADO (PARCIAL)'),
        ('', 'PENDENTE'),
        (None, 'PENDENTE'),
        ('valor que ninguém previu', 'PENDENTE'),
    ],
)
def test_normalizar_status_conciliacao(entrada, esperado):
    assert normalizar_status_conciliacao(entrada) == esperado


# =========================================================
# linha_para_vencimentario
# =========================================================
LINHA_VENCIMENTARIO = {
    'id': 7,
    'originador': 'FCT',
    'mes_referencia_conciliacao': '2025-07',
    'numero_convenio': '126225',
    'data_vencimento': '2025-07-19',
    'data_sla_concilicacao': '2025-07-21',
    'qtd_dias_sla_pagamento': '5',
    'data_corte': '2025-07-24',
    'valor_remessa': 98734.69,
    'valor_retorno': 97499.43,
    'valor_repasse': 96862.49,
    'status_conciliacao': 'OK',
    'motivo_falta_conciliacao': '',
    'porcentagem_inadimplencia': 0.73,
}


def test_linha_para_vencimentario_identifica_a_competencia_e_o_dia():
    venc = linha_para_vencimentario(LINHA_VENCIMENTARIO)

    assert venc['id'] == '7'
    assert venc['competencia'] == '07/2025'
    assert venc['dia_vencimento'] == '19'
    # 'Conciliado' não é campo próprio: o front deriva do status.
    assert 'conciliado' not in venc
    assert venc['conciliacao']['status_conciliacao'] == 'CONCILIADO'


def test_linha_para_vencimentario_usa_o_cenario_do_banco_quando_existe():
    linha = {
        **LINHA_VENCIMENTARIO,
        'cenario_conciliacao': 'Conciliação manual',
    }

    conciliacao = linha_para_vencimentario(linha)['conciliacao']

    assert conciliacao['cenario_conciliacao'] == 'Conciliação manual'


def test_linha_para_vencimentario_converte_datas_e_valores():
    conciliacao = linha_para_vencimentario(LINHA_VENCIMENTARIO)['conciliacao']

    assert conciliacao['data_vencimento'] == '19/07/2025'
    assert conciliacao['data_baixa'] == '21/07/2025'
    assert conciliacao['data_corte'] == '24/07/2025'
    assert conciliacao['valor_remessa'] == pytest.approx(98734.69)
    assert conciliacao['status_conciliacao'] == 'CONCILIADO'


def test_linha_para_vencimentario_tolera_colunas_ausentes():
    venc = linha_para_vencimentario({'id': 1})

    assert venc['competencia'] == ''
    assert venc['dia_vencimento'] == ''
    assert venc['conciliacao']['status_conciliacao'] == 'PENDENTE'
    assert venc['conciliacao']['cenario_conciliacao'] != ''
    assert venc['conciliacao']['valor_remessa'] == 0.0
    # Ainda sem coluna no banco — entram vazios até a migração da etapa 2.
    assert venc['conciliacao']['qtd_contratos'] == ''
    assert venc['conciliacao']['observacao'] == ''
    assert venc['financeiro'] == []


# =========================================================
# resumo_competencia
# =========================================================
def _venc(status, dia, motivo='', inadimplencia=0.0):
    return {
        'dia_vencimento': dia,
        'conciliacao': {
            'status_conciliacao': status,
            'motivo_falta_conciliacao': motivo,
            'data_baixa': '21/07/2025',
            'data_corte': f'2{dia}/07/2025',
            'qtd_dias_inadimplencia': '3',
            'porcentagem_inadimplencia': inadimplencia,
        },
    }


@pytest.mark.parametrize(
    'statuses, esperado',
    [
        (['CONCILIADO', 'CONCILIADO'], 'CONCILIADO'),
        (['PENDENTE', 'PENDENTE'], 'PENDENTE'),
        (['CONCILIADO', 'PENDENTE'], 'CONCILIADO (PARCIAL)'),
        (['CONCILIADO (PARCIAL)'], 'CONCILIADO (PARCIAL)'),
    ],
)
def test_resumo_competencia_consolida_status(statuses, esperado):
    vencimentarios = [_venc(s, '05') for s in statuses]

    assert resumo_competencia(vencimentarios)['status_conciliacao'] == esperado


def test_resumo_competencia_usa_o_pior_indicador():
    resumo = resumo_competencia(
        [
            _venc('CONCILIADO', '05', inadimplencia=1.5),
            _venc('PENDENTE', '20', motivo='Outros', inadimplencia=42.0),
        ]
    )

    assert resumo['qtd_vencimentarios'] == 2
    assert resumo['dias_venc'] == '05 / 20'
    assert resumo['motivos'] == ['Outros']
    assert resumo['porcentagem_inadimplencia'] == pytest.approx(42.0)


# =========================================================
# linha_para_registro_retorno
# =========================================================
LINHA_CONCILIACAO = {
    'id': 1,
    'originador': 'FCT',
    'mes_referencia_conciliacao': '2025-07',
    'numero_convenio': '126225',
    'nome_convenio': 'Convenio FCT 01',
    'cnpj_convenio': '45.350.328/3286-23',
    'data_corte': '2025-07-24',
    'valor_remessa': 98734.69,
    'valor_retorno': 97499.43,
    'valor_repasse': 96862.49,
    'status_conciliacao': 'OK',
}


def test_linha_para_registro_retorno_usa_valor_retorno():
    registro = linha_para_registro_retorno(LINHA_CONCILIACAO)

    assert registro['convenio'] == 'Convenio FCT 01'
    assert registro['competencia'] == '07/2025'
    assert registro['valor'] == pytest.approx(97499.43)
    assert registro['originador'] == 'FCT'
    assert registro['numeroConvenio'] == '126225'


def test_linha_para_registro_retorno_nao_muta_a_entrada():
    original = dict(LINHA_CONCILIACAO)
    linha_para_registro_retorno(LINHA_CONCILIACAO)
    assert LINHA_CONCILIACAO == original


def test_linha_para_registro_retorno_valor_nulo_vira_zero():
    registro = linha_para_registro_retorno(
        {**LINHA_CONCILIACAO, 'valor_retorno': None}
    )
    assert registro['valor'] == 0.0


# =========================================================
# caso_para_dto
# =========================================================
CASO_DB = {
    'id': 7,
    'originador': 'FCT',
    'numero_convenio': '126225',
    'nome_convenio': 'Convenio FCT 01',
    'cnpj_convenio': '45.350.328/3286-23',
    'contato_nome': 'Paulo Souza',
    'contato_telefone': '(11) 91641-5059',
    'contato_email': 'paulo.souza@fct.mock',
    'mes_referencia': '07/2025',
    'valor_em_aberto': 636.94,
    'status_cobranca': 'pendente',
    'motivo': 'conciliacao',
    'observacao': 'Gerado da conciliação.',
    'criado_em': '2026-07-20 10:00:00',
    'atualizado_em': '2026-07-21 09:00:00',
}


def test_caso_para_dto_traduz_para_o_contrato_do_front():
    dto = caso_para_dto(CASO_DB, tentativas=[], agendamentos=[])

    assert dto['id'] == '7'
    assert dto['empresa'] == 'Convenio FCT 01'
    assert dto['cnpj'] == '45.350.328/3286-23'
    assert dto['contato'] == 'Paulo Souza'
    assert dto['competencia'] == '07/2025'
    assert dto['valorDivergente'] == pytest.approx(636.94)
    assert dto['status'] == 'pendente'
    assert dto['origem'] == 'conciliacao'
    assert dto['tentativas'] == []
    assert dto['agendamentos'] == []


def test_caso_para_dto_converte_concluido_para_booleano():
    dto = caso_para_dto(
        CASO_DB,
        tentativas=[
            {
                'id': 1,
                'data_hora': '2026-07-20T10:00:00',
                'canal': 'telefone',
                'resultado': 'sem_resposta',
                'observacao': '',
            }
        ],
        agendamentos=[
            {
                'id': 3,
                'data_hora': '2026-07-25T14:00:00',
                'assunto': 'Negociar',
                'observacao': '',
                'concluido': 1,
            }
        ],
    )

    assert dto['tentativas'][0]['id'] == '1'
    assert dto['tentativas'][0]['canal'] == 'telefone'
    assert dto['agendamentos'][0]['concluido'] is True


def test_caso_para_dto_status_desconhecido_cai_para_pendente():
    dto = caso_para_dto(
        {**CASO_DB, 'status_cobranca': 'INEXISTENTE'},
        tentativas=[],
        agendamentos=[],
    )
    assert dto['status'] == 'pendente'
