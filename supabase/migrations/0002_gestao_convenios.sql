-- ============================================================
-- SCO · Módulo: Gestão de Convênios  (DER-MCN)
-- Submódulos: Cadastros Estruturais · Vínculos e Custos
-- Depende de: 0001_seguranca.sql. Sem RLS.
-- Ordem: originadora → averbadora/gestora → grupo → convênio →
--        convenio_grupo → vínculo → custo → custo_faixa.
-- ============================================================

-- --- Cadastros Estruturais · Originadora ---------------------------------
create table if not exists public.tb_originadora (
    id_originadora uuid        primary key default gen_random_uuid(),
    nome           text        not null unique,
    codigo         text,
    cnpj           text,
    ativo          boolean     not null default true,
    observacao     text,
    data_cadastro  timestamptz not null default now()
);

-- --- Cadastros Estruturais · Averbadora / Gestora de Margem --------------
create table if not exists public.tb_averbadora (
    id_averbadora uuid    primary key default gen_random_uuid(),
    nome          text    not null,
    cnpj          text,
    ativo         boolean not null default true,
    observacao    text
);

create table if not exists public.tb_gestora_margem (
    id_gestora_margem uuid    primary key default gen_random_uuid(),
    nome              text    not null,
    link_portal       text,
    ativo             boolean not null default true
);

-- --- Cadastros Estruturais · Classificação (Grupo) ----------------------
create table if not exists public.tb_grupo (
    id_grupo uuid    primary key default gen_random_uuid(),
    nome     text    not null,
    ativo    boolean not null default true
);

-- --- Cadastros Estruturais · Convênio -----------------------------------
create table if not exists public.tb_convenio (
    id_convenio       uuid        primary key default gen_random_uuid(),
    id_averbadora     uuid        references public.tb_averbadora (id_averbadora),
    id_gestora_margem uuid        references public.tb_gestora_margem (id_gestora_margem),
    cnpj              text        not null unique,
    nome              text        not null,
    status            text        not null default 'ATIVO'
        check (status in ('ATIVO', 'INATIVO')),
    status_producao   text
        check (status_producao is null or status_producao in
            ('Em produção', 'Em implantação', 'Suspenso', 'Encerrado')),
    ativo             boolean     not null default true,
    observacao        text,
    data_cadastro     timestamptz not null default now()
);
create index if not exists ix_convenio_averbadora on public.tb_convenio (id_averbadora);
create index if not exists ix_convenio_gestora on public.tb_convenio (id_gestora_margem);

-- Classificação N:N convênio ↔ grupo
create table if not exists public.tb_convenio_grupo (
    id_convenio_grupo uuid primary key default gen_random_uuid(),
    id_convenio       uuid not null references public.tb_convenio (id_convenio) on delete cascade,
    id_grupo          uuid not null references public.tb_grupo (id_grupo) on delete cascade,
    unique (id_convenio, id_grupo)
);

-- --- Vínculos e Custos · Vínculo (centro operacional) -------------------
create table if not exists public.tb_vinculo (
    id_vinculo              uuid    primary key default gen_random_uuid(),
    id_originadora          uuid    not null references public.tb_originadora (id_originadora),
    id_convenio             uuid    not null references public.tb_convenio (id_convenio),
    numero_convenio         text    not null,
    ativo                   boolean not null default true,
    data_competencia_inicio date,
    data_competencia_fim    date,
    observacao              text,
    unique (id_originadora, numero_convenio)
);
create index if not exists ix_vinculo_convenio on public.tb_vinculo (id_convenio);

-- --- Vínculos e Custos · Custo (versionado por vigência) ----------------
create table if not exists public.tb_custo (
    id_custo             uuid    primary key default gen_random_uuid(),
    id_vinculo           uuid    not null references public.tb_vinculo (id_vinculo) on delete cascade,
    metodo               text    not null
        check (metodo in ('PERCENTUAL', 'FIXO_MENSAL', 'POR_CONTRATO', 'FAIXA')),
    base_calculo         text
        check (base_calculo is null or base_calculo in
            ('VALOR_RETORNO', 'VALOR_REMESSA', 'VALOR_REPASSE')),
    aliquota_percentual  numeric(9, 4),
    valor_fixo           numeric(15, 2),
    valor_unitario       numeric(15, 2),
    data_vigencia_inicio date,
    data_vigencia_fim    date,
    ativo                boolean not null default true
);
create index if not exists ix_custo_vinculo on public.tb_custo (id_vinculo);

create table if not exists public.tb_custo_faixa (
    id_custo_faixa      uuid primary key default gen_random_uuid(),
    id_custo            uuid not null references public.tb_custo (id_custo) on delete cascade,
    valor_ate           numeric(15, 2),
    aliquota_percentual numeric(9, 4),
    valor_fixo          numeric(15, 2),
    valor_unitario      numeric(15, 2)
);
create index if not exists ix_custo_faixa_custo on public.tb_custo_faixa (id_custo);

-- Sem RLS (decisão do projeto).
alter table public.tb_originadora    disable row level security;
alter table public.tb_averbadora     disable row level security;
alter table public.tb_gestora_margem disable row level security;
alter table public.tb_grupo          disable row level security;
alter table public.tb_convenio       disable row level security;
alter table public.tb_convenio_grupo disable row level security;
alter table public.tb_vinculo        disable row level security;
alter table public.tb_custo          disable row level security;
alter table public.tb_custo_faixa    disable row level security;
