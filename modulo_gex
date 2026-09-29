# ==============================================================
#  MÓDULO GEX — Gamma Exposure, punto de cambio de gamma y paredes
#  100% independiente del módulo de opciones (no comparte funciones,
#  caché ni claves de sesión). Fuente de datos: cadena pública y gratuita
#  de CBOE (retrasada ~15 min). No usa Yahoo Finance ni yfinance.
#
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
                              max(dias, 0.5) / 365.0, o.get('open_interest'), o.get('iv')))
            if not filas:
                raise LookupError('No se pudo interpretar ningún contrato vigente de la cadena.')

            df = pd.DataFrame(filas, columns=['strike', 'tipo', 'vto', 'T', 'openInterest', 'impliedVolatility'])
            df['openInterest'] = pd.to_numeric(df['openInterest'], errors='coerce').fillna(0.0)
            df['impliedVolatility'] = pd.to_numeric(df['impliedVolatility'], errors='coerce')
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
    vtos = sorted(df_completo['vto'].unique())[:n_vtos]
    df = df_completo[df_completo['vto'].isin(vtos)].copy()
    diag['vtos'] = len(vtos)

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
