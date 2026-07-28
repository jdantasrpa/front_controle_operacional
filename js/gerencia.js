'use strict';

/* ============================================================
   gerencia.js — Submódulo "Gerência de Convênios" (Conciliação).

   A visão da mesa de conciliação sobre convênio → originadora. A lista
   mostra os convênios; clicar numa linha abre o DETALHE do convênio em
   abas (Dados Gerais, Originadora, Competência, Controle). A originadora
   (grupo master) e a geração massiva ficam na própria lista.

   Convênio desligado não entra na geração: quem decide o que a conciliação
   trata é a mesa. Este submódulo escreve e depende da API — sem servidor
   (file://) ele avisa em vez de fingir que funciona.
   ============================================================ */

/* ---------------- Estado ---------------- */

let linhasGerencia = [];
let originadorasGerencia = [];
let originadoraFiltro = '';
let detalheSelecionado = null;

/* ---------------- Utilitários ---------------- */

function competenciaRefGerencia() {
  return $('#gr-competencia').value || competenciaDeHoje();
}

// Carimbo de cadastro vem em ISO ('2026-07-24T09:55:33'); só a data
// interessa na exibição.
function soData(iso) {
  return (iso || '').slice(0, 10);
}

function filtrarGerencia(linhas, termo) {
  const alvo = (termo || '').toLowerCase();

  return linhas
    .filter((l) => !originadoraFiltro || l.originador === originadoraFiltro)
    .filter((l) => !alvo || [
      l.nome_convenio, l.cnpj_convenio, l.originador, l.numero_convenio,
    ].join(' ').toLowerCase().includes(alvo));
}

/* ---------------- Carga e render da lista ---------------- */

async function carregarGerencia() {
  if (!apiDisponivel()) {
    $('#gr-resumo').textContent =
      'Sem servidor: abra o painel pelo endereço http para usar este módulo.';
    return;
  }
  try {
    const competencia = competenciaRefGerencia();
    [linhasGerencia, originadorasGerencia] = await Promise.all([
      apiListarGerencia(competencia),
      apiListarGerenciaOriginadoras(competencia),
    ]);
  } catch (erro) {
    apiRegistrarFalha(erro);
    toast('Não foi possível carregar a gerência: ' + erro.message, 'erro');
    return;
  }

  renderOriginadorasGerencia();
  renderGerencia();
}

function renderGerencia() {
  const visiveis = filtrarGerencia(linhasGerencia, $('#gr-busca').value);
  const ligados = visiveis.filter((l) => l.em_conciliacao_ativa).length;
  const filtro = originadoraFiltro ? ` — filtrado por ${originadoraFiltro}` : '';

  $('#gr-resumo').textContent =
    `${visiveis.length} convênio(s) — ${ligados} ligado(s) na competência `
    + competenciaRefGerencia() + filtro;

  const tbody = $('#tbl-gerencia tbody');
  $('#tbl-gerencia thead').innerHTML = _cabecalhoGerencia();
  tbody.innerHTML = '';

  if (!visiveis.length) {
    tbody.innerHTML =
      '<tr><td class="cell-empty" colspan="8">Nenhum convênio.</td></tr>';
    return;
  }
  visiveis.forEach((linha) => tbody.appendChild(_linhaGerencia(linha)));
}

function _cabecalhoGerencia() {
  const titulos = [
    'Convênio', 'Originadora', 'N°', 'CNPJ', 'Vigente', 'Gestão',
    'Em conciliação', 'Dia',
  ];
  return '<tr>' + titulos.map((t) => `<th>${t}</th>`).join('') + '</tr>';
}

// A linha inteira é clicável: abre o detalhe do convênio (item 1).
function _linhaGerencia(linha) {
  const tr = document.createElement('tr');
  tr.classList.add('linha-clicavel');
  if (!linha.em_conciliacao_ativa) tr.classList.add('linha-desligada');

  _celulaTexto(tr, linha.nome_convenio, true);
  _celulaTexto(tr, linha.originador, true);
  _celulaTexto(tr, linha.numero_convenio);
  _celulaTexto(tr, linha.cnpj_convenio);
  _celulaTexto(tr, linha.vigente ? 'Sim' : 'Não');
  tr.appendChild(_celulaGestao(linha));
  _celulaTexto(tr, linha.em_conciliacao_ativa ? 'Ligado' : 'Desligado');
  _celulaTexto(tr, linha.dia_vencimento === '' ? '—' : String(linha.dia_vencimento));

  tr.addEventListener('click', () => abrirDetalhe(linha));
  return tr;
}

// Status da Gestão só para leitura — os dois controles são independentes.
// Quando a Gestão inativa, o motivo (a observação) fica no tooltip.
function _celulaGestao(linha) {
  const td = document.createElement('td');
  if (linha.status_gestao !== 'INATIVO') {
    td.textContent = 'Ativo';
    return td;
  }
  const badge = document.createElement('span');
  badge.className = 'chip chip-danger';
  badge.textContent = `Inativo (${linha.nivel_gestao})`;
  badge.title = linha.motivo_gestao
    ? `Motivo (Gestão): ${linha.motivo_gestao}`
    : 'Inativado na Gestão, sem motivo registrado.';
  td.appendChild(badge);
  return td;
}

function _celulaTexto(tr, valor, esquerda) {
  const td = document.createElement('td');
  if (esquerda) td.classList.add('cell-left');
  td.textContent = valor || '—';
  tr.appendChild(td);
}

/* ---------------- Detalhe do convênio (abas) ---------------- */

const ABAS_DETALHE = [
  'dados', 'originadora', 'competencia', 'controle', 'remessas',
  'responsaveis',
];

function abrirDetalhe(linha) {
  detalheSelecionado = linha;
  preencherDetalhe(linha);
  if (typeof preencherAbaRemessas === 'function') {
    preencherAbaRemessas(linha);
  }
  if (typeof preencherAbaResponsaveis === 'function') {
    preencherAbaResponsaveis(linha);
  }
  trocarAbaDetalhe('dados');
  navegar('gerencia-detalhe');
}

function trocarAbaDetalhe(aba) {
  $$('#grd-tabs .tab-btn').forEach((b) =>
    b.classList.toggle('active', b.dataset.gtab === aba));
  ABAS_DETALHE.forEach((nome) => {
    $('#gtab-' + nome).hidden = nome !== aba;
  });
}

function _num(valor) {
  return valor === '' || valor === null || valor === undefined ? '' : valor;
}

function preencherDetalhe(linha) {
  $('#grd-titulo').textContent =
    `${linha.nome_convenio} — ${linha.originador} (${linha.numero_convenio})`;

  // Dados Gerais (leitura)
  $('#grd-nome').textContent = linha.nome_convenio || '—';
  $('#grd-cnpj').textContent = linha.cnpj_convenio || '—';
  $('#grd-cadastrado').textContent = soData(linha.cadastrado_em) || '—';
  $('#grd-vigente').textContent = linha.vigente ? 'Sim' : 'Não';
  $('#grd-gestao').textContent = linha.status_gestao === 'INATIVO'
    ? `Inativo (${linha.nivel_gestao})`
      + (linha.motivo_gestao ? ` — ${linha.motivo_gestao}` : '')
    : 'Ativo';

  // Originadora (leitura)
  $('#grd-originadora').textContent = linha.originador || '—';
  $('#grd-numero').textContent = linha.numero_convenio || '—';
  $('#grd-averbadora').textContent = linha.averbadora || '—';

  // Controle (edição)
  $('#grd-ativa').checked = linha.em_conciliacao_ativa;
  $('#grd-dia').value = _num(linha.dia_vencimento);
  $('#grd-remessa').value = _num(linha.dias_antes_remessa);
  $('#grd-sla').value = _num(linha.qtd_dias_sla_pagamento);
  $('#grd-corte').value = _num(linha.dias_antes_corte);
  msgInline('msg-grd-controle', '');

  // Competência (geração por período)
  $('#grd-per-inicio').value = competenciaRefGerencia();
  $('#grd-per-fim').value = competenciaRefGerencia();
  msgInline('msg-grd-periodo', '');
}

// O toggle salva na hora; os demais campos vão no "Salvar controle".
async function alternarConciliacaoDetalhe() {
  if (!detalheSelecionado) return;
  const linha = detalheSelecionado;
  const desejado = $('#grd-ativa').checked;
  if (exigirApi('msg-grd-controle')) {
    $('#grd-ativa').checked = linha.em_conciliacao_ativa;
    return;
  }
  try {
    const estado = await apiAtualizarEstadoGerencia(
      linha.originador, linha.numero_convenio,
      { em_conciliacao_ativa: desejado },
    );
    linha.em_conciliacao_ativa = estado.em_conciliacao_ativa;
    toast(desejado ? 'Ligado na conciliação.' : 'Desligado na conciliação.', 'ok');
  } catch (erro) {
    $('#grd-ativa').checked = linha.em_conciliacao_ativa;
    msgInline('msg-grd-controle', erro.message, 'erro');
  }
}

// Campo vazio manda '' (limpa); número manda o inteiro. A validação de
// faixa (dia 1..30; offsets >= 0) é reforçada no servidor.
function _campoPayload(id) {
  const bruto = $(id).value;
  return bruto === '' ? '' : Number(bruto);
}

async function salvarControleDetalhe() {
  if (exigirApi('msg-grd-controle') || !detalheSelecionado) return;

  const linha = detalheSelecionado;
  try {
    const estado = await apiAtualizarEstadoGerencia(
      linha.originador, linha.numero_convenio,
      {
        dia_vencimento: _campoPayload('#grd-dia'),
        dias_antes_remessa: _campoPayload('#grd-remessa'),
        qtd_dias_sla_pagamento: _campoPayload('#grd-sla'),
        dias_antes_corte: _campoPayload('#grd-corte'),
      },
    );
    linha.dia_vencimento = estado.dia_vencimento;
    linha.dias_antes_remessa = estado.dias_antes_remessa;
    linha.qtd_dias_sla_pagamento = estado.qtd_dias_sla_pagamento;
    linha.dias_antes_corte = estado.dias_antes_corte;
    msgInline('msg-grd-controle', 'Controle salvo.');
    toast(`Controle de ${linha.nome_convenio} salvo.`, 'ok');
  } catch (erro) {
    msgInline('msg-grd-controle', erro.message, 'erro');
  }
}

async function gerarPeriodoDetalhe() {
  if (exigirApi('msg-grd-periodo') || !detalheSelecionado) return;

  const linha = detalheSelecionado;
  const inicio = $('#grd-per-inicio').value;
  const fim = $('#grd-per-fim').value;
  if (!inicio || !fim) {
    msgInline('msg-grd-periodo', 'Informe o período (inicial e final).', 'erro');
    return;
  }

  try {
    const r = await apiGerarPeriodo({
      originador: linha.originador,
      numero_convenio: linha.numero_convenio,
      competencia_inicio: inicio,
      competencia_fim: fim,
    });
    _relatarPeriodo(linha, r);
  } catch (erro) {
    msgInline('msg-grd-periodo', erro.message, 'erro');
  }
}

function _relatarPeriodo(linha, resumo) {
  if (resumo.desligado) {
    msgInline(
      'msg-grd-periodo',
      `${linha.nome_convenio} está desligado na conciliação — nada gerado. `
      + 'Ligue-o na aba Controle antes de gerar.',
      'erro',
    );
    return;
  }
  msgInline(
    'msg-grd-periodo',
    `${resumo.competencia_inicio} → ${resumo.competencia_fim}: `
    + `${resumo.gerados.length} gerado(s), ${resumo.pulados.length} já `
    + `existia(m), ${resumo.fora_vigencia.length} fora de vigência, `
    + `${resumo.sem_origem.length} sem mês anterior.`,
  );
  toast('Geração por período concluída.', 'ok');
}

/* ---------------- Originadoras (grupo master) ---------------- */

function renderOriginadorasGerencia() {
  const tbody = $('#tbl-gr-originadoras tbody');
  $('#tbl-gr-originadoras thead').innerHTML = _cabecalhoOriginadoras();
  tbody.innerHTML = '';

  if (!originadorasGerencia.length) {
    tbody.innerHTML =
      '<tr><td class="cell-empty" colspan="6">Nenhuma originadora.</td></tr>';
    return;
  }
  originadorasGerencia.forEach((o) => tbody.appendChild(_linhaOriginadora(o)));
}

function _cabecalhoOriginadoras() {
  const titulos = [
    'Originadora', 'Ativa', 'Convênios', 'Ligados', 'Vigentes', 'Ações',
  ];
  return '<tr>' + titulos.map((t) => `<th>${t}</th>`).join('') + '</tr>';
}

function _linhaOriginadora(orig) {
  const tr = document.createElement('tr');
  if (!orig.em_conciliacao_ativa) tr.classList.add('linha-desligada');
  if (orig.originador === originadoraFiltro) tr.classList.add('selected');

  _celulaTexto(tr, orig.originador, true);
  tr.appendChild(_celulaToggleOriginadora(orig));
  _celulaTexto(tr, String(orig.total_convenios));
  _celulaTexto(tr, String(orig.total_ligados));
  _celulaTexto(tr, String(orig.total_vigentes));
  tr.appendChild(_celulaAcoesOriginadora(orig));

  return tr;
}

function _celulaToggleOriginadora(orig) {
  const td = document.createElement('td');
  const label = document.createElement('label');
  label.className = 'switch';
  const input = document.createElement('input');
  input.type = 'checkbox';
  input.checked = orig.em_conciliacao_ativa;
  input.addEventListener('change', () => alternarOriginadora(orig, input));
  label.appendChild(input);
  label.appendChild(document.createElement('span'));
  td.appendChild(label);
  return td;
}

function _celulaAcoesOriginadora(orig) {
  const td = document.createElement('td');
  td.classList.add('cell-acoes');
  td.appendChild(_botaoOrig('Ver convênios', () => filtrarPorOriginadora(orig)));
  td.appendChild(_botaoOrig('Gerar mês', () => gerarOriginadoraMes(orig)));
  td.appendChild(_botaoOrig('Gerar período', () => gerarOriginadoraPeriodo(orig)));
  return td;
}

function _botaoOrig(texto, aoClicar) {
  const btn = document.createElement('button');
  btn.className = 'btn btn-secondary btn-sm';
  btn.textContent = texto;
  btn.addEventListener('click', aoClicar);
  return btn;
}

// "Ver convênios" alterna o filtro da tabela de convênios abaixo: clicar
// de novo na mesma originadora limpa o filtro.
function filtrarPorOriginadora(orig) {
  originadoraFiltro = originadoraFiltro === orig.originador
    ? '' : orig.originador;
  renderOriginadorasGerencia();
  renderGerencia();
}

async function alternarOriginadora(orig, input) {
  if (exigirApi('msg-gerencia-originadora')) {
    input.checked = orig.em_conciliacao_ativa;
    return;
  }
  const desejado = input.checked;
  try {
    const estado = await apiAtivarOriginadora(orig.originador, desejado);
    orig.em_conciliacao_ativa = estado.em_conciliacao_ativa;
    renderOriginadorasGerencia();
    toast(
      `${orig.originador}: `
      + (desejado ? 'ativada' : 'desativada') + ' na conciliação.',
      'ok',
    );
  } catch (erro) {
    input.checked = orig.em_conciliacao_ativa;
    msgInline('msg-gerencia-originadora', erro.message, 'erro');
  }
}

async function gerarOriginadoraMes(orig) {
  if (exigirApi('msg-gerencia-originadora')) return;

  const competencia = competenciaRefGerencia();
  const confirmado = window.confirm(
    `Gerar a competência ${competencia} para todos os convênios ligados e `
    + `vigentes de ${orig.originador}?`,
  );
  if (!confirmado) return;

  try {
    const r = await apiGerarOriginadoraCompetencia(orig.originador, competencia);
    _relatarOriginadora(orig, r, competencia);
    await carregarGerencia();
  } catch (erro) {
    msgInline('msg-gerencia-originadora', erro.message, 'erro');
  }
}

function _relatarOriginadora(orig, resumo, competencia) {
  if (resumo.desativada) {
    msgInline(
      'msg-gerencia-originadora',
      `${orig.originador} está desativada — nada gerado. Ative-a antes.`,
      'erro',
    );
    return;
  }
  msgInline(
    'msg-gerencia-originadora',
    `${orig.originador} — ${competencia}: ${resumo.gerados.length} gerado(s), `
    + `${resumo.pulados.length} já existia(m), ${resumo.sem_origem.length} sem `
    + 'mês anterior.',
  );
  toast(`Competência de ${orig.originador} gerada.`, 'ok');
}

async function gerarOriginadoraPeriodo(orig) {
  if (exigirApi('msg-gerencia-originadora')) return;

  const inicio = $('#gr-orig-inicio').value;
  const fim = $('#gr-orig-fim').value;
  if (!inicio || !fim) {
    msgInline(
      'msg-gerencia-originadora',
      'Defina o período (inicial e final) no topo do card.',
      'erro',
    );
    return;
  }

  try {
    const r = await apiGerarOriginadoraPeriodo(orig.originador, inicio, fim);
    _relatarOriginadoraPeriodo(orig, r);
    await carregarGerencia();
  } catch (erro) {
    msgInline('msg-gerencia-originadora', erro.message, 'erro');
  }
}

function _relatarOriginadoraPeriodo(orig, resumo) {
  if (resumo.desativada) {
    msgInline(
      'msg-gerencia-originadora',
      `${orig.originador} está desativada — nada gerado. Ative-a antes.`,
      'erro',
    );
    return;
  }
  const total = resumo.por_competencia.reduce(
    (soma, c) => soma + c.gerados.length, 0,
  );
  msgInline(
    'msg-gerencia-originadora',
    `${orig.originador} — ${resumo.competencia_inicio} → `
    + `${resumo.competencia_fim}: ${total} vencimentário(s) gerado(s) em `
    + `${resumo.por_competencia.length} competência(s).`,
  );
  toast(`Período de ${orig.originador} gerado.`, 'ok');
}

/* ---------------- Geração massiva geral ---------------- */

async function gerarMassivoGerencia() {
  if (exigirApi('msg-gerencia')) return;

  const competencia = competenciaRefGerencia();
  const confirmado = window.confirm(
    `Gerar a competência ${competencia} para todos os convênios vigentes e `
    + 'ligados?\n\nClona o esqueleto do mês anterior com valores zerados e '
    + 'emite a solicitação para a automação do Datacob. Convênio já gerado é '
    + 'preservado; desligado fica de fora.',
  );
  if (!confirmado) return;

  try {
    const r = await apiGerarCompetencia(competencia);
    msgInline(
      'msg-gerencia',
      `Competência ${competencia}: ${r.gerados.length} gerado(s), `
      + `${r.pulados.length} já existia(m), ${r.sem_origem.length} sem mês `
      + `anterior. Ticket na fila: ${r.ticket}.`,
    );
    toast(`Competência ${competencia} gerada.`, 'ok');
    await carregarGerencia();
  } catch (erro) {
    msgInline('msg-gerencia', erro.message, 'erro');
  }
}

/* ---------------- Setup ---------------- */

function setupGerencia() {
  $('#gr-competencia').value = competenciaDeHoje();

  $('#btn-gr-atualizar').addEventListener('click', carregarGerencia);
  $('#btn-gr-massivo').addEventListener('click', gerarMassivoGerencia);
  $('#gr-busca').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') carregarGerencia();
  });

  // Detalhe em abas
  $$('#grd-tabs .tab-btn').forEach((b) =>
    b.addEventListener('click', () => trocarAbaDetalhe(b.dataset.gtab)));
  $('#grd-ativa').addEventListener('change', alternarConciliacaoDetalhe);
  $('#btn-grd-ctrl-salvar').addEventListener('click', salvarControleDetalhe);
  $('#btn-grd-periodo').addEventListener('click', gerarPeriodoDetalhe);
}

// Carrega só ao entrar: quem abriu o painel para a Gestão não paga pela
// leitura da gerência.
async function aoEntrarNaGerencia() {
  await carregarGerencia();
}
