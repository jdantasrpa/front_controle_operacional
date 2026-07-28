"""API de leitura do Controle Operacional (Alvo Card).

Camada que expõe, em JSON, os dados que hoje o front lia de arquivos
.xlsx/.csv. As fontes são os bancos SQLite do próprio projeto:

* Conciliação (COFCT) -> Extrato, Retorno e Conciliação
* bd_cobranca_financeiro.db -> módulo Cobrança PJ (leitura e escrita)
"""

__all__ = ['__version__']

__version__ = '1.0.0'
