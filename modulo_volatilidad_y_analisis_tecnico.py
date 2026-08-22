# ==============================================================
#  MÓDULOS COMBINADOS: PERFIL DE VOLATILIDAD + ANÁLISIS TÉCNICO
#
#  Este archivo une dos módulos independientes que antes vivían en
#  archivos separados:
#
#    1) MÓDULO PERFIL DE VOLATILIDAD — Volatilidad realizada, volatilidad
#       relativa (percentil/Z-Score), régimen (compresión/expansión) y
#       cruce precio vs. volatilidad, para CUALQUIER activo de tu universo
#       (funciones con prefijo _vol_, entry point: modulo_volatilidad)
#
#    2) MÓDULO ANÁLISIS TÉCNICO — Weinstein / O'Neil / Darvas Box /
#       Wyckoff / CPR / Market Profile / ORB
#       (funciones con prefijo _at_, entry point: modulo_analisis_tecnico)
#
#  Son módulos independientes entre sí (prefijos de función distintos,
#  sin superposición de nombres), así que conviven en el mismo archivo
#  sin conflictos. Se importan y se llaman igual que antes desde
#  app.py:
#
#      from modulo_volatilidad_y_analisis_tecnico import (
#          modulo_volatilidad,
#          modulo_analisis_tecnico,
#      )
#
#  Ninguno de los dos persiste datos en Supabase: cada análisis vive
#  solo en la sesión actual de Streamlit.
# ==============================================================

import string
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
from zoneinfo import ZoneInfo

# Diccionarios de activos (industrias, forex, países, ETFs, mercados
# reales), usados por AMBOS módulos (Volatilidad y Análisis Técnico) para
# el selector de activo. Deben vivir en un módulo aparte para evitar
# import circular con app.py.
from config_activos import (
    ACCIONES_POR_INDUSTRIA,
    FOREX,
    PAISES,
    ETFS,
    SECTORES_TOTAL,
    MERCADOS_REALES,
)


# ██████████████████████████████████████████████████████████████
#  MÓDULO 1 — PERFIL DE VOLATILIDAD DEL ACTIVO
#
#  Diferencia clave respecto a la versión anterior: acá NO se compara un
#  universo fijo de índices de miedo (VIX/VXN/RVX/etc.), sino que se
#  analiza la volatilidad de UN activo elegido por el usuario — el mismo
#  selector por categorías que usa el módulo de Análisis Técnico (acciones
#  por industria, forex, índices/países, ETFs, mercados reales, o ticker
#  manual).
#
#  Cuatro bloques de análisis:
#    1) Volatilidad realizada anualizada en 6 ventanas (5/10/20/50/100/200
#       ruedas), calculada sobre retornos logarítmicos diarios.
#    2) Volatilidad relativa: percentil histórico (1 año) y Z-Score de la
#       volatilidad de referencia contra el propio historial del activo.
#    3) Régimen de volatilidad: heurística que ubica el momento actual
#       dentro del ciclo COMPRESSION → BUILDING → EXPANSION → EXTREME →
#       NORMALIZATION, usando percentil histórico + tendencia reciente.
#    4) Cruce dirección de precio × dirección de volatilidad, para una
#       lectura rápida del tipo de movimiento en curso (tendencia sana,
#       tensión, capitulación, pérdida de momentum, compresión o
#       preparación para una expansión).
#
#  Sin persistencia: no se guarda nada en Supabase. Cada análisis vive
#  solo en la sesión actual.
# ██████████████████████████████████████████████████████████████

# ==============================================================
#  CONFIG
# ==============================================================

# Categorías del selector de activo (idénticas en espíritu a las de
# Análisis Técnico, pero con claves de widget propias — prefijo "vol_" —
# para no pisar las del otro módulo si ambos viven en la misma página).
VOL_CATEGORIAS_ACTIVO = [
    "Acción (por industria)",
    "Forex",
    "Índice / País",
    "ETF de Índice",
    "ETF Sector / Subsector",
    "Mercado real (commodity / cripto)",
    "Ticker manual",
]

# Ventanas de volatilidad realizada, en cantidad de ruedas.
VOL_PERIODOS_REALIZADA = [5, 10, 20, 50, 100, 200]
VOL_PERIODO_REFERENCIA_DEFAULT = 20

# Ventanas usadas para volatilidad relativa y detección de régimen.
VOL_VENTANA_PERCENTIL = 252   # ~1 año de ruedas
VOL_VENTANA_ZSCORE = 60
VOL_VENTANA_TENDENCIA = 10    # ruedas hacia atrás para medir "¿está subiendo o bajando?"

# Umbrales de clasificación.
VOL_UMBRAL_SPIKE_ZSCORE = 2.5
VOL_UMBRAL_ELEVADO_PERCENTIL = 70
VOL_UMBRAL_BAJO_PERCENTIL = 30
VOL_UMBRAL_PRECIO_PLANO_PCT = 2.0  # variación de precio por debajo de esto se considera "lateral"


# ==============================================================
#  SELECTOR DE ACTIVO
# ==============================================================

def _vol_seleccionar_ticker():
    """Devuelve (ticker, etiqueta_legible) según la categoría elegida."""
    categoria = st.selectbox('Tipo de activo', VOL_CATEGORIAS_ACTIVO, key='vol_categoria')

    if categoria == "Acción (por industria)":
        industria = st.selectbox('Industria', sorted(ACCIONES_POR_INDUSTRIA.keys()), key='vol_industria')
        ticker = st.selectbox('Ticker', sorted(set(ACCIONES_POR_INDUSTRIA[industria])), key='vol_ticker_industria')
        return ticker, f"{ticker} ({industria})"

    elif categoria == "Forex":
        par = st.selectbox('Par de divisas', sorted(FOREX.keys()), key='vol_forex_par')
        ticker, sub = FOREX[par]
        return ticker, f"{par} ({sub})"

    elif categoria == "Índice / País":
        pais = st.selectbox('País / Índice', sorted(PAISES.keys()), key='vol_pais')
        ticker, region = PAISES[pais]
        return ticker, f"{pais} ({region})"

    elif categoria == "ETF de Índice":
        nombre = st.selectbox('Índice (vía ETF)', sorted(ETFS.keys()), key='vol_etf_indice')
        ticker, cat, _color = ETFS[nombre]
        return ticker, f"{nombre} ({cat})"

    elif categoria == "ETF Sector / Subsector":
        nombre = st.selectbox('Sector / Subsector', sorted(SECTORES_TOTAL.keys()), key='vol_etf_sector')
        ticker, cat, _color = SECTORES_TOTAL[nombre]
        return ticker, f"{nombre} ({cat})"

    elif categoria == "Mercado real (commodity / cripto)":
        nombre = st.selectbox('Mercado', sorted(MERCADOS_REALES.keys()), key='vol_mercado_real')
        ticker, cat, _color = MERCADOS_REALES[nombre]
        return ticker, f"{nombre} ({cat})"

    else:  # Ticker manual
        ticker = st.text_input(
            'Ticker manual (cualquier activo soportado por Yahoo Finance)',
            value='AAPL', key='vol_ticker_manual',
        ).strip().upper()
        return ticker, ticker


# ==============================================================
#  DESCARGA DE DATOS
# ==============================================================

@st.cache_data(ttl=3600, show_spinner=False)
def _vol_descargar(ticker, periodo="3y", intervalo="1d"):
    try:
        import yfinance as yf
        data = yf.Ticker(ticker).history(period=periodo, interval=intervalo, auto_adjust=True)
        data = data[["Close"]].dropna()
        return data if not data.empty else None
    except Exception:
        return None


# ==============================================================
#  ESTADÍSTICA BASE (percentil, z-score — igual lógica que antes, ahora
#  aplicada a la volatilidad del activo en vez de a un índice VIX)
# ==============================================================

def _vol_percentil(serie, valor, ventana=None):
    """Percentil del valor actual dentro de la serie histórica (o los
    últimos `ventana` datos si se especifica). 0 = el valor más bajo
    jamás visto en esa ventana, 100 = el más alto."""
    sub = serie.tail(ventana) if ventana else serie
    sub = sub.dropna()
    if len(sub) < 20:
        return None
    return float((sub < valor).mean() * 100)


def _vol_zscore(serie, ventana=60):
    """Qué tan lejos está el valor actual de su propio promedio reciente,
    en desvíos estándar."""
    sub = serie.tail(ventana).dropna()
    if len(sub) < 20:
        return None
    media, desvio = sub.mean(), sub.std()
    if not desvio:
        return None
    return float((serie.iloc[-1] - media) / desvio)


# ==============================================================
#  BLOQUE 1 — VOLATILIDAD REALIZADA (6 ventanas)
# ==============================================================

def _vol_calcular_retornos_log(close):
    return np.log(close / close.shift(1))


def _vol_calcular_vol_realizada(close, periodos=VOL_PERIODOS_REALIZADA):
    """Volatilidad realizada anualizada (desvío estándar de retornos
    logarítmicos diarios, anualizado con sqrt(252)) para cada ventana en
    `periodos` (expresadas en ruedas). Devuelve un dict {periodo: serie_%}."""
    retornos = _vol_calcular_retornos_log(close)
    return {p: (retornos.rolling(p).std() * np.sqrt(252) * 100) for p in periodos}


# ==============================================================
#  BLOQUE 2 — VOLATILIDAD RELATIVA (percentil + Z-Score contra el propio
#  historial de la volatilidad de referencia elegida)
# ==============================================================

def _vol_clasificar_relativa(percentil, zscore):
    if percentil is None:
        return "Sin dato suficiente", "#6b7d9a"
    if zscore is not None and zscore >= VOL_UMBRAL_SPIKE_ZSCORE:
        return "Volatilidad muy elevada vs. su historial reciente (spike)", "#f85149"
    if percentil >= VOL_UMBRAL_ELEVADO_PERCENTIL:
        return "Volatilidad alta vs. su historial (1 año)", "#e3b341"
    if percentil <= VOL_UMBRAL_BAJO_PERCENTIL:
        return "Volatilidad baja vs. su historial — posible complacencia", "#3fb950"
    return "Volatilidad normal vs. su historial", "#39c5cf"


# ==============================================================
#  BLOQUE 3 — RÉGIMEN DE VOLATILIDAD (ciclo compresión → expansión)
# ==============================================================

def _vol_detectar_regimen(vol_serie, ventana_percentil=VOL_VENTANA_PERCENTIL,
                           ventana_tendencia=VOL_VENTANA_TENDENCIA):
    """Heurística que ubica el momento actual dentro del ciclo clásico:

        VOLATILITY COMPRESSION
                ↓
        VOLATILITY BUILDING
                ↓
        VOLATILITY EXPANSION
                ↓
        VOLATILITY EXTREME
                ↓
        VOLATILITY NORMALIZATION

    usando el percentil histórico (1 año) de la volatilidad de referencia y
    su tendencia reciente (contra el valor de hace `ventana_tendencia`
    ruedas). No es una clasificación exacta: es una lectura rápida del
    ciclo, pensada para complementar —no reemplazar— el resto del análisis."""
    serie_valida = vol_serie.dropna()
    if len(serie_valida) < ventana_tendencia + 20:
        return None

    valor_actual = serie_valida.iloc[-1]
    percentil_actual = _vol_percentil(vol_serie, valor_actual, ventana=ventana_percentil)
    zscore_actual = _vol_zscore(vol_serie, ventana=VOL_VENTANA_ZSCORE)

    if percentil_actual is None:
        return None

    valor_hace_n = serie_valida.iloc[-ventana_tendencia - 1] if len(serie_valida) > ventana_tendencia else None
    percentil_hace_n = (
        _vol_percentil(vol_serie, valor_hace_n, ventana=ventana_percentil) if valor_hace_n is not None else None
    )

    subiendo = bool(percentil_hace_n is not None and percentil_actual > percentil_hace_n + 5)
    bajando = bool(percentil_hace_n is not None and percentil_actual < percentil_hace_n - 5)

    if (zscore_actual is not None and zscore_actual >= VOL_UMBRAL_SPIKE_ZSCORE) or percentil_actual >= 92:
        regimen, color = "VOLATILITY EXTREME", "#f85149"
        descripcion = ("La volatilidad está en niveles extremos frente a su propio historial: zona de "
                       "pánico/capitulación o de un evento puntual (earnings, noticia). Suele ser "
                       "insostenible en el tiempo y tiende a revertir.")
    elif bajando and percentil_hace_n is not None and percentil_hace_n >= 60:
        regimen, color = "VOLATILITY NORMALIZATION", "#3a7bd5"
        descripcion = ("La volatilidad viene bajando después de haber estado en zona elevada: el activo se "
                       "está calmando tras el episodio de estrés reciente.")
    elif percentil_actual <= VOL_UMBRAL_BAJO_PERCENTIL and not subiendo:
        regimen, color = "VOLATILITY COMPRESSION", "#3fb950"
        descripcion = ("La volatilidad está comprimida frente a su historial reciente: rango de precios "
                       "angosto, señal típica de que se está acumulando energía para un movimiento futuro.")
    elif percentil_actual < VOL_UMBRAL_ELEVADO_PERCENTIL and subiendo:
        regimen, color = "VOLATILITY BUILDING", "#e3b341"
        descripcion = ("La volatilidad viene subiendo desde niveles bajos o normales: primeras señales de "
                       "que el activo está saliendo de la calma, sin llegar todavía a una expansión plena.")
    elif percentil_actual >= VOL_UMBRAL_ELEVADO_PERCENTIL:
        regimen, color = "VOLATILITY EXPANSION", "#f0883e"
        descripcion = ("La volatilidad está en niveles altos y en expansión activa: el activo se está "
                       "moviendo con rangos mucho más amplios que lo habitual.")
    else:
        regimen, color = "Zona de transición — sin sesgo claro", "#6b7d9a"
        descripcion = ("La volatilidad no muestra todavía un sesgo claro de tendencia dentro del ciclo "
                       "compresión/expansión con los datos disponibles.")

    return {
        "regimen": regimen, "color": color, "descripcion": descripcion,
        "percentil_actual": percentil_actual, "percentil_hace_n": percentil_hace_n,
        "zscore_actual": zscore_actual, "subiendo": subiendo, "bajando": bajando,
    }


# ==============================================================
#  BLOQUE 4 — PRECIO × VOLATILIDAD (matriz de interpretación)
# ==============================================================

def _vol_direccion_precio(close, ventana=VOL_VENTANA_TENDENCIA, umbral_pct=VOL_UMBRAL_PRECIO_PLANO_PCT):
    """↑ / ↓ / → según la variación de precio en las últimas `ventana`
    ruedas, con `umbral_pct` como banda muerta para considerarlo lateral."""
    sub = close.dropna()
    if len(sub) <= ventana:
        return "→", None
    cambio_pct = float((sub.iloc[-1] / sub.iloc[-ventana - 1] - 1) * 100)
    if cambio_pct >= umbral_pct:
        return "↑", cambio_pct
    if cambio_pct <= -umbral_pct:
        return "↓", cambio_pct
    return "→", cambio_pct


def _vol_direccion_volatilidad(regimen_info):
    """↑ / ↓ / → según la tendencia de volatilidad detectada en el régimen."""
    if regimen_info is None:
        return "→"
    if regimen_info["subiendo"]:
        return "↑"
    if regimen_info["bajando"]:
        return "↓"
    return "→"


# Matriz de interpretación combinando dirección de precio y de volatilidad.
VOL_MATRIZ_INTERPRETACION = {
    ("↑", "↓"): ("Tendencia saludable", "#3fb950",
                 "El precio sube y la volatilidad baja: suba ordenada, con participación consistente y "
                 "sin sobresaltos. Es el escenario más sano para una tendencia alcista."),
    ("↑", "↑"): ("Tendencia con tensión", "#e3b341",
                 "El precio sube pero la volatilidad también: la suba viene acompañada de rangos cada vez "
                 "más amplios, señal de nerviosismo o de un movimiento que se está acelerando más de lo "
                 "sano."),
    ("↓", "↑"): ("Presión / posible capitulación", "#f85149",
                 "El precio cae y la volatilidad sube: presión vendedora fuerte, típica de un proceso de "
                 "capitulación o pánico."),
    ("↓", "↓"): ("Pérdida de momentum", "#6b7d9a",
                 "El precio cae pero la volatilidad baja: la caída pierde fuerza, sin nuevos vendedores "
                 "agresivos entrando. Puede anticipar un amesetamiento."),
    ("→", "↓"): ("Compresión", "#3a7bd5",
                 "El precio lateraliza y la volatilidad sigue bajando: el activo se está comprimiendo, "
                 "acumulando energía para un movimiento futuro."),
    ("→", "↑"): ("Preparación para expansión", "#f0883e",
                 "El precio todavía lateraliza pero la volatilidad ya empezó a subir: suele preceder a una "
                 "ruptura del rango, aunque todavía no se definió la dirección."),
}
VOL_MATRIZ_DEFAULT = ("Sin señal clara", "#6b7d9a",
                      "La combinación actual de dirección de precio y de volatilidad no encaja en ninguno "
                      "de los patrones típicos analizados (por ejemplo, ambas laterales).")


def _vol_interpretar_matriz(dir_precio, dir_vol):
    return VOL_MATRIZ_INTERPRETACION.get((dir_precio, dir_vol), VOL_MATRIZ_DEFAULT)


# ==============================================================
#  GRÁFICOS (Plotly, mismo estilo oscuro que el resto de la app)
# ==============================================================

def _vol_fig_snapshot_periodos(vol_dict):
    """Barra con el valor ACTUAL de volatilidad realizada por cada ventana,
    para comparar de un vistazo el corto plazo contra el largo plazo."""
    periodos = list(vol_dict.keys())
    valores = [
        float(vol_dict[p].iloc[-1]) if not np.isnan(vol_dict[p].iloc[-1]) else None
        for p in periodos
    ]
    etiquetas = [f"{p} ruedas" for p in periodos]

    fig = go.Figure(go.Bar(
        x=etiquetas, y=valores, marker=dict(color='#3a7bd5'),
        text=[f"{v:.1f}%" if v is not None else "s/d" for v in valores], textposition='outside',
    ))
    fig.update_layout(
        plot_bgcolor='#0d1117', paper_bgcolor='#07090f', font=dict(color='#b0bcd0', family='Inter, sans-serif'),
        title=dict(text='Volatilidad realizada actual por ventana (corto vs. largo plazo)',
                   font=dict(color='#e6edf3', size=13)),
        xaxis=dict(gridcolor='#21262d'), yaxis=dict(title='Volatilidad anualizada (%)', gridcolor='#21262d'),
        height=380, margin=dict(l=10, r=40, t=45, b=30),
    )
    return fig


def _vol_fig_realizada_historia(vol_dict, ventana_grafico=300):
    """Serie histórica de volatilidad realizada para cada ventana, últimas
    `ventana_grafico` ruedas — para ver cómo se relacionan entre sí en el
    tiempo (ej. cuándo la corta cruza por encima de la larga)."""
    paleta = ['#3a7bd5', '#e3b341', '#a371f7', '#39c5cf', '#f85149', '#3fb950']
    fig = go.Figure()
    for i, (periodo, serie) in enumerate(vol_dict.items()):
        sub = serie.tail(ventana_grafico)
        fig.add_trace(go.Scatter(x=sub.index, y=sub, mode='lines', name=f"{periodo}R",
                                  line=dict(color=paleta[i % len(paleta)], width=1.4)))
    fig.update_layout(
        plot_bgcolor='#0d1117', paper_bgcolor='#07090f', font=dict(color='#b0bcd0', family='Inter, sans-serif'),
        title=dict(text='Volatilidad realizada anualizada por ventana — evolución reciente',
                   font=dict(color='#e6edf3', size=13)),
        xaxis=dict(title='Fecha', gridcolor='#21262d'),
        yaxis=dict(title='Volatilidad anualizada (%)', gridcolor='#21262d'),
        height=420, margin=dict(l=10, r=10, t=45, b=30), legend=dict(orientation='h', y=-0.2),
    )
    return fig


def _vol_fig_percentil_historia(vol_referencia, ventana_percentil=VOL_VENTANA_PERCENTIL, ventana_grafico=300):
    """Serie histórica del percentil rolling (1 año) de la volatilidad de
    referencia, con líneas de umbral bajo/elevado — sirve para ver
    visualmente los tramos de compresión y expansión pasados."""
    serie = vol_referencia.dropna()
    percentiles = serie.rolling(ventana_percentil, min_periods=60).apply(
        lambda ventana: (ventana < ventana.iloc[-1]).mean() * 100, raw=False
    ).tail(ventana_grafico)

    fig = go.Figure(go.Scatter(x=percentiles.index, y=percentiles, mode='lines',
                                line=dict(color='#a371f7', width=1.6)))
    fig.add_hline(y=VOL_UMBRAL_ELEVADO_PERCENTIL, line=dict(color='#f85149', width=1, dash='dot'))
    fig.add_hline(y=VOL_UMBRAL_BAJO_PERCENTIL, line=dict(color='#3fb950', width=1, dash='dot'))
    fig.update_layout(
        plot_bgcolor='#0d1117', paper_bgcolor='#07090f', font=dict(color='#b0bcd0', family='Inter, sans-serif'),
        title=dict(text='Percentil histórico (1 año) de la volatilidad de referencia',
                   font=dict(color='#e6edf3', size=13)),
        xaxis=dict(title='Fecha', gridcolor='#21262d'),
        yaxis=dict(title='Percentil', range=[0, 105], gridcolor='#21262d'),
        height=380, margin=dict(l=10, r=10, t=45, b=30),
    )
    return fig


# ==============================================================
#  TARJETAS (mismo lenguaje visual que el resto de la app)
# ==============================================================

def _vol_tarjeta_resumen(ticker, etiqueta_activo, valor_actual, cambio_1d, periodo_ref,
                          vol_actual, clasificacion, color):
    cambio_1d_color = "#3fb950" if (cambio_1d or 0) >= 0 else "#f85149"
    cambio_1d_txt = f"{cambio_1d:+.2f}%" if cambio_1d is not None else "s/d"
    vol_txt = f"{vol_actual:.1f}%" if vol_actual is not None else "s/d"

    st.markdown(f"""
    <div style="background:#0d1117;border:1px solid #21262d;border-left:3px solid {color};
         border-radius:8px;padding:14px 18px;margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;align-items:baseline">
        <div>
          <div style="color:#6b7d9a;font-size:11px;text-transform:uppercase">{ticker}</div>
          <div style="color:#e6edf3;font-size:15px;font-weight:700">{etiqueta_activo}</div>
        </div>
        <div style="text-align:right">
          <div style="color:#e6edf3;font-size:20px;font-weight:700">${valor_actual:,.2f}</div>
          <div style="color:{cambio_1d_color};font-size:12px">{cambio_1d_txt} hoy</div>
        </div>
      </div>
      <div style="color:{color};font-size:13px;font-weight:600;margin-top:6px">{clasificacion}</div>
      <div style="margin-top:8px;font-size:11px;color:#8b949e">
        Volatilidad realizada ({periodo_ref}R, anualizada): <b style="color:#e6edf3">{vol_txt}</b>
      </div>
    </div>
    """, unsafe_allow_html=True)


def _vol_tarjeta_regimen(regimen_info):
    p_actual = regimen_info["percentil_actual"]
    p_hace_n = regimen_info["percentil_hace_n"]
    z = regimen_info["zscore_actual"]
    p_actual_txt = f"{p_actual:.0f}" if p_actual is not None else "s/d"
    p_hace_n_txt = f"{p_hace_n:.0f}" if p_hace_n is not None else "s/d"
    z_txt = f"{z:+.2f}" if z is not None else "s/d"

    st.markdown(f"""
    <div style="background:#0d1117;border:1px solid #21262d;border-left:3px solid {regimen_info['color']};
         border-radius:8px;padding:16px 20px;margin-bottom:14px">
      <div style="color:#6b7d9a;font-size:11px;text-transform:uppercase;letter-spacing:0.5px">Régimen de volatilidad</div>
      <div style="color:{regimen_info['color']};font-size:17px;font-weight:700;margin:4px 0 8px 0">{regimen_info['regimen']}</div>
      <div style="font-size:12px;color:#8b949e;margin-bottom:8px">{regimen_info['descripcion']}</div>
      <div style="font-size:11px;color:#6b7d9a">
        Percentil actual: <b style="color:#e6edf3">{p_actual_txt}</b> ·
        Percentil hace {VOL_VENTANA_TENDENCIA} ruedas: <b style="color:#e6edf3">{p_hace_n_txt}</b> ·
        Z-Score(60): <b style="color:#e6edf3">{z_txt}</b>
      </div>
    </div>
    """, unsafe_allow_html=True)


def _vol_tarjeta_matriz(dir_precio, dir_vol, titulo, color, descripcion, cambio_precio_pct):
    cambio_txt = f"{cambio_precio_pct:+.1f}%" if cambio_precio_pct is not None else "s/d"

    st.markdown(f"""
    <div style="background:#0d1117;border:1px solid #21262d;border-left:3px solid {color};
         border-radius:8px;padding:16px 20px;margin-bottom:14px">
      <div style="color:#6b7d9a;font-size:11px;text-transform:uppercase;letter-spacing:0.5px">Precio vs. Volatilidad</div>
      <div style="display:flex;align-items:baseline;gap:14px;margin:6px 0 8px 0">
        <div style="font-size:26px">{dir_precio}</div>
        <div style="font-size:12px;color:#6b7d9a">precio</div>
        <div style="font-size:26px">{dir_vol}</div>
        <div style="font-size:12px;color:#6b7d9a">volatilidad</div>
      </div>
      <div style="color:{color};font-size:17px;font-weight:700;margin-bottom:8px">{titulo}</div>
      <div style="font-size:12px;color:#8b949e;margin-bottom:8px">{descripcion}</div>
      <div style="font-size:11px;color:#6b7d9a">
        Variación de precio ({VOL_VENTANA_TENDENCIA} ruedas): <b style="color:#e6edf3">{cambio_txt}</b>
      </div>
    </div>
    """, unsafe_allow_html=True)


# ==============================================================
#  ENTRY POINT — llamar esto desde el archivo principal
#  Reemplaza al dashboard comparativo de índices VIX (modulo_volatilidad
#  anterior). Se mantiene el mismo nombre de función para no romper el
#  import ya existente en app.py.
# ==============================================================

def modulo_volatilidad(PLOTLY_CONFIG=None):
    """Perfil de volatilidad de UN activo (no un dashboard de índices VIX):

      1) Volatilidad realizada anualizada en 6 ventanas (5/10/20/50/100/200
         ruedas), calculada sobre retornos logarítmicos diarios.
      2) Volatilidad relativa: percentil histórico (1 año) y Z-Score de la
         ventana de referencia contra el propio historial del activo.
      3) Régimen de volatilidad dentro del ciclo COMPRESSION → BUILDING →
         EXPANSION → EXTREME → NORMALIZATION.
      4) Cruce dirección de precio × dirección de volatilidad, con la
         matriz de interpretación (tendencia sana, tensión, capitulación,
         pérdida de momentum, compresión o preparación para expansión).

    El activo se elige desde las mismas categorías que usa el módulo de
    Análisis Técnico (acciones por industria, forex, índices/países, ETFs,
    mercados reales) o como ticker manual. Todo se descarga de Yahoo
    Finance vía yfinance, con caché de 1 hora. Sin persistencia: vive solo
    en la sesión actual, igual que el resto de la app."""

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1420 0%,#0a1c30 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #a371f7;
         border-radius:14px; padding:26px 30px; margin-bottom:22px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">🌪️ Perfil de Volatilidad del Activo</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Analizá la volatilidad de <b style="color:#e6edf3">cualquier activo</b> de tu universo, en vez de
        mirar un índice de miedo genérico como el VIX: <b style="color:#e6edf3">volatilidad realizada</b>
        anualizada en 6 ventanas (5/10/20/50/100/200 ruedas), <b style="color:#e6edf3">volatilidad
        relativa</b> (percentil histórico y Z-Score contra su propio historial), el
        <b style="color:#e6edf3">régimen de volatilidad</b> dentro del ciclo COMPRESSION → BUILDING →
        EXPANSION → EXTREME → NORMALIZATION, y el cruce entre <b style="color:#e6edf3">dirección de
        precio</b> y <b style="color:#e6edf3">dirección de volatilidad</b> para leer rápido qué tipo de
        movimiento hay en curso. Este análisis no se guarda: vive solo en la sesión actual.
      </div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns([2, 1])
    with col1:
        ticker, etiqueta_activo = _vol_seleccionar_ticker()
    with col2:
        periodo_ref = st.selectbox(
            'Ventana de referencia (relativa / régimen)',
            VOL_PERIODOS_REALIZADA,
            index=VOL_PERIODOS_REALIZADA.index(VOL_PERIODO_REFERENCIA_DEFAULT),
            key='vol_periodo_ref',
        )

    if not ticker:
        st.info('Seleccioná o ingresá un activo para analizar.')
        return

    with st.spinner(f'Descargando datos de {ticker}...'):
        data = _vol_descargar(ticker)

    if data is None or len(data) < 220:
        st.error(f'No se pudieron descargar suficientes datos para {ticker} (se necesitan al menos ~220 '
                 f'ruedas para calcular el percentil de 1 año). Verificá el ticker.')
        return

    close = data["Close"]
    vol_dict = _vol_calcular_vol_realizada(close)
    vol_referencia = vol_dict[periodo_ref]

    valor_actual = float(close.iloc[-1])
    cambio_1d = float((close.iloc[-1] / close.iloc[-2] - 1) * 100) if len(close) > 1 else None

    ultimo_vol = vol_referencia.iloc[-1]
    vol_actual = float(ultimo_vol) if not np.isnan(ultimo_vol) else None
    percentil = _vol_percentil(vol_referencia, vol_actual, ventana=VOL_VENTANA_PERCENTIL) if vol_actual is not None else None
    zscore = _vol_zscore(vol_referencia, ventana=VOL_VENTANA_ZSCORE) if vol_actual is not None else None
    clasificacion, color = _vol_clasificar_relativa(percentil, zscore)

    regimen_info = _vol_detectar_regimen(vol_referencia)
    dir_precio, cambio_precio_pct = _vol_direccion_precio(close)
    dir_vol = _vol_direccion_volatilidad(regimen_info)
    titulo_matriz, color_matriz, descripcion_matriz = _vol_interpretar_matriz(dir_precio, dir_vol)

    cols = st.columns(4)
    with cols[0]:
        st.metric('Último cierre', f"${valor_actual:,.2f}", f"{cambio_1d:+.2f}%" if cambio_1d is not None else None)
    with cols[1]:
        st.metric(f'Volatilidad {periodo_ref}R', f"{vol_actual:.1f}%" if vol_actual is not None else "s/d")
    with cols[2]:
        st.metric('Percentil histórico (1A)', f"{percentil:.0f}" if percentil is not None else "s/d")
    with cols[3]:
        st.metric('Z-Score (60R)', f"{zscore:+.2f}" if zscore is not None else "s/d")

    tab_resumen, tab_realizada, tab_regimen, tab_matriz = st.tabs(
        ['🧾 Resumen', '📊 Volatilidad realizada', '🔄 Régimen', '🎯 Precio vs. Volatilidad']
    )

    with tab_resumen:
        _vol_tarjeta_resumen(ticker, etiqueta_activo, valor_actual, cambio_1d, periodo_ref,
                             vol_actual, clasificacion, color)
        if regimen_info:
            _vol_tarjeta_regimen(regimen_info)
        _vol_tarjeta_matriz(dir_precio, dir_vol, titulo_matriz, color_matriz, descripcion_matriz, cambio_precio_pct)

    with tab_realizada:
        fig_snapshot = _vol_fig_snapshot_periodos(vol_dict)
        st.plotly_chart(fig_snapshot, use_container_width=True, config=PLOTLY_CONFIG)
        fig_historia = _vol_fig_realizada_historia(vol_dict)
        st.plotly_chart(fig_historia, use_container_width=True, config=PLOTLY_CONFIG)
        st.caption("La volatilidad realizada de ventanas cortas (5-10 ruedas) reacciona más rápido a "
                   "eventos recientes; las ventanas largas (100-200 ruedas) muestran el nivel de fondo del "
                   "activo. Cuando la corta está muy por encima de la larga, el activo está más nervioso "
                   "que su promedio de largo plazo; cuando está muy por debajo, se calmó respecto a ese "
                   "promedio.")

    with tab_regimen:
        if regimen_info:
            _vol_tarjeta_regimen(regimen_info)
            fig_percentil = _vol_fig_percentil_historia(vol_referencia)
            st.plotly_chart(fig_percentil, use_container_width=True, config=PLOTLY_CONFIG)
            st.caption("Percentil alto (línea roja, ≥70) = volatilidad cara en términos históricos para "
                       "este activo. Percentil bajo (línea verde, ≤30) = volatilidad comprimida, terreno "
                       "típico previo a una expansión.")
        else:
            st.info('No hay suficiente historial de este activo para detectar el régimen de volatilidad.')

    with tab_matriz:
        _vol_tarjeta_matriz(dir_precio, dir_vol, titulo_matriz, color_matriz, descripcion_matriz, cambio_precio_pct)
        st.caption(f"Dirección de precio calculada sobre las últimas {VOL_VENTANA_TENDENCIA} ruedas (banda "
                   f"muerta de {VOL_UMBRAL_PRECIO_PLANO_PCT:.0f}% para considerarlo lateral); dirección de "
                   f"volatilidad según la tendencia del régimen detectado en la pestaña anterior.")


# ██████████████████████████████████████████████████████████████
#  MÓDULO 2 — ANÁLISIS TÉCNICO
#  Weinstein / O'Neil / Darvas Box / Wyckoff / CPR / Market Profile / ORB
#
#  Diferencia clave respecto al módulo de Volatilidad: acá NO hay un
#  universo fijo de activos ni ranking entre varios — el usuario elige
#  el activo desde las categorías ya definidas en config_activos.py
#  (acciones por industria, forex, índices/países, ETFs de
#  sector/subsector, mercados reales), o tipea cualquier ticker manual
#  soportado por Yahoo Finance. El ADX de Wilder se calcula siempre
#  como dato/filtro transversal (se usa fuerte dentro de O'Neil).
#
#  Selector de temporalidad: 1 Día / 4 Horas / 1 Hora / 45 Minutos /
#  30 Minutos / 15 Minutos / 5 Minutos, para los métodos Weinstein,
#  O'Neil, Darvas Box, Wyckoff y CPR. Yahoo Finance no tiene intervalo
#  nativo de 4H ni de 45M, así que esas dos se arman resampleando con
#  pandas (4H desde velas de 1H, 45M desde velas de 15M).
#
#  ORB y Market Profile necesitan velas intradía finas (5 minutos) y
#  trabajan por SESIÓN (día calendario), no con N velas históricas fijas
#  de una temporalidad elegida. Por eso comparten su propio pipeline de
#  datos y su propio selector de período (caja de apertura / período de
#  TPO), separados del selector de temporalidad genérico.
#
#  Sin persistencia: no se guarda nada en Supabase. Cada análisis
#  vive solo en la sesión actual.
# ██████████████████████████████████████████████████████████████

# ==============================================================
#  CONSTANTES DEL MÓDULO
# ==============================================================

# Benchmark de mercado usado por el método O'Neil para calcular el RS Rating
BENCHMARK_DEFAULT = 'SPY'

# Categorías que ofrece el selector de activo
CATEGORIAS_ACTIVO = [
    "Acción (por industria)",
    "Forex",
    "Índice / País",
    "ETF de Índice",
    "ETF Sector / Subsector",
    "Mercado real (commodity / cripto)",
    "Ticker manual",
]

# Métodos de análisis técnico disponibles (label visible -> clave interna)
METODOS_DISPONIBLES = {
    "Stan Weinstein (fases de mercado)": "weinstein",
    "William O'Neil (CANSLIM técnico)": "oneil",
    "Darvas Box": "darvas",
    "Wyckoff (Acumulación/Distribución)": "wyckoff",
    "CPR (Central Pivot Range)": "cpr",
    "Market Profile (TPO)": "market_profile",
    "ORB (Opening Range Breakout)": "orb",
}

# ----------------------------------------------------------------
#  Temporalidades disponibles (métodos Weinstein / O'Neil / Darvas /
#  Wyckoff / CPR).
#  yf_interval / yf_periodo: lo que se le pide a Yahoo Finance.
#  resample: si no es None, se descarga yf_interval y se agrupa a esa
#            regla de pandas (ej. "4h", "45min") porque Yahoo no la
#            ofrece nativa.
#  min_velas / min_velas_mm_largas: umbrales de historial mínimo,
#            iguales en cantidad de barras para todas las temporalidades
#            (30/50/150/200 velas siguen significando lo mismo en
#            cantidad de barras, cambia lo que representan en tiempo).
#
#  Límites reales de Yahoo Finance para datos intradiarios:
#   - intervalo 60m/1h: hasta ~730 días de histórico.
#   - intervalos 5m/15m/30m: hasta ~60 días de histórico.
#  Por eso 30m se pide directo con yf_periodo="60d", y 45m (que Yahoo
#  no ofrece nativo) se arma resampleando velas de 15m también con
#  yf_periodo="60d".
# ----------------------------------------------------------------
TIMEFRAMES_DISPONIBLES = {
    "1 Día": {
        "yf_interval": "1d",
        "yf_periodo": "3y",
        "resample": None,
        "sufijo_grafico": "Diario",
    },
    "4 Horas": {
        "yf_interval": "1h",
        "yf_periodo": "730d",   # límite real de Yahoo para intervalo 60m
        "resample": "4h",
        "sufijo_grafico": "4H",
    },
    "1 Hora": {
        "yf_interval": "1h",
        "yf_periodo": "730d",   # límite real de Yahoo para intervalo 60m
        "resample": None,
        "sufijo_grafico": "1H",
    },
    "45 Minutos": {
        "yf_interval": "15m",
        "yf_periodo": "60d",    # límite real de Yahoo para intervalos 5m/15m/30m
        "resample": "45min",    # Yahoo no ofrece 45m nativo, se arma desde 15m
        "sufijo_grafico": "45M",
    },
    "30 Minutos": {
        "yf_interval": "30m",
        "yf_periodo": "60d",    # límite real de Yahoo para intervalos 5m/15m/30m
        "resample": None,
        "sufijo_grafico": "30M",
    },
    "15 Minutos": {
        "yf_interval": "15m",
        "yf_periodo": "60d",
        "resample": None,
        "sufijo_grafico": "15M",
    },

    "5 Minutos": {
        "yf_interval": "5m",
        "yf_periodo": "60d",
        "resample": None,
        "sufijo_grafico": "5M",
    },
}
TIMEFRAME_DEFAULT = "1 Día"

# ----------------------------------------------------------------
#  Config de Darvas Box por temporalidad: ventana y confirmación
#  expresadas en velas, pero calculadas para representar una cantidad
#  de tiempo REAL distinta en cada timeframe (asumiendo ~24h de
#  mercado, razonable para forex/cripto; en acciones el día real
#  puede ser más largo, pero el objetivo acá es solo diferenciar
#  las temporalidades entre sí, no ser exacto al segundo).
#  Cuanto más chica la vela, ventana más corta/reciente en días;
#  cuanto más grande la vela, ventana más amplia.
# ----------------------------------------------------------------
DARVAS_CONFIG_POR_TIMEFRAME = {
    "1 Día":      {"ventana": 130, "confirmacion_velas": 3},    # ~130 días
    "4 Horas":    {"ventana": 270, "confirmacion_velas": 12},   # ~45 días
    "1 Hora":     {"ventana": 432, "confirmacion_velas": 24},   # ~18 días
    "45 Minutos": {"ventana": 384, "confirmacion_velas": 20},   # ~10 días
    "30 Minutos": {"ventana": 480, "confirmacion_velas": 24},   # ~6 días
    "15 Minutos": {"ventana": 640, "confirmacion_velas": 32},   # ~6 días
    "5 Minutos": {"ventana": 900, "confirmacion_velas": 36},   # ~6 días
}

# ----------------------------------------------------------------
#  Períodos de caja disponibles para el método ORB.
#  Se expresan en cantidad de velas de 5 minutos, porque la data de ORB
#  siempre se descarga en ese intervalo (ver _at_descargar_orb), sin
#  importar qué período de caja elija el usuario.
# ----------------------------------------------------------------
ORB_PERIODOS_DISPONIBLES = {
    "5 Minutos": 1,
    "15 Minutos": 3,
    "30 Minutos": 6,
}
ORB_PERIODO_DEFAULT = "15 Minutos"

# ----------------------------------------------------------------
#  Períodos de TPO disponibles para Market Profile. Igual que en ORB,
#  se expresan en cantidad de velas de 5 minutos porque la data siempre
#  se descarga en ese intervalo. 30 Minutos es el estándar clásico de
#  Market Profile (nació con barras de 30 min en el CBOT).
# ----------------------------------------------------------------
MARKET_PROFILE_PERIODOS_DISPONIBLES = {
    "15 Minutos": 3,
    "30 Minutos": 6,
    "60 Minutos": 12,
}
MARKET_PROFILE_PERIODO_DEFAULT = "30 Minutos"


# ==============================================================
#  SELECTOR DE ACTIVO (reemplaza al text_input libre)
# ==============================================================

def _at_seleccionar_ticker():
    """Devuelve (ticker, etiqueta_legible) según la categoría elegida."""
    categoria = st.selectbox('Tipo de activo', CATEGORIAS_ACTIVO, key='at_categoria')

    if categoria == "Acción (por industria)":
        industria = st.selectbox('Industria', sorted(ACCIONES_POR_INDUSTRIA.keys()), key='at_industria')
        ticker = st.selectbox('Ticker', sorted(set(ACCIONES_POR_INDUSTRIA[industria])), key='at_ticker_industria')
        return ticker, f"{ticker} ({industria})"

    elif categoria == "Forex":
        par = st.selectbox('Par de divisas', sorted(FOREX.keys()), key='at_forex_par')
        ticker, sub = FOREX[par]
        return ticker, f"{par} ({sub})"

    elif categoria == "Índice / País":
        pais = st.selectbox('País / Índice', sorted(PAISES.keys()), key='at_pais')
        ticker, region = PAISES[pais]
        return ticker, f"{pais} ({region})"

    elif categoria == "ETF de Índice":
        nombre = st.selectbox('Índice (vía ETF)', sorted(ETFS.keys()), key='at_etf_indice')
        ticker, cat, _color = ETFS[nombre]
        return ticker, f"{nombre} ({cat})"

    elif categoria == "ETF Sector / Subsector":
        nombre = st.selectbox('Sector / Subsector', sorted(SECTORES_TOTAL.keys()), key='at_etf_sector')
        ticker, cat, _color = SECTORES_TOTAL[nombre]
        return ticker, f"{nombre} ({cat})"

    elif categoria == "Mercado real (commodity / cripto)":
        nombre = st.selectbox('Mercado', sorted(MERCADOS_REALES.keys()), key='at_mercado_real')
        ticker, cat, _color = MERCADOS_REALES[nombre]
        return ticker, f"{nombre} ({cat})"

    else:  # Ticker manual
        ticker = st.text_input(
            'Ticker manual (cualquier activo soportado por Yahoo Finance)',
            value='AAPL', key='at_ticker_manual',
        ).strip().upper()
        return ticker, ticker


# ==============================================================
#  SELECTOR DE TEMPORALIDAD (métodos Weinstein / O'Neil / Darvas /
#  Wyckoff / CPR)
# ==============================================================

def _at_seleccionar_timeframe():
    """Devuelve la etiqueta de temporalidad elegida (clave de TIMEFRAMES_DISPONIBLES)."""
    return st.selectbox(
        'Temporalidad',
        list(TIMEFRAMES_DISPONIBLES.keys()),
        index=list(TIMEFRAMES_DISPONIBLES.keys()).index(TIMEFRAME_DEFAULT),
        key='at_timeframe',
    )


def _at_seleccionar_periodo_orb():
    """Devuelve la etiqueta de período de caja elegida para ORB (clave de
    ORB_PERIODOS_DISPONIBLES)."""
    return st.selectbox(
        'Período de la caja de apertura',
        list(ORB_PERIODOS_DISPONIBLES.keys()),
        index=list(ORB_PERIODOS_DISPONIBLES.keys()).index(ORB_PERIODO_DEFAULT),
        key='at_orb_periodo',
    )


def _at_seleccionar_periodo_market_profile():
    """Devuelve la etiqueta de período de TPO elegida (clave de
    MARKET_PROFILE_PERIODOS_DISPONIBLES)."""
    return st.selectbox(
        'Período de TPO',
        list(MARKET_PROFILE_PERIODOS_DISPONIBLES.keys()),
        index=list(MARKET_PROFILE_PERIODOS_DISPONIBLES.keys()).index(MARKET_PROFILE_PERIODO_DEFAULT),
        key='at_mp_periodo',
    )


# ==============================================================
#  DESCARGA DE DATOS (métodos Weinstein / O'Neil / Darvas / Wyckoff / CPR)
# ==============================================================

@st.cache_data(ttl=3600, show_spinner=False)
def _at_descargar(ticker, periodo='2y', intervalo='1d'):
    try:
        import yfinance as yf
        data = yf.Ticker(ticker).history(period=periodo, interval=intervalo, auto_adjust=True)
        data = data[["Open", "High", "Low", "Close", "Volume"]].dropna()
        return data if not data.empty else None
    except Exception:
        return None


def _at_resample_ohlcv(data, regla):
    """Agrupa velas (ej. de 15m o 1H) a una temporalidad mayor no soportada
    nativamente por Yahoo Finance (ej. 45m, 4H), respetando OHLCV."""
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    out = data.resample(regla).agg(agg)
    out = out.dropna(subset=["Open", "High", "Low", "Close"])
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def _at_obtener_datos(ticker, timeframe_label):
    """Descarga los datos de `ticker` en la temporalidad elegida,
    resampleando si hace falta (casos 4H y 45M)."""
    if timeframe_label not in TIMEFRAMES_DISPONIBLES:
        timeframe_label = TIMEFRAME_DEFAULT
    cfg = TIMEFRAMES_DISPONIBLES[timeframe_label]

    data = _at_descargar(ticker, periodo=cfg["yf_periodo"], intervalo=cfg["yf_interval"])
    if data is None or data.empty:
        return None

    if cfg["resample"]:
        data = _at_resample_ohlcv(data, cfg["resample"])
        if data.empty:
            return None

    return data


def _at_agregar_medias(data):
    data = data.copy()
    data["MM30"] = data["Close"].rolling(window=30).mean()
    data["MM50"] = data["Close"].rolling(window=50).mean()
    data["MM150"] = data["Close"].rolling(window=150).mean()
    data["MM200"] = data["Close"].rolling(window=200).mean()
    return data


# ==============================================================
#  DESCARGA DE DATOS (métodos ORB y Market Profile — velas intradía de
#  5 minutos, trabajan por sesión)
# ==============================================================

@st.cache_data(ttl=300, show_spinner=False)
def _at_descargar_orb(ticker):
    """Descarga velas de 5 minutos, usadas tanto por ORB como por Market
    Profile (y como fallback del gráfico de CPR). TTL corto (5 min, a
    diferencia de 1 hora en los otros métodos) porque acá interesa la
    sesión más reciente, posiblemente en curso. Yahoo Finance devuelve
    por default solo el horario regular de mercado (prepost=False), así
    que la primera vela de cada día calendario en el resultado coincide
    con la apertura real de la sesión — no hace falta resolver el huso
    horario ni la hora de apertura de cada exchange a mano."""
    try:
        import yfinance as yf
        data = yf.Ticker(ticker).history(period="60d", interval="5m", auto_adjust=True, prepost=False)
        data = data[["Open", "High", "Low", "Close", "Volume"]].dropna()
        return data if not data.empty else None
    except Exception:
        return None


def _at_seleccionar_sesion(data, min_velas=1):
    """A partir de velas de 5 minutos ya descargadas, devuelve (sub_dia,
    fecha) de la sesión (día calendario) más reciente que tenga al menos
    `min_velas` velas — típicamente la sesión en curso, o la última
    sesión completa si la de hoy todavía no llegó al mínimo pedido.
    Devuelve (None, None) si ninguna sesión alcanza ese mínimo. Función
    compartida por ORB, Market Profile y el gráfico intradía de CPR."""
    if data is None or data.empty:
        return None, None
    fechas = sorted(set(data.index.date))
    for fecha in reversed(fechas):
        sub_fecha = data[data.index.date == fecha]
        if len(sub_fecha) >= min_velas:
            return sub_fecha, fecha
    return None, None


# ==============================================================
#  ADX DE WILDER (filtro de tendencia, uso transversal en Weinstein/
#  O'Neil/Darvas/Wyckoff/CPR — ORB usa su propio ATR, más abajo)
# ==============================================================

def _at_calcular_adx(data, periodo=14):
    """ADX (Average Directional Index) de Welles Wilder. Filtro objetivo de
    '¿hay tendencia establecida o no?', reutilizado dentro de O'Neil y como
    dato informativo en Weinstein/Darvas/Wyckoff/CPR. ADX >= 25 = umbral
    clásico de tendencia establecida. El período (14 barras) se mantiene
    fijo sin importar la temporalidad, tal como se usa habitualmente en
    cualquier gráfico (14 velas de 1H, de 4H o diarias)."""
    high, low, close = data["High"], data["Low"], data["Close"]
    prev_close, prev_high, prev_low = close.shift(1), high.shift(1), low.shift(1)

    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)

    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=data.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=data.index)

    tr_s = tr.ewm(alpha=1 / periodo, adjust=False).mean()
    plus_dm_s = plus_dm.ewm(alpha=1 / periodo, adjust=False).mean()
    minus_dm_s = minus_dm.ewm(alpha=1 / periodo, adjust=False).mean()

    plus_di = 100 * (plus_dm_s / tr_s)
    minus_di = 100 * (minus_dm_s / tr_s)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.ewm(alpha=1 / periodo, adjust=False).mean()

    return plus_di, minus_di, adx


# ==============================================================
#  MÉTODO 1: STAN WEINSTEIN
# ==============================================================

def _at_analizar_weinstein(data):
    mm30_actual = data["MM30"].iloc[-1]
    pendiente_mm30 = data["MM30"].diff().iloc[-5:].mean()
    precio = data["Close"].iloc[-1]

    if precio > mm30_actual and pendiente_mm30 > 0:
        fase = "Fase 2 – Tendencia alcista"
        descripcion = "El precio está por encima de la MM30 y la media sube. Señal alcista."
    elif precio < mm30_actual and pendiente_mm30 < 0:
        fase = "Fase 4 – Tendencia bajista"
        descripcion = "El precio está por debajo de la MM30 y la media baja. Señal bajista."
    elif abs(precio - mm30_actual) / mm30_actual < 0.03 and abs(pendiente_mm30) < 0.01:
        fase = "Fase 1 – Acumulación"
        descripcion = "El precio y la MM30 se mueven lateralmente sin tendencia clara."
    else:
        fase = "Fase 3 – Distribución"
        descripcion = "El precio pierde fuerza, lateraliza cerca de la MM30. Posible techo."

    if "Fase 2" in fase:
        conclusion = ("El activo está en tendencia alcista confirmada. Es la fase que Weinstein "
                      "considera apta para comprar o mantener posiciones ya abiertas.")
    elif "Fase 4" in fase:
        conclusion = ("El activo está en tendencia bajista confirmada. Weinstein recomienda evitar "
                      "compras acá y, si tenés posición, priorizar la salida o esperar una nueva Fase 1.")
    elif "Fase 1" in fase:
        conclusion = ("El activo está lateralizando, sin tendencia definida. Es una fase de espera: "
                      "conviene monitorear hasta que se confirme una ruptura al alza (Fase 2) o a la baja (Fase 4).")
    else:
        conclusion = ("El activo muestra señales de agotamiento tras una suba. Es momento de cautela, "
                      "ya que suele preceder a un cambio de tendencia hacia la Fase 4.")

    resumen = {
        "Método": "Stan Weinstein", "Señal principal": fase, "Descripción": descripcion,
        "MM30 actual": mm30_actual, "Pendiente MM30 (5 velas)": pendiente_mm30,
        "ADX(14)": data["ADX"].iloc[-1],
        "+DI / -DI": f"{data['+DI'].iloc[-1]:.1f} / {data['-DI'].iloc[-1]:.1f}",
        "Conclusión": conclusion,
    }
    return resumen, [("MM30", data["MM30"])], []


# ==============================================================
#  FUERZA RELATIVA (usada por O'Neil)
# ==============================================================

def _at_calcular_rs_rating(data, benchmark_data):
    """Fuerza relativa simplificada estilo IBD: compara el retorno del activo
    contra el benchmark en distintas ventanas, ponderando más lo reciente.
    No es el RS Rating oficial de IBD, pero sigue la misma lógica.
    Las ventanas están expresadas en cantidad de velas (igual que en el
    original, que usaba velas diarias); en temporalidades intradiarias
    representan una porción de tiempo menor, lo cual es esperable."""
    activo = data["Close"]
    bench = benchmark_data["Close"].reindex(activo.index, method="nearest")

    ventanas, pesos = [63, 126, 189, 252], [0.4, 0.2, 0.2, 0.2]
    score = 0
    for w, p in zip(ventanas, pesos):
        w = min(w, len(activo) - 1)
        if w <= 0:
            continue
        ret_activo = activo.iloc[-1] / activo.iloc[-w] - 1
        ret_bench = bench.iloc[-1] / bench.iloc[-w] - 1
        score += p * (ret_activo - ret_bench)

    return int(np.clip(50 + score * 200, 1, 99))


# ==============================================================
#  MÉTODO 2: WILLIAM O'NEIL
# ==============================================================

def _at_analizar_oneil(data, benchmark_data):
    precio = data["Close"].iloc[-1]
    mm50, mm150 = data["MM50"].iloc[-1], data["MM150"].iloc[-1]

    maximo_52 = data["Close"].rolling(window=252, min_periods=50).max().iloc[-1]
    minimo_52 = data["Close"].rolling(window=252, min_periods=50).min().iloc[-1]
    distancia_maximo = (precio / maximo_52 - 1) * 100
    distancia_minimo = (precio / minimo_52 - 1) * 100

    vol_mm50 = data["Volume"].rolling(50).mean().iloc[-1]
    vol_mm10 = data["Volume"].rolling(10).mean().iloc[-1]
    volumen_creciente = bool(vol_mm10 > vol_mm50)

    rs_rating = None
    if benchmark_data is not None:
        try:
            rs_rating = _at_calcular_rs_rating(data, benchmark_data)
        except Exception:
            rs_rating = None

    adx_actual = data["ADX"].iloc[-1]
    plus_di_actual, minus_di_actual = data["+DI"].iloc[-1], data["-DI"].iloc[-1]
    tendencia_confirmada_adx = bool(
        not np.isnan(adx_actual) and adx_actual >= 25 and plus_di_actual > minus_di_actual
    )

    condiciones = {
        "Precio sobre MM50": bool(precio > mm50),
        "Precio sobre MM150": bool(precio > mm150),
        "Cerca del máximo del rango analizado (dentro del 15%)": bool(distancia_maximo >= -15),
        "Lejos del mínimo del rango analizado (>=30% sobre el piso)": bool(distancia_minimo >= 30),
        "Volumen en expansión (promedio 10 velas > promedio 50 velas)": volumen_creciente,
        "ADX(14) >= 25 con +DI > -DI (tendencia alcista confirmada por Wilder)": tendencia_confirmada_adx,
    }
    if rs_rating is not None:
        condiciones["RS Rating aproximado >= 70 (fuerte vs mercado)"] = bool(rs_rating >= 70)

    cumplidas, total = sum(condiciones.values()), len(condiciones)

    if cumplidas == total:
        senal = "Configuración O'Neil COMPLETA – Candidato de compra / líder de mercado"
    elif cumplidas >= total - 1:
        senal = "Configuración O'Neil casi completa – Vigilar de cerca"
    elif cumplidas >= total / 2:
        senal = "Configuración parcial – Falta confirmar fuerza"
    else:
        senal = "No cumple criterios O'Neil – Débil frente al mercado"

    rs_texto = f"un RS Rating aproximado de {rs_rating}" if rs_rating is not None else "sin dato de RS Rating"
    if cumplidas == total:
        conclusion = (f"El activo cumple todos los criterios de O'Neil: está por encima de sus medias "
                      f"móviles clave, cerca de máximos del rango analizado, con volumen en expansión, tendencia "
                      f"confirmada por ADX y {rs_texto}. Es el perfil de 'líder de mercado' que busca CANSLIM.")
    elif cumplidas >= total - 1:
        conclusion = ("Al activo le falta un solo criterio para el perfil O'Neil completo. Vale la pena "
                      "seguirlo de cerca, está muy cerca de mostrar fuerza relativa frente al mercado.")
    elif cumplidas >= total / 2:
        conclusion = ("El activo cumple parte de los criterios, pero todavía no muestra la fuerza y el "
                      "acompañamiento de volumen que O'Neil exige para considerarlo un líder claro.")
    else:
        conclusion = ("El activo está débil frente al criterio O'Neil: lejos de máximos, sin acompañamiento "
                      "de volumen o por debajo de sus medias móviles clave. No es el momento para este método.")

    resumen = {
        "Método": "William O'Neil (CANSLIM técnico)", "Señal principal": senal,
        "Criterios cumplidos": f"{cumplidas}/{total}", "Detalle": condiciones,
        "% respecto al máximo del rango": distancia_maximo, "% respecto al mínimo del rango": distancia_minimo,
        "RS Rating (aprox., no oficial IBD)": rs_rating, "ADX(14)": adx_actual, "Conclusión": conclusion,
    }
    return resumen, [("MM50", data["MM50"]), ("MM150", data["MM150"])], []


# ==============================================================
#  MÉTODO 3: DARVAS BOX
# ==============================================================

def _at_detectar_darvas_box(data, ventana=130, dias_confirmacion=3, tolerancia_pct=1.0):
    """Detección algorítmica simplificada de Cajas de Darvas: techo confirmado
    tras N velas sin ser superado, piso = mínimo posterior mientras el precio
    se mantenga dentro de la caja, breakout = cierre sobre el techo con
    volumen por encima del promedio. `ventana` y `dias_confirmacion` están
    en cantidad de velas, no de días calendario, así que funcionan igual
    sin importar la temporalidad elegida."""
    sub = data.tail(ventana).copy()
    highs, lows, closes, fechas, n = sub["High"].values, sub["Low"].values, sub["Close"].values, sub.index, len(sub)

    cajas, i = [], 0
    while i < n:
        max_local, idx_max, j, confirmado = highs[i], i, i + 1, 0
        while j < n and confirmado < dias_confirmacion:
            if highs[j] > max_local:
                max_local, idx_max, confirmado = highs[j], j, 0
            else:
                confirmado += 1
            j += 1
        if confirmado < dias_confirmacion:
            break

        techo, idx_techo = max_local, idx_max
        piso, idx_piso = lows[idx_techo], idx_techo
        k = idx_techo + 1
        while k < n:
            if closes[k] > techo * (1 + tolerancia_pct / 100):
                break
            if lows[k] < piso:
                piso, idx_piso = lows[k], k
            if closes[k] < piso * (1 - tolerancia_pct / 100):
                break
            k += 1

        cajas.append({"techo": techo, "piso": piso, "fecha_techo": fechas[idx_techo],
                       "fecha_piso": fechas[idx_piso], "fin_idx": k})
        i = k if k > idx_techo else idx_techo + 1

    if not cajas:
        return {"detectado": False, "caja_actual": None}

    caja_actual = cajas[-1]
    techo, piso = caja_actual["techo"], caja_actual["piso"]
    precio_actual, volumen_actual = data["Close"].iloc[-1], data["Volume"].iloc[-1]
    vol_mm50 = data["Volume"].rolling(50).mean().iloc[-1]

    ancho_caja_pct = (techo - piso) / piso * 100
    breakout = bool(precio_actual > techo and volumen_actual > vol_mm50 * 1.3)
    dentro_de_caja = bool(piso <= precio_actual <= techo * (1 + tolerancia_pct / 100))

    criterios = {
        "Caja angosta (ancho <= 15%, consolidación real)": bool(ancho_caja_pct <= 15),
        "Precio dentro o rompiendo la caja actual": bool(dentro_de_caja or breakout),
        "Breakout con volumen (> 1.3x MM50 de volumen)": breakout,
    }

    return {"detectado": True, "caja_actual": caja_actual, "techo": techo, "piso": piso,
            "ancho_caja_pct": ancho_caja_pct, "breakout": breakout, "criterios": criterios}


def _at_analizar_darvas(data, timeframe_label=TIMEFRAME_DEFAULT):
    cfg_darvas = DARVAS_CONFIG_POR_TIMEFRAME.get(timeframe_label, DARVAS_CONFIG_POR_TIMEFRAME[TIMEFRAME_DEFAULT])
    resultado = _at_detectar_darvas_box(
        data,
        ventana=cfg_darvas["ventana"],
        dias_confirmacion=cfg_darvas["confirmacion_velas"],
    )
    adx_actual = data["ADX"].iloc[-1]

    if not resultado["detectado"]:
        resumen = {
            "Método": "Darvas Box",
            "Señal principal": "No se pudo identificar una Caja de Darvas clara con los datos disponibles",
            "ADX(14)": adx_actual,
            "Conclusión": ("No se detectó una secuencia de techo/piso confirmada en la ventana analizada. "
                          "Puede que el activo esté en tendencia demasiado limpia o con demasiada "
                          "volatilidad para formar una caja clásica de Darvas en esta temporalidad."),
        }
        return resumen, [], []

    criterios = resultado["criterios"]
    cumplidas, total = sum(criterios.values()), len(criterios)
    breakout = resultado["breakout"]

    if breakout and cumplidas == total:
        senal = "BREAKOUT confirmado de la Caja de Darvas – Señal de compra clásica"
    elif breakout:
        senal = "Breakout del techo, pero sin confirmación total (revisar volumen/ancho)"
    elif cumplidas >= total - 1:
        senal = "Precio dentro de una caja angosta – Vigilar breakout inminente"
    else:
        senal = "Caja identificada pero todavía amplia / sin condiciones de breakout"

    if breakout and cumplidas == total:
        conclusion = (f"El precio rompió el techo de la caja (USD {resultado['techo']:.2f}) con volumen por "
                      f"encima del promedio, cumpliendo la regla clásica de Darvas: comprar en la ruptura de "
                      f"una caja angosta con más volumen que lo normal, usando el piso (USD {resultado['piso']:.2f}) "
                      f"como referencia de stop.")
    elif breakout:
        conclusion = ("Hay ruptura del techo, pero la caja no era lo suficientemente angosta o el volumen no "
                      "acompañó del todo. Darvas exigía ambas condiciones; conviene ser cauteloso.")
    else:
        conclusion = (f"El precio se mantiene dentro de la caja actual (piso USD {resultado['piso']:.2f} – "
                      f"techo USD {resultado['techo']:.2f}, ancho {resultado['ancho_caja_pct']:.1f}%). "
                      f"Conviene esperar la ruptura del techo con volumen antes de actuar.")

    resumen = {
        "Método": "Darvas Box", "Señal principal": senal, "Criterios cumplidos": f"{cumplidas}/{total}",
        "Detalle": criterios, "Techo de la caja actual": resultado["techo"],
        "Piso de la caja actual": resultado["piso"], "Ancho de la caja (%)": resultado["ancho_caja_pct"],
        "ADX(14)": adx_actual, "Conclusión": conclusion,
    }
    marcadores = [
        (resultado["caja_actual"]["fecha_techo"], resultado["techo"], "pico"),
        (resultado["caja_actual"]["fecha_piso"], resultado["piso"], "valle"),
    ]
    return resumen, [], marcadores


# ==============================================================
#  MÉTODO 4: WYCKOFF (Acumulación/Distribución)
# ==============================================================

def _at_analizar_wyckoff(data, ventana=90):
    """Aproximación heurística al esquema de Wyckoff usando volumen, spread
    y posición del precio dentro del rango reciente. No sustituye una
    lectura barra-por-barra de eventos (Spring, Test, UTAD, SOS, SOW).
    `ventana` está en cantidad de velas, igual en todas las temporalidades."""
    sub = data.tail(ventana).copy()
    precio, mm50 = data["Close"].iloc[-1], data["MM50"].iloc[-1]
    mm50_hace_20 = data["MM50"].iloc[-21] if len(data) > 21 else np.nan
    tendencia_mm50 = "ascendente" if (not np.isnan(mm50_hace_20) and mm50 > mm50_hace_20) else "descendente"

    maximo_rango, minimo_rango = sub["High"].max(), sub["Low"].min()
    rango_total = maximo_rango - minimo_rango
    posicion_en_rango = (precio - minimo_rango) / rango_total * 100 if rango_total > 0 else 50

    spread = sub["High"] - sub["Low"]
    compresion = bool(spread.tail(15).mean() < spread.mean() * 0.8)

    vol_mm50_serie = data["Volume"].rolling(50).mean()
    dias_climax = sub[sub["Volume"] > vol_mm50_serie.reindex(sub.index) * 2]
    hay_climax_reciente = bool(len(dias_climax.tail(15)) > 0)

    if compresion and posicion_en_rango <= 35 and tendencia_mm50 == "descendente":
        fase = "Posible Acumulación"
        descripcion = ("El precio lateraliza en la parte baja de su rango reciente, con contracción de "
                       "volatilidad tras una tendencia bajista. " +
                       ("Se detectó volumen de clímax reciente (posible Selling Climax / Spring)."
                        if hay_climax_reciente else "Todavía sin un clímax de volumen claro que confirme el piso."))
    elif not compresion and posicion_en_rango >= 60 and tendencia_mm50 == "ascendente" and precio > mm50:
        fase = "Markup (Tendencia alcista)"
        descripcion = ("El precio está en la parte alta de su rango reciente, con la MM50 ascendente. "
                       "Fase de tendencia alcista activa (expansión de rango).")
    elif compresion and posicion_en_rango >= 65 and tendencia_mm50 == "ascendente":
        fase = "Posible Distribución"
        descripcion = ("El precio lateraliza en la parte alta de su rango tras una suba, con contracción de "
                       "volatilidad. " +
                       ("Se detectó volumen de clímax reciente (posible Buying Climax / UTAD)."
                        if hay_climax_reciente else "Todavía sin un clímax de volumen claro que confirme el techo."))
    elif not compresion and posicion_en_rango <= 40 and tendencia_mm50 == "descendente" and precio < mm50:
        fase = "Markdown (Tendencia bajista)"
        descripcion = ("El precio está en la parte baja de su rango reciente, con la MM50 descendente. "
                       "Fase de tendencia bajista activa.")
    else:
        fase = "Fase indefinida / transición"
        descripcion = ("La combinación de rango, volumen y tendencia no encaja claramente en ninguna de las "
                       "4 fases clásicas de Wyckoff con los umbrales usados acá.")

    conclusiones = {
        "Posible Acumulación": ("El activo muestra señales compatibles con una fase de Acumulación: "
                                 "lateralización tras la baja, con contracción de volatilidad. Si aparece un "
                                 "clímax de volumen seguido de un Spring y un Test exitoso, sería la "
                                 "confirmación clásica para buscar el inicio del Markup."),
        "Markup (Tendencia alcista)": ("El activo está en Markup: tendencia alcista confirmada con expansión "
                                        "de rango y precio en la parte alta de su banda reciente. Es la fase "
                                        "que Wyckoff considera para mantener o sumar posiciones."),
        "Posible Distribución": ("El activo muestra señales compatibles con una fase de Distribución: "
                                  "lateralización tras la suba, en la parte alta del rango, con contracción "
                                  "de volatilidad. Si aparece un clímax de volumen y luego un UTAD fallido, "
                                  "sería la confirmación clásica de un techo antes del Markdown."),
        "Markdown (Tendencia bajista)": ("El activo está en Markdown: tendencia bajista confirmada, con "
                                          "precio en la parte baja de su rango reciente. Conviene evitar "
                                          "compras y esperar señales de Acumulación."),
        "Fase indefinida / transición": ("No hay una fase de Wyckoff clara todavía. Conviene esperar más "
                                          "definición en el rango y el volumen antes de sacar conclusiones."),
    }

    resumen = {
        "Método": "Wyckoff (Acumulación/Distribución) — aproximación algorítmica", "Señal principal": fase,
        "Descripción": descripcion, "Posición dentro del rango reciente (%)": posicion_en_rango,
        "Tendencia MM50": tendencia_mm50, "Compresión de volatilidad reciente": compresion,
        "Clímax de volumen detectado (últimas 15 velas)": hay_climax_reciente,
        "Máximo del rango analizado": maximo_rango, "Mínimo del rango analizado": minimo_rango,
        "ADX(14)": data["ADX"].iloc[-1], "Conclusión": conclusiones[fase],
    }
    return resumen, [("MM50", data["MM50"])], []


# ==============================================================
#  MÉTODO 5: CPR (Central Pivot Range) + niveles R1–R4 / S1–S4
# ==============================================================

def _at_calcular_cpr(data):
    """Central Pivot Range + niveles de floor traders, calculados con la
    vela ANTERIOR y proyectados sobre la vela actual:
      Pivot = (H+L+C)/3
      BC (Bottom Central) = (H+L)/2      TC (Top Central) = 2*Pivot - BC
      R1 = 2*Pivot - L        S1 = 2*Pivot - H
      R2 = Pivot + (H - L)    S2 = Pivot - (H - L)
      R3 = H + 2*(Pivot - L)  S3 = L - 2*(H - Pivot)
      R4 = R3 + (R2 - R1)     S4 = S3 - (S1 - S2)
    El ancho del CPR (TC - BC) sigue siendo la señal de "tipo de período":
    angosto = probable tendencia/breakout, ancho = probable rango.
    Funciona igual sin importar la temporalidad elegida porque opera
    sobre 'la vela anterior', no sobre una cantidad fija de días."""
    h, l, c = data["High"].shift(1), data["Low"].shift(1), data["Close"].shift(1)

    pivot = (h + l + c) / 3
    bc_raw = (h + l) / 2
    tc_raw = 2 * pivot - bc_raw
    # normalizamos para que "techo" sea siempre el mayor de los dos
    techo = pd.concat([tc_raw, bc_raw], axis=1).max(axis=1)
    piso = pd.concat([tc_raw, bc_raw], axis=1).min(axis=1)
    ancho = techo - piso

    r1 = 2 * pivot - l
    s1 = 2 * pivot - h
    r2 = pivot + (h - l)
    s2 = pivot - (h - l)
    r3 = h + 2 * (pivot - l)
    s3 = l - 2 * (h - pivot)
    r4 = r3 + (r2 - r1)
    s4 = s3 - (s1 - s2)

    return {
        "pivot": pivot, "techo": techo, "piso": piso, "ancho": ancho,
        "r1": r1, "r2": r2, "r3": r3, "r4": r4,
        "s1": s1, "s2": s2, "s3": s3, "s4": s4,
    }


def _at_analizar_cpr(data, ventana_ancho=10):
    niveles_series = _at_calcular_cpr(data)
    data = data.copy()
    for nombre, serie in niveles_series.items():
        data[f"CPR_{nombre}"] = serie

    precio = data["Close"].iloc[-1]
    valores_actuales = {k: v.iloc[-1] for k, v in niveles_series.items()}
    pivot_actual, techo_actual, piso_actual = valores_actuales["pivot"], valores_actuales["techo"], valores_actuales["piso"]
    ancho_actual = valores_actuales["ancho"]
    ancho_promedio = niveles_series["ancho"].tail(ventana_ancho).mean()

    ancho_pct_vs_promedio = (
        (ancho_actual / ancho_promedio - 1) * 100
        if ancho_promedio and not np.isnan(ancho_promedio) else np.nan
    )
    if not np.isnan(ancho_pct_vs_promedio) and ancho_pct_vs_promedio <= -25:
        tipo_periodo = "CPR angosto — probable período de tendencia/breakout"
    elif not np.isnan(ancho_pct_vs_promedio) and ancho_pct_vs_promedio >= 25:
        tipo_periodo = "CPR ancho — probable período lateral / de rango"
    else:
        tipo_periodo = "CPR de ancho normal — sin sesgo claro de tipo de período"

    # ---- Ubicar el precio dentro de la escalera completa de niveles ----
    escalera = sorted(
        [
            ("S4", valores_actuales["s4"]), ("S3", valores_actuales["s3"]),
            ("S2", valores_actuales["s2"]), ("S1", valores_actuales["s1"]),
            ("BC", piso_actual), ("Pivot", pivot_actual), ("TC", techo_actual),
            ("R1", valores_actuales["r1"]), ("R2", valores_actuales["r2"]),
            ("R3", valores_actuales["r3"]), ("R4", valores_actuales["r4"]),
        ],
        key=lambda par: par[1],
    )
    resistencia = next(((nom, val) for nom, val in escalera if val > precio), None)
    soporte = next(((nom, val) for nom, val in reversed(escalera) if val < precio), None)

    if precio > techo_actual:
        posicion, sesgo = "Precio por ENCIMA del CPR (sobre el TC)", "alcista"
    elif precio < piso_actual:
        posicion, sesgo = "Precio por DEBAJO del CPR (bajo el BC)", "bajista"
    else:
        posicion, sesgo = "Precio DENTRO del CPR (entre BC y TC)", "neutral"

    adx_actual = data["ADX"].iloc[-1] if "ADX" in data.columns else np.nan
    plus_di_actual = data["+DI"].iloc[-1] if "+DI" in data.columns else np.nan
    minus_di_actual = data["-DI"].iloc[-1] if "-DI" in data.columns else np.nan
    adx_confirma_alcista = bool(not np.isnan(adx_actual) and adx_actual >= 25 and plus_di_actual > minus_di_actual)
    adx_confirma_bajista = bool(not np.isnan(adx_actual) and adx_actual >= 25 and minus_di_actual > plus_di_actual)

    zona_texto = ""
    if soporte and resistencia:
        zona_texto = f"Zona actual: entre {soporte[0]} (${soporte[1]:.2f}) y {resistencia[0]} (${resistencia[1]:.2f})."
    objetivo_texto = ""
    if resistencia:
        objetivo_texto += f" Próxima resistencia: {resistencia[0]} (${resistencia[1]:.2f})."
    if soporte:
        objetivo_texto += f" Próximo soporte: {soporte[0]} (${soporte[1]:.2f})."

    if sesgo == "alcista":
        senal = "Ruptura alcista del CPR" + (" con tendencia confirmada por ADX" if adx_confirma_alcista else "")
        conclusion = (f"El precio superó el techo del CPR (TC ${techo_actual:.2f}), calculado con la vela "
                      f"anterior. {tipo_periodo}. {zona_texto}{objetivo_texto} Mientras se sostenga arriba "
                      f"del CPR el sesgo de corto plazo es alcista; una pérdida del pivot (${pivot_actual:.2f}) "
                      f"debilitaría el escenario.")
    elif sesgo == "bajista":
        senal = "Ruptura bajista del CPR" + (" con tendencia confirmada por ADX" if adx_confirma_bajista else "")
        conclusion = (f"El precio perdió el piso del CPR (BC ${piso_actual:.2f}), calculado con la vela "
                      f"anterior. {tipo_periodo}. {zona_texto}{objetivo_texto} Mientras se sostenga debajo "
                      f"del CPR el sesgo de corto plazo es bajista; una recuperación del pivot "
                      f"(${pivot_actual:.2f}) debilitaría el escenario.")
    else:
        senal = "Precio dentro del CPR — zona de equilibrio"
        conclusion = (f"El precio está dentro del rango del CPR (piso ${piso_actual:.2f} – techo "
                      f"${techo_actual:.2f}), zona de equilibrio entre compradores y vendedores. {tipo_periodo}. "
                      f"{zona_texto}{objetivo_texto} Conviene esperar una ruptura confirmada de TC o BC antes "
                      f"de tomar una posición direccional.")

    resumen = {
        "Método": "CPR (Central Pivot Range)",
        "Señal principal": senal,
        "Descripción": posicion,
        "R4": valores_actuales["r4"], "R3": valores_actuales["r3"],
        "R2": valores_actuales["r2"], "R1": valores_actuales["r1"],
        "TC (techo)": techo_actual, "Pivot": pivot_actual, "BC (piso)": piso_actual,
        "S1": valores_actuales["s1"], "S2": valores_actuales["s2"],
        "S3": valores_actuales["s3"], "S4": valores_actuales["s4"],
        "Ancho del CPR": ancho_actual,
        "Ancho vs. promedio reciente (%)": ancho_pct_vs_promedio,
        "Tipo de período esperado": tipo_periodo,
        "ADX(14)": adx_actual,
        "Conclusión": conclusion,
    }
    lineas_extra = [
        ("R2", data["CPR_r2"]), ("R1", data["CPR_r1"]), ("TC", data["CPR_techo"]),
        ("Pivot", data["CPR_pivot"]), ("BC", data["CPR_piso"]),
        ("S1", data["CPR_s1"]), ("S2", data["CPR_s2"]),
    ]
    return resumen, lineas_extra, []


# ==============================================================
#  MÉTODO 6: MARKET PROFILE (TPO)
# ==============================================================

def _at_generar_letra_tpo(indice):
    """Genera la letra de un período TPO (A, B, C, ..., Z, a, b, c, ...).
    Un día de cripto (24hs) puede superar las 26 letras con TPOs de 30
    minutos (48 períodos), por eso se sigue con minúsculas."""
    letras = string.ascii_uppercase + string.ascii_lowercase
    return letras[indice % len(letras)]


def _at_construir_market_profile(sub_dia, n_velas_periodo, n_filas=30):
    """Arma el perfil de mercado (TPO) de una sesión: divide la sesión en
    bloques de `n_velas_periodo` velas de 5 minutos (períodos TPO de
    15/30/60 minutos) y cuenta, para cada nivel de precio, cuántos
    períodos TPO distintos tocaron ese nivel. Devuelve el histograma de
    TPOs por nivel y el precio representativo de cada nivel."""
    maximo, minimo = sub_dia["High"].max(), sub_dia["Low"].min()
    rango_total = maximo - minimo
    if rango_total <= 0:
        return None

    alto_fila = rango_total / n_filas
    n_bloques = int(np.ceil(len(sub_dia) / n_velas_periodo))

    tpo_por_fila = np.zeros(n_filas, dtype=int)
    letras_por_fila = [[] for _ in range(n_filas)]

    for b in range(n_bloques):
        bloque = sub_dia.iloc[b * n_velas_periodo:(b + 1) * n_velas_periodo]
        if bloque.empty:
            continue
        letra = _at_generar_letra_tpo(b)
        high_bloque, low_bloque = bloque["High"].max(), bloque["Low"].min()

        fila_inicio = int((low_bloque - minimo) / alto_fila)
        fila_fin = int((high_bloque - minimo) / alto_fila)
        fila_inicio = max(0, min(fila_inicio, n_filas - 1))
        fila_fin = max(0, min(fila_fin, n_filas - 1))

        for fila in range(fila_inicio, fila_fin + 1):
            tpo_por_fila[fila] += 1
            letras_por_fila[fila].append(letra)

    precios_fila = minimo + (np.arange(n_filas) + 0.5) * alto_fila

    return {
        "tpo_por_fila": tpo_por_fila, "precios_fila": precios_fila,
        "letras_por_fila": letras_por_fila, "alto_fila": alto_fila,
        "maximo": maximo, "minimo": minimo,
    }


def _at_calcular_poc_y_valor(perfil, porcentaje_valor=0.70):
    """POC = nivel de precio con más TPOs (más tiempo de la sesión). Área
    de Valor = expansión desde el POC hacia arriba/abajo hasta cubrir el
    70% del total de TPOs, agregando de a una fila por vez del lado con
    más actividad — el algoritmo clásico de Market Profile."""
    tpo = perfil["tpo_por_fila"]
    precios = perfil["precios_fila"]
    alto_fila = perfil["alto_fila"]
    total_tpo = int(tpo.sum())
    if total_tpo == 0:
        return None

    poc_idx = int(np.argmax(tpo))
    objetivo = total_tpo * porcentaje_valor

    fila_inf, fila_sup = poc_idx, poc_idx
    acumulado = int(tpo[poc_idx])

    while acumulado < objetivo and (fila_inf > 0 or fila_sup < len(tpo) - 1):
        cuenta_abajo = tpo[fila_inf - 1] if fila_inf > 0 else -1
        cuenta_arriba = tpo[fila_sup + 1] if fila_sup < len(tpo) - 1 else -1

        if cuenta_arriba >= cuenta_abajo and cuenta_arriba >= 0:
            fila_sup += 1
            acumulado += tpo[fila_sup]
        elif cuenta_abajo >= 0:
            fila_inf -= 1
            acumulado += tpo[fila_inf]
        else:
            break

    return {
        "poc_precio": precios[poc_idx], "poc_idx": poc_idx,
        "val_precio": precios[fila_inf] - alto_fila / 2,
        "vah_precio": precios[fila_sup] + alto_fila / 2,
        "fila_inf": fila_inf, "fila_sup": fila_sup,
        "total_tpo": total_tpo, "porcentaje_cubierto": acumulado / total_tpo * 100,
    }


def _at_clasificar_forma_perfil(perfil, poc_info):
    """Clasifica la forma del perfil según dónde cae el POC en el rango, y
    si hay un segundo pico significativo separado del POC por un valle
    (Doble Distribución). Heurística simplificada — no sustituye la
    lectura visual completa de un Market Profile, pero da una idea rápida
    del tipo de sesión."""
    tpo = perfil["tpo_por_fila"]
    n_filas = len(tpo)
    poc_idx = poc_info["poc_idx"]
    posicion_poc_pct = poc_idx / (n_filas - 1) * 100 if n_filas > 1 else 50

    umbral_pico_secundario = tpo[poc_idx] * 0.7 if poc_info["total_tpo"] > 0 else 0
    doble_distribucion = False
    for i in range(1, n_filas - 1):
        if i == poc_idx:
            continue
        es_pico_local = tpo[i] > tpo[i - 1] and tpo[i] > tpo[i + 1]
        if es_pico_local and tpo[i] >= umbral_pico_secundario and abs(i - poc_idx) > n_filas * 0.15:
            inicio, fin = sorted([i, poc_idx])
            valle = tpo[inicio + 1:fin] if fin > inicio + 1 else np.array([0])
            if valle.size and valle.min() < min(tpo[i], tpo[poc_idx]) * 0.5:
                doble_distribucion = True
                break

    if doble_distribucion:
        return "Doble Distribución (posible cambio de sesgo intra-sesión)"
    elif posicion_poc_pct >= 70:
        return "Día de Tendencia Alcista (POC en la parte alta del rango)"
    elif posicion_poc_pct <= 30:
        return "Día de Tendencia Bajista (POC en la parte baja del rango)"
    else:
        return "Día Normal / Balanceado (POC cerca del centro del rango)"


def _at_analizar_market_profile(ticker, periodo_tpo_label):
    """Arma el Market Profile (TPO) de la sesión más reciente disponible:
    Punto de Control (POC), Área de Valor (VAH/VAL) y forma del día.

    Devuelve (resumen, contexto_grafico) si pudo analizar, o (None, mensaje)
    si no hay datos suficientes."""
    n_velas_periodo = MARKET_PROFILE_PERIODOS_DISPONIBLES[periodo_tpo_label]

    data = _at_descargar_orb(ticker)
    if data is None or data.empty:
        return None, (
            f"No se pudieron descargar velas de 5 minutos para {ticker}. El Market Profile necesita datos "
            f"intradía, que Yahoo Finance no siempre ofrece (típico en ETFs poco líquidos, forex exóticos "
            f"o algunos mercados reales). Probá con otro activo o con otro método."
        )

    # Se pide al menos 3 períodos TPO completos para que el perfil tenga
    # sentido (con menos, el POC/Área de Valor son poco representativos).
    sub_dia, dia_objetivo = _at_seleccionar_sesion(data, min_velas=n_velas_periodo * 3)
    if sub_dia is None:
        return None, (
            "No hay suficientes velas dentro de una misma sesión para armar un Market Profile con este "
            "período de TPO. Probá con un período más corto (ej. 15 Minutos)."
        )

    perfil = _at_construir_market_profile(sub_dia, n_velas_periodo)
    if perfil is None:
        return None, "El rango de precios de la sesión fue cero o inválido; no se pudo armar el perfil."

    poc_info = _at_calcular_poc_y_valor(perfil)
    if poc_info is None:
        return None, "No se pudo calcular el Punto de Control (POC) para esta sesión."

    forma = _at_clasificar_forma_perfil(perfil, poc_info)

    precio_actual = sub_dia["Close"].iloc[-1]
    vah, val = poc_info["vah_precio"], poc_info["val_precio"]

    if precio_actual > vah:
        posicion = "Por encima del Área de Valor"
        sesgo_texto = ("Rechazo del rango si vuelve a entrar, o continuación alcista si mantiene "
                       "cierres por fuera del VAH.")
    elif precio_actual < val:
        posicion = "Por debajo del Área de Valor"
        sesgo_texto = ("Rechazo del rango si vuelve a entrar, o continuación bajista si mantiene "
                       "cierres por fuera del VAL.")
    else:
        posicion = "Dentro del Área de Valor"
        sesgo_texto = "Zona de equilibrio: lo esperable es rotación dentro del área de valor, sin dirección clara."

    senal = f"{forma.split(' (')[0]} — Precio {posicion.lower()}"

    conclusion = (
        f"El perfil de la sesión ({str(dia_objetivo)}) muestra un Punto de Control (POC) en "
        f"${poc_info['poc_precio']:.2f}, con un Área de Valor entre ${val:.2f} (VAL) y ${vah:.2f} (VAH) "
        f"que concentra ~{poc_info['porcentaje_cubierto']:.0f}% del tiempo/actividad de la sesión. "
        f"Se clasifica como {forma.lower()}. {sesgo_texto}"
    )

    resumen = {
        "Método": f"Market Profile / TPO ({periodo_tpo_label})",
        "Señal principal": senal,
        "POC (Punto de Control)": poc_info["poc_precio"],
        "VAH (techo Área de Valor)": vah,
        "VAL (piso Área de Valor)": val,
        "% de la sesión en el Área de Valor": poc_info["porcentaje_cubierto"],
        "Forma del perfil": forma,
        "Sesión analizada": str(dia_objetivo),
        "Conclusión": conclusion,
    }

    contexto_grafico = {"sub_dia": sub_dia, "perfil": perfil, "poc_info": poc_info}
    return resumen, contexto_grafico


# ==============================================================
#  MÉTODO 7: OPENING RANGE BREAKOUT (ORB)
# ==============================================================

def _at_calcular_vwap_sesion(sub_dia):
    """VWAP de la sesión, reiniciado en cada llamada (recibe solo las velas
    de UN día). Precio típico (H+L+C)/3 ponderado por volumen, tal como se
    usa habitualmente en trading intradía."""
    precio_tipico = (sub_dia["High"] + sub_dia["Low"] + sub_dia["Close"]) / 3
    vol_acumulado = sub_dia["Volume"].cumsum()
    return (precio_tipico * sub_dia["Volume"]).cumsum() / vol_acumulado.replace(0, np.nan)


def _at_calcular_rsi(closes, periodo=14):
    """RSI de Wilder estándar."""
    delta = closes.diff()
    ganancia = delta.clip(lower=0)
    perdida = -delta.clip(upper=0)
    avg_gain = ganancia.ewm(alpha=1 / periodo, adjust=False).mean()
    avg_loss = perdida.ewm(alpha=1 / periodo, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _at_calcular_atr(data, periodo=14):
    """ATR de Wilder (misma lógica de True Range que el ADX, sin la parte
    direccional)."""
    high, low, close = data["High"], data["Low"], data["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / periodo, adjust=False).mean()


def _at_clasificar_atr(atr_serie, ventana_promedio=20):
    """Clasifica el ATR actual contra su propio promedio reciente (ventana
    de 20 velas de 5 minutos, ≈ última hora y media de sesión), en vez de un
    umbral fijo — así funciona igual sin importar cuán volátil sea el activo
    de base."""
    if len(atr_serie.dropna()) < 5:
        return "Sin dato suficiente", None
    atr_actual = atr_serie.iloc[-1]
    atr_promedio = atr_serie.tail(ventana_promedio).mean()
    if not atr_promedio or np.isnan(atr_promedio):
        return "Sin dato suficiente", None
    ratio = atr_actual / atr_promedio
    if ratio < 0.8:
        return "Comprimido (volatilidad baja vs. reciente)", ratio
    elif ratio > 1.3:
        return "Expandido (volatilidad alta vs. reciente)", ratio
    else:
        return "Normal", ratio


def _at_analizar_orb(ticker, periodo_orb_label):
    """Arma la caja de apertura (Opening Range) con los primeros minutos de
    la sesión más reciente disponible y evalúa si hubo ruptura del techo
    (LONG) o del piso (SHORT), con VWAP, RSI, ATR y volumen de la vela de
    ruptura contra el volumen histórico promedio de ESE horario puntual
    (una especie de RVOL), no contra el promedio general del día.

    Devuelve (resumen, contexto_grafico) si pudo analizar, o (None, mensaje)
    si no hay datos suficientes."""
    n_velas_caja = ORB_PERIODOS_DISPONIBLES[periodo_orb_label]

    data = _at_descargar_orb(ticker)
    if data is None or data.empty:
        return None, (
            f"No se pudieron descargar velas de 5 minutos para {ticker}. El método ORB necesita datos "
            f"intradía, que Yahoo Finance no siempre ofrece (típico en ETFs poco líquidos, forex exóticos "
            f"o algunos mercados reales). Probá con otro activo o con otro método."
        )

    # Volumen promedio histórico por horario puntual (ej. todas las velas
    # de las 09:35 de los últimos ~60 días), para medir el "volume breakout"
    # de forma realista en vez de comparar solo contra la propia caja.
    vol_promedio_horario = data.groupby(data.index.time)["Volume"].mean()

    # Sesión más reciente que ya tenga al menos la caja completa + 1 vela
    # de confirmación (si la de hoy está en curso y no llegó al mínimo,
    # cae a la última sesión completa).
    sub_dia, dia_objetivo = _at_seleccionar_sesion(data, min_velas=n_velas_caja + 1)
    if sub_dia is None:
        return None, (
            f"No hay suficientes velas dentro de una misma sesión para formar la caja de apertura de "
            f"{periodo_orb_label}. Probá con un período de caja más corto (ej. 5 Minutos)."
        )

    caja = sub_dia.iloc[:n_velas_caja]
    resto = sub_dia.iloc[n_velas_caja:]

    techo_caja, piso_caja = caja["High"].max(), caja["Low"].min()
    apertura = caja["Open"].iloc[0]
    ancho_caja_pct = (techo_caja - piso_caja) / apertura * 100 if apertura else np.nan

    # VWAP, RSI y ATR sobre TODA la sesión (no solo el "resto"), para que
    # el VWAP arranque bien desde la apertura y el ATR tenga contexto previo.
    vwap = _at_calcular_vwap_sesion(sub_dia)
    rsi = _at_calcular_rsi(sub_dia["Close"])
    atr = _at_calcular_atr(sub_dia)
    clasificacion_atr, ratio_atr = _at_clasificar_atr(atr)

    precio_actual = sub_dia["Close"].iloc[-1]
    vwap_actual = vwap.iloc[-1]
    rsi_actual = rsi.iloc[-1]
    vwap_sesgo = "Alcista (precio sobre VWAP)" if precio_actual > vwap_actual else "Bajista (precio bajo VWAP)"

    # Recorremos el resto de la sesión vela por vela llevando el ESTADO
    # ACTUAL (dentro de la caja / LONG / SHORT) en vez de quedarnos solo con
    # la primera ruptura. Esto permite detectar reingresos a la caja (falsa
    # ruptura) y reversiones completas de un lado al otro — algo que pasa
    # seguido en cripto, que no tiene "cierre de sesión" real.
    primer_breakout_tipo, primer_breakout_vela = None, None
    estado_actual, vela_ultimo_cambio, cambios_de_estado = "DENTRO", None, 0

    for _, vela in resto.iterrows():
        if vela["Close"] > techo_caja:
            nuevo_estado = "LONG"
        elif vela["Close"] < piso_caja:
            nuevo_estado = "SHORT"
        else:
            nuevo_estado = "DENTRO"

        if nuevo_estado != estado_actual:
            cambios_de_estado += 1
            if primer_breakout_tipo is None and nuevo_estado in ("LONG", "SHORT"):
                primer_breakout_tipo, primer_breakout_vela = nuevo_estado, vela
            estado_actual, vela_ultimo_cambio = nuevo_estado, vela

    # El volumen de referencia es el de la vela que generó el estado VIGENTE
    # (la última transición), no necesariamente la primera ruptura del día.
    volumen_breakout_pct = None
    vela_para_volumen = vela_ultimo_cambio if vela_ultimo_cambio is not None else primer_breakout_vela
    if vela_para_volumen is not None:
        hora_vela = vela_para_volumen.name.time()
        vol_prom_ese_horario = vol_promedio_horario.get(hora_vela, np.nan)
        if not vol_prom_ese_horario or np.isnan(vol_prom_ese_horario) or vol_prom_ese_horario <= 0:
            # fallback: si no hay suficiente historia por horario, comparar
            # contra el volumen promedio de la propia caja
            vol_mm_caja = caja["Volume"].mean()
            if vol_mm_caja > 0:
                volumen_breakout_pct = (vela_para_volumen["Volume"] / vol_mm_caja - 1) * 100
        else:
            volumen_breakout_pct = (vela_para_volumen["Volume"] / vol_prom_ese_horario - 1) * 100

    lado_texto = {"LONG": "techo", "SHORT": "piso"}

    if primer_breakout_tipo is None:
        # Nunca rompió ningún lado de la caja en toda la sesión.
        senal = "Sin ruptura todavía — Precio dentro de la caja de apertura"
        conclusion = (f"El precio todavía se mueve dentro del rango formado en los primeros "
                      f"{periodo_orb_label.lower()} de la sesión (${piso_caja:.2f} – ${techo_caja:.2f}). "
                      f"Conviene esperar el cierre de una vela por fuera de la caja antes de operar el ORB.")

    elif estado_actual == "DENTRO":
        # Rompió un lado en algún momento, pero volvió a meterse dentro de
        # la caja: ruptura fallida / falsa señal.
        senal = f"Ruptura fallida ({primer_breakout_tipo}) — el precio reingresó a la caja"
        conclusion = (f"El precio llegó a romper el {lado_texto[primer_breakout_tipo]} de la caja "
                      f"(setup {primer_breakout_tipo} inicial), pero volvió a entrar dentro del rango "
                      f"(${piso_caja:.2f} – ${techo_caja:.2f}). Es una falsa ruptura clásica del ORB: conviene "
                      f"esperar una nueva señal en vez de operar la ruptura original.")

    elif estado_actual != primer_breakout_tipo:
        # Reversión completa: rompió para un lado y terminó rompiendo el
        # lado opuesto (por ejemplo: SHORT al principio, LONG ahora).
        senal = f"{estado_actual} — Reversión tras ruptura fallida de {primer_breakout_tipo}"
        conclusion = (f"El precio inicialmente rompió el {lado_texto[primer_breakout_tipo]} de la caja "
                      f"(señal {primer_breakout_tipo}), pero revirtió por completo y ahora está rompiendo el "
                      f"{lado_texto[estado_actual]} opuesto, con señal {estado_actual} vigente. La ruptura "
                      f"{primer_breakout_tipo} original quedó invalidada — lo que importa ahora es el estado actual.")

    else:
        # Mismo lado que la ruptura original, sostenida (puede haber tenido
        # algún reingreso en el medio, pero terminó volviendo a romper del
        # mismo lado).
        nota_extra = (" (tuvo al menos un reingreso a la caja en el medio antes de retomar la ruptura)"
                      if cambios_de_estado > 1 else "")
        senal = f"{estado_actual} — Ruptura de la caja de apertura vigente{nota_extra}"
        nivel_ref = techo_caja if estado_actual == "LONG" else piso_caja
        stop_ref = piso_caja if estado_actual == "LONG" else techo_caja
        direccion = "alcista" if estado_actual == "LONG" else "bajista"
        conclusion = (f"El precio rompió el {lado_texto[estado_actual]} de la caja de apertura (${nivel_ref:.2f}) "
                      f"formada en los primeros {periodo_orb_label.lower()} de la sesión{nota_extra}. Setup "
                      f"clásico de ORB {direccion}: entrada en la ruptura, con ${stop_ref:.2f} (lado opuesto de "
                      f"la caja) como referencia de stop.")

    atr_texto = clasificacion_atr if ratio_atr is None else f"{clasificacion_atr} (x{ratio_atr:.2f} vs. últimas 20 velas)"

    resumen = {
        "Método": f"Opening Range Breakout ({periodo_orb_label})",
        "Señal principal": senal,
        "Rango de la caja (%)": ancho_caja_pct,
        "Techo de la caja": techo_caja,
        "Piso de la caja": piso_caja,
        "Volumen breakout (% vs. promedio histórico del horario)": volumen_breakout_pct,
        "VWAP": vwap_sesgo,
        "RSI(14)": rsi_actual,
        "ATR(14)": atr_texto,
        "Sesión analizada": str(dia_objetivo),
        "Conclusión": conclusion,
    }

    contexto_grafico = {
        "sub_dia": sub_dia, "techo_caja": techo_caja, "piso_caja": piso_caja,
        "vwap": vwap, "n_velas_caja": n_velas_caja,
    }
    return resumen, contexto_grafico


# ==============================================================
#  DISPATCH (métodos Weinstein / O'Neil / Darvas / Wyckoff / CPR — ORB y
#  Market Profile tienen su propio flujo en _at_ejecutar_* porque no
#  comparten pipeline de datos con estos 5)
# ==============================================================

def _at_analizar(metodo, data, benchmark_data=None, timeframe_label=TIMEFRAME_DEFAULT):
    if metodo == "weinstein":
        return _at_analizar_weinstein(data)
    elif metodo == "oneil":
        return _at_analizar_oneil(data, benchmark_data)
    elif metodo == "darvas":
        return _at_analizar_darvas(data, timeframe_label)
    elif metodo == "wyckoff":
        return _at_analizar_wyckoff(data)
    elif metodo == "cpr":
        return _at_analizar_cpr(data)
    raise ValueError("Método no reconocido")


# ==============================================================
#  GRÁFICO (Plotly, mismo estilo oscuro que el resto de la app) —
#  métodos Weinstein / O'Neil / Darvas / Wyckoff
# ==============================================================

def _at_fig_precio(data, lineas_extra, marcadores_extra, titulo):
    paleta = ['#3a7bd5', '#e3b341', '#a371f7', '#39c5cf']
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=data.index, y=data["Close"], mode='lines', name='Precio cierre',
                              line=dict(color='#e6edf3', width=1.6)))
    for i, (etiqueta, serie) in enumerate(lineas_extra):
        fig.add_trace(go.Scatter(x=data.index, y=serie, mode='lines', name=etiqueta,
                                  line=dict(color=paleta[i % len(paleta)], width=1.2, dash='dash')))
    for fecha, precio_marca, tipo in marcadores_extra:
        es_pico = tipo == "pico"
        fig.add_trace(go.Scatter(x=[fecha], y=[precio_marca], mode='markers',
                                  marker=dict(color='#f85149' if es_pico else '#3fb950',
                                              symbol='triangle-down' if es_pico else 'triangle-up', size=12),
                                  name='Techo caja' if es_pico else 'Piso caja', showlegend=True))
    fig.update_layout(
        plot_bgcolor='#0d1117', paper_bgcolor='#07090f', font=dict(color='#b0bcd0', family='Inter, sans-serif'),
        title=dict(text=titulo, font=dict(color='#e6edf3', size=14)),
        xaxis=dict(title='Fecha', gridcolor='#21262d'), yaxis=dict(title='Precio', gridcolor='#21262d'),
        height=460, margin=dict(l=10, r=10, t=45, b=30), legend=dict(orientation='h', y=-0.2),
    )
    return fig


# ==============================================================
#  GRÁFICO — método CPR: sesión en velas de 5 minutos desde la apertura
#  (igual que ORB), con los niveles calculados según la temporalidad
#  seleccionada arriba superpuestos como líneas horizontales. Si el
#  ticker no tiene datos intradía disponibles, cae de nuevo a mostrar la
#  última ventana de velas de la temporalidad elegida.
# ==============================================================

def _at_fig_cpr(data, ticker, resumen, etiqueta_activo, tf_cfg, n_velas_fallback=60):
    """Los NIVELES numéricos (Pivot/TC/BC/R1-R4/S1-S4) siempre salen de
    _at_analizar_cpr, calculados con la temporalidad que el usuario eligió
    arriba — acá solo cambia CÓMO se visualiza el precio: en vez de la
    última ventana de velas de esa temporalidad, se muestra la sesión más
    reciente en velas de 5 minutos desde la apertura, para poder ver con
    detalle cómo se comportó el precio contra esos niveles minuto a
    minuto."""
    data_intradia = _at_descargar_orb(ticker)
    sub_dia, dia_objetivo = _at_seleccionar_sesion(data_intradia, min_velas=1) if data_intradia is not None else (None, None)

    techo, piso, pivot = resumen["TC (techo)"], resumen["BC (piso)"], resumen["Pivot"]
    niveles_lineas = [
        ("R4", resumen["R4"], '#f85149'), ("R3", resumen["R3"], '#f85149'),
        ("R2", resumen["R2"], '#e3b341'), ("R1", resumen["R1"], '#e3b341'),
        ("TC", techo, '#3fb950'), ("Pivot", pivot, '#a371f7'), ("BC", piso, '#3fb950'),
        ("S1", resumen["S1"], '#39c5cf'), ("S2", resumen["S2"], '#39c5cf'),
        ("S3", resumen["S3"], '#e3b341'), ("S4", resumen["S4"], '#e3b341'),
    ]

    fig = go.Figure()

    if sub_dia is not None and not sub_dia.empty:
        # Caso normal: sesión más reciente en velas de 5 minutos, desde
        # la apertura hasta el dato más nuevo disponible.
        fig.add_trace(go.Scatter(x=sub_dia.index, y=sub_dia["Close"], mode='lines', name='Precio cierre',
                                  line=dict(color='#e6edf3', width=1.6)))
        fig.add_shape(type="rect", x0=sub_dia.index[0], x1=sub_dia.index[-1], y0=piso, y1=techo,
                      fillcolor="rgba(58,123,213,0.10)", line=dict(color="#3a7bd5", width=1))
        eje_x_titulo = 'Hora'
        subtitulo = f" — sesión {dia_objetivo} en velas de 5 minutos"
    else:
        # Fallback: ticker sin datos de 5 minutos en Yahoo Finance (pasa
        # con algunos forex/mercados reales) — se muestra la última
        # ventana de velas de la temporalidad seleccionada, como antes.
        sub = data.tail(n_velas_fallback)
        fig.add_trace(go.Scatter(x=sub.index, y=sub["Close"], mode='lines', name='Precio cierre',
                                  line=dict(color='#e6edf3', width=1.6)))
        fig.add_shape(type="rect", x0=sub.index[0], x1=sub.index[-1], y0=piso, y1=techo,
                      fillcolor="rgba(58,123,213,0.10)", line=dict(color="#3a7bd5", width=1))
        eje_x_titulo = 'Fecha'
        subtitulo = " — sin datos intradía de 5 minutos disponibles, se muestra la temporalidad seleccionada"

    for nombre, valor, color in niveles_lineas:
        if valor is None or (isinstance(valor, float) and np.isnan(valor)):
            continue
        fig.add_hline(y=valor, line=dict(color=color, width=1, dash='dash'),
                      annotation_text=nombre, annotation_position='right')

    fig.update_layout(
        plot_bgcolor='#0d1117', paper_bgcolor='#07090f', font=dict(color='#b0bcd0', family='Inter, sans-serif'),
        title=dict(text=f"CPR ({tf_cfg['sufijo_grafico']}){subtitulo} — {etiqueta_activo}",
                   font=dict(color='#e6edf3', size=14)),
        xaxis=dict(title=eje_x_titulo, gridcolor='#21262d'), yaxis=dict(title='Precio', gridcolor='#21262d'),
        height=460, margin=dict(l=10, r=10, t=45, b=30), legend=dict(orientation='h', y=-0.2),
    )
    return fig


# ==============================================================
#  GRÁFICO — método Market Profile (histograma de TPO a la izquierda +
#  precio intradía a la derecha, con POC y Área de Valor superpuestos)
# ==============================================================

def _at_fig_market_profile(contexto, etiqueta_activo, periodo_tpo_label):
    sub_dia = contexto["sub_dia"]
    perfil = contexto["perfil"]
    poc_info = contexto["poc_info"]

    fig = make_subplots(rows=1, cols=2, column_widths=[0.25, 0.75], shared_yaxes=True,
                         horizontal_spacing=0.02)

    fig.add_trace(go.Bar(x=perfil["tpo_por_fila"], y=perfil["precios_fila"], orientation='h',
                          width=perfil["alto_fila"] * 0.9,
                          marker=dict(color='#3a7bd5'), name='TPO por nivel', showlegend=False),
                  row=1, col=1)

    fig.add_trace(go.Scatter(x=sub_dia.index, y=sub_dia["Close"], mode='lines', name='Precio cierre',
                              line=dict(color='#e6edf3', width=1.6)), row=1, col=2)

    fig.add_hline(y=poc_info["poc_precio"], line=dict(color='#e3b341', width=1.5),
                  annotation_text='POC', annotation_position='top left', row=1, col=2)
    fig.add_hrect(y0=poc_info["val_precio"], y1=poc_info["vah_precio"],
                  fillcolor="rgba(63,185,80,0.08)", line=dict(color="#3fb950", width=1), row=1, col=2)

    fig.update_layout(
        plot_bgcolor='#0d1117', paper_bgcolor='#07090f', font=dict(color='#b0bcd0', family='Inter, sans-serif'),
        title=dict(text=f"Market Profile {periodo_tpo_label} — {etiqueta_activo}",
                   font=dict(color='#e6edf3', size=14)),
        height=480, margin=dict(l=10, r=10, t=45, b=30), legend=dict(orientation='h', y=-0.15),
        bargap=0.1, showlegend=True,
    )
    fig.update_xaxes(title_text='TPOs', gridcolor='#21262d', row=1, col=1)
    fig.update_xaxes(title_text='Hora', gridcolor='#21262d', row=1, col=2)
    fig.update_yaxes(title_text='Precio', gridcolor='#21262d', row=1, col=1)
    fig.update_yaxes(gridcolor='#21262d', row=1, col=2)
    return fig


# ==============================================================
#  GRÁFICO — método ORB (velas intradía + caja de apertura + VWAP)
# ==============================================================

def _at_fig_orb(contexto, etiqueta_activo, periodo_orb_label):
    sub_dia = contexto["sub_dia"]
    techo, piso = contexto["techo_caja"], contexto["piso_caja"]
    vwap = contexto["vwap"]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=sub_dia.index, y=sub_dia["Close"], mode='lines', name='Precio cierre',
                              line=dict(color='#e6edf3', width=1.6)))
    fig.add_trace(go.Scatter(x=sub_dia.index, y=vwap, mode='lines', name='VWAP',
                              line=dict(color='#e3b341', width=1.2, dash='dot')))

    fig.add_shape(type="rect", x0=sub_dia.index[0], x1=sub_dia.index[-1], y0=piso, y1=techo,
                  fillcolor="rgba(58,123,213,0.10)", line=dict(color="#3a7bd5", width=1))
    fig.add_hline(y=techo, line=dict(color='#3fb950', width=1, dash='dash'),
                  annotation_text='Techo caja', annotation_position='top left')
    fig.add_hline(y=piso, line=dict(color='#f85149', width=1, dash='dash'),
                  annotation_text='Piso caja', annotation_position='bottom left')

    fig.update_layout(
        plot_bgcolor='#0d1117', paper_bgcolor='#07090f', font=dict(color='#b0bcd0', family='Inter, sans-serif'),
        title=dict(text=f"ORB {periodo_orb_label} — {etiqueta_activo}", font=dict(color='#e6edf3', size=14)),
        xaxis=dict(title='Hora', gridcolor='#21262d'), yaxis=dict(title='Precio', gridcolor='#21262d'),
        height=460, margin=dict(l=10, r=10, t=45, b=30), legend=dict(orientation='h', y=-0.2),
    )
    return fig


# ==============================================================
#  TARJETA DE RESUMEN (mismo lenguaje visual que el resto de la app,
#  compartida por los 7 métodos)
# ==============================================================

def _at_tarjeta_resumen(resumen):
    detalle = resumen.get("Detalle")
    lineas_check = ''
    if isinstance(detalle, dict):
        lineas_check = ''.join(
            f'<div style="font-size:11px;color:{"#3fb950" if cumple else "#f85149"};padding:2px 0">'
            f'{"✅" if cumple else "❌"} {cond}</div>'
            for cond, cumple in detalle.items()
        )

    metricas = []
    for k, v in resumen.items():
        if k in ("Método", "Señal principal", "Detalle", "Conclusión", "Descripción"):
            continue
        if v is None:
            continue
        if isinstance(v, float) and np.isnan(v):
            continue
        val_fmt = f"{v:,.2f}" if isinstance(v, float) else str(v)
        metricas.append(f'<span style="display:inline-block;background:#0d1117;border:1px solid #21262d;'
                         f'border-radius:6px;padding:4px 10px;margin:3px 6px 3px 0;font-size:11px;'
                         f'color:#e6edf3;font-family:JetBrains Mono,monospace">{k}: {val_fmt}</span>')

    descripcion_html = f'<div style="font-size:12px;color:#8b949e;margin:8px 0">{resumen["Descripción"]}</div>' \
        if resumen.get("Descripción") else ''
    criterios_html = f'<div style="font-size:12px;color:#6b7d9a;margin:4px 0 8px 0">' \
                     f'Criterios cumplidos: <b style="color:#e6edf3">{resumen["Criterios cumplidos"]}</b></div>' \
        if resumen.get("Criterios cumplidos") else ''

    st.markdown(f"""
    <div style="background:#0d1117;border:1px solid #21262d;border-left:3px solid #6CC24A;
         border-radius:8px;padding:16px 20px;margin-bottom:14px">
      <div style="color:#6b7d9a;font-size:11px;text-transform:uppercase;letter-spacing:0.5px">{resumen['Método']}</div>
      <div style="color:#e6edf3;font-size:16px;font-weight:700;margin:4px 0 8px 0">{resumen['Señal principal']}</div>
      {descripcion_html}
      {criterios_html}
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:2px 16px;margin-bottom:8px">{lineas_check}</div>
      <div>{''.join(metricas)}</div>
      <div style="margin-top:12px;padding-top:12px;border-top:1px solid #21262d;font-size:13px;color:#f5f7fa">
        <b style="color:#6CC24A">Conclusión:</b> {resumen['Conclusión']}
      </div>
    </div>
    """, unsafe_allow_html=True)


# ==============================================================
#  FLUJO COMPLETO DEL MÉTODO ORB (datos, métricas, tarjeta, gráfico)
#  Separado del resto porque no comparte pipeline (MM/ADX/benchmark)
#  con Weinstein/O'Neil/Darvas/Wyckoff/CPR.
# ==============================================================

def _at_ejecutar_orb(ticker, etiqueta_activo, periodo_orb_label, PLOTLY_CONFIG):
    with st.spinner(f'Descargando velas de 5 minutos de {ticker}...'):
        resumen, extra = _at_analizar_orb(ticker, periodo_orb_label)

    if resumen is None:
        st.error(extra)
        return

    contexto = extra
    sub_dia = contexto["sub_dia"]

    cols = st.columns(4)
    with cols[0]:
        st.metric('Último cierre', f"${sub_dia['Close'].iloc[-1]:,.2f}")
    with cols[1]:
        rsi_val = resumen['RSI(14)']
        st.metric('RSI(14)', f"{rsi_val:.1f}" if not np.isnan(rsi_val) else "s/d")
    with cols[2]:
        st.metric('Caja de apertura', periodo_orb_label)
    with cols[3]:
        st.metric('Sesión analizada', resumen['Sesión analizada'])

    tab_resumen, tab_grafico = st.tabs(['🧾 Resumen y señal', '📈 Gráfico'])

    with tab_resumen:
        _at_tarjeta_resumen(resumen)

    with tab_grafico:
        fig = _at_fig_orb(contexto, etiqueta_activo, periodo_orb_label)
        st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)


# ==============================================================
#  FLUJO COMPLETO DEL MÉTODO MARKET PROFILE (datos, métricas, tarjeta,
#  gráfico). Separado del resto porque no comparte pipeline con los
#  otros 5 métodos ni con ORB (aunque reutiliza la misma descarga de
#  velas de 5 minutos).
# ==============================================================

def _at_ejecutar_market_profile(ticker, etiqueta_activo, periodo_tpo_label, PLOTLY_CONFIG):
    with st.spinner(f'Descargando velas de 5 minutos de {ticker}...'):
        resumen, extra = _at_analizar_market_profile(ticker, periodo_tpo_label)

    if resumen is None:
        st.error(extra)
        return

    contexto = extra
    sub_dia = contexto["sub_dia"]

    cols = st.columns(4)
    with cols[0]:
        st.metric('Último cierre', f"${sub_dia['Close'].iloc[-1]:,.2f}")
    with cols[1]:
        st.metric('POC', f"${resumen['POC (Punto de Control)']:,.2f}")
    with cols[2]:
        st.metric('Período TPO', periodo_tpo_label)
    with cols[3]:
        st.metric('Sesión analizada', resumen['Sesión analizada'])

    tab_resumen, tab_grafico = st.tabs(['🧾 Resumen y señal', '📈 Gráfico'])

    with tab_resumen:
        _at_tarjeta_resumen(resumen)

    with tab_grafico:
        fig = _at_fig_market_profile(contexto, etiqueta_activo, periodo_tpo_label)
        st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)


# ==============================================================
#  ENTRY POINT — llamar esto desde el archivo principal
#  (reemplaza a modulo_sector_rotation / modulo_commodities_rotation /
#   modulo_cripto_rotation / modulo_indices_rotation)
#
#  Sin Supabase: no recibe supabase/user_id y no persiste nada.
# ==============================================================

def modulo_analisis_tecnico(PLOTLY_CONFIG=None, benchmark=BENCHMARK_DEFAULT):
    """Análisis técnico de un activo con 7 métodos: Stan Weinstein,
    William O'Neil, Darvas Box, Wyckoff, CPR, Market Profile (TPO) y ORB
    (Opening Range Breakout).

    Los primeros 5 (Weinstein, O'Neil, Darvas, Wyckoff, CPR) operan sobre
    la temporalidad que elijas (1 Día, 4 Horas, 1 Hora, 45/30/15/5
    Minutos). Market Profile y ORB trabajan por SESIÓN, con su propio
    selector de período (TPO / caja de apertura) en vez del selector de
    temporalidad genérico, y comparten la misma descarga de velas de 5
    minutos.

    El ADX de Wilder se calcula siempre como filtro/dato transversal en
    los primeros 5 métodos. El activo se elige desde las categorías de tu
    configuración (acciones por industria, forex, índices/países, ETFs de
    índice, ETFs de sector/subsector, mercados reales) o como ticker
    manual. No se guarda ningún historial."""

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1420 0%,#0a1c30 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #6CC24A;
         border-radius:14px; padding:26px 30px; margin-bottom:22px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">📐 Análisis Técnico</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Analizá cualquier activo de tu universo con 7 métodos técnicos: <b style="color:#e6edf3">Stan
        Weinstein</b> (fases de mercado), <b style="color:#e6edf3">William O'Neil</b> (CANSLIM técnico /
        fuerza relativa), <b style="color:#e6edf3">Darvas Box</b> (cajas de consolidación + breakout),
        <b style="color:#e6edf3">Wyckoff</b> (acumulación/distribución), <b style="color:#e6edf3">CPR</b>
        (Central Pivot Range + R1-R4/S1-S4), <b style="color:#e6edf3">Market Profile</b> (POC + Área de Valor)
        y <b style="color:#e6edf3">ORB</b> (Opening Range Breakout intradía). Los primeros 5 operan en la
        temporalidad que elijas: <b style="color:#e6edf3">1 Día</b>, <b style="color:#e6edf3">4 Horas</b>,
        <b style="color:#e6edf3">1 Hora</b>, <b style="color:#e6edf3">45 Minutos</b>,
        <b style="color:#e6edf3">30 Minutos</b>, <b style="color:#e6edf3">15 Minutos</b> o
        <b style="color:#e6edf3">5 Minutos</b>; Market Profile y ORB arman su propio período por sesión.
        Este análisis no se guarda: vive solo en la sesión actual.
      </div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([2, 2, 1.3])

    with col2:
        metodo_label = st.selectbox('Método de análisis', list(METODOS_DISPONIBLES.keys()), key='at_metodo')
    metodo = METODOS_DISPONIBLES[metodo_label]

    with col1:
        ticker, etiqueta_activo = _at_seleccionar_ticker()

    with col3:
        if metodo == "orb":
            periodo_orb_label = _at_seleccionar_periodo_orb()
            timeframe_label, periodo_tpo_label = None, None
        elif metodo == "market_profile":
            periodo_tpo_label = _at_seleccionar_periodo_market_profile()
            timeframe_label, periodo_orb_label = None, None
        else:
            timeframe_label = _at_seleccionar_timeframe()
            periodo_orb_label, periodo_tpo_label = None, None

    if not ticker:
        st.info('Seleccioná o ingresá un activo para analizar.')
        return

    # ---- Flujo ORB: pipeline propio, se corta acá ----
    if metodo == "orb":
        _at_ejecutar_orb(ticker, etiqueta_activo, periodo_orb_label, PLOTLY_CONFIG)
        return

    # ---- Flujo Market Profile: pipeline propio, se corta acá ----
    if metodo == "market_profile":
        _at_ejecutar_market_profile(ticker, etiqueta_activo, periodo_tpo_label, PLOTLY_CONFIG)
        return

    # ---- Flujo Weinstein / O'Neil / Darvas / Wyckoff / CPR ----
    tf_cfg = TIMEFRAMES_DISPONIBLES[timeframe_label]

    with st.spinner(f'Descargando datos de {ticker} ({timeframe_label})...'):
        data = _at_obtener_datos(ticker, timeframe_label)

    if data is None or data.empty:
        st.error(f'No se pudieron descargar datos para {ticker} en temporalidad {timeframe_label}. '
                 f'Verificá el ticker (algunos activos no tienen datos intradiarios en Yahoo Finance).')
        return
    if len(data) < 60:
        st.error(f'{ticker} tiene muy poca historia en {timeframe_label} ({len(data)} velas) '
                 f'para un análisis técnico confiable.')
        return
    if len(data) < 210:
        st.warning(f'⚠️ {ticker} tiene solo {len(data)} velas de historial en {timeframe_label}. Los criterios '
                   f'que usan MM150/MM200 pueden no ser confiables (activo joven / poca historia / la '
                   f'temporalidad intradiaria tiene menos velas disponibles que la diaria).')

    data = _at_agregar_medias(data)
    data["+DI"], data["-DI"], data["ADX"] = _at_calcular_adx(data)

    benchmark_data = None
    if metodo == 'oneil':
        with st.spinner('Descargando benchmark de mercado...'):
            benchmark_data = _at_obtener_datos(benchmark, timeframe_label)
        if benchmark_data is None:
            st.info('No se pudo descargar el benchmark — el RS Rating no estará disponible para este análisis.')

    resumen, lineas_extra, marcadores_extra = _at_analizar(metodo, data, benchmark_data, timeframe_label)

    cols = st.columns(4)
    with cols[0]:
        st.metric('Último cierre', f"${data['Close'].iloc[-1]:,.2f}")
    with cols[1]:
        st.metric('ADX(14)', f"{data['ADX'].iloc[-1]:.1f}")
    with cols[2]:
        st.metric('Temporalidad', timeframe_label)
    with cols[3]:
        fmt_fecha = '%Y-%m-%d %H:%M' if tf_cfg["resample"] or tf_cfg["yf_interval"] != "1d" else '%Y-%m-%d'
        st.metric('Fecha del dato', data.index[-1].strftime(fmt_fecha))

    tab_resumen, tab_grafico = st.tabs(['🧾 Resumen y señal', '📈 Gráfico'])

    with tab_resumen:
        _at_tarjeta_resumen(resumen)

    with tab_grafico:
        if metodo == "cpr":
            fig = _at_fig_cpr(data, ticker, resumen, etiqueta_activo, tf_cfg)
        else:
            titulo = f"{resumen['Método']} — {etiqueta_activo} ({tf_cfg['sufijo_grafico']})"
            fig = _at_fig_precio(data, lineas_extra, marcadores_extra, titulo)
        st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
