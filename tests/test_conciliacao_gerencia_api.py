"""Testes do contrato HTTP da gerência de convênios pela Conciliação."""

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


def _rota_estado():
    return f'/api/conciliacao/gerencia/{ORIGINADORA}/{NUMERO}'


# =========================================================
# Visão de gerência
# =========================================================
def test_listar_gerencia_nasce_ligada(cliente):
    resposta = cliente.get('/api/conciliacao/gerencia')

    assert resposta.status_code == 200
    linhas = resposta.json()['linhas']
    assert linhas[0]['em_conciliacao_ativa'] is True
    assert linhas[0]['nome_convenio'] == NOME


# =========================================================
# Liga/desliga e dia de vencimento
# =========================================================
def test_desligar_via_patch(cliente):
    resposta = cliente.patch(
        _rota_estado(), json={'em_conciliacao_ativa': False}
    )

    assert resposta.status_code == 200
    assert resposta.json()['estado']['em_conciliacao_ativa'] is False


def test_dia_vencimento_via_patch(cliente):
    resposta = cliente.patch(_rota_estado(), json={'dia_vencimento': 5})

    assert resposta.status_code == 200
    assert resposta.json()['estado']['dia_vencimento'] == 5


def test_dia_fora_da_faixa_400(cliente):
    resposta = cliente.patch(_rota_estado(), json={'dia_vencimento': 31})

    assert resposta.status_code == 400


def test_estado_vinculo_inexistente_404(cliente):
    resposta = cliente.patch(
        '/api/conciliacao/gerencia/Hatchbank/00061HTC',
        json={'em_conciliacao_ativa': False},
    )

    assert resposta.status_code == 404


# =========================================================
# Massivo gated pelo toggle
# =========================================================
def test_massivo_pula_desligado(cliente, banco):
    cliente.patch(_rota_estado(), json={'em_conciliacao_ativa': False})
    resposta = cliente.post(
        '/api/conciliacao/gerencia/gerar-competencia',
        json={'competencia': '2026-08'},
    )

    assert resposta.status_code == 200
    assert resposta.json()['resumo']['gerados'] == []
    assert not caminho_registro(
        banco, TABELA, ORIGINADORA, NUMERO, '2026-08'
    ).is_file()


# =========================================================
# Geração por período
# =========================================================
def test_gerar_periodo_devolve_resumo(cliente, banco):
    resposta = cliente.post(
        '/api/conciliacao/gerencia/gerar-periodo',
        json={
            'originador': ORIGINADORA,
            'numero_convenio': NUMERO,
            'competencia_inicio': '2026-08',
            'competencia_fim': '2026-09',
        },
    )

    assert resposta.status_code == 200
    resumo = resposta.json()['resumo']
    assert len(resumo['gerados']) == 2
    lido = ler_arquivo(
        caminho_registro(banco, TABELA, ORIGINADORA, NUMERO, '2026-08')
    )
    assert lido[0]['registros'][0]['status_conciliacao'] == 'PENDENTE'


def test_gerar_periodo_invalido_400(cliente):
    resposta = cliente.post(
        '/api/conciliacao/gerencia/gerar-periodo',
        json={
            'originador': ORIGINADORA,
            'numero_convenio': NUMERO,
            'competencia_inicio': '2026-10',
            'competencia_fim': '2026-08',
        },
    )

    assert resposta.status_code == 400


# =========================================================
# Originadoras (grupo master)
# =========================================================
def test_listar_originadoras_nasce_ativa(cliente):
    resposta = cliente.get('/api/conciliacao/gerencia/originadoras')

    assert resposta.status_code == 200
    originadoras = resposta.json()['originadoras']
    assert originadoras[0]['originador'] == ORIGINADORA
    assert originadoras[0]['em_conciliacao_ativa'] is True
    assert originadoras[0]['total_convenios'] == 1


def test_desativar_originadora_e_gate_no_massivo(cliente, banco):
    patch = cliente.patch(
        f'/api/conciliacao/gerencia/originadoras/{ORIGINADORA}',
        json={'em_conciliacao_ativa': False},
    )
    assert patch.status_code == 200
    assert patch.json()['originadora']['em_conciliacao_ativa'] is False

    massivo = cliente.post(
        '/api/conciliacao/gerencia/gerar-competencia',
        json={'competencia': '2026-08'},
    )
    assert massivo.json()['resumo']['gerados'] == []
    assert not caminho_registro(
        banco, TABELA, ORIGINADORA, NUMERO, '2026-08'
    ).is_file()


def test_originadora_inexistente_404(cliente):
    resposta = cliente.patch(
        '/api/conciliacao/gerencia/originadoras/Inexistente',
        json={'em_conciliacao_ativa': False},
    )

    assert resposta.status_code == 404


def test_gerar_competencia_de_originadora(cliente, banco):
    resposta = cliente.post(
        f'/api/conciliacao/gerencia/originadoras/{ORIGINADORA}/gerar-competencia',
        json={'competencia': '2026-08'},
    )

    assert resposta.status_code == 200
    assert resposta.json()['resumo']['desativada'] is False
    assert len(resposta.json()['resumo']['gerados']) == 1


def test_gerar_periodo_de_originadora(cliente, banco):
    resposta = cliente.post(
        f'/api/conciliacao/gerencia/originadoras/{ORIGINADORA}/gerar-periodo',
        json={'competencia_inicio': '2026-08', 'competencia_fim': '2026-09'},
    )

    assert resposta.status_code == 200
    assert len(resposta.json()['resumo']['por_competencia']) == 2
