import streamlit as st
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sb
import warnings
warnings.filterwarnings('ignore')

st.set_page_config(
    page_title="Análisis Top-Down",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════════════════════
#  CSS
# ══════════════════════════════════════════════════════════════
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
  html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
  .stApp { background-color: #080c14; }
  section[data-testid="stSidebar"] {
      background: linear-gradient(180deg, #0d1117 0%, #080c14 100%);
      border-right: 1px solid #1e2533;
  }
  .main-header {
      background: linear-gradient(135deg, #0d1f3c 0%, #0a1628 50%, #0d1117 100%);
      border: 1px solid #1e3a5f;
      border-radius: 16px;
      padding: 28px 32px;
      margin-bottom: 24px;
      position: relative;
      overflow: hidden;
  }
  .main-header::before {
      content: '';
      position: absolute;
      top: -40px; right: -40px;
      width: 180px; height: 180px;
      background: radial-gradient(circle, rgba(88,166,255,0.08) 0%, transparent 70%);
      border-radius: 50%;
  }
  .main-header h1 { color: #e6edf3 !important; font-size: 26px !important; font-weight: 700 !important; margin: 0 0 6px 0 !important; }
  .main-header p  { color: #8b949e !important; font-size: 13px !important; margin: 0 !important; }
  .kpi-card {
      background: #0d1117;
      border: 1px solid #1e2533;
      border-radius: 12px;
      padding: 16px 20px;
      position: relative;
      overflow: hidden;
      transition: border-color .2s;
  }
  .kpi-card:hover { border-color: #58a6ff; }
  .kpi-card .accent { position:absolute; top:0; left:0; width:100%; height:3px; border-radius:12px 12px 0 0; }
  .kpi-card .label { color: #8b949e; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .8px; margin-bottom: 6px; }
  .kpi-card .value { color: #e6edf3; font-size: 20px; font-weight: 700; letter-spacing: -0.5px; }
  .kpi-card .sub   { color: #8b949e; font-size: 12px; margin-top: 4px; }
  .stTabs [data-baseweb="tab-list"] { background: #0d1117; border-bottom: 1px solid #1e2533; gap: 0; padding: 0; }
  .stTabs [data-baseweb="tab"] { background: transparent; color: #8b949e !important; border: none; padding: 12px 18px; font-weight: 500; font-size: 13px; border-bottom: 2px solid transparent; }
  .stTabs [aria-selected="true"] { color: #58a6ff !important; border-bottom: 2px solid #58a6ff !important; background: transparent !important; }
  .section-title { font-size: 15px; font-weight: 600; color: #e6edf3; margin: 20px 0 12px 0; padding-bottom: 8px; border-bottom: 1px solid #1e2533; }
  .info-banner { background: rgba(88,166,255,0.06); border: 1px solid rgba(88,166,255,0.2); border-radius: 8px; padding: 10px 14px; color: #8b949e; font-size: 12px; margin-bottom: 16px; }
  .signal-pill { display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; background: rgba(88,166,255,0.1); border: 1px solid rgba(88,166,255,0.3); color: #58a6ff; }
  .sidebar-logo { font-size: 17px; font-weight: 700; color: #e6edf3; padding: 12px 0 4px 0; letter-spacing: -0.3px; }
  .sidebar-sub  { font-size: 11px; color: #8b949e; margin-bottom: 16px; }
  h1,h2,h3,h4 { color: #e6edf3 !important; }
  p, label, .stMarkdown { color: #c9d1d9 !important; }
  .stButton > button { background: linear-gradient(135deg, #1f6feb, #388bfd); color: white; border: none; border-radius: 8px; font-weight: 600; font-size: 13px; transition: opacity .2s; }
  .stButton > button:hover { opacity: .85; }
  .stSelectbox > div > div { background: #0d1117 !important; border-color: #1e2533 !important; color: #e6edf3 !important; }
  .stMultiSelect > div > div { background: #0d1117 !important; border-color: #1e2533 !important; }
  hr { border-color: #1e2533 !important; }
  [data-testid="stMetric"] { background: #0d1117; border: 1px solid #1e2533; border-radius: 10px; padding: 12px 16px; }
  [data-testid="stMetricLabel"] { color: #8b949e !important; font-size: 11px !important; }
  [data-testid="stMetricValue"] { color: #e6edf3 !important; }
  .stDataFrame { border-radius: 10px; overflow: hidden; }
</style>
""", unsafe_allow_html=True)

plt.rcParams.update({
    'figure.facecolor': '#080c14', 'axes.facecolor': '#0d1117',
    'text.color': '#c9d1d9', 'axes.labelcolor': '#8b949e',
    'xtick.color': '#8b949e', 'ytick.color': '#8b949e',
    'grid.color': '#1e2533', 'axes.edgecolor': '#1e2533',
    'font.family': 'DejaVu Sans',
})

# ══════════════════════════════════════════════════════════════
#  FUNCIONES BASE
# ══════════════════════════════════════════════════════════════

@st.cache_data(ttl=1800, show_spinner=False)
def descargar_datos(ticker, period='3mo'):
    try:
        import yfinance as yf
        d = yf.download(ticker, period=period, interval='1d', progress=False, auto_adjust=True)
        if d is None or d.empty:
            return None
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
        if 'Close' not in d.columns:
            cols_close = [c for c in d.columns if 'close' in str(c).lower()]
            if cols_close:
                d = d.rename(columns={cols_close[0]: 'Close'})
            else:
                return None
        return d.dropna(subset=['Close'])
    except Exception:
        return None

def get_close(df):
    if df is None: return None
    try:
        if isinstance(df, pd.Series): return df.dropna()
        if 'Close' in df.columns:
            c = df['Close']
            if isinstance(c, pd.DataFrame): c = c.iloc[:, 0]
            return c.dropna()
        for col in df.columns:
            if 'close' in str(col).lower(): return df[col].dropna()
        return None
    except: return None

def calcular_atr(df, p=14):
    if df is None: return None
    try:
        h = df.get('High'); l = df.get('Low'); c = get_close(df)
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

def vol_anual(close, v=20):
    s = pd.Series(close).dropna()
    return s.pct_change().rolling(v).std() * np.sqrt(252) * 100

def clasificar(s):
    if   s <= 20: return 'Miedo Extremo',  '#f85149', '🔴'
    elif s <= 40: return 'Miedo',           '#f0883e', '🟠'
    elif s <= 60: return 'Neutral',         '#e3b341', '🟡'
    elif s <= 80: return 'Codicia',         '#7ee787', '🟢'
    else:         return 'Codicia Extrema', '#3fb950', '💚'

def scores_activo(close_vol, close_mp, atr):
    cv = pd.Series(close_vol).dropna()
    cm = pd.Series(close_mp).dropna()
    if len(cv) < 15 or len(cm) < 5: return 50.0, 50.0, 50.0
    precio_pct = pct_rank(cv)
    rsi_pct    = 100 - pct_rank(calcular_rsi(cv, p=7))
    vol_pct    = 100 - pct_rank(vol_anual(cv, 10))
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

def señal_accion(sa, sn, ss):
    if   sa>=62 and sn>=55:              return '🟢 ACUMULAR'
    elif sa>=62 and sn>=40:              return '🟡 VIGILAR'
    elif sa>=58 and sn<40:               return '🔵 ACUMULAR GRADUAL'
    elif sa<45  and sn>=62 and ss>=62:   return '🚀 TENDENCIA ALCISTA'
    elif sn>=65 and 40<=sa<62:           return '⚡ MOVIMIENTO INMINENTE'
    elif sa<38  and sn<42  and ss>=65:   return '⚠️ MÁXIMOS'
    elif sa>=55 and sn<35  and ss<35:    return '🔴 EVITAR'
    elif sa<38  and sn>=55 and ss<40:    return '🟠 REBOTE'
    else:                                return '⏸️ ESPERAR'

def score_color(v):
    if   v <= 20: return '#f85149'
    elif v <= 40: return '#f0883e'
    elif v <= 60: return '#e3b341'
    elif v <= 80: return '#7ee787'
    else:         return '#3fb950'

def fmt_precio_fx(p):
    if p is None: return '—'
    if p >= 100:  return f'{p:.3f}'
    if p >= 10:   return f'{p:.4f}'
    return f'{p:.5f}'

def fmt_precio_gen(p):
    if not p or p <= 0: return 'S/D'
    if p >= 1000: return f'${p:,.0f}'
    if p >= 10:   return f'${p:.2f}'
    return f'${p:.4f}'

# ══════════════════════════════════════════════════════════════
#  DATOS — DEFINICIÓN DE UNIVERSOS
# ══════════════════════════════════════════════════════════════

FOREX = {
    'EUR/USD':('EURUSD=X','Majors'),   'GBP/USD':('GBPUSD=X','Majors'),
    'USD/JPY':('USDJPY=X','Majors'),   'USD/CHF':('USDCHF=X','Majors'),
    'USD/CAD':('USDCAD=X','Majors'),   'AUD/USD':('AUDUSD=X','Majors'),
    'NZD/USD':('NZDUSD=X','Majors'),   'USD/CNY':('USDCNY=X','Majors'),
    'EUR/GBP':('EURGBP=X','Crosses EUR'), 'EUR/JPY':('EURJPY=X','Crosses EUR'),
    'EUR/CHF':('EURCHF=X','Crosses EUR'), 'EUR/AUD':('EURAUD=X','Crosses EUR'),
    'EUR/CAD':('EURCAD=X','Crosses EUR'), 'EUR/NZD':('EURNZD=X','Crosses EUR'),
    'GBP/JPY':('GBPJPY=X','Crosses GBP'), 'GBP/CHF':('GBPCHF=X','Crosses GBP'),
    'GBP/AUD':('GBPAUD=X','Crosses GBP'), 'GBP/CAD':('GBPCAD=X','Crosses GBP'),
    'GBP/NZD':('GBPNZD=X','Crosses GBP'),
    'AUD/JPY':('AUDJPY=X','Crosses AUD/NZD'), 'AUD/CAD':('AUDCAD=X','Crosses AUD/NZD'),
    'AUD/CHF':('AUDCHF=X','Crosses AUD/NZD'), 'AUD/NZD':('AUDNZD=X','Crosses AUD/NZD'),
    'NZD/JPY':('NZDJPY=X','Crosses AUD/NZD'), 'NZD/CAD':('NZDCAD=X','Crosses AUD/NZD'),
    'NZD/CHF':('NZDCHF=X','Crosses AUD/NZD'),
    'CAD/JPY':('CADJPY=X','Crosses JPY'), 'CHF/JPY':('CHFJPY=X','Crosses JPY'),
    'USD/ARS':('USDARS=X','LatAm'), 'USD/BRL':('USDBRL=X','LatAm'),
    'USD/MXN':('USDMXN=X','LatAm'), 'USD/CLP':('USDCLP=X','LatAm'),
    'USD/COP':('USDCOP=X','LatAm'), 'USD/PEN':('USDPEN=X','LatAm'),
    'USD/UYU':('USDUYU=X','LatAm'),
}
COLORES_GRUPO_FX = {
    'Majors':'#58a6ff', 'Crosses EUR':'#f0883e', 'Crosses GBP':'#7ee787',
    'Crosses AUD/NZD':'#bc8cff', 'Crosses JPY':'#e3b341', 'LatAm':'#f85149',
}
ACCENT_GRUPO_FX = {
    'Majors':'#1f6feb', 'Crosses EUR':'#b35d00', 'Crosses GBP':'#2ea043',
    'Crosses AUD/NZD':'#8250df', 'Crosses JPY':'#9a6700', 'LatAm':'#cf222e',
}

PAISES = {
    'EE.UU. S&P500':    ('SPY',  'América'),
    'EE.UU. NASDAQ':    ('QQQ',  'América'),
    'EE.UU. DOW JONES': ('DIA',  'América'),
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

COLORES_REGION = {'América':'#58a6ff','Asia':'#f0883e','Europa':'#7ee787','Global':'#bc8cff'}

SECTORES = {
    'Tecnología':     ('XLK',  '#58a6ff'),
    'Salud':          ('XLV',  '#7ee787'),
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
    'Petróleo WTI':    ('CL=F',    'Energía',    '#f0883e'),
    'Petróleo Brent':  ('BZ=F',    'Energía',    '#ffa657'),
    'Gas Natural':     ('NG=F',    'Energía',    '#79c0ff'),
    'Gasolina RBOB':   ('RB=F',    'Energía',    '#f85149'),
    'Oro':             ('GC=F',    'Met. Prec.', '#e3b341'),
    'Plata':           ('SI=F',    'Met. Prec.', '#8b949e'),
    'Platino':         ('PL=F',    'Met. Prec.', '#bc8cff'),
    'Paladio':         ('PA=F',    'Met. Prec.', '#d2a8ff'),
    'Cobre':           ('HG=F',    'Met. Ind.',  '#cd7f32'),
    'Acero (ETF)':     ('SLX',     'Met. Ind.',  '#8b949e'),
    'Mineras Oro':     ('GDX',     'Minería',    '#e3b341'),
    'Mineras Jr. Oro': ('GDXJ',    'Minería',    '#ffa657'),
    'Mineras Plata':   ('SIL',     'Minería',    '#8b949e'),
    'Mineras Cobre':   ('COPX',    'Minería',    '#cd7f32'),
    'Soja':            ('ZS=F',    'Agro',       '#3fb950'),
    'Maíz':            ('ZC=F',    'Agro',       '#7ee787'),
    'Trigo':           ('ZW=F',    'Agro',       '#ffa657'),
    'Café':            ('KC=F',    'Agro',       '#cd7f32'),
    'Azúcar':          ('SB=F',    'Agro',       '#f85149'),
    'Bitcoin':         ('BTC-USD', 'Cripto',     '#f0883e'),
    'Ethereum':        ('ETH-USD', 'Cripto',     '#7ee787'),
    'Solana':          ('SOL-USD', 'Cripto',     '#bc8cff'),
    'BNB':             ('BNB-USD', 'Cripto',     '#e3b341'),
    'XRP':             ('XRP-USD', 'Cripto',     '#58a6ff'),
    'Cardano':         ('ADA-USD', 'Cripto',     '#d2a8ff'),
}

INDUSTRIAS = {
    'Tecnología': {
        'Semiconductores':  'SOXX', 'Software':        'IGV',
        'Ciberseguridad':   'CIBR', 'Cloud/AI':        'SKYY',
        'Hardware/Equipos': 'QTEC', 'Fintech':         'FINX',
    },
    'Salud': {
        'Biotecnología':       'IBB',  'Farmacéuticas':      'IHE',
        'Equipos Médicos':     'IHI',  'Servicios de Salud': 'IHF',
        'Genómica':            'ARKG',
    },
    'Finanzas': {
        'Bancos':             'KBE',  'Bancos Regionales':  'KRE',
        'Seguros':            'KIE',  'Mercados Capitales': 'IAI',
        'Finanzas Diversif.': 'VFH',
    },
    'Energía': {
        'Petróleo Integrado': 'IEO',  'Exploración/Prod.':  'XOP',
        'Gas Natural':        'FCG',  'Energía Renovable':  'ICLN',
        'Energía Solar':      'TAN',
    },
    'Industriales': {
        'Aeroespacial': 'ITA', 'Transporte':  'IYT',
        'Construcción': 'ITB', 'Maquinaria':  'XMHQ',
        'Defensa':      'PPA',
    },
    'Consumo Discr.': {
        'Retail': 'XRT', 'Autos': 'CARZ', 'Hotelería/Viajes': 'AWAY',
        'E-commerce': 'IBUY',
    },
    'Consumo Básico': {
        'Alimentos': 'PBJ', 'Supermercados': 'FXG', 'Hogar/Limpieza': 'EZU',
    },
    'Materiales': {
        'Minería Oro':   'GDX',  'Cobre/Metales': 'COPX',
        'Minería Plata': 'SIL',  'Químicos':      'XLB',
        'Acero':         'SLX',
    },
    'Utilities': {
        'Eléctricas': 'IDU', 'Agua': 'PHO', 'Gas Natural Distr.': 'EMLP',
    },
    'Real Estate': {
        'REIT Comercial':   'VNQ',  'REIT Industrial':   'INDS',
        'REIT Residencial': 'REZ',  'REIT Salud':        'WELL',
    },
    'Comunicaciones': {
        'Telecomunicaciones':    'IYZ', 'Internet':             'FDN',
        'Media/Entretenimiento': 'PBS', 'Streaming':            'SUBZ',
    },
}

ACCIONES_POR_INDUSTRIA = {
    'Semiconductores':    ['NVDA','AMD','INTC','TSM','ASML','QCOM','AVGO','MU','AMAT','LRCX'],
    'Software':           ['MSFT','ORCL','CRM','ADBE','SAP','NOW','INTU','WDAY','SNOW','PLTR'],
    'Ciberseguridad':     ['CRWD','PANW','ZS','FTNT','OKTA','S','CYBR','QLYS','TENB','RPD'],
    'Cloud/AI':           ['AMZN','GOOGL','META','MSFT','ORCL','IBM','SNOW','MDB','DDOG','NET'],
    'Hardware/Equipos':   ['AAPL','HPQ','HPE','DELL','STX','WDC','NTAP','PSTG','GLW'],
    'Fintech':            ['PYPL','SQ','AFRM','UPST','SOFI','LC','OPEN','CURO','ENVA'],
    'Biotecnología':      ['MRNA','BNTX','REGN','VRTX','BIIB','GILD','AMGN','ILMN','SGEN','BMRN'],
    'Farmacéuticas':      ['JNJ','PFE','LLY','ABBV','MRK','BMY','AZN','NVO','RHHBY','SNY'],
    'Equipos Médicos':    ['MDT','ABT','SYK','BSX','EW','ISRG','ZBH','BAX','BDX','HOLX'],
    'Servicios de Salud': ['UNH','CVS','CI','HUM','CNC','MOH','ELV','DVA'],
    'Genómica':           ['ILMN','PACB','NVTA','BEAM','CRSP','EDIT','NTLA'],
    'Bancos':             ['JPM','BAC','WFC','C','GS','MS','USB','TFC','PNC','COF'],
    'Seguros':            ['BRK-B','CB','AON','MMC','TRV','AIG','PRU','MET','ALL','AFL'],
    'Mercados Capitales': ['BX','KKR','APO','ARES','CG','BAM','GS','MS','SCHW','IBKR'],
    'Bancos Regionales':  ['FITB','HBAN','RF','CFG','ZION','FHN','WTFC','GBCI'],
    'Finanzas Diversif.': ['V','MA','AXP','DFS','SYF','ALLY','CACC','OMF'],
    'Petróleo Integrado': ['XOM','CVX','COP','EOG','PXD','DVN','MPC','VLO'],
    'Energía Renovable':  ['NEE','ENPH','SEDG','FSLR','RUN','PLUG','BE','ARRY','AES'],
    'Exploración/Prod.':  ['PXD','EOG','DVN','FANG','MRO','APA','OVV','SM','CTRA'],
    'Gas Natural':        ['LNG','AR','EQT','RRC','SWN','CNX'],
    'Energía Solar':      ['FSLR','ENPH','SEDG','ARRY','MAXN','CSIQ','JKS','RUN'],
    'Aeroespacial':       ['BA','RTX','LMT','NOC','GD','HII','TDG','HEICO','SPR','CW'],
    'Transporte':         ['UPS','FDX','UNP','CSX','NSC','JBHT','ODFL','XPO','CHRW'],
    'Construcción':       ['CAT','DE','EMR','ETN','HON','GE','ROK','AME','PH','IR'],
    'Maquinaria':         ['CAT','DE','AGCO','PCAR','CMI','TXT','GGG','FELE'],
    'Defensa':            ['LMT','RTX','NOC','GD','HII','KTOS','AVAV','BWXT'],
    'Retail':             ['AMZN','WMT','TGT','COST','HD','LOW','TJX','ROST','DG','DLTR'],
    'Autos':              ['TSLA','GM','F','TM','STLA','NIO','RIVN','LCID','XPEV'],
    'Hotelería/Viajes':   ['MAR','HLT','H','IHG','WH','ABNB','BKNG','EXPE','TRIP'],
    'E-commerce':         ['AMZN','SHOP','ETSY','EBAY','W','CHWY','SE','MELI','PDD'],
    'Alimentos':          ['KHC','GIS','CPB','SJM','MKC','CAG','POST','LANC'],
    'Bebidas':            ['KO','PEP','MNST','STZ','BUD','TAP','SAM','CELH','COKE'],
    'Supermercados':      ['WMT','KR','ACI','SFM','CASY','GO'],
    'Hogar/Limpieza':     ['PG','CL','KMB','CHD','NWL','SPB'],
    'Minería Oro':        ['NEM','GOLD','AEM','WPM','KGC','AG','PAAS','CDE','HL','EXK'],
    'Cobre/Metales':      ['FCX','SCCO','TECK','HBM','CLF','NUE','STLD','CMC','RS'],
    'Minería Plata':      ['WPM','PAAS','AG','CDE','HL','EXK','SILV','MAG'],
    'Químicos':           ['LIN','APD','DD','DOW','LYB','EMN','CE','HUN'],
    'Acero':              ['NUE','STLD','CLF','RS','CMC','X','MT','TS'],
    'Eléctricas':         ['NEE','DUK','SO','D','AEP','EXC','XEL','ED','ES','ETR'],
    'Agua':               ['AWK','WTR','WTRG','SJW','MSEX'],
    'Gas Natural Distr.': ['OKE','WMB','ET','KMI','TRGP','NI','ATO'],
    'REIT Comercial':     ['SPG','O','VICI','NNN','BXP','KIM','REG','FRT'],
    'REIT Industrial':    ['PLD','EGP','FR','REXR','STAG','LXP'],
    'REIT Residencial':   ['EQR','AVB','ESS','MAA','UDR','CPT'],
    'REIT Salud':         ['WELL','VTR','PEAK','HR','MPW','SBRA','LTC'],
    'Telecomunicaciones': ['T','VZ','TMUS','LUMN','AMT','CCI','SBAC'],
    'Internet':           ['GOOGL','META','NFLX','SNAP','PINS','RDDT','SPOT'],
    'Media/Entretenimiento':['DIS','CMCSA','PARA','WBD','FOX','NYT','NWSA'],
    'Streaming':          ['NFLX','DIS','ROKU','SPOT','PARA','WBD','FUBO'],
}

# ══════════════════════════════════════════════════════════════
#  FUNCIONES DE CARGA POR MÓDULO
# ══════════════════════════════════════════════════════════════

@st.cache_data(ttl=1800, show_spinner=False)
def cargar_forex():
    res = {}
    for nombre, (tk, grupo) in FOREX.items():
        try:
            df_v = descargar_datos(tk, '3mo'); df_m = descargar_datos(tk, '1mo')
            if df_v is None: continue
            cl_v = get_close(df_v); cl_m = get_close(df_m)
            if cl_v is None or cl_m is None or len(cl_v.dropna())<15: continue
            atr = calcular_atr(df_m)
            sa, sn, ss = scores_activo(cl_v, cl_m, atr)
            rsi    = float(calcular_rsi(cl_m, p=7).iloc[-1])
            ret_5d = float(cl_m.pct_change(5).iloc[-1]*100)  if len(cl_m)>=6  else 0
            ret_10d= float(cl_m.pct_change(10).iloc[-1]*100) if len(cl_m)>=11 else 0
            precio = float(cl_m.iloc[-1])
            for v in [rsi, ret_5d, ret_10d]:
                if np.isnan(v): v = 0
            hist = cl_m.reset_index(); hist.columns = ['Fecha','Precio']
            res[nombre] = dict(tk=tk, grupo=grupo, sa=sa, sn=sn, ss=ss,
                sf=sa*0.45+sn*0.35+ss*0.20, rsi=rsi, ret_5d=ret_5d, ret_10d=ret_10d,
                precio=precio, accion=señal_accion(sa,sn,ss), hist=hist)
        except: continue
    return res

@st.cache_data(ttl=1800, show_spinner=False)
def cargar_paises():
    res = {}
    for nombre, (tk, region) in PAISES.items():
        try:
            df_v = descargar_datos(tk, '3mo'); df_m = descargar_datos(tk, '1mo')
            if df_v is None: continue
            cl_v = get_close(df_v); cl_m = get_close(df_m)
            if cl_v is None or cl_m is None or len(cl_v.dropna())<15: continue
            atr = calcular_atr(df_m)
            sa, sn, ss = scores_activo(cl_v, cl_m, atr)
            ret_5d  = float(cl_m.pct_change(5).iloc[-1]*100)  if len(cl_m)>=6  else 0
            ret_10d = float(cl_m.pct_change(10).iloc[-1]*100) if len(cl_m)>=11 else 0
            precio  = float(cl_m.iloc[-1])
            res[nombre] = dict(tk=tk, region=region, sa=sa, sn=sn, ss=ss,
                sf=sa*0.45+sn*0.35+ss*0.20, ret_5d=ret_5d, ret_10d=ret_10d,
                precio=precio, accion=señal_accion(sa,sn,ss))
        except: continue
    return res

@st.cache_data(ttl=1800, show_spinner=False)
def cargar_sectores():
    res = {}
    for nombre, (tk, color) in SECTORES.items():
        try:
            df_v = descargar_datos(tk, '3mo'); df_m = descargar_datos(tk, '1mo')
            if df_v is None: continue
            cl_v = get_close(df_v); cl_m = get_close(df_m)
            if cl_v is None or cl_m is None or len(cl_v.dropna())<15: continue
            atr = calcular_atr(df_m)
            sa, sn, ss = scores_activo(cl_v, cl_m, atr)
            rsi    = float(calcular_rsi(cl_m, p=7).iloc[-1])
            ret_5d = float(cl_m.pct_change(5).iloc[-1]*100)  if len(cl_m)>=6  else 0
            ret_10d= float(cl_m.pct_change(10).iloc[-1]*100) if len(cl_m)>=11 else 0
            precio = float(cl_m.iloc[-1])
            res[nombre] = dict(tk=tk, color=color, sa=sa, sn=sn, ss=ss,
                sf=sa*0.45+sn*0.35+ss*0.20, rsi=rsi, ret_5d=ret_5d, ret_10d=ret_10d,
                precio=precio, accion=señal_accion(sa,sn,ss))
        except: continue
    return res

@st.cache_data(ttl=1800, show_spinner=False)
def cargar_mercados():
    res = {}
    for nombre, (tk, cat, color) in MERCADOS_REALES.items():
        try:
            df_v = descargar_datos(tk, '3mo'); df_m = descargar_datos(tk, '1mo')
            if df_v is None or df_m is None: continue
            cl_v = get_close(df_v); cl_m = get_close(df_m)
            if cl_v is None or cl_m is None or len(cl_v.dropna())<20: continue
            atr = calcular_atr(df_m)
            sa, sn, ss = scores_activo(cl_v, cl_m, atr)
            rsi    = float(calcular_rsi(cl_m, p=7).iloc[-1])
            ret_5d = float(cl_m.pct_change(5).iloc[-1]*100)  if len(cl_m)>=6  else 0
            ret_10d= float(cl_m.pct_change(10).iloc[-1]*100) if len(cl_m)>=11 else 0
            precio = float(cl_m.iloc[-1])
            for v in [ret_5d, ret_10d, rsi]:
                if np.isnan(v): v = 0
            res[nombre] = dict(tk=tk, cat=cat, color=color, sa=sa, sn=sn, ss=ss,
                sf=sa*0.45+sn*0.35+ss*0.20, rsi=rsi, ret_5d=ret_5d, ret_10d=ret_10d,
                precio=precio, accion=señal_accion(sa,sn,ss))
        except: continue
    return res

@st.cache_data(ttl=1800, show_spinner=False)
def cargar_industrias():
    res = {}
    for sector, inds in INDUSTRIAS.items():
        res[sector] = {}
        for ind_nombre, tk in inds.items():
            try:
                df_v = descargar_datos(tk, '3mo'); df_m = descargar_datos(tk, '1mo')
                if df_v is None: continue
                cl_v = get_close(df_v); cl_m = get_close(df_m)
                if cl_v is None or cl_m is None or len(cl_v.dropna())<15: continue
                atr = calcular_atr(df_m)
                sa, sn, ss = scores_activo(cl_v, cl_m, atr)
                rsi    = float(calcular_rsi(cl_m, p=7).iloc[-1])
                ret_5d = float(cl_m.pct_change(5).iloc[-1]*100)  if len(cl_m)>=6  else 0
                ret_10d= float(cl_m.pct_change(10).iloc[-1]*100) if len(cl_m)>=11 else 0
                precio = float(cl_m.iloc[-1])
                res[sector][ind_nombre] = dict(tk=tk, sa=sa, sn=sn, ss=ss,
                    sf=sa*0.45+sn*0.35+ss*0.20, rsi=rsi, ret_5d=ret_5d, ret_10d=ret_10d,
                    precio=precio, accion=señal_accion(sa,sn,ss))
            except: continue
    return res

@st.cache_data(ttl=1800, show_spinner=False)
def cargar_acciones():
    res = {}
    for industria, tickers in ACCIONES_POR_INDUSTRIA.items():
        res[industria] = {}
        for tk in tickers:
            try:
                df_v = descargar_datos(tk, '3mo'); df_m = descargar_datos(tk, '1mo')
                if df_v is None: continue
                cl_v = get_close(df_v); cl_m = get_close(df_m)
                if cl_v is None or cl_m is None or len(cl_v.dropna())<15: continue
                atr = calcular_atr(df_m)
                sa, sn, ss = scores_activo(cl_v, cl_m, atr)
                rsi    = float(calcular_rsi(cl_m, p=7).iloc[-1])
                ret_5d = float(cl_m.pct_change(5).iloc[-1]*100)  if len(cl_m)>=6  else 0
                ret_10d= float(cl_m.pct_change(10).iloc[-1]*100) if len(cl_m)>=11 else 0
                precio = float(cl_m.iloc[-1])
                res[industria][tk] = dict(sa=sa, sn=sn, ss=ss,
                    sf=sa*0.45+sn*0.35+ss*0.20, rsi=rsi, ret_5d=ret_5d, ret_10d=ret_10d,
                    precio=precio, accion=señal_accion(sa,sn,ss))
            except: continue
    return res

# ══════════════════════════════════════════════════════════════
#  COMPONENTES DE GRAFICOS REUTILIZABLES
# ══════════════════════════════════════════════════════════════

def grafico_barras_h(items_ord, titulo, color_barra_alt=None, accent_color='#1f6feb'):
    """Barras horizontales acum + antic."""
    ns   = [n for n,_ in items_ord]
    sas  = [d['sa'] for _,d in items_ord]
    sns_ = [d['sn'] for _,d in items_ord]
    y    = np.arange(len(ns))

    fig, ax = plt.subplots(figsize=(7, max(3, len(ns)*0.52)))
    fig.patch.set_facecolor('#080c14')
    ax.set_facecolor('#0d1117')

    col_bars = [score_color(s) for s in sas]
    brs = ax.barh(y, sas, color=col_bars, edgecolor='none', height=0.52, alpha=.92, zorder=3)
    col_alt = color_barra_alt if color_barra_alt else '#58a6ff'
    ax.barh(y, sns_, color=col_alt, edgecolor='none', height=0.24, alpha=0.35, zorder=3)

    ax.axvline(62, color='#2ea043', ls='--', alpha=.5, lw=.9)
    ax.axvline(38, color='#cf222e', ls='--', alpha=.5, lw=.9)
    ax.fill_betweenx([-0.5,len(ns)-0.5], 62,100, alpha=.04, color='#2ea043')
    ax.fill_betweenx([-0.5,len(ns)-0.5],  0, 38, alpha=.04, color='#cf222e')

    ax.set_xlim(0, 118)
    ax.set_yticks(y)
    ax.set_yticklabels(ns, fontsize=9, color='#c9d1d9')
    ax.set_title(titulo, color='#e6edf3', fontsize=11, fontweight='600', pad=8, loc='left', x=0.01)

    for b, s in zip(brs, sas):
        ax.text(s+1, b.get_y()+b.get_height()/2, f'{s:.0f}', va='center', color='#e6edf3', fontsize=8.5, fontweight='600')

    ax.spines['top'].set_color(accent_color); ax.spines['top'].set_linewidth(2)
    ax.grid(axis='x', alpha=.15, zorder=0); ax.tick_params(colors='#8b949e')
    ax.set_xlabel('Score Acumulación', color='#8b949e', fontsize=8)
    plt.tight_layout(pad=1.2)
    return fig

def grafico_momentum(pares_ord, label_5d='5 días', label_10d='10 días'):
    ns_all  = [n for n,_ in pares_ord]
    r5_all  = [d.get('ret_5d', d.get('ret_1m',0)) for _,d in pares_ord]
    r10_all = [d.get('ret_10d', d.get('ret_3m',0)) for _,d in pares_ord]
    x_all   = np.arange(len(ns_all))

    fig, ax = plt.subplots(figsize=(max(12, len(ns_all)*0.52), 5))
    fig.patch.set_facecolor('#080c14'); ax.set_facecolor('#0d1117')

    ax.bar(x_all-.2, r5_all,  width=.38, color=['#2ea043' if v>=0 else '#cf222e' for v in r5_all],  alpha=.95, label=label_5d, zorder=3)
    ax.bar(x_all+.2, r10_all, width=.38, color=['#388bfd' if v>=0 else '#bc8cff' for v in r10_all], alpha=.65, label=label_10d, zorder=3)
    ax.axhline(0, color='#c9d1d9', lw=.7, alpha=.4)
    ax.set_xticks(x_all)
    ax.set_xticklabels(ns_all, rotation=45, ha='right', fontsize=8.5)
    ax.set_ylabel('Retorno %', fontsize=9)
    ax.legend(facecolor='#0d1117', labelcolor='#c9d1d9', fontsize=9, framealpha=.8)
    ax.grid(axis='y', alpha=.15, zorder=0); ax.tick_params(colors='#8b949e')
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    plt.tight_layout(pad=1.2)
    return fig

def grafico_heatmap(datos_dict, titulo='Heatmap de scores'):
    df_heat = pd.DataFrame({
        'Acum':  {n:d['sa'] for n,d in datos_dict.items()},
        'Antic': {n:d['sn'] for n,d in datos_dict.items()},
        'Sent':  {n:d['ss'] for n,d in datos_dict.items()},
    }).sort_values('Acum', ascending=False)

    fig, ax = plt.subplots(figsize=(5.5, max(5, len(datos_dict)*0.36)))
    fig.patch.set_facecolor('#080c14')
    sb.heatmap(df_heat, annot=True, fmt='.0f', cmap='RdYlGn', vmin=0, vmax=100,
               ax=ax, linewidths=.4, linecolor='#080c14', cbar_kws={'label':'Score', 'shrink':.8})
    ax.set_title(titulo, color='#e6edf3', fontsize=11, pad=10, loc='left')
    ax.tick_params(colors='#c9d1d9')
    ax.set_xticklabels(ax.get_xticklabels(), rotation=0, fontsize=9)
    ax.set_yticklabels(ax.get_yticklabels(), rotation=0, fontsize=8)
    plt.tight_layout(pad=1.2)
    return fig

def grafico_cuadrante(datos_dict, colores_dict=None, titulo='Mapa de Oportunidades'):
    fig, ax = plt.subplots(figsize=(9, 7))
    fig.patch.set_facecolor('#080c14'); ax.set_facecolor('#0d1117')

    for nombre, d in datos_dict.items():
        col_p = colores_dict.get(d.get('grupo', d.get('region', d.get('cat',''))), '#58a6ff') if colores_dict else '#58a6ff'
        ax.scatter(d['sn'], d['sa'], color=col_p, s=150, zorder=5, edgecolors='#080c14', linewidths=1.2, alpha=.9)
        ax.annotate(nombre[:10], (d['sn'], d['sa']), xytext=(6,3), textcoords='offset points', fontsize=7.5, color='#c9d1d9')

    ax.axhline(62, color='#2ea043', ls='--', alpha=.4, lw=1)
    ax.axhline(38, color='#cf222e', ls='--', alpha=.4, lw=1)
    ax.axvline(55, color='#e3b341', ls='--', alpha=.4, lw=1)
    ax.fill_between([55,100],[62,62],[100,100], alpha=.06, color='#2ea043')
    ax.fill_between([0,55],  [0,0],  [38,38],  alpha=.06, color='#cf222e')
    ax.text(77, 97, '✦ Mejor zona entrada', color='#2ea043', fontsize=8.5, alpha=.8, ha='center', fontweight='600')
    ax.text(25,  5, '✦ Zona de cautela',    color='#cf222e', fontsize=8.5, alpha=.8, ha='center', fontweight='600')
    ax.set_xlabel('Score Anticipación →', fontsize=10)
    ax.set_ylabel('← Score Acumulación',  fontsize=10)
    ax.set_title(titulo, color='#e6edf3', fontsize=11, pad=10)
    ax.set_xlim(0,100); ax.set_ylim(0,100)
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    ax.grid(alpha=.12); ax.tick_params(colors='#8b949e')
    plt.tight_layout(pad=1.2)
    return fig

def tabla_ranking(filas_dict, precio_fmt='gen'):
    filas = []
    for nombre, d in sorted(filas_dict.items(), key=lambda x: x[1]['sa'], reverse=True):
        p = fmt_precio_fx(d['precio']) if precio_fmt=='fx' else fmt_precio_gen(d.get('precio',0))
        filas.append({
            'Nombre':    nombre,
            'Acum':      round(d['sa'],1),
            'Antic':     round(d['sn'],1),
            'Sent':      round(d['ss'],1),
            'RSI':       round(d.get('rsi',0),1),
            'Ret 5d %':  round(d.get('ret_5d', d.get('ret_1m',0)),2),
            'Ret 10d %': round(d.get('ret_10d', d.get('ret_3m',0)),2),
            'Precio':    p,
            'Señal':     d['accion'],
        })
    df = pd.DataFrame(filas)

    def color_score_cell(val):
        try:
            v = float(val)
            if   v<=20: return 'background-color:#3d1a1a; color:#f85149; font-weight:600'
            elif v<=40: return 'background-color:#3d2a10; color:#f0883e; font-weight:600'
            elif v<=60: return 'background-color:#2e2a10; color:#e3b341; font-weight:600'
            elif v<=80: return 'background-color:#102a1a; color:#7ee787; font-weight:600'
            else:       return 'background-color:#0a2a10; color:#3fb950; font-weight:600'
        except: return ''

    def color_ret(val):
        try:
            v = float(val)
            c = '#3fb950' if v>=0 else '#f85149'
            return f'color:{c}; font-weight:600'
        except: return ''

    _map = 'map' if hasattr(df.style,'map') else 'applymap'
    styled = (df.style
        .pipe(lambda s: getattr(s,_map)(color_score_cell, subset=['Acum','Antic','Sent']))
        .pipe(lambda s: getattr(s,_map)(color_ret, subset=['Ret 5d %','Ret 10d %']))
        .set_properties(**{'background-color':'#0d1117','color':'#e6edf3','border':'1px solid #1e2533'})
        .set_table_styles([{
            'selector':'th',
            'props':[('background-color','#161b22'),('color','#e6edf3'),
                     ('font-weight','600'),('text-align','center'),
                     ('border-bottom','2px solid #1f6feb')]
        },{'selector':'td','props':[('text-align','center')]}])
    )
    altura = min(600, max(150, len(df)*35 + 45))
    st.dataframe(styled, use_container_width=True, height=altura)
    return df

def kpi_cards(datos_dict, label_extra=''):
    if not datos_dict: return
    mejor   = max(datos_dict.items(), key=lambda x: x[1]['sa'])
    mom_max = max(datos_dict.items(), key=lambda x: x[1]['sn'])
    riesgo  = min(datos_dict.items(), key=lambda x: x[1]['sa'])
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(f'<div class="kpi-card"><div class="accent" style="background:#1f6feb"></div>'
                    f'<div class="label">Total analizados</div><div class="value">{len(datos_dict)}</div>'
                    f'<div class="sub">{label_extra}</div></div>', unsafe_allow_html=True)
    with k2:
        lbl,col,_ = clasificar(mejor[1]['sa'])
        st.markdown(f'<div class="kpi-card"><div class="accent" style="background:#2ea043"></div>'
                    f'<div class="label">🟢 Mejor oportunidad</div><div class="value">{mejor[0][:18]}</div>'
                    f'<div class="sub">Acum: <b style="color:{col}">{mejor[1]["sa"]:.0f}</b> · {lbl}</div></div>', unsafe_allow_html=True)
    with k3:
        lbl2,col2,_ = clasificar(mom_max[1]['sn'])
        st.markdown(f'<div class="kpi-card"><div class="accent" style="background:#9a6700"></div>'
                    f'<div class="label">⚡ Mayor momentum</div><div class="value">{mom_max[0][:18]}</div>'
                    f'<div class="sub">Antic: <b style="color:{col2}">{mom_max[1]["sn"]:.0f}</b></div></div>', unsafe_allow_html=True)
    with k4:
        lbl3,col3,_ = clasificar(riesgo[1]['sa'])
        st.markdown(f'<div class="kpi-card"><div class="accent" style="background:#cf222e"></div>'
                    f'<div class="label">⚠️ Mayor riesgo</div><div class="value">{riesgo[0][:18]}</div>'
                    f'<div class="sub">Acum: <b style="color:{col3}">{riesgo[1]["sa"]:.0f}</b> · {lbl3}</div></div>', unsafe_allow_html=True)
    st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
#  SIDEBAR
# ══════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown('<div class="sidebar-logo">📊 Análisis Top-Down</div>', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-sub">Scores por percentil histórico · 3 meses</div>', unsafe_allow_html=True)
    st.markdown('---')

    modulo = st.radio('Módulo de análisis', [
        '💱 Forex',
        '🌍 Países / Índices',
        '📊 Sectores S&P500',
        '🛢️ Mercados Reales',
        '🏭 Industrias',
        '📈 Acciones',
        '🎯 Resumen Top-Down',
    ])
    st.markdown('---')
    if st.button('🔄  Actualizar datos', use_container_width=True):
        st.cache_data.clear(); st.rerun()
    st.markdown('---')
    st.markdown("""
    <div style='font-size:11px; color:#8b949e; line-height:1.7'>
    <b style='color:#c9d1d9'>Scores (0–100)</b><br>
    <span style='color:#3fb950'>●</span> 81–100 &nbsp;Muy alto<br>
    <span style='color:#7ee787'>●</span> 61–80 &nbsp;Alto<br>
    <span style='color:#e3b341'>●</span> 41–60 &nbsp;Neutral<br>
    <span style='color:#f0883e'>●</span> 21–40 &nbsp;Bajo<br>
    <span style='color:#f85149'>●</span> 0–20 &nbsp;&nbsp;Muy bajo<br><br>
    <b style='color:#c9d1d9'>Fuente:</b> Yahoo Finance<br>
    <b style='color:#c9d1d9'>Caché:</b> 30 minutos<br><br>
    <i>Solo informativo. No constituye asesoramiento financiero.</i>
    </div>
    """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
#  HEADER PRINCIPAL
# ══════════════════════════════════════════════════════════════
ICONOS = {
    '💱 Forex':           ('💱 Análisis Forex — Top-Down',           'Majors · Crosses · LatAm — Scores por percentil histórico 3 meses'),
    '🌍 Países / Índices':('🌍 Países e Índices Globales',            'ETFs por país — Scores por percentil histórico 3 meses'),
    '📊 Sectores S&P500': ('📊 Sectores del S&P500',                  '11 sectores GICS — Scores por percentil histórico 3 meses'),
    '🛢️ Mercados Reales': ('🛢️ Commodities · Metales · Cripto',       'Energía · Metales · Agro · Cripto — Scores por percentil histórico 3 meses'),
    '🏭 Industrias':      ('🏭 Industrias por Sector',                'ETFs de industria dentro de cada sector S&P500 — 3 meses'),
    '📈 Acciones':        ('📈 Acciones por Industria',               'Top acciones de cada industria — Scores por percentil histórico 3 meses'),
    '🎯 Resumen Top-Down':('🎯 Resumen Ejecutivo Top-Down',           'País → Sector → Mercado → Industria → Acción · Solo informativo'),
}
titulo_h, sub_h = ICONOS.get(modulo, ('📊 Análisis Top-Down',''))
st.markdown(f'<div class="main-header"><h1>{titulo_h}</h1><p>{sub_h}</p></div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
#  MÓDULO: FOREX
# ══════════════════════════════════════════════════════════════
if modulo == '💱 Forex':
    grupos_disponibles = list(dict.fromkeys(v[1] for v in FOREX.values()))

    with st.sidebar:
        st.markdown('---')
        grupos_sel = st.multiselect('Grupos FX', grupos_disponibles, default=grupos_disponibles)

    with st.spinner('⏳ Descargando datos Forex...'):
        datos_fx = cargar_forex()

    datos_filtrados = {n:d for n,d in datos_fx.items() if d['grupo'] in grupos_sel}
    if not datos_filtrados:
        st.error('No hay datos. Verificá la conexión o seleccioná al menos un grupo.')
        st.stop()

    kpi_cards(datos_filtrados, f'{len(grupos_sel)} grupos activos')

    tab1, tab2, tab3, tab4 = st.tabs(['📊 Scores por grupo','📈 Momentum','🗺️ Cuadrante','📋 Ranking'])

    with tab1:
        st.markdown('<div class="info-banner">Barra grande = <b>Acumulación</b> (precio barato históricamente) · Barra fina = <b>Anticipación</b> (momentum) · Línea verde = zona de entrada (>62) · Línea roja = cautela (<38)</div>', unsafe_allow_html=True)
        grupos_en_datos = [g for g in grupos_disponibles if g in grupos_sel and any(d['grupo']==g for d in datos_filtrados.values())]
        for i in range(0, len(grupos_en_datos), 2):
            cols = st.columns(2)
            for j, grupo in enumerate(grupos_en_datos[i:i+2]):
                items = [(n,d) for n,d in datos_filtrados.items() if d['grupo']==grupo]
                if not items: continue
                items_ord = sorted(items, key=lambda x: x[1]['sa'], reverse=True)
                fig = grafico_barras_h(items_ord, grupo, COLORES_GRUPO_FX.get(grupo,'#58a6ff'), ACCENT_GRUPO_FX.get(grupo,'#1f6feb'))
                with cols[j]: st.pyplot(fig, use_container_width=True)
                plt.close(fig)

    with tab2:
        st.markdown('<p class="section-title">Retorno 5d vs 10d</p>', unsafe_allow_html=True)
        pares_ord = sorted(datos_filtrados.items(), key=lambda x: x[1]['ret_5d'], reverse=True)
        fig2 = grafico_momentum(pares_ord)
        st.pyplot(fig2, use_container_width=True); plt.close(fig2)
        st.markdown('<p class="section-title">Heatmap de scores</p>', unsafe_allow_html=True)
        col_heat, _ = st.columns([1,1])
        with col_heat:
            fig_h = grafico_heatmap(datos_filtrados, 'Heatmap Forex — verde=oportunidad')
            st.pyplot(fig_h, use_container_width=True); plt.close(fig_h)

    with tab3:
        st.markdown('<div class="info-banner">🟢 Arriba-derecha: precio barato + momentum alcista → mejor zona de entrada · 🔴 Abajo-izquierda: precio caro + bajista → evitar</div>', unsafe_allow_html=True)
        col_mapa, _ = st.columns([2,1])
        with col_mapa:
            fig3 = grafico_cuadrante(datos_filtrados, COLORES_GRUPO_FX, 'Mapa Oportunidades Forex')
            st.pyplot(fig3, use_container_width=True); plt.close(fig3)

    with tab4:
        st.markdown('<p class="section-title">Ranking completo</p>', unsafe_allow_html=True)
        c_fil1, c_fil2 = st.columns([1,3])
        with c_fil1:
            señales_unicas = ['Todas'] + sorted(set(d['accion'] for d in datos_filtrados.values()))
            señal_sel = st.selectbox('Filtrar señal', señales_unicas)
        df_show = {n:d for n,d in datos_filtrados.items() if señal_sel=='Todas' or d['accion']==señal_sel}
        tabla_ranking(df_show, precio_fmt='fx')

        st.markdown('<p class="section-title">🔍 Detalle de par</p>', unsafe_allow_html=True)
        par_sel = st.selectbox('Par', list(datos_filtrados.keys()), key='det_fx')
        if par_sel and par_sel in datos_filtrados:
            d = datos_filtrados[par_sel]
            sc1,sc2,sc3,sc4,sc5 = st.columns(5)
            for col_st, label, value, ref in [(sc1,'Acumulación',d['sa'],62),(sc2,'Anticipación',d['sn'],55),(sc3,'Sentimiento',d['ss'],50),(sc4,'RSI',d['rsi'],50),(sc5,'Precio',None,None)]:
                with col_st:
                    if value is not None:
                        delta = f"+{value-ref:.1f}" if value>=ref else f"{value-ref:.1f}"
                        st.metric(label, f'{value:.1f}', delta)
                    else:
                        st.metric(label, fmt_precio_fx(d['precio']))
            st.markdown(f'<div style="margin:8px 0"><span class="signal-pill">{d["accion"]}</span> &nbsp;<span style="color:#8b949e;font-size:13px">{d["grupo"]}</span></div>', unsafe_allow_html=True)
            hist = d.get('hist')
            if hist is not None and len(hist) > 2:
                precios = hist['Precio'].values
                p_min = precios.min(); p_max = precios.max()
                margen = (p_max-p_min)*0.15 if (p_max-p_min)>0 else p_min*0.01
                fig_line, ax_line = plt.subplots(figsize=(10, 3.2))
                fig_line.patch.set_facecolor('#080c14'); ax_line.set_facecolor('#0d1117')
                ax_line.fill_between(range(len(precios)), precios, alpha=0.15, color='#388bfd')
                trend_color = '#2ea043' if precios[-1]>=precios[0] else '#cf222e'
                ax_line.plot(range(len(precios)), precios, color=trend_color, lw=2, zorder=4)
                ax_line.scatter(len(precios)-1, precios[-1], color=trend_color, s=60, zorder=5, edgecolors='#e6edf3', lw=1)
                ax_line.set_ylim(p_min-margen, p_max+margen)
                fechas = hist['Fecha'].values; n_ticks = min(6, len(fechas))
                idx_ticks = np.linspace(0, len(fechas)-1, n_ticks, dtype=int)
                ax_line.set_xticks(idx_ticks)
                try: ax_line.set_xticklabels([str(fechas[i])[:10] for i in idx_ticks], rotation=0, fontsize=8)
                except: pass
                ret_pct = (precios[-1]/precios[0]-1)*100
                ax_line.set_title(f'{par_sel} — últimos 30 días  ({ret_pct:+.2f}%)', color='#2ea043' if ret_pct>=0 else '#cf222e', fontsize=10, fontweight='600', pad=8, loc='left')
                ax_line.spines['top'].set_visible(False); ax_line.spines['right'].set_visible(False)
                ax_line.grid(axis='y', alpha=.15); ax_line.tick_params(colors='#8b949e')
                plt.tight_layout(pad=1.2)
                st.pyplot(fig_line, use_container_width=True); plt.close(fig_line)

# ══════════════════════════════════════════════════════════════
#  MÓDULO: PAÍSES / ÍNDICES
# ══════════════════════════════════════════════════════════════
elif modulo == '🌍 Países / Índices':
    with st.spinner('⏳ Descargando datos de países...'):
        datos_p = cargar_paises()
    if not datos_p:
        st.error('No hay datos disponibles.'); st.stop()

    kpi_cards(datos_p, 'índices globales')
    tab1, tab2, tab3, tab4 = st.tabs(['📊 Scores','📈 Momentum','🗺️ Cuadrante','📋 Ranking'])

    with tab1:
        st.markdown('<div class="info-banner">Barra grande = Acumulación · Barra fina = Anticipación · Línea verde = zona entrada (>62)</div>', unsafe_allow_html=True)
        regiones = list(dict.fromkeys(d['region'] for d in datos_p.values()))
        for i in range(0, len(regiones), 2):
            cols = st.columns(2)
            for j, region in enumerate(regiones[i:i+2]):
                items = sorted([(n,d) for n,d in datos_p.items() if d['region']==region], key=lambda x: x[1]['sa'], reverse=True)
                if not items: continue
                fig = grafico_barras_h(items, region, COLORES_REGION.get(region,'#58a6ff'))
                with cols[j]: st.pyplot(fig, use_container_width=True)
                plt.close(fig)

    with tab2:
        pares_ord = sorted(datos_p.items(), key=lambda x: x[1]['ret_5d'], reverse=True)
        fig2 = grafico_momentum(pares_ord)
        st.pyplot(fig2, use_container_width=True); plt.close(fig2)
        col_heat, _ = st.columns([1,1])
        with col_heat:
            fig_h = grafico_heatmap(datos_p, 'Heatmap Países — verde=oportunidad')
            st.pyplot(fig_h, use_container_width=True); plt.close(fig_h)

    with tab3:
        col_mapa, _ = st.columns([2,1])
        with col_mapa:
            fig3 = grafico_cuadrante(datos_p, COLORES_REGION, 'Mapa Oportunidades Países')
            st.pyplot(fig3, use_container_width=True); plt.close(fig3)

    with tab4:
        tabla_ranking(datos_p)

# ══════════════════════════════════════════════════════════════
#  MÓDULO: SECTORES S&P500
# ══════════════════════════════════════════════════════════════
elif modulo == '📊 Sectores S&P500':
    with st.spinner('⏳ Descargando datos de sectores...'):
        datos_s = cargar_sectores()
    if not datos_s:
        st.error('No hay datos disponibles.'); st.stop()

    kpi_cards(datos_s, '11 sectores GICS')
    tab1, tab2, tab3, tab4 = st.tabs(['📊 Scores','📈 Momentum','🗺️ Cuadrante','📋 Ranking'])

    with tab1:
        st.markdown('<div class="info-banner">Scores de los 11 sectores del S&P500. Colores por nivel de score: 🟢 alto (barato) → 🔴 bajo (caro)</div>', unsafe_allow_html=True)
        items_ord = sorted(datos_s.items(), key=lambda x: x[1]['sa'], reverse=True)
        fig = grafico_barras_h(items_ord, 'S&P500 — Todos los sectores')
        st.pyplot(fig, use_container_width=True); plt.close(fig)

    with tab2:
        pares_ord = sorted(datos_s.items(), key=lambda x: x[1]['ret_5d'], reverse=True)
        fig2 = grafico_momentum(pares_ord)
        st.pyplot(fig2, use_container_width=True); plt.close(fig2)
        col_heat, _ = st.columns([1,1])
        with col_heat:
            fig_h = grafico_heatmap(datos_s, 'Heatmap Sectores — verde=oportunidad')
            st.pyplot(fig_h, use_container_width=True); plt.close(fig_h)

    with tab3:
        col_mapa, _ = st.columns([2,1])
        with col_mapa:
            fig3 = grafico_cuadrante(datos_s, None, 'Mapa Oportunidades Sectores')
            st.pyplot(fig3, use_container_width=True); plt.close(fig3)

    with tab4:
        tabla_ranking(datos_s)

# ══════════════════════════════════════════════════════════════
#  MÓDULO: MERCADOS REALES
# ══════════════════════════════════════════════════════════════
elif modulo == '🛢️ Mercados Reales':
    with st.spinner('⏳ Descargando datos de mercados reales...'):
        datos_m = cargar_mercados()
    if not datos_m:
        st.error('No hay datos disponibles.'); st.stop()

    kpi_cards(datos_m, 'commodities · metales · cripto')
    tab1, tab2, tab3, tab4 = st.tabs(['📊 Scores por categoría','📈 Momentum','🗺️ Cuadrante','📋 Ranking'])

    with tab1:
        st.markdown('<div class="info-banner">Energía · Metales Preciosos · Metales Industriales · Minería · Agro · Cripto</div>', unsafe_allow_html=True)
        cats = list(dict.fromkeys(d['cat'] for d in datos_m.values()))
        for i in range(0, len(cats), 2):
            cols = st.columns(2)
            for j, cat in enumerate(cats[i:i+2]):
                items = sorted([(n,d) for n,d in datos_m.items() if d['cat']==cat], key=lambda x: x[1]['sa'], reverse=True)
                if not items: continue
                fig = grafico_barras_h(items, cat)
                with cols[j]: st.pyplot(fig, use_container_width=True)
                plt.close(fig)

    with tab2:
        pares_ord = sorted(datos_m.items(), key=lambda x: x[1]['ret_5d'], reverse=True)
        fig2 = grafico_momentum(pares_ord)
        st.pyplot(fig2, use_container_width=True); plt.close(fig2)
        col_heat, _ = st.columns([1,1])
        with col_heat:
            fig_h = grafico_heatmap(datos_m, 'Heatmap Mercados Reales — verde=oportunidad')
            st.pyplot(fig_h, use_container_width=True); plt.close(fig_h)

    with tab3:
        col_mapa, _ = st.columns([2,1])
        with col_mapa:
            fig3 = grafico_cuadrante(datos_m, None, 'Mapa Oportunidades Mercados Reales')
            st.pyplot(fig3, use_container_width=True); plt.close(fig3)

    with tab4:
        tabla_ranking(datos_m)

# ══════════════════════════════════════════════════════════════
#  MÓDULO: INDUSTRIAS
# ══════════════════════════════════════════════════════════════
elif modulo == '🏭 Industrias':
    with st.spinner('⏳ Descargando datos de industrias... (puede tardar ~2 min)'):
        datos_ind = cargar_industrias()

    todas_ind = {f'{s[:4]}·{i}': d for s, inds in datos_ind.items() for i, d in inds.items()}
    if not todas_ind:
        st.error('No hay datos disponibles.'); st.stop()

    kpi_cards(todas_ind, 'ETFs de industria')
    tab1, tab2, tab3 = st.tabs(['📊 Por sector','🗺️ Cuadrante','📋 Ranking'])

    with tab1:
        st.markdown('<div class="info-banner">Industrias ordenadas por Score de Acumulación dentro de cada sector</div>', unsafe_allow_html=True)
        sectores_con_datos = [s for s in datos_ind if datos_ind[s]]
        with st.sidebar:
            st.markdown('---')
            sector_sel = st.selectbox('Ver sector', ['Todos'] + sectores_con_datos)

        for sector, inds in datos_ind.items():
            if not inds: continue
            if sector_sel != 'Todos' and sector != sector_sel: continue
            items_ord = sorted(inds.items(), key=lambda x: x[1]['sa'], reverse=True)
            fig = grafico_barras_h(items_ord, sector)
            st.pyplot(fig, use_container_width=True); plt.close(fig)

    with tab2:
        col_mapa, _ = st.columns([2,1])
        with col_mapa:
            fig3 = grafico_cuadrante(todas_ind, None, 'Mapa Oportunidades Industrias')
            st.pyplot(fig3, use_container_width=True); plt.close(fig3)

    with tab3:
        st.markdown('<p class="section-title">Ranking completo de industrias</p>', unsafe_allow_html=True)
        filas = []
        for sector, inds in datos_ind.items():
            for ind_n, d in sorted(inds.items(), key=lambda x: x[1]['sa'], reverse=True):
                filas.append({'Sector': sector, 'Industria': ind_n, 'ETF': d['tk'],
                    'Acum': round(d['sa'],1), 'Antic': round(d['sn'],1), 'Sent': round(d['ss'],1),
                    'RSI': round(d.get('rsi',0),1), 'Ret 5d %': round(d.get('ret_5d',0),2),
                    'Ret 10d %': round(d.get('ret_10d',0),2), 'Precio': fmt_precio_gen(d.get('precio',0)),
                    'Señal': d['accion']})
        df_ind = pd.DataFrame(filas).sort_values('Acum', ascending=False)

        def cs(val):
            try:
                v = float(val)
                if v<=20: return 'background-color:#3d1a1a;color:#f85149;font-weight:600'
                elif v<=40: return 'background-color:#3d2a10;color:#f0883e;font-weight:600'
                elif v<=60: return 'background-color:#2e2a10;color:#e3b341;font-weight:600'
                elif v<=80: return 'background-color:#102a1a;color:#7ee787;font-weight:600'
                else: return 'background-color:#0a2a10;color:#3fb950;font-weight:600'
            except: return ''

        def cr(val):
            try: v=float(val); return f'color:{"#3fb950" if v>=0 else "#f85149"};font-weight:600'
            except: return ''

        _map = 'map' if hasattr(df_ind.style,'map') else 'applymap'
        styled = (df_ind.style
            .pipe(lambda s: getattr(s,_map)(cs, subset=['Acum','Antic','Sent']))
            .pipe(lambda s: getattr(s,_map)(cr, subset=['Ret 5d %','Ret 10d %']))
            .set_properties(**{'background-color':'#0d1117','color':'#e6edf3','border':'1px solid #1e2533'})
            .set_table_styles([{'selector':'th','props':[('background-color','#161b22'),('color','#e6edf3'),('font-weight','600'),('text-align','center'),('border-bottom','2px solid #1f6feb')]},{'selector':'td','props':[('text-align','center')]}])
        )
        altura = min(700, max(200, len(df_ind)*35+45))
        st.dataframe(styled, use_container_width=True, height=altura)

# ══════════════════════════════════════════════════════════════
#  MÓDULO: ACCIONES
# ══════════════════════════════════════════════════════════════
elif modulo == '📈 Acciones':
    with st.sidebar:
        st.markdown('---')
        industrias_disponibles = list(ACCIONES_POR_INDUSTRIA.keys())
        industrias_sel = st.multiselect('Industrias a analizar', industrias_disponibles, default=industrias_disponibles[:5], help='Seleccioná todas para análisis completo (~10 min)')
        if st.button('▶ Analizar seleccionadas', use_container_width=True):
            st.cache_data.clear()

    if not industrias_sel:
        st.info('Seleccioná al menos una industria en el menú lateral para comenzar.')
        st.stop()

    with st.spinner(f'⏳ Analizando acciones de {len(industrias_sel)} industrias... (puede tardar varios minutos)'):
        datos_acc_raw = cargar_acciones()

    datos_acc = {ind: tks for ind, tks in datos_acc_raw.items() if ind in industrias_sel and tks}
    if not datos_acc:
        st.error('No hay datos disponibles.'); st.stop()

    todas_acc = {tk: d for ind, tks in datos_acc.items() for tk, d in tks.items()}
    kpi_cards(todas_acc, f'{len(industrias_sel)} industrias')

    tab1, tab2, tab3 = st.tabs(['📊 Por industria','🗺️ Cuadrante','📋 Ranking'])

    with tab1:
        st.markdown('<div class="info-banner">Top acciones por industria ordenadas por Score de Acumulación</div>', unsafe_allow_html=True)
        for industria, tickers in datos_acc.items():
            if not tickers: continue
            st.markdown(f'<p class="section-title">📂 {industria}</p>', unsafe_allow_html=True)
            items_ord = sorted(tickers.items(), key=lambda x: x[1]['sa'], reverse=True)
            fig = grafico_barras_h(items_ord, industria)
            st.pyplot(fig, use_container_width=True); plt.close(fig)

    with tab2:
        col_mapa, _ = st.columns([2,1])
        with col_mapa:
            fig3 = grafico_cuadrante(todas_acc, None, 'Mapa Oportunidades Acciones')
            st.pyplot(fig3, use_container_width=True); plt.close(fig3)

    with tab3:
        st.markdown('<p class="section-title">Ranking completo de acciones</p>', unsafe_allow_html=True)
        filas = []
        for industria, tickers in datos_acc.items():
            for tk, d in sorted(tickers.items(), key=lambda x: x[1]['sa'], reverse=True):
                filas.append({'Industria': industria, 'Ticker': tk,
                    'Acum': round(d['sa'],1), 'Antic': round(d['sn'],1), 'Sent': round(d['ss'],1),
                    'RSI': round(d.get('rsi',0),1), 'Ret 5d %': round(d.get('ret_5d',0),2),
                    'Ret 10d %': round(d.get('ret_10d',0),2), 'Precio': fmt_precio_gen(d.get('precio',0)),
                    'Señal': d['accion']})
        df_acc = pd.DataFrame(filas).sort_values('Acum', ascending=False)

        def cs(val):
            try:
                v = float(val)
                if v<=20: return 'background-color:#3d1a1a;color:#f85149;font-weight:600'
                elif v<=40: return 'background-color:#3d2a10;color:#f0883e;font-weight:600'
                elif v<=60: return 'background-color:#2e2a10;color:#e3b341;font-weight:600'
                elif v<=80: return 'background-color:#102a1a;color:#7ee787;font-weight:600'
                else: return 'background-color:#0a2a10;color:#3fb950;font-weight:600'
            except: return ''

        def cr(val):
            try: v=float(val); return f'color:{"#3fb950" if v>=0 else "#f85149"};font-weight:600'
            except: return ''

        c_fil1, c_fil2 = st.columns([1,3])
        with c_fil1:
            señales_acc = ['Todas'] + sorted(df_acc['Señal'].unique().tolist())
            señal_acc = st.selectbox('Filtrar señal', señales_acc)
        df_show_acc = df_acc if señal_acc=='Todas' else df_acc[df_acc['Señal']==señal_acc]

        _map = 'map' if hasattr(df_show_acc.style,'map') else 'applymap'
        styled = (df_show_acc.style
            .pipe(lambda s: getattr(s,_map)(cs, subset=['Acum','Antic','Sent']))
            .pipe(lambda s: getattr(s,_map)(cr, subset=['Ret 5d %','Ret 10d %']))
            .set_properties(**{'background-color':'#0d1117','color':'#e6edf3','border':'1px solid #1e2533'})
            .set_table_styles([{'selector':'th','props':[('background-color','#161b22'),('color','#e6edf3'),('font-weight','600'),('text-align','center'),('border-bottom','2px solid #1f6feb')]},{'selector':'td','props':[('text-align','center')]}])
        )
        altura = min(700, max(200, len(df_show_acc)*35+45))
        st.dataframe(styled, use_container_width=True, height=altura)

# ══════════════════════════════════════════════════════════════
#  MÓDULO: RESUMEN TOP-DOWN
# ══════════════════════════════════════════════════════════════
elif modulo == '🎯 Resumen Top-Down':
    st.markdown('<div class="info-banner">Este módulo carga los datos de <b>todos los niveles</b> para mostrar el flujo completo Top-Down. Puede tardar 3–5 minutos en la primera carga.</div>', unsafe_allow_html=True)

    col_btn1, col_btn2 = st.columns([1,4])
    with col_btn1:
        cargar = st.button('▶ Cargar resumen completo', use_container_width=True)

    if cargar or 'resumen_loaded' in st.session_state:
        st.session_state['resumen_loaded'] = True

        prog = st.progress(0, text='Cargando países...')
        datos_p   = cargar_paises();   prog.progress(20, 'Cargando sectores...')
        datos_s   = cargar_sectores(); prog.progress(40, 'Cargando mercados reales...')
        datos_m   = cargar_mercados(); prog.progress(60, 'Cargando industrias...')
        datos_ind = cargar_industrias(); prog.progress(80, 'Procesando...')
        todas_ind = {f'{s[:4]}·{i}': d for s, inds in datos_ind.items() for i, d in inds.items()}
        prog.progress(100, '✅ Listo'); prog.empty()

        # ── Tabla resumen ejecutivo ──────────────────────────
        st.markdown('<p class="section-title">🏆 Mejores oportunidades por nivel</p>', unsafe_allow_html=True)

        def row_resumen(nivel, datos_dict, icono):
            if not datos_dict: return None
            mejor = max(datos_dict.items(), key=lambda x: x[1]['sa'])
            d = mejor[1]
            lbl,col,em = clasificar(d['sa'])
            return {'Nivel': f'{icono} {nivel}', 'Nombre': mejor[0], 'Acum': round(d['sa'],1),
                    'Antic': round(d['sn'],1), 'Señal': d['accion'], 'Clasificación': lbl}

        rows_res = [r for r in [
            row_resumen('País / Índice',  datos_p,   '🌍'),
            row_resumen('Sector S&P500',  datos_s,   '📊'),
            row_resumen('Mercado Real',   datos_m,   '🛢️'),
            row_resumen('Industria',      todas_ind, '🏭'),
        ] if r]

        if rows_res:
            df_res = pd.DataFrame(rows_res)
            def cs(val):
                try:
                    v=float(val)
                    if v<=20: return 'background-color:#3d1a1a;color:#f85149;font-weight:600'
                    elif v<=40: return 'background-color:#3d2a10;color:#f0883e;font-weight:600'
                    elif v<=60: return 'background-color:#2e2a10;color:#e3b341;font-weight:600'
                    elif v<=80: return 'background-color:#102a1a;color:#7ee787;font-weight:600'
                    else: return 'background-color:#0a2a10;color:#3fb950;font-weight:600'
                except: return ''
            _map = 'map' if hasattr(df_res.style,'map') else 'applymap'
            styled = (df_res.style
                .pipe(lambda s: getattr(s,_map)(cs, subset=['Acum','Antic']))
                .set_properties(**{'background-color':'#0d1117','color':'#e6edf3','border':'1px solid #1e2533'})
                .set_table_styles([{'selector':'th','props':[('background-color','#161b22'),('color','#e6edf3'),('font-weight','600'),('text-align','center'),('border-bottom','2px solid #1f6feb')]},{'selector':'td','props':[('text-align','center')]}])
            )
            st.dataframe(styled, use_container_width=True, height=len(df_res)*42+50)

        # ── Gráfico comparativo top-down ──────────────────────
        st.markdown('<p class="section-title">📊 Comparación visual — mejores de cada nivel</p>', unsafe_allow_html=True)

        fuentes = []
        if datos_p:   fuentes.append(('Países',   datos_p,   '#58a6ff'))
        if datos_s:   fuentes.append(('Sectores', datos_s,   '#7ee787'))
        if datos_m:   fuentes.append(('Mercados', datos_m,   '#f0883e'))
        if todas_ind: fuentes.append(('Industr.',  todas_ind, '#bc8cff'))

        if fuentes:
            fig_td, axes_td = plt.subplots(1, len(fuentes), figsize=(5*len(fuentes), 9))
            fig_td.patch.set_facecolor('#080c14')
            if len(fuentes)==1: axes_td=[axes_td]
            ACCENT_TD = ['#1f6feb','#2ea043','#b35d00','#8250df']

            for ax_td, (label, datos_d, col_td), acc_td in zip(axes_td, fuentes, ACCENT_TD):
                ax_td.set_facecolor('#0d1117')
                top_items = sorted(datos_d.items(), key=lambda x: x[1]['sa'], reverse=True)[:12]
                ns_td  = [n[:14] for n,_ in top_items]
                sas_td = [d['sa'] for _,d in top_items]
                sns_td = [d['sn'] for _,d in top_items]
                y_td   = np.arange(len(ns_td))
                brs_td = ax_td.barh(y_td, sas_td, color=[score_color(s) for s in sas_td], edgecolor='none', height=0.55, alpha=.9)
                ax_td.barh(y_td, sns_td, color=col_td, edgecolor='none', height=0.25, alpha=0.35)
                ax_td.axvline(62, color='#3fb950', ls=':', alpha=.4)
                ax_td.axvline(38, color='#f85149', ls=':', alpha=.4)
                ax_td.fill_betweenx([-0.5,len(ns_td)-0.5], 62,100, alpha=.04, color='#3fb950')
                ax_td.set_xlim(0,118)
                ax_td.set_yticks(y_td); ax_td.set_yticklabels(ns_td, fontsize=8)
                ax_td.set_title(label, color='#e6edf3', fontsize=10, pad=6, fontweight='600')
                for b, s in zip(brs_td, sas_td):
                    ax_td.text(s+1, b.get_y()+b.get_height()/2, f'{s:.0f}', va='center', color='white', fontsize=7.5)
                ax_td.spines['top'].set_color(acc_td); ax_td.spines['top'].set_linewidth(2)
                ax_td.grid(axis='x', alpha=.2); ax_td.tick_params(colors='#8b949e')

            plt.suptitle('Top-Down: mejores oportunidades por nivel', color='#e6edf3', fontsize=13, fontweight='bold', y=1.01)
            plt.tight_layout(pad=1.5)
            st.pyplot(fig_td, use_container_width=True); plt.close(fig_td)

        # ── Flujo Top-Down ────────────────────────────────────
        st.markdown('<p class="section-title">🔄 Flujo Top-Down recomendado</p>', unsafe_allow_html=True)
        st.markdown("""
        <div style='background:#0d1117;border:1px solid #1e2533;border-radius:12px;padding:20px;'>
        <div style='display:flex;align-items:center;gap:12px;flex-wrap:wrap;'>
          <div style='background:#1f6feb22;border:1px solid #1f6feb44;border-radius:8px;padding:10px 16px;text-align:center'>
            <div style='color:#8b949e;font-size:11px;font-weight:600;text-transform:uppercase'>Paso 1</div>
            <div style='color:#e6edf3;font-size:13px;font-weight:700;margin-top:4px'>🌍 País / Índice</div>
            <div style='color:#8b949e;font-size:11px'>¿Qué mercado está barato?</div>
          </div>
          <div style='color:#58a6ff;font-size:20px'>→</div>
          <div style='background:#2ea04322;border:1px solid #2ea04344;border-radius:8px;padding:10px 16px;text-align:center'>
            <div style='color:#8b949e;font-size:11px;font-weight:600;text-transform:uppercase'>Paso 2</div>
            <div style='color:#e6edf3;font-size:13px;font-weight:700;margin-top:4px'>📊 Sector</div>
            <div style='color:#8b949e;font-size:11px'>¿Qué sector lidera?</div>
          </div>
          <div style='color:#58a6ff;font-size:20px'>→</div>
          <div style='background:#b35d0022;border:1px solid #b35d0044;border-radius:8px;padding:10px 16px;text-align:center'>
            <div style='color:#8b949e;font-size:11px;font-weight:600;text-transform:uppercase'>Paso 3</div>
            <div style='color:#e6edf3;font-size:13px;font-weight:700;margin-top:4px'>🏭 Industria</div>
            <div style='color:#8b949e;font-size:11px'>¿Qué industria destaca?</div>
          </div>
          <div style='color:#58a6ff;font-size:20px'>→</div>
          <div style='background:#8250df22;border:1px solid #8250df44;border-radius:8px;padding:10px 16px;text-align:center'>
            <div style='color:#8b949e;font-size:11px;font-weight:600;text-transform:uppercase'>Paso 4</div>
            <div style='color:#e6edf3;font-size:13px;font-weight:700;margin-top:4px'>📈 Acción</div>
            <div style='color:#8b949e;font-size:11px'>¿Qué ticker tiene mejor score?</div>
          </div>
        </div>
        <div style='color:#8b949e;font-size:11px;margin-top:14px;border-top:1px solid #1e2533;padding-top:10px'>
        ⚡ Regla clave: el sector arrastra a las acciones dentro de él. Buscar acciones donde sector + industria + acción apunten en la misma dirección.
        </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style='background:#0d1117;border:1px dashed #1e3a5f;border-radius:12px;padding:32px;text-align:center'>
          <div style='font-size:40px;margin-bottom:12px'>🎯</div>
          <div style='color:#e6edf3;font-size:16px;font-weight:600;margin-bottom:8px'>Resumen Top-Down</div>
          <div style='color:#8b949e;font-size:13px'>Presioná el botón para cargar todos los niveles y ver el análisis completo.</div>
        </div>
        """, unsafe_allow_html=True)

# ── Footer ────────────────────────────────────────────────────
st.markdown('<div style="height:24px"></div>', unsafe_allow_html=True)
st.markdown("""
<div style='text-align:center; color:#484f58; font-size:11px; padding:12px;
     border-top:1px solid #1e2533; margin-top:8px'>
📊 Análisis Top-Down &nbsp;·&nbsp; Datos: Yahoo Finance &nbsp;·&nbsp; Caché: 30 min
&nbsp;·&nbsp; Solo informativo, no constituye asesoramiento financiero
</div>
""", unsafe_allow_html=True)
