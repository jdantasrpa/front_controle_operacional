# INSERIR EM: api/repositories/responsaveis.py
"""Persistência dos responsáveis pela conciliação.

Duas tabelas no banco de arquivos (:mod:`api.arquivos`):

    cadastro_colaborador/colaboradores.txt   <- mestre dos colaboradores
    responsavel_convenio/alvo_card__00001ALV.txt  <- titular/substituto do
                                                       vínculo + histórico

O cadastro de colaboradores é uma lista curta, num arquivo só (como o
mestre de originadoras da Gestão). O responsável é **por vínculo**: um
arquivo por convênio × originadora, com o titular, a substituição vigente
e o histórico de auditoria.

O **responsável efetivo** é calculado em :mod:`api.domain_responsaveis` —
substituição vigente vence o titular; titular desligado vira ``Usuário
Não Cadastrado``. Desligar um colaborador não reescreve os convênios dele:
o efetivo passa a ``Usuário Não Cadastrado`` na hora, por cálculo.
"""

from __future__ import annotations

# --- stdlib ---
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

# --- locais ---
from api.arquivos import (
    EXTENSAO,
    caminho_registro,
    garantir_raiz,
    gravar_arquivo,
    ler_arquivo,
    montar_documento,
)
from api.domain import texto
from api.domain_responsaveis import (
    STATUS_COLABORADOR_VALIDOS,
    StatusColaborador,
    anexar_historico,
    responsavel_efetivo,
    validar_substituicao,
)

logger = logging.getLogger(__name__)

TABELA_COLABORADOR = 'cadastro_colaborador'
ARQUIVO_COLABORADOR = f'colaboradores{EXTENSAO}'
TABELA_RESPONSAVEL = 'responsavel_convenio'


class ColaboradorNaoEncontradoError(LookupError):
    """Sinaliza colaborador inexistente no cadastro."""


class ColaboradorInvalidoError(ValueError):
    """Sinaliza payload de colaborador reprovado pelas regras."""


class ChaveDuplicadaError(RuntimeError):
    """Sinaliza criação de colaborador cujo nome já existe."""


class SubstituicaoInvalidaError(ValueError):
    """Sinaliza substituição reprovada pelas regras puras."""


def _agora() -> str:
    """Carimbo de gravação, em ISO até os segundos."""
    return datetime.now().isoformat(timespec='seconds')


def _hoje() -> str:
    """Data de hoje em ``AAAA-MM-DD``."""
    return datetime.now().strftime('%Y-%m-%d')


# =====================================================================
# Colaboradores (mestre)
# =====================================================================
def _caminho_colaboradores(raiz: Path) -> Path:
    """Resolve o arquivo único do cadastro de colaboradores."""
    return raiz / TABELA_COLABORADOR / ARQUIVO_COLABORADOR


def _ler_colaboradores(raiz: Path) -> list[dict[str, Any]]:
    """Lê os colaboradores; lista vazia quando o cadastro não existe."""
    lido = ler_arquivo(_caminho_colaboradores(raiz))

    return list(lido[0]['registros']) if lido else []


def _gravar_colaboradores(
    raiz: Path, registros: list[Mapping[str, Any]]
) -> None:
    """Regrava o cadastro de colaboradores inteiro, de forma atômica."""
    documento = montar_documento(
        TABELA_COLABORADOR, '', '', [dict(r) for r in registros]
    )
    gravar_arquivo(_caminho_colaboradores(raiz), documento)


def listar_colaboradores(pasta_banco: Path) -> list[dict[str, Any]]:
    """Lista os colaboradores em ordem alfabética.

    Args:
        pasta_banco: Raiz do banco de arquivos.

    Returns:
        Registros de colaborador.

    Raises:
        ArmazenamentoIndisponivelError: Se a pasta do banco não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)

    return sorted(
        _ler_colaboradores(raiz),
        key=lambda c: texto(c.get('nome')).lower(),
    )


def colaboradores_ativos(pasta_banco: Path) -> set[str]:
    """Nomes de colaboradores com status ATIVO."""
    return {
        texto(c.get('nome'))
        for c in listar_colaboradores(pasta_banco)
        if texto(c.get('status')) == StatusColaborador.ATIVO.value
    }


def criar_colaborador(
    pasta_banco: Path, dados: Mapping[str, Any]
) -> dict[str, Any]:
    """Cadastra um colaborador novo (o nome é a chave e não se repete).

    Args:
        pasta_banco: Raiz do banco de arquivos.
        dados: ``nome`` obrigatório; ``status`` e ``observacao`` opcionais.

    Returns:
        O colaborador gravado.

    Raises:
        ColaboradorInvalidoError: Se o nome vier vazio.
        ChaveDuplicadaError: Se já existir colaborador com esse nome.
        ArmazenamentoIndisponivelError: Se a gravação falhar.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    nome = texto(dados.get('nome'))
    if not nome:
        raise ColaboradorInvalidoError('Informe o nome do colaborador.')

    atuais = _ler_colaboradores(raiz)
    if any(texto(c.get('nome')) == nome for c in atuais):
        raise ChaveDuplicadaError(
            f'Já existe um colaborador chamado {nome!r}.'
        )

    registro = {
        'nome': nome,
        'status': _status_valido(dados.get('status')),
        'observacao': texto(dados.get('observacao')),
        'criado_em': _agora(),
        'atualizado_em': _agora(),
    }
    _gravar_colaboradores(raiz, [*atuais, registro])
    logger.info('Colaborador criado: %s', nome)

    return registro


def atualizar_colaborador(
    pasta_banco: Path, nome: str, alteracoes: Mapping[str, Any]
) -> dict[str, Any]:
    """Atualiza status e observação de um colaborador (o nome é a chave).

    Desligar é só mudar o status para ``DESLIGADO``: os convênios do
    colaborador passam a exibir ``Usuário Não Cadastrado`` por cálculo,
    sem reescrever nada.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        nome: Nome exato do colaborador.
        alteracoes: ``status`` e/ou ``observacao``.

    Returns:
        O colaborador após a alteração.

    Raises:
        ColaboradorNaoEncontradoError: Se o nome não existe.
        ArmazenamentoIndisponivelError: Se a gravação falhar.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    atuais = _ler_colaboradores(raiz)
    anterior = next(
        (c for c in atuais if texto(c.get('nome')) == texto(nome)), None
    )
    if anterior is None:
        raise ColaboradorNaoEncontradoError(
            f'Colaborador {nome!r} não encontrado.'
        )

    registro = {
        **anterior,
        'status': _status_valido(
            alteracoes.get('status', anterior.get('status'))
        ),
        'observacao': texto(
            alteracoes.get('observacao', anterior.get('observacao'))
        ),
        'atualizado_em': _agora(),
    }
    _gravar_colaboradores(
        raiz,
        [
            registro if texto(c.get('nome')) == texto(nome) else c
            for c in atuais
        ],
    )
    logger.info('Colaborador atualizado: %s (%s)', nome, registro['status'])

    return registro


def _status_valido(valor: Any) -> str:
    """Normaliza o status; cai para ATIVO quando ausente ou inválido."""
    bruto = texto(valor).upper()

    return (
        bruto
        if bruto in STATUS_COLABORADOR_VALIDOS
        else (StatusColaborador.ATIVO.value)
    )


# =====================================================================
# Responsável por vínculo
# =====================================================================
def _ler_estado(
    raiz: Path, originador: str, numero_convenio: str
) -> dict[str, Any]:
    """Lê o responsável de um vínculo; vazio quando ausente."""
    lido = ler_arquivo(
        caminho_registro(raiz, TABELA_RESPONSAVEL, originador, numero_convenio)
    )
    if not lido:
        return {}

    registros = lido[0].get('registros') or []

    return dict(registros[0]) if registros else {}


def _gravar_estado(
    raiz: Path,
    originador: str,
    numero_convenio: str,
    registro: Mapping[str, Any],
) -> None:
    """Grava o responsável de um vínculo — um registro por arquivo."""
    gravar_arquivo(
        caminho_registro(
            raiz, TABELA_RESPONSAVEL, originador, numero_convenio
        ),
        montar_documento(
            TABELA_RESPONSAVEL, originador, numero_convenio, [dict(registro)]
        ),
    )


def obter_responsavel(
    pasta_banco: Path, originador: str, numero_convenio: str
) -> dict[str, Any]:
    """Devolve o responsável do vínculo, com o efetivo já calculado.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        originador: Originadora do vínculo.
        numero_convenio: Número do convênio naquela originadora.

    Returns:
        ``{titular, substituto, substituicao_fim, efetivo, origem,
        historico}``.

    Raises:
        ArmazenamentoIndisponivelError: Se a pasta do banco não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    estado = _ler_estado(raiz, originador, numero_convenio)
    efetivo = responsavel_efetivo(
        estado, colaboradores_ativos(pasta_banco), _hoje()
    )

    return {
        'titular': texto(estado.get('titular')),
        'substituto': texto(estado.get('substituto')),
        'substituicao_fim': texto(estado.get('substituicao_fim')),
        'efetivo': efetivo['responsavel'],
        'origem': efetivo['origem'],
        'historico': list(estado.get('historico') or []),
    }


def definir_titular(
    pasta_banco: Path,
    originador: str,
    numero_convenio: str,
    colaborador: str,
    ator: str,
) -> dict[str, Any]:
    """Define (ou troca) o titular do convênio.

    Colaborador vazio devolve o convênio a ``Usuário Não Cadastrado``.
    Colaborador informado precisa existir no cadastro.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        originador: Originadora do vínculo.
        numero_convenio: Número do convênio naquela originadora.
        colaborador: Nome do titular; vazio desassocia.
        ator: Quem fez a alteração, para auditoria.

    Returns:
        O responsável após a alteração (com efetivo calculado).

    Raises:
        ColaboradorNaoEncontradoError: Se o colaborador não existe.
        ArmazenamentoIndisponivelError: Se a gravação falhar.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    nome = texto(colaborador)
    if nome:
        _exigir_colaborador(pasta_banco, nome)

    estado = _ler_estado(raiz, originador, numero_convenio)
    historico = anexar_historico(
        estado.get('historico') or [],
        {
            'em': _agora(),
            'ator': texto(ator),
            'acao': 'titular',
            'de': texto(estado.get('titular')),
            'para': nome,
        },
    )
    _gravar_estado(
        raiz,
        originador,
        numero_convenio,
        {**estado, 'titular': nome, 'historico': historico},
    )
    logger.info('Titular de %s/%s: %s', originador, numero_convenio, nome)

    return obter_responsavel(pasta_banco, originador, numero_convenio)


def definir_substituicao(
    pasta_banco: Path,
    originador: str,
    numero_convenio: str,
    dados: Mapping[str, Any],
    ator: str,
) -> dict[str, Any]:
    """Coloca um substituto temporário; passada a data, volta ao titular.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        originador: Originadora do vínculo.
        numero_convenio: Número do convênio naquela originadora.
        dados: ``substituto`` (obrigatório) e ``substituicao_fim``
            (opcional; vazio = substituição aberta).
        ator: Quem fez a alteração, para auditoria.

    Returns:
        O responsável após a alteração.

    Raises:
        SubstituicaoInvalidaError: Se o payload for reprovado.
        ColaboradorNaoEncontradoError: Se o substituto não existe.
        ArmazenamentoIndisponivelError: Se a gravação falhar.

    Example:
        >>> ...  # doctest: +SKIP
    """
    erros = validar_substituicao(dados)
    if erros:
        raise SubstituicaoInvalidaError(' '.join(erros))

    raiz = garantir_raiz(pasta_banco)
    substituto = texto(dados.get('substituto'))
    _exigir_colaborador(pasta_banco, substituto)
    fim = texto(dados.get('substituicao_fim'))

    estado = _ler_estado(raiz, originador, numero_convenio)
    historico = anexar_historico(
        estado.get('historico') or [],
        {
            'em': _agora(),
            'ator': texto(ator),
            'acao': 'substituicao',
            'para': substituto,
            'ate': fim,
        },
    )
    _gravar_estado(
        raiz,
        originador,
        numero_convenio,
        {
            **estado,
            'substituto': substituto,
            'substituicao_fim': fim,
            'historico': historico,
        },
    )
    logger.info(
        'Substituto de %s/%s: %s (até %s)',
        originador,
        numero_convenio,
        substituto,
        fim or 'aberto',
    )

    return obter_responsavel(pasta_banco, originador, numero_convenio)


def encerrar_substituicao(
    pasta_banco: Path,
    originador: str,
    numero_convenio: str,
    ator: str,
) -> dict[str, Any]:
    """Encerra a substituição na hora, devolvendo a carteira ao titular.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        originador: Originadora do vínculo.
        numero_convenio: Número do convênio naquela originadora.
        ator: Quem fez a alteração, para auditoria.

    Returns:
        O responsável após encerrar a substituição.

    Raises:
        ArmazenamentoIndisponivelError: Se a gravação falhar.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    estado = _ler_estado(raiz, originador, numero_convenio)
    historico = anexar_historico(
        estado.get('historico') or [],
        {
            'em': _agora(),
            'ator': texto(ator),
            'acao': 'encerrar_substituicao',
            'de': texto(estado.get('substituto')),
        },
    )
    _gravar_estado(
        raiz,
        originador,
        numero_convenio,
        {
            **estado,
            'substituto': '',
            'substituicao_fim': '',
            'historico': historico,
        },
    )
    logger.info('Substituição encerrada em %s/%s', originador, numero_convenio)

    return obter_responsavel(pasta_banco, originador, numero_convenio)


def _exigir_colaborador(pasta_banco: Path, nome: str) -> None:
    """Barra vínculo com colaborador que não existe no cadastro."""
    existe = any(
        texto(c.get('nome')) == texto(nome)
        for c in listar_colaboradores(pasta_banco)
    )
    if not existe:
        raise ColaboradorNaoEncontradoError(
            f'Colaborador {nome!r} não encontrado. Cadastre-o antes.'
        )
