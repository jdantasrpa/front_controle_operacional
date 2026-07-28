# INSERIR EM: scripts/gerar_der_mcn_drawio.py
"""Gera o DER-MCN do SCO em formato draw.io com hierarquia aninhada
(Modulo -> Submodulo -> Grupo -> Entidade), mirando Supabase/PostgreSQL.

Executar: ``python scripts/gerar_der_mcn_drawio.py``.
"""

# --- stdlib ---
import logging
from html import escape
from math import ceil
from pathlib import Path

logger = logging.getLogger(__name__)

DESTINO = Path(__file__).resolve().parent.parent / 'docs' / 'der_mcn_sco.drawio'

# geometria (px)
ENT_LARGURA = 260
ALTURA_LINHA = 18
ENT_MARGEM = 24
ENT_GAP = 16
GRUPO_PAD_X = 20
GRUPO_ENT_TOPO = 62
GRUPO_MARGEM_INF = 20
GRUPO_GAP = 24
SUB_TITULO = 30
SUB_PAD_X = 16
SUB_TOPO = 40
SUB_GAP = 24
SUB_MARGEM_INF = 16
MOD_TITULO = 34
MOD_PAD_X = 16
MOD_TOPO = 40
MOD_MARGEM_INF = 16
MOD_GAP_X = 40
CANVAS_X0 = 40
CANVAS_Y0 = 40

CORES = {
    'modulo': ('#dae8fc', '#6c8ebf'),
    'submodulo': ('#e1d5e7', '#9673a6'),
    'grupo': ('#d5e8d4', '#82b366'),
    'entidade': ('#ffffff', '#33475b'),
}

# marcadores de campo
PK = 'PK'
FK = 'FK'
_ = ''

# entidade: (nome_funcional, nome_tecnico, [(marcador, campo)])
# grupo: (nome_grupo, subtitulo, [entidades])
# submodulo: (nome_submodulo, [grupos])
# modulo: (nome_modulo, [submodulos])
HIERARQUIA: list[tuple[str, list]] = [
    (
        'Modulo: Gestao de Convenios',
        [
            (
                'Submodulo: Cadastros Estruturais',
                [
                    (
                        'Grupo Originadora',
                        'Pagina Originadoras - empresa que origina os '
                        'contratos (grupo master dos convenios)',
                        [
                            (
                                'Originadora',
                                'tb_originadora',
                                [
                                    (PK, 'id_originadora'),
                                    (_, 'nome'),
                                    (_, 'codigo'),
                                    (_, 'cnpj'),
                                    (_, 'ativo'),
                                    (_, 'observacao'),
                                    (_, 'data_cadastro'),
                                ],
                            ),
                        ],
                    ),
                    (
                        'Grupo Averbadora',
                        'Pagina Averbadoras - orgaos que averbam a margem '
                        'e gestoras de margem',
                        [
                            (
                                'Averbadora',
                                'tb_averbadora',
                                [
                                    (PK, 'id_averbadora'),
                                    (_, 'nome'),
                                    (_, 'cnpj'),
                                    (_, 'ativo'),
                                    (_, 'observacao'),
                                ],
                            ),
                            (
                                'Gestora de Margem',
                                'tb_gestora_margem',
                                [
                                    (PK, 'id_gestora_margem'),
                                    (_, 'nome'),
                                    (_, 'link_portal'),
                                    (_, 'ativo'),
                                ],
                            ),
                        ],
                    ),
                    (
                        'Grupo Convenio',
                        'Pagina Convenios - orgao conveniado onde os '
                        'contratos sao consignados',
                        [
                            (
                                'Convenio',
                                'tb_convenio',
                                [
                                    (PK, 'id_convenio'),
                                    (FK, 'id_averbadora'),
                                    (FK, 'id_gestora_margem'),
                                    (_, 'cnpj'),
                                    (_, 'nome'),
                                    (_, 'status'),
                                    (_, 'status_producao'),
                                    (_, 'ativo'),
                                    (_, 'observacao'),
                                    (_, 'data_cadastro'),
                                ],
                            ),
                        ],
                    ),
                    (
                        'Grupo Classificacao',
                        'Aba Classificacao - agrupamento livre de convenios '
                        '(dimensao gerencial, N:N)',
                        [
                            (
                                'Grupo',
                                'tb_grupo',
                                [
                                    (PK, 'id_grupo'),
                                    (_, 'nome'),
                                    (_, 'ativo'),
                                ],
                            ),
                            (
                                'Convenio Grupo',
                                'tb_convenio_grupo',
                                [
                                    (PK, 'id_convenio_grupo'),
                                    (FK, 'id_convenio'),
                                    (FK, 'id_grupo'),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
            (
                'Submodulo: Vinculos e Custos',
                [
                    (
                        'Grupo Vinculo',
                        'Pagina Vinculo - liga originadora a convenio; '
                        'centro operacional do sistema',
                        [
                            (
                                'Vinculo',
                                'tb_vinculo',
                                [
                                    (PK, 'id_vinculo'),
                                    (FK, 'id_originadora'),
                                    (FK, 'id_convenio'),
                                    (_, 'numero_convenio'),
                                    (_, 'ativo'),
                                    (_, 'data_competencia_inicio'),
                                    (_, 'data_competencia_fim'),
                                    (_, 'observacao'),
                                ],
                            ),
                        ],
                    ),
                    (
                        'Grupo Custo',
                        'Aba Custo - regra de cobranca por vinculo, '
                        'versionada por vigencia',
                        [
                            (
                                'Custo',
                                'tb_custo',
                                [
                                    (PK, 'id_custo'),
                                    (FK, 'id_vinculo'),
                                    (_, 'metodo'),
                                    (_, 'base_calculo'),
                                    (_, 'aliquota_percentual'),
                                    (_, 'valor_fixo'),
                                    (_, 'valor_unitario'),
                                    (_, 'data_vigencia_inicio'),
                                    (_, 'data_vigencia_fim'),
                                    (_, 'ativo'),
                                ],
                            ),
                            (
                                'Custo Faixa',
                                'tb_custo_faixa',
                                [
                                    (PK, 'id_custo_faixa'),
                                    (FK, 'id_custo'),
                                    (_, 'valor_ate'),
                                    (_, 'aliquota_percentual'),
                                    (_, 'valor_fixo'),
                                    (_, 'valor_unitario'),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        ],
    ),
    (
        'Modulo: Conciliacao',
        [
            (
                'Submodulo: Gerencia de Convenios',
                [
                    (
                        'Grupo Controle de Conciliacao',
                        'Liga/desliga a conciliacao e parametriza o ciclo '
                        'de vencimento (independente da Gestao)',
                        [
                            (
                                'Gerencia Conciliacao',
                                'tb_gerencia_conciliacao',
                                [
                                    (PK, 'id_gerencia_conciliacao'),
                                    (FK, 'id_vinculo'),
                                    (_, 'em_conciliacao'),
                                    (_, 'dia_vencimento'),
                                    (_, 'dias_antes_remessa'),
                                    (_, 'qtd_dias_sla_pagamento'),
                                    (_, 'dias_antes_corte'),
                                    (_, 'data_alteracao'),
                                    (_, 'ator'),
                                ],
                            ),
                            (
                                'Gerencia Originadora',
                                'tb_gerencia_originadora',
                                [
                                    (PK, 'id_gerencia_originadora'),
                                    (FK, 'id_originadora'),
                                    (_, 'em_conciliacao'),
                                    (_, 'data_alteracao'),
                                    (_, 'ator'),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
            (
                'Submodulo: Controle Analitico',
                [
                    (
                        'Grupo Vencimentario',
                        'Aba Dados Gerais - competencia gerada por vinculo: '
                        'valores e status da conciliacao',
                        [
                            (
                                'Vencimentario',
                                'tb_vencimentario',
                                [
                                    (PK, 'id_vencimentario'),
                                    (FK, 'id_vinculo'),
                                    (_, 'competencia'),
                                    (_, 'data_vencimento'),
                                    (_, 'data_envio_remessa'),
                                    (_, 'data_sla_conciliacao'),
                                    (_, 'data_corte'),
                                    (_, 'valor_remessa'),
                                    (_, 'valor_retorno'),
                                    (_, 'valor_repasse'),
                                    (_, 'status_conciliacao'),
                                    (_, 'motivo_falta_conciliacao'),
                                    (_, 'percentual_inadimplencia'),
                                    (_, 'data_cadastro'),
                                ],
                            ),
                        ],
                    ),
                    (
                        'Grupo Remessa',
                        'Aba Remessa - controle de envio da remessa de '
                        'cada vencimento',
                        [
                            (
                                'Remessa Envio',
                                'tb_remessa_envio',
                                [
                                    (PK, 'id_remessa_envio'),
                                    (FK, 'id_vencimentario'),
                                    (FK, 'id_usuario'),
                                    (_, 'situacao'),
                                    (_, 'data_envio'),
                                    (_, 'observacao'),
                                ],
                            ),
                        ],
                    ),
                    (
                        'Grupo Repasse',
                        'Aba Financeiro - recebimento por secretaria, '
                        'custo aplicado e calculo do devido',
                        [
                            (
                                'Repasse',
                                'tb_repasse',
                                [
                                    (PK, 'id_repasse'),
                                    (FK, 'id_vencimentario'),
                                    (FK, 'id_secretaria'),
                                    (FK, 'id_custo'),
                                    (_, 'status_financeiro'),
                                    (_, 'data_recebimento'),
                                    (_, 'valor_recebido'),
                                    (_, 'quantidade'),
                                    (_, 'valor_custo_aplicado'),
                                    (_, 'valor_devendo'),
                                    (_, 'observacao'),
                                ],
                            ),
                        ],
                    ),
                    (
                        'Grupo Secretaria',
                        'Aba Secretarias - entidades pagadoras vinculadas '
                        'ao convenio',
                        [
                            (
                                'Secretaria',
                                'tb_secretaria',
                                [
                                    (PK, 'id_secretaria'),
                                    (FK, 'id_vinculo'),
                                    (_, 'nome'),
                                    (_, 'codigo'),
                                    (_, 'ativo'),
                                    (_, 'observacao'),
                                ],
                            ),
                        ],
                    ),
                    (
                        'Grupo Contato',
                        'Aba Contatos - pessoas de contato no convenio '
                        'ou secretaria',
                        [
                            (
                                'Contato',
                                'tb_contato',
                                [
                                    (PK, 'id_contato'),
                                    (FK, 'id_vinculo'),
                                    (FK, 'id_secretaria'),
                                    (_, 'nome'),
                                    (_, 'email'),
                                    (_, 'telefone'),
                                    (_, 'area'),
                                    (_, 'ativo'),
                                ],
                            ),
                        ],
                    ),
                    (
                        'Grupo Particularidade',
                        'Aba Particularidades - rubrica, modelo de averbacao '
                        'e modelos de envio (N:N)',
                        [
                            (
                                'Particularidade',
                                'tb_particularidade',
                                [
                                    (PK, 'id_particularidade'),
                                    (FK, 'id_vinculo'),
                                    (FK, 'id_modelo_averbacao'),
                                    (_, 'rubrica_produto'),
                                    (_, 'ativo'),
                                    (_, 'observacao'),
                                ],
                            ),
                            (
                                'Modelo Averbacao',
                                'tb_modelo_averbacao',
                                [
                                    (PK, 'id_modelo_averbacao'),
                                    (_, 'nome'),
                                    (_, 'ativo'),
                                ],
                            ),
                            (
                                'Modelo Envio',
                                'tb_modelo_envio',
                                [
                                    (PK, 'id_modelo_envio'),
                                    (_, 'nome'),
                                    (_, 'ativo'),
                                ],
                            ),
                            (
                                'Particularidade Modelo Envio',
                                'tb_particularidade_modelo_envio',
                                [
                                    (PK, 'id_particularidade_modelo_envio'),
                                    (FK, 'id_particularidade'),
                                    (FK, 'id_modelo_envio'),
                                ],
                            ),
                        ],
                    ),
                    (
                        'Grupo Conta Bancaria',
                        'Aba Contas - dados bancarios usados no repasse',
                        [
                            (
                                'Conta',
                                'tb_conta',
                                [
                                    (PK, 'id_conta'),
                                    (FK, 'id_vinculo'),
                                    (FK, 'id_banco'),
                                    (_, 'agencia'),
                                    (_, 'numero_conta'),
                                    (_, 'chave_pix'),
                                    (_, 'cnpj'),
                                    (_, 'ativo'),
                                ],
                            ),
                            (
                                'Banco',
                                'tb_banco',
                                [
                                    (PK, 'id_banco'),
                                    (_, 'codigo_compe'),
                                    (_, 'nome'),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
            (
                'Submodulo: Responsaveis pela Conciliacao',
                [
                    (
                        'Grupo Responsavel',
                        'Titular e substituto da conciliacao por vinculo, '
                        'com auditoria de trocas',
                        [
                            (
                                'Colaborador',
                                'tb_colaborador',
                                [
                                    (PK, 'id_colaborador'),
                                    (_, 'nome'),
                                    (_, 'ativo'),
                                    (_, 'observacao'),
                                ],
                            ),
                            (
                                'Responsavel Convenio',
                                'tb_responsavel_convenio',
                                [
                                    (PK, 'id_responsavel_convenio'),
                                    (FK, 'id_vinculo'),
                                    (FK, 'id_colaborador_titular'),
                                    (FK, 'id_colaborador_substituto'),
                                    (_, 'data_fim_substituicao'),
                                    (_, 'data_alteracao'),
                                    (_, 'ator'),
                                ],
                            ),
                            (
                                'Responsavel Historico',
                                'tb_responsavel_historico',
                                [
                                    (PK, 'id_responsavel_historico'),
                                    (FK, 'id_responsavel_convenio'),
                                    (_, 'acao'),
                                    (_, 'valor_de'),
                                    (_, 'valor_para'),
                                    (_, 'ator'),
                                    (_, 'data_evento'),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        ],
    ),
    (
        'Modulo: Cobranca',
        [
            (
                'Submodulo: Cobranca de Inadimplencia',
                [
                    (
                        'Grupo Cobranca',
                        'Casos de cobranca por vinculo e as tentativas '
                        'de contato',
                        [
                            (
                                'Cobranca Caso',
                                'tb_cobranca_caso',
                                [
                                    (PK, 'id_cobranca_caso'),
                                    (FK, 'id_vinculo'),
                                    (_, 'competencia'),
                                    (_, 'valor'),
                                    (_, 'status'),
                                    (_, 'data_abertura'),
                                ],
                            ),
                            (
                                'Cobranca Tentativa',
                                'tb_cobranca_tentativa',
                                [
                                    (PK, 'id_cobranca_tentativa'),
                                    (FK, 'id_cobranca_caso'),
                                    (_, 'canal'),
                                    (_, 'resultado'),
                                    (_, 'data_tentativa'),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        ],
    ),
    (
        'Modulo: Seguranca',
        [
            (
                'Submodulo: Controle de Acesso',
                [
                    (
                        'Grupo Acesso',
                        'Usuarios do sistema (mapeavel ao Supabase Auth '
                        'via id_usuario)',
                        [
                            (
                                'Usuario',
                                'tb_usuario',
                                [
                                    (PK, 'id_usuario'),
                                    (_, 'email'),
                                    (_, 'nome'),
                                    (_, 'perfil'),
                                    (_, 'senha_hash'),
                                    (_, 'ativo'),
                                    (_, 'data_cadastro'),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        ],
    ),
]

# (entidade_origem, entidade_destino, cardinalidade)
RELACIONAMENTOS: list[tuple[str, str, str]] = [
    ('Convenio', 'Averbadora', 'N:1'),
    ('Convenio', 'Gestora de Margem', 'N:1'),
    ('Convenio Grupo', 'Convenio', 'N:1'),
    ('Convenio Grupo', 'Grupo', 'N:1'),
    ('Vinculo', 'Originadora', 'N:1'),
    ('Vinculo', 'Convenio', 'N:1'),
    ('Custo', 'Vinculo', 'N:1'),
    ('Custo Faixa', 'Custo', 'N:1'),
    ('Gerencia Conciliacao', 'Vinculo', '1:1'),
    ('Gerencia Originadora', 'Originadora', '1:1'),
    ('Vencimentario', 'Vinculo', 'N:1'),
    ('Remessa Envio', 'Vencimentario', '1:1'),
    ('Remessa Envio', 'Usuario', 'N:1'),
    ('Repasse', 'Vencimentario', 'N:1'),
    ('Repasse', 'Secretaria', 'N:1'),
    ('Repasse', 'Custo', 'N:1'),
    ('Secretaria', 'Vinculo', 'N:1'),
    ('Contato', 'Vinculo', 'N:1'),
    ('Contato', 'Secretaria', 'N:1'),
    ('Particularidade', 'Vinculo', 'N:1'),
    ('Particularidade', 'Modelo Averbacao', 'N:1'),
    ('Particularidade Modelo Envio', 'Particularidade', 'N:1'),
    ('Particularidade Modelo Envio', 'Modelo Envio', 'N:1'),
    ('Conta', 'Vinculo', 'N:1'),
    ('Conta', 'Banco', 'N:1'),
    ('Responsavel Convenio', 'Vinculo', '1:1'),
    ('Responsavel Convenio', 'Colaborador', 'N:1'),
    ('Responsavel Historico', 'Responsavel Convenio', 'N:1'),
    ('Cobranca Caso', 'Vinculo', 'N:1'),
    ('Cobranca Tentativa', 'Cobranca Caso', 'N:1'),
]


def _id_entidade(nome_tecnico: str) -> str:
    """Deriva o id da celula da entidade a partir do nome tecnico."""
    return f'ent-{nome_tecnico}'


def altura_entidade(campos: list[tuple[str, str]]) -> int:
    """Calcula a altura da caixa da entidade pela formula da skill.

    Args:
        campos: Lista de (marcador, campo).

    Returns:
        Altura em px (total_linhas * 18 + 24), arredondada para cima.
    """
    total_linhas = 2 + len(campos)
    return ceil(total_linhas * ALTURA_LINHA + ENT_MARGEM)


def altura_grupo(grupo: tuple[str, str, list]) -> int:
    """Calcula a altura do container do grupo somando suas entidades."""
    _nome, _subtitulo, entidades = grupo
    alturas = [altura_entidade(campos) for _, _, campos in entidades]
    espacos = ENT_GAP * (len(entidades) - 1)
    return GRUPO_ENT_TOPO + sum(alturas) + espacos + GRUPO_MARGEM_INF


def altura_submodulo(submodulo: tuple[str, list]) -> int:
    """Calcula a altura do container do submodulo somando seus grupos."""
    _nome, grupos = submodulo
    alturas = [altura_grupo(grupo) for grupo in grupos]
    espacos = GRUPO_GAP * (len(grupos) - 1)
    return SUB_TOPO + sum(alturas) + espacos + SUB_MARGEM_INF


def altura_modulo(modulo: tuple[str, list]) -> int:
    """Calcula a altura do container do modulo somando seus submodulos."""
    _nome, submodulos = modulo
    alturas = [altura_submodulo(sub) for sub in submodulos]
    espacos = SUB_GAP * (len(submodulos) - 1)
    return MOD_TOPO + sum(alturas) + espacos + MOD_MARGEM_INF


def _estilo_container(tipo: str) -> str:
    """Monta o style de um container hierarquico pelo tipo."""
    preenchimento, borda = CORES[tipo]
    return (
        'rounded=0;whiteSpace=wrap;html=1;verticalAlign=top;'
        f'fillColor={preenchimento};strokeColor={borda};container=1;'
        'collapsible=0;fontStyle=1;'
    )


def _valor_entidade(
    nome: str, nome_tecnico: str, campos: list[tuple[str, str]]
) -> str:
    """Monta o value HTML (multi-linha) da caixa da entidade."""
    linhas = [f'<b>{nome}</b> ({nome_tecnico})<br><hr>']
    for marcador, campo in campos:
        prefixo = f'<b>{marcador}</b> ' if marcador else ''
        linhas.append(f'{prefixo}{campo}')
    return escape('<br>'.join(linhas))


def montar_grupo(
    grupo: tuple[str, str, list], id_grupo: str, parent: str, y: int
) -> list[str]:
    """Monta o container do grupo, seu subtitulo e suas entidades.

    Args:
        grupo: Tupla (nome, subtitulo, entidades).
        id_grupo: Id unico do container do grupo.
        parent: Id do container pai (submodulo).
        y: Coordenada y relativa ao pai.

    Returns:
        Lista de fragmentos XML (mxCell).
    """
    nome, subtitulo, entidades = grupo
    largura = ENT_LARGURA + 2 * GRUPO_PAD_X
    altura = altura_grupo(grupo)
    celulas = [
        f'<mxCell id="{id_grupo}" value="{escape(nome)}" '
        f'style="{_estilo_container("grupo")}" vertex="1" parent="{parent}">'
        f'<mxGeometry x="{SUB_PAD_X}" y="{y}" width="{largura}" '
        f'height="{altura}" as="geometry"/></mxCell>',
        f'<mxCell id="{id_grupo}-sub" value="{escape(subtitulo)}" '
        'style="text;html=1;align=left;verticalAlign=top;whiteSpace=wrap;'
        'overflow=hidden;fontSize=10;fontStyle=2;fontColor=#555555;" '
        f'vertex="1" parent="{id_grupo}">'
        f'<mxGeometry x="10" y="26" width="{largura - 20}" height="34" '
        'as="geometry"/></mxCell>',
    ]
    cursor = GRUPO_ENT_TOPO
    for nome_ent, nome_tec, campos in entidades:
        altura_ent = altura_entidade(campos)
        valor = _valor_entidade(nome_ent, nome_tec, campos)
        celulas.append(
            f'<mxCell id="{_id_entidade(nome_tec)}" value="{valor}" '
            'style="rounded=0;whiteSpace=wrap;overflow=hidden;html=1;'
            'align=left;verticalAlign=top;spacingLeft=8;spacingTop=6;'
            'fillColor=#ffffff;strokeColor=#33475b;fontSize=12;" '
            f'vertex="1" parent="{id_grupo}">'
            f'<mxGeometry x="{GRUPO_PAD_X}" y="{cursor}" '
            f'width="{ENT_LARGURA}" height="{altura_ent}" as="geometry"/>'
            '</mxCell>'
        )
        cursor += altura_ent + ENT_GAP
    return celulas


def montar_submodulo(
    submodulo: tuple[str, list], id_sub: str, parent: str, y: int
) -> list[str]:
    """Monta o container do submodulo e seus grupos empilhados."""
    nome, grupos = submodulo
    largura = ENT_LARGURA + 2 * GRUPO_PAD_X + 2 * SUB_PAD_X
    altura = altura_submodulo(submodulo)
    celulas = [
        f'<mxCell id="{id_sub}" value="{escape(nome)}" '
        f'style="{_estilo_container("submodulo")}" vertex="1" '
        f'parent="{parent}"><mxGeometry x="{MOD_PAD_X}" y="{y}" '
        f'width="{largura}" height="{altura}" as="geometry"/></mxCell>'
    ]
    cursor = SUB_TOPO
    for indice, grupo in enumerate(grupos):
        id_grupo = f'{id_sub}-g{indice}'
        celulas.extend(montar_grupo(grupo, id_grupo, id_sub, cursor))
        cursor += altura_grupo(grupo) + GRUPO_GAP
    return celulas


def montar_modulo(
    modulo: tuple[str, list], indice: int, x: int
) -> list[str]:
    """Monta o container do modulo e seus submodulos empilhados."""
    nome, submodulos = modulo
    id_mod = f'mod-{indice}'
    largura = ENT_LARGURA + 2 * GRUPO_PAD_X + 2 * SUB_PAD_X + 2 * MOD_PAD_X
    altura = altura_modulo(modulo)
    celulas = [
        f'<mxCell id="{id_mod}" value="{escape(nome)}" '
        f'style="{_estilo_container("modulo")}" vertex="1" parent="1">'
        f'<mxGeometry x="{x}" y="{CANVAS_Y0}" width="{largura}" '
        f'height="{altura}" as="geometry"/></mxCell>'
    ]
    cursor = MOD_TOPO
    for pos, submodulo in enumerate(submodulos):
        id_sub = f'{id_mod}-s{pos}'
        celulas.extend(montar_submodulo(submodulo, id_sub, id_mod, cursor))
        cursor += altura_submodulo(submodulo) + SUB_GAP
    return celulas


def montar_relacionamentos(
    relacionamentos: list[tuple[str, str, str]],
    indice_tecnico: dict[str, str],
) -> list[str]:
    """Monta as arestas de relacionamento com cardinalidade.

    Args:
        relacionamentos: Lista de (origem, destino, cardinalidade).
        indice_tecnico: Mapa nome_funcional -> nome_tecnico.

    Returns:
        Lista de fragmentos XML (mxCell) das arestas.
    """
    celulas = []
    for pos, (origem, destino, card) in enumerate(relacionamentos):
        seta_ini = 'ERone' if card == '1:1' else 'ERmany'
        estilo = (
            'edgeStyle=entityRelationEdgeStyle;html=1;fontSize=10;'
            f'endArrow=ERone;startArrow={seta_ini};rounded=0;'
        )
        celulas.append(
            f'<mxCell id="rel-{pos}" value="{card}" style="{estilo}" '
            f'edge="1" parent="1" '
            f'source="{_id_entidade(indice_tecnico[origem])}" '
            f'target="{_id_entidade(indice_tecnico[destino])}">'
            '<mxGeometry relative="1" as="geometry"/></mxCell>'
        )
    return celulas


def _indice_tecnico(hierarquia: list) -> dict[str, str]:
    """Mapeia nome funcional -> nome tecnico de toda entidade."""
    return {
        nome_ent: nome_tec
        for _mod, subs in hierarquia
        for _sub, grupos in subs
        for _grp, _subt, entidades in grupos
        for nome_ent, nome_tec, _campos in entidades
    }


def _celula_legenda(y: int) -> str:
    """Monta a caixa de legenda fixa no rodape do diagrama."""
    valor = (
        '<b>Legenda</b><br><hr>'
        '<b>PK</b> = Chave Primaria: identifica cada registro<br>'
        '<b>FK</b> = Chave Estrangeira: aponta para outra tabela<br>'
        '<b>1:1</b> = um para um<br>'
        '<b>1:N</b> = um registro se relaciona com varios<br>'
        '<b>N:1</b> = varios registros se relacionam com um<br>'
        '<b>N:N</b> = varios para varios (via tabela de ligacao)<br>'
        'prefixo <b>data_</b> = campo de data | '
        '<b>ativo</b> = booleano'
    )
    return (
        f'<mxCell id="legenda" value="{escape(valor)}" '
        'style="rounded=0;whiteSpace=wrap;overflow=hidden;html=1;align=left;'
        'verticalAlign=top;spacingLeft=8;spacingTop=6;fillColor=#fff2cc;'
        'strokeColor=#d6b656;fontSize=11;" vertex="1" parent="1">'
        f'<mxGeometry x="{CANVAS_X0}" y="{y}" width="360" height="180" '
        'as="geometry"/></mxCell>'
    )


def gerar_documento(hierarquia: list, relacionamentos: list) -> str:
    """Gera o documento draw.io completo do DER-MCN.

    Args:
        hierarquia: Arvore Modulo -> Submodulo -> Grupo -> Entidades.
        relacionamentos: Lista de (origem, destino, cardinalidade).

    Returns:
        Conteudo XML do arquivo .drawio.
    """
    corpo: list[str] = []
    x = CANVAS_X0
    largura_mod = ENT_LARGURA + 2 * GRUPO_PAD_X + 2 * SUB_PAD_X + 2 * MOD_PAD_X
    for indice, modulo in enumerate(hierarquia):
        corpo.extend(montar_modulo(modulo, indice, x))
        x += largura_mod + MOD_GAP_X
    corpo.extend(
        montar_relacionamentos(relacionamentos, _indice_tecnico(hierarquia))
    )
    altura_maxima = max(altura_modulo(mod) for mod in hierarquia)
    corpo.append(_celula_legenda(CANVAS_Y0 + altura_maxima + 40))
    interno = ''.join(corpo)
    return (
        '<mxfile host="app.diagrams.net" version="24.0.0">'
        '<diagram name="DER-MCN SCO" id="der-mcn-sco">'
        '<mxGraphModel dx="1600" dy="1000" grid="1" gridSize="10" '
        'guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" '
        'pageScale="1" pageWidth="2400" pageHeight="1600" math="0" '
        f'shadow="0"><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
        f'{interno}</root></mxGraphModel></diagram></mxfile>'
    )


def main() -> None:
    """Gera o arquivo docs/der_mcn_sco.drawio e registra o resultado."""
    logging.basicConfig(level=logging.INFO)
    conteudo = gerar_documento(HIERARQUIA, RELACIONAMENTOS)
    DESTINO.write_text(conteudo, encoding='utf-8')
    logger.info('DER-MCN draw.io gerado em: %s', DESTINO)


if __name__ == '__main__':
    main()
