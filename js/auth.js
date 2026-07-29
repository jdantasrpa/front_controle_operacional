'use strict';

/* ============================================================
   auth.js — Autenticação NATIVA do Supabase (Supabase Auth), sem Edge
   Functions.

   • Login: supabase.auth.signInWithPassword; o perfil vem de usuario_perfil.
   • Aprovação: cadastro nasce PENDENTE (aprovado=false); só entra depois que
     um admin aprova (a RLS também bloqueia o pendente no banco).
   • Esqueci a senha: supabase.auth.resetPasswordForEmail (e-mail nativo) e,
     ao voltar pelo link, supabase.auth.updateUser define a nova senha.

   Sem Supabase configurado (config.js vazio), o painel abre em modo
   demonstração, sem gate.
   ============================================================ */

let scoDB = null; // cliente supabase-js (singleton)
// { usuario: {id, email, nome, perfil, id_equipe, ativo, aprovado}, token }
let scoSessaoAtual = null;
// true = trocar senha estando logado (não desloga ao final); false = fluxo
// de recuperação por e-mail (desloga e volta ao login).
let scoTrocaLogado = false;

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

// Lê nome/perfil/equipe/aprovação do usuário logado na tabela própria.
async function scoCarregarPerfil(user) {
  let perfil = 'LEITOR';
  let nome = user.email;
  let idEquipe = null;
  let ativo = true;
  let aprovado = false;
  try {
    const { data } = await scoDB
      .from('usuario_perfil')
      .select('nome, perfil, id_equipe, ativo, aprovado')
      .eq('id', user.id)
      .maybeSingle();
    if (data) {
      perfil = data.perfil || perfil;
      nome = data.nome || nome;
      idEquipe = data.id_equipe;
      ativo = data.ativo;
      aprovado = Boolean(data.aprovado);
    }
  } catch (_) {
    /* perfil ainda não criado: fica pendente */
  }
  return {
    id: user.id,
    email: user.email,
    nome,
    perfil,
    id_equipe: idEquipe,
    ativo,
    aprovado,
  };
}

// Sincroniza scoSessaoAtual com a sessão do supabase-js. Usuário pendente
// (não aprovado) é deslogado — não entra no painel.
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

  if (session && session.user) {
    const usuario = await scoCarregarPerfil(session.user);
    if (!usuario.aprovado) {
      scoSessaoAtual = null;
      try {
        await cli.auth.signOut();
      } catch (_) {
        /* segue */
      }
      scoAplicarSessao();
      return;
    }
    scoSessaoAtual = { usuario, token: session.access_token };
  } else {
    scoSessaoAtual = null;
  }
  scoAplicarSessao();
}

function scoAplicarSessao() {
  const tela = $('#tela-login');
  if (!tela) return;

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

  const btnAdmin = $('#btn-sco-admin');
  if (btnAdmin) btnAdmin.hidden = !(logado && scoPerfil() === 'ADMIN');
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
    if (!scoLogado()) {
      msgInline(
        'msg-sco-login',
        'Seu acesso está aguardando aprovação de um administrador.',
        'erro',
      );
      return;
    }
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
      /* segue */
    }
  }
  scoSessaoAtual = null;
  scoAplicarSessao();
}

// Cadastro nativo (signUp). Nasce PENDENTE (aprovado=false, via trigger);
// o admin aprova depois. Não loga direto — mostra "aguarde aprovação".
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
      try {
        await cli.auth.signOut();
      } catch (_) {
        /* segue */
      }
    }
    scoSessaoAtual = null;
    scoAplicarSessao();
    msgInline(
      'msg-sco-solicitar',
      'Cadastro criado! Aguarde a aprovação de um administrador para entrar.',
    );
    toast('Cadastro criado — aguardando aprovação.', 'ok');
    scoTrocarForm('login');
  } catch (erro) {
    msgInline('msg-sco-solicitar', erro.message, 'erro');
  }
}

// Esqueci a senha: dispara o e-mail nativo de redefinição do Supabase.
async function scoEsqueciSenha() {
  const email = $('#sco-reset-email').value.trim();
  if (!email) {
    msgInline('msg-sco-reset', 'Informe seu e-mail.', 'erro');
    return;
  }
  const cli = scoCliente();
  if (!cli) {
    msgInline('msg-sco-reset', 'Supabase não configurado.', 'erro');
    return;
  }
  try {
    const { error } = await cli.auth.resetPasswordForEmail(email, {
      redirectTo: location.href.split('#')[0],
    });
    if (error) {
      msgInline('msg-sco-reset', error.message, 'erro');
      return;
    }
    msgInline(
      'msg-sco-reset',
      'Link enviado! Verifique seu e-mail para criar uma nova senha.',
    );
    toast('Link de redefinição enviado.', 'ok');
  } catch (erro) {
    msgInline('msg-sco-reset', erro.message, 'erro');
  }
}

// Ao voltar pelo link do e-mail (evento PASSWORD_RECOVERY), define a senha.
async function scoDefinirNovaSenha() {
  const senha = $('#sco-nova-senha').value;
  if (!senha || senha.length < 6) {
    msgInline('msg-sco-nova', 'A senha deve ter ao menos 6 caracteres.', 'erro');
    return;
  }
  const cli = scoCliente();
  if (!cli) {
    msgInline('msg-sco-nova', 'Supabase não configurado.', 'erro');
    return;
  }
  try {
    const { error } = await cli.auth.updateUser({ password: senha });
    if (error) {
      msgInline('msg-sco-nova', error.message, 'erro');
      return;
    }
    $('#sco-nova-senha').value = '';
    scoTrocarForm('login');
    if (scoTrocaLogado) {
      // Troca estando logado: segue na sessão, só fecha o overlay.
      scoTrocaLogado = false;
      toast('Senha alterada com sucesso.', 'ok');
      await scoSincronizarSessao();
    } else {
      // Fluxo de recuperação: desloga e volta ao login.
      try {
        await cli.auth.signOut();
      } catch (_) {
        /* segue */
      }
      scoSessaoAtual = null;
      toast('Senha atualizada! Faça login com a nova senha.', 'ok');
      scoAplicarSessao();
    }
  } catch (erro) {
    msgInline('msg-sco-nova', erro.message, 'erro');
  }
}

// Abre o formulário de nova senha para quem JÁ está logado (sem e-mail).
function scoTrocaSenhaLogado() {
  scoTrocaLogado = true;
  const tela = $('#tela-login');
  if (tela) tela.hidden = false;
  $('#sco-nova-senha').value = '';
  msgInline('msg-sco-nova', '');
  scoTrocarForm('nova');
}

function scoCancelarNova() {
  scoTrocaLogado = false;
  scoTrocarForm('login');
  scoAplicarSessao();
}

// Mostra um dos formulários do gate: login | solicitar | reset | nova.
function scoTrocarForm(alvo) {
  ['login', 'solicitar', 'reset', 'nova'].forEach((f) => {
    const el = $('#sco-form-' + f);
    if (el) el.hidden = f !== alvo;
  });
}

function _ligar(id, evento, fn) {
  const el = $('#' + id);
  if (el) el.addEventListener(evento, fn);
}

function setupAuth() {
  if (!$('#tela-login')) return;

  // Captura o hash ANTES de criar o cliente — o supabase-js limpa a URL ao
  // inicializar, então precisamos ler o retorno do link de e-mail aqui.
  const hashInicial = location.hash || '';

  _ligar('btn-sco-entrar', 'click', scoLogin);
  _ligar('sco-senha', 'keydown', (e) => {
    if (e.key === 'Enter') scoLogin();
  });
  _ligar('link-sco-solicitar', 'click', (e) => {
    e.preventDefault();
    scoTrocarForm('solicitar');
  });
  _ligar('link-sco-voltar-login', 'click', (e) => {
    e.preventDefault();
    scoTrocarForm('login');
  });
  _ligar('link-sco-esqueci', 'click', (e) => {
    e.preventDefault();
    scoTrocarForm('reset');
  });
  _ligar('link-sco-reset-voltar', 'click', (e) => {
    e.preventDefault();
    scoTrocarForm('login');
  });
  _ligar('btn-sco-solicitar', 'click', scoSolicitar);
  _ligar('btn-sco-reset-enviar', 'click', scoEsqueciSenha);
  _ligar('btn-sco-nova-salvar', 'click', scoDefinirNovaSenha);
  _ligar('btn-sco-trocar-senha', 'click', scoTrocaSenhaLogado);
  _ligar('link-sco-nova-cancelar', 'click', (e) => {
    e.preventDefault();
    scoCancelarNova();
  });
  _ligar('btn-sco-sair', 'click', scoLogout);
  _ligar('btn-sco-admin', 'click', () => navegar('usuarios'));

  const cli = scoCliente();
  if (cli) {
    cli.auth.onAuthStateChange((evento, session) => {
      if (evento === 'PASSWORD_RECOVERY') {
        const tela = $('#tela-login');
        if (tela) tela.hidden = false;
        scoTrocarForm('nova');
        return;
      }
      scoSincronizarSessao(session);
    });
  }

  // O link do e-mail pode voltar com erro (expirado/inválido) OU com o token
  // de recuperação. Trata os dois antes da sincronização normal.
  const params = new URLSearchParams(hashInicial.replace(/^#/, ''));
  const erroLink = params.get('error_description') || params.get('error');
  if (erroLink) {
    $('#tela-login').hidden = false;
    scoTrocarForm('reset');
    msgInline(
      'msg-sco-reset',
      decodeURIComponent(erroLink).replace(/\+/g, ' ') + '. Peça um novo link.',
      'erro',
    );
  } else if (/type=recovery/.test(hashInicial)) {
    $('#tela-login').hidden = false;
    scoTrocarForm('nova');
  } else {
    scoSincronizarSessao();
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', setupAuth);
} else {
  setupAuth();
}
