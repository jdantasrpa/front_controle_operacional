# INSERIR EM: scripts/gerar_der_drawio.py
"""Gera o DER do SCO em formato draw.io (.drawio) a partir da definicao
relacional das entidades. Executar: ``python scripts/gerar_der_drawio.py``.
"""

# --- stdlib ---
import logging
from html import escape
from pathlib import Path

logger = logging.getLogger(__name__)

DESTINO = Path(__file__).resolve().parent.parent / 'docs' / 'der_sco.drawio'
LARGURA = 240
ALTURA_LINHA = 24
ALTURA_CABECALHO = 26
GAP_VERTICAL = 40
LARGURA_COLUNA = 300

ESTILO_ENTIDADE = (
    'swimlane;fontStyle=1;childLayout=stackLayout;horizontal=1;'
    'startSize=26;horizontalStack=0;resizeParent=1;resizeParentMax=0;'
    'collapsible=1;marginBottom=0;rounded=0;shadow=0;strokeColor=#4a6572;'
    'fillColor=#eef3f5;'
)
ESTILO_LINHA = (
    'text;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;'
    'spacingLeft=6;spacingRight=6;overflow=hidden;rotatable=0;'
    'points=[[0,0.5],[1,0.5]];portConstraint=eastwest;fontSize=11;'
)
ESTILO_ARESTA = (
    'edgeStyle=entityRelationEdgeStyle;fontSize=10;html=1;endArrow=%s;'
    'startArrow=%s;rounded=0;exitX=1;exitY=0.5;entryX=0;entryY=0.5;'
)

UM = 'ERmandOne'
MUITOS = 'ERzeroToMany'
ZERO_UM = 'ERzeroToOne'

# entidade -> (coluna, [(campo, tipo, marcador)])
ENTIDADES: dict[str, tuple[int, list[tuple[str, str, str]]]] = {
    'originadora': (
        0,
        [
            ('id', 'bigint', 'PK'),
            ('nome', 'text', 'UK'),
            ('codigo', 'text', 'UK'),
            ('cnpj', 'text', ''),
            ('status', 'text', ''),
            ('observacao', 'text', ''),
            ('criado_em', 'timestamptz', ''),
        ],
    ),
    'gerencia_originadora': (
        0,
        [
            ('id', 'bigint', 'PK'),
            ('originadora_id', 'bigint', 'FK'),
            ('em_conciliacao_ativa', 'boolean', ''),
            ('ator', 'text', ''),
        ],
    ),
    'convenio': (
        0,
        [
            ('id', 'bigint', 'PK'),
            ('cnpj', 'text', 'UK'),
            ('nome', 'text', ''),
            ('averbadora', 'text', ''),
            ('status', 'text', ''),
            ('status_producao', 'text', ''),
            ('gestora_margem', 'text', ''),
            ('link_gestora', 'text', ''),
            ('observacao', 'text', ''),
        ],
    ),
    'grupo': (
        0,
        [('id', 'bigint', 'PK'), ('nome', 'text', 'UK')],
    ),
    'convenio_grupo': (
        0,
        [('convenio_id', 'bigint', 'FK'), ('grupo_id', 'bigint', 'FK')],
    ),
    'vinculo': (
        1,
        [
            ('id', 'bigint', 'PK'),
            ('originadora_id', 'bigint', 'FK'),
            ('convenio_id', 'bigint', 'FK'),
            ('numero_convenio', 'text', 'UK'),
            ('status', 'text', ''),
            ('competencia_inicio', 'char(7)', ''),
            ('competencia_fim', 'char(7)', ''),
            ('observacao', 'text', ''),
        ],
    ),
    'gerencia_conciliacao': (
        1,
        [
            ('id', 'bigint', 'PK'),
            ('vinculo_id', 'bigint', 'FK'),
            ('em_conciliacao_ativa', 'boolean', ''),
            ('dia_vencimento', 'int', ''),
            ('dias_antes_remessa', 'int', ''),
            ('qtd_dias_sla_pagamento', 'int', ''),
            ('dias_antes_corte', 'int', ''),
            ('ator', 'text', ''),
        ],
    ),
    'custo': (
        1,
        [
            ('id', 'bigint', 'PK'),
            ('vinculo_id', 'bigint', 'FK'),
            ('metodo', 'text', ''),
            ('base_calculo', 'text', ''),
            ('aliquota_percentual', 'numeric', ''),
            ('valor_fixo', 'numeric', ''),
            ('valor_unitario', 'numeric', ''),
            ('competencia_inicio', 'char(7)', ''),
            ('competencia_fim', 'char(7)', ''),
            ('status', 'text', ''),
        ],
    ),
    'custo_faixa': (
        1,
        [
            ('id', 'bigint', 'PK'),
            ('custo_id', 'bigint', 'FK'),
            ('ate', 'numeric', ''),
            ('aliquota_percentual', 'numeric', ''),
            ('valor_fixo', 'numeric', ''),
            ('valor_unitario', 'numeric', ''),
        ],
    ),
    'vencimentario': (
        2,
        [
            ('id', 'bigint', 'PK'),
            ('vinculo_id', 'bigint', 'FK'),
            ('competencia', 'char(7)', ''),
            ('data_vencimento', 'date', ''),
            ('data_env_remessa', 'date', ''),
            ('data_sla_conciliacao', 'date', ''),
            ('data_corte', 'date', ''),
            ('valor_remessa', 'numeric', ''),
            ('valor_retorno', 'numeric', ''),
            ('valor_repasse', 'numeric', ''),
            ('status_conciliacao', 'text', ''),
            ('motivo_falta_conciliacao', 'text', ''),
            ('porcentagem_inadimplencia', 'numeric', ''),
        ],
    ),
    'remessa_envio': (
        2,
        [
            ('id', 'bigint', 'PK'),
            ('vencimentario_id', 'bigint', 'FK'),
            ('situacao', 'text', ''),
            ('data_envio', 'date', ''),
            ('usuario', 'text', ''),
            ('observacao', 'text', ''),
        ],
    ),
    'repasse': (
        2,
        [
            ('id', 'bigint', 'PK'),
            ('vencimentario_id', 'bigint', 'FK'),
            ('custo_id', 'bigint', 'FK'),
            ('secretaria', 'text', ''),
            ('status_financeiro', 'text', ''),
            ('data_recebimento', 'date', ''),
            ('valor_recebido', 'numeric', ''),
            ('quantidade', 'int', ''),
            ('custo_aplicado', 'numeric', ''),
            ('devendo', 'numeric', ''),
            ('observacao', 'text', ''),
        ],
    ),
    'secretaria': (
        2,
        [
            ('id', 'bigint', 'PK'),
            ('vinculo_id', 'bigint', 'FK'),
            ('status', 'text', ''),
            ('nome', 'text', ''),
            ('codigo', 'text', ''),
            ('observacao', 'text', ''),
        ],
    ),
    'particularidade': (
        3,
        [
            ('id', 'bigint', 'PK'),
            ('vinculo_id', 'bigint', 'FK'),
            ('status', 'text', ''),
            ('rubrica_produto', 'text', ''),
            ('modelo_averbacao', 'text', ''),
            ('modelo_envio', 'text', ''),
            ('observacao', 'text', ''),
        ],
    ),
    'conta': (
        3,
        [
            ('id', 'bigint', 'PK'),
            ('vinculo_id', 'bigint', 'FK'),
            ('status', 'text', ''),
            ('banco', 'text', ''),
            ('agencia', 'text', ''),
            ('conta', 'text', ''),
            ('chave_pix', 'text', ''),
            ('cnpj', 'text', ''),
        ],
    ),
    'contato': (
        3,
        [
            ('id', 'bigint', 'PK'),
            ('vinculo_id', 'bigint', 'FK'),
            ('status', 'text', ''),
            ('secretaria', 'text', ''),
            ('nome', 'text', ''),
            ('email', 'text', ''),
            ('telefone', 'text', ''),
            ('area', 'text', ''),
        ],
    ),
    'colaborador': (
        4,
        [
            ('id', 'bigint', 'PK'),
            ('nome', 'text', 'UK'),
            ('status', 'text', ''),
            ('observacao', 'text', ''),
        ],
    ),
    'responsavel_convenio': (
        4,
        [
            ('id', 'bigint', 'PK'),
            ('vinculo_id', 'bigint', 'FK'),
            ('titular_id', 'bigint', 'FK'),
            ('substituto_id', 'bigint', 'FK'),
            ('substituicao_fim', 'date', ''),
            ('ator', 'text', ''),
        ],
    ),
    'responsavel_historico': (
        4,
        [
            ('id', 'bigint', 'PK'),
            ('responsavel_id', 'bigint', 'FK'),
            ('acao', 'text', ''),
            ('de', 'text', ''),
            ('para', 'text', ''),
            ('ator', 'text', ''),
            ('em', 'timestamptz', ''),
        ],
    ),
    'cobranca_caso': (
        4,
        [
            ('id', 'bigint', 'PK'),
            ('vinculo_id', 'bigint', 'FK'),
            ('competencia', 'char(7)', ''),
            ('valor', 'numeric', ''),
            ('status', 'text', ''),
        ],
    ),
    'cobranca_tentativa': (
        4,
        [
            ('id', 'bigint', 'PK'),
            ('cobranca_caso_id', 'bigint', 'FK'),
            ('data', 'date', ''),
            ('canal', 'text', ''),
            ('resultado', 'text', ''),
        ],
    ),
    'usuario': (
        4,
        [
            ('id', 'bigint', 'PK'),
            ('email', 'text', 'UK'),
            ('nome', 'text', ''),
            ('perfil', 'text', ''),
            ('senha_hash', 'text', ''),
            ('ativo', 'boolean', ''),
        ],
    ),
}

# (origem, destino, cardinalidade_origem, cardinalidade_destino, rotulo)
RELACIONAMENTOS: list[tuple[str, str, str, str, str]] = [
    ('originadora', 'vinculo', UM, MUITOS, 'opera'),
    ('convenio', 'vinculo', UM, MUITOS, 'assume numero'),
    ('originadora', 'gerencia_originadora', UM, UM, 'grupo master'),
    ('convenio', 'convenio_grupo', UM, MUITOS, 'classifica'),
    ('grupo', 'convenio_grupo', UM, MUITOS, 'agrupa'),
    ('vinculo', 'gerencia_conciliacao', UM, UM, 'controla'),
    ('vinculo', 'custo', UM, MUITOS, 'cobra'),
    ('custo', 'custo_faixa', UM, MUITOS, 'escalona'),
    ('vinculo', 'vencimentario', UM, MUITOS, 'gera'),
    ('vinculo', 'responsavel_convenio', UM, UM, 'tem responsavel'),
    ('vinculo', 'secretaria', UM, MUITOS, 'possui'),
    ('vinculo', 'particularidade', UM, MUITOS, 'possui'),
    ('vinculo', 'conta', UM, MUITOS, 'possui'),
    ('vinculo', 'contato', UM, MUITOS, 'possui'),
    ('vinculo', 'cobranca_caso', UM, MUITOS, 'origina'),
    ('vencimentario', 'remessa_envio', UM, ZERO_UM, 'envia'),
    ('vencimentario', 'repasse', UM, MUITOS, 'recebe'),
    ('custo', 'repasse', UM, MUITOS, 'aplicado em'),
    ('colaborador', 'responsavel_convenio', UM, MUITOS, 'titular'),
    ('colaborador', 'responsavel_convenio', UM, MUITOS, 'substituto'),
    ('responsavel_convenio', 'responsavel_historico', UM, MUITOS, 'audita'),
    ('cobranca_caso', 'cobranca_tentativa', UM, MUITOS, 'registra'),
]


def calcular_posicoes(
    entidades: dict[str, tuple[int, list]],
) -> dict[str, tuple[int, int]]:
    """Calcula a posicao (x, y) de cada entidade empilhada por coluna.

    Args:
        entidades: Mapa entidade -> (coluna, campos).

    Returns:
        Mapa entidade -> (x, y) em coordenadas do canvas.
    """
    topo_por_coluna: dict[int, int] = {}
    posicoes: dict[str, tuple[int, int]] = {}
    for nome, (coluna, campos) in entidades.items():
        y = topo_por_coluna.get(coluna, 40)
        posicoes[nome] = (40 + coluna * LARGURA_COLUNA, y)
        altura = ALTURA_CABECALHO + len(campos) * ALTURA_LINHA
        topo_por_coluna[coluna] = y + altura + GAP_VERTICAL
    return posicoes


def montar_celulas_entidade(
    nome: str,
    campos: list[tuple[str, str, str]],
    posicao: tuple[int, int],
) -> list[str]:
    """Monta as celulas XML de uma entidade (cabecalho + linhas).

    Args:
        nome: Nome da entidade/tabela.
        campos: Lista de (campo, tipo, marcador).
        posicao: Coordenada (x, y) do canto superior esquerdo.

    Returns:
        Lista de fragmentos XML (mxCell) da entidade.
    """
    x, y = posicao
    altura = ALTURA_CABECALHO + len(campos) * ALTURA_LINHA
    celulas = [
        f'<mxCell id="{nome}" value="{escape(nome)}" '
        f'style="{ESTILO_ENTIDADE}" vertex="1" parent="1">'
        f'<mxGeometry x="{x}" y="{y}" width="{LARGURA}" '
        f'height="{altura}" as="geometry"/></mxCell>'
    ]
    for indice, (campo, tipo, marcador) in enumerate(campos):
        sufixo = f'  {marcador}' if marcador else ''
        rotulo = escape(f'{campo}: {tipo}{sufixo}')
        celulas.append(
            f'<mxCell id="{nome}.{campo}" value="{rotulo}" '
            f'style="{ESTILO_LINHA}" vertex="1" parent="{nome}">'
            f'<mxGeometry y="{ALTURA_CABECALHO + indice * ALTURA_LINHA}" '
            f'width="{LARGURA}" height="{ALTURA_LINHA}" as="geometry"/>'
            f'</mxCell>'
        )
    return celulas


def montar_arestas(
    relacionamentos: list[tuple[str, str, str, str, str]],
) -> list[str]:
    """Monta as celulas XML das arestas (relacionamentos).

    Args:
        relacionamentos: Lista de (origem, destino, card_origem,
            card_destino, rotulo).

    Returns:
        Lista de fragmentos XML (mxCell) das arestas.
    """
    return [
        f'<mxCell id="rel{indice}" value="{escape(rotulo)}" '
        f'style="{ESTILO_ARESTA % (card_destino, card_origem)}" '
        f'edge="1" parent="1" source="{origem}" target="{destino}">'
        f'<mxGeometry relative="1" as="geometry"/></mxCell>'
        for indice, (origem, destino, card_origem, card_destino, rotulo)
        in enumerate(relacionamentos)
    ]


def gerar_documento(
    entidades: dict[str, tuple[int, list]],
    relacionamentos: list[tuple[str, str, str, str, str]],
) -> str:
    """Gera o documento draw.io completo do DER.

    Args:
        entidades: Definicao das entidades e seus campos.
        relacionamentos: Definicao dos relacionamentos.

    Returns:
        Conteudo XML do arquivo .drawio.
    """
    posicoes = calcular_posicoes(entidades)
    corpo = [
        fragmento
        for nome, (_, campos) in entidades.items()
        for fragmento in montar_celulas_entidade(
            nome, campos, posicoes[nome]
        )
    ]
    corpo.extend(montar_arestas(relacionamentos))
    interno = ''.join(corpo)
    return (
        '<mxfile host="app.diagrams.net" version="24.0.0">'
        '<diagram id="der-sco" name="DER SCO">'
        '<mxGraphModel dx="1400" dy="900" grid="1" gridSize="10" '
        'guides="1" tooltips="1" connect="1" arrows="1" fold="1" '
        'page="1" pageScale="1" pageWidth="1600" pageHeight="1200" '
        'math="0" shadow="0"><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        f'{interno}'
        '</root></mxGraphModel></diagram></mxfile>'
    )


def main() -> None:
    """Gera o arquivo docs/der_sco.drawio e registra o resultado."""
    logging.basicConfig(level=logging.INFO)
    conteudo = gerar_documento(ENTIDADES, RELACIONAMENTOS)
    DESTINO.write_text(conteudo, encoding='utf-8')
    logger.info('DER draw.io gerado em: %s', DESTINO)


if __name__ == '__main__':
    main()
