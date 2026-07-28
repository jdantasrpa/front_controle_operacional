"""Testes de I/O da geração de vencimentários (banco de arquivos)."""

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
from api.repositories import convenios as repo_convenios  # noqa: E402
from api.repositories import geracao as repo  # noqa: E402

CNPJ = '02.476.034/0001-82'
ORIGINADORA = 'Alvo Card'
NUMERO = '00011ALV'
NOME = 'GOV. GOIÁS'
TABELA = 'tabela_concilicacao_convenio'

VENCIMENTARIOS_JULHO = [
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
        'valor_remessa': 607769.2,
        'valor_retorno': 597133.24,
        'valor_repasse': 590000.0,
        'status_conciliacao': 'CONCILIADO',
        'motivo_falta_conciliacao': '',
        'porcentagem_inadimplencia': 1.2,
        'criado_em': '2026-07-05',
        'atualizado_em': '2026-07-28',
    },
    {
        'id': 94,
        'originador': ORIGINADORA,
        'mes_referencia_conciliacao': '2026-07',
        'numero_convenio': NUMERO,
        'nome_convenio': NOME,
        'cnpj_convenio': CNPJ,
        'data_vencimento': '2026-07-20',
        'data_env_remessa': '2026-07-17',
        'data_sla_concilicacao': '2026-07-21',
        'qtd_dias_sla_pagamento': '1',
        'data_corte': '2026-07-18',
        'valor_remessa': 737241.11,
        'valor_retorno': 706055.81,
        'valor_repasse': 706055.81,
        'status_conciliacao': 'CONCILIADO',
        'motivo_falta_conciliacao': '',
        'porcentagem_inadimplencia': 4.23,
        'criado_em': '2026-07-20',
        'atualizado_em': '2026-07-21',
    },
]


def _gravar_julho(banco: Path) -> None:
    """Grava a competência 2026-07 de origem para a clonagem."""
    gravar_arquivo(
        caminho_registro(banco, TABELA, ORIGINADORA, NUMERO, '2026-07'),
        montar_documento(
            TABELA, ORIGINADORA, NUMERO, VENCIMENTARIOS_JULHO, '2026-07'
        ),
    )


@pytest.fixture()
def banco(tmp_path):
    """Banco com um convênio vigente e o mês 2026-07 pronto para clonar."""
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
            'competencia_fim': '',
            'status': 'ATIVO',
        },
    )
    _gravar_julho(tmp_path)
    return tmp_path


def _ler(banco: Path, competencia: str) -> list[dict]:
    lido = ler_arquivo(
        caminho_registro(banco, TABELA, ORIGINADORA, NUMERO, competencia)
    )
    return lido[0]['registros'] if lido else []


# =========================================================
# Geração massiva
# =========================================================
def test_gerar_clona_o_mes_anterior_zerado(banco, tmp_path):
    fila = tmp_path / 'fila'
    resumo = repo.gerar_competencia(banco, '2026-08', fila, 'joao')

    agosto = _ler(banco, '2026-08')
    assert [r['data_vencimento'] for r in agosto] == [
        '2026-08-05',
        '2026-08-20',
    ]
    assert all(r['valor_retorno'] == 0.0 for r in agosto)
    assert all(r['status_conciliacao'] == 'PENDENTE' for r in agosto)
    assert len(resumo['gerados']) == 1
    assert resumo['competencia_origem'] == '2026-07'


def test_gerar_ids_unicos_acima_do_historico(banco, tmp_path):
    repo.gerar_competencia(banco, '2026-08', tmp_path / 'fila', 'joao')

    agosto = _ler(banco, '2026-08')
    # Histórico ia até 94; os clones seguem a partir de 95.
    assert [r['id'] for r in agosto] == [95, 96]


def test_gerar_emite_ticket_na_fila(banco, tmp_path):
    fila = tmp_path / 'fila'
    resumo = repo.gerar_competencia(banco, '2026-08', fila, 'joao')

    ticket = ler_arquivo(fila / resumo['ticket'])
    assert ticket is not None
    corpo = ticket[0]
    assert corpo['tipo'] == 'GERAR_COMPETENCIA'
    assert corpo['competencia'] == '2026-08'
    assert corpo['vinculos'][0]['dias_vencimento'] == ['05', '20']


def test_gerar_e_idempotente(banco, tmp_path):
    fila = tmp_path / 'fila'
    repo.gerar_competencia(banco, '2026-08', fila, 'joao')
    # O operador editou um valor depois da 1ª geração.
    agosto = _ler(banco, '2026-08')
    agosto[0]['valor_retorno'] = 123.0
    gravar_arquivo(
        caminho_registro(banco, TABELA, ORIGINADORA, NUMERO, '2026-08'),
        montar_documento(TABELA, ORIGINADORA, NUMERO, agosto, '2026-08'),
    )

    resumo = repo.gerar_competencia(banco, '2026-08', fila, 'joao')

    assert len(resumo['pulados']) == 1
    assert len(resumo['gerados']) == 0
    # Não sobrescreveu a edição do operador.
    assert _ler(banco, '2026-08')[0]['valor_retorno'] == 123.0


def test_gerar_vigente_sem_origem_nao_quebra(banco, tmp_path):
    """Vínculo vigente sem mês anterior entra como 'sem_origem'."""
    repo_convenios.criar_vinculo(
        banco,
        CNPJ,
        {
            'originador': 'Hatchbank',
            'numero_convenio': '00061HTC',
            'competencia_inicio': '2025-01',
            'status': 'ATIVO',
        },
    )
    resumo = repo.gerar_competencia(banco, '2026-08', tmp_path / 'fila', 'x')

    assert len(resumo['sem_origem']) == 1
    assert resumo['sem_origem'][0]['originador'] == 'Hatchbank'


# =========================================================
# Vencimentário avulso
# =========================================================
def test_avulso_grava_com_id_unico(banco):
    registro = repo.criar_vencimentario_avulso(
        banco,
        '2026-08',
        {
            'originador': ORIGINADORA,
            'numero_convenio': NUMERO,
            'data_vencimento': '2026-08-05',
            'valor_retorno': 100.0,
        },
    )

    assert registro['id'] == 95  # acima do histórico (94)
    assert registro['mes_referencia_conciliacao'] == '2026-08'
    assert _ler(banco, '2026-08')[0]['valor_retorno'] == 100.0


def test_avulso_recusa_data_fora_da_competencia(banco):
    with pytest.raises(repo.VencimentarioInvalidoError):
        repo.criar_vencimentario_avulso(
            banco,
            '2026-08',
            {
                'originador': ORIGINADORA,
                'numero_convenio': NUMERO,
                'data_vencimento': '2026-07-05',
            },
        )


def test_avulso_soma_ao_mes_existente(banco):
    repo.criar_vencimentario_avulso(
        banco,
        '2026-07',
        {
            'originador': ORIGINADORA,
            'numero_convenio': NUMERO,
            'data_vencimento': '2026-07-25',
        },
    )
    assert len(_ler(banco, '2026-07')) == 3


# =========================================================
# Exclusão de um vencimento
# =========================================================
def test_excluir_remove_apenas_o_vencimento_alvo(banco):
    repo.excluir_vencimentario(
        banco, ORIGINADORA, NUMERO, '2026-07', '2026-07-05'
    )
    restantes = _ler(banco, '2026-07')
    assert [r['data_vencimento'] for r in restantes] == ['2026-07-20']


def test_excluir_ultimo_remove_o_arquivo(banco):
    for data in ('2026-07-05', '2026-07-20'):
        repo.excluir_vencimentario(banco, ORIGINADORA, NUMERO, '2026-07', data)

    caminho = caminho_registro(banco, TABELA, ORIGINADORA, NUMERO, '2026-07')
    assert not caminho.is_file()


def test_excluir_data_inexistente_erra(banco):
    with pytest.raises(repo.VencimentarioNaoEncontradoError):
        repo.excluir_vencimentario(
            banco, ORIGINADORA, NUMERO, '2026-07', '2026-07-31'
        )
