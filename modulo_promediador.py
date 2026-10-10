# ==============================================================
#  MÓDULO PROMEDIADOR — v3.1 (multi-mercado + multi-plataforma)
#  Calcula precio promedio, tamaño de posición según tu riesgo,
#  tendencia y stop loss/apalancamiento — todo explicado en criollo.
#
#  NOVEDADES v3.1:
#  - Selector de PLATAFORMA: "Exchange · unidades" o "Broker · lotes".
#    Cualquier activo (cripto, acciones, forex, commodities) se puede
#    operar de las dos formas:
#        Exchange · unidades : cantidad en unidades/tokens + apalancamiento
#        Broker · lotes      : cantidad en lotes + apalancamiento
#  - El tamaño de lote (unidades por lote) es editable cuando operás en
#    lotes, porque cada bróker define el suyo.
#  - Nueva tarjeta "Ganancia estimada (Take Profit)" en los resultados.
#  - Modo Exchange: se carga "Capital para la operación" y el apalancamiento,
#    y la cantidad se calcula sola. Avisa si ese capital te hace pasar del
#    % de riesgo deseado y sugiere el capital máximo para respetarlo.
#
#  v3 (se mantiene):
#  - Decimales automáticos según el mercado y el ticker.
#        Acciones / CEDEARs : cantidad 0 dec · precio 2 dec
#        Cripto (BTC, ETH…) : cantidad 6 dec · precio 2 dec
#                             (si el precio es < 1 sube solo a 4/6/10 dec
#                              para no truncar altcoins baratas)
#        Forex              : precio 5 dec (3 en JPY)
#        Commodities        : precio 2 dec
#        En lotes           : cantidad 2 dec
#  - Selector de mercado: Cripto / Acciones · Forex · Commodities.
#  - Internamente todo se convierte a unidades (1 lote Forex = 100.000 ·
#    1 lote Oro = 100 oz · etc.) para que margen, exposición, pérdida y
#    liquidación salgan bien.
#  - Stop Loss con 3 modos: Manual · Por ATR · % Fijo (-2% / -3% / -5%).
#  - Botón "⚡ Usar recomendado" pegado al campo de cantidad (un clic).
#  - Semáforo coherente: sobre-riesgo = naranja/rojo; verde solo si la
#    pérdida en el stop entra dentro del riesgo permitido.
#  - Layout fijo en 2 columnas: izquierda = inputs, derecha = resultados.
# ==============================================================
"""
Se integra al Analizador Cuantitativo Unificado como un módulo más.

IMPORTANTE — evita import circular:
Este archivo NO importa nada de tu app principal. Tu app principal le
PASA sus propias funciones (analizar_largo, descargar_datos,
get_close_series, calcular_atr, scores_corto, señal_accion_corto)
como argumentos.

Uso en tu archivo principal:

    from modulo_promediador import modulo_promediador
    ...
    elif MODULO == 'promediador':
        modulo_promediador(
            analizar_largo=analizar_largo,
            descargar_datos=descargar_datos,
            get_close_series=get_close_series,
            calcular_atr=calcular_atr,
            scores_corto=scores_corto,
            señal_accion_corto=señal_accion_corto,
        )
"""

import math
import time

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

try:
    import yfinance as yf
except ImportError:
    yf = None


# ==============================================================
#  1) MATEMÁTICA PURA (sin Streamlit — se puede testear sola)
#     Todas las cantidades de esta sección están en UNIDADES
#     (nunca en lotes): la conversión lote→unidades se hace afuera.
# ==============================================================

def calcular_promedio(cant_actual, precio_prom_actual, cant_nueva, precio_nuevo):
    """Nuevo precio promedio después de comprar o vender parte de una posición."""
    if cant_actual < 0:
        raise ValueError("La cantidad actual no puede ser negativa.")
    if cant_nueva == 0:
        raise ValueError("La cantidad de la operación no puede ser 0.")
    if precio_nuevo <= 0:
        raise ValueError("El precio debe ser mayor a 0.")

    invertido_actual = cant_actual * precio_prom_actual
    monto_operacion = cant_nueva * precio_nuevo
    cant_final = cant_actual + cant_nueva

    if cant_final <= 0:
        return dict(
            cantidad_final=max(cant_final, 0), precio_promedio_final=0.0,
            invertido_total=0.0, monto_operacion=monto_operacion,
            variacion_precio_prom_pct=None, venta_excede_posicion=cant_final < 0,
        )

    invertido_total = invertido_actual + monto_operacion
    precio_prom_final = invertido_total / cant_final
    var_pct = (
        (precio_prom_final - precio_prom_actual) / precio_prom_actual * 100
        if precio_prom_actual > 0 else 0.0
    )
    return dict(
        cantidad_final=cant_final, precio_promedio_final=precio_prom_final,
        invertido_total=invertido_total, monto_operacion=monto_operacion,
        variacion_precio_prom_pct=var_pct, venta_excede_posicion=False,
    )


def sugerir_stop_atr(precio_entrada, atr, direccion='long', multiplo=1.5):
    """Stop sugerido según la volatilidad real del activo (ATR), no un % fijo al voleo."""
    if not atr or atr <= 0 or not precio_entrada:
        return None
    if direccion == 'long':
        return round(precio_entrada - multiplo * atr, 10)
    return round(precio_entrada + multiplo * atr, 10)


def sugerir_stop_pct(precio_entrada, pct, direccion='long'):
    """Stop a un % fijo del precio de entrada (long: por debajo · short: por encima)."""
    if not precio_entrada or precio_entrada <= 0 or not pct or pct <= 0:
        return None
    if direccion == 'long':
        return precio_entrada * (1 - pct / 100)
    return precio_entrada * (1 + pct / 100)


def calcular_tamano_posicion(capital, pct_riesgo, precio_entrada, precio_stop, apalancamiento=1.0):
    """
    LA CUENTA MÁS IMPORTANTE DE TODAS: cuánto podés comprar sin romper tu regla de riesgo.
    Fórmula: (capital × % que estás dispuesto a perder) / (distancia en $ hasta el stop).
    Devuelve la cantidad en UNIDADES.
    """
    if capital <= 0 or pct_riesgo <= 0 or precio_entrada <= 0 or precio_stop <= 0:
        return None
    distancia = abs(precio_entrada - precio_stop)
    if distancia <= 0:
        return None
    dinero_a_arriesgar = capital * pct_riesgo / 100
    cantidad_sugerida = dinero_a_arriesgar / distancia
    exposicion_sugerida = cantidad_sugerida * precio_entrada
    margen_sugerido = exposicion_sugerida / apalancamiento if apalancamiento else exposicion_sugerida
    return dict(
        dinero_a_arriesgar=dinero_a_arriesgar, cantidad_sugerida=cantidad_sugerida,
        exposicion_sugerida=exposicion_sugerida, margen_sugerido=margen_sugerido,
    )


def cantidad_recomendada_unidades(capital, pct_riesgo, direccion, precio_entrada, precio_stop,
                                   cant_actual=0.0, precio_prom_actual=0.0):
    """
    Cantidad (en unidades) que se puede AGREGAR sin superar el riesgo permitido.
    Si ya hay posición, primero se descuenta del presupuesto de riesgo lo que ya
    se perdería en esa posición si salta el stop.
    Devuelve None si faltan datos o el stop está del lado equivocado.
    """
    if capital <= 0 or pct_riesgo <= 0 or precio_entrada <= 0 or precio_stop <= 0:
        return None
    if direccion == 'long' and precio_stop >= precio_entrada:
        return None
    if direccion == 'short' and precio_stop <= precio_entrada:
        return None
    presupuesto = capital * pct_riesgo / 100
    if cant_actual > 0 and precio_prom_actual > 0:
        perdida_existente = (
            (precio_prom_actual - precio_stop) * cant_actual if direccion == 'long'
            else (precio_stop - precio_prom_actual) * cant_actual
        )
        presupuesto -= perdida_existente
    if presupuesto <= 0:
        return 0.0
    return presupuesto / abs(precio_entrada - precio_stop)


def calcular_stop_loss(precio_entrada, precio_stop, cantidad, apalancamiento=1.0,
                        direccion='long', capital_cuenta=None, precio_take_profit=None,
                        atr=None):
    """Pérdida si se toca el stop, precio de liquidación aproximado y ratio riesgo/beneficio."""
    if precio_entrada <= 0 or precio_stop <= 0 or cantidad <= 0:
        raise ValueError("Precio de entrada, stop y cantidad deben ser mayores a 0.")
    if apalancamiento < 1:
        raise ValueError("El apalancamiento mínimo es 1x (sin apalancar).")
    direccion = direccion.lower()
    if direccion not in ('long', 'short'):
        raise ValueError("La dirección debe ser 'long' o 'short'.")
    if direccion == 'long' and precio_stop >= precio_entrada:
        raise ValueError("En una posición LONG el stop loss debe estar por DEBAJO del precio de entrada.")
    if direccion == 'short' and precio_stop <= precio_entrada:
        raise ValueError("En una posición SHORT el stop loss debe estar por ENCIMA del precio de entrada.")

    distancia_stop_pct = abs(precio_stop - precio_entrada) / precio_entrada * 100
    exposicion_total = precio_entrada * cantidad
    capital_propio = exposicion_total / apalancamiento
    perdida_dinero = abs(precio_entrada - precio_stop) * cantidad
    perdida_pct_capital = (perdida_dinero / capital_propio * 100) if capital_propio > 0 else None
    perdida_pct_cuenta = (
        perdida_dinero / capital_cuenta * 100 if capital_cuenta and capital_cuenta > 0 else None
    )

    if direccion == 'long':
        precio_liquidacion = precio_entrada * (1 - 1 / apalancamiento)
    else:
        precio_liquidacion = precio_entrada * (1 + 1 / apalancamiento)
    distancia_liquidacion_pct = abs(precio_liquidacion - precio_entrada) / precio_entrada * 100
    stop_antes_de_liquidar = (
        precio_stop > precio_liquidacion if direccion == 'long' else precio_stop < precio_liquidacion
    )

    rr_ratio = None
    ganancia_potencial = None
    if precio_take_profit:
        ganancia_potencial = (
            (precio_take_profit - precio_entrada) * cantidad if direccion == 'long'
            else (precio_entrada - precio_take_profit) * cantidad
        )
        if perdida_dinero > 0:
            rr_ratio = ganancia_potencial / perdida_dinero

    distancia_stop_en_atr = abs(precio_entrada - precio_stop) / atr if atr and atr > 0 else None

    return dict(
        direccion=direccion, precio_entrada=precio_entrada, precio_stop=precio_stop,
        cantidad=cantidad, apalancamiento=apalancamiento,
        distancia_stop_pct=distancia_stop_pct, exposicion_total=exposicion_total,
        capital_propio=capital_propio, perdida_dinero=perdida_dinero,
        perdida_pct_capital=perdida_pct_capital, perdida_pct_cuenta=perdida_pct_cuenta,
        precio_liquidacion=precio_liquidacion, distancia_liquidacion_pct=distancia_liquidacion_pct,
        stop_antes_de_liquidar=stop_antes_de_liquidar, rr_ratio=rr_ratio,
        ganancia_potencial=ganancia_potencial, distancia_stop_en_atr=distancia_stop_en_atr,
    )


# Techo absoluto de sensatez: por más que el usuario "acepte" perder más que
# esto de TODA la cuenta en una sola operación, siempre se marca como ALTO.
PERDIDA_PCT_CUENTA_ALTO_ABSOLUTO = 15.0


def evaluar_riesgo_stop(stop_info, horizonte='largo', pct_riesgo_max_cuenta=2.0):
    """Traduce los números del stop-loss a avisos en criollo + nivel de riesgo (OK/MEDIO/ALTO)."""
    avisos, nivel = [], 'OK'

    if stop_info['perdida_pct_cuenta'] is not None:
        perdida_pct_cuenta = stop_info['perdida_pct_cuenta']
        if perdida_pct_cuenta > PERDIDA_PCT_CUENTA_ALTO_ABSOLUTO:
            nivel = 'ALTO'
            avisos.append(f"🚨 Si te toca el stop, perdés {perdida_pct_cuenta:.1f}% de TODA tu cuenta. "
                           f"Sin importar qué % de riesgo hayas definido vos, esto es una pérdida enorme "
                           f"para una sola operación — casi nadie se recupera de perder esta proporción "
                           f"de su capital de una vez.")
        elif perdida_pct_cuenta > pct_riesgo_max_cuenta * 2:
            nivel = 'ALTO'
            avisos.append(f"Si te toca el stop, perdés {perdida_pct_cuenta:.1f}% de TODA tu cuenta "
                           f"— muy por encima del {pct_riesgo_max_cuenta:.0f}% que dijiste que ibas a arriesgar. "
                           f"La posición es demasiado grande para tu capital.")
        elif perdida_pct_cuenta > pct_riesgo_max_cuenta * 1.0001:
            nivel = 'MEDIO' if nivel == 'OK' else nivel
            avisos.append(f"Si te toca el stop, perdés {perdida_pct_cuenta:.1f}% de tu cuenta, "
                           f"un poco por encima del {pct_riesgo_max_cuenta:.0f}% que te propusiste.")
        else:
            avisos.append(f"Si te toca el stop, perdés {perdida_pct_cuenta:.1f}% de tu cuenta — "
                           f"dentro de lo que dijiste que estabas dispuesto a arriesgar. ✅")

    if not stop_info['stop_antes_de_liquidar']:
        nivel = 'ALTO'
        avisos.append('⚠️ Con este apalancamiento, el precio de liquidación llega ANTES que tu stop — '
                       'el bróker/exchange te cerraría la posición por la fuerza antes de que tu stop actúe.')
    elif (stop_info['distancia_liquidacion_pct'] - stop_info['distancia_stop_pct']) < 2:
        nivel = 'ALTO' if nivel == 'OK' else nivel
        avisos.append('Tu stop está muy cerca del precio de liquidación: casi no hay margen para un '
                       'movimiento brusco o un pequeño desfasaje de precio.')

    if stop_info['distancia_stop_en_atr'] is not None:
        multiplo_min = 1.0 if horizonte == 'corto' else 1.5
        if stop_info['distancia_stop_en_atr'] < multiplo_min:
            avisos.append(f"El stop está muy pegado al precio (a solo {stop_info['distancia_stop_en_atr']:.2f} "
                           f"veces la volatilidad normal del activo): puede saltar por un vaivén normal, "
                           f"sin que la tendencia realmente haya cambiado.")

    if stop_info['rr_ratio'] is not None:
        if stop_info['rr_ratio'] < 1:
            nivel = 'ALTO' if nivel == 'OK' else nivel
            avisos.append(f"Por cada $1 que arriesgás, tu objetivo de ganancia es de solo ${stop_info['rr_ratio']:.2f}. "
                           f"Estás arriesgando más de lo que buscás ganar.")
        elif stop_info['rr_ratio'] < 1.5:
            avisos.append(f"Por cada $1 que arriesgás, buscás ganar ${stop_info['rr_ratio']:.2f}. Aceptable, "
                           f"aunque lo ideal es apuntar a $2 o más por cada $1 arriesgado.")
        else:
            avisos.append(f"Por cada $1 que arriesgás, buscás ganar ${stop_info['rr_ratio']:.2f}. Relación favorable. ✅")

    if not avisos:
        avisos.append('Sin alertas particulares en la gestión de riesgo cargada.')
    return dict(nivel=nivel, avisos=avisos)


def _sesgo_a_tendencia(sesgo):
    if sesgo in ('MUY ALCISTA', 'ALCISTA'):
        return 'ALCISTA'
    if sesgo in ('MUY BAJISTA', 'BAJISTA'):
        return 'BAJISTA'
    return 'LATERAL'


# ==============================================================
#  1-bis) CONFIGURACIÓN AUTOMÁTICA POR MERCADO / ACTIVO / PLATAFORMA
#         (decimales, lotes, tamaño de contrato)
# ==============================================================

MERCADOS = ['Cripto / Acciones', 'Forex', 'Commodities']

# Dónde operás: en un exchange (unidades) o en un bróker CFD (lotes).
# Los dos permiten apalancamiento.
PLATAFORMAS = ['Exchange · unidades', 'Broker · lotes']

CONTRATO_FOREX = 100_000.0  # 1 lote estándar = 100.000 unidades de la divisa base

# Tamaño de contrato estándar (unidades por 1 lote) de los commodities más comunes.
CONTRATOS_COMMODITY = {
    'GC=F': 100.0,  'XAUUSD=X': 100.0, 'XAUUSD': 100.0, 'MGC=F': 10.0,   # Oro (onzas)
    'SI=F': 5000.0, 'XAGUSD=X': 5000.0, 'XAGUSD': 5000.0,                # Plata (onzas)
    'CL=F': 1000.0, 'BZ=F': 1000.0, 'USOIL': 1000.0,                     # Petróleo (barriles)
    'NG=F': 10000.0,                                                     # Gas natural (MMBtu)
    'HG=F': 25000.0,                                                     # Cobre (libras)
    'PL=F': 50.0,   'PA=F': 100.0,                                       # Platino / Paladio (onzas)
}

_PLACEHOLDER_TICKER = {
    'Cripto / Acciones': 'NVDA, AAPL, BTC-USD, ETH-USD',
    'Forex': 'EURUSD=X, USDJPY=X',
    'Commodities': 'GC=F (oro), CL=F (petróleo)',
}


def _es_cripto(t):
    sufijos_cripto = ('-USD', '-USDT', '-USDC', '-EUR', '-BTC', '-ETH')
    simbolos_cripto_conocidos = (
        'BTC', 'ETH', 'SOL', 'XRP', 'DOGE', 'ADA', 'BNB', 'AVAX', 'MATIC',
        'DOT', 'LINK', 'LTC', 'SHIB', 'TRX', 'ATOM', 'UNI', 'ETC', 'XLM',
    )
    return t.endswith(sufijos_cripto) or t.endswith('USDT') or any(
        t.startswith(s) and (t == s or not t[len(s):len(s) + 1].isalpha())
        for s in simbolos_cripto_conocidos
    )


def config_activo(mercado, ticker, precio_ref=None, usa_lotes=None):
    """
    Decide sola la precisión y la unidad de operación según el activo Y la plataforma.
      - Exchange (usa_lotes=False): cantidad en unidades/tokens, solo apalancamiento.
      - Broker CFD (usa_lotes=True): cantidad en lotes (+ apalancamiento).
    Si usa_lotes es None se usa el comportamiento clásico (Forex/Commodities = lotes).
    Devuelve: clase, dec_cant, dec_precio, es_lotes, contrato (unidades por lote, o 1 si son
    unidades), contrato_conocido (False si el tamaño de lote depende del bróker).
    """
    t = (ticker or '').upper().strip()
    if usa_lotes is None:
        usa_lotes = mercado in ('Forex', 'Commodities')

    # 1) Clase de activo → decimales de precio, decimales de cantidad en unidades y tamaño de lote
    if mercado == 'Forex':
        clase, dec_p = 'forex', (3 if 'JPY' in t else 5)
        dec_unid, contrato_lote, conocido = 0, CONTRATO_FOREX, True
    elif mercado == 'Commodities':
        c = CONTRATOS_COMMODITY.get(t)
        clase, dec_p = 'commodity', 2
        dec_unid, contrato_lote, conocido = 2, (c or 100.0), c is not None
    elif _es_cripto(t):
        # 2 decimales de precio para las grandes; sube solo si el precio es chico
        # para no truncar altcoins tipo 0.00000012.
        if not precio_ref or precio_ref >= 1:
            dec_p = 2
        elif precio_ref >= 0.01:
            dec_p = 4
        elif precio_ref >= 0.0001:
            dec_p = 6
        else:
            dec_p = 10
        clase = 'cripto'
        dec_unid, contrato_lote, conocido = 6, 1.0, False   # en MT5 suele ser 1 lote = 1 moneda
    else:
        clase, dec_p = 'accion', 2
        dec_unid, contrato_lote, conocido = 0, 1.0, False   # CFD de acciones: suele ser 1 lote = 1 acción

    # 2) Plataforma → unidades o lotes
    if usa_lotes:
        return dict(clase=clase, dec_cant=2, dec_precio=dec_p, es_lotes=True,
                    contrato=contrato_lote, contrato_conocido=conocido)
    return dict(clase=clase, dec_cant=dec_unid, dec_precio=dec_p, es_lotes=False,
                contrato=1.0, contrato_conocido=True)


def _paso(decimales):
    """Paso mínimo (step) para un number_input dado un número de decimales."""
    return round(10 ** (-decimales), decimales) if decimales > 0 else 1.0


def _floor_dec(x, decimales):
    """Redondea hacia ABAJO (para que la cantidad recomendada nunca pase tu límite de riesgo)."""
    f = 10 ** decimales
    return math.floor(x * f + 1e-9) / f


# ==============================================================
#  2) TENDENCIA — reutiliza TU motor (largo/corto) o uno propio de respaldo
# ==============================================================

def detectar_tendencia_largo(ticker, analizar_largo, descargar_datos, get_close_series, calcular_atr=None):
    df_tk = descargar_datos(ticker, '2y')
    if df_tk is None or df_tk.empty:
        return None
    cl = get_close_series(df_tk)
    if cl is None or len(cl) < 150:
        return None
    r = analizar_largo(ticker, cl)
    if r is None:
        return None
    atr_val = None
    if calcular_atr:
        atr_series = calcular_atr(df_tk)
        if atr_series is not None and len(atr_series.dropna()) > 0:
            atr_val = float(atr_series.dropna().iloc[-1])
    return dict(
        ticker=ticker, horizonte='largo', tendencia=_sesgo_a_tendencia(r['sesgo']),
        fuerza=r['global_score'], sesgo=r['sesgo'], rsi=r['rsi'], precio_actual=r['precio'],
        golden_cross=r['golden_cross'], max_dd=r['max_dd'], reversion_signal=r['reversion_signal'],
        atr=atr_val, serie=cl, motor='analizar_largo',
    )


def detectar_estado_corto(ticker, descargar_datos, get_close_series, calcular_atr=None,
                           scores_corto=None, señal_accion_corto=None):
    df_v = descargar_datos(ticker, '3mo')
    df_m = descargar_datos(ticker, '1mo')
    if df_v is None or df_m is None:
        return None
    cl_v = get_close_series(df_v)
    cl_m = get_close_series(df_m)
    if cl_v is None or cl_m is None or len(cl_v.dropna()) < 15:
        return None

    atr_series = calcular_atr(df_m) if calcular_atr else None
    atr_val = (float(atr_series.dropna().iloc[-1])
               if atr_series is not None and len(atr_series.dropna()) > 0 else None)

    precio_actual = float(cl_m.iloc[-1])
    ret_5d = float(cl_m.pct_change(5).iloc[-1] * 100) if len(cl_m) >= 6 else 0.0
    if np.isnan(ret_5d): ret_5d = 0.0

    delta = cl_m.diff()
    ganancia = delta.clip(lower=0).rolling(7).mean()
    perdida = (-delta.clip(upper=0)).rolling(7).mean()
    rs = ganancia / perdida.replace(0, np.nan)
    rsi = float((100 - 100 / (1 + rs)).iloc[-1])
    if np.isnan(rsi): rsi = 50.0

    sa = sn = ss = sf = None
    señal_txt = None
    if scores_corto:
        sa, sn, ss = scores_corto(cl_v, cl_m, atr_series)
        sf = round(sa * 0.45 + sn * 0.35 + ss * 0.20, 1)
        if señal_accion_corto:
            señal_txt = señal_accion_corto(sa, sn, ss)

    if ret_5d > 1.5 and rsi > 50:
        tendencia = 'ALCISTA'
    elif ret_5d < -1.5 and rsi < 50:
        tendencia = 'BAJISTA'
    else:
        tendencia = 'LATERAL'

    fuerza = sf if sf is not None else round(min(100, 50 + abs(ret_5d) * 5), 1)
    return dict(
        ticker=ticker, horizonte='corto', tendencia=tendencia, fuerza=fuerza, sesgo=None,
        rsi=round(rsi, 1), precio_actual=precio_actual, atr=atr_val, ret_5d=round(ret_5d, 2),
        score_final=sf, señal_corto=señal_txt, serie=cl_m, motor='corto_plazo',
    )


def detectar_tendencia_standalone(ticker, periodo='6mo', horizonte='largo'):
    """Respaldo si no le pasás las funciones de tu app."""
    if yf is None:
        raise RuntimeError("yfinance no está instalado en este entorno.")
    df = yf.download(ticker, period=periodo, interval='1d', auto_adjust=True, progress=False)
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if 'Close' not in df.columns:
        return None
    cl = df['Close'].dropna()
    n = len(cl)
    if n < 20:
        return None

    x = np.arange(n)
    log_y = np.log(cl.values)
    slope, _ = np.polyfit(x, log_y, 1)
    pendiente_diaria_pct = (np.exp(slope) - 1) * 100
    r2 = float(np.corrcoef(x, log_y)[0, 1] ** 2)
    ventana_corta = max(5, min(20, n // 3))
    ventana_larga = max(ventana_corta + 5, min(50, n - 1))
    ma_corta = cl.rolling(ventana_corta).mean()
    ma_larga = cl.rolling(ventana_larga).mean()
    cruce_alcista = float(ma_corta.iloc[-1]) > float(ma_larga.iloc[-1])

    delta = cl.diff()
    ganancia = delta.clip(lower=0).rolling(14).mean()
    perdida = (-delta.clip(upper=0)).rolling(14).mean()
    rs = ganancia / perdida.replace(0, np.nan)
    rsi = float((100 - 100 / (1 + rs)).iloc[-1])
    if np.isnan(rsi): rsi = 50.0

    vol_diaria_pct = float(cl.pct_change().std() * 100)
    umbral = max(0.03, vol_diaria_pct * 0.15)
    if pendiente_diaria_pct > umbral and cruce_alcista:
        tendencia = 'ALCISTA'
    elif pendiente_diaria_pct < -umbral and not cruce_alcista:
        tendencia = 'BAJISTA'
    else:
        tendencia = 'LATERAL'
    fuerza = round(min(100, abs(pendiente_diaria_pct) / umbral * 40 + r2 * 60), 1)

    atr_val = None
    if {'High', 'Low'}.issubset(df.columns):
        h, l = df['High'], df['Low']
        tr = pd.concat([h - l, (h - cl.shift(1)).abs(), (l - cl.shift(1)).abs()], axis=1).max(axis=1)
        atr_s = tr.rolling(14).mean().dropna()
        if len(atr_s) > 0:
            atr_val = float(atr_s.iloc[-1])

    return dict(
        ticker=ticker, horizonte=horizonte, tendencia=tendencia, fuerza=fuerza, sesgo=None,
        rsi=round(rsi, 1), precio_actual=float(cl.iloc[-1]), atr=atr_val,
        golden_cross=None, max_dd=None, serie=cl,
        ma_corta=ma_corta, ma_larga=ma_larga,
        ventana_corta=ventana_corta, ventana_larga=ventana_larga, motor='standalone',
    )


def evaluar_operacion(cant_actual, precio_prom_actual, cant_nueva, precio_nuevo, info_tend):
    calc = calcular_promedio(cant_actual, precio_prom_actual, cant_nueva, precio_nuevo)
    if calc.get('venta_excede_posicion'):
        return dict(calculo=calc, tendencia='N/A', riesgo='INVÁLIDO',
                    veredicto='⚠️ Estás intentando vender más de lo que tenés en cartera.',
                    razones=['Revisá la cantidad: la venta supera la posición actual.'])

    es_compra = cant_nueva > 0
    tendencia = info_tend['tendencia'] if info_tend else 'DESCONOCIDA'
    fuerza = info_tend['fuerza'] if info_tend else 0
    rsi = info_tend['rsi'] if info_tend else 50.0
    motor = info_tend.get('motor') if info_tend else None
    razones, riesgo = [], 'MEDIO'

    if es_compra:
        if precio_prom_actual > 0 and precio_nuevo < precio_prom_actual:
            razones.append('Estás promediando A LA BAJA: comprás más abajo que tu promedio actual.')
        elif precio_prom_actual > 0:
            razones.append('Estás promediando AL ALZA: comprás más arriba que tu promedio actual.')
        else:
            razones.append('Es una posición nueva.')

        if tendencia == 'BAJISTA':
            if precio_prom_actual > 0 and precio_nuevo < precio_prom_actual:
                riesgo = 'ALTO'
                razones.append('La tendencia es BAJISTA y estás comprando en la caída: el precio podría '
                                'seguir bajando antes de girar ("cuchillo cayendo").')
            else:
                razones.append('La tendencia es BAJISTA: conviene ser cauteloso.')
        elif tendencia == 'ALCISTA':
            riesgo = 'BAJO' if fuerza >= 55 else 'MEDIO'
            razones.append(f'La tendencia es ALCISTA (score {fuerza:.0f}/100): da soporte a la compra.')
        elif tendencia == 'LATERAL':
            razones.append('La tendencia es LATERAL, sin dirección clara: conviene ir de a poco.')
        else:
            razones.append('No se pudo determinar la tendencia (datos insuficientes).')

        if rsi < 30:
            razones.append(f'RSI en {rsi:.1f}: zona de sobreventa, puede favorecer un rebote.')
        elif rsi > 70:
            razones.append(f'RSI en {rsi:.1f}: zona de sobrecompra, mayor riesgo de entrar "caro".')

        if motor == 'analizar_largo' and info_tend.get('reversion_signal'):
            razones.append('Hay señal de reversión a la media activa: contexto más favorable para promediar a la baja.')
        elif motor == 'corto_plazo' and info_tend.get('señal_corto'):
            razones.append(f"Señal de corto plazo del modelo: {info_tend['señal_corto']}")
    else:
        razones.append('Estás vendiendo parte (o toda) la posición.')
        if tendencia == 'ALCISTA':
            razones.append('Ojo: la tendencia sigue siendo ALCISTA — podrías estar saliendo antes de tiempo.')
        elif tendencia == 'BAJISTA':
            razones.append('La tendencia es BAJISTA: reducir exposición es consistente con el contexto.')
            riesgo = 'BAJO'
        else:
            razones.append('La tendencia es LATERAL: sin catalizador claro a favor ni en contra.')

    if riesgo == 'ALTO':
        veredicto = '🔴 El contexto de tendencia no acompaña esta operación.'
    elif riesgo == 'BAJO':
        veredicto = '🟢 Buen contexto de tendencia para esta operación.'
    else:
        veredicto = '🟡 Operación viable, sin una señal fuerte a favor ni en contra.'
    return dict(calculo=calc, tendencia=tendencia, riesgo=riesgo, veredicto=veredicto, razones=razones)


# ==============================================================
#  3) GLOSARIO — para el expander "¿Qué significa cada cosa?"
# ==============================================================

GLOSARIO_PROM = [
    ('Precio promedio', 'Es el precio "de referencia" de toda tu posición si sumás todas las compras. '
     'Si comprás a distintos precios, el promedio te dice a qué precio necesitarías vender para no ganar ni perder.'),
    ('Promediar a la baja', 'Comprar más del mismo activo cuando bajó de precio. Baja tu precio promedio, '
     'pero solo tiene sentido si creés que el activo va a recuperarse — si sigue el motivo de la baja, perdés más.'),
    ('Tendencia', 'Hacia dónde se está moviendo el precio en general: ALCISTA (sube), BAJISTA (baja) '
     'o LATERAL (sin dirección clara, se mueve para los costados).'),
    ('Capital total de tu cuenta', 'TODO el dinero que tenés disponible para invertir u operar en general — '
     'no solo lo que vas a poner en esta operación puntual. Se usa como referencia para calcular qué '
     'porción de tu plata total estarías arriesgando si esta operación sale mal. No es un monto que la '
     'herramienta te va a descontar ni reservar, es solo la base del cálculo.'),
    ('% de riesgo deseado', 'Cuánto de tu cuenta TOTAL estás dispuesto a perder si esta operación puntual '
     'sale mal (no el % de esta operación en sí). La regla clásica de trading dice no arriesgar más del 1-2% '
     'de tu cuenta en una sola operación, aunque uses todo tu apalancamiento o toda tu convicción en ella.'),
    ('Capital para la operación', 'Solo en modo Exchange. Es la plata tuya (margen) que ponés en ESTA operación. '
     'La cantidad se calcula sola: capital × apalancamiento ÷ precio de entrada. El módulo te avisa si, con ese '
     'capital, la pérdida en el stop supera el % de riesgo que definiste sobre tu cuenta total.'),
    ('Plataforma', 'Dónde ejecutás la operación. Exchange: comprás en unidades o tokens (por ejemplo 0,05 BTC) '
     'y, si querés, con apalancamiento. Broker CFD (MT4/MT5, cTrader, etc.): operás en lotes, también con '
     'apalancamiento. Un mismo activo se puede operar de las dos formas; elegí la que usás vos.'),
    ('Lote', 'Unidad de contrato que usan los brókers CFD (MT4/MT5, cTrader, etc.). 1 lote estándar de Forex = '
     '100.000 unidades de la divisa; 1 lote de oro = 100 onzas; 1 lote de petróleo = 1.000 barriles. En los '
     'exchanges no hay lotes: se opera en unidades o tokens. El módulo convierte los lotes a unidades por vos '
     'para calcular margen, exposición y pérdida.'),
    ('Stop Loss', 'El precio al que vas a vender (o cerrar la posición) automáticamente si el precio va en tu contra, '
     'para cortar la pérdida antes de que sea mayor. En una inversión de largo plazo suele pensarse más '
     'como "el precio al que la razón por la que compré dejó de ser válida", no como un stop ajustado día a día.'),
    ('Modos de Stop', 'Manual: vos escribís el precio exacto. Por ATR: el módulo lo calcula según la volatilidad '
     'real del activo. % Fijo: lo coloca a -2%, -3% o -5% del precio de entrada (invertido si es Short).'),
    ('ATR', 'Mide cuánto se mueve el precio de un activo en un día normal (su volatilidad). '
     'Un stop basado en ATR se adapta a cada activo, en vez de usar el mismo % para todos.'),
    ('Apalancamiento', 'Operar con más dinero del que tenés, pedido "prestado" por el bróker/exchange. '
     'Multiplica tanto las ganancias como las pérdidas — con 10x, un movimiento de 10% en tu contra puede '
     'liquidar toda tu posición. Si estás comprando un activo para conservarlo en el tiempo, lo normal es '
     'dejarlo en 1x (sin apalancar).'),
    ('Precio de liquidación', 'El precio al que el bróker/exchange te cierra la posición por la fuerza porque '
     'perdiste todo el margen que pusiste. Cuanto más apalancamiento, más cerca está de tu precio de entrada. '
     'Con apalancamiento 1x no aplica: nadie te puede liquidar, en el peor caso el activo vale $0.'),
    ('Cantidad recomendada', 'Cuánto podés comprar/vender sin superar el % de tu cuenta que dijiste que ibas '
     'a arriesgar, dado dónde pusiste el stop. Es el "tamaño correcto" de la operación. Si ya tenés posición, '
     'se descuenta el riesgo que esa posición ya tiene.'),
    ('Ganancia estimada', 'Cuánto ganarías en dólares si el precio llega a tu Take Profit. Se calcula sobre '
     'toda tu posición (lo que ya tenías más lo nuevo) contra el precio promedio resultante.'),
    ('Ratio Riesgo/Beneficio', 'Compara cuánto podés perder contra cuánto podés ganar. Un ratio de 2:1 significa '
     'que por cada $1 que arriesgás, tu objetivo es ganar $2.'),
]


# ==============================================================
#  4) MÓDULO STREAMLIT — layout 2 columnas fijas, resultados en vivo
# ==============================================================

_TTL_TENDENCIA = 300  # segundos que se reutiliza la tendencia ya descargada

_NIVELES_UI = {
    'ok':     ('#3fb950', '🟢'),
    'warn':   ('#f0883e', '🟠'),
    'danger': ('#f85149', '🔴'),
    'info':   ('#3a7bd5', 'ℹ️'),
}


def _banner(nivel, texto):
    color, icono = _NIVELES_UI[nivel]
    return (f'<div style="background:{color}22;border:1px solid {color};border-left:5px solid {color};'
            f'border-radius:10px;padding:14px 18px;margin-bottom:14px;font-size:14px;font-weight:600;'
            f'color:#e6edf3;line-height:1.5">{icono} {texto}</div>')


def _kpi_card(titulo, valor, detalle='', color='#e6edf3', destacado=False):
    borde = f'2px solid {color}' if destacado else '1px solid #21262d'
    tam = '28px' if destacado else '19px'
    return (f'<div style="background:#0d1117;border:{borde};border-radius:10px;padding:12px 14px;'
            f'min-height:98px;margin-bottom:10px">'
            f'<div style="font-size:11px;color:#6b7d9a;margin-bottom:4px">{titulo}</div>'
            f'<div style="font-size:{tam};font-weight:700;color:{color};line-height:1.2">{valor}</div>'
            f'<div style="font-size:11px;color:#8b949e;margin-top:4px">{detalle}</div></div>')


def _pill(etiqueta, valor, color='#e6edf3'):
    return (f'<div style="background:#0d1117;border:1px solid #21262d;border-radius:20px;'
            f'padding:8px 16px;font-size:13px;color:#6b7d9a">{etiqueta}: '
            f'<b style="color:{color}">{valor}</b></div>')


def _set_state(clave, valor):
    """Callback para botones: pisa el valor de un input antes del próximo rerun."""
    st.session_state[clave] = valor


def _calcular_tendencia(ticker, horizonte, f):
    usa_largo = all([f['analizar_largo'], f['descargar_datos'], f['get_close_series']])
    usa_corto = all([f['descargar_datos'], f['get_close_series'], f['scores_corto'], f['señal_accion_corto']])
    if horizonte == 'largo' and usa_largo:
        return detectar_tendencia_largo(ticker, f['analizar_largo'], f['descargar_datos'],
                                        f['get_close_series'], f['calcular_atr'])
    if horizonte == 'corto' and usa_corto:
        return detectar_estado_corto(ticker, f['descargar_datos'], f['get_close_series'],
                                     f['calcular_atr'], f['scores_corto'], f['señal_accion_corto'])
    return detectar_tendencia_standalone(ticker, '6mo', horizonte)


def _obtener_tendencia(ticker, horizonte, motores):
    """La tendencia se guarda unos minutos en session_state para no volver a descargar datos
    cada vez que tocás un número."""
    cache = st.session_state.setdefault('_prom_cache_tend', {})
    clave = (ticker, horizonte)
    hit = cache.get(clave)
    if hit and time.time() - hit[0] < _TTL_TENDENCIA:
        return hit[1], None
    try:
        info = _calcular_tendencia(ticker, horizonte, motores)
    except Exception as e:
        return None, str(e)
    if info is not None:
        cache[clave] = (time.time(), info)
    return info, None


def _senal_modelo(info, direccion):
    """Texto corto para el badge 'Señal Modelo'."""
    if info.get('señal_corto'):
        return str(info['señal_corto']), '#e6edf3'
    tend = info['tendencia']
    if (direccion == 'long' and tend == 'ALCISTA') or (direccion == 'short' and tend == 'BAJISTA'):
        return 'A favor', '#3fb950'
    if (direccion == 'long' and tend == 'BAJISTA') or (direccion == 'short' and tend == 'ALCISTA'):
        return 'Esperar', '#f85149'
    return 'Neutral', '#e3b341'


# --------------------------------------------------------------
#  Panel derecho: banner + grilla de KPIs
#  (cantidades recibidas en UNIDADES; se muestran en lotes si corresponde)
# --------------------------------------------------------------
def _panel_resultados(capital, pct_max, horizonte, direccion, apal, precio, cant_op_u,
                      precio_stop, precio_tp, cant_actual_u, prec_prom_actual, cfg, atr_val):
    dec_c, dec_p, contrato = cfg['dec_cant'], cfg['dec_precio'], cfg['contrato']

    faltan = []
    if precio <= 0:
        faltan.append('precio de entrada')
    if cant_op_u <= 0:
        faltan.append('cantidad')
    if precio_stop <= 0:
        faltan.append('Stop Loss')
    if cant_actual_u > 0 and prec_prom_actual <= 0:
        faltan.append('precio promedio actual')
    if faltan:
        st.markdown(_banner('info', 'Cargá ' + ', '.join(faltan) + ' para ver los resultados.'),
                    unsafe_allow_html=True)
        return

    # Stop disparatado (típico error de tipeo) — se frena antes de calcular nada
    dist_pct = abs(precio - precio_stop) / precio * 100
    limite = 60.0 if horizonte == 'corto' else 85.0
    if dist_pct > limite:
        st.markdown(_banner(
            'danger',
            f'Tu stop está a {dist_pct:.1f}% del precio de entrada (entrada ${precio:,.{dec_p}f} vs. '
            f'stop ${precio_stop:,.{dec_p}f}). Parece un error de tipeo o de decimales; corregilo.'),
            unsafe_allow_html=True)
        return

    # Promedio (si no hay posición previa, cant_actual = 0 y da la propia operación).
    # El riesgo se calcula sobre la posición TOTAL contra su precio promedio.
    try:
        prom = calcular_promedio(cant_actual_u, prec_prom_actual, cant_op_u, precio)
        stop_info = calcular_stop_loss(
            precio_entrada=prom['precio_promedio_final'], precio_stop=precio_stop,
            cantidad=prom['cantidad_final'], apalancamiento=apal, direccion=direccion,
            capital_cuenta=capital,
            precio_take_profit=precio_tp if precio_tp and precio_tp > 0 else None, atr=atr_val,
        )
    except ValueError as e:
        st.markdown(_banner('danger', str(e)), unsafe_allow_html=True)
        return

    riesgo_stop = evaluar_riesgo_stop(stop_info, horizonte, pct_max)

    # ── Banner de validación (semáforo coherente con la cantidad cargada) ──
    perdida_pct = stop_info['perdida_pct_cuenta']
    perdida_usd = stop_info['perdida_dinero']
    dinero_max = capital * pct_max / 100
    sobre = perdida_usd > dinero_max * 1.0001

    if not stop_info['stop_antes_de_liquidar']:
        lado = 'por debajo' if direccion == 'long' else 'por encima'
        st.markdown(_banner('danger', f'Peligro: El Stop Loss está {lado} del precio de liquidación'),
                    unsafe_allow_html=True)
    elif perdida_pct > PERDIDA_PCT_CUENTA_ALTO_ABSOLUTO:
        st.markdown(_banner('danger',
                            f'Peligro: si salta el stop perdés {perdida_pct:.1f}% de TODA tu cuenta — '
                            f'demasiado para una sola operación'), unsafe_allow_html=True)
    elif perdida_usd > dinero_max * 2:
        st.markdown(_banner('danger',
                            f'Sobre-riesgo fuerte: perdés ${perdida_usd:,.2f} ({perdida_pct:.1f}%) y tu límite '
                            f'es ${dinero_max:,.2f} ({pct_max:g}%). Reducí la cantidad.'),
                    unsafe_allow_html=True)
    elif sobre:
        st.markdown(_banner('warn',
                            f'Sobre-riesgo: perdés ${perdida_usd:,.2f} ({perdida_pct:.1f}%) y tu límite '
                            f'es ${dinero_max:,.2f} ({pct_max:g}%). Reducí la cantidad.'),
                    unsafe_allow_html=True)
    else:
        st.markdown(_banner('ok',
                            f'Riesgo dentro del límite: arriesgás ${perdida_usd:,.2f} '
                            f'({perdida_pct:.1f}% de tu cuenta) de un máximo de ${dinero_max:,.2f}'),
                    unsafe_allow_html=True)

    # ── Grilla de KPIs ────────────────────────────────────────
    rr = stop_info['rr_ratio']
    gan = stop_info['ganancia_potencial']

    # 1) Ganancia estimada al Take Profit
    if gan is None:
        card_gan = _kpi_card('Ganancia estimada (Take Profit)', '—',
                             'Poné un precio en Take Profit para calcularla', '#6b7d9a', True)
    elif gan <= 0:
        card_gan = _kpi_card('Ganancia estimada (Take Profit)', '—',
                             '⚠️ El Take Profit está del lado equivocado de la entrada '
                             '(en Long va por encima, en Short por debajo)', '#f0883e', True)
    else:
        dist_tp_pct = abs(precio_tp - prom['precio_promedio_final']) / prom['precio_promedio_final'] * 100
        card_gan = _kpi_card(
            'Ganancia estimada (Take Profit)', f'+${gan:,.2f}',
            f'+{gan / capital * 100:.1f}% de tu cuenta · TP a {dist_tp_pct:.2f}% de la entrada · '
            f'neto vs. pérdida del stop: +${gan - perdida_usd:,.2f}',
            '#3fb950', True)

    # 2) Ratio R/B
    if rr is None:
        card_rr = _kpi_card('Ratio Riesgo / Beneficio', '—', 'Definí un Take Profit para calcularlo', '#6b7d9a')
    elif gan is not None and gan <= 0:
        card_rr = _kpi_card('Ratio Riesgo / Beneficio', '—',
                            '⚠️ El Take Profit está del lado equivocado de la entrada', '#f0883e')
    else:
        col_rr = '#3fb950' if rr >= 2 else ('#e3b341' if rr >= 1 else '#f85149')
        txt_rr = 'Relación favorable' if rr >= 2 else ('Aceptable, ideal ≥ 1:2' if rr >= 1
                                                       else 'Arriesgás más de lo que buscás ganar')
        card_rr = _kpi_card('Ratio Riesgo / Beneficio', f'1:{rr:.1f}', txt_rr, col_rr)

    # 3) Pérdida máxima
    card_perd = _kpi_card('Pérdida máxima (si salta el Stop)', f'-${perdida_usd:,.2f}',
                          f'{perdida_pct:.1f}% de tu cuenta · límite ${dinero_max:,.2f} · '
                          f'stop a {stop_info["distancia_stop_pct"]:.2f}%',
                          '#f85149' if sobre else '#e6edf3')

    # 4) Margen requerido
    margen = stop_info['capital_propio']
    col_m = '#f85149' if margen > capital else '#e6edf3'
    det_m = (f'{margen / capital * 100:.1f}% de tu cuenta · exposición ${stop_info["exposicion_total"]:,.2f}'
             + (' · ⚠️ supera tu capital' if margen > capital else ''))
    card_marg = _kpi_card('Margen requerido', f'${margen:,.2f}', det_m, col_m)

    # 5) Precio de liquidación
    if apal > 1:
        col_l = '#e6edf3' if stop_info['stop_antes_de_liquidar'] else '#f85149'
        card_liq = _kpi_card('Precio de liquidación aprox.', f'${stop_info["precio_liquidacion"]:,.{dec_p}f}',
                             f'a {stop_info["distancia_liquidacion_pct"]:.2f}% de la entrada', col_l)
    else:
        card_liq = _kpi_card('Precio de liquidación aprox.', 'No aplica',
                             'Sin apalancamiento (1x) nadie te puede liquidar', '#6b7d9a')

    # Fila 1: Ganancia | Pérdida (lo que ganás vs. lo que arriesgás, lado a lado)
    # Fila 2: Ratio R/B | Margen
    # Fila 3: Liquidación
    fila1 = st.columns(2)
    fila2 = st.columns(2)
    fila3 = st.columns(2)
    for col, card in zip(fila1 + fila2 + fila3[:1],
                         [card_gan, card_perd, card_rr, card_marg, card_liq]):
        with col:
            st.markdown(card, unsafe_allow_html=True)

    if cant_actual_u > 0 and prom['variacion_precio_prom_pct'] is not None:
        unidad = 'lotes' if cfg['es_lotes'] else 'unidades'
        st.caption(f'🧮 Precio promedio nuevo: **${prom["precio_promedio_final"]:,.{dec_p}f}** '
                   f'({prom["variacion_precio_prom_pct"]:+.2f}%) · cantidad total: '
                   f'**{prom["cantidad_final"] / contrato:,.{dec_c}f} {unidad}**')

    if cant_actual_u > 0 and gan is not None and gan > 0:
        st.caption('💡 La ganancia estimada es la de toda tu posición (lo que ya tenías + lo nuevo) '
                   'si el precio llega al Take Profit.')

    with st.expander('Ver detalle de los avisos de riesgo'):
        for aviso in riesgo_stop['avisos']:
            st.markdown(f'- {aviso}')


# --------------------------------------------------------------
#  Módulo principal
# --------------------------------------------------------------
def modulo_promediador(analizar_largo=None, descargar_datos=None, get_close_series=None,
                        calcular_atr=None, scores_corto=None, señal_accion_corto=None):
    motores = dict(analizar_largo=analizar_largo, descargar_datos=descargar_datos,
                   get_close_series=get_close_series, calcular_atr=calcular_atr,
                   scores_corto=scores_corto, señal_accion_corto=señal_accion_corto)

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #6CC24A;
         border-radius:14px; padding:16px 24px; margin-bottom:16px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:4px">
        📐 Promediador + Riesgo
      </div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Cargá los parámetros a la izquierda: los resultados se actualizan al instante a la derecha.
        La tendencia y el gráfico quedan abajo como confirmación antes de ejecutar.
      </div>
    </div>
    """, unsafe_allow_html=True)

    col_in, col_out = st.columns([1, 1.25], gap='large')

    # ══════════════════ COLUMNA IZQUIERDA: INPUTS ══════════════════
    with col_in:
        st.markdown('#### 📥 Parámetros del trade')

        # ── Bloque 1: Activo y Cuenta ──────────────────────────────
        with st.container(border=True):
            st.markdown('**① Activo y cuenta**')
            mercado = st.selectbox('Mercado / tipo de activo', MERCADOS, key='prom_mercado')
            usa_lotes = st.radio(
                'Plataforma donde operás', PLATAFORMAS,
                index=1 if mercado in ('Forex', 'Commodities') else 0,
                horizontal=True, key=f'prom_plataforma_{mercado}',
                help='Exchange (o bróker de acciones): comprás en unidades/tokens y, si querés, con '
                     'apalancamiento. Broker CFD (MT4/MT5, cTrader, etc.): operás en lotes, también '
                     'con apalancamiento. Podés operar el mismo activo de las dos formas.',
            ) == 'Broker · lotes'
            b1, b2 = st.columns([1, 1])
            with b1:
                ticker = st.text_input('Ticker', value='', placeholder=_PLACEHOLDER_TICKER[mercado],
                                        key='prom_ticker').strip().upper()
            with b2:
                horizonte_label = st.radio(
                    'Tipo de operación', ['Inversión', 'Trade'], horizontal=True, key='prom_horizonte',
                    help='Inversión: comprar y conservar meses/años (normalmente sin apalancar). '
                         'Trade: operación acotada de días o semanas. Cambia el análisis de tendencia.',
                )
            horizonte = 'largo' if horizonte_label == 'Inversión' else 'corto'
            es_inversion = (horizonte == 'largo')

            b3, b4 = st.columns([1, 1])
            with b3:
                capital_cuenta = st.number_input(
                    '💰 Capital total (USD)', min_value=1.0, value=1000.0, step=100.0,
                    key='prom_capital_cuenta',
                    help='NO es lo que ponés en esta operación: es TODO tu dinero operable. '
                         'Sirve solo de base para calcular qué porción de tu cuenta arriesgás.',
                )
            with b4:
                pct_riesgo_max = st.number_input(
                    '% de riesgo deseado', min_value=0.1, max_value=25.0, value=2.0, step=0.5,
                    key='prom_pct_riesgo_max',
                    help='% de tu capital TOTAL que aceptás perder si salta el stop de ESTA operación. '
                         'Regla clásica: 1-2%. Tope en 25%.',
                )
            st.caption(f'Máximo a perder: **${capital_cuenta * pct_riesgo_max / 100:,.2f}**'
                       + (' · ⚠️ por encima del 5% que suele recomendarse' if pct_riesgo_max > 5 else ''))

        # Tendencia (en caché). Se calcula acá porque el precio actual define los
        # decimales de las criptos baratas y el ATR alimenta el stop automático.
        info_tend, err_tend = None, None
        if ticker:
            with st.spinner(f'Analizando {ticker}...'):
                info_tend, err_tend = _obtener_tendencia(ticker, horizonte, motores)
        atr_val = info_tend.get('atr') if info_tend else None
        precio_ref = info_tend['precio_actual'] if info_tend else None

        # Precisión y unidad de operación: 100% automáticas (según activo + plataforma)
        cfg = config_activo(mercado, ticker, precio_ref, usa_lotes)
        dec_c, dec_p = cfg['dec_cant'], cfg['dec_precio']
        paso_cant, paso_precio = _paso(dec_c), _paso(dec_p)
        fmt_cant, fmt_precio = f'%.{dec_c}f', f'%.{dec_p}f'
        etiqueta_cant = ('Cantidad a operar (en Lotes)' if cfg['es_lotes']
                         else 'Cantidad a operar (unidades/tokens)')

        # ── Bloque 2: Parámetros de entrada ────────────────────────
        with st.container(border=True):
            st.markdown('**② Parámetros de entrada**')
            help_apal = ('1x = con tu propia plata, sin margen ni futuros.'
                         + (' Para inversión de largo plazo lo normal es 1x.' if es_inversion else ''))
            capital_op = 0.0

            if cfg['es_lotes']:
                # ── Broker · lotes: la cantidad se carga a mano, en lotes ──
                e1, e2 = st.columns([1, 1])
                with e1:
                    direccion_label = st.radio('Dirección', ['Long', 'Short'], horizontal=True, key='prom_direccion')
                    direccion = 'long' if direccion_label == 'Long' else 'short'
                with e2:
                    apalancamiento = st.number_input(
                        'Apalancamiento (x)', min_value=1.0, max_value=1000.0, value=1.0, step=1.0,
                        key='prom_apalancamiento', help=help_apal)

                e3, e4 = st.columns([1, 1])
                with e3:
                    precio_nuevo = st.number_input('Precio de entrada (USD)', min_value=0.0, value=0.0,
                                                    step=paso_precio, format=fmt_precio, key='prom_precio_nuevo')
                with e4:
                    cant_op = st.number_input(etiqueta_cant, min_value=0.0, value=0.0,
                                               step=paso_cant, format=fmt_cant, key='prom_cant_op_lotes')
            else:
                # ── Exchange · unidades: capital → apalancamiento → cantidad automática ──
                direccion_label = st.radio('Dirección', ['Long', 'Short'], horizontal=True, key='prom_direccion')
                direccion = 'long' if direccion_label == 'Long' else 'short'

                capital_op = st.number_input(
                    '💵 Capital para la operación (USD)', min_value=0.0, value=0.0, step=10.0,
                    format='%.2f', key='prom_capital_op',
                    help='Cuánta plata tuya (margen) ponés en ESTA operación. Con el apalancamiento de abajo '
                         'se calcula la cantidad. Es distinto del capital total de tu cuenta.')
                apalancamiento = st.number_input(
                    'Apalancamiento (x)', min_value=1.0, max_value=1000.0, value=1.0, step=1.0,
                    key='prom_apalancamiento', help=help_apal)

                e3, e4 = st.columns([1, 1])
                with e3:
                    precio_nuevo = st.number_input('Precio de entrada (USD)', min_value=0.0, value=0.0,
                                                    step=paso_precio, format=fmt_precio, key='prom_precio_nuevo')
                cant_calc = (_floor_dec(capital_op * apalancamiento / precio_nuevo, dec_c)
                             if precio_nuevo > 0 and capital_op > 0 else 0.0)
                with e4:
                    cant_op = st.number_input(
                        'Cantidad a operar (automática)', min_value=0.0, value=float(cant_calc),
                        step=paso_cant, format=fmt_cant, disabled=True,
                        help='Se calcula sola: capital para la operación × apalancamiento ÷ precio de entrada '
                             '(redondeada hacia abajo).')

            if info_tend:
                px = info_tend['precio_actual']
                st.button(f'📍 Usar precio actual (${px:,.{dec_p}f})', key='prom_btn_px',
                          on_click=_set_state, args=('prom_precio_nuevo', round(float(px), dec_p)))

            # Tamaño de contrato: editable siempre que operes en lotes (cada bróker define el suyo)
            if cfg['es_lotes']:
                cfg['contrato'] = st.number_input(
                    'Unidades por lote (tamaño de contrato)', min_value=0.0001,
                    value=float(cfg['contrato']), step=1.0, format='%.4f',
                    key=f'prom_contrato_{cfg["clase"]}_{ticker}',
                    help='Cuántas unidades tiene 1 lote en tu bróker. Forex estándar = 100.000, '
                         'oro = 100 oz, petróleo = 1.000 barriles. En CFD de cripto y acciones '
                         'suele ser 1 lote = 1 unidad, pero varía: confirmalo en tu plataforma.')
                if not cfg['contrato_conocido']:
                    st.caption('⚠️ Este tamaño de lote es un valor típico, no un dato seguro: '
                               'verificalo en la especificación del contrato de tu bróker.')
                contrato_txt = (f' → {cant_op:,.{dec_c}f} lotes = {cant_op * cfg["contrato"]:,.8g} '
                                f'unidades de exposición' if cant_op > 0 else '')
                st.caption(f'📦 1 lote = {cfg["contrato"]:,.8g} unidades' + contrato_txt)

            slot_riesgo = st.container()  # aviso de riesgo del capital cargado (solo modo exchange)
            slot_rec = st.container()  # acá va "⚡ Usar recomendado" (se completa cuando ya hay stop)

            tiene_posicion = st.checkbox('Ya tengo posición en este activo (promediar)', key='prom_tiene_posicion')
            cant_actual, precio_prom_actual = 0.0, 0.0
            if tiene_posicion:
                p1, p2 = st.columns(2)
                with p1:
                    cant_actual = st.number_input(
                        'Cantidad que ya tengo' + (' (lotes)' if cfg['es_lotes'] else ''),
                        min_value=0.0, value=0.0, step=paso_cant, format=fmt_cant,
                        key=f'prom_cant_actual_{"lotes" if cfg["es_lotes"] else "unid"}')
                with p2:
                    precio_prom_actual = st.number_input('Precio promedio actual', min_value=0.0, value=0.0,
                                                          step=paso_precio, format=fmt_precio,
                                                          key='prom_precio_actual')
            if es_inversion and apalancamiento > 1:
                st.info('Marcaste "Inversión" pero usás apalancamiento: existe precio de liquidación aunque '
                        'tu plan sea conservar.')

        # ── Bloque 3: Gestión de salida ────────────────────────────
        with st.container(border=True):
            st.markdown('**③ Gestión de salida**')
            modo_stop = st.radio('Modo de Stop Loss', ['Manual', 'Por ATR / Volatilidad', '% Fijo'],
                                  horizontal=True, key='prom_modo_stop')
            precio_stop = 0.0

            if modo_stop == 'Manual':
                precio_stop = st.number_input(
                    '🛑 Stop Loss (USD)', min_value=0.0, value=0.0, step=paso_precio,
                    format=fmt_precio, key='prom_stop_manual',
                    help='Precio al que cortás la pérdida.'
                         + (' En inversión: donde deja de ser válida la razón de tu compra.' if es_inversion else ''))

            elif modo_stop == 'Por ATR / Volatilidad':
                mults = [1.0, 1.5, 2.0, 3.0]
                mult = st.select_slider(
                    'Múltiplo de ATR', options=mults, value=3.0 if es_inversion else 1.5,
                    key=f'prom_mult_atr_{horizonte}',
                    format_func=lambda m: f'{m:g}× ATR',
                    help='Cuántas "volatilidades diarias normales" separan el stop de tu entrada. '
                         'Más alto = stop más holgado.')
                if not ticker:
                    st.info('Ingresá un ticker para calcular el ATR.')
                elif not atr_val:
                    st.warning('No hay ATR disponible para este activo. Usá el modo Manual o % Fijo.')
                elif precio_nuevo <= 0:
                    st.info('Cargá el precio de entrada para calcular el stop por ATR.')
                else:
                    sug = sugerir_stop_atr(precio_nuevo, atr_val, direccion, mult)
                    if sug and sug > 0:
                        precio_stop = round(sug, dec_p)
                        st.success(f'🛑 Stop calculado: **${precio_stop:,.{dec_p}f}** '
                                   f'({mult:g} × ATR de {atr_val:,.{dec_p}f})')
                    else:
                        st.warning('El stop por ATR quedaría en un precio inválido (≤ 0). '
                                   'Probá un múltiplo menor.')

            else:  # % Fijo
                pct_stop = st.radio('Distancia del stop', [2, 3, 5], horizontal=True,
                                     format_func=lambda p: f'-{p}%' if direccion == 'long' else f'+{p}%',
                                     key='prom_pct_stop')
                if precio_nuevo <= 0:
                    st.info('Cargá el precio de entrada para calcular el stop.')
                else:
                    precio_stop = round(sugerir_stop_pct(precio_nuevo, pct_stop, direccion), dec_p)
                    st.success(f'🛑 Stop calculado: **${precio_stop:,.{dec_p}f}** '
                               f'({pct_stop}% {"por debajo" if direccion == "long" else "por encima"} de la entrada)')

            precio_tp = st.number_input(
                '🎯 Take Profit (USD)', min_value=0.0, value=0.0, step=paso_precio,
                format=fmt_precio, key='prom_tp',
                help='Opcional (0 = sin objetivo). Habilita la ganancia estimada y el ratio Riesgo/Beneficio.')

        # ── Botón "⚡ Usar recomendado" (junto al campo de cantidad) ──
        contrato = cfg['contrato']
        cant_actual_u = cant_actual * contrato
        rec_u = cantidad_recomendada_unidades(
            capital_cuenta, pct_riesgo_max, direccion, precio_nuevo, precio_stop,
            cant_actual_u, precio_prom_actual)
        dinero_max_op = capital_cuenta * pct_riesgo_max / 100

        # Capital máximo (margen) que respeta tu riesgo con este stop — solo modo exchange
        cap_rec = None
        if not cfg['es_lotes'] and rec_u is not None and precio_nuevo > 0:
            cap_rec = math.floor(rec_u * precio_nuevo / apalancamiento * 100) / 100

        # ── Aviso de riesgo según el capital cargado (solo modo exchange) ──
        with slot_riesgo:
            if not cfg['es_lotes'] and capital_op > 0 and precio_nuevo > 0:
                if cant_op <= 0:
                    st.warning('Con este capital y apalancamiento no alcanza ni para la mínima cantidad '
                               'operable. Subí el capital o el apalancamiento.')
                else:
                    if capital_op > capital_cuenta:
                        st.warning(f'⚠️ El capital de la operación (\\${capital_op:,.2f}) supera el capital '
                                   f'total de tu cuenta (\\${capital_cuenta:,.2f}).')
                    if precio_stop > 0 and not (cant_actual_u > 0 and precio_prom_actual <= 0):
                        try:
                            prom_l = calcular_promedio(cant_actual_u, precio_prom_actual, cant_op, precio_nuevo)
                            p_avg = prom_l['precio_promedio_final']
                            lado_ok = precio_stop < p_avg if direccion == 'long' else precio_stop > p_avg
                            if lado_ok:
                                perd = abs(p_avg - precio_stop) * prom_l['cantidad_final']
                                perd_pct = perd / capital_cuenta * 100
                                tope = (f' Capital máximo para respetarlo: **\\${cap_rec:,.2f}**.'
                                        if cap_rec else '')
                                if perd > dinero_max_op * 1.0001:
                                    msg = (f'🚨 Con **\\${capital_op:,.2f}** de capital ({apalancamiento:g}x) '
                                           f'te pasás de tu riesgo deseado: si salta el stop perdés '
                                           f'**\\${perd:,.2f}** ({perd_pct:.1f}% de tu cuenta) y tu límite es '
                                           f'**\\${dinero_max_op:,.2f}** ({pct_riesgo_max:g}%).' + tope)
                                    (st.error if perd > dinero_max_op * 2 else st.warning)(msg)
                        except ValueError:
                            pass

        # ── Botón recomendado ──
        with slot_rec:
            if rec_u is None:
                st.caption('⚡ Cargá entrada y Stop para ver la recomendación.')
            elif not cfg['es_lotes']:
                # Exchange: se recomienda el CAPITAL; la cantidad sale sola
                if cap_rec and cap_rec > 0:
                    st.button('⚡ Usar capital recomendado', key='prom_usar_sugerida',
                              on_click=_set_state, args=('prom_capital_op', cap_rec))
                else:
                    st.caption('Con este stop y tu % de riesgo no alcanza ni para la mínima '
                               'cantidad operable. Acercá el stop o subí el % de riesgo.')
            else:
                rec_op = _floor_dec(rec_u / contrato, dec_c)
                r1, r2 = st.columns([1, 1.6])
                with r1:
                    st.button('⚡ Usar recomendado', key='prom_usar_sugerida',
                              on_click=_set_state, args=('prom_cant_op_lotes', rec_op),
                              disabled=rec_op <= 0, use_container_width=True)
                with r2:
                    if rec_op > 0:
                        st.caption(f'Recomendado: **{rec_op:,.{dec_c}f}** lotes para arriesgar '
                                   f'como máximo ${dinero_max_op:,.2f}')
                    else:
                        st.caption('Con este stop y tu % de riesgo no alcanza ni para la mínima '
                                   'cantidad operable. Acercá el stop o subí el % de riesgo.')

    # ══════════════════ COLUMNA DERECHA: RESULTADOS EN VIVO ══════════════════
    with col_out:
        st.markdown('#### 📊 Resultados en tiempo real')
        _panel_resultados(
            capital_cuenta, pct_riesgo_max, horizonte, direccion, apalancamiento, precio_nuevo,
            cant_op * contrato, precio_stop, precio_tp, cant_actual_u, precio_prom_actual,
            cfg, atr_val,
        )

    # ══════════════════ SECCIÓN INFERIOR: TENDENCIA Y GRÁFICO ══════════════════
    st.markdown('---')
    st.markdown('#### 📉 Filtro de tendencia y gráfico')
    if not ticker:
        st.info('Ingresá un ticker para ver la tendencia y el gráfico.')
    elif err_tend:
        st.error(f'No se pudo analizar la tendencia: {err_tend}')
    elif info_tend is None:
        st.warning(f'No hay datos suficientes para {ticker}. Verificá el símbolo.')
    else:
        color_t = {'ALCISTA': '#3fb950', 'BAJISTA': '#f85149', 'LATERAL': '#e3b341'}.get(info_tend['tendencia'], '#e6edf3')
        senal_txt, senal_col = _senal_modelo(info_tend, direccion)
        pills = [
            _pill('Tendencia', (info_tend.get('sesgo') or info_tend['tendencia']).capitalize(), color_t),
            _pill('RSI', f"{info_tend['rsi']:.1f}"),
            _pill('Señal Modelo', senal_txt, senal_col),
            _pill('Precio actual', f"${info_tend['precio_actual']:,.{dec_p}f}"),
        ]
        st.markdown('<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px">'
                    + ''.join(pills) + '</div>', unsafe_allow_html=True)

        # Gráfico simplificado: precio + medias de 7 y 20 períodos
        cl = info_tend['serie']
        ma7, ma20 = cl.rolling(7).mean(), cl.rolling(20).mean()
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=cl.index, y=cl, name='Precio', line=dict(color=color_t, width=2)))
        fig.add_trace(go.Scatter(x=ma7.index, y=ma7, name='Media 7', line=dict(color='#e3b341', width=1.2, dash='dot')))
        fig.add_trace(go.Scatter(x=ma20.index, y=ma20, name='Media 20', line=dict(color='#3a7bd5', width=1.4)))
        fig.update_layout(
            plot_bgcolor='#0d1117', paper_bgcolor='#07090f',
            font=dict(color='#b0bcd0', family='Inter, sans-serif'),
            title=dict(text=f"{info_tend['ticker']} · {info_tend['tendencia']}", font=dict(color='#e6edf3', size=13)),
            xaxis=dict(gridcolor='#21262d'), yaxis=dict(gridcolor='#21262d'),
            height=340, hovermode='x unified', legend=dict(orientation='h', y=1.1),
            margin=dict(l=10, r=10, t=45, b=10),
        )
        st.plotly_chart(fig, use_container_width=True, config=dict(displayModeBar=False, scrollZoom=False))

        # Por qué la tendencia acompaña o no
        if precio_nuevo > 0 and cant_op > 0:
            try:
                ev = evaluar_operacion(cant_actual_u, precio_prom_actual, cant_op * contrato,
                                       precio_nuevo, info_tend)
                with st.expander(f"Detalle del filtro de tendencia — {ev['veredicto']}"):
                    for r in ev['razones']:
                        st.markdown(f'- {r}')
            except ValueError:
                pass

    with st.expander('❓ ¿Qué significa cada cosa? (glosario rápido)'):
        for termino, explicacion in GLOSARIO_PROM:
            st.markdown(f"<div style='margin:4px 0;font-size:12px'><b style='color:#6CC24A'>{termino}</b> "
                        f"— <span style='color:#8b949e'>{explicacion}</span></div>", unsafe_allow_html=True)

    st.caption('⚠️ Herramienta de apoyo cuantitativo, no asesoramiento financiero. El precio de liquidación '
               'es aproximado (no incluye fees ni margen de mantenimiento del bróker/exchange). En Forex y '
               'Commodities la pérdida se expresa en USD asumiendo que la moneda de cotización es el dólar. '
               'El tamaño de lote en cripto y acciones depende de tu bróker: verificalo antes de operar.')
