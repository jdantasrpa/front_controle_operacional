# INSERIR EM: api/repositories/geracao.py
"""Persistência da geração de vencimentários no banco de arquivos.

Escreve na mesma árvore do resto do painel (:mod:`api.arquivos`), na
tabela ``tabela_concilicacao_convenio`` — pasta = tabela, subpasta =
competência, um ``.txt`` por convênio. Três operações, todas de gravação
direta (com versão otimista, como o restante do painel):

* :func:`gerar_competencia` — o "gerar mês seguinte" massivo. Clona o
  esqueleto de cada convênio vigente a partir do mês anterior, grava a
  competência nova zerada e deixa um **ticket** na fila para a automação
  do Datacob preencher os valores.
* :func:`criar_vencimentario_avulso` — o operador cria um vencimentário à
  mão, informando todos os campos.
* :func:`excluir_vencimentario` — remove um vencimento específico (mira
  pela data de vencimento).

As regras puras — clonagem, validação, montagem do ticket — ficam em
:mod:`api.domain_geracao`; aqui há leitura, gravação e a orquestração
das duas coisas. Quem decide **quem** está vigente é
:mod:`api.repositories.convenios`, fonte única da vigência.
"""

from __future__ import annotations

# --- stdlib ---
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

# --- locais ---
from api.arquivos import (
    caminho_registro,
    garantir_raiz,
    gravar_arquivo,
    ler_arquivo,
    listar_competencias,
    montar_documento,
)
from api.domain import texto
from api.domain_convenios import esta_vigente
from api.domain_geracao import (
    clonar_competencia,
    competencia_anterior,
    competencias_no_intervalo,
    dias_de_vencimento,
    montar_solicitacao_geracao,
    montar_vencimentario_do_controle,
    montar_vencimentario_manual,
    proximo_id,
    validar_vencimentario_manual,
)
from api.repositories import conciliacao_gerencia as repo_gerencia
from api.repositories import convenios as repo_convenios

logger = logging.getLogger(__name__)

TABELA_CONCILIACAO = 'tabela_concilicacao_convenio'
EXTENSAO_TICKET = '.txt'


class VencimentarioInvalidoError(ValueError):
    """Sinaliza payload de vencimentário reprovado pelas regras puras."""


class VencimentarioNaoEncontradoError(LookupError):
    """Sinaliza exclusão de um vencimento que não existe na competência."""


class PeriodoInvalidoError(ValueError):
    """Sinaliza intervalo de competências malformado na geração por período."""


# =====================================================================
# Carimbos de tempo
# =====================================================================
def _hoje() -> str:
    """Data de hoje em ``AAAA-MM-DD`` — mesmo formato dos carimbos gravados."""
    return datetime.now().strftime('%Y-%m-%d')


def _agora_ticket() -> str:
    """Data/hora da solicitação, no formato brasileiro da fila."""
    return datetime.now().strftime('%d-%m-%Y %H:%M:%S')


def _id_ticket() -> str:
    """Identificador único de um ticket de geração (nome do arquivo)."""
    return (
        f'{datetime.now().strftime("%Y%m%d_%H%M%S_%f")}'
        f'__{uuid.uuid4().hex[:8]}'
    )


# =====================================================================
# Leitura de vencimentários
# =====================================================================
def _caminho(
    raiz: Path, originador: str, numero_convenio: str, competencia: str
) -> Path:
    """Resolve o arquivo de conciliação de um convênio numa competência."""
    return caminho_registro(
        raiz, TABELA_CONCILIACAO, originador, numero_convenio, competencia
    )


def _ler_vencimentarios(
    raiz: Path, originador: str, numero_convenio: str, competencia: str
) -> tuple[list[dict[str, Any]], str]:
    """Lê os vencimentários de um convênio numa competência, com a versão.

    Args:
        raiz: Pasta do banco.
        originador: Originadora do convênio.
        numero_convenio: Número do convênio.
        competencia: Competência ``AAAA-MM``.

    Returns:
        Par ``(registros, versao)``; lista vazia e versão vazia quando o
        arquivo ainda não existe.
    """
    lido = ler_arquivo(
        _caminho(raiz, originador, numero_convenio, competencia)
    )
    if not lido:
        return [], ''

    return list(lido[0].get('registros') or []), lido[1]


def _ids_existentes(
    raiz: Path, originador: str, numero_convenio: str
) -> list[Any]:
    """Coleta todos os ids de vencimentário já usados pelo convênio.

    Varre todas as competências: o front identifica o vencimentário pelo
    ``id`` sobre o histórico inteiro do convênio, então o próximo id tem
    de ser único aí, não só no mês.

    Args:
        raiz: Pasta do banco.
        originador: Originadora do convênio.
        numero_convenio: Número do convênio.

    Returns:
        Ids encontrados, em qualquer competência.
    """
    return [
        registro.get('id')
        for competencia in listar_competencias(raiz, TABELA_CONCILIACAO)
        for registro in _ler_vencimentarios(
            raiz, originador, numero_convenio, competencia
        )[0]
    ]


def _gravar_vencimentarios(
    raiz: Path,
    originador: str,
    numero_convenio: str,
    competencia: str,
    registros: Iterable[Mapping[str, Any]],
    versao_esperada: str | None,
) -> None:
    """Grava o arquivo de conciliação de um convênio numa competência."""
    documento = montar_documento(
        TABELA_CONCILIACAO,
        originador,
        numero_convenio,
        [dict(registro) for registro in registros],
        competencia,
    )
    gravar_arquivo(
        _caminho(raiz, originador, numero_convenio, competencia),
        documento,
        versao_esperada,
    )


# =====================================================================
# Geração massiva (clonar mês anterior + emitir ticket)
# =====================================================================
def gerar_competencia(
    pasta_banco: Path,
    competencia: str,
    pasta_fila: Path,
    ator: str,
) -> dict[str, Any]:
    """Gera a competência seguinte para os convênios vigentes e ligados.

    Para cada vínculo vigente na competência **e ligado na Conciliação**,
    clona o esqueleto do mês anterior (dias de vencimento, SLA e corte)
    com os valores zerados e grava a competência nova. Vínculo que a mesa
    desligou fica de fora — a Conciliação é a dona do que entra. Convênio
    que já tem a competência gravada é preservado — a operação é
    idempotente e nunca sobrescreve trabalho já feito. Ao final, deixa um
    ticket na fila para a automação do Datacob completar os saldos.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        competencia: Competência ``AAAA-MM`` a gerar.
        pasta_fila: Pasta onde o ticket de geração é depositado.
        ator: Quem solicitou a geração, para auditoria.

    Returns:
        Resumo com os convênios gerados, os pulados (já existentes), os
        sem esqueleto de origem e o nome do ticket emitido.

    Raises:
        ArmazenamentoIndisponivelError: Se a pasta do banco não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)

    return _gerar_uma_competencia(
        raiz, pasta_banco, competencia, pasta_fila, ator, None
    )


def _gerar_uma_competencia(
    raiz: Path,
    pasta_banco: Path,
    competencia: str,
    pasta_fila: Path,
    ator: str,
    filtro_originador: str | None,
) -> dict[str, Any]:
    """Gera uma competência para os vínculos aptos, opcionalmente filtrados.

    Núcleo comum do massivo geral e do massivo por originadora: só muda o
    conjunto de vínculos. ``filtro_originador`` ``None`` gera todos; um nome
    afunila naquela originadora.
    """
    origem = competencia_anterior(competencia)
    agora = _hoje()
    controles = repo_gerencia.controles_vencimento(pasta_banco)

    ativos = _vinculos_para_gerar(pasta_banco, competencia)
    if filtro_originador is not None:
        ativos = [
            v
            for v in ativos
            if texto(v.get('originador')) == texto(filtro_originador)
        ]
    resultado = [
        _gerar_para_vinculo(
            raiz,
            v,
            competencia,
            origem,
            agora,
            _controle_do_vinculo(controles, v),
        )
        for v in ativos
    ]

    ticket = _emitir_ticket(pasta_fila, competencia, origem, resultado, ator)
    logger.info(
        'Geração de %s: %s convênio(s), ticket %s',
        competencia,
        len(resultado),
        ticket,
    )

    return _resumo_massivo(competencia, origem, resultado, ticket)


def _resumo_massivo(
    competencia: str,
    origem: str,
    resultado: list[dict[str, Any]],
    ticket: str,
) -> dict[str, Any]:
    """Agrupa o resultado da geração de uma competência por situação."""
    return {
        'competencia': competencia,
        'competencia_origem': origem,
        'gerados': [r for r in resultado if r['situacao'] == 'gerado'],
        'pulados': [r for r in resultado if r['situacao'] == 'ja_existia'],
        'sem_origem': [r for r in resultado if r['situacao'] == 'sem_origem'],
        'ticket': ticket,
    }


def _controle_do_vinculo(
    controles: Mapping[tuple[str, str], dict[str, Any]],
    vinculo: Mapping[str, Any],
) -> dict[str, Any]:
    """Controle de vencimento definido para o vínculo; ``{}`` se não houver."""
    chave = (
        texto(vinculo.get('originador')),
        texto(vinculo.get('numero_convenio')),
    )
    return controles.get(chave, {})


def _gerar_para_vinculo(
    raiz: Path,
    vinculo: Mapping[str, Any],
    competencia: str,
    origem: str,
    agora: str,
    controle: Mapping[str, Any],
) -> dict[str, Any]:
    """Gera a competência de um convênio: pelo controle definido ou clonando.

    Com controle de vencimento cadastrado na gerência, o mês nasce com um
    vencimento só, replicando o dia e os offsets — resolve inclusive o
    convênio novo (sem mês anterior). Sem controle, cai no caminho antigo
    de clonar o mês anterior. Competência já gravada é sempre preservada
    (idempotência).
    """
    originador = texto(vinculo.get('originador'))
    numero = texto(vinculo.get('numero_convenio'))
    ficha = {
        'originador': originador,
        'numero_convenio': numero,
        'nome_convenio': texto(vinculo.get('nome_convenio')),
        'cnpj_convenio': texto(vinculo.get('cnpj_convenio')),
    }

    ja_gravado, _ = _ler_vencimentarios(raiz, originador, numero, competencia)
    if ja_gravado:
        return {
            **ficha,
            'situacao': 'ja_existia',
            'dias_vencimento': dias_de_vencimento(ja_gravado),
        }

    if controle:
        return _gerar_da_definicao(raiz, ficha, competencia, controle, agora)

    origem_regs, _ = _ler_vencimentarios(raiz, originador, numero, origem)
    if not origem_regs:
        return {**ficha, 'situacao': 'sem_origem', 'dias_vencimento': []}

    id_inicial = proximo_id(_ids_existentes(raiz, originador, numero))
    clones = clonar_competencia(origem_regs, competencia, id_inicial, agora)
    _gravar_vencimentarios(raiz, originador, numero, competencia, clones, None)

    return {
        **ficha,
        'situacao': 'gerado',
        'dias_vencimento': dias_de_vencimento(clones),
    }


def _gerar_da_definicao(
    raiz: Path,
    ficha: Mapping[str, Any],
    competencia: str,
    controle: Mapping[str, Any],
    agora: str,
) -> dict[str, Any]:
    """Cria o vencimentário único da competência a partir do controle."""
    originador = texto(ficha.get('originador'))
    numero = texto(ficha.get('numero_convenio'))
    id_inicial = proximo_id(_ids_existentes(raiz, originador, numero))
    registro = montar_vencimentario_do_controle(
        ficha, competencia, controle, id_inicial, agora
    )
    _gravar_vencimentarios(
        raiz, originador, numero, competencia, [registro], None
    )

    return {
        **dict(ficha),
        'situacao': 'gerado',
        'dias_vencimento': dias_de_vencimento([registro]),
    }


def _emitir_ticket(
    pasta_fila: Path,
    competencia: str,
    origem: str,
    resultado: Iterable[Mapping[str, Any]],
    ator: str,
) -> str:
    """Grava o ticket de geração na fila e devolve o nome do arquivo.

    O ticket lista **todos** os convênios vigentes — inclusive os que já
    tinham a competência —, porque a automação do Datacob precisa
    preencher os valores de todos eles, não só dos recém-clonados.
    """
    id_ticket = _id_ticket()
    ticket = montar_solicitacao_geracao(
        competencia,
        origem,
        [
            {
                k: r[k]
                for k in (
                    'originador',
                    'numero_convenio',
                    'nome_convenio',
                    'cnpj_convenio',
                    'dias_vencimento',
                )
            }
            for r in resultado
        ],
        ator,
        id_ticket,
        _agora_ticket(),
    )

    pasta_fila.mkdir(parents=True, exist_ok=True)
    caminho = pasta_fila / f'{id_ticket}{EXTENSAO_TICKET}'
    gravar_arquivo(caminho, ticket)

    return caminho.name


def _vinculos_para_gerar(
    pasta_banco: Path, competencia: str
) -> list[dict[str, Any]]:
    """Vínculos que entram na geração — passam nos três gates.

    Um vínculo só gera se estiver: vigente na Gestão (competência
    início/fim), ligado na mesa (toggle do convênio) e com a originadora
    ativa (grupo master). Vigência é da Gestão; os outros dois são estados
    próprios da Conciliação.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        competencia: Competência ``AAAA-MM`` a gerar.

    Returns:
        Vínculos aptos à geração.
    """
    vigentes = repo_convenios.listar_ativos_para_conciliacao(
        pasta_banco, competencia
    )
    desligadas = repo_gerencia.chaves_desligadas(pasta_banco)
    originadoras_off = repo_gerencia.originadoras_desativadas(pasta_banco)

    return [
        vinculo
        for vinculo in vigentes
        if texto(vinculo.get('originador')) not in originadoras_off
        and (
            texto(vinculo.get('originador')),
            texto(vinculo.get('numero_convenio')),
        )
        not in desligadas
    ]


# =====================================================================
# Geração por período (um convênio, várias competências)
# =====================================================================
def gerar_competencias_periodo(
    pasta_banco: Path,
    originador: str,
    numero_convenio: str,
    competencia_inicio: str,
    competencia_fim: str,
    pasta_fila: Path,
    ator: str,
) -> dict[str, Any]:
    """Gera a competência de **um convênio** ao longo de um intervalo.

    A pessoa escolhe a originadora, o número e o período (inicial →
    final); cada mês é clonado a partir do anterior, na ordem crescente. É
    idempotente por competência (mês já gravado é preservado) e respeita o
    liga/desliga: convênio desligado não gera nada. Emite um ticket por
    competência efetivamente gerada, para a automação do Datacob.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        originador: Originadora do convênio.
        numero_convenio: Número do convênio naquela originadora.
        competencia_inicio: Competência ``AAAA-MM`` inicial.
        competencia_fim: Competência ``AAAA-MM`` final.
        pasta_fila: Pasta onde os tickets são depositados.
        ator: Quem solicitou a geração, para auditoria.

    Returns:
        Resumo com gerados, pulados, fora de vigência, os tickets e — se
        for o caso — a marca de convênio desligado.

    Raises:
        PeriodoInvalidoError: Se o intervalo for malformado.
        api.repositories.convenios.VinculoNaoEncontradoError: Se o vínculo
            não existir.
        ArmazenamentoIndisponivelError: Se a pasta do banco não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    competencias = competencias_no_intervalo(
        competencia_inicio, competencia_fim
    )
    if not competencias:
        raise PeriodoInvalidoError(
            f'Período inválido: {competencia_inicio!r} a '
            f'{competencia_fim!r}. Use AAAA-MM, com fim >= início.'
        )

    vinculo = _achar_vinculo(pasta_banco, originador, numero_convenio)
    if vinculo is None:
        raise repo_convenios.VinculoNaoEncontradoError(
            f'Vínculo {originador} / {numero_convenio} não encontrado.'
        )

    if _esta_desligado(pasta_banco, originador, numero_convenio):
        return _resumo_desligado(originador, numero_convenio, competencias)

    controle = _controle_do_vinculo(
        repo_gerencia.controles_vencimento(pasta_banco), vinculo
    )
    resultados = [
        _gerar_periodo_para_competencia(raiz, vinculo, comp, _hoje(), controle)
        for comp in competencias
    ]
    tickets = _emitir_tickets_periodo(pasta_fila, resultados, ator)
    logger.info(
        'Geração por período de %s/%s: %s a %s, %s ticket(s)',
        originador,
        numero_convenio,
        competencias[0],
        competencias[-1],
        len(tickets),
    )

    return _resumo_periodo(
        originador, numero_convenio, competencias, resultados, tickets
    )


def _achar_vinculo(
    pasta_banco: Path, originador: str, numero_convenio: str
) -> dict[str, Any] | None:
    """Localiza o vínculo cru (com vigência) pelo par originadora/número."""
    return next(
        (
            vinculo
            for vinculo in repo_convenios.listar_vinculos(pasta_banco)
            if texto(vinculo.get('originador')) == texto(originador)
            and texto(vinculo.get('numero_convenio')) == texto(numero_convenio)
        ),
        None,
    )


def _esta_desligado(
    pasta_banco: Path, originador: str, numero_convenio: str
) -> bool:
    """Diz se a mesa desligou este vínculo na Conciliação."""
    return (
        texto(originador),
        texto(numero_convenio),
    ) in repo_gerencia.chaves_desligadas(pasta_banco)


def _gerar_periodo_para_competencia(
    raiz: Path,
    vinculo: Mapping[str, Any],
    competencia: str,
    agora: str,
    controle: Mapping[str, Any],
) -> dict[str, Any]:
    """Gera uma competência do convênio, respeitando a janela de vigência."""
    if not esta_vigente(vinculo, competencia):
        return {
            'originador': texto(vinculo.get('originador')),
            'numero_convenio': texto(vinculo.get('numero_convenio')),
            'nome_convenio': texto(vinculo.get('nome_convenio')),
            'cnpj_convenio': texto(vinculo.get('cnpj_convenio')),
            'competencia': competencia,
            'situacao': 'fora_vigencia',
            'dias_vencimento': [],
        }

    origem = competencia_anterior(competencia)
    resultado = _gerar_para_vinculo(
        raiz, vinculo, competencia, origem, agora, controle
    )

    return {**resultado, 'competencia': competencia}


def _emitir_tickets_periodo(
    pasta_fila: Path,
    resultados: Iterable[Mapping[str, Any]],
    ator: str,
) -> list[str]:
    """Emite um ticket por competência com convênio a preencher."""
    return [
        _emitir_ticket(
            pasta_fila,
            resultado['competencia'],
            competencia_anterior(resultado['competencia']),
            [resultado],
            ator,
        )
        for resultado in resultados
        if resultado['situacao'] in ('gerado', 'ja_existia')
    ]


def _resumo_periodo(
    originador: str,
    numero_convenio: str,
    competencias: list[str],
    resultados: list[dict[str, Any]],
    tickets: list[str],
) -> dict[str, Any]:
    """Monta o resumo da geração por período agrupado por situação."""
    return {
        'originador': originador,
        'numero_convenio': numero_convenio,
        'competencia_inicio': competencias[0],
        'competencia_fim': competencias[-1],
        'desligado': False,
        'gerados': [r for r in resultados if r['situacao'] == 'gerado'],
        'pulados': [r for r in resultados if r['situacao'] == 'ja_existia'],
        'sem_origem': [r for r in resultados if r['situacao'] == 'sem_origem'],
        'fora_vigencia': [
            r for r in resultados if r['situacao'] == 'fora_vigencia'
        ],
        'tickets': tickets,
    }


def _resumo_desligado(
    originador: str, numero_convenio: str, competencias: list[str]
) -> dict[str, Any]:
    """Resumo de quando o convênio está desligado na Conciliação."""
    return {
        'originador': originador,
        'numero_convenio': numero_convenio,
        'competencia_inicio': competencias[0],
        'competencia_fim': competencias[-1],
        'desligado': True,
        'gerados': [],
        'pulados': [],
        'sem_origem': [],
        'fora_vigencia': [],
        'tickets': [],
    }


# =====================================================================
# Geração por originadora (grupo master)
# =====================================================================
def gerar_competencia_originadora(
    pasta_banco: Path,
    originador: str,
    competencia: str,
    pasta_fila: Path,
    ator: str,
) -> dict[str, Any]:
    """Gera uma competência para todos os convênios de uma originadora.

    É o massivo afunilado no grupo master: gera os convênios daquela
    originadora que estão vigentes e ligados. Originadora desativada não
    gera nada e o resumo diz isso.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        originador: Originadora dona dos convênios.
        competencia: Competência ``AAAA-MM`` a gerar.
        pasta_fila: Pasta onde o ticket é depositado.
        ator: Quem solicitou a geração, para auditoria.

    Returns:
        Resumo da competência (como o massivo) com ``originador`` e
        ``desativada``.

    Raises:
        ArmazenamentoIndisponivelError: Se a pasta do banco não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    if _originadora_desativada(pasta_banco, originador):
        return {
            'originador': originador,
            'competencia': competencia,
            'desativada': True,
            'gerados': [],
            'pulados': [],
            'sem_origem': [],
            'ticket': '',
        }

    resumo = _gerar_uma_competencia(
        raiz, pasta_banco, competencia, pasta_fila, ator, originador
    )

    return {'originador': originador, 'desativada': False, **resumo}


def gerar_competencias_periodo_originadora(
    pasta_banco: Path,
    originador: str,
    competencia_inicio: str,
    competencia_fim: str,
    pasta_fila: Path,
    ator: str,
) -> dict[str, Any]:
    """Gera um intervalo de competências para uma originadora inteira.

    Percorre o período em ordem crescente, gerando em cada mês os convênios
    vigentes e ligados da originadora. Originadora desativada não gera nada.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        originador: Originadora dona dos convênios.
        competencia_inicio: Competência ``AAAA-MM`` inicial.
        competencia_fim: Competência ``AAAA-MM`` final.
        pasta_fila: Pasta onde os tickets são depositados.
        ator: Quem solicitou a geração, para auditoria.

    Returns:
        Resumo com o intervalo, o resumo de cada competência e os tickets.

    Raises:
        PeriodoInvalidoError: Se o intervalo for malformado.
        ArmazenamentoIndisponivelError: Se a pasta do banco não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    competencias = competencias_no_intervalo(
        competencia_inicio, competencia_fim
    )
    if not competencias:
        raise PeriodoInvalidoError(
            f'Período inválido: {competencia_inicio!r} a '
            f'{competencia_fim!r}. Use AAAA-MM, com fim >= início.'
        )

    if _originadora_desativada(pasta_banco, originador):
        return {
            'originador': originador,
            'competencia_inicio': competencias[0],
            'competencia_fim': competencias[-1],
            'desativada': True,
            'por_competencia': [],
            'tickets': [],
        }

    resumos = [
        _gerar_uma_competencia(
            raiz, pasta_banco, comp, pasta_fila, ator, originador
        )
        for comp in competencias
    ]

    return {
        'originador': originador,
        'competencia_inicio': competencias[0],
        'competencia_fim': competencias[-1],
        'desativada': False,
        'por_competencia': resumos,
        'tickets': [resumo['ticket'] for resumo in resumos],
    }


def _originadora_desativada(pasta_banco: Path, originador: str) -> bool:
    """Diz se a mesa desativou a originadora (gate de grupo master)."""
    return texto(originador) in repo_gerencia.originadoras_desativadas(
        pasta_banco
    )


# =====================================================================
# Vencimentário avulso
# =====================================================================
def criar_vencimentario_avulso(
    pasta_banco: Path,
    competencia: str,
    dados: Mapping[str, Any],
) -> dict[str, Any]:
    """Cria um vencimentário avulso, com todos os campos do operador.

    O caminho de um convênio só: o operador informa a data de vencimento,
    o SLA, o corte e os valores. O registro nasce preso à competência do
    contexto, com id único no histórico do convênio.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        competencia: Competência ``AAAA-MM`` em que o vencimentário nasce.
        dados: Payload do formulário — ``originador``,
            ``numero_convenio`` e ``data_vencimento`` obrigatórios.

    Returns:
        O vencimentário gravado.

    Raises:
        VencimentarioInvalidoError: Se o payload for reprovado.
        ArmazenamentoIndisponivelError: Se a gravação falhar.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    originador = texto(dados.get('originador'))
    numero = texto(dados.get('numero_convenio'))

    erros = _validar_avulso(originador, numero, dados, competencia)
    if erros:
        raise VencimentarioInvalidoError(' '.join(erros))

    existentes, versao = _ler_vencimentarios(
        raiz, originador, numero, competencia
    )
    novo_id = proximo_id(_ids_existentes(raiz, originador, numero))
    registro = montar_vencimentario_manual(
        dados, competencia, novo_id, _hoje()
    )

    _gravar_vencimentarios(
        raiz,
        originador,
        numero,
        competencia,
        [*existentes, registro],
        versao or None,
    )
    logger.info(
        'Vencimentário avulso %s/%s em %s (venc %s)',
        originador,
        numero,
        competencia,
        registro['data_vencimento'],
    )

    return registro


def _validar_avulso(
    originador: str,
    numero_convenio: str,
    dados: Mapping[str, Any],
    competencia: str,
) -> list[str]:
    """Junta as validações de identidade e as regras puras do avulso."""
    return [
        *([] if originador else ['Informe a originadora.']),
        *([] if numero_convenio else ['Informe o número do convênio.']),
        *validar_vencimentario_manual(dados, competencia),
    ]


# =====================================================================
# Exclusão de um vencimento específico
# =====================================================================
def excluir_vencimentario(
    pasta_banco: Path,
    originador: str,
    numero_convenio: str,
    competencia: str,
    data_vencimento: str,
) -> None:
    """Remove um vencimento específico de uma competência.

    A data de vencimento é a chave que distingue os vencimentos de um mês
    (dia 05 × dia 20), então é por ela que a exclusão mira. Some o último
    vencimento da competência? O arquivo do mês é removido, para a
    listagem de competências não mostrar um mês vazio.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        originador: Originadora do convênio.
        numero_convenio: Número do convênio.
        competencia: Competência ``AAAA-MM``.
        data_vencimento: Data ``AAAA-MM-DD`` do vencimento a excluir.

    Raises:
        VencimentarioNaoEncontradoError: Se não houver vencimento nessa
            data.
        ArmazenamentoIndisponivelError: Se a gravação falhar.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    alvo = texto(data_vencimento)
    existentes, versao = _ler_vencimentarios(
        raiz, originador, numero_convenio, competencia
    )

    restantes = [
        registro
        for registro in existentes
        if texto(registro.get('data_vencimento')) != alvo
    ]
    if len(restantes) == len(existentes):
        raise VencimentarioNaoEncontradoError(
            f'Nenhum vencimento em {alvo} para {originador} / '
            f'{numero_convenio} na competência {competencia}.'
        )

    if restantes:
        _gravar_vencimentarios(
            raiz,
            originador,
            numero_convenio,
            competencia,
            restantes,
            versao or None,
        )
    else:
        _caminho(raiz, originador, numero_convenio, competencia).unlink(
            missing_ok=True
        )

    logger.info(
        'Vencimento %s excluído de %s/%s em %s',
        alvo,
        originador,
        numero_convenio,
        competencia,
    )
