"""Testes dos responsáveis pela conciliação (colaboradores + workflow)."""

# --- stdlib ---
import sys
from pathlib import Path

# --- terceiros ---
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# --- locais ---
from api.domain_responsaveis import (  # noqa: E402
    USUARIO_NAO_CADASTRADO,
    responsavel_efetivo,
    validar_substituicao,
)
from api.repositories import responsaveis as repo  # noqa: E402

ORIGINADORA = 'Alvo Card'
NUMERO = '00001ALV'


@pytest.fixture()
def banco(tmp_path):
    """Banco com dois colaboradores ativos."""
    repo.criar_colaborador(tmp_path, {'nome': 'Ana'})
    repo.criar_colaborador(tmp_path, {'nome': 'Beto'})
    return tmp_path


# =========================================================
# Domínio puro
# =========================================================
def test_substituto_vigente_responde():
    efetivo = responsavel_efetivo(
        {
            'titular': 'Ana',
            'substituto': 'Beto',
            'substituicao_fim': '2026-07-31',
        },
        ['Ana', 'Beto'],
        '2026-07-10',
    )
    assert efetivo == {'responsavel': 'Beto', 'origem': 'substituto'}


def test_substituto_expirado_volta_ao_titular():
    efetivo = responsavel_efetivo(
        {
            'titular': 'Ana',
            'substituto': 'Beto',
            'substituicao_fim': '2026-07-31',
        },
        ['Ana', 'Beto'],
        '2026-08-05',
    )
    assert efetivo['responsavel'] == 'Ana'


def test_titular_desligado_vira_nao_cadastrado():
    efetivo = responsavel_efetivo({'titular': 'Ana'}, [], '2026-08-05')
    assert efetivo == {
        'responsavel': USUARIO_NAO_CADASTRADO,
        'origem': 'nao_cadastrado',
    }


def test_validar_substituicao_exige_substituto():
    assert validar_substituicao({'substituto': ''}) == [
        'Informe o substituto.'
    ]


# =========================================================
# Colaboradores
# =========================================================
def test_criar_colaborador_nasce_ativo(banco):
    colaboradores = repo.listar_colaboradores(banco)
    assert [c['nome'] for c in colaboradores] == ['Ana', 'Beto']
    assert all(c['status'] == 'ATIVO' for c in colaboradores)


def test_criar_colaborador_duplicado_erra(banco):
    with pytest.raises(repo.ChaveDuplicadaError):
        repo.criar_colaborador(banco, {'nome': 'Ana'})


def test_desligar_colaborador(banco):
    repo.atualizar_colaborador(banco, 'Ana', {'status': 'DESLIGADO'})
    assert repo.colaboradores_ativos(banco) == {'Beto'}


# =========================================================
# Titular e substituição (workflow)
# =========================================================
def test_definir_titular_reflete_no_efetivo(banco):
    r = repo.definir_titular(banco, ORIGINADORA, NUMERO, 'Ana', 'joao')
    assert r['titular'] == 'Ana'
    assert r['efetivo'] == 'Ana'
    assert r['origem'] == 'titular'


def test_titular_inexistente_erra(banco):
    with pytest.raises(repo.ColaboradorNaoEncontradoError):
        repo.definir_titular(banco, ORIGINADORA, NUMERO, 'Zed', 'joao')


def test_substituicao_vigente_responde_e_encerra(banco):
    repo.definir_titular(banco, ORIGINADORA, NUMERO, 'Ana', 'joao')
    r = repo.definir_substituicao(
        banco,
        ORIGINADORA,
        NUMERO,
        {'substituto': 'Beto', 'substituicao_fim': '2099-12-31'},
        'joao',
    )
    assert r['efetivo'] == 'Beto'
    assert r['origem'] == 'substituto'

    devolvido = repo.encerrar_substituicao(banco, ORIGINADORA, NUMERO, 'joao')
    assert devolvido['efetivo'] == 'Ana'


def test_desligar_titular_deixa_convenio_disponivel(banco):
    repo.definir_titular(banco, ORIGINADORA, NUMERO, 'Ana', 'joao')
    repo.atualizar_colaborador(banco, 'Ana', {'status': 'DESLIGADO'})

    r = repo.obter_responsavel(banco, ORIGINADORA, NUMERO)
    assert r['titular'] == 'Ana'  # o cadastro do vínculo é preservado
    assert r['efetivo'] == USUARIO_NAO_CADASTRADO  # mas o efetivo cai


def test_historico_registra_auditoria(banco):
    repo.definir_titular(banco, ORIGINADORA, NUMERO, 'Ana', 'joao')
    repo.definir_substituicao(
        banco, ORIGINADORA, NUMERO, {'substituto': 'Beto'}, 'maria'
    )
    r = repo.obter_responsavel(banco, ORIGINADORA, NUMERO)

    acoes = [(h['acao'], h['ator']) for h in r['historico']]
    assert acoes == [('titular', 'joao'), ('substituicao', 'maria')]
