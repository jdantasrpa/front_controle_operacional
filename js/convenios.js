'use strict';

/* ============================================================
   convenios.js — Módulo Gestão de Convênios.

   A visão é convênio → originadoras: o convênio (chaveado pelo CNPJ) é
   o assunto, e cada originadora que o opera é uma linha dele, com o
   número daquela originadora, a vigência e o custo próprios.

   CHAVES SÃO IMUTÁVEIS. CNPJ do convênio, nome da originadora e o par
   (originadora, número) do vínculo travam depois de criados — no banco
   de arquivos essa chave é o nome do arquivo, então editá-la criaria um
   registro novo e abandonaria o original com o histórico de custo dele.
   A tela reflete isso desabilitando o campo, e o servidor recusa com 409
   quem tentar por fora.

   Diferente do Sintético/Analítico, este módulo escreve — e depende da
   API: sem servidor (file://) ele avisa em vez de fingir que funciona.
   ============================================================ */

/* ---------------- Estado ---------------- */

let convenios = [];
let convenioAberto = null;
let vinculoSelecionado = null;
let originadoras = [];
let originadoraSelecionada = null;
let faixasEmEdicao = [];

const METODO_LABEL = {
  PERCENTUAL: 'Percentual sobre valor',
  FIXO_MENSAL: 'Valor fixo mensal',
  POR_CONTRATO: 'Valor por contrato',
  FAIXA: 'Faixa / escalonado',
};

const BASE_LABEL = {
  VALOR_RETORNO: 'Valor retorno',
  VALOR_REMESSA: 'Valor remessa',
  VALOR_REPASSE: 'Valor repasse',
};

/* ---------------- Utilitários ---------------- */

function competenciaDeHoje() {
  return new Date().toISOString().slice(0, 7);
}

function competenciaFiltro() {
  return $('#cv-competencia').value || competenciaDeHoje();
}

// Vigência aberta é o caso comum; mostrar 'até —' evita o operador achar
// que faltou preencher alguma coisa.
function rotuloVigencia(registro) {
  const inicio = registro.competencia_inicio || 'sempre';
  const fim = registro.competencia_fim || '—';
  return `${inicio} → ${fim}`;
}

function exigirApi(msgId) {
  if (apiDisponivel()) return false;
  msgInline(
    msgId,
    'Este módulo grava no banco e precisa do servidor: abra o painel pelo '
    + 'endereço http, não pelo arquivo.',
    'erro',
  );
  return true;
}

/*
  Campo de chave não some da tela: fica visível e travado, para o
  operador conferir a identidade do registro que está editando.
*/
function travarChave(campo, travado) {
  if (!campo) return;
  campo.disabled = travado;
  campo.classList.toggle('campo-chave', travado);
  campo.title = travado
    ? 'Chave do registro — não pode ser alterada depois do cadastro.'
    : '';
}

function lerFormulario(seletor, atributo) {
  const dados = {};
  $$(`${seletor} [data-${atributo}]`).forEach((el) => {
    dados[el.dataset[atributo]] = el.value.trim();
  });
  return dados;
}

function escreverFormulario(seletor, atributo, registro) {
  $$(`${seletor} [data-${atributo}]`).forEach((el) => {
    el.value = registro[el.dataset[atributo]] ?? '';
  });
}

/* ---------------- Lista de convênios ---------------- */

const COLS_CONVENIO = [
  { key: 'nome_convenio', label: 'Convênio', left: true },
  { key: 'cnpj_convenio', label: 'CNPJ' },
  { key: 'originadoras_texto', label: 'Originadoras', left: true, wrap: true },
  { key: 'total_originadoras', label: 'Total' },
  { key: 'total_vigentes', label: 'Vigentes' },
  { key: 'status', label: 'Status' },
];

function linhaDeConvenio(convenio) {
  return {
    ...convenio,
    originadoras_texto: convenio.originadoras
      .map((o) => `${o.originador} (${o.numero_convenio})`)
      .join(', '),
  };
}

function filtrarConvenios(lista, { vigencia, busca }) {
  const termo = (busca || '').toLowerCase();

  return lista
    .filter((c) => vigencia === 'todos'
      || (vigencia === 'vigentes' ? c.total_vigentes > 0 : c.total_vigentes === 0))
    .filter((c) => !termo || [
      c.nome_convenio, c.cnpj_convenio,
      ...c.originadoras.map((o) => `${o.originador} ${o.numero_convenio}`),
    ].join(' ').toLowerCase().includes(termo));
}

async function pesquisarConvenios() {
  if (!apiDisponivel()) {
    $('#cv-resumo').textContent =
      'Sem servidor: abra o painel pelo endereço http para usar este módulo.';
    return;
  }
  try {
    convenios = await apiConvenios(competenciaFiltro());
  } catch (erro) {
    apiRegistrarFalha(erro);
    toast('Não foi possível carregar os convênios: ' + erro.message, 'erro');
    return;
  }

  const visiveis = filtrarConvenios(convenios, {
    vigencia: $('#cv-vigencia').value,
    busca: $('#cv-busca').value,
  });

  $('#cv-resumo').textContent =
    `${visiveis.length} convênio(s) — competência ${competenciaFiltro()}`;
  renderGrid(
    $('#tbl-convenios'),
    COLS_CONVENIO,
    visiveis.map(linhaDeConvenio),
    (linha) => abrirConvenio(linha.cnpj_chave),
  );
}

/* ---------------- Detalhe do convênio ---------------- */

const COLS_VINCULO = [
  { key: 'originador', label: 'Originadora', left: true },
  { key: 'numero_convenio', label: 'N° do convênio' },
  { key: 'averbadora', label: 'Averbadora' },
  { key: 'vigencia', label: 'Vigência' },
  { key: 'situacao', label: 'Na competência' },
  { key: 'status', label: 'Status' },
  { key: 'custo_resumo', label: 'Custo vigente', left: true, wrap: true },
];

async function abrirConvenio(cnpj) {
  try {
    convenioAberto = await apiConvenioPorCnpj(cnpj, competenciaFiltro());
  } catch (erro) {
    toast('Não foi possível abrir o convênio: ' + erro.message, 'erro');
    return;
  }

  escreverFormulario('#page-convenio', 'c', convenioAberto);
  travarChave($('#cvd-cnpj'), true);
  $('#convenio-header').innerHTML =
    `<b>${convenioAberto.nome_convenio || '(sem nome)'}</b> — `
    + `${convenioAberto.cnpj_convenio} · `
    + `${convenioAberto.total_vigentes} de ${convenioAberto.total_originadoras} `
    + `originadora(s) vigente(s) em ${competenciaFiltro()}`;

  limparFormVinculo();
  renderVinculos();
  navegar('convenio');
}

function renderVinculos() {
  const linhas = convenioAberto.originadoras.map((v) => ({
    ...v,
    vigencia: rotuloVigencia(v),
    situacao: v.vigente ? 'Vigente' : 'Fora da vigência',
  }));

  renderGrid($('#tbl-vinculos'), COLS_VINCULO, linhas, (linha) =>
    selecionarVinculo(linha.originador, linha.numero_convenio));
}

async function novoConvenio() {
  convenioAberto = null;
  escreverFormulario('#page-convenio', 'c', { status: 'ATIVO' });
  travarChave($('#cvd-cnpj'), false);
  $('#convenio-header').textContent =
    'Novo convênio — o CNPJ é a chave e não poderá ser alterado depois.';
  renderGrid($('#tbl-vinculos'), COLS_VINCULO, [], null);
  $('#card-custo').hidden = true;
  limparFormVinculo();
  navegar('convenio');
}

async function salvarConvenio() {
  if (exigirApi('msg-convenio')) return;

  const dados = lerFormulario('#page-convenio', 'c');
  if (!dados.nome_convenio) {
    msgInline('msg-convenio', 'Informe o nome do convênio.', 'erro');
    return;
  }

  try {
    const salvo = convenioAberto
      ? await apiAtualizarConvenio(convenioAberto.cnpj_chave, {
        nome_convenio: dados.nome_convenio,
        status: dados.status,
        status_producao: dados.status_producao,
        gestora_margem: dados.gestora_margem,
        link_gestora: dados.link_gestora,
        observacao: dados.observacao,
      })
      : await apiCriarConvenio(dados);

    msgInline('msg-convenio', 'Convênio salvo.');
    toast('Convênio salvo.', 'ok');
    await pesquisarConvenios();
    await abrirConvenio(salvo.cnpj_convenio);
  } catch (erro) {
    msgInline('msg-convenio', erro.message, 'erro');
  }
}

// Abre o link da gestora de margem numa nova aba. Só http(s) é aberto —
// evita `javascript:` e outros esquemas colados por engano no campo.
function acessarGestora() {
  const url = $('#cvd-link-gestora').value.trim();
  if (!url) {
    msgInline('msg-convenio', 'Nenhum link de gestora cadastrado.', 'erro');
    return;
  }
  if (!/^https?:\/\//i.test(url)) {
    msgInline('msg-convenio', 'O link deve começar com http:// ou https://.', 'erro');
    return;
  }
  window.open(url, '_blank', 'noopener');
}

/* ---------------- Vínculo (originadora do convênio) ---------------- */

function limparFormVinculo() {
  vinculoSelecionado = null;
  // O nome do convênio não está aqui de propósito: ele é do convênio,
  // não do vínculo. O servidor copia o nome do mestre para dentro do
  // arquivo do vínculo sozinho.
  escreverFormulario('#page-convenio', 'v', {
    status: 'ATIVO',
    competencia_inicio: competenciaFiltro(),
  });
  preencherSelectOriginadoras();

  travarChave($('#vin-originador'), false);
  travarChave($('#vin-numero'), false);
  $('#titulo-form-vinculo').textContent = 'Adicionar originadora ao convênio';
  $('#btn-excluir-vinculo').hidden = true;
  $('#card-custo').hidden = true;
}

function preencherSelectOriginadoras(valor) {
  const nomes = originadoras
    .filter((o) => o.status === 'ATIVO' || o.nome === valor)
    .map((o) => o.nome);
  const opcoes = nomes.length
    ? nomes
    : [{ value: '', label: '(cadastre uma originadora no submódulo Originadoras)' }];

  // O vínculo pode ser de uma originadora que só existe nos arquivos
  // antigos, sem passar pelo cadastro mestre: ela entra na lista para o
  // registro continuar editável.
  if (valor && !nomes.includes(valor)) opcoes.unshift(valor);
  preencherSelect($('#vin-originador'), opcoes, valor);
}

function selecionarVinculo(originador, numeroConvenio) {
  vinculoSelecionado = convenioAberto.originadoras.find(
    (v) => v.originador === originador && v.numero_convenio === numeroConvenio,
  );
  if (!vinculoSelecionado) return;

  escreverFormulario('#page-convenio', 'v', vinculoSelecionado);
  preencherSelectOriginadoras(originador);
  $('#vin-numero').value = numeroConvenio;

  travarChave($('#vin-originador'), true);
  travarChave($('#vin-numero'), true);
  $('#titulo-form-vinculo').textContent =
    `Vínculo: ${originador} · ${numeroConvenio} `
    + '(originadora e número são a chave e não mudam)';
  $('#btn-excluir-vinculo').hidden = false;

  abrirCusto();
}

async function salvarVinculo() {
  if (exigirApi('msg-vinculo')) return;
  if (!convenioAberto) {
    msgInline('msg-vinculo', 'Salve o convênio antes de vincular.', 'erro');
    return;
  }

  const dados = lerFormulario('#page-convenio', 'v');

  try {
    if (vinculoSelecionado) {
      // Originadora e número não vão no corpo: são a chave, vêm da rota.
      const { originador, numero_convenio: numero, ...editaveis } = dados;
      await apiAtualizarVinculo(
        vinculoSelecionado.originador,
        vinculoSelecionado.numero_convenio,
        editaveis,
      );
    } else {
      await apiCriarVinculo(convenioAberto.cnpj_chave, dados);
    }
    msgInline('msg-vinculo', 'Vínculo salvo.');
    toast('Vínculo salvo.', 'ok');
    await recarregarConvenioAberto();
  } catch (erro) {
    msgInline('msg-vinculo', erro.message, 'erro');
  }
}

async function excluirVinculo() {
  if (exigirApi('msg-vinculo') || !vinculoSelecionado) return;

  const { originador, numero_convenio: numero } = vinculoSelecionado;
  const confirmado = window.confirm(
    `Excluir o vínculo ${originador} · ${numero}?\n\n`
    + 'O histórico de custo dele vai junto. Para apenas desligar o convênio '
    + 'nesta originadora, preencha "Encerrado em" e salve.',
  );
  if (!confirmado) return;

  try {
    await apiExcluirVinculo(originador, numero);
    toast('Vínculo excluído.', 'ok');
    await recarregarConvenioAberto();
  } catch (erro) {
    msgInline('msg-vinculo', erro.message, 'erro');
  }
}

async function recarregarConvenioAberto() {
  const cnpj = convenioAberto.cnpj_chave;
  convenioAberto = await apiConvenioPorCnpj(cnpj, competenciaFiltro());
  renderVinculos();
  limparFormVinculo();
  await pesquisarConvenios();
}

/* ---------------- Custo do vínculo ---------------- */

const COLS_CUSTO = [
  { key: 'vigencia', label: 'Vigência' },
  { key: 'metodo_label', label: 'Método', left: true },
  { key: 'detalhe', label: 'Parâmetros', left: true, wrap: true },
  { key: 'status_label', label: 'Status' },
  { key: 'observacao', label: 'Observação', left: true, wrap: true },
  { key: 'criado_em', label: 'Cadastrado em' },
];

const COLS_FAIXA = [
  { key: 'ate', label: 'Até (0 = sem teto)' },
  { key: 'metodo_label', label: 'Método' },
  { key: 'parametro', label: 'Parâmetro' },
  { key: 'acao', label: '' },
];

// Espelha o resumo que o servidor devolve, só que para o histórico
// inteiro. É exibição, não regra: o cálculo do custo mora no servidor.
function detalheDoCusto(custo) {
  if (custo.metodo === 'PERCENTUAL') {
    return `${custo.aliquota_percentual}% sobre `
      + `${BASE_LABEL[custo.base_calculo] || custo.base_calculo}`;
  }
  if (custo.metodo === 'FIXO_MENSAL') return brMoney(custo.valor_fixo) + '/mês';
  if (custo.metodo === 'POR_CONTRATO') {
    return brMoney(custo.valor_unitario) + ' por contrato';
  }
  return `${(custo.faixas || []).length} faixa(s) por `
    + `${custo.criterio_faixa === 'VALOR' ? 'valor' : 'quantidade'}`;
}

function abrirCusto() {
  $('#card-custo').hidden = false;
  $('#titulo-custo').textContent =
    `Custo de ${vinculoSelecionado.originador} · `
    + `${vinculoSelecionado.numero_convenio}`;

  const vigente = vinculoSelecionado.custo_vigente;
  escreverFormulario('#card-custo', 'k', vigente || {
    metodo: 'PERCENTUAL',
    base_calculo: 'VALOR_RETORNO',
    criterio_faixa: 'QUANTIDADE',
  });
  $('[data-k="competencia_inicio"]', $('#card-custo')).value =
    competenciaFiltro();

  faixasEmEdicao = vigente ? (vigente.faixas || []).map((f) => ({ ...f })) : [];
  aplicarMetodoCusto();
  renderFaixas();
  carregarHistoricoDeCusto();
}

function aplicarMetodoCusto() {
  const metodo = $('#custo-metodo').value;
  $$('#card-custo .custo-campo').forEach((el) => {
    el.hidden = !el.classList.contains('custo-' + metodo);
  });
}

function renderFaixas() {
  const linhas = faixasEmEdicao.map((faixa, indice) => ({
    ate: faixa.ate || 0,
    metodo_label: METODO_LABEL[faixa.metodo] || faixa.metodo,
    parametro: detalheDoCusto(faixa),
    acao: 'remover',
    _indice: indice,
  }));

  renderGrid($('#tbl-faixas'), COLS_FAIXA, linhas, (linha) => {
    faixasEmEdicao.splice(linha._indice, 1);
    renderFaixas();
  });
}

// Um degrau por vez, com prompt: a tabela é curta e um editor inline
// completo custaria mais tela do que o cadastro merece.
function adicionarFaixa() {
  const ate = window.prompt(
    'Até quanto vale este degrau? (0 = último, sem teto)', '0',
  );
  if (ate === null) return;

  const metodo = window.prompt(
    'Método do degrau: PERCENTUAL, FIXO_MENSAL ou POR_CONTRATO',
    'POR_CONTRATO',
  );
  if (!metodo || !METODO_LABEL[metodo] || metodo === 'FAIXA') {
    toast('Método de degrau inválido.', 'erro');
    return;
  }

  const valor = parseNumeroBR(window.prompt(
    metodo === 'PERCENTUAL' ? 'Alíquota (%)' : 'Valor (R$)', '0',
  ));

  faixasEmEdicao.push({
    ate: parseNumeroBR(ate) || 0,
    metodo,
    base_calculo: $('[data-k="base_calculo"]', $('#card-custo')).value,
    aliquota_percentual: metodo === 'PERCENTUAL' ? valor : 0,
    valor_fixo: metodo === 'FIXO_MENSAL' ? valor : 0,
    valor_unitario: metodo === 'POR_CONTRATO' ? valor : 0,
  });
  renderFaixas();
}

async function carregarHistoricoDeCusto() {
  let historico = [];
  try {
    historico = await apiCustos(
      vinculoSelecionado.originador, vinculoSelecionado.numero_convenio,
    );
  } catch (erro) {
    toast('Não foi possível ler o histórico: ' + erro.message, 'erro');
  }

  renderGrid($('#tbl-custos'), COLS_CUSTO, historico.map((c) => ({
    ...c,
    vigencia: rotuloVigencia(c),
    metodo_label: METODO_LABEL[c.metodo] || c.metodo,
    detalhe: detalheDoCusto(c),
    status_label: (c.status || 'ATIVO') === 'ATIVO' ? 'Ativo' : 'Inativo',
  })), (linha) => alternarCusto(linha));
}

// Clicar num custo alterna ativo/inativo — desativado não é aplicado no
// cálculo (o convênio fica sem custo enquanto assim). O histórico fica.
async function alternarCusto(custo) {
  if (exigirApi('msg-custo') || !vinculoSelecionado) return;
  const ativo = (custo.status || 'ATIVO') !== 'ATIVO';
  const acao = ativo ? 'ativar' : 'desativar';
  if (!window.confirm(
    `Deseja ${acao} este custo (vigência ${rotuloVigencia(custo)})?`,
  )) return;

  try {
    await apiAlternarCusto(
      vinculoSelecionado.originador, vinculoSelecionado.numero_convenio,
      custo.competencia_inicio, ativo,
    );
    toast(`Custo ${ativo ? 'ativado' : 'desativado'}.`, 'ok');
    await carregarHistoricoDeCusto();
  } catch (erro) {
    msgInline('msg-custo', erro.message, 'erro');
  }
}

async function salvarCusto() {
  if (exigirApi('msg-custo') || !vinculoSelecionado) return;

  const bruto = lerFormulario('#card-custo', 'k');
  const payload = {
    metodo: bruto.metodo,
    competencia_inicio: bruto.competencia_inicio,
    base_calculo: bruto.base_calculo,
    criterio_faixa: bruto.criterio_faixa,
    aliquota_percentual: parseNumeroBR(bruto.aliquota_percentual) || 0,
    valor_fixo: parseNumeroBR(bruto.valor_fixo) || 0,
    valor_unitario: parseNumeroBR(bruto.valor_unitario) || 0,
    faixas: faixasEmEdicao,
    observacao: bruto.observacao || '',
  };

  try {
    await apiSalvarCusto(
      vinculoSelecionado.originador,
      vinculoSelecionado.numero_convenio,
      payload,
    );
    msgInline('msg-custo', 'Custo em vigor. O anterior foi encerrado.');
    toast('Custo atualizado.', 'ok');

    const chave = {
      originador: vinculoSelecionado.originador,
      numero: vinculoSelecionado.numero_convenio,
    };
    await recarregarConvenioAberto();
    selecionarVinculo(chave.originador, chave.numero);
  } catch (erro) {
    msgInline('msg-custo', erro.message, 'erro');
  }
}

/* ---------------- Originadoras ---------------- */

const COLS_ORIGINADORA = [
  { key: 'nome', label: 'Originadora', left: true },
  { key: 'codigo', label: 'Código' },
  { key: 'cnpj', label: 'CNPJ' },
  { key: 'status', label: 'Status' },
  { key: 'cadastro', label: 'Cadastro' },
  { key: 'observacao', label: 'Observação', left: true, wrap: true },
  { key: 'atualizado_em', label: 'Atualizado em' },
];

async function carregarOriginadoras() {
  if (!apiDisponivel()) return;
  try {
    originadoras = await apiOriginadoras();
  } catch (erro) {
    apiRegistrarFalha(erro);
    return;
  }

  // 'Herdada' é a originadora que só existe nos vínculos antigos: dá
  // para usá-la normalmente, e salvá-la aqui cria a ficha própria dela.
  const linhas = originadoras.map((o) => ({
    ...o,
    cadastro: o.cadastrado ? 'Cadastrada' : 'Herdada',
  }));
  renderGrid($('#tbl-originadoras'), COLS_ORIGINADORA, linhas,
    (linha) => selecionarOriginadora(linha.nome));
}

function selecionarOriginadora(nome) {
  originadoraSelecionada = originadoras.find((o) => o.nome === nome);
  if (!originadoraSelecionada) return;

  escreverFormulario('#page-originadoras', 'o', originadoraSelecionada);
  travarChave($('#org-nome'), true);
  $('#titulo-form-originadora').textContent =
    `Originadora: ${nome} (o nome é a chave e não muda)`;
  $('#btn-excluir-originadora').hidden = false;
}

function limparFormOriginadora() {
  originadoraSelecionada = null;
  escreverFormulario('#page-originadoras', 'o', { status: 'ATIVO' });
  travarChave($('#org-nome'), false);
  $('#titulo-form-originadora').textContent =
    'Cadastro de originadora (o nome não poderá ser alterado depois)';
  $('#btn-excluir-originadora').hidden = true;
}

async function salvarOriginadora() {
  if (exigirApi('msg-originadora')) return;

  const dados = lerFormulario('#page-originadoras', 'o');

  try {
    if (originadoraSelecionada) {
      const { nome, ...editaveis } = dados;
      await apiAtualizarOriginadora(originadoraSelecionada.nome, editaveis);
    } else {
      if (!dados.nome) {
        msgInline('msg-originadora', 'Informe o nome da originadora.', 'erro');
        return;
      }
      await apiCriarOriginadora(dados);
    }
    msgInline('msg-originadora', 'Originadora salva.');
    toast('Originadora salva.', 'ok');
    limparFormOriginadora();
    await carregarOriginadoras();
  } catch (erro) {
    msgInline('msg-originadora', erro.message, 'erro');
  }
}

async function excluirOriginadora() {
  if (exigirApi('msg-originadora') || !originadoraSelecionada) return;

  const nome = originadoraSelecionada.nome;
  if (!window.confirm(`Excluir a originadora ${nome}?`)) return;

  try {
    await apiExcluirOriginadora(nome);
    toast('Originadora excluída.', 'ok');
    limparFormOriginadora();
    await carregarOriginadoras();
  } catch (erro) {
    msgInline('msg-originadora', erro.message, 'erro');
  }
}

/* ---------------- Setup ---------------- */

function setupConvenios() {
  $('#cv-competencia').value = competenciaDeHoje();

  $('#btn-cv-buscar').addEventListener('click', pesquisarConvenios);
  $('#cv-busca').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') pesquisarConvenios();
  });
  $('#btn-cv-novo').addEventListener('click', novoConvenio);


  $('#btn-salvar-convenio').addEventListener('click', salvarConvenio);
  $('#btn-acessar-gestora').addEventListener('click', acessarGestora);
  $('#btn-salvar-vinculo').addEventListener('click', salvarVinculo);
  $('#btn-novo-vinculo').addEventListener('click', limparFormVinculo);
  $('#btn-excluir-vinculo').addEventListener('click', excluirVinculo);

  $('#custo-metodo').addEventListener('change', aplicarMetodoCusto);
  $('#btn-add-faixa').addEventListener('click', adicionarFaixa);
  $('#btn-salvar-custo').addEventListener('click', salvarCusto);

  $('#btn-salvar-originadora').addEventListener('click', salvarOriginadora);
  $('#btn-novo-originadora').addEventListener('click', limparFormOriginadora);
  $('#btn-excluir-originadora').addEventListener('click', excluirOriginadora);

  limparFormOriginadora();
}

// Carregar só ao entrar na página evita puxar o cadastro inteiro para
// quem abriu o painel para usar a Conciliação.
async function aoEntrarNaPaginaDeConvenios(pagina) {
  if (pagina === 'convenios') {
    await carregarOriginadoras();
    await pesquisarConvenios();
  }
  if (pagina === 'originadoras') await carregarOriginadoras();
}
