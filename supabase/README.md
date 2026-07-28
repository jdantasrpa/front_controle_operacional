# SCO — Estrutura Supabase (modular por contexto de negócio)

Migrations geradas a partir do DER-MCN (`docs/der_mcn_sco.drawio`). A
modelagem é **relacional, normalizada, sem RLS** (decisão do projeto) e
organizada em módulos, na mesma divisão do DER.

## Ordem de execução (as FKs cruzam módulos)

| # | Arquivo | Módulo | Tabelas |
|---|---------|--------|---------|
| 1 | `0001_seguranca.sql` | Segurança | `tb_usuario` |
| 2 | `0002_gestao_convenios.sql` | Gestão de Convênios | `tb_originadora`, `tb_averbadora`, `tb_gestora_margem`, `tb_grupo`, `tb_convenio`, `tb_convenio_grupo`, `tb_vinculo`, `tb_custo`, `tb_custo_faixa` |
| 3 | `0003_conciliacao.sql` | Conciliação | `tb_banco`, `tb_modelo_averbacao`, `tb_modelo_envio`, `tb_colaborador`, `tb_gerencia_originadora`, `tb_gerencia_conciliacao`, `tb_vencimentario`, `tb_secretaria`, `tb_remessa_envio`, `tb_repasse`, `tb_contato`, `tb_particularidade`, `tb_particularidade_modelo_envio`, `tb_conta`, `tb_responsavel_convenio`, `tb_responsavel_historico` |
| 4 | `0004_cobranca.sql` | Cobrança | `tb_cobranca_caso`, `tb_cobranca_tentativa` |
| 5 | `0005_seed_lookups.sql` | (seed) | modelos de averbação e envio |

**A ordem importa**: `tb_vinculo` (Gestão) é o centro operacional e é
referenciado por quase toda a Conciliação e pela Cobrança; `tb_usuario`
(Segurança) é referenciado pela Remessa. Rode 0001 → 0005 em sequência.

## Como aplicar

**Opção A — SQL Editor do Supabase:** cole o conteúdo de cada arquivo, na
ordem, e execute.

**Opção B — Supabase CLI:**

```bash
supabase db push
```

(os arquivos já estão em `supabase/migrations/` no padrão da CLI.)

## Conta admin

O schema não semeia usuários. Gere o admin com senha aleatória:

```bash
python scripts/criar_admin.py
```

O script imprime a senha uma única vez e o `INSERT`. Ajuste o `INSERT`
para a tabela `public.tb_usuario` (colunas `nome`, `email`, `perfil`,
`senha_hash`) antes de colar no Supabase — o hash PBKDF2 é o mesmo.

## Convenções

- **PK**: `uuid` com `gen_random_uuid()` (extensão `pgcrypto`).
- **FK**: `id_<tabela>`, com `on delete cascade` nos filhos fracos.
- **Prefixo `data_`**: datas de negócio são `date`; carimbos de auditoria
  (`data_cadastro`, `data_alteracao`, `data_evento`) são `timestamptz`.
- **`ativo`**: booleano. **Valores**: `numeric(15,2)`; percentuais
  `numeric(9,4)`.
- **CHECKs** aplicados só nos domínios estáveis (`custo.metodo`,
  `custo.base_calculo`, `convenio.status`, `convenio.status_producao`,
  `vencimentario.status_conciliacao`, `usuario.perfil`). Os demais status
  ficam como `text` para não travar a operação enquanto as listas evoluem.

## Próximo passo (aplicação)

Ligar a persistência do painel a este schema exige uma camada de
repositório (`RepositorioSupabase`) atrás da interface já discutida, para
os módulos escreverem no Supabase em vez do store local/arquivos.
