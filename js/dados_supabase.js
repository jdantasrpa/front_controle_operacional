'use strict';

/* ============================================================
   dados_supabase.js — Acesso DIRETO ao banco via supabase-js (PostgREST),
   protegido por RLS. Sem Edge Functions. Reimplementa a camada api.js dos
   módulos já migrados; carregue depois de api.js (sobrescreve as funções
   de lá) e conta com o cliente scoCliente() do auth.js em tempo de chamada.

   Migrado: Originadoras. Convênios, vínculos e custos replicam este padrão.
   ============================================================ */

if (typeof scoAuthConfigurado === 'function' && scoAuthConfigurado()) {
  // Com Supabase, "API disponível" = existe sessão (usuário logado).
  apiDisponivel = function () {
    return typeof scoSessao === 'function' && Boolean(scoSessao());
  };

  const _db = function () {
    const cli = typeof scoCliente === 'function' ? scoCliente() : null;
    if (!cli) throw new Error('Faça login para acessar os dados.');
    return cli;
  };

  const COLS_ORIG = 'id_originadora,nome,codigo,cnpj,ativo,observacao';

  // tb_originadora (banco) -> forma que o front espera (status<->ativo).
  const _mapOrig = function (o) {
    return {
      id_originadora: o.id_originadora,
      nome: o.nome,
      codigo: o.codigo || '',
      cnpj: o.cnpj || '',
      status: o.ativo ? 'ATIVO' : 'INATIVO',
      observacao: o.observacao || '',
      cadastrado: true,
    };
  };

  const _registroOrig = function (dados) {
    return {
      codigo: (dados.codigo || '').trim() || null,
      cnpj: (dados.cnpj || '').trim() || null,
      ativo: String(dados.status || 'ATIVO').toUpperCase() !== 'INATIVO',
      observacao: (dados.observacao || '').trim() || null,
    };
  };

  apiOriginadoras = async function () {
    const { data, error } = await _db()
      .from('tb_originadora')
      .select(COLS_ORIG)
      .order('nome');
    if (error) throw new Error(error.message);
    return (data || []).map(_mapOrig);
  };

  apiCriarOriginadora = async function (dados) {
    const registro = { nome: (dados.nome || '').trim(), ..._registroOrig(dados) };
    const { data, error } = await _db()
      .from('tb_originadora')
      .insert(registro)
      .select(COLS_ORIG)
      .single();
    if (error) throw new Error(error.message);
    return _mapOrig(data);
  };

  apiAtualizarOriginadora = async function (nome, dados) {
    const { data, error } = await _db()
      .from('tb_originadora')
      .update(_registroOrig(dados))
      .eq('nome', nome)
      .select(COLS_ORIG)
      .single();
    if (error) throw new Error(error.message);
    return _mapOrig(data);
  };

  apiExcluirOriginadora = async function (nome) {
    const { error } = await _db()
      .from('tb_originadora')
      .delete()
      .eq('nome', nome);
    if (error) throw new Error(error.message);
    return { ok: true };
  };
}
