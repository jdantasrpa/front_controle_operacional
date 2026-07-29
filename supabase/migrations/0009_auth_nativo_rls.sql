-- ============================================================
-- SCO · Fase 1 da virada para Supabase Auth (login nativo, sem Edge Functions)
--
-- O login passa a ser o Supabase Auth (auth.users). Cada usuário tem UM
-- perfil em public.usuario_perfil (1:1 com auth.users), criado sozinho no
-- cadastro. As telas leem/gravam direto pelo JS, protegidas por RLS.
--
-- BOOTSTRAP do 1º admin (rode no SQL Editor, que ignora RLS):
--   1) Crie o usuário no Dashboard: Authentication > Users > Add user
--      (defina e-mail + senha; marque "Auto Confirm User").
--   2) Promova para ADMIN:
--      update public.usuario_perfil set perfil = 'ADMIN'
--       where id = (select id from auth.users where email = 'seu@email');
-- ============================================================

-- --- Perfil do usuário (1:1 com auth.users) -----------------------------
create table if not exists public.usuario_perfil (
    id        uuid primary key references auth.users (id) on delete cascade,
    nome      text,
    perfil    text not null default 'LEITOR'
        check (perfil in ('ADMIN', 'MASTER', 'GESTOR', 'OPERADOR', 'LEITOR')),
    id_equipe uuid,
    ativo     boolean not null default true,
    criado_em timestamptz not null default now()
);

-- --- Cria o perfil automaticamente quando um usuário nasce no Auth -------
create or replace function public.criar_perfil_no_signup()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.usuario_perfil (id, nome)
    values (new.id, coalesce(new.raw_user_meta_data ->> 'nome', new.email))
    on conflict (id) do nothing;
    return new;
end;
$$;

drop trigger if exists trg_criar_perfil on auth.users;
create trigger trg_criar_perfil
    after insert on auth.users
    for each row execute function public.criar_perfil_no_signup();

-- --- Helper: perfil do usuário logado (usado nas políticas de RLS) -------
create or replace function public.meu_perfil()
returns text
language sql
stable
security definer
set search_path = public
as $$
    select perfil from public.usuario_perfil where id = auth.uid();
$$;

-- --- RLS do perfil ------------------------------------------------------
alter table public.usuario_perfil enable row level security;

-- Qualquer logado enxerga os perfis (para listar responsáveis, equipe etc.).
drop policy if exists usuario_perfil_leitura on public.usuario_perfil;
create policy usuario_perfil_leitura on public.usuario_perfil
    for select to authenticated using (true);

-- Só o ADMIN altera perfis (promover, trocar equipe, ativar/desativar).
drop policy if exists usuario_perfil_admin_escreve on public.usuario_perfil;
create policy usuario_perfil_admin_escreve on public.usuario_perfil
    for all to authenticated
    using (public.meu_perfil() = 'ADMIN')
    with check (public.meu_perfil() = 'ADMIN');
