-- ============================================================
-- SCO · Módulo: Conciliação  (DER-MCN)
-- Submódulos: Gerência de Convênios · Controle Analítico ·
--             Responsáveis pela Conciliação
-- Depende de: 0001_seguranca.sql, 0002_gestao_convenios.sql. Sem RLS.
-- ============================================================

-- --- Tabelas de apoio (independentes) -----------------------------------
create table if not exists public.tb_banco (
    id_banco     uuid primary key default gen_random_uuid(),
    codigo_compe text,
    nome         text not null
);

create table if not exists public.tb_modelo_averbacao (
    id_modelo_averbacao uuid    primary key default gen_random_uuid(),
    nome                text    not null,
    ativo               boolean not null default true
);

create table if not exists public.tb_modelo_envio (
    id_modelo_envio uuid    primary key default gen_random_uuid(),
    nome            text    not null,
    ativo           boolean not null default true
);

create table if not exists public.tb_colaborador (
    id_colaborador uuid    primary key default gen_random_uuid(),
    nome           text    not null,
    ativo          boolean not null default true,
    observacao     text
);

-- --- Gerência de Convênios ----------------------------------------------
-- 1:1 com originadora — liga/desliga a conciliação da originadora inteira.
create table if not exists public.tb_gerencia_originadora (
    id_gerencia_originadora uuid        primary key default gen_random_uuid(),
    id_originadora          uuid        not null unique references public.tb_originadora (id_originadora) on delete cascade,
    em_conciliacao          boolean     not null default true,
    data_alteracao          timestamptz not null default now(),
    ator                    text
);

-- 1:1 com vínculo — parametriza o ciclo de vencimento do convênio.
create table if not exists public.tb_gerencia_conciliacao (
    id_gerencia_conciliacao uuid        primary key default gen_random_uuid(),
    id_vinculo              uuid        not null unique references public.tb_vinculo (id_vinculo) on delete cascade,
    em_conciliacao          boolean     not null default true,
    dia_vencimento          integer,
    dias_antes_remessa      integer,
    qtd_dias_sla_pagamento  integer,
    dias_antes_corte        integer,
    data_alteracao          timestamptz not null default now(),
    ator                    text
);

-- --- Controle Analítico · Vencimentário (competência por vínculo) -------
create table if not exists public.tb_vencimentario (
    id_vencimentario         uuid        primary key default gen_random_uuid(),
    id_vinculo               uuid        not null references public.tb_vinculo (id_vinculo) on delete cascade,
    competencia              text        not null,
    data_vencimento          date,
    data_envio_remessa       date,
    data_sla_conciliacao     date,
    data_corte               date,
    valor_remessa            numeric(15, 2),
    valor_retorno            numeric(15, 2),
    valor_repasse            numeric(15, 2),
    status_conciliacao       text
        check (status_conciliacao is null or status_conciliacao in
            ('CONCILIADO', 'CONCILIADO (PARCIAL)', 'PENDENTE')),
    motivo_falta_conciliacao text,
    percentual_inadimplencia numeric(9, 4),
    data_cadastro            timestamptz not null default now(),
    unique (id_vinculo, competencia, data_vencimento)
);
create index if not exists ix_vencimentario_vinculo on public.tb_vencimentario (id_vinculo);

-- --- Controle Analítico · Secretaria (pagadoras do vínculo) -------------
create table if not exists public.tb_secretaria (
    id_secretaria uuid    primary key default gen_random_uuid(),
    id_vinculo    uuid    not null references public.tb_vinculo (id_vinculo) on delete cascade,
    nome          text    not null,
    codigo        text,
    ativo         boolean not null default true,
    observacao    text
);
create index if not exists ix_secretaria_vinculo on public.tb_secretaria (id_vinculo);

-- --- Controle Analítico · Remessa (envio por vencimento) ----------------
create table if not exists public.tb_remessa_envio (
    id_remessa_envio uuid primary key default gen_random_uuid(),
    id_vencimentario uuid not null unique references public.tb_vencimentario (id_vencimentario) on delete cascade,
    id_usuario       uuid references public.tb_usuario (id_usuario),
    situacao         text,
    data_envio       date,
    observacao       text
);
create index if not exists ix_remessa_envio_usuario on public.tb_remessa_envio (id_usuario);

-- --- Controle Analítico · Repasse (financeiro por secretaria) -----------
create table if not exists public.tb_repasse (
    id_repasse           uuid primary key default gen_random_uuid(),
    id_vencimentario     uuid not null references public.tb_vencimentario (id_vencimentario) on delete cascade,
    id_secretaria        uuid references public.tb_secretaria (id_secretaria),
    id_custo             uuid references public.tb_custo (id_custo),
    status_financeiro    text,
    data_recebimento     date,
    valor_recebido       numeric(15, 2),
    quantidade           integer,
    valor_custo_aplicado numeric(15, 2),
    valor_devendo        numeric(15, 2),
    observacao           text
);
create index if not exists ix_repasse_vencimentario on public.tb_repasse (id_vencimentario);
create index if not exists ix_repasse_secretaria on public.tb_repasse (id_secretaria);

-- --- Controle Analítico · Contato ---------------------------------------
create table if not exists public.tb_contato (
    id_contato    uuid    primary key default gen_random_uuid(),
    id_vinculo    uuid    not null references public.tb_vinculo (id_vinculo) on delete cascade,
    id_secretaria uuid    references public.tb_secretaria (id_secretaria),
    nome          text    not null,
    email         text,
    telefone      text,
    area          text,
    ativo         boolean not null default true
);
create index if not exists ix_contato_vinculo on public.tb_contato (id_vinculo);

-- --- Controle Analítico · Particularidade (rubrica + modelos, N:N) ------
create table if not exists public.tb_particularidade (
    id_particularidade  uuid    primary key default gen_random_uuid(),
    id_vinculo          uuid    not null references public.tb_vinculo (id_vinculo) on delete cascade,
    id_modelo_averbacao uuid    references public.tb_modelo_averbacao (id_modelo_averbacao),
    rubrica_produto     text,
    ativo               boolean not null default true,
    observacao          text
);
create index if not exists ix_particularidade_vinculo on public.tb_particularidade (id_vinculo);

create table if not exists public.tb_particularidade_modelo_envio (
    id_particularidade_modelo_envio uuid primary key default gen_random_uuid(),
    id_particularidade              uuid not null references public.tb_particularidade (id_particularidade) on delete cascade,
    id_modelo_envio                 uuid not null references public.tb_modelo_envio (id_modelo_envio) on delete cascade,
    unique (id_particularidade, id_modelo_envio)
);

-- --- Controle Analítico · Conta bancária --------------------------------
create table if not exists public.tb_conta (
    id_conta      uuid    primary key default gen_random_uuid(),
    id_vinculo    uuid    not null references public.tb_vinculo (id_vinculo) on delete cascade,
    id_banco      uuid    references public.tb_banco (id_banco),
    agencia       text,
    numero_conta  text,
    chave_pix     text,
    cnpj          text,
    ativo         boolean not null default true
);
create index if not exists ix_conta_vinculo on public.tb_conta (id_vinculo);

-- --- Responsáveis pela Conciliação --------------------------------------
-- 1:1 com vínculo; titular e substituto apontam para colaboradores.
create table if not exists public.tb_responsavel_convenio (
    id_responsavel_convenio  uuid        primary key default gen_random_uuid(),
    id_vinculo               uuid        not null unique references public.tb_vinculo (id_vinculo) on delete cascade,
    id_colaborador_titular   uuid        references public.tb_colaborador (id_colaborador),
    id_colaborador_substituto uuid       references public.tb_colaborador (id_colaborador),
    data_fim_substituicao    date,
    data_alteracao           timestamptz not null default now(),
    ator                     text
);

create table if not exists public.tb_responsavel_historico (
    id_responsavel_historico uuid        primary key default gen_random_uuid(),
    id_responsavel_convenio  uuid        not null references public.tb_responsavel_convenio (id_responsavel_convenio) on delete cascade,
    acao                     text,
    valor_de                 text,
    valor_para               text,
    ator                     text,
    data_evento              timestamptz not null default now()
);
create index if not exists ix_resp_hist_convenio on public.tb_responsavel_historico (id_responsavel_convenio);

-- Sem RLS (decisão do projeto).
alter table public.tb_banco                       disable row level security;
alter table public.tb_modelo_averbacao            disable row level security;
alter table public.tb_modelo_envio                disable row level security;
alter table public.tb_colaborador                 disable row level security;
alter table public.tb_gerencia_originadora        disable row level security;
alter table public.tb_gerencia_conciliacao        disable row level security;
alter table public.tb_vencimentario               disable row level security;
alter table public.tb_secretaria                  disable row level security;
alter table public.tb_remessa_envio               disable row level security;
alter table public.tb_repasse                     disable row level security;
alter table public.tb_contato                     disable row level security;
alter table public.tb_particularidade             disable row level security;
alter table public.tb_particularidade_modelo_envio disable row level security;
alter table public.tb_conta                       disable row level security;
alter table public.tb_responsavel_convenio        disable row level security;
alter table public.tb_responsavel_historico       disable row level security;
