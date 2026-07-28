-- ============================================================
-- SCO · Seed de demonstração (mock) — a "nova cara" do painel lê estes
-- dados do Supabase no lugar do SEED que ficava embutido no front (data.js).
--
-- Idempotente (on conflict do nothing): pode rodar mais de uma vez.
-- Espelha a originadora Alvo Card e os 6 convênios de exemplo do demo.
-- Depende de: 0002_gestao_convenios.sql.
-- ============================================================

-- --- Originadora (grupo master) -----------------------------------------
insert into public.tb_originadora (nome, codigo, ativo)
values ('Alvo Card', 'ALV', true)
on conflict (nome) do nothing;

-- --- Convênios (chave natural = CNPJ) -----------------------------------
insert into public.tb_convenio (cnpj, nome, status, status_producao, ativo) values
  ('00.394.429/0082-76', 'AERONÁUTICA',            'ATIVO', 'Em produção', true),
  ('02.476.034/0001-82', 'GOV. GOIÁS',             'ATIVO', 'Em produção', true),
  ('12.200.184/0001-12', 'GOV. ALAGOAS',           'ATIVO', 'Em produção', true),
  ('03.929.049/0001-11', 'ASSEMBLEIA MATO GROSSO', 'ATIVO', 'Em implantação', true),
  ('01.612.092/0001-23', 'PREF. GOIÂNIA',          'ATIVO', 'Em produção', true),
  ('02.938.150/0001-90', 'TJ GOIÁS',               'ATIVO', 'Em produção', true)
on conflict (cnpj) do nothing;

-- --- Vínculos (Alvo Card opera cada convênio; nº = seq + código) --------
insert into public.tb_vinculo
    (id_originadora, id_convenio, numero_convenio, ativo, data_competencia_inicio)
select o.id_originadora, c.id_convenio, v.numero, true, date '2025-01-01'
from (values
    ('00.394.429/0082-76', '00001ALV'),
    ('02.476.034/0001-82', '00011ALV'),
    ('12.200.184/0001-12', '00021ALV'),
    ('03.929.049/0001-11', '00031ALV'),
    ('01.612.092/0001-23', '00041ALV'),
    ('02.938.150/0001-90', '00051ALV')
) as v (cnpj, numero)
join public.tb_convenio c on c.cnpj = v.cnpj
cross join public.tb_originadora o
where o.nome = 'Alvo Card'
on conflict (id_originadora, numero_convenio) do nothing;

-- --- Estado da mesa: liga a conciliação da originadora e de cada vínculo -
insert into public.tb_gerencia_originadora (id_originadora, em_conciliacao)
select id_originadora, true from public.tb_originadora where nome = 'Alvo Card'
on conflict (id_originadora) do nothing;

insert into public.tb_gerencia_conciliacao (id_vinculo, em_conciliacao, dia_vencimento)
select id_vinculo, true, 5 from public.tb_vinculo
on conflict (id_vinculo) do nothing;
