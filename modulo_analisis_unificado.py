# ==============================================================
#  MÓDULO UNIFICADO — un activo, un gráfico en vivo fijo y análisis debajo
#
#  El activo se elige UNA sola vez arriba. El gráfico con GEX y velas
#  (que se actualiza seguido) queda fijo, y debajo se muestra el análisis
#  que elija el usuario:
#     🕯️ Lectura de velas + Monte Carlo -> modulo_velas.py
#     🌪️ Perfil de volatilidad          -> modulo_volatilidad_y_analisis_tecnico.py
#     📐 Análisis técnico (7 métodos)   -> modulo_volatilidad_y_analisis_tecnico.py
#
#  Uso en app.py:
#      modulo_analisis_unificado(
#          descargar_datos=descargar_datos,
#          selector_ticker_autocomplete=selector_ticker_autocomplete,
#          kpi_cards_4=kpi_cards_4,
#          fmt_precio=fmt_precio,
#          PLOTLY_CONFIG=PLOTLY_CONFIG,
#          fuente_velas=None,          # opcional
#      )
# ==============================================================

import streamlit as st

from modulo_grafico_live import grafico_live_panel
from modulo_velas import modulo_velas
from modulo_volatilidad_y_analisis_tecnico import modulo_volatilidad, modulo_analisis_tecnico

OPCION_VELAS = '🕯️ Velas + Monte Carlo'
OPCION_VOL = '🌪️ Perfil de volatilidad'
OPCION_TECNICO = '📐 Análisis técnico'
OPCIONES = [OPCION_VELAS, OPCION_VOL, OPCION_TECNICO]

DESCRIPCIONES = {
    OPCION_VELAS: 'Patrones de velas, score de freno de caída/suba, historial de señales y simulación Monte Carlo.',
    OPCION_VOL: 'Volatilidad realizada, percentil/Z-Score, régimen de volatilidad y cruce precio × volatilidad.',
    OPCION_TECNICO: "Weinstein, O'Neil, Darvas Box, Wyckoff, CPR, Market Profile y ORB.",
}

TF_HUB = {'Diaria (1D)': '1d', '1 hora (1H)': '1h', '30 minutos (30M)': '30m'}


def _a_yahoo(t):
    """Los módulos de volatilidad y técnico usan Yahoo: BTC -> BTC-USD, SOLUSDT -> SOL-USD."""
    t = (t or '').strip().upper()
    if t in ('BTC', 'ETH'):
        return f'{t}-USD'
    for suf in ('-USDT', '/USDT', 'USDT'):
        if t.endswith(suf) and len(t) > len(suf):
            return f'{t[:-len(suf)]}-USD'
    return t


def modulo_analisis_unificado(descargar_datos, selector_ticker_autocomplete, kpi_cards_4, fmt_precio,
                              PLOTLY_CONFIG=None, fuente_velas=None):
    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #3a7bd5;
         border-radius:14px; padding:22px 30px; margin-bottom:18px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">🧭 Centro de análisis</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Elegí el activo y la temporalidad una sola vez: el gráfico en vivo queda arriba y el análisis que elijas se muestra debajo.
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── 1) Activo + temporalidad únicos ──
    c_tk, c_tf = st.columns([3, 1])
    with c_tk:
        ticker = selector_ticker_autocomplete('hub_ticker', st.session_state.get('ticker_from_table', ''))
    with c_tf:
        tf_label = st.selectbox('Temporalidad', list(TF_HUB), key='hub_tf')
    tf = TF_HUB[tf_label]

    if not ticker:
        st.info('Elegí un activo para empezar.')
        return

    # ── 2) Gráfico grande en vivo (GEX + velas + conclusión) ──
    grafico_live_panel(ticker, kpi_cards_4, fmt_precio, fuente_velas, tf_forzado=tf)

    st.divider()

    # ── 3) Análisis elegido, debajo del gráfico ──
    opcion = st.radio('¿Qué análisis querés ver?', OPCIONES, horizontal=True, key='hub_analisis')
    st.caption(DESCRIPCIONES[opcion])

    if opcion == OPCION_VELAS:
        modulo_velas(
            descargar_datos=descargar_datos,
            selector_ticker_autocomplete=selector_ticker_autocomplete,
            kpi_cards_4=kpi_cards_4,
            fmt_precio=fmt_precio,
            PLOTLY_CONFIG=PLOTLY_CONFIG,
            ticker_externo=ticker,
            tf_externo=tf,
        )
    elif opcion == OPCION_VOL:
        modulo_volatilidad(PLOTLY_CONFIG=PLOTLY_CONFIG, ticker_externo=_a_yahoo(ticker))
    else:
        modulo_analisis_tecnico(PLOTLY_CONFIG=PLOTLY_CONFIG, ticker_externo=_a_yahoo(ticker))
