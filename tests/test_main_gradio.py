"""Testes do fluxo Gradio (main.py): abas novas e registro de cobrança.

O ``main.py`` lê o .ini no import e aponta para o share COFCT. Aqui o
apontamos, via ``COFC_CONFIG``, para uma cópia local do banco e uma fila
temporária — assim o módulo é exercitável sem depender da rede.
"""

# --- stdlib ---
import importlib
import json
import shutil
import sqlite3
import sys
from pathlib import Path

# --- terceiros ---
import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

BANCO_MOCK = RAIZ / 'doc' / 'convenios_mock_layout.db'

SQL_COBRANCA = """
CREATE TABLE tabela_cobranca_caso (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    originador TEXT, numero_convenio TEXT, nome_convenio TEXT,
    cnpj_convenio TEXT, mes_referencia TEXT, valor_em_aberto REAL DEFAULT 0,
    status_cobranca TEXT DEFAULT 'pendente', motivo TEXT,
    prioridade TEXT DEFAULT 'media', responsavel TEXT, observacao TEXT,
    criado_em TEXT, atualizado_em TEXT,
    UNIQUE (originador, numero_convenio, mes_referencia)
);
CREATE TABLE tabela_cobranca_tentativa (
    id INTEGER PRIMARY KEY AUTOINCREMENT, id_caso INTEGER NOT NULL,
    data_hora TEXT, canal TEXT, resultado TEXT, contato_nome TEXT,
    observacao TEXT, ator TEXT, criado_em TEXT,
    FOREIGN KEY (id_caso) REFERENCES tabela_cobranca_caso (id) ON DELETE CASCADE
);
CREATE TABLE tabela_financeiro_repasse (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    originador TEXT, numero_convenio TEXT, nome_convenio TEXT,
    cnpj_convenio TEXT, mes_referencia TEXT, data_prevista TEXT,
    data_efetiva TEXT, valor_previsto REAL DEFAULT 0,
    valor_recebido REAL DEFAULT 0, valor_repassado REAL DEFAULT 0,
    forma_pagamento TEXT, status_financeiro TEXT DEFAULT 'previsto',
    observacao TEXT, criado_em TEXT, atualizado_em TEXT,
    UNIQUE (originador, numero_convenio, mes_referencia)
);
INSERT INTO tabela_financeiro_repasse
    (originador, numero_convenio, nome_convenio, mes_referencia,
     valor_previsto, valor_recebido, valor_repassado, status_financeiro)
VALUES ('FCT', '126225', 'Convenio FCT 01', '2025-07',
        1000.0, 900.0, 880.0, 'recebido');
"""


# O doc/convenios_mock_layout.db está defasado: o main.py consulta colunas
# que só existem no COFCT real. Completamos a cópia de teste para exercitar
# o fluxo sem depender do share de rede.
COLUNAS_FALTANTES_MOCK = (
    ('data_baixa', 'TEXT'),
    ('qtd_dias_inadimplencia', 'TEXT'),
    ('valor_pendente', 'REAL'),
    ('inadimplencia_pf', 'REAL'),
    ('inadimplencia_pj', 'REAL'),
)


def _completar_schema_cofct(caminho: Path) -> None:
    """Adiciona ao mock as colunas que o main.py espera do COFCT."""
    conexao = sqlite3.connect(caminho)
    existentes = {
        linha[1]
        for linha in conexao.execute(
            'PRAGMA table_info(tabela_concilicacao_convenio)'
        )
    }
    for nome, tipo in COLUNAS_FALTANTES_MOCK:
        if nome not in existentes:
            conexao.execute(
                'ALTER TABLE tabela_concilicacao_convenio '
                f'ADD COLUMN {nome} {tipo}'
            )
    conexao.execute(
        'UPDATE tabela_concilicacao_convenio '
        'SET data_baixa = data_sla_concilicacao, '
        '    qtd_dias_inadimplencia = qtd_dias_sla_pagamento'
    )
    conexao.commit()
    conexao.close()


@pytest.fixture()
def main_mod(tmp_path, monkeypatch):
    """Importa main.py apontando para bancos e fila locais."""
    pasta_db = tmp_path / 'BD'
    pasta_db.mkdir()
    shutil.copy(BANCO_MOCK, pasta_db / 'bd_cofct.db')
    _completar_schema_cofct(pasta_db / 'bd_cofct.db')

    banco_cobranca = tmp_path / 'bd_cobranca_financeiro.db'
    conexao = sqlite3.connect(banco_cobranca)
    conexao.executescript(SQL_COBRANCA)
    conexao.commit()
    conexao.close()

    fila = tmp_path / 'fila'
    ini = tmp_path / 'config_teste.ini'
    ini.write_text(
        '[FRONT]\n'
        f'banco_conciliacao = {pasta_db / "bd_cofct.db"}\n'
        f'banco_cobranca = {banco_cobranca}\n'
        'host = 127.0.0.1\n'
        'porta = 8000\n'
        '\n'
        '[DIRETORIOS]\n'
        f'pasta_db = {pasta_db}\n'
        f'pasta_fila_entrada = {fila}\n',
        encoding='utf-8',
    )

    monkeypatch.setenv('COFC_CONFIG', str(ini))

    import api.config

    api.config.obter_configuracao.cache_clear()

    import main

    modulo = importlib.reload(main)
    modulo.FILA_TESTE = fila
    return modulo


def _comandos_na_fila(fila: Path) -> list[dict]:
    return [
        json.loads(arquivo.read_text(encoding='utf-8'))
        for arquivo in sorted(fila.glob('*.txt'))
    ]


# =========================================================
# Leitura das abas novas
# =========================================================
def test_financeiro_lista_repasses_do_convenio(main_mod):
    linhas = main_mod.listar_financeiro('126225', '2025-07')

    assert len(linhas) == 1
    assert linhas[0]['status_financeiro'] == 'recebido'
    assert linhas[0]['valor_repassado'] == pytest.approx(880.0)


def test_contatos_ativos_alimentam_o_registro_de_cobranca(main_mod):
    contatos = main_mod.listar_contatos_ativos('126225')

    assert contatos, 'convênio 126225 deve ter contato ATIVO no mock'
    # Só contatos ATIVOS entram na lista (o mock tem INATIVOS no convênio).
    assert 'Carlos Costa' not in ' | '.join(contatos)
    assert (
        main_mod.nome_do_contato('Ana Paula — Financeiro — (11) 9')
        == 'Ana Paula'
    )


def test_cobranca_comeca_vazia(main_mod):
    assert main_mod.listar_cobranca_casos('126225', '2025-07') == []
    assert main_mod.listar_cobranca_historico('126225') == []


# =========================================================
# Escrita via fila de comandos
# =========================================================
def test_registro_de_cobranca_enfileira_caso_status_e_tentativa(main_mod):
    contato = main_mod.listar_contatos_ativos('126225')[0]

    msg, casos, historico = main_mod.salvar_cobranca(
        numero_convenio='126225',
        mes_ref='2025-07',
        contato_rotulo=contato,
        canal='whatsapp',
        resultado='contato_efetivo',
        valor_em_aberto='1.234,56',
        status_cobranca='em_negociacao',
        prioridade='alta',
        observacao='Prometeu pagar dia 30.',
        data_hora='2026-07-21 10:00:00',
    )

    assert 'Cobrança registrada' in msg

    comandos = _comandos_na_fila(main_mod.FILA_TESTE)
    metodos = [c['metodo'] for c in comandos]
    assert metodos == [
        'INSERT_COBRANCA_CASO',
        'UPDATE_COBRANCA_CASO',
        'INSERT_COBRANCA_TENTATIVA',
    ]

    # Todos precisam dizer ao writer que o alvo é o banco de cobrança.
    assert {c['banco_destino'] for c in comandos} == {'cobranca_financeiro'}

    caso = comandos[0]
    assert 'INSERT OR IGNORE INTO tabela_cobranca_caso' in caso['sql']
    assert caso['params'][1] == '126225'
    assert caso['params'][5] == pytest.approx(1234.56)

    tentativa = comandos[2]
    # O id_caso é resolvido por subquery no momento em que o writer aplica.
    assert 'SELECT id, ?, ?, ?, ?, ?, ?, ?' in tentativa['sql']
    assert 'whatsapp' in tentativa['params']
    assert 'contato_efetivo' in tentativa['params']


def test_cobranca_sem_contato_nao_enfileira_nada(main_mod):
    msg, _, _ = main_mod.salvar_cobranca(
        '126225',
        '2025-07',
        '',
        'telefone',
        'sem_resposta',
        '0',
        'pendente',
        'media',
        '',
        '',
    )

    assert 'Selecione o contato' in msg
    assert _comandos_na_fila(main_mod.FILA_TESTE) == []


def test_salvar_financeiro_enfileira_no_banco_de_cobranca(main_mod):
    msg, linhas = main_mod.salvar_financeiro(
        numero_convenio='126225',
        mes_ref='2025-07',
        financeiro_id=None,
        mes_referencia='2025-08',
        data_prevista='2025-08-05',
        data_efetiva='',
        valor_previsto='2.000,00',
        valor_recebido='0',
        valor_repassado='0',
        forma_pagamento='ted',
        status_financeiro='previsto',
        observacao='Previsto para agosto.',
    )

    assert 'INSERT_FINANCEIRO_REPASSE' in msg

    (comando,) = _comandos_na_fila(main_mod.FILA_TESTE)
    assert comando['banco_destino'] == 'cobranca_financeiro'
    assert comando['params'][7] == pytest.approx(2000.0)
    assert 'ted' in comando['params']

    # A leitura ainda não reflete: o writer aplica depois.
    assert len(linhas) == 1


# =========================================================
# Sintético: mês e originadora obrigatórios
# =========================================================
def test_build_app_monta_sem_erro(main_mod):
    app = main_mod.build_app()
    assert app is not None
