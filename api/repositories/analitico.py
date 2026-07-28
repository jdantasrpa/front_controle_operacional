# INSERIR EM: api/repositories/analitico.py
"""Leitura do Controle Sintético e do Analítico sobre o banco de arquivos.

A fonte é a árvore de pastas descrita em ``api.arquivos``: pasta =
tabela, subpasta = competência, um ``.txt`` por convênio.

Cada registro de ``tabela_concilicacao_convenio`` é um **vencimentário**:
a competência (``mes_referencia_conciliacao``) mais a data de vencimento
daquele ciclo. Um convênio acumula vencimentários de várias competências,
e é isso que alimenta o dashboard do Analítico.

Os nomes de campo dentro do ``.txt`` são os mesmos que vinham do SQLite,
então ``api.domain`` continua traduzindo sem saber de onde o dado veio.
"""

from __future__ import annotations

# --- stdlib ---
import logging
from pathlib import Path
from typing import Any, Iterable, Mapping

# --- locais ---
from api.arquivos import (
    caminho_registro,
    garantir_raiz,
    ler_arquivo,
    listar_competencias,
    listar_documentos,
)
from api.domain import (
    competencia_para_mes_referencia,
    linha_para_vencimentario,
    mes_referencia_para_competencia,
    resumo_competencia,
    texto,
)

logger = logging.getLogger(__name__)

TABELA_CONCILIACAO = 'tabela_concilicacao_convenio'
TABELA_CADASTRO = 'gestao_convenios_originador'
TABELA_PARTICULARIDADE = 'tabela_particularidade'
TABELA_CONTA = 'tabela_conta_conv'
TABELA_CONTATO = 'tabela_contato'
TABELA_SECRETARIA = 'tabela_secretaria_conv'

# Campos das abas compartilhadas, na ordem em que o front os exibe.
CAMPOS_PARTICULARIDADE = (
    'status_particularidade',
    'rubrica_produto',
    'modelo_de_averbacao',
    'retencao',
    'retencao_valor',
    'retencao_percent',
    'observacao',
    'criado_em',
    'atualizado_em',
)
CAMPOS_CONTA = (
    'banco',
    'agencia',
    'conta',
    'chave_pix',
    'cnpj',
    'status_conta',
    'criado_em',
    'atualizado_em',
)
CAMPOS_CONTATO = (
    'status',
    'secretaria',
    'nome',
    'email',
    'telefone',
    'area',
    'observacao',
    'criado_em',
    'atualizado_em',
)
CAMPOS_SECRETARIA = (
    'status_secretaria',
    'nome',
    'codigo',
    'observacao',
    'criado_em',
    'atualizado_em',
)

ABAS_COMPARTILHADAS = (
    ('secretarias', TABELA_SECRETARIA, CAMPOS_SECRETARIA),
    ('particularidades', TABELA_PARTICULARIDADE, CAMPOS_PARTICULARIDADE),
    ('contas', TABELA_CONTA, CAMPOS_CONTA),
    ('contatos', TABELA_CONTATO, CAMPOS_CONTATO),
)


class ConvenioNaoEncontradoError(LookupError):
    """Sinaliza convênio inexistente para o par originador/número."""


# =====================================================================
# Regras puras
# =====================================================================
def _projetar(linha: Mapping[str, Any], campos: tuple[str, ...]) -> dict:
    """Reduz um registro aos campos do contrato do front.

    Usa ``.get`` para tolerar arquivos gravados por versões diferentes:
    campo ausente vira string vazia em vez de quebrar a tela.

    Args:
        linha: Registro lido do arquivo.
        campos: Nomes que o front espera receber.

    Returns:
        Dicionário com ``id`` e os campos pedidos.

    Example:
        >>> _projetar({'id': 1, 'banco': 'BB'}, ('banco', 'agencia'))
        {'id': '1', 'banco': 'BB', 'agencia': ''}
    """
    return {
        'id': texto(linha.get('id')),
        **{campo: texto(linha.get(campo)) for campo in campos},
    }


def _identificacao(documento: Mapping[str, Any]) -> dict[str, str]:
    """Extrai a identificação do convênio do cabeçalho do documento."""
    primeiro = (documento.get('registros') or [{}])[0]

    return {
        'originador': texto(documento.get('originador')),
        'numero_convenio': texto(documento.get('numero_convenio')),
        'nome_convenio': texto(primeiro.get('nome_convenio')),
        'cnpj_convenio': texto(primeiro.get('cnpj_convenio')),
    }


def _do_originador(
    documentos: Iterable[Mapping[str, Any]], originador: str
) -> list[Mapping[str, Any]]:
    """Filtra documentos de uma originadora."""
    return [d for d in documentos if texto(d.get('originador')) == originador]


# =====================================================================
# I/O
# =====================================================================
def listar_filtros(pasta_banco: Path) -> dict[str, list[str]]:
    """Lê as competências e originadoras disponíveis no banco.

    Competência sai da própria árvore de pastas (sem abrir arquivo);
    originadora sai do cadastro de convênios, que é pequeno.

    Args:
        pasta_banco: Raiz do banco de arquivos.

    Returns:
        ``{'competencias': [...], 'originadores': [...]}`` — competências
        da mais nova para a mais antiga.

    Raises:
        ArmazenamentoIndisponivelError: Se a pasta do banco não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)

    pastas = listar_competencias(raiz, TABELA_CONCILIACAO)
    competencias = [mes_referencia_para_competencia(p) for p in pastas]

    return {
        'competencias': [c for c in competencias if c],
        'originadores': _originadores(raiz, pastas),
    }


def _originadores(raiz: Path, competencias: list[str]) -> list[str]:
    """Lista as originadoras, preferindo o cadastro por ser barato.

    Sem cadastro, varre a conciliação: mais lento, mas o filtro vazio
    deixaria o painel inutilizável.

    Args:
        raiz: Pasta do banco.
        competencias: Pastas de competência já listadas.

    Returns:
        Originadoras em ordem alfabética.
    """
    do_cadastro = {
        texto(documento.get('originador'))
        for documento in listar_documentos(raiz, TABELA_CADASTRO)
    }
    if any(do_cadastro):
        return sorted(o for o in do_cadastro if o)

    logger.warning(
        'Cadastro %s vazio — varrendo a conciliação para achar as '
        'originadoras.',
        TABELA_CADASTRO,
    )
    da_conciliacao = {
        texto(documento.get('originador'))
        for competencia in competencias
        for documento in listar_documentos(
            raiz, TABELA_CONCILIACAO, competencia
        )
    }

    return sorted(o for o in da_conciliacao if o)


def listar_sintetico(
    pasta_banco: Path, competencia: str, originador: str
) -> list[dict[str, Any]]:
    """Monta as linhas do Controle Sintético de uma competência.

    Lê apenas a pasta daquela competência — o custo não cresce com o
    histórico acumulado.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        competencia: Competência no formato ``MM/AAAA``.
        originador: Originadora selecionada no filtro.

    Returns:
        Uma linha por convênio, com o resumo dos vencimentários daquela
        competência.

    Raises:
        ArmazenamentoIndisponivelError: Se a pasta do banco não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    mes_referencia = competencia_para_mes_referencia(competencia)

    documentos = _do_originador(
        listar_documentos(raiz, TABELA_CONCILIACAO, mes_referencia),
        originador,
    )

    return [
        {
            'convenio': _identificacao(documento),
            'competencia': competencia,
            'resumo': resumo_competencia(
                [
                    linha_para_vencimentario(registro)
                    for registro in documento['registros']
                ]
            ),
        }
        for documento in documentos
        if documento['registros']
    ]


def _ler_aba(
    raiz: Path, tabela: str, originador: str, numero_convenio: str
) -> list[dict[str, Any]]:
    """Lê os registros de uma aba compartilhada do convênio."""
    lido = ler_arquivo(
        caminho_registro(raiz, tabela, originador, numero_convenio)
    )

    return lido[0]['registros'] if lido else []


def obter_convenio(
    pasta_banco: Path, originador: str, numero_convenio: str
) -> dict[str, Any]:
    """Monta o convênio completo do Controle Analítico.

    Traz os vencimentários de **todas** as competências — é o que
    alimenta o dashboard onde o operador troca de competência sem voltar
    ao Sintético — e as abas compartilhadas (regra do convênio).

    Cada competência é um acesso direto ao arquivo do convênio: não há
    varredura de pasta.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        originador: Originadora do convênio.
        numero_convenio: Número do convênio.

    Returns:
        Convênio no contrato de ``front/js/data.js``.

    Raises:
        ConvenioNaoEncontradoError: Se não há conciliação para o par.
        ArmazenamentoIndisponivelError: Se a pasta do banco não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)

    documentos = [
        lido[0]
        for competencia in listar_competencias(raiz, TABELA_CONCILIACAO)
        if (
            lido := ler_arquivo(
                caminho_registro(
                    raiz,
                    TABELA_CONCILIACAO,
                    originador,
                    numero_convenio,
                    competencia,
                )
            )
        )
    ]
    registros = [r for d in documentos for r in d['registros']]

    if not registros:
        raise ConvenioNaoEncontradoError(
            f'Convênio {numero_convenio} não encontrado '
            f'para a originadora {originador}.'
        )

    abas = {
        chave: [
            _projetar(registro, campos)
            for registro in _ler_aba(raiz, tabela, originador, numero_convenio)
        ]
        for chave, tabela, campos in ABAS_COMPARTILHADAS
    }

    return {
        **_identificacao(documentos[0]),
        **abas,
        'vencimentarios': [
            linha_para_vencimentario(registro) for registro in registros
        ],
    }
