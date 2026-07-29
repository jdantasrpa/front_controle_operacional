'use strict';

/* ============================================================
   auth.js — Autenticação NATIVA do Supabase (Supabase Auth), sem Edge
   Functions. O login usa supabase.auth; o perfil (ADMIN/MASTER/…) vem da
   tabela public.usuario_perfil. A sessão é mantida pelo próprio cliente
   supabase-js (localStorage) e renovada sozinha.

   Sem Supabase configurado (config.js vazio), o painel abre em modo
   demonstração, sem gate.
   ============================================================ */

let scoDB = null; // cliente supabase-js (singleton)
// { usuario: {id, email, nome, perfil, id_equipe, ativo}, token }
let scoSessaoAtual = null;

// Inicializa (uma vez) o cliente a partir do config público.
function scoCliente() {
  if (scoDB) return scoDB;
  if (!scoAuthConfigurado() || !window.supabase) return null;
  scoDB = window.supabase.createClient(
    SCO_CONFIG.SUPABASE_URL,
    SCO_CONFIG.SUPABASE_ANON_KEY,
  );
  return scoDB;
}

function scoSessao() {
  return scoSessaoAtual;
}

function scoLogado() {
  return Boolean(scoSessaoAtual);
}

function scoPerfil() {
  return scoSessaoAtual && scoSessaoAtual.usuario && scoSessaoAtual.usuario.perfil
    ? String(scoSessaoAtual.usuario.perfil).toUpperCase()
    : '';
}

function scoAcessoTotal() {
  return ['ADMIN', 'MASTER'].includes(scoPerfil());
}

// Lê o perfil do usuário logado (nome, perfil, equipe) na tabela própria.
async function scoCarregarPerfil(user) {
  let perfil = 'LEITOR';
  let nome = user.email;
  let idEquipe = null;
  let ativo = true;
  try {
    const { data } = await scoDB
      .from('usuario_perfil')
      .select('nome, perfil, id_equipe, ativo')
      .eq('id', user.id)
      .maybeSingle();
    if (data) {
      perfil = data.perfil || perfil;
      nome = data.nome || nome;
      idEquipe = data.id_equipe;
      ativo = data.ativo;
    }
  } catch (_) {
    /* perfil ainda não criado: mantém o padrão LEITOR */
  }
  return { id: user.id, email: user.email, nome, perfil, id_equipe: idEquipe, ativo };
}

// Sincroniza scoSessaoAtual com a sessão do supabase-js e aplica na tela.
async function scoSincronizarSessao(sessionConhecida) {
  const cli = scoCliente();
  if (!cli) {
    scoAplicarSessao();
    return;
  }
  let session = sessionConhecida;
  if (session === undefined) {
    const { data } = await cli.auth.getSession();
    session = data.session;
  }
  scoSessaoAtual = session && session.user
    ? { usuario: await scoCarregarPerfil(session.user), token: session.access_token }
    : null;
  scoAplicarSessao();
}

function scoAplicarSessao() {
  const tela = $('#tela-login');
  if (!tela) return;

  // Sem Supabase configurado: modo demonstração, sem gate.
  if (!scoAuthConfigurado()) {
    tela.hidden = true;
    return;
  }

  const logado = scoLogado();
  tela.hidden = logado;

  const barra = $('#sco-usuario-barra');
  if (barra) {
    barra.hidden = !logado;
    if (logado) {
      barra.querySelector('#sco-usuario-nome').textContent =
        `${scoSessaoAtual.usuario.nome} · ${scoSessaoAtual.usuario.perfil}`;
    }
  }

  // Botão "Usuários" (topbar) só para quem tem acesso total (ADMIN/MASTER).
  const btnAdmin = $('#btn-sco-admin');
  if (btnAdmin) btnAdmin.hidden = !(logado && scoAcessoTotal());
}

async function scoLogin() {
  const email = $('#sco-email').value.trim();
  const senha = $('#sco-senha').value;
  if (!email || !senha) {
    msgInline('msg-sco-login', 'Informe e-mail e senha.', 'erro');
    return;
  }
  const cli = scoCliente();
  if (!cli) {
    msgInline('msg-sco-login', 'Supabase não configurado.', 'erro');
    return;
  }
  try {
    const { data, error } = await cli.auth.signInWithPassword({
      email,
      password: senha,
    });
    if (error) {
      msgInline('msg-sco-login', error.message || 'Credenciais inválidas.', 'erro');
      return;
    }
    $('#sco-senha').value = '';
    await scoSincronizarSessao(data.session);
    toast(`Bem-vindo, ${scoSessaoAtual.usuario.nome}.`, 'ok');
  } catch (erro) {
    msgInline('msg-sco-login', erro.message, 'erro');
  }
}

async function scoLogout() {
  const cli = scoCliente();
  if (cli) {
    try {
      await cli.auth.signOut();
    } catch (_) {
      /* segue: limpa a sessão local de qualquer forma */
    }
  }
  scoSessaoAtual = null;
  scoAplicarSessao();
}

// Cadastro nativo (signUp). O perfil nasce LEITOR (trigger no banco); um
// admin promove depois — o próprio usuário nunca escolhe o nível de acesso.
async function scoSolicitar() {
  const nome = $('#sco-sol-nome').value.trim();
  const email = $('#sco-sol-email').value.trim();
  const senha = $('#sco-sol-senha').value;
  if (!nome || !email || !senha) {
    msgInline('msg-sco-solicitar', 'Informe nome, e-mail e senha.', 'erro');
    return;
  }
  const cli = scoCliente();
  if (!cli) {
    msgInline('msg-sco-solicitar', 'Supabase não configurado.', 'erro');
    return;
  }
  try {
    const { data, error } = await cli.auth.signUp({
      email,
      password: senha,
      options: { data: { nome } },
    });
    if (error) {
      msgInline('msg-sco-solicitar', error.message, 'erro');
      return;
    }
    if (data.session) {
      await scoSincronizarSessao(data.session);
      toast('Cadastro criado. Bem-vindo!', 'ok');
    } else {
      msgInline(
        'msg-sco-solicitar',
        'Cadastro criado. Confirme o e-mail e faça login.',
      );
      toast('Cadastro criado — confirme o e-mail.', 'ok');
    }
  } catch (erro) {
    msgInline('msg-sco-solicitar', erro.message, 'erro');
  }
}

function scoTrocarForm(mostrarSolicitar) {
  $('#sco-form-login').hidden = mostrarSolicitar;
  $('#sco-form-solicitar').hidden = !mostrarSolicitar;
}

function setupAuth() {
  if (!$('#tela-login')) return;

  $('#btn-sco-entrar').addEventListener('click', scoLogin);
  $('#sco-senha').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') scoLogin();
  });
  $('#link-sco-solicitar').addEventListener('click', (e) => {
    e.preventDefault();
    scoTrocarForm(true);
  });
  $('#link-sco-voltar-login').addEventListener('click', (e) => {
    e.preventDefault();
    scoTrocarForm(false);
  });
  $('#btn-sco-solicitar').addEventListener('click', scoSolicitar);
  const btnSair = $('#btn-sco-sair');
  if (btnSair) btnSair.addEventListener('click', scoLogout);
  const btnAdmin = $('#btn-sco-admin');
  if (btnAdmin) btnAdmin.addEventListener('click', () => navegar('usuarios'));

  // Reage a login/logout/refresh do token e faz a sincronização inicial.
  const cli = scoCliente();
  if (cli) {
    cli.auth.onAuthStateChange((_evento, session) => {
      scoSincronizarSessao(session);
    });
  }
  scoSincronizarSessao();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', setupAuth);
} else {
  setupAuth();
}
