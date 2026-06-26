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
  .block-container { padding: 0 2rem 2rem 2rem !important; max-width: 1400px; }

  /* ── Top nav bar ── */
  .topbar {
    position: sticky; top: 0; z-index: 999;
    background: rgba(7,9,15,0.97);
    border-bottom: 1px solid #21262d;
    padding: 0 2rem;
    display: flex; align-items: center; gap: 2rem;
    height: 56px;
    backdrop-filter: blur(12px);
  }
  .topbar-logo {
    font-size: 14px; font-weight: 700; color: #e6edf3;
    letter-spacing: -0.3px; white-space: nowrap;
    display: flex; align-items: center; gap: 8px;
  }
  .topbar-logo span { color: #3a7bd5; }
  .topbar-sep { width: 1px; height: 24px; background: #21262d; }
  .topbar-nav { display: flex; gap: 4px; flex: 1; overflow-x: auto; }
  .topbar-nav::-webkit-scrollbar { height: 0; }
  .nav-btn {
    padding: 6px 14px; border-radius: 6px; border: none;
    font-size: 12px; font-weight: 500; cursor: pointer;
    white-space: nowrap; transition: all .15s;
    background: transparent; color: #8b949e;
  }
  .nav-btn:hover { background: #161b22; color: #e6edf3; }
  .nav-btn.active { background: #1f3a5f; color: #3a7bd5; font-weight: 600; }
  .nav-badge {
    display: inline-block; margin-left: 5px;
    background: #1f3a5f; color: #3a7bd5;
    font-size: 9px; font-weight: 700;
    padding: 1px 5px; border-radius: 10px;
    vertical-align: middle;
  }

  /* ── Page header ── */
  .page-header {
    padding: 28px 0 20px 0;
    border-bottom: 1px solid #21262d;
    margin-bottom: 24px;
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
  .kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }
  .kpi-card {
    background: #0d1117; border: 1px solid #21262d; border-radius: 10px;
    padding: 16px 18px; position: relative; overflow: hidden; transition: border-color .2s;
  }
  .kpi-card:hover { border-color: #3a7bd5; }
  .kpi-accent { position: absolute; top: 0; left: 0; width: 100%; height: 2px; border-radius: 10px 10px 0 0; }
  .kpi-label { color: #6b7d9a; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }
  .kpi-value { color: #e6edf3; font-size: 20px; font-weight: 700; letter-spacing: -0.5px; font-family: 'JetBrains Mono', monospace; }
  .kpi-sub { color: #6b7d9a; font-size: 11px; margin-top: 4px; }

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

def tabla_corto(filas_dict):
    filas = []
    for nombre, d in sorted(filas_dict.items(), key=lambda x: x[1]['sa'], reverse=True):
        filas.append({'Nombre': nombre, 'Acum': round(d['sa'],1), 'Antic': round(d['sn'],1),
            'Sent': round(d['ss'],1), 'RSI': round(d.get('rsi',0),1),
            'Ret 5d %': round(d.get('ret_5d',0),2), 'Ret 10d %': round(d.get('ret_10d',0),2),
            'Precio': fmt_precio(d.get('precio',0)), 'Señal': d['accion']})
    df = pd.DataFrame(filas)
    styled = _apply_score_style(df, ['Acum','Antic','Sent'], ['Ret 5d %','Ret 10d %'])
    st.dataframe(styled, use_container_width=True, height=min(600, max(150, len(df)*35+45)))

def tabla_largo(df_res):
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
    def sesgo_style(val):
        return {'MUY ALCISTA':'color:#3fb950;font-weight:700','ALCISTA':'color:#7ee787;font-weight:700',
                'NEUTRAL':'color:#e3b341;font-weight:700','BAJISTA':'color:#f0883e;font-weight:700',
                'MUY BAJISTA':'color:#f85149;font-weight:700'}.get(val,'')
    _map = 'map' if hasattr(df_show.style,'map') else 'applymap'
    styled = (_apply_score_style(df_show, ['Trend','MR','Risk','Global'])
              .pipe(lambda s: getattr(s,_map)(sesgo_style, subset=['Sesgo'])))
    st.dataframe(styled, use_container_width=True, height=min(700, max(200, len(df_show)*30+45)))

# ==============================================================
#  MÓDULO BUSCADOR UNIVERSAL
# ==============================================================

def modulo_buscador():
    st.markdown('<div class="search-container">', unsafe_allow_html=True)
    st.markdown('<div class="search-title">🔍 Buscador Universal</div>', unsafe_allow_html=True)
    st.markdown('<div class="search-sub">Ingresá cualquier ticker del universo (acciones, cripto, ETF) y obtené el análisis completo: corto y largo plazo.</div>', unsafe_allow_html=True)

    col_sel, col_btn = st.columns([3,1])
    with col_sel:
        ticker_input = st.selectbox(
            'Seleccioná o escribí un ticker',
            options=[''] + ALL_TICKERS,
            index=0,
            format_func=lambda x: f"{x} — {TICKER_INDUSTRY.get(x,'')}" if x else '— Buscá un ticker —',
            key='buscador_ticker'
        )
    with col_btn:
        st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)
        buscar = st.button('▶ Analizar', use_container_width=True, key='btn_buscar')

    # También permitir texto libre
    ticker_free = st.text_input('O escribí el ticker manualmente (ej: NVDA, BTC-USD, EURUSD=X)', key='ticker_manual', placeholder='NVDA')
    st.markdown('</div>', unsafe_allow_html=True)

    ticker_final = (ticker_free.strip().upper() if ticker_free.strip() else ticker_input)
    if not ticker_final or not (buscar or ticker_free.strip()):
        st.markdown("""
        <div style='background:#0d1117;border:1px dashed #21262d;border-radius:10px;padding:40px;text-align:center;margin-top:8px'>
          <div style='font-size:40px;margin-bottom:12px'>🔍</div>
          <div style='color:#e6edf3;font-size:15px;font-weight:600;margin-bottom:6px'>Buscador de Activos</div>
          <div style='color:#6b7d9a;font-size:12px;line-height:1.7'>
            Seleccioná un ticker del menú o escribilo manualmente.<br>
            Obtendrás análisis de corto plazo (percentil histórico) y largo plazo (cuantitativo 2 años).
          </div>
        </div>
        """, unsafe_allow_html=True)
        return

    _renderizar_buscador(ticker_final)

def _renderizar_buscador(ticker):
    st.markdown(f'<div class="sec-title">Resultados para: {ticker}</div>', unsafe_allow_html=True)

    industria = TICKER_INDUSTRY.get(ticker, 'Externo / Manual')

    # ── CORTO PLAZO ──────────────────────────────────────────
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

            # Mini gráfico precio 30d
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

    # ── LARGO PLAZO ──────────────────────────────────────────
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

    # Interpretación
    interp = interpretar_largo(r)
    sesgo_class = {'MUY ALCISTA':'sesgo-muy-alc','ALCISTA':'sesgo-alc','NEUTRAL':'sesgo-neu',
                   'BAJISTA':'sesgo-baj','MUY BAJISTA':'sesgo-muy-baj'}.get(r['sesgo'],'')
    st.markdown(f"""
    <div class="interp-card">
      <div class="interp-header">{ticker} · {industria} · <span class="{sesgo_class}">{r['sesgo']}</span></div>
      {interp}
    </div>
    """, unsafe_allow_html=True)

    # Gráficos
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

# ==============================================================
#  ESTADO DE NAVEGACIÓN
# ==============================================================

# Init session state
for key, default in [
    ('nav_horizonte', 'corto'),
    ('nav_modulo', 'resumen'),
    ('nav_ind_sel_corto', list(ACCIONES_POR_INDUSTRIA.keys())[:5]),
    ('nav_ind_sel_largo', list(ACCIONES_POR_INDUSTRIA.keys())[:6]),
    ('nav_grupos_fx', list(dict.fromkeys(v[1] for v in FOREX.values()))),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ==============================================================
#  TOP NAV BAR (HTML estático + botones Streamlit)
# ==============================================================

st.markdown("""
<div class="topbar">
  <div class="topbar-logo">📡 <span>Analizador</span> Cuantitativo</div>
  <div class="topbar-sep"></div>
</div>
""", unsafe_allow_html=True)

# Nav usando columnas con botones
nav_cols = st.columns([1,1,1,1,1,1,1,1,1,1,0.5])

HORIZONTE = st.session_state['nav_horizonte']
MODULO    = st.session_state['nav_modulo']

with nav_cols[0]:
    if st.button('⚡ Corto Plazo', use_container_width=True, key='nav_h_corto'):
        st.session_state['nav_horizonte'] = 'corto'
        st.session_state['nav_modulo'] = 'resumen'
        st.rerun()
with nav_cols[1]:
    if st.button('📈 Largo Plazo', use_container_width=True, key='nav_h_largo'):
        st.session_state['nav_horizonte'] = 'largo'
        st.session_state['nav_modulo'] = 'ranking'
        st.rerun()
with nav_cols[2]:
    if st.button('🔍 Buscador', use_container_width=True, key='nav_buscador'):
        st.session_state['nav_horizonte'] = 'buscador'
        st.session_state['nav_modulo'] = 'buscador'
        st.rerun()

if HORIZONTE == 'corto':
    with nav_cols[3]:
        if st.button('💱 Forex', use_container_width=True, key='nav_forex'):
            st.session_state['nav_modulo'] = 'forex'; st.rerun()
    with nav_cols[4]:
        if st.button('🌍 Países', use_container_width=True, key='nav_paises'):
            st.session_state['nav_modulo'] = 'paises'; st.rerun()
    with nav_cols[5]:
        if st.button('📊 Sectores', use_container_width=True, key='nav_sectores'):
            st.session_state['nav_modulo'] = 'sectores'; st.rerun()
    with nav_cols[6]:
        if st.button('🛢️ Mercados', use_container_width=True, key='nav_mercados'):
            st.session_state['nav_modulo'] = 'mercados'; st.rerun()
    with nav_cols[7]:
        if st.button('📈 Acciones', use_container_width=True, key='nav_acciones'):
            st.session_state['nav_modulo'] = 'acciones'; st.rerun()
    with nav_cols[8]:
        if st.button('🎯 Top-Down', use_container_width=True, key='nav_topdown'):
            st.session_state['nav_modulo'] = 'topdown'; st.rerun()

elif HORIZONTE == 'largo':
    with nav_cols[3]:
        if st.button('📋 Ranking', use_container_width=True, key='nav_ranking'):
            st.session_state['nav_modulo'] = 'ranking'; st.rerun()
    with nav_cols[4]:
        if st.button('🔄 Reversión', use_container_width=True, key='nav_rev'):
            st.session_state['nav_modulo'] = 'reversion'; st.rerun()
    with nav_cols[5]:
        if st.button('🏭 Por Industria', use_container_width=True, key='nav_indust'):
            st.session_state['nav_modulo'] = 'industria'; st.rerun()
    with nav_cols[6]:
        if st.button('🔍 Ticker', use_container_width=True, key='nav_ticker'):
            st.session_state['nav_modulo'] = 'ticker'; st.rerun()

with nav_cols[10]:
    if st.button('🔄', use_container_width=True, key='nav_refresh', help='Actualizar datos'):
        st.cache_data.clear(); st.rerun()

st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)

# Actualizar estado local
HORIZONTE = st.session_state['nav_horizonte']
MODULO    = st.session_state['nav_modulo']

# ==============================================================
#  PAGE HEADER
# ==============================================================

titulos = {
    'buscador':  ('🔍 Buscador Universal', 'Análisis completo por ticker — corto y largo plazo'),
    'forex':     ('💱 Análisis Forex', 'Pares de divisas — ranking y oportunidades'),
    'paises':    ('🌍 Países / Índices Globales', 'Índices nacionales y regionales'),
    'sectores':  ('📊 Sectores S&P500', '11 sectores GICS — flujo de capital'),
    'mercados':  ('🛢️ Commodities · Metales · Cripto', 'Mercados reales globales'),
    'acciones':  ('📈 Acciones por Industria', 'Ranking por sector corto plazo'),
    'topdown':   ('🎯 Resumen Top-Down', 'Flujo macro → micro'),
    'ranking':   ('📋 Ranking Cuantitativo', 'Global Score · Trend · MR · Risk'),
    'reversion': ('🔄 Candidatos a Reversión', 'Sobreventa estadística · Z-Score · Bollinger · RSI'),
    'industria': ('🏭 Análisis por Industria', 'Comparativa cuantitativa sectorial'),
    'ticker':    ('🔍 Análisis Individual', 'Detalle cuantitativo por ticker'),
    'resumen':   ('🎯 Resumen Top-Down', 'Vista ejecutiva multi-nivel'),
}
titulo_h, subtitulo_h = titulos.get(MODULO, ('📡 Analizador', ''))

badge_color = '#f0883e' if HORIZONTE == 'corto' else ('#3fb950' if HORIZONTE == 'largo' else '#3a7bd5')
badge_txt   = 'CORTO PLAZO' if HORIZONTE == 'corto' else ('LARGO PLAZO' if HORIZONTE == 'largo' else 'BUSCADOR')

st.markdown(f"""
<div class="page-header">
  <div class="page-title">
    {titulo_h}
    <span style="display:inline-block;margin-left:12px;padding:3px 10px;border-radius:20px;
      font-size:10px;font-weight:700;letter-spacing:0.8px;text-transform:uppercase;
      background:rgba(255,255,255,0.06);border:1px solid {badge_color};color:{badge_color}">
      {badge_txt}
    </span>
  </div>
  <div class="page-sub">{subtitulo_h} &nbsp;·&nbsp; {datetime.now().strftime('%d/%m/%Y %H:%M')}</div>
</div>
""", unsafe_allow_html=True)

# ==============================================================
#  RENDERIZADO DE MÓDULOS
# ==============================================================

# ── BUSCADOR ────────────────────────────────────────────────────

if MODULO == 'buscador':
    modulo_buscador()

# ── CORTO PLAZO ─────────────────────────────────────────────────

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
            señ_u2 = ['Todas'] + sorted(df_acc['Señal'].unique().tolist())
            señ_s2 = st.selectbox('Filtrar señal', señ_u2, key='acc_corto_f')
            df_show_a = df_acc if señ_s2=='Todas' else df_acc[df_acc['Señal']==señ_s2]
            styled = _apply_score_style(df_show_a, ['Acum','Antic','Sent'], ['Ret 5d %','Ret 10d %'])
            st.dataframe(styled, use_container_width=True, height=min(700, max(200, len(df_show_a)*32+45)))

# ── LARGO PLAZO ─────────────────────────────────────────────────

elif HORIZONTE == 'largo':
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
            sesgos_u = ['Todos'] + df_res_l['sesgo'].unique().tolist()
            sesgo_f = st.selectbox('Filtrar sesgo', sesgos_u)
            df_show_l = df_res_l if sesgo_f=='Todos' else df_res_l[df_res_l['sesgo']==sesgo_f]
            tabla_largo(df_show_l)
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
            for col_fmt, fmt in [('Precio',fmt_precio),('BB Inf.',fmt_precio)]:
                df_rv[col_fmt] = df_rv[col_fmt].apply(fmt)
            df_rv['Z-Score'] = df_rv['Z-Score'].apply(lambda x: f'{x:+.2f}')
            df_rv['RSI']     = df_rv['RSI'].apply(lambda x: f'{x:.1f}')
            df_rv['Hurst']   = df_rv['Hurst'].apply(lambda x: f'{x:.3f}')
            df_rv['Ret %']   = df_rv['Ret %'].apply(lambda x: f'{x:+.1f}')
            df_rv['Vol %']   = df_rv['Vol %'].apply(lambda x: f'{x:.1f}')
            df_rv['Sharpe']  = df_rv['Sharpe'].apply(lambda x: f'{x:.2f}')
            df_rv['DD%']     = df_rv['DD%'].apply(lambda x: f'{x:.1f}')
            styled_rev = _apply_score_style(df_rv, ['MR','Risk','Global'])
            st.dataframe(styled_rev, use_container_width=True, height=min(700, max(200, len(df_rv)*32+45)))

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
