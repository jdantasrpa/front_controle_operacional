'use strict';

/* ============================================================
   usuarios.js — Gestão de Usuários por acesso DIRETO ao banco
   (public.usuario_perfil), sem Edge Functions. Só ADMIN (a RLS de
   usuario_perfil só deixa ADMIN gravar).

   O ADMIN aqui: aprova/revoga o acesso (aprovado) e define o perfil de
   cada usuário. Contas nascem no Supabase Auth (Criar cadastro / dashboard);
   a senha é sempre do próprio usuário (nunca passa por aqui).
   ============================================================ */

let USRP_LISTA = [];
let USRP_EQUIPES = [];
let usrpSelecionado = null; // id (uuid) do usuario_perfil em edição
let usrpEqpSel = null; // id_equipe em edição

function _dbUsr() {
  const cli = typeof scoCliente === 'function' ? scoCliente() : null;
  if (!cli) throw new Error('Faça login para gerenciar usuários.');
  return cli;
}

function _ligarU(id, evento, fn) {
  const el = $('#' + id);
  if (el) el.addEventListener(evento, fn);
}


/* ---------------- Carregamento ---------------- */

async function usrpCarregarEquipes() {
  const { data, error } = await _dbUsr()
    .from('tb_equipe')
    .select('id_equipe, nome, ativo')
    .order('nome');
  if (error) throw new Error(error.message);
  USRP_EQUIPES = data || [];

  const sel = $('#usr-equipe');
  if (sel) {
    sel.innerHTML =
      '<option value="">(sem equipe)</option>' +
      USRP_EQUIPES.map(
        (e) => `<option value="${e.id_equipe}">${e.nome}${e.ativo ? '' : ' (inativa)'}</option>`,
      ).join('');
  }

  renderGrid(
    $('#tbl-equipes'),
    [
      { label: 'Equipe', key: 'nome', left: true },
      { label: 'Situação', key: 'situacao' },
    ],
    USRP_EQUIPES.map((e) => ({ ...e, situacao: e.ativo ? 'Ativa' : 'Inativa' })),
    usrpSelecionarEquipe,
  );
}

async function usrpCarregarUsuarios() {
  const { data, error } = await _dbUsr()
    .from('usuario_perfil')
    .select('id, email, nome, perfil, aprovado, ativo, id_equipe')
    .order('aprovado', { ascending: true }) // pendentes primeiro
    .order('nome');
  if (error) throw new Error(error.message);
  USRP_LISTA = data || [];
  usrpRender();
}

function usrpEquipeNome(id) {
  const e = USRP_EQUIPES.find((x) => x.id_equipe === id);
  return e ? e.nome : '';
}

function usrpRender() {
  const termo = ($('#usr-busca').value || '').trim().toLowerCase();
  const linhas = USRP_LISTA.filter(
    (u) =>
      !termo ||
      [u.nome, u.email, u.perfil].some((c) =>
        String(c || '').toLowerCase().includes(termo),
      ),
  ).map((u) => ({
    ...u,
    situacao: u.aprovado ? 'Ativo' : 'Pendente',
    equipe_nome: usrpEquipeNome(u.id_equipe) || '—',
  }));

  renderGrid(
    $('#tbl-usuarios'),
    [
      { label: 'Nome', key: 'nome', left: true },
      { label: 'E-mail', key: 'email', left: true },
      { label: 'Perfil', key: 'perfil' },
      { label: 'Situação', key: 'situacao' },
      { label: 'Equipe', key: 'equipe_nome' },
    ],
    linhas,
    usrpSelecionarUsuario,
  );

  const pendentes = USRP_LISTA.filter((u) => !u.aprovado).length;
  $('#usr-resumo').textContent =
    `${linhas.length} usuário(s)` + (pendentes ? ` · ${pendentes} pendente(s)` : '');
}


/* ---------------- Edição do usuário ---------------- */

function usrpSelecionarUsuario(rec) {
  usrpSelecionado = rec.id;
  $('#titulo-usr-form').textContent = `Editar: ${rec.nome}`;
  $('#usr-nome').value = rec.nome || '';
  $('#usr-email').value = rec.email || '';
  $('#usr-perfil').value = rec.perfil || 'LEITOR';
  $('#usr-equipe').value = rec.id_equipe || '';

  const btnAcesso = $('#btn-usr-acesso');
  btnAcesso.hidden = false;
  btnAcesso.textContent = rec.aprovado ? 'Revogar acesso' : 'Aprovar acesso';
  btnAcesso.dataset.aprovar = rec.aprovado ? '0' : '1';
}

function usrpLimparEdicao() {
  usrpSelecionado = null;
  $('#titulo-usr-form').textContent = 'Selecione um usuário na lista';
  $('#usr-nome').value = '';
  $('#usr-email').value = '';
  $('#usr-perfil').value = 'LEITOR';
  $('#usr-equipe').value = '';
  const btnAcesso = $('#btn-usr-acesso');
  if (btnAcesso) btnAcesso.hidden = true;
}

async function usrpSalvar() {
  if (!usrpSelecionado) {
    msgInline('msg-usr', 'Selecione um usuário na lista.', 'erro');
    return;
  }
  try {
    const { error } = await _dbUsr()
      .from('usuario_perfil')
      .update({
        nome: $('#usr-nome').value.trim(),
        perfil: $('#usr-perfil').value,
        id_equipe: $('#usr-equipe').value || null,
      })
      .eq('id', usrpSelecionado);
    if (error) throw new Error(error.message);
    toast('Perfil atualizado.', 'ok');
    await usrpCarregarUsuarios();
  } catch (erro) {
    msgInline('msg-usr', erro.message, 'erro');
  }
}

async function usrpAlternarAcesso() {
  if (!usrpSelecionado) return;
  const aprovar = $('#btn-usr-acesso').dataset.aprovar === '1';
  try {
    const { error } = await _dbUsr()
      .from('usuario_perfil')
      .update({ aprovado: aprovar })
      .eq('id', usrpSelecionado);
    if (error) throw new Error(error.message);
    toast(aprovar ? 'Acesso aprovado.' : 'Acesso revogado.', 'ok');
    await usrpCarregarUsuarios();
    usrpLimparEdicao();
  } catch (erro) {
    msgInline('msg-usr', erro.message, 'erro');
  }
}


/* ---------------- Equipes ---------------- */

function usrpSelecionarEquipe(rec) {
  usrpEqpSel = rec.id_equipe;
  $('#eqp-nome').value = rec.nome || '';
  $('#eqp-ativo').checked = Boolean(rec.ativo);
  $('#eqp-ativo-campo').hidden = false;
  $('#btn-eqp-salvar').textContent = 'Salvar equipe';
}

function usrpLimparEquipe() {
  usrpEqpSel = null;
  $('#eqp-nome').value = '';
  $('#eqp-ativo').checked = true;
  $('#eqp-ativo-campo').hidden = true;
  $('#btn-eqp-salvar').textContent = 'Criar equipe';
}

async function usrpSalvarEquipe() {
  const nome = $('#eqp-nome').value.trim();
  if (!nome) {
    msgInline('msg-eqp', 'Informe o nome da equipe.', 'erro');
    return;
  }
  try {
    if (!usrpEqpSel) {
      const { error } = await _dbUsr().from('tb_equipe').insert({ nome });
      if (error) throw new Error(error.message);
      toast('Equipe criada.', 'ok');
    } else {
      const { error } = await _dbUsr()
        .from('tb_equipe')
        .update({ nome, ativo: $('#eqp-ativo').checked })
        .eq('id_equipe', usrpEqpSel);
      if (error) throw new Error(error.message);
      toast('Equipe atualizada.', 'ok');
    }
    await usrpCarregarEquipes();
    usrpRender();
    usrpLimparEquipe();
  } catch (erro) {
    msgInline('msg-eqp', erro.message, 'erro');
  }
}


/* ---------------- Entrada na página / setup ---------------- */

async function aoEntrarNaGestaoUsuarios() {
  const aviso = $('#usuarios-aviso');
  if (!scoAuthConfigurado()) {
    aviso.hidden = false;
    aviso.textContent = 'Gestão de usuários exige o Supabase configurado.';
    return;
  }
  if (scoPerfil() !== 'ADMIN') {
    aviso.hidden = false;
    aviso.textContent = 'Acesso restrito ao ADMIN.';
    return;
  }
  aviso.hidden = true;
  try {
    await usrpCarregarEquipes();
    await usrpCarregarUsuarios();
  } catch (erro) {
    toast(erro.message, 'erro');
  }
  usrpLimparEdicao();
  usrpLimparEquipe();
}

function usrpSetup() {
  if (!$('#page-usuarios')) return;
  _ligarU('usr-busca', 'input', usrpRender);
  _ligarU('btn-usr-salvar', 'click', usrpSalvar);
  _ligarU('btn-usr-acesso', 'click', usrpAlternarAcesso);
  _ligarU('btn-usr-novo', 'click', usrpLimparEdicao);
  _ligarU('btn-eqp-salvar', 'click', usrpSalvarEquipe);
  _ligarU('btn-eqp-novo', 'click', usrpLimparEquipe);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', usrpSetup);
} else {
  usrpSetup();
}
