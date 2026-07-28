'use strict';

/* ============================================================
   remessa_convenios.js — Submódulo "Remessas" (dentro de Conciliação).

   Lista por convênio (um por linha). A REMESSA é MENSAL e o histórico é
   IMUTÁVEL: cada mês guarda o snapshot de como a remessa foi enviada —
   corte, modo de envio, modelo de averbação, acesso, status da importação,
   status do envio e OBS. É o LASTRO do envio. O snapshot é replicado do
   mês anterior e só o mês corrente é editável.

   Identidade e regra do convênio (originador, nome, CNPJ, status, status de
   produção, gestora e URL) moram no convênio — editadas na Gestão de
   Convênios — e aqui aparecem em somente leitura.

   Demo: opera sobre o STORE local. A gravação real (API) fica para a etapa
   de escrita do painel, como nos demais submódulos.
   ============================================================ */

let remConvNumero = null;   // numero_convenio do convênio em edição

const COLS_REMESSA = [
  { key: 'id', label: 'ID' },
  { key: 'originador', label: 'Originador', left: true },
  { key: 'nome_convenio', label: 'Nome do Convênio', left: true },
  { key: 'status', label: 'Status', flag: true },
  { key: 'status_producao', label: 'Status de produção', flag: true },
  { key: 'cnpj_convenio', label: 'CNPJ' },
  { key: 'gestora_margem', label: 'Gestora de Margem', left: true },
  { key: 'link_gestora', label: 'URL', trunc: true },
  { key: 'modelo_averbacao', label: 'Modelo de Averbação', flag: true },
  { key: 'data_corte', label: 'Data Corte' },
  { key: 'acesso', label: 'Acesso', flag: true },
  { key: 'status_importacao', label: 'Status da Importação', flag: true },
  { key: 'modo_envio', label: 'Modo de envio', flag: true },
  { key: 'obs', label: 'OBS.', left: true, wrap: true },
];

// Histórico mensal (lastro) — colunas do painel de meses.
const COLS_REM_ENVIO = [
  { key: 'mes_br', label: 'Mês' },
  { key: 'corte', label: 'Corte' },
  { key: 'modo_envio', label: 'Modo de envio', flag: true },
  { key: 'modelo_averbacao', label: 'Modelo', flag: true },
  { key: 'status_importacao', label: 'Importação', flag: true },
  { key: 'status_envio', label: 'Envio', flag: true },
  { key: 'trava', label: '' },
];

// =====================================================================
// Regras puras de mês
// =====================================================================
function mesAtual() {
  return new Date().toISOString().slice(0, 7);
}

function mesParaBr(mes) {
  const partes = String(mes || '').split('-');
  return partes.length === 2 ? `${partes[1]}/${partes[0]}` : mes;
}

function diasDoMes() {
  return ['', ...Array.from({ length: 31 }, (_, i) => String(i + 1))];
}

// Meses passados são histórico imutável; só o mês corrente é editável.
function ehMesHistorico(mes) {
  return Boolean(mes) && mes < mesAtual();
}

// Snapshot do mês corrente; na falta, o do mês mais recente registrado.
function mesVigente(remessa) {
  const meses = remessa.meses || {};
  if (meses[mesAtual()]) return meses[mesAtual()];
  const chaves = Object.keys(meses).sort();
  return chaves.length ? meses[chaves[chaves.length - 1]] : {};
}

// Snapshot a replicar num mês novo: cópia do mês registrado imediatamente
// anterior (sem o carimbo de atualização). Vazio quando não há anterior.
function snapshotAnterior(meses, mesAlvo) {
  const anteriores = Object.keys(meses || {})
    .filter((m) => m < mesAlvo)
    .sort();
  const ultima = anteriores[anteriores.length - 1];
  if (!ultima) return {};
  const { atualizado_em, ...resto } = meses[ultima];
  return { ...resto };
}

function _joinModelo(valor) {
  return Array.isArray(valor) ? valor.join(', ') : valor || '';
}

// =====================================================================
// Chips genéricos de múltipla escolha (flag on/off) — modelo de averbação
// e modo de envio usam a mesma lógica.
// =====================================================================
function renderChips(contId, opcoes, selecionados, bloqueado = false) {
  const marcados = Array.isArray(selecionados)
    ? selecionados
    : selecionados
      ? [selecionados]
      : [];
  const cont = $('#' + contId);
  cont.innerHTML = '';
  cont.classList.toggle('is-locked', bloqueado);
  opcoes.forEach((opcao) => {
    const chip = document.createElement('span');
    chip.className = 'chip-toggle' + (marcados.includes(opcao) ? ' is-on' : '');
    chip.textContent = opcao;
    chip.dataset.valor = opcao;
    if (!bloqueado) {
      chip.addEventListener('click', () => chip.classList.toggle('is-on'));
    }
    cont.appendChild(chip);
  });
}

function lerChips(contId) {
  return [...$$('#' + contId + ' .chip-toggle.is-on')].map(
    (chip) => chip.dataset.valor,
  );
}

// =====================================================================
// Lista por convênio
// =====================================================================
function linhaRemessa(conv) {
  const vig = mesVigente(conv.remessa || {});
  return {
    id: conv.id ?? '',
    originador: conv.originador || '',
    nome_convenio: conv.nome_convenio || '',
    status: conv.status || 'Ativo',
    status_producao: conv.status_producao || '—',
    cnpj_convenio: conv.cnpj_convenio || '',
    gestora_margem: conv.gestora_margem || '',
    link_gestora: conv.link_gestora || '',
    modelo_averbacao: _joinModelo(vig.modelo_averbacao),
    data_corte: vig.corte || '',
    acesso: vig.acesso || '',
    status_importacao: vig.status_importacao || '',
    modo_envio: _joinModelo(vig.modo_envio),
    obs: vig.obs || '',
    _numero: conv.numero_convenio,
  };
}

function filtrarPorBusca(linhas, termo) {
  const t = (termo || '').toLowerCase();
  if (!t) return linhas;
  return linhas.filter((l) => [
    l.originador, l.nome_convenio, l.cnpj_convenio, l.gestora_margem,
  ].join(' ').toLowerCase().includes(t));
}

function _distintos(linhas, chave) {
  return [...new Set(linhas.map((l) => l[chave]).filter(Boolean))].sort();
}

// Repovoa um select de filtro preservando a escolha se ainda válida.
function _repovoarFiltro(sel, opcoes, rotuloTodos) {
  const atual = sel.value;
  preencherSelect(
    sel,
    [{ value: '', label: rotuloTodos }, ...opcoes],
    opcoes.includes(atual) ? atual : '',
  );
}

// Filtros ENCADEADOS: originadora limita gestoras, que limitam status e corte.
function carregarRemessasConvenios() {
  const base = STORE.todosConvenios().map(linhaRemessa);

  const selOrig = $('#rem-f-originadora');
  const selGest = $('#rem-f-gestora');
  const selStat = $('#rem-f-status');
  const selCorte = $('#rem-f-corte');

  _repovoarFiltro(selOrig, _distintos(base, 'originador'), 'Todas');
  const porOrig = base.filter(
    (l) => !selOrig.value || l.originador === selOrig.value,
  );

  _repovoarFiltro(selGest, _distintos(porOrig, 'gestora_margem'), 'Todas');
  const porGest = porOrig.filter(
    (l) => !selGest.value || l.gestora_margem === selGest.value,
  );

  _repovoarFiltro(selStat, _distintos(porGest, 'status'), 'Todos');
  const porStat = porGest.filter(
    (l) => !selStat.value || l.status === selStat.value,
  );

  _repovoarFiltro(selCorte, _distintos(porStat, 'data_corte'), 'Todas');
  const porCorte = porStat.filter(
    (l) => !selCorte.value || l.data_corte === selCorte.value,
  );

  const visiveis = filtrarPorBusca(porCorte, $('#rem-busca').value);
  $('#rem-resumo').textContent = `${visiveis.length} convênio(s)`;
  renderGrid($('#tbl-remessas'), COLS_REMESSA, visiveis, (linha) =>
    abrirFormRemessa(linha._numero));
}

// =====================================================================
// Editor mensal (lastro)
// =====================================================================
function abrirFormRemessa(numeroConvenio) {
  const conv = STORE.acharConvenio(numeroConvenio);
  if (!conv) return;
  remConvNumero = numeroConvenio;

  // Identidade / regra do convênio (somente leitura).
  $$('#card-rem-form [data-rid]').forEach((el) => {
    el.value = conv[el.dataset.rid] ?? '';
  });

  $('#titulo-rem-form').textContent =
    `Remessa · ${conv.nome_convenio} (${conv.originador})`;
  $('#rem-envio-mes').value = mesAtual();
  carregarMesEnvio(conv);
  renderEnviosMensais(conv);
  $('#card-rem-form').hidden = false;
  msgInline('msg-remessas', '');
}

// Carrega o snapshot do mês escolhido: registro existente ou, se for mês
// novo, replicado do mês anterior. Histórico entra em somente leitura.
function carregarMesEnvio(conv) {
  const mes = $('#rem-envio-mes').value;
  const meses = conv.remessa.meses || {};
  const base = meses[mes] || snapshotAnterior(meses, mes);
  const historico = ehMesHistorico(mes);

  preencherSelect($('#rem-envio-corte'), diasDoMes(), base.corte || '');
  preencherSelect(
    $('#rem-acesso'), ['', ...ACESSO_REMESSA_OPCOES], base.acesso || '',
  );
  preencherSelect(
    $('#rem-status-importacao'), ['', ...STATUS_IMPORTACAO_REMESSA_OPCOES],
    base.status_importacao || '',
  );
  preencherSelect(
    $('#rem-envio-status'), ['', ...STATUS_ENVIO_MENSAL_OPCOES],
    base.status_envio || '',
  );
  $('[data-fm="obs"]', $('#card-rem-form')).value = base.obs || '';
  renderChips(
    'rem-modo-envio', MODO_ENVIO_REMESSA_OPCOES, base.modo_envio, historico,
  );
  renderChips(
    'rem-modelo-averbacao', MODELO_AVERBACAO_REMESSA_OPCOES,
    base.modelo_averbacao, historico,
  );

  $$('#card-rem-form [data-fm]').forEach((el) => {
    el.disabled = historico;
  });
  $('#btn-salvar-envio-mes').disabled = historico;

  const aviso = $('#rem-envio-aviso');
  aviso.hidden = !historico;
  aviso.textContent = historico
    ? 'Mês do histórico — somente leitura (lastro). Apenas o mês corrente '
      + 'pode ser alterado.'
    : '';
}

// Histórico dos meses (mais recente primeiro); clicar carrega o mês.
function renderEnviosMensais(conv) {
  const meses = conv.remessa.meses || {};
  const linhas = Object.keys(meses)
    .sort((a, b) => b.localeCompare(a))
    .map((mes) => ({
      mes,
      mes_br: mesParaBr(mes),
      corte: meses[mes].corte || '',
      modo_envio: _joinModelo(meses[mes].modo_envio),
      modelo_averbacao: _joinModelo(meses[mes].modelo_averbacao),
      status_importacao: meses[mes].status_importacao || '',
      status_envio: meses[mes].status_envio || '',
      trava: ehMesHistorico(mes) ? '🔒' : '✎',
    }));

  renderGrid($('#tbl-rem-envios'), COLS_REM_ENVIO, linhas, (linha) => {
    $('#rem-envio-mes').value = linha.mes;
    carregarMesEnvio(conv);
  });
}

// Grava o snapshot do mês. Bloqueia o histórico: só o mês corrente muda.
function salvarMesRemessa() {
  if (bloqueadoParaEscrita('msg-remessas') || !remConvNumero) return;
  const conv = STORE.acharConvenio(remConvNumero);
  if (!conv) return;

  const mes = $('#rem-envio-mes').value;
  if (!mes) {
    msgInline('msg-remessas', 'Informe o mês.', 'erro');
    return;
  }
  if (ehMesHistorico(mes)) {
    msgInline(
      'msg-remessas', 'Mês do histórico não pode ser alterado.', 'erro',
    );
    return;
  }

  const registro = {
    modelo_averbacao: lerChips('rem-modelo-averbacao'),
    modo_envio: lerChips('rem-modo-envio'),
  };
  $$('#card-rem-form [data-fm]').forEach((el) => {
    registro[el.dataset.fm] =
      typeof el.value === 'string' ? el.value.trim() : el.value;
  });
  registro.atualizado_em = STORE.agora();

  conv.remessa.meses = { ...conv.remessa.meses, [mes]: registro };
  STORE.salvar();
  renderEnviosMensais(conv);
  carregarRemessasConvenios();
  msgInline('msg-remessas', `Mês ${mesParaBr(mes)} salvo (lastro).`);
  toast('Remessa do mês salva.', 'ok');
}

// Abre a URL da gestora (regra do convênio); só http(s).
function acessarUrlGestora() {
  const url = $('#rem-url').value.trim();
  if (!url) {
    msgInline('msg-remessas', 'Nenhuma URL cadastrada.', 'erro');
    return;
  }
  if (!/^https?:\/\//i.test(url)) {
    msgInline(
      'msg-remessas', 'A URL deve começar com http:// ou https://.', 'erro',
    );
    return;
  }
  window.open(url, '_blank', 'noopener');
}

function aoEntrarNasRemessas() {
  $('#card-rem-form').hidden = true;
  remConvNumero = null;
  carregarRemessasConvenios();
}

function setupRemessasConvenios() {
  $('#rem-busca').addEventListener('input', carregarRemessasConvenios);
  ['#rem-f-originadora', '#rem-f-gestora', '#rem-f-status', '#rem-f-corte']
    .forEach((sel) => {
      $(sel).addEventListener('change', carregarRemessasConvenios);
    });
  $('#btn-salvar-envio-mes').addEventListener('click', salvarMesRemessa);
  $('#btn-acessar-url-gestora').addEventListener('click', acessarUrlGestora);
  // Trocar o mês recarrega o snapshot (replicado do anterior em mês novo).
  $('#rem-envio-mes').addEventListener('change', () => {
    const conv = STORE.acharConvenio(remConvNumero);
    if (conv) carregarMesEnvio(conv);
  });
}
