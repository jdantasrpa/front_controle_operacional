"""Testes da numeração automática e da averbadora no convênio."""

# --- stdlib ---
import sys
from pathlib import Path

# --- terceiros ---
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# --- locais ---
from api.repositories import convenios as repo  # noqa: E402

CNPJ_A = '02.476.034/0001-82'
CNPJ_B = '00.394.429/0082-76'


@pytest.fixture()
def banco(tmp_path):
    """Banco com a originadora Alvo Card (código ALV) cadastrada."""
    (tmp_path / 'cadastro_convenio').mkdir()
    repo.criar_originadora(tmp_path, {'nome': 'Alvo Card', 'codigo': 'ALV'})
    return tmp_path


def _convenio(banco, cnpj, averbadora=''):
    repo.criar_convenio(
        banco,
        {
            'cnpj_convenio': cnpj,
            'nome_convenio': 'ÓRGÃO',
            'averbadora': averbadora,
        },
    )


def test_numero_gerado_com_codigo_da_originadora(banco):
    _convenio(banco, CNPJ_A)
    vinculo = repo.criar_vinculo(
        banco,
        CNPJ_A,
        {'originador': 'Alvo Card', 'competencia_inicio': '2025-01'},
    )

    assert vinculo['numero_convenio'] == '00001ALV'


def test_numero_incrementa_a_cada_vinculo(banco):
    _convenio(banco, CNPJ_A)
    _convenio(banco, CNPJ_B)
    primeiro = repo.criar_vinculo(
        banco,
        CNPJ_A,
        {'originador': 'Alvo Card', 'competencia_inicio': '2025-01'},
    )
    segundo = repo.criar_vinculo(
        banco,
        CNPJ_B,
        {'originador': 'Alvo Card', 'competencia_inicio': '2025-01'},
    )

    assert primeiro['numero_convenio'] == '00001ALV'
    assert segundo['numero_convenio'] == '00002ALV'


def test_originadora_sem_codigo_nao_gera(tmp_path):
    (tmp_path / 'cadastro_convenio').mkdir()
    repo.criar_originadora(tmp_path, {'nome': 'Sem Código'})
    _convenio(tmp_path, CNPJ_A)

    with pytest.raises(repo.RegistroInvalidoError):
        repo.criar_vinculo(
            tmp_path,
            CNPJ_A,
            {'originador': 'Sem Código', 'competencia_inicio': '2025-01'},
        )


def test_numero_informado_e_respeitado(banco):
    _convenio(banco, CNPJ_A)
    vinculo = repo.criar_vinculo(
        banco,
        CNPJ_A,
        {
            'originador': 'Alvo Card',
            'numero_convenio': '99999ALV',
            'competencia_inicio': '2025-01',
        },
    )

    assert vinculo['numero_convenio'] == '99999ALV'


def test_averbadora_do_convenio_copia_para_o_vinculo(banco):
    _convenio(banco, CNPJ_A, averbadora='Zetra')
    vinculo = repo.criar_vinculo(
        banco,
        CNPJ_A,
        {'originador': 'Alvo Card', 'competencia_inicio': '2025-01'},
    )

    assert vinculo['averbadora'] == 'Zetra'
    assert repo.obter_convenio(banco, CNPJ_A)['averbadora'] == 'Zetra'
