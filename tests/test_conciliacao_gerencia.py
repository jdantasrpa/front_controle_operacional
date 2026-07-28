"""Testes do estado de gerência de convênios pela Conciliação."""

# --- stdlib ---
import sys
from pathlib import Path

# --- terceiros ---
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# --- locais ---
from api.domain_conciliacao_gerencia import (  # noqa: E402
    aplicar_estado,
    esta_ligado,
    validar_estado,
)
from api.repositories import conciliacao_gerencia as repo  # noqa: E402
from api.repositories import convenios as repo_convenios  # noqa: E402

CNPJ = '02.476.034/0001-82'
ORIGINADORA = 'Alvo Card'
NUMERO = '00011ALV'
NOME = 'GOV. GOIÁS'


@pytest.fixture()
def banco(tmp_path):
    """Banco com um convênio e um vínculo vigente cadastrados pela Gestão."""
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
    return tmp_path


def _linha(banco, competencia=''):
    return repo.listar_gerencia(banco, competencia)[0]


# =========================================================
# Domínio puro
# =========================================================
def test_ligado_por_padrao_sem_registro():
    assert esta_ligado({}) is True


def test_aplicar_estado_preserva_campo_omitido():
    atual = {'em_conciliacao_ativa': False, 'dia_vencimento': 5}
    novo = aplicar_estado(atual, {'em_conciliacao_ativa': True})

    assert novo['em_conciliacao_ativa'] is True
    assert novo['dia_vencimento'] == 5


def test_validar_estado_recusa_dia_fora_da_faixa():
    assert validar_estado({'dia_vencimento': 31})


def test_validar_estado_recusa_offset_negativo():
    assert validar_estado({'dias_antes_remessa': -2})


def test_validar_estado_aceita_vazio():
    assert validar_estado({'dia_vencimento': ''}) == []


# =========================================================
# Visão de gerência
# =========================================================
def test_gerencia_nasce_ligada_e_com_cadastro(banco):
    linha = _linha(banco)

    assert linha['em_conciliacao_ativa'] is True
    assert linha['dia_vencimento'] == ''
    assert linha['nome_convenio'] == NOME
    assert linha['cadastrado_em']  # criado_em do vínculo, não vazio


def test_desligar_reflete_na_visao_e_no_filtro(banco):
    repo.atualizar_estado(
        banco, ORIGINADORA, NUMERO, {'em_conciliacao_ativa': False}, 'joao'
    )

    assert _linha(banco)['em_conciliacao_ativa'] is False
    assert repo.chaves_desligadas(banco) == {(ORIGINADORA, NUMERO)}


def test_religar_limpa_o_filtro(banco):
    repo.atualizar_estado(
        banco, ORIGINADORA, NUMERO, {'em_conciliacao_ativa': False}, 'joao'
    )
    repo.atualizar_estado(
        banco, ORIGINADORA, NUMERO, {'em_conciliacao_ativa': True}, 'joao'
    )

    assert repo.chaves_desligadas(banco) == set()


def test_dia_vencimento_manual_persiste(banco):
    repo.atualizar_estado(
        banco,
        ORIGINADORA,
        NUMERO,
        {'dia_vencimento': 5},
        'joao',
    )

    assert _linha(banco)['dia_vencimento'] == 5


def test_atualizar_um_campo_preserva_o_outro(banco):
    repo.atualizar_estado(
        banco, ORIGINADORA, NUMERO, {'em_conciliacao_ativa': False}, 'joao'
    )
    repo.atualizar_estado(
        banco,
        ORIGINADORA,
        NUMERO,
        {'dia_vencimento': 5},
        'joao',
    )

    linha = _linha(banco)
    assert linha['em_conciliacao_ativa'] is False
    assert linha['dia_vencimento'] == 5


def test_dia_fora_da_faixa_recusado(banco):
    with pytest.raises(repo.EstadoInvalidoError):
        repo.atualizar_estado(
            banco,
            ORIGINADORA,
            NUMERO,
            {'dia_vencimento': 31},
            'joao',
        )


def test_estado_de_vinculo_inexistente_erra(banco):
    with pytest.raises(repo.VinculoNaoEncontradoError):
        repo.atualizar_estado(
            banco,
            'Hatchbank',
            '00061HTC',
            {'em_conciliacao_ativa': False},
            'x',
        )


# =========================================================
# Status da Gestão surfaçado (só leitura) e independência
# =========================================================
def test_motivo_de_inativacao_da_gestao_aparece(banco):
    repo_convenios.atualizar_convenio(
        banco,
        CNPJ,
        {
            'nome_convenio': NOME,
            'status': 'INATIVO',
            'observacao': 'Contrato encerrado pelo órgão.',
        },
    )

    linha = _linha(banco)
    assert linha['status_gestao'] == 'INATIVO'
    assert linha['motivo_gestao'] == 'Contrato encerrado pelo órgão.'
    assert linha['nivel_gestao'] == 'convênio'


def test_status_gestao_nao_conversa_com_a_conciliacao(banco):
    """Inativar na Gestão não desliga na Conciliação, e vice-versa."""
    repo_convenios.atualizar_convenio(
        banco, CNPJ, {'nome_convenio': NOME, 'status': 'INATIVO'}
    )

    # A Conciliação continua com o seu próprio estado (ligado por padrão).
    assert _linha(banco)['em_conciliacao_ativa'] is True

    # E desligar na Conciliação não muda o status da Gestão.
    repo.atualizar_estado(
        banco, ORIGINADORA, NUMERO, {'em_conciliacao_ativa': False}, 'joao'
    )
    assert _linha(banco)['status_gestao'] == 'INATIVO'
