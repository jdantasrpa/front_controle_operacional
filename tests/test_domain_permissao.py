"""Testes das regras de permissão e do fluxo de aprovação de acesso."""

# --- stdlib ---
import sys
from pathlib import Path

# --- terceiros ---
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# --- locais ---
from api.domain_permissao import (  # noqa: E402
    StatusSolicitacao,
    aplicar_resposta_autorizacao,
    gerar_token_autorizacao,
    montar_solicitacao,
    pode_alterar_equipe,
    pode_criar_usuario,
    tem_acesso_total,
)

AGORA = '2026-07-27T09:00:00'


@pytest.mark.parametrize(
    'perfil,esperado',
    [('ADMIN', True), ('MASTER', True), ('GESTOR', False),
     ('OPERADOR', False), ('LEITOR', False)],
)
def test_acesso_total_de_admin_e_master(perfil, esperado):
    assert tem_acesso_total(perfil) is esperado


@pytest.mark.parametrize(
    'perfil,esperado',
    [('ADMIN', True), ('MASTER', False), ('GESTOR', False)],
)
def test_so_admin_cria_usuario(perfil, esperado):
    assert pode_criar_usuario(perfil) is esperado


def test_master_tem_tudo_menos_criar_usuario():
    assert tem_acesso_total('MASTER') is True
    assert pode_criar_usuario('MASTER') is False


@pytest.mark.parametrize(
    'perfil,esperado',
    [('ADMIN', True), ('MASTER', True), ('GESTOR', False),
     ('OPERADOR', False)],
)
def test_adm_e_master_alteram_equipe(perfil, esperado):
    assert pode_alterar_equipe(perfil) is esperado


def test_token_e_unico_e_longo():
    a, b = gerar_token_autorizacao(), gerar_token_autorizacao()
    assert a != b
    assert len(a) >= 32


def test_solicitacao_nasce_pendente_com_token():
    s = montar_solicitacao({'nome': 'Ana', 'email': 'A@X.com'}, AGORA)
    assert s['status'] == StatusSolicitacao.PENDENTE.value
    assert s['email'] == 'a@x.com'
    assert s['perfil_solicitado'] == 'OPERADOR'
    assert len(s['token_autorizacao']) >= 32


def test_resposta_negativa_nega_a_criacao():
    r = aplicar_resposta_autorizacao(False, 'Chefe@X.com', AGORA, 'sem verba')
    assert r['status'] == StatusSolicitacao.NEGADA.value
    assert r['autorizador_email'] == 'chefe@x.com'
    assert r['motivo'] == 'sem verba'


def test_resposta_positiva_aprova():
    r = aplicar_resposta_autorizacao(True, 'chefe@x.com', AGORA)
    assert r['status'] == StatusSolicitacao.APROVADA.value
