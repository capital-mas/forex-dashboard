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
#      CAPITAL COMPUESTO.
#
#  v4: la herramienta pasa a ser de SOLO OBSERVACIÓN — todas las
#      señales que dispara el bot se registran automáticamente
#      como si hubieran sido aceptadas (ya no hay botones de
#      Aceptar/Rechazar ni ventana de decisión). El capital inicial
#      queda fijo en USD 100 y el rendimiento se simula bajo
#      distintos niveles de apalancamiento (1x a 5x) sobre la MISMA
#      secuencia de operaciones que arroja el bot, para poder
#      comparar cómo se hubiera movido el capital en cada caso.
#      El rebalanceo (promediar antes de tocar el Stop, y recalcular
#      el Stop/TP sobre el precio promedio) sigue funcionando igual
#      que antes, de forma totalmente automática.
#
#  v5: se saca toda la simulación/estado "real" que dependía de
#      bot_señales_log en Supabase (registro de señales, chequeo de
#      rebalanceo y resultado contra el log, tabla de "Operaciones
#      de este activo"). En su lugar, la simulación de rendimiento se
#      arma 100% EN MEMORIA, directamente sobre el mismo "Historial
#      de señales disparadas" que ya se calcula en cada corrida
#      (misma ventana de datos descargada de Yahoo Finance). El
#      rebalanceo se sigue simulando (también en memoria, con la
#      misma lógica de siempre) y el capital inicial de la
#      simulación pasa a ser configurable, desde USD 50 en adelante,
#      en lugar de estar fijo en USD 100.
# ==============================================================

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

MAX_ACTIVOS_BOT = 10

# Capital inicial de la simulación: ahora es configurable desde la UI
# (mínimo USD 50). Estas son solo el piso y el valor por defecto que se
# usan la primera vez, antes de que el usuario elija otro monto.
CAPITAL_MINIMO_BOT = 50.0
CAPITAL_INICIAL_BOT_DEFAULT = 100.0

# Niveles de apalancamiento que se pueden comparar sobre la misma secuencia
# de operaciones que va arrojando el bot.
APALANCAMIENTOS_BOT = [1, 2, 3, 4, 5]

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

def _evaluar_señales_con_rebalanceo(df, rebalanceo_umbral_pct, rebalanceo_pct_capital,
                                      stop_pct_100, stop_pct_50, tp_pct_100, tp_pct_50,
                                      max_entradas=3):
    """Para cada señal disparada, calcula UN ÚNICO resultado (✅/❌/⏳/⛔) que ya
    tiene en cuenta el rebalanceo y el solapamiento de operaciones — así toda
    la pantalla (resumen, historial de señales, win rate y simulación de
    capital) lee siempre el mismo dato y no puede haber números que no
    cierren entre sí.

    Reglas, en orden cronológico:
      1. **Sin solapamiento**: si esta señal aparece mientras todavía hay una
         operación abierta de este mismo activo (una anterior que no cerró
         ✅/❌ todavía), el bot NO la toma — queda marcada con resultado
         '⛔' (no tomada) y no genera entradas ni afecta el capital. Sigue
         apareciendo en el historial para que se vea que el bot la vio pero
         no operó.
      2. **Rebalanceo (hasta 2 veces → 3 entradas en total)**: si el precio
         recorre 'rebalanceo_umbral_pct' % del camino hacia el Stop vigente
         SIN llegar a tocarlo, se dispara una entrada adicional (tamaño =
         'rebalanceo_pct_capital' % de la 1ra entrada), se recalcula el
         precio promedio ponderado por cantidad y, sobre ese promedio, el
         nuevo Stop/TP (mismos % configurados originalmente). Esto puede
         repetirse una segunda vez (3ra entrada) usando como referencia el
         nuevo promedio y el nuevo Stop — hasta un máximo de 'max_entradas'
         entradas por operación.
      3. **Resultado** contra el Stop/TP vigentes en ese momento: ✅ si tocó
         primero el TP, ❌ si tocó primero el Stop (o si ambos se tocan en
         la misma vela — no se puede saber cuál fue primero con datos OHLC
         estándar, así que se asume el escenario conservador), ⏳ si
         todavía no definió (en cuyo caso la operación se considera abierta
         hasta el final de los datos disponibles, bloqueando señales
         nuevas de este activo hasta que aparezcan más datos).
    """
    df = df.copy()
    n = len(df)
    resultado = [''] * n
    precio_resultado = [np.nan] * n
    barras_hasta = [np.nan] * n
    tomada = [False] * n
    num_rebalanceos = [0] * n
    entrada2_precio = [np.nan] * n
    entrada3_precio = [np.nan] * n
    fecha_entrada2 = [pd.NaT] * n
    fecha_entrada3 = [pd.NaT] * n
    precio_promedio_arr = [np.nan] * n
    stop_vigente_arr = [np.nan] * n
    tp_vigente_arr = [np.nan] * n

    idx = df.index
    hi_arr = df['high'].values
    lo_arr = df['low'].values
    precio_arr = df['precio'].values
    estado_arr = df['estado'].values
    disparo_arr = df['disparo'].values
    tp_arr = df['tp'].values
    sl_arr = df['stop'].values

    ocupado_hasta = -1  # índice de la última barra "ocupada" por una operación en curso

    for i in range(n):
        if not disparo_arr[i] or estado_arr[i] == '—' or pd.isna(tp_arr[i]) or pd.isna(sl_arr[i]):
            continue

        if i <= ocupado_hasta:
            resultado[i] = '⛔'  # no tomada: ya había una operación abierta en este activo
            continue

        tomada[i] = True
        es_venta = 'VENTA' in estado_arr[i]
        es_100 = '100%' in estado_arr[i]
        stop_pct_usado = stop_pct_100 if es_100 else stop_pct_50
        tp_pct_usado = tp_pct_100 if es_100 else tp_pct_50

        precio_prom = precio_arr[i]
        stop_vigente = sl_arr[i]
        tp_vigente = tp_arr[i]
        capital_total = 100.0  # unidad nominal (peso relativo), no dólares reales
        qty_total = capital_total / precio_prom
        j_cursor = i + 1
        n_entradas = 1

        # ── 1) ¿Corresponde rebalanceo (1ra o 2da vez) antes de tocar el Stop vigente? ──
        while n_entradas < max_entradas:
            distancia_stop = abs(stop_vigente - precio_prom)
            if distancia_stop <= 0:
                break
            j_reb = None
            for j in range(j_cursor, n):
                precio_j = precio_arr[j]
                if precio_j is None or (isinstance(precio_j, float) and np.isnan(precio_j)):
                    continue
                avance_pct = ((precio_j - precio_prom) / distancia_stop * 100) if es_venta \
                    else ((precio_prom - precio_j) / distancia_stop * 100)
                if avance_pct >= 100:
                    break  # ya tocó/pasó el Stop vigente antes de llegar a un nuevo rebalanceo
                if avance_pct >= rebalanceo_umbral_pct:
                    j_reb = j
                    break
            if j_reb is None:
                break

            precio_j = precio_arr[j_reb]
            capital_entrada = 100.0 * (rebalanceo_pct_capital / 100.0)
            qty_entrada = capital_entrada / precio_j
            capital_total += capital_entrada
            qty_total += qty_entrada
            precio_prom = capital_total / qty_total
            if es_venta:
                stop_vigente = precio_prom * (1 + stop_pct_usado / 100)
                tp_vigente = precio_prom * (1 - tp_pct_usado / 100)
            else:
                stop_vigente = precio_prom * (1 - stop_pct_usado / 100)
                tp_vigente = precio_prom * (1 + tp_pct_usado / 100)

            n_entradas += 1
            num_rebalanceos[i] = n_entradas - 1
            if n_entradas == 2:
                entrada2_precio[i] = precio_j
                fecha_entrada2[i] = idx[j_reb]
            elif n_entradas == 3:
                entrada3_precio[i] = precio_j
                fecha_entrada3[i] = idx[j_reb]
            j_cursor = j_reb

        if n_entradas > 1:
            precio_promedio_arr[i] = precio_prom
        stop_vigente_arr[i] = stop_vigente
        tp_vigente_arr[i] = tp_vigente

        # ── 2) Resultado contra el Stop/TP vigente, desde la última entrada ──
        encontrado = False
        j_exit = n - 1  # si no se resuelve, la operación queda "abierta" hasta el final de los datos
        for j in range(j_cursor, n):
            hi_j, lo_j = hi_arr[j], lo_arr[j]
            if es_venta:
                toco_tp, toco_sl = lo_j <= tp_vigente, hi_j >= stop_vigente
            else:
                toco_tp, toco_sl = hi_j >= tp_vigente, lo_j <= stop_vigente
            if toco_tp or toco_sl:
                if toco_sl:
                    resultado[i], precio_resultado[i] = '❌', stop_vigente
                else:
                    resultado[i], precio_resultado[i] = '✅', tp_vigente
                barras_hasta[i] = j - i
                j_exit = j
                encontrado = True
                break
        if not encontrado:
            resultado[i] = '⏳'

        ocupado_hasta = j_exit

    df['resultado'] = resultado
    df['precio_resultado'] = precio_resultado
    df['barras_hasta_resultado'] = barras_hasta
    df['tomada'] = tomada
    df['num_rebalanceos'] = num_rebalanceos
    df['rebalanceada'] = [x > 0 for x in num_rebalanceos]
    df['entrada2_precio'] = entrada2_precio
    df['entrada3_precio'] = entrada3_precio
    df['fecha_entrada2'] = fecha_entrada2
    df['fecha_entrada3'] = fecha_entrada3
    df['precio_promedio'] = precio_promedio_arr
    df['stop_vigente'] = stop_vigente_arr
    df['tp_vigente'] = tp_vigente_arr
    return df


def _color_resultado(val):
    return {'✅': 'color:#3fb950;font-weight:700', '❌': 'color:#f85149;font-weight:700',
            '⏳': 'color:#e3b341;font-weight:600'}.get(val, '')


def _color_rebalanceada(val):
    return f'color:{C_BOT_REBALANCEO};font-weight:700' if val == 'Sí' else ''

# ── Persistencia en Supabase: configuración, registro automático y rebalanceo ─

def _bot_obtener_config(supabase, user_id):
    try:
        res = supabase.table('bot_config_usuario').select('*').eq('user_id', user_id).limit(1).execute()
        if res.data:
            return res.data[0]
    except Exception:
        pass
    return {'capital_inicial': CAPITAL_INICIAL_BOT_DEFAULT, 'pct_por_operacion': 10.0, 'apalancamiento': 1}


def _bot_guardar_config(supabase, user_id, capital_inicial, pct_por_operacion, apalancamiento):
    try:
        supabase.table('bot_config_usuario').upsert({
            'user_id': user_id, 'capital_inicial': float(capital_inicial),
            'pct_por_operacion': pct_por_operacion,
            'apalancamiento': int(apalancamiento),
            'actualizado_en': datetime.now().isoformat(),
        }).execute()
    except Exception:
        pass


# ── Simulación de rendimiento — 100% en memoria ────────────────────────
#
# Todo lo que antes se guardaba y recalculaba contra la tabla
# bot_señales_log de Supabase (registro de señales, chequeo de rebalanceo,
# chequeo de resultado, curva de capital) se arma ahora directamente sobre
# el "Historial de señales disparadas" que ya calcula _calcular_bot_dataframe
# + _evaluar_señales_con_rebalanceo para el activo/temporalidad
# seleccionados. Esta función NO recalcula el rebalanceo, el resultado ni
# cuáles señales se tomaron — los toma tal cual quedaron en df_bot, así el
# Win Rate que ves en el resumen, en la tabla de historial y en esta
# simulación son siempre EL MISMO número, sin importar el apalancamiento o
# el capital elegidos (esos dos solo afectan cuánto gana/pierde cada
# operación y el tamaño en USD de cada entrada, no si gana o pierde ni
# cuáles señales se toman).

def _bot_simular_en_memoria(df_bot, capital_inicial, pct_por_operacion, apalancamiento,
                              rebalanceo_pct_capital):
    """Recorre, en orden cronológico, las señales TOMADAS de df_bot (las que
    no quedaron bloqueadas por tener otra operación abierta) y compone el
    capital: cada operación cerrada arriesga 'pct_por_operacion' % del
    capital ACTUAL de esta simulación (la 1ra entrada), multiplicado por el
    apalancamiento. Las entradas adicionales por rebalanceo (2da y 3ra, si
    las hubo) se dimensionan como 'rebalanceo_pct_capital' % de esa misma
    1ra entrada — así el tamaño en USD de cada entrada queda guardado en
    'montos', para mostrarlo en la tabla de historial. La pérdida de una
    operación nunca supera el 100% del capital arriesgado en la 1ra entrada
    (se simula que esa posición se liquida, no toda la cuenta)."""
    disparos = df_bot[df_bot['disparo'] & (df_bot['estado'] != '—') & (df_bot['tomada'] == True)]
    equity = capital_inicial
    curva = [{'fecha': 'Inicio', 'equity': equity}]
    cerradas = ganadoras = abiertas = rebalanceos = 0
    montos = {}

    for ts, row in disparos.iterrows():
        resultado = row['resultado']
        n_reb = int(row.get('num_rebalanceos', 0) or 0)
        if n_reb > 0:
            rebalanceos += 1
        precio_base = row['precio_promedio'] if n_reb > 0 else row['precio']
        tp_base = row['tp_vigente']
        stop_base = row['stop_vigente']

        capital_operado = equity * (pct_por_operacion / 100.0)
        monto_e2 = capital_operado * (rebalanceo_pct_capital / 100.0) if n_reb >= 1 else None
        monto_e3 = capital_operado * (rebalanceo_pct_capital / 100.0) if n_reb >= 2 else None
        montos[ts] = {
            'e1': capital_operado, 'e2': monto_e2, 'e3': monto_e3,
            'total': capital_operado + (monto_e2 or 0) + (monto_e3 or 0),
        }

        if pd.isna(precio_base) or pd.isna(tp_base) or pd.isna(stop_base):
            abiertas += 1
            continue

        if resultado == '✅':
            pct_mov = abs(tp_base - precio_base) / precio_base
            equity += capital_operado * pct_mov * apalancamiento
            ganadoras += 1; cerradas += 1
        elif resultado == '❌':
            pct_mov = abs(stop_base - precio_base) / precio_base
            perdida = min(capital_operado * pct_mov * apalancamiento, capital_operado)
            equity -= perdida
            cerradas += 1
        else:
            abiertas += 1
            continue

        curva.append({'fecha': ts.strftime('%Y-%m-%d %H:%M'), 'equity': equity})

    return {
        'capital_inicial': capital_inicial, 'capital_actual': equity,
        'rendimiento_pct': (equity / capital_inicial - 1) * 100 if capital_inicial else 0.0,
        'win_rate': (ganadoras / cerradas * 100) if cerradas > 0 else None,
        'cerradas': cerradas, 'ganadoras': ganadoras, 'perdedoras': cerradas - ganadoras,
        'abiertas': abiertas, 'total_señales': len(disparos), 'curva': curva,
        'rebalanceos': rebalanceos, 'apalancamiento': apalancamiento, 'montos': montos,
    }


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
    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #6CC24A;
         border-radius:14px; padding:28px 32px; margin-bottom:24px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">🤖 Bot de Inversión — Señales Intradía</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Herramienta de <b style="color:#e3b341">observación</b>: el bot dispara señales solo,
        basado en 4 condiciones evaluadas en tiempo real —
        <b style="color:#e3b341">Fractal</b> (piso/techo confirmado),
        <b style="color:#e3b341">Sentimiento</b> en nivel extremo,
        <b style="color:#e3b341">Z-Score</b> del precio y
        <b style="color:#e3b341">RSI</b> en sobrecompra/sobreventa—
        y las va tomando <b style="color:#a371f7">automáticamente</b>, sin que haga falta
        aceptar ni rechazar nada. Si el precio se acerca al Stop sin llegar a tocarlo, el bot
        <b style="color:#a371f7">rebalancea</b> (promedia) y recalcula el Stop/TP solo.
        La simulación de capital se arma directamente sobre el
        <b style="color:#e3b341">historial de señales disparadas</b> de cada activo, con un
        capital inicial configurable <b style="color:#e3b341">desde USD 50</b>
        y podés ver cómo hubiera rendido con <b style="color:#e3b341">apalancamiento de 1x a 5x</b>
        sobre la misma secuencia de operaciones. Analizá hasta
        <b style="color:#e3b341">10 activos</b> en simultáneo, en velas de
        <b style="color:#e3b341">5, 15, 30 minutos, 1 hora o 4 horas</b>.
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
                      'promediar. No espera a que el precio toque el Stop. Es automático.'),
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

    with st.expander('💰 Capital simulado y apalancamiento', expanded=True):
        cfg_bot_user = _bot_obtener_config(supabase, user_id)
        cb1, cb2, cb3 = st.columns(3)
        with cb1:
            capital_inicial_bot = st.number_input(
                'Capital inicial simulado (USD)', min_value=CAPITAL_MINIMO_BOT,
                value=float(cfg_bot_user.get('capital_inicial', CAPITAL_INICIAL_BOT_DEFAULT)),
                step=10.0, key='bot_capital_inicial',
                help=f'Mínimo USD {CAPITAL_MINIMO_BOT:,.0f}. Todas las curvas de rendimiento —para cualquier apalancamiento— arrancan acá.',
            )
        with cb2:
            pct_por_operacion_bot = st.number_input(
                '% de capital por operación', min_value=1.0, max_value=100.0,
                value=float(cfg_bot_user.get('pct_por_operacion', 10.0)), step=1.0, key='bot_pct_operacion',
                help='Se aplica sobre el capital simulado (compone con cada operación cerrada).',
            )
        with cb3:
            apalancamiento_bot = st.select_slider(
                'Apalancamiento a visualizar', options=APALANCAMIENTOS_BOT,
                value=int(cfg_bot_user.get('apalancamiento', 1)) if int(cfg_bot_user.get('apalancamiento', 1)) in APALANCAMIENTOS_BOT else 1,
                key='bot_apalancamiento',
            )
        st.caption(
            'La simulación recorre, en orden cronológico, el historial de señales disparadas de cada '
            'activo (con su ✅/❌/⏳ y su rebalanceo) y va componiendo el capital desde el monto inicial '
            'elegido arriba — no depende de sesiones anteriores, se arma de nuevo en cada corrida.'
        )
        if st.button('💾 Guardar configuración', key='bot_guardar_config'):
            _bot_guardar_config(supabase, user_id, capital_inicial_bot, pct_por_operacion_bot, apalancamiento_bot)
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
        df_bot = _evaluar_señales_con_rebalanceo(
            df_bot, rebalanceo_umbral_pct, rebalanceo_pct_capital,
            stop_pct_100, stop_pct_50, tp_pct_100, tp_pct_50,
        )
        resultados_bot[tk] = df_bot

    if fallidos:
        st.warning(f"⚠️ No se pudo descargar/calcular para: {', '.join(fallidos)} "
                    "(puede ser un símbolo sin datos intradía en Yahoo Finance, o límite temporal).")

    if not resultados_bot:
        st.error('No se pudo calcular ninguna señal con los activos seleccionados.')
        return
    st.caption(
        f"🕐 {datetime.now().strftime('%H:%M:%S')} · Temporalidad {horizonte_bot} · "
        f"caché de precios: 20s · tocá '🔄 Actualizar precios ahora' para forzar la recarga."
    )

    # ── Resumen multi-activo ─────────────────────────────────────────
    st.markdown('### 📋 Resumen — señal actual por activo')
    filas_resumen = []
    for tk, df_bot in resultados_bot.items():
        u = df_bot.iloc[-1]
        disparos_tk = df_bot[df_bot['disparo'] & (df_bot['estado'] != '—') & (df_bot['tomada'] == True)]
        n_no_tomadas_tk = int((df_bot['disparo'] & (df_bot['estado'] != '—') & (~df_bot['tomada'])).sum())
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
            'Track record': f'{n_ok}✅ {n_bad}❌ {n_open}⏳' + (f' · {n_no_tomadas_tk}⛔' if n_no_tomadas_tk else ''),
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

    # La simulación se corre antes de armar la tabla de historial para poder
    # mostrar, en esa misma tabla, cuántos USD representó cada entrada real
    # (1ra, 2da y 3ra) según el capital/% por operación/apalancamiento
    # elegidos arriba.
    rend = _bot_simular_en_memoria(df_bot_sel, capital_inicial_bot, pct_por_operacion_bot,
                                     apalancamiento_bot, rebalanceo_pct_capital)
    montos = rend['montos']

    st.markdown('#### 📋 Historial de señales disparadas')
    df_hist = df_bot_sel[df_bot_sel['disparo']].copy().sort_index(ascending=False)
    if df_hist.empty:
        st.info('No se disparó ninguna señal en el período analizado con los parámetros actuales.')
    else:
        def _monto(ts, clave):
            m = montos.get(ts)
            if not m or m.get(clave) is None:
                return '—'
            return f"USD {m[clave]:,.2f}"

        df_hist_show = pd.DataFrame({
            'Fecha/Hora': df_hist.index.strftime('%Y-%m-%d %H:%M'),
            'Señal': df_hist['estado'],
            'Tomada': df_hist['tomada'].apply(lambda v: 'Sí' if v else 'No'),
            'Resultado': df_hist['resultado'].apply(lambda v: 'No tomada' if v == '⛔' else v),
            '1ra entrada': df_hist['precio'].apply(fmt_precio),
            'Monto 1ra': [_monto(ts, 'e1') for ts in df_hist.index],
            '2da entrada': df_hist['entrada2_precio'].apply(lambda v: fmt_precio(v) if pd.notna(v) else '—'),
            'Monto 2da': [_monto(ts, 'e2') for ts in df_hist.index],
            '3ra entrada': df_hist['entrada3_precio'].apply(lambda v: fmt_precio(v) if pd.notna(v) else '—'),
            'Monto 3ra': [_monto(ts, 'e3') for ts in df_hist.index],
            'Precio promedio': df_hist['precio_promedio'].apply(lambda v: fmt_precio(v) if pd.notna(v) else '—'),
            'Stop vigente': df_hist['stop_vigente'].apply(lambda v: fmt_precio(v) if pd.notna(v) else '—'),
            'TP vigente': df_hist['tp_vigente'].apply(lambda v: fmt_precio(v) if pd.notna(v) else '—'),
            'Precio Result.': df_hist['precio_resultado'].apply(lambda v: fmt_precio(v) if pd.notna(v) else '—'),
            'Velas hasta result.': df_hist['barras_hasta_resultado'].apply(lambda v: int(v) if pd.notna(v) else '—'),
            'Fractal': df_hist.apply(_marca_fractal, axis=1),
            'Sent': df_hist['sc_sent'].round(1),
            'Z-Score': df_hist['zscore'].round(2),
            'RSI': df_hist['rsi'].round(1),
            'Cond V': df_hist['count_venta'].astype(int).astype(str) + '/4',
            'Cond C': df_hist['count_compra'].astype(int).astype(str) + '/4',
        })
        _color_tomada = lambda v: 'color:#8b949e' if v == 'No' else 'color:#3fb950;font-weight:700'
        styled_hist = (df_hist_show.style
            .pipe(lambda s: getattr(s, _map)(_color_señal_bot, subset=['Señal']))
            .pipe(lambda s: getattr(s, _map)(_color_resultado, subset=['Resultado']))
            .pipe(lambda s: getattr(s, _map)(_color_tomada, subset=['Tomada']))
            .set_properties(**{'background-color': '#0d1117', 'color': '#e6edf3', 'border': '1px solid #21262d'})
            .set_table_styles([
                {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', '#e6edf3'),
                    ('font-weight', '700'), ('text-align', 'center'),
                    ('border-bottom', '2px solid #3a7bd5'), ('font-size', '11px')]},
                {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]},
            ]))
        st.dataframe(styled_hist, use_container_width=True, height=min(500, len(df_hist_show) * 38 + 45))
        n_no_tomadas = int((~df_hist['tomada']).sum())
        st.caption(
            f'{len(df_hist_show)} señales disparadas en el historial analizado ({cfg["periodo_descarga"]} · '
            f'{horizonte_bot}) · {n_no_tomadas} no tomadas por tener otra operación abierta en ese momento. '
            'El Resultado, el Stop/TP "vigente" y los montos de cada entrada ya tienen en cuenta el rebalanceo '
            'y el capital simulado — son los mismos que usa la simulación de rendimiento de abajo, así que el '
            'Win Rate cierra en toda la pantalla.'
        )


    st.markdown('---')
    st.markdown(f'### 📈 Rendimiento simulado — {ticker_detalle} (apalancamiento {apalancamiento_bot}x)')
    st.caption(
        'Se recorre, en orden cronológico, el historial de señales TOMADAS de arriba (con su '
        'rebalanceo simulado) y se va componiendo el capital desde el monto inicial elegido.'
    )

    if rend['total_señales'] == 0:
        st.info('No se disparó ninguna señal de este activo en el período analizado — el rendimiento se arma solo cuando aparecen operaciones.')
    else:
        color_rend = '#3fb950' if rend['rendimiento_pct'] >= 0 else '#f85149'
        kpi_cards_4([
            ('Capital Simulado', f"USD {rend['capital_actual']:,.2f}",
             f"Inicial: USD {rend['capital_inicial']:,.2f} · {apalancamiento_bot}x", color_rend),
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
            title=dict(text=f'Evolución del capital simulado ({apalancamiento_bot}x)', font=dict(size=13)),
            xaxis=dict(gridcolor='#21262d'), yaxis=dict(gridcolor='#21262d', title='USD'),
            margin=dict(l=10, r=10, t=45, b=10),
        )
        st.plotly_chart(fig_eq, use_container_width=True, config=PLOTLY_CONFIG, key='bot_equity_fig')
        st.caption(
            'Todas las señales del historial se cuentan automáticamente, no hay sesgo de selección '
            'manual. Cada operación arriesga el % de capital configurado sobre el capital SIMULADO en '
            'ese momento (capital compuesto), multiplicado por el apalancamiento elegido. Si la '
            'operación fue rebalanceada, el resultado se calcula sobre el precio promedio y el Stop/TP '
            'recalculados. Las operaciones "en curso" (⏳) todavía no suman ni restan al capital.'
        )

        st.markdown('#### ⚖️ Comparativa por apalancamiento')
        st.caption(f'Misma secuencia de señales de {ticker_detalle}, simulada con cada nivel de apalancamiento.')
        filas_comp = []
        for lev in APALANCAMIENTOS_BOT:
            r_lev = rend if lev == apalancamiento_bot else \
                _bot_simular_en_memoria(df_bot_sel, capital_inicial_bot, pct_por_operacion_bot, lev, rebalanceo_pct_capital)
            filas_comp.append({
                'Apalancamiento': f'{lev}x' + (' ← actual' if lev == apalancamiento_bot else ''),
                'Capital final (USD)': round(r_lev['capital_actual'], 2),
                'Rendimiento': f"{r_lev['rendimiento_pct']:+.2f}%",
                'Cerradas': r_lev['cerradas'],
                'Win Rate': f"{r_lev['win_rate']:.0f}%" if r_lev['win_rate'] is not None else 'N/D',
            })
        df_comp = pd.DataFrame(filas_comp)
        st.dataframe(df_comp, use_container_width=True, height=min(260, len(df_comp) * 38 + 45), hide_index=True)

    with st.expander('❓ Cómo funciona esta señal'):
        st.markdown(f"""
        Cada barra se evalúa contra 4 condiciones por lado: **Fractal** (piso/techo confirmado con
        barras de izquierda/derecha), **Sentimiento** (percentil del precio dentro del rango elegido),
        **Z-Score** (desvíos respecto a la media móvil) y **RSI** (nivel de sobrecompra/sobreventa).

        - **4 de 4 condiciones cumplidas** → señal **completa** (mostrada como "100%"), con el Stop y
          Take Profit más amplios que configuraste.
        - **3 de 4 condiciones cumplidas** → **entrada anticipada** (mostrada como "50%"), más débil
          y con su propio Stop/TP.

        Cada señal disparada se evalúa hacia adelante: se marca **✅** si el precio tocó primero el
        Take Profit, **❌** si tocó primero el Stop, y **⏳ En curso** si todavía no definió.

        **🤖 Todo es automático**: no hay botones de Aceptar/Rechazar. Cada señal que dispara el bot
        queda registrada en el historial y forma parte del rendimiento simulado — esta herramienta es
        para observar el comportamiento del bot, no para decidir manualmente sobre cada operación.

        **🚫 Sin solapamiento**: si aparece una señal nueva mientras el bot todavía tiene una operación
        abierta de ese mismo activo (una anterior que no cerró ✅ ni ❌), esa señal NO se toma — queda
        marcada como **"No tomada"** en el historial (Resultado ⛔), para que veas que el bot la vio pero
        no operó. No afecta el capital ni el Win Rate.

        **🔁 Rebalanceo (hasta 3 entradas)**: si el precio recorre el % configurado del camino hacia el
        Stop vigente (por defecto 80%) SIN llegar a tocarlo, el bot dispara una entrada adicional de
        tamaño = % configurable del capital de la 1ra entrada, calcula un **precio promedio** ponderado
        por cantidad (capital ÷ precio, como promediar acciones o contratos reales), y sobre ese promedio
        recalcula el Stop y el TP usando los **mismos %** que configuraste originalmente. Esto puede
        repetirse una vez más (3ra entrada), usando como referencia el nuevo promedio y el nuevo Stop.
        De ahí en más, el resultado de la operación se evalúa contra el Stop/TP más recientes. Todo este
        cálculo se hace al vuelo, sobre el historial de señales disparadas que ves más arriba — no queda
        nada guardado entre sesiones.

        **💵 Monto de cada entrada**: en la tabla de historial, "Monto 1ra/2da/3ra" muestra cuántos USD
        representó cada entrada real, calculados con el % de capital por operación y el capital simulado
        en ese momento (compuesto) — la 2da y 3ra entrada son el % de rebalanceo configurado sobre esa
        misma 1ra entrada.

        **💰 Capital simulado y apalancamiento**: el capital inicial es **configurable, desde
        USD {CAPITAL_MINIMO_BOT:,.0f}**. Cada operación arriesga el % de capital configurado sobre
        el capital simulado en ese momento (compuesto), multiplicado por el apalancamiento elegido
        (1x a 5x). Podés comparar los 5 niveles sobre la misma secuencia de señales de este activo en
        la tabla "Comparativa por apalancamiento". La pérdida de una operación individual nunca supera
        el 100% del capital arriesgado en la 1ra entrada (simula que se liquida esa posición puntual).

        ⚠️ **Importante**: si NO se llegó a rebalancear una operación, el Stop se sigue tratando como
        una salida total. Solo cuando el bot rebalancea de verdad se está "promediando en vez de cerrar";
        el resto del tiempo, tocar el Stop vigente todavía implica cerrar la posición con esa pérdida.

        Usalo como medida de calidad de la señal, no como tu resultado real de trading.
        """)
