'use strict';

/* ============================================================
   responsaveis.js — Responsáveis pela Conciliação.

   Duas frentes:
   * o submódulo de cadastro de colaboradores (page-responsaveis);
   * a aba "Responsáveis" do detalhe do convênio (na Gerência), que define
     titular e substituição e mostra o responsável efetivo + histórico.

   O responsável efetivo vem calculado do servidor: substituição vigente
   vence o titular; titular desligado vira "Usuário Não Cadastrado".
   ============================================================ */

/* ---------------- Estado ---------------- */

let colaboradores = [];
let colaboradorEditando = null;   // nome em edição; null = novo
let respVinculo = null;           // {originador, numero_convenio} do detalhe

/* ---------------- Colaboradores (submódulo) ---------------- */

const COLS_COLABORADOR = [
  { key: 'nome', label: 'Nome', left: true },
  { key: 'status', label: 'Status' },
  { key: 'observacao', label: 'Observação', left: true, wrap: true },
];

async function carregarColaboradores() {
  if (!apiDisponivel()) {
    colaboradores = [];
    return colaboradores;
  }
  try {
    colaboradores = await apiListarColaboradores();
  } catch (erro) {
    apiRegistrarFalha(erro);
    colaboradores = [];
  }
  return colaboradores;
}

function renderColaboradores() {
  $('#colab-resumo').textContent = `${colaboradores.length} colaborador(es)`;
  renderGrid(
    $('#tbl-colaboradores'), COLS_COLABORADOR, colaboradores,
    (linha) => editarColaborador(linha),
  );
}

function _obsColab() {
  return document.querySelector('#page-responsaveis [data-col="observacao"]');
}

function limparFormColaborador() {
  colaboradorEditando = null;
  $('#titulo-form-colab').textContent = 'Novo colaborador';
  $('#col-nome').value = '';
  $('#col-nome').disabled = false;
  $('#col-status').value = 'ATIVO';
  _obsColab().value = '';
  msgInline('msg-colab', '');
}

// O nome é a chave: em edição ele fica travado (status/observação mudam).
function editarColaborador(linha) {
  colaboradorEditando = linha.nome;
  $('#titulo-form-colab').textContent = `Editar ${linha.nome}`;
  $('#col-nome').value = linha.nome;
  $('#col-nome').disabled = true;
  $('#col-status').value = linha.status || 'ATIVO';
  _obsColab().value = linha.observacao || '';
  msgInline('msg-colab', '');
}

async function salvarColaborador() {
  if (exigirApi('msg-colab')) return;
  const nome = $('#col-nome').value.trim();
  const status = $('#col-status').value;
  const observacao = _obsColab().value.trim();

  try {
    if (colaboradorEditando) {
      await apiAtualizarColaborador(colaboradorEditando, { status, observacao });
      toast('Colaborador atualizado.', 'ok');
    } else {
      await apiCriarColaborador({ nome, status, observacao });
      toast('Colaborador criado.', 'ok');
    }
    limparFormColaborador();
    await carregarColaboradores();
    renderColaboradores();
  } catch (erro) {
    msgInline('msg-colab', erro.message, 'erro');
  }
}

/* ---------------- Aba Responsáveis (detalhe do convênio) ---------------- */

const HIST_LABEL = {
  titular: 'Titular',
  substituicao: 'Substituição',
  encerrar_substituicao: 'Fim substituição',
};

async function preencherAbaResponsaveis(linha) {
  respVinculo = {
    originador: linha.originador,
    numero_convenio: linha.numero_convenio,
  };
  msgInline('msg-grd-resp', '');
  await carregarColaboradores();
  _preencherSelectColab('#grd-resp-titular', true);
  _preencherSelectColab('#grd-resp-substituto', false);

  try {
    const r = await apiObterResponsavel(
      respVinculo.originador, respVinculo.numero_convenio,
    );
    _mostrarResponsavel(r);
  } catch (erro) {
    msgInline('msg-grd-resp', erro.message, 'erro');
  }
}

function _preencherSelectColab(sel, incluirVazio) {
  const ativos = colaboradores
    .filter((c) => c.status === 'ATIVO')
    .map((c) => c.nome);
  const opcoes = incluirVazio
    ? [{ value: '', label: '— (Usuário Não Cadastrado)' }, ...ativos]
    : ativos;
  preencherSelect($(sel), opcoes, '');
}

function _mostrarResponsavel(r) {
  $('#grd-resp-efetivo').textContent = r.efetivo;

  // Titular desligado não está na lista de ativos: garante a opção para o
  // select não perder o valor gravado.
  const selTit = $('#grd-resp-titular');
  if (r.titular && ![...selTit.options].some((o) => o.value === r.titular)) {
    const opt = document.createElement('option');
    opt.value = r.titular;
    opt.textContent = `${r.titular} (desligado)`;
    selTit.appendChild(opt);
  }
  selTit.value = r.titular || '';
  $('#grd-resp-substituto').value = r.substituto || '';
  $('#grd-resp-fim').value = r.substituicao_fim || '';
  _renderHistorico(r.historico || []);
}

function _renderHistorico(hist) {
  const cols = [
    { key: 'em', label: 'Quando' },
    { key: 'ator', label: 'Usuário' },
    { key: 'acao_label', label: 'Ação', left: true },
    { key: 'detalhe', label: 'Detalhe', left: true, wrap: true },
  ];
  const linhas = hist
    .map((h) => ({
      em: (h.em || '').replace('T', ' ').slice(0, 16),
      ator: h.ator || '—',
      acao_label: HIST_LABEL[h.acao] || h.acao,
      detalhe: _detalheHist(h),
    }))
    .reverse();
  renderGrid($('#tbl-grd-resp-hist'), cols, linhas, null);
}

function _detalheHist(h) {
  if (h.acao === 'titular') return `${h.de || '—'} → ${h.para || '(nenhum)'}`;
  if (h.acao === 'substituicao') return `${h.para} até ${h.ate || 'aberto'}`;
  if (h.acao === 'encerrar_substituicao') return `saiu ${h.de || '—'}`;
  return '';
}

async function salvarTitular() {
  if (exigirApi('msg-grd-resp') || !respVinculo) return;
  try {
    const r = await apiDefinirTitular(
      respVinculo.originador,
      respVinculo.numero_convenio,
      $('#grd-resp-titular').value,
    );
    _mostrarResponsavel(r);
    toast('Titular salvo.', 'ok');
  } catch (erro) {
    msgInline('msg-grd-resp', erro.message, 'erro');
  }
}

async function definirSubstituicao() {
  if (exigirApi('msg-grd-resp') || !respVinculo) return;
  const substituto = $('#grd-resp-substituto').value;
  if (!substituto) {
    msgInline('msg-grd-resp', 'Escolha o substituto.', 'erro');
    return;
  }
  try {
    const r = await apiDefinirSubstituicao(
      respVinculo.originador,
      respVinculo.numero_convenio,
      { substituto, substituicao_fim: $('#grd-resp-fim').value },
    );
    _mostrarResponsavel(r);
    toast('Substituição definida.', 'ok');
  } catch (erro) {
    msgInline('msg-grd-resp', erro.message, 'erro');
  }
}

async function encerrarSubstituicao() {
  if (exigirApi('msg-grd-resp') || !respVinculo) return;
  try {
    const r = await apiEncerrarSubstituicao(
      respVinculo.originador, respVinculo.numero_convenio,
    );
    _mostrarResponsavel(r);
    toast('Substituição encerrada.', 'ok');
  } catch (erro) {
    msgInline('msg-grd-resp', erro.message, 'erro');
  }
}

/* ---------------- Setup ---------------- */

function setupResponsaveis() {
  $('#btn-salvar-colab').addEventListener('click', salvarColaborador);
  $('#btn-novo-colab').addEventListener('click', limparFormColaborador);
  $('#btn-grd-resp-titular').addEventListener('click', salvarTitular);
  $('#btn-grd-resp-sub').addEventListener('click', definirSubstituicao);
  $('#btn-grd-resp-sub-fim').addEventListener('click', encerrarSubstituicao);
  limparFormColaborador();
}

// Carrega só ao entrar no submódulo.
async function aoEntrarNosResponsaveis() {
  await carregarColaboradores();
  renderColaboradores();
}
