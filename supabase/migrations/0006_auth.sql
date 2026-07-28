-- ============================================================
-- SCO · Autenticação e Permissões (estende o Módulo Segurança)
-- ALTERA a tb_usuario já existente e cria o fluxo de aprovação de acesso.
-- Depende de: 0001_seguranca.sql. Sem RLS.
-- ============================================================

-- --- Perfis: acrescenta MASTER; status da conta -------------------------
-- ADMIN  = acesso total + ÚNICO que cria usuários.
-- MASTER = mesmo acesso do ADMIN, MAS não cria usuários.
-- GESTOR / OPERADOR / LEITOR = perfis operacionais.
alter table public.tb_usuario
    drop constraint if exists tb_usuario_perfil_check;
alter table public.tb_usuario
    add constraint tb_usuario_perfil_check
    check (perfil in ('ADMIN', 'MASTER', 'GESTOR', 'OPERADOR', 'LEITOR'));

alter table public.tb_usuario
    add column if not exists status text not null default 'ATIVO';
alter table public.tb_usuario
    drop constraint if exists tb_usuario_status_check;
alter table public.tb_usuario
    add constraint tb_usuario_status_check
    check (status in ('ATIVO', 'SUSPENSO', 'PENDENTE'));

alter table public.tb_usuario
    add column if not exists senha_provisoria boolean not null default true;
alter table public.tb_usuario
    add column if not exists data_ultimo_acesso timestamptz;

-- --- Caixas que autorizam a criação de acesso ---------------------------
create table if not exists public.tb_email_autorizador (
    id_email_autorizador uuid    primary key default gen_random_uuid(),
    email                text    not null unique,
    nome                 text,
    ativo                boolean not null default true
);
alter table public.tb_email_autorizador disable row level security;

-- --- Solicitações de acesso ao portal (fluxo de aprovação) --------------
-- Alguém pede acesso → PENDENTE + e-mail aos autorizadores. Resposta
-- negativa → NEGADA (usuário suspenso na criação). Positiva → APROVADA e
-- o usuário é criado/ativado.
create table if not exists public.tb_solicitacao_acesso (
    id_solicitacao    uuid        primary key default gen_random_uuid(),
    nome              text        not null,
    email             text        not null,
    perfil_solicitado text        not null default 'OPERADOR'
        check (perfil_solicitado in
            ('ADMIN', 'MASTER', 'GESTOR', 'OPERADOR', 'LEITOR')),
    status            text        not null default 'PENDENTE'
        check (status in ('PENDENTE', 'APROVADA', 'NEGADA')),
    token_autorizacao text        not null unique,
    id_usuario        uuid        references public.tb_usuario (id_usuario),
    autorizador_email text,
    motivo            text,
    solicitado_em     timestamptz not null default now(),
    respondido_em     timestamptz
);
create index if not exists ix_solicitacao_status
    on public.tb_solicitacao_acesso (status);
create index if not exists ix_solicitacao_email
    on public.tb_solicitacao_acesso (email);
alter table public.tb_solicitacao_acesso disable row level security;
