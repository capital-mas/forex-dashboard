# ==============================================================
#  MÓDULO GEX — Gamma Exposure, punto de cambio de gamma y paredes
#  100% independiente del módulo de opciones (no comparte funciones,
#  caché ni claves de sesión). Fuente de datos: cadena pública y gratuita
#  de CBOE (retrasada ~15 min). No usa Yahoo Finance ni yfinance.
#
#  Incluye: GEX + Put/Call, Max Pain, movimiento esperado, GEX por vencimiento,
#  vol. implícita (estructura y skew) y flujo inusual.
#  Uso:   from modulo_gex import modulo_gex
#         modulo_gex()
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
                              _mid_contrato(o.get('bid'), o.get('ask'), o.get('last_trade_price'))))
            if not filas:
                raise LookupError('No se pudo interpretar ningún contrato vigente de la cadena.')

            df = pd.DataFrame(filas, columns=['strike', 'tipo', 'vto', 'T', 'openInterest', 'impliedVolatility',
                                                 'volume', 'mid'])
            df['openInterest'] = pd.to_numeric(df['openInterest'], errors='coerce').fillna(0.0)
            df['impliedVolatility'] = pd.to_numeric(df['impliedVolatility'], errors='coerce')
            df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0.0)
            df['mid'] = pd.to_numeric(df['mid'], errors='coerce')
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


# ── Render de las 6 pestañas ──────────────────────────────────────────────

def _render_analisis_extra(d, df, S, r, q, mult, rango_pct, clave):
    st.markdown('---')
    st.markdown('### 🔬 Análisis complementarios (mismos datos de CBOE)')
    st.caption('Se calculan con la misma descarga de arriba (sin pedidos extra) y sobre los vencimientos que elegiste.')

    dias_map = d.groupby('vto')['dias'].first().to_dict()
    etiq = {v: _etiqueta_vto(v, dd) for v, dd in dias_map.items()}
    rango = rango_pct / 100

    tabs = st.tabs(['⚖️ Put/Call', '📌 Max Pain', '📏 Mov. esperado', '🗓️ GEX por vencimiento',
                    '🌊 Vol. implícita', '🔥 Flujo inusual'])

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

    st.caption(f"📡 Fuente: CBOE · {simbolo} · precio {fmt_precio(S)} · descargado {datos['descargado']} · "
               f"{diag['vtos']} vencimientos · {diag['filas']:,} contratos")
    if diag['iv_rellenadas']:
        st.caption(f"ℹ️ {diag['iv_rellenadas']} contratos tenían vol. implícita inválida; se reemplazó por la mediana del vencimiento.")

    piv = calcular_gex_por_strike(df, S, r, q, mult, rango_pct / 100)
    if piv.empty:
        st.warning('No hay precios de ejercicio con interés abierto cerca del precio actual para estos vencimientos. '
                   'Probá ampliar el rango de precios o incluir más vencimientos.')
        return
    grid, total = gex_total_vs_spot(df, S, r, q, mult)
    z = calcular_zonas_gex(piv, grid, total, S)

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

    # ── Análisis complementarios: Put/Call, Max Pain, mov. esperado, GEX por vencimiento, IV y flujo ──
    _render_analisis_extra(_subset_vtos(datos['df'], n_vtos), df, S, r, q, mult, rango_pct, f'{simbolo}_{n_vtos}')
