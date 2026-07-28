"""Testes das regras puras de gestão de usuários (hashing e validação)."""

# --- stdlib ---
import sys
from pathlib import Path

# --- terceiros ---
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# --- locais ---
from api.domain_usuarios import (  # noqa: E402
    ALGORITMO_HASH,
    Perfil,
    Status,
    gerar_hash_senha,
    montar_admin_padrao,
    montar_usuario,
    senha_forte_o_suficiente,
    validar_usuario,
    verificar_senha,
)

AGORA = '2026-07-27T09:00:00'


# =====================================================================
# Hashing de senha
# =====================================================================
def test_hash_confere_com_a_senha_correta():
    hash_ = gerar_hash_senha('senhaGrande1')
    assert hash_.startswith(f'{ALGORITMO_HASH}$')
    assert verificar_senha('senhaGrande1', hash_) is True


def test_hash_rejeita_senha_errada():
    hash_ = gerar_hash_senha('senhaGrande1')
    assert verificar_senha('outraSenha', hash_) is False


def test_hash_do_mesmo_texto_difere_pelo_salt():
    # Salt aleatório: dois hashes da mesma senha não podem colidir.
    assert gerar_hash_senha('senhaGrande1') != gerar_hash_senha('senhaGrande1')


def test_senha_vazia_nao_gera_hash():
    with pytest.raises(ValueError):
        gerar_hash_senha('')


@pytest.mark.parametrize('bruto', ['', 'sem-cifrao', 'a$b$c', 'x$1$s$h'])
def test_hash_malformado_nao_valida(bruto):
    assert verificar_senha('qualquer', bruto) is False


# =====================================================================
# Validação
# =====================================================================
def test_usuario_valido_nao_acusa_erro():
    dados = {
        'nome': 'Ana',
        'email': 'ana@x.com',
        'login': 'ana',
        'perfil': Perfil.OPERADOR.value,
        'status': Status.ATIVO.value,
    }
    assert validar_usuario(dados) == []


def test_validacao_lista_campos_faltando():
    erros = validar_usuario({'nome': '', 'email': 'invalido', 'login': ''})
    assert 'Informe o nome.' in erros
    assert 'E-mail inválido.' in erros
    assert 'Informe o login.' in erros


def test_validacao_barra_perfil_desconhecido():
    dados = {'nome': 'Ana', 'email': 'a@x.com', 'login': 'ana', 'perfil': 'X'}
    assert any('Perfil inválido' in e for e in validar_usuario(dados))


@pytest.mark.parametrize(
    'senha,esperado', [('curta', False), ('senhaGrande1', True)]
)
def test_forca_minima_da_senha(senha, esperado):
    assert senha_forte_o_suficiente(senha) is esperado


# =====================================================================
# Montagem de registro
# =====================================================================
def test_montar_usuario_nao_guarda_texto_da_senha():
    reg = montar_usuario(
        {'nome': 'Ana', 'email': 'A@X.com', 'login': 'Ana'},
        'senhaGrande1',
        AGORA,
    )
    assert 'senhaGrande1' not in str(reg)
    assert verificar_senha('senhaGrande1', reg['senha_hash']) is True
    # E-mail e login normalizados em minúsculas.
    assert reg['email'] == 'a@x.com'
    assert reg['login'] == 'ana'


def test_montar_usuario_recusa_senha_fraca():
    with pytest.raises(ValueError):
        montar_usuario(
            {'nome': 'Ana', 'email': 'a@x.com', 'login': 'ana'},
            'curta',
            AGORA,
        )


def test_admin_padrao_e_administrador_ativo_provisorio():
    admin = montar_admin_padrao('senhaGrande1', AGORA)
    assert admin['login'] == 'admin'
    assert admin['perfil'] == Perfil.ADMIN.value
    assert admin['status'] == Status.ATIVO.value
    assert admin['senha_provisoria'] is True
    assert verificar_senha('senhaGrande1', admin['senha_hash']) is True
