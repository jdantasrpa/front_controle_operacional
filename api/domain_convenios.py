# INSERIR EM: api/domain_convenios.py
"""Regras puras da gestão de convênios, originadoras e custos.

Três conceitos, nesta ordem de dependência:

* **Convênio** — identidade canônica do órgão conveniado. A chave é o
  **CNPJ**, não o número: cada originadora numera o mesmo convênio do seu
  jeito (``00001ALV`` na Alvo Card, ``00061HTC`` na Hatchbank), então o
  número não serve para reconhecer que é o mesmo convênio.
* **Vínculo** — o par ``(originadora, numero_convenio)``. É aqui que mora
  a vigência: um convênio pode estar ativo numa originadora e encerrado
  em outra, e isso muda mês a mês.
* **Custo** — a regra de remuneração daquele vínculo. Vale um custo por
  competência, mas as versões anteriores ficam guardadas: recalcular
  08/2025 tem que usar o custo que valia em 08/2025.

Competência circula aqui sempre como ``AAAA-MM`` — mesmo formato das
pastas do banco de arquivos, que assim ordena sozinho. A conversão para
``MM/AAAA`` da tela fica em :mod:`api.domain`.

**Chaves são imutáveis.** Depois de cadastrado, nem o CNPJ do convênio,
nem o nome da originadora, nem o par ``(originadora, numero_convenio)``
podem ser alterados. Não é preciosismo: no banco de arquivos essa chave
*é o nome do arquivo* (``alvo_card__00001ALV.txt``). Editá-la não
renomearia o registro — criaria um segundo, deixando para trás o vínculo
original e todo o histórico de custo dele, sem ninguém perceber. Errou a
chave? Exclui e cadastra de novo; o resto dos campos edita à vontade.

Este módulo não faz I/O: tudo é função pura sobre dicionários.
"""

from __future__ import annotations

# --- stdlib ---
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

# --- locais ---
from api.domain import numero, texto

PADRAO_COMPETENCIA_ISO = re.compile(r'^(\d{4})-(0[1-9]|1[0-2])$')
PADRAO_CNPJ = re.compile(r'\D+')

TAMANHO_CNPJ = 14
MESES_NO_ANO = 12
CEM_PORCENTO = 100.0


class MetodoCusto(str, Enum):
    """Formas de apurar o custo de um vínculo convênio × originadora."""

    PERCENTUAL = 'PERCENTUAL'
    FIXO_MENSAL = 'FIXO_MENSAL'
    POR_CONTRATO = 'POR_CONTRATO'
    FAIXA = 'FAIXA'


class BaseCalculo(str, Enum):
    """Valor da conciliação sobre o qual o percentual incide."""

    VALOR_REMESSA = 'VALOR_REMESSA'
    VALOR_RETORNO = 'VALOR_RETORNO'
    VALOR_REPASSE = 'VALOR_REPASSE'


class CriterioFaixa(str, Enum):
    """O que define em qual faixa a competência caiu."""

    QUANTIDADE = 'QUANTIDADE'
    VALOR = 'VALOR'


class StatusRegistro(str, Enum):
    """Situação de um cadastro (convênio, originadora ou vínculo)."""

    ATIVO = 'ATIVO'
    INATIVO = 'INATIVO'


METODOS_VALIDOS = tuple(item.value for item in MetodoCusto)
BASES_VALIDAS = tuple(item.value for item in BaseCalculo)
CRITERIOS_VALIDOS = tuple(item.value for item in CriterioFaixa)
STATUS_VALIDOS = tuple(item.value for item in StatusRegistro)

# Faixa sem teto: o último degrau da tabela vale para todo o resto.
SEM_TETO = 0.0


@dataclass(frozen=True)
class BaseApuracao:
    """Números da competência que alimentam o cálculo do custo.

    Attributes:
        valor_remessa: Total enviado ao convênio na competência.
        valor_retorno: Total efetivamente descontado em folha.
        valor_repasse: Total repassado pelo convênio à originadora.
        quantidade_contratos: Contratos/parcelas descontados no mês.
    """

    valor_remessa: float = 0.0
    valor_retorno: float = 0.0
    valor_repasse: float = 0.0
    quantidade_contratos: int = 0


# =====================================================================
# Identidade
# =====================================================================
def normalizar_cnpj(valor: Any) -> str:
    """Reduz um CNPJ aos seus dígitos, para servir de chave.

    Args:
        valor: CNPJ em qualquer formatação.

    Returns:
        Apenas os dígitos; string vazia quando não há nada aproveitável.

    Example:
        >>> normalizar_cnpj('00.394.429/0082-76')
        '00394429008276'
        >>> normalizar_cnpj(None)
        ''
    """
    return PADRAO_CNPJ.sub('', texto(valor))


def cnpj_formatado(valor: Any) -> str:
    """Devolve o CNPJ na máscara brasileira, quando possível.

    Args:
        valor: CNPJ com ou sem máscara.

    Returns:
        ``00.000.000/0000-00``; o valor original se não tiver 14 dígitos.

    Example:
        >>> cnpj_formatado('00394429008276')
        '00.394.429/0082-76'
        >>> cnpj_formatado('123')
        '123'
    """
    digitos = normalizar_cnpj(valor)
    if len(digitos) != TAMANHO_CNPJ:
        return texto(valor)

    return (
        f'{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}'
        f'/{digitos[8:12]}-{digitos[12:]}'
    )


CHAVE_CONVENIO = ('cnpj_convenio',)
CHAVE_ORIGINADORA = ('nome',)
CHAVE_VINCULO = ('originador', 'numero_convenio', 'cnpj_convenio')

# Campos comparados como CNPJ (só os dígitos importam) na hora de dizer
# se a chave mudou: '00394429008276' e '00.394.429/0082-76' são o mesmo.
CAMPOS_CNPJ = ('cnpj_convenio', 'cnpj')


def chave_vinculo(originador: Any, numero_convenio: Any) -> str:
    """Monta a chave de um vínculo convênio × originadora.

    Args:
        originador: Originadora dona do vínculo.
        numero_convenio: Número do convênio naquela originadora.

    Returns:
        Chave ``originadora|numero``, estável para indexar dicionários.

    Example:
        >>> chave_vinculo('Alvo Card', '00001ALV')
        'Alvo Card|00001ALV'
    """
    return f'{texto(originador)}|{texto(numero_convenio)}'


# =====================================================================
# Imutabilidade da chave
# =====================================================================
def _mesmo_valor(campo: str, atual: Any, novo: Any) -> bool:
    """Compara dois valores de um campo de chave, tolerando formatação."""
    if campo in CAMPOS_CNPJ:
        return normalizar_cnpj(atual) == normalizar_cnpj(novo)

    return texto(atual) == texto(novo)


def violacoes_de_chave(
    atual: Mapping[str, Any],
    alteracoes: Mapping[str, Any],
    campos_chave: tuple[str, ...],
) -> list[str]:
    """Aponta quais campos de chave a alteração tentaria mudar.

    Campo ausente ou vazio no payload não conta como tentativa: um
    formulário que não mostra a chave simplesmente não a envia.

    Args:
        atual: Registro como está gravado.
        alteracoes: Campos que o usuário quer alterar.
        campos_chave: Campos que formam a identidade do registro.

    Returns:
        Mensagens de erro; lista vazia quando nenhuma chave foi tocada.

    Example:
        >>> atual = {'originador': 'Alvo Card', 'numero_convenio': '1'}
        >>> violacoes_de_chave(atual, {'numero_convenio': '2'},
        ...                    ('originador', 'numero_convenio'))
        ["O campo 'numero_convenio' é a chave do registro e não pode ser alterado (gravado: '1')."]
        >>> violacoes_de_chave(atual, {'averbadora': 'Zetra'},
        ...                    ('originador', 'numero_convenio'))
        []
    """
    return [
        f'O campo {campo!r} é a chave do registro e não pode ser '
        f'alterado (gravado: {texto(atual.get(campo))!r}).'
        for campo in campos_chave
        if texto(alteracoes.get(campo))
        and not _mesmo_valor(campo, atual.get(campo), alteracoes.get(campo))
    ]


def aplicar_alteracao(
    atual: Mapping[str, Any],
    alteracoes: Mapping[str, Any],
    campos_chave: tuple[str, ...],
) -> dict[str, Any]:
    """Aplica alterações sobre um registro, blindando os campos de chave.

    A chave é copiada do registro gravado, nunca do payload: mesmo que a
    validação deixe passar, o que vai para o disco continua sendo a
    identidade original.

    Args:
        atual: Registro como está gravado.
        alteracoes: Campos a atualizar.
        campos_chave: Campos que formam a identidade do registro.

    Returns:
        Novo registro — nem ``atual`` nem ``alteracoes`` são modificados.

    Example:
        >>> atual = {'originador': 'Alvo Card', 'averbadora': 'Zetra'}
        >>> aplicar_alteracao(atual, {'originador': 'X', 'averbadora': 'E-'},
        ...                   ('originador',))
        {'originador': 'Alvo Card', 'averbadora': 'E-'}
    """
    return {
        **atual,
        **alteracoes,
        **{
            campo: atual.get(campo) for campo in campos_chave if campo in atual
        },
    }


# =====================================================================
# Competência e vigência
# =====================================================================
def competencia_valida(competencia: Any) -> bool:
    """Diz se a competência está no formato ``AAAA-MM``.

    Args:
        competencia: Valor informado pelo usuário.

    Returns:
        True quando casa com ``AAAA-MM`` e o mês está entre 01 e 12.

    Example:
        >>> competencia_valida('2026-07'), competencia_valida('07/2026')
        (True, False)
        >>> competencia_valida('2026-13')
        False
    """
    return bool(PADRAO_COMPETENCIA_ISO.match(texto(competencia)))


def deslocar_competencia(competencia: str, meses: int) -> str:
    """Anda meses para frente ou para trás numa competência.

    Args:
        competencia: Competência ``AAAA-MM`` de partida.
        meses: Deslocamento; negativo anda para trás.

    Returns:
        Nova competência ``AAAA-MM``; vazio se a entrada for inválida.

    Example:
        >>> deslocar_competencia('2026-01', -1)
        '2025-12'
        >>> deslocar_competencia('2025-12', 1)
        '2026-01'
    """
    casamento = PADRAO_COMPETENCIA_ISO.match(texto(competencia))
    if not casamento:
        return ''

    ano, mes = int(casamento.group(1)), int(casamento.group(2))
    total = ano * MESES_NO_ANO + (mes - 1) + meses

    return f'{total // MESES_NO_ANO:04d}-{total % MESES_NO_ANO + 1:02d}'


def esta_vigente(registro: Mapping[str, Any], competencia: str) -> bool:
    """Diz se um registro com vigência vale numa competência.

    Vigência aberta (``competencia_fim`` vazio) vale para sempre, e
    ``competencia_inicio`` vazio vale desde sempre — é o que faz os
    vínculos antigos, gravados antes deste módulo, continuarem
    aparecendo em vez de sumirem da conciliação.

    Args:
        registro: Registro com ``competencia_inicio``/``competencia_fim``
            e, opcionalmente, ``status``.
        competencia: Competência ``AAAA-MM`` consultada.

    Returns:
        True quando o registro está ativo e dentro da janela.

    Example:
        >>> vinculo = {'competencia_inicio': '2025-01',
        ...            'competencia_fim': '2025-06'}
        >>> esta_vigente(vinculo, '2025-03')
        True
        >>> esta_vigente(vinculo, '2025-08')
        False
        >>> esta_vigente({}, '2025-08')
        True
    """
    if texto(registro.get('status')) == StatusRegistro.INATIVO.value:
        return False

    alvo = texto(competencia)
    inicio = texto(registro.get('competencia_inicio'))
    fim = texto(registro.get('competencia_fim'))

    return (not inicio or inicio <= alvo) and (not fim or alvo <= fim)


def filtrar_vigentes(
    registros: Iterable[Mapping[str, Any]], competencia: str
) -> list[dict[str, Any]]:
    """Seleciona os registros vigentes numa competência.

    Args:
        registros: Vínculos ou custos com vigência.
        competencia: Competência ``AAAA-MM``; vazio devolve todos.

    Returns:
        Cópias dos registros vigentes, na ordem de entrada.

    Example:
        >>> filtrar_vigentes([{'competencia_fim': '2024-12'}], '2025-01')
        []
    """
    if not competencia:
        return [dict(registro) for registro in registros]

    return [
        dict(registro)
        for registro in registros
        if esta_vigente(registro, competencia)
    ]


def custo_vigente(
    historico: Iterable[Mapping[str, Any]], competencia: str
) -> dict[str, Any] | None:
    """Escolhe, no histórico, o custo que valia numa competência.

    Havendo mais de um candidato — o que só acontece com histórico
    inconsistente —, vence o de início mais recente.

    Args:
        historico: Versões de custo do vínculo.
        competencia: Competência ``AAAA-MM`` consultada.

    Returns:
        O custo vigente, ou ``None`` se nenhum cobre a competência.

    Example:
        >>> custo_vigente([{'competencia_inicio': '2026-01'}], '2026-05')
        {'competencia_inicio': '2026-01'}
    """
    candidatos = filtrar_vigentes(historico, competencia)
    if not candidatos:
        return None

    return max(candidatos, key=lambda c: texto(c.get('competencia_inicio')))


def abrir_nova_vigencia(
    historico: Iterable[Mapping[str, Any]],
    novo_custo: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Fecha o custo em vigor e coloca o novo no lugar.

    É o mecanismo de histórico pedido pelo negócio: o valor é único, mas
    a versão anterior não some — fica encerrada na competência anterior à
    do custo que entra.

    Args:
        historico: Versões já gravadas do custo do vínculo.
        novo_custo: Custo que passa a valer, com ``competencia_inicio``.

    Returns:
        Novo histórico, ordenado pela competência de início.

    Raises:
        ValueError: Se ``competencia_inicio`` do novo custo for inválida.

    Example:
        >>> antigo = {'id': '1', 'competencia_inicio': '2025-01',
        ...           'competencia_fim': ''}
        >>> h = abrir_nova_vigencia([antigo], {'id': '2',
        ...                                    'competencia_inicio': '2026-01'})
        >>> h[0]['competencia_fim']
        '2025-12'
    """
    inicio = texto(novo_custo.get('competencia_inicio'))
    if not competencia_valida(inicio):
        raise ValueError(
            f'Competência inicial inválida: {inicio!r}. Use AAAA-MM.'
        )

    encerramento = deslocar_competencia(inicio, -1)
    anteriores = [
        _encerrar_se_aberto(versao, inicio, encerramento)
        for versao in historico
    ]

    return sorted(
        [*anteriores, dict(novo_custo)],
        key=lambda c: texto(c.get('competencia_inicio')),
    )


def _encerrar_se_aberto(
    versao: Mapping[str, Any], inicio_novo: str, encerramento: str
) -> dict[str, Any]:
    """Fecha uma versão de custo que invadiria a vigência da nova."""
    fim = texto(versao.get('competencia_fim'))
    if fim and fim < inicio_novo:
        return dict(versao)

    return {**versao, 'competencia_fim': encerramento}


# =====================================================================
# Cálculo do custo
# =====================================================================
def _base_do_percentual(
    custo: Mapping[str, Any], apuracao: BaseApuracao
) -> float:
    """Resolve qual valor da competência o percentual usa como base."""
    valores = {
        BaseCalculo.VALOR_REMESSA.value: apuracao.valor_remessa,
        BaseCalculo.VALOR_RETORNO.value: apuracao.valor_retorno,
        BaseCalculo.VALOR_REPASSE.value: apuracao.valor_repasse,
    }
    escolhida = texto(custo.get('base_calculo'))

    return valores.get(escolhida, apuracao.valor_retorno)


def _faixa_aplicavel(
    custo: Mapping[str, Any], apuracao: BaseApuracao
) -> Mapping[str, Any] | None:
    """Escolhe o degrau da tabela em que a competência caiu.

    A tabela é lida em ordem crescente de teto; ``ate`` igual a zero
    marca o último degrau, que absorve tudo acima do anterior.
    """
    criterio = texto(custo.get('criterio_faixa'))
    medida = (
        apuracao.quantidade_contratos
        if criterio == CriterioFaixa.QUANTIDADE.value
        else _base_do_percentual(custo, apuracao)
    )
    faixas = sorted(
        custo.get('faixas') or [],
        key=lambda f: numero(f.get('ate')) or float('inf'),
    )

    return next(
        (
            faixa
            for faixa in faixas
            if numero(faixa.get('ate')) == SEM_TETO
            or medida <= numero(faixa.get('ate'))
        ),
        None,
    )


def calcular_custo(
    custo: Mapping[str, Any] | None, apuracao: BaseApuracao
) -> float:
    """Apura o custo de uma competência conforme o método cadastrado.

    Args:
        custo: Custo vigente do vínculo; ``None`` devolve zero.
        apuracao: Números da competência.

    Returns:
        Valor do custo, arredondado a duas casas.

    Example:
        >>> pct = {'metodo': 'PERCENTUAL', 'base_calculo': 'VALOR_RETORNO',
        ...        'aliquota_percentual': 2.5}
        >>> calcular_custo(pct, BaseApuracao(valor_retorno=1000))
        25.0
        >>> calcular_custo({'metodo': 'POR_CONTRATO', 'valor_unitario': 3.5},
        ...                BaseApuracao(quantidade_contratos=10))
        35.0
        >>> calcular_custo(None, BaseApuracao())
        0.0
    """
    if not custo:
        return 0.0

    metodo = texto(custo.get('metodo'))

    if metodo == MetodoCusto.FIXO_MENSAL.value:
        return round(numero(custo.get('valor_fixo')), 2)

    if metodo == MetodoCusto.POR_CONTRATO.value:
        unitario = numero(custo.get('valor_unitario'))
        return round(unitario * apuracao.quantidade_contratos, 2)

    if metodo == MetodoCusto.PERCENTUAL.value:
        base = _base_do_percentual(custo, apuracao)
        aliquota = numero(custo.get('aliquota_percentual'))
        return round(base * aliquota / CEM_PORCENTO, 2)

    if metodo == MetodoCusto.FAIXA.value:
        faixa = _faixa_aplicavel(custo, apuracao)
        return calcular_custo(_faixa_como_custo(custo, faixa), apuracao)

    return 0.0


def _faixa_como_custo(
    custo: Mapping[str, Any], faixa: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    """Converte um degrau da tabela num custo simples, reaproveitando o
    cálculo dos demais métodos em vez de duplicá-lo."""
    if not faixa:
        return None

    return {
        'metodo': texto(faixa.get('metodo')),
        'base_calculo': texto(
            faixa.get('base_calculo') or custo.get('base_calculo')
        ),
        'aliquota_percentual': numero(faixa.get('aliquota_percentual')),
        'valor_fixo': numero(faixa.get('valor_fixo')),
        'valor_unitario': numero(faixa.get('valor_unitario')),
    }


def descrever_custo(custo: Mapping[str, Any] | None) -> str:
    """Resume o custo numa frase para a grade do painel.

    Args:
        custo: Custo vigente do vínculo; ``None`` vira aviso de ausência.

    Returns:
        Texto curto, pronto para exibir.

    Example:
        >>> descrever_custo({'metodo': 'FIXO_MENSAL', 'valor_fixo': 1500})
        'R$ 1500.00/mês'
        >>> descrever_custo(None)
        'sem custo cadastrado'
    """
    if not custo:
        return 'sem custo cadastrado'

    metodo = texto(custo.get('metodo'))
    resumos = {
        MetodoCusto.PERCENTUAL.value: (
            f'{numero(custo.get("aliquota_percentual")):.2f}% sobre '
            f'{texto(custo.get("base_calculo")).replace("_", " ").lower()}'
        ),
        MetodoCusto.FIXO_MENSAL.value: (
            f'R$ {numero(custo.get("valor_fixo")):.2f}/mês'
        ),
        MetodoCusto.POR_CONTRATO.value: (
            f'R$ {numero(custo.get("valor_unitario")):.2f} por contrato'
        ),
        MetodoCusto.FAIXA.value: (
            f'{len(custo.get("faixas") or [])} faixa(s) por '
            f'{texto(custo.get("criterio_faixa")).lower()}'
        ),
    }

    return resumos.get(metodo, 'método não reconhecido')


# =====================================================================
# Validação
# =====================================================================
def _erros_do_metodo(custo: Mapping[str, Any]) -> list[str]:
    """Cobra os campos que só fazem sentido no método escolhido."""
    metodo = texto(custo.get('metodo'))

    if metodo == MetodoCusto.PERCENTUAL.value:
        return _erros_percentual(custo)
    if metodo == MetodoCusto.FIXO_MENSAL.value:
        return _erros_positivo(custo, 'valor_fixo', 'Valor fixo mensal')
    if metodo == MetodoCusto.POR_CONTRATO.value:
        return _erros_positivo(custo, 'valor_unitario', 'Valor por contrato')
    if metodo == MetodoCusto.FAIXA.value:
        return _erros_faixa(custo)

    return [f'Método de custo inválido: {metodo!r}.']


def _erros_percentual(custo: Mapping[str, Any]) -> list[str]:
    """Valida alíquota e base do método percentual."""
    aliquota = numero(custo.get('aliquota_percentual'))
    base = texto(custo.get('base_calculo'))

    return [
        *(['Informe uma alíquota maior que zero.'] if aliquota <= 0 else []),
        *(
            [f'Base de cálculo inválida: {base!r}.']
            if base not in BASES_VALIDAS
            else []
        ),
    ]


def _erros_positivo(
    custo: Mapping[str, Any], campo: str, rotulo: str
) -> list[str]:
    """Cobra valor maior que zero num campo monetário obrigatório."""
    return [] if numero(custo.get(campo)) > 0 else [f'{rotulo} deve ser > 0.']


def _erros_faixa(custo: Mapping[str, Any]) -> list[str]:
    """Valida a tabela de faixas e cada degrau dentro dela."""
    faixas = custo.get('faixas') or []
    if not faixas:
        return ['Cadastre ao menos uma faixa.']

    criterio = texto(custo.get('criterio_faixa'))
    erros = (
        []
        if criterio in CRITERIOS_VALIDOS
        else [f'Critério de faixa inválido: {criterio!r}.']
    )

    return erros + [
        f'Faixa {posicao}: {problema}'
        for posicao, faixa in enumerate(faixas, start=1)
        for problema in _erros_do_metodo(faixa)
    ]


def validar_custo(custo: Mapping[str, Any]) -> list[str]:
    """Lista tudo que impede um custo de ser gravado.

    Devolver a lista inteira — em vez de estourar no primeiro problema —
    deixa o front apontar todos os campos de uma vez.

    Args:
        custo: Payload do formulário de custo.

    Returns:
        Mensagens de erro; lista vazia quando o custo é válido.

    Example:
        >>> validar_custo({'metodo': 'FIXO_MENSAL', 'valor_fixo': 0,
        ...                'competencia_inicio': '2026-01'})
        ['Valor fixo mensal deve ser > 0.']
        >>> validar_custo({'metodo': 'FIXO_MENSAL', 'valor_fixo': 10,
        ...                'competencia_inicio': '2026-01'})
        []
    """
    inicio = texto(custo.get('competencia_inicio'))
    fim = texto(custo.get('competencia_fim'))

    erros = [
        *(
            []
            if competencia_valida(inicio)
            else ['Competência inicial deve estar no formato AAAA-MM.']
        ),
        *(
            ['Competência final não pode ser anterior à inicial.']
            if fim and inicio and fim < inicio
            else []
        ),
        *(
            [f'Competência final inválida: {fim!r}.']
            if fim and not competencia_valida(fim)
            else []
        ),
    ]

    return erros + _erros_do_metodo(custo)


def validar_vinculo(vinculo: Mapping[str, Any]) -> list[str]:
    """Lista o que impede um vínculo convênio × originadora de valer.

    Args:
        vinculo: Payload do formulário de vínculo.

    Returns:
        Mensagens de erro; lista vazia quando o vínculo é válido.

    Example:
        >>> validar_vinculo({'originador': 'Alvo Card',
        ...                  'numero_convenio': '00001ALV',
        ...                  'competencia_inicio': '2026-01'})
        []
        >>> validar_vinculo({'originador': '', 'numero_convenio': '1',
        ...                  'competencia_inicio': '2026-01'})
        ['Informe a originadora.']
    """
    inicio = texto(vinculo.get('competencia_inicio'))
    fim = texto(vinculo.get('competencia_fim'))

    return [
        *(
            []
            if texto(vinculo.get('originador'))
            else ['Informe a originadora.']
        ),
        *(
            []
            if texto(vinculo.get('numero_convenio'))
            else ['Informe o número do convênio na originadora.']
        ),
        *(
            []
            if competencia_valida(inicio)
            else ['Competência inicial deve estar no formato AAAA-MM.']
        ),
        *(
            [f'Competência final inválida: {fim!r}.']
            if fim and not competencia_valida(fim)
            else []
        ),
        *(
            ['Competência final não pode ser anterior à inicial.']
            if fim and inicio and fim < inicio
            else []
        ),
    ]
