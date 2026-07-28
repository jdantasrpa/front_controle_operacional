// supabase/functions/login/index.ts
// POST { email, senha } -> valida contra tb_usuario e devolve token de sessão.
// Deploy com verify_jwt=false (é pré-autenticação; o front chama com anon).

import { assinarToken, CORS, json, supaAdmin } from '../_shared/comum.ts';
import { verificarSenha } from '../_shared/cripto.ts';

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS });
  if (req.method !== 'POST') return json({ erro: 'Método não suportado.' }, 405);

  let corpo: { email?: string; senha?: string };
  try {
    corpo = await req.json();
  } catch {
    return json({ erro: 'JSON inválido.' }, 400);
  }

  const email = String(corpo.email || '').trim().toLowerCase();
  const senha = String(corpo.senha || '');
  if (!email || !senha) return json({ erro: 'Informe e-mail e senha.' }, 400);

  const supa = supaAdmin();
  const { data: usuario } = await supa
    .from('tb_usuario')
    .select('id_usuario, nome, email, perfil, senha_hash, status, senha_provisoria')
    .eq('email', email)
    .maybeSingle();

  // Mensagem genérica: não revela se o e-mail existe.
  const generico = { erro: 'Credenciais inválidas.' };
  if (!usuario) return json(generico, 401);
  if (usuario.status !== 'ATIVO') {
    return json({ erro: 'Conta não está ativa.' }, 403);
  }
  if (!(await verificarSenha(senha, usuario.senha_hash))) {
    return json(generico, 401);
  }

  await supa
    .from('tb_usuario')
    .update({ data_ultimo_acesso: new Date().toISOString() })
    .eq('id_usuario', usuario.id_usuario);

  const token = await assinarToken({
    sub: usuario.id_usuario,
    perfil: usuario.perfil,
    email: usuario.email,
  });

  return json({
    token,
    usuario: {
      id_usuario: usuario.id_usuario,
      nome: usuario.nome,
      email: usuario.email,
      perfil: usuario.perfil,
      senha_provisoria: usuario.senha_provisoria,
    },
  });
});
