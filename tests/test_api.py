"""Testes de integração da API sobre bancos SQLite temporários."""

# --- stdlib ---
import sqlite3
import sys
from pathlib import Path

# --- terceiros ---
import pytest
from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

# --- locais ---
from api import app as modulo_app  # noqa: E402
from api.arquivos import (  # noqa: E402
    caminho_registro,
    gravar_arquivo,
    montar_documento,
)
from api.config import Configuracao, carregar_configuracao  # noqa: E402
from api.repositories import analitico as repo_analitico  # noqa: E402
from scripts.migrar_para_arquivos import migrar  # noqa: E402

SQL_CONCILIACAO = """
CREATE TABLE tabela_concilicacao_convenio (
  id INTEGER PRIMARY KEY,
  originador TEXT,
  mes_referencia_conciliacao TEXT,
  numero_convenio TEXT,
  nome_convenio TEXT,
  cnpj_convenio TEXT,
  data_vencimento TEXT,
  data_sla_concilicacao TEXT,
  qtd_dias_sla_pagamento TEXT,
  data_corte TEXT,
  valor_remessa REAL,
  valor_retorno REAL,
  valor_repasse REAL,
  status_conciliacao TEXT,
  motivo_falta_conciliacao TEXT,
  porcentagem_inadimplencia REAL
);

CREATE TABLE tabela_contato (
  id INTEGER PRIMARY KEY,
  originador TEXT,
  numero_convenio TEXT,
  area TEXT,
  status TEXT,
  nome TEXT,
  email TEXT,
  telefone TEXT,
  observacao TEXT
);

CREATE TABLE tabela_conta_conv (
  id INTEGER PRIMARY KEY,
  originador TEXT,
  numero_convenio TEXT,
  banco TEXT,
  agencia TEXT,
  conta TEXT,
  chave_pix TEXT,
  cnpj TEXT,
  status_conta TEXT
);

-- tabela_particularidade fica de fora de propósito: o Analítico precisa
-- continuar carregando com a aba vazia quando o banco não a tem.

INSERT INTO tabela_concilicacao_convenio VALUES
  (1, 'FCT', '2025-07', '126225', 'Convenio FCT 01', '45.350.328/3286-23',
   '2025-07-19', '2025-07-21', '5', '2025-07-24',
   98734.69, 97499.43, 96862.49, 'OK', '', 0.73),
  (2, 'FCT', '2025-07', '126225', 'Convenio FCT 01', '45.350.328/3286-23',
   '2025-07-28', '2025-07-30', '2', '2025-07-31',
   50.0, 45.0, 20.0, 'DIVERGENTE', 'Erro de processamento', 8.0),
  (3, 'FCT', '2025-08', '126225', 'Convenio FCT 01', '45.350.328/3286-23',
   '2025-08-19', '2025-08-21', '1', '2025-08-24',
   100.0, 90.0, 40.0, 'DIVERGENTE', 'Erro', 3.0),
  (4, 'BANCO_Y', '2025-07', '542417', 'Convenio BANCO_Y 02', '14.130.195/4582-39',
   '2025-07-13', '2025-07-15', '0', NULL,
   500.0, 480.0, 480.0, 'OK', '', 0.0);

INSERT INTO tabela_contato VALUES
  (1, 'FCT', '126225', 'Financeiro', 'ATIVO', 'Paulo Souza',
   'paulo@fct.mock', '(11) 91641-5059', ''),
  (2, 'FCT', '126225', 'Financeiro', 'INATIVO', 'Antigo',
   'antigo@fct.mock', '(11) 0000-0000', '');

INSERT INTO tabela_conta_conv VALUES
  (1, 'FCT', '126225', 'Banco do Brasil', '3057-1', '12345-6',
   'pix@fct.mock', '45.350.328/3286-23', 'ATIVA');
"""

SQL_COBRANCA = """
PRAGMA foreign_keys = ON;

CREATE TABLE tabela_cobranca_caso (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    originador TEXT,
    numero_convenio TEXT,
    nome_convenio TEXT,
    cnpj_convenio TEXT,
    mes_referencia TEXT,
    valor_em_aberto REAL DEFAULT 0,
    status_cobranca TEXT DEFAULT 'pendente',
    motivo TEXT,
    prioridade TEXT DEFAULT 'media',
    responsavel TEXT,
    observacao TEXT,
    criado_em TEXT DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TEXT,
    UNIQUE (originador, numero_convenio, mes_referencia)
);

CREATE TABLE tabela_cobranca_tentativa (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    id_caso INTEGER NOT NULL,
    data_hora TEXT,
    canal TEXT,
    resultado TEXT,
    contato_nome TEXT,
    observacao TEXT,
    ator TEXT,
    criado_em TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (id_caso) REFERENCES tabela_cobranca_caso (id) ON DELETE CASCADE
);

CREATE TABLE tabela_cobranca_agendamento (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    id_caso INTEGER NOT NULL,
    data_hora TEXT,
    assunto TEXT,
    observacao TEXT,
    concluido INTEGER DEFAULT 0,
    ator TEXT,
    criado_em TEXT DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TEXT,
    FOREIGN KEY (id_caso) REFERENCES tabela_cobranca_caso (id) ON DELETE CASCADE
);
"""


def _criar_banco(caminho: Path, script: str) -> Path:
    conexao = sqlite3.connect(caminho)
    conexao.executescript(script)
    conexao.commit()
    conexao.close()
    return caminho


@pytest.fixture()
def cliente(tmp_path, monkeypatch):
    """Cliente de teste com fontes isoladas por teste.

    O Sintético e o Analítico leem do banco de arquivos, gerado aqui a
    partir do mesmo SQLite — assim a migração entra no caminho testado.
    """
    banco_conciliacao = _criar_banco(
        tmp_path / 'conciliacao.db', SQL_CONCILIACAO
    )
    pasta_banco = tmp_path / 'DADOS'
    migrar(banco_conciliacao, pasta_banco)

    config = Configuracao(
        banco_conciliacao=banco_conciliacao,
        banco_cobranca=_criar_banco(tmp_path / 'cobranca.db', SQL_COBRANCA),
        pasta_fila_entrada=None,
        host='127.0.0.1',
        porta=8000,
        pasta_banco=pasta_banco,
    )
    monkeypatch.setattr(modulo_app, 'obter_configuracao', lambda: config)
    return TestClient(modulo_app.app)


CASO_BASE = {
    'empresa': 'Convenio FCT 01',
    'cnpj': '45.350.328/3286-23',
    'contato': 'Paulo Souza',
    'telefone': '(11) 91641-5059',
    'email': 'paulo@fct.mock',
    'competencia': '08/2025',
    'valorDivergente': 50.0,
    'status': 'pendente',
    'origem': 'conciliacao',
    'originador': 'FCT',
    'numeroConvenio': '126225',
}


# =========================================================
# Leitura
# =========================================================
def test_status_reporta_as_duas_bases(cliente):
    corpo = cliente.get('/api/status').json()

    assert corpo['conciliacao']['disponivel'] is True
    assert corpo['conciliacao']['registros'] == 4
    assert corpo['cobranca']['disponivel'] is True
    assert corpo['cobranca']['casos'] == 0


def test_extrato_foi_removido(cliente):
    assert cliente.get('/api/extrato').status_code == 404


def test_retorno_traz_valor_descontado(cliente):
    linhas = cliente.get('/api/retorno').json()['rows']
    assert len(linhas) == 4

    # A query ordena por competência e nome do convênio.
    assert [l['convenio'] for l in linhas] == [
        'Convenio BANCO_Y 02',
        'Convenio FCT 01',
        'Convenio FCT 01',
        'Convenio FCT 01',
    ]

    fct_julho = next(
        l
        for l in linhas
        if l['convenio'] == 'Convenio FCT 01' and l['competencia'] == '07/2025'
    )
    assert fct_julho['valor'] == pytest.approx(97499.43)
    assert fct_julho['numeroConvenio'] == '126225'


def test_ini_com_bom_ainda_e_lido(tmp_path):
    """.ini salvo pelo Bloco de Notas vem com BOM e não pode ser ignorado."""
    caminho = tmp_path / 'com_bom.ini'
    caminho.write_text(
        '[FRONT]\nbanco_conciliacao = doc/x.db\nporta = 9123\n',
        encoding='utf-8-sig',
    )

    config = carregar_configuracao(caminho)

    assert config.porta == 9123
    assert config.banco_conciliacao.name == 'x.db'


def test_filtros_listam_competencias_da_mais_nova_para_a_mais_antiga(cliente):
    corpo = cliente.get('/api/analitico/filtros').json()

    # Competência sai do nome das pastas; originadora, dos documentos.
    assert corpo['competencias'] == ['08/2025', '07/2025']
    assert corpo['originadores'] == ['BANCO_Y', 'FCT']


def test_filtros_usam_o_cadastro_quando_ele_existe(tmp_path):
    """Com cadastro, o filtro não varre a conciliação inteira."""
    pasta_banco = tmp_path / 'DADOS'
    gravar_arquivo(
        caminho_registro(
            pasta_banco, 'gestao_convenios_originador', 'FCT', '126225'
        ),
        montar_documento(
            'gestao_convenios_originador',
            'FCT',
            '126225',
            [{'id': 1, 'originador': 'FCT', 'numero_convenio': '126225'}],
        ),
    )
    (pasta_banco / 'tabela_concilicacao_convenio' / '2025-07').mkdir(
        parents=True
    )

    filtros = repo_analitico.listar_filtros(pasta_banco)

    assert filtros['originadores'] == ['FCT']
    assert filtros['competencias'] == ['07/2025']


def test_pasta_de_banco_inexistente_responde_503(tmp_path, monkeypatch):
    config = Configuracao(
        banco_conciliacao=tmp_path / 'x.db',
        banco_cobranca=tmp_path / 'y.db',
        pasta_fila_entrada=None,
        host='127.0.0.1',
        porta=8000,
        pasta_banco=tmp_path / 'nao_existe',
    )
    monkeypatch.setattr(modulo_app, 'obter_configuracao', lambda: config)

    resposta = TestClient(modulo_app.app).get('/api/analitico/filtros')

    assert resposta.status_code == 503


def test_sintetico_resume_os_vencimentarios_da_competencia(cliente):
    linhas = cliente.get(
        '/api/analitico/sintetico',
        params={'competencia': '07/2025', 'originador': 'FCT'},
    ).json()['linhas']

    assert len(linhas) == 1
    linha = linhas[0]

    assert linha['convenio']['numero_convenio'] == '126225'
    # Um vencimentário OK e outro DIVERGENTE -> parcial no consolidado.
    assert linha['resumo']['status_conciliacao'] == 'CONCILIADO (PARCIAL)'
    assert linha['resumo']['qtd_vencimentarios'] == 2
    assert linha['resumo']['dias_venc'] == '19 / 28'
    assert linha['resumo']['motivos'] == ['Erro de processamento']
    assert linha['resumo']['porcentagem_inadimplencia'] == pytest.approx(8.0)


def test_sintetico_nao_mistura_originadoras(cliente):
    linhas = cliente.get(
        '/api/analitico/sintetico',
        params={'competencia': '07/2025', 'originador': 'BANCO_Y'},
    ).json()['linhas']

    assert [l['convenio']['numero_convenio'] for l in linhas] == ['542417']


def test_convenio_traz_vencimentarios_de_todas_as_competencias(cliente):
    convenio = cliente.get(
        '/api/analitico/convenio',
        params={'originador': 'FCT', 'numero_convenio': '126225'},
    ).json()['convenio']

    # O dashboard do Analítico troca de competência sem voltar ao Sintético.
    assert [
        (v['competencia'], v['dia_vencimento'])
        for v in convenio['vencimentarios']
    ] == [('08/2025', '19'), ('07/2025', '19'), ('07/2025', '28')]

    primeiro = convenio['vencimentarios'][1]
    assert primeiro['conciliacao']['data_vencimento'] == '19/07/2025'
    assert primeiro['conciliacao']['data_baixa'] == '21/07/2025'
    assert primeiro['conciliacao']['status_conciliacao'] == 'CONCILIADO'
    # 'Conciliado' é derivado do status no front, não campo do contrato.
    assert 'conciliado' not in primeiro


def test_convenio_traz_abas_compartilhadas(cliente):
    convenio = cliente.get(
        '/api/analitico/convenio',
        params={'originador': 'FCT', 'numero_convenio': '126225'},
    ).json()['convenio']

    assert [c['nome'] for c in convenio['contatos']] == [
        'Paulo Souza',
        'Antigo',
    ]
    assert convenio['contas'][0]['banco'] == 'Banco do Brasil'
    # Banco sem tabela_particularidade: a aba vem vazia, a tela carrega.
    assert convenio['particularidades'] == []
    # Secretaria só existe a partir da etapa 2 (migração do schema).
    assert convenio['secretarias'] == []


def test_convenio_inexistente_responde_404(cliente):
    resposta = cliente.get(
        '/api/analitico/convenio',
        params={'originador': 'FCT', 'numero_convenio': '000000'},
    )

    assert resposta.status_code == 404


def test_contatos_ignora_inativos(cliente):
    contatos = cliente.get('/api/contatos').json()['contatos']
    assert contatos['126225']['contato'] == 'Paulo Souza'


# =========================================================
# Cobrança — escrita
# =========================================================
def test_criar_caso_persiste_no_banco(cliente):
    resposta = cliente.post('/api/cobranca/casos', json=CASO_BASE)
    assert resposta.status_code == 201

    caso = resposta.json()['casos'][0]
    assert caso['empresa'] == 'Convenio FCT 01'
    assert caso['contato'] == 'Paulo Souza'
    assert caso['competencia'] == '08/2025'
    assert caso['status'] == 'pendente'

    assert len(cliente.get('/api/cobranca/casos').json()['casos']) == 1


def test_lote_deduplica_por_convenio_e_competencia(cliente):
    payload = {'casos': [CASO_BASE, CASO_BASE]}
    primeira = cliente.post('/api/cobranca/casos/lote', json=payload)
    assert len(primeira.json()['casos']) == 1

    segunda = cliente.post('/api/cobranca/casos/lote', json=payload)
    assert segunda.json()['casos'] == []
    assert len(cliente.get('/api/cobranca/casos').json()['casos']) == 1


def test_registros_manuais_sem_convenio_nao_colidem(cliente):
    manual = {'empresa': 'Empresa Avulsa', 'competencia': '08/2025'}
    cliente.post('/api/cobranca/casos', json=manual)
    cliente.post('/api/cobranca/casos', json=manual)

    assert len(cliente.get('/api/cobranca/casos').json()['casos']) == 2


def test_tentativa_regularizou_resolve_o_caso(cliente):
    id_caso = cliente.post('/api/cobranca/casos', json=CASO_BASE).json()[
        'casos'
    ][0]['id']

    resposta = cliente.post(
        f'/api/cobranca/casos/{id_caso}/tentativas',
        json={
            'dataHora': '2026-07-21T10:00:00',
            'canal': 'telefone',
            'resultado': 'regularizou',
            'observacao': 'Vai pagar hoje.',
        },
    )

    caso = resposta.json()['caso']
    assert caso['status'] == 'resolvido'
    assert len(caso['tentativas']) == 1


def test_primeira_tentativa_move_pendente_para_negociacao(cliente):
    id_caso = cliente.post('/api/cobranca/casos', json=CASO_BASE).json()[
        'casos'
    ][0]['id']

    caso = cliente.post(
        f'/api/cobranca/casos/{id_caso}/tentativas',
        json={
            'dataHora': '2026-07-21T10:00:00',
            'canal': 'whatsapp',
            'resultado': 'sem_resposta',
        },
    ).json()['caso']

    assert caso['status'] == 'em_negociacao'


def test_agendar_e_concluir_devolve_para_negociacao(cliente):
    id_caso = cliente.post('/api/cobranca/casos', json=CASO_BASE).json()[
        'casos'
    ][0]['id']

    caso = cliente.post(
        f'/api/cobranca/casos/{id_caso}/agendamentos',
        json={'dataHora': '2026-07-25T14:00:00', 'assunto': 'Negociar'},
    ).json()['caso']
    assert caso['status'] == 'agendado'

    id_agenda = caso['agendamentos'][0]['id']
    caso = cliente.patch(
        f'/api/cobranca/casos/{id_caso}/agendamentos/{id_agenda}/concluir'
    ).json()['caso']

    assert caso['agendamentos'][0]['concluido'] is True
    assert caso['status'] == 'em_negociacao'


def test_alterar_status_e_excluir_caso(cliente):
    id_caso = cliente.post('/api/cobranca/casos', json=CASO_BASE).json()[
        'casos'
    ][0]['id']

    caso = cliente.patch(
        f'/api/cobranca/casos/{id_caso}/status',
        json={'status': 'sem_sucesso'},
    ).json()['caso']
    assert caso['status'] == 'sem_sucesso'

    assert cliente.delete(f'/api/cobranca/casos/{id_caso}').status_code == 204
    assert cliente.get('/api/cobranca/casos').json()['casos'] == []


def test_operacao_em_caso_inexistente_retorna_404(cliente):
    resposta = cliente.patch(
        '/api/cobranca/casos/999/status', json={'status': 'resolvido'}
    )
    assert resposta.status_code == 404


def test_status_invalido_e_rejeitado(cliente):
    resposta = cliente.patch(
        '/api/cobranca/casos/1/status', json={'status': 'inventado'}
    )
    assert resposta.status_code == 422
