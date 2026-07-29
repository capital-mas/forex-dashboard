# ==============================================================
#  MÓDULO BOT DE INVERSIÓN — Señales Sent./Antic./Z-Score/RSI+Div
#  Portado desde el indicador Pine Script "Top-Down Cuantitativo
#  — Solo Señales (Sent/Antic/Z/RSI-Div)".
#
#  Uso: importar modulo_bot_inversion() en la app principal y
#  llamarlo pasando las funciones/objetos ya definidos ahí
#  (mismo patrón que modulo_promediador). Ver instrucciones de
#  integración al final del archivo.
# ==============================================================

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

HORIZONTES_BOT = {
    'Corto Plazo':   dict(ventana_valor=63,   ventana_momento=21,  rsi_periodo=7,  vol_periodo=10, bb_periodo=10, atr_periodo=14, ret_dias=5,  mom_escala=2.00, periodo_descarga='6mo'),
    'Mediano Plazo': dict(ventana_valor=504,  ventana_momento=126, rsi_periodo=14, vol_periodo=20, bb_periodo=20, atr_periodo=14, ret_dias=20, mom_escala=0.60, periodo_descarga='3y'),
    'Largo Plazo':   dict(ventana_valor=1260, ventana_momento=504, rsi_periodo=21, vol_periodo=60, bb_periodo=50, atr_periodo=21, ret_dias=60, mom_escala=0.35, periodo_descarga='7y'),
}

C_BOT_VENTA_100  = '#f85149'
C_BOT_VENTA_50   = '#f0883e'
C_BOT_COMPRA_100 = '#3fb950'
C_BOT_COMPRA_50  = '#2dd4bf'


# ── Funciones auxiliares (equivalentes a las de Pine Script) ──────────

def _rsi_sma(close, length):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(length).mean()
    avg_loss = loss.rolling(length).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def _vol_anual_rolling(close, length):
    ret = close.pct_change()
    return ret.rolling(length).std() * np.sqrt(252) * 100


def _rolling_percentrank(s, length):
    """Equivalente a ta.percentrank de Pine: % de las barras anteriores
    (dentro de la ventana) que son menores al valor actual."""
    min_p = max(5, length // 4)

    def _r(x):
        return (x < x[-1]).sum() / len(x) * 100

    return s.rolling(length, min_periods=min_p).apply(_r, raw=True)


@st.cache_data(ttl=1800, show_spinner=False)
def _calcular_bot_dataframe(_close, _high, _low, horizonte,
                             antic_min, antic_max, zscore_periodo, zscore_umbral,
                             rsi_nivel_venta, rsi_nivel_compra, divergencia_lookback,
                             stop_pct_100, stop_pct_50):
    """Los parámetros con prefijo '_' (Series) no se usan para la clave de
    caché de Streamlit; el resto sí, así se recalcula si cambia cualquier input."""
    cfg = HORIZONTES_BOT[horizonte]
    cl = _close.dropna()
    hi = _high.reindex(cl.index)
    lo = _low.reindex(cl.index)

    # Score Acumulación (se calcula pero ya no se usa para la señal — igual que en el Pine v6)
    precio_pct = _rolling_percentrank(cl, cfg['ventana_valor'])
    rsi_valor = _rsi_sma(cl, cfg['rsi_periodo'])
    rsi_pct = 100 - _rolling_percentrank(rsi_valor, cfg['ventana_valor'])
    vol_valor = _vol_anual_rolling(cl, cfg['vol_periodo'])
    vol_pct = 100 - _rolling_percentrank(vol_valor, cfg['ventana_valor'])
    sc_acum = (100 - precio_pct) * 0.40 + rsi_pct * 0.35 + vol_pct * 0.25  # noqa: F841 (informativo)

    # Score Anticipación
    ret_mom = cl.pct_change(cfg['ret_dias']) * 100
    mom = (50 + ret_mom * cfg['mom_escala']).clip(0, 100)

    tr = pd.concat([hi - lo, (hi - cl.shift(1)).abs(), (lo - cl.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(cfg['atr_periodo']).mean()
    atr_media = atr.rolling(cfg['ventana_momento']).mean()
    comp_atr = (100 - (atr / atr_media * 50)).clip(0, 100)

    bb_media = cl.rolling(cfg['bb_periodo']).mean()
    bb_std = cl.rolling(cfg['bb_periodo']).std()
    bbw = (bb_std / bb_media.replace(0, np.nan)) * 100
    bb_c = 100 - _rolling_percentrank(bbw, cfg['ventana_momento'])

    sc_antic = mom * 0.40 + comp_atr * 0.30 + bb_c * 0.30

    # Score Sentimiento (idéntico a precio_pct, como en el Pine original)
    sc_sent = precio_pct

    # Z-Score del precio
    z_media = cl.rolling(zscore_periodo).mean()
    z_std = cl.rolling(zscore_periodo).std()
    zscore = (cl - z_media) / z_std.replace(0, np.nan)

    # RSI extremo + Divergencia
    rsi_alto = rsi_valor >= rsi_nivel_venta
    rsi_bajo = rsi_valor <= rsi_nivel_compra
    div_baj = (cl > cl.shift(divergencia_lookback)) & (rsi_valor < rsi_valor.shift(divergencia_lookback))
    div_alc = (cl < cl.shift(divergencia_lookback)) & (rsi_valor > rsi_valor.shift(divergencia_lookback))
    rsi_pts_venta = np.where(rsi_alto, np.where(div_baj, 2, 1), 0)
    rsi_pts_compra = np.where(rsi_bajo, np.where(div_alc, 2, 1), 0)

    # Señal de posición: 4 condiciones obligatorias en simultáneo
    antic_valida = (sc_antic >= antic_min) & (sc_antic <= antic_max)
    z_venta = zscore >= zscore_umbral
    z_compra = zscore <= -zscore_umbral
    rsi_cond_venta = rsi_pts_venta > 0
    rsi_cond_compra = rsi_pts_compra > 0

    pct_venta = pd.Series(0.0, index=cl.index)
    pct_venta[(sc_sent >= 96) & (sc_sent <= 100) & antic_valida & z_venta & rsi_cond_venta] = 100.0
    mask50v = (sc_sent >= 90) & (sc_sent < 96) & antic_valida & z_venta & rsi_cond_venta & (pct_venta == 0)
    pct_venta[mask50v] = 50.0

    pct_compra = pd.Series(0.0, index=cl.index)
    pct_compra[(sc_sent >= 0) & (sc_sent <= 6) & antic_valida & z_compra & rsi_cond_compra] = 100.0
    mask50c = (sc_sent > 7) & (sc_sent <= 10) & antic_valida & z_compra & rsi_cond_compra & (pct_compra == 0)
    pct_compra[mask50c] = 50.0

    estado = pd.Series('—', index=cl.index)
    estado[pct_venta == 100] = 'VENTA 100%'
    estado[pct_venta == 50] = 'VENTA 50%'
    estado[pct_compra == 100] = 'COMPRA 100%'
    estado[pct_compra == 50] = 'COMPRA 50%'
    # Disparo único: solo la barra donde arranca la señal (igual que "estado_anterior" en Pine)
    disparo = (estado != '—') & (estado != estado.shift(1))

    df = pd.DataFrame({
        'precio': cl, 'sc_acum': sc_acum, 'sc_antic': sc_antic, 'sc_sent': sc_sent,
        'zscore': zscore, 'rsi': rsi_valor,
        'rsi_pts_venta': rsi_pts_venta, 'rsi_pts_compra': rsi_pts_compra,
        'pct_venta': pct_venta, 'pct_compra': pct_compra,
        'estado': estado, 'disparo': disparo,
    })
    df['stop'] = np.select(
        [df['pct_venta'] == 100, df['pct_venta'] == 50, df['pct_compra'] == 100, df['pct_compra'] == 50],
        [df['precio'] * (1 + stop_pct_100 / 100), df['precio'] * (1 + stop_pct_50 / 100),
         df['precio'] * (1 - stop_pct_100 / 100), df['precio'] * (1 - stop_pct_50 / 100)],
        default=np.nan,
    )
    return df


def _fig_bot_señales(ticker, df, PLOTLY_LAYOUT_BASE):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df['precio'], line=dict(color='#3a7bd5', width=1.8), name='Precio'))
    for tipo, color, symbol in [
        ('VENTA 100%', C_BOT_VENTA_100, 'triangle-down'),
        ('VENTA 50%', C_BOT_VENTA_50, 'triangle-down'),
        ('COMPRA 100%', C_BOT_COMPRA_100, 'triangle-up'),
        ('COMPRA 50%', C_BOT_COMPRA_50, 'triangle-up'),
    ]:
        sub = df[(df['disparo']) & (df['estado'] == tipo)]
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(
            x=sub.index, y=sub['precio'], mode='markers', name=tipo,
            marker=dict(size=12, color=color, symbol=symbol, line=dict(width=1, color='#0d1117')),
        ))
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE,
        title=dict(text=f'{ticker} — Señales del Bot de Inversión', font=dict(size=14)),
        height=520, hovermode='x unified',
        legend=dict(orientation='h', y=1.1),
        xaxis=dict(gridcolor='#21262d'), yaxis=dict(gridcolor='#21262d'),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    return fig


# ── Módulo principal ────────────────────────────────────────────────

def modulo_bot_inversion(
    descargar_datos, get_close_series, fmt_precio,
    score_color_hex, kpi_cards_4, selector_ticker_autocomplete,
    chips_navegacion, PLOTLY_LAYOUT_BASE, PLOTLY_CONFIG,
):
    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #6CC24A;
         border-radius:14px; padding:28px 32px; margin-bottom:24px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">🤖 Bot de Inversión — Señales Cuantitativas</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Señal de COMPRA/VENTA basada en 4 condiciones obligatorias simultáneas:
        <b style="color:#e3b341">Sentimiento</b> en nivel extremo,
        <b style="color:#e3b341">Anticipación</b> dentro de rango válido,
        <b style="color:#e3b341">Z-Score</b> del precio y
        <b style="color:#e3b341">RSI + Divergencia</b>.
        Portado del indicador Pine Script "Top-Down Cuantitativo — Solo Señales".
      </div>
    </div>
    """, unsafe_allow_html=True)

    c1, c2 = st.columns([3, 1])
    with c1:
        ticker_bot = selector_ticker_autocomplete('bot_inversion_ticker', label='Ticker')
    with c2:
        horizonte_bot = st.selectbox('Horizonte', list(HORIZONTES_BOT.keys()), index=1, key='bot_horizonte')

    with st.expander('⚙️ Parámetros de la señal (opcional)', expanded=False):
        p1, p2, p3 = st.columns(3)
        with p1:
            antic_min = st.number_input('Anticipación mínima', value=15.0, key='bot_antic_min')
            antic_max = st.number_input('Anticipación máxima', value=38.0, key='bot_antic_max')
        with p2:
            zscore_periodo = st.number_input('Período Z-Score', value=20, min_value=5, key='bot_z_periodo')
            zscore_umbral = st.number_input('Umbral Z-Score (±)', value=2.5, min_value=0.1, step=0.1, key='bot_z_umbral')
        with p3:
            rsi_nivel_venta = st.number_input('Nivel RSI venta (≥)', value=70.0, key='bot_rsi_venta')
            rsi_nivel_compra = st.number_input('Nivel RSI compra (≤)', value=30.0, key='bot_rsi_compra')
        p4, p5, p6 = st.columns(3)
        with p4:
            divergencia_lookback = st.number_input('Barras divergencia', value=5, min_value=2, key='bot_div_lookback')
        with p5:
            stop_pct_100 = st.number_input('Stop % (señal 100%)', value=5.0, key='bot_stop_100')
        with p6:
            stop_pct_50 = st.number_input('Stop % (señal 50%)', value=10.0, key='bot_stop_50')

    analizar_bot = st.button('▶ Analizar', key='bot_run', type='primary')
    if not analizar_bot and not st.session_state.get('bot_run_flag'):
        st.info('Elegí un ticker y horizonte, después presioná "Analizar".')
        return
    if analizar_bot:
        st.session_state['bot_run_flag'] = True

    if not ticker_bot:
        st.warning('Ingresá un ticker válido.')
        return

    cfg = HORIZONTES_BOT[horizonte_bot]
    with st.spinner(f'Descargando historial ({cfg["periodo_descarga"]}) y calculando señales...'):
        df_raw = descargar_datos(ticker_bot, cfg['periodo_descarga'])
    if df_raw is None or df_raw.empty:
        st.error(f'No se encontraron datos para {ticker_bot}.')
        return
    cl = get_close_series(df_raw)
    if cl is None or len(cl.dropna()) < cfg['ventana_valor'] // 2:
        st.warning(f'Historial insuficiente para {horizonte_bot} (se recomienda más historia para este ticker).')
        return
    hi = df_raw['High'] if 'High' in df_raw.columns else cl
    lo = df_raw['Low'] if 'Low' in df_raw.columns else cl

    df_bot = _calcular_bot_dataframe(
        cl, hi, lo, horizonte_bot,
        antic_min, antic_max, int(zscore_periodo), zscore_umbral,
        rsi_nivel_venta, rsi_nivel_compra, int(divergencia_lookback),
        stop_pct_100, stop_pct_50,
    )

    ultimo = df_bot.iloc[-1]
    estado_actual = ultimo['estado']
    color_estado = {
        'VENTA 100%': C_BOT_VENTA_100, 'VENTA 50%': C_BOT_VENTA_50,
        'COMPRA 100%': C_BOT_COMPRA_100, 'COMPRA 50%': C_BOT_COMPRA_50, '—': '#8b949e',
    }.get(estado_actual, '#8b949e')

    kpi_cards_4([
        ('Señal Actual', estado_actual, f'{ticker_bot} · {horizonte_bot}', color_estado),
        ('Precio', fmt_precio(ultimo['precio']),
         f"Stop sugerido: {fmt_precio(ultimo['stop']) if not pd.isna(ultimo['stop']) else '—'}", '#3a7bd5'),
        ('Sentimiento / Anticipación', f"{ultimo['sc_sent']:.0f} / {ultimo['sc_antic']:.0f}",
         'Ambos sobre 100', score_color_hex(ultimo['sc_sent'])),
        ('Z-Score / RSI', f"{ultimo['zscore']:+.2f} / {ultimo['rsi']:.1f}",
         f"Umbral ±{zscore_umbral} · RSI {rsi_nivel_compra:.0f}-{rsi_nivel_venta:.0f}", '#e3b341'),
    ])

    st.plotly_chart(_fig_bot_señales(ticker_bot, df_bot, PLOTLY_LAYOUT_BASE),
                     use_container_width=True, config=PLOTLY_CONFIG, key='bot_fig_señales')

    st.markdown('### 📋 Historial de señales disparadas')
    df_hist = df_bot[df_bot['disparo']].copy().sort_index(ascending=False)
    if df_hist.empty:
        st.info('No se disparó ninguna señal en el período analizado con los parámetros actuales.')
    else:
        df_hist_show = pd.DataFrame({
            'Fecha': df_hist.index.strftime('%Y-%m-%d'),
            'Señal': df_hist['estado'],
            'Precio': df_hist['precio'].apply(fmt_precio),
            'Stop': df_hist['stop'].apply(fmt_precio),
            'Sent': df_hist['sc_sent'].round(1),
            'Antic': df_hist['sc_antic'].round(1),
            'Z-Score': df_hist['zscore'].round(2),
            'RSI': df_hist['rsi'].round(1),
        })

        def _color_señal_bot(val):
            c = {'VENTA 100%': C_BOT_VENTA_100, 'VENTA 50%': C_BOT_VENTA_50,
                 'COMPRA 100%': C_BOT_COMPRA_100, 'COMPRA 50%': C_BOT_COMPRA_50}.get(val, '#e6edf3')
            return f'color:{c};font-weight:700'

        _map = 'map' if hasattr(df_hist_show.style, 'map') else 'applymap'
        styled = (df_hist_show.style
                  .pipe(lambda s: getattr(s, _map)(_color_señal_bot, subset=['Señal']))
                  .set_properties(**{'background-color': '#0d1117', 'color': '#e6edf3', 'border': '1px solid #21262d'})
                  .set_table_styles([
                      {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', '#e6edf3'),
                          ('font-weight', '700'), ('text-align', 'center'),
                          ('border-bottom', '2px solid #3a7bd5'), ('font-size', '11px')]},
                      {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]},
                  ]))
        st.dataframe(styled, use_container_width=True, height=min(500, len(df_hist_show) * 38 + 45))
        st.caption(f'{len(df_hist_show)} señales disparadas en el historial analizado ({cfg["periodo_descarga"]}).')

    with st.expander('❓ Cómo funciona esta señal'):
        st.markdown("""
        Se dispara una señal de **VENTA** o **COMPRA** solo cuando se cumplen **las 4 condiciones a la vez**:
        1. **Sentimiento** (percentil del precio) en nivel extremo — ≥96 (100%) / 90-96 (50%) para venta, ≤6 (100%) / 7-10 (50%) para compra.
        2. **Anticipación** (momentum + compresión de volatilidad) dentro del rango configurado.
        3. **Z-Score** del precio cruzando el umbral (±2.5 por defecto).
        4. **RSI** en nivel extremo (≥70 venta / ≤30 compra); si además hay **divergencia** contra el precio, la confirmación es más fuerte.

        Al ser 4 condiciones simultáneas, las señales son poco frecuentes — están pensadas como confirmaciones
        de alta convicción, no como señales diarias. **Esto es informativo, no asesoramiento financiero.**
        """)

    chips_navegacion([(ticker_bot, ticker_bot)], 'bot_inversion')


# ==============================================================
#  INSTRUCCIONES DE INTEGRACIÓN EN LA APP PRINCIPAL
#  (no ejecutar esto — es la guía para pegar en tu script grande)
# ==============================================================
#
# 1) Import, junto a los otros módulos:
#    from modulo_bot_inversion import modulo_bot_inversion
#
# 2) Agregar 'bot_inversion' a los diccionarios de nav (junto a 'finanzas', 'promediador', etc.):
#    titulos['bot_inversion']   = ('Bot de Inversión', '🤖', 'Señales Sent./Antic./Z-Score/RSI+Div')
#    badge_map['bot_inversion'] = ('#6CC24A', 'rgba(108,194,74,0.12)', 'BOT')
#
# 3) Agregar un botón en el popover "Mi Cuenta" (o como pill de nav propia):
#    if st.button('🤖 Bot de Inversión', use_container_width=True, key='menu_bot_inversion'):
#        st.session_state['nav_horizonte'] = 'bot_inversion'
#        st.session_state['nav_modulo'] = 'bot_inversion'
#        st.rerun()
#
#    (y su equivalente en _OPCIONES_HORIZONTE_MOBILE para el nav de celular)
#
# 4) Agregar la rama de renderizado, junto a las otras (elif MODULO == 'pares': ...):
#    elif MODULO == 'bot_inversion':
#        modulo_bot_inversion(
#            descargar_datos=descargar_datos, get_close_series=get_close_series,
#            fmt_precio=fmt_precio, score_color_hex=score_color_hex,
#            kpi_cards_4=kpi_cards_4, selector_ticker_autocomplete=selector_ticker_autocomplete,
#            chips_navegacion=chips_navegacion, PLOTLY_LAYOUT_BASE=PLOTLY_LAYOUT_BASE,
#            PLOTLY_CONFIG=PLOTLY_CONFIG,
#        )
