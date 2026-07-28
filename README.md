# Front Controle Operacional

Painel operacional de conciliação e cobrança (Alvo Card), em janela
nativa (pywebview), servido por uma API FastAPI que lê um **banco em
árvore de arquivos**.

```bash
python app_desktop.py
```

## Banco em árvore de arquivos

Não há mais `.db` no caminho do painel: pasta é tabela, subpasta é
competência, e cada convênio tem um `.txt` com seus registros em JSON.

```
banco/DADOS/
├── tabela_concilicacao_convenio/     <- tem competência
│   ├── 2026-07/
│   │   ├── alvo_card__00011ALV.txt
│   │   └── hatchbank__00061HTC.txt
│   └── 2026-06/
├── gestao_convenios_originador/      <- não tem competência
├── tabela_contato/
├── tabela_conta_conv/
├── tabela_particularidade/
└── tabela_secretaria_conv/
```

O nome do arquivo carrega a originadora porque a identidade do convênio
é o par `(originador, numero_convenio)`.

Duas garantias que arquivo solto não dá de graça, implementadas em
[`api/arquivos.py`](api/arquivos.py):

- **Gravação atômica** — escreve em `.tmp` e renomeia. Ninguém lê arquivo
  pela metade, mesmo se o processo morrer no meio.
- **Versão otimista** — quem grava informa a versão que leu; se o arquivo
  mudou nesse meio tempo, a gravação é recusada. Sem isso, dois
  operadores no mesmo convênio se sobrescrevem em silêncio.

Migrar de um `.db` existente:

```bash
python scripts/migrar_para_arquivos.py --origem doc/amostra_2anos.db
```

> O SQLite continua sendo lido por `/api/retorno`, `/api/contatos` e
> `/api/cobranca/*` — rotas do painel antigo, que nenhuma tela usa hoje.

## O que faz

O painel em `front/` (HTML/CSS/JS) reproduz o fluxo do Gradio —
`Módulos → Conciliação → Controle Sintético → Controle Analítico` — com
store local (`localStorage`, `front/js/data.js`) para demonstração.

No **Controle Analítico**, o convênio abre com um **dashboard de
vencimentários**: uma linha por ciclo de vencimento, no formato do
Sintético, e o clique na linha troca o vencimentário de trabalho.

| Aba | Escopo | Regra |
|---|---|---|
| Conciliação | vencimentário | `Valor repasse` é **somente leitura**: soma o `valor repassado` do Financeiro. `Valor pendente` = retorno − repasse |
| Particularidade | convênio | rubrica, averbação e retenção (telefone vive na aba Contato) |
| Financeiro | vencimentário | cada lançamento aponta a **secretaria** repassada |
| Conta | convênio | dados bancários |
| Secretaria | convênio | secretarias do convênio; ATIVA sem repasse no Financeiro aparece como **devedora** na Conciliação |
| Contato | convênio | um contato por secretaria, ou `Todas as secretarias` para quem responde por todas |
| Cobrança | vencimentário | só o **histórico de tentativas da competência** aberta, mais o registro de nova tentativa |

> As telas de **Extrato** (Ranking, Evolução) e o painel antigo (Home,
> Importar Dados, Retorno BPO, Cobrança PJ) foram removidos do front.

### Dois modos de operação

O painel decide o modo na abertura, chamando `/api/analitico/filtros`:

| Modo | Quando | O que faz |
|---|---|---|
| **Dados reais** | API no ar | Lê Sintético e Analítico do COFCT. **Somente leitura** — botões de salvar desabilitados |
| **Demonstração** | sem servidor (`file://`) ou API fora | Store local em `localStorage` com dados de exemplo, leitura **e** escrita |

A faixa no topo da tela diz em qual modo o painel está.

### Integração com a API — onde parou

- **Etapa 1 (feita)** — leitura: filtros, Sintético e Analítico
  (vencimentários de todas as competências + particularidade, conta e
  contato) vêm de `tabela_concilicacao_convenio` e das tabelas do COFCT.
  Cada linha da conciliação é um vencimentário.
- **Etapa 2 (pendente)** — schema: não existe tabela de **secretaria**;
  faltam `qtd_contratos`, `cenario_conciliacao`, `conciliado` e
  `observacao` na conciliação, e as colunas `secretaria` e
  `dia_vencimento` em `tabela_financeiro_repasse` (mais `secretaria` em
  `tabela_contato`).

  O painel já grava o repasse com `mes_referencia` e `dia_vencimento`
  carimbados do vencimentário aberto — o operador não digita competência
  no Financeiro. Falta o destino aceitar esses dois campos; sem
  `dia_vencimento` não dá para separar dois vencimentários do mesmo mês.
- **Etapa 3 (pendente)** — escrita: no COFCT ela passa pela fila de
  comandos (ver `main.py`), não por SQL direto da API.

## Fluxo Gradio (`main.py`)

Aplicação independente do painel web, com fila de comandos e auditoria:

```
Módulos → Conciliação → Controle Sintético → Controle Analítico
```

**Controle Sintético** — o controle é mensal por originadora: `Mês
(referência)` e `Originadora` são **obrigatórios** e vêm do próprio
snapshot (dropdowns). Sem os dois não há listagem.

**Controle Analítico** — página do convênio, com 6 abas:

| # | Aba | Fonte | Escrita |
|---|---|---|---|
| 1 | Conciliação | `tabela_concilicacao_convenio` | fila |
| 2 | Particularidade | `tabela_particularidade` | fila |
| 3 | Financeiro | `tabela_financeiro_repasse` | fila |
| 4 | Conta | `tabela_conta_conv` | fila |
| 5 | Contato | `tabela_contato` | fila |
| 6 | Cobrança | `tabela_cobranca_caso` / `_tentativa` | fila |

A aba **Cobrança** tem as duas partes: **histórico** (casos + tentativas
já registradas) e **registro**, em que o operador escolhe o contato
acionado a partir dos contatos ATIVOS cadastrados na aba Contato.

### ⚠️ Fila: chave `banco_destino`

Financeiro e Cobrança vivem em `bd_cobranca_financeiro.db`, não no COFCT.
Por isso os comandos dessas abas trazem uma chave a mais no payload:

```json
{ "metodo": "INSERT_COBRANCA_CASO", "banco_destino": "cobranca_financeiro", ... }
```

**O writer precisa ler `banco_destino`** e abrir o banco correspondente
(`cofct` = comportamento atual, é o default para todos os comandos
antigos). Sem esse ajuste no writer, os comandos de Financeiro/Cobrança
falharão ao serem aplicados, porque as tabelas não existem no COFCT.

O registro de cobrança gera 3 comandos encadeados: cria o caso
(`INSERT OR IGNORE`, idempotente pela UNIQUE), atualiza status/valor e
insere a tentativa — esta resolve o `id_caso` por subquery, já que na
fila o id ainda não existe no momento da gravação.

### Configuração alternativa

A variável de ambiente `COFC_CONFIG` aponta outro `.ini` sem editar o do
projeto (homologação, testes). Vale para `main.py` e para a API.

## Como usar

1. `PrepararAmbiente.bat` — cria o venv e instala o `requirements.txt`
2. `IniciarPainel.bat` — sobe o servidor e abre o navegador

Por padrão em <http://127.0.0.1:8000>.

## Amostra de dados

`scripts/gerar_amostra.py` cria um banco no schema real do COFCT com
**24 competências** (2 anos até o mês corrente), 8 convênios em duas
originadoras e 1–2 vencimentários por competência — com repasses
integrais, parciais e pendentes distribuídos de forma realista:

```bash
python scripts/gerar_amostra.py
```

Gera `doc/amostra_2anos.db` (264 vencimentários). A geração é
determinística: mesma semente, mesmo banco. Para usar no painel, aponte
`banco_conciliacao` para ele. O mock `doc/convenios_mock_layout.db`, que
os testes usam, não é tocado.

## Configuração

Seção `[FRONT]` do `config_projeto.ini`:

```ini
[FRONT]
pasta_banco = banco/DADOS
banco_conciliacao = doc/convenios_mock_layout.db
banco_cobranca = banco/COBRANCA_FINANCEIRO/bd_cobranca_financeiro.db
host = 127.0.0.1
porta = 8000
```

`pasta_banco` é a raiz do banco de arquivos — é ela que o painel usa.
Se a porta estiver ocupada, `app_desktop.py` escolhe outra livre em vez
de falhar, então duas janelas abertas não brigam entre si.

Caminhos relativos partem da raiz do projeto; absolutos e UNC também
funcionam. Para apontar ao COFCT de rede, use o caminho completo do `.db`
que está em `[DIRETORIOS] pasta_db`.

## Estrutura

```
app_desktop.py                 # janela nativa (pywebview) + FastAPI embutido
api/
├── arquivos.py                # banco em árvore de arquivos (atômico + versão)
├── config.py                  # leitura do .ini e resolução de caminhos
├── database.py                # conexões SQLite (rotas legadas)
├── domain.py                  # regras puras banco -> contrato do front
├── schemas.py                 # validação Pydantic dos payloads
├── repositories/
│   ├── analitico.py           # Sintético e Analítico sobre os arquivos
│   ├── conciliacao.py         # SELECT no SQLite (rotas legadas)
│   └── cobranca.py            # CRUD dos casos de cobrança (legado)
└── app.py                     # rotas FastAPI + serve o front/
banco/DADOS/                   # o banco: pasta = tabela, subpasta = competência
front/                         # painel (HTML/CSS/JS)
scripts/
├── gerar_amostra.py           # amostra de 2 anos no schema do COFCT
└── migrar_para_arquivos.py    # SQLite -> árvore de arquivos
serve.py                       # ponto de entrada só do servidor (sem janela)
tests/                         # pytest
```

## Endpoints

```
GET    /api/status
GET    /api/analitico/filtros
GET    /api/analitico/sintetico?competencia=MM/AAAA&originador=
GET    /api/analitico/convenio?originador=&numero_convenio=
GET    /api/retorno
GET    /api/contatos
GET    /api/cobranca/casos
POST   /api/cobranca/casos
POST   /api/cobranca/casos/lote
PATCH  /api/cobranca/casos/{id}/status
DELETE /api/cobranca/casos/{id}
POST   /api/cobranca/casos/{id}/tentativas
POST   /api/cobranca/casos/{id}/agendamentos
PATCH  /api/cobranca/casos/{id}/agendamentos/{id_agenda}/concluir
```

Documentação interativa em `/docs`.

## Acesso

Suba com `IniciarPainel.bat` e acesse <http://127.0.0.1:8000>.

Usuários: `Master` (acesso total) e `AlvoCard` (somente leitura). A
autenticação é feita no navegador — separa perfis, não protege dado
sensível. Para trocar a senha, gere `SHA-256(salt + senha)` e substitua
`salt`/`hash` em `front/js/app.js`.

Abrir `front/index.html` direto do disco (`file://`) não funciona mais:
sem servidor não há banco, e o painel avisa na tela.

## Testes e estilo

```bash
venv\Scripts\python.exe -m pytest
venv\Scripts\python.exe -m isort api serve.py tests
venv\Scripts\python.exe -m blue api serve.py tests
```

## Tecnologias

- fastapi, uvicorn, pydantic
- sqlite3
- gradio (apenas `main.py`)
