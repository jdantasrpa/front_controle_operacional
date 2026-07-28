import sqlite3
from pathlib import Path
from datetime import datetime
import gradio as gr
import pandas as pd
import time
import re
import math
import uuid
import json
import configparser
import os
import getpass
from typing import Optional

CONFIG_PATH = Path(__file__).with_name("config_projeto.ini")


PASTA_DB: Optional[Path] = None
PASTA_ENTRADA: Optional[Path] = None


def _expand_username(v: str) -> str:
    if not isinstance(v, str):
        return v
    if "[USERNAME]" in v:
        return v.replace("[USERNAME]", os.getenv("USERNAME", ""))
    return v

def empty_df(cols):
    return pd.DataFrame(columns=cols)

def ensure_df(value, cols):
    # se vier ""/None -> vira dataframe vazio
    if value is None or value == "":
        return empty_df(cols)
    if isinstance(value, pd.DataFrame):
        return value
    # se vier lista de dicts etc
    return normalize_df(value, cols)

def get_actor():
    return (
        os.getenv("USERNAME")  # Windows
        or os.getenv("USER")   # Linux/Mac
        or getpass.getuser()   # fallback
        or "unknown_user"
    )

def make_datatypes(cols):
    # id -> number, resto -> str
    return ["number" if c == "id" else "str" for c in cols]

def load_config_vars(config_path: Path) -> dict:
    if not config_path.exists():
        raise FileNotFoundError(f"Config não encontrado: {config_path}")

    cfg = configparser.ConfigParser()
    cfg.read(config_path, encoding="utf-8")

    # Mapeamento no seu estilo (tipo, seção, chave)
    spec = {
        "PASTA_DB": {
            "tipo": "diretorio",
            "secao": "DIRETORIOS",
            "chave": "pasta_db",
        },
        "PASTA_ENTRADA": {
            "tipo": "diretorio",
            "secao": "DIRETORIOS",
            "chave": "pasta_fila_entrada",
        },
    }

    out = {}
    for var_name, meta in spec.items():
        sec = meta["secao"]
        key = meta["chave"]

        if sec not in cfg or key not in cfg[sec]:
            raise KeyError(f"Faltando [{sec}] {key} no config.ini")

        raw = cfg[sec][key].strip()
        val = _expand_username(raw)

        if meta["tipo"].upper() == "DIRETORIO":
            p = Path(val)
            p.mkdir(parents=True, exist_ok=True)
            out[var_name] = p
        else:
            out[var_name] = val

    return out

# Carrega e injeta em variáveis globais (igual seu padrão)
_cfg = load_config_vars(CONFIG_PATH)
globals().update(_cfg)

def safe_pick_choice_ui(raw, options):
    s = ("" if raw is None else str(raw)).strip()
    if not s:
        return ""
    for opt in options:
        if str(opt).strip().upper() == s.upper():
            return str(opt).strip()
    return ""

def safe_pick_choice(raw, options):
    """
    Retorna exatamente o valor oficial do choice (mantendo capitalização),
    comparando case-insensitive.
    Se não encontrar, levanta erro.
    """
    for opt in options:
        if str(opt).strip().upper() == str(raw).strip().upper():
            return opt
    raise ValueError(f"Valor inválido. Opções permitidas: {options}")

def br_money(v):
    if v is None or v == "":
        return ""
    try:
        v = float(v)
        # sem "R$" e sem milhar (como você comentou em outra conversa)
        # mantém 2 casas com vírgula
        return f"{v:.2f}".replace(".", ",")
    except Exception:
        return str(v)

def br_percent(x):
    if x is None:
        return "-"
    try:
        return f"{float(x)*100:,.2f}%".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return "-"

def iso_date(v):
    # espera "YYYY-MM-DD" ou "YYYY-MM"
    return "" if v is None else str(v)

def _match_choice(raw, options):
    """Casa valor do DB com choices (trim + case-insensitive)."""
    if raw is None:
        return None
    s = str(raw).strip()
    for opt in options:
        if str(opt).strip().lower() == s.lower():
            return opt
    return None

def _make_cmd_id() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    suf = uuid.uuid4().hex[:8]
    return f"{ts}__{suf}"

def _created_at_br() -> str:
    return datetime.now().strftime("%d-%m-%Y %H:%M:%S")

def _now_sql() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _queue_write(pasta_entrada: Path, payload: dict) -> Path:
    pasta_entrada.mkdir(parents=True, exist_ok=True)
    arquivo = pasta_entrada / f"{payload['id']}.txt"
    arquivo.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return arquivo

def auto_refresh_por_aba(numero_convenio, mes_ref, current_page, active_tab):
    noop_inputs = [gr.update() for _ in DADOS_FIELDS]

    if current_page != PAGE_ANALITICO or not numero_convenio or not mes_ref:
        return (
            gr.update(), gr.update(), gr.update(),
            *noop_inputs,
            gr.update(), gr.update(), gr.update()
        )

    try:
        dados, contatos, parts, contas, msg, _, _ = carregar_convenio_por_chave(str(numero_convenio), str(mes_ref))
        dados = montar_dados_analitico(dados)

        df_contatos = ensure_df(contatos, CONTATO_COLS)
        df_parts = ensure_df(parts, PART_COLS)
        df_contas = ensure_df(contas, CONTA_COLS)

        upd_header = _build_header(dados, f"{numero_convenio}/{mes_ref}")
        upd_state = dados
        upd_inputs = preencher_dados_updates(dados)

        return (
            gr.update(),
            upd_header,
            upd_state,
            *upd_inputs,
            df_contatos,
            df_parts,
            df_contas,
        )

    except Exception:
        return (
            gr.update(), gr.update(), gr.update(),
            *noop_inputs,
            gr.update(), gr.update(), gr.update()
        )

# =========================================
# Banco (apontando para o mock)
# =========================================
DB_PATH = Path("convenios_mock_layout.db")  # coloque o mock aqui com esse nome

# =========================================
# Colunas oficiais (ordem + garantia)
# =========================================
CONTATO_COLS = [
    "id",
    "status", 
    "nome", 
    "email", 
    "telefone", 
    "area", 
    "observacao", 
    "criado_em", 
    "atualizado_em"]

PART_COLS = [
    "id",
    "status_particularidade",
    "rubrica_produto",
    "modelo_de_averbacao",
    "retencao",
    "retencao_valor",
    "retencao_percent",
    "telefone",
    "observacao",
    "criado_em",
    "atualizado_em",
]

CONTA_COLS = [
    "id",
    "banco",
    "agencia",
    "conta",
    "chave_pix",
    "cnpj",
    "status_conta",
    "criado_em",
    "atualizado_em",
]

# =========================
# Página: Controle Analítico
# =========================
        
STATUS_CONCILIACAO_OPCOES = [
    "CONCILIADO",
    "CONCILIADO (PARCIAL)",
    "PENDENTE",
]

MOTIVO_FALTA_CONCILIACAO_OPCOES = [
    "Falta de repasse do convênio",
    "Arquivo retorno não disponível",
    "Outros",
]

STATUS_CONTA_OPCOES = ["ATIVA", "INATIVA", "EM VALIDAÇÃO"]

DADOS_FIELDS = [

    # DATAS (pode escolher quais liberam edição)
    {"key": "data_vencimento", "label": "Data vencimento", "editable": False, "fmt": iso_date},
    #{"key": "data_env_remessa", "label": "Data envio remessa", "editable": False, "fmt": iso_date},
    {"key": "data_baixa", "label": "Data SLA conciliação", "editable": False, "fmt": iso_date},
    {"key": "qtd_dias_inadimplencia", "label": "Qtd dias SLA pagamento", "editable": False},
    {"key": "data_corte", "label": "Data corte", "editable": True, "fmt": iso_date},

    # VALORES
    {"key": "valor_remessa", "label": "Valor remessa", "editable": True, "fmt": br_money},
    {"key": "valor_retorno", "label": "Valor retorno", "editable": True, "fmt": br_money},
    {"key": "valor_repasse", "label": "Valor repasse", "editable": True, "fmt": br_money},
    # valor pendente = valor retorno - valor repasse
    {"key": "valor_pendente", "label": "Valor pendente", "editable": False, "fmt": br_money},


    # % (inadimplência)
    {"key": "porcentagem_inadimplencia", "label": "% inadimplência", "editable": False, "fmt": br_percent},

    {"key": "qtd_contratos", "label": "QTD de contratos", "editable": False },

    # STATUS
    {
        "key": "status_conciliacao",
        "label": "Status conciliação",
        "editable": True,
        "type": "select",
        "options": STATUS_CONCILIACAO_OPCOES,
    },
    {
        "key": "motivo_falta_conciliacao",
        "label": "Motivo falta conciliação",
        "editable": True,
        "type": "select",
        "options": MOTIVO_FALTA_CONCILIACAO_OPCOES,
        "depends_on": {
            "field": "status_conciliacao",
            "show_when": ["CONCILIADO (PARCIAL)"]
        }
    },
    {"key": "observacao", "label": "Observação", "editable": True},

]

def normalize_df(rows, cols):
    """
    rows: list[dict] | pd.DataFrame
    cols: list[str] ordem final de colunas
    """
    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    return df[cols]


# -----------------------------
# Infra DB
# -----------------------------
def get_latest_db_path() -> Path:
    if not PASTA_DB.exists():
        raise FileNotFoundError(f"Pasta de DB não encontrada: {PASTA_DB}")

    db_files = [f for f in PASTA_DB.glob("*.db") if f.is_file()]
    if not db_files:
        raise FileNotFoundError(f"Nenhum .db encontrado em: {PASTA_DB}")

    latest = max(db_files, key=lambda f: f.stat().st_mtime)
    return latest

def db_connect(db_path=None):
    """
    Se db_path não for informado, usa automaticamente
    o último banco disponível na pasta configurada.
    """
    if db_path is None:
        db_path = get_latest_db_path()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _distinct_values(sql: str) -> list[str]:
    # abre sempre o último snapshot
    try:
        conn = db_connect()  # se você adotou db_connect(db_path=None)
    except TypeError:
        conn = db_connect(get_latest_db_path())  # se db_connect exige db_path

    cur = conn.cursor()
    rows = cur.execute(sql).fetchall()
    conn.close()

    # pega primeira coluna, remove None/vazio, e retorna como str
    out = []
    for r in rows:
        v = r[0]
        if v is None:
            continue
        s = str(v).strip()
        if not s:
            continue
        out.append(s)

    return out


def get_filter_options():
    meses = _distinct_values("""
        SELECT DISTINCT mes_referencia_conciliacao
        FROM tabela_concilicacao_convenio
        ORDER BY mes_referencia_conciliacao DESC
    """)

    status = _distinct_values("""
        SELECT DISTINCT status_conciliacao
        FROM tabela_concilicacao_convenio
        ORDER BY status_conciliacao
    """)

    motivos = _distinct_values("""
        SELECT DISTINCT motivo_falta_conciliacao
        FROM tabela_concilicacao_convenio
        WHERE motivo_falta_conciliacao IS NOT NULL AND TRIM(motivo_falta_conciliacao) <> ''
        ORDER BY motivo_falta_conciliacao
    """)

    originadores = _distinct_values("""
        SELECT DISTINCT originador
        FROM tabela_concilicacao_convenio
        WHERE originador IS NOT NULL AND TRIM(originador) <> ''
        ORDER BY originador
    """)

    data_vencimento = _distinct_values("""
        SELECT DISTINCT data_vencimento
        FROM tabela_concilicacao_convenio
        WHERE data_vencimento IS NOT NULL AND TRIM(data_vencimento) <> ''
        ORDER BY data_vencimento DESC
    """)

    data_baixa = _distinct_values("""
        SELECT DISTINCT data_baixa
        FROM tabela_concilicacao_convenio
        WHERE data_baixa IS NOT NULL AND TRIM(data_baixa) <> ''
        ORDER BY data_baixa DESC
    """)

    data_corte = _distinct_values("""
        SELECT DISTINCT data_corte
        FROM tabela_concilicacao_convenio
        WHERE data_corte IS NOT NULL AND TRIM(data_corte) <> ''
        ORDER BY data_corte DESC
    """)

    return (
        ["Todos"] + meses,
        ["Todos"] + status,
        ["Todos"] + motivos,
        ["Todos"] + originadores,
        ["Todos"] + data_vencimento,
        ["Todos"] + data_baixa,
        ["Todos"] + data_corte,
    )


# -----------------------------
# Queries (Sintético)
# -----------------------------
def listar_convenios(
    mes,
    status,
    motivo,
    originador,
    data_vencimento,
    data_baixa,
    data_corte,
    busca
):

    conn = db_connect(get_latest_db_path())

    cur = conn.cursor()

    where = []
    params = []

    if mes and mes != "Todos":
        where.append("mes_referencia_conciliacao = ?")
        params.append(mes)

    if status and status != "Todos":
        where.append("UPPER(COALESCE(status_conciliacao,'')) = ?")
        params.append((status or "").strip().upper())

    if motivo and motivo != "Todos":
        where.append("COALESCE(motivo_falta_conciliacao,'') = ?")
        params.append(motivo)

    if originador and originador != "Todos":
        where.append("COALESCE(originador,'') = ?")
        params.append(originador)

    if data_vencimento and data_vencimento != "Todos":
        where.append("COALESCE(data_vencimento,'') = ?")
        params.append(data_vencimento)

    if data_baixa and data_baixa != "Todos":
        where.append("COALESCE(data_baixa,'') = ?")
        params.append(data_baixa)

    if data_corte and data_corte != "Todos":
        where.append("COALESCE(data_corte,'') = ?")
        params.append(data_corte)

    if busca and busca.strip():
        b = f"%{busca.strip()}%"
        where.append("""
            (COALESCE(nome_convenio,'') LIKE ?
             OR COALESCE(cnpj_convenio,'') LIKE ?
             OR COALESCE(CAST(numero_convenio AS TEXT),'') LIKE ?
             OR COALESCE(motivo_falta_conciliacao,'') LIKE ?)
        """)
        params.extend([b, b, b, b])

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    sql = f"""
        SELECT
            id,
            mes_referencia_conciliacao AS mes,
            nome_convenio,
            status_conciliacao,
            numero_convenio,
            originador,
            data_vencimento AS vencimento_convenio,
            data_baixa,
            data_corte,
            qtd_dias_inadimplencia,
            porcentagem_inadimplencia
        FROM tabela_concilicacao_convenio
        {where_sql}
        ORDER BY mes_referencia_conciliacao DESC, nome_convenio ASC
    """

    rows = cur.execute(sql, params).fetchall()
    conn.close()

    data = [dict(r) for r in rows]
    return data, f"{len(data)} registro(s) encontrado(s)"


# -----------------------------
# Queries (Analítico)
# -----------------------------

def salvar_dados(
    numero_convenio,
    mes_referencia_conciliacao,
    status_conciliacao,
    motivo_falta_conciliacao,
    valor_pendente,
    inadimplencia_pf,
    inadimplencia_pj,
):
    # =========================
    # 0) chave composta obrigatória
    # =========================
    numero_convenio = (numero_convenio or "").strip()
    mes_referencia_conciliacao = (mes_referencia_conciliacao or "").strip()

    if not numero_convenio or not mes_referencia_conciliacao:
        return "<div class='alert'>Convênio e Mês referência não selecionados.</div>"

    try:
        latest_db = get_latest_db_path()
        bd_utilizado = latest_db.name
        actor = get_actor()
        now_sql = _now_sql()

        # =========================
        # 1) monta payload + normaliza (padrão salvar_dados_gr)
        # =========================
        payload = {}

        # Status (dropdown) -> valida + normaliza
        payload["status_conciliacao"] = normalize_choice(
            status_conciliacao,
            STATUS_CONCILIACAO_OPCOES,
            default="PENDENTE",
            upper_db=True,   # ✅ grava padronizado
            field="Status conciliação",
        )

        # Motivo (dropdown condicional) -> valida com options oficiais
        motivo_raw = ("" if motivo_falta_conciliacao is None else str(motivo_falta_conciliacao)).strip()
        if motivo_raw:
            payload["motivo_falta_conciliacao"] = safe_pick_choice(
                motivo_raw,
                MOTIVO_FALTA_CONCILIACAO_OPCOES
            )
        else:
            payload["motivo_falta_conciliacao"] = ""

        # Regra: motivo só vale quando status == CONCILIADO (PARCIAL)
        if payload["status_conciliacao"].strip().upper() != "CONCILIADO (PARCIAL)":
            payload["motivo_falta_conciliacao"] = ""

        # Valores numéricos (BR)
        payload["valor_pendente"] = parse_br_number(valor_pendente)
        payload["inadimplencia_pf"] = parse_br_number(inadimplencia_pf)
        payload["inadimplencia_pj"] = parse_br_number(inadimplencia_pj)

        # Timestamp
        payload["atualizado_em"] = now_sql

        # =========================
        # 2) valida existência no snapshot
        # =========================
        conn = db_connect(latest_db)
        cur = conn.cursor()

        conv = cur.execute(
            """
            SELECT 1
            FROM tabela_concilicacao_convenio
            WHERE numero_convenio = ?
              AND mes_referencia_conciliacao = ?
            """,
            (numero_convenio, mes_referencia_conciliacao)
        ).fetchone()

        if not conv:
            conn.close()
            return "<div class='alert error'>Convênio não encontrado para este mês de referência.</div>"

        # =========================
        # 3) monta UPDATE dinâmico (writer)
        # =========================
        set_sql = ", ".join([f"{k} = ?" for k in payload.keys()])
        sql = f"""
            UPDATE tabela_concilicacao_convenio
            SET {set_sql}
            WHERE numero_convenio = ?
              AND mes_referencia_conciliacao = ?
        """.strip()

        params = list(payload.values()) + [numero_convenio, mes_referencia_conciliacao]

        cmd = {
            "id": _make_cmd_id(),
            "created_at": _created_at_br(),
            "actor": actor,
            "bd_utilizado": bd_utilizado,
            "metodo": "UPDATE_DADOS_CONCILIACAO",
            "sql": " ".join(sql.split()),
            "params": params,
        }

        arq = _queue_write(PASTA_ENTRADA, cmd)
        conn.close()

        return f"<div class='alert success'>Comando enfileirado ({arq.name}) — BD: {bd_utilizado}</div>"

    except Exception as e:
        return f"<div class='alert error'>Erro ao salvar: {str(e)}</div>"


def recarregar_dados(convenio_id):
    if not convenio_id:
        return "", "", "", "", ""

    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            status_conciliacao,
            motivo_falta_conciliacao,
            valor_pendente,
            inadimplencia_pf,
            inadimplencia_pj
        FROM tabela_concilicacao_convenio
        WHERE id = ?
    """, (int(convenio_id),))

    row = cur.fetchone()
    conn.close()

    if not row:
        return "", "", "", "", ""

    return (
        (row["status_conciliacao"] or ""),
        (row["motivo_falta_conciliacao"] or ""),
        br_money(row["valor_pendente"]),
        br_money(row["inadimplencia_pf"]),
        br_money(row["inadimplencia_pj"]),
    )

def _build_header(dados: dict, convenio_key: str):
    cnpj_conv = (dados.get("cnpj_convenio") or "").strip()
    numero_conv = (dados.get("numero_convenio") or "").strip()
    nome_conv = (dados.get("nome_convenio") or "").strip()
    nome_originador = (dados.get("originador") or "").strip()
    mes_ref = (dados.get("mes_referencia_conciliacao") or "").strip()
    status_c = (dados.get("status_conciliacao") or "").strip()

    return f"""
    <div class="app-title-text-card2">
        <span class="item"><strong>Originador:</strong> {nome_originador}</span>
        <span class="sep">|</span>

        <span class="item"><strong>Nº Convênio:</strong> {numero_conv}</span>
        <span class="sep">|</span>

        <span class="item"><strong>Convênio:</strong> {nome_conv}</span>
        <span class="sep">|</span>

        <span class="item"><strong>Cnpj:</strong> {cnpj_conv}</span>
        <span class="sep">|</span>

        <span class="item"><strong>Mês:</strong> {mes_ref}</span>
        <span class="sep">|</span>

        <span class="item"><strong>Status:</strong> {status_c}</span>
        <span class="sep">|</span>

        <span class="item id"><strong>ID:</strong> {convenio_key}</span>
    </div>
    """


def salvar_contato(numero_convenio, mes_ref, contato_id, area, status, nome, email, telefone, observacao):
    """
    NOVA LÓGICA:
      - Entrada: numero_convenio + mes_referencia_conciliacao (mes_ref)
      - Validação do convênio na tabela_concilicacao_convenio pelo par (numero_convenio, mes_ref)
      - CRUD de contato permanece por numero_convenio (tabela_contato)
    """
    if not numero_convenio or not mes_ref:
        return "Selecione um convênio e o mês de referência antes de salvar contato.", []

    now_sql = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    latest_db = get_latest_db_path()
    bd_utilizado = latest_db.name
    actor = get_actor()

    conn = db_connect()
    cur = conn.cursor()

    # ✅ Valida o convênio selecionado (numero_convenio + mes_ref)
    conv = cur.execute(
        """
        SELECT originador, numero_convenio, nome_convenio, cnpj_convenio, mes_referencia_conciliacao
        FROM tabela_concilicacao_convenio
        WHERE numero_convenio = ?
          AND mes_referencia_conciliacao = ?
        LIMIT 1
        """,
        (str(numero_convenio).strip(), str(mes_ref).strip())
    ).fetchone()

    if not conv:
        conn.close()
        return "Convênio não encontrado para salvar contato (nº + mês ref).", []

    numero_convenio = (conv["numero_convenio"] or "").strip()

    # -------------------------
    # NORMALIZAÇÃO
    # -------------------------
    area = (area or "").strip()
    status = ((status or "ATIVO").strip().upper())
    if status not in ["ATIVO", "INATIVO"]:
        conn.close()
        return "Status inválido. Selecione ATIVO ou INATIVO.", []

    nome = (nome or "").strip()
    email = (email or "").strip()
    telefone = (telefone or "").strip()
    observacao = (observacao or "").strip()

    # Se não tiver nome, devolve lista atual
    if not nome:
        contatos = cur.execute(
            """
            SELECT id, area, status, nome, email, telefone, observacao, criado_em, atualizado_em
            FROM tabela_contato
            WHERE numero_convenio = ?
            ORDER BY id DESC
            """,
            (numero_convenio,)
        ).fetchall()
        conn.close()
        return "Informe ao menos o Nome do contato.", [dict(r) for r in contatos]

    # contato_id coercion
    contato_id_norm = None
    try:
        if contato_id not in (None, "", 0, "0"):
            contato_id_norm = int(contato_id)
    except Exception:
        contato_id_norm = None

    # -------------------------
    # COMANDO PARA WRITER
    # ✅ Corrigido: UPDATE deve usar ID (ou ID+numero_convenio), não só numero_convenio.
    # Senão, editar 1 contato atualiza todos do convênio.
    # -------------------------
    if contato_id_norm:
        metodo = "UPDATE_CONTATO"
        sql = """
            UPDATE tabela_contato
            SET area = ?, status = ?, nome = ?, email = ?, telefone = ?, observacao = ?, atualizado_em = ?
            WHERE id = ?
              AND numero_convenio = ?
        """.strip()
        params = [area, status, nome, email, telefone, observacao, now_sql, contato_id_norm, numero_convenio]
        msg = f"Comando enfileirado: UPDATE_CONTATO (ID {contato_id_norm})"
    else:
        metodo = "INSERT_CONTATO"
        sql = """
            INSERT INTO tabela_contato
            (originador, numero_convenio, nome_convenio, cnpj_convenio,
             area, status, nome, email, telefone, observacao, criado_em, atualizado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """.strip()
        params = [
            conv["originador"], numero_convenio, conv["nome_convenio"], conv["cnpj_convenio"],
            area, status, nome, email, telefone, observacao,
            now_sql, now_sql
        ]
        msg = "Comando enfileirado: INSERT_CONTATO"

    cmd = {
        "id": _make_cmd_id(),
        "created_at": _created_at_br(),
        "actor": actor,
        "bd_utilizado": bd_utilizado,
        "metodo": metodo,
        "sql": " ".join(sql.split()),
        "params": params
    }

    arq = _queue_write(PASTA_ENTRADA, cmd)

    # SELECT (permitido) — pode vir “antigo” até writer aplicar
    contatos = cur.execute(
        """
        SELECT id, area, status, nome, email, telefone, observacao, criado_em, atualizado_em
        FROM tabela_contato
        WHERE numero_convenio = ?
        ORDER BY id DESC
        """,
        (numero_convenio,)
    ).fetchall()

    conn.close()
    return f"{msg} | BD: {bd_utilizado} | Arquivo: {arq.name}", [dict(r) for r in contatos]


def validar_dropdown(valor, choices, nome_campo):
    raw = "" if valor is None else str(valor).strip()
    if not raw:
        return f"Selecione uma opção válida para '{nome_campo}'."

    ok = any(str(c).strip().lower() == raw.lower() for c in choices)
    if not ok:
        return f"Selecione uma opção válida para '{nome_campo}'."
    return None

def salvar_particularidade(
    numero_convenio,
    mes_ref,
    part_id,
    rubrica_produto,
    modelo_de_averbacao,
    retencao,
    telefone,
    observacao,
    status_particularidade,
    retencao_valor,
    retencao_percent
):
    if not numero_convenio or not mes_ref:
        return "Selecione um convênio e o mês referência antes de salvar particularidade.", []

    now_sql = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # sempre pega o último DB (para bd_utilizado e leituras)
    latest_db = get_latest_db_path()
    bd_utilizado = latest_db.name
    actor = get_actor()

    conn = db_connect()
    cur = conn.cursor()

    # Busca dados do convênio usando chave composta (numero + mes)
    conv = cur.execute(
        """
        SELECT originador, numero_convenio, nome_convenio, cnpj_convenio, mes_referencia_conciliacao
        FROM tabela_concilicacao_convenio
        WHERE numero_convenio = ?
          AND mes_referencia_conciliacao = ?
        """,
        (str(numero_convenio).strip(), str(mes_ref).strip())
    ).fetchone()

    if not conv:
        conn.close()
        return "Convênio não encontrado para este mês referência.", []

    # -------------------------
    # NORMALIZAÇÃO PADRÃO
    # -------------------------
    rubrica_produto = (rubrica_produto or "").strip()
    modelo_de_averbacao = (modelo_de_averbacao or "").strip()

    retencao = (retencao or "").strip().upper()
    if retencao not in ["SIM", "NÃO"]:
        conn.close()
        return "Retenção inválida. Selecione SIM ou NÃO.", []

    status_particularidade = (status_particularidade or "").strip().upper()
    if status_particularidade not in ["ATIVO", "INATIVO"]:
        conn.close()
        return "Status inválido. Selecione ATIVO ou INATIVO.", []

    telefone = (telefone or "").strip()
    observacao = (observacao or "").strip()

    val_num = parse_br_number(retencao_valor)
    pct_num = parse_br_number(retencao_percent)

    if retencao != "SIM":
        val_num = None
        pct_num = None

    # -------------------------
    # part_id coercion
    # -------------------------
    part_id_norm = None
    try:
        if part_id not in (None, "", 0, "0"):
            part_id_norm = int(part_id)
    except Exception:
        part_id_norm = None

    # -------------------------
    # COMANDO PARA WRITER
    # -------------------------
    if part_id_norm:
        metodo = "UPDATE_PARTICULARIDADE"
        sql = """
            UPDATE tabela_particularidade
               SET rubrica_produto = ?,
                   modelo_de_averbacao = ?,
                   retencao = ?,
                   retencao_valor = ?,
                   retencao_percent = ?,
                   status_particularidade = ?,
                   telefone = ?,
                   observacao = ?,
                   atualizado_em = ?
             WHERE id = ?
               AND numero_convenio = ?
        """.strip()

        params = [
            rubrica_produto,
            modelo_de_averbacao,
            retencao,
            val_num,
            pct_num,
            status_particularidade,
            telefone,
            observacao,
            now_sql,
            part_id_norm,
            conv["numero_convenio"],
        ]
        msg = f"Comando enfileirado: {metodo} (Particularidade #{part_id_norm})"

    else:
        metodo = "INSERT_PARTICULARIDADE"
        sql = """
            INSERT INTO tabela_particularidade
            (originador, numero_convenio, nome_convenio, cnpj_convenio,
            rubrica_produto, modelo_de_averbacao,
            retencao, retencao_valor, retencao_percent,
            status_particularidade,
            telefone, observacao, criado_em, atualizado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """.strip()

        params = [
            conv["originador"],
            conv["numero_convenio"],
            conv["nome_convenio"],
            conv["cnpj_convenio"],
            rubrica_produto,
            modelo_de_averbacao,
            retencao,
            val_num,
            pct_num,
            status_particularidade,
            telefone,
            observacao,
            now_sql,
            now_sql,
        ]
        msg = "Comando enfileirado: INSERT_PARTICULARIDADE"

    cmd = {
        "id": _make_cmd_id(),
        "created_at": _created_at_br(),
        "actor": actor,
        "bd_utilizado": bd_utilizado,
        "metodo": metodo,
        "sql": " ".join(sql.split()),
        "params": params
    }

    arq = _queue_write(PASTA_ENTRADA, cmd)

    # -------------------------
    # SELECT (permitido) - pode não refletir até writer aplicar
    # -------------------------
    particularidades = cur.execute("""
        SELECT
            id,
            rubrica_produto,
            modelo_de_averbacao,
            retencao,
            retencao_valor,
            retencao_percent,
            status_particularidade,
            telefone,
            observacao,
            criado_em,
            atualizado_em
        FROM tabela_particularidade
        WHERE numero_convenio = ?
        ORDER BY id DESC
    """, (conv["numero_convenio"],)).fetchall()
    conn.close()

    msg = f"{msg} | BD: {bd_utilizado} | Arquivo: {arq.name}"
    return msg, [dict(r) for r in particularidades]


def salvar_conta(numero_convenio, mes_ref, conta_id, banco, agencia, conta, chave_pix, cnpj, status_conta):
    if not numero_convenio or not mes_ref:
        return "Selecione um convênio e o mês de referência antes de salvar conta.", []

    latest_db = get_latest_db_path()
    bd_utilizado = latest_db.name
    now_sql = _now_sql()
    actor = get_actor()

    # normalização
    numero_convenio = str(numero_convenio).strip()
    mes_ref = str(mes_ref).strip()

    banco = (banco or "").strip()
    agencia = (agencia or "").strip()
    conta = (conta or "").strip()
    chave_pix = (chave_pix or "").strip()
    cnpj = (cnpj or "").strip()
    status_conta = normalize_choice(
        status_conta,
        STATUS_CONTA_OPCOES,
        default="ATIVA",
        upper_db=True,
        field="Status da conta"
    )

    conta_id_norm = None
    try:
        if conta_id not in (None, "", 0, "0"):
            conta_id_norm = int(conta_id)
    except Exception:
        conta_id_norm = None

    conn = db_connect(latest_db)
    cur = conn.cursor()

    conv = cur.execute(
        """
        SELECT originador, numero_convenio, nome_convenio, cnpj_convenio, mes_referencia_conciliacao
        FROM tabela_concilicacao_convenio
        WHERE numero_convenio = ?
          AND mes_referencia_conciliacao = ?
        LIMIT 1
        """,
        (numero_convenio, mes_ref)
    ).fetchone()

    if not conv:
        conn.close()
        return "Convênio não encontrado para este mês de referência.", []

    if conta_id_norm:
        metodo = "UPDATE_CONTA"
        sql = """
            UPDATE tabela_conta_conv
            SET banco=?, agencia=?, conta=?, chave_pix=?, cnpj=?, status_conta=?, atualizado_em=?
            WHERE numero_convenio = ?
        """.strip()
        params = [banco, agencia, conta, chave_pix, cnpj, status_conta, now_sql, conv["numero_convenio"]]
        msg = f"Comando enfileirado: UPDATE_CONTA (Convenio {conv['numero_convenio']})"
    else:
        metodo = "INSERT_CONTA"
        sql = """
            INSERT INTO tabela_conta_conv
            (originador, numero_convenio, nome_convenio, cnpj_convenio,
             banco, agencia, conta, chave_pix, cnpj, status_conta, criado_em, atualizado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """.strip()
        params = [
            conv["originador"], conv["numero_convenio"], conv["nome_convenio"], conv["cnpj_convenio"],
            banco, agencia, conta, chave_pix, cnpj, status_conta, now_sql, now_sql
        ]
        msg = "Comando enfileirado: INSERT_CONTA"

    payload = {
        "id": _make_cmd_id(),
        "created_at": _created_at_br(),
        "actor": actor,
        "bd_utilizado": bd_utilizado,
        "metodo": metodo,
        "sql": " ".join(sql.split()),
        "params": params
    }

    arq = _queue_write(PASTA_ENTRADA, payload)

    contas = cur.execute("""
        SELECT id, banco, agencia, conta, chave_pix, cnpj, status_conta, criado_em, atualizado_em
        FROM tabela_conta_conv
        WHERE numero_convenio = ?
        ORDER BY id DESC
    """, (conv["numero_convenio"],)).fetchall()

    conn.close()

    return f"{msg} | BD: {bd_utilizado} | Arquivo: {arq.name}", [dict(r) for r in contas]


# -----------------------------
# Form: limpar + select handlers (robustos)
# -----------------------------
def limpar_form_contato():
    return None, "", "ATIVO", "", "", "", ""


def on_select_contato(df, evt: gr.SelectData):
    row = evt.index[0]
    if hasattr(df, "iloc"):
        try:
            r = df.iloc[row].to_dict()
        except Exception:
            return None, "", "ATIVO", "", "", "", ""
    else:
        try:
            r = df[row]
        except Exception:
            return None, "", "ATIVO", "", "", "", ""

    return (
        r.get("id"),
        r.get("area", "") or "",
        r.get("status", "") or "ATIVO",
        r.get("nome", "") or "",
        r.get("email", "") or "",
        r.get("telefone", "") or "",
        r.get("observacao", "") or "",
    )





def montar_dados_analitico(row: dict) -> dict:
    dados = dict(row)

    dados["porcentagem_inadimplencia"] = calc_percent_inadimplencia(
        dados.get("valor_repasse"),
        dados.get("valor_retorno"),
    )

    # ✅ pendente = retorno - repasse
    dados["valor_pendente"] = calc_valor_pendente(
        dados.get("valor_retorno"),
        dados.get("valor_repasse"),
    )

    return dados

def parse_br_number(v):
    """Aceita float/int, '1234.56', '1.234,56', 'R$ 1.234,56', None."""
    if v is None:
        return None
    if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)):
        return float(v)

    s = str(v).strip()
    if not s:
        return None

    # remove R$, espaços e tudo que não seja dígito, . , ou -
    s = re.sub(r"[^\d,.\-]", "", s)

    # casos comuns BR: 1.234,56 -> 1234.56
    # se tem vírgula, assume vírgula decimal e ponto milhar
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None

def df_row_to_dict(df, idx):
    row = df.iloc[idx].to_dict()
    row["porcentagem_inadimplencia"] = calc_percent_inadimplencia(
        row.get("valor_repasse"),
        row.get("valor_retorno"),
    )
    return row

def on_valores_change(valor_repasse, valor_retorno):
    # retorna o TEXTO formatado (%), pois o .change() não passa pelo fmt do preencher_dados_updates
    return br_percent(calc_percent_inadimplencia(valor_repasse, valor_retorno))

def calc_percent_inadimplencia(valor_repasse, valor_retorno):
    rep = parse_br_number(valor_repasse)
    ret = parse_br_number(valor_retorno)

    if rep is None or ret is None:
        return None
    if ret == 0:
        return None 

    return rep / ret

# =========================================================
# 1) FUNÇÃO DE CÁLCULO (RETORNO - REPASSE)
#    (usa seu parse_br_number existente)
# =========================================================
def calc_valor_pendente(valor_retorno, valor_repasse):
    ret = parse_br_number(valor_retorno)
    rep = parse_br_number(valor_repasse)

    if ret is None or rep is None:
        return None

    return ret - rep


def on_pendente_change(valor_retorno, valor_repasse):
    return br_money(calc_valor_pendente(valor_retorno, valor_repasse))

def norm_upper(v) -> str:
    """Normaliza qualquer entrada para UPPER e sem espaços."""
    return ("" if v is None else str(v)).strip().upper()

def normalize_choice(value, choices, *, default=None, upper_db=False, field=""):
    """
    - Casa value com choices ignorando case/trim
    - Se não casar: retorna default (ou levanta ValueError)
    - Se upper_db=True: devolve em UPPER (para gravar no BD)
    """
    raw = "" if value is None else str(value).strip()
    if not raw:
        if default is not None:
            return default.upper() if upper_db and isinstance(default, str) else default
        return ""

    for c in choices:
        if str(c).strip().lower() == raw.lower():
            return str(c).strip().upper() if upper_db else str(c).strip()

    # não casou
    if default is not None:
        return default.upper() if upper_db and isinstance(default, str) else default

    raise ValueError(f"Valor inválido para {field or 'campo'}: {raw!r}")

def _coerce_choice(raw, choices, default):
    s = (raw or "").strip()
    for c in choices:
        if c.strip().lower() == s.lower():
            return c
    return default

MODELO_AVERBACAO_OPCOES = ["Parcelado", "Arquivo remessa"]
STATUS_PARTICULARIDADE_OPCOES = ["ATIVO", "INATIVO"]

def limpar_form_part():
    return None, "", "Arquivo remessa", "NÃO", "", "", "ATIVO", "", ""

def on_select_part(df, evt: gr.SelectData):
    row = evt.index[0]

    if hasattr(df, "iloc"):
        try:
            r = df.iloc[row].to_dict()
        except Exception:
            return limpar_form_part()
    else:
        try:
            r = df[row]
        except Exception:
            return limpar_form_part()

    modelo_ok = _coerce_choice(
        r.get("modelo_de_averbacao"),
        MODELO_AVERBACAO_OPCOES,
        "Arquivo remessa"
    )

    ret_ok = _coerce_choice(r.get("retencao"), ["SIM", "NÃO"], "NÃO")

    # ✅ status particularidade correto
    status_ok = normalize_choice(
        r.get("status_particularidade"),
        STATUS_PARTICULARIDADE_OPCOES,
        default="ATIVO",
        upper_db=True,
        field="Status particularidade"
    )

    return (
        r.get("id"),
        r.get("rubrica_produto", "") or "",
        modelo_ok,
        ret_ok,
        r.get("telefone", "") or "",
        r.get("observacao", "") or "",
        status_ok,
        br_money(r.get("retencao_valor")),
        "" if r.get("retencao_percent") in (None, "") else str(r.get("retencao_percent")),
    )



def pick_choice(raw, choices, fallback=None):
    if raw is None:
        return fallback
    s = str(raw).strip()
    if not s:
        return fallback

    if s in choices:
        return s

    for c in choices:
        if str(c).strip().lower() == s.lower():
            return c

    for c in choices:
        if s.lower() in str(c).strip().lower():
            return c

    return fallback


def limpar_form_conta():
    return None, "", "", "", "", "", "ATIVA"


def on_select_conta(df, evt: gr.SelectData):
    row = evt.index[0]
    r = df.iloc[row].to_dict()

    status_ok = normalize_choice(
        r.get("status_conta"),
        STATUS_CONTA_OPCOES,
        default="ATIVA",
        upper_db=True,
        field="Status conta"
    )

    return (
        r.get("id"),
        r.get("banco", "") or "",
        r.get("agencia", "") or "",
        r.get("conta", "") or "",
        r.get("chave_pix", "") or "",
        r.get("cnpj", "") or "",
        status_ok,
    )


# -----------------------------
# Navegação (páginas)
# -----------------------------
PAGE_MODULOS = "MODULOS"
PAGE_CONCILIACAO = "CONCILIACAO"
PAGE_SINTETICO = "SINTETICO"
PAGE_ANALITICO = "ANALITICO"


def _breadcrumb(page, ctx=None):
    if page == PAGE_MODULOS:
        return "Você está em: Módulos"
    if page == PAGE_CONCILIACAO:
        return "Você está em: Módulos > Conciliação"
    if page == PAGE_SINTETICO:
        return "Você está em: Módulos > Conciliação > Controle Sintético"
    if page == PAGE_ANALITICO:
        base = "Você está em: Módulos > Conciliação > Controle Sintético > Controle Analítico"
        if isinstance(ctx, dict):
            n = (ctx.get("numero_convenio") or "").strip()
            m = (ctx.get("mes_referencia_conciliacao") or "").strip()
            if n and m:
                base += f" (Convênio {n} / {m})"
        return base
    return ""


def nav_to(page, numero_convenio=None, mes_ref=None):
    v_mod = page == PAGE_MODULOS
    v_con = page == PAGE_CONCILIACAO
    v_sin = page == PAGE_SINTETICO
    v_ana = page == PAGE_ANALITICO

    # ✅ contexto do breadcrumb (agora não é mais convenio_id)
    ctx = {
        "numero_convenio": (str(numero_convenio).strip() if numero_convenio is not None else ""),
        "mes_referencia_conciliacao": (str(mes_ref).strip() if mes_ref is not None else ""),
    }

    bread = _breadcrumb(page, ctx)
    back_visible = page != PAGE_MODULOS

    return (
        page,
        gr.update(value=bread),
        gr.update(visible=back_visible),
        gr.update(visible=v_mod),
        gr.update(visible=v_con),
        gr.update(visible=v_sin),
        gr.update(visible=v_ana),
    )

def nav_back(current_page):
    if current_page == PAGE_ANALITICO:
        return nav_to(PAGE_SINTETICO)
    if current_page == PAGE_SINTETICO:
        return nav_to(PAGE_CONCILIACAO)
    if current_page == PAGE_CONCILIACAO:
        return nav_to(PAGE_MODULOS)
    return nav_to(PAGE_MODULOS)

def carregar_convenio_por_chave(numero_convenio: str, mes_ref: str):
    latest_db = get_latest_db_path()
    conn = db_connect(latest_db)
    cur = conn.cursor()

    numero_convenio = (str(numero_convenio).strip() if numero_convenio else "")
    mes_ref = (str(mes_ref).strip() if mes_ref else "")

    row = cur.execute(
        """
        SELECT *
        FROM tabela_concilicacao_convenio
        WHERE numero_convenio = ?
          AND mes_referencia_conciliacao = ?
        """,
        (numero_convenio, mes_ref)
    ).fetchone()

    if not row:
        conn.close()
        return (
            {"erro": "Convênio não encontrado"},
            [],  # contatos
            [],  # particularidades
            [],  # contas
            "Convênio não encontrado.",
            numero_convenio,
            mes_ref
        )

    # ========================
    # CARREGA RELACIONADOS
    # ========================

    contatos = cur.execute("""
        SELECT
            id, area, status, nome, email, telefone, observacao,
            criado_em, atualizado_em
        FROM tabela_contato
        WHERE numero_convenio = ?
        ORDER BY id DESC
    """, (numero_convenio,)).fetchall()

    particularidades = cur.execute("""
        SELECT
            id,
            rubrica_produto,
            modelo_de_averbacao,
            retencao,
            retencao_valor,
            retencao_percent,
            status_particularidade,
            telefone,
            observacao,
            criado_em,
            atualizado_em
        FROM tabela_particularidade
        WHERE numero_convenio = ?
        ORDER BY id DESC
    """, (numero_convenio,)).fetchall()

    contas = cur.execute("""
        SELECT
            id, banco, agencia, conta, chave_pix, cnpj, status_conta,
            criado_em, atualizado_em
        FROM tabela_conta_conv
        WHERE numero_convenio = ?
        ORDER BY id DESC
    """, (numero_convenio,)).fetchall()

    conn.close()

    return (
        dict(row),
        [dict(r) for r in contatos],
        [dict(r) for r in particularidades],
        [dict(r) for r in contas],
        f"Detalhe carregado do convênio {numero_convenio} | Mês {mes_ref}.",
        numero_convenio,
        mes_ref
    )


def salvar_dados_gr(numero_convenio, mes_ref, *vals):
    """
    Inputs:
      numero_convenio (str)  -> chave do convênio
      mes_ref (str)          -> mes_referencia_conciliacao (ex: '02/2026' ou '2026-02' conforme seu BD)
      vals = valores dos inputs na mesma ordem do DADOS_FIELDS

    Saída:
      msg_dados, analitico_header, dados_state, *updates_dados_inputs
    """
    numero_convenio = (numero_convenio or "").strip()
    mes_ref = (mes_ref or "").strip()

    if not numero_convenio or not mes_ref:
        clear_updates = [gr.update(value="") for _ in DADOS_FIELDS]
        return (
            "<div class='alert'>Selecione um convênio e o mês referência antes de salvar.</div>",
            "<div class='alert'>Selecione um convênio no Sintético.</div>",
            {},
            *clear_updates
        )

    # 1) monta payload somente com campos editáveis
    payload = {}
    for f, raw in zip(DADOS_FIELDS, vals):
        if not f.get("editable", True):
            continue
        payload[f["key"]] = raw

    # 2) normalizações
    if "status_conciliacao" in payload:
        payload["status_conciliacao"] = normalize_choice(
            payload.get("status_conciliacao"),
            STATUS_CONCILIACAO_OPCOES,
            default="PENDENTE",
            upper_db=True,
            field="Status conciliação"
        )

    # Motivo
    motivo_raw = (payload.get("motivo_falta_conciliacao") or "").strip()

    if motivo_raw:
        # Valida contra as opções oficiais (case-insensitive)
        payload["motivo_falta_conciliacao"] = safe_pick_choice(
            motivo_raw,
            MOTIVO_FALTA_CONCILIACAO_OPCOES
        )
    else:
        payload["motivo_falta_conciliacao"] = ""

    for k in ["valor_remessa", "valor_retorno", "valor_repasse"]:
        if k in payload:
            payload[k] = parse_br_number(payload[k])

    if "data_corte" in payload:
        payload["data_corte"] = (payload["data_corte"] or "").strip()

    # regra: motivo só vale quando status == CONCILIADO (PARCIAL)
    st = (payload.get("status_conciliacao") or "").strip().upper()
    if st != "CONCILIADO (PARCIAL)":
        payload["motivo_falta_conciliacao"] = ""

    try:
        latest_db = get_latest_db_path()
        bd_utilizado = latest_db.name
        actor = get_actor()

        now_sql = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        payload["atualizado_em"] = now_sql

        conn = db_connect(latest_db)
        cur = conn.cursor()

        # 3) valida se existe a linha (chave composta)
        conv = cur.execute(
            """
            SELECT 1
            FROM tabela_concilicacao_convenio
            WHERE numero_convenio = ?
              AND mes_referencia_conciliacao = ?
            """,
            (numero_convenio, mes_ref)
        ).fetchone()

        if not conv:
            conn.close()
            keep_updates = [gr.update() for _ in DADOS_FIELDS]
            return (
                "<div class='alert'>Convênio não encontrado no snapshot para este mês.</div>",
                gr.update(),
                gr.update(),
                *keep_updates
            )

        # 4) monta SQL dinâmico (writer)
        set_sql = ", ".join([f"{k} = ?" for k in payload.keys()])
        sql = f"""
            UPDATE tabela_concilicacao_convenio
            SET {set_sql}
            WHERE numero_convenio = ?
              AND mes_referencia_conciliacao = ?
        """.strip()

        params = list(payload.values()) + [numero_convenio, mes_ref]

        cmd = {
            "id": _make_cmd_id(),
            "created_at": _created_at_br(),
            "actor": actor,
            "bd_utilizado": bd_utilizado,
            "metodo": "UPDATE_DADOS_CONVENIO",
            "sql": " ".join(sql.split()),
            "params": params
        }

        arq = _queue_write(PASTA_ENTRADA, cmd)

        # 5) recarrega UI (SELECT) — ainda pode não refletir até writer aplicar
        dados, contatos, parts, contas, msg, numero_convenio, mes_ref = carregar_convenio_por_chave(numero_convenio, mes_ref)
        dados = montar_dados_analitico(dados)

        header = _build_header(dados, f"{numero_convenio}/{mes_ref}")
        updates = preencher_dados_updates(dados)

        conn.close()

        msg_ok = f"<div class='alert'>Comando enfileirado ({arq.name}) — BD: {bd_utilizado}</div>"
        return (msg_ok, header, dados, *updates)

    except Exception as e:
        keep_updates = [gr.update() for _ in DADOS_FIELDS]
        return (
            f"<div class='alert'>Erro ao salvar: {str(e)}</div>",
            gr.update(),
            gr.update(),
            *keep_updates
        )


def recarregar_dados_gr(numero_convenio, mes_ref):
    if not numero_convenio or not mes_ref:
        clear_updates = [gr.update(value="") for _ in DADOS_FIELDS]
        return (
            "<div class='alert'>Selecione um convênio antes de recarregar.</div>",
            "<div class='alert'>Selecione um convênio no Sintético.</div>",
            {},
            *clear_updates,
            ensure_df([], CONTATO_COLS),
            ensure_df([], PART_COLS),
            ensure_df([], CONTA_COLS),
        )

    # você precisa ter uma função de carregar por (numero_convenio, mes_ref)
    dados, contatos, parts, contas, msg, *resto = carregar_convenio_por_chave(numero_convenio, mes_ref)

    dados = montar_dados_analitico(dados)
    header = _build_header(dados, f"{numero_convenio}/{mes_ref}") # ou ajuste header p/ não depender de id
    updates = preencher_dados_updates(dados)

    return (
        "<div class='alert'>Dados recarregados.</div>",
        header,
        dados,
        *updates,
        ensure_df(contatos, CONTATO_COLS),
        ensure_df(parts, PART_COLS),
        ensure_df(contas, CONTA_COLS),
    )

def preencher_dados_updates(dados: dict):
    dados = dados or {}
    updates = []

    status_up = (dados.get("status_conciliacao") or "").strip().upper()

    for f in DADOS_FIELDS:
        key = f["key"]
        field_type = f.get("type", "text")
        options = f.get("options") or []
        fmt = f.get("fmt")
        raw = dados.get(key)

        if key == "motivo_falta_conciliacao":
            show = status_up == "CONCILIADO (PARCIAL)"
            val = safe_pick_choice_ui(raw, options) if show else ""
            updates.append(
                gr.update(
                    value=val,
                    visible=show,
                    interactive=show,
                )
            )
            continue

        if field_type == "select" and options:
            updates.append(gr.update(value=safe_pick_choice_ui(raw, options)))
            continue

        if raw is None:
            val = ""
        else:
            if fmt:
                try:
                    val = fmt(raw)
                except Exception:
                    val = str(raw)
            else:
                val = str(raw)

        updates.append(gr.update(value=val))

    return updates

# -----------------------------
# App
# -----------------------------
def build_app():

    js_code = """ 
        (function () {
        const POLL_MS = 250;   // 1000 = 1x por segundo
        const GAP_PX  = 6;
        const PAD_PX  = 10;
        const Z       = 999999;

        function getRoot() {
            const ga = document.querySelector("gradio-app");
            return (ga && ga.shadowRoot) ? ga.shadowRoot : document;
        }

        function getChoicesFromTarget(target) {
            return target?.closest?.(".choices[data-type*='select-one']");
        }

        function getAnchor(choicesEl) {
            return choicesEl?.querySelector(".choices__inner");
        }

        function getList(choicesEl) {
            return choicesEl?.querySelector(".choices__list--dropdown");
        }

        function isOpen(choicesEl) {
            if (!choicesEl) return false;
            if (choicesEl.classList.contains("is-active")) return true;
            const list = getList(choicesEl);
            const exp = list?.getAttribute("aria-expanded");
            return exp === "true";
        }

        function isVisible(el) {
            if (!el) return false;
            if (!document.contains(el)) return false;
            if (el.offsetParent === null) return false;
            const r = el.getBoundingClientRect();
            return r.width > 2 && r.height > 2;
        }

        function place(choicesEl) {
            const anchor = getAnchor(choicesEl);
            const list   = getList(choicesEl);
            if (!anchor || !list) return;
            if (!isVisible(anchor)) return;

            const r = anchor.getBoundingClientRect();
            const left  = Math.round(r.left);
            const width = Math.round(r.width);

            const top = Math.round(r.bottom + GAP_PX);
            const spaceBelow = Math.max(140, window.innerHeight - top - PAD_PX);

            list.style.position = "fixed";
            list.style.left = `${left}px`;
            list.style.top = `${top}px`;
            list.style.width = `${width}px`;
            list.style.zIndex = String(Z);

            list.style.maxHeight = `${spaceBelow}px`;
            list.style.overflowY = "auto";

            list.style.transform = "none";
            list.style.marginTop = "0";
        }

        let active = { choicesEl: null, timer: null };

        function stopLoop() {
            if (active.timer) {
            clearInterval(active.timer);
            active.timer = null;
            }
            active.choicesEl = null;
        }

        function startLoop(choicesEl) {
            active.choicesEl = choicesEl;

            // warmup (tabs/visible=False às vezes precisa de alguns frames)
            let tries = 0;
            (function warmup() {
            tries++;
            place(choicesEl);
            const anchor = getAnchor(choicesEl);
            const ok = isVisible(anchor);
            if (!ok && tries < 20 && isOpen(choicesEl)) {
                requestAnimationFrame(warmup);
            }
            })();

            if (active.timer) clearInterval(active.timer);
            active.timer = setInterval(() => {
            const el = active.choicesEl;
            if (!el || !document.contains(el) || !isOpen(el)) {
                stopLoop();
                return;
            }
            place(el);
            }, POLL_MS);
        }

        function activate(target) {
            const choicesEl = getChoicesFromTarget(target);
            if (!choicesEl) return;

            requestAnimationFrame(() => {
            if (isOpen(choicesEl)) {
                startLoop(choicesEl);
            } else {
                setTimeout(() => { if (isOpen(choicesEl)) startLoop(choicesEl); }, 80);
            }
            });
        }

        function boot() {
            const root = getRoot();
            root.addEventListener("pointerdown", (e) => activate(e.target), true);
            root.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown") activate(e.target);
            }, true);

            window.addEventListener("scroll", () => {
            if (active.choicesEl && isOpen(active.choicesEl)) place(active.choicesEl);
            }, true);

            window.addEventListener("resize", () => {
            if (active.choicesEl && isOpen(active.choicesEl)) place(active.choicesEl);
            }, true);
        }

        const t0 = Date.now();
        const timer = setInterval(() => {
            const root = getRoot();
            if (root && root.querySelector) {
            boot();
            clearInterval(timer);
            }
            if (Date.now() - t0 > 8000) clearInterval(timer);
        }, 120);
        })();
    """
    css_part_01_tokens = """
    /* =========================================================
    01) DESIGN SYSTEM (TOKENS)
    ========================================================= */
    :root{
    --radius: 14px;

    --primary: var(--primary-500, #2563eb);
    --primary-dark: var(--primary-700, #1e40af);

    --card: var(--panel-background);
    --border: var(--border-color-primary);

    --text: var(--body-text-color);
    --muted: var(--body-text-color-subdued);

    --shadow-xs: 0 1px 6px rgba(0,0,0,.05);
    --shadow-sm: 0 6px 18px rgba(0,0,0,.06);
    --shadow-md: 0 10px 26px rgba(0,0,0,.08);

    --ring: 0 0 0 3px rgba(37,99,235,.18);
    --app-bg: linear-gradient(to top, #dfe9f3 2%, white 100%);
    --app-bg-topbar: linear-gradient(to right, #1488cc, #2b32b2);
    --app-card-modulos: linear-gradient(to right, #1488cc, #2b32b2);
    --app-card-modulos-container: linear-gradient(157deg,rgba(196, 233, 255, 1) 0%, rgba(255, 255, 255, 1) 33%, rgba(255, 255, 255, 1) 67%, rgba(196, 233, 255, 1) 99%);
    --app-card-submodulos: linear-gradient(to right, #1488cc, #2b32b2);
    --app-card-controle_sintetico: var(--app-card-modulos);
    --app-card-controle_analitico: var(--app-card-modulos);
    --app-card-controle_analitico_abas: linear-gradient(to right,#f5f7fa,#c3cfe2);
    --font-family: "Inter","Segoe UI",Arial,sans-serif;
    --color-text-h1: #ffffff;
    --color-text-h2: #ffffff;
    --color-text-h3: #ffffff;
    --color-text-h4: #ffffff;
    --color-text-h2-invert: #000000;
    --color-text-h4-invert: #000000;
    --tab-text-muted: var(--color-text-h4);
    --background-disabled: linear-gradient(180deg,rgba(0,0,0,.06),rgba(0,0,0,.02));
    --color-disabled: #6b7280;
    
    /*
    =======================================================
                    TABELA SINTETICA
    =======================================================
    */
    --tbl-bg: #ffffff;
    --tab-bg-selected: linear-gradient(181deg,#fff 69%,#e3e9ff 100%);
    --tbl-border: #e5e7eb;
    --tbl-text: #1f2937;

    --tbl-head-bg: linear-gradient(
        180deg,
        rgba(37,99,235,.14),
        rgba(37,99,235,.06)
    );
    --tbl-head-text: #1e3a8a;
    --tbl-head-border: rgba(37,99,235,.35);

    --tbl-row-even: rgba(0,0,0,.018);
    --tbl-row-hover: rgba(37,99,235,.055);

    --tbl-row-selected: rgba(37,99,235,.18);
    --tbl-row-selected-accent: #2563eb;

    --tbl-scrollbar-thumb: rgba(0,0,0,.22);
    --tbl-scrollbar-track: rgba(0,0,0,.06);

    /*
    =======================================================
                        ABAS
    =======================================================
    */
    --primary: linear-gradient(181deg,rgba(255, 255, 255, 1) 69%, rgba(227, 233, 255, 1) 100%);
    --primary-soft: #2a6fda;

    --card: #ffffff;
    --border: #e4e9f2;

    --tab-text: #4b6a9b;          /* texto inativo */
    --tab-text-selected: #000000;
    --tab-selected: #FFFFFF;      /* texto ativo */
    --tab-divider: #d6deec;

    --tab-hover-bg: rgba(30,95,191,.08);
    --tab-underline: #1e5fbf;

    /* ===== Acessibilidade ===== */
    --btn-ring: 0 0 0 3px rgba(30,95,191,.25);
    }
    """

    css_part_02_dark = """
    /* =========================================================
    02) DARK THEME OVERRIDES
    ========================================================= */
    body.dark{
    --app-bg: linear-gradient(to right, #0f0c29, #302b63, #24243e);
    --app-card-modulos: linear-gradient(to right, #1488cc, #2b32b2);
    --app-card-modulos-container: linear-gradient(157deg,rgba(57, 64, 115, 1) 0%, rgba(76, 142, 175, 1) 31%, rgba(76, 142, 175, 1) 66%, rgba(57, 64, 115, 1) 100%);
    --app-card-submodulos: var(--app-card-modulos);
    --app-card-submodulos-container: var(--app-card-modulos-container);
    --app-card-controle_sintetico: var(--app-card-modulos);
    --app-card-controle_analitico: var(--app-card-modulos);
    --app-card-controle_analitico_abas: linear-gradient(to right,#485563,#29323c);

    --background-disabled: linear-gradient(180deg, rgba(255,255,255,.08), rgba(255,255,255,.04));
    --color-disabled: #94a3b8;

    --color-text-h1: #ffffff;
    --color-text-h2: #ffffff;
    --color-text-h3: #ffffff;
    --color-text-h4: #ffffff;
    --color-text-h2-invert: #0000;
    --color-text-h4-invert: #0000;
    --tab-text-muted: var(--color-text-h4);

    /*
    =======================================================
                    TABELA SINTETICA
    =======================================================
    */
    --tbl-bg: #0f172a;
    --tbl-border: #1e293b;
    --tbl-text: #e5e7eb;

    --tbl-head-bg: linear-gradient(
        180deg,
        rgba(59,130,246,.28),
        rgba(59,130,246,.14)
    );
    --tbl-head-text: #bfdbfe;
    --tbl-head-border: rgba(59,130,246,.45);

    --tbl-row-even: rgba(255,255,255,.03);
    --tbl-row-hover: rgba(59,130,246,.14);

    --tbl-row-selected: rgba(59,130,246,.35);
    --tbl-row-selected-accent: #60a5fa;

    --tbl-scrollbar-thumb: rgba(255,255,255,.28);
    --tbl-scrollbar-track: rgba(255,255,255,.08);

    /*
    =======================================================
                        ABAS
    =======================================================
    */
    --tab-hover-bg: color-mix(in srgb, #ffffff 10%, transparent);
    --tab-divider: color-mix(in srgb, #ffffff 12%, transparent);
    }
    """

    css_part_03_base = """
    /* =========================================================
    03) BASE (GLOBAL)
    ========================================================= */
    html, body{ height:100%; }

    body, gradio-app,
    .gradio-container{
    background: var(--app-bg) !important;
    color: var(--color-text-h4) !important;
    font-family: "Inter","Segoe UI",Arial,sans-serif !important;
    position: relative;
    z-index: 1;
    }
    """

    css_part_04_container = """
    /* =========================================================
    04) LARGURA / PADRÃO GLOBAL DO APP (GLOBAL)
    ========================================================= */
    .gradio-container{
    max-width: none !important;
    width: 100vw !important;
    margin: 0 !important;
    padding: 12px 14px 28px !important;
    }
    """

    css_part_05_topbar = """
    /* =========================================================
    05) TOPBAR
    ========================================================= */
    .app-topbar{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;

    padding: 18px 20px;
    margin-bottom: 16px;

    border-radius: calc(var(--radius) + 2px);
    border: 1px solid var(--border);

    background: var(--app-bg-topbar);

    box-shadow: var(--shadow-sm);
    backdrop-filter: blur(8px);

    position: relative;
    overflow: hidden;
    }

    .app-topbar::after{
    content:"";
    position:absolute;
    inset:0;
    background: rgba(0,0,0,.18);
    pointer-events:none;
    }

    .app-topbar,
    .app-topbar *{
    color: var(--body-text-color) !important;
    position: relative;
    z-index: 1;
    }

    .app-title h3{
    margin: 0 !important;
    letter-spacing: .2px;
    font-weight: 800;
    color: var(--body-text-color) !important;
    }

    .app-title small,
    .app-title p,
    .app-title p small{
    color: var(--body-text-color-subdued) !important;
    }

    .breadcrumb-pill{
    display: inline-flex;
    align-items: center;
    gap: 8px;

    padding: 6px 14px;
    border-radius: 999px;

    background: linear-gradient(
        180deg,
        rgba(255,255,255,.22),
        rgba(255,255,255,.08)
    ) !important;

    border: 1px solid rgba(255,255,255,.28);

    color: #FFFFFF !important;
    font-weight: 600;
    font-size: .9rem;
    letter-spacing: .15px;

    backdrop-filter: blur(10px) saturate(140%);
    -webkit-backdrop-filter: blur(10px) saturate(140%);

    box-shadow:
        0 1px 2px rgba(0,0,0,.12),
        inset 0 1px 0 rgba(255,255,255,.35);

    white-space: nowrap;
    user-select: none;
    }

    .breadcrumb-pill:hover{
    background: linear-gradient(
        180deg,
        rgba(255,255,255,.30),
        rgba(255,255,255,.12)
    ) !important;
    border-color: rgba(255,255,255,.38);
    }

    .breadcrumb-pill svg,
    .breadcrumb-pill i{
    font-size: .95em;
    opacity: .85;
    }

    @media (prefers-color-scheme: dark){
    .breadcrumb-pill{
        background: linear-gradient(
        180deg,
        rgba(0,0,0,.35),
        rgba(0,0,0,.18)
        ) !important;

        border: 1px solid rgba(255,255,255,.18);

        box-shadow:
        0 1px 3px rgba(0,0,0,.45),
        inset 0 1px 0 rgba(255,255,255,.12);
    }
    }

    .app-title h3{
    color: #ffffff !important;
    }
    """

    css_part_06_cards = """
    /* =========================================================
    06) CARDS
    ========================================================= */
    .card{
    border-radius: calc(var(--radius) + 2px);
    border: 1px solid var(--border);
    background: var(--card);
    box-shadow: var(--shadow-sm);
    padding: 22px 22px 18px;
    margin-bottom: 16px;
    position: relative;
    overflow: hidden;
    }

    /* camada visual do blur */
    .card::before{
    content: "";
    position: absolute;
    inset: 0;
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    pointer-events: none;
    z-index: 0;
    }

    /* garante que o conteúdo fique acima do blur */
    .card > *{
    position: relative;
    z-index: 1;
    }

    .card h1, .card h2{
    margin-top: 0 !important;
    color: var(--color-text-h2) !important;
    }

    .card h3{
    margin-top: 0 !important;
    color: var(--color-text-h3) !important;
    }
    .card h4{
    margin-top: 0 !important;
    color: var(--color-text-h4) !important;
    }

    .card-modululos{ background: var(--app-card-modulos) !important; }
    .card-modululos-container{ background: var(--app-card-modulos-container) !important; }
    .card-submodululos{ background: var(--app-card-modulos) !important; }
    .card-submodululos-container{ background: var(--app-card-modulos-container) !important; }
    .card-controle_sintetico{ background: var(--app-card-controle_sintetico) !important; }
    .card-controle_analitico{ background: var(--app-card-controle_analitico) !important; }
    .card-controle_analitico_abas{ background: var(--app-card-controle_analitico_abas) !important; }
    """

    css_part_07_texts_alerts = """
    /* =========================================================
    07) TEXTOS / ALERTAS
    ========================================================= */
    .gradio-container h1, h2{
    color: var(--color-text-h1) !important;
    font-family: var(--font-family) !important;
    }

    .app-title-text{
    color: var(--color-text-h2) !important;
    font-family: var(--font-family) !important;
    }

    .muted{
    color: var(--color-text-h3) !important;
    font-size: .95rem;
    line-height: 1.35;
    }

    .tbl-hint{
    display:flex;
    align-items:center;
    gap:10px;

    padding: 12px 14px;
    border-radius: var(--radius);

    background: rgba(37,99,235,.06);
    border: 1px solid rgba(37,99,235,.18);
    color: var(--color-text-h4);
    }

    .alert{
        display:flex;
        align-items:center;
        gap:10px;

        padding: 12px 14px;
        border-radius: var(--radius);

        background: rgba(37,99,235,.06);
        border: 1px solid rgba(37,99,235,.18);
        color: var(--color-text-h4-invert);
    }

    .alert::before{
        content:"";
        width:10px; height:10px;
        border-radius:999px;
        background: var(--primary);
        box-shadow: 0 0 0 3px rgba(37,99,235,.18);
    }

    .alert-invert{
        display:flex;
        align-items:center;
        gap:10px;

        padding: 12px 14px;
        border-radius: var(--radius);

        background: rgba(37,99,235,.06);
        border: 1px solid rgba(37,99,235,.18);
        color: var(--color-text-h4);
    }

    .alert-invert::before{
        content:"";
        width:10px; height:10px;
        border-radius:999px;
        background: var(--primary);
        box-shadow: 0 0 0 3px rgba(37,99,235,.18);
    }

    .aba_text_fora_campo{
    font-family: var(--font-family) !important;
    color: var(--color-text-h4-invert) !important;
    }

    /* =========================================================
    CAMPOS SOMENTE LEITURA / BLOQUEADOS (interactive=False)
    ========================================================= */

    /* Textbox, Textarea e Input desabilitados */
    .gradio-container input[disabled],
    .gradio-container textarea[disabled],
    .gradio-container select[disabled],
    .gradio-container .wrap input[disabled],
    .gradio-container .wrap textarea[disabled]{
        background: var(--background-disabled) !important;

        color: var(--color-disabled) !important; 
        border: 1px solid rgba(0,0,0,.18) !important;

        cursor: not-allowed !important;
        opacity: 1 !important;
        box-shadow:
            inset 0 1px 2px rgba(0,0,0,.08),
            inset 0 0 0 999px rgba(0,0,0,.02);
    }

    /* Placeholder em campos bloqueados */
    .gradio-container input[disabled]::placeholder,
    .gradio-container textarea[disabled]::placeholder{
        color: var(--color-disabled) !important;
    }

    /* Dropdown (choices.js) desabilitado */
    .gradio-container .choices.is-disabled .choices__inner{
        background: var(--background-disabled) !important;

        border: 1px solid rgba(0,0,0,.18) !important;
        color: var(--color-disabled) !important;

        cursor: not-allowed !important;
        opacity: 1 !important;
    }

    /* Label do campo bloqueado */
    .gradio-container label:has(+ .wrap input[disabled]),
    .gradio-container label:has(+ .wrap textarea[disabled]),
    .gradio-container label:has(+ .wrap select[disabled]){
        color: var(--color-disabled) !important;
    }

    """

    css_part_08_tabs = """
    /* =========================================================
    08) ABAS (Tabs)
    ========================================================= */
    .gradio-container [role="tablist"] button.selected[class^="svelte-"]{
    display: flex;
    gap: 10px;
    align-items: center;

    padding: 10px 14px;

    background: var(--tab-bg-selected) !important;

    margin-bottom: 10px;
    }

    .gradio-container [role="tablist"] button[class^="svelte-"]{
    margin: 0 !important;
    border: 0 !important;

    height: 46px;
    min-height: 46px;
    padding: 0 22px;

    border-radius: 14px !important;

    background: transparent !important;
    color: var(--tab-text-muted) !important;

    font-weight: 700 !important;
    font-size: 0.95rem !important;

    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;

    position: relative !important;
    white-space: nowrap !important;

    transition:
        background-color .18s ease,
        color .18s ease,
        box-shadow .18s ease,
        transform .05s ease !important;
    }

    .gradio-container [role="tablist"] button[class^="svelte-"]:hover{
        background: color-mix(in srgb, var(--primary) 10%, transparent) !important;
        color: var(--tab-text) !important;
    }

    .gradio-container [role="tablist"] button[class^="svelte-"]:active{
    transform: translateY(1px);
    }

    .gradio-container [role="tablist"]
    .selected[class^="svelte-"],
    .gradio-container [role="tablist"]
    button.selected[class^="svelte-"]{
    color: var(--tab-text-selected) !important;
    background: var(--primary) !important;

    box-shadow:
        0 1px 2px rgba(0,0,0,.08),
        inset 0 1px 0 rgba(255,255,255,.35);
    }

    .gradio-container [role="tablist"]
    .selected[class^="svelte-"]::after,
    .gradio-container [role="tablist"]
    button.selected[class^="svelte-"]::after{
    content: "";
    position: absolute;
    left: 14px;
    right: 14px;
    bottom: 5px;

    height: 4px;
    border-radius: 999px;

    background: linear-gradient(
        to right,
        color-mix(in srgb, var(--primary) 85%, white 15%),
        var(--primary)
    );
    }

    .gradio-container [role="tablist"] button[class^="svelte-"]:focus-visible{
    outline: none !important;

    background: rgba(0,0,0,.06) !important;
    color: #111111 !important;

    box-shadow:
        0 0 0 3px rgba(0,0,0,.22),
        inset 0 1px 0 rgba(255,255,255,.45) !important;
    }
    """

    css_part_09_buttons_inputs = """
    /* =========================================================
    09) BOTÕES + INPUTS
    ========================================================= */
    button.gr-button{
    border-radius: var(--radius) !important;
    min-height: 42px !important;
    font-weight: 650 !important;
    letter-spacing: .1px;
    }

    #btn_back{
    background-color: #B10101;
    max-width: 140px;
    margin-left: auto;
    color: #ffffff !important;
    border-radius: 12px;
    box-shadow: var(--shadow-xs);
    }

    button.gr-button:hover{
    filter: brightness(1.02);
    box-shadow: var(--shadow-xs);
    }
    button.gr-button:focus{
    outline: none !important;
    box-shadow: var(--ring);
    }

    .btn_open_modulo{
    background: linear-gradient(339deg,rgba(17, 0, 199, 1) 12%, rgba(26, 18, 138, 1) 39%, rgba(4, 0, 51, 1) 87%, rgba(60, 38, 255, 1) 100%);
    max-width: 230px;
    }

    .btn_open_controle_sintetico{
    max-width: 230px;
    }

    input, textarea, select{
    border-radius: 12px !important;
    }

    .filter-compact label{
    font-size: .86rem !important;
    color: var(--muted) !important;
    }
    .filter-compact input,
    .filter-compact textarea,
    .filter-compact .wrap,
    .filter-compact .input-container{
    font-size: .93rem !important;
    }
    """

    css_part_10_txt_limitado = """
        /* =========================================================
        10) TXT LIMITADO (labels + textarea + dropdown)
        ========================================================= */

        .txt-limitado label,
        .txt-limitado label *{
            background: transparent !important;
            box-shadow: none !important;
        }

        .txt-limitado label{
            background: transparent !important;
            box-shadow: none !important;
            border: 0 !important;

            padding: 0 !important;
            margin-bottom: 6px !important;

            border-radius: 0 !important;
        }

        /* =====================================
        TEXTAREA + SELECT (DROPDOWN)
        ===================================== */
        .txt-limitado textarea,
        .txt-limitado select{
            /* tamanho travado */
            width: 120px !important;
            height: 32px !important;

            min-width: 120px !important;
            max-width: 120px !important;

            min-height: 32px !important;
            max-height: 32px !important;

            padding: 6px 12px !important;
            line-height: 1.2 !important;
            font-size: .92rem !important;
            font-family: inherit;

            background: rgba(255,255,255,.72) !important;
            border: 1px solid rgba(0,0,0,.14) !important;
            border-radius: 12px !important;

            box-shadow: 0 1px 0 rgba(255,255,255,.55) inset !important;
            outline: none !important;

            resize: none !important;
            overflow-y: auto;

            transition: border-color .18s ease,
                        box-shadow .18s ease,
                        background .18s ease;
        }

        /* =====================================
        DROPDOWN CUSTOM (Gradio moderno)
        ===================================== */
        .txt-limitado [role="combobox"],
        .txt-limitado button{
            width: 120px !important;
            height: 32px !important;

            padding: 6px 12px !important;
            border-radius: 12px !important;
        }

        /* =====================================
        FOCUS (textarea + dropdown)
        ===================================== */
        .txt-limitado textarea:focus,
        .txt-limitado select:focus,
        .txt-limitado [role="combobox"]:focus,
        .txt-limitado button:focus{
            background: rgba(255,255,255,.88) !important;
            border-color: rgba(37,99,235,.55) !important;
            box-shadow:
                0 0 0 3px rgba(37,99,235,.12),
                0 1px 0 rgba(255,255,255,.55) inset !important;
        }

        /* =====================================
        SCROLLBAR (textarea)
        ===================================== */
        .txt-limitado textarea::-webkit-scrollbar{
            width: 8px;
        }
        .txt-limitado textarea::-webkit-scrollbar-thumb{
            background: rgba(0,0,0,.22);
            border-radius: 999px;
        }
        .txt-limitado textarea::-webkit-scrollbar-track{
            background: rgba(0,0,0,.06);
        }
    """

    css_part_11_accordion = """
    /* =========================================================
    11) ACCORDION
    ========================================================= */
    details{ border-radius: var(--radius) !important; }
    details summary{ font-weight: 700 !important; }
    """

    css_part_12_table = """
    /* =========================================================
    12) TABELA SINTÉTICA – LAYOUT BASE
    ========================================================= */
    #tbl_sintetico {
    border-radius: var(--radius);
    border: 1px solid var(--tbl-border);
    background: var(--tbl-bg);
    box-shadow: var(--shadow-xs);
    overflow: hidden;
    }

    #tbl_sintetico,
    #tbl_sintetico > div,
    #tbl_sintetico .table-wrap,
    #tbl_sintetico .wrap,
    #tbl_sintetico .grid-wrap {
    width: 100% !important;
    max-width: 100% !important;
    }

    #tbl_sintetico table { width: 100% !important; }

    #tbl_sintetico thead { box-shadow: 0 2px 6px rgba(0,0,0,.15); }

    #tbl_sintetico thead th {
    position: sticky;
    top: 0;
    z-index: 3;

    background: var(--tbl-head-bg);
    color: var(--tbl-head-text);

    font-weight: 800;
    font-size: 12.8px;
    letter-spacing: .35px;

    border-bottom: 1px solid var(--tbl-head-border);
    padding: 10px 12px !important;
    white-space: nowrap;
    }

    #tbl_sintetico tbody td {
    padding: 10px 12px !important;
    font-size: 13px;
    color: var(--tbl-text);

    border-bottom: 1px solid var(--tbl-border);
    vertical-align: middle;
    white-space: nowrap;
    line-height: 1.25;
    }

    #tbl_sintetico tbody tr:nth-child(even) td { background: var(--tbl-row-even); }
    #tbl_sintetico tbody tr:hover td { background: var(--tbl-row-hover); }

    #tbl_sintetico tbody tr.selected td,
    #tbl_sintetico tbody tr.cellselected td {
    background: var(--tbl-row-selected) !important;
    box-shadow: inset 4px 0 0 var(--tbl-row-selected-accent);
    }

    #tbl_sintetico tbody td:nth-child(10),
    #tbl_sintetico tbody td:nth-child(11) {
    text-align: right !important;
    font-variant-numeric: tabular-nums;
    }

    #tbl_sintetico thead th:nth-child(5),
    #tbl_sintetico tbody td:nth-child(5) {
    min-width: 210px !important;
    width: 230px !important;
    max-width: 280px !important;
    font-variant-numeric: tabular-nums;
    }

    #tbl_sintetico *::-webkit-scrollbar { height: 10px; width: 10px; }
    #tbl_sintetico *::-webkit-scrollbar-thumb {
    background: var(--tbl-scrollbar-thumb);
    border-radius: 999px;
    }
    #tbl_sintetico *::-webkit-scrollbar-track { background: var(--tbl-scrollbar-track); }

    #tbl_sintetico:focus-within thead th { filter: brightness(1.15); }
    """

    css_part_13_header_card2 = """
    /* =========================================================
    13) DADOS EXIBIÇÃO (app-title-text-card2)
    ========================================================= */
    .app-title-text-card2{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px 10px;

    padding: 8px 16px;
    border-radius: 999px;

    font-family: var(--font-family, system-ui);
    font-size: .9rem;
    font-weight: 600;

    color: var(--text, #1f2937);
    background: linear-gradient(
        135deg,
        #d7d2e8 0%,
        #ebe7f4 50%,
        #f6f4fb 100%
    );

    border: 1px solid rgba(0,0,0,.08);
    box-shadow:
        0 1px 3px rgba(0,0,0,.08),
        inset 0 1px 0 rgba(255,255,255,.6);
    }

    .app-title-text-card2 .item strong{
    font-weight: 700;
    color: var(--color-text-h2-invert);
    margin-right: 4px;
    }

    .app-title-text-card2 .item{
    white-space: nowrap;
    max-width: 260px;
    overflow: hidden;
    text-overflow: ellipsis;
    }

    .app-title-text-card2 .sep{
    opacity: .45;
    font-size: .85rem;
    }

    .app-title-text-card2 .item.id{
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    background: rgba(0,0,0,.05);
    padding: 2px 8px;
    border-radius: 999px;
    }
    """

    css_part_14_dropdown = """
    /* =========================================================
    14) DROPDOWN (Gradio / Choices.js)
    ========================================================= */
    .gradio-container .choices,
    .gradio-container .choices__inner,
    .gradio-container .choices__list { overflow: visible !important; }

    .gradio-container .choices__list--dropdown{
    transform: none !important;
    margin-top: 0 !important;
    }

    /* quando portalado, o dropdown está no body */
    body > .choices__list--dropdown{
    position: fixed !important;
    z-index: 999999 !important;
    }

    /* evita estilos antigos do Choices interferirem */
    .gradio-container .choices__list--dropdown{
    margin-top: 0 !important;
    transform: none !important;
    }
    """

    # =========================================================
    # CSS FINAL (concat) — copie/cole para validar
    # =========================================================
    css_code = ''.join(
        (
            css_part_01_tokens,
            css_part_02_dark,
            css_part_03_base,
            css_part_04_container,
            css_part_05_topbar,
            css_part_06_cards,
            css_part_07_texts_alerts,
            css_part_08_tabs,
            css_part_09_buttons_inputs,
            css_part_10_txt_limitado,
            css_part_11_accordion,
            css_part_12_table,
            css_part_13_header_card2,
            css_part_14_dropdown,
        )
    )


    theme = gr.themes.Soft(radius_size="lg", text_size="md")

    meses, statuses, motivos, originadores, datas_venc, datas_sla, datas_corte = get_filter_options()
    titulo_sistema = "COFC - Controle Operacional - FCT Consignado"

    with gr.Blocks(
        title=titulo_sistema, 
        theme=theme,
        css=css_code,
        js=js_code
    ) as demo:

        current_page = gr.State(PAGE_MODULOS)
        selected_numero_convenio = gr.State()
        selected_mes_ref = gr.State()
        last_click_time = gr.State(0.0)
        abrir_flag = gr.State(False)
        #auto_timer = gr.Timer(5)  # 5 segundos

        # -------------------------
        # Topbar
        # -------------------------
        with gr.Row(elem_classes=["app-topbar"]):
            with gr.Column(scale=8, elem_classes=["app-title"]):
                gr.Markdown(f"### {titulo_sistema}\n<small>• Navegação por páginas</small>", elem_classes=["app-title-text"])
                breadcrumb = gr.HTML(f"<span class='breadcrumb-pill'>{_breadcrumb(PAGE_MODULOS)}</span>")
            with gr.Column(scale=2):
                btn_back = gr.Button(
                    "Voltar", 
                    visible=False, 
                    elem_id="btn_back",
                    min_width=140,
                    scale=2
                )

        # =========================
        # Página: Módulos
        # =========================
        with gr.Column(visible=True) as page_modulos:
            with gr.Column(elem_classes=["card-modululos", "card"]):
                gr.Markdown("### Módulos", elem_classes=["app-module-title"])
                gr.Markdown(
                    "<div class='muted'>Selecione um módulo para continuar.</div>",
                    elem_classes=["muted"]
                )
                with gr.Column(elem_classes=["card", "card-modululos-container"]):
                    btn_open_conciliacao = gr.Button(
                        "Conciliação", 
                        variant="primary", 
                        elem_classes="btn_open_modulo"
                    )

        # =========================
        # Página: Conciliação
        # =========================
        with gr.Column(visible=False) as page_conciliacao:
            with gr.Column(elem_classes=["card-submodululos", "card"]):
                gr.Markdown("### Submodulos de Conciliação")
                gr.Markdown("<div class='muted'>Acesse as funcionalidades do módulo.</div>")
                with gr.Column(elem_classes=["card", "card-submodululos-container"]):
                    with gr.Row():
                        btn_open_sintetico = gr.Button("Controle Sintético - Convênios", variant="primary", elem_classes="btn_open_modulo")
                        gr.Button("Dashboard (futuro)", interactive=False, elem_classes="btn_open_modulo")

        # =========================
        # Página: Controle Sintético
        # =========================
        # Schema técnico (para lógica) - inclui id
        SINT_COLS_TECH = [
            "id",
            "mes",
            "originador",
            "numero_convenio",
            "nome_convenio",
            "status_conciliacao",
            "vencimento_convenio",
            #"data_env_remessa",
            "data_sla",
            "data_corte",
            "qtd_dias_inadimplencia",
            "porcentagem_inadimplencia",
        ]

        SINT_COLS_VIEW = [
            "mes",
            "originador",
            "numero_convenio",
            "nome_convenio",
            "status_conciliacao",
            "vencimento_convenio",
            #"data_env_remessa",
            "data_sla",
            "data_corte",
            "qtd_dias_inadimplencia",
            "porcentagem_inadimplencia",
        ]

        SINT_LABELS_VIEW = {
            "mes": "Mês Ref.",
            "originador": "Originador",
            "numero_convenio": "N° Convênio",
            "nome_convenio": "Nome convênio",
            "status_conciliacao": "Status Conciliação",
            "vencimento_convenio": "VCTO convênio",
            #"data_env_remessa": "DT env. remessa",
            "data_sla": "SLA Conciliação",
            "data_corte": "Data corte",
            "qtd_dias_inadimplencia": "Inadimp",
            "porcentagem_inadimplencia": "% Inadimp",
        }

        SINT_DTYPES = [
            "number",  # id
            "str",     # mes
            "str",     # originador
            "str",     # numero_convenio
            "str",     # nome_convenio
            "str",     # cnpj_convenio
            "str",     # vencimento_convenio
            #"str",     # data_env_remessa
            "str",     # data_sla
            "str",     # data_corte
            "str",     # qtd_dias_inadimplencia
            "str",     # porcentagem_inadimplencia
        ]

        with gr.Column(visible=False) as page_sintetico:
            with gr.Column(elem_classes=["card-controle_sintetico", "card"]):
                gr.Markdown("### Controle Sintético")
                gr.Markdown("<div class='muted'>Filtre, selecione um convênio e abra o detalhamento.</div>")

                with gr.Row():
                    with gr.Column(scale=10, min_width=400):
                        with gr.Accordion("Filtros", open=True):
                            with gr.Row():
                                MES_ATUAL = datetime.now().strftime("%m/%Y")
                                f_mes = gr.Textbox(elem_classes=["txt-limitado"], value=MES_ATUAL, label="Mês (referência)")
                                f_status = gr.Dropdown(elem_classes=["txt-limitado"], choices=statuses, value="Todos", label="Status")
                                f_motivo = gr.Dropdown(elem_classes=["txt-limitado"], choices=motivos, value="Todos", label="Motivo")
                                f_originador = gr.Dropdown(elem_classes=["txt-limitado"], choices=originadores, value="Todos", label="Originador")
                                f_data_vencimento = gr.Textbox(elem_classes=["txt-limitado"], value="", label="Data vencimento")
                                f_data_baixa = gr.Textbox(elem_classes=["txt-limitado"], value="", label="Data SLA")
                                f_data_corte = gr.Textbox(elem_classes=["txt-limitado"], value="", label="Data corte")
                            busca = gr.Textbox(elem_classes='txtobs', label="Busca", placeholder="Nome, CNPJ, número do convênio, motivo...")

                    with gr.Column(scale=1, min_width=100):
                        btn_filtrar = gr.Button("Pesquisar", variant="primary", elem_classes="btn_open_controle_sintetico")
                        btn_ir_analitico = gr.Button("Abrir", variant="secondary", elem_classes="btn_open_controle_sintetico")
                        btn_limpar = gr.Button("Limpar", elem_classes="btn_open_controle_sintetico")

                resumo = gr.HTML("<div class='alert-invert'>0 registro(s) encontrado(s)</div>")

            tabela_tech = gr.State(pd.DataFrame(columns=SINT_COLS_TECH))

            with gr.Column(elem_classes=["card-controle_sintetico", "card"]):
                tabela = gr.Dataframe(
                    value=pd.DataFrame(columns=[SINT_LABELS_VIEW[c] for c in SINT_COLS_VIEW]),
                    headers=[SINT_LABELS_VIEW[c] for c in SINT_COLS_VIEW],
                    datatype=["str"] * len(SINT_COLS_VIEW),
                    interactive=False,
                    wrap=True,
                    row_count=12,
                    column_count=(len(SINT_COLS_VIEW), "fixed"),
                    label="",
                    elem_id="tbl_sintetico"
                )

                gr.Markdown(
                    "<div class='tbl-hint'>💡 Selecione uma linha e clique em <b>Abrir</b> (ou duplo clique).</div>"
                )



        ################################
                    #CAMPOS#
        ################################


        with gr.Column(visible=False) as page_analitico:
            with gr.Column(elem_classes=["card-controle_analitico", "card"]):
                gr.Markdown("### Controle Analítico")
                analitico_header = gr.HTML("<div class='alert'>Selecione um convênio no Sintético para ver o detalhe.</div>")

                dados_inputs = {}     # key -> componente
                dados_state = gr.State({})  # guarda o dict “bruto” atual do convênio
                active_tab = gr.State("Dados")
                with gr.Tabs() as tabs:
                    with gr.Tab("Dados", elem_classes=['aba_style']):
                        with gr.Column(elem_classes=["card-controle_analitico_abas", "card"]):
                            gr.HTML("<div class='aba_text_fora_campo'>Dados do Convênio (edição controlada por campo)</div>")

                            with gr.Row():
                                col_left = gr.Column(scale=1)
                                col_right = gr.Column(scale=1)

                            dados_inputs = {}

                            for i, f in enumerate(DADOS_FIELDS):
                                key = f["key"]
                                label = f["label"]
                                editable = f.get("editable", True)
                                field_type = f.get("type", "text")
                                options = f.get("options")

                                parent = col_left if i % 2 == 0 else col_right
                                with parent:

                                    # SELECT / DROPDOWN
                                    if field_type == "select" and options:
                                        # ✅ sempre inclui opção vazia
                                        choices = [""] + list(options)

                                        dados_inputs[key] = gr.Dropdown(
                                            label=label,
                                            choices=choices,
                                            value="",  # ✅ começa vazio
                                            interactive=bool(editable),
                                            multiselect=False,
                                        )
                                    else:
                                        dados_inputs[key] = gr.Textbox(
                                            label=label,
                                            value="",
                                            interactive=bool(editable),
                                            placeholder="" if editable else "Somente leitura",
                                        )

                            DADOS_KEYS = [f["key"] for f in DADOS_FIELDS]
                            DADOS_OUTPUTS = [dados_inputs[k] for k in DADOS_KEYS]

                            # =========================
                            # % inadimplência (dinâmico ao digitar)
                            # =========================
                            if "valor_repasse" in dados_inputs and "valor_retorno" in dados_inputs and "porcentagem_inadimplencia" in dados_inputs:
                                dados_inputs["valor_repasse"].input(
                                    fn=on_valores_change,
                                    inputs=[dados_inputs["valor_repasse"], dados_inputs["valor_retorno"]],
                                    outputs=dados_inputs["porcentagem_inadimplencia"],
                                )

                                dados_inputs["valor_retorno"].input(
                                    fn=on_valores_change,
                                    inputs=[dados_inputs["valor_repasse"], dados_inputs["valor_retorno"]],
                                    outputs=dados_inputs["porcentagem_inadimplencia"],
                                )

                            # =========================
                            # Valor pendente (dinâmico ao digitar)
                            # =========================
                            if "valor_retorno" in dados_inputs and "valor_repasse" in dados_inputs and "valor_pendente" in dados_inputs:
                                dados_inputs["valor_retorno"].input(
                                    fn=on_pendente_change,
                                    inputs=[dados_inputs["valor_retorno"], dados_inputs["valor_repasse"]],
                                    outputs=dados_inputs["valor_pendente"],
                                )

                                dados_inputs["valor_repasse"].input(
                                    fn=on_pendente_change,
                                    inputs=[dados_inputs["valor_retorno"], dados_inputs["valor_repasse"]],
                                    outputs=dados_inputs["valor_pendente"],
                                )

                                def on_status_conc_change(status):
                                    st = (status or "").strip().upper()
                                    show = st == "CONCILIADO (PARCIAL)"

                                    if show:
                                        return gr.update(visible=True, interactive=True)

                                    # ✅ esconde e zera
                                    return gr.update(value="", visible=False, interactive=False)

                            # se existir os campos
                            if "status_conciliacao" in dados_inputs and "motivo_falta_conciliacao" in dados_inputs:
                                # garante que o motivo fique visível/oculto conforme status
                                dados_inputs["status_conciliacao"].change(
                                    fn=on_status_conc_change,
                                    inputs=[dados_inputs["status_conciliacao"]],
                                    outputs=[dados_inputs["motivo_falta_conciliacao"]],
                                )

                        with gr.Row():
                            btn_salvar_dados = gr.Button("Salvar dados", variant="primary")
                            btn_recarregar_dados = gr.Button("Recarregar", variant="secondary")

                        msg_dados = gr.HTML("")

                    with gr.Tab("Contato"):
                        with gr.Column(elem_classes=["card-controle_analitico_abas", "card"]):
                            gr.HTML("<div class='aba_text_fora_campo'>Contatos do Convênio</div>")
                            contatos_df = gr.Dataframe(
                                value=ensure_df([], CONTATO_COLS),
                                headers=CONTATO_COLS,
                                datatype=["number", "str", "str", "str", "str", "str", "str", "str", "str"],
                                interactive=False,
                                wrap=True,
                                row_count=8,
                                column_count=(len(CONTATO_COLS), "fixed"),
                                label=""
                            )

                        with gr.Column(elem_classes=["card"]):
                            gr.HTML("<div class='aba_text_fora_campo'>Formulário de contato (criar/editar)</div>")
                            contato_id = gr.State(None)

                            with gr.Row():
                                area = gr.Textbox(label="Área", placeholder="Ex.: Operações / Financeiro / TI")
                                cstatus = gr.Dropdown(label="Status", choices=["ATIVO", "INATIVO"], value="ATIVO")
                            with gr.Row():
                                nome = gr.Textbox(label="Nome*", placeholder="Obrigatório")
                                email = gr.Textbox(label="E-mail")
                            with gr.Row():
                                telefone = gr.Textbox(label="Telefone")
                                observacao = gr.Textbox(label="Observação")

                            with gr.Row():
                                btn_salvar_contato = gr.Button("Salvar contato", variant="primary")
                                btn_novo_contato = gr.Button("Novo / Limpar", variant="secondary")

                            msg_contato = gr.HTML("")

                    with gr.Tab("Particularidade"):
                        with gr.Column(elem_classes=["card-controle_analitico_abas", "card"]):
                            gr.HTML("<div class='aba_text_fora_campo'>Particularidades do Convênio</div>")
                            particularidades_df = gr.Dataframe(
                                value=ensure_df([], PART_COLS),
                                headers=PART_COLS,
                                datatype=["number", "str", "str", "str", "str", "str", "str", "str", "str"],
                                interactive=False,
                                wrap=True,
                                row_count=8,
                                column_count=(len(PART_COLS), "fixed"),
                                label=""
                            )
                                                
                        with gr.Column(elem_classes=["card"]):
                            gr.HTML("<div class='aba_text_fora_campo'>Formulário de particularidade (criar/editar)</div>")
                            part_id = gr.State(None)

                            with gr.Row():
                                rubrica_produto = gr.Textbox(label="Rubrica / Produto")
                                modelo_de_averbacao = gr.Dropdown(
                                    label="Modelo de averbação",
                                    choices=["Parcelado", "Arquivo remessa"],
                                    value="Arquivo remessa",
                                    interactive=True
                                )

                            with gr.Row():
                                status_particularidade = gr.Dropdown(
                                    label="Status da Particularidade",
                                    choices=["ATIVO", "INATIVO"],
                                    value="ATIVO",
                                    interactive=True
                                )
                                part_observacao = gr.Textbox(label="Observação")

                            # Retenção (controla os campos abaixo)
                            with gr.Row():
                                retencao = gr.Dropdown(label="Retenção", choices=["SIM", "NÃO"], value="NÃO")
                                part_telefone = gr.Textbox(label="Telefone")

                            # Campos condicionais (Retenção = Sim)
                            with gr.Row():
                                retencao_valor = gr.Textbox(label="Valor", visible=False)          # pode aplicar br_money depois
                                retencao_percent = gr.Textbox(label="Porcentagem", visible=False)  # pode aplicar br_percent depois

                            with gr.Row():
                                btn_salvar_part = gr.Button("Salvar particularidade", variant="primary")
                                btn_novo_part = gr.Button("Novo / Limpar", variant="secondary")

                            msg_part = gr.HTML("")

                    with gr.Tab("Conta"):
                        with gr.Column(elem_classes=["card-controle_analitico_abas", "card"]):
                            gr.Markdown("#### Contas do Convênio")
                            contas_df = gr.Dataframe(
                                value=ensure_df([], CONTA_COLS),
                                headers=CONTA_COLS,
                                datatype=["number", "str", "str", "str", "str", "str", "str", "str", "str"],
                                interactive=False,
                                wrap=True,
                                row_count=8,
                                column_count=(len(CONTA_COLS), "fixed"),
                                label="Lista de contas"
                            )

                        with gr.Column(elem_classes=["card"]):
                            gr.HTML("<div class='aba_text_fora_campo'>Formulário de conta (criar/editar)</div>")
                            conta_id = gr.State(value=None)

                            with gr.Row():
                                conta_banco = gr.Textbox(label="Banco")
                                conta_agencia = gr.Textbox(label="Agência")
                            with gr.Row():
                                conta_numero = gr.Textbox(label="Conta")
                                conta_pix = gr.Textbox(label="Chave Pix")
                            with gr.Row():
                                conta_cnpj = gr.Textbox(label="CNPJ")
                                conta_status = gr.Dropdown(
                                    label="Status da conta",
                                    choices=["ATIVA", "INATIVA", "EM VALIDAÇÃO"],
                                    value="ATIVA"
                                )

                            with gr.Row():
                                btn_salvar_conta = gr.Button("Salvar conta", variant="primary")
                                btn_novo_conta = gr.Button("Novo / Limpar", variant="secondary")

                            msg_conta = gr.HTML("")
                def on_tab_select(evt: gr.SelectData):
                    # evt.value normalmente é o label da aba selecionada
                    return (evt.value or "").strip()
                
                tabs.select(
                    fn=on_tab_select,
                    inputs=None,
                    outputs=active_tab
                ).then(
                    fn=auto_refresh_por_aba,
                    inputs=[selected_numero_convenio, selected_mes_ref, current_page, active_tab],
                    outputs=[msg_dados, analitico_header, dados_state, *DADOS_OUTPUTS, contatos_df, particularidades_df, contas_df]
                )
        # -------------------------
        # Helpers navegação HTML
        # -------------------------
        def nav_to_html(page, numero_convenio=None, mes_ref=None):
            page_state, _, back_upd, mod_upd, con_upd, sin_upd, ana_upd = nav_to(page, numero_convenio, mes_ref)
            bread_val = f"<span class='breadcrumb-pill'>{_breadcrumb(page, {'numero_convenio': numero_convenio, 'mes_referencia_conciliacao': mes_ref})}</span>"
            return (page_state, gr.update(value=bread_val), back_upd, mod_upd, con_upd, sin_upd, ana_upd)

        def nav_back_html(current_page):
            page_state, _, back_upd, mod_upd, con_upd, sin_upd, ana_upd = nav_back(current_page)
            bread_val = f"<span class='breadcrumb-pill'>{_breadcrumb(page_state, None)}</span>"
            return (page_state, gr.update(value=bread_val), back_upd, mod_upd, con_upd, sin_upd, ana_upd)

        # -------------------------
        # Sintético: handlers
        # -------------------------
        def do_filtrar(mes, status, motivo, originador, data_vencimento, data_sla, data_corte, busca):
            data, info = listar_convenios(mes, status, motivo, originador, data_vencimento, data_sla, data_corte, busca)
            df = pd.DataFrame(data)

            for col in SINT_COLS_TECH:
                if col not in df.columns:
                    df[col] = ""

            df_tech = df[SINT_COLS_TECH].copy()
            df_view = df_tech[SINT_COLS_VIEW].rename(columns=SINT_LABELS_VIEW)

            return f"<div class='alert-invert'>{info}</div>", df_view, df_tech

        def do_limpar():
            return "", "Todos", "Todos", "Todos", "", "", "", ""

        def on_row_click_simulated(df_tech, evt: gr.SelectData, last_time):
            now = time.time()
            row_idx = evt.index[0]

            numero_convenio = ""
            mes_ref = ""

            try:
                if hasattr(df_tech, "iloc"):
                    r = df_tech.iloc[row_idx]
                    # ajuste aqui conforme o nome REAL da coluna no df_tech
                    numero_convenio = str(r.get("numero_convenio", "")).strip()
                    mes_ref = str(r.get("mes", "")).strip()  # ou "mes_referencia_conciliacao"
                else:
                    r = df_tech[row_idx]
                    numero_convenio = str(r.get("numero_convenio", "")).strip()
                    mes_ref = str(r.get("mes", "")).strip()
            except Exception:
                pass

            # duplo clique
            abrir = (now - float(last_time or 0.0)) < 0.4

            return numero_convenio, mes_ref, now, abrir
                


        # =========================
        # Lógica Retenção: Sim/Não
        # =========================
        def on_retencao_change(v):
            is_sim = (v == "SIM")
            if is_sim:
                return (
                    gr.update(visible=True),
                    gr.update(visible=True),
                )
            # Se "Não": esconde e limpa
            return (
                gr.update(value="", visible=False),
                gr.update(value="", visible=False),
            )
                
        def formatar_telefone_br(v):
            if not v:
                return ""

            numeros = re.sub(r"\D", "", str(v))

            if len(numeros) == 11:
                return f"({numeros[:2]}) {numeros[2:7]}-{numeros[7:]}"
            elif len(numeros) == 10:
                return f"({numeros[:2]}) {numeros[2:6]}-{numeros[6:]}"
            else:
                return numeros
                    

        def formatar_valor_blur(v):
            num = parse_br_number(v)
            if num is None:
                return ""
            return br_money(num)

        def formatar_percent_blur(v):
            num = parse_br_number(v)
            if num is None:
                return ""
            # aqui espera decimal (ex: 15 vira 15%)
            return f"{num:.2f}%".replace(".", ",")


        def abrir_analitico(numero_convenio, mes_ref):
            numero_convenio = (numero_convenio or "").strip()
            mes_ref = (mes_ref or "").strip()

            clear_updates = [gr.update(value="") for _ in DADOS_FIELDS]

            if not numero_convenio or not mes_ref:
                return (
                    *nav_to_html(PAGE_ANALITICO, numero_convenio, mes_ref),
                    "", "",
                    "Dados",
                    "<div class='alert'>Selecione um convênio no Sintético antes de abrir o Analítico.</div>",
                    {},
                    *clear_updates,
                    ensure_df([], CONTATO_COLS),
                    ensure_df([], PART_COLS),
                    ensure_df([], CONTA_COLS),
                )

            dados, contatos, parts, contas, msg, *resto = carregar_convenio_por_chave(numero_convenio, mes_ref)
            dados = montar_dados_analitico(dados)
            updates = preencher_dados_updates(dados)
            header = _build_header(dados, f"{numero_convenio}/{mes_ref}")

            return (
                *nav_to_html(PAGE_ANALITICO, numero_convenio, mes_ref),
                numero_convenio, mes_ref,
                "Dados",
                header,
                dados,
                *updates,
                ensure_df(contatos, CONTATO_COLS),
                ensure_df(parts, PART_COLS),
                ensure_df(contas, CONTA_COLS),
            )
        
        def abrir_por_duplo_clique(flag, numero_convenio, mes_ref, current_page):
            if not flag:
                noop_dados = [gr.update() for _ in DADOS_FIELDS]
                return (
                    current_page,
                    gr.update(), gr.update(),
                    gr.update(), gr.update(), gr.update(), gr.update(),
                    gr.update(),
                    gr.update(), gr.update(),
                    *noop_dados,
                    gr.update(), gr.update(), gr.update(),
                )

            ret = abrir_analitico(numero_convenio, mes_ref)

            nav = ret[:7]
            active_tab_value = ret[9]
            header = ret[10]
            dados = ret[11]
            inputs = ret[12:12+len(DADOS_FIELDS)]
            dfs = ret[12+len(DADOS_FIELDS):]

            return (*nav, active_tab_value, header, dados, *inputs, *dfs)

        # -------------------------
        # Wiring navegação
        # -------------------------
        btn_open_conciliacao.click(
            fn=lambda: nav_to_html(PAGE_CONCILIACAO),
            inputs=[],
            outputs=[current_page, breadcrumb, btn_back, page_modulos, page_conciliacao, page_sintetico, page_analitico]
        )

        btn_open_sintetico.click(
            fn=lambda: nav_to_html(PAGE_SINTETICO),
            inputs=[],
            outputs=[current_page, breadcrumb, btn_back, page_modulos, page_conciliacao, page_sintetico, page_analitico]
        )

        btn_back.click(
            fn=nav_back_html,
            inputs=[current_page],
            outputs=[current_page, breadcrumb, btn_back, page_modulos, page_conciliacao, page_sintetico, page_analitico]
        )

        btn_filtrar.click(
            fn=do_filtrar,
            inputs=[f_mes, f_status, f_motivo, f_originador, f_data_vencimento, f_data_baixa, f_data_corte, busca],
            outputs=[resumo, tabela, tabela_tech]
        )

        btn_limpar.click(
            fn=do_limpar,
            inputs=[],
            outputs=[f_mes, f_status, f_motivo, f_originador, f_data_vencimento, f_data_baixa, f_data_corte, busca]
        ).then(
            fn=do_filtrar,
            inputs=[f_mes, f_status, f_motivo, f_originador, f_data_vencimento, f_data_baixa, f_data_corte, busca],
            outputs=[resumo, tabela, tabela_tech]
        )

        tabela.select(
            fn=on_row_click_simulated,
            inputs=[tabela_tech, last_click_time],
            outputs=[
                selected_numero_convenio,
                selected_mes_ref,
                last_click_time,
                abrir_flag
            ]
        )


        btn_ir_analitico.click(
            fn=abrir_analitico,
            inputs=[selected_numero_convenio, selected_mes_ref],
            outputs=[
                current_page, breadcrumb, btn_back,
                page_modulos, page_conciliacao, page_sintetico, page_analitico,

                selected_numero_convenio,
                selected_mes_ref,
                active_tab,

                analitico_header,
                dados_state,
                *DADOS_OUTPUTS,
                contatos_df, particularidades_df, contas_df
            ]
        )


        abrir_flag.change(
            fn=abrir_por_duplo_clique,
            inputs=[abrir_flag, selected_numero_convenio, selected_mes_ref, current_page],
            outputs=[
                current_page, breadcrumb, btn_back,
                page_modulos, page_conciliacao, page_sintetico, page_analitico,
                active_tab,
                analitico_header,
                dados_state,
                *DADOS_OUTPUTS,
                contatos_df, particularidades_df, contas_df
            ]
        )

        # -------------------------
        # Load inicial
        # -------------------------
        demo.load(
            fn=lambda: do_filtrar(
                MES_ATUAL,   # <-- mês atual automático
                "Todos",
                "Todos",
                "Todos",
                "",
                "",
                "",
                ""
            ),
            inputs=[],
            outputs=[resumo, tabela, tabela_tech]
        )
        # =========================
        # SALVAR / RECARREGAR - ABA DADOS
        # =========================
        dados_outputs = DADOS_OUTPUTS
        dados_inputs_list = DADOS_OUTPUTS

        btn_salvar_dados.click(
            fn=salvar_dados_gr,
            inputs=[selected_numero_convenio, selected_mes_ref, *dados_inputs_list],
            outputs=[msg_dados, analitico_header, dados_state, *dados_outputs],
        )

        btn_recarregar_dados.click(
            fn=recarregar_dados_gr,
            inputs=[selected_numero_convenio, selected_mes_ref],
            outputs=[
                msg_dados,
                analitico_header,
                dados_state,
                *dados_outputs,
                contatos_df,
                particularidades_df,
                contas_df,
            ],
        )

        # auto_timer.tick(
        #     fn=auto_refresh_por_aba,
        #     inputs=[selected_numero_convenio, selected_mes_ref, current_page, active_tab],
        #     outputs=[msg_dados, analitico_header, dados_state, *dados_outputs, contatos_df, particularidades_df, contas_df]
        # )


        # =========================
        # CRUD / Select - Contato
        # =========================
        contatos_df.select(
            fn=on_select_contato,
            inputs=[contatos_df],
            outputs=[contato_id, area, cstatus, nome, email, telefone, observacao]
        )

        btn_novo_contato.click(
            fn=limpar_form_contato,
            inputs=[],
            outputs=[contato_id, area, cstatus, nome, email, telefone, observacao]
        )

        def salvar_contato_e_recarregar(numero_convenio, mes_ref, contato_id, area, status, nome, email, telefone, observacao):
            msg, rows = salvar_contato(numero_convenio, mes_ref, contato_id, area, status, nome, email, telefone, observacao)
            df = ensure_df(rows, CONTATO_COLS)
            return f"<div class='alert'>{msg}</div>", df, None, "", "ATIVO", "", "", "", ""

        btn_salvar_contato.click(
            fn=salvar_contato_e_recarregar,
            inputs=[selected_numero_convenio, selected_mes_ref, contato_id, area, cstatus, nome, email, telefone, observacao],
            outputs=[msg_contato, contatos_df, contato_id, area, cstatus, nome, email, telefone, observacao]
        )

        # =========================
        # CRUD / Select - Particularidade
        # =========================
        particularidades_df.select(
            fn=on_select_part,
            inputs=[particularidades_df],
            outputs=[
                part_id,
                rubrica_produto,
                modelo_de_averbacao,
                retencao,
                part_telefone,
                part_observacao,
                status_particularidade,
                retencao_valor,
                retencao_percent,
            ]
        )

        btn_novo_part.click(
            fn=limpar_form_part,
            inputs=[],
            outputs=[
                part_id,
                rubrica_produto,
                modelo_de_averbacao,
                retencao,
                part_telefone,
                part_observacao,
                status_particularidade,
                retencao_valor,
                retencao_percent,
            ]
        )


        retencao.change(
            fn=on_retencao_change,
            inputs=[retencao],
            outputs=[retencao_valor, retencao_percent],
        )

        retencao_valor.blur(
            fn=formatar_valor_blur,
            inputs=retencao_valor,
            outputs=retencao_valor
        )

        retencao_percent.blur(
            fn=formatar_percent_blur,
            inputs=retencao_percent,
            outputs=retencao_percent
        )

        part_telefone.blur(
            fn=formatar_telefone_br,
            inputs=part_telefone,
            outputs=part_telefone
        )

        def salvar_part_e_recarregar(
            numero_convenio,
            mes_ref,
            part_id,
            rub,
            mod,
            ret,
            tel,
            obs,
            status_particularidade,
            retencao_valor,
            retencao_percent,
        ):
            msg, rows = salvar_particularidade(
                numero_convenio,
                mes_ref,
                part_id,
                rub,
                mod,
                ret,
                tel,
                obs,
                status_particularidade,
                retencao_valor,
                retencao_percent,
            )

            df = ensure_df(rows, PART_COLS)

            # formata no retorno do salvar (mesmo sem blur)
            v_num = parse_br_number(retencao_valor)
            p_num = parse_br_number(retencao_percent)

            v_fmt = "" if v_num is None else br_money(v_num)
            p_fmt = "" if p_num is None else br_percent(p_num / 100.0) if p_num > 1 else br_percent(p_num)

            # se Retenção != SIM, limpa campos condicionais
            if (ret or "").strip().upper() != "SIM":
                v_fmt = ""
                p_fmt = ""

            return (
                f"<div class='alert'>{msg}</div>",
                df,
                None,          # part_id
                "",            # rubrica
                "Arquivo remessa",  # modelo averbação (volta pro default)
                "NÃO",         # retencao (default)
                "",            # telefone
                "",            # observacao
                "ATIVO",       #f status_particularidade (default)
                v_fmt,         # retencao_valor
                p_fmt,         # retencao_percent
            )
        
        btn_salvar_part.click(
            fn=salvar_part_e_recarregar,
            inputs=[
                selected_numero_convenio,
                selected_mes_ref,
                part_id,
                rubrica_produto,
                modelo_de_averbacao,
                retencao,
                part_telefone,
                part_observacao,
                status_particularidade,
                retencao_valor,
                retencao_percent,
            ],
            outputs=[
                msg_part,
                particularidades_df,
                part_id,
                rubrica_produto,
                modelo_de_averbacao,
                retencao,
                part_telefone,
                part_observacao,
                status_particularidade,
                retencao_valor,
                retencao_percent,
            ]
        )


        # =========================
        # CRUD / Select - Conta
        # =========================
        contas_df.select(
            fn=on_select_conta,
            inputs=[contas_df],
            outputs=[conta_id, conta_banco, conta_agencia, conta_numero, conta_pix, conta_cnpj, conta_status]
        )

        btn_novo_conta.click(
            fn=limpar_form_conta,
            inputs=[],
            outputs=[conta_id, conta_banco, conta_agencia, conta_numero, conta_pix, conta_cnpj, conta_status]
        )

        def salvar_conta_e_recarregar(
            numero_convenio,
            mes_ref,
            conta_id,
            banco,
            agencia,
            conta,
            chave_pix,
            cnpj,
            status_conta
        ):
            msg, rows = salvar_conta(
                numero_convenio,
                mes_ref,
                conta_id,
                banco,
                agencia,
                conta,
                chave_pix,
                cnpj,
                status_conta
            )

            df = ensure_df(rows, CONTA_COLS)

            # opcional: limpar formulário após salvar (volta pro default do dropdown)
            return (
                f"<div class='alert'>{msg}</div>",
                df,
                None,     # conta_id
                "",       # banco
                "",       # agencia
                "",       # conta
                "",       # pix
                "",       # cnpj
                "ATIVA"   # ✅ status_conta (default compatível com choices)
            )
        

        btn_salvar_conta.click(
            fn=salvar_conta_e_recarregar,
            inputs=[
                selected_numero_convenio,
                selected_mes_ref,
                conta_id,
                conta_banco,
                conta_agencia,
                conta_numero,
                conta_pix,
                conta_cnpj,
                conta_status
            ],
            outputs=[
                msg_conta,
                contas_df,
                conta_id,
                conta_banco,
                conta_agencia,
                conta_numero,
                conta_pix,
                conta_cnpj,
                conta_status
            ]
        )
    return demo


if __name__ == "__main__":
    app = build_app()
    app.queue() 
    app.launch(
        debug=True,
    )
