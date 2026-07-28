# DER — SCO Controle Operacional

Modelagem relacional proposta para migração do file-store atual (pasta = tabela,
subpasta = competência, um `.txt` JSON por registro) para **Supabase / PostgreSQL**.

> Versão para revisão. Renderização visual (light/dark) em [`der_sco.html`](der_sco.html).

## Diagrama

```mermaid
erDiagram
  originadora ||--o{ vinculo : opera
  convenio    ||--o{ vinculo : "assume numero"
  originadora ||--|| gerencia_originadora : "grupo master"
  convenio    ||--o{ convenio_grupo : classifica
  grupo       ||--o{ convenio_grupo : agrupa

  vinculo ||--|| gerencia_conciliacao : controla
  vinculo ||--o{ custo : cobra
  custo   ||--o{ custo_faixa : escalona
  vinculo ||--o{ vencimentario : gera
  vinculo ||--|| responsavel_convenio : "tem responsavel"
  vinculo ||--o{ secretaria : possui
  vinculo ||--o{ particularidade : possui
  vinculo ||--o{ conta : possui
  vinculo ||--o{ contato : possui
  vinculo ||--o{ cobranca_caso : origina

  vencimentario ||--o| remessa_envio : envia
  vencimentario ||--o{ repasse : recebe
  custo         ||--o{ repasse : "aplicado em"

  colaborador ||--o{ responsavel_convenio : "titular"
  colaborador ||--o{ responsavel_convenio : "substituto"
  responsavel_convenio ||--o{ responsavel_historico : audita

  cobranca_caso ||--o{ cobranca_tentativa : registra

  originadora {
    bigint id PK
    text nome UK
    text codigo UK
    text cnpj
    text status
    text observacao
    timestamptz criado_em
  }
  convenio {
    bigint id PK
    text cnpj UK
    text nome
    text averbadora
    text status
    text status_producao
    text gestora_margem
    text link_gestora
    text observacao
  }
  vinculo {
    bigint id PK
    bigint originadora_id FK
    bigint convenio_id FK
    text numero_convenio UK
    text status
    char competencia_inicio
    char competencia_fim
    text observacao
  }
  grupo {
    bigint id PK
    text nome UK
  }
  convenio_grupo {
    bigint convenio_id FK
    bigint grupo_id FK
  }
  custo {
    bigint id PK
    bigint vinculo_id FK
    text metodo
    text base_calculo
    numeric aliquota_percentual
    numeric valor_fixo
    numeric valor_unitario
    char competencia_inicio
    char competencia_fim
    text status
  }
  custo_faixa {
    bigint id PK
    bigint custo_id FK
    numeric ate
    numeric aliquota_percentual
    numeric valor_fixo
    numeric valor_unitario
  }
  gerencia_conciliacao {
    bigint id PK
    bigint vinculo_id FK
    boolean em_conciliacao_ativa
    int dia_vencimento
    int dias_antes_remessa
    int qtd_dias_sla_pagamento
    int dias_antes_corte
    text ator
  }
  gerencia_originadora {
    bigint id PK
    bigint originadora_id FK
    boolean em_conciliacao_ativa
    text ator
  }
  vencimentario {
    bigint id PK
    bigint vinculo_id FK
    char competencia
    date data_vencimento
    date data_env_remessa
    date data_sla_conciliacao
    date data_corte
    numeric valor_remessa
    numeric valor_retorno
    numeric valor_repasse
    text status_conciliacao
    text motivo_falta_conciliacao
    numeric porcentagem_inadimplencia
  }
  remessa_envio {
    bigint id PK
    bigint vencimentario_id FK
    text situacao
    date data_envio
    text usuario
    text observacao
  }
  repasse {
    bigint id PK
    bigint vencimentario_id FK
    bigint custo_id FK
    text secretaria
    text status_financeiro
    date data_recebimento
    numeric valor_recebido
    int quantidade
    numeric custo_aplicado
    numeric devendo
    text observacao
  }
  colaborador {
    bigint id PK
    text nome UK
    text status
    text observacao
  }
  responsavel_convenio {
    bigint id PK
    bigint vinculo_id FK
    bigint titular_id FK
    bigint substituto_id FK
    date substituicao_fim
    text ator
  }
  responsavel_historico {
    bigint id PK
    bigint responsavel_id FK
    text acao
    text de
    text para
    text ator
    timestamptz em
  }
  secretaria {
    bigint id PK
    bigint vinculo_id FK
    text status
    text nome
    text codigo
    text observacao
  }
  particularidade {
    bigint id PK
    bigint vinculo_id FK
    text status
    text rubrica_produto
    text modelo_averbacao
    text modelo_envio
    text observacao
  }
  conta {
    bigint id PK
    bigint vinculo_id FK
    text status
    text banco
    text agencia
    text conta
    text chave_pix
    text cnpj
  }
  contato {
    bigint id PK
    bigint vinculo_id FK
    text status
    text secretaria
    text nome
    text email
    text telefone
    text area
  }
  cobranca_caso {
    bigint id PK
    bigint vinculo_id FK
    char competencia
    numeric valor
    text status
  }
  cobranca_tentativa {
    bigint id PK
    bigint cobranca_caso_id FK
    date data
    text canal
    text resultado
  }
  usuario {
    bigint id PK
    text email UK
    text nome
    text perfil
    text senha_hash
    boolean ativo
  }
```

## Domínios

| Domínio | Tabelas |
|---|---|
| **Gestão de Convênios** | `originadora`, `convenio`, `vinculo`, `grupo`, `convenio_grupo`, `custo`, `custo_faixa` |
| **Conciliação / Gerência** | `gerencia_conciliacao`, `gerencia_originadora`, `vencimentario`, `remessa_envio` |
| **Responsáveis** | `colaborador`, `responsavel_convenio`, `responsavel_historico` |
| **Financeiro** | `repasse` |
| **Analítico (abas do convênio)** | `secretaria`, `particularidade`, `conta`, `contato` |
| **Cobrança** | `cobranca_caso`, `cobranca_tentativa` |
| **Sistema** | `usuario` + indicadores como `VIEW` |

## Decisões de modelagem

- **Chave técnica + chave natural** — toda tabela tem `id bigint identity` como PK; as
  chaves imutáveis do domínio (CNPJ, nome, numero_convenio) viram `UNIQUE`. FKs referenciam
  o `id`, não o texto, permitindo correção sem quebrar vínculos.
- **O `vinculo` é o centro** — convênio × originadora. Conciliação, custo, responsável,
  remessa, financeiro e abas do analítico penduram no vínculo, não no convênio mestre.
- **Competência como `char(7)` AAAA-MM** — espelha o file-store e ordena lexicograficamente.
  (Alternativa: `date` truncado ao 1º dia — a decidir.)
- **Custo versionado, não sobrescrito** — `custo` guarda histórico por vigência + `status`
  ATIVO/INATIVO; `custo_faixa` só no método FAIXA. O custo vigente é calculado por competência.
- **Financeiro registra o custo aplicado** — `repasse.custo_id` + `custo_aplicado` + `devendo`
  gravam o snapshot auditável; `status_financeiro` é definido pelo backend.
- **Status independentes** — Gestão (`convenio.status`) e Conciliação
  (`gerencia_conciliacao.em_conciliacao_ativa`) em tabelas distintas: coexistem, não se influenciam.
- **Auditoria em toda tabela mutável** — `criado_em` / `atualizado_em` (`timestamptz`) e `ator`;
  histórico de responsável em `responsavel_historico`.
- **Indicadores = VIEW** — indicadores de conciliação (mês/quadrimestre/ano) não são tabela:
  `VIEW` (ou materialized view) agregando `vencimentario`. Zero duplicação de dado.

## Pontos a decidir antes do DDL

1. **Competência**: manter `char(7)` AAAA-MM ou migrar para `date` (1º dia do mês)?
2. **Remessa**: `remessa_envio` 1:1 com o vencimentário ou 1:N (histórico de reenvio)?
3. **Modelo de envio** (particularidade, múltiplo): normalizar em `particularidade_envio` (N:N)
   ou manter como array/texto?
4. **Grupo master**: a originadora já agrupa convênios via `vinculo`; `grupo`/`convenio_grupo`
   é 2ª dimensão de agrupamento — confirmar necessidade.
5. **Usuários**: usar `auth.users` nativo do Supabase (uuid) ou tabela própria com `senha_hash`?
6. **Enums**: `ENUM` nativo do Postgres ou `text` + CHECK constraint?
