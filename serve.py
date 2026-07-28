# INSERIR EM: serve.py
# DEPENDÊNCIA: pip install fastapi uvicorn
"""Ponto de entrada do painel Controle Operacional.

Sobe o servidor FastAPI (que serve o front e a API de leitura dos bancos)
e abre o navegador na porta configurada em ``config_projeto.ini``.

Uso:
    python serve.py
"""

from __future__ import annotations

# --- stdlib ---
import logging
import threading
import webbrowser

# --- terceiros ---
import uvicorn

# --- locais ---
from api.config import obter_configuracao

logger = logging.getLogger(__name__)

ATRASO_ABERTURA_SEGUNDOS = 1.5


def agendar_abertura_navegador(url: str) -> None:
    """Abre o navegador logo após o servidor subir.

    Args:
        url: Endereço do painel.

    Example:
        >>> agendar_abertura_navegador('http://127.0.0.1:8000')
    """
    threading.Timer(
        ATRASO_ABERTURA_SEGUNDOS, webbrowser.open, args=(url,)
    ).start()


def executar() -> None:
    """Sobe o servidor do painel usando a configuração do projeto.

    Example:
        >>> executar()  # doctest: +SKIP
    """
    config = obter_configuracao()
    url = f'http://{config.host}:{config.porta}'

    logger.info('Conciliação: %s', config.banco_conciliacao)
    logger.info('Cobrança:    %s', config.banco_cobranca)
    logger.info('Painel em:   %s', url)

    agendar_abertura_navegador(url)
    uvicorn.run('api.app:app', host=config.host, port=config.porta)


if __name__ == '__main__':
    executar()
