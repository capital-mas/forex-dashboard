# ==============================================================
#  MÓDULO UNIFICADO — un solo punto de entrada, el usuario elige el análisis
#
#  Reúne:
#     📈 Gráfico con GEX y velas      -> modulo_grafico_live.py
#     🕯️ Lectura de velas + Monte Carlo -> modulo_velas.py
#     🌪️ Perfil de volatilidad         -> modulo_volatilidad_y_analisis_tecnico.py
#     📐 Análisis técnico (7 métodos)  -> modulo_volatilidad_y_analisis_tecnico.py
#
#  Solo se ejecuta el análisis elegido, así que no se descargan datos
#  de los demás (cero carga innecesaria sobre Yahoo / CBOE / Binance).
#
#  Uso en app.py:
#      from modulo_analisis_unificado import modulo_analisis_unificado
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

from modulo_grafico_live import modulo_grafico_live
from modulo_velas import modulo_velas
from modulo_volatilidad_y_analisis_tecnico import modulo_volatilidad, modulo_analisis_tecnico

OPCION_GRAFICO = '📈 Gráfico con GEX y velas'
OPCION_VELAS = '🕯️ Velas + Monte Carlo'
OPCION_VOL = '🌪️ Perfil de volatilidad'
OPCION_TECNICO = '📐 Análisis técnico'

OPCIONES = [OPCION_GRAFICO, OPCION_VELAS, OPCION_VOL, OPCION_TECNICO]

DESCRIPCIONES = {
    OPCION_GRAFICO: 'Gráfico de velas con niveles GEX (flip, call/put wall, soportes y resistencias) y marcadores de lectura de velas.',
    OPCION_VELAS: 'Patrones de velas, score de freno de caída/suba, historial de señales y simulación Monte Carlo.',
    OPCION_VOL: 'Volatilidad realizada, percentil/Z-Score, régimen de volatilidad y cruce precio × volatilidad.',
    OPCION_TECNICO: 'Weinstein, O\'Neil, Darvas Box, Wyckoff, CPR, Market Profile y ORB.',
}


def modulo_analisis_unificado(descargar_datos, selector_ticker_autocomplete, kpi_cards_4, fmt_precio,
                              PLOTLY_CONFIG=None, fuente_velas=None):
    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #3a7bd5;
         border-radius:14px; padding:22px 30px; margin-bottom:18px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">🧭 Centro de análisis</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Elegí qué análisis querés hacer. Solo se carga el que seleccionás.
      </div>
    </div>
    """, unsafe_allow_html=True)

    opcion = st.radio('¿Qué análisis querés hacer?', OPCIONES, horizontal=True, key='hub_analisis')
    st.caption(DESCRIPCIONES[opcion])
    st.divider()

    if opcion == OPCION_GRAFICO:
        modulo_grafico_live(
            selector_ticker_autocomplete=selector_ticker_autocomplete,
            kpi_cards_4=kpi_cards_4,
            fmt_precio=fmt_precio,
            fuente_velas=fuente_velas,
        )
    elif opcion == OPCION_VELAS:
        modulo_velas(
            descargar_datos=descargar_datos,
            selector_ticker_autocomplete=selector_ticker_autocomplete,
            kpi_cards_4=kpi_cards_4,
            fmt_precio=fmt_precio,
            PLOTLY_CONFIG=PLOTLY_CONFIG,
        )
    elif opcion == OPCION_VOL:
        modulo_volatilidad(PLOTLY_CONFIG=PLOTLY_CONFIG)
    else:
        modulo_analisis_tecnico(PLOTLY_CONFIG=PLOTLY_CONFIG)
