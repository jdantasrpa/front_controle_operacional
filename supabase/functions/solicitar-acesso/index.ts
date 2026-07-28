// supabase/functions/solicitar-acesso/index.ts
// POST { nome, email, perfil_solicitado } -> cria solicitação PENDENTE e
// envia e-mail (Resend) aos autorizadores com links Aprovar / Negar.
// Deploy com verify_jwt=false (chamado do front com a anon key).

import { CORS, json, supaAdmin, tokenAleatorio } from '../_shared/comum.ts';

const PERFIS = ['ADMIN', 'MASTER', 'GESTOR', 'OPERADOR', 'LEITOR'];

// deno-lint-ignore no-explicit-any
const env = (k: string) => (globalThis as any).Deno.env.get(k) as string;

async function enviarEmail(para: string[], assunto: string, corpo: string) {
  const resp = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${env('RESEND_API_KEY')}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      from: env('RESEND_FROM'),
      to: para,
      subject: assunto,
      html: corpo,
    }),
  });
  if (!resp.ok) throw new Error(`Resend ${resp.status}: ${await resp.text()}`);
}

function corpoEmail(nome: string, email: string, perfil: string, link: string) {
  const aprovar = `${link}&decisao=aprovar`;
  const negar = `${link}&decisao=negar`;
  return `
    <div style="font-family:sans-serif;max-width:520px">
      <h2>Solicitação de acesso ao SCO</h2>
      <p><b>${nome}</b> (${email}) pediu acesso como <b>${perfil}</b>.</p>
      <p>
        <a href="${aprovar}" style="background:#16a34a;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none;margin-right:8px">Aprovar</a>
        <a href="${negar}" style="background:#dc2626;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none">Negar</a>
      </p>
      <p style="color:#666;font-size:12px">Negar suspende a criação do usuário.</p>
    </div>`;
}

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS });
  if (req.method !== 'POST') return json({ erro: 'Método não suportado.' }, 405);

  let corpo: { nome?: string; email?: string; perfil_solicitado?: string };
  try {
    corpo = await req.json();
  } catch {
    return json({ erro: 'JSON inválido.' }, 400);
  }

  const nome = String(corpo.nome || '').trim();
  const email = String(corpo.email || '').trim().toLowerCase();
  const perfil = String(corpo.perfil_solicitado || 'OPERADOR').toUpperCase();
  if (!nome || !email) return json({ erro: 'Informe nome e e-mail.' }, 400);
  if (!PERFIS.includes(perfil)) return json({ erro: 'Perfil inválido.' }, 400);

  const supa = supaAdmin();

  // Já existe usuário ou solicitação pendente para esse e-mail?
  const { data: jaUsuario } = await supa
    .from('tb_usuario').select('id_usuario').eq('email', email).maybeSingle();
  if (jaUsuario) return json({ erro: 'Já existe usuário com esse e-mail.' }, 409);

  const token = tokenAleatorio();
  const { error: erroInsert } = await supa.from('tb_solicitacao_acesso').insert({
    nome,
    email,
    perfil_solicitado: perfil,
    status: 'PENDENTE',
    token_autorizacao: token,
  });
  if (erroInsert) return json({ erro: erroInsert.message }, 400);

  const { data: autorizadores } = await supa
    .from('tb_email_autorizador').select('email').eq('ativo', true);
  const para = (autorizadores || []).map((a) => a.email);
  if (!para.length) {
    return json({ erro: 'Nenhuma caixa autorizadora cadastrada.' }, 500);
  }

  const link = `${env('SUPABASE_URL')}/functions/v1/autorizar-acesso?token=${token}`;
  try {
    await enviarEmail(para, 'SCO — solicitação de acesso', corpoEmail(nome, email, perfil, link));
  } catch (e) {
    return json({ erro: `Falha ao enviar e-mail: ${e.message}` }, 502);
  }

  return json({ ok: true, mensagem: 'Solicitação enviada para autorização.' });
});
