# ==============================================================
#  MÓDULO LECTURA DE VELAS DIARIAS
#  Portado del script Colab (GGAL) a Streamlit + Plotly.
#  Uso en la app principal:
#      from modulo_velas import modulo_velas
#      modulo_velas(
#          descargar_datos=descargar_datos,
#          selector_ticker_autocomplete=selector_ticker_autocomplete,
#          kpi_cards_4=kpi_cards_4,
#          fmt_precio=fmt_precio,
#          PLOTLY_CONFIG=PLOTLY_CONFIG,
#      )
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


# ==============================================================
#  CÁLCULO DE INDICADORES Y PATRONES
# ==============================================================

def _rsi(close, periodo=14):
    delta = close.diff()
    gan = delta.clip(lower=0).ewm(alpha=1 / periodo, adjust=False).mean()
    per = (-delta.clip(upper=0)).ewm(alpha=1 / periodo, adjust=False).mean()
    rs = gan / per.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def preparar_velas(df):
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
    d['CAIDA_PREVIA'] = d['RET_5'] <= -0.03
    d['SUBA_PREVIA'] = d['RET_5'] >= 0.03
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

def _fig_velas(d, ticker):
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

    # Saltar días sin rueda (fines de semana / feriados) para que no queden huecos
    fechas_presentes = set(d.index.normalize())
    todas = pd.date_range(d.index.min(), d.index.max(), freq='D')
    faltantes = [str(x.date()) for x in todas if x not in fechas_presentes]

    fig.update_xaxes(gridcolor=C_GRID, rangeslider=dict(visible=False),
                     rangebreaks=[dict(values=faltantes)])
    fig.update_yaxes(gridcolor=C_GRID)
    fig.update_layout(
        **_LAYOUT_BASE,
        title=dict(text=f'{ticker} — Velas diarias', font=dict(color=C_TEXT, size=14),
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


def _render_conclusion(d, ticker, fmt, kpi_cards_4):
    u = d.iloc[-1]
    emoji, color = _SENAL_STYLE.get(u['SEÑAL_VELA'], ('⚪', '#8b949e'))

    vol_rel = (u['Volume'] / u['VOL_MEDIA20']
               if pd.notna(u['VOL_MEDIA20']) and u['VOL_MEDIA20'] > 0 else None)

    kpi_cards_4([
        ('Último cierre', fmt(u['Close']), f"Rueda: {d.index[-1].strftime('%d/%m/%Y')}", C_ACENT, ''),
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


def _render_historial(d, n=15):
    sig = d[d['SEÑAL_VELA'] != 'SIN SEÑAL CLARA'].tail(n).iloc[::-1]
    if sig.empty:
        st.info('No hubo señales relevantes en el período mostrado.')
        return
    tabla = pd.DataFrame({
        'Fecha': sig.index.strftime('%d/%m/%Y'),
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

    _map = 'map' if hasattr(tabla.style, 'map') else 'applymap'
    styled = (tabla.style.pipe(lambda s: getattr(s, _map)(_color, subset=['Señal']))
              .set_properties(**{'background-color': C_BG1, 'color': C_TEXT, 'border': f'1px solid {C_GRID}'})
              .set_table_styles([
                  {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', C_TEXT),
                                               ('font-weight', '700'), ('text-align', 'center'),
                                               ('border-bottom', f'2px solid {C_ACENT}'), ('font-size', '11px')]},
                  {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]},
              ]))
    st.dataframe(styled, use_container_width=True, hide_index=True,
                 height=min(560, len(tabla) * 36 + 45))


# ==============================================================
#  MÓDULO PRINCIPAL
# ==============================================================

def modulo_velas(descargar_datos, selector_ticker_autocomplete, kpi_cards_4, fmt_precio,
                 PLOTLY_CONFIG=None):
    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #e3b341;
         border-radius:14px; padding:28px 32px; margin-bottom:24px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">🕯️ Lectura de Velas Diarias</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Detecta patrones de velas japonesas (martillo, estrella fugaz, envolventes, rechazos, doji),
        los combina con RSI, volumen y contexto de las últimas 5 ruedas, y arma un score de
        <b style="color:#3fb950">freno de caída</b> / <b style="color:#f85149">freno de suba</b>
        con niveles de confirmación e invalidación.
      </div>
    </div>
    """, unsafe_allow_html=True)

    c_inp, c_per, c_rue, c_btn = st.columns([3, 1, 1, 1])
    with c_inp:
        ticker = selector_ticker_autocomplete('velas_ticker', st.session_state.get('ticker_from_table', ''))
    with c_per:
        periodo = st.selectbox('Historial', ['3mo', '6mo', '2y'], index=1, key='velas_periodo',
                               format_func=lambda x: {'3mo': '3 meses', '6mo': '6 meses', '2y': '2 años'}[x])
    with c_rue:
        ruedas = st.selectbox('Ruedas en gráfico', [30, 60, 90, 120], index=1, key='velas_ruedas')
    with c_btn:
        st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)
        analizar = st.button('▶ Analizar', use_container_width=True, key='velas_btn')

    if analizar and ticker:
        st.session_state['velas_ticker_ok'] = ticker

    ticker_ok = st.session_state.get('velas_ticker_ok', '')
    if not ticker_ok:
        st.markdown("""
        <div style="border:1px dashed #21262d;border-radius:12px;padding:48px;text-align:center;margin-top:20px">
          <div style="font-size:44px;margin-bottom:14px;opacity:.6">🕯️</div>
          <div style="color:#6b7d9a;font-size:13px;line-height:1.8">
            Elegí el activo arriba y presioná <b style="color:#e6edf3">Analizar</b>
            para leer sus velas diarias.
          </div>
        </div>
        """, unsafe_allow_html=True)
        return

    with st.spinner(f'Descargando velas de {ticker_ok}...'):
        df = descargar_datos(ticker_ok, periodo)

    if df is None or df.empty or not {'Open', 'High', 'Low', 'Close'}.issubset(df.columns):
        st.error(f'No se pudieron descargar velas para {ticker_ok}. Verificá el símbolo o probá en unos minutos.')
        return

    d = preparar_velas(df)
    if len(d) < 25:
        st.warning('Hay muy poco historial para leer las velas con indicadores confiables (se necesitan ≥ 25 ruedas).')
        return

    st.markdown(f'<div class="sec-title">Resultados para: {ticker_ok}</div>', unsafe_allow_html=True)

    tab_graf, tab_hist = st.tabs(['📈 Gráfico y conclusión', '🗂️ Historial de señales'])
    with tab_graf:
        st.plotly_chart(_fig_velas(d.tail(ruedas), ticker_ok), use_container_width=True,
                        config=PLOTLY_CONFIG, key=f'velas_fig_{ticker_ok}')
        _render_conclusion(d, ticker_ok, fmt_precio, kpi_cards_4)
    with tab_hist:
        st.caption('Últimas 15 ruedas con alguna señal distinta de "Sin señal clara".')
        _render_historial(d, 15)

    st.markdown(
        '<div style="font-size:11px;color:#6b7d9a;margin-top:12px">Las velas son una herramienta de '
        'lectura de corto plazo: ningún patrón garantiza resultados. No es asesoramiento financiero.</div>',
        unsafe_allow_html=True)
