-- ============================================================
-- SCO · Módulo: Cobrança  (DER-MCN — Submódulo: Cobrança de Inadimplência)
-- Depende de: 0002_gestao_convenios.sql (tb_vinculo). Sem RLS.
-- ============================================================

create table if not exists public.tb_cobranca_caso (
    id_cobranca_caso uuid        primary key default gen_random_uuid(),
    id_vinculo       uuid        not null references public.tb_vinculo (id_vinculo) on delete cascade,
    competencia      text,
    valor            numeric(15, 2),
    status           text,
    data_abertura    timestamptz not null default now()
);
create index if not exists ix_cobranca_caso_vinculo on public.tb_cobranca_caso (id_vinculo);

create table if not exists public.tb_cobranca_tentativa (
    id_cobranca_tentativa uuid        primary key default gen_random_uuid(),
    id_cobranca_caso      uuid        not null references public.tb_cobranca_caso (id_cobranca_caso) on delete cascade,
    canal                 text,
    resultado             text,
    data_tentativa        timestamptz not null default now()
);
create index if not exists ix_cobranca_tentativa_caso on public.tb_cobranca_tentativa (id_cobranca_caso);

-- Sem RLS (decisão do projeto).
alter table public.tb_cobranca_caso      disable row level security;
alter table public.tb_cobranca_tentativa disable row level security;
