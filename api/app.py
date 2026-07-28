# INSERIR EM: api/app.py
# DEPENDÊNCIA: pip install fastapi uvicorn
"""Aplicação FastAPI que serve o front e expõe os dados dos bancos.

O front (HTML/CSS) permanece exatamente como está: mudou apenas a origem
dos dados, que antes vinha de upload de .xlsx/.csv e agora vem daqui.

Rotas:
    GET    /api/status
    GET    /api/retorno
    GET    /api/analitico/filtros
    GET    /api/analitico/sintetico
    GET    /api/analitico/convenio
    GET    /api/cobranca/casos
    POST   /api/cobranca/casos
    POST   /api/cobranca/casos/lote
    PATCH  /api/cobranca/casos/{id_caso}/status
    DELETE /api/cobranca/casos/{id_caso}
    POST   /api/cobranca/casos/{id_caso}/tentativas
    POST   /api/cobranca/casos/{id_caso}/agendamentos
    PATCH  /api/cobranca/casos/{id_caso}/agendamentos/{id_agenda}/concluir

Gestão de convênios — POST cria (chave nasce no corpo), PUT altera
(chave vem da rota e não é editável):

    GET    /api/convenios
    POST   /api/convenios
    GET    /api/convenios/ativos
    GET    /api/convenios/{cnpj}
    PUT    /api/convenios/{cnpj}
    POST   /api/convenios/{cnpj}/originadoras
    PUT    /api/vinculos/{originador}/{numero_convenio}
    DELETE /api/vinculos/{originador}/{numero_convenio}
    GET    /api/vinculos/{originador}/{numero_convenio}/custos
    POST   /api/vinculos/{originador}/{numero_convenio}/custos
    GET    /api/originadoras
    POST   /api/originadoras
    PUT    /api/originadoras/{nome}
    DELETE /api/originadoras/{nome}

Gerência de convênios pela Conciliação — estado próprio da mesa
(liga/desliga e primeiro vencimento) e a geração de competência, que
migrou da Gestão para cá porque quem decide o que entra é a mesa:

    GET    /api/conciliacao/gerencia
    PATCH  /api/conciliacao/gerencia/{originador}/{numero_convenio}
    POST   /api/conciliacao/gerencia/gerar-competencia
    POST   /api/conciliacao/gerencia/gerar-periodo
    GET    /api/conciliacao/gerencia/originadoras
    PATCH  /api/conciliacao/gerencia/originadoras/{nome}
    POST   /api/conciliacao/gerencia/originadoras/{nome}/gerar-competencia
    POST   /api/conciliacao/gerencia/originadoras/{nome}/gerar-periodo
"""

from __future__ import annotations

# --- stdlib ---
import getpass
import logging
import os
from typing import Any

# --- terceiros ---
from fastapi import FastAPI, Header, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# --- locais ---
from api import __version__
from api.arquivos import ArmazenamentoIndisponivelError
from api.config import PASTA_FRONT, obter_configuracao
from api.database import BancoIndisponivelError
from api.repositories import analitico as repo_analitico
from api.repositories import cobranca as repo_cobranca
from api.repositories import conciliacao as repo_conciliacao
from api.repositories import conciliacao_gerencia as repo_gerencia
from api.repositories import convenios as repo_convenios
from api.repositories import geracao as repo_geracao
from api.repositories import remessas as repo_remessas
from api.repositories import responsaveis as repo_responsaveis
from api.schemas import (
    AgendamentoEntrada,
    CasoEntrada,
    CasosEmLoteEntrada,
    ColaboradorAlteracao,
    ColaboradorEntrada,
    ConfrontoEntrada,
    ConvenioAlteracao,
    ConvenioEntrada,
    CustoEntrada,
    CustoStatusEntrada,
    EstadoGerenciaEntrada,
    EstadoOriginadoraEntrada,
    GeracaoEntrada,
    GeracaoPeriodoEntrada,
    GeracaoPeriodoOriginadoraEntrada,
    OriginadoraAlteracao,
    OriginadoraEntrada,
    RemessaEntrada,
    StatusEntrada,
    SubstituicaoEntrada,
    TentativaEntrada,
    TitularEntrada,
    VencimentarioEntrada,
    VinculoAlteracao,
    VinculoEntrada,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title='Controle Operacional — API',
    version=__version__,
    description='Leitura dos bancos SQLite do projeto para o painel SCO.',
)


def _ator(usuario: str | None) -> str:
    """Identifica quem executou a operação, para auditoria.

    Args:
        usuario: Valor do cabeçalho ``X-Usuario`` enviado pelo front.

    Returns:
        Nome do usuário; cai para o usuário do SO quando ausente.
    """
    return (
        (usuario or '').strip()
        or os.getenv('USERNAME')
        or getpass.getuser()
        or 'desconhecido'
    )


def _erro_banco(
    exc: BancoIndisponivelError | ArmazenamentoIndisponivelError,
) -> HTTPException:
    """Traduz indisponibilidade de fonte de dados em 503 com mensagem útil."""
    logger.error('Fonte de dados indisponível: %s', exc)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=str(exc),
    )


def _erro_dados(exc: Exception) -> HTTPException:
    """Devolve como 400 o que a regra de negócio reprovou.

    A mensagem vai crua para o painel de propósito: quem escreveu a regra
    em ``api.domain_convenios`` já a redigiu para o operador ler.
    """
    logger.warning('Payload recusado pela regra de negócio: %s', exc)
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=str(exc),
    )


def _erro_conflito(exc: Exception) -> HTTPException:
    """Devolve como 409 o choque com um registro que já existe.

    Cobre os dois lados da imutabilidade da chave: criar em cima de uma
    chave ocupada e tentar alterar uma chave já gravada.
    """
    logger.warning('Conflito de chave: %s', exc)
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=str(exc),
    )


# =====================================================================
# Status
# =====================================================================
@app.get('/api/status')
def obter_status() -> dict[str, Any]:
    """Informa quais fontes estão acessíveis e com quantos registros.

    Returns:
        Diagnóstico das duas bases usadas pelo painel.
    """
    config = obter_configuracao()

    try:
        total_conciliacao = len(
            repo_conciliacao.listar_linhas(config.banco_conciliacao)
        )
        conciliacao_ok = True
    except BancoIndisponivelError as exc:
        logger.warning('Conciliação indisponível: %s', exc)
        total_conciliacao, conciliacao_ok = 0, False

    try:
        total_casos = len(repo_cobranca.listar_casos(config.banco_cobranca))
        cobranca_ok = True
    except BancoIndisponivelError as exc:
        logger.warning('Cobrança indisponível: %s', exc)
        total_casos, cobranca_ok = 0, False

    return {
        'versao': __version__,
        'conciliacao': {
            'disponivel': conciliacao_ok,
            'banco': str(config.banco_conciliacao),
            'registros': total_conciliacao,
        },
        'cobranca': {
            'disponivel': cobranca_ok,
            'banco': str(config.banco_cobranca),
            'casos': total_casos,
        },
    }


# =====================================================================
# Retorno BPO (leitura da conciliação COFCT)
# =====================================================================
@app.get('/api/retorno')
def obter_retorno() -> dict[str, Any]:
    """Devolve os valores descontados por convênio e competência.

    Returns:
        Estrutura ``{rows}`` esperada pelo front.

    Raises:
        HTTPException: 503 quando o banco de conciliação não abre.
    """
    config = obter_configuracao()

    try:
        return {
            'rows': repo_conciliacao.listar_retorno(config.banco_conciliacao)
        }
    except BancoIndisponivelError as exc:
        raise _erro_banco(exc) from exc


@app.get('/api/contatos')
def obter_contatos() -> dict[str, Any]:
    """Devolve o contato ATIVO de cada convênio, indexado pelo número.

    Returns:
        Estrutura ``{contatos: {numero_convenio: {...}}}``.
    """
    config = obter_configuracao()
    return {
        'contatos': repo_conciliacao.mapear_contatos_por_convenio(
            config.banco_conciliacao
        )
    }


# =====================================================================
# Controle Sintético / Analítico (leitura do COFCT)
# =====================================================================
@app.get('/api/analitico/filtros')
def obter_filtros() -> dict[str, Any]:
    """Lista as competências e originadoras do snapshot de conciliação.

    Returns:
        Estrutura ``{competencias: [...], originadores: [...]}``.

    Raises:
        HTTPException: 503 quando o banco de conciliação não abre.
    """
    config = obter_configuracao()

    try:
        return repo_analitico.listar_filtros(config.pasta_banco)
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc


@app.get('/api/analitico/sintetico')
def obter_sintetico(competencia: str, originador: str) -> dict[str, Any]:
    """Lista os convênios de uma competência, resumidos por originadora.

    Args:
        competencia: Competência no formato ``MM/AAAA``.
        originador: Originadora selecionada no filtro.

    Returns:
        Estrutura ``{linhas: [...]}`` — uma linha por convênio.

    Raises:
        HTTPException: 503 quando o banco de conciliação não abre.
    """
    config = obter_configuracao()

    try:
        linhas = repo_analitico.listar_sintetico(
            config.pasta_banco, competencia, originador
        )
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'linhas': linhas}


@app.get('/api/analitico/convenio')
def obter_convenio(originador: str, numero_convenio: str) -> dict[str, Any]:
    """Devolve o convênio completo do Controle Analítico.

    Traz os vencimentários de todas as competências e as abas
    compartilhadas (particularidade, conta e contato).

    Args:
        originador: Originadora do convênio.
        numero_convenio: Número do convênio.

    Returns:
        Estrutura ``{convenio: {...}}``.

    Raises:
        HTTPException: 404 se o convênio não existe; 503 se o banco não
            abre.
    """
    config = obter_configuracao()

    try:
        convenio = repo_analitico.obter_convenio(
            config.pasta_banco, originador, numero_convenio
        )
    except repo_analitico.ConvenioNaoEncontradoError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'convenio': convenio}


# =====================================================================
# Cobrança PJ (leitura e escrita)
# =====================================================================
@app.get('/api/cobranca/casos')
def listar_casos() -> dict[str, Any]:
    """Lista os casos de cobrança com tentativas e agendamentos.

    Returns:
        Estrutura ``{casos: [...]}``.

    Raises:
        HTTPException: 503 quando o banco de cobrança não abre.
    """
    config = obter_configuracao()

    try:
        return {'casos': repo_cobranca.listar_casos(config.banco_cobranca)}
    except BancoIndisponivelError as exc:
        raise _erro_banco(exc) from exc


@app.post('/api/cobranca/casos', status_code=status.HTTP_201_CREATED)
def criar_caso(
    entrada: CasoEntrada,
    x_usuario: str | None = Header(default=None),
) -> dict[str, Any]:
    """Cria um caso de cobrança avulso (botão "Novo Registro").

    Args:
        entrada: Payload validado do formulário.
        x_usuario: Usuário logado no front.

    Returns:
        Estrutura ``{casos: [...]}`` com o caso criado (vazia se duplicado).

    Raises:
        HTTPException: 503 quando o banco de cobrança não abre.
    """
    config = obter_configuracao()

    try:
        criados = repo_cobranca.inserir_casos(
            config.banco_cobranca, [entrada.model_dump()], _ator(x_usuario)
        )
    except BancoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'casos': criados}


@app.post('/api/cobranca/casos/lote', status_code=status.HTTP_201_CREATED)
def criar_casos_em_lote(
    entrada: CasosEmLoteEntrada,
    x_usuario: str | None = Header(default=None),
) -> dict[str, Any]:
    """Cria vários casos de uma vez (botão "Gerar da Conciliação").

    Args:
        entrada: Lista de casos derivados das divergências.
        x_usuario: Usuário logado no front.

    Returns:
        Estrutura ``{casos: [...]}`` apenas com os efetivamente criados.

    Raises:
        HTTPException: 503 quando o banco de cobrança não abre.
    """
    config = obter_configuracao()

    try:
        criados = repo_cobranca.inserir_casos(
            config.banco_cobranca,
            [caso.model_dump() for caso in entrada.casos],
            _ator(x_usuario),
        )
    except BancoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'casos': criados}


@app.patch('/api/cobranca/casos/{id_caso}/status')
def alterar_status(id_caso: int, entrada: StatusEntrada) -> dict[str, Any]:
    """Altera o status de um caso de cobrança.

    Args:
        id_caso: Identificador do caso.
        entrada: Novo status.

    Returns:
        Estrutura ``{caso: {...}}`` com o caso atualizado.

    Raises:
        HTTPException: 404 se o caso não existe; 503 se o banco não abre.
    """
    config = obter_configuracao()

    try:
        caso = repo_cobranca.atualizar_status(
            config.banco_cobranca, id_caso, entrada.status
        )
    except repo_cobranca.CasoNaoEncontradoError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except BancoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'caso': caso}


@app.delete(
    '/api/cobranca/casos/{id_caso}', status_code=status.HTTP_204_NO_CONTENT
)
def excluir_caso(id_caso: int) -> None:
    """Exclui um caso e seus registros filhos.

    Args:
        id_caso: Identificador do caso.

    Raises:
        HTTPException: 404 se o caso não existe; 503 se o banco não abre.
    """
    config = obter_configuracao()

    try:
        repo_cobranca.excluir_caso(config.banco_cobranca, id_caso)
    except repo_cobranca.CasoNaoEncontradoError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except BancoIndisponivelError as exc:
        raise _erro_banco(exc) from exc


@app.post(
    '/api/cobranca/casos/{id_caso}/tentativas',
    status_code=status.HTTP_201_CREATED,
)
def registrar_tentativa(
    id_caso: int,
    entrada: TentativaEntrada,
    x_usuario: str | None = Header(default=None),
) -> dict[str, Any]:
    """Registra uma tentativa de contato no caso.

    Args:
        id_caso: Identificador do caso.
        entrada: Data/hora, canal, resultado e observação.
        x_usuario: Usuário logado no front.

    Returns:
        Estrutura ``{caso: {...}}`` com o caso atualizado.

    Raises:
        HTTPException: 404 se o caso não existe; 503 se o banco não abre.
    """
    config = obter_configuracao()

    try:
        caso = repo_cobranca.registrar_tentativa(
            config.banco_cobranca,
            id_caso,
            entrada.model_dump(),
            _ator(x_usuario),
        )
    except repo_cobranca.CasoNaoEncontradoError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except BancoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'caso': caso}


@app.post(
    '/api/cobranca/casos/{id_caso}/agendamentos',
    status_code=status.HTTP_201_CREATED,
)
def agendar_conversa(
    id_caso: int,
    entrada: AgendamentoEntrada,
    x_usuario: str | None = Header(default=None),
) -> dict[str, Any]:
    """Agenda uma conversa de negociação para o caso.

    Args:
        id_caso: Identificador do caso.
        entrada: Data/hora, assunto e observação.
        x_usuario: Usuário logado no front.

    Returns:
        Estrutura ``{caso: {...}}`` com o caso atualizado.

    Raises:
        HTTPException: 404 se o caso não existe; 503 se o banco não abre.
    """
    config = obter_configuracao()

    try:
        caso = repo_cobranca.agendar_conversa(
            config.banco_cobranca,
            id_caso,
            entrada.model_dump(),
            _ator(x_usuario),
        )
    except repo_cobranca.CasoNaoEncontradoError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except BancoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'caso': caso}


@app.patch('/api/cobranca/casos/{id_caso}/agendamentos/{id_agenda}/concluir')
def concluir_agendamento(id_caso: int, id_agenda: int) -> dict[str, Any]:
    """Marca um agendamento como concluído.

    Args:
        id_caso: Identificador do caso.
        id_agenda: Identificador do agendamento.

    Returns:
        Estrutura ``{caso: {...}}`` com o caso atualizado.

    Raises:
        HTTPException: 404 se o caso não existe; 503 se o banco não abre.
    """
    config = obter_configuracao()

    try:
        caso = repo_cobranca.concluir_agendamento(
            config.banco_cobranca, id_caso, id_agenda
        )
    except repo_cobranca.CasoNaoEncontradoError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except BancoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'caso': caso}


# =====================================================================
# Gestão de convênios, originadoras e custos
# =====================================================================
# A visão é **convênio → originadoras**: o convênio é o assunto, e cada
# originadora que o opera é uma linha dele, com número, vigência e custo
# próprios. Por isso o vínculo nasce em /api/convenios/{cnpj}/originadoras
# e não numa rota de originadora.
@app.get('/api/convenios')
def listar_convenios(competencia: str = '') -> dict[str, Any]:
    """Lista os convênios com as originadoras que os operam.

    Args:
        competencia: Competência ``AAAA-MM`` para avaliar vigência e
            custo; vazio usa o mês corrente.

    Returns:
        Estrutura ``{convenios: [...]}``.

    Raises:
        HTTPException: 503 quando a pasta do banco não abre.
    """
    config = obter_configuracao()

    try:
        convenios = repo_convenios.listar_convenios(
            config.pasta_banco, competencia
        )
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'convenios': convenios}


@app.get('/api/convenios/ativos')
def listar_convenios_ativos(competencia: str) -> dict[str, Any]:
    """Lista o que entra na conciliação de uma competência.

    Args:
        competencia: Competência ``AAAA-MM``.

    Returns:
        Estrutura ``{competencia, vinculos: [...]}`` — um item por
        vínculo vigente, com o custo que vale naquele mês.

    Raises:
        HTTPException: 503 quando a pasta do banco não abre.
    """
    config = obter_configuracao()

    try:
        vinculos = repo_convenios.listar_ativos_para_conciliacao(
            config.pasta_banco, competencia
        )
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'competencia': competencia, 'vinculos': vinculos}


@app.post('/api/convenios', status_code=status.HTTP_201_CREATED)
def criar_convenio(entrada: ConvenioEntrada) -> dict[str, Any]:
    """Cadastra um convênio novo (o CNPJ nasce aqui e não muda mais).

    Args:
        entrada: CNPJ, nome, status e observação.

    Returns:
        Estrutura ``{convenio: {...}}`` com o registro gravado.

    Raises:
        HTTPException: 400 se o payload for inválido; 409 se o CNPJ já
            estiver cadastrado; 503 se o banco não abre.
    """
    config = obter_configuracao()

    try:
        convenio = repo_convenios.criar_convenio(
            config.pasta_banco, entrada.model_dump()
        )
    except repo_convenios.ChaveDuplicadaError as exc:
        raise _erro_conflito(exc) from exc
    except repo_convenios.RegistroInvalidoError as exc:
        raise _erro_dados(exc) from exc
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'convenio': convenio}


@app.put('/api/convenios/{cnpj}')
def atualizar_convenio(
    cnpj: str, entrada: ConvenioAlteracao
) -> dict[str, Any]:
    """Atualiza nome, status e observação de um convênio.

    O CNPJ vem da rota e não do corpo: ele é a chave e não é editável.

    Args:
        cnpj: CNPJ do convênio a atualizar.
        entrada: Campos editáveis.

    Returns:
        Estrutura ``{convenio: {...}}`` com o registro atualizado.

    Raises:
        HTTPException: 404 se o CNPJ não existe; 409 se o payload tentar
            mudar a chave; 503 se o banco não abre.
    """
    config = obter_configuracao()

    try:
        convenio = repo_convenios.atualizar_convenio(
            config.pasta_banco, cnpj, entrada.model_dump()
        )
    except repo_convenios.ConvenioNaoEncontradoError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except repo_convenios.ChaveImutavelError as exc:
        raise _erro_conflito(exc) from exc
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'convenio': convenio}


@app.get('/api/convenios/{cnpj}')
def obter_convenio_completo(
    cnpj: str, competencia: str = ''
) -> dict[str, Any]:
    """Devolve um convênio com todas as suas originadoras e custos.

    Args:
        cnpj: CNPJ do convênio, com ou sem máscara (só os dígitos
            importam).
        competencia: Competência ``AAAA-MM`` para vigência e custo.

    Returns:
        Estrutura ``{convenio: {...}}``.

    Raises:
        HTTPException: 404 se o CNPJ não existe; 503 se o banco não abre.
    """
    config = obter_configuracao()

    try:
        convenio = repo_convenios.obter_convenio(
            config.pasta_banco, cnpj, competencia
        )
    except repo_convenios.ConvenioNaoEncontradoError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'convenio': convenio}


@app.post(
    '/api/convenios/{cnpj}/originadoras', status_code=status.HTTP_201_CREATED
)
def criar_vinculo(cnpj: str, entrada: VinculoEntrada) -> dict[str, Any]:
    """Liga uma originadora ao convênio.

    O trio ``(cnpj, originador, numero_convenio)`` é fixado aqui e não
    muda mais — é a chave que o custo e a conciliação referenciam.

    Args:
        cnpj: CNPJ do convênio.
        entrada: Originadora, número naquela originadora e vigência.

    Returns:
        Estrutura ``{vinculo: {...}}`` com o vínculo gravado.

    Raises:
        HTTPException: 400 se o payload for inválido; 409 se o par
            originadora/número já existir; 503 se o banco não abre.
    """
    config = obter_configuracao()

    try:
        vinculo = repo_convenios.criar_vinculo(
            config.pasta_banco, cnpj, entrada.model_dump()
        )
    except repo_convenios.ChaveDuplicadaError as exc:
        raise _erro_conflito(exc) from exc
    except repo_convenios.RegistroInvalidoError as exc:
        raise _erro_dados(exc) from exc
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'vinculo': vinculo}


@app.put('/api/vinculos/{originador}/{numero_convenio}')
def atualizar_vinculo(
    originador: str, numero_convenio: str, entrada: VinculoAlteracao
) -> dict[str, Any]:
    """Atualiza vigência, status, averbadora e observação de um vínculo.

    Originadora e número vêm da rota: são a chave e não são editáveis.
    Para desligar o convênio nessa originadora, preencha
    ``competencia_fim`` — o histórico anterior continua explicável.

    Args:
        originador: Originadora do vínculo.
        numero_convenio: Número do convênio naquela originadora.
        entrada: Campos editáveis.

    Returns:
        Estrutura ``{vinculo: {...}}`` com o vínculo atualizado.

    Raises:
        HTTPException: 400 se a vigência for inválida; 404 se o vínculo
            não existe; 409 se o payload tentar mudar a chave; 503 se o
            banco não abre.
    """
    config = obter_configuracao()

    try:
        vinculo = repo_convenios.atualizar_vinculo(
            config.pasta_banco,
            originador,
            numero_convenio,
            entrada.model_dump(),
        )
    except repo_convenios.VinculoNaoEncontradoError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except repo_convenios.ChaveImutavelError as exc:
        raise _erro_conflito(exc) from exc
    except repo_convenios.RegistroInvalidoError as exc:
        raise _erro_dados(exc) from exc
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'vinculo': vinculo}


@app.delete(
    '/api/vinculos/{originador}/{numero_convenio}',
    status_code=status.HTTP_204_NO_CONTENT,
)
def desvincular_originadora(originador: str, numero_convenio: str) -> None:
    """Apaga o vínculo e o histórico de custo dele.

    Args:
        originador: Originadora do vínculo.
        numero_convenio: Número do convênio naquela originadora.

    Raises:
        HTTPException: 404 se o vínculo não existe; 503 se o banco não
            abre.
    """
    config = obter_configuracao()

    try:
        repo_convenios.excluir_vinculo(
            config.pasta_banco, originador, numero_convenio
        )
    except repo_convenios.VinculoNaoEncontradoError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc


@app.get('/api/vinculos/{originador}/{numero_convenio}/custos')
def listar_custos(originador: str, numero_convenio: str) -> dict[str, Any]:
    """Lê o histórico de custo de um vínculo.

    Args:
        originador: Originadora do vínculo.
        numero_convenio: Número do convênio naquela originadora.

    Returns:
        Estrutura ``{custos: [...]}``, do mais novo ao mais antigo.

    Raises:
        HTTPException: 503 quando a pasta do banco não abre.
    """
    config = obter_configuracao()

    try:
        custos = repo_convenios.listar_custos(
            config.pasta_banco, originador, numero_convenio
        )
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'custos': custos}


@app.post(
    '/api/vinculos/{originador}/{numero_convenio}/custos',
    status_code=status.HTTP_201_CREATED,
)
def salvar_custo(
    originador: str, numero_convenio: str, entrada: CustoEntrada
) -> dict[str, Any]:
    """Coloca um novo custo em vigor, encerrando o anterior.

    Args:
        originador: Originadora do vínculo.
        numero_convenio: Número do convênio naquela originadora.
        entrada: Método de custo e a competência em que passa a valer.

    Returns:
        Estrutura ``{custos: [...]}`` com o histórico após a gravação.

    Raises:
        HTTPException: 400 se o custo for inválido; 404 se o vínculo não
            existe; 503 se o banco não abre.
    """
    config = obter_configuracao()

    try:
        custos = repo_convenios.salvar_custo(
            config.pasta_banco,
            originador,
            numero_convenio,
            entrada.model_dump(),
        )
    except repo_convenios.VinculoNaoEncontradoError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except repo_convenios.RegistroInvalidoError as exc:
        raise _erro_dados(exc) from exc
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'custos': custos}


@app.patch('/api/vinculos/{originador}/{numero_convenio}/custos/status')
def alternar_custo(
    originador: str, numero_convenio: str, entrada: CustoStatusEntrada
) -> dict[str, Any]:
    """Ativa ou desativa uma versão de custo (desativado não é aplicado).

    Args:
        originador: Originadora do vínculo.
        numero_convenio: Número do convênio naquela originadora.
        entrada: Competência inicial da versão e o novo estado.

    Returns:
        Estrutura ``{custos: [...]}`` com o histórico após a alteração.

    Raises:
        HTTPException: 400 se a versão não existe; 503 se o banco não abre.
    """
    config = obter_configuracao()

    try:
        custos = repo_convenios.alternar_status_custo(
            config.pasta_banco,
            originador,
            numero_convenio,
            entrada.competencia_inicio,
            entrada.ativo,
        )
    except repo_convenios.RegistroInvalidoError as exc:
        raise _erro_dados(exc) from exc
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'custos': custos}


@app.post('/api/vinculos/{originador}/{numero_convenio}/confronto')
def confrontar_financeiro(
    originador: str, numero_convenio: str, entrada: ConfrontoEntrada
) -> dict[str, Any]:
    """Calcula o custo aplicado e classifica o status do financeiro.

    Fonte única do confronto: o front informa os valores e recebe de volta
    o status automático (Conciliado, a maior, a menor, Divergente, Sem
    Extrato, Sem Retorno), o custo aplicado e o quanto fica devendo.

    Args:
        originador: Originadora do vínculo.
        numero_convenio: Número do convênio naquela originadora.
        entrada: Competência e valores da apuração.

    Returns:
        Estrutura ``{confronto: {...}}``.

    Raises:
        HTTPException: 503 quando a pasta do banco não abre.
    """
    config = obter_configuracao()

    try:
        confronto = repo_convenios.confrontar(
            config.pasta_banco,
            originador,
            numero_convenio,
            entrada.competencia,
            entrada.model_dump(),
        )
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'confronto': confronto}


# =====================================================================
# Geração de vencimentários (clonar mês seguinte, avulso e exclusão)
# =====================================================================
# Fecham o ciclo da Gestão de Convênios: ela sabe quem está vigente num
# mês; estas rotas materializam os vencimentários daquele mês. O massivo
# clona o mês anterior e deixa um ticket para a automação do Datacob; o
# avulso e a exclusão gravam direto no banco de arquivos, com efeito
# imediato para o operador.
@app.post('/api/conciliacao/gerencia/gerar-competencia')
def gerar_competencia(
    entrada: GeracaoEntrada,
    x_usuario: str | None = Header(default=None),
) -> dict[str, Any]:
    """Gera a competência para todos os convênios vigentes e ligados.

    Clona o esqueleto de cada convênio a partir do mês anterior (valores
    zerados, status PENDENTE) e emite um ticket na fila para a automação
    do Datacob completar os saldos. É idempotente: convênio que já tem a
    competência gravada é preservado.

    Args:
        entrada: Competência ``AAAA-MM`` a gerar.
        x_usuario: Usuário logado no front.

    Returns:
        Estrutura ``{resumo: {...}}`` com gerados, pulados e o ticket.

    Raises:
        HTTPException: 503 quando a pasta do banco não abre.
    """
    config = obter_configuracao()

    try:
        resumo = repo_geracao.gerar_competencia(
            config.pasta_banco,
            entrada.competencia,
            config.pasta_fila_geracao,
            _ator(x_usuario),
        )
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'resumo': resumo}


@app.post(
    '/api/vinculos/{originador}/{numero_convenio}/vencimentarios',
    status_code=status.HTTP_201_CREATED,
)
def criar_vencimentario(
    originador: str,
    numero_convenio: str,
    entrada: VencimentarioEntrada,
) -> dict[str, Any]:
    """Cria um vencimentário avulso (o operador informa todos os campos).

    Originadora e número vêm da rota (identidade do vínculo);
    ``competencia`` e os demais campos vêm do corpo.

    Args:
        originador: Originadora do vínculo.
        numero_convenio: Número do convênio naquela originadora.
        entrada: Competência, data de vencimento e valores.

    Returns:
        Estrutura ``{vencimentario: {...}}`` com o registro gravado.

    Raises:
        HTTPException: 400 se o payload for inválido; 503 se o banco não
            abre.
    """
    config = obter_configuracao()
    dados = {
        **entrada.model_dump(),
        'originador': originador,
        'numero_convenio': numero_convenio,
    }

    try:
        vencimentario = repo_geracao.criar_vencimentario_avulso(
            config.pasta_banco, entrada.competencia, dados
        )
    except repo_geracao.VencimentarioInvalidoError as exc:
        raise _erro_dados(exc) from exc
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'vencimentario': vencimentario}


@app.delete(
    '/api/vinculos/{originador}/{numero_convenio}/vencimentarios',
    status_code=status.HTTP_204_NO_CONTENT,
)
def excluir_vencimentario(
    originador: str,
    numero_convenio: str,
    competencia: str,
    data_vencimento: str,
) -> None:
    """Exclui um vencimento específico de uma competência.

    Args:
        originador: Originadora do vínculo.
        numero_convenio: Número do convênio naquela originadora.
        competencia: Competência ``AAAA-MM`` do vencimento.
        data_vencimento: Data ``AAAA-MM-DD`` do vencimento a excluir.

    Raises:
        HTTPException: 404 se não houver vencimento nessa data; 503 se o
            banco não abre.
    """
    config = obter_configuracao()

    try:
        repo_geracao.excluir_vencimentario(
            config.pasta_banco,
            originador,
            numero_convenio,
            competencia,
            data_vencimento,
        )
    except repo_geracao.VencimentarioNaoEncontradoError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc


# =====================================================================
# Originadoras (submódulo próprio: cadastro de cada uma)
# =====================================================================
@app.get('/api/originadoras')
def listar_originadoras() -> dict[str, Any]:
    """Lista as originadoras cadastradas.

    Returns:
        Estrutura ``{originadoras: [...]}`` em ordem alfabética.

    Raises:
        HTTPException: 503 quando a pasta do banco não abre.
    """
    config = obter_configuracao()

    try:
        originadoras = repo_convenios.listar_originadoras(config.pasta_banco)
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'originadoras': originadoras}


@app.post('/api/originadoras', status_code=status.HTTP_201_CREATED)
def criar_originadora(entrada: OriginadoraEntrada) -> dict[str, Any]:
    """Cadastra uma originadora nova.

    O nome nasce aqui e não muda: ele é o prefixo do nome de arquivo de
    todo vínculo dela.

    Args:
        entrada: Nome (chave), CNPJ, status e observação.

    Returns:
        Estrutura ``{originadora: {...}}`` com o registro gravado.

    Raises:
        HTTPException: 400 se o payload for inválido; 409 se o nome já
            existir; 503 se o banco não abre.
    """
    config = obter_configuracao()

    try:
        originadora = repo_convenios.criar_originadora(
            config.pasta_banco, entrada.model_dump()
        )
    except repo_convenios.ChaveDuplicadaError as exc:
        raise _erro_conflito(exc) from exc
    except repo_convenios.RegistroInvalidoError as exc:
        raise _erro_dados(exc) from exc
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'originadora': originadora}


@app.put('/api/originadoras/{nome}')
def atualizar_originadora(
    nome: str, entrada: OriginadoraAlteracao
) -> dict[str, Any]:
    """Atualiza CNPJ, status e observação de uma originadora.

    Args:
        nome: Nome exato da originadora (chave, vem da rota).
        entrada: Campos editáveis.

    Returns:
        Estrutura ``{originadora: {...}}`` com o registro atualizado.

    Raises:
        HTTPException: 400 se a originadora não existe; 409 se o payload
            tentar mudar o nome; 503 se o banco não abre.
    """
    config = obter_configuracao()

    try:
        originadora = repo_convenios.atualizar_originadora(
            config.pasta_banco, nome, entrada.model_dump()
        )
    except repo_convenios.ChaveImutavelError as exc:
        raise _erro_conflito(exc) from exc
    except repo_convenios.RegistroInvalidoError as exc:
        raise _erro_dados(exc) from exc
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'originadora': originadora}


@app.delete('/api/originadoras/{nome}', status_code=status.HTTP_204_NO_CONTENT)
def excluir_originadora(nome: str) -> None:
    """Exclui uma originadora que ainda não tem convênio vinculado.

    Args:
        nome: Nome exato da originadora.

    Raises:
        HTTPException: 409 se houver vínculo apontando para ela; 503 se o
            banco não abre.
    """
    config = obter_configuracao()

    try:
        repo_convenios.excluir_originadora(config.pasta_banco, nome)
    except repo_convenios.RegistroEmUsoError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc


# =====================================================================
# Gerência de convênios pela Conciliação (estado próprio + geração)
# =====================================================================
# A mesa de conciliação governa a saúde do convênio: liga/desliga o que
# acompanha (sem tocar no cadastro da Gestão) e registra o primeiro
# vencimento. É também daqui que sai a geração de competência — massiva ou
# por período —, porque quem decide o que entra na conciliação é a mesa.
@app.get('/api/conciliacao/gerencia')
def listar_gerencia(competencia: str = '') -> dict[str, Any]:
    """Lista os convênios em conciliação com o estado próprio da mesa.

    Args:
        competencia: Competência ``AAAA-MM`` para avaliar a vigência;
            vazio usa o mês corrente.

    Returns:
        Estrutura ``{linhas: [...]}`` — uma linha por vínculo.

    Raises:
        HTTPException: 503 quando a pasta do banco não abre.
    """
    config = obter_configuracao()

    try:
        linhas = repo_gerencia.listar_gerencia(config.pasta_banco, competencia)
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'linhas': linhas}


# As rotas de originadora (grupo master) vêm ANTES da rota de convênio: o
# segmento literal "originadoras" não pode ser capturado pelo padrão
# {originador}/{numero_convenio}, que casaria dois segmentos quaisquer.
@app.get('/api/conciliacao/gerencia/originadoras')
def listar_gerencia_originadoras(competencia: str = '') -> dict[str, Any]:
    """Lista as originadoras com o estado da mesa e a contagem de convênios.

    Args:
        competencia: Competência ``AAAA-MM`` para avaliar a vigência;
            vazio usa o mês corrente.

    Returns:
        Estrutura ``{originadoras: [...]}`` — uma linha por originadora.

    Raises:
        HTTPException: 503 quando a pasta do banco não abre.
    """
    config = obter_configuracao()

    try:
        originadoras = repo_gerencia.listar_originadoras_gerencia(
            config.pasta_banco, competencia
        )
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'originadoras': originadoras}


@app.patch('/api/conciliacao/gerencia/originadoras/{nome}')
def atualizar_gerencia_originadora(
    nome: str,
    entrada: EstadoOriginadoraEntrada,
    x_usuario: str | None = Header(default=None),
) -> dict[str, Any]:
    """Ativa ou desativa uma originadora inteira na Conciliação.

    Desativar é o gate de grupo master: para toda a geração dos convênios
    dela sem mexer no toggle de cada um.

    Args:
        nome: Nome exato da originadora.
        entrada: Novo estado.
        x_usuario: Usuário logado no front.

    Returns:
        Estrutura ``{originadora: {...}}`` com o estado gravado.

    Raises:
        HTTPException: 404 se a originadora não existe; 503 se o banco não
            abre.
    """
    config = obter_configuracao()

    try:
        estado = repo_gerencia.atualizar_estado_originadora(
            config.pasta_banco,
            nome,
            entrada.em_conciliacao_ativa,
            _ator(x_usuario),
        )
    except repo_gerencia.OriginadoraNaoEncontradaError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'originadora': estado}


@app.post('/api/conciliacao/gerencia/originadoras/{nome}/gerar-competencia')
def gerar_competencia_de_originadora(
    nome: str,
    entrada: GeracaoEntrada,
    x_usuario: str | None = Header(default=None),
) -> dict[str, Any]:
    """Gera uma competência para todos os convênios de uma originadora.

    Args:
        nome: Nome exato da originadora.
        entrada: Competência ``AAAA-MM`` a gerar.
        x_usuario: Usuário logado no front.

    Returns:
        Estrutura ``{resumo: {...}}``.

    Raises:
        HTTPException: 503 quando a pasta do banco não abre.
    """
    config = obter_configuracao()

    try:
        resumo = repo_geracao.gerar_competencia_originadora(
            config.pasta_banco,
            nome,
            entrada.competencia,
            config.pasta_fila_geracao,
            _ator(x_usuario),
        )
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'resumo': resumo}


@app.post('/api/conciliacao/gerencia/originadoras/{nome}/gerar-periodo')
def gerar_periodo_de_originadora(
    nome: str,
    entrada: GeracaoPeriodoOriginadoraEntrada,
    x_usuario: str | None = Header(default=None),
) -> dict[str, Any]:
    """Gera um intervalo de competências para uma originadora inteira.

    Args:
        nome: Nome exato da originadora.
        entrada: Período (competência inicial → final).
        x_usuario: Usuário logado no front.

    Returns:
        Estrutura ``{resumo: {...}}``.

    Raises:
        HTTPException: 400 se o período for inválido; 503 se o banco não
            abre.
    """
    config = obter_configuracao()

    try:
        resumo = repo_geracao.gerar_competencias_periodo_originadora(
            config.pasta_banco,
            nome,
            entrada.competencia_inicio,
            entrada.competencia_fim,
            config.pasta_fila_geracao,
            _ator(x_usuario),
        )
    except repo_geracao.PeriodoInvalidoError as exc:
        raise _erro_dados(exc) from exc
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'resumo': resumo}


@app.patch('/api/conciliacao/gerencia/{originador}/{numero_convenio}')
def atualizar_gerencia(
    originador: str,
    numero_convenio: str,
    entrada: EstadoGerenciaEntrada,
    x_usuario: str | None = Header(default=None),
) -> dict[str, Any]:
    """Liga/desliga um vínculo ou registra o primeiro vencimento.

    Originadora e número vêm da rota (identidade do vínculo); o corpo traz
    só o que muda — o toggle, a data, ou ambos.

    Args:
        originador: Originadora do vínculo.
        numero_convenio: Número do convênio naquela originadora.
        entrada: Campos a alterar.
        x_usuario: Usuário logado no front.

    Returns:
        Estrutura ``{estado: {...}}`` com o estado gravado.

    Raises:
        HTTPException: 400 se o primeiro vencimento for inválido; 404 se o
            vínculo não existe; 503 se o banco não abre.
    """
    config = obter_configuracao()

    try:
        estado = repo_gerencia.atualizar_estado(
            config.pasta_banco,
            originador,
            numero_convenio,
            entrada.model_dump(),
            _ator(x_usuario),
        )
    except repo_gerencia.VinculoNaoEncontradoError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except repo_gerencia.EstadoInvalidoError as exc:
        raise _erro_dados(exc) from exc
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'estado': estado}


@app.post('/api/conciliacao/gerencia/gerar-periodo')
def gerar_periodo(
    entrada: GeracaoPeriodoEntrada,
    x_usuario: str | None = Header(default=None),
) -> dict[str, Any]:
    """Gera a competência de um convênio ao longo de um intervalo.

    Clona mês a mês, do início ao fim, respeitando vigência e liga/desliga.
    Convênio desligado devolve o resumo com ``desligado = true`` e nada
    gerado.

    Args:
        entrada: Vínculo (originadora + número) e o período.
        x_usuario: Usuário logado no front.

    Returns:
        Estrutura ``{resumo: {...}}``.

    Raises:
        HTTPException: 400 se o período for inválido; 404 se o vínculo não
            existe; 503 se o banco não abre.
    """
    config = obter_configuracao()

    try:
        resumo = repo_geracao.gerar_competencias_periodo(
            config.pasta_banco,
            entrada.originador,
            entrada.numero_convenio,
            entrada.competencia_inicio,
            entrada.competencia_fim,
            config.pasta_fila_geracao,
            _ator(x_usuario),
        )
    except repo_geracao.PeriodoInvalidoError as exc:
        raise _erro_dados(exc) from exc
    except repo_convenios.VinculoNaoEncontradoError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'resumo': resumo}


# =====================================================================
# Responsáveis pela conciliação (colaboradores + titular/substituição)
# =====================================================================
# O responsável efetivo é calculado: substituição vigente vence o titular;
# titular desligado vira "Usuário Não Cadastrado". Desligar um colaborador
# não reescreve os convênios dele — o efetivo muda por cálculo.
@app.get('/api/responsaveis/colaboradores')
def listar_colaboradores() -> dict[str, Any]:
    """Lista os colaboradores cadastrados."""
    config = obter_configuracao()

    try:
        colaboradores = repo_responsaveis.listar_colaboradores(
            config.pasta_banco
        )
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'colaboradores': colaboradores}


@app.post(
    '/api/responsaveis/colaboradores', status_code=status.HTTP_201_CREATED
)
def criar_colaborador(entrada: ColaboradorEntrada) -> dict[str, Any]:
    """Cadastra um colaborador novo (o nome é a chave)."""
    config = obter_configuracao()

    try:
        colaborador = repo_responsaveis.criar_colaborador(
            config.pasta_banco, entrada.model_dump()
        )
    except repo_responsaveis.ChaveDuplicadaError as exc:
        raise _erro_conflito(exc) from exc
    except repo_responsaveis.ColaboradorInvalidoError as exc:
        raise _erro_dados(exc) from exc
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'colaborador': colaborador}


@app.put('/api/responsaveis/colaboradores/{nome}')
def atualizar_colaborador(
    nome: str, entrada: ColaboradorAlteracao
) -> dict[str, Any]:
    """Atualiza status (inclui desligamento) e observação do colaborador."""
    config = obter_configuracao()

    try:
        colaborador = repo_responsaveis.atualizar_colaborador(
            config.pasta_banco, nome, entrada.model_dump()
        )
    except repo_responsaveis.ColaboradorNaoEncontradoError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'colaborador': colaborador}


@app.get('/api/responsaveis/{originador}/{numero_convenio}')
def obter_responsavel(originador: str, numero_convenio: str) -> dict[str, Any]:
    """Devolve o responsável do convênio, com o efetivo já calculado."""
    config = obter_configuracao()

    try:
        responsavel = repo_responsaveis.obter_responsavel(
            config.pasta_banco, originador, numero_convenio
        )
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'responsavel': responsavel}


@app.put('/api/responsaveis/{originador}/{numero_convenio}/titular')
def definir_titular(
    originador: str,
    numero_convenio: str,
    entrada: TitularEntrada,
    x_usuario: str | None = Header(default=None),
) -> dict[str, Any]:
    """Define ou troca o titular do convênio (vazio = desassocia)."""
    config = obter_configuracao()

    try:
        responsavel = repo_responsaveis.definir_titular(
            config.pasta_banco,
            originador,
            numero_convenio,
            entrada.colaborador,
            _ator(x_usuario),
        )
    except repo_responsaveis.ColaboradorNaoEncontradoError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'responsavel': responsavel}


@app.post('/api/responsaveis/{originador}/{numero_convenio}/substituicao')
def definir_substituicao(
    originador: str,
    numero_convenio: str,
    entrada: SubstituicaoEntrada,
    x_usuario: str | None = Header(default=None),
) -> dict[str, Any]:
    """Coloca um substituto temporário no convênio."""
    config = obter_configuracao()

    try:
        responsavel = repo_responsaveis.definir_substituicao(
            config.pasta_banco,
            originador,
            numero_convenio,
            entrada.model_dump(),
            _ator(x_usuario),
        )
    except repo_responsaveis.SubstituicaoInvalidaError as exc:
        raise _erro_dados(exc) from exc
    except repo_responsaveis.ColaboradorNaoEncontradoError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'responsavel': responsavel}


@app.delete('/api/responsaveis/{originador}/{numero_convenio}/substituicao')
def encerrar_substituicao(
    originador: str,
    numero_convenio: str,
    x_usuario: str | None = Header(default=None),
) -> dict[str, Any]:
    """Encerra a substituição, devolvendo a carteira ao titular."""
    config = obter_configuracao()

    try:
        responsavel = repo_responsaveis.encerrar_substituicao(
            config.pasta_banco,
            originador,
            numero_convenio,
            _ator(x_usuario),
        )
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'responsavel': responsavel}


# =====================================================================
# Remessas por vencimento (rastreio de envio + auditoria)
# =====================================================================
@app.get('/api/remessas/{originador}/{numero_convenio}')
def listar_remessas(
    originador: str, numero_convenio: str, competencia: str
) -> dict[str, Any]:
    """Lista os vencimentos da competência com o status de envio.

    Args:
        originador: Originadora do convênio.
        numero_convenio: Número do convênio naquela originadora.
        competencia: Competência ``AAAA-MM``.

    Returns:
        Estrutura ``{remessas: [...]}``.

    Raises:
        HTTPException: 503 quando a pasta do banco não abre.
    """
    config = obter_configuracao()

    try:
        remessas = repo_remessas.listar_remessas(
            config.pasta_banco, originador, numero_convenio, competencia
        )
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'remessas': remessas}


@app.put('/api/remessas/{originador}/{numero_convenio}')
def registrar_remessa(
    originador: str,
    numero_convenio: str,
    entrada: RemessaEntrada,
    x_usuario: str | None = Header(default=None),
) -> dict[str, Any]:
    """Registra ou atualiza a situação de envio de um vencimento.

    Args:
        originador: Originadora do convênio.
        numero_convenio: Número do convênio naquela originadora.
        entrada: Competência, vencimento, situação, data e observação.
        x_usuario: Usuário logado no front (responsável pelo envio).

    Returns:
        Estrutura ``{remessa: {...}}`` com o registro gravado.

    Raises:
        HTTPException: 400 se o payload for inválido; 404 se o vencimento
            não existe; 503 se o banco não abre.
    """
    config = obter_configuracao()

    try:
        remessa = repo_remessas.registrar_envio(
            config.pasta_banco,
            originador,
            numero_convenio,
            entrada.competencia,
            entrada.data_vencimento,
            entrada.model_dump(),
            _ator(x_usuario),
        )
    except repo_remessas.RemessaInvalidaError as exc:
        raise _erro_dados(exc) from exc
    except repo_remessas.VencimentoNaoEncontradoError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ArmazenamentoIndisponivelError as exc:
        raise _erro_banco(exc) from exc

    return {'remessa': remessa}


# =====================================================================
# Front estático (mantido exatamente como está em front/)
# =====================================================================
@app.get('/', include_in_schema=False)
def abrir_painel() -> FileResponse:
    """Serve a página inicial do painel.

    Returns:
        O ``front/index.html`` inalterado.
    """
    return FileResponse(PASTA_FRONT / 'index.html')


if PASTA_FRONT.exists():
    app.mount('/', StaticFiles(directory=PASTA_FRONT, html=True), name='front')
else:  # pragma: no cover - proteção contra instalação incompleta
    logger.error('Pasta do front não encontrada: %s', PASTA_FRONT)
