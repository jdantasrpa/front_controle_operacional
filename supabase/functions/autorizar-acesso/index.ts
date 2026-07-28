// supabase/functions/autorizar-acesso/index.ts
// GET ?token=...&decisao=aprovar|negar  (link clicado no e-mail).
// Aprovar -> cria o usuário (senha provisória enviada por e-mail) e marca
// APROVADA. Negar -> marca NEGADA (usuário suspenso na criação).
// Deploy com verify_jwt=false (é um link público, sem anon key).

import { CORS, html, supaAdmin, tokenAleatorio } from '../_shared/comum.ts';
import { gerarHashSenha } from '../_shared/cripto.ts';

// deno-lint-ignore no-explicit-any
const env = (k: string) => (globalThis as any).Deno.env.get(k) as string;

function pagina(titulo: string, msg: string) {
  return html(`<!doctype html><meta charset="utf-8">
    <div style="font-family:sans-serif;max-width:520px;margin:60px auto;text-align:center">
      <h2>${titulo}</h2><p style="color:#444">${msg}</p>
    </div>`);
}

async function enviarSenha(email: string, nome: string, senha: string) {
  await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${env('RESEND_API_KEY')}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      from: env('RESEND_FROM'),
      to: [email],
      subject: 'SCO — acesso aprovado',
      html: `<div style="font-family:sans-serif">
        <h2>Acesso aprovado</h2>
        <p>Olá, ${nome}. Seu acesso ao SCO foi aprovado.</p>
        <p>Senha provisória: <b>${senha}</b></p>
        <p style="color:#666;font-size:12px">Troque a senha no primeiro acesso.</p>
      </div>`,
    }),
  });
}

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS });

  const url = new URL(req.url);
  const token = url.searchParams.get('token') || '';
  const decisao = (url.searchParams.get('decisao') || '').toLowerCase();
  if (!token || !['aprovar', 'negar'].includes(decisao)) {
    return pagina('Link inválido', 'Faltam parâmetros token/decisao.');
  }

  const supa = supaAdmin();
  const { data: sol } = await supa
    .from('tb_solicitacao_acesso')
    .select('*')
    .eq('token_autorizacao', token)
    .maybeSingle();

  if (!sol) return pagina('Solicitação não encontrada', 'Token desconhecido.');
  if (sol.status !== 'PENDENTE') {
    return pagina('Já respondida', `Esta solicitação já está ${sol.status}.`);
  }

  const agora = new Date().toISOString();

  if (decisao === 'negar') {
    await supa.from('tb_solicitacao_acesso').update({
      status: 'NEGADA',
      respondido_em: agora,
      motivo: 'Negada pelo autorizador.',
    }).eq('id_solicitacao', sol.id_solicitacao);
    return pagina('Acesso negado', `A criação de ${sol.email} foi suspensa.`);
  }

  // Aprovar: cria o usuário com senha provisória.
  const senha = tokenAleatorio(9);
  const { data: novo, error: erroUser } = await supa.from('tb_usuario').insert({
    nome: sol.nome,
    email: sol.email,
    perfil: sol.perfil_solicitado,
    senha_hash: await gerarHashSenha(senha),
    status: 'ATIVO',
    senha_provisoria: true,
  }).select('id_usuario').single();

  if (erroUser) {
    return pagina('Erro ao criar usuário', erroUser.message);
  }

  await supa.from('tb_solicitacao_acesso').update({
    status: 'APROVADA',
    respondido_em: agora,
    id_usuario: novo.id_usuario,
  }).eq('id_solicitacao', sol.id_solicitacao);

  try {
    await enviarSenha(sol.email, sol.nome, senha);
  } catch (_) {
    // Usuário criado mesmo se o e-mail falhar; senha pode ser resetada.
  }

  return pagina('Acesso aprovado', `Usuário ${sol.email} criado e notificado.`);
});
