# -*- coding: utf-8 -*-
"""
Dashboard Operacional ETE
Refatorado – nível sênior
"""

# =============================================================================
# IMPORTS — único bloco, sem duplicatas
# =============================================================================
import base64
import io
import json
import os
import re
import subprocess
import tempfile
import time as _time
import unicodedata

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from plotly.subplots import make_subplots  # noqa: F401 (disponível se necessário)

# =============================================================================
# CONFIGURAÇÃO DA PÁGINA
# =============================================================================
st.set_page_config(page_title="Dashboard Operacional ETE", layout="wide")

# =============================================================================
# GOOGLE SHEETS — ABA OPERACIONAL
# =============================================================================
SHEET_ID = "1Gv0jhdQLaGkzuzDXWNkD0GD5OMM84Q_zkOkQHGBhLjU"
GID_FORM = "1283870792"
CSV_URL  = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID_FORM}"

df = pd.read_csv(CSV_URL)
df.columns = [str(c).strip() for c in df.columns]

# =============================================================================
# UTILITÁRIOS GERAIS
# =============================================================================

def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", str(s))
        if unicodedata.category(c) != "Mn"
    )

def _slug(s: str) -> str:
    return _strip_accents(str(s).lower()).replace(" ", "-").replace("–", "-").replace("/", "-")

def _remove_brackets(text: str) -> str:
    return text.split("[", 1)[0].strip()

def _extract_number(base: str) -> str:
    return "".join(ch for ch in base if ch.isdigit())

def _units_from_label(label: str) -> str:
    s = _strip_accents(label.lower())
    if "m3/h" in s or "m³/h" in label.lower():
        return " m³/h"
    if "mg/l" in s:
        return " mg/L"
    if "(%)" in label or "%" in label:
        return "%"
    return ""

def re_replace_ci(s: str, pattern: str, repl: str) -> str:
    return re.sub(pattern, repl, s, flags=re.IGNORECASE)

def to_float_ptbr(x):
    """Converte valor PT-BR (vírgula decimal, %) para float."""
    if isinstance(x, pd.Series):
        xx = x.dropna(); x = xx.iloc[-1] if not xx.empty else np.nan
    elif isinstance(x, pd.DataFrame):
        xx = x.stack().dropna(); x = xx.iloc[-1] if not xx.empty else np.nan
    elif isinstance(x, (list, tuple, np.ndarray)):
        x = x[-1] if len(x) else np.nan
    if pd.isna(x):
        return np.nan
    s = str(x).strip().replace("%", "")
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    elif "." in s and "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return np.nan

def last_valid_raw(df_local: pd.DataFrame, col):
    """Último valor não-vazio; lida com colunas duplicadas."""
    obj = df_local[col]
    s = obj.iloc[:, -1] if isinstance(obj, pd.DataFrame) else obj
    s = s.replace(r"^\s*$", np.nan, regex=True)
    valid = s.dropna()
    return valid.iloc[-1] if not valid.empty else None

# =============================================================================
# MAPEAMENTO DE COLUNAS
# =============================================================================
cols_lower_noacc = [_strip_accents(c.lower()) for c in df.columns]
COLMAP = dict(zip(cols_lower_noacc, df.columns))

# Keywords por grupo
KW_CACAMBA        = ["cacamba", "caçamba"]
KW_NITR           = ["nitrificacao", "nitrificação", "nitrificac"]
KW_MBBR           = ["mbbr"]
KW_VALVULA        = ["valvula", "válvula"]
KW_SOPRADOR       = ["soprador"]
KW_OXIG           = ["oxigenacao", "oxigenação"]
KW_NIVEIS_OUTROS  = ["nivel", "nível"]
KW_VAZAO          = ["vazao", "vazão"]
KW_PH             = ["ph "]
KW_SST            = ["sst ", " sst", "ss "]
KW_DQO            = ["dqo ", " dqo"]
KW_ESTADOS        = ["decanter", "desvio", "tempo de desc", "volante"]
KW_EXCLUDE_GENERIC = KW_SST + KW_DQO + KW_PH + KW_VAZAO + KW_NIVEIS_OUTROS + KW_CACAMBA


def _filter_columns_by_keywords(all_cols_norm, keywords: list) -> list:
    kws = [_strip_accents(k.lower()) for k in keywords]
    return [COLMAP[c] for c in all_cols_norm if any(k in c for k in kws)]


def _filter_cols_intersection(all_cols_norm, must_any_1, must_any_2, forbid_any=None) -> list:
    kws1 = [_strip_accents(k.lower()) for k in must_any_1]
    kws2 = [_strip_accents(k.lower()) for k in must_any_2]
    forb = [_strip_accents(k.lower()) for k in (forbid_any or [])]
    return [
        COLMAP[c] for c in all_cols_norm
        if any(k in c for k in kws1)
        and any(k in c for k in kws2)
        and not any(k in c for k in forb)
    ]

# =============================================================================
# TEMA CLARO / ESCURO
# =============================================================================
tema_escuro = st.sidebar.toggle("Tema escuro", value=True)

if tema_escuro:
    BG_PRIMARY   = "#1a1d23"
    BG_CARD      = "#22262f"
    BG_SECTION   = "#2a2f3a"
    TEXT_PRIMARY = "#dde1ea"
    TEXT_MUTED   = "#8891a4"
    BORDER_COLOR = "#353c4a"
    CHART_BG     = "#1a1d23"
    CHART_TEXT   = "#dde1ea"
    CHART_GRID   = "#2a2f3a"
    ACCENT       = "#4d9ef7"
else:
    BG_PRIMARY   = "#f6f8fa"
    BG_CARD      = "#ffffff"
    BG_SECTION   = "#eaeef2"
    TEXT_PRIMARY = "#1f2328"
    TEXT_MUTED   = "#656d76"
    BORDER_COLOR = "#d0d7de"
    CHART_BG     = "#ffffff"
    CHART_TEXT   = "#1f2328"
    CHART_GRID   = "#eaeef2"
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
[data-testid="stSidebar"] * {{ color: var(--text-primary) !important; }}

.ete-header {{
  padding: 2rem 0 1.5rem;
  border-bottom: 1px solid var(--border);
  margin-bottom: 1.5rem;
}}
.ete-title {{
  font-size: 2rem; font-weight: 700; letter-spacing: -0.03em;
  color: var(--text-primary); margin: 0;
}}
.ete-subtitle {{
  font-size: 0.875rem; color: var(--text-muted);
  margin-top: 0.25rem; font-weight: 400;
}}
.ete-section-label {{
  display: flex; align-items: center; gap: 0.5rem;
  margin: 1.75rem 0 0.75rem;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid var(--border);
}}
.ete-section-label span {{
  font-size: 0.7rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--text-muted);
}}
.ete-section-dot {{
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--accent); flex-shrink: 0;
}}
.ete-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 0.625rem; margin-bottom: 1rem;
}}
.ete-card {{
  border-radius: 10px; padding: 0.875rem 0.75rem;
  display: flex; flex-direction: column; gap: 0.3rem;
  min-height: 80px; justify-content: center;
}}
.ete-card-value {{
  font-size: 1.1rem; font-weight: 700; color: #ffffff;
  line-height: 1.2; font-family: 'DM Mono', monospace;
}}
.ete-card-label {{
  font-size: 0.72rem; color: rgba(255,255,255,0.8);
  font-weight: 400; line-height: 1.3;
}}
[data-testid="stMetric"] {{
  background: var(--bg-section) !important;
  border-radius: 10px; padding: 0.875rem 1rem !important;
  border: 1px solid var(--border);
}}
[data-testid="stMetricLabel"] {{
  color: var(--text-muted) !important; font-size: 0.75rem !important;
  font-weight: 500 !important; text-transform: uppercase; letter-spacing: 0.06em;
}}
[data-testid="stMetricValue"] {{
  color: var(--text-primary) !important; font-size: 1.4rem !important;
  font-weight: 600 !important; font-family: 'DM Mono', monospace;
}}
[data-testid="stTabs"] [role="tab"] {{
  font-size: 0.8rem; font-weight: 500; color: var(--text-muted) !important;
  border-bottom: 2px solid transparent; padding: 0.5rem 0.875rem;
}}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {{
  color: var(--text-primary) !important; border-bottom-color: var(--accent);
}}
h1, h2, h3 {{
  color: var(--text-primary) !important;
  font-family: 'DM Sans', sans-serif !important;
  font-weight: 600 !important; letter-spacing: -0.02em !important;
}}
h2 {{ font-size: 1.15rem !important; }}
h3 {{ font-size: 1rem !important; }}
[data-testid="stPlotlyChart"] {{
  background: var(--bg-card) !important; border-radius: 12px;
  border: 1px solid var(--border); padding: 0.5rem; overflow: hidden;
}}
[data-testid="stImage"] img {{ border-radius: 10px; border: 1px solid var(--border); }}
[data-testid="stTextArea"] textarea {{
  background: var(--bg-section) !important; color: var(--text-primary) !important;
  border: 1px solid var(--border) !important;
  font-family: 'DM Mono', monospace !important; font-size: 0.8rem !important;
  border-radius: 8px !important;
}}
[data-testid="stExpander"] {{
  background: var(--bg-card) !important; border: 1px solid var(--border) !important;
  border-radius: 10px !important;
}}
[data-testid="stExpander"] summary {{ color: var(--text-primary) !important; font-weight: 500; }}
[data-testid="stButton"] button {{
  background: var(--bg-section) !important; border: 1px solid var(--border) !important;
  color: var(--text-primary) !important; border-radius: 8px !important;
  font-weight: 500 !important; font-size: 0.85rem !important;
}}
[data-testid="stButton"] button:hover {{
  border-color: var(--accent) !important; color: var(--accent) !important;
}}
[data-testid="stStatus"] {{
  background: var(--bg-card) !important; border: 1px solid var(--border) !important;
  border-radius: 10px !important; color: var(--text-primary) !important;
}}
[data-testid="stAlert"] {{ border-radius: 8px !important; }}
[data-testid="stNumberInput"] input, [data-testid="stTextInput"] input {{
  background: var(--bg-primary) !important; color: var(--text-primary) !important;
  border: 1px solid var(--border) !important; border-radius: 6px !important;
}}
.ete-cost-header {{
  background: var(--bg-section); border: 1px solid var(--border);
  border-radius: 10px; padding: 0.75rem 1rem;
  margin: 1.5rem 0 0.75rem; display: flex; align-items: center;
  gap: 0.5rem; font-weight: 600; font-size: 0.95rem;
  color: var(--text-primary);
}}
.ete-resumo-box {{
  background: var(--bg-section); border: 1px solid var(--border);
  border-radius: 10px; padding: 1rem;
  font-family: 'DM Mono', monospace; font-size: 0.82rem;
  color: var(--text-primary); white-space: pre-wrap;
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

# =============================================================================
# PARÂMETROS DO SEMÁFORO (Sidebar)
# =============================================================================
with st.sidebar.expander("Parâmetros do Semáforo", expanded=True):
    st.caption("Ajuste os limites; os valores abaixo são padrões comuns.")
    st.markdown("**Oxigenação (mg/L)**")
    do_ok_min_nitr    = st.number_input("Nitrificação – DO mínimo (verde)",        value=2.0, step=0.1)
    do_ok_max_nitr    = st.number_input("Nitrificação – DO máximo (verde)",        value=3.0, step=0.1)
    do_warn_low_nitr  = st.number_input("Nitrificação – abaixo disso é VERMELHO",  value=1.0, step=0.1)
    do_warn_high_nitr = st.number_input("Nitrificação – acima disso é VERMELHO",   value=4.0, step=0.1)
    do_ok_min_mbbr    = st.number_input("MBBR – DO mínimo (verde)",               value=2.0, step=0.1)
    do_ok_max_mbbr    = st.number_input("MBBR – DO máximo (verde)",               value=3.0, step=0.1)
    do_warn_low_mbbr  = st.number_input("MBBR – abaixo disso é VERMELHO",         value=1.0, step=0.1)
    do_warn_high_mbbr = st.number_input("MBBR – acima disso é VERMELHO",          value=4.0, step=0.1)

    st.markdown("---")
    st.markdown("**pH**")
    ph_ok_min_general    = st.number_input("pH geral – mínimo (verde)",         value=6.5, step=0.1)
    ph_ok_max_general    = st.number_input("pH geral – máximo (verde)",         value=8.5, step=0.1)
    ph_warn_low_general  = st.number_input("pH geral – abaixo disso VERMELHO",  value=6.0, step=0.1)
    ph_warn_high_general = st.number_input("pH geral – acima disso VERMELHO",   value=9.0, step=0.1)
    ph_ok_min_mab        = st.number_input("pH MAB – mínimo (verde)",           value=4.5, step=0.1)
    ph_ok_max_mab        = st.number_input("pH MAB – máximo (verde)",           value=6.5, step=0.1)
    ph_warn_low_mab      = st.number_input("pH MAB – abaixo disso VERMELHO",    value=4.0, step=0.1)
    ph_warn_high_mab     = st.number_input("pH MAB – acima disso VERMELHO",     value=7.0, step=0.1)

    st.markdown("---")
    st.markdown("**Efluente – limites (Saída)**")
    sst_green_max  = st.number_input("SST Saída – Máx verde [mg/L]",   value=30.0,  step=1.0)
    sst_orange_max = st.number_input("SST Saída – Máx laranja [mg/L]", value=50.0,  step=1.0)
    dqo_green_max  = st.number_input("DQO Saída – Máx verde [mg/L]",   value=150.0, step=10.0)
    dqo_orange_max = st.number_input("DQO Saída – Máx laranja [mg/L]", value=300.0, step=10.0)

SEMAFORO_CFG = {
    "do": {
        "nitr": {"ok_min": do_ok_min_nitr,  "ok_max": do_ok_max_nitr,
                 "red_low": do_warn_low_nitr, "red_high": do_warn_high_nitr},
        "mbbr": {"ok_min": do_ok_min_mbbr,  "ok_max": do_ok_max_mbbr,
                 "red_low": do_warn_low_mbbr, "red_high": do_warn_high_mbbr},
    },
    "ph": {
        "general": {"ok_min": ph_ok_min_general,  "ok_max": ph_ok_max_general,
                    "red_low": ph_warn_low_general, "red_high": ph_warn_high_general},
        "mab":     {"ok_min": ph_ok_min_mab,       "ok_max": ph_ok_max_mab,
                    "red_low": ph_warn_low_mab,      "red_high": ph_warn_high_mab},
    },
    "sst_saida": {"green_max": sst_green_max,  "orange_max": sst_orange_max},
    "dqo_saida": {"green_max": dqo_green_max,  "orange_max": dqo_orange_max},
}

# =============================================================================
# CONTROLES DE RÓTULOS (Sidebar)
# =============================================================================
with st.sidebar.expander("Rótulos das Cartas (visual)", expanded=False):
    cc_lbl_max_points      = st.slider("Máximo de rótulos por carta",          0,  60, 20, 2)
    cc_lbl_out_of_control  = st.checkbox("Rotular fora de controle (LSC/LIC)", value=True)
    cc_lbl_local_extremes  = st.checkbox("Rotular extremos locais (máx/mín)",  value=True)
    cc_lbl_show_first_last = st.checkbox("Rotular 1º e último ponto",          value=True)
    cc_lbl_compact_format  = st.checkbox("Formatação compacta (mil/mi)",        value=True)
    cc_lbl_fontsize        = st.slider("Tamanho da fonte do rótulo",            6,  14, 8)
    cc_lbl_angle           = st.slider("Ângulo do rótulo (graus)",            -90,  90, 0)
    cc_lbl_bbox            = st.checkbox("Fundo no rótulo",                    value=True)

# =============================================================================
# PADRONIZAÇÃO DE NOMES
# =============================================================================

def _nome_exibicao(label_original: str) -> str:
    base_clean = _remove_brackets(label_original)
    base = _strip_accents(base_clean.lower()).strip()
    num  = _extract_number(base)

    if "cacamba" in base:
        return f"Nível da caçamba {num}" if num else "Nível da caçamba"
    if "oxigenacao" in base:
        if any(k in base for k in KW_NITR):
            return f"Oxigenação Nitrificação {num}".strip()
        if any(k in base for k in KW_MBBR):
            return f"Oxigenação MBBR {num}".strip()
        return f"Oxigenação {num}".strip()
    if "soprador" in base:
        if any(k in base for k in KW_NITR):
            return f"Soprador de Nitrificação {num}" if num else "Soprador de Nitrificação"
        if any(k in base for k in KW_MBBR):
            return f"Soprador de MBBR {num}" if num else "Soprador de MBBR"
        return f"Soprador {num}" if num else "Soprador"
    if "valvula" in base:
        if any(k in base for k in KW_NITR):
            return f"Válvula de Nitrificação {num}" if num else "Válvula de Nitrificação"
        if any(k in base for k in KW_MBBR):
            return f"Válvula de MBBR {num}" if num else "Válvula de MBBR"
        return f"Válvula {num}" if num else "Válvula"

    txt = base_clean
    for k, v in {
        "ph": "pH", "dqo": "DQO", "sst": "SST", "ss ": "SS ",
        "vazao": "Vazão", "nível": "Nível", "nivel": "Nível",
        "mix": "MIX", "tq": "TQ", "mbbr": "MBBR",
        "nitrificacao": "Nitrificação", "nitrificação": "Nitrificação", "mab": "MAB",
    }.items():
        txt = re_replace_ci(txt, k, v)
    return txt.strip()

# =============================================================================
# SEMÁFORO — cores por tipo de parâmetro
# =============================================================================
COLOR_OK      = "#43A047"
COLOR_WARN    = "#FB8C00"
COLOR_BAD     = "#E53935"
COLOR_NEUTRAL = "#546E7A"
COLOR_NULL    = "#9E9E9E"


def semaforo_numeric_color(label: str, val: float):
    if val is None or np.isnan(val):
        return COLOR_NULL
    base = _strip_accents(label.lower())

    if "oxigenacao" in base:
        return COLOR_OK if 1 <= val <= 5 else COLOR_BAD

    if re.search(r"\bph\b", base):
        cfg = SEMAFORO_CFG["ph"]["mab" if "mab" in base else "general"]
        if val < cfg["red_low"] or val > cfg["red_high"]:
            return COLOR_BAD
        if cfg["ok_min"] <= val <= cfg["ok_max"]:
            return COLOR_OK
        return COLOR_WARN

    if "sst" in base or re.search(r"\bss\b", base):
        if "saida" in base or "saída" in label.lower():
            cfg = SEMAFORO_CFG["sst_saida"]
            if val <= cfg["green_max"]:  return COLOR_OK
            if val <= cfg["orange_max"]: return COLOR_WARN
            return COLOR_BAD
        return COLOR_NEUTRAL

    if "dqo" in base:
        if "saida" in base or "saída" in label.lower():
            cfg = SEMAFORO_CFG["dqo_saida"]
            if val <= cfg["green_max"]:  return COLOR_OK
            if val <= cfg["orange_max"]: return COLOR_WARN
            return COLOR_BAD
        return COLOR_NEUTRAL

    return None

# =============================================================================
# GAUGES — Caçambas
# =============================================================================

def make_speedometer(val, label):
    nome = _nome_exibicao(label)
    if val is None or np.isnan(val):
        val = 0.0
    color = COLOR_OK if val >= 70 else COLOR_WARN if val >= 30 else COLOR_BAD
    return go.Indicator(
        mode="gauge+number",
        value=float(val),
        number={"suffix": "%", "font": {"size": 28, "color": TEXT_PRIMARY}},
        title={"text": f"<b>{nome}</b>", "font": {"size": 13, "color": TEXT_MUTED}},
        gauge={
            "axis": {"range": [0, 100], "tickfont": {"size": 10, "color": TEXT_MUTED}, "tickcolor": TEXT_MUTED},
            "bar": {"color": color, "thickness": 0.25},
            "bgcolor": "rgba(0,0,0,0)", "borderwidth": 0,
            "steps": [
                {"range": [0,   30],  "color": "rgba(229,57,53,0.12)"},
                {"range": [30,  70],  "color": "rgba(251,140,0,0.12)"},
                {"range": [70, 100],  "color": "rgba(67,160,71,0.12)"},
            ],
            "threshold": {"line": {"color": color, "width": 3}, "thickness": 0.75, "value": float(val)},
        },
        domain={"x": [0, 1], "y": [0.05, 1]},
    )


def _cacamba_valor_radio(numero: int) -> float:
    padrao = _strip_accents(f"cacamba {numero}").lower()
    cols_desta = [col for col in df.columns if padrao in _strip_accents(col.lower())]
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


def render_cacambas_gauges(n_cols: int = 4):
    numeros = set()
    for col in df.columns:
        m = re.search(r"cacamba\s*(\d+)", _strip_accents(col.lower()))
        if m:
            numeros.add(int(m.group(1)))
    if not numeros:
        st.info("Nenhuma caçamba encontrada.")
        return
    for row_start in range(0, len(sorted(numeros)), n_cols):
        row_nums = sorted(numeros)[row_start:row_start + n_cols]
        cols = st.columns(len(row_nums))
        for col_widget, num in zip(cols, row_nums):
            with col_widget:
                val = _cacamba_valor_radio(num)
                fig = go.Figure(make_speedometer(val, f"Nivel da cacamba {num}"))
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

# =============================================================================
# TILES (cards genéricos com semáforo)
# =============================================================================

def _tile_color_and_text(raw_value, val_num: float, label: str, force_neutral_numeric: bool = False):
    if raw_value is None:
        return COLOR_NULL, "—"
    t = _strip_accents(str(raw_value).strip().lower())
    if t in ("ok", "ligado", "aberto", "rodando", "on"):
        return COLOR_OK, str(raw_value).upper()
    if t in ("nok", "falha", "erro", "fechado", "off"):
        return COLOR_BAD, str(raw_value).upper()
    if not np.isnan(val_num):
        units = _units_from_label(label)
        base  = _strip_accents(label.lower())
        if "vazao" in base or "vazão" in base:
            color = COLOR_OK if 0 <= val_num <= 200 else COLOR_BAD
            return color, f"{val_num:.0f} m³/h"
        if not force_neutral_numeric:
            color_rule = semaforo_numeric_color(label, val_num)
            if color_rule is not None:
                return color_rule, f"{val_num:.2f}{units}"
        if force_neutral_numeric:
            return COLOR_NEUTRAL, f"{val_num:.2f}{units}"
        if units == "%":
            fill = COLOR_OK if val_num >= 70 else COLOR_WARN if val_num >= 30 else COLOR_BAD
            return fill, f"{val_num:.1f}%"
        return COLOR_NEUTRAL, f"{val_num:.2f}{units}"
    return COLOR_WARN, str(raw_value)


def _render_tiles_from_cols(title: str, cols_orig: list, n_cols: int = 4,
                             force_neutral_numeric: bool = False):
    cols_orig = sorted(
        [c for c in cols_orig if c and last_valid_raw(df, c) not in (None, "")],
        key=_nome_exibicao,
    )
    if not cols_orig:
        st.info(f"Nenhum item encontrado para: {title}")
        return
    cards_html = ""
    for c in cols_orig:
        raw  = last_valid_raw(df, c)
        val  = to_float_ptbr(raw)
        fill, txt = _tile_color_and_text(raw, val, c, force_neutral_numeric=force_neutral_numeric)
        nome = _nome_exibicao(c)
        cards_html += (
            f'<div class="ete-card" style="background:{fill};">'
            f'<div class="ete-card-value">{txt}</div>'
            f'<div class="ete-card-label">{nome}</div>'
            f'</div>'
        )
    st.markdown(f'<div class="ete-grid">{cards_html}</div>', unsafe_allow_html=True)


def _section(label: str):
    st.markdown(
        f'<div class="ete-section-label">'
        f'<div class="ete-section-dot"></div>'
        f'<span>{label}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

# =============================================================================
# CABEÇALHO (última medição)
# =============================================================================

def _operador_valor_radio() -> str:
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
                m = re.search(r"\[(.+?)\]", col)
                return m.group(1).strip() if m else v
    return "—"


def header_info():
    cand = {"carimbo de data/hora": None, "data": None}
    for c in df.columns:
        k = _strip_accents(c.lower())
        if k in cand:
            cand[k] = c
    c0, c1, c2 = st.columns(3)
    if cand.get("carimbo de data/hora"):
        c0.metric("Último carimbo", str(last_valid_raw(df, cand["carimbo de data/hora"])))
    elif cand.get("data"):
        c0.metric("Data", str(last_valid_raw(df, cand["data"])))
    c1.metric("Operador", _operador_valor_radio())
    c2.metric("Registros", f"{len(df)} linhas")

# =============================================================================
# SOPRADORES — tiles específicos
# =============================================================================

def _render_sopradores_radio(titulo: str, kw_area: list):
    cols = [
        col for col in df.columns
        if "soprador" in _strip_accents(col.lower())
        and any(_strip_accents(k.lower()) in _strip_accents(col.lower()) for k in kw_area)
        and "oxigenac" not in _strip_accents(col.lower())
        and last_valid_raw(df, col) not in (None, "")
    ]
    if cols:
        _section(titulo)
        _render_tiles_from_cols(titulo, cols, n_cols=4)

# =============================================================================
# OXIGENAÇÃO — tiles com leitura de radio
# =============================================================================

def _render_oxigenacao_radio(titulo: str, kw_area: list):
    grupos: dict[str, list] = {}
    for col in df.columns:
        cn = _strip_accents(col.lower())
        if "oxigenac" not in cn:
            continue
        if not any(_strip_accents(k.lower()) in cn for k in kw_area):
            continue
        nome_base = re.sub(r"\s*\[.*?\]", "", col).strip()
        grupos.setdefault(nome_base, []).append(col)

    if not grupos:
        return

    itens: list[tuple[str, float]] = []
    for nome_base, cols_grupo in grupos.items():
        for idx in range(len(df) - 1, -1, -1):
            row = df.iloc[idx]
            for col in cols_grupo:
                v = str(row[col]).strip()
                if v and v.lower() not in ("nan", ""):
                    m = re.search(r"\[(\d+)\]", col)
                    val = float(m.group(1)) if m else None
                    if val is None:
                        try:
                            val = float(v)
                        except Exception:
                            val = None
                    if val is not None:
                        itens.append((nome_base, val))
                    break
            else:
                continue
            break

    if not itens:
        return

    cards_html = ""
    for nome, val in itens:
        color = COLOR_OK if 1 <= val <= 5 else COLOR_BAD
        nome_display = _nome_exibicao(nome)
        cards_html += (
            f'<div class="ete-card" style="background:{color};">'
            f'<div class="ete-card-value">{val:.0f} mg/L</div>'
            f'<div class="ete-card-label">{nome_display}</div>'
            f'</div>'
        )
    st.markdown(f'<div class="ete-grid">{cards_html}</div>', unsafe_allow_html=True)

# =============================================================================
# GRUPOS ADICIONAIS
# =============================================================================

def render_outros_niveis():
    cols = [
        c for c in _filter_columns_by_keywords(cols_lower_noacc, KW_NIVEIS_OUTROS)
        if not any(k in _strip_accents(c.lower()) for k in KW_CACAMBA)
    ]
    if cols:
        _render_tiles_from_cols("Níveis (MAB/TQ de Lodo)", cols, n_cols=3)

def render_vazoes():
    cols = _filter_columns_by_keywords(cols_lower_noacc, KW_VAZAO)
    if cols:
        _render_tiles_from_cols("Vazões", cols, n_cols=3, force_neutral_numeric=True)

def render_ph():
    cols = _filter_columns_by_keywords(cols_lower_noacc, KW_PH)
    if cols:
        _render_tiles_from_cols("pH", cols, n_cols=4)

def render_sst():
    cols = _filter_columns_by_keywords(cols_lower_noacc, KW_SST)
    if cols:
        _render_tiles_from_cols("Sólidos (SS/SST)", cols, n_cols=4)

def render_dqo():
    cols = _filter_columns_by_keywords(cols_lower_noacc, KW_DQO)
    if cols:
        _render_tiles_from_cols("DQO", cols, n_cols=4)

def render_estados():
    cols = _filter_columns_by_keywords(cols_lower_noacc, KW_ESTADOS)
    if cols:
        _render_tiles_from_cols("Estados / Equipamentos", cols, n_cols=3)

# =============================================================================
# RESUMO TEXTO — Sopradores (WhatsApp / Relatório)
# =============================================================================

def _extract_first_int(text: str):
    m = re.search(r"\d+", _strip_accents(text.lower()))
    return int(m.group()) if m else None


def _parse_status_ok_nok(raw) -> str:
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return "—"
    t = _strip_accents(str(raw).strip().lower())
    if t in ("ok", "ligado", "aberto", "rodando", "on"):
        return "OK"
    if t in ("nok", "falha", "erro", "fechado", "off"):
        return "NOK"
    return "—"


def _coletar_status_area(area_keywords: list) -> list[str]:
    cols_area = [
        col for col in df.columns
        if "soprador" in _strip_accents(col.lower())
        and any(_strip_accents(k.lower()) in _strip_accents(col.lower()) for k in area_keywords)
        and not any(_strip_accents(k.lower()) in _strip_accents(col.lower())
                    for k in KW_EXCLUDE_GENERIC + KW_OXIG)
    ]
    itens = [((_extract_first_int(col) or 9999), _parse_status_ok_nok(last_valid_raw(df, col))) for col in cols_area]
    itens.sort(key=lambda x: x[0])
    return [f"{num} ({stt})" for num, stt in itens if num != 9999]


def gerar_resumo_sopradores() -> str:
    mbbr_linha = _coletar_status_area(KW_MBBR)
    nitr_linha = _coletar_status_area(KW_NITR)
    return (
        "Sopradores MBBR:\n"
        + (" ".join(mbbr_linha) if mbbr_linha else "—")
        + "\nSopradores Nitrificação:\n"
        + (" ".join(nitr_linha) if nitr_linha else "—")
    )


def render_resumo_sopradores():
    """Exibe o resumo de sopradores + botão de cópia na tela."""
    _section("Resumo de Sopradores — Relatório / WhatsApp")
    resumo = gerar_resumo_sopradores()
    st.markdown(f'<div class="ete-resumo-box">{resumo}</div>', unsafe_allow_html=True)
    st.text_area(
        "Copie o resumo (Ctrl+A → Ctrl+C):",
        value=resumo,
        height=100,
        key="ta_resumo_sopradores",
        label_visibility="collapsed",
    )

# =============================================================================
# CARTAS DE CONTROLE — helpers
# =============================================================================

def cc_fmt_brl_compacto(v: float) -> str:
    try:
        n = float(v)
    except Exception:
        return str(v)
    sinal = "-" if n < 0 else ""
    n = abs(n)
    if n >= 1_000_000:
        return f"{sinal}R$ {n/1_000_000:.1f} mi".replace(".", ",")
    if n >= 1_000:
        return f"{sinal}R$ {n/1_000:.1f} mil".replace(".", ",")
    return (sinal + "R$ " + f"{n:,.0f}").replace(",", "X").replace(".", ",").replace("X", ".")


def cc_fmt_brl(v, pos=None):
    try:
        return ("R$ " + f"{v:,.0f}").replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(v)


def _indices_extremos_locais(y: pd.Series) -> set:
    idxs, ys = set(), y.reset_index(drop=True)
    for i in range(1, len(ys) - 1):
        if any(pd.isna(ys[j]) for j in (i-1, i, i+1)):
            continue
        if ys[i] > ys[i-1] and ys[i] > ys[i+1]:
            idxs.add(y.index[i])
        if ys[i] < ys[i-1] and ys[i] < ys[i+1]:
            idxs.add(y.index[i])
    return idxs


def _selecionar_indices_para_rotulo(x: pd.Series, y: pd.Series,
                                    LSC: float, LIC: float,
                                    max_labels: int,
                                    incluir_oor: bool,
                                    incluir_extremos: bool,
                                    incluir_primeiro_ultimo: bool) -> list:
    y_clean = y.dropna()
    if y_clean.empty or max_labels <= 0:
        return []
    candidatos = []
    if incluir_oor:
        candidatos.extend(y[(y > LSC) | (y < LIC)].dropna().index.tolist())
    if incluir_extremos:
        candidatos.extend(list(_indices_extremos_locais(y)))
    if incluir_primeiro_ultimo:
        candidatos.extend([y_clean.index[0], y_clean.index[-1]])
    seen, candidatos = set(), [i for i in candidatos if not (i in seen or seen.add(i))]
    if len(candidatos) < max_labels:
        faltam = max_labels - len(candidatos)
        resto  = [idx for idx in y.index if idx not in candidatos and pd.notna(y.loc[idx])]
        candidatos.extend(resto[-faltam:])
    return sorted(set(candidatos), key=lambda i: x.loc[i])


def cc_desenhar_carta(x, y, titulo: str, ylabel: str, mostrar_rotulos: bool = True):
    x = pd.Series(x).reset_index(drop=True)
    y = pd.Series(y).reset_index(drop=True).astype(float)
    x_dt   = pd.to_datetime(x, errors="coerce")
    mask_ok = x_dt.notna() & x_dt.dt.year.between(1900, 2100)
    if mask_ok.sum() == 0:
        st.warning(f"Sem datas válidas para: {titulo}")
        return
    x = x[mask_ok].reset_index(drop=True)
    y = y[mask_ok].reset_index(drop=True)

    y_stats = y.dropna()
    media   = y_stats.mean() if not y_stats.empty else 0.0
    desvio  = y_stats.std(ddof=1) if len(y_stats) > 1 else 0.0
    LSC, LIC = media + 3 * desvio, media - 3 * desvio

    fig, ax = plt.subplots(figsize=(12, 4.8))
    fig.patch.set_facecolor(CHART_BG)
    ax.set_facecolor(CHART_BG)
    ax.plot(x, y, marker="o", color=ACCENT, label="Série", linewidth=2, markersize=5)
    ax.axhline(media, color=ACCENT, linestyle="--", label="Média", alpha=0.7)
    if desvio > 0:
        ax.axhline(LSC, color=COLOR_BAD, linestyle="--", label="LSC (+3σ)", alpha=0.8)
        ax.axhline(LIC, color=COLOR_BAD, linestyle="--", label="LIC (−3σ)", alpha=0.8)
    ax.yaxis.set_major_formatter(FuncFormatter(cc_fmt_brl))
    ax.tick_params(colors=CHART_TEXT, labelsize=9)
    for attr in ("xaxis.label", "yaxis.label", "title"):
        getattr(ax, attr.split(".")[0]).label.set_color(CHART_TEXT) if "." not in attr \
            else getattr(getattr(ax, attr.split(".")[0]), attr.split(".")[1]).set_color(CHART_TEXT)
    ax.title.set_color(CHART_TEXT)
    ax.xaxis.label.set_color(CHART_TEXT)
    ax.yaxis.label.set_color(CHART_TEXT)
    for spine in ax.spines.values():
        spine.set_edgecolor(CHART_GRID)

    if mostrar_rotulos and len(y_stats) > 0:
        idx_rotulos = _selecionar_indices_para_rotulo(
            pd.Series(x), y, LSC, LIC,
            max_labels=cc_lbl_max_points,
            incluir_oor=cc_lbl_out_of_control,
            incluir_extremos=cc_lbl_local_extremes,
            incluir_primeiro_ultimo=cc_lbl_show_first_last,
        )
        idx_rotulos = [i for i in idx_rotulos if pd.notna(y.loc[i]) and y.loc[i] != 0]

        def _fmt(v):
            return cc_fmt_brl_compacto(v) if cc_lbl_compact_format \
                else ("R$ " + f"{v:,.0f}").replace(",", "X").replace(".", ",").replace("X", ".")

        x_num    = pd.to_numeric(pd.to_datetime(pd.Series(x), errors="coerce"), errors="coerce")
        bbox     = dict(boxstyle="round,pad=0.25", fc=BG_CARD, ec=BORDER_COLOR, alpha=0.85) if cc_lbl_bbox else None
        OFFSET_BASE, OFFSET_STEP = 18, 14
        prev_x_num, acum, sinal  = None, 0, 1

        for idx in idx_rotulos:
            if pd.isna(y.loc[idx]):
                continue
            try:
                pos_idx    = list(y.index).index(idx)
                curr_x_num = x_num.iloc[pos_idx] if pos_idx < len(x_num) else None
            except Exception:
                curr_x_num = None

            if prev_x_num is not None and curr_x_num is not None:
                diff = abs(curr_x_num - prev_x_num)
                rng  = x_num.max() - x_num.min() or 1
                acum = acum + 1 if diff / rng < 0.04 else 0
            else:
                acum = 0

            dy    = sinal * (OFFSET_BASE + acum * OFFSET_STEP)
            sinal = sinal * -1
            prev_x_num = curr_x_num

            ax.annotate(
                _fmt(y.loc[idx]),
                (x.loc[idx], y.loc[idx]),
                textcoords="offset points", xytext=(0, dy),
                ha="center", fontsize=cc_lbl_fontsize, rotation=cc_lbl_angle,
                bbox=bbox, color=CHART_TEXT,
                arrowprops=dict(arrowstyle="-", color=TEXT_MUTED, lw=0.8) if abs(dy) > OFFSET_BASE else None,
            )

    ax.set_title(titulo); ax.set_ylabel(ylabel); ax.set_xlabel("Data")
    ax.grid(True, axis="y", alpha=0.2, color=CHART_GRID)
    legend = ax.legend(loc="best", frameon=True)
    legend.get_frame().set_facecolor(BG_CARD)
    legend.get_frame().set_edgecolor(BORDER_COLOR)
    for txt in legend.get_texts():
        txt.set_color(CHART_TEXT)
    plt.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

# =============================================================================
# MICROBIOLOGIA — CETESB L1.025
# =============================================================================

# ---- Tabela 6 ---------------------------------------------------------------
_MICRO_TABELA6 = {
    "flagelados":           {"semaforo": "vermelho", "condicao": "Deficiência de aeração, má depuração e/ou sobrecarga orgânica",                    "recomendacao": "Verificar OD no tanque de aeração. Reduzir carga orgânica ou aumentar aeração."},
    "flagelados_rizopodes": {"semaforo": "laranja",  "condicao": "Lodo jovem — início de operação ou θc baixa",                                       "recomendacao": "Verificar idade do lodo. Sistema em partida ou com sobrecarga hidráulica."},
    "ciliados_pedunculados":{"semaforo": "verde",    "condicao": "Boas condições de depuração (ciliados pedunculados)",                               "recomendacao": "Sistema operando bem. Manter parâmetros atuais."},
    "ciliados_livres":      {"semaforo": "verde",    "condicao": "Boas condições de depuração (ciliados livres)",                                     "recomendacao": "Sistema operando bem."},
    "arcella":              {"semaforo": "verde",    "condicao": "Boa depuração — Arcella sp. presente",                                              "recomendacao": "Indicador positivo. Manter condições atuais."},
    "aspidisca":            {"semaforo": "verde",    "condicao": "Nitrificação ocorrendo — Aspidisca costata",                                        "recomendacao": "Nitrificação ativa. Monitorar amônia e nitrito."},
    "trachelophyllum":      {"semaforo": "laranja",  "condicao": "Idade do lodo (θc) elevada — Trachelophyllum",                                      "recomendacao": "Lodo velho. Avaliar descarte para rejuvenescer a biomassa."},
    "vorticella_microstoma":{"semaforo": "vermelho", "condicao": "Efluente de má qualidade — Vorticella microstoma",                                  "recomendacao": "Investigar causa: sobrecarga, tóxicos ou aeração insuficiente."},
    "aelosoma":             {"semaforo": "laranja",  "condicao": "Excesso de OD — Aelosoma (anelídeo)",                                               "recomendacao": "Reduzir aeração. OD possivelmente > 6 mg/L."},
    "rotiferos":            {"semaforo": "verde",    "condicao": "Lodo maduro com boa sedimentação — Rotíferos presentes",                            "recomendacao": "Indicador positivo de lodo aeróbio maduro."},
    "filamentos":           {"semaforo": "vermelho", "condicao": "Risco de intumescimento filamentoso (bulking)",                                     "recomendacao": "Verificar IVL. Causas: baixo OD, sobrecarga, pH baixo, falta de nutrientes."},
    "nematoides":           {"semaforo": "laranja",  "condicao": "θc elevada — Nematóides presentes",                                                "recomendacao": "Monitorar descarte de lodo."},
    "rizopodes_amebas":     {"semaforo": "laranja",  "condicao": "Lodo jovem ou em transição — Amebas/Rizópodes",                                    "recomendacao": "Verificar idade do lodo e condições operacionais."},
    "flocos_bons":          {"semaforo": "verde",    "condicao": "Flocos bem formados — boa sedimentação",                                            "recomendacao": "Morfologia do lodo adequada. Manter operação."},
    "flocos_dispersos":     {"semaforo": "vermelho", "condicao": "Lodo disperso (pin-point) — má sedimentação",                                       "recomendacao": "Verificar θc, toxicidade e variações de carga."},
    "cianobacterias":       {"semaforo": "vermelho", "condicao": "Cianobactérias — risco de toxicidade",                                              "recomendacao": "ALERTA: possível toxicidade. Verificar origem do afluente."},
    "protozoa_livre":       {"semaforo": "laranja",  "condicao": "Protozoários de vida livre — qualidade moderada",                                   "recomendacao": "Monitorar evolução. Pode indicar lodo jovem ou perturbação."},
}

_COR_MICRO = {"verde": "#43A047", "laranja": "#FB8C00", "vermelho": "#E53935", "cinza": "#546E7A"}

_PESO_CETESB = {
    "ciliados_pedunculados": +3, "ciliados_livres": +2, "rotiferos": +3,
    "arcella": +2, "aspidisca": +2, "flocos_bons": +2, "nematoides": +1,
    "trachelophyllum": 0, "aelosoma": -1, "protozoa_livre": 0,
    "rizopodes_amebas": -1, "flagelados_rizopodes": -1, "flocos_dispersos": -2,
    "flagelados": -3, "vorticella_microstoma": -3, "filamentos": -2,
}

# ---- Gestão de chaves Gemini ------------------------------------------------

def _carregar_chaves_gemini() -> list:
    if not hasattr(st, "secrets"):
        return []
    return [v for nome in ["GOOGLE_API_KEY", "GOOGLE_API_KEY_2", "GOOGLE_API_KEY_3", "GOOGLE_API_KEY_4"]
            if (v := st.secrets.get(nome, ""))]

# ---- Cota diária / por minuto -----------------------------------------------
_COTA_FILE = "/tmp/gemini_cota_micro.json"


def _brt_now():
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone(timedelta(hours=-3)))


def _cota_carregar() -> dict:
    agora      = _brt_now()
    reset_hoje = agora.replace(hour=4, minute=0, second=0, microsecond=0)
    if agora < reset_hoje:
        from datetime import timedelta
        reset_hoje -= timedelta(days=1)
    padrao = {"total_dia": 0, "ultimo_reset": reset_hoje.isoformat(), "historico_min": []}
    if not os.path.exists(_COTA_FILE):
        return padrao
    try:
        with open(_COTA_FILE) as f:
            dados = json.load(f)
        from datetime import datetime
        if datetime.fromisoformat(dados["ultimo_reset"]) < reset_hoje:
            dados.update({"total_dia": 0, "ultimo_reset": reset_hoje.isoformat(), "historico_min": []})
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
    agora = _brt_now().timestamp()
    dados = _cota_carregar()
    dados["total_dia"] = dados.get("total_dia", 0) + 1
    hist = [t for t in dados.get("historico_min", []) if agora - t < 60]
    hist.append(agora)
    dados["historico_min"] = hist
    _cota_salvar(dados)
    return dados["total_dia"], len(hist)


def _cota_status() -> dict:
    agora    = _brt_now().timestamp()
    dados    = _cota_carregar()
    hist     = [t for t in dados.get("historico_min", []) if agora - t < 60]
    n_chaves = len(_carregar_chaves_gemini())
    lim      = max(n_chaves, 1)
    return {
        "total_dia": dados.get("total_dia", 0), "limite_dia": 1500 * lim,
        "req_min": len(hist), "limite_min": 15 * lim, "n_chaves": n_chaves,
    }


def _cota_widget():
    from datetime import timedelta
    agora = _brt_now()
    reset = agora.replace(hour=4, minute=0, second=0, microsecond=0)
    if agora >= reset:
        reset += timedelta(days=1)
    hh = int((reset - agora).total_seconds() // 3600)
    mm = int(((reset - agora).total_seconds() % 3600) // 60)
    s   = _cota_status()
    pct = s["total_dia"] / s["limite_dia"] if s["limite_dia"] else 0
    cor = "🟢" if pct < 0.6 else ("🟡" if pct < 0.85 else "🔴")
    with st.expander(f"{cor} Cota Gemini — {s['total_dia']}/{s['limite_dia']} req hoje", expanded=False):
        c1, c2, c3 = st.columns(3)
        c1.metric("Usadas hoje",   s["total_dia"],  delta=f"/{s['limite_dia']}")
        c2.metric("Req/min agora", s["req_min"],    delta=f"/{s['limite_min']} limite")
        c3.metric("Chaves ativas", s["n_chaves"])
        st.progress(min(pct, 1.0))
        st.caption(f"Reset em {hh}h {mm}min (04:00 BRT) · Dados aproximados por sessão")

# ---- Extração de frames (vídeo) ---------------------------------------------

def _extrair_frames_video(video_bytes: bytes) -> list:
    frames_b64 = []
    with tempfile.TemporaryDirectory() as tmpdir:
        vpath = os.path.join(tmpdir, "video.mp4")
        with open(vpath, "wb") as f:
            f.write(video_bytes)
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", vpath],
            capture_output=True, text=True,
        )
        try:
            duration = float(result.stdout.strip())
        except Exception:
            duration = 10.0
        for i, t in enumerate([duration * 0.33, duration * 0.66]):
            fpath = os.path.join(tmpdir, f"frame_{i:02d}.jpg")
            subprocess.run(
                ["ffmpeg", "-ss", str(t), "-i", vpath,
                 "-vframes", "1", "-vf", "scale=768:-1", "-q:v", "5", fpath, "-y"],
                capture_output=True,
            )
            if os.path.exists(fpath):
                with open(fpath, "rb") as fimg:
                    frames_b64.append(base64.b64encode(fimg.read()).decode())
    return frames_b64

# ---- Compressão de imagem ---------------------------------------------------

def _comprimir_b64(b64: str, max_lado: int = 1024, qualidade: int = 82) -> str:
    try:
        from PIL import Image
        data = base64.b64decode(b64)
        img  = Image.open(io.BytesIO(data)).convert("RGB")
        w, h = img.size
        if max(w, h) > max_lado:
            ratio = max_lado / max(w, h)
            img   = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=qualidade, optimize=True)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return b64

# ---- Prompt do sistema ------------------------------------------------------
_SYSTEM_PROMPT_MICRO = """Você é um especialista em microbiologia de lodos ativados da norma CETESB L1.025.

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

# ---- Chamada à API Gemini ---------------------------------------------------

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key="
_MAX_503     = 3
_MAX_RPM_RETRY = 2      # tentativas com espera de 65 s cada


def _chamar_gemini(frames_b64: list, params_dia: dict) -> dict:
    chaves = _carregar_chaves_gemini()
    if not chaves:
        raise RuntimeError("Nenhuma chave GOOGLE_API_KEY encontrada nos Secrets do Streamlit.")

    ctx = ""
    if params_dia:
        ctx = "\n\nParâmetros operacionais do dia:\n" + \
              "".join(f"  - {k}: {v}\n" for k, v in params_dia.items() if v) + \
              "\nConsidere esses valores ao interpretar os organismos encontrados."

    parts = [{"inline_data": {"mime_type": "image/jpeg", "data": _comprimir_b64(b64)}} for b64 in frames_b64]
    parts.append({"text": (
        f"Analise estas imagens de microscópio de lodo ativado de ETE.{ctx}\n\n"
        "IMPORTANTE: Identifique todos os organismos/estruturas visíveis conforme CETESB L1.025.\n"
        "Retorne SOMENTE JSON puro conforme as instruções."
    )})

    payload = {
        "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT_MICRO}]},
        "contents":           [{"parts": parts}],
        "generationConfig":   {"temperature": 0.1, "maxOutputTokens": 1000},
    }

    chaves_esgotadas: set = set()
    idx              = 0
    retries_servidor = 0
    retries_rpm      = 0

    while True:
        # --- pula chaves com cota diária esgotada ---
        tentativas = 0
        while idx in chaves_esgotadas:
            idx = (idx + 1) % len(chaves)
            tentativas += 1
            if tentativas >= len(chaves):
                raise RuntimeError(
                    "COTA_DIARIA_ESGOTADA: todas as chaves atingiram o limite diário.\n"
                    "Aguarde o reset às 04:00 BRT ou adicione mais chaves nos Secrets."
                )

        try:
            resp = requests.post(
                _GEMINI_URL + chaves[idx],
                headers={"Content-Type": "application/json"},
                json=payload, timeout=90,
            )

            # --- 429: rate-limit ---
            if resp.status_code == 429:
                corpo = ""
                try:
                    corpo = str(resp.json()).lower()
                except Exception:
                    corpo = resp.text.lower()

                if "daily" in corpo or "per_day" in corpo:
                    chaves_esgotadas.add(idx)
                    idx = (idx + 1) % len(chaves)
                    _time.sleep(1)
                    continue

                # Rate limit por minuto — countdown visual
                retries_rpm += 1
                if retries_rpm > _MAX_RPM_RETRY:
                    raise RuntimeError("RATE_LIMIT_MIN")
                espera = 65
                ph = st.empty()
                for seg in range(espera, 0, -1):
                    ph.info(
                        f"⏳ Rate limit (req/min). Tentando novamente em **{seg}s** "
                        f"(tentativa {retries_rpm}/{_MAX_RPM_RETRY})…"
                    )
                    _time.sleep(1)
                ph.empty()
                continue

            # --- 503: servidor ocupado ---
            if resp.status_code == 503:
                retries_servidor += 1
                if retries_servidor <= _MAX_503:
                    espera = 5 * retries_servidor
                    st.toast(f"Servidor ocupado, aguardando {espera}s… ({retries_servidor}/{_MAX_503})")
                    _time.sleep(espera)
                    continue
                resp.raise_for_status()

            resp.raise_for_status()
            break

        except requests.exceptions.Timeout:
            retries_servidor += 1
            if retries_servidor <= _MAX_503:
                st.toast(f"Timeout — tentando novamente ({retries_servidor}/{_MAX_503})…")
                _time.sleep(5)
                continue
            raise

    # --- parse da resposta ---
    try:
        texto = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        return {"organismos": [], "qualidade_imagem": "ruim",
                "observacoes_gerais": f"Resposta inesperada: {str(resp.json())[:200]}"}

    texto = texto.strip()
    for fence in ("```json", "```JSON", "```"):
        texto = texto.replace(fence, "")
    texto = texto.strip()

    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", texto, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
        return {"organismos": [], "qualidade_imagem": "ruim",
                "observacoes_gerais": f"Erro ao parsear JSON. Texto: {texto[:300]}"}

# ---- Diagnóstico CETESB -----------------------------------------------------

def _diagnostico_cetesb(organismos: list) -> dict:
    if not organismos:
        return {"qualidade": "indeterminada", "descricao": "Nenhum organismo identificado.",
                "cor": _COR_MICRO["cinza"], "acoes": ["Repetir análise com imagens de melhor qualidade."]}

    chaves   = {o.get("chave", "") for o in organismos}
    conf_map = {}
    for o in organismos:
        ch = o.get("chave", "")
        conf_map[ch] = max(conf_map.get(ch, 0), o.get("confianca", 0.5))

    if "cianobacterias" in chaves:
        return {"qualidade": "critico", "cor": _COR_MICRO["vermelho"],
                "descricao": "Cianobactérias detectadas — risco de toxicidade.",
                "acoes": ["Verificar origem do afluente.", "Alertar equipe de operação imediatamente."]}

    if "flocos_dispersos" in chaves and "flocos_bons" not in chaves:
        return {"qualidade": "ruim", "cor": _COR_MICRO["vermelho"],
                "descricao": "Lodo totalmente disperso (pin-point) — má sedimentação.",
                "acoes": ["Verificar θc.", "Investigar tóxicos no afluente."]}

    score = sum(_PESO_CETESB.get(ch, 0) * conf for ch, conf in conf_map.items())

    acoes = []
    if "filamentos"          in chaves: acoes.append("Monitorar IVL — filamentos presentes, avaliar risco de bulking.")
    if "flagelados"          in chaves: acoes.append("Verificar OD no tanque — flagelados indicam deficiência de aeração.")
    if "vorticella_microstoma" in chaves: acoes.append("Investigar sobrecarga, tóxicos ou aeração insuficiente.")
    if "aelosoma"            in chaves: acoes.append("OD possivelmente elevado (>6 mg/L) — reduzir aeração.")

    if score >= 3:
        return {"qualidade": "boa",     "cor": _COR_MICRO["verde"],
                "descricao": "Sistema estável com organismos indicadores de boa depuração.",
                "acoes": acoes or ["Manter parâmetros operacionais."]}
    if score >= 0:
        return {"qualidade": "regular", "cor": _COR_MICRO["laranja"],
                "descricao": "Sistema em equilíbrio — organismos mistos, monitorar evolução.",
                "acoes": acoes or ["Verificar idade do lodo e parâmetros operacionais."]}
    if score >= -2:
        return {"qualidade": "ruim",    "cor": _COR_MICRO["vermelho"],
                "descricao": "Organismos indicadores de problema — verificar operação.",
                "acoes": acoes or ["Verificar OD, carga orgânica e θc."]}
    return {"qualidade": "critico",     "cor": _COR_MICRO["vermelho"],
            "descricao": "Múltiplos indicadores negativos — problema sério no sistema.",
            "acoes": acoes or ["Acionar equipe técnica para revisão completa."]}

# ---- Relatório copiável -----------------------------------------------------

def _gerar_relatorio_micro(organismos: list, diag: dict,
                            params_dia: dict, confianca_media: float) -> str:
    agora = _brt_now().strftime("%d/%m/%Y %H:%M")
    linhas = [
        "=" * 52,
        "   RELATÓRIO MICROBIOLÓGICO — LODO ATIVADO",
        f"   Data/Hora: {agora}",
        "   Norma: CETESB L1.025 + IA (Gemini)",
        "=" * 52, "",
        f"QUALIDADE DO PROCESSO: {diag['qualidade'].upper()}",
        f"Diagnóstico: {diag['descricao']}",
        f"Confiança média da análise: {confianca_media*100:.0f}%", "",
    ]
    if params_dia:
        linhas.append("PARÂMETROS DO DIA:")
        linhas.extend(f"  {k}: {v}" for k, v in params_dia.items() if v)
        linhas.append("")

    linhas.append(f"MICRORGANISMOS IDENTIFICADOS ({len(organismos)}):")
    for o in organismos:
        meta = _MICRO_TABELA6.get(o.get("chave", ""), {})
        linhas += [
            f"  • {o.get('nome','?')} ({o.get('grupo','')})",
            f"    Observação: {o.get('descricao','')}",
            *([ f"    Indicação CETESB: {meta['condicao']}"] if meta.get("condicao") else []),
            f"    Confiança da IA: {int(o.get('confianca',0)*100)}%", "",
        ]

    linhas.append("DIAGNÓSTICO CETESB L1.025 (Tabela 6):")
    for ch in {o.get("chave","") for o in organismos if o.get("chave") in _MICRO_TABELA6}:
        meta     = _MICRO_TABELA6[ch]
        semaforo = {"verde": "[✓]", "laranja": "[!]", "vermelho": "[✗]"}.get(meta["semaforo"], "[-]")
        linhas.append(f"  {semaforo} {meta['condicao']}")
        if meta["semaforo"] != "verde":
            linhas.append(f"      → {meta['recomendacao']}")
    linhas += [
        "", "AÇÕES RECOMENDADAS:",
        *[f"  • {a}" for a in diag["acoes"]],
        "", "Análise gerada por IA + regras CETESB L1.025",
        "Confirme sempre com análise laboratorial qualificada.",
    ]
    return "\n".join(linhas)

# ---- Interface principal -----------------------------------------------------

def render_microbiologia():
    st.markdown(
        '<hr style="border:none;border-top:1px solid var(--border);margin:2rem 0 1.5rem;">',
        unsafe_allow_html=True,
    )
    _section("Microbiologia do Lodo — Análise por IA (CETESB L1.025)")
    st.caption(
        "Suba fotos ou vídeo do microscópio. "
        "A IA identifica os organismos e gera relatório conforme a Tabela 6 da L1.025."
    )

    _cota_widget()

    # --- Parâmetros do dia como contexto para o prompt ---
    params_dia: dict = {}
    for kws, label in [
        (["ph mbbr", "ph mab"],         "pH"),
        (["oxigenac", "oxigenação"],     "OD Nitrificação"),
        (["sst nitrif"],                 "SST Nitrificação"),
        (["dqo saida", "dqo saída"],     "DQO Saída"),
    ]:
        for col in df.columns:
            if any(k in _strip_accents(col.lower()) for k in kws):
                v = last_valid_raw(df, col)
                if v:
                    params_dia[label] = str(v)
                    break

    if params_dia:
        st.caption("Parâmetros do último registro (contexto para a IA):")
        cols_p = st.columns(len(params_dia))
        for i, (k, v) in enumerate(params_dia.items()):
            cols_p[i].metric(k, v)

    # --- Modo de upload ---
    st.subheader("Upload de Imagens ou Vídeo do Microscópio")
    modo = st.radio(
        "Formato:",
        ["📷 Fotos (JPG/PNG)", "🎥 Vídeo (MP4/MOV)"],
        horizontal=True, key="micro_modo_upload",
    )
    frames_b64: list = []

    if "Fotos" in modo:
        imgs = st.file_uploader(
            "Selecione até 3 fotos do microscópio",
            type=["jpg", "jpeg", "png", "bmp", "tiff"],
            accept_multiple_files=True, key="micro_upload_fotos",
            help="O sistema usa as 2 primeiras imagens para economizar cota da API.",
        )
        if imgs:
            frames_b64 = [base64.b64encode(img.read()).decode() for img in imgs[:2]]
            cols_img = st.columns(min(len(frames_b64), 2))
            for i, b64 in enumerate(frames_b64):
                cols_img[i].image(base64.b64decode(b64), caption=f"Imagem {i+1}", use_container_width=True)
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
            with st.spinner("Extraindo frames do vídeo…"):
                try:
                    frames_b64 = _extrair_frames_video(video_bytes)
                    if frames_b64:
                        st.success(f"{len(frames_b64)} frame(s) extraído(s).")
                        cols_img = st.columns(min(len(frames_b64), 2))
                        for i, b64 in enumerate(frames_b64):
                            cols_img[i].image(base64.b64decode(b64), caption=f"Frame {i+1}", use_container_width=True)
                    else:
                        st.error("Não foi possível extrair frames. Use o modo Fotos.")
                except Exception as e:
                    st.error(f"ffmpeg indisponível neste servidor. Use o modo Fotos.\n\nDetalhe: {e}")

    # --- Botão de análise ---
    if frames_b64:
        if st.button("🔬 Analisar com IA + Regras CETESB", type="primary", use_container_width=True):
            if not _carregar_chaves_gemini():
                st.error("Chave GOOGLE_API_KEY não encontrada nos Secrets do Streamlit.")
                st.stop()
            with st.status("Analisando imagens…", expanded=True) as status_box:
                try:
                    st.write(f"🤖 Enviando {len(frames_b64)} imagem(ns) para o Gemini…")
                    resultado = _chamar_gemini(frames_b64, params_dia)
                    _cota_incrementar()

                    organismos = resultado.get("organismos", [])
                    qualidade  = resultado.get("qualidade_imagem", "regular")
                    obs        = resultado.get("observacoes_gerais", "")

                    if not organismos:
                        st.warning("A IA não identificou organismos. Tente com foto mais nítida.")

                    st.write("📋 Aplicando regras CETESB L1.025 (Tabela 6)…")
                    diag             = _diagnostico_cetesb(organismos)
                    confianca_media  = (sum(o.get("confianca", 0) for o in organismos) / len(organismos)
                                        if organismos else 0.0)

                    st.session_state["micro_resultado"] = {
                        "organismos": organismos, "qualidade_img": qualidade,
                        "obs_gerais": obs, "diag": diag,
                        "confianca_media": confianca_media, "params_dia": params_dia,
                    }
                    status_box.update(label="✅ Análise concluída!", state="complete")

                except RuntimeError as e:
                    msg = str(e)
                    if "COTA_DIARIA_ESGOTADA" in msg:
                        st.warning(
                            "⚠️ **Cota diária da API esgotada em todas as chaves.**\n\n"
                            "Aguarde o reset às **04:00 BRT** ou adicione mais chaves nos Secrets."
                        )
                    elif "RATE_LIMIT_MIN" in msg:
                        st.warning(
                            "⏳ **Muitas requisições por minuto.**\n\n"
                            "Aguarde **1 minuto** e tente novamente. Isso não consome cota diária."
                        )
                    else:
                        st.error(f"Erro: {msg}")
                    st.stop()
                except Exception as e:
                    import traceback
                    st.error(f"Erro inesperado: {e}")
                    st.code(traceback.format_exc())
                    st.stop()

    # --- Exibição dos resultados ---
    r = st.session_state.get("micro_resultado")
    if not r:
        st.info("Faça upload de imagens e clique em **Analisar** para ver o diagnóstico.")
        return

    organismos      = r["organismos"]
    qualidade_img   = r["qualidade_img"]
    obs_gerais      = r["obs_gerais"]
    diag            = r["diag"]
    confianca_media = r["confianca_media"]
    params_dia_r    = r["params_dia"]

    if qualidade_img == "ruim":
        st.info("💡 Qualidade de imagem baixa — confiança reduzida.")
    elif qualidade_img == "regular":
        st.info("Qualidade regular das imagens.")
    if obs_gerais:
        st.caption(f"Observação da IA: {obs_gerais}")

    if not organismos:
        st.warning("Nenhum organismo identificado.")
        if st.button("🔄 Limpar e tentar novamente", key="micro_btn_limpar_vazio"):
            del st.session_state["micro_resultado"]
            st.rerun()
        return

    # Métricas
    st.subheader("Resumo da Análise")
    m1, m2, m3 = st.columns(3)
    m1.metric("Organismos identificados", len(organismos))
    m2.metric("Confiança média",          f"{confianca_media*100:.0f}%")
    m3.metric("Qualidade da imagem",      qualidade_img.capitalize())

    # Card de qualidade
    st.subheader("Qualidade Estimada do Lodo / Processo")
    st.markdown(
        f'<div style="background:{diag["cor"]};border-radius:10px;padding:16px 20px;'
        f'margin-bottom:12px;color:white;">'
        f'<div style="font-size:18px;font-weight:700">Qualidade: {diag["qualidade"].upper()}</div>'
        f'<div style="font-size:13px;margin-top:6px;opacity:0.92">{diag["descricao"]}</div>'
        f'<div style="font-size:11px;margin-top:8px;opacity:0.75;font-family:monospace">'
        f'Análise: IA Gemini + Tabela 6 CETESB L1.025</div></div>',
        unsafe_allow_html=True,
    )
    with st.expander("📋 Ações Recomendadas", expanded=True):
        for a in diag["acoes"]:
            st.markdown(f"• {a}")

    # Cards por organismo
    st.subheader(f"Organismos Detectados ({len(organismos)})")
    cols_org = st.columns(2)
    for i, o in enumerate(organismos):
        meta  = _MICRO_TABELA6.get(o.get("chave",""), {"semaforo":"cinza","condicao":"","recomendacao":""})
        cor_o = _COR_MICRO.get(meta.get("semaforo","cinza"), _COR_MICRO["cinza"])
        conf  = o.get("confianca", 0.0)
        barra = "█" * int(conf * 10) + "░" * (10 - int(conf * 10))
        icon  = {"verde":"✅","laranja":"⚠️","vermelho":"🔴","cinza":"🔍"}.get(meta.get("semaforo","cinza"),"🔍")
        cond_html = (f'<div style="font-size:11px;margin-top:4px;opacity:0.85">📋 {meta["condicao"]}</div>'
                     if meta.get("condicao") else "")
        with cols_org[i % 2]:
            st.markdown(
                f'<div style="background:{cor_o};border-radius:8px;padding:12px 14px;'
                f'margin-bottom:8px;color:white;">'
                f'<div style="font-size:15px;font-weight:500">{icon} {o.get("nome","—")}</div>'
                f'<div style="font-size:11px;opacity:0.85">{o.get("grupo","")}</div>'
                f'<div style="font-size:12px;margin-top:6px">{o.get("descricao","")}</div>'
                f'{cond_html}'
                f'<div style="font-size:11px;margin-top:6px;opacity:0.8">'
                f'🎯 Confiança: {barra} {conf*100:.0f}%</div></div>',
                unsafe_allow_html=True,
            )

    # Diagnóstico Tabela 6
    st.subheader("Diagnóstico CETESB L1.025 — Tabela 6")
    for ch in {o.get("chave","") for o in organismos if o.get("chave") in _MICRO_TABELA6}:
        meta = _MICRO_TABELA6[ch]
        msg  = f"**{meta['condicao']}**\n\n→ {meta['recomendacao']}"
        if   meta["semaforo"] == "vermelho": st.error(msg)
        elif meta["semaforo"] == "laranja":  st.warning(msg)
        else:                                st.success(f"**{meta['condicao']}**")

    # Relatório copiável
    st.subheader("Relatório Completo — Copiar para WhatsApp / Laudo")
    relatorio = _gerar_relatorio_micro(organismos, diag, params_dia_r, confianca_media)
    st.text_area(
        "Selecione tudo (Ctrl+A) e copie (Ctrl+C):",
        value=relatorio, height=300,
        key="micro_ta_relatorio", label_visibility="collapsed",
    )
    st.caption("Ctrl+A → Ctrl+C para copiar o relatório completo.")

    if st.button("🔄 Limpar e analisar novamente", key="micro_btn_limpar"):
        del st.session_state["micro_resultado"]
        st.rerun()

# =============================================================================
# CARTAS DE CONTROLE — CUSTOS
# =============================================================================

with st.sidebar:
    gid_input = st.text_input("GID da aba de gastos", value="668859455")
CC_GID_GASTOS = gid_input.strip() or "668859455"
CC_URL_GASTOS = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={CC_GID_GASTOS}"
)


@st.cache_data(ttl=900, show_spinner=False)
def cc_baixar_csv_bruto(url: str, timeout: int = 20) -> pd.DataFrame:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    df_txt = pd.read_csv(io.StringIO(resp.text), dtype=str, keep_default_na=False, header=None)
    df_txt.columns = [str(c).strip() for c in df_txt.columns]
    return df_txt


def _cc_strip(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s))
    return "".join(ch for ch in s if not unicodedata.combining(ch)).lower().strip()


def cc_find_header_row(df_txt: pd.DataFrame, max_scan: int = 120):
    kws_custo = ["custo", "custos", "gasto", "gastos", "valor", "$"]
    for i in range(min(len(df_txt), max_scan)):
        row_vals = [_cc_strip(x) for x in df_txt.iloc[i].tolist()]
        if any("data" in v for v in row_vals) and any(any(kw in v for kw in kws_custo) for v in row_vals):
            return i
    return None


def cc_parse_currency_br(series: pd.Series) -> pd.Series:
    s = (series.astype(str)
         .str.replace("\u00A0", " ", regex=False)
         .str.replace("R$", "", regex=False)
         .str.replace(" ", "", regex=False)
         .str.replace(".", "", regex=False)
         .str.replace(",", ".", regex=False)
         .apply(lambda x: re.sub(r"[^0-9.\-]", "", x)))
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
    label = (label or fallback).replace("\n", " ").strip()
    return label[:77] + "..." if len(label) > 80 else label


def cc_ultimo_valido_positivo(ser: pd.Series) -> float:
    s = pd.to_numeric(ser, errors="coerce").dropna()
    if s.empty:
        return 0.0
    nz = s[s != 0]
    return float(nz.iloc[-1]) if not nz.empty else float(s.iloc[-1])


def cc_metricas_item(df_item: pd.DataFrame):
    mask_nz = df_item["CUSTO"].fillna(0) != 0
    idx_ref = mask_nz[mask_nz].index[-1] if mask_nz.any() else df_item.index[-1]
    ultimo  = cc_ultimo_valido_positivo(df_item["CUSTO"])

    df_tmp = df_item.copy()
    iso    = df_tmp["DATA"].dt.isocalendar()
    df_tmp["__sem__"] = iso.week.astype(int)
    df_tmp["__anoiso__"] = iso.year.astype(int)
    ult_sem, ult_ano = int(df_tmp.loc[idx_ref, "__sem__"]), int(df_tmp.loc[idx_ref, "__anoiso__"])
    custo_semana = df_tmp[(df_tmp["__sem__"] == ult_sem) & (df_tmp["__anoiso__"] == ult_ano)]["CUSTO"].sum()

    df_tmp["__mes__"] = df_tmp["DATA"].dt.month
    df_tmp["__ano__"] = df_tmp["DATA"].dt.year
    ult_mes, ult_ano2 = int(df_tmp.loc[idx_ref, "__mes__"]), int(df_tmp.loc[idx_ref, "__ano__"])
    custo_mes = df_tmp[(df_tmp["__mes__"] == ult_mes) & (df_tmp["__ano__"] == ult_ano2)]["CUSTO"].sum()

    return ultimo, custo_semana, custo_mes


def _fmt_brl(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# =============================================================================
# LAYOUT PRINCIPAL
# =============================================================================

st.markdown("""
<div class="ete-header">
  <div class="ete-title">Dashboard Operacional ETE</div>
  <div class="ete-subtitle">Monitoramento em tempo real — dados via Google Forms</div>
</div>
""", unsafe_allow_html=True)

header_info()

# ---- Caçambas ----------------------------------------------------------------
_section("Nível das Caçambas")
render_cacambas_gauges()

# ---- Válvulas ----------------------------------------------------------------
cols_valvulas = [
    col for col in df.columns
    if ("valvula" in _strip_accents(col.lower()) or "válvula" in col.lower())
    and last_valid_raw(df, col) not in (None, "")
]
if cols_valvulas:
    _section("Válvulas — MBBR")
    _render_tiles_from_cols("Válvulas – MBBR", cols_valvulas, n_cols=4)

# ---- Sopradores --------------------------------------------------------------
_render_sopradores_radio("Sopradores — MBBR",         KW_MBBR)
_render_sopradores_radio("Sopradores — Nitrificação",  KW_NITR)

# ---- Oxigenação --------------------------------------------------------------
_section("Oxigenação — MBBR")
_render_oxigenacao_radio("Oxigenação – MBBR", KW_MBBR)
_section("Oxigenação — Nitrificação")
_render_oxigenacao_radio("Oxigenação – Nitrificação", KW_NITR)

# ---- Indicadores adicionais --------------------------------------------------
_section("Níveis — MAB / TQ de Lodo");  render_outros_niveis()
_section("Vazões");                      render_vazoes()
_section("pH");                          render_ph()
_section("Sólidos — SS / SST");          render_sst()
_section("DQO");                         render_dqo()
_section("Estados / Equipamentos");      render_estados()

# ---- Resumo de sopradores (WhatsApp) -----------------------------------------
render_resumo_sopradores()

# =============================================================================
# CARTAS DE CONTROLE — CUSTOS
# =============================================================================
st.markdown('<hr style="border:none;border-top:1px solid var(--border);margin:2rem 0 1.5rem;">', unsafe_allow_html=True)
st.markdown('<div class="ete-cost-header">📈 Cartas de Controle — Custo (R$)</div>', unsafe_allow_html=True)

if st.button("Recarregar cartas"):
    st.cache_data.clear()
    st.rerun()

with st.status("Carregando dados das cartas…", expanded=True) as status_cc:
    try:
        st.write("• Baixando CSV do Google Sheets…")
        cc_df_raw = cc_baixar_csv_bruto(CC_URL_GASTOS)
        st.write(f"• CSV bruto: {cc_df_raw.shape[0]}L × {cc_df_raw.shape[1]}C")
        st.write("• Detectando linha de cabeçalho…")
        cc_hdr = cc_find_header_row(cc_df_raw)
        if cc_hdr is None:
            st.error("Não encontrei cabeçalho com DATA e CUSTOS na aba informada.")
            st.stop()
        cc_header_vals = [str(x).strip() for x in cc_df_raw.iloc[cc_hdr].tolist()]
        cc_df_all      = cc_df_raw.iloc[cc_hdr + 1:].copy()
        cc_df_all.columns = cc_header_vals
        cc_df_all = cc_df_all.loc[:, [c.strip() != "" for c in cc_df_all.columns]]
        status_cc.update(label="Dados carregados ✅", state="complete")
    except requests.exceptions.Timeout:
        st.error("Timeout ao acessar o Google Sheets. Tente novamente.")
        st.stop()
    except Exception as e:
        st.error(f"Erro: {e}")
        st.stop()

cc_norm_cols = [_cc_strip(c) for c in cc_df_all.columns]
CC_KW_INC  = ["custo", "custos", "gasto", "gastos", "valor", "$"]
CC_KW_EXC  = ["media", "média", "status", "automatic", "automatico", "automático", "meta"]
cc_cost_idx = [i for i, nc in enumerate(cc_norm_cols)
               if any(k in nc for k in CC_KW_INC) and not any(k in nc for k in CC_KW_EXC)]
cc_data_idx = [i for i, nc in enumerate(cc_norm_cols) if "data" in nc]

if not cc_cost_idx:
    st.error("Nenhuma coluna de CUSTO/GASTO/VALOR válida encontrada.")
    st.write("Colunas disponíveis:", list(cc_df_all.columns))
    st.stop()
if not cc_data_idx:
    st.error("Nenhuma coluna de DATA encontrada.")
    st.stop()

cc_items, cc_seen = [], set()
for cost_idx in cc_cost_idx:
    left_data = [i for i in cc_data_idx if i <= cost_idx]
    data_idx  = max(left_data) if left_data else min(cc_data_idx, key=lambda i: abs(i - cost_idx))
    df_item   = pd.DataFrame({
        "DATA":  pd.to_datetime(cc_df_all.iloc[:, data_idx].astype(str), errors="coerce", dayfirst=True),
        "CUSTO": cc_parse_currency_br(cc_df_all.iloc[:, cost_idx]),
    }).dropna(subset=["DATA", "CUSTO"]).sort_values("DATA")
    if df_item.empty:
        continue
    label = cc_guess_item_label(cc_df_raw, cc_hdr, cost_idx, fallback=cc_df_all.columns[cost_idx])
    if _cc_strip(label) in cc_seen:
        continue
    cc_seen.add(_cc_strip(label))
    cc_items.append({
        "label": label, "cost_name": cc_df_all.columns[cost_idx],
        "data_name": cc_df_all.columns[data_idx], "df": df_item,
    })

if not cc_items:
    st.warning("Nenhum item com dados válidos encontrado.")
    st.stop()

cc_sel = st.multiselect("Itens para exibir", [it["label"] for it in cc_items],
                         default=[it["label"] for it in cc_items])
cc_rotulos = st.checkbox("Mostrar rótulos nas cartas", value=True)
cc_items   = [it for it in cc_items if it["label"] in cc_sel]

if not cc_items:
    st.info("Selecione pelo menos um item.")
    st.stop()

for tab, it in zip(st.tabs([it["label"] for it in cc_items]), cc_items):
    with tab:
        df_item = it["df"]
        ultimo, custo_semana, custo_mes = cc_metricas_item(df_item)
        c1, c2, c3 = st.columns(3)
        c1.metric("Custo do Dia",     _fmt_brl(ultimo))
        c2.metric("Custo da Semana",  _fmt_brl(custo_semana))
        c3.metric("Custo do Mês",     _fmt_brl(custo_mes))

        df_day = df_item.groupby("DATA", as_index=False)["CUSTO"].sum().sort_values("DATA")
        df_week = (df_item.assign(semana=df_item["DATA"].dt.to_period("W-MON"))
                          .groupby("semana", as_index=False)["CUSTO"].sum())
        df_week["Data"] = df_week["semana"].dt.start_time
        df_month = (df_item.assign(mes=df_item["DATA"].dt.to_period("M"))
                           .groupby("mes", as_index=False)["CUSTO"].sum())
        df_month["Data"] = df_month["mes"].dt.to_timestamp()

        st.subheader("Carta Diária")
        cc_desenhar_carta(df_day["DATA"], df_day["CUSTO"],
                          f"Custo Diário (R$) — {it['label']}", "R$", mostrar_rotulos=cc_rotulos)
        st.subheader("Carta Semanal (ISO)")
        cc_desenhar_carta(df_week["Data"], df_week["CUSTO"],
                          f"Custo Semanal (R$) — {it['label']}", "R$", mostrar_rotulos=cc_rotulos)
        st.subheader("Carta Mensal")
        cc_desenhar_carta(df_month["Data"], df_month["CUSTO"],
                          f"Custo Mensal (R$) — {it['label']}", "R$", mostrar_rotulos=cc_rotulos)

        with st.expander("Debug do item"):
            st.write("DATA:", it["data_name"], "| CUSTO:", it["cost_name"])
            st.dataframe(df_item.head(10))

# =============================================================================
# MICROBIOLOGIA (deve ser a última seção da página)
# =============================================================================
render_microbiologia()
