# INSERIR EM: api/repositories/conciliacao_gerencia.py
"""Persistência do estado de gerência de convênios pela Conciliação.

Grava na árvore de arquivos do painel (:mod:`api.arquivos`) uma tabela
nova, separada do cadastro da Gestão de Convênios::

    gerencia_conciliacao_convenio/
        alvo_card__00001ALV.txt   <- estado da Conciliação para o vínculo

Um arquivo por vínculo, chaveado pelo par ``(originadora, número)`` —
mesmo esquema de nome do resto do painel. Mantê-lo **fora** do arquivo do
vínculo (``gestao_convenios_originador``) é de propósito: a Gestão origina
o convênio e a Conciliação governa a saúde dele; cada uma escreve no seu
próprio lugar, e desligar na Conciliação nunca altera o cadastro da
Gestão.

As regras puras ficam em :mod:`api.domain_conciliacao_gerencia`; aqui há
leitura, gravação e a junção com o cadastro de vínculos da Gestão.
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
    listar_documentos,
    montar_documento,
)
from api.domain import texto
from api.domain_conciliacao_gerencia import (
    CAMPO_DIA_VENCIMENTO,
    CAMPO_DIAS_ANTES_CORTE,
    CAMPO_DIAS_ANTES_REMESSA,
    CAMPO_QTD_DIAS_SLA,
    aplicar_estado,
    esta_ligado,
    validar_estado,
)
from api.domain_convenios import (
    StatusRegistro,
    cnpj_formatado,
    esta_vigente,
    normalizar_cnpj,
)
from api.repositories import convenios as repo_convenios

logger = logging.getLogger(__name__)

TABELA_GERENCIA = 'gerencia_conciliacao_convenio'

# Estado por originadora (o "grupo master"): lista curta, cabe num arquivo
# só, como o mestre de originadoras da Gestão.
TABELA_GERENCIA_ORIGINADORA = 'gerencia_conciliacao_originadora'
ARQUIVO_ORIGINADORA = f'originadoras{EXTENSAO}'


class VinculoNaoEncontradoError(LookupError):
    """Sinaliza estado pedido para um vínculo que não existe."""


class OriginadoraNaoEncontradaError(LookupError):
    """Sinaliza estado pedido para uma originadora desconhecida."""


class EstadoInvalidoError(ValueError):
    """Sinaliza estado reprovado pelas regras de :mod:`domain`."""


# =====================================================================
# Carimbos de tempo
# =====================================================================
def _agora() -> str:
    """Carimbo de gravação, em ISO até os segundos."""
    return datetime.now().isoformat(timespec='seconds')


def _competencia_de_hoje() -> str:
    """Competência ``AAAA-MM`` do mês corrente."""
    return datetime.now().strftime('%Y-%m')


# =====================================================================
# Leitura e gravação do estado
# =====================================================================
def _ler_estado(
    raiz: Path, originador: str, numero_convenio: str
) -> dict[str, Any]:
    """Lê o estado da Conciliação de um vínculo; vazio quando ausente."""
    lido = ler_arquivo(
        caminho_registro(raiz, TABELA_GERENCIA, originador, numero_convenio)
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
    """Grava o estado da Conciliação de um vínculo — um registro por arquivo."""
    gravar_arquivo(
        caminho_registro(raiz, TABELA_GERENCIA, originador, numero_convenio),
        montar_documento(
            TABELA_GERENCIA, originador, numero_convenio, [dict(registro)]
        ),
    )


# =====================================================================
# Filtro da geração (o que a mesa desligou)
# =====================================================================
def chaves_desligadas(pasta_banco: Path) -> set[tuple[str, str]]:
    """Pares ``(originadora, número)`` desligados na Conciliação.

    É o filtro que a geração de competência usa para pular o que a mesa
    desligou. Só entram os que têm registro **explícito** de desligamento —
    ausência conta como ligado.

    Args:
        pasta_banco: Raiz do banco de arquivos.

    Returns:
        Conjunto de pares desligados; vazio quando ninguém desligou nada.

    Raises:
        ArmazenamentoIndisponivelError: Se a pasta do banco não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)

    return {
        (
            texto(documento.get('originador')),
            texto(documento.get('numero_convenio')),
        )
        for documento in listar_documentos(raiz, TABELA_GERENCIA)
        for registro in documento.get('registros') or []
        if not esta_ligado(registro)
    }


def controles_vencimento(
    pasta_banco: Path,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Controle de vencimento definido por vínculo, para alimentar a geração.

    Só entram os vínculos com **dia** cadastrado — os demais caem no
    caminho de clonagem do mês anterior. Alterar o controle aqui vale para
    as competências novas; as já geradas são preservadas pela idempotência.

    Args:
        pasta_banco: Raiz do banco de arquivos.

    Returns:
        Mapa ``(originadora, número) -> {dia_vencimento, dias_antes_remessa,
        qtd_dias_sla_pagamento, dias_antes_corte}``.

    Raises:
        ArmazenamentoIndisponivelError: Se a pasta do banco não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)

    return {
        (
            texto(documento.get('originador')),
            texto(documento.get('numero_convenio')),
        ): {
            'dia_vencimento': int(registro.get(CAMPO_DIA_VENCIMENTO)),
            'dias_antes_remessa': registro.get(CAMPO_DIAS_ANTES_REMESSA, ''),
            'qtd_dias_sla_pagamento': registro.get(CAMPO_QTD_DIAS_SLA, ''),
            'dias_antes_corte': registro.get(CAMPO_DIAS_ANTES_CORTE, ''),
        }
        for documento in listar_documentos(raiz, TABELA_GERENCIA)
        for registro in documento.get('registros') or []
        if str(registro.get(CAMPO_DIA_VENCIMENTO, '')).isdigit()
    }


# =====================================================================
# Visão de gerência (vínculos × estado)
# =====================================================================
def listar_gerencia(
    pasta_banco: Path, competencia: str = ''
) -> list[dict[str, Any]]:
    """Lista os convênios em conciliação com o estado próprio da mesa.

    Uma linha por vínculo convênio × originadora, juntando o que a Gestão
    cadastrou (identidade, data de cadastro, vigência) com o que a
    Conciliação governa (ligado/desligado, primeiro vencimento).

    Args:
        pasta_banco: Raiz do banco de arquivos.
        competencia: Competência ``AAAA-MM`` para avaliar a vigência;
            vazio usa o mês corrente.

    Returns:
        Linhas ordenadas por nome do convênio e originadora.

    Raises:
        ArmazenamentoIndisponivelError: Se a pasta do banco não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    referencia = competencia or _competencia_de_hoje()
    mestre = {
        texto(convenio.get('cnpj_chave')): convenio
        for convenio in repo_convenios.listar_convenios(
            pasta_banco, referencia
        )
    }

    linhas = [
        _montar_linha(raiz, vinculo, referencia, mestre)
        for vinculo in repo_convenios.listar_vinculos(pasta_banco)
    ]

    return sorted(
        linhas,
        key=lambda linha: (
            texto(linha['nome_convenio']).lower(),
            texto(linha['originador']).lower(),
        ),
    )


def _montar_linha(
    raiz: Path,
    vinculo: Mapping[str, Any],
    competencia: str,
    mestre: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Monta uma linha da gerência juntando o vínculo com o seu estado."""
    originador = texto(vinculo.get('originador'))
    numero_convenio = texto(vinculo.get('numero_convenio'))
    estado = _ler_estado(raiz, originador, numero_convenio)
    convenio = mestre.get(normalizar_cnpj(vinculo.get('cnpj_convenio')), {})
    gestao = _info_gestao(vinculo, convenio)

    return {
        'originador': originador,
        'numero_convenio': numero_convenio,
        'nome_convenio': texto(vinculo.get('nome_convenio')),
        'cnpj_convenio': cnpj_formatado(vinculo.get('cnpj_convenio')),
        'averbadora': texto(vinculo.get('averbadora')),
        'cadastrado_em': texto(vinculo.get('criado_em')),
        'vigente': esta_vigente(vinculo, competencia),
        'em_conciliacao_ativa': esta_ligado(estado),
        'dia_vencimento': estado.get(CAMPO_DIA_VENCIMENTO, ''),
        'dias_antes_remessa': estado.get(CAMPO_DIAS_ANTES_REMESSA, ''),
        'qtd_dias_sla_pagamento': estado.get(CAMPO_QTD_DIAS_SLA, ''),
        'dias_antes_corte': estado.get(CAMPO_DIAS_ANTES_CORTE, ''),
        'status_gestao': gestao['status'],
        'motivo_gestao': gestao['motivo'],
        'nivel_gestao': gestao['nivel'],
    }


def _info_gestao(
    vinculo: Mapping[str, Any], convenio: Mapping[str, Any]
) -> dict[str, str]:
    """Extrai o status da Gestão e o motivo da inativação, só para leitura.

    Os dois status (Gestão × Conciliação) são independentes — nenhum
    aciona o outro. Mas quando a Gestão inativa, a mesa precisa saber o
    porquê: o motivo é a observação do registro inativado. A inativação do
    convênio (mestre) tem prioridade sobre a do vínculo, por ser mais
    ampla.

    Args:
        vinculo: Registro do vínculo (traz status e observação da Gestão).
        convenio: Registro do convênio mestre correspondente (idem).

    Returns:
        ``{status, motivo, nivel}`` — ``nivel`` diz onde a inativação
        ocorreu (``convênio`` ou ``vínculo``); vazio quando ativo.
    """
    inativo = StatusRegistro.INATIVO.value

    if texto(convenio.get('status')) == inativo:
        return {
            'status': inativo,
            'motivo': texto(convenio.get('observacao')),
            'nivel': 'convênio',
        }
    if texto(vinculo.get('status')) == inativo:
        return {
            'status': inativo,
            'motivo': texto(vinculo.get('observacao')),
            'nivel': 'vínculo',
        }

    return {'status': StatusRegistro.ATIVO.value, 'motivo': '', 'nivel': ''}


def atualizar_estado(
    pasta_banco: Path,
    originador: str,
    numero_convenio: str,
    alteracoes: Mapping[str, Any],
    ator: str,
) -> dict[str, Any]:
    """Liga/desliga um vínculo ou registra o primeiro vencimento.

    A alteração é parcial: o front manda só o que mudou (o toggle ou a
    data). O estado só existe para vínculo já cadastrado pela Gestão —
    estado órfão não faria sentido na conciliação.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        originador: Originadora do vínculo.
        numero_convenio: Número do convênio naquela originadora.
        alteracoes: Campos a alterar (``em_conciliacao_ativa`` e/ou
            ``primeiro_vencimento``).
        ator: Quem fez a alteração, para auditoria.

    Returns:
        O estado gravado, com os carimbos de auditoria.

    Raises:
        VinculoNaoEncontradoError: Se o vínculo não existe.
        EstadoInvalidoError: Se o primeiro vencimento for inválido.
        ArmazenamentoIndisponivelError: Se a gravação falhar.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    if not repo_convenios.vinculo_existe(
        pasta_banco, originador, numero_convenio
    ):
        raise VinculoNaoEncontradoError(
            f'Vínculo {originador} / {numero_convenio} não encontrado.'
        )

    atual = _ler_estado(raiz, originador, numero_convenio)
    novo = aplicar_estado(atual, alteracoes)

    erros = validar_estado(novo)
    if erros:
        raise EstadoInvalidoError(' '.join(erros))

    registro = {
        'originador': originador,
        'numero_convenio': numero_convenio,
        **novo,
        'atualizado_em': _agora(),
        'ator': texto(ator),
    }
    _gravar_estado(raiz, originador, numero_convenio, registro)
    logger.info(
        'Estado de conciliação atualizado: %s/%s (ativa=%s)',
        originador,
        numero_convenio,
        registro['em_conciliacao_ativa'],
    )

    return registro


# =====================================================================
# Originadoras — o "grupo master" acima dos convênios
# =====================================================================
# A originadora agrupa convênios. Ativá-la/desativá-la é um gate acima do
# liga/desliga de cada convênio: originadora desativada não gera nenhum
# convênio dela, independentemente do toggle individual. É um estado
# próprio da Conciliação — separado do status do cadastro da Gestão.
def _caminho_originadoras(raiz: Path) -> Path:
    """Resolve o arquivo único de estado das originadoras."""
    return raiz / TABELA_GERENCIA_ORIGINADORA / ARQUIVO_ORIGINADORA


def _ler_estado_originadoras(raiz: Path) -> dict[str, dict[str, Any]]:
    """Indexa o estado de cada originadora pelo nome; vazio quando ausente."""
    lido = ler_arquivo(_caminho_originadoras(raiz))
    registros = (lido[0].get('registros') or []) if lido else []

    return {
        texto(registro.get('nome')): dict(registro)
        for registro in registros
        if texto(registro.get('nome'))
    }


def _gravar_estado_originadoras(
    raiz: Path, registros: list[Mapping[str, Any]]
) -> None:
    """Regrava o arquivo único de estado das originadoras, de forma atômica."""
    documento = montar_documento(
        TABELA_GERENCIA_ORIGINADORA, '', '', [dict(r) for r in registros]
    )
    gravar_arquivo(_caminho_originadoras(raiz), documento)


def originadoras_desativadas(pasta_banco: Path) -> set[str]:
    """Nomes de originadoras desativadas na Conciliação.

    É o gate de grupo master da geração: nenhum convênio de uma
    originadora nesta lista entra na geração. Ausência de registro conta
    como ativa.

    Args:
        pasta_banco: Raiz do banco de arquivos.

    Returns:
        Conjunto de nomes desativados; vazio quando ninguém desativou nada.

    Raises:
        ArmazenamentoIndisponivelError: Se a pasta do banco não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)

    return {
        nome
        for nome, estado in _ler_estado_originadoras(raiz).items()
        if not esta_ligado(estado)
    }


def listar_originadoras_gerencia(
    pasta_banco: Path, competencia: str = ''
) -> list[dict[str, Any]]:
    """Lista as originadoras com o estado da mesa e a contagem de convênios.

    Uma linha por originadora que opera algum convênio, com o ativo/inativo
    próprio da Conciliação e quantos convênios ela tem — no total, ligados
    e vigentes na competência. É a visão de grupo master.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        competencia: Competência ``AAAA-MM`` para avaliar a vigência;
            vazio usa o mês corrente.

    Returns:
        Linhas ordenadas por nome da originadora.

    Raises:
        ArmazenamentoIndisponivelError: Se a pasta do banco não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    referencia = competencia or _competencia_de_hoje()
    estados = _ler_estado_originadoras(raiz)

    grupos: dict[str, list[dict[str, Any]]] = {}
    for vinculo in repo_convenios.listar_vinculos(pasta_banco):
        grupos.setdefault(texto(vinculo.get('originador')), []).append(vinculo)

    linhas = [
        _montar_linha_originadora(
            raiz, nome, grupo, estados.get(nome, {}), referencia
        )
        for nome, grupo in grupos.items()
    ]

    return sorted(linhas, key=lambda linha: texto(linha['originador']).lower())


def _montar_linha_originadora(
    raiz: Path,
    nome: str,
    vinculos: list[Mapping[str, Any]],
    estado: Mapping[str, Any],
    competencia: str,
) -> dict[str, Any]:
    """Monta a linha de uma originadora com as contagens dos convênios dela."""
    vigentes = [v for v in vinculos if esta_vigente(v, competencia)]
    ligados = [
        v
        for v in vinculos
        if esta_ligado(
            _ler_estado(
                raiz,
                texto(v.get('originador')),
                texto(v.get('numero_convenio')),
            )
        )
    ]

    return {
        'originador': nome,
        'em_conciliacao_ativa': esta_ligado(estado),
        'total_convenios': len(vinculos),
        'total_vigentes': len(vigentes),
        'total_ligados': len(ligados),
    }


def atualizar_estado_originadora(
    pasta_banco: Path, nome: str, ativa: bool, ator: str
) -> dict[str, Any]:
    """Ativa ou desativa uma originadora inteira na Conciliação.

    Desativar é o gate de grupo master: para toda a geração dos convênios
    dela sem mexer no toggle de cada um — religar a originadora devolve
    cada convênio ao estado individual que ele já tinha.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        nome: Nome exato da originadora.
        ativa: Novo estado (``True`` liga, ``False`` desliga).
        ator: Quem fez a alteração, para auditoria.

    Returns:
        O estado gravado, com os carimbos de auditoria.

    Raises:
        OriginadoraNaoEncontradaError: Se a originadora não existir.
        ArmazenamentoIndisponivelError: Se a gravação falhar.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    if not _originadora_conhecida(pasta_banco, nome):
        raise OriginadoraNaoEncontradaError(
            f'Originadora {nome!r} não encontrada.'
        )

    estados = _ler_estado_originadoras(raiz)
    registro = {
        'nome': texto(nome),
        'em_conciliacao_ativa': bool(ativa),
        'atualizado_em': _agora(),
        'ator': texto(ator),
    }
    estados[texto(nome)] = registro
    _gravar_estado_originadoras(raiz, list(estados.values()))
    logger.info(
        'Originadora %s %s na conciliação.',
        nome,
        'ativada' if ativa else 'desativada',
    )

    return registro


def _originadora_conhecida(pasta_banco: Path, nome: str) -> bool:
    """Diz se a originadora existe no cadastro ou nos vínculos da Gestão."""
    alvo = texto(nome)

    return any(
        texto(originadora.get('nome')) == alvo
        for originadora in repo_convenios.listar_originadoras(pasta_banco)
    )
