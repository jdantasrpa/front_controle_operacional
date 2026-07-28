# INSERIR EM: app_desktop.py
# DEPENDÊNCIA: pip install pywebview
"""Janela nativa do painel Controle Operacional (pywebview).

Sobe o FastAPI em ``127.0.0.1`` dentro do próprio processo e abre a
janela apontando para ele — o operador não vê navegador nem terminal.

Se a porta configurada estiver ocupada (outra instância já aberta, ou
qualquer serviço do parque), escolhe uma porta livre em vez de falhar:
duas janelas abertas ao mesmo tempo não brigam entre si.

Uso:
    python app_desktop.py
"""

from __future__ import annotations

# --- stdlib ---
import logging
import socket
import threading
import time

# --- terceiros ---
import uvicorn
import webview

# --- locais ---
from api.config import obter_configuracao

logger = logging.getLogger(__name__)

TITULO_JANELA = 'Alvo Card — Controle Operacional'
LARGURA_JANELA = 1440
ALTURA_JANELA = 900
LARGURA_MINIMA = 1024
ALTURA_MINIMA = 700

TEMPO_LIMITE_SERVIDOR_SEGUNDOS = 20.0
INTERVALO_ESPERA_SEGUNDOS = 0.1

# Porta 0 faz o SO escolher uma livre.
PORTA_EFEMERA = 0


class ServidorNaoSubiuError(RuntimeError):
    """Sinaliza que o FastAPI não ficou pronto no tempo esperado."""


def porta_disponivel(host: str, porta: int) -> bool:
    """Informa se dá para escutar no par host/porta.

    Args:
        host: Endereço de escuta.
        porta: Porta desejada.

    Returns:
        ``True`` quando a porta está livre.

    Example:
        >>> porta_disponivel('127.0.0.1', 0)
        True
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tomada:
        try:
            tomada.bind((host, porta))
            return True
        except OSError:
            return False


def escolher_porta(host: str, preferida: int) -> int:
    """Devolve a porta preferida, ou uma livre quando ela está ocupada.

    Args:
        host: Endereço de escuta.
        preferida: Porta do ``config_projeto.ini``.

    Returns:
        Porta a usar nesta execução.

    Example:
        >>> escolher_porta('127.0.0.1', 0) >= 0
        True
    """
    if porta_disponivel(host, preferida):
        return preferida

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tomada:
        tomada.bind((host, PORTA_EFEMERA))
        porta = tomada.getsockname()[1]

    logger.warning(
        'Porta %s ocupada; usando %s nesta instância.', preferida, porta
    )
    return porta


def criar_servidor(host: str, porta: int) -> uvicorn.Server:
    """Monta o servidor FastAPI que a janela vai consumir.

    Args:
        host: Endereço de escuta.
        porta: Porta de escuta.

    Returns:
        Servidor configurado, ainda não iniciado.

    Example:
        >>> criar_servidor('127.0.0.1', 8000).config.port
        8000
    """
    configuracao = uvicorn.Config(
        'api.app:app',
        host=host,
        port=porta,
        log_level='info',
        access_log=False,
    )
    return uvicorn.Server(configuracao)


def iniciar_em_segundo_plano(servidor: uvicorn.Server) -> threading.Thread:
    """Sobe o servidor numa thread daemon e espera ficar pronto.

    Args:
        servidor: Servidor criado por :func:`criar_servidor`.

    Returns:
        A thread em execução.

    Raises:
        ServidorNaoSubiuError: Se o servidor não ficar pronto a tempo.

    Example:
        >>> ...  # doctest: +SKIP
    """
    thread = threading.Thread(target=servidor.run, daemon=True)
    thread.start()

    limite = time.monotonic() + TEMPO_LIMITE_SERVIDOR_SEGUNDOS
    while not servidor.started:
        if not thread.is_alive() or time.monotonic() > limite:
            raise ServidorNaoSubiuError(
                'O servidor do painel não respondeu a tempo. '
                'Verifique o log acima.'
            )
        time.sleep(INTERVALO_ESPERA_SEGUNDOS)

    return thread


def executar() -> None:
    """Abre a janela do painel e encerra o servidor ao fechá-la.

    Raises:
        ServidorNaoSubiuError: Se o FastAPI não ficar pronto.

    Example:
        >>> executar()  # doctest: +SKIP
    """
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    )
    config = obter_configuracao()
    porta = escolher_porta(config.host, config.porta)
    servidor = criar_servidor(config.host, porta)

    logger.info('Banco de arquivos: %s', config.pasta_banco)
    logger.info('Painel em: http://%s:%s', config.host, porta)

    iniciar_em_segundo_plano(servidor)

    webview.create_window(
        TITULO_JANELA,
        f'http://{config.host}:{porta}',
        width=LARGURA_JANELA,
        height=ALTURA_JANELA,
        min_size=(LARGURA_MINIMA, ALTURA_MINIMA),
    )

    try:
        # Bloqueia até o operador fechar a janela.
        webview.start()
    finally:
        logger.info('Janela fechada; encerrando o servidor.')
        servidor.should_exit = True


if __name__ == '__main__':
    executar()
