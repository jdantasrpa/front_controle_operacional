-- ============================================================
-- SCO · Equipes (estende o Módulo Segurança)
-- Usuário pertence a uma equipe; só ADMIN e MASTER trocam a equipe
-- (regra em api/domain_permissao.pode_alterar_equipe).
-- Depende de: 0001_seguranca.sql, 0006_auth.sql. Sem RLS.
-- ============================================================

create table if not exists public.tb_equipe (
    id_equipe uuid    primary key default gen_random_uuid(),
    nome      text    not null unique,
    ativo     boolean not null default true
);
alter table public.tb_equipe disable row level security;

alter table public.tb_usuario
    add column if not exists id_equipe uuid references public.tb_equipe (id_equipe);
create index if not exists ix_usuario_equipe on public.tb_usuario (id_equipe);
