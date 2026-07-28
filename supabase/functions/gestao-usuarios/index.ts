// supabase/functions/gestao-usuarios/index.ts
// Gestão de usuários e equipes. Protegida pelo token de sessão (header
// x-sco-token) e por perfil:
//   ADMIN            -> cria usuário
//   ADMIN | MASTER   -> lista, gerencia equipes e troca a equipe do usuário
// POST { acao, ... }. Deploy com verify_jwt=false (validamos nosso token).

import {
  CORS,
  json,
  supaAdmin,
  tokenAleatorio,
  verificarToken,
} from '../_shared/comum.ts';
import { gerarHashSenha } from '../_shared/cripto.ts';

const ACESSO_TOTAL = ['ADMIN', 'MASTER'];
const PERFIS = ['ADMIN', 'MASTER', 'GESTOR', 'OPERADOR', 'LEITOR'];

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS });
  if (req.method !== 'POST') return json({ erro: 'Método não suportado.' }, 405);

  const sessao = await verificarToken(req.headers.get('x-sco-token') || '');
  if (!sessao) return json({ erro: 'Sessão inválida ou expirada.' }, 401);
  const perfil = String(sessao.perfil || '').toUpperCase();

  let corpo: Record<string, unknown>;
  try {
    corpo = await req.json();
  } catch {
    return json({ erro: 'JSON inválido.' }, 400);
  }
  const acao = String(corpo.acao || '');
  const supa = supaAdmin();
  const exigir = (ok: boolean) => ok || null;

  if (acao === 'listar_usuarios') {
    if (!ACESSO_TOTAL.includes(perfil)) return json({ erro: 'Sem permissão.' }, 403);
    const { data } = await supa
      .from('tb_usuario')
      .select('id_usuario,nome,email,perfil,status,id_equipe,data_ultimo_acesso')
      .order('nome');
    return json({ usuarios: data || [] });
  }

  if (acao === 'listar_equipes') {
    if (!ACESSO_TOTAL.includes(perfil)) return json({ erro: 'Sem permissão.' }, 403);
    const { data } = await supa
      .from('tb_equipe').select('id_equipe,nome,ativo').order('nome');
    return json({ equipes: data || [] });
  }

  if (acao === 'criar_usuario') {
    if (perfil !== 'ADMIN') return json({ erro: 'Só o ADMIN cria usuários.' }, 403);
    const nome = String(corpo.nome || '').trim();
    const email = String(corpo.email || '').trim().toLowerCase();
    const perfilNovo = String(corpo.perfil || 'OPERADOR').toUpperCase();
    if (!nome || !email) return json({ erro: 'Informe nome e e-mail.' }, 400);
    if (!PERFIS.includes(perfilNovo)) return json({ erro: 'Perfil inválido.' }, 400);

    const senha = String(corpo.senha || '') || tokenAleatorio(9);
    const { data, error } = await supa.from('tb_usuario').insert({
      nome,
      email,
      perfil: perfilNovo,
      senha_hash: await gerarHashSenha(senha),
      status: 'ATIVO',
      senha_provisoria: true,
      id_equipe: corpo.id_equipe || null,
    }).select('id_usuario').single();
    if (error) return json({ erro: error.message }, 400);
    // Senha provisória devolvida uma vez para o ADMIN repassar.
    return json({ ok: true, id_usuario: data.id_usuario, senha_provisoria: senha });
  }

  if (acao === 'criar_equipe') {
    if (!ACESSO_TOTAL.includes(perfil)) return json({ erro: 'Sem permissão.' }, 403);
    const nome = String(corpo.nome || '').trim();
    if (!nome) return json({ erro: 'Informe o nome da equipe.' }, 400);
    const { error } = await supa.from('tb_equipe').insert({ nome });
    if (error) return json({ erro: error.message }, 400);
    return json({ ok: true });
  }

  if (acao === 'alterar_equipe') {
    if (!ACESSO_TOTAL.includes(perfil)) {
      return json({ erro: 'Só ADMIN ou MASTER trocam a equipe.' }, 403);
    }
    const idUsuario = String(corpo.id_usuario || '');
    if (!idUsuario) return json({ erro: 'Informe o usuário.' }, 400);
    const { error } = await supa
      .from('tb_usuario')
      .update({ id_equipe: corpo.id_equipe || null })
      .eq('id_usuario', idUsuario);
    if (error) return json({ erro: error.message }, 400);
    return json({ ok: true });
  }

  if (acao === 'alterar_status') {
    if (!ACESSO_TOTAL.includes(perfil)) return json({ erro: 'Sem permissão.' }, 403);
    const status = String(corpo.status || '');
    if (!['ATIVO', 'SUSPENSO'].includes(status)) {
      return json({ erro: 'Status inválido.' }, 400);
    }
    const { error } = await supa
      .from('tb_usuario').update({ status })
      .eq('id_usuario', String(corpo.id_usuario || ''));
    if (error) return json({ erro: error.message }, 400);
    return json({ ok: true });
  }

  if (acao === 'editar_usuario') {
    if (perfil !== 'ADMIN') return json({ erro: 'Só o ADMIN edita usuários.' }, 403);
    const idUsuario = String(corpo.id_usuario || '');
    if (!idUsuario) return json({ erro: 'Informe o usuário.' }, 400);
    const nome = String(corpo.nome || '').trim();
    const email = String(corpo.email || '').trim().toLowerCase();
    const perfilNovo = String(corpo.perfil || '').toUpperCase();
    const status = String(corpo.status || '').toUpperCase();
    if (!nome || !email) return json({ erro: 'Informe nome e e-mail.' }, 400);
    if (!PERFIS.includes(perfilNovo)) return json({ erro: 'Perfil inválido.' }, 400);
    if (!['ATIVO', 'SUSPENSO'].includes(status)) return json({ erro: 'Status inválido.' }, 400);
    const { error } = await supa.from('tb_usuario').update({
      nome,
      email,
      perfil: perfilNovo,
      status,
      id_equipe: corpo.id_equipe || null,
    }).eq('id_usuario', idUsuario);
    if (error) return json({ erro: error.message }, 400);
    return json({ ok: true });
  }

  if (acao === 'editar_equipe') {
    if (!ACESSO_TOTAL.includes(perfil)) return json({ erro: 'Sem permissão.' }, 403);
    const idEquipe = String(corpo.id_equipe || '');
    if (!idEquipe) return json({ erro: 'Informe a equipe.' }, 400);
    const patch: Record<string, unknown> = {};
    if (corpo.nome !== undefined) {
      const nome = String(corpo.nome || '').trim();
      if (!nome) return json({ erro: 'Informe o nome da equipe.' }, 400);
      patch.nome = nome;
    }
    if (corpo.ativo !== undefined) patch.ativo = Boolean(corpo.ativo);
    if (!Object.keys(patch).length) return json({ erro: 'Nada para alterar.' }, 400);
    const { error } = await supa.from('tb_equipe').update(patch).eq('id_equipe', idEquipe);
    if (error) return json({ erro: error.message }, 400);
    return json({ ok: true });
  }

  if (acao === 'listar_solicitacoes') {
    // Somente leitura: a decisão (aprovar/negar) é feita pelos links do
    // e-mail (função autorizar-acesso). Aqui é só acompanhamento no painel.
    if (!ACESSO_TOTAL.includes(perfil)) return json({ erro: 'Sem permissão.' }, 403);
    const { data } = await supa
      .from('tb_solicitacao_acesso')
      .select('id_solicitacao,nome,email,perfil_solicitado,status,solicitado_em,respondido_em,autorizador_email')
      .order('solicitado_em', { ascending: false })
      .limit(100);
    return json({ solicitacoes: data || [] });
  }

  return json({ erro: `Ação desconhecida: ${acao}` }, 400);
});
