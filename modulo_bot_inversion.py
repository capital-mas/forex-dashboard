# ==============================================================
#  MÓDULO BOT DE INVERSIÓN — Señales Fractal/Sentimiento/Z-Score/RSI
#  Versión intradía: temporalidades 5/15/30 min, 1h y 4h, multi-activo (hasta 10)
#  Portado desde el indicador Pine Script "Top-Down Cuantitativo
#  — Fractal + Sentimiento + Z-Score + RSI v15".
#
#  v2: se reemplaza el motor de Sentimiento+Anticipación por el
#      esquema de conteo del Pine v15: 4 condiciones por lado
#      (Fractal, Sentimiento, Z-Score, RSI). 4/4 cumplidas → señal
#      completa (equivalente a "100%"); 3/4 cumplidas → entrada
#      anticipada (equivalente a "50%"). Se mantiene el mismo
#      esquema de nombres de estado ('VENTA 100%'/'VENTA 50%'/etc.)
#      para no romper la tabla bot_señales_log ni el resto del
#      motor de seguimiento/rendimiento, que no se tocan.
#
#  v3: se agrega REBALANCEO (promediar en contra) y SIMULACIÓN DE
#      CAPITAL COMPUESTO:
#        - Rebalanceo: cuando una operación ACEPTADA avanza un %
#          configurable del camino hacia su Stop (no cuando lo
#          toca), se dispara una 2da entrada del 50% del capital
#          de la entrada original, al precio de ese momento. Se
#          recalcula un precio promedio ponderado por cantidad
#          (capital/precio) y, sobre ese promedio, un nuevo
#          Stop/TP usando los MISMOS % configurados originalmente
#          para esa señal (100% o 50%).
#        - Capital compuesto: al ACEPTAR una señal, el tamaño de
#          esa entrada (capital_original_usd) se calcula como
#          % de operación sobre el capital ACTUAL (resultado de
#          todas las operaciones aceptadas y cerradas hasta ese
#          momento), no sobre el capital inicial fijo. Así el
#          tamaño de cada entrada "se va moviendo" con el capital.
#
#      Requiere columnas nuevas en bot_señales_log (ver el bloque
#      SQL al final de este archivo, en el comentario MIGRACIÓN).
# ==============================================================

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

MAX_ACTIVOS_BOT = 10

# yfinance permite hasta 60 días de historia para velas de 5m/15m/30m,
# y hasta 730 días para velas de 60m. No existe intervalo nativo de 4h:
# se arma resampleando velas de 60m (agrupando OHLC de a 4 en 4).
HORIZONTES_BOT = {
    '5 minutos': dict(
        interval='5m', periodo_descarga='60d', resample=None, minutos_vela=5,
        ventana_valor=560, rsi_periodo=14,
    ),
    '15 minutos': dict(
        interval='15m', periodo_descarga='60d', resample=None, minutos_vela=15,
        ventana_valor=380, rsi_periodo=14,
    ),
    '30 minutos': dict(
        interval='30m', periodo_descarga='60d', resample=None, minutos_vela=30,
        ventana_valor=250, rsi_periodo=14,
    ),
    '1 hora': dict(
        interval='60m', periodo_descarga='730d', resample=None, minutos_vela=60,
        ventana_valor=180, rsi_periodo=14,
    ),
    '4 horas': dict(
        interval='60m', periodo_descarga='730d', resample='4h', minutos_vela=240,
        ventana_valor=120, rsi_periodo=14,
    ),
}

C_BOT_VENTA_100  = '#f85149'
C_BOT_VENTA_50   = '#f0883e'
C_BOT_COMPRA_100 = '#3fb950'
C_BOT_COMPRA_50  = '#2dd4bf'
C_BOT_REBALANCEO = '#a371f7'


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


def _rolling_percentrank(s, length):
    """Equivalente a ta.percentrank de Pine: % de las barras anteriores
    (dentro de la ventana) que son menores al valor actual."""
    min_p = max(5, length // 4)

    def _r(x):
        return (x < x[-1]).sum() / len(x) * 100

    return s.rolling(length, min_periods=min_p).apply(_r, raw=True)


def _pivote_confirmado(serie, izq, der, modo='max'):
    """Equivalente a ta.pivothigh/ta.pivotlow de Pine: True en la barra donde
    se confirma un pivote (techo si modo='max', piso si modo='min'), usando
    'izq' barras a la izquierda y 'der' barras a la derecha. La confirmación
    aparece 'der' barras después del pico real (igual que en Pine, donde el
    fractal 'tarda' en confirmarse)."""
    ventana = izq + der + 1
    roll = serie.rolling(ventana, min_periods=ventana).max() if modo == 'max' \
        else serie.rolling(ventana, min_periods=ventana).min()
    # roll, evaluado en la posición i+der, es el máximo/mínimo de la ventana
    # [i-izq, i+der]. shift(-der) lo trae a la posición i, y comparándolo con
    # serie[i] sabemos si i es el pico. shift(der) recién publica ese dato
    # 'der' barras más tarde, que es cuando de verdad se puede confirmar.
    es_pivote = serie == roll.shift(-der)
    confirmado = es_pivote.shift(der)
    return confirmado.fillna(False).astype(bool)


def _calcular_bot_dataframe(close, high, low, cfg,
                             sent_min_compra, sent_max_compra, sent_min_venta, sent_max_venta,
                             zscore_periodo, zscore_umbral,
                             rsi_nivel_venta, rsi_nivel_compra,
                             fractal_izq, fractal_der,
                             stop_pct_100, stop_pct_50, tp_pct_100, tp_pct_50):
    """Cálculo puro (sin caché): es liviano — unas pocas rolling windows sobre
    unos cientos de velas — así que no vale la pena cachearlo, y cachearlo mal
    (por ticker) es justamente lo que rompía el análisis multi-activo.

    4 condiciones por lado, evaluadas en la barra actual:
      Fractal (pivote confirmado), Sentimiento (percentil de precio dentro
      de rango), Z-Score (± umbral), RSI (nivel de sobrecompra/sobreventa).
      4/4 → señal completa ('...100%'). 3/4 → entrada anticipada ('...50%')."""
    cl = close.dropna()
    hi = high.reindex(cl.index)
    lo = low.reindex(cl.index)

    sc_sent = _rolling_percentrank(cl, cfg['ventana_valor'])
    rsi_valor = _rsi_sma(cl, cfg['rsi_periodo'])

    z_media = cl.rolling(zscore_periodo).mean()
    z_std = cl.rolling(zscore_periodo).std()
    zscore = (cl - z_media) / z_std.replace(0, np.nan)

    fractal_top = _pivote_confirmado(hi, fractal_izq, fractal_der, modo='max')
    fractal_bottom = _pivote_confirmado(lo, fractal_izq, fractal_der, modo='min')

    sent_venta_ok  = (sc_sent >= sent_min_venta)  & (sc_sent <= sent_max_venta)
    sent_compra_ok = (sc_sent >= sent_min_compra) & (sc_sent <= sent_max_compra)
    z_venta_ok  = zscore >= zscore_umbral
    z_compra_ok = zscore <= -zscore_umbral
    rsi_venta_ok  = rsi_valor >= rsi_nivel_venta
    rsi_compra_ok = rsi_valor <= rsi_nivel_compra

    count_venta = (fractal_top.astype(int) + sent_venta_ok.astype(int)
                   + z_venta_ok.astype(int) + rsi_venta_ok.astype(int))
    count_compra = (fractal_bottom.astype(int) + sent_compra_ok.astype(int)
                     + z_compra_ok.astype(int) + rsi_compra_ok.astype(int))

    pct_venta = pd.Series(0.0, index=cl.index)
    pct_venta[count_venta == 4] = 100.0
    pct_venta[count_venta == 3] = 50.0

    pct_compra = pd.Series(0.0, index=cl.index)
    pct_compra[count_compra == 4] = 100.0
    pct_compra[count_compra == 3] = 50.0

    estado = pd.Series('—', index=cl.index)
    estado[pct_venta == 100] = 'VENTA 100%'
    estado[pct_venta == 50] = 'VENTA 50%'
    estado[pct_compra == 100] = 'COMPRA 100%'
    estado[pct_compra == 50] = 'COMPRA 50%'
    disparo = (estado != '—') & (estado != estado.shift(1))

    df = pd.DataFrame({
        'precio': cl, 'sc_sent': sc_sent, 'zscore': zscore, 'rsi': rsi_valor,
        'fractal_top': fractal_top, 'fractal_bottom': fractal_bottom,
        'count_venta': count_venta, 'count_compra': count_compra,
        'pct_venta': pct_venta, 'pct_compra': pct_compra,
        'estado': estado, 'disparo': disparo,
    })
    df['stop'] = np.select(
        [df['pct_venta'] == 100, df['pct_venta'] == 50, df['pct_compra'] == 100, df['pct_compra'] == 50],
        [df['precio'] * (1 + stop_pct_100 / 100), df['precio'] * (1 + stop_pct_50 / 100),
         df['precio'] * (1 - stop_pct_100 / 100), df['precio'] * (1 - stop_pct_50 / 100)],
        default=np.nan,
    )
    # Take Profit: dirección opuesta al stop (venta → objetivo abajo, compra → objetivo arriba)
    df['tp'] = np.select(
        [df['pct_venta'] == 100, df['pct_venta'] == 50, df['pct_compra'] == 100, df['pct_compra'] == 50],
        [df['precio'] * (1 - tp_pct_100 / 100), df['precio'] * (1 - tp_pct_50 / 100),
         df['precio'] * (1 + tp_pct_100 / 100), df['precio'] * (1 + tp_pct_50 / 100)],
        default=np.nan,
    )
    df['high'] = hi
    df['low'] = lo
    return df

def _evaluar_resultados_señales(df, hi, lo):
    """Para cada señal disparada, mira hacia adelante en las velas siguientes
    y determina si el precio tocó primero el Take Profit (✅) o el Stop (❌).
    Si todavía no tocó ninguno de los dos, queda '⏳ En curso'.

    NOTA: esta evaluación es la del historial "en vivo" del gráfico (no toca
    Supabase) y usa siempre el Stop/TP originales de la señal — no conoce el
    rebalanceo, que solo aplica a operaciones ACEPTADAS y se calcula aparte
    contra bot_señales_log (ver _bot_chequear_rebalanceos más abajo). Si en tu
    operativa real usás el stop como gatillo para una segunda entrada
    (promediar) en vez de cerrar la posición, la ❌ de esta tabla no equivale
    necesariamente a "perdiste la operación" — es solo "el precio llegó
    primero a tu nivel de stop original"."""
    df = df.copy()
    n = len(df)
    resultado = [''] * n
    precio_resultado = [np.nan] * n
    barras_hasta = [np.nan] * n

    hi_arr = hi.reindex(df.index).values
    lo_arr = lo.reindex(df.index).values
    estado_arr = df['estado'].values
    disparo_arr = df['disparo'].values
    tp_arr = df['tp'].values
    sl_arr = df['stop'].values

    for i in range(n):
        if not disparo_arr[i] or estado_arr[i] == '—' or pd.isna(tp_arr[i]) or pd.isna(sl_arr[i]):
            continue
        es_venta = 'VENTA' in estado_arr[i]
        tp, sl = tp_arr[i], sl_arr[i]
        encontrado = False
        for j in range(i + 1, n):
            hi_j, lo_j = hi_arr[j], lo_arr[j]
            if es_venta:
                toco_tp, toco_sl = lo_j <= tp, hi_j >= sl
            else:
                toco_tp, toco_sl = hi_j >= tp, lo_j <= sl
            if toco_tp and toco_sl:
                # Ambas se tocaron en la misma vela: no se puede saber cuál fue
                # primero con datos OHLC diarios/intradía estándar. Se asume el
                # escenario conservador (perdedor) para no sobreestimar aciertos.
                resultado[i], precio_resultado[i], barras_hasta[i] = '❌', sl, j - i
                encontrado = True
                break
            elif toco_tp:
                resultado[i], precio_resultado[i], barras_hasta[i] = '✅', tp, j - i
                encontrado = True
                break
            elif toco_sl:
                resultado[i], precio_resultado[i], barras_hasta[i] = '❌', sl, j - i
                encontrado = True
                break
        if not encontrado:
            resultado[i] = '⏳'

    df['resultado'] = resultado
    df['precio_resultado'] = precio_resultado
    df['barras_hasta_resultado'] = barras_hasta
    return df


def _color_resultado(val):
    return {'✅': 'color:#3fb950;font-weight:700', '❌': 'color:#f85149;font-weight:700',
            '⏳': 'color:#e3b341;font-weight:600'}.get(val, '')

# ── Persistencia en Supabase: configuración, registro y decisiones ────

def _bot_obtener_config(supabase, user_id):
    try:
        res = supabase.table('bot_config_usuario').select('*').eq('user_id', user_id).limit(1).execute()
        if res.data:
            return res.data[0]
    except Exception:
        pass
    return {'capital_inicial': 10000.0, 'pct_por_operacion': 10.0, 'minutos_limite_decision': 10}


def _bot_guardar_config(supabase, user_id, capital_inicial, pct_por_operacion, minutos_limite):
    try:
        supabase.table('bot_config_usuario').upsert({
            'user_id': user_id, 'capital_inicial': capital_inicial,
            'pct_por_operacion': pct_por_operacion, 'minutos_limite_decision': minutos_limite,
            'actualizado_en': datetime.now().isoformat(),
        }).execute()
    except Exception:
        pass


def _bot_registrar_señales_nuevas(supabase, user_id, ticker, horizonte, df_bot, minutos_limite,
                                    stop_pct_100, stop_pct_50, tp_pct_100, tp_pct_50):
    """Inserta las señales recién disparadas que todavía no estén logueadas.
    Se intenta insertar una por una y se ignora el error si ya existe (gracias
    al UNIQUE de la tabla) — así nunca se pisa una decisión ya tomada.

    Además de los campos originales, guarda 'stop_pct_usado' y 'tp_pct_usado'
    (el % configurado que corresponde a esa señal, 100% o 50%): son los que
    se van a reaplicar sobre el precio promedio el día que la operación se
    rebalancee, para que el nuevo Stop/TP respete los mismos % originales."""
    disparos = df_bot[df_bot['disparo'] & (df_bot['estado'] != '—')]
    for ts, row in disparos.iterrows():
        fecha_limite = ts.to_pydatetime() + pd.Timedelta(minutes=minutos_limite)
        es_100 = '100%' in row['estado']
        fila = {
            'user_id': user_id, 'ticker': ticker, 'horizonte': horizonte,
            'fecha_señal': ts.isoformat(), 'tipo_señal': row['estado'],
            'precio_entrada': float(row['precio']),
            'tp': float(row['tp']) if pd.notna(row['tp']) else None,
            'stop': float(row['stop']) if pd.notna(row['stop']) else None,
            'fecha_limite_decision': fecha_limite.isoformat(),
            'stop_pct_usado': float(stop_pct_100 if es_100 else stop_pct_50),
            'tp_pct_usado': float(tp_pct_100 if es_100 else tp_pct_50),
        }
        try:
            supabase.table('bot_señales_log').insert(fila).execute()
        except Exception:
            pass  # ya estaba registrada


def _bot_expirar_vencidas(supabase, user_id):
    """Marca como 'expirada' toda señal sin decisión cuya ventana ya pasó.
    Esto evita el sesgo de aceptar señales 'a toro pasado'."""
    try:
        ahora_iso = datetime.now().isoformat()
        supabase.table('bot_señales_log').update({'decision': 'expirada'}) \
            .eq('user_id', user_id).is_('decision', 'null') \
            .lt('fecha_limite_decision', ahora_iso).execute()
    except Exception:
        pass


def _bot_pendientes_decision(supabase, user_id):
    try:
        ahora_iso = datetime.now().isoformat()
        res = supabase.table('bot_señales_log').select('*') \
            .eq('user_id', user_id).is_('decision', 'null') \
            .gt('fecha_limite_decision', ahora_iso).order('fecha_señal', desc=True).execute()
        return res.data or []
    except Exception:
        return []


def _bot_obtener_equity_actual(supabase, user_id, capital_inicial, pct_por_operacion):
    """Devuelve el capital (equity) resultante de todas las operaciones
    aceptadas y ya cerradas hasta este momento. Se usa para dimensionar la
    PRÓXIMA entrada con el % de capital configurado — así el tamaño de cada
    operación se va moviendo junto con el capital (simulación de capital
    compuesto), en vez de quedar siempre atado al capital inicial fijo."""
    rend = _bot_calcular_rendimiento(supabase, user_id, capital_inicial, pct_por_operacion)
    return rend['capital_actual']


def _bot_decidir_señal(supabase, señal_id, decision,
                        capital_inicial=None, pct_por_operacion=None, user_id=None):
    """Guarda la decisión (aceptada/rechazada). Si se acepta, además calcula
    y guarda 'capital_original_usd' = % de operación sobre el capital ACTUAL
    (no el inicial fijo), que es lo que después usan el rebalanceo y el
    cálculo de rendimiento para dimensionar esta operación en particular."""
    payload = {'decision': decision, 'fecha_decision': datetime.now().isoformat()}
    if decision == 'aceptada' and None not in (capital_inicial, pct_por_operacion, user_id):
        equity_actual = _bot_obtener_equity_actual(supabase, user_id, capital_inicial, pct_por_operacion)
        capital_original = equity_actual * (pct_por_operacion / 100.0)
        payload['capital_original_usd'] = capital_original
        payload['capital_total_usd'] = capital_original  # se ajusta si más tarde se rebalancea
    try:
        supabase.table('bot_señales_log').update(payload).eq('id', señal_id).execute()
    except Exception:
        pass


def _bot_chequear_rebalanceos(supabase, user_id, ticker, horizonte, df_bot,
                                rebalanceo_umbral_pct, rebalanceo_pct_capital):
    """Recorre las señales ACEPTADAS de este ticker/horizonte que todavía no
    tienen resultado ni fueron rebalanceadas, y revisa vela por vela si el
    precio ya recorrió 'rebalanceo_umbral_pct' % de la distancia entre la
    entrada y el Stop (en contra) — NO espera a que el Stop se toque.

    Si se cumple, dispara una 2da entrada de tamaño
    'capital_original_usd' * rebalanceo_pct_capital/100, al precio de esa
    vela. Calcula el precio promedio ponderado por cantidad (capital/precio,
    igual que promediar acciones/contratos reales) y, sobre ese promedio,
    el nuevo Stop/TP reaplicando los MISMOS % configurados originalmente
    para esa señal (stop_pct_usado / tp_pct_usado)."""
    try:
        res = supabase.table('bot_señales_log').select('*') \
            .eq('user_id', user_id).eq('ticker', ticker).eq('horizonte', horizonte) \
            .eq('decision', 'aceptada').execute()
        candidatas = [f for f in (res.data or [])
                      if f.get('resultado') in (None, '⏳') and not f.get('rebalanceada')
                      and f.get('capital_original_usd') and f.get('stop_pct_usado') is not None
                      and f.get('tp_pct_usado') is not None and f.get('stop') is not None]
    except Exception:
        candidatas = []

    for fila in candidatas:
        ts_señal = pd.Timestamp(fila['fecha_señal'])
        velas_post = df_bot[df_bot.index > ts_señal]
        if velas_post.empty or 'precio' not in velas_post.columns:
            continue

        es_venta = 'VENTA' in fila['tipo_señal']
        p0 = fila['precio_entrada']
        stop0 = fila['stop']
        stop_pct_usado = fila['stop_pct_usado']
        tp_pct_usado = fila['tp_pct_usado']
        distancia_stop = abs(stop0 - p0)
        if distancia_stop == 0:
            continue

        for ts_v, row_v in velas_post.iterrows():
            precio_v = row_v.get('precio')
            if precio_v is None or pd.isna(precio_v):
                continue

            avance_pct = ((precio_v - p0) / distancia_stop * 100) if es_venta \
                else ((p0 - precio_v) / distancia_stop * 100)

            # Si el precio ya se fue de largo y tocó (o pasó) el Stop original
            # antes de llegar al umbral, no corresponde rebalancear: esa vela
            # ya la va a cerrar como ❌ el chequeo normal de resultado.
            if avance_pct >= 100:
                break

            if avance_pct >= rebalanceo_umbral_pct:
                capital_original = float(fila['capital_original_usd'])
                capital_rebalanceo = capital_original * (rebalanceo_pct_capital / 100.0)
                qty1 = capital_original / p0
                qty2 = capital_rebalanceo / precio_v
                precio_promedio = (capital_original + capital_rebalanceo) / (qty1 + qty2)
                if es_venta:
                    stop_final = precio_promedio * (1 + stop_pct_usado / 100)
                    tp_final = precio_promedio * (1 - tp_pct_usado / 100)
                else:
                    stop_final = precio_promedio * (1 - stop_pct_usado / 100)
                    tp_final = precio_promedio * (1 + tp_pct_usado / 100)
                try:
                    supabase.table('bot_señales_log').update({
                        'rebalanceada': True,
                        'precio_rebalanceo': float(precio_v),
                        'fecha_rebalanceo': ts_v.isoformat(),
                        'capital_rebalanceo_usd': float(capital_rebalanceo),
                        'capital_total_usd': float(capital_original + capital_rebalanceo),
                        'precio_promedio': float(precio_promedio),
                        'stop_final': float(stop_final),
                        'tp_final': float(tp_final),
                    }).eq('id', fila['id']).execute()
                except Exception:
                    pass
                break


def _bot_actualizar_resultados_aceptadas(supabase, user_id, ticker, horizonte, df_bot):
    """Para señales ACEPTADAS de este ticker/horizonte sin resultado aún,
    revisa las velas nuevas para ver si ya tocó TP o Stop.

    Si la operación fue rebalanceada, evalúa contra 'stop_final'/'tp_final'
    (calculados sobre el precio promedio) y solo mirando velas a partir del
    momento del rebalanceo; si no fue rebalanceada, evalúa contra el Stop/TP
    originales de la señal, como antes.

    IMPORTANTE: llamar esta función DESPUÉS de _bot_chequear_rebalanceos en
    cada pasada, para que una operación recién rebalanceada ya se evalúe
    contra su Stop/TP nuevo en la misma corrida."""
    try:
        res = supabase.table('bot_señales_log').select('*') \
            .eq('user_id', user_id).eq('ticker', ticker).eq('horizonte', horizonte) \
            .eq('decision', 'aceptada').execute()
        candidatas = [f for f in (res.data or []) if f.get('resultado') in (None, '⏳')]
    except Exception:
        candidatas = []

    for fila in candidatas:
        ts_señal = pd.Timestamp(fila['fecha_señal'])
        velas_post = df_bot[df_bot.index > ts_señal]
        if velas_post.empty:
            continue
        es_venta = 'VENTA' in fila['tipo_señal']

        if fila.get('rebalanceada'):
            tp, sl = fila.get('tp_final'), fila.get('stop_final')
            if fila.get('fecha_rebalanceo'):
                velas_post = velas_post[velas_post.index >= pd.Timestamp(fila['fecha_rebalanceo'])]
        else:
            tp, sl = fila.get('tp'), fila.get('stop')
        if tp is None or sl is None or velas_post.empty:
            continue

        for ts_v, row_v in velas_post.iterrows():
            hi_v, lo_v = row_v['high'], row_v['low']
            if es_venta:
                toco_tp, toco_sl = lo_v <= tp, hi_v >= sl
            else:
                toco_tp, toco_sl = hi_v >= tp, lo_v <= sl
            resultado = None
            if toco_tp and toco_sl:
                resultado = '❌'  # ambiguo en la misma vela → se asume el escenario conservador
            elif toco_tp:
                resultado = '✅'
            elif toco_sl:
                resultado = '❌'
            if resultado:
                try:
                    supabase.table('bot_señales_log').update({
                        'resultado': resultado,
                        'precio_resultado': float(tp if resultado == '✅' else sl),
                        'fecha_resultado': ts_v.isoformat(),
                    }).eq('id', fila['id']).execute()
                except Exception:
                    pass
                break

def _bot_pendientes_globales(supabase, user_id):
    """Devuelve los pares (ticker, horizonte) que tienen al menos una señal
    aceptada sin resultado todavía, sin importar si están en la selección
    actual del multiselect. Esto es lo que permite que el historial 'siga'
    aunque el usuario cambie de activos entre sesiones."""
    try:
        res = supabase.table('bot_señales_log').select('ticker, horizonte') \
            .eq('user_id', user_id).eq('decision', 'aceptada').execute()
        filas = res.data or []
    except Exception:
        return []
    pendientes_check = set()
    try:
        res2 = supabase.table('bot_señales_log').select('ticker, horizonte, resultado') \
            .eq('user_id', user_id).eq('decision', 'aceptada').execute()
        for f in (res2.data or []):
            if f.get('resultado') in (None, '⏳'):
                pendientes_check.add((f['ticker'], f['horizonte']))
    except Exception:
        pass
    return list(pendientes_check)


def _bot_actualizar_todos_los_pendientes(supabase, user_id, get_close_series,
                                           rebalanceo_umbral_pct, rebalanceo_pct_capital):
    """Recorre TODOS los tickers con señales aceptadas abiertas —estén o no
    en la selección actual— y les actualiza rebalanceo + resultado. Se llama
    siempre al entrar al módulo, así el historial no se 'traba' cuando el
    usuario deja de mirar un activo puntual."""
    pendientes = _bot_pendientes_globales(supabase, user_id)
    for ticker, horizonte in pendientes:
        cfg_h = HORIZONTES_BOT.get(horizonte)
        if cfg_h is None:
            continue
        df_raw = _descargar_intradia(ticker, cfg_h['periodo_descarga'], cfg_h['interval'])
        if cfg_h.get('resample'):
            df_raw = _resamplear_ohlc(df_raw, cfg_h['resample']) if df_raw is not None else None
        if df_raw is None or df_raw.empty:
            continue
        cl = get_close_series(df_raw)
        if cl is None or cl.empty:
            continue
        hi = df_raw['High'] if 'High' in df_raw.columns else cl
        lo = df_raw['Low'] if 'Low' in df_raw.columns else cl
        df_lite = pd.DataFrame({'precio': cl, 'high': hi, 'low': lo}).reindex(cl.index)
        _bot_chequear_rebalanceos(supabase, user_id, ticker, horizonte, df_lite,
                                    rebalanceo_umbral_pct, rebalanceo_pct_capital)
        _bot_actualizar_resultados_aceptadas(supabase, user_id, ticker, horizonte, df_lite)


def _bot_calcular_rendimiento(supabase, user_id, capital_inicial, pct_por_operacion):
    """Arma el rendimiento acumulado a partir de señales ACEPTADAS y con
    resultado ya definido (✅/❌). Las que siguen '⏳' no afectan el cálculo
    todavía — se muestran aparte como 'abiertas'.

    El tamaño de cada operación es 'capital_total_usd' (guardado al aceptar,
    y ajustado si se rebalanceó), NO un % fijo del capital inicial — así el
    capital operado en cada trade refleja el capital que había disponible en
    ESE momento (simulación de capital compuesto). El % de movimiento se
    calcula sobre el precio promedio (si hubo rebalanceo) o sobre el precio
    de entrada original."""
    try:
        res = supabase.table('bot_señales_log').select('*') \
            .eq('user_id', user_id).eq('decision', 'aceptada').order('fecha_señal').execute()
        filas = res.data or []
    except Exception:
        filas = []

    equity = capital_inicial
    curva = [{'fecha': 'Inicio', 'equity': capital_inicial}]
    cerradas = ganadoras = abiertas = rebalanceos = 0

    for fila in filas:
        if fila.get('rebalanceada'):
            rebalanceos += 1
        resultado = fila.get('resultado')
        precio_base = fila.get('precio_promedio') if fila.get('rebalanceada') else fila.get('precio_entrada')
        tp_base = fila.get('tp_final') if fila.get('rebalanceada') else fila.get('tp')
        stop_base = fila.get('stop_final') if fila.get('rebalanceada') else fila.get('stop')
        capital_operado = fila.get('capital_total_usd') or fila.get('capital_original_usd') \
            or (capital_inicial * (pct_por_operacion / 100.0))

        if resultado == '✅' and tp_base and precio_base:
            pct_mov = abs(tp_base - precio_base) / precio_base
            equity += capital_operado * pct_mov
            ganadoras += 1; cerradas += 1
        elif resultado == '❌' and stop_base and precio_base:
            pct_mov = abs(stop_base - precio_base) / precio_base
            equity -= capital_operado * pct_mov
            cerradas += 1
        else:
            abiertas += 1
            continue
        curva.append({'fecha': fila.get('fecha_resultado') or fila['fecha_señal'], 'equity': equity})

    return {
        'capital_inicial': capital_inicial, 'capital_actual': equity,
        'rendimiento_pct': (equity / capital_inicial - 1) * 100,
        'win_rate': (ganadoras / cerradas * 100) if cerradas > 0 else None,
        'cerradas': cerradas, 'ganadoras': ganadoras, 'perdedoras': cerradas - ganadoras,
        'abiertas': abiertas, 'total_señales': len(filas), 'curva': curva,
        'rebalanceos': rebalanceos,
    }


def _bot_rendimiento_por_ticker(supabase, user_id, capital_inicial, pct_por_operacion):
    """Mismo cálculo que _bot_calcular_rendimiento pero agrupado por ticker,
    para ver qué activos vienen aportando y cuáles restando."""
    try:
        res = supabase.table('bot_señales_log').select('*') \
            .eq('user_id', user_id).eq('decision', 'aceptada').order('fecha_señal').execute()
        filas = res.data or []
    except Exception:
        filas = []

    por_ticker = {}
    for fila in filas:
        tk = fila['ticker']
        d = por_ticker.setdefault(tk, {'aporte_usd': 0.0, 'ganadoras': 0, 'perdedoras': 0,
                                        'abiertas': 0, 'rebalanceos': 0})
        if fila.get('rebalanceada'):
            d['rebalanceos'] += 1
        resultado = fila.get('resultado')
        precio_base = fila.get('precio_promedio') if fila.get('rebalanceada') else fila.get('precio_entrada')
        tp_base = fila.get('tp_final') if fila.get('rebalanceada') else fila.get('tp')
        stop_base = fila.get('stop_final') if fila.get('rebalanceada') else fila.get('stop')
        capital_operado = fila.get('capital_total_usd') or fila.get('capital_original_usd') \
            or (capital_inicial * (pct_por_operacion / 100.0))

        if resultado == '✅' and tp_base and precio_base:
            pct_mov = abs(tp_base - precio_base) / precio_base
            d['aporte_usd'] += capital_operado * pct_mov
            d['ganadoras'] += 1
        elif resultado == '❌' and stop_base and precio_base:
            pct_mov = abs(stop_base - precio_base) / precio_base
            d['aporte_usd'] -= capital_operado * pct_mov
            d['perdedoras'] += 1
        else:
            d['abiertas'] += 1

    filas_out = []
    for tk, d in sorted(por_ticker.items(), key=lambda x: x[1]['aporte_usd'], reverse=True):
        cerradas = d['ganadoras'] + d['perdedoras']
        wr = f"{d['ganadoras'] / cerradas * 100:.0f}%" if cerradas > 0 else 'N/D'
        filas_out.append({
            'Ticker': tk, 'Aporte al capital (USD)': round(d['aporte_usd'], 2),
            'Ganadoras': d['ganadoras'], 'Perdedoras': d['perdedoras'],
            'Abiertas': d['abiertas'], 'Rebalanceos': d['rebalanceos'], 'Win Rate': wr,
        })
    return pd.DataFrame(filas_out)


def _bot_detalle_aceptadas(supabase, user_id, ticker, horizonte):
    """Trae las operaciones aceptadas de este ticker/horizonte (incluye
    abiertas), para mostrar en la UI el estado de capital/rebalanceo real
    de cada una — a diferencia del historial de señales del gráfico, que es
    puramente informativo y no conoce el rebalanceo."""
    try:
        res = supabase.table('bot_señales_log').select('*') \
            .eq('user_id', user_id).eq('ticker', ticker).eq('horizonte', horizonte) \
            .eq('decision', 'aceptada').order('fecha_señal', desc=True).execute()
        return res.data or []
    except Exception:
        return []

# ── Descarga intradía — TTL corto para que se sienta "en vivo" ────────

@st.cache_data(ttl=20, show_spinner=False)
def _descargar_intradia(ticker, periodo, intervalo):
    try:
        import yfinance as yf
        d = yf.download(ticker, period=periodo, interval=intervalo,
                         progress=False, auto_adjust=True)
        if d is None or d.empty:
            return None
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
        if 'Close' not in d.columns:
            cols_close = [c for c in d.columns if 'close' in str(c).lower()]
            if cols_close:
                d = d.rename(columns={cols_close[0]: 'Close'})
            else:
                return None
        return d.dropna(subset=['Close'])
    except Exception:
        return None


def _resamplear_ohlc(df, regla):
    """Agrupa velas más chicas (ej. 60m) en velas más grandes (ej. 4h),
    respetando la lógica OHLC: apertura=primera, máximo=el más alto,
    mínimo=el más bajo, cierre=el último."""
    if df is None or df.empty:
        return None
    try:
        agregado = {}
        if 'Open' in df.columns:
            agregado['Open'] = 'first'
        if 'High' in df.columns:
            agregado['High'] = 'max'
        if 'Low' in df.columns:
            agregado['Low'] = 'min'
        if 'Close' not in df.columns:
            return None
        agregado['Close'] = 'last'
        if 'Volume' in df.columns:
            agregado['Volume'] = 'sum'
        out = df.resample(regla).agg(agregado)
        return out.dropna(subset=['Close'])
    except Exception:
        return None


def _fetch_paralelo_bot(tickers, cfg):
    """Descarga en paralelo los precios intradía de todos los activos elegidos."""
    resultados = {}
    with ThreadPoolExecutor(max_workers=min(10, max(len(tickers), 1))) as ex:
        futuros = {
            ex.submit(_descargar_intradia, tk, cfg['periodo_descarga'], cfg['interval']): tk
            for tk in tickers
        }
        for fut in as_completed(futuros):
            tk = futuros[fut]
            resultados[tk] = fut.result()
    return resultados


# ── Gráfico de señales ──────────────────────────────────────────────

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
        height=480, hovermode='x unified',
        legend=dict(orientation='h', y=1.1),
        xaxis=dict(gridcolor='#21262d'), yaxis=dict(gridcolor='#21262d'),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    return fig


def _color_estado(estado):
    return {
        'VENTA 100%': C_BOT_VENTA_100, 'VENTA 50%': C_BOT_VENTA_50,
        'COMPRA 100%': C_BOT_COMPRA_100, 'COMPRA 50%': C_BOT_COMPRA_50, '—': '#8b949e',
    }.get(estado, '#8b949e')


def _color_señal_bot(val):
    c = {'VENTA 100%': C_BOT_VENTA_100, 'VENTA 50%': C_BOT_VENTA_50,
         'COMPRA 100%': C_BOT_COMPRA_100, 'COMPRA 50%': C_BOT_COMPRA_50}.get(val, '#e6edf3')
    return f'color:{c};font-weight:700'


def _marca_fractal(row):
    if row.get('fractal_top'):
        return '🔻 Techo'
    if row.get('fractal_bottom'):
        return '🔺 Piso'
    return '–'


# ── Módulo principal ────────────────────────────────────────────────

def modulo_bot_inversion(
    get_close_series, fmt_precio, score_color_hex, kpi_cards_4,
    chips_navegacion, PLOTLY_LAYOUT_BASE, PLOTLY_CONFIG,
    universo_opciones, universo_mapa, supabase, user_id,
):
    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #6CC24A;
         border-radius:14px; padding:28px 32px; margin-bottom:24px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">🤖 Bot de Inversión — Señales Intradía</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Señal basada en 4 condiciones evaluadas en tiempo real:
        <b style="color:#e3b341">Fractal</b> (piso/techo confirmado),
        <b style="color:#e3b341">Sentimiento</b> en nivel extremo,
        <b style="color:#e3b341">Z-Score</b> del precio y
        <b style="color:#e3b341">RSI</b> en sobrecompra/sobreventa.
        4 de 4 condiciones → señal <b style="color:#3fb950">completa</b>.
        3 de 4 → entrada <b style="color:#e3b341">anticipada</b> (más débil).
        Analizá hasta <b style="color:#e3b341">10 activos</b> en simultáneo, en velas de
        <b style="color:#e3b341">5, 15, 30 minutos, 1 hora o 4 horas</b>.
        Las operaciones <b style="color:#a371f7">aceptadas</b> se dimensionan sobre el
        capital <b style="color:#a371f7">actual</b> (compuesto) y, si el precio se acerca
        al Stop sin llegar a tocarlo, el bot <b style="color:#a371f7">rebalancea</b>
        (promedia) automáticamente.
      </div>
    </div>
    """, unsafe_allow_html=True)

    c1, c2 = st.columns([2, 1])
    with c1:
        horizonte_bot = st.selectbox(
            'Temporalidad', list(HORIZONTES_BOT.keys()), index=1, key='bot_horizonte',
        )
    with c2:
        st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)
        if st.button('🔄 Actualizar precios ahora', key='bot_refresh_btn', use_container_width=True):
            _descargar_intradia.clear()
            st.rerun()

    st.markdown(f'#### 🎯 Activos a analizar (hasta {MAX_ACTIVOS_BOT})')
    seleccion = st.multiselect(
        'Elegí hasta 10 activos', universo_opciones,
        default=st.session_state.get('bot_activos_sel', []),
        max_selections=MAX_ACTIVOS_BOT, key='bot_activos_multiselect',
        help='Buscá por nombre o ticker: acciones, ETFs, forex, cripto o commodities.',
    )
    st.session_state['bot_activos_sel'] = seleccion

    manual_extra = st.text_input(
        'Agregar tickers manuales (separados por coma, opcional)',
        key='bot_activos_manual', placeholder='Ej: XYZ, ABC-USD',
    )

    tickers_bot = [universo_mapa.get(s, s) for s in seleccion]
    if manual_extra:
        tickers_bot += [t.strip().upper() for t in manual_extra.split(',') if t.strip()]
    tickers_bot = list(dict.fromkeys(tickers_bot))  # dedup preservando orden

    if len(tickers_bot) > MAX_ACTIVOS_BOT:
        st.warning(f'Se seleccionaron más de {MAX_ACTIVOS_BOT} activos — se van a analizar solo los primeros {MAX_ACTIVOS_BOT}.')
        tickers_bot = tickers_bot[:MAX_ACTIVOS_BOT]

    with st.expander('⚙️ Parámetros de la señal (opcional, aplican a todos los activos)', expanded=False):
        p1, p2, p3 = st.columns(3)
        with p1:
            st.markdown('**Fractal**')
            fractal_izq = st.number_input('Barras izquierda', value=8, min_value=1, key='bot_fractal_izq')
            fractal_der = st.number_input('Barras derecha (retraso confirmación)', value=8, min_value=1, key='bot_fractal_der')
        with p2:
            st.markdown('**Z-Score**')
            zscore_periodo = st.number_input('Período', value=20, min_value=5, key='bot_z_periodo')
            zscore_umbral = st.number_input('Umbral (±)', value=2.5, min_value=0.1, step=0.1, key='bot_z_umbral')
        with p3:
            st.markdown('**RSI**')
            rsi_nivel_venta = st.number_input('Nivel venta (≥)', value=70.0, key='bot_rsi_venta')
            rsi_nivel_compra = st.number_input('Nivel compra (≤)', value=30.0, key='bot_rsi_compra')

        p4, p5 = st.columns(2)
        with p4:
            st.markdown('**Sentimiento — rango COMPRA** (percentil del precio)')
            sent_min_compra = st.number_input('Mínimo', value=0.0, min_value=0.0, max_value=100.0, key='bot_sent_min_compra')
            sent_max_compra = st.number_input('Máximo', value=10.0, min_value=0.0, max_value=100.0, key='bot_sent_max_compra')
        with p5:
            st.markdown('**Sentimiento — rango VENTA** (percentil del precio)')
            sent_min_venta = st.number_input('Mínimo', value=90.0, min_value=0.0, max_value=100.0, key='bot_sent_min_venta')
            sent_max_venta = st.number_input('Máximo', value=100.0, min_value=0.0, max_value=100.0, key='bot_sent_max_venta')

        p6, p7 = st.columns(2)
        with p6:
            st.markdown('**Stop Loss**')
            stop_pct_100 = st.number_input('Stop % — señal completa (4/4)', value=5.0, min_value=0.1, step=0.1, key='bot_stop_100')
            stop_pct_50 = st.number_input('Stop % — entrada anticipada (3/4)', value=5.0, min_value=0.1, step=0.1, key='bot_stop_50')
        with p7:
            st.markdown('**Take Profit**')
            tp_pct_100 = st.number_input('TP % — señal completa (4/4)', value=1.5, min_value=0.1, step=0.1, key='bot_tp_100')
            tp_pct_50 = st.number_input('TP % — entrada anticipada (3/4)', value=1.5, min_value=0.1, step=0.1, key='bot_tp_50')

        p8, p9 = st.columns(2)
        with p8:
            st.markdown('**🔁 Rebalanceo** (promediar antes de tocar el Stop)')
            rebalanceo_umbral_pct = st.number_input(
                'Disparar al X% del camino hacia el Stop', value=80.0,
                min_value=10.0, max_value=99.0, step=5.0, key='bot_rebalanceo_umbral',
                help=('Ej: 80 = si el precio ya recorrió el 80% de la distancia entre tu '
                      'entrada y el Stop (en contra), se dispara una 2da entrada para '
                      'promediar. No espera a que el precio toque el Stop.'),
            )
        with p9:
            st.markdown('**Tamaño de la 2da entrada**')
            rebalanceo_pct_capital = st.number_input(
                '% del capital de la entrada original', value=50.0,
                min_value=5.0, max_value=200.0, step=5.0, key='bot_rebalanceo_pct_capital',
                help='El Stop/TP de la posición promediada se recalcula con los mismos % configurados arriba, aplicados sobre el nuevo precio promedio.',
            )

    analizar_bot = st.button('▶ Analizar', key='bot_run', type='primary')
    if not analizar_bot and not st.session_state.get('bot_run_flag'):
        st.info(f'Elegí la temporalidad y hasta {MAX_ACTIVOS_BOT} activos, después presioná "Analizar".')
        return
    if analizar_bot:
        st.session_state['bot_run_flag'] = True
    with st.expander('💰 Configuración de capital y decisión', expanded=False):
        cfg_bot_user = _bot_obtener_config(supabase, user_id)
        cb1, cb2, cb3 = st.columns(3)
        with cb1:
            capital_inicial_bot = st.number_input(
                'Capital inicial (USD)', min_value=100.0,
                value=float(cfg_bot_user['capital_inicial']), step=500.0, key='bot_capital_inicial',
            )
        with cb2:
            pct_por_operacion_bot = st.number_input(
                '% de capital por operación', min_value=1.0, max_value=100.0,
                value=float(cfg_bot_user['pct_por_operacion']), step=1.0, key='bot_pct_operacion',
                help='Se aplica sobre el capital ACTUAL (compuesto), no sobre el capital inicial fijo.',
            )
        with cb3:
            minutos_limite_bot = st.number_input(
                'Minutos límite para decidir', min_value=1, max_value=120,
                value=int(cfg_bot_user['minutos_limite_decision']), step=1, key='bot_minutos_limite',
                help='Pasado este tiempo sin Aceptar/Rechazar, la señal expira y no cuenta para el rendimiento.',
            )
        if st.button('💾 Guardar configuración', key='bot_guardar_config'):
            _bot_guardar_config(supabase, user_id, capital_inicial_bot, pct_por_operacion_bot, minutos_limite_bot)
            st.success('Configuración guardada.')
            
    if not tickers_bot:
        st.warning('Seleccioná al menos un activo.')
        return

    cfg = HORIZONTES_BOT[horizonte_bot]

    with st.spinner(f'Descargando velas de {horizonte_bot} para {len(tickers_bot)} activo(s)...'):
        precios_raw = _fetch_paralelo_bot(tickers_bot, cfg)

    resultados_bot = {}
    fallidos = []
    for tk in tickers_bot:
        df_raw = precios_raw.get(tk)
        if df_raw is None or df_raw.empty:
            fallidos.append(tk)
            continue
        if cfg.get('resample'):
            df_raw = _resamplear_ohlc(df_raw, cfg['resample'])
            if df_raw is None or df_raw.empty:
                fallidos.append(tk)
                continue
        cl = get_close_series(df_raw)
        if cl is None or len(cl.dropna()) < max(30, cfg['ventana_valor'] // 4):
            fallidos.append(tk)
            continue
        hi = df_raw['High'] if 'High' in df_raw.columns else cl
        lo = df_raw['Low'] if 'Low' in df_raw.columns else cl
        df_bot = _calcular_bot_dataframe(
            cl, hi, lo, cfg,
            sent_min_compra, sent_max_compra, sent_min_venta, sent_max_venta,
            int(zscore_periodo), zscore_umbral,
            rsi_nivel_venta, rsi_nivel_compra,
            int(fractal_izq), int(fractal_der),
            stop_pct_100, stop_pct_50, tp_pct_100, tp_pct_50,
        )
        hi_r = hi.reindex(df_bot.index)
        lo_r = lo.reindex(df_bot.index)
        df_bot = _evaluar_resultados_señales(df_bot, hi_r, lo_r)
        resultados_bot[tk] = df_bot
        _bot_registrar_señales_nuevas(supabase, user_id, tk, horizonte_bot, df_bot, int(minutos_limite_bot),
                                        stop_pct_100, stop_pct_50, tp_pct_100, tp_pct_50)
        # Orden importante: primero se chequea si corresponde rebalanceo (así
        # una operación recién promediada ya usa su Stop/TP nuevo) y recién
        # después se evalúa si tocó TP/Stop.
        _bot_chequear_rebalanceos(supabase, user_id, tk, horizonte_bot, df_bot,
                                    rebalanceo_umbral_pct, rebalanceo_pct_capital)
        _bot_actualizar_resultados_aceptadas(supabase, user_id, tk, horizonte_bot, df_bot)

    if fallidos:
        st.warning(f"⚠️ No se pudo descargar/calcular para: {', '.join(fallidos)} "
                    "(puede ser un símbolo sin datos intradía en Yahoo Finance, o límite temporal).")

    if not resultados_bot:
        st.error('No se pudo calcular ninguna señal con los activos seleccionados.')
        return
    _bot_expirar_vencidas(supabase, user_id)
    _bot_actualizar_todos_los_pendientes(supabase, user_id, get_close_series,
                                           rebalanceo_umbral_pct, rebalanceo_pct_capital)
    st.caption(
        f"🕐 {datetime.now().strftime('%H:%M:%S')} · Temporalidad {horizonte_bot} · "
        f"caché de precios: 20s · tocá '🔄 Actualizar precios ahora' para forzar la recarga."
    )
    
    st.markdown('### ⏱️ Señales pendientes de decisión')
    pendientes = _bot_pendientes_decision(supabase, user_id)
    if not pendientes:
        st.info('No hay señales esperando tu decisión ahora mismo.')
    else:
        for p in pendientes:
            fecha_lim = pd.Timestamp(p['fecha_limite_decision'])
            mins_restantes = max(0, int((fecha_lim - pd.Timestamp.now(tz=fecha_lim.tz)).total_seconds() // 60))
            col_info, col_ok, col_no = st.columns([4, 1, 1])
            with col_info:
                st.markdown(
                    f"**{p['ticker']}** · {p['tipo_señal']} · Entrada: {fmt_precio(p['precio_entrada'])} · "
                    f"TP: {fmt_precio(p['tp'])} · Stop: {fmt_precio(p['stop'])} · "
                    f"⏳ Quedan **{mins_restantes} min** para decidir"
                )
            with col_ok:
                if st.button('✅ Aceptar', key=f"bot_aceptar_{p['id']}", use_container_width=True):
                    _bot_decidir_señal(supabase, p['id'], 'aceptada',
                                         capital_inicial=capital_inicial_bot,
                                         pct_por_operacion=pct_por_operacion_bot,
                                         user_id=user_id)
                    st.rerun()
            with col_no:
                if st.button('❌ Rechazar', key=f"bot_rechazar_{p['id']}", use_container_width=True):
                    _bot_decidir_señal(supabase, p['id'], 'rechazada')
                    st.rerun()
    st.markdown('---')
    
    # ── Resumen multi-activo ─────────────────────────────────────────
    st.markdown('### 📋 Resumen — señal actual por activo')
    filas_resumen = []
    for tk, df_bot in resultados_bot.items():
        u = df_bot.iloc[-1]
        disparos_tk = df_bot[df_bot['disparo'] & (df_bot['estado'] != '—')]
        n_ok = int((disparos_tk['resultado'] == '✅').sum())
        n_bad = int((disparos_tk['resultado'] == '❌').sum())
        n_open = int((disparos_tk['resultado'] == '⏳').sum())
        cerradas = n_ok + n_bad
        winrate = f'{n_ok / cerradas * 100:.0f}%' if cerradas > 0 else 'N/D'
        filas_resumen.append({
            'Ticker': tk, 'Señal': u['estado'], 'Precio': fmt_precio(u['precio']),
            'Última vela': df_bot.index[-1].strftime('%H:%M:%S'),
            'Fractal': _marca_fractal(u),
            'Sent': round(u['sc_sent'], 1),
            'Z-Score': round(u['zscore'], 2), 'RSI': round(u['rsi'], 1),
            'Cond V': f"{int(u['count_venta'])}/4", 'Cond C': f"{int(u['count_compra'])}/4",
            'Stop': fmt_precio(u['stop']) if not pd.isna(u['stop']) else '—',
            'TP': fmt_precio(u['tp']) if not pd.isna(u['tp']) else '—',
            'Track record': f'{n_ok}✅ {n_bad}❌ {n_open}⏳',
            'Win rate': winrate,
        })
    df_resumen = pd.DataFrame(filas_resumen)
    orden_prioridad = {'VENTA 100%': 0, 'COMPRA 100%': 0, 'VENTA 50%': 1, 'COMPRA 50%': 1, '—': 2}
    df_resumen['_orden'] = df_resumen['Señal'].map(orden_prioridad)
    df_resumen = df_resumen.sort_values('_orden').drop(columns=['_orden'])

    _map = 'map' if hasattr(df_resumen.style, 'map') else 'applymap'
    styled_resumen = (df_resumen.style
        .pipe(lambda s: getattr(s, _map)(_color_señal_bot, subset=['Señal']))
        .set_properties(**{'background-color': '#0d1117', 'color': '#e6edf3', 'border': '1px solid #21262d'})
        .set_table_styles([
            {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', '#e6edf3'),
                ('font-weight', '700'), ('text-align', 'center'),
                ('border-bottom', '2px solid #3a7bd5'), ('font-size', '11px')]},
            {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]},
        ]))
    st.dataframe(styled_resumen, use_container_width=True, height=min(400, len(df_resumen) * 40 + 45))
    chips_navegacion([(tk, tk) for tk in resultados_bot.keys()], 'bot_inversion_resumen')

    n_señales = int((df_resumen['Señal'] != '—').sum())
    if n_señales > 0:
        st.success(f'⚡ {n_señales} activo(s) con señal activa ahora mismo.')

    # ── Detalle de un activo ─────────────────────────────────────────
    st.markdown('---')
    st.markdown('### 🔍 Detalle por activo')
    ticker_detalle = st.selectbox(
        'Elegí un activo para ver el gráfico y el historial completo',
        list(resultados_bot.keys()), key='bot_detalle_sel',
    )
    df_bot_sel = resultados_bot[ticker_detalle]
    ultimo = df_bot_sel.iloc[-1]
    estado_actual = ultimo['estado']
    color_estado = _color_estado(estado_actual)

    kpi_cards_4([
        ('Señal Actual', estado_actual, f'{ticker_detalle} · {horizonte_bot}', color_estado),
        ('Precio', fmt_precio(ultimo['precio']),
         f"Stop sugerido: {fmt_precio(ultimo['stop']) if not pd.isna(ultimo['stop']) else '—'}", '#3a7bd5'),
        ('Sentimiento / Fractal', f"{ultimo['sc_sent']:.0f} · {_marca_fractal(ultimo)}",
         'Percentil de precio · pivote confirmado', score_color_hex(ultimo['sc_sent'])),
        ('Z-Score / RSI', f"{ultimo['zscore']:+.2f} / {ultimo['rsi']:.1f}",
         f"Cond. Venta {int(ultimo['count_venta'])}/4 · Cond. Compra {int(ultimo['count_compra'])}/4", '#e3b341'),
    ])

    st.plotly_chart(_fig_bot_señales(ticker_detalle, df_bot_sel, PLOTLY_LAYOUT_BASE),
                     use_container_width=True, config=PLOTLY_CONFIG, key=f'bot_fig_señales_{ticker_detalle}')

    st.markdown('#### 📋 Historial de señales disparadas')
    df_hist = df_bot_sel[df_bot_sel['disparo']].copy().sort_index(ascending=False)
    if df_hist.empty:
        st.info('No se disparó ninguna señal en el período analizado con los parámetros actuales.')
    else:
        df_hist_show = pd.DataFrame({
            'Fecha/Hora': df_hist.index.strftime('%Y-%m-%d %H:%M'),
            'Señal': df_hist['estado'],
            'Resultado': df_hist['resultado'],
            'Precio': df_hist['precio'].apply(fmt_precio),
            'Stop': df_hist['stop'].apply(fmt_precio),
            'TP': df_hist['tp'].apply(fmt_precio),
            'Precio Result.': df_hist['precio_resultado'].apply(lambda v: fmt_precio(v) if pd.notna(v) else '—'),
            'Velas hasta result.': df_hist['barras_hasta_resultado'].apply(lambda v: int(v) if pd.notna(v) else '—'),
            'Fractal': df_hist.apply(_marca_fractal, axis=1),
            'Sent': df_hist['sc_sent'].round(1),
            'Z-Score': df_hist['zscore'].round(2),
            'RSI': df_hist['rsi'].round(1),
            'Cond V': df_hist['count_venta'].astype(int).astype(str) + '/4',
            'Cond C': df_hist['count_compra'].astype(int).astype(str) + '/4',
        })
        styled_hist = (df_hist_show.style
            .pipe(lambda s: getattr(s, _map)(_color_señal_bot, subset=['Señal']))
            .pipe(lambda s: getattr(s, _map)(_color_resultado, subset=['Resultado']))
            .set_properties(**{'background-color': '#0d1117', 'color': '#e6edf3', 'border': '1px solid #21262d'})
            .set_table_styles([
                {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', '#e6edf3'),
                    ('font-weight', '700'), ('text-align', 'center'),
                    ('border-bottom', '2px solid #3a7bd5'), ('font-size', '11px')]},
                {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]},
            ]))
        st.dataframe(styled_hist, use_container_width=True, height=min(500, len(df_hist_show) * 38 + 45))
        st.caption(f'{len(df_hist_show)} señales disparadas en el historial analizado ({cfg["periodo_descarga"]} · {horizonte_bot}).')

    # ── Estado real de las operaciones aceptadas (con rebalanceo) ────
    st.markdown('#### 💼 Operaciones aceptadas de este activo (estado real, con rebalanceo)')
    aceptadas_tk = _bot_detalle_aceptadas(supabase, user_id, ticker_detalle, horizonte_bot)
    if not aceptadas_tk:
        st.info('Todavía no aceptaste ninguna señal de este activo en esta temporalidad.')
    else:
        filas_acept = []
        for f in aceptadas_tk:
            rebal = bool(f.get('rebalanceada'))
            filas_acept.append({
                'Fecha señal': pd.Timestamp(f['fecha_señal']).strftime('%Y-%m-%d %H:%M'),
                'Tipo': f['tipo_señal'],
                'Entrada': fmt_precio(f['precio_entrada']),
                'Capital orig.': f"USD {f.get('capital_original_usd', 0):,.0f}" if f.get('capital_original_usd') else '—',
                'Rebalanceada': '🔁 Sí' if rebal else '—',
                'Precio rebal.': fmt_precio(f['precio_rebalanceo']) if rebal and f.get('precio_rebalanceo') else '—',
                'Precio promedio': fmt_precio(f['precio_promedio']) if rebal and f.get('precio_promedio') else '—',
                'Capital total': f"USD {f.get('capital_total_usd', 0):,.0f}" if f.get('capital_total_usd') else '—',
                'Stop vigente': fmt_precio(f['stop_final'] if rebal else f.get('stop')) if (f.get('stop_final') or f.get('stop')) else '—',
                'TP vigente': fmt_precio(f['tp_final'] if rebal else f.get('tp')) if (f.get('tp_final') or f.get('tp')) else '—',
                'Resultado': f.get('resultado') or '⏳',
            })
        df_acept_show = pd.DataFrame(filas_acept)
        styled_acept = (df_acept_show.style
            .pipe(lambda s: getattr(s, _map)(_color_resultado, subset=['Resultado']))
            .set_properties(**{'background-color': '#0d1117', 'color': '#e6edf3', 'border': '1px solid #21262d'})
            .set_table_styles([
                {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', '#e6edf3'),
                    ('font-weight', '700'), ('text-align', 'center'),
                    ('border-bottom', f'2px solid {C_BOT_REBALANCEO}'), ('font-size', '11px')]},
                {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]},
            ]))
        st.dataframe(styled_acept, use_container_width=True, height=min(360, len(df_acept_show) * 38 + 45))

    st.markdown('---')
    st.markdown('### 📈 Rendimiento del bot (solo señales aceptadas)')
    rend = _bot_calcular_rendimiento(supabase, user_id, capital_inicial_bot, pct_por_operacion_bot)

    if rend['total_señales'] == 0:
        st.info('Todavía no aceptaste ninguna señal — el rendimiento se arma a medida que decidís sobre las que aparecen.')
    else:
        color_rend = '#3fb950' if rend['rendimiento_pct'] >= 0 else '#f85149'
        kpi_cards_4([
            ('Capital Actual', f"USD {rend['capital_actual']:,.2f}",
             f"Inicial: USD {rend['capital_inicial']:,.2f}", color_rend),
            ('Rendimiento', f"{rend['rendimiento_pct']:+.2f}%", 'Sobre capital inicial', color_rend),
            ('Win Rate', f"{rend['win_rate']:.0f}%" if rend['win_rate'] is not None else 'N/D',
             f"{rend['ganadoras']}✅ / {rend['perdedoras']}❌ cerradas", '#3a7bd5'),
            ('Operaciones', str(rend['total_señales']),
             f"{rend['cerradas']} cerradas · {rend['abiertas']} en curso · {rend['rebalanceos']} 🔁 rebalanceadas", '#e3b341'),
        ])

        fig_eq = go.Figure()
        eq_x = [str(c['fecha'])[:16] for c in rend['curva']]
        eq_y = [c['equity'] for c in rend['curva']]
        fig_eq.add_trace(go.Scatter(x=eq_x, y=eq_y, mode='lines+markers',
                                     line=dict(color=color_rend, width=2)))
        fig_eq.update_layout(
            **PLOTLY_LAYOUT_BASE, height=340,
            title=dict(text='Evolución del capital (señales aceptadas)', font=dict(size=13)),
            xaxis=dict(gridcolor='#21262d'), yaxis=dict(gridcolor='#21262d', title='USD'),
            margin=dict(l=10, r=10, t=45, b=10),
        )
        st.plotly_chart(fig_eq, use_container_width=True, config=PLOTLY_CONFIG, key='bot_equity_fig')
        st.caption(
            'Solo se cuentan señales que aceptaste dentro del límite de tiempo configurado — '
            'esto evita medir con sesgo retrospectivo (aceptar solo las que ya sabías que salieron bien). '
            'Cada operación se dimensiona con el % de capital configurado sobre el capital ACTUAL en el '
            'momento de aceptarla (simulación de capital compuesto), y si se rebalanceó, el resultado se '
            'calcula sobre el precio promedio y el capital total (original + rebalanceo). '
            'Las señales "en curso" (⏳) todavía no suman ni restan al capital.'
        )

        st.markdown('#### 📊 Rendimiento por activo')
        df_por_tk = _bot_rendimiento_por_ticker(supabase, user_id, capital_inicial_bot, pct_por_operacion_bot)
        if df_por_tk.empty:
            st.info('Todavía no hay operaciones cerradas para desglosar por activo.')
        else:
            def _color_aporte(val):
                try:
                    v = float(val)
                    return f'color:{"#3fb950" if v >= 0 else "#f85149"};font-weight:700'
                except Exception:
                    return ''
            _map_pt = 'map' if hasattr(df_por_tk.style, 'map') else 'applymap'
            styled_pt = (df_por_tk.style
                .pipe(lambda s: getattr(s, _map_pt)(_color_aporte, subset=['Aporte al capital (USD)']))
                .set_properties(**{'background-color': '#0d1117', 'color': '#e6edf3', 'border': '1px solid #21262d'})
                .set_table_styles([
                    {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', '#e6edf3'),
                        ('font-weight', '700'), ('text-align', 'center'),
                        ('border-bottom', '2px solid #3a7bd5'), ('font-size', '11px')]},
                    {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]},
                ]))
            st.dataframe(styled_pt, use_container_width=True, height=min(400, len(df_por_tk) * 40 + 45))
            st.caption('El activo que aparece "seleccionado o no" no importa para este cálculo: se suma todo lo que aceptaste alguna vez, esté o no en tu multiselect actual.')

        st.markdown('#### ⚠️ Reiniciar historial')
        st.caption('Esto borra TODAS tus señales aceptadas/rechazadas/expiradas y arranca el rendimiento de cero. No afecta a otros usuarios.')
        if st.button('🗑️ Reiniciar mi historial completo', key='bot_reset_btn'):
            st.session_state['bot_reset_confirmar'] = True
        if st.session_state.get('bot_reset_confirmar'):
            st.warning('¿Confirmás? Esta acción no se puede deshacer.')
            cconf1, cconf2 = st.columns(2)
            with cconf1:
                if st.button('✅ Sí, borrar todo', key='bot_reset_confirm_yes'):
                    try:
                        supabase.table('bot_señales_log').delete().eq('user_id', user_id).execute()
                        st.session_state['bot_reset_confirmar'] = False
                        st.success('Historial reiniciado.')
                        st.rerun()
                    except Exception:
                        st.error('No se pudo reiniciar el historial. Probá de nuevo.')
            with cconf2:
                if st.button('✖️ Cancelar', key='bot_reset_confirm_no'):
                    st.session_state['bot_reset_confirmar'] = False
                    st.rerun()
    with st.expander('❓ Cómo funciona esta señal'):
        st.markdown("""
        Cada barra se evalúa contra 4 condiciones por lado: **Fractal** (piso/techo confirmado con
        barras de izquierda/derecha), **Sentimiento** (percentil del precio dentro del rango elegido),
        **Z-Score** (desvíos respecto a la media móvil) y **RSI** (nivel de sobrecompra/sobreventa).

        - **4 de 4 condiciones cumplidas** → señal **completa** (mostrada como "100%"), con el Stop y
          Take Profit más amplios que configuraste.
        - **3 de 4 condiciones cumplidas** → **entrada anticipada** (mostrada como "50%"), más débil
          y con su propio Stop/TP.

        Cada señal disparada se evalúa hacia adelante: se marca **✅** si el precio tocó primero el
        Take Profit, **❌** si tocó primero el Stop, y **⏳ En curso** si todavía no definió.

        **🔁 Rebalanceo (solo en operaciones aceptadas)**: si el precio recorre el % configurado del
        camino hacia el Stop (por defecto 80%) SIN llegar a tocarlo, el bot dispara una 2da entrada de
        tamaño = 50% del capital de la entrada original (configurable), calcula un **precio promedio**
        ponderado por cantidad (capital ÷ precio, como promediar acciones o contratos reales), y sobre
        ese promedio recalcula el Stop y el TP usando los **mismos %** que configuraste originalmente.
        De ahí en más, el resultado de esa operación se evalúa contra el Stop/TP nuevos.

        **💰 Simulación de capital compuesto**: al aceptar una señal, el tamaño de esa entrada se
        calcula como el % de operación configurado sobre el **capital actual** (resultado de todas las
        operaciones aceptadas y cerradas hasta ese momento), no sobre el capital inicial fijo. Así el
        tamaño de cada entrada se va ajustando junto con el capital, hacia arriba o hacia abajo.

        ⚠️ **Importante**: si NO se llegó a rebalancear una operación, el Stop se sigue tratando como
        una salida total. Solo cuando el bot rebalancea de verdad se está "promediando en vez de cerrar";
        el resto del tiempo, tocar el Stop original todavía implica cerrar la posición con esa pérdida.

        Usalo como medida de calidad de la señal, no como tu resultado real de trading.
        """)
