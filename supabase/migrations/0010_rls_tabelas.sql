-- ============================================================
-- SCO · Fase 1 — RLS das tabelas de negócio (acesso direto pela página)
--
-- Com o front falando direto com o banco, a RLS é a ÚNICA trava. Regra:
--   • LER: qualquer usuário LOGADO (authenticated).
--   • GRAVAR/APAGAR: só ADMIN, MASTER ou GESTOR (via public.meu_perfil()).
--   • Deslogado (anon): nada.
--
-- Depende de: 0009 (função public.meu_perfil()). Idempotente.
-- ============================================================

do $$
declare
    t text;
    tabelas text[] := array[
        -- Gestão de Convênios (0002)
        'tb_originadora', 'tb_averbadora', 'tb_gestora_margem', 'tb_grupo',
        'tb_convenio', 'tb_convenio_grupo', 'tb_vinculo', 'tb_custo',
        'tb_custo_faixa',
        -- Conciliação (0003)
        'tb_banco', 'tb_modelo_averbacao', 'tb_modelo_envio', 'tb_colaborador',
        'tb_gerencia_originadora', 'tb_gerencia_conciliacao', 'tb_vencimentario',
        'tb_secretaria', 'tb_remessa_envio', 'tb_repasse', 'tb_contato',
        'tb_particularidade', 'tb_particularidade_modelo_envio', 'tb_conta',
        'tb_responsavel_convenio', 'tb_responsavel_historico',
        -- Cobrança (0004)
        'tb_cobranca_caso', 'tb_cobranca_tentativa',
        -- Segurança / apoio (0006, 0007)
        'tb_equipe', 'tb_solicitacao_acesso', 'tb_email_autorizador'
    ];
begin
    foreach t in array tabelas loop
        -- Pula tabelas que não existirem neste banco (evita erro no bloco).
        if exists (
            select 1 from information_schema.tables
            where table_schema = 'public' and table_name = t
        ) then
            execute format('alter table public.%I enable row level security', t);

            -- Leitura: qualquer logado.
            execute format('drop policy if exists %I on public.%I', t || '_rls_sel', t);
            execute format(
                'create policy %I on public.%I for select to authenticated using (true)',
                t || '_rls_sel', t
            );

            -- Escrita: só ADMIN/MASTER/GESTOR.
            execute format('drop policy if exists %I on public.%I', t || '_rls_wr', t);
            execute format(
                $f$create policy %I on public.%I for all to authenticated
                   using (public.meu_perfil() = any (array['ADMIN', 'MASTER', 'GESTOR']))
                   with check (public.meu_perfil() = any (array['ADMIN', 'MASTER', 'GESTOR']))$f$,
                t || '_rls_wr', t
            );
        end if;
    end loop;
end $$;

-- tb_usuario (custom, legado do login antigo) guarda senha_hash: RLS ligada
-- e SEM política = ninguém lê/escreve via página. Só SQL Editor/service_role.
do $$
begin
    if exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'tb_usuario'
    ) then
        execute 'alter table public.tb_usuario enable row level security';
        execute 'drop policy if exists tb_usuario_rls_sel on public.tb_usuario';
        execute 'drop policy if exists tb_usuario_rls_wr on public.tb_usuario';
    end if;
end $$;
