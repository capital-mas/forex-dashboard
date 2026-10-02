# ==============================================================
#  MÓDULO LECTURA DE VELAS + MONTE CARLO
#  Portado del script Colab (GGAL) a Streamlit + Plotly.
#  Uso en la app principal (sin cambios respecto de antes):
#      from modulo_velas import modulo_velas
#      modulo_velas(
#          descargar_datos=descargar_datos,
#          selector_ticker_autocomplete=selector_ticker_autocomplete,
#          kpi_cards_4=kpi_cards_4,
#          fmt_precio=fmt_precio,
#          PLOTLY_CONFIG=PLOTLY_CONFIG,
#      )
#
#  Pestaña "🎲 Monte Carlo". El usuario elige por separado:
#     - la temporalidad de las VELAS (1D o 1H), arriba, y
#     - el horizonte del MONTE CARLO (próxima 1 hora o próximo 1 día),
#       dentro de la pestaña.
#
#  NOVEDADES:
#     - Tabla AUTOMÁTICA de probabilidades de llegar a distintos precios
#       (múltiplos de σ + niveles técnicos), sin cargar objetivo a mano.
#     - Historial de las últimas 15 velas del Monte Carlo (backtest:
#       qué predijo el modelo vs. qué pasó realmente).
#     - Opción "Usar precio en vivo" (1H): las probabilidades parten del
#       precio de la vela en formación; el historial muestra la fila ⏳
#       con la proyección vigente.
# ==============================================================

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

C_GREEN = '#3fb950'
C_RED = '#f85149'
C_YELL = '#e3b341'
C_ACENT = '#3a7bd5'
C_MUTED = '#6b7d9a'
C_GRID = '#21262d'
C_BG1 = '#0d1117'
C_BG2 = '#07090f'
C_TEXT = '#e6edf3'

_LAYOUT_BASE = dict(
    plot_bgcolor=C_BG1, paper_bgcolor=C_BG2,
    font=dict(color='#b0bcd0', family='Inter, sans-serif'),
    dragmode=False,
)

# --- Parámetros Monte Carlo ---
MC_HORIZONTES = {'1h': 'Próxima 1 hora', '1d': 'Próximo 1 día'}
MC_VENTANA_RET = {'1h': 150, '1d': 40}      # cantidad de retornos usados para estimar σ
MC_PASOS_PATH = 24                           # subpasos de cada trayectoria (solo afecta el gráfico/toque)
MC_MIN_RETORNOS = 20
MC_SEED = 42
MC_MULT_SIGMA = [-2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0]   # niveles automáticos (en σ)
MC_HIST_N = 15                               # velas del historial Monte Carlo
MC_HIST_SIMS = 2000                          # simulaciones por vela en el historial


# ==============================================================
#  CÁLCULO DE INDICADORES Y PATRONES
# ==============================================================

@st.cache_data(ttl=600, show_spinner=False)
def _descargar_velas_intradia(ticker, period, interval='1h'):
    """Velas intradiarias directo de Yahoo (el caché de Supabase de la app solo guarda fechas
    diarias, así que acá se cachea 10 min con el caché de Streamlit)."""
    try:
        import yfinance as yf
        d = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
        if d is None or d.empty:
            return None
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
        if not {'Open', 'High', 'Low', 'Close'}.issubset(d.columns):
            return None
        if 'Volume' not in d.columns:
            d['Volume'] = 0
        return d[['Open', 'High', 'Low', 'Close', 'Volume']].dropna(
            subset=['Open', 'High', 'Low', 'Close'])
    except Exception:
        return None


def _preparar_intradia(df, excluir_formacion=True):
    """Opcionalmente descarta la vela de la hora en curso (todavía incompleta) y pasa
    el índice a horario Argentina, sin zona horaria, para mostrar y graficar."""
    d = df.copy()
    tz = d.index.tz
    if excluir_formacion and len(d) > 1:
        ahora = pd.Timestamp.now(tz=tz) if tz is not None else pd.Timestamp.now()
        if d.index[-1] + pd.Timedelta(hours=1) > ahora:
            d = d.iloc[:-1]
    if tz is not None:
        d.index = d.index.tz_convert('America/Argentina/Buenos_Aires').tz_localize(None)
    return d


def _rsi(close, periodo=14):
    delta = close.diff()
    gan = delta.clip(lower=0).ewm(alpha=1 / periodo, adjust=False).mean()
    per = (-delta.clip(upper=0)).ewm(alpha=1 / periodo, adjust=False).mean()
    rs = gan / per.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def preparar_velas(df, umbral_mov=0.03):
    d = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
    for c in d.columns:
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d = d.dropna(subset=['Open', 'High', 'Low', 'Close'])
    d['Volume'] = d['Volume'].fillna(0)

    d['SMA20'] = d['Close'].rolling(20).mean()
    d['SMA50'] = d['Close'].rolling(50).mean()
    d['RSI14'] = _rsi(d['Close'], 14)
    d['VOL_MEDIA20'] = d['Volume'].rolling(20).mean()

    # ATR
    cierre_ant = d['Close'].shift(1)
    tr = pd.concat([
        d['High'] - d['Low'],
        (d['High'] - cierre_ant).abs(),
        (d['Low'] - cierre_ant).abs(),
    ], axis=1).max(axis=1)
    d['ATR14'] = tr.rolling(14).mean()

    # Geometría de la vela
    d['CUERPO'] = (d['Close'] - d['Open']).abs()
    d['RANGO'] = d['High'] - d['Low']
    d['MECHA_SUP'] = d['High'] - d[['Open', 'Close']].max(axis=1)
    d['MECHA_INF'] = d[['Open', 'Close']].min(axis=1) - d['Low']

    rango_seg = d['RANGO'].replace(0, np.nan)
    cuerpo_seg = d['CUERPO'].replace(0, np.nan)
    d['CUERPO_PCT'] = d['CUERPO'] / rango_seg

    # Patrones individuales
    d['DOJI'] = d['CUERPO_PCT'] <= 0.15

    d['MARTILLO'] = (
        (d['MECHA_INF'] >= cuerpo_seg * 2)
        & (d['MECHA_SUP'] <= cuerpo_seg)
        & (d['CUERPO_PCT'] <= 0.45)
    )
    d['ESTRELLA_FUGAZ'] = (
        (d['MECHA_SUP'] >= cuerpo_seg * 2)
        & (d['MECHA_INF'] <= cuerpo_seg)
        & (d['CUERPO_PCT'] <= 0.45)
    )
    d['ENV_ALCISTA'] = (
        (d['Close'] > d['Open'])
        & (d['Close'].shift(1) < d['Open'].shift(1))
        & (d['Open'] <= d['Close'].shift(1))
        & (d['Close'] >= d['Open'].shift(1))
    )
    d['ENV_BAJISTA'] = (
        (d['Close'] < d['Open'])
        & (d['Close'].shift(1) > d['Open'].shift(1))
        & (d['Open'] >= d['Close'].shift(1))
        & (d['Close'] <= d['Open'].shift(1))
    )
    d['RECHAZO_MIN'] = (
        (d['MECHA_INF'] > d['CUERPO'] * 1.5)
        & (d['Close'] > d['Low'] + d['RANGO'] * 0.60)
    )
    d['RECHAZO_MAX'] = (
        (d['MECHA_SUP'] > d['CUERPO'] * 1.5)
        & (d['Close'] < d['Low'] + d['RANGO'] * 0.40)
    )

    # Contexto
    d['RET_5'] = d['Close'].pct_change(5)
    d['CAIDA_PREVIA'] = d['RET_5'] <= -umbral_mov
    d['SUBA_PREVIA'] = d['RET_5'] >= umbral_mov
    d['VOLUMEN_ALTO'] = d['Volume'] > d['VOL_MEDIA20'] * 1.20

    d['RSI_REBOTE'] = (d['RSI14'] > d['RSI14'].shift(1)) & (d['RSI14'].shift(1) < 40)
    d['RSI_GIRO_BAJISTA'] = (d['RSI14'] < d['RSI14'].shift(1)) & (d['RSI14'].shift(1) > 60)

    patrones = ['MARTILLO', 'ESTRELLA_FUGAZ', 'ENV_ALCISTA', 'ENV_BAJISTA', 'RECHAZO_MIN',
                'RECHAZO_MAX', 'DOJI', 'CAIDA_PREVIA', 'SUBA_PREVIA', 'VOLUMEN_ALTO',
                'RSI_REBOTE', 'RSI_GIRO_BAJISTA']
    for p in patrones:
        d[p] = d[p].fillna(False).astype(bool)

    # Scores
    d['SCORE_ALCISTA'] = (
        d['MARTILLO'].astype(int) * 2 + d['ENV_ALCISTA'].astype(int) * 2
        + d['RECHAZO_MIN'].astype(int) + d['RSI_REBOTE'].astype(int)
        + d['VOLUMEN_ALTO'].astype(int) + d['CAIDA_PREVIA'].astype(int)
    )
    d['SCORE_BAJISTA'] = (
        d['ESTRELLA_FUGAZ'].astype(int) * 2 + d['ENV_BAJISTA'].astype(int) * 2
        + d['RECHAZO_MAX'].astype(int) + d['RSI_GIRO_BAJISTA'].astype(int)
        + d['VOLUMEN_ALTO'].astype(int) + d['SUBA_PREVIA'].astype(int)
    )

    def _clasificar(row):
        alc, baj = row['SCORE_ALCISTA'], row['SCORE_BAJISTA']
        if alc >= 5 and alc > baj: return 'FRENO DE CAIDA FUERTE'
        if alc >= 3 and alc > baj: return 'POSIBLE FRENO DE CAIDA'
        if baj >= 5 and baj > alc: return 'FRENO DE SUBA FUERTE'
        if baj >= 3 and baj > alc: return 'POSIBLE FRENO DE SUBA'
        if row['DOJI']: return 'INDECISION'
        return 'SIN SEÑAL CLARA'

    d['SEÑAL_VELA'] = d.apply(_clasificar, axis=1)
    return d


# ==============================================================
#  GRÁFICO
# ==============================================================

def _fig_velas(d, ticker, intradia=False):
    if intradia:
        d = d.copy()
        d.index = d.index.strftime('%d/%m %H:%M')
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                        row_heights=[0.76, 0.24])

    fig.add_trace(go.Candlestick(
        x=d.index, open=d['Open'], high=d['High'], low=d['Low'], close=d['Close'],
        name='Precio',
        increasing_line_color=C_GREEN, decreasing_line_color=C_RED,
        increasing_fillcolor=C_GREEN, decreasing_fillcolor=C_RED,
    ), row=1, col=1)

    fig.add_trace(go.Scatter(x=d.index, y=d['SMA20'], name='SMA20',
                             line=dict(color=C_YELL, width=1.3)), row=1, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d['SMA50'], name='SMA50',
                             line=dict(color=C_ACENT, width=1.3)), row=1, col=1)

    # Marcadores de señales
    alc = d[d['SEÑAL_VELA'].str.contains('FRENO DE CAIDA') & d['ATR14'].notna()]
    baj = d[d['SEÑAL_VELA'].str.contains('FRENO DE SUBA') & d['ATR14'].notna()]
    if not alc.empty:
        fig.add_trace(go.Scatter(
            x=alc.index, y=alc['Low'] - alc['ATR14'] * 0.35, mode='markers',
            marker=dict(symbol='triangle-up', size=12, color=C_GREEN,
                        line=dict(width=1, color=C_BG2)),
            name='▲ Freno de caída', text=alc['SEÑAL_VELA'],
            hovertemplate='%{text}<extra></extra>',
        ), row=1, col=1)
    if not baj.empty:
        fig.add_trace(go.Scatter(
            x=baj.index, y=baj['High'] + baj['ATR14'] * 0.35, mode='markers',
            marker=dict(symbol='triangle-down', size=12, color=C_RED,
                        line=dict(width=1, color=C_BG2)),
            name='▼ Freno de suba', text=baj['SEÑAL_VELA'],
            hovertemplate='%{text}<extra></extra>',
        ), row=1, col=1)

    vol_cols = [C_GREEN if c >= o else C_RED for c, o in zip(d['Close'], d['Open'])]
    fig.add_trace(go.Bar(x=d.index, y=d['Volume'], marker_color=vol_cols, opacity=0.55,
                         name='Volumen', showlegend=False), row=2, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d['VOL_MEDIA20'], name='Vol. media 20',
                             line=dict(color=C_MUTED, width=1, dash='dot'),
                             showlegend=False), row=2, col=1)

    if intradia:
        # eje categórico: elimina solo los huecos de noches, fines de semana y feriados
        fig.update_xaxes(gridcolor=C_GRID, rangeslider=dict(visible=False),
                         type='category', nticks=12, tickangle=-45)
    else:
        fechas_presentes = set(d.index.normalize())
        todas = pd.date_range(d.index.min(), d.index.max(), freq='D')
        faltantes = [str(x.date()) for x in todas if x not in fechas_presentes]
        fig.update_xaxes(gridcolor=C_GRID, rangeslider=dict(visible=False),
                         rangebreaks=[dict(values=faltantes)])
    fig.update_yaxes(gridcolor=C_GRID)
    fig.update_layout(
        **_LAYOUT_BASE,
        title=dict(text=f"{ticker} — {'Velas de 1 hora' if intradia else 'Velas diarias'}", font=dict(color=C_TEXT, size=14),
                   x=0.01, xanchor='left', y=0.97),
        height=620, hovermode='x unified',
        legend=dict(orientation='h', y=1.08, x=0, font=dict(size=9)),
        margin=dict(l=10, r=10, t=80, b=10),
    )
    return fig


# ==============================================================
#  CONCLUSIÓN
# ==============================================================

_SENAL_STYLE = {
    'FRENO DE CAIDA FUERTE':  ('🟢', C_GREEN),
    'POSIBLE FRENO DE CAIDA': ('🟢', '#7ee787'),
    'FRENO DE SUBA FUERTE':   ('🔴', C_RED),
    'POSIBLE FRENO DE SUBA':  ('🔴', '#f0883e'),
    'INDECISION':             ('🟡', C_YELL),
    'SIN SEÑAL CLARA':        ('⚪', '#8b949e'),
}


def _patrones_detectados(u):
    nombres = [
        ('MARTILLO', 'Martillo'), ('ENV_ALCISTA', 'Envolvente alcista'),
        ('ESTRELLA_FUGAZ', 'Estrella fugaz'), ('ENV_BAJISTA', 'Envolvente bajista'),
        ('RECHAZO_MIN', 'Rechazo de mínimos'), ('RECHAZO_MAX', 'Rechazo de máximos'),
        ('DOJI', 'Doji / indecisión'),
    ]
    return [txt for col, txt in nombres if bool(u[col])]


def _texto_conclusion(u, fmt):
    s = u['SEÑAL_VELA']
    hi, lo = fmt(u['High']), fmt(u['Low'])

    if s == 'FRENO DE CAIDA FUERTE':
        return (
            'La rueda presenta varias señales simultáneas de agotamiento de la presión vendedora. '
            'El precio podría estar intentando formar un piso de corto plazo. '
            'Esto todavía <b>no</b> confirma automáticamente un cambio de tendencia.',
            f'✅ Confirmación del rebote: superar <b>{hi}</b> &nbsp;·&nbsp; '
            f'❌ Invalidación: perder <b>{lo}</b>')
    if s == 'POSIBLE FRENO DE CAIDA':
        return (
            'Aparecen señales iniciales de que la presión vendedora podría estar perdiendo fuerza. '
            'La señal todavía es preliminar.',
            f'✅ Para confirmar el rebote debería superar <b>{hi}</b> &nbsp;·&nbsp; '
            f'❌ Si pierde <b>{lo}</b>, la señal queda invalidada.')
    if s == 'FRENO DE SUBA FUERTE':
        return (
            'La rueda presenta varias señales simultáneas de agotamiento comprador. '
            'La suba podría estar encontrando un techo de corto plazo.',
            f'✅ Confirmación bajista: perder <b>{lo}</b> &nbsp;·&nbsp; '
            f'❌ Invalidación: superar <b>{hi}</b>')
    if s == 'POSIBLE FRENO DE SUBA':
        return (
            'Aparecen señales iniciales de agotamiento de la presión compradora.',
            f'✅ La señal ganaría confirmación si pierde <b>{lo}</b> &nbsp;·&nbsp; '
            f'❌ Si supera <b>{hi}</b>, la señal queda invalidada.')
    if s == 'INDECISION':
        return (
            'La última vela muestra equilibrio entre compradores y vendedores. '
            'No existe todavía una señal direccional clara.',
            f'🟢 Superar <b>{hi}</b> favorecería el escenario alcista &nbsp;·&nbsp; '
            f'🔴 Perder <b>{lo}</b> favorecería el escenario bajista.')

    sma20 = u['SMA20']
    if pd.notna(sma20) and u['Close'] < sma20:
        ctx = 'El precio permanece por debajo de SMA20, por lo que el corto plazo conserva debilidad.'
    else:
        ctx = 'El precio se encuentra por encima de SMA20, por lo que el corto plazo conserva fortaleza.'
    return (
        'La última rueda no presenta suficientes elementos para hablar de un freno confirmado. ' + ctx,
        f'👁️ Máximo a vigilar: <b>{hi}</b> &nbsp;·&nbsp; Mínimo a vigilar: <b>{lo}</b>')


def _render_conclusion(d, ticker, fmt, kpi_cards_4, intradia=False):
    u = d.iloc[-1]
    emoji, color = _SENAL_STYLE.get(u['SEÑAL_VELA'], ('⚪', '#8b949e'))

    vol_rel = (u['Volume'] / u['VOL_MEDIA20']
               if pd.notna(u['VOL_MEDIA20']) and u['VOL_MEDIA20'] > 0 else None)

    kpi_cards_4([
        ('Último cierre', fmt(u['Close']), f"{'Vela' if intradia else 'Rueda'}: {d.index[-1].strftime('%d/%m %H:%M' if intradia else '%d/%m/%Y')}", C_ACENT, ''),
        ('RSI 14', f"{u['RSI14']:.1f}",
         'Sobreventa' if u['RSI14'] < 30 else ('Sobrecompra' if u['RSI14'] > 70 else 'Zona media'),
         C_YELL, ''),
        ('Score freno de caída', f"{int(u['SCORE_ALCISTA'])}/8", 'Presión vendedora agotándose', C_GREEN, ''),
        ('Score freno de suba', f"{int(u['SCORE_BAJISTA'])}/8", 'Presión compradora agotándose', C_RED, ''),
    ])

    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric('Máximo rueda', fmt(u['High']))
    with c2: st.metric('Mínimo rueda', fmt(u['Low']))
    with c3: st.metric('SMA20 / SMA50',
                       f"{fmt(u['SMA20']) if pd.notna(u['SMA20']) else 'N/D'} / "
                       f"{fmt(u['SMA50']) if pd.notna(u['SMA50']) else 'N/D'}")
    with c4: st.metric('Volumen vs media', f'{vol_rel:.2f}x' if vol_rel is not None else 'N/D')

    patrones = _patrones_detectados(u)
    chips = ' '.join(
        f'<span class="signal-pill" style="margin-right:6px">{p}</span>' for p in patrones
    ) if patrones else '<span style="color:#6b7d9a;font-size:12px">Ningún patrón relevante en la última rueda</span>'

    cuerpo, niveles = _texto_conclusion(u, fmt)

    st.markdown(f"""
    <div style="background:{color}15;border:1.5px solid {color};border-radius:12px;
         padding:18px 22px;text-align:center;margin:14px 0">
      <div style="font-size:11px;color:#8b949e;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">
        Señal de la última vela</div>
      <div style="font-size:22px;font-weight:800;color:{color}">{emoji} {u['SEÑAL_VELA']}</div>
    </div>
    <div class="interp-card">
      <div class="interp-header">🕯️ {ticker} · Patrones detectados</div>
      <div style="margin-bottom:8px">{chips}</div>
    </div>
    <div class="interp-card">
      <div class="interp-header">📝 Conclusión sobre las velas</div>
      {cuerpo}<br><br>{niveles}
    </div>
    """, unsafe_allow_html=True)


def _estilo_tabla(tabla, map_cols):
    """Aplica el estilo oscuro común a las tablas. map_cols = {columna: función_color}."""
    _map = 'map' if hasattr(tabla.style, 'map') else 'applymap'
    styled = tabla.style
    for col, fn in map_cols.items():
        styled = getattr(styled, _map)(fn, subset=[col])
    return (styled
            .set_properties(**{'background-color': C_BG1, 'color': C_TEXT, 'border': f'1px solid {C_GRID}'})
            .set_table_styles([
                {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', C_TEXT),
                                             ('font-weight', '700'), ('text-align', 'center'),
                                             ('border-bottom', f'2px solid {C_ACENT}'), ('font-size', '11px')]},
                {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]},
            ]))


def _render_historial(d, n=15, intradia=False):
    sig = d[d['SEÑAL_VELA'] != 'SIN SEÑAL CLARA'].tail(n).iloc[::-1]
    if sig.empty:
        st.info('No hubo señales relevantes en el período mostrado.')
        return
    tabla = pd.DataFrame({
        'Fecha': sig.index.strftime('%d/%m %H:%M' if intradia else '%d/%m/%Y'),
        'Señal': sig['SEÑAL_VELA'].values,
        'Cierre': sig['Close'].round(2).values,
        'Score caída': sig['SCORE_ALCISTA'].astype(int).values,
        'Score suba': sig['SCORE_BAJISTA'].astype(int).values,
        'RSI': sig['RSI14'].round(1).values,
        'Patrones': [', '.join(_patrones_detectados(r)) or '—' for _, r in sig.iterrows()],
    })

    def _color(val):
        if 'CAIDA' in val: return f'color:{C_GREEN};font-weight:700'
        if 'SUBA' in val: return f'color:{C_RED};font-weight:700'
        if val == 'INDECISION': return f'color:{C_YELL};font-weight:700'
        return ''

    st.dataframe(_estilo_tabla(tabla, {'Señal': _color}), use_container_width=True, hide_index=True,
                 height=min(560, len(tabla) * 36 + 45))


# ==============================================================
#  MONTE CARLO  (horizonte: 1 hora o 1 día)
# ==============================================================

def _datos_mc(ticker, horizonte, descargar_datos):
    """Devuelve (df, vivo).
    df   = velas CERRADAS (con la frecuencia del horizonte elegido).
    vivo = (precio_actual, hora_apertura_vela) de la vela en formación (solo 1h), o None.
    1h -> velas de 1 hora (últimos 3 meses) | 1d -> velas diarias (último año).
    Así σ se estima con retornos de la misma escala que se quiere proyectar."""
    if horizonte == '1h':
        raw = _descargar_velas_intradia(ticker, '3mo', '1h')
        if raw is None or raw.empty:
            return None, None
        cerradas = _preparar_intradia(raw, excluir_formacion=True)
        completo = _preparar_intradia(raw, excluir_formacion=False)
        vivo = None
        if len(completo) > len(cerradas):
            vivo = (float(completo['Close'].iloc[-1]), completo.index[-1])
        return cerradas, vivo
    return descargar_datos(ticker, '1y'), None


def _retornos_full(df, horizonte):
    """Retornos logarítmicos por barra (serie completa). En 1h se descartan los retornos que
    cruzan de una rueda a la siguiente (gap nocturno), porque inflarían la volatilidad horaria."""
    close = pd.to_numeric(df['Close'], errors='coerce').dropna()
    r = np.log(close / close.shift(1))
    if horizonte == '1h':
        dias = pd.Series(close.index.normalize(), index=close.index)
        r = r[dias.eq(dias.shift(1))]
    return r.replace([np.inf, -np.inf], np.nan).dropna()


def _retornos_mc(df, horizonte):
    return _retornos_full(df, horizonte).tail(MC_VENTANA_RET[horizonte])


def _simular_mc(S0, mu_log, sigma, n_sims, pasos=MC_PASOS_PATH, seed=MC_SEED):
    """GBM en unidades de 'un horizonte'. mu_log y sigma son por horizonte (no anualizados).
    El horizonte se subdivide en `pasos`; la distribución final no depende de ese número."""
    rng = np.random.default_rng(seed)
    dt_ = 1.0 / pasos
    Z = rng.standard_normal((pasos, n_sims))
    inc = mu_log * dt_ + sigma * np.sqrt(dt_) * Z
    log_paths = np.vstack([np.zeros(n_sims), np.cumsum(inc, axis=0)])
    return S0 * np.exp(log_paths)


def _prob_toque(paths, nivel, sigma):
    """Probabilidad de tocar `nivel` en algún momento del horizonte.
    Corrige el chequeo discreto con la fórmula del puente browniano entre subpasos,
    así no se subestima el toque real (en tiempo continuo)."""
    S0 = paths[0, 0]
    pasos = paths.shape[0] - 1
    if nivel > S0:
        la = np.log(nivel / paths[:-1])      # distancia (>0 si todavía no llegó)
        lb = np.log(nivel / paths[1:])
    else:
        la = np.log(paths[:-1] / nivel)
        lb = np.log(paths[1:] / nivel)
    var_paso = (sigma ** 2) / pasos
    with np.errstate(over='ignore', invalid='ignore'):
        p_paso = np.exp(-2.0 * la * lb / var_paso)
    p_paso = np.where((la <= 0) | (lb <= 0), 1.0, p_paso)
    p_paso = np.clip(np.nan_to_num(p_paso, nan=0.0), 0.0, 1.0)
    p_path = 1.0 - np.prod(1.0 - p_paso, axis=0)
    return float(p_path.mean() * 100)


def _tabla_niveles_auto(paths, S0, sigma, fmt, ref_niveles=None):
    """Tabla automática: probabilidad de tocar / terminar más allá de cada nivel.
    Niveles = múltiplos de σ del horizonte + referencias técnicas (máx/mín última vela, SMA20)."""
    finales = paths[-1]
    niveles = [(f'{k:+.1f}σ', S0 * float(np.exp(k * sigma))) for k in MC_MULT_SIGMA]
    for nombre, val in (ref_niveles or {}).items():
        if val is not None and pd.notna(val) and val > 0 and abs(val - S0) / S0 > 1e-6:
            niveles.append((nombre, float(val)))
    niveles.sort(key=lambda x: x[1], reverse=True)

    filas = []
    for nombre, precio in niveles:
        arriba = precio > S0
        p_final = float(np.mean(finales >= precio) * 100) if arriba else float(np.mean(finales <= precio) * 100)
        p_toque = _prob_toque(paths, precio, sigma)
        filas.append({
            'Nivel': nombre,
            'Precio': fmt(precio),
            'Distancia': f'{(precio / S0 - 1) * 100:+.2f}%',
            'Sentido': '▲ Arriba' if arriba else '▼ Abajo',
            'Prob. de tocarlo': f'{p_toque:.1f}%',
            'Prob. de terminar más allá': f'{p_final:.1f}%',
        })
    return pd.DataFrame(filas)


def _historial_mc(df, horizonte, usar_drift, n_hist=MC_HIST_N, n_sims=MC_HIST_SIMS):
    """Backtest de las últimas `n_hist` velas: en cada una se simula con los datos disponibles
    hasta ese momento y se compara contra la vela siguiente (lo que pasó de verdad)."""
    d = df.copy()
    for c in ('Open', 'High', 'Low', 'Close'):
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d = d.dropna(subset=['Open', 'High', 'Low', 'Close'])
    close = d['Close']
    r_full = _retornos_full(d, horizonte)
    ventana = MC_VENTANA_RET[horizonte]

    filas = []
    for j in range(len(d) - 1, 0, -1):          # j = vela "real"; j-1 = vela desde la que se proyecta
        if len(filas) >= n_hist:
            break
        t_base, t_real = d.index[j - 1], d.index[j]
        if horizonte == '1h' and t_real not in r_full.index:
            continue                             # cruza de rueda (gap nocturno): no es 1 hora comparable
        base = r_full[r_full.index <= t_base].tail(ventana)
        if len(base) < MC_MIN_RETORNOS:
            continue
        S0 = float(close.iloc[j - 1])
        sigma = float(base.std(ddof=1))
        if not np.isfinite(sigma) or sigma <= 0:
            continue
        mu = float(base.mean()) if usar_drift else -0.5 * sigma ** 2
        finales = _simular_mc(S0, mu, sigma, n_sims)[-1]
        p5, p25, p50, p75, p95 = np.percentile(finales, [5, 25, 50, 75, 95])
        prob_sube = float(np.mean(finales > S0) * 100)
        real = float(close.iloc[j])
        perc_real = float(np.mean(finales <= real) * 100)
        filas.append({
            'base': t_base, 'S0': S0, 'p5': p5, 'p25': p25, 'p50': p50, 'p75': p75, 'p95': p95,
            'prob_sube': prob_sube, 'real': real, 'var_real': (real / S0 - 1) * 100,
            'perc_real': perc_real,
            'en_90': bool(p5 <= real <= p95), 'en_50': bool(p25 <= real <= p75),
            'sube_real': real > S0,
        })
    return filas


def _fila_en_curso(df, horizonte, usar_drift, vivo):
    """Proyección vigente (desde el último cierre) comparada con el precio en vivo."""
    if horizonte != '1h' or vivo is None:
        return None
    precio_vivo, t_vivo = vivo
    close = pd.to_numeric(df['Close'], errors='coerce').dropna()
    if close.empty:
        return None
    t_base = close.index[-1]
    if t_vivo.normalize() != t_base.normalize():
        return None   # la vela en formación es de otra rueda: no hay comparación válida
    ret = _retornos_mc(df, horizonte)
    if len(ret) < MC_MIN_RETORNOS:
        return None
    S0 = float(close.iloc[-1])
    sigma = float(ret.std(ddof=1))
    mu = float(ret.mean()) if usar_drift else -0.5 * sigma ** 2
    finales = _simular_mc(S0, mu, sigma, MC_HIST_SIMS)[-1]
    p5, p95 = np.percentile(finales, [5, 95])
    return {
        'base': t_base, 'S0': S0, 'p5': p5, 'p95': p95,
        'prob_sube': float(np.mean(finales > S0) * 100),
        'real': precio_vivo, 'var_real': (precio_vivo / S0 - 1) * 100,
        'perc_real': float(np.mean(finales <= precio_vivo) * 100),
    }


def _render_historial_mc(df, horizonte, fmt, usar_drift, vivo=None):
    filas = _historial_mc(df, horizonte, usar_drift)
    if not filas:
        st.info('No hay suficientes velas para armar el historial del Monte Carlo.')
        return

    n = len(filas)
    cob90 = sum(f['en_90'] for f in filas) / n * 100
    cob50 = sum(f['en_50'] for f in filas) / n * 100

    k1, k2, k3 = st.columns(3)
    with k1: st.metric('Cobertura banda 5–95%', f'{cob90:.0f}%', help='Debería rondar 90% si el modelo está bien calibrado.')
    with k2: st.metric('Cobertura banda 25–75%', f'{cob50:.0f}%', help='Debería rondar 50% si el modelo está bien calibrado.')
    if usar_drift:
        aciertos = sum((f['prob_sube'] >= 50) == f['sube_real'] for f in filas) / n * 100
        with k3: st.metric('Acierto de dirección', f'{aciertos:.0f}%',
                           help='Compara "prob. de subir ≥ 50%" contra si la vela siguiente realmente subió.')
    else:
        with k3: st.metric('Velas evaluadas', f'{n}')

    intr = (horizonte == '1h')

    def _desde(t):
        # En 1H Yahoo etiqueta la vela por su hora de APERTURA; acá se muestra la hora de CIERRE,
        # que es el momento desde el que se hizo la proyección.
        return (t + pd.Timedelta(hours=1)).strftime('%d/%m %H:%M') if intr else t.strftime('%d/%m/%Y')

    registros = []
    ec = _fila_en_curso(df, horizonte, usar_drift, vivo)
    if ec:
        registros.append({
            'Proyectado desde': _desde(ec['base']) + ' ⏳',
            'Precio base': fmt(ec['S0']),
            'Banda 5–95%': f"{fmt(ec['p5'])} – {fmt(ec['p95'])}",
            'Prob. subir': f"{ec['prob_sube']:.1f}%",
            'Cierre real': f"{fmt(ec['real'])} (en curso)",
            'Var. real': f"{ec['var_real']:+.2f}%",
            'Percentil real': f"P{ec['perc_real']:.0f}",
            '¿Dentro de 90%?': '⏳ Va dentro' if ec['p5'] <= ec['real'] <= ec['p95'] else '⏳ Va fuera',
        })
    for f in filas:
        registros.append({
            'Proyectado desde': _desde(f['base']),
            'Precio base': fmt(f['S0']),
            'Banda 5–95%': f"{fmt(f['p5'])} – {fmt(f['p95'])}",
            'Prob. subir': f"{f['prob_sube']:.1f}%",
            'Cierre real': fmt(f['real']),
            'Var. real': f"{f['var_real']:+.2f}%",
            'Percentil real': f"P{f['perc_real']:.0f}",
            '¿Dentro de 90%?': '✅ Sí' if f['en_90'] else '❌ No',
        })
    tabla = pd.DataFrame(registros)

    def _c_var(v):
        return f'color:{C_GREEN};font-weight:700' if v.startswith('+') else f'color:{C_RED};font-weight:700'

    def _c_ok(v):
        return f'color:{C_GREEN};font-weight:700' if ('Sí' in v or 'Va dentro' in v) else f'color:{C_RED};font-weight:700'

    st.dataframe(_estilo_tabla(tabla, {'Var. real': _c_var, '¿Dentro de 90%?': _c_ok}),
                 use_container_width=True, hide_index=True, height=min(640, len(tabla) * 36 + 45))
    st.caption(
        'Cada fila: se simuló la ' + ('hora' if intr else 'rueda') + ' siguiente usando solo los datos hasta '
        '"Proyectado desde" y se comparó con el cierre real. "Percentil real" indica en qué lugar de la '
        'distribución simulada cayó el cierre real (P50 = justo en la mediana). '
        + ('La fila ⏳ es la proyección vigente: compara contra el precio de ahora y todavía no está resuelta '
           '(no entra en las coberturas). En 1H se omiten los pasos que cruzan de una rueda a otra. ' if intr
           else 'La última rueda puede estar todavía en curso. ')
        + 'Con drift apagado la prob. de subir ronda 50% por construcción: lo que se evalúa ahí es el rango, no la dirección.')


def _fig_mc_abanico(paths, S0, horizonte, objetivo=None):
    n_pasos = paths.shape[0] - 1
    x = (np.linspace(0, 60, n_pasos + 1) if horizonte == '1h'
         else np.linspace(0, 100, n_pasos + 1))
    x_title = 'Minutos desde ahora' if horizonte == '1h' else 'Avance del día (%)'

    p5, p25, p50, p75, p95 = np.percentile(paths, [5, 25, 50, 75, 95], axis=1)
    fig = go.Figure()

    # Muestra de trayectorias individuales
    for i in range(min(paths.shape[1], 80)):
        fig.add_trace(go.Scatter(x=x, y=paths[:, i], mode='lines', showlegend=False,
                                 line=dict(width=0.6, color='rgba(58,123,213,0.18)'),
                                 hoverinfo='skip'))

    # Bandas de percentiles
    fig.add_trace(go.Scatter(x=x, y=p5, mode='lines', line=dict(width=0), showlegend=False,
                             hoverinfo='skip'))
    fig.add_trace(go.Scatter(x=x, y=p95, mode='lines', line=dict(width=0), fill='tonexty',
                             fillcolor='rgba(227,179,65,0.12)', name='Banda 5–95%'))
    fig.add_trace(go.Scatter(x=x, y=p25, mode='lines', line=dict(width=0), showlegend=False,
                             hoverinfo='skip'))
    fig.add_trace(go.Scatter(x=x, y=p75, mode='lines', line=dict(width=0), fill='tonexty',
                             fillcolor='rgba(227,179,65,0.25)', name='Banda 25–75%'))
    fig.add_trace(go.Scatter(x=x, y=p50, mode='lines', name='Mediana',
                             line=dict(color=C_YELL, width=2)))

    fig.add_hline(y=S0, line_dash='dash', line_color='#8b949e', annotation_text='Precio actual',
                  annotation_position='bottom right')
    if objetivo:
        fig.add_hline(y=objetivo, line_dash='dot', line_color=C_ACENT,
                      annotation_text='Nivel objetivo', annotation_position='top right')

    fig.update_xaxes(gridcolor=C_GRID, title=x_title)
    fig.update_yaxes(gridcolor=C_GRID, title='Precio')
    fig.update_layout(
        **_LAYOUT_BASE,
        title=dict(text=f'Trayectorias simuladas — {MC_HORIZONTES[horizonte].lower()}',
                   font=dict(color=C_TEXT, size=14), x=0.01, xanchor='left'),
        height=420, hovermode='x', margin=dict(l=10, r=10, t=60, b=10),
        legend=dict(orientation='h', y=1.12, x=0, font=dict(size=9)),
    )
    return fig


def _fig_mc_hist(finales, S0, p5, p95, objetivo, fmt):
    fig = go.Figure(go.Histogram(x=finales, nbinsx=50, marker_color=C_ACENT, opacity=0.75,
                                 name='Precio final'))
    fig.add_vline(x=S0, line_dash='dash', line_color='#8b949e', annotation_text='Actual')
    fig.add_vline(x=p5, line_dash='dot', line_color=C_RED, annotation_text=f'P5 {fmt(p5)}')
    fig.add_vline(x=p95, line_dash='dot', line_color=C_GREEN, annotation_text=f'P95 {fmt(p95)}')
    if objetivo:
        fig.add_vline(x=objetivo, line_color=C_YELL, annotation_text='Objetivo')
    fig.update_xaxes(gridcolor=C_GRID, title='Precio al final del horizonte')
    fig.update_yaxes(gridcolor=C_GRID, title='Frecuencia')
    fig.update_layout(
        **_LAYOUT_BASE,
        title=dict(text='Distribución del precio final', font=dict(color=C_TEXT, size=14),
                   x=0.01, xanchor='left'),
        height=340, margin=dict(l=10, r=10, t=60, b=10), showlegend=False,
    )
    return fig


def _render_montecarlo(ticker, fmt, kpi_cards_4, descargar_datos, PLOTLY_CONFIG,
                       senal_vela, tf_velas_txt, ref_niveles=None):
    st.caption('El Monte Carlo es independiente de la temporalidad de las velas: '
               'podés mirar velas de 1H y proyectar a 1 día, o al revés.')

    c1, c2, c3, c4 = st.columns([1.8, 1, 1.4, 1.6])
    with c1:
        horizonte = st.radio('Horizonte de la simulación', list(MC_HORIZONTES.keys()),
                             format_func=lambda k: MC_HORIZONTES[k], horizontal=True,
                             key='velas_mc_horizonte')
    with c2:
        n_sims = st.selectbox('Simulaciones', [1000, 5000, 10000], index=1, key='velas_mc_nsims')
    with c3:
        usar_drift = st.checkbox('Incluir drift histórico', value=False, key='velas_mc_drift',
                                 help='Si está apagado, la simulación no tiene sesgo direccional '
                                      '(solo expande el rango según la volatilidad). Con drift '
                                      'encendido se usa la media reciente de retornos, que es muy ruidosa.')
    with c4:
        usar_vivo = st.checkbox('Usar precio en vivo (vela en formación)', value=True,
                                key='velas_mc_vivo', disabled=(horizonte != '1h'),
                                help='Solo 1H. Las probabilidades parten del precio de ahora y no del '
                                     'cierre de la última vela completa.')

    with st.spinner('Descargando datos y simulando...'):
        df, vivo = _datos_mc(ticker, horizonte, descargar_datos)

    if df is None or len(df) == 0 or 'Close' not in df.columns:
        st.error('No se pudieron obtener datos para la simulación.')
        return

    ret = _retornos_mc(df, horizonte)
    if len(ret) < MC_MIN_RETORNOS:
        st.warning(f'Hay muy pocos retornos ({len(ret)}) para estimar la volatilidad. '
                   f'Se necesitan al menos {MC_MIN_RETORNOS}.')
        return

    S0_cerrada = float(pd.to_numeric(df['Close'], errors='coerce').dropna().iloc[-1])
    en_vivo = bool(usar_vivo and vivo is not None and horizonte == '1h')
    S0 = vivo[0] if en_vivo else S0_cerrada
    sigma = float(ret.std(ddof=1))
    mu_log = float(ret.mean()) if usar_drift else -0.5 * sigma ** 2

    paths = _simular_mc(S0, mu_log, sigma, n_sims)
    finales = paths[-1]
    p5, p25, p50, p75, p95 = np.percentile(finales, [5, 25, 50, 75, 95])
    prob_sube = float(np.mean(finales > S0) * 100)
    prob_baja = 100 - prob_sube
    unidad = 'hora' if horizonte == '1h' else 'día'

    kpi_cards_4([
        ('Precio actual', fmt(S0),
         (f'En vivo · vela de las {vivo[1]:%H:%M}' if en_vivo else 'Último cierre de la serie'), C_ACENT, ''),
        (f'Volatilidad por {unidad}', f'{sigma * 100:.2f}%',
         f'Desvío de {len(ret)} retornos {"horarios" if horizonte == "1h" else "diarios"}', C_YELL, ''),
        ('Prob. de subir', f'{prob_sube:.1f}%', f'Terminar por encima de {fmt(S0)}', C_GREEN, ''),
        ('Prob. de bajar', f'{prob_baja:.1f}%', f'Terminar por debajo de {fmt(S0)}', C_RED, ''),
    ])

    m1, m2, m3, m4, m5 = st.columns(5)
    with m1: st.metric('P5 (escenario bajo)', fmt(p5), f'{(p5 / S0 - 1) * 100:+.2f}%')
    with m2: st.metric('P25', fmt(p25), f'{(p25 / S0 - 1) * 100:+.2f}%')
    with m3: st.metric('Mediana', fmt(p50), f'{(p50 / S0 - 1) * 100:+.2f}%')
    with m4: st.metric('P75', fmt(p75), f'{(p75 / S0 - 1) * 100:+.2f}%')
    with m5: st.metric('P95 (escenario alto)', fmt(p95), f'{(p95 / S0 - 1) * 100:+.2f}%')

    # --- Probabilidades automáticas de llegar a cada nivel ---
    st.markdown(f'<div class="sec-title">Probabilidad de llegar a cada precio · {MC_HORIZONTES[horizonte].lower()}</div>',
                unsafe_allow_html=True)
    tabla_niv = _tabla_niveles_auto(paths, S0, sigma, fmt, ref_niveles)

    def _c_sentido(v):
        return f'color:{C_GREEN};font-weight:700' if 'Arriba' in v else f'color:{C_RED};font-weight:700'

    def _c_prob(v):
        try:
            x = float(v.replace('%', ''))
        except ValueError:
            return ''
        if x >= 50: return f'color:{C_YELL};font-weight:700'
        return ''

    st.dataframe(
        _estilo_tabla(tabla_niv, {'Sentido': _c_sentido, 'Prob. de tocarlo': _c_prob}),
        use_container_width=True, hide_index=True, height=min(520, len(tabla_niv) * 36 + 45))
    st.caption('"σ" es la volatilidad estimada del horizonte (ej. +1.0σ = precio actual × e^σ). '
               '"Tocarlo" = que el precio llegue al nivel en algún momento del horizonte; '
               '"terminar más allá" = que cierre el horizonte por encima (niveles arriba) o por debajo (niveles abajo). '
               'Tocar siempre es más probable que terminar más allá.')

    st.plotly_chart(_fig_mc_abanico(paths, S0, horizonte),
                    use_container_width=True, config=PLOTLY_CONFIG,
                    key=f'velas_mc_fan_{ticker}_{horizonte}')
    st.plotly_chart(_fig_mc_hist(finales, S0, p5, p95, None, fmt),
                    use_container_width=True, config=PLOTLY_CONFIG,
                    key=f'velas_mc_hist_{ticker}_{horizonte}')

    # Lectura combinada con la señal de las velas
    sesgo_mc = 'alcista' if prob_sube >= 55 else ('bajista' if prob_sube <= 45 else 'neutral')
    sesgo_vela = ('alcista' if 'CAIDA' in senal_vela else
                  'bajista' if 'SUBA' in senal_vela else 'neutral')
    if not usar_drift:
        lectura = ('Sin drift, el Monte Carlo no tiene sesgo direccional: su aporte es el '
                   '<b>rango probable</b> de precios, no la dirección.')
    elif sesgo_mc == sesgo_vela and sesgo_mc != 'neutral':
        lectura = f'La señal de las velas ({tf_velas_txt}) y el drift histórico apuntan en el mismo sentido ({sesgo_mc}).'
    elif sesgo_mc != 'neutral' and sesgo_vela != 'neutral':
        lectura = f'Señales contradictorias: velas {sesgo_vela} vs. Monte Carlo {sesgo_mc}.'
    else:
        lectura = 'Al menos una de las dos lecturas es neutral; no hay confirmación direccional clara.'

    st.markdown(f"""
    <div class="interp-card">
      <div class="interp-header">🎲 Lectura del Monte Carlo · {ticker}</div>
      En {MC_HORIZONTES[horizonte].lower()}, el 90% de los escenarios simulados termina entre
      <b>{fmt(p5)}</b> y <b>{fmt(p95)}</b>; la mitad central (25–75%) entre
      <b>{fmt(p25)}</b> y <b>{fmt(p75)}</b>.<br><br>
      Señal de las velas ({tf_velas_txt}): <b>{senal_vela}</b>. {lectura}
    </div>
    """, unsafe_allow_html=True)

    # --- Historial de las últimas 15 velas del Monte Carlo ---
    st.markdown(f'<div class="sec-title">Historial Monte Carlo · últimas {MC_HIST_N} velas ({"1H" if horizonte == "1h" else "1D"})</div>',
                unsafe_allow_html=True)
    with st.spinner('Calculando historial del Monte Carlo...'):
        _render_historial_mc(df, horizonte, fmt, usar_drift, vivo if horizonte == '1h' else None)

    st.caption('Modelo: movimiento browniano geométrico con volatilidad constante, estimada con los '
               'retornos recientes. No contempla gaps, saltos ni cambios de régimen, y las colas '
               'reales suelen ser más gordas que las simuladas.')


# ==============================================================
#  MÓDULO PRINCIPAL
# ==============================================================

def modulo_velas(descargar_datos, selector_ticker_autocomplete, kpi_cards_4, fmt_precio,
                 PLOTLY_CONFIG=None):
    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #e3b341;
         border-radius:14px; padding:28px 32px; margin-bottom:24px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">🕯️ Lectura de Velas + Monte Carlo</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Detecta patrones de velas japonesas (martillo, estrella fugaz, envolventes, rechazos, doji),
        los combina con RSI, volumen y contexto de las últimas 5 velas, y arma un score de
        <b style="color:#3fb950">freno de caída</b> / <b style="color:#f85149">freno de suba</b>
        con niveles de confirmación e invalidación. Velas <b>diarias</b> o de <b>1 hora</b>.
        Además incluye una simulación <b>Monte Carlo</b> a <b>1 hora</b> o <b>1 día</b> que calcula sola
        la probabilidad de llegar a cada precio y muestra el historial de sus últimas 15 velas.
      </div>
    </div>
    """, unsafe_allow_html=True)

    c_inp, c_tf, c_per, c_rue, c_btn = st.columns([3, 1.2, 1, 1, 1])
    with c_inp:
        ticker = selector_ticker_autocomplete('velas_ticker', st.session_state.get('ticker_from_table', ''))
    with c_tf:
        tf = st.selectbox('Temporalidad velas', ['1d', '1h'], key='velas_tf',
                          format_func=lambda x: {'1d': 'Diaria (1D)', '1h': '1 hora (1H)'}[x])
    intradia = (tf == '1h')
    with c_per:
        if intradia:
            periodo = st.selectbox('Historial', ['1mo', '3mo', '6mo'], index=1, key='velas_periodo_1h',
                                   format_func=lambda x: {'1mo': '1 mes', '3mo': '3 meses', '6mo': '6 meses'}[x])
        else:
            periodo = st.selectbox('Historial', ['3mo', '6mo', '2y'], index=1, key='velas_periodo_1d',
                                   format_func=lambda x: {'3mo': '3 meses', '6mo': '6 meses', '2y': '2 años'}[x])
    with c_rue:
        opciones_vel = [60, 120, 200, 300] if intradia else [30, 60, 90, 120]
        ruedas = st.selectbox('Velas en gráfico', opciones_vel, index=1,
                              key='velas_ruedas_1h' if intradia else 'velas_ruedas_1d')
    with c_btn:
        st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)
        analizar = st.button('▶ Analizar', use_container_width=True, key='velas_btn')

    excluir_formacion = True
    if intradia:
        excluir_formacion = st.checkbox(
            'Excluir la vela de la hora en curso (todavía incompleta)', value=True, key='velas_excl',
            help='Una vela de 1H que aún no cerró puede cambiar de forma y disparar señales falsas.')

    if analizar and ticker:
        st.session_state['velas_ticker_ok'] = ticker

    ticker_ok = st.session_state.get('velas_ticker_ok', '')
    if not ticker_ok:
        st.markdown("""
        <div style="border:1px dashed #21262d;border-radius:12px;padding:48px;text-align:center;margin-top:20px">
          <div style="font-size:44px;margin-bottom:14px;opacity:.6">🕯️</div>
          <div style="color:#6b7d9a;font-size:13px;line-height:1.8">
            Elegí el activo y la temporalidad, y presioná <b style="color:#e6edf3">Analizar</b>
            para leer sus velas y simular escenarios.
          </div>
        </div>
        """, unsafe_allow_html=True)
        return

    with st.spinner(f'Descargando velas de {ticker_ok} ({"1H" if intradia else "1D"})...'):
        if intradia:
            df = _descargar_velas_intradia(ticker_ok, periodo, '1h')
        else:
            df = descargar_datos(ticker_ok, periodo)

    if df is None or df.empty or not {'Open', 'High', 'Low', 'Close'}.issubset(df.columns):
        st.error(f'No se pudieron descargar velas para {ticker_ok}. Verificá el símbolo o probá en unos minutos.')
        return

    if intradia:
        df = _preparar_intradia(df, excluir_formacion)

    d = preparar_velas(df, umbral_mov=0.01 if intradia else 0.03)
    if len(d) < 25:
        st.warning('Hay muy poco historial para leer las velas con indicadores confiables (se necesitan ≥ 25 velas).')
        return

    st.markdown(f'<div class="sec-title">Resultados para: {ticker_ok} · {"1 hora" if intradia else "Diario"}</div>',
                unsafe_allow_html=True)
    if intradia:
        st.caption('🕐 Horario Argentina · SMA20/SMA50 y RSI calculados sobre velas de 1 hora · '
                   '"Movimiento previo" mide las últimas 5 horas (umbral 1%).')

    u = d.iloc[-1]
    ref_niveles = {
        'Máx. última vela': float(u['High']),
        'Mín. última vela': float(u['Low']),
        'SMA20': float(u['SMA20']) if pd.notna(u['SMA20']) else None,
    }

    tab_graf, tab_hist, tab_mc = st.tabs(['📈 Gráfico y conclusión', '🗂️ Historial de señales',
                                          '🎲 Monte Carlo'])
    with tab_graf:
        st.plotly_chart(_fig_velas(d.tail(ruedas), ticker_ok, intradia), use_container_width=True,
                        config=PLOTLY_CONFIG, key=f'velas_fig_{ticker_ok}_{tf}')
        _render_conclusion(d, ticker_ok, fmt_precio, kpi_cards_4, intradia)
    with tab_hist:
        st.caption('Últimas 15 velas con alguna señal distinta de "Sin señal clara".')
        _render_historial(d, 15, intradia)
    with tab_mc:
        _render_montecarlo(ticker_ok, fmt_precio, kpi_cards_4, descargar_datos, PLOTLY_CONFIG,
                           senal_vela=u['SEÑAL_VELA'],
                           tf_velas_txt='1H' if intradia else '1D',
                           ref_niveles=ref_niveles)

    st.markdown(
        '<div style="font-size:11px;color:#6b7d9a;margin-top:12px">Las velas y las simulaciones son '
        'herramientas de lectura de corto plazo: ningún patrón ni modelo garantiza resultados. '
        'No es asesoramiento financiero.</div>',
        unsafe_allow_html=True)
