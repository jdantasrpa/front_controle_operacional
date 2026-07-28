# INSERIR EM: api/domain_permissao.py
"""Regras puras de permissão e do fluxo de aprovação de acesso do SCO.

Papéis:
    ADMIN  — acesso total e **único** que cria usuários.
    MASTER — mesmo acesso do ADMIN, exceto criar usuários.
    GESTOR / OPERADOR / LEITOR — perfis operacionais.

O fluxo de acesso: alguém solicita → PENDENTE + e-mail aos autorizadores.
Resposta positiva → APROVADA (usuário criado/ativado). Resposta negativa →
NEGADA (usuário suspenso na criação). Este módulo não faz I/O.
"""

from __future__ import annotations

# --- stdlib ---
import secrets
from enum import Enum
from typing import Any, Mapping

# --- locais ---
from api.domain import texto
from api.domain_usuarios import Perfil

# Perfis com acesso total ao sistema.
PERFIS_ACESSO_TOTAL = frozenset({Perfil.ADMIN.value, Perfil.MASTER.value})
# Perfis que podem criar usuários (só o ADMIN).
PERFIS_CRIAM_USUARIO = frozenset({Perfil.ADMIN.value})


class StatusSolicitacao(str, Enum):
    """Estado de uma solicitação de acesso ao portal."""

    PENDENTE = 'PENDENTE'
    APROVADA = 'APROVADA'
    NEGADA = 'NEGADA'


def _perfil(valor: Any) -> str:
    return texto(valor).upper()


def tem_acesso_total(perfil: Any) -> bool:
    """Diz se o perfil enxerga/usa tudo (ADMIN ou MASTER).

    Example:
        >>> tem_acesso_total('ADMIN'), tem_acesso_total('MASTER')
        (True, True)
        >>> tem_acesso_total('OPERADOR')
        False
    """
    return _perfil(perfil) in PERFIS_ACESSO_TOTAL


def pode_criar_usuario(perfil: Any) -> bool:
    """Diz se o perfil pode criar novos usuários (só o ADMIN).

    Example:
        >>> pode_criar_usuario('ADMIN')
        True
        >>> pode_criar_usuario('MASTER')
        False
    """
    return _perfil(perfil) in PERFIS_CRIAM_USUARIO


def pode_alterar_equipe(perfil: Any) -> bool:
    """Diz se o perfil pode trocar a equipe de um usuário (ADMIN ou MASTER).

    Example:
        >>> pode_alterar_equipe('ADMIN'), pode_alterar_equipe('MASTER')
        (True, True)
        >>> pode_alterar_equipe('GESTOR')
        False
    """
    return _perfil(perfil) in PERFIS_ACESSO_TOTAL


def gerar_token_autorizacao() -> str:
    """Gera um token opaco para os links de aprovar/negar do e-mail.

    Example:
        >>> len(gerar_token_autorizacao()) >= 32
        True
    """
    return secrets.token_urlsafe(32)


def montar_solicitacao(
    dados: Mapping[str, Any], agora: str
) -> dict[str, Any]:
    """Normaliza um pedido de acesso em registro PENDENTE com token.

    Args:
        dados: ``nome``, ``email`` e ``perfil_solicitado``.
        agora: Carimbo ISO da solicitação.

    Returns:
        Registro pronto para gravar em ``tb_solicitacao_acesso``.

    Example:
        >>> s = montar_solicitacao(
        ...     {'nome': 'Ana', 'email': 'a@x.com'}, '2026-07-27T09:00:00'
        ... )
        >>> s['status'], s['perfil_solicitado']
        ('PENDENTE', 'OPERADOR')
    """
    perfil = _perfil(dados.get('perfil_solicitado')) or Perfil.OPERADOR.value

    return {
        'nome': texto(dados.get('nome')),
        'email': texto(dados.get('email')).lower(),
        'perfil_solicitado': perfil,
        'status': StatusSolicitacao.PENDENTE.value,
        'token_autorizacao': gerar_token_autorizacao(),
        'solicitado_em': texto(agora),
    }


def aplicar_resposta_autorizacao(
    aprovado: bool, autorizador_email: str, agora: str, motivo: str = ''
) -> dict[str, Any]:
    """Traduz a resposta do autorizador em atualização da solicitação.

    Resposta negativa suspende a criação (status NEGADA); positiva libera
    (APROVADA).

    Args:
        aprovado: ``True`` se o autorizador aprovou.
        autorizador_email: Quem respondeu (auditoria).
        agora: Carimbo ISO da resposta.
        motivo: Justificativa (usada sobretudo na negativa).

    Returns:
        Campos a atualizar em ``tb_solicitacao_acesso``.

    Example:
        >>> r = aplicar_resposta_autorizacao(False, 'chefe@x.com', 'AGORA')
        >>> r['status']
        'NEGADA'
    """
    status = (
        StatusSolicitacao.APROVADA if aprovado else StatusSolicitacao.NEGADA
    )

    return {
        'status': status.value,
        'autorizador_email': texto(autorizador_email).lower(),
        'motivo': texto(motivo),
        'respondido_em': texto(agora),
    }
