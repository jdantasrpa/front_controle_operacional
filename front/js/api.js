'use strict';

/* ============================================================
   api.js — Cliente HTTP da API de leitura dos bancos do projeto.

   ETAPA 1 (leitura): o painel lê o Controle Sintético e o Analítico
   de tabela_concilicacao_convenio (COFCT) e as abas compartilhadas
   (particularidade, conta e contato) do mesmo banco.

   A gravação ainda NÃO passa por aqui — no COFCT ela é feita pela fila
   de comandos (ver main.py). Enquanto isso, com a API no ar o painel
   opera em modo somente leitura; sem API, cai no store local de
   demonstração (data.js).

   Aberto direto do disco (file://) não há servidor para consultar.
   ============================================================ */

const API_BASE = '/api';

// Quando a página vem de file:// não há servidor para consultar.
const API_HABILITADA = location.protocol === 'http:' || location.protocol === 'https:';

let apiOnline = API_HABILITADA;

/* ---------------- Estado da conexão ---------------- */

function apiDisponivel() {
  return apiOnline;
}

async function _requisitar(metodo, caminho, corpo) {
  if (!API_HABILITADA) throw new Error('API indisponível em file://');

  const opcoes = { method: metodo, headers: {} };

  if (corpo !== undefined) {
    opcoes.headers['Content-Type'] = 'application/json';
    opcoes.body = JSON.stringify(corpo);
  }

  const resposta = await fetch(API_BASE + caminho, opcoes);

  if (!resposta.ok) {
    throw await _erroDaResposta(resposta, caminho);
  }

  apiOnline = true;
  return resposta.status === 204 ? null : resposta.json();
}

function _query(parametros) {
  return new URLSearchParams(parametros).toString();
}

/*
  A API devolve em `detail` uma mensagem já escrita para o operador ler
  ("O campo 'numero_convenio' é a chave..."). Extraí-la aqui evita que
  cada tela tenha de desembrulhar JSON para mostrar um recado decente.
*/
async function _erroDaResposta(resposta, caminho) {
  const bruto = await resposta.text().catch(() => '');
  let detalhe = bruto;

  try {
    const corpo = JSON.parse(bruto);
    if (typeof corpo.detail === 'string') detalhe = corpo.detail;
    else if (Array.isArray(corpo.detail)) {
      detalhe = corpo.detail.map((d) => d.msg || '').filter(Boolean).join(' ');
    }
  } catch (_) { /* resposta sem JSON: fica o texto cru */ }

  const erro = new Error(detalhe || `HTTP ${resposta.status} em ${caminho}`);
  erro.status = resposta.status;
  erro.caminho = caminho;
  return erro;
}

/* ---------------- Leitura ---------------- */

async function apiStatus() {
  return _requisitar('GET', '/status');
}

/** Competências e originadoras disponíveis no snapshot de conciliação. */
async function apiFiltros() {
  return _requisitar('GET', '/analitico/filtros');
}

/** Linhas do Controle Sintético de uma competência/originadora. */
async function apiSintetico(competencia, originador) {
  const corpo = await _requisitar(
    'GET',
    '/analitico/sintetico?' + _query({ competencia, originador }),
  );
  return corpo.linhas || [];
}

/** Convênio completo do Analítico, com os vencimentários de todas as competências. */
async function apiConvenio(originador, numeroConvenio) {
  const corpo = await _requisitar(
    'GET',
    '/analitico/convenio?' + _query({
      originador,
      numero_convenio: numeroConvenio,
    }),
  );
  return corpo.convenio;
}

/* ---------------- Gestão de convênios ---------------- */

/*
  Diferente do Sintético/Analítico, este módulo também escreve. A regra
  de negócio (método de custo, vigência) mora no servidor — aqui só
  passamos o payload e devolvemos o erro que ele mandar, para não existir
  uma segunda versão das regras vivendo no navegador.
*/

/** Convênios com as originadoras que os operam na competência. */
async function apiConvenios(competencia = '') {
  const corpo = await _requisitar('GET', '/convenios?' + _query({ competencia }));
  return corpo.convenios || [];
}

/** Um convênio com todas as suas originadoras e o custo de cada uma. */
async function apiConvenioPorCnpj(cnpj, competencia = '') {
  const corpo = await _requisitar(
    'GET', `/convenios/${encodeURIComponent(cnpj)}?` + _query({ competencia }),
  );
  return corpo.convenio;
}

/*
  Criar e alterar são chamadas distintas porque a chave é imutável: no
  POST ela vai no corpo, no PUT ela vem da rota e o corpo nem a menciona.
*/

/** Cadastra um convênio novo (CNPJ nasce aqui e não muda mais). */
async function apiCriarConvenio(dados) {
  const corpo = await _requisitar('POST', '/convenios', dados);
  return corpo.convenio;
}

/** Atualiza nome, status e observação de um convênio. */
async function apiAtualizarConvenio(cnpj, dados) {
  const corpo = await _requisitar(
    'PUT', `/convenios/${encodeURIComponent(cnpj)}`, dados,
  );
  return corpo.convenio;
}

/** Liga uma originadora ao convênio. */
async function apiCriarVinculo(cnpj, dados) {
  const corpo = await _requisitar(
    'POST', `/convenios/${encodeURIComponent(cnpj)}/originadoras`, dados,
  );
  return corpo.vinculo;
}

/** Atualiza vigência, status e averbadora de um vínculo já criado. */
async function apiAtualizarVinculo(originador, numeroConvenio, dados) {
  const corpo = await _requisitar(
    'PUT', _rotaVinculo(originador, numeroConvenio), dados,
  );
  return corpo.vinculo;
}

function _rotaVinculo(originador, numeroConvenio) {
  return `/vinculos/${encodeURIComponent(originador)}`
    + `/${encodeURIComponent(numeroConvenio)}`;
}

/** Apaga o vínculo e o histórico de custo dele. */
async function apiExcluirVinculo(originador, numeroConvenio) {
  return _requisitar('DELETE', _rotaVinculo(originador, numeroConvenio));
}

/** Histórico de custo de um vínculo, do mais novo ao mais antigo. */
async function apiCustos(originador, numeroConvenio) {
  const corpo = await _requisitar(
    'GET', _rotaVinculo(originador, numeroConvenio) + '/custos',
  );
  return corpo.custos || [];
}

/** Coloca um novo custo em vigor, encerrando o anterior. */
async function apiSalvarCusto(originador, numeroConvenio, dados) {
  const corpo = await _requisitar(
    'POST', _rotaVinculo(originador, numeroConvenio) + '/custos', dados,
  );
  return corpo.custos || [];
}

/** Ativa/desativa uma versão de custo (desativado não é aplicado). */
async function apiAlternarCusto(originador, numeroConvenio, competenciaInicio, ativo) {
  const corpo = await _requisitar(
    'PATCH', _rotaVinculo(originador, numeroConvenio) + '/custos/status',
    { competencia_inicio: competenciaInicio, ativo },
  );
  return corpo.custos || [];
}

/** Confronto financeiro de um vencimento (custo aplicado + status automático). */
async function apiConfronto(originador, numeroConvenio, dados) {
  const corpo = await _requisitar(
    'POST', _rotaVinculo(originador, numeroConvenio) + '/confronto', dados,
  );
  return corpo.confronto;
}

/* ---------------- Geração de vencimentários ---------------- */

/*
  Fecham o ciclo do módulo: a Gestão de Convênios sabe quem está vigente
  num mês; estas chamadas materializam os vencimentários daquele mês. O
  massivo clona o mês anterior e deixa um ticket para a automação do
  Datacob; o avulso e a exclusão gravam direto, com efeito imediato.
*/

/** Gera a competência para todos os convênios vigentes e ligados (massivo). */
async function apiGerarCompetencia(competencia) {
  const corpo = await _requisitar(
    'POST', '/conciliacao/gerencia/gerar-competencia', { competencia },
  );
  return corpo.resumo;
}

/** Lança um vencimentário avulso num vínculo (o operador informa tudo). */
async function apiCriarVencimentario(originador, numeroConvenio, dados) {
  const corpo = await _requisitar(
    'POST', _rotaVinculo(originador, numeroConvenio) + '/vencimentarios', dados,
  );
  return corpo.vencimentario;
}

/** Exclui um vencimento específico (mira pela data de vencimento). */
async function apiExcluirVencimentario(
  originador, numeroConvenio, competencia, dataVencimento,
) {
  return _requisitar(
    'DELETE',
    _rotaVinculo(originador, numeroConvenio) + '/vencimentarios?'
    + _query({ competencia, data_vencimento: dataVencimento }),
  );
}

/** Originadoras cadastradas. */
async function apiOriginadoras() {
  const corpo = await _requisitar('GET', '/originadoras');
  return corpo.originadoras || [];
}

/** Cadastra uma originadora nova (o nome é a chave e não muda). */
async function apiCriarOriginadora(dados) {
  const corpo = await _requisitar('POST', '/originadoras', dados);
  return corpo.originadora;
}

/** Atualiza CNPJ, status e observação de uma originadora. */
async function apiAtualizarOriginadora(nome, dados) {
  const corpo = await _requisitar(
    'PUT', '/originadoras/' + encodeURIComponent(nome), dados,
  );
  return corpo.originadora;
}

/** Exclui uma originadora sem convênio vinculado. */
async function apiExcluirOriginadora(nome) {
  return _requisitar('DELETE', '/originadoras/' + encodeURIComponent(nome));
}

/* ---------------- Gerência de convênios (Conciliação) ---------------- */

/*
  Estado próprio da mesa de conciliação, separado do cadastro da Gestão:
  o liga/desliga e o primeiro vencimento. A geração de competência —
  massiva (acima) e por período (abaixo) — também mora aqui, porque quem
  decide o que entra na conciliação é a mesa.
*/

/** Convênios em conciliação com o estado próprio da mesa. */
async function apiListarGerencia(competencia = '') {
  const corpo = await _requisitar(
    'GET', '/conciliacao/gerencia?' + _query({ competencia }),
  );
  return corpo.linhas || [];
}

/** Liga/desliga um vínculo ou registra o primeiro vencimento (parcial). */
async function apiAtualizarEstadoGerencia(originador, numeroConvenio, dados) {
  const corpo = await _requisitar(
    'PATCH',
    `/conciliacao/gerencia/${encodeURIComponent(originador)}`
    + `/${encodeURIComponent(numeroConvenio)}`,
    dados,
  );
  return corpo.estado;
}

/** Gera a competência de um convênio ao longo de um intervalo. */
async function apiGerarPeriodo(dados) {
  const corpo = await _requisitar(
    'POST', '/conciliacao/gerencia/gerar-periodo', dados,
  );
  return corpo.resumo;
}

/* Originadoras (grupo master): ativar/desativar a originadora inteira e
   gerar todos os convênios dela. Desativada não gera nada. */

function _rotaOriginadoraGr(nome) {
  return '/conciliacao/gerencia/originadoras/' + encodeURIComponent(nome);
}

/** Originadoras com o estado da mesa e a contagem de convênios. */
async function apiListarGerenciaOriginadoras(competencia = '') {
  const corpo = await _requisitar(
    'GET', '/conciliacao/gerencia/originadoras?' + _query({ competencia }),
  );
  return corpo.originadoras || [];
}

/** Ativa/desativa uma originadora inteira (gate de grupo master). */
async function apiAtivarOriginadora(nome, ativa) {
  const corpo = await _requisitar(
    'PATCH', _rotaOriginadoraGr(nome), { em_conciliacao_ativa: ativa },
  );
  return corpo.originadora;
}

/** Gera a competência de todos os convênios de uma originadora. */
async function apiGerarOriginadoraCompetencia(nome, competencia) {
  const corpo = await _requisitar(
    'POST', _rotaOriginadoraGr(nome) + '/gerar-competencia', { competencia },
  );
  return corpo.resumo;
}

/** Gera um intervalo de competências para uma originadora inteira. */
async function apiGerarOriginadoraPeriodo(nome, competenciaInicio, competenciaFim) {
  const corpo = await _requisitar(
    'POST', _rotaOriginadoraGr(nome) + '/gerar-periodo',
    { competencia_inicio: competenciaInicio, competencia_fim: competenciaFim },
  );
  return corpo.resumo;
}

/* ---------------- Responsáveis pela conciliação ---------------- */

/*
  Colaboradores (cadastro próprio) e o responsável de cada convênio. O
  responsável efetivo vem calculado do servidor: substituição vigente
  vence o titular; titular desligado vira "Usuário Não Cadastrado".
*/

/** Colaboradores cadastrados. */
async function apiListarColaboradores() {
  const corpo = await _requisitar('GET', '/responsaveis/colaboradores');
  return corpo.colaboradores || [];
}

/** Cadastra um colaborador novo (o nome é a chave). */
async function apiCriarColaborador(dados) {
  const corpo = await _requisitar('POST', '/responsaveis/colaboradores', dados);
  return corpo.colaborador;
}

/** Atualiza status (inclui desligamento) e observação do colaborador. */
async function apiAtualizarColaborador(nome, dados) {
  const corpo = await _requisitar(
    'PUT', '/responsaveis/colaboradores/' + encodeURIComponent(nome), dados,
  );
  return corpo.colaborador;
}

function _rotaResponsavel(originador, numeroConvenio, sufixo = '') {
  return `/responsaveis/${encodeURIComponent(originador)}`
    + `/${encodeURIComponent(numeroConvenio)}${sufixo}`;
}

/** Responsável do convênio, com o efetivo já calculado. */
async function apiObterResponsavel(originador, numeroConvenio) {
  const corpo = await _requisitar(
    'GET', _rotaResponsavel(originador, numeroConvenio),
  );
  return corpo.responsavel;
}

/** Define ou troca o titular (colaborador vazio desassocia). */
async function apiDefinirTitular(originador, numeroConvenio, colaborador) {
  const corpo = await _requisitar(
    'PUT', _rotaResponsavel(originador, numeroConvenio, '/titular'),
    { colaborador },
  );
  return corpo.responsavel;
}

/** Coloca um substituto temporário. */
async function apiDefinirSubstituicao(originador, numeroConvenio, dados) {
  const corpo = await _requisitar(
    'POST', _rotaResponsavel(originador, numeroConvenio, '/substituicao'), dados,
  );
  return corpo.responsavel;
}

/** Encerra a substituição, devolvendo a carteira ao titular. */
async function apiEncerrarSubstituicao(originador, numeroConvenio) {
  const corpo = await _requisitar(
    'DELETE', _rotaResponsavel(originador, numeroConvenio, '/substituicao'),
  );
  return corpo.responsavel;
}

/* ---------------- Remessas por vencimento ---------------- */

function _rotaRemessa(originador, numeroConvenio) {
  return `/remessas/${encodeURIComponent(originador)}`
    + `/${encodeURIComponent(numeroConvenio)}`;
}

/** Vencimentos da competência com o status de envio. */
async function apiListarRemessas(originador, numeroConvenio, competencia) {
  const corpo = await _requisitar(
    'GET',
    _rotaRemessa(originador, numeroConvenio) + '?' + _query({ competencia }),
  );
  return corpo.remessas || [];
}

/** Registra/atualiza a situação de envio de um vencimento. */
async function apiRegistrarRemessa(originador, numeroConvenio, dados) {
  const corpo = await _requisitar(
    'PUT', _rotaRemessa(originador, numeroConvenio), dados,
  );
  return corpo.remessa;
}

/* ---------------- Diagnóstico ---------------- */

/**
 * Marca a API como indisponível e registra o motivo.
 * O painel segue funcionando no modo de demonstração (localStorage).
 *
 * @param {Error} erro Falha capturada na chamada HTTP.
 */
function apiRegistrarFalha(erro) {
  apiOnline = false;
  console.error('Falha ao falar com a API:', erro);
}
