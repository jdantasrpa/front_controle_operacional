"""Testes do confronto financeiro e do ativar/desativar de custo."""

# --- stdlib ---
import sys
from pathlib import Path

# --- terceiros ---
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# --- locais ---
from api.domain_confronto import classificar_confronto  # noqa: E402
from api.repositories import convenios as repo  # noqa: E402

CNPJ = '02.476.034/0001-82'
ORIGINADORA = 'Alvo Card'
NUMERO = '00011ALV'
NOME = 'GOV. GOIÁS'


@pytest.fixture()
def banco(tmp_path):
    """Convênio com um custo percentual de 2,5% sobre o retorno."""
    (tmp_path / 'cadastro_convenio').mkdir()
    repo.criar_convenio(
        tmp_path, {'cnpj_convenio': CNPJ, 'nome_convenio': NOME}
    )
    repo.criar_vinculo(
        tmp_path,
        CNPJ,
        {
            'originador': ORIGINADORA,
            'numero_convenio': NUMERO,
            'competencia_inicio': '2025-01',
        },
    )
    repo.salvar_custo(
        tmp_path,
        ORIGINADORA,
        NUMERO,
        {
            'metodo': 'PERCENTUAL',
            'base_calculo': 'VALOR_RETORNO',
            'aliquota_percentual': 2.5,
            'competencia_inicio': '2025-01',
        },
    )
    return tmp_path


def _confrontar(banco, retorno, recebido, quantidade=0):
    return repo.confrontar(
        banco,
        ORIGINADORA,
        NUMERO,
        '2026-07',
        {
            'valor_retorno': retorno,
            'valor_recebido': recebido,
            'quantidade': quantidade,
        },
    )


# =========================================================
# Domínio (régua de classificação)
# =========================================================
def test_conciliado_diferenca_menor_que_um_centavo():
    assert classificar_confronto(1000, 1000, 0)['status'] == 'Conciliado'


def test_a_maior_dentro_de_5():
    assert (
        classificar_confronto(1000, 1020, 0)['status'] == 'Conciliado a maior'
    )


def test_a_menor_dentro_de_5():
    assert (
        classificar_confronto(1000, 980, 0)['status'] == 'Conciliado a menor'
    )


def test_divergente_acima_de_5():
    assert classificar_confronto(1000, 900, 0)['status'] == 'Divergente'


def test_sem_extrato_quando_nao_ha_recebido():
    assert classificar_confronto(1000, 0, 20)['status'] == 'Sem Extrato'


def test_sem_retorno_quando_bpo_nao_informou():
    assert classificar_confronto(0, 500, 0)['status'] == 'Sem Retorno'


# =========================================================
# Confronto com o custo cadastrado
# =========================================================
def test_custo_aplicado_entra_no_esperado(banco):
    # custo = 2,5% de 1000 = 25; esperado = 1025; recebido 1025 -> concilia.
    r = _confrontar(banco, 1000, 1025)
    assert r['custo'] == 25.0
    assert r['esperado'] == 1025.0
    assert r['status'] == 'Conciliado'


def test_recebido_so_o_retorno_fica_devendo_o_custo(banco):
    r = _confrontar(banco, 1000, 1000)  # não pagou o custo
    assert r['devendo'] == 25.0
    assert r['status'] == 'Conciliado a menor'


def test_percentual_nao_exige_quantidade(banco):
    assert _confrontar(banco, 1000, 1025)['exige_quantidade'] is False


# =========================================================
# Ativar/desativar custo (Recado A)
# =========================================================
def test_desativar_custo_zera_o_custo_aplicado(banco):
    repo.alternar_status_custo(banco, ORIGINADORA, NUMERO, '2025-01', False)
    r = _confrontar(banco, 1000, 1025)

    assert r['custo'] == 0.0
    # sem custo, esperado = 1000 e recebido 1025 -> a maior.
    assert r['status'] == 'Conciliado a maior'


def test_reativar_custo_volta_a_aplicar(banco):
    repo.alternar_status_custo(banco, ORIGINADORA, NUMERO, '2025-01', False)
    repo.alternar_status_custo(banco, ORIGINADORA, NUMERO, '2025-01', True)

    assert _confrontar(banco, 1000, 1025)['custo'] == 25.0


def test_alternar_custo_inexistente_erra(banco):
    with pytest.raises(repo.RegistroInvalidoError):
        repo.alternar_status_custo(
            banco, ORIGINADORA, NUMERO, '2099-01', False
        )


def test_por_contrato_exige_quantidade(banco):
    repo.salvar_custo(
        banco,
        ORIGINADORA,
        NUMERO,
        {
            'metodo': 'POR_CONTRATO',
            'valor_unitario': 3.5,
            'competencia_inicio': '2026-01',
        },
    )
    r = _confrontar(banco, 1000, 1035, quantidade=10)

    assert r['exige_quantidade'] is True
    assert r['custo'] == 35.0  # 3,5 x 10 contratos
