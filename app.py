# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import matplotlib.pyplot as plt
import io, requests, re
from matplotlib.ticker import FuncFormatter

# =========================
# CONFIGURAÇÃO DA PÁGINA
# =========================
st.set_page_config(page_title="Dashboard Operacional ETE", layout="wide")

# =========================
# GOOGLE SHEETS – ABA 1 (Respostas ao Formulário / Operacional)
# =========================
SHEET_ID = "1Gv0jhdQLaGkzuzDXWNkD0GD5OMM84Q_zkOkQHGBhLjU"
GID_FORM = "1283870792"  # aba com o formulário operacional
# Corrigido: use &gid= (não &amp;amp;gid=)
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID_FORM}"

# -------------------------
# Carrega a planilha (df = operacional)
# -------------------------
df = pd.read_csv(CSV_URL)
df.columns = [str(c).strip() for c in df.columns]

# =========================
# NORMALIZAÇÃO / AUXILIARES
# =========================
def _strip_accents(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

def _slug(s: str) -> str:
    # gera chave curta para evitar IDs duplicados em gráficos (Plotly)
    return _strip_accents(str(s).lower()).replace(" ", "-").replace("–", "-").replace("/", "-")

cols_lower_noacc = [_strip_accents(c.lower()) for c in df.columns]
COLMAP = dict(zip(cols_lower_noacc, df.columns))  # normalizado -> original

# Palavras‑chave — refletem os nomes reais do Google Forms
KW_CACAMBA   = ["cacamba", "caçamba"]
KW_NITR      = ["nitrificacao", "nitrificação", "nitrificac"]
KW_MBBR      = ["mbbr"]
# Válvulas: no Forms são "Válvula Inferior Tq. MBBR1/2" — sem "nitrificação"
KW_VALVULA   = ["valvula", "válvula"]
KW_SOPRADOR  = ["soprador"]
# Oxigenação: no Forms são "Oxigenação MBBR1/2" e "Oxigenação 1/2 Nitrificação"
KW_OXIG      = ["oxigenacao", "oxigenação"]

# Grupos adicionais
KW_NIVEIS_OUTROS = ["nivel", "nível"]
KW_VAZAO         = ["vazao", "vazão"]
KW_PH            = ["ph "]
KW_SST           = ["sst ", " sst", "ss "]
KW_DQO           = ["dqo ", " dqo"]
KW_ESTADOS       = ["decanter", "desvio", "tempo de desc", "volante"]

# Exclusões genéricas para não poluir cartões
KW_EXCLUDE_GENERIC = KW_SST + KW_DQO + KW_PH + KW_VAZAO + KW_NIVEIS_OUTROS + KW_CACAMBA

# -------------------------
# Conversões e utilidades
# -------------------------
def to_float_ptbr(x):
    """Converte string PT-BR (%, vírgula) para float. Aceita escalar ou Series/DataFrame/list."""
    # Se vier Series/DataFrame/array por engano, tenta extrair um escalar útil
    if isinstance(x, pd.Series):
        xx = x.dropna()
        x = xx.iloc[-1] if not xx.empty else np.nan
    elif isinstance(x, pd.DataFrame):
        xx = x.stack().dropna()
        x = xx.iloc[-1] if not xx.empty else np.nan
    elif isinstance(x, (list, tuple, np.ndarray)):
        x = x[-1] if len(x) else np.nan

    if pd.isna(x):
        return np.nan
    s = str(x).strip().replace("%", "")
    # "10,5" -> "10.5" ; "1.234,5" -> "1234.5"
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    elif "." in s and "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except:
        return np.nan

def last_valid_raw(df_local, col):
    """Retorna o último valor não vazio de uma coluna,
    tratando o caso de cabeçalhos duplicados (DataFrame) ao
    escolher a coluna mais à direita.
    """
    obj = df_local[col]
    # Se houver colunas duplicadas com o mesmo nome, obj será um DataFrame.
    if isinstance(obj, pd.DataFrame):
        s = obj.iloc[:, -1]  # prefere a última coluna (mais à direita)
    else:
        s = obj
    s = s.replace(r"^\s*$", np.nan, regex=True)
    valid = s.dropna()
    if valid.empty:
        return None
    return valid.iloc[-1]

def _filter_columns_by_keywords(all_cols_norm_noacc, keywords):
    """Retorna nomes originais das colunas que contenham QUALQUER keyword."""
    kws = [_strip_accents(k.lower()) for k in keywords]
    selected_norm = []
    for c_norm in all_cols_norm_noacc:
        if any(k in c_norm for k in kws):
            selected_norm.append(c_norm)
    return [COLMAP[c] for c in selected_norm]

def _extract_number(base: str) -> str:
    return "".join(ch for ch in base if ch.isdigit())

def _remove_brackets(text: str) -> str:
    # Remove qualquer coisa após '['
    return text.split("[", 1)[0].strip()

def _units_from_label(label: str) -> str:
    s = _strip_accents(label.lower())
    if "m3/h" in s or "m³/h" in label.lower():
        return " m³/h"
    if "mg/l" in s:
        return " mg/L"
    if "(%)" in label or "%" in label:
        return "%"
    return ""

def _filter_cols_intersection(all_cols_norm_noacc, must_any_1, must_any_2, forbid_any=None):
    kws1 = [_strip_accents(k.lower()) for k in must_any_1]
    kws2 = [_strip_accents(k.lower()) for k in must_any_2]
    forb = [_strip_accents(k.lower()) for k in (forbid_any or [])]
    selected_norm = []
    for c_norm in all_cols_norm_noacc:
        has1 = any(k in c_norm for k in kws1)
        has2 = any(k in c_norm for k in kws2)
        has_forb = any(k in c_norm for k in forb)
        if has1 and has2 and not has_forb:
            selected_norm.append(c_norm)
    return [COLMAP[c] for c in selected_norm]

# =========================
# TEMA CLARO / ESCURO
# =========================
tema_escuro = st.sidebar.toggle("Tema escuro", value=True)

# Paleta de cores
if tema_escuro:
    BG_PRIMARY   = "#1a1d23"
    BG_CARD      = "#22262f"
    BG_SECTION   = "#2a2f3a"
    TEXT_PRIMARY = "#dde1ea"
    TEXT_MUTED   = "#8891a4"
    BORDER_COLOR = "#353c4a"
    GAUGE_BG     = "rgba(255,255,255,0.04)"
    CHART_BG     = "#1a1d23"
    CHART_TEXT   = "#dde1ea"
    CHART_GRID   = "#2a2f3a"
    METRIC_BG    = "#2a2f3a"
    ACCENT       = "#4d9ef7"
else:
    BG_PRIMARY   = "#f6f8fa"
    BG_CARD      = "#ffffff"
    BG_SECTION   = "#eaeef2"
    TEXT_PRIMARY = "#1f2328"
    TEXT_MUTED   = "#656d76"
    BORDER_COLOR = "#d0d7de"
    GAUGE_BG     = "rgba(0,0,0,0.03)"
    CHART_BG     = "#ffffff"
    CHART_TEXT   = "#1f2328"
    CHART_GRID   = "#eaeef2"
    METRIC_BG    = "#f6f8fa"
    ACCENT       = "#0969da"

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap');

:root {{
  --bg-primary:   {BG_PRIMARY};
  --bg-card:      {BG_CARD};
  --bg-section:   {BG_SECTION};
  --text-primary: {TEXT_PRIMARY};
  --text-muted:   {TEXT_MUTED};
  --border:       {BORDER_COLOR};
  --accent:       {ACCENT};
}}

html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"],
[data-testid="block-container"], .main, .stApp {{
  background-color: var(--bg-primary) !important;
  color: var(--text-primary) !important;
  font-family: 'DM Sans', sans-serif !important;
}}

[data-testid="stSidebar"] {{
  background-color: var(--bg-card) !important;
  border-right: 1px solid var(--border) !important;
}}

[data-testid="stSidebar"] * {{
  color: var(--text-primary) !important;
}}

/* Header principal */
.ete-header {{
  padding: 2rem 0 1.5rem;
  border-bottom: 1px solid var(--border);
  margin-bottom: 1.5rem;
}}
.ete-title {{
  font-size: 2rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--text-primary);
  margin: 0;
}}
.ete-subtitle {{
  font-size: 0.875rem;
  color: var(--text-muted);
  margin-top: 0.25rem;
  font-weight: 400;
}}

/* Separadores de seção */
.ete-section-label {{
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 1.75rem 0 0.75rem;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid var(--border);
}}
.ete-section-label span {{
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-muted);
}}
.ete-section-dot {{
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  flex-shrink: 0;
}}

/* Cards de status (tiles HTML) */
.ete-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 0.625rem;
  margin-bottom: 1rem;
}}
.ete-card {{
  border-radius: 10px;
  padding: 0.875rem 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  min-height: 80px;
  justify-content: center;
}}
.ete-card-value {{
  font-size: 1.1rem;
  font-weight: 700;
  color: #ffffff;
  line-height: 1.2;
  font-family: 'DM Mono', monospace;
}}
.ete-card-label {{
  font-size: 0.72rem;
  color: rgba(255,255,255,0.8);
  font-weight: 400;
  line-height: 1.3;
}}

/* Métricas nativas do Streamlit */
[data-testid="stMetric"] {{
  background: var(--bg-section) !important;
  border-radius: 10px;
  padding: 0.875rem 1rem !important;
  border: 1px solid var(--border);
}}
[data-testid="stMetricLabel"] {{
  color: var(--text-muted) !important;
  font-size: 0.75rem !important;
  font-weight: 500 !important;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}}
[data-testid="stMetricValue"] {{
  color: var(--text-primary) !important;
  font-size: 1.4rem !important;
  font-weight: 600 !important;
  font-family: 'DM Mono', monospace;
}}

/* Tabs */
[data-testid="stTabs"] [role="tab"] {{
  font-size: 0.8rem;
  font-weight: 500;
  color: var(--text-muted) !important;
  border-bottom: 2px solid transparent;
  padding: 0.5rem 0.875rem;
}}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {{
  color: var(--text-primary) !important;
  border-bottom-color: var(--accent);
}}

/* Subheaders */
h1, h2, h3 {{
  color: var(--text-primary) !important;
  font-family: 'DM Sans', sans-serif !important;
  font-weight: 600 !important;
  letter-spacing: -0.02em !important;
}}
h2 {{ font-size: 1.15rem !important; }}
h3 {{ font-size: 1rem !important; }}

/* Plotly chart containers */
[data-testid="stPlotlyChart"] {{
  background: var(--bg-card) !important;
  border-radius: 12px;
  border: 1px solid var(--border);
  padding: 0.5rem;
  overflow: hidden;
}}

/* matplotlib */
[data-testid="stImage"] img {{
  border-radius: 10px;
  border: 1px solid var(--border);
}}

/* text_area */
[data-testid="stTextArea"] textarea {{
  background: var(--bg-section) !important;
  color: var(--text-primary) !important;
  border: 1px solid var(--border) !important;
  font-family: 'DM Mono', monospace !important;
  font-size: 0.8rem !important;
  border-radius: 8px !important;
}}

/* Expanders */
[data-testid="stExpander"] {{
  background: var(--bg-card) !important;
  border: 1px solid var(--border) !important;
  border-radius: 10px !important;
}}
[data-testid="stExpander"] summary {{
  color: var(--text-primary) !important;
  font-weight: 500;
}}

/* Botões */
[data-testid="stButton"] button {{
  background: var(--bg-section) !important;
  border: 1px solid var(--border) !important;
  color: var(--text-primary) !important;
  border-radius: 8px !important;
  font-weight: 500 !important;
  font-size: 0.85rem !important;
}}
[data-testid="stButton"] button:hover {{
  border-color: var(--accent) !important;
  color: var(--accent) !important;
}}

/* Status box */
[data-testid="stStatus"] {{
  background: var(--bg-card) !important;
  border: 1px solid var(--border) !important;
  border-radius: 10px !important;
  color: var(--text-primary) !important;
}}

/* Info/warning/error */
[data-testid="stAlert"] {{
  border-radius: 8px !important;
}}

/* Inputs sidebar */
[data-testid="stNumberInput"] input, [data-testid="stTextInput"] input {{
  background: var(--bg-primary) !important;
  color: var(--text-primary) !important;
  border: 1px solid var(--border) !important;
  border-radius: 6px !important;
}}

/* Multiselect */
[data-testid="stMultiSelect"] {{
  background: var(--bg-primary) !important;
}}

/* Cabeçalho de seção de custo */
.ete-cost-header {{
  background: var(--bg-section);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 0.75rem 1rem;
  margin: 1.5rem 0 0.75rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 600;
  font-size: 0.95rem;
  color: var(--text-primary);
}}

/* Resumo sopradores */
.ete-resumo-box {{
  background: var(--bg-section);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 1rem;
  font-family: 'DM Mono', monospace;
  font-size: 0.82rem;
  color: var(--text-primary);
  white-space: pre-wrap;
}}

@media (max-width: 768px) {{
  .ete-title {{ font-size: 1.4rem; }}
  .ete-grid {{ grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 0.5rem; }}
  .ete-card {{ min-height: 70px; padding: 0.75rem 0.625rem; }}
  .ete-card-value {{ font-size: 1rem; }}
  .ete-card-label {{ font-size: 0.68rem; }}
  [data-testid="stMetricValue"] {{ font-size: 1.1rem !important; }}
}}
</style>
""", unsafe_allow_html=True)

# =========================
# PARÂMETROS DO SEMÁFORO (Sidebar)
# =========================
with st.sidebar.expander("Parâmetros do Semáforo", expanded=True):
    st.caption("Ajuste os limites; os valores abaixo são padrões comuns e podem ser adaptados.")
    # Oxigenação (DO)
    st.markdown("**Oxigenação (mg/L)**")
    do_ok_min_nitr = st.number_input("Nitrificação – DO mínimo (verde)", value=2.0, step=0.1)
    do_ok_max_nitr = st.number_input("Nitrificação – DO máximo (verde)", value=3.0, step=0.1)
    do_warn_low_nitr  = st.number_input("Nitrificação – abaixo disso é VERMELHO", value=1.0, step=0.1)
    do_warn_high_nitr = st.number_input("Nitrificação – acima disso é VERMELHO", value=4.0, step=0.1)

    do_ok_min_mbbr = st.number_input("MBBR – DO mínimo (verde)", value=2.0, step=0.1)
    do_ok_max_mbbr = st.number_input("MBBR – DO máximo (verde)", value=3.0, step=0.1)
    do_warn_low_mbbr  = st.number_input("MBBR – abaixo disso é VERMELHO", value=1.0, step=0.1)
    do_warn_high_mbbr = st.number_input("MBBR – acima disso é VERMELHO", value=4.0, step=0.1)

    # pH
    st.markdown("---")
    st.markdown("**pH**")
    ph_ok_min_general = st.number_input("pH geral – mínimo (verde)", value=6.5, step=0.1)
    ph_ok_max_general = st.number_input("pH geral – máximo (verde)", value=8.5, step=0.1)
    ph_warn_low_general  = st.number_input("pH geral – abaixo disso é VERMELHO", value=6.0, step=0.1)
    ph_warn_high_general = st.number_input("pH geral – acima disso é VERMELHO", value=9.0, step=0.1)

    ph_ok_min_mab = st.number_input("pH MAB – mínimo (verde)", value=4.5, step=0.1)
    ph_ok_max_mab = st.number_input("pH MAB – máximo (verde)", value=6.5, step=0.1)
    ph_warn_low_mab  = st.number_input("pH MAB – abaixo disso é VERMELHO", value=4.0, step=0.1)
    ph_warn_high_mab = st.number_input("pH MAB – acima disso é VERMELHO", value=7.0, step=0.1)

    # Qualidade do efluente
    st.markdown("---")
    st.markdown("**Efluente – limites (Saída)**")
    sst_green_max = st.number_input("SST Saída – Máximo (verde) [mg/L]", value=30.0, step=1.0)
    sst_orange_max = st.number_input("SST Saída – Máximo (laranja) [mg/L]", value=50.0, step=1.0)

    dqo_green_max = st.number_input("DQO Saída – Máximo (verde) [mg/L]", value=150.0, step=10.0)
    dqo_orange_max = st.number_input("DQO Saída – Máximo (laranja) [mg/L]", value=300.0, step=10.0)

SEMAFORO_CFG = {
    "do": {
        "nitr": {"ok_min": do_ok_min_nitr, "ok_max": do_ok_max_nitr,
                 "red_low": do_warn_low_nitr, "red_high": do_warn_high_nitr},
        "mbbr": {"ok_min": do_ok_min_mbbr, "ok_max": do_ok_max_mbbr,
                 "red_low": do_warn_low_mbbr, "red_high": do_warn_high_mbbr},
    },
    "ph": {
        "general": {"ok_min": ph_ok_min_general, "ok_max": ph_ok_max_general,
                    "red_low": ph_warn_low_general, "red_high": ph_warn_high_general},
        "mab": {"ok_min": ph_ok_min_mab, "ok_max": ph_ok_max_mab,
                "red_low": ph_warn_low_mab, "red_high": ph_warn_high_mab},
    },
    "sst_saida": {"green_max": sst_green_max, "orange_max": sst_orange_max},
    "dqo_saida": {"green_max": dqo_green_max, "orange_max": dqo_orange_max},
}

# =========================
# CONTROLES VISUAIS DOS RÓTULOS (Sidebar)
# =========================
with st.sidebar.expander("Rotulos das Cartas (visual)", expanded=False):
    cc_lbl_max_points = st.slider("Máximo de rótulos por carta", min_value=0, max_value=60, value=20, step=2)
    cc_lbl_out_of_control = st.checkbox("Rotular pontos fora de controle (LSC/LIC)", value=True)
    cc_lbl_local_extremes = st.checkbox("Rotular extremos locais (máx/mín)", value=True)
    cc_lbl_show_first_last = st.checkbox("Rotular 1º e último ponto", value=True)
    cc_lbl_compact_format = st.checkbox("Formatação compacta (mil/mi)", value=True)
    cc_lbl_fontsize = st.slider("Tamanho da fonte do rótulo", min_value=6, max_value=14, value=8)
    cc_lbl_angle = st.slider("Ângulo do rótulo (graus)", min_value=-90, max_value=90, value=0)
    cc_lbl_bbox = st.checkbox("Fundo no rótulo (melhora leitura)", value=True)

# =========================
# PADRONIZAÇÃO DE NOMES (TÍTULOS)
# =========================

def re_replace_case_insensitive(s, pattern, repl):
    import re
    return re.sub(pattern, repl, s, flags=re.IGNORECASE)


def _nome_exibicao(label_original: str) -> str:
    """
    Padroniza nomes para:
      - "Nível da caçamba X"
      - "Soprador de Nitrificação X" / "Soprador de MBBR X"
      - "Oxigenação Nitrificação X" / "Oxigenação MBBR X"
      - "Válvula ..." conforme área
    """
    base_clean = _remove_brackets(label_original)
    base = _strip_accents(base_clean.lower()).strip()
    num = _extract_number(base)

    # Caçambas
    if "cacamba" in base:
        return f"Nível da caçamba {num}" if num else "Nível da caçamba"

    # Oxigenação (DO) — NÃO chamar de "Soprador"
    if "oxigenacao" in base:
        if any(k in base for k in KW_NITR):
            return f"Oxigenação Nitrificação {num}".strip()
        if any(k in base for k in KW_MBBR):
            return f"Oxigenação MBBR {num}".strip()
        return f"Oxigenação {num}".strip()

    # Sopradores (status)
    if "soprador" in base:
        if any(k in base for k in KW_NITR):
            return f"Soprador de Nitrificação {num}" if num else "Soprador de Nitrificação"
        if any(k in base for k in KW_MBBR):
            return f"Soprador de MBBR {num}" if num else "Soprador de MBBR"
        return f"Soprador {num}" if num else "Soprador"

    # Válvulas
    if "valvula" in base:
        if any(k in base for k in KW_NITR):
            return f"Válvula de Nitrificação {num}" if num else "Válvula de Nitrificação"
        if any(k in base for k in KW_MBBR):
            return f"Válvula de MBBR {num}" if num else "Válvula de MBBR"
        return f"Válvula {num}" if num else "Válvula"

    # Ajustes de capitalização comuns
    txt = base_clean
    replacements = {
        "ph": "pH", "dqo": "DQO", "sst": "SST", "ss ": "SS ",
        "vazao": "Vazão", "nível": "Nível", "nivel": "Nível",
        "mix": "MIX", "tq": "TQ", "mbbr": "MBBR",
        "nitrificacao": "Nitrificação", "nitrificação": "Nitrificação",
        "mab": "MAB",
    }
    for k, v in replacements.items():
        txt = re_replace_case_insensitive(txt, k, v)

    return txt.strip()

# =========================
# MOTOR DE SEMÁFORO (cores)
# =========================
COLOR_OK = "#43A047"      # verde
COLOR_WARN = "#FB8C00"    # laranja
COLOR_BAD = "#E53935"     # vermelho
COLOR_NEUTRAL = "#546E7A" # cinza azulado
COLOR_NULL = "#9E9E9E"    # cinza (sem dado)

def semaforo_numeric_color(label: str, val: float):
    """
    Retorna cor baseada em regras por tipo (Oxigenação, pH, SST/DQO Saída, etc.)
    Se não houver regra aplicável, retorna None (para cair no padrão antigo).
    """
    if val is None or np.isnan(val):
        return COLOR_NULL

    base = _strip_accents(label.lower())

    # -------- Oxigenação (DO) — faixa fixa 1 a 5 mg/L --------
    if "oxigenacao" in base:
        if 1 <= val <= 5:
            return COLOR_OK
        else:
            return COLOR_BAD

    # -------- pH --------
    if re.search(r"\bph\b", base):
        is_mab = "mab" in base
        cfg = SEMAFORO_CFG["ph"]["mab" if is_mab else "general"]
        ok_min, ok_max = cfg["ok_min"], cfg["ok_max"]
        red_low, red_high = cfg["red_low"], cfg["red_high"]
        if val < red_low or val > red_high:
            return COLOR_BAD
        if ok_min <= val <= ok_max:
            return COLOR_OK
        return COLOR_WARN

    # -------- SST / SS — SAÍDA --------
    if "sst" in base or re.search(r"\bss\b", base):
        if "saida" in base or "saída" in label.lower():
            cfg = SEMAFORO_CFG["sst_saida"]
            if val <= cfg["green_max"]:
                return COLOR_OK
            if val <= cfg["orange_max"]:
                return COLOR_WARN
            return COLOR_BAD
        else:
            return COLOR_NEUTRAL  # internos -> neutro

    # -------- DQO — SAÍDA --------
    if "dqo" in base:
        if "saida" in base or "saída" in label.lower():
            cfg = SEMAFORO_CFG["dqo_saida"]
            if val <= cfg["green_max"]:
                return COLOR_OK
            if val <= cfg["orange_max"]:
                return COLOR_WARN
            return COLOR_BAD
        else:
            return COLOR_NEUTRAL  # internos -> neutro

    # Sem regra específica
    return None

# =========================
# GAUGES — SOMENTE colunas com "cacamba" no nome (sem acento)
# =========================

def make_speedometer(val, label):
    nome_exibicao = _nome_exibicao(label)
    if val is None or np.isnan(val):
        val = 0.0

    color = COLOR_OK if val >= 70 else COLOR_WARN if val >= 30 else COLOR_BAD

    return go.Indicator(
        mode="gauge+number",
        value=float(val),
        number={"suffix": "%", "font": {"size": 28, "color": TEXT_PRIMARY}},
        title={"text": f"<b>{nome_exibicao}</b>", "font": {"size": 13, "color": TEXT_MUTED}},
        gauge={
            "axis": {"range": [0, 100], "tickfont": {"size": 10, "color": TEXT_MUTED}, "tickcolor": TEXT_MUTED},
            "bar": {"color": color, "thickness": 0.25},
            "bgcolor": "rgba(0,0,0,0)",
            "borderwidth": 0,
            "steps": [
                {"range": [0, 30],   "color": "rgba(229,57,53,0.12)"},
                {"range": [30, 70],  "color": "rgba(251,140,0,0.12)"},
                {"range": [70, 100], "color": "rgba(67,160,71,0.12)"},
            ],
            "threshold": {"line": {"color": color, "width": 3}, "thickness": 0.75, "value": float(val)},
        },
        domain={"x": [0, 1], "y": [0.05, 1]},
    )


def _cacamba_valor_radio(numero: int) -> float:
    """
    O Google Forms cria uma coluna por opcao de % para cada cacamba
    (ex: 'Cacamba 1 [1%]', 'Cacamba 1 [2%]', ...).
    Encontra todas as colunas da cacamba numero, olha a ultima linha
    preenchida e retorna o valor percentual da opcao marcada.
    """
    padrao = _strip_accents(f"cacamba {numero}").lower()
    cols_desta = [
        col for col in df.columns
        if padrao in _strip_accents(col.lower())
    ]
    if not cols_desta:
        return np.nan

    for idx in range(len(df) - 1, -1, -1):
        row = df.iloc[idx]
        for col in cols_desta:
            v = str(row[col]).strip()
            if v and v.lower() not in ("nan", ""):
                m = re.search(r"(\d+)\s*%", col)
                if m:
                    return float(m.group(1))
                m2 = re.search(r"(\d+)", v)
                if m2:
                    return float(m2.group(1))
    return np.nan


def render_cacambas_gauges(title, n_cols=4):
    """
    Mostra EXATAMENTE um gauge por cacamba numerada, em colunas individuais — 
    muito mais legível no mobile.
    """
    numeros = set()
    for col in df.columns:
        col_norm = _strip_accents(col.lower())
        if "cacamba" in col_norm:
            m = re.search(r"cacamba\s*(\d+)", col_norm)
            if m:
                numeros.add(int(m.group(1)))

    cacambas = sorted(numeros)

    if not cacambas:
        st.info("Nenhuma cacamba encontrada.")
        return

    # Renderiza em linhas de n_cols gauges individuais
    for row_start in range(0, len(cacambas), n_cols):
        row_cacambas = cacambas[row_start:row_start + n_cols]
        cols = st.columns(len(row_cacambas))
        for col_widget, num in zip(cols, row_cacambas):
            with col_widget:
                val = _cacamba_valor_radio(num)
                label = f"Nivel da cacamba {num}"
                fig = go.Figure(make_speedometer(val, label))
                fig.update_layout(
                    height=240,
                    margin=dict(l=20, r=20, t=40, b=40),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font={"family": "DM Sans"},
                )
                st.plotly_chart(fig, use_container_width=True,
                                config={"displayModeBar": False},
                                key=f"gauge-cacamba-{num}")

# =========================
# TILES (cards genéricos com semáforo)
# =========================

def _tile_color_and_text(raw_value, val_num, label, force_neutral_numeric=False):
    """Define cor e texto do card conforme tipo de dado + semáforo configurável."""
    if raw_value is None:
        return COLOR_NULL, "—"

    # 1) Texto (OK/NOK etc.)
    t = _strip_accents(str(raw_value).strip().lower())
    if t in ["ok", "ligado", "aberto", "rodando", "on"]:
        return COLOR_OK, str(raw_value).upper()
    if t in ["nok", "falha", "erro", "fechado", "off"]:
        return COLOR_BAD, str(raw_value).upper()

    # 2) Numérico
    if not np.isnan(val_num):
        units = _units_from_label(label)
        base = _strip_accents(label.lower())

        # ---- Vazão (0 a 200 m³/h) – regra fixa independente de force_neutral_numeric ----
        if "vazao" in base or "vazão" in base:
            if 0 <= val_num <= 200:
                return COLOR_OK, f"{val_num:.0f} m³/h"
            else:
                return COLOR_BAD, f"{val_num:.0f} m³/h"

        # Semáforo dedicado por regra
        color_by_rule = None if force_neutral_numeric else semaforo_numeric_color(label, val_num)
        if color_by_rule is not None:
            return color_by_rule, f"{val_num:.2f}{units}"

        # Caso neutro forçado
        if force_neutral_numeric:
            return COLOR_NEUTRAL, f"{val_num:.2f}{units}"

        # Padrão (mantém 70/30) — melhor para % (ex.: caçamba fora dos gauges)
        if units == "%":
            fill = COLOR_OK if val_num >= 70 else COLOR_WARN if val_num >= 30 else COLOR_BAD
            return fill, f"{val_num:.1f}%"

        # Sem regra específica → neutro
        return COLOR_NEUTRAL, f"{val_num:.2f}{units}"

    # 3) Texto que não bate com dicionário → laranja
    return COLOR_WARN, str(raw_value)

def _render_tiles_from_cols(title, cols_orig, n_cols=4, force_neutral_numeric=False):
    cols_orig = [c for c in cols_orig if c]
    cols_orig = sorted(cols_orig, key=lambda x: _nome_exibicao(x))
    if not cols_orig:
        st.info(f"Nenhum item encontrado para: {title}")
        return

    cols_orig = [c for c in cols_orig if last_valid_raw(df, c) not in (None, "")]

    if not cols_orig:
        st.info(f"Nenhum item encontrado para: {title}")
        return

    cards_html = ""
    for c in cols_orig:
        raw = last_valid_raw(df, c)
        val = to_float_ptbr(raw)
        fill, txt = _tile_color_and_text(raw, val, c, force_neutral_numeric=force_neutral_numeric)
        nome = _nome_exibicao(c)
        cards_html += f"""<div class="ete-card" style="background:{fill};">
            <div class="ete-card-value">{txt}</div>
            <div class="ete-card-label">{nome}</div>
        </div>"""

    st.markdown(f'<div class="ete-grid">{cards_html}</div>', unsafe_allow_html=True)
    if title:
        pass  # título já renderizado pelo chamador via section label


def render_tiles_split(title_base, base_keywords, n_cols=4, exclude_generic=True):
    """Cards: Nitrificação e MBBR para Válvulas/Sopradores/Oxigenação — com interseção e exclusão."""
    excl = KW_EXCLUDE_GENERIC if exclude_generic else []
    # Nitrificação = (base_keywords) AND (KW_NITR)
    cols_nitr = _filter_cols_intersection(
        cols_lower_noacc, must_any_1=base_keywords, must_any_2=KW_NITR, forbid_any=excl
    )
    if cols_nitr:
        st.markdown(f'<div class="ete-section-label"><div class="ete-section-dot"></div><span>{title_base} — Nitrificação</span></div>', unsafe_allow_html=True)
        _render_tiles_from_cols(f"{title_base} – Nitrificação", cols_nitr, n_cols=n_cols)

    # MBBR = (base_keywords) AND (KW_MBBR)
    cols_mbbr = _filter_cols_intersection(
        cols_lower_noacc, must_any_1=base_keywords, must_any_2=KW_MBBR, forbid_any=excl
    )
    if cols_mbbr:
        st.markdown(f'<div class="ete-section-label"><div class="ete-section-dot"></div><span>{title_base} — MBBR</span></div>', unsafe_allow_html=True)
        _render_tiles_from_cols(f"{title_base} – MBBR", cols_mbbr, n_cols=n_cols)

# -------------------------
# Grupos adicionais
# -------------------------

def render_outros_niveis():
    cols = _filter_columns_by_keywords(cols_lower_noacc, KW_NIVEIS_OUTROS)
    cols = [c for c in cols if not any(k in _strip_accents(c.lower()) for k in KW_CACAMBA)]
    if not cols:
        return
    _render_tiles_from_cols("Níveis (MAB/TQ de Lodo)", cols, n_cols=3, force_neutral_numeric=False)


def render_vazoes():
    cols = _filter_columns_by_keywords(cols_lower_noacc, KW_VAZAO)
    if not cols:
        return
    _render_tiles_from_cols("Vazões", cols, n_cols=3, force_neutral_numeric=True)


def render_ph():
    cols = _filter_columns_by_keywords(cols_lower_noacc, KW_PH)
    if not cols:
        return
    _render_tiles_from_cols("pH", cols, n_cols=4, force_neutral_numeric=False)


def render_sst():
    cols = _filter_columns_by_keywords(cols_lower_noacc, KW_SST)
    if not cols:
        return
    _render_tiles_from_cols("Sólidos (SS/SST)", cols, n_cols=4, force_neutral_numeric=False)


def render_dqo():
    cols = _filter_columns_by_keywords(cols_lower_noacc, KW_DQO)
    if not cols:
        return
    _render_tiles_from_cols("DQO", cols, n_cols=4, force_neutral_numeric=False)


def render_estados():
    cols = _filter_columns_by_keywords(cols_lower_noacc, KW_ESTADOS)
    if not cols:
        return
    _render_tiles_from_cols("Estados / Equipamentos", cols, n_cols=3, force_neutral_numeric=False)

# =========================
# CABEÇALHO (última medição)
# =========================

def _operador_valor_radio() -> str:
    """
    O Forms gera uma coluna por nome de operador (ex: 'Operador [Bruce]').
    Percorre a ultima linha preenchida e retorna o nome do operador marcado.
    """
    cols_op = [
        col for col in df.columns
        if "operador" in _strip_accents(col.lower()) or "operardor" in _strip_accents(col.lower())
    ]
    if not cols_op:
        return "—"

    for idx in range(len(df) - 1, -1, -1):
        row = df.iloc[idx]
        for col in cols_op:
            v = str(row[col]).strip()
            if v and v.lower() not in ("nan", ""):
                # Tenta extrair nome do colchete: 'Operador [Bruce]' -> 'Bruce'
                import re as _re
                m = _re.search(r"\[(.+?)\]", col)
                if m:
                    return m.group(1).strip()
                # Se nao tiver colchete, retorna o proprio valor
                return v
    return "—"


def header_info():
    # tenta achar campos de auditoria
    cand = ["carimbo de data/hora", "data"]
    found = {}
    for c in df.columns:
        k = _strip_accents(c.lower())
        if k in [_strip_accents(x) for x in cand]:
            found[k] = c

    col0, col1, col2 = st.columns(3)
    if "carimbo de data/hora" in found:
        col0.metric("Último carimbo", str(last_valid_raw(df, found["carimbo de data/hora"])))
    elif "data" in found:
        col0.metric("Data", str(last_valid_raw(df, found["data"])))
    col1.metric("Operador", _operador_valor_radio())
    col2.metric("Registros", f"{len(df)} linhas")

# =========================
# CARTAS — Funções (rótulos inteligentes)
# =========================

def cc_fmt_brl(v, pos=None):
    try:
        return ("R$ " + f"{v:,.0f}").replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return v


def cc_fmt_brl_compacto(v: float) -> str:
    """Formata R$ de forma compacta (1.200 -> 1,2 mil; 1.200.000 -> 1,2 mi)."""
    try:
        n = float(v)
    except:
        return str(v)
    sinal = "-" if n < 0 else ""
    n = abs(n)
    if n >= 1_000_000:
        return f"{sinal}R$ {n/1_000_000:.1f} mi".replace(".", ",")
    if n >= 1_000:
        return f"{sinal}R$ {n/1_000:.1f} mil".replace(".", ",")
    return (sinal + "R$ " + f"{n:,.0f}").replace(",", "X").replace(".", ",").replace("X", ".")


def _indices_extremos_locais(y: pd.Series) -> set[int]:
    """Encontra picos e vales simples (comparando com vizinhos imediatos)."""
    idxs = set()
    ys = y.reset_index(drop=True)
    for i in range(1, len(ys)-1):
        if pd.isna(ys[i-1]) or pd.isna(ys[i]) or pd.isna(ys[i+1]):
            continue
        # pico
        if ys[i] > ys[i-1] and ys[i] > ys[i+1]:
            idxs.add(y.index[i])
        # vale
        if ys[i] < ys[i-1] and ys[i] < ys[i+1]:
            idxs.add(y.index[i])
    return idxs


def _selecionar_indices_para_rotulo(x: pd.Series, y: pd.Series,
                                    LSC: float, LIC: float,
                                    max_labels: int,
                                    incluir_oor: bool,
                                    incluir_extremos: bool,
                                    incluir_primeiro_ultimo: bool) -> list[int]:
    """
    Seleciona índices a rotular priorizando:
      1) OOR (out-of-range: > LSC ou < LIC)
      2) Extremos locais
      3) Primeiro e último
      4) Preenche com últimos N restantes (mais recentes)
    """
    candidatos = []
    y_clean = y.dropna()
    if y_clean.empty or max_labels <= 0:
        return []

    # 1) Fora de controle
    if incluir_oor:
        oor_idx = y[(y > LSC) | (y < LIC)].dropna().index.tolist()
        candidatos.extend(oor_idx)

    # 2) Extremos locais
    if incluir_extremos:
        extremos = list(_indices_extremos_locais(y))
        candidatos.extend(extremos)

    # 3) Primeiro e último
    if incluir_primeiro_ultimo:
        candidatos.extend([y_clean.index[0], y_clean.index[-1]])

    # Remove duplicados preservando ordem
    seen = set()
    candidatos = [i for i in candidatos if (not (i in seen) and not seen.add(i))]

    # 4) Caso falte preencher até max_labels: pega os mais recentes
    if len(candidatos) < max_labels:
        faltam = max_labels - len(candidatos)
        resto = [idx for idx in y.index.tolist() if (idx not in candidatos) and pd.notna(y.loc[idx])]
        resto = resto[-faltam:]  # últimos
        candidatos.extend(resto)

    return sorted(set(candidatos), key=lambda i: x.loc[i])


def cc_desenhar_carta(x, y, titulo, ylabel, mostrar_rotulos=True):
    """
    Carta de controle com rótulos inteligentes (sem poluição visual).
    Usa controles da sidebar:
      cc_lbl_max_points, cc_lbl_out_of_control, cc_lbl_local_extremes,
      cc_lbl_show_first_last, cc_lbl_compact_format, cc_lbl_fontsize,
      cc_lbl_angle, cc_lbl_bbox
    """
    # Alinha séries e filtra datas inválidas (causa do erro matplotlib year 0001)
    x = pd.Series(x).reset_index(drop=True)
    y = pd.Series(y).reset_index(drop=True).astype(float)
    x_dt = pd.to_datetime(x, errors="coerce")
    mask_ok = x_dt.notna() & (x_dt.dt.year >= 1900) & (x_dt.dt.year <= 2100)
    if mask_ok.sum() == 0:
        st.warning(f"Sem datas válidas para: {titulo}")
        return
    x = x[mask_ok].reset_index(drop=True)
    y = y[mask_ok].reset_index(drop=True)
    # Série como float
    y = y.astype(float)
    # Remove NaN para estatística
    y_stats = y.dropna()
    media = y_stats.mean() if not y_stats.empty else 0.0
    desvio = y_stats.std(ddof=1) if len(y_stats) > 1 else 0.0
    LSC = media + 3*desvio
    LIC = media - 3*desvio

    fig, ax = plt.subplots(figsize=(12, 4.8))
    fig.patch.set_facecolor(CHART_BG)
    ax.set_facecolor(CHART_BG)

    # Série
    ax.plot(x, y, marker="o", color=ACCENT, label="Série", linewidth=2, markersize=5)

    # Linhas de média/controle
    ax.axhline(media, color=ACCENT, linestyle="--", label="Média", alpha=0.7)
    if desvio > 0:
        ax.axhline(LSC, color=COLOR_BAD, linestyle="--", label="LSC (+3σ)", alpha=0.8)
        ax.axhline(LIC, color=COLOR_BAD, linestyle="--", label="LIC (−3σ)", alpha=0.8)

    # Formatação do eixo Y em R$
    ax.yaxis.set_major_formatter(FuncFormatter(cc_fmt_brl))

    # Cor dos ticks e labels
    ax.tick_params(colors=CHART_TEXT, labelsize=9)
    ax.xaxis.label.set_color(CHART_TEXT)
    ax.yaxis.label.set_color(CHART_TEXT)
    ax.title.set_color(CHART_TEXT)
    for spine in ax.spines.values():
        spine.set_edgecolor(CHART_GRID)

    # Rótulos inteligentes
    if mostrar_rotulos and len(y_stats) > 0:
        idx_rotulos = _selecionar_indices_para_rotulo(
            x=pd.Series(x),
            y=y,
            LSC=LSC, LIC=LIC,
            max_labels=cc_lbl_max_points,
            incluir_oor=cc_lbl_out_of_control,
            incluir_extremos=cc_lbl_local_extremes,
            incluir_primeiro_ultimo=cc_lbl_show_first_last,
        )

        # Remove zeros da lista de rótulos — evita amontoamento em séries com muitos R$0
        idx_rotulos = [i for i in idx_rotulos if not (pd.notna(y.loc[i]) and y.loc[i] == 0)]

        def _fmt(v):
            if cc_lbl_compact_format:
                return cc_fmt_brl_compacto(v)
            else:
                return ("R$ " + f"{v:,.0f}").replace(",", "X").replace(".", ",").replace("X", ".")

        # Converte índices para posições numéricas no eixo X para calcular distância
        x_series = pd.Series(x).reset_index(drop=True)
        x_num = pd.to_numeric(pd.to_datetime(x_series, errors="coerce"), errors="coerce")

        bbox = dict(boxstyle="round,pad=0.25", fc=BG_CARD, ec=BORDER_COLOR, alpha=0.85) if cc_lbl_bbox else None

        # Offsets verticais: alterna cima/baixo com amplitude crescente
        # para pontos próximos no eixo X (evita sobreposição)
        OFFSET_BASE = 18
        OFFSET_STEP = 14
        prev_x_num = None
        acum = 0  # acumulador de proximidade para aumentar offset
        sinal = 1

        for k, idx in enumerate(idx_rotulos):
            if pd.isna(y.loc[idx]):
                continue

            # Calcula posição X numérica deste ponto
            try:
                pos_idx = list(y.index).index(idx)
                curr_x_num = x_num.iloc[pos_idx] if pos_idx < len(x_num) else None
            except Exception:
                curr_x_num = None

            # Se está muito próximo do anterior, aumenta o offset
            if prev_x_num is not None and curr_x_num is not None:
                diff = abs(curr_x_num - prev_x_num)
                total_range = x_num.max() - x_num.min() if x_num.max() != x_num.min() else 1
                proporcao = diff / total_range
                if proporcao < 0.04:   # pontos muito próximos (< 4% do range)
                    acum += 1
                else:
                    acum = 0
            else:
                acum = 0

            dy = sinal * (OFFSET_BASE + acum * OFFSET_STEP)
            sinal *= -1  # alterna cima/baixo
            prev_x_num = curr_x_num

            ax.annotate(
                _fmt(y.loc[idx]),
                (x.loc[idx] if hasattr(x, "loc") else pd.Series(x).iloc[list(y.index).index(idx)], y.loc[idx]),
                textcoords="offset points",
                xytext=(0, dy),
                ha="center",
                fontsize=cc_lbl_fontsize,
                rotation=cc_lbl_angle,
                bbox=bbox,
                color=CHART_TEXT,
                arrowprops=dict(arrowstyle="-", color=TEXT_MUTED, lw=0.8) if abs(dy) > OFFSET_BASE else None,
            )

    ax.set_title(titulo)
    ax.set_ylabel(ylabel)
    ax.set_xlabel("Data")
    ax.grid(True, axis="y", alpha=0.2, color=CHART_GRID)
    legend = ax.legend(loc="best", frameon=True)
    legend.get_frame().set_facecolor(BG_CARD)
    legend.get_frame().set_edgecolor(BORDER_COLOR)
    for text in legend.get_texts():
        text.set_color(CHART_TEXT)
    plt.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

# =========================
# DASHBOARD (seções)
# =========================
st.markdown("""
<div class="ete-header">
  <div class="ete-title">Dashboard Operacional ETE</div>
  <div class="ete-subtitle">Monitoramento em tempo real — dados via Google Forms</div>
</div>
""", unsafe_allow_html=True)
header_info()

# Caçambas (gauge)
st.markdown('<div class="ete-section-label"><div class="ete-section-dot"></div><span>Nivel das Cacambas</span></div>', unsafe_allow_html=True)
render_cacambas_gauges("Caçambas")

# Válvulas — no Forms: "Válvula Inferior Tq. MBBR1/2" (somente MBBR, sem nitrificação)
cols_valvulas = [col for col in df.columns if "valvula" in _strip_accents(col.lower()) or "válvula" in col.lower()]
cols_valvulas = [c for c in cols_valvulas if last_valid_raw(df, c) not in (None, "")]
if cols_valvulas:
    st.markdown('<div class="ete-section-label"><div class="ete-section-dot"></div><span>Valvulas — MBBR</span></div>', unsafe_allow_html=True)
    _render_tiles_from_cols("Válvulas – MBBR", cols_valvulas, n_cols=4)

# Sopradores — no Forms: "Sopradores MBBR" e "Sopradores Nitrificação" com radio por soprador
def _render_sopradores_radio(titulo, kw_area):
    """Sopradores do Forms: pergunta-mãe tem OK/NOK/OF e sub-colunas por número de soprador."""
    # Pega colunas cuja pergunta-mãe é o grupo (ex: "Sopradores MBBR [Soprador 1]")
    cols = []
    for col in df.columns:
        cn = _strip_accents(col.lower())
        has_sop = "soprador" in cn
        has_area = any(_strip_accents(k.lower()) in cn for k in kw_area)
        has_oxig = "oxigenac" in cn
        if has_sop and has_area and not has_oxig:
            cols.append(col)
    cols = [c for c in cols if last_valid_raw(df, c) not in (None, "")]
    if cols:
        st.markdown(f'<div class="ete-section-label"><div class="ete-section-dot"></div><span>{titulo}</span></div>', unsafe_allow_html=True)
        _render_tiles_from_cols(titulo, cols, n_cols=4)

_render_sopradores_radio("Sopradores — MBBR", KW_MBBR)
_render_sopradores_radio("Sopradores — Nitrificacao", KW_NITR)

# Oxigenação — no Forms: "Oxigenação MBBR1/2" e "Oxigenação 1/2 Nitrificação" (radio 1-10)
def _render_oxigenacao_radio(titulo, kw_area):
    """Lê colunas de oxigenação (radio 1-10) e consolida por sensor."""
    # Agrupa colunas por sensor (nome sem o valor do radio)
    import re as _re
    grupos = {}  # nome_sensor -> lista de colunas
    for col in df.columns:
        cn = _strip_accents(col.lower())
        if "oxigenac" not in cn:
            continue
        has_area = any(_strip_accents(k.lower()) in cn for k in kw_area)
        if not has_area:
            continue
        # Remove valor entre colchetes para agrupar: "Oxigenação MBBR1 [5]" -> "Oxigenação MBBR1"
        nome_base = _re.sub(r"\s*\[.*?\]", "", col).strip()
        if nome_base not in grupos:
            grupos[nome_base] = []
        grupos[nome_base].append(col)

    if not grupos:
        return

    # Para cada sensor, acha o valor marcado na última linha
    itens_com_valor = []
    for nome_base, cols_grupo in grupos.items():
        for idx in range(len(df) - 1, -1, -1):
            row = df.iloc[idx]
            for col in cols_grupo:
                v = str(row[col]).strip()
                if v and v.lower() not in ("nan", ""):
                    # Tenta extrair número do colchete
                    m = _re.search(r"\[(\d+)\]", col)
                    val = float(m.group(1)) if m else None
                    if val is None:
                        try:
                            val = float(v)
                        except:
                            val = None
                    if val is not None:
                        itens_com_valor.append((nome_base, val))
                    break
            else:
                continue
            break

    if not itens_com_valor:
        return

    # Renderiza como HTML grid
    cards_html = ""
    for nome, val in itens_com_valor:
        color = COLOR_OK if 1 <= val <= 5 else COLOR_BAD
        nome_display = _nome_exibicao(nome)
        cards_html += f"""<div class="ete-card" style="background:{color};">
            <div class="ete-card-value">{val:.0f} mg/L</div>
            <div class="ete-card-label">{nome_display}</div>
        </div>"""

    st.markdown(f'<div class="ete-grid">{cards_html}</div>', unsafe_allow_html=True)

st.markdown('<div class="ete-section-label"><div class="ete-section-dot"></div><span>Oxigenacao — MBBR</span></div>', unsafe_allow_html=True)
_render_oxigenacao_radio("Oxigenação – MBBR", KW_MBBR)
st.markdown('<div class="ete-section-label"><div class="ete-section-dot"></div><span>Oxigenacao — Nitrificacao</span></div>', unsafe_allow_html=True)
_render_oxigenacao_radio("Oxigenação – Nitrificação", KW_NITR)

# ---- Indicadores adicionais
def _section(label):
    st.markdown(f'<div class="ete-section-label"><div class="ete-section-dot"></div><span>{label}</span></div>', unsafe_allow_html=True)

_section("Niveis — MAB / TQ de Lodo")
render_outros_niveis()
_section("Vazoes")
render_vazoes()
_section("pH")
render_ph()
_section("Solidos — SS / SST")
render_sst()
_section("DQO")
render_dqo()
_section("Estados / Equipamentos")
render_estados()

# ============================================================
#        CARTAS DE CONTROLE — CUSTOS (R$)  [MULTI-ITEM]
# ============================================================
st.markdown('<hr style="border:none;border-top:1px solid var(--border);margin:2rem 0 1.5rem;">', unsafe_allow_html=True)
st.markdown('<div class="ete-cost-header">Cartas de Controle — Custo (R$)</div>', unsafe_allow_html=True)

# ---- CONFIG: GID da aba (pode trocar na sidebar) ----
with st.sidebar:
    gid_input = st.text_input("GID da aba de gastos", value="668859455")
CC_GID_GASTOS = gid_input.strip() or "668859455"
# Corrigido: use &gid=
CC_URL_GASTOS = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={CC_GID_GASTOS}"

# Botão de recarregar (útil no Cloud)
if st.button("Recarregar cartas"):
    st.rerun()

@st.cache_data(ttl=900, show_spinner=False)
def cc_baixar_csv_bruto(url: str, timeout: int = 20) -> pd.DataFrame:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    buf = io.StringIO(resp.text)
    df_txt = pd.read_csv(buf, dtype=str, keep_default_na=False, header=None)
    df_txt.columns = [str(c).strip() for c in df_txt.columns]
    return df_txt

def cc_strip_acc_lower(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower().strip()

def cc_find_header_row(df_txt: pd.DataFrame, max_scan: int = 120) -> int | None:
    kws_custo = ["custo", "custos", "gasto", "gastos", "valor", "$"]
    n = min(len(df_txt), max_scan)
    for i in range(n):
        row_vals = [cc_strip_acc_lower(x) for x in df_txt.iloc[i].tolist()]
        has_data  = any("data" in v for v in row_vals)
        has_custo = any(any(kw in v for v in row_vals) for kw in kws_custo)
        if has_data and has_custo:
            return i
    return None

def cc_parse_currency_br(series: pd.Series) -> pd.Series:
    s = series.astype(str)
    s = s.str.replace("\u00A0", " ", regex=False)  # NBSP
    s = s.str.replace("R$", "", regex=False)
    s = s.str.replace(" ", "", regex=False)
    s = s.str.replace(".", "", regex=False)       # milhar
    s = s.str.replace(",", ".", regex=False)      # decimal
    s = s.apply(lambda x: re.sub(r"[^0-9.\-]", "", x))
    return pd.to_numeric(s, errors="coerce")

def cc_guess_item_label(df_txt: pd.DataFrame, header_row: int, col_idx: int, fallback: str) -> str:
    label = ""
    if header_row - 1 >= 0:
        try:
            label = str(df_txt.iat[header_row - 1, col_idx]).strip()
        except Exception:
            label = ""
        if not label:
            for j in range(col_idx - 1, max(-1, col_idx - 8), -1):
                try:
                    v = str(df_txt.iat[header_row - 1, j]).strip()
                except Exception:
                    v = ""
                if v:
                    label = v
                    break
    if not label:
        label = fallback
    label = label.replace("\n", " ").strip()
    if len(label) > 80:
        label = label[:77] + "..."
    return label

with st.status("Carregando dados das cartas...", expanded=True) as status:
    try:
        st.write("• Baixando CSV do Google Sheets…")
        cc_df_raw = cc_baixar_csv_bruto(CC_URL_GASTOS, timeout=20)
        st.write(f"• CSV bruto: {cc_df_raw.shape[0]} linhas × {cc_df_raw.shape[1]} colunas")

        st.write("• Detectando linha de cabeçalho…")
        cc_hdr = cc_find_header_row(cc_df_raw, max_scan=120)
        if cc_hdr is None:
            st.error("Não achei a linha de cabeçalho com DATA e CUSTOS na aba informada.")
            st.stop()

        cc_header_vals = [str(x).strip() for x in cc_df_raw.iloc[cc_hdr].tolist()]
        cc_df_all = cc_df_raw.iloc[cc_hdr + 1:].copy()
        cc_df_all.columns = cc_header_vals
        cc_df_all = cc_df_all.loc[:, [c.strip() != "" for c in cc_df_all.columns]]

        status.update(label="Dados carregados com sucesso ✅", state="complete")
    except requests.exceptions.Timeout:
        st.error("Timeout ao acessar o Google Sheets (20s). Tente novamente ou verifique sua conexão.")
        st.stop()
    except requests.exceptions.RequestException as e:
        st.error(f"Falha ao baixar o CSV: {e}")
        st.stop()
    except Exception as e:
        st.error(f"Erro inesperado ao preparar dados: {e}")
        st.stop()

cc_norm_cols = [cc_strip_acc_lower(c) for c in cc_df_all.columns]
CC_KW_COST_INCLUDE = ["custo", "custos", "gasto", "gastos", "valor", "$"]
CC_KW_COST_EXCLUDE = ["media", "média", "status", "automatic", "automatico", "automático", "meta"]

def cc_is_valid_cost_header(nc: str) -> bool:
    has_include = any(k in nc for k in CC_KW_COST_INCLUDE)
    has_exclude = any(k in nc for k in CC_KW_COST_EXCLUDE)
    return has_include and not has_exclude

cc_cost_idx_list = [i for i, nc in enumerate(cc_norm_cols) if cc_is_valid_cost_header(nc)]
cc_data_idx_list = [i for i, nc in enumerate(cc_norm_cols) if "data" in nc]

if not cc_cost_idx_list:
    st.error("Não encontrei nenhuma coluna de CUSTO/GASTO/VALOR válida (excluídas: média, status, meta).")
    st.write("Colunas disponíveis:", list(cc_df_all.columns))
    st.stop()
if not cc_data_idx_list:
    st.error("Não encontrei nenhuma coluna de DATA.")
    st.write("Colunas disponíveis:", list(cc_df_all.columns))
    st.stop()

cc_items = []
cc_seen_labels = set()

for cost_idx in cc_cost_idx_list:
    cost_name = cc_df_all.columns[cost_idx]
    left_data = [i for i in cc_data_idx_list if i <= cost_idx]
    if left_data:
        data_idx = max(left_data)
    else:
        data_idx = min(cc_data_idx_list, key=lambda i: abs(i - cost_idx))
    data_name = cc_df_all.columns[data_idx]

    df_item = pd.DataFrame({
        "DATA": pd.to_datetime(cc_df_all.iloc[:, data_idx].astype(str), errors="coerce", dayfirst=True),
        "CUSTO": cc_parse_currency_br(cc_df_all.iloc[:, cost_idx]),
    }).dropna(subset=["DATA", "CUSTO"]).sort_values("DATA")

    if df_item.empty:
        continue

    label_guess = cc_guess_item_label(cc_df_raw, cc_hdr, cost_idx, fallback=cost_name)
    label_norm = cc_strip_acc_lower(label_guess)
    if label_norm in cc_seen_labels:
        continue
    cc_seen_labels.add(label_norm)

    cc_items.append({
        "label": label_guess,
        "cost_name": cost_name,
        "data_name": data_name,
        "data_idx": data_idx,
        "cost_idx": cost_idx,
        "df": df_item
    })

if not cc_items:
    st.warning("Nenhum item com dados válidos (DATA + CUSTO) foi encontrado após os filtros.")
    with st.expander("Debug de cabecalhos de custo filtrados"):
        df_debug = pd.DataFrame({
            "col": list(cc_df_all.columns),
            "norm": cc_norm_cols,
            "is_valid_cost": [ cc_is_valid_cost_header(n) for n in cc_norm_cols ],
        })
        st.dataframe(df_debug)
    st.stop()

cc_labels_all = [it["label"] for it in cc_items]
cc_sel_labels = st.multiselect("Itens para exibir nas cartas", cc_labels_all, default=cc_labels_all)
cc_mostrar_rotulos = st.checkbox("Mostrar rótulos de dados nas cartas", value=True)

cc_items = [it for it in cc_items if it["label"] in cc_sel_labels]
if not cc_items:
    st.info("Selecione pelo menos um item para visualizar.")
    st.stop()

def cc_ultimo_valido_positivo(ser: pd.Series) -> float:
    s = pd.to_numeric(ser, errors="coerce")
    s = s[~s.isna()]
    if s.empty:
        return 0.0
    nz = s[s != 0]
    if not nz.empty:
        return float(nz.iloc[-1])
    return float(s.iloc[-1])


def cc_metricas_item(df_item: pd.DataFrame):
    ultimo = cc_ultimo_valido_positivo(df_item["CUSTO"])
    mask_nz = df_item["CUSTO"].fillna(0) != 0
    idx_ref = mask_nz[mask_nz].index[-1] if mask_nz.any() else df_item.index[-1]

    iso_week = df_item["DATA"].dt.isocalendar()
    df_tmp = df_item.copy()
    df_tmp["__sem__"]    = iso_week.week.astype(int)
    df_tmp["__anoiso__"] = iso_week.year.astype(int)
    ult_sem = int(df_tmp.loc[idx_ref, "__sem__"])
    ult_ano = int(df_tmp.loc[idx_ref, "__anoiso__"])
    custo_semana = df_tmp[(df_tmp["__sem__"] == ult_sem) & (df_tmp["__anoiso__"] == ult_ano)]["CUSTO"].sum()

    df_tmp["__mes__"] = df_tmp["DATA"].dt.month
    df_tmp["__ano__"] = df_tmp["DATA"].dt.year
    ult_mes  = int(df_tmp.loc[idx_ref, "__mes__"])
    ult_ano2 = int(df_tmp.loc[idx_ref, "__ano__"])
    custo_mes = df_tmp[(df_tmp["__mes__"] == ult_mes) & (df_tmp["__ano__"] == ult_ano2)]["CUSTO"].sum()

    return ultimo, custo_semana, custo_mes


cc_tabs = st.tabs([it["label"] for it in cc_items])
for tab, it in zip(cc_tabs, cc_items):
    with tab:
        df_item = it["df"]

        ultimo, custo_semana, custo_mes = cc_metricas_item(df_item)
        c1, c2, c3 = st.columns(3)
        c1.metric("Custo do Dia",
                  f"R$ {ultimo:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        c2.metric("Custo da Semana",
                  f"R$ {custo_semana:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        c3.metric("Custo do Mês",
                  f"R$ {custo_mes:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

        df_day = df_item.groupby("DATA", as_index=False)["CUSTO"].sum().sort_values("DATA")

        df_week = (
            df_item.assign(semana=df_item["DATA"].dt.to_period("W-MON"))
                   .groupby("semana", as_index=False)["CUSTO"].sum()
        )
        df_week["Data"] = df_week["semana"].dt.start_time

        df_month = (
            df_item.assign(mes=df_item["DATA"].dt.to_period("M"))
                   .groupby("mes", as_index=False)["CUSTO"].sum()
        )
        df_month["Data"] = df_month["mes"].dt.to_timestamp()

        st.subheader("Carta Diaria")
        cc_desenhar_carta(df_day["DATA"], df_day["CUSTO"],
                          f"Custo Diário (R$) — {it['label']}", "R$", mostrar_rotulos=cc_mostrar_rotulos)

        st.subheader("Carta Semanal (ISO)")
        cc_desenhar_carta(df_week["Data"], df_week["CUSTO"],
                          f"Custo Semanal (R$) — {it['label']}", "R$", mostrar_rotulos=cc_mostrar_rotulos)

        st.subheader("Carta Mensal")
        cc_desenhar_carta(df_month["Data"], df_month["CUSTO"],
                          f"Custo Mensal (R$) — {it['label']}", "R$", mostrar_rotulos=cc_mostrar_rotulos)

        with st.expander("Debug do item"):
            st.write("Coluna de DATA original:", it["data_name"], " | índice:", it["data_idx"])
            st.write("Coluna de CUSTO original:", it["cost_name"], " | índice:", it["cost_idx"])
            st.dataframe(df_item.head(10))

# ------------------------------------------------------------
# 7) RESUMO TEXTO — Sopradores (para WhatsApp/Relatório)
# ------------------------------------------------------------

def _col_matches_any(cnorm: str, kws):
    kws_norm = [_strip_accents(k.lower()) for k in kws]
    return any(k in cnorm for k in kws_norm)


def _select_soprador_cols(df_cols_norm, area_keywords):
    sel = []
    for c_norm in df_cols_norm:
        has_soprador = "soprador" in c_norm
        has_area = _col_matches_any(c_norm, area_keywords)
        has_excluded = _col_matches_any(c_norm, KW_EXCLUDE_GENERIC + KW_OXIG)
        if has_soprador and has_area and not has_excluded:
            sel.append(c_norm)
    return [COLMAP[c] for c in sel]


def _parse_status_ok_nok(raw):
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return "—"
    t = _strip_accents(str(raw).strip().lower())
    if t in ["ok", "ligado", "aberto", "rodando", "on"]:
        return "OK"
    if t in ["nok", "falha", "erro", "fechado", "off"]:
        return "NOK"
    return "—"


def _extract_first_int(text: str) -> int | None:
    m = re.search(r"\d+", _strip_accents(text.lower()))
    return int(m.group()) if m else None


def _coletar_status_area(df, area_keywords):
    cols_area = _select_soprador_cols(cols_lower_noacc, area_keywords)
    itens = []
    for col in cols_area:
        num = _extract_first_int(col)
        raw = last_valid_raw(df, col)
        stt = _parse_status_ok_nok(raw)
        itens.append((num, stt, col))
    itens.sort(key=lambda x: (9999 if x[0] is None else x[0], _strip_accents(x[2].lower())))
    pares = [f"{num} ({stt})" for num, stt, _ in itens if num is not None]
    return pares


def gerar_resumo_sopradores(df):
    mbbr_linha = _coletar_status_area(df, KW_MBBR)
    nitr_linha = _coletar_status_area(df, KW_NITR)
    linhas = []
    linhas.append("Sopradores MBBR:")
    linhas.append(" ".join(mbbr_linha) if mbbr_linha else "—")
    linhas.append("Sopradores Nitrificação:")
    linhas.append(" ".join(nitr_linha) if nitr_linha else "—")
    return "\n".join(linhas)
    # ==============================================================================
# MICROBIOLOGIA — Análise de imagens via Google Gemini + Regras CETESB L1.025
# ==============================================================================
# COMO USAR:
#   Cole este bloco inteiro no FINAL do seu app.py,
#   logo após a função gerar_resumo_sopradores().
#   Depois adicione a chamada:
#
#       render_microbiologia()
#
#   no final do arquivo (após o bloco do resumo de sopradores).
#
# SECRETS necessários no Streamlit Cloud (.streamlit/secrets.toml):
#   GOOGLE_API_KEY   = "sua-chave-1"
#   GOOGLE_API_KEY_2 = "sua-chave-2"
#   GOOGLE_API_KEY_3 = "sua-chave-3"
# ==============================================================================

import base64, tempfile, json, os, time as _time
import subprocess

# ──────────────────────────────────────────────────────────────────────────────
# TABELA 6 CETESB L1.025 — mapeamento organismo → diagnóstico
# ──────────────────────────────────────────────────────────────────────────────
_MICRO_TABELA6 = {
    "flagelados": {
        "semaforo": "vermelho",
        "condicao": "Deficiência de aeração, má depuração e/ou sobrecarga orgânica",
        "recomendacao": "Verificar OD no tanque de aeração. Reduzir carga orgânica ou aumentar aeração.",
    },
    "flagelados_rizopodes": {
        "semaforo": "laranja",
        "condicao": "Lodo jovem — início de operação ou θc baixa",
        "recomendacao": "Verificar idade do lodo. Sistema em partida ou com sobrecarga hidráulica.",
    },
    "ciliados_pedunculados": {
        "semaforo": "verde",
        "condicao": "Boas condições de depuração (ciliados pedunculados)",
        "recomendacao": "Sistema operando bem. Manter parâmetros atuais.",
    },
    "ciliados_livres": {
        "semaforo": "verde",
        "condicao": "Boas condições de depuração (ciliados livres)",
        "recomendacao": "Sistema operando bem.",
    },
    "arcella": {
        "semaforo": "verde",
        "condicao": "Boa depuração — Arcella sp. presente",
        "recomendacao": "Indicador positivo. Manter condições atuais.",
    },
    "aspidisca": {
        "semaforo": "verde",
        "condicao": "Nitrificação ocorrendo — Aspidisca costata",
        "recomendacao": "Nitrificação ativa. Monitorar amônia e nitrito.",
    },
    "trachelophyllum": {
        "semaforo": "laranja",
        "condicao": "Idade do lodo (θc) elevada — Trachelophyllum",
        "recomendacao": "Lodo velho. Avaliar descarte para rejuvenescer a biomassa.",
    },
    "vorticella_microstoma": {
        "semaforo": "vermelho",
        "condicao": "Efluente de má qualidade — Vorticella microstoma",
        "recomendacao": "Investigar causa: sobrecarga, tóxicos ou aeração insuficiente.",
    },
    "aelosoma": {
        "semaforo": "laranja",
        "condicao": "Excesso de OD — Aelosoma (anelídeo)",
        "recomendacao": "Reduzir aeração. OD possivelmente > 6 mg/L.",
    },
    "rotiferos": {
        "semaforo": "verde",
        "condicao": "Lodo maduro com boa sedimentação — Rotíferos presentes",
        "recomendacao": "Indicador positivo de lodo aeróbio maduro.",
    },
    "filamentos": {
        "semaforo": "vermelho",
        "condicao": "Risco de intumescimento filamentoso (bulking)",
        "recomendacao": "Verificar IVL. Causas: baixo OD, sobrecarga, pH baixo, falta de nutrientes.",
    },
    "nematoides": {
        "semaforo": "laranja",
        "condicao": "θc elevada — Nematóides presentes",
        "recomendacao": "Monitorar descarte de lodo.",
    },
    "rizopodes_amebas": {
        "semaforo": "laranja",
        "condicao": "Lodo jovem ou em transição — Amebas/Rizópodes",
        "recomendacao": "Verificar idade do lodo e condições operacionais.",
    },
    "flocos_bons": {
        "semaforo": "verde",
        "condicao": "Flocos bem formados — boa sedimentação",
        "recomendacao": "Morfologia do lodo adequada. Manter operação.",
    },
    "flocos_dispersos": {
        "semaforo": "vermelho",
        "condicao": "Lodo disperso (pin-point) — má sedimentação",
        "recomendacao": "Verificar θc, toxicidade e variações de carga.",
    },
    "cianobacterias": {
        "semaforo": "vermelho",
        "condicao": "Cianobactérias — risco de toxicidade",
        "recomendacao": "ALERTA: possível toxicidade. Verificar origem do afluente.",
    },
    "protozoa_livre": {
        "semaforo": "laranja",
        "condicao": "Protozoários de vida livre — qualidade moderada",
        "recomendacao": "Monitorar evolução. Pode indicar lodo jovem ou perturbação.",
    },
}

_COR = {"verde": "#43A047", "laranja": "#FB8C00", "vermelho": "#E53935", "cinza": "#546E7A"}

_PESO_CETESB = {
    "ciliados_pedunculados": +3,
    "ciliados_livres":       +2,
    "rotiferos":             +3,
    "arcella":               +2,
    "aspidisca":             +2,
    "flocos_bons":           +2,
    "nematoides":            +1,
    "trachelophyllum":        0,
    "aelosoma":              -1,
    "protozoa_livre":         0,
    "rizopodes_amebas":      -1,
    "flagelados_rizopodes":  -1,
    "flocos_dispersos":      -2,
    "flagelados":            -3,
    "vorticella_microstoma": -3,
    "filamentos":            -2,
}

# ──────────────────────────────────────────────────────────────────────────────
# GERENCIAMENTO DE CHAVES API
# ──────────────────────────────────────────────────────────────────────────────
def _carregar_chaves_gemini() -> list:
    if not hasattr(st, "secrets"):
        return []
    chaves = []
    for nome in ["GOOGLE_API_KEY", "GOOGLE_API_KEY_2", "GOOGLE_API_KEY_3", "GOOGLE_API_KEY_4"]:
        v = st.secrets.get(nome, "")
        if v:
            chaves.append(v)
    return chaves

# ──────────────────────────────────────────────────────────────────────────────
# COTA DIÁRIA / POR MINUTO
# ──────────────────────────────────────────────────────────────────────────────
_COTA_FILE = "/tmp/gemini_cota_micro.json"

def _cota_carregar() -> dict:
    from datetime import datetime, timezone, timedelta
    BRT = timezone(timedelta(hours=-3))
    agora = datetime.now(BRT)
    reset_hoje = agora.replace(hour=4, minute=0, second=0, microsecond=0)
    if agora < reset_hoje:
        reset_hoje -= timedelta(days=1)
    padrao = {"total_dia": 0, "ultimo_reset": reset_hoje.isoformat(), "historico_min": []}
    if not os.path.exists(_COTA_FILE):
        return padrao
    try:
        with open(_COTA_FILE) as f:
            dados = json.load(f)
        ultimo_reset = datetime.fromisoformat(dados["ultimo_reset"])
        if ultimo_reset < reset_hoje:
            dados["total_dia"] = 0
            dados["ultimo_reset"] = reset_hoje.isoformat()
            dados["historico_min"] = []
        return dados
    except Exception:
        return padrao

def _cota_salvar(dados: dict):
    try:
        with open(_COTA_FILE, "w") as f:
            json.dump(dados, f)
    except Exception:
        pass

def _cota_incrementar():
    from datetime import datetime, timezone, timedelta
    BRT = timezone(timedelta(hours=-3))
    agora = datetime.now(BRT).timestamp()
    dados = _cota_carregar()
    dados["total_dia"] = dados.get("total_dia", 0) + 1
    hist = [t for t in dados.get("historico_min", []) if agora - t < 60]
    hist.append(agora)
    dados["historico_min"] = hist
    _cota_salvar(dados)
    return dados["total_dia"], len(hist)

def _cota_status() -> dict:
    from datetime import datetime, timezone, timedelta
    BRT = timezone(timedelta(hours=-3))
    agora = datetime.now(BRT).timestamp()
    dados = _cota_carregar()
    hist = [t for t in dados.get("historico_min", []) if agora - t < 60]
    n_chaves = len(_carregar_chaves_gemini())
    lim = max(n_chaves, 1)
    return {
        "total_dia":  dados.get("total_dia", 0),
        "limite_dia": 1500 * lim,
        "req_min":    len(hist),
        "limite_min": 15 * lim,
        "n_chaves":   n_chaves,
    }

def _cota_widget():
    from datetime import datetime, timezone, timedelta
    BRT = timezone(timedelta(hours=-3))
    agora = datetime.now(BRT)
    reset = agora.replace(hour=4, minute=0, second=0, microsecond=0)
    if agora >= reset:
        reset += timedelta(days=1)
    hh = int((reset - agora).total_seconds() // 3600)
    mm = int(((reset - agora).total_seconds() % 3600) // 60)
    s = _cota_status()
    pct = s["total_dia"] / s["limite_dia"] if s["limite_dia"] else 0
    cor = "🟢" if pct < 0.6 else ("🟡" if pct < 0.85 else "🔴")
    with st.expander(f"{cor} Cota Gemini — {s['total_dia']}/{s['limite_dia']} req hoje", expanded=False):
        c1, c2, c3 = st.columns(3)
        c1.metric("Usadas hoje",   s["total_dia"],  delta=f"/{s['limite_dia']}")
        c2.metric("Req/min agora", s["req_min"],    delta=f"/{s['limite_min']} limite")
        c3.metric("Chaves ativas", s["n_chaves"])
        st.progress(min(pct, 1.0))
        st.caption(f"Reset em {hh}h {mm}min (04:00 BRT) · Dados aproximados por sessão")

# ──────────────────────────────────────────────────────────────────────────────
# EXTRAÇÃO DE FRAMES (vídeo via ffmpeg)
# ──────────────────────────────────────────────────────────────────────────────
def _extrair_frames_video(video_bytes: bytes) -> list:
    frames_b64 = []
    with tempfile.TemporaryDirectory() as tmpdir:
        vpath = os.path.join(tmpdir, "video.mp4")
        with open(vpath, "wb") as f:
            f.write(video_bytes)
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", vpath],
            capture_output=True, text=True
        )
        try:
            duration = float(result.stdout.strip())
        except Exception:
            duration = 10.0
        for i, t in enumerate([duration * 0.33, duration * 0.66]):
            fpath = os.path.join(tmpdir, f"frame_{i:02d}.jpg")
            subprocess.run(
                ["ffmpeg", "-ss", str(t), "-i", vpath,
                 "-vframes", "1", "-vf", "scale=768:-1", "-q:v", "5",
                 fpath, "-y"],
                capture_output=True
            )
            if os.path.exists(fpath):
                with open(fpath, "rb") as fimg:
                    frames_b64.append(base64.b64encode(fimg.read()).decode())
    return frames_b64

# ──────────────────────────────────────────────────────────────────────────────
# COMPRESSÃO DE IMAGEM (economiza tokens na API)
# ──────────────────────────────────────────────────────────────────────────────
def _comprimir_b64(b64: str, max_lado: int = 1024, qualidade: int = 82) -> str:
    try:
        from PIL import Image
        import io as _io
        data = base64.b64decode(b64)
        img = Image.open(_io.BytesIO(data)).convert("RGB")
        w, h = img.size
        if max(w, h) > max_lado:
            ratio = max_lado / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = _io.BytesIO()
        img.save(buf, format="JPEG", quality=qualidade, optimize=True)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return b64

# ──────────────────────────────────────────────────────────────────────────────
# PROMPT DO SISTEMA — especialista CETESB L1.025
# ──────────────────────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """Você é um especialista em microbiologia de lodos ativados da norma CETESB L1.025.

MISSÃO: Analisar imagens de microscópio de lodo ativado e identificar organismos indicadores conforme a Tabela 6 da L1.025.

CHAVES VÁLIDAS para o campo "chave" (use EXATAMENTE uma delas):
flagelados, flagelados_rizopodes, ciliados_pedunculados, ciliados_livres, arcella,
aspidisca, trachelophyllum, vorticella_microstoma, aelosoma, rotiferos, filamentos,
nematoides, rizopodes_amebas, flocos_bons, flocos_dispersos, cianobacterias, protozoa_livre

REGRA CRÍTICA: organismos[] NUNCA pode ser vazio. Se a imagem for de baixa qualidade,
identifique ao menos flocos (flocos_bons ou flocos_dispersos) com confiança baixa (0.3).

ESTRATÉGIA PARA IMAGENS DIFÍCEIS:
- Imagem turva/escura → "flocos_dispersos", confiança 0.4
- Partículas visíveis → "flocos_bons" ou "flocos_dispersos"
- Estruturas alongadas → "filamentos"
- Organismos com cílios/movimento → "ciliados_livres" ou "ciliados_pedunculados"
- Em dúvida → escolha a chave mais próxima com confiança 0.3–0.5

Retorne SOMENTE JSON puro, sem markdown, sem texto fora do JSON:
{
  "organismos": [
    {
      "chave": "chave_valida",
      "nome": "Nome científico ou comum",
      "grupo": "Grupo taxonômico",
      "descricao": "O que foi observado na imagem",
      "confianca": 0.0
    }
  ],
  "qualidade_imagem": "boa|regular|ruim",
  "observacoes_gerais": "Observação geral sobre o estado do lodo"
}"""

# ──────────────────────────────────────────────────────────────────────────────
# CHAMADA À API GEMINI — com rotação de chaves e retry
# ──────────────────────────────────────────────────────────────────────────────
def _chamar_gemini(frames_b64: list, params_dia: dict) -> dict:
    chaves = _carregar_chaves_gemini()
    if not chaves:
        raise RuntimeError("Nenhuma chave GOOGLE_API_KEY encontrada nos Secrets do Streamlit.")

    # Contexto operacional para enriquecer a análise
    ctx = ""
    if params_dia:
        ctx = "\n\nParâmetros operacionais do dia:\n"
        for k, v in params_dia.items():
            if v:
                ctx += f"  - {k}: {v}\n"
        ctx += "\nConsidere esses valores ao interpretar os organismos encontrados."

    # Monta partes da mensagem (imagens + texto)
    parts = []
    for b64 in frames_b64:
        b64_comprimido = _comprimir_b64(b64)
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64_comprimido}})
    parts.append({"text": (
        f"Analise estas imagens de microscópio de lodo ativado de ETE.{ctx}\n\n"
        "IMPORTANTE: Identifique todos os organismos/estruturas visíveis conforme CETESB L1.025.\n"
        "Retorne SOMENTE JSON puro conforme as instruções."
    )})

    payload = {
        "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
        "contents":           [{"parts": parts}],
        "generationConfig":   {"temperature": 0.1, "maxOutputTokens": 1000},
    }

    url_base = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key="
    chaves_esgotadas = set()
    idx = 0
    retries_servidor = 0
    MAX_503 = 3

    while True:
        # Pula chaves com cota diária esgotada
        tentativas = 0
        while idx in chaves_esgotadas:
            idx = (idx + 1) % len(chaves)
            tentativas += 1
            if tentativas >= len(chaves):
                raise RuntimeError(
                    f"COTA_DIARIA_ESGOTADA: todas as {len(chaves)} chaves atingiram o limite diário.\n"
                    "Aguarde o reset às 04:00 BRT ou adicione mais chaves nos Secrets."
                )

        try:
            resp = requests.post(
                url_base + chaves[idx],
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=90,
            )

            if resp.status_code == 429:
                corpo = ""
                try:
                    corpo = str(resp.json()).lower()
                except Exception:
                    corpo = resp.text.lower()

                if "daily" in corpo or "per_day" in corpo:
                    # Cota diária — marca chave e tenta próxima
                    chaves_esgotadas.add(idx)
                    idx = (idx + 1) % len(chaves)
                    _time.sleep(1)
                    continue
                else:
                    # Rate limit por minuto — não é fatal
                    raise RuntimeError("RATE_LIMIT_MIN")

            if resp.status_code == 503:
                retries_servidor += 1
                if retries_servidor <= MAX_503:
                    espera = 5 * retries_servidor
                    st.toast(f"Servidor ocupado, aguardando {espera}s... ({retries_servidor}/{MAX_503})")
                    _time.sleep(espera)
                    continue
                resp.raise_for_status()

            resp.raise_for_status()
            break

        except requests.exceptions.Timeout:
            retries_servidor += 1
            if retries_servidor <= MAX_503:
                st.toast(f"Timeout — tentando novamente ({retries_servidor}/{MAX_503})...")
                _time.sleep(5)
                continue
            raise

    # Parse da resposta
    try:
        texto = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        return {"organismos": [], "qualidade_imagem": "ruim",
                "observacoes_gerais": f"Resposta inesperada: {str(resp.json())[:200]}"}

    texto = texto.strip()
    for m in ["```json", "```JSON", "```"]:
        texto = texto.replace(m, "")
    texto = texto.strip()

    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', texto, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        return {"organismos": [], "qualidade_imagem": "ruim",
                "observacoes_gerais": f"Erro ao parsear JSON. Texto: {texto[:300]}"}

# ──────────────────────────────────────────────────────────────────────────────
# DIAGNÓSTICO CETESB — pontuação ponderada por confiança
# ──────────────────────────────────────────────────────────────────────────────
def _diagnostico_cetesb(organismos: list) -> dict:
    if not organismos:
        return {
            "qualidade":   "indeterminada",
            "descricao":   "Nenhum organismo identificado.",
            "cor":         _COR["cinza"],
            "acoes":       ["Repetir análise com imagens de melhor qualidade."],
        }

    chaves = {o.get("chave", "") for o in organismos}
    conf_map = {}
    for o in organismos:
        ch = o.get("chave", "")
        conf_map[ch] = max(conf_map.get(ch, 0), o.get("confianca", 0.5))

    # Regras absolutas
    if "cianobacterias" in chaves:
        return {"qualidade": "critico", "cor": _COR["vermelho"],
                "descricao": "Cianobactérias detectadas — risco de toxicidade.",
                "acoes": ["Verificar origem do afluente.", "Alertar equipe de operação imediatamente."]}

    if "flocos_dispersos" in chaves and "flocos_bons" not in chaves:
        return {"qualidade": "ruim", "cor": _COR["vermelho"],
                "descricao": "Lodo totalmente disperso (pin-point) — má sedimentação.",
                "acoes": ["Verificar θc.", "Investigar tóxicos no afluente."]}

    # Score ponderado
    score = sum(_PESO_CETESB.get(ch, 0) * conf for ch, conf in conf_map.items())

    acoes = []
    if "filamentos" in chaves:
        acoes.append("Monitorar IVL — filamentos presentes, avaliar risco de bulking.")
    if "flagelados" in chaves:
        acoes.append("Verificar OD no tanque — flagelados indicam deficiência de aeração.")
    if "vorticella_microstoma" in chaves:
        acoes.append("Investigar sobrecarga, tóxicos ou aeração insuficiente.")
    if "aelosoma" in chaves:
        acoes.append("OD possivelmente elevado (>6 mg/L) — reduzir aeração.")

    if score >= 3:
        return {"qualidade": "boa", "cor": _COR["verde"],
                "descricao": "Sistema estável com organismos indicadores de boa depuração.",
                "acoes":     acoes or ["Manter parâmetros operacionais."]}
    elif score >= 0:
        return {"qualidade": "regular", "cor": _COR["laranja"],
                "descricao": "Sistema em equilíbrio — organismos mistos, monitorar evolução.",
                "acoes":     acoes or ["Verificar idade do lodo e parâmetros operacionais."]}
    elif score >= -2:
        return {"qualidade": "ruim", "cor": _COR["vermelho"],
                "descricao": "Organismos indicadores de problema — verificar operação.",
                "acoes":     acoes or ["Verificar OD, carga orgânica e θc."]}
    else:
        return {"qualidade": "critico", "cor": _COR["vermelho"],
                "descricao": "Múltiplos indicadores negativos — problema sério no sistema.",
                "acoes":     acoes or ["Acionar equipe técnica para revisão completa."]}

# ──────────────────────────────────────────────────────────────────────────────
# GERADOR DE RELATÓRIO COMPLETO (texto copiável)
# ──────────────────────────────────────────────────────────────────────────────
def _gerar_relatorio(organismos: list, diag: dict, params_dia: dict, confianca_media: float) -> str:
    from datetime import datetime, timezone, timedelta
    BRT = timezone(timedelta(hours=-3))
    agora = datetime.now(BRT).strftime("%d/%m/%Y %H:%M")

    linhas = [
        "=" * 52,
        "   RELATÓRIO MICROBIOLÓGICO — LODO ATIVADO",
        f"   Data/Hora: {agora}",
        "   Norma: CETESB L1.025 + IA (Gemini)",
        "=" * 52,
        "",
        f"QUALIDADE DO PROCESSO: {diag['qualidade'].upper()}",
        f"Diagnóstico: {diag['descricao']}",
        f"Confiança média da análise: {confianca_media*100:.0f}%",
        "",
    ]

    if params_dia:
        linhas.append("PARÂMETROS DO DIA:")
        for k, v in params_dia.items():
            if v:
                linhas.append(f"  {k}: {v}")
        linhas.append("")

    linhas.append(f"MICRORGANISMOS IDENTIFICADOS ({len(organismos)}):")
    for o in organismos:
        conf_pct = int(o.get("confianca", 0) * 100)
        meta = _MICRO_TABELA6.get(o.get("chave", ""), {})
        linhas.append(f"  • {o.get('nome','?')} ({o.get('grupo','')})")
        linhas.append(f"    Observação: {o.get('descricao','')}")
        if meta.get("condicao"):
            linhas.append(f"    Indicação CETESB: {meta['condicao']}")
        linhas.append(f"    Confiança da IA: {conf_pct}%")
        linhas.append("")

    linhas.append("DIAGNÓSTICO CETESB L1.025 (Tabela 6):")
    chaves_unicas = list({o.get("chave", "") for o in organismos if o.get("chave") in _MICRO_TABELA6})
    for ch in chaves_unicas:
        meta = _MICRO_TABELA6[ch]
        semaforo = {"verde": "[✓]", "laranja": "[!]", "vermelho": "[✗]"}.get(meta["semaforo"], "[-]")
        linhas.append(f"  {semaforo} {meta['condicao']}")
        if meta["semaforo"] != "verde":
            linhas.append(f"      → {meta['recomendacao']}")
    linhas.append("")

    linhas.append("AÇÕES RECOMENDADAS:")
    for acao in diag["acoes"]:
        linhas.append(f"  • {acao}")
    linhas.append("")
    linhas.append("Análise gerada por IA + regras CETESB L1.025")
    linhas.append("Confirme sempre com análise laboratorial qualificada.")

    return "\n".join(linhas)

# ──────────────────────────────────────────────────────────────────────────────
# INTERFACE PRINCIPAL — render_microbiologia()
# ──────────────────────────────────────────────────────────────────────────────
def render_microbiologia():
    st.markdown(
        '<hr style="border:none;border-top:1px solid var(--border);margin:2rem 0 1.5rem;">',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="ete-section-label">'
        '<div class="ete-section-dot"></div>'
        '<span>Microbiologia do Lodo — Análise por IA (CETESB L1.025)</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Suba fotos ou vídeo do microscópio. "
        "A IA identifica os organismos e gera relatório conforme a Tabela 6 da L1.025."
    )

    # Widget de cota
    _cota_widget()

    # Parâmetros do dia (contexto para enriquecer o prompt)
    params_dia = {}
    for kws, label in [
        (["ph mbbr", "ph mab"],            "pH"),
        (["oxigenac", "oxigenação"],        "OD Nitrificação"),
        (["sst nitrif"],                    "SST Nitrificação"),
        (["dqo saida", "dqo saída"],        "DQO Saída"),
    ]:
        for col in df.columns:
            if any(k in _strip_accents(col.lower()) for k in kws):
                v = last_valid_raw(df, col)
                if v:
                    params_dia[label] = str(v)
                    break

    if params_dia:
        st.caption("Parâmetros do último registro (usados como contexto para a IA):")
        cols_p = st.columns(len(params_dia))
        for i, (k, v) in enumerate(params_dia.items()):
            cols_p[i].metric(k, v)

    # ── Seleção do modo de upload ──────────────────────────────────────────────
    st.subheader("Upload de Imagens ou Vídeo do Microscópio")
    modo = st.radio(
        "Formato:",
        ["📷 Fotos (JPG/PNG)", "🎥 Vídeo (MP4/MOV)"],
        horizontal=True,
        key="micro_modo_upload",
    )

    frames_b64: list = []

    if "Fotos" in modo:
        imgs = st.file_uploader(
            "Selecione até 3 fotos do microscópio",
            type=["jpg", "jpeg", "png", "bmp", "tiff"],
            accept_multiple_files=True,
            key="micro_upload_fotos",
            help="O sistema usa as 2 primeiras imagens para economizar cota da API.",
        )
        if imgs:
            frames_b64 = [base64.b64encode(img.read()).decode() for img in imgs[:2]]
            cols = st.columns(min(len(frames_b64), 2))
            for i, b64 in enumerate(frames_b64):
                cols[i].image(base64.b64decode(b64), caption=f"Imagem {i+1}", use_container_width=True)

    else:
        video_file = st.file_uploader(
            "Selecione o vídeo (.mp4, .mov, .avi)",
            type=["mp4", "mov", "avi", "webm", "mkv"],
            key="micro_upload_video",
        )
        if video_file is not None:
            st.video(video_file)
            video_file.seek(0)
            video_bytes = video_file.read()
            st.caption(f"Tamanho: {len(video_bytes)/(1024*1024):.1f} MB")
            with st.spinner("Extraindo frames do vídeo..."):
                try:
                    frames_b64 = _extrair_frames_video(video_bytes)
                    if frames_b64:
                        st.success(f"{len(frames_b64)} frame(s) extraído(s).")
                        cols = st.columns(min(len(frames_b64), 2))
                        for i, b64 in enumerate(frames_b64):
                            cols[i].image(base64.b64decode(b64), caption=f"Frame {i+1}", use_container_width=True)
                    else:
                        st.error("Não foi possível extrair frames. Use o modo Fotos.")
                except Exception as e:
                    st.error(f"ffmpeg indisponível neste servidor. Use o modo Fotos.\n\nDetalhe: {e}")

    # ── Botão de análise ───────────────────────────────────────────────────────
    if frames_b64:
        if st.button("🔬 Analisar com IA + Regras CETESB", type="primary", use_container_width=True):

            if not _carregar_chaves_gemini():
                st.error("Chave GOOGLE_API_KEY não encontrada nos Secrets do Streamlit.")
                st.stop()

            with st.status("Analisando imagens...", expanded=True) as status_box:
                try:
                    st.write(f"🤖 Enviando {len(frames_b64)} imagem(ns) para o Gemini...")
                    resultado = _chamar_gemini(frames_b64, params_dia)
                    _cota_incrementar()

                    organismos = resultado.get("organismos", [])
                    qualidade  = resultado.get("qualidade_imagem", "regular")
                    obs        = resultado.get("observacoes_gerais", "")

                    if not organismos:
                        st.warning(
                            "A IA não identificou organismos nesta imagem. "
                            "Tente com foto mais nítida (melhor iluminação e foco)."
                        )

                    st.write("📋 Aplicando regras CETESB L1.025 (Tabela 6)...")
                    diag = _diagnostico_cetesb(organismos)

                    confianca_media = (
                        sum(o.get("confianca", 0) for o in organismos) / len(organismos)
                        if organismos else 0.0
                    )

                    st.session_state["micro_resultado"] = {
                        "organismos":      organismos,
                        "qualidade_img":   qualidade,
                        "obs_gerais":      obs,
                        "diag":            diag,
                        "confianca_media": confianca_media,
                        "params_dia":      params_dia,
                    }
                    status_box.update(label="✅ Análise concluída!", state="complete")

                except RuntimeError as e:
                    msg = str(e)
                    if "COTA_DIARIA_ESGOTADA" in msg:
                        st.warning(
                            "⚠️ **Cota diária da API esgotada em todas as chaves.**\n\n"
                            "Aguarde o reset às **04:00 BRT** ou adicione mais chaves "
                            "(`GOOGLE_API_KEY_2`, `_3`...) nos Secrets do Streamlit."
                        )
                    elif "RATE_LIMIT_MIN" in msg:
                        st.warning(
                            "⏳ **Muitas requisições por minuto.**\n\n"
                            "Aguarde **1 minuto** e tente novamente. "
                            "Isso não consome sua cota diária."
                        )
                    else:
                        st.error(f"Erro: {msg}")
                    st.stop()
                except Exception as e:
                    st.error(f"Erro inesperado: {e}")
                    import traceback
                    st.code(traceback.format_exc())
                    st.stop()

    # ── Exibição dos resultados ────────────────────────────────────────────────
    r = st.session_state.get("micro_resultado")
    if not r:
        st.info(
            "Faça upload de imagens do microscópio e clique em **Analisar** "
            "para ver o diagnóstico microbiológico."
        )
        return

    organismos      = r["organismos"]
    qualidade_img   = r["qualidade_img"]
    obs_gerais      = r["obs_gerais"]
    diag            = r["diag"]
    confianca_media = r["confianca_media"]
    params_dia_r    = r["params_dia"]

    # Aviso de qualidade da imagem
    if qualidade_img == "ruim":
        st.info("💡 Qualidade de imagem baixa — confiança reduzida, mas análise realizada com o disponível.")
    elif qualidade_img == "regular":
        st.info("Qualidade regular das imagens.")

    if obs_gerais:
        st.caption(f"Observação da IA: {obs_gerais}")

    if not organismos:
        st.warning("Nenhum organismo identificado com as imagens fornecidas.")
        if st.button("🔄 Limpar e tentar novamente", key="micro_btn_limpar_vazio"):
            del st.session_state["micro_resultado"]
            st.rerun()
        return

    # ── Métricas resumo ────────────────────────────────────────────────────────
    st.subheader("Resumo da Análise")
    m1, m2, m3 = st.columns(3)
    m1.metric("Organismos identificados", len(organismos))
    m2.metric("Confiança média",          f"{confianca_media*100:.0f}%")
    m3.metric("Qualidade da imagem",      qualidade_img.capitalize())

    # ── Card de qualidade do processo ─────────────────────────────────────────
    st.subheader("Qualidade Estimada do Lodo / Processo")
    cor   = diag["cor"]
    qual  = diag["qualidade"].upper()
    desc  = diag["descricao"]
    st.markdown(
        f"""<div style="background:{cor};border-radius:10px;padding:16px 20px;
                        margin-bottom:12px;color:white;">
            <div style="font-size:18px;font-weight:700">Qualidade: {qual}</div>
            <div style="font-size:13px;margin-top:6px;opacity:0.92">{desc}</div>
            <div style="font-size:11px;margin-top:8px;opacity:0.75;font-family:monospace">
                Análise: IA Gemini + Tabela 6 CETESB L1.025
            </div>
        </div>""",
        unsafe_allow_html=True,
    )

    # Ações recomendadas
    with st.expander("📋 Ações Recomendadas", expanded=True):
        for a in diag["acoes"]:
            st.markdown(f"• {a}")

    # ── Cards de organismos ────────────────────────────────────────────────────
    st.subheader(f"Organismos Detectados ({len(organismos)})")
    cols_org = st.columns(2)
    for i, o in enumerate(organismos):
        meta  = _MICRO_TABELA6.get(o.get("chave", ""), {"semaforo": "cinza", "condicao": "", "recomendacao": ""})
        cor_o = _COR.get(meta.get("semaforo", "cinza"), _COR["cinza"])
        conf  = o.get("confianca", 0.0)
        barra = "█" * int(conf * 10) + "░" * (10 - int(conf * 10))
        icon  = {"verde": "✅", "laranja": "⚠️", "vermelho": "🔴", "cinza": "🔍"}.get(meta.get("semaforo", "cinza"), "🔍")
        with cols_org[i % 2]:
            st.markdown(
                f"""<div style="background:{cor_o};border-radius:8px;padding:12px 14px;
                                margin-bottom:8px;color:white;">
                    <div style="font-size:15px;font-weight:500">{icon} {o.get('nome','—')}</div>
                    <div style="font-size:11px;opacity:0.85">{o.get('grupo','')}</div>
                    <div style="font-size:12px;margin-top:6px">{o.get('descricao','')}</div>
                    {'<div style="font-size:11px;margin-top:4px;opacity:0.85">📋 ' + meta['condicao'] + '</div>'
                      if meta.get('condicao') else ''}
                    <div style="font-size:11px;margin-top:6px;opacity:0.8">
                        🎯 Confiança: {barra} {conf*100:.0f}%
                    </div>
                </div>""",
                unsafe_allow_html=True,
            )

    # ── Diagnóstico pela Tabela 6 ──────────────────────────────────────────────
    st.subheader("Diagnóstico CETESB L1.025 — Tabela 6")
    chaves_unicas = list({o.get("chave", "") for o in organismos if o.get("chave") in _MICRO_TABELA6})

    for ch in chaves_unicas:
        meta = _MICRO_TABELA6[ch]
        if meta["semaforo"] == "vermelho":
            st.error(f"**{meta['condicao']}**\n\n→ {meta['recomendacao']}")
        elif meta["semaforo"] == "laranja":
            st.warning(f"**{meta['condicao']}**\n\n→ {meta['recomendacao']}")
        else:
            st.success(f"**{meta['condicao']}**")

    # ── Relatório copiável ─────────────────────────────────────────────────────
    st.subheader("Relatório Completo — Copiar para WhatsApp / Laudo")
    relatorio = _gerar_relatorio(organismos, diag, params_dia_r, confianca_media)
    st.text_area(
        "Selecione tudo (Ctrl+A) e copie (Ctrl+C):",
        value=relatorio,
        height=300,
        key="micro_ta_relatorio",
        label_visibility="collapsed",
    )
    st.caption("Ctrl+A → Ctrl+C para copiar o relatório completo.")

    if st.button("🔄 Limpar e analisar novamente", key="micro_btn_limpar"):
        del st.session_state["micro_resultado"]
        st.rerun()


# ──────────────────────────────────────────────────────────────────────────────
# CHAMADA — adicione esta linha no final do seu app.py
# ──────────────────────────────────────────────────────────────────────────────
render_microbiologia()
