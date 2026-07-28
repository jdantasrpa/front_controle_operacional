"""Testes do banco em árvore de arquivos (pasta = tabela)."""

# --- stdlib ---
import sys
from pathlib import Path

# --- terceiros ---
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# --- locais ---
from api.arquivos import (  # noqa: E402
    ArmazenamentoIndisponivelError,
    ConflitoDeVersaoError,
    apelidar,
    caminho_registro,
    desserializar,
    garantir_raiz,
    gravar_arquivo,
    ler_arquivo,
    listar_competencias,
    listar_documentos,
    montar_documento,
    nome_arquivo,
    serializar,
    versao_do_conteudo,
)


# =========================================================
# Nomes e caminhos
# =========================================================
@pytest.mark.parametrize(
    'entrada, esperado',
    [
        ('Alvo Card', 'alvo_card'),
        ('GOV. GOIÁS', 'gov_goias'),
        ('  Hatchbank  ', 'hatchbank'),
        ('C:\\ilegal/no*windows?', 'c_ilegal_no_windows'),
        ('', ''),
    ],
)
def test_apelidar_gera_nome_seguro(entrada, esperado):
    assert apelidar(entrada) == esperado


def test_nome_arquivo_inclui_a_originadora():
    """A identidade do convênio é o par (originador, número)."""
    assert nome_arquivo('Alvo Card', '00011ALV') == 'alvo_card__00011ALV.txt'


def test_caminho_com_e_sem_competencia(tmp_path):
    com = caminho_registro(
        tmp_path, 'tabela_concilicacao_convenio', 'Alvo Card', '1', '2026-07'
    )
    sem = caminho_registro(tmp_path, 'tabela_contato', 'Alvo Card', '1')

    assert com.parent.name == '2026-07'
    assert sem.parent.name == 'tabela_contato'


# =========================================================
# Serialização
# =========================================================
def test_serializar_preserva_acento_e_tipo():
    texto = serializar({'nome': 'GOV. GOIÁS', 'valor': 1234.56})

    assert 'GOIÁS' in texto
    assert '1234.56' in texto


def test_desserializar_garante_lista_de_registros():
    assert desserializar('{"tabela": "x"}')['registros'] == []


def test_desserializar_recusa_json_invalido():
    with pytest.raises(ValueError):
        desserializar('isto não é json')


# =========================================================
# Leitura e gravação
# =========================================================
def _documento(registros):
    return montar_documento(
        'tabela_contato', 'Alvo Card', '00011ALV', registros
    )


def test_gravar_e_ler_de_volta(tmp_path):
    caminho = tmp_path / 'tabela_contato' / 'alvo_card__00011ALV.txt'

    gravar_arquivo(caminho, _documento([{'nome': 'Marina'}]))
    documento, versao = ler_arquivo(caminho)

    assert documento['registros'] == [{'nome': 'Marina'}]
    assert documento['originador'] == 'Alvo Card'
    assert versao == versao_do_conteudo(caminho.read_text(encoding='utf-8'))


def test_ler_arquivo_inexistente_devolve_none(tmp_path):
    """Ausência é registro inexistente, não erro."""
    assert ler_arquivo(tmp_path / 'nao_existe.txt') is None


def test_ler_arquivo_corrompido_falha_alto(tmp_path):
    caminho = tmp_path / 'quebrado.txt'
    caminho.write_text('{ isto não fecha', encoding='utf-8')

    with pytest.raises(ArmazenamentoIndisponivelError):
        ler_arquivo(caminho)


def test_gravacao_nao_deixa_temporario_para_tras(tmp_path):
    caminho = tmp_path / 'tabela_contato' / 'alvo_card__00011ALV.txt'

    gravar_arquivo(caminho, _documento([{'nome': 'Marina'}]))

    assert list(caminho.parent.glob('*.tmp')) == []


# =========================================================
# Versão otimista — o que impede um operador apagar o outro
# =========================================================
def test_gravar_com_versao_correta_passa(tmp_path):
    caminho = tmp_path / 'c.txt'
    gravar_arquivo(caminho, _documento([{'nome': 'Marina'}]))
    _, versao = ler_arquivo(caminho)

    nova = gravar_arquivo(
        caminho, _documento([{'nome': 'Marina Alves'}]), versao
    )

    assert nova != versao
    assert ler_arquivo(caminho)[0]['registros'] == [{'nome': 'Marina Alves'}]


def test_gravar_com_versao_defasada_e_recusado(tmp_path):
    caminho = tmp_path / 'c.txt'
    gravar_arquivo(caminho, _documento([{'nome': 'Marina'}]))
    _, versao_do_operador_a = ler_arquivo(caminho)

    # Operador B salva primeiro.
    gravar_arquivo(caminho, _documento([{'nome': 'Beatriz'}]))

    # Operador A tenta salvar com a versão que leu antes.
    with pytest.raises(ConflitoDeVersaoError):
        gravar_arquivo(
            caminho, _documento([{'nome': 'Marina'}]), versao_do_operador_a
        )

    # O trabalho de B continua lá.
    assert ler_arquivo(caminho)[0]['registros'] == [{'nome': 'Beatriz'}]


def test_criar_arquivo_novo_exige_versao_vazia(tmp_path):
    caminho = tmp_path / 'novo.txt'

    with pytest.raises(ConflitoDeVersaoError):
        gravar_arquivo(caminho, _documento([]), 'versao_inventada')

    assert gravar_arquivo(caminho, _documento([]), '')


# =========================================================
# Varredura da árvore
# =========================================================
def test_listar_competencias_da_mais_nova_para_a_mais_antiga(tmp_path):
    for competencia in ('2025-12', '2026-07', '2026-01'):
        (tmp_path / 'tabela_concilicacao_convenio' / competencia).mkdir(
            parents=True
        )
    # Pasta que não é competência não pode entrar na lista.
    (tmp_path / 'tabela_concilicacao_convenio' / 'rascunho').mkdir()

    competencias = listar_competencias(
        tmp_path, 'tabela_concilicacao_convenio'
    )

    assert competencias == ['2026-07', '2026-01', '2025-12']


def test_listar_competencias_de_tabela_ausente_devolve_vazio(tmp_path):
    assert listar_competencias(tmp_path, 'tabela_que_nao_existe') == []


def test_listar_documentos_percorre_a_pasta(tmp_path):
    for numero in ('00011ALV', '00001ALV'):
        gravar_arquivo(
            caminho_registro(tmp_path, 'tabela_contato', 'Alvo Card', numero),
            montar_documento('tabela_contato', 'Alvo Card', numero, []),
        )

    numeros = [
        d['numero_convenio']
        for d in listar_documentos(tmp_path, 'tabela_contato')
    ]

    assert numeros == ['00001ALV', '00011ALV']


def test_garantir_raiz_recusa_pasta_inexistente(tmp_path):
    with pytest.raises(ArmazenamentoIndisponivelError):
        garantir_raiz(tmp_path / 'nao_existe')
