# ==============================================================
#  MÓDULO ANÁLISIS TÉCNICO — Weinstein / O'Neil / Darvas Box / Wyckoff
#  Reemplaza al módulo de Rotación (Sector/Commodities/Cripto/Índices).
#
#  Diferencia clave: acá NO hay un universo fijo de activos ni ranking
#  entre varios — el usuario elige el activo desde las categorías ya
#  definidas en tu archivo de configuración (acciones por industria,
#  forex, índices/países, ETFs de sector/subsector, mercados reales),
#  o tipea cualquier ticker manual soportado por Yahoo Finance.
#  El ADX de Wilder se calcula siempre como dato/filtro transversal
#  (se usa fuerte dentro de O'Neil).
#
#  NUEVO: selector de temporalidad (1 Hora / 4 Horas / 1 Día).
#  Yahoo Finance no tiene intervalo nativo de 4H, así que para esa
#  opción se descargan velas de 1H y se resamplean a 4H con pandas.
#  El intervalo de 60m tiene un límite de histórico de Yahoo de ~730
#  días, así que se pide el máximo permitido para esa temporalidad.
#
#  Sin persistencia: no se guarda nada en Supabase. Cada análisis
#  vive solo en la sesión actual.
# ==============================================================

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from datetime import datetime
from zoneinfo import ZoneInfo

# Diccionarios de activos (industrias, forex, países, ETFs, mercados reales).
# Deben vivir en un módulo aparte para evitar import circular con app.py.
from config_activos import (
    ACCIONES_POR_INDUSTRIA,
    FOREX,
    PAISES,
    ETFS,
    SECTORES_TOTAL,
    MERCADOS_REALES,
)

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
}

# ----------------------------------------------------------------
#  Temporalidades disponibles.
#  yf_interval / yf_periodo: lo que se le pide a Yahoo Finance.
#  resample: si no es None, se descarga yf_interval y se agrupa a esa
#            regla de pandas (ej. "4h", "45min") porque Yahoo no la
#            ofrece nativa.
#  min_velas / min_velas_mm_largas: umbrales de historial mínimo,
#            iguales en cantidad de barras para las 3 temporalidades
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
}
TIMEFRAME_DEFAULT = "1 Día"


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
#  SELECTOR DE TEMPORALIDAD
# ==============================================================

def _at_seleccionar_timeframe():
    """Devuelve la etiqueta de temporalidad elegida (clave de TIMEFRAMES_DISPONIBLES)."""
    return st.selectbox(
        'Temporalidad',
        list(TIMEFRAMES_DISPONIBLES.keys()),
        index=list(TIMEFRAMES_DISPONIBLES.keys()).index(TIMEFRAME_DEFAULT),
        key='at_timeframe',
    )


# ==============================================================
#  DESCARGA DE DATOS
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
#  ADX DE WILDER (filtro de tendencia, uso transversal)
# ==============================================================

def _at_calcular_adx(data, periodo=14):
    """ADX (Average Directional Index) de Welles Wilder. Filtro objetivo de
    '¿hay tendencia establecida o no?', reutilizado dentro de O'Neil y como
    dato informativo en Weinstein/Darvas/Wyckoff. ADX >= 25 = umbral clásico
    de tendencia establecida. El período (14 barras) se mantiene fijo sin
    importar la temporalidad, tal como se usa habitualmente en cualquier
    gráfico (14 velas de 1H, de 4H o diarias)."""
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


def _at_analizar_darvas(data):
    resultado = _at_detectar_darvas_box(data)
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
    `ventana` está en cantidad de velas, igual en las 3 temporalidades."""
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
#  DISPATCH
# ==============================================================

def _at_analizar(metodo, data, benchmark_data=None):
    if metodo == "weinstein":
        return _at_analizar_weinstein(data)
    elif metodo == "oneil":
        return _at_analizar_oneil(data, benchmark_data)
    elif metodo == "darvas":
        return _at_analizar_darvas(data)
    elif metodo == "wyckoff":
        return _at_analizar_wyckoff(data)
    raise ValueError("Método no reconocido")


# ==============================================================
#  GRÁFICO (Plotly, mismo estilo oscuro que el resto de la app)
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
#  TARJETA DE RESUMEN (mismo lenguaje visual que el resto de la app)
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
#  ENTRY POINT — llamar esto desde el archivo principal
#  (reemplaza a modulo_sector_rotation / modulo_commodities_rotation /
#   modulo_cripto_rotation / modulo_indices_rotation)
#
#  Sin Supabase: no recibe supabase/user_id y no persiste nada.
# ==============================================================

def modulo_analisis_tecnico(PLOTLY_CONFIG=None, benchmark=BENCHMARK_DEFAULT):
    """Análisis técnico de un activo con 4 métodos clásicos: Stan Weinstein,
    William O'Neil, Darvas Box y Wyckoff, en 5 temporalidades: 1 Día,
    4 Horas, 1 Hora, 45 Minutos y 30 Minutos. El ADX de Wilder se calcula
    siempre como filtro/dato transversal. El activo se elige desde las
    categorías de tu configuración (acciones por industria, forex,
    índices/países, ETFs de índice, ETFs de sector/subsector, mercados
    reales) o como ticker manual. No se guarda ningún historial."""

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1420 0%,#0a1c30 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #6CC24A;
         border-radius:14px; padding:26px 30px; margin-bottom:22px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">📐 Análisis Técnico</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Analizá cualquier activo de tu universo con 4 métodos técnicos clásicos:
        <b style="color:#e6edf3">Stan Weinstein</b> (fases de mercado), <b style="color:#e6edf3">William O'Neil</b>
        (CANSLIM técnico / fuerza relativa), <b style="color:#e6edf3">Darvas Box</b> (cajas de consolidación +
        breakout) y <b style="color:#e6edf3">Wyckoff</b> (acumulación/distribución), en la temporalidad que elijas:
        <b style="color:#e6edf3">1 Día</b>, <b style="color:#e6edf3">4 Horas</b>, <b style="color:#e6edf3">1 Hora</b>,
        <b style="color:#e6edf3">45 Minutos</b> o <b style="color:#e6edf3">30 Minutos</b>.
        El ADX de Wilder se calcula siempre como filtro de tendencia. Este análisis no se guarda: vive solo en
        la sesión actual.
      </div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([2, 2, 1.3])
    with col1:
        ticker, etiqueta_activo = _at_seleccionar_ticker()
    with col2:
        metodo_label = st.selectbox('Método de análisis', list(METODOS_DISPONIBLES.keys()), key='at_metodo')
    with col3:
        timeframe_label = _at_seleccionar_timeframe()
    metodo = METODOS_DISPONIBLES[metodo_label]
    tf_cfg = TIMEFRAMES_DISPONIBLES[timeframe_label]

    if not ticker:
        st.info('Seleccioná o ingresá un activo para analizar.')
        return

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

    resumen, lineas_extra, marcadores_extra = _at_analizar(metodo, data, benchmark_data)

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
        titulo = f"{resumen['Método']} — {etiqueta_activo} ({tf_cfg['sufijo_grafico']})"
        fig = _at_fig_precio(data, lineas_extra, marcadores_extra, titulo)
        st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
