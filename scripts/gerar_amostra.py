# INSERIR EM: scripts/gerar_amostra.py
"""Gera uma amostra de 2 anos no schema real do COFCT.

Cria um SQLite com ``tabela_concilicacao_convenio`` e as tabelas
compartilhadas (conta, contato, particularidade) para exercitar o painel
no modo **dados reais**, sem tocar no mock que os testes usam.

Cada linha da conciliação é um **vencimentário**: a competência
(``mes_referencia_conciliacao``) mais a data de vencimento daquele ciclo.
Convênios com dois vencimentos no mês geram duas linhas na competência.

A geração é determinística: mesma semente, mesmo banco.

Uso:
    python scripts/gerar_amostra.py
    python scripts/gerar_amostra.py --destino doc/amostra.db --meses 24
"""

from __future__ import annotations

# --- stdlib ---
import argparse
import calendar
import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from random import Random
from typing import Any, Iterable, Sequence

logger = logging.getLogger(__name__)

RAIZ_PROJETO = Path(__file__).resolve().parents[1]
DESTINO_PADRAO = RAIZ_PROJETO / 'doc' / 'amostra_2anos.db'

MESES_DE_AMOSTRA = 24
SEMENTE_PADRAO = 2026

# Competências recentes ainda não fecharam: quanto mais nova, maior a
# chance de o repasse estar pendente.
MESES_EM_ABERTO = 2
CHANCE_PENDENTE_RECENTE = 0.55
CHANCE_PENDENTE_ANTIGO = 0.08
CHANCE_PARCIAL = 0.18

DIAS_ANTES_REMESSA = 3
DIAS_ANTES_CORTE = 2

MOTIVOS_PARCIAL = (
    'Arquivo retorno não disponível',
    'Outros',
)
MOTIVO_SEM_REPASSE = 'Falta de repasse do convênio'

STATUS_CONCILIADO = 'CONCILIADO'
STATUS_PARCIAL = 'CONCILIADO (PARCIAL)'
STATUS_PENDENTE = 'PENDENTE'


@dataclass(frozen=True)
class Convenio:
    """Convênio da amostra e o comportamento dos seus repasses.

    Attributes:
        originador: Originadora dona do convênio.
        numero_convenio: Número do convênio no COFCT.
        nome_convenio: Nome exibido no painel.
        cnpj_convenio: CNPJ formatado.
        averbadora: Averbadora do convênio.
        dias_vencimento: Dias do mês em que vence — dois dias geram dois
            vencimentários por competência.
        valor_base: Valor de remessa típico, antes da variação mensal.
    """

    originador: str
    numero_convenio: str
    nome_convenio: str
    cnpj_convenio: str
    averbadora: str
    dias_vencimento: tuple[int, ...]
    valor_base: float


CONVENIOS: tuple[Convenio, ...] = (
    Convenio(
        'Alvo Card',
        '00001ALV',
        'AERONÁUTICA',
        '00.394.429/0082-76',
        'Zetra',
        (5, 20),
        300000.00,
    ),
    Convenio(
        'Alvo Card',
        '00011ALV',
        'GOV. GOIÁS',
        '02.476.034/0001-82',
        'Zetra',
        (5, 20),
        700000.00,
    ),
    Convenio(
        'Alvo Card',
        '00021ALV',
        'GOV. ALAGOAS',
        '12.200.184/0001-12',
        'Neoconsig',
        (8,),
        620000.00,
    ),
    Convenio(
        'Alvo Card',
        '00031ALV',
        'ASSEMBLEIA MATO GROSSO',
        '03.929.049/0001-11',
        'Neoconsig',
        (7,),
        205000.00,
    ),
    Convenio(
        'Alvo Card',
        '00041ALV',
        'PREF. GOIÂNIA',
        '01.612.092/0001-23',
        'Consigfácil',
        (6,),
        890000.00,
    ),
    Convenio(
        'Alvo Card',
        '00051ALV',
        'TJ GOIÁS',
        '02.938.150/0001-90',
        'Zetra',
        (9,),
        342000.00,
    ),
    Convenio(
        'Hatchbank',
        '00061HTC',
        'PREF. ANÁPOLIS',
        '01.809.176/0001-03',
        'Consigfácil',
        (10, 25),
        158000.00,
    ),
    Convenio(
        'Hatchbank',
        '00071HTC',
        'GOV. TOCANTINS',
        '01.786.029/0001-03',
        'Zetra',
        (12,),
        430000.00,
    ),
)

CONTATOS_POR_CONVENIO = (
    ('Financeiro', 'ATIVO', 'Marina Alves', 'marina.alves'),
    ('Tesouraria', 'ATIVO', 'Ricardo Nunes', 'ricardo.nunes'),
    ('Folha', 'INATIVO', 'Contato antigo', 'antigo'),
)

BANCOS = ('Banco do Brasil', 'Caixa Econômica', 'Itaú', 'Bradesco')

RUBRICAS = ('Consignado 001', 'Consignado 002', 'Cartão benefício')
MODELOS_AVERBACAO = ('MARGEM', 'FOLHA')


# =====================================================================
# Regras puras — nenhuma toca banco
# =====================================================================
def competencias(referencia: date, meses: int) -> tuple[str, ...]:
    """Lista as competências ``AAAA-MM`` terminando na de referência.

    Args:
        referencia: Mês final da amostra.
        meses: Quantidade de competências a gerar.

    Returns:
        Competências da mais antiga para a mais nova.

    Example:
        >>> competencias(date(2026, 2, 10), 3)
        ('2025-12', '2026-01', '2026-02')
    """
    indice_final = referencia.year * 12 + (referencia.month - 1)
    indices = range(indice_final - meses + 1, indice_final + 1)

    return tuple(
        f'{indice // 12:04d}-{indice % 12 + 1:02d}' for indice in indices
    )


def data_do_vencimento(competencia: str, dia: int) -> date:
    """Resolve a data de vencimento dentro da competência.

    Meses curtos recebem o último dia disponível, para nunca gerar data
    inválida (ex.: dia 30 em fevereiro).

    Args:
        competencia: Competência ``AAAA-MM``.
        dia: Dia do mês em que o convênio vence.

    Returns:
        Data de vencimento daquele vencimentário.

    Example:
        >>> data_do_vencimento('2026-02', 30)
        datetime.date(2026, 2, 28)
    """
    ano, mes = (int(parte) for parte in competencia.split('-'))
    ultimo_dia = calendar.monthrange(ano, mes)[1]

    return date(ano, mes, min(dia, ultimo_dia))


def _iso(momento: date) -> str:
    """Formata a data no padrão do banco (``AAAA-MM-DD``)."""
    return momento.isoformat()


def sortear_desfecho(
    sorteio: Random, meses_atras: int
) -> tuple[str, float, str]:
    """Sorteia como o repasse daquele vencimentário terminou.

    Competência recente tem mais chance de estar pendente; competência
    antiga já deveria ter fechado.

    Args:
        sorteio: Gerador determinístico.
        meses_atras: Distância da competência até o mês de referência.

    Returns:
        Tupla ``(status, fracao_repassada, motivo)``.

    Example:
        >>> status, fracao, _ = sortear_desfecho(Random(1), 20)
        >>> status in (
        ...     'CONCILIADO', 'CONCILIADO (PARCIAL)', 'PENDENTE'
        ... )
        True
    """
    chance_pendente = (
        CHANCE_PENDENTE_RECENTE
        if meses_atras < MESES_EM_ABERTO
        else CHANCE_PENDENTE_ANTIGO
    )
    dado = sorteio.random()

    if dado < chance_pendente:
        return STATUS_PENDENTE, 0.0, MOTIVO_SEM_REPASSE

    if dado < chance_pendente + CHANCE_PARCIAL:
        return (
            STATUS_PARCIAL,
            sorteio.uniform(0.45, 0.95),
            sorteio.choice(MOTIVOS_PARCIAL),
        )

    return STATUS_CONCILIADO, 1.0, ''


def montar_vencimentario(
    convenio: Convenio,
    competencia: str,
    dia: int,
    meses_atras: int,
    sorteio: Random,
) -> dict[str, Any]:
    """Monta uma linha de ``tabela_concilicacao_convenio``.

    Args:
        convenio: Convênio da amostra.
        competencia: Competência ``AAAA-MM``.
        dia: Dia de vencimento do ciclo.
        meses_atras: Distância da competência até o mês de referência.
        sorteio: Gerador determinístico.

    Returns:
        Registro pronto para o INSERT, no schema do COFCT.

    Example:
        >>> linha = montar_vencimentario(
        ...     CONVENIOS[0], '2025-03', 5, 10, Random(7)
        ... )
        >>> linha['mes_referencia_conciliacao']
        '2025-03'
    """
    vencimento = data_do_vencimento(competencia, dia)
    status, fracao_repasse, motivo = sortear_desfecho(sorteio, meses_atras)

    remessa = round(convenio.valor_base * sorteio.uniform(0.82, 1.18), 2)
    inadimplencia = round(sorteio.uniform(0.0, 4.5), 2)
    retorno = round(remessa * (1 - inadimplencia / 100), 2)
    repasse = round(retorno * fracao_repasse, 2)

    dias_atraso = 0 if status == STATUS_CONCILIADO else sorteio.randint(3, 25)
    baixa = vencimento + timedelta(days=sorteio.randint(0, 2) + dias_atraso)

    return {
        'originador': convenio.originador,
        'mes_referencia_conciliacao': competencia,
        'numero_convenio': convenio.numero_convenio,
        'nome_convenio': convenio.nome_convenio,
        'cnpj_convenio': convenio.cnpj_convenio,
        'data_vencimento': _iso(vencimento),
        'data_env_remessa': _iso(
            vencimento - timedelta(days=DIAS_ANTES_REMESSA)
        ),
        'data_sla_concilicacao': _iso(baixa),
        'qtd_dias_sla_pagamento': str((baixa - vencimento).days),
        'data_corte': (
            ''
            if status == STATUS_PENDENTE
            else _iso(vencimento - timedelta(days=DIAS_ANTES_CORTE))
        ),
        'valor_remessa': remessa,
        'valor_retorno': retorno,
        'valor_repasse': repasse,
        'status_conciliacao': status,
        'motivo_falta_conciliacao': motivo,
        'porcentagem_inadimplencia': (
            100.0 if status == STATUS_PENDENTE else inadimplencia
        ),
        'criado_em': _iso(vencimento),
        'atualizado_em': _iso(baixa),
    }


def montar_conciliacoes(
    meses: int, referencia: date, semente: int
) -> list[dict[str, Any]]:
    """Gera os vencimentários de todos os convênios no período.

    Args:
        meses: Quantidade de competências.
        referencia: Mês final da amostra.
        semente: Semente do gerador, para reprodutibilidade.

    Returns:
        Uma linha por (convênio, competência, dia de vencimento).

    Example:
        >>> linhas = montar_conciliacoes(2, date(2026, 7, 1), 1)
        >>> len(linhas) == 2 * sum(len(c.dias_vencimento) for c in CONVENIOS)
        True
    """
    sorteio = Random(semente)
    meses_da_amostra = competencias(referencia, meses)
    ultimo = len(meses_da_amostra) - 1

    return [
        montar_vencimentario(
            convenio, competencia, dia, ultimo - posicao, sorteio
        )
        for convenio in CONVENIOS
        for posicao, competencia in enumerate(meses_da_amostra)
        for dia in convenio.dias_vencimento
    ]


def montar_contatos(semente: int) -> list[dict[str, Any]]:
    """Gera os contatos compartilhados de cada convênio."""
    sorteio = Random(semente + 1)

    return [
        {
            'originador': convenio.originador,
            'numero_convenio': convenio.numero_convenio,
            'nome_convenio': convenio.nome_convenio,
            'cnpj_convenio': convenio.cnpj_convenio,
            'area': area,
            'status': status,
            'nome': nome,
            'email': f'{usuario}@{convenio.numero_convenio.lower()}.gov.br',
            'telefone': (
                f'({sorteio.randint(11, 99)}) '
                f'9{sorteio.randint(1000, 9999)}-{sorteio.randint(1000, 9999)}'
            ),
            'observacao': '',
            'criado_em': '',
            'atualizado_em': '',
        }
        for convenio in CONVENIOS
        for area, status, nome, usuario in CONTATOS_POR_CONVENIO
    ]


def montar_contas(semente: int) -> list[dict[str, Any]]:
    """Gera uma conta bancária ativa por convênio."""
    sorteio = Random(semente + 2)

    return [
        {
            'originador': convenio.originador,
            'numero_convenio': convenio.numero_convenio,
            'nome_convenio': convenio.nome_convenio,
            'cnpj_convenio': convenio.cnpj_convenio,
            'banco': sorteio.choice(BANCOS),
            'agencia': f'{sorteio.randint(1000, 9999)}-{sorteio.randint(0, 9)}',
            'conta': f'{sorteio.randint(10000, 99999)}-{sorteio.randint(0, 9)}',
            'chave_pix': convenio.cnpj_convenio,
            'cnpj': convenio.cnpj_convenio,
            'status_conta': 'ATIVA',
            'criado_em': '',
            'atualizado_em': '',
        }
        for convenio in CONVENIOS
    ]


def montar_particularidades(semente: int) -> list[dict[str, Any]]:
    """Gera uma particularidade por convênio, parte delas com retenção."""
    sorteio = Random(semente + 3)

    def _uma(convenio: Convenio) -> dict[str, Any]:
        tem_retencao = sorteio.random() < 0.4
        percentual = round(sorteio.uniform(1.0, 3.5), 2)

        return {
            'originador': convenio.originador,
            'numero_convenio': convenio.numero_convenio,
            'nome_convenio': convenio.nome_convenio,
            'cnpj_convenio': convenio.cnpj_convenio,
            'rubrica_produto': sorteio.choice(RUBRICAS),
            'modelo_de_averbacao': sorteio.choice(MODELOS_AVERBACAO),
            'retencao': 'SIM' if tem_retencao else 'NÃO',
            'qual_retencao': f'{percentual}%' if tem_retencao else '',
            'telefone': '',
            'observacao': (
                f'Retenção de {percentual}% sobre o repasse.'
                if tem_retencao
                else ''
            ),
            'criado_em': '',
            'atualizado_em': '',
            'status_particularidade': 'ATIVA',
            'retencao_valor': '',
            'retencao_percent': str(percentual) if tem_retencao else '',
        }

    return [_uma(convenio) for convenio in CONVENIOS]


def montar_cadastro_convenios() -> list[dict[str, Any]]:
    """Gera ``gestao_convenios_originador`` a partir dos convênios."""
    return [
        {
            'originador': convenio.originador,
            'numero_convenio': convenio.numero_convenio,
            'nome_convenio': convenio.nome_convenio,
            'cnpj_convenio': convenio.cnpj_convenio,
            'averbadora': convenio.averbadora,
        }
        for convenio in CONVENIOS
    ]


# =====================================================================
# I/O — criação do banco
# =====================================================================
SQL_SCHEMA = """
CREATE TABLE gestao_convenios_originador (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  originador TEXT, numero_convenio TEXT, nome_convenio TEXT,
  cnpj_convenio TEXT, averbadora TEXT
);

CREATE TABLE tabela_concilicacao_convenio (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  originador TEXT, mes_referencia_conciliacao TEXT, numero_convenio TEXT,
  nome_convenio TEXT, cnpj_convenio TEXT, data_vencimento TEXT,
  data_env_remessa TEXT, data_sla_concilicacao TEXT,
  qtd_dias_sla_pagamento TEXT, data_corte TEXT,
  valor_remessa REAL, valor_retorno REAL, valor_repasse REAL,
  status_conciliacao TEXT, motivo_falta_conciliacao TEXT,
  porcentagem_inadimplencia REAL, criado_em TEXT, atualizado_em TEXT
);

CREATE TABLE tabela_conta_conv (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  originador TEXT, numero_convenio TEXT, nome_convenio TEXT,
  cnpj_convenio TEXT, banco TEXT, agencia TEXT, conta TEXT,
  chave_pix TEXT, cnpj TEXT, status_conta TEXT,
  criado_em TEXT, atualizado_em TEXT
);

CREATE TABLE tabela_contato (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  originador TEXT, numero_convenio TEXT, nome_convenio TEXT,
  cnpj_convenio TEXT, area TEXT, status TEXT, nome TEXT, email TEXT,
  telefone TEXT, observacao TEXT, criado_em TEXT, atualizado_em TEXT
);

CREATE TABLE tabela_particularidade (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  originador TEXT, numero_convenio TEXT, nome_convenio TEXT,
  cnpj_convenio TEXT, rubrica_produto TEXT, modelo_de_averbacao TEXT,
  retencao TEXT, qual_retencao TEXT, telefone TEXT, observacao TEXT,
  criado_em TEXT, atualizado_em TEXT, status_particularidade TEXT,
  retencao_valor TEXT, retencao_percent TEXT
);

CREATE TABLE log_registros_padrao (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tabela TEXT, convenio TEXT, originador TEXT, nome_usuario TEXT,
  data_registro TEXT, hora_registro TEXT, json_dados_editados TEXT
);

CREATE INDEX idx_conciliacao_competencia
  ON tabela_concilicacao_convenio (mes_referencia_conciliacao, originador);
CREATE INDEX idx_conciliacao_convenio
  ON tabela_concilicacao_convenio (originador, numero_convenio);
"""


def inserir(
    conexao: sqlite3.Connection,
    tabela: str,
    registros: Sequence[dict[str, Any]],
) -> int:
    """Insere registros em lote, derivando as colunas do primeiro item.

    Args:
        conexao: Conexão SQLite ativa.
        tabela: Tabela de destino.
        registros: Linhas a inserir; todas com as mesmas chaves.

    Returns:
        Quantidade de linhas inseridas.

    Example:
        >>> ...  # doctest: +SKIP
    """
    if not registros:
        return 0

    colunas = tuple(registros[0])
    marcadores = ', '.join('?' for _ in colunas)
    sql = (
        f'INSERT INTO {tabela} ({", ".join(colunas)}) '
        f'VALUES ({marcadores})'
    )

    conexao.executemany(
        sql,
        [
            tuple(registro[coluna] for coluna in colunas)
            for registro in registros
        ],
    )
    return len(registros)


def gerar_amostra(
    destino: Path,
    meses: int = MESES_DE_AMOSTRA,
    semente: int = SEMENTE_PADRAO,
    referencia: date | None = None,
) -> dict[str, int]:
    """Cria o banco de amostra do zero e devolve a contagem por tabela.

    Args:
        destino: Arquivo .db a criar. É sobrescrito se já existir.
        meses: Quantidade de competências (24 = 2 anos).
        semente: Semente do gerador, para reprodutibilidade.
        referencia: Mês final da amostra; ``None`` usa o mês corrente.

    Returns:
        Dicionário ``tabela -> linhas inseridas``.

    Raises:
        sqlite3.Error: Propaga falha de criação do banco após log.

    Example:
        >>> ...  # doctest: +SKIP
    """
    mes_final = referencia or date.today().replace(day=1)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.unlink(missing_ok=True)

    dados = {
        'gestao_convenios_originador': montar_cadastro_convenios(),
        'tabela_concilicacao_convenio': montar_conciliacoes(
            meses, mes_final, semente
        ),
        'tabela_conta_conv': montar_contas(semente),
        'tabela_contato': montar_contatos(semente),
        'tabela_particularidade': montar_particularidades(semente),
    }

    try:
        with sqlite3.connect(destino) as conexao:
            conexao.executescript(SQL_SCHEMA)
            contagem = {
                tabela: inserir(conexao, tabela, registros)
                for tabela, registros in dados.items()
            }
    except sqlite3.Error as exc:
        logger.error('Falha ao gerar %s: %s', destino, exc)
        raise

    logger.info('Amostra gerada em %s: %s', destino, contagem)
    return contagem


def _argumentos(argv: Iterable[str] | None = None) -> argparse.Namespace:
    """Lê os argumentos de linha de comando."""
    analisador = argparse.ArgumentParser(
        description='Gera uma amostra de 2 anos no schema do COFCT.'
    )
    analisador.add_argument(
        '--destino',
        type=Path,
        default=DESTINO_PADRAO,
        help=f'Arquivo .db a criar (padrão: {DESTINO_PADRAO}).',
    )
    analisador.add_argument(
        '--meses',
        type=int,
        default=MESES_DE_AMOSTRA,
        help='Quantidade de competências (padrão: 24).',
    )
    analisador.add_argument(
        '--semente',
        type=int,
        default=SEMENTE_PADRAO,
        help='Semente do gerador (padrão: 2026).',
    )
    return analisador.parse_args(list(argv) if argv is not None else None)


def main() -> None:
    """Ponto de entrada de linha de comando."""
    logging.basicConfig(
        level=logging.INFO, format='%(levelname)-8s | %(message)s'
    )
    argumentos = _argumentos()

    contagem = gerar_amostra(
        argumentos.destino, argumentos.meses, argumentos.semente
    )

    print(f'Amostra criada em: {argumentos.destino}')
    for tabela, linhas in contagem.items():
        print(f'  {tabela}: {linhas} linha(s)')
    print(
        '\nPara usar no painel, aponte o config_projeto.ini:\n'
        f'  [FRONT]\n  banco_conciliacao = '
        f'{argumentos.destino.relative_to(RAIZ_PROJETO).as_posix()}'
    )


if __name__ == '__main__':
    main()
