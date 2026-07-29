-- ============================================================
-- SCO · Aprovação de acesso ("qual login pode acessar ou não")
--
-- Todo cadastro nasce PENDENTE (aprovado = false). Enquanto não aprovado:
--   • não passa no login (bloqueio no front) E
--   • a RLS não deixa ler/gravar nada (meu_perfil() vira NULL).
-- Um ADMIN aprova (aprovado = true) — pela tela ou por SQL.
--
-- Depende de: 0009, 0010. Idempotente.
--
-- ⚠️ Se você já criou o admin, reaprove ele depois desta migration:
--   update public.usuario_perfil set perfil='ADMIN', aprovado=true
--    where id = (select id from auth.users where email='SEU-EMAIL');
-- ============================================================

alter table public.usuario_perfil
    add column if not exists email text;
alter table public.usuario_perfil
    add column if not exists aprovado boolean not null default false;

-- O perfil passa a guardar o e-mail e nascer NÃO aprovado.
create or replace function public.criar_perfil_no_signup()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.usuario_perfil (id, email, nome, aprovado)
    values (
        new.id,
        new.email,
        coalesce(new.raw_user_meta_data ->> 'nome', new.email),
        false
    )
    on conflict (id) do update set email = excluded.email;
    return new;
end;
$$;

-- meu_perfil() só devolve o perfil se o usuário estiver APROVADO — assim as
-- políticas de escrita (0010) já bloqueiam pendente automaticamente.
create or replace function public.meu_perfil()
returns text
language sql
stable
security definer
set search_path = public
as $$
    select perfil from public.usuario_perfil
    where id = auth.uid() and aprovado = true;
$$;

-- A leitura das tabelas de negócio passa a exigir aprovação.
do $$
declare
    t text;
    tabelas text[] := array[
        'tb_originadora', 'tb_averbadora', 'tb_gestora_margem', 'tb_grupo',
        'tb_convenio', 'tb_convenio_grupo', 'tb_vinculo', 'tb_custo',
        'tb_custo_faixa', 'tb_banco', 'tb_modelo_averbacao', 'tb_modelo_envio',
        'tb_colaborador', 'tb_gerencia_originadora', 'tb_gerencia_conciliacao',
        'tb_vencimentario', 'tb_secretaria', 'tb_remessa_envio', 'tb_repasse',
        'tb_contato', 'tb_particularidade', 'tb_particularidade_modelo_envio',
        'tb_conta', 'tb_responsavel_convenio', 'tb_responsavel_historico',
        'tb_cobranca_caso', 'tb_cobranca_tentativa', 'tb_equipe',
        'tb_solicitacao_acesso', 'tb_email_autorizador'
    ];
begin
    foreach t in array tabelas loop
        if exists (
            select 1 from information_schema.tables
            where table_schema = 'public' and table_name = t
        ) then
            execute format('drop policy if exists %I on public.%I', t || '_rls_sel', t);
            execute format(
                'create policy %I on public.%I for select to authenticated using (public.meu_perfil() is not null)',
                t || '_rls_sel', t
            );
        end if;
    end loop;
end $$;
