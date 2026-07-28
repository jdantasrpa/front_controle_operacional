# SCO — Edge Functions (auth + fluxo de acesso)

Camada server-side (Deno) hospedada pelo Supabase. Guarda os segredos,
faz login, checa permissão, cifra/decifra (AES-256-GCM interoperável com
`api/cripto.py`) e dispara os e-mails via Resend.

```
Front (GitHub Pages) → Edge Function → Postgres
                              └──> Resend (e-mail)
```

## Funções
| Função | Método | O que faz |
|---|---|---|
| `login` | POST | Valida e-mail/senha (`tb_usuario`) e devolve token de sessão |
| `solicitar-acesso` | POST | Cria solicitação PENDENTE e e-mail aos autorizadores (links Aprovar/Negar) |
| `autorizar-acesso` | GET | Link do e-mail: Aprovar cria o usuário (senha provisória); Negar suspende |

Compartilhado em `_shared/`: `cripto.ts` (AES-256-GCM + PBKDF2, **mesma
chave/formato do Python**) e `comum.ts` (cliente, CORS, token de sessão).

## Pré-requisitos
1. Rodar as migrations, inclusive **`0006_auth.sql`**.
2. Cadastrar quem autoriza (SQL Editor):
   ```sql
   insert into public.tb_email_autorizador (email, nome)
   values ('chefe@empresa.com', 'Gestor');
   ```
3. Conta no **Resend** com um remetente/domínio verificado.

## Secrets (nunca no front)
`SUPABASE_URL` e `SUPABASE_SERVICE_ROLE_KEY` são injetados automaticamente.
Defina os demais:

```bash
supabase secrets set \
  SCO_CHAVE_MESTRA="<a MESMA chave base64 do backend Python>" \
  SCO_JWT_SECRET="<segredo forte para assinar o token de sessão>" \
  RESEND_API_KEY="re_..." \
  RESEND_FROM="SCO <no-reply@seudominio.com>"
```

> ⚠️ `SCO_CHAVE_MESTRA` **tem que ser idêntica** à do `.env` do backend —
> senão um lado não decifra o que o outro cifrou (interop já validada).

## Deploy
As três são públicas (login/solicitar são pré-auth; autorizar é link de
e-mail), então **sem verificação de JWT**:

```bash
supabase functions deploy login --no-verify-jwt
supabase functions deploy solicitar-acesso --no-verify-jwt
supabase functions deploy autorizar-acesso --no-verify-jwt
```

## Uso no front (GitHub Pages)
```js
const BASE = `${SUPABASE_URL}/functions/v1`;
const headers = { 'Content-Type': 'application/json', apikey: SUPABASE_ANON_KEY };

// login
const r = await fetch(`${BASE}/login`, {
  method: 'POST', headers,
  body: JSON.stringify({ email, senha }),
});
const { token, usuario } = await r.json();   // guarde o token da sessão

// solicitar acesso
await fetch(`${BASE}/solicitar-acesso`, {
  method: 'POST', headers,
  body: JSON.stringify({ nome, email, perfil_solicitado: 'OPERADOR' }),
});
```

O link Aprovar/Negar do e-mail aponta para `autorizar-acesso` e é clicado
direto pelo autorizador — não precisa de chave.

## Papéis (enforcement)
- **ADMIN**: tudo + único que cria usuário direto.
- **MASTER**: tudo, menos criar usuário.
- Regras puras em `api/domain_permissao.py`; nas functions, cheque
  `payload.perfil` do token antes de qualquer escrita sensível.
