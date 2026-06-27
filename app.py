# ==============================================================
#  ANALIZADOR CUANTITATIVO UNIFICADO — v2 (sin sidebar)
#  Corto Plazo (Top-Down) + Mediano/Largo Plazo (Cuantitativo)
#  + Buscador Universal por Ticker
# ==============================================================


import warnings
warnings.filterwarnings("ignore")


import streamlit as st
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sb
from datetime import datetime
import sys, os


try:
    from hurst import compute_Hc
    HURST_OK = True
except ImportError:
    HURST_OK = False


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
#  CSS — diseño sin sidebar, nav superior
# ==============================================================


st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');


  /* ── Reset sidebar ── */
  [data-testid="stSidebar"] { display: none !important; }
  [data-testid="collapsedControl"] { display: none !important; }
  section[data-testid="stSidebar"] { width: 0 !important; }


  html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
    background: #07090f;
    color: #c9d1d9;
  }
  .stApp { background: #07090f; }
  .block-container { padding: 0 1.5rem 1.5rem 1.5rem !important; max-width: 1500px; }


  /* ── Top nav bar ── */
  .topbar-wrap {
    position: sticky; top: 0; z-index: 999;
    background: rgba(7,9,15,0.96);
    border-bottom: 1px solid #21262d;
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    padding: 0;
  }
  .topbar-inner {
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
  .topbar-brand-name {
    font-size: 13px; font-weight: 700; color: #e6edf3;
    letter-spacing: -0.3px; line-height: 1.2;
  }
  .topbar-brand-sub {
    font-size: 10px; color: #6b7d9a; letter-spacing: 0.2px;
  }
  .topbar-divider { width: 1px; height: 22px; background: #21262d; margin: 0 20px; flex-shrink: 0; }
  .topbar-nav-group { display: flex; align-items: center; gap: 2px; flex: 1; }
  .topbar-section-label {
    font-size: 9px; font-weight: 700; color: #3a4a5f;
    text-transform: uppercase; letter-spacing: 1.2px;
    margin-right: 6px; white-space: nowrap;
  }
  .topbar-actions { display: flex; align-items: center; gap: 8px; margin-left: auto; }
  .topbar-time {
    font-size: 10px; color: #3a4a5f; font-family: 'JetBrains Mono', monospace;
    white-space: nowrap;
  }


  /* ── Nav pills — todos los botones de la fila de navegación ── */
  div[data-testid="stHorizontalBlock"] div[data-testid="column"] .stButton button {
    border-radius: 999px !important;
    border: 1px solid #21262d !important;
    padding: 6px 16px !important;
    font-size: 12px !important; font-weight: 500 !important;
    height: 34px !important; min-height: 34px !important;
    background: #0d1117 !important;
    color: #8b949e !important;
    transition: all .18s ease !important;
    box-shadow: none !important;
    white-space: nowrap !important;
    letter-spacing: 0.1px !important;
  }
  div[data-testid="stHorizontalBlock"] div[data-testid="column"] .stButton button:hover {
    background: #161b22 !important;
    color: #e6edf3 !important;
    border-color: #3a4a5a !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3) !important;
  }


  /* ── Page header ── */
  .page-header {
    padding: 14px 0 12px 0;
    border-bottom: 1px solid #21262d;
    margin-bottom: 14px;
  }
  .page-title { font-size: 22px; font-weight: 700; color: #e6edf3; margin: 0; letter-spacing: -0.5px; }
  .page-sub { font-size: 12px; color: #6b7d9a; margin: 4px 0 0 0; }


  /* ── Toolbar (filtros debajo del header) ── */
  .toolbar {
    background: #0d1117;
    border: 1px solid #21262d;
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 20px;
    display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  }
  .toolbar-label { font-size: 11px; font-weight: 600; color: #6b7d9a; text-transform: uppercase; letter-spacing: 0.8px; }


  /* ── KPI cards ── */
  .kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 16px; }
  .kpi-card {
    background: #0d1117; border: 1px solid #21262d; border-radius: 10px;
    padding: 13px 16px; position: relative; overflow: hidden;
    transition: border-color .18s ease, transform .18s ease, box-shadow .18s ease;
    cursor: default;
  }
  .kpi-card:hover {
    border-color: #3a7bd5;
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(58,123,213,0.15);
  }
  .kpi-accent { position: absolute; top: 0; left: 0; width: 100%; height: 2px; border-radius: 10px 10px 0 0; }
  .kpi-label { color: #6b7d9a; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 5px; }
  .kpi-value { color: #e6edf3; font-size: 19px; font-weight: 700; letter-spacing: -0.5px; font-family: 'JetBrains Mono', monospace; }
  .kpi-sub { color: #6b7d9a; font-size: 10px; margin-top: 3px; line-height: 1.4; }


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
    color: #3a7bd5 !important;
    border-bottom: 2px solid #3a7bd5 !important;
    background: transparent !important;
  }


  /* ── Section title ── */
  .sec-title {
    font-size: 12px; font-weight: 700; color: #e6edf3;
    text-transform: uppercase; letter-spacing: 0.8px;
    margin: 20px 0 12px 0; padding-bottom: 8px;
    border-bottom: 1px solid #21262d;
  }


  /* ── Info banner ── */
  .info-banner {
    background: rgba(58,123,213,0.07); border: 1px solid rgba(58,123,213,0.2);
    border-radius: 8px; padding: 10px 14px; color: #6b7d9a;
    font-size: 11px; margin-bottom: 16px; line-height: 1.6;
  }


  /* ── Search box ── */
  .search-container {
    background: #0d1117; border: 1px solid #21262d; border-radius: 12px;
    padding: 24px 28px; margin-bottom: 24px;
  }
  .search-title { font-size: 15px; font-weight: 700; color: #e6edf3; margin-bottom: 4px; }
  .search-sub { font-size: 12px; color: #6b7d9a; margin-bottom: 16px; }


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
    font-size: 12px; line-height: 1.7; color: #b0bcd0;
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


  /* ── Buttons ── */
  .stButton > button {
    background: linear-gradient(135deg, #1e5fbd, #3a7bd5);
    color: white; border: none; border-radius: 7px;
    font-weight: 600; font-size: 12px; transition: opacity .2s;
  }
  .stButton > button:hover { opacity: .85; }


  /* ── Selectbox / multiselect ── */
  .stSelectbox > div > div { background: #0d1117 !important; border-color: #21262d !important; color: #e6edf3 !important; }
  .stMultiSelect > div > div { background: #0d1117 !important; border-color: #21262d !important; }


  /* ── Metric ── */
  [data-testid="stMetric"] { background: #0d1117; border: 1px solid #21262d; border-radius: 9px; padding: 12px 16px; }
  [data-testid="stMetricLabel"] { color: #6b7d9a !important; font-size: 10px !important; }
  [data-testid="stMetricValue"] { color: #e6edf3 !important; font-family: 'JetBrains Mono', monospace; }


  /* ── DataFrame ── */
  .stDataFrame { border-radius: 10px; overflow: hidden; }


  /* General ── */
  h1,h2,h3,h4 { color: #e6edf3 !important; }
  hr { border-color: #21262d !important; }
  p, label, .stMarkdown { color: #b0bcd0 !important; }

  /* ── Ticker mini-card (Fundamental) ── */
  .tk-card {
    background: #0d1117; border: 1px solid #21262d; border-radius: 9px;
    padding: 11px 14px; transition: all .18s ease; cursor: default;
  }
  .tk-card:hover { border-color: #3a7bd5; transform: translateY(-1px); box-shadow: 0 4px 14px rgba(58,123,213,0.12); }

  /* ── Filtro-chip activo ── */
  .filter-chip {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 3px 9px; border-radius: 20px; font-size: 10px; font-weight: 700;
    background: rgba(58,123,213,0.12); border: 1px solid rgba(58,123,213,0.3);
    color: #3a7bd5; margin: 2px 3px; white-space: nowrap;
  }

  /* ── Buscador global en nav ── */
  .nav-search-box {
    display: flex; align-items: center; gap: 8px;
    background: #0d1117; border: 1px solid #21262d; border-radius: 7px;
    padding: 5px 12px; transition: border-color .15s;
  }
  .nav-search-box:focus-within { border-color: #3a7bd5; }

  /* ── Metric compacto ── */
  [data-testid="stMetric"] { background: #0d1117; border: 1px solid #21262d; border-radius: 9px; padding: 10px 14px; transition: all .18s ease; }
  [data-testid="stMetric"]:hover { border-color: #3a7bd5; transform: translateY(-1px); }
  [data-testid="stMetricLabel"] { color: #6b7d9a !important; font-size: 10px !important; }
  [data-testid="stMetricValue"] { color: #e6edf3 !important; font-family: 'JetBrains Mono', monospace; }

  /* ── Expander compacto ── */
  details summary { padding: 8px 12px !important; font-size: 12px !important; }
  details[open] { border-color: #3a4a5a !important; }

  /* ── Tabs más compactos ── */
  .stTabs [data-baseweb="tab"] { padding: 8px 14px; font-size: 11px; }

  /* ── Progress bar ── */
  .stProgress > div > div > div { background: linear-gradient(90deg, #1e5fbd, #3a7bd5) !important; border-radius: 4px !important; }

  /* ── Spinner ── */
  .stSpinner > div { border-top-color: #3a7bd5 !important; }

  /* ── Scrollbar fina ── */
  ::-webkit-scrollbar { width: 5px; height: 5px; }
  ::-webkit-scrollbar-track { background: #07090f; }
  ::-webkit-scrollbar-thumb { background: #21262d; border-radius: 4px; }
  ::-webkit-scrollbar-thumb:hover { background: #3a4a5a; }

  /* ── Altura mínima para no ver pantalla vacía ── */
  .main .block-container { min-height: 100vh; }
</style>
""", unsafe_allow_html=True)


# ==============================================================
#  MATPLOTLIB THEME
# ==============================================================


plt.rcParams.update({
    'figure.facecolor': '#07090f', 'axes.facecolor': '#0d1117',
    'text.color': '#b0bcd0', 'axes.labelcolor': '#6b7d9a',
    'xtick.color': '#6b7d9a', 'ytick.color': '#6b7d9a',
    'grid.color': '#21262d', 'axes.edgecolor': '#21262d',
    'font.family': 'DejaVu Sans',
})


# ==============================================================
#  PALETA
# ==============================================================


C_BG1   = '#0d1117'
C_BG2   = '#07090f'
C_ACENT = '#3a7bd5'
C_TEXT  = '#e6edf3'
C_MUTED = '#6b7d9a'
C_GREEN = '#3fb950'
C_RED   = '#f85149'
C_YELL  = '#e3b341'
C_GOLD  = '#f0e68c'
C_LGRE  = '#7ee787'
C_LRED  = '#f0883e'
C_GRID  = '#21262d'


def score_color_hex(v):
    if   v <= 20: return '#f85149'
    elif v <= 40: return '#f0883e'
    elif v <= 60: return '#e3b341'
    elif v <= 80: return '#7ee787'
    else:         return '#3fb950'


def score_color_mpl(v): return score_color_hex(v)


def sesgo_color_hex(s):
    return {'MUY ALCISTA':'#3fb950','ALCISTA':'#7ee787','NEUTRAL':'#e3b341','BAJISTA':'#f0883e','MUY BAJISTA':'#f85149'}.get(s,'#e6edf3')


def clasificar_score(s):
    if   s <= 20: return 'Muy bajo',  '#f85149', '🔴'
    elif s <= 40: return 'Bajo',      '#f0883e', '🟠'
    elif s <= 60: return 'Neutral',   '#e3b341', '🟡'
    elif s <= 80: return 'Alto',      '#7ee787', '🟢'
    else:         return 'Muy alto',  '#3fb950', '💚'


# ==============================================================
#  UNIVERSO DE ACTIVOS
# ==============================================================


ACCIONES_POR_INDUSTRIA = {
    'Semiconductores':    ['NVDA','AMD','INTC','TSM','ASML','QCOM','AVGO','MU','AMAT','LRCX'],
    'Software':           ['MSFT','ORCL','CRM','ADBE','SAP','NOW','INTU','WDAY','SNOW','PLTR'],
    'Ciberseguridad':     ['CRWD','PANW','ZS','FTNT','OKTA','S','CYBR','QLYS','TENB'],
    'Cloud/AI':           ['AMZN','GOOGL','META','MSFT','ORCL','IBM','SNOW','MDB','DDOG','NET'],
    'Hardware/Equipos':   ['AAPL','HPQ','HPE','DELL','STX','WDC','NTAP','PSTG','GLW'],
    'Fintech':            ['PYPL','SQ','AFRM','UPST','SOFI','LC','ENVA'],
    'Biotecnología':      ['MRNA','BNTX','REGN','VRTX','BIIB','GILD','AMGN','ILMN','BMRN'],
    'Farmacéuticas':      ['JNJ','PFE','LLY','ABBV','MRK','BMY','AZN','NVO'],
    'Equipos Médicos':    ['MDT','ABT','SYK','BSX','EW','ISRG','ZBH','BAX','BDX','HOLX'],
    'Servicios de Salud': ['UNH','CVS','CI','HUM','CNC','MOH','ELV','DVA'],
    'Bancos':             ['JPM','BAC','WFC','C','GS','MS','USB','TFC','PNC','COF'],
    'Seguros':            ['BRK-B','CB','AON','MMC','TRV','AIG','PRU','MET','ALL','AFL'],
    'Mercados Capitales': ['BX','KKR','APO','ARES','CG','BAM','SCHW','IBKR'],
    'Bancos Regionales':  ['FITB','HBAN','RF','CFG','ZION','FHN','WTFC'],
    'Finanzas Diversif.': ['V','MA','AXP','DFS','SYF','ALLY','CACC'],
    'Petróleo Integrado': ['XOM','CVX','COP','EOG','DVN','MPC','VLO'],
    'Energía Renovable':  ['NEE','ENPH','SEDG','FSLR','RUN','PLUG','BE','AES'],
    'Gas Natural':        ['LNG','AR','EQT','RRC','SWN','CNX'],
    'Energía Solar':      ['FSLR','ENPH','SEDG','MAXN','CSIQ','JKS','RUN'],
    'Aeroespacial':       ['BA','RTX','LMT','NOC','GD','HII','TDG','HEICO','CW'],
    'Transporte':         ['UPS','FDX','UNP','CSX','NSC','JBHT','ODFL','XPO'],
    'Construcción':       ['CAT','DE','EMR','ETN','HON','GE','ROK','AME','PH','IR'],
    'Defensa':            ['LMT','RTX','NOC','GD','HII','KTOS','AVAV','BWXT'],
    'Retail':             ['AMZN','WMT','TGT','COST','HD','LOW','TJX','ROST','DG','DLTR'],
    'Autos':              ['TSLA','GM','F','TM','NIO','RIVN','LCID','XPEV'],
    'Hotelería/Viajes':   ['MAR','HLT','H','IHG','ABNB','BKNG','EXPE'],
    'E-commerce':         ['AMZN','SHOP','ETSY','EBAY','W','CHWY','SE','MELI','PDD'],
    'Alimentos':          ['KHC','GIS','CPB','SJM','MKC','CAG','POST'],
    'Bebidas':            ['KO','PEP','MNST','STZ','BUD','TAP','CELH'],
    'Minería Oro':        ['NEM','GOLD','AEM','WPM','KGC','AG','PAAS','CDE','HL'],
    'Cobre/Metales':      ['FCX','SCCO','TECK','HBM','CLF','NUE','STLD','CMC'],
    'Químicos':           ['LIN','APD','DD','DOW','LYB','EMN','CE'],
    'Acero':              ['NUE','STLD','CLF','RS','CMC','X','MT'],
    'Eléctricas':         ['NEE','DUK','SO','D','AEP','EXC','XEL','ED','ETR'],
    'Agua':               ['AWK','WTR','WTRG','SJW','MSEX'],
    'REIT Comercial':     ['SPG','O','VICI','NNN','BXP','KIM','REG'],
    'REIT Industrial':    ['PLD','EGP','FR','REXR','STAG'],
    'REIT Residencial':   ['EQR','AVB','ESS','MAA','UDR','CPT'],
    'Telecomunicaciones': ['T','VZ','TMUS','AMT','CCI','SBAC'],
    'Internet':           ['GOOGL','META','NFLX','SNAP','PINS','RDDT','SPOT'],
    'Argentina':          ['GGAL','BMA','BFR','SUPV','BBAR','CEPU','YPF','PAM','TGS','CRESY','LOMA','VISTA'],
    'Brasil':             ['VALE','ITUB','PBR','BBD','ABEV','NU'],
    'México':             ['WALMEX.MX','AMXL.MX','CEMEXCPO.MX','GFINBURO.MX'],
    'China':              ['BABA','TCEHY','BIDU','JD','NIO','LI','XPEV','BYDDF','PDD','NTES'],
    'India':              ['INFY','WIT','HDB','IBN','VEDL','RDY','TTM'],
    'Europa Tecnología':  ['SAP','ASML','IFNNY','NXPI'],
    'Europa Finanzas':    ['HSBC','BBVA','SAN','DBK.DE','LLOY.L','UBS','ING'],
    'Agro/Fertilizantes': ['MOS','NTR','CF','ADM','BG','FMC','CTVA'],
    'Cripto (ETF/Coin)':  ['BTC-USD','ETH-USD','SOL-USD','BNB-USD','XRP-USD','ADA-USD'],
}


TICKER_INDUSTRY = {}
for ind, lst in ACCIONES_POR_INDUSTRIA.items():
    for t in lst:
        if t not in TICKER_INDUSTRY:
            TICKER_INDUSTRY[t] = ind


ALL_TICKERS = sorted(set(t for lst in ACCIONES_POR_INDUSTRIA.values() for t in lst))


FOREX = {
    'EUR/USD':('EURUSD=X','Majors'),   'GBP/USD':('GBPUSD=X','Majors'),
    'USD/JPY':('USDJPY=X','Majors'),   'USD/CHF':('USDCHF=X','Majors'),
    'USD/CAD':('USDCAD=X','Majors'),   'AUD/USD':('AUDUSD=X','Majors'),
    'NZD/USD':('NZDUSD=X','Majors'),   'USD/CNY':('USDCNY=X','Majors'),
    'EUR/GBP':('EURGBP=X','Crosses EUR'), 'EUR/JPY':('EURJPY=X','Crosses EUR'),
    'EUR/CHF':('EURCHF=X','Crosses EUR'), 'EUR/AUD':('EURAUD=X','Crosses EUR'),
    'GBP/JPY':('GBPJPY=X','Crosses GBP'), 'GBP/AUD':('GBPAUD=X','Crosses GBP'),
    'AUD/JPY':('AUDJPY=X','Crosses AUD'), 'NZD/JPY':('NZDJPY=X','Crosses AUD'),
    'USD/ARS':('USDARS=X','LatAm'), 'USD/BRL':('USDBRL=X','LatAm'),
    'USD/MXN':('USDMXN=X','LatAm'), 'USD/CLP':('USDCLP=X','LatAm'),
    'USD/COP':('USDCOP=X','LatAm'), 'USD/PEN':('USDPEN=X','LatAm'),
}


PAISES = {
    'EE.UU. S&P500':    ('SPY',  'América'),
    'EE.UU. NASDAQ':    ('QQQ',  'América'),
    'EE.UU. DOW':       ('DIA',  'América'),
    'EE.UU. Russell':   ('IWM',  'América'),
    'Argentina':        ('ARGT', 'América'),
    'Brasil':           ('EWZ',  'América'),
    'Japón':            ('EWJ',  'Asia'),
    'China':            ('FXI',  'Asia'),
    'Corea del Sur':    ('EWY',  'Asia'),
    'Alemania':         ('EWG',  'Europa'),
    'Europa general':   ('VGK',  'Europa'),
    'Mercados Emerg.':  ('EEM',  'Global'),
    'India':            ('INDA', 'Asia'),
}


SECTORES = {
    'Tecnología':     ('XLK',  '#3a7bd5'),
    'Salud':          ('XLV',  '#3fb950'),
    'Finanzas':       ('XLF',  '#e3b341'),
    'Consumo Discr.': ('XLY',  '#f0883e'),
    'Consumo Básico': ('XLP',  '#bc8cff'),
    'Energía':        ('XLE',  '#ffa657'),
    'Industriales':   ('XLI',  '#79c0ff'),
    'Materiales':     ('XLB',  '#8b949e'),
    'Utilities':      ('XLU',  '#3fb950'),
    'Real Estate':    ('XLRE', '#f85149'),
    'Comunicaciones': ('XLC',  '#d2a8ff'),
}


MERCADOS_REALES = {
    'Petróleo WTI':  ('CL=F',    'Energía',    '#f0883e'),
    'Petróleo Brent':('BZ=F',    'Energía',    '#ffa657'),
    'Gas Natural':   ('NG=F',    'Energía',    '#79c0ff'),
    'Oro':           ('GC=F',    'Met. Prec.', '#e3b341'),
    'Plata':         ('SI=F',    'Met. Prec.', '#8b949e'),
    'Platino':       ('PL=F',    'Met. Prec.', '#bc8cff'),
    'Cobre':         ('HG=F',    'Met. Ind.',  '#cd7f32'),
    'Mineras Oro':   ('GDX',     'Minería',    '#e3b341'),
    'Mineras Plata': ('SIL',     'Minería',    '#8b949e'),
    'Mineras Cobre': ('COPX',    'Minería',    '#cd7f32'),
    'Soja':          ('ZS=F',    'Agro',       '#3fb950'),
    'Maíz':          ('ZC=F',    'Agro',       '#7ee787'),
    'Trigo':         ('ZW=F',    'Agro',       '#ffa657'),
    'Bitcoin':       ('BTC-USD', 'Cripto',     '#f0883e'),
    'Ethereum':      ('ETH-USD', 'Cripto',     '#7ee787'),
    'Solana':        ('SOL-USD', 'Cripto',     '#bc8cff'),
    'XRP':           ('XRP-USD', 'Cripto',     '#3a7bd5'),
}


COLORES_GRUPO_FX  = {'Majors':'#3a7bd5','Crosses EUR':'#f0883e','Crosses GBP':'#7ee787','Crosses AUD':'#bc8cff','LatAm':'#f85149'}
COLORES_REGION    = {'América':'#3a7bd5','Asia':'#f0883e','Europa':'#7ee787','Global':'#bc8cff'}


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
#  CARGA DATOS CORTO PLAZO
# ==============================================================


@st.cache_data(ttl=1800, show_spinner=False)
def cargar_forex_corto():
    res = {}
    for nombre, (tk, grupo) in FOREX.items():
        try:
            df_v = descargar_datos(tk, '3mo'); df_m = descargar_datos(tk, '1mo')
            if df_v is None: continue
            cl_v = get_close_series(df_v); cl_m = get_close_series(df_m)
            if cl_v is None or cl_m is None or len(cl_v.dropna())<15: continue
            atr = calcular_atr(df_m)
            sa, sn, ss = scores_corto(cl_v, cl_m, atr)
            rsi     = float(calcular_rsi(cl_m, p=7).iloc[-1])
            ret_5d  = float(cl_m.pct_change(5).iloc[-1]*100) if len(cl_m)>=6 else 0
            ret_10d = float(cl_m.pct_change(10).iloc[-1]*100) if len(cl_m)>=11 else 0
            precio  = float(cl_m.iloc[-1])
            hist = cl_m.reset_index(); hist.columns = ['Fecha','Precio']
            res[nombre] = dict(tk=tk, grupo=grupo, sa=sa, sn=sn, ss=ss,
                sf=sa*0.45+sn*0.35+ss*0.20, rsi=rsi, ret_5d=ret_5d, ret_10d=ret_10d,
                precio=precio, accion=señal_accion_corto(sa,sn,ss), hist=hist)
        except: continue
    return res


@st.cache_data(ttl=1800, show_spinner=False)
def cargar_paises_corto():
    res = {}
    for nombre, (tk, region) in PAISES.items():
        try:
            df_v = descargar_datos(tk, '3mo'); df_m = descargar_datos(tk, '1mo')
            if df_v is None: continue
            cl_v = get_close_series(df_v); cl_m = get_close_series(df_m)
            if cl_v is None or cl_m is None or len(cl_v.dropna())<15: continue
            atr = calcular_atr(df_m)
            sa, sn, ss = scores_corto(cl_v, cl_m, atr)
            ret_5d  = float(cl_m.pct_change(5).iloc[-1]*100) if len(cl_m)>=6 else 0
            ret_10d = float(cl_m.pct_change(10).iloc[-1]*100) if len(cl_m)>=11 else 0
            res[nombre] = dict(tk=tk, region=region, sa=sa, sn=sn, ss=ss,
                sf=sa*0.45+sn*0.35+ss*0.20, ret_5d=ret_5d, ret_10d=ret_10d,
                precio=float(cl_m.iloc[-1]), accion=señal_accion_corto(sa,sn,ss))
        except: continue
    return res


@st.cache_data(ttl=1800, show_spinner=False)
def cargar_sectores_corto():
    res = {}
    for nombre, (tk, color) in SECTORES.items():
        try:
            df_v = descargar_datos(tk, '3mo'); df_m = descargar_datos(tk, '1mo')
            if df_v is None: continue
            cl_v = get_close_series(df_v); cl_m = get_close_series(df_m)
            if cl_v is None or cl_m is None or len(cl_v.dropna())<15: continue
            atr = calcular_atr(df_m)
            sa, sn, ss = scores_corto(cl_v, cl_m, atr)
            rsi     = float(calcular_rsi(cl_m, p=7).iloc[-1])
            ret_5d  = float(cl_m.pct_change(5).iloc[-1]*100) if len(cl_m)>=6 else 0
            ret_10d = float(cl_m.pct_change(10).iloc[-1]*100) if len(cl_m)>=11 else 0
            res[nombre] = dict(tk=tk, color=color, sa=sa, sn=sn, ss=ss,
                sf=sa*0.45+sn*0.35+ss*0.20, rsi=rsi, ret_5d=ret_5d, ret_10d=ret_10d,
                precio=float(cl_m.iloc[-1]), accion=señal_accion_corto(sa,sn,ss))
        except: continue
    return res


@st.cache_data(ttl=1800, show_spinner=False)
def cargar_mercados_corto():
    res = {}
    for nombre, (tk, cat, color) in MERCADOS_REALES.items():
        try:
            df_v = descargar_datos(tk, '3mo'); df_m = descargar_datos(tk, '1mo')
            if df_v is None or df_m is None: continue
            cl_v = get_close_series(df_v); cl_m = get_close_series(df_m)
            if cl_v is None or cl_m is None or len(cl_v.dropna())<20: continue
            atr = calcular_atr(df_m)
            sa, sn, ss = scores_corto(cl_v, cl_m, atr)
            rsi     = float(calcular_rsi(cl_m, p=7).iloc[-1])
            ret_5d  = float(cl_m.pct_change(5).iloc[-1]*100) if len(cl_m)>=6 else 0
            ret_10d = float(cl_m.pct_change(10).iloc[-1]*100) if len(cl_m)>=11 else 0
            res[nombre] = dict(tk=tk, cat=cat, color=color, sa=sa, sn=sn, ss=ss,
                sf=sa*0.45+sn*0.35+ss*0.20, rsi=rsi, ret_5d=ret_5d, ret_10d=ret_10d,
                precio=float(cl_m.iloc[-1]), accion=señal_accion_corto(sa,sn,ss))
        except: continue
    return res


@st.cache_data(ttl=1800, show_spinner=False)
def cargar_acciones_corto(industrias_sel):
    res = {}
    for industria in industrias_sel:
        tickers = ACCIONES_POR_INDUSTRIA.get(industria, [])
        res[industria] = {}
        for tk in tickers:
            try:
                df_v = descargar_datos(tk, '3mo'); df_m = descargar_datos(tk, '1mo')
                if df_v is None: continue
                cl_v = get_close_series(df_v); cl_m = get_close_series(df_m)
                if cl_v is None or cl_m is None or len(cl_v.dropna())<15: continue
                atr = calcular_atr(df_m)
                sa, sn, ss = scores_corto(cl_v, cl_m, atr)
                rsi     = float(calcular_rsi(cl_m, p=7).iloc[-1])
                ret_5d  = float(cl_m.pct_change(5).iloc[-1]*100) if len(cl_m)>=6 else 0
                ret_10d = float(cl_m.pct_change(10).iloc[-1]*100) if len(cl_m)>=11 else 0
                res[industria][tk] = dict(sa=sa, sn=sn, ss=ss,
                    sf=sa*0.45+sn*0.35+ss*0.20, rsi=rsi, ret_5d=ret_5d, ret_10d=ret_10d,
                    precio=float(cl_m.iloc[-1]), accion=señal_accion_corto(sa,sn,ss))
            except: continue
    return res


@st.cache_data(ttl=3600, show_spinner=False)
def cargar_resultados_largo(industrias_sel):
    tickers = list(set(t for ind in industrias_sel for t in ACCIONES_POR_INDUSTRIA.get(ind,[])))
    if not tickers: return pd.DataFrame()
    df_all = descargar_bulk(tickers, period='2y')
    if df_all is None: return pd.DataFrame()
    resultados = []
    for tk in tickers:
        precio = get_close_from_bulk(df_all, tk)
        if len(precio) < 150: continue
        r = analizar_largo(tk, precio)
        if r: resultados.append(r)
    if not resultados: return pd.DataFrame()
    df_res = pd.DataFrame(resultados).sort_values('global_score', ascending=False).reset_index(drop=True)
    df_res['rank'] = df_res.index + 1
    return df_res


# ==============================================================
#  HELPERS GRÁFICOS
# ==============================================================


def fmt_precio(p):
    if not p or p <= 0: return 'S/D'
    if p >= 1000: return f'${p:,.0f}'
    if p >= 10:   return f'${p:.2f}'
    return f'${p:.5f}'


def kpi_cards_4(items):
    """items = list of (label, value, sub, accent_color)"""
    cols = st.columns(len(items))
    for col, (label, value, sub, color) in zip(cols, items):
        with col:
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-accent" style="background:{color}"></div>'
                f'<div class="kpi-label">{label}</div>'
                f'<div class="kpi-value">{value}</div>'
                f'<div class="kpi-sub">{sub}</div></div>',
                unsafe_allow_html=True
            )
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)


def grafico_barras_h(items_ord, titulo, color_ant='#3a7bd5'):
    ns   = [n for n,_ in items_ord]
    sas  = [d['sa'] for _,d in items_ord]
    sns_ = [d['sn'] for _,d in items_ord]
    y    = np.arange(len(ns))
    fig, ax = plt.subplots(figsize=(7, max(3, len(ns)*0.52)))
    fig.patch.set_facecolor('#07090f'); ax.set_facecolor('#0d1117')
    col_bars = [score_color_mpl(s) for s in sas]
    brs = ax.barh(y, sas,  color=col_bars, edgecolor='none', height=0.50, alpha=.90, zorder=3)
    ax.barh(y, sns_, color=color_ant, edgecolor='none', height=0.22, alpha=0.35, zorder=3)
    ax.axvline(62, color='#2ea043', ls='--', alpha=.45, lw=.8)
    ax.axvline(38, color='#cf222e', ls='--', alpha=.45, lw=.8)
    ax.fill_betweenx([-0.5,len(ns)-0.5], 62,100, alpha=.04, color='#3fb950')
    ax.fill_betweenx([-0.5,len(ns)-0.5],  0, 38, alpha=.04, color='#f85149')
    ax.set_xlim(0, 118); ax.set_yticks(y)
    ax.set_yticklabels(ns, fontsize=8.5, color='#b0bcd0')
    ax.set_title(titulo, color='#e6edf3', fontsize=10, fontweight='600', pad=7, loc='left', x=0.01)
    for b, s in zip(brs, sas):
        ax.text(s+1, b.get_y()+b.get_height()/2, f'{s:.0f}', va='center', color='#e6edf3', fontsize=8, fontweight='600')
    ax.spines['top'].set_color(C_ACENT); ax.spines['top'].set_linewidth(1.5)
    ax.grid(axis='x', alpha=.12, zorder=0); ax.tick_params(colors='#6b7d9a')
    ax.set_xlabel('Score Acumulación', color='#6b7d9a', fontsize=7.5)
    plt.tight_layout(pad=1.2)
    return fig


def grafico_momentum(pares_ord):
    ns    = [n for n,_ in pares_ord]
    r5    = [d.get('ret_5d',0) for _,d in pares_ord]
    r10   = [d.get('ret_10d',0) for _,d in pares_ord]
    x_all = np.arange(len(ns))
    fig, ax = plt.subplots(figsize=(max(10, len(ns)*0.5), 4.5))
    fig.patch.set_facecolor('#07090f'); ax.set_facecolor('#0d1117')
    ax.bar(x_all-.2, r5,  width=.36, color=['#2ea043' if v>=0 else '#cf222e' for v in r5],  alpha=.95, label='5 días', zorder=3)
    ax.bar(x_all+.2, r10, width=.36, color=['#3a7bd5' if v>=0 else '#bc8cff' for v in r10], alpha=.65, label='10 días', zorder=3)
    ax.axhline(0, color='#b0bcd0', lw=.6, alpha=.4)
    ax.set_xticks(x_all); ax.set_xticklabels(ns, rotation=45, ha='right', fontsize=8)
    ax.set_ylabel('Retorno %', fontsize=8.5)
    ax.legend(facecolor='#0d1117', labelcolor='#b0bcd0', fontsize=8, framealpha=.8)
    ax.grid(axis='y', alpha=.12, zorder=0)
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    plt.tight_layout(pad=1.2)
    return fig


def grafico_heatmap(datos_dict, titulo='Heatmap'):
    df_heat = pd.DataFrame({
        'Acum':  {n:d['sa'] for n,d in datos_dict.items()},
        'Antic': {n:d['sn'] for n,d in datos_dict.items()},
        'Sent':  {n:d['ss'] for n,d in datos_dict.items()},
    }).sort_values('Acum', ascending=False)
    fig, ax = plt.subplots(figsize=(5, max(4, len(datos_dict)*0.35)))
    fig.patch.set_facecolor('#07090f')
    sb.heatmap(df_heat, annot=True, fmt='.0f', cmap='RdYlGn', vmin=0, vmax=100,
               ax=ax, linewidths=.35, linecolor='#07090f', cbar_kws={'label':'Score','shrink':.7})
    ax.set_title(titulo, color='#e6edf3', fontsize=10, pad=8, loc='left')
    ax.tick_params(colors='#b0bcd0')
    ax.set_xticklabels(ax.get_xticklabels(), rotation=0, fontsize=8.5)
    ax.set_yticklabels(ax.get_yticklabels(), rotation=0, fontsize=7.5)
    plt.tight_layout(pad=1.2)
    return fig


def grafico_cuadrante(datos_dict, colores_dict=None, titulo='Mapa de Oportunidades'):
    fig, ax = plt.subplots(figsize=(8.5, 6.5))
    fig.patch.set_facecolor('#07090f'); ax.set_facecolor('#0d1117')
    for nombre, d in datos_dict.items():
        clave = d.get('grupo', d.get('region', d.get('cat','')))
        col_p = colores_dict.get(clave, C_ACENT) if colores_dict else C_ACENT
        ax.scatter(d['sn'], d['sa'], color=col_p, s=130, zorder=5, edgecolors='#07090f', linewidths=1.1, alpha=.9)
        ax.annotate(nombre[:12], (d['sn'], d['sa']), xytext=(5,3), textcoords='offset points', fontsize=7.5, color='#b0bcd0')
    ax.axhline(62, color='#3fb950', ls='--', alpha=.35, lw=.9)
    ax.axhline(38, color='#f85149', ls='--', alpha=.35, lw=.9)
    ax.axvline(55, color='#e3b341', ls='--', alpha=.35, lw=.9)
    ax.fill_between([55,100],[62,62],[100,100], alpha=.05, color='#3fb950')
    ax.fill_between([0,55],  [0,0],  [38,38],  alpha=.05, color='#f85149')
    ax.text(77, 97, '✦ Zona de entrada', color='#3fb950', fontsize=8, alpha=.8, ha='center', fontweight='600')
    ax.text(25,  4, '✦ Zona de cautela', color='#f85149', fontsize=8, alpha=.8, ha='center', fontweight='600')
    ax.set_xlabel('Score Anticipación →', fontsize=9.5)
    ax.set_ylabel('← Score Acumulación', fontsize=9.5)
    ax.set_title(titulo, color='#e6edf3', fontsize=10.5, pad=8)
    ax.set_xlim(0,100); ax.set_ylim(0,100)
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    ax.grid(alpha=.10); ax.tick_params(colors='#6b7d9a')
    plt.tight_layout(pad=1.2)
    return fig


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


def tabla_corto(filas_dict, key_suffix=''):
    filas = []
    for nombre, d in sorted(filas_dict.items(), key=lambda x: x[1]['sa'], reverse=True):
        filas.append({'Nombre': nombre, 'Acum': round(d['sa'],1), 'Antic': round(d['sn'],1),
            'Sent': round(d['ss'],1), 'RSI': round(d.get('rsi',0),1),
            'Ret 5d %': round(d.get('ret_5d',0),2), 'Ret 10d %': round(d.get('ret_10d',0),2),
            'Precio': fmt_precio(d.get('precio',0)), 'Señal': d['accion']})
    df = pd.DataFrame(filas)


    fc1, fc2 = st.columns([2,2])
    with fc1:
        señales_u = ['Todas'] + sorted(df['Señal'].unique().tolist())
        f_señal = st.selectbox('Señal', señales_u, key=f'tc_señal_{key_suffix}')
    with fc2:
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
    df_f = df_f[df_f['Acum'].between(*f_acum) & df_f['Antic'].between(*f_antic)
                & df_f['Sent'].between(*f_sent) & df_f['RSI'].between(*f_rsi)
                & df_f['Ret 5d %'].between(*f_ret5) & df_f['Ret 10d %'].between(*f_ret10)]


    styled = _apply_score_style(df_f, ['Acum','Antic','Sent'], ['Ret 5d %','Ret 10d %'])
    st.dataframe(styled, use_container_width=True, height=min(600, max(150, len(df_f)*35+45)))
    st.caption(f'{len(df_f)} activos mostrados de {len(df)} totales')


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


    st.markdown('<div style="margin-top:12px">', unsafe_allow_html=True)
    tickers_disponibles = df_f['Ticker'].tolist()
    if tickers_disponibles:
        cc1, cc2 = st.columns([3,1])
        with cc1:
            ticker_click = st.selectbox(
                '🔍 Analizar ticker de la tabla',
                ['— Seleccioná un ticker —'] + tickers_disponibles,
                key=f'tl_ticker_click_{key_suffix}'
            )
        with cc2:
            st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)
            if st.button('▶ Ver análisis completo', use_container_width=True, key=f'tl_go_{key_suffix}'):
                if ticker_click and ticker_click != '— Seleccioná un ticker —':
                    st.session_state['ticker_from_table'] = ticker_click
                    st.session_state['nav_horizonte'] = 'buscador'
                    st.session_state['nav_modulo']    = 'buscador'
                    st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)



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


@st.cache_data(ttl=3600, show_spinner=False)
def analizar_fundamental(ticker, industria):
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


def _senal_color(s):
    if 'COMPRA' in s: return '#3fb950', 'rgba(63,185,80,0.12)'
    if 'MANTENER' in s: return '#e3b341', 'rgba(227,179,65,0.12)'
    return '#f85149', 'rgba(248,81,73,0.12)'


# ==============================================================
#  MÓDULO BUSCADOR UNIVERSAL
# ==============================================================


def modulo_buscador():
    prefill = st.session_state.get('ticker_from_table', '')


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
            Ingresá el símbolo de cualquier activo: acciones, ETF, cripto, divisas o commodities.<br>
            Obtenés análisis completo de <b style="color:#f0883e">corto plazo</b> (percentiles históricos)
            y <b style="color:#3fb950">largo plazo</b> (cuantitativo 2 años).
          </div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)


    col_inp, col_btn = st.columns([4, 1])
    with col_inp:
        ticker_manual = st.text_input(
            'Símbolo del activo',
            value=prefill,
            key='ticker_manual_input',
            placeholder='Ej: NVDA · AAPL · BTC-USD · EURUSD=X · GC=F · GGAL',
            label_visibility='collapsed',
        )
    with col_btn:
        analizar = st.button('▶ Analizar', use_container_width=True, key='btn_buscar')


    st.markdown("""
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;margin-bottom:4px">
      <span style="font-size:10px;color:#3a4a5f;font-weight:600;align-self:center">Ejemplos →</span>
      <code style="background:#161b22;border:1px solid #21262d;color:#8b949e;padding:2px 8px;border-radius:5px;font-size:10px">NVDA</code>
      <code style="background:#161b22;border:1px solid #21262d;color:#8b949e;padding:2px 8px;border-radius:5px;font-size:10px">AAPL</code>
      <code style="background:#161b22;border:1px solid #21262d;color:#8b949e;padding:2px 8px;border-radius:5px;font-size:10px">TSLA</code>
      <code style="background:#161b22;border:1px solid #21262d;color:#8b949e;padding:2px 8px;border-radius:5px;font-size:10px">BTC-USD</code>
      <code style="background:#161b22;border:1px solid #21262d;color:#8b949e;padding:2px 8px;border-radius:5px;font-size:10px">ETH-USD</code>
      <code style="background:#161b22;border:1px solid #21262d;color:#8b949e;padding:2px 8px;border-radius:5px;font-size:10px">EURUSD=X</code>
      <code style="background:#161b22;border:1px solid #21262d;color:#8b949e;padding:2px 8px;border-radius:5px;font-size:10px">GC=F</code>
      <code style="background:#161b22;border:1px solid #21262d;color:#8b949e;padding:2px 8px;border-radius:5px;font-size:10px">GGAL</code>
      <code style="background:#161b22;border:1px solid #21262d;color:#8b949e;padding:2px 8px;border-radius:5px;font-size:10px">YPF</code>
    </div>
    """, unsafe_allow_html=True)


    ticker_final = ticker_manual.strip().upper() if ticker_manual else ''


    auto_run = bool(prefill and ticker_final == prefill.upper())
    if prefill:
        st.session_state['ticker_from_table'] = ''


    if not ticker_final or not (analizar or auto_run):
        st.markdown("""
        <div style="border:1px dashed #21262d;border-radius:12px;padding:48px;text-align:center;margin-top:20px">
          <div style="font-size:44px;margin-bottom:14px;opacity:.6">📊</div>
          <div style="color:#6b7d9a;font-size:13px;font-weight:500;line-height:1.8">
            Escribí el ticker arriba y presioná <b style="color:#e6edf3">Analizar</b><br>
            para ver el análisis completo del activo.
          </div>
        </div>
        """, unsafe_allow_html=True)
        return


    _renderizar_buscador(ticker_final)


def _renderizar_buscador(ticker):
    st.markdown(f'<div class="sec-title">Resultados para: {ticker}</div>', unsafe_allow_html=True)


    industria = TICKER_INDUSTRY.get(ticker, 'Externo / Manual')


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
            with c1: st.metric('RSI (7)', f'{rsi:.1f}')
            with c2: st.metric('Ret 5d', f'{ret_5d:+.2f}%')
            with c3: st.metric('Ret 10d', f'{ret_10d:+.2f}%')
            with c4: st.metric('Precio', fmt_precio(precio))
            with c5: st.metric('Industria', industria[:15])


            st.markdown(f'<div style="margin:10px 0"><span class="signal-pill">{señal}</span></div>', unsafe_allow_html=True)


            precios = cl_m.values
            if len(precios) > 2:
                fig_l, ax_l = plt.subplots(figsize=(10, 3))
                fig_l.patch.set_facecolor('#07090f'); ax_l.set_facecolor('#0d1117')
                trend_c = '#3fb950' if precios[-1]>=precios[0] else '#f85149'
                ax_l.fill_between(range(len(precios)), precios, alpha=0.12, color='#3a7bd5')
                ax_l.plot(range(len(precios)), precios, color=trend_c, lw=1.8, zorder=4)
                ax_l.scatter(len(precios)-1, precios[-1], color=trend_c, s=55, zorder=5)
                ax_l.grid(axis='y', alpha=.12)
                ax_l.spines['top'].set_visible(False); ax_l.spines['right'].set_visible(False)
                ret_p = (precios[-1]/precios[0]-1)*100
                ax_l.set_title(f'{ticker} — 30 días ({ret_p:+.2f}%)', color=trend_c, fontsize=10, fontweight='600', loc='left')
                plt.tight_layout(pad=1.2)
                st.pyplot(fig_l, use_container_width=True); plt.close(fig_l)
        else:
            st.info('Datos insuficientes para el análisis de corto plazo.')


    st.markdown('---')


    st.markdown('### 📈 Análisis Largo Plazo (2 años cuantitativo)')
    with st.spinner('Cargando 2 años de datos...'):
        df_tk = descargar_datos(ticker, '2y')


    if df_tk is None or df_tk.empty:
        st.warning('No hay datos suficientes para el análisis de largo plazo.')
        return


    cl = get_close_series(df_tk)
    if cl is None or len(cl) < 150:
        st.info('Se necesitan al menos 150 sesiones para el análisis cuantitativo.')
        return


    r = analizar_largo(ticker, cl)
    if r is None:
        st.warning('No se pudo calcular el análisis cuantitativo.')
        return


    accent = score_color_hex(r['global_score'])
    kpi_cards_4([
        ('Global Score',  f"{int(r['global_score'])}/100",  r['sesgo'], accent),
        ('Trend Score',   f"{int(r['trend_score'])}/100",   f"GC: {'Sí' if r['golden_cross'] else 'No'} · MACD: {'Alc' if r['macd_bull'] else 'Baj'}", score_color_hex(r['trend_score'])),
        ('MR Score',      f"{int(r['mr_score'])}/100",      f"Z: {r['zscore']:+.2f} · RSI: {r['rsi']:.1f}", score_color_hex(r['mr_score'])),
        ('Risk Score',    f"{int(r['risk_score'])}/100",    f"Sharpe: {r['sharpe']:.2f} · DD: {r['max_dd']:.1f}%", score_color_hex(r['risk_score'])),
    ])


    c1,c2,c3,c4 = st.columns(4)
    with c1: st.metric('Ret. Anual', f"{r['ret_anual']:+.1f}%")
    with c2: st.metric('Volatilidad', f"{r['vol_anual']:.1f}%")
    with c3: st.metric('Max DrawDown', f"{r['max_dd']:.1f}%")
    with c4: st.metric('Hurst', f"{r['hurst']:.3f}")


    interp = interpretar_largo(r)
    sesgo_class = {'MUY ALCISTA':'sesgo-muy-alc','ALCISTA':'sesgo-alc','NEUTRAL':'sesgo-neu',
                   'BAJISTA':'sesgo-baj','MUY BAJISTA':'sesgo-muy-baj'}.get(r['sesgo'],'')
    st.markdown(f"""
    <div class="interp-card">
      <div class="interp-header">{ticker} · {industria} · <span class="{sesgo_class}">{r['sesgo']}</span></div>
      {interp}
    </div>
    """, unsafe_allow_html=True)


    tab_g1, tab_g2, tab_g3 = st.tabs(['📈 Precio + Bollinger', '📊 RSI & MACD', '📉 Drawdown'])


    with tab_g1:
        ma20_tk = cl.rolling(20).mean(); std20_tk = cl.rolling(20).std()
        upper_tk = ma20_tk + 2*std20_tk; lower_tk = ma20_tk - 2*std20_tk
        ma50_tk = cl.rolling(50).mean(); ma200_tk = cl.rolling(200).mean()
        fig_p, ax_p = plt.subplots(figsize=(12, 5))
        fig_p.patch.set_facecolor('#07090f'); ax_p.set_facecolor('#0d1117')
        ax_p.fill_between(cl.index, lower_tk, upper_tk, alpha=0.08, color='#3a7bd5')
        ax_p.plot(cl.index, upper_tk, color='#3a7bd5', lw=0.8, alpha=0.5)
        ax_p.plot(cl.index, lower_tk, color='#3a7bd5', lw=0.8, alpha=0.5)
        ax_p.plot(cl.index, ma20_tk, color='#e3b341', lw=1.2, ls='--', label='MA20')
        ax_p.plot(cl.index, ma50_tk, color='#3fb950', lw=1.2, label='MA50')
        ax_p.plot(cl.index, ma200_tk, color='#f85149', lw=1.2, label='MA200')
        trend_c = '#3fb950' if float(cl.iloc[-1]) >= float(cl.iloc[0]) else '#f85149'
        ax_p.plot(cl.index, cl, color=trend_c, lw=1.8, zorder=4, label='Precio')
        ax_p.fill_between(cl.index, cl, float(cl.min()), alpha=0.06, color=trend_c)
        ax_p.set_title(f'{ticker} — Precio + Indicadores (2 años)', color='#e6edf3', fontsize=11, fontweight='600')
        ax_p.legend(fontsize=8, facecolor='#0d1117', labelcolor='#b0bcd0', ncol=3)
        ax_p.grid(alpha=.12); ax_p.tick_params(colors='#6b7d9a')
        ax_p.spines['top'].set_visible(False); ax_p.spines['right'].set_visible(False)
        plt.tight_layout(pad=1.2)
        st.pyplot(fig_p, use_container_width=True); plt.close(fig_p)


    with tab_g2:
        rsi_tk    = calcular_rsi(cl, 14)
        macd_tk   = cl.ewm(span=12,adjust=False).mean() - cl.ewm(span=26,adjust=False).mean()
        signal_tk = macd_tk.ewm(span=9,adjust=False).mean()
        hist_macd = macd_tk - signal_tk
        fig_rs, (ax_rsi, ax_macd) = plt.subplots(2,1, figsize=(12,6), gridspec_kw={'hspace':0.3})
        fig_rs.patch.set_facecolor('#07090f')
        for ax_i in [ax_rsi, ax_macd]: ax_i.set_facecolor('#0d1117')
        ax_rsi.plot(rsi_tk.index, rsi_tk, color='#bc8cff', lw=1.5)
        ax_rsi.axhline(70, color='#f85149', ls='--', alpha=.5, lw=.9)
        ax_rsi.axhline(30, color='#3fb950', ls='--', alpha=.5, lw=.9)
        ax_rsi.fill_between(rsi_tk.index, 30, rsi_tk.values, where=rsi_tk.values<30, alpha=.2, color='#3fb950')
        ax_rsi.fill_between(rsi_tk.index, 70, rsi_tk.values, where=rsi_tk.values>70, alpha=.2, color='#f85149')
        ax_rsi.set_title('RSI (14)', color='#e6edf3', fontsize=9.5, fontweight='600')
        ax_rsi.set_ylim(0,100); ax_rsi.grid(alpha=.12); ax_rsi.tick_params(colors='#6b7d9a')
        ax_macd.plot(macd_tk.index, macd_tk, color='#3a7bd5', lw=1.3, label='MACD')
        ax_macd.plot(signal_tk.index, signal_tk, color='#f0883e', lw=1.1, label='Signal')
        ax_macd.bar(hist_macd.index, hist_macd, color=['#3fb950' if v>=0 else '#f85149' for v in hist_macd], alpha=.5)
        ax_macd.axhline(0, color='#b0bcd0', lw=.6, alpha=.4)
        ax_macd.set_title('MACD (12,26,9)', color='#e6edf3', fontsize=9.5, fontweight='600')
        ax_macd.legend(fontsize=8, facecolor='#0d1117', labelcolor='#b0bcd0')
        ax_macd.grid(alpha=.12); ax_macd.tick_params(colors='#6b7d9a')
        for ax_i in [ax_rsi, ax_macd]:
            ax_i.spines['top'].set_visible(False); ax_i.spines['right'].set_visible(False)
        plt.tight_layout(pad=1.2)
        st.pyplot(fig_rs, use_container_width=True); plt.close(fig_rs)


    with tab_g3:
        retornos_tk = cl.pct_change().dropna()
        cum_tk = (1 + retornos_tk).cumprod()
        dd_tk  = (cum_tk / cum_tk.cummax()) - 1
        fig_dd, ax_dd = plt.subplots(figsize=(12, 4))
        fig_dd.patch.set_facecolor('#07090f'); ax_dd.set_facecolor('#0d1117')
        ax_dd.fill_between(dd_tk.index, dd_tk*100, 0, alpha=0.6, color='#f85149')
        ax_dd.plot(dd_tk.index, dd_tk*100, color='#f85149', lw=1.2)
        ax_dd.axhline(0, color='#b0bcd0', lw=.6, alpha=.4)
        ax_dd.axhline(-20, color='#e3b341', ls='--', alpha=.4, lw=.8, label='-20%')
        ax_dd.axhline(-40, color='#f85149', ls='--', alpha=.4, lw=.8, label='-40%')
        ax_dd.set_title(f'{ticker} — Drawdown desde máximo · Máx: {float(dd_tk.min()*100):.1f}%', color='#e6edf3', fontsize=10, fontweight='600')
        ax_dd.legend(fontsize=8, facecolor='#0d1117', labelcolor='#b0bcd0')
        ax_dd.grid(alpha=.12); ax_dd.tick_params(colors='#6b7d9a')
        ax_dd.spines['top'].set_visible(False); ax_dd.spines['right'].set_visible(False)
        plt.tight_layout(pad=1.2)
        st.pyplot(fig_dd, use_container_width=True); plt.close(fig_dd)


    # ── ANÁLISIS FUNDAMENTAL ──────────────────────────────────────────────
    st.markdown('---')
    st.markdown('### 📊 Análisis Fundamental')

    industria_fund = TICKER_INDUSTRY.get(ticker, 'Sin Clasificar')
    sector_fund    = SECTOR_MAP_FUND.get(industria_fund, 'Sin Clasificar')

    with st.spinner('Descargando ratios fundamentales...'):
        res_fund = analizar_fundamental(ticker, industria_fund)

    if res_fund is None:
        st.info('No se encontraron datos fundamentales para este activo (puede ser cripto, forex o commodity sin estados financieros).')
    else:
        sc_col_b, sc_bg_b = _senal_color(res_fund['senal_final'])
        bench_b = res_fund['bench']

        # KPIs fundamentales
        kpi_cards_4([
            ('Señal Fundamental', res_fund['senal_final'],
             f"✅ {res_fund['n_ok']} positivas · ⚠️ {res_fund['n_alt']} alertas", sc_col_b),
            ('Valuación',
             f"PER {_fmt_num(res_fund.get('per'))}x · P/B {_fmt_num(res_fund.get('pb'))}x",
             f"EV/EBITDA: {_fmt_num(res_fund.get('ev_ebitda'))}x · PEG: {_fmt_num(res_fund.get('peg'))}",
             '#3a7bd5'),
            ('Rentabilidad',
             f"ROE {_fmt_pct(res_fund.get('roe'))} · ROA {_fmt_pct(res_fund.get('roa'))}",
             f"Mg.Bruto: {_fmt_pct(res_fund.get('gross_margin'))} · Mg.Op: {_fmt_pct(res_fund.get('op_margin'))}",
             '#3fb950'),
            ('Solvencia / Flujo',
             f"D/E {_fmt_num(res_fund.get('debt_equity'))}x · CR {_fmt_num(res_fund.get('curr_ratio'))}x",
             f"FCF: {_fmt_big(res_fund.get('fcf'))} · Beta: {_fmt_num(res_fund.get('beta'))}",
             '#e3b341'),
        ])

        # Métricas secundarias
        mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
        with mc1: st.metric('Sector', sector_fund[:16])
        with mc2: st.metric('Industria', industria_fund[:16])
        with mc3: st.metric('Rev. Growth', _fmt_pct(res_fund.get('revenue_growth')))
        with mc4: st.metric('Div. Yield', _fmt_pct(res_fund.get('div_yield')))
        with mc5: st.metric('Precio Obj.', fmt_precio(res_fund.get('target_price')))
        with mc6: st.metric('Rec. Analistas', res_fund.get('recommendation') or 'N/D')

        # Benchmark del sector
        st.markdown(f"""
        <div style='background:rgba(58,123,213,0.07);border:1px solid rgba(58,123,213,0.2);
             border-radius:8px;padding:10px 16px;margin:10px 0;font-size:11px;color:#b0bcd0;line-height:1.8'>
          <b style='color:#3a7bd5;font-size:12px'>BENCHMARK {sector_fund.upper()}</b><br>
          {bench_b['descripcion']}<br>
          <b style='color:#6b7d9a'>Métricas clave:</b> {' · '.join(bench_b.get('metricas_clave', []))}
        </div>
        """, unsafe_allow_html=True)

        # Señales en dos columnas
        ok_sigs_b  = [(t,m) for t,m in res_fund['senales'] if t=='OK']
        alt_sigs_b = [(t,m) for t,m in res_fund['senales'] if t=='ALT']
        col_sig1, col_sig2 = st.columns(2)
        with col_sig1:
            st.markdown('<div style="font-size:11px;font-weight:700;color:#3fb950;margin-bottom:4px">✅ SEÑALES POSITIVAS</div>', unsafe_allow_html=True)
            if ok_sigs_b:
                for _, msg in ok_sigs_b:
                    st.markdown(f'<div style="font-size:11px;color:#3fb950;padding:2px 0;border-bottom:1px solid #21262d">• {msg}</div>', unsafe_allow_html=True)
            else:
                st.markdown('<div style="font-size:11px;color:#6b7d9a">Sin señales positivas detectadas</div>', unsafe_allow_html=True)
        with col_sig2:
            st.markdown('<div style="font-size:11px;font-weight:700;color:#f85149;margin-bottom:4px">⚠️ ALERTAS</div>', unsafe_allow_html=True)
            if alt_sigs_b:
                for _, msg in alt_sigs_b:
                    st.markdown(f'<div style="font-size:11px;color:#f85149;padding:2px 0;border-bottom:1px solid #21262d">• {msg}</div>', unsafe_allow_html=True)
            else:
                st.markdown('<div style="font-size:11px;color:#6b7d9a">Sin alertas detectadas</div>', unsafe_allow_html=True)

        # Vs benchmark sectorial
        if res_fund['sector_senales']:
            st.markdown('<div style="margin-top:12px;font-size:11px;font-weight:700;color:#3a7bd5;margin-bottom:4px">📐 COMPARATIVA VS BENCHMARK SECTORIAL</div>', unsafe_allow_html=True)
            for tipo, msg in res_fund['sector_senales']:
                col_vs_b = '#3fb950' if tipo == 'POS' else '#f85149'
                ico_vs_b = '✔' if tipo == 'POS' else '✘'
                st.markdown(f'<div style="font-size:11px;color:{col_vs_b};padding:3px 0;border-bottom:1px solid #21262d">{ico_vs_b} {msg}</div>', unsafe_allow_html=True)


# ==============================================================
#  ESTADO DE NAVEGACIÓN
# ==============================================================


for key, default in [
    ('nav_horizonte', 'corto'),
    ('nav_modulo', 'resumen'),
    ('nav_ind_sel_global', list(ACCIONES_POR_INDUSTRIA.keys())[:2]),
    ('nav_ind_sel_corto', list(ACCIONES_POR_INDUSTRIA.keys())[:2]),
    ('nav_ind_sel_largo', list(ACCIONES_POR_INDUSTRIA.keys())[:2]),
    ('fund_ind_sel', list(ACCIONES_POR_INDUSTRIA.keys())[:2]),
    ('nav_grupos_fx', list(dict.fromkeys(v[1] for v in FOREX.values()))),
    ('ticker_from_table', ''),
    ('ticker_manual', ''),
    ('nav_search_ticker', ''),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ==============================================================
#  TOP NAV BAR
# ==============================================================


_now_str = datetime.now().strftime('%H:%M')
_h_color = {'corto': '#f0883e', 'largo': '#3fb950', 'buscador': '#3a7bd5'}
_h_label = {'corto': 'Corto Plazo', 'largo': 'Largo Plazo', 'buscador': 'Búsqueda'}


HORIZONTE = st.session_state['nav_horizonte']
MODULO    = st.session_state['nav_modulo']


st.markdown(f"""
<div class="topbar-wrap">
  <div class="topbar-inner">
    <div class="topbar-brand">
      <div class="topbar-brand-icon">📡</div>
      <div>
        <div class="topbar-brand-name">QuantAnalyzer</div>
        <div class="topbar-brand-sub">Live · Yahoo Finance</div>
      </div>
    </div>
    <div class="topbar-divider"></div>
    <div style="display:flex;align-items:center;gap:6px;margin-right:16px;flex-shrink:0">
      <span style="width:7px;height:7px;border-radius:50%;background:{_h_color.get(HORIZONTE,'#3a7bd5')};display:inline-block"></span>
      <span style="font-size:11px;font-weight:600;color:{_h_color.get(HORIZONTE,'#3a7bd5')}">{_h_label.get(HORIZONTE,'')}</span>
    </div>
    <div class="topbar-divider"></div>
    <div style="flex:1"></div>
    <div class="topbar-time">🕐 {_now_str}</div>
  </div>
</div>
""", unsafe_allow_html=True)


st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)


def _nav_btn(col, label, key, is_active, on_click_state, on_click_val_h=None, on_click_val_m=None):
    with col:
        cont_key = f'navcont_{key}'
        with st.container(key=cont_key):
            clicked = st.button(label, use_container_width=True, key=key)
        if is_active:
            st.markdown(f"""
            <style>
            .st-key-{cont_key} button {{
                background: linear-gradient(135deg, #1a7f37, #2ea043) !important;
                color: #ffffff !important;
                border-color: #2ea043 !important;
                font-weight: 700 !important;
                box-shadow: 0 0 0 3px rgba(46,160,67,0.18), 0 2px 8px rgba(46,160,67,0.25) !important;
            }}
            .st-key-{cont_key} button:hover {{
                background: linear-gradient(135deg, #238636, #3fb950) !important;
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


_c = st.columns([1.1, 1.1, 0.05, 1, 1, 1, 1, 1, 1, 0.05, 2.0, 0.8])


_nav_btn(_c[0], '⚡ Corto Plazo', 'nav_h_corto',
         HORIZONTE=='corto', None, 'corto', 'resumen')
_nav_btn(_c[1], '📈 Largo Plazo', 'nav_h_largo',
         HORIZONTE=='largo', None, 'largo', 'ranking')


# Buscador global siempre visible
with _c[10]:
    _search_val = st.text_input('', placeholder='🔍  Ticker: NVDA, AAPL, GGAL...',
                                 label_visibility='collapsed', key='nav_global_search')
with _c[11]:
    _search_btn = st.button('Buscar', key='nav_global_search_btn', use_container_width=True)

if _search_btn and _search_val.strip():
    _tk_nav = _search_val.strip().upper()
    st.session_state['ticker_from_table'] = _tk_nav
    st.session_state['nav_horizonte'] = 'buscador'
    st.session_state['nav_modulo']    = 'buscador'
    st.rerun()


if HORIZONTE == 'corto':
    _mods_corto = [
        ('💱 Forex',    'forex',    3),
        ('🌍 Países',   'paises',   4),
        ('📊 Sectores', 'sectores', 5),
        ('🛢️ Mercados', 'mercados', 6),
        ('📈 Acciones', 'acciones', 7),
        ('🎯 Top-Down', 'topdown',  8),
    ]
    for label, mod_key, col_idx in _mods_corto:
        _nav_btn(_c[col_idx], label, f'nav_{mod_key}',
                 MODULO==mod_key, None, None, mod_key)


elif HORIZONTE == 'largo':
    _mods_largo = [
        ('📋 Ranking',      'ranking',      3),
        ('🔄 Reversión',    'reversion',    4),
        ('🏭 Industria',    'industria',    5),
        ('🔍 Ticker',       'ticker',       6),
        ('📊 Fundamental',  'fundamental',  7),
    ]
    for label, mod_key, col_idx in _mods_largo:
        _nav_btn(_c[col_idx], label, f'nav_{mod_key}',
                 MODULO==mod_key, None, None, mod_key)


with _c[9]:
    with st.container(key='nav_refresh_cont'):
        if st.button('↺', use_container_width=True, key='nav_refresh'):
            st.cache_data.clear(); st.rerun()
st.markdown("""
<style>
.st-key-nav_refresh_cont button {
    background: transparent !important;
    color: #6b7d9a !important;
    border-color: #21262d !important;
    font-size: 11px !important;
}
.st-key-nav_refresh_cont button:hover {
    background: #161b22 !important;
    color: #e6edf3 !important;
    border-color: #3a4a5a !important;
}
</style>
""", unsafe_allow_html=True)


st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)


HORIZONTE = st.session_state['nav_horizonte']
MODULO    = st.session_state['nav_modulo']


# ==============================================================
#  PAGE HEADER
# ==============================================================


titulos = {
    'buscador':  ('Buscador Universal', '🔍', 'Análisis completo por ticker — corto y largo plazo'),
    'forex':     ('Análisis Forex', '💱', 'Pares de divisas — ranking y oportunidades de acumulación'),
    'paises':    ('Países / Índices Globales', '🌍', 'Índices nacionales y regionales — flujo de capital macro'),
    'sectores':  ('Sectores S&P500', '📊', '11 sectores GICS — rotación y momentum'),
    'mercados':  ('Commodities · Metales · Cripto', '🛢️', 'Mercados reales globales — energía, metales, agro, digital'),
    'acciones':  ('Acciones por Industria', '📈', 'Ranking por sector — oportunidades de corto plazo'),
    'topdown':   ('Resumen Top-Down', '🎯', 'Vista ejecutiva macro → sector → acción'),
    'ranking':   ('Ranking Cuantitativo', '📋', 'Global Score · Trend Score · MR Score · Risk Score'),
    'reversion': ('Candidatos a Reversión', '🔄', 'Sobreventa estadística — Z-Score · Bollinger · RSI < 35'),
    'industria': ('Análisis por Industria', '🏭', 'Comparativa cuantitativa sectorial con interpretación'),
    'ticker':      ('Análisis Individual', '🔍', 'Detalle cuantitativo completo para un ticker específico'),
    'resumen':     ('Resumen Top-Down', '🎯', 'Vista ejecutiva multi-nivel — macro a micro'),
    'fundamental': ('Análisis Fundamental', '📊', 'Ratios financieros · Benchmarks por sector · Señales de valuación'),
}
titulo_h, icono_h, subtitulo_h = titulos.get(MODULO, ('Analizador', '📡', ''))


badge_map = {
    'corto':    ('#f0883e', 'rgba(240,136,62,0.12)', 'CORTO PLAZO'),
    'largo':    ('#3fb950', 'rgba(63,185,80,0.10)',  'LARGO PLAZO'),
    'buscador': ('#3a7bd5', 'rgba(58,123,213,0.12)', 'BÚSQUEDA'),
}
badge_color, badge_bg, badge_txt = badge_map.get(HORIZONTE, ('#3a7bd5','rgba(58,123,213,0.12)',''))


st.markdown(f"""
<div class="page-header">
  <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:16px">
    <div>
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:5px">
        <span style="font-size:22px;line-height:1">{icono_h}</span>
        <span class="page-title">{titulo_h}</span>
        <span style="padding:3px 10px;border-radius:20px;font-size:9px;font-weight:700;
          letter-spacing:1px;text-transform:uppercase;background:{badge_bg};
          border:1px solid {badge_color};color:{badge_color}">{badge_txt}</span>
      </div>
      <div class="page-sub">{subtitulo_h}</div>
    </div>
    <div style="text-align:right;flex-shrink:0">
      <div style="font-size:11px;color:#3a4a5f;font-family:'JetBrains Mono',monospace">
        {datetime.now().strftime('%d/%m/%Y · %H:%M')}
      </div>
      <div style="font-size:10px;color:#2a3a4f;margin-top:2px">Yahoo Finance</div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)


# ==============================================================
#  RENDERIZADO DE MÓDULOS
# ==============================================================


if MODULO == 'buscador':
    modulo_buscador()


elif HORIZONTE == 'corto':


    if MODULO in ('resumen', 'topdown'):
        st.markdown('<div class="info-banner">Vista ejecutiva Top-Down. Presioná <b>Cargar</b> para analizar todos los niveles.</div>', unsafe_allow_html=True)
        if st.button('▶ Cargar resumen completo', key='btn_td'):
            st.session_state['td_loaded'] = True
        if st.session_state.get('td_loaded'):
            prog = st.progress(0, text='Cargando países...')
            d_p = cargar_paises_corto(); prog.progress(33, 'Sectores...')
            d_s = cargar_sectores_corto(); prog.progress(66, 'Mercados...')
            d_m = cargar_mercados_corto(); prog.progress(100, '✅ Listo'); prog.empty()
            fuentes = [(l,d,c) for l,d,c in [('Países',d_p,'#3a7bd5'),('Sectores',d_s,'#3fb950'),('Mercados',d_m,'#f0883e')] if d]
            if fuentes:
                fig_td, axes_td = plt.subplots(1, len(fuentes), figsize=(5*len(fuentes), 8))
                fig_td.patch.set_facecolor('#07090f')
                if len(fuentes)==1: axes_td=[axes_td]
                for ax_td, (label, dd, col_td) in zip(axes_td, fuentes):
                    ax_td.set_facecolor('#0d1117')
                    top_items = sorted(dd.items(), key=lambda x: x[1]['sa'], reverse=True)[:12]
                    ns_td=[n[:14] for n,_ in top_items]; sas_td=[d['sa'] for _,d in top_items]
                    sns_td=[d['sn'] for _,d in top_items]; y_td=np.arange(len(ns_td))
                    brs_td = ax_td.barh(y_td, sas_td, color=[score_color_mpl(s) for s in sas_td], edgecolor='none', height=0.52, alpha=.88)
                    ax_td.barh(y_td, sns_td, color=col_td, edgecolor='none', height=0.22, alpha=0.32)
                    ax_td.axvline(62, color='#3fb950', ls=':', alpha=.4)
                    ax_td.axvline(38, color='#f85149', ls=':', alpha=.4)
                    ax_td.set_xlim(0,118); ax_td.set_yticks(y_td)
                    ax_td.set_yticklabels(ns_td, fontsize=8)
                    ax_td.set_title(label, color='#e6edf3', fontsize=10, fontweight='600', pad=5)
                    for b, s in zip(brs_td, sas_td):
                        ax_td.text(s+1, b.get_y()+b.get_height()/2, f'{s:.0f}', va='center', color='white', fontsize=7.5)
                    ax_td.spines['top'].set_color(col_td); ax_td.grid(axis='x', alpha=.15)
                plt.suptitle('Top-Down: mejores oportunidades por nivel', color='#e6edf3', fontsize=12, fontweight='bold', y=1.01)
                plt.tight_layout(pad=1.5)
                st.pyplot(fig_td, use_container_width=True); plt.close(fig_td)
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
        tab1, tab2, tab3, tab4 = st.tabs(['📊 Scores','📈 Momentum','🗺️ Cuadrante','📋 Ranking'])
        with tab1:
            grupos_en = [g for g in grupos_disp if g in grupos_sel and any(d['grupo']==g for d in datos_f.values())]
            for i in range(0, len(grupos_en), 2):
                cols = st.columns(2)
                for j, grupo in enumerate(grupos_en[i:i+2]):
                    items = sorted([(n,d) for n,d in datos_f.items() if d['grupo']==grupo], key=lambda x: x[1]['sa'], reverse=True)
                    if not items: continue
                    fig = grafico_barras_h(items, grupo, COLORES_GRUPO_FX.get(grupo, C_ACENT))
                    with cols[j]: st.pyplot(fig, use_container_width=True); plt.close(fig)
        with tab2:
            fig2 = grafico_momentum(sorted(datos_f.items(), key=lambda x: x[1]['ret_5d'], reverse=True))
            st.pyplot(fig2, use_container_width=True); plt.close(fig2)
        with tab3:
            c_m, _ = st.columns([2,1])
            with c_m:
                fig3 = grafico_cuadrante(datos_f, COLORES_GRUPO_FX, 'Mapa Oportunidades Forex')
                st.pyplot(fig3, use_container_width=True); plt.close(fig3)
        with tab4:
            tabla_corto(datos_f)


    elif MODULO == 'paises':
        with st.spinner('Descargando países...'):
            datos_p = cargar_paises_corto()
        if not datos_p: st.error('Sin datos.'); st.stop()
        tab1, tab2, tab3, tab4 = st.tabs(['📊 Scores','📈 Momentum','🗺️ Cuadrante','📋 Ranking'])
        with tab1:
            regiones = list(dict.fromkeys(d['region'] for d in datos_p.values()))
            for i in range(0, len(regiones), 2):
                cols = st.columns(2)
                for j, region in enumerate(regiones[i:i+2]):
                    items = sorted([(n,d) for n,d in datos_p.items() if d['region']==region], key=lambda x: x[1]['sa'], reverse=True)
                    if not items: continue
                    fig = grafico_barras_h(items, region, COLORES_REGION.get(region, C_ACENT))
                    with cols[j]: st.pyplot(fig, use_container_width=True); plt.close(fig)
        with tab2:
            fig2 = grafico_momentum(sorted(datos_p.items(), key=lambda x: x[1]['ret_5d'], reverse=True))
            st.pyplot(fig2, use_container_width=True); plt.close(fig2)
        with tab3:
            c_m, _ = st.columns([2,1])
            with c_m:
                fig3 = grafico_cuadrante(datos_p, COLORES_REGION, 'Mapa Oportunidades Países')
                st.pyplot(fig3, use_container_width=True); plt.close(fig3)
        with tab4:
            tabla_corto(datos_p)


    elif MODULO == 'sectores':
        with st.spinner('Descargando sectores...'):
            datos_s = cargar_sectores_corto()
        if not datos_s: st.error('Sin datos.'); st.stop()
        tab1, tab2, tab3, tab4 = st.tabs(['📊 Scores','📈 Momentum','🗺️ Cuadrante','📋 Ranking'])
        with tab1:
            items_ord = sorted(datos_s.items(), key=lambda x: x[1]['sa'], reverse=True)
            fig = grafico_barras_h(items_ord, 'S&P500 — Sectores')
            st.pyplot(fig, use_container_width=True); plt.close(fig)
        with tab2:
            fig2 = grafico_momentum(sorted(datos_s.items(), key=lambda x: x[1]['ret_5d'], reverse=True))
            st.pyplot(fig2, use_container_width=True); plt.close(fig2)
        with tab3:
            c_m, _ = st.columns([2,1])
            with c_m:
                fig3 = grafico_cuadrante(datos_s, None, 'Mapa Oportunidades Sectores')
                st.pyplot(fig3, use_container_width=True); plt.close(fig3)
        with tab4:
            tabla_corto(datos_s)


    elif MODULO == 'mercados':
        with st.spinner('Descargando commodities...'):
            datos_m = cargar_mercados_corto()
        if not datos_m: st.error('Sin datos.'); st.stop()
        tab1, tab2, tab3, tab4 = st.tabs(['📊 Por categoría','📈 Momentum','🗺️ Cuadrante','📋 Ranking'])
        with tab1:
            cats = list(dict.fromkeys(d['cat'] for d in datos_m.values()))
            for i in range(0, len(cats), 2):
                cols = st.columns(2)
                for j, cat in enumerate(cats[i:i+2]):
                    items = sorted([(n,d) for n,d in datos_m.items() if d['cat']==cat], key=lambda x: x[1]['sa'], reverse=True)
                    if not items: continue
                    fig = grafico_barras_h(items, cat)
                    with cols[j]: st.pyplot(fig, use_container_width=True); plt.close(fig)
        with tab2:
            fig2 = grafico_momentum(sorted(datos_m.items(), key=lambda x: x[1]['ret_5d'], reverse=True))
            st.pyplot(fig2, use_container_width=True); plt.close(fig2)
        with tab3:
            c_m, _ = st.columns([2,1])
            with c_m:
                fig3 = grafico_cuadrante(datos_m, None, 'Mapa Mercados Reales')
                st.pyplot(fig3, use_container_width=True); plt.close(fig3)
        with tab4:
            tabla_corto(datos_m)


    elif MODULO == 'acciones':
        ind_disp_c = list(ACCIONES_POR_INDUSTRIA.keys())
        ind_sel_c  = st.multiselect('Industrias', ind_disp_c, default=st.session_state['nav_ind_sel_corto'], key='acc_ind_sel')
        st.session_state['nav_ind_sel_corto'] = ind_sel_c
        if not ind_sel_c:
            st.info('Seleccioná al menos una industria.')
            st.stop()
        with st.spinner(f'Analizando {len(ind_sel_c)} industrias...'):
            datos_acc_c = cargar_acciones_corto(tuple(ind_sel_c))
        datos_acc_c = {ind: tks for ind, tks in datos_acc_c.items() if tks}
        if not datos_acc_c: st.error('Sin datos.'); st.stop()
        todas_c = {tk: d for ind, tks in datos_acc_c.items() for tk, d in tks.items()}
        tab1, tab2, tab3 = st.tabs(['📊 Por industria','🗺️ Cuadrante','📋 Ranking'])
        with tab1:
            for industria, tickers in datos_acc_c.items():
                if not tickers: continue
                st.markdown(f'<div class="sec-title">📂 {industria}</div>', unsafe_allow_html=True)
                items_ord = sorted(tickers.items(), key=lambda x: x[1]['sa'], reverse=True)
                fig = grafico_barras_h(items_ord, industria)
                st.pyplot(fig, use_container_width=True); plt.close(fig)
        with tab2:
            c_m, _ = st.columns([2,1])
            with c_m:
                fig3 = grafico_cuadrante(todas_c, None, 'Mapa Oportunidades Acciones')
                st.pyplot(fig3, use_container_width=True); plt.close(fig3)
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


            tickers_disp = df_show_a['Ticker'].tolist()
            if tickers_disp:
                cca1, cca2 = st.columns([3,1])
                with cca1:
                    tk_click_a = st.selectbox('🔍 Analizar ticker de la tabla',
                        ['— Seleccioná —'] + tickers_disp, key='acc_corto_click')
                with cca2:
                    st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)
                    if st.button('▶ Ver análisis completo', use_container_width=True, key='acc_corto_go'):
                        if tk_click_a and tk_click_a != '— Seleccioná —':
                            st.session_state['ticker_from_table'] = tk_click_a
                            st.session_state['nav_horizonte'] = 'buscador'
                            st.session_state['nav_modulo']    = 'buscador'
                            st.rerun()


elif HORIZONTE == 'largo':
    if MODULO == 'fundamental':
        pass  # handled by modulo_fundamental() below
    else:
        ind_disp = list(ACCIONES_POR_INDUSTRIA.keys())
        _largo_default = st.session_state.get('nav_ind_sel_global',
                         st.session_state.get('nav_ind_sel_largo', ind_disp[:2]))
        ind_sel  = st.multiselect('Industrias a analizar (2 años)', ind_disp,
                                   default=_largo_default, key='largo_ind_sel')
        st.session_state['nav_ind_sel_largo']  = ind_sel
        st.session_state['nav_ind_sel_global'] = ind_sel
        st.session_state['fund_ind_sel']       = ind_sel


        if not ind_sel:
            st.info('Seleccioná al menos una industria.')
            st.stop()


        if MODULO == 'ranking':
            with st.spinner(f'Descargando 2 años de datos — {len(ind_sel)} industrias...'):
                df_res_l = cargar_resultados_largo(tuple(ind_sel))
            if df_res_l.empty: st.error('Sin datos.'); st.stop()
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
                fig_dist, axes_dist = plt.subplots(1, 3, figsize=(14, 4))
                fig_dist.patch.set_facecolor('#07090f')
                for ax_d, col_d, titulo_d in zip(axes_dist, ['trend_score','mr_score','global_score'],
                                                  ['Trend Score','MR Score','Global Score']):
                    ax_d.set_facecolor('#0d1117')
                    vals = df_res_l[col_d].values
                    ax_d.hist(vals, bins=20, color=C_ACENT, alpha=0.8, edgecolor='#07090f')
                    ax_d.axvline(vals.mean(), color='#f0883e', lw=1.5, ls='--', label=f'Media: {vals.mean():.1f}')
                    ax_d.axvline(70, color='#3fb950', lw=1, ls=':', alpha=.6)
                    ax_d.axvline(30, color='#f85149', lw=1, ls=':', alpha=.6)
                    ax_d.set_title(titulo_d, color='#e6edf3', fontsize=10, fontweight='600')
                    ax_d.legend(fontsize=8, facecolor='#0d1117', labelcolor='#b0bcd0')
                    ax_d.grid(alpha=.12); ax_d.tick_params(colors='#6b7d9a')
                plt.tight_layout(pad=1.5)
                st.pyplot(fig_dist, use_container_width=True); plt.close(fig_dist)
            with tab3:
                datos_cuad = {r['ticker']:{'sa':r['trend_score'],'sn':r['mr_score'],'ss':r['risk_score'],'grupo':r['industria']} for _,r in df_res_l.iterrows()}
                c_m, _ = st.columns([2,1])
                with c_m:
                    fig_c = grafico_cuadrante(datos_cuad, None, 'Trend Score vs MR Score')
                    st.pyplot(fig_c, use_container_width=True); plt.close(fig_c)


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
                accent = score_color_hex(r['global_score'])
                kpi_cards_4([
                    ('Global Score',  f"{int(r['global_score'])}/100",  r['sesgo'], accent),
                    ('Trend Score',   f"{int(r['trend_score'])}/100",   f"GC: {'Sí' if r['golden_cross'] else 'No'} · MACD: {'Alc' if r['macd_bull'] else 'Baj'}", score_color_hex(r['trend_score'])),
                    ('MR Score',      f"{int(r['mr_score'])}/100",      f"Z: {r['zscore']:+.2f} · RSI: {r['rsi']:.1f}", score_color_hex(r['mr_score'])),
                    ('Risk Score',    f"{int(r['risk_score'])}/100",    f"Sharpe: {r['sharpe']:.2f} · DD: {r['max_dd']:.1f}%", score_color_hex(r['risk_score'])),
                ])
                c1,c2,c3,c4 = st.columns(4)
                with c1: st.metric('Ret. Anual', f"{r['ret_anual']:+.1f}%")
                with c2: st.metric('Volatilidad', f"{r['vol_anual']:.1f}%")
                with c3: st.metric('Max DrawDown', f"{r['max_dd']:.1f}%")
                with c4: st.metric('Hurst', f"{r['hurst']:.3f}")
                interp = interpretar_largo(r)
                sesgo_class = {'MUY ALCISTA':'sesgo-muy-alc','ALCISTA':'sesgo-alc','NEUTRAL':'sesgo-neu',
                               'BAJISTA':'sesgo-baj','MUY BAJISTA':'sesgo-muy-baj'}.get(r['sesgo'],'')
                st.markdown(f"""
                <div class="interp-card">
                  <div class="interp-header">{ticker_sel} · {r['industria']} · <span class="{sesgo_class}">{r['sesgo']}</span></div>
                  {interp}
                </div>
                """, unsafe_allow_html=True)
                tab_g1, tab_g2, tab_g3 = st.tabs(['📈 Precio + Bollinger','📊 RSI & MACD','📉 Drawdown'])
                with tab_g1:
                    ma20_tk=cl.rolling(20).mean(); std20_tk=cl.rolling(20).std()
                    upper_tk=ma20_tk+2*std20_tk; lower_tk=ma20_tk-2*std20_tk
                    ma50_tk=cl.rolling(50).mean(); ma200_tk=cl.rolling(200).mean()
                    fig_p, ax_p = plt.subplots(figsize=(12, 5))
                    fig_p.patch.set_facecolor('#07090f'); ax_p.set_facecolor('#0d1117')
                    ax_p.fill_between(cl.index, lower_tk, upper_tk, alpha=0.08, color='#3a7bd5')
                    ax_p.plot(cl.index, upper_tk, color='#3a7bd5', lw=0.8, alpha=0.5)
                    ax_p.plot(cl.index, lower_tk, color='#3a7bd5', lw=0.8, alpha=0.5)
                    ax_p.plot(cl.index, ma20_tk, color='#e3b341', lw=1.2, ls='--', label='MA20')
                    ax_p.plot(cl.index, ma50_tk, color='#3fb950', lw=1.2, label='MA50')
                    ax_p.plot(cl.index, ma200_tk, color='#f85149', lw=1.2, label='MA200')
                    trend_c = '#3fb950' if float(cl.iloc[-1])>=float(cl.iloc[0]) else '#f85149'
                    ax_p.plot(cl.index, cl, color=trend_c, lw=1.8, zorder=4, label='Precio')
                    ax_p.fill_between(cl.index, cl, float(cl.min()), alpha=0.06, color=trend_c)
                    ax_p.set_title(f'{ticker_sel} — Precio + Indicadores (2 años)', color='#e6edf3', fontsize=11, fontweight='600')
                    ax_p.legend(fontsize=8, facecolor='#0d1117', labelcolor='#b0bcd0', ncol=3)
                    ax_p.grid(alpha=.12); ax_p.tick_params(colors='#6b7d9a')
                    ax_p.spines['top'].set_visible(False); ax_p.spines['right'].set_visible(False)
                    plt.tight_layout(pad=1.2); st.pyplot(fig_p, use_container_width=True); plt.close(fig_p)
                with tab_g2:
                    rsi_tk=calcular_rsi(cl, 14); macd_tk=cl.ewm(span=12,adjust=False).mean()-cl.ewm(span=26,adjust=False).mean()
                    signal_tk=macd_tk.ewm(span=9,adjust=False).mean(); hist_macd=macd_tk-signal_tk
                    fig_rs, (ax_rsi, ax_macd) = plt.subplots(2,1, figsize=(12,6), gridspec_kw={'hspace':0.3})
                    fig_rs.patch.set_facecolor('#07090f')
                    for ax_i in [ax_rsi, ax_macd]: ax_i.set_facecolor('#0d1117')
                    ax_rsi.plot(rsi_tk.index, rsi_tk, color='#bc8cff', lw=1.5)
                    ax_rsi.axhline(70, color='#f85149', ls='--', alpha=.5, lw=.9); ax_rsi.axhline(30, color='#3fb950', ls='--', alpha=.5, lw=.9)
                    ax_rsi.fill_between(rsi_tk.index, 30, rsi_tk.values, where=rsi_tk.values<30, alpha=.2, color='#3fb950')
                    ax_rsi.fill_between(rsi_tk.index, 70, rsi_tk.values, where=rsi_tk.values>70, alpha=.2, color='#f85149')
                    ax_rsi.set_title('RSI (14)', color='#e6edf3', fontsize=9.5, fontweight='600')
                    ax_rsi.set_ylim(0,100); ax_rsi.grid(alpha=.12); ax_rsi.tick_params(colors='#6b7d9a')
                    ax_macd.plot(macd_tk.index, macd_tk, color='#3a7bd5', lw=1.3, label='MACD')
                    ax_macd.plot(signal_tk.index, signal_tk, color='#f0883e', lw=1.1, label='Signal')
                    ax_macd.bar(hist_macd.index, hist_macd, color=['#3fb950' if v>=0 else '#f85149' for v in hist_macd], alpha=.5)
                    ax_macd.axhline(0, color='#b0bcd0', lw=.6, alpha=.4)
                    ax_macd.set_title('MACD (12,26,9)', color='#e6edf3', fontsize=9.5, fontweight='600')
                    ax_macd.legend(fontsize=8, facecolor='#0d1117', labelcolor='#b0bcd0')
                    ax_macd.grid(alpha=.12); ax_macd.tick_params(colors='#6b7d9a')
                    for ax_i in [ax_rsi, ax_macd]: ax_i.spines['top'].set_visible(False); ax_i.spines['right'].set_visible(False)
                    plt.tight_layout(pad=1.2); st.pyplot(fig_rs, use_container_width=True); plt.close(fig_rs)
                with tab_g3:
                    retornos_tk=cl.pct_change().dropna(); cum_tk=(1+retornos_tk).cumprod(); dd_tk=(cum_tk/cum_tk.cummax())-1
                    fig_dd, ax_dd = plt.subplots(figsize=(12, 4))
                    fig_dd.patch.set_facecolor('#07090f'); ax_dd.set_facecolor('#0d1117')
                    ax_dd.fill_between(dd_tk.index, dd_tk*100, 0, alpha=0.6, color='#f85149')
                    ax_dd.plot(dd_tk.index, dd_tk*100, color='#f85149', lw=1.2)
                    ax_dd.axhline(0, color='#b0bcd0', lw=.6, alpha=.4)
                    ax_dd.axhline(-20, color='#e3b341', ls='--', alpha=.4, lw=.8, label='-20%')
                    ax_dd.axhline(-40, color='#f85149', ls='--', alpha=.4, lw=.8, label='-40%')
                    ax_dd.set_title(f'{ticker_sel} — Drawdown · Máx: {float(dd_tk.min()*100):.1f}%', color='#e6edf3', fontsize=10, fontweight='600')
                    ax_dd.legend(fontsize=8, facecolor='#0d1117', labelcolor='#b0bcd0')
                    ax_dd.grid(alpha=.12); ax_dd.tick_params(colors='#6b7d9a')
                    ax_dd.spines['top'].set_visible(False); ax_dd.spines['right'].set_visible(False)
                    plt.tight_layout(pad=1.2); st.pyplot(fig_dd, use_container_width=True); plt.close(fig_dd)



def modulo_fundamental():
    ind_disp_f = list(ACCIONES_POR_INDUSTRIA.keys())
    # Sincronizar con estado global de industrias
    _fund_default = st.session_state.get('fund_ind_sel',
                    st.session_state.get('nav_ind_sel_largo',
                    st.session_state.get('nav_ind_sel_global', ind_disp_f[:2])))
    ind_sel_f  = st.multiselect(
        'Industrias a analizar', ind_disp_f,
        default=_fund_default,
        key='fund_ind_sel_widget'
    )
    # Guardar en estado global para que otros módulos lo compartan
    st.session_state['fund_ind_sel'] = ind_sel_f
    st.session_state['nav_ind_sel_global'] = ind_sel_f

    if not ind_sel_f:
        st.info('Seleccioná al menos una industria.')
        return

    # Modo: industria vs ticker único
    tab_modo_f, tab_ticker_f = st.tabs(['🏭 Por Industria', '🔍 Ticker Individual'])

    # ── TAB 1: Por industria ──────────────────────────────────────────────
    with tab_modo_f:
        # Carga automática — sin botón, spinner inline en los cards
        _fund_key = f'fund_cache_{"_".join(sorted(ind_sel_f))}'
        if _fund_key not in st.session_state:
            todos_resultados = {}
            prog_f = st.progress(0, text='⟳ Iniciando descarga...')
            tickers_total = [tk for ind in ind_sel_f for tk in ACCIONES_POR_INDUSTRIA.get(ind, [])]
            procesados = 0
            for industria in ind_sel_f:
                todos_resultados[industria] = []
                for tk in ACCIONES_POR_INDUSTRIA.get(industria, []):
                    r = analizar_fundamental(tk, industria)
                    if r: todos_resultados[industria].append(r)
                    procesados += 1
                    pct = int(procesados / max(len(tickers_total), 1) * 100)
                    prog_f.progress(min(pct, 100), text=f'⟳ {tk} ({procesados}/{len(tickers_total)})...')
            prog_f.empty()
            st.session_state[_fund_key] = todos_resultados
        else:
            todos_resultados = st.session_state[_fund_key]

        total_emp = sum(len(v) for v in todos_resultados.values())
        if total_emp == 0:
            st.error('No se pudieron obtener datos fundamentales.')
            return

        # KPIs globales
        todas_emp = [e for lst in todos_resultados.values() for e in lst]
        n_compra   = sum(1 for e in todas_emp if 'COMPRA' in e['senal_final'])
        n_mantener = sum(1 for e in todas_emp if 'MANTENER' in e['senal_final'])
        n_riesgo   = sum(1 for e in todas_emp if 'RIESGO' in e['senal_final'])
        pct_compra = round(n_compra/max(total_emp,1)*100)
        pct_mantener = round(n_mantener/max(total_emp,1)*100)
        pct_riesgo = round(n_riesgo/max(total_emp,1)*100)
        kpi_cards_4([
            ('Analizadas', str(total_emp), f'{len(ind_sel_f)} industrias seleccionadas', '#3a7bd5'),
            ('Compra Fuerte', str(n_compra),   f'{pct_compra}% del total · ≥ 8 señales OK', '#3fb950'),
            ('Mantener',      str(n_mantener), f'{pct_mantener}% del total · 5-7 señales OK', '#e3b341'),
            ('Riesgo / Vender', str(n_riesgo), f'{pct_riesgo}% del total · < 5 señales OK', '#f85149'),
        ])

        # Tabla global resumen
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

        # ── FILTROS AVANZADOS ─────────────────────────────────────────────
        # ── Chips de filtros activos ──────────────────────────────────────
        _DEFS_CHIP = {
            'per': (0.0,200.0), 'pb': (0.0,30.0), 'eveb': (0.0,60.0),
            'roe': (-50.0,100.0), 'gm': (-20.0,100.0), 'om': (-50.0,60.0),
            'rg': (-50.0,100.0), 'de': (0.0,10.0), 'beta': (0.0,4.0),
            'div': (0.0,20.0), 'ytd': (-80.0,300.0), 'ok': (0,20),
        }
        _NAMES_CHIP = {'per':'PER','pb':'P/B','eveb':'EV/EBITDA','roe':'ROE%',
                       'gm':'Mg.Bruto%','om':'Mg.Op%','rg':'Rev.Growth%',
                       'de':'D/E','beta':'Beta','div':'Div.Yield%','ytd':'YTD%','ok':'OK'}
        _active_chips = []
        for _ck, _cd in _DEFS_CHIP.items():
            _rng_val = st.session_state.get(f'fund_f_{_ck}_rng', _cd)
            if _rng_val != _cd:
                _active_chips.append(f'{_NAMES_CHIP[_ck]}: {_rng_val[0]}–{_rng_val[1]}')
        if st.session_state.get('fund_f_fcf', False):
            _active_chips.append('FCF+')
        if st.session_state.get('fund_f_senal','Todas') != 'Todas':
            _active_chips.append(f"Señal: {st.session_state['fund_f_senal']}")
        if st.session_state.get('fund_f_ind','Todas') != 'Todas':
            _active_chips.append(f"Ind: {st.session_state['fund_f_ind']}")

        if _active_chips:
            _chips_html = ''.join(f'<span class="filter-chip">✕ {c}</span>' for c in _active_chips)
            st.markdown(f'<div style="margin-bottom:8px;line-height:2.2"><b style="font-size:10px;color:#6b7d9a;text-transform:uppercase;letter-spacing:.8px">Filtros activos: </b>{_chips_html}</div>', unsafe_allow_html=True)

        with st.expander('🎛️ Filtros avanzados', expanded=not bool(_active_chips)):
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
                f_per_rng = st.slider('PER', min_value=0.0, max_value=200.0, value=(0.0, 200.0), step=1.0, key='fund_f_per_rng')
            with vrow[1]:
                f_pb_rng = st.slider('P/B', min_value=0.0, max_value=30.0, value=(0.0, 30.0), step=0.5, key='fund_f_pb_rng')
            with vrow[2]:
                f_eveb_rng = st.slider('EV/EBITDA', min_value=0.0, max_value=60.0, value=(0.0, 60.0), step=1.0, key='fund_f_eveb_rng')

            st.markdown('<div style="margin-top:8px;margin-bottom:4px;font-size:11px;color:#6b7d9a;font-weight:700;letter-spacing:.5px">📈 RENTABILIDAD Y MÁRGENES</div>', unsafe_allow_html=True)
            rrow = st.columns(4)
            with rrow[0]:
                f_roe_rng = st.slider('ROE %', min_value=-50.0, max_value=100.0, value=(-50.0, 100.0), step=1.0, key='fund_f_roe_rng')
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
                f_beta_rng = st.slider('Beta', min_value=0.0, max_value=4.0, value=(0.0, 4.0), step=0.1, key='fund_f_beta_rng')
            with srow[2]:
                f_div_rng = st.slider('Div. Yield %', min_value=0.0, max_value=20.0, value=(0.0, 20.0), step=0.5, key='fund_f_div_rng')
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

        # ── APLICAR FILTROS ───────────────────────────────────────────────
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

        _map_f = 'map' if hasattr(df_f2.style, 'map') else 'applymap'
        styled_fund = (df_f2.style
            .set_properties(**{'background-color':'#0d1117','color':'#e6edf3','border':'1px solid #21262d'})
            .pipe(lambda s: getattr(s,_map_f)(style_senal_fund, subset=['Señal']))
            .pipe(lambda s: getattr(s,_map_f)(style_ok,  subset=['OK']))
            .pipe(lambda s: getattr(s,_map_f)(style_alt, subset=['ALT']))
            .set_table_styles([
                {'selector':'th','props':[('background-color','#161b22'),('color','#e6edf3'),
                    ('font-weight','700'),('text-align','center'),
                    ('border-bottom','2px solid #3a7bd5'),('font-size','11px')]},
                {'selector':'td','props':[('text-align','center'),('font-size','11px')]},
            ])
        )
        st.dataframe(styled_fund, use_container_width=True, height=min(700, max(200, len(df_f2)*32+45)))
        st.caption(f'{len(df_f2)} empresas de {len(df_fund)} totales')

        # Detalle por industria con benchmark y señales
        for industria in ind_sel_f:
            emps = todos_resultados.get(industria, [])
            if not emps: continue
            sector_ind = SECTOR_MAP_FUND.get(industria, 'Sin Clasificar')
            bench_ind  = INDUSTRY_BENCHMARKS_FUND.get(sector_ind, DEFAULT_BENCHMARK_FUND)
            best_emp   = max(emps, key=lambda e: e['n_ok'])

            with st.expander(f'📂 {industria}  ·  Sector: {sector_ind}  ·  {len(emps)} empresas  ·  Mejor: {best_emp["ticker"]} ({best_emp["senal_final"]})', expanded=False):
                # Benchmark del sector
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

                    # Señales internas
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

                    # Vs benchmark sector
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
            tk_fund = st.text_input('Ticker', placeholder='Ej: NVDA · AAPL · GGAL · TSLA',
                                    key='fund_ticker_input', label_visibility='collapsed')
        with col_tk2:
            analizar_fund = st.button('▶ Analizar', key='btn_fund_ticker')

        if tk_fund and analizar_fund:
            tk_fund = tk_fund.strip().upper()
            industria_f = TICKER_INDUSTRY.get(tk_fund, 'Sin Clasificar')
            with st.spinner(f'Descargando datos fundamentales para {tk_fund}...'):
                res_f = analizar_fundamental(tk_fund, industria_f)

            if res_f is None:
                st.error(f'No se pudieron obtener datos para {tk_fund}. Verificá el símbolo.')
            else:
                sc_col_f, sc_bg_f = _senal_color(res_f['senal_final'])
                fp_f = _fmt_pct
                fn_f = _fmt_num
                fb_f = _fmt_big

                kpi_cards_4([
                    ('Señal Final', res_f['senal_final'], f"{res_f['n_ok']} OK · {res_f['n_alt']} Alertas", sc_col_f),
                    ('Precio', fmt_precio(res_f.get('precio')), f"Obj: {fmt_precio(res_f.get('target_price'))}", '#3a7bd5'),
                    ('PER / P/B', f"{fn_f(res_f.get('per'))}x / {fn_f(res_f.get('pb'))}x", f"EV/EBITDA: {fn_f(res_f.get('ev_ebitda'))}x", '#e3b341'),
                    ('ROE / Mg.Bruto', f"{fp_f(res_f.get('roe'))} / {fp_f(res_f.get('gross_margin'))}", f"Rev.Growth: {fp_f(res_f.get('revenue_growth'))}", '#3fb950'),
                ])

                c1f, c2f, c3f, c4f, c5f = st.columns(5)
                with c1f: st.metric('Sector', res_f['sector'][:18])
                with c2f: st.metric('Beta', fn_f(res_f.get('beta')))
                with c3f: st.metric('D/E', fn_f(res_f.get('debt_equity')))
                with c4f: st.metric('FCF', fb_f(res_f.get('fcf')))
                with c5f: st.metric('YTD', f"{res_f['alza_ytd']:.1f}%" if res_f.get('alza_ytd') is not None else 'N/D')

                # Benchmark
                bench_f = res_f['bench']
                st.markdown(f"""
                <div style='background:rgba(58,123,213,0.07);border:1px solid rgba(58,123,213,0.2);
                     border-radius:8px;padding:10px 14px;margin:12px 0;font-size:11px;color:#b0bcd0;line-height:1.7'>
                  <b style='color:#3a7bd5'>BENCHMARK {res_f['sector'].upper()}</b><br>
                  {bench_f['descripcion']}
                </div>
                """, unsafe_allow_html=True)

                # Señales en dos columnas
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

                # Vs Sector
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
        st.session_state['fund_ind_sel'] = list(ACCIONES_POR_INDUSTRIA.keys())[:2]
    modulo_fundamental()


# ==============================================================
#  FOOTER
# ==============================================================


st.markdown('<div style="height:24px"></div>', unsafe_allow_html=True)
st.markdown(f"""
<div style='text-align:center;color:#3a4a5a;font-size:10px;padding:14px;
     border-top:1px solid #21262d;margin-top:12px'>
  📡 Analizador Cuantitativo Unificado &nbsp;·&nbsp; Datos: Yahoo Finance &nbsp;·&nbsp;
  Caché: 30 min &nbsp;·&nbsp; {datetime.now().strftime('%d/%m/%Y')} &nbsp;·&nbsp;
  <b>Solo informativo. No constituye asesoramiento financiero.</b>
</div>
""", unsafe_allow_html=True)
