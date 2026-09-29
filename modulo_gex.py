# ==============================================================
#  MÓDULO GEX — Gamma Exposure, punto de cambio de gamma y paredes
#  100% independiente del módulo de opciones (no comparte funciones,
#  caché ni claves de sesión, salvo el "puente" explícito de abajo).
#  Fuente de datos: cadena pública y gratuita de CBOE (retrasada ~15 min).
#  No usa Yahoo Finance ni yfinance.
#
#  Incluye: GEX + Put/Call, Max Pain, movimiento esperado, GEX por vencimiento,
#  vol. implícita (estructura y skew), flujo inusual, DEX (exposición delta con
#  la delta publicada por CBOE), Vanna y Charm, y un puente hacia
#  "Valuación de Opciones" (punto de cambio de gamma, paredes y strikes
#  vendidos sugeridos).
#
#  Uso:   from modulo_gex import modulo_gex
#         modulo_gex()
#  Puente (desde la calculadora):
#         from modulo_gex import leer_puente_gex
#         p = leer_puente_gex('SPY')      # dict o None
#  Requiere: streamlit, pandas, numpy, scipy, plotly, requests
# ==============================================================

import re
import time
from datetime import date, datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from scipy.stats import norm

# ── Paleta ──
C_ACENT, C_TEXT, C_MUTED = '#3a7bd5', '#e6edf3', '#6b7d9a'
C_GREEN, C_RED, C_YELL, C_GRID = '#3fb950', '#f85149', '#e3b341', '#21262d'
C_BG1, C_BG2 = '#0d1117', '#07090f'
PLOTLY_LAYOUT_GEX = dict(plot_bgcolor=C_BG1, paper_bgcolor=C_BG2,
                         font=dict(color='#b0bcd0', family='Inter, sans-serif'))

CBOE_URL = 'https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json'
CBOE_HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; GEX-Analyzer/1.0)', 'Accept': 'application/json'}
INDICES_CBOE = {'SPX', 'NDX', 'RUT', 'VIX', 'XSP', 'DJX'}      # en CBOE llevan guion bajo: _SPX

# Símbolos de Buenos Aires (.BA) → subyacente de EEUU que sí tiene opciones
MAPA_ADR = {'GGAL.BA': 'GGAL', 'YPFD.BA': 'YPF', 'PAMP.BA': 'PAM', 'BMA.BA': 'BMA',
            'BBAR.BA': 'BBAR', 'SUPV.BA': 'SUPV', 'CEPU.BA': 'CEPU', 'EDN.BA': 'EDN',
            'LOMA.BA': 'LOMA', 'TGSU2.BA': 'TGS', 'TEO.BA': 'TEO', 'CRES.BA': 'CRESY'}

_OCC = re.compile(r'^(.+?)(\d{6})([CP])(\d{8})$')            # ej. NVDA260116C00150000

EXPLICACIONES_ABIERTAS = True

# Clave de sesión del puente hacia "Valuación de Opciones" (único punto de contacto entre módulos)
CLAVE_PUENTE = 'gex_puente'


# ==============================================================
#  UTILIDADES
# ==============================================================

def render_explicacion(titulo, contenido_md):
    with st.expander(f'📘 {titulo}', expanded=EXPLICACIONES_ABIERTAS):
        st.markdown(contenido_md)


def fmt_precio(p):
    if p is None or (isinstance(p, float) and np.isnan(p)): return 'N/D'
    if p >= 1000: return f'${p:,.0f}'
    if p >= 10: return f'${p:.2f}'
    return f'${p:.5f}'


def resolver_simbolo(entrada):
    """Devuelve (simbolo_cboe, simbolo_limpio, aviso).
    - Quita el prefijo ^ y espacios.
    - Si es .BA, usa el ADR conocido o, si no, la raíz sin .BA (CEDEARs de acciones de EEUU).
    - Índices (SPX, NDX...) llevan guion bajo en CBOE."""
    s = (entrada or '').strip().upper().lstrip('^')
    aviso = None
    if s.endswith('.BA'):
        base = MAPA_ADR.get(s) or s[:-3]
        aviso = (f'{s} cotiza en Buenos Aires y no tiene opciones en CBOE; se usa **{base}** '
                 f'(el subyacente de EEUU, precio en USD).')
        s = base
    cboe = f'_{s}' if s in INDICES_CBOE else s.replace('.', '-')
    return cboe, s, aviso


# ==============================================================
#  DATOS — CBOE (gratis, sin clave)
# ==============================================================

def _mid_contrato(bid, ask, last):
    """Precio medio (compra+venta)/2; si no hay cotización válida, último precio operado; si no, NaN."""
    try:
        b, a = float(bid), float(ask)
        if b > 0 and a >= b:
            return (a + b) / 2.0
    except (TypeError, ValueError):
        pass
    try:
        l = float(last)
        return l if l > 0 else np.nan
    except (TypeError, ValueError):
        return np.nan


@st.cache_data(ttl=300, show_spinner=False)
def _gex_descargar(simbolo_cboe):
    """Descarga la cadena completa de CBOE. Si falla LANZA excepción, así el error
    NO queda cacheado (st.cache_data no guarda excepciones)."""
    ultimo = None
    for i in range(3):
        try:
            resp = requests.get(CBOE_URL.format(sym=simbolo_cboe), headers=CBOE_HEADERS, timeout=20)
            if resp.status_code in (403, 404):
                raise LookupError(f'CBOE no tiene cadena de opciones para "{simbolo_cboe}" '
                                  f'(HTTP {resp.status_code}). Solo cubre símbolos con opciones listadas en EEUU.')
            resp.raise_for_status()
            data = resp.json().get('data') or {}
            opts = data.get('options') or []
            if not opts:
                raise LookupError(f'CBOE respondió sin contratos para "{simbolo_cboe}".')

            spot = data.get('current_price') or data.get('close') or data.get('prev_day_close')
            if not spot:
                raise ValueError('CBOE no informó el precio del subyacente.')

            hoy = date.today()
            filas = []
            for o in opts:
                m = _OCC.match(str(o.get('option', '')))
                if not m:
                    continue
                try:
                    vto = datetime.strptime(m.group(2), '%y%m%d').date()
                except ValueError:
                    continue
                dias = (vto - hoy).days
                if dias < 0:
                    continue
                filas.append((int(m.group(4)) / 1000.0, m.group(3), vto.isoformat(),
                              max(dias, 0.5) / 365.0, o.get('open_interest'), o.get('iv'),
                              o.get('volume'),
                              _mid_contrato(o.get('bid'), o.get('ask'), o.get('last_trade_price')),
                              o.get('delta')))
            if not filas:
                raise LookupError('No se pudo interpretar ningún contrato vigente de la cadena.')

            df = pd.DataFrame(filas, columns=['strike', 'tipo', 'vto', 'T', 'openInterest', 'impliedVolatility',
                                                 'volume', 'mid', 'delta'])
            df['openInterest'] = pd.to_numeric(df['openInterest'], errors='coerce').fillna(0.0)
            df['impliedVolatility'] = pd.to_numeric(df['impliedVolatility'], errors='coerce')
            df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0.0)
            df['mid'] = pd.to_numeric(df['mid'], errors='coerce')
            df['delta'] = pd.to_numeric(df['delta'], errors='coerce')
            return {'spot': float(spot), 'df': df,
                    'hora': str(data.get('last_trade_time') or ''),
                    'descargado': datetime.now().strftime('%H:%M:%S')}
        except LookupError:
            raise                                   # no tiene sentido reintentar
        except Exception as e:
            ultimo = e
            time.sleep(0.8 * (i + 1))
    raise RuntimeError(f'No se pudo descargar de CBOE tras 3 intentos: {type(ultimo).__name__}: {ultimo}')


def preparar_cadena(df_completo, n_vtos, iv_respaldo=0.40):
    """Toma los primeros n vencimientos, descarta contratos sin interés abierto y repara IV inválida.
    Devuelve (df, diag). df es None si no quedó nada."""
    diag = {'vtos': 0, 'filas': 0, 'iv_rellenadas': 0, 'motivo': None}
    df = _subset_vtos(df_completo, n_vtos)
    diag['vtos'] = df['vto'].nunique()

    df = df[df['openInterest'] > 0].copy()
    if df.empty:
        diag['motivo'] = 'Todos los contratos de esos vencimientos tienen interés abierto 0.'
        return None, diag

    valida = (df['impliedVolatility'] > 0.01) & (df['impliedVolatility'] < 5.0)
    if (~valida).any():
        med_vto = df.loc[valida].groupby('vto')['impliedVolatility'].median()
        med_global = float(df.loc[valida, 'impliedVolatility'].median()) if valida.any() else iv_respaldo
        relleno = df['vto'].map(med_vto).fillna(med_global)
        df.loc[~valida, 'impliedVolatility'] = relleno[~valida]
        diag['iv_rellenadas'] = int((~valida).sum())

    df = df.reset_index(drop=True)
    diag['filas'] = len(df)
    return df, diag


def _delta_bs_vec(S, K, T, r, sigma, q, tipo):
    """Delta Black-Scholes (solo se usa para completar contratos donde CBOE no publicó delta)."""
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    return np.where(tipo == 'C', np.exp(-q * T) * norm.cdf(d1), -np.exp(-q * T) * norm.cdf(-d1))


def reparar_delta(df, S, r, q):
    """Deja la columna 'delta' lista: usa la de CBOE y solo completa (con Black-Scholes) los contratos
    donde falta o es inválida (call fuera de 0..1, put fuera de -1..0). Devuelve (df, cantidad_completada)."""
    df = df.copy()
    if 'delta' not in df.columns:
        df['delta'] = np.nan
    d = pd.to_numeric(df['delta'], errors='coerce')
    es_c = df['tipo'] == 'C'
    ok = d.notna() & ((es_c & (d >= 0) & (d <= 1)) | (~es_c & (d <= 0) & (d >= -1)))
    if (~ok).any():
        bs = _delta_bs_vec(S, df['strike'].values, df['T'].values, r, df['impliedVolatility'].values, q,
                           df['tipo'].values)
        d = d.where(ok, pd.Series(bs, index=df.index))
    df['delta'] = d
    return df, int((~ok).sum())


# ==============================================================
#  CÁLCULO GEX
# ==============================================================

def _gamma_bs_vec(S, K, T, r, sigma, q=0.0):
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    return np.exp(-q * T) * norm.pdf(d1) / (S * sigma * np.sqrt(T))


def calcular_gex_por_strike(df, S, r, q, mult=100, rango=0.20):
    """GEX por precio de ejercicio: calls (+) y puts (−). Solo strikes dentro de ±rango del precio."""
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
    """GEX total recalculado en una grilla de precios → ubica el punto de cambio de gamma."""
    grid = np.linspace(S * (1 - rango), S * (1 + rango), n)
    K, T, iv = (df[c].values[None, :] for c in ('strike', 'T', 'impliedVolatility'))
    oi = df['openInterest'].values[None, :]
    signo = np.where(df['tipo'].values == 'C', 1.0, -1.0)[None, :]
    g = _gamma_bs_vec(grid[:, None], K, T, r, iv, q)
    total = (g * signo * oi * mult * grid[:, None] ** 2 * 0.01).sum(axis=1)
    return grid, total


def encontrar_gamma_flip(grid, total, S):
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


def lectura_personalizada_gex(z, S):
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


# ==============================================================
#  GRÁFICOS
# ==============================================================

def fig_gex(piv, zonas, S):
    y_max = float(max(piv['gex_calls'].max(), abs(piv['gex_puts'].min()), 1.0)) * 1.1
    x_min, x_max = float(piv['strike'].min()), float(piv['strike'].max())
    fig = go.Figure()

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

    fig.update_layout(**PLOTLY_LAYOUT_GEX, height=460, barmode='relative',
                      title=dict(text='GEX por precio de ejercicio (USD por cada 1% de movimiento)',
                                 font=dict(color=C_TEXT, size=13), y=0.98),
                      legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0,
                                  font=dict(size=10.5, color=C_TEXT)),
                      xaxis=dict(title='Precio de ejercicio', gridcolor=C_GRID),
                      yaxis=dict(title='GEX ($ / 1%)', gridcolor=C_GRID),
                      margin=dict(l=10, r=10, t=90, b=10))
    return fig


def fig_gex_total(grid, total, S, flip):
    fig = go.Figure(go.Scatter(x=grid, y=total / 1e6, line=dict(color=C_ACENT, width=2.2)))
    fig.add_hline(y=0, line_color=C_MUTED, opacity=0.6)
    fig.add_vline(x=S, line_dash='dot', line_color=C_YELL, opacity=0.7)
    if flip:
        fig.add_vline(x=flip, line_dash='dash', line_color='#bc8cff', opacity=0.8)
    fig.update_layout(**PLOTLY_LAYOUT_GEX, height=300,
                      title=dict(text='GEX total vs precio del subyacente (el cruce por 0 es el punto de cambio de gamma)',
                                 font=dict(color=C_TEXT, size=13)),
                      xaxis=dict(title='Precio', gridcolor=C_GRID),
                      yaxis=dict(title='GEX total (millones de US$ / 1%)', gridcolor=C_GRID),
                      margin=dict(l=10, r=10, t=45, b=10))
    return fig


# ==============================================================
#  ANÁLISIS COMPLEMENTARIOS — misma descarga de CBOE, sin pedidos extra
#  1) Put/Call  2) Max Pain  3) Movimiento esperado
#  4) GEX por vencimiento  5) Vol. implícita (estructura + skew)  6) Flujo inusual
#  7) DEX  8) Vanna y Charm  9) Puente a Valuación de Opciones
# ==============================================================

def _subset_vtos(df_completo, n_vtos):
    """Primeros n vencimientos de la cadena (sin filtrar por interés abierto)."""
    vtos = sorted(df_completo['vto'].unique())[:n_vtos]
    d = df_completo[df_completo['vto'].isin(vtos)].copy()
    for c in ('volume', 'mid'):
        if c not in d.columns:
            d[c] = np.nan
    d['volume'] = pd.to_numeric(d['volume'], errors='coerce').fillna(0.0)
    d['openInterest'] = pd.to_numeric(d['openInterest'], errors='coerce').fillna(0.0)
    d['dias'] = (d['T'] * 365).round(1)
    return d


def _etiqueta_vto(vto, dias):
    return f'{vto} ({int(round(dias))}d)'


def _iv_valida(serie):
    return (serie > 0.01) & (serie < 5.0)


def _fmt_ent(x):
    return f'{x:,.0f}'


def _fmt_musd(x):
    """Dólares en formato corto: millones o miles de millones."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return 'N/D'
    if abs(x) >= 1e9:
        return f'{x / 1e9:,.2f} mil millones US$'
    return f'{x / 1e6:,.1f} M US$'


def _txt_flujo(x):
    """Convierte un flujo firmado en texto: positivo = compra, negativo = venta."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return 'N/D'
    return f"{'Compra' if x > 0 else 'Venta'} de {_fmt_musd(abs(x))}"


# ── 1) Put / Call ─────────────────────────────────────────────────────────

def calcular_put_call(d):
    """Ratio Put/Call por interés abierto y por volumen, por vencimiento y total."""
    oi = d.pivot_table(index='vto', columns='tipo', values='openInterest', aggfunc='sum') \
          .reindex(columns=['C', 'P']).fillna(0.0)
    vol = d.pivot_table(index='vto', columns='tipo', values='volume', aggfunc='sum') \
           .reindex(columns=['C', 'P']).fillna(0.0)
    t = pd.DataFrame({'Días': d.groupby('vto')['dias'].first(),
                      'OI Calls': oi['C'], 'OI Puts': oi['P'],
                      'Vol. Calls': vol['C'], 'Vol. Puts': vol['P']})
    t['P/C OI'] = t['OI Puts'] / t['OI Calls'].replace(0, np.nan)
    t['P/C Vol.'] = t['Vol. Puts'] / t['Vol. Calls'].replace(0, np.nan)
    tot = {k: float(t[k].sum()) for k in ('OI Calls', 'OI Puts', 'Vol. Calls', 'Vol. Puts')}
    tot['P/C OI'] = tot['OI Puts'] / tot['OI Calls'] if tot['OI Calls'] > 0 else np.nan
    tot['P/C Vol.'] = tot['Vol. Puts'] / tot['Vol. Calls'] if tot['Vol. Calls'] > 0 else np.nan
    return t, tot


def _lectura_put_call(pc):
    if pc is None or pd.isna(pc):
        return 'sin datos suficientes'
    if pc < 0.6:  return 'muy sesgado a calls (optimismo o especulación alcista fuerte)'
    if pc < 0.9:  return 'algo más de calls que de puts (sesgo alcista moderado)'
    if pc <= 1.1: return 'equilibrado entre calls y puts'
    if pc <= 1.5: return 'más puts que calls (más coberturas o sesgo bajista)'
    return 'muy sesgado a puts (mucha protección o pesimismo)'


def fig_put_call(t, etiq):
    x = [etiq.get(v, v) for v in t.index]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=x, y=t['P/C OI'], name='P/C por interés abierto', marker_color=C_ACENT, opacity=0.85))
    if t['P/C Vol.'].notna().any():
        fig.add_trace(go.Bar(x=x, y=t['P/C Vol.'], name='P/C por volumen', marker_color=C_YELL, opacity=0.85))
    fig.add_hline(y=1.0, line_dash='dash', line_color=C_MUTED, opacity=0.8,
                  annotation_text='1.0 = igual cantidad de puts y calls', annotation_font_color=C_MUTED)
    fig.update_layout(**PLOTLY_LAYOUT_GEX, height=360, barmode='group',
                      title=dict(text='Ratio Put/Call por vencimiento', font=dict(color=C_TEXT, size=13), y=0.98),
                      legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0, font=dict(size=10.5, color=C_TEXT)),
                      xaxis=dict(gridcolor=C_GRID, type='category'), yaxis=dict(title='Puts / Calls', gridcolor=C_GRID),
                      margin=dict(l=10, r=10, t=80, b=10))
    return fig


# ── 2) Max Pain ───────────────────────────────────────────────────────────

def calcular_max_pain(d, S, mult=100):
    """Precio de ejercicio donde el conjunto de compradores de opciones pierde más dinero al vencimiento."""
    filas, curvas = [], {}
    for vto, g in d.groupby('vto'):
        g = g[g['openInterest'] > 0]
        if g.empty:
            continue
        strikes = np.sort(g['strike'].unique())
        calls = g[g['tipo'] == 'C'].groupby('strike')['openInterest'].sum()
        puts = g[g['tipo'] == 'P'].groupby('strike')['openInterest'].sum()
        kc, oc = calls.index.values.astype(float), calls.values.astype(float)
        kp, op = puts.index.values.astype(float), puts.values.astype(float)
        pain = (np.maximum(strikes[:, None] - kc[None, :], 0) * oc[None, :]).sum(axis=1) \
             + (np.maximum(kp[None, :] - strikes[:, None], 0) * op[None, :]).sum(axis=1)
        pain = pain * mult
        mp = float(strikes[int(np.argmin(pain))])
        curvas[vto] = (strikes, pain)
        filas.append({'vto': vto, 'dias': float(g['dias'].iloc[0]), 'max_pain': mp,
                      'dist_pct': (mp / S - 1) * 100, 'oi_total': float(g['openInterest'].sum())})
    return pd.DataFrame(filas), curvas


def fig_max_pain(strikes, pain, mp, S, titulo):
    lo, hi = S * 0.75, S * 1.25
    m = (strikes >= lo) & (strikes <= hi)
    ks, ps = (strikes[m], pain[m]) if m.sum() >= 3 else (strikes, pain)
    fig = go.Figure(go.Scatter(x=ks, y=ps / 1e6, mode='lines', line=dict(color=C_ACENT, width=2.2),
                               fill='tozeroy', fillcolor='rgba(58,123,213,0.10)', name='Pérdida de compradores'))
    for x, col, dash, nom in ((S, C_YELL, 'dot', 'Precio actual'), (mp, '#bc8cff', 'dash', 'Max Pain')):
        fig.add_trace(go.Scatter(x=[x, x], y=[0, float(np.max(ps / 1e6)) * 1.05], mode='lines',
                                 line=dict(color=col, dash=dash, width=1.8), name=f'{nom} ({x:,.2f})', hoverinfo='skip'))
    fig.update_layout(**PLOTLY_LAYOUT_GEX, height=380,
                      title=dict(text=titulo, font=dict(color=C_TEXT, size=13), y=0.98),
                      legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0, font=dict(size=10.5, color=C_TEXT)),
                      xaxis=dict(title='Precio al vencimiento', gridcolor=C_GRID),
                      yaxis=dict(title='Pérdida total de compradores (millones US$)', gridcolor=C_GRID),
                      margin=dict(l=10, r=10, t=80, b=10))
    return fig


# ── 3) Movimiento esperado ────────────────────────────────────────────────

def calcular_movimiento_esperado(d, S):
    """Straddle ATM (call + put del mismo precio de ejercicio más cercano al precio) por vencimiento,
    y el movimiento de 1 desvío estándar según la vol. implícita ATM."""
    filas = []
    for vto, g in d.groupby('vto'):
        dias = float(g['dias'].iloc[0])
        mc = g[g['tipo'] == 'C'].groupby('strike')['mid'].mean().dropna()
        mp = g[g['tipo'] == 'P'].groupby('strike')['mid'].mean().dropna()
        comunes = mc.index.intersection(mp.index)
        if len(comunes) == 0:
            continue
        k = float(comunes[int(np.argmin(np.abs(comunes.values - S)))])
        straddle = float(mc[k] + mp[k])
        gk = g[(g['strike'] == k) & _iv_valida(g['impliedVolatility'])]
        iv = float(gk['impliedVolatility'].mean()) if not gk.empty else np.nan
        sig = S * iv * np.sqrt(dias / 365.0) if not np.isnan(iv) else np.nan
        filas.append({'vto': vto, 'dias': dias, 'strike_atm': k, 'straddle': straddle,
                      'em_pct': straddle / S * 100, 'bajo': S - straddle, 'alto': S + straddle,
                      'iv_atm': iv * 100 if not np.isnan(iv) else np.nan,
                      'sigma': sig, 'sigma_pct': sig / S * 100 if not np.isnan(sig) else np.nan})
    return pd.DataFrame(filas)


def fig_movimiento_esperado(t, S):
    x = t['dias']
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=t['alto'], mode='lines+markers', line=dict(color=C_GREEN, width=2),
                             name='Techo esperado (precio + straddle)'))
    fig.add_trace(go.Scatter(x=x, y=t['bajo'], mode='lines+markers', line=dict(color=C_RED, width=2),
                             fill='tonexty', fillcolor='rgba(58,123,213,0.10)', name='Piso esperado (precio − straddle)'))
    if t['sigma'].notna().any():
        fig.add_trace(go.Scatter(x=x, y=S + t['sigma'], mode='lines', line=dict(color=C_MUTED, dash='dash', width=1.3),
                                 name='+1σ según vol. implícita'))
        fig.add_trace(go.Scatter(x=x, y=S - t['sigma'], mode='lines', line=dict(color=C_MUTED, dash='dash', width=1.3),
                                 name='−1σ según vol. implícita'))
    fig.add_hline(y=S, line_dash='dot', line_color=C_YELL, opacity=0.8)
    fig.update_layout(**PLOTLY_LAYOUT_GEX, height=400,
                      title=dict(text='Cono de movimiento esperado por el mercado', font=dict(color=C_TEXT, size=13), y=0.98),
                      legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0, font=dict(size=10, color=C_TEXT)),
                      xaxis=dict(title='Días al vencimiento', gridcolor=C_GRID),
                      yaxis=dict(title='Precio del subyacente', gridcolor=C_GRID),
                      margin=dict(l=10, r=10, t=90, b=10))
    return fig


# ── 4) GEX por vencimiento ────────────────────────────────────────────────

def calcular_gex_por_vto(df, S, r, q, mult=100, rango=0.20):
    """GEX total por vencimiento (calls / puts / neto) y matriz precio de ejercicio × vencimiento."""
    g = _gamma_bs_vec(S, df['strike'].values, df['T'].values, r, df['impliedVolatility'].values, q)
    signo = np.where(df['tipo'] == 'C', 1.0, -1.0)
    x = df.copy()
    x['gex'] = signo * g * x['openInterest'] * mult * S ** 2 * 0.01
    x = x[(x['strike'] >= S * (1 - rango)) & (x['strike'] <= S * (1 + rango))]
    if x.empty:
        return None, None
    pt = x.pivot_table(index='vto', columns='tipo', values='gex', aggfunc='sum') \
          .reindex(columns=['C', 'P']).fillna(0.0)
    res = pd.DataFrame({'dias': x.groupby('vto')['T'].first() * 365,
                        'calls': pt['C'], 'puts': pt['P'], 'neto': pt['C'] + pt['P']})
    res['abs'] = res['calls'] + res['puts'].abs()
    heat = x.pivot_table(index='strike', columns='vto', values='gex', aggfunc='sum').fillna(0.0).sort_index()
    return res, heat


def fig_gex_por_vto(res, etiq):
    x = [etiq.get(v, v) for v in res.index]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=x, y=res['calls'] / 1e6, name='GEX Calls', marker_color=C_GREEN, opacity=0.85))
    fig.add_trace(go.Bar(x=x, y=res['puts'] / 1e6, name='GEX Puts', marker_color=C_RED, opacity=0.85))
    fig.add_trace(go.Scatter(x=x, y=res['neto'] / 1e6, mode='markers', name='Neto',
                             marker=dict(size=11, color=C_TEXT, symbol='diamond-open', line=dict(width=2))))
    fig.update_layout(**PLOTLY_LAYOUT_GEX, height=380, barmode='relative',
                      title=dict(text='GEX por vencimiento (millones de US$ por cada 1%)', font=dict(color=C_TEXT, size=13), y=0.98),
                      legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0, font=dict(size=10.5, color=C_TEXT)),
                      xaxis=dict(gridcolor=C_GRID, type='category'), yaxis=dict(title='GEX (M US$ / 1%)', gridcolor=C_GRID),
                      margin=dict(l=10, r=10, t=80, b=10))
    return fig


def fig_heatmap_gex(heat, S, etiq):
    fig = go.Figure(go.Heatmap(z=heat.values / 1e6, x=[etiq.get(c, c) for c in heat.columns], y=heat.index.values,
                               colorscale=[[0.0, '#f85149'], [0.5, '#161b22'], [1.0, '#3fb950']], zmid=0,
                               colorbar=dict(title='M US$ / 1%')))
    fig.add_hline(y=S, line_dash='dot', line_color=C_YELL, opacity=0.9)
    fig.update_layout(**PLOTLY_LAYOUT_GEX, height=520,
                      title=dict(text='Mapa de calor: precio de ejercicio × vencimiento (verde = gamma de calls, rojo = de puts)',
                                 font=dict(color=C_TEXT, size=13)),
                      xaxis=dict(type='category', gridcolor=C_GRID), yaxis=dict(title='Precio de ejercicio', gridcolor=C_GRID),
                      margin=dict(l=10, r=10, t=55, b=10))
    return fig


# ── 5) Volatilidad implícita: estructura temporal y skew ──────────────────

def calcular_estructura_iv(d, S):
    """Vol. implícita ATM (contratos a ±2% del precio) por vencimiento."""
    filas = []
    for vto, g in d.groupby('vto'):
        g = g[_iv_valida(g['impliedVolatility']) & ((g['openInterest'] > 0) | (g['volume'] > 0))]
        if g.empty:
            continue
        near = g[(g['strike'] / S - 1).abs() <= 0.02]
        if near.empty:
            near = g.iloc[[int(np.argmin((g['strike'] - S).abs().values))]]
        filas.append({'vto': vto, 'dias': float(g['dias'].iloc[0]),
                      'iv_atm': float(near['impliedVolatility'].mean()) * 100})
    return pd.DataFrame(filas)


def fig_estructura_iv(t):
    fig = go.Figure(go.Scatter(x=t['dias'], y=t['iv_atm'], mode='lines+markers',
                               line=dict(color='#bc8cff', width=2.4), marker=dict(size=8)))
    fig.update_layout(**PLOTLY_LAYOUT_GEX, height=330,
                      title=dict(text='Estructura temporal de la vol. implícita ATM', font=dict(color=C_TEXT, size=13)),
                      xaxis=dict(title='Días al vencimiento', gridcolor=C_GRID),
                      yaxis=dict(title='Vol. implícita ATM (%)', gridcolor=C_GRID),
                      margin=dict(l=10, r=10, t=50, b=10))
    return fig


def calcular_skew_vto(d, S, vto, rango=0.20):
    g = d[(d['vto'] == vto) & _iv_valida(d['impliedVolatility']) & ((d['openInterest'] > 0) | (d['volume'] > 0))]
    g = g[(g['strike'] >= S * (1 - rango)) & (g['strike'] <= S * (1 + rango))]
    puts = g[(g['tipo'] == 'P') & (g['strike'] <= S)].groupby('strike')['impliedVolatility'].mean().reset_index()
    calls = g[(g['tipo'] == 'C') & (g['strike'] >= S)].groupby('strike')['impliedVolatility'].mean().reset_index()

    def _cerca(sub, obj):
        if sub.empty:
            return np.nan
        i = int(np.argmin((sub['strike'] - obj).abs().values))
        return float(sub['impliedVolatility'].iloc[i]) * 100 if abs(sub['strike'].iloc[i] / obj - 1) <= 0.04 else np.nan

    iv_p, iv_c = _cerca(puts, 0.90 * S), _cerca(calls, 1.10 * S)
    iv_atm = float(g[(g['strike'] / S - 1).abs() <= 0.02]['impliedVolatility'].mean()) * 100 \
        if not g[(g['strike'] / S - 1).abs() <= 0.02].empty else np.nan
    return {'puts': puts, 'calls': calls, 'iv_p90': iv_p, 'iv_c110': iv_c, 'iv_atm': iv_atm,
            'skew': (iv_p - iv_c) if not (np.isnan(iv_p) or np.isnan(iv_c)) else np.nan}


def fig_skew(sk, S, titulo):
    fig = go.Figure()
    if not sk['puts'].empty:
        fig.add_trace(go.Scatter(x=sk['puts']['strike'], y=sk['puts']['impliedVolatility'] * 100, mode='lines+markers',
                                 line=dict(color=C_RED, width=2), marker=dict(size=5), name='Puts fuera del dinero'))
    if not sk['calls'].empty:
        fig.add_trace(go.Scatter(x=sk['calls']['strike'], y=sk['calls']['impliedVolatility'] * 100, mode='lines+markers',
                                 line=dict(color=C_GREEN, width=2), marker=dict(size=5), name='Calls fuera del dinero'))
    fig.add_vline(x=S, line_dash='dot', line_color=C_YELL, opacity=0.8)
    fig.update_layout(**PLOTLY_LAYOUT_GEX, height=360,
                      title=dict(text=titulo, font=dict(color=C_TEXT, size=13), y=0.98),
                      legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0, font=dict(size=10.5, color=C_TEXT)),
                      xaxis=dict(title='Precio de ejercicio', gridcolor=C_GRID),
                      yaxis=dict(title='Vol. implícita (%)', gridcolor=C_GRID),
                      margin=dict(l=10, r=10, t=80, b=10))
    return fig


# ── 6) Flujo inusual ──────────────────────────────────────────────────────

def calcular_flujo_inusual(d, S, mult, vol_min, ratio_min):
    """Contratos con volumen del día alto respecto del interés abierto (posiciones nuevas)."""
    x = d[d['volume'] > 0].copy()
    if x.empty:
        return x, x
    x['vol_oi'] = x['volume'] / x['openInterest'].replace(0, np.nan)
    x['prima'] = x['mid'] * x['volume'] * mult
    x['dist'] = (x['strike'] / S - 1) * 100
    cond = (x['volume'] >= vol_min) & ((x['vol_oi'] >= ratio_min) | (x['openInterest'] <= 0))
    sel = x[cond].sort_values(['prima', 'volume'], ascending=False, na_position='last')
    return x, sel


def fig_volumen_por_strike(x, S, rango):
    y = x[(x['strike'] >= S * (1 - rango)) & (x['strike'] <= S * (1 + rango))]
    v = y.pivot_table(index='strike', columns='tipo', values='volume', aggfunc='sum').reindex(columns=['C', 'P']).fillna(0.0)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=v.index, y=v['C'], name='Volumen Calls', marker_color=C_GREEN, opacity=0.85))
    fig.add_trace(go.Bar(x=v.index, y=-v['P'], name='Volumen Puts', marker_color=C_RED, opacity=0.85))
    fig.add_vline(x=S, line_dash='dot', line_color=C_YELL, opacity=0.8)
    fig.update_layout(**PLOTLY_LAYOUT_GEX, height=360, barmode='relative',
                      title=dict(text='Volumen operado hoy por precio de ejercicio (calls arriba, puts abajo)',
                                 font=dict(color=C_TEXT, size=13), y=0.98),
                      legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0, font=dict(size=10.5, color=C_TEXT)),
                      xaxis=dict(title='Precio de ejercicio', gridcolor=C_GRID),
                      yaxis=dict(title='Contratos', gridcolor=C_GRID),
                      margin=dict(l=10, r=10, t=80, b=10))
    return fig


# ── 7) DEX — exposición delta (delta publicada por CBOE) ──────────────────

def calcular_dex_por_strike(df, S, mult=100, rango=0.20):
    """DEX en dólares por precio de ejercicio = delta (CBOE) × interés abierto × multiplicador × precio.
    Calls con delta positiva, puts con delta negativa (tal cual la publica CBOE)."""
    x = df.copy()
    x['dex'] = x['delta'] * x['openInterest'] * mult * S
    x = x[(x['strike'] >= S * (1 - rango)) & (x['strike'] <= S * (1 + rango))]
    if x.empty:
        return pd.DataFrame(columns=['strike', 'dex_calls', 'dex_puts', 'neto'])
    piv = x.pivot_table(index='strike', columns='tipo', values='dex', aggfunc='sum') \
           .reindex(columns=['C', 'P']).fillna(0.0)
    piv['neto'] = piv['C'] + piv['P']
    return piv.reset_index().rename(columns={'C': 'dex_calls', 'P': 'dex_puts'})


def calcular_dex_por_vto(df, S, mult=100, rango=0.20):
    x = df.copy()
    x['dex'] = x['delta'] * x['openInterest'] * mult * S
    x = x[(x['strike'] >= S * (1 - rango)) & (x['strike'] <= S * (1 + rango))]
    if x.empty:
        return pd.DataFrame()
    pt = x.pivot_table(index='vto', columns='tipo', values='dex', aggfunc='sum') \
          .reindex(columns=['C', 'P']).fillna(0.0)
    res = pd.DataFrame({'dias': x.groupby('vto')['T'].first() * 365,
                        'calls': pt['C'], 'puts': pt['P'], 'neto': pt['C'] + pt['P']})
    return res


def fig_dex(piv, S):
    fig = go.Figure()
    fig.add_trace(go.Bar(x=piv['strike'], y=piv['dex_calls'] / 1e6, marker_color=C_GREEN, name='DEX Calls', opacity=0.85))
    fig.add_trace(go.Bar(x=piv['strike'], y=piv['dex_puts'] / 1e6, marker_color=C_RED, name='DEX Puts', opacity=0.85))
    fig.add_trace(go.Scatter(x=piv['strike'], y=piv['neto'] / 1e6, mode='lines', name='Neto por strike',
                             line=dict(color=C_TEXT, width=1.6)))
    fig.add_vline(x=S, line_dash='dot', line_color=C_YELL, opacity=0.8)
    fig.update_layout(**PLOTLY_LAYOUT_GEX, height=420, barmode='relative',
                      title=dict(text='DEX por precio de ejercicio (millones de US$ de exposición delta)',
                                 font=dict(color=C_TEXT, size=13), y=0.98),
                      legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0, font=dict(size=10.5, color=C_TEXT)),
                      xaxis=dict(title='Precio de ejercicio', gridcolor=C_GRID),
                      yaxis=dict(title='DEX (M US$)', gridcolor=C_GRID),
                      margin=dict(l=10, r=10, t=80, b=10))
    return fig


# ── 8) Vanna y Charm (Black-Scholes con la vol. implícita de CBOE) ────────

def calcular_vanna_charm(df, S, r, q, mult=100, rango=0.20):
    """Exposición Vanna (Δ de la delta por +1 punto de vol.) y Charm (Δ de la delta por día), en dólares.
    Convención igual al GEX: los creadores de mercado están largos calls y cortos puts.
    Devuelve (por_strike, por_vto) o (None, None) si no hay datos."""
    K = df['strike'].values
    T = df['T'].values
    sig = df['impliedVolatility'].values
    sq = np.sqrt(T)
    d1 = (np.log(S / K) + (r - q + 0.5 * sig ** 2) * T) / (sig * sq)
    d2 = d1 - sig * sq
    pdf, eq = norm.pdf(d1), np.exp(-q * T)

    vanna = -eq * pdf * d2 / sig                                              # ∂Δ/∂σ
    termino = eq * pdf * (2 * (r - q) * T - d2 * sig * sq) / (2 * T * sig * sq)
    es_c = (df['tipo'].values == 'C')
    charm = np.where(es_c, q * eq * norm.cdf(d1) - termino,                   # ∂Δ/∂t (por año)
                     -q * eq * norm.cdf(-d1) - termino)

    signo = np.where(es_c, 1.0, -1.0)
    base = signo * df['openInterest'].values * mult * S
    x = df[['strike', 'vto', 'T']].copy()
    x['vex'] = base * vanna * 0.01            # US$ de delta por cada +1 punto de vol.
    x['cex'] = base * charm / 365.0           # US$ de delta por cada día que pasa
    x = x[(x['strike'] >= S * (1 - rango)) & (x['strike'] <= S * (1 + rango))]
    x = x.replace([np.inf, -np.inf], np.nan).dropna(subset=['vex', 'cex'])
    if x.empty:
        return None, None
    por_strike = x.groupby('strike')[['vex', 'cex']].sum().reset_index()
    por_vto = x.groupby('vto').agg(dias=('T', lambda s: float(s.iloc[0]) * 365), vex=('vex', 'sum'), cex=('cex', 'sum'))
    return por_strike, por_vto


def fig_barras_signo(x, y, S, titulo, ytitulo):
    """Barras verdes si el valor es positivo y rojas si es negativo."""
    colores = np.where(np.asarray(y) >= 0, C_GREEN, C_RED)
    fig = go.Figure(go.Bar(x=x, y=np.asarray(y) / 1e6, marker_color=colores, opacity=0.85))
    fig.add_vline(x=S, line_dash='dot', line_color=C_YELL, opacity=0.8)
    fig.update_layout(**PLOTLY_LAYOUT_GEX, height=340,
                      title=dict(text=titulo, font=dict(color=C_TEXT, size=13)),
                      xaxis=dict(title='Precio de ejercicio', gridcolor=C_GRID),
                      yaxis=dict(title=ytitulo, gridcolor=C_GRID),
                      margin=dict(l=10, r=10, t=50, b=10), showlegend=False)
    return fig


# ── 9) Puente hacia "Valuación de Opciones" ───────────────────────────────

def publicar_puente_gex(simbolo, S, z, extra=None):
    """Guarda en session_state el punto de cambio de gamma, las paredes y (si hay) los strikes sugeridos.
    La calculadora lo lee con leer_puente_gex()."""
    p = {'simbolo': simbolo, 'spot': float(S), 'flip': z['flip'], 'call_wall': z['call_wall'],
         'put_wall': z['put_wall'], 'regimen': z['regimen'], 'gex_total': z['gex_total'],
         'hora': datetime.now().strftime('%H:%M:%S'), 'ts': time.time()}
    if extra:
        p.update(extra)
    st.session_state[CLAVE_PUENTE] = p


def leer_puente_gex(simbolo=None, max_min=30):
    """Lee el puente. Devuelve el dict o None si no hay, si es de otro símbolo o si tiene más de max_min minutos."""
    p = st.session_state.get(CLAVE_PUENTE)
    if not p:
        return None
    if simbolo and p.get('simbolo') != resolver_simbolo(simbolo)[1]:
        return None
    if (time.time() - p.get('ts', 0)) / 60.0 > max_min:
        return None
    return p


def sugerir_strikes_vendidos(df, S, z, vto, fila_em=None):
    """Sugiere un call y un put a vender en el vencimiento elegido.
    Call: primer strike listado en/por encima de la pared de Calls (si está sobre el precio).
    Put: primer strike listado en/por debajo de la pared de Puts (si está bajo el precio).
    Si la pared no sirve, usa el techo/piso del movimiento esperado y, en última instancia, ±5%."""
    g = df[df['vto'] == vto]
    strikes = np.sort(g['strike'].unique())
    if len(strikes) == 0:
        return []
    cw, pw = z['call_wall'], z['put_wall']

    if cw and cw > S:
        obj_c, base_c = cw, 'pared de Calls'
    elif fila_em is not None and not pd.isna(fila_em['alto']):
        obj_c, base_c = float(fila_em['alto']), 'techo del movimiento esperado'
    else:
        obj_c, base_c = S * 1.05, '+5% del precio'
    if pw and pw < S:
        obj_p, base_p = pw, 'pared de Puts'
    elif fila_em is not None and not pd.isna(fila_em['bajo']):
        obj_p, base_p = float(fila_em['bajo']), 'piso del movimiento esperado'
    else:
        obj_p, base_p = S * 0.95, '−5% del precio'

    arriba = strikes[strikes >= obj_c]
    abajo = strikes[strikes <= obj_p]
    out = []
    for lado, tipo, k, base, obj in (('Call vendido', 'C', float(arriba[0]) if len(arriba) else None, base_c, obj_c),
                                      ('Put vendido', 'P', float(abajo[-1]) if len(abajo) else None, base_p, obj_p)):
        if k is None:
            continue
        fila = g[(g['strike'] == k) & (g['tipo'] == tipo)]
        if fila.empty:
            continue
        f = fila.iloc[0]
        delta = float(f['delta']) if not pd.isna(f['delta']) else np.nan
        out.append({'lado': lado, 'tipo': tipo, 'strike': k, 'base': base, 'objetivo': float(obj),
                    'dist_pct': (k / S - 1) * 100,
                    'prima_mid': float(f['mid']) if not pd.isna(f['mid']) else np.nan,
                    'iv': float(f['impliedVolatility']) * 100,
                    'delta': delta,
                    'prob_itm': abs(delta) * 100 if not np.isnan(delta) else np.nan,
                    'oi': float(f['openInterest'])})
    return out


# ── Render de las pestañas ────────────────────────────────────────────────

def _render_analisis_extra(d, df, S, r, q, mult, rango_pct, clave, z, simbolo):
    st.markdown('---')
    st.markdown('### 🔬 Análisis complementarios (mismos datos de CBOE)')
    st.caption('Se calculan con la misma descarga de arriba (sin pedidos extra) y sobre los vencimientos que elegiste.')

    dias_map = d.groupby('vto')['dias'].first().to_dict()
    etiq = {v: _etiqueta_vto(v, dd) for v, dd in dias_map.items()}
    rango = rango_pct / 100

    tabs = st.tabs(['⚖️ Put/Call', '📌 Max Pain', '📏 Mov. esperado', '🗓️ GEX por vencimiento',
                    '🌊 Vol. implícita', '🔥 Flujo inusual', '🎯 DEX (delta)', '🌀 Vanna y Charm',
                    '🌉 Puente a Valuación'])

    # ───────────── 1) PUT / CALL ─────────────
    with tabs[0]:
        t_pc, tot = calcular_put_call(d)
        m1, m2, m3, m4 = st.columns(4)
        with m1: st.metric('Put/Call por interés abierto', f"{tot['P/C OI']:.2f}" if not pd.isna(tot['P/C OI']) else 'N/D')
        with m2: st.metric('Put/Call por volumen', f"{tot['P/C Vol.']:.2f}" if not pd.isna(tot['P/C Vol.']) else 'N/D')
        with m3: st.metric('Interés abierto Calls', _fmt_ent(tot['OI Calls']))
        with m4: st.metric('Interés abierto Puts', _fmt_ent(tot['OI Puts']))

        st.plotly_chart(fig_put_call(t_pc, etiq), use_container_width=True, key='gex_fig_pc')

        t_show = t_pc.copy()
        t_show.insert(0, 'Vencimiento', [etiq.get(v, v) for v in t_show.index])
        st.dataframe(t_show.reset_index(drop=True).drop(columns=['Días']), use_container_width=True, hide_index=True,
                     column_config={'P/C OI': st.column_config.NumberColumn(format='%.2f'),
                                    'P/C Vol.': st.column_config.NumberColumn(format='%.2f'),
                                    'OI Calls': st.column_config.NumberColumn(format='%.0f'),
                                    'OI Puts': st.column_config.NumberColumn(format='%.0f'),
                                    'Vol. Calls': st.column_config.NumberColumn(format='%.0f'),
                                    'Vol. Puts': st.column_config.NumberColumn(format='%.0f')})

        vol_txt = (f"Por **volumen** operado hoy: **{tot['P/C Vol.']:.2f}** — {_lectura_put_call(tot['P/C Vol.'])}."
                   if not pd.isna(tot['P/C Vol.']) else
                   "Todavía no hay volumen operado hoy (mercado cerrado o sin datos), así que solo se puede leer el interés abierto.")
        render_explicacion('Cómo leer el Put/Call y cómo usarlo', f"""
**Qué es**
Es la cantidad de **puts dividida por la cantidad de calls**. Un put es una apuesta (o cobertura) a la baja y un call, al alza. Un ratio de 1 significa la misma cantidad de ambos. Se mide de dos formas:
- **Por interés abierto:** cuántos contratos están abiertos hoy. Es la foto del **posicionamiento acumulado**.
- **Por volumen:** cuántos se operaron hoy. Es el **ánimo del día**, más cambiante.

**Datos de hoy**
- Por interés abierto: **{tot['P/C OI']:.2f}** — {_lectura_put_call(tot['P/C OI'])}.
- {vol_txt}

**Cómo leerlo**
- **Menor a 0.7:** predominan los calls. Suele reflejar optimismo, pero a niveles muy bajos puede ser **exceso de euforia**.
- **Entre 0.7 y 1.1:** zona equilibrada.
- **Mayor a 1.1:** predominan los puts. Puede ser pesimismo o simplemente **coberturas** de gente que tiene acciones. A niveles muy altos suele coincidir con **miedo extremo**, que a veces marca zonas de suelo.
- Mirá el gráfico por vencimiento: si los vencimientos cercanos tienen un ratio muy distinto de los lejanos, el posicionamiento táctico (corto plazo) no coincide con el de fondo.

**Cómo sacarle provecho**
- **No compares con un número universal.** Los índices (SPX) y los ETFs tienen ratios normalmente más altos que 1 por las coberturas; una acción individual suele estar entre 0.4 y 0.9. Compará contra lo que es habitual **para ese mismo activo**.
- Sirve como **termómetro de sentimiento** y para detectar extremos, no como señal de entrada.
- Combinalo con el régimen de gamma de arriba: ratio alto + gamma negativa es una combinación más frágil que ratio alto + gamma positiva.

**Límites:** un put puede ser una cobertura o una apuesta y el dato no distingue cuál. Los vencimientos elegidos en el control de arriba determinan qué se suma.
""")

    # ───────────── 2) MAX PAIN ─────────────
    with tabs[1]:
        t_mp, curvas = calcular_max_pain(d, S, mult)
        if t_mp.empty:
            st.info('No hay interés abierto suficiente para calcular el Max Pain.')
        else:
            opciones = t_mp['vto'].tolist()
            vto_sel = st.selectbox('Vencimiento', opciones, format_func=lambda v: etiq.get(v, v), key=f'gex_mp_vto_{clave}')
            fila = t_mp[t_mp['vto'] == vto_sel].iloc[0]
            k1, k2, k3 = st.columns(3)
            with k1: st.metric('Max Pain', fmt_precio(fila['max_pain']))
            with k2: st.metric('Distancia vs. precio actual', f"{fila['dist_pct']:+.1f}%")
            with k3: st.metric('Interés abierto total', _fmt_ent(fila['oi_total']))

            strikes_c, pain_c = curvas[vto_sel]
            st.plotly_chart(fig_max_pain(strikes_c, pain_c, float(fila['max_pain']), S,
                                         f'Max Pain — {etiq.get(vto_sel, vto_sel)}'),
                            use_container_width=True, key='gex_fig_maxpain')

            tabla_mp = t_mp.copy()
            tabla_mp['Vencimiento'] = [etiq.get(v, v) for v in tabla_mp['vto']]
            st.dataframe(tabla_mp[['Vencimiento', 'max_pain', 'dist_pct', 'oi_total']].rename(columns={
                'max_pain': 'Max Pain', 'dist_pct': 'Distancia vs. precio %', 'oi_total': 'Interés abierto'}),
                use_container_width=True, hide_index=True,
                column_config={'Max Pain': st.column_config.NumberColumn(format='%.2f'),
                               'Distancia vs. precio %': st.column_config.NumberColumn(format='%+.2f'),
                               'Interés abierto': st.column_config.NumberColumn(format='%.0f')})

            dir_txt = 'por encima' if fila['dist_pct'] > 0 else 'por debajo'
            render_explicacion('Cómo leer el Max Pain y cómo usarlo', f"""
**Qué es**
El **Max Pain** es el precio de ejercicio al que, si el activo cerrara justo ahí el día del vencimiento, **los compradores de opciones en conjunto perderían la mayor cantidad de dinero** (y los vendedores, que suelen ser los grandes creadores de mercado, quedarían mejor parados). La curva del gráfico suma, para cada precio final posible, lo que valdrían todas las opciones abiertas: el **punto más bajo de la curva** es el Max Pain.

**Datos de hoy** ({etiq.get(vto_sel, vto_sel)})
- Max Pain: **{fila['max_pain']:,.2f}**, que está **{abs(fila['dist_pct']):.1f}% {dir_txt}** del precio actual ({S:,.2f}).

**Cómo leerlo**
- La idea es que, cerca del vencimiento, el precio tiende a **acercarse** a ese nivel por las coberturas de los creadores de mercado (el llamado *pinning*).
- Cuanto **más profundo y angosto** es el valle de la curva, más marcado es el imán. Si la curva es plana, no hay un nivel claro.
- Si el Max Pain está **lejos** del precio, la atracción es débil: el precio puede tener otros motivos para moverse.

**Cómo sacarle provecho**
- Es más útil en **vencimientos mensuales y semanales grandes** y en los **últimos 1 a 3 días** antes de expirar. A un mes vista casi no dice nada.
- Sirve para elegir strikes de estrategias de rango (Cóndor de hierro, vender prima): un Max Pain cercano al precio favorece la lógica de que el precio se quede quieto.
- Cruzalo con las **paredes de Calls y Puts** del GEX: si coinciden cerca del mismo nivel, ese nivel gana peso.

**Límites:** es una teoría **discutida**, no una ley; los datos que usa (interés abierto del día anterior) no muestran quién compró y quién vendió, y una noticia fuerte lo pasa por encima.
""")

    # ───────────── 3) MOVIMIENTO ESPERADO ─────────────
    with tabs[2]:
        t_em = calcular_movimiento_esperado(d, S)
        if t_em.empty:
            st.info('No hay cotizaciones suficientes de compra/venta para calcular el straddle (mercado cerrado o contratos sin precio).')
        else:
            cand = t_em[t_em['dias'] >= 1]
            prox = (cand if not cand.empty else t_em).iloc[0]
            e1, e2, e3, e4 = st.columns(4)
            with e1: st.metric('Próximo vencimiento', f"{etiq.get(prox['vto'], prox['vto'])}")
            with e2: st.metric('Movimiento esperado', f"± {prox['straddle']:,.2f}")
            with e3: st.metric('En porcentaje', f"± {prox['em_pct']:.1f}%")
            with e4: st.metric('Vol. implícita ATM', f"{prox['iv_atm']:.1f}%" if not pd.isna(prox['iv_atm']) else 'N/D')

            st.plotly_chart(fig_movimiento_esperado(t_em, S), use_container_width=True, key='gex_fig_em')

            t_show = t_em.copy()
            t_show['Vencimiento'] = [etiq.get(v, v) for v in t_show['vto']]
            st.dataframe(t_show[['Vencimiento', 'strike_atm', 'straddle', 'em_pct', 'bajo', 'alto', 'iv_atm', 'sigma_pct']].rename(columns={
                'strike_atm': 'Strike ATM', 'straddle': 'Straddle', 'em_pct': '± % (straddle)', 'bajo': 'Piso', 'alto': 'Techo',
                'iv_atm': 'Vol. impl. ATM %', 'sigma_pct': '± % (1σ por IV)'}),
                use_container_width=True, hide_index=True,
                column_config={c: st.column_config.NumberColumn(format='%.2f')
                               for c in ['Strike ATM', 'Straddle', '± % (straddle)', 'Piso', 'Techo', 'Vol. impl. ATM %', '± % (1σ por IV)']})

            render_explicacion('Cómo leer el movimiento esperado y cómo usarlo', f"""
**Qué es**
Es el rango de precios que **el mercado está descontando** hasta cada vencimiento. Se calcula con el **straddle ATM**: la suma del precio de un call y un put con el precio de ejercicio más cercano al precio actual. Como quien compra ese straddle gana si el precio se mueve más que eso, su costo es una estimación de **cuánto se espera que se mueva** el activo.

**Datos de hoy**
- Hasta **{etiq.get(prox['vto'], prox['vto'])}** el mercado descuenta un movimiento de aproximadamente **± {prox['straddle']:,.2f}** (**± {prox['em_pct']:.1f}%**): rango **{prox['bajo']:,.2f} a {prox['alto']:,.2f}**.

**Cómo leerlo**
- La línea verde/roja es el **techo y piso** según el straddle. Las líneas grises punteadas son **±1 desvío estándar** calculado con la vol. implícita ATM (algo más amplio, porque el straddle equivale a ~0.8 desvíos).
- El cono se **ensancha con el tiempo**, pero no en línea recta: crece con la raíz de los días.
- Los porcentajes de la tabla te dejan comparar vencimientos entre sí y contra otros activos.

**Cómo sacarle provecho**
- **Para elegir strikes:** vender opciones **fuera** del cono da más margen de seguridad; vender **adentro** cobra más prima pero con más riesgo.
- **Para comprar opciones:** si tu escenario espera un movimiento **mayor** que el descontado, las opciones están baratas; si esperás uno menor, están caras.
- Compará este rango con el del **Monte Carlo** de la calculadora de opciones: si difieren mucho, el mercado y la estadística histórica no coinciden y conviene entender por qué (eventos como resultados, por ejemplo).

**Límites:** el straddle es una aproximación; usa precios con retraso de ~15 min y en contratos poco líquidos el punto medio puede ser engañoso. Es lo que se descuenta, no una predicción.
""")

    # ───────────── 4) GEX POR VENCIMIENTO ─────────────
    with tabs[3]:
        res_v, heat = calcular_gex_por_vto(df, S, r, q, mult, rango)
        if res_v is None:
            st.info('No hay contratos con interés abierto cerca del precio para calcular el GEX por vencimiento.')
        else:
            tot_abs = float(res_v['abs'].sum())
            share_prim = float(res_v['abs'].iloc[0] / tot_abs * 100) if tot_abs > 0 else np.nan
            dom = res_v['abs'].idxmax()
            v1, v2, v3 = st.columns(3)
            with v1: st.metric('GEX absoluto en el 1.º vencimiento', f'{share_prim:.0f}%')
            with v2: st.metric('Vencimiento dominante', etiq.get(dom, dom))
            with v3: st.metric('GEX neto total', f"{res_v['neto'].sum() / 1e6:,.1f} M US$")

            st.plotly_chart(fig_gex_por_vto(res_v, etiq), use_container_width=True, key='gex_fig_vto')
            st.plotly_chart(fig_heatmap_gex(heat, S, etiq), use_container_width=True, key='gex_fig_heat')

            concentra = ('muy concentrado en el vencimiento más cercano: las paredes pueden **desaparecer o moverse** apenas expire'
                         if share_prim >= 50 else
                         'repartido entre varios vencimientos: los niveles son **más estables** en el tiempo')
            render_explicacion('Cómo leer el GEX por vencimiento y cómo usarlo', f"""
**Qué muestra**
El mismo GEX de arriba, pero **separado por fecha de vencimiento**. Importa porque la gamma de una opción **desaparece cuando vence**: si casi todo el gamma está en una sola fecha, el régimen puede cambiar de un día para el otro.

- **Gráfico de barras:** cuánto gamma de calls (verde) y de puts (rojo) hay en cada vencimiento; el rombo es el neto.
- **Mapa de calor:** cada celda es un **precio de ejercicio en un vencimiento**. Verde intenso = mucho gamma de calls; rojo intenso = mucho gamma de puts. La línea amarilla es el precio actual.

**Datos de hoy**
- El **{share_prim:.0f}%** del gamma total está en el vencimiento más cercano: el panorama está {concentra}.
- El vencimiento con más peso es **{etiq.get(dom, dom)}**.

**Cómo leerlo**
- **Barras muy altas en el primer vencimiento:** después de esa fecha, las coberturas de los creadores de mercado se "aflojan" y el efecto amortiguador o amplificador se debilita. Muchas veces el mercado se mueve distinto **después** de un vencimiento grande.
- **Celdas intensas alineadas en vertical** (el mismo strike en varios vencimientos): es un nivel muy relevante y **persistente**, no solo de un día.
- **Celda intensa solo en el primer vencimiento:** nivel de corto plazo, que puede caducar rápido.

**Cómo sacarle provecho**
- Antes de confiar en una pared, fijate **de qué vencimiento viene**. Una pared que solo existe en el vencimiento de esta semana no sirve para una operación de un mes.
- Ubicá los **vencimientos grandes** (mensuales, trimestrales) en tu calendario: son días con más probabilidad de cambio de comportamiento.
- Si querés una lectura más de fondo, subí la cantidad de vencimientos en el control de arriba para que los cercanos no tapen todo.

**Límites:** usa el interés abierto del día anterior y asume creadores de mercado largos calls y cortos puts, como el GEX principal.
""")

    # ───────────── 5) VOL. IMPLÍCITA ─────────────
    with tabs[4]:
        t_iv = calcular_estructura_iv(d, S)
        st.markdown('#### Estructura temporal')
        if t_iv.empty:
            st.info('No hay vol. implícita válida para armar la estructura temporal.')
        else:
            st.plotly_chart(fig_estructura_iv(t_iv), use_container_width=True, key='gex_fig_iv_term')
            if len(t_iv) >= 2:
                delante, atras = float(t_iv['iv_atm'].iloc[0]), float(t_iv['iv_atm'].iloc[-1])
                pend = atras - delante
                if pend > 1:
                    forma, forma_txt = 'contango', 'la vol. implícita **sube** con el plazo: situación normal, sin estrés inmediato'
                elif pend < -1:
                    forma, forma_txt = 'backwardation', 'la vol. implícita de corto plazo es **más alta** que la de largo: el mercado espera turbulencia cercana (un evento, o estrés)'
                else:
                    forma, forma_txt = 'plana', 'la vol. implícita es **similar** en todos los plazos'
                st.metric('Forma de la curva', forma.capitalize(), f'{pend:+.1f} puntos entre el primer y el último vencimiento')
            else:
                forma, forma_txt, delante, atras = 'N/D', 'hace falta más de un vencimiento para comparar', np.nan, np.nan

            render_explicacion('Cómo leer la estructura temporal y cómo usarla', f"""
**Qué muestra**
La **volatilidad implícita ATM** (la que descuenta el mercado) para cada vencimiento. Permite ver **cuánto movimiento se espera** en cada plazo.

**Datos de hoy**
- Forma actual: **{forma}** — {forma_txt}.
- Primer vencimiento: **{delante:.1f}%** · último elegido: **{atras:.1f}%**.

**Cómo leerlo**
- **Contango (curva ascendente):** lo normal en mercados tranquilos; el futuro lejano tiene más incertidumbre.
- **Backwardation (curva descendente):** el corto plazo cotiza **más caro** que el largo. Suele aparecer ante un **evento próximo** (resultados, decisiones de bancos centrales) o en momentos de estrés.
- **Un escalón** en un vencimiento puntual suele indicar un **evento** que cae en esa fecha.

**Cómo sacarle provecho**
- **Comprar opciones** antes de un evento cuando la vol. corta todavía no subió; después del evento la vol. suele **caer** ("aplastamiento de volatilidad") aunque el precio se mueva a tu favor.
- **Vender opciones** en el tramo más caro de la curva puede tener ventaja, con el riesgo de que el evento sí sorprenda.
- Elegir vencimientos donde la vol. sea **relativamente baja** al comprar y **relativamente alta** al vender es la idea de fondo.

**Límites:** el primer vencimiento (0 a 2 días) es muy ruidoso y puede distorsionar la comparación.
""")

        st.markdown('#### Skew (sonrisa de volatilidad)')
        vtos_iv = [v for v in sorted(dias_map) if not calcular_skew_vto(d, S, v, rango)['puts'].empty
                   or not calcular_skew_vto(d, S, v, rango)['calls'].empty]
        if not vtos_iv:
            st.info('No hay vol. implícita válida por precio de ejercicio para armar el skew.')
        else:
            vto_skew = st.selectbox('Vencimiento para el skew', vtos_iv, format_func=lambda v: etiq.get(v, v),
                                    key=f'gex_skew_vto_{clave}')
            sk = calcular_skew_vto(d, S, vto_skew, rango)
            s1, s2, s3, s4 = st.columns(4)
            with s1: st.metric('IV puts a 90% del precio', f"{sk['iv_p90']:.1f}%" if not np.isnan(sk['iv_p90']) else 'N/D')
            with s2: st.metric('IV ATM', f"{sk['iv_atm']:.1f}%" if not np.isnan(sk['iv_atm']) else 'N/D')
            with s3: st.metric('IV calls a 110% del precio', f"{sk['iv_c110']:.1f}%" if not np.isnan(sk['iv_c110']) else 'N/D')
            with s4: st.metric('Skew (put 90% − call 110%)', f"{sk['skew']:+.1f} pts" if not np.isnan(sk['skew']) else 'N/D')

            st.plotly_chart(fig_skew(sk, S, f'Skew de vol. implícita — {etiq.get(vto_skew, vto_skew)}'),
                            use_container_width=True, key='gex_fig_skew')

            if np.isnan(sk['skew']):
                skew_txt = 'no hay strikes suficientes a 90% y 110% del precio para medirlo'
            elif sk['skew'] > 3:
                skew_txt = 'los **puts lejanos son claramente más caros** que los calls: el mercado paga más por protección a la baja (skew bajista, lo más habitual)'
            elif sk['skew'] < -3:
                skew_txt = 'los **calls lejanos son más caros** que los puts: el mercado paga por potencial alcista (skew alcista, típico de activos especulativos)'
            else:
                skew_txt = 'la curva es **bastante plana**: no hay una preferencia marcada por protección ni por especulación'
            render_explicacion('Cómo leer el skew y cómo usarlo', f"""
**Qué muestra**
La vol. implícita **según el precio de ejercicio**, para un mismo vencimiento. Rojo: puts por debajo del precio (protección a la baja). Verde: calls por encima del precio (apuestas al alza). Si todas las opciones tuvieran la misma vol., sería una línea horizontal.

**Datos de hoy** ({etiq.get(vto_skew, vto_skew)})
- Skew (put 90% − call 110%): **{sk['skew'] if not np.isnan(sk['skew']) else float('nan'):+.1f} puntos** — {skew_txt}.

**Cómo leerlo**
- **Rama roja más alta que la verde** (lo más habitual en acciones e índices): el mercado le tiene más miedo a una caída que le tiene ganas a una suba.
- **Curva en forma de U** (sonrisa): tanto puts como calls lejanos son caros; el mercado espera movimientos grandes en **cualquier** dirección.
- **Skew que se vuelve muy pronunciado** de un día al otro: aumenta la demanda de protección.

**Cómo sacarle provecho**
- **Vender un put** fuera del dinero cobra una prima "inflada" por el skew (pero es también donde está el riesgo de cola).
- **Comprar un vertical alcista con calls** suele salir relativamente barato cuando el skew favorece a los puts.
- En un **Cóndor de hierro**, el ala de puts cobra más que la de calls: no esperes simetría.

**Límites:** en strikes lejanos hay poca liquidez y la vol. implícita puede ser ruidosa. Se muestran solo contratos con interés abierto o volumen.
""")

    # ───────────── 6) FLUJO INUSUAL ─────────────
    with tabs[5]:
        x_all, _ = calcular_flujo_inusual(d, S, mult, 0, 0)
        if x_all.empty:
            st.info('No hay volumen operado hoy en estos vencimientos (mercado cerrado o sin operaciones). '
                    'Volvé a mirar durante la rueda: el volumen se acumula a lo largo del día.')
        else:
            f1, f2 = st.columns(2)
            with f1:
                vol_min = st.slider('Volumen mínimo del contrato', 10, 5000, 200, 10, key=f'gex_flow_vmin_{clave}',
                                    help='Ignora contratos con poco volumen.')
            with f2:
                ratio_min = st.slider('Volumen / interés abierto mínimo', 0.5, 10.0, 1.0, 0.5, key=f'gex_flow_ratio_{clave}',
                                      help='1.0 = hoy se operó tanto como todo lo que había abierto ayer.')
            x_all, sel = calcular_flujo_inusual(d, S, mult, vol_min, ratio_min)

            vc = float(x_all.loc[x_all['tipo'] == 'C', 'volume'].sum())
            vp = float(x_all.loc[x_all['tipo'] == 'P', 'volume'].sum())
            g1, g2, g3, g4 = st.columns(4)
            with g1: st.metric('Volumen total Calls', _fmt_ent(vc))
            with g2: st.metric('Volumen total Puts', _fmt_ent(vp))
            with g3: st.metric('Contratos inusuales', f'{len(sel)}')
            with g4:
                top_prima = sel['prima'].max() if not sel.empty and sel['prima'].notna().any() else np.nan
                st.metric('Mayor prima operada', f'US$ {top_prima:,.0f}' if not np.isnan(top_prima) else 'N/D')

            st.plotly_chart(fig_volumen_por_strike(x_all, S, rango), use_container_width=True, key='gex_fig_flujo')

            if sel.empty:
                st.info('Ningún contrato cumple los filtros actuales. Bajá el volumen mínimo o el ratio Volumen/OI.')
            else:
                tabla = sel.head(30).copy()
                tabla['Vencimiento'] = [etiq.get(v, v) for v in tabla['vto']]
                tabla['Tipo'] = np.where(tabla['tipo'] == 'C', 'Call', 'Put')
                st.dataframe(tabla[['Vencimiento', 'Tipo', 'strike', 'dist', 'volume', 'openInterest', 'vol_oi',
                                    'impliedVolatility', 'prima']].rename(columns={
                    'strike': 'Precio de ejercicio', 'dist': 'Distancia al precio %', 'volume': 'Volumen',
                    'openInterest': 'Interés abierto', 'vol_oi': 'Vol./OI', 'impliedVolatility': 'Vol. implícita',
                    'prima': 'Prima aprox. (US$)'}),
                    use_container_width=True, hide_index=True,
                    column_config={'Precio de ejercicio': st.column_config.NumberColumn(format='%.2f'),
                                   'Distancia al precio %': st.column_config.NumberColumn(format='%+.1f'),
                                   'Volumen': st.column_config.NumberColumn(format='%.0f'),
                                   'Interés abierto': st.column_config.NumberColumn(format='%.0f'),
                                   'Vol./OI': st.column_config.NumberColumn(format='%.1f'),
                                   'Vol. implícita': st.column_config.NumberColumn(format='%.2f'),
                                   'Prima aprox. (US$)': st.column_config.NumberColumn(format='%.0f')})

            if not sel.empty:
                c0 = sel.iloc[0]
                top_txt = (f"El contrato inusual de mayor prima es un **{'Call' if c0['tipo'] == 'C' else 'Put'} de precio de ejercicio "
                           f"{c0['strike']:,.2f}** ({etiq.get(c0['vto'], c0['vto'])}), con **{c0['volume']:,.0f} contratos** operados hoy "
                           f"contra {c0['openInterest']:,.0f} de interés abierto.")
            else:
                top_txt = 'Con los filtros actuales no hay contratos que se destaquen.'
            render_explicacion('Cómo leer el flujo inusual y cómo usarlo', f"""
**Qué muestra**
Los contratos donde **hoy se operó mucho más de lo habitual** respecto de lo que había abierto ayer (el interés abierto que publica CBOE es del día anterior). Si el volumen supera al interés abierto, esos contratos son en gran parte **posiciones nuevas**, no cierres de posiciones viejas.

**Datos de hoy**
- Volumen total: **{_fmt_ent(vc)} calls** y **{_fmt_ent(vp)} puts**.
- {top_txt}

**Cómo leerlo**
- **Vol./OI mayor a 1:** se operó más que todo lo abierto ayer. Cuanto más alto, más "nuevo" es el interés.
- **Prima aprox.:** cuánto dinero se movió (precio medio × volumen × multiplicador). Un contrato con muchísimo volumen pero prima chica (opciones muy baratas, lejanas) importa menos que uno con prima grande.
- **Distancia al precio:** contratos muy lejanos suelen ser apuestas especulativas; los cercanos, coberturas o posiciones direccionales.
- El gráfico de barras te muestra en **qué precios de ejercicio** se concentró la actividad de hoy.

**Cómo sacarle provecho**
- Es un **radar de atención**: te avisa dónde mirar (un vencimiento, un nivel), no qué hacer.
- Un **grupo de contratos inusuales del mismo lado y vencimiento**, alineados con una noticia o un evento próximo, es más significativo que un contrato aislado.
- Combinalo con el **GEX**: actividad fuerte justo en una pared o cerca del punto de cambio de gamma puede reforzar o debilitar ese nivel.

**Límites (importante)**
- **No se sabe si fue una compra o una venta.** Un call muy operado puede ser alguien comprando o alguien vendiendo. Tampoco distingue una cobertura de una apuesta.
- Los datos tienen ~15 minutos de retraso y el volumen es **acumulado del día**: a media rueda la lectura es parcial.
- Con el mercado cerrado, muestra el volumen final del último día operado.
""")

    # ───────────── 7) DEX (exposición delta) ─────────────
    with tabs[6]:
        piv_d = calcular_dex_por_strike(df, S, mult, rango)
        if piv_d.empty:
            st.info('No hay contratos con interés abierto cerca del precio para calcular el DEX.')
        else:
            dex_c, dex_p = float(piv_d['dex_calls'].sum()), float(piv_d['dex_puts'].sum())
            dex_n = dex_c + dex_p
            bruto = abs(dex_c) + abs(dex_p)
            sesgo = dex_n / bruto * 100 if bruto > 0 else np.nan
            equiv = dex_n / S

            x1, x2, x3, x4 = st.columns(4)
            with x1: st.metric('DEX neto', _fmt_musd(dex_n))
            with x2: st.metric('DEX de Calls', _fmt_musd(dex_c))
            with x3: st.metric('DEX de Puts', _fmt_musd(dex_p))
            with x4: st.metric('Sesgo direccional', f'{sesgo:+.0f}%' if not np.isnan(sesgo) else 'N/D')

            st.plotly_chart(fig_dex(piv_d, S), use_container_width=True, key='gex_fig_dex')

            res_dv = calcular_dex_por_vto(df, S, mult, rango)
            if not res_dv.empty:
                t_dv = res_dv.copy()
                t_dv.insert(0, 'Vencimiento', [etiq.get(v, v) for v in t_dv.index])
                t_dv = t_dv.reset_index(drop=True).drop(columns=['dias'])
                for c in ('calls', 'puts', 'neto'):
                    t_dv[c] = t_dv[c] / 1e6
                st.dataframe(t_dv.rename(columns={'calls': 'DEX Calls (M US$)', 'puts': 'DEX Puts (M US$)',
                                                  'neto': 'DEX neto (M US$)'}),
                             use_container_width=True, hide_index=True,
                             column_config={c: st.column_config.NumberColumn(format='%.1f')
                                            for c in ['DEX Calls (M US$)', 'DEX Puts (M US$)', 'DEX neto (M US$)']})

            if sesgo >= 25:
                sesgo_txt = 'la exposición está **claramente inclinada al alza**: pesan más las opciones que ganan si el precio sube'
            elif sesgo <= -25:
                sesgo_txt = 'la exposición está **claramente inclinada a la baja**: pesan más las opciones que ganan si el precio cae'
            else:
                sesgo_txt = 'la exposición está **bastante equilibrada** entre alza y baja'
            signo_txt = 'largo' if dex_n > 0 else 'corto'
            render_explicacion('Cómo leer el DEX (exposición delta) y cómo usarlo', f"""
**Qué es**
La **delta** de una opción dice cuánto cambia su valor si el activo se mueve 1 dólar: un call tiene delta positiva (entre 0 y 1) y un put, negativa (entre −1 y 0). El **DEX** suma la delta de **todas las opciones abiertas**, multiplicada por el interés abierto, el multiplicador del contrato y el precio. El resultado es una cifra en dólares que responde: *"¿cuánta exposición direccional al subyacente hay metida en las opciones?"*. La delta es **la que publica CBOE** en cada contrato; solo se completa con Black-Scholes en los pocos casos donde CBOE no la trae.

**Datos de hoy**
- DEX neto: **{_fmt_musd(dex_n)}**, equivalente a estar **{signo_txt}** en unas **{abs(equiv):,.0f} unidades** del subyacente.
- Calls: **{_fmt_musd(dex_c)}** · Puts: **{_fmt_musd(dex_p)}**.
- Sesgo direccional: **{sesgo:+.0f}%** (neto dividido por el total en valor absoluto) — {sesgo_txt}.

**Cómo leerlo**
- **Barras verdes (calls):** exposición alcista. **Barras rojas (puts):** exposición bajista. La línea blanca es el neto de cada strike.
- **DEX neto positivo:** el conjunto de opciones abiertas se comporta como una posición **larga** del activo. **Negativo:** como una posición **corta**.
- **El sesgo** te dice qué tan desparejo está: cerca de 0% = fuerzas compensadas; cerca de ±100% = casi todo del mismo lado.
- Si hay **barras grandes en un strike puntual**, ahí hay mucha exposición direccional concentrada.

**Cómo sacarle provecho**
- **Complementa al GEX:** el GEX te dice *qué tan fuerte* reaccionan los creadores de mercado ante un movimiento (gamma); el DEX te dice *hacia qué lado* está inclinada la exposición (delta). Un régimen de gamma negativa con DEX muy inclinado hacia un lado marca un mercado más propenso a movimientos bruscos en la dirección en que las coberturas se desarman.
- Si los creadores de mercado están del otro lado de estas posiciones (es lo habitual), **su cobertura tiene el signo contrario**: cuando el precio se mueve y las deltas cambian, ellos compran o venden el subyacente para reajustarse. Ese es el origen del efecto de amortiguación o amplificación que ves en el GEX.
- Mirá la tabla por vencimiento: si el DEX está concentrado en el primer vencimiento, esa exposición **desaparece al expirar**.

**Límites**
- El interés abierto no dice quién compró y quién vendió: el DEX muestra la **exposición del conjunto**, no la posición real de los creadores de mercado. Por eso acá los puts figuran con su delta negativa tal cual la publica CBOE, y no con la convención "creadores largos calls / cortos puts" del GEX.
- Usa el interés abierto del día anterior y datos con ~15 min de retraso.
- No es una señal de compra o venta por sí solo.
""")

    # ───────────── 8) VANNA Y CHARM ─────────────
    with tabs[7]:
        por_strike, por_vto_vc = calcular_vanna_charm(df, S, r, q, mult, rango)
        if por_strike is None:
            st.info('No hay contratos con interés abierto cerca del precio para calcular Vanna y Charm.')
        else:
            vex_n, cex_n = float(por_strike['vex'].sum()), float(por_strike['cex'].sum())
            flujo_vol = vex_n            # si la vol. BAJA 1 punto, los creadores compran +vex (venden si es negativo)
            flujo_tiempo = -cex_n        # por el paso de 1 día, la cobertura se ajusta con signo contrario a la delta

            n1, n2, n3, n4 = st.columns(4)
            with n1: st.metric('Vanna neta (por +1 pt de vol.)', _fmt_musd(vex_n))
            with n2: st.metric('Charm neto (por día)', _fmt_musd(cex_n))
            with n3: st.metric('Si la vol. baja 1 pt', _txt_flujo(flujo_vol))
            with n4: st.metric('Por el paso de 1 día', _txt_flujo(flujo_tiempo))

            st.plotly_chart(fig_barras_signo(por_strike['strike'], por_strike['vex'], S,
                                             'Vanna por precio de ejercicio (M US$ de delta por +1 punto de vol.)',
                                             'Vanna (M US$)'),
                            use_container_width=True, key='gex_fig_vanna')
            st.plotly_chart(fig_barras_signo(por_strike['strike'], por_strike['cex'], S,
                                             'Charm por precio de ejercicio (M US$ de delta por día)',
                                             'Charm (M US$ / día)'),
                            use_container_width=True, key='gex_fig_charm')

            t_vc = por_vto_vc.copy()
            t_vc.insert(0, 'Vencimiento', [etiq.get(v, v) for v in t_vc.index])
            t_vc = t_vc.reset_index(drop=True).drop(columns=['dias'])
            t_vc['vex'] = t_vc['vex'] / 1e6
            t_vc['cex'] = t_vc['cex'] / 1e6
            st.dataframe(t_vc.rename(columns={'vex': 'Vanna (M US$ por +1 pt vol.)', 'cex': 'Charm (M US$ por día)'}),
                         use_container_width=True, hide_index=True,
                         column_config={c: st.column_config.NumberColumn(format='%.2f')
                                        for c in ['Vanna (M US$ por +1 pt vol.)', 'Charm (M US$ por día)']})

            if vex_n > 0:
                vanna_txt = ('si la volatilidad **baja**, los creadores de mercado tienden a **comprar** el subyacente '
                             '(viento a favor para el precio); si **sube**, tienden a **venderlo**')
            else:
                vanna_txt = ('si la volatilidad **baja**, los creadores de mercado tienden a **vender** el subyacente; '
                             'si **sube**, tienden a **comprarlo** (efecto poco habitual)')
            if flujo_tiempo > 0:
                charm_txt = ('con el simple paso del tiempo, sin que cambie nada más, tienden a **comprar** el subyacente '
                             '(soporte que se acumula hacia los vencimientos)')
            else:
                charm_txt = ('con el simple paso del tiempo, sin que cambie nada más, tienden a **vender** el subyacente '
                             '(presión que se acumula hacia los vencimientos)')

            render_explicacion('Cómo leer Vanna y Charm y cómo usarlos', f"""
**Qué son**
Son dos "griegas de segundo orden": miden **cómo cambia la delta** (y por lo tanto, cuánto tienen que cubrirse los creadores de mercado) cuando cambia otra cosa.
- **Vanna:** cuánto cambia la delta cuando cambia la **volatilidad implícita**. Acá se muestra en dólares de delta por cada **+1 punto** de volatilidad.
- **Charm:** cuánto cambia la delta cuando **pasa el tiempo**. Acá se muestra en dólares de delta por **cada día**. Se lo llama también "decaimiento de la delta": una opción fuera del dinero pierde delta a medida que se acerca el vencimiento.

Cuando la delta de sus posiciones cambia, los creadores de mercado **compran o venden el subyacente** para volver a quedar cubiertos. Eso genera flujos de compra o venta que **no dependen de ninguna noticia**.

**Cómo se calculan**
CBOE publica la vol. implícita y el interés abierto de cada contrato, pero no publica Vanna ni Charm. Se calculan con las fórmulas de **Black-Scholes** usando esa vol. implícita, y se suman con la misma convención del GEX (creadores largos calls / cortos puts).

**Datos de hoy**
- Vanna neta: **{_fmt_musd(vex_n)}** por cada +1 punto de vol. → {vanna_txt}.
- Charm neto: **{_fmt_musd(cex_n)}** por día → {charm_txt}.

**Cómo leerlo**
- **Vanna positiva:** una **baja** de volatilidad empuja a comprar (suele acompañar los rallies tranquilos); una **suba** de volatilidad empuja a vender (acelera las caídas).
- **Charm:** el flujo es gradual y constante. Se vuelve **más fuerte cerca de los vencimientos**, sobre todo en las últimas jornadas antes de expirar.
- **Barras grandes en un strike** = nivel donde estos flujos se concentran. Verde = suma un componente positivo, rojo = uno negativo.
- La tabla por vencimiento te muestra **cuál fecha domina**: normalmente los vencimientos más cercanos pesan mucho más.

**Cómo sacarle provecho**
- Antes de un evento con **volatilidad alta que se espera que baje** (por ejemplo, resultados), una Vanna positiva puede ayudar a que el precio se sostenga *después* del evento.
- En los **días previos a un vencimiento grande**, mirá el Charm: si tiene el mismo signo que el DEX y que el régimen de gamma, el efecto se refuerza.
- Usalos como **contexto** para saber de qué lado pueden venir los flujos, no como señal de entrada.

**Límites (importante)**
- Son **difíciles de interpretar**: dependen de asumir quién está largo y quién corto, y esa hipótesis puede fallar.
- Se calculan con Black-Scholes y la vol. implícita publicada por CBOE (con retraso y ruido en strikes ilíquidos). En contratos que vencen en 0 o 1 día, el Charm es muy grande y muy sensible: tomalo con pinzas.
- Un cambio brusco de la vol. o del precio puede dar vuelta la lectura en minutos.
""")

    # ───────────── 9) PUENTE A VALUACIÓN DE OPCIONES ─────────────
    with tabs[8]:
        opts = sorted(df['vto'].unique())
        if not opts:
            st.info('No hay vencimientos con interés abierto para sugerir strikes.')
        else:
            dias_df = (df.groupby('vto')['T'].first() * 365).to_dict()
            idx = next((i for i, v in enumerate(opts) if dias_df.get(v, 0) >= 7), len(opts) - 1)
            vto_p = st.selectbox('Vencimiento objetivo para vender prima', opts, index=idx,
                                 format_func=lambda v: etiq.get(v, _etiqueta_vto(v, dias_df.get(v, 0))),
                                 key=f'gex_puente_vto_{clave}')

            t_em_p = calcular_movimiento_esperado(d, S)
            fila_em = None
            if not t_em_p.empty:
                m_em = t_em_p[t_em_p['vto'] == vto_p]
                if not m_em.empty:
                    fila_em = m_em.iloc[0]

            sug = sugerir_strikes_vendidos(df, S, z, vto_p, fila_em)

            b1, b2, b3, b4 = st.columns(4)
            with b1: st.metric('Régimen de gamma', z['regimen'].capitalize())
            with b2: st.metric('Punto de cambio de gamma', fmt_precio(z['flip']) if z['flip'] else 'N/D')
            with b3: st.metric('Pared de Calls', fmt_precio(z['call_wall']) if z['call_wall'] else 'N/D')
            with b4: st.metric('Pared de Puts', fmt_precio(z['put_wall']) if z['put_wall'] else 'N/D')

            if not sug:
                st.info('No se pudieron sugerir strikes con los datos de este vencimiento.')
            else:
                tabla_s = pd.DataFrame([{
                    'Operación': s['lado'], 'Strike': s['strike'], 'Distancia al precio %': s['dist_pct'],
                    'Criterio': s['base'], 'Prima media (US$)': s['prima_mid'],
                    'Vol. implícita %': s['iv'], 'Delta (CBOE)': s['delta'],
                    'Prob. aprox. de terminar dentro del dinero %': s['prob_itm'],
                    'Interés abierto': s['oi']} for s in sug])
                st.dataframe(tabla_s, use_container_width=True, hide_index=True,
                             column_config={'Strike': st.column_config.NumberColumn(format='%.2f'),
                                            'Distancia al precio %': st.column_config.NumberColumn(format='%+.1f'),
                                            'Prima media (US$)': st.column_config.NumberColumn(format='%.2f'),
                                            'Vol. implícita %': st.column_config.NumberColumn(format='%.1f'),
                                            'Delta (CBOE)': st.column_config.NumberColumn(format='%+.2f'),
                                            'Prob. aprox. de terminar dentro del dinero %': st.column_config.NumberColumn(format='%.0f'),
                                            'Interés abierto': st.column_config.NumberColumn(format='%.0f')})

                if z['regimen'] == 'negativo':
                    st.warning('🔴 Régimen de gamma **negativa**: vender prima es más riesgoso porque los movimientos se amplifican. '
                               'Considerá alejar los strikes, achicar el tamaño o usar estrategias de riesgo definido.')
                for s in sug:
                    if s['tipo'] == 'P' and z['flip'] and s['strike'] > z['flip']:
                        st.caption(f"ℹ️ El put sugerido ({s['strike']:,.2f}) queda **por encima** del punto de cambio de gamma "
                                   f"({z['flip']:,.2f}): si el precio lo alcanza, ya estaría en régimen de amplificación.")

            # publica todo en la sesión para que la calculadora lo lea
            publicar_puente_gex(simbolo, S, z, extra={
                'vto': vto_p, 'sugerencias': sug,
                'techo_esperado': float(fila_em['alto']) if fila_em is not None else None,
                'piso_esperado': float(fila_em['bajo']) if fila_em is not None else None})
            st.success(f"✅ Datos publicados para **Valuación de Opciones** ({simbolo}, {etiq.get(vto_p, vto_p)}). "
                       "La calculadora puede leerlos con `leer_puente_gex()`.")

            with st.expander('🧩 Cómo leerlo desde la calculadora (código)', expanded=False):
                st.code("""from modulo_gex import leer_puente_gex

p = leer_puente_gex('SPY')          # None si no hay datos, son de otro símbolo o tienen +30 min
if p:
    p['flip'], p['call_wall'], p['put_wall'], p['regimen'], p['spot']
    for s in p.get('sugerencias', []):
        s['lado'], s['strike'], s['prima_mid'], s['delta']   # 'Call vendido' / 'Put vendido'
""", language='python')

            render_explicacion('Cómo funciona el puente con Valuación de Opciones y cómo usarlo', f"""
**Qué hace**
Toma lo que ya calculó el GEX (**punto de cambio de gamma** y **paredes de Calls y Puts**) y lo deja disponible para la calculadora de opciones. A partir de eso sugiere **qué strikes vender** en el vencimiento que elijas. Todos los datos (strikes, primas, vol. implícita, delta) vienen de la misma cadena de CBOE.

**Cómo elige los strikes**
- **Call vendido:** el primer strike listado **en o por encima de la pared de Calls**, siempre que esa pared esté sobre el precio. La lógica: la pared suele actuar como techo, así que vender por encima tiene un "escudo" extra.
- **Put vendido:** el primer strike listado **en o por debajo de la pared de Puts**, si esa pared está bajo el precio. La pared de Puts suele actuar como piso.
- Si la pared no sirve (está del lado equivocado del precio), usa el **techo o piso del movimiento esperado** y, como último recurso, **±5%** del precio.

**Cómo leer la tabla**
- **Delta (CBOE):** la delta que publica CBOE para ese contrato.
- **Prob. aprox. de terminar dentro del dinero:** es el valor absoluto de la delta expresado en porcentaje. Es una aproximación habitual, no una probabilidad exacta. Un put vendido con 15% quiere decir que, según el mercado, tiene alrededor de una chance en siete de terminar perdiendo.
- **Prima media:** el promedio entre compra y venta, por acción (multiplicala por {mult} para tener el valor por contrato).

**Cómo sacarle provecho**
- Usalo como **punto de partida**: llevá esos strikes a la calculadora para ver el perfil de resultado, el máximo de pérdida y las griegas antes de decidir.
- En **régimen positivo** las paredes tienden a sostenerse y esta lógica funciona mejor; en **régimen negativo** las paredes se rompen con más facilidad.
- Comprobá siempre el **interés abierto** del strike: si es muy bajo, es difícil operarlo sin pagar un buen diferencial entre compra y venta.
- Cruzalo con el **calendario de eventos** y con la **estructura de vol. implícita**: no conviene vender prima justo antes de un evento importante.

**Límites**
- Es una **referencia**, no una recomendación. Las paredes son un modelo y no garantizan que el precio no las cruce.
- Vender opciones descubiertas puede generar pérdidas grandes. Verificá el riesgo en la calculadora antes de operar.
- Los datos tienen ~15 minutos de retraso y el interés abierto es del día anterior.
""")


# ==============================================================
#  UI PRINCIPAL
# ==============================================================

def modulo_gex():
    st.markdown("""
    <div style="background:linear-gradient(135deg,#1c1020 0%,#2a0a30 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #bc8cff;
         border-radius:14px; padding:24px 30px; margin-bottom:20px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">🧲 GEX — Exposición Gamma y zonas</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Mostrá dónde están concentradas las coberturas de los creadores de mercado y si el régimen actual
        <b style="color:#3fb950">amortigua</b> o <b style="color:#f85149">amplifica</b> los movimientos.
        Datos de opciones de <b>CBOE</b> (gratis, retrasados ~15 min). Cubre símbolos con opciones listadas en EEUU
        (acciones, ETFs, ADRs e índices como SPX).
      </div>
    </div>
    """, unsafe_allow_html=True)

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        entrada = st.text_input('Símbolo (ej: SPY, NVDA, AAPL, GGAL, SPX; los .BA se convierten solos)',
                                value='SPY', key='gex_ticker')
    with c2:
        n_vtos = st.slider('Vencimientos a incluir', 1, 12, 6, key='gex_nvtos',
                           help='Más vencimientos = más panorama, pero los cercanos pesan mucho más (gamma alta).')
    with c3:
        rango_pct = st.slider('Rango de precios (±%)', 5, 30, 20, key='gex_rango',
                              help='Solo se grafican precios de ejercicio dentro de este rango alrededor del precio actual.')

    with st.expander('⚙️ Parámetros avanzados', expanded=False):
        a1, a2, a3 = st.columns(3)
        with a1:
            r = st.number_input('Tasa de interés anual (decimal)', 0.0, 1.0, 0.045, 0.005, format='%.4f', key='gex_r')
        with a2:
            q = st.number_input('Rendimiento por dividendos (decimal)', 0.0, 0.5, 0.0, 0.005, format='%.4f', key='gex_q')
        with a3:
            mult = st.number_input('Multiplicador de contrato', 1, 1000, 100, 1, key='gex_mult')

    if not entrada.strip():
        st.info('Ingresá un símbolo para continuar.')
        return

    simbolo_cboe, simbolo, aviso = resolver_simbolo(entrada)
    if aviso:
        st.info(aviso)

    b1, _ = st.columns([1, 3])
    with b1:
        if st.button('🔄 Actualizar datos', key='gex_refresh'):
            _gex_descargar.clear()                     # solo la caché de GEX
            st.rerun()

    try:
        with st.spinner(f'Descargando cadena de {simbolo} desde CBOE...'):
            datos = _gex_descargar(simbolo_cboe)
    except Exception as e:
        st.error(f'No se pudieron obtener datos de {simbolo}.')
        st.code(f'{type(e).__name__}: {e}')
        return

    S = datos['spot']
    df, diag = preparar_cadena(datos['df'], n_vtos)
    if df is None:
        st.warning(f"No hay cadena utilizable: {diag['motivo']}")
        return
    df, n_delta_rell = reparar_delta(df, S, r, q)

    st.caption(f"📡 Fuente: CBOE · {simbolo} · precio {fmt_precio(S)} · descargado {datos['descargado']} · "
               f"{diag['vtos']} vencimientos · {diag['filas']:,} contratos")
    if diag['iv_rellenadas']:
        st.caption(f"ℹ️ {diag['iv_rellenadas']} contratos tenían vol. implícita inválida; se reemplazó por la mediana del vencimiento.")
    if n_delta_rell:
        st.caption(f"ℹ️ {n_delta_rell} contratos no traían delta válida de CBOE; se completó con Black-Scholes (afecta solo al DEX y a los strikes sugeridos).")

    piv = calcular_gex_por_strike(df, S, r, q, mult, rango_pct / 100)
    if piv.empty:
        st.warning('No hay precios de ejercicio con interés abierto cerca del precio actual para estos vencimientos. '
                   'Probá ampliar el rango de precios o incluir más vencimientos.')
        return
    grid, total = gex_total_vs_spot(df, S, r, q, mult)
    z = calcular_zonas_gex(piv, grid, total, S)

    # Puente base hacia Valuación de Opciones (la pestaña "Puente" lo completa con strikes sugeridos)
    publicar_puente_gex(simbolo, S, z)

    m1, m2, m3, m4 = st.columns(4)
    with m1: st.metric('GEX total (al precio actual)', f"{z['gex_total']/1e6:,.1f} millones de US$")
    with m2: st.metric('Punto de cambio de gamma', fmt_precio(z['flip']) if z['flip'] else 'N/D')
    with m3: st.metric('Pared de Calls', fmt_precio(z['call_wall']) if z['call_wall'] else 'N/D')
    with m4: st.metric('Pared de Puts', fmt_precio(z['put_wall']) if z['put_wall'] else 'N/D')

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

    st.plotly_chart(fig_gex(piv, z, S), use_container_width=True, key='gex_fig_strike')

    render_explicacion('Cómo leer el gráfico "GEX por precio de ejercicio" y cómo usarlo', """
**Qué muestra**
Cada barra es un precio de ejercicio. **Verde hacia arriba** = gamma de las calls. **Rojo hacia abajo** = gamma de las puts. Cuanto más alta la barra, más peso tiene ese precio de ejercicio en las coberturas de los creadores de mercado. El fondo verde/rojo marca dónde rige cada régimen según el punto de cambio de gamma, y las líneas verticales marcan el precio actual, el punto de cambio de gamma y las paredes.

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
    for linea in lectura_personalizada_gex(z, S):
        st.markdown(f'- {linea}')

    st.plotly_chart(fig_gex_total(grid, total, S, z['flip']), use_container_width=True, key='gex_fig_total')

    render_explicacion('Cómo leer el gráfico "GEX total vs precio" y cómo usarlo', """
**Qué muestra**
Responde a esta pregunta: *"si el activo estuviera en otro precio, ¿cuál sería el GEX total?"*. El eje horizontal es el precio hipotético y el vertical es el GEX total. La línea punteada amarilla es el precio actual y la violeta es el punto de cambio de gamma.

**Cómo leerlo**
- Donde la curva está **por encima de 0** = régimen positivo (los creadores de mercado amortiguan).
- Donde está **por debajo de 0** = régimen negativo (los creadores de mercado amplifican).
- El punto donde **cruza el cero** es el punto de cambio de gamma.
- Una curva que **cae rápido hacia el cero** al bajar el precio indica que el régimen es frágil: no hace falta una caída grande para cambiar de escenario.
- Los picos y pequeñas muescas suelen venir de muchos precios de ejercicio juntos o de datos ruidosos; no los tomes como niveles exactos.

**Cómo sacarle provecho**
- Es el gráfico ideal para responder *"¿cuánto tiene que moverse el precio para que cambie el comportamiento del mercado?"*.
- Si el precio está **lejos del punto de cambio y del lado positivo**, hay más margen para estrategias de rango.
- Si está **cerca del punto de cambio**, conviene achicar el tamaño o elegir estrategias con riesgo definido.
""")

    st.caption('⚠️ Asume creadores de mercado largos calls / cortos puts. Usa el interés abierto del día anterior y la vol. implícita '
               'publicada por CBOE (con ~15 min de retraso; puede ser ruidosa en precios de ejercicio ilíquidos). '
               'Es una referencia de régimen, no una señal por sí sola.')

    # ── Análisis complementarios: Put/Call, Max Pain, mov. esperado, GEX por vencimiento, IV, flujo, DEX, Vanna/Charm y puente ──
    _render_analisis_extra(_subset_vtos(datos['df'], n_vtos), df, S, r, q, mult, rango_pct,
                           f'{simbolo}_{n_vtos}', z, simbolo)
