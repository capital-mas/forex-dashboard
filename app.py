# ==============================================================
#  ANALIZADOR CUANTITATIVO UNIFICADO — v3
#  Corto Plazo (Top-Down) + Mediano/Largo Plazo (Cuantitativo)
#  + Buscador Universal + Comparador de Activos + Optimizador de Cartera
#  Cambios v3: Plotly interactivo, descargas en paralelo,
#  comparador de tickers, cross-linking con un clic, glosario
#  con tooltips, autocomplete en buscador, botones ovalados.
#  Cambios v4: módulo Optimizador de Cartera (Monte Carlo + informe
#  comparativo vs benchmark), integrado como módulo nativo de Streamlit.
# ==============================================================


import warnings
warnings.filterwarnings("ignore")


import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import combinations
from modulo_opciones import modulo_opciones
from modulo_estados_financieros import render_analisis_profundo, render_comparativo_estados
from modulo_calendario import render_calendario_economico, render_noticias
from modulo_senales_trading import render_senales_trading
from finanzas_ui import render_finanzas_personales
import finanzas_data as fd
from modulo_pago_manual import pantalla_suscripcion, panel_admin_pagos, panel_gestion_cuentas, es_admin_usuario
from modulo_promediador import modulo_promediador
from modulo_volatilidad_y_analisis_tecnico import (
    modulo_volatilidad,
    modulo_analisis_tecnico,
)
from modulo_pares_cointegracion import modulo_pares_cointegracion

ZONA_AR = ZoneInfo("America/Argentina/Buenos_Aires")

def ahora_ar():
    """Devuelve la hora actual en horario de Argentina (evita el desfasaje UTC de Streamlit Cloud)."""
    return datetime.now(ZONA_AR)

try:
    from hurst import compute_Hc
    HURST_OK = True
except ImportError:
    HURST_OK = False

try:
    from hmmlearn.hmm import GaussianHMM
    HMM_OK = True
except ImportError:
    HMM_OK = False

from supabase import create_client, Client

# ==============================================================
#  CONFIG
# ==============================================================


st.set_page_config(
    page_title="Analizador Cuantitativo",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ==============================================================
#  CSS — diseño sin sidebar, nav superior, botones ovalados
#  (sin rellenos de color — solo texto en verde monster)
# ==============================================================


st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');

  :root {
    --verde-monster: #6CC24A;
    --verde-monster-hover: #8ddb5e;
    --verde-monster-dim: #4f9438;
  }

  /* ── Reset sidebar ── */
  [data-testid="stSidebar"] { display: none !important; }
  [data-testid="collapsedControl"] { display: none !important; }
  section[data-testid="stSidebar"] { width: 0 !important; }


  html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
    background: #07090f;
    color: #ffffff;
    font-size: 14px;
  }
  .stApp { background: #07090f; }
  .block-container { 
    padding: 24px 2rem 2rem 2rem !important;   /* ← antes tenía 0 arriba */
    max-width: 1400px; 
  }


  /* ── Top nav bar ── */
  .topbar-wrap {
    position: sticky; top: 0; z-index: 998;
    background: #07090f;
    border-bottom: 1px solid #21262d;
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    padding: 0;
  }
  .topbar-inner {
    position: relative;
    display: flex; align-items: center;
    padding: 0 24px; height: 58px; gap: 0;
  }
  .topbar-brand {
    display: flex; align-items: center; gap: 10px;
    margin-right: 28px; flex-shrink: 0;
  }
  .topbar-brand-icon {
    width: 30px; height: 30px; border-radius: 8px;
    background: linear-gradient(135deg, #1e4fa8, #3a7bd5);
    display: flex; align-items: center; justify-content: center;
    font-size: 14px;
  }
  .topbar-brand-center {
    position: absolute; left: 50%; top: 50%;
    transform: translate(-50%, -50%);
    display: flex; align-items: center; gap: 10px;
    pointer-events: none;
  }
  .topbar-brand-name {
    font-size: 16px; font-weight: 800; color: #e6edf3;
    letter-spacing: -0.3px; line-height: 1.2;
  }
  .topbar-brand-name span { color: #6CC24A; }
  .topbar-brand-sub {
    font-size: 11px; color: #6b7d9a; letter-spacing: 0.2px;
  }
  .topbar-divider { width: 1px; height: 22px; background: #21262d; margin: 0 20px; flex-shrink: 0; }
  .topbar-actions { display: flex; align-items: center; gap: 8px; margin-left: auto; }
  .topbar-time {
    font-size: 12px; color: #f5f7fa; font-family: 'JetBrains Mono', monospace;
    white-space: nowrap;
  }


  /* ── Ticker tape — barra deslizante de cotizaciones ── */
  .ticker-tape-wrap {
    width: 100%;
    overflow: hidden;
    background: #0a0c12;
    border-bottom: 1px solid #21262d;
    padding: 7px 0;
  }
  .ticker-tape-track {
    display: flex;
    width: max-content;
    animation: tape-scroll 55s linear infinite;
  }
  .ticker-tape-wrap:hover .ticker-tape-track {
    animation-play-state: paused;
  }
  .ticker-tape-content {
    display: flex;
    white-space: nowrap;
    padding-right: 48px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11.5px;
  }
  .tape-item { display: inline-flex; align-items: center; gap: 5px; }
  .tape-sep { color: #2a3a4f; padding: 0 14px; }
  @keyframes tape-scroll {
    from { transform: translateX(0); }
    to   { transform: translateX(-50%); }
  }
  @media (max-width: 768px) {
    .ticker-tape-content { font-size: 10.5px; }
    .ticker-tape-track { animation-duration: 38s; }
  }


  /* ── Botones — ovalados, sin relleno de color, texto verde monster ── */
  .stButton > button {
    background: #0d1117 !important;
    color: var(--verde-monster) !important;
    border: 1px solid #21262d !important;
    border-radius: 999px !important;
    padding: 6px 18px !important;
    font-weight: 600 !important;
    font-size: 12px !important;
    transition: all .18s ease !important;
    box-shadow: none !important;
  }
  .stButton > button:hover {
    border-color: var(--verde-monster) !important;
    color: var(--verde-monster-hover) !important;
    background: #11150f !important;
    transform: translateY(-1px) !important;
  }
  .stButton > button:active {
    color: var(--verde-monster) !important;
  }


  /* ── Nav pills — fila de navegación superior ── */
div[data-testid="stHorizontalBlock"] div[data-testid="column"] .stButton button {
    border-radius: 999px !important;
    border: 1px solid #21262d !important;
    padding: 8px 16px !important;
    font-size: 13px !important; font-weight: 600 !important;
    height: auto !important; min-height: 40px !important;
    background: #0d1117 !important;
    color: var(--verde-monster) !important;
    transition: all .18s ease !important;
    box-shadow: none !important;
    white-space: normal !important;
    line-height: 1.25 !important;
    letter-spacing: 0.1px !important;
  }
  div[data-testid="stHorizontalBlock"] div[data-testid="column"] .stButton button:hover {
    background: #161b22 !important;
    color: var(--verde-monster-hover) !important;
    border-color: var(--verde-monster) !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3) !important;
  }


  /* ── Page header ── */
  .page-header {
    padding: 28px 0 20px 0;
    margin-top: 20px;   /* ← esto es lo que agrega el aire de arriba */
    border-bottom: 1px solid #21262d;
    margin-bottom: 24px;
    text-align: center;
  }
  .page-title { font-size: 26px; font-weight: 700; color: #e6edf3; margin: 0; letter-spacing: -0.5px; }
  .page-sub { font-size: 14px; color: #f5f7fa; margin: 4px 0 0 0; }


  /* ── Toolbar (filtros debajo del header) ── */
  .toolbar {
    background: #0d1117;
    border: 1px solid #21262d;
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 20px;
    display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  }
  .toolbar-label { font-size: 13px; font-weight: 600; color: #f5f7fa; text-transform: uppercase; letter-spacing: 0.8px; }


  /* ── KPI cards ── */
  .kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }
  .kpi-card {
    background: #0d1117; border: 1px solid #21262d; border-radius: 10px;
    padding: 16px 18px; position: relative; overflow: hidden; transition: border-color .2s;
    cursor: help;
  }
  .kpi-card:hover { border-color: #3a7bd5; }
  .kpi-accent { position: absolute; top: 0; left: 0; width: 100%; height: 2px; border-radius: 10px 10px 0 0; }
  .kpi-label { color: #f5f7fa; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }
  .kpi-value { color: #e6edf3; font-size: 22px; font-weight: 700; letter-spacing: -0.5px; font-family: 'JetBrains Mono', monospace; }
  .kpi-sub { color: #f5f7fa; font-size: 13px; margin-top: 4px; }
  .kpi-card-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px 14px; margin-top:6px; }
  .kpi-metric-label { font-size:11px; color:#f5f7fa; text-transform:uppercase; letter-spacing:.5px; margin-bottom:2px; }
  .kpi-metric-value { font-size:16px; font-weight:700; color:#e6edf3; font-family:'JetBrains Mono',monospace; }


  /* ── Tabs ── */
  .stTabs [data-baseweb="tab-list"] {
    background: transparent; border-bottom: 1px solid #21262d;
    gap: 0; padding: 0;
  }
  .stTabs [data-baseweb="tab"] {
    background: transparent; color: #6b7d9a !important;
    border: none; padding: 10px 16px;
    font-weight: 500; font-size: 12px;
    border-bottom: 2px solid transparent;
  }
  .stTabs [aria-selected="true"] {
    color: var(--verde-monster) !important;
    border-bottom: 2px solid var(--verde-monster) !important;
    background: transparent !important;
  }


  /* ── Section title ── */
  .sec-title {
    font-size: 14px; font-weight: 700; color: #e6edf3;
    text-transform: uppercase; letter-spacing: 0.8px;
    margin: 20px 0 12px 0; padding-bottom: 8px;
    border-bottom: 1px solid #21262d;
    text-align: center;
  }


  /* ── Info banner ── */
  .info-banner {
    background: rgba(58,123,213,0.07); border: 1px solid rgba(58,123,213,0.2);
    border-radius: 8px; padding: 10px 14px; color: #f5f7fa;
    font-size: 13px; margin-bottom: 16px; line-height: 1.6;
  }


  /* ── Search box ── */
  .search-container {
    background: #0d1117; border: 1px solid #21262d; border-radius: 12px;
    padding: 24px 28px; margin-bottom: 24px;
  }
  .search-title { font-size: 15px; font-weight: 700; color: #e6edf3; margin-bottom: 4px; }
  .search-sub { font-size: 14px; color: #f5f7fa; margin-bottom: 16px; }


  /* ── Signal pill ── */
  .signal-pill {
    display: inline-block; padding: 4px 12px; border-radius: 20px;
    font-size: 11px; font-weight: 700;
    background: rgba(58,123,213,0.12); border: 1px solid rgba(58,123,213,0.3);
    color: #3a7bd5;
  }


  /* ── Interp card ── */
  .interp-card {
    background: #0d1117; border: 1px solid #21262d;
    border-left: 3px solid #3a7bd5; border-radius: 8px;
    padding: 12px 16px; margin-bottom: 10px;
    font-size: 14px; line-height: 1.7; color: #f5f7fa;
  }
  .interp-header {
    color: #3a7bd5; font-weight: 700; font-size: 12px;
    margin-bottom: 6px; font-family: 'JetBrains Mono', monospace;
  }
  .sesgo-muy-alc { color: #3fb950; font-weight: 700; }
  .sesgo-alc     { color: #7ee787; font-weight: 700; }
  .sesgo-neu     { color: #e3b341; font-weight: 700; }
  .sesgo-baj     { color: #f0883e; font-weight: 700; }
  .sesgo-muy-baj { color: #f85149; font-weight: 700; }


  /* ── Selectbox / multiselect ── */
  .stSelectbox > div > div { background: #0d1117 !important; border-color: #21262d !important; color: #e6edf3 !important; }
  .stMultiSelect > div > div { background: #0d1117 !important; border-color: #21262d !important; }


  /* ── Metric ── */
  [data-testid="stMetric"] { background: #0d1117; border: 1px solid #21262d; border-radius: 9px; padding: 12px 16px; }
  [data-testid="stMetricLabel"] { color: #f5f7fa !important; font-size: 12px !important; }
  [data-testid="stMetricValue"] { color: #e6edf3 !important; font-family: 'JetBrains Mono', monospace; }


  /* ── DataFrame ── */
  .stDataFrame { border-radius: 10px; overflow: hidden; }


  /* General ── */
  h1,h2,h3,h4 { color: #e6edf3 !important; text-align: center !important; }
  hr { border-color: #21262d !important; }
  p, label, .stMarkdown { color: #f5f7fa !important; font-size: 14px !important; }
</style>
""", unsafe_allow_html=True)

# ==============================================================
#  SUPABASE — Conexión + Autenticación
# ==============================================================

@st.cache_resource
def init_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

@st.cache_resource
def init_supabase_admin():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)

auth_client = init_supabase()      # solo para login/registro/sesión (anon key)
supabase = init_supabase_admin()   # todo lo demás (service_role, bypassea RLS)


def pantalla_landing():
    st.markdown("""
    <style>
    .landing-hero-wrap { max-width:1100px; margin:40px auto 0 auto; padding:0 20px; }
    .landing-badge {
        display:inline-block; padding:5px 14px; border-radius:20px; font-size:11px;
        font-weight:700; letter-spacing:.8px; text-transform:uppercase;
        background:rgba(108,194,74,0.12); border:1px solid #6CC24A; color:#6CC24A;
        margin-bottom:18px;
    }
    .landing-title {
        font-size:34px; font-weight:800; color:#e6edf3; letter-spacing:-1px;
        line-height:1.18; margin-bottom:14px;
    }
    .landing-title span { color:#6CC24A; }
    .landing-sub { font-size:14.5px; color:#8b949e; line-height:1.7; margin-bottom:6px; }
    .landing-auth-card {
        background:#0d1117; border:1px solid #21262d; border-top:2px solid #6CC24A;
        border-radius:14px; padding:26px 26px 18px 26px;
    }
    .landing-auth-title { font-size:16px; font-weight:700; color:#e6edf3; margin-bottom:2px; }
    .landing-auth-sub { font-size:12px; color:#6CC24A; margin-bottom:16px; }
    .landing-section-title {
        text-align:center; font-size:24px; font-weight:800; color:#e6edf3;
        margin:70px 0 8px 0; letter-spacing:-0.5px;
    }
    .landing-section-sub { text-align:center; font-size:13.5px; color:#8b949e; margin-bottom:36px; }
    .landing-features {
        display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
        gap:16px; max-width:1080px; margin:0 auto; padding:0 20px;
    }
    .landing-card {
        background:#0d1117; border:1px solid #21262d; border-radius:12px;
        padding:22px 20px; transition:border-color .2s;
    }
    .landing-card:hover { border-color:#3a7bd5; }
    .landing-card-icon { font-size:26px; margin-bottom:10px; }
    .landing-card-title { font-size:14px; font-weight:700; color:#e6edf3; margin-bottom:6px; }
    .landing-card-desc { font-size:12.5px; color:#8b949e; line-height:1.6; }
    .landing-steps {
        display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
        gap:20px; max-width:900px; margin:0 auto; padding:0 20px;
    }
    .landing-step { text-align:center; padding:10px; }
    .landing-step-num {
        width:36px; height:36px; border-radius:50%; background:rgba(108,194,74,0.12);
        border:1px solid #6CC24A; color:#6CC24A; font-weight:800; font-size:15px;
        display:flex; align-items:center; justify-content:center; margin:0 auto 12px auto;
    }
    .landing-step-title { font-size:13.5px; font-weight:700; color:#e6edf3; margin-bottom:6px; }
    .landing-step-desc { font-size:12px; color:#8b949e; line-height:1.6; }
    .landing-pricing {
        max-width:380px; margin:0 auto; background:#0d1117; border:1px solid #21262d;
        border-top:2px solid #6CC24A; border-radius:16px; padding:32px 28px; text-align:center;
    }
    .landing-price { font-size:42px; font-weight:800; color:#e6edf3; margin:10px 0 2px 0; }
    .landing-price-sub { font-size:12px; color:#8b949e; margin-bottom:20px; }
    .landing-trial { font-size:12px; color:#6CC24A; font-weight:700; margin-bottom:4px; }
    .landing-cancel { font-size:11px; color:#6b7d9a; margin-bottom:4px; }
    .landing-footer { text-align:center; color:#3a4a5a; font-size:11px; padding:50px 20px 30px 20px; }
    </style>
    """, unsafe_allow_html=True)

    # ── HERO + LOGIN/REGISTRO lado a lado ──────────────────────────────
    st.markdown('<div class="landing-hero-wrap">', unsafe_allow_html=True)
    col_hero, col_auth = st.columns([1.15, 1], gap="large")

    with col_hero:
        st.markdown("""
        <div class="landing-badge">📡 Análisis Cuantitativo de Mercados</div>
        <div class="landing-title">Invertí con datos,<br>no con <span>corazonadas</span></div>
        <div class="landing-sub">
          Capital+ combina scores cuantitativos, análisis fundamental, optimización de
          cartera y valuación de opciones en una sola herramienta — para acciones, ETFs,
          forex, commodities y cripto.
        </div>
        <div class="landing-sub" style="margin-top:18px">
          🎁 <b style="color:#e6edf3">7 días de prueba gratis</b>, sin tarjeta. Cancelás cuando quieras.
        </div>
        """, unsafe_allow_html=True)

    with col_auth:
        st.markdown('<div class="landing-auth-card">', unsafe_allow_html=True)
        tab_login, tab_registro = st.tabs(["Iniciar sesión", "Crear cuenta gratis"])

        with tab_login:
            st.markdown('<div class="landing-auth-sub">Bienvenido de nuevo</div>', unsafe_allow_html=True)
            email = st.text_input("Email", key="landing_login_email")
            password = st.text_input("Contraseña", type="password", key="landing_login_pass")
            if st.button("Entrar", use_container_width=True, key="landing_btn_login", type="primary"):
                if not email or not password:
                    st.error("Completá email y contraseña.")
                else:
                    try:
                        res = auth_client.auth.sign_in_with_password({"email": email, "password": password})
                        st.session_state["usuario"] = res.user
                        cookies.set("sb_refresh_token", res.session.refresh_token)
                        st.rerun()
                    except Exception:
                        st.error("Email o contraseña incorrectos.")

        with tab_registro:
            st.markdown('<div class="landing-auth-sub">Empezá gratis en 30 segundos</div>', unsafe_allow_html=True)
            email_r = st.text_input("Email", key="landing_reg_email")
            password_r = st.text_input("Contraseña", type="password", key="landing_reg_pass")
            password_r2 = st.text_input("Confirmar contraseña", type="password", key="landing_reg_pass2")
            if st.button("Crear cuenta gratis", use_container_width=True, key="landing_btn_registro", type="primary"):
                if not email_r or not password_r:
                    st.error("Completá email y contraseña.")
                elif password_r != password_r2:
                    st.error("Las contraseñas no coinciden.")
                elif len(password_r) < 6:
                    st.error("La contraseña debe tener al menos 6 caracteres.")
                else:
                    try:
                        auth_client.auth.sign_up({"email": email_r, "password": password_r})
                        st.success("¡Cuenta creada! Revisá tu email para confirmarla y después iniciá sesión.")
                    except Exception as e:
                        st.error(f"Error al registrarse: {e}")
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

    # ── FEATURES ─────────────────────────────────────────────────────
    st.markdown("""
    <div class="landing-section-title">Todo lo que necesitás para decidir</div>
    <div class="landing-section-sub">Seis módulos integrados, sin saltar entre herramientas distintas</div>
    <div class="landing-features">
      <div class="landing-card">
        <div class="landing-card-icon">⚡</div>
        <div class="landing-card-title">Scoring cuantitativo</div>
        <div class="landing-card-desc">Percentiles históricos, tendencia, reversión a la media y riesgo — corto y largo plazo, en un ranking claro.</div>
      </div>
      <div class="landing-card">
        <div class="landing-card-icon">📊</div>
        <div class="landing-card-title">Análisis fundamental</div>
        <div class="landing-card-desc">Ratios financieros comparados contra benchmarks por sector, con señales automáticas de valuación.</div>
      </div>
      <div class="landing-card">
        <div class="landing-card-icon">🧮</div>
        <div class="landing-card-title">Optimizador de cartera</div>
        <div class="landing-card-desc">Simulación Monte Carlo: encontrá la combinación de activos con mejor relación riesgo-retorno.</div>
      </div>
      <div class="landing-card">
        <div class="landing-card-icon">🎲</div>
        <div class="landing-card-title">Valuación de opciones</div>
        <div class="landing-card-desc">Black-Scholes, binomial, griegas y catálogo de estrategias, con payoff visual.</div>
      </div>
      <div class="landing-card">
        <div class="landing-card-icon">🔗</div>
        <div class="landing-card-title">Scanner de pares</div>
        <div class="landing-card-desc">Detectá oportunidades de reversión a la media entre activos del mismo sector.</div>
      </div>
      <div class="landing-card">
        <div class="landing-card-icon">📆</div>
        <div class="landing-card-title">Calendario económico</div>
        <div class="landing-card-desc">Eventos macro relevantes y su impacto esperado en los mercados, todo en un solo lugar.</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── CÓMO FUNCIONA ────────────────────────────────────────────────
    st.markdown("""
    <div class="landing-section-title">Empezá en 3 pasos</div>
    <div class="landing-section-sub">Sin instalar nada, todo desde el navegador</div>
    <div class="landing-steps">
      <div class="landing-step">
        <div class="landing-step-num">1</div>
        <div class="landing-step-title">Creá tu cuenta</div>
        <div class="landing-step-desc">Registrate gratis con tu email arriba. Sin tarjeta, sin compromiso.</div>
      </div>
      <div class="landing-step">
        <div class="landing-step-num">2</div>
        <div class="landing-step-title">Probá 7 días gratis</div>
        <div class="landing-step-desc">Acceso completo a todos los módulos, sin restricciones.</div>
      </div>
      <div class="landing-step">
        <div class="landing-step-num">3</div>
        <div class="landing-step-title">Elegí tu plan</div>
        <div class="landing-step-desc">Básico o Pro, pagando en cripto. Cancelás cuando quieras, sin ataduras.</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── PRICING — grilla de 4 planes lado a lado ──────────────────────
    st.markdown("""
    <style>
    .pricing-grid {
        display:grid;
        grid-template-columns:repeat(4,1fr);
        gap:16px;
        max-width:1080px;
        margin:0 auto;
        padding:0 20px;
        align-items:stretch;
    }
    .pricing-card {
        position:relative;
        background:#0d1117; border:1px solid #21262d; border-top:2px solid #21262d;
        border-radius:14px; padding:26px 20px 22px 20px;
        text-align:center; display:flex; flex-direction:column;
        transition:border-color .2s, transform .2s;
    }
    .pricing-card:hover { border-color:#3a7bd5; transform:translateY(-2px); }
    .pricing-card.featured {
        border-color:#6CC24A; border-top:2px solid #6CC24A;
        box-shadow:0 0 0 1px rgba(108,194,74,0.25);
    }
    .pricing-badge {
        position:absolute; top:-11px; left:50%; transform:translateX(-50%);
        background:#6CC24A; color:#07090f; font-size:10px; font-weight:800;
        letter-spacing:.6px; text-transform:uppercase;
        padding:4px 14px; border-radius:20px; white-space:nowrap;
    }
    .pricing-name {
        font-size:12px; color:#8b949e; font-weight:700;
        text-transform:uppercase; letter-spacing:1px; margin-bottom:14px;
    }
    .pricing-price {
        font-size:26px; font-weight:800; color:#e6edf3; line-height:1.15;
    }
    .pricing-price small { font-size:13px; color:#8b949e; font-weight:500; }
    .pricing-permes {
        font-size:12px; color:#6CC24A; font-weight:700; margin-top:6px;
    }
    .pricing-sub { font-size:11.5px; color:#8b949e; margin:10px 0 16px 0; flex-grow:1; }
    .pricing-trial { font-size:11.5px; color:#6CC24A; font-weight:700; margin-bottom:3px; }
    .pricing-cancel { font-size:10.5px; color:#6b7d9a; }
    @media (max-width:900px) {
        .pricing-grid { grid-template-columns:repeat(2,1fr); }
    }
    @media (max-width:560px) {
        .pricing-grid { grid-template-columns:1fr; }
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown('<div class="landing-section-title">Elegí tu plan</div>', unsafe_allow_html=True)
    st.markdown('<div class="landing-section-sub">Dos niveles de acceso, pagando en criptomonedas</div>', unsafe_allow_html=True)

    st.markdown("""
    <div class="pricing-grid" style="grid-template-columns:repeat(2,1fr);max-width:640px">
      <div class="pricing-card">
        <div class="pricing-name">Básico</div>
        <div class="pricing-price">U$S10<br><small>/ mes</small></div>
        <div class="pricing-permes">Trimestral U$S27 · Anual U$S90</div>
        <div class="pricing-sub">Acceso a los módulos esenciales</div>
        <div class="pricing-trial">🎁 7 días gratis</div>
        <div class="pricing-cancel">Pago en cripto</div>
      </div>
      <div class="pricing-card featured">
        <div class="pricing-badge">Recomendado</div>
        <div class="pricing-name">Pro</div>
        <div class="pricing-price">U$S18<br><small>/ mes</small></div>
        <div class="pricing-permes">Trimestral U$S48 · Anual U$S160</div>
        <div class="pricing-sub">Acceso completo: Optimizador, Opciones, Señales y más</div>
        <div class="pricing-trial">🎁 7 días gratis</div>
        <div class="pricing-cancel">Pago en cripto</div>
      </div>
    </div>
    """, unsafe_allow_html=True)
    # ── FAQ ──────────────────────────────────────────────────────────
    st.markdown('<div class="landing-section-title">Preguntas frecuentes</div>', unsafe_allow_html=True)
    _, col_faq, _ = st.columns([1, 3, 1])
    with col_faq:
        with st.expander("¿Necesito tarjeta para probarlo?"):
            st.write("No. Te registrás con tu email y arrancás el trial de 7 días sin cargar ningún método de pago.")
        with st.expander("¿Qué pasa cuando termina el trial?"):
            st.write("Te pedimos que elijas un plan (Básico o Pro) para seguir con acceso. El pago se realiza en criptomonedas.")
        with st.expander("¿Puedo cancelar cuando quiera?"):
            st.write("Sí, la suscripción se puede cancelar en cualquier momento, sin permanencia mínima.")
        with st.expander("¿Los datos son en tiempo real?"):
            st.write("Los precios se actualizan con caché de hasta 30 minutos según el módulo, usando datos de Yahoo Finance.")
        with st.expander("¿Esto es asesoramiento financiero?"):
            st.write("No. Capital+ es una herramienta de análisis cuantitativo con fines informativos, no constituye recomendación de inversión.")

    st.markdown("""
    <div class="landing-footer">
      📡 Capital+ · Análisis cuantitativo de mercados · Solo informativo, no constituye asesoramiento financiero.
    </div>
    """, unsafe_allow_html=True)


# ── GATE: si no hay sesión, mostrar login y frenar acá ──
from streamlit_cookies_controller import CookieController

cookies = CookieController()

def restaurar_sesion():
    """Intenta restaurar la sesión desde la cookie del navegador si session_state la perdió."""
    if "usuario" in st.session_state:
        return  # ya está logueado en esta ejecución
    refresh_token = cookies.get("sb_refresh_token")
    if refresh_token:
        try:
            res = auth_client.auth.refresh_session(refresh_token)
            st.session_state["usuario"] = res.user
            cookies.set("sb_refresh_token", res.session.refresh_token)
        except Exception:
            cookies.remove("sb_refresh_token")

restaurar_sesion()

if "usuario" not in st.session_state:
    pantalla_landing()
    st.stop()
    
USER_ID = st.session_state["usuario"].id

# ── GATE: si no tiene trial activo ni plan pro, mostrar pantalla de pago ──
tiene_acceso = pantalla_suscripcion(supabase, USER_ID, st.session_state["usuario"].email)
if not tiene_acceso:
    st.stop()

@st.cache_data(ttl=300, show_spinner=False)
def _contar_alertas_finanzas(_client, user_id):
    """Cuenta las alertas de Finanzas Personales. Cacheado 5 min para no
    consultar Supabase/Yahoo Finance en cada rerun de TODA la app."""
    try:
        return len(fd.obtener_alertas(_client, user_id))
    except Exception:
        return 0

@st.cache_data(ttl=300, show_spinner=False)
def _es_admin_cache(_client, user_id):
    try:
        return es_admin_usuario(_client, user_id)
    except Exception:
        return False

ES_ADMIN = _es_admin_cache(supabase, USER_ID)
# ==============================================================
#  PALETA (para HTML / Plotly)
# ==============================================================


C_ACENT   = '#3a7bd5'
C_MONSTER = '#6CC24A'
C_TEXT    = '#e6edf3'
C_MUTED   = '#6b7d9a'
C_GREEN   = '#3fb950'
C_RED     = '#f85149'
C_YELL    = '#e3b341'
C_LGRE    = '#7ee787'
C_LRED    = '#f0883e'
C_GRID    = '#21262d'
C_BG1     = '#0d1117'
C_BG2     = '#07090f'

PLOTLY_LAYOUT_BASE = dict(
    plot_bgcolor=C_BG1, paper_bgcolor=C_BG2,
    font=dict(color='#b0bcd0', family='Inter, sans-serif'),
    dragmode=False,   # ← deshabilita el recuadro de zoom por arrastre
)

PLOTLY_CONFIG = dict(
    displayModeBar=False,  # ← oculta cámara/lupa/pan de la esquina
    scrollZoom=False,      # ← deshabilita zoom con la rueda del mouse
)


def score_color_hex(v):
    if   v <= 20: return '#f85149'
    elif v <= 40: return '#f0883e'
    elif v <= 60: return '#e3b341'
    elif v <= 80: return '#7ee787'
    else:         return '#3fb950'


def sesgo_color_hex(s):
    return {'MUY ALCISTA':'#3fb950','ALCISTA':'#7ee787','NEUTRAL':'#e3b341','BAJISTA':'#f0883e','MUY BAJISTA':'#f85149'}.get(s,'#e6edf3')


def clasificar_score(s):
    if   s <= 20: return 'Muy bajo',  '#f85149', '🔴'
    elif s <= 40: return 'Bajo',      '#f0883e', '🟠'
    elif s <= 60: return 'Neutral',   '#e3b341', '🟡'
    elif s <= 80: return 'Alto',      '#7ee787', '🟢'
    else:         return 'Muy alto',  '#3fb950', '💚'


# ==============================================================
#  GLOSARIO — términos cuantitativos y fundamentales
# ==============================================================


GLOSARIO = {
    'Score Acumulación': 'Percentil del precio actual respecto a su propio historial (3 meses), combinado con RSI y volatilidad reciente. Alto = el activo está relativamente barato dentro de su propio rango reciente (zona de acumulación). Bajo = relativamente caro / en zona de distribución.',
    'Score Anticipación': 'Mide el momentum de corto plazo junto con la compresión de volatilidad (ATR) y de Bandas de Bollinger. Anticipa posibles movimientos fuertes inminentes, sin importar la dirección.',
    'Score Sentimiento': 'Percentil del precio en los últimos 3 meses. Más alto = más cerca de máximos recientes (sentimiento optimista); más bajo = más cerca de mínimos.',
    'Score Final': 'Combinación ponderada de Acumulación (45%), Anticipación (35%) y Sentimiento (20%). Resumen de corto plazo.',
    'Trend Score': 'Fuerza de la tendencia de largo plazo: Golden Cross, MACD alcista, RSI>50 y persistencia (Hurst). Más alto = tendencia más fuerte y sostenida.',
    'MR Score': 'Mean Reversion Score: qué tan lejos está el precio de su media de 20 días (Z-Score, Bandas de Bollinger) y su tendencia a revertir (Hurst < 0.5). Alto = mayor probabilidad estadística de reversión a la media.',
    'Risk Score': 'Combina Sharpe, Sortino, Máximo Drawdown y volatilidad anualizada. Alto = mejor retorno ajustado por riesgo y caídas más controladas.',
    'Global Score': 'Promedio de Trend, MR y Risk Score. Resumen cuantitativo de largo plazo (0-100).',
    'Hurst': 'Mide si el precio se comporta de forma persistente (H>0.55, sigue su tendencia), aleatoria (H≈0.5) o reversiva (H<0.45, tiende a revertir tras un movimiento).',
    'Z-Score': 'Cuántas desviaciones estándar está el precio respecto a su media móvil de 20 días. Muy negativo = sobreventa estadística; muy positivo = sobrecompra.',
    'RSI': 'Oscilador de momentum (0-100). Por debajo de 30 sugiere sobreventa; por encima de 70, sobrecompra.',
    'MACD': 'Diferencia entre dos medias móviles exponenciales (12 y 26) y su señal (9). Cruce del MACD por encima de la señal = señal alcista.',
    'Sharpe': 'Retorno anualizado por encima de la tasa libre de riesgo, dividido por la volatilidad. Retorno obtenido por unidad de riesgo total.',
    'Sortino': 'Similar al Sharpe, pero solo penaliza la volatilidad negativa (caídas).',
    'Max Drawdown': 'La mayor caída porcentual desde un máximo histórico hasta el mínimo posterior.',
    'Golden Cross': 'Cuando la media móvil de 50 días cruza por encima de la de 200 días. Señal técnica clásica de tendencia alcista de largo plazo.',
    'Bandas de Bollinger': 'Bandas a 2 desvíos estándar de la media de 20 días. El precio fuera de las bandas indica condiciones estadísticamente extremas.',
    'ATR': 'Average True Range: promedio del rango verdadero de precios (volatilidad absoluta) de los últimos 14 períodos.',
    'PER': 'Precio / Ganancias por acción. Cuanto más bajo, en general más "barata" luce la acción (depende del sector).',
    'P/B': 'Precio / Valor libro por acción. Muy usado en bancos y financieras.',
    'EV/EBITDA': 'Valor de la empresa (Enterprise Value) / EBITDA. Múltiplo que no depende de la estructura de capital ni de impuestos.',
    'PEG': 'PER / crecimiento esperado de ganancias. PEG < 1 sugiere que el crecimiento está "barato" respecto al precio pagado.',
    'ROE': 'Ganancia neta / patrimonio neto. Rentabilidad sobre el capital de los accionistas.',
    'ROA': 'Ganancia neta / activos totales. Eficiencia en el uso de los activos.',
    'Beta': 'Sensibilidad del activo respecto al mercado. Beta > 1 = más volátil que el mercado; Beta < 1 = más defensivo.',
    'FCF': 'Free Cash Flow: efectivo generado por operaciones, neto de CAPEX. Positivo y creciente = buena salud financiera.',
    'Dividend Yield': 'Dividendo anual / precio de la acción.',
    'P/S': 'Precio / Ventas por acción. Útil para valuar empresas con ganancias bajas o negativas, ya que las ventas son menos volátiles que las ganancias.',
    'Margen Bruto': 'Ganancia bruta (ingresos − costo de ventas) / ingresos totales. Lo que le queda a la empresa después de producir lo que vende, antes de gastos operativos.',
    'Margen Operativo': 'Ganancia operativa / ingresos totales. Mide la eficiencia del negocio antes de intereses e impuestos.',
    'Margen Neto': 'Ganancia neta / ingresos totales. Porcentaje de cada peso/dólar de ventas que termina siendo ganancia final.',
    'Revenue Growth': 'Crecimiento de los ingresos totales respecto al período anterior (interanual).',
    'EPS Growth': 'Crecimiento de las ganancias por acción (EPS) respecto al período anterior.',
    'Earnings Growth': 'Crecimiento de las ganancias totales de la empresa respecto al período anterior.',
    'D/E': 'Deuda total / patrimonio neto. Mide cuánto apalancamiento financiero usa la empresa respecto a su capital propio. Más alto implica más riesgo financiero.',
    'Current Ratio': 'Activo corriente / pasivo corriente. Capacidad de pagar obligaciones de corto plazo. Por encima de 1.5-2 se considera saludable.',
    'Market Cap': 'Capitalización de mercado: precio de la acción × cantidad de acciones en circulación. Tamaño total de la empresa según el mercado.',
    'Enterprise Value': 'Valor de la empresa: Market Cap + deuda total − caja. Costo teórico de comprar toda la empresa.',
    'Cash': 'Efectivo y equivalentes en el balance. Recursos líquidos disponibles de forma inmediata.',
    'Operating Cash Flow': 'Efectivo generado por las operaciones del negocio, antes de inversiones de capital (CAPEX).',
    'YTD': 'Year to Date: variación del precio desde el 1° de enero del año en curso hasta hoy.',
    'Precio Objetivo': 'Precio promedio que estiman los analistas que cubren la acción, a 12 meses.',
}


def G(term):
    return GLOSARIO.get(term)

# ==============================================================
#  NIVELES POR TÉRMINO — tabla de rangos/interpretación para el glosario
# ==============================================================

_NIV_SCORE = lambda txt_bajo, txt_neutral, txt_alto: [
    ('0 – 20',   'Muy bajo', f'{txt_bajo} (extremo).'),
    ('21 – 40',  'Bajo',      txt_bajo),
    ('41 – 60',  'Neutral',   txt_neutral),
    ('61 – 80',  'Alto',      txt_alto),
    ('81 – 100', 'Muy alto', f'{txt_alto} (extremo).'),
]

GLOSARIO_NIVELES = {
    'Score Acumulación': _NIV_SCORE(
        'Precio caro respecto a su propio historial reciente (zona de distribución)',
        'Precio dentro de su rango normal de los últimos 3 meses',
        'Precio relativamente barato dentro de su historial reciente (zona de acumulación)'),
    'Score Anticipación': _NIV_SCORE(
        'Momentum débil, sin compresión de volatilidad',
        'Momentum y volatilidad en rango normal',
        'Momentum en aumento con compresión de volatilidad (movimiento cercano)'),
    'Score Sentimiento': _NIV_SCORE(
        'Precio cerca de mínimos de 3 meses (pesimismo)',
        'Precio en la mitad de su rango reciente',
        'Precio cerca de máximos de 3 meses (optimismo/euforia)'),
    'Score Final': _NIV_SCORE(
        'Combinación de corto plazo débil (caro / sin momentum / pesimismo)',
        'Combinación de corto plazo neutral',
        'Combinación de corto plazo favorable (barato / con momentum / optimismo)'),
    'Trend Score': _NIV_SCORE(
        'Tendencia débil o inexistente (sin Golden Cross, MACD bajista)',
        'Tendencia mixta, sin confirmación clara',
        'Tendencia fuerte y sostenida (Golden Cross, MACD alcista, Hurst persistente)'),
    'MR Score': _NIV_SCORE(
        'Baja probabilidad de reversión a la media',
        'Probabilidad de reversión moderada',
        'Alta probabilidad estadística de reversión a la media (sobreventa)'),
    'Risk Score': _NIV_SCORE(
        'Mala relación retorno/riesgo (Sharpe bajo, drawdown severo)',
        'Relación retorno/riesgo aceptable',
        'Excelente relación retorno/riesgo (Sharpe alto, drawdown controlado)'),
    'Global Score': _NIV_SCORE(
        'Perfil cuantitativo de largo plazo débil (MUY BAJISTA/BAJISTA)',
        'Perfil cuantitativo neutral',
        'Perfil cuantitativo de largo plazo sólido (ALCISTA/MUY ALCISTA)'),

    'Hurst': [
        ('< 0.45',     'Reversivo',   'Tiende a revertir tras un movimiento (anti-persistente).'),
        ('0.45 – 0.55','Aleatorio',   'Comportamiento cercano a un paseo aleatorio, sin persistencia clara.'),
        ('> 0.55',     'Persistente', 'La tendencia actual tiende a continuar.'),
    ],
    'Z-Score': [
        ('< -2',    'Sobreventa extrema',    'Precio muy por debajo de su media de 20 días.'),
        ('-2 a -1', 'Sobreventa moderada',   'Precio por debajo de su media; posible soporte.'),
        ('-1 a 1',  'Neutral',               'Precio cerca de su media móvil.'),
        ('1 a 2',   'Sobrecompra moderada',  'Precio por encima de su media; presión compradora.'),
        ('> 2',     'Sobrecompra extrema',   'Precio muy por encima de su media; posible resistencia.'),
    ],
    'RSI': [
        ('0 – 30',   'Sobreventa', 'Momentum vendedor dominante, posible rebote.'),
        ('30 – 45',  'Débil',      'Momentum bajista moderado.'),
        ('45 – 55',  'Neutral',    'Sin sesgo claro de momentum.'),
        ('55 – 70',  'Fuerte',     'Momentum comprador moderado.'),
        ('70 – 100', 'Sobrecompra','Momentum comprador extremo, posible corrección.'),
    ],
    'MACD': [
        ('MACD > Señal', 'Alcista', 'Cruce alcista: posible continuación/inicio de suba.'),
        ('MACD < Señal', 'Bajista', 'Cruce bajista: posible continuación/inicio de baja.'),
    ],
    'Sharpe': [
        ('< 0',    'Negativo',  'El retorno no compensa el riesgo asumido.'),
        ('0 – 1',  'Moderado',  'Retorno ajustado por riesgo aceptable.'),
        ('1 – 2',  'Bueno',     'Buena relación retorno/riesgo.'),
        ('> 2',    'Excelente', 'Relación retorno/riesgo sobresaliente.'),
    ],
    'Sortino': [
        ('< 0',    'Negativo',  'El retorno no compensa la volatilidad negativa.'),
        ('0 – 1',  'Moderado',  'Retorno aceptable ajustado por caídas.'),
        ('1 – 2',  'Bueno',     'Buena relación retorno/volatilidad negativa.'),
        ('> 2',    'Excelente', 'Relación sobresaliente frente a las caídas.'),
    ],
    'Max Drawdown': [
        ('> -10%',        'Contenido',    'Caídas históricas leves.'),
        ('-10% a -20%',   'Aceptable',    'Caídas moderadas, dentro de lo normal.'),
        ('-20% a -35%',   'Significativo','Caídas relevantes, requiere gestión de riesgo.'),
        ('< -35%',        'Severo',       'Caídas muy profundas, alto riesgo histórico.'),
    ],
    'Golden Cross': [
        ('MA50 > MA200', 'Golden Cross', 'Señal alcista de largo plazo.'),
        ('MA50 < MA200', 'Death Cross',  'Señal bajista de largo plazo.'),
    ],
    'Bandas de Bollinger': [
        ('Precio > Banda superior', 'Sobrecompra', 'Condición estadísticamente extrema al alza.'),
        ('Dentro de las bandas',    'Normal',      'Precio dentro del rango estadístico esperado.'),
        ('Precio < Banda inferior', 'Sobreventa',  'Condición estadísticamente extrema a la baja.'),
    ],
    'ATR': [
        ('Alto vs. su propio promedio', 'Volatilidad elevada',    'Movimientos de precio más amplios de lo habitual.'),
        ('Bajo vs. su propio promedio', 'Volatilidad comprimida', 'Movimientos contenidos; posible antesala de un impulso.'),
    ],
    'PER': [
        ('< 10x',    'Muy barato',    'Valuación baja; puede reflejar riesgo o infravaloración.'),
        ('10x – 15x','Barato',        'Valuación atractiva en términos relativos.'),
        ('15x – 25x','Normal',        'Valuación en línea con el promedio de mercado.'),
        ('25x – 40x','Exigente',      'Valuación alta; el mercado espera fuerte crecimiento.'),
        ('> 40x',    'Muy exigente',  'Riesgo de corrección si no se cumplen expectativas.'),
    ],
    'P/B': [
        ('< 1x',     'Bajo valor libro', 'Cotiza por debajo de su patrimonio contable.'),
        ('1x – 2.5x','Razonable',        'Valuación típica para la mayoría de sectores.'),
        ('2.5x – 6x','Elevado',          'Valuación exigente respecto al valor contable.'),
        ('> 6x',     'Muy elevado',      'Valuación muy por encima del valor contable.'),
    ],
    'EV/EBITDA': [
        ('< 10x',    'Atractivo',   'Múltiplo bajo respecto al EBITDA generado.'),
        ('10x – 15x','Normal',      'Múltiplo típico de mercado.'),
        ('15x – 20x','Elevado',     'Valuación exigente.'),
        ('> 20x',    'Muy elevado', 'Valuación muy exigente respecto a la caja operativa.'),
    ],
    'PEG': [
        ('< 1',   'Barato',    'El crecimiento esperado está "barato" respecto al precio pagado.'),
        ('1 – 2', 'Razonable', 'Relación precio/crecimiento equilibrada.'),
        ('> 2',   'Caro',      'El crecimiento esperado está "caro" respecto al precio pagado.'),
    ],
    'ROE': [
        ('< 8%',    'Débil',       'Rentabilidad sobre el capital baja.'),
        ('8% – 15%','Aceptable',   'Rentabilidad dentro de rangos normales.'),
        ('15% – 25%','Buena',      'Rentabilidad sólida sobre el patrimonio.'),
        ('> 25%',   'Excepcional', 'Rentabilidad muy alta sobre el capital propio.'),
    ],
    'ROA': [
        ('< 3%',    'Bajo',      'Baja eficiencia en el uso de activos.'),
        ('3% – 10%','Aceptable', 'Eficiencia normal en el uso de activos.'),
        ('> 10%',   'Sólido',    'Alta eficiencia en la generación de ganancias con los activos.'),
    ],
    'Beta': [
        ('< 0.8',    'Defensivo',            'Menor volatilidad que el mercado.'),
        ('0.8 – 1.2','En línea con mercado', 'Volatilidad similar al mercado general.'),
        ('1.2 – 1.5','Más volátil',          'Mayor sensibilidad que el mercado.'),
        ('> 1.5',    'Muy volátil',          'Sensibilidad muy alta; mayor riesgo.'),
    ],
    'FCF': [
        ('Positivo y creciente', 'Saludable', 'Genera caja real de forma sostenida.'),
        ('Positivo estable',     'Aceptable', 'Genera caja, sin gran crecimiento.'),
        ('Negativo',             'Alerta',    'Puede ser ciclo inversor o problema estructural — revisar.'),
    ],
    'Dividend Yield': [
        ('0%',      'Sin dividendo', 'La empresa no distribuye dividendos.'),
        ('0% – 2%', 'Bajo',          'Rendimiento por dividendo modesto.'),
        ('2% – 4%', 'Moderado',      'Rendimiento por dividendo saludable.'),
        ('4% – 6%', 'Atractivo',     'Rendimiento por dividendo alto.'),
        ('> 6%',    'Muy alto',      'Verificar sostenibilidad del pago.'),
    ],
    'P/S': [
        ('< 2x',   'Barato', 'Valuación baja respecto a las ventas.'),
        ('2x – 5x','Normal', 'Valuación típica de mercado.'),
        ('> 5x',   'Caro',   'Valuación alta respecto a las ventas generadas.'),
    ],
    'Margen Bruto': [
        ('< 20%',    'Bajo',      'Estructura de costos poco eficiente o sector de bajo margen.'),
        ('20% – 40%','Moderado',  'Margen bruto típico de sectores industriales/comerciales.'),
        ('40% – 60%','Bueno',     'Buen poder de fijación de precios.'),
        ('> 60%',    'Excelente', 'Márgenes propios de software/tecnología o alto valor agregado.'),
    ],
    'Margen Operativo': [
        ('< 10%',    'Bajo',      'Eficiencia operativa limitada.'),
        ('10% – 20%','Moderado',  'Eficiencia operativa normal.'),
        ('20% – 30%','Bueno',     'Buena eficiencia operativa.'),
        ('> 30%',    'Excelente', 'Eficiencia operativa sobresaliente.'),
    ],
    'Margen Neto': [
        ('< 5%',     'Bajo',      'Poca rentabilidad final sobre ventas.'),
        ('5% – 10%', 'Moderado',  'Rentabilidad neta típica.'),
        ('10% – 20%','Bueno',     'Buena rentabilidad final.'),
        ('> 20%',    'Excelente', 'Muy alta rentabilidad final sobre ventas.'),
    ],
    'Revenue Growth': [
        ('< 0%',     'Contracción', 'Caída interanual de ingresos.'),
        ('0% – 10%', 'Moderado',    'Crecimiento bajo/estable.'),
        ('10% – 20%','Bueno',       'Buen ritmo de crecimiento.'),
        ('> 20%',    'Excelente',   'Crecimiento fuerte/acelerado.'),
    ],
    'EPS Growth': [
        ('< 0%',     'Contracción', 'Caída interanual de EPS.'),
        ('0% – 10%', 'Moderado',    'Crecimiento bajo/estable.'),
        ('10% – 20%','Bueno',       'Buen ritmo de crecimiento.'),
        ('> 20%',    'Excelente',   'Crecimiento fuerte/acelerado.'),
    ],
    'Earnings Growth': [
        ('< 0%',     'Contracción', 'Caída interanual de ganancias.'),
        ('0% – 10%', 'Moderado',    'Crecimiento bajo/estable.'),
        ('10% – 20%','Bueno',       'Buen ritmo de crecimiento.'),
        ('> 20%',    'Excelente',   'Crecimiento fuerte/acelerado.'),
    ],
    'D/E': [
        ('< 0.5x',   'Conservador', 'Bajo apalancamiento financiero.'),
        ('0.5x – 1x','Moderado',    'Apalancamiento razonable.'),
        ('1x – 2x',  'Elevado',     'Apalancamiento alto, mayor riesgo financiero.'),
        ('> 2x',     'Muy elevado', 'Riesgo financiero significativo.'),
    ],
    'Current Ratio': [
        ('< 1x',     'Riesgo de liquidez', 'Pasivos corrientes superan a los activos corrientes.'),
        ('1x – 1.5x','Ajustado',           'Liquidez justa, poco margen.'),
        ('1.5x – 2x','Saludable',          'Buena capacidad de pago de corto plazo.'),
        ('> 2x',     'Muy líquido',        'Amplia holgura de liquidez de corto plazo.'),
    ],
    'Market Cap': [
        ('< USD 2.000M',              'Small Cap', 'Baja capitalización; mayor riesgo/volatilidad.'),
        ('USD 2.000M – 10.000M',      'Mid Cap',   'Capitalización media.'),
        ('USD 10.000M – 200.000M',    'Large Cap', 'Capitalización grande, empresa consolidada.'),
        ('> USD 200.000M',            'Mega Cap',  'Capitalización gigante, líder de mercado.'),
    ],
    'Enterprise Value': [
        ('Informativo', '—', 'Se usa junto a EBITDA/ventas para calcular múltiplos; no tiene rango propio.'),
    ],
    'Cash': [
        ('Informativo', '—', 'Se interpreta junto a la deuda total: caja > deuda es señal positiva de solvencia.'),
    ],
    'Operating Cash Flow': [
        ('Positivo', 'Saludable', 'La operación genera caja real.'),
        ('Negativo', 'Alerta',    'La operación no genera caja; requiere revisión.'),
    ],
    'YTD': [
        ('< -15%',     'Tendencia bajista fuerte',   'Caída relevante en lo que va del año.'),
        ('-15% – 0%',  'Bajista / lateral',          'Rendimiento negativo o plano en el año.'),
        ('0% – 15%',   'Alcista moderado',           'Suba saludable en el año.'),
        ('15% – 30%',  'Alcista fuerte',             'Momentum alcista fuerte en el año.'),
        ('> 30%',      'Extremadamente alcista',     'Suba muy fuerte; verificar sostenibilidad.'),
    ],
    'Precio Objetivo': [
        ('Objetivo > Precio actual', 'Upside potencial',   'Los analistas ven recorrido alcista.'),
        ('Objetivo < Precio actual', 'Downside potencial',  'Los analistas ven recorrido bajista.'),
    ],
}

_COLOR_NIVEL_MAP = {
    'Muy bajo': '#f85149', 'Bajo': '#f0883e', 'Neutral': '#e3b341', 'Alto': '#7ee787', 'Muy alto': '#3fb950',
    'Sobreventa extrema': '#f85149', 'Sobreventa moderada': '#f0883e', 'Sobrecompra moderada': '#7ee787', 'Sobrecompra extrema': '#3fb950',
    'Sobreventa': '#f85149', 'Débil': '#f0883e', 'Fuerte': '#7ee787', 'Sobrecompra': '#3fb950',
    'Negativo': '#f85149', 'Moderado': '#e3b341', 'Bueno': '#7ee787', 'Excelente': '#3fb950',
    'Contenido': '#3fb950', 'Aceptable': '#e3b341', 'Significativo': '#f0883e', 'Severo': '#f85149',
    'Reversivo': '#e3b341', 'Aleatorio': '#8b949e', 'Persistente': '#3fb950',
    'Alcista': '#3fb950', 'Bajista': '#f85149', 'Golden Cross': '#3fb950', 'Death Cross': '#f85149',
    'Sobrecompra ': '#f85149', 'Normal': '#e3b341',
    'Muy barato': '#3fb950', 'Barato': '#7ee787', 'Exigente': '#f0883e', 'Muy exigente': '#f85149',
    'Bajo valor libro': '#e3b341', 'Razonable': '#7ee787', 'Elevado': '#f0883e', 'Muy elevado': '#f85149',
    'Atractivo': '#3fb950', 'Caro': '#f85149',
    'Excepcional': '#3fb950', 'Sólido': '#3fb950', 'Defensivo': '#7ee787', 'En línea con mercado': '#e3b341',
    'Más volátil': '#f0883e', 'Muy volátil': '#f85149', 'Saludable': '#3fb950', 'Alerta': '#f85149',
    'Sin dividendo': '#8b949e', 'Muy alto': '#f0883e', 'Contracción': '#f85149', 'Conservador': '#3fb950',
    'Riesgo de liquidez': '#f85149', 'Ajustado': '#e3b341', 'Muy líquido': '#3fb950',
    'Small Cap': '#f0883e', 'Mid Cap': '#e3b341', 'Large Cap': '#7ee787', 'Mega Cap': '#3fb950',
    'Tendencia bajista fuerte': '#f85149', 'Bajista / lateral': '#f0883e', 'Alcista moderado': '#7ee787',
    'Alcista fuerte': '#3fb950', 'Extremadamente alcista': '#e3b341',
    'Upside potencial': '#3fb950', 'Downside potencial': '#f85149', '—': '#8b949e',
}

# ==============================================================
#  UNIVERSO DE ACTIVOS
# ==============================================================


ACCIONES_POR_INDUSTRIA = {
    'Semiconductores':    ['NVDA','AMD','AVGO','TSM','ASML','QCOM','TXN','ADI','NXPI','MCHP', 'MRVL','ON','MU','INTC','ARM','GFS','STM','UMC','SNDK','MPWR', 'SYNA','QRVO','CRUS','LSCC','DIOD','RMBS','CEVA','AEHR','ALAB','ACLS', 'AMAT','LRCX','KLAC','TER','ONTO','UCTT','FORM','KLIC','CAMT','COHR', 'ENTG','SMTC','MTSI','POWI','VECO','HIMX','SIMO','INDI','ICHR'],
    'Software':           ['MSFT','ORCL','CRM','ADBE','SAP','NOW','INTU','WDAY','SNOW','PLTR', 'TEAM','HUBS','DOCU','MDB','DDOG','ESTC','BOX','ASAN','SMAR','PATH', 'PAYC','PAYX','TYL','PTC','ADSK','GWRE','MANH','PEGA','APPF', 'NCNO','QTWO','SPSC','WK','FIVN','BILL','DUOL','GTLB','BL','CVLT','PD','DBX','PCOR','RELY','MNDY','TWLO','FRSH'],
    'Ciberseguridad':     ['CRWD','PANW','ZS','FTNT','OKTA','QLYS','TENB','RPD','VRNS','NET', 'CHKP','GEN','AKAM','CSCO','FFIV','EXTR','RDWR','BB','OSIS','TLS','S','NABL','MSI','LDOS','LHX','SAIC','CACI', 'MRCY','ANET','VRSN','DOCN','BLZE','AI','IBM','ORCL','DDOG','NET'],
    'Cloud/AI':           ['MSFT','AMZN','GOOGL','META','ORCL','IBM','SNOW','MDB','DDOG','NET', 'PLTR','AI','CFLT','ESTC','SMCI','DELL','NVDA','AMD','CRM','SAP', 'NOW','INTU','ADBE','PATH','AKAM','GTLB','APP','ANET','HPE','NTAP', 'PSTG','BOX','ASAN','ARM','TSM','AVGO','COHR','VRT','EQIX','DLR', 'CIEN','SNPS','CDNS','MU','SNDK','WDC','CRWV','DOCN','FSLY','RBRK'],
    'Hardware/Equipos':   ['AAPL','DELL','HPE','HPQ','SMCI','CSCO','ANET','NTAP','PSTG','STX', 'WDC','SNDK','GLW','LOGI','JNPR','CIEN','KEYS','ZBRA','FLEX','SANM', 'ARW','JBL','APH','TEL','PLXS','FN','COMM','CRDO','LITE','COHR', 'IPGP','VSH','BELFA','TTMI','KLIC','CAMT','AEIS','MTSI','OLED','VRT', 'CDNS','SNPS','TER','ENTG','RMBS','SIMO','HIMX','AZTA','SMTC','FORM'],
    'Fintech':            ['XYZ','PYPL','AFRM','SOFI','UPST','LC','ENVA','NU','STNE','PAGS', 'DLO','PAYO','MQ','FOUR','COIN','HOOD','GPN','FI','FIS','JKHY', 'EEFT','PAY','FLT','WU','RM','NVEI','PSFE','BILL','MARA','RIOT', 'CIFR','CLSK','IREN','BTDR','CORZ','GLXY','BMNR','HUT','BTM','ML'],
    'Biotecnología':      ['AMGN','REGN','VRTX','GILD','BIIB','MRNA','BNTX','ALNY','INCY','EXEL', 'NBIX','HALO','IONS','LEGN','SRPT','CRSP','NTLA','BEAM','EDIT','RXRX', 'RNA','DNLI','ADPT','XENE','SANA','VERV','ARWR','FOLD','BMRN','TECH', 'ABCL','NTRA','GH','CDNA','PACB','TWST','ILMN','OMIC','RARE','ACAD', 'KYMR','CGON','IMVT','APLS','RVMD','MRUS','AUTL','BLUE','KROS','XNCR'],
    'Farmacéuticas':      ['LLY','JNJ','PFE','MRK','ABBV','BMY','AZN','NVO','NVS','SNY', 'GSK','TAK','TEVA','VTRS','OGN','BHC','RDY','EYPT','ZTS','ELV', 'CVS','HIMS','PHR','SUPN','ITCI','ACAD','ARRY','CPRX','BCRX','AMRX', 'PRGO','EOLS','AMPH','ANIP','COLL','EGRX','KNSA','MYOV','NGM','TVTX', 'XERS','ZYME','SLNO','ADMA','PTGX','ARDX','CRNX','MNKD','HROW','ETON'],
    'Equipos Médicos':    ['ISRG','ABT','SYK','BSX','MDT','EW','ZBH','BDX','BAX','HOLX', 'DXCM','PODD','MASI','RMD','STE','TFX','ICUI','HAE','OMCL','PEN', 'GKOS','INSP','NVCR','ALGN','XRAY','SEM','LIVN','IRTC','TMDX','PROF', 'LNTH','NEOG','OSUR','AXNX','SIBN','NARI','OFIX','AVNS','AORT','CVAC', 'PHG','SONVY','GEHC','SOLV','STER','MMSI','ENVX','ATRC','OM','SKTX'],
    'Servicios de Salud': ['UNH','ELV','CI','HUM','CVS','CNC','MOH','OSCR','DVA','HCA', 'UHS','THC','EHC','ACHC','SEM','LFST','PGNY','DOCS','AMED','ENSG', 'CHE','PNTG','FMS','OPCH','ADUS','SGRY','BKD','PACS','GH','DGX', 'LH','NEO','MEDP','IQV','ICON','SYNH','CRL','CTLT','TDOC','VEEV', 'EVH','AGL','ALHC','PRVA','ACCD','ONEM','SHC','ARDT','HIMS','LFMD'],
    'Bancos':             ['JPM','BAC','WFC','C','GS','MS','USB','PNC','TFC','COF', 'BK','STT','MTB','FITB','HBAN','RF','CFG','KEY','CMA','ZION', 'FHN','WTFC','EWBC','ONB','SNV','BPOP','FULT','FFIN','CADE','UBSI', 'ASB','OZK','PNFP','WBS','HOMB','BKU','SBSI','IBOC','TCBI','COLB', 'WAL','FIBK','FCNCA','CVBF','CATY','BANF','NBHC','GBCI','SFNC','FNB'],
    'Seguros':            ['BRK-B','PGR','CB','TRV','ALL','AFL','MET','PRU','AIG','HIG', 'CINF','WRB','RGA','LNC','GL','UNM','EG','MKL','BRO','AON', 'MMC','AJG','WTW','ACGL','RLI','ORI','KNSL','THG','AXS','RE', 'PFG','VOYA','SLF','MFC','EQH','AMP','FNF','FAF','AIZ','CNO', 'PIPR','JRVR','UFCS','NMIH','ESNT','MTG','RDN','HCI','TRUP','ROOT'],
    'Mercados Capitales': ['BX','KKR','APO','ARES','CG','OWL','BAM','BN','SCHW','IBKR', 'CME','ICE','NDAQ','MKTX','MS','GS','RJF','EVR','LAZ','PIPR', 'SF','LPLA','HOOD','COIN','SEIC','BEN','TROW','BLK','IVZ','AMG', 'JHG','PFG','CNS','MC','PJT','HLI','TREE','OPY','VIRT','XP', 'STNE','NMR','NOMD','DB','UBS','CS','RY','TD','BMO','BNS'],
    'Bancos Regionales':  ['FITB','HBAN','RF','CFG','ZION','FHN','WTFC','KEY','CMA','MTB', 'EWBC','ONB','SNV','FULT','FFIN','CADE','UBSI','ASB','OZK','PNFP', 'WBS','HOMB','BKU','SBSI','IBOC','TCBI','COLB','WAL','FIBK','FCNCA', 'CVBF','BANF','NBHC','GBCI','SFNC','FNB','CATY','PACW','UCBI','INDB'],
    'Finanzas Diversif.': ['V','MA','AXP','DFS','SYF','ALLY','COF','CACC','SLM','NAVI', 'RKT','OMF','WU','GPN','FI','FIS','JKHY','FLT','EEFT','PAY', 'PYPL','XYZ','AFRM','SOFI','UPST','LC','HOOD','COIN','NU','STNE', 'PAGS','DLO','PAYO','MQ','FOUR','TRU','EFX','EXPGY','SPGI','MCO', 'FICO','CINF','AMP','VOYA','EQH','BEN','TROW','BLK','IVZ','JHG'],
    'Petróleo Integrado': ['XOM','CVX','COP','EOG','OXY','DVN','MRO','APA','FANG','HES', 'PXD','CTRA','EQT','AR','RRC','CNX','CIVI','SM','MTDR','PR', 'MPC','PSX','VLO','PBF','DK','SUN','MUSA','SLB','HAL','BKR', 'NOV','CHX','LBRT','NBR','PTEN','HP','WTTR','TDW','RIG','VAL', 'PBR','SHEL','BP','TTE','EQNR','ENI','REPYY','YPF','VIST','EC'],
    'Energía Renovable':  ['NEE','BEP','BEPC','CWEN','CWEN-A','NEP','AES','ORA','AY', 'ENPH','FSLR','SEDG','RUN','ARRY','NXT','SHLS','FLNC','STEM', 'BE','PLUG','GEV','VRT','CSIQ','JKS','MAXN','NOVA','SPWR', 'AMRC','HASI','RNW','BLDP','HYLN','EVGO','CHPT','FREY', 'SES','EOSE','ENVX','SLDP','QS','MVST','LICY','LAC','ALTM','PLL'],
    'Gas Natural':        ['LNG','EQT','AR','RRC','CNX','KMI','WMB','OKE','TRGP','ET', 'EPD','MPLX','PAA','AM','DTM','HESM','KGS','MGY','CRK','GPOR', 'CTRA','OVV','SM','CIVI','EXE','NFG','SWX','ATO','NWN','UGI', 'NI','OGS','POR','SJI','SR','CPK','MMP','ENLC','WES','PAGP', 'GLNG','FLNG','GLOP','TGS','TGNP','ENB','TRP','KEYUF','KNTK','HUN'],
    'Energía Solar':      ['FSLR','ENPH','SEDG','RUN','ARRY','NXT','SHLS','CSIQ','JKS','MAXN', 'NOVA','SPWR','EMBK','BE','PLUG','FLNC','STEM','AMRC','ORA', 'NEE','CWEN','BEP','BEPC','NEP','AES','GEV','VRT','HASI','RNW', 'BLDP','CHPT','EVGO','EOSE','FREY','SES','SLDP','QS','ENVX','MVST'],
    'Aeroespacial':       ['BA','RTX','LMT','NOC','GD','HII','TDG','HEI','HEI-A','CW','TXT','KTOS','AVAV','BWXT','LHX','LDOS','MRCY','OSIS','SPR','COL','HON','AER','AJRD','IRDM','MAXR','RKLB','SPCE','ASTS','DRS','NOC','LMT','RTX','GD','BA','HII','TDG','HEI','CW','VSEC','ATRO','HXL','CWST','KAMN','TGI','MOG-A','DCO','ESLT','ARL','AVX','HEI-A','AIM','JOBY','ACHR','EH','LILAK','NNDM','PL'],
    'Transporte':         ['UPS','FDX','UNP','CSX','NSC','JBHT','ODFL','XPO','CHRW','EXPD', 'KEX','MATX','ZIM','DAC','SBLK','GOGL','PANL','GNK','TRTN','SFL', 'CAI','SINO','NM','DSX','LPG','STNG','INSW','TNK','EURN','FRO'],
    'Construcción':       ['CAT','DE','EMR','ETN','HON','GE','ROK','PH','ITW','MMM', 'VMC','MLM','EXP','BLDR','NVR','DHI','LEN','PHM','KBH','TOL', 'JCI','TT','URI','PWR','FIX','MTZ','ACM','FLR','HUBG','MAS'],
    'Defensa':            ['LMT','RTX','NOC','GD','HII','BA','TDG','HEI','CW','TXT', 'KTOS','AVAV','BWXT','LHX','LDOS','MRCY','OSIS','CACI','SAIC','NOC', 'GD','RTX','LMT','HII','BA','TDG','CW','HEI','TXT','KTOS'],
    'Retail':             ['AMZN','WMT','TGT','COST','HD','LOW','TJX','ROST','DG','DLTR', 'BBY','KR','BJ','WBA','CVS','ULTA','M','KSS','JWN','GPS', 'BURL','FIVE','WSM','RH','ORLY','AZO','AAP','TSCO','Ollies','OLLI', 'FND','TPR','RL','NKE','DECK','CROX','LEVI','PVH','URBN','AEO'],
    'Autos':              ['TSLA','GM','F','TM','HMC','STLA','RIVN','LCID','NIO','XPEV', 'LI','FCAU','MBGYY','BMWYY','VWAGY','RACE','GM','F','APTV','BWA', 'VC','GT','LEA','ALV','HOG','PII','THO','MBLY','ZK','XPEL'],
    'Hotelería/Viajes':   ['MAR','HLT','H','IHG','ABNB','BKNG','EXPE','RCL','CCL','NCLH', 'TRIP','DESP','TCOM','LVS','MGM','WYNN','CZR','SIX','SIXF','PLAY', 'DKNG','BALY','WYNN','HLT','MAR','VAC','WH','HGV','SVC','PK'],
    'E-commerce':         ['AMZN','SHOP','ETSY','EBAY','MELI','SE','PDD','BABA','JD','CPNG', 'W','CVNA','OSTK','WISH','BZUN','EXFY','REAL','GRPN','WIX','DOCN', 'FVRR','UPWK','RBLX','TTD','APP','NET','GTLB','FSLY','BIGC','BOX'],
    'Alimentos':          ['KO','PEP','MDLZ','KHC','GIS','CPB','SJM','K','KDP','HSY', 'MDLZ','TSN','HRL','ADM','BG','CHD','CLX','CAG','POST','MKC', 'EL','PG','UL','NOMD','LANC','COKE','FLO','DAR','INGR','SMPL'],
    'Bebidas':            ['KO','PEP','MNST','STZ','BUD','TAP','DEO','KDP','CELH','FIZZ', 'PRMW','CCEP','FMX','SAM','BFB','BUD','TAP','WULF','COKE','NAPA', 'VIV','BRBR','SPB','SOVO','REX','KOF','ABEV','CCU','AGRO','COTY'],
    'Minería Oro':        ['NEM','GOLD','AEM','WPM','KGC','PAAS','AG','CDE','HL','SSRM', 'NGD','AUX','DRD','BTG','EGO','HMY','IAG','AU','SA','GFI', 'OR','FNV','RGLD','KNT','WDO','EQX','TGB','SILV','BVN','CGAU'],
    'Cobre/Metales':      ['FCX','SCCO','TECK','HBM','NUE','STLD','CLF','NUE','AA','CDE', 'KGC','PAAS','AG','HL','WPM','AEM','NEM','GOLD','SSRM','NGD', 'ERO','LUNMF','LAC','ALB','PLL','MP','CRS','ATI','X','HBM','TECK'],
    'Químicos':           ['LIN','APD','DD','DOW','LYB','EMN','CE','IFF','PPG','SHW', 'ECL','ALB','FMC','CF','MOS','NTR','OLN','ASH','AVNT','HUN', 'X','BC','RPM','WLK','TSE','SXT','SCL','NEU','IOSP','CBT'],
    'Acero':              ['NUE','STLD','CLF','X','MT','RS','CMC','SID','GGB','TX', 'PKX','NWL','CRS','ATI','SCHN','ZEUS','NBR','X','STLD','CLF', 'CLF','NUE','STLD','CMC','MT','RS','X','PKX','SID','GGB'],
    'Eléctricas':         ['NEE','DUK','SO','D','AEP','EXC','XEL','ED','ETR','PEG', 'PCG','PPL','FE','ES','EIX','AES','CNP','NI','ATO','LNT', 'WEC','CMS','DTE','SRE','XEL','EVRG','IDA','BEP','BEPC','NEP', 'ORA','PEGI','UGI','BIP','BIPC','AVA','PNW','NRG','NRZ','CVA'],
    'Agua':               ['AWK','WTRG','WTR','AWR','YORW','MSEX','SJW','CWCO','GWRS','ARTNA', 'PNW','AWK','AWK','WTRG','SJW','CWT','CWT','SJW','AWR','YORW', 'WSO','AQUA','ECL','XYL','PUMP','GRC','MEG','H2O','CWCO','PRMW'],
    'REIT Comercial':     ['SPG','O','VICI','NNN','BXP','KIM','REG','MAC','PEAK','FRT', 'SLG','EPR','WPC','ARE','HST','PK','VNO','CUZ','HIW','KRC', 'DEI','BRX','ADC','STAG','PLD','EQIX','DLR','CONE','COR','AMT', 'CCI','SBAC','WY','IRM','GOOD','LAND','SLG','BXP','O','SPG'],
    'REIT Industrial':    ['PLD','AMT','CCI','DLR','EQIX','STAG','EGP','FR','REXR','TRNO', 'PLYM','LXP','COLD','ILPT','PSTL','STAG','IRM','CUBE','GOOD','O', 'PLD','EQIX','DLR','AMT','CCI','SBAC','CONE','COR','DLR','PLD'],
    'REIT Residencial':   ['EQR','AVB','ESS','MAA','UDR','CPT','ELS','AIV','NXRT','INVH', 'IRT','AMH','BRG','SUI','NXRT','MHC','UMH','ESS','EQR','AVB', 'UDR','MAA','CPT','INVH','AMH','SUI','ELS','AIRC','CUBE','CPT'],
    'Telecomunicaciones': ['T','VZ','TMUS','S','CHTR','CMCSA','LUMN','FYBR','VOD','BT', 'ORAN','TEF','TU','BCE','RCI','SKM','ZL','AMX','TIGO','TDS', 'ATUS','WOW','CNSL','QCOM','AMT','CCI','SBAC','WBD','NFLX','DIS', 'TMUS','VZ','T','CMCSA','CHTR','S','LUMN','VOD','BT','TEF'],
    'Internet':           ['GOOGL','META','NFLX','SNAP','PINS','RDDT','SPOT','ROKU','IAC','MTCH', 'BMBL','YELP','DASH','UBER','LYFT','SHOP','SE','MELI','ETSY','EBAY', 'BABA','JD','PDD','BIDU','NTES','WB','IQ','TME','WIX','RBLX', 'DUOL','TTD','PUBM','APP','NET','AKAM','DOCN','GTLB','BOX','ZI', 'YEXT','COUR','CHGG','RUM','VKTX','CRWV','FSLY','CFLT','DBX','TASK'],
    'Argentina':          ['GGAL', 'BMA', 'BBAR', 'SUPV', 'CEPU', 'YPF', 'PAM', 'TGS', 'CRESY', 'LOMA', 'VIST', 'IRCP', 'EDN', 'TRAN', 'IRS', 'DESP', 'GLOB', 'BIOX', 'MTR', 'AGRO', 'PGR', 'SBS'],
    'Brasil':             ['VALE','ITUB','PBR','BBD','ABEV','NU'],
    'China':              ['BABA','TCEHY','BIDU','JD','NIO','LI','XPEV','BYDDF','PDD','NTES'],
    'India':              ['INFY','WIT','HDB','IBN','VEDL','RDY','TTM'],
    'Europa Tecnología':  ['SAP','ASML','IFNNY','NXPI'],
    'Europa Finanzas':    ['HSBC','BBVA','SAN','DBK.DE','LLOY.L','UBS','ING'],
    'Agro/Fertilizantes': ['MOS','NTR','CF','ADM','BG','FMC','CTVA'],
    'Cripto (ETF/Coin)':  ['BTC-USD','ETH-USD','SOL-USD','BNB-USD','XRP-USD','ADA-USD','DOGE-USD','AVAX-USD','DOT-USD','MATIC-USD', 'LINK-USD','LTC-USD','ATOM-USD','ETC-USD','XLM-USD','FIL-USD','ICP-USD','HBAR-USD','NEAR-USD','ARB-USD', 'COIN','MARA','RIOT','CLSK','HUT','BITF','BTDR','IREN','CAN','WULF'],
}



TICKER_INDUSTRY = {}
for ind, lst in ACCIONES_POR_INDUSTRIA.items():
    for t in lst:
        if t not in TICKER_INDUSTRY:
            TICKER_INDUSTRY[t] = ind


ALL_TICKERS = sorted(set(t for lst in ACCIONES_POR_INDUSTRIA.values() for t in lst))


FOREX = {
    # --- Majors ---
    'EUR/USD': ('EURUSD=X', 'Majors'),
    'GBP/USD': ('GBPUSD=X', 'Majors'),
    'USD/JPY': ('USDJPY=X', 'Majors'),
    'USD/CHF': ('USDCHF=X', 'Majors'),
    'USD/CAD': ('USDCAD=X', 'Majors'),
    'AUD/USD': ('AUDUSD=X', 'Majors'),
    'NZD/USD': ('NZDUSD=X', 'Majors'),
    'USD/CNY': ('USDCNY=X', 'Majors'),

    # --- Crosses EUR ---
    'EUR/GBP': ('EURGBP=X', 'Crosses EUR'),
    'EUR/JPY': ('EURJPY=X', 'Crosses EUR'),
    'EUR/CHF': ('EURCHF=X', 'Crosses EUR'),
    'EUR/AUD': ('EURAUD=X', 'Crosses EUR'),
    'EUR/CAD': ('EURCAD=X', 'Crosses EUR'),

    # --- Crosses GBP ---
    'GBP/JPY': ('GBPJPY=X', 'Crosses GBP'),
    'GBP/AUD': ('GBPAUD=X', 'Crosses GBP'),
    'GBP/CAD': ('GBPCAD=X', 'Crosses GBP'),

    # --- Crosses AUD/NZD ---
    'AUD/JPY': ('AUDJPY=X', 'Crosses AUD'),
    'AUD/CAD': ('AUDCAD=X', 'Crosses AUD'),
    'AUD/NZD': ('AUDNZD=X', 'Crosses AUD'),
    'NZD/JPY': ('NZDJPY=X', 'Crosses NZD'),

    # --- Crosses JPY/CHF ---
    'CAD/JPY': ('CADJPY=X', 'Crosses JPY'),
    'CHF/JPY': ('CHFJPY=X', 'Crosses JPY'),

    # --- LatAm ---
    'USD/ARS': ('USDARS=X', 'LatAm'),
    'USD/BRL': ('USDBRL=X', 'LatAm'),
    'USD/MXN': ('USDMXN=X', 'LatAm'),
    'USD/CLP': ('USDCLP=X', 'LatAm'),
    'USD/COP': ('USDCOP=X', 'LatAm'),
    'USD/PEN': ('USDPEN=X', 'LatAm'),
    'USD/UYU': ('USDUYU=X', 'LatAm'),
}


PAISES = {
    'EE.UU. S&P500':    ('^GSPC',  'América'),
    'EE.UU. NASDAQ':    ('^NDX',   'América'),
    'EE.UU. DOW':       ('^DJI',   'América'),
    'EE.UU. Russell':   ('^RUT',   'América'),
    'Argentina':        ('^MERV',  'América'),
    'Brasil':           ('^BVSP',  'América'),
    'Japón':            ('^N225',  'Asia'),
    'China':            ('^HSI',   'Asia'),
    'Corea del Sur':    ('^KS11',  'Asia'),
    'India':            ('^NSEI',  'Asia'),
    'Alemania':         ('^GDAXI', 'Europa'),
    'Europa general':   ('^STOXX50E', 'Europa'),
    'Gran Bretaña':   ('^FTSE',  'Europa'),
    'Francia':   ('^FCHI',  'Europa'),
}

# --- ETFs (Índices + Sectores, todo junto) ---
ETFS = {
    # Índices (ETF que los replica)
    'EE.UU. S&P500':    ('SPY',  'Índices', '#3a7bd5'),
    'EE.UU. NASDAQ':    ('QQQ',  'Índices', '#79c0ff'),
    'EE.UU. DOW':       ('DIA',  'Índices', '#8b949e'),
    'EE.UU. Russell':   ('IWM',  'Índices', '#bc8cff'),
    'Argentina':        ('ARGT', 'Índices', '#6cb6ff'),
    'Brasil':           ('EWZ',  'Índices', '#3fb950'),
    'Japón':            ('EWJ',  'Índices', '#f0883e'),
    'China':            ('FXI',  'Índices', '#f85149'),
    'Corea del Sur':    ('EWY',  'Índices', '#e3b341'),
    'India':            ('INDA', 'Índices', '#ffa657'),
    'Alemania':         ('EWG',  'Índices', '#d2a8ff'),
    'Europa general':   ('VGK',  'Índices', '#3a7bd5'),
    'Mercados Emerg.':  ('EEM',  'Índices', '#8b949e'),
}

SECTORES_TOTAL = {
    # --- Sectores (SPDR, vista macro - 11 sectores GICS) ---
    'Tecnología':     ('XLK',  'Sectores', '#3a7bd5'),
    'Salud':          ('XLV',  'Sectores', '#3fb950'),
    'Finanzas':       ('XLF',  'Sectores', '#e3b341'),
    'Consumo Discr.': ('XLY',  'Sectores', '#f0883e'),
    'Consumo Básico': ('XLP',  'Sectores', '#bc8cff'),
    'Energía':        ('XLE',  'Sectores', '#ffa657'),
    'Industriales':   ('XLI',  'Sectores', '#79c0ff'),
    'Materiales':     ('XLB',  'Sectores', '#8b949e'),
    'Utilities':      ('XLU',  'Sectores', '#3fb950'),
    'Real Estate':    ('XLRE', 'Sectores', '#f85149'),
    'Comunicaciones': ('XLC',  'Sectores', '#d2a8ff'),

    # --- Sub-sectores (vista granular / temática) ---
    'Semiconductores':    ('SMH',  'Sub-sectores', '#3a7bd5'),
    'Software':           ('IGV',  'Sub-sectores', '#79c0ff'),
    'Ciberseguridad':     ('CIBR', 'Sub-sectores', '#f85149'),
    'Cloud/AI':           ('SKYY', 'Sub-sectores', '#bc8cff'),
    'Fintech':            ('FINX', 'Sub-sectores', '#3fb950'),
    'Biotecnología':      ('XBI',  'Sub-sectores', '#f0883e'),
    'Farmacéuticas':      ('PPH',  'Sub-sectores', '#e3b341'),
    'Equipos Médicos':    ('IHI',  'Sub-sectores', '#79c0ff'),
    'Servicios de Salud': ('IHF',  'Sub-sectores', '#3fb950'),
    'Bancos':             ('KBE',  'Sub-sectores', '#e3b341'),
    'Seguros':            ('KIE',  'Sub-sectores', '#8b949e'),
    'Mercados Capitales': ('KCE',  'Sub-sectores', '#d2a8ff'),
    'Bancos Regionales':  ('KRE',  'Sub-sectores', '#f0883e'),
    'Finanzas Diversif.': ('IYG',  'Sub-sectores', '#3a7bd5'),
    'Petróleo Integrado': ('XOP',  'Sub-sectores', '#ffa657'),
    'Energía Renovable':  ('ICLN', 'Sub-sectores', '#3fb950'),
    'Gas Natural':        ('FCG',  'Sub-sectores', '#79c0ff'),
    'Energía Solar':      ('TAN',  'Sub-sectores', '#e3b341'),
    'Aeroespacial':       ('ITA',  'Sub-sectores', '#8b949e'),
    'Transporte':         ('IYT',  'Sub-sectores', '#f0883e'),
    'Defensa':            ('XAR',  'Sub-sectores', '#6c5ce7'),
    'Retail':             ('XRT',  'Sub-sectores', '#f85149'),
    'Autos':              ('CARZ', 'Sub-sectores', '#3a7bd5'),
    'Hotelería/Viajes':   ('PEJ',  'Sub-sectores', '#ffa657'),
    'E-commerce':         ('IBUY', 'Sub-sectores', '#bc8cff'),
    'Alimentos':          ('PBJ',  'Sub-sectores', '#3fb950'),
    'Minería Oro':        ('GDX',  'Sub-sectores', '#e3b341'),
    'Cobre/Metales':      ('COPX', 'Sub-sectores', '#cd7f32'),
    'Acero':              ('SLX',  'Sub-sectores', '#79c0ff'),
    'Eléctricas':         ('XLU',  'Sub-sectores', '#3fb950'),
    'Agua':               ('PHO',  'Sub-sectores', '#3a7bd5'),
    'REIT Industrial':    ('INDS', 'Sub-sectores', '#8b949e'),
    'REIT Residencial':   ('REZ',  'Sub-sectores', '#3fb950'),
    'Telecomunicaciones': ('IYZ',  'Sub-sectores', '#d2a8ff'),
    'Internet':           ('FDN',  'Sub-sectores', '#3a7bd5'),
}

# ← AGREGAR ESTA LÍNEA:
SECTORES = {nombre: (tk, color) for nombre, (tk, cat, color) in SECTORES_TOTAL.items()}
SECTORES_GICS = {nombre: (tk, color) for nombre, (tk, cat, color) in SECTORES_TOTAL.items() if cat == 'Sectores'}
SUBSECTORES   = {nombre: (tk, color) for nombre, (tk, cat, color) in SECTORES_TOTAL.items() if cat == 'Sub-sectores'}

SUBSECTOR_A_SECTOR = {
    'Semiconductores': 'Tecnología', 'Software': 'Tecnología',
    'Ciberseguridad': 'Tecnología', 'Cloud/AI': 'Tecnología',
    'Fintech': 'Finanzas', 'Bancos': 'Finanzas', 'Seguros': 'Finanzas',
    'Mercados Capitales': 'Finanzas', 'Bancos Regionales': 'Finanzas',
    'Finanzas Diversif.': 'Finanzas',
    'Biotecnología': 'Salud', 'Farmacéuticas': 'Salud',
    'Equipos Médicos': 'Salud', 'Servicios de Salud': 'Salud',
    'Petróleo Integrado': 'Energía', 'Energía Renovable': 'Energía',
    'Gas Natural': 'Energía', 'Energía Solar': 'Energía',
    'Aeroespacial': 'Industriales', 'Transporte': 'Industriales', 'Defensa': 'Industriales',
    'Retail': 'Consumo Discr.', 'Autos': 'Consumo Discr.',
    'Hotelería/Viajes': 'Consumo Discr.', 'E-commerce': 'Consumo Discr.',
    'Alimentos': 'Consumo Básico',
    'Minería Oro': 'Materiales', 'Cobre/Metales': 'Materiales', 'Acero': 'Materiales',
    'Eléctricas': 'Utilities', 'Agua': 'Utilities',
    'REIT Industrial': 'Real Estate', 'REIT Residencial': 'Real Estate',
    'Telecomunicaciones': 'Comunicaciones', 'Internet': 'Comunicaciones',
}

COLORES_SECTOR_PADRE = {nombre: color for nombre, (tk, color) in SECTORES_GICS.items()}

MERCADOS_REALES = {
    # --- Energía ---
    'Petróleo WTI':   ('CL=F',    'Energía',      '#f0883e'),
    'Petróleo Brent': ('BZ=F',    'Energía',      '#ffa657'),
    'Gas Natural':    ('NG=F',    'Energía',      '#79c0ff'),
    'Gasolina RBOB':  ('RB=F',    'Energía',      '#ff9e64'),
    'Heating Oil':    ('HO=F',    'Energía',      '#ff7b72'),
    'Uranio (ETF)':   ('URA',     'Energía',      '#56d364'),

    # --- Metales Preciosos ---
    'Oro':     ('GC=F', 'Met. Prec.', '#e3b341'),
    'Plata':   ('SI=F', 'Met. Prec.', '#8b949e'),
    'Platino': ('PL=F', 'Met. Prec.', '#bc8cff'),
    'Paladio': ('PA=F', 'Met. Prec.', '#d2a8ff'),

    # --- Metales Industriales / Tierras Raras ---
    'Cobre':          ('HG=F',  'Met. Ind.', '#cd7f32'),
    'Litio (ETF)':    ('LIT',   'Met. Ind.', '#79c0ff'),
    'Acero (ETF)':    ('SLX',   'Met. Ind.', '#8b949e'),

    # --- Minería ---
    'Mineras Oro':   ('GDX',  'Minería', '#e3b341'),
    'Mineras Plata': ('SIL',  'Minería', '#8b949e'),
    'Mineras Cobre': ('COPX', 'Minería', '#cd7f32'),
    
    # --- Agro (granos) ---
    'Soja':  ('ZS=F', 'Agro', '#3fb950'),
    'Maíz':  ('ZC=F', 'Agro', '#7ee787'),
    'Trigo': ('ZW=F', 'Agro', '#ffa657'),
    'Avena': ('ZO=F', 'Agro', '#a4e494'),
    'Arroz': ('ZR=F', 'Agro', '#c9e88c'),

    # --- Blandos (Softs) ---
    'Café':             ('KC=F', 'Blandos', '#a0754b'),
    'Azúcar':           ('SB=F', 'Blandos', '#f3d9a4'),
    'Algodón':          ('CT=F', 'Blandos', '#eaeaea'),
    'Cacao':            ('CC=F', 'Blandos', '#7a4b2a'),

    # --- Cripto (Coins) ---
    'Bitcoin':    ('BTC-USD',  'Cripto', '#f0883e'),
    'Ethereum':   ('ETH-USD',  'Cripto', '#7ee787'),
    'Solana':     ('SOL-USD',  'Cripto', '#bc8cff'),
    'BNB':        ('BNB-USD',  'Cripto', '#f3ba2f'),
    'XRP':        ('XRP-USD',  'Cripto', '#3a7bd5'),
    'Cardano':    ('ADA-USD',  'Cripto', '#2a71d0'),
    'Dogecoin':   ('DOGE-USD', 'Cripto', '#e8b923'),
    'Avalanche':  ('AVAX-USD', 'Cripto', '#e84142'),
    'Polkadot':   ('DOT-USD',  'Cripto', '#e6007a'),
    'Chainlink':  ('LINK-USD', 'Cripto', '#2a5ada'),
    'Litecoin':   ('LTC-USD',  'Cripto', '#bebebe'),
    'Cosmos':     ('ATOM-USD', 'Cripto', '#2e3148'),
    'Ethereum Classic':('ETC-USD','Cripto','#328332'),
    'Stellar':    ('XLM-USD',  'Cripto', '#08b5e5'),
    'Filecoin':   ('FIL-USD',  'Cripto', '#0090ff'),
    'Internet Computer':('ICP-USD','Cripto','#3b00b9'),
    'Hedera':     ('HBAR-USD', 'Cripto', '#4b4b4b'),
    'Near':       ('NEAR-USD', 'Cripto', '#000000'),
    'Arbitrum':   ('ARB-USD',  'Cripto', '#28a0f0'),

    # --- Cripto (ETF / Mineras) ---
    'Coinbase':   ('COIN',  'Cripto ETF', '#0052ff'),
    'Marathon Digital':('MARA','Cripto ETF','#f7931a'),
    'Riot Platforms':  ('RIOT', 'Cripto ETF', '#e8412f'),
    'CleanSpark':      ('CLSK', 'Cripto ETF', '#00b894'),
    'Hut 8':           ('HUT',  'Cripto ETF', '#6c5ce7'),
    'Bitdeer':         ('BTDR', 'Cripto ETF', '#fdcb6e'),
    'Iris Energy':     ('IREN', 'Cripto ETF', '#74b9ff'),
    'Canaan':          ('CAN',  'Cripto ETF', '#a29bfe'),
    'TeraWulf':        ('WULF', 'Cripto ETF', '#fab1a0'),
}

COLORES_GRUPO_FX  = {'Majors':'#3a7bd5','Crosses EUR':'#f0883e','Crosses GBP':'#7ee787','Crosses AUD':'#bc8cff','LatAm':'#f85149'}
COLORES_REGION    = {'América':'#3a7bd5','Asia':'#f0883e','Europa':'#7ee787','Global':'#bc8cff'}


# ==============================================================
#  AUTOCOMPLETE — universo de búsqueda combinado
# ==============================================================


def _build_universo_buscador():
    opciones, mapa = [], {}
    for t in ALL_TICKERS:
        opciones.append(t); mapa[t] = t
    for nombre, (tk, _) in FOREX.items():
        label = f'{nombre} · {tk}'
        opciones.append(label); mapa[label] = tk
    for nombre, (tk, _) in PAISES.items():
        label = f'{nombre} (ETF {tk})'
        opciones.append(label); mapa[label] = tk
    for nombre, (tk, _) in SECTORES.items():
        label = f'{nombre} (ETF {tk})'
        opciones.append(label); mapa[label] = tk
    for nombre, (tk, cat, _) in MERCADOS_REALES.items():
        label = f'{nombre} · {tk}'
        opciones.append(label); mapa[label] = tk
    return sorted(set(opciones)), mapa


UNIVERSO_OPCIONES, UNIVERSO_MAPA = _build_universo_buscador()
OPCION_MANUAL = '✏️ Otro símbolo (escribir manualmente)'


def selector_ticker_autocomplete(key, prefill='', label='Buscar activo'):
    """Selectbox con filtro por escritura (autocomplete nativo de Streamlit) + fallback manual.
    Importante: forzamos el valor vía session_state (no con index=) porque Streamlit ignora
    'index' una vez que el widget ya existe en la sesión — así el prefill (chips, accesos rápidos)
    funciona siempre, no solo la primera vez que se usa el buscador."""
    opciones = [OPCION_MANUAL] + UNIVERSO_OPCIONES
    sel_key = f'{key}_sel'
    if prefill:
        pf = prefill.strip().upper()
        match = next((o for o in UNIVERSO_OPCIONES if UNIVERSO_MAPA.get(o, '').upper() == pf or o.upper() == pf), None)
        if match and st.session_state.get(sel_key) != match:
            st.session_state[sel_key] = match
    elegido = st.selectbox(
        label, opciones, key=sel_key,
        help='Escribí para filtrar: acciones, ETFs, forex, commodities y cripto.',
        label_visibility='collapsed',
    )
    if elegido == OPCION_MANUAL:
        manual = st.text_input(
            'Símbolo manual', value=prefill, key=f'{key}_manual',
            placeholder='Ej: NVDA · BTC-USD · EURUSD=X · GC=F',
        )
        return manual.strip().upper()
    val = UNIVERSO_MAPA.get(elegido, elegido)
    return val.strip().upper()


# ==============================================================
#  DESCARGA DE DATOS
# ==============================================================


@st.cache_data(ttl=1800, show_spinner=False)
def descargar_datos(ticker, period='3mo'):
    try:
        import yfinance as yf
        d = yf.download(ticker, period=period, interval='1d', progress=False, auto_adjust=True)
        if d is None or d.empty: return None
        if isinstance(d.columns, pd.MultiIndex): d.columns = d.columns.get_level_values(0)
        if 'Close' not in d.columns:
            cols_close = [c for c in d.columns if 'close' in str(c).lower()]
            if cols_close: d = d.rename(columns={cols_close[0]: 'Close'})
            else: return None
        return d.dropna(subset=['Close'])
    except Exception: return None


@st.cache_data(ttl=3600, show_spinner=False)
def descargar_bulk(tickers, period='2y'):
    try:
        import yfinance as yf
        df_all = yf.download(tickers, period=period, interval='1d',
                             auto_adjust=True, progress=False, group_by='ticker')
        return df_all
    except Exception: return None


def get_close_series(df):
    if df is None: return None
    try:
        if isinstance(df, pd.Series): return df.dropna()
        if 'Close' in df.columns:
            c = df['Close']
            if isinstance(c, pd.DataFrame): c = c.iloc[:,0]
            return c.dropna()
        for col in df.columns:
            if 'close' in str(col).lower(): return df[col].dropna()
        return None
    except: return None


def get_close_from_bulk(df_all, ticker):
    try:
        if isinstance(df_all.columns, pd.MultiIndex):
            if (ticker, 'Close') in df_all.columns:
                return df_all[(ticker, 'Close')].dropna().astype(float)
            elif ('Close', ticker) in df_all.columns:
                return df_all[('Close', ticker)].dropna().astype(float)
        return pd.Series(dtype=float)
    except: return pd.Series(dtype=float)


# ==============================================================
#  INDICADORES — CORTO PLAZO
# ==============================================================


def calcular_atr(df, p=14):
    if df is None: return None
    try:
        h = df.get('High'); l = df.get('Low'); c = get_close_series(df)
        if h is None or l is None or c is None: return None
        tr = pd.concat([h-l, abs(h-c.shift(1)), abs(l-c.shift(1))], axis=1).max(axis=1)
        return tr.rolling(p).mean()
    except: return None


def pct_rank(serie):
    s = pd.Series(serie).dropna()
    if len(s) < 5: return 50.0
    return float((s < s.iloc[-1]).sum() / len(s) * 100)


def calcular_rsi(close, p=14):
    s = pd.Series(close).dropna()
    d = s.diff()
    g = d.clip(lower=0).rolling(p).mean()
    l = (-d.clip(upper=0)).rolling(p).mean()
    rs = g / l.replace(0, np.nan)
    return (100 - (100/(1+rs))).fillna(50)


def vol_anual_rolling(close, v=20):
    s = pd.Series(close).dropna()
    return s.pct_change().rolling(v).std() * np.sqrt(252) * 100


def scores_corto(close_vol, close_mp, atr):
    cv = pd.Series(close_vol).dropna()
    cm = pd.Series(close_mp).dropna()
    if len(cv) < 15 or len(cm) < 5: return 50.0, 50.0, 50.0
    precio_pct = pct_rank(cv)
    rsi_pct    = 100 - pct_rank(calcular_rsi(cv, p=7))
    vol_pct    = 100 - pct_rank(vol_anual_rolling(cv, 10))
    sc_acum    = (100-precio_pct)*0.40 + rsi_pct*0.35 + vol_pct*0.25
    ret20 = float(cm.pct_change(5).iloc[-1]*100) if len(cm)>=6 else 0
    if np.isnan(ret20): ret20=0
    mom = min(100, max(0, 50+ret20*2.0))
    if atr is not None:
        atr_s = pd.Series(atr).dropna()
        comp_atr = max(0,min(100,100-(float(atr_s.iloc[-1])/float(atr_s.mean())*50))) if len(atr_s)>5 else 50
    else: comp_atr=50
    bbw = (cm.rolling(10).std()/cm.rolling(10).mean().replace(0,np.nan)*100).dropna()
    bb_c = 100-pct_rank(bbw) if len(bbw)>5 else 50
    sc_antic = mom*0.40+comp_atr*0.30+bb_c*0.30
    return round(sc_acum,1), round(sc_antic,1), round(pct_rank(cv),1)


def señal_accion_corto(sa, sn, ss):
    if   sa>=62 and sn>=55:            return '🟢 ACUMULAR'
    elif sa>=62 and sn>=40:            return '🟡 VIGILAR'
    elif sa>=58 and sn<40:             return '🔵 ACUMULAR GRADUAL'
    elif sa<45  and sn>=62 and ss>=62: return '🚀 TENDENCIA ALCISTA'
    elif sn>=65 and 40<=sa<62:         return '⚡ MOVIMIENTO INMINENTE'
    elif sa<38  and sn<42  and ss>=65: return '⚠️ EN MÁXIMOS'
    elif sa>=55 and sn<35  and ss<35:  return '🔴 EVITAR'
    elif sa<38  and sn>=55 and ss<40:  return '🟠 POSIBLE REBOTE'
    else:                              return '⏸️ ESPERAR'


def calcular_regimen_hmm(cl, n_states=3, min_obs=120):
    """Ajusta un Hidden Markov Model Gaussiano sobre los retornos logarítmicos
    y determina el régimen actual (bajista/neutral/alcista) del activo, junto
    con la probabilidad (confianza) de ese estado. Requiere mínimo 6 meses
    de historial (min_obs=120 ruedas ≈ 6 meses hábiles)."""
    if not HMM_OK:
        return None
    try:
        s = pd.Series(cl).dropna().astype(float)
        if len(s) < min_obs:
            return None
        log_ret = np.log(s / s.shift(1)).dropna()
        if len(log_ret) < min_obs:
            return None
        X = log_ret.values.reshape(-1, 1)
        modelo = GaussianHMM(n_components=n_states, covariance_type='diag',
                              n_iter=200, random_state=42)
        modelo.fit(X)
        estados = modelo.predict(X)
        probs = modelo.predict_proba(X)

        medias = modelo.means_.flatten()
        orden = np.argsort(medias)  # de menor a mayor retorno medio
        if n_states == 3:
            etiquetas = {orden[0]: 'BAJISTA', orden[1]: 'NEUTRAL', orden[2]: 'ALCISTA'}
        elif n_states == 2:
            etiquetas = {orden[0]: 'BAJISTA', orden[1]: 'ALCISTA'}
        else:
            etiquetas = {idx: f'ESTADO {rank+1}' for rank, idx in enumerate(orden)}

        estado_actual = int(estados[-1])
        prob_actual = float(probs[-1, estado_actual])
        vol_estado = float(np.sqrt(modelo.covars_[estado_actual]).flatten()[0]) * np.sqrt(252) * 100
        ret_anual_estado = float(medias[estado_actual]) * 252 * 100

        duracion = 1
        for e in estados[-2::-1]:
            if e == estado_actual:
                duracion += 1
            else:
                break

        return dict(
            regimen=etiquetas.get(estado_actual, f'ESTADO {estado_actual}'),
            prob=round(prob_actual * 100, 1),
            ret_anual_regimen=round(ret_anual_estado, 1),
            vol_regimen=round(vol_estado, 1),
            duracion=duracion,
        )
    except Exception:
        return None
        
# ==============================================================
#  INDICADORES — LARGO PLAZO
# ==============================================================


def analizar_largo(ticker, precio_series):
    try:
        precio = precio_series.dropna().astype(float)
        if len(precio) < 150: return None
        retornos = precio.pct_change().dropna()
        delta    = precio.diff()
        avg_gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
        avg_loss = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
        rsi_v    = float((100 - 100 / (1 + avg_gain / avg_loss)).iloc[-1])
        macd      = precio.ewm(span=12,adjust=False).mean() - precio.ewm(span=26,adjust=False).mean()
        signal_m  = macd.ewm(span=9, adjust=False).mean()
        macd_bull = float(macd.iloc[-1]) > float(signal_m.iloc[-1])
        ma50  = precio.rolling(50).mean()
        ma200 = precio.rolling(200).mean()
        golden_cross = float(ma50.iloc[-1]) > float(ma200.iloc[-1])
        ma20     = precio.rolling(20).mean()
        std20    = precio.rolling(20).std()
        upper_bb = float((ma20 + 2*std20).iloc[-1])
        lower_bb = float((ma20 - 2*std20).iloc[-1])
        z_v      = float(((precio - ma20) / std20).iloc[-1])
        p_actual = float(precio.iloc[-1])
        if HURST_OK and len(precio) >= 200:
            try: H, _, _ = compute_Hc(precio.values, kind='change', simplified=True)
            except: H = 0.5
        else: H = 0.5
        rf      = 0.04
        ret_a   = float(retornos.mean()) * 252
        vol_a   = float(retornos.std()) * np.sqrt(252)
        sharpe  = (ret_a - rf) / vol_a if vol_a > 0 else 0.0
        neg     = retornos[retornos < 0]
        sortino = float((ret_a - rf) / (float(neg.std())*np.sqrt(252))) if len(neg)>5 else None
        cum     = (1 + retornos).cumprod()
        max_dd  = float(((cum / cum.cummax()) - 1).min())
        ts = 50
        if golden_cross: ts += 20
        if H > 0.55: ts += 10
        elif H < 0.45: ts -= 5
        if macd_bull: ts += 15
        if rsi_v > 50: ts += 10
        if rsi_v > 70: ts -= 5
        ts = max(0, min(100, ts))
        mr = 50
        if   -2 < z_v < -0.5:   mr += 20
        elif z_v < -2:           mr += 10
        elif -0.5 <= z_v <= 0.5: mr += 10
        elif z_v > 2:            mr -= 15
        elif z_v > 1:            mr -= 5
        if p_actual < lower_bb:  mr += 15
        elif p_actual > upper_bb:mr -= 10
        if H < 0.45:   mr += 10
        elif H > 0.65: mr -= 10
        mr = max(0, min(100, mr))
        rs = 50
        if sharpe > 2:   rs += 25
        elif sharpe > 1: rs += 15
        elif sharpe > 0: rs += 5
        else:            rs -= 15
        if sortino is not None:
            if sortino > 2:   rs += 10
            elif sortino > 1: rs += 5
            elif sortino < 0: rs -= 10
        if max_dd > -0.10:   rs += 15
        elif max_dd > -0.20: rs += 8
        elif max_dd < -0.40: rs -= 10
        if vol_a < 0.15:     rs += 10
        elif vol_a < 0.30:   rs += 5
        elif vol_a > 0.60:   rs -= 10
        rs = max(0, min(100, rs))
        gs = int((ts + mr + rs) / 3)
        rev_signal  = any([z_v < -1.0, p_actual < lower_bb, rsi_v < 35])
        rev_reasons = []
        if z_v < -1.0:          rev_reasons.append(f'Z={z_v:.2f}')
        if p_actual < lower_bb: rev_reasons.append('BajoBB')
        if rsi_v < 35:          rev_reasons.append(f'RSI={rsi_v:.1f}')
        if gs >= 70:   sesgo = 'MUY ALCISTA'
        elif gs >= 55: sesgo = 'ALCISTA'
        elif gs >= 45: sesgo = 'NEUTRAL'
        elif gs >= 30: sesgo = 'BAJISTA'
        else:          sesgo = 'MUY BAJISTA'
        return dict(
            ticker=ticker, industria=TICKER_INDUSTRY.get(ticker,'N/A'),
            precio=p_actual, ret_anual=ret_a*100, vol_anual=vol_a*100,
            rsi=rsi_v, macd_bull=macd_bull, golden_cross=golden_cross,
            hurst=H, zscore=z_v, sharpe=sharpe, sortino=sortino,
            max_dd=max_dd*100, trend_score=ts, mr_score=mr,
            risk_score=rs, global_score=gs, sesgo=sesgo,
            reversion_signal=rev_signal,
            reversion_reasons=', '.join(rev_reasons) if rev_reasons else '—',
            upper_bb=upper_bb, lower_bb=lower_bb, ma20=float(ma20.iloc[-1]),
        )
    except Exception: return None


def interpretar_largo(r):
    sesgo_txt = {
        'MUY ALCISTA': 'presenta un perfil cuantitativo muy alcista',
        'ALCISTA':     'muestra un sesgo alcista moderado',
        'NEUTRAL':     'se encuentra en zona neutral sin dirección clara',
        'BAJISTA':     'exhibe señales bajistas en el periodo analizado',
        'MUY BAJISTA': 'muestra un perfil cuantitativo claramente bajista',
    }.get(r['sesgo'], 'no tiene sesgo definido')
    lineas = [f"{r['ticker']} ({r['industria']}) {sesgo_txt}, con un Global Score de {int(r['global_score'])}/100."]
    t_parts = []
    if r['golden_cross']: t_parts.append("Golden Cross activo (MA50 > MA200)")
    else: t_parts.append("sin Golden Cross: MA50 < MA200")
    if r['macd_bull']: t_parts.append("MACD alcista")
    else: t_parts.append("MACD bajista")
    if r['hurst'] > 0.55: t_parts.append(f"Hurst {r['hurst']:.3f}: tendencia persistente")
    elif r['hurst'] < 0.45: t_parts.append(f"Hurst {r['hurst']:.3f}: comportamiento reversivo")
    else: t_parts.append(f"Hurst {r['hurst']:.3f}: próximo a paseo aleatorio")
    lineas.append("Tendencia: " + " | ".join(t_parts) + ".")
    z = r['zscore']
    if z < -2: val_txt = f"Z-Score {z:.2f}: precio muy deprimido respecto a media de 20d"
    elif z < -1: val_txt = f"Z-Score {z:.2f}: precio por debajo de media — zona de soporte potencial"
    elif z > 2: val_txt = f"Z-Score {z:.2f}: sobrecompra estadística"
    elif z > 1: val_txt = f"Z-Score {z:.2f}: presión compradora por encima de media"
    else: val_txt = f"Z-Score {z:.2f}: neutro, precio cercano a su media"
    if r['precio'] < r['lower_bb']: val_txt += " | BAJO Banda Bollinger inferior (sobreventa extrema)"
    if r['rsi'] < 35: val_txt += f" | RSI {r['rsi']:.1f}: momentum vendedor dominante"
    elif r['rsi'] > 70: val_txt += f" | RSI {r['rsi']:.1f}: sobrecompra en momentum"
    lineas.append(val_txt + ".")
    sh = r['sharpe']; dd = r['max_dd']; vol = r['vol_anual']
    r_parts = []
    if sh > 2:   r_parts.append(f"Sharpe excelente ({sh:.2f})")
    elif sh > 1: r_parts.append(f"Sharpe bueno ({sh:.2f})")
    elif sh > 0: r_parts.append(f"Sharpe moderado ({sh:.2f})")
    else:        r_parts.append(f"Sharpe negativo ({sh:.2f}): retorno no compensa el riesgo")
    if dd > -10:   r_parts.append(f"drawdown contenido ({dd:.1f}%)")
    elif dd > -20: r_parts.append(f"drawdown {dd:.1f}%: nivel aceptable")
    elif dd > -35: r_parts.append(f"drawdown {dd:.1f}%: caída significativa")
    else:          r_parts.append(f"drawdown severo ({dd:.1f}%)")
    if vol < 20:   r_parts.append(f"volatilidad baja ({vol:.1f}%)")
    elif vol < 35: r_parts.append(f"volatilidad moderada ({vol:.1f}%)")
    else:          r_parts.append(f"alta volatilidad ({vol:.1f}%)")
    lineas.append("Riesgo: " + " | ".join(r_parts) + ".")
    if r['reversion_signal']:
        lineas.append(f"SEÑAL REVERSIÓN ({r['reversion_reasons']}): condiciones de sobreventa estadística. MR Score: {int(r['mr_score'])}/100.")
    return " ".join(lineas)


# ==============================================================
#  DESCARGAS EN PARALELO (corto plazo)
# ==============================================================


def _fetch_corto_ticker(tk, extra=None):
    """Descarga y calcula scores de corto plazo para un ticker. Devuelve dict o None."""
    try:
        df_v = descargar_datos(tk, '3mo'); df_m = descargar_datos(tk, '1mo')
        if df_v is None or df_m is None: return None
        cl_v = get_close_series(df_v); cl_m = get_close_series(df_m)
        if cl_v is None or cl_m is None or len(cl_v.dropna()) < 15: return None
        atr = calcular_atr(df_m)
        sa, sn, ss = scores_corto(cl_v, cl_m, atr)
        rsi = float(calcular_rsi(cl_m, p=7).iloc[-1])
        ret_5d  = float(cl_m.pct_change(5).iloc[-1]*100) if len(cl_m) >= 6 else 0
        ret_10d = float(cl_m.pct_change(10).iloc[-1]*100) if len(cl_m) >= 11 else 0
        precio  = float(cl_m.iloc[-1])

        # HMM necesita al menos 6 meses de historial (más que la ventana de 3 meses del resto del scoring)
        df_hmm = descargar_datos(tk, '6mo')
        cl_hmm = get_close_series(df_hmm) if df_hmm is not None else None
        hmm_r = calcular_regimen_hmm(cl_hmm) if cl_hmm is not None else None

        out = dict(sa=sa, sn=sn, ss=ss, sf=sa*0.45+sn*0.35+ss*0.20, rsi=rsi,
                   ret_5d=ret_5d, ret_10d=ret_10d, precio=precio,
                   accion=señal_accion_corto(sa, sn, ss), hmm=hmm_r)
        if extra:
            out.update(extra)
        return out
    except Exception:
        return None


def _fetch_paralelo(tareas, max_workers=10, grupo=None):
    """tareas: {nombre: (ticker, extra_dict_o_None)}. Devuelve {nombre: resultado}.
    Si se pasa 'grupo', deja registro en session_state de cuántos/qué tickers fallaron
    y a qué hora se hizo esta descarga real (no cuenta los cache-hits, solo ejecuciones reales)."""
    resultados = {}
    fallidos = []
    if not tareas:
        if grupo:
            st.session_state[f'_fallidos_{grupo}'] = fallidos
            st.session_state[f'_ts_{grupo}'] = datetime.now()
        return resultados
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futuros = {ex.submit(_fetch_corto_ticker, tk, extra): nombre
                   for nombre, (tk, extra) in tareas.items()}
        for fut in as_completed(futuros):
            nombre = futuros[fut]
            r = fut.result()
            if r:
                resultados[nombre] = r
            else:
                fallidos.append(nombre)
    if grupo:
        st.session_state[f'_fallidos_{grupo}'] = fallidos
        st.session_state[f'_ts_{grupo}'] = datetime.now()
    return resultados


def badge_actualizacion(grupo, ttl_min=30):
    """Muestra hace cuánto se hizo la última descarga real de este grupo (no cuenta cache-hits)."""
    ts = st.session_state.get(f'_ts_{grupo}')
    if not ts:
        return
    mins = int((datetime.now() - ts).total_seconds() // 60)
    if mins <= 0:
        texto = '🕐 Datos recién actualizados'
    else:
        texto = f'🕐 Datos de hace {mins} min · caché de {ttl_min} min'
    st.caption(texto)


def aviso_fallidos(grupo, etiqueta='activos'):
    """Si algún ticker no pudo descargarse en la última actualización real, avisa al usuario
    en vez de hacerlo desaparecer en silencio de la tabla."""
    fallidos = st.session_state.get(f'_fallidos_{grupo}', [])
    if not fallidos:
        return
    listado = ', '.join(fallidos[:10])
    extra = f' (+{len(fallidos) - 10} más)' if len(fallidos) > 10 else ''
    st.warning(
        f'⚠️ {len(fallidos)} {etiqueta} no pudieron cargarse: {listado}{extra}. '
        'Puede ser un límite temporal de Yahoo Finance — probá tocar "↺ Actualizar" en unos minutos.'
    )


# ==============================================================
#  CARGA DATOS CORTO PLAZO (paralelizado)
# ==============================================================


@st.cache_data(ttl=1800, show_spinner=False)
def cargar_forex_corto():
    tareas = {nombre: (tk, dict(tk=tk, grupo=grupo)) for nombre, (tk, grupo) in FOREX.items()}
    return _fetch_paralelo(tareas, max_workers=10, grupo='forex')


@st.cache_data(ttl=1800, show_spinner=False)
def cargar_paises_corto():
    tareas = {nombre: (tk, dict(tk=tk, region=region)) for nombre, (tk, region) in PAISES.items()}
    return _fetch_paralelo(tareas, max_workers=10, grupo='paises')


@st.cache_data(ttl=1800, show_spinner=False)
def cargar_sectores_corto():
    tareas = {nombre: (tk, dict(tk=tk, color=color)) for nombre, (tk, color) in SECTORES_GICS.items()}
    return _fetch_paralelo(tareas, max_workers=10, grupo='sectores')


@st.cache_data(ttl=1800, show_spinner=False)
def cargar_subsectores_corto():
    tareas = {
        nombre: (tk, dict(tk=tk, color=color, grupo=SUBSECTOR_A_SECTOR.get(nombre, 'Otros')))
        for nombre, (tk, color) in SUBSECTORES.items()
    }
    return _fetch_paralelo(tareas, max_workers=10, grupo='subsectores')


@st.cache_data(ttl=1800, show_spinner=False)
def cargar_mercados_corto():
    tareas = {nombre: (tk, dict(tk=tk, cat=cat, color=color)) for nombre, (tk, cat, color) in MERCADOS_REALES.items()}
    return _fetch_paralelo(tareas, max_workers=10, grupo='mercados')


@st.cache_data(ttl=1800, show_spinner=False)
def cargar_acciones_corto(industrias_sel):
    res = {ind: {} for ind in industrias_sel}
    tareas = {}
    for industria in industrias_sel:
        for tk in ACCIONES_POR_INDUSTRIA.get(industria, []):
            tareas[f'{industria}::{tk}'] = (tk, None)
    flat = _fetch_paralelo(tareas, max_workers=12, grupo='acciones')
    for key, data in flat.items():
        industria, tk = key.split('::', 1)
        res[industria][tk] = data
    return res


@st.cache_data(ttl=3600, show_spinner=False)
def cargar_resultados_largo(industrias_sel):
    tickers = list(set(t for ind in industrias_sel for t in ACCIONES_POR_INDUSTRIA.get(ind,[])))
    if not tickers: return pd.DataFrame()
    df_all = descargar_bulk(tickers, period='2y')
    if df_all is None: return pd.DataFrame()

    def _proc(tk):
        precio = get_close_from_bulk(df_all, tk)
        if len(precio) < 150: return None
        return analizar_largo(tk, precio)

    resultados = []
    fallidos_largo = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futuros = {ex.submit(_proc, tk): tk for tk in tickers}
        for fut in as_completed(futuros):
            tk = futuros[fut]
            r = fut.result()
            if r:
                resultados.append(r)
            else:
                fallidos_largo.append(tk)
    st.session_state['_fallidos_largo'] = fallidos_largo
    st.session_state['_ts_largo'] = datetime.now()
    if not resultados: return pd.DataFrame()
    df_res = pd.DataFrame(resultados).sort_values('global_score', ascending=False).reset_index(drop=True)
    df_res['rank'] = df_res.index + 1
    return df_res


# ==============================================================
#  DATOS INICIO — precios del día en bulk
# ==============================================================


@st.cache_data(ttl=300, show_spinner=False)
def cargar_precios_inicio_base():
    """Descarga precios del día (period=5d) para índices, sectores, mercados y forex en bulk.
    TTL corto (5 min) para que la página de inicio se sienta viva."""
    try:
        import yfinance as yf
        tks_paises   = [tk for tk, _ in PAISES.values()]
        tks_sectores = [tk for tk, _ in SECTORES.values()]
        tks_mercados = [tk for tk, _, _ in MERCADOS_REALES.values()]
        tks_forex    = [tk for tk, _ in FOREX.values()]
        todos = sorted(set(tks_paises + tks_sectores + tks_mercados + tks_forex))
        df = yf.download(todos, period='5d', interval='1d',
                         auto_adjust=True, progress=False, group_by='ticker')
        if df is None or df.empty:
            return {}
        resultados = {}
        for tk in todos:
            try:
                close = get_close_from_bulk(df, tk)
                if close is None or len(close) < 2:
                    continue
                precio = float(close.iloc[-1])
                previo = float(close.iloc[-2])
                resultados[tk] = {
                    'precio': precio,
                    'cambio_pct': (precio / previo - 1) * 100,
                    'cambio_abs': precio - previo,
                }
            except:
                continue
        return resultados
    except:
        return {}


@st.cache_data(ttl=300, show_spinner=False)
def cargar_precios_acciones_inicio(industrias_tuple):
    """Descarga precios del día para acciones de las industrias seleccionadas."""
    try:
        import yfinance as yf
        tickers = sorted(set(t for ind in industrias_tuple
                             for t in ACCIONES_POR_INDUSTRIA.get(ind, [])))
        if not tickers:
            return {}
        df = yf.download(tickers, period='5d', interval='1d',
                         auto_adjust=True, progress=False, group_by='ticker')
        if df is None or df.empty:
            return {}
        resultados = {}
        for tk in tickers:
            try:
                close = get_close_from_bulk(df, tk)
                if close is None or len(close) < 2:
                    continue
                precio = float(close.iloc[-1])
                previo = float(close.iloc[-2])
                resultados[tk] = {
                    'precio': precio,
                    'cambio_pct': (precio / previo - 1) * 100,
                    'cambio_abs': precio - previo,
                }
            except:
                continue
        return resultados
    except:
        return {}


# ==============================================================
#  HELPERS GENERALES
# ==============================================================


def fmt_precio(p):
    if not p or p <= 0: return 'S/D'
    if p >= 1000: return f'${p:,.0f}'
    if p >= 10:   return f'${p:.2f}'
    return f'${p:.5f}'


def kpi_cards_4(items):
    """items = (label, value, sub, accent_color) o (label, value, sub, accent_color, tooltip)."""
    cols = st.columns(len(items))
    for col, item in zip(cols, items):
        label, value, sub, color = item[0], item[1], item[2], item[3]
        tooltip = item[4] if len(item) > 4 else G(label)
        tip_attr = (tooltip or '').replace('"', "'")
        marca_info = ' ⓘ' if tip_attr else ''
        with col:
            st.markdown(
                f'<div class="kpi-card" title="{tip_attr}"><div class="kpi-accent" style="background:{color}"></div>'
                f'<div class="kpi-label">{label}{marca_info}</div>'
                f'<div class="kpi-value">{value}</div>'
                f'<div class="kpi-sub">{sub}</div></div>',
                unsafe_allow_html=True
            )
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

def kpi_card_fundamental(titulo, color, metrics, tooltip=None):
    """Card con 4 métricas (label, valor) del mismo tamaño, en grilla 2x2."""
    tip_attr = (tooltip or '').replace('"', "'")
    marca_info = ' ⓘ' if tip_attr else ''
    celdas = ''.join(
        f'<div><div class="kpi-metric-label">{lbl}</div>'
        f'<div class="kpi-metric-value">{val}</div></div>'
        for lbl, val in metrics
    )
    st.markdown(
        f'<div class="kpi-card" title="{tip_attr}"><div class="kpi-accent" style="background:{color}"></div>'
        f'<div class="kpi-label">{titulo}{marca_info}</div>'
        f'<div class="kpi-card-grid">{celdas}</div></div>',
        unsafe_allow_html=True
    )
    
def chips_navegacion(items, key_prefix, max_chips=18):
    """items: lista de tickers (str) o de tuplas (label_visible, ticker_real).
    Renderiza botones-chip que llevan directo al Buscador con un clic (cross-linking)."""
    items = list(items)[:max_chips]
    if not items:
        return
    normal = [(it, it) if isinstance(it, str) else it for it in items]
    st.markdown(
        '<div style="font-size:11px;color:#6b7d9a;margin:10px 0 4px 0">'
        '🔍 Ir directo al análisis completo (un clic):</div>',
        unsafe_allow_html=True
    )
    n_cols = 6
    for i in range(0, len(normal), n_cols):
        cols = st.columns(n_cols)
        fila = normal[i:i+n_cols]
        for j, (col, (label, tk)) in enumerate(zip(cols, fila)):
            idx_global = i + j
            with col:
                if st.button(str(label), key=f'{key_prefix}_chip_{idx_global}_{tk}', use_container_width=True):
                    st.session_state['ticker_from_table'] = tk
                    st.session_state['nav_horizonte'] = 'buscador'
                    st.session_state['nav_modulo']    = 'buscador'
                    st.rerun()

# ==============================================================
#  TICKER TAPE — barra deslizante de cotizaciones (estilo Bloomberg)
# ==============================================================


TICKER_TAPE_SIMBOLOS = [
    ('S&P 500', '^GSPC'), ('Nasdaq', '^NDX'),('Dow Jones', '^DJI'), ('Rusell', '^RUT'),
    ('Bitcoin', 'BTC-USD'), ('Ethereum', 'ETH-USD'),
    ('EUR/USD', 'EURUSD=X'), ('EUR/GBP', 'EURGBP=X'), ('USD/JPY', 'USDJPY=X'), ('GBP/USD', 'GBPUSD=X'),
    ('Oro', 'GC=F'), ('Petróleo WTI', 'CL=F'), ('Plata', 'SI=F'), ('Platino', 'PL=F'),
    ('NVDA', 'NVDA'), ('AAPL', 'AAPL'), ('TSLA', 'TSLA'), ('MSFT', 'MSFT'), ('GOOGL', 'GOOGL'), ('AMZN', 'AMZN'), ('META', 'META'),
]


def _fetch_tape_item(nombre, tk):
    try:
        df = descargar_datos(tk, '5d')
        cl = get_close_series(df)
        if cl is None or len(cl) < 2:
            return None
        precio = float(cl.iloc[-1])
        previo = float(cl.iloc[-2])
        var_pct = (precio / previo - 1) * 100 if previo else 0.0
        return dict(nombre=nombre, tk=tk, precio=precio, var_pct=var_pct)
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def cargar_ticker_tape():
    """Cotizaciones para la barra deslizante. TTL corto (5 min) para que se sienta 'vivo',
    pero reutiliza el caché de descargar_datos (30 min) así no multiplica las llamadas a Yahoo."""
    resultados = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futuros = {ex.submit(_fetch_tape_item, nombre, tk): nombre for nombre, tk in TICKER_TAPE_SIMBOLOS}
        for fut in as_completed(futuros):
            r = fut.result()
            if r:
                resultados.append(r)
    orden = {nombre: i for i, (nombre, _tk) in enumerate(TICKER_TAPE_SIMBOLOS)}
    resultados.sort(key=lambda r: orden.get(r['nombre'], 999))
    return resultados


def render_ticker_tape():
    """Renderiza la barra deslizante de cotizaciones. Si falla, no rompe el resto de la app."""
    try:
        datos = cargar_ticker_tape()
    except Exception:
        return
    if not datos:
        return
    piezas = []
    for d in datos:
        color = '#3fb950' if d['var_pct'] >= 0 else '#f85149'
        flecha = '▲' if d['var_pct'] >= 0 else '▼'
        piezas.append(
            f'<span class="tape-item">'
            f'<b style="color:#e6edf3">{d["nombre"]}</b>'
            f'<span style="color:#8b949e">{fmt_precio(d["precio"])}</span>'
            f'<span style="color:{color};font-weight:700">{flecha} {abs(d["var_pct"]):.2f}%</span>'
            f'</span>'
        )
    contenido = '<span class="tape-sep">•</span>'.join(piezas)
    st.markdown(f"""
    <div class="ticker-tape-wrap">
      <div class="ticker-tape-track">
        <div class="ticker-tape-content">{contenido}</div>
        <div class="ticker-tape-content">{contenido}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)


# ==============================================================
#  GRÁFICOS — PLOTLY
# ==============================================================


def fig_barras_h(items_ord, titulo, color_ant=C_MONSTER):
    ns   = [n for n,_ in items_ord]
    sas  = [d['sa'] for _,d in items_ord]
    sns_ = [d['sn'] for _,d in items_ord]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=ns, x=sas, orientation='h', marker_color=[score_color_hex(s) for s in sas], width=0.55,
        text=[f'{s:.0f}' for s in sas], textposition='outside', textfont=dict(color=C_TEXT, size=11),
        name='Acumulación', hovertemplate='%{y}<br>Acum: %{x:.0f}<extra></extra>',
    ))
    fig.add_trace(go.Bar(
        y=ns, x=sns_, orientation='h', marker_color=color_ant, opacity=0.35, width=0.22,
        name='Anticipación', hovertemplate='%{y}<br>Antic: %{x:.0f}<extra></extra>',
    ))
    fig.add_vline(x=62, line_dash='dash', line_color=C_GREEN, opacity=0.45)
    fig.add_vline(x=38, line_dash='dash', line_color=C_RED, opacity=0.45)
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE, barmode='overlay',
        title=dict(text=titulo, font=dict(color=C_TEXT, size=13), x=0.01),
        xaxis=dict(range=[0, 118], gridcolor=C_GRID, title='Score Acumulación', title_font=dict(size=10)),
        yaxis=dict(autorange='reversed'),
        height=max(260, len(ns) * 38 + 90),
        margin=dict(l=10, r=20, t=45, b=30),
        legend=dict(orientation='h', y=1.1, x=0, font=dict(size=9)),
    )
    return fig


def fig_momentum(pares_ord):
    ns  = [n for n,_ in pares_ord]
    r5  = [d.get('ret_5d',0) for _,d in pares_ord]
    r10 = [d.get('ret_10d',0) for _,d in pares_ord]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=ns, y=r5, name='5 días',
        marker_color=[C_GREEN if v >= 0 else C_RED for v in r5]))
    fig.add_trace(go.Bar(x=ns, y=r10, name='10 días', opacity=0.6,
        marker_color=[C_MONSTER if v >= 0 else '#bc8cff' for v in r10]))
    fig.add_hline(y=0, line_color=C_MUTED, opacity=0.4)
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE, barmode='group',
        yaxis=dict(title='Retorno %', gridcolor=C_GRID),
        xaxis=dict(tickangle=-45, gridcolor=C_GRID),
        height=460, margin=dict(l=10, r=10, t=30, b=90),
        legend=dict(orientation='h', y=1.08),
    )
    return fig


def fig_cuadrante(datos_dict, colores_dict=None, titulo='Mapa de Oportunidades'):
    fig = go.Figure()
    for nombre, d in datos_dict.items():
        clave = d.get('grupo', d.get('region', d.get('cat','')))
        col_p = colores_dict.get(clave, C_MONSTER) if colores_dict else C_MONSTER
        fig.add_trace(go.Scatter(
            x=[d['sn']], y=[d['sa']], mode='markers+text', text=[nombre],
            textposition='top center', textfont=dict(size=9, color='#b0bcd0'),
            marker=dict(size=14, color=col_p, line=dict(width=1, color=C_BG2)),
            name=nombre, showlegend=False,
            hovertemplate=f'{nombre}<br>Antic: %{{x:.0f}}<br>Acum: %{{y:.0f}}<extra></extra>',
        ))
    fig.add_hline(y=62, line_dash='dash', line_color=C_GREEN, opacity=0.35)
    fig.add_hline(y=38, line_dash='dash', line_color=C_RED, opacity=0.35)
    fig.add_vline(x=55, line_dash='dash', line_color=C_YELL, opacity=0.35)
    fig.add_shape(type='rect', x0=55, x1=100, y0=62, y1=100, fillcolor=C_GREEN, opacity=0.05, line_width=0)
    fig.add_shape(type='rect', x0=0, x1=55, y0=0, y1=38, fillcolor=C_RED, opacity=0.05, line_width=0)
    fig.add_annotation(x=77, y=97, text='✦ Zona de entrada', font=dict(color=C_GREEN, size=10), showarrow=False)
    fig.add_annotation(x=25, y=4, text='✦ Zona de cautela', font=dict(color=C_RED, size=10), showarrow=False)
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE,
        title=dict(text=titulo, font=dict(color=C_TEXT, size=14)),
        xaxis=dict(title='Score Anticipación →', range=[0, 100], gridcolor=C_GRID),
        yaxis=dict(title='← Score Acumulación', range=[0, 100], gridcolor=C_GRID),
        height=560, margin=dict(l=10, r=10, t=45, b=10),
    )
    return fig


def fig_heatmap(datos_dict, titulo='Heatmap'):
    df_heat = pd.DataFrame({
        'Acum':  {n:d['sa'] for n,d in datos_dict.items()},
        'Antic': {n:d['sn'] for n,d in datos_dict.items()},
        'Sent':  {n:d['ss'] for n,d in datos_dict.items()},
    }).sort_values('Acum', ascending=False)
    fig = go.Figure(data=go.Heatmap(
        z=df_heat.values, x=list(df_heat.columns), y=list(df_heat.index),
        colorscale='RdYlGn', zmin=0, zmax=100,
        text=np.round(df_heat.values, 0), texttemplate='%{text}',
        colorbar=dict(title='Score'),
    ))
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE,
        title=dict(text=titulo, font=dict(color=C_TEXT)),
        height=max(320, len(datos_dict) * 26),
        margin=dict(l=10, r=10, t=45, b=10),
    )
    return fig


def fig_precio_bollinger(ticker, cl, df_ohlc=None, tipo='Línea'):
    ma20 = cl.rolling(20).mean(); std20 = cl.rolling(20).std()
    upper = ma20 + 2*std20; lower = ma20 - 2*std20
    ma50 = cl.rolling(50).mean(); ma200 = cl.rolling(200).mean()
    trend_c = C_GREEN if float(cl.iloc[-1]) >= float(cl.iloc[0]) else C_RED
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=cl.index, y=upper, line=dict(color=C_ACENT, width=0.8), name='BB Superior', opacity=0.5))
    fig.add_trace(go.Scatter(x=cl.index, y=lower, line=dict(color=C_ACENT, width=0.8), name='BB Inferior',
                              fill='tonexty', fillcolor='rgba(58,123,213,0.08)', opacity=0.5))
    fig.add_trace(go.Scatter(x=cl.index, y=ma20, line=dict(color=C_YELL, width=1.3, dash='dash'), name='MA20'))
    fig.add_trace(go.Scatter(x=cl.index, y=ma50, line=dict(color=C_GREEN, width=1.3), name='MA50'))
    fig.add_trace(go.Scatter(x=cl.index, y=ma200, line=dict(color=C_RED, width=1.3), name='MA200'))

    usar_velas = (
        tipo == 'Velas'
        and df_ohlc is not None
        and {'Open', 'High', 'Low'}.issubset(df_ohlc.columns)
    )

    if usar_velas:
        # Alinear el OHLC exactamente al índice de cl (que ya viene sin NaN)
        df_ohlc_alineado = df_ohlc.reindex(cl.index)
        if df_ohlc_alineado[['Open', 'High', 'Low']].isna().any().any():
            df_ohlc_alineado = df_ohlc_alineado.ffill().bfill()
        fig.add_trace(go.Candlestick(
            x=df_ohlc_alineado.index,
            open=df_ohlc_alineado['Open'],
            high=df_ohlc_alineado['High'],
            low=df_ohlc_alineado['Low'],
            close=cl,
            name='Precio',
            increasing_line_color=C_GREEN,
            decreasing_line_color=C_RED,
            increasing_fillcolor=C_GREEN,
            decreasing_fillcolor=C_RED,
        ))
    else:
        fig.add_trace(go.Scatter(x=cl.index, y=cl, line=dict(color=trend_c, width=2.2), name='Precio'))

    fig.update_layout(
        **PLOTLY_LAYOUT_BASE,
        title=dict(text=f'{ticker}', font=dict(color=C_TEXT, size=14),
            y=0.97, x=0.01, xanchor='left'),
        xaxis=dict(gridcolor=C_GRID, rangeslider=dict(visible=False)),
        yaxis=dict(gridcolor=C_GRID),
        height=500, hovermode='x unified',
        legend=dict(orientation='h', y=1.16, x=0, font=dict(size=9)),
        margin=dict(l=10, r=10, t=75, b=10),
    )
    return fig


def fig_rsi_macd(cl):
    rsi    = calcular_rsi(cl, 14)
    macd   = cl.ewm(span=12, adjust=False).mean() - cl.ewm(span=26, adjust=False).mean()
    signal = macd.ewm(span=9, adjust=False).mean()
    hist   = macd - signal
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1,
                         subplot_titles=('RSI (14)', 'MACD (12,26,9)'))
    fig.add_trace(go.Scatter(x=rsi.index, y=rsi, line=dict(color='#bc8cff', width=1.6), name='RSI'), row=1, col=1)
    fig.add_hline(y=70, line_dash='dash', line_color=C_RED, opacity=0.5, row=1, col=1)
    fig.add_hline(y=30, line_dash='dash', line_color=C_GREEN, opacity=0.5, row=1, col=1)
    fig.add_trace(go.Scatter(x=macd.index, y=macd, line=dict(color=C_ACENT, width=1.4), name='MACD'), row=2, col=1)
    fig.add_trace(go.Scatter(x=signal.index, y=signal, line=dict(color=C_LRED, width=1.2), name='Signal'), row=2, col=1)
    fig.add_trace(go.Bar(x=hist.index, y=hist,
        marker_color=[C_GREEN if v >= 0 else C_RED for v in hist], opacity=0.5, name='Hist'), row=2, col=1)
    fig.update_yaxes(range=[0, 100], gridcolor=C_GRID, row=1, col=1)
    fig.update_yaxes(gridcolor=C_GRID, row=2, col=1)
    fig.update_xaxes(gridcolor=C_GRID)
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE, height=560, hovermode='x unified', showlegend=True,
        legend=dict(orientation='h', y=1.07, font=dict(size=9)),
        margin=dict(l=10, r=10, t=45, b=10),
    )
    fig.update_annotations(font=dict(color=C_TEXT, size=12))
    return fig


def fig_drawdown(ticker, cl):
    ret = cl.pct_change().dropna()
    cum = (1 + ret).cumprod()
    dd  = (cum / cum.cummax() - 1) * 100
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dd.index, y=dd, fill='tozeroy', line=dict(color=C_RED, width=1.3),
                              fillcolor='rgba(248,81,73,0.35)', name='Drawdown'))
    fig.add_hline(y=-20, line_dash='dash', line_color=C_YELL, opacity=0.5, annotation_text='-20%')
    fig.add_hline(y=-40, line_dash='dash', line_color=C_RED, opacity=0.5, annotation_text='-40%')
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE,
        title=dict(text=f'{ticker} — Drawdown desde máximo · Máx: {float(dd.min()):.1f}%', font=dict(color=C_TEXT, size=13)),
        xaxis=dict(gridcolor=C_GRID), yaxis=dict(gridcolor=C_GRID, title='%'),
        height=340, margin=dict(l=10, r=10, t=45, b=10),
    )
    return fig


def fig_mini_precio(ticker, precios):
    trend_c = C_GREEN if precios[-1] >= precios[0] else C_RED
    ret_p = (precios[-1]/precios[0]-1)*100
    fig = go.Figure()
    fig.add_trace(go.Scatter(y=precios, mode='lines', line=dict(color=trend_c, width=2),
                              fill='tozeroy', fillcolor='rgba(58,123,213,0.10)', name='Precio'))
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE,
        title=dict(text=f'{ticker} — 30 días ({ret_p:+.2f}%)', font=dict(color=trend_c, size=13)),
        height=260, margin=dict(l=10, r=10, t=40, b=10),
        xaxis=dict(showticklabels=False, gridcolor=C_GRID), yaxis=dict(gridcolor=C_GRID),
    )
    return fig


def fig_distribuciones(df_res_l):
    fig = make_subplots(rows=1, cols=3, subplot_titles=('Trend Score', 'MR Score', 'Global Score'))
    for i, c in enumerate(['trend_score', 'mr_score', 'global_score']):
        vals = df_res_l[c].values
        fig.add_trace(go.Histogram(x=vals, nbinsx=20, marker_color=C_MONSTER, opacity=0.85), row=1, col=i+1)
        fig.add_vline(x=float(np.mean(vals)), line_dash='dash', line_color=C_LRED, row=1, col=i+1)
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE, height=380, showlegend=False, margin=dict(l=10, r=10, t=45, b=10),
    )
    fig.update_xaxes(gridcolor=C_GRID); fig.update_yaxes(gridcolor=C_GRID)
    fig.update_annotations(font=dict(color=C_TEXT, size=12))
    return fig


def fig_topdown(fuentes):
    fig = make_subplots(rows=1, cols=len(fuentes), subplot_titles=[f[0] for f in fuentes])
    for i, (label, dd, col_td) in enumerate(fuentes):
        top_items = sorted(dd.items(), key=lambda x: x[1]['sa'], reverse=True)[:12]
        ns  = [n[:16] for n,_ in top_items]
        sas = [d['sa'] for _,d in top_items]
        fig.add_trace(go.Bar(y=ns, x=sas, orientation='h',
            marker_color=[score_color_hex(s) for s in sas],
            text=[f'{s:.0f}' for s in sas], textposition='outside'), row=1, col=i+1)
        fig.update_yaxes(autorange='reversed', row=1, col=i+1)
        fig.add_vline(x=62, line_dash='dot', line_color=C_GREEN, opacity=0.4, row=1, col=i+1)
        fig.add_vline(x=38, line_dash='dot', line_color=C_RED, opacity=0.4, row=1, col=i+1)
        fig.update_xaxes(range=[0, 118], gridcolor=C_GRID, row=1, col=i+1)
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE, height=500, showlegend=False, margin=dict(l=10, r=10, t=55, b=10),
        title=dict(text='Top-Down: mejores oportunidades por nivel', font=dict(color=C_TEXT, size=14)),
    )
    fig.update_annotations(font=dict(color=C_TEXT, size=11))
    return fig


def fig_comparador_precio(series_dict):
    fig = go.Figure()
    palette = [C_MONSTER, C_ACENT, C_LRED, '#bc8cff', C_YELL]
    for i, (tk, s) in enumerate(series_dict.items()):
        base = s.dropna()
        if len(base) == 0: continue
        rebased = base / float(base.iloc[0]) * 100
        fig.add_trace(go.Scatter(x=rebased.index, y=rebased, name=tk,
            line=dict(color=palette[i % len(palette)], width=2.2)))
    fig.add_hline(y=100, line_dash='dot', line_color=C_MUTED, opacity=0.4)
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE,
        title=dict(text='Comparativa de rendimiento (base 100)', font=dict(color=C_TEXT, size=14)),
        xaxis=dict(gridcolor=C_GRID), yaxis=dict(gridcolor=C_GRID, title='Índice (base 100)'),
        height=480, hovermode='x unified',
        legend=dict(orientation='h', y=1.08),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    return fig


def fig_radar_comparador(resultados_l):
    """Radar de Trend/MR/Risk/Global Score — comparación visual entre tickers."""
    categorias = ['Trend', 'MR', 'Risk', 'Global']
    palette = [C_MONSTER, C_ACENT, C_LRED, '#bc8cff', C_YELL]
    fig = go.Figure()
    for i, (tk, r) in enumerate(resultados_l.items()):
        valores = [r['trend_score'], r['mr_score'], r['risk_score'], r['global_score']]
        color = palette[i % len(palette)]
        fig.add_trace(go.Scatterpolar(
            r=valores + [valores[0]], theta=categorias + [categorias[0]],
            fill='toself', name=tk, opacity=0.55,
            line=dict(color=color, width=2), fillcolor=color,
        ))
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE,
        polar=dict(
            bgcolor=C_BG1,
            radialaxis=dict(visible=True, range=[0, 100], gridcolor=C_GRID, color=C_MUTED),
            angularaxis=dict(gridcolor=C_GRID, color=C_TEXT),
        ),
        title=dict(text='Scores cuantitativos — comparación', font=dict(color=C_TEXT, size=14)),
        height=460, showlegend=True, legend=dict(orientation='h', y=-0.12),
        margin=dict(l=40, r=40, t=50, b=40),
    )
    return fig


def _pct100(v):
    """Convierte una fracción (0.25) a porcentaje (25.0), preservando None."""
    return v * 100 if v is not None else None


# Categorías de métricas fundamentales: (título, [(label, extractor, dirección, clave_glosario), ...])
# dirección: 'menor' = el valor más bajo es mejor · 'mayor' = el valor más alto es mejor · None = informativo
CATEGORIAS_FUNDAMENTAL = [
    ('📐 Valuación', [
        ('PER', lambda e: e.get('per'), 'menor', 'PER'),
        ('P/B', lambda e: e.get('pb'), 'menor', 'P/B'),
        ('P/S', lambda e: e.get('ps'), 'menor', 'P/S'),
        ('PEG', lambda e: e.get('peg'), 'menor', 'PEG'),
        ('EV/EBITDA', lambda e: e.get('ev_ebitda'), 'menor', 'EV/EBITDA'),
    ]),
    ('📈 Rentabilidad', [
        ('ROE %', lambda e: _pct100(e.get('roe')), 'mayor', 'ROE'),
        ('ROA %', lambda e: _pct100(e.get('roa')), 'mayor', 'ROA'),
        ('Mg. Bruto %', lambda e: _pct100(e.get('gross_margin')), 'mayor', 'Margen Bruto'),
        ('Mg. Operativo %', lambda e: _pct100(e.get('op_margin')), 'mayor', 'Margen Operativo'),
        ('Mg. Neto %', lambda e: _pct100(e.get('profit_margin')), 'mayor', 'Margen Neto'),
    ]),
    ('🚀 Crecimiento', [
        ('Rev. Growth %', lambda e: _pct100(e.get('revenue_growth')), 'mayor', 'Revenue Growth'),
        ('EPS Growth %', lambda e: _pct100(e.get('eps_growth')), 'mayor', 'EPS Growth'),
        ('Earnings Growth %', lambda e: _pct100(e.get('earnings_growth')), 'mayor', 'Earnings Growth'),
        ('Alza YTD %', lambda e: e.get('alza_ytd'), 'mayor', 'YTD'),
    ]),
    ('🔒 Riesgo y Solvencia', [
        ('Beta', lambda e: e.get('beta'), 'menor', 'Beta'),
        ('D/E', lambda e: e.get('debt_equity'), 'menor', 'D/E'),
        ('Current Ratio', lambda e: e.get('curr_ratio'), 'mayor', 'Current Ratio'),
    ]),
    ('💰 Dividendos y Flujo', [
        ('Div. Yield %', lambda e: _pct100(e.get('div_yield')), 'mayor', 'Dividend Yield'),
        ('FCF', lambda e: e.get('fcf'), 'mayor', 'FCF'),
        ('Operating CF', lambda e: e.get('op_cf'), 'mayor', 'Operating Cash Flow'),
        ('Cash', lambda e: e.get('cash'), 'mayor', 'Cash'),
    ]),
    ('🏢 Tamaño y Precio', [
        ('Market Cap', lambda e: e.get('market_cap'), None, 'Market Cap'),
        ('Enterprise Value', lambda e: e.get('ev'), None, 'Enterprise Value'),
        ('Precio', lambda e: e.get('precio'), None, None),
        ('Precio Objetivo', lambda e: e.get('target_price'), None, 'Precio Objetivo'),
    ]),
]


def fig_categoria_fundamental(datos_fund, metricas, titulo):
    """Pequeños múltiplos comparando un grupo de métricas fundamentales entre tickers.
    metricas: lista de (label, extractor, direccion, clave_glosario) — se usan label y extractor."""
    tickers = list(datos_fund.keys())
    palette = [C_MONSTER, C_ACENT, C_LRED, '#bc8cff', C_YELL]
    colores = [palette[j % len(palette)] for j in range(len(tickers))]
    n = len(metricas)
    cols_n = min(3, n) if n > 0 else 1
    rows_n = max(1, (n + cols_n - 1) // cols_n)
    fig = make_subplots(rows=rows_n, cols=cols_n, subplot_titles=[m[0] for m in metricas])
    for i, (nombre, extractor, _direccion, _glos_key) in enumerate(metricas):
        row, col = i // cols_n + 1, i % cols_n + 1
        vals = [extractor(datos_fund[tk]) for tk in tickers]
        textos = []
        for v in vals:
            if v is None:
                textos.append('N/D')
            elif abs(v) >= 1e6:
                textos.append(_fmt_big(v))
            else:
                textos.append(f'{v:.2f}')
        fig.add_trace(go.Bar(
            x=tickers, y=vals, marker_color=colores, showlegend=False,
            text=textos, textposition='outside',
        ), row=row, col=col)
        fig.update_yaxes(gridcolor=C_GRID, row=row, col=col)
        fig.update_xaxes(gridcolor=C_GRID, row=row, col=col)
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE, height=max(320, rows_n * 270), margin=dict(l=10, r=10, t=60, b=10),
        title=dict(text=titulo, font=dict(color=C_TEXT, size=14)),
    )
    fig.update_annotations(font=dict(color=C_TEXT, size=11))
    return fig


# ==============================================================
#  RENDER ÚNICO — ANÁLISIS DE LARGO PLAZO (evita duplicación)
# ==============================================================


def render_largo_completo(ticker, cl, r, key_suffix='', df_ohlc=None):
    accent = score_color_hex(r['global_score'])
    kpi_cards_4([
        ('Global Score',  f"{int(r['global_score'])}/100",  r['sesgo'], accent),
        ('Trend Score',   f"{int(r['trend_score'])}/100",
         f"GC: {'Sí' if r['golden_cross'] else 'No'} · MACD: {'Alc' if r['macd_bull'] else 'Baj'}",
         score_color_hex(r['trend_score'])),
        ('MR Score',      f"{int(r['mr_score'])}/100",
         f"Z: {r['zscore']:+.2f} · RSI: {r['rsi']:.1f}", score_color_hex(r['mr_score'])),
        ('Risk Score',    f"{int(r['risk_score'])}/100",
         f"Sharpe: {r['sharpe']:.2f} · DD: {r['max_dd']:.1f}%", score_color_hex(r['risk_score'])),
    ])

    c1,c2,c3,c4 = st.columns(4)
    with c1: st.metric('Ret. Anual', f"{r['ret_anual']:+.1f}%")
    with c2: st.metric('Volatilidad', f"{r['vol_anual']:.1f}%")
    with c3: st.metric('Max DrawDown', f"{r['max_dd']:.1f}%", help=G('Max Drawdown'))
    with c4: st.metric('Hurst', f"{r['hurst']:.3f}", help=G('Hurst'))

    interp = interpretar_largo(r)
    sesgo_class = {'MUY ALCISTA':'sesgo-muy-alc','ALCISTA':'sesgo-alc','NEUTRAL':'sesgo-neu',
                   'BAJISTA':'sesgo-baj','MUY BAJISTA':'sesgo-muy-baj'}.get(r['sesgo'],'')
    st.markdown(f"""
    <div class="interp-card">
      <div class="interp-header">{ticker} · {r['industria']} · <span class="{sesgo_class}">{r['sesgo']}</span></div>
      {interp}
    </div>
    """, unsafe_allow_html=True)

    tab_g1, tab_g2, tab_g3 = st.tabs(['📈 Precio + Bollinger', '📊 RSI & MACD', '📉 Drawdown'])
    with tab_g1:
        tipo_graf = st.radio('Tipo de gráfico', ['Línea', 'Velas'],
                              horizontal=True, key=f'tipo_graf_{key_suffix}_{ticker}')
        st.plotly_chart(fig_precio_bollinger(ticker, cl, df_ohlc=df_ohlc, tipo=tipo_graf),
                         use_container_width=True, config=PLOTLY_CONFIG, key=f'fpb_{key_suffix}_{ticker}')
    with tab_g2:
        st.plotly_chart(fig_rsi_macd(cl), use_container_width=True, config=PLOTLY_CONFIG, key=f'frm_{key_suffix}_{ticker}')
    with tab_g3:
        st.plotly_chart(fig_drawdown(ticker, cl), use_container_width=True, config=PLOTLY_CONFIG, key=f'fdd_{key_suffix}_{ticker}')


def _tabla_fundamental_completa(df, columnas, fmt_overrides=None):
    """Tabla con TODAS las métricas fundamentales: resalta en verde el mejor valor por columna
    cuando corresponde, y formatea cada columna (incluyendo números grandes vía fmt_overrides).
    columnas: lista de (nombre_columna, direccion) — direccion en {'menor','mayor', None}.
    'menor' = el valor más bajo es mejor (PER, P/B, D/E, Beta...).
    'mayor' = el valor más alto es mejor (ROE, márgenes, Dividend Yield...).
    None    = informativo, no se resalta (Market Cap, Precio, etc.).
    """
    fmt_overrides = fmt_overrides or {}
    direcciones = {c: d for c, d in columnas if c in df.columns}
    cols_resaltar = [c for c, d in direcciones.items() if d is not None]
    cols_formato = list(direcciones.keys())

    def _highlight(col):
        out = [''] * len(col)
        direction = direcciones.get(col.name)
        if direction is None:
            return out
        vals = pd.to_numeric(col, errors='coerce')
        if vals.notna().sum() == 0:
            return out
        best = vals.idxmin() if direction == 'menor' else vals.idxmax()
        pos = col.index.get_loc(best)
        out[pos] = 'background-color:#0d2410;color:#3fb950;font-weight:700'
        return out

    fmt = {c: fmt_overrides.get(c, '{:.2f}') for c in cols_formato}
    styled = df.style
    if cols_resaltar:
        styled = styled.apply(_highlight, subset=cols_resaltar)
    styled = (styled
        .format(fmt, na_rep='N/D')
        .set_properties(**{'background-color': '#0d1117', 'color': '#e6edf3', 'border': '1px solid #21262d'})
        .set_table_styles([
            {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', '#e6edf3'),
                ('font-weight', '700'), ('text-align', 'center'),
                ('border-bottom', '2px solid #3a7bd5'), ('font-size', '11px')]},
            {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]},
        ]))
    return styled


def _apply_score_style(df, score_cols, ret_cols=None):
    def cs(val):
        try:
            v = float(val)
            if v<=20: return 'background-color:#2a0a0a;color:#f85149;font-weight:600'
            elif v<=40: return 'background-color:#2a1a05;color:#f0883e;font-weight:600'
            elif v<=60: return 'background-color:#1e1a05;color:#e3b341;font-weight:600'
            elif v<=80: return 'background-color:#081a0a;color:#7ee787;font-weight:600'
            else: return 'background-color:#051505;color:#3fb950;font-weight:600'
        except: return ''
    def cr(val):
        try: v=float(val); return f'color:{"#3fb950" if v>=0 else "#f85149"};font-weight:600'
        except: return ''
    _map = 'map' if hasattr(df.style,'map') else 'applymap'
    styled = df.style.pipe(lambda s: getattr(s,_map)(cs, subset=score_cols))
    if ret_cols:
        styled = styled.pipe(lambda s: getattr(s,_map)(cr, subset=ret_cols))
    styled = styled.set_properties(**{'background-color':'#0d1117','color':'#e6edf3','border':'1px solid #21262d'})
    styled = styled.set_table_styles([
        {'selector':'th','props':[('background-color','#161b22'),('color','#e6edf3'),('font-weight','700'),
                                   ('text-align','center'),('border-bottom','2px solid #3a7bd5'),('font-size','11px')]},
        {'selector':'td','props':[('text-align','center'),('font-size','11px')]}
    ])
    return styled


def _color_regimen_hmm(val):
    return {'ALCISTA':'color:#3fb950;font-weight:700',
            'NEUTRAL':'color:#e3b341;font-weight:700',
            'BAJISTA':'color:#f85149;font-weight:700'}.get(val, 'color:#6b7d9a')


def tabla_corto(filas_dict, key_suffix=''):
    filas = []
    for nombre, d in sorted(filas_dict.items(), key=lambda x: x[1]['sa'], reverse=True):
        hmm_d = d.get('hmm') or {}
        filas.append({'Nombre': nombre, 'Acum': round(d['sa'],1), 'Antic': round(d['sn'],1),
            'Sent': round(d['ss'],1), 'RSI': round(d.get('rsi',0),1),
            'Ret 5d %': round(d.get('ret_5d',0),2), 'Ret 10d %': round(d.get('ret_10d',0),2),
            'Precio': fmt_precio(d.get('precio',0)), 'Señal': d['accion'],
            'Régimen HMM': hmm_d.get('regimen', 'N/D'),
            'Prob HMM %': hmm_d.get('prob', None),
            'Duración (ruedas)': hmm_d.get('duracion', None)})
    df = pd.DataFrame(filas)


    fc1, fc2, fc3 = st.columns([2,2,2])
    with fc1:
        señales_u = ['Todas'] + sorted(df['Señal'].unique().tolist())
        f_señal = st.selectbox('Señal', señales_u, key=f'tc_señal_{key_suffix}')
    with fc2:
        regs_u = ['Todos'] + sorted([r for r in df['Régimen HMM'].unique() if r != 'N/D'])
        f_regimen = st.selectbox('Régimen HMM', regs_u, key=f'tc_regimen_{key_suffix}')
    with fc3:
        st.write('')


    fr1, fr2, fr3 = st.columns(3)
    with fr1:
        f_acum = st.slider('Rango Acum', 0, 100, (0,100), 1, key=f'tc_acum_{key_suffix}')
    with fr2:
        f_antic = st.slider('Rango Antic', 0, 100, (0,100), 1, key=f'tc_antic_{key_suffix}')
    with fr3:
        f_sent = st.slider('Rango Sent', 0, 100, (0,100), 1, key=f'tc_sent_{key_suffix}')


    fr4, fr5, fr6 = st.columns(3)
    with fr4:
        f_rsi = st.slider('Rango RSI', 0, 100, (0,100), 1, key=f'tc_rsi_{key_suffix}')
    with fr5:
        f_ret5 = st.slider('Rango Ret 5d %', -30, 30, (-30,30), 1, key=f'tc_ret5_{key_suffix}')
    with fr6:
        f_ret10 = st.slider('Rango Ret 10d %', -30, 30, (-30,30), 1, key=f'tc_ret10_{key_suffix}')


    df_f = df.copy()
    if f_señal != 'Todas': df_f = df_f[df_f['Señal']==f_señal]
    if f_regimen != 'Todos': df_f = df_f[df_f['Régimen HMM']==f_regimen]
    df_f = df_f[df_f['Acum'].between(*f_acum) & df_f['Antic'].between(*f_antic)
                & df_f['Sent'].between(*f_sent) & df_f['RSI'].between(*f_rsi)
                & df_f['Ret 5d %'].between(*f_ret5) & df_f['Ret 10d %'].between(*f_ret10)]


    _map_tc = 'map' if hasattr(df_f.style,'map') else 'applymap'
    styled = (_apply_score_style(df_f, ['Acum','Antic','Sent'], ['Ret 5d %','Ret 10d %'])
              .pipe(lambda s: getattr(s,_map_tc)(_color_regimen_hmm, subset=['Régimen HMM'])))
    st.dataframe(styled, use_container_width=True, height=min(600, max(150, len(df_f)*35+45)))
    st.caption(f'{len(df_f)} activos mostrados de {len(df)} totales')

    pares = [(n, filas_dict[n].get('tk', n)) for n in df_f['Nombre'].tolist()]
    chips_navegacion(pares, f'tc_{key_suffix}')


def tabla_largo(df_res, key_suffix=''):
    if df_res.empty: return
    cols_show = ['rank','ticker','industria','precio','ret_anual','vol_anual','rsi','sharpe',
                 'max_dd','trend_score','mr_score','risk_score','global_score','sesgo']
    df_show = df_res[cols_show].copy()
    df_show.columns = ['#','Ticker','Industria','Precio','Ret %','Vol %','RSI','Sharpe','DD%',
                        'Trend','MR','Risk','Global','Sesgo']
    df_show['Precio'] = df_show['Precio'].apply(fmt_precio)
    df_show['Ret %']  = df_show['Ret %'].apply(lambda x: f'{x:+.1f}' if pd.notna(x) else 'N/A')
    df_show['Vol %']  = df_show['Vol %'].apply(lambda x: f'{x:.1f}' if pd.notna(x) else 'N/A')
    df_show['RSI']    = df_show['RSI'].apply(lambda x: f'{x:.1f}')
    df_show['Sharpe'] = df_show['Sharpe'].apply(lambda x: f'{x:.2f}')
    df_show['DD%']    = df_show['DD%'].apply(lambda x: f'{x:.1f}')


    fc1, fc2 = st.columns([2,2])
    with fc1:
        sesgos_u = ['Todos'] + sorted(df_show['Sesgo'].unique().tolist())
        f_sesgo = st.selectbox('Sesgo', sesgos_u, key=f'tl_sesgo_{key_suffix}')
    with fc2:
        inds_u = ['Todas'] + sorted(df_show['Industria'].unique().tolist())
        f_ind = st.selectbox('Industria', inds_u, key=f'tl_ind_{key_suffix}')


    fr1, fr2, fr3, fr4 = st.columns(4)
    with fr1:
        f_global = st.slider('Rango Global', 0, 100, (0,100), 1, key=f'tl_global_{key_suffix}')
    with fr2:
        f_sharpe = st.slider('Rango Sharpe', -3.0, 5.0, (-3.0,5.0), 0.1, key=f'tl_sharpe_{key_suffix}')
    with fr3:
        f_trend = st.slider('Rango Trend', 0, 100, (0,100), 1, key=f'tl_trend_{key_suffix}')
    with fr4:
        f_risk = st.slider('Rango Risk', 0, 100, (0,100), 1, key=f'tl_risk_{key_suffix}')


    fr5, fr6, fr7, fr8 = st.columns(4)
    with fr5:
        f_mr = st.slider('Rango MR', 0, 100, (0,100), 1, key=f'tl_mr_{key_suffix}')
    with fr6:
        f_ret = st.slider('Rango Ret %', -80, 200, (-80,200), 5, key=f'tl_ret_{key_suffix}')
    with fr7:
        f_vol = st.slider('Rango Vol %', 0, 150, (0,150), 5, key=f'tl_vol_{key_suffix}')
    with fr8:
        f_dd = st.slider('Rango DD %', -100, 0, (-100,0), 5, key=f'tl_dd_{key_suffix}')


    df_f = df_show.copy()
    if f_sesgo != 'Todos': df_f = df_f[df_f['Sesgo']==f_sesgo]
    if f_ind   != 'Todas': df_f = df_f[df_f['Industria']==f_ind]
    try:
        df_f = df_f[df_f['Global'].astype(int).between(*f_global)]
        df_f = df_f[df_f['Sharpe'].astype(float).between(*f_sharpe)]
        df_f = df_f[df_f['Trend'].astype(int).between(*f_trend)]
        df_f = df_f[df_f['Risk'].astype(int).between(*f_risk)]
        df_f = df_f[df_f['MR'].astype(int).between(*f_mr)]
        df_f = df_f[df_f['Ret %'].astype(float).between(*f_ret)]
        df_f = df_f[df_f['Vol %'].astype(float).between(*f_vol)]
        df_f = df_f[df_f['DD%'].astype(float).between(*f_dd)]
    except: pass


    def sesgo_style(val):
        return {'MUY ALCISTA':'color:#3fb950;font-weight:700','ALCISTA':'color:#7ee787;font-weight:700',
                'NEUTRAL':'color:#e3b341;font-weight:700','BAJISTA':'color:#f0883e;font-weight:700',
                'MUY BAJISTA':'color:#f85149;font-weight:700'}.get(val,'')
    _map = 'map' if hasattr(df_f.style,'map') else 'applymap'
    styled = (_apply_score_style(df_f, ['Trend','MR','Risk','Global'])
              .pipe(lambda s: getattr(s,_map)(sesgo_style, subset=['Sesgo'])))
    st.dataframe(styled, use_container_width=True, height=min(700, max(200, len(df_f)*30+45)))
    st.caption(f'{len(df_f)} activos mostrados de {len(df_show)} totales')

    chips_navegacion(df_f['Ticker'].tolist(), f'tl_{key_suffix}')


# ==============================================================
#  ANÁLISIS FUNDAMENTAL — DATOS
# ==============================================================

SECTOR_MAP_FUND = {
    'Semiconductores': 'Technology',   'Software': 'Technology',
    'Ciberseguridad': 'Technology',    'Cloud/AI': 'Technology',
    'Hardware/Equipos': 'Technology',  'Fintech': 'Financial Services',
    'Biotecnología': 'Healthcare',     'Farmacéuticas': 'Healthcare',
    'Equipos Médicos': 'Healthcare',   'Servicios de Salud': 'Healthcare',
    'Bancos': 'Financial Services',    'Seguros': 'Financial Services',
    'Mercados Capitales': 'Financial Services',
    'Bancos Regionales': 'Financial Services',
    'Finanzas Diversif.': 'Financial Services',
    'Petróleo Integrado': 'Energy',    'Energía Renovable': 'Energy',
    'Gas Natural': 'Energy',           'Energía Solar': 'Energy',
    'Aeroespacial': 'Industrials',     'Transporte': 'Industrials',
    'Construcción': 'Industrials',     'Defensa': 'Industrials',
    'Retail': 'Consumer Cyclical',     'Autos': 'Consumer Cyclical',
    'Hotelería/Viajes': 'Consumer Cyclical', 'E-commerce': 'Consumer Cyclical',
    'Alimentos': 'Consumer Defensive', 'Bebidas': 'Consumer Defensive',
    'Minería Oro': 'Basic Materials',  'Cobre/Metales': 'Basic Materials',
    'Químicos': 'Basic Materials',     'Acero': 'Basic Materials',
    'Telecomunicaciones': 'Communication Services',
    'Internet': 'Communication Services',
    'Eléctricas': 'Utilities',         'Agua': 'Utilities',
    'REIT Comercial': 'Real Estate',   'REIT Industrial': 'Real Estate',
    'REIT Residencial': 'Real Estate',
    'Agro/Fertilizantes': 'Basic Materials',
    'Argentina': 'Latam Emergente',    'Brasil': 'Latam Emergente',
    'México': 'Latam Emergente',
    'China': 'Asia Emergente',         'India': 'Asia Emergente',
    'Europa Tecnología': 'Europa',     'Europa Finanzas': 'Europa',
    'Cripto (ETF/Coin)': 'Cripto',
}

INDUSTRY_BENCHMARKS_FUND = {
    'Technology': {
        'per_max': 35, 'pb_max': 10, 'gross_margin_min': 0.50,
        'roe_min': 0.15, 'debt_equity_max': 1.0,
        'descripcion': 'Altos márgenes brutos (>50%), valuaciones PER elevadas. FCF positivo y expansión de márgenes son clave. Múltiplos relevantes: EV/EBITDA, P/S.',
        'metricas_clave': ['Margen Bruto', 'Crecimiento Ingresos', 'FCF', 'EV/EBITDA', 'ROE'],
    },
    'Financial Services': {
        'per_max': 18, 'pb_max': 2.5, 'gross_margin_min': None,
        'roe_min': 0.10, 'debt_equity_max': None,
        'descripcion': 'Se valúan por P/B y ROE. P/B < 1 puede indicar infravaloración. ROE objetivo > 10-12%. Deuda estructural es parte del modelo.',
        'metricas_clave': ['P/B', 'ROE', 'ROA', 'Margen Neto', 'Crecimiento EPS'],
    },
    'Healthcare': {
        'per_max': 30, 'pb_max': 6.0, 'gross_margin_min': 0.40,
        'roe_min': 0.12, 'debt_equity_max': 1.2,
        'descripcion': 'Combina defensividad con crecimiento estructural. Farmacéuticas con pipeline sólido sostienen márgenes brutos >60%.',
        'metricas_clave': ['PEG Ratio', 'Margen Bruto', 'ROE', 'FCF', 'Crecimiento Ingresos'],
    },
    'Energy': {
        'per_max': 20, 'pb_max': 3.0, 'gross_margin_min': 0.20,
        'roe_min': 0.08, 'debt_equity_max': 1.5,
        'descripcion': 'Sector cíclico sensible al precio del petróleo/gas. Se valoriza por EV/EBITDA, FCF yield y dividendos.',
        'metricas_clave': ['EV/EBITDA', 'FCF', 'Dividend Yield', 'Deuda/Equity', 'Beta'],
    },
    'Industrials': {
        'per_max': 22, 'pb_max': 4.0, 'gross_margin_min': 0.25,
        'roe_min': 0.12, 'debt_equity_max': 1.5,
        'descripcion': 'Manufactura, aeroespacial, logística. Cíclico, ligado al ciclo económico global. Margen operativo es el indicador más relevante.',
        'metricas_clave': ['Margen Operativo', 'EV/EBITDA', 'ROE', 'Deuda/Equity', 'FCF'],
    },
    'Consumer Cyclical': {
        'per_max': 25, 'pb_max': 5.0, 'gross_margin_min': 0.30,
        'roe_min': 0.12, 'debt_equity_max': 1.5,
        'descripcion': 'Retail, automotriz y entretenimiento. Muy sensible al ciclo económico. Beta alto (>1.2) típico.',
        'metricas_clave': ['Beta', 'Margen Operativo', 'Current Ratio', 'FCF', 'Revenue Growth'],
    },
    'Consumer Defensive': {
        'per_max': 22, 'pb_max': 4.0, 'gross_margin_min': 0.35,
        'roe_min': 0.15, 'debt_equity_max': 1.5,
        'descripcion': 'Alimentos, bebidas, cuidado personal: demanda estable, dividendos crecientes. Beta bajo (<0.8) los hace refugio.',
        'metricas_clave': ['Dividend Yield', 'Beta', 'Margen Bruto', 'ROE', 'P/B'],
    },
    'Basic Materials': {
        'per_max': 18, 'pb_max': 2.5, 'gross_margin_min': 0.20,
        'roe_min': 0.08, 'debt_equity_max': 1.0,
        'descripcion': 'Minería, química, acero: negocios intensivos en capital y muy cíclicos. EV/EBITDA es el múltiplo estándar.',
        'metricas_clave': ['EV/EBITDA', 'Deuda/Equity', 'FCF', 'Margen Bruto', 'Beta'],
    },
    'Communication Services': {
        'per_max': 28, 'pb_max': 5.0, 'gross_margin_min': 0.40,
        'roe_min': 0.12, 'debt_equity_max': 1.5,
        'descripcion': 'Telcos con alto CAPEX y dividendos. Plataformas digitales con márgenes altos.',
        'metricas_clave': ['Margen Bruto', 'FCF', 'Dividend Yield', 'EV/EBITDA', 'Revenue Growth'],
    },
    'Utilities': {
        'per_max': 20, 'pb_max': 2.5, 'gross_margin_min': 0.30,
        'roe_min': 0.08, 'debt_equity_max': 2.0,
        'descripcion': 'Negocios regulados con flujos predecibles. Beta < 0.5 típico. Dividend yield sostenible es el principal atractivo.',
        'metricas_clave': ['Dividend Yield', 'Beta', 'Deuda/Equity', 'P/B', 'Margen Operativo'],
    },
    'Real Estate': {
        'per_max': 30, 'pb_max': 3.0, 'gross_margin_min': 0.40,
        'roe_min': 0.07, 'debt_equity_max': 2.5,
        'descripcion': 'REITs: se valúan por FFO. Dividend yield crucial (deben distribuir >= 90% de ganancias).',
        'metricas_clave': ['Dividend Yield', 'P/B', 'Deuda/Equity', 'Current Ratio', 'FCF'],
    },
    'Latam Emergente': {
        'per_max': 14, 'pb_max': 2.0, 'gross_margin_min': 0.20,
        'roe_min': 0.10, 'debt_equity_max': 1.5,
        'descripcion': 'Riesgo país y tipo de cambio comprimen los múltiplos. PER < 10 frecuente en Argentina. FCF positivo requisito mínimo. ROE > 15% en entornos inflacionarios.',
        'metricas_clave': ['PER', 'P/B', 'Dividend Yield', 'FCF', 'Deuda/Equity', 'Beta', 'ROE'],
    },
    'Asia Emergente': {
        'per_max': 20, 'pb_max': 3.0, 'gross_margin_min': 0.25,
        'roe_min': 0.10, 'debt_equity_max': 1.2,
        'descripcion': 'Heterogéneo: Japón y Corea con múltiplos comprimidos. China con descuento regulatorio (PER 10-15x). India admite múltiplos más altos por crecimiento estructural.',
        'metricas_clave': ['PER', 'P/B', 'ROE', 'FCF', 'EV/EBITDA', 'Revenue Growth', 'Deuda/Equity'],
    },
    'Europa': {
        'per_max': 20, 'pb_max': 3.5, 'gross_margin_min': 0.30,
        'roe_min': 0.10, 'debt_equity_max': 1.5,
        'descripcion': 'Descuento histórico de 20-30% vs EE.UU. PER de 14-18x normal. Energía paga dividendos del 4-6%. Tecnología europea (ASML, SAP) admite múltiplos más altos.',
        'metricas_clave': ['PER', 'P/B', 'Dividend Yield', 'EV/EBITDA', 'ROE', 'FCF', 'Deuda/Equity'],
    },
    'Cripto': {
        'per_max': None, 'pb_max': None, 'gross_margin_min': None,
        'roe_min': None, 'debt_equity_max': None,
        'descripcion': 'Activos digitales sin métricas de valuación tradicionales. Análisis técnico y on-chain son más relevantes.',
        'metricas_clave': ['Volatilidad', 'Momentum', 'Correlación BTC', 'Dominancia'],
    },
}

DEFAULT_BENCHMARK_FUND = {
    'per_max': None, 'pb_max': None, 'gross_margin_min': None,
    'roe_min': None, 'debt_equity_max': None,
    'descripcion': 'Sin benchmark predefinido. Comparar contra peers directos.',
    'metricas_clave': ['FCF', 'ROE', 'Revenue Growth', 'Margen Operativo', 'EV/EBITDA'],
}


def _fmt_pct(v):
    return f'{v*100:.2f}%' if v is not None else 'N/D'

def _fmt_num(v, d=2):
    return f'{v:.{d}f}' if v is not None else 'N/D'

def _fmt_big(v):
    if v is None: return 'N/D'
    av = abs(v)
    if av >= 1e12: return f'{v/1e12:.2f}T'
    if av >= 1e9:  return f'{v/1e9:.2f}B'
    if av >= 1e6:  return f'{v/1e6:.2f}M'
    if av >= 1e3:  return f'{v/1e3:.2f}K'
    return str(round(v, 2))

def _es_activo_sin_fundamentals(ticker):
    """Forex, cripto y futuros/commodities no tienen estados financieros en Yahoo Finance."""
    t = ticker.upper()
    return t.endswith('=X') or t.endswith('-USD') or t.endswith('=F')


@st.cache_data(ttl=3600, show_spinner=False)
def _analizar_fundamental_cached(ticker, industria):
    if _es_activo_sin_fundamentals(ticker):
        return None
    try:
        import yfinance as yf
        sector = SECTOR_MAP_FUND.get(industria, 'Sin Clasificar')
        bench  = INDUSTRY_BENCHMARKS_FUND.get(sector, DEFAULT_BENCHMARK_FUND)
        stock  = yf.Ticker(ticker)
        info   = stock.info or {}

        precio_actual    = info.get('currentPrice') or info.get('regularMarketPrice')
        market_cap       = info.get('marketCap')
        enterprise_value = info.get('enterpriseValue')
        nombre           = info.get('longName') or ticker
        recommendation   = info.get('recommendationKey')

        alza_ytd = None
        try:
            inicio_ano = f"{datetime.now().year}-01-02"
            hist = stock.history(start=inicio_ano)
            if not hist.empty and precio_actual:
                alza_ytd = ((precio_actual - hist['Close'].iloc[0]) / hist['Close'].iloc[0]) * 100
        except: pass

        net_income = ebitda = None
        try:
            income = stock.financials
            if not income.empty:
                if 'Net Income' in income.index:   net_income = income.loc['Net Income'].iloc[0]
                if 'EBITDA' in income.index:       ebitda = income.loc['EBITDA'].iloc[0]
        except: pass

        total_debt = cash = None
        try:
            bal = stock.balance_sheet
            if not bal.empty:
                for n in ['Total Debt', 'TotalDebt']:
                    if n in bal.index: total_debt = bal.loc[n].iloc[0]; break
                for n in ['Cash', 'Cash And Cash Equivalents', 'Cash Cash Equivalents And Short Term Investments']:
                    if n in bal.index: cash = bal.loc[n].iloc[0]; break
        except: pass

        fcf            = info.get('freeCashflow')
        op_cf          = info.get('operatingCashflow')
        per            = info.get('trailingPE') or info.get('forwardPE')
        pb             = info.get('priceToBook')
        ps             = info.get('priceToSalesTrailing12Months')
        peg            = info.get('pegRatio')
        roe            = info.get('returnOnEquity')
        roa            = info.get('returnOnAssets')
        curr_ratio     = info.get('currentRatio')
        debt_equity    = info.get('debtToEquity')
        beta           = info.get('beta')
        op_margin      = info.get('operatingMargins')
        profit_margin  = info.get('profitMargins')
        gross_margin   = info.get('grossMargins')
        div_yield      = info.get('dividendYield')
        eps_growth     = info.get('earningsQuarterlyGrowth')
        revenue_growth = info.get('revenueGrowth')
        earnings_growth= info.get('earningsGrowth')
        target_price   = info.get('targetMeanPrice')

        if debt_equity is not None: debt_equity = debt_equity / 100

        try:
            bal = stock.balance_sheet
            if not bal.empty:
                equity = None
                for n in ['Stockholders Equity','Total Stockholders Equity','Common Stock Equity','Total Equity Gross Minority Interest']:
                    if n in bal.index: equity = bal.loc[n].iloc[0]; break
                if debt_equity is None and total_debt is not None and equity and equity != 0:
                    debt_equity = total_debt / equity
                if curr_ratio is None:
                    ca = cl_ = None
                    for n in ['Current Assets','Total Current Assets']:
                        if n in bal.index: ca = bal.loc[n].iloc[0]; break
                    for n in ['Current Liabilities','Total Current Liabilities']:
                        if n in bal.index: cl_ = bal.loc[n].iloc[0]; break
                    if ca and cl_ and cl_ != 0: curr_ratio = ca / cl_
        except: pass

        if div_yield is None:
            div_yield = info.get('yield') or info.get('trailingAnnualDividendYield')

        try:
            income = stock.financials
            if not income.empty:
                tr = None
                for n in ['Total Revenue','Revenue']:
                    if n in income.index: tr = income.loc[n].iloc[0]; break
                if tr and tr != 0:
                    if gross_margin is None:
                        if 'Gross Profit' in income.index: gross_margin = income.loc['Gross Profit'].iloc[0] / tr
                    if op_margin is None:
                        for n in ['Operating Income','Total Operating Income As Reported']:
                            if n in income.index: op_margin = income.loc[n].iloc[0] / tr; break
                    if profit_margin is None and net_income is not None:
                        profit_margin = net_income / tr
        except: pass

        ev_ebitda = enterprise_value / ebitda if enterprise_value and ebitda else None

        campos_clave = [per, pb, roe, roa, gross_margin, op_margin, profit_margin,
                         revenue_growth, debt_equity, market_cap]
        n_datos_disponibles = sum(1 for v in campos_clave if v is not None)
        if n_datos_disponibles < 5:
            return None

        senales = []
        if revenue_growth:
            if revenue_growth > 0.20:   senales.append(('OK','Crecimiento de ingresos explosivo'))
            elif revenue_growth > 0.10: senales.append(('OK','Buen crecimiento de ingresos'))
            elif revenue_growth < 0:    senales.append(('ALT','Caída en ingresos'))
        if eps_growth:
            if eps_growth > 0.20:       senales.append(('OK','EPS creciendo fuertemente'))
            elif eps_growth > 0.10:     senales.append(('OK','Crecimiento positivo de EPS'))
            elif eps_growth < 0:        senales.append(('ALT','EPS en deterioro'))
        if earnings_growth:
            if earnings_growth > 0.15:  senales.append(('OK','Ganancias en expansión'))
            elif earnings_growth < 0:   senales.append(('ALT','Contracción de ganancias'))
        if roe:
            if roe > 0.25:              senales.append(('OK','ROE excepcional'))
            elif roe > 0.15:            senales.append(('OK','ROE saludable'))
            elif roe < 0.08:            senales.append(('ALT','ROE débil'))
        if roa:
            if roa > 0.10:              senales.append(('OK','ROA sólido'))
            elif roa < 0.03:            senales.append(('ALT','Baja eficiencia sobre activos'))
        if gross_margin:
            if gross_margin > 0.50:     senales.append(('OK','Margen bruto excelente'))
            elif gross_margin < 0.20:   senales.append(('ALT','Margen bruto bajo'))
        if op_margin:
            if op_margin > 0.25:        senales.append(('OK','Margen operativo fuerte'))
            elif op_margin < 0.10:      senales.append(('ALT','Margen operativo débil'))
        if profit_margin:
            if profit_margin > 0.20:    senales.append(('OK','Margen neto muy saludable'))
            elif profit_margin < 0.05:  senales.append(('ALT','Margen neto muy bajo'))
        if alza_ytd:
            if alza_ytd > 30:           senales.append(('OK','Momentum extremadamente alcista'))
            elif alza_ytd > 15:         senales.append(('OK','Momentum alcista fuerte'))
            elif alza_ytd < -15:        senales.append(('ALT','Tendencia bajista fuerte'))
        if per:
            if per < 10:                senales.append(('OK','Empresa posiblemente infravalorada (PER < 10)'))
            elif per < 15:              senales.append(('OK','PER atractivo'))
            elif per > 40:              senales.append(('ALT','Valuación exigente (PER > 40)'))
        if pb:
            if pb < 1.5:                senales.append(('OK','P/B atractivo'))
            elif pb > 8:                senales.append(('ALT','P/B elevado'))
        if peg:
            if peg < 1:                 senales.append(('OK','Crecimiento barato según PEG'))
            elif peg > 2:               senales.append(('ALT','Crecimiento caro según PEG'))
        if ev_ebitda:
            if ev_ebitda < 10:          senales.append(('OK','EV/EBITDA atractivo'))
            elif ev_ebitda > 20:        senales.append(('ALT','EV/EBITDA elevado'))
        if fcf:
            if fcf > 0:                 senales.append(('OK','Free Cash Flow positivo'))
            else:                       senales.append(('ALT','Free Cash Flow negativo'))
        if cash and total_debt:
            if cash > total_debt:       senales.append(('OK','Caja superior a deuda'))
            elif total_debt > cash * 3: senales.append(('ALT','Deuda muy superior a caja'))
        if beta:
            if beta > 1.5:              senales.append(('ALT','Volatilidad muy alta (Beta > 1.5)'))
            elif beta < 0.8:            senales.append(('OK','Activo defensivo (Beta bajo)'))
        if curr_ratio:
            if curr_ratio > 2:          senales.append(('OK','Liquidez excelente'))
            elif curr_ratio < 1:        senales.append(('ALT','Riesgo de liquidez'))
        if div_yield:
            if div_yield > 0.05:        senales.append(('OK','Dividendo muy atractivo'))
            elif div_yield > 0.02:      senales.append(('OK','Dividendo saludable'))

        n_ok  = sum(1 for t,_ in senales if t=='OK')
        n_alt = sum(1 for t,_ in senales if t=='ALT')
        if n_ok >= 8:   senal_final = 'COMPRA FUERTE'
        elif n_ok >= 5: senal_final = 'MANTENER'
        else:           senal_final = 'RIESGO / VENDER'

        sector_senales = []
        per_max = bench.get('per_max'); pb_max = bench.get('pb_max')
        gm_min  = bench.get('gross_margin_min'); roe_min = bench.get('roe_min')
        de_max  = bench.get('debt_equity_max')
        if per and per_max:
            if per < per_max*0.6: sector_senales.append(('POS', f'PER ({per:.1f}x) muy por debajo del límite sectorial ({per_max}x)'))
            elif per < per_max:   sector_senales.append(('POS', f'PER ({per:.1f}x) dentro del rango aceptable (max {per_max}x)'))
            else:                 sector_senales.append(('ALT', f'PER ({per:.1f}x) supera benchmark sectorial ({per_max}x)'))
        if pb and pb_max:
            if pb < 1.0:       sector_senales.append(('ALT', f'P/B ({pb:.2f}x) < 1 — cotiza bajo valor libro'))
            elif pb < pb_max:  sector_senales.append(('POS', f'P/B ({pb:.2f}x) dentro del rango sectorial (max {pb_max}x)'))
            else:              sector_senales.append(('ALT', f'P/B ({pb:.2f}x) elevado vs benchmark ({pb_max}x)'))
        if gross_margin and gm_min:
            if gross_margin > gm_min: sector_senales.append(('POS', f'Margen bruto ({gross_margin*100:.1f}%) supera mínimo sectorial ({gm_min*100:.0f}%)'))
            else:                     sector_senales.append(('ALT', f'Margen bruto ({gross_margin*100:.1f}%) bajo benchmark ({gm_min*100:.0f}%)'))
        if roe and roe_min:
            if roe > roe_min*1.5: sector_senales.append(('POS', f'ROE ({roe*100:.1f}%) muy sobre benchmark ({roe_min*100:.0f}%)'))
            elif roe > roe_min:   sector_senales.append(('POS', f'ROE ({roe*100:.1f}%) supera mínimo sectorial ({roe_min*100:.0f}%)'))
            else:                 sector_senales.append(('ALT', f'ROE ({roe*100:.1f}%) bajo benchmark sectorial ({roe_min*100:.0f}%)'))
        if debt_equity is not None and de_max:
            if debt_equity < de_max*0.5: sector_senales.append(('POS', f'Deuda/Equity ({debt_equity:.2f}x) muy conservadora vs sector'))
            elif debt_equity < de_max:   sector_senales.append(('POS', f'Deuda/Equity ({debt_equity:.2f}x) dentro del rango ({de_max}x max)'))
            else:                        sector_senales.append(('ALT', f'Deuda/Equity ({debt_equity:.2f}x) supera límite sectorial ({de_max}x)'))
        if fcf is not None:
            if fcf > 0: sector_senales.append(('POS', 'FCF positivo — genera caja real'))
            else:       sector_senales.append(('ALT', 'FCF negativo — revisar si es ciclo inversor o problema estructural'))

        return {
            'ticker': ticker, 'nombre': nombre, 'sector': sector, 'industria': industria,
            'precio': precio_actual, 'market_cap': market_cap, 'ev': enterprise_value,
            'per': per, 'pb': pb, 'ps': ps, 'peg': peg, 'ev_ebitda': ev_ebitda,
            'roe': roe, 'roa': roa, 'gross_margin': gross_margin, 'op_margin': op_margin,
            'profit_margin': profit_margin, 'debt_equity': debt_equity, 'curr_ratio': curr_ratio,
            'beta': beta, 'div_yield': div_yield, 'revenue_growth': revenue_growth,
            'eps_growth': eps_growth, 'earnings_growth': earnings_growth,
            'fcf': fcf, 'op_cf': op_cf, 'target_price': target_price, 'cash': cash,
            'alza_ytd': alza_ytd, 'recommendation': recommendation,
            'senales': senales, 'senal_final': senal_final, 'sector_senales': sector_senales,
            'bench': bench, 'n_ok': n_ok, 'n_alt': n_alt,
        }
    except Exception as e:
        return None


def _sanitizar_json(obj):
    """Convierte tipos numpy/pandas a tipos nativos de Python para que
    Supabase pueda serializar el dict como jsonb sin explotar."""
    if isinstance(obj, dict):
        return {k: _sanitizar_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitizar_json(v) for v in obj]
    if isinstance(obj, np.floating):
        return None if np.isnan(obj) else float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, float) and np.isnan(obj):
        return None
    return obj


def _fund_supabase_guardar(ticker, industria, datos):
    try:
        payload = _sanitizar_json({k: v for k, v in datos.items() if not k.startswith('_')})
        supabase.table('fundamental_cache').upsert({
            'ticker': ticker, 'industria': industria, 'datos': payload,
            'actualizado_en': ahora_ar().isoformat(),
        }).execute()
    except Exception:
        pass  # si falla el guardado en Supabase, no rompemos el análisis en pantalla


def _fund_supabase_leer(ticker):
    try:
        res = supabase.table('fundamental_cache').select('datos, actualizado_en').eq('ticker', ticker).limit(1).execute()
        if res.data:
            return res.data[0]['datos'], res.data[0]['actualizado_en']
    except Exception:
        pass
    return None, None


def analizar_fundamental(ticker, industria):
    """Envoltorio persistente en 3 capas: 1) descarga en vivo (Yahoo), 2) si falla,
    lo último bueno de esta sesión, 3) si tampoco hay, lo último bueno guardado en
    Supabase (compartido entre todos los usuarios). Solo se pisa Supabase cuando
    la descarga en vivo sale bien."""
    if '_fund_cache_ok' not in st.session_state:
        st.session_state['_fund_cache_ok'] = {}

    resultado = _analizar_fundamental_cached(ticker, industria)
    if resultado is not None:
        st.session_state['_fund_cache_ok'][ticker] = resultado
        _fund_supabase_guardar(ticker, industria, resultado)
        return resultado

    en_sesion = st.session_state['_fund_cache_ok'].get(ticker)
    if en_sesion is not None:
        return en_sesion

    datos_db, ts_db = _fund_supabase_leer(ticker)
    if datos_db is not None:
        datos_db = dict(datos_db)
        datos_db['_desde_respaldo'] = True
        datos_db['_respaldo_fecha'] = ts_db
        st.session_state['_fund_cache_ok'][ticker] = datos_db
        return datos_db

    return None


def _senal_color(s):
    if 'COMPRA' in s: return '#3fb950', 'rgba(63,185,80,0.12)'
    if 'MANTENER' in s: return '#e3b341', 'rgba(227,179,65,0.12)'
    return '#f85149', 'rgba(248,81,73,0.12)'


# ==============================================================
#  RESUMEN VISUAL FUNDAMENTAL — semáforo + scores 0-10 + veredicto
# ==============================================================

def _resumen_visual_fundamental(res):
    """Toma el dict que devuelve analizar_fundamental() y arma:
    - categorias: lista de (nombre, emoji, label) para la tabla semáforo
    - 4 scores 0-10 (calidad, valoración, crecimiento, riesgo)
    - veredicto final y una conclusión de una línea."""

    def _prom(lst):
        lst = [x for x in lst if x is not None]
        return round(sum(lst) / len(lst), 1) if lst else None

    roe = res.get('roe'); gm = res.get('gross_margin'); om = res.get('op_margin')
    fcf = res.get('fcf'); rg = res.get('revenue_growth'); de = res.get('debt_equity')
    cr = res.get('curr_ratio'); per = res.get('per'); pb = res.get('pb')
    peg = res.get('peg'); beta = res.get('beta'); eg = res.get('eps_growth')
    ytd = res.get('alza_ytd')

    categorias = []

    if roe is not None:
        v = roe * 100
        if   v >= 25: categorias.append(('Rentabilidad (ROE)', '🟢', 'Excepcional'))
        elif v >= 15: categorias.append(('Rentabilidad (ROE)', '🟢', 'Buena'))
        elif v >= 8:  categorias.append(('Rentabilidad (ROE)', '🟡', 'Aceptable'))
        else:         categorias.append(('Rentabilidad (ROE)', '🔴', 'Débil'))

    if gm is not None:
        v = gm * 100
        if   v >= 60: categorias.append(('Margen Bruto', '🟢', 'Excelente'))
        elif v >= 40: categorias.append(('Margen Bruto', '🟢', 'Bueno'))
        elif v >= 20: categorias.append(('Margen Bruto', '🟡', 'Moderado'))
        else:         categorias.append(('Margen Bruto', '🔴', 'Bajo'))

    if fcf is not None:
        categorias.append(('Flujo de Caja (FCF)', '🟢' if fcf > 0 else '🔴',
                            'Positivo' if fcf > 0 else 'Negativo'))

    if rg is not None:
        v = rg * 100
        if   v >= 20: categorias.append(('Crecimiento', '🟢', 'Muy alto'))
        elif v >= 10: categorias.append(('Crecimiento', '🟢', 'Bueno'))
        elif v >= 0:  categorias.append(('Crecimiento', '🟡', 'Moderado'))
        else:         categorias.append(('Crecimiento', '🔴', 'Contracción'))

    if de is not None:
        if   de < 0.5: categorias.append(('Endeudamiento', '🟢', 'Muy bajo'))
        elif de < 1:   categorias.append(('Endeudamiento', '🟢', 'Conservador'))
        elif de < 2:   categorias.append(('Endeudamiento', '🟡', 'Elevado'))
        else:          categorias.append(('Endeudamiento', '🔴', 'Muy elevado'))

    if cr is not None:
        if   cr >= 2:   categorias.append(('Liquidez', '🟢', 'Excelente'))
        elif cr >= 1.5: categorias.append(('Liquidez', '🟢', 'Saludable'))
        elif cr >= 1:   categorias.append(('Liquidez', '🟡', 'Ajustada'))
        else:           categorias.append(('Liquidez', '🔴', 'Riesgo de liquidez'))

    if per is not None and per > 0:
        if   per < 10: categorias.append(('Valoración', '🟢', 'Muy barata'))
        elif per < 15: categorias.append(('Valoración', '🟢', 'Barata'))
        elif per < 25: categorias.append(('Valoración', '🟡', 'Normal'))
        elif per < 40: categorias.append(('Valoración', '🟠', 'Exigente'))
        else:          categorias.append(('Valoración', '🔴', 'Muy exigente'))

    if beta is not None:
        if   beta < 0.8: categorias.append(('Volatilidad', '🟢', 'Baja (defensiva)'))
        elif beta < 1.2: categorias.append(('Volatilidad', '🟡', 'En línea con el mercado'))
        elif beta < 1.5: categorias.append(('Volatilidad', '🟠', 'Alta'))
        else:            categorias.append(('Volatilidad', '🔴', 'Muy alta'))

    # ── Scores 0-10 ──────────────────────────────────────────────
    calidad = _prom([
        min(10, max(0, roe * 100 / 3)) if roe is not None else None,
        min(10, max(0, gm * 100 / 7)) if gm is not None else None,
        min(10, max(0, om * 100 / 3.5)) if om is not None else None,
        (10 if fcf and fcf > 0 else 2) if fcf is not None else None,
        max(0, 10 - de * 3) if de is not None else None,
    ])

    valoracion = _prom([
        max(0, min(10, 10 - (per - 10) * 10 / 30)) if per else None,
        max(0, min(10, 10 - (peg - 0.5) * 10 / 2)) if peg else None,
        max(0, min(10, 10 - (pb - 1) * 10 / 7)) if pb else None,
    ])

    crecimiento = _prom([
        max(0, min(10, 5 + rg * 100 / 4)) if rg is not None else None,
        max(0, min(10, 5 + eg * 100 / 4)) if eg is not None else None,
        max(0, min(10, 5 + ytd / 6)) if ytd is not None else None,
    ])

    riesgo = _prom([
        max(0, min(10, beta * 5)) if beta is not None else None,
        max(0, min(10, de * 3)) if de is not None else None,
        max(0, min(10, 10 - (cr - 1) * 5)) if cr is not None else None,
    ])

    componentes = [calidad, valoracion, crecimiento, (10 - riesgo) if riesgo is not None else None]
    pesos = [0.35, 0.20, 0.25, 0.20]
    num, den = 0.0, 0.0
    for c, p in zip(componentes, pesos):
        if c is not None:
            num += c * p; den += p
    conclusion = round(num / den, 1) if den > 0 else None

    if conclusion is None:
        veredicto, v_emoji = 'SIN DATOS SUFICIENTES', '⚪'
    elif conclusion >= 8.5:
        veredicto, v_emoji = 'COMPRA FUERTE', '🟢'
    elif conclusion >= 7:
        veredicto, v_emoji = 'COMPRA', '🟢'
    elif conclusion >= 5.5:
        veredicto, v_emoji = 'MANTENER', '🟡'
    elif conclusion >= 4:
        veredicto, v_emoji = 'RIESGO', '🟠'
    else:
        veredicto, v_emoji = 'EVITAR', '🔴'

    def _frase(valor, mapa):
        if valor is None: return 'sin datos suficientes de calidad'
        for (lo, hi), txt in mapa.items():
            if lo <= valor < hi: return txt
        return 'sin datos suficientes'

    txt_calidad = _frase(calidad, {(8.5,999):'de altísima calidad',(7,8.5):'de buena calidad',
                                    (5,7):'de calidad aceptable',(0,5):'de calidad débil'})
    txt_valor = _frase(valoracion, {(7,999):'con valoración atractiva',(4,7):'con valoración razonable',
                                     (0,4):'con valoración exigente'})
    conclusion_texto = (f'Empresa {txt_calidad}, {txt_valor}.'
                         if calidad is not None and valoracion is not None
                         else 'Datos insuficientes para una conclusión completa.')

    return dict(categorias=categorias, calidad=calidad, valoracion=valoracion,
                crecimiento=crecimiento, riesgo=riesgo, conclusion=conclusion,
                veredicto=veredicto, v_emoji=v_emoji, conclusion_texto=conclusion_texto)


def render_resumen_visual_fundamental(res):
    resumen = _resumen_visual_fundamental(res)

    color_map = {'🟢': '#3fb950', '🟡': '#e3b341', '🟠': '#f0883e', '🔴': '#f85149'}
    filas_html = ''.join(
        f'<tr style="border-bottom:1px solid #21262d">'
        f'<td style="padding:9px 14px;text-align:left;color:#e6edf3;font-size:13px">{emo} {nombre}</td>'
        f'<td style="padding:9px 14px;text-align:right;font-weight:700;font-size:13px;'
        f'color:{color_map.get(emo,"#8b949e")}">{label}</td></tr>'
        for nombre, emo, label in resumen['categorias']
    )
    st.markdown(f"""
    <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;overflow:hidden;margin-bottom:16px">
      <table style="width:100%;border-collapse:collapse">{filas_html}</table>
    </div>
    """, unsafe_allow_html=True)

    def _fmt_score(v):
        return f'{v:.1f}/10' if v is not None else 'N/D'

    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric('⭐ Calidad del Negocio', _fmt_score(resumen['calidad']))
    with c2: st.metric('💰 Valoración', _fmt_score(resumen['valoracion']))
    with c3: st.metric('📈 Potencial de Crecimiento', _fmt_score(resumen['crecimiento']))
    with c4: st.metric('⚠️ Nivel de Riesgo', _fmt_score(resumen['riesgo']))

    v_color = color_map.get(resumen['v_emoji'], '#8b949e')
    st.markdown(f"""
    <div style="background:{v_color}15;border:1.5px solid {v_color};border-radius:12px;
         padding:18px 22px;text-align:center;margin:16px 0">
      <div style="font-size:11px;color:#8b949e;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">Veredicto Final</div>
      <div style="font-size:22px;font-weight:800;color:{v_color}">{resumen['v_emoji']} {resumen['veredicto']}</div>
    </div>
    <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:14px 18px">
      <div style="font-size:12px;color:#6CC24A;font-weight:700;margin-bottom:4px">⭐ Conclusión</div>
      <div style="font-size:14px;color:#e6edf3">
        <b>{_fmt_score(resumen['conclusion'])}</b> — {resumen['conclusion_texto']}
      </div>
    </div>
    """, unsafe_allow_html=True)


# ==============================================================
#  PERFIL DE EMPRESA — logo, capitalización, descripción del negocio
# ==============================================================

def _extraer_dominio(website):
    if not website:
        return None
    try:
        dominio = website.replace('https://', '').replace('http://', '').split('/')[0]
        dominio = dominio.replace('www.', '')
        return dominio if dominio and '.' in dominio else None
    except Exception:
        return None


def _logo_url_desde_dominio(website):
    """Clearbit como principal; si falla, se usa Google Favicons como respaldo (ver logo_html)."""
    dominio = _extraer_dominio(website)
    return f'https://logo.clearbit.com/{dominio}' if dominio else None


SECTOR_ES = {
    'Technology': 'Tecnología', 'Financial Services': 'Servicios Financieros',
    'Healthcare': 'Salud', 'Energy': 'Energía', 'Industrials': 'Industriales',
    'Consumer Cyclical': 'Consumo Cíclico', 'Consumer Defensive': 'Consumo Defensivo',
    'Basic Materials': 'Materiales Básicos', 'Communication Services': 'Comunicaciones',
    'Utilities': 'Servicios Públicos', 'Real Estate': 'Bienes Raíces',
}


@st.cache_data(ttl=604800, show_spinner=False)
def _traducir_es(texto):
    """Traduce el resumen de negocio al español. Cacheado 7 días porque el texto
    de una empresa no cambia seguido y así no volvemos a traducir en cada carga."""
    if not texto:
        return texto
    try:
        from deep_translator import GoogleTranslator
        # GoogleTranslator tiene límite ~5000 caracteres por llamada
        if len(texto) > 4500:
            partes = [texto[i:i+4500] for i in range(0, len(texto), 4500)]
            return ' '.join(GoogleTranslator(source='en', target='es').translate(p) for p in partes)
        return GoogleTranslator(source='en', target='es').translate(texto)
    except Exception:
        return texto  # si falla la traducción, mostramos el original en vez de romper la página


@st.cache_data(ttl=86400, show_spinner=False)
def _obtener_perfil_empresa_cached(ticker):
    """Datos de perfil: nombre, logo, capitalización, sector/industria, empleados,
    sede, descripción del negocio (traducida), exchange, rango 52 semanas,
    % institucional/insider y CEO (todo sale de yfinance.info, sin requests extra)."""
    if _es_activo_sin_fundamentals(ticker):
        return None
    import time
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        info = None
        # Reintenta hasta 2 veces con pausa corta si Yahoo devuelve vacío por rate limit
        for intento in range(2):
            info = stock.info or {}
            if info:
                break
            time.sleep(1.5)
        info = info or {}
        website = info.get('website')

        ceo = None
        oficiales = info.get('companyOfficers') or []
        for o in oficiales:
            titulo = (o.get('title') or '').lower()
            if 'chief executive' in titulo or titulo == 'ceo':
                ceo = o.get('name')
                break
        if ceo is None and oficiales:
            ceo = oficiales[0].get('name')

        sector_en = info.get('sector')
        precio_actual = info.get('currentPrice') or info.get('regularMarketPrice')
        max52 = info.get('fiftyTwoWeekHigh')
        min52 = info.get('fiftyTwoWeekLow')
        pct_desde_max = ((precio_actual - max52) / max52 * 100) if precio_actual and max52 else None
        pct_desde_min = ((precio_actual - min52) / min52 * 100) if precio_actual and min52 else None

        return {
            'ticker': ticker,
            'nombre': info.get('longName') or info.get('shortName') or ticker,
            'logo_url': _logo_url_desde_dominio(website),
            'dominio': _extraer_dominio(website),
            'website': website,
            'market_cap': info.get('marketCap'),
            'enterprise_value': info.get('enterpriseValue'),
            'sector': SECTOR_ES.get(sector_en, sector_en),
            'industria_yahoo': info.get('industry'),
            'empleados': info.get('fullTimeEmployees'),
            'pais': info.get('country'),
            'ciudad': info.get('city'),
            'descripcion': _traducir_es(info.get('longBusinessSummary')),
            'precio': precio_actual,
            'moneda': info.get('currency'),
            'exchange': info.get('fullExchangeName') or info.get('exchange'),
            'semana52_max': max52,
            'semana52_min': min52,
            'pct_desde_max52': pct_desde_max,
            'pct_desde_min52': pct_desde_min,
            'pct_institucional': info.get('heldPercentInstitutions'),
            'pct_insiders': info.get('heldPercentInsiders'),
            'ceo': ceo,
        }
    except Exception:
        return None


def _perfil_supabase_guardar(ticker, datos):
    try:
        payload = _sanitizar_json({k: v for k, v in datos.items() if not k.startswith('_')})
        supabase.table('perfil_cache').upsert({
            'ticker': ticker, 'datos': payload, 'actualizado_en': ahora_ar().isoformat(),
        }).execute()
    except Exception:
        pass


def _perfil_supabase_leer(ticker):
    try:
        res = supabase.table('perfil_cache').select('datos, actualizado_en').eq('ticker', ticker).limit(1).execute()
        if res.data:
            return res.data[0]['datos'], res.data[0]['actualizado_en']
    except Exception:
        pass
    return None, None


def obtener_perfil_empresa(ticker):
    """Envoltorio persistente en 3 capas: descarga en vivo → último bueno de esta
    sesión → último bueno guardado en Supabase (compartido entre usuarios)."""
    if '_perfil_cache_ok' not in st.session_state:
        st.session_state['_perfil_cache_ok'] = {}

    resultado = _obtener_perfil_empresa_cached(ticker)
    if resultado is not None:
        st.session_state['_perfil_cache_ok'][ticker] = resultado
        _perfil_supabase_guardar(ticker, resultado)
        return resultado

    en_sesion = st.session_state['_perfil_cache_ok'].get(ticker)
    if en_sesion is not None:
        return en_sesion

    datos_db, ts_db = _perfil_supabase_leer(ticker)
    if datos_db is not None:
        datos_db = dict(datos_db)
        datos_db['_desde_respaldo'] = True
        datos_db['_respaldo_fecha'] = ts_db
        st.session_state['_perfil_cache_ok'][ticker] = datos_db
        return datos_db

    return None


def logo_html(logo_url, size=28, dominio_fallback=None):
    """Devuelve el <img> del logo. Si Clearbit falla, cae al ícono de Google Favicons;
    si eso también falla, oculta la imagen en vez de mostrar un cuadro roto."""
    if not logo_url and not dominio_fallback:
        return ''
    fallback = f'https://www.google.com/s2/favicons?sz=128&domain={dominio_fallback}' if dominio_fallback else ''
    src = logo_url or fallback
    if fallback and fallback != src:
        onerror = f"this.onerror=null;this.src='{fallback}';"
    else:
        onerror = "this.style.display='none';"
    return (
        f'<img src="{src}" width="{size}" height="{size}" '
        f'style="border-radius:6px;object-fit:contain;background:#fff;padding:2px;vertical-align:middle" '
        f'onerror="{onerror}">'
    )


def render_perfil_empresa(ticker, key_suffix=''):
    """Card con logo, capitalización y descripción del negocio. Usar en cualquier
    pantalla donde se analice un ticker individual (Buscador, Comparador, Fundamental)."""
    if _es_activo_sin_fundamentals(ticker):
        return
    with st.spinner('Cargando perfil de la empresa...'):
        perfil = obtener_perfil_empresa(ticker)

    if perfil is None:
        col_w1, col_w2 = st.columns([4, 1])
        with col_w1:
            st.warning(
                f'⚠️ No se pudo cargar el perfil de {ticker}. '
                'Es probable que sea un límite temporal de Yahoo Finance (demasiadas solicitudes seguidas). '
                'Esperá 1-2 minutos y probá de nuevo.'
            )
        with col_w2:
            if st.button('🔄 Reintentar', key=f'retry_perfil_{key_suffix}_{ticker}'):
                _obtener_perfil_empresa_cached.clear()
                st.rerun()
        return

    if not perfil.get('descripcion'):
        st.info(f'ℹ️ {ticker} no tiene descripción de negocio disponible en Yahoo Finance. Mostrando el resto de los datos igual.')
        perfil['descripcion'] = 'Descripción no disponible.'
        return

    mc = _fmt_big(perfil.get('market_cap'))
    ev = _fmt_big(perfil.get('enterprise_value'))
    empleados = f"{perfil['empleados']:,}" if perfil.get('empleados') else 'N/D'
    ubicacion = ', '.join(x for x in [perfil.get('ciudad'), perfil.get('pais')] if x) or 'N/D'
    exchange = perfil.get('exchange') or 'N/D'
    ceo = perfil.get('ceo') or 'N/D'
    if perfil.get('semana52_min') and perfil.get('semana52_max'):
        pct_max_txt = f"{perfil['pct_desde_max52']:+.1f}%" if perfil.get('pct_desde_max52') is not None else ''
        pct_min_txt = f"{perfil['pct_desde_min52']:+.1f}%" if perfil.get('pct_desde_min52') is not None else ''
        rango52 = (
            f"{fmt_precio(perfil['semana52_min'])} – {fmt_precio(perfil['semana52_max'])}"
            f'<br><span style="font-size:10px;color:#6b7d9a">'
            f'{pct_max_txt} desde máx · {pct_min_txt} desde mín</span>'
        )
    else:
        rango52 = 'N/D'
    pct_inst = _fmt_pct(perfil.get('pct_institucional'))
    pct_ins  = _fmt_pct(perfil.get('pct_insiders'))
    website_html = (
        f'<a href="{perfil["website"]}" target="_blank" style="color:#3a7bd5;text-decoration:none">{perfil["website"]}</a>'
        if perfil.get('website') else 'N/D'
    )

    st.markdown(f"""
    <div style="background:#0d1117;border:1px solid #21262d;border-top:2px solid #3a7bd5;
         border-radius:12px;padding:20px 24px;margin-bottom:16px">
      <div style="text-align:center;margin-bottom:14px">
        <div style="font-size:17px;font-weight:700;color:#e6edf3">{perfil['nombre']} <span style="color:#6b7d9a;font-size:12px">({ticker})</span></div>
        <div style="font-size:12px;color:#f5f7fa;margin-top:2px">{perfil.get('sector') or 'N/D'} · {perfil.get('industria_yahoo') or 'N/D'} · {exchange}</div>
      </div>
      <div class="kpi-card-grid" style="grid-template-columns:repeat(4,1fr);margin-bottom:10px">
        <div><div class="kpi-metric-label">Market Cap</div><div class="kpi-metric-value">{mc}</div></div>
        <div><div class="kpi-metric-label">Enterprise Value</div><div class="kpi-metric-value">{ev}</div></div>
        <div><div class="kpi-metric-label">Empleados</div><div class="kpi-metric-value">{empleados}</div></div>
        <div><div class="kpi-metric-label">Sede</div><div class="kpi-metric-value" style="font-size:13px">{ubicacion}</div></div>
      </div>
      <div class="kpi-card-grid" style="grid-template-columns:repeat(4,1fr);margin-bottom:14px">
        <div><div class="kpi-metric-label">Rango 52 sem.</div><div class="kpi-metric-value" style="font-size:14px">{rango52}</div></div>
        <div><div class="kpi-metric-label">% Institucional</div><div class="kpi-metric-value">{pct_inst}</div></div>
        <div><div class="kpi-metric-label">% Insiders</div><div class="kpi-metric-value">{pct_ins}</div></div>
        <div><div class="kpi-metric-label">CEO</div><div class="kpi-metric-value" style="font-size:13px">{ceo}</div></div>
      </div>
      <div style="font-size:12px;color:#6b7d9a;margin-bottom:14px">🌐 Sitio web: {website_html}</div>
      <div style="font-size:11px;font-weight:700;color:#6CC24A;text-transform:uppercase;letter-spacing:.6px;margin-bottom:6px">
        🏢 A qué se dedica / Modelo de negocio
      </div>
      <div style="font-size:13px;color:#f5f7fa;line-height:1.7">{perfil['descripcion']}</div>
    </div>
    """, unsafe_allow_html=True)


# ==============================================================
#  MÓDULO BUSCADOR UNIVERSAL
# ==============================================================


def modulo_buscador():
    prefill = st.session_state.get('ticker_from_table', '')
    if prefill:
        st.session_state['ticker_from_table'] = ''

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #3a7bd5;
         border-radius:14px; padding:32px 36px; margin-bottom:28px;">
      <div style="display:flex;align-items:flex-start;gap:18px">
        <div style="font-size:32px;line-height:1">🔍</div>
        <div>
          <div style="font-size:18px;font-weight:700;color:#e6edf3;letter-spacing:-0.4px;margin-bottom:6px">
            Buscador Universal de Activos
          </div>
          <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
            Elegí cualquier activo del listado (con autocompletado) o escribilo manualmente.<br>
            Obtenés análisis completo de <b style="color:#f0883e">corto plazo</b> (percentiles históricos)
            y <b style="color:#3fb950">largo plazo</b> (cuantitativo 2 años).
          </div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    col_inp, col_btn = st.columns([4, 1])
    with col_inp:
        ticker_final = selector_ticker_autocomplete('buscador_universal', prefill)
    with col_btn:
        st.markdown('<div style="height:6px"></div>', unsafe_allow_html=True)
        analizar = st.button('▶ Analizar', use_container_width=True, key='btn_buscar')

    st.markdown('<div style="font-size:10px;color:#3a4a5f;font-weight:600;margin-top:6px">¿No sabés por dónde arrancar? Probá con un clic →</div>', unsafe_allow_html=True)
    cq1, cq2, cq3, cq4 = st.columns(4)
    ejemplos_rapidos = [('🎲 NVDA', 'NVDA'), ('₿ BTC-USD', 'BTC-USD'), ('🇦🇷 GGAL', 'GGAL'), ('🥇 Oro (GC=F)', 'GC=F')]
    for col_q, (label_q, tk_q) in zip([cq1, cq2, cq3, cq4], ejemplos_rapidos):
        with col_q:
            if st.button(label_q, key=f'btn_rapido_{tk_q}', use_container_width=True):
                st.session_state['ticker_from_table'] = tk_q
                st.session_state['nav_horizonte'] = 'buscador'
                st.session_state['nav_modulo'] = 'buscador'
                st.rerun()

    auto_run = bool(prefill and ticker_final == prefill.strip().upper()
                    and st.session_state.get('nav_modulo') == 'buscador')

    # ── NUEVO: bandera persistente ──────────────────────────────────────
    # Sin esto, cualquier interacción posterior (radio Línea/Velas, tabs,
    # expanders, etc.) provoca un rerun de Streamlit donde 'analizar' vuelve
    # a False y 'prefill' ya está vacío -> se perdía el análisis renderizado.
    if analizar or auto_run:
        st.session_state['buscador_ticker_confirmado'] = ticker_final

    ticker_confirmado = st.session_state.get('buscador_ticker_confirmado', '')

    if not ticker_confirmado:
        st.markdown("""
        <div style="border:1px dashed #21262d;border-radius:12px;padding:48px;text-align:center;margin-top:20px">
          <div style="font-size:44px;margin-bottom:14px;opacity:.6">📊</div>
          <div style="color:#6b7d9a;font-size:13px;font-weight:500;line-height:1.8">
            Elegí el activo arriba y presioná <b style="color:#e6edf3">Analizar</b><br>
            para ver el análisis completo del activo.
          </div>
        </div>
        """, unsafe_allow_html=True)
        return

    _renderizar_buscador(ticker_confirmado)


def _renderizar_buscador(ticker):
    st.markdown(f'<div class="sec-title">Resultados para: {ticker}</div>', unsafe_allow_html=True)

    industria = TICKER_INDUSTRY.get(ticker, 'Externo / Manual')

    # ── Selector de qué mostrar ─────────────────────────────────
    SECCIONES_DISPONIBLES = {
        '🏢 Perfil de la empresa':                     'perfil',
        '⚡ Corto Plazo (1-30 días)':                   'corto',
        '📈 Largo Plazo (2 años cuantitativo)':         'largo',
        '📊 Análisis Fundamental':                      'fundamental',
        '📐 Top-Down Cuantitativo (Mediano/Largo Plazo)':'tdc',
        '👥📑 Accionistas y Estados Financieros':       'estados',
    }
    secciones_sel = st.multiselect(
        '¿Qué querés ver?', list(SECCIONES_DISPONIBLES.keys()),
        default=st.session_state.get('buscador_secciones_sel', list(SECCIONES_DISPONIBLES.keys())),
        key='buscador_secciones_sel',
        help='Elegí qué bloques de análisis mostrar para este ticker.',
    )
    activos = set(SECCIONES_DISPONIBLES[s] for s in secciones_sel)

    if not activos:
        st.info('Seleccioná al menos una sección arriba para ver el análisis.')
        return

    if 'perfil' in activos:
        render_perfil_empresa(ticker, key_suffix='buscador_top')

    # ── Corto plazo ──────────────────────────────────────────────
    if 'corto' in activos:
        st.markdown('### ⚡ Análisis Corto Plazo (1–30 días)')
        with st.spinner('Cargando datos de corto plazo...'):
            df_v = descargar_datos(ticker, '3mo')
            df_m = descargar_datos(ticker, '1mo')

        if df_v is None or df_m is None:
            st.warning(f'No se encontraron datos para {ticker}. Verificá que el símbolo sea correcto.')
        else:
            cl_v = get_close_series(df_v)
            cl_m = get_close_series(df_m)
            if cl_v is not None and cl_m is not None and len(cl_v.dropna()) >= 15:
                atr = calcular_atr(df_m)
                sa, sn, ss = scores_corto(cl_v, cl_m, atr)
                sf  = sa*0.45 + sn*0.35 + ss*0.20
                rsi = float(calcular_rsi(cl_m, p=7).iloc[-1])
                ret_5d  = float(cl_m.pct_change(5).iloc[-1]*100) if len(cl_m)>=6 else 0
                ret_10d = float(cl_m.pct_change(10).iloc[-1]*100) if len(cl_m)>=11 else 0
                precio  = float(cl_m.iloc[-1])
                señal   = señal_accion_corto(sa, sn, ss)
                lbl_sa, col_sa, _ = clasificar_score(sa)

                kpi_cards_4([
                    ('Score Acumulación', f'{sa:.0f}/100', lbl_sa, col_sa),
                    ('Score Anticipación', f'{sn:.0f}/100', 'Momentum futuro', score_color_hex(sn)),
                    ('Score Sentimiento', f'{ss:.0f}/100', 'Percentil precio', score_color_hex(ss)),
                    ('Score Final', f'{sf:.0f}/100', 'Compuesto 45/35/20', score_color_hex(sf)),
                ])

                c1, c2, c3, c4, c5 = st.columns(5)
                with c1: st.metric('RSI (7)', f'{rsi:.1f}', help=G('RSI'))
                with c2: st.metric('Ret 5d', f'{ret_5d:+.2f}%')
                with c3: st.metric('Ret 10d', f'{ret_10d:+.2f}%')
                with c4: st.metric('Precio', fmt_precio(precio))
                with c5: st.metric('Industria', industria[:15])

                st.markdown(f'<div style="margin:10px 0"><span class="signal-pill">{señal}</span></div>', unsafe_allow_html=True)

                precios = cl_m.values
                if len(precios) > 2:
                    st.plotly_chart(fig_mini_precio(ticker, precios), use_container_width=True, config=PLOTLY_CONFIG, key=f'mini_{ticker}')
            else:
                st.info('Datos insuficientes para el análisis de corto plazo.')

    # ── Largo plazo ──────────────────────────────────────────────
    r = None
    cl = None
    df_tk = None
    if 'largo' in activos or 'estados' in activos or 'tdc' in activos:
        # descargamos precios una sola vez si hace falta para largo
        pass

    if 'largo' in activos:
        if activos != {'largo'}:
            st.markdown('---')
        st.markdown('### 📈 Análisis Largo Plazo (2 años cuantitativo)')
        with st.spinner('Cargando 2 años de datos...'):
            df_tk = descargar_datos(ticker, '2y')

        if df_tk is None or df_tk.empty:
            st.warning('No hay datos suficientes para el análisis de largo plazo.')
        else:
            cl = get_close_series(df_tk)
            if cl is None or len(cl) < 150:
                st.info('Se necesitan al menos 150 sesiones para el análisis cuantitativo.')
            else:
                r = analizar_largo(ticker, cl)
                if r is None:
                    st.warning('No se pudo calcular el análisis cuantitativo.')
                else:
                    render_largo_completo(ticker, cl, r, key_suffix='buscador', df_ohlc=df_tk)

    # ── ANÁLISIS FUNDAMENTAL — resumen visual ───────────────────────
    if 'fundamental' in activos:
        st.markdown('---')
        st.markdown('### 📊 Análisis Fundamental')

        industria_fund = TICKER_INDUSTRY.get(ticker, 'Sin Clasificar')
        sector_fund    = SECTOR_MAP_FUND.get(industria_fund, 'Sin Clasificar')

        with st.spinner('Descargando ratios fundamentales...'):
            res_fund = analizar_fundamental(ticker, industria_fund)

        if res_fund is None:
            st.info('No se encontraron datos fundamentales para este activo (puede ser cripto, forex o commodity sin estados financieros).')
        else:
            mc1, mc2, mc3 = st.columns(3)
            with mc1: st.metric('Sector', sector_fund[:20])
            with mc2: st.metric('Industria', industria_fund[:20])
            with mc3: st.metric('Rec. Analistas', res_fund.get('recommendation') or 'N/D')

            render_resumen_visual_fundamental(res_fund)

            with st.expander('🔎 Ver todos los datos y señales detalladas'):
                bench_b = res_fund['bench']
                cols_fund_kpi = st.columns(3)
                with cols_fund_kpi[0]:
                    kpi_card_fundamental('Valuación', '#3a7bd5', [
                        ('PER', f"{_fmt_num(res_fund.get('per'))}x"),
                        ('P/B', f"{_fmt_num(res_fund.get('pb'))}x"),
                        ('EV/EBITDA', f"{_fmt_num(res_fund.get('ev_ebitda'))}x"),
                        ('PEG', f"{_fmt_num(res_fund.get('peg'))}"),
                    ], f"{G('PER')} | {G('P/B')}")
                with cols_fund_kpi[1]:
                    kpi_card_fundamental('Rentabilidad', '#3fb950', [
                        ('ROE', _fmt_pct(res_fund.get('roe'))),
                        ('ROA', _fmt_pct(res_fund.get('roa'))),
                        ('Mg.Bruto', _fmt_pct(res_fund.get('gross_margin'))),
                        ('Mg.Op.', _fmt_pct(res_fund.get('op_margin'))),
                    ], f"{G('ROE')} | {G('ROA')}")
                with cols_fund_kpi[2]:
                    kpi_card_fundamental('Solvencia / Flujo', '#e3b341', [
                        ('D/E', f"{_fmt_num(res_fund.get('debt_equity'))}x"),
                        ('Curr.Ratio', f"{_fmt_num(res_fund.get('curr_ratio'))}x"),
                        ('FCF', _fmt_big(res_fund.get('fcf'))),
                        ('Beta', _fmt_num(res_fund.get('beta'))),
                    ], f"{G('FCF')} | {G('Beta')}")

                st.markdown(f"""
                <div style='background:rgba(58,123,213,0.07);border:1px solid rgba(58,123,213,0.2);
                     border-radius:8px;padding:10px 16px;margin:10px 0;font-size:13px;color:#f5f7fa;line-height:1.8'>
                  <b style='color:#3a7bd5;font-size:13px'>BENCHMARK {sector_fund.upper()}</b><br>
                  {bench_b['descripcion']}<br>
                  <b style='color:#f5f7fa'>Métricas clave:</b> {' · '.join(bench_b.get('metricas_clave', []))}
                </div>
                """, unsafe_allow_html=True)

                ok_sigs_b  = [(t,m) for t,m in res_fund['senales'] if t=='OK']
                alt_sigs_b = [(t,m) for t,m in res_fund['senales'] if t=='ALT']
                col_sig1, col_sig2 = st.columns(2)
                with col_sig1:
                    st.markdown('<div style="font-size:11px;font-weight:700;color:#3fb950;margin-bottom:4px">✅ SEÑALES POSITIVAS</div>', unsafe_allow_html=True)
                    for _, msg in ok_sigs_b:
                        st.markdown(f'<div style="font-size:11px;color:#3fb950;padding:2px 0;border-bottom:1px solid #21262d">• {msg}</div>', unsafe_allow_html=True)
                with col_sig2:
                    st.markdown('<div style="font-size:11px;font-weight:700;color:#f85149;margin-bottom:4px">⚠️ ALERTAS</div>', unsafe_allow_html=True)
                    for _, msg in alt_sigs_b:
                        st.markdown(f'<div style="font-size:11px;color:#f85149;padding:2px 0;border-bottom:1px solid #21262d">• {msg}</div>', unsafe_allow_html=True)

                if res_fund['sector_senales']:
                    st.markdown('<div style="margin-top:12px;font-size:11px;font-weight:700;color:#3a7bd5;margin-bottom:4px">📐 COMPARATIVA VS BENCHMARK SECTORIAL</div>', unsafe_allow_html=True)
                    for tipo, msg in res_fund['sector_senales']:
                        col_vs_b = '#3fb950' if tipo == 'POS' else '#f85149'
                        ico_vs_b = '✔' if tipo == 'POS' else '✘'
                        st.markdown(f'<div style="font-size:11px;color:{col_vs_b};padding:3px 0;border-bottom:1px solid #21262d">{ico_vs_b} {msg}</div>', unsafe_allow_html=True)

    # ── TOP-DOWN CUANTITATIVO ────────────────────────────────────
    if 'tdc' in activos:
        st.markdown('---')
        st.markdown('### 📐 Top-Down Cuantitativo (Mediano/Largo Plazo)')

        with st.spinner('Calculando scores Top-Down Cuantitativo...'):
            tdc_mp = _tdc_analizar_ticker(ticker, HORIZONTES_TDC['MP'])
            tdc_lp = _tdc_analizar_ticker(ticker, HORIZONTES_TDC['LP'])

        if tdc_mp is None and tdc_lp is None:
            st.info('No hay historial suficiente para calcular el Top-Down Cuantitativo de este activo '
                    '(se necesitan al menos ~100 sesiones para Mediano Plazo y ~250 para Largo Plazo).')
        else:
            tab_tdc_mp, tab_tdc_lp = st.tabs(['📆 Mediano Plazo (3-6 meses)', '📆 Largo Plazo (1-2 años)'])
            for tab_obj, d_tdc, hz_key in [(tab_tdc_mp, tdc_mp, 'MP'), (tab_tdc_lp, tdc_lp, 'LP')]:
                with tab_obj:
                    if d_tdc is None:
                        st.info(f"Historial insuficiente para calcular {HORIZONTES_TDC[hz_key]['nombre'].lower()} "
                                f"(mínimo {HORIZONTES_TDC[hz_key]['min_dias_valor']} sesiones).")
                        continue
                    cfg_hz = HORIZONTES_TDC[hz_key]
                    lbl_sa_tdc, col_sa_tdc, _ = clasificar_score(d_tdc['sa'])
                    kpi_cards_4([
                        ('Score Acumulación', f"{d_tdc['sa']:.0f}/100", lbl_sa_tdc, col_sa_tdc),
                        ('Score Anticipación', f"{d_tdc['sn']:.0f}/100", 'Momentum', score_color_hex(d_tdc['sn'])),
                        ('Score Sentimiento', f"{d_tdc['ss']:.0f}/100", 'Percentil precio', score_color_hex(d_tdc['ss'])),
                        ('Score Final', f"{d_tdc['sf']:.0f}/100", 'Compuesto 45/35/20', score_color_hex(d_tdc['sf'])),
                    ])
                    c1t, c2t, c3t = st.columns(3)
                    with c1t: st.metric(f"Ret {cfg_hz['ret_label_1']}", f"{d_tdc['ret_1']:+.2f}%")
                    with c2t: st.metric(f"Ret {cfg_hz['ret_label_2']}", f"{d_tdc['ret_2']:+.2f}%")
                    with c3t: st.metric('RSI', f"{d_tdc['rsi']:.1f}")
                    st.markdown(f'<div style="margin:10px 0"><span class="signal-pill">{d_tdc["accion"]}</span></div>',
                                unsafe_allow_html=True)
                    _, col_lbl_tdc, emo_lbl_tdc = _tdc_clasificar(d_tdc['sa'])
                    st.markdown(f"""
                    <div class="interp-card">
                      <div class="interp-header">{emo_lbl_tdc} {ticker} · {cfg_hz['nombre']} · {col_lbl_tdc}</div>
                      {_tdc_texto_interpretacion(d_tdc['sa'], d_tdc['sn'], d_tdc['ss'])}
                    </div>
                    """, unsafe_allow_html=True)

    # ── ACCIONISTAS Y ESTADOS FINANCIEROS ─────────────────────────
    if 'estados' in activos:
        st.markdown('---')
        st.markdown('### 👥📑 Accionistas y Estados Financieros')
        render_analisis_profundo(ticker, key_suffix='buscador')


# ==============================================================
#  MÓDULO COMPARADOR DE ACTIVOS
# ==============================================================


def modulo_comparador():
    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #6CC24A;
         border-radius:14px; padding:28px 32px; margin-bottom:24px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">⚖️ Comparador de Activos</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Sumá entre 2 y 5 activos para comparar su rendimiento normalizado y sus scores cuantitativos lado a lado.
      </div>
    </div>
    """, unsafe_allow_html=True)

    c_add, c_btn = st.columns([4, 1])
    with c_add:
        nuevo = selector_ticker_autocomplete('comparador_add')
    with c_btn:
        st.markdown('<div style="height:6px"></div>', unsafe_allow_html=True)
        if st.button('➕ Agregar', use_container_width=True, key='comp_add_btn'):
            lista = st.session_state['comparador_tickers']
            if nuevo and nuevo not in lista and len(lista) < 5:
                lista.append(nuevo)
                st.session_state['comp_run_flag'] = False
                st.rerun()

    if st.session_state['comparador_tickers']:
        st.markdown('<div style="margin:10px 0 4px 0;font-size:11px;color:#6b7d9a">Activos seleccionados (clic para quitar):</div>', unsafe_allow_html=True)
        lista = st.session_state['comparador_tickers']
        cols_chip = st.columns(max(len(lista), 1))
        for i, tk in enumerate(lista):
            with cols_chip[i]:
                if st.button(f'✕ {tk}', key=f'comp_rm_{tk}', use_container_width=True):
                    st.session_state['comparador_tickers'].remove(tk)
                    st.session_state['comp_run_flag'] = False
                    st.rerun()

    tickers_cmp = st.session_state['comparador_tickers']
    if len(tickers_cmp) < 2:
        st.info('Agregá al menos 2 activos para comparar.')
        return

    if st.button('▶ Comparar', key='comp_run'):
        st.session_state['comp_run_flag'] = True

    if not st.session_state.get('comp_run_flag'):
        return

    def _proc_cmp(tk):
        df_tk = descargar_datos(tk, '2y')
        cl = get_close_series(df_tk) if df_tk is not None else None
        r_l = analizar_largo(tk, cl) if cl is not None and len(cl) >= 150 else None
        df_m = descargar_datos(tk, '1mo'); df_v = descargar_datos(tk, '3mo')
        r_c = None
        if df_m is not None and df_v is not None:
            cl_m = get_close_series(df_m); cl_v = get_close_series(df_v)
            if cl_m is not None and cl_v is not None and len(cl_v.dropna()) >= 15:
                atr = calcular_atr(df_m)
                sa, sn, ss = scores_corto(cl_v, cl_m, atr)
                r_c = dict(sa=sa, sn=sn, ss=ss, sf=sa*0.45+sn*0.35+ss*0.20)
        industria_tk = TICKER_INDUSTRY.get(tk, 'Sin Clasificar')
        r_f = analizar_fundamental(tk, industria_tk)
        return tk, cl, r_l, r_c, r_f

    with st.spinner('Descargando y calculando comparación...'):
        series, resultados_l, resultados_c, resultados_f = {}, {}, {}, {}
        sin_precio = []
        with ThreadPoolExecutor(max_workers=5) as ex:
            for tk, cl, r_l, r_c, r_f in ex.map(_proc_cmp, tickers_cmp):
                if cl is not None:
                    series[tk] = cl
                else:
                    sin_precio.append(tk)
                if r_l: resultados_l[tk] = r_l
                if r_c: resultados_c[tk] = r_c
                if r_f: resultados_f[tk] = r_f

    if not series:
        st.error('No se pudieron descargar datos para los activos seleccionados.')
        return

    if sin_precio:
        st.warning(f"⚠️ No se pudo descargar precio para: {', '.join(sin_precio)}. Probá tocar \"↺ Actualizar\" en unos minutos.")

        # ── Perfiles de cada empresa comparada ─────────────────────────────
    st.markdown('---')
    st.markdown('### 🏢 Perfiles de las empresas')
    tabs_perfil = st.tabs([f'🏢 {tk}' for tk in tickers_cmp])
    for tab_p, tk_p in zip(tabs_perfil, tickers_cmp):
        with tab_p:
            render_perfil_empresa(tk_p, key_suffix=f'comp_{tk_p}')

    st.plotly_chart(fig_comparador_precio(series), use_container_width=True, config=PLOTLY_CONFIG, key='comp_precio_fig')

    if resultados_l:
        filas = []
        for tk, r in resultados_l.items():
            filas.append({
                'Ticker': tk, 'Precio': fmt_precio(r['precio']), 'Sesgo': r['sesgo'],
                'Global': int(r['global_score']), 'Trend': int(r['trend_score']),
                'MR': int(r['mr_score']), 'Risk': int(r['risk_score']),
                'Ret Anual %': round(r['ret_anual'], 1), 'Vol %': round(r['vol_anual'], 1),
                'Sharpe': round(r['sharpe'], 2), 'Max DD %': round(r['max_dd'], 1),
                'RSI': round(r['rsi'], 1), 'Hurst': round(r['hurst'], 3),
                'Acum (corto)': resultados_c.get(tk, {}).get('sa'),
            })
        df_cmp = pd.DataFrame(filas)
        styled_cmp = _apply_score_style(df_cmp, ['Global', 'Trend', 'MR', 'Risk'])
        st.dataframe(styled_cmp, use_container_width=True, height=min(400, len(df_cmp)*45+60))

        col_radar, col_vacio = st.columns([2, 1])
        with col_radar:
            st.plotly_chart(fig_radar_comparador(resultados_l), use_container_width=True, config=PLOTLY_CONFIG, key='comp_radar_fig')

        ganador = max(resultados_l.items(), key=lambda x: x[1]['global_score'])
        st.markdown(f"""
        <div class="interp-card">
          <div class="interp-header">🏆 Mejor Global Score del grupo</div>
          {ganador[0]} lidera la comparación con un Global Score de {int(ganador[1]['global_score'])}/100 ({ganador[1]['sesgo']}).
        </div>
        """, unsafe_allow_html=True)
    else:
        st.info('No hay suficiente historial (2 años) para calcular el análisis cuantitativo de estos activos. Aun así, podés ver el gráfico de rendimiento comparado arriba.')

    # ── COMPARACIÓN FUNDAMENTAL ───────────────────────────────────────────
    st.markdown('---')
    st.markdown('### 📊 Comparación Fundamental — todos los datos')

    if resultados_f:
        # Explicación de cada métrica, organizada por categoría (siempre visible arriba de los datos)
        with st.expander('❓ ¿Qué significa cada métrica? (referencia rápida)', expanded=True):
            for categoria, metricas_cat in CATEGORIAS_FUNDAMENTAL:
                st.markdown(
                    f"<div style='margin-top:10px;font-size:12px;font-weight:700;color:#6CC24A'>{categoria}</div>",
                    unsafe_allow_html=True,
                )
                for label, _extractor, _direccion, glos_key in metricas_cat:
                    desc = GLOSARIO.get(glos_key, '') if glos_key else ''
                    if not desc:
                        continue
                    st.markdown(
                        f"<div style='margin:3px 0 3px 8px;font-size:11px'>"
                        f"<b style='color:#e6edf3'>{label}</b> — <span style='color:#8b949e'>{desc}</span></div>",
                        unsafe_allow_html=True,
                    )

        # Gráficos agrupados por categoría (pestañas para no amontonar todo en una sola imagen)
        tabs_cat = st.tabs([c for c, _ in CATEGORIAS_FUNDAMENTAL])
        for tab_obj, (categoria, metricas_cat) in zip(tabs_cat, CATEGORIAS_FUNDAMENTAL):
            with tab_obj:
                st.plotly_chart(
                    fig_categoria_fundamental(resultados_f, metricas_cat, categoria),
                    use_container_width=True, key=f'comp_fund_{categoria}',
                )

        # Tabla con TODOS los datos fundamentales disponibles
        filas_f = []
        for tk in tickers_cmp:
            e = resultados_f.get(tk)
            if not e: continue
            filas_f.append({
                'Ticker': tk,
                'Señal': e['senal_final'],
                'Rec. Analistas': e.get('recommendation') or 'N/D',
                'PER': e.get('per'),
                'P/B': e.get('pb'),
                'P/S': e.get('ps'),
                'PEG': e.get('peg'),
                'EV/EBITDA': e.get('ev_ebitda'),
                'ROE %': _pct100(e.get('roe')),
                'ROA %': _pct100(e.get('roa')),
                'Mg.Bruto %': _pct100(e.get('gross_margin')),
                'Mg.Op. %': _pct100(e.get('op_margin')),
                'Mg.Neto %': _pct100(e.get('profit_margin')),
                'Rev.Growth %': _pct100(e.get('revenue_growth')),
                'EPS Growth %': _pct100(e.get('eps_growth')),
                'Earnings Growth %': _pct100(e.get('earnings_growth')),
                'Alza YTD %': e.get('alza_ytd'),
                'Beta': e.get('beta'),
                'D/E': e.get('debt_equity'),
                'Current Ratio': e.get('curr_ratio'),
                'Div.Yield %': _pct100(e.get('div_yield')),
                'FCF': e.get('fcf'),
                'Operating CF': e.get('op_cf'),
                'Cash': e.get('cash'),
                'Market Cap': e.get('market_cap'),
                'Enterprise Value': e.get('ev'),
                'Precio': e.get('precio'),
                'Precio Objetivo': e.get('target_price'),
            })

        if filas_f:
            df_fund_cmp = pd.DataFrame(filas_f)

            columnas_directivas = [
                ('PER', 'menor'), ('P/B', 'menor'), ('P/S', 'menor'), ('PEG', 'menor'), ('EV/EBITDA', 'menor'),
                ('ROE %', 'mayor'), ('ROA %', 'mayor'), ('Mg.Bruto %', 'mayor'), ('Mg.Op. %', 'mayor'), ('Mg.Neto %', 'mayor'),
                ('Rev.Growth %', 'mayor'), ('EPS Growth %', 'mayor'), ('Earnings Growth %', 'mayor'), ('Alza YTD %', 'mayor'),
                ('Beta', 'menor'), ('D/E', 'menor'), ('Current Ratio', 'mayor'),
                ('Div.Yield %', 'mayor'), ('FCF', 'mayor'), ('Operating CF', 'mayor'), ('Cash', 'mayor'),
                ('Market Cap', None), ('Enterprise Value', None), ('Precio', None), ('Precio Objetivo', None),
            ]
            fmt_overrides_fund = {
                'FCF': (lambda v: _fmt_big(v)),
                'Operating CF': (lambda v: _fmt_big(v)),
                'Cash': (lambda v: _fmt_big(v)),
                'Market Cap': (lambda v: _fmt_big(v)),
                'Enterprise Value': (lambda v: _fmt_big(v)),
                'Precio': (lambda v: fmt_precio(v)),
                'Precio Objetivo': (lambda v: fmt_precio(v)),
            }

            def style_senal_cmp(val):
                c, bg = _senal_color(val)
                return f'color:{c};font-weight:700;background:{bg}'

            styled_fc = _tabla_fundamental_completa(df_fund_cmp, columnas_directivas, fmt_overrides=fmt_overrides_fund)
            _map_fc = 'map' if hasattr(df_fund_cmp.style, 'map') else 'applymap'
            styled_fc = styled_fc.pipe(lambda s: getattr(s, _map_fc)(style_senal_cmp, subset=['Señal']))
            st.caption('↔️ Desliza horizontalmente para ver todas las columnas (son muchas métricas).')
            st.dataframe(styled_fc, use_container_width=True, height=min(560, len(df_fund_cmp)*45+90))

            st.caption(
                '🟢 resaltado = mejor valor del grupo en esa métrica. '
                'PER · P/B · P/S · PEG · EV/EBITDA · Beta · D/E: el valor más bajo se considera mejor. '
                'ROE · ROA · márgenes · crecimiento · Current Ratio · Dividend Yield · FCF · Operating CF · Cash: el valor más alto se considera mejor. '
                'Market Cap, Enterprise Value, Precio y Precio Objetivo son solo informativos (no se resaltan).'
            )
        else:
            st.info('No se pudieron calcular ratios fundamentales para estos activos.')
    else:
        st.info('No hay datos fundamentales disponibles para estos activos (puede tratarse de cripto, forex o commodities sin estados financieros).')

    # ── ESTADOS FINANCIEROS COMPARADOS ─────────────────────────────────
    st.markdown('---')
    st.markdown('### 📑 Comparación de Estados Financieros')
    render_comparativo_estados(tickers_cmp, key_suffix='comparador')


# ==============================================================
#  MÓDULO OPTIMIZADOR DE CARTERA — Monte Carlo + informe comparativo
#  (Adaptado de script Colab/ipywidgets a Streamlit nativo)
# ==============================================================


TASA_LIBRE_RIESGO_OPT = 0.00


def _opt_drawdown(equity_arr):
    maximos = np.maximum.accumulate(equity_arr)
    return equity_arr / maximos - 1


def _opt_cagr_serie(ret):
    ret = ret.dropna()
    if len(ret) == 0: return np.nan
    equity = (1 + ret).cumprod()
    anios = len(ret) / 252
    return equity.iloc[-1] ** (1 / anios) - 1 if anios > 0 else np.nan


def _opt_metricas_completas(ret, ret_bench=None, rf=TASA_LIBRE_RIESGO_OPT):
    ret = ret.dropna()
    equity = (1 + ret).cumprod()
    anios = len(ret) / 252
    cagr = equity.iloc[-1] ** (1 / anios) - 1
    rent_acum = equity.iloc[-1] - 1
    vol = ret.std() * np.sqrt(252)
    sharpe = (cagr - rf) / vol if vol != 0 else np.nan
    downside = ret[ret < 0].std() * np.sqrt(252)
    sortino = (cagr - rf) / downside if downside != 0 else np.nan
    dd = pd.Series(_opt_drawdown(equity.values), index=equity.index)
    max_dd = dd.min()
    calmar = cagr / abs(max_dd) if max_dd != 0 else np.nan
    ulcer = np.sqrt(np.mean((dd[dd < 0] * 100) ** 2)) if (dd < 0).any() else 0.0

    maximos = equity.cummax()
    dias, max_dias = 0, 0
    eq_vals = equity.values; max_vals = maximos.values
    for i in range(len(eq_vals)):
        if eq_vals[i] < max_vals[i]:
            dias += 1; max_dias = max(max_dias, dias)
        else:
            dias = 0
    recuperacion = max_dias

    var95 = np.percentile(ret, 5)
    cvar95 = ret[ret <= var95].mean()

    meses = ret.resample('ME').apply(lambda x: (1 + x).prod() - 1)
    meses_pos = int((meses > 0).sum()); meses_neg = int((meses < 0).sum())
    mejor_mes = meses.max() if len(meses) else np.nan
    peor_mes = meses.min() if len(meses) else np.nan

    if ret_bench is not None:
        ret_bench = ret_bench.dropna()
        cov = np.cov(ret, ret_bench)[0, 1]
        var_b = np.var(ret_bench)
        beta = cov / var_b if var_b != 0 else np.nan
        cagr_b = _opt_cagr_serie(ret_bench)
        alpha = cagr - (rf + beta * (cagr_b - rf))
        track_err = (ret - ret_bench).std() * np.sqrt(252)
        info_ratio = (cagr - cagr_b) / track_err if track_err != 0 else np.nan
        corr = ret.corr(ret_bench)
        prob_sup = (ret > ret_bench).mean()
    else:
        beta, alpha, track_err, info_ratio = 1.0, 0.0, 0.0, np.nan
        corr, prob_sup = 1.0, np.nan

    return {
        'CAGR': cagr, 'Rentabilidad Acumulada': rent_acum, 'Volatilidad': vol,
        'Sharpe': sharpe, 'Sortino': sortino, 'Max Drawdown': max_dd, 'Calmar': calmar,
        'Ulcer Index': ulcer, 'Tiempo Recuperacion': recuperacion, 'Beta': beta,
        'Alpha': alpha, 'Tracking Error': track_err, 'Information Ratio': info_ratio,
        'VaR 95%': var95, 'CVaR 95%': cvar95, 'Meses Positivos': meses_pos,
        'Meses Negativos': meses_neg, 'Mejor Mes': mejor_mes, 'Peor Mes': peor_mes,
        'Correlacion Benchmark': corr, 'Prob Superar Benchmark': prob_sup,
        'Equity': equity, 'Drawdown': dd,
    }


def _opt_pct(x):
    return f'{x*100:.2f}%' if x is not None and not pd.isna(x) else '-'


def _opt_estrellas(v):
    if v is None or pd.isna(v): return ''
    if v >= 2: return '★★★★★'
    if v >= 1.5: return '★★★★'
    if v >= 1: return '★★★'
    if v >= 0.5: return '★★'
    return '★'


@st.cache_data(ttl=3600, show_spinner=False)
def _opt_descargar_precios(universo_tuple, fecha_inicio):
    try:
        import yfinance as yf
        universo = sorted(universo_tuple)
        data = yf.download(universo, start=fecha_inicio, auto_adjust=True, progress=False)
        if data is None or data.empty: return None
        if isinstance(data.columns, pd.MultiIndex):
            precios = data['Close'].copy()
        else:
            precios = data.copy()
            if len(universo) == 1 and 'Close' in precios.columns:
                precios = precios[['Close']].rename(columns={'Close': universo[0]})
        return precios.dropna()
    except Exception:
        return None


def _opt_simular_carteras(retornos, tickers, simulaciones, rf=TASA_LIBRE_RIESGO_OPT, seed=42):
    rng = np.random.default_rng(seed)
    n = len(tickers)
    pesos = rng.dirichlet(np.ones(n), size=simulaciones)            # (sims, n)
    ret_mat = retornos[tickers].values                              # (days, n)
    ret_cart = ret_mat @ pesos.T                                    # (days, sims)

    equity = np.cumprod(1 + ret_cart, axis=0)
    anios = ret_cart.shape[0] / 252
    cagr = equity[-1, :] ** (1 / anios) - 1
    vol = ret_cart.std(axis=0, ddof=1) * np.sqrt(252)
    sharpe = np.where(vol != 0, (cagr - rf) / vol, np.nan)

    neg = np.where(ret_cart < 0, ret_cart, np.nan)
    with np.errstate(invalid='ignore'):
        downside = np.nanstd(neg, axis=0) * np.sqrt(252)
    sortino = np.where(downside != 0, (cagr - rf) / downside, np.nan)

    running_max = np.maximum.accumulate(equity, axis=0)
    dd = equity / running_max - 1
    max_dd = dd.min(axis=0)
    calmar = np.where(max_dd != 0, cagr / np.abs(max_dd), np.nan)

    df = pd.DataFrame({
        'CAGR': cagr, 'Volatilidad': vol, 'Sharpe': sharpe, 'Sortino': sortino,
        'Max Drawdown': max_dd, 'Calmar': calmar,
    })
    for i, tk in enumerate(tickers):
        df[tk] = pesos[:, i]

    df['Score Global'] = (
        df['CAGR'].rank(pct=True) * 0.35 +
        df['Sharpe'].rank(pct=True) * 0.25 +
        df['Sortino'].rank(pct=True) * 0.20 +
        df['Calmar'].rank(pct=True) * 0.10 +
        (1 - df['Max Drawdown'].abs().rank(pct=True)) * 0.10
    )
    return df


def _opt_fig_equity(series_dict, capital_inicial, benchmark):
    fig = go.Figure()
    palette = [C_MONSTER, C_ACENT, '#bc8cff', C_YELL, C_LGRE]
    for i, (nombre, eq) in enumerate(series_dict.items()):
        valores = capital_inicial * eq
        dash = 'dash' if nombre == benchmark else 'solid'
        color = C_RED if nombre == benchmark else palette[i % len(palette)]
        fig.add_trace(go.Scatter(x=valores.index, y=valores, name=nombre,
            line=dict(color=color, width=2.2, dash=dash)))
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE,
        title=dict(text=f'Evolución de USD {capital_inicial:,.0f}', font=dict(color=C_TEXT, size=14)),
        xaxis=dict(gridcolor=C_GRID), yaxis=dict(gridcolor=C_GRID, title='Valor de la inversión'),
        height=460, hovermode='x unified', legend=dict(orientation='h', y=1.1),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    return fig


def _opt_fig_drawdown(dd_dict, benchmark):
    fig = go.Figure()
    palette = [C_MONSTER, C_ACENT, '#bc8cff', C_YELL, C_LGRE]
    for i, (nombre, dd) in enumerate(dd_dict.items()):
        dash = 'dash' if nombre == benchmark else 'solid'
        color = C_RED if nombre == benchmark else palette[i % len(palette)]
        fig.add_trace(go.Scatter(x=dd.index, y=dd*100, name=nombre, line=dict(color=color, width=1.6, dash=dash)))
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE,
        title=dict(text='Drawdown histórico comparado', font=dict(color=C_TEXT, size=14)),
        xaxis=dict(gridcolor=C_GRID), yaxis=dict(gridcolor=C_GRID, title='Caída desde máximo (%)'),
        height=380, hovermode='x unified', legend=dict(orientation='h', y=1.1),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    return fig


def _opt_fig_corr(corr):
    fig = go.Figure(data=go.Heatmap(
        z=corr.values, x=list(corr.columns), y=list(corr.index),
        colorscale='RdBu', zmin=-1, zmax=1, reversescale=True,
        text=np.round(corr.values, 2), texttemplate='%{text}',
        colorbar=dict(title='Corr'),
    ))
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE,
        title=dict(text='Correlación entre activos', font=dict(color=C_TEXT, size=14)),
        height=max(360, len(corr)*32), margin=dict(l=10, r=10, t=45, b=10),
    )
    return fig


def _opt_fig_frontera(df_sim, carteras_candidatas, vol_bench, cagr_bench, benchmark):
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_sim['Volatilidad'], y=df_sim['CAGR'], mode='markers',
        marker=dict(size=5, color=df_sim['Sharpe'], colorscale='Viridis',
                    colorbar=dict(title='Sharpe'), opacity=0.45),
        name='Simulaciones', hovertemplate='Vol: %{x:.2%}<br>CAGR: %{y:.2%}<extra></extra>',
    ))
    simbolos = ['star', 'diamond', 'cross', 'square', 'triangle-up']
    colores_c = [C_MONSTER, C_ACENT, '#bc8cff', C_YELL, C_LGRE]
    for (nombre, cart), simb, col in zip(carteras_candidatas.items(), simbolos, colores_c):
        fig.add_trace(go.Scatter(
            x=[cart['Volatilidad']], y=[cart['CAGR']], mode='markers',
            marker=dict(size=16, symbol=simb, color=col, line=dict(width=1.5, color='#0d1117')),
            name=nombre,
        ))
    fig.add_trace(go.Scatter(
        x=[vol_bench], y=[cagr_bench], mode='markers',
        marker=dict(size=16, symbol='circle', color=C_RED, line=dict(width=1.5, color='#0d1117')),
        name=benchmark,
    ))
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE,
        title=dict(text='Frontera eficiente simulada', font=dict(color=C_TEXT, size=14)),
        xaxis=dict(title='Volatilidad anual', tickformat='.0%', gridcolor=C_GRID),
        yaxis=dict(title='CAGR', tickformat='.0%', gridcolor=C_GRID),
        height=520, legend=dict(orientation='h', y=1.12), margin=dict(l=10, r=10, t=50, b=10),
    )
    return fig


def modulo_optimizador():
    st.markdown("""
    <div style="background:linear-gradient(135deg,#150d20 0%,#1c0a30 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #bc8cff;
         border-radius:14px; padding:28px 32px; margin-bottom:24px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">🧮 Optimizador de Cartera</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Simulación Monte Carlo sobre los activos elegidos: encuentra 5 carteras candidatas
        (más rentable, mejor Sharpe, mejor Sortino, menor drawdown y recomendada por Score Global)
        y las compara entre sí y contra un benchmark, con informe descargable en Excel.
      </div>
    </div>
    """, unsafe_allow_html=True)

    if 'opt_tickers' not in st.session_state:
        st.session_state['opt_tickers'] = ['VIST', 'PFE', 'MU', 'SPXL', 'TQQQ', 'GDX', 'SLV', 'XLE', 'GGAL']

    c_add, c_btn = st.columns([4, 1])
    with c_add:
        nuevo_opt = selector_ticker_autocomplete('opt_add')
    with c_btn:
        st.markdown('<div style="height:6px"></div>', unsafe_allow_html=True)
        if st.button('➕ Agregar', use_container_width=True, key='opt_add_btn'):
            if nuevo_opt and nuevo_opt not in st.session_state['opt_tickers'] and len(st.session_state['opt_tickers']) < 15:
                st.session_state['opt_tickers'].append(nuevo_opt)
                st.rerun()

    if st.session_state['opt_tickers']:
        st.markdown('<div style="margin:10px 0 4px 0;font-size:11px;color:#6b7d9a">Activos en la cartera (clic para quitar):</div>', unsafe_allow_html=True)
        lista_opt = st.session_state['opt_tickers']
        n_chip_cols = min(max(len(lista_opt), 1), 8)
        cols_chip = st.columns(n_chip_cols)
        for i, tk in enumerate(lista_opt):
            with cols_chip[i % n_chip_cols]:
                if st.button(f'✕ {tk}', key=f'opt_rm_{tk}_{i}', use_container_width=True):
                    st.session_state['opt_tickers'].remove(tk)
                    st.rerun()

    if len(st.session_state['opt_tickers']) < 2:
        st.info('Agregá al menos 2 activos para poder optimizar la cartera.')
        return

    st.markdown('---')
    cb1, cb2, cb3 = st.columns(3)
    with cb1:
        bench_opciones = {
            'S&P 500 (SPY)': 'SPY', 'Nasdaq 100 (QQQ)': 'QQQ', 'Dow Jones (DIA)': 'DIA',
            'Russell 2000 (IWM)': 'IWM', 'Mercado total EE.UU. (VTI)': 'VTI',
            'Innovación / growth (ARKK)': 'ARKK', 'Mercados emergentes (EEM)': 'EEM',
        }
        bench_label = st.selectbox('Benchmark', list(bench_opciones.keys()), key='opt_bench_sel')
        benchmark_opt = bench_opciones[bench_label]
    with cb2:
        capital_opt = st.number_input('Capital inicial (USD)', min_value=100.0, value=10000.0, step=500.0, key='opt_capital')
    with cb3:
        sim_opt = st.slider('Simulaciones', 1000, 30000, 10000, 1000, key='opt_sims')

    fecha_inicio_opt = st.text_input('Fecha de inicio del histórico (AAAA-MM-DD)', value='2019-01-01', key='opt_fecha')

    correr = st.button('▶ Ejecutar análisis', key='opt_run', type='primary')

    if not correr and not st.session_state.get('opt_resultado_ok'):
        return
    if correr:
        st.session_state['opt_resultado_ok'] = True

    tickers_opt_base = sorted(set(st.session_state['opt_tickers']))
    firma_opt = (tuple(tickers_opt_base), benchmark_opt, sim_opt, fecha_inicio_opt)

    necesita_recalcular = (
        correr
        or st.session_state.get('opt_firma') != firma_opt
        or 'opt_cache' not in st.session_state
    )

    if necesita_recalcular:
        tickers_opt = tickers_opt_base
        if benchmark_opt in tickers_opt:
            st.warning(f"'{benchmark_opt}' está tanto entre los activos como en el benchmark elegido. Se lo deja en ambos lados, tenelo en cuenta al leer los resultados.")

        with st.spinner('Descargando precios históricos...'):
            universo_opt = tuple(sorted(set(tickers_opt) | {benchmark_opt}))
            precios_opt = _opt_descargar_precios(universo_opt, fecha_inicio_opt)

        if precios_opt is None or precios_opt.empty:
            st.error('No se pudieron descargar precios. Revisá que los tickers y el benchmark sean válidos en Yahoo Finance.')
            return

        faltantes = [t for t in universo_opt if t not in precios_opt.columns]
        if faltantes:
            st.warning(f"No se encontraron datos para: {', '.join(faltantes)}. Se excluyen del análisis.")
            tickers_opt = [t for t in tickers_opt if t not in faltantes]
            if benchmark_opt in faltantes or len(tickers_opt) < 2:
                st.error('No hay suficientes activos válidos para continuar.')
                return

        retornos_opt = precios_opt[tickers_opt].pct_change().dropna()
        ret_bench_opt = precios_opt[benchmark_opt].pct_change().dropna()
        fechas_comunes = retornos_opt.index.intersection(ret_bench_opt.index)
        retornos_opt = retornos_opt.loc[fechas_comunes]
        ret_bench_opt = ret_bench_opt.loc[fechas_comunes]

        if len(retornos_opt) < 100:
            st.error('Muy pocas ruedas de historial común entre los activos y el benchmark. Probá una fecha de inicio más reciente o cambiá algún ticker.')
            return

        with st.spinner(f'Simulando {sim_opt:,} carteras...'):
            df_sim = _opt_simular_carteras(retornos_opt, tickers_opt, sim_opt)

        candidatas_idx = {
            'Más Rentable': df_sim['CAGR'].idxmax(),
            'Mejor Sharpe': df_sim['Sharpe'].idxmax(),
            'Mejor Sortino': df_sim['Sortino'].idxmax(),
            'Menor Drawdown': df_sim['Max Drawdown'].idxmax(),  # el menos negativo
            'Recomendada (Score Global)': df_sim['Score Global'].idxmax(),
        }
        carteras_candidatas = {nombre: df_sim.loc[idx] for nombre, idx in candidatas_idx.items()}

        series_ret, metricas_cart = {}, {}
        for nombre, cart in carteras_candidatas.items():
            pesos_arr = cart[tickers_opt].values.astype(float)
            ret_serie = retornos_opt[tickers_opt] @ pesos_arr
            series_ret[nombre] = ret_serie
            metricas_cart[nombre] = _opt_metricas_completas(ret_serie, ret_bench_opt)
        series_ret[benchmark_opt] = ret_bench_opt
        metricas_cart[benchmark_opt] = _opt_metricas_completas(ret_bench_opt, None)
        nombres_col = list(carteras_candidatas.keys()) + [benchmark_opt]

        # Guardamos todo lo pesado en session_state para no recalcular
        # en cada rerun que dispara la tabla de "Mi Cartera Actual"
        # (por ejemplo, al escribir un monto en una celda).
        st.session_state['opt_firma'] = firma_opt
        st.session_state['opt_cache'] = dict(
            tickers_opt=tickers_opt, benchmark_opt=benchmark_opt,
            retornos_opt=retornos_opt, ret_bench_opt=ret_bench_opt,
            df_sim=df_sim, carteras_candidatas=carteras_candidatas,
            series_ret=series_ret, metricas_cart=metricas_cart,
            nombres_col=nombres_col,
        )
    else:
        cache = st.session_state['opt_cache']
        tickers_opt = cache['tickers_opt']
        retornos_opt = cache['retornos_opt']
        ret_bench_opt = cache['ret_bench_opt']
        df_sim = cache['df_sim']
        carteras_candidatas = cache['carteras_candidatas']
        series_ret = cache['series_ret']
        metricas_cart = cache['metricas_cart']
        nombres_col = cache['nombres_col']

    st.caption(f"📅 Período: {retornos_opt.index[0].date()} → {retornos_opt.index[-1].date()} · {len(retornos_opt)} ruedas")

    st.markdown('### 🏆 Carteras candidatas')
    for nombre, cart in carteras_candidatas.items():
        m = metricas_cart[nombre]
        with st.expander(
            f"{nombre} — CAGR {_opt_pct(m['CAGR'])} · Sharpe {m['Sharpe']:.2f} {_opt_estrellas(m['Sharpe'])}",
            expanded=(nombre == 'Recomendada (Score Global)')
        ):
            kpi_cards_4([
                ('CAGR', _opt_pct(m['CAGR']), 'Retorno anualizado', C_MONSTER),
                ('Sharpe', f"{m['Sharpe']:.2f}", _opt_estrellas(m['Sharpe']), score_color_hex(min(100, max(0, m['Sharpe']*33)))),
                ('Volatilidad', _opt_pct(m['Volatilidad']), 'Anualizada', C_YELL),
                ('Max Drawdown', _opt_pct(m['Max Drawdown']), f"Sortino {m['Sortino']:.2f}", C_RED),
            ])
            pesos_orden = cart[tickers_opt].sort_values(ascending=False)
            txt_pesos = ' · '.join(f"{tk}: {p*100:.1f}%" for tk, p in pesos_orden.items() if p > 0.005)
            st.markdown(f"<div style='font-size:12px;color:#b0bcd0'>{txt_pesos}</div>", unsafe_allow_html=True)

    # ── MI CARTERA ACTUAL: comparar y rebalancear ──────────────────────
    st.markdown('---')
    st.markdown('### 💼 Mi Cartera Actual — Comparar y Rebalancear')
    st.caption('Cargá cuánto tenés invertido hoy en cada activo (de los que están en "Activos en la cartera" arriba) y compará contra las carteras candidatas para ver qué comprar o vender.')

    if 'reb_montos' not in st.session_state or set(st.session_state['reb_montos'].get('Ticker', [])) != set(tickers_opt):
        st.session_state['reb_montos'] = pd.DataFrame({
            'Ticker': tickers_opt,
            'Monto actual (USD)': [0.0] * len(tickers_opt),
        })

    df_reb_input = st.data_editor(
        st.session_state['reb_montos'],
        key='reb_editor',
        use_container_width=True,
        hide_index=True,
        column_config={
            'Ticker': st.column_config.TextColumn(disabled=True),
            'Monto actual (USD)': st.column_config.NumberColumn(min_value=0.0, step=50.0, format='%.2f'),
        },
    )
    st.session_state['reb_montos'] = df_reb_input

    cash_actual = st.number_input(
        'Efectivo sin invertir (USD, opcional)', min_value=0.0, value=0.0, step=50.0, key='reb_cash'
    )

    cartera_comparar = st.selectbox(
        'Comparar contra', list(carteras_candidatas.keys()),
        index=list(carteras_candidatas.keys()).index('Recomendada (Score Global)'),
        key='reb_cartera_sel',
    )

    total_actual = float(df_reb_input['Monto actual (USD)'].sum()) + cash_actual

    if st.button('▶ Comparar y calcular rebalanceo', key='reb_run'):
        st.session_state['reb_run_flag'] = True

    if st.session_state.get('reb_run_flag'):
        if total_actual <= 0:
            st.warning('Cargá al menos un monto mayor a 0 en algún activo para poder comparar.')
        else:
            pesos_actuales = {}
            for _, fila in df_reb_input.iterrows():
                pesos_actuales[fila['Ticker']] = float(fila['Monto actual (USD)']) / total_actual

            pesos_objetivo = carteras_candidatas[cartera_comparar][tickers_opt].to_dict()

            filas_reb = []
            for tk in tickers_opt:
                p_act = pesos_actuales.get(tk, 0.0)
                p_obj = pesos_objetivo.get(tk, 0.0)
                diff = p_obj - p_act
                monto_operar = diff * total_actual
                if abs(diff) < 0.005:
                    accion = '⏸️ Mantener'
                elif diff > 0:
                    accion = '🟢 Comprar'
                else:
                    accion = '🔴 Vender'
                filas_reb.append({
                    'Ticker': tk,
                    'Peso Actual %': round(p_act * 100, 2),
                    'Peso Objetivo %': round(p_obj * 100, 2),
                    'Diferencia %': round(diff * 100, 2),
                    'Acción': accion,
                    'Monto a operar (USD)': round(monto_operar, 2),
                })
            if cash_actual > 0:
                filas_reb.append({
                    'Ticker': 'CASH',
                    'Peso Actual %': round(cash_actual / total_actual * 100, 2),
                    'Peso Objetivo %': 0.0,
                    'Diferencia %': round(-cash_actual / total_actual * 100, 2),
                    'Acción': '🔴 Invertir',
                    'Monto a operar (USD)': round(-cash_actual, 2),
                })

            df_reb = pd.DataFrame(filas_reb).sort_values(
                'Monto a operar (USD)', key=lambda s: s.abs(), ascending=False
            )

            def _color_accion_reb(val):
                if 'Comprar' in val or 'Invertir' in val: return 'color:#3fb950;font-weight:700'
                if 'Vender' in val: return 'color:#f85149;font-weight:700'
                return 'color:#8b949e'

            _map_reb = 'map' if hasattr(df_reb.style, 'map') else 'applymap'
            styled_reb = (df_reb.style
                .pipe(lambda s: getattr(s, _map_reb)(_color_accion_reb, subset=['Acción']))
                .format({'Peso Actual %': '{:.2f}%', 'Peso Objetivo %': '{:.2f}%',
                          'Diferencia %': '{:+.2f}%', 'Monto a operar (USD)': '{:+,.2f}'})
                .set_properties(**{'background-color': '#0d1117', 'color': '#e6edf3', 'border': '1px solid #21262d'})
                .set_table_styles([
                    {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', '#e6edf3'),
                        ('font-weight', '700'), ('text-align', 'center'),
                        ('border-bottom', '2px solid #bc8cff'), ('font-size', '11px')]},
                    {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]},
                ]))
            st.dataframe(styled_reb, use_container_width=True, height=min(500, len(df_reb) * 38 + 45))

            fig_reb = go.Figure()
            fig_reb.add_trace(go.Bar(x=df_reb['Ticker'], y=df_reb['Peso Actual %'], name='Actual', marker_color=C_ACENT))
            fig_reb.add_trace(go.Bar(x=df_reb['Ticker'], y=df_reb['Peso Objetivo %'], name=cartera_comparar, marker_color=C_MONSTER))
            fig_reb.update_layout(
                **PLOTLY_LAYOUT_BASE, barmode='group',
                title=dict(text='Peso actual vs. objetivo por activo', font=dict(color=C_TEXT, size=13)),
                xaxis=dict(gridcolor=C_GRID, tickangle=-45), yaxis=dict(gridcolor=C_GRID, title='% de cartera'),
                height=380, legend=dict(orientation='h', y=1.1), margin=dict(l=10, r=10, t=45, b=80),
            )
            st.plotly_chart(fig_reb, use_container_width=True, config=PLOTLY_CONFIG, key='reb_fig_pesos')

            pesos_arr_actual = np.array([pesos_actuales.get(tk, 0.0) for tk in tickers_opt])
            if pesos_arr_actual.sum() > 0:
                ret_actual = retornos_opt[tickers_opt] @ pesos_arr_actual
                m_actual = _opt_metricas_completas(ret_actual, ret_bench_opt)
                m_obj = metricas_cart[cartera_comparar]

                st.markdown('#### 📐 Tu cartera actual vs. la recomendada')
                kc1, kc2, kc3, kc4 = st.columns(4)
                with kc1:
                    st.metric('CAGR actual', _opt_pct(m_actual['CAGR']),
                              f"{_opt_pct(m_obj['CAGR'] - m_actual['CAGR'])} vs objetivo")
                with kc2:
                    st.metric('Sharpe actual', f"{m_actual['Sharpe']:.2f}",
                              f"{m_obj['Sharpe'] - m_actual['Sharpe']:+.2f} vs objetivo")
                with kc3:
                    st.metric('Volatilidad actual', _opt_pct(m_actual['Volatilidad']),
                              f"{_opt_pct(m_obj['Volatilidad'] - m_actual['Volatilidad'])} vs objetivo")
                with kc4:
                    st.metric('Max Drawdown actual', _opt_pct(m_actual['Max Drawdown']),
                              f"{_opt_pct(m_obj['Max Drawdown'] - m_actual['Max Drawdown'])} vs objetivo")

                if m_obj['Sharpe'] > m_actual['Sharpe'] + 0.05:
                    veredicto_reb = (f"La cartera **{cartera_comparar}** mejora tu Sharpe actual — "
                                      "el rebalanceo sugerido tiene sentido según los datos históricos.")
                elif m_obj['Sharpe'] < m_actual['Sharpe'] - 0.05:
                    veredicto_reb = ("Tu cartera actual ya tiene mejor Sharpe histórico que la sugerida — "
                                      "el rebalanceo no aportaría demasiado según estos datos.")
                else:
                    veredicto_reb = "Tu cartera actual y la recomendada tienen un perfil riesgo-retorno histórico similar."
                st.markdown(f"""
                <div class="interp-card">
                  <div class="interp-header">🧭 Lectura del rebalanceo</div>
                  {veredicto_reb}<br>
                  <span style="color:#6b7d9a;font-size:11px">Basado en el mismo período histórico usado en la simulación — no es asesoramiento financiero.</span>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.info('No se pudo calcular el rendimiento histórico de tu cartera actual (sin pesos válidos).')

    st.markdown('---')
    st.markdown(f'### 📋 Tabla comparativa vs {benchmark_opt}')

    filas_m = ['CAGR','Rentabilidad Acumulada','Volatilidad','Sharpe','Sortino','Calmar','Max Drawdown',
               'Ulcer Index','Beta','Alpha','Tracking Error','Information Ratio','VaR 95%','CVaR 95%',
               'Meses Positivos','Meses Negativos','Mejor Mes','Peor Mes','Tiempo Recuperacion',
               'Correlacion Benchmark','Prob Superar Benchmark']
    pct_fields = {'CAGR','Rentabilidad Acumulada','Volatilidad','Max Drawdown','Alpha','Tracking Error',
                  'VaR 95%','CVaR 95%','Mejor Mes','Peor Mes','Prob Superar Benchmark'}
    tabla_cmp = {}
    for nombre in nombres_col:
        m = metricas_cart[nombre]
        col_vals = []
        for clave in filas_m:
            v = m[clave]
            if clave in {'Meses Positivos','Meses Negativos','Tiempo Recuperacion'}:
                col_vals.append(f'{v}')
            elif clave in pct_fields:
                col_vals.append(_opt_pct(v))
            else:
                col_vals.append(f'{v:.2f}' if v is not None and not pd.isna(v) else '-')
        tabla_cmp[nombre] = col_vals
    df_cmp_opt = pd.DataFrame(tabla_cmp, index=filas_m)
    st.dataframe(df_cmp_opt, use_container_width=True, height=min(700, len(filas_m)*35+45))

    st.markdown('### 📅 Rentabilidad por año')
    rent_anual = pd.DataFrame({n: s.resample('YE').apply(lambda x: (1+x).prod()-1) for n, s in series_ret.items()})
    rent_anual.index = rent_anual.index.year
    st.dataframe(rent_anual.style.format('{:.2%}'), use_container_width=True)

    cap_final = {n: capital_opt * metricas_cart[n]['Equity'].iloc[-1] for n in nombres_col}
    st.markdown('### 💵 Capital final simulado')
    df_cap = pd.DataFrame({'Cartera': list(cap_final.keys()), 'Capital Final': list(cap_final.values())}).sort_values('Capital Final', ascending=False)
    df_cap['Capital Final'] = df_cap['Capital Final'].apply(lambda v: f'USD {v:,.2f}')
    st.dataframe(df_cap, use_container_width=True, hide_index=True)

    st.markdown('---')
    tabg1, tabg2, tabg3, tabg4 = st.tabs(['📈 Evolución capital', '📉 Drawdown', '🔥 Correlación', '🗺️ Frontera eficiente'])
    with tabg1:
        eq_dict = {n: metricas_cart[n]['Equity'] for n in nombres_col}
        st.plotly_chart(_opt_fig_equity(eq_dict, capital_opt, benchmark_opt), use_container_width=True, config=PLOTLY_CONFIG, key='opt_equity_fig')
    with tabg2:
        dd_dict = {n: metricas_cart[n]['Drawdown'] for n in nombres_col}
        st.plotly_chart(_opt_fig_drawdown(dd_dict, benchmark_opt), use_container_width=True, config=PLOTLY_CONFIG, key='opt_dd_fig')
    with tabg3:
        corr_opt = retornos_opt[tickers_opt].corr()
        st.plotly_chart(_opt_fig_corr(corr_opt), use_container_width=True, config=PLOTLY_CONFIG, key='opt_corr_fig')
    with tabg4:
        vol_b = ret_bench_opt.std() * np.sqrt(252)
        cagr_b = _opt_cagr_serie(ret_bench_opt)
        st.plotly_chart(_opt_fig_frontera(df_sim, carteras_candidatas, vol_b, cagr_b, benchmark_opt), use_container_width=True, config=PLOTLY_CONFIG, key='opt_frontera_fig')

    st.markdown('---')
    mejor_nombre_opt = max((n for n in nombres_col if n != benchmark_opt), key=lambda n: metricas_cart[n]['Sharpe'])
    m_mejor, m_bench = metricas_cart[mejor_nombre_opt], metricas_cart[benchmark_opt]
    if m_mejor['CAGR'] > m_bench['CAGR'] and m_mejor['Sharpe'] > m_bench['Sharpe']:
        veredicto = f"superó a {benchmark_opt} tanto en rentabilidad como en eficiencia riesgo-retorno."
    elif m_mejor['CAGR'] > m_bench['CAGR']:
        veredicto = f"superó a {benchmark_opt} en rentabilidad, aunque con más riesgo."
    else:
        veredicto = f"no superó claramente a {benchmark_opt}. Conviene revisar los activos elegidos."
    st.markdown(f"""
    <div class="interp-card">
      <div class="interp-header">🏁 Veredicto — {mejor_nombre_opt}</div>
      De las 5 carteras candidatas, la de mejor Sharpe es <b>{mejor_nombre_opt}</b> y {veredicto}<br>
      <span style="color:#6b7d9a;font-size:11px">Basado en datos históricos y simulación — no garantiza resultados futuros, no es asesoramiento financiero.</span>
    </div>
    """, unsafe_allow_html=True)



# ==============================================================
#  MÓDULO SCANNER DE PARES (MEAN REVERSION)
#  Adaptado del script standalone: mismo motor (ratio + Z-Score
#  + bandas), ahora con Plotly, caché y filtros interactivos.
# ==============================================================

PARES_SECTORES = {
    # ============================================================
    #  GRUPOS ORIGINALES (sin cambios)
    # ============================================================
    "Metales Preciosos": {
        "benchmark": "GLD",
        "empresas": ["B", "AEM", "KGC", "CDE", "NG", "HL", "HMY", "PAAS"],
        "tickers": {
            "GLD": "GLD", "SLV": "SLV", "GDX": "GDX",
            "B": "GOLD", "AEM": "AEM", "KGC": "KGC", "CDE": "CDE",
            "NG": "NG", "HL": "HL", "HMY": "HMY", "PAAS": "PAAS",
        },
    },
    "Tecnología": {
        "benchmark": "XLK",
        "empresas": ["AAPL", "MSFT", "GOOGL", "META", "NVDA", "ORCL", "CRM", "ADBE", "AMD"],
        "tickers": {
            "XLK": "XLK", "AAPL": "AAPL", "MSFT": "MSFT", "GOOGL": "GOOGL",
            "META": "META", "NVDA": "NVDA", "ORCL": "ORCL", "CRM": "CRM",
            "ADBE": "ADBE", "AMD": "AMD",
        },
    },
    "Semiconductores": {
        "benchmark": "SOXX",
        "empresas": ["NVDA", "AMD", "INTC", "TSM", "QCOM", "AVGO", "MU", "TXN", "ASML"],
        "tickers": {
            "SOXX": "SOXX", "NVDA": "NVDA", "AMD": "AMD", "INTC": "INTC",
            "TSM": "TSM", "QCOM": "QCOM", "AVGO": "AVGO", "MU": "MU",
            "TXN": "TXN", "ASML": "ASML",
        },
    },
    "Financieras": {
        "benchmark": "XLF",
        "empresas": ["JPM", "BAC", "WFC", "C", "GS", "MS", "USB", "PNC", "TFC"],
        "tickers": {
            "XLF": "XLF", "JPM": "JPM", "BAC": "BAC", "WFC": "WFC", "C": "C",
            "GS": "GS", "MS": "MS", "USB": "USB", "PNC": "PNC", "TFC": "TFC",
        },
    },
    "Energía": {
        "benchmark": "XLE",
        "empresas": ["XOM", "CVX", "COP", "SLB", "EOG", "PSX", "MPC", "OXY", "HAL"],
        "tickers": {
            "XLE": "XLE", "XOM": "XOM", "CVX": "CVX", "COP": "COP", "SLB": "SLB",
            "EOG": "EOG", "PSX": "PSX", "MPC": "MPC", "OXY": "OXY", "HAL": "HAL",
        },
    },
    "Salud": {
        "benchmark": "XLV",
        "empresas": ["JNJ", "PFE", "MRK", "ABBV", "LLY", "UNH", "BMY", "GILD", "AMGN"],
        "tickers": {
            "XLV": "XLV", "JNJ": "JNJ", "PFE": "PFE", "MRK": "MRK", "ABBV": "ABBV",
            "LLY": "LLY", "UNH": "UNH", "BMY": "BMY", "GILD": "GILD", "AMGN": "AMGN",
        },
    },
    "Consumo Discrecional": {
        "benchmark": "XLY",
        "empresas": ["AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "LOW", "TJX", "BKNG"],
        "tickers": {
            "XLY": "XLY", "AMZN": "AMZN", "TSLA": "TSLA", "HD": "HD", "MCD": "MCD",
            "NKE": "NKE", "SBUX": "SBUX", "LOW": "LOW", "TJX": "TJX", "BKNG": "BKNG",
        },
    },
    "Consumo Básico": {
        "benchmark": "XLP",
        "empresas": ["PG", "KO", "PEP", "WMT", "COST", "PM", "MO", "CL", "KMB"],
        "tickers": {
            "XLP": "XLP", "PG": "PG", "KO": "KO", "PEP": "PEP", "WMT": "WMT",
            "COST": "COST", "PM": "PM", "MO": "MO", "CL": "CL", "KMB": "KMB",
        },
    },
    "Industriales": {
        "benchmark": "XLI",
        "empresas": ["BA", "CAT", "GE", "HON", "UPS", "RTX", "LMT", "DE", "MMM"],
        "tickers": {
            "XLI": "XLI", "BA": "BA", "CAT": "CAT", "GE": "GE", "HON": "HON",
            "UPS": "UPS", "RTX": "RTX", "LMT": "LMT", "DE": "DE", "MMM": "MMM",
        },
    },
    "Utilities": {
        "benchmark": "XLU",
        "empresas": ["NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE", "XEL", "ED"],
        "tickers": {
            "XLU": "XLU", "NEE": "NEE", "DUK": "DUK", "SO": "SO", "D": "D",
            "AEP": "AEP", "EXC": "EXC", "SRE": "SRE", "XEL": "XEL", "ED": "ED",
        },
    },
    "Real Estate": {
        "benchmark": "XLRE",
        "empresas": ["AMT", "PLD", "CCI", "EQIX", "PSA", "O", "SPG", "DLR", "WELL"],
        "tickers": {
            "XLRE": "XLRE", "AMT": "AMT", "PLD": "PLD", "CCI": "CCI", "EQIX": "EQIX",
            "PSA": "PSA", "O": "O", "SPG": "SPG", "DLR": "DLR", "WELL": "WELL",
        },
    },
    "Comunicaciones": {
        "benchmark": "XLC",
        "empresas": ["GOOGL", "META", "NFLX", "DIS", "CMCSA", "T", "VZ", "TMUS", "EA"],
        "tickers": {
            "XLC": "XLC", "GOOGL": "GOOGL", "META": "META", "NFLX": "NFLX",
            "DIS": "DIS", "CMCSA": "CMCSA", "T": "T", "VZ": "VZ", "TMUS": "TMUS", "EA": "EA",
        },
    },
    "Materiales": {
        "benchmark": "XLB",
        "empresas": ["LIN", "APD", "SHW", "ECL", "FCX", "NEM", "DOW", "DD", "PPG"],
        "tickers": {
            "XLB": "XLB", "LIN": "LIN", "APD": "APD", "SHW": "SHW", "ECL": "ECL",
            "FCX": "FCX", "NEM": "NEM", "DOW": "DOW", "DD": "DD", "PPG": "PPG",
        },
    },
    "Argentina": {
        "benchmark": "ARGT",
        "empresas": ["GGAL", "YPF", "PAM", "BMA", "CRESY", "IRS", "LOMA", "EDN", "SUPV", "CEPU", "TGS"],
        "tickers": {
            "ARGT": "ARGT", "GGAL": "GGAL", "YPF": "YPF", "PAM": "PAM", "BMA": "BMA",
            "CRESY": "CRESY", "IRS": "IRSA", "LOMA": "LOMA", "EDN": "EDN",
            "SUPV": "SUPV", "CEPU": "CEPU", "TGS": "TGS",
        },
    },
    "Brasil": {
        "benchmark": "EWZ",
        "empresas": ["VALE", "PBR", "ITUB", "BBD", "ABEV", "SBS", "UGP", "BSBR", "ERJ", "GGB", "CIG", "VIV"],
        "tickers": {
            "EWZ": "EWZ", "VALE": "VALE", "PBR": "PBR", "ITUB": "ITUB", "BBD": "BBD",
            "ABEV": "ABEV", "SBS": "SBS", "UGP": "UGP", "BSBR": "BSBR", "ERJ": "ERJ",
            "GGB": "GGB", "CIG": "CIG", "VIV": "VIV",
        },
    },
    "Criptomonedas": {
        "benchmark": "BTC",
        "empresas": ["ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "DOT", "LINK", "LTC",
                     "ATOM", "ETC", "XLM", "FIL", "ICP", "HBAR", "NEAR", "ARB"],
        "tickers": {
            "BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD", "BNB": "BNB-USD",
            "XRP": "XRP-USD", "ADA": "ADA-USD", "DOGE": "DOGE-USD", "AVAX": "AVAX-USD",
            "DOT": "DOT-USD", "LINK": "LINK-USD", "LTC": "LTC-USD",
            "ATOM": "ATOM-USD", "ETC": "ETC-USD", "XLM": "XLM-USD", "FIL": "FIL-USD",
            "ICP": "ICP-USD", "HBAR": "HBAR-USD", "NEAR": "NEAR-USD", "ARB": "ARB-USD",
        },
    },

    # ============================================================
    #  GRUPOS NUEVOS — sub-sectores tecnológicos
    # ============================================================
    "Cloud/AI": {
        "benchmark": "SKYY",
        "empresas": ["PLTR", "SNOW", "DDOG", "NET", "MDB", "ESTC", "CFLT", "DOCN", "APP"],
        "tickers": {
            "SKYY": "SKYY", "PLTR": "PLTR", "SNOW": "SNOW", "DDOG": "DDOG", "NET": "NET",
            "MDB": "MDB", "ESTC": "ESTC", "CFLT": "CFLT", "DOCN": "DOCN", "APP": "APP",
        },
    },
    "Software": {
        "benchmark": "IGV",
        "empresas": ["ORCL", "CRM", "ADBE", "NOW", "INTU", "WDAY", "SNOW", "PLTR", "TEAM"],
        "tickers": {
            "IGV": "IGV", "ORCL": "ORCL", "CRM": "CRM", "ADBE": "ADBE", "NOW": "NOW",
            "INTU": "INTU", "WDAY": "WDAY", "SNOW": "SNOW", "PLTR": "PLTR", "TEAM": "TEAM",
        },
    },
    "Ciberseguridad": {
        "benchmark": "CIBR",
        "empresas": ["CRWD", "PANW", "ZS", "FTNT", "OKTA", "QLYS", "TENB", "RPD", "VRNS"],
        "tickers": {
            "CIBR": "CIBR", "CRWD": "CRWD", "PANW": "PANW", "ZS": "ZS", "FTNT": "FTNT",
            "OKTA": "OKTA", "QLYS": "QLYS", "TENB": "TENB", "RPD": "RPD", "VRNS": "VRNS",
        },
    },
    "Fintech": {
        "benchmark": "FINX",
        "empresas": ["PYPL", "AFRM", "SOFI", "UPST", "LC", "NU", "COIN", "HOOD", "BILL"],
        "tickers": {
            "FINX": "FINX", "PYPL": "PYPL", "AFRM": "AFRM", "SOFI": "SOFI", "UPST": "UPST",
            "LC": "LC", "NU": "NU", "COIN": "COIN", "HOOD": "HOOD", "BILL": "BILL",
        },
    },
    "Internet": {
        "benchmark": "FDN",
        "empresas": ["GOOGL", "META", "NFLX", "SNAP", "PINS", "RDDT", "SPOT", "ROKU", "DASH"],
        "tickers": {
            "FDN": "FDN", "GOOGL": "GOOGL", "META": "META", "NFLX": "NFLX", "SNAP": "SNAP",
            "PINS": "PINS", "RDDT": "RDDT", "SPOT": "SPOT", "ROKU": "ROKU", "DASH": "DASH",
        },
    },
    "E-commerce": {
        "benchmark": "IBUY",
        "empresas": ["AMZN", "SHOP", "ETSY", "EBAY", "MELI", "SE", "PDD", "BABA", "JD"],
        "tickers": {
            "IBUY": "IBUY", "AMZN": "AMZN", "SHOP": "SHOP", "ETSY": "ETSY", "EBAY": "EBAY",
            "MELI": "MELI", "SE": "SE", "PDD": "PDD", "BABA": "BABA", "JD": "JD",
        },
    },

    # ============================================================
    #  GRUPOS NUEVOS — salud
    # ============================================================
    "Biotecnología": {
        "benchmark": "XBI",
        "empresas": ["AMGN", "REGN", "VRTX", "GILD", "BIIB", "MRNA", "ALNY", "CRSP", "BEAM"],
        "tickers": {
            "XBI": "XBI", "AMGN": "AMGN", "REGN": "REGN", "VRTX": "VRTX", "GILD": "GILD",
            "BIIB": "BIIB", "MRNA": "MRNA", "ALNY": "ALNY", "CRSP": "CRSP", "BEAM": "BEAM",
        },
    },
    "Farmacéuticas": {
        "benchmark": "PPH",
        "empresas": ["LLY", "JNJ", "PFE", "MRK", "ABBV", "BMY", "AZN", "NVO", "SNY"],
        "tickers": {
            "PPH": "PPH", "LLY": "LLY", "JNJ": "JNJ", "PFE": "PFE", "MRK": "MRK",
            "ABBV": "ABBV", "BMY": "BMY", "AZN": "AZN", "NVO": "NVO", "SNY": "SNY",
        },
    },
    "Equipos Médicos": {
        "benchmark": "IHI",
        "empresas": ["ISRG", "ABT", "SYK", "BSX", "MDT", "EW", "ZBH", "BDX", "DXCM"],
        "tickers": {
            "IHI": "IHI", "ISRG": "ISRG", "ABT": "ABT", "SYK": "SYK", "BSX": "BSX",
            "MDT": "MDT", "EW": "EW", "ZBH": "ZBH", "BDX": "BDX", "DXCM": "DXCM",
        },
    },
    "Servicios de Salud": {
        "benchmark": "IHF",
        "empresas": ["UNH", "ELV", "CI", "HUM", "CVS", "CNC", "MOH", "DVA", "HCA"],
        "tickers": {
            "IHF": "IHF", "UNH": "UNH", "ELV": "ELV", "CI": "CI", "HUM": "HUM",
            "CVS": "CVS", "CNC": "CNC", "MOH": "MOH", "DVA": "DVA", "HCA": "HCA",
        },
    },

    # ============================================================
    #  GRUPOS NUEVOS — financieras granulares
    # ============================================================
    "Seguros": {
        "benchmark": "KIE",
        "empresas": ["PGR", "CB", "TRV", "ALL", "AFL", "MET", "PRU", "AIG", "HIG"],
        "tickers": {
            "KIE": "KIE", "PGR": "PGR", "CB": "CB", "TRV": "TRV", "ALL": "ALL",
            "AFL": "AFL", "MET": "MET", "PRU": "PRU", "AIG": "AIG", "HIG": "HIG",
        },
    },
    "Mercados Capitales": {
        "benchmark": "KCE",
        "empresas": ["SCHW", "CME", "ICE", "NDAQ", "MS", "GS", "IBKR", "HOOD", "COIN"],
        "tickers": {
            "KCE": "KCE", "SCHW": "SCHW", "CME": "CME", "ICE": "ICE", "NDAQ": "NDAQ",
            "MS": "MS", "GS": "GS", "IBKR": "IBKR", "HOOD": "HOOD", "COIN": "COIN",
        },
    },
    "Bancos Regionales": {
        "benchmark": "KRE",
        "empresas": ["FITB", "HBAN", "RF", "CFG", "ZION", "KEY", "CMA", "MTB", "WAL"],
        "tickers": {
            "KRE": "KRE", "FITB": "FITB", "HBAN": "HBAN", "RF": "RF", "CFG": "CFG",
            "ZION": "ZION", "KEY": "KEY", "CMA": "CMA", "MTB": "MTB", "WAL": "WAL",
        },
    },
    "Finanzas Diversif.": {
        "benchmark": "IYG",
        "empresas": ["V", "MA", "AXP", "DFS", "SYF", "ALLY", "COF", "FI", "PYPL"],
        "tickers": {
            "IYG": "IYG", "V": "V", "MA": "MA", "AXP": "AXP", "DFS": "DFS",
            "SYF": "SYF", "ALLY": "ALLY", "COF": "COF", "FI": "FI", "PYPL": "PYPL",
        },
    },

    # ============================================================
    #  GRUPOS NUEVOS — energía granular
    # ============================================================
    "Petróleo Integrado": {
        "benchmark": "XOP",
        "empresas": ["XOM", "CVX", "COP", "EOG", "OXY", "DVN", "MRO", "APA", "PXD"],
        "tickers": {
            "XOP": "XOP", "XOM": "XOM", "CVX": "CVX", "COP": "COP", "EOG": "EOG",
            "OXY": "OXY", "DVN": "DVN", "MRO": "MRO", "APA": "APA", "PXD": "PXD",
        },
    },
    "Gas Natural": {
        "benchmark": "FCG",
        "empresas": ["LNG", "EQT", "AR", "RRC", "CNX", "KMI", "WMB", "OKE", "TRGP"],
        "tickers": {
            "FCG": "FCG", "LNG": "LNG", "EQT": "EQT", "AR": "AR", "RRC": "RRC",
            "CNX": "CNX", "KMI": "KMI", "WMB": "WMB", "OKE": "OKE", "TRGP": "TRGP",
        },
    },
    "Energía Renovable": {
        "benchmark": "ICLN",
        "empresas": ["NEE", "BEP", "BEPC", "AES", "ORA", "PLUG", "BE", "GEV", "RUN"],
        "tickers": {
            "ICLN": "ICLN", "NEE": "NEE", "BEP": "BEP", "BEPC": "BEPC", "AES": "AES",
            "ORA": "ORA", "PLUG": "PLUG", "BE": "BE", "GEV": "GEV", "RUN": "RUN",
        },
    },
    "Energía Solar": {
        "benchmark": "TAN",
        "empresas": ["FSLR", "ENPH", "SEDG", "RUN", "ARRY", "SHLS", "CSIQ", "JKS", "NOVA"],
        "tickers": {
            "TAN": "TAN", "FSLR": "FSLR", "ENPH": "ENPH", "SEDG": "SEDG", "RUN": "RUN",
            "ARRY": "ARRY", "SHLS": "SHLS", "CSIQ": "CSIQ", "JKS": "JKS", "NOVA": "NOVA",
        },
    },
    "Litio/Baterías": {
        "benchmark": "LIT",
        "empresas": ["ALB", "LAC", "PLL", "SES", "QS", "MVST", "LICY", "ALTM", "ENVX"],
        "tickers": {
            "LIT": "LIT", "ALB": "ALB", "LAC": "LAC", "PLL": "PLL", "SES": "SES",
            "QS": "QS", "MVST": "MVST", "LICY": "LICY", "ALTM": "ALTM", "ENVX": "ENVX",
        },
    },

    # ============================================================
    #  GRUPOS NUEVOS — industriales / defensa / transporte
    # ============================================================
    "Aeroespacial": {
        "benchmark": "ITA",
        "empresas": ["BA", "RTX", "LMT", "NOC", "GD", "HII", "TDG", "HEI", "LHX"],
        "tickers": {
            "ITA": "ITA", "BA": "BA", "RTX": "RTX", "LMT": "LMT", "NOC": "NOC",
            "GD": "GD", "HII": "HII", "TDG": "TDG", "HEI": "HEI", "LHX": "LHX",
        },
    },
    "Defensa": {
        "benchmark": "XAR",
        "empresas": ["LMT", "RTX", "NOC", "GD", "HII", "TDG", "KTOS", "AVAV", "LDOS"],
        "tickers": {
            "XAR": "XAR", "LMT": "LMT", "RTX": "RTX", "NOC": "NOC", "GD": "GD",
            "HII": "HII", "TDG": "TDG", "KTOS": "KTOS", "AVAV": "AVAV", "LDOS": "LDOS",
        },
    },
    "Transporte": {
        "benchmark": "IYT",
        "empresas": ["UPS", "FDX", "UNP", "CSX", "NSC", "JBHT", "ODFL", "XPO", "CHRW"],
        "tickers": {
            "IYT": "IYT", "UPS": "UPS", "FDX": "FDX", "UNP": "UNP", "CSX": "CSX",
            "NSC": "NSC", "JBHT": "JBHT", "ODFL": "ODFL", "XPO": "XPO", "CHRW": "CHRW",
        },
    },

    # ============================================================
    #  GRUPOS NUEVOS — consumo
    # ============================================================
    "Retail": {
        "benchmark": "XRT",
        "empresas": ["AMZN", "WMT", "TGT", "COST", "HD", "LOW", "TJX", "ROST", "DG"],
        "tickers": {
            "XRT": "XRT", "AMZN": "AMZN", "WMT": "WMT", "TGT": "TGT", "COST": "COST",
            "HD": "HD", "LOW": "LOW", "TJX": "TJX", "ROST": "ROST", "DG": "DG",
        },
    },
    "Autos": {
        "benchmark": "CARZ",
        "empresas": ["TSLA", "GM", "F", "TM", "HMC", "STLA", "RIVN", "LCID", "NIO"],
        "tickers": {
            "CARZ": "CARZ", "TSLA": "TSLA", "GM": "GM", "F": "F", "TM": "TM",
            "HMC": "HMC", "STLA": "STLA", "RIVN": "RIVN", "LCID": "LCID", "NIO": "NIO",
        },
    },
    "Hotelería/Viajes": {
        "benchmark": "PEJ",
        "empresas": ["MAR", "HLT", "ABNB", "BKNG", "EXPE", "RCL", "CCL", "NCLH", "MGM"],
        "tickers": {
            "PEJ": "PEJ", "MAR": "MAR", "HLT": "HLT", "ABNB": "ABNB", "BKNG": "BKNG",
            "EXPE": "EXPE", "RCL": "RCL", "CCL": "CCL", "NCLH": "NCLH", "MGM": "MGM",
        },
    },
    "Alimentos": {
        "benchmark": "PBJ",
        "empresas": ["KO", "PEP", "MDLZ", "KHC", "GIS", "CPB", "SJM", "K", "HSY"],
        "tickers": {
            "PBJ": "PBJ", "KO": "KO", "PEP": "PEP", "MDLZ": "MDLZ", "KHC": "KHC",
            "GIS": "GIS", "CPB": "CPB", "SJM": "SJM", "K": "K", "HSY": "HSY",
        },
    },

    # ============================================================
    #  GRUPOS NUEVOS — materiales / commodities
    # ============================================================
    "Cobre/Metales": {
        "benchmark": "COPX",
        "empresas": ["FCX", "SCCO", "TECK", "HBM", "NUE", "STLD", "CLF", "AA", "ERO"],
        "tickers": {
            "COPX": "COPX", "FCX": "FCX", "SCCO": "SCCO", "TECK": "TECK", "HBM": "HBM",
            "NUE": "NUE", "STLD": "STLD", "CLF": "CLF", "AA": "AA", "ERO": "ERO",
        },
    },
    "Acero": {
        "benchmark": "SLX",
        "empresas": ["NUE", "STLD", "CLF", "X", "MT", "RS", "CMC", "PKX", "ATI"],
        "tickers": {
            "SLX": "SLX", "NUE": "NUE", "STLD": "STLD", "CLF": "CLF", "X": "X",
            "MT": "MT", "RS": "RS", "CMC": "CMC", "PKX": "PKX", "ATI": "ATI",
        },
    },
    "Agua": {
        "benchmark": "PHO",
        "empresas": ["AWK", "WTRG", "AWR", "YORW", "MSEX", "SJW", "CWCO", "GWRS", "ARTNA"],
        "tickers": {
            "PHO": "PHO", "AWK": "AWK", "WTRG": "WTRG", "AWR": "AWR", "YORW": "YORW",
            "MSEX": "MSEX", "SJW": "SJW", "CWCO": "CWCO", "GWRS": "GWRS", "ARTNA": "ARTNA",
        },
    },
    "Agro/Fertilizantes": {
        "benchmark": "MOS",
        "empresas": ["NTR", "CF", "ADM", "BG", "FMC", "CTVA"],
        "tickers": {
            "MOS": "MOS", "NTR": "NTR", "CF": "CF", "ADM": "ADM",
            "BG": "BG", "FMC": "FMC", "CTVA": "CTVA",
        },
    },

    # ============================================================
    #  GRUPOS NUEVOS — REITs granulares
    # ============================================================
    "REIT Industrial": {
        "benchmark": "INDS",
        "empresas": ["PLD", "AMT", "CCI", "DLR", "EQIX", "STAG", "EGP", "FR", "REXR"],
        "tickers": {
            "INDS": "INDS", "PLD": "PLD", "AMT": "AMT", "CCI": "CCI", "DLR": "DLR",
            "EQIX": "EQIX", "STAG": "STAG", "EGP": "EGP", "FR": "FR", "REXR": "REXR",
        },
    },
    "REIT Residencial": {
        "benchmark": "REZ",
        "empresas": ["EQR", "AVB", "ESS", "MAA", "UDR", "CPT", "ELS", "INVH", "AMH"],
        "tickers": {
            "REZ": "REZ", "EQR": "EQR", "AVB": "AVB", "ESS": "ESS", "MAA": "MAA",
            "UDR": "UDR", "CPT": "CPT", "ELS": "ELS", "INVH": "INVH", "AMH": "AMH",
        },
    },

    # ============================================================
    #  GRUPOS NUEVOS — telecom
    # ============================================================
    "Telecomunicaciones": {
        "benchmark": "IYZ",
        "empresas": ["T", "VZ", "TMUS", "S", "CHTR", "CMCSA", "LUMN", "VOD", "BT"],
        "tickers": {
            "IYZ": "IYZ", "T": "T", "VZ": "VZ", "TMUS": "TMUS", "S": "S",
            "CHTR": "CHTR", "CMCSA": "CMCSA", "LUMN": "LUMN", "VOD": "VOD", "BT": "BT",
        },
    },

    # ============================================================
    #  GRUPOS NUEVOS — países / regiones
    # ============================================================
    "China": {
        "benchmark": "FXI",
        "empresas": ["BABA", "TCEHY", "BIDU", "JD", "NIO", "LI", "XPEV", "PDD", "NTES"],
        "tickers": {
            "FXI": "FXI", "BABA": "BABA", "TCEHY": "TCEHY", "BIDU": "BIDU", "JD": "JD",
            "NIO": "NIO", "LI": "LI", "XPEV": "XPEV", "PDD": "PDD", "NTES": "NTES",
        },
    },
    "India": {
        "benchmark": "INDA",
        "empresas": ["INFY", "WIT", "HDB", "IBN", "VEDL", "RDY", "TTM"],
        "tickers": {
            "INDA": "INDA", "INFY": "INFY", "WIT": "WIT", "HDB": "HDB", "IBN": "IBN",
            "VEDL": "VEDL", "RDY": "RDY", "TTM": "TTM",
        },
    },
    "Europa Tecnología": {
        "benchmark": "VGK",
        "empresas": ["SAP", "ASML", "NXPI"],
        "tickers": {
            "VGK": "VGK", "SAP": "SAP", "ASML": "ASML", "NXPI": "NXPI",
        },
    },
    "Europa Finanzas": {
        "benchmark": "VGK",
        "empresas": ["HSBC", "BBVA", "SAN", "UBS", "ING"],
        "tickers": {
            "VGK": "VGK", "HSBC": "HSBC", "BBVA": "BBVA", "SAN": "SAN",
            "UBS": "UBS", "ING": "ING",
        },
    },

    # ============================================================
    #  GRUPOS NUEVOS — cripto mineras
    # ============================================================
    "Cripto Mineras": {
        "benchmark": "COIN",
        "empresas": ["MARA", "RIOT", "CLSK", "HUT", "BTDR", "IREN", "CAN", "WULF"],
        "tickers": {
            "COIN": "COIN", "MARA": "MARA", "RIOT": "RIOT", "CLSK": "CLSK", "HUT": "HUT",
            "BTDR": "BTDR", "IREN": "IREN", "CAN": "CAN", "WULF": "WULF",
        },
    },
}


def _pares_armar_parejas(sectores_sel, incluir_cruces=False):
    """Benchmark vs cada empresa (siempre) y, si incluir_cruces=True, también
    todas las combinaciones empresa-empresa dentro del sector."""
    parejas = {}
    tickers_codigos = {}
    for sector in sectores_sel:
        info = PARES_SECTORES[sector]
        benchmark = info["benchmark"]
        empresas = info["empresas"]
        tickers_codigos.update(info["tickers"])
        for empresa in empresas:
            parejas[f'[{sector}] {benchmark}/{empresa}'] = (benchmark, empresa, sector)
        if incluir_cruces:
            for a, b in combinations(empresas, 2):
                parejas[f'[{sector}] {a}/{b}'] = (a, b, sector)
    return parejas, tickers_codigos


@st.cache_data(ttl=3600, show_spinner=False)
def _pares_descargar_precios(tickers_items, inicio):
    """tickers_items: tupla ordenada de (codigo, symbol_yahoo) — clave de caché estable."""
    try:
        import yfinance as yf
        tickers_dict = dict(tickers_items)
        symbols = sorted(set(tickers_dict.values()))
        data = yf.download(symbols, start=inicio, auto_adjust=True, progress=False, group_by='column')
        if data is None or data.empty:
            return None
        if isinstance(data.columns, pd.MultiIndex):
            if 'Close' in data.columns.get_level_values(0):
                precios_symbol = data['Close'].copy()
            elif 'Adj Close' in data.columns.get_level_values(0):
                precios_symbol = data['Adj Close'].copy()
            else:
                return None
        else:
            precios_symbol = data.copy()
            if len(symbols) == 1 and 'Close' in precios_symbol.columns:
                precios_symbol = precios_symbol[['Close']].rename(columns={'Close': symbols[0]})
        precios = pd.DataFrame(index=precios_symbol.index)
        for codigo, symbol in tickers_dict.items():
            precios[codigo] = precios_symbol[symbol] if symbol in precios_symbol.columns else np.nan
        return precios.dropna(how='all').ffill()
    except Exception:
        return None


def _pares_generar_ratio(precios, num, den, ventana, z_entry, z_exit):
    df = pd.DataFrame(index=precios.index)
    df['NUM'] = precios[num]
    df['DEN'] = precios[den]
    df = df.dropna()
    if df.empty:
        return df
    df['RATIO'] = df['NUM'] / df['DEN']
    df['MEDIA'] = df['RATIO'].rolling(ventana).mean()
    df['STD'] = df['RATIO'].rolling(ventana).std()
    df['Z'] = (df['RATIO'] - df['MEDIA']) / df['STD']
    df['UPPER'] = df['MEDIA'] + df['STD'] * z_entry
    df['LOWER'] = df['MEDIA'] - df['STD'] * z_entry
    df['SEÑAL'] = 'NEUTRO'
    df.loc[df['Z'] > z_entry, 'SEÑAL'] = f'🔴 VENDER {num} / COMPRAR {den}'
    df.loc[df['Z'] < -z_entry, 'SEÑAL'] = f'🟢 COMPRAR {num} / VENDER {den}'
    df.loc[df['Z'].abs() < z_exit, 'SEÑAL'] = '⚪ CERRAR / NEUTRO'
    return df


def _pares_interpretar(z, z_entry, z_exit):
    if z > z_entry:
        return 'Ratio caro respecto a su historia reciente. Posible reversión bajista del ratio.'
    elif z < -z_entry:
        return 'Ratio barato respecto a su historia reciente. Posible reversión alcista del ratio.'
    elif abs(z) < z_exit:
        return 'El ratio volvió a su zona de equilibrio histórico — sin ventaja estadística clara.'
    else:
        return 'Z-Score dentro de rango normal, sin señal extrema.'


def _pares_fig_ratio(nombre, df, z_entry):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                         row_heights=[0.65, 0.35], subplot_titles=(f'Ratio {nombre}', 'Z-Score'))
    fig.add_trace(go.Scatter(x=df.index, y=df['UPPER'], line=dict(color=C_MUTED, width=0.8, dash='dash'),
                              name='Banda superior'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['LOWER'], line=dict(color=C_MUTED, width=0.8, dash='dash'),
                              name='Banda inferior', fill='tonexty', fillcolor='rgba(58,123,213,0.08)'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MEDIA'], line=dict(color=C_YELL, width=1.2, dash='dot'),
                              name='Media móvil'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['RATIO'], line=dict(color=C_ACENT, width=1.8),
                              name='Ratio'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['Z'], line=dict(color=C_MONSTER, width=1.4),
                              name='Z-Score'), row=2, col=1)
    fig.add_hline(y=z_entry, line_dash='dash', line_color=C_RED, opacity=0.6, row=2, col=1)
    fig.add_hline(y=-z_entry, line_dash='dash', line_color=C_GREEN, opacity=0.6, row=2, col=1)
    fig.add_hline(y=0, line_color=C_MUTED, opacity=0.4, row=2, col=1)
    fig.update_yaxes(gridcolor=C_GRID, row=1, col=1)
    fig.update_yaxes(gridcolor=C_GRID, row=2, col=1)
    fig.update_xaxes(gridcolor=C_GRID)
    fig.update_layout(**PLOTLY_LAYOUT_BASE, height=560, hovermode='x unified',
                       legend=dict(orientation='h', y=1.08, font=dict(size=9)),
                       margin=dict(l=10, r=10, t=50, b=10))
    fig.update_annotations(font=dict(color=C_TEXT, size=12))
    return fig


def modulo_scanner_pares():
    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1c20 0%,#0a2530 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #79c0ff;
         border-radius:14px; padding:28px 32px; margin-bottom:24px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">🔗 Scanner de Pares (Mean Reversion)</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Calcula el ratio entre el ETF benchmark de cada sector y sus empresas (y, opcionalmente,
        entre empresas del mismo sector), mide su Z-Score respecto a la media móvil y señala
        cuándo el ratio está estadísticamente "caro" o "barato" — candidato a reversión a la media.
      </div>
    </div>
    """, unsafe_allow_html=True)

    sectores_disp = list(PARES_SECTORES.keys())
    c1, c2 = st.columns([3, 1])
    with c1:
        sectores_sel = st.multiselect('Sectores a escanear', sectores_disp,
                                       default=sectores_disp[:2], key='pares_sectores_sel')
    with c2:
        incluir_cruces = st.checkbox('Incluir cruces empresa-empresa', value=False, key='pares_cruces',
                                      help='Suma todas las combinaciones entre empresas del mismo sector. Crece rápido: usar con pocos sectores.')

    cparam1, cparam2, cparam3, cparam4 = st.columns(4)
    with cparam1:
        ventana = st.slider('Ventana (ruedas)', 60, 504, 252, 6, key='pares_ventana')
    with cparam2:
        z_entry = st.slider('Z de entrada', 0.5, 3.0, 1.5, 0.1, key='pares_z_entry')
    with cparam3:
        z_exit = st.slider('Z de salida (neutro)', 0.1, 1.5, 0.5, 0.1, key='pares_z_exit')
    with cparam4:
        inicio_fecha = st.text_input('Inicio histórico', value='2020-01-01', key='pares_inicio')

    if not sectores_sel:
        st.info('Seleccioná al menos un sector para escanear.')
        return

    correr = st.button('▶ Escanear pares', key='pares_run', type='primary')
    if not correr and not st.session_state.get('pares_run_flag'):
        st.markdown("""
        <div style='background:#0d1117;border:1px dashed #21262d;border-radius:10px;padding:40px;text-align:center'>
          <div style='font-size:40px;margin-bottom:12px'>🔗</div>
          <div style='color:#e6edf3;font-size:14px;font-weight:600;margin-bottom:6px'>Scanner de Pares</div>
          <div style='color:#6b7d9a;font-size:12px'>Elegí sectores y presioná "Escanear pares" para calcular los ratios.</div>
        </div>
        """, unsafe_allow_html=True)
        return
    if correr:
        st.session_state['pares_run_flag'] = True

    parejas, tickers_codigos = _pares_armar_parejas(sectores_sel, incluir_cruces)
    if not parejas:
        st.warning('No se generaron parejas para los sectores elegidos.')
        return
    if len(parejas) > 300:
        st.warning(f'⚠️ Se generaron {len(parejas)} parejas — puede tardar. Considerá reducir sectores o desactivar los cruces.')

    with st.spinner(f'Descargando precios para {len(tickers_codigos)} activos...'):
        tickers_items = tuple(sorted(tickers_codigos.items()))
        precios = _pares_descargar_precios(tickers_items, inicio_fecha)

    if precios is None or precios.empty:
        st.error('No se pudieron descargar precios. Revisá la fecha de inicio o probá con otros sectores.')
        return

    resumen = []
    dataframes = {}
    fallidas = []
    prog = st.progress(0, text='Calculando ratios y Z-Scores...')
    total_p = len(parejas)
    for i, (nombre_ratio, (num, den, sector)) in enumerate(parejas.items()):
        try:
            if num not in precios.columns or den not in precios.columns:
                fallidas.append(nombre_ratio); continue
            df = _pares_generar_ratio(precios, num, den, ventana, z_entry, z_exit)
            df_clean = df.dropna(subset=['Z']) if not df.empty else df
            if df_clean.empty:
                fallidas.append(nombre_ratio); continue
            ultimo = df_clean.iloc[-1]
            z = float(ultimo['Z'])
            resumen.append({
                'Sector': sector, 'Pareja': nombre_ratio, 'Numerador': num, 'Denominador': den,
                'Ratio': round(float(ultimo['RATIO']), 4), 'Media': round(float(ultimo['MEDIA']), 4),
                'Z-Score': round(z, 2), 'Señal': ultimo['SEÑAL'],
                'Lectura': _pares_interpretar(z, z_entry, z_exit),
            })
            dataframes[nombre_ratio] = df
        except Exception:
            fallidas.append(nombre_ratio)
        if i % 10 == 0:
            prog.progress(min(int((i + 1) / total_p * 100), 100), text=f'Calculando... {i+1}/{total_p}')
    prog.empty()

    if not resumen:
        st.error('No se pudo calcular ningún ratio (historia insuficiente para la ventana elegida).')
        return
    if fallidas:
        st.caption(f'⚠️ {len(fallidas)} parejas sin datos suficientes y excluidas del resumen.')

    df_res = pd.DataFrame(resumen).sort_values('Z-Score', key=lambda s: s.abs(), ascending=False).reset_index(drop=True)

    n_compra = int((df_res['Z-Score'] < -z_entry).sum())
    n_venta  = int((df_res['Z-Score'] > z_entry).sum())
    n_neutro = int((df_res['Z-Score'].abs() < z_exit).sum())
    kpi_cards_4([
        ('Pares analizados', str(len(df_res)), f'{len(sectores_sel)} sectores', '#3a7bd5'),
        ('🟢 Señal compra ratio', str(n_compra), f'Z < -{z_entry}', '#3fb950'),
        ('🔴 Señal venta ratio', str(n_venta), f'Z > {z_entry}', '#f85149'),
        ('⚪ Neutros', str(n_neutro), f'|Z| < {z_exit}', '#e3b341'),
    ])

    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        sec_u = ['Todos'] + sorted(df_res['Sector'].unique().tolist())
        f_sec = st.selectbox('Sector', sec_u, key='pares_f_sector')
    with fc2:
        sen_u = ['Todas'] + sorted(df_res['Señal'].unique().tolist())
        f_sen = st.selectbox('Señal', sen_u, key='pares_f_senal')
    with fc3:
        max_z_data = float(max(3.0, df_res['Z-Score'].abs().max()))
        if 'pares_f_z' not in st.session_state:
            st.session_state['pares_f_z'] = (0.0, max_z_data)
        else:
            lo_prev, hi_prev = st.session_state['pares_f_z']
            if hi_prev > max_z_data or lo_prev > max_z_data:
                st.session_state['pares_f_z'] = (0.0, max_z_data)
        f_z = st.slider('Rango |Z-Score|', 0.0, max_z_data, key='pares_f_z')

    df_f = df_res.copy()
    if f_sec != 'Todos': df_f = df_f[df_f['Sector'] == f_sec]
    if f_sen != 'Todas': df_f = df_f[df_f['Señal'] == f_sen]
    df_f = df_f[df_f['Z-Score'].abs().between(*f_z)]

    def _color_z(val):
        try:
            v = abs(float(val))
            if v >= z_entry: return 'color:#f85149;font-weight:700' if val > 0 else 'color:#3fb950;font-weight:700'
            if v < z_exit: return 'color:#8b949e'
            return 'color:#e3b341;font-weight:600'
        except: return ''

    _map = 'map' if hasattr(df_f.style, 'map') else 'applymap'
    styled = (df_f[['Sector','Pareja','Ratio','Media','Z-Score','Señal']].style
              .pipe(lambda s: getattr(s, _map)(_color_z, subset=['Z-Score']))
              .set_properties(**{'background-color':'#0d1117','color':'#e6edf3','border':'1px solid #21262d'})
              .set_table_styles([
                  {'selector':'th','props':[('background-color','#161b22'),('color','#e6edf3'),
                      ('font-weight','700'),('text-align','center'),
                      ('border-bottom','2px solid #3a7bd5'),('font-size','11px')]},
                  {'selector':'td','props':[('text-align','center'),('font-size','11px')]},
              ]))
    st.dataframe(styled, use_container_width=True, height=min(600, max(150, len(df_f)*35+45)))
    st.caption(f'{len(df_f)} pares mostrados de {len(df_res)} totales')

    # ── BUSCAR SEÑALES POR ACTIVO ──────────────────────────────────────
    st.markdown('---')
    st.markdown('### 🔎 Buscar señales por activo')
    st.caption('Elegí un activo puntual y mirá TODAS las parejas donde aparece (como numerador o denominador), con su sector, Z-Score y señal.')

    activos_disponibles = sorted(tickers_codigos.keys())
    activo_sel = st.selectbox('Activo', activos_disponibles, key='pares_activo_sel')

    if activo_sel:
        df_activo = df_res[
            (df_res['Numerador'] == activo_sel) | (df_res['Denominador'] == activo_sel)
        ].copy()
        df_activo = df_activo.sort_values(
            'Z-Score', key=lambda s: s.abs(), ascending=False
        ).reset_index(drop=True)

        if df_activo.empty:
            st.info(f'No hay parejas calculadas para {activo_sel} con los sectores/parámetros elegidos arriba.')
        else:
            n_compra_act = int((df_activo['Z-Score'] < -z_entry).sum())
            n_venta_act  = int((df_activo['Z-Score'] > z_entry).sum())
            n_neutro_act = int((df_activo['Z-Score'].abs() < z_exit).sum())
            kpi_cards_4([
                ('Parejas encontradas', str(len(df_activo)), activo_sel, '#3a7bd5'),
                ('🟢 Señal compra', str(n_compra_act), f'Z < -{z_entry}', '#3fb950'),
                ('🔴 Señal venta', str(n_venta_act), f'Z > {z_entry}', '#f85149'),
                ('⚪ Neutros', str(n_neutro_act), f'|Z| < {z_exit}', '#e3b341'),
            ])

            styled_act = (
                df_activo[['Sector', 'Pareja', 'Ratio', 'Media', 'Z-Score', 'Señal']].style
                .pipe(lambda s: getattr(s, _map)(_color_z, subset=['Z-Score']))
                .set_properties(**{'background-color': '#0d1117', 'color': '#e6edf3', 'border': '1px solid #21262d'})
                .set_table_styles([
                    {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', '#e6edf3'),
                        ('font-weight', '700'), ('text-align', 'center'),
                        ('border-bottom', '2px solid #79c0ff'), ('font-size', '11px')]},
                    {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]},
                ])
            )
            st.dataframe(styled_act, use_container_width=True,
                         height=min(500, max(150, len(df_activo) * 38 + 45)))

            with st.expander(f'📝 Lectura detallada de cada pareja de {activo_sel}', expanded=False):
                for _, fila_act in df_activo.iterrows():
                    st.markdown(f"""
                    <div class="interp-card">
                      <div class="interp-header">{fila_act['Pareja']} · Sector: {fila_act['Sector']} · Z-Score: {fila_act['Z-Score']:+.2f}</div>
                      {fila_act['Lectura']}<br>
                      <span style="color:#6b7d9a;font-size:11px">Señal actual: {fila_act['Señal']}</span>
                    </div>
                    """, unsafe_allow_html=True)

    st.markdown('---')
    st.markdown('### 📈 Detalle de un par')
    pares_disp = df_f['Pareja'].tolist()
    if pares_disp:
        par_sel = st.selectbox('Elegí un par para ver el gráfico', pares_disp, key='pares_detalle_sel')
        fila = df_res[df_res['Pareja'] == par_sel].iloc[0]
        st.plotly_chart(_pares_fig_ratio(par_sel, dataframes[par_sel], z_entry),
                         use_container_width=True, key=f'pares_fig_{par_sel}')
        st.markdown(f"""
        <div class="interp-card">
          <div class="interp-header">{par_sel} · Sector: {fila['Sector']} · Z-Score: {fila['Z-Score']:+.2f}</div>
          {fila['Lectura']}<br>
          <span style="color:#6b7d9a;font-size:11px">Señal actual: {fila['Señal']}</span>
        </div>
        """, unsafe_allow_html=True)
        chips_navegacion([(fila['Numerador'], fila['Numerador']), (fila['Denominador'], fila['Denominador'])], 'pares_detalle')
    else:
        st.info('Ningún par cumple los filtros seleccionados.')



# ==============================================================
#  MÓDULO INICIO — cotizaciones del día por sección
# ==============================================================


def _cards_html(items_config, datos_precios):
    """Genera HTML de grilla de cards de cotización.
    items_config: lista de (display_name, ticker)
    datos_precios: dict {ticker: {precio, cambio_pct, cambio_abs}}
    """
    cards = []
    for nombre, tk in items_config:
        d = datos_precios.get(tk)
        if not d:
            cards.append(f"""
            <div style="background:#0d1117;border:1px solid #21262d;border-top:2px solid #21262d;
                 border-radius:8px;padding:12px 14px;min-width:0">
              <div style="font-size:11px;font-weight:700;color:#8b949e;font-family:'JetBrains Mono',monospace">{tk}</div>
              <div style="font-size:10px;color:#3a4a5f;margin-bottom:6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{nombre[:22]}</div>
              <div style="font-size:14px;color:#3a4a5f">S/D</div>
            </div>""")
            continue

        precio   = d['precio']
        pct      = d['cambio_pct']
        abs_c    = d['cambio_abs']
        color    = '#3fb950' if pct >= 0 else '#f85149'
        flecha   = '▲' if pct >= 0 else '▼'
        pct_str  = f'{flecha} {abs(pct):.2f}%'

        # formato del cambio absoluto según magnitud del precio
        if abs(precio) >= 1000:
            abs_str = f'{abs_c:+.2f}'
        elif abs(precio) >= 1:
            abs_str = f'{abs_c:+.3f}'
        else:
            abs_str = f'{abs_c:+.6f}'

        cards.append(f"""
        <div style="background:#0d1117;border:1px solid #21262d;border-top:2px solid {color};
             border-radius:8px;padding:12px 14px;min-width:0">
          <div style="font-size:11px;font-weight:700;color:#e6edf3;font-family:'JetBrains Mono',monospace;
               white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{tk}</div>
          <div style="font-size:10px;color:#6b7d9a;margin-bottom:8px;white-space:nowrap;overflow:hidden;
               text-overflow:ellipsis" title="{nombre}">{nombre[:22]}</div>
          <div style="font-size:15px;font-weight:700;color:#e6edf3;font-family:'JetBrains Mono',monospace">{fmt_precio(precio)}</div>
          <div style="font-size:12px;font-weight:700;color:{color};margin-top:3px">{pct_str}</div>
          <div style="font-size:10px;color:#6b7d9a;margin-top:1px">{abs_str}</div>
        </div>""")

    html = (
        '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(148px,1fr));'
        'gap:8px;margin-bottom:4px">'
        + ''.join(cards)
        + '</div>'
    )
    return html


def _sec_inicio(titulo, icono, items_config, datos_precios):
    """Renderiza un bloque de sección con título y grilla de cards."""
    st.markdown(
        f'<div class="sec-title">{icono} {titulo}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(_cards_html(items_config, datos_precios), unsafe_allow_html=True)


def _kpi_resumen_seccion(datos_dict, etiqueta_extra=''):
    """Calcula y renderiza los 4 KPI cards (Subiendo/Bajando/Neutros/Mejor)
    para un diccionario {ticker: {precio, cambio_pct, cambio_abs}} específico
    de una sección (índices, sectores, mercados, forex o acciones)."""
    if not datos_dict:
        st.info('Sin datos disponibles para esta sección.')
        return

    todos_pct = [d['cambio_pct'] for d in datos_dict.values()]
    n_sub = sum(1 for v in todos_pct if v > 0.05)
    n_baj = sum(1 for v in todos_pct if v < -0.05)
    n_neu = len(todos_pct) - n_sub - n_baj
    mejor = max(datos_dict.items(), key=lambda x: x[1]['cambio_pct'], default=(None, {'cambio_pct': 0}))

    sufijo = f' {etiqueta_extra}' if etiqueta_extra else ''
    kpi_cards_4([
        ('Subiendo hoy', str(n_sub), f'de {len(todos_pct)}{sufijo}', '#3fb950'),
        ('Bajando hoy',  str(n_baj), f'de {len(todos_pct)}{sufijo}', '#f85149'),
        ('Neutros',      str(n_neu), 'variación < ±0.05%', '#e3b341'),
        ('Mejor del día', mejor[0] or '-',
         f"{mejor[1]['cambio_pct']:+.2f}%" if mejor[0] else '', '#3fb950'),
    ])


def modulo_inicio():
    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #e3b341;
         border-radius:14px; padding:22px 28px; margin-bottom:20px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:4px">
        📊 Cotizaciones del día
      </div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.6">
        Precios y variación diaria para índices, sectores, mercados, forex y acciones.
        Datos de Yahoo Finance · caché 5 min · tocá <b style="color:#e6edf3">↺ Actualizar</b> para forzar recarga.
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Tabs principales ─────────────────────────────────────────────────
    tab_indices, tab_sectores, tab_mercados, tab_forex, tab_acciones = st.tabs([
        '🌍 Índices', '📊 Sectores', '🛢️ Mercados', '💱 Forex', '📈 Acciones',
    ])

    with st.spinner('Cargando cotizaciones...'):
        datos_base = cargar_precios_inicio_base()

    # ── Subconjuntos de datos_base por sección (para los KPI por tab) ─────
    tks_paises_all   = [tk for tk, _ in PAISES.values()]
    tks_sectores_all = [tk for tk, _ in SECTORES.values()]
    tks_mercados_all = [tk for tk, _, _ in MERCADOS_REALES.values()]
    tks_forex_all    = [tk for tk, _ in FOREX.values()]

    datos_indices_kpi  = {tk: d for tk, d in datos_base.items() if tk in tks_paises_all}
    datos_sectores_kpi = {tk: d for tk, d in datos_base.items() if tk in tks_sectores_all}
    datos_mercados_kpi = {tk: d for tk, d in datos_base.items() if tk in tks_mercados_all}
    datos_forex_kpi    = {tk: d for tk, d in datos_base.items() if tk in tks_forex_all}

    # ── TAB: Índices ──────────────────────────────────────────────────────
    with tab_indices:
        _kpi_resumen_seccion(datos_indices_kpi, 'índices')

        regiones = {}
        for nombre, (tk, region) in PAISES.items():
            regiones.setdefault(region, []).append((nombre, tk))

        for region, items in regiones.items():
            color_r = COLORES_REGION.get(region, C_MONSTER)
            st.markdown(
                f'<div style="font-size:11px;font-weight:700;color:{color_r};'
                f'text-transform:uppercase;letter-spacing:.8px;margin:14px 0 8px 0">'
                f'◆ {region}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(_cards_html(items, datos_base), unsafe_allow_html=True)

# ── TAB: Sectores ─────────────────────────────────────────────────────
    with tab_sectores:
        _kpi_resumen_seccion(datos_sectores_kpi, 'sectores')

        items_gics = [(nombre, tk) for nombre, (tk, cat, _c) in SECTORES_TOTAL.items() if cat == 'Sectores']
        items_sub  = [(nombre, tk) for nombre, (tk, cat, _c) in SECTORES_TOTAL.items() if cat == 'Sub-sectores']

        _sec_inicio('Sectores GICS (11 sectores)', '📊', items_gics, datos_base)
        st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)
        _sec_inicio('Sub-sectores / Temáticos', '🧩', items_sub, datos_base)

    # ── TAB: Mercados ─────────────────────────────────────────────────────
    with tab_mercados:
        _kpi_resumen_seccion(datos_mercados_kpi, 'mercados')

        cats_merc = {}
        for nombre, (tk, cat, _) in MERCADOS_REALES.items():
            cats_merc.setdefault(cat, []).append((nombre, tk))

        for cat, items in cats_merc.items():
            st.markdown(
                f'<div style="font-size:11px;font-weight:700;color:#f0883e;'
                f'text-transform:uppercase;letter-spacing:.8px;margin:14px 0 8px 0">'
                f'◆ {cat}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(_cards_html(items, datos_base), unsafe_allow_html=True)

    # ── TAB: Forex ────────────────────────────────────────────────────────
    with tab_forex:
        _kpi_resumen_seccion(datos_forex_kpi, 'pares')

        grupos_fx = {}
        for nombre, (tk, grupo) in FOREX.items():
            grupos_fx.setdefault(grupo, []).append((nombre, tk))

        for grupo, items in grupos_fx.items():
            color_fx = COLORES_GRUPO_FX.get(grupo, C_MONSTER)
            st.markdown(
                f'<div style="font-size:11px;font-weight:700;color:{color_fx};'
                f'text-transform:uppercase;letter-spacing:.8px;margin:14px 0 8px 0">'
                f'◆ {grupo}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(_cards_html(items, datos_base), unsafe_allow_html=True)

    # ── TAB: Acciones ─────────────────────────────────────────────────────
    with tab_acciones:
        ind_disp_ini = list(ACCIONES_POR_INDUSTRIA.keys())
        ind_sel_ini  = st.multiselect(
            'Industrias', ind_disp_ini,
            default=ind_disp_ini[:3],
            key='inicio_ind_sel',
            help='Elegí una o más industrias para ver sus cotizaciones del día.',
        )

        if not ind_sel_ini:
            st.info('Seleccioná al menos una industria para ver cotizaciones.')
        else:
            with st.spinner('Cargando precios de acciones...'):
                datos_acc_ini = cargar_precios_acciones_inicio(tuple(ind_sel_ini))

            # KPIs propios de Acciones, en base a las industrias seleccionadas
            _kpi_resumen_seccion(datos_acc_ini, 'acciones seleccionadas')

            filas_acc = []
            for ind in ind_sel_ini:
                for tk in ACCIONES_POR_INDUSTRIA.get(ind, []):
                    d = datos_acc_ini.get(tk)
                    if d:
                        filas_acc.append({
                            'Ticker': tk,
                            'Industria': ind,
                            'Precio': d['precio'],
                            'Cambio %': round(d['cambio_pct'], 2),
                            'Cambio $': round(d['cambio_abs'], 4),
                        })

            if not filas_acc:
                st.warning('No se pudieron cargar datos. Intentá ↺ Actualizar.')
            else:
                df_acc_ini = pd.DataFrame(filas_acc).sort_values('Cambio %', ascending=False)

                # Filtros rápidos
                fc1, fc2, fc3 = st.columns(3)
                with fc1:
                    inds_u_ini = ['Todas'] + sorted(df_acc_ini['Industria'].unique().tolist())
                    f_ind_ini  = st.selectbox('Industria', inds_u_ini, key='ini_f_ind')
                with fc2:
                    f_dir = st.selectbox('Dirección', ['Todas', '▲ Subiendo', '▼ Bajando'], key='ini_f_dir')
                with fc3:
                    f_pct_ini = st.slider('Cambio % mín/máx', -30.0, 30.0, (-30.0, 30.0), 0.5, key='ini_f_pct')

                df_acc_f = df_acc_ini.copy()
                if f_ind_ini != 'Todas':
                    df_acc_f = df_acc_f[df_acc_f['Industria'] == f_ind_ini]
                if f_dir == '▲ Subiendo':
                    df_acc_f = df_acc_f[df_acc_f['Cambio %'] > 0]
                elif f_dir == '▼ Bajando':
                    df_acc_f = df_acc_f[df_acc_f['Cambio %'] < 0]
                df_acc_f = df_acc_f[df_acc_f['Cambio %'].between(*f_pct_ini)]

                st.caption(f'{len(df_acc_f)} acciones mostradas de {len(df_acc_ini)} totales')

                # ── Cards agrupadas por industria ────────────────────────
                industrias_con_datos = [
                    ind for ind in ind_sel_ini
                    if (f_ind_ini == 'Todas' or f_ind_ini == ind)
                    and not df_acc_f[df_acc_f['Industria'] == ind].empty
                ]

                if not industrias_con_datos:
                    st.info('Ningún activo cumple los filtros seleccionados.')
                else:
                    for ind in industrias_con_datos:
                        tks_ind = df_acc_f[df_acc_f['Industria'] == ind].sort_values(
                            'Cambio %', ascending=False
                        )['Ticker'].tolist()
                        if not tks_ind:
                            continue
                        st.markdown(
                            f'<div style="font-size:11px;font-weight:700;color:{C_MONSTER};'
                            f'text-transform:uppercase;letter-spacing:.8px;margin:14px 0 8px 0">'
                            f'◆ {ind} ({len(tks_ind)})</div>',
                            unsafe_allow_html=True,
                        )
                        items_ind = [(tk, tk) for tk in tks_ind]
                        st.markdown(_cards_html(items_ind, datos_acc_ini), unsafe_allow_html=True)

                # Chips para ir al buscador
                chips_navegacion(df_acc_f['Ticker'].tolist(), 'inicio_acc')

# ==============================================================
#  MÓDULO NUEVO — SCORE AAS (Acumulación / Anticipación / Sentimiento)
#  Portado del script Top-Down MP/LP (Colab).
# ==============================================================

HORIZONTES_TDC = {
    'MP': {
        'nombre': 'MEDIANO PLAZO', 'subtitulo': 'Posiciones estimadas de 3 a 6 meses',
        'periodo_valor': '2y', 'periodo_momento': '6mo', 'min_dias_valor': 100,
        'ret_dias_1': 20, 'ret_label_1': '1m', 'ret_dias_2': 60, 'ret_label_2': '3m',
        'rsi_periodo': 14, 'vol_corta': 20, 'bb_ventana': 20, 'atr_periodo': 14,
        'mom_escala': 0.60,
    },
    'LP': {
        'nombre': 'LARGO PLAZO', 'subtitulo': 'Posiciones estimadas de 1 a 2 años',
        'periodo_valor': '10y', 'periodo_momento': '2y', 'min_dias_valor': 250,
        'ret_dias_1': 60, 'ret_label_1': '3m', 'ret_dias_2': 252, 'ret_label_2': '12m',
        'rsi_periodo': 21, 'vol_corta': 60, 'bb_ventana': 50, 'atr_periodo': 21,
        'mom_escala': 0.35,
    },
}


def _tdc_clasificar(s):
    if   s <= 20: return 'Miedo Extremo',  '#f85149', '🔴'
    elif s <= 40: return 'Miedo',           '#f0883e', '🟠'
    elif s <= 60: return 'Neutral',         '#e3b341', '🟡'
    elif s <= 80: return 'Codicia',         '#7ee787', '🟢'
    else:         return 'Codicia Extrema', '#3fb950', '💚'


def _tdc_scores(cv, cm, atr, cfg):
    cv = pd.Series(cv).dropna(); cm = pd.Series(cm).dropna()
    if len(cv) < 30 or len(cm) < 15:
        return 50.0, 50.0, 50.0
    precio_pct = pct_rank(cv)
    rsi_pct = 100 - pct_rank(calcular_rsi(cv, p=cfg['rsi_periodo']))
    vol_pct = 100 - pct_rank(vol_anual_rolling(cv, cfg['vol_corta']))
    sc_acum = (100 - precio_pct) * 0.40 + rsi_pct * 0.35 + vol_pct * 0.25

    d1 = cfg['ret_dias_1']
    ret_m = float(cm.pct_change(d1).iloc[-1] * 100) if len(cm) >= d1 + 1 else 0
    if np.isnan(ret_m): ret_m = 0
    mom = min(100, max(0, 50 + ret_m * cfg['mom_escala']))

    if atr is not None:
        atr_s = pd.Series(atr).dropna()
        comp_atr = max(0, min(100, 100 - (float(atr_s.iloc[-1]) / float(atr_s.mean()) * 50))) if len(atr_s) > 5 else 50
    else:
        comp_atr = 50

    bbv = cfg['bb_ventana']
    ma_bb = cm.rolling(bbv).mean(); sd_bb = cm.rolling(bbv).std()
    bbw = (sd_bb / ma_bb.replace(0, np.nan) * 100).dropna()
    bb_c = 100 - pct_rank(bbw) if len(bbw) > 5 else 50
    sc_antic = mom * 0.40 + comp_atr * 0.30 + bb_c * 0.30

    sc_sent = pct_rank(cv)
    return round(sc_acum, 1), round(sc_antic, 1), round(sc_sent, 1)


def _tdc_señal(sa, sn, ss):
    if   sa >= 62 and sn >= 55:               return '🟢 ACUMULAR'
    elif sa >= 62 and sn >= 40:               return '🟡 VIGILAR'
    elif sa >= 58 and sn <  40:               return '🔵 ACUMULAR GRADUAL'
    elif sa <  45 and sn >= 62 and ss >= 62:  return '🚀 TENDENCIA ALCISTA'
    elif sn >= 65 and 40 <= sa < 62:          return '⚡ MOVIMIENTO INMINENTE'
    elif sa <  38 and sn <  42 and ss >= 65:  return '⚠️ MÁXIMOS'
    elif sa >= 55 and sn <  35 and ss <  35:  return '🔴 EVITAR'
    elif sa <  38 and sn >= 55 and ss <  40:  return '🟠 REBOTE'
    else:                                      return '⏸️ ESPERAR'


def _tdc_fase(s):
    if   s <= 20: return 'MUY BAJO'
    elif s <= 40: return 'BAJO'
    elif s <= 60: return 'NEUTRAL'
    elif s <= 80: return 'ALTO'
    else:         return 'MUY ALTO'


def _tdc_interp_acum(s):
    if   s <= 20: return 'caro'
    elif s <= 40: return 'sobre la media'
    elif s <= 60: return 'en zona neutra'
    elif s <= 80: return 'barato'
    else:         return 'muy barato'


def _tdc_interp_antic(s):
    if   s <= 20: return 'momentum bajista fuerte'
    elif s <= 40: return 'momentum débil'
    elif s <= 60: return 'momentum neutral'
    elif s <= 80: return 'momentum alcista'
    else:         return 'momentum muy fuerte'


def _tdc_interp_sent(s):
    if   s <= 20: return 'pesimismo extremo'
    elif s <= 40: return 'pesimismo moderado'
    elif s <= 60: return 'sentimiento neutral'
    elif s <= 80: return 'sentimiento positivo'
    else:         return 'euforia'


def _tdc_interp_conjunto(sa, sn, ss):
    barato, caro = sa > 60, sa < 40
    alcista, bajista = sn > 60, sn < 40
    eufor, pesim = ss > 80, ss < 20
    if barato and alcista:      base = 'Continuidad alcista: precio barato + momentum confirmando la suba.'
    elif barato and bajista:    base = 'Rebote técnico o lateralización: precio barato pero el momentum aún no confirma giro al alza.'
    elif caro and bajista:      base = 'Continuidad bajista o corrección: precio caro + momentum débil/negativo.'
    elif caro and alcista:      base = 'Suba con riesgo de agotamiento: precio caro pero el momentum sigue empujando.'
    elif barato:                base = 'Acumulación: precio barato en zona de momentum neutral, posible piso formándose.'
    elif caro:                  base = 'Distribución o pausa: precio caro con momentum neutral, sin impulso claro.'
    else:                       base = 'Lateralización: sin sesgo claro entre precio y momentum.'
    if eufor: base += ' Sentimiento en euforia: señal de alerta de posible sobrecompra/techo cercano.'
    elif pesim: base += ' Sentimiento en pesimismo extremo: suele anticipar zonas de suelo o capitulación.'
    return base


def _tdc_texto_interpretacion(sa, sn, ss):
    return (f"Acum ({sa:.0f}) {_tdc_fase(sa)} — {_tdc_interp_acum(sa)}. "
            f"Antic ({sn:.0f}) {_tdc_fase(sn)} — {_tdc_interp_antic(sn)}. "
            f"Sent ({ss:.0f}) {_tdc_fase(ss)} — {_tdc_interp_sent(ss)}. "
            f"» {_tdc_interp_conjunto(sa, sn, ss)}")


def _tdc_analizar_ticker(tk, cfg):
    try:
        df_v = descargar_datos(tk, cfg['periodo_valor'])
        df_m = descargar_datos(tk, cfg['periodo_momento'])
        if df_v is None or df_m is None: return None
        cl_v = get_close_series(df_v); cl_m = get_close_series(df_m)
        if cl_v is None or cl_m is None or len(cl_v.dropna()) < cfg['min_dias_valor']:
            return None
        atr = calcular_atr(df_m, p=cfg['atr_periodo'])
        sa, sn, ss = _tdc_scores(cl_v, cl_m, atr, cfg)
        sf = sa * 0.45 + sn * 0.35 + ss * 0.20
        d1, d2 = cfg['ret_dias_1'], cfg['ret_dias_2']
        ret_1 = float(cl_m.pct_change(d1).iloc[-1] * 100) if len(cl_m) >= d1 + 1 else 0
        ret_2 = float(cl_m.pct_change(d2).iloc[-1] * 100) if len(cl_m) >= d2 + 1 else 0
        if np.isnan(ret_1): ret_1 = 0
        if np.isnan(ret_2): ret_2 = 0
        rsi = float(calcular_rsi(cl_m, p=cfg['rsi_periodo']).iloc[-1])
        if np.isnan(rsi): rsi = 50
        precio = float(cl_m.iloc[-1])
        return dict(tk=tk, sa=sa, sn=sn, ss=ss, sf=round(sf, 1),
                    ret_1=ret_1, ret_2=ret_2, rsi=rsi, precio=precio,
                    accion=_tdc_señal(sa, sn, ss))
    except Exception:
        return None


@st.cache_data(ttl=1800, show_spinner=False)
def cargar_topdown_cuantitativo(tickers_tuple, horizonte):
    """tickers_tuple: tupla ordenada de (nombre, ticker). horizonte: 'MP' o 'LP'."""
    cfg = HORIZONTES_TDC[horizonte]
    resultados = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futuros = {ex.submit(_tdc_analizar_ticker, tk, cfg): nombre for nombre, tk in tickers_tuple}
        for fut in as_completed(futuros):
            nombre = futuros[fut]
            r = fut.result()
            if r: resultados[nombre] = r
    return resultados


def _tdc_fig_momentum(datos_dict, cfg):
    ns = list(datos_dict.keys())
    r1 = [datos_dict[n]['ret_1'] for n in ns]
    r2 = [datos_dict[n]['ret_2'] for n in ns]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=ns, y=r1, name=cfg['ret_label_1'],
        marker_color=[C_GREEN if v >= 0 else C_RED for v in r1]))
    fig.add_trace(go.Bar(x=ns, y=r2, name=cfg['ret_label_2'], opacity=0.6,
        marker_color=[C_MONSTER if v >= 0 else '#bc8cff' for v in r2]))
    fig.add_hline(y=0, line_color=C_MUTED, opacity=0.4)
    fig.update_layout(**PLOTLY_LAYOUT_BASE, barmode='group',
        yaxis=dict(title='Retorno %', gridcolor=C_GRID),
        xaxis=dict(tickangle=-45, gridcolor=C_GRID),
        height=440, margin=dict(l=10, r=10, t=30, b=90),
        legend=dict(orientation='h', y=1.08))
    return fig


def modulo_topdown_cuantitativo():
    st.markdown("""
    <div style="background:linear-gradient(135deg,#150d20 0%,#1c1a0a 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #e3b341;
         border-radius:14px; padding:28px 32px; margin-bottom:24px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">📐 Top-Down Cuantitativo — Mediano/Largo Plazo</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Modelo Top-Down por percentil histórico, con dos horizontes: <b style="color:#f0883e">Mediano Plazo</b>
        (3-6 meses) y <b style="color:#3fb950">Largo Plazo</b> (1-2 años). Se aplica sobre los mismos activos
        que ya tiene la app (países, sectores, mercados reales y acciones por industria) — sin agregar tickers nuevos.
      </div>
    </div>
    """, unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        hz_label = st.selectbox('Horizonte', ['Mediano Plazo (3-6 meses)', 'Largo Plazo (1-2 años)'], key='tdc_hz')
        hz = 'MP' if 'Mediano' in hz_label else 'LP'
    with c2:
        universo_label = st.selectbox('Universo', [
            '🌍 Países / Índices Globales', '📊 Sectores GICS',
            '🧩 Sub-sectores / Temáticos', '🛢️ Mercados Reales',
            '📈 Acciones por Industria',
        ], key='tdc_universo')

    cfg = HORIZONTES_TDC[hz]
    st.caption(f"Historial de referencia: {cfg['periodo_valor']} · Ventana reciente: {cfg['periodo_momento']} · "
               f"Retornos mostrados: {cfg['ret_label_1']} / {cfg['ret_label_2']}")

    extra_map, tickers_tuple = {}, ()

    if universo_label.startswith('🌍'):
        tickers_tuple = tuple((n, tk) for n, (tk, _r) in PAISES.items())
        extra_map = {n: {'region': r} for n, (tk, r) in PAISES.items()}
    elif universo_label.startswith('📊'):
        tickers_tuple = tuple((n, tk) for n, (tk, _c) in SECTORES_GICS.items())
        extra_map = {n: {'color': c} for n, (tk, c) in SECTORES_GICS.items()}
    elif universo_label.startswith('🧩'):
        tickers_tuple = tuple((n, tk) for n, (tk, _c) in SUBSECTORES.items())
        extra_map = {n: {'color': c, 'grupo': SUBSECTOR_A_SECTOR.get(n, 'Otros')} for n, (tk, c) in SUBSECTORES.items()}
    elif universo_label.startswith('🛢️'):
        tickers_tuple = tuple((n, tk) for n, (tk, _cat, _c) in MERCADOS_REALES.items())
        extra_map = {n: {'cat': cat, 'color': c} for n, (tk, cat, c) in MERCADOS_REALES.items()}
    else:
        ind_disp_tdc = list(ACCIONES_POR_INDUSTRIA.keys())
        ind_sel_tdc = st.multiselect('Industrias', ind_disp_tdc,
            default=st.session_state.get('tdc_ind_sel', ind_disp_tdc[:1]), key='tdc_ind_sel_widget')
        st.session_state['tdc_ind_sel'] = ind_sel_tdc
        if not ind_sel_tdc:
            st.info('Seleccioná al menos una industria.'); return
        pares = []
        for ind in ind_sel_tdc:
            for tk in ACCIONES_POR_INDUSTRIA.get(ind, []):
                pares.append((tk, tk))
                extra_map[tk] = {'industria': ind}
        tickers_tuple = tuple(dict(pares).items())  # dedup por ticker

    if not tickers_tuple:
        st.info('No hay activos para este universo.'); return

    if st.button('▶ Calcular Scores del Top-Down Cuantitativo', key='tdc_run'):
        st.session_state['tdc_run_flag'] = True

    if not st.session_state.get('tdc_run_flag'):
        st.markdown("""
        <div style='background:#0d1117;border:1px dashed #21262d;border-radius:10px;padding:36px;text-align:center'>
          <div style='font-size:36px;margin-bottom:10px'>📐</div>
          <div style='color:#6b7d9a;font-size:12px'>Elegí horizonte y universo, después presioná "Calcular Scores del Top-Down Cuantitativo".</div>
        </div>
        """, unsafe_allow_html=True)
        return

    with st.spinner(f'Calculando scores del Top-Down Cuantitativo ({len(tickers_tuple)} activos)...'):
        datos = cargar_topdown_cuantitativo(tickers_tuple, hz)
        for n, extra in extra_map.items():
            if n in datos: datos[n].update(extra)

    if not datos:
        st.error('No se pudieron calcular scores (verificá el historial mínimo requerido).')
        return

    n_acum = sum(1 for d in datos.values() if d['sa'] >= 62)
    n_evitar = sum(1 for d in datos.values() if d['sa'] <= 38)
    mejor = max(datos.items(), key=lambda x: x[1]['sa'])
    kpi_cards_4([
        ('Activos analizados', str(len(datos)), f'{HORIZONTES_TDC[hz]["nombre"]}', '#e3b341'),
        ('🟢 Zona Acumulación', str(n_acum), 'Score Acum ≥ 62', '#3fb950'),
        ('🔴 Zona Evitar', str(n_evitar), 'Score Acum ≤ 38', '#f85149'),
        ('Mejor oportunidad', mejor[0], f"Acum {mejor[1]['sa']:.0f}", score_color_hex(mejor[1]['sa'])),
    ])

    tab1, tab2, tab3, tab4, tab5 = st.tabs(['📊 Scores', '📈 Momentum', '🗺️ Cuadrante', '🔥 Heatmap', '📋 Ranking'])
    items_ord = sorted(datos.items(), key=lambda x: x[1]['sa'], reverse=True)
    es_subsectores = universo_label.startswith('🧩')

    with tab1:
        if es_subsectores:
            grupos_en = sorted(set(d.get('grupo', 'Otros') for d in datos.values()))
            for i in range(0, len(grupos_en), 2):
                cols = st.columns(2)
                for j, grupo in enumerate(grupos_en[i:i+2]):
                    items_g = sorted([(n, d) for n, d in datos.items() if d.get('grupo') == grupo],
                                      key=lambda x: x[1]['sa'], reverse=True)
                    if not items_g: continue
                    fig_g = fig_barras_h(items_g, grupo, COLORES_SECTOR_PADRE.get(grupo, C_MONSTER))
                    with cols[j]:
                        st.plotly_chart(fig_g, use_container_width=True, key=f'tdc_barras_{grupo}')
        else:
            st.plotly_chart(fig_barras_h(items_ord, f'Score Acumulación — {HORIZONTES_TDC[hz]["nombre"]}'),
                             use_container_width=True, key='tdc_barras')
    with tab2:
        st.plotly_chart(_tdc_fig_momentum(datos, cfg), use_container_width=True, config=PLOTLY_CONFIG, key='tdc_momentum')
    with tab3:
        if es_subsectores:
            colores_grp = COLORES_SECTOR_PADRE
        elif universo_label.startswith('🌍'):
            colores_grp = COLORES_REGION
        else:
            colores_grp = None
        st.plotly_chart(fig_cuadrante(datos, colores_grp, f'Mapa de Oportunidades — {HORIZONTES_TDC[hz]["nombre"]}'),
                         use_container_width=True, key='tdc_cuadrante')
    with tab4:
        st.plotly_chart(fig_heatmap(datos, f'Heatmap Top-Down Cuantitativo — {HORIZONTES_TDC[hz]["nombre"]}'),
                         use_container_width=True, key='tdc_heatmap')
    with tab5:
        filas = []
        for n, d in items_ord:
            filas.append({'Nombre': n, 'Acum': d['sa'], 'Antic': d['sn'], 'Sent': d['ss'],
                          'RSI': round(d['rsi'], 1), f"Ret {cfg['ret_label_1']} %": round(d['ret_1'], 2),
                          f"Ret {cfg['ret_label_2']} %": round(d['ret_2'], 2),
                          'Precio': fmt_precio(d['precio']), 'Señal': d['accion']})
        df_tdc = pd.DataFrame(filas)
        ret_cols = [c for c in df_tdc.columns if c.startswith('Ret ')]
        styled = _apply_score_style(df_tdc, ['Acum', 'Antic', 'Sent'], ret_cols)
        st.dataframe(styled, use_container_width=True, height=min(600, max(150, len(df_tdc) * 35 + 45)))
        chips_navegacion([(n, datos[n].get('tk', n)) for n, _ in items_ord], 'tdc_tabla')

        st.markdown('### 📝 Lectura por activo')
        for n, d in items_ord[:15]:
            _, col_lbl, emo_lbl = _tdc_clasificar(d['sa'])
            st.markdown(f"""
            <div class="interp-card">
              <div class="interp-header">{emo_lbl} {n} · {col_lbl} · {d['accion']}</div>
              {_tdc_texto_interpretacion(d['sa'], d['sn'], d['ss'])}
            </div>
            """, unsafe_allow_html=True)
        if len(items_ord) > 15:
            st.caption(f'Mostrando lectura de los primeros 15 de {len(items_ord)} activos (ordenados por Score Acumulación).')

def _refrescar_cotizaciones():
    """Fuerza nueva descarga de precios y scores (corto/largo plazo, forex, países,
    sectores, mercados, acciones, ticker tape, Top-Down Cuantitativo). A propósito
    NO toca el caché de fundamental ni de perfil de empresa: esos ya tienen su TTL
    propio (1h / 24h), y si también se vacían acá, '↺ Actualizar' obliga a pedirle
    todo a Yahoo de golpe y aparece N/D por rate limit."""
    funciones_a_limpiar = [
        descargar_datos, descargar_bulk,
        cargar_forex_corto, cargar_paises_corto, cargar_sectores_corto,
        cargar_mercados_corto, cargar_acciones_corto, cargar_resultados_largo,
        cargar_precios_inicio_base, cargar_precios_acciones_inicio,
        cargar_ticker_tape, cargar_topdown_cuantitativo,
    ]
    for fn in funciones_a_limpiar:
        try:
            fn.clear()
        except Exception:
            pass
    st.rerun()


# ==============================================================
#  ESTADO DE NAVEGACIÓN
# ==============================================================

for key, default in [
    ('nav_horizonte', 'inicio'),
    ('nav_modulo', 'inicio'),
    ('nav_ind_sel_corto', list(ACCIONES_POR_INDUSTRIA.keys())[:1]),
    ('nav_ind_sel_largo', list(ACCIONES_POR_INDUSTRIA.keys())[:1]),
    ('nav_grupos_fx', list(dict.fromkeys(v[1] for v in FOREX.values()))),
    ('ticker_from_table', ''),
    ('ticker_manual', ''),
    ('comparador_tickers', []),
    ('comp_run_flag', False),
    ('pares_run_flag', False),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ==============================================================
#  TOP NAV BAR
# ==============================================================


_now_str = ahora_ar().strftime('%H:%M')
_h_color = {'inicio': '#e3b341', 'corto': '#f0883e', 'largo': '#3fb950', 'buscador': '#3a7bd5', 'comparador': '#6CC24A', 'optimizador': '#bc8cff', 'pares': '#79c0ff', 'opciones': '#bc5cff', 'senales': '#ff6ec7', 'finanzas': '#6CC24A'}
_h_label = {'inicio': 'Inicio', 'corto': 'Corto Plazo', 'largo': 'Largo Plazo', 'buscador': 'Búsqueda', 'comparador': 'Comparador', 'optimizador': 'Optimizador', 'pares': 'Rotación', 'opciones': 'Opciones', 'senales': 'Señales', 'finanzas': 'Finanzas'}

HORIZONTE = st.session_state['nav_horizonte']
MODULO    = st.session_state['nav_modulo']


st.markdown(f"""
<div class="topbar-wrap">
  <div class="topbar-inner">
    <div style="display:flex;align-items:center;gap:6px;flex-shrink:0">
      <span style="width:7px;height:7px;border-radius:50%;background:{_h_color.get(HORIZONTE,'#3a7bd5')};display:inline-block"></span>
      <span style="font-size:11px;font-weight:600;color:{_h_color.get(HORIZONTE,'#3a7bd5')}">{_h_label.get(HORIZONTE,'')}</span>
    </div>
    <div class="topbar-brand-center">
      <div class="topbar-brand-icon">📡</div>
      <div>
        <div class="topbar-brand-name">Capital<span>+</span></div>
        <div class="topbar-brand-sub">Actualización cada 30min</div>
      </div>
    </div>
    <div style="flex:1"></div>
    <div class="topbar-time">🕐 {_now_str}</div>
  </div>
</div>
""", unsafe_allow_html=True)


render_ticker_tape()


st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)


def _nav_btn(col, label, key, is_active, on_click_state, on_click_val_h=None, on_click_val_m=None):
    with col:
        cont_key = f'navcont_{key}'
        with st.container(key=cont_key):
            clicked = st.button(label, use_container_width=True, key=key)
        if is_active:
            st.markdown(f"""
            <style>
            .st-key-{cont_key} button {{
                background: #0d1117 !important;
                color: var(--verde-monster) !important;
                border: 1.5px solid var(--verde-monster) !important;
                font-weight: 700 !important;
                box-shadow: 0 0 0 2px rgba(108,194,74,0.15) !important;
            }}
            .st-key-{cont_key} button:hover {{
                background: #11150f !important;
                transform: translateY(-1px) !important;
            }}
            </style>
            """, unsafe_allow_html=True)
        if clicked:
            if on_click_val_h:
                st.session_state['nav_horizonte'] = on_click_val_h
            if on_click_val_m:
                st.session_state['nav_modulo'] = on_click_val_m
            st.rerun()


with st.container(key='nav_pills_wrap'):
    _c = st.columns([1.0, 1.15, 1.15, 1.05, 1.15, 1.1, 1.15, 0.95, 1.0, 1.15, 0.25, 1.1, 0.15, 1.3])

    _nav_btn(_c[0], '🏠 Inicio', 'nav_h_inicio',
             HORIZONTE=='inicio', None, 'inicio', 'inicio')
    _nav_btn(_c[1], '⚡ Corto Plazo', 'nav_h_corto',
             HORIZONTE=='corto', None, 'corto', 'resumen')
    _nav_btn(_c[2], '📈 Largo Plazo', 'nav_h_largo',
             HORIZONTE=='largo', None, 'largo', 'ranking')
    _nav_btn(_c[3], '🔍 Buscador', 'nav_buscador',
             HORIZONTE=='buscador', None, 'buscador', 'buscador')
    _nav_btn(_c[4], '⚖️ Comparar', 'nav_comparador',
             HORIZONTE=='comparador', None, 'comparador', 'comparador')
    _nav_btn(_c[5], '🧮 Optimizar', 'nav_optimizador',
             HORIZONTE=='optimizador', None, 'optimizador', 'optimizador')
    _nav_btn(_c[6], '📐 Promediador', 'nav_promediador',
             HORIZONTE=='promediador', None, 'promediador', 'promediador')
    _nav_btn(_c[7], '🔄 Rotación', 'nav_pares',
             HORIZONTE=='pares', None, 'pares', 'pares')
    _nav_btn(_c[8], '🎲 Opciones', 'nav_opciones',
             HORIZONTE=='opciones', None, 'opciones', 'opciones')
    _nav_btn(_c[9], '🎯 Señales', 'nav_senales',
             HORIZONTE=='senales', None, 'senales', 'senales')

    n_alertas_fin = _contar_alertas_finanzas(supabase, USER_ID)
    _label_cuenta = f'👤 Mi Cuenta 🔴{n_alertas_fin}' if n_alertas_fin > 0 else '👤 Mi Cuenta'
    _label_finanzas = (
        f'💰 Finanzas ({n_alertas_fin} alerta{"s" if n_alertas_fin != 1 else ""})'
        if n_alertas_fin > 0 else '💰 Finanzas'
    )

    with _c[11]:
        with st.container(key='nav_refresh_cont'):
            if st.button('↺ Actualizar', use_container_width=True, key='nav_refresh'):
                _refrescar_cotizaciones()

    with _c[13]:
        with st.container(key='nav_cuenta_cont'):
            with st.popover(_label_cuenta, use_container_width=True):
                st.markdown(
                    '<div style="font-size:11px;color:#6b7d9a;padding:2px 4px 8px 4px">'
                    'Gestioná tu cuenta</div>',
                    unsafe_allow_html=True
                )
                if st.button(_label_finanzas, use_container_width=True, key='menu_finanzas'):
                    st.session_state['nav_horizonte'] = 'finanzas'
                    st.session_state['nav_modulo'] = 'finanzas'
                    st.rerun()
                if st.button('📊 Calendario Económico', use_container_width=True, key='menu_calendario'):
                    st.session_state['nav_horizonte'] = 'calendario'
                    st.session_state['nav_modulo'] = 'calendario'
                    st.rerun()
                if st.button('📰 Noticias', use_container_width=True, key='menu_noticias'):
                    st.session_state['nav_horizonte'] = 'noticias'
                    st.session_state['nav_modulo'] = 'noticias'
                    st.rerun()

                if ES_ADMIN:
                    st.markdown('<hr style="margin:6px 0;border-color:#21262d">', unsafe_allow_html=True)
                    if st.button('🛠️ Panel de Pagos', use_container_width=True, key='menu_admin_pagos'):
                        st.session_state['nav_horizonte'] = 'admin_pagos'
                        st.session_state['nav_modulo'] = 'admin_pagos'
                        st.rerun()

                st.markdown(
                    '<hr style="margin:6px 0;border-color:#21262d">',
                    unsafe_allow_html=True
                )
                if st.button('🚪 Cerrar sesión', use_container_width=True, key='btn_logout'):
                    auth_client.auth.sign_out()
                    cookies.remove("sb_refresh_token")
                    del st.session_state["usuario"]
                    st.rerun()

# ── Submenú como lista desplegable (no empuja los botones principales) ──
def _cambiar_submodulo_corto():
    st.session_state['nav_modulo'] = _OPCIONES_SUB_CORTO[st.session_state['nav_sub_corto']]

def _cambiar_submodulo_largo():
    st.session_state['nav_modulo'] = _OPCIONES_SUB_LARGO[st.session_state['nav_sub_largo']]

if HORIZONTE == 'corto':
    _OPCIONES_SUB_CORTO = {
        '🎯 Resumen Top-Down': 'resumen', '💱 Forex': 'forex', '🌍 Países': 'paises',
        '📊 Sectores': 'sectores', '🧩 Sub-sectores': 'subsectores',
        '🛢️ Mercados': 'mercados', '📈 Acciones': 'acciones',
    }
    _label_sub_actual = next(
        (k for k, v in _OPCIONES_SUB_CORTO.items()
         if v == MODULO or (MODULO == 'topdown' and v == 'resumen')),
        '🎯 Resumen Top-Down'
    )
    # Con on_change, si el cambio vino de ESTE selectbox, MODULO ya llega
    # actualizado acá arriba y este if no hace nada. Solo entra en juego
    # cuando el módulo cambió por otra vía (botón, chip, onboarding).
    if st.session_state.get('nav_sub_corto') != _label_sub_actual:
        st.session_state['nav_sub_corto'] = _label_sub_actual
    st.selectbox('Módulo de Corto Plazo', list(_OPCIONES_SUB_CORTO.keys()),
                  key='nav_sub_corto', on_change=_cambiar_submodulo_corto)

elif HORIZONTE == 'largo':
    _OPCIONES_SUB_LARGO = {
        '📋 Ranking': 'ranking', '🔄 Reversión': 'reversion', '🏭 Industria': 'industria',
        '🔍 Ticker': 'ticker', '📊 Fundamental': 'fundamental',
        '📐 Top-Down Cuantitativo': 'tdc',
    }
    _label_sub_actual_l = next((k for k, v in _OPCIONES_SUB_LARGO.items() if v == MODULO), '📋 Ranking')
    if st.session_state.get('nav_sub_largo') != _label_sub_actual_l:
        st.session_state['nav_sub_largo'] = _label_sub_actual_l
    st.selectbox('Módulo de Largo Plazo', list(_OPCIONES_SUB_LARGO.keys()),
                  key='nav_sub_largo', on_change=_cambiar_submodulo_largo)

st.markdown("""
<style>
.st-key-nav_refresh_cont button {
    background: transparent !important;
    color: var(--verde-monster-dim) !important;
    border-color: #21262d !important;
    font-size: 12px !important;
}
.st-key-nav_refresh_cont button:hover {
    background: #11150f !important;
    color: var(--verde-monster) !important;
    border-color: var(--verde-monster) !important;
}
.st-key-nav_logout_cont button {
    background: transparent !important;
    color: #f0883e !important;
    border-color: #21262d !important;
    font-size: 12px !important;
}
.st-key-nav_logout_cont button:hover {
    background: #201008 !important;
    color: #f85149 !important;
    border-color: #f85149 !important;
}

/* ── Nav alternativo para pantallas chicas (celular) ──
   En desktop se ve la fila de botones; en mobile esa fila se
   esconde y aparecen 2 selectbox en su lugar, mucho más usables
   con el dedo que botones angostos en una fila scrolleable. */
.st-key-nav_mobile_wrap { display: none; }
@media (max-width: 768px) {
  .st-key-nav_pills_wrap { display: none !important; }
  .st-key-nav_mobile_wrap { display: block !important; }
}
</style>
""", unsafe_allow_html=True)

def _mobile_cambiar_horizonte():
    nuevo_h = _OPCIONES_HORIZONTE_MOBILE[st.session_state['nav_mobile_h']]
    st.session_state['nav_horizonte'] = nuevo_h
    if nuevo_h in _OPCIONES_MODULO_MOBILE:
        st.session_state['nav_modulo'] = list(_OPCIONES_MODULO_MOBILE[nuevo_h].values())[0]
    else:
        st.session_state['nav_modulo'] = nuevo_h
    st.session_state.pop('nav_mobile_m', None)

def _mobile_cambiar_modulo():
    h_actual = st.session_state['nav_horizonte']
    st.session_state['nav_modulo'] = _OPCIONES_MODULO_MOBILE[h_actual][st.session_state['nav_mobile_m']]

with st.container(key='nav_mobile_wrap'):
    _OPCIONES_HORIZONTE_MOBILE = {
        '🏠 Inicio': 'inicio', '⚡ Corto Plazo': 'corto', '📈 Largo Plazo': 'largo',
        '🔍 Buscador': 'buscador', '⚖️ Comparar': 'comparador',
        '🧮 Optimizar': 'optimizador', '🔗 Pares': 'pares', '🎲 Opciones': 'opciones',
        '📐 Promediador': 'promediador', '🎯 Señales': 'senales',
        '👤 Mi Cuenta': 'finanzas', '📊 Calendario': 'calendario', '📰 Noticias': 'noticias',
    }
    if ES_ADMIN:
        _OPCIONES_HORIZONTE_MOBILE['🛠️ Panel de Pagos'] = 'admin_pagos'
    _OPCIONES_MODULO_MOBILE = {
        'corto': {'🎯 Resumen Top-Down': 'resumen', '💱 Forex': 'forex', '🌍 Países': 'paises',
                  '📊 Sectores': 'sectores', '🧩 Sub-sectores': 'subsectores',
                  '🛢️ Mercados': 'mercados', '📈 Acciones': 'acciones'},
        'largo': {'📋 Ranking': 'ranking', '🔄 Reversión': 'reversion', '🏭 Industria': 'industria',
                  '🔍 Ticker': 'ticker', '📊 Fundamental': 'fundamental',
                  '📐 Top-Down Cuantitativo': 'tdc'},
    }
    _label_h_actual = next((k for k, v in _OPCIONES_HORIZONTE_MOBILE.items() if v == HORIZONTE), '🏠 Inicio')
    if st.session_state.get('nav_mobile_h') != _label_h_actual:
        st.session_state['nav_mobile_h'] = _label_h_actual
    _mc1, _mc2 = st.columns(2)
    with _mc1:
        st.selectbox('Sección', list(_OPCIONES_HORIZONTE_MOBILE.keys()),
                      key='nav_mobile_h', label_visibility='collapsed',
                      on_change=_mobile_cambiar_horizonte)
    with _mc2:
        if HORIZONTE in _OPCIONES_MODULO_MOBILE:
            _mods_disp = _OPCIONES_MODULO_MOBILE[HORIZONTE]
            _label_m_actual = next((k for k, v in _mods_disp.items() if v == MODULO), list(_mods_disp.keys())[0])
            if st.session_state.get('nav_mobile_m') != _label_m_actual:
                st.session_state['nav_mobile_m'] = _label_m_actual
            st.selectbox('Módulo', list(_mods_disp.keys()),
                          key='nav_mobile_m', label_visibility='collapsed',
                          on_change=_mobile_cambiar_modulo)
        elif HORIZONTE == 'finanzas':
            st.markdown(
                '<div style="font-size:11px;color:#6b7d9a;padding-top:8px;text-align:center">'
                '💰 Finanzas Personales</div>',
                unsafe_allow_html=True
            )
        else:
            st.write('')

    if n_alertas_fin > 0:
        st.caption(f'🔔 {n_alertas_fin} alerta(s) en Finanzas Personales')

    _mc3, _mc4 = st.columns(2)
    with _mc3:
        if st.button('↺ Actualizar', use_container_width=True, key='nav_refresh_mobile'):
            _refrescar_cotizaciones()
    with _mc4:
        if st.button('🚪 Cerrar sesión', use_container_width=True, key='btn_logout_mobile'):
            auth_client.auth.sign_out()
            cookies.remove("sb_refresh_token")
            del st.session_state["usuario"]
            st.rerun()

st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)


with st.expander('❓ Glosario de términos cuantitativos y fundamentales', expanded=False):
    st.markdown(
        '<div style="font-size:11px;color:#6b7d9a;margin-bottom:8px">'
        'Elegí un término para ver su definición y la tabla de niveles/rangos que usa la app.</div>',
        unsafe_allow_html=True
    )
    _termino_sel = st.selectbox(
        'Término', sorted(GLOSARIO.keys()), key='glosario_termino_sel', label_visibility='collapsed'
    )
    st.markdown(
        f"<div style='margin:6px 0 14px 0'><b style='color:#6CC24A;font-size:14px'>{_termino_sel}</b><br>"
        f"<span style='color:#f5f7fa;font-size:13px;line-height:1.6'>{GLOSARIO.get(_termino_sel,'')}</span></div>",
        unsafe_allow_html=True
    )

    _niveles = GLOSARIO_NIVELES.get(_termino_sel)
    if _niveles:
        df_gloss = pd.DataFrame(_niveles, columns=['Rango / Condición', 'Nivel', 'Interpretación'])

        def _color_nivel_gloss(val):
            c = _COLOR_NIVEL_MAP.get(val, '#e6edf3')
            return f'color:{c};font-weight:700'

        _map_g = 'map' if hasattr(df_gloss.style, 'map') else 'applymap'
        styled_gloss = (df_gloss.style
            .pipe(lambda s: getattr(s, _map_g)(_color_nivel_gloss, subset=['Nivel']))
            .set_properties(**{'background-color': '#0d1117', 'color': '#e6edf3', 'border': '1px solid #21262d'})
            .set_table_styles([
                {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', '#e6edf3'),
                    ('font-weight', '700'), ('text-align', 'center'),
                    ('border-bottom', '2px solid #3a7bd5'), ('font-size', '11px')]},
                {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11.5px')]},
            ])
        )
        st.dataframe(styled_gloss, use_container_width=True, hide_index=True,
                     height=min(320, len(df_gloss) * 40 + 45))
    else:
        st.info('Este término es informativo y no tiene niveles cuantitativos fijos (se interpreta en contexto).')


HORIZONTE = st.session_state['nav_horizonte']
MODULO    = st.session_state['nav_modulo']


# ==============================================================
#  PAGE HEADER
# ==============================================================


titulos = {
    'inicio':    ('Cotizaciones del Día', '📊', 'Precios y variación diaria — índices, sectores, mercados, forex y acciones'),
    'buscador':  ('Buscador Universal', '🔍', 'Análisis completo por ticker — corto y largo plazo'),
    'comparador':('Comparador de Activos', '⚖️', 'Comparación lado a lado — rendimiento y scores cuantitativos'),
    'optimizador': ('Optimizador de Cartera', '🧮', 'Monte Carlo · Frontera eficiente · Comparación vs benchmark'),
    'pares': ('Rotación y Pares', '🔄', 'Portfolio Rotation · Sector Rotation · Scanner de Pares (Mean Reversion)'),
    'forex':     ('Análisis Forex', '💱', 'Pares de divisas — ranking y oportunidades de acumulación'),
    'paises':    ('Países / Índices Globales', '🌍', 'Índices nacionales y regionales — flujo de capital macro'),
    'sectores':  ('Sectores S&P500', '📊', '11 sectores GICS — rotación y momentum'),
    'subsectores': ('Sub-sectores / Temáticos', '🧩', 'ETFs temáticos y sub-industrias — rotación granular'),
    'mercados':  ('Commodities · Metales · Cripto', '🛢️', 'Mercados reales globales — energía, metales, agro, digital'),
    'acciones':  ('Acciones por Industria', '📈', 'Ranking por sector — oportunidades de corto plazo'),
    'topdown':   ('Resumen Top-Down', '🎯', 'Vista ejecutiva macro → sector → acción'),
    'ranking':   ('Ranking Cuantitativo', '📋', 'Global Score · Trend Score · MR Score · Risk Score'),
    'reversion': ('Candidatos a Reversión', '🔄', 'Sobreventa estadística — Z-Score · Bollinger · RSI < 35'),
    'industria': ('Análisis por Industria', '🏭', 'Comparativa cuantitativa sectorial con interpretación'),
    'ticker':      ('Análisis Individual', '🔍', 'Detalle cuantitativo completo para un ticker específico'),
    'resumen':     ('Resumen Top-Down', '🎯', 'Vista ejecutiva multi-nivel — macro a micro'),
    'fundamental': ('Análisis Fundamental', '📊', 'Ratios financieros · Benchmarks por sector · Señales de valuación'),
    'tdc': ('Top-Down Cuantitativo (Mediano/Largo Plazo)', '📐', 'Percentil histórico MP/LP — modelo Top-Down original'),
    'opciones': ('Valuación de Opciones', '🎲', 'Black-Scholes / Binomial · Catálogo de estrategias · Griegas · Payoff'),
    'senales': ('Señales de Trading', '🎯', 'Publicación de señales y simulador de capital'),
    'finanzas': ('Finanzas Personales', '💰', 'Ingresos, gastos, deudas, inversiones y objetivos de ahorro'),
    'promediador': ('Promediador + Stop Loss', '📐', 'Precio promedio, tendencia y gestión de riesgo con apalancamiento'),
    'calendario': ('Calendario Económico', '📆', 'Eventos económicos relevantes y su impacto en mercados'),
    'noticias': ('Noticias', '📰', 'Noticias y análisis de mercado'),
    'admin_pagos': ('Panel de Aprobación de Pagos', '🛠️', 'Revisión y aprobación de solicitudes de pago manual'),
}
titulo_h, icono_h, subtitulo_h = titulos.get(MODULO, ('Analizador', '📡', ''))
# st.caption(f'🔧 DEBUG — HORIZONTE={HORIZONTE} · MODULO={MODULO}')


badge_map = {
    'inicio':     ('#e3b341', 'rgba(227,179,65,0.12)',  'INICIO'),
    'corto':      ('#f0883e', 'rgba(240,136,62,0.12)', 'CORTO PLAZO'),
    'largo':      ('#3fb950', 'rgba(63,185,80,0.10)',  'LARGO PLAZO'),
    'buscador':   ('#3a7bd5', 'rgba(58,123,213,0.12)', 'BÚSQUEDA'),
    'comparador': ('#6CC24A', 'rgba(108,194,74,0.12)', 'COMPARADOR'),
    'optimizador':('#bc8cff', 'rgba(188,140,255,0.12)','OPTIMIZADOR'),
    'pares': ('#79c0ff', 'rgba(121,192,255,0.12)', 'ROTACIÓN'),
    'opciones': ('#bc5cff', 'rgba(188,92,255,0.12)', 'OPCIONES'),
    'senales': ('#ff6ec7', 'rgba(255,110,199,0.12)', 'SEÑALES'),
    'finanzas': ('#6CC24A', 'rgba(108,194,74,0.12)', 'FINANZAS'),
    'promediador': ('#6CC24A', 'rgba(108,194,74,0.12)', 'PROMEDIADOR'),
    'calendario': ('#79c0ff', 'rgba(121,192,255,0.12)', 'CALENDARIO'),
    'noticias': ('#3a7bd5', 'rgba(58,123,213,0.12)', 'NOTICIAS'),
    'admin_pagos': ('#f0883e', 'rgba(240,136,62,0.12)', 'ADMIN'),
}
badge_color, badge_bg, badge_txt = badge_map.get(HORIZONTE, ('#3a7bd5','rgba(58,123,213,0.12)',''))


st.markdown(f"""
<div class="page-header">
  <div style="display:flex;flex-direction:column;align-items:center;text-align:center;gap:6px">
    <div style="display:flex;align-items:center;justify-content:center;gap:12px">
      <span style="font-size:24px;line-height:1">{icono_h}</span>
      <span class="page-title">{titulo_h}</span>
      <span style="padding:3px 10px;border-radius:20px;font-size:9px;font-weight:700;
        letter-spacing:1px;text-transform:uppercase;background:{badge_bg};
        border:1px solid {badge_color};color:{badge_color}">{badge_txt}</span>
    </div>
    <div class="page-sub">{subtitulo_h}</div>
    <div style="font-size:12px;color:#f5f7fa;font-family:'JetBrains Mono',monospace;margin-top:4px">
      {ahora_ar().strftime('%d/%m/%Y · %H:%M')} &nbsp;·&nbsp
    </div>
  </div>
</div>
""", unsafe_allow_html=True)



# ==============================================================
#  RENDERIZADO DE MÓDULOS
# ==============================================================


if MODULO == 'inicio':
    modulo_inicio()


elif MODULO == 'buscador':
    modulo_buscador()


elif MODULO == 'comparador':
    modulo_comparador()


elif MODULO == 'optimizador':
    modulo_optimizador()


elif MODULO == 'pares':
    tab_analisis_tecnico, tab_rot_pares, tab_coint, tab_vol = st.tabs([
        '📐 Análisis Técnico', '🔗 Pares (Mean Reversion)', '📐 Cointegración (Engle-Granger)', '🌪️ Volatilidad (VIX)',
    ])
    with tab_analisis_tecnico:
        modulo_analisis_tecnico(PLOTLY_CONFIG=PLOTLY_CONFIG)
    with tab_rot_pares:
        modulo_scanner_pares()
    with tab_coint:
        modulo_pares_cointegracion(
            descargar_datos=descargar_datos,
            get_close_series=get_close_series,
            fmt_precio=fmt_precio,
            kpi_cards_4=kpi_cards_4,
            chips_navegacion=chips_navegacion,
            PLOTLY_CONFIG=PLOTLY_CONFIG,
            selector_ticker_autocomplete=selector_ticker_autocomplete,
        )
    with tab_vol:
        modulo_volatilidad(PLOTLY_CONFIG=PLOTLY_CONFIG)
elif MODULO == 'opciones':
    modulo_opciones()

elif MODULO == 'senales':
    render_senales_trading(supabase, USER_ID, st.session_state["usuario"].email)

elif MODULO == 'calendario':
       render_calendario_economico(supabase, USER_ID, st.session_state["usuario"].email)

elif MODULO == 'noticias':
       render_noticias(supabase, USER_ID, st.session_state["usuario"].email)

elif MODULO == 'finanzas':
    render_finanzas_personales(supabase, USER_ID)

elif MODULO == 'promediador':                 # ← agregar
    modulo_promediador(
        analizar_largo=analizar_largo,
        descargar_datos=descargar_datos,
        get_close_series=get_close_series,
        calcular_atr=calcular_atr,
        scores_corto=scores_corto,
        señal_accion_corto=señal_accion_corto,
    )
    
elif MODULO == 'admin_pagos':
    if ES_ADMIN:
        panel_admin_pagos(supabase, USER_ID)
        panel_gestion_cuentas(supabase, USER_ID)
    else:
        st.warning('No tenés permisos de administrador.')

elif HORIZONTE == 'corto':


    if MODULO in ('resumen', 'topdown'):
        if not st.session_state.get('td_loaded'):
            st.markdown("""
            <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
                 border:1px solid #21262d; border-top:2px solid #6CC24A;
                 border-radius:14px; padding:30px 34px; margin-bottom:22px;">
              <div style="font-size:19px;font-weight:700;color:#e6edf3;margin-bottom:6px">
                👋 ¿Qué querés hacer hoy?
              </div>
              <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
                Este es un analizador cuantitativo de mercados: combina scores estadísticos de corto plazo,
                un modelo cuantitativo de largo plazo (tendencia, reversión y riesgo), ratios fundamentales
                y un optimizador de cartera por Monte Carlo, para acciones, ETFs, forex, commodities y cripto.
                Elegí por dónde arrancar:
              </div>
            </div>
            """, unsafe_allow_html=True)

            cc1, cc2, cc3, cc4, cc5 = st.columns(5)
            with cc1:
                if st.button('🔍 Analizar un ticker', use_container_width=True, key='onb_buscador'):
                    st.session_state['nav_horizonte'] = 'buscador'
                    st.session_state['nav_modulo'] = 'buscador'
                    st.rerun()
            with cc2:
                if st.button('⚖️ Comparar activos', use_container_width=True, key='onb_comparador'):
                    st.session_state['nav_horizonte'] = 'comparador'
                    st.session_state['nav_modulo'] = 'comparador'
                    st.rerun()
            with cc3:
                if st.button('🎯 Ver oportunidades macro', use_container_width=True, key='onb_topdown'):
                    st.session_state['td_loaded'] = True
                    st.rerun()
            with cc4:
                if st.button('📋 Ranking de largo plazo', use_container_width=True, key='onb_ranking'):
                    st.session_state['nav_horizonte'] = 'largo'
                    st.session_state['nav_modulo'] = 'ranking'
                    st.rerun()
            with cc5:
                if st.button('🧮 Optimizar cartera', use_container_width=True, key='onb_optimizador'):
                    st.session_state['nav_horizonte'] = 'optimizador'
                    st.session_state['nav_modulo'] = 'optimizador'
                    st.rerun()

            st.markdown('<div style="height:6px"></div>', unsafe_allow_html=True)

        st.markdown('<div class="info-banner">Vista ejecutiva Top-Down. Presioná <b>Cargar</b> para analizar todos los niveles.</div>', unsafe_allow_html=True)
        if st.button('▶ Cargar resumen completo', key='btn_td'):
            st.session_state['td_loaded'] = True
        if st.session_state.get('td_loaded'):
            prog = st.progress(0, text='Cargando países...')
            d_p = cargar_paises_corto(); prog.progress(25, 'Sectores...')
            d_s = cargar_sectores_corto(); prog.progress(50, 'Sub-sectores...')
            d_ss = cargar_subsectores_corto(); prog.progress(75, 'Mercados...')
            d_m = cargar_mercados_corto(); prog.progress(100, '✅ Listo'); prog.empty()
            fuentes = [(l,d,c) for l,d,c in [
                ('Países', d_p, '#3a7bd5'), ('Sectores', d_s, '#3fb950'),
                ('Sub-sectores', d_ss, '#79c0ff'), ('Mercados', d_m, '#f0883e'),
            ] if d]
            if fuentes:
                st.plotly_chart(fig_topdown(fuentes), use_container_width=True, config=PLOTLY_CONFIG, key='topdown_fig')
        else:
            st.markdown("""
            <div style='background:#0d1117;border:1px dashed #21262d;border-radius:10px;padding:40px;text-align:center'>
              <div style='font-size:40px;margin-bottom:12px'>🎯</div>
              <div style='color:#e6edf3;font-size:15px;font-weight:600;margin-bottom:6px'>Resumen Top-Down</div>
              <div style='color:#6b7d9a;font-size:12px'>Presioná el botón de arriba para cargar todos los niveles.</div>
            </div>
            """, unsafe_allow_html=True)


    elif MODULO == 'forex':
        grupos_disp = list(dict.fromkeys(v[1] for v in FOREX.values()))
        grupos_sel = st.multiselect('Grupos FX', grupos_disp, default=grupos_disp, key='fx_grupos')
        with st.spinner('Descargando Forex...'):
            datos_f = {n:d for n,d in cargar_forex_corto().items() if d['grupo'] in grupos_sel}
        if not datos_f: st.error('Sin datos.'); st.stop()
        badge_actualizacion('forex')
        aviso_fallidos('forex', etiqueta='pares de Forex')
        tab1, tab2, tab3, tab4 = st.tabs(['📊 Scores','📈 Momentum','🗺️ Cuadrante','📋 Ranking'])
        with tab1:
            grupos_en = [g for g in grupos_disp if g in grupos_sel and any(d['grupo']==g for d in datos_f.values())]
            for i in range(0, len(grupos_en), 2):
                cols = st.columns(2)
                for j, grupo in enumerate(grupos_en[i:i+2]):
                    items = sorted([(n,d) for n,d in datos_f.items() if d['grupo']==grupo], key=lambda x: x[1]['sa'], reverse=True)
                    if not items: continue
                    fig = fig_barras_h(items, grupo, COLORES_GRUPO_FX.get(grupo, C_MONSTER))
                    with cols[j]: st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG, key=f'fx_barras_{grupo}')
        with tab2:
            fig2 = fig_momentum(sorted(datos_f.items(), key=lambda x: x[1]['ret_5d'], reverse=True))
            st.plotly_chart(fig2, use_container_width=True, config=PLOTLY_CONFIG, key='fx_momentum')
        with tab3:
            c_m, _ = st.columns([2,1])
            with c_m:
                fig3 = fig_cuadrante(datos_f, COLORES_GRUPO_FX, 'Mapa Oportunidades Forex')
                st.plotly_chart(fig3, use_container_width=True, config=PLOTLY_CONFIG, key='fx_cuadrante')
        with tab4:
            tabla_corto(datos_f)


    elif MODULO == 'paises':
        with st.spinner('Descargando países...'):
            datos_p = cargar_paises_corto()
        if not datos_p: st.error('Sin datos.'); st.stop()
        badge_actualizacion('paises')
        aviso_fallidos('paises', etiqueta='países/índices')
        tab1, tab2, tab3, tab4 = st.tabs(['📊 Scores','📈 Momentum','🗺️ Cuadrante','📋 Ranking'])
        with tab1:
            regiones = list(dict.fromkeys(d['region'] for d in datos_p.values()))
            for i in range(0, len(regiones), 2):
                cols = st.columns(2)
                for j, region in enumerate(regiones[i:i+2]):
                    items = sorted([(n,d) for n,d in datos_p.items() if d['region']==region], key=lambda x: x[1]['sa'], reverse=True)
                    if not items: continue
                    fig = fig_barras_h(items, region, COLORES_REGION.get(region, C_MONSTER))
                    with cols[j]: st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG, key=f'pa_barras_{region}')
        with tab2:
            fig2 = fig_momentum(sorted(datos_p.items(), key=lambda x: x[1]['ret_5d'], reverse=True))
            st.plotly_chart(fig2, use_container_width=True, config=PLOTLY_CONFIG, key='pa_momentum')
        with tab3:
            c_m, _ = st.columns([2,1])
            with c_m:
                fig3 = fig_cuadrante(datos_p, COLORES_REGION, 'Mapa Oportunidades Países')
                st.plotly_chart(fig3, use_container_width=True, config=PLOTLY_CONFIG, key='pa_cuadrante')
        with tab4:
            tabla_corto(datos_p)


    elif MODULO == 'sectores':
        with st.spinner('Descargando sectores...'):
            datos_s = cargar_sectores_corto()
        if not datos_s: st.error('Sin datos.'); st.stop()
        badge_actualizacion('sectores')
        aviso_fallidos('sectores', etiqueta='sectores')
        tab1, tab2, tab3, tab4 = st.tabs(['📊 Scores','📈 Momentum','🗺️ Cuadrante','📋 Ranking'])
        with tab1:
            items_ord = sorted(datos_s.items(), key=lambda x: x[1]['sa'], reverse=True)
            fig = fig_barras_h(items_ord, 'S&P500 — Sectores')
            st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG, key='sec_barras')
        with tab2:
            fig2 = fig_momentum(sorted(datos_s.items(), key=lambda x: x[1]['ret_5d'], reverse=True))
            st.plotly_chart(fig2, use_container_width=True, config=PLOTLY_CONFIG, key='sec_momentum')
        with tab3:
            c_m, _ = st.columns([2,1])
            with c_m:
                fig3 = fig_cuadrante(datos_s, None, 'Mapa Oportunidades Sectores')
                st.plotly_chart(fig3, use_container_width=True, config=PLOTLY_CONFIG, key='sec_cuadrante')
        with tab4:
            tabla_corto(datos_s)
            
    elif MODULO == 'subsectores':
        with st.spinner('Descargando sub-sectores...'):
            datos_ss = cargar_subsectores_corto()
        if not datos_ss: st.error('Sin datos.'); st.stop()
        badge_actualizacion('subsectores')
        aviso_fallidos('subsectores', etiqueta='sub-sectores')
        tab1, tab2, tab3, tab4 = st.tabs(['📊 Scores','📈 Momentum','🗺️ Cuadrante','📋 Ranking'])
        with tab1:
            grupos_en = sorted(set(d.get('grupo', 'Otros') for d in datos_ss.values()))
            for i in range(0, len(grupos_en), 2):
                cols = st.columns(2)
                for j, grupo in enumerate(grupos_en[i:i+2]):
                    items = sorted([(n, d) for n, d in datos_ss.items() if d.get('grupo') == grupo],
                                    key=lambda x: x[1]['sa'], reverse=True)
                    if not items: continue
                    fig = fig_barras_h(items, grupo, COLORES_SECTOR_PADRE.get(grupo, C_MONSTER))
                    with cols[j]:
                        st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG, key=f'subsec_barras_{grupo}')
        with tab2:
            fig2 = fig_momentum(sorted(datos_ss.items(), key=lambda x: x[1]['ret_5d'], reverse=True))
            st.plotly_chart(fig2, use_container_width=True, config=PLOTLY_CONFIG, key='subsec_momentum')
        with tab3:
            c_m, _ = st.columns([2,1])
            with c_m:
                fig3 = fig_cuadrante(datos_ss, COLORES_SECTOR_PADRE, 'Mapa Oportunidades Sub-sectores')
                st.plotly_chart(fig3, use_container_width=True, config=PLOTLY_CONFIG, key='subsec_cuadrante')
        with tab4:
            tabla_corto(datos_ss, key_suffix='subsec')

    elif MODULO == 'mercados':
        with st.spinner('Descargando commodities...'):
            datos_m = cargar_mercados_corto()
        if not datos_m: st.error('Sin datos.'); st.stop()
        badge_actualizacion('mercados')
        aviso_fallidos('mercados', etiqueta='mercados')
        tab1, tab2, tab3, tab4 = st.tabs(['📊 Por categoría','📈 Momentum','🗺️ Cuadrante','📋 Ranking'])
        with tab1:
            cats = list(dict.fromkeys(d['cat'] for d in datos_m.values()))
            for i in range(0, len(cats), 2):
                cols = st.columns(2)
                for j, cat in enumerate(cats[i:i+2]):
                    items = sorted([(n,d) for n,d in datos_m.items() if d['cat']==cat], key=lambda x: x[1]['sa'], reverse=True)
                    if not items: continue
                    fig = fig_barras_h(items, cat)
                    with cols[j]: st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG, key=f'merc_barras_{cat}')
        with tab2:
            fig2 = fig_momentum(sorted(datos_m.items(), key=lambda x: x[1]['ret_5d'], reverse=True))
            st.plotly_chart(fig2, use_container_width=True, config=PLOTLY_CONFIG, key='merc_momentum')
        with tab3:
            c_m, _ = st.columns([2,1])
            with c_m:
                fig3 = fig_cuadrante(datos_m, None, 'Mapa Mercados Reales')
                st.plotly_chart(fig3, use_container_width=True, config=PLOTLY_CONFIG, key='merc_cuadrante')
        with tab4:
            tabla_corto(datos_m)


    elif MODULO == 'acciones':
        ind_disp_c = list(ACCIONES_POR_INDUSTRIA.keys())
        ind_sel_c  = st.multiselect('Industrias', ind_disp_c, default=st.session_state['nav_ind_sel_corto'], key='acc_ind_sel')
        st.session_state['nav_ind_sel_corto'] = ind_sel_c
        if not ind_sel_c:
            st.info('Seleccioná al menos una industria.')
            st.stop()
        with st.spinner(f'Analizando {len(ind_sel_c)} industrias en paralelo...'):
            datos_acc_c = cargar_acciones_corto(tuple(ind_sel_c))
        datos_acc_c = {ind: tks for ind, tks in datos_acc_c.items() if tks}
        if not datos_acc_c: st.error('Sin datos.'); st.stop()
        badge_actualizacion('acciones')
        aviso_fallidos('acciones', etiqueta='acciones')
        todas_c = {tk: d for ind, tks in datos_acc_c.items() for tk, d in tks.items()}
        tab1, tab2, tab3 = st.tabs(['📊 Por industria','🗺️ Cuadrante','📋 Ranking'])
        with tab1:
            for industria, tickers in datos_acc_c.items():
                if not tickers: continue
                st.markdown(f'<div class="sec-title">📂 {industria}</div>', unsafe_allow_html=True)
                items_ord = sorted(tickers.items(), key=lambda x: x[1]['sa'], reverse=True)
                fig = fig_barras_h(items_ord, industria)
                st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG, key=f'acc_barras_{industria}')
        with tab2:
            c_m, _ = st.columns([2,1])
            with c_m:
                fig3 = fig_cuadrante(todas_c, None, 'Mapa Oportunidades Acciones')
                st.plotly_chart(fig3, use_container_width=True, config=PLOTLY_CONFIG, key='acc_cuadrante')
        with tab3:
            filas = []
            for industria, tickers in datos_acc_c.items():
                for tk, d in sorted(tickers.items(), key=lambda x: x[1]['sa'], reverse=True):
                    filas.append({'Industria': industria, 'Ticker': tk,
                        'Acum': round(d['sa'],1), 'Antic': round(d['sn'],1), 'Sent': round(d['ss'],1),
                        'RSI': round(d.get('rsi',0),1), 'Ret 5d %': round(d.get('ret_5d',0),2),
                        'Ret 10d %': round(d.get('ret_10d',0),2),
                        'Precio': fmt_precio(d.get('precio',0)), 'Señal': d['accion']})
            df_acc = pd.DataFrame(filas).sort_values('Acum', ascending=False)


            fa1, fa2 = st.columns([2,2])
            with fa1:
                señ_u2 = ['Todas'] + sorted(df_acc['Señal'].unique().tolist())
                señ_s2 = st.selectbox('Señal', señ_u2, key='acc_corto_f')
            with fa2:
                ind_u2 = ['Todas'] + sorted(df_acc['Industria'].unique().tolist())
                ind_s2 = st.selectbox('Industria', ind_u2, key='acc_corto_ind')


            fb1, fb2, fb3 = st.columns(3)
            with fb1:
                acum_r = st.slider('Rango Acum', 0, 100, (0,100), 1, key='acc_corto_acum')
            with fb2:
                antic_r = st.slider('Rango Antic', 0, 100, (0,100), 1, key='acc_corto_antic')
            with fb3:
                sent_r = st.slider('Rango Sent', 0, 100, (0,100), 1, key='acc_corto_sent')


            fb4, fb5, fb6 = st.columns(3)
            with fb4:
                rsi_r = st.slider('Rango RSI', 0, 100, (0,100), 1, key='acc_corto_rsi')
            with fb5:
                ret5_r = st.slider('Rango Ret 5d %', -30, 30, (-30,30), 1, key='acc_corto_ret5')
            with fb6:
                ret10_r = st.slider('Rango Ret 10d %', -30, 30, (-30,30), 1, key='acc_corto_ret10')


            df_show_a = df_acc.copy()
            if señ_s2 != 'Todas': df_show_a = df_show_a[df_show_a['Señal']==señ_s2]
            if ind_s2 != 'Todas': df_show_a = df_show_a[df_show_a['Industria']==ind_s2]
            df_show_a = df_show_a[df_show_a['Acum'].between(*acum_r) & df_show_a['Antic'].between(*antic_r)
                                   & df_show_a['Sent'].between(*sent_r) & df_show_a['RSI'].between(*rsi_r)
                                   & df_show_a['Ret 5d %'].between(*ret5_r) & df_show_a['Ret 10d %'].between(*ret10_r)]


            styled = _apply_score_style(df_show_a, ['Acum','Antic','Sent'], ['Ret 5d %','Ret 10d %'])
            st.dataframe(styled, use_container_width=True, height=min(700, max(200, len(df_show_a)*32+45)))
            st.caption(f'{len(df_show_a)} activos mostrados de {len(df_acc)} totales')

            chips_navegacion(df_show_a['Ticker'].tolist(), 'acc_corto')


elif HORIZONTE == 'largo':
    if MODULO in ('fundamental', 'tdc'):
        pass  # handled by modulo_fundamental() / modulo_topdown_cuantitativo() below
    else:
        ind_disp = list(ACCIONES_POR_INDUSTRIA.keys())
        ind_sel  = st.multiselect('Industrias a analizar (2 años de historia)', ind_disp,
                                   default=st.session_state['nav_ind_sel_largo'], key='largo_ind_sel')
        st.session_state['nav_ind_sel_largo'] = ind_sel


        if not ind_sel:
            st.info('Seleccioná al menos una industria.')
            st.stop()


        if MODULO == 'ranking':
            with st.spinner(f'Descargando 2 años de datos — {len(ind_sel)} industrias...'):
                df_res_l = cargar_resultados_largo(tuple(ind_sel))
            if df_res_l.empty: st.error('Sin datos.'); st.stop()
            badge_actualizacion('largo', ttl_min=60)
            aviso_fallidos('largo', etiqueta='tickers (necesitan ≥150 sesiones de historia)')
            n_alc = len(df_res_l[df_res_l['sesgo'].isin(['ALCISTA','MUY ALCISTA'])])
            n_baj = len(df_res_l[df_res_l['sesgo'].isin(['BAJISTA','MUY BAJISTA'])])
            n_rev = int(df_res_l['reversion_signal'].sum())
            kpi_cards_4([
                ('Total analizados', str(len(df_res_l)), f'{len(ind_sel)} industrias · 2 años', '#3a7bd5'),
                ('🟢 Alcistas', str(n_alc), 'Alcista + Muy Alcista', '#3fb950'),
                ('🔴 Bajistas', str(n_baj), 'Bajista + Muy Bajista', '#f85149'),
                ('⚡ Candidatos Reversión', str(n_rev), 'Z<-1 | BajoBB | RSI<35', '#f0e68c'),
            ])
            tab1, tab2, tab3 = st.tabs(['📋 Tabla completa','📊 Distribución','🗺️ Cuadrante largo plazo'])
            with tab1:
                tabla_largo(df_res_l, key_suffix='ranking')
            with tab2:
                st.plotly_chart(fig_distribuciones(df_res_l), use_container_width=True, config=PLOTLY_CONFIG, key='ranking_dist')
            with tab3:
                datos_cuad = {r['ticker']:{'sa':r['trend_score'],'sn':r['mr_score'],'ss':r['risk_score'],'grupo':r['industria']} for _,r in df_res_l.iterrows()}
                c_m, _ = st.columns([2,1])
                with c_m:
                    fig_c = fig_cuadrante(datos_cuad, None, 'Trend Score vs MR Score')
                    st.plotly_chart(fig_c, use_container_width=True, config=PLOTLY_CONFIG, key='ranking_cuadrante')


        elif MODULO == 'reversion':
            with st.spinner('Calculando señales de reversión...'):
                df_res_l = cargar_resultados_largo(tuple(ind_sel))
            if df_res_l.empty: st.error('Sin datos.'); st.stop()
            df_rev_l = df_res_l[df_res_l['reversion_signal']].sort_values('mr_score', ascending=False)
            st.markdown(f'<div class="info-banner">Condiciones: Z &lt; -1.0 | Precio bajo BB inferior | RSI &lt; 35. Total candidatos: <b>{len(df_rev_l)}</b></div>', unsafe_allow_html=True)
            if len(df_rev_l) == 0:
                st.info('No se detectaron candidatos con las condiciones actuales.')
            else:
                cols_rev = ['ticker','industria','precio','zscore','rsi','hurst','lower_bb','ret_anual','vol_anual','sharpe','max_dd','mr_score','risk_score','global_score','reversion_reasons']
                df_rv = df_rev_l[cols_rev].copy()
                df_rv.columns = ['Ticker','Industria','Precio','Z-Score','RSI','Hurst','BB Inf.','Ret %','Vol %','Sharpe','DD%','MR','Risk','Global','Razones']


                fr1, fr2 = st.columns(2)
                with fr1:
                    inds_rev = ['Todas'] + sorted(df_rv['Industria'].unique().tolist())
                    ind_rev_sel = st.selectbox('Industria', inds_rev, key='rev_ind')
                with fr2:
                    f_mr_rev = st.slider('Rango MR', 0, 100, (0,100), 1, key='rev_mr')


                df_rv_f = df_rv.copy()
                if ind_rev_sel != 'Todas': df_rv_f = df_rv_f[df_rv_f['Industria']==ind_rev_sel]
                df_rv_f = df_rv_f[df_rv_f['MR'].between(*f_mr_rev)]


                for col_fmt, fmt in [('Precio',fmt_precio),('BB Inf.',fmt_precio)]:
                    df_rv_f[col_fmt] = df_rv_f[col_fmt].apply(fmt)
                df_rv_f['Z-Score'] = df_rv_f['Z-Score'].apply(lambda x: f'{x:+.2f}')
                df_rv_f['RSI']     = df_rv_f['RSI'].apply(lambda x: f'{x:.1f}')
                df_rv_f['Hurst']   = df_rv_f['Hurst'].apply(lambda x: f'{x:.3f}')
                df_rv_f['Ret %']   = df_rv_f['Ret %'].apply(lambda x: f'{x:+.1f}')
                df_rv_f['Vol %']   = df_rv_f['Vol %'].apply(lambda x: f'{x:.1f}')
                df_rv_f['Sharpe']  = df_rv_f['Sharpe'].apply(lambda x: f'{x:.2f}')
                df_rv_f['DD%']     = df_rv_f['DD%'].apply(lambda x: f'{x:.1f}')
                styled_rev = _apply_score_style(df_rv_f, ['MR','Risk','Global'])
                st.dataframe(styled_rev, use_container_width=True, height=min(700, max(200, len(df_rv_f)*32+45)))
                st.caption(f'{len(df_rv_f)} activos mostrados de {len(df_rv)} totales')
                chips_navegacion(df_rv_f['Ticker'].tolist(), 'reversion')


        elif MODULO == 'industria':
            with st.spinner('Calculando análisis por industria...'):
                df_res_l = cargar_resultados_largo(tuple(ind_sel))
            if df_res_l.empty: st.error('Sin datos.'); st.stop()
            for industria in ind_sel:
                grupo = df_res_l[df_res_l['industria']==industria].sort_values('global_score', ascending=False)
                if grupo.empty: continue
                avg_g = grupo['global_score'].mean()
                best  = grupo.iloc[0]
                n_alc = grupo['sesgo'].isin(['ALCISTA','MUY ALCISTA']).sum()
                st.markdown(f'<div class="sec-title">📂 {industria} &nbsp;·&nbsp; Score prom: {avg_g:.1f} &nbsp;·&nbsp; Alcistas: {n_alc}/{len(grupo)} &nbsp;·&nbsp; Mejor: {best["ticker"]} ({int(best["global_score"])})</div>', unsafe_allow_html=True)
                cols_ind = ['ticker','precio','ret_anual','vol_anual','rsi','hurst','sharpe','max_dd','trend_score','mr_score','risk_score','global_score','sesgo']
                df_ind = grupo[cols_ind].copy()
                df_ind.columns = ['Ticker','Precio','Ret %','Vol %','RSI','Hurst','Sharpe','DD%','Trend','MR','Risk','Global','Sesgo']
                df_ind['Precio'] = df_ind['Precio'].apply(fmt_precio)
                df_ind['Ret %']  = df_ind['Ret %'].apply(lambda x: f'{x:+.1f}')
                df_ind['Vol %']  = df_ind['Vol %'].apply(lambda x: f'{x:.1f}')
                df_ind['RSI']    = df_ind['RSI'].apply(lambda x: f'{x:.1f}')
                df_ind['Hurst']  = df_ind['Hurst'].apply(lambda x: f'{x:.3f}')
                df_ind['Sharpe'] = df_ind['Sharpe'].apply(lambda x: f'{x:.2f}')
                df_ind['DD%']    = df_ind['DD%'].apply(lambda x: f'{x:.1f}')
                def sesgo_st(val):
                    return {'MUY ALCISTA':'color:#3fb950;font-weight:700','ALCISTA':'color:#7ee787;font-weight:700',
                            'NEUTRAL':'color:#e3b341;font-weight:700','BAJISTA':'color:#f0883e;font-weight:700',
                            'MUY BAJISTA':'color:#f85149;font-weight:700'}.get(val,'')
                _map = 'map' if hasattr(df_ind.style,'map') else 'applymap'
                styled_ind = (_apply_score_style(df_ind, ['Trend','MR','Risk','Global'])
                              .pipe(lambda s: getattr(s,_map)(sesgo_st, subset=['Sesgo'])))
                st.dataframe(styled_ind, use_container_width=True, height=min(400, len(df_ind)*32+45))
                with st.expander(f'📝 Interpretaciones — {industria}'):
                    for _, row in grupo.iterrows():
                        r_dict = row.to_dict()
                        interp = interpretar_largo(r_dict)
                        sesgo_class = {'MUY ALCISTA':'sesgo-muy-alc','ALCISTA':'sesgo-alc','NEUTRAL':'sesgo-neu',
                                       'BAJISTA':'sesgo-baj','MUY BAJISTA':'sesgo-muy-baj'}.get(r_dict['sesgo'],'')
                        st.markdown(f"""
                        <div class="interp-card">
                          <div class="interp-header">{r_dict['ticker']} · Score: {int(r_dict['global_score'])}/100 · <span class="{sesgo_class}">{r_dict['sesgo']}</span> · {fmt_precio(r_dict['precio'])}</div>
                          {interp}
                        </div>
                        """, unsafe_allow_html=True)


        elif MODULO == 'ticker':
            todos_tickers = sorted(set(t for ind in ind_sel for t in ACCIONES_POR_INDUSTRIA.get(ind,[])))
            if not todos_tickers:
                st.info('Seleccioná al menos una industria.'); st.stop()
            ticker_sel = st.selectbox('Seleccioná un ticker', todos_tickers, key='largo_ticker_sel')
            if ticker_sel:
                with st.spinner(f'Descargando 2 años para {ticker_sel}...'):
                    df_tk = descargar_datos(ticker_sel, '2y')
                if df_tk is None or df_tk.empty:
                    st.error(f'Sin datos para {ticker_sel}.'); st.stop()
                cl = get_close_series(df_tk)
                if cl is None or len(cl) < 150:
                    st.error('Datos insuficientes.'); st.stop()
                r = analizar_largo(ticker_sel, cl)
                if r is None:
                    st.error('No se pudo calcular el análisis.'); st.stop()
                render_largo_completo(ticker_sel, cl, r, key_suffix='tickermod', df_ohlc=df_tk)



def modulo_fundamental():
    ind_disp_f = list(ACCIONES_POR_INDUSTRIA.keys())
    ind_sel_f  = st.multiselect(
        'Industrias a analizar (Fundamental)', ind_disp_f,
        default=st.session_state.get('fund_ind_sel', ind_disp_f[:1]),
        key='fund_ind_sel_widget'
    )
    st.session_state['fund_ind_sel'] = ind_sel_f

    if not ind_sel_f:
        st.info('Seleccioná al menos una industria.')
        return

    tab_modo_f, tab_ticker_f = st.tabs(['🏭 Por Industria', '🔍 Ticker Individual'])

    # ── TAB 1: Por industria ──────────────────────────────────────────────
    with tab_modo_f:
        if st.button('▶ Cargar análisis fundamental', key='btn_fund_load'):
            st.session_state['fund_loaded'] = True

        if not st.session_state.get('fund_loaded'):
            st.markdown("""
            <div style='background:#0d1117;border:1px dashed #21262d;border-radius:10px;
                 padding:40px;text-align:center;margin-top:16px'>
              <div style='font-size:40px;margin-bottom:12px'>📊</div>
              <div style='color:#e6edf3;font-size:14px;font-weight:600;margin-bottom:6px'>Análisis Fundamental</div>
              <div style='color:#6b7d9a;font-size:12px'>Ratios financieros + benchmarks por sector.<br>
              La descarga se hace en paralelo para que sea más rápida.</div>
            </div>
            """, unsafe_allow_html=True)
            return

        todos_resultados = {ind: [] for ind in ind_sel_f}
        tickers_industria = [(tk, ind) for ind in ind_sel_f for tk in ACCIONES_POR_INDUSTRIA.get(ind, [])]
        total_t = len(tickers_industria)
        prog_f = st.progress(0, text='Descargando datos fundamentales en paralelo...')
        procesados = 0
        fallidos_fund = []

        with ThreadPoolExecutor(max_workers=8) as ex:
            futuros = {ex.submit(analizar_fundamental, tk, ind): (tk, ind) for tk, ind in tickers_industria}
            for fut in as_completed(futuros):
                tk, ind = futuros[fut]
                r = fut.result()
                if r:
                    todos_resultados[ind].append(r)
                else:
                    fallidos_fund.append(tk)
                procesados += 1
                pct = int(procesados / max(total_t, 1) * 100)
                prog_f.progress(min(pct, 100), text=f'Procesado {tk} ({procesados}/{total_t})')

        prog_f.empty()
        st.session_state['_fallidos_fundamental'] = fallidos_fund
        st.session_state['_ts_fundamental'] = datetime.now()

        total_emp = sum(len(v) for v in todos_resultados.values())
        if total_emp == 0:
            st.error('No se pudieron obtener datos fundamentales.')
            return

        badge_actualizacion('fundamental', ttl_min=60)
        aviso_fallidos('fundamental', etiqueta='empresas (sin datos fundamentales en Yahoo Finance)')

        todas_emp = [e for lst in todos_resultados.values() for e in lst]
        n_compra   = sum(1 for e in todas_emp if 'COMPRA' in e['senal_final'])
        n_mantener = sum(1 for e in todas_emp if 'MANTENER' in e['senal_final'])
        n_riesgo   = sum(1 for e in todas_emp if 'RIESGO' in e['senal_final'])
        kpi_cards_4([
            ('Total analizadas', str(total_emp), f'{len(ind_sel_f)} industrias', '#3a7bd5'),
            ('✅ Compra Fuerte', str(n_compra),   'score_ok ≥ 8 señales positivas', '#3fb950'),
            ('🟡 Mantener',      str(n_mantener), 'score_ok 5-7', '#e3b341'),
            ('🔴 Riesgo/Vender', str(n_riesgo),   'score_ok < 5', '#f85149'),
        ])

        filas_res = []
        for e in sorted(todas_emp, key=lambda x: x['n_ok'], reverse=True):
            fp = _fmt_pct
            fn = _fmt_num
            filas_res.append({
                'Ticker': e['ticker'],
                'Nombre': (e['nombre'] or e['ticker'])[:28],
                'Industria': e['industria'],
                'Sector': e['sector'],
                'Precio': fmt_precio(e.get('precio')),
                'Señal': e['senal_final'],
                'Rec. Anal.': e.get('recommendation') or 'N/D',
                'PER': fn(e.get('per')),
                'P/B': fn(e.get('pb')),
                'EV/EBITDA': fn(e.get('ev_ebitda')),
                'ROE %': fp(e.get('roe')),
                'Mg.Bruto %': fp(e.get('gross_margin')),
                'Mg.Op. %': fp(e.get('op_margin')),
                'Rev.Growth %': fp(e.get('revenue_growth')),
                'D/E': fn(e.get('debt_equity')),
                'Beta': fn(e.get('beta')),
                'Div.Yield %': fp(e.get('div_yield')),
                'FCF': _fmt_big(e.get('fcf')),
                'YTD %': f"{e['alza_ytd']:.1f}%" if e.get('alza_ytd') is not None else 'N/D',
                'OK': e['n_ok'],
                'ALT': e['n_alt'],
            })

        df_fund = pd.DataFrame(filas_res)

        modo_avanzado = st.toggle(
            '🎛️ Modo avanzado (todos los filtros y columnas)',
            value=st.session_state.get('fund_modo_avanzado', False),
            key='fund_modo_avanzado',
            help='Desactivado: vista simple con lo esencial. Activado: todos los filtros, columnas y fichas por empresa.',
        )

        if modo_avanzado:
            with st.expander('🎛️ Filtros avanzados', expanded=True):
                frow1 = st.columns(4)
                with frow1[0]:
                    f_senal_f = st.selectbox('Señal', ['Todas','COMPRA FUERTE','MANTENER','RIESGO / VENDER'], key='fund_f_senal')
                with frow1[1]:
                    inds_u_f = ['Todas'] + sorted(df_fund['Industria'].unique().tolist())
                    f_ind_f  = st.selectbox('Industria', inds_u_f, key='fund_f_ind')
                with frow1[2]:
                    sects_u  = ['Todos'] + sorted(df_fund['Sector'].unique().tolist())
                    f_sect_f = st.selectbox('Sector', sects_u, key='fund_f_sect')
                with frow1[3]:
                    f_sort = st.selectbox('Ordenar por', [
                        'OK ↓ (más señales positivas)', 'ALT ↑ (más alertas)',
                        'YTD % ↓', 'PER ↑ (más barato)', 'ROE % ↓'
                    ], key='fund_f_sort')

                st.markdown('<div style="margin-top:10px;margin-bottom:4px;font-size:11px;color:#6b7d9a;font-weight:700;letter-spacing:.5px">📐 VALUACIÓN</div>', unsafe_allow_html=True)
                vrow = st.columns(3)
                with vrow[0]:
                    f_per_rng = st.slider('PER', min_value=0.0, max_value=200.0, value=(0.0, 200.0), step=1.0, key='fund_f_per_rng', help=G('PER'))
                with vrow[1]:
                    f_pb_rng = st.slider('P/B', min_value=0.0, max_value=30.0, value=(0.0, 30.0), step=0.5, key='fund_f_pb_rng', help=G('P/B'))
                with vrow[2]:
                    f_eveb_rng = st.slider('EV/EBITDA', min_value=0.0, max_value=60.0, value=(0.0, 60.0), step=1.0, key='fund_f_eveb_rng', help=G('EV/EBITDA'))

                st.markdown('<div style="margin-top:8px;margin-bottom:4px;font-size:11px;color:#6b7d9a;font-weight:700;letter-spacing:.5px">📈 RENTABILIDAD Y MÁRGENES</div>', unsafe_allow_html=True)
                rrow = st.columns(4)
                with rrow[0]:
                    f_roe_rng = st.slider('ROE %', min_value=-50.0, max_value=100.0, value=(-50.0, 100.0), step=1.0, key='fund_f_roe_rng', help=G('ROE'))
                with rrow[1]:
                    f_gm_rng = st.slider('Mg. Bruto %', min_value=-20.0, max_value=100.0, value=(-20.0, 100.0), step=1.0, key='fund_f_gm_rng')
                with rrow[2]:
                    f_om_rng = st.slider('Mg. Operativo %', min_value=-50.0, max_value=60.0, value=(-50.0, 60.0), step=1.0, key='fund_f_om_rng')
                with rrow[3]:
                    f_rg_rng = st.slider('Rev. Growth %', min_value=-50.0, max_value=100.0, value=(-50.0, 100.0), step=1.0, key='fund_f_rg_rng')

                st.markdown('<div style="margin-top:8px;margin-bottom:4px;font-size:11px;color:#6b7d9a;font-weight:700;letter-spacing:.5px">🔒 SOLVENCIA, RIESGO Y FLUJO</div>', unsafe_allow_html=True)
                srow = st.columns(4)
                with srow[0]:
                    f_de_rng = st.slider('D/E', min_value=0.0, max_value=10.0, value=(0.0, 10.0), step=0.1, key='fund_f_de_rng')
                with srow[1]:
                    f_beta_rng = st.slider('Beta', min_value=0.0, max_value=4.0, value=(0.0, 4.0), step=0.1, key='fund_f_beta_rng', help=G('Beta'))
                with srow[2]:
                    f_div_rng = st.slider('Div. Yield %', min_value=0.0, max_value=20.0, value=(0.0, 20.0), step=0.5, key='fund_f_div_rng', help=G('Dividend Yield'))
                with srow[3]:
                    f_ytd_rng = st.slider('YTD %', min_value=-80.0, max_value=300.0, value=(-80.0, 300.0), step=5.0, key='fund_f_ytd_rng')

                st.markdown('<div style="margin-top:8px;margin-bottom:4px;font-size:11px;color:#6b7d9a;font-weight:700;letter-spacing:.5px">✅ SEÑALES Y FCF</div>', unsafe_allow_html=True)
                qrow = st.columns(3)
                with qrow[0]:
                    f_ok_rng = st.slider('Señales OK', min_value=0, max_value=20, value=(0, 20), step=1, key='fund_f_ok_rng')
                with qrow[1]:
                    f_fcf_pos = st.checkbox('Solo FCF positivo', key='fund_f_fcf', value=False)
                with qrow[2]:
                    st.markdown('<div style="font-size:10px;color:#6b7d9a;padding-top:28px">N/D: la empresa se excluye si el rango es distinto al default.</div>', unsafe_allow_html=True)
        else:
            st.caption('💡 Vista simple activa — mostrando lo esencial. Activá "Modo avanzado" arriba para filtros detallados, todas las columnas y fichas por empresa.')
            f_senal_f, f_ind_f, f_sect_f = 'Todas', 'Todas', 'Todos'
            f_sort = 'OK ↓ (más señales positivas)'
            f_per_rng, f_pb_rng, f_eveb_rng = (0.0, 200.0), (0.0, 30.0), (0.0, 60.0)
            f_roe_rng, f_gm_rng, f_om_rng, f_rg_rng = (-50.0, 100.0), (-20.0, 100.0), (-50.0, 60.0), (-50.0, 100.0)
            f_de_rng, f_beta_rng, f_div_rng, f_ytd_rng = (0.0, 10.0), (0.0, 4.0), (0.0, 20.0), (-80.0, 300.0)
            f_ok_rng = (0, 20)
            f_fcf_pos = False

        df_f2 = df_fund.copy()
        if f_senal_f != 'Todas':
            df_f2 = df_f2[df_f2['Señal'] == f_senal_f]
        if f_ind_f != 'Todas':
            df_f2 = df_f2[df_f2['Industria'] == f_ind_f]
        if f_sect_f != 'Todos':
            df_f2 = df_f2[df_f2['Sector'] == f_sect_f]

        emp_filtradas = [e for lst in todos_resultados.values() for e in lst]
        tickers_validos = set(df_f2['Ticker'].tolist())

        def _en_rango(val, lo, hi, escala=1.0):
            if val is None: return False
            return lo <= val * escala <= hi

        _DEFAULTS = {
            'per':  (0.0, 200.0), 'pb':  (0.0, 30.0),  'eveb': (0.0, 60.0),
            'roe':  (-50.0, 100.0), 'gm': (-20.0, 100.0), 'om': (-50.0, 60.0),
            'rg':   (-50.0, 100.0), 'de': (0.0, 10.0),  'beta': (0.0, 4.0),
            'div':  (0.0, 20.0),   'ytd': (-80.0, 300.0), 'ok': (0, 20),
        }
        _RNGS = {
            'per': f_per_rng, 'pb': f_pb_rng, 'eveb': f_eveb_rng,
            'roe': f_roe_rng, 'gm': f_gm_rng, 'om': f_om_rng,
            'rg':  f_rg_rng,  'de': f_de_rng, 'beta': f_beta_rng,
            'div': f_div_rng, 'ytd': f_ytd_rng, 'ok': f_ok_rng,
        }
        _activo = {k: (_RNGS[k] != _DEFAULTS[k]) for k in _DEFAULTS}

        nuevos = set()
        for e in emp_filtradas:
            if e['ticker'] not in tickers_validos: continue
            lo, hi = f_per_rng
            if _activo['per']  and not _en_rango(e.get('per'),            lo, hi):         continue
            lo, hi = f_pb_rng
            if _activo['pb']   and not _en_rango(e.get('pb'),             lo, hi):         continue
            lo, hi = f_eveb_rng
            if _activo['eveb'] and not _en_rango(e.get('ev_ebitda'),      lo, hi):         continue
            lo, hi = f_roe_rng
            if _activo['roe']  and not _en_rango(e.get('roe'),            lo, hi, 100.0):  continue
            lo, hi = f_gm_rng
            if _activo['gm']   and not _en_rango(e.get('gross_margin'),   lo, hi, 100.0):  continue
            lo, hi = f_om_rng
            if _activo['om']   and not _en_rango(e.get('op_margin'),      lo, hi, 100.0):  continue
            lo, hi = f_rg_rng
            if _activo['rg']   and not _en_rango(e.get('revenue_growth'), lo, hi, 100.0):  continue
            lo, hi = f_de_rng
            if _activo['de']   and not _en_rango(e.get('debt_equity'),    lo, hi):         continue
            lo, hi = f_beta_rng
            if _activo['beta'] and not _en_rango(e.get('beta'),           lo, hi):         continue
            lo, hi = f_div_rng
            if _activo['div']  and not _en_rango(e.get('div_yield'),      lo, hi, 100.0):  continue
            lo, hi = f_ytd_rng
            if _activo['ytd']  and not _en_rango(e.get('alza_ytd'),       lo, hi):         continue
            lo, hi = f_ok_rng
            if _activo['ok']   and not (lo <= e['n_ok'] <= hi):                            continue
            if f_fcf_pos and (e.get('fcf') is None or e['fcf'] <= 0):                      continue
            nuevos.add(e['ticker'])

        if any(_activo.values()) or f_fcf_pos:
            tickers_validos = nuevos

        df_f2 = df_f2[df_f2['Ticker'].isin(tickers_validos)]


        if 'OK ↓' in f_sort:
            df_f2 = df_f2.sort_values('OK', ascending=False)
        elif 'ALT ↑' in f_sort:
            df_f2 = df_f2.sort_values('ALT', ascending=False)
        elif 'YTD' in f_sort:
            ytd_num = df_f2['YTD %'].str.replace('%','').apply(pd.to_numeric, errors='coerce')
            df_f2 = df_f2.assign(_ytd=ytd_num).sort_values('_ytd', ascending=False).drop(columns=['_ytd'])
        elif 'PER' in f_sort:
            per_num = df_f2['PER'].apply(pd.to_numeric, errors='coerce')
            df_f2 = df_f2.assign(_per=per_num).sort_values('_per', ascending=True).drop(columns=['_per'])
        elif 'ROE' in f_sort:
            roe_num = df_f2['ROE %'].str.replace('%','').apply(pd.to_numeric, errors='coerce')
            df_f2 = df_f2.assign(_roe=roe_num).sort_values('_roe', ascending=False).drop(columns=['_roe'])

        def style_senal_fund(val):
            c, bg = _senal_color(val)
            return f'color:{c};font-weight:700;background:{bg}'

        def style_ok(val):
            try:
                v = int(val)
                if v >= 8: return 'color:#3fb950;font-weight:700'
                if v >= 5: return 'color:#e3b341;font-weight:700'
                return 'color:#f85149;font-weight:700'
            except: return ''

        def style_alt(val):
            try:
                v = int(val)
                if v >= 5: return 'color:#f85149;font-weight:700'
                if v >= 2: return 'color:#f0883e;font-weight:700'
                return 'color:#3fb950;font-weight:700'
            except: return ''

        if modo_avanzado:
            df_f2_show = df_f2
        else:
            cols_simple = ['Ticker', 'Nombre', 'Industria', 'Señal', 'Precio', 'PER', 'ROE %', 'Rev.Growth %', 'YTD %', 'OK']
            df_f2_show = df_f2[[c for c in cols_simple if c in df_f2.columns]]

        _map_f = 'map' if hasattr(df_f2_show.style, 'map') else 'applymap'
        styled_fund = df_f2_show.style.set_properties(**{'background-color':'#0d1117','color':'#e6edf3','border':'1px solid #21262d'})
        if 'Señal' in df_f2_show.columns:
            styled_fund = styled_fund.pipe(lambda s: getattr(s,_map_f)(style_senal_fund, subset=['Señal']))
        if 'OK' in df_f2_show.columns:
            styled_fund = styled_fund.pipe(lambda s: getattr(s,_map_f)(style_ok, subset=['OK']))
        if 'ALT' in df_f2_show.columns:
            styled_fund = styled_fund.pipe(lambda s: getattr(s,_map_f)(style_alt, subset=['ALT']))
        styled_fund = styled_fund.set_table_styles([
            {'selector':'th','props':[('background-color','#161b22'),('color','#e6edf3'),
                ('font-weight','700'),('text-align','center'),
                ('border-bottom','2px solid #3a7bd5'),('font-size','11px')]},
            {'selector':'td','props':[('text-align','center'),('font-size','11px')]},
        ])
        if modo_avanzado:
            st.caption('↔️ Desliza horizontalmente para ver todas las columnas.')
        st.dataframe(styled_fund, use_container_width=True, height=min(700, max(200, len(df_f2_show)*32+45)))
        st.caption(f'{len(df_f2_show)} empresas de {len(df_fund)} totales')
        chips_navegacion(df_f2_show['Ticker'].tolist(), 'fund_tabla')

        for industria in ind_sel_f:
            if not modo_avanzado:
                break
            emps = todos_resultados.get(industria, [])
            if not emps: continue
            sector_ind = SECTOR_MAP_FUND.get(industria, 'Sin Clasificar')
            bench_ind  = INDUSTRY_BENCHMARKS_FUND.get(sector_ind, DEFAULT_BENCHMARK_FUND)
            best_emp   = max(emps, key=lambda e: e['n_ok'])

            with st.expander(f'📂 {industria}  ·  Sector: {sector_ind}  ·  {len(emps)} empresas  ·  Mejor: {best_emp["ticker"]} ({best_emp["senal_final"]})', expanded=False):
                st.markdown(f"""
                <div style='background:rgba(58,123,213,0.07);border:1px solid rgba(58,123,213,0.2);
                     border-radius:8px;padding:10px 14px;margin-bottom:12px;font-size:11px;color:#b0bcd0;line-height:1.7'>
                  <b style='color:#3a7bd5'>BENCHMARK {sector_ind.upper()}</b><br>
                  {bench_ind['descripcion']}<br>
                  <b>Métricas clave:</b> {' · '.join(bench_ind.get('metricas_clave',[]))}
                </div>
                """, unsafe_allow_html=True)

                for e in sorted(emps, key=lambda x: x['n_ok'], reverse=True):
                    sc_col, sc_bg = _senal_color(e['senal_final'])
                    fp = _fmt_pct
                    fn = _fmt_num
                    fb = _fmt_big

                    st.markdown(f"""
                    <div style='background:#0d1117;border:1px solid #21262d;border-left:3px solid {sc_col};
                         border-radius:8px;padding:12px 16px;margin-bottom:10px'>
                      <div style='display:flex;align-items:center;gap:12px;margin-bottom:8px;flex-wrap:wrap'>
                        <span style='color:#e6edf3;font-size:14px;font-weight:700;font-family:JetBrains Mono,monospace'>{e['ticker']}</span>
                        <span style='color:#6b7d9a;font-size:11px'>{(e['nombre'] or '')[:40]}</span>
                        <span style='padding:3px 10px;border-radius:20px;font-size:10px;font-weight:700;
                          background:{sc_bg};border:1px solid {sc_col};color:{sc_col}'>{e['senal_final']}</span>
                        <span style='color:#6b7d9a;font-size:10px'>Analistas: {e.get('recommendation') or 'N/D'}</span>
                        <span style='color:#6b7d9a;font-size:10px'>✅ {e['n_ok']} OK  ·  ⚠️ {e['n_alt']} Alertas</span>
                      </div>
                      <div style='display:grid;grid-template-columns:repeat(5,1fr);gap:6px;font-size:11px;margin-bottom:8px'>
                        <div><span style='color:#6b7d9a'>Precio</span><br><b style='color:#e6edf3'>{fmt_precio(e.get('precio'))}</b></div>
                        <div><span style='color:#6b7d9a'>PER</span><br><b style='color:#e6edf3'>{fn(e.get('per'))}x</b></div>
                        <div><span style='color:#6b7d9a'>P/B</span><br><b style='color:#e6edf3'>{fn(e.get('pb'))}x</b></div>
                        <div><span style='color:#6b7d9a'>EV/EBITDA</span><br><b style='color:#e6edf3'>{fn(e.get('ev_ebitda'))}x</b></div>
                        <div><span style='color:#6b7d9a'>YTD</span><br><b style='color:{"#3fb950" if (e.get("alza_ytd") or 0)>=0 else "#f85149"}'>{f"{e['alza_ytd']:.1f}%" if e.get("alza_ytd") is not None else "N/D"}</b></div>
                        <div><span style='color:#6b7d9a'>ROE</span><br><b style='color:#e6edf3'>{fp(e.get('roe'))}</b></div>
                        <div><span style='color:#6b7d9a'>Mg.Bruto</span><br><b style='color:#e6edf3'>{fp(e.get('gross_margin'))}</b></div>
                        <div><span style='color:#6b7d9a'>Mg.Op.</span><br><b style='color:#e6edf3'>{fp(e.get('op_margin'))}</b></div>
                        <div><span style='color:#6b7d9a'>Rev.Growth</span><br><b style='color:#e6edf3'>{fp(e.get('revenue_growth'))}</b></div>
                        <div><span style='color:#6b7d9a'>D/E</span><br><b style='color:#e6edf3'>{fn(e.get('debt_equity'))}x</b></div>
                        <div><span style='color:#6b7d9a'>Beta</span><br><b style='color:#e6edf3'>{fn(e.get('beta'))}</b></div>
                        <div><span style='color:#6b7d9a'>Div.Yield</span><br><b style='color:#e6edf3'>{fp(e.get('div_yield'))}</b></div>
                        <div><span style='color:#6b7d9a'>FCF</span><br><b style='color:#e6edf3'>{fb(e.get('fcf'))}</b></div>
                        <div><span style='color:#6b7d9a'>Curr.Ratio</span><br><b style='color:#e6edf3'>{fn(e.get('curr_ratio'))}</b></div>
                        <div><span style='color:#6b7d9a'>Precio Obj.</span><br><b style='color:#e6edf3'>{fmt_precio(e.get('target_price'))}</b></div>
                      </div>
                    </div>
                    """, unsafe_allow_html=True)

                    if e['senales']:
                        sig_cols = st.columns(2)
                        ok_sigs  = [(t,m) for t,m in e['senales'] if t=='OK']
                        alt_sigs = [(t,m) for t,m in e['senales'] if t=='ALT']
                        with sig_cols[0]:
                            for _,msg in ok_sigs:
                                st.markdown(f'<div style="font-size:11px;color:#3fb950;padding:2px 0">✅ {msg}</div>', unsafe_allow_html=True)
                        with sig_cols[1]:
                            for _,msg in alt_sigs:
                                st.markdown(f'<div style="font-size:11px;color:#f85149;padding:2px 0">⚠️ {msg}</div>', unsafe_allow_html=True)

                    if e['sector_senales']:
                        st.markdown('<div style="margin-top:6px;font-size:11px;color:#6b7d9a;font-weight:700">VS SECTOR:</div>', unsafe_allow_html=True)
                        for tipo, msg in e['sector_senales']:
                            col_vs = '#3fb950' if tipo=='POS' else '#f85149'
                            ico_vs = '✔' if tipo=='POS' else '✘'
                            st.markdown(f'<div style="font-size:11px;color:{col_vs};padding:1px 0">{ico_vs} {msg}</div>', unsafe_allow_html=True)

                    st.markdown('<hr style="border-color:#21262d;margin:10px 0">', unsafe_allow_html=True)

    # ── TAB 2: Ticker individual ──────────────────────────────────────────
    with tab_ticker_f:
        col_tk1, col_tk2 = st.columns([4,1])
        with col_tk1:
            tk_fund = selector_ticker_autocomplete('fund_ticker', label='Ticker')
        with col_tk2:
            st.markdown('<div style="height:6px"></div>', unsafe_allow_html=True)
            analizar_fund = st.button('▶ Analizar', key='btn_fund_ticker')

        if tk_fund and analizar_fund:
            industria_f = TICKER_INDUSTRY.get(tk_fund, 'Sin Clasificar')
            with st.spinner(f'Descargando datos fundamentales para {tk_fund}...'):
                res_f = analizar_fundamental(tk_fund, industria_f)

            if res_f is None:
                st.error(f'No se pudieron obtener datos para {tk_fund}. Verificá el símbolo.')
            else:
                render_perfil_empresa(tk_fund, key_suffix='fund_ticker')
                render_analisis_profundo(tk_fund, key_suffix='fund_ticker_ef')
                sc_col_f, sc_bg_f = _senal_color(res_f['senal_final'])
                fp_f = _fmt_pct
                fn_f = _fmt_num
                fb_f = _fmt_big

                kpi_cards_4([
                    ('Señal Final', res_f['senal_final'], f"{res_f['n_ok']} OK · {res_f['n_alt']} Alertas", sc_col_f),
                    ('Precio', fmt_precio(res_f.get('precio')), f"Obj: {fmt_precio(res_f.get('target_price'))}", '#3a7bd5'),
                    ('PER / P/B', f"{fn_f(res_f.get('per'))}x / {fn_f(res_f.get('pb'))}x", f"EV/EBITDA: {fn_f(res_f.get('ev_ebitda'))}x", '#e3b341', f"{G('PER')} | {G('P/B')}"),
                    ('ROE / Mg.Bruto', f"{fp_f(res_f.get('roe'))} / {fp_f(res_f.get('gross_margin'))}", f"Rev.Growth: {fp_f(res_f.get('revenue_growth'))}", '#3fb950', G('ROE')),
                ])

                c1f, c2f, c3f, c4f, c5f = st.columns(5)
                with c1f: st.metric('Sector', res_f['sector'][:18])
                with c2f: st.metric('Beta', fn_f(res_f.get('beta')), help=G('Beta'))
                with c3f: st.metric('D/E', fn_f(res_f.get('debt_equity')))
                with c4f: st.metric('FCF', fb_f(res_f.get('fcf')), help=G('FCF'))
                with c5f: st.metric('YTD', f"{res_f['alza_ytd']:.1f}%" if res_f.get('alza_ytd') is not None else 'N/D')

                bench_f = res_f['bench']
                st.markdown(f"""
                <div style='background:rgba(58,123,213,0.07);border:1px solid rgba(58,123,213,0.2);
                     border-radius:8px;padding:10px 14px;margin:12px 0;font-size:11px;color:#b0bcd0;line-height:1.7'>
                  <b style='color:#3a7bd5'>BENCHMARK {res_f['sector'].upper()}</b><br>
                  {bench_f['descripcion']}
                </div>
                """, unsafe_allow_html=True)

                col_ok_f, col_alt_f = st.columns(2)
                with col_ok_f:
                    st.markdown('<div style="font-size:11px;font-weight:700;color:#3fb950;margin-bottom:4px">✅ POSITIVAS</div>', unsafe_allow_html=True)
                    for t, msg in res_f['senales']:
                        if t == 'OK':
                            st.markdown(f'<div style="font-size:11px;color:#3fb950;padding:2px 0">• {msg}</div>', unsafe_allow_html=True)
                with col_alt_f:
                    st.markdown('<div style="font-size:11px;font-weight:700;color:#f85149;margin-bottom:4px">⚠️ ALERTAS</div>', unsafe_allow_html=True)
                    for t, msg in res_f['senales']:
                        if t == 'ALT':
                            st.markdown(f'<div style="font-size:11px;color:#f85149;padding:2px 0">• {msg}</div>', unsafe_allow_html=True)

                if res_f['sector_senales']:
                    st.markdown('<div class="sec-title">VS BENCHMARK SECTORIAL</div>', unsafe_allow_html=True)
                    for tipo, msg in res_f['sector_senales']:
                        col_vs_f = '#3fb950' if tipo=='POS' else '#f85149'
                        ico_vs_f = '✔' if tipo=='POS' else '✘'
                        st.markdown(f'<div style="font-size:12px;color:{col_vs_f};padding:3px 0;border-bottom:1px solid #21262d">{ico_vs_f} {msg}</div>', unsafe_allow_html=True)


# ==============================================================
#  MÓDULO FUNDAMENTAL — RENDERIZADO
# ==============================================================

if HORIZONTE == 'largo' and MODULO == 'fundamental':
    if 'fund_ind_sel' not in st.session_state:
        st.session_state['fund_ind_sel'] = list(ACCIONES_POR_INDUSTRIA.keys())[:1]
    modulo_fundamental()

if HORIZONTE == 'largo' and MODULO == 'tdc':
    modulo_topdown_cuantitativo()


# ==============================================================
#  FOOTER
# ==============================================================


st.markdown('<div style="height:24px"></div>', unsafe_allow_html=True)
st.markdown(f"""
<div style='text-align:center;color:#3a4a5a;font-size:10px;padding:14px;
     border-top:1px solid #21262d;margin-top:12px'>
  📡 Analizador Cuantitativo Unificado &nbsp;·&nbsp; Datos: Yahoo Finance &nbsp;·&nbsp;
  Caché: 30 min &nbsp;·&nbsp; {ahora_ar().strftime('%d/%m/%Y')} &nbsp;·&nbsp;
  <b>Solo informativo. No constituye asesoramiento financiero.</b>
</div>
""", unsafe_allow_html=True)
