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
N_SIMULACIONES_OPC = 3000          # trayectorias de la simulación Monte Carlo
VENTANA_VOL_CORTA_OPC = 40         # ruedas usadas para estimar la tendencia reciente


# True = las explicaciones debajo de cada gráfico aparecen abiertas; False = plegadas
EXPLICACIONES_ABIERTAS = True


def render_explicacion(titulo, contenido_md):
    """Bloque explicativo debajo de un gráfico: qué muestra, cómo leerlo y cómo usarlo."""
    with st.expander(f'📘 {titulo}', expanded=EXPLICACIONES_ABIERTAS):
        st.markdown(contenido_md)


def lectura_personalizada_gex(z, S):
    """Traduce los números actuales de GEX a frases en criollo."""
    L = []
    flip, cw, pw = z['flip'], z['call_wall'], z['put_wall']
    if flip:
        d = (S / flip - 1) * 100
        if d > 0:
            L.append(f"El precio actual ({S:,.2f}) está **{d:.1f}% por encima** del punto de cambio de gamma ({flip:,.2f}). "
                     f"Ese es tu colchón: mientras el precio se mantenga arriba, el régimen es de amortiguación. "
                     f"Si cae por debajo de {flip:,.2f}, el mercado pasa a amplificar los movimientos.")
        else:
            L.append(f"El precio actual ({S:,.2f}) está **{abs(d):.1f}% por debajo** del punto de cambio de gamma ({flip:,.2f}). "
                     f"Ya estamos en régimen de amplificación: los movimientos tienden a ser más bruscos. "
                     f"Recuperar {flip:,.2f} devolvería el efecto amortiguador.")
    else:
        L.append("No hay punto de cambio de gamma dentro del rango analizado (±15% del precio): el régimen es "
                 f"**{z['regimen']}** en todo ese rango, así que no hay un nivel cercano donde cambie.")
    if cw:
        dc = (cw / S - 1) * 100
        pos = "por encima" if dc > 0 else "por debajo"
        L.append(f"La **pared de Calls ({cw:,.2f})** está {abs(dc):.1f}% {pos} del precio. "
                 f"Es el nivel donde más gamma de calls se concentra: suele comportarse como imán o resistencia.")
    if pw:
        dp = (pw / S - 1) * 100
        pos = "por encima" if dp > 0 else "por debajo"
        L.append(f"La **pared de Puts ({pw:,.2f})** está {abs(dp):.1f}% {pos} del precio. "
                 f"Es el nivel donde más gamma de puts se concentra: suele comportarse como soporte, "
                 f"y si se pierde, la caída puede acelerarse.")
    return L


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
    """Precio, volatilidad histórica, rendimiento por dividendos sugerido, RSI, media móvil de 20 ruedas."""
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

@st.cache_data(ttl=1800, show_spinner=False)
def _opc_serie_precios_completa(ticker, periodo='2y'):
    """Serie completa de cierres — insumo del Monte Carlo y del rango empírico histórico.
    Se cachea aparte de _opc_datos_activo porque esta devuelve la serie entera, no solo
    los estadísticos agregados."""
    try:
        import yfinance as yf
        df = yf.download(ticker, period=periodo, interval='1d', auto_adjust=True, progress=False)
        if df is None or df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        precios = df['Close'].dropna()
        if len(precios) < 30: return None
        return precios
    except Exception:
        return None


# ==============================================================
#  CADENA DE OPCIONES REAL (Yahoo Finance)
# ==============================================================

@st.cache_data(ttl=900, show_spinner=False)
def _opc_vencimientos_disponibles(ticker):
    """Fechas de vencimiento reales que Yahoo Finance tiene publicadas para el símbolo."""
    try:
        import yfinance as yf
        vtos = yf.Ticker(ticker).options
        return list(vtos) if vtos else []
    except Exception:
        return []


@st.cache_data(ttl=900, show_spinner=False)
def _opc_cadena_opciones(ticker, vencimiento):
    """Descarga la cadena de opciones (calls y puts) de Yahoo Finance para un símbolo
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
    """Dado un DataFrame de calls o puts y un precio de ejercicio de referencia (ej. el precio actual),
    devuelve la fila cuyo precio de ejercicio está más cerca — útil para pre-seleccionar en el dinero."""
    if df_lado is None or df_lado.empty:
        return None
    idx = (df_lado['strike'] - strike_objetivo).abs().idxmin()
    return df_lado.loc[idx]


def render_tabla_cadena_opciones(cadena, S, tipo=None):
    """Muestra calls y/o puts de la cadena real, resaltando el precio de ejercicio más cercano
    al precio actual y formateando compra/venta/vol. implícita/volumen para lectura rápida."""
    if cadena is None:
        st.warning('No se pudo descargar la cadena de opciones para este vencimiento.')
        return

    def _fmt_df(df):
        d = df.copy()
        d['Dentro del dinero'] = d['inTheMoney'].map({True: '🟢 Dentro del dinero', False: '⚪ Fuera del dinero'})
        d['Vol. implícita'] = d['impliedVolatility'].apply(lambda v: f'{v:.1%}' if pd.notna(v) else 'N/D')
        d['Compra'] = d['bid'].apply(lambda v: f'{v:.2f}' if pd.notna(v) else 'N/D')
        d['Venta'] = d['ask'].apply(lambda v: f'{v:.2f}' if pd.notna(v) else 'N/D')
        d['Último'] = d['lastPrice'].apply(lambda v: f'{v:.2f}' if pd.notna(v) else 'N/D')
        d['Vol.'] = d['volume'].fillna(0).astype(int)
        d['Interés abierto'] = d['openInterest'].fillna(0).astype(int)
        return d[['strike', 'Último', 'Compra', 'Venta', 'Vol.', 'Interés abierto', 'Vol. implícita', 'Dentro del dinero']].rename(columns={'strike': 'Precio de ejercicio'})

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
    if spread_vol > TOLERANCIA_VOL and sobre > 0: return "🔴 CARA (vol. implícita alta y precio mercado > teórico)"
    if spread_vol < -TOLERANCIA_VOL and sobre < 0: return "🟢 BARATA (vol. implícita baja y precio mercado < teórico)"
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
#  ANÁLISIS PROBABILÍSTICO — Monte Carlo, rango empírico y señal
#  (adaptado del script standalone de Colab a Streamlit nativo)
# ==============================================================

def simular_monte_carlo_opc(S0, sigma, drift, dias, n_sims=N_SIMULACIONES_OPC, seed=42):
    """GBM vectorizado. 'Tendencia' es el retorno esperado anualizado del mundo real (no neutral al riesgo),
    a diferencia de la valuación Black-Scholes/Binomial que usa la tasa libre de riesgo."""
    dt_ = 1 / 365
    pasos = max(int(dias), 1)
    rng = np.random.default_rng(seed)
    ruido = rng.standard_normal((pasos, n_sims))
    log_ret = (drift - 0.5 * sigma ** 2) * dt_ + sigma * np.sqrt(dt_) * ruido
    log_path = np.cumsum(log_ret, axis=0)
    sims = S0 * np.exp(log_path)
    return np.vstack([np.full(n_sims, S0), sims])


def rango_empirico_opc(precios, S0, dias, p_bajo=40, p_alto=60):
    """Rango percentil 40-60 de los retornos log históricos observados a 'dias' de distancia."""
    retornos_T = np.log(precios.shift(-dias) / precios).dropna()
    if len(retornos_T) < 20:
        return None, None, len(retornos_T)
    r_bajo = np.percentile(retornos_T, p_bajo)
    r_alto = np.percentile(retornos_T, p_alto)
    return float(S0 * np.exp(r_bajo)), float(S0 * np.exp(r_alto)), len(retornos_T)


def sigma_desde_rango_opc(precio_bajo, precio_alto, t_frac, p_bajo=40, p_alto=60):
    z = norm.ppf(p_alto / 100) - norm.ppf(p_bajo / 100)
    return float(np.log(precio_alto / precio_bajo) / (z * np.sqrt(t_frac)))


def sugerir_alternativas_opcion(checks, accion, tipo, precio_mercado, precio_teorico):
    """Sugerencias tipo 'Qué mirar en cambio', una por cada chequeo que falló,
    redactadas según si la opción se compra o se vende."""
    sugerencias = []
    verbo = 'comprar' if accion == 'comprar' else 'vender'

    if not checks['iv']['ok']:
        if accion == 'comprar':
            sugerencias.append("La vol. implícita está relativamente inflada frente a la referencia → buscá un precio de ejercicio o "
                                "vencimiento con vol. implícita más alineada, o evaluá vender prima en vez de comprar.")
        else:
            sugerencias.append("La vol. implícita está relativamente comprimida frente a la referencia → vender acá deja "
                                "poca prima; buscá un precio de ejercicio/vencimiento con más vol. implícita, o evaluá comprar en su lugar.")

    if not checks['tendencia']['ok']:
        sugerencias.append(f"La tendencia de corto plazo (media móvil de 20 ruedas) no acompaña esta opción para {verbo} → "
                            f"esperá una confirmación de tendencia antes de entrar, o reconsiderá el sesgo.")

    if not checks['momentum']['ok']:
        sugerencias.append("El momentum (RSI) está débil para esta dirección → esperá una mejora del RSI, "
                            "o reducí el tamaño de la posición si igual querés entrar.")

    if not checks['delta']['ok']:
        sugerencias.append("El Delta está fuera de la zona en el dinero ideal (0.4-0.6) → probá un precio de ejercicio más cercano "
                            "al precio actual para mejor apalancamiento, o aceptá el perfil más direccional/especulativo.")

    if not checks['precio']['ok']:
        diff_pct = abs(precio_mercado - precio_teorico) / precio_teorico * 100 if precio_teorico > 0 else 0.0
        if accion == 'comprar':
            sugerencias.append(f"Estás pagando {diff_pct:.1f}% más de lo que el modelo considera valor justo "
                                f"(${precio_teorico:,.2f} vs ${precio_mercado:,.2f} de mercado) → esperá que "
                                f"baje la prima, buscá otro precio de ejercicio/vencimiento, o evaluá vender en vez de comprar.")
        else:
            sugerencias.append(f"Estás cobrando {diff_pct:.1f}% menos de lo que el modelo considera valor justo "
                                f"(${precio_teorico:,.2f} vs ${precio_mercado:,.2f} de mercado) → buscá un precio de ejercicio "
                                f"con mejor prima, o evaluá comprar en vez de vender.")

    if not checks['monte_carlo']['ok']:
        sugerencias.append("Según el Monte Carlo, la probabilidad de que el precio favorezca a esta opción es "
                            "menor al 45% → la estadística del activo no acompaña esta opción en particular. "
                            "Considerá un precio de ejercicio más cercano al precio actual, o esperá a que el escenario se corra a favor.")

    return sugerencias


def evaluar_señal_opcion(tipo, accion, S, vol_hist, vol_empirica, vol_implicita,
                        precio_teorico, precio_mercado, delta, rsi, sma20,
                        prob_mc_favorable, tolerancia=TOLERANCIA_VOL):
    """6 chequeos independientes, adaptados según si la opción se COMPRA o se VENDE.
    'Favorable' siempre significa: a favor del resultado de ESTA opción en particular,
    no de la estrategia completa (eso ya lo cubren el perfil de resultado y los puntos de equilibrio).
    Devuelve también color (para la tarjeta HTML) y sugerencias tipo 'Qué mirar en cambio'."""
    es_alcista_favorable = (tipo == 'C' and accion == 'comprar') or (tipo == 'P' and accion == 'vender')
    vol_referencia = np.nanmean([vol_hist, vol_empirica]) if not np.isnan(vol_empirica) else vol_hist
    spread_iv = (vol_implicita - vol_referencia) if not np.isnan(vol_implicita) else 0.0
    sobrevaloracion = precio_mercado - precio_teorico

    if accion == 'comprar':
        ok_iv = (vol_implicita < vol_referencia + tolerancia) if not np.isnan(vol_implicita) else False
        ok_precio = precio_mercado < precio_teorico
        txt_iv = 'Vol. implícita relativamente barata (favorable para comprar)'
        txt_precio = 'Precio de mercado < precio justo (no pagás de más)'
    else:
        ok_iv = (vol_implicita > vol_referencia - tolerancia) if not np.isnan(vol_implicita) else False
        ok_precio = precio_mercado > precio_teorico
        txt_iv = 'Vol. implícita relativamente cara (favorable para vender)'
        txt_precio = 'Precio de mercado > precio justo (cobrás de más)'

    if es_alcista_favorable:
        ok_tendencia, ok_momentum = S > sma20, rsi > 50
        txt_tendencia, txt_momentum = 'Tendencia (precio sobre media móvil de 20 ruedas) a favor', 'Impulso (RSI > 50) a favor'
    else:
        ok_tendencia, ok_momentum = S < sma20, rsi < 50
        txt_tendencia, txt_momentum = 'Tendencia (precio bajo media móvil de 20 ruedas) a favor', 'Impulso (RSI < 50) a favor'

    ok_delta = 0.4 <= abs(delta) <= 0.6
    ok_mc = prob_mc_favorable > 45

    checks = {
        'iv': {'ok': bool(ok_iv), 'texto': txt_iv},
        'tendencia': {'ok': bool(ok_tendencia), 'texto': txt_tendencia},
        'momentum': {'ok': bool(ok_momentum), 'texto': txt_momentum},
        'delta': {'ok': bool(ok_delta), 'texto': 'Delta en zona 0.4-0.6 (en el dinero, buen apalancamiento/gamma)'},
        'precio': {'ok': bool(ok_precio), 'texto': txt_precio},
        'monte_carlo': {'ok': bool(ok_mc), 'texto': 'Monte Carlo favorece esta opción (prob. > 45%)'},
    }
    puntaje = sum(1 for c in checks.values() if c['ok'])

    if puntaje == 6:
        veredicto = f"🟢 {'COMPRAR' if accion == 'comprar' else 'VENDER'}"
        color, alternativas = ('#1e7e34', '#d4f4dd'), []
    elif accion == 'comprar' and spread_iv > 0.15 and sobrevaloracion > 0 and abs(delta) > 0.6:
        veredicto = "🟠 CONSIDERAR VENDER EN SU LUGAR"
        color = ('#8a5a00', '#fff3cd')
        alternativas = sugerir_alternativas_opcion(checks, accion, tipo, precio_mercado, precio_teorico)
    elif accion == 'vender' and spread_iv < -0.15 and sobrevaloracion < 0 and abs(delta) > 0.6:
        veredicto = "🟠 CONSIDERAR COMPRAR EN SU LUGAR"
        color = ('#8a5a00', '#fff3cd')
        alternativas = sugerir_alternativas_opcion(checks, accion, tipo, precio_mercado, precio_teorico)
    else:
        veredicto = "🔴 NO OPERAR (esta opción)"
        color = ('#a71d2a', '#fbdadd')
        alternativas = sugerir_alternativas_opcion(checks, accion, tipo, precio_mercado, precio_teorico)

    return {'veredicto': veredicto, 'puntaje': puntaje, 'checks': checks, 'color': color,
            'alternativas': alternativas, 'prob_mc_favorable': prob_mc_favorable}


def render_veredicto_opcion_html(resultado):
    """Tarjeta HTML con el veredicto, los 6 chequeos y 'Qué mirar en cambio' — mismo
    estilo que el resumen del script de Colab, adaptado a la paleta oscura de la app."""
    color_texto, color_fondo = resultado['color']

    filas_checks = ""
    for c in resultado['checks'].values():
        icono = "✔" if c['ok'] else "✘"
        color_icono = "#3fb950" if c['ok'] else "#f85149"
        filas_checks += f"""
        <tr>
          <td style="padding:6px 10px;color:{color_icono};font-weight:bold;text-align:center;width:26px;">{icono}</td>
          <td style="padding:6px 10px;color:#e6edf3;font-size:12.5px;">{c['texto']}</td>
        </tr>"""

    filas_alt = ""
    if resultado['alternativas']:
        items = "".join(f"<li style='margin-bottom:6px;'>{a}</li>" for a in resultado['alternativas'])
        filas_alt = f"""
        <div style="margin-top:12px;padding:12px 16px;background:#161b22;border-left:4px solid #6b7d9a;border-radius:4px;">
          <div style="font-weight:bold;color:#e6edf3;margin-bottom:6px;font-size:13px;">Qué mirar en cambio:</div>
          <ul style="margin:0;padding-left:20px;color:#b0bcd0;font-size:12.5px;line-height:1.5;">{items}</ul>
        </div>"""

    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;border:1px solid #21262d;border-radius:10px;overflow:hidden;margin-top:6px;">
      <div style="padding:14px 18px;background:{color_fondo};text-align:center;">
        <div style="font-size:16px;font-weight:bold;color:{color_texto};letter-spacing:0.3px;">{resultado['veredicto']}</div>
        <div style="font-size:12.5px;color:{color_texto};margin-top:4px;">{resultado['puntaje']}/6 condiciones</div>
      </div>
      <div style="padding:12px 16px;background:#0d1117;">
        <table style="width:100%;border-collapse:collapse;background:#0d1117;">{filas_checks}</table>
        {filas_alt}
      </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def fig_monte_carlo_distribucion(precios_finales, S, strikes, p40_mc, p60_mc, p40_emp=None, p60_emp=None):
    """Histograma Monte Carlo. Las líneas de referencia van como trazas con leyenda propia
    (en vez de anotaciones flotantes) para que no se pisen las etiquetas cuando los valores
    quedan muy cerca entre sí en el eje X."""
    counts, _ = np.histogram(precios_finales, bins=60)
    y_top = float(counts.max()) * 1.08 if len(counts) else 1.0

    fig = go.Figure()
    fig.add_trace(go.Histogram(x=precios_finales, nbinsx=60, marker_color=C_ACENT,
                                opacity=0.75, name='Precios simulados', showlegend=False))

    def _linea_vertical(x, color, dash, nombre):
        fig.add_trace(go.Scatter(x=[x, x], y=[0, y_top], mode='lines',
                                  line=dict(color=color, dash=dash, width=1.6),
                                  name=f'{nombre} ({x:,.2f})', hoverinfo='skip'))

    _linea_vertical(S, C_YELL, 'dot', 'Precio actual')
    _linea_vertical(p40_mc, C_MUTED, 'dash', 'Monte Carlo 40%')
    _linea_vertical(p60_mc, C_MUTED, 'dash', 'Monte Carlo 60%')
    if p40_emp is not None:
        _linea_vertical(p40_emp, C_GREEN, 'dashdot', 'Emp. 40%')
        _linea_vertical(p60_emp, C_GREEN, 'dashdot', 'Emp. 60%')
    for k in sorted(set(strikes)):
        _linea_vertical(k, C_RED, 'dot', f'Precio de ejercicio {k:,.2f}')

    fig.update_layout(**PLOTLY_LAYOUT_OPC, height=430, showlegend=True,
                       legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0,
                                   font=dict(size=10.5, color=C_TEXT)),
                       title=dict(text='Distribución Monte Carlo del mundo real al vencimiento',
                                  font=dict(color=C_TEXT, size=13), y=0.98),
                       xaxis=dict(title='Precio del subyacente', gridcolor=C_GRID),
                       yaxis=dict(title='Frecuencia', gridcolor=C_GRID, range=[0, y_top]),
                       margin=dict(l=10, r=10, t=90, b=10))
    return fig


# ==============================================================
#  GEX — Gamma Exposure, Gamma Flip y zonas
# ==============================================================

def _gamma_bs_vec(S, K, T, r, sigma, q=0.0):
    """Gamma Black-Scholes vectorizado (acepta arrays / broadcasting)."""
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    return np.exp(-q * T) * norm.pdf(d1) / (S * sigma * np.sqrt(T))


@st.cache_data(ttl=900, show_spinner=False)
def _opc_gex_base(ticker, max_vtos=6):
    """Cadena de los próximos vencimientos en un solo DataFrame largo (precio de ejercicio, tipo, interés abierto, vol. implícita, T)."""
    vtos = _opc_vencimientos_disponibles(ticker)[:max_vtos]
    partes = []
    for v in vtos:
        cad = _opc_cadena_opciones(ticker, v)
        if not cad:
            continue
        dias = max((datetime.strptime(v, '%Y-%m-%d').date() - date.today()).days, 0)
        T = max(dias, 0.5) / 365          # piso para que 0DTE no rompa la división
        for tipo, key in (('C', 'calls'), ('P', 'puts')):
            d = cad[key][['strike', 'openInterest', 'impliedVolatility']].copy()
            d['tipo'], d['T'], d['vto'] = tipo, T, v
            partes.append(d)
    if not partes:
        return None
    df = pd.concat(partes, ignore_index=True).dropna(subset=['openInterest', 'impliedVolatility'])
    df = df[(df['openInterest'] > 0) & (df['impliedVolatility'] > 0.01)]   # filtra IV basura de Yahoo
    return df.reset_index(drop=True) if not df.empty else None


def calcular_gex_por_strike(df, S, r, q, mult=100, rango=0.20):
    """GEX neto por precio de ejercicio, separado en calls (+) y puts (−). Solo precios de ejercicio dentro de ±rango del precio actual."""
    g = _gamma_bs_vec(S, df['strike'].values, df['T'].values, r, df['impliedVolatility'].values, q)
    signo = np.where(df['tipo'] == 'C', 1.0, -1.0)
    d = df.copy()
    d['gex'] = signo * g * d['openInterest'] * mult * S ** 2 * 0.01
    d = d[(d['strike'] >= S * (1 - rango)) & (d['strike'] <= S * (1 + rango))]
    if d.empty:
        return pd.DataFrame(columns=['strike', 'gex_calls', 'gex_puts', 'neto'])
    piv = d.pivot_table(index='strike', columns='tipo', values='gex', aggfunc='sum').fillna(0.0)
    for c in ('C', 'P'):
        if c not in piv.columns:
            piv[c] = 0.0
    piv['neto'] = piv['C'] + piv['P']
    return piv.reset_index().rename(columns={'C': 'gex_calls', 'P': 'gex_puts'})


def gex_total_vs_spot(df, S, r, q, mult=100, rango=0.15, n=121):
    """GEX total recalculado sobre una grilla de precios → sirve para ubicar el punto de cambio de gamma."""
    grid = np.linspace(S * (1 - rango), S * (1 + rango), n)
    K, T, iv = (df[c].values[None, :] for c in ('strike', 'T', 'impliedVolatility'))
    oi = df['openInterest'].values[None, :]
    signo = np.where(df['tipo'].values == 'C', 1.0, -1.0)[None, :]
    g = _gamma_bs_vec(grid[:, None], K, T, r, iv, q)
    total = (g * signo * oi * mult * grid[:, None] ** 2 * 0.01).sum(axis=1)
    return grid, total


def encontrar_gamma_flip(grid, total, S):
    """Cruce por cero (interpolado) más cercano al precio actual. None si no hay cruce en el rango."""
    cruces = np.where(np.sign(total[:-1]) * np.sign(total[1:]) < 0)[0]
    if len(cruces) == 0:
        return None
    i = cruces[np.argmin(np.abs(grid[cruces] - S))]
    return float(grid[i] - total[i] * (grid[i + 1] - grid[i]) / (total[i + 1] - total[i]))


def calcular_zonas_gex(piv, grid, total, S):
    flip = encontrar_gamma_flip(grid, total, S)
    call_wall = float(piv.loc[piv['gex_calls'].idxmax(), 'strike']) if (piv['gex_calls'] > 0).any() else None
    put_wall = float(piv.loc[piv['gex_puts'].idxmin(), 'strike']) if (piv['gex_puts'] < 0).any() else None
    gex_total_spot = float(np.interp(S, grid, total))
    if flip is None:
        regimen = 'positivo' if gex_total_spot > 0 else 'negativo'
    else:
        regimen = 'positivo' if S > flip else 'negativo'
    return dict(flip=flip, call_wall=call_wall, put_wall=put_wall,
                gex_total=gex_total_spot, regimen=regimen)


def fig_gex(piv, zonas, S):
    y_max = float(max(piv['gex_calls'].max(), abs(piv['gex_puts'].min()), 1.0)) * 1.1
    x_min, x_max = float(piv['strike'].min()), float(piv['strike'].max())
    fig = go.Figure()

    # zonas de fondo: gamma negativa (rojo) / positiva (verde) según el flip
    flip = zonas['flip']
    if flip is not None:
        fig.add_vrect(x0=x_min, x1=min(max(flip, x_min), x_max), fillcolor='rgba(248,81,73,0.08)', line_width=0)
        fig.add_vrect(x0=min(max(flip, x_min), x_max), x1=x_max, fillcolor='rgba(63,185,80,0.08)', line_width=0)
    else:
        col = 'rgba(63,185,80,0.08)' if zonas['regimen'] == 'positivo' else 'rgba(248,81,73,0.08)'
        fig.add_vrect(x0=x_min, x1=x_max, fillcolor=col, line_width=0)

    fig.add_trace(go.Bar(x=piv['strike'], y=piv['gex_calls'], marker_color=C_GREEN, name='GEX Calls', opacity=0.85))
    fig.add_trace(go.Bar(x=piv['strike'], y=piv['gex_puts'], marker_color=C_RED, name='GEX Puts', opacity=0.85))

    def _linea(x, color, dash, nombre):
        if x is None:
            return
        fig.add_trace(go.Scatter(x=[x, x], y=[-y_max, y_max], mode='lines',
                                 line=dict(color=color, dash=dash, width=1.8),
                                 name=f'{nombre} ({x:,.2f})', hoverinfo='skip'))
    _linea(S, C_YELL, 'dot', 'Precio actual')
    _linea(flip, '#bc8cff', 'dash', 'Punto de cambio de gamma')
    _linea(zonas['call_wall'], C_GREEN, 'dashdot', 'Pared de Calls')
    _linea(zonas['put_wall'], C_RED, 'dashdot', 'Pared de Puts')

    fig.update_layout(**PLOTLY_LAYOUT_OPC, height=460, barmode='relative',
                      title=dict(text='GEX por precio de ejercicio (USD por cada 1% de movimiento)', font=dict(color=C_TEXT, size=13), y=0.98),
                      legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0,
                                  font=dict(size=10.5, color=C_TEXT)),
                      xaxis=dict(title='Precio de ejercicio', gridcolor=C_GRID),
                      yaxis=dict(title='GEX ($ / 1%)', gridcolor=C_GRID),
                      margin=dict(l=10, r=10, t=90, b=10))
    return fig


def render_gex(ticker, S, r, q, mult=100):
    if not ticker:
        return
    c1, _ = st.columns([1, 2])
    with c1:
        n_vtos = st.slider('Vencimientos a incluir', 1, 12, 6, key='opc_gex_nvtos',
                           help='Más vencimientos = más panorama, pero los cercanos pesan mucho más (gamma alta).')
    st.caption(f'Tasa usada: {r:.2%} (la que cargaste en el paso 1).')
    df = _opc_gex_base(ticker, n_vtos)
    if df is None:
        st.warning('No hay cadena de opciones utilizable (interés abierto / vol. implícita) para este símbolo. '
                   'GEX necesita cadena real; no funciona con carga manual.')
        return

    piv = calcular_gex_por_strike(df, S, r, q, mult)
    if piv.empty:
        st.warning('No hay precios de ejercicio con interés abierto/vol. implícita utilizable cerca del precio actual para estos vencimientos.')
        return
    grid, total = gex_total_vs_spot(df, S, r, q, mult)
    z = calcular_zonas_gex(piv, grid, total, S)

    m1, m2, m3, m4 = st.columns(4)
    with m1: st.metric('GEX total (al precio actual)', f"{z['gex_total']/1e6:,.1f} millones de US$")
    with m2: st.metric('Punto de cambio de gamma', fmt_precio_opc(z['flip']) if z['flip'] else 'N/D')
    with m3: st.metric('Pared de Calls', fmt_precio_opc(z['call_wall']) if z['call_wall'] else 'N/D')
    with m4: st.metric('Pared de Puts', fmt_precio_opc(z['put_wall']) if z['put_wall'] else 'N/D')

    if z['regimen'] == 'positivo':
        st.success('🟢 **Zona gamma POSITIVA** — los creadores de mercado amortiguan el movimiento: más reversión a la media, '
                   'menor volatilidad realizada. Las paredes de Calls y Puts tienden a funcionar como imanes/límites.')
    else:
        st.error('🔴 **Zona gamma NEGATIVA** — los creadores de mercado amplifican el movimiento: más tendencia y volatilidad. '
                 'Perder la pared de Puts puede acelerar la caída.')

    render_explicacion('Cómo leer estos 4 indicadores', """
**Qué es cada uno**
- **GEX total (al precio actual):** el GEX es la *exposición gamma*: la suma de la gamma de todas las opciones, en dólares que los *creadores de mercado* deberían comprar o vender por cada 1% que se mueva el precio. Lo que importa es el **signo**: positivo = frenan el movimiento, negativo = lo aceleran. El tamaño no se compara entre distintos activos.
- **Punto de cambio de gamma:** el precio donde el GEX total pasa de negativo a positivo. Es la **frontera entre los dos regímenes**.
- **Pared de Calls:** el precio de ejercicio con más gamma de calls. Suele actuar como **techo o imán**.
- **Pared de Puts:** el precio de ejercicio con más gamma de puts. Suele actuar como **piso o soporte**.

**Cómo usarlo**
- Régimen **positivo** (verde): esperá mercado más tranquilo y de rango. Sirve para estrategias que ganan con el precio quieto (vender prima, Cóndor de hierro, Strangle vendido con cobertura).
- Régimen **negativo** (rojo): esperá movimientos más grandes y bruscos. Sirve para estrategias que ganan con movimiento (Straddle, Strangle) y hay que ser más cuidadoso con las que venden prima.
- Mirá la **distancia entre el precio y el punto de cambio de gamma**: cuanto más cerca, más probable un cambio de comportamiento.
""")

    st.plotly_chart(fig_gex(piv, z, S), use_container_width=True, key='opc_fig_gex')

    render_explicacion('Cómo leer el gráfico "GEX por precio de ejercicio" y cómo usarlo', """
**Qué muestra**
Cada barra es un precio de ejercicio. **Verde hacia arriba** = gamma de las calls. **Rojo hacia abajo** = gamma de las puts. Cuanto más alta la barra, más peso tiene ese precio de ejercicio en las coberturas de los creadores de mercado. El fondo verde/rojo marca dónde rige cada régimen según el punto de cambio de gamma, y las líneas verticales marcan el precio actual (precio actual), el punto de cambio de gamma y las paredes.

**Cómo leerlo**
- Una **barra muy alta** es un nivel "pegajoso": el precio tiende a orbitar o detenerse cerca.
- Si el **precio actual está pegado a una barra grande**, el precio está en una zona de mucha influencia.
- Si las barras están **casi todas del lado de las calls**, el neto da positivo; si dominan las puts, da negativo.
- Zonas **sin barras** = casi sin influencia de opciones: el precio se mueve más libre ahí.

**Cómo sacarle provecho**
- Usá los precios de ejercicio con barras grandes como **referencias** para elegir precios de ejercicio vendidos (por ejemplo, vender una Call por encima de la pared de Calls o una Put por debajo de la pared de Puts).
- Si el precio se acerca a la pared de Puts desde arriba, prestá atención: perderla puede acelerar la caída.
- Combinalo siempre con el resto del análisis (tendencia, volatilidad, perfil de resultado). **No es una señal de compra o venta por sí solo.**
""")

    st.markdown('**Lectura con los datos de hoy:**')
    for _linea in lectura_personalizada_gex(z, S):
        st.markdown(f'- {_linea}')

    fig_flip = go.Figure(go.Scatter(x=grid, y=total / 1e6, line=dict(color=C_ACENT, width=2.2)))
    fig_flip.add_hline(y=0, line_color=C_MUTED, opacity=0.6)
    fig_flip.add_vline(x=S, line_dash='dot', line_color=C_YELL, opacity=0.7)
    if z['flip']:
        fig_flip.add_vline(x=z['flip'], line_dash='dash', line_color='#bc8cff', opacity=0.8)
    fig_flip.update_layout(**PLOTLY_LAYOUT_OPC, height=300,
                           title=dict(text='GEX total vs precio del subyacente (el cruce por 0 es el punto de cambio de gamma)',
                                      font=dict(color=C_TEXT, size=13)),
                           xaxis=dict(title='Precio', gridcolor=C_GRID),
                           yaxis=dict(title='GEX total (millones de US$ / 1%)', gridcolor=C_GRID),
                           margin=dict(l=10, r=10, t=45, b=10))
    st.plotly_chart(fig_flip, use_container_width=True, key='opc_fig_gex_flip')

    render_explicacion('Cómo leer el gráfico "GEX total vs precio" y cómo usarlo', """
**Qué muestra**
Responde a esta pregunta: *"si el activo estuviera en otro precio, ¿cuál sería el GEX total?"*. El eje horizontal es el precio hipotético y el vertical es el GEX total. La línea punteada amarilla es el precio actual y la violeta es el punto de cambio de gamma.

**Cómo leerlo**
- Donde la curva está **por encima de 0** = régimen positivo (los creadores de mercado amortiguan).
- Donde está **por debajo de 0** = régimen negativo (los creadores de mercado amplifican).
- El punto donde **cruza el cero** es el punto de cambio de gamma.
- Una curva que **cae rápido hacia el cero** al bajar el precio indica que el régimen es frágil: no hace falta una caída grande para cambiar de escenario.
- Los picos y pequeñas muescas suelen venir de muchos precios de ejercicio juntos o de datos ruidosos de Yahoo; no los tomes como niveles exactos.

**Cómo sacarle provecho**
- Es el gráfico ideal para responder *"¿cuánto tiene que moverse el precio para que cambie el comportamiento del mercado?"*.
- Si el precio está **lejos del punto de cambio y del lado positivo**, hay más margen para estrategias de rango.
- Si está **cerca del punto de cambio**, conviene achicar el tamaño o elegir estrategias con riesgo definido.
""")

    st.caption('⚠️ Asume creadores de mercado largos calls / cortos puts. Usa el interés abierto del día anterior y la vol. implícita de Yahoo (ruidosa en precios de ejercicio '
               'ilíquidos). Es una referencia de régimen, no una señal por sí sola.')

# ==============================================================
#  CATÁLOGO DE ESTRATEGIAS
# ==============================================================

CATALOGO_ESTRATEGIAS = [
    {"id": 1, "nombre": "Compra de Call", "sesgo": "alcista",
     "descripcion": "Comprás una Call. Ganás si el precio sube por encima del punto de equilibrio (precio de ejercicio + prima). Pérdida máxima = prima. Ganancia ilimitada.",
     "opciones": [{"tipo": "C", "accion": "comprar", "prompt": "Call que comprás"}]},
    {"id": 2, "nombre": "Vertical alcista con Calls", "sesgo": "alcista",
     "descripcion": "Comprás Call de precio de ejercicio bajo y vendés Call de precio de ejercicio alto. Baja costo y riesgo, ganancia limitada al ancho entre precios de ejercicio menos el débito.",
     "opciones": [{"tipo": "C", "accion": "comprar", "prompt": "Call COMPRADA (precio de ejercicio más bajo)"},
               {"tipo": "C", "accion": "vender", "prompt": "Call VENDIDA (precio de ejercicio más alto)"}]},
    {"id": 3, "nombre": "Vertical alcista con Puts (crédito)", "sesgo": "alcista",
     "descripcion": "Vendés Put de precio de ejercicio alto, comprás Put de precio de ejercicio bajo como cobertura. Cobrás crédito neto. Ganás si el precio queda arriba del precio de ejercicio vendido.",
     "opciones": [{"tipo": "P", "accion": "vender", "prompt": "Put VENDIDA (precio de ejercicio más alto)"},
               {"tipo": "P", "accion": "comprar", "prompt": "Put COMPRADA (precio de ejercicio más bajo, cobertura)"}]},
    {"id": 4, "nombre": "Put con garantía en efectivo", "sesgo": "alcista",
     "descripcion": "Vendés una Put reservando efectivo para comprar el subyacente si te asignan. Riesgo bajista grande si el precio se derrumba.",
     "opciones": [{"tipo": "P", "accion": "vender", "prompt": "Put que vendés"}]},
    {"id": 5, "nombre": "Comprar Call + Vender Put (Reversión de riesgo / Sintética)", "sesgo": "alcista",
     "descripcion": "Comprás Call y vendés Put. Mismo precio de ejercicio = sintética (como tener el subyacente, apalancado). Precios de ejercicio distintos = Reversión de riesgo. Pérdida potencial grande si cae fuerte.",
     "opciones": [{"tipo": "C", "accion": "comprar", "prompt": "Call que comprás"},
               {"tipo": "P", "accion": "vender", "prompt": "Put que vendés"}]},
    {"id": 6, "nombre": "Compra de Put", "sesgo": "bajista",
     "descripcion": "Comprás una Put. Ganás si el precio cae por debajo del punto de equilibrio (precio de ejercicio - prima). Pérdida máxima = prima.",
     "opciones": [{"tipo": "P", "accion": "comprar", "prompt": "Put que comprás"}]},
    {"id": 7, "nombre": "Vertical bajista con Puts", "sesgo": "bajista",
     "descripcion": "Comprás Put de precio de ejercicio alto y vendés Put de precio de ejercicio bajo. Ganancia limitada al ancho entre precios de ejercicio menos el débito pagado.",
     "opciones": [{"tipo": "P", "accion": "comprar", "prompt": "Put COMPRADA (precio de ejercicio más alto)"},
               {"tipo": "P", "accion": "vender", "prompt": "Put VENDIDA (precio de ejercicio más bajo)"}]},
    {"id": 8, "nombre": "Vertical bajista con Calls (crédito)", "sesgo": "bajista",
     "descripcion": "Vendés Call de precio de ejercicio bajo y comprás Call de precio de ejercicio alto como cobertura. Ganás si el precio queda debajo del precio de ejercicio vendido.",
     "opciones": [{"tipo": "C", "accion": "vender", "prompt": "Call VENDIDA (precio de ejercicio más bajo)"},
               {"tipo": "C", "accion": "comprar", "prompt": "Call COMPRADA (precio de ejercicio más alto, cobertura)"}]},
    {"id": 9, "nombre": "Straddle comprado", "sesgo": "neutral",
     "descripcion": "Comprás Call y Put del mismo precio de ejercicio (en el dinero). Ganás con movimiento fuerte en cualquier dirección; perdés si el precio queda quieto.",
     "opciones": [{"tipo": "C", "accion": "comprar", "prompt": "Call y Put (mismo precio de ejercicio) que comprás"},
               {"tipo": "P", "accion": "comprar", "prompt": None, "mismo_strike_que": 0}]},
    {"id": 10, "nombre": "Strangle comprado", "sesgo": "neutral",
     "descripcion": "Comprás Call fuera del dinero y Put fuera del dinero. Más barato que el Straddle, necesita movimiento más grande para ser rentable.",
     "opciones": [{"tipo": "C", "accion": "comprar", "prompt": "Call fuera del dinero (precio de ejercicio más alto)"},
               {"tipo": "P", "accion": "comprar", "prompt": "Put fuera del dinero (precio de ejercicio más bajo)"}]},
    {"id": 11, "nombre": "Strangle vendido", "sesgo": "neutral",
     "descripcion": "Vendés Call fuera del dinero y Put fuera del dinero cobrando ambas primas. Ganás si el precio queda dentro del rango. Riesgo ILIMITADO si se escapa fuerte.",
     "opciones": [{"tipo": "C", "accion": "vender", "prompt": "Call fuera del dinero VENDIDA (precio de ejercicio más alto)"},
               {"tipo": "P", "accion": "vender", "prompt": "Put fuera del dinero VENDIDA (precio de ejercicio más bajo)"}]},
    {"id": 12, "nombre": "Cóndor de hierro", "sesgo": "neutral",
     "descripcion": "Versión con cobertura del Strangle vendido: vendés Put y Call, comprás otras más lejanas. Crédito neto acotado, pérdida máxima definida.",
     "opciones": [{"tipo": "P", "accion": "vender", "prompt": "Put VENDIDA (ala interna)"},
               {"tipo": "P", "accion": "comprar", "prompt": "Put COMPRADA (ala externa, cobertura)"},
               {"tipo": "C", "accion": "vender", "prompt": "Call VENDIDA (ala interna)"},
               {"tipo": "C", "accion": "comprar", "prompt": "Call COMPRADA (ala externa, cobertura)"}]},
]

# ── Glosario general de términos de opciones (independiente de cualquier cálculo) ──
GLOSARIO_TERMINOS = {
    'Opción': 'Contrato que da el DERECHO (no la obligación) de comprar (Call) o vender (Put) un activo a un precio fijado, antes o en una fecha determinada.',
    'Americana/Europea': 'Americana: se ejerce en cualquier momento antes del vencimiento (acciones en Argentina y EEUU). Europea: solo se ejerce en la fecha de vencimiento (ej. índices como el SPX).',
    'Subyacente': 'El activo sobre el que está armada la opción.',
    'Precio de ejercicio (K)': 'Precio al que se puede ejercer la opción.',
    'Prima': 'Precio que pagás (si comprás) o cobrás (si vendés) la opción.',
    'Vencimiento': 'Fecha límite hasta la que la opción existe.',
    'Call / Put': 'Call = derecho a COMPRAR al precio de ejercicio. Put = derecho a VENDER al precio de ejercicio.',
    'Dentro / fuera / en el dinero': 'Dentro del dinero: la opción tiene valor intrínseco. Fuera del dinero: no lo tiene. En el dinero: el precio de ejercicio es casi igual al precio actual.',
    'Asignación': 'Lo que le pasa al VENDEDOR de una opción cuando el comprador decide ejercerla: queda obligado a cumplir.',
    'Punto de equilibrio': 'Precio del subyacente al vencimiento donde la estrategia empieza a ser rentable.',
    'Crédito / Débito': 'Crédito = cobrás dinero al armar la estrategia. Débito = pagás dinero.',
    'Compra / Venta': 'Compra = el precio más alto que alguien ofrece pagar por la opción: a ese precio vos vendés. Venta = el precio más bajo al que alguien ofrece vender: a ese precio vos comprás. La venta siempre es mayor o igual a la compra.',
    'Diferencial (compra-venta)': 'Diferencia entre la venta y la compra. Más grande = menos líquida, más cuesta entrar y salir.',
    'Deslizamiento': 'Costo de ejecutar a precios reales (cruzando el diferencial) en vez del precio medio teórico. Comprar te cuesta el precio de venta; vender te da el precio de compra.',
    'Vol. Histórica': 'Cuánto se movió el activo en el pasado.',
    'Vol. Implícita': 'Cuánto movimiento futuro está descontando el mercado a través del precio de la opción.',
    'Rendimiento por dividendos (q)': 'Rendimiento de dividendos anual continuo. Baja el precio de la Call y sube el de la Put (quien tiene la opción no cobra esos dividendos).',
    'Tamaño de posición': 'Cuántos contratos operar según tu capital y tu tolerancia al riesgo. Una regla común es no arriesgar más de 1-2% del capital total en una sola operación.',
    'Efecto Palanca': 'Efecto Palanca = Delta * S / Precio_opción. Cuántas veces más se mueve, en %, la opción respecto del subyacente.',
    'Lote/Contrato': 'Cuántas unidades del subyacente representa 1 contrato. En EEUU suele ser 100 (hay que multiplicar). En Argentina puede variar según el bróker — confirmalo antes de operar.',
}


# ==============================================================
#  MOTOR DE PAYOFF
# ==============================================================

def payoff_opcion(opcion, S_T):
    intrinsico = max(S_T - opcion["strike"], 0) if opcion["tipo"] == "C" else max(opcion["strike"] - S_T, 0)
    return (intrinsico - opcion["precio_mercado"]) if opcion["accion"] == "comprar" else (opcion["precio_mercado"] - intrinsico)


def payoff_total(opciones, S_T):
    return sum(payoff_opcion(p, S_T) for p in opciones)


def costo_neto_estrategia(opciones):
    return sum(p["precio_mercado"] if p["accion"] == "comprar" else -p["precio_mercado"] for p in opciones)


def costo_neto_real_estrategia(opciones):
    total = 0.0
    for p in opciones:
        total += p["ask"] if p["accion"] == "comprar" else -p["bid"]
    return total


def _pendiente_mas_alla_del_strike_maximo(opciones):
    return sum((1 if p["accion"] == "comprar" else -1) for p in opciones if p["tipo"] == "C")


def analizar_payoff_estrategia(opciones):
    strikes = sorted(set(p["strike"] for p in opciones))
    valor_en_cero = payoff_total(opciones, 0.0)
    valores_en_strikes = {k: payoff_total(opciones, k) for k in strikes}
    puntos_x = [0.0] + strikes
    puntos_y = [valor_en_cero] + [valores_en_strikes[k] for k in strikes]

    breakevens = []
    for i in range(len(puntos_x) - 1):
        x0, x1, y0, y1 = puntos_x[i], puntos_x[i+1], puntos_y[i], puntos_y[i+1]
        if abs(y0) < 1e-9: breakevens.append(round(x0, 2))
        if (y0 < 0 < y1) or (y0 > 0 > y1):
            breakevens.append(round(x0 + (0 - y0) * (x1 - x0) / (y1 - y0), 2))

    pendiente_arriba = _pendiente_mas_alla_del_strike_maximo(opciones)
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
        "costo_neto": costo_neto_estrategia(opciones),
    }


def calcular_tamano_posicion(analisis, opciones, capital, pct_riesgo, mult=100):
    riesgo_maximo = capital * pct_riesgo
    L = [f"Capital: {capital:,.2f} · Riesgo máx. por operación: {pct_riesgo:.1%} → {riesgo_maximo:,.2f}"]
    if analisis["perdida_ilimitada"]:
        L.append("⚠️ Pérdida ILIMITADA (opción vendida sin cobertura). No se puede fijar tamaño por 'pérdida máxima'. "
                  "Evaluá agregar una opción de protección (ej. Strangle vendido → Cóndor de hierro).")
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
    puts_vendidas = [p for p in opciones if p["tipo"] == "P" and p["accion"] == "vender"]
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
                alertas.append(f"Precio de ejercicio {k}: vol. implícita Call {ivc:.2%} vs vol. implícita Put {ivp:.2%} → diferencia {diff:.2%}")
    if not alertas:
        return True, "✅ Sin violaciones grandes de paridad Put-Call."
    return False, "⚠️ Diferencias grandes de vol. implícita en el mismo precio de ejercicio:\n" + "\n".join(alertas)


def analizar_skew(filas, S):
    puts_otm = [f["_iv"] for f in filas if f["_tipo"] == "P" and f["_strike"] < S and not np.isnan(f["_iv"])]
    calls_otm = [f["_iv"] for f in filas if f["_tipo"] == "C" and f["_strike"] > S and not np.isnan(f["_iv"])]
    if not puts_otm or not calls_otm:
        return "⚠️ No hay precios de ejercicio fuera del dinero de ambos lados del precio actual para medir sesgo de volatilidad."
    iv_p, iv_c = sum(puts_otm)/len(puts_otm), sum(calls_otm)/len(calls_otm)
    diff = iv_p - iv_c
    txt = f"Vol. implícita prom. Puts fuera del dinero: {iv_p:.2%} · vol. implícita prom. Calls fuera del dinero: {iv_c:.2%} · Diferencia: {diff:+.2%}. "
    if diff > 0.03: txt += "📐 Sesgo de volatilidad bajista: el mercado paga más por protección a la baja."
    elif diff < -0.03: txt += "📐 Sesgo de volatilidad alcista: el mercado paga más por potencial alcista especulativo."
    else: txt += "📐 Sesgo de volatilidad plano."
    return txt


# ==============================================================
#  GRÁFICOS
# ==============================================================

def fig_payoff(opciones, S, analisis):
    xs = np.linspace(max(0.01, S*0.5), S*1.5, 200)
    ys = [payoff_total(opciones, x) for x in xs]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=ys, line=dict(color=C_ACENT, width=2.4), fill='tozeroy',
                              fillcolor='rgba(58,123,213,0.10)', name='Resultado al vencimiento'))
    fig.add_hline(y=0, line_color=C_MUTED, opacity=0.5)
    fig.add_vline(x=S, line_dash='dot', line_color=C_YELL, opacity=0.6,
                  annotation_text=f'Precio actual {S:.2f}', annotation_font_color=C_YELL)
    for be in analisis['breakevens']:
        fig.add_vline(x=be, line_dash='dash', line_color=C_GREEN, opacity=0.5,
                      annotation_text=f'PE {be:.2f}', annotation_font_color=C_GREEN)
    for p in opciones:
        fig.add_vline(x=p['strike'], line_dash='dot', line_color=C_MUTED, opacity=0.25)
    fig.update_layout(**PLOTLY_LAYOUT_OPC, height=440,
                       title=dict(text='Perfil de resultado al vencimiento', font=dict(color=C_TEXT, size=14)),
                       xaxis=dict(title='Precio del subyacente', gridcolor=C_GRID),
                       yaxis=dict(title='Resultado por acción', gridcolor=C_GRID),
                       margin=dict(l=10, r=10, t=45, b=10))
    return fig


def fig_griegas_sensibilidad(opciones, S, T, r, sigmas, q, estilo):
    variaciones = np.linspace(-0.20, 0.20, 21)
    datos = {g: [] for g in NOMBRES_GRIEGAS}
    for var in variaciones:
        S_T = S * (1 + var)
        totales = {g: 0.0 for g in NOMBRES_GRIEGAS}
        for opcion, sigma in zip(opciones, sigmas):
            try:
                letras = calcular_griegas(opcion['tipo'], S_T, opcion['strike'], T, r, sigma, q, estilo)
            except Exception:
                letras = {g: np.nan for g in NOMBRES_GRIEGAS}
            signo = 1 if opcion['accion'] == 'comprar' else -1
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


def fig_repricing(opciones, S, T, r, sigmas, q, estilo, costo_neto):
    variaciones = np.linspace(-0.20, 0.20, 41)
    valores, xs = [], []
    for var in variaciones:
        S_T = S * (1 + var)
        v = 0.0
        for opcion, sigma in zip(opciones, sigmas):
            try:
                precio = precio_opcion(opcion['tipo'], S_T, opcion['strike'], T, r, sigma, q, estilo)
            except Exception:
                precio = np.nan
            v += precio if opcion['accion'] == 'comprar' else -precio
        valores.append(v); xs.append(S_T)
    pnl = [v - costo_neto for v in valores]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=pnl, line=dict(color=C_MONSTER, width=2.2), name='Resultado a precio de mercado (hoy)'))
    fig.add_hline(y=0, line_color=C_MUTED, opacity=0.5)
    fig.add_vline(x=S, line_dash='dot', line_color=C_YELL, opacity=0.6)
    fig.update_layout(**PLOTLY_LAYOUT_OPC, height=380,
                       title=dict(text='Resultado si el subyacente se mueve HOY (mismo T, sin pasar tiempo)', font=dict(color=C_TEXT, size=13)),
                       xaxis=dict(title='Precio del subyacente', gridcolor=C_GRID),
                       yaxis=dict(title='Resultado por acción', gridcolor=C_GRID),
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


# ==============================================================
#  ESTADO DE SESIÓN
# ==============================================================

def _init_estado_opciones():
    defaults = {
        'opc_paso': 1, 'opc_ticker': '', 'opc_vto': None, 'opc_r': 0.30, 'opc_q': 0.0,
        'opc_estilo': 'americana', 'opc_estrategia_id': None, 'opc_opciones_data': [],
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
        Elegí una estrategia del catálogo, cargá compra/venta de cada opción y obtené precio teórico,
        volatilidad implícita, griegas, liquidez/deslizamiento, perfil de resultado, escenarios de revaluación y
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
            ticker = st.text_input('Símbolo (ej: GGAL.BA, AAPL, YPFD.BA)', value=st.session_state['opc_ticker'],
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
                    st.caption('⚠️ Yahoo Finance no tiene cadena de opciones publicada para este símbolo '
                               '(común en algunos ADRs/CEDEARs). Carga manual de precios.')
        with c4:
            r = st.number_input('Tasa de interés anual (decimal)', min_value=0.0, max_value=3.0,
                                 value=float(st.session_state['opc_r']), step=0.01, format='%.4f', key='opc_r_input')
        with c5:
            q = st.number_input('Rendimiento por dividendos anual (decimal)', min_value=0.0, max_value=1.0,
                                 value=float(st.session_state['opc_q']), step=0.001, format='%.4f', key='opc_q_input')

        datos_activo = None
        if ticker:
            with st.spinner(f'Descargando datos de {ticker}...'):
                datos_activo = _opc_datos_activo(ticker.strip().upper())
            if datos_activo is None:
                st.warning(f'No se encontraron datos para {ticker}. Verificá el símbolo.')
            else:
                if datos_activo.get('q_sugerido') is not None:
                    st.caption(f"💡 Rendimiento por dividendos sugerido por Yahoo Finance: {datos_activo['q_sugerido']:.2%} "
                               f"(ajustá arriba si querés usarlo)")
                cm1, cm2, cm3, cm4 = st.columns(4)
                with cm1: st.metric('Precio', fmt_precio_opc(datos_activo['S']), help=datos_activo['fuente'])
                with cm2: st.metric('Vol. Histórica (40d)', f"{datos_activo['vol_hist']:.2%}")
                with cm3: st.metric('RSI', f"{datos_activo['rsi']:.1f}")
                with cm4: st.metric('Media móvil de 20 ruedas', fmt_precio_opc(datos_activo['sma20']))

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
        st.info('Ingresá un símbolo para continuar.')
        return

    datos_activo = _opc_datos_activo(st.session_state['opc_ticker'].strip().upper())
    if datos_activo is None:
        st.error('No se pudieron obtener datos del activo. Revisá el símbolo.')
        return

    S = datos_activo['S']
    vol_hist = datos_activo['vol_hist']
    dias_vto = max((st.session_state['opc_vto'] - date.today()).days, 1)
    T = dias_vto / 365
    r, q, estilo, mult = st.session_state['opc_r'], st.session_state['opc_q'], st.session_state['opc_estilo'], st.session_state['opc_mult']

    # GEX: solo se calcula si activás el toggle (evita descargar cadenas en cada rerun)
    with st.expander('🧲 GEX — Exposición Gamma y zonas', expanded=False):
        if st.toggle('Calcular GEX', value=False, key='opc_gex_toggle'):
            render_gex(st.session_state['opc_ticker'].strip().upper(), S, r, q, mult)

    # ── PASO 2: elegir estrategia ────────────────────────────────────────
    st.markdown('---')
    st.markdown('### 2️⃣ Elegí la estrategia')

    sesgo_tabs = st.tabs(['📈 Alcistas', '📉 Bajistas', '➡️ Neutrales'])
    sesgo_map = {'📈 Alcistas': 'alcista', '📉 Bajistas': 'bajista', '➡️ Neutrales': 'neutral'}
    estrategia = None
    for tab, (label, sesgo) in zip(sesgo_tabs, sesgo_map.items()):
        with tab:
            estrategias_filtradas = [e for e in CATALOGO_ESTRATEGIAS if e['sesgo'] == sesgo]
            nombres = [e['nombre'] for e in estrategias_filtradas]
            idx_actual = 0
            if st.session_state['opc_estrategia_id']:
                actual = next((i for i, e in enumerate(estrategias_filtradas) if e['id'] == st.session_state['opc_estrategia_id']), None)
                if actual is not None: idx_actual = actual
            sel = st.radio(f'Estrategias {label.lower()}', nombres, index=idx_actual if estrategias_filtradas else 0,
                            key=f'opc_radio_{sesgo}', label_visibility='collapsed')
            if sel:
                est_candidato = next(e for e in estrategias_filtradas if e['nombre'] == sel)
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

    # ── PASO 3: cargar opciones (strike, bid, ask) ─────────────────────────
    st.markdown('---')
    st.markdown('### 3️⃣ Cargá precio de ejercicio, compra y venta de cada opción')

    vencimiento_str = st.session_state['opc_vto'].strftime('%Y-%m-%d')
    cadena_disponible = vencimiento_str in vtos_reales if vtos_reales else False
    cadena = _opc_cadena_opciones(st.session_state['opc_ticker'].strip().upper(), vencimiento_str) \
        if cadena_disponible else None

    if cadena_disponible and cadena:
        with st.expander('📡 Ver cadena completa de opciones (Yahoo Finance)', expanded=False):
            render_tabla_cadena_opciones(cadena, S)
    elif vtos_reales and not cadena_disponible:
        st.caption('⚠️ El vencimiento elegido no está en la cadena real — carga manual para todas las opciones.')

    opciones_input = []
    cols_opciones = st.columns(len(estrategia['opciones']))
    strikes_previos = {}
    for i, (col, spec) in enumerate(zip(cols_opciones, estrategia['opciones'])):
        with col:
            tipo_txt = 'Call' if spec['tipo'] == 'C' else 'Put'
            accion_txt = 'COMPRÁS' if spec['accion'] == 'comprar' else 'VENDÉS'
            st.markdown(f"**Opción {i+1}: {tipo_txt} — {accion_txt}**")

            lado_df = None
            if cadena and spec.get('mismo_strike_que') is None:
                lado_df = cadena['calls'] if spec['tipo'] == 'C' else cadena['puts']

            usar_cadena_opcion = False
            if lado_df is not None and not lado_df.empty:
                usar_cadena_opcion = st.checkbox(f'Usar cadena real', value=True, key=f'opc_usar_cadena_{i}')

            if spec.get('mismo_strike_que') is not None:
                strike = strikes_previos[spec['mismo_strike_que']]
                st.caption(f'Mismo precio de ejercicio que opción {spec["mismo_strike_que"]+1}: {strike:.2f}')
                bid = st.number_input(f'Compra opción {i+1}', min_value=0.0, value=0.0, step=0.01, key=f'opc_bid_{i}')
                ask = st.number_input(f'Venta opción {i+1}', min_value=0.0, value=0.0, step=0.01, key=f'opc_ask_{i}')

            elif usar_cadena_opcion:
                strikes_disp = lado_df['strike'].tolist()
                fila_atm = _opc_fila_strike_mas_cercano(lado_df, S)
                idx_def = strikes_disp.index(float(fila_atm['strike'])) if fila_atm is not None else 0
                strike = st.selectbox(f'Precio de ejercicio opción {i+1} (cadena real)', strikes_disp,
                                       index=idx_def, key=f'opc_strike_cadena_{i}')
                fila_sel = lado_df[lado_df['strike'] == strike].iloc[0]
                bid_def = float(fila_sel['bid']) if pd.notna(fila_sel['bid']) else 0.0
                ask_def = float(fila_sel['ask']) if pd.notna(fila_sel['ask']) else 0.0
                iv_txt = f"{fila_sel['impliedVolatility']:.1%}" if pd.notna(fila_sel['impliedVolatility']) else 'N/D'
                oi_txt = int(fila_sel['openInterest']) if pd.notna(fila_sel['openInterest']) else 0
                st.caption(f"Vol. implícita de mercado: {iv_txt} · interés abierto: {oi_txt} · {'🟢 Dentro del dinero' if fila_sel['inTheMoney'] else '⚪ Fuera del dinero'}")
                bid = st.number_input(f'Compra opción {i+1}', min_value=0.0, value=bid_def, step=0.01, key=f'opc_bid_{i}')
                ask = st.number_input(f'Venta opción {i+1}', min_value=0.0, value=ask_def, step=0.01, key=f'opc_ask_{i}')

            else:
                strike = st.number_input(f'Precio de ejercicio opción {i+1}', min_value=0.01,
                                          value=round(S, 2), step=0.5, key=f'opc_strike_{i}')
                bid = st.number_input(f'Compra opción {i+1}', min_value=0.0, value=0.0, step=0.01, key=f'opc_bid_{i}')
                ask = st.number_input(f'Venta opción {i+1}', min_value=0.0, value=0.0, step=0.01, key=f'opc_ask_{i}')

            strikes_previos[i] = strike
            opciones_input.append({'tipo': spec['tipo'], 'accion': spec['accion'], 'strike': strike,
                                 'bid': bid, 'ask': ask, 'precio_mercado': (bid + ask) / 2.0})

    calcular = st.button('▶ Calcular', type='primary', key='opc_btn_calcular')
    if calcular:
        if any(p['ask'] <= 0 for p in opciones_input):
            st.error('Cargá compra y venta (> 0) de todas las opciones antes de calcular.')
            return
        st.session_state['opc_calculado'] = True
        st.session_state['opc_opciones_data'] = opciones_input

    if not st.session_state.get('opc_calculado'):
        return

    opciones = st.session_state['opc_opciones_data']

    # ── CÁLCULOS ─────────────────────────────────────────────────────────
    filas = []
    for opcion in opciones:
        tipo, K, precio_mercado = opcion['tipo'], opcion['strike'], opcion['precio_mercado']
        precio_teorico = float(precio_opcion(tipo, S, K, T, r, vol_hist, q, estilo))
        vol_impl, motivo_falla = volatilidad_implicita(tipo, S, K, T, r, precio_mercado, q, estilo)
        letras = calcular_griegas(tipo, S, K, T, r, vol_hist, q, estilo)
        lam = calcular_apalancamiento(letras['Delta'], S, precio_mercado)
        senal = generar_senal_operacion(precio_teorico, precio_mercado, vol_hist, vol_impl, motivo_falla)
        mid, spread_abs, spread_pct, senal_liq = evaluar_liquidez(opcion['bid'], opcion['ask'])
        accion_desc = 'comprada' if opcion['accion'] == 'comprar' else 'vendida'
        tipo_desc = 'Call' if tipo == 'C' else 'Put'
        filas.append({
            'Opción': f'{tipo_desc} {accion_desc}', 'Precio de ejercicio': K, 'Compra': opcion['bid'], 'Venta': opcion['ask'],
            'Punto medio': round(mid, 2), 'Diferencial': round(spread_abs, 2),
            'Diferencial %': f'{spread_pct:.1%}' if not np.isnan(spread_pct) else 'N/D',
            'Liquidez': senal_liq, 'Precio Teórico': round(precio_teorico, 2),
            'Vol. Histórica': f'{vol_hist:.2%}',
            'Vol. Implícita': f'{vol_impl:.2%}' if not np.isnan(vol_impl) else 'N/D',
            'Delta': round(letras['Delta'], 3), 'Gamma': round(letras['Gamma'], 4),
            'Theta': round(letras['Theta'], 4), 'Vega': round(letras['Vega'], 4), 'Rho': round(letras['Rho'], 4),
            'Efecto Palanca': round(lam, 2) if not np.isnan(lam) else 'N/D', 'Señal': senal,
            '_tipo': tipo, '_strike': K, '_iv': vol_impl,
        })
    df_filas = pd.DataFrame(filas)

    st.markdown('---')
    st.markdown('### 📊 Valuación y liquidez de cada opción')
    st.dataframe(df_filas[['Opción', 'Precio de ejercicio', 'Compra', 'Venta', 'Punto medio', 'Diferencial', 'Diferencial %', 'Liquidez',
                            'Precio Teórico', 'Vol. Histórica', 'Vol. Implícita', 'Señal']],
                 use_container_width=True, hide_index=True)

    st.markdown('### 📊 Griegas de cada opción')
    st.dataframe(df_filas[['Opción', 'Delta', 'Gamma', 'Theta', 'Vega', 'Rho', 'Efecto Palanca']],
                 use_container_width=True, hide_index=True)

    # ── análisis probabilístico: Monte Carlo, rango empírico y señal por opción ──
    st.markdown('---')
    st.markdown('### 🎲 Análisis probabilístico (Monte Carlo + señal por opción)')

    precios_serie = _opc_serie_precios_completa(st.session_state['opc_ticker'].strip().upper())
    if precios_serie is None:
        st.warning('No se pudo descargar la serie histórica completa para el análisis probabilístico.')
    else:
        retornos_activo = np.log(precios_serie / precios_serie.shift(1)).dropna()
        drift_real = float(retornos_activo[-VENTANA_VOL_CORTA_OPC:].mean() * 252) \
            if len(retornos_activo) >= VENTANA_VOL_CORTA_OPC else float(retornos_activo.mean() * 252)

        sims_mc = simular_monte_carlo_opc(S, vol_hist, drift_real, dias_vto, N_SIMULACIONES_OPC, seed=42)
        precios_finales_mc = sims_mc[-1]
        p40_mc = float(np.percentile(precios_finales_mc, 40))
        p60_mc = float(np.percentile(precios_finales_mc, 60))
        prob_perdida = float(np.mean(precios_finales_mc < S) * 100)

        p40_emp, p60_emp, n_ventanas_emp = rango_empirico_opc(precios_serie, S, dias_vto)
        vol_empirica = sigma_desde_rango_opc(p40_emp, p60_emp, T) if p40_emp is not None else float('nan')

        banda_inf_1s = S * np.exp((drift_real - 0.5 * vol_hist ** 2) * T - vol_hist * np.sqrt(T))
        banda_sup_1s = S * np.exp((drift_real - 0.5 * vol_hist ** 2) * T + vol_hist * np.sqrt(T))

        cmc1, cmc2, cmc3 = st.columns(3)
        with cmc1: st.metric('Precio medio simulado', fmt_precio_opc(float(np.mean(precios_finales_mc))))
        with cmc2: st.metric('Rango Monte Carlo (perc. 40-60%)', f'{p40_mc:,.2f} – {p60_mc:,.2f}')
        with cmc3: st.metric('Prob. de pérdida vs precio actual', f'{prob_perdida:.1f}%')

        st.markdown(f"**Comparación de 3 fuentes de rango probable a {dias_vto} días:**")
        st.markdown(f"- 🎲 Monte Carlo (con tendencia reciente {drift_real:+.1%} anual): {p40_mc:,.2f} – {p60_mc:,.2f}")
        st.markdown(f"- 📐 Analítico ±1σ (vol. histórica): {banda_inf_1s:,.2f} – {banda_sup_1s:,.2f}")
        if p40_emp is not None:
            st.markdown(f"- 📊 Empírico histórico (n={n_ventanas_emp} ventanas, vol. implícita en el rango "
                        f"{vol_empirica:.2%}): {p40_emp:,.2f} – {p60_emp:,.2f}")
        else:
            st.caption('⚠️ Historial insuficiente para calcular el rango empírico.')

        strikes_opciones = [p['strike'] for p in opciones]
        st.plotly_chart(fig_monte_carlo_distribucion(precios_finales_mc, S, strikes_opciones, p40_mc, p60_mc,
                                                       p40_emp, p60_emp),
                         use_container_width=True, key='opc_fig_montecarlo')

        render_explicacion('Cómo leer la distribución Monte Carlo y cómo usarla', f"""
**Qué muestra**
Se simularon miles de caminos posibles del precio hasta el vencimiento ({dias_vto} días), usando la volatilidad histórica y la tendencia reciente. El histograma muestra **dónde terminó el precio en cada simulación**: las barras más altas son los resultados más probables. Las líneas verticales marcan el precio actual, los rangos del 40% al 60% (Monte Carlo y empírico histórico) y los precios de ejercicio de tu estrategia.

**Datos de hoy**
- La mitad central de los resultados simulados cae entre **{p40_mc:,.2f} y {p60_mc:,.2f}**.
- La probabilidad de que el precio termine por debajo del actual es **{prob_perdida:.1f}%**.

**Cómo leerlo**
- Si un **precio de ejercicio vendido** queda en una zona con pocas barras (lejos del centro), es menos probable que el precio llegue ahí.
- Si un **precio de ejercicio comprado** queda en una zona con muchas barras, es más probable que termine con valor.
- Cuando el Monte Carlo y el rango empírico **coinciden**, la estimación es más confiable; si difieren mucho, hay que tomarla con más cautela.

**Cómo sacarle provecho**
Usalo para comparar tus precios de ejercicio contra el rango probable. Es una **estimación estadística basada en el pasado**, no una predicción: un evento inesperado puede dejar el precio fuera de todo el gráfico.
""")

        st.markdown('#### Veredicto por opción (6 chequeos independientes)')
        rsi_actual, sma20_actual = datos_activo['rsi'], datos_activo['sma20']
        for i, (opcion, fila) in enumerate(zip(opciones, filas), start=1):
            tipo_desc = 'Call' if opcion['tipo'] == 'C' else 'Put'
            accion_desc = 'comprada' if opcion['accion'] == 'comprar' else 'vendida'
            if opcion['tipo'] == 'C':
                prob_fav = float(np.mean(precios_finales_mc > opcion['strike']) * 100) if opcion['accion'] == 'comprar' \
                    else float(np.mean(precios_finales_mc <= opcion['strike']) * 100)
            else:
                prob_fav = float(np.mean(precios_finales_mc < opcion['strike']) * 100) if opcion['accion'] == 'comprar' \
                    else float(np.mean(precios_finales_mc >= opcion['strike']) * 100)

            resultado = evaluar_señal_opcion(opcion['tipo'], opcion['accion'], S, vol_hist, vol_empirica, fila['_iv'],
                                            fila['Precio Teórico'], opcion['precio_mercado'], fila['Delta'],
                                            rsi_actual, sma20_actual, prob_fav)

            with st.expander(f"Opción {i}: {tipo_desc} {accion_desc} K={opcion['strike']:.2f} — "
                              f"{resultado['veredicto']} ({resultado['puntaje']}/6)", expanded=False):
                render_veredicto_opcion_html(resultado)
                st.caption(f"Prob. Monte Carlo favorable a esta opción: {prob_fav:.1f}%")

    ok_par, msg_par = verificar_paridad_put_call(filas)
    st.markdown(f"**⚖️ Paridad Put-Call:** {msg_par}" if ok_par else f"**⚖️ Paridad Put-Call:**\n\n{msg_par}")
    st.markdown(f"**📐 Sesgo de volatilidad:** {analizar_skew(filas, S)}")

    # ── liquidez y deslizamiento (slippage) de la estrategia ────────────
    costo_teorico = costo_neto_estrategia(opciones)
    costo_real = costo_neto_real_estrategia(opciones)
    slippage = costo_real - costo_teorico
    st.markdown('### 💧 Liquidez y deslizamiento de la estrategia')
    cl1, cl2, cl3 = st.columns(3)
    with cl1: st.metric('Costo neto teórico (punto medio)', f'{costo_teorico:.2f}/acción')
    with cl2: st.metric('Costo neto real (compra/venta)', f'{costo_real:.2f}/acción')
    with cl3: st.metric('Deslizamiento', f'{slippage:.2f}/acción', f'{slippage*mult:.2f} por contrato')
    opciones_iliquidas = [f for f in filas if '🔴' in f['Liquidez'] or '🟠' in f['Liquidez']]
    if opciones_iliquidas:
        st.warning('⚠️ Opciones con liquidez media/baja — priorizá orden límite: ' +
                   ', '.join(f"{f['Opción']} K={f['Precio de ejercicio']}" for f in opciones_iliquidas))
    else:
        st.success('✅ Todas las opciones tienen buena liquidez.')

    # ── resultado de la estrategia completa ─────────────────────────────
    analisis = analizar_payoff_estrategia(opciones)
    st.markdown('---')
    st.markdown(f'### 🎯 Resultado — {estrategia["nombre"]}')

    be_txt = ', '.join(f'{b:.2f}' for b in analisis['breakevens']) if analisis['breakevens'] else 'sin cruce por cero en el rango cargado'
    gan_txt = 'ILIMITADA ⬆️' if analisis['ganancia_ilimitada'] else f"{analisis['ganancia_max']:.2f} ({analisis['ganancia_max']*mult:.2f} x{mult})"
    per_txt = 'ILIMITADA ⬆️' if analisis['perdida_ilimitada'] else f"{analisis['perdida_max']:.2f} ({analisis['perdida_max']*mult:.2f} x{mult})"

    kc1, kc2, kc3 = st.columns(3)
    with kc1: st.metric('Puntos de equilibrio', be_txt)
    with kc2: st.metric('Ganancia máxima', gan_txt)
    with kc3: st.metric('Pérdida máxima', per_txt)

    st.plotly_chart(fig_payoff(opciones, S, analisis), use_container_width=True, key='opc_fig_payoff')

    render_explicacion('Cómo leer el gráfico de perfil de resultado y cómo usarlo', f"""
**Qué muestra**
La ganancia o pérdida **por acción** de toda la estrategia **al vencimiento**, según el precio final del activo. Por encima de la línea de cero hay ganancia; por debajo, pérdida.

**Datos de hoy**
- Puntos de equilibrio: **{be_txt}**
- Ganancia máxima: **{gan_txt}**
- Pérdida máxima: **{per_txt}**

**Cómo leerlo**
- Los **puntos de equilibrio** (líneas verdes) son los precios donde la estrategia pasa de perder a ganar.
- La parte **plana** de la curva indica ganancia o pérdida acotada; una parte que **sigue subiendo o bajando** indica que no hay tope en ese lado.
- La línea amarilla es el precio actual: fijate de qué lado de los puntos de equilibrio quedás hoy.

**Cómo sacarle provecho**
- Preguntate: *"¿el precio necesita moverse mucho para llegar al punto de equilibrio?"* y compará con el rango probable del Monte Carlo.
- Revisá la **pérdida máxima** antes de operar y asegurate de que entra en tu regla de riesgo (más abajo está el tamaño de posición sugerido).
- Este gráfico es **al vencimiento**. Antes del vencimiento, el resultado depende también del tiempo y la volatilidad (mirá el gráfico de revaluación).
""")

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
    for linea in calcular_tamano_posicion(analisis, opciones, capital, pct_riesgo, mult):
        st.markdown(f'- {linea}')

    # ── repricing y escenarios ───────────────────────────────────────────
    sigmas_por_opcion = [f['_iv'] if not np.isnan(f['_iv']) else vol_hist for f in filas]

    st.markdown('---')
    st.markdown('### 💲 Revaluación si el subyacente se mueve HOY (sin pasar tiempo)')
    st.plotly_chart(fig_repricing(opciones, S, T, r, sigmas_por_opcion, q, estilo, costo_teorico),
                     use_container_width=True, key='opc_fig_repricing')

    render_explicacion('Cómo leer el gráfico de revaluación y cómo usarlo', """
**Qué muestra**
Cuánto ganarías o perderías **hoy** (no al vencimiento) si el activo se moviera de golpe, sin que pase el tiempo. Se vuelve a calcular el precio de cada opción para cada nuevo valor del activo.

**Cómo leerlo**
- Es una curva **más suave** que el perfil de resultado, porque las opciones todavía tienen valor por el tiempo que les queda.
- Cuanto más **inclinada** es la curva, más sensible es tu posición a los movimientos del activo (delta alto).
- Cuanto más **curva** es, más importa la gamma.

**Cómo sacarle provecho**
- Sirve para saber cuánto podrías ganar o perder si el activo se mueve en los próximos días y **querés salir antes del vencimiento**.
- Compará este gráfico con el de perfil de resultado: la diferencia entre ambos es el valor temporal que todavía tienen las opciones.
""")

    variaciones_tabla = [i / 100 for i in range(-10, 11, 2)]
    filas_esc = []
    for var in variaciones_tabla:
        S_T = S * (1 + var)
        fila = {'Var. %': f'{var:+.0%}', 'Subyacente': round(S_T, 2)}
        v_total = 0.0
        for i, (opcion, sigma) in enumerate(zip(opciones, sigmas_por_opcion), start=1):
            try:
                precio_rep = float(precio_opcion(opcion['tipo'], S_T, opcion['strike'], T, r, sigma, q, estilo))
            except Exception:
                precio_rep = float('nan')
            fila[f'Opción {i}'] = round(precio_rep, 2)
            v_total += precio_rep if opcion['accion'] == 'comprar' else -precio_rep
        fila['Resultado hoy'] = round(v_total - costo_teorico, 2)
        fila['Resultado al vencimiento'] = round(payoff_total(opciones, S_T), 2)
        filas_esc.append(fila)
    st.markdown('### 📋 Escenarios: precios revaluados, resultado hoy y resultado al vencimiento')
    st.dataframe(pd.DataFrame(filas_esc), use_container_width=True, hide_index=True)

    st.markdown('### 🧮 Sensibilidad de las griegas')
    st.plotly_chart(fig_griegas_sensibilidad(opciones, S, T, r, sigmas_por_opcion, q, estilo),
                     use_container_width=True, key='opc_fig_griegas')

    render_explicacion('Cómo leer la sensibilidad de las griegas y cómo usarla', """
**Qué muestra**
Cómo cambian las griegas **netas** de toda tu estrategia cuando el activo sube o baja hasta un 20%. Cada panel es una griega y la línea punteada es el precio actual.

**Qué significa cada panel**
- **Delta:** cuánto gana o pierde la estrategia por cada $1 que se mueve el activo. Positivo = te favorece que suba; negativo = que baje.
- **Gamma:** qué tan rápido cambia el delta. Positiva = la posición se vuelve más favorable cuanto más se mueve el precio; negativa = al revés.
- **Theta:** lo que gana o pierde por día por el simple paso del tiempo. Negativo = el tiempo juega en contra (típico al comprar opciones); positivo = a favor (típico al vender).
- **Vega:** cuánto cambia el valor si la volatilidad implícita sube o baja 1 punto. Positiva = te conviene que suba la volatilidad; negativa = que baje.
- **Rho:** sensibilidad a la tasa de interés (suele ser la menos relevante).

**Cómo sacarle provecho**
- Fijate cómo **cambia** la delta al moverse el precio: si se dispara, tu posición se vuelve más direccional de lo que pensabas.
- Si el theta es muy negativo, necesitás que el movimiento llegue **rápido**.
- Si el vega es muy positivo o negativo, la estrategia depende mucho de lo que pase con la volatilidad, además del precio.
""")

    # ── simulador interactivo ────────────────────────────────────────────
    st.markdown('---')
    st.markdown('### 🎮 Simulador interactivo')
    st.caption('Movés el subyacente y los días transcurridos, y ves el precio revaluado, griegas y resultado al instante '
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
    for opcion, sigma in zip(opciones, sigmas_por_opcion):
        tipo_desc = 'Call' if opcion['tipo'] == 'C' else 'Put'
        accion_desc = 'comprada' if opcion['accion'] == 'comprar' else 'vendida'
        try:
            p_sin_t = precio_opcion(opcion['tipo'], S_T_sim, opcion['strike'], T, r, sigma, q, estilo)
            p_con_t = precio_opcion(opcion['tipo'], S_T_sim, opcion['strike'], T_nuevo, r, sigma, q, estilo)
            letras_sim = calcular_griegas(opcion['tipo'], S_T_sim, opcion['strike'], T_nuevo, r, sigma, q, estilo)
        except Exception:
            p_sin_t = p_con_t = float('nan')
            letras_sim = {g: float('nan') for g in NOMBRES_GRIEGAS}
        signo = 1 if opcion['accion'] == 'comprar' else -1
        valor_sin_tiempo += signo * p_sin_t
        valor_con_tiempo += signo * p_con_t
        for g in NOMBRES_GRIEGAS: totales_g_sim[g] += signo * letras_sim[g]
        filas_sim.append({
            'Opción': f'{tipo_desc} {accion_desc} K={opcion["strike"]:.2f}',
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
    pnl_vto = payoff_total(opciones, S_T_sim)

    sm1, sm2, sm3 = st.columns(3)
    with sm1: st.metric('Resultado sin pasar tiempo', f'{pnl_sin_tiempo:.2f}', f'x{mult}: {pnl_sin_tiempo*mult:.2f}')
    with sm2: st.metric(f'Resultado con {dias_sim}d pasados', f'{pnl_con_tiempo:.2f}', f'x{mult}: {pnl_con_tiempo*mult:.2f}')
    with sm3: st.metric('Resultado si fuera al vencimiento', f'{pnl_vto:.2f}', f'x{mult}: {pnl_vto*mult:.2f}')
    st.caption(f'💀 Efecto acumulado del paso del tiempo (Theta): {efecto_tiempo_total:.2f} por acción '
               f'(x{mult} = {efecto_tiempo_total*mult:.2f} por contrato)')

    gcols = st.columns(5)
    for gc, g in zip(gcols, NOMBRES_GRIEGAS):
        with gc:
            st.metric(f'{g} neto', f'{totales_g_sim[g]:.4f}')

    if st.button('🔄 Reiniciar (nueva estrategia / nuevas opciones)', key='opc_reset'):
        for k in list(st.session_state.keys()):
            if k.startswith('opc_'):
                del st.session_state[k]
        st.rerun()
