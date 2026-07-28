"""Testes do rastreio de envio de remessa por vencimento."""

# --- stdlib ---
import sys
from pathlib import Path

# --- terceiros ---
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# --- locais ---
from api.arquivos import (  # noqa: E402
    caminho_registro,
    gravar_arquivo,
    montar_documento,
)
from api.domain_remessas import validar_remessa  # noqa: E402
from api.repositories import remessas as repo  # noqa: E402

ORIGINADORA = 'Alvo Card'
NUMERO = '00001ALV'
COMPET = '2026-07'
TABELA_CONC = 'tabela_concilicacao_convenio'

VENCIMENTOS = [
    {
        'id': 1,
        'originador': ORIGINADORA,
        'mes_referencia_conciliacao': COMPET,
        'numero_convenio': NUMERO,
        'nome_convenio': 'AERONÁUTICA',
        'cnpj_convenio': '00.394.429/0082-76',
        'data_vencimento': '2026-07-05',
        'valor_remessa': 299741.06,
        'status_conciliacao': 'PENDENTE',
    },
    {
        'id': 2,
        'originador': ORIGINADORA,
        'mes_referencia_conciliacao': COMPET,
        'numero_convenio': NUMERO,
        'data_vencimento': '2026-07-20',
        'valor_remessa': 281185.24,
        'status_conciliacao': 'PENDENTE',
    },
]


@pytest.fixture()
def banco(tmp_path):
    """Banco com a competência 2026-07 (dois vencimentos) na conciliação."""
    gravar_arquivo(
        caminho_registro(tmp_path, TABELA_CONC, ORIGINADORA, NUMERO, COMPET),
        montar_documento(
            TABELA_CONC, ORIGINADORA, NUMERO, VENCIMENTOS, COMPET
        ),
    )
    return tmp_path


# =========================================================
# Domínio
# =========================================================
def test_enviada_exige_data():
    assert validar_remessa({'situacao': 'ENVIADA'}) == [
        'Informe a data de envio para marcar como enviada.'
    ]


def test_pendente_nao_exige_data():
    assert validar_remessa({'situacao': 'PENDENTE'}) == []


# =========================================================
# Listagem (vencimentos da conciliação + status)
# =========================================================
def test_lista_vencimentos_pendentes_por_padrao(banco):
    linhas = repo.listar_remessas(banco, ORIGINADORA, NUMERO, COMPET)

    assert [l['data_vencimento'] for l in linhas] == [
        '2026-07-05',
        '2026-07-20',
    ]
    assert all(l['situacao'] == 'PENDENTE' for l in linhas)


def test_sem_conciliacao_lista_vazia(banco):
    assert repo.listar_remessas(banco, ORIGINADORA, NUMERO, '2026-08') == []


# =========================================================
# Registro de envio
# =========================================================
def test_registrar_envio_reflete_na_listagem(banco):
    repo.registrar_envio(
        banco,
        ORIGINADORA,
        NUMERO,
        COMPET,
        '2026-07-05',
        {'situacao': 'ENVIADA', 'data_envio': '2026-07-02'},
        'joao',
    )
    linha = repo.listar_remessas(banco, ORIGINADORA, NUMERO, COMPET)[0]

    assert linha['situacao'] == 'ENVIADA'
    assert linha['data_envio'] == '2026-07-02'
    assert linha['usuario'] == 'joao'


def test_registrar_envio_data_invalida_erra(banco):
    with pytest.raises(repo.RemessaInvalidaError):
        repo.registrar_envio(
            banco,
            ORIGINADORA,
            NUMERO,
            COMPET,
            '2026-07-05',
            {'situacao': 'ENVIADA'},
            'joao',
        )


def test_registrar_envio_vencimento_inexistente_erra(banco):
    with pytest.raises(repo.VencimentoNaoEncontradoError):
        repo.registrar_envio(
            banco,
            ORIGINADORA,
            NUMERO,
            COMPET,
            '2026-07-31',
            {'situacao': 'PENDENTE'},
            'joao',
        )


def test_reenviar_atualiza_o_mesmo_registro(banco):
    for data_envio in ('2026-07-02', '2026-07-03'):
        repo.registrar_envio(
            banco,
            ORIGINADORA,
            NUMERO,
            COMPET,
            '2026-07-05',
            {'situacao': 'ENVIADA', 'data_envio': data_envio},
            'joao',
        )
    enviadas = [
        l
        for l in repo.listar_remessas(banco, ORIGINADORA, NUMERO, COMPET)
        if l['data_vencimento'] == '2026-07-05'
    ]

    assert len(enviadas) == 1
    assert enviadas[0]['data_envio'] == '2026-07-03'
