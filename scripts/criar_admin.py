# INSERIR EM: scripts/criar_admin.py
"""Gera a conta administradora inicial do painel para o Supabase.

Produz um comando ``INSERT`` para a tabela ``public.usuarios`` (schema em
``scripts/supabase_schema_usuarios.sql``) contendo apenas o **hash** da
senha. A senha em texto claro vem de ``COFC_ADMIN_SENHA`` ou é sorteada, e
é impressa **uma única vez** no terminal — nunca é gravada em arquivo nem
versionada.

Uso:
    python scripts/criar_admin.py            # senha aleatória
    COFC_ADMIN_SENHA=... python scripts/criar_admin.py

Depois, cole o INSERT no SQL Editor do Supabase.
"""

from __future__ import annotations

# --- stdlib ---
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# --- locais ---
from api.domain_usuarios import (  # noqa: E402
    TAMANHO_MINIMO_SENHA,
    montar_admin_padrao,
)

VARIAVEL_SENHA = 'COFC_ADMIN_SENHA'
TAMANHO_SENHA_SORTEADA = 16
COLUNAS_INSERT = (
    'nome',
    'email',
    'login',
    'senha_hash',
    'perfil',
    'status',
    'senha_provisoria',
)


def resolver_senha() -> tuple[str, bool]:
    """Lê a senha do ambiente ou sorteia uma forte.

    Returns:
        Par ``(senha, foi_sorteada)``.

    Raises:
        ValueError: Se ``COFC_ADMIN_SENHA`` existir mas for curta demais.

    Example:
        >>> senha, sorteada = resolver_senha()
        >>> len(senha) >= 8
        True
    """
    do_ambiente = os.getenv(VARIAVEL_SENHA)
    if do_ambiente:
        if len(do_ambiente) < TAMANHO_MINIMO_SENHA:
            raise ValueError(
                f'{VARIAVEL_SENHA} deve ter ao menos '
                f'{TAMANHO_MINIMO_SENHA} caracteres.'
            )
        return do_ambiente, False

    return secrets.token_urlsafe(TAMANHO_SENHA_SORTEADA), True


def _valor_sql(valor: Any) -> str:
    """Formata um valor Python como literal SQL seguro."""
    if isinstance(valor, bool):
        return 'true' if valor else 'false'
    escapado = str(valor).replace("'", "''")
    return f"'{escapado}'"


def montar_insert(registro: Mapping[str, Any]) -> str:
    """Monta o INSERT de um usuário para ``public.usuarios``.

    Args:
        registro: Usuário já com ``senha_hash`` (ver domain_usuarios).

    Returns:
        Comando SQL ``INSERT`` pronto para o Supabase.

    Example:
        >>> sql = montar_insert(
        ...     montar_admin_padrao('senhaGrande1', '2026-07-27T09:00:00')
        ... )
        >>> sql.startswith('insert into public.usuarios')
        True
    """
    colunas = ', '.join(COLUNAS_INSERT)
    valores = ', '.join(
        _valor_sql(registro[coluna]) for coluna in COLUNAS_INSERT
    )

    return (
        f'insert into public.usuarios ({colunas})\n'
        f'values ({valores})\n'
        f'on conflict (login) do nothing;'
    )


def main() -> None:
    """Gera o admin e imprime a senha (uma vez) e o INSERT."""
    senha, sorteada = resolver_senha()
    agora = datetime.now(timezone.utc).isoformat(timespec='seconds')
    admin = montar_admin_padrao(senha, agora)

    print('=' * 60)
    print('CONTA ADMIN — anote a senha agora; ela NÃO será mostrada de novo.')
    print(f'  login: {admin["login"]}')
    origem = '(sorteada)' if sorteada else '(do ambiente)'
    print(f'  senha: {senha}  {origem}')
    print('  troca obrigatória no primeiro acesso (senha_provisoria = true)')
    print('=' * 60)
    print()
    print('-- Cole no SQL Editor do Supabase:')
    print(montar_insert(admin))


if __name__ == '__main__':
    main()
