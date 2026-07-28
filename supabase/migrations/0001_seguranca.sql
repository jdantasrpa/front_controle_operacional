-- ============================================================
-- SCO · Módulo: Segurança  (DER-MCN — Submódulo: Controle de Acesso)
-- Roda PRIMEIRO: tb_usuario é referenciada pela Remessa (Conciliação).
-- Sem RLS, conforme decisão do projeto. Supersede
-- scripts/supabase_schema_usuarios.sql (tb_usuario passa a ser canônica).
-- ============================================================

create extension if not exists pgcrypto;

create table if not exists public.tb_usuario (
    id_usuario    uuid        primary key default gen_random_uuid(),
    email         text        not null unique,
    nome          text        not null,
    perfil        text        not null default 'OPERADOR'
        check (perfil in ('ADMIN', 'GESTOR', 'OPERADOR', 'LEITOR')),
    senha_hash    text        not null,
    ativo         boolean     not null default true,
    data_cadastro timestamptz not null default now()
);

create index if not exists ix_usuario_email on public.tb_usuario (email);

-- id_usuario pode ser alinhado ao Supabase Auth (auth.users.id) no futuro;
-- hoje é autônomo (autenticação própria via senha_hash — ver domain_usuarios).
alter table public.tb_usuario disable row level security;
