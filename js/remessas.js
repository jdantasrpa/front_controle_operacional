'use strict';

/* ============================================================
   remessas.js — Aba "Remessas" do detalhe do convênio (Gerência).

   Acompanha o envio de cada vencimento da competência: situação
   (pendente/enviada), data de envio, usuário e observação, com auditoria.
   A REGRA de envio (dias antes, SLA, corte) vem do Controle e é só
   exibida aqui — o que se registra é o histórico de envio.
   ============================================================ */

let remVinculo = null;   // {originador, numero_convenio} do detalhe
let remLinhas = [];

function _brMoeda(valor) {
  return (Number(valor) || 0).toLocaleString('pt-BR', {
    style: 'currency', currency: 'BRL',
  });
}

// Resumo textual da regra de envio, lida do controle do convênio (a linha
// da gerência já traz os offsets).
function _resumoRegra(linha) {
  const partes = [];
  if (linha.dias_antes_remessa !== '') {
    partes.push(`remessa D-${linha.dias_antes_remessa}`);
  }
  if (linha.qtd_dias_sla_pagamento !== '') {
    partes.push(`SLA ${linha.qtd_dias_sla_pagamento}d`);
  }
  if (linha.dias_antes_corte !== '') {
    partes.push(`corte D-${linha.dias_antes_corte}`);
  }
  return partes.length ? partes.join(' · ') : 'sem regra definida no Controle';
}

async function preencherAbaRemessas(linha) {
  remVinculo = {
    originador: linha.originador,
    numero_convenio: linha.numero_convenio,
  };
  $('#grd-rem-regra').textContent = _resumoRegra(linha);
  $('#grd-rem-competencia').value = competenciaRefGerencia();
  msgInline('msg-grd-remessa', '');
  await carregarRemessas();
}

async function carregarRemessas() {
  if (!remVinculo) return;
  if (exigirApi('msg-grd-remessa')) {
    renderRemessas([]);
    return;
  }
  try {
    remLinhas = await apiListarRemessas(
      remVinculo.originador,
      remVinculo.numero_convenio,
      $('#grd-rem-competencia').value || competenciaRefGerencia(),
    );
  } catch (erro) {
    msgInline('msg-grd-remessa', erro.message, 'erro');
    remLinhas = [];
  }
  renderRemessas(remLinhas);
}

function renderRemessas(linhas) {
  const thead = $('#tbl-grd-remessas thead');
  const tbody = $('#tbl-grd-remessas tbody');
  const titulos = [
    'Vencimento', 'Valor remessa', 'Situação', 'Data envio', 'Usuário',
    'Observação', '',
  ];
  thead.innerHTML =
    '<tr>' + titulos.map((t) => `<th>${t}</th>`).join('') + '</tr>';
  tbody.innerHTML = '';

  if (!linhas.length) {
    tbody.innerHTML =
      '<tr><td class="cell-empty" colspan="7">Nenhum vencimento na '
      + 'competência (gere a competência antes).</td></tr>';
    return;
  }
  linhas.forEach((linha) => tbody.appendChild(_linhaRemessa(linha)));
}

function _linhaRemessa(linha) {
  const tr = document.createElement('tr');
  if (linha.situacao === 'ENVIADA') tr.classList.add('linha-ok');

  _celTexto(tr, linha.data_vencimento);
  _celTexto(tr, _brMoeda(linha.valor_remessa));
  const situacao = _celSelect(tr, ['PENDENTE', 'ENVIADA'], linha.situacao);
  const envio = _celInput(tr, 'date', linha.data_envio);
  _celTexto(tr, linha.usuario || '—');
  const obs = _celInput(tr, 'text', linha.observacao);
  _celBotao(tr, () => salvarRemessa(linha, situacao, envio, obs));

  return tr;
}

function _celTexto(tr, valor) {
  const td = document.createElement('td');
  td.textContent = valor || '—';
  tr.appendChild(td);
}

function _celSelect(tr, opcoes, valor) {
  const td = document.createElement('td');
  const sel = document.createElement('select');
  opcoes.forEach((o) => {
    const opt = document.createElement('option');
    opt.value = o;
    opt.textContent = o;
    sel.appendChild(opt);
  });
  sel.value = valor;
  td.appendChild(sel);
  tr.appendChild(td);
  return sel;
}

function _celInput(tr, tipo, valor) {
  const td = document.createElement('td');
  const inp = document.createElement('input');
  inp.type = tipo;
  inp.value = valor || '';
  td.appendChild(inp);
  tr.appendChild(td);
  return inp;
}

function _celBotao(tr, aoClicar) {
  const td = document.createElement('td');
  const btn = document.createElement('button');
  btn.className = 'btn btn-secondary btn-sm';
  btn.textContent = 'Salvar';
  btn.addEventListener('click', aoClicar);
  td.appendChild(btn);
  tr.appendChild(td);
}

async function salvarRemessa(linha, situacao, envio, obs) {
  if (exigirApi('msg-grd-remessa') || !remVinculo) return;
  try {
    await apiRegistrarRemessa(
      remVinculo.originador, remVinculo.numero_convenio,
      {
        competencia: $('#grd-rem-competencia').value || competenciaRefGerencia(),
        data_vencimento: linha.data_vencimento,
        situacao: situacao.value,
        data_envio: envio.value,
        observacao: obs.value.trim(),
      },
    );
    toast(`Remessa de ${linha.data_vencimento} salva.`, 'ok');
    await carregarRemessas();
  } catch (erro) {
    msgInline('msg-grd-remessa', erro.message, 'erro');
  }
}

function setupRemessas() {
  $('#btn-grd-rem-atualizar').addEventListener('click', carregarRemessas);
}
