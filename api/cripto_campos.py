# INSERIR EM: api/cripto_campos.py
"""Mapa das colunas sensíveis a cifrar por tabela (AES-256-GCM).

Cifrar TUDO quebra o banco relacional: PKs/FKs, colunas de filtro e junção,
datas e valores usados em cálculo/agrupamento deixam de ser consultáveis
ou somáveis no Postgres — e a cifra é não determinística, então nem busca
por igualdade funciona sem um índice cego à parte.

Por isso o padrão cifra apenas o que é **confidencial e não participa de
busca/junção/agregação**: PII, dados bancários e textos livres. Chaves de
negócio pesquisáveis (``cnpj`` do convênio, ``email`` de login, ``numero_
convenio``) e valores usados em SLA/repasse ficam em claro de propósito.

Ajuste conforme a política de dados da empresa. Para tornar um campo-chave
pesquisável E cifrado, é preciso um índice cego (HMAC) — não coberto aqui.
"""

from __future__ import annotations

# --- stdlib ---
from typing import Mapping

# senha_hash de tb_usuario já é um hash (não se cifra); email é login
# (pesquisável) e fica em claro.
CAMPOS_SENSIVEIS: Mapping[str, tuple[str, ...]] = {
    'tb_originadora': ('cnpj', 'observacao'),
    'tb_averbadora': ('cnpj', 'observacao'),
    'tb_convenio': ('observacao',),
    'tb_vinculo': ('observacao',),
    'tb_secretaria': ('observacao',),
    'tb_remessa_envio': ('observacao',),
    'tb_repasse': ('observacao',),
    'tb_contato': ('nome', 'email', 'telefone'),
    'tb_particularidade': ('observacao',),
    'tb_conta': ('agencia', 'numero_conta', 'chave_pix', 'cnpj'),
    'tb_colaborador': ('observacao',),
    'tb_responsavel_historico': ('valor_de', 'valor_para'),
}


def campos_da_tabela(tabela: str) -> tuple[str, ...]:
    """Colunas sensíveis de uma tabela; vazio quando nenhuma.

    Example:
        >>> campos_da_tabela('tb_conta')
        ('agencia', 'numero_conta', 'chave_pix', 'cnpj')
        >>> campos_da_tabela('tb_grupo')
        ()
    """
    return CAMPOS_SENSIVEIS.get(tabela, ())
