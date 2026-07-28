'use strict';

/* ============================================================
   dados_supabase.js — Fonte de dados via Supabase (gateway de Edge
   Functions). Reimplementa a camada api.js apontando para as functions
   `dados-*`, para o front (GitHub Pages) consumir o Postgres do Supabase.

   Só entra em ação com o Supabase configurado (config.js); sem ele, o
   painel mantém o modo api/demo. Carregue SEMPRE depois de api.js — estas
   definições sobrescrevem as de lá.

   Migrado até agora: Originadoras. Convênios, vínculos e custos replicam
   este mesmo padrão (uma função apiX -> uma acao do gateway dados-gestao).
   ============================================================ */

if (typeof scoAuthConfigurado === 'function' && scoAuthConfigurado()) {
  // Com Supabase, a "API" do painel passa a ser o gateway de functions.
  // A gravação da Gestão é liberada por exigirApi(), que consulta isto.
  apiDisponivel = function () {
    return typeof scoSessao === 'function' && Boolean(scoSessao());
  };

  const _gestao = (corpo) => scoChamarFuncaoAutenticada('dados-gestao', corpo);

  apiOriginadoras = async function () {
    const dados = await _gestao({ acao: 'listar_originadoras' });
    return dados.originadoras || [];
  };

  apiCriarOriginadora = async function (dados) {
    const resp = await _gestao({ acao: 'salvar_originadora', ...dados });
    return resp.originadora;
  };

  apiAtualizarOriginadora = async function (nome, dados) {
    const resp = await _gestao({ acao: 'salvar_originadora', nome, ...dados });
    return resp.originadora;
  };

  apiExcluirOriginadora = async function (nome) {
    return _gestao({ acao: 'excluir_originadora', nome });
  };
}
