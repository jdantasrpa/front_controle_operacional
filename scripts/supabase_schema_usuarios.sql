-- ============================================================
-- Gestão de usuários do Painel Controle Operacional (Supabase / PostgreSQL)
--
-- Sem Row Level Security, conforme decisão do projeto. A senha é guardada
-- apenas como hash PBKDF2 (ver api/domain_usuarios.py); texto claro nunca
-- é persistido. Rode este script no SQL Editor do Supabase.
--
-- ATENÇÃO: sem RLS, o acesso à tabela depende de qual chave a aplicação
-- usa. Nunca exponha a `service_role key` no front (página pública do
-- GitHub Pages); o acesso a esta tabela deve passar por um backend/Edge
-- Function que valide a senha — a página estática não deve ler senha_hash.
-- ============================================================

create table if not exists public.usuarios (
    id               uuid         primary key default gen_random_uuid(),
    nome             text         not null,
    email            text         not null unique,
    login            text         not null unique,
    senha_hash       text         not null,
    perfil           text         not null default 'OPERADOR'
        check (perfil in ('ADMIN', 'GESTOR', 'OPERADOR', 'LEITOR')),
    status           text         not null default 'ATIVO'
        check (status in ('ATIVO', 'INATIVO', 'BLOQUEADO')),
    senha_provisoria boolean      not null default true,
    criado_em        timestamptz  not null default now(),
    atualizado_em    timestamptz  not null default now(),
    ultimo_acesso_em timestamptz
);

create index if not exists idx_usuarios_login on public.usuarios (login);
create index if not exists idx_usuarios_email on public.usuarios (email);

-- RLS desativado por decisão do projeto (padrão do Supabase para tabela
-- nova; explícito aqui para não haver ambiguidade).
alter table public.usuarios disable row level security;

-- Mantém `atualizado_em` sempre coerente em UPDATEs.
create or replace function public.tocar_atualizado_em()
returns trigger as $$
begin
    new.atualizado_em := now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_usuarios_atualizado_em on public.usuarios;
create trigger trg_usuarios_atualizado_em
    before update on public.usuarios
    for each row execute function public.tocar_atualizado_em();

-- A conta admin NÃO é criada aqui: gere o INSERT com senha aleatória por
-- `python scripts/criar_admin.py`, que imprime a senha uma única vez.
