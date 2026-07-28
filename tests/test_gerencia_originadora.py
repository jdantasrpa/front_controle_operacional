"""Testes do grupo master (originadora) na gerência da Conciliação."""

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
from api.repositories import (  # noqa: E402
    conciliacao_gerencia as repo_gerencia,
)
from api.repositories import convenios as repo_convenios  # noqa: E402
from api.repositories import geracao as repo_geracao  # noqa: E402

CNPJ_A = '02.476.034/0001-82'
CNPJ_B = '00.394.429/0082-76'
ORIGINADORA = 'Alvo Card'
NUM_A = '00011ALV'
NUM_B = '00001ALV'
TABELA = 'tabela_concilicacao_convenio'


def _venc(num, nome, cnpj):
    return [
        {
            'id': 1,
            'originador': ORIGINADORA,
            'mes_referencia_conciliacao': '2026-07',
            'numero_convenio': num,
            'nome_convenio': nome,
            'cnpj_convenio': cnpj,
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
    """Uma originadora (Alvo Card) com dois convênios vigentes."""
    (tmp_path / 'cadastro_convenio').mkdir()
    for cnpj, num, nome in (
        (CNPJ_A, NUM_A, 'GOV. GOIÁS'),
        (CNPJ_B, NUM_B, 'AERONÁUTICA'),
    ):
        repo_convenios.criar_convenio(
            tmp_path, {'cnpj_convenio': cnpj, 'nome_convenio': nome}
        )
        repo_convenios.criar_vinculo(
            tmp_path,
            cnpj,
            {
                'originador': ORIGINADORA,
                'numero_convenio': num,
                'competencia_inicio': '2025-01',
                'status': 'ATIVO',
            },
        )
        gravar_arquivo(
            caminho_registro(tmp_path, TABELA, ORIGINADORA, num, '2026-07'),
            montar_documento(
                TABELA, ORIGINADORA, num, _venc(num, nome, cnpj), '2026-07'
            ),
        )
    return tmp_path


def _existe(banco, num, competencia):
    return caminho_registro(
        banco, TABELA, ORIGINADORA, num, competencia
    ).is_file()


# =========================================================
# Listagem e estado
# =========================================================
def test_originadora_nasce_ativa_com_contagem(banco):
    linhas = repo_gerencia.listar_originadoras_gerencia(banco, '2026-07')

    assert len(linhas) == 1
    assert linhas[0]['originador'] == ORIGINADORA
    assert linhas[0]['em_conciliacao_ativa'] is True
    assert linhas[0]['total_convenios'] == 2
    assert linhas[0]['total_vigentes'] == 2
    assert linhas[0]['total_ligados'] == 2


def test_desativar_entra_no_filtro(banco):
    repo_gerencia.atualizar_estado_originadora(
        banco, ORIGINADORA, False, 'joao'
    )

    assert repo_gerencia.originadoras_desativadas(banco) == {ORIGINADORA}
    linha = repo_gerencia.listar_originadoras_gerencia(banco)[0]
    assert linha['em_conciliacao_ativa'] is False


def test_originadora_desconhecida_erra(banco):
    with pytest.raises(repo_gerencia.OriginadoraNaoEncontradaError):
        repo_gerencia.atualizar_estado_originadora(
            banco, 'Inexistente', False, 'x'
        )


# =========================================================
# Gate de grupo master na geração massiva
# =========================================================
def test_massivo_pula_originadora_desativada(banco, tmp_path):
    repo_gerencia.atualizar_estado_originadora(
        banco, ORIGINADORA, False, 'joao'
    )
    resumo = repo_geracao.gerar_competencia(
        banco, '2026-08', tmp_path / 'f', 'x'
    )

    assert resumo['gerados'] == []
    assert not _existe(banco, NUM_A, '2026-08')
    assert not _existe(banco, NUM_B, '2026-08')


def test_originadora_off_vence_toggle_ligado(banco, tmp_path):
    """Convênio ligado, mas originadora desativada: não gera (gate acima)."""
    repo_gerencia.atualizar_estado(
        banco, ORIGINADORA, NUM_A, {'em_conciliacao_ativa': True}, 'joao'
    )
    repo_gerencia.atualizar_estado_originadora(
        banco, ORIGINADORA, False, 'joao'
    )
    resumo = repo_geracao.gerar_competencia(
        banco, '2026-08', tmp_path / 'f', 'x'
    )

    assert resumo['gerados'] == []


# =========================================================
# Geração por originadora (massivo e período)
# =========================================================
def test_gerar_competencia_originadora(banco, tmp_path):
    resumo = repo_geracao.gerar_competencia_originadora(
        banco, ORIGINADORA, '2026-08', tmp_path / 'f', 'x'
    )

    assert resumo['desativada'] is False
    assert len(resumo['gerados']) == 2
    assert _existe(banco, NUM_A, '2026-08')
    assert _existe(banco, NUM_B, '2026-08')


def test_gerar_competencia_originadora_desativada(banco, tmp_path):
    repo_gerencia.atualizar_estado_originadora(
        banco, ORIGINADORA, False, 'joao'
    )
    resumo = repo_geracao.gerar_competencia_originadora(
        banco, ORIGINADORA, '2026-08', tmp_path / 'f', 'x'
    )

    assert resumo['desativada'] is True
    assert resumo['gerados'] == []
    assert not _existe(banco, NUM_A, '2026-08')


def test_gerar_periodo_originadora(banco, tmp_path):
    resumo = repo_geracao.gerar_competencias_periodo_originadora(
        banco, ORIGINADORA, '2026-08', '2026-09', tmp_path / 'f', 'x'
    )

    assert resumo['desativada'] is False
    assert len(resumo['por_competencia']) == 2
    assert len(resumo['tickets']) == 2
    assert _existe(banco, NUM_A, '2026-08')
    assert _existe(banco, NUM_B, '2026-09')


def test_gerar_periodo_originadora_intervalo_invalido(banco, tmp_path):
    with pytest.raises(repo_geracao.PeriodoInvalidoError):
        repo_geracao.gerar_competencias_periodo_originadora(
            banco, ORIGINADORA, '2026-09', '2026-08', tmp_path / 'f', 'x'
        )
