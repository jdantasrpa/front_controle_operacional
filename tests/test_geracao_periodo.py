"""Testes da geração gated pelo toggle e da geração por período."""

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
    ler_arquivo,
    montar_documento,
)
from api.domain_geracao import competencias_no_intervalo  # noqa: E402
from api.repositories import (  # noqa: E402
    conciliacao_gerencia as repo_gerencia,
)
from api.repositories import convenios as repo_convenios  # noqa: E402
from api.repositories import geracao as repo  # noqa: E402


def _definir_dia(banco, dia):
    repo_gerencia.atualizar_estado(
        banco, ORIGINADORA, NUMERO, {'dia_vencimento': dia}, 'joao'
    )


CNPJ = '02.476.034/0001-82'
ORIGINADORA = 'Alvo Card'
NUMERO = '00011ALV'
NOME = 'GOV. GOIÁS'
TABELA = 'tabela_concilicacao_convenio'

JULHO = [
    {
        'id': 93,
        'originador': ORIGINADORA,
        'mes_referencia_conciliacao': '2026-07',
        'numero_convenio': NUMERO,
        'nome_convenio': NOME,
        'cnpj_convenio': CNPJ,
        'data_vencimento': '2026-07-05',
        'data_env_remessa': '2026-07-02',
        'data_sla_concilicacao': '2026-07-28',
        'qtd_dias_sla_pagamento': '23',
        'data_corte': '',
        'valor_remessa': 100.0,
        'valor_retorno': 90.0,
        'valor_repasse': 90.0,
        'status_conciliacao': 'CONCILIADO',
        'motivo_falta_conciliacao': '',
        'porcentagem_inadimplencia': 0.0,
        'criado_em': '2026-07-05',
        'atualizado_em': '2026-07-28',
    }
]


@pytest.fixture()
def banco(tmp_path):
    """Banco com convênio vigente e a competência 2026-07 de origem."""
    (tmp_path / 'cadastro_convenio').mkdir()
    repo_convenios.criar_convenio(
        tmp_path, {'cnpj_convenio': CNPJ, 'nome_convenio': NOME}
    )
    repo_convenios.criar_vinculo(
        tmp_path,
        CNPJ,
        {
            'originador': ORIGINADORA,
            'numero_convenio': NUMERO,
            'competencia_inicio': '2025-01',
            'status': 'ATIVO',
        },
    )
    gravar_arquivo(
        caminho_registro(tmp_path, TABELA, ORIGINADORA, NUMERO, '2026-07'),
        montar_documento(TABELA, ORIGINADORA, NUMERO, JULHO, '2026-07'),
    )
    return tmp_path


def _ler(banco, competencia):
    lido = ler_arquivo(
        caminho_registro(banco, TABELA, ORIGINADORA, NUMERO, competencia)
    )
    return lido[0]['registros'] if lido else []


# =========================================================
# Intervalo (função pura)
# =========================================================
def test_intervalo_ascendente_inclusivo():
    assert competencias_no_intervalo('2026-01', '2026-03') == [
        '2026-01',
        '2026-02',
        '2026-03',
    ]


def test_intervalo_invertido_vazio():
    assert competencias_no_intervalo('2026-03', '2026-01') == []


# =========================================================
# Massivo respeita o liga/desliga
# =========================================================
def test_massivo_pula_convenio_desligado(banco, tmp_path):
    repo_gerencia.atualizar_estado(
        banco, ORIGINADORA, NUMERO, {'em_conciliacao_ativa': False}, 'joao'
    )
    resumo = repo.gerar_competencia(banco, '2026-08', tmp_path / 'fila', 'x')

    assert resumo['gerados'] == []
    assert _ler(banco, '2026-08') == []


def test_massivo_gera_quando_ligado(banco, tmp_path):
    resumo = repo.gerar_competencia(banco, '2026-08', tmp_path / 'fila', 'x')

    assert len(resumo['gerados']) == 1
    assert _ler(banco, '2026-08')


# =========================================================
# Geração por período
# =========================================================
def test_periodo_gera_o_intervalo_inteiro(banco, tmp_path):
    resumo = repo.gerar_competencias_periodo(
        banco,
        ORIGINADORA,
        NUMERO,
        '2026-08',
        '2026-10',
        tmp_path / 'fila',
        'x',
    )

    assert len(resumo['gerados']) == 3
    assert [r['data_vencimento'] for r in _ler(banco, '2026-08')] == [
        '2026-08-05'
    ]
    assert _ler(banco, '2026-09')  # clonado do mês recém-gerado
    assert _ler(banco, '2026-10')


def test_periodo_emite_um_ticket_por_competencia(banco, tmp_path):
    fila = tmp_path / 'fila'
    resumo = repo.gerar_competencias_periodo(
        banco, ORIGINADORA, NUMERO, '2026-08', '2026-09', fila, 'x'
    )

    assert len(resumo['tickets']) == 2
    assert all((fila / nome).is_file() for nome in resumo['tickets'])


def test_periodo_respeita_desligado(banco, tmp_path):
    repo_gerencia.atualizar_estado(
        banco, ORIGINADORA, NUMERO, {'em_conciliacao_ativa': False}, 'joao'
    )
    resumo = repo.gerar_competencias_periodo(
        banco,
        ORIGINADORA,
        NUMERO,
        '2026-08',
        '2026-09',
        tmp_path / 'fila',
        'x',
    )

    assert resumo['desligado'] is True
    assert _ler(banco, '2026-08') == []


def test_periodo_fora_de_vigencia_nao_gera(banco, tmp_path):
    """Convênio começa em 2025-01; pedir 2024 fica fora de vigência."""
    resumo = repo.gerar_competencias_periodo(
        banco,
        ORIGINADORA,
        NUMERO,
        '2024-11',
        '2024-12',
        tmp_path / 'fila',
        'x',
    )

    assert len(resumo['fora_vigencia']) == 2
    assert resumo['gerados'] == []


def test_periodo_intervalo_invalido_erra(banco, tmp_path):
    with pytest.raises(repo.PeriodoInvalidoError):
        repo.gerar_competencias_periodo(
            banco,
            ORIGINADORA,
            NUMERO,
            '2026-10',
            '2026-08',
            tmp_path / 'f',
            'x',
        )


def test_periodo_vinculo_inexistente_erra(banco, tmp_path):
    with pytest.raises(repo_convenios.VinculoNaoEncontradoError):
        repo.gerar_competencias_periodo(
            banco,
            'Hatchbank',
            '00061HTC',
            '2026-08',
            '2026-09',
            tmp_path / 'f',
            'x',
        )


# =========================================================
# Geração a partir do dia de vencimento definido
# =========================================================
def test_dia_definido_gera_um_unico_vencimento(banco, tmp_path):
    """Com dia definido, o mês nasce com um vencimento só, nesse dia."""
    _definir_dia(banco, 15)
    repo.gerar_competencia(banco, '2026-08', tmp_path / 'f', 'x')

    agosto = _ler(banco, '2026-08')
    assert [r['data_vencimento'] for r in agosto] == ['2026-08-15']


def test_controle_replica_offsets_de_remessa_sla_corte(banco, tmp_path):
    """Os offsets do controle viram as datas de remessa, SLA e corte."""
    repo_gerencia.atualizar_estado(
        banco,
        ORIGINADORA,
        NUMERO,
        {
            'dia_vencimento': 5,
            'dias_antes_remessa': 3,
            'qtd_dias_sla_pagamento': 17,
            'dias_antes_corte': 2,
        },
        'joao',
    )
    repo.gerar_competencia(banco, '2026-08', tmp_path / 'f', 'x')

    venc = _ler(banco, '2026-08')[0]
    assert venc['data_vencimento'] == '2026-08-05'
    assert venc['data_env_remessa'] == '2026-08-02'
    assert venc['data_sla_concilicacao'] == '2026-08-22'
    assert venc['qtd_dias_sla_pagamento'] == '17'
    assert venc['data_corte'] == '2026-08-03'


def test_dia_definido_gera_convenio_sem_mes_anterior(banco, tmp_path):
    """Convênio novo (sem mês anterior) gera pelo dia — não é 'sem_origem'."""
    repo_convenios.criar_convenio(
        banco, {'cnpj_convenio': '11.111.111/0001-11', 'nome_convenio': 'NOVO'}
    )
    repo_convenios.criar_vinculo(
        banco,
        '11.111.111/0001-11',
        {
            'originador': ORIGINADORA,
            'numero_convenio': '00099ALV',
            'competencia_inicio': '2025-01',
            'status': 'ATIVO',
        },
    )
    repo_gerencia.atualizar_estado(
        banco, ORIGINADORA, '00099ALV', {'dia_vencimento': 10}, 'j'
    )
    resumo = repo.gerar_competencia(banco, '2026-08', tmp_path / 'f', 'x')

    gerado = [
        g for g in resumo['gerados'] if g['numero_convenio'] == '00099ALV'
    ]
    assert len(gerado) == 1
    assert not any(
        s['numero_convenio'] == '00099ALV' for s in resumo['sem_origem']
    )


def test_alterar_dia_nao_reescreve_o_passado(banco, tmp_path):
    """Julho já existe (dia 05); definir outro dia não mexe no que passou."""
    _definir_dia(banco, 20)
    resumo = repo.gerar_competencia(banco, '2026-07', tmp_path / 'f', 'x')

    julho = _ler(banco, '2026-07')
    assert [r['data_vencimento'] for r in julho] == ['2026-07-05']
    assert any(p['numero_convenio'] == NUMERO for p in resumo['pulados'])
