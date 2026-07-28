'use strict';

/* ============================================================
   config.js — Configuração PÚBLICA do front (vai para o GitHub Pages).
   Só valores públicos por design: URL do projeto + chave publishable.
   NUNCA coloque aqui secret key, DB URL ou a chave-mestra.
   Se ficar vazio, o painel opera em modo demonstração (sem login).
   ============================================================ */

const SCO_CONFIG = {
  SUPABASE_URL: 'https://zmifihasxzdyccxqparx.supabase.co',
  SUPABASE_ANON_KEY: 'sb_publishable_GJ3P9xysJRR49oV_PSzYtA_2PeVE8s8',
};

// Diz se o login está configurado (senão, modo demonstração sem gate).
function scoAuthConfigurado() {
  return Boolean(SCO_CONFIG.SUPABASE_URL && SCO_CONFIG.SUPABASE_ANON_KEY);
}
