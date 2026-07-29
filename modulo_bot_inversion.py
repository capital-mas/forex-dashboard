# ==============================================================
#  MÓDULO BOT DE INVERSIÓN — Señales Sent./Antic./Z-Score/RSI+Div
#  Versión intradía: temporalidades 5/15/30 min, multi-activo (hasta 10)
#  Portado desde el indicador Pine Script "Top-Down Cuantitativo
#  — Solo Señales (Sent/Antic/Z/RSI-Div)".
# ==============================================================

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

MAX_ACTIVOS_BOT = 10

# yfinance permite hasta 60 días de historia para velas de 5m/15m/30m.
# Usamos el máximo posible para tener la ventana estadística más robusta.
HORIZONTES_BOT = {
    '5 minutos': dict(
        interval='5m', periodo_descarga='60d',
        ventana_valor=560, ventana_momento=90, rsi_periodo=14,
        vol_periodo=40, bb_periodo=30, atr_periodo=14,
        ret_dias=12, mom_escala=3.0,
    ),
    '15 minutos': dict(
        interval='15m', periodo_descarga='60d',
        ventana_valor=380, ventana_momento=65, rsi_periodo=14,
        vol_periodo=30, bb_periodo=26, atr_periodo=14,
        ret_dias=8, mom_escala=2.2,
    ),
    '30 minutos': dict(
        interval='30m', periodo_descarga='60d',
        ventana_valor=250, ventana_momento=48, rsi_periodo=14,
        vol_periodo=24, bb_periodo=20, atr_periodo=14,
        ret_dias=6, mom_escala=1.6,
    ),
}

C_BOT_VENTA_100  = '#f85149'
C_BOT_VENTA_50   = '#f0883e'
C_BOT_COMPRA_100 = '#3fb950'
C_BOT_COMPRA_50  = '#2dd4bf'


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


def _vol_anual_rolling(close, length, barras_por_año):
    """Anualiza la volatilidad según la cantidad de barras intradía por año
    (varía con la temporalidad: 5m/15m/30m tienen distinta cantidad de barras/día)."""
    ret = close.pct_change()
    return ret.rolling(length).std() * np.sqrt(barras_por_año) * 100


def _rolling_percentrank(s, length):
    """Equivalente a ta.percentrank de Pine: % de las barras anteriores
    (dentro de la ventana) que son menores al valor actual."""
    min_p = max(5, length // 4)

    def _r(x):
        return (x < x[-1]).sum() / len(x) * 100

    return s.rolling(length, min_periods=min_p).apply(_r, raw=True)


def _barras_por_año(interval):
    """Barras de mercado (~6.5hs, ~252 días) por año, según temporalidad."""
    minutos_sesion = 6.5 * 60
    minutos_vela = {'5m': 5, '15m': 15, '30m': 30}.get(interval, 15)
    barras_dia = minutos_sesion / minutos_vela
    return barras_dia * 252


def _calcular_bot_dataframe(close, high, low, cfg,
                             antic_min, antic_max, zscore_periodo, zscore_umbral,
                             rsi_nivel_venta, rsi_nivel_compra, divergencia_lookback,
                             stop_pct_100, stop_pct_50, tp_pct_100, tp_pct_50):
    """Cálculo puro (sin caché): es liviano — unas pocas rolling windows sobre
    unos cientos de velas — así que no vale la pena cachearlo, y cachearlo mal
    (por ticker) es justamente lo que rompía el análisis multi-activo."""
    cl = close.dropna()
    hi = high.reindex(cl.index)
    lo = low.reindex(cl.index)
    barras_año = _barras_por_año(cfg['interval'])

    precio_pct = _rolling_percentrank(cl, cfg['ventana_valor'])
    rsi_valor = _rsi_sma(cl, cfg['rsi_periodo'])
    rsi_pct = 100 - _rolling_percentrank(rsi_valor, cfg['ventana_valor'])
    vol_valor = _vol_anual_rolling(cl, cfg['vol_periodo'], barras_año)
    vol_pct = 100 - _rolling_percentrank(vol_valor, cfg['ventana_valor'])
    sc_acum = (100 - precio_pct) * 0.40 + rsi_pct * 0.35 + vol_pct * 0.25  # informativo

    ret_mom = cl.pct_change(cfg['ret_dias']) * 100
    mom = (50 + ret_mom * cfg['mom_escala']).clip(0, 100)

    tr = pd.concat([hi - lo, (hi - cl.shift(1)).abs(), (lo - cl.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(cfg['atr_periodo']).mean()
    atr_media = atr.rolling(cfg['ventana_momento']).mean()
    comp_atr = (100 - (atr / atr_media * 50)).clip(0, 100)

    bb_media = cl.rolling(cfg['bb_periodo']).mean()
    bb_std = cl.rolling(cfg['bb_periodo']).std()
    bbw = (bb_std / bb_media.replace(0, np.nan)) * 100
    bb_c = 100 - _rolling_percentrank(bbw, cfg['ventana_momento'])

    sc_antic = mom * 0.40 + comp_atr * 0.30 + bb_c * 0.30
    sc_sent = precio_pct

    z_media = cl.rolling(zscore_periodo).mean()
    z_std = cl.rolling(zscore_periodo).std()
    zscore = (cl - z_media) / z_std.replace(0, np.nan)

    rsi_alto = rsi_valor >= rsi_nivel_venta
    rsi_bajo = rsi_valor <= rsi_nivel_compra
    div_baj = (cl > cl.shift(divergencia_lookback)) & (rsi_valor < rsi_valor.shift(divergencia_lookback))
    div_alc = (cl < cl.shift(divergencia_lookback)) & (rsi_valor > rsi_valor.shift(divergencia_lookback))
    rsi_pts_venta = np.where(rsi_alto, np.where(div_baj, 2, 1), 0)
    rsi_pts_compra = np.where(rsi_bajo, np.where(div_alc, 2, 1), 0)

    antic_valida = (sc_antic >= antic_min) & (sc_antic <= antic_max)
    z_venta = zscore >= zscore_umbral
    z_compra = zscore <= -zscore_umbral
    rsi_cond_venta = rsi_pts_venta > 0
    rsi_cond_compra = rsi_pts_compra > 0

    pct_venta = pd.Series(0.0, index=cl.index)
    pct_venta[(sc_sent >= 96) & (sc_sent <= 100) & antic_valida & z_venta & rsi_cond_venta] = 100.0
    mask50v = (sc_sent >= 90) & (sc_sent < 96) & antic_valida & z_venta & rsi_cond_venta & (pct_venta == 0)
    pct_venta[mask50v] = 50.0

    pct_compra = pd.Series(0.0, index=cl.index)
    pct_compra[(sc_sent >= 0) & (sc_sent <= 6) & antic_valida & z_compra & rsi_cond_compra] = 100.0
    mask50c = (sc_sent > 7) & (sc_sent <= 10) & antic_valida & z_compra & rsi_cond_compra & (pct_compra == 0)
    pct_compra[mask50c] = 50.0

    estado = pd.Series('—', index=cl.index)
    estado[pct_venta == 100] = 'VENTA 100%'
    estado[pct_venta == 50] = 'VENTA 50%'
    estado[pct_compra == 100] = 'COMPRA 100%'
    estado[pct_compra == 50] = 'COMPRA 50%'
    disparo = (estado != '—') & (estado != estado.shift(1))

    df = pd.DataFrame({
        'precio': cl, 'sc_acum': sc_acum, 'sc_antic': sc_antic, 'sc_sent': sc_sent,
        'zscore': zscore, 'rsi': rsi_valor,
        'rsi_pts_venta': rsi_pts_venta, 'rsi_pts_compra': rsi_pts_compra,
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

    IMPORTANTE: esto asume que el stop es una salida total. Si en tu operativa
    real usás el stop como gatillo para una segunda entrada (promediar) en vez
    de cerrar la posición, la ❌ no equivale necesariamente a "perdiste la
    operación" — es solo "el precio llegó primero a tu nivel de stop"."""
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


def _bot_registrar_señales_nuevas(supabase, user_id, ticker, horizonte, df_bot, minutos_limite):
    """Inserta las señales recién disparadas que todavía no estén logueadas.
    Se intenta insertar una por una y se ignora el error si ya existe (gracias
    al UNIQUE de la tabla) — así nunca se pisa una decisión ya tomada."""
    disparos = df_bot[df_bot['disparo'] & (df_bot['estado'] != '—')]
    for ts, row in disparos.iterrows():
        fecha_limite = ts.to_pydatetime() + pd.Timedelta(minutes=minutos_limite)
        fila = {
            'user_id': user_id, 'ticker': ticker, 'horizonte': horizonte,
            'fecha_señal': ts.isoformat(), 'tipo_señal': row['estado'],
            'precio_entrada': float(row['precio']),
            'tp': float(row['tp']) if pd.notna(row['tp']) else None,
            'stop': float(row['stop']) if pd.notna(row['stop']) else None,
            'fecha_limite_decision': fecha_limite.isoformat(),
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


def _bot_decidir_señal(supabase, señal_id, decision):
    try:
        supabase.table('bot_señales_log').update({
            'decision': decision, 'fecha_decision': datetime.now().isoformat(),
        }).eq('id', señal_id).execute()
    except Exception:
        pass


def _bot_actualizar_resultados_aceptadas(supabase, user_id, ticker, horizonte, df_bot):
    """Para señales ACEPTADAS de este ticker/horizonte sin resultado aún,
    revisa las velas nuevas para ver si ya tocó TP o Stop."""
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
        tp, sl = fila['tp'], fila['stop']
        if tp is None or sl is None:
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


def _bot_calcular_rendimiento(supabase, user_id, capital_inicial, pct_por_operacion):
    """Arma el rendimiento acumulado a partir de señales ACEPTADAS y con
    resultado ya definido (✅/❌). Las que siguen '⏳' no afectan el cálculo
    todavía — se muestran aparte como 'abiertas'."""
    try:
        res = supabase.table('bot_señales_log').select('*') \
            .eq('user_id', user_id).eq('decision', 'aceptada').order('fecha_señal').execute()
        filas = res.data or []
    except Exception:
        filas = []

    capital_por_op = capital_inicial * (pct_por_operacion / 100.0)
    equity = capital_inicial
    curva = [{'fecha': 'Inicio', 'equity': capital_inicial}]
    cerradas = ganadoras = abiertas = 0

    for fila in filas:
        resultado = fila.get('resultado')
        precio_entrada = fila['precio_entrada']
        if resultado == '✅':
            pct_mov = abs(fila['tp'] - precio_entrada) / precio_entrada
            equity += capital_por_op * pct_mov
            ganadoras += 1; cerradas += 1
        elif resultado == '❌':
            pct_mov = abs(fila['stop'] - precio_entrada) / precio_entrada
            equity -= capital_por_op * pct_mov
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


# ── Módulo principal ────────────────────────────────────────────────

def modulo_bot_inversion(
    get_close_series, fmt_precio, score_color_hex, kpi_cards_4,
    chips_navegacion, PLOTLY_LAYOUT_BASE, PLOTLY_CONFIG,
    universo_opciones, universo_mapa,
):
    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #6CC24A;
         border-radius:14px; padding:28px 32px; margin-bottom:24px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">🤖 Bot de Inversión — Señales Intradía</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Señal de COMPRA/VENTA basada en 4 condiciones obligatorias simultáneas:
        <b style="color:#e3b341">Sentimiento</b> en nivel extremo,
        <b style="color:#e3b341">Anticipación</b> dentro de rango válido,
        <b style="color:#e3b341">Z-Score</b> del precio y
        <b style="color:#e3b341">RSI + Divergencia</b>.
        Analizá hasta <b style="color:#e3b341">10 activos</b> en simultáneo, en velas de
        <b style="color:#e3b341">5, 15 o 30 minutos</b>.
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
            antic_min = st.number_input('Anticipación mínima', value=15.0, key='bot_antic_min')
            antic_max = st.number_input('Anticipación máxima', value=38.0, key='bot_antic_max')
        with p2:
            zscore_periodo = st.number_input('Período Z-Score', value=20, min_value=5, key='bot_z_periodo')
            zscore_umbral = st.number_input('Umbral Z-Score (±)', value=2.5, min_value=0.1, step=0.1, key='bot_z_umbral')
        with p3:
            rsi_nivel_venta = st.number_input('Nivel RSI venta (≥)', value=70.0, key='bot_rsi_venta')
            rsi_nivel_compra = st.number_input('Nivel RSI compra (≤)', value=30.0, key='bot_rsi_compra')
        p4, p5, p6 = st.columns(3)
        with p4:
            divergencia_lookback = st.number_input('Barras divergencia', value=5, min_value=2, key='bot_div_lookback')
        with p5:
            stop_pct_100 = st.number_input('Stop % (señal 100%)', value=1.5, key='bot_stop_100')
        with p6:
            stop_pct_50 = st.number_input('Stop % (señal 50%)', value=3.0, key='bot_stop_50')
        p7, p8 = st.columns(2)
        with p7:
            tp_pct_100 = st.number_input('Take Profit % (señal 100%)', value=3.0, min_value=0.1, key='bot_tp_100')
        with p8:
            tp_pct_50 = st.number_input('Take Profit % (señal 50%)', value=5.0, min_value=0.1, key='bot_tp_50')

    analizar_bot = st.button('▶ Analizar', key='bot_run', type='primary')
    if not analizar_bot and not st.session_state.get('bot_run_flag'):
        st.info(f'Elegí la temporalidad y hasta {MAX_ACTIVOS_BOT} activos, después presioná "Analizar".')
        return
    if analizar_bot:
        st.session_state['bot_run_flag'] = True

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
        cl = get_close_series(df_raw)
        if cl is None or len(cl.dropna()) < max(30, cfg['ventana_valor'] // 4):
            fallidos.append(tk)
            continue
        hi = df_raw['High'] if 'High' in df_raw.columns else cl
        lo = df_raw['Low'] if 'Low' in df_raw.columns else cl
        df_bot = _calcular_bot_dataframe(
            cl, hi, lo, cfg,
            antic_min, antic_max, int(zscore_periodo), zscore_umbral,
            rsi_nivel_venta, rsi_nivel_compra, int(divergencia_lookback),
            stop_pct_100, stop_pct_50, tp_pct_100, tp_pct_50,
        )
        hi_r = hi.reindex(df_bot.index)
        lo_r = lo.reindex(df_bot.index)
        df_bot = _evaluar_resultados_señales(df_bot, hi_r, lo_r)
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
        disparos_tk = df_bot[df_bot['disparo'] & (df_bot['estado'] != '—')]
        n_ok = int((disparos_tk['resultado'] == '✅').sum())
        n_bad = int((disparos_tk['resultado'] == '❌').sum())
        n_open = int((disparos_tk['resultado'] == '⏳').sum())
        cerradas = n_ok + n_bad
        winrate = f'{n_ok / cerradas * 100:.0f}%' if cerradas > 0 else 'N/D'
        filas_resumen.append({
            'Ticker': tk, 'Señal': u['estado'], 'Precio': fmt_precio(u['precio']),
            'Última vela': df_bot.index[-1].strftime('%H:%M:%S'),
            'Sent': round(u['sc_sent'], 1), 'Antic': round(u['sc_antic'], 1),
            'Z-Score': round(u['zscore'], 2), 'RSI': round(u['rsi'], 1),
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
        ('Sentimiento / Anticipación', f"{ultimo['sc_sent']:.0f} / {ultimo['sc_antic']:.0f}",
         'Ambos sobre 100', score_color_hex(ultimo['sc_sent'])),
        ('Z-Score / RSI', f"{ultimo['zscore']:+.2f} / {ultimo['rsi']:.1f}",
         f"Umbral ±{zscore_umbral} · RSI {rsi_nivel_compra:.0f}-{rsi_nivel_venta:.0f}", '#e3b341'),
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
            'Sent': df_hist['sc_sent'].round(1),
            'Antic': df_hist['sc_antic'].round(1),
            'Z-Score': df_hist['zscore'].round(2),
            'RSI': df_hist['rsi'].round(1),
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

    with st.expander('❓ Cómo funciona esta señal'):
        st.markdown("""
        Cada señal disparada se evalúa hacia adelante: se marca **✅** si el precio tocó primero
        el Take Profit, **❌** si tocó primero el Stop, y **⏳ En curso** si todavía no definió.

        ⚠️ **Importante**: esto asume que el Stop es una salida total de la operación. Si en tu
        operativa real usás el Stop como pie para una **segunda entrada** (promediar) en vez de
        cerrar, la ❌ no equivale necesariamente a "perdiste la operación completa" — solo indica
        que el precio llegó primero a ese nivel. Usalo como medida de calidad de la señal, no como
        tu resultado real de trading.
