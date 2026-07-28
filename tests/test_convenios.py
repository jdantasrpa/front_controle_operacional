"""Testes da gestão de convênios, originadoras e custos."""

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
from api.domain_convenios import (  # noqa: E402
    CHAVE_VINCULO,
    BaseApuracao,
    abrir_nova_vigencia,
    aplicar_alteracao,
    calcular_custo,
    cnpj_formatado,
    competencia_valida,
    custo_vigente,
    deslocar_competencia,
    esta_vigente,
    normalizar_cnpj,
    validar_custo,
    validar_vinculo,
    violacoes_de_chave,
)
from api.repositories import convenios as repo  # noqa: E402

CNPJ = '00.394.429/0082-76'
ORIGINADORA = 'Alvo Card'
NUMERO = '00001ALV'


@pytest.fixture()
def banco(tmp_path):
    """Pasta de banco vazia, pronta para gravação."""
    (tmp_path / 'cadastro_convenio').mkdir()
    return tmp_path


@pytest.fixture()
def vinculo_gravado(banco):
    """Convênio já com uma originadora ligada — base dos testes de custo."""
    repo.criar_convenio(
        banco, {'cnpj_convenio': CNPJ, 'nome_convenio': 'AERONÁUTICA'}
    )
    repo.criar_vinculo(
        banco,
        CNPJ,
        {
            'originador': ORIGINADORA,
            'numero_convenio': NUMERO,
            'nome_convenio': 'AERONÁUTICA',
            'averbadora': 'Zetra',
            'competencia_inicio': '2025-01',
            'competencia_fim': '',
            'status': 'ATIVO',
        },
    )
    return banco


# =========================================================
# Identidade do convênio
# =========================================================
def test_cnpj_e_a_chave_entre_originadoras():
    """O número muda por originadora; o CNPJ é o que identifica o órgão."""
    assert normalizar_cnpj(CNPJ) == normalizar_cnpj('00394429008276')


def test_cnpj_formatado_devolve_original_quando_incompleto():
    assert cnpj_formatado('123') == '123'
    assert cnpj_formatado('00394429008276') == CNPJ


# =========================================================
# Vigência por competência
# =========================================================
@pytest.mark.parametrize(
    'competencia, esperado',
    [('2026-07', True), ('2026-13', False), ('07/2026', False), ('', False)],
)
def test_competencia_valida(competencia, esperado):
    assert competencia_valida(competencia) is esperado


@pytest.mark.parametrize(
    'origem, meses, esperado',
    [
        ('2026-01', -1, '2025-12'),
        ('2025-12', 1, '2026-01'),
        ('2026-07', 0, '2026-07'),
        ('lixo', -1, ''),
    ],
)
def test_deslocar_competencia(origem, meses, esperado):
    assert deslocar_competencia(origem, meses) == esperado


@pytest.mark.parametrize(
    'competencia, esperado',
    [
        ('2024-12', False),
        ('2025-01', True),
        ('2025-06', True),
        ('2025-07', False),
    ],
)
def test_esta_vigente_respeita_a_janela(competencia, esperado):
    vinculo = {'competencia_inicio': '2025-01', 'competencia_fim': '2025-06'}

    assert esta_vigente(vinculo, competencia) is esperado


def test_vinculo_antigo_sem_vigencia_continua_valendo():
    """Registro gravado antes deste módulo não pode sumir da conciliação."""
    assert esta_vigente({}, '2026-07') is True


def test_status_inativo_vence_a_janela():
    vinculo = {'status': 'INATIVO', 'competencia_inicio': '2025-01'}

    assert esta_vigente(vinculo, '2025-05') is False


# =========================================================
# Cálculo do custo — os quatro métodos
# =========================================================
def test_custo_percentual_sobre_a_base_escolhida():
    custo = {
        'metodo': 'PERCENTUAL',
        'base_calculo': 'VALOR_REPASSE',
        'aliquota_percentual': 2.5,
    }
    apuracao = BaseApuracao(valor_retorno=999.0, valor_repasse=1000.0)

    assert calcular_custo(custo, apuracao) == 25.0


def test_custo_fixo_ignora_o_volume():
    custo = {'metodo': 'FIXO_MENSAL', 'valor_fixo': 1500.0}

    assert (
        calcular_custo(custo, BaseApuracao(quantidade_contratos=900)) == 1500.0
    )


def test_custo_por_contrato_multiplica_a_quantidade():
    custo = {'metodo': 'POR_CONTRATO', 'valor_unitario': 3.5}

    assert calcular_custo(custo, BaseApuracao(quantidade_contratos=10)) == 35.0


def test_custo_por_faixa_escolhe_o_degrau_pela_quantidade():
    custo = {
        'metodo': 'FAIXA',
        'criterio_faixa': 'QUANTIDADE',
        'faixas': [
            {'ate': 100, 'metodo': 'POR_CONTRATO', 'valor_unitario': 5.0},
            {'ate': 0, 'metodo': 'POR_CONTRATO', 'valor_unitario': 2.0},
        ],
    }

    dentro = calcular_custo(custo, BaseApuracao(quantidade_contratos=50))
    acima = calcular_custo(custo, BaseApuracao(quantidade_contratos=500))

    assert (dentro, acima) == (250.0, 1000.0)


def test_custo_ausente_nao_quebra_o_calculo():
    assert calcular_custo(None, BaseApuracao(valor_retorno=1000)) == 0.0


# =========================================================
# Validação
# =========================================================
def test_percentual_exige_aliquota_e_base():
    erros = validar_custo(
        {
            'metodo': 'PERCENTUAL',
            'competencia_inicio': '2026-01',
            'aliquota_percentual': 0,
            'base_calculo': 'INVENTADA',
        }
    )

    assert len(erros) == 2


def test_faixa_sem_degrau_e_recusada():
    erros = validar_custo(
        {
            'metodo': 'FAIXA',
            'competencia_inicio': '2026-01',
            'criterio_faixa': 'QUANTIDADE',
            'faixas': [],
        }
    )

    assert erros == ['Cadastre ao menos uma faixa.']


def test_competencia_final_anterior_a_inicial_e_recusada():
    erros = validar_custo(
        {
            'metodo': 'FIXO_MENSAL',
            'valor_fixo': 10,
            'competencia_inicio': '2026-05',
            'competencia_fim': '2026-01',
        }
    )

    assert 'Competência final não pode ser anterior à inicial.' in erros


def test_vinculo_exige_originadora_e_numero():
    erros = validar_vinculo({'competencia_inicio': '2026-01'})

    assert len(erros) == 2


# =========================================================
# Histórico de custo
# =========================================================
def test_novo_custo_encerra_o_anterior_sem_apagar():
    antigo = {
        'id': '1',
        'competencia_inicio': '2025-01',
        'competencia_fim': '',
    }

    historico = abrir_nova_vigencia(
        [antigo],
        {'id': '2', 'competencia_inicio': '2026-01', 'competencia_fim': ''},
    )

    assert len(historico) == 2
    assert historico[0]['competencia_fim'] == '2025-12'
    assert historico[1]['competencia_fim'] == ''


def test_abrir_vigencia_nao_muta_o_historico_recebido():
    antigo = {
        'id': '1',
        'competencia_inicio': '2025-01',
        'competencia_fim': '',
    }

    abrir_nova_vigencia([antigo], {'id': '2', 'competencia_inicio': '2026-01'})

    assert antigo['competencia_fim'] == ''


def test_competencia_passada_recupera_o_custo_da_epoca():
    historico = [
        {
            'id': '1',
            'competencia_inicio': '2025-01',
            'competencia_fim': '2025-12',
            'valor_fixo': 100,
        },
        {
            'id': '2',
            'competencia_inicio': '2026-01',
            'competencia_fim': '',
            'valor_fixo': 150,
        },
    ]

    assert custo_vigente(historico, '2025-08')['valor_fixo'] == 100
    assert custo_vigente(historico, '2026-08')['valor_fixo'] == 150
    assert custo_vigente(historico, '2024-08') is None


def test_abrir_vigencia_recusa_competencia_invalida():
    with pytest.raises(ValueError):
        abrir_nova_vigencia([], {'competencia_inicio': '01/2026'})


# =========================================================
# Repositório — visão convênio → originadoras
# =========================================================
def test_convenio_agrupa_originadoras_pelo_cnpj(vinculo_gravado):
    """Duas originadoras, números diferentes, o mesmo convênio."""
    repo.criar_vinculo(
        vinculo_gravado,
        CNPJ,
        {
            'originador': 'Hatchbank',
            'numero_convenio': '00061HTC',
            'nome_convenio': 'AERONÁUTICA',
            'competencia_inicio': '2026-01',
        },
    )

    convenio = repo.obter_convenio(vinculo_gravado, CNPJ, '2026-03')

    assert convenio['total_originadoras'] == 2
    assert [o['originador'] for o in convenio['originadoras']] == [
        'Alvo Card',
        'Hatchbank',
    ]


def test_originadora_fora_da_vigencia_nao_conta_como_vigente(
    vinculo_gravado,
):
    repo.criar_vinculo(
        vinculo_gravado,
        CNPJ,
        {
            'originador': 'Hatchbank',
            'numero_convenio': '00061HTC',
            'competencia_inicio': '2026-01',
        },
    )

    convenio = repo.obter_convenio(vinculo_gravado, CNPJ, '2025-06')

    assert (convenio['total_originadoras'], convenio['total_vigentes']) == (
        2,
        1,
    )


def test_conciliacao_do_mes_lista_so_o_que_esta_vigente(vinculo_gravado):
    repo.criar_vinculo(
        vinculo_gravado,
        CNPJ,
        {
            'originador': 'Hatchbank',
            'numero_convenio': '00061HTC',
            'competencia_inicio': '2025-01',
            'competencia_fim': '2025-03',
        },
    )

    ativos = repo.listar_ativos_para_conciliacao(vinculo_gravado, '2025-06')

    assert [v['originador'] for v in ativos] == ['Alvo Card']


def test_convenio_inexistente_estoura(banco):
    with pytest.raises(repo.ConvenioNaoEncontradoError):
        repo.obter_convenio(banco, '11.111.111/1111-11')


# =========================================================
# Repositório — custos
# =========================================================
def test_salvar_custo_devolve_historico_do_mais_novo(vinculo_gravado):
    repo.salvar_custo(
        vinculo_gravado,
        ORIGINADORA,
        NUMERO,
        {
            'metodo': 'FIXO_MENSAL',
            'valor_fixo': 100,
            'competencia_inicio': '2025-01',
        },
    )
    historico = repo.salvar_custo(
        vinculo_gravado,
        ORIGINADORA,
        NUMERO,
        {
            'metodo': 'FIXO_MENSAL',
            'valor_fixo': 150,
            'competencia_inicio': '2026-01',
        },
    )

    assert [c['competencia_inicio'] for c in historico] == [
        '2026-01',
        '2025-01',
    ]
    assert historico[1]['competencia_fim'] == '2025-12'


def test_custo_aparece_no_vinculo_da_competencia(vinculo_gravado):
    repo.salvar_custo(
        vinculo_gravado,
        ORIGINADORA,
        NUMERO,
        {
            'metodo': 'PERCENTUAL',
            'base_calculo': 'VALOR_RETORNO',
            'aliquota_percentual': 2.5,
            'competencia_inicio': '2025-01',
        },
    )

    convenio = repo.obter_convenio(vinculo_gravado, CNPJ, '2025-08')
    vinculo = convenio['originadoras'][0]

    assert vinculo['custo_vigente']['aliquota_percentual'] == 2.5
    assert '2.50%' in vinculo['custo_resumo']


def test_custo_sem_vinculo_e_recusado(banco):
    with pytest.raises(repo.VinculoNaoEncontradoError):
        repo.salvar_custo(
            banco,
            'Inexistente',
            'X',
            {
                'metodo': 'FIXO_MENSAL',
                'valor_fixo': 10,
                'competencia_inicio': '2026-01',
            },
        )


def test_custo_invalido_e_recusado(vinculo_gravado):
    with pytest.raises(repo.RegistroInvalidoError):
        repo.salvar_custo(
            vinculo_gravado,
            ORIGINADORA,
            NUMERO,
            {
                'metodo': 'PERCENTUAL',
                'aliquota_percentual': 0,
                'competencia_inicio': '2026-01',
            },
        )


# =========================================================
# Repositório — originadoras
# =========================================================
def test_originadora_com_vinculo_nao_pode_ser_excluida(vinculo_gravado):
    repo.criar_originadora(vinculo_gravado, {'nome': ORIGINADORA})

    with pytest.raises(repo.RegistroEmUsoError):
        repo.excluir_originadora(vinculo_gravado, ORIGINADORA)


def test_originadora_sem_vinculo_e_excluida(banco):
    repo.criar_originadora(banco, {'nome': 'Nova'})
    repo.excluir_originadora(banco, 'Nova')

    assert repo.listar_originadoras(banco) == []


def test_originadora_dos_vinculos_antigos_aparece_na_lista(vinculo_gravado):
    """Instalação existente não pode nascer com o cadastro vazio."""
    lista = repo.listar_originadoras(vinculo_gravado)

    assert [(o['nome'], o['cadastrado']) for o in lista] == [
        (ORIGINADORA, False)
    ]


def test_editar_originadora_herdada_cria_a_ficha_dela(vinculo_gravado):
    atualizado = repo.atualizar_originadora(
        vinculo_gravado, ORIGINADORA, {'cnpj': '11222333000144'}
    )

    assert atualizado['cnpj'] == '11.222.333/0001-44'
    assert repo.listar_originadoras(vinculo_gravado)[0]['cadastrado'] is True


def test_editar_originadora_inexistente_estoura(banco):
    with pytest.raises(repo.RegistroInvalidoError):
        repo.atualizar_originadora(banco, 'Fantasma', {'cnpj': '1'})


def test_originadora_sem_nome_e_recusada(banco):
    with pytest.raises(repo.RegistroInvalidoError):
        repo.criar_originadora(banco, {'nome': '   '})


def test_atualizar_originadora_preserva_criado_em(banco):
    primeiro = repo.criar_originadora(banco, {'nome': 'Alvo Card'})
    segundo = repo.atualizar_originadora(
        banco, 'Alvo Card', {'status': 'INATIVO'}
    )

    assert segundo['criado_em'] == primeiro['criado_em']
    assert segundo['status'] == 'INATIVO'
    assert len(repo.listar_originadoras(banco)) == 1


# =========================================================
# Imutabilidade da chave
# =========================================================
def test_violacoes_de_chave_ignora_campo_ausente():
    atual = {'originador': 'Alvo Card', 'numero_convenio': '1'}

    assert (
        violacoes_de_chave(atual, {'averbadora': 'Zetra'}, CHAVE_VINCULO) == []
    )


def test_violacoes_de_chave_tolera_mascara_de_cnpj():
    """'00394429008276' e '00.394.429/0082-76' são a mesma chave."""
    atual = {'cnpj_convenio': CNPJ}

    assert (
        violacoes_de_chave(
            atual, {'cnpj_convenio': '00394429008276'}, CHAVE_VINCULO
        )
        == []
    )


def test_aplicar_alteracao_blinda_a_chave_mesmo_no_payload():
    atual = {'originador': 'Alvo Card', 'averbadora': 'Zetra'}

    resultado = aplicar_alteracao(
        atual,
        {'originador': 'Outra', 'averbadora': 'E-Consig'},
        ('originador',),
    )

    assert resultado == {'originador': 'Alvo Card', 'averbadora': 'E-Consig'}


def test_criar_vinculo_com_chave_ocupada_e_recusado(vinculo_gravado):
    with pytest.raises(repo.ChaveDuplicadaError):
        repo.criar_vinculo(
            vinculo_gravado,
            CNPJ,
            {
                'originador': ORIGINADORA,
                'numero_convenio': NUMERO,
                'competencia_inicio': '2026-01',
            },
        )


def test_alterar_numero_do_vinculo_e_recusado(vinculo_gravado):
    """Renomear a chave criaria outro arquivo e abandonaria o histórico."""
    with pytest.raises(repo.ChaveImutavelError):
        repo.atualizar_vinculo(
            vinculo_gravado,
            ORIGINADORA,
            NUMERO,
            {'numero_convenio': '99999ALV', 'competencia_inicio': '2025-01'},
        )


def test_alterar_originadora_do_vinculo_e_recusado(vinculo_gravado):
    with pytest.raises(repo.ChaveImutavelError):
        repo.atualizar_vinculo(
            vinculo_gravado,
            ORIGINADORA,
            NUMERO,
            {'originador': 'Hatchbank', 'competencia_inicio': '2025-01'},
        )


def test_encerrar_vigencia_e_a_forma_de_desligar(vinculo_gravado):
    repo.atualizar_vinculo(
        vinculo_gravado,
        ORIGINADORA,
        NUMERO,
        {
            'competencia_inicio': '2025-01',
            'competencia_fim': '2025-06',
            'averbadora': 'E-Consig',
        },
    )

    depois = repo.listar_ativos_para_conciliacao(vinculo_gravado, '2025-09')
    durante = repo.listar_ativos_para_conciliacao(vinculo_gravado, '2025-03')

    assert depois == []
    assert durante[0]['averbadora'] == 'E-Consig'
    assert durante[0]['numero_convenio'] == NUMERO


def test_atualizar_vinculo_inexistente_estoura(banco):
    with pytest.raises(repo.VinculoNaoEncontradoError):
        repo.atualizar_vinculo(
            banco, 'Nada', 'X', {'competencia_inicio': '2026-01'}
        )


def test_criar_convenio_com_cnpj_ocupado_e_recusado(vinculo_gravado):
    with pytest.raises(repo.ChaveDuplicadaError):
        repo.criar_convenio(
            vinculo_gravado,
            {'cnpj_convenio': CNPJ, 'nome_convenio': 'Outro nome'},
        )


def test_alterar_cnpj_do_convenio_e_recusado(vinculo_gravado):
    with pytest.raises(repo.ChaveImutavelError):
        repo.atualizar_convenio(
            vinculo_gravado,
            CNPJ,
            {
                'cnpj_convenio': '11.111.111/1111-11',
                'nome_convenio': 'AERONÁUTICA',
            },
        )


def test_criar_originadora_com_nome_ocupado_e_recusado(banco):
    repo.criar_originadora(banco, {'nome': 'Alvo Card'})

    with pytest.raises(repo.ChaveDuplicadaError):
        repo.criar_originadora(banco, {'nome': 'Alvo Card'})


def test_alterar_nome_da_originadora_e_recusado(banco):
    """O nome é o prefixo dos arquivos de vínculo; renomear os órfãna."""
    repo.criar_originadora(banco, {'nome': 'Alvo Card'})

    with pytest.raises(repo.ChaveImutavelError):
        repo.atualizar_originadora(banco, 'Alvo Card', {'nome': 'Alvo'})


def test_convenio_so_dos_vinculos_e_promovido_na_primeira_edicao(banco):
    """Base anterior ao módulo: o mestre nasce na primeira edição."""
    repo.criar_vinculo(
        banco,
        CNPJ,
        {
            'originador': ORIGINADORA,
            'numero_convenio': NUMERO,
            'nome_convenio': 'AERONAUTICA',
            'competencia_inicio': '2025-01',
        },
    )

    atualizado = repo.atualizar_convenio(
        banco, CNPJ, {'nome_convenio': 'AERONÁUTICA', 'status': 'ATIVO'}
    )

    assert atualizado['nome_convenio'] == 'AERONÁUTICA'
    assert repo.obter_convenio(banco, CNPJ)['cadastrado'] is True


# =========================================================
# Excluir vínculo
# =========================================================
def test_excluir_vinculo_leva_o_custo_junto(vinculo_gravado):
    repo.salvar_custo(
        vinculo_gravado,
        ORIGINADORA,
        NUMERO,
        {
            'metodo': 'FIXO_MENSAL',
            'valor_fixo': 10,
            'competencia_inicio': '2026-01',
        },
    )

    repo.excluir_vinculo(vinculo_gravado, ORIGINADORA, NUMERO)

    assert repo.listar_custos(vinculo_gravado, ORIGINADORA, NUMERO) == []


def test_excluir_vinculo_inexistente_estoura(banco):
    with pytest.raises(repo.VinculoNaoEncontradoError):
        repo.excluir_vinculo(banco, 'Nada', 'X')


# =========================================================
# API — contrato HTTP do módulo
# =========================================================
@pytest.fixture()
def cliente(banco, monkeypatch):
    """Cliente de teste apontado para um banco de arquivos isolado."""
    config = Configuracao(
        banco_conciliacao=banco / 'x.db',
        banco_cobranca=banco / 'y.db',
        pasta_fila_entrada=None,
        host='127.0.0.1',
        porta=8000,
        pasta_banco=banco,
    )
    monkeypatch.setattr(modulo_app, 'obter_configuracao', lambda: config)
    return TestClient(modulo_app.app)


def _criar_convenio_com_vinculo(cliente):
    """Cadastra convênio + vínculo pela API e devolve o CNPJ sem máscara."""
    cliente.post(
        '/api/convenios',
        json={'cnpj_convenio': CNPJ, 'nome_convenio': 'AERONÁUTICA'},
    )
    cliente.post(
        '/api/convenios/00394429008276/originadoras',
        json={
            'originador': ORIGINADORA,
            'numero_convenio': NUMERO,
            'competencia_inicio': '2025-01',
        },
    )
    return '00394429008276'


def test_campo_omitido_grava_o_valor_do_enum_e_nao_o_membro(cliente):
    """Sem validar o default, 'ATIVO' iria para o disco como
    'StatusRegistro.ATIVO' — ilegível no .txt e reprovado pelo domínio."""
    resposta = cliente.post('/api/originadoras', json={'nome': 'Alvo Card'})

    assert resposta.json()['originadora']['status'] == 'ATIVO'


def test_faixa_sem_base_informada_tambem_grava_o_valor(cliente):
    cnpj = _criar_convenio_com_vinculo(cliente)
    assert cnpj

    resposta = cliente.post(
        f'/api/vinculos/{ORIGINADORA}/{NUMERO}/custos',
        json={
            'metodo': 'FAIXA',
            'competencia_inicio': '2026-01',
            'faixas': [
                {'ate': 0, 'metodo': 'POR_CONTRATO', 'valor_unitario': 2}
            ],
        },
    )

    assert resposta.status_code == 201
    assert (
        resposta.json()['custos'][0]['faixas'][0]['base_calculo']
        == 'VALOR_RETORNO'
    )


def test_alterar_vinculo_preserva_o_nome_do_convenio(cliente):
    """O nome é do convênio, não do vínculo: o PUT não pode zerá-lo."""
    _criar_convenio_com_vinculo(cliente)

    resposta = cliente.put(
        f'/api/vinculos/{ORIGINADORA}/{NUMERO}',
        json={'competencia_inicio': '2025-01', 'averbadora': 'Zetra'},
    )

    assert resposta.json()['vinculo']['nome_convenio'] == 'AERONÁUTICA'


def test_chave_duplicada_responde_409(cliente):
    cnpj = _criar_convenio_com_vinculo(cliente)

    resposta = cliente.post(
        f'/api/convenios/{cnpj}/originadoras',
        json={
            'originador': ORIGINADORA,
            'numero_convenio': NUMERO,
            'competencia_inicio': '2025-01',
        },
    )

    assert resposta.status_code == 409


def test_custo_invalido_responde_400_com_a_mensagem_do_dominio(cliente):
    _criar_convenio_com_vinculo(cliente)

    resposta = cliente.post(
        f'/api/vinculos/{ORIGINADORA}/{NUMERO}/custos',
        json={
            'metodo': 'PERCENTUAL',
            'aliquota_percentual': 0,
            'competencia_inicio': '2026-01',
        },
    )

    assert resposta.status_code == 400
    assert 'alíquota' in resposta.json()['detail']


def test_rota_de_ativos_nao_e_engolida_pela_rota_de_cnpj(cliente):
    """'/convenios/ativos' tem de ser declarada antes de '/convenios/{cnpj}'."""
    _criar_convenio_com_vinculo(cliente)

    resposta = cliente.get('/api/convenios/ativos?competencia=2025-06')

    assert resposta.status_code == 200
    assert [v['originador'] for v in resposta.json()['vinculos']] == [
        ORIGINADORA
    ]
