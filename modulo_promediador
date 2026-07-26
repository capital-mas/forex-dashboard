# ==============================================================
#  MÓDULO PROMEDIADOR DE POSICIONES + STOP LOSS + APALANCAMIENTO
#  (reutiliza el motor cuantitativo de tu app — no duplica lógica)
# ==============================================================
"""
Se integra al Analizador Cuantitativo Unificado como un módulo más.

IMPORTANTE — evita import circular:
Este archivo NO importa nada de tu app principal. Tu app principal le
PASA sus propias funciones (analizar_largo, descargar_datos,
get_close_series, calcular_atr, scores_corto, señal_accion_corto)
como argumentos. Así reutiliza el mismo motor de Trend/MR/Risk Score
(largo plazo) y de Acumulación/Anticipación/Sentimiento (corto plazo)
sin que los dos archivos se importen entre sí.

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

Si lo llamás sin argumentos, funciona igual con un motor propio más
liviano (regresión + medias móviles + RSI), útil para probarlo suelto.
"""

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

try:
    import yfinance as yf
except ImportError:
    yf = None


# ==============================================================
#  1) CALCULADORA DE PROMEDIO — matemática pura
# ==============================================================

def calcular_promedio(cant_actual, precio_prom_actual, cant_nueva, precio_nuevo):
    """
    cant_actual         : cantidad que ya tenés (>= 0)
    precio_prom_actual  : precio promedio de compra actual
    cant_nueva          : cantidad de la operación (+compra / -venta)
    precio_nuevo        : precio de la operación
    """
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


# ==============================================================
#  2) STOP LOSS + APALANCAMIENTO — matemática pura
# ==============================================================

def sugerir_stop_atr(precio_entrada, atr, direccion='long', multiplo=1.5):
    """Stop sugerido en base a volatilidad (ATR), no a un % arbitrario."""
    if not atr or atr <= 0 or not precio_entrada:
        return None
    if direccion == 'long':
        return round(precio_entrada - multiplo * atr, 4)
    return round(precio_entrada + multiplo * atr, 4)


def calcular_stop_loss(precio_entrada, precio_stop, cantidad, apalancamiento=1.0,
                        direccion='long', capital_cuenta=None, precio_take_profit=None,
                        atr=None):
    """
    Calcula la pérdida si se toca el stop, el precio de liquidación
    aproximado (simplificado, sin fees ni margen de mantenimiento —
    cada bróker/exchange tiene su propia fórmula exacta) y el ratio
    riesgo/beneficio si hay take profit.
    """
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

    # Liquidación aproximada — simplificada (ignora fees / margen de mantenimiento).
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

    distancia_stop_en_atr = (
        abs(precio_entrada - precio_stop) / atr if atr and atr > 0 else None
    )

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


def evaluar_riesgo_stop(stop_info, horizonte='largo', pct_riesgo_max_cuenta=2.0):
    """Traduce los números del stop-loss en avisos de texto + nivel de riesgo."""
    avisos = []
    nivel = 'OK'

    if stop_info['perdida_pct_capital'] is not None:
        if stop_info['perdida_pct_capital'] > 50:
            nivel = 'ALTO'
            avisos.append(f"El stop implica perder {stop_info['perdida_pct_capital']:.1f}% del capital "
                           f"propio puesto en la operación: tamaño/apalancamiento muy agresivo.")
        elif stop_info['perdida_pct_capital'] > 25:
            nivel = 'MEDIO' if nivel == 'OK' else nivel
            avisos.append(f"El stop implica perder {stop_info['perdida_pct_capital']:.1f}% del capital propio: "
                           f"es una pérdida considerable para una sola operación.")

    if stop_info['perdida_pct_cuenta'] is not None:
        if stop_info['perdida_pct_cuenta'] > pct_riesgo_max_cuenta:
            nivel = 'ALTO' if stop_info['perdida_pct_cuenta'] > pct_riesgo_max_cuenta * 2 else (
                'MEDIO' if nivel == 'OK' else nivel)
            avisos.append(f"Estás arriesgando {stop_info['perdida_pct_cuenta']:.2f}% de tu cuenta total, "
                           f"por encima del {pct_riesgo_max_cuenta:.1f}% recomendado por operación "
                           f"(regla clásica de gestión de riesgo).")
        else:
            avisos.append(f"Estás arriesgando {stop_info['perdida_pct_cuenta']:.2f}% de tu cuenta total — "
                           f"dentro de un rango prudente para un límite de {pct_riesgo_max_cuenta:.1f}%.")

    if not stop_info['stop_antes_de_liquidar']:
        nivel = 'ALTO'
        avisos.append('⚠️ El precio de liquidación estimado está ANTES que tu stop loss: con este '
                       'apalancamiento podrías ser liquidado antes de que tu stop se ejecute.')
    elif (stop_info['distancia_liquidacion_pct'] - stop_info['distancia_stop_pct']) < 2:
        nivel = 'ALTO' if nivel == 'OK' else nivel
        avisos.append('El stop está muy cerca del precio de liquidación estimado: poco margen frente '
                       'a movimientos bruscos o slippage.')

    if stop_info['distancia_stop_en_atr'] is not None:
        multiplo_min = 1.0 if horizonte == 'corto' else 1.5
        if stop_info['distancia_stop_en_atr'] < multiplo_min:
            avisos.append(f"El stop está a solo {stop_info['distancia_stop_en_atr']:.2f} ATR de la entrada: "
                           f"puede saltar por ruido normal del precio.")
        elif stop_info['distancia_stop_en_atr'] > 5:
            avisos.append(f"El stop está a {stop_info['distancia_stop_en_atr']:.2f} ATR de distancia: es "
                           f"bastante amplio, revisá que el tamaño de posición siga siendo coherente.")

    if stop_info['rr_ratio'] is not None:
        if stop_info['rr_ratio'] < 1:
            nivel = 'ALTO' if nivel == 'OK' else nivel
            avisos.append(f"Ratio riesgo/beneficio de {stop_info['rr_ratio']:.2f}:1 — estás arriesgando "
                           f"más de lo que podrías ganar.")
        elif stop_info['rr_ratio'] < 1.5:
            avisos.append(f"Ratio riesgo/beneficio de {stop_info['rr_ratio']:.2f}:1 — aceptable, aunque "
                           f"lo ideal suele ser 2:1 o más.")
        else:
            avisos.append(f"Ratio riesgo/beneficio de {stop_info['rr_ratio']:.2f}:1 — favorable.")

    if not avisos:
        avisos.append('Sin alertas particulares en la gestión de riesgo cargada.')

    return dict(nivel=nivel, avisos=avisos)


# ==============================================================
#  3) MAPEO SESGO -> TENDENCIA SIMPLE
# ==============================================================

def _sesgo_a_tendencia(sesgo):
    if sesgo in ('MUY ALCISTA', 'ALCISTA'):
        return 'ALCISTA'
    if sesgo in ('MUY BAJISTA', 'BAJISTA'):
        return 'BAJISTA'
    return 'LATERAL'


# ==============================================================
#  4) DETECTORES DE TENDENCIA / ESTADO — LARGO Y CORTO PLAZO
# ==============================================================

def detectar_tendencia_largo(ticker, analizar_largo, descargar_datos, get_close_series,
                              calcular_atr=None):
    """Largo plazo usando TU motor: Trend/MR/Risk Score, Golden Cross, MACD, Hurst, Z-Score."""
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
        golden_cross=r['golden_cross'], macd_bull=r['macd_bull'], hurst=r['hurst'],
        zscore=r['zscore'], sharpe=r['sharpe'], max_dd=r['max_dd'],
        trend_score=r['trend_score'], mr_score=r['mr_score'], risk_score=r['risk_score'],
        reversion_signal=r['reversion_signal'], atr=atr_val, serie=cl, motor='analizar_largo',
    )


def detectar_estado_corto(ticker, descargar_datos, get_close_series, calcular_atr=None,
                           scores_corto=None, señal_accion_corto=None):
    """Corto plazo usando TU motor: Score Acumulación/Anticipación/Sentimiento."""
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
        score_acum=sa, score_antic=sn, score_sent=ss, score_final=sf,
        señal_corto=señal_txt, serie=cl_m, motor='corto_plazo',
    )


def detectar_tendencia_standalone(ticker, periodo='6mo', horizonte='largo'):
    """Fallback si no le pasás las funciones de tu app: regresión + medias + RSI + ATR."""
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
        golden_cross=None, macd_bull=None, hurst=None, zscore=None, sharpe=None, max_dd=None,
        serie=cl, ma_corta=ma_corta, ma_larga=ma_larga,
        ventana_corta=ventana_corta, ventana_larga=ventana_larga, motor='standalone',
    )


# ==============================================================
#  5) EVALUADOR DE LA OPERACIÓN (promedio + tendencia)
# ==============================================================

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
            razones.append('Estás promediando A LA BAJA: el precio nuevo es menor al promedio actual.')
        elif precio_prom_actual > 0:
            razones.append('Estás promediando AL ALZA: el precio nuevo es mayor al promedio actual.')
        else:
            razones.append('Es una posición nueva (no había cantidad previa).')

        if tendencia == 'BAJISTA':
            if precio_prom_actual > 0 and precio_nuevo < precio_prom_actual:
                riesgo = 'ALTO'
                razones.append('La tendencia es BAJISTA y estás comprando en la caída: '
                                'el precio podría seguir bajando antes de girar (cuchillo cayendo).')
            else:
                razones.append('La tendencia es BAJISTA: conviene ser cauteloso incluso a precio actual.')
        elif tendencia == 'ALCISTA':
            riesgo = 'BAJO' if fuerza >= 55 else 'MEDIO'
            razones.append(f'La tendencia es ALCISTA (fuerza {fuerza:.0f}/100): da soporte a la compra.')
        elif tendencia == 'LATERAL':
            razones.append('La tendencia es LATERAL: conviene operar en tramos chicos y esperar confirmación.')
        else:
            razones.append('No se pudo determinar la tendencia (datos insuficientes).')

        if rsi < 30:
            razones.append(f'RSI en {rsi:.1f}: zona de sobreventa, puede favorecer un rebote de corto plazo.')
        elif rsi > 70:
            razones.append(f'RSI en {rsi:.1f}: zona de sobrecompra, mayor riesgo de entrar "caro".')

        if motor == 'analizar_largo':
            if info_tend.get('reversion_signal'):
                razones.append('Hay señal de reversión a la media activa: contexto más favorable para promediar a la baja.')
            if info_tend.get('golden_cross') is False and tendencia != 'BAJISTA':
                razones.append('MA50 aún por debajo de MA200 (sin Golden Cross): tendencia de fondo no confirmada.')
            if info_tend.get('max_dd') is not None and info_tend['max_dd'] < -35:
                razones.append(f"Drawdown histórico severo ({info_tend['max_dd']:.1f}%): el activo mostró caídas profundas.")
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
            razones.append('La tendencia es LATERAL: sin catalizador claro a favor ni en contra de la venta.')

    if riesgo == 'ALTO':
        veredicto = '🔴 Operación de mayor riesgo — el contexto de tendencia no acompaña.'
    elif riesgo == 'BAJO':
        veredicto = '🟢 Operación con buen contexto estadístico a favor.'
    else:
        veredicto = '🟡 Operación viable, sin señal estadística fuerte a favor ni en contra.'

    return dict(calculo=calc, tendencia=tendencia, riesgo=riesgo, veredicto=veredicto, razones=razones)


# ==============================================================
#  6) GRÁFICO
# ==============================================================

def _fig_tendencia(info):
    cl = info['serie']
    color_tend = {'ALCISTA': '#3fb950', 'BAJISTA': '#f85149', 'LATERAL': '#e3b341'}.get(info['tendencia'], '#3a7bd5')
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=cl.index, y=cl, name='Precio', line=dict(color=color_tend, width=2)))

    if info.get('motor') == 'analizar_largo':
        ma50, ma200 = cl.rolling(50).mean(), cl.rolling(200).mean()
        fig.add_trace(go.Scatter(x=ma50.index, y=ma50, name='MA50', line=dict(color='#3fb950', width=1.3)))
        fig.add_trace(go.Scatter(x=ma200.index, y=ma200, name='MA200', line=dict(color='#f85149', width=1.3)))
        titulo = f"{info['ticker']} · Sesgo: {info['sesgo']} · Global {info['fuerza']:.0f}/100"
    elif info.get('motor') == 'corto_plazo':
        ma7, ma20 = cl.rolling(7).mean(), cl.rolling(20).mean()
        fig.add_trace(go.Scatter(x=ma7.index, y=ma7, name='MA7', line=dict(color='#e3b341', width=1.2, dash='dot')))
        fig.add_trace(go.Scatter(x=ma20.index, y=ma20, name='MA20', line=dict(color='#3a7bd5', width=1.3)))
        titulo = f"{info['ticker']} · Corto plazo · Tendencia: {info['tendencia']}"
    else:
        ma_c, ma_l = info['ma_corta'], info['ma_larga']
        fig.add_trace(go.Scatter(x=ma_c.index, y=ma_c, name=f"MA{info['ventana_corta']}", line=dict(color='#e3b341', width=1.3, dash='dash')))
        fig.add_trace(go.Scatter(x=ma_l.index, y=ma_l, name=f"MA{info['ventana_larga']}", line=dict(color='#3a7bd5', width=1.3)))
        titulo = f"{info['ticker']} · Tendencia: {info['tendencia']} (fuerza {info['fuerza']:.0f}/100)"

    fig.update_layout(
        plot_bgcolor='#0d1117', paper_bgcolor='#07090f',
        font=dict(color='#b0bcd0', family='Inter, sans-serif'),
        title=dict(text=titulo, font=dict(color='#e6edf3', size=13)),
        xaxis=dict(gridcolor='#21262d'), yaxis=dict(gridcolor='#21262d'),
        height=380, hovermode='x unified', legend=dict(orientation='h', y=1.1),
        margin=dict(l=10, r=10, t=45, b=10),
    )
    return fig


# ==============================================================
#  7) MÓDULO STREAMLIT
# ==============================================================

def modulo_promediador(analizar_largo=None, descargar_datos=None, get_close_series=None,
                        calcular_atr=None, scores_corto=None, señal_accion_corto=None):
    usa_motor_largo = all([analizar_largo, descargar_datos, get_close_series])
    usa_motor_corto = all([descargar_datos, get_close_series, scores_corto, señal_accion_corto])

    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #6CC24A;
         border-radius:14px; padding:26px 30px; margin-bottom:22px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">
        📐 Promediador + Stop Loss + Apalancamiento
      </div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Calculá tu nuevo precio promedio, chequeá si la tendencia acompaña la operación,
        y definí tu stop loss con apalancamiento — pérdida en $, % sobre tu capital y
        sobre tu cuenta, y precio de liquidación aproximado.
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Horizonte ─────────────────────────────────────────────────────
    horizonte_label = st.radio(
        'Horizonte de la operación', ['📈 Largo Plazo (meses/años)', '⚡ Corto Plazo (días/semanas)'],
        horizontal=True, key='prom_horizonte',
    )
    horizonte = 'largo' if 'Largo' in horizonte_label else 'corto'

    c1, c2 = st.columns([2, 1])
    with c1:
        ticker = st.text_input('Ticker', value='', placeholder='Ej: NVDA, GGAL, BTC-USD',
                                key='prom_ticker').strip().upper()
    with c2:
        motor_disp = usa_motor_largo if horizonte == 'largo' else usa_motor_corto
        if motor_disp:
            st.caption(f"Motor: {'analizar_largo (2 años)' if horizonte=='largo' else 'scores de corto plazo (1-3 meses)'}")
        else:
            periodo_fallback = st.selectbox('Historial (motor liviano)', ['3mo', '6mo', '1y', '2y'],
                                             index=1, key='prom_periodo')

    st.markdown('#### 📊 Posición actual')
    p1, p2 = st.columns(2)
    with p1:
        cant_actual = st.number_input('Cantidad que ya tenés', min_value=0.0, value=0.0,
                                       step=1.0, key='prom_cant_actual')
    with p2:
        precio_prom_actual = st.number_input('Precio promedio actual', min_value=0.0, value=0.0,
                                              step=0.01, format='%.4f', key='prom_precio_actual')

    st.markdown('#### 🎯 Operación a realizar')
    o1, o2 = st.columns(2)
    with o1:
        tipo_op = st.radio('Tipo de operación', ['Comprar (promediar)', 'Vender parcial'],
                            horizontal=True, key='prom_tipo_op')
    with o2:
        precio_nuevo = st.number_input('Precio de la operación', min_value=0.0001, value=1.0,
                                        step=0.01, format='%.4f', key='prom_precio_nuevo')
    cant_op = st.number_input('Cantidad de la operación', min_value=0.0001, value=1.0,
                               step=1.0, key='prom_cant_op')
    cant_nueva = cant_op if tipo_op.startswith('Comprar') else -cant_op

    # ── Stop Loss + Apalancamiento ──────────────────────────────────────
    st.markdown('#### 🛡️ Stop Loss y Apalancamiento')
    r1, r2, r3 = st.columns(3)
    with r1:
        direccion_default = 0 if tipo_op.startswith('Comprar') else 1
        direccion_label = st.radio('Dirección', ['Long (compra)', 'Short (venta en corto)'],
                                    index=direccion_default, horizontal=True, key='prom_direccion')
        direccion = 'long' if direccion_label.startswith('Long') else 'short'
    with r2:
        apalancamiento = st.number_input('Apalancamiento (x)', min_value=1.0, max_value=125.0,
                                          value=1.0, step=1.0, key='prom_apalancamiento')
    with r3:
        precio_entrada_riesgo = st.number_input('Precio de entrada para el cálculo', min_value=0.0001,
                                                 value=precio_nuevo, step=0.01, format='%.4f',
                                                 key='prom_precio_entrada_riesgo')

    modo_stop = st.selectbox(
        'Definir el stop loss por', ['Precio manual', '% de distancia', 'Múltiplo de ATR (según volatilidad)'],
        key='prom_modo_stop',
    )
    s1, s2 = st.columns(2)
    with s1:
        if modo_stop == 'Precio manual':
            precio_stop_manual = st.number_input('Precio del stop loss', min_value=0.0001, value=precio_nuevo * 0.95,
                                                   step=0.01, format='%.4f', key='prom_stop_manual')
        elif modo_stop == '% de distancia':
            pct_stop = st.number_input('% de distancia del stop', min_value=0.1, max_value=90.0, value=5.0,
                                        step=0.5, key='prom_stop_pct')
        else:
            multiplo_atr = st.number_input('Múltiplo de ATR', min_value=0.5, max_value=10.0,
                                            value=1.5 if horizonte == 'corto' else 3.0, step=0.5,
                                            key='prom_stop_atr_mult')
    with s2:
        usar_tp = st.checkbox('Definir Take Profit (opcional)', key='prom_usar_tp')
        precio_tp = None
        if usar_tp:
            precio_tp = st.number_input('Precio del Take Profit', min_value=0.0001,
                                         value=precio_nuevo * 1.10, step=0.01, format='%.4f', key='prom_tp')

    g1, g2 = st.columns(2)
    with g1:
        usar_capital = st.checkbox('Ingresar capital total de mi cuenta (para % de riesgo real)', key='prom_usar_capital')
        capital_cuenta = None
        if usar_capital:
            capital_cuenta = st.number_input('Capital total de la cuenta', min_value=0.0, value=1000.0,
                                              step=100.0, key='prom_capital_cuenta')
    with g2:
        pct_riesgo_max = st.number_input('% máximo de riesgo por operación (regla propia)', min_value=0.1,
                                          max_value=20.0, value=2.0, step=0.5, key='prom_pct_riesgo_max')

    analizar = st.button('▶ Calcular y evaluar todo', key='prom_run', type='primary')
    if not analizar:
        return
    if not ticker:
        st.warning('Ingresá un ticker para poder detectar la tendencia.')
        return

    # ── Tendencia / estado según horizonte ─────────────────────────────
    with st.spinner(f'Analizando {ticker} ({horizonte} plazo)...'):
        try:
            if horizonte == 'largo' and usa_motor_largo:
                info_tend = detectar_tendencia_largo(ticker, analizar_largo, descargar_datos,
                                                      get_close_series, calcular_atr)
            elif horizonte == 'corto' and usa_motor_corto:
                info_tend = detectar_estado_corto(ticker, descargar_datos, get_close_series,
                                                   calcular_atr, scores_corto, señal_accion_corto)
            else:
                periodo_fb = st.session_state.get('prom_periodo', '6mo')
                info_tend = detectar_tendencia_standalone(ticker, periodo_fb, horizonte)
        except Exception as e:
            st.error(f'No se pudo calcular la tendencia: {e}')
            info_tend = None

    if info_tend is None:
        st.warning(f'No se encontraron datos suficientes para {ticker}. Verificá el símbolo o el historial disponible.')

    # ── Promedio ─────────────────────────────────────────────────────
    try:
        resultado = evaluar_operacion(cant_actual, precio_prom_actual, cant_nueva, precio_nuevo, info_tend)
    except ValueError as e:
        st.error(f'Error en los datos de la posición: {e}')
        return

    calc = resultado['calculo']
    st.markdown('---')
    st.markdown('### 🧮 Resultado del promedio')
    if calc.get('venta_excede_posicion'):
        st.error(resultado['veredicto'])
        return

    k1, k2, k3, k4 = st.columns(4)
    with k1: st.metric('Cantidad final', f"{calc['cantidad_final']:,.2f}")
    with k2: st.metric('Precio promedio final', f"${calc['precio_promedio_final']:,.4f}",
                        f"{calc['variacion_precio_prom_pct']:+.2f}%" if calc['variacion_precio_prom_pct'] is not None else None)
    with k3: st.metric('Monto de la operación', f"${calc['monto_operacion']:,.2f}")
    with k4: st.metric('Total invertido', f"${calc['invertido_total']:,.2f}")

    st.markdown('### 🧭 Diagnóstico de tendencia y viabilidad')
    color_riesgo = {'BAJO': '#3fb950', 'MEDIO': '#e3b341', 'ALTO': '#f85149'}.get(resultado['riesgo'], '#3a7bd5')
    st.markdown(f"""
    <div style="background:#0d1117;border:1px solid #21262d;border-left:3px solid {color_riesgo};
         border-radius:8px;padding:14px 18px;margin-bottom:14px">
      <div style="font-size:13px;font-weight:700;color:{color_riesgo};margin-bottom:6px">{resultado['veredicto']}</div>
      <div style="font-size:12px;color:#f5f7fa;line-height:1.8">{'<br>• '.join([''] + resultado['razones'])}</div>
    </div>
    """, unsafe_allow_html=True)

    if info_tend:
        if info_tend.get('motor') == 'analizar_largo':
            t1, t2, t3, t4, t5 = st.columns(5)
            with t1: st.metric('Sesgo', info_tend['sesgo'])
            with t2: st.metric('Global Score', f"{info_tend['fuerza']:.0f}/100")
            with t3: st.metric('RSI', f"{info_tend['rsi']:.1f}")
            with t4: st.metric('Golden Cross', 'Sí' if info_tend['golden_cross'] else 'No')
            with t5: st.metric('Max Drawdown', f"{info_tend['max_dd']:.1f}%")
        elif info_tend.get('motor') == 'corto_plazo':
            t1, t2, t3, t4 = st.columns(4)
            with t1: st.metric('Tendencia', info_tend['tendencia'])
            with t2: st.metric('Score Final', f"{info_tend['score_final']:.0f}/100" if info_tend['score_final'] is not None else 'N/D')
            with t3: st.metric('RSI (7)', f"{info_tend['rsi']:.1f}")
            with t4: st.metric('Ret 5d', f"{info_tend['ret_5d']:+.2f}%")
            if info_tend.get('señal_corto'):
                st.markdown(f'<div style="margin:6px 0"><span style="padding:4px 12px;border-radius:20px;'
                            f'font-size:11px;font-weight:700;background:rgba(58,123,213,0.12);'
                            f'border:1px solid rgba(58,123,213,0.3);color:#3a7bd5">{info_tend["señal_corto"]}</span></div>',
                            unsafe_allow_html=True)
        else:
            t1, t2, t3, t4 = st.columns(4)
            with t1: st.metric('Tendencia', info_tend['tendencia'])
            with t2: st.metric('Fuerza', f"{info_tend['fuerza']:.0f}/100")
            with t3: st.metric('RSI', f"{info_tend['rsi']:.1f}")
            with t4: st.metric('Precio actual', f"${info_tend['precio_actual']:,.4f}")

        st.plotly_chart(_fig_tendencia(info_tend), use_container_width=True,
                         config=dict(displayModeBar=False, scrollZoom=False))

    # ── Cálculo del stop loss ───────────────────────────────────────────
    st.markdown('---')
    st.markdown('### 🛡️ Gestión de riesgo — Stop Loss y Apalancamiento')

    atr_val = info_tend.get('atr') if info_tend else None

    try:
        if modo_stop == 'Precio manual':
            precio_stop = precio_stop_manual
        elif modo_stop == '% de distancia':
            precio_stop = (
                precio_entrada_riesgo * (1 - pct_stop / 100) if direccion == 'long'
                else precio_entrada_riesgo * (1 + pct_stop / 100)
            )
        else:
            if not atr_val:
                st.warning('No hay ATR disponible para este activo/horizonte — cambiá a "Precio manual" o "% de distancia".')
                precio_stop = None
            else:
                precio_stop = sugerir_stop_atr(precio_entrada_riesgo, atr_val, direccion, multiplo_atr)

        if precio_stop is None:
            return

        stop_info = calcular_stop_loss(
            precio_entrada=precio_entrada_riesgo, precio_stop=precio_stop,
            cantidad=calc['cantidad_final'], apalancamiento=apalancamiento,
            direccion=direccion, capital_cuenta=capital_cuenta,
            precio_take_profit=precio_tp, atr=atr_val,
        )
    except ValueError as e:
        st.error(f'Error en la configuración del stop loss: {e}')
        return

    riesgo_stop = evaluar_riesgo_stop(stop_info, horizonte, pct_riesgo_max)

    sr1, sr2, sr3, sr4 = st.columns(4)
    with sr1:
        st.metric('Precio del Stop', f"${stop_info['precio_stop']:,.4f}", f"-{stop_info['distancia_stop_pct']:.2f}%")
    with sr2:
        st.metric('Pérdida si toca el stop', f"${stop_info['perdida_dinero']:,.2f}")
    with sr3:
        st.metric('Pérdida % del capital propio', f"{stop_info['perdida_pct_capital']:.1f}%" if stop_info['perdida_pct_capital'] is not None else 'N/D')
    with sr4:
        st.metric('Precio de liquidación (aprox.)', f"${stop_info['precio_liquidacion']:,.4f}" if apalancamiento > 1 else 'N/A (1x)')

    if stop_info['perdida_pct_cuenta'] is not None:
        st.metric('Pérdida % de tu cuenta total', f"{stop_info['perdida_pct_cuenta']:.2f}%")

    if stop_info['rr_ratio'] is not None:
        rr1, rr2 = st.columns(2)
        with rr1:
            st.metric('Ganancia potencial (TP)', f"${stop_info['ganancia_potencial']:,.2f}")
        with rr2:
            st.metric('Ratio Riesgo/Beneficio', f"{stop_info['rr_ratio']:.2f} : 1")

    if atr_val and stop_info['distancia_stop_en_atr'] is not None:
        st.caption(f"📏 ATR actual: {atr_val:.4f} · Tu stop está a {stop_info['distancia_stop_en_atr']:.2f} ATR de la entrada.")
        sugerido = sugerir_stop_atr(precio_entrada_riesgo, atr_val, direccion,
                                     1.5 if horizonte == 'corto' else 3.0)
        if sugerido:
            st.caption(f"💡 Stop sugerido por volatilidad ({'1.5' if horizonte=='corto' else '3.0'}×ATR, {direccion}): ${sugerido:,.4f}")

    color_stop = {'OK': '#3fb950', 'MEDIO': '#e3b341', 'ALTO': '#f85149'}.get(riesgo_stop['nivel'], '#3a7bd5')
    st.markdown(f"""
    <div style="background:#0d1117;border:1px solid #21262d;border-left:3px solid {color_stop};
         border-radius:8px;padding:14px 18px;margin:14px 0">
      <div style="font-size:13px;font-weight:700;color:{color_stop};margin-bottom:6px">
        Nivel de riesgo de la gestión: {riesgo_stop['nivel']}
      </div>
      <div style="font-size:12px;color:#f5f7fa;line-height:1.8">{'<br>• '.join([''] + riesgo_stop['avisos'])}</div>
    </div>
    """, unsafe_allow_html=True)

    # ── Veredicto combinado (tendencia + gestión de riesgo) ─────────────
    niveles_rank = {'BAJO': 0, 'OK': 0, 'MEDIO': 1, 'ALTO': 2, 'INVÁLIDO': 3}
    peor = max(resultado['riesgo'], riesgo_stop['nivel'], key=lambda n: niveles_rank.get(n, 1))
    if peor == 'ALTO':
        veredicto_final = '🔴 Operación NO recomendada tal como está planteada: revisá tendencia, tamaño o stop.'
    elif peor == 'MEDIO':
        veredicto_final = '🟡 Operación posible, pero con puntos a mejorar (ver avisos arriba).'
    else:
        veredicto_final = '🟢 Operación viable: tendencia y gestión de riesgo razonablemente alineadas.'

    st.markdown(f"""
    <div style="background:#0d1117;border:2px solid {color_stop if peor==riesgo_stop['nivel'] else color_riesgo};
         border-radius:10px;padding:16px 20px;margin-top:6px;text-align:center">
      <div style="font-size:14px;font-weight:700;color:#e6edf3">{veredicto_final}</div>
    </div>
    """, unsafe_allow_html=True)

    st.caption('⚠️ Herramienta cuantitativa de apoyo, no asesoramiento financiero. El precio de liquidación '
               'es una aproximación (no incluye fees ni margen de mantenimiento del bróker/exchange).')
