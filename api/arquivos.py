# INSERIR EM: api/arquivos.py
"""Banco em árvore de arquivos: pasta = tabela, subpasta = competência.

Substitui o SQLite como fonte do painel. O layout é legível e auditável
direto no Explorer::

    <pasta_banco>/
        tabela_concilicacao_convenio/     <- tem competência
            2026-07/
                alvo_card__00011ALV.txt
            2026-06/
                alvo_card__00011ALV.txt
        tabela_contato/                   <- não tem competência
            alvo_card__00011ALV.txt
        tabela_conta_conv/
        tabela_particularidade/
        tabela_secretaria_conv/

Cada ``.txt`` guarda um documento JSON com os registros daquele convênio
naquela tabela (e competência, quando houver).

Duas garantias que arquivo solto não dá de graça:

* **Gravação atômica** — escreve em ``.tmp`` e renomeia. Um leitor nunca
  enxerga arquivo pela metade, mesmo se o processo morrer no meio.
* **Versão otimista** — quem grava informa a versão que leu. Se o arquivo
  mudou nesse meio tempo, a gravação é recusada em vez de apagar em
  silêncio o trabalho do outro operador.
"""

from __future__ import annotations

# --- stdlib ---
import hashlib
import json
import logging
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

CODIFICACAO = 'utf-8'
EXTENSAO = '.txt'
EXTENSAO_TEMPORARIA = '.tmp'
SEPARADOR_NOME = '__'

# Competência como AAAA-MM: ordena sozinha na listagem de pastas.
PADRAO_PASTA_COMPETENCIA = re.compile(r'^\d{4}-\d{2}$')

TAMANHO_VERSAO = 12
CARACTERES_INVALIDOS = re.compile(r'[^a-z0-9]+')


class ArmazenamentoIndisponivelError(RuntimeError):
    """Sinaliza pasta de banco inexistente ou ilegível."""


class ConflitoDeVersaoError(RuntimeError):
    """Sinaliza que o arquivo mudou desde a leitura — gravação recusada."""


# =====================================================================
# Regras puras
# =====================================================================
def apelidar(valor: str) -> str:
    """Reduz um texto a um pedaço de nome de arquivo seguro.

    Args:
        valor: Texto livre (nome de originadora, por exemplo).

    Returns:
        Texto em minúsculas, sem acento e sem caractere proibido pelo
        Windows.

    Example:
        >>> apelidar('Alvo Card')
        'alvo_card'
        >>> apelidar('GOV. GOIÁS')
        'gov_goias'
    """
    sem_acento = unicodedata.normalize('NFKD', valor or '')
    apenas_ascii = sem_acento.encode('ascii', 'ignore').decode('ascii')

    return CARACTERES_INVALIDOS.sub('_', apenas_ascii.lower()).strip('_')


def nome_arquivo(originador: str, numero_convenio: str) -> str:
    """Monta o nome do ``.txt`` de um convênio.

    A originadora entra no nome porque a identidade do convênio é o par
    ``(originador, numero_convenio)`` — dois originadores podem repetir
    o mesmo número.

    Args:
        originador: Originadora dona do convênio.
        numero_convenio: Número do convênio.

    Returns:
        Nome do arquivo, com extensão.

    Example:
        >>> nome_arquivo('Alvo Card', '00011ALV')
        'alvo_card__00011ALV.txt'
    """
    return f'{apelidar(originador)}{SEPARADOR_NOME}{numero_convenio}{EXTENSAO}'


def caminho_registro(
    raiz: Path,
    tabela: str,
    originador: str,
    numero_convenio: str,
    competencia: str | None = None,
) -> Path:
    """Resolve o arquivo de um convênio dentro de uma tabela.

    Args:
        raiz: Pasta do banco.
        tabela: Nome da tabela (vira pasta).
        originador: Originadora do convênio.
        numero_convenio: Número do convênio.
        competencia: Competência ``AAAA-MM``; ``None`` para tabela
            compartilhada, que não se divide por competência.

    Returns:
        Caminho completo do ``.txt``.

    Example:
        >>> caminho_registro(
        ...     Path('/b'), 'tabela_contato', 'Alvo Card', '00011ALV'
        ... ).as_posix()
        '/b/tabela_contato/alvo_card__00011ALV.txt'
    """
    pasta = raiz / tabela
    if competencia:
        pasta = pasta / competencia

    return pasta / nome_arquivo(originador, numero_convenio)


def montar_documento(
    tabela: str,
    originador: str,
    numero_convenio: str,
    registros: list[dict[str, Any]],
    competencia: str | None = None,
) -> dict[str, Any]:
    """Monta o documento JSON gravado no ``.txt``.

    O cabeçalho repete a identidade para o arquivo se explicar sozinho a
    quem abrir no Bloco de Notas, fora da árvore de pastas.

    Args:
        tabela: Tabela de origem.
        originador: Originadora do convênio.
        numero_convenio: Número do convênio.
        registros: Linhas daquele convênio na tabela.
        competencia: Competência ``AAAA-MM``, quando a tabela tiver.

    Returns:
        Documento pronto para serializar.

    Example:
        >>> doc = montar_documento('t', 'Alvo Card', '1', [])
        >>> doc['numero_convenio']
        '1'
    """
    return {
        'tabela': tabela,
        'originador': originador,
        'numero_convenio': numero_convenio,
        'competencia': competencia or '',
        'registros': registros,
    }


def serializar(documento: dict[str, Any]) -> str:
    """Converte o documento em texto JSON legível.

    Args:
        documento: Documento a gravar.

    Returns:
        JSON indentado, com acentuação preservada.

    Example:
        >>> serializar({'a': 'ç'})
        '{\\n  "a": "ç"\\n}'
    """
    return json.dumps(documento, ensure_ascii=False, indent=2)


def desserializar(conteudo: str) -> dict[str, Any]:
    """Lê o documento JSON de um ``.txt``.

    Args:
        conteudo: Texto lido do arquivo.

    Returns:
        Documento; ``registros`` sempre presente como lista.

    Raises:
        ValueError: Se o arquivo não for JSON válido.

    Example:
        >>> desserializar('{"registros": [1]}')['registros']
        [1]
    """
    documento = json.loads(conteudo)
    documento.setdefault('registros', [])

    return documento


def versao_do_conteudo(conteudo: str) -> str:
    """Calcula a versão (hash curto) de um conteúdo de arquivo.

    Args:
        conteudo: Texto do arquivo.

    Returns:
        Prefixo do SHA-256, suficiente para detectar alteração.

    Example:
        >>> len(versao_do_conteudo('x')) == 12
        True
    """
    digest = hashlib.sha256(conteudo.encode(CODIFICACAO)).hexdigest()

    return digest[:TAMANHO_VERSAO]


# =====================================================================
# I/O
# =====================================================================
def garantir_raiz(raiz: Path) -> Path:
    """Valida que a pasta do banco existe.

    Args:
        raiz: Pasta do banco.

    Returns:
        A própria pasta.

    Raises:
        ArmazenamentoIndisponivelError: Se a pasta não existir.

    Example:
        >>> ...  # doctest: +SKIP
    """
    if not raiz.is_dir():
        logger.error('Pasta do banco não encontrada: %s', raiz)
        raise ArmazenamentoIndisponivelError(
            f'Pasta do banco não encontrada: {raiz}'
        )

    return raiz


def ler_arquivo(caminho: Path) -> tuple[dict[str, Any], str] | None:
    """Lê um ``.txt`` do banco.

    Args:
        caminho: Arquivo a ler.

    Returns:
        Par ``(documento, versao)``; ``None`` quando o arquivo não
        existe — ausência é registro inexistente, não erro.

    Raises:
        ArmazenamentoIndisponivelError: Se o arquivo existir mas estiver
            corrompido ou ilegível.

    Example:
        >>> ...  # doctest: +SKIP
    """
    if not caminho.is_file():
        return None

    try:
        conteudo = caminho.read_text(encoding=CODIFICACAO)
        return desserializar(conteudo), versao_do_conteudo(conteudo)
    except (OSError, ValueError) as exc:
        logger.error('Arquivo ilegível em %s: %s', caminho, exc)
        raise ArmazenamentoIndisponivelError(
            f'Arquivo ilegível em {caminho}: {exc}'
        ) from exc


def gravar_arquivo(
    caminho: Path,
    documento: dict[str, Any],
    versao_esperada: str | None = None,
) -> str:
    """Grava um ``.txt`` do banco de forma atômica.

    Escreve em arquivo temporário e renomeia por cima: ninguém lê estado
    parcial. Com ``versao_esperada``, recusa a gravação se o arquivo
    mudou desde a leitura — é o que impede um operador de apagar em
    silêncio a edição do outro.

    Args:
        caminho: Arquivo de destino.
        documento: Documento a gravar.
        versao_esperada: Versão lida antes da edição; ``None`` grava sem
            checar (carga inicial e migração).

    Returns:
        A nova versão do arquivo.

    Raises:
        ConflitoDeVersaoError: Se o arquivo mudou desde a leitura.
        ArmazenamentoIndisponivelError: Se a gravação falhar.

    Example:
        >>> ...  # doctest: +SKIP
    """
    if versao_esperada is not None:
        atual = ler_arquivo(caminho)
        versao_atual = atual[1] if atual else ''
        if versao_atual != versao_esperada:
            logger.warning(
                'Conflito em %s: esperado %s, encontrado %s',
                caminho,
                versao_esperada,
                versao_atual,
            )
            raise ConflitoDeVersaoError(
                f'{caminho.name} foi alterado por outra pessoa. '
                'Recarregue a tela antes de salvar.'
            )

    conteudo = serializar(documento)
    temporario = caminho.with_suffix(EXTENSAO_TEMPORARIA)

    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        temporario.write_text(conteudo, encoding=CODIFICACAO)
        os.replace(temporario, caminho)
    except OSError as exc:
        logger.error('Falha ao gravar %s: %s', caminho, exc)
        temporario.unlink(missing_ok=True)
        raise ArmazenamentoIndisponivelError(
            f'Falha ao gravar {caminho}: {exc}'
        ) from exc

    return versao_do_conteudo(conteudo)


def listar_competencias(raiz: Path, tabela: str) -> list[str]:
    """Lista as competências existentes numa tabela, da mais nova.

    Args:
        raiz: Pasta do banco.
        tabela: Tabela a inspecionar.

    Returns:
        Competências ``AAAA-MM``; vazio quando a tabela não existe.

    Example:
        >>> ...  # doctest: +SKIP
    """
    pasta = raiz / tabela
    if not pasta.is_dir():
        logger.warning('Tabela %s ausente em %s.', tabela, raiz)
        return []

    return sorted(
        (
            sub.name
            for sub in pasta.iterdir()
            if sub.is_dir() and PADRAO_PASTA_COMPETENCIA.match(sub.name)
        ),
        reverse=True,
    )


def listar_documentos(
    raiz: Path, tabela: str, competencia: str | None = None
) -> Iterator[dict[str, Any]]:
    """Percorre os documentos de uma tabela (opcionalmente de um mês).

    Args:
        raiz: Pasta do banco.
        tabela: Tabela a percorrer.
        competencia: Competência ``AAAA-MM``; ``None`` para tabela
            compartilhada.

    Yields:
        Documentos lidos, na ordem do nome do arquivo.

    Example:
        >>> ...  # doctest: +SKIP
    """
    pasta = raiz / tabela
    if competencia:
        pasta = pasta / competencia

    if not pasta.is_dir():
        logger.warning('Sem dados em %s.', pasta)
        return

    for caminho in sorted(pasta.glob(f'*{EXTENSAO}')):
        lido = ler_arquivo(caminho)
        if lido:
            yield lido[0]
