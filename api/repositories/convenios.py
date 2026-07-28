# INSERIR EM: api/repositories/convenios.py
"""Persistência da gestão de convênios, originadoras e custos.

Grava no mesmo banco em árvore de arquivos do resto do painel
(:mod:`api.arquivos`), acrescentando quatro tabelas:

    cadastro_convenio/convenios.txt          <- mestre, chave = CNPJ
    cadastro_originadora/originadoras.txt    <- mestre das originadoras
    gestao_convenios_originador/             <- vínculo convênio × orig.
        alvo_card__00001ALV.txt
    tabela_custo_convenio/                   <- histórico de custo do
        alvo_card__00001ALV.txt                 vínculo

Os dois mestres cabem num arquivo só: são listas curtas, e mantê-las
inteiras num documento dá operação atômica de lista de graça (reordenar,
remover) sem espalhar arquivo pela pasta.

``gestao_convenios_originador`` **já existia** com o cadastro básico do
convênio por originadora. Este módulo continua lendo aqueles arquivos e
apenas acrescenta os campos de vigência — nada de migração: registro sem
``competencia_inicio`` conta como vigente desde sempre (ver
:func:`api.domain_convenios.esta_vigente`).

Criação e alteração são operações **separadas** de propósito. A chave de
cada registro — CNPJ do convênio, nome da originadora, par
``(originadora, numero_convenio)`` do vínculo — é o próprio nome do
arquivo; um ``salvar`` que aceitasse chave nova gravaria um segundo
arquivo em vez de renomear o primeiro, e o vínculo original ficaria para
trás com todo o histórico de custo dele. Por isso ``criar_*`` recusa
chave que já existe e ``atualizar_*`` recusa payload que tente mudá-la.

As regras de negócio ficam em :mod:`api.domain_convenios`; aqui só há
leitura, gravação e a composição das duas coisas.
"""

from __future__ import annotations

# --- stdlib ---
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

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
from api.domain import numero, texto
from api.domain_confronto import classificar_confronto
from api.domain_convenios import (
    CHAVE_CONVENIO,
    CHAVE_ORIGINADORA,
    CHAVE_VINCULO,
    BaseApuracao,
    CriterioFaixa,
    MetodoCusto,
    StatusRegistro,
    abrir_nova_vigencia,
    aplicar_alteracao,
    calcular_custo,
    chave_vinculo,
    cnpj_formatado,
    custo_vigente,
    descrever_custo,
    esta_vigente,
    normalizar_cnpj,
    validar_custo,
    validar_vinculo,
    violacoes_de_chave,
)

logger = logging.getLogger(__name__)

TABELA_CONVENIO = 'cadastro_convenio'
TABELA_ORIGINADORA = 'cadastro_originadora'
TABELA_VINCULO = 'gestao_convenios_originador'
TABELA_CUSTO = 'tabela_custo_convenio'

ARQUIVO_CONVENIO = f'convenios{EXTENSAO}'
ARQUIVO_ORIGINADORA = f'originadoras{EXTENSAO}'


class ConvenioNaoEncontradoError(LookupError):
    """Sinaliza CNPJ de convênio inexistente no cadastro."""


class VinculoNaoEncontradoError(LookupError):
    """Sinaliza vínculo convênio × originadora inexistente."""


class RegistroInvalidoError(ValueError):
    """Sinaliza payload reprovado pelas regras de :mod:`domain_convenios`."""


class RegistroEmUsoError(RuntimeError):
    """Sinaliza exclusão barrada por dependência de outro cadastro."""


class ChaveDuplicadaError(RuntimeError):
    """Sinaliza criação de registro cuja chave já está cadastrada."""


class ChaveImutavelError(RuntimeError):
    """Sinaliza alteração que tentaria mudar a chave de um registro."""


# =====================================================================
# Infraestrutura comum
# =====================================================================
def _agora() -> str:
    """Carimbo de data/hora da gravação, em ISO até os segundos."""
    return datetime.now().isoformat(timespec='seconds')


def _caminho_mestre(raiz: Path, tabela: str, arquivo: str) -> Path:
    """Resolve o arquivo único de uma tabela mestre."""
    return raiz / tabela / arquivo


def _ler_mestre(raiz: Path, tabela: str, arquivo: str) -> list[dict[str, Any]]:
    """Lê os registros de uma tabela mestre; vazio quando ainda não existe."""
    lido = ler_arquivo(_caminho_mestre(raiz, tabela, arquivo))

    return list(lido[0]['registros']) if lido else []


def _gravar_mestre(
    raiz: Path,
    tabela: str,
    arquivo: str,
    registros: Iterable[Mapping[str, Any]],
) -> None:
    """Regrava a tabela mestre inteira, de forma atômica."""
    documento = montar_documento(tabela, '', '', list(registros))
    gravar_arquivo(_caminho_mestre(raiz, tabela, arquivo), documento)


def _substituir(
    registros: Iterable[Mapping[str, Any]],
    novo: Mapping[str, Any],
    chave: str,
) -> list[dict[str, Any]]:
    """Troca o registro de mesma chave, ou acrescenta o novo no fim.

    Args:
        registros: Coleção atual.
        novo: Registro a inserir ou atualizar.
        chave: Campo que identifica o registro.

    Returns:
        Nova lista — a original não é tocada.
    """
    identificador = texto(novo.get(chave))
    substituidos = [
        dict(novo) if texto(item.get(chave)) == identificador else dict(item)
        for item in registros
    ]
    ja_existe = any(
        texto(item.get(chave)) == identificador for item in registros
    )

    return substituidos if ja_existe else [*substituidos, dict(novo)]


# =====================================================================
# Originadoras
# =====================================================================
def listar_originadoras(pasta_banco: Path) -> list[dict[str, Any]]:
    """Lista as originadoras, em ordem alfabética.

    Inclui as que só aparecem nos vínculos herdados da base anterior a
    este módulo. Sem isso, numa instalação existente o cadastro nasceria
    vazio e ninguém conseguiria ligar uma originadora a um convênio sem
    antes recadastrar à mão o que já está em produção. ``cadastrado``
    diz de onde veio cada uma.

    Args:
        pasta_banco: Raiz do banco de arquivos.

    Returns:
        Registros de originadora, do mestre e dos vínculos.

    Raises:
        ArmazenamentoIndisponivelError: Se a pasta do banco não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    cadastradas = [
        {**registro, 'cadastrado': True}
        for registro in _ler_mestre(
            raiz, TABELA_ORIGINADORA, ARQUIVO_ORIGINADORA
        )
    ]
    conhecidas = {texto(o.get('nome')) for o in cadastradas}

    herdadas = [
        _originadora_herdada(nome)
        for nome in sorted(
            {
                texto(vinculo.get('originador'))
                for vinculo in _ler_vinculos(raiz)
            }
            - conhecidas
        )
        if nome
    ]

    return sorted(
        [*cadastradas, *herdadas], key=lambda o: texto(o.get('nome')).lower()
    )


def _originadora_herdada(nome: str) -> dict[str, Any]:
    """Monta a ficha mínima de uma originadora que só existe nos vínculos."""
    return {
        'nome': nome,
        'codigo': '',
        'cnpj': '',
        'status': StatusRegistro.ATIVO.value,
        'observacao': 'Em uso nos vínculos, ainda sem cadastro próprio.',
        'criado_em': '',
        'atualizado_em': '',
        'cadastrado': False,
    }


def criar_originadora(
    pasta_banco: Path, dados: Mapping[str, Any]
) -> dict[str, Any]:
    """Cadastra uma originadora nova.

    O nome é a chave — e uma chave especialmente sensível: é ele que vira
    o prefixo do nome de arquivo de todo vínculo daquela originadora
    (``alvo_card__00001ALV.txt``). Por isso o nome não é editável depois;
    ver :func:`atualizar_originadora`.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        dados: Campos da originadora — ``nome`` é obrigatório.

    Returns:
        A originadora gravada, já com os carimbos de auditoria.

    Raises:
        RegistroInvalidoError: Se o nome vier vazio.
        ChaveDuplicadaError: Se já existir originadora com esse nome.
        ArmazenamentoIndisponivelError: Se a gravação falhar.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    nome = texto(dados.get('nome'))
    if not nome:
        raise RegistroInvalidoError('Informe o nome da originadora.')

    atuais = _ler_mestre(raiz, TABELA_ORIGINADORA, ARQUIVO_ORIGINADORA)
    if any(texto(o.get('nome')) == nome for o in atuais):
        raise ChaveDuplicadaError(
            f'Já existe uma originadora chamada {nome!r}. '
            'O nome é a chave do cadastro e não se repete.'
        )

    registro = {
        'nome': nome,
        'codigo': texto(dados.get('codigo')).upper(),
        'cnpj': cnpj_formatado(dados.get('cnpj')),
        'status': texto(dados.get('status')) or StatusRegistro.ATIVO.value,
        'observacao': texto(dados.get('observacao')),
        'criado_em': _agora(),
        'atualizado_em': _agora(),
    }

    _gravar_mestre(
        raiz, TABELA_ORIGINADORA, ARQUIVO_ORIGINADORA, [*atuais, registro]
    )
    logger.info('Originadora criada: %s', nome)

    return registro


def atualizar_originadora(
    pasta_banco: Path, nome: str, alteracoes: Mapping[str, Any]
) -> dict[str, Any]:
    """Atualiza os dados editáveis de uma originadora já cadastrada.

    O nome não entra: renomear a originadora deixaria todos os arquivos
    de vínculo dela órfãos, já que o nome é o prefixo deles. Nome errado
    se resolve excluindo (só é possível sem vínculo) e cadastrando de
    novo.

    Originadora que só existia nos vínculos (base anterior a este
    módulo) ganha ficha própria nesta primeira edição.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        nome: Nome exato da originadora a atualizar.
        alteracoes: Campos editáveis — CNPJ, status e observação.

    Returns:
        A originadora após a alteração.

    Raises:
        RegistroInvalidoError: Se a originadora não existir nem no
            mestre nem nos vínculos.
        ChaveImutavelError: Se o payload tentar mudar o nome.
        ArmazenamentoIndisponivelError: Se a gravação falhar.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    atuais = _ler_mestre(raiz, TABELA_ORIGINADORA, ARQUIVO_ORIGINADORA)
    anterior = next(
        (o for o in atuais if texto(o.get('nome')) == texto(nome)), None
    )
    if anterior is None:
        anterior = _promover_originadora(raiz, texto(nome))

    _exigir_chave_intacta(anterior, alteracoes, CHAVE_ORIGINADORA)

    registro = {
        **aplicar_alteracao(anterior, alteracoes, CHAVE_ORIGINADORA),
        'codigo': texto(
            alteracoes.get('codigo', anterior.get('codigo'))
        ).upper(),
        'cnpj': cnpj_formatado(alteracoes.get('cnpj', anterior.get('cnpj'))),
        'criado_em': texto(anterior.get('criado_em')) or _agora(),
        'atualizado_em': _agora(),
    }
    registro.pop('cadastrado', None)

    _gravar_mestre(
        raiz,
        TABELA_ORIGINADORA,
        ARQUIVO_ORIGINADORA,
        _substituir(atuais, registro, 'nome'),
    )
    logger.info('Originadora atualizada: %s', nome)

    return registro


def _promover_originadora(raiz: Path, nome: str) -> dict[str, Any]:
    """Cria a ficha de uma originadora que só existia nos vínculos.

    Args:
        raiz: Pasta do banco.
        nome: Nome exato procurado nos vínculos.

    Returns:
        Ficha inicial, pronta para receber as alterações.

    Raises:
        RegistroInvalidoError: Se nenhum vínculo usa esse nome.
    """
    em_uso = any(
        texto(vinculo.get('originador')) == nome
        for vinculo in _ler_vinculos(raiz)
    )
    if not em_uso:
        raise RegistroInvalidoError(f'Originadora {nome!r} não encontrada.')

    return _originadora_herdada(nome)


def _exigir_chave_intacta(
    atual: Mapping[str, Any],
    alteracoes: Mapping[str, Any],
    campos_chave: tuple[str, ...],
) -> None:
    """Recusa a alteração que tentar mudar a identidade do registro."""
    problemas = violacoes_de_chave(atual, alteracoes, campos_chave)
    if problemas:
        raise ChaveImutavelError(' '.join(problemas))


def excluir_originadora(pasta_banco: Path, nome: str) -> None:
    """Remove uma originadora que ainda não tem convênio vinculado.

    Originadora com vínculo não é excluída: apagá-la deixaria vínculos
    órfãos e conciliações sem dono. O caminho nesse caso é inativar.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        nome: Nome exato da originadora.

    Raises:
        RegistroEmUsoError: Se houver vínculo apontando para ela.
        ArmazenamentoIndisponivelError: Se a gravação falhar.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    alvo = texto(nome)

    em_uso = [v for v in _ler_vinculos(raiz) if texto(v['originador']) == alvo]
    if em_uso:
        raise RegistroEmUsoError(
            f'{alvo} tem {len(em_uso)} convênio(s) vinculado(s). '
            'Inative a originadora em vez de excluí-la.'
        )

    atuais = _ler_mestre(raiz, TABELA_ORIGINADORA, ARQUIVO_ORIGINADORA)
    _gravar_mestre(
        raiz,
        TABELA_ORIGINADORA,
        ARQUIVO_ORIGINADORA,
        [o for o in atuais if texto(o.get('nome')) != alvo],
    )
    logger.info('Originadora excluída: %s', alvo)


# =====================================================================
# Vínculos convênio × originadora
# =====================================================================
def _ler_vinculos(raiz: Path) -> list[dict[str, Any]]:
    """Lê todos os vínculos gravados, um por arquivo da tabela.

    Args:
        raiz: Pasta do banco.

    Returns:
        Registros com a identidade do documento já garantida — arquivos
        antigos nem sempre repetem originadora e número dentro do
        registro, e o cabeçalho é a fonte confiável dos dois.
    """
    return [
        {
            **registro,
            'originador': texto(documento.get('originador')),
            'numero_convenio': texto(documento.get('numero_convenio')),
        }
        for documento in listar_documentos(raiz, TABELA_VINCULO)
        for registro in documento.get('registros') or []
    ]


def listar_vinculos(pasta_banco: Path) -> list[dict[str, Any]]:
    """Lista todos os vínculos convênio × originadora, sem agrupar.

    Diferente de :func:`listar_convenios` (que agrupa por CNPJ) e de
    :func:`listar_ativos_para_conciliacao` (que só traz os vigentes), aqui
    vem a lista **plana e completa** — ligados ou não, vigentes ou não. É
    o que a gerência de convênios da Conciliação precisa para poder religar
    o que foi desligado e ver o histórico inteiro.

    Args:
        pasta_banco: Raiz do banco de arquivos.

    Returns:
        Registros de vínculo com a identidade garantida pelo cabeçalho.

    Raises:
        ArmazenamentoIndisponivelError: Se a pasta do banco não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    return _ler_vinculos(garantir_raiz(pasta_banco))


def vinculo_existe(
    pasta_banco: Path, originador: str, numero_convenio: str
) -> bool:
    """Diz se existe arquivo de vínculo para o par informado.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        originador: Originadora do vínculo.
        numero_convenio: Número do convênio naquela originadora.

    Returns:
        True quando o vínculo está cadastrado.

    Raises:
        ArmazenamentoIndisponivelError: Se a pasta do banco não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)

    return caminho_registro(
        raiz, TABELA_VINCULO, originador, numero_convenio
    ).is_file()


def _ler_custos(raiz: Path, originador: str, numero_convenio: str) -> list:
    """Lê o histórico de custo de um vínculo."""
    lido = ler_arquivo(
        caminho_registro(raiz, TABELA_CUSTO, originador, numero_convenio)
    )

    return list(lido[0]['registros']) if lido else []


def _montar_vinculo(
    raiz: Path, vinculo: Mapping[str, Any], competencia: str
) -> dict[str, Any]:
    """Enriquece um vínculo com a situação e o custo daquela competência.

    Args:
        raiz: Pasta do banco.
        vinculo: Registro lido da tabela de vínculos.
        competencia: Competência ``AAAA-MM``; vazio consulta a vigência
            aberta de hoje.

    Returns:
        Vínculo pronto para a tela, com ``custo_vigente`` embutido.
    """
    originador = texto(vinculo.get('originador'))
    numero_convenio = texto(vinculo.get('numero_convenio'))
    referencia = competencia or _competencia_de_hoje()
    custo = custo_vigente(
        _ler_custos(raiz, originador, numero_convenio), referencia
    )

    return {
        'originador': originador,
        'numero_convenio': numero_convenio,
        'nome_convenio': texto(vinculo.get('nome_convenio')),
        'cnpj_convenio': cnpj_formatado(vinculo.get('cnpj_convenio')),
        'averbadora': texto(vinculo.get('averbadora')),
        'status': texto(vinculo.get('status')) or StatusRegistro.ATIVO.value,
        'competencia_inicio': texto(vinculo.get('competencia_inicio')),
        'competencia_fim': texto(vinculo.get('competencia_fim')),
        'observacao': texto(vinculo.get('observacao')),
        'vigente': esta_vigente(vinculo, referencia),
        'custo_vigente': custo,
        'custo_resumo': descrever_custo(custo),
    }


def _competencia_de_hoje() -> str:
    """Competência ``AAAA-MM`` do mês corrente."""
    return datetime.now().strftime('%Y-%m')


# =====================================================================
# Convênios (visão principal do módulo)
# =====================================================================
def _mestre_por_cnpj(raiz: Path) -> dict[str, dict[str, Any]]:
    """Indexa o mestre de convênios pelo CNPJ normalizado."""
    return {
        normalizar_cnpj(registro.get('cnpj_convenio')): dict(registro)
        for registro in _ler_mestre(raiz, TABELA_CONVENIO, ARQUIVO_CONVENIO)
        if normalizar_cnpj(registro.get('cnpj_convenio'))
    }


def _agrupar_por_convenio(
    raiz: Path, vinculos: Iterable[Mapping[str, Any]], competencia: str
) -> dict[str, list[dict[str, Any]]]:
    """Agrupa os vínculos pelo CNPJ do convênio.

    O CNPJ é a chave porque o número muda de originadora para
    originadora — ``00001ALV`` e ``00061HTC`` podem ser o mesmo órgão.
    """
    agrupados: dict[str, list[dict[str, Any]]] = {}
    for vinculo in vinculos:
        cnpj = normalizar_cnpj(vinculo.get('cnpj_convenio'))
        montado = _montar_vinculo(raiz, vinculo, competencia)
        agrupados.setdefault(cnpj, []).append(montado)

    return agrupados


def listar_convenios(
    pasta_banco: Path, competencia: str = ''
) -> list[dict[str, Any]]:
    """Lista os convênios com as originadoras que os operam.

    Esta é a visão pedida pelo negócio: **um convênio, várias
    originadoras**, cada uma com o seu número, a sua vigência e o seu
    custo. Convênio que só existe nos vínculos (cadastro antigo, sem
    passar pelo mestre) também aparece — o módulo funciona sobre a base
    atual sem exigir migração.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        competencia: Competência ``AAAA-MM`` para avaliar a vigência e
            escolher o custo; vazio usa o mês corrente.

    Returns:
        Um item por convênio, ordenado por nome, com ``originadoras`` e
        a contagem das que estão vigentes na competência.

    Raises:
        ArmazenamentoIndisponivelError: Se a pasta do banco não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    mestre = _mestre_por_cnpj(raiz)
    agrupados = _agrupar_por_convenio(raiz, _ler_vinculos(raiz), competencia)

    convenios = [
        _compor_convenio(cnpj, mestre.get(cnpj, {}), agrupados.get(cnpj, []))
        for cnpj in {*mestre, *agrupados}
    ]

    return sorted(convenios, key=lambda c: texto(c['nome_convenio']).lower())


def _compor_convenio(
    cnpj: str,
    do_mestre: Mapping[str, Any],
    originadoras: list[dict[str, Any]],
) -> dict[str, Any]:
    """Monta o convênio juntando o mestre com o que os vínculos dizem.

    O nome vem do mestre quando existe; senão, do primeiro vínculo. Com
    isso o cadastro corrige um nome divergente sem precisar editar cada
    originadora.
    """
    do_vinculo = originadoras[0] if originadoras else {}
    vigentes = [o for o in originadoras if o['vigente']]

    return {
        'cnpj_convenio': cnpj_formatado(cnpj),
        'cnpj_chave': cnpj,
        'nome_convenio': (
            texto(do_mestre.get('nome_convenio'))
            or texto(do_vinculo.get('nome_convenio'))
        ),
        'averbadora': (
            texto(do_mestre.get('averbadora'))
            or texto(do_vinculo.get('averbadora'))
        ),
        'status': (
            texto(do_mestre.get('status')) or StatusRegistro.ATIVO.value
        ),
        'status_producao': texto(do_mestre.get('status_producao')),
        'gestora_margem': texto(do_mestre.get('gestora_margem')),
        'link_gestora': texto(do_mestre.get('link_gestora')),
        'observacao': texto(do_mestre.get('observacao')),
        'cadastrado': bool(do_mestre),
        'originadoras': sorted(
            originadoras, key=lambda o: texto(o['originador']).lower()
        ),
        'total_originadoras': len(originadoras),
        'total_vigentes': len(vigentes),
    }


def obter_convenio(
    pasta_banco: Path, cnpj: str, competencia: str = ''
) -> dict[str, Any]:
    """Devolve um convênio e todas as suas originadoras.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        cnpj: CNPJ do convênio, com ou sem máscara.
        competencia: Competência ``AAAA-MM`` para vigência e custo.

    Returns:
        O convênio no mesmo formato de :func:`listar_convenios`.

    Raises:
        ConvenioNaoEncontradoError: Se o CNPJ não existe no cadastro nem
            nos vínculos.
        ArmazenamentoIndisponivelError: Se a pasta do banco não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    procurado = normalizar_cnpj(cnpj)
    encontrado = next(
        (
            convenio
            for convenio in listar_convenios(pasta_banco, competencia)
            if convenio['cnpj_chave'] == procurado
        ),
        None,
    )

    if not encontrado:
        raise ConvenioNaoEncontradoError(
            f'Convênio de CNPJ {cnpj_formatado(cnpj)} não encontrado.'
        )

    return encontrado


def criar_convenio(
    pasta_banco: Path, dados: Mapping[str, Any]
) -> dict[str, Any]:
    """Cadastra um convênio novo no mestre.

    O CNPJ é a chave: é ele que junta, num convênio só, os números que
    cada originadora dá ao mesmo órgão. Depois de criado não muda — ver
    :func:`atualizar_convenio`.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        dados: ``cnpj_convenio`` e ``nome_convenio`` obrigatórios.

    Returns:
        O registro gravado no mestre.

    Raises:
        RegistroInvalidoError: Se CNPJ ou nome vierem vazios.
        ChaveDuplicadaError: Se o CNPJ já estiver cadastrado.
        ArmazenamentoIndisponivelError: Se a gravação falhar.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    cnpj = normalizar_cnpj(dados.get('cnpj_convenio'))
    nome = texto(dados.get('nome_convenio'))

    erros = [
        *([] if cnpj else ['Informe o CNPJ do convênio.']),
        *([] if nome else ['Informe o nome do convênio.']),
    ]
    if erros:
        raise RegistroInvalidoError(' '.join(erros))

    atuais = _ler_mestre(raiz, TABELA_CONVENIO, ARQUIVO_CONVENIO)
    if any(normalizar_cnpj(c.get('cnpj_convenio')) == cnpj for c in atuais):
        raise ChaveDuplicadaError(
            f'O CNPJ {cnpj_formatado(cnpj)} já está cadastrado. '
            'Abra o convênio existente para editá-lo.'
        )

    registro = {
        'cnpj_convenio': cnpj_formatado(cnpj),
        'nome_convenio': nome,
        'averbadora': texto(dados.get('averbadora')),
        'status': texto(dados.get('status')) or StatusRegistro.ATIVO.value,
        'status_producao': texto(dados.get('status_producao')),
        'gestora_margem': texto(dados.get('gestora_margem')),
        'link_gestora': texto(dados.get('link_gestora')),
        'observacao': texto(dados.get('observacao')),
        'criado_em': _agora(),
        'atualizado_em': _agora(),
    }

    _gravar_mestre(
        raiz, TABELA_CONVENIO, ARQUIVO_CONVENIO, [*atuais, registro]
    )
    logger.info('Convênio criado: %s (%s)', nome, registro['cnpj_convenio'])

    return registro


def atualizar_convenio(
    pasta_banco: Path, cnpj: str, alteracoes: Mapping[str, Any]
) -> dict[str, Any]:
    """Atualiza nome, status e observação de um convênio.

    O CNPJ fica de fora: trocá-lo não corrigiria o cadastro, criaria
    outro convênio e deixaria os vínculos apontando para o CNPJ antigo.

    Convênio que só existe nos vínculos (base anterior a este módulo,
    nunca passado pelo mestre) é promovido a cadastro nesta primeira
    edição, mantendo o CNPJ que já vinha dos vínculos.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        cnpj: CNPJ do convênio a atualizar.
        alteracoes: Campos editáveis.

    Returns:
        O registro após a alteração.

    Raises:
        ChaveImutavelError: Se o payload tentar mudar o CNPJ.
        ConvenioNaoEncontradoError: Se o CNPJ não existe em lugar nenhum.
        ArmazenamentoIndisponivelError: Se a gravação falhar.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    chave = normalizar_cnpj(cnpj)
    atuais = _ler_mestre(raiz, TABELA_CONVENIO, ARQUIVO_CONVENIO)
    anterior = next(
        (
            c
            for c in atuais
            if normalizar_cnpj(c.get('cnpj_convenio')) == chave
        ),
        None,
    )

    if anterior is None:
        anterior = _promover_dos_vinculos(raiz, chave)

    _exigir_chave_intacta(anterior, alteracoes, CHAVE_CONVENIO)

    registro = {
        **aplicar_alteracao(anterior, alteracoes, CHAVE_CONVENIO),
        'atualizado_em': _agora(),
    }

    _gravar_mestre(
        raiz,
        TABELA_CONVENIO,
        ARQUIVO_CONVENIO,
        _substituir(atuais, registro, 'cnpj_convenio'),
    )
    logger.info('Convênio atualizado: %s', registro['cnpj_convenio'])

    return registro


def _promover_dos_vinculos(raiz: Path, chave: str) -> dict[str, Any]:
    """Monta o registro mestre de um convênio que só existia nos vínculos.

    Args:
        raiz: Pasta do banco.
        chave: CNPJ normalizado procurado.

    Returns:
        Registro mestre inicial, com o nome que os vínculos já usavam.

    Raises:
        ConvenioNaoEncontradoError: Se nenhum vínculo tem esse CNPJ.
    """
    dos_vinculos = next(
        (
            vinculo
            for vinculo in _ler_vinculos(raiz)
            if normalizar_cnpj(vinculo.get('cnpj_convenio')) == chave
        ),
        None,
    )
    if dos_vinculos is None:
        raise ConvenioNaoEncontradoError(
            f'Convênio de CNPJ {cnpj_formatado(chave)} não encontrado.'
        )

    return {
        'cnpj_convenio': cnpj_formatado(chave),
        'nome_convenio': texto(dos_vinculos.get('nome_convenio')),
        'status': StatusRegistro.ATIVO.value,
        'observacao': '',
        'criado_em': _agora(),
        'atualizado_em': _agora(),
    }


def _sequencia_do_numero(numero: Any) -> int:
    """Extrai os dígitos iniciais de um número de convênio (``00001ALV``)."""
    casado = re.match(r'^(\d+)', texto(numero))

    return int(casado.group(1)) if casado else 0


def _codigo_da_originadora(raiz: Path, nome: str) -> str:
    """Código cadastrado da originadora (sufixo do número); vazio se ausente."""
    originadora = next(
        (
            o
            for o in _ler_mestre(raiz, TABELA_ORIGINADORA, ARQUIVO_ORIGINADORA)
            if texto(o.get('nome')) == texto(nome)
        ),
        {},
    )

    return texto(originadora.get('codigo')).upper()


def _gerar_numero_convenio(raiz: Path, originador: str) -> str:
    """Gera o próximo número: sequencial global + código da originadora.

    O sequencial é global (não repete entre originadoras) e o código
    identifica a originadora no próprio número — ``00001ALV``, ``00061HTC``.

    Raises:
        RegistroInvalidoError: Se a originadora não tem código cadastrado.
    """
    codigo = _codigo_da_originadora(raiz, originador)
    if not codigo:
        raise RegistroInvalidoError(
            f'A originadora {originador!r} não tem código cadastrado. '
            'Defina o código da originadora para o número ser gerado.'
        )

    proximo = max(
        (_sequencia_do_numero(v.get('numero_convenio'))
         for v in _ler_vinculos(raiz)),
        default=0,
    ) + 1

    return f'{proximo:05d}{codigo}'


def _averbadora_do_convenio(raiz: Path, cnpj: str) -> str:
    """Averbadora cadastrada no convênio mestre (copiada para o vínculo)."""
    return texto(
        _mestre_por_cnpj(raiz).get(normalizar_cnpj(cnpj), {}).get('averbadora')
    )


def criar_vinculo(
    pasta_banco: Path, cnpj: str, dados: Mapping[str, Any]
) -> dict[str, Any]:
    """Liga uma originadora a um convênio.

    É por aqui que "o convênio ganha mais uma originadora": o número do
    convênio informado é o **daquela originadora**, e a vigência diz a
    partir de qual competência ele entra na conciliação dela.

    O trio ``(CNPJ do convênio, originadora, número)`` é a chave do
    vínculo e nasce fechado aqui: nenhuma das três partes é editável
    depois. Isso é o que permite o custo, a conciliação e o histórico
    apontarem para o vínculo sem risco de o alvo mudar debaixo deles.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        cnpj: CNPJ do convênio dono do vínculo.
        dados: ``originador``, ``numero_convenio`` e
            ``competencia_inicio`` obrigatórios.

    Returns:
        O vínculo gravado, já enriquecido com vigência e custo.

    Raises:
        RegistroInvalidoError: Se o payload for reprovado pelas regras.
        ChaveDuplicadaError: Se o par originadora/número já existir.
        ArmazenamentoIndisponivelError: Se a gravação falhar.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)

    originador = texto(dados.get('originador'))
    numero_convenio = texto(dados.get('numero_convenio')) or (
        _gerar_numero_convenio(raiz, originador)
    )

    erros = validar_vinculo({**dados, 'numero_convenio': numero_convenio})
    if erros:
        raise RegistroInvalidoError(' '.join(erros))

    caminho = caminho_registro(
        raiz, TABELA_VINCULO, originador, numero_convenio
    )
    if caminho.is_file():
        raise ChaveDuplicadaError(
            f'A originadora {originador} já tem o convênio '
            f'{numero_convenio} cadastrado. Abra o vínculo para editá-lo.'
        )

    registro = {
        'id': chave_vinculo(originador, numero_convenio),
        'originador': originador,
        'numero_convenio': numero_convenio,
        'cnpj_convenio': cnpj_formatado(cnpj),
        'nome_convenio': _nome_do_convenio(raiz, cnpj),
        'averbadora': _averbadora_do_convenio(raiz, cnpj),
        'status': texto(dados.get('status')) or StatusRegistro.ATIVO.value,
        'competencia_inicio': texto(dados.get('competencia_inicio')),
        'competencia_fim': texto(dados.get('competencia_fim')),
        'observacao': texto(dados.get('observacao')),
        'criado_em': _agora(),
        'atualizado_em': _agora(),
    }

    _gravar_vinculo(raiz, registro)
    logger.info('Vínculo criado: %s', registro['id'])

    return _montar_vinculo(raiz, registro, '')


def atualizar_vinculo(
    pasta_banco: Path,
    originador: str,
    numero_convenio: str,
    alteracoes: Mapping[str, Any],
) -> dict[str, Any]:
    """Atualiza o que é editável num vínculo já cadastrado.

    Editável é tudo que descreve o vínculo: averbadora, status, vigência
    e observação. Fora isso está a chave — originadora, número e CNPJ do
    convênio —, que só sai por exclusão e novo cadastro.

    Trocar a competência final é justamente como se **desliga** um
    convênio numa originadora: ele para de aparecer na conciliação a
    partir do mês seguinte, e os meses anteriores continuam explicáveis.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        originador: Originadora do vínculo.
        numero_convenio: Número do convênio naquela originadora.
        alteracoes: Campos editáveis.

    Returns:
        O vínculo após a alteração, com vigência e custo recalculados.

    Raises:
        VinculoNaoEncontradoError: Se o vínculo não existe.
        ChaveImutavelError: Se o payload tentar mudar a chave.
        RegistroInvalidoError: Se o resultado violar as regras de
            vigência.
        ArmazenamentoIndisponivelError: Se a gravação falhar.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    caminho = caminho_registro(
        raiz, TABELA_VINCULO, originador, numero_convenio
    )
    lido = ler_arquivo(caminho)
    if not lido:
        raise VinculoNaoEncontradoError(
            f'Vínculo {originador} / {numero_convenio} não encontrado.'
        )

    anterior = {
        **(lido[0]['registros'] or [{}])[0],
        'originador': originador,
        'numero_convenio': numero_convenio,
    }
    _exigir_chave_intacta(anterior, alteracoes, CHAVE_VINCULO)

    registro = {
        **aplicar_alteracao(anterior, alteracoes, CHAVE_VINCULO),
        'atualizado_em': _agora(),
    }
    erros = validar_vinculo(registro)
    if erros:
        raise RegistroInvalidoError(' '.join(erros))

    _gravar_vinculo(raiz, registro)
    logger.info(
        'Vínculo atualizado: %s', chave_vinculo(originador, numero_convenio)
    )

    return _montar_vinculo(raiz, registro, '')


def _nome_do_convenio(raiz: Path, cnpj: str) -> str:
    """Copia o nome do convênio do mestre para dentro do vínculo.

    O nome fica repetido no arquivo do vínculo de propósito — é o que
    faz o ``.txt`` se explicar sozinho para quem o abre no Bloco de
    Notas. Mas ele é *cópia*: quem manda é o mestre, e por isso o nome
    não entra no formulário de vínculo. Editar o nome em dois lugares
    seria o caminho curto para dois nomes diferentes para o mesmo órgão.

    Args:
        raiz: Pasta do banco.
        cnpj: CNPJ do convênio.

    Returns:
        O nome do mestre; na falta dele — convênio herdado da base
        anterior a este módulo —, o nome que os vínculos irmãos já usam.
    """
    chave = normalizar_cnpj(cnpj)
    do_mestre = texto(
        _mestre_por_cnpj(raiz).get(chave, {}).get('nome_convenio')
    )
    if do_mestre:
        return do_mestre

    return next(
        (
            texto(vinculo.get('nome_convenio'))
            for vinculo in _ler_vinculos(raiz)
            if normalizar_cnpj(vinculo.get('cnpj_convenio')) == chave
            and texto(vinculo.get('nome_convenio'))
        ),
        '',
    )


def _gravar_vinculo(raiz: Path, registro: Mapping[str, Any]) -> None:
    """Grava o arquivo do vínculo — um registro por arquivo."""
    originador = texto(registro.get('originador'))
    numero_convenio = texto(registro.get('numero_convenio'))

    gravar_arquivo(
        caminho_registro(raiz, TABELA_VINCULO, originador, numero_convenio),
        montar_documento(
            TABELA_VINCULO, originador, numero_convenio, [dict(registro)]
        ),
    )


def excluir_vinculo(
    pasta_banco: Path, originador: str, numero_convenio: str
) -> None:
    """Apaga o vínculo e o histórico de custo que dependia dele.

    Encerrar a vigência costuma ser melhor que excluir — o histórico de
    conciliação passa a não ter como explicar o custo cobrado. A exclusão
    existe para desfazer cadastro errado, não para desligar convênio.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        originador: Originadora do vínculo.
        numero_convenio: Número do convênio naquela originadora.

    Raises:
        VinculoNaoEncontradoError: Se o vínculo não existe.
        ArmazenamentoIndisponivelError: Se a pasta do banco não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    caminho = caminho_registro(
        raiz, TABELA_VINCULO, originador, numero_convenio
    )

    if not caminho.is_file():
        raise VinculoNaoEncontradoError(
            f'Vínculo {originador} / {numero_convenio} não encontrado.'
        )

    caminho.unlink()
    caminho_registro(raiz, TABELA_CUSTO, originador, numero_convenio).unlink(
        missing_ok=True
    )
    logger.info(
        'Vínculo excluído: %s', chave_vinculo(originador, numero_convenio)
    )


# =====================================================================
# Custos
# =====================================================================
def listar_custos(
    pasta_banco: Path, originador: str, numero_convenio: str
) -> list[dict[str, Any]]:
    """Lê o histórico de custo de um vínculo, do mais novo ao mais antigo.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        originador: Originadora do vínculo.
        numero_convenio: Número do convênio naquela originadora.

    Returns:
        Versões de custo em ordem decrescente de vigência.

    Raises:
        ArmazenamentoIndisponivelError: Se a pasta do banco não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    historico = _ler_custos(raiz, originador, numero_convenio)

    return sorted(
        historico,
        key=lambda c: texto(c.get('competencia_inicio')),
        reverse=True,
    )


def salvar_custo(
    pasta_banco: Path,
    originador: str,
    numero_convenio: str,
    dados: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Coloca um novo custo em vigor, encerrando o anterior.

    O valor em vigor é sempre um só; o que sai não é apagado, fica
    fechado na competência anterior. É assim que uma conciliação de mês
    passado continua sabendo qual custo valia naquele mês.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        originador: Originadora do vínculo.
        numero_convenio: Número do convênio naquela originadora.
        dados: Payload do formulário de custo.

    Returns:
        O histórico completo após a gravação, do mais novo ao antigo.

    Raises:
        RegistroInvalidoError: Se o custo for reprovado pelas regras.
        VinculoNaoEncontradoError: Se o vínculo não existe.
        ArmazenamentoIndisponivelError: Se a gravação falhar.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    _exigir_vinculo(raiz, originador, numero_convenio)

    erros = validar_custo(dados)
    if erros:
        raise RegistroInvalidoError(' '.join(erros))

    historico = _ler_custos(raiz, originador, numero_convenio)
    registro = _registro_de_custo(dados, originador, numero_convenio)

    gravar_arquivo(
        caminho_registro(raiz, TABELA_CUSTO, originador, numero_convenio),
        montar_documento(
            TABELA_CUSTO,
            originador,
            numero_convenio,
            abrir_nova_vigencia(historico, registro),
        ),
    )
    logger.info(
        'Custo gravado para %s a partir de %s',
        chave_vinculo(originador, numero_convenio),
        registro['competencia_inicio'],
    )

    return listar_custos(pasta_banco, originador, numero_convenio)


def _exigir_vinculo(raiz: Path, originador: str, numero_convenio: str) -> None:
    """Barra custo de vínculo que não existe — custo órfão não é cobrável."""
    caminho = caminho_registro(
        raiz, TABELA_VINCULO, originador, numero_convenio
    )
    if not caminho.is_file():
        raise VinculoNaoEncontradoError(
            f'Vínculo {originador} / {numero_convenio} não encontrado. '
            'Cadastre a originadora no convênio antes do custo.'
        )


def _registro_de_custo(
    dados: Mapping[str, Any], originador: str, numero_convenio: str
) -> dict[str, Any]:
    """Normaliza o payload do formulário no registro gravado."""
    return {
        'id': f'{chave_vinculo(originador, numero_convenio)}'
        f'|{texto(dados.get("competencia_inicio"))}',
        'originador': originador,
        'numero_convenio': numero_convenio,
        'metodo': texto(dados.get('metodo')),
        'base_calculo': texto(dados.get('base_calculo')),
        'aliquota_percentual': numero(dados.get('aliquota_percentual')),
        'valor_fixo': numero(dados.get('valor_fixo')),
        'valor_unitario': numero(dados.get('valor_unitario')),
        'criterio_faixa': texto(dados.get('criterio_faixa')),
        'faixas': [dict(faixa) for faixa in dados.get('faixas') or []],
        'competencia_inicio': texto(dados.get('competencia_inicio')),
        'competencia_fim': texto(dados.get('competencia_fim')),
        'observacao': texto(dados.get('observacao')),
        'status': texto(dados.get('status')) or StatusRegistro.ATIVO.value,
        'criado_em': _agora(),
    }


def alternar_status_custo(
    pasta_banco: Path,
    originador: str,
    numero_convenio: str,
    competencia_inicio: str,
    ativo: bool,
) -> list[dict[str, Any]]:
    """Ativa ou desativa uma versão de custo do vínculo.

    Custo desativado não é aplicado — ``custo_vigente`` já o ignora por
    :func:`api.domain_convenios.esta_vigente`. O histórico é preservado;
    reativar devolve o custo ao cálculo.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        originador: Originadora do vínculo.
        numero_convenio: Número do convênio naquela originadora.
        competencia_inicio: Competência inicial que identifica a versão.
        ativo: ``True`` ativa, ``False`` desativa.

    Returns:
        O histórico de custo após a alteração.

    Raises:
        RegistroInvalidoError: Se não houver custo com essa competência.
        ArmazenamentoIndisponivelError: Se a gravação falhar.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    alvo = texto(competencia_inicio)
    historico = _ler_custos(raiz, originador, numero_convenio)
    if not any(texto(c.get('competencia_inicio')) == alvo for c in historico):
        raise RegistroInvalidoError(
            f'Custo com início {alvo!r} não encontrado neste vínculo.'
        )

    status = (
        StatusRegistro.ATIVO.value if ativo else StatusRegistro.INATIVO.value
    )
    novos = [
        {**c, 'status': status}
        if texto(c.get('competencia_inicio')) == alvo
        else dict(c)
        for c in historico
    ]
    gravar_arquivo(
        caminho_registro(raiz, TABELA_CUSTO, originador, numero_convenio),
        montar_documento(TABELA_CUSTO, originador, numero_convenio, novos),
    )
    logger.info(
        'Custo %s de %s/%s: %s',
        alvo,
        originador,
        numero_convenio,
        status,
    )

    return listar_custos(pasta_banco, originador, numero_convenio)


def confrontar(
    pasta_banco: Path,
    originador: str,
    numero_convenio: str,
    competencia: str,
    dados: Mapping[str, Any],
) -> dict[str, Any]:
    """Calcula o custo aplicado e classifica o status do financeiro.

    É a fonte única do confronto: pega o custo **vigente e ativo** do
    vínculo, aplica a regra cadastrada (percentual, fixo, por contrato,
    faixa) sobre os valores da competência e classifica o status pela
    diferença (:mod:`api.domain_confronto`). O front só exibe.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        originador: Originadora do vínculo.
        numero_convenio: Número do convênio naquela originadora.
        competencia: Competência ``AAAA-MM`` do vencimento.
        dados: ``valor_remessa``, ``valor_retorno``, ``valor_recebido`` e
            ``quantidade`` (quantidade só pesa em custo por contrato/faixa).

    Returns:
        O confronto (status, esperado, custo, devendo, ...) com o resumo
        do custo e se a quantidade é exigida pela regra.

    Raises:
        ArmazenamentoIndisponivelError: Se a pasta do banco não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)
    custo = custo_vigente(
        _ler_custos(raiz, originador, numero_convenio), competencia
    )
    apuracao = BaseApuracao(
        valor_remessa=numero(dados.get('valor_remessa')),
        valor_retorno=numero(dados.get('valor_retorno')),
        valor_repasse=numero(dados.get('valor_recebido')),
        quantidade_contratos=int(numero(dados.get('quantidade'))),
    )
    valor_custo = calcular_custo(custo, apuracao)
    confronto = classificar_confronto(
        numero(dados.get('valor_retorno')),
        numero(dados.get('valor_recebido')),
        valor_custo,
    )

    return {
        **confronto,
        'custo_resumo': descrever_custo(custo),
        'exige_quantidade': _exige_quantidade(custo),
    }


def _exige_quantidade(custo: Mapping[str, Any] | None) -> bool:
    """Diz se a regra de custo precisa da quantidade recebida.

    Percentual e fixo não pedem quantidade; por contrato e faixa por
    quantidade pedem, pois o custo depende do número de contratos/linhas.
    """
    if not custo:
        return False

    metodo = texto(custo.get('metodo'))
    if metodo == MetodoCusto.POR_CONTRATO.value:
        return True
    if metodo == MetodoCusto.FAIXA.value:
        return (
            texto(custo.get('criterio_faixa'))
            == CriterioFaixa.QUANTIDADE.value
        )

    return False


# =====================================================================
# Visão de conciliação mensal
# =====================================================================
def listar_ativos_para_conciliacao(
    pasta_banco: Path, competencia: str
) -> list[dict[str, Any]]:
    """Lista os vínculos que entram na conciliação de uma competência.

    É a resposta operacional da pergunta "o que eu tenho que conciliar
    este mês": todo vínculo vigente na competência, com o custo que vale
    nela. Vínculo encerrado antes do mês, ou que ainda não começou, fica
    de fora sem ninguém precisar lembrar de desmarcá-lo.

    Args:
        pasta_banco: Raiz do banco de arquivos.
        competencia: Competência ``AAAA-MM``.

    Returns:
        Vínculos vigentes, ordenados por originadora e nome do convênio.

    Raises:
        ArmazenamentoIndisponivelError: Se a pasta do banco não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    raiz = garantir_raiz(pasta_banco)

    vigentes = [
        _montar_vinculo(raiz, vinculo, competencia)
        for vinculo in _ler_vinculos(raiz)
        if esta_vigente(vinculo, competencia)
    ]

    return sorted(
        vigentes,
        key=lambda v: (
            texto(v['originador']).lower(),
            texto(v['nome_convenio']).lower(),
        ),
    )
