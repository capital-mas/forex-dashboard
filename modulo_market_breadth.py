# ==============================================================
#  MÓDULO: SALUD Y PARTICIPACIÓN DEL MERCADO (MARKET BREADTH)
# ==============================================================
"""
Módulo standalone pensado para integrarse a Capital+ dentro de
"Herramientas". No depende de nada del archivo principal — reutiliza
sus mismos colores y estilo de cards, pero si le pasás las funciones
propias (kpi_cards_4, fmt_precio, PLOTLY_CONFIG, chips_navegacion) las
usa en vez de sus versiones internas, para que quede 100% consistente
visualmente con el resto de la app.

INTEGRACIÓN (3 pasos):

1) Copiar este archivo junto al resto de tus módulos (por ejemplo al
   lado de modulo_fscore.py, modulo_promediador.py, etc.)

2) En el archivo principal, importar:

       from modulo_market_breadth import render_market_breadth

3) Agregar la entrada en tu diccionario de Herramientas y en el
   dispatcher de módulos:

   _HERRAMIENTAS_MAP = {
       ...
       '📡 Salud del Mercado': ('breadth', 'breadth'),
   }

   y en el bloque de renderizado (donde están los `elif MODULO == ...`):

   elif MODULO == 'breadth':
       render_market_breadth(
           ACCIONES_POR_INDUSTRIA=ACCIONES_POR_INDUSTRIA,
           PLOTLY_CONFIG=PLOTLY_CONFIG,
           kpi_cards_4=kpi_cards_4,
           fmt_precio=fmt_precio,
           chips_navegacion=chips_navegacion,
       )

No hace falta pasar nada de esto — si no le pasás argumentos, el
módulo funciona igual con sus propios fallbacks (mismo esquema de
colores del resto de la app).

LIMITACIÓN A TENER EN CUENTA:
Yahoo Finance no expone listas de constituyentes reales de un índice
(ej. "las 500 empresas del S&P500"). Por eso el "universo de mercado"
que se analiza acá es el que VOS elijas: una industria predefinida de
tu diccionario ACCIONES_POR_INDUSTRIA, o una lista manual de tickers
que pegues. Cuantos más activos representativos incluyas, más fiel es
la lectura de amplitud.

CHANGELOG (mejoras agregadas sobre la versión original):
 1. Estado principal ahora deriva de un rango de score (6 niveles) en
    vez de un único label fijo.
 2. Breadth Momentum 1W y 1M como indicador propio.
 3. Breadth Acceleration (aceleración del momentum semanal).
 4. A/D Ratio y A/D Net.
 5. A/D Line con detector de divergencia precio vs A/D.
 6. Trend Breadth ponderado (20/50/200) en vez de promedio simple.
 7. New Highs/Lows con NH-NL, NH/NL ratio y momentum de nuevos mínimos.
 8. Volume Breadth con % up/down y lectura de confirmación de volumen.
 9. Concentración Top5/Resto + contribución al movimiento del índice.
10. Equal Weight vs Índice (divergencia de participación amplia).
11. Market Health Score (separado del Breadth Score y su Momentum).
12. Matriz de diagnóstico Precio vs Breadth.
13. Detector automático de divergencias.
14. Régimen de mercado (6 estados).
"""

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==============================================================
#  ÍNDICES REALES — constituyentes completos (no proxy)
# ==============================================================
INDICES_CONSTITUYENTES = {
    'Dow Jones Industrial Average (30)': {
        'ticker_indice': '^DJI',
        'constituyentes': [
            'MMM', 'AMZN', 'AXP', 'AMGN', 'AAPL', 'BA', 'CAT', 'CVX', 'CSCO', 'KO',
            'GS', 'HD', 'HON', 'IBM', 'JNJ', 'JPM', 'MCD', 'MRK', 'MSFT', 'NKE',
            'NVDA', 'PG', 'CRM', 'SHW', 'TRV', 'UNH', 'V', 'WMT', 'DIS', 'GOOGL',
        ],
   },
       'Nasdaq 100 (100)': {
          'ticker_indice': '^NDX',
          'constituyentes': [
              'AAPL', 'ABNB', 'ADBE', 'ADI', 'ADP', 'ADSK', 'AEP', 'AMAT', 'AMD', 'AMGN',
              'AMZN', 'ANSS', 'APP', 'ARM', 'ASML', 'AVGO', 'AZN', 'BKR', 'BIIB', 'BKNG',
              'CDNS', 'CDW', 'CEG', 'CHTR', 'CMCSA', 'COST', 'CPRT', 'CRWD', 'CSGP', 'CSX',
              'CTAS', 'CTSH', 'DASH', 'DDOG', 'DLTR', 'DXCM', 'EA', 'EXC', 'FANG', 'FAST',
              'FTNT', 'GEHC', 'GFCI', 'GILD', 'GOOG', 'GOOGL', 'HON', 'IDXX', 'ILMN', 'INTC',
              'INTU', 'ISRG', 'KDP', 'KHC', 'KLAC', 'LRCX', 'LULU', 'MAR', 'MCHP', 'MDLZ',
              'MELI', 'META', 'MNST', 'MRVL', 'MSFT', 'MU', 'NFLX', 'NRA', 'NVDA', 'NXPI',
              'ODFL', 'ON', 'ORLY', 'PANW', 'PAYX', 'PCAR', 'PDD', 'PEP', 'PYPL', 'QCOM',
              'REGN', 'ROP', 'ROST', 'SBUX', 'SNPS', 'TEAM', 'TMUS', 'TSLA', 'TTD', 'TTWO',
              'TXN', 'VRSK', 'VRTX', 'WBD', 'WDAY', 'XEL', 'ZS'
          ],
    },
      'S&P 500 (503)': {
          'ticker_indice': '^GSPC',
          'constituyentes': [
              'A', 'AAL', 'AAPL', 'ABBV', 'ABNB', 'ABT', 'ACGL', 'ACN', 'ADBE', 'ADI',
              'ADM', 'ADP', 'ADSK', 'AEE', 'AEP', 'AES', 'AFL', 'AIG', 'AIZ', 'AJG',
              'AKAM', 'ALB', 'ALGN', 'ALL', 'ALLE', 'AMAT', 'AMCR', 'AMD', 'AME', 'AMGN',
              'AMP', 'AMT', 'AMZN', 'ANET', 'ANSS', 'AON', 'AOS', 'APA', 'APD', 'APH',
              'APTV', 'ARE', 'ATO', 'AVGO', 'AVB', 'AVY', 'AWK', 'AXON', 'AXP', 'AZO',
              'BA', 'BAC', 'BALL', 'BAX', 'BBWI', 'BBY', 'BDX', 'BEN', 'BF-B', 'BG',
              'BIIB', 'BIO', 'BK', 'BKNG', 'BKR', 'BLDR', 'BLK', 'BMY', 'BR', 'BRK-B',
              'BSX', 'BWA', 'BX', 'BXP', 'C', 'CAG', 'CAH', 'CARR', 'CAT', 'CB',
              'CERE', 'CBRE', 'CCI', 'CCJ', 'CDNS', 'CDW', 'CE', 'CEG', 'CF', 'CFG',
              'CHD', 'CHRW', 'CHTR', 'CI', 'CINF', 'CL', 'CLX', 'CMA', 'CMCSA', 'CME',
              'CMG', 'CMI', 'CMS', 'CNC', 'CNP', 'COF', 'COO', 'COP', 'COR', 'COST',
              'CPB', 'CPRT', 'CPT', 'CRL', 'CRM', 'CRWD', 'CSCO', 'CSGP', 'CSX', 'CTAS',
              'CTRA', 'CTSH', 'CTVA', 'CVS', 'CVX', 'CZR', 'D', 'DAL', 'DD', 'DDOG',
              'DE', 'DECK', 'DFS', 'DG', 'DGX', 'DHI', 'DHR', 'DIS', 'DLR', 'DLTR',
              'DOC', 'DOV', 'DOW', 'DPZ', 'DRI', 'DTE', 'DUK', 'DVA', 'DVN', 'DXCM',
              'EA', 'EBAY', 'ECL', 'ED', 'EFX', 'EG', 'EIX', 'EL', 'ELV', 'EMN',
              'EMR', 'ENPH', 'EOG', 'EPAM', 'EQIX', 'EQR', 'EQT', 'ERIE', 'ES', 'ESS',
              'ETN', 'ETR', 'EVRG', 'EW', 'EXC', 'EXPD', 'EXPE', 'EXR', 'F', 'FANG',
              'FAST', 'FCX', 'FDS', 'FDX', 'FE', 'FFIV', 'FI', 'FICO', 'FIS', 'FITB',
              'FMC', 'FOX', 'FOXA', 'FRT', 'FSLR', 'FTNT', 'FTV', 'GD', 'GDDY', 'GE',
              'GEHC', 'GEV', 'GEN', 'GILD', 'GIS', 'GL', 'GLW', 'GM', 'GNRC', 'GOOG',
              'GOOGL', 'GPC', 'GPN', 'GRMN', 'GS', 'GWW', 'HAL', 'HAS', 'HBAN', 'HCA',
              'HD', 'AES', 'HIG', 'HII', 'HLT', 'HOLX', 'HON', 'HPE', 'HPQ', 'HRL',
              'HSIC', 'HST', 'HSY', 'HUBB', 'HUM', 'HWM', 'IBM', 'ICE', 'IDXX', 'IEX',
              'IFF', 'INCY', 'INTC', 'INTU', 'INVH', 'IP', 'IPG', 'IQV', 'IR', 'IRM',
              'ISRG', 'IT', 'ITW', 'IVZ', 'J', 'JBHT', 'JBL', 'JCI', 'JKHY', 'JNJ',
              'JNPR', 'JPM', 'K', 'KDP', 'KEY', 'KEYS', 'KHC', 'KIM', 'KLAC', 'KMB',
              'KMI', 'KMX', 'KO', 'KR', 'KVUE', 'L', 'LDOS', 'LEN', 'LH', 'LHX',
              'LIN', 'LKQ', 'LLY', 'LMT', 'LNT', 'LOW', 'LRCX', 'LULU', 'LUV', 'LVS',
              'LW', 'LYB', 'LYV', 'MA', 'MAA', 'MAR', 'MAS', 'MCD', 'MCHP', 'MCK',
              'MCO', 'MDLZ', 'MDT', 'MET', 'META', 'MGM', 'MHK', 'MKC', 'MKTX', 'MLM',
              'MMC', 'MMM', 'MNST', 'MO', 'MOH', 'MOS', 'MPC', 'MPWR', 'MRK', 'MRNA',
              'MS', 'MSI', 'MSFT', 'MTB', 'MTD', 'MU', 'NCLH', 'NDAQ', 'NDSN', 'NEE',
              'NEM', 'NFLX', 'NI', 'NKE', 'NOC', 'NOW', 'NRG', 'NSC', 'NTAP', 'NTRS',
              'NUE', 'NVDA', 'NVR', 'NWS', 'NWSA', 'NXPI', 'O', 'ODFL', 'OKE', 'OMC',
              'ON', 'ORLY', 'ORCL', 'OTIS', 'OXY', 'PANW', 'PARA', 'PAYX', 'PAYC', 'PCAR',
              'PCG', 'PEG', 'PEP', 'PFE', 'PFG', 'PG', 'PGR', 'PH', 'PHM', 'PKG',
              'PLD', 'PLTR', 'PM', 'PNC', 'PNR', 'PNW', 'PODD', 'POOL', 'PPG', 'PPL',
              'PRU', 'PSA', 'PSX', 'PTC', 'PWR', 'PYPL', 'QCOM', 'QRVO', 'RCL', 'REG',
              'REGN', 'RF', 'RJF', 'RL', 'RMD', 'ROK', 'ROL', 'ROP', 'ROST', 'RSG',
              'RTX', 'RVTY', 'SBAC', 'SBUX', 'SCHW', 'SHW', 'SJM', 'SLB', 'SMCI', 'SNA',
              'SNPS', 'SO', 'SPG', 'SPGI', 'SRE', 'STE', 'STLD', 'STT', 'STX', 'SWK',
              'SWKS', 'SYK', 'SYF', 'SYY', 'T', 'TAP', 'TDG', 'TDY', 'TECH', 'TEL',
              'TER', 'TFC', 'TFX', 'TGT', 'TJX', 'TMO', 'TMUS', 'TPR', 'TRGP', 'TRMB',
              'TROW', 'TRV', 'TSCO', 'TSLA', 'TSN', 'TYL', 'TXN', 'TXT', 'UAL', 'UDR',
              'UHS', 'ULTA', 'UNH', 'UNP', 'UPS', 'URI', 'USB', 'V', 'VICI', 'VLO',
              'VLTO', 'VMC', 'VRSN', 'VRSK', 'VRTX', 'VST', 'VTR', 'VTRS', 'WZ', 'WAB',
              'WAT', 'WBA', 'WBD', 'WDC', 'WEC', 'WELL', 'WFC', 'WM', 'WMB', 'WMT',
              'WRB', 'WST', 'WTW', 'WY', 'WYNN', 'XEL', 'XOM', 'XYL', 'YUM', 'ZBH',
              'ZBRA', 'ZTS'
          ],
   },
    # 👉 Acá se suman más índices con la lista real de constituyentes,
    #    por ejemplo 'S&P 500 (500)', 'Nasdaq 100 (100)', 'Merval (Argentina)', etc.
}

# ==============================================================
#  PALETA Y HELPERS DE FALLBACK (si no se inyectan desde la app)
# ==============================================================

C_BG1, C_BG2   = '#0d1117', '#07090f'
C_GRID         = '#21262d'
C_TEXT         = '#e6edf3'
C_MUTED        = '#6b7d9a'
C_GREEN        = '#3fb950'
C_LGRE         = '#7ee787'
C_YELL         = '#e3b341'
C_LRED         = '#f0883e'
C_RED          = '#f85149'
C_ACENT        = '#3a7bd5'
C_MONSTER      = '#6CC24A'
C_BLUE         = '#58a6ff'

PLOTLY_LAYOUT_BASE_BD = dict(
    plot_bgcolor=C_BG1, paper_bgcolor=C_BG2,
    font=dict(color='#b0bcd0', family='Inter, sans-serif'),
    dragmode=False,
)
PLOTLY_CONFIG_BD = dict(displayModeBar=False, scrollZoom=False)


def _bd_color_score(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return C_MUTED
    if v <= 20:  return C_RED
    if v <= 40:  return C_LRED
    if v <= 60:  return C_YELL
    if v <= 80:  return C_LGRE
    return C_GREEN


def _fmt_precio_bd(p):
    if p is None or (isinstance(p, float) and np.isnan(p)) or p <= 0:
        return 'S/D'
    if p >= 1000: return f'${p:,.0f}'
    if p >= 10:   return f'${p:.2f}'
    return f'${p:.4f}'


def _kpi_cards_4_bd(items):
    """Fallback local de kpi_cards_4 — mismo look que el resto de Capital+.
    items = (label, value, sub, color)"""
    cols = st.columns(len(items))
    for col, item in zip(cols, items):
        label, value, sub, color = item[0], item[1], item[2], item[3]
        with col:
            st.markdown(
                f'<div style="background:{C_BG1};border:1px solid {C_GRID};border-radius:10px;'
                f'padding:16px 18px;position:relative;overflow:hidden">'
                f'<div style="position:absolute;top:0;left:0;width:100%;height:2px;background:{color}"></div>'
                f'<div style="color:{C_MUTED};font-size:12px;font-weight:700;text-transform:uppercase;'
                f'letter-spacing:1px;margin-bottom:6px">{label}</div>'
                f'<div style="color:{C_TEXT};font-size:22px;font-weight:700;letter-spacing:-0.5px;'
                f'font-family:JetBrains Mono,monospace">{value}</div>'
                f'<div style="color:{C_MUTED};font-size:13px;margin-top:4px">{sub}</div></div>',
                unsafe_allow_html=True,
            )
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)


def _bd_badge(titulo, emoji, label, color, detalle=''):
    """Badge chico reutilizable para estados/regímenes (mejoras 1, 11, 14)."""
    st.markdown(f"""
    <div style="background:{color}15;border:1px solid {color};border-radius:10px;
         padding:12px 14px;text-align:center;height:100%">
      <div style="font-size:10px;color:{C_MUTED};text-transform:uppercase;letter-spacing:1px;
           margin-bottom:4px">{titulo}</div>
      <div style="font-size:15px;font-weight:800;color:{color}">{emoji} {label}</div>
      {f'<div style="font-size:11px;color:{C_MUTED};margin-top:4px">{detalle}</div>' if detalle else ''}
    </div>
    """, unsafe_allow_html=True)


# ==============================================================
#  DESCARGA DE DATOS
# ==============================================================

@st.cache_data(ttl=1800, show_spinner=False)
def _bd_descargar_universo(tickers_tuple, periodo='1y'):
    """Descarga OHLCV de todo el universo en un solo bulk call."""
    try:
        import yfinance as yf
        tickers = sorted(set(tickers_tuple))
        data = yf.download(tickers, period=periodo, interval='1d',
                            auto_adjust=True, progress=False, group_by='ticker')
        if data is None or data.empty:
            return None
        return data
    except Exception:
        return None


def _bd_extraer_serie(data, tk, campo='Close'):
    try:
        if isinstance(data.columns, pd.MultiIndex):
            if (tk, campo) in data.columns:
                return data[(tk, campo)].dropna()
            elif (campo, tk) in data.columns:
                return data[(campo, tk)].dropna()
            return pd.Series(dtype=float)
        # un solo ticker: columnas planas
        if campo in data.columns:
            return data[campo].dropna()
        return pd.Series(dtype=float)
    except Exception:
        return pd.Series(dtype=float)


@st.cache_data(ttl=86400, show_spinner=False)
def _bd_market_caps(tickers_tuple):
    """Market cap por ticker (para el subíndice de concentración). Cacheado 24h
    porque la cap no cambia significativamente rueda a rueda."""
    import yfinance as yf
    caps = {}

    def _one(tk):
        try:
            fi = yf.Ticker(tk).fast_info
            mc = fi.get('market_cap') or fi.get('marketCap')
            return tk, mc
        except Exception:
            return tk, None

    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(_one, tk): tk for tk in tickers_tuple}
        for fut in as_completed(futs):
            tk, mc = fut.result()
            if mc:
                caps[tk] = float(mc)
    return caps


# ==============================================================
#  CÁLCULO DE SUB-ÍNDICES DE AMPLITUD
# ==============================================================

def _bd_snapshot(df_close, df_vol, hasta=None):
    """Calcula Trend Breadth, Advance/Decline, New Highs/Lows y Volume Breadth
    usando datos hasta la fila posicional 'hasta' (inclusive). Si hasta=None,
    usa toda la data disponible. Sirve para el snapshot de hoy y para
    reconstruir snapshots pasados (1 semana, 2 semanas, 1 mes) y así medir
    momentum y aceleración del Breadth Score."""
    dfc = df_close if hasta is None else df_close.iloc[:hasta + 1]
    dfv = df_vol if hasta is None else df_vol.iloc[:hasta + 1]
    if len(dfc) < 25:
        return None

    ret = dfc.pct_change()
    ultimo_ret = ret.iloc[-1].dropna()
    adv = int((ultimo_ret > 0).sum())
    dec = int((ultimo_ret < 0).sum())
    ad_score = adv / (adv + dec) * 100 if (adv + dec) > 0 else 50.0
    # Mejora 4: A/D Ratio y A/D Net
    ad_ratio = round(adv / dec, 2) if dec > 0 else (float('inf') if adv > 0 else 1.0)
    ad_net = adv - dec

    n = len(dfc)
    last = dfc.iloc[-1]
    sma20 = dfc.rolling(min(20, n)).mean().iloc[-1]
    sma50 = dfc.rolling(min(50, n)).mean().iloc[-1] if n >= 10 else sma20
    sma200 = dfc.rolling(min(200, n)).mean().iloc[-1] if n >= 30 else sma50
    pct20 = float((last > sma20).mean() * 100)
    pct50 = float((last > sma50).mean() * 100)
    pct200 = float((last > sma200).mean() * 100)
    # Mejora 6: Trend Breadth Score ponderado (corto/medio/largo plazo)
    trend_score = pct20 * 0.30 + pct50 * 0.35 + pct200 * 0.35

    ventana_hl = min(252, n)
    roll_max = dfc.rolling(ventana_hl).max().iloc[-1]
    roll_min = dfc.rolling(ventana_hl).min().iloc[-1]
    nh = int((last >= roll_max).sum())
    nl = int((last <= roll_min).sum())
    nhnl_score = nh / (nh + nl) * 100 if (nh + nl) > 0 else 50.0
    # Mejora 7: NH-NL Net y NH/NL Ratio
    nhnl_net = nh - nl
    nhnl_ratio = round(nh / nl, 2) if nl > 0 else (float('inf') if nh > 0 else 1.0)

    vol_hoy = dfv.iloc[-1].reindex(ultimo_ret.index).fillna(0)
    up_vol = float(vol_hoy[ultimo_ret > 0].sum())
    down_vol = float(vol_hoy[ultimo_ret < 0].sum())
    vol_score = up_vol / (up_vol + down_vol) * 100 if (up_vol + down_vol) > 0 else 50.0
    # Mejora 8: % Up/Down volume y ratio
    tot_vol = up_vol + down_vol
    up_vol_pct = round(up_vol / tot_vol * 100, 1) if tot_vol > 0 else 50.0
    down_vol_pct = round(100 - up_vol_pct, 1) if tot_vol > 0 else 50.0
    up_down_vol_ratio = round(up_vol / down_vol, 2) if down_vol > 0 else (float('inf') if up_vol > 0 else 1.0)

    return dict(
        adv=adv, dec=dec, ad_score=round(ad_score, 1), ad_ratio=ad_ratio, ad_net=ad_net,
        pct20=round(pct20, 1), pct50=round(pct50, 1), pct200=round(pct200, 1),
        trend_score=round(trend_score, 1),
        nh=nh, nl=nl, nhnl_score=round(nhnl_score, 1), nhnl_net=nhnl_net, nhnl_ratio=nhnl_ratio,
        up_vol=up_vol, down_vol=down_vol, vol_score=round(vol_score, 1),
        up_vol_pct=up_vol_pct, down_vol_pct=down_vol_pct, up_down_vol_ratio=up_down_vol_ratio,
        ret_1d_serie=ultimo_ret,
    )


def _bd_concentracion(tickers, caps, df_close):
    """Score de concentración: combina el peso de las Top 5 empresas por
    capitalización y la divergencia entre el retorno ponderado por cap
    vs. el retorno equal-weight del último mes. Cuanto más concentrado
    el mercado en pocas empresas, más bajo el score."""
    tickers_con_cap = [t for t in tickers if t in caps and t in df_close.columns]
    if len(tickers_con_cap) < 3:
        return dict(top5_pct=None, top10_pct=None, resto_pct=None, conc_score=50.0,
                    pesos=None, diff_ret=0.0, top5_tickers=[])

    caps_ser = pd.Series({t: caps[t] for t in tickers_con_cap}).sort_values(ascending=False)
    total = caps_ser.sum()
    pesos = caps_ser / total
    top5_pct = float(pesos.iloc[:5].sum() * 100)
    top10_pct = float(pesos.iloc[:min(10, len(pesos))].sum() * 100)
    top5_tickers = list(pesos.index[:5])

    n = len(df_close)
    ventana = min(21, n - 1) if n > 1 else 0
    diff_ret = 0.0
    if ventana > 0:
        sub = df_close[tickers_con_cap].iloc[[-ventana - 1, -1]]
        ret_ind = (sub.iloc[-1] / sub.iloc[0] - 1).dropna()
        pesos_alineados = pesos.reindex(ret_ind.index).fillna(0)
        if pesos_alineados.sum() > 0:
            cap_ret = float((ret_ind * pesos_alineados).sum() / pesos_alineados.sum())
            eq_ret = float(ret_ind.mean())
            diff_ret = cap_ret - eq_ret

    score1 = max(0.0, min(100.0, 100 - top5_pct))                 # menos peso Top5 = mejor
    score2 = max(0.0, min(100.0, 50 - diff_ret * 500))             # cap outperform fuerte = peor
    conc_score = round(score1 * 0.6 + score2 * 0.4, 1)

    return dict(top5_pct=round(top5_pct, 1), top10_pct=round(top10_pct, 1),
                resto_pct=round(100 - top5_pct, 1),
                conc_score=conc_score, pesos=pesos, diff_ret=diff_ret,
                top5_tickers=top5_tickers)


def _bd_breadth_score(snap, conc_score):
    if snap is None:
        return None
    return round(
        snap['trend_score'] * 0.25 + snap['ad_score'] * 0.20 + snap['nhnl_score'] * 0.15
        + snap['vol_score'] * 0.20 + conc_score * 0.20, 1
    )


# ==============================================================
#  MEJORA 1 — ESTADO PRINCIPAL POR RANGO DE SCORE
# ==============================================================

def _bd_estado_por_score(score):
    """Mapea el Breadth Score (0-100) a uno de 6 niveles de estado.
    Reemplaza el label único y fijo que tenía antes la app."""
    if score is None or (isinstance(score, float) and np.isnan(score)):
        return ('⚪', 'SIN DATOS', C_MUTED)
    if score >= 80:  return ('🟢', 'PARTICIPACIÓN MUY FUERTE', C_GREEN)
    if score >= 65:  return ('🟢', 'PARTICIPACIÓN SALUDABLE', C_LGRE)
    if score >= 50:  return ('🟡', 'PARTICIPACIÓN NEUTRAL', C_YELL)
    if score >= 35:  return ('🟠', 'DEBILIDAD INTERNA', C_LRED)
    if score >= 20:  return ('🔴', 'DETERIORO GENERALIZADO', C_RED)
    return ('🔴', 'CAPITULACIÓN / ESTRÉS EXTREMO', C_RED)


# ==============================================================
#  ESTADO DE PARTICIPACIÓN DEL MERCADO (cruce precio × breadth)
# ==============================================================

def _bd_estado_mercado(price_ret_1m, breadth_now, breadth_prev, ad_score, nhnl_score):
    """Cruza la dirección del precio (índice proxy, 1 mes) con la amplitud
    interna del mercado para devolver uno de los 5 estados + neutral."""
    delta_breadth = (breadth_now - breadth_prev) if breadth_prev is not None else 0.0
    precio_sube = price_ret_1m is not None and price_ret_1m > 0.5
    precio_baja = price_ret_1m is not None and price_ret_1m < -0.5

    if precio_sube and breadth_now >= 60 and ad_score >= 55 and nhnl_score >= 55:
        return ('CONFIRMACIÓN ALCISTA', '🟢', C_GREEN,
                'El precio sube y una porción amplia del mercado acompaña: amplitud, avance/declive '
                'y nuevos máximos alineados al alza. Movimiento sano.')

    if precio_sube and breadth_now < 45 and delta_breadth <= 2:
        if breadth_now < 35 or ad_score < 40:
            return ('DIVERGENCIA', '🟠', C_LRED,
                    'El precio sigue haciendo nuevos máximos, pero la participación interna se '
                    'deteriora con fuerza — señal de alerta de fragilidad en la suba.')
        return ('CONCENTRACIÓN', '🟡', C_YELL,
                'El índice sube, pero cada vez depende de menos activos: la amplitud no acompaña '
                'el nuevo máximo del precio.')

    if precio_baja and breadth_now < 45 and ad_score < 45:
        return ('DETERIORO GENERALIZADO', '🔴', C_RED,
                'La baja está siendo acompañada ampliamente: mayoría de activos cayendo, con '
                'volumen y amplitud débiles en todo el universo analizado.')

    if (not precio_sube) and breadth_now >= 55 and delta_breadth > 0 and ad_score >= 55:
        return ('ACUMULACIÓN / RECUPERACIÓN', '🔵', C_ACENT,
                'El precio todavía no confirma fortaleza, pero la participación interna del mercado '
                'empieza a mejorar — patrón típico de zonas de piso.')

    return ('NEUTRAL / MIXTO', '⚪', C_MUTED,
            'Los indicadores de amplitud no muestran un sesgo dominante por ahora — sin '
            'confirmación ni divergencia clara entre precio y participación interna.')


# ==============================================================
#  MEJORA 11 — MARKET HEALTH SCORE
# ==============================================================

def _bd_market_health(breadth_hoy, momentum_1m):
    """Separa 'estado actual' (Breadth Score) de 'dirección' (Momentum) y
    los combina en un tercer número: Market Health Score. No reemplaza a
    ninguno de los dos — se muestran los tres por separado en el dashboard."""
    if breadth_hoy is None:
        return None
    mom = momentum_1m if momentum_1m is not None else 0.0
    health = breadth_hoy * 0.7 + (50 + mom) * 0.3
    return round(max(0.0, min(100.0, health)), 1)


# ==============================================================
#  MEJORA 12 — MATRIZ DE DIAGNÓSTICO PRECIO × BREADTH
# ==============================================================

def _bd_matriz_diagnostico(ret_1m, momentum_1m):
    tabla = {
        ('up', 'up'):     ('🟢', 'Rally saludable'),
        ('up', 'down'):   ('🔴', 'Rally concentrado'),
        ('down', 'down'): ('🔴', 'Venta generalizada'),
        ('down', 'up'):   ('🟢', 'Posible acumulación'),
        ('flat', 'up'):   ('🟢', 'Acumulación'),
        ('flat', 'down'): ('🟠', 'Distribución'),
        ('up', 'flat'):   ('🟡', 'Suba sin cambios de fondo en breadth'),
        ('down', 'flat'): ('🟡', 'Baja sin cambios de fondo en breadth'),
        ('flat', 'flat'): ('⚪', 'Mercado sin definición'),
    }
    dir_precio = 'up' if (ret_1m is not None and ret_1m > 0.5) else \
                 'down' if (ret_1m is not None and ret_1m < -0.5) else 'flat'
    dir_breadth = 'up' if (momentum_1m is not None and momentum_1m > 1) else \
                  'down' if (momentum_1m is not None and momentum_1m < -1) else 'flat'
    emoji, label = tabla.get((dir_precio, dir_breadth), ('⚪', 'Mixto / sin señal clara'))
    return emoji, label, dir_precio, dir_breadth


# ==============================================================
#  MEJORA 13 — DETECTOR DE DIVERGENCIAS
# ==============================================================

def _bd_detectar_divergencias(dir_precio, momentum_1m, ad_score, nh_now, nh_1m, ad_line_dir):
    """Devuelve una lista de (emoji, texto) con las divergencias/confirmaciones
    detectadas automáticamente cruzando precio contra distintos indicadores
    de amplitud."""
    señales = []

    if dir_precio == 'up' and momentum_1m is not None and momentum_1m < -1:
        señales.append(('🔴', 'Precio ↑ + Breadth ↓ → Divergencia bajista'))
    elif dir_precio == 'down' and momentum_1m is not None and momentum_1m > 1:
        señales.append(('🟢', 'Precio ↓ + Breadth ↑ → Divergencia alcista'))

    if dir_precio == 'up' and ad_line_dir == 'down':
        señales.append(('🔴', 'Precio ↑ + A/D Line ↓ → Distribución potencial'))
    elif dir_precio == 'down' and ad_line_dir == 'up':
        señales.append(('🟢', 'Precio ↓ + A/D Line ↑ → Acumulación potencial'))

    if dir_precio == 'up' and nh_now is not None and nh_1m is not None and nh_now < nh_1m:
        señales.append(('🟠', 'Precio ↑ + Nuevos Máximos ↓ → Menor participación'))

    if not señales:
        señales.append(('⚪', 'No se detectan divergencias relevantes entre precio y amplitud.'))

    return señales


# ==============================================================
#  MEJORA 14 — RÉGIMEN DE MERCADO
# ==============================================================

def _bd_regimen_mercado(breadth_hoy, momentum_1m, ad_score, trend_score, ret_1m):
    """Clasifica el mercado en uno de 6 regímenes combinando nivel y
    dirección del Breadth Score junto con tendencia y avance/declive."""
    mom = momentum_1m if momentum_1m is not None else 0.0
    precio_sube = ret_1m is not None and ret_1m > 0.5
    precio_baja = ret_1m is not None and ret_1m < -0.5

    if breadth_hoy is None:
        return ('⚪', 'SIN DATOS', C_MUTED)
    if breadth_hoy < 20:
        return ('🔴', 'CAPITULACIÓN', C_RED)
    if breadth_hoy < 35 and mom < 0:
        return ('🔴', 'CONTRACCIÓN', C_RED)
    if breadth_hoy < 50 and mom <= 0:
        return ('🟠', 'DETERIORO', C_LRED)
    if breadth_hoy >= 65 and mom >= 0 and precio_sube and trend_score >= 55:
        return ('🟢', 'EXPANSIÓN', C_GREEN)
    if breadth_hoy >= 50 and precio_sube and ad_score >= 50:
        return ('🟢', 'TENDENCIA ALCISTA', C_LGRE)
    return ('🟡', 'TRANSICIÓN', C_YELL)


# ==============================================================
#  RENDER PRINCIPAL
# ==============================================================

def render_market_breadth(
    ACCIONES_POR_INDUSTRIA=None,
    PLOTLY_CONFIG=None,
    kpi_cards_4=None,
    fmt_precio=None,
    chips_navegacion=None,
):
    PLOTLY_CONFIG = PLOTLY_CONFIG or PLOTLY_CONFIG_BD
    kpi_cards_4 = kpi_cards_4 or _kpi_cards_4_bd
    fmt_precio = fmt_precio or _fmt_precio_bd

    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#0d1c20 0%,#0a2530 50%,#0d1117 100%);
         border:1px solid {C_GRID}; border-top:2px solid {C_ACENT};
         border-radius:14px; padding:28px 32px; margin-bottom:24px;">
      <div style="font-size:18px;font-weight:700;color:{C_TEXT};margin-bottom:6px">
        📡 Salud y Participación del Mercado
      </div>
      <div style="font-size:12px;color:{C_MUTED};line-height:1.7">
        Amplitud de mercado (breadth): mide cuántos activos acompañan de verdad un movimiento de
        precio, no solo si el índice sube o baja. Combina Tendencia, Avance/Declive, Máximos/Mínimos
        de 52 semanas, Volumen y Concentración en un <b style="color:{C_TEXT}">Breadth Score</b> y un
        estado de participación (confirmación, concentración, divergencia, deterioro o acumulación).
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Selección de universo ──────────────────────────────────────────
    opciones_modo = ['Lista manual de tickers']
    if INDICES_CONSTITUYENTES:
        opciones_modo.insert(0, 'Índice real (constituyentes)')
    if ACCIONES_POR_INDUSTRIA:
        opciones_modo.insert(0 if not INDICES_CONSTITUYENTES else 1, 'Industria predefinida')

    modo = st.radio('Universo a analizar', opciones_modo, horizontal=True, key='bd_modo')

    tickers_universo, nombre_universo, ticker_indice_real = [], '', None

    if modo == 'Índice real (constituyentes)':
        idx_sel = st.selectbox('Índice', list(INDICES_CONSTITUYENTES.keys()), key='bd_indice_real')
        info_idx = INDICES_CONSTITUYENTES[idx_sel]
        tickers_universo = list(info_idx['constituyentes'])
        ticker_indice_real = info_idx.get('ticker_indice')
        nombre_universo = idx_sel
        st.caption(f'📌 {len(tickers_universo)} constituyentes reales del índice.')
    elif modo == 'Industria predefinida' and ACCIONES_POR_INDUSTRIA:
        ind_sel = st.selectbox('Industria', list(ACCIONES_POR_INDUSTRIA.keys()), key='bd_industria')
        tickers_universo = list(ACCIONES_POR_INDUSTRIA[ind_sel])
        nombre_universo = ind_sel
    else:
        txt = st.text_area(
            'Tickers separados por coma',
            'AAPL,MSFT,GOOGL,AMZN,META,NVDA,TSLA,AVGO,ORCL,CRM,ADBE,AMD,QCOM,INTC,IBM',
            key='bd_manual', height=80,
        )
        tickers_universo = sorted(set(t.strip().upper() for t in txt.split(',') if t.strip()))
        nombre_universo = 'Lista manual'

    c_p1, c_p2 = st.columns([1, 3])
    with c_p1:
        periodo = st.selectbox('Historial', ['6mo', '1y', '2y'], index=1, key='bd_periodo')
    with c_p2:
        st.markdown(
            f'<div style="font-size:11px;color:{C_MUTED};padding-top:28px">'
            f'{len(tickers_universo)} tickers en el universo actual.</div>',
            unsafe_allow_html=True,
        )

    if len(tickers_universo) < 5:
        st.info('Necesitás al menos 5 tickers para un análisis de amplitud representativo.')
        return

    if st.button('▶ Calcular Salud del Mercado', key='bd_run', type='primary'):
        st.session_state['bd_run_flag'] = True
        st.session_state['bd_universo_firma'] = (tuple(tickers_universo), periodo)

    if not st.session_state.get('bd_run_flag'):
        st.markdown(f"""
        <div style='background:{C_BG1};border:1px dashed {C_GRID};border-radius:10px;padding:40px;text-align:center'>
          <div style='font-size:40px;margin-bottom:12px'>📡</div>
          <div style='color:{C_TEXT};font-size:14px;font-weight:600;margin-bottom:6px'>Salud del Mercado</div>
          <div style='color:{C_MUTED};font-size:12px'>Elegí un universo y presioná "Calcular Salud del Mercado".</div>
        </div>
        """, unsafe_allow_html=True)
        return

    tickers_descarga = list(tickers_universo)
    if ticker_indice_real and ticker_indice_real not in tickers_descarga:
        tickers_descarga.append(ticker_indice_real)

    with st.spinner(f'Descargando {len(tickers_descarga)} activos ({periodo})...'):
        data = _bd_descargar_universo(tuple(tickers_descarga), periodo)
    if data is None:
        st.error('No se pudieron descargar los datos. Probá con otro universo o volvé a intentar.')
        return

    serie_indice_real = None
    if ticker_indice_real:
        serie_indice_real = _bd_extraer_serie(data, ticker_indice_real, 'Close')
        if len(serie_indice_real) < 25:
            serie_indice_real = None

    closes, vols = {}, {}
    for tk in tickers_universo:
        c = _bd_extraer_serie(data, tk, 'Close')
        v = _bd_extraer_serie(data, tk, 'Volume')
        if len(c) > 25:
            closes[tk] = c
            vols[tk] = v

    faltantes = [t for t in tickers_universo if t not in closes]
    if faltantes:
        st.caption(f'⚠️ Sin datos suficientes para: {", ".join(faltantes[:15])}'
                   f'{" (+ más)" if len(faltantes) > 15 else ""} — se excluyen del análisis.')

    if len(closes) < 5:
        st.error('Datos insuficientes para calcular amplitud (menos de 5 activos válidos).')
        return

    df_close = pd.DataFrame(closes).sort_index().ffill().dropna(how='all')
    df_vol = pd.DataFrame(vols).reindex(df_close.index).fillna(0)
    n_dias = len(df_close)

    with st.spinner('Descargando capitalización de mercado (para concentración)...'):
        caps = _bd_market_caps(tuple(closes.keys()))

    snap_hoy = _bd_snapshot(df_close, df_vol)
    if snap_hoy is None:
        st.error('Historial insuficiente para calcular amplitud (mínimo ~25 ruedas).')
        return

    # ── Snapshots históricos para Momentum / Aceleración (mejoras 2 y 3) ──
    idx_1m = max(0, n_dias - 22)
    idx_1w = max(0, n_dias - 6)
    idx_2w = max(0, n_dias - 11)
    snap_prev = _bd_snapshot(df_close, df_vol, hasta=idx_1m) if n_dias > 30 else None
    snap_1w = _bd_snapshot(df_close, df_vol, hasta=idx_1w) if n_dias > 15 else None
    snap_2w = _bd_snapshot(df_close, df_vol, hasta=idx_2w) if n_dias > 20 else None

    conc = _bd_concentracion(list(closes.keys()), caps, df_close)
    breadth_hoy = _bd_breadth_score(snap_hoy, conc['conc_score'])
    breadth_prev = _bd_breadth_score(snap_prev, conc['conc_score']) if snap_prev else None
    breadth_1w = _bd_breadth_score(snap_1w, conc['conc_score']) if snap_1w else None
    breadth_2w = _bd_breadth_score(snap_2w, conc['conc_score']) if snap_2w else None

    # Mejora 2: Breadth Momentum 1W / 1M
    momentum_1m = (breadth_hoy - breadth_prev) if (breadth_hoy is not None and breadth_prev is not None) else None
    momentum_1w = (breadth_hoy - breadth_1w) if (breadth_hoy is not None and breadth_1w is not None) else None
    # Mejora 3: Breadth Acceleration (momentum de esta semana vs. semana previa)
    momentum_prev_1w = (breadth_1w - breadth_2w) if (breadth_1w is not None and breadth_2w is not None) else None
    aceleracion = (momentum_1w - momentum_prev_1w) if (momentum_1w is not None and momentum_prev_1w is not None) else None

    # ── Índice proxy (ponderado por cap si hay datos, si no equal-weight) ──
    if conc['pesos'] is not None and conc['pesos'].sum() > 0:
        pesos_full = conc['pesos'].reindex(df_close.columns).fillna(0)
        if pesos_full.sum() == 0:
            pesos_full = pd.Series(1 / len(df_close.columns), index=df_close.columns)
        else:
            pesos_full = pesos_full / pesos_full.sum()
    else:
        pesos_full = pd.Series(1 / len(df_close.columns), index=df_close.columns)

    idx_serie_proxy = (df_close * pesos_full).sum(axis=1)
    # Si hay ticker real del índice (ej. ^DJI), usamos SU precio para los retornos
    # y para cruzar contra la amplitud — el proxy ponderado por cap queda de respaldo
    # solo para universos armados a mano (industria / lista manual) sin índice real.
    idx_serie = serie_indice_real if serie_indice_real is not None else idx_serie_proxy
    usando_indice_real = serie_indice_real is not None

    def _ret_de(serie, dias):
        if serie is None or len(serie) <= dias:
            return None
        return float(serie.iloc[-1] / serie.iloc[-dias - 1] - 1) * 100

    ret_1d = _ret_de(idx_serie, 1)
    ret_1w = _ret_de(idx_serie, 5)
    ret_1m = _ret_de(idx_serie, 21)
    ret_3m = _ret_de(idx_serie, 63)
    ret_6m = _ret_de(idx_serie, 126)
    ret_1y = _ret_de(idx_serie, 252)

    # Mejora 10: Equal Weight vs Índice
    serie_equal_weight = (df_close / df_close.iloc[0]).mean(axis=1)
    ret_1m_eq = _ret_de(serie_equal_weight, 21)
    ew_divergence = (ret_1m - ret_1m_eq) if (ret_1m is not None and ret_1m_eq is not None) else None

    estado, emoji_estado, color_estado, desc_estado = _bd_estado_mercado(
        ret_1m, breadth_hoy, breadth_prev, snap_hoy['ad_score'], snap_hoy['nhnl_score']
    )
    emoji_score, label_score, color_score = _bd_estado_por_score(breadth_hoy)
    market_health = _bd_market_health(breadth_hoy, momentum_1m)
    emoji_reg, label_reg, color_reg = _bd_regimen_mercado(
        breadth_hoy, momentum_1m, snap_hoy['ad_score'], snap_hoy['trend_score'], ret_1m
    )

    # ── Card de estado (cruce precio × breadth) ─────────────────────────
    st.markdown(f"""
    <div style="background:{color_estado}15;border:1.5px solid {color_estado};border-radius:14px;
         padding:22px 26px;text-align:center;margin:10px 0 14px 0">
      <div style="font-size:11px;color:{C_MUTED};text-transform:uppercase;letter-spacing:1.5px;margin-bottom:8px">
        Estado de Participación del Mercado — {nombre_universo}
      </div>
      <div style="font-size:24px;font-weight:800;color:{color_estado}">{emoji_estado} {estado}</div>
      <div style="font-size:13px;color:{C_TEXT};margin-top:10px;max-width:680px;margin-left:auto;
           margin-right:auto;line-height:1.6">
        {desc_estado}
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Mejoras 1, 11, 14: badges de Estado por Score / Market Health / Régimen ──
    c_b1, c_b2, c_b3 = st.columns(3)
    with c_b1:
        _bd_badge('Estado por Breadth Score', emoji_score, label_score, color_score,
                   f'Score: {breadth_hoy:.0f}/100' if breadth_hoy is not None else '')
    with c_b2:
        detalle_health = ''
        if market_health is not None:
            detalle_health = (f'Breadth {breadth_hoy:.0f} + Momentum {momentum_1m:+.1f}'
                               if momentum_1m is not None else f'Breadth {breadth_hoy:.0f}')
        _bd_badge('Market Health Score', '🩺', f'{market_health:.0f}/100' if market_health is not None else 'N/D',
                   _bd_color_score(market_health), detalle_health)
    with c_b3:
        _bd_badge('Régimen de Mercado', emoji_reg, label_reg, color_reg,
                   f'1M: {ret_1m:+.2f}%' if ret_1m is not None else '')

    st.markdown('<div style="height:14px"></div>', unsafe_allow_html=True)

    # ── KPIs principales ─────────────────────────────────────────────────
    kpi_cards_4([
        ('Breadth Score', f'{breadth_hoy:.0f}/100',
         (f"{momentum_1m:+.1f} vs. hace 1 mes" if momentum_1m is not None else 'Score compuesto'),
         _bd_color_score(breadth_hoy)),
        ('Avance / Declive', f"{snap_hoy['adv']} / {snap_hoy['dec']}",
         f"Ratio {snap_hoy['ad_ratio']:.2f} · Net {snap_hoy['ad_net']:+d}", _bd_color_score(snap_hoy['ad_score'])),
        ('Máx / Mín 52 sem.', f"{snap_hoy['nh']} / {snap_hoy['nl']}",
         f"NH-NL {snap_hoy['nhnl_net']:+d} · Ratio {snap_hoy['nhnl_ratio']:.2f}", _bd_color_score(snap_hoy['nhnl_score'])),
        ('Concentración Top 5', f"{conc['top5_pct']:.1f}%" if conc['top5_pct'] is not None else 'N/D',
         f"Resto: {conc['resto_pct']:.1f}%" if conc['resto_pct'] is not None else f"Score: {conc['conc_score']:.0f}/100",
         _bd_color_score(conc['conc_score'])),
    ])

    # ── Mejoras 2 y 3: Breadth Momentum y Aceleración ──────────────────────
    st.markdown('##### 📐 Breadth Momentum & Aceleración')
    kpi_cards_4([
        ('Momentum 1W', f"{momentum_1w:+.1f}" if momentum_1w is not None else 'N/D',
         'vs. hace 1 semana', _bd_color_score(50 + momentum_1w) if momentum_1w is not None else C_MUTED),
        ('Momentum 1M', f"{momentum_1m:+.1f}" if momentum_1m is not None else 'N/D',
         'vs. hace 1 mes', _bd_color_score(50 + momentum_1m) if momentum_1m is not None else C_MUTED),
        ('Aceleración', f"{aceleracion:+.1f}" if aceleracion is not None else 'N/D',
         ('⚠️ Deterioro acelerando' if (aceleracion is not None and aceleracion < -1 and momentum_1w is not None and momentum_1w < 0)
          else ('Mejora acelerando' if (aceleracion is not None and aceleracion > 1) else 'Sin cambios bruscos')),
         _bd_color_score(50 + aceleracion) if aceleracion is not None else C_MUTED),
        ('Equal Weight vs Índice', f"{ew_divergence:+.2f}%" if ew_divergence is not None else 'N/D',
         ('⚠️ Rally concentrado' if (ew_divergence is not None and ew_divergence > 1) else
          ('🟢 Participación amplia' if (ew_divergence is not None and ew_divergence < -1) else 'Sin sesgo relevante')),
         _bd_color_score(50 - (ew_divergence or 0) * 5)),
    ])

    label_precio = f'📊 Rendimiento del índice real ({ticker_indice_real})' if usando_indice_real \
        else '📊 Rendimiento del índice proxy (ponderado por cap)'
    st.markdown(f'##### {label_precio}')
    cols_ret = st.columns(6)
    for col, (lbl, val) in zip(cols_ret,
        [('1D', ret_1d), ('1W', ret_1w), ('1M', ret_1m), ('3M', ret_3m), ('6M', ret_6m), ('1Y', ret_1y)]):
        with col:
            st.metric(lbl, f'{val:+.2f}%' if val is not None else 'N/D')

    # ── Subíndices ───────────────────────────────────────────────────────
    st.markdown('---')
    st.markdown('### 🧩 Subíndices de Amplitud')
    subitems = [
        ('Trend Breadth', snap_hoy['trend_score'], '25%'),
        ('Advance/Decline', snap_hoy['ad_score'], '20%'),
        ('New Highs/Lows', snap_hoy['nhnl_score'], '15%'),
        ('Volume Breadth', snap_hoy['vol_score'], '20%'),
        ('Concentration', conc['conc_score'], '20%'),
    ]
    cols_sub = st.columns(5)
    for col, (nombre, valor, peso) in zip(cols_sub, subitems):
        color_sub = _bd_color_score(valor)
        with col:
            st.markdown(f"""
            <div style="background:{C_BG1};border:1px solid {C_GRID};border-top:2px solid {color_sub};
                 border-radius:10px;padding:14px;text-align:center">
              <div style="font-size:10px;color:{C_MUTED};text-transform:uppercase">{nombre} ({peso})</div>
              <div style="font-size:22px;font-weight:700;color:{color_sub};margin-top:4px">{valor:.0f}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown('<div style="height:14px"></div>', unsafe_allow_html=True)

    fig_smas = go.Figure()
    vals_sma = [snap_hoy['pct20'], snap_hoy['pct50'], snap_hoy['pct200']]
    fig_smas.add_trace(go.Bar(
        x=['% > SMA20 (30%)', '% > SMA50 (35%)', '% > SMA200 (35%)'], y=vals_sma,
        marker_color=[_bd_color_score(v) for v in vals_sma],
        text=[f'{v:.0f}%' for v in vals_sma], textposition='outside',
    ))
    fig_smas.add_hline(y=50, line_dash='dash', line_color=C_MUTED, opacity=0.5)
    fig_smas.update_layout(
        **PLOTLY_LAYOUT_BASE_BD, height=340,
        yaxis=dict(range=[0, 115], gridcolor=C_GRID, title='% de activos'),
        xaxis=dict(gridcolor=C_GRID),
        title=dict(text='Amplitud de Tendencia (Trend Breadth ponderado)', font=dict(color=C_TEXT, size=13)),
        margin=dict(l=10, r=10, t=45, b=10),
    )
    st.plotly_chart(fig_smas, use_container_width=True, config=PLOTLY_CONFIG, key='bd_fig_smas')

    # ── A/D Line histórica + divergencia (mejora 5) ────────────────────────
    st.markdown('### 📈 A/D Line histórica')
    ret_matrix = df_close.pct_change()
    adv_diaria = (ret_matrix > 0).sum(axis=1)
    dec_diaria = (ret_matrix < 0).sum(axis=1)
    ad_line = (adv_diaria - dec_diaria).cumsum()

    ventana_div = min(21, len(ad_line) - 1)
    ad_line_delta = ad_line.iloc[-1] - ad_line.iloc[-ventana_div - 1] if ventana_div > 0 else 0
    ad_line_dir = 'up' if ad_line_delta > 0 else ('down' if ad_line_delta < 0 else 'flat')
    dir_precio_1m = 'up' if (ret_1m is not None and ret_1m > 0.5) else \
                    'down' if (ret_1m is not None and ret_1m < -0.5) else 'flat'

    if dir_precio_1m == 'up' and ad_line_dir == 'down':
        div_texto, div_color = '⚠️ DIVERGENCIA BAJISTA — el precio sube pero la A/D Line cae', C_RED
    elif dir_precio_1m == 'down' and ad_line_dir == 'up':
        div_texto, div_color = '🟢 DIVERGENCIA ALCISTA — el precio cae pero la A/D Line sube', C_GREEN
    elif ad_line_dir == 'up':
        div_texto, div_color = '↗ A/D Line recuperándose, en línea con el precio', C_LGRE
    elif ad_line_dir == 'down':
        div_texto, div_color = '↘ A/D Line deteriorándose, en línea con el precio', C_LRED
    else:
        div_texto, div_color = '→ A/D Line lateral, sin señal clara', C_MUTED

    fig_ad = go.Figure()
    fig_ad.add_trace(go.Scatter(
        x=ad_line.index, y=ad_line.values, line=dict(color=C_MONSTER, width=2),
        fill='tozeroy', fillcolor='rgba(108,194,74,0.10)', name='A/D Line',
    ))
    fig_ad.update_layout(
        **PLOTLY_LAYOUT_BASE_BD, height=340,
        xaxis=dict(gridcolor=C_GRID), yaxis=dict(gridcolor=C_GRID, title='A/D acumulado'),
        title=dict(text='Advance/Decline Line', font=dict(color=C_TEXT, size=13)),
        margin=dict(l=10, r=10, t=45, b=10),
    )
    st.plotly_chart(fig_ad, use_container_width=True, config=PLOTLY_CONFIG, key='bd_fig_ad')

    st.markdown(f"""
    <div style="background:{C_BG1};border:1px solid {C_GRID};border-left:3px solid {div_color};
         border-radius:8px;padding:10px 14px;margin:-6px 0 16px 0;font-size:12px;color:{C_TEXT}">
      {div_texto}
    </div>
    """, unsafe_allow_html=True)

    if breadth_prev is not None:
        interp_tendencia = (
            'mejorando' if breadth_hoy > breadth_prev + 2 else
            'empeorando' if breadth_hoy < breadth_prev - 2 else
            'estable'
        )
        st.markdown(f"""
        <div style="background:{C_BG1};border:1px solid {C_GRID};border-left:3px solid {C_ACENT};
             border-radius:8px;padding:12px 16px;margin:10px 0;font-size:13px;line-height:1.7;color:#f5f7fa">
          <div style="color:{C_ACENT};font-weight:700;font-size:12px;margin-bottom:4px">📐 LECTURA</div>
          El Breadth Score pasó de {breadth_prev:.0f} a {breadth_hoy:.0f} en el último mes — la
          participación interna del mercado está <b>{interp_tendencia}</b>. Combinado con el estado
          "{estado}", esto {"confirma" if interp_tendencia != "estable" else "no cambia"} la lectura de arriba.
        </div>
        """, unsafe_allow_html=True)

    # ── Mejora 7: New Highs/Lows extendido ─────────────────────────────────
    st.markdown('### 🏔️ Nuevos Máximos / Mínimos (52 sem.)')
    nl_1m = snap_prev['nl'] if snap_prev else None
    delta_nl = (snap_hoy['nl'] - nl_1m) if nl_1m is not None else None
    kpi_cards_4([
        ('New Highs', str(snap_hoy['nh']), 'Últimas 52 semanas', C_GREEN),
        ('New Lows', str(snap_hoy['nl']), 'Últimas 52 semanas', C_RED),
        ('NH - NL', f"{snap_hoy['nhnl_net']:+d}", f"Ratio: {snap_hoy['nhnl_ratio']:.2f}", _bd_color_score(snap_hoy['nhnl_score'])),
        ('Momentum New Lows', f"{delta_nl:+d}" if delta_nl is not None else 'N/D',
         ('🟢 Los nuevos mínimos disminuyen' if (delta_nl is not None and delta_nl < 0) else
          ('🔴 Los nuevos mínimos aumentan' if (delta_nl is not None and delta_nl > 0) else 'Sin cambios vs. 1M')),
         C_GREEN if (delta_nl is not None and delta_nl < 0) else (C_RED if (delta_nl is not None and delta_nl > 0) else C_MUTED)),
    ])

    # ── Mejora 8: Volume Breadth extendido + confirmación ──────────────────
    st.markdown('### 💧 Volume Breadth y Confirmación')
    down_vol_1m = snap_prev['down_vol_pct'] if snap_prev else None
    if ret_1d is not None and ret_1d < 0:
        if down_vol_1m is not None and snap_hoy['down_vol_pct'] > down_vol_1m:
            texto_conf, color_conf = '🔴 Presión vendedora confirmada (down volume en aumento)', C_RED
        else:
            texto_conf, color_conf = '🟡 Caída con menor participación — posible agotamiento vendedor', C_YELL
    elif ret_1d is not None and ret_1d > 0:
        up_vol_1m = (100 - down_vol_1m) if down_vol_1m is not None else None
        if up_vol_1m is not None and snap_hoy['up_vol_pct'] > up_vol_1m:
            texto_conf, color_conf = '🟢 Suba confirmada por volumen (up volume en aumento)', C_GREEN
        else:
            texto_conf, color_conf = '🟡 Suba con menor convicción de volumen', C_YELL
    else:
        texto_conf, color_conf = '⚪ Sin variación relevante de precio para leer el volumen', C_MUTED

    kpi_cards_4([
        ('Up Volume', f"{snap_hoy['up_vol_pct']:.0f}%", 'Del volumen total', C_GREEN),
        ('Down Volume', f"{snap_hoy['down_vol_pct']:.0f}%", 'Del volumen total', C_RED),
        ('Up/Down Volume', f"{snap_hoy['up_down_vol_ratio']:.2f}", 'Ratio', _bd_color_score(snap_hoy['vol_score'])),
        ('Confirmación', '', texto_conf, color_conf),
    ])

    # ── Mejora 9: Concentración y contribución al movimiento ───────────────
    st.markdown('### 🏗️ Concentración y Contribución al Movimiento')
    if conc['top5_tickers'] and ret_1d is not None:
        ret1d_all = snap_hoy['ret_1d_serie']
        top5_tks = [t for t in conc['top5_tickers'] if t in ret1d_all.index]
        pesos_top5 = pesos_full.reindex(top5_tks).fillna(0)
        contrib_top5 = float((pesos_top5 * ret1d_all.reindex(top5_tks).fillna(0)).sum() * 100)
        contrib_total = float((pesos_full * ret1d_all.reindex(pesos_full.index).fillna(0)).sum() * 100)
        contrib_resto = contrib_total - contrib_top5
        concentrada = abs(contrib_top5) > abs(contrib_resto)
        texto_contrib = ('La caída/suba de hoy está altamente concentrada en pocas empresas.' if concentrada
                          else 'El movimiento de hoy está ampliamente distribuido entre el universo.')
    else:
        contrib_top5, contrib_resto, texto_contrib = None, None, 'Datos insuficientes para estimar contribución diaria.'

    kpi_cards_4([
        ('Top 5 (peso)', f"{conc['top5_pct']:.1f}%" if conc['top5_pct'] is not None else 'N/D',
         'Del total del universo', C_YELL),
        ('Resto (peso)', f"{conc['resto_pct']:.1f}%" if conc['resto_pct'] is not None else 'N/D',
         'Del total del universo', C_ACENT),
        ('Contribución Top 5 (1D)', f"{contrib_top5:+.2f}%" if contrib_top5 is not None else 'N/D',
         'Al retorno del índice', C_YELL),
        ('Contribución Resto (1D)', f"{contrib_resto:+.2f}%" if contrib_resto is not None else 'N/D',
         texto_contrib, C_ACENT),
    ])

    # ── Mejora 12: Matriz de diagnóstico ────────────────────────────────────
    st.markdown('### 🧭 Matriz de Diagnóstico (Precio × Breadth)')
    emoji_diag, label_diag, dir_p, dir_b = _bd_matriz_diagnostico(ret_1m, momentum_1m)
    flecha_precio = '↑' if dir_p == 'up' else ('↓' if dir_p == 'down' else '→')
    flecha_breadth = '↑' if dir_b == 'up' else ('↓' if dir_b == 'down' else '→')
    st.markdown(f"""
    <div style="background:{C_BG1};border:1px solid {C_GRID};border-radius:10px;padding:18px;
         display:flex;align-items:center;gap:24px;flex-wrap:wrap">
      <div style="font-size:13px;color:{C_MUTED}">
        Precio (1M): <b style="color:{C_TEXT};font-size:16px">{flecha_precio}</b>
      </div>
      <div style="font-size:13px;color:{C_MUTED}">
        Breadth Momentum: <b style="color:{C_TEXT};font-size:16px">{flecha_breadth}</b>
      </div>
      <div style="font-size:15px;font-weight:700;color:{C_TEXT}">→ {emoji_diag} {label_diag}</div>
    </div>
    """, unsafe_allow_html=True)

    # ── Mejora 13: Detector de divergencias ─────────────────────────────────
    st.markdown('### 🔎 Detección de Divergencias')
    señales = _bd_detectar_divergencias(dir_p, momentum_1m, snap_hoy['ad_score'],
                                          snap_hoy['nh'], (snap_prev['nh'] if snap_prev else None), ad_line_dir)
    for emoji_s, texto_s in señales:
        st.markdown(f"""
        <div style="background:{C_BG1};border:1px solid {C_GRID};border-radius:8px;
             padding:10px 14px;margin-bottom:6px;font-size:13px;color:{C_TEXT}">
          {emoji_s} {texto_s}
        </div>
        """, unsafe_allow_html=True)

    # ── Detalle por activo ───────────────────────────────────────────────
    st.markdown('---')
    st.markdown('### 📋 Detalle por activo')

    last_row = df_close.iloc[-1]
    n_tot = len(df_close)
    sma20_all = df_close.rolling(min(20, n_tot)).mean().iloc[-1]
    sma50_all = df_close.rolling(min(50, n_tot)).mean().iloc[-1] if n_tot >= 10 else sma20_all
    sma200_all = df_close.rolling(min(200, n_tot)).mean().iloc[-1] if n_tot >= 30 else sma50_all
    ret1d_all = ret_matrix.iloc[-1]
    ventana_hl2 = min(252, n_tot)
    max_all = df_close.rolling(ventana_hl2).max().iloc[-1]
    min_all = df_close.rolling(ventana_hl2).min().iloc[-1]

    filas = []
    for tk in df_close.columns:
        peso_tk = float(pesos_full.get(tk, 0)) * 100
        precio_tk = last_row.get(tk)
        r1d = ret1d_all.get(tk)
        filas.append({
            'Ticker': tk,
            'Precio': fmt_precio(precio_tk),
            'Ret 1D %': round(float(r1d) * 100, 2) if pd.notna(r1d) else None,
            '>SMA20': '✅' if pd.notna(precio_tk) and precio_tk > sma20_all.get(tk, np.inf) else '❌',
            '>SMA50': '✅' if pd.notna(precio_tk) and precio_tk > sma50_all.get(tk, np.inf) else '❌',
            '>SMA200': '✅' if pd.notna(precio_tk) and precio_tk > sma200_all.get(tk, np.inf) else '❌',
            'Máx 52s': '🔺' if pd.notna(precio_tk) and precio_tk >= max_all.get(tk, np.inf) else '',
            'Mín 52s': '🔻' if pd.notna(precio_tk) and precio_tk <= min_all.get(tk, -np.inf) else '',
            'Peso %': round(peso_tk, 2) if peso_tk else None,
        })

    df_detalle = pd.DataFrame(filas).sort_values('Ret 1D %', ascending=False, na_position='last')

    def _color_ret1d(val):
        try:
            v = float(val)
            return f'color:{"#3fb950" if v >= 0 else "#f85149"};font-weight:600'
        except Exception:
            return ''

    _map_bd = 'map' if hasattr(df_detalle.style, 'map') else 'applymap'
    styled_detalle = (df_detalle.style
        .pipe(lambda s: getattr(s, _map_bd)(_color_ret1d, subset=['Ret 1D %']))
        .set_properties(**{'background-color': C_BG1, 'color': C_TEXT, 'border': f'1px solid {C_GRID}'})
        .set_table_styles([
            {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', C_TEXT),
                ('font-weight', '700'), ('text-align', 'center'),
                ('border-bottom', f'2px solid {C_ACENT}'), ('font-size', '11px')]},
            {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]},
        ])
    )
    st.dataframe(styled_detalle, use_container_width=True, hide_index=True,
                 height=min(600, max(200, len(df_detalle) * 35 + 45)))

    if chips_navegacion:
        chips_navegacion(df_detalle['Ticker'].tolist(), 'bd_detalle')

    st.caption(
        '⚠️ Al no existir en Yahoo Finance una lista pública de constituyentes reales de un índice, '
        'este módulo usa como "universo de mercado" el grupo de tickers que elegiste arriba (industria '
        'predefinida o lista manual) a modo de proxy representativo. Cuantos más activos incluyas, '
        'más fiel es la lectura de amplitud real del mercado que estás mirando.'
    )
