# ==============================================================
#  MÓDULO BOT DE INVERSIÓN — Rango + Volatilidad + Rejilla + Trailing
#  Versión intradía: temporalidades 5/15/30 min, 1h y 4h, multi-activo (hasta 10)
#
#  v6: se REEMPLAZA por completo el motor anterior (Fractal + Sentimiento +
#      Z-Score + RSI, Pine v15) por un motor nuevo, de un solo tipo de
#      operación por activo a la vez ("holdeo"):
#
#        1) RANGO: canal de Donchian (máximo/mínimo de N velas) — define
#           el techo y el piso donde se mueve el precio.
#        2) VOLATILIDAD: ATR (rango verdadero promedio) — es la unidad de
#           medida de todo lo demás (rejilla, activación de trailing,
#           distancia del trailing, stop duro).
#        3) REJILLA: cuando el precio entra en la zona baja del rango
#           (cerca del piso) el bot abre una posición COMPRA; si entra en
#           la zona alta (cerca del techo), abre VENTA. Si el precio sigue
#           moviéndose en contra en pasos de X × ATR, el bot agrega nuevas
#           entradas (hasta un máximo configurable), recalculando el
#           precio promedio — igual espíritu que el "rebalanceo" de la
#           versión anterior, pero ahora es la forma NORMAL de operar
#           (rejilla), no una excepción.
#        4) HOLDEO: el bot sostiene la posición (todas las entradas de la
#           rejilla juntas) hasta que se activa y toca el trailing, o hasta
#           que se rompe el stop duro (por fuera del rango, en unidades de
#           ATR) — no hay Take Profit fijo.
#        5) TRAILING (por volatilidad): una vez que el precio avanzó a
#           favor una cierta cantidad de ATR desde el precio promedio, se
#           activa un trailing stop = precio extremo alcanzado ∓ X × ATR,
#           que se va ajustando (ratchet) a favor de la posición. El cierre
#           se marca ✅ si el trailing se activó por encima del precio
#           promedio (ganancia) o ❌ si el cierre fue por el stop duro o
#           por un trailing que quedó por debajo del promedio.
#
#      Solo puede haber UNA posición abierta por activo a la vez (no se
#      abren posiciones nuevas mientras el bot sigue "holdeando" la
#      anterior), igual que en la versión anterior no se permitía
#      solapamiento.
# ==============================================================

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

MAX_ACTIVOS_BOT = 10

CAPITAL_MINIMO_BOT = 50.0
CAPITAL_INICIAL_BOT_DEFAULT = 100.0

APALANCAMIENTOS_BOT = [1, 2, 3, 4, 5]

# yfinance permite hasta 60 días de historia para velas de 5m/15m/30m,
# y hasta 730 días para velas de 60m. No existe intervalo nativo de 4h:
# se arma resampleando velas de 60m (agrupando OHLC de a 4 en 4).
HORIZONTES_BOT = {
    '5 minutos': dict(
        interval='5m', periodo_descarga='60d', resample=None, minutos_vela=5,
    ),
    '15 minutos': dict(
        interval='15m', periodo_descarga='60d', resample=None, minutos_vela=15,
    ),
    '30 minutos': dict(
        interval='30m', periodo_descarga='60d', resample=None, minutos_vela=30,
    ),
    '1 hora': dict(
        interval='60m', periodo_descarga='730d', resample=None, minutos_vela=60,
    ),
    '4 horas': dict(
        interval='60m', periodo_descarga='730d', resample='4h', minutos_vela=240,
    ),
}

C_BOT_HOLD_COMPRA  = '#3fb950'
C_BOT_HOLD_VENTA   = '#f85149'
C_BOT_TRAILING     = '#a371f7'
C_BOT_GRID_ENTRADA = '#e3b341'
C_BOT_CIERRE_OK    = '#3fb950'
C_BOT_CIERRE_BAD   = '#f85149'


# ── Volatilidad y rango ────────────────────────────────────────────────

def _atr(high, low, close, periodo):
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(periodo, min_periods=max(3, periodo // 3)).mean()


def _donchian(high, low, periodo):
    r_high = high.rolling(periodo, min_periods=max(5, periodo // 3)).max()
    r_low = low.rolling(periodo, min_periods=max(5, periodo // 3)).min()
    return r_high, r_low


# ── Motor: rango + volatilidad + rejilla + holdeo + trailing ──────────

def _motor_grid_trailing(close, high, low,
                          atr_periodo, rango_periodo,
                          grid_step_atr, zona_compra_pct, zona_venta_pct,
                          max_niveles, pct_capital_nivel,
                          trailing_activacion_atr, trailing_atr_mult,
                          hard_stop_atr_mult):
    """Recorre las velas en orden y arma, en un solo pase con estado, tanto
    la serie continua (para el gráfico) como la lista de operaciones
    ('trades': cada una es un ciclo completo de holdeo, desde que se abre
    la 1ra entrada hasta que se cierra por trailing o por stop duro, o
    queda '⏳ en curso' si todavía está abierta al final de los datos)."""
    cl = close.dropna()
    hi = high.reindex(cl.index)
    lo = low.reindex(cl.index)

    atr = _atr(hi, lo, cl, atr_periodo)
    r_high, r_low = _donchian(hi, lo, rango_periodo)
    rango_amplitud = (r_high - r_low).replace(0, np.nan)
    pos_pct = ((cl - r_low) / rango_amplitud * 100).clip(0, 100)

    idx = cl.index
    n = len(cl)
    precio_arr = cl.values
    hi_arr = hi.values
    lo_arr = lo.values
    atr_arr = atr.values
    rhigh_arr = r_high.values
    rlow_arr = r_low.values
    pos_arr = pos_pct.values

    estado = ['—'] * n
    evento = [''] * n
    precio_promedio_serie = [np.nan] * n
    trailing_activo_serie = [False] * n
    trailing_stop_serie = [np.nan] * n
    hard_stop_serie = [np.nan] * n

    trades = []
    pos_actual = None  # dict con el estado de la posición abierta

    for i in range(n):
        precio = precio_arr[i]
        a = atr_arr[i]
        if np.isnan(precio) or np.isnan(a) or np.isnan(pos_arr[i]):
            continue

        if pos_actual is None:
            if pos_arr[i] <= zona_compra_pct:
                pos_actual = dict(
                    direccion='COMPRA', fecha_apertura=idx[i],
                    entradas=[precio], fechas_entradas=[idx[i]], pesos=[1.0],
                    precio_prom=precio, extremo=hi_arr[i],
                    trailing_activo=False, trailing_stop=np.nan,
                    hard_stop=rlow_arr[i] - hard_stop_atr_mult * a,
                )
            elif pos_arr[i] >= zona_venta_pct:
                pos_actual = dict(
                    direccion='VENTA', fecha_apertura=idx[i],
                    entradas=[precio], fechas_entradas=[idx[i]], pesos=[1.0],
                    precio_prom=precio, extremo=lo_arr[i],
                    trailing_activo=False, trailing_stop=np.nan,
                    hard_stop=rhigh_arr[i] + hard_stop_atr_mult * a,
                )
            if pos_actual is not None:
                trades.append(pos_actual)
                estado[i] = f"HOLD {pos_actual['direccion']}"
                evento[i] = 'Entrada 1'
                precio_promedio_serie[i] = pos_actual['precio_prom']
                hard_stop_serie[i] = pos_actual['hard_stop']
            continue

        # ── hay una posición abierta: actualizarla ──
        d = pos_actual['direccion']
        estado[i] = f'HOLD {d}'

        if d == 'COMPRA':
            pos_actual['extremo'] = max(pos_actual['extremo'], hi_arr[i])
        else:
            pos_actual['extremo'] = min(pos_actual['extremo'], lo_arr[i])

        # -- nueva entrada de rejilla (promediar) si el precio siguió en contra --
        if len(pos_actual['entradas']) < max_niveles:
            distancia = (pos_actual['precio_prom'] - precio) if d == 'COMPRA' \
                else (precio - pos_actual['precio_prom'])
            if distancia >= grid_step_atr * a:
                peso_nuevo = pos_actual['pesos'][0] * (pct_capital_nivel / 100.0)
                pos_actual['entradas'].append(precio)
                pos_actual['fechas_entradas'].append(idx[i])
                pos_actual['pesos'].append(peso_nuevo)
                cantidad_total = sum(w / p for w, p in zip(pos_actual['pesos'], pos_actual['entradas']))
                capital_total = sum(pos_actual['pesos'])
                pos_actual['precio_prom'] = capital_total / cantidad_total
                evento[i] = f"Entrada {len(pos_actual['entradas'])} (rejilla)"

        # -- stop duro: se recalcula contra el rango vigente, solo se endurece --
        if d == 'COMPRA':
            candidato = rlow_arr[i] - hard_stop_atr_mult * a
            pos_actual['hard_stop'] = max(pos_actual['hard_stop'], candidato) \
                if not np.isnan(pos_actual['hard_stop']) else candidato
        else:
            candidato = rhigh_arr[i] + hard_stop_atr_mult * a
            pos_actual['hard_stop'] = min(pos_actual['hard_stop'], candidato) \
                if not np.isnan(pos_actual['hard_stop']) else candidato

        # -- activación del trailing --
        if not pos_actual['trailing_activo']:
            avance = (precio - pos_actual['precio_prom']) if d == 'COMPRA' \
                else (pos_actual['precio_prom'] - precio)
            if avance >= trailing_activacion_atr * a:
                pos_actual['trailing_activo'] = True
                pos_actual['fecha_trailing_activado'] = idx[i]
                if evento[i] == '':
                    evento[i] = 'Trailing activado'

        # -- ratchet del trailing stop --
        if pos_actual['trailing_activo']:
            if d == 'COMPRA':
                nuevo = pos_actual['extremo'] - trailing_atr_mult * a
                pos_actual['trailing_stop'] = max(pos_actual['trailing_stop'], nuevo) \
                    if not np.isnan(pos_actual['trailing_stop']) else nuevo
            else:
                nuevo = pos_actual['extremo'] + trailing_atr_mult * a
                pos_actual['trailing_stop'] = min(pos_actual['trailing_stop'], nuevo) \
                    if not np.isnan(pos_actual['trailing_stop']) else nuevo

        precio_promedio_serie[i] = pos_actual['precio_prom']
        trailing_activo_serie[i] = pos_actual['trailing_activo']
        trailing_stop_serie[i] = pos_actual['trailing_stop']
        hard_stop_serie[i] = pos_actual['hard_stop']

        # -- chequeo de cierre (con máximo/mínimo intravela) --
        cerro, res, precio_cierre = False, None, None
        if d == 'COMPRA':
            if pos_actual['trailing_activo'] and lo_arr[i] <= pos_actual['trailing_stop']:
                precio_cierre = pos_actual['trailing_stop']
                res = '✅' if precio_cierre >= pos_actual['precio_prom'] else '❌'
                cerro = True
            elif not pos_actual['trailing_activo'] and lo_arr[i] <= pos_actual['hard_stop']:
                precio_cierre = pos_actual['hard_stop']
                res = '❌'
                cerro = True
        else:
            if pos_actual['trailing_activo'] and hi_arr[i] >= pos_actual['trailing_stop']:
                precio_cierre = pos_actual['trailing_stop']
                res = '✅' if precio_cierre <= pos_actual['precio_prom'] else '❌'
                cerro = True
            elif not pos_actual['trailing_activo'] and hi_arr[i] >= pos_actual['hard_stop']:
                precio_cierre = pos_actual['hard_stop']
                res = '❌'
                cerro = True

        if cerro:
            retorno_pct = (precio_cierre - pos_actual['precio_prom']) / pos_actual['precio_prom'] * 100 \
                if d == 'COMPRA' else (pos_actual['precio_prom'] - precio_cierre) / pos_actual['precio_prom'] * 100
            pos_actual['resultado'] = res
            pos_actual['precio_cierre'] = precio_cierre
            pos_actual['fecha_cierre'] = idx[i]
            pos_actual['retorno_pct'] = retorno_pct
            pos_actual['velas_hasta_cierre'] = i  # se corrige a "relativas" más abajo
            evento[i] = 'Cierre ✅' if res == '✅' else 'Cierre ❌'
            pos_actual = None

    # posición que sigue abierta al final de los datos: queda "en curso"
    if pos_actual is not None:
        precio_last = precio_arr[-1]
        d = pos_actual['direccion']
        pos_actual['resultado'] = '⏳'
        pos_actual['precio_cierre'] = np.nan
        pos_actual['fecha_cierre'] = pd.NaT
        pos_actual['retorno_pct'] = (precio_last - pos_actual['precio_prom']) / pos_actual['precio_prom'] * 100 \
            if d == 'COMPRA' else (pos_actual['precio_prom'] - precio_last) / pos_actual['precio_prom'] * 100
        pos_actual['velas_hasta_cierre'] = np.nan

    # convertir "velas_hasta_cierre" (índice absoluto) a relativas a la apertura
    idx_pos = {ts: k for k, ts in enumerate(idx)}
    for t in trades:
        if pd.notna(t.get('fecha_cierre', pd.NaT)):
            t['velas_hasta_cierre'] = idx_pos[t['fecha_cierre']] - idx_pos[t['fecha_apertura']]

    df = pd.DataFrame({
        'precio': cl, 'high': hi, 'low': lo, 'atr': atr,
        'range_high': r_high, 'range_low': r_low, 'pos_pct': pos_pct,
        'estado': estado, 'evento': evento,
        'precio_promedio': precio_promedio_serie,
        'trailing_activo': trailing_activo_serie,
        'trailing_stop': trailing_stop_serie, 'hard_stop': hard_stop_serie,
    }, index=idx)
    return df, trades


def _trades_a_dataframe(trades, fmt_precio):
    if not trades:
        return pd.DataFrame()
    filas = []
    for t in trades:
        n_ent = len(t['entradas'])
        filas.append({
            'Apertura': t['fecha_apertura'],
            'Dirección': t['direccion'],
            'Entradas': n_ent,
            '1ra entrada': fmt_precio(t['entradas'][0]),
            '2da entrada': fmt_precio(t['entradas'][1]) if n_ent >= 2 else '—',
            '3ra entrada': fmt_precio(t['entradas'][2]) if n_ent >= 3 else '—',
            'Precio promedio': fmt_precio(t['precio_prom']),
            'Trailing activado': 'Sí' if t.get('trailing_activo') else 'No',
            'Trailing stop': fmt_precio(t['trailing_stop']) if not pd.isna(t.get('trailing_stop', np.nan)) else '—',
            'Stop duro': fmt_precio(t['hard_stop']) if not pd.isna(t.get('hard_stop', np.nan)) else '—',
            'Resultado': t['resultado'],
            'Cierre': t['fecha_cierre'].strftime('%Y-%m-%d %H:%M') if pd.notna(t.get('fecha_cierre', pd.NaT)) else '—',
            'Precio cierre': fmt_precio(t['precio_cierre']) if not pd.isna(t.get('precio_cierre', np.nan)) else '—',
            'Retorno %': f"{t['retorno_pct']:+.2f}%" if not pd.isna(t.get('retorno_pct', np.nan)) else '—',
            'Velas hasta cierre': int(t['velas_hasta_cierre']) if not pd.isna(t.get('velas_hasta_cierre', np.nan)) else '—',
        })
    df = pd.DataFrame(filas).sort_values('Apertura', ascending=False)
    df['Apertura'] = df['Apertura'].dt.strftime('%Y-%m-%d %H:%M')
    return df


def _color_resultado(val):
    return {'✅': f'color:{C_BOT_CIERRE_OK};font-weight:700',
            '❌': f'color:{C_BOT_CIERRE_BAD};font-weight:700',
            '⏳': 'color:#e3b341;font-weight:600'}.get(val, '')


def _color_direccion(val):
    c = C_BOT_HOLD_COMPRA if val == 'COMPRA' else C_BOT_HOLD_VENTA
    return f'color:{c};font-weight:700'


# ── Persistencia en Supabase: solo configuración de capital/apalancamiento ─

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


# ── Simulación de rendimiento — 100% en memoria, sobre la lista de trades ──
#
# Recorre los ciclos de holdeo (apertura → cierre) en orden cronológico y
# va componiendo el capital simulado. El tamaño de cada entrada (1ra, 2da,
# 3ra) se calcula sobre el capital simulado vigente al momento de abrir esa
# operación (compuesto), igual que la 1ra entrada; la 2da y 3ra son el %
# de rejilla configurado sobre esa misma 1ra entrada. El Win Rate depende
# solo de la secuencia de trades (no del apalancamiento ni del capital).

def _bot_simular_en_memoria(trades, capital_inicial, pct_por_operacion, apalancamiento,
                             pct_capital_nivel):
    cerrados = [t for t in trades if t['resultado'] in ('✅', '❌')]
    cerrados = sorted(cerrados, key=lambda t: t['fecha_apertura'])
    equity = capital_inicial
    curva = [{'fecha': 'Inicio', 'equity': equity}]
    ganadoras = 0
    rebalanceos = 0
    montos = {}
    pnl_por_trade = {}

    for t in cerrados:
        n_ent = len(t['entradas'])
        if n_ent > 1:
            rebalanceos += 1
        capital_operado = equity * (pct_por_operacion / 100.0)
        monto_e2 = capital_operado * (pct_capital_nivel / 100.0) if n_ent >= 2 else None
        monto_e3 = capital_operado * (pct_capital_nivel / 100.0) if n_ent >= 3 else None
        capital_total = capital_operado + (monto_e2 or 0) + (monto_e3 or 0)
        montos[t['fecha_apertura']] = {'e1': capital_operado, 'e2': monto_e2, 'e3': monto_e3, 'total': capital_total}

        pnl = capital_total * (t['retorno_pct'] / 100.0) * apalancamiento
        pnl = max(pnl, -capital_total)  # la pérdida nunca supera el capital arriesgado en el ciclo
        equity += pnl
        pnl_por_trade[t['fecha_apertura']] = pnl
        if t['resultado'] == '✅':
            ganadoras += 1
        curva.append({'fecha': t['fecha_cierre'].strftime('%Y-%m-%d %H:%M'), 'equity': equity})

    cerradas_n = len(cerrados)
    abiertas_n = sum(1 for t in trades if t['resultado'] == '⏳')

    return {
        'capital_inicial': capital_inicial, 'capital_actual': equity,
        'rendimiento_pct': (equity / capital_inicial - 1) * 100 if capital_inicial else 0.0,
        'win_rate': (ganadoras / cerradas_n * 100) if cerradas_n > 0 else None,
        'cerradas': cerradas_n, 'ganadoras': ganadoras, 'perdedoras': cerradas_n - ganadoras,
        'abiertas': abiertas_n, 'total_trades': len(trades), 'curva': curva,
        'rebalanceos': rebalanceos, 'apalancamiento': apalancamiento, 'montos': montos,
        'pnl_por_trade': pnl_por_trade,
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


# ── Gráfico: precio + rango (Donchian) + eventos del bot ──────────────

def _fig_bot_grid(ticker, df, trades, PLOTLY_LAYOUT_BASE):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df['precio'], line=dict(color='#3a7bd5', width=1.8), name='Precio'))
    fig.add_trace(go.Scatter(x=df.index, y=df['range_high'], line=dict(color='#8b949e', width=1, dash='dot'),
                              name='Techo del rango'))
    fig.add_trace(go.Scatter(x=df.index, y=df['range_low'], line=dict(color='#8b949e', width=1, dash='dot'),
                              name='Piso del rango', fill='tonexty', fillcolor='rgba(139,148,158,0.05)'))

    aperturas_c = [t['fecha_apertura'] for t in trades if t['direccion'] == 'COMPRA']
    aperturas_v = [t['fecha_apertura'] for t in trades if t['direccion'] == 'VENTA']
    cierres_ok = [t['fecha_cierre'] for t in trades if t['resultado'] == '✅']
    cierres_bad = [t['fecha_cierre'] for t in trades if t['resultado'] == '❌']

    def _y(fechas):
        return [df.loc[f, 'precio'] for f in fechas if f in df.index]

    if aperturas_c:
        fig.add_trace(go.Scatter(x=aperturas_c, y=_y(aperturas_c), mode='markers', name='Apertura COMPRA',
                                  marker=dict(size=11, color=C_BOT_HOLD_COMPRA, symbol='triangle-up',
                                              line=dict(width=1, color='#0d1117'))))
    if aperturas_v:
        fig.add_trace(go.Scatter(x=aperturas_v, y=_y(aperturas_v), mode='markers', name='Apertura VENTA',
                                  marker=dict(size=11, color=C_BOT_HOLD_VENTA, symbol='triangle-down',
                                              line=dict(width=1, color='#0d1117'))))
    if cierres_ok:
        fig.add_trace(go.Scatter(x=cierres_ok, y=_y(cierres_ok), mode='markers', name='Cierre ✅',
                                  marker=dict(size=10, color=C_BOT_CIERRE_OK, symbol='x')))
    if cierres_bad:
        fig.add_trace(go.Scatter(x=cierres_bad, y=_y(cierres_bad), mode='markers', name='Cierre ❌',
                                  marker=dict(size=10, color=C_BOT_CIERRE_BAD, symbol='x')))

    fig.update_layout(
        **PLOTLY_LAYOUT_BASE,
        title=dict(text=f'{ticker} — Rango, rejilla y trailing del bot', font=dict(size=14)),
        height=480, hovermode='x unified',
        legend=dict(orientation='h', y=1.1),
        xaxis=dict(gridcolor='#21262d'), yaxis=dict(gridcolor='#21262d'),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    return fig


def _color_estado(estado):
    if 'COMPRA' in estado:
        return C_BOT_HOLD_COMPRA
    if 'VENTA' in estado:
        return C_BOT_HOLD_VENTA
    return '#8b949e'


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
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">🤖 Bot de Inversión — Rango · Volatilidad · Rejilla · Trailing</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Herramienta de <b style="color:#e3b341">observación</b>: el bot detecta el
        <b style="color:#e3b341">Rango</b> del precio (canal de Donchian) y mide la
        <b style="color:#e3b341">Volatilidad</b> (ATR). Cuando el precio entra en la zona baja
        del rango abre una posición de <b style="color:#3fb950">COMPRA</b>, y en la zona alta,
        de <b style="color:#f85149">VENTA</b>. Si el precio sigue en contra en pasos de ATR,
        el bot agrega entradas a la <b style="color:#e3b341">rejilla</b> (promedia), y
        <b style="color:#a371f7">holdea</b> la posición hasta que un
        <b style="color:#a371f7">trailing stop</b> (también en unidades de ATR) se activa y
        se toca, o hasta que se rompe un stop duro fuera del rango. Todo es
        <b style="color:#a371f7">automático</b>: no hay botones de Aceptar/Rechazar. Analizá hasta
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
    tickers_bot = list(dict.fromkeys(tickers_bot))

    if len(tickers_bot) > MAX_ACTIVOS_BOT:
        st.warning(f'Se seleccionaron más de {MAX_ACTIVOS_BOT} activos — se van a analizar solo los primeros {MAX_ACTIVOS_BOT}.')
        tickers_bot = tickers_bot[:MAX_ACTIVOS_BOT]

    with st.expander('⚙️ Parámetros de la estrategia (opcional, aplican a todos los activos)', expanded=False):
        p1, p2 = st.columns(2)
        with p1:
            st.markdown('**📏 Rango (Donchian)**')
            rango_periodo = st.number_input('Período (velas)', value=50, min_value=10, key='bot_rango_periodo')
            zona_compra_pct = st.number_input('Zona COMPRA: hasta % del rango', value=20.0,
                                               min_value=1.0, max_value=49.0, step=1.0, key='bot_zona_compra')
            zona_venta_pct = st.number_input('Zona VENTA: desde % del rango', value=80.0,
                                              min_value=51.0, max_value=99.0, step=1.0, key='bot_zona_venta')
        with p2:
            st.markdown('**📊 Volatilidad (ATR)**')
            atr_periodo = st.number_input('Período ATR (velas)', value=14, min_value=3, key='bot_atr_periodo')
            hard_stop_atr_mult = st.number_input('Stop duro: × ATR más allá del rango', value=1.0,
                                                  min_value=0.1, step=0.1, key='bot_hard_stop_atr')

        p3, p4 = st.columns(2)
        with p3:
            st.markdown('**🔲 Rejilla (holdeo)**')
            grid_step_atr = st.number_input('Nueva entrada cada × ATR en contra', value=1.0,
                                             min_value=0.1, step=0.1, key='bot_grid_step_atr')
            max_niveles = st.number_input('Máximo de entradas por ciclo', value=3, min_value=1, max_value=6,
                                           key='bot_max_niveles')
            pct_capital_nivel = st.number_input('Tamaño de cada entrada extra (% de la 1ra)', value=50.0,
                                                 min_value=5.0, max_value=200.0, step=5.0, key='bot_pct_capital_nivel')
        with p4:
            st.markdown('**🎯 Trailing (por volatilidad)**')
            trailing_activacion_atr = st.number_input('Se activa tras avanzar × ATR a favor', value=1.0,
                                                        min_value=0.1, step=0.1, key='bot_trailing_activacion')
            trailing_atr_mult = st.number_input('Distancia del trailing: × ATR', value=1.5,
                                                 min_value=0.1, step=0.1, key='bot_trailing_atr_mult')

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
                '% de capital por ciclo (1ra entrada)', min_value=1.0, max_value=100.0,
                value=float(cfg_bot_user.get('pct_por_operacion', 10.0)), step=1.0, key='bot_pct_operacion',
                help='Se aplica sobre el capital simulado (compone con cada ciclo cerrado). La 2da/3ra entrada son el % de rejilla configurado sobre esta.',
            )
        with cb3:
            apalancamiento_bot = st.select_slider(
                'Apalancamiento a visualizar', options=APALANCAMIENTOS_BOT,
                value=int(cfg_bot_user.get('apalancamiento', 1)) if int(cfg_bot_user.get('apalancamiento', 1)) in APALANCAMIENTOS_BOT else 1,
                key='bot_apalancamiento',
            )
        st.caption(
            'La simulación recorre, en orden cronológico, los ciclos de holdeo (apertura → cierre) de cada '
            'activo y va componiendo el capital desde el monto inicial elegido arriba — no depende de sesiones '
            'anteriores, se arma de nuevo en cada corrida.'
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
    ventana_minima = max(rango_periodo, atr_periodo) + 20
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
        if cl is None or len(cl.dropna()) < ventana_minima:
            fallidos.append(tk)
            continue
        hi = df_raw['High'] if 'High' in df_raw.columns else cl
        lo = df_raw['Low'] if 'Low' in df_raw.columns else cl
        df_bot, trades = _motor_grid_trailing(
            cl, hi, lo,
            int(atr_periodo), int(rango_periodo),
            grid_step_atr, zona_compra_pct, zona_venta_pct,
            int(max_niveles), pct_capital_nivel,
            trailing_activacion_atr, trailing_atr_mult,
            hard_stop_atr_mult,
        )
        resultados_bot[tk] = {'df': df_bot, 'trades': trades}

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
    st.markdown('### 📋 Resumen — estado actual por activo')
    filas_resumen = []
    for tk, r in resultados_bot.items():
        df_bot, trades = r['df'], r['trades']
        u = df_bot.iloc[-1]
        cerrados_tk = [t for t in trades if t['resultado'] in ('✅', '❌')]
        n_ok = sum(1 for t in cerrados_tk if t['resultado'] == '✅')
        n_bad = len(cerrados_tk) - n_ok
        n_open = sum(1 for t in trades if t['resultado'] == '⏳')
        winrate = f'{n_ok / len(cerrados_tk) * 100:.0f}%' if cerrados_tk else 'N/D'
        n_entradas_actual = int((df_bot['precio_promedio'].notna() & (df_bot.index == df_bot.index[-1])).sum())
        filas_resumen.append({
            'Ticker': tk, 'Estado': u['estado'], 'Precio': fmt_precio(u['precio']),
            'Última vela': df_bot.index[-1].strftime('%H:%M:%S'),
            'Pos. en rango': f"{u['pos_pct']:.0f}%" if not pd.isna(u['pos_pct']) else '—',
            'ATR': fmt_precio(u['atr']) if not pd.isna(u['atr']) else '—',
            'Techo': fmt_precio(u['range_high']) if not pd.isna(u['range_high']) else '—',
            'Piso': fmt_precio(u['range_low']) if not pd.isna(u['range_low']) else '—',
            'Precio promedio': fmt_precio(u['precio_promedio']) if not pd.isna(u['precio_promedio']) else '—',
            'Trailing': 'Activo' if u['trailing_activo'] else ('Holdeando' if u['estado'] != '—' else '—'),
            'Stop vigente': (fmt_precio(u['trailing_stop']) if u['trailing_activo'] and not pd.isna(u['trailing_stop'])
                              else (fmt_precio(u['hard_stop']) if not pd.isna(u['hard_stop']) else '—')),
            'Track record': f'{n_ok}✅ {n_bad}❌ {n_open}⏳',
            'Win rate': winrate,
        })
    df_resumen = pd.DataFrame(filas_resumen)
    orden_prioridad = df_resumen['Estado'].apply(lambda e: 0 if e != '—' else 1)
    df_resumen = df_resumen.assign(_orden=orden_prioridad).sort_values('_orden').drop(columns=['_orden'])

    _map = 'map' if hasattr(df_resumen.style, 'map') else 'applymap'
    styled_resumen = (df_resumen.style
        .set_properties(**{'background-color': '#0d1117', 'color': '#e6edf3', 'border': '1px solid #21262d'})
        .set_table_styles([
            {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', '#e6edf3'),
                ('font-weight', '700'), ('text-align', 'center'),
                ('border-bottom', '2px solid #3a7bd5'), ('font-size', '11px')]},
            {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]},
        ]))
    st.dataframe(styled_resumen, use_container_width=True, height=min(400, len(df_resumen) * 40 + 45))
    chips_navegacion([(tk, tk) for tk in resultados_bot.keys()], 'bot_inversion_resumen')

    n_holdeando = int((df_resumen['Estado'] != '—').sum())
    if n_holdeando > 0:
        st.success(f'⚡ {n_holdeando} activo(s) con una posición holdeada ahora mismo.')

    # ── Detalle de un activo ─────────────────────────────────────────
    st.markdown('---')
    st.markdown('### 🔍 Detalle por activo')
    ticker_detalle = st.selectbox(
        'Elegí un activo para ver el gráfico y el historial completo',
        list(resultados_bot.keys()), key='bot_detalle_sel',
    )
    df_bot_sel = resultados_bot[ticker_detalle]['df']
    trades_sel = resultados_bot[ticker_detalle]['trades']
    ultimo = df_bot_sel.iloc[-1]
    estado_actual = ultimo['estado']
    color_estado = _color_estado(estado_actual)

    kpi_cards_4([
        ('Estado Actual', estado_actual, f'{ticker_detalle} · {horizonte_bot}', color_estado),
        ('Precio', fmt_precio(ultimo['precio']),
         f"Stop vigente: {(fmt_precio(ultimo['trailing_stop']) if ultimo['trailing_activo'] and not pd.isna(ultimo['trailing_stop']) else (fmt_precio(ultimo['hard_stop']) if not pd.isna(ultimo['hard_stop']) else '—'))}",
         '#3a7bd5'),
        ('Rango / Posición', f"{fmt_precio(ultimo['range_low'])} – {fmt_precio(ultimo['range_high'])}",
         f"Posición en el rango: {ultimo['pos_pct']:.0f}%" if not pd.isna(ultimo['pos_pct']) else '—',
         score_color_hex(ultimo['pos_pct']) if not pd.isna(ultimo['pos_pct']) else '#8b949e'),
        ('ATR / Trailing', fmt_precio(ultimo['atr']) if not pd.isna(ultimo['atr']) else '—',
         'Trailing activo' if ultimo['trailing_activo'] else 'Trailing no activado aún', '#e3b341'),
    ])

    st.plotly_chart(_fig_bot_grid(ticker_detalle, df_bot_sel, trades_sel, PLOTLY_LAYOUT_BASE),
                     use_container_width=True, config=PLOTLY_CONFIG, key=f'bot_fig_grid_{ticker_detalle}')

    rend = _bot_simular_en_memoria(trades_sel, capital_inicial_bot, pct_por_operacion_bot,
                                     apalancamiento_bot, pct_capital_nivel)
    montos = rend['montos']
    pnl_por_trade = rend['pnl_por_trade']

    st.markdown('#### 📋 Historial de ciclos (holdeos)')
    df_hist_show = _trades_a_dataframe(trades_sel, fmt_precio)
    if df_hist_show.empty:
        st.info('No se abrió ningún ciclo en el período analizado con los parámetros actuales.')
    else:
        fechas_apertura_ordenadas = [t['fecha_apertura'] for t in
                                      sorted(trades_sel, key=lambda t: t['fecha_apertura'], reverse=True)]

        def _monto(ts, clave):
            m = montos.get(ts)
            if not m or m.get(clave) is None:
                return '—'
            return f"USD {m[clave]:,.2f}"

        def _ganancia(ts, trade):
            if trade['resultado'] == '⏳':
                return '—'
            val = pnl_por_trade.get(ts)
            return f"USD {val:+,.2f}" if val is not None else '—'

        trades_por_fecha = {t['fecha_apertura']: t for t in trades_sel}
        df_hist_show.insert(len(df_hist_show.columns) - 0, 'Ganancia/Pérdida (USD)',
                             [_ganancia(ts, trades_por_fecha[ts]) for ts in fechas_apertura_ordenadas])
        df_hist_show.insert(1, 'Monto 1ra', [_monto(ts, 'e1') for ts in fechas_apertura_ordenadas])
        df_hist_show.insert(2, 'Monto 2da', [_monto(ts, 'e2') for ts in fechas_apertura_ordenadas])
        df_hist_show.insert(3, 'Monto 3ra', [_monto(ts, 'e3') for ts in fechas_apertura_ordenadas])

        _color_tomada = lambda v: 'color:#8b949e' if v == 'No' else f'color:{C_BOT_TRAILING};font-weight:700'
        styled_hist = (df_hist_show.style
            .pipe(lambda s: getattr(s, _map)(_color_direccion, subset=['Dirección']))
            .pipe(lambda s: getattr(s, _map)(_color_resultado, subset=['Resultado']))
            .pipe(lambda s: getattr(s, _map)(_color_tomada, subset=['Trailing activado']))
            .set_properties(**{'background-color': '#0d1117', 'color': '#e6edf3', 'border': '1px solid #21262d'})
            .set_table_styles([
                {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', '#e6edf3'),
                    ('font-weight', '700'), ('text-align', 'center'),
                    ('border-bottom', '2px solid #3a7bd5'), ('font-size', '11px')]},
                {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]},
            ]))
        st.dataframe(styled_hist, use_container_width=True, height=min(500, len(df_hist_show) * 38 + 45))
        st.caption(
            f'{len(df_hist_show)} ciclos de holdeo en el período analizado ({cfg["periodo_descarga"]} · {horizonte_bot}). '
            'Solo puede haber un ciclo abierto por activo a la vez: mientras el bot está holdeando una posición, '
            'no evalúa nuevas aperturas. El Precio promedio y el Stop vigente ya tienen en cuenta la rejilla, y los '
            'montos usan el mismo capital simulado que la sección de abajo, así que el Win Rate cierra en toda la pantalla.'
        )

    st.markdown('---')
    st.markdown(f'### 📈 Rendimiento simulado — {ticker_detalle} (apalancamiento {apalancamiento_bot}x)')
    st.caption(
        'Se recorren, en orden cronológico, los ciclos CERRADOS de arriba (con su rejilla ya resuelta) '
        'y se va componiendo el capital desde el monto inicial elegido.'
    )

    if rend['total_trades'] == 0:
        st.info('No se abrió ningún ciclo de este activo en el período analizado — el rendimiento se arma solo cuando aparecen operaciones.')
    else:
        color_rend = '#3fb950' if rend['rendimiento_pct'] >= 0 else '#f85149'
        kpi_cards_4([
            ('Capital Simulado', f"USD {rend['capital_actual']:,.2f}",
             f"Inicial: USD {rend['capital_inicial']:,.2f} · {apalancamiento_bot}x", color_rend),
            ('Rendimiento', f"{rend['rendimiento_pct']:+.2f}%", 'Sobre capital inicial', color_rend),
            ('Win Rate', f"{rend['win_rate']:.0f}%" if rend['win_rate'] is not None else 'N/D',
             f"{rend['ganadoras']}✅ / {rend['perdedoras']}❌ cerrados", '#3a7bd5'),
            ('Ciclos', str(rend['total_trades']),
             f"{rend['cerradas']} cerrados · {rend['abiertas']} en curso · {rend['rebalanceos']} 🔲 con rejilla", '#e3b341'),
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
            'Todos los ciclos del historial se cuentan automáticamente, no hay sesgo de selección manual. '
            'Cada ciclo arriesga el % de capital configurado sobre el capital SIMULADO en ese momento '
            '(capital compuesto), multiplicado por el apalancamiento elegido. Los ciclos "en curso" (⏳) '
            'todavía no suman ni restan al capital.'
        )

        st.markdown('#### ⚖️ Comparativa por apalancamiento')
        st.caption(f'Misma secuencia de ciclos de {ticker_detalle}, simulada con cada nivel de apalancamiento.')
        filas_comp = []
        for lev in APALANCAMIENTOS_BOT:
            r_lev = rend if lev == apalancamiento_bot else \
                _bot_simular_en_memoria(trades_sel, capital_inicial_bot, pct_por_operacion_bot, lev, pct_capital_nivel)
            filas_comp.append({
                'Apalancamiento': f'{lev}x' + (' ← actual' if lev == apalancamiento_bot else ''),
                'Capital final (USD)': round(r_lev['capital_actual'], 2),
                'Rendimiento': f"{r_lev['rendimiento_pct']:+.2f}%",
                'Cerrados': r_lev['cerradas'],
                'Win Rate': f"{r_lev['win_rate']:.0f}%" if r_lev['win_rate'] is not None else 'N/D',
            })
        df_comp = pd.DataFrame(filas_comp)
        st.dataframe(df_comp, use_container_width=True, height=min(260, len(df_comp) * 38 + 45), hide_index=True)

    with st.expander('❓ Cómo funciona esta estrategia'):
        st.markdown(f"""
        **📏 Rango**: el bot calcula un canal de Donchian (máximo y mínimo de las últimas N velas). Ese
        canal define el "techo" y el "piso" donde se está moviendo el precio, y la posición del precio
        actual dentro de ese rango se expresa como un %: 0% = tocando el piso, 100% = tocando el techo.

        **📊 Volatilidad**: se mide con el ATR (rango verdadero promedio de las últimas N velas). El ATR
        es la unidad de medida de todo lo demás: cada cuánto se agrega una entrada a la rejilla, cuándo se
        activa el trailing, qué tan lejos queda el trailing del precio, y qué tan lejos del rango queda el
        stop duro.

        **🔲 Rejilla y holdeo**: cuando el precio entra en la zona baja del rango (por debajo del %
        configurado) el bot abre una posición **COMPRA**; si entra en la zona alta, abre **VENTA**. Si el
        precio sigue moviéndose en contra en pasos de **{grid_step_atr} × ATR**, se agrega una nueva
        entrada (hasta un máximo de **{int(max_niveles)}**), de un tamaño igual al **{pct_capital_nivel:.0f}%**
        del monto de la 1ra entrada, y se recalcula el **precio promedio** ponderado por el capital de cada
        entrada. El bot sostiene ("holdea") toda la posición junta — no vende parcialmente.

        **🎯 Trailing (por volatilidad)**: una vez que el precio avanzó a favor **{trailing_activacion_atr} × ATR**
        desde el precio promedio, se activa un trailing stop ubicado a **{trailing_atr_mult} × ATR** del
        precio extremo alcanzado desde la apertura del ciclo. El trailing solo se ajusta a favor de la
        posición (nunca retrocede). El cierre se marca **✅** si al tocarse el trailing el precio de cierre
        queda por encima del promedio (COMPRA) o por debajo (VENTA), y **❌** si queda del otro lado.

        **🛑 Stop duro**: mientras el trailing todavía no se activó, la posición se protege con un stop
        duro ubicado a **{hard_stop_atr_mult} × ATR** por fuera del rango vigente (por debajo del piso para
        COMPRA, por encima del techo para VENTA). Si se toca antes de que el trailing se active, el ciclo
        cierra **❌**.

        **🚫 Un solo ciclo a la vez**: mientras el bot está holdeando una posición de un activo, no evalúa
        nuevas aperturas de ese mismo activo — recién vuelve a buscar zona de COMPRA/VENTA una vez que el
        ciclo anterior cerró.

        **🤖 Todo es automático**: no hay botones de Aceptar/Rechazar. Cada ciclo que abre el bot queda
        registrado en el historial y forma parte del rendimiento simulado.

        **💰 Capital simulado y apalancamiento**: el capital inicial es **configurable, desde
        USD {CAPITAL_MINIMO_BOT:,.0f}**. Cada ciclo arriesga el % de capital configurado sobre el capital
        simulado en ese momento (compuesto), multiplicado por el apalancamiento elegido (1x a 5x). Podés
        comparar los 5 niveles sobre la misma secuencia de ciclos de este activo en la tabla "Comparativa
        por apalancamiento". La pérdida de un ciclo nunca supera el 100% del capital arriesgado en ese ciclo.

        Usalo como medida de calidad de la estrategia, no como tu resultado real de trading.
        """)
