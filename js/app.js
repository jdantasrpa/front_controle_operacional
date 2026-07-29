'use strict';

/* ============================================================
   app.js — UI do SCO — Controle Operacional (HTML/CSS/JS)
   Reproduz a navegação e as telas do app Gradio original.
   ============================================================ */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/* ---------------- Formatação ---------------- */

function brMoney(v) {
  if (v === '' || v === null || v === undefined) return '';
  const n = Number(v);
  if (isNaN(n)) return String(v);
  return 'R$ ' + n.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function brPercent(v) {
  if (v === '' || v === null || v === undefined) return '';
  const n = Number(v);
  if (isNaN(n)) return String(v);
  return n.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + '%';
}

function fmtValor(fmt, v) {
  if (fmt === 'money') return brMoney(v);
  if (fmt === 'percent') return brPercent(v);
  if (v === '' || v === null || v === undefined) return '';
  return String(v);
}

function parseNumeroBR(v) {
  if (typeof v === 'number') return v;
  if (v === null || v === undefined || v === '') return '';
  let s = String(v).trim().replace(/[^\d,.-]/g, '');
  if (s.includes(',')) s = s.replace(/\./g, '').replace(',', '.');
  const n = parseFloat(s);
  return isNaN(n) ? '' : n;
}

/* ---------------- Toast ---------------- */

function toast(msg, tipo = 'info') {
  const cont = $('#toast-container');
  const el = document.createElement('div');
  el.className = `toast toast-${tipo}`;
  el.textContent = msg;
  cont.appendChild(el);
  setTimeout(() => {
    el.classList.add('hide');
    el.addEventListener('animationend', () => el.remove());
  }, 3200);
}

function msgInline(id, texto, tipo = 'ok') {
  const el = $('#' + id);
  if (!el) return;
  el.textContent = texto;
  el.className = 'form-msg ' + (tipo === 'erro' ? 'is-erro' : 'is-ok');
  if (texto) setTimeout(() => { el.textContent = ''; el.className = 'form-msg'; }, 3500);
}

/* ---------------- Navegação ---------------- */

const PARENTE = {
  conciliacao: 'modulos', sintetico: 'conciliacao', analitico: 'sintetico',
  gerencia: 'conciliacao', 'gerencia-detalhe': 'gerencia',
  responsaveis: 'conciliacao', remessas: 'conciliacao',
  gestao: 'modulos', convenios: 'gestao', convenio: 'convenios',
  originadoras: 'gestao',
  usuarios: 'modulos',
};
const BREADCRUMB = {
  modulos: 'Módulos',
  conciliacao: 'Módulos › Conciliação',
  sintetico: 'Módulos › Conciliação › Controle Sintético',
  analitico: 'Módulos › Conciliação › Controle Sintético › Analítico',
  gerencia: 'Módulos › Conciliação › Gerência de Convênios',
  'gerencia-detalhe':
    'Módulos › Conciliação › Gerência de Convênios › Convênio',
  responsaveis: 'Módulos › Conciliação › Responsáveis pela Conciliação',
  remessas: 'Módulos › Conciliação › Remessas',
  gestao: 'Módulos › Gestão de Convênios',
  convenios: 'Módulos › Gestão de Convênios › Convênios',
  convenio: 'Módulos › Gestão de Convênios › Convênios › Convênio',
  originadoras: 'Módulos › Gestão de Convênios › Originadoras',
  usuarios: 'Módulos › Segurança › Gestão de Usuários',
};

let paginaAtual = 'modulos';

function navegar(page) {
  paginaAtual = page;
  $$('.page').forEach((p) => (p.hidden = p.id !== 'page-' + page));
  $('#breadcrumb').textContent = BREADCRUMB[page];
  $('#btn-back').hidden = page === 'modulos';
  window.scrollTo(0, 0);

  // A Gestão de Convênios busca os dados dela ao entrar: quem abriu o
  // painel para conciliar não paga por um cadastro que não vai ver.
  if (typeof aoEntrarNaPaginaDeConvenios === 'function') {
    aoEntrarNaPaginaDeConvenios(page);
  }
  if (page === 'gerencia' && typeof aoEntrarNaGerencia === 'function') {
    aoEntrarNaGerencia();
  }
  if (page === 'responsaveis' && typeof aoEntrarNosResponsaveis === 'function') {
    aoEntrarNosResponsaveis();
  }
  if (page === 'remessas' && typeof aoEntrarNasRemessas === 'function') {
    aoEntrarNasRemessas();
  }
  if (page === 'usuarios' && typeof aoEntrarNaGestaoUsuarios === 'function') {
    aoEntrarNaGestaoUsuarios();
  }
}

function voltar() {
  navegar(PARENTE[paginaAtual] || 'modulos');
}

/* ---------------- Modo de operação ---------------- */

/*
  'api'  — dados reais do COFCT, somente leitura (etapa 1 da integração:
           a gravação no COFCT passa pela fila de comandos, ainda não
           implementada aqui).
  'demo' — store local em localStorage, com leitura e escrita.
*/
let MODO = 'demo';

const BOTOES_DE_ESCRITA = [
  'btn-salvar-conciliacao', 'btn-salvar-secretaria', 'btn-salvar-part',
  'btn-salvar-fin', 'btn-salvar-conta', 'btn-salvar-contato',
  'btn-registrar-cobranca',
];

function aplicarModo(modo) {
  MODO = modo;
  const somenteLeitura = modo === 'api';

  BOTOES_DE_ESCRITA.forEach((id) => {
    const btn = $('#' + id);
    if (btn) btn.disabled = somenteLeitura;
  });

  const banner = $('#banner-modo');
  banner.hidden = false;
  banner.className = 'alert alert-modo ' + (somenteLeitura ? 'is-api' : 'is-demo');
  banner.innerHTML = somenteLeitura
    ? '🔒 <b>Dados reais do banco</b> — a <b>Conciliação</b> está em somente '
      + 'leitura: a gravação no COFCT passa pela fila de comandos e ainda não '
      + 'está ligada ao painel. A <b>Gestão de Convênios</b> grava normalmente.'
    : '🧪 <b>Modo demonstração</b> — sem servidor: os dados são de exemplo e '
      + 'ficam salvos apenas neste navegador.';
}

// Bloqueia a gravação enquanto o painel está lendo dados reais.
function bloqueadoParaEscrita(msgId) {
  if (MODO !== 'api') return false;
  msgInline(
    msgId,
    'Somente leitura: a gravação no banco ainda não está ligada ao painel.',
    'erro',
  );
  return true;
}

async function iniciarFonteDeDados() {
  if (!apiDisponivel()) {
    preencherFiltros();
    aplicarModo('demo');
    return;
  }
  try {
    const filtros = await apiFiltros();
    preencherSelect($('#f-mes'), filtros.competencias, filtros.competencias[0]);
    preencherSelect(
      $('#f-originador'), filtros.originadores, filtros.originadores[0],
    );
    preencherSelect($('#f-status'), ['Todos', ...STATUS_CONCILIACAO_OPCOES], 'Todos');
    preencherSelect($('#f-motivo'), ['Todos', ...MOTIVO_FALTA_OPCOES], 'Todos');
    aplicarModo('api');
  } catch (erro) {
    apiRegistrarFalha(erro);
    preencherFiltros();
    aplicarModo('demo');
  }
}

/* ---------------- Sintético ---------------- */

let convenioSelecionado = null;

function preencherSelect(sel, opcoes, valor) {
  sel.innerHTML = '';
  for (const opt of opcoes) {
    const o = document.createElement('option');
    if (opt && typeof opt === 'object') {
      o.value = opt.value;
      o.textContent = opt.label;
    } else {
      o.value = opt;
      o.textContent = opt;
    }
    sel.appendChild(o);
  }
  if (valor !== undefined && [...sel.options].some((o) => o.value === valor)) sel.value = valor;
}

function preencherFiltros() {
  const { meses, originadores, statuses, motivos } = STORE.opcoesFiltro();
  preencherSelect($('#f-mes'), meses, meses[0]);
  preencherSelect($('#f-originador'), originadores, originadores[0]);
  preencherSelect($('#f-status'), statuses, 'Todos');
  preencherSelect($('#f-motivo'), motivos, 'Todos');
}

const STATUS_BADGE = {
  'CONCILIADO': 'badge-ok',
  'CONCILIADO (PARCIAL)': 'badge-warn',
  'PENDENTE': 'badge-danger',
};

// Status, motivo e busca rodam no cliente: a API devolve a competência
// inteira e o filtro fino não justifica ida ao banco.
function filtrarLinhas(linhas, filtros) {
  return linhas
    .filter((l) => !filtros.status || filtros.status === 'Todos'
      || l.resumo.status_conciliacao === filtros.status)
    .filter((l) => !filtros.motivo || filtros.motivo === 'Todos'
      || (l.resumo.motivos || []).includes(filtros.motivo))
    .filter((l) => {
      if (!filtros.busca) return true;
      const c = l.convenio;
      const alvo = `${c.nome_convenio} ${c.cnpj_convenio} ${c.numero_convenio}`;
      return alvo.toLowerCase().includes(filtros.busca.toLowerCase());
    });
}

async function pesquisar() {
  const mes = $('#f-mes').value;
  const originador = $('#f-originador').value;
  if (!mes || !originador) {
    toast('Selecione a competência e a originadora.', 'erro');
    return;
  }
  const filtros = {
    mes, originador,
    status: $('#f-status').value,
    motivo: $('#f-motivo').value,
    busca: $('#f-busca').value.trim(),
  };

  if (MODO === 'api') {
    try {
      const linhas = await apiSintetico(mes, originador);
      renderSintetico(filtrarLinhas(linhas, filtros));
    } catch (erro) {
      apiRegistrarFalha(erro);
      toast('Falha ao consultar o banco. Veja o console.', 'erro');
    }
    return;
  }
  renderSintetico(STORE.listarConvenios(filtros));
}

function renderSintetico(linhas) {
  const tbody = $('#tbl-sintetico-body');
  const empty = $('#sintetico-empty');
  tbody.innerHTML = '';
  convenioSelecionado = null;

  $('#sintetico-resumo').textContent = `${linhas.length} registro(s) encontrado(s)`;
  empty.hidden = linhas.length > 0;

  for (const linha of linhas) {
    const c = linha.convenio;
    const r = linha.resumo;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${linha.competencia}</td>
      <td>${c.originador}</td>
      <td>${c.numero_convenio}</td>
      <td class="cell-left">${c.nome_convenio}</td>
      <td><span class="badge ${STATUS_BADGE[r.status_conciliacao] || ''}">${r.status_conciliacao}</span></td>
      <td>dia ${r.dias_venc}</td>
      <td>${r.data_baixa || '—'}</td>
      <td>${r.data_corte || '—'}</td>
      <td>${r.qtd_dias_inadimplencia}</td>
      <td>${brPercent(r.porcentagem_inadimplencia)}</td>
    `;
    tr.addEventListener('click', () => {
      $$('#tbl-sintetico-body tr').forEach((outra) => outra.classList.remove('selected'));
      tr.classList.add('selected');
      convenioSelecionado = linha;
    });
    tr.addEventListener('dblclick', () => { convenioSelecionado = linha; abrirAnalitico(); });
    tbody.appendChild(tr);
  }
}

async function abrirAnalitico() {
  if (!convenioSelecionado) {
    toast('Selecione uma linha na tabela.', 'erro');
    return;
  }
  const { convenio, competencia } = convenioSelecionado;

  if (MODO === 'api') {
    try {
      // No Sintético a linha traz só a identificação; o Analítico precisa
      // dos vencimentários de todas as competências.
      const completo = await apiConvenio(
        convenio.originador,
        convenio.numero_convenio,
      );
      renderAnalitico(completo, competencia);
    } catch (erro) {
      apiRegistrarFalha(erro);
      toast('Falha ao abrir o convênio. Veja o console.', 'erro');
      return;
    }
  } else {
    renderAnalitico(convenio, competencia);
  }

  navegar('analitico');
  // Só agora a tabela tem altura para medir as 3 linhas visíveis.
  ajustarAlturaDashboard();
}

/* ---------------- Analítico: infra ---------------- */

let convAtivo = null;
// Id do vencimentário aberto. Guardar o id (e não o índice) mantém a
// seleção válida com a tabela ordenada por competência.
let vencAtivoId = null;

function vencAtivo() {
  return convAtivo.vencimentarios.find((v) => v.id === vencAtivoId);
}

function renderGrid(tableEl, cols, rows, onRowClick) {
  const thead = tableEl.querySelector('thead');
  const tbody = tableEl.querySelector('tbody');
  thead.innerHTML = '<tr>' + cols.map((c) => `<th>${c.label}</th>`).join('') + '</tr>';
  tbody.innerHTML = '';

  if (!rows.length) {
    tbody.innerHTML = `<tr><td class="cell-empty" colspan="${cols.length}">Nenhum registro.</td></tr>`;
    return;
  }
  rows.forEach((rec) => {
    const tr = document.createElement('tr');
    cols.forEach((c) => {
      const td = document.createElement('td');
      if (c.left) td.classList.add('cell-left');
      if (c.wrap) td.classList.add('cell-wrap');
      if (c.trunc) {
        td.classList.add('cell-trunc');
        td.title = rec[c.key] || '';
      }
      if (c.flag) {
        preencherFlags(td, rec[c.key]);
      } else {
        td.textContent = fmtValor(c.fmt, rec[c.key]) || '—';
      }
      tr.appendChild(td);
    });
    if (onRowClick) tr.addEventListener('click', () => {
      [...tbody.children].forEach((r) => r.classList.remove('selected'));
      tr.classList.add('selected');
      onRowClick(rec);
    });
    tbody.appendChild(tr);
  });
}

// Exibe um valor como flag(s) coloridas — vale para valor único e para
// vários juntos (array ou lista separada por vírgula), como no modelo de
// envio, que pode ter mais de uma situação ao mesmo tempo.
function preencherFlags(td, valor) {
  const partes = Array.isArray(valor) ? valor : String(valor || '').split(',');
  const flags = partes.map((p) => p.trim()).filter(Boolean);

  if (!flags.length) {
    td.textContent = '—';
    return;
  }
  // As flags vão num wrapper interno; a <td> continua célula de tabela
  // normal (vertical-align middle), senão o flex quebra o alinhamento.
  const wrap = document.createElement('div');
  wrap.className = 'cell-flags';
  flags.forEach((f) => {
    const chip = document.createElement('span');
    chip.className = 'chip chip-flag flag-c' + (_hashFlag(f) % 6);
    chip.textContent = f;
    wrap.appendChild(chip);
  });
  td.appendChild(wrap);
}

function _hashFlag(texto) {
  let h = 0;
  for (let i = 0; i < texto.length; i += 1) {
    h = (h * 31 + texto.charCodeAt(i)) >>> 0;
  }
  return h;
}

function renderAnalitico(conv, competencia) {
  convAtivo = conv;
  // Abre no vencimentário da competência que veio do Sintético.
  const daCompetencia = STORE.vencimentariosDaCompetencia(conv, competencia);
  const inicial = daCompetencia[0] || STORE.vencimentariosOrdenados(conv)[0];
  vencAtivoId = inicial.id;

  renderCabecalhoAnalitico();

  // Selects que dependem do cadastro de secretarias — antes dos CRUDs.
  atualizarSelectsSecretaria();

  renderVencDashboard();
  trocarAba('conciliacao');
  // Compartilhado (regra do convênio) — renderiza uma vez:
  crudSecretaria.render();
  crudParticularidade.render();
  crudConta.render();
  crudContato.render();
  // Por vencimentário:
  renderDadosVencimentario();
}

/* ---- Dashboard de vencimentários (resumo estilo Sintético) ---- */

const LINHAS_VISIVEIS_VENC = 3;

const VENC_COLS = [
  { label: 'Competência' },
  { label: 'Vencimento' },
  { label: 'Status conciliação' },
  { label: 'Cenário' },
  { label: 'Remessa' },
  { label: 'Retorno' },
  { label: 'Repasse (financeiro)' },
  { label: 'Pendente' },
  { label: '% Inadimp' },
  { label: 'Contratos' },
  { label: 'Conciliado' },
];

function renderCabecalhoAnalitico() {
  const conv = convAtivo;
  const producao = conv.status_producao
    ? ` · Produção <b>${conv.status_producao}</b>`
    : '';
  $('#analitico-header').innerHTML =
    `<b>${conv.nome_convenio}</b> · Nº ${conv.numero_convenio} · CNPJ ${conv.cnpj_convenio} · `
    + `Originador ${conv.originador} · ${conv.vencimentarios.length} vencimentário(s) · `
    + `Competência aberta <b>${vencAtivo().competencia}</b>${producao}`;
}

function renderVencDashboard() {
  const tbl = $('#tbl-venc');
  tbl.querySelector('thead').innerHTML =
    '<tr>' + VENC_COLS.map((c) => `<th>${c.label}</th>`).join('') + '</tr>';
  const tbody = tbl.querySelector('tbody');
  tbody.innerHTML = '';

  STORE.vencimentariosOrdenados(convAtivo).forEach((v) => {
    const cc = v.conciliacao;
    const repasse = STORE.somaRepasseFinanceiro(v);
    const pendente = STORE.valorPendenteVencimentario(v);
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><b>${v.competencia}</b></td>
      <td>${v.dia_vencimento}</td>
      <td><span class="badge ${STATUS_BADGE[cc.status_conciliacao] || ''}">${cc.status_conciliacao}</span></td>
      <td class="cell-left">${cc.cenario_conciliacao || '—'}</td>
      <td>${brMoney(cc.valor_remessa)}</td>
      <td>${brMoney(cc.valor_retorno)}</td>
      <td>${brMoney(repasse)}</td>
      <td class="${pendente > 0 ? 'cell-alerta' : ''}">${brMoney(pendente)}</td>
      <td>${brPercent(cc.porcentagem_inadimplencia)}</td>
      <td>${cc.qtd_contratos}</td>
      <td>${STORE.estaConciliado(v) ? '✓' : '—'}</td>
    `;
    if (v.id === vencAtivoId) tr.classList.add('selected');
    tr.addEventListener('click', () => selecionarVencimentario(v.id));
    tbody.appendChild(tr);
  });

  ajustarAlturaDashboard();
}

// Mostra 3 vencimentários; o resto fica a um scroll de distância.
// A altura é medida, e não fixada em CSS, para continuar valendo 3
// linhas com outro zoom ou outra fonte.
function ajustarAlturaDashboard() {
  const janela = $('#venc-scroll');
  const linhas = $$('#tbl-venc tbody tr');

  if (linhas.length <= LINHAS_VISIVEIS_VENC) {
    janela.style.maxHeight = '';
    return;
  }

  const cabecalho = $('#tbl-venc thead').offsetHeight;
  // Página ainda oculta: medida sai zerada, ajusta depois de navegar.
  if (!cabecalho) return;

  const alturaDasLinhas = linhas
    .slice(0, LINHAS_VISIVEIS_VENC)
    .reduce((total, linha) => total + linha.offsetHeight, 0);

  janela.style.maxHeight = `${cabecalho + alturaDasLinhas}px`;
}

function selecionarVencimentario(id) {
  if (id === vencAtivoId) return;
  vencAtivoId = id;
  renderCabecalhoAnalitico();
  renderVencDashboard();
  renderDadosVencimentario();
}

// Renderiza apenas o que muda por vencimentário (Conciliação/Financeiro/Cobrança).
function renderDadosVencimentario() {
  const rot = STORE.rotuloVencimentario(vencAtivo());
  $$('.venc-atual').forEach((el) => (el.textContent = rot));
  // Deixa explícito a qual vencimentário o repasse será lançado.
  $('#titulo-form-financeiro').textContent = `Repasse para ${rot}`;
  renderConciliacaoForm();
  renderSecretariasDevedoras();
  crudFinanceiro.render();
  crudFinanceiro.clearForm();
  atualizarConfronto();
  renderCobranca();
}

/* ---- Confronto financeiro: custo + status automático ao vivo ---- */

// Ao digitar o valor recebido (e a quantidade, quando o custo exige), o
// servidor calcula o custo aplicado e classifica o status pela diferença.
// A regra vive no servidor (fonte única); aqui só exibimos.
async function atualizarConfronto() {
  if (!apiDisponivel() || !convAtivo) return;
  const venc = vencAtivo();
  if (!venc) return;

  const compBr = venc.competencia || '';
  const competencia = compBr.includes('/')
    ? compBr.split('/').reverse().join('-')
    : compBr;

  try {
    const c = await apiConfronto(
      convAtivo.originador, convAtivo.numero_convenio,
      {
        competencia,
        valor_retorno: Number(venc.conciliacao.valor_retorno) || 0,
        valor_recebido: parseNumeroBR($('#fin-recebido').value) || 0,
        quantidade: Number($('#fin-quantidade').value) || 0,
      },
    );
    $('#fin-quantidade-campo').hidden = !c.exige_quantidade;
    $('#fin-custo').value = brMoney(c.custo);
    $('#fin-status').value = c.status;
    $('#fin-devendo').value = brMoney(c.devendo);
  } catch (_) {
    // Sem servidor não há confronto; os campos ficam como estão.
  }
}

function trocarAba(tab) {
  $$('#analitico-tabs .tab-btn').forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
  $$('.tab-panel').forEach((p) => (p.hidden = p.id !== 'tab-' + tab));
}

/* ---------------- Aba Conciliação (form via DADOS_FIELDS) ---------------- */

// Valores derivados: o operador não digita nenhum dos dois.
function valorComputado(chave, venc) {
  if (chave === 'repasse') return STORE.somaRepasseFinanceiro(venc);
  if (chave === 'pendente') return STORE.valorPendenteVencimentario(venc);
  return '';
}

function renderConciliacaoForm() {
  const venc = vencAtivo();
  const cc = venc.conciliacao;
  const cont = $('#form-conciliacao');
  cont.innerHTML = '';

  for (const f of DADOS_FIELDS) {
    const wrap = document.createElement('div');
    wrap.className = 'field';
    wrap.dataset.key = f.key;

    const valor = f.computed ? valorComputado(f.computed, venc) : cc[f.key];

    let controle;
    if (f.type === 'select') {
      controle = document.createElement('select');
      preencherSelect(controle, f.options, valor || f.options[0]);
    } else if (f.type === 'textarea') {
      controle = document.createElement('textarea');
      controle.rows = 3;
      controle.value = valor ?? '';
    } else {
      controle = document.createElement('input');
      controle.value = f.editable ? (valor ?? '') : fmtValor(f.fmt, valor);
    }
    // data-campo fica só no controle. O wrapper usa data-key, e um
    // seletor por data-key acharia a <div> antes do input.
    controle.dataset.campo = f.key;
    if (!f.editable) controle.disabled = true;

    // O repasse pode vir do Financeiro ou da própria conciliação do
    // banco; o rótulo tem que dizer qual dos dois está na tela.
    let textoNota = f.nota || 'somente leitura';
    if (f.computed === 'repasse' && !STORE.repasseVemDoFinanceiro(venc)) {
      textoNota = 'valor da conciliação — sem lançamento no Financeiro';
    }
    const nota = f.editable ? '' : ` <span class="ro">(${textoNota})</span>`;
    const label = document.createElement('label');
    label.innerHTML = f.label + nota;
    wrap.appendChild(label);
    wrap.appendChild(controle);
    cont.appendChild(wrap);

    if (f.depends_on) {
      wrap.hidden = !f.depends_on.show_when.includes(cc[f.depends_on.field]);
    }
  }

  cont.querySelector('[data-campo="status_conciliacao"]').addEventListener('change', (e) => {
    const motivoWrap = cont.querySelector('.field[data-key="motivo_falta_conciliacao"]');
    if (motivoWrap) motivoWrap.hidden = e.target.value !== 'CONCILIADO (PARCIAL)';
  });
  const inpRetorno = cont.querySelector('[data-campo="valor_retorno"]');
  if (inpRetorno) inpRetorno.addEventListener('input', atualizarPendente);
}

// Pendente = valor retorno digitado - repasse já lançado no Financeiro.
function atualizarPendente() {
  const cont = $('#form-conciliacao');
  const ret = parseNumeroBR(cont.querySelector('[data-campo="valor_retorno"]').value) || 0;
  const rep = STORE.somaRepasseFinanceiro(vencAtivo());
  const pend = cont.querySelector('[data-campo="valor_pendente"]');
  if (pend) pend.value = brMoney(ret - rep);
}

function salvarConciliacao() {
  if (bloqueadoParaEscrita('msg-conciliacao')) return;

  const cont = $('#form-conciliacao');
  const cc = vencAtivo().conciliacao;
  for (const f of DADOS_FIELDS) {
    if (!f.editable || f.computed) continue;
    const el = cont.querySelector(`[data-campo="${f.key}"]`);
    if (!el) continue;
    cc[f.key] = (f.fmt === 'money' || f.fmt === 'percent' || f.fmt === 'int')
      ? parseNumeroBR(el.value)
      : el.value;
  }
  STORE.salvar();
  renderVencDashboard();
  msgInline('msg-conciliacao', 'Dados salvos com sucesso.');
  toast('Conciliação salva.', 'ok');
}

/* ---- Secretarias devedoras (evidência na Conciliação) ---- */

function renderSecretariasDevedoras() {
  const card = $('#card-secretarias-devedoras');
  const lista = $('#lista-secretarias-devedoras');
  const cadastradas = convAtivo.secretarias || [];

  card.hidden = cadastradas.length === 0;
  if (card.hidden) return;

  const devedoras = STORE.secretariasDevedoras(convAtivo, vencAtivo());
  lista.innerHTML = '';

  if (!devedoras.length) {
    const ok = document.createElement('span');
    ok.className = 'chip chip-ok';
    ok.textContent = 'Todas as secretarias ativas têm repasse lançado neste vencimentário.';
    lista.appendChild(ok);
    return;
  }
  devedoras.forEach((s) => {
    const chip = document.createElement('span');
    chip.className = 'chip chip-danger';
    chip.textContent = s.codigo ? `${s.nome} (${s.codigo})` : s.nome;
    lista.appendChild(chip);
  });
}

/* ---- Selects alimentados pelo cadastro de secretarias ---- */

function secretariasAtivas() {
  return (convAtivo.secretarias || [])
    .filter((s) => s.status_secretaria === 'ATIVA')
    .map((s) => s.nome);
}

function atualizarSelectsSecretaria() {
  const ativas = secretariasAtivas();

  // Convênio sem secretaria cadastrada: o repasse não fica preso a um
  // cadastro que não existe — cai no balde padrão "Nenhuma Sec. Reg.",
  // já pré-selecionado, e a conciliação segue normalmente.
  const selFin = $('#fin-secretaria');
  const opcoesFin = ativas.length
    ? [{ value: '', label: '(não informado)' }, SECRETARIA_TODAS, ...ativas]
    : [SECRETARIA_NENHUMA];
  preencherSelect(selFin, opcoesFin, selFin.value || SECRETARIA_NENHUMA);

  const selContato = $('#contato-secretaria');
  preencherSelect(selContato, [SECRETARIA_TODAS, ...ativas], selContato.value);
}

/* ---------------- CRUD genérico (secretaria/particularidade/financeiro/conta/contato) ---------------- */

function criarCrud(cfg) {
  let editId = null;
  const panel = () => $('#tab-' + cfg.tab);
  const inputs = () => $$('[data-f]', panel());
  const colecaoAlvo = () => (cfg.escopo === 'vencimentario' ? vencAtivo()[cfg.colecao] : convAtivo[cfg.colecao]);

  function render() {
    renderGrid($('#' + cfg.tableId), cfg.cols, colecaoAlvo(), loadForm);
  }

  function loadForm(rec) {
    editId = rec.id;
    inputs().forEach((el) => {
      const valor = rec[el.dataset.f] ?? '';
      // Valor histórico fora da lista (ex.: secretaria inativada) não pode
      // sumir do formulário — vira opção extra para não corromper o registro.
      if (el.tagName === 'SELECT' && valor && ![...el.options].some((o) => o.value === valor)) {
        const extra = document.createElement('option');
        extra.value = valor;
        extra.textContent = valor;
        el.appendChild(extra);
      }
      el.value = valor;
    });
    cfg.afterLoad && cfg.afterLoad();
  }

  function clearForm() {
    editId = null;
    inputs().forEach((el) => {
      el.value = el.tagName === 'SELECT' ? (el.options[0] ? el.options[0].value : '') : '';
    });
    cfg.afterLoad && cfg.afterLoad();
  }

  function save() {
    if (bloqueadoParaEscrita(cfg.msgId)) return;

    const dados = {};
    inputs().forEach((el) => { dados[el.dataset.f] = typeof el.value === 'string' ? el.value.trim() : el.value; });

    if (cfg.required && !dados[cfg.required]) {
      msgInline(cfg.msgId, `Campo obrigatório: ${cfg.required}.`, 'erro');
      return;
    }
    const recusa = cfg.validar && cfg.validar(dados);
    if (recusa) {
      msgInline(cfg.msgId, recusa, 'erro');
      return;
    }

    // Campos que o contexto da tela decide — o operador não digita.
    const completo = { ...dados, ...(cfg.camposAutomaticos?.() || {}) };

    const colecao = colecaoAlvo();
    if (editId) {
      const rec = colecao.find((r) => r.id === editId);
      Object.assign(rec, completo, { atualizado_em: STORE.agora() });
      msgInline(cfg.msgId, 'Registro atualizado.');
    } else {
      colecao.push({ id: STORE.uid(), ...completo, criado_em: STORE.agora(), atualizado_em: '' });
      msgInline(cfg.msgId, 'Registro criado.');
    }
    STORE.salvar();
    render();
    clearForm();
    cfg.afterSave && cfg.afterSave();
    toast('Salvo.', 'ok');
  }

  $('#' + cfg.saveBtnId).addEventListener('click', save);
  $('#' + cfg.newBtnId).addEventListener('click', clearForm);

  return { render, clearForm };
}

const COLS = {
  secretaria: [
    { key: 'status_secretaria', label: 'Status' },
    { key: 'nome', label: 'Secretaria', left: true },
    { key: 'codigo', label: 'Código' },
    { key: 'observacao', label: 'Observação', left: true, wrap: true },
  ],
  particularidade: [
    { key: 'status_particularidade', label: 'Status' },
    { key: 'rubrica_produto', label: 'Rubrica/Produto', left: true },
    { key: 'modelo_de_averbacao', label: 'Averbação', flag: true },
    { key: 'retencao', label: 'Retenção' },
    { key: 'retencao_percent', label: '% ret.' },
    { key: 'observacao', label: 'Observação', left: true, wrap: true },
  ],
  // Sem competência: a grade só mostra os repasses do vencimentário
  // aberto, então a coluna seria a mesma em todas as linhas.
  financeiro: [
    { key: 'secretaria', label: 'Secretaria', left: true },
    { key: 'status_financeiro', label: 'Status' },
    { key: 'data_efetiva', label: 'Recebimento' },
    { key: 'valor_recebido', label: 'V. recebido', fmt: 'money' },
    { key: 'custo', label: 'Custo', fmt: 'money' },
    { key: 'devendo', label: 'Devendo', fmt: 'money' },
    { key: 'observacao', label: 'Observação', left: true, wrap: true },
  ],
  conta: [
    { key: 'banco', label: 'Banco', left: true },
    { key: 'agencia', label: 'Agência' },
    { key: 'conta', label: 'Conta' },
    { key: 'chave_pix', label: 'Chave Pix', left: true },
    { key: 'cnpj', label: 'CNPJ' },
    { key: 'status_conta', label: 'Status' },
  ],
  contato: [
    { key: 'status', label: 'Status' },
    { key: 'secretaria', label: 'Secretaria', left: true },
    { key: 'nome', label: 'Nome', left: true },
    { key: 'email', label: 'E-mail', left: true },
    { key: 'telefone', label: 'Telefone' },
    { key: 'area', label: 'Área' },
    { key: 'observacao', label: 'Observação', left: true, wrap: true },
  ],
  cobrancaHist: [
    { key: 'data_hora', label: 'Data/hora' },
    { key: 'canal', label: 'Canal' },
    { key: 'resultado', label: 'Resultado' },
    { key: 'contato_nome', label: 'Contato' },
    { key: 'observacao', label: 'Observação', left: true, wrap: true },
    { key: 'ator', label: 'Ator' },
  ],
};

let crudSecretaria, crudParticularidade, crudFinanceiro, crudConta, crudContato;

// Sem competência para preencher, o formulário vazio salvaria uma linha
// em branco sem reclamar. O valor recebido é obrigatório.
function exigirAlgumValor(dados) {
  return dados.valor_recebido
    ? null
    : 'Informe o valor recebido.';
}

// O Financeiro é a fonte do Valor repasse: ao salvar, tudo que depende
// dele é redesenhado (Conciliação, dashboard e secretarias devedoras).
function refletirFinanceiro() {
  renderConciliacaoForm();
  renderVencDashboard();
  renderSecretariasDevedoras();
}

function refletirSecretarias() {
  atualizarSelectsSecretaria();
  renderSecretariasDevedoras();
  crudContato.render();
}

/* ---------------- Aba Cobrança ---------------- */

const RESULTADO_LABEL = {
  sem_resposta: 'Sem resposta', contato_efetivo: 'Contato efetivo',
  retornar: 'Pediu para retornar', recusado: 'Recusou', regularizou: 'Regularizou',
};

function renderCobranca() {
  $('#titulo-cobranca-hist').textContent =
    `Histórico de tentativas — ${STORE.rotuloVencimentario(vencAtivo())}`;

  const hist = STORE.tentativasDaCompetencia(vencAtivo())
    .map((h) => ({ ...h, resultado: RESULTADO_LABEL[h.resultado] || h.resultado }));
  renderGrid($('#tbl-cobranca-hist'), COLS.cobrancaHist, hist, null);

  const sel = $('#cob-contato');
  // Rótulo mostra a secretaria; o valor gravado continua sendo só o nome.
  const opcoes = convAtivo.contatos
    .filter((c) => c.status === 'ATIVO')
    .map((c) => ({
      value: c.nome,
      label: c.secretaria ? `${c.nome} — ${c.secretaria}` : c.nome,
    }));
  preencherSelect(
    sel,
    opcoes.length ? opcoes : [{ value: '', label: '(cadastre um contato na aba Contato)' }],
  );
}

function registrarCobranca() {
  if (bloqueadoParaEscrita('msg-cobranca')) return;

  const panel = $('#tab-cobranca');
  const dados = {};
  $$('[data-f]', panel).forEach((el) => { dados[el.dataset.f] = el.value; });

  if (!dados.contato_nome) {
    msgInline('msg-cobranca', 'Selecione o contato acionado.', 'erro');
    return;
  }
  // A aba só mostra tentativas da competência aberta: barrar data de fora
  // evita registrar algo que sumiria da tela logo em seguida.
  const compInformada = STORE.competenciaDaData(dados.data_hora);
  if (compInformada && compInformada !== vencAtivo().competencia) {
    msgInline('msg-cobranca', `Data fora da competência ${vencAtivo().competencia}.`, 'erro');
    return;
  }
  vencAtivo().cobranca_historico.push({
    id: STORE.uid(),
    data_hora: dados.data_hora || STORE.agora(),
    canal: dados.canal,
    resultado: dados.resultado,
    contato_nome: dados.contato_nome,
    observacao: dados.observacao || '',
    ator: 'usuario',
    criado_em: STORE.agora(),
  });

  STORE.salvar();
  renderCobranca();
  $('#cob-data').value = '';
  $('[data-f="observacao"]', panel).value = '';

  const total = STORE.tentativasDaCompetencia(vencAtivo()).length;
  msgInline('msg-cobranca', `Tentativa registrada. Total na competência: ${total}.`);
  toast('Tentativa de cobrança registrada.', 'ok');
}

/* ---------------- Setup ---------------- */

function togglePartRetencao() {
  const mostra = $('#part-retencao').value === 'SIM';
  $$('#tab-particularidade .part-retencao-campo').forEach((el) => (el.hidden = !mostra));
}

/* ---------------- Tema (claro / escuro) ---------------- */

const TEMA_KEY = 'cofc_tema';

// Ícones da família SCO (stroke herda a cor do botão via currentColor).
const ICONE_SOL =
  '<svg viewBox="0 0 48 48" width="16" height="16" fill="none" '
  + 'stroke="currentColor" stroke-width="2.6" stroke-linecap="round" '
  + 'stroke-linejoin="round" style="vertical-align:-3px">'
  + '<circle cx="24" cy="24" r="8"/><path d="M24 4 V9 M24 39 V44 M4 24 H9 '
  + 'M39 24 H44 M11 11 L14.5 14.5 M33.5 33.5 L37 37 M37 11 L33.5 14.5 '
  + 'M14.5 33.5 L11 37"/></svg>';
const ICONE_LUA =
  '<svg viewBox="0 0 48 48" width="16" height="16" fill="none" '
  + 'stroke="currentColor" stroke-width="2.6" stroke-linecap="round" '
  + 'stroke-linejoin="round" style="vertical-align:-3px">'
  + '<path d="M32 10 A15 15 0 1 0 32 38 A11 11 0 0 1 32 10 Z"/></svg>';

// Botão único: mostra o tema em uso — sol no claro, lua no escuro.
function aplicarTema(tema) {
  const t = tema === 'dark' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', t);
  localStorage.setItem(TEMA_KEY, t);

  const btn = $('#btn-tema');
  btn.innerHTML = t === 'dark'
    ? `${ICONE_LUA} Escuro`
    : `${ICONE_SOL} Claro`;
  btn.title = t === 'dark' ? 'Mudar para o tema claro' : 'Mudar para o tema escuro';
}

function temaAtual() {
  return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
}

function setupTema() {
  aplicarTema(localStorage.getItem(TEMA_KEY) || 'light');
  $('#btn-tema').addEventListener(
    'click',
    () => aplicarTema(temaAtual() === 'dark' ? 'light' : 'dark'),
  );
}

async function setup() {
  setupTema();
  STORE.carregar();
  navegar('modulos');

  $('#btn-back').addEventListener('click', voltar);
  $$('[data-goto]').forEach((b) => b.addEventListener('click', () => navegar(b.dataset.goto)));

  // Clicar na marca (logo Alvo Card) volta para a página inicial (Módulos).
  const marca = $('.app-title');
  if (marca) {
    marca.style.cursor = 'pointer';
    marca.addEventListener('click', () => navegar('modulos'));
  }

  $('#btn-filtrar').addEventListener('click', pesquisar);
  $('#btn-abrir').addEventListener('click', abrirAnalitico);
  $('#btn-limpar').addEventListener('click', () => {
    $('#f-status').value = 'Todos';
    $('#f-motivo').value = 'Todos';
    ['f-venc', 'f-sla', 'f-corte', 'f-busca'].forEach((id) => ($('#' + id).value = ''));
    $('#tbl-sintetico-body').innerHTML = '';
    $('#sintetico-resumo').textContent = '0 registro(s) encontrado(s)';
    $('#sintetico-empty').hidden = false;
  });

  $$('#analitico-tabs .tab-btn').forEach((b) => b.addEventListener('click', () => trocarAba(b.dataset.tab)));

  $('#btn-salvar-conciliacao').addEventListener('click', salvarConciliacao);

  // Compartilhado (regra do convênio) — escopo 'convenio':
  crudSecretaria = criarCrud({
    tab: 'secretaria', escopo: 'convenio', colecao: 'secretarias', cols: COLS.secretaria,
    tableId: 'tbl-secretaria', saveBtnId: 'btn-salvar-secretaria', newBtnId: 'btn-novo-secretaria',
    msgId: 'msg-secretaria', required: 'nome', afterSave: refletirSecretarias,
  });
  crudParticularidade = criarCrud({
    tab: 'particularidade', escopo: 'convenio', colecao: 'particularidades', cols: COLS.particularidade,
    tableId: 'tbl-particularidade', saveBtnId: 'btn-salvar-part', newBtnId: 'btn-novo-part',
    msgId: 'msg-part', required: 'rubrica_produto', afterLoad: togglePartRetencao,
  });
  crudConta = criarCrud({
    tab: 'conta', escopo: 'convenio', colecao: 'contas', cols: COLS.conta,
    tableId: 'tbl-conta', saveBtnId: 'btn-salvar-conta', newBtnId: 'btn-novo-conta',
    msgId: 'msg-conta', required: 'banco',
  });
  crudContato = criarCrud({
    tab: 'contato', escopo: 'convenio', colecao: 'contatos', cols: COLS.contato,
    tableId: 'tbl-contato', saveBtnId: 'btn-salvar-contato', newBtnId: 'btn-novo-contato',
    msgId: 'msg-contato', required: 'nome', afterSave: renderCobranca,
  });
  // Por vencimentário — escopo 'vencimentario':
  crudFinanceiro = criarCrud({
    tab: 'financeiro', escopo: 'vencimentario', colecao: 'financeiro', cols: COLS.financeiro,
    tableId: 'tbl-financeiro', saveBtnId: 'btn-salvar-fin', newBtnId: 'btn-novo-fin',
    msgId: 'msg-fin', afterSave: refletirFinanceiro,
    // O repasse é do vencimentário aberto: competência e dia vêm da
    // linha selecionada no dashboard, não de campo digitado.
    camposAutomaticos: () => STORE.carimbarVencimentario(vencAtivo(), {}),
    validar: exigirAlgumValor,
  });

  $('#part-retencao').addEventListener('change', togglePartRetencao);
  $('#btn-registrar-cobranca').addEventListener('click', registrarCobranca);
  // Confronto ao vivo: recalcula custo/status ao digitar valor ou quantidade.
  ['#fin-recebido', '#fin-quantidade'].forEach((sel) => {
    const el = $(sel);
    if (el) el.addEventListener('input', atualizarConfronto);
  });

  setupConvenios();
  if (typeof setupGerencia === 'function') setupGerencia();
  if (typeof setupResponsaveis === 'function') setupResponsaveis();
  if (typeof setupRemessas === 'function') setupRemessas();
  if (typeof setupRemessasConvenios === 'function') setupRemessasConvenios();

  // Por último: define a fonte (API real ou store de demonstração) e o
  // que a tela permite fazer com ela.
  await iniciarFonteDeDados();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', setup);
} else {
  setup();
}
