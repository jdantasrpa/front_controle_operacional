'use strict';

/* ============================================================
   auth.js — Login e "solicitar acesso" via Edge Functions do Supabase.

   O front (GitHub Pages) só conversa com as functions usando a chave
   PUBLICA (config.js). Login/solicitação/aprovação e a criptografia rodam
   no servidor (Edge Functions). Sem Supabase configurado, o painel abre em
   modo demonstração, sem gate.
   ============================================================ */

const SCO_SESSAO_KEY = 'sco_sessao';

async function scoChamarFuncao(nome, corpo) {
  const resp = await fetch(
    `${SCO_CONFIG.SUPABASE_URL}/functions/v1/${nome}`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        apikey: SCO_CONFIG.SUPABASE_ANON_KEY,
        Authorization: `Bearer ${SCO_CONFIG.SUPABASE_ANON_KEY}`,
      },
      body: JSON.stringify(corpo),
    },
  );
  const dados = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(dados.erro || `Erro ${resp.status}`);
  return dados;
}

// Igual à scoChamarFuncao, mas envia o token da sessão em x-sco-token —
// exigido pelas functions protegidas (ex.: gestao-usuarios).
async function scoChamarFuncaoAutenticada(nome, corpo) {
  const s = scoSessao();
  const resp = await fetch(
    `${SCO_CONFIG.SUPABASE_URL}/functions/v1/${nome}`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        apikey: SCO_CONFIG.SUPABASE_ANON_KEY,
        Authorization: `Bearer ${SCO_CONFIG.SUPABASE_ANON_KEY}`,
        'x-sco-token': (s && s.token) || '',
      },
      body: JSON.stringify(corpo),
    },
  );
  const dados = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(dados.erro || `Erro ${resp.status}`);
  return dados;
}

function scoSessao() {
  try {
    return JSON.parse(localStorage.getItem(SCO_SESSAO_KEY));
  } catch {
    return null;
  }
}

function scoPerfil() {
  const s = scoSessao();
  return s && s.usuario && s.usuario.perfil
    ? String(s.usuario.perfil).toUpperCase()
    : '';
}

function scoAcessoTotal() {
  return ['ADMIN', 'MASTER'].includes(scoPerfil());
}

// Lê a expiração do token (payload em base64url) sem validar a assinatura —
// é só para UX; a validação de verdade acontece na Edge Function.
function scoTokenExpirado(token) {
  try {
    const parte = String(token).split('.')[0].replace(/-/g, '+').replace(/_/g, '/');
    const payload = JSON.parse(atob(parte));
    return payload.exp && payload.exp < Math.floor(Date.now() / 1000);
  } catch {
    return true;
  }
}

function scoLogado() {
  const s = scoSessao();
  return Boolean(s && s.token && !scoTokenExpirado(s.token));
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
    const s = scoSessao();
    barra.hidden = !logado;
    if (logado) {
      barra.querySelector('#sco-usuario-nome').textContent =
        `${s.usuario.nome} · ${s.usuario.perfil}`;
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
  try {
    const d = await scoChamarFuncao('login', { email, senha });
    localStorage.setItem(
      SCO_SESSAO_KEY,
      JSON.stringify({ token: d.token, usuario: d.usuario }),
    );
    $('#sco-senha').value = '';
    scoAplicarSessao();
    toast(`Bem-vindo, ${d.usuario.nome}.`, 'ok');
  } catch (erro) {
    msgInline('msg-sco-login', erro.message, 'erro');
  }
}

function scoLogout() {
  localStorage.removeItem(SCO_SESSAO_KEY);
  scoAplicarSessao();
}

async function scoSolicitar() {
  const nome = $('#sco-sol-nome').value.trim();
  const email = $('#sco-sol-email').value.trim();
  const perfil = $('#sco-sol-perfil').value;
  if (!nome || !email) {
    msgInline('msg-sco-solicitar', 'Informe nome e e-mail.', 'erro');
    return;
  }
  try {
    await scoChamarFuncao('solicitar-acesso', {
      nome,
      email,
      perfil_solicitado: perfil,
    });
    msgInline('msg-sco-solicitar', 'Solicitação enviada para autorização.');
    toast('Solicitação enviada.', 'ok');
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
  if (btnAdmin) {
    btnAdmin.addEventListener('click', () => navegar('usuarios'));
  }

  scoAplicarSessao();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', setupAuth);
} else {
  setupAuth();
}
