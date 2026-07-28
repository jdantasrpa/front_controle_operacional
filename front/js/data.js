'use strict';

/* ============================================================
   data.js — Modelo de dados + store (demonstração)
   Reproduz o domínio do app Gradio SCO — Controle Operacional.

   REGRA DE NEGÓCIO:
   - VENCIMENTÁRIO = competência de vencimento (MM/AAAA) + a data de
     vencimento daquele ciclo. Um convênio acumula vencimentários de
     várias competências, e o operador troca de um para outro dentro
     do próprio Analítico.
   - POR VENCIMENTÁRIO: Conciliação, Financeiro, Cobrança.
   - COMPARTILHADO (regra do convênio, vale para todas as competências):
     Secretaria, Particularidade, Conta, Contato.
   - O convênio pode ter várias SECRETARIAS. Cada lançamento do
     Financeiro aponta a secretaria repassada; secretaria ativa sem
     repasse no vencimentário é DEVEDORA e aparece na Conciliação.
   - Cada secretaria tem seu contato, e pode existir um contato que
     responde por todas elas (SECRETARIA_TODAS).
   ============================================================ */

const STORAGE_KEY = 'cofc_store_v4';

const STATUS_CONCILIACAO_OPCOES = ['CONCILIADO', 'CONCILIADO (PARCIAL)', 'PENDENTE'];

// Status de PRODUÇÃO do convênio — controlado pela Gestão de Convênios.
// Diz a "saúde"/produção do convênio; é distinto dos status de cada
// atividade (conciliação, remessa), que têm comportamento próprio.
const STATUS_PRODUCAO_OPCOES = [
  'Em produção',
  'Em implantação',
  'Suspenso',
  'Encerrado',
];
const MOTIVO_FALTA_OPCOES = [
  'Falta de repasse do convênio',
  'Arquivo retorno não disponível',
  'Outros',
];

// Submódulo Remessas (lista por convênio, dentro de Conciliação).
// Valores em uso hoje na operação.
const MODO_ENVIO_REMESSA_OPCOES = ['Parcelado', 'Arquivo'];
const ACESSO_REMESSA_OPCOES = ['Acesso Ok', 'Não recebido', 'Bloqueado'];
// Modelo de averbação é MÚLTIPLA seleção: guardado como lista.
const MODELO_AVERBACAO_REMESSA_OPCOES = [
  'Parcelado',
  'Arquivo',
  'Não Atuamos',
  'sem acesso',
];
// Status do envio da remessa, registrado por convênio e por mês.
const STATUS_ENVIO_MENSAL_OPCOES = ['Enviado', 'Pendente', 'Não enviado'];
const STATUS_IMPORTACAO_REMESSA_OPCOES = [
  'Importado',
  'Não importado',
  'Parcelado',
  'Sem produção',
  'Em andamento',
  'Sem acesso',
];

// Contato/repasse que vale para o convênio inteiro, não para uma secretaria.
const SECRETARIA_TODAS = 'Todas as secretarias';

// Convênio sem secretaria cadastrada: o Financeiro usa este balde padrão,
// para lançar repasse e conciliar sem depender do cadastro de secretaria.
const SECRETARIA_NENHUMA = 'Nenhuma Sec. Reg.';

// Cenários de conciliação que o operador pode escolher por vencimentário.
const CENARIOS_CONCILIACAO = [
  'Repasse único (valor total)',
  'Repasse por vencimentário',
  'Repasse parcial com retenção',
  'Conciliação manual',
  'Sem repasse (inadimplente)',
];

// Aba Conciliação do Analítico (espelha DADOS_FIELDS do main.py).
// `computed` = valor derivado, nunca digitado: 'repasse' vem da soma do
// Financeiro do vencimentário; 'pendente' = valor retorno - repasse.
const DADOS_FIELDS = [
  { key: 'data_vencimento', label: 'Data vencimento', editable: false, fmt: 'date' },
  { key: 'data_baixa', label: 'Data SLA conciliação', editable: false, fmt: 'date' },
  { key: 'data_baixa_efetiva', label: 'Data da baixa realizada', editable: true, fmt: 'date' },
  { key: 'qtd_dias_inadimplencia', label: 'Qtd dias SLA pagamento', editable: false, fmt: 'int' },
  { key: 'data_corte', label: 'Data corte', editable: true, fmt: 'date' },
  { key: 'valor_remessa', label: 'Valor remessa', editable: true, fmt: 'money' },
  { key: 'valor_retorno', label: 'Valor retorno', editable: true, fmt: 'money' },
  {
    key: 'valor_repasse', label: 'Valor repasse', editable: false, fmt: 'money',
    computed: 'repasse', nota: 'soma do Financeiro',
  },
  {
    key: 'valor_pendente', label: 'Valor pendente', editable: false, fmt: 'money',
    computed: 'pendente', nota: 'retorno − repasse',
  },
  { key: 'porcentagem_inadimplencia', label: '% inadimplência', editable: false, fmt: 'percent' },
  { key: 'qtd_contratos', label: 'QTD de contratos', editable: false, fmt: 'int' },
  {
    key: 'status_conciliacao', label: 'Status conciliação', editable: true,
    type: 'select', options: STATUS_CONCILIACAO_OPCOES,
  },
  {
    key: 'cenario_conciliacao', label: 'Cenário de conciliação', editable: true,
    type: 'select', options: CENARIOS_CONCILIACAO,
  },
  {
    key: 'motivo_falta_conciliacao', label: 'Motivo falta conciliação', editable: true,
    type: 'select', options: MOTIVO_FALTA_OPCOES,
    depends_on: { field: 'status_conciliacao', show_when: ['CONCILIADO (PARCIAL)'] },
  },
  { key: 'numero_card_asset', label: 'Nº do card (Asset)', editable: true },
  { key: 'observacao', label: 'Observação', editable: true, type: 'textarea' },
];

/* ---------------- Helpers de seed ---------------- */

function _uid() {
  if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
  return 'id_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
}

function _agora() {
  return new Date().toLocaleString('pt-BR');
}

// Todo repasse do Financeiro pertence ao vencimentário que o contém: a
// competência e o dia são carimbados aqui, nunca digitados. É o que
// permite a automação saber a que vencimento o repasse se refere sem
// depender da posição do registro.
function carimbarVencimentario(venc, registro) {
  return {
    ...registro,
    mes_referencia: venc.competencia,
    dia_vencimento: venc.dia_vencimento,
  };
}

function _venc(d) {
  const identidade = {
    competencia: d.competencia,
    dia_vencimento: d.dia_vencimento,
  };

  return {
    id: d.id || _uid(),
    ...identidade,
    // Cenário é atributo da conciliação daquele vencimentário: mora
    // junto do status, e é salvo pelo mesmo formulário.
    conciliacao: {
      ...d.conciliacao,
      cenario_conciliacao:
        d.cenario_conciliacao || CENARIOS_CONCILIACAO[0],
    },
    financeiro: (d.financeiro || []).map(
      (registro) => carimbarVencimentario(identidade, registro)
    ),
    cobranca_historico: d.cobranca_historico || [],
  };
}

function _conv(d) {
  return {
    id: d.id,
    originador: d.originador || 'Alvo Card',
    numero_convenio: d.numero_convenio,
    nome_convenio: d.nome_convenio,
    cnpj_convenio: d.cnpj_convenio,
    // Compartilhado (regra do convênio, vale para toda competência):
    secretarias: d.secretarias || [],
    particularidades: d.particularidades || [],
    contas: d.contas || [],
    contatos: d.contatos || [],
    // Identidade usada no submódulo Remessas (lista por convênio).
    status: d.status || 'Ativo',
    // Status de produção — controlado pela Gestão de Convênios, visível
    // (somente leitura) para Conciliação e Remessa.
    status_producao: d.status_producao || '',
    gestora_margem: d.gestora_margem || '',
    link_gestora: d.link_gestora || '',
    // Configuração de remessa do convênio (submódulo Remessas · Conciliação).
    // Remessa é MENSAL e imutável no histórico (lastro de como foi
    // enviada). Cada mês guarda o snapshot operacional:
    //   { 'AAAA-MM': { corte, status_envio, modo_envio, modelo_averbacao,
    //                  acesso, status_importacao, obs } }
    // Replicado do mês anterior; só o mês corrente é editável.
    // Gestora e URL ficam no convênio (regra da Gestão de Convênios).
    remessa: {
      meses: {},
      atualizado_em: '',
      ...(d.remessa || {}),
    },
    // Um por competência de vencimento:
    vencimentarios: d.vencimentarios,
  };
}

/* ---------------- Dados de demonstração ---------------- */

const SEED = {
  convenios: [
    _conv({
      id: 1, numero_convenio: '00001ALV', nome_convenio: 'AERONÁUTICA',
      cnpj_convenio: '00.394.429/0082-76',
      status: 'Ativo',
      status_producao: 'Em produção',
      gestora_margem: 'FÁCILCONSIG',
      link_gestora: 'https://www.faciltecnologia.com.br/consigfacil/index.php',
      remessa: {
        meses: {
          '2026-06': {
            corte: '3', status_envio: 'Enviado', modo_envio: ['Arquivo'],
            modelo_averbacao: ['Parcelado'], acesso: 'Acesso Ok',
            status_importacao: 'Importado', obs: '',
          },
          '2026-07': {
            corte: '3', status_envio: 'Pendente', modo_envio: ['Arquivo'],
            modelo_averbacao: ['Parcelado'], acesso: 'Acesso Ok',
            status_importacao: '', obs: '',
          },
        },
      },
      contatos: [
        { id: _uid(), status: 'ATIVO', nome: 'Marina Alves', secretaria: SECRETARIA_TODAS, email: 'financeiro@aer.gov.br', telefone: '(61) 98111-2020', area: 'Financeiro', observacao: '', criado_em: _agora(), atualizado_em: '' },
      ],
      contas: [
        { id: _uid(), banco: 'Banco do Brasil', agencia: '3057-1', conta: '12345-6', chave_pix: '00.394.429/0082-76', cnpj: '00.394.429/0082-76', status_conta: 'ATIVA', criado_em: _agora(), atualizado_em: '' },
      ],
      vencimentarios: [
        _venc({
          competencia: '03/2026', dia_vencimento: '05',
          cenario_conciliacao: 'Repasse único (valor total)',
          conciliacao: {
            data_vencimento: '05/03/2026', data_baixa: '07/03/2026', qtd_dias_inadimplencia: 0,
            data_corte: '03/03/2026', valor_remessa: 300000.00, valor_retorno: 299400.00,
            porcentagem_inadimplencia: 0.20, qtd_contratos: 18,
            status_conciliacao: 'CONCILIADO', motivo_falta_conciliacao: '', observacao: '',
            numero_card_asset: 'ASSET-10432', data_baixa_efetiva: '07/03/2026',
          },
          financeiro: [
            { id: _uid(), mes_referencia: '03/2026', secretaria: SECRETARIA_TODAS, data_prevista: '05/03/2026', data_efetiva: '07/03/2026', valor_previsto: 299400.00, valor_recebido: 299400.00, valor_repassado: 299400.00, forma_pagamento: 'pix', status_financeiro: 'Conciliado', observacao: '', criado_em: _agora(), atualizado_em: '' },
          ],
        }),
        _venc({
          competencia: '03/2026', dia_vencimento: '20',
          cenario_conciliacao: 'Repasse por vencimentário',
          conciliacao: {
            data_vencimento: '20/03/2026', data_baixa: '22/03/2026', qtd_dias_inadimplencia: 0,
            data_corte: '18/03/2026', valor_remessa: 180250.00, valor_retorno: 179500.00,
            porcentagem_inadimplencia: 0.41, qtd_contratos: 10,
            status_conciliacao: 'CONCILIADO', motivo_falta_conciliacao: '', observacao: '',
          },
          financeiro: [
            { id: _uid(), mes_referencia: '03/2026', secretaria: SECRETARIA_TODAS, data_prevista: '20/03/2026', data_efetiva: '22/03/2026', valor_previsto: 179500.00, valor_recebido: 179500.00, valor_repassado: 179500.00, forma_pagamento: 'pix', status_financeiro: 'Conciliado', observacao: '', criado_em: _agora(), atualizado_em: '' },
          ],
        }),
        _venc({
          competencia: '02/2026', dia_vencimento: '05',
          cenario_conciliacao: 'Repasse único (valor total)',
          conciliacao: {
            data_vencimento: '05/02/2026', data_baixa: '06/02/2026', qtd_dias_inadimplencia: 0,
            data_corte: '03/02/2026', valor_remessa: 471000.00, valor_retorno: 470100.00,
            porcentagem_inadimplencia: 0.19, qtd_contratos: 27,
            status_conciliacao: 'CONCILIADO', motivo_falta_conciliacao: '', observacao: '',
          },
          financeiro: [
            { id: _uid(), mes_referencia: '02/2026', secretaria: SECRETARIA_TODAS, data_prevista: '05/02/2026', data_efetiva: '06/02/2026', valor_previsto: 470100.00, valor_recebido: 470100.00, valor_repassado: 470100.00, forma_pagamento: 'pix', status_financeiro: 'Conciliado', observacao: '', criado_em: _agora(), atualizado_em: '' },
          ],
        }),
      ],
    }),
    _conv({
      id: 2, numero_convenio: '00011ALV', nome_convenio: 'GOV. GOIÁS',
      cnpj_convenio: '02.476.034/0001-82',
      status: 'Ativo',
      status_producao: 'Em implantação',
      gestora_margem: 'ZETRA',
      link_gestora: 'https://portal.zetra.com.br',
      remessa: {
        meses: {
          '2026-06': {
            corte: '5', status_envio: 'Enviado', modo_envio: ['Parcelado'],
            modelo_averbacao: ['Parcelado'], acesso: 'Acesso Ok',
            status_importacao: 'Importado', obs: '',
          },
          '2026-07': {
            corte: '5', status_envio: 'Pendente', modo_envio: ['Parcelado'],
            modelo_averbacao: ['Parcelado'], acesso: 'Acesso Ok',
            status_importacao: '', obs: '',
          },
        },
      },
      secretarias: [
        { id: _uid(), nome: 'Secretaria de Educação', codigo: 'SEDUC', status_secretaria: 'ATIVA', observacao: 'Maior folha do convênio.', criado_em: _agora(), atualizado_em: '' },
        { id: _uid(), nome: 'Secretaria de Saúde', codigo: 'SES', status_secretaria: 'ATIVA', observacao: '', criado_em: _agora(), atualizado_em: '' },
        { id: _uid(), nome: 'Secretaria de Administração', codigo: 'SEAD', status_secretaria: 'ATIVA', observacao: 'Repasse costuma atrasar.', criado_em: _agora(), atualizado_em: '' },
      ],
      contatos: [
        { id: _uid(), status: 'ATIVO', nome: 'Ricardo Nunes', secretaria: SECRETARIA_TODAS, email: 'contas@goias.gov.br', telefone: '(62) 98222-3030', area: 'Tesouraria', observacao: 'Responde por todas as secretarias.', criado_em: _agora(), atualizado_em: '' },
        { id: _uid(), status: 'ATIVO', nome: 'Beatriz Campos', secretaria: 'Secretaria de Educação', email: 'convenios@goias.gov.br', telefone: '(62) 98222-4040', area: 'Convênios', observacao: '', criado_em: _agora(), atualizado_em: '' },
        { id: _uid(), status: 'ATIVO', nome: 'Tiago Rocha', secretaria: 'Secretaria de Administração', email: 'folha.sead@goias.gov.br', telefone: '(62) 98222-5050', area: 'Folha', observacao: '', criado_em: _agora(), atualizado_em: '' },
      ],
      contas: [
        { id: _uid(), banco: 'Caixa Econômica', agencia: '0101', conta: '98765-4', chave_pix: 'financeiro@goias.gov.br', cnpj: '02.476.034/0001-82', status_conta: 'ATIVA', criado_em: _agora(), atualizado_em: '' },
      ],
      particularidades: [
        { id: _uid(), status_particularidade: 'ATIVA', rubrica_produto: 'Consignado 001', modelo_de_averbacao: 'MARGEM', retencao: 'SIM', retencao_valor: '', retencao_percent: '2.5', observacao: 'Retenção de 2,5% sobre repasse.', criado_em: _agora(), atualizado_em: '' },
      ],
      vencimentarios: [
        _venc({
          competencia: '03/2026', dia_vencimento: '05',
          cenario_conciliacao: 'Repasse por vencimentário',
          conciliacao: {
            data_vencimento: '05/03/2026', data_baixa: '05/03/2026', qtd_dias_inadimplencia: 0,
            data_corte: '03/03/2026', valor_remessa: 700000.00, valor_retorno: 700000.00,
            porcentagem_inadimplencia: 0, qtd_contratos: 80,
            status_conciliacao: 'CONCILIADO', motivo_falta_conciliacao: '', observacao: '',
          },
          financeiro: [
            { id: _uid(), mes_referencia: '03/2026', secretaria: 'Secretaria de Educação', data_prevista: '05/03/2026', data_efetiva: '05/03/2026', valor_previsto: 400000.00, valor_recebido: 400000.00, valor_repassado: 400000.00, forma_pagamento: 'pix', status_financeiro: 'Conciliado', observacao: '', criado_em: _agora(), atualizado_em: '' },
            { id: _uid(), mes_referencia: '03/2026', secretaria: 'Secretaria de Saúde', data_prevista: '05/03/2026', data_efetiva: '05/03/2026', valor_previsto: 200000.00, valor_recebido: 200000.00, valor_repassado: 200000.00, forma_pagamento: 'pix', status_financeiro: 'Conciliado', observacao: '', criado_em: _agora(), atualizado_em: '' },
            { id: _uid(), mes_referencia: '03/2026', secretaria: 'Secretaria de Administração', data_prevista: '05/03/2026', data_efetiva: '05/03/2026', valor_previsto: 100000.00, valor_recebido: 100000.00, valor_repassado: 100000.00, forma_pagamento: 'pix', status_financeiro: 'Conciliado', observacao: '', criado_em: _agora(), atualizado_em: '' },
          ],
        }),
        _venc({
          competencia: '03/2026', dia_vencimento: '20',
          cenario_conciliacao: 'Sem repasse (inadimplente)',
          conciliacao: {
            data_vencimento: '20/03/2026', data_baixa: '20/03/2026', qtd_dias_inadimplencia: 16,
            data_corte: '', valor_remessa: 550800.00, valor_retorno: 550800.00,
            porcentagem_inadimplencia: 56.37, qtd_contratos: 63,
            status_conciliacao: 'PENDENTE', motivo_falta_conciliacao: 'Falta de repasse do convênio',
            observacao: 'Repasse parcial; cobrança em andamento.',
          },
          financeiro: [
            { id: _uid(), mes_referencia: '03/2026', secretaria: 'Secretaria de Educação', data_prevista: '20/03/2026', data_efetiva: '23/03/2026', valor_previsto: 300000.00, valor_recebido: 240300.00, valor_repassado: 240300.00, forma_pagamento: 'ted', status_financeiro: 'Conciliado a menor', observacao: 'Repasse parcial da SEDUC.', criado_em: _agora(), atualizado_em: '' },
          ],
          cobranca_historico: [
            { id: _uid(), data_hora: '18/03/2026 10:15', canal: 'telefone', resultado: 'sem_resposta', contato_nome: 'Ricardo Nunes', observacao: 'Ligação não atendida.', ator: 'joao', criado_em: _agora() },
            { id: _uid(), data_hora: '19/03/2026 14:30', canal: 'whatsapp', resultado: 'contato_efetivo', contato_nome: 'Ricardo Nunes', observacao: 'Prometeu repasse até dia 25.', ator: 'joao', criado_em: _agora() },
          ],
        }),
        _venc({
          competencia: '02/2026', dia_vencimento: '05',
          cenario_conciliacao: 'Repasse por vencimentário',
          conciliacao: {
            data_vencimento: '05/02/2026', data_baixa: '05/02/2026', qtd_dias_inadimplencia: 0,
            data_corte: '03/02/2026', valor_remessa: 690400.00, valor_retorno: 690400.00,
            porcentagem_inadimplencia: 0, qtd_contratos: 78,
            status_conciliacao: 'CONCILIADO', motivo_falta_conciliacao: '', observacao: '',
          },
          financeiro: [
            { id: _uid(), mes_referencia: '02/2026', secretaria: SECRETARIA_TODAS, data_prevista: '05/02/2026', data_efetiva: '05/02/2026', valor_previsto: 690400.00, valor_recebido: 690400.00, valor_repassado: 690400.00, forma_pagamento: 'pix', status_financeiro: 'Conciliado', observacao: '', criado_em: _agora(), atualizado_em: '' },
          ],
        }),
      ],
    }),
    _conv({
      id: 3, numero_convenio: '00021ALV', nome_convenio: 'GOV. ALAGOAS',
      cnpj_convenio: '12.200.184/0001-12',
      contatos: [
        { id: _uid(), status: 'ATIVO', nome: 'Helena Prado', secretaria: SECRETARIA_TODAS, email: 'financeiro@alagoas.gov.br', telefone: '(82) 95555-6060', area: 'Financeiro', observacao: '', criado_em: _agora(), atualizado_em: '' },
      ],
      contas: [
        { id: _uid(), banco: 'Banco do Brasil', agencia: '1234-5', conta: '55555-0', chave_pix: '12.200.184/0001-12', cnpj: '12.200.184/0001-12', status_conta: 'ATIVA', criado_em: _agora(), atualizado_em: '' },
      ],
      vencimentarios: [
        _venc({
          competencia: '03/2026', dia_vencimento: '08',
          cenario_conciliacao: 'Repasse parcial com retenção',
          conciliacao: {
            data_vencimento: '08/03/2026', data_baixa: '09/03/2026', qtd_dias_inadimplencia: 4,
            data_corte: '06/03/2026', valor_remessa: 620400.00, valor_retorno: 618900.00,
            porcentagem_inadimplencia: 2.68, qtd_contratos: 76,
            status_conciliacao: 'CONCILIADO (PARCIAL)', motivo_falta_conciliacao: 'Arquivo retorno não disponível',
            observacao: 'Diferença pequena; aguardando arquivo retorno.',
          },
          financeiro: [
            { id: _uid(), mes_referencia: '03/2026', secretaria: SECRETARIA_TODAS, data_prevista: '08/03/2026', data_efetiva: '09/03/2026', valor_previsto: 618900.00, valor_recebido: 602300.00, valor_repassado: 602300.00, forma_pagamento: 'ted', status_financeiro: 'Divergente', observacao: 'Faltam R$ 16.600,00.', criado_em: _agora(), atualizado_em: '' },
          ],
          cobranca_historico: [
            { id: _uid(), data_hora: '10/03/2026 11:20', canal: 'email', resultado: 'sem_resposta', contato_nome: 'Helena Prado', observacao: 'Cobrado o arquivo retorno.', ator: 'joao', criado_em: _agora() },
          ],
        }),
      ],
    }),
    _conv({
      id: 4, numero_convenio: '00031ALV', nome_convenio: 'ASSEMBLEIA MATO GROSSO',
      cnpj_convenio: '03.929.049/0001-11',
      contatos: [
        { id: _uid(), status: 'ATIVO', nome: 'Fábio Teixeira', secretaria: SECRETARIA_TODAS, email: 'tesouraria@al.mt.gov.br', telefone: '(65) 94666-7070', area: 'Tesouraria', observacao: '', criado_em: _agora(), atualizado_em: '' },
      ],
      vencimentarios: [
        _venc({
          competencia: '03/2026', dia_vencimento: '07',
          cenario_conciliacao: 'Repasse único (valor total)',
          conciliacao: {
            data_vencimento: '07/03/2026', data_baixa: '07/03/2026', qtd_dias_inadimplencia: 0,
            data_corte: '05/03/2026', valor_remessa: 205600.00, valor_retorno: 205600.00,
            porcentagem_inadimplencia: 0, qtd_contratos: 31,
            status_conciliacao: 'CONCILIADO', motivo_falta_conciliacao: '', observacao: '',
          },
          financeiro: [
            { id: _uid(), mes_referencia: '03/2026', secretaria: SECRETARIA_TODAS, data_prevista: '07/03/2026', data_efetiva: '07/03/2026', valor_previsto: 205600.00, valor_recebido: 205600.00, valor_repassado: 205600.00, forma_pagamento: 'pix', status_financeiro: 'Conciliado', observacao: '', criado_em: _agora(), atualizado_em: '' },
          ],
        }),
      ],
    }),
    _conv({
      id: 5, numero_convenio: '00041ALV', nome_convenio: 'PREF. GOIÂNIA',
      cnpj_convenio: '01.612.092/0001-23',
      secretarias: [
        { id: _uid(), nome: 'Secretaria de Educação', codigo: 'SME', status_secretaria: 'ATIVA', observacao: '', criado_em: _agora(), atualizado_em: '' },
        { id: _uid(), nome: 'Secretaria de Saúde', codigo: 'SMS', status_secretaria: 'ATIVA', observacao: '', criado_em: _agora(), atualizado_em: '' },
      ],
      contatos: [
        { id: _uid(), status: 'ATIVO', nome: 'Cláudia Moraes', secretaria: SECRETARIA_TODAS, email: 'rh@goiania.go.gov.br', telefone: '(62) 93777-8080', area: 'RH', observacao: 'Centraliza as duas secretarias.', criado_em: _agora(), atualizado_em: '' },
      ],
      vencimentarios: [
        _venc({
          competencia: '03/2026', dia_vencimento: '06',
          cenario_conciliacao: 'Sem repasse (inadimplente)',
          conciliacao: {
            data_vencimento: '06/03/2026', data_baixa: '06/03/2026', qtd_dias_inadimplencia: 22,
            data_corte: '', valor_remessa: 890000.00, valor_retorno: 890000.00,
            porcentagem_inadimplencia: 100, qtd_contratos: 98,
            status_conciliacao: 'PENDENTE', motivo_falta_conciliacao: 'Falta de repasse do convênio',
            observacao: 'Nenhum repasse recebido na competência.',
          },
          cobranca_historico: [
            { id: _uid(), data_hora: '20/03/2026 09:00', canal: 'email', resultado: 'retornar', contato_nome: 'Cláudia Moraes', observacao: 'Pediu para retornar na próxima semana.', ator: 'joao', criado_em: _agora() },
          ],
        }),
      ],
    }),
    _conv({
      id: 6, numero_convenio: '00051ALV', nome_convenio: 'TJ GOIÁS',
      cnpj_convenio: '02.938.150/0001-90',
      vencimentarios: [
        _venc({
          competencia: '03/2026', dia_vencimento: '09',
          cenario_conciliacao: 'Repasse único (valor total)',
          conciliacao: {
            data_vencimento: '09/03/2026', data_baixa: '09/03/2026', qtd_dias_inadimplencia: 0,
            data_corte: '05/03/2026', valor_remessa: 342100.00, valor_retorno: 342100.00,
            porcentagem_inadimplencia: 0, qtd_contratos: 44,
            status_conciliacao: 'CONCILIADO', motivo_falta_conciliacao: '', observacao: '',
          },
          financeiro: [
            { id: _uid(), mes_referencia: '03/2026', secretaria: SECRETARIA_TODAS, data_prevista: '09/03/2026', data_efetiva: '09/03/2026', valor_previsto: 342100.00, valor_recebido: 342100.00, valor_repassado: 342100.00, forma_pagamento: 'pix', status_financeiro: 'Conciliado', observacao: '', criado_em: _agora(), atualizado_em: '' },
          ],
        }),
      ],
    }),
  ],
};

/* ---------------- Regras puras (sem I/O) ---------------- */

// 'MM/AAAA' -> 'AAAAMM', para ordenar competência sem parsear data.
function chaveCompetencia(competencia) {
  const partes = String(competencia || '').split('/');
  return partes.length === 2 ? partes[1] + partes[0] : '';
}

function rotuloVencimentario(venc) {
  return `${venc.competencia} · vencimento dia ${venc.dia_vencimento}`;
}

// Vencimentário conciliado é o que o status diz — não existe marcação
// paralela que possa discordar dele.
function estaConciliado(venc) {
  return venc.conciliacao.status_conciliacao === 'CONCILIADO';
}

// Vencimentários do convênio, da competência mais nova para a mais antiga.
function vencimentariosOrdenados(conv) {
  return [...conv.vencimentarios].sort((a, b) => {
    const ca = chaveCompetencia(a.competencia);
    const cb = chaveCompetencia(b.competencia);
    if (ca !== cb) return cb.localeCompare(ca);
    return String(a.dia_vencimento).localeCompare(String(b.dia_vencimento));
  });
}

function vencimentariosDaCompetencia(conv, competencia) {
  return conv.vencimentarios.filter((v) => v.competencia === competencia);
}

// Valor repasse do vencimentário = soma do que o Financeiro registrou.
// A Conciliação apenas reflete esse número; não há digitação paralela.
//
// Sem nenhum lançamento no Financeiro vale o valor_repasse que veio da
// própria conciliação: é o caso dos dados reais do banco, onde o repasse
// por secretaria ainda não existe (etapa 2 da integração). Sem esse
// fallback todo vencimentário do banco apareceria 100% pendente.
function somaRepasseFinanceiro(venc) {
  const lancamentos = venc.financeiro || [];

  if (!lancamentos.length) return Number(venc.conciliacao.valor_repasse) || 0;

  return lancamentos.reduce(
    (total, reg) => total + (Number(reg.valor_recebido) || 0),
    0,
  );
}

// Diz de onde saiu o Valor repasse, para o rótulo do campo não mentir.
function repasseVemDoFinanceiro(venc) {
  return (venc.financeiro || []).length > 0;
}

function valorPendenteVencimentario(venc) {
  const retorno = Number(venc.conciliacao.valor_retorno) || 0;
  return retorno - somaRepasseFinanceiro(venc);
}

// Secretaria ATIVA sem nenhum repasse lançado no Financeiro daquele
// vencimentário está devendo. Um lançamento marcado como
// SECRETARIA_TODAS quita a pendência de todas de uma vez.
function secretariasDevedoras(conv, venc) {
  const repassadas = new Set(
    (venc.financeiro || [])
      .filter((reg) => (Number(reg.valor_recebido) || 0) > 0)
      .map((reg) => reg.secretaria)
      .filter(Boolean),
  );
  if (repassadas.has(SECRETARIA_TODAS)) return [];
  return (conv.secretarias || [])
    .filter((s) => s.status_secretaria === 'ATIVA')
    .filter((s) => !repassadas.has(s.nome));
}

// Extrai MM/AAAA de 'dd/mm/aaaa hh:mm'. Sem data reconhecível, devolve ''.
function competenciaDaData(dataHora) {
  const casamento = String(dataHora || '').match(/^\s*\d{2}\/(\d{2})\/(\d{4})/);
  return casamento ? `${casamento[1]}/${casamento[2]}` : '';
}

// Aba Cobrança: só as tentativas da competência do vencimentário aberto.
function tentativasDaCompetencia(venc) {
  return (venc.cobranca_historico || []).filter((h) => {
    const comp = competenciaDaData(h.data_hora);
    return comp === '' || comp === venc.competencia;
  });
}

/* ---------------- Store (persistência) ---------------- */

let DB = null;

function carregar() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    DB = raw ? JSON.parse(raw) : JSON.parse(JSON.stringify(SEED));
  } catch {
    DB = JSON.parse(JSON.stringify(SEED));
  }
}

function salvar() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(DB));
}

function resetar() {
  DB = JSON.parse(JSON.stringify(SEED));
  salvar();
}

// Linha do Sintético: o convênio resumido dentro de UMA competência.
function resumoCompetencia(conv, competencia) {
  const vs = vencimentariosDaCompetencia(conv, competencia);
  const statuses = vs.map((v) => v.conciliacao.status_conciliacao);
  let status;
  if (statuses.every((s) => s === 'CONCILIADO')) status = 'CONCILIADO';
  else if (statuses.every((s) => s === 'PENDENTE')) status = 'PENDENTE';
  else status = 'CONCILIADO (PARCIAL)';

  return {
    status_conciliacao: status,
    qtd_vencimentarios: vs.length,
    dias_venc: vs.map((v) => v.dia_vencimento).join(' / '),
    data_baixa: vs[0].conciliacao.data_baixa,
    data_corte: vs.map((v) => v.conciliacao.data_corte).filter(Boolean).join(' / ') || '',
    qtd_dias_inadimplencia: Math.max(...vs.map((v) => Number(v.conciliacao.qtd_dias_inadimplencia) || 0)),
    porcentagem_inadimplencia: Math.max(...vs.map((v) => Number(v.conciliacao.porcentagem_inadimplencia) || 0)),
  };
}

function competenciasDisponiveis() {
  const todas = DB.convenios.flatMap((c) => c.vencimentarios.map((v) => v.competencia));
  return [...new Set(todas)].sort(
    (a, b) => chaveCompetencia(b).localeCompare(chaveCompetencia(a)),
  );
}

function opcoesFiltro() {
  const meses = competenciasDisponiveis();
  const originadores = [...new Set(DB.convenios.map((c) => c.originador))].sort();
  const statuses = ['Todos', ...STATUS_CONCILIACAO_OPCOES];
  const motivos = ['Todos', ...MOTIVO_FALTA_OPCOES];
  return { meses, originadores, statuses, motivos };
}

// Devolve linhas { convenio, competencia, resumo } — uma por convênio que
// tenha vencimentário na competência filtrada.
function listarConvenios(filtros) {
  const f = filtros || {};
  return DB.convenios
    .filter((c) => !f.originador || c.originador === f.originador)
    .filter((c) => vencimentariosDaCompetencia(c, f.mes).length > 0)
    .filter((c) => {
      if (!f.busca) return true;
      const alvo = `${c.nome_convenio} ${c.cnpj_convenio} ${c.numero_convenio}`.toLowerCase();
      return alvo.includes(f.busca.toLowerCase());
    })
    .map((c) => ({ convenio: c, competencia: f.mes, resumo: resumoCompetencia(c, f.mes) }))
    .filter((linha) => !f.status || f.status === 'Todos'
      || linha.resumo.status_conciliacao === f.status)
    .filter((linha) => {
      if (!f.motivo || f.motivo === 'Todos') return true;
      return vencimentariosDaCompetencia(linha.convenio, f.mes)
        .some((v) => v.conciliacao.motivo_falta_conciliacao === f.motivo);
    });
}

function acharConvenio(numero) {
  return DB.convenios.find((c) => c.numero_convenio === numero) || null;
}

// Todos os convênios (sem filtro de competência) — usado pelo submódulo
// Remessas, que é cadastro por convênio, não por vencimentário.
function todosConvenios() {
  return DB.convenios;
}

const STORE = {
  carregar, salvar, resetar,
  opcoesFiltro, listarConvenios, acharConvenio, todosConvenios, resumoCompetencia,
  competenciasDisponiveis, vencimentariosOrdenados, vencimentariosDaCompetencia,
  rotuloVencimentario, chaveCompetencia, carimbarVencimentario,
  estaConciliado,
  somaRepasseFinanceiro, valorPendenteVencimentario, secretariasDevedoras,
  repasseVemDoFinanceiro,
  tentativasDaCompetencia, competenciaDaData,
  uid: _uid, agora: _agora,
};
