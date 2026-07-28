'use strict';

/* ============================================================
   usuarios.js — Tela de Gestão de Usuários (módulo Segurança).

   Consome a Edge Function `gestao-usuarios` (protegida por x-sco-token,
   via scoChamarFuncaoAutenticada do auth.js). Regras de perfil:
     ADMIN            -> cria e edita usuário (cadastro completo)
     ADMIN | MASTER   -> trocam equipe/status e mantêm o CRUD de equipes
   As solicitações de acesso são SÓ LEITURA aqui: a aprovação acontece
   pelos links do e-mail (função autorizar-acesso).
   ============================================================ */

let USR_EQUIPES = [];
let USR_LISTA = [];
let usrEdicaoId = null; // null = criando usuário
let eqpEdicaoId = null; // null = criando equipe


function usrEhAdmin() {
  return scoPerfil() === 'ADMIN';
}

function usrEquipeNome(id) {
  const equipe = USR_EQUIPES.find((e) => e.id_equipe === id);
  return equipe ? equipe.nome : '';
}

function usrFmtData(valor) {
  if (!valor) return '';
  const data = new Date(valor);
  return Number.isNaN(data.getTime()) ? String(valor) : data.toLocaleString('pt-BR');
}


/* ---------------- Carregamento ---------------- */

async function usrCarregarEquipes() {
  const dados = await scoChamarFuncaoAutenticada('gestao-usuarios', {
    acao: 'listar_equipes',
  });
  USR_EQUIPES = dados.equipes || [];

  const sel = $('#usr-equipe');
  sel.innerHTML =
    '<option value="">(sem equipe)</option>' +
    USR_EQUIPES.map(
      (e) =>
        `<option value="${e.id_equipe}">${e.nome}${e.ativo ? '' : ' (inativa)'}</option>`,
    ).join('');

  renderGrid(
    $('#tbl-equipes'),
    [
      { label: 'Equipe', key: 'nome', left: true },
      { label: 'Situação', key: 'situacao' },
    ],
    USR_EQUIPES.map((e) => ({ ...e, situacao: e.ativo ? 'Ativa' : 'Inativa' })),
    usrSelecionarEquipe,
  );
}

async function usrCarregarUsuarios() {
  const dados = await scoChamarFuncaoAutenticada('gestao-usuarios', {
    acao: 'listar_usuarios',
  });
  USR_LISTA = dados.usuarios || [];
  usrRenderUsuarios();
}

function usrRenderUsuarios() {
  const termo = ($('#usr-busca').value || '').trim().toLowerCase();
  const linhas = USR_LISTA.filter(
    (u) =>
      !termo ||
      [u.nome, u.email, u.perfil].some((c) =>
        String(c || '').toLowerCase().includes(termo),
      ),
  ).map((u) => ({
    ...u,
    equipe_nome: usrEquipeNome(u.id_equipe) || '—',
    ultimo: usrFmtData(u.data_ultimo_acesso) || '—',
  }));

  renderGrid(
    $('#tbl-usuarios'),
    [
      { label: 'Nome', key: 'nome', left: true },
      { label: 'E-mail', key: 'email', left: true },
      { label: 'Perfil', key: 'perfil' },
      { label: 'Status', key: 'status' },
      { label: 'Equipe', key: 'equipe_nome' },
      { label: 'Último acesso', key: 'ultimo' },
    ],
    linhas,
    usrSelecionarUsuario,
  );
  $('#usr-resumo').textContent = `${linhas.length} usuário(s)`;
}

async function usrCarregarSolicitacoes() {
  const dados = await scoChamarFuncaoAutenticada('gestao-usuarios', {
    acao: 'listar_solicitacoes',
  });
  renderGrid(
    $('#tbl-solicitacoes'),
    [
      { label: 'Nome', key: 'nome', left: true },
      { label: 'E-mail', key: 'email', left: true },
      { label: 'Perfil pedido', key: 'perfil_solicitado' },
      { label: 'Situação', key: 'status' },
      { label: 'Solicitado em', key: 'solicitado' },
      { label: 'Respondido por', key: 'autorizador_email' },
    ],
    (dados.solicitacoes || []).map((s) => ({
      ...s,
      solicitado: usrFmtData(s.solicitado_em),
    })),
    null,
  );
}


/* ---------------- Formulário de usuário ---------------- */

// Ajusta quais campos ficam editáveis conforme o perfil e o modo:
// identidade/perfil só o ADMIN mexe; criar exige ADMIN.
function usrEstadoCampos(modo) {
  const admin = usrEhAdmin();
  ['usr-nome', 'usr-email', 'usr-perfil'].forEach(
    (id) => ($('#' + id).disabled = !admin),
  );
  const podeSalvar = modo === 'novo' ? admin : true;
  $('#btn-usr-salvar').disabled = !podeSalvar;
}

function usrLimparFormUsuario() {
  usrEdicaoId = null;
  $('#titulo-usr-form').textContent = 'Novo usuário';
  $('#usr-nome').value = '';
  $('#usr-email').value = '';
  $('#usr-perfil').value = 'OPERADOR';
  $('#usr-status').value = 'ATIVO';
  $('#usr-equipe').value = '';
  $('#usr-senha-provisoria').hidden = true;
  $('#btn-usr-salvar').textContent = 'Criar usuário';
  usrEstadoCampos('novo');
}

function usrSelecionarUsuario(rec) {
  usrEdicaoId = rec.id_usuario;
  $('#titulo-usr-form').textContent = `Editar: ${rec.nome}`;
  $('#usr-nome').value = rec.nome || '';
  $('#usr-email').value = rec.email || '';
  $('#usr-perfil').value = rec.perfil || 'OPERADOR';
  $('#usr-status').value = rec.status === 'SUSPENSO' ? 'SUSPENSO' : 'ATIVO';
  $('#usr-equipe').value = rec.id_equipe || '';
  $('#usr-senha-provisoria').hidden = true;
  $('#btn-usr-salvar').textContent = 'Salvar alterações';
  usrEstadoCampos('edicao');
}

async function usrCriarUsuario(nome, email, perfil, idEquipe) {
  if (!nome || !email) {
    msgInline('msg-usr', 'Informe nome e e-mail.', 'erro');
    return false;
  }
  const dados = await scoChamarFuncaoAutenticada('gestao-usuarios', {
    acao: 'criar_usuario',
    nome,
    email,
    perfil,
    id_equipe: idEquipe,
  });
  const box = $('#usr-senha-provisoria');
  box.hidden = false;
  box.innerHTML =
    'Usuário criado. Senha provisória (repasse ao usuário, aparece só agora): ' +
    `<b>${dados.senha_provisoria}</b>`;
  toast('Usuário criado.', 'ok');
  return true;
}

async function usrEditarComoAdmin(nome, email, perfil, status, idEquipe) {
  await scoChamarFuncaoAutenticada('gestao-usuarios', {
    acao: 'editar_usuario',
    id_usuario: usrEdicaoId,
    nome,
    email,
    perfil,
    status,
    id_equipe: idEquipe,
  });
  toast('Usuário atualizado.', 'ok');
}

// MASTER não edita identidade/perfil: só troca equipe e status.
async function usrEditarComoMaster(status, idEquipe) {
  await scoChamarFuncaoAutenticada('gestao-usuarios', {
    acao: 'alterar_equipe',
    id_usuario: usrEdicaoId,
    id_equipe: idEquipe,
  });
  await scoChamarFuncaoAutenticada('gestao-usuarios', {
    acao: 'alterar_status',
    id_usuario: usrEdicaoId,
    status,
  });
  toast('Equipe e status atualizados.', 'ok');
}

async function usrSalvarUsuario() {
  const nome = $('#usr-nome').value.trim();
  const email = $('#usr-email').value.trim();
  const perfil = $('#usr-perfil').value;
  const status = $('#usr-status').value;
  const idEquipe = $('#usr-equipe').value || null;

  try {
    if (!usrEdicaoId) {
      const criou = await usrCriarUsuario(nome, email, perfil, idEquipe);
      if (!criou) return;
    } else if (usrEhAdmin()) {
      await usrEditarComoAdmin(nome, email, perfil, status, idEquipe);
    } else {
      await usrEditarComoMaster(status, idEquipe);
    }
    await usrCarregarUsuarios();
    if (usrEdicaoId) usrLimparFormUsuario();
  } catch (erro) {
    msgInline('msg-usr', erro.message, 'erro');
  }
}


/* ---------------- Formulário de equipe ---------------- */

function usrLimparFormEquipe() {
  eqpEdicaoId = null;
  $('#eqp-nome').value = '';
  $('#eqp-ativo').checked = true;
  $('#eqp-ativo-campo').hidden = true;
  $('#btn-eqp-salvar').textContent = 'Criar equipe';
}

function usrSelecionarEquipe(rec) {
  eqpEdicaoId = rec.id_equipe;
  $('#eqp-nome').value = rec.nome || '';
  $('#eqp-ativo').checked = Boolean(rec.ativo);
  $('#eqp-ativo-campo').hidden = false;
  $('#btn-eqp-salvar').textContent = 'Salvar equipe';
}

async function usrSalvarEquipe() {
  const nome = $('#eqp-nome').value.trim();
  if (!nome) {
    msgInline('msg-eqp', 'Informe o nome da equipe.', 'erro');
    return;
  }
  try {
    if (!eqpEdicaoId) {
      await scoChamarFuncaoAutenticada('gestao-usuarios', {
        acao: 'criar_equipe',
        nome,
      });
      toast('Equipe criada.', 'ok');
    } else {
      await scoChamarFuncaoAutenticada('gestao-usuarios', {
        acao: 'editar_equipe',
        id_equipe: eqpEdicaoId,
        nome,
        ativo: $('#eqp-ativo').checked,
      });
      toast('Equipe atualizada.', 'ok');
    }
    await usrCarregarEquipes();
    usrRenderUsuarios();
    usrLimparFormEquipe();
  } catch (erro) {
    msgInline('msg-eqp', erro.message, 'erro');
  }
}


/* ---------------- Entrada na página / setup ---------------- */

async function aoEntrarNaGestaoUsuarios() {
  const aviso = $('#usuarios-aviso');
  if (!scoAuthConfigurado()) {
    aviso.hidden = false;
    aviso.textContent =
      'Gestão de usuários exige o Supabase configurado — o modo demonstração não tem backend de contas.';
    return;
  }
  if (!scoAcessoTotal()) {
    aviso.hidden = false;
    aviso.textContent = 'Acesso restrito a ADMIN e MASTER.';
    return;
  }
  aviso.hidden = true;

  try {
    await usrCarregarEquipes();
    await Promise.all([usrCarregarUsuarios(), usrCarregarSolicitacoes()]);
  } catch (erro) {
    toast(erro.message, 'erro');
  }
  usrLimparFormUsuario();
  usrLimparFormEquipe();
}

function usrSetup() {
  if (!$('#page-usuarios')) return;
  $('#usr-busca').addEventListener('input', usrRenderUsuarios);
  $('#btn-usr-salvar').addEventListener('click', usrSalvarUsuario);
  $('#btn-usr-novo').addEventListener('click', usrLimparFormUsuario);
  $('#btn-eqp-salvar').addEventListener('click', usrSalvarEquipe);
  $('#btn-eqp-novo').addEventListener('click', usrLimparFormEquipe);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', usrSetup);
} else {
  usrSetup();
}
