# INSERIR EM: api/schemas.py
"""Contratos de entrada da API (validação Pydantic).

As respostas seguem o formato que o JavaScript já consumia, por isso são
devolvidas como dicionários montados em ``api.domain``. Aqui validamos
apenas o que entra — o que protege o banco de payloads malformados.
"""

from __future__ import annotations

# --- stdlib ---
from typing import Literal

# --- terceiros ---
from pydantic import BaseModel, ConfigDict, Field

# --- locais ---
from api.domain import (
    CANAIS_VALIDOS,
    RESULTADOS_VALIDOS,
    STATUS_COBRANCA_VALIDOS,
)
from api.domain_convenios import (
    BaseCalculo,
    CriterioFaixa,
    MetodoCusto,
    StatusRegistro,
)

StatusCobranca = Literal[STATUS_COBRANCA_VALIDOS]  # type: ignore[valid-type]
Canal = Literal[CANAIS_VALIDOS]  # type: ignore[valid-type]
Resultado = Literal[RESULTADOS_VALIDOS]  # type: ignore[valid-type]


class CasoEntrada(BaseModel):
    """Payload de criação de um caso de cobrança."""

    empresa: str = Field(min_length=1, description='Razão social do convênio')
    cnpj: str = ''
    contato: str = ''
    telefone: str = ''
    email: str = ''
    competencia: str = ''
    valorDivergente: float = 0.0
    status: StatusCobranca = 'pendente'
    observacao: str = ''
    origem: str = 'manual'
    originador: str = ''
    numeroConvenio: str = ''


class CasosEmLoteEntrada(BaseModel):
    """Payload de criação em lote (usado por "Gerar da Conciliação")."""

    casos: list[CasoEntrada] = Field(default_factory=list)


class StatusEntrada(BaseModel):
    """Payload de alteração de status de um caso."""

    status: StatusCobranca


class TentativaEntrada(BaseModel):
    """Payload de registro de uma tentativa de contato."""

    dataHora: str = Field(min_length=1)
    canal: Canal
    resultado: Resultado
    observacao: str = ''


class AgendamentoEntrada(BaseModel):
    """Payload de agendamento de uma conversa de negociação."""

    dataHora: str = Field(min_length=1)
    assunto: str = ''
    observacao: str = ''


# =====================================================================
# Gestão de convênios, originadoras e custos
# =====================================================================
# A validação aqui é só de forma (tipo e domínio de enum). As regras que
# cruzam campos — alíquota exigida no método percentual, competência
# final anterior à inicial — ficam em api.domain_convenios, para o painel
# e um eventual script de carga cobrarem exatamente as mesmas regras.
#
# Cada cadastro tem dois contratos, e a diferença entre eles é a chave:
# o de criação a exige, o de alteração nem a menciona. A chave é o nome
# do arquivo no banco — alterá-la não renomearia o registro, criaria
# outro e abandonaria o original com todo o histórico dele.
class ModeloDeCadastro(BaseModel):
    """Base dos payloads de cadastro deste módulo.

    ``use_enum_values`` faz o Pydantic guardar o **valor** do Enum, e não
    o membro. Sem isso, ``model_dump()`` devolveria ``MetodoCusto.
    PERCENTUAL``, que gravado no .txt viraria a string
    ``'MetodoCusto.PERCENTUAL'`` — ilegível no arquivo e reprovada pela
    validação do domínio, que compara com ``'PERCENTUAL'``.

    ``validate_default`` completa o serviço: por padrão o Pydantic não
    passa os valores default pela validação, então um campo **omitido**
    pelo front escapava como membro de Enum justamente onde ninguém
    olhava — o status de um cadastro novo, a base de cálculo de um
    degrau de faixa.
    """

    model_config = ConfigDict(use_enum_values=True, validate_default=True)


class OriginadoraEntrada(ModeloDeCadastro):
    """Payload de criação de uma originadora.

    ``codigo`` é o sufixo do número dos convênios daquela originadora
    (ex.: ``ALV`` gera ``00001ALV``) — usado na numeração automática.
    """

    nome: str = Field(
        min_length=1, description='Nome da originadora — chave, imutável'
    )
    codigo: str = ''
    cnpj: str = ''
    status: StatusRegistro = StatusRegistro.ATIVO
    observacao: str = ''


class OriginadoraAlteracao(ModeloDeCadastro):
    """Payload de alteração de uma originadora (sem o nome)."""

    codigo: str = ''
    cnpj: str = ''
    status: StatusRegistro = StatusRegistro.ATIVO
    observacao: str = ''


class ConvenioEntrada(ModeloDeCadastro):
    """Payload de criação de um convênio (mestre, chaveado por CNPJ).

    ``averbadora`` é do convênio (vale para todas as originadoras que o
    operam), não do vínculo.
    """

    cnpj_convenio: str = Field(
        min_length=1, description='CNPJ do convênio — chave, imutável'
    )
    nome_convenio: str = Field(min_length=1)
    averbadora: str = ''
    status: StatusRegistro = StatusRegistro.ATIVO
    status_producao: str = ''
    gestora_margem: str = ''
    link_gestora: str = ''
    observacao: str = ''


class ConvenioAlteracao(ModeloDeCadastro):
    """Payload de alteração de um convênio (sem o CNPJ)."""

    nome_convenio: str = Field(min_length=1)
    averbadora: str = ''
    status: StatusRegistro = StatusRegistro.ATIVO
    status_producao: str = ''
    gestora_margem: str = ''
    link_gestora: str = ''
    observacao: str = ''


class VinculoEntrada(ModeloDeCadastro):
    """Payload de criação da ligação de uma originadora a um convênio.

    ``numero_convenio`` é **gerado automaticamente** quando vazio: o
    próximo sequencial + o código da originadora (ex.: ``00001ALV``).
    A averbadora não vem aqui — é do convênio.
    """

    originador: str = Field(min_length=1)
    numero_convenio: str = ''
    status: StatusRegistro = StatusRegistro.ATIVO
    competencia_inicio: str = Field(
        min_length=1, description='Competência AAAA-MM em que passa a valer'
    )
    competencia_fim: str = ''
    observacao: str = ''


class VinculoAlteracao(ModeloDeCadastro):
    """Payload de alteração de um vínculo (sem originadora nem número).

    ``competencia_fim`` é o campo que desliga o convênio naquela
    originadora sem apagar o passado dele.
    """

    status: StatusRegistro = StatusRegistro.ATIVO
    competencia_inicio: str = Field(
        min_length=1, description='Competência AAAA-MM em que passa a valer'
    )
    competencia_fim: str = ''
    observacao: str = ''


class FaixaEntrada(ModeloDeCadastro):
    """Um degrau da tabela do método por faixa.

    ``ate`` igual a zero marca o último degrau, sem teto.
    """

    ate: float = 0.0
    metodo: MetodoCusto = MetodoCusto.PERCENTUAL
    base_calculo: BaseCalculo = BaseCalculo.VALOR_RETORNO
    aliquota_percentual: float = 0.0
    valor_fixo: float = 0.0
    valor_unitario: float = 0.0


class CustoEntrada(ModeloDeCadastro):
    """Payload do custo de um vínculo convênio × originadora."""

    metodo: MetodoCusto
    competencia_inicio: str = Field(
        min_length=1, description='Competência AAAA-MM em que passa a valer'
    )
    competencia_fim: str = ''
    base_calculo: BaseCalculo = BaseCalculo.VALOR_RETORNO
    aliquota_percentual: float = 0.0
    valor_fixo: float = 0.0
    valor_unitario: float = 0.0
    criterio_faixa: CriterioFaixa = CriterioFaixa.QUANTIDADE
    faixas: list[FaixaEntrada] = Field(default_factory=list)
    observacao: str = ''


class CustoStatusEntrada(BaseModel):
    """Payload do ativar/desativar de uma versão de custo."""

    competencia_inicio: str = Field(min_length=1)
    ativo: bool


class ConfrontoEntrada(BaseModel):
    """Payload do confronto financeiro de um vencimento.

    ``quantidade`` só pesa quando o custo é por contrato/faixa; o status é
    calculado no servidor a partir da diferença (recebido × esperado).
    """

    competencia: str = Field(min_length=1, description='Competência AAAA-MM')
    valor_remessa: float = 0.0
    valor_retorno: float = 0.0
    valor_recebido: float = 0.0
    quantidade: int = 0


# =====================================================================
# Geração de vencimentários
# =====================================================================
# A regra que decide o que gerar (clonar do mês anterior, zerar valores,
# recusar data fora da competência) mora em api.domain_geracao. Aqui a
# validação é só de forma — os valores são convertidos e cobrados lá.
class GeracaoEntrada(BaseModel):
    """Payload do "gerar competência" massivo."""

    competencia: str = Field(
        min_length=1, description='Competência AAAA-MM a gerar'
    )


class GeracaoPeriodoEntrada(BaseModel):
    """Payload da geração por período de um convênio.

    A pessoa escolhe o vínculo (originadora + número) e o intervalo de
    competências; a regra de validação do intervalo e o liga/desliga ficam
    em ``api.repositories.geracao`` e ``api.repositories.conciliacao_gerencia``.
    """

    originador: str = Field(min_length=1)
    numero_convenio: str = Field(min_length=1)
    competencia_inicio: str = Field(
        min_length=1, description='Competência AAAA-MM inicial'
    )
    competencia_fim: str = Field(
        min_length=1, description='Competência AAAA-MM final'
    )


# =====================================================================
# Gerência de convênios pela Conciliação (estado próprio da mesa)
# =====================================================================
class EstadoGerenciaEntrada(BaseModel):
    """Payload do liga/desliga e do controle de vencimento de um vínculo.

    Alteração parcial: ``None`` num campo preserva o valor gravado — o
    front manda só o que mudou. ``dia_vencimento`` é o dia do mês (1 a 30);
    os demais são offsets em dias (>= 0). A validação de faixa fica em
    ``api.domain_conciliacao_gerencia``.
    """

    # int define/atualiza; '' limpa; None (ausente) preserva o valor gravado.
    em_conciliacao_ativa: bool | None = None
    dia_vencimento: int | str | None = None
    dias_antes_remessa: int | str | None = None
    qtd_dias_sla_pagamento: int | str | None = None
    dias_antes_corte: int | str | None = None


class EstadoOriginadoraEntrada(BaseModel):
    """Payload do ativar/desativar de uma originadora (grupo master)."""

    em_conciliacao_ativa: bool


# =====================================================================
# Responsáveis pela conciliação
# =====================================================================
class ColaboradorEntrada(BaseModel):
    """Payload de criação de um colaborador (o nome é a chave)."""

    nome: str = Field(min_length=1)
    status: str = 'ATIVO'
    observacao: str = ''


class ColaboradorAlteracao(BaseModel):
    """Payload de alteração de um colaborador (status e observação).

    Desligar é mudar ``status`` para ``DESLIGADO``.
    """

    status: str = 'ATIVO'
    observacao: str = ''


class TitularEntrada(BaseModel):
    """Payload para definir o titular de um convênio.

    ``colaborador`` vazio devolve o convênio a ``Usuário Não Cadastrado``.
    """

    colaborador: str = ''


class SubstituicaoEntrada(BaseModel):
    """Payload de substituição temporária.

    ``substituicao_fim`` vazio = substituição aberta (sem data de retorno).
    """

    substituto: str = Field(min_length=1)
    substituicao_fim: str = ''


# =====================================================================
# Remessas por vencimento
# =====================================================================
class RemessaEntrada(BaseModel):
    """Payload do rastreio de envio de um vencimento.

    O usuário responsável vem do cabeçalho ``X-Usuario``; a regra de envio
    (dias antes da remessa, SLA, corte) fica no controle da gerência.
    """

    competencia: str = Field(min_length=1, description='Competência AAAA-MM')
    data_vencimento: str = Field(
        min_length=1, description='Vencimento AAAA-MM-DD'
    )
    situacao: str = 'PENDENTE'
    data_envio: str = ''
    observacao: str = ''


class GeracaoPeriodoOriginadoraEntrada(BaseModel):
    """Payload da geração por período de uma originadora inteira.

    A originadora vem da rota; o corpo traz só o intervalo.
    """

    competencia_inicio: str = Field(
        min_length=1, description='Competência AAAA-MM inicial'
    )
    competencia_fim: str = Field(
        min_length=1, description='Competência AAAA-MM final'
    )


class VencimentarioEntrada(BaseModel):
    """Payload do vencimentário avulso (o operador informa tudo).

    Originadora e número do convênio vêm da rota, não do corpo: são a
    identidade do vínculo dono do vencimentário. ``data_vencimento`` é a
    chave que distingue os vencimentos de um mesmo mês.
    """

    competencia: str = Field(
        min_length=1, description='Competência AAAA-MM do vencimentário'
    )
    data_vencimento: str = Field(
        min_length=1, description='Data AAAA-MM-DD do vencimento'
    )
    nome_convenio: str = ''
    cnpj_convenio: str = ''
    data_env_remessa: str = ''
    data_sla_concilicacao: str = ''
    qtd_dias_sla_pagamento: str = ''
    data_corte: str = ''
    valor_remessa: float = 0.0
    valor_retorno: float = 0.0
    valor_repasse: float = 0.0
    status_conciliacao: str = 'PENDENTE'
    motivo_falta_conciliacao: str = ''
    porcentagem_inadimplencia: float = 0.0
