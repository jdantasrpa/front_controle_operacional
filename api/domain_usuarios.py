# INSERIR EM: api/domain_usuarios.py
"""Regras puras de gestão de usuários: perfis, validação e hashing.

Não faz I/O. O hash de senha usa PBKDF2-HMAC-SHA256 (stdlib), com salt
aleatório por usuário, no formato ``pbkdf2_sha256$iteracoes$salt$hash``
(compatível com o de frameworks como o Django). A verificação é feita em
tempo constante para não vazar informação por temporização.

A escolha por PBKDF2 da stdlib evita dependência nova e roda em qualquer
ambiente; a força vem do número de iterações, não de segredo embutido.
"""

from __future__ import annotations

# --- stdlib ---
import base64
import hashlib
import hmac
import re
import secrets
from enum import Enum
from typing import Any, Mapping

ALGORITMO_HASH = 'pbkdf2_sha256'
ITERACOES_PADRAO = 260_000
TAMANHO_SALT_BYTES = 16
TAMANHO_MINIMO_SENHA = 8

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


class Perfil(str, Enum):
    """Perfis de acesso do painel, do mais amplo ao mais restrito.

    ADMIN e MASTER têm acesso total; a diferença é que **só o ADMIN cria
    usuários** (ver :mod:`api.domain_permissao`).
    """

    ADMIN = 'ADMIN'
    MASTER = 'MASTER'
    GESTOR = 'GESTOR'
    OPERADOR = 'OPERADOR'
    LEITOR = 'LEITOR'


class Status(str, Enum):
    """Situação da conta do usuário."""

    ATIVO = 'ATIVO'
    INATIVO = 'INATIVO'
    BLOQUEADO = 'BLOQUEADO'


def gerar_hash_senha(senha: str, iteracoes: int = ITERACOES_PADRAO) -> str:
    """Deriva o hash PBKDF2 de uma senha, com salt aleatório.

    Args:
        senha: Senha em texto claro (nunca é armazenada).
        iteracoes: Número de rodadas do PBKDF2.

    Returns:
        String ``pbkdf2_sha256$iteracoes$salt_b64$hash_b64``.

    Raises:
        ValueError: Se a senha for vazia.

    Example:
        >>> h = gerar_hash_senha('segredo123')
        >>> h.startswith('pbkdf2_sha256$')
        True
    """
    if not senha:
        raise ValueError('Senha vazia não pode ser convertida em hash.')

    salt = secrets.token_bytes(TAMANHO_SALT_BYTES)
    derivada = hashlib.pbkdf2_hmac(
        'sha256', senha.encode('utf-8'), salt, iteracoes
    )

    return '{}${}${}${}'.format(
        ALGORITMO_HASH,
        iteracoes,
        base64.b64encode(salt).decode('ascii'),
        base64.b64encode(derivada).decode('ascii'),
    )


def verificar_senha(senha: str, hash_armazenado: str) -> bool:
    """Confere uma senha contra o hash guardado, em tempo constante.

    Args:
        senha: Senha em texto claro informada no login.
        hash_armazenado: Hash no formato de :func:`gerar_hash_senha`.

    Returns:
        ``True`` se a senha corresponde ao hash; ``False`` caso contrário
        (inclusive para hash malformado ou algoritmo desconhecido).

    Example:
        >>> h = gerar_hash_senha('segredo123')
        >>> verificar_senha('segredo123', h)
        True
        >>> verificar_senha('errada', h)
        False
    """
    partes = str(hash_armazenado or '').split('$')
    if len(partes) != 4 or partes[0] != ALGORITMO_HASH:
        return False

    _, iteracoes_txt, salt_b64, hash_b64 = partes
    try:
        derivada = hashlib.pbkdf2_hmac(
            'sha256',
            senha.encode('utf-8'),
            base64.b64decode(salt_b64),
            int(iteracoes_txt),
        )
        return hmac.compare_digest(derivada, base64.b64decode(hash_b64))
    except (ValueError, TypeError):
        return False


def _valida_membro(valor: str, enum: type[Enum]) -> bool:
    """Diz se o valor é um dos membros do Enum informado."""
    return valor in {membro.value for membro in enum}


def validar_usuario(dados: Mapping[str, Any]) -> list[str]:
    """Lista o que impede um usuário de ser cadastrado.

    Args:
        dados: ``nome``, ``email``, ``login``, ``perfil`` e ``status``.

    Returns:
        Mensagens de erro; lista vazia quando válido.

    Example:
        >>> validar_usuario({'nome': '', 'email': 'x', 'login': ''})
        ['Informe o nome.', 'E-mail inválido.', 'Informe o login.']
    """
    perfil = str(dados.get('perfil') or Perfil.OPERADOR.value)
    status = str(dados.get('status') or Status.ATIVO.value)

    return [
        *([] if str(dados.get('nome') or '').strip() else ['Informe o nome.']),
        *(
            []
            if _EMAIL_RE.match(str(dados.get('email') or '').strip())
            else ['E-mail inválido.']
        ),
        *(
            []
            if str(dados.get('login') or '').strip()
            else ['Informe o login.']
        ),
        *(
            []
            if _valida_membro(perfil, Perfil)
            else [f'Perfil inválido: {perfil!r}.']
        ),
        *(
            []
            if _valida_membro(status, Status)
            else [f'Status inválido: {status!r}.']
        ),
    ]


def senha_forte_o_suficiente(senha: str) -> bool:
    """Diz se a senha atende ao tamanho mínimo exigido.

    Example:
        >>> senha_forte_o_suficiente('curta')
        False
        >>> senha_forte_o_suficiente('senhaGrande1')
        True
    """
    return len(str(senha or '')) >= TAMANHO_MINIMO_SENHA


def montar_usuario(
    dados: Mapping[str, Any],
    senha: str,
    agora: str,
) -> dict[str, Any]:
    """Normaliza o payload de cadastro num registro de usuário.

    A senha entra em texto claro e sai apenas como hash — o texto nunca é
    persistido. ``senha_provisoria`` marca contas que devem trocar a senha
    no primeiro acesso.

    Args:
        dados: Payload do formulário (nome, email, login, perfil, status).
        senha: Senha em texto claro a ser convertida em hash.
        agora: Carimbo ISO da criação.

    Returns:
        Registro pronto para persistir (sem ``id``, definido pelo banco).

    Raises:
        ValueError: Se a senha não atender ao tamanho mínimo.

    Example:
        >>> reg = montar_usuario(
        ...     {'nome': 'Ana', 'email': 'a@x.com', 'login': 'ana'},
        ...     'senhaGrande1', '2026-07-27T09:00:00',
        ... )
        >>> reg['perfil'], reg['status'], reg['senha_provisoria']
        ('OPERADOR', 'ATIVO', True)
    """
    if not senha_forte_o_suficiente(senha):
        raise ValueError(
            f'Senha deve ter ao menos {TAMANHO_MINIMO_SENHA} caracteres.'
        )

    return {
        'nome': str(dados.get('nome') or '').strip(),
        'email': str(dados.get('email') or '').strip().lower(),
        'login': str(dados.get('login') or '').strip().lower(),
        'senha_hash': gerar_hash_senha(senha),
        'perfil': str(dados.get('perfil') or Perfil.OPERADOR.value),
        'status': str(dados.get('status') or Status.ATIVO.value),
        'senha_provisoria': bool(dados.get('senha_provisoria', True)),
        'criado_em': str(agora),
        'atualizado_em': str(agora),
        'ultimo_acesso_em': '',
    }


def montar_admin_padrao(senha: str, agora: str) -> dict[str, Any]:
    """Monta a conta administradora inicial do painel.

    Perfil ADMIN, status ATIVO e senha provisória: força a troca no
    primeiro acesso, para que a senha semeada não vire credencial fixa.

    Args:
        senha: Senha em texto claro do admin (gerada fora, nunca fixa).
        agora: Carimbo ISO da criação.

    Returns:
        Registro do usuário administrador.

    Example:
        >>> a = montar_admin_padrao('senhaGrande1', '2026-07-27T09:00:00')
        >>> a['login'], a['perfil'], a['senha_provisoria']
        ('admin', 'ADMIN', True)
    """
    return montar_usuario(
        {
            'nome': 'Administrador',
            'email': 'admin@alvocard.com.br',
            'login': 'admin',
            'perfil': Perfil.ADMIN.value,
            'status': Status.ATIVO.value,
            'senha_provisoria': True,
        },
        senha,
        agora,
    )
