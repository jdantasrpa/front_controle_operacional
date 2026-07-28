"""Testes da geração de vencimentários (clonagem, avulso e solicitação)."""

# --- stdlib ---
import sys
from pathlib import Path

# --- terceiros ---
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# --- locais ---
from api.domain_geracao import (  # noqa: E402
    TIPO_SOLICITACAO_GERACAO,
    clonar_competencia,
    clonar_vencimentario,
    competencia_anterior,
    dia_do_vencimento,
    dias_de_vencimento,
    montar_solicitacao_geracao,
    montar_vencimentario_manual,
    mudar_competencia_da_data,
    proximo_id,
    validar_vencimentario_manual,
)

AGORA = '2026-07-23'

VENCIMENTARIO_JULHO = {
    'id': 47,
    'originador': 'Alvo Card',
    'mes_referencia_conciliacao': '2026-07',
    'numero_convenio': '00011ALV',
    'nome_convenio': 'GOV. GOIÁS',
    'cnpj_convenio': '02.476.034/0001-82',
    'data_vencimento': '2026-07-05',
    'data_env_remessa': '2026-07-02',
    'data_sla_concilicacao': '2026-07-28',
    'qtd_dias_sla_pagamento': '23',
    'data_corte': '2026-07-18',
    'valor_remessa': 607769.2,
    'valor_retorno': 597133.24,
    'valor_repasse': 500000.0,
    'status_conciliacao': 'CONCILIADO',
    'motivo_falta_conciliacao': '',
    'porcentagem_inadimplencia': 16.3,
    'criado_em': '2026-07-05',
    'atualizado_em': '2026-07-28',
}


# =========================================================
# Datas: mover o dia de um mês para o outro
# =========================================================
@pytest.mark.parametrize(
    'data, competencia, esperado',
    [
        ('2026-07-05', '2026-08', '2026-08-05'),
        ('2026-07-20', '2026-08', '2026-08-20'),
        ('2026-01-31', '2026-02', '2026-02-28'),  # clamp em fevereiro
        ('2024-01-31', '2024-02', '2024-02-29'),  # bissexto
        ('', '2026-08', ''),
        ('2026-07-05', '08/2026', ''),  # competência inválida
    ],
)
def test_mudar_competencia_da_data(data, competencia, esperado):
    assert mudar_competencia_da_data(data, competencia) == esperado


def test_dia_do_vencimento():
    assert dia_do_vencimento('2026-08-05') == '05'
    assert dia_do_vencimento('') == ''


def test_dias_de_vencimento_ordena_e_deduplica():
    registros = [
        {'data_vencimento': '2026-07-20'},
        {'data_vencimento': '2026-07-05'},
        {'data_vencimento': '2026-07-20'},
    ]
    assert dias_de_vencimento(registros) == ['05', '20']


# =========================================================
# Identificador único no histórico do convênio
# =========================================================
def test_proximo_id_acima_do_maior():
    assert proximo_id([47, 48, '93']) == 94


def test_proximo_id_comeca_em_um_quando_vazio():
    assert proximo_id([]) == 1


def test_proximo_id_ignora_ids_nao_numericos():
    assert proximo_id(['abc', '', None, 10]) == 11


# =========================================================
# Clonagem do mês anterior (geração massiva)
# =========================================================
def test_clone_desloca_datas_mantendo_o_dia():
    clone = clonar_vencimentario(VENCIMENTARIO_JULHO, '2026-08', 94, AGORA)

    assert clone['data_vencimento'] == '2026-08-05'
    assert clone['data_env_remessa'] == '2026-08-02'
    assert clone['data_sla_concilicacao'] == '2026-08-28'
    assert clone['data_corte'] == '2026-08-18'
    assert clone['mes_referencia_conciliacao'] == '2026-08'


def test_clone_zera_valores_e_reinicia_status():
    clone = clonar_vencimentario(VENCIMENTARIO_JULHO, '2026-08', 94, AGORA)

    assert clone['valor_remessa'] == 0.0
    assert clone['valor_retorno'] == 0.0
    assert clone['valor_repasse'] == 0.0
    assert clone['porcentagem_inadimplencia'] == 0.0
    assert clone['status_conciliacao'] == 'PENDENTE'
    assert clone['motivo_falta_conciliacao'] == ''


def test_clone_preserva_identidade_e_sla():
    clone = clonar_vencimentario(VENCIMENTARIO_JULHO, '2026-08', 94, AGORA)

    assert clone['originador'] == 'Alvo Card'
    assert clone['numero_convenio'] == '00011ALV'
    assert clone['nome_convenio'] == 'GOV. GOIÁS'
    assert clone['cnpj_convenio'] == '02.476.034/0001-82'
    # SLA é duração (dias), não data: não desloca.
    assert clone['qtd_dias_sla_pagamento'] == '23'
    assert clone['id'] == 94
    assert clone['criado_em'] == AGORA


def test_clone_nao_modifica_o_registro_de_origem():
    original = dict(VENCIMENTARIO_JULHO)
    clonar_vencimentario(VENCIMENTARIO_JULHO, '2026-08', 94, AGORA)
    assert VENCIMENTARIO_JULHO == original


def test_clonar_competencia_numera_em_sequencia():
    registros = [
        {'data_vencimento': '2026-07-05'},
        {'data_vencimento': '2026-07-20'},
    ]
    clones = clonar_competencia(registros, '2026-08', 94, AGORA)

    assert [c['id'] for c in clones] == [94, 95]
    assert [c['data_vencimento'] for c in clones] == [
        '2026-08-05',
        '2026-08-20',
    ]


def test_clonar_competencia_vazia_devolve_lista_vazia():
    assert clonar_competencia([], '2026-08', 94, AGORA) == []


# =========================================================
# Vencimentário avulso
# =========================================================
def test_avulso_valido_nao_tem_erros():
    assert (
        validar_vencimentario_manual(
            {'data_vencimento': '2026-08-05'}, '2026-08'
        )
        == []
    )


def test_avulso_recusa_data_fora_da_competencia():
    erros = validar_vencimentario_manual(
        {'data_vencimento': '2026-07-05'}, '2026-08'
    )
    assert len(erros) == 1
    assert 'não pertence à competência' in erros[0]


def test_avulso_recusa_data_ausente():
    erros = validar_vencimentario_manual({}, '2026-08')
    assert any('data de vencimento' in erro for erro in erros)


def test_avulso_recusa_valor_negativo():
    erros = validar_vencimentario_manual(
        {'data_vencimento': '2026-08-05', 'valor_retorno': -1}, '2026-08'
    )
    assert any('negativo' in erro for erro in erros)


def test_avulso_recusa_status_invalido():
    erros = validar_vencimentario_manual(
        {'data_vencimento': '2026-08-05', 'status_conciliacao': 'XPTO'},
        '2026-08',
    )
    assert any('Status' in erro for erro in erros)


def test_montar_avulso_prende_a_competencia_do_contexto():
    registro = montar_vencimentario_manual(
        {
            'originador': 'Alvo Card',
            'numero_convenio': '00011ALV',
            'data_vencimento': '2026-08-05',
            'mes_referencia_conciliacao': '1999-01',  # deve ser ignorado
            'valor_retorno': 100.0,
        },
        '2026-08',
        94,
        AGORA,
    )

    assert registro['mes_referencia_conciliacao'] == '2026-08'
    assert registro['id'] == 94
    assert registro['valor_retorno'] == 100.0
    assert registro['status_conciliacao'] == 'PENDENTE'


# =========================================================
# Solicitação de geração (ticket do Datacob)
# =========================================================
def test_ticket_descreve_competencia_e_convenios():
    ticket = montar_solicitacao_geracao(
        '2026-08',
        '2026-07',
        [
            {
                'originador': 'Alvo Card',
                'numero_convenio': '00011ALV',
                'nome_convenio': 'GOV. GOIÁS',
                'cnpj_convenio': '02.476.034/0001-82',
                'dias_vencimento': ['05', '20'],
            }
        ],
        'joao',
        'abc123',
        '23-07-2026 14:00:00',
    )

    assert ticket['tipo'] == TIPO_SOLICITACAO_GERACAO
    assert ticket['competencia'] == '2026-08'
    assert ticket['competencia_origem'] == '2026-07'
    assert ticket['ator'] == 'joao'
    assert ticket['status'] == 'PENDENTE'
    assert ticket['vinculos'][0]['dias_vencimento'] == ['05', '20']


def test_competencia_anterior():
    assert competencia_anterior('2026-01') == '2025-12'
    assert competencia_anterior('2026-08') == '2026-07'
