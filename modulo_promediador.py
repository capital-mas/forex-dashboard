# ==============================================================
#  MÓDULO PROMEDIADOR — versión simple
#  Calcula precio promedio, tamaño de posición según tu riesgo,
#  tendencia y stop loss/apalancamiento — todo explicado en criollo.
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
        return round(precio_entrada - multiplo * atr, 4)
    return round(precio_entrada + multiplo * atr, 4)


def calcular_tamano_posicion(capital, pct_riesgo, precio_entrada, precio_stop, apalancamiento=1.0):
    """
    LA CUENTA MÁS IMPORTANTE DE TODAS: cuánto podés comprar sin romper tu regla de riesgo.
    Fórmula: (capital × % que estás dispuesto a perder) / (distancia en $ hasta el stop).
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


def evaluar_riesgo_stop(stop_info, horizonte='largo', pct_riesgo_max_cuenta=2.0):
    """Traduce los números del stop-loss a avisos en criollo + nivel de riesgo (OK/MEDIO/ALTO)."""
    avisos, nivel = [], 'OK'

    if stop_info['perdida_pct_cuenta'] is not None:
        if stop_info['perdida_pct_cuenta'] > pct_riesgo_max_cuenta * 2:
            nivel = 'ALTO'
            avisos.append(f"Si te toca el stop, perdés {stop_info['perdida_pct_cuenta']:.1f}% de TODA tu cuenta "
                           f"— muy por encima del {pct_riesgo_max_cuenta:.0f}% que dijiste que ibas a arriesgar. "
                           f"La posición es demasiado grande para tu capital.")
        elif stop_info['perdida_pct_cuenta'] > pct_riesgo_max_cuenta:
            nivel = 'MEDIO' if nivel == 'OK' else nivel
            avisos.append(f"Si te toca el stop, perdés {stop_info['perdida_pct_cuenta']:.1f}% de tu cuenta, "
                           f"un poco por encima del {pct_riesgo_max_cuenta:.0f}% que te propusiste.")
        else:
            avisos.append(f"Si te toca el stop, perdés {stop_info['perdida_pct_cuenta']:.1f}% de tu cuenta — "
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


def _fig_tendencia(info):
    cl = info['serie']
    color_tend = {'ALCISTA': '#3fb950', 'BAJISTA': '#f85149', 'LATERAL': '#e3b341'}.get(info['tendencia'], '#3a7bd5')
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=cl.index, y=cl, name='Precio', line=dict(color=color_tend, width=2)))
    if info.get('motor') == 'analizar_largo':
        ma50, ma200 = cl.rolling(50).mean(), cl.rolling(200).mean()
        fig.add_trace(go.Scatter(x=ma50.index, y=ma50, name='Media 50 sesiones', line=dict(color='#3fb950', width=1.3)))
        fig.add_trace(go.Scatter(x=ma200.index, y=ma200, name='Media 200 sesiones', line=dict(color='#f85149', width=1.3)))
        titulo = f"{info['ticker']} · {info['sesgo']}"
    elif info.get('motor') == 'corto_plazo':
        ma7, ma20 = cl.rolling(7).mean(), cl.rolling(20).mean()
        fig.add_trace(go.Scatter(x=ma7.index, y=ma7, name='Media 7 sesiones', line=dict(color='#e3b341', width=1.2, dash='dot')))
        fig.add_trace(go.Scatter(x=ma20.index, y=ma20, name='Media 20 sesiones', line=dict(color='#3a7bd5', width=1.3)))
        titulo = f"{info['ticker']} · Corto plazo · {info['tendencia']}"
    else:
        ma_c, ma_l = info['ma_corta'], info['ma_larga']
        fig.add_trace(go.Scatter(x=ma_c.index, y=ma_c, name=f"MA{info['ventana_corta']}", line=dict(color='#e3b341', width=1.3, dash='dash')))
        fig.add_trace(go.Scatter(x=ma_l.index, y=ma_l, name=f"MA{info['ventana_larga']}", line=dict(color='#3a7bd5', width=1.3)))
        titulo = f"{info['ticker']} · {info['tendencia']}"
    fig.update_layout(
        plot_bgcolor='#0d1117', paper_bgcolor='#07090f',
        font=dict(color='#b0bcd0', family='Inter, sans-serif'),
        title=dict(text=titulo, font=dict(color='#e6edf3', size=13)),
        xaxis=dict(gridcolor='#21262d'), yaxis=dict(gridcolor='#21262d'),
        height=360, hovermode='x unified', legend=dict(orientation='h', y=1.1),
        margin=dict(l=10, r=10, t=45, b=10),
    )
    return fig


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
    ('% que arriesgo por operación', 'Cuánto de tu cuenta total estás dispuesto a perder si la operación sale mal. '
     'La regla clásica de trading dice no arriesgar más del 1-2% de tu cuenta en una sola operación.'),
    ('Stop Loss', 'El precio al que vas a vender (o cerrar la posición) automáticamente si el precio va en tu contra, '
     'para cortar la pérdida antes de que sea mayor.'),
    ('ATR', 'Mide cuánto se mueve el precio de un activo en un día normal (su volatilidad). '
     'Un stop basado en ATR se adapta a cada activo, en vez de usar el mismo % para todos.'),
    ('Apalancamiento', 'Operar con más dinero del que tenés, pedido "prestado" por el bróker/exchange. '
     'Multiplica tanto las ganancias como las pérdidas — con 10x, un movimiento de 10% en tu contra puede '
     'liquidar toda tu posición.'),
    ('Precio de liquidación', 'El precio al que el bróker/exchange te cierra la posición por la fuerza porque '
     'perdiste todo el margen que pusiste. Cuanto más apalancamiento, más cerca está de tu precio de entrada.'),
    ('Cantidad recomendada', 'Cuánto podés comprar/vender sin superar el % de tu cuenta que dijiste que ibas '
     'a arriesgar, dado dónde pusiste el stop. Es el "tamaño correcto" de la operación.'),
    ('Ratio Riesgo/Beneficio', 'Compara cuánto podés perder contra cuánto podés ganar. Un ratio de 2:1 significa '
     'que por cada $1 que arriesgás, tu objetivo es ganar $2.'),
]


# ==============================================================
#  4) MÓDULO STREAMLIT — flujo simple
# ==============================================================

def modulo_promediador(analizar_largo=None, descargar_datos=None, get_close_series=None,
                        calcular_atr=None, scores_corto=None, señal_accion_corto=None):
    usa_motor_largo = all([analizar_largo, descargar_datos, get_close_series])
    usa_motor_corto = all([descargar_datos, get_close_series, scores_corto, señal_accion_corto])

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #6CC24A;
         border-radius:14px; padding:24px 28px; margin-bottom:20px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">
        📐 Promediador + Riesgo (versión simple)
      </div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.8">
        Cómo funciona en 4 pasos: <b style="color:#e6edf3">1)</b> Decís cuánta plata tenés y cuánto estás
        dispuesto a arriesgar. <b style="color:#e6edf3">2)</b> Cargás la operación. <b style="color:#e6edf3">3)</b>
        Elegís tu stop loss. <b style="color:#e6edf3">4)</b> La herramienta te dice el <u>tamaño correcto</u>
        de la operación, si la tendencia acompaña, y si el riesgo es razonable.
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Paso 1: activo y capital ────────────────────────────────────────
    st.markdown('#### 1️⃣ Activo, horizonte y tu capital')
    c1, c2 = st.columns([2, 1])
    with c1:
        ticker = st.text_input('Ticker', value='', placeholder='Ej: NVDA, GGAL, BTC-USD, EURUSD=X',
                                key='prom_ticker').strip().upper()
    with c2:
        horizonte_label = st.radio('Horizonte', ['📈 Largo Plazo', '⚡ Corto Plazo'],
                                    horizontal=True, key='prom_horizonte')
        horizonte = 'largo' if 'Largo' in horizonte_label else 'corto'

    cc1, cc2 = st.columns(2)
    with cc1:
        capital_cuenta = st.number_input(
            'Capital total de tu cuenta (USD)', min_value=1.0, value=1000.0, step=100.0,
            key='prom_capital_cuenta',
            help='Todo tu dinero disponible para operar, no solo lo que vas a poner en esta operación.',
        )
    with cc2:
        pct_riesgo_max = st.number_input(
            '% de tu cuenta que estás dispuesto a perder en ESTA operación',
            min_value=0.1, max_value=20.0, value=2.0, step=0.5, key='prom_pct_riesgo_max',
            help='Regla clásica: 1-2%. Así, aunque tengas varias operaciones perdedoras seguidas, no te vaciás la cuenta.',
        )
    st.caption(f'👉 Con estos datos, estás dispuesto a perder hasta **${capital_cuenta * pct_riesgo_max / 100:,.2f}** en esta operación si te toca el stop.')

    # ── Paso 2: la operación ────────────────────────────────────────────
    st.markdown('#### 2️⃣ La operación')
    o1, o2, o3 = st.columns(3)
    with o1:
        tipo_op = st.radio('¿Comprás o vendés?', ['Comprar', 'Vender parcial'], key='prom_tipo_op')
    with o2:
        direccion_label = st.radio('Dirección', ['Long (al alza)', 'Short (a la baja)'],
                                    index=0 if tipo_op == 'Comprar' else 1, key='prom_direccion')
        direccion = 'long' if direccion_label.startswith('Long') else 'short'
    with o3:
        apalancamiento = st.number_input('Apalancamiento (x)', min_value=1.0, max_value=125.0,
                                          value=1.0, step=1.0, key='prom_apalancamiento',
                                          help='Dejalo en 1 si comprás con tu propia plata, sin margen ni futuros.')

    precio_nuevo = st.number_input('Precio al que operás ahora (USD)', min_value=0.0001, value=1.0,
                                    step=0.01, format='%.4f', key='prom_precio_nuevo')

    tiene_posicion = st.checkbox('¿Ya tenés una posición abierta en este activo? (para promediar)',
                                  key='prom_tiene_posicion')
    cant_actual, precio_prom_actual = 0.0, 0.0
    if tiene_posicion:
        p1, p2 = st.columns(2)
        with p1:
            cant_actual = st.number_input('Cantidad que ya tenés', min_value=0.0, value=1.0,
                                           step=1.0, key='prom_cant_actual')
        with p2:
            precio_prom_actual = st.number_input('Precio promedio actual', min_value=0.0, value=1.0,
                                                  step=0.01, format='%.4f', key='prom_precio_actual')

    cant_op = st.number_input(
        'Cantidad de la operación', min_value=0.0001, value=1.0, step=1.0, key='prom_cant_op',
        help='Podés dejarla en cualquier valor: más abajo te vamos a mostrar cuál sería el tamaño recomendado.',
    )
    cant_nueva = cant_op if tipo_op == 'Comprar' else -cant_op

    # ── Paso 3: stop loss ────────────────────────────────────────────────
    st.markdown('#### 3️⃣ Tu Stop Loss (dónde cortás la pérdida)')
    modo_stop = st.selectbox(
        '¿Cómo lo definís?',
        ['Múltiplo de ATR (recomendado — se adapta a la volatilidad del activo)',
         '% de distancia del precio', 'Precio manual'],
        key='prom_modo_stop',
    )
    if modo_stop.startswith('Múltiplo'):
        multiplo_atr = st.number_input('Múltiplo de ATR', min_value=0.5, max_value=10.0,
                                        value=1.5 if horizonte == 'corto' else 3.0, step=0.5,
                                        key='prom_stop_atr_mult')
        precio_stop_manual = pct_stop = None
    elif modo_stop.startswith('%'):
        pct_stop = st.number_input('% de distancia del stop', min_value=0.1, max_value=90.0, value=5.0,
                                    step=0.5, key='prom_stop_pct')
        precio_stop_manual = multiplo_atr = None
    else:
        precio_stop_manual = st.number_input('Precio del stop loss', min_value=0.0001,
                                              value=round(precio_nuevo * 0.95, 4),
                                              step=0.01, format='%.4f', key='prom_stop_manual')
        pct_stop = multiplo_atr = None

    with st.expander('➕ Opcional: Take Profit (para ver ratio riesgo/beneficio)'):
        usar_tp = st.checkbox('Definir un precio objetivo de ganancia', key='prom_usar_tp')
        precio_tp = None
        if usar_tp:
            precio_tp = st.number_input('Precio del Take Profit', min_value=0.0001,
                                         value=round(precio_nuevo * 1.10, 4), step=0.01,
                                         format='%.4f', key='prom_tp')

    # ── Paso 4: calcular ─────────────────────────────────────────────────
    st.markdown('#### 4️⃣ Resultado')
    analizar = st.button('▶ Calcular todo', key='prom_run', type='primary', use_container_width=True)
    if not analizar:
        return
    if not ticker:
        st.warning('Ingresá un ticker para poder analizar la tendencia.')
        return

    with st.spinner(f'Analizando {ticker}...'):
        try:
            if horizonte == 'largo' and usa_motor_largo:
                info_tend = detectar_tendencia_largo(ticker, analizar_largo, descargar_datos, get_close_series, calcular_atr)
            elif horizonte == 'corto' and usa_motor_corto:
                info_tend = detectar_estado_corto(ticker, descargar_datos, get_close_series, calcular_atr, scores_corto, señal_accion_corto)
            else:
                info_tend = detectar_tendencia_standalone(ticker, '6mo', horizonte)
        except Exception as e:
            st.error(f'No se pudo analizar la tendencia: {e}')
            info_tend = None

    if info_tend is None:
        st.warning(f'No hay datos suficientes para {ticker}. Verificá el símbolo.')
        return

    atr_val = info_tend.get('atr')
    try:
        if modo_stop.startswith('Múltiplo'):
            if not atr_val:
                st.warning('No hay suficiente volatilidad calculable para este activo — probá con "% de distancia" o "Precio manual".')
                return
            precio_stop = sugerir_stop_atr(precio_nuevo, atr_val, direccion, multiplo_atr)
        elif modo_stop.startswith('%'):
            precio_stop = precio_nuevo * (1 - pct_stop / 100) if direccion == 'long' else precio_nuevo * (1 + pct_stop / 100)
        else:
            precio_stop = precio_stop_manual
    except Exception as e:
        st.error(f'Error definiendo el stop: {e}')
        return

    # ── Tamaño de posición recomendado (ANTES de mostrar el resto) ──────
    tam = calcular_tamano_posicion(capital_cuenta, pct_riesgo_max, precio_nuevo, precio_stop, apalancamiento)
    if tam:
        st.markdown('##### 📏 ¿Qué tamaño debería tener esta operación?')
        t1, t2, t3 = st.columns(3)
        with t1:
            st.metric('Podés arriesgar hasta', f"${tam['dinero_a_arriesgar']:,.2f}")
        with t2:
            st.metric('Cantidad recomendada', f"{tam['cantidad_sugerida']:.6g}")
        with t3:
            st.metric('Cantidad que cargaste', f"{cant_op:.6g}")

        ratio_tam = cant_op / tam['cantidad_sugerida'] if tam['cantidad_sugerida'] > 0 else None
        if ratio_tam and ratio_tam > 1.5:
            st.error(f"🔴 Cargaste **{ratio_tam:.1f} veces más** de lo que tu regla de riesgo permite con este stop. "
                     f"Si te toca el stop, vas a perder mucho más del {pct_riesgo_max:.0f}% que definiste.")
            if st.button('✅ Usar la cantidad recomendada y recalcular', key='prom_usar_sugerida'):
                st.session_state['prom_cant_op'] = round(tam['cantidad_sugerida'], 6)
                st.rerun()
        elif ratio_tam and ratio_tam < 0.5:
            st.info('🔵 Estás usando bastante menos de lo que tu riesgo permitiría — está bien si preferís ir con cautela.')
        else:
            st.success('🟢 El tamaño que cargaste está cerca de lo recomendado para tu nivel de riesgo.')
        st.caption('Esta cantidad recomendada surge de: (capital × % de riesgo) ÷ (distancia en $ hasta tu stop).')

    st.markdown('---')

    # ── Promedio ─────────────────────────────────────────────────────
    try:
        resultado = evaluar_operacion(cant_actual, precio_prom_actual, cant_nueva, precio_nuevo, info_tend)
    except ValueError as e:
        st.error(f'Error en los datos de la posición: {e}')
        return
    calc = resultado['calculo']
    if calc.get('venta_excede_posicion'):
        st.error(resultado['veredicto'])
        return

    st.markdown('##### 🧮 Tu precio promedio')
    k1, k2 = st.columns(2)
    with k1:
        st.metric('Cantidad total después de esta operación', f"{calc['cantidad_final']:,.4g}")
    with k2:
        st.metric('Precio promedio nuevo', f"${calc['precio_promedio_final']:,.4f}",
                   f"{calc['variacion_precio_prom_pct']:+.2f}%" if calc['variacion_precio_prom_pct'] is not None else None)

    st.markdown('##### 🧭 ¿La tendencia acompaña?')
    color_riesgo = {'BAJO': '#3fb950', 'MEDIO': '#e3b341', 'ALTO': '#f85149'}.get(resultado['riesgo'], '#3a7bd5')
    st.markdown(f"""
    <div style="background:#0d1117;border:1px solid #21262d;border-left:3px solid {color_riesgo};
         border-radius:8px;padding:14px 18px;margin-bottom:14px">
      <div style="font-size:13px;font-weight:700;color:{color_riesgo};margin-bottom:6px">{resultado['veredicto']}</div>
      <div style="font-size:12px;color:#f5f7fa;line-height:1.8">{'<br>• '.join([''] + resultado['razones'])}</div>
    </div>
    """, unsafe_allow_html=True)

    t1, t2, t3 = st.columns(3)
    with t1:
        st.metric('Tendencia', info_tend.get('sesgo') or info_tend['tendencia'])
    with t2:
        st.metric('RSI', f"{info_tend['rsi']:.1f}")
    with t3:
        st.metric('Precio actual del mercado', f"${info_tend['precio_actual']:,.4f}")
    st.plotly_chart(_fig_tendencia(info_tend), use_container_width=True, config=dict(displayModeBar=False, scrollZoom=False))

    # ── Stop loss final (con la cantidad que quedó cargada) ────────────
    st.markdown('---')
    st.markdown('##### 🛡️ Tu Stop Loss, en números')
    try:
        stop_info = calcular_stop_loss(
            precio_entrada=precio_nuevo, precio_stop=precio_stop, cantidad=calc['cantidad_final'],
            apalancamiento=apalancamiento, direccion=direccion, capital_cuenta=capital_cuenta,
            precio_take_profit=precio_tp, atr=atr_val,
        )
    except ValueError as e:
        st.error(f'Error en el stop loss: {e}')
        return

    riesgo_stop = evaluar_riesgo_stop(stop_info, horizonte, pct_riesgo_max)
    sr1, sr2, sr3, sr4 = st.columns(4)
    with sr1:
        st.metric('Precio del Stop', f"${stop_info['precio_stop']:,.4f}", f"-{stop_info['distancia_stop_pct']:.2f}%")
    with sr2:
        st.metric('Si te toca el stop, perdés', f"${stop_info['perdida_dinero']:,.2f}")
    with sr3:
        st.metric('Eso es, de tu cuenta total', f"{stop_info['perdida_pct_cuenta']:.1f}%" if stop_info['perdida_pct_cuenta'] is not None else 'N/D')
    with sr4:
        st.metric('Precio de liquidación aprox.', f"${stop_info['precio_liquidacion']:,.4f}" if apalancamiento > 1 else 'No aplica (1x)')

    if stop_info['rr_ratio'] is not None:
        rr1, rr2 = st.columns(2)
        with rr1:
            st.metric('Si llegás al Take Profit, ganás', f"${stop_info['ganancia_potencial']:,.2f}")
        with rr2:
            st.metric('Por cada $1 arriesgado, buscás ganar', f"${stop_info['rr_ratio']:.2f}")

    color_stop = {'OK': '#3fb950', 'MEDIO': '#e3b341', 'ALTO': '#f85149'}.get(riesgo_stop['nivel'], '#3a7bd5')
    st.markdown(f"""
    <div style="background:#0d1117;border:1px solid #21262d;border-left:3px solid {color_stop};
         border-radius:8px;padding:14px 18px;margin:14px 0">
      <div style="font-size:13px;font-weight:700;color:{color_stop};margin-bottom:6px">
        Riesgo de esta gestión: {riesgo_stop['nivel']}
      </div>
      <div style="font-size:12px;color:#f5f7fa;line-height:1.8">{'<br>• '.join([''] + riesgo_stop['avisos'])}</div>
    </div>
    """, unsafe_allow_html=True)

    # ── Veredicto combinado ─────────────────────────────────────────────
    niveles_rank = {'BAJO': 0, 'OK': 0, 'MEDIO': 1, 'ALTO': 2, 'INVÁLIDO': 3}
    peor = max(resultado['riesgo'], riesgo_stop['nivel'], key=lambda n: niveles_rank.get(n, 1))
    if peor == 'ALTO':
        veredicto_final = '🔴 Esta operación, tal como está planteada, NO es recomendable. Revisá el tamaño o el stop.'
    elif peor == 'MEDIO':
        veredicto_final = '🟡 Es una operación posible, pero con puntos para mejorar (mirá los avisos de arriba).'
    else:
        veredicto_final = '🟢 Operación razonable: la tendencia y el manejo de riesgo están alineados.'
    st.markdown(f"""
    <div style="background:#0d1117;border:2px solid {color_stop};border-radius:10px;
         padding:16px 20px;margin-top:6px;text-align:center">
      <div style="font-size:14px;font-weight:700;color:#e6edf3">{veredicto_final}</div>
    </div>
    """, unsafe_allow_html=True)

    with st.expander('❓ ¿Qué significa cada cosa? (glosario rápido)'):
        for termino, explicacion in GLOSARIO_PROM:
            st.markdown(f"<div style='margin:4px 0;font-size:12px'><b style='color:#6CC24A'>{termino}</b> "
                        f"— <span style='color:#8b949e'>{explicacion}</span></div>", unsafe_allow_html=True)

    st.caption('⚠️ Herramienta de apoyo cuantitativo, no asesoramiento financiero. El precio de liquidación '
               'es aproximado (no incluye fees ni margen de mantenimiento del bróker/exchange).')
