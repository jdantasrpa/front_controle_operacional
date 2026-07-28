# INSERIR EM: api/repositories/remessas.py
"""Persistência do rastreio de envio de remessa por vencimento.

Grava na árvore de arquivos do painel (:mod:`api.arquivos`) a tabela
``remessa_vencimento`` — pasta = tabela, subpasta = competência, um
``.txt`` por convênio, com um registro por vencimento (``data_vencimento``).

A lista de vencimentos vem da conciliação (``tabela_concilicacao_convenio``):
a remessa acompanha os vencimentos que já existem, sem inventar nenhum. A
*regra* de envio (dias antes da remessa, SLA, corte) fica no controle da
gerência — aqui é só situação (pendente/enviada), data de envio, usuário e
observação, com auditoria.
"""

from __future__ import annotations

# --- stdlib ---
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

# --- locais ---
from api.arquivos import (
    caminho_registro,
    garantir_raiz,
    gravar_arquivo,
    ler_arquivo,
    montar_documento,
)
from api.domain import numero, texto
from api.domain_remessas import (
    montar_registro,
    situacao_normalizada,
    validar_remessa,
)

logger = logging.getLogger(__name__)

TABELA_REMESSA = 'remessa_vencimento'
TABELA_CONCILIACAO = 'tabela_concilicacao_convenio'


class RemessaInvalidaError(ValueError):
    """Sinaliza payload de envio reprovado pelas regras puras."""


class VencimentoNaoEncontradoError(LookupError):
    """Sinaliza envio para um vencimento que não existe na competência."""


def _agora() -> str:
    """Carimbo de gravação, em ISO até os segundos."""
    return datetime.now().isoformat(timespec='seconds')


def _ler_remessas(
    raiz: Path, originador: str, numero_convenio: str, competencia: str
) -> list[dict[str, Any]]:
    """Lê os registros de envio de um convênio numa competência."""
    lido = ler_arquivo(
        caminho_registro(
            raiz, TABELA_REMESSA, originador, numero_convenio, competencia
        )
    )

    return list(lido[0]['registros']) if lido else []


def _gravar_remessas(
    raiz: Path,
    originador: str,
    numero_convenio: str,
    competencia: str,
    registros: list[Mapping[str, Any]],
) -> None:
    """Grava os registros de envio de um convênio numa competência."""
    gravar_arquivo(
        caminho_registro(
            raiz, TABELA_REMESSA, originador, numero_convenio, competencia
        ),
        montar_documento(
            TABELA_REMESSA,
            originador,
            numero_convenio,
            [dict(r) for r in registros],
            competencia,
        ),
    )


def _vencimentos(
    raiz: Path, originador: str, numero_convenio: str, competencia: str
) -> list[dict[str, Any]]:
    """Lê os vencimentos da conciliação para a competência."""
    lido = ler_arquivo(
        caminho_registro(
            raiz, TABELA_CONCILIACAO, originador, numero_convenio, competencia
        )
    )

    return list(lido[0]['registros']) if lido else []


def listar_remessas(
    pasta_banco: Path,
    originador: str,
    numero_convenio: str,
    competencia: str,
) -> list[dict[str, Any]]:
    """Lista os vencimentos da competência com o status de envio.

    Um item por vencimento existente na conciliação, com a situação da
    remessa (pendente por padrão) e a auditoria do envio.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        originador: Originadora do convênio.
        numero_convenio: Número do convênio naquela originadora.
        competencia: Competência ``AAAA-MM``.

    Returns:
        Linhas ordenadas por data de vencimento.

    Raises:
        ArmazenamentoIndisponivelError: Se a pasta do banco não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    estado = {
        texto(r.get('data_vencimento')): r
        for r in _ler_remessas(raiz, originador, numero_convenio, competencia)
    }
    vencimentos = _vencimentos(raiz, originador, numero_convenio, competencia)

    linhas = [_montar_linha(v, estado) for v in vencimentos]

    return sorted(linhas, key=lambda linha: linha['data_vencimento'])


def _montar_linha(
    vencimento: Mapping[str, Any], estado: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """Junta um vencimento da conciliação com o seu status de remessa."""
    data = texto(vencimento.get('data_vencimento'))
    registro = estado.get(data, {})

    return {
        'data_vencimento': data,
        'valor_remessa': numero(vencimento.get('valor_remessa')),
        'situacao': situacao_normalizada(registro.get('situacao')),
        'data_envio': texto(registro.get('data_envio')),
        'usuario': texto(registro.get('usuario')),
        'observacao': texto(registro.get('observacao')),
        'atualizado_em': texto(registro.get('atualizado_em')),
    }


def registrar_envio(
    pasta_banco: Path,
    originador: str,
    numero_convenio: str,
    competencia: str,
    data_vencimento: str,
    dados: Mapping[str, Any],
    ator: str,
) -> dict[str, Any]:
    """Registra (ou atualiza) a situação de envio de um vencimento.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        originador: Originadora do convênio.
        numero_convenio: Número do convênio naquela originadora.
        competencia: Competência ``AAAA-MM``.
        data_vencimento: Vencimento ``AAAA-MM-DD`` a marcar.
        dados: ``situacao``, ``data_envio`` e ``observacao``.
        ator: Usuário responsável pelo envio/edição (auditoria).

    Returns:
        O registro de envio gravado.

    Raises:
        RemessaInvalidaError: Se o payload for reprovado.
        VencimentoNaoEncontradoError: Se o vencimento não existe na
            competência.
        ArmazenamentoIndisponivelError: Se a gravação falhar.

    Example:
        >>> ...  # doctest: +SKIP
    """
    erros = validar_remessa(dados)
    if erros:
        raise RemessaInvalidaError(' '.join(erros))

    raiz = garantir_raiz(pasta_banco)
    _exigir_vencimento(
        raiz, originador, numero_convenio, competencia, data_vencimento
    )

    registro = montar_registro(dados, data_vencimento, ator, _agora())
    atuais = _ler_remessas(raiz, originador, numero_convenio, competencia)
    _gravar_remessas(
        raiz,
        originador,
        numero_convenio,
        competencia,
        _substituir_por_data(atuais, registro),
    )
    logger.info(
        'Remessa %s/%s %s: %s',
        originador,
        numero_convenio,
        data_vencimento,
        registro['situacao'],
    )

    return registro


def _exigir_vencimento(
    raiz: Path,
    originador: str,
    numero_convenio: str,
    competencia: str,
    data_vencimento: str,
) -> None:
    """Barra envio para vencimento que não existe na conciliação."""
    datas = {
        texto(v.get('data_vencimento'))
        for v in _vencimentos(raiz, originador, numero_convenio, competencia)
    }
    if texto(data_vencimento) not in datas:
        raise VencimentoNaoEncontradoError(
            f'Vencimento {data_vencimento} não existe na competência '
            f'{competencia} de {originador} / {numero_convenio}.'
        )


def _substituir_por_data(
    registros: list[Mapping[str, Any]], novo: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Troca o registro do mesmo vencimento, ou acrescenta o novo."""
    data = texto(novo.get('data_vencimento'))
    existe = any(texto(r.get('data_vencimento')) == data for r in registros)
    trocados = [
        dict(novo) if texto(r.get('data_vencimento')) == data else dict(r)
        for r in registros
    ]

    return trocados if existe else [*trocados, dict(novo)]
