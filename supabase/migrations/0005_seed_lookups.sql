-- ============================================================
-- SCO · Seed de lookups (idempotente) — valores em uso hoje no front.
-- Roda por último. Não semeia dados de negócio, só as listas de apoio.
-- ============================================================

insert into public.tb_modelo_averbacao (nome)
select v.nome
from (values ('Parcelado'), ('Arquivo'), ('Não Atuamos'), ('sem acesso')) as v(nome)
where not exists (
    select 1 from public.tb_modelo_averbacao m where m.nome = v.nome
);

insert into public.tb_modelo_envio (nome)
select v.nome
from (values ('Parcelado'), ('Arquivo')) as v(nome)
where not exists (
    select 1 from public.tb_modelo_envio m where m.nome = v.nome
);
