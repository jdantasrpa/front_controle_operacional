# INSERIR EM: api/cripto.py
# DEPENDÊNCIA: pip install cryptography
"""Criptografia de aplicação do SCO (AES-256-GCM) para dados no Supabase.

A "criptografia única da empresa" é a **chave-mestra secreta** — o
algoritmo é o padrão auditado AES-256-GCM (cifra + autenticação). A chave
vem da variável de ambiente ``SCO_CHAVE_MESTRA`` (32 bytes em base64) e
**nunca** é versionada. Gere-a uma vez com :func:`gerar_chave_mestra`.

Este serviço roda no **servidor** (onde a chave é secreta): cifra antes de
gravar no Supabase e decifra depois de ler. Uma página estática pública
não pode guardar a chave — por isso o caminho de escrita/leitura passa
pela API.

Formato do envelope (texto): ``sco1$<nonce_b64>$<ciphertext_b64>``. O nonce
é aleatório por operação, então o mesmo texto gera cifras diferentes (bom
para confidencialidade; ruim para busca por igualdade — ver observação em
:func:`criptografar`).
"""

from __future__ import annotations

# --- stdlib ---
import base64
import os
import secrets
from typing import Any, Iterable, Mapping

# --- terceiros ---
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VARIAVEL_CHAVE = 'SCO_CHAVE_MESTRA'
PREFIXO = 'sco1'
SEPARADOR = '$'
TAMANHO_CHAVE_BYTES = 32
TAMANHO_NONCE_BYTES = 12


class CriptoConfigError(RuntimeError):
    """Sinaliza chave-mestra ausente ou malformada no ambiente."""


class CriptoError(ValueError):
    """Sinaliza cifra inválida, adulterada ou com chave errada."""


def gerar_chave_mestra() -> str:
    """Gera uma chave-mestra AES-256 nova, em base64.

    Rode uma vez, guarde no cofre de segredos e exporte em
    ``SCO_CHAVE_MESTRA``. Trocar a chave torna ilegível o que já foi
    cifrado — planeje rotação com recriptografia.

    Returns:
        32 bytes aleatórios codificados em base64.

    Example:
        >>> chave = gerar_chave_mestra()
        >>> len(base64.b64decode(chave))
        32
    """
    return base64.b64encode(secrets.token_bytes(TAMANHO_CHAVE_BYTES)).decode(
        'ascii'
    )


def _carregar_chave() -> bytes:
    """Lê e valida a chave-mestra do ambiente.

    Raises:
        CriptoConfigError: Se a variável faltar ou não decodificar em 32
            bytes.
    """
    bruto = os.getenv(VARIAVEL_CHAVE)
    if not bruto:
        raise CriptoConfigError(
            f'Defina {VARIAVEL_CHAVE} com a chave-mestra (base64 de 32 bytes).'
        )
    try:
        chave = base64.b64decode(bruto, validate=True)
    except (ValueError, TypeError) as exc:
        raise CriptoConfigError(f'{VARIAVEL_CHAVE} inválida: {exc}') from exc

    if len(chave) != TAMANHO_CHAVE_BYTES:
        raise CriptoConfigError(
            f'{VARIAVEL_CHAVE} deve ter {TAMANHO_CHAVE_BYTES} bytes '
            f'(tem {len(chave)}).'
        )
    return chave


def esta_criptografado(valor: Any) -> bool:
    """Diz se o valor já é um envelope cifrado deste serviço.

    Example:
        >>> esta_criptografado('sco1$abc$def')
        True
        >>> esta_criptografado('texto claro')
        False
    """
    return isinstance(valor, str) and valor.startswith(PREFIXO + SEPARADOR)


def criptografar(texto: Any, chave: bytes | None = None) -> Any:
    """Cifra um texto em envelope AES-256-GCM.

    ``None`` passa direto (para manter ``NULL`` no banco). Valores já
    cifrados não são recifrados. A cifra é **não determinística** (nonce
    aleatório): não use em colunas que precisam de busca por igualdade sem
    um índice cego (HMAC) à parte.

    Args:
        texto: Texto claro a cifrar (convertido para ``str``).
        chave: Chave de 32 bytes; ``None`` lê de ``SCO_CHAVE_MESTRA``.

    Returns:
        ``sco1$<nonce_b64>$<ciphertext_b64>`` ou ``None``.

    Raises:
        CriptoConfigError: Se a chave-mestra não estiver configurada.

    Example:
        >>> import os
        >>> os.environ['SCO_CHAVE_MESTRA'] = gerar_chave_mestra()
        >>> token = criptografar('12.345.678/0001-90')
        >>> token.startswith('sco1$')
        True
    """
    if texto is None or esta_criptografado(texto):
        return texto

    chave = chave or _carregar_chave()
    nonce = secrets.token_bytes(TAMANHO_NONCE_BYTES)
    cifra = AESGCM(chave).encrypt(nonce, str(texto).encode('utf-8'), None)

    return SEPARADOR.join(
        (
            PREFIXO,
            base64.b64encode(nonce).decode('ascii'),
            base64.b64encode(cifra).decode('ascii'),
        )
    )


def descriptografar(token: Any, chave: bytes | None = None) -> Any:
    """Decifra um envelope; devolve texto claro inalterado como está.

    Tolerante a migração: o que não estiver no formato do serviço é tratado
    como já em claro e retornado sem mudança.

    Args:
        token: Envelope ``sco1$...`` ou texto claro.
        chave: Chave de 32 bytes; ``None`` lê de ``SCO_CHAVE_MESTRA``.

    Returns:
        Texto claro, ou ``None``.

    Raises:
        CriptoError: Se o envelope estiver malformado, adulterado ou a
            chave estiver errada.
        CriptoConfigError: Se a chave-mestra não estiver configurada.

    Example:
        >>> import os
        >>> os.environ['SCO_CHAVE_MESTRA'] = gerar_chave_mestra()
        >>> descriptografar(criptografar('segredo'))
        'segredo'
    """
    if token is None or not esta_criptografado(token):
        return token

    partes = token.split(SEPARADOR)
    if len(partes) != 3:
        raise CriptoError('Envelope cifrado malformado.')

    chave = chave or _carregar_chave()
    try:
        nonce = base64.b64decode(partes[1])
        cifra = base64.b64decode(partes[2])
        return AESGCM(chave).decrypt(nonce, cifra, None).decode('utf-8')
    except (InvalidTag, ValueError) as exc:
        raise CriptoError(
            'Falha ao decifrar: chave errada ou dado adulterado.'
        ) from exc


def criptografar_campos(
    registro: Mapping[str, Any], campos: Iterable[str]
) -> dict[str, Any]:
    """Devolve cópia do registro com os campos indicados cifrados.

    Não modifica o registro original. Campos ausentes ou ``None`` são
    ignorados.

    Args:
        registro: Linha a persistir.
        campos: Nomes das colunas sensíveis a cifrar.

    Returns:
        Novo dicionário pronto para gravar no Supabase.

    Example:
        >>> import os
        >>> os.environ['SCO_CHAVE_MESTRA'] = gerar_chave_mestra()
        >>> r = criptografar_campos({'nome': 'X', 'cnpj': '1'}, ['cnpj'])
        >>> r['nome'], esta_criptografado(r['cnpj'])
        ('X', True)
    """
    alvo = set(campos)

    return {
        chave: criptografar(valor) if chave in alvo else valor
        for chave, valor in registro.items()
    }


def descriptografar_campos(
    registro: Mapping[str, Any], campos: Iterable[str]
) -> dict[str, Any]:
    """Devolve cópia do registro com os campos indicados decifrados.

    Args:
        registro: Linha lida do Supabase.
        campos: Nomes das colunas sensíveis a decifrar.

    Returns:
        Novo dicionário pronto para o domínio/front.

    Example:
        >>> import os
        >>> os.environ['SCO_CHAVE_MESTRA'] = gerar_chave_mestra()
        >>> guardado = criptografar_campos({'cnpj': '1'}, ['cnpj'])
        >>> descriptografar_campos(guardado, ['cnpj'])['cnpj']
        '1'
    """
    alvo = set(campos)

    return {
        chave: descriptografar(valor) if chave in alvo else valor
        for chave, valor in registro.items()
    }
