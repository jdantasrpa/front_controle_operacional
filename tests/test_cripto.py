"""Testes do serviço de criptografia de aplicação (AES-256-GCM)."""

# --- stdlib ---
import base64
import sys
from pathlib import Path

# --- terceiros ---
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# --- locais ---
from api.cripto import (  # noqa: E402
    VARIAVEL_CHAVE,
    CriptoConfigError,
    CriptoError,
    criptografar,
    criptografar_campos,
    descriptografar,
    descriptografar_campos,
    esta_criptografado,
    gerar_chave_mestra,
)


@pytest.fixture(autouse=True)
def _chave(monkeypatch):
    monkeypatch.setenv(VARIAVEL_CHAVE, gerar_chave_mestra())


# =====================================================================
# Ciclo cifra/decifra
# =====================================================================
def test_round_trip_preserva_o_texto():
    token = criptografar('12.345.678/0001-90')
    assert esta_criptografado(token)
    assert descriptografar(token) == '12.345.678/0001-90'


def test_none_passa_direto():
    assert criptografar(None) is None
    assert descriptografar(None) is None


def test_cifra_nao_e_deterministica():
    # Nonce aleatório: o mesmo texto gera envelopes diferentes.
    assert criptografar('igual') != criptografar('igual')


def test_nao_recifra_valor_ja_cifrado():
    token = criptografar('segredo')
    assert criptografar(token) == token


def test_texto_claro_e_tolerado_na_leitura():
    # Migração gradual: o que não é envelope volta inalterado.
    assert descriptografar('ainda em claro') == 'ainda em claro'


# =====================================================================
# Segurança
# =====================================================================
def test_chave_errada_falha(monkeypatch):
    token = criptografar('segredo')
    monkeypatch.setenv(VARIAVEL_CHAVE, gerar_chave_mestra())
    with pytest.raises(CriptoError):
        descriptografar(token)


def test_adulteracao_falha():
    token = criptografar('segredo')
    prefixo, nonce, cifra = token.split('$')
    adulterado = '$'.join((prefixo, nonce, cifra[:-4] + 'AAAA'))
    with pytest.raises(CriptoError):
        descriptografar(adulterado)


def test_chave_ausente_falha(monkeypatch):
    monkeypatch.delenv(VARIAVEL_CHAVE, raising=False)
    with pytest.raises(CriptoConfigError):
        criptografar('x')


def test_chave_tamanho_invalido_falha(monkeypatch):
    monkeypatch.setenv(
        VARIAVEL_CHAVE, base64.b64encode(b'curta').decode('ascii')
    )
    with pytest.raises(CriptoConfigError):
        criptografar('x')


# =====================================================================
# Helpers de campos (imutáveis)
# =====================================================================
def test_criptografar_campos_so_mexe_nos_indicados():
    original = {'nome': 'X', 'cnpj': '1', 'obs': 'nota'}
    guardado = criptografar_campos(original, ['cnpj', 'obs'])

    assert guardado['nome'] == 'X'
    assert esta_criptografado(guardado['cnpj'])
    assert esta_criptografado(guardado['obs'])
    # Não modifica o original.
    assert original['cnpj'] == '1'


def test_round_trip_de_campos():
    original = {'cnpj': '99', 'chave_pix': 'a@b.com', 'ativo': True}
    campos = ['cnpj', 'chave_pix']
    guardado = criptografar_campos(original, campos)
    lido = descriptografar_campos(guardado, campos)

    assert lido == original
