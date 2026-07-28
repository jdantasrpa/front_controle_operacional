"""Testes do contrato HTTP da geração de vencimentários."""

# --- stdlib ---
import sys
from pathlib import Path

# --- terceiros ---
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# --- locais ---
from api import app as modulo_app  # noqa: E402
from api.arquivos import (  # noqa: E402
    caminho_registro,
    gravar_arquivo,
    ler_arquivo,
    montar_documento,
)
from api.config import Configuracao  # noqa: E402
from api.repositories import convenios as repo_convenios  # noqa: E402

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


@pytest.fixture()
def cliente(banco, monkeypatch):
    """Cliente HTTP apontado para um banco isolado, com fila em tmp."""
    config = Configuracao(
        banco_conciliacao=banco / 'x.db',
        banco_cobranca=banco / 'y.db',
        pasta_fila_entrada=None,
        host='127.0.0.1',
        porta=8000,
        pasta_banco=banco,
        pasta_fila_geracao=banco / 'fila_geracao',
    )
    monkeypatch.setattr(modulo_app, 'obter_configuracao', lambda: config)
    return TestClient(modulo_app.app)


def _rota_venc():
    return f'/api/vinculos/{ORIGINADORA}/{NUMERO}/vencimentarios'


# =========================================================
# Gerar competência (massivo)
# =========================================================
def test_gerar_competencia_devolve_resumo(cliente, banco):
    resposta = cliente.post(
        '/api/conciliacao/gerencia/gerar-competencia', json={'competencia': '2026-08'}
    )

    assert resposta.status_code == 200
    resumo = resposta.json()['resumo']
    assert resumo['competencia'] == '2026-08'
    assert len(resumo['gerados']) == 1

    lido = ler_arquivo(
        caminho_registro(banco, TABELA, ORIGINADORA, NUMERO, '2026-08')
    )
    assert lido[0]['registros'][0]['data_vencimento'] == '2026-08-05'
    assert lido[0]['registros'][0]['status_conciliacao'] == 'PENDENTE'


def test_gerar_competencia_grava_ticket(cliente, banco):
    resposta = cliente.post(
        '/api/conciliacao/gerencia/gerar-competencia', json={'competencia': '2026-08'}
    )
    ticket = resposta.json()['resumo']['ticket']

    assert (banco / 'fila_geracao' / ticket).is_file()


# =========================================================
# Avulso
# =========================================================
def test_criar_avulso_201(cliente, banco):
    resposta = cliente.post(
        _rota_venc(),
        json={
            'competencia': '2026-08',
            'data_vencimento': '2026-08-10',
            'valor_retorno': 50.0,
        },
    )

    assert resposta.status_code == 201
    assert resposta.json()['vencimentario']['data_vencimento'] == '2026-08-10'


def test_criar_avulso_data_fora_da_competencia_400(cliente):
    resposta = cliente.post(
        _rota_venc(),
        json={'competencia': '2026-08', 'data_vencimento': '2026-07-10'},
    )

    assert resposta.status_code == 400
    assert 'competência' in resposta.json()['detail']


# =========================================================
# Exclusão
# =========================================================
def test_excluir_vencimento_204(cliente, banco):
    resposta = cliente.request(
        'DELETE',
        _rota_venc(),
        params={'competencia': '2026-07', 'data_vencimento': '2026-07-05'},
    )

    assert resposta.status_code == 204
    caminho = caminho_registro(banco, TABELA, ORIGINADORA, NUMERO, '2026-07')
    assert not caminho.is_file()  # era o único vencimento do mês


def test_excluir_vencimento_inexistente_404(cliente):
    resposta = cliente.request(
        'DELETE',
        _rota_venc(),
        params={'competencia': '2026-07', 'data_vencimento': '2026-07-31'},
    )

    assert resposta.status_code == 404
