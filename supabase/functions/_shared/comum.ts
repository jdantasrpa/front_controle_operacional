// supabase/functions/_shared/comum.ts
// Utilidades comuns às Edge Functions: cliente Supabase (service_role),
// CORS, resposta JSON e token de sessão (HMAC-SHA256).

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

// deno-lint-ignore no-explicit-any
const env = (k: string) => (globalThis as any).Deno.env.get(k) as string;

export const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers':
    'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
};

export function json(corpo: unknown, status = 200): Response {
  return new Response(JSON.stringify(corpo), {
    status,
    headers: { ...CORS, 'Content-Type': 'application/json' },
  });
}

export function html(corpo: string, status = 200): Response {
  return new Response(corpo, {
    status,
    headers: { ...CORS, 'Content-Type': 'text/html; charset=utf-8' },
  });
}

// Cliente admin — usa a service_role (injetada pelo Supabase nas functions).
export function supaAdmin() {
  return createClient(
    env('SUPABASE_URL'),
    env('SUPABASE_SERVICE_ROLE_KEY'),
    { auth: { persistSession: false } },
  );
}

const b64url = (bytes: Uint8Array) =>
  btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');

// Token opaco (url-safe) para os links de aprovar/negar do e-mail.
export function tokenAleatorio(bytes = 32): string {
  return b64url(crypto.getRandomValues(new Uint8Array(bytes)));
}

async function hmac(mensagem: string): Promise<string> {
  const chave = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(env('SCO_JWT_SECRET')),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const assinatura = new Uint8Array(
    await crypto.subtle.sign(
      'HMAC',
      chave,
      new TextEncoder().encode(mensagem),
    ),
  );
  return b64url(assinatura);
}

// Token de sessão: <payload_b64url>.<hmac_b64url>. Expira em `horas`.
export async function assinarToken(
  payload: Record<string, unknown>,
  horas = 12,
): Promise<string> {
  const corpo = {
    ...payload,
    exp: Math.floor(Date.now() / 1000) + horas * 3600,
  };
  const parte = b64url(new TextEncoder().encode(JSON.stringify(corpo)));
  return `${parte}.${await hmac(parte)}`;
}

export async function verificarToken(
  token: string,
): Promise<Record<string, unknown> | null> {
  const [parte, assinatura] = String(token || '').split('.');
  if (!parte || !assinatura) return null;
  if ((await hmac(parte)) !== assinatura) return null;

  try {
    const bin = atob(parte.replace(/-/g, '+').replace(/_/g, '/'));
    const payload = JSON.parse(bin);
    if (payload.exp && payload.exp < Math.floor(Date.now() / 1000)) return null;
    return payload;
  } catch {
    return null;
  }
}
