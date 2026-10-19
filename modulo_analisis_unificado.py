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


def _selector_fijo(ticker):
    """Devuelve una función que reemplaza al selector de activo de los submódulos:
    en vez de mostrar un selector, devuelve siempre el activo elegido en el hub."""
    def _f(*args, **kwargs):
        return ticker
    return _f


def modulo_analisis_unificado(descargar_datos, selector_ticker_autocomplete, kpi_cards_4, fmt_precio,
                              PLOTLY_CONFIG=None, fuente_velas=None):
    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #3a7bd5;
         border-radius:14px; padding:22px 30px; margin-bottom:18px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">🧭 Centro de análisis</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Elegí el activo una sola vez: el gráfico en vivo queda arriba y el análisis que elijas se muestra debajo.
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── 1) Activo único para todo el centro de análisis ──
    ticker = selector_ticker_autocomplete('hub_ticker', st.session_state.get('ticker_from_table', ''))
    if not ticker:
        st.info('Elegí un activo para empezar.')
        return

    # ── 2) Gráfico en vivo (GEX + velas), siempre visible ──
    grafico_live_panel(ticker, kpi_cards_4, fmt_precio, fuente_velas)

    st.divider()

    # ── 3) Análisis elegido, debajo del gráfico ──
    opcion = st.radio('¿Qué análisis querés ver?', OPCIONES, horizontal=True, key='hub_analisis')
    st.caption(DESCRIPCIONES[opcion])

    if opcion == OPCION_VELAS:
        modulo_velas(
            descargar_datos=descargar_datos,
            selector_ticker_autocomplete=_selector_fijo(ticker),
            kpi_cards_4=kpi_cards_4,
            fmt_precio=fmt_precio,
            PLOTLY_CONFIG=PLOTLY_CONFIG,
        )
    elif opcion == OPCION_VOL:
        modulo_volatilidad(PLOTLY_CONFIG=PLOTLY_CONFIG)
    else:
        modulo_analisis_tecnico(PLOTLY_CONFIG=PLOTLY_CONFIG)
