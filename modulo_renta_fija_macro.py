# ==============================================================
#  MÓDULO RENTA FIJA · SALUD DEL MERCADO · ANÁLISIS MACRO
#  Para Capital+ (Streamlit + yfinance + Plotly)
#
#  Cómo integrarlo en app.py:
#    from modulo_renta_fija_macro import modulo_renta_fija_macro
#    ...
#    elif MODULO == 'renta_fija_macro':
#        modulo_renta_fija_macro(PLOTLY_CONFIG=PLOTLY_CONFIG)
#
#  Y agregar una entrada de navegación (botón / opción de menú) que
#  fije st.session_state['nav_horizonte'] = 'renta_fija_macro' y
#  st.session_state['nav_modulo'] = 'renta_fija_macro'.
#
#  El módulo es autocontenido: define su propia paleta de colores,
#  sus propios diccionarios de tickers y sus propias funciones de
#  descarga/cálculo, así que no depende de nada de app.py.
# ==============================================================

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime

# ==============================================================
#  PALETA DE COLORES (coherente con el resto de Capital+)
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
    dragmode=False,
)

_DEFAULT_PLOTLY_CONFIG = dict(displayModeBar=False, scrollZoom=False)


# ==============================================================
#  1. DICCIONARIO UNIFICADO DE ETFS / BONOS / TASAS
#     Tupla: 'Nombre': ('TICKER', 'Categoría', 'ColorHex')
# ==============================================================

ETFS = {
    # --- Índices & Factores ---
    'EE.UU. S&P500':                 ('SPY',   'Índices', '#3a7bd5'),
    'EE.UU. NASDAQ':                 ('QQQ',   'Índices', '#79c0ff'),
    'EE.UU. DOW':                    ('DIA',   'Índices', '#8b949e'),
    'EE.UU. Russell':                ('IWM',   'Índices', '#bc8cff'),
    'Mid Caps (S&P 400)':            ('IJH',   'Índices', '#9c27b0'),
    'Crecimiento (Growth)':          ('IWF',   'Factores', '#00e676'),
    'Valor (Value)':                 ('IWD',   'Factores', '#ff9100'),
    'Alta Dividendos':               ('VYM',   'Factores', '#ffd700'),
    'Baja Volatilidad':              ('USMV',  'Factores', '#607d8b'),

    # --- Geografías / Global ---
    'Mercados Globales':             ('VT',    'Global', '#00bcd4'),
    'Latinoamérica':                 ('ILF',   'Global', '#4caf50'),
    'Mercados Emerg.':               ('EEM',   'Global', '#8b949e'),
    'Europa general':                ('VGK',   'Global', '#3a7bd5'),
    'Alemania':                      ('EWG',   'Global', '#d2a8ff'),
    'Argentina':                     ('ARGT',  'Global', '#6cb6ff'),
    'Brasil':                        ('EWZ',   'Global', '#3fb950'),
    'Japón':                         ('EWJ',   'Global', '#f0883e'),
    'China':                         ('FXI',   'Global', '#f85149'),
    'Corea del Sur':                 ('EWY',   'Global', '#e3b341'),
    'India':                         ('INDA',  'Global', '#ffa657'),

    # --- Tasas del Tesoro (Yields directos) ---
    'Tasa Tesoro 3 Meses':           ('^IRX',  'Tasas Tesoro', '#00e5ff'),
    'Tasa Tesoro 5 Años':            ('^FVX',  'Tasas Tesoro', '#00b0ff'),
    'Tasa Tesoro 10 Años (Bench)':   ('^TNX',  'Tasas Tesoro', '#2979ff'),
    'Tasa Tesoro 30 Años':           ('^TYX',  'Tasas Tesoro', '#3d5aff'),

    # --- Bonos Soberanos EE.UU. ---
    'Bonos Tesoro Corto (1-3y)':     ('SHY',   'Bonos EE.UU.', '#80deea'),
    'Bonos Tesoro Medio (7-10y)':    ('IEF',   'Bonos EE.UU.', '#26c6da'),
    'Bonos Tesoro Largo (20y+)':     ('TLT',   'Bonos EE.UU.', '#00838f'),
    'Bonos Inflación (TIPS)':       ('TIP',   'Bonos EE.UU.', '#ab47bc'),

    # --- Crédito Corporativo EE.UU. ---
    'Bonos Corp. Corto Plazo IG':    ('VCSH',  'Crédito Corporativo', '#b388ff'),
    'Bonos Corporativos IG':         ('LQD',   'Crédito Corporativo', '#7e57c2'),
    'Bonos Alto Rendimiento (Junk)': ('HYG',   'Crédito Corporativo', '#ff7043'),
    'Bonos Junk SPDR':               ('JNK',   'Crédito Corporativo', '#f4511e'),

    # --- Renta Fija Global y Emergentes ---
    'Deuda Emergente USD (iShares)':  ('EMB',   'Renta Fija Global', '#ff9800'),
    'Deuda Emergente USD (Vanguard)': ('VWOB',  'Renta Fija Global', '#fb8c00'),
    'Deuda Emergente Moneda Local':   ('EMLC',  'Renta Fija Global', '#e65100'),
    'Corporativos Emergentes USD':    ('CEMB',  'Renta Fija Global', '#d81b60'),
    'Deuda Desarrollada ex-US':       ('BNDX',  'Renta Fija Global', '#03a9f4'),
    'Soberanos Desarrollados ex-US':  ('IGOV',  'Renta Fija Global', '#0288d1'),
}

# Orden de las 5 subcategorías pedidas para las tarjetas KPI de Renta Fija
CATEGORIAS_RENTA_FIJA_ORDEN = [
    'Tasas Tesoro', 'Bonos EE.UU.', 'Crédito Corporativo',
    'Renta Fija Global', 'Índices',  # "Factores/Índices" -> agrupamos Índices y Factores
]

# --- Factores adicionales para los ratios avanzados (no están en ETFS) ---
FACTORES_AVANZADOS = {
    'VIX 30 días':                ('^VIX',  'Volatilidad', '#f85149'),
    'VIX 9 días':                 ('^VIX9D','Volatilidad', '#ffa657'),
    'Alta Beta (SPHB)':           ('SPHB',  'Liquidez/Apalancamiento', '#bc8cff'),
    'Baja Volatilidad (SPLV)':    ('SPLV',  'Liquidez/Apalancamiento', '#79c0ff'),
    'Consumo Discrecional (XLY)': ('XLY',   'Rotación Sectorial', '#f0883e'),
    'Consumo Básico (XLP)':       ('XLP',   'Rotación Sectorial', '#bc8cff'),
    'Industriales (XLI)':         ('XLI',   'Rotación Sectorial', '#79c0ff'),
    'Utilities (XLU)':            ('XLU',   'Rotación Sectorial', '#3fb950'),
    'ARK Innovation (ARKK)':      ('ARKK',  'Rotación Sectorial', '#d2a8ff'),
    'Cobre (CPER)':               ('CPER',  'Macro Valuación', '#cd7f32'),
    'Oro (GLD)':                  ('GLD',   'Macro Valuación', '#e3b341'),
    'Energía (XLE)':              ('XLE',   'Macro Valuación', '#ffa657'),
}

# Tickers cuyo valor de Yahoo viene multiplicado x10 (representan % de yield)
_TICKERS_TASA_X10 = {'^IRX', '^FVX', '^TNX', '^TYX'}


# ==============================================================
#  2. DESCARGA UNIFICADA DE PRECIOS
# ==============================================================

@st.cache_data(ttl=300, show_spinner=False)
def cargar_precios_renta_fija_macro():
    """Descarga 1 año de precios diarios para todos los ETFs de renta fija/macro
    y los factores avanzados, en una sola llamada a yfinance. auto_adjust=False
    para no perder la columna 'Close' en tickers de índice (los que empiezan con ^)."""
    try:
        import yfinance as yf
    except Exception:
        return None, {}

    tks_etfs = [v[0] for v in ETFS.values()]
    tks_fact = [v[0] for v in FACTORES_AVANZADOS.values()]
    todos = sorted(set(tks_etfs + tks_fact))

    try:
        df = yf.download(
            todos, period='1y', interval='1d',
            auto_adjust=False, progress=False, group_by='ticker',
        )
    except Exception:
        return None, {}

    if df is None or df.empty:
        return None, {}

    # Armamos un DataFrame ancho: columnas = ticker, valores = precio de cierre
    precios = pd.DataFrame(index=df.index)
    fallidos = []
    for tk in todos:
        serie = _extraer_close(df, tk)
        if serie is not None and len(serie.dropna()) >= 2:
            precios[tk] = serie
        else:
            fallidos.append(tk)

    precios = precios.sort_index().ffill()
    meta = {'fallidos': fallidos, 'ts': datetime.now()}
    return precios, meta


def _extraer_close(df, ticker):
    """Extrae la serie de cierre de un ticker desde un DataFrame descargado en
    bulk con group_by='ticker' (soporta MultiIndex en ambos órdenes y el caso
    de un solo ticker sin MultiIndex)."""
    try:
        if isinstance(df.columns, pd.MultiIndex):
            if (ticker, 'Close') in df.columns:
                return df[(ticker, 'Close')].astype(float)
            if ('Close', ticker) in df.columns:
                return df[('Close', ticker)].astype(float)
            return None
        # Un solo ticker: columnas planas
        if 'Close' in df.columns:
            return df['Close'].astype(float)
        return None
    except Exception:
        return None


def _ultimo_y_variacion(serie):
    """Devuelve (último valor, variación % vs. la rueda anterior)."""
    s = pd.Series(serie).dropna()
    if len(s) < 2:
        return None, None
    ultimo = float(s.iloc[-1])
    previo = float(s.iloc[-2])
    var_pct = (ultimo / previo - 1) * 100 if previo else None
    return ultimo, var_pct


def fmt_precio_rf(p):
    if p is None:
        return 'S/D'
    if abs(p) >= 1000:
        return f'{p:,.1f}'
    if abs(p) >= 10:
        return f'{p:.2f}'
    return f'{p:.4f}'


def _tasa(precios, ticker):
    """Devuelve la serie de una tasa del Tesoro ya convertida a % real
    (Yahoo cotiza ^IRX/^FVX/^TNX/^TYX multiplicados x10)."""
    if ticker not in precios.columns:
        return None
    s = precios[ticker].dropna()
    if ticker in _TICKERS_TASA_X10:
        s = s / 10.0
    return s


# ==============================================================
#  3. MATRIZ DE RATIOS ESTRATÉGICOS (12 ratios + avanzados)
# ==============================================================

def calcular_matriz_ratios_macro(precios):
    """Procesa los 12 ratios estratégicos + los ratios avanzados de
    volatilidad, liquidez, rotación sectorial y valuación macro.
    Devuelve un DataFrame (índice = fecha) con una columna por ratio."""
    if precios is None or precios.empty:
        return pd.DataFrame()

    def r(num, den):
        if num not in precios.columns or den not in precios.columns:
            return None
        a = precios[num].dropna()
        b = precios[den].dropna()
        idx = a.index.intersection(b.index)
        if len(idx) < 5:
            return None
        return (a.loc[idx] / b.loc[idx]).rename(f'{num}/{den}')

    ratios = {}

    # ── Los 12 ratios estratégicos originales ──────────────────────────
    ratios['Apetito Riesgo Crediticio (HYG/IEF)']   = r('HYG', 'IEF')
    ratios['Riesgo de Crédito Puro (HYG/LQD)']      = r('HYG', 'LQD')
    ratios['Liquidez Corporativa (VCSH/LQD)']       = r('VCSH', 'LQD')

    irx = _tasa(precios, '^IRX'); tnx = _tasa(precios, '^TNX'); tyx = _tasa(precios, '^TYX')
    if irx is not None and tnx is not None:
        idx = irx.index.intersection(tnx.index)
        if len(idx) > 5:
            ratios['Spread Curva 10Y-3M (TNX-IRX)'] = (tnx.loc[idx] - irx.loc[idx])
    if tyx is not None and tnx is not None:
        idx = tyx.index.intersection(tnx.index)
        if len(idx) > 5:
            ratios['Spread Curva Larga (TYX-TNX)'] = (tyx.loc[idx] - tnx.loc[idx])

    ratios['Sensibilidad a Tasas / Duration (TLT/SHY)']    = r('TLT', 'SHY')
    ratios['Expectativa Inflacionaria (TIP/IEF)']          = r('TIP', 'IEF')
    ratios['Estrés Monetario Emergente (EMLC/EMB)']        = r('EMLC', 'EMB')
    ratios['Flujo Global (EEM/VT)']                        = r('EEM', 'VT')
    ratios['Rotación Crecimiento vs Refugio (SPY/TLT)']    = r('SPY', 'TLT')
    ratios['Liderazgo Tecnológico (QQQ/SPY)']              = r('QQQ', 'SPY')
    ratios['Estilos de Inversión (IWF/IWD)']               = r('IWF', 'IWD')

    # ── Ratios avanzados: Volatilidad y Miedo Institucional ─────────────
    vix = precios['^VIX'].dropna() if '^VIX' in precios.columns else None
    vix9d = precios['^VIX9D'].dropna() if '^VIX9D' in precios.columns else None
    if vix is not None and vix9d is not None:
        idx = vix.index.intersection(vix9d.index)
        if len(idx) > 5:
            ratios['Estrés Volatilidad Táctica (VIX/VIX9D)'] = (vix.loc[idx] / vix9d.loc[idx])

    if 'HYG' in precios.columns and vix is not None:
        hyg_ret = precios['HYG'].pct_change()
        hyg_vol = (hyg_ret.rolling(20).std() * np.sqrt(252) * 100).dropna()
        idx = hyg_vol.index.intersection(vix.index)
        if len(idx) > 5:
            ratios['Miedo Crediticio vs Accionario (HYG_Vol/VIX)'] = (hyg_vol.loc[idx] / vix.loc[idx])

    # ── Ratios avanzados: Liquidez y Apalancamiento Sistémico ───────────
    ratios['Apetito Apalancamiento (SPHB/SPLV)'] = r('SPHB', 'SPLV')

    # ── Ratios avanzados: Rotación Sectorial Profunda ───────────────────
    ratios['Sensibilidad al Consumo (XLY/XLP)']        = r('XLY', 'XLP')
    ratios['Salud Economía Real (XLI/XLU)']            = r('XLI', 'XLU')
    ratios['Apetito Innovación/Especulación (ARKK/QQQ)'] = r('ARKK', 'QQQ')

    # ── Ratios avanzados: Valuación Macro y Commodities ────────────────
    ratios['Cobre/Oro — Doctor Copper (CPER/GLD)'] = r('CPER', 'GLD')
    ratios['Energía vs Mercado (XLE/SPY)']         = r('XLE', 'SPY')

    df_out = pd.concat({k: v for k, v in ratios.items() if v is not None}, axis=1)
    return df_out.sort_index()


# ==============================================================
#  4. GLOSARIO — explicaciones de alto nivel, fáciles de entender
# ==============================================================

GLOSARIO_RATIOS = {
    'Apetito Riesgo Crediticio (HYG/IEF)':
        'Compara bonos "basura" de alto rendimiento (HYG) contra bonos del Tesoro '
        'de mediano plazo (IEF). Cuando sube, el mercado tiene apetito por el riesgo '
        '("Risk-On"); cuando cae, los inversores buscan refugio ("Risk-Off").',
    'Riesgo de Crédito Puro (HYG/LQD)':
        'Mide el estrés específico del crédito de menor calidad (HYG) frente a '
        'empresas sólidas con grado de inversión (LQD). Si cae con fuerza, es señal '
        'de que el mercado le empieza a temer a un default corporativo.',
    'Liquidez Corporativa (VCSH/LQD)':
        'Compara el costo de financiamiento corporativo a corto plazo (VCSH) contra '
        'el de largo plazo (LQD). Ayuda a ver si las empresas están teniendo más o '
        'menos facilidad para financiarse en el corto plazo.',
    'Spread Curva 10Y-3M (TNX-IRX)':
        'La diferencia entre la tasa a 10 años y la tasa a 3 meses del Tesoro de EE.UU. '
        'Cuando este número se vuelve negativo (la curva se "invierte"), ha sido, '
        'históricamente, una de las señales de recesión más confiables.',
    'Spread Curva Larga (TYX-TNX)':
        'La prima extra que exige el mercado por prestar a 30 años en vez de a 10 años. '
        'Si esta prima se achica o se vuelve negativa, sugiere expectativas de menor '
        'crecimiento o inflación en el largo plazo.',
    'Sensibilidad a Tasas / Duration (TLT/SHY)':
        'Compara bonos largos (TLT, muy sensibles a cambios de tasas) contra bonos '
        'cortos (SHY, casi insensibles). Si sube, el mercado está apostando a que las '
        'tasas de la Fed van a bajar; si cae, a que van a subir o mantenerse altas.',
    'Expectativa Inflacionaria (TIP/IEF)':
        'TIP son bonos protegidos contra la inflación; IEF son bonos tradicionales. '
        'Cuando el ratio sube, el mercado empieza a temerle más a la inflación futura.',
    'Estrés Monetario Emergente (EMLC/EMB)':
        'Compara deuda emergente en moneda local (EMLC) contra deuda emergente en '
        'dólares (EMB). Si cae, sugiere que el mercado teme más una devaluación de '
        'las monedas emergentes que un default en dólares.',
    'Flujo Global (EEM/VT)':
        'Mide si el dinero global fluye hacia mercados emergentes (EEM) o se queda '
        'en el promedio del mercado mundial (VT, que incluye desarrollados).',
    'Rotación Crecimiento vs Refugio (SPY/TLT)':
        'Compara acciones (SPY) contra bonos del Tesoro largo (TLT), el activo '
        'refugio por excelencia. Si sube, hay apetito por el riesgo; si cae, los '
        'inversores buscan protección.',
    'Liderazgo Tecnológico (QQQ/SPY)':
        'Mide si el Nasdaq (dominado por tecnología) le está ganando o perdiendo al '
        'mercado general. Un ratio en alza indica que las mega-tecnológicas están '
        'concentrando el liderazgo del rally.',
    'Estilos de Inversión (IWF/IWD)':
        'Compara acciones de "crecimiento" (Growth, IWF) contra acciones de "valor" '
        '(Value, IWD). Ayuda a identificar qué estilo está liderando el ciclo actual.',
    'Estrés Volatilidad Táctica (VIX/VIX9D)':
        'Compara el VIX tradicional (30 días) contra el VIX de 9 días. Cuando el '
        'ratio cae por debajo de 1, significa que el mercado le está poniendo más '
        'miedo al muy corto plazo que al mediano plazo — señal de pánico inminente.',
    'Miedo Crediticio vs Accionario (HYG_Vol/VIX)':
        'Compara qué tan nerviosos están los bonos basura (HYG) frente a qué tan '
        'nervioso está el mercado accionario (VIX). Si la volatilidad de los bonos '
        'se dispara más rápido que la de las acciones, el crédito puede estar '
        'anticipando un problema de liquidez que las acciones todavía no reflejan.',
    'Apetito Apalancamiento (SPHB/SPLV)':
        'Compara acciones de alta volatilidad/beta (SPHB) contra acciones defensivas '
        'de baja volatilidad (SPLV). Si cae con fuerza, el capital institucional está '
        'rotando hacia posiciones más defensivas ("Risk-Off").',
    'Sensibilidad al Consumo (XLY/XLP)':
        'El "termómetro del consumidor": Consumo Discrecional (autos, viajes, lujo) '
        'contra Consumo Básico (alimentos, higiene). Si sube, el consumidor gasta con '
        'confianza; si cae, el dinero busca refugio en lo esencial.',
    'Salud Economía Real (XLI/XLU)':
        'Compara Industriales (fábricas, maquinaria) contra Utilities (servicios '
        'públicos, muy defensivos). Si sube, la economía real se está expandiendo; '
        'si cae, el dinero huye hacia lo más seguro.',
    'Apetito Innovación/Especulación (ARKK/QQQ)':
        'Compara empresas tecnológicas especulativas y sin ganancias consolidadas '
        '(ARKK) contra las mega-tecnológicas más sólidas del Nasdaq (QQQ). Si sube, '
        'hay apetito especulativo real, no solo un rally de las grandes empresas.',
    'Cobre/Oro — Doctor Copper (CPER/GLD)':
        'El cobre refleja actividad industrial y crecimiento; el oro refleja refugio '
        'e inflación. Si el ratio sube, anticipa crecimiento económico (y presión '
        'sobre las tasas); si cae, anticipa desaceleración o mayor aversión al riesgo.',
    'Energía vs Mercado (XLE/SPY)':
        'Si el sector Energía empieza a subir más que el mercado en general, suele '
        'anticipar presiones inflacionarias por el lado de los costos de insumos.',
}


# ==============================================================
#  5. MOTOR DE REGLAS — ALERTAS AUTOMÁTICAS
# ==============================================================

def generar_alertas_macro(precios, df_ratios):
    """Evalúa las 3 reglas de diagnóstico automático sobre el estado del
    mercado y devuelve una lista de alertas: [{'nivel','icono','titulo','texto'}]."""
    alertas = []
    if precios is None or precios.empty or df_ratios is None or df_ratios.empty:
        return alertas

    col_hyg_ief = 'Apetito Riesgo Crediticio (HYG/IEF)'
    col_spread = 'Spread Curva 10Y-3M (TNX-IRX)'
    col_spy_tlt = 'Rotación Crecimiento vs Refugio (SPY/TLT)'

    # ── Regla 1: Divergencia Bajista de Crédito ─────────────────────────
    try:
        if 'SPY' in precios.columns and col_hyg_ief in df_ratios.columns:
            spy = precios['SPY'].dropna()
            spy_sube_5d = len(spy) > 5 and float(spy.iloc[-1]) > float(spy.iloc[-6])
            hyg_ief = df_ratios[col_hyg_ief].dropna()
            sma20 = hyg_ief.rolling(20).mean()
            if len(hyg_ief) > 20 and spy_sube_5d and float(hyg_ief.iloc[-1]) < float(sma20.iloc[-1]):
                alertas.append(dict(
                    nivel='alto', icono='🔴', titulo='Divergencia de Crédito Detectada',
                    texto='Las acciones suben en los últimos 5 días, pero el ratio HYG/IEF '
                          'cayó por debajo de su media móvil de 20 días: las acciones suben '
                          'sin respaldo del mercado de bonos corporativos. Riesgo alto de corrección.',
                ))
    except Exception:
        pass

    # ── Regla 2: Inversión/Des-inversión de Curva ───────────────────────
    try:
        if col_spread in df_ratios.columns:
            spread = df_ratios[col_spread].dropna()
            if len(spread) > 0 and float(spread.iloc[-1]) < 0:
                alertas.append(dict(
                    nivel='alto', icono='🚨', titulo='Alerta Macro: Curva de Rendimientos Invertida',
                    texto=f'El spread 10Y-3M está en {float(spread.iloc[-1]):+.2f} puntos — '
                          'territorio negativo. Señal histórica de recesión económica.',
                ))
    except Exception:
        pass

    # ── Regla 3: Apetito por Riesgo Total (Risk-On) ─────────────────────
    try:
        if col_hyg_ief in df_ratios.columns and col_spy_tlt in df_ratios.columns:
            hyg_ief = df_ratios[col_hyg_ief].dropna()
            sma20_h = hyg_ief.rolling(20).mean()
            spy_tlt = df_ratios[col_spy_tlt].dropna()
            max20 = spy_tlt.rolling(20).max()
            cond_credito = len(hyg_ief) > 20 and float(hyg_ief.iloc[-1]) > float(sma20_h.iloc[-1])
            cond_accion = len(spy_tlt) > 20 and float(spy_tlt.iloc[-1]) >= float(max20.iloc[-1])
            if cond_credito and cond_accion:
                alertas.append(dict(
                    nivel='positivo', icono='🟢', titulo='Régimen Risk-On',
                    texto='Confianza plena en el crédito corporativo y la renta variable: '
                          'HYG/IEF por encima de su media de 20 días y SPY/TLT en máximos '
                          'de 20 días.',
                ))
    except Exception:
        pass

    return alertas


# ==============================================================
#  6. FUNCIONES DE GRÁFICOS
# ==============================================================

def _fig_serie_simple(nombre, serie, sma_ventana=None, hline_cero=False, formato_pct=False):
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=serie.index, y=serie.values, line=dict(color=C_ACENT, width=2.0), name=nombre,
    ))
    if sma_ventana:
        sma = serie.rolling(sma_ventana).mean()
        fig.add_trace(go.Scatter(
            x=sma.index, y=sma.values, line=dict(color=C_YELL, width=1.3, dash='dash'),
            name=f'SMA {sma_ventana}',
        ))
    if hline_cero:
        fig.add_hline(y=0, line_color=C_MUTED, opacity=0.5, line_dash='dot')
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE,
        title=dict(text=nombre, font=dict(color=C_TEXT, size=13), x=0.01),
        xaxis=dict(gridcolor=C_GRID), yaxis=dict(gridcolor=C_GRID),
        height=320, margin=dict(l=10, r=10, t=45, b=10), hovermode='x unified',
        legend=dict(orientation='h', y=1.15, font=dict(size=9)),
    )
    return fig


def _fig_base100(series_dict, titulo='Comparativa Base 100'):
    fig = go.Figure()
    palette = [C_MONSTER, C_ACENT, C_LRED, '#bc8cff', C_YELL, C_LGRE]
    for i, (nombre, serie) in enumerate(series_dict.items()):
        s = serie.dropna()
        if len(s) == 0:
            continue
        rebased = s / float(s.iloc[0]) * 100
        fig.add_trace(go.Scatter(
            x=rebased.index, y=rebased.values, name=nombre,
            line=dict(color=palette[i % len(palette)], width=2.0),
        ))
    fig.add_hline(y=100, line_dash='dot', line_color=C_MUTED, opacity=0.4)
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE,
        title=dict(text=titulo, font=dict(color=C_TEXT, size=14)),
        xaxis=dict(gridcolor=C_GRID), yaxis=dict(gridcolor=C_GRID, title='Índice (base 100)'),
        height=440, hovermode='x unified',
        legend=dict(orientation='h', y=1.1),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    return fig


# ==============================================================
#  7. COMPONENTES VISUALES
# ==============================================================

def _tarjeta_interp(titulo, texto, color=C_ACENT):
    st.markdown(f"""
    <div style="background:{C_BG1};border:1px solid {C_GRID};border-left:3px solid {color};
         border-radius:8px;padding:12px 16px;margin-bottom:10px;font-size:13px;
         line-height:1.7;color:#f5f7fa">
      <div style="color:{color};font-weight:700;font-size:12px;margin-bottom:6px;
           font-family:'JetBrains Mono',monospace">{titulo}</div>
      {texto}
    </div>
    """, unsafe_allow_html=True)


def _kpi_card(label, value, sub, color, tooltip=''):
    tip = (tooltip or '').replace('"', "'")
    marca = ' ⓘ' if tip else ''
    st.markdown(f"""
    <div title="{tip}" style="background:{C_BG1};border:1px solid {C_GRID};border-radius:10px;
         padding:14px 16px;position:relative;overflow:hidden;cursor:help">
      <div style="position:absolute;top:0;left:0;width:100%;height:2px;background:{color}"></div>
      <div style="color:#f5f7fa;font-size:11px;font-weight:700;text-transform:uppercase;
           letter-spacing:1px;margin-bottom:6px">{label}{marca}</div>
      <div style="color:{C_TEXT};font-size:19px;font-weight:700;letter-spacing:-0.4px;
           font-family:'JetBrains Mono',monospace">{value}</div>
      <div style="color:#f5f7fa;font-size:12px;margin-top:4px">{sub}</div>
    </div>
    """, unsafe_allow_html=True)


def _fila_kpis(items):
    """items: lista de (label, value, sub, color, tooltip_opcional)."""
    cols = st.columns(len(items))
    for col, item in zip(cols, items):
        label, value, sub, color = item[0], item[1], item[2], item[3]
        tooltip = item[4] if len(item) > 4 else ''
        with col:
            _kpi_card(label, value, sub, color, tooltip)
    st.markdown('<div style="height:6px"></div>', unsafe_allow_html=True)


def _render_alertas(alertas):
    if not alertas:
        st.markdown("""
        <div style="background:rgba(63,185,80,0.08);border:1px solid rgba(63,185,80,0.3);
             border-radius:10px;padding:14px 18px;margin-bottom:16px;color:#7ee787;font-size:13px">
          ✅ Sin alertas activas por el momento — el motor de reglas no detectó ninguna de las
          3 condiciones de divergencia, inversión de curva o régimen Risk-On extremo.
        </div>
        """, unsafe_allow_html=True)
        return
    for a in alertas:
        color_map = {'alto': C_RED, 'positivo': C_GREEN, 'medio': C_YELL}
        color = color_map.get(a['nivel'], C_ACENT)
        bg = f'rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.08)'
        st.markdown(f"""
        <div style="background:{bg};border:1px solid {color};border-radius:10px;
             padding:14px 18px;margin-bottom:10px">
          <div style="font-size:14px;font-weight:700;color:{color};margin-bottom:4px">
            {a['icono']} {a['titulo']}
          </div>
          <div style="font-size:12.5px;color:#f5f7fa;line-height:1.6">{a['texto']}</div>
        </div>
        """, unsafe_allow_html=True)


def _tarjetas_categoria_bonos(precios, categoria, items):
    st.markdown(
        f'<div style="font-size:11px;font-weight:700;color:#f5f7fa;text-transform:uppercase;'
        f'letter-spacing:.8px;margin:14px 0 8px 0;border-bottom:1px solid {C_GRID};padding-bottom:6px">'
        f'◆ {categoria}</div>', unsafe_allow_html=True,
    )
    n_cols = min(4, len(items)) or 1
    filas = [items[i:i + n_cols] for i in range(0, len(items), n_cols)]
    for fila in filas:
        cols = st.columns(n_cols)
        for col, (nombre, tk, color) in zip(cols, fila):
            ultimo, var_pct = _ultimo_y_variacion(precios[tk]) if tk in precios.columns else (None, None)
            with col:
                if ultimo is None:
                    _kpi_card(nombre, 'S/D', tk, '#3a4a5f')
                else:
                    signo_color = C_GREEN if (var_pct or 0) >= 0 else C_RED
                    flecha = '▲' if (var_pct or 0) >= 0 else '▼'
                    sub = f'<span style="color:{signo_color};font-weight:700">{flecha} {abs(var_pct or 0):.2f}%</span> · {tk}'
                    _kpi_card(nombre, fmt_precio_rf(ultimo), sub, color)


# ==============================================================
#  8. RENDER DE CADA SECCIÓN / TAB
# ==============================================================

def _tab_renta_fija(precios):
    st.markdown("""
    <div class="rf-info-banner">
      Tarjetas de las 5 subcategorías de Renta Fija y Tasas: precio (o nivel, en el
      caso de las tasas) y variación diaria.
    </div>
    """, unsafe_allow_html=True)

    categorias = {}
    for nombre, (tk, cat, color) in ETFS.items():
        cat_agrupada = 'Índices' if cat in ('Índices', 'Factores') else cat
        categorias.setdefault(cat_agrupada, []).append((nombre, tk, color))

    for cat in CATEGORIAS_RENTA_FIJA_ORDEN:
        items = categorias.get(cat, [])
        if items:
            _tarjetas_categoria_bonos(precios, cat, items)


def _tab_salud_mercado(precios, df_ratios):
    st.markdown("""
    <div class="rf-info-banner">
      Panel de <b>salud del mercado</b>: el ratio HYG/IEF (apetito por riesgo crediticio),
      el spread de la curva 10Y-3M, y una comparación normalizada en Base 100 contra el S&amp;P 500.
    </div>
    """, unsafe_allow_html=True)

    col_hyg = 'Apetito Riesgo Crediticio (HYG/IEF)'
    col_spread = 'Spread Curva 10Y-3M (TNX-IRX)'

    kpis = []
    if col_hyg in df_ratios.columns:
        s = df_ratios[col_hyg].dropna()
        sma20 = s.rolling(20).mean()
        val = float(s.iloc[-1]) if len(s) else None
        sma_val = float(sma20.iloc[-1]) if len(sma20.dropna()) else None
        estado = 'Risk-On' if (val and sma_val and val > sma_val) else 'Risk-Off'
        col_est = C_GREEN if estado == 'Risk-On' else C_RED
        kpis.append(('HYG / IEF', f'{val:.3f}' if val else 'S/D',
                     f'<span style="color:{col_est};font-weight:700">{estado}</span> vs SMA20',
                     C_ACENT, GLOSARIO_RATIOS.get(col_hyg, '')))
    if col_spread in df_ratios.columns:
        s = df_ratios[col_spread].dropna()
        val = float(s.iloc[-1]) if len(s) else None
        estado_c = 'Invertida ⚠️' if (val is not None and val < 0) else 'Normal'
        col_est_c = C_RED if (val is not None and val < 0) else C_GREEN
        kpis.append(('Spread 10Y-3M', f'{val:+.2f} pp' if val is not None else 'S/D',
                     f'<span style="color:{col_est_c};font-weight:700">{estado_c}</span>',
                     C_YELL, GLOSARIO_RATIOS.get(col_spread, '')))
    if 'SPY' in precios.columns:
        ultimo, var = _ultimo_y_variacion(precios['SPY'])
        col_v = C_GREEN if (var or 0) >= 0 else C_RED
        kpis.append(('S&P 500 (SPY)', fmt_precio_rf(ultimo),
                     f'<span style="color:{col_v};font-weight:700">{var:+.2f}%</span> hoy' if var is not None else '',
                     C_MONSTER))
    if 'TLT' in precios.columns:
        ultimo, var = _ultimo_y_variacion(precios['TLT'])
        col_v = C_GREEN if (var or 0) >= 0 else C_RED
        kpis.append(('Bonos Largo (TLT)', fmt_precio_rf(ultimo),
                     f'<span style="color:{col_v};font-weight:700">{var:+.2f}%</span> hoy' if var is not None else '',
                     '#00838f'))

    if kpis:
        _fila_kpis(kpis)

    c1, c2 = st.columns(2)
    with c1:
        if col_hyg in df_ratios.columns:
            fig = _fig_serie_simple(col_hyg, df_ratios[col_hyg].dropna(), sma_ventana=20)
            st.plotly_chart(fig, use_container_width=True, config=_DEFAULT_PLOTLY_CONFIG, key='rf_fig_hyg_ief')
            _tarjeta_interp('¿Qué significa?', GLOSARIO_RATIOS.get(col_hyg, ''), C_ACENT)
    with c2:
        if col_spread in df_ratios.columns:
            fig = _fig_serie_simple(col_spread, df_ratios[col_spread].dropna(), hline_cero=True)
            st.plotly_chart(fig, use_container_width=True, config=_DEFAULT_PLOTLY_CONFIG, key='rf_fig_spread')
            _tarjeta_interp('¿Qué significa?', GLOSARIO_RATIOS.get(col_spread, ''), C_YELL)

    st.markdown('### 📐 Comparativa normalizada (Base 100) vs S&P 500')
    series_b100 = {}
    for nombre_corto, tk in [('S&P 500', 'SPY'), ('Bonos Largo (TLT)', 'TLT'),
                              ('Crédito HY (HYG)', 'HYG'), ('Bonos 7-10y (IEF)', 'IEF')]:
        if tk in precios.columns:
            series_b100[nombre_corto] = precios[tk]
    if series_b100:
        st.plotly_chart(_fig_base100(series_b100, 'S&P 500 vs. Renta Fija — Base 100'),
                         use_container_width=True, config=_DEFAULT_PLOTLY_CONFIG, key='rf_fig_base100')


def _tab_matriz_ratios(df_ratios):
    st.markdown("""
    <div class="rf-info-banner">
      Los <b>12 ratios estratégicos</b> que arma el módulo, con su último valor y una
      explicación de qué mide cada uno, en lenguaje simple.
    </div>
    """, unsafe_allow_html=True)

    orden_12 = [
        'Apetito Riesgo Crediticio (HYG/IEF)', 'Riesgo de Crédito Puro (HYG/LQD)',
        'Liquidez Corporativa (VCSH/LQD)', 'Spread Curva 10Y-3M (TNX-IRX)',
        'Spread Curva Larga (TYX-TNX)', 'Sensibilidad a Tasas / Duration (TLT/SHY)',
        'Expectativa Inflacionaria (TIP/IEF)', 'Estrés Monetario Emergente (EMLC/EMB)',
        'Flujo Global (EEM/VT)', 'Rotación Crecimiento vs Refugio (SPY/TLT)',
        'Liderazgo Tecnológico (QQQ/SPY)', 'Estilos de Inversión (IWF/IWD)',
    ]

    filas = []
    for nombre in orden_12:
        if nombre not in df_ratios.columns:
            continue
        s = df_ratios[nombre].dropna()
        if s.empty:
            continue
        ultimo = float(s.iloc[-1])
        var_5d = None
        if len(s) > 5:
            prev = float(s.iloc[-6])
            var_5d = (ultimo / prev - 1) * 100 if prev else None
        filas.append({
            'Ratio': nombre, 'Último valor': round(ultimo, 4),
            'Var. 5 ruedas %': round(var_5d, 2) if var_5d is not None else None,
        })

    if filas:
        df_tabla = pd.DataFrame(filas)

        def _color_var(val):
            try:
                v = float(val)
                return f'color:{"#3fb950" if v >= 0 else "#f85149"};font-weight:700'
            except Exception:
                return ''

        _map = 'map' if hasattr(df_tabla.style, 'map') else 'applymap'
        styled = (df_tabla.style
                  .pipe(lambda s: getattr(s, _map)(_color_var, subset=['Var. 5 ruedas %']))
                  .set_properties(**{'background-color': C_BG1, 'color': C_TEXT, 'border': f'1px solid {C_GRID}'})
                  .set_table_styles([
                      {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', C_TEXT),
                          ('font-weight', '700'), ('text-align', 'center'),
                          ('border-bottom', f'2px solid {C_ACENT}'), ('font-size', '11px')]},
                      {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11.5px')]},
                  ]))
        st.dataframe(styled, use_container_width=True, hide_index=True,
                     height=min(500, len(df_tabla) * 40 + 45))
    else:
        st.info('No se pudieron calcular los ratios (datos insuficientes).')

    st.markdown('### 📈 Ver un ratio en detalle')
    disponibles = [n for n in orden_12 if n in df_ratios.columns and not df_ratios[n].dropna().empty]
    if disponibles:
        sel = st.selectbox('Elegí un ratio', disponibles, key='rf_ratio_detalle_sel')
        fig = _fig_serie_simple(sel, df_ratios[sel].dropna(), sma_ventana=20)
        st.plotly_chart(fig, use_container_width=True, config=_DEFAULT_PLOTLY_CONFIG, key='rf_fig_detalle')
        _tarjeta_interp('¿Qué significa este ratio?', GLOSARIO_RATIOS.get(sel, 'Sin descripción.'), C_ACENT)


def _tab_grupo_avanzado(df_ratios, ratios_grupo, titulo_grupo, color_grupo):
    """Renderiza un grupo de ratios avanzados (volatilidad, liquidez, rotación,
    valuación macro) con su gráfico y su interpretación de alto nivel."""
    disponibles = [n for n in ratios_grupo if n in df_ratios.columns and not df_ratios[n].dropna().empty]
    if not disponibles:
        st.info(f'No hay datos suficientes para calcular los ratios de "{titulo_grupo}".')
        return

    for nombre in disponibles:
        s = df_ratios[nombre].dropna()
        c1, c2 = st.columns([2, 1])
        with c1:
            fig = _fig_serie_simple(nombre, s, sma_ventana=20)
            st.plotly_chart(fig, use_container_width=True, config=_DEFAULT_PLOTLY_CONFIG,
                             key=f'rf_fig_{nombre}')
        with c2:
            ultimo = float(s.iloc[-1])
            sma20 = s.rolling(20).mean()
            sma_val = float(sma20.dropna().iloc[-1]) if len(sma20.dropna()) else None
            estado = None
            if sma_val is not None:
                estado = 'Por encima de su media (20d)' if ultimo > sma_val else 'Por debajo de su media (20d)'
            st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
            _kpi_card('Último valor', f'{ultimo:.4f}', estado or '', color_grupo)
        _tarjeta_interp('¿Qué significa?', GLOSARIO_RATIOS.get(nombre, 'Sin descripción.'), color_grupo)
        st.markdown('<hr style="border-color:#21262d;margin:8px 0 18px 0">', unsafe_allow_html=True)


# ==============================================================
#  9. ESTILOS LOCALES (inyectados una sola vez)
# ==============================================================

def _inyectar_estilos():
    st.markdown("""
    <style>
    .rf-info-banner {
        background: rgba(58,123,213,0.07); border: 1px solid rgba(58,123,213,0.2);
        border-radius: 8px; padding: 10px 14px; color: #f5f7fa;
        font-size: 13px; margin-bottom: 16px; line-height: 1.6;
    }
    </style>
    """, unsafe_allow_html=True)


# ==============================================================
#  10. FUNCIÓN PRINCIPAL — punto de entrada del módulo
# ==============================================================

def modulo_renta_fija_macro(PLOTLY_CONFIG=None):
    """Punto de entrada del módulo. Llamar desde app.py, por ejemplo:

        from modulo_renta_fija_macro import modulo_renta_fija_macro
        ...
        elif MODULO == 'renta_fija_macro':
            modulo_renta_fija_macro(PLOTLY_CONFIG=PLOTLY_CONFIG)
    """
    global _DEFAULT_PLOTLY_CONFIG
    if PLOTLY_CONFIG:
        _DEFAULT_PLOTLY_CONFIG = PLOTLY_CONFIG

    _inyectar_estilos()

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #00838f;
         border-radius:14px; padding:28px 32px; margin-bottom:24px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">
        📉 Renta Fija, Salud del Mercado y Análisis Macro
      </div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Módulo cuantitativo de renta fija y macro: tarjetas KPI por subcategoría de bonos,
        un panel de salud de mercado (crédito + curva de tasas), la matriz de 12 ratios
        estratégicos con alertas automáticas, y cuatro grupos de ratios avanzados
        (volatilidad, liquidez, rotación sectorial y valuación macro/commodities).
      </div>
    </div>
    """, unsafe_allow_html=True)

    with st.spinner('Descargando precios de bonos, tasas y factores macro...'):
        precios, meta = cargar_precios_renta_fija_macro()

    if precios is None or precios.empty:
        st.error('No se pudieron descargar los datos. Revisá la conexión a Yahoo Finance '
                 'o intentá de nuevo en unos minutos.')
        return

    if meta.get('fallidos'):
        st.caption(f"⚠️ {len(meta['fallidos'])} tickers no pudieron descargarse: "
                    f"{', '.join(meta['fallidos'][:10])}"
                    f"{'…' if len(meta['fallidos']) > 10 else ''}")

    df_ratios = calcular_matriz_ratios_macro(precios)
    alertas = generar_alertas_macro(precios, df_ratios)

    st.markdown('### 🚨 Alertas Automáticas')
    _render_alertas(alertas)

    tabs = st.tabs([
        '💵 Renta Fija', '🏥 Salud del Mercado', '📊 Matriz de 12 Ratios',
        '🌪️ Volatilidad y Miedo', '💧 Liquidez y Apalancamiento',
        '🔄 Rotación Sectorial', '🪙 Valuación Macro y Commodities',
    ])

    with tabs[0]:
        _tab_renta_fija(precios)

    with tabs[1]:
        _tab_salud_mercado(precios, df_ratios)

    with tabs[2]:
        _tab_matriz_ratios(df_ratios)

    with tabs[3]:
        st.markdown("""
        <div class="rf-info-banner">
          Ratios de <b>volatilidad y miedo institucional</b>: miden el nivel de cobertura
          y de histeria en el mercado de derivados y bonos.
        </div>
        """, unsafe_allow_html=True)
        _tab_grupo_avanzado(
            df_ratios,
            ['Estrés Volatilidad Táctica (VIX/VIX9D)', 'Miedo Crediticio vs Accionario (HYG_Vol/VIX)'],
            'Volatilidad y Miedo', C_RED,
        )

    with tabs[4]:
        st.markdown("""
        <div class="rf-info-banner">
          Ratios de <b>liquidez y apalancamiento sistémico</b>: rastrean la disponibilidad
          de dinero real en el sistema financiero.
        </div>
        """, unsafe_allow_html=True)
        _tab_grupo_avanzado(
            df_ratios, ['Apetito Apalancamiento (SPHB/SPLV)'], 'Liquidez y Apalancamiento', '#bc8cff',
        )

    with tabs[5]:
        st.markdown("""
        <div class="rf-info-banner">
          Ratios de <b>rotación sectorial profunda</b>: permiten saber en qué fase del
          ciclo económico estamos, según qué sectores lideran el rally.
        </div>
        """, unsafe_allow_html=True)
        _tab_grupo_avanzado(
            df_ratios,
            ['Sensibilidad al Consumo (XLY/XLP)', 'Salud Economía Real (XLI/XLU)',
             'Apetito Innovación/Especulación (ARKK/QQQ)'],
            'Rotación Sectorial', C_LRED,
        )

    with tabs[6]:
        st.markdown("""
        <div class="rf-info-banner">
          Ratios de <b>valuación macro y commodities</b>: relacionan materias primas
          clave con el crecimiento económico y la inflación.
        </div>
        """, unsafe_allow_html=True)
        _tab_grupo_avanzado(
            df_ratios,
            ['Cobre/Oro — Doctor Copper (CPER/GLD)', 'Energía vs Mercado (XLE/SPY)'],
            'Valuación Macro y Commodities', C_YELL,
        )

    st.markdown(f"""
    <div style='text-align:center;color:#3a4a5a;font-size:10px;padding:14px;
         border-top:1px solid #21262d;margin-top:12px'>
      📉 Renta Fija · Salud del Mercado · Análisis Macro &nbsp;·&nbsp; Datos: Yahoo Finance
      &nbsp;·&nbsp; Caché: 5 min &nbsp;·&nbsp; {datetime.now().strftime('%d/%m/%Y %H:%M')} &nbsp;·&nbsp;
      <b>Solo informativo. No constituye asesoramiento financiero.</b>
    </div>
    """, unsafe_allow_html=True)
