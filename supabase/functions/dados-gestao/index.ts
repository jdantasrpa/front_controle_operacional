// supabase/functions/dados-gestao/index.ts
// Gateway de dados do módulo Gestão de Convênios. Protegido pelo token de
// sessão (header x-sco-token). Leitura: qualquer sessão válida. Escrita:
// ADMIN, MASTER ou GESTOR. POST { acao, ... }.
// Deploy com verify_jwt=false (validamos o nosso próprio token).
//
// Escopo migrado: Originadoras (listar/salvar/excluir). Convênios, vínculos
// e custos replicam este mesmo padrão de ação.

import { CORS, json, supaAdmin, verificarToken } from '../_shared/comum.ts';

const PERFIS_ESCRITA = ['ADMIN', 'MASTER', 'GESTOR'];

// tb_originadora (Postgres) -> forma que o front espera (status<->ativo).
function mapOriginadora(row: Record<string, unknown>) {
  return {
    id_originadora: row.id_originadora,
    nome: row.nome,
    codigo: row.codigo ?? '',
    cnpj: row.cnpj ?? '',
    status: row.ativo ? 'ATIVO' : 'INATIVO',
    observacao: row.observacao ?? '',
    cadastrado: true,
  };
}

const COLUNAS_ORIGINADORA = 'id_originadora,nome,codigo,cnpj,ativo,observacao';

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS });
  if (req.method !== 'POST') return json({ erro: 'Método não suportado.' }, 405);

  const sessao = await verificarToken(req.headers.get('x-sco-token') || '');
  if (!sessao) return json({ erro: 'Sessão inválida ou expirada.' }, 401);
  const perfil = String(sessao.perfil || '').toUpperCase();

  let corpo: Record<string, unknown>;
  try {
    corpo = await req.json();
  } catch {
    return json({ erro: 'JSON inválido.' }, 400);
  }
  const acao = String(corpo.acao || '');
  const supa = supaAdmin();
  const podeEscrever = PERFIS_ESCRITA.includes(perfil);

  if (acao === 'listar_originadoras') {
    const { data, error } = await supa
      .from('tb_originadora')
      .select(COLUNAS_ORIGINADORA)
      .order('nome');
    if (error) return json({ erro: error.message }, 400);
    return json({ originadoras: (data || []).map(mapOriginadora) });
  }

  if (acao === 'salvar_originadora') {
    if (!podeEscrever) return json({ erro: 'Sem permissão para gravar.' }, 403);
    const nome = String(corpo.nome || '').trim();
    if (!nome) return json({ erro: 'Informe o nome da originadora.' }, 400);

    const registro = {
      nome,
      codigo: String(corpo.codigo || '').trim() || null,
      cnpj: String(corpo.cnpj || '').trim() || null,
      ativo: String(corpo.status || 'ATIVO').toUpperCase() !== 'INATIVO',
      observacao: String(corpo.observacao || '').trim() || null,
    };

    // nome é a chave natural (imutável): já existe -> update; senão -> insert.
    const { data: existente } = await supa
      .from('tb_originadora')
      .select('id_originadora')
      .eq('nome', nome)
      .maybeSingle();
    const escrita = existente
      ? supa.from('tb_originadora').update(registro).eq('nome', nome)
      : supa.from('tb_originadora').insert(registro);

    const { data, error } = await escrita.select(COLUNAS_ORIGINADORA).single();
    if (error) return json({ erro: error.message }, 400);
    return json({ originadora: mapOriginadora(data) });
  }

  if (acao === 'excluir_originadora') {
    if (!podeEscrever) return json({ erro: 'Sem permissão para gravar.' }, 403);
    const nome = String(corpo.nome || '').trim();
    const { data: orig } = await supa
      .from('tb_originadora')
      .select('id_originadora')
      .eq('nome', nome)
      .maybeSingle();
    if (!orig) return json({ erro: 'Originadora não encontrada.' }, 404);

    // FK sem cascade: bloquear exclusão se houver vínculo (inativar, não apagar).
    const { count } = await supa
      .from('tb_vinculo')
      .select('id_vinculo', { count: 'exact', head: true })
      .eq('id_originadora', orig.id_originadora);
    if (count && count > 0) {
      return json(
        { erro: 'Originadora com convênio vinculado — inative-a em vez de excluir.' },
        409,
      );
    }

    const { error } = await supa.from('tb_originadora').delete().eq('nome', nome);
    if (error) return json({ erro: error.message }, 400);
    return json({ ok: true });
  }

  return json({ erro: `Ação desconhecida: ${acao}` }, 400);
});
