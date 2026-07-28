"""Testes do contrato HTTP dos responsáveis pela conciliação."""

# --- stdlib ---
import sys
from pathlib import Path

# --- terceiros ---
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# --- locais ---
from api import app as modulo_app  # noqa: E402
from api.config import Configuracao  # noqa: E402

ORIGINADORA = 'Alvo Card'
NUMERO = '00001ALV'


@pytest.fixture()
def cliente(tmp_path, monkeypatch):
    config = Configuracao(
        banco_conciliacao=tmp_path / 'x.db',
        banco_cobranca=tmp_path / 'y.db',
        pasta_fila_entrada=None,
        host='127.0.0.1',
        porta=8000,
        pasta_banco=tmp_path,
        pasta_fila_geracao=tmp_path / 'fila',
    )
    monkeypatch.setattr(modulo_app, 'obter_configuracao', lambda: config)
    return TestClient(modulo_app.app)


def _rota_venc(sufixo=''):
    return f'/api/responsaveis/{ORIGINADORA}/{NUMERO}{sufixo}'


def test_criar_e_listar_colaborador(cliente):
    criar = cliente.post(
        '/api/responsaveis/colaboradores', json={'nome': 'Ana'}
    )
    assert criar.status_code == 201
    assert criar.json()['colaborador']['status'] == 'ATIVO'

    lista = cliente.get('/api/responsaveis/colaboradores')
    assert [c['nome'] for c in lista.json()['colaboradores']] == ['Ana']


def test_colaborador_duplicado_409(cliente):
    cliente.post('/api/responsaveis/colaboradores', json={'nome': 'Ana'})
    dup = cliente.post('/api/responsaveis/colaboradores', json={'nome': 'Ana'})
    assert dup.status_code == 409


def test_definir_titular_e_efetivo(cliente):
    cliente.post('/api/responsaveis/colaboradores', json={'nome': 'Ana'})
    resp = cliente.put(_rota_venc('/titular'), json={'colaborador': 'Ana'})

    assert resp.status_code == 200
    assert resp.json()['responsavel']['efetivo'] == 'Ana'


def test_titular_inexistente_404(cliente):
    resp = cliente.put(_rota_venc('/titular'), json={'colaborador': 'Zed'})
    assert resp.status_code == 404


def test_substituicao_e_encerramento(cliente):
    cliente.post('/api/responsaveis/colaboradores', json={'nome': 'Ana'})
    cliente.post('/api/responsaveis/colaboradores', json={'nome': 'Beto'})
    cliente.put(_rota_venc('/titular'), json={'colaborador': 'Ana'})

    sub = cliente.post(
        _rota_venc('/substituicao'),
        json={'substituto': 'Beto', 'substituicao_fim': '2099-12-31'},
    )
    assert sub.status_code == 200
    assert sub.json()['responsavel']['efetivo'] == 'Beto'

    fim = cliente.delete(_rota_venc('/substituicao'))
    assert fim.status_code == 200
    assert fim.json()['responsavel']['efetivo'] == 'Ana'


def test_desligar_deixa_nao_cadastrado(cliente):
    cliente.post('/api/responsaveis/colaboradores', json={'nome': 'Ana'})
    cliente.put(_rota_venc('/titular'), json={'colaborador': 'Ana'})
    cliente.put(
        '/api/responsaveis/colaboradores/Ana', json={'status': 'DESLIGADO'}
    )

    resp = cliente.get(_rota_venc())
    assert resp.json()['responsavel']['efetivo'] == 'Usuário Não Cadastrado'
