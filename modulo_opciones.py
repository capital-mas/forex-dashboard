# ==============================================================
#  MÓDULO OPCIONES — Black-Scholes (Europea) / Binomial (Americana)
#  Adaptado del script standalone a Streamlit nativo.
#  Integrar en el Analizador Cuantitativo como horizonte propio.
# ==============================================================

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import date, datetime
from scipy.stats import norm
from scipy.optimize import brentq

# ── Paleta — coherente con el resto de la app ──
C_ACENT, C_MONSTER, C_TEXT, C_MUTED = '#3a7bd5', '#6CC24A', '#e6edf3', '#6b7d9a'
C_GREEN, C_RED, C_YELL, C_GRID = '#3fb950', '#f85149', '#e3b341', '#21262d'
C_BG1, C_BG2 = '#0d1117', '#07090f'
PLOTLY_LAYOUT_OPC = dict(plot_bgcolor=C_BG1, paper_bgcolor=C_BG2,
                         font=dict(color='#b0bcd0', family='Inter, sans-serif'))

N_PASOS_BINOMIAL = 150
TOLERANCIA_VOL = 0.10
NOMBRES_GRIEGAS = ["Delta", "Gamma", "Theta", "Vega", "Rho"]


def fmt_precio_opc(p):
    if p is None or (isinstance(p, float) and np.isnan(p)): return 'N/D'
    if p >= 1000: return f'${p:,.0f}'
    if p >= 10: return f'${p:.2f}'
    return f'${p:.5f}'


# ==============================================================
#  DATOS DEL ACTIVO
# ==============================================================

@st.cache_data(ttl=1800, show_spinner=False)
def _opc_datos_activo(ticker):
    """Precio, volatilidad histórica, dividend yield sugerido, RSI, SMA20."""
    try:
        import yfinance as yf
        df = yf.download(ticker, period='2y', interval='1d', auto_adjust=True, progress=False)
        if df is None or df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        precios = df['Close'].dropna()
        if len(precios) < 30: return None

        S, fuente, fecha_precio = None, None, None
        try:
            fast = yf.Ticker(ticker).fast_info
            p = fast.get('last_price') if hasattr(fast, 'get') else getattr(fast, 'last_price', None)
            if p: S, fuente = float(p), 'cotización en vivo (fast_info)'
        except Exception:
            pass
        if S is None:
            S, fuente = float(precios.iloc[-1]), 'último cierre diario'
            fecha_precio = precios.index[-1]

        retornos = np.log(precios / precios.shift(1)).dropna()
        vol_hist = float(retornos[-40:].std(ddof=1) * np.sqrt(252))
        sma20 = float(precios.rolling(20).mean().iloc[-1])

        delta = precios.diff()
        g = delta.clip(lower=0).rolling(14).mean()
        l = (-delta.clip(upper=0)).rolling(14).mean()
        rsi = float((100 - 100 / (1 + g / l)).iloc[-1])

        q_sug = None
        try:
            info = yf.Ticker(ticker).info or {}
            dy = info.get('dividendYield')
            if dy is not None:
                dy = float(dy)
                q_sug = dy / 100.0 if dy > 1 else dy
        except Exception:
            pass

        return dict(S=S, fuente=fuente, fecha_precio=fecha_precio, vol_hist=vol_hist,
                    sma20=sma20, rsi=rsi, q_sugerido=q_sug, ultimo_cierre=float(precios.iloc[-1]))
    except Exception:
        return None

# ==============================================================
#  CADENA DE OPCIONES REAL (Yahoo Finance)
# ==============================================================

@st.cache_data(ttl=900, show_spinner=False)
def _opc_vencimientos_disponibles(ticker):
    """Fechas de vencimiento reales que Yahoo Finance tiene publicadas para el ticker."""
    try:
        import yfinance as yf
        vtos = yf.Ticker(ticker).options
        return list(vtos) if vtos else []
    except Exception:
        return []


@st.cache_data(ttl=900, show_spinner=False)
def _opc_cadena_opciones(ticker, vencimiento):
    """Descarga la cadena de opciones (calls y puts) de Yahoo Finance para un ticker
    y una fecha de vencimiento puntual (formato 'YYYY-MM-DD', tal cual la devuelve
    yfinance en .options). Devuelve dict {'calls': df, 'puts': df} o None si falla."""
    try:
        import yfinance as yf
        cadena = yf.Ticker(ticker).option_chain(vencimiento)
        calls, puts = cadena.calls.copy(), cadena.puts.copy()

        cols_utiles = ['contractSymbol', 'strike', 'lastPrice', 'bid', 'ask', 'volume',
                       'openInterest', 'impliedVolatility', 'inTheMoney']
        for df in (calls, puts):
            for c in cols_utiles:
                if c not in df.columns:
                    df[c] = np.nan

        calls = calls[cols_utiles].sort_values('strike').reset_index(drop=True)
        puts = puts[cols_utiles].sort_values('strike').reset_index(drop=True)
        if calls.empty and puts.empty:
            return None
        return {'calls': calls, 'puts': puts}
    except Exception:
        return None


def _opc_fila_strike_mas_cercano(df_lado, strike_objetivo):
    """Dado un DataFrame de calls o puts y un strike de referencia (ej. el spot),
    devuelve la fila cuyo strike está más cerca — útil para pre-seleccionar ATM."""
    if df_lado is None or df_lado.empty:
        return None
    idx = (df_lado['strike'] - strike_objetivo).abs().idxmin()
    return df_lado.loc[idx]


def render_tabla_cadena_opciones(cadena, S, tipo=None):
    """Muestra calls y/o puts de la cadena real, resaltando el strike más cercano
    al spot y formateando bid/ask/IV/volumen para lectura rápida."""
    if cadena is None:
        st.warning('No se pudo descargar la cadena de opciones para este vencimiento.')
        return

    def _fmt_df(df):
        d = df.copy()
        d['ITM'] = d['inTheMoney'].map({True: '🟢 ITM', False: '⚪ OTM'})
        d['IV'] = d['impliedVolatility'].apply(lambda v: f'{v:.1%}' if pd.notna(v) else 'N/D')
        d['Bid'] = d['bid'].apply(lambda v: f'{v:.2f}' if pd.notna(v) else 'N/D')
        d['Ask'] = d['ask'].apply(lambda v: f'{v:.2f}' if pd.notna(v) else 'N/D')
        d['Último'] = d['lastPrice'].apply(lambda v: f'{v:.2f}' if pd.notna(v) else 'N/D')
        d['Vol.'] = d['volume'].fillna(0).astype(int)
        d['OI'] = d['openInterest'].fillna(0).astype(int)
        return d[['strike', 'Último', 'Bid', 'Ask', 'Vol.', 'OI', 'IV', 'ITM']].rename(columns={'strike': 'Strike'})

    tabs_lado = []
    if tipo in (None, 'C'): tabs_lado.append(('📈 Calls', cadena['calls']))
    if tipo in (None, 'P'): tabs_lado.append(('📉 Puts', cadena['puts']))

    if len(tabs_lado) == 1:
        _, df_lado = tabs_lado[0]
        st.dataframe(_fmt_df(df_lado), use_container_width=True, hide_index=True, height=320)
    else:
        tabs = st.tabs([n for n, _ in tabs_lado])
        for tab, (_, df_lado) in zip(tabs, tabs_lado):
            with tab:
                st.dataframe(_fmt_df(df_lado), use_container_width=True, hide_index=True, height=320)
              
# ==============================================================
#  MODELO EUROPEO — Black-Scholes-Merton
# ==============================================================

def opcion_europea_bs(tipo, S, K, T, r, sigma, q=0.0):
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if tipo == 'C':
        return S * np.exp(-q * T) * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * np.exp(-q * T) * norm.cdf(-d1)


def calcular_letras_griegas_europea(tipo, S, K, T, r, sigma, q=0.0):
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    pdf_d1 = norm.pdf(d1)
    desc_div = np.exp(-q * T)
    delta = desc_div * norm.cdf(d1) if tipo == 'C' else desc_div * (norm.cdf(d1) - 1)
    gamma = desc_div * pdf_d1 / (S * sigma * np.sqrt(T))
    vega = S * desc_div * pdf_d1 * np.sqrt(T) / 100
    if tipo == 'C':
        theta = (-S * desc_div * pdf_d1 * sigma / (2 * np.sqrt(T))
                 - r * K * np.exp(-r * T) * norm.cdf(d2) + q * S * desc_div * norm.cdf(d1)) / 365
        rho = K * T * np.exp(-r * T) * norm.cdf(d2) / 100
    else:
        theta = (-S * desc_div * pdf_d1 * sigma / (2 * np.sqrt(T))
                 + r * K * np.exp(-r * T) * norm.cdf(-d2) - q * S * desc_div * norm.cdf(-d1)) / 365
        rho = -K * T * np.exp(-r * T) * norm.cdf(-d2) / 100
    return {'Delta': float(delta), 'Gamma': float(gamma), 'Theta': float(theta),
            'Vega': float(vega), 'Rho': float(rho)}


# ==============================================================
#  MODELO AMERICANO — Binomial CRR
# ==============================================================

def precio_binomial_americana(tipo, S, K, T, r, sigma, q=0.0, n=N_PASOS_BINOMIAL):
    if T <= 0:
        return max(S - K, 0.0) if tipo == 'C' else max(K - S, 0.0)
    dt = T / n
    u = np.exp(sigma * np.sqrt(dt)); d = 1.0 / u
    disc = np.exp(-r * dt)
    p = (np.exp((r - q) * dt) - d) / (u - d)
    p = min(max(p, 1e-8), 1 - 1e-8)
    j = np.arange(n + 1)
    ST = S * (u ** j) * (d ** (n - j))
    valores = np.maximum(ST - K, 0.0) if tipo == 'C' else np.maximum(K - ST, 0.0)
    for i in range(n - 1, -1, -1):
        valores = disc * (p * valores[1:i + 2] + (1 - p) * valores[0:i + 1])
        j = np.arange(i + 1)
        ST = S * (u ** j) * (d ** (i - j))
        intrinsico = np.maximum(ST - K, 0.0) if tipo == 'C' else np.maximum(K - ST, 0.0)
        valores = np.maximum(valores, intrinsico)
    return float(valores[0])


def _arbol_extendido_americana(tipo, S, K, T, r, sigma, q, n):
    dt = T / n
    u = np.exp(sigma * np.sqrt(dt)); d = 1.0 / u
    disc = np.exp(-r * dt)
    p = (np.exp((r - q) * dt) - d) / (u - d)
    p = min(max(p, 1e-8), 1 - 1e-8)
    N = n + 2
    j = np.arange(N + 1)
    ST = S * (u ** j) * (d ** (N - j))
    valores = np.maximum(ST - K, 0.0) if tipo == 'C' else np.maximum(K - ST, 0.0)
    capturas = {}
    for i in range(N - 1, -1, -1):
        valores = disc * (p * valores[1:i + 2] + (1 - p) * valores[0:i + 1])
        j = np.arange(i + 1)
        ST_i = S * (u ** j) * (d ** (i - j))
        intrinsico = np.maximum(ST_i - K, 0.0) if tipo == 'C' else np.maximum(K - ST_i, 0.0)
        valores = np.maximum(valores, intrinsico)
        if i in (0, 1, 2): capturas[i] = valores.copy()
    return capturas, u, d, dt


def calcular_letras_griegas_americana(tipo, S, K, T, r, sigma, q=0.0, n=N_PASOS_BINOMIAL):
    capturas, u, d, dt = _arbol_extendido_americana(tipo, S, K, T, r, sigma, q, n)
    f0 = capturas[0][0]
    f1_d, f1_u = capturas[1][0], capturas[1][1]
    f2_dd, f2_ud, f2_uu = capturas[2][0], capturas[2][1], capturas[2][2]
    delta = (f1_u - f1_d) / (S * u - S * d)
    gamma = ((f2_uu - f2_ud) / (S * u ** 2 - S) - (f2_ud - f2_dd) / (S - S * d ** 2)) / (0.5 * (S * u ** 2 - S * d ** 2))
    theta = (f2_ud - f0) / (2 * dt) / 365
    h_sigma = 1e-4
    vega = (precio_binomial_americana(tipo, S, K, T, r, sigma + h_sigma, q, n)
            - precio_binomial_americana(tipo, S, K, T, r, sigma - h_sigma, q, n)) / (2 * h_sigma) / 100
    h_r = 1e-5
    rho = (precio_binomial_americana(tipo, S, K, T, r + h_r, sigma, q, n)
           - precio_binomial_americana(tipo, S, K, T, r - h_r, sigma, q, n)) / (2 * h_r) / 100
    return {'Delta': float(delta), 'Gamma': float(gamma), 'Theta': float(theta),
            'Vega': float(vega), 'Rho': float(rho)}


def precio_opcion(tipo, S, K, T, r, sigma, q=0.0, estilo="americana"):
    if T <= 0:
        return max(S - K, 0.0) if tipo == 'C' else max(K - S, 0.0)
    if estilo == "europea":
        return float(opcion_europea_bs(tipo, S, K, T, r, sigma, q))
    return precio_binomial_americana(tipo, S, K, T, r, sigma, q, N_PASOS_BINOMIAL)


def calcular_griegas(tipo, S, K, T, r, sigma, q=0.0, estilo="americana"):
    if T <= 0:
        delta = (1.0 if S > K else 0.0) if tipo == 'C' else (-1.0 if S < K else 0.0)
        return {'Delta': delta, 'Gamma': 0.0, 'Theta': 0.0, 'Vega': 0.0, 'Rho': 0.0}
    if estilo == "europea":
        return calcular_letras_griegas_europea(tipo, S, K, T, r, sigma, q)
    return calcular_letras_griegas_americana(tipo, S, K, T, r, sigma, q, N_PASOS_BINOMIAL)


def volatilidad_implicita(tipo, S, K, T, r, precio_mercado, q=0.0, estilo="americana"):
    piso_sigma = 1e-6 if estilo == "europea" else 1e-3
    try:
        f = lambda sigma: precio_opcion(tipo, S, K, T, r, sigma, q, estilo) - precio_mercado
        return float(brentq(f, piso_sigma, 5.0)), None
    except ValueError:
        piso = precio_opcion(tipo, S, K, T, r, piso_sigma, q, estilo)
        techo = precio_opcion(tipo, S, K, T, r, 5.0, q, estilo)
        if precio_mercado < piso:
            return float('nan'), f"precio mercado ({precio_mercado:.2f}) < piso teórico ({piso:.2f})"
        elif precio_mercado > techo:
            return float('nan'), f"precio mercado ({precio_mercado:.2f}) > techo teórico ({techo:.2f})"
        return float('nan'), "no converge"


def calcular_apalancamiento(delta, S, precio_opcion_valor):
    if precio_opcion_valor == 0 or np.isnan(precio_opcion_valor): return float('nan')
    return float(delta * S / precio_opcion_valor)


def generar_senal_operacion(precio_teorico, precio_mercado, vol_hist, vol_implicita, motivo_falla=None):
    if np.isnan(vol_implicita):
        return f"❌ Vol. implícita no disponible" + (f" ({motivo_falla})" if motivo_falla else "")
    spread_vol = vol_implicita - vol_hist
    sobre = precio_mercado - precio_teorico
    if spread_vol > TOLERANCIA_VOL and sobre > 0: return "🔴 CARA (IV alta y precio mercado > teórico)"
    if spread_vol < -TOLERANCIA_VOL and sobre < 0: return "🟢 BARATA (IV baja y precio mercado < teórico)"
    if sobre > 0: return "🟠 Levemente cara"
    if sobre < 0: return "🟡 Levemente barata"
    return "⚪ Neutra / a precio justo"


def evaluar_liquidez(bid, ask):
    mid = (bid + ask) / 2.0
    spread_abs = ask - bid
    spread_pct = spread_abs / mid if mid > 0 else float('nan')
    if np.isnan(spread_pct): senal = "N/D"
    elif spread_pct > 0.15: senal = "🔴 MUY poco líquida (>15%) — usar orden límite"
    elif spread_pct > 0.07: senal = "🟠 Liquidez media (7-15%) — orden límite"
    else: senal = "🟢 Líquida (<7%)"
    return mid, spread_abs, spread_pct, senal


# ==============================================================
#  CATÁLOGO DE ESTRATEGIAS
# ==============================================================

CATALOGO_ESTRATEGIAS = [
    {"id": 1, "nombre": "Long Call", "sesgo": "alcista",
     "descripcion": "Comprás una Call. Ganás si el precio sube por encima del break-even (strike + prima). Pérdida máxima = prima. Ganancia ilimitada.",
     "patas": [{"tipo": "C", "accion": "comprar", "prompt": "Call que comprás"}]},
    {"id": 2, "nombre": "Bull Call Spread", "sesgo": "alcista",
     "descripcion": "Comprás Call de strike bajo y vendés Call de strike alto. Baja costo y riesgo, ganancia limitada al ancho entre strikes menos el débito.",
     "patas": [{"tipo": "C", "accion": "comprar", "prompt": "Call COMPRADA (strike más bajo)"},
               {"tipo": "C", "accion": "vender", "prompt": "Call VENDIDA (strike más alto)"}]},
    {"id": 3, "nombre": "Bull Put Spread (credit)", "sesgo": "alcista",
     "descripcion": "Vendés Put de strike alto, comprás Put de strike bajo como cobertura. Cobrás crédito neto. Ganás si el precio queda arriba del strike vendido.",
     "patas": [{"tipo": "P", "accion": "vender", "prompt": "Put VENDIDA (strike más alto)"},
               {"tipo": "P", "accion": "comprar", "prompt": "Put COMPRADA (strike más bajo, cobertura)"}]},
    {"id": 4, "nombre": "Cash-Secured Put", "sesgo": "alcista",
     "descripcion": "Vendés una Put reservando efectivo para comprar el subyacente si te asignan. Riesgo bajista grande si el precio se derrumba.",
     "patas": [{"tipo": "P", "accion": "vender", "prompt": "Put que vendés"}]},
    {"id": 5, "nombre": "Comprar Call + Vender Put (Risk Reversal / Sintética)", "sesgo": "alcista",
     "descripcion": "Comprás Call y vendés Put. Mismo strike = sintética (como tener el subyacente, apalancado). Strikes distintos = Risk Reversal. Pérdida potencial grande si cae fuerte.",
     "patas": [{"tipo": "C", "accion": "comprar", "prompt": "Call que comprás"},
               {"tipo": "P", "accion": "vender", "prompt": "Put que vendés"}]},
    {"id": 6, "nombre": "Long Put", "sesgo": "bajista",
     "descripcion": "Comprás una Put. Ganás si el precio cae por debajo del break-even (strike - prima). Pérdida máxima = prima.",
     "patas": [{"tipo": "P", "accion": "comprar", "prompt": "Put que comprás"}]},
    {"id": 7, "nombre": "Bear Put Spread", "sesgo": "bajista",
     "descripcion": "Comprás Put de strike alto y vendés Put de strike bajo. Ganancia limitada al ancho entre strikes menos el débito pagado.",
     "patas": [{"tipo": "P", "accion": "comprar", "prompt": "Put COMPRADA (strike más alto)"},
               {"tipo": "P", "accion": "vender", "prompt": "Put VENDIDA (strike más bajo)"}]},
    {"id": 8, "nombre": "Bear Call Spread (credit)", "sesgo": "bajista",
     "descripcion": "Vendés Call de strike bajo y comprás Call de strike alto como cobertura. Ganás si el precio queda debajo del strike vendido.",
     "patas": [{"tipo": "C", "accion": "vender", "prompt": "Call VENDIDA (strike más bajo)"},
               {"tipo": "C", "accion": "comprar", "prompt": "Call COMPRADA (strike más alto, cobertura)"}]},
    {"id": 9, "nombre": "Long Straddle", "sesgo": "neutral",
     "descripcion": "Comprás Call y Put del mismo strike (ATM). Ganás con movimiento fuerte en cualquier dirección; perdés si el precio queda quieto.",
     "patas": [{"tipo": "C", "accion": "comprar", "prompt": "Call y Put (mismo strike) que comprás"},
               {"tipo": "P", "accion": "comprar", "prompt": None, "mismo_strike_que": 0}]},
    {"id": 10, "nombre": "Long Strangle", "sesgo": "neutral",
     "descripcion": "Comprás Call OTM y Put OTM. Más barato que el Straddle, necesita movimiento más grande para ser rentable.",
     "patas": [{"tipo": "C", "accion": "comprar", "prompt": "Call OTM (strike más alto)"},
               {"tipo": "P", "accion": "comprar", "prompt": "Put OTM (strike más bajo)"}]},
    {"id": 11, "nombre": "Short Strangle", "sesgo": "neutral",
     "descripcion": "Vendés Call OTM y Put OTM cobrando ambas primas. Ganás si el precio queda dentro del rango. Riesgo ILIMITADO si se escapa fuerte.",
     "patas": [{"tipo": "C", "accion": "vender", "prompt": "Call OTM VENDIDA (strike más alto)"},
               {"tipo": "P", "accion": "vender", "prompt": "Put OTM VENDIDA (strike más bajo)"}]},
    {"id": 12, "nombre": "Iron Condor", "sesgo": "neutral",
     "descripcion": "Versión con cobertura del Short Strangle: vendés Put y Call, comprás otras más lejanas. Crédito neto acotado, pérdida máxima definida.",
     "patas": [{"tipo": "P", "accion": "vender", "prompt": "Put VENDIDA (ala interna)"},
               {"tipo": "P", "accion": "comprar", "prompt": "Put COMPRADA (ala externa, cobertura)"},
               {"tipo": "C", "accion": "vender", "prompt": "Call VENDIDA (ala interna)"},
               {"tipo": "C", "accion": "comprar", "prompt": "Call COMPRADA (ala externa, cobertura)"}]},
]

# ── Glosario general de términos de opciones (independiente de cualquier cálculo) ──
GLOSARIO_TERMINOS = {
    'Opción': 'Contrato que da el DERECHO (no la obligación) de comprar (Call) o vender (Put) un activo a un precio fijado, antes o en una fecha determinada.',
    'Americana/Europea': 'Americana: se ejerce en cualquier momento antes del vencimiento (acciones en Argentina y EEUU). Europea: solo se ejerce en la fecha de vencimiento (ej. índices como el SPX).',
    'Subyacente': 'El activo sobre el que está armada la opción.',
    'Strike (K)': 'Precio al que se puede ejercer la opción.',
    'Prima': 'Precio que pagás (si comprás) o cobrás (si vendés) la opción.',
    'Vencimiento': 'Fecha límite hasta la que la opción existe.',
    'Call / Put': 'Call = derecho a COMPRAR al strike. Put = derecho a VENDER al strike.',
    'ITM/OTM/ATM': 'In/Out/At the Money — con valor intrínseco, sin valor intrínseco, o strike ≈ precio actual.',
    'Asignación': 'Lo que le pasa al VENDEDOR de una opción cuando el comprador decide ejercerla: queda obligado a cumplir.',
    'Break-even': 'Precio del subyacente al vencimiento donde la estrategia empieza a ser rentable.',
    'Crédito / Débito': 'Crédito = cobrás dinero al armar la estrategia. Débito = pagás dinero.',
    'Bid/Ask': 'Bid = precio al que podés vender ahora. Ask = precio al que podés comprar ahora. El Ask siempre es mayor o igual al Bid.',
    'Spread (bid-ask)': 'Diferencia entre Ask y Bid. Más grande = menos líquida, más cuesta entrar/salir.',
    'Slippage': 'Costo de ejecutar a precios reales (cruzando el spread) en vez del precio medio teórico. Comprar te cuesta el Ask; vender te da el Bid.',
    'Vol. Histórica (HV)': 'Cuánto se movió el activo en el pasado.',
    'Vol. Implícita (IV)': 'Cuánto movimiento futuro está pricing el mercado a través del precio de la opción.',
    'Dividend Yield (q)': 'Rendimiento de dividendos anual continuo. Baja el precio de la Call y sube el de la Put (quien tiene la opción no cobra esos dividendos).',
    'Tamaño de posición': 'Cuántos contratos operar según tu capital y tu tolerancia al riesgo. Una regla común es no arriesgar más de 1-2% del capital total en una sola operación.',
    'Lote/Contrato': 'Cuántas unidades del subyacente representa 1 contrato. En EEUU suele ser 100 (hay que multiplicar). En Argentina puede variar según el bróker — confirmalo antes de operar.',
}

# ── Glosario específico de las griegas (separado, porque son el motor de sensibilidad) ──
GLOSARIO_GRIEGAS = {
    'Delta': 'Cuánto se mueve el precio de la opción por cada $1 que se mueve el subyacente. También aproxima la probabilidad de terminar ITM.',
    'Gamma': 'Qué tan rápido cambia el Delta cuando se mueve el subyacente. Más alto cerca del ATM y cerca del vencimiento.',
    'Theta': 'Cuánto vale la opción por día, solo por el paso del tiempo (negativo si comprás prima, a favor si vendés prima).',
    'Vega': 'Cuánto cambia el precio de la opción si la volatilidad implícita sube o baja 1 punto porcentual. Comprar = Vega positiva; vender = Vega negativa.',
    'Rho': 'Cuánto cambia el precio de la opción si la tasa de interés sube o baja 1 punto porcentual.',
    'Apalancamiento (Lambda)': 'Lambda = Delta * S / Precio_opción. Cuántas veces más se mueve, en %, la opción respecto del subyacente.',
}


# ==============================================================
#  MOTOR DE PAYOFF
# ==============================================================

def payoff_pata(pata, S_T):
    intrinsico = max(S_T - pata["strike"], 0) if pata["tipo"] == "C" else max(pata["strike"] - S_T, 0)
    return (intrinsico - pata["precio_mercado"]) if pata["accion"] == "comprar" else (pata["precio_mercado"] - intrinsico)


def payoff_total(patas, S_T):
    return sum(payoff_pata(p, S_T) for p in patas)


def costo_neto_estrategia(patas):
    return sum(p["precio_mercado"] if p["accion"] == "comprar" else -p["precio_mercado"] for p in patas)


def costo_neto_real_estrategia(patas):
    total = 0.0
    for p in patas:
        total += p["ask"] if p["accion"] == "comprar" else -p["bid"]
    return total


def _pendiente_mas_alla_del_strike_maximo(patas):
    return sum((1 if p["accion"] == "comprar" else -1) for p in patas if p["tipo"] == "C")


def analizar_payoff_estrategia(patas):
    strikes = sorted(set(p["strike"] for p in patas))
    valor_en_cero = payoff_total(patas, 0.0)
    valores_en_strikes = {k: payoff_total(patas, k) for k in strikes}
    puntos_x = [0.0] + strikes
    puntos_y = [valor_en_cero] + [valores_en_strikes[k] for k in strikes]

    breakevens = []
    for i in range(len(puntos_x) - 1):
        x0, x1, y0, y1 = puntos_x[i], puntos_x[i+1], puntos_y[i], puntos_y[i+1]
        if abs(y0) < 1e-9: breakevens.append(round(x0, 2))
        if (y0 < 0 < y1) or (y0 > 0 > y1):
            breakevens.append(round(x0 + (0 - y0) * (x1 - x0) / (y1 - y0), 2))

    pendiente_arriba = _pendiente_mas_alla_del_strike_maximo(patas)
    if strikes:
        x_ult, y_ult = strikes[-1], valores_en_strikes[strikes[-1]]
        if abs(y_ult) < 1e-9: breakevens.append(round(x_ult, 2))
        elif pendiente_arriba != 0 and ((y_ult < 0 and pendiente_arriba > 0) or (y_ult > 0 and pendiente_arriba < 0)):
            breakevens.append(round(x_ult - y_ult / pendiente_arriba, 2))

    ganancia_max = max(puntos_y); perdida_max = min(puntos_y)
    return {
        "breakevens": sorted(set(breakevens)),
        "ganancia_max": ganancia_max, "ganancia_ilimitada": pendiente_arriba > 0,
        "perdida_max": perdida_max, "perdida_ilimitada": pendiente_arriba < 0,
        "costo_neto": costo_neto_estrategia(patas),
    }


def calcular_tamano_posicion(analisis, patas, capital, pct_riesgo, mult=100):
    riesgo_maximo = capital * pct_riesgo
    L = [f"Capital: {capital:,.2f} · Riesgo máx. por operación: {pct_riesgo:.1%} → {riesgo_maximo:,.2f}"]
    if analisis["perdida_ilimitada"]:
        L.append("⚠️ Pérdida ILIMITADA (pata vendida sin cobertura). No se puede fijar tamaño por 'pérdida máxima'. "
                  "Evaluá agregar una pata de protección (ej. Short Strangle → Iron Condor).")
    else:
        perdida_x_contrato = abs(analisis["perdida_max"]) * mult
        if perdida_x_contrato <= 0:
            L.append("La pérdida máxima calculada da 0 — revisá los datos cargados.")
        else:
            contratos = int(riesgo_maximo // perdida_x_contrato)
            L.append(f"Pérdida máxima por contrato: {perdida_x_contrato:,.2f}")
            if contratos >= 1:
                L.append(f"✅ Tamaño sugerido: hasta {contratos} contrato(s) "
                         f"(pérdida máx. total: {contratos*perdida_x_contrato:,.2f})")
            else:
                L.append(f"⚠️ Ni 1 contrato entra en tu regla de riesgo: pérdida máxima de 1 contrato "
                         f"({perdida_x_contrato:,.2f}) supera tu límite ({riesgo_maximo:,.2f}).")
    puts_vendidas = [p for p in patas if p["tipo"] == "P" and p["accion"] == "vender"]
    if puts_vendidas:
        capital_reservado = sum(p["strike"] for p in puts_vendidas) * mult
        L.append(f"💰 Si te asignan alguna Put vendida vas a necesitar {capital_reservado:,.2f} "
                  f"(aparte del riesgo de la operación).")
    return L


def verificar_paridad_put_call(filas, umbral=0.08):
    por_strike = {}
    for f in filas:
        por_strike.setdefault(f["_strike"], {})[f["_tipo"]] = f["_iv"]
    alertas = []
    for k, d in sorted(por_strike.items()):
        ivc, ivp = d.get("C"), d.get("P")
        if ivc is not None and ivp is not None and not np.isnan(ivc) and not np.isnan(ivp):
            diff = abs(ivc - ivp)
            if diff > umbral:
                alertas.append(f"Strike {k}: IV Call {ivc:.2%} vs IV Put {ivp:.2%} → diferencia {diff:.2%}")
    if not alertas:
        return True, "✅ Sin violaciones grandes de paridad Put-Call."
    return False, "⚠️ Diferencias grandes de IV en el mismo strike:\n" + "\n".join(alertas)


def analizar_skew(filas, S):
    puts_otm = [f["_iv"] for f in filas if f["_tipo"] == "P" and f["_strike"] < S and not np.isnan(f["_iv"])]
    calls_otm = [f["_iv"] for f in filas if f["_tipo"] == "C" and f["_strike"] > S and not np.isnan(f["_iv"])]
    if not puts_otm or not calls_otm:
        return "⚠️ No hay strikes OTM de ambos lados del spot para medir skew."
    iv_p, iv_c = sum(puts_otm)/len(puts_otm), sum(calls_otm)/len(calls_otm)
    diff = iv_p - iv_c
    txt = f"IV prom. Puts OTM: {iv_p:.2%} · IV prom. Calls OTM: {iv_c:.2%} · Diferencia: {diff:+.2%}. "
    if diff > 0.03: txt += "📐 Skew bajista: el mercado paga más por protección a la baja."
    elif diff < -0.03: txt += "📐 Skew alcista: el mercado paga más por upside especulativo."
    else: txt += "📐 Skew plano."
    return txt


# ==============================================================
#  GRÁFICOS
# ==============================================================

def fig_payoff(patas, S, analisis):
    xs = np.linspace(max(0.01, S*0.5), S*1.5, 200)
    ys = [payoff_total(patas, x) for x in xs]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=ys, line=dict(color=C_ACENT, width=2.4), fill='tozeroy',
                              fillcolor='rgba(58,123,213,0.10)', name='P&L al vencimiento'))
    fig.add_hline(y=0, line_color=C_MUTED, opacity=0.5)
    fig.add_vline(x=S, line_dash='dot', line_color=C_YELL, opacity=0.6,
                  annotation_text=f'Spot {S:.2f}', annotation_font_color=C_YELL)
    for be in analisis['breakevens']:
        fig.add_vline(x=be, line_dash='dash', line_color=C_GREEN, opacity=0.5,
                      annotation_text=f'BE {be:.2f}', annotation_font_color=C_GREEN)
    for p in patas:
        fig.add_vline(x=p['strike'], line_dash='dot', line_color=C_MUTED, opacity=0.25)
    fig.update_layout(**PLOTLY_LAYOUT_OPC, height=440,
                       title=dict(text='Payoff al vencimiento', font=dict(color=C_TEXT, size=14)),
                       xaxis=dict(title='Precio del subyacente', gridcolor=C_GRID),
                       yaxis=dict(title='P&L por acción', gridcolor=C_GRID),
                       margin=dict(l=10, r=10, t=45, b=10))
    return fig


def fig_griegas_sensibilidad(patas, S, T, r, sigmas, q, estilo):
    variaciones = np.linspace(-0.20, 0.20, 21)
    datos = {g: [] for g in NOMBRES_GRIEGAS}
    for var in variaciones:
        S_T = S * (1 + var)
        totales = {g: 0.0 for g in NOMBRES_GRIEGAS}
        for pata, sigma in zip(patas, sigmas):
            try:
                letras = calcular_griegas(pata['tipo'], S_T, pata['strike'], T, r, sigma, q, estilo)
            except Exception:
                letras = {g: np.nan for g in NOMBRES_GRIEGAS}
            signo = 1 if pata['accion'] == 'comprar' else -1
            for g in NOMBRES_GRIEGAS:
                totales[g] += signo * letras[g]
        for g in NOMBRES_GRIEGAS:
            datos[g].append(totales[g])

    xs = S * (1 + variaciones)
    fig = make_subplots(rows=1, cols=5, subplot_titles=NOMBRES_GRIEGAS)
    colores = [C_MONSTER, C_ACENT, C_RED, '#bc8cff', C_YELL]
    for i, g in enumerate(NOMBRES_GRIEGAS):
        fig.add_trace(go.Scatter(x=xs, y=datos[g], line=dict(color=colores[i], width=2), showlegend=False),
                      row=1, col=i+1)
        fig.add_vline(x=S, line_dash='dot', line_color=C_MUTED, opacity=0.4, row=1, col=i+1)
        fig.update_xaxes(gridcolor=C_GRID, row=1, col=i+1)
        fig.update_yaxes(gridcolor=C_GRID, row=1, col=i+1)
    fig.update_layout(**PLOTLY_LAYOUT_OPC, height=320, margin=dict(l=10, r=10, t=40, b=10),
                       title=dict(text='Sensibilidad de las griegas NETAS al precio del subyacente', font=dict(color=C_TEXT, size=13)))
    fig.update_annotations(font=dict(color=C_TEXT, size=11))
    return fig


def fig_repricing(patas, S, T, r, sigmas, q, estilo, costo_neto):
    variaciones = np.linspace(-0.20, 0.20, 41)
    valores, xs = [], []
    for var in variaciones:
        S_T = S * (1 + var)
        v = 0.0
        for pata, sigma in zip(patas, sigmas):
            try:
                precio = precio_opcion(pata['tipo'], S_T, pata['strike'], T, r, sigma, q, estilo)
            except Exception:
                precio = np.nan
            v += precio if pata['accion'] == 'comprar' else -precio
        valores.append(v); xs.append(S_T)
    pnl = [v - costo_neto for v in valores]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=pnl, line=dict(color=C_MONSTER, width=2.2), name='P&L mark-to-market (hoy)'))
    fig.add_hline(y=0, line_color=C_MUTED, opacity=0.5)
    fig.add_vline(x=S, line_dash='dot', line_color=C_YELL, opacity=0.6)
    fig.update_layout(**PLOTLY_LAYOUT_OPC, height=380,
                       title=dict(text='P&L si el subyacente se mueve HOY (mismo T, sin pasar tiempo)', font=dict(color=C_TEXT, size=13)),
                       xaxis=dict(title='Precio del subyacente', gridcolor=C_GRID),
                       yaxis=dict(title='P&L por acción', gridcolor=C_GRID),
                       margin=dict(l=10, r=10, t=45, b=10))
    return fig


def render_glosario_opciones():
    """Glosario independiente — no depende de ninguna estrategia cargada ni cálculo hecho.
    Se muestra siempre arriba, como referencia rápida, separado del resto del flujo."""
    with st.expander('📖 Glosario — términos de opciones', expanded=False):
        for term, desc in GLOSARIO_TERMINOS.items():
            st.markdown(f"<div style='margin-bottom:8px'><b style='color:#bc8cff;font-size:12.5px'>{term}</b><br>"
                        f"<span style='color:#f5f7fa;font-size:12px;line-height:1.5'>{desc}</span></div>",
                        unsafe_allow_html=True)

    with st.expander('📐 Glosario — qué significa cada griega', expanded=False):
        for term, desc in GLOSARIO_GRIEGAS.items():
            st.markdown(f"<div style='margin-bottom:8px'><b style='color:#3a7bd5;font-size:12.5px'>{term}</b><br>"
                        f"<span style='color:#f5f7fa;font-size:12px;line-height:1.5'>{desc}</span></div>",
                        unsafe_allow_html=True)


# ==============================================================
#  ESTADO DE SESIÓN
# ==============================================================

def _init_estado_opciones():
    defaults = {
        'opc_paso': 1, 'opc_ticker': '', 'opc_vto': None, 'opc_r': 0.30, 'opc_q': 0.0,
        'opc_estilo': 'americana', 'opc_estrategia_id': None, 'opc_patas_data': [],
        'opc_mult': 100, 'opc_capital': 1000.0, 'opc_pct_riesgo': 0.02, 'opc_calculado': False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ==============================================================
#  UI PRINCIPAL
# ==============================================================

def modulo_opciones():
    _init_estado_opciones()

    st.markdown("""
    <div style="background:linear-gradient(135deg,#1c1020 0%,#2a0a30 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #bc8cff;
         border-radius:14px; padding:28px 32px; margin-bottom:24px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">🎲 Valuación de Opciones</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Elegí una estrategia del catálogo, cargá bid/ask de cada pata y obtené precio teórico,
        volatilidad implícita, griegas, liquidez/slippage, payoff, escenarios de repricing y
        tamaño de posición sugerido. Modelo <b style="color:#f0883e">Binomial (americana)</b> o
        <b style="color:#3a7bd5">Black-Scholes (europea)</b> según el estilo de ejercicio.
      </div>
    </div>
    """, unsafe_allow_html=True)

    render_glosario_opciones()

    # ── PASO 1: activo y parámetros generales ──────────────────────────
    with st.expander('1️⃣ Activo y parámetros generales', expanded=(st.session_state['opc_paso'] == 1)):
        c1, c2 = st.columns([2, 1])
        with c1:
            ticker = st.text_input('Ticker (ej: GGAL.BA, AAPL, YPFD.BA)', value=st.session_state['opc_ticker'],
                                    key='opc_ticker_input')
        with c2:
            estilo = st.selectbox('Estilo de ejercicio', ['americana', 'europea'],
                                   index=0 if st.session_state['opc_estilo'] == 'americana' else 1,
                                   help='Americana: acciones/ETFs (Arg y EEUU), se ejerce en cualquier momento. '
                                        'Europea: típico de índices (SPX), solo se ejerce al vencimiento.',
                                   key='opc_estilo_input')

        vtos_reales = _opc_vencimientos_disponibles(ticker.strip().upper()) if ticker else []

        c3, c4, c5 = st.columns(3)
        with c3:
            if vtos_reales:
                usar_manual = st.toggle('Vencimiento manual (fuera de la cadena)', value=False,
                                         key='opc_vto_manual_toggle')
                if usar_manual:
                    vto = st.date_input('Vencimiento', value=st.session_state['opc_vto'] or date.today(),
                                         min_value=date.today(), key='opc_vto_input')
                else:
                    vtos_fmt = [datetime.strptime(v, '%Y-%m-%d').date() for v in vtos_reales]
                    idx_def = 0
                    if st.session_state['opc_vto'] in vtos_fmt:
                        idx_def = vtos_fmt.index(st.session_state['opc_vto'])
                    vto_str = st.selectbox('Vencimiento (cadena real de Yahoo Finance)', vtos_reales,
                                            index=idx_def, key='opc_vto_select')
                    vto = datetime.strptime(vto_str, '%Y-%m-%d').date()
                    st.caption(f'📡 {len(vtos_reales)} vencimientos disponibles para {ticker.strip().upper()}.')
            else:
                vto = st.date_input('Vencimiento', value=st.session_state['opc_vto'] or date.today(),
                                     min_value=date.today(), key='opc_vto_input')
                if ticker:
                    st.caption('⚠️ Yahoo Finance no tiene cadena de opciones publicada para este ticker '
                               '(común en algunos ADRs/CEDEARs). Carga manual de precios.')
        with c4:
            r = st.number_input('Tasa de interés anual (decimal)', min_value=0.0, max_value=3.0,
                                 value=float(st.session_state['opc_r']), step=0.01, format='%.4f', key='opc_r_input')
        with c5:
            q = st.number_input('Dividend yield anual (decimal)', min_value=0.0, max_value=1.0,
                                 value=float(st.session_state['opc_q']), step=0.001, format='%.4f', key='opc_q_input')

        datos_activo = None
        if ticker:
            with st.spinner(f'Descargando datos de {ticker}...'):
                datos_activo = _opc_datos_activo(ticker.strip().upper())
            if datos_activo is None:
                st.warning(f'No se encontraron datos para {ticker}. Verificá el símbolo.')
            else:
                if datos_activo.get('q_sugerido') is not None:
                    st.caption(f"💡 Dividend yield sugerido por Yahoo Finance: {datos_activo['q_sugerido']:.2%} "
                               f"(ajustá arriba si querés usarlo)")
                cm1, cm2, cm3, cm4 = st.columns(4)
                with cm1: st.metric('Precio', fmt_precio_opc(datos_activo['S']), help=datos_activo['fuente'])
                with cm2: st.metric('Vol. Histórica (40d)', f"{datos_activo['vol_hist']:.2%}")
                with cm3: st.metric('RSI', f"{datos_activo['rsi']:.1f}")
                with cm4: st.metric('SMA20', fmt_precio_opc(datos_activo['sma20']))

        mult = st.number_input('Multiplicador de contrato (100 = 1 contrato representa 100 acciones; '
                                'poné 1 si tu bróker ya muestra el costo total)',
                                min_value=1, value=int(st.session_state['opc_mult']), step=1, key='opc_mult_input')

        st.session_state['opc_ticker'] = ticker
        st.session_state['opc_vto'] = vto
        st.session_state['opc_r'] = r
        st.session_state['opc_q'] = q
        st.session_state['opc_estilo'] = estilo
        st.session_state['opc_mult'] = mult

    if not st.session_state['opc_ticker']:
        st.info('Ingresá un ticker para continuar.')
        return

    datos_activo = _opc_datos_activo(st.session_state['opc_ticker'].strip().upper())
    if datos_activo is None:
        st.error('No se pudieron obtener datos del activo. Revisá el ticker.')
        return

    S = datos_activo['S']
    vol_hist = datos_activo['vol_hist']
    dias_vto = max((st.session_state['opc_vto'] - date.today()).days, 1)
    T = dias_vto / 365
    r, q, estilo, mult = st.session_state['opc_r'], st.session_state['opc_q'], st.session_state['opc_estilo'], st.session_state['opc_mult']

    # ── PASO 2: elegir estrategia ────────────────────────────────────────
    st.markdown('---')
    st.markdown('### 2️⃣ Elegí la estrategia')

    sesgo_tabs = st.tabs(['📈 Alcistas', '📉 Bajistas', '➡️ Neutrales'])
    sesgo_map = {'📈 Alcistas': 'alcista', '📉 Bajistas': 'bajista', '➡️ Neutrales': 'neutral'}
    estrategia = None
    for tab, (label, sesgo) in zip(sesgo_tabs, sesgo_map.items()):
        with tab:
            opciones = [e for e in CATALOGO_ESTRATEGIAS if e['sesgo'] == sesgo]
            nombres = [e['nombre'] for e in opciones]
            idx_actual = 0
            if st.session_state['opc_estrategia_id']:
                actual = next((i for i, e in enumerate(opciones) if e['id'] == st.session_state['opc_estrategia_id']), None)
                if actual is not None: idx_actual = actual
            sel = st.radio(f'Estrategias {label.lower()}', nombres, index=idx_actual if opciones else 0,
                            key=f'opc_radio_{sesgo}', label_visibility='collapsed')
            if sel:
                est_candidato = next(e for e in opciones if e['nombre'] == sel)
                st.markdown(f"<div style='font-size:12px;color:#b0bcd0;background:#0d1117;border:1px solid #21262d;"
                            f"border-radius:8px;padding:10px 14px;margin-top:8px'>{est_candidato['descripcion']}</div>",
                            unsafe_allow_html=True)
                _id_candidato = est_candidato['id']
                if st.button(f"✅ Usar '{sel}'", key=f'opc_usar_{sesgo}_{_id_candidato}'):
                    st.session_state['opc_estrategia_id'] = est_candidato['id']
                    st.session_state['opc_calculado'] = False
                    st.rerun()

    if not st.session_state['opc_estrategia_id']:
        st.info('Elegí una estrategia y tocá "Usar" para continuar.')
        return

    estrategia = next(e for e in CATALOGO_ESTRATEGIAS if e['id'] == st.session_state['opc_estrategia_id'])
    st.success(f"Estrategia activa: **{estrategia['nombre']}** — {estrategia['descripcion']}")

    # ── PASO 3: cargar patas (strike, bid, ask) ─────────────────────────
    st.markdown('---')
    st.markdown('### 3️⃣ Cargá Strike, Bid y Ask de cada pata')

    vencimiento_str = st.session_state['opc_vto'].strftime('%Y-%m-%d')
    cadena_disponible = vencimiento_str in vtos_reales if vtos_reales else False
    cadena = _opc_cadena_opciones(st.session_state['opc_ticker'].strip().upper(), vencimiento_str) \
        if cadena_disponible else None

    if cadena_disponible and cadena:
        with st.expander('📡 Ver cadena completa de opciones (Yahoo Finance)', expanded=False):
            render_tabla_cadena_opciones(cadena, S)
    elif vtos_reales and not cadena_disponible:
        st.caption('⚠️ El vencimiento elegido no está en la cadena real — carga manual para todas las patas.')

    patas_input = []
    cols_patas = st.columns(len(estrategia['patas']))
    strikes_previos = {}
    for i, (col, spec) in enumerate(zip(cols_patas, estrategia['patas'])):
        with col:
            tipo_txt = 'Call' if spec['tipo'] == 'C' else 'Put'
            accion_txt = 'COMPRÁS' if spec['accion'] == 'comprar' else 'VENDÉS'
            st.markdown(f"**Pata {i+1}: {tipo_txt} — {accion_txt}**")

            lado_df = None
            if cadena and spec.get('mismo_strike_que') is None:
                lado_df = cadena['calls'] if spec['tipo'] == 'C' else cadena['puts']

            usar_cadena_pata = False
            if lado_df is not None and not lado_df.empty:
                usar_cadena_pata = st.checkbox(f'Usar cadena real', value=True, key=f'opc_usar_cadena_{i}')

            if spec.get('mismo_strike_que') is not None:
                strike = strikes_previos[spec['mismo_strike_que']]
                st.caption(f'Mismo strike que pata {spec["mismo_strike_que"]+1}: {strike:.2f}')
                bid = st.number_input(f'Bid pata {i+1}', min_value=0.0, value=0.0, step=0.01, key=f'opc_bid_{i}')
                ask = st.number_input(f'Ask pata {i+1}', min_value=0.0, value=0.0, step=0.01, key=f'opc_ask_{i}')

            elif usar_cadena_pata:
                strikes_disp = lado_df['strike'].tolist()
                fila_atm = _opc_fila_strike_mas_cercano(lado_df, S)
                idx_def = strikes_disp.index(float(fila_atm['strike'])) if fila_atm is not None else 0
                strike = st.selectbox(f'Strike pata {i+1} (cadena real)', strikes_disp,
                                       index=idx_def, key=f'opc_strike_cadena_{i}')
                fila_sel = lado_df[lado_df['strike'] == strike].iloc[0]
                bid_def = float(fila_sel['bid']) if pd.notna(fila_sel['bid']) else 0.0
                ask_def = float(fila_sel['ask']) if pd.notna(fila_sel['ask']) else 0.0
                iv_txt = f"{fila_sel['impliedVolatility']:.1%}" if pd.notna(fila_sel['impliedVolatility']) else 'N/D'
                oi_txt = int(fila_sel['openInterest']) if pd.notna(fila_sel['openInterest']) else 0
                st.caption(f"IV mercado: {iv_txt} · OI: {oi_txt} · {'🟢 ITM' if fila_sel['inTheMoney'] else '⚪ OTM'}")
                bid = st.number_input(f'Bid pata {i+1}', min_value=0.0, value=bid_def, step=0.01, key=f'opc_bid_{i}')
                ask = st.number_input(f'Ask pata {i+1}', min_value=0.0, value=ask_def, step=0.01, key=f'opc_ask_{i}')

            else:
                strike = st.number_input(f'Strike pata {i+1}', min_value=0.01,
                                          value=round(S, 2), step=0.5, key=f'opc_strike_{i}')
                bid = st.number_input(f'Bid pata {i+1}', min_value=0.0, value=0.0, step=0.01, key=f'opc_bid_{i}')
                ask = st.number_input(f'Ask pata {i+1}', min_value=0.0, value=0.0, step=0.01, key=f'opc_ask_{i}')

            strikes_previos[i] = strike
            patas_input.append({'tipo': spec['tipo'], 'accion': spec['accion'], 'strike': strike,
                                 'bid': bid, 'ask': ask, 'precio_mercado': (bid + ask) / 2.0})

    calcular = st.button('▶ Calcular', type='primary', key='opc_btn_calcular')
    if calcular:
        if any(p['ask'] <= 0 for p in patas_input):
            st.error('Cargá Bid y Ask (> 0) de todas las patas antes de calcular.')
            return
        st.session_state['opc_calculado'] = True
        st.session_state['opc_patas_data'] = patas_input

    if not st.session_state.get('opc_calculado'):
        return

    patas = st.session_state['opc_patas_data']

    # ── CÁLCULOS ─────────────────────────────────────────────────────────
    filas = []
    for pata in patas:
        tipo, K, precio_mercado = pata['tipo'], pata['strike'], pata['precio_mercado']
        precio_teorico = float(precio_opcion(tipo, S, K, T, r, vol_hist, q, estilo))
        vol_impl, motivo_falla = volatilidad_implicita(tipo, S, K, T, r, precio_mercado, q, estilo)
        letras = calcular_griegas(tipo, S, K, T, r, vol_hist, q, estilo)
        lam = calcular_apalancamiento(letras['Delta'], S, precio_mercado)
        senal = generar_senal_operacion(precio_teorico, precio_mercado, vol_hist, vol_impl, motivo_falla)
        mid, spread_abs, spread_pct, senal_liq = evaluar_liquidez(pata['bid'], pata['ask'])
        accion_desc = 'comprada' if pata['accion'] == 'comprar' else 'vendida'
        tipo_desc = 'Call' if tipo == 'C' else 'Put'
        filas.append({
            'Pata': f'{tipo_desc} {accion_desc}', 'Strike': K, 'Bid': pata['bid'], 'Ask': pata['ask'],
            'Mid': round(mid, 2), 'Spread': round(spread_abs, 2),
            'Spread %': f'{spread_pct:.1%}' if not np.isnan(spread_pct) else 'N/D',
            'Liquidez': senal_liq, 'Precio Teórico': round(precio_teorico, 2),
            'Vol. Histórica': f'{vol_hist:.2%}',
            'Vol. Implícita': f'{vol_impl:.2%}' if not np.isnan(vol_impl) else 'N/D',
            'Delta': round(letras['Delta'], 3), 'Gamma': round(letras['Gamma'], 4),
            'Theta': round(letras['Theta'], 4), 'Vega': round(letras['Vega'], 4), 'Rho': round(letras['Rho'], 4),
            'Lambda': round(lam, 2) if not np.isnan(lam) else 'N/D', 'Señal': senal,
            '_tipo': tipo, '_strike': K, '_iv': vol_impl,
        })
    df_filas = pd.DataFrame(filas)

    st.markdown('---')
    st.markdown('### 📊 Valuación y liquidez de cada pata')
    st.dataframe(df_filas[['Pata', 'Strike', 'Bid', 'Ask', 'Mid', 'Spread', 'Spread %', 'Liquidez',
                            'Precio Teórico', 'Vol. Histórica', 'Vol. Implícita', 'Señal']],
                 use_container_width=True, hide_index=True)

    st.markdown('### 📊 Griegas de cada pata')
    st.dataframe(df_filas[['Pata', 'Delta', 'Gamma', 'Theta', 'Vega', 'Rho', 'Lambda']],
                 use_container_width=True, hide_index=True)

    ok_par, msg_par = verificar_paridad_put_call(filas)
    st.markdown(f"**⚖️ Paridad Put-Call:** {msg_par}" if ok_par else f"**⚖️ Paridad Put-Call:**\n\n{msg_par}")
    st.markdown(f"**📐 Skew:** {analizar_skew(filas, S)}")

    # ── liquidez y slippage de la estrategia ────────────────────────────
    costo_teorico = costo_neto_estrategia(patas)
    costo_real = costo_neto_real_estrategia(patas)
    slippage = costo_real - costo_teorico
    st.markdown('### 💧 Liquidez y slippage de la estrategia')
    cl1, cl2, cl3 = st.columns(3)
    with cl1: st.metric('Costo neto teórico (mid)', f'{costo_teorico:.2f}/acción')
    with cl2: st.metric('Costo neto real (bid/ask)', f'{costo_real:.2f}/acción')
    with cl3: st.metric('Slippage', f'{slippage:.2f}/acción', f'{slippage*mult:.2f} por contrato')
    patas_iliquidas = [f for f in filas if '🔴' in f['Liquidez'] or '🟠' in f['Liquidez']]
    if patas_iliquidas:
        st.warning('⚠️ Patas con liquidez media/baja — priorizá orden límite: ' +
                   ', '.join(f"{f['Pata']} K={f['Strike']}" for f in patas_iliquidas))
    else:
        st.success('✅ Todas las patas tienen buena liquidez.')

    # ── resultado de la estrategia completa ─────────────────────────────
    analisis = analizar_payoff_estrategia(patas)
    st.markdown('---')
    st.markdown(f'### 🎯 Resultado — {estrategia["nombre"]}')

    be_txt = ', '.join(f'{b:.2f}' for b in analisis['breakevens']) if analisis['breakevens'] else 'sin cruce por cero en el rango cargado'
    gan_txt = 'ILIMITADA ⬆️' if analisis['ganancia_ilimitada'] else f"{analisis['ganancia_max']:.2f} ({analisis['ganancia_max']*mult:.2f} x{mult})"
    per_txt = 'ILIMITADA ⬆️' if analisis['perdida_ilimitada'] else f"{analisis['perdida_max']:.2f} ({analisis['perdida_max']*mult:.2f} x{mult})"

    kc1, kc2, kc3 = st.columns(3)
    with kc1: st.metric('Break-even(s)', be_txt)
    with kc2: st.metric('Ganancia máxima', gan_txt)
    with kc3: st.metric('Pérdida máxima', per_txt)

    st.plotly_chart(fig_payoff(patas, S, analisis), use_container_width=True, key='opc_fig_payoff')

    # ── gestión de riesgo / tamaño de posición ──────────────────────────
    st.markdown('### 🛡️ Gestión de riesgo y tamaño de posición')
    cr1, cr2 = st.columns(2)
    with cr1:
        capital = st.number_input('Capital destinado a esta operación', min_value=1.0,
                                   value=float(st.session_state['opc_capital']), step=100.0, key='opc_capital_input')
    with cr2:
        pct_riesgo = st.slider('% máximo de riesgo sobre ese capital', 0.01, 1.00,
                                float(st.session_state['opc_pct_riesgo']), 0.01, key='opc_pct_riesgo_input')
    st.session_state['opc_capital'] = capital
    st.session_state['opc_pct_riesgo'] = pct_riesgo
    for linea in calcular_tamano_posicion(analisis, patas, capital, pct_riesgo, mult):
        st.markdown(f'- {linea}')

    # ── repricing y escenarios ───────────────────────────────────────────
    sigmas_por_pata = [f['_iv'] if not np.isnan(f['_iv']) else vol_hist for f in filas]

    st.markdown('---')
    st.markdown('### 💲 Repricing si el subyacente se mueve HOY (sin pasar tiempo)')
    st.plotly_chart(fig_repricing(patas, S, T, r, sigmas_por_pata, q, estilo, costo_teorico),
                     use_container_width=True, key='opc_fig_repricing')

    variaciones_tabla = [i / 100 for i in range(-10, 11, 2)]
    filas_esc = []
    for var in variaciones_tabla:
        S_T = S * (1 + var)
        fila = {'Var. %': f'{var:+.0%}', 'Subyacente': round(S_T, 2)}
        v_total = 0.0
        for i, (pata, sigma) in enumerate(zip(patas, sigmas_por_pata), start=1):
            try:
                precio_rep = float(precio_opcion(pata['tipo'], S_T, pata['strike'], T, r, sigma, q, estilo))
            except Exception:
                precio_rep = float('nan')
            fila[f'Pata {i}'] = round(precio_rep, 2)
            v_total += precio_rep if pata['accion'] == 'comprar' else -precio_rep
        fila['P&L hoy'] = round(v_total - costo_teorico, 2)
        fila['P&L vencimiento'] = round(payoff_total(patas, S_T), 2)
        filas_esc.append(fila)
    st.markdown('### 📋 Escenarios: precios repreciados, P&L hoy y P&L al vencimiento')
    st.dataframe(pd.DataFrame(filas_esc), use_container_width=True, hide_index=True)

    st.markdown('### 🧮 Sensibilidad de las griegas')
    st.plotly_chart(fig_griegas_sensibilidad(patas, S, T, r, sigmas_por_pata, q, estilo),
                     use_container_width=True, key='opc_fig_griegas')

    # ── simulador interactivo ────────────────────────────────────────────
    st.markdown('---')
    st.markdown('### 🎮 Simulador interactivo')
    st.caption('Movés el subyacente y los días transcurridos, y ves el precio repreciado, griegas y P&L al instante '
               '(separando el efecto del precio del efecto del paso del tiempo — Theta).')

    sc1, sc2 = st.columns(2)
    with sc1:
        var_sim = st.slider('Variación del subyacente (%)', -30.0, 30.0, 0.0, 0.5, key='opc_sim_var') / 100
    with sc2:
        dias_sim = st.slider('Días transcurridos', 0, dias_vto, 0, key='opc_sim_dias')

    S_T_sim = S * (1 + var_sim)
    T_nuevo = max(dias_vto - dias_sim, 0) / 365
    st.caption(f"Subyacente: {S:.2f} → {S_T_sim:.2f} ({var_sim:+.2%})  ·  "
               f"Quedan {dias_vto - dias_sim} de {dias_vto} días al vencimiento")

    filas_sim = []
    valor_sin_tiempo = valor_con_tiempo = 0.0
    totales_g_sim = {g: 0.0 for g in NOMBRES_GRIEGAS}
    for pata, sigma in zip(patas, sigmas_por_pata):
        tipo_desc = 'Call' if pata['tipo'] == 'C' else 'Put'
        accion_desc = 'comprada' if pata['accion'] == 'comprar' else 'vendida'
        try:
            p_sin_t = precio_opcion(pata['tipo'], S_T_sim, pata['strike'], T, r, sigma, q, estilo)
            p_con_t = precio_opcion(pata['tipo'], S_T_sim, pata['strike'], T_nuevo, r, sigma, q, estilo)
            letras_sim = calcular_griegas(pata['tipo'], S_T_sim, pata['strike'], T_nuevo, r, sigma, q, estilo)
        except Exception:
            p_sin_t = p_con_t = float('nan')
            letras_sim = {g: float('nan') for g in NOMBRES_GRIEGAS}
        signo = 1 if pata['accion'] == 'comprar' else -1
        valor_sin_tiempo += signo * p_sin_t
        valor_con_tiempo += signo * p_con_t
        for g in NOMBRES_GRIEGAS: totales_g_sim[g] += signo * letras_sim[g]
        filas_sim.append({
            'Pata': f'{tipo_desc} {accion_desc} K={pata["strike"]:.2f}',
            'Precio (sin pasar tiempo)': round(p_sin_t, 2),
            f'Precio ({dias_sim}d pasados)': round(p_con_t, 2),
            'Efecto tiempo ($)': round(p_con_t - p_sin_t, 2),
            'Delta': round(letras_sim['Delta'], 3), 'Gamma': round(letras_sim['Gamma'], 4),
            'Theta': round(letras_sim['Theta'], 4), 'Vega': round(letras_sim['Vega'], 4),
            'Rho': round(letras_sim['Rho'], 4),
        })
    st.dataframe(pd.DataFrame(filas_sim), use_container_width=True, hide_index=True)

    efecto_tiempo_total = valor_con_tiempo - valor_sin_tiempo
    pnl_sin_tiempo = valor_sin_tiempo - costo_teorico
    pnl_con_tiempo = valor_con_tiempo - costo_teorico
    pnl_vto = payoff_total(patas, S_T_sim)

    sm1, sm2, sm3 = st.columns(3)
    with sm1: st.metric('P&L sin pasar tiempo', f'{pnl_sin_tiempo:.2f}', f'x{mult}: {pnl_sin_tiempo*mult:.2f}')
    with sm2: st.metric(f'P&L con {dias_sim}d pasados', f'{pnl_con_tiempo:.2f}', f'x{mult}: {pnl_con_tiempo*mult:.2f}')
    with sm3: st.metric('P&L si fuera al vencimiento', f'{pnl_vto:.2f}', f'x{mult}: {pnl_vto*mult:.2f}')
    st.caption(f'💀 Efecto acumulado del paso del tiempo (Theta): {efecto_tiempo_total:.2f} por acción '
               f'(x{mult} = {efecto_tiempo_total*mult:.2f} por contrato)')

    gcols = st.columns(5)
    for gc, g in zip(gcols, NOMBRES_GRIEGAS):
        with gc:
            st.metric(f'{g} neto', f'{totales_g_sim[g]:.4f}')

    if st.button('🔄 Reiniciar (nueva estrategia / nuevas patas)', key='opc_reset'):
        for k in list(st.session_state.keys()):
            if k.startswith('opc_'):
                del st.session_state[k]
        st.rerun()
