# ==============================================================
#  MÓDULO: SALUD Y PARTICIPACIÓN DEL MERCADO (MARKET BREADTH)
# ==============================================================
"""
Módulo standalone pensado para integrarse a Capital+ dentro de
"Herramientas". No depende de nada del archivo principal — reutiliza
sus mismos colores y estilo de cards, pero si le pasás las funciones
propias (kpi_cards_4, fmt_precio, PLOTLY_CONFIG, chips_navegacion) las
usa en vez de sus versiones internas, para que quede 100% consistente
visualmente con el resto de la app.

INTEGRACIÓN (3 pasos):

1) Copiar este archivo junto al resto de tus módulos (por ejemplo al
   lado de modulo_fscore.py, modulo_promediador.py, etc.)

2) En el archivo principal, importar:

       from modulo_market_breadth import render_market_breadth

3) Agregar la entrada en tu diccionario de Herramientas y en el
   dispatcher de módulos:

   _HERRAMIENTAS_MAP = {
       ...
       '📡 Salud del Mercado': ('breadth', 'breadth'),
   }

   y en el bloque de renderizado (donde están los `elif MODULO == ...`):

   elif MODULO == 'breadth':
       render_market_breadth(
           ACCIONES_POR_INDUSTRIA=ACCIONES_POR_INDUSTRIA,
           PLOTLY_CONFIG=PLOTLY_CONFIG,
           kpi_cards_4=kpi_cards_4,
           fmt_precio=fmt_precio,
           chips_navegacion=chips_navegacion,
       )

No hace falta pasar nada de esto — si no le pasás argumentos, el
módulo funciona igual con sus propios fallbacks (mismo esquema de
colores del resto de la app).

LIMITACIÓN A TENER EN CUENTA:
Yahoo Finance no expone listas de constituyentes reales de un índice
(ej. "las 500 empresas del S&P500"). Por eso el "universo de mercado"
que se analiza acá es el que VOS elijas: una industria predefinida de
tu diccionario ACCIONES_POR_INDUSTRIA, o una lista manual de tickers
que pegues. Cuantos más activos representativos incluyas, más fiel es
la lectura de amplitud.
"""

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==============================================================
#  ÍNDICES REALES — constituyentes completos (no proxy)
# ==============================================================
"""
A diferencia del modo "Industria predefinida" (que usa tus grupos
sectoriales como proxy), estos son índices con su lista REAL de
componentes, así el Breadth Score refleja la amplitud genuina de
ese índice y no de un grupo armado a mano.

Para sumar un índice nuevo: agregá una entrada más al diccionario
con el mismo formato — nombre del índice como clave, dict con
'ticker_indice' (para comparar el proxy calculado vs el índice real,
opcional, puede ir None) y 'constituyentes' (lista de tickers).
"""

INDICES_CONSTITUYENTES = {
    'Dow Jones Industrial Average (30)': {
        'ticker_indice': '^DJI',
        'constituyentes': [
            'MMM', 'AMZN', 'AXP', 'AMGN', 'AAPL', 'BA', 'CAT', 'CVX', 'CSCO', 'KO',
            'GS', 'HD', 'HON', 'IBM', 'JNJ', 'JPM', 'MCD', 'MRK', 'MSFT', 'NKE',
            'NVDA', 'PG', 'CRM', 'SHW', 'TRV', 'UNH', 'V', 'WMT', 'DIS', 'GOOGL',
        ],
    },
    # 👉 Acá se suman más índices con la lista real de constituyentes,
    #    por ejemplo 'S&P 500 (500)', 'Nasdaq 100 (100)', 'Merval (Argentina)', etc.
}

# ==============================================================
#  PALETA Y HELPERS DE FALLBACK (si no se inyectan desde la app)
# ==============================================================

C_BG1, C_BG2   = '#0d1117', '#07090f'
C_GRID         = '#21262d'
C_TEXT         = '#e6edf3'
C_MUTED        = '#6b7d9a'
C_GREEN        = '#3fb950'
C_LGRE         = '#7ee787'
C_YELL         = '#e3b341'
C_LRED         = '#f0883e'
C_RED          = '#f85149'
C_ACENT        = '#3a7bd5'
C_MONSTER      = '#6CC24A'

PLOTLY_LAYOUT_BASE_BD = dict(
    plot_bgcolor=C_BG1, paper_bgcolor=C_BG2,
    font=dict(color='#b0bcd0', family='Inter, sans-serif'),
    dragmode=False,
)
PLOTLY_CONFIG_BD = dict(displayModeBar=False, scrollZoom=False)


def _bd_color_score(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return C_MUTED
    if v <= 20:  return C_RED
    if v <= 40:  return C_LRED
    if v <= 60:  return C_YELL
    if v <= 80:  return C_LGRE
    return C_GREEN


def _fmt_precio_bd(p):
    if p is None or (isinstance(p, float) and np.isnan(p)) or p <= 0:
        return 'S/D'
    if p >= 1000: return f'${p:,.0f}'
    if p >= 10:   return f'${p:.2f}'
    return f'${p:.4f}'


def _kpi_cards_4_bd(items):
    """Fallback local de kpi_cards_4 — mismo look que el resto de Capital+.
    items = (label, value, sub, color)"""
    cols = st.columns(len(items))
    for col, item in zip(cols, items):
        label, value, sub, color = item[0], item[1], item[2], item[3]
        with col:
            st.markdown(
                f'<div style="background:{C_BG1};border:1px solid {C_GRID};border-radius:10px;'
                f'padding:16px 18px;position:relative;overflow:hidden">'
                f'<div style="position:absolute;top:0;left:0;width:100%;height:2px;background:{color}"></div>'
                f'<div style="color:{C_MUTED};font-size:12px;font-weight:700;text-transform:uppercase;'
                f'letter-spacing:1px;margin-bottom:6px">{label}</div>'
                f'<div style="color:{C_TEXT};font-size:22px;font-weight:700;letter-spacing:-0.5px;'
                f'font-family:JetBrains Mono,monospace">{value}</div>'
                f'<div style="color:{C_MUTED};font-size:13px;margin-top:4px">{sub}</div></div>',
                unsafe_allow_html=True,
            )
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)


# ==============================================================
#  DESCARGA DE DATOS
# ==============================================================

@st.cache_data(ttl=1800, show_spinner=False)
def _bd_descargar_universo(tickers_tuple, periodo='1y'):
    """Descarga OHLCV de todo el universo en un solo bulk call."""
    try:
        import yfinance as yf
        tickers = sorted(set(tickers_tuple))
        data = yf.download(tickers, period=periodo, interval='1d',
                            auto_adjust=True, progress=False, group_by='ticker')
        if data is None or data.empty:
            return None
        return data
    except Exception:
        return None


def _bd_extraer_serie(data, tk, campo='Close'):
    try:
        if isinstance(data.columns, pd.MultiIndex):
            if (tk, campo) in data.columns:
                return data[(tk, campo)].dropna()
            elif (campo, tk) in data.columns:
                return data[(campo, tk)].dropna()
            return pd.Series(dtype=float)
        # un solo ticker: columnas planas
        if campo in data.columns:
            return data[campo].dropna()
        return pd.Series(dtype=float)
    except Exception:
        return pd.Series(dtype=float)


@st.cache_data(ttl=86400, show_spinner=False)
def _bd_market_caps(tickers_tuple):
    """Market cap por ticker (para el subíndice de concentración). Cacheado 24h
    porque la cap no cambia significativamente rueda a rueda."""
    import yfinance as yf
    caps = {}

    def _one(tk):
        try:
            fi = yf.Ticker(tk).fast_info
            mc = fi.get('market_cap') or fi.get('marketCap')
            return tk, mc
        except Exception:
            return tk, None

    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(_one, tk): tk for tk in tickers_tuple}
        for fut in as_completed(futs):
            tk, mc = fut.result()
            if mc:
                caps[tk] = float(mc)
    return caps


# ==============================================================
#  CÁLCULO DE SUB-ÍNDICES DE AMPLITUD
# ==============================================================

def _bd_snapshot(df_close, df_vol, hasta=None):
    """Calcula Trend Breadth, Advance/Decline, New Highs/Lows y Volume Breadth
    usando datos hasta la fila posicional 'hasta' (inclusive). Si hasta=None,
    usa toda la data disponible. Sirve tanto para el snapshot de hoy como
    para reconstruir un snapshot de ~1 mes atrás y medir la tendencia del
    Breadth Score."""
    dfc = df_close if hasta is None else df_close.iloc[:hasta + 1]
    dfv = df_vol if hasta is None else df_vol.iloc[:hasta + 1]
    if len(dfc) < 25:
        return None

    ret = dfc.pct_change()
    ultimo_ret = ret.iloc[-1].dropna()
    adv = int((ultimo_ret > 0).sum())
    dec = int((ultimo_ret < 0).sum())
    ad_score = adv / (adv + dec) * 100 if (adv + dec) > 0 else 50.0

    n = len(dfc)
    last = dfc.iloc[-1]
    sma20 = dfc.rolling(min(20, n)).mean().iloc[-1]
    sma50 = dfc.rolling(min(50, n)).mean().iloc[-1] if n >= 10 else sma20
    sma200 = dfc.rolling(min(200, n)).mean().iloc[-1] if n >= 30 else sma50
    pct20 = float((last > sma20).mean() * 100)
    pct50 = float((last > sma50).mean() * 100)
    pct200 = float((last > sma200).mean() * 100)
    trend_score = (pct20 + pct50 + pct200) / 3

    ventana_hl = min(252, n)
    roll_max = dfc.rolling(ventana_hl).max().iloc[-1]
    roll_min = dfc.rolling(ventana_hl).min().iloc[-1]
    nh = int((last >= roll_max).sum())
    nl = int((last <= roll_min).sum())
    nhnl_score = nh / (nh + nl) * 100 if (nh + nl) > 0 else 50.0

    vol_hoy = dfv.iloc[-1].reindex(ultimo_ret.index).fillna(0)
    up_vol = float(vol_hoy[ultimo_ret > 0].sum())
    down_vol = float(vol_hoy[ultimo_ret < 0].sum())
    vol_score = up_vol / (up_vol + down_vol) * 100 if (up_vol + down_vol) > 0 else 50.0

    return dict(
        adv=adv, dec=dec, ad_score=round(ad_score, 1),
        pct20=round(pct20, 1), pct50=round(pct50, 1), pct200=round(pct200, 1),
        trend_score=round(trend_score, 1),
        nh=nh, nl=nl, nhnl_score=round(nhnl_score, 1),
        up_vol=up_vol, down_vol=down_vol, vol_score=round(vol_score, 1),
    )


def _bd_concentracion(tickers, caps, df_close):
    """Score de concentración: combina el peso de las Top 5 empresas por
    capitalización y la divergencia entre el retorno ponderado por cap
    vs. el retorno equal-weight del último mes. Cuanto más concentrado
    el mercado en pocas empresas, más bajo el score."""
    tickers_con_cap = [t for t in tickers if t in caps and t in df_close.columns]
    if len(tickers_con_cap) < 3:
        return dict(top5_pct=None, top10_pct=None, conc_score=50.0, pesos=None, diff_ret=0.0)

    caps_ser = pd.Series({t: caps[t] for t in tickers_con_cap}).sort_values(ascending=False)
    total = caps_ser.sum()
    pesos = caps_ser / total
    top5_pct = float(pesos.iloc[:5].sum() * 100)
    top10_pct = float(pesos.iloc[:min(10, len(pesos))].sum() * 100)

    n = len(df_close)
    ventana = min(21, n - 1) if n > 1 else 0
    diff_ret = 0.0
    if ventana > 0:
        sub = df_close[tickers_con_cap].iloc[[-ventana - 1, -1]]
        ret_ind = (sub.iloc[-1] / sub.iloc[0] - 1).dropna()
        pesos_alineados = pesos.reindex(ret_ind.index).fillna(0)
        if pesos_alineados.sum() > 0:
            cap_ret = float((ret_ind * pesos_alineados).sum() / pesos_alineados.sum())
            eq_ret = float(ret_ind.mean())
            diff_ret = cap_ret - eq_ret

    score1 = max(0.0, min(100.0, 100 - top5_pct))                 # menos peso Top5 = mejor
    score2 = max(0.0, min(100.0, 50 - diff_ret * 500))             # cap outperform fuerte = peor
    conc_score = round(score1 * 0.6 + score2 * 0.4, 1)

    return dict(top5_pct=round(top5_pct, 1), top10_pct=round(top10_pct, 1),
                conc_score=conc_score, pesos=pesos, diff_ret=diff_ret)


def _bd_breadth_score(snap, conc_score):
    if snap is None:
        return None
    return round(
        snap['trend_score'] * 0.25 + snap['ad_score'] * 0.20 + snap['nhnl_score'] * 0.15
        + snap['vol_score'] * 0.20 + conc_score * 0.20, 1
    )


# ==============================================================
#  ESTADO DE PARTICIPACIÓN DEL MERCADO
# ==============================================================

def _bd_estado_mercado(price_ret_1m, breadth_now, breadth_prev, ad_score, nhnl_score):
    """Cruza la dirección del precio (índice proxy, 1 mes) con la amplitud
    interna del mercado para devolver uno de los 5 estados + neutral."""
    delta_breadth = (breadth_now - breadth_prev) if breadth_prev is not None else 0.0
    precio_sube = price_ret_1m is not None and price_ret_1m > 0.5
    precio_baja = price_ret_1m is not None and price_ret_1m < -0.5

    if precio_sube and breadth_now >= 60 and ad_score >= 55 and nhnl_score >= 55:
        return ('CONFIRMACIÓN ALCISTA', '🟢', C_GREEN,
                'El precio sube y una porción amplia del mercado acompaña: amplitud, avance/declive '
                'y nuevos máximos alineados al alza. Movimiento sano.')

    if precio_sube and breadth_now < 45 and delta_breadth <= 2:
        if breadth_now < 35 or ad_score < 40:
            return ('DIVERGENCIA', '🟠', C_LRED,
                    'El precio sigue haciendo nuevos máximos, pero la participación interna se '
                    'deteriora con fuerza — señal de alerta de fragilidad en la suba.')
        return ('CONCENTRACIÓN', '🟡', C_YELL,
                'El índice sube, pero cada vez depende de menos activos: la amplitud no acompaña '
                'el nuevo máximo del precio.')

    if precio_baja and breadth_now < 45 and ad_score < 45:
        return ('DETERIORO GENERALIZADO', '🔴', C_RED,
                'La baja está siendo acompañada ampliamente: mayoría de activos cayendo, con '
                'volumen y amplitud débiles en todo el universo analizado.')

    if (not precio_sube) and breadth_now >= 55 and delta_breadth > 0 and ad_score >= 55:
        return ('ACUMULACIÓN / RECUPERACIÓN', '🔵', C_ACENT,
                'El precio todavía no confirma fortaleza, pero la participación interna del mercado '
                'empieza a mejorar — patrón típico de zonas de piso.')

    return ('NEUTRAL / MIXTO', '⚪', C_MUTED,
            'Los indicadores de amplitud no muestran un sesgo dominante por ahora — sin '
            'confirmación ni divergencia clara entre precio y participación interna.')


# ==============================================================
#  RENDER PRINCIPAL
# ==============================================================

def render_market_breadth(
    ACCIONES_POR_INDUSTRIA=None,
    PLOTLY_CONFIG=None,
    kpi_cards_4=None,
    fmt_precio=None,
    chips_navegacion=None,
):
    PLOTLY_CONFIG = PLOTLY_CONFIG or PLOTLY_CONFIG_BD
    kpi_cards_4 = kpi_cards_4 or _kpi_cards_4_bd
    fmt_precio = fmt_precio or _fmt_precio_bd

    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#0d1c20 0%,#0a2530 50%,#0d1117 100%);
         border:1px solid {C_GRID}; border-top:2px solid {C_ACENT};
         border-radius:14px; padding:28px 32px; margin-bottom:24px;">
      <div style="font-size:18px;font-weight:700;color:{C_TEXT};margin-bottom:6px">
        📡 Salud y Participación del Mercado
      </div>
      <div style="font-size:12px;color:{C_MUTED};line-height:1.7">
        Amplitud de mercado (breadth): mide cuántos activos acompañan de verdad un movimiento de
        precio, no solo si el índice sube o baja. Combina Tendencia, Avance/Declive, Máximos/Mínimos
        de 52 semanas, Volumen y Concentración en un <b style="color:{C_TEXT}">Breadth Score</b> y un
        estado de participación (confirmación, concentración, divergencia, deterioro o acumulación).
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Selección de universo ──────────────────────────────────────────
    opciones_modo = ['Lista manual de tickers']
    if INDICES_CONSTITUYENTES:
        opciones_modo.insert(0, 'Índice real (constituyentes)')
    if ACCIONES_POR_INDUSTRIA:
        opciones_modo.insert(0 if not INDICES_CONSTITUYENTES else 1, 'Industria predefinida')

    modo = st.radio('Universo a analizar', opciones_modo, horizontal=True, key='bd_modo')

    tickers_universo, nombre_universo, ticker_indice_real = [], '', None

    if modo == 'Índice real (constituyentes)':
        idx_sel = st.selectbox('Índice', list(INDICES_CONSTITUYENTES.keys()), key='bd_indice_real')
        info_idx = INDICES_CONSTITUYENTES[idx_sel]
        tickers_universo = list(info_idx['constituyentes'])
        ticker_indice_real = info_idx.get('ticker_indice')
        nombre_universo = idx_sel
        st.caption(f'📌 {len(tickers_universo)} constituyentes reales del índice.')
    elif modo == 'Industria predefinida' and ACCIONES_POR_INDUSTRIA:
        ind_sel = st.selectbox('Industria', list(ACCIONES_POR_INDUSTRIA.keys()), key='bd_industria')
        tickers_universo = list(ACCIONES_POR_INDUSTRIA[ind_sel])
        nombre_universo = ind_sel
    else:
        txt = st.text_area(
            'Tickers separados por coma',
            'AAPL,MSFT,GOOGL,AMZN,META,NVDA,TSLA,AVGO,ORCL,CRM,ADBE,AMD,QCOM,INTC,IBM',
            key='bd_manual', height=80,
        )
        tickers_universo = sorted(set(t.strip().upper() for t in txt.split(',') if t.strip()))
        nombre_universo = 'Lista manual'

    c_p1, c_p2 = st.columns([1, 3])
    with c_p1:
        periodo = st.selectbox('Historial', ['6mo', '1y', '2y'], index=1, key='bd_periodo')
    with c_p2:
        st.markdown(
            f'<div style="font-size:11px;color:{C_MUTED};padding-top:28px">'
            f'{len(tickers_universo)} tickers en el universo actual.</div>',
            unsafe_allow_html=True,
        )

    if len(tickers_universo) < 5:
        st.info('Necesitás al menos 5 tickers para un análisis de amplitud representativo.')
        return

    if st.button('▶ Calcular Salud del Mercado', key='bd_run', type='primary'):
        st.session_state['bd_run_flag'] = True
        st.session_state['bd_universo_firma'] = (tuple(tickers_universo), periodo)

    if not st.session_state.get('bd_run_flag'):
        st.markdown(f"""
        <div style='background:{C_BG1};border:1px dashed {C_GRID};border-radius:10px;padding:40px;text-align:center'>
          <div style='font-size:40px;margin-bottom:12px'>📡</div>
          <div style='color:{C_TEXT};font-size:14px;font-weight:600;margin-bottom:6px'>Salud del Mercado</div>
          <div style='color:{C_MUTED};font-size:12px'>Elegí un universo y presioná "Calcular Salud del Mercado".</div>
        </div>
        """, unsafe_allow_html=True)
        return

    tickers_descarga = list(tickers_universo)
    if ticker_indice_real and ticker_indice_real not in tickers_descarga:
        tickers_descarga.append(ticker_indice_real)

    with st.spinner(f'Descargando {len(tickers_descarga)} activos ({periodo})...'):
        data = _bd_descargar_universo(tuple(tickers_descarga), periodo)
    if data is None:
        st.error('No se pudieron descargar los datos. Probá con otro universo o volvé a intentar.')
        return

    serie_indice_real = None
    if ticker_indice_real:
        serie_indice_real = _bd_extraer_serie(data, ticker_indice_real, 'Close')
        if len(serie_indice_real) < 25:
            serie_indice_real = None

    closes, vols = {}, {}
    for tk in tickers_universo:
        c = _bd_extraer_serie(data, tk, 'Close')
        v = _bd_extraer_serie(data, tk, 'Volume')
        if len(c) > 25:
            closes[tk] = c
            vols[tk] = v

    faltantes = [t for t in tickers_universo if t not in closes]
    if faltantes:
        st.caption(f'⚠️ Sin datos suficientes para: {", ".join(faltantes[:15])}'
                   f'{" (+ más)" if len(faltantes) > 15 else ""} — se excluyen del análisis.')

    if len(closes) < 5:
        st.error('Datos insuficientes para calcular amplitud (menos de 5 activos válidos).')
        return

    df_close = pd.DataFrame(closes).sort_index().ffill().dropna(how='all')
    df_vol = pd.DataFrame(vols).reindex(df_close.index).fillna(0)

    with st.spinner('Descargando capitalización de mercado (para concentración)...'):
        caps = _bd_market_caps(tuple(closes.keys()))

    snap_hoy = _bd_snapshot(df_close, df_vol)
    if snap_hoy is None:
        st.error('Historial insuficiente para calcular amplitud (mínimo ~25 ruedas).')
        return

    idx_prev = max(0, len(df_close) - 22)
    snap_prev = _bd_snapshot(df_close, df_vol, hasta=idx_prev) if len(df_close) > 30 else None

    conc = _bd_concentracion(list(closes.keys()), caps, df_close)
    breadth_hoy = _bd_breadth_score(snap_hoy, conc['conc_score'])
    breadth_prev = _bd_breadth_score(snap_prev, conc['conc_score']) if snap_prev else None

    # ── Índice proxy (ponderado por cap si hay datos, si no equal-weight) ──
    if conc['pesos'] is not None and conc['pesos'].sum() > 0:
        pesos_full = conc['pesos'].reindex(df_close.columns).fillna(0)
        if pesos_full.sum() == 0:
            pesos_full = pd.Series(1 / len(df_close.columns), index=df_close.columns)
        else:
            pesos_full = pesos_full / pesos_full.sum()
    else:
        pesos_full = pd.Series(1 / len(df_close.columns), index=df_close.columns)

    idx_serie_proxy = (df_close * pesos_full).sum(axis=1)
    # Si hay ticker real del índice (ej. ^DJI), usamos SU precio para los retornos
    # y para cruzar contra la amplitud — el proxy ponderado por cap queda de respaldo
    # solo para universos armados a mano (industria / lista manual) sin índice real.
    idx_serie = serie_indice_real if serie_indice_real is not None else idx_serie_proxy
    usando_indice_real = serie_indice_real is not None

    def _ret_periodo(dias):
        if len(idx_serie) <= dias:
            return None
        return float(idx_serie.iloc[-1] / idx_serie.iloc[-dias - 1] - 1) * 100

    ret_1d, ret_1w, ret_1m = _ret_periodo(1), _ret_periodo(5), _ret_periodo(21)
    ret_3m, ret_6m, ret_1y = _ret_periodo(63), _ret_periodo(126), _ret_periodo(252)

    estado, emoji_estado, color_estado, desc_estado = _bd_estado_mercado(
        ret_1m, breadth_hoy, breadth_prev, snap_hoy['ad_score'], snap_hoy['nhnl_score']
    )

    # ── Card de estado ──────────────────────────────────────────────────
    st.markdown(f"""
    <div style="background:{color_estado}15;border:1.5px solid {color_estado};border-radius:14px;
         padding:22px 26px;text-align:center;margin:10px 0 22px 0">
      <div style="font-size:11px;color:{C_MUTED};text-transform:uppercase;letter-spacing:1.5px;margin-bottom:8px">
        Estado de Participación del Mercado — {nombre_universo}
      </div>
      <div style="font-size:24px;font-weight:800;color:{color_estado}">{emoji_estado} {estado}</div>
      <div style="font-size:13px;color:{C_TEXT};margin-top:10px;max-width:680px;margin-left:auto;
           margin-right:auto;line-height:1.6">
        {desc_estado}
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── KPIs principales ─────────────────────────────────────────────────
    kpi_cards_4([
        ('Breadth Score', f'{breadth_hoy:.0f}/100',
         (f"{breadth_hoy - breadth_prev:+.1f} vs. hace 1 mes" if breadth_prev is not None else 'Score compuesto'),
         _bd_color_score(breadth_hoy)),
        ('Avance / Declive', f"{snap_hoy['adv']} / {snap_hoy['dec']}",
         f"AD Score: {snap_hoy['ad_score']:.0f}/100", _bd_color_score(snap_hoy['ad_score'])),
        ('Máx / Mín 52 sem.', f"{snap_hoy['nh']} / {snap_hoy['nl']}",
         f"NH/NL Score: {snap_hoy['nhnl_score']:.0f}/100", _bd_color_score(snap_hoy['nhnl_score'])),
        ('Concentración Top 5', f"{conc['top5_pct']:.1f}%" if conc['top5_pct'] is not None else 'N/D',
         f"Score: {conc['conc_score']:.0f}/100", _bd_color_score(conc['conc_score'])),
    ])

    label_precio = f'📊 Rendimiento del índice real ({ticker_indice_real})' if usando_indice_real \
        else '📊 Rendimiento del índice proxy (ponderado por cap)'
    st.markdown(f'##### {label_precio}')
    cols_ret = st.columns(6)
    for col, (lbl, val) in zip(cols_ret,
        [('1D', ret_1d), ('1W', ret_1w), ('1M', ret_1m), ('3M', ret_3m), ('6M', ret_6m), ('1Y', ret_1y)]):
        with col:
            st.metric(lbl, f'{val:+.2f}%' if val is not None else 'N/D')

    # ── Subíndices ───────────────────────────────────────────────────────
    st.markdown('---')
    st.markdown('### 🧩 Subíndices de Amplitud')
    subitems = [
        ('Trend Breadth', snap_hoy['trend_score'], '25%'),
        ('Advance/Decline', snap_hoy['ad_score'], '20%'),
        ('New Highs/Lows', snap_hoy['nhnl_score'], '15%'),
        ('Volume Breadth', snap_hoy['vol_score'], '20%'),
        ('Concentration', conc['conc_score'], '20%'),
    ]
    cols_sub = st.columns(5)
    for col, (nombre, valor, peso) in zip(cols_sub, subitems):
        color_sub = _bd_color_score(valor)
        with col:
            st.markdown(f"""
            <div style="background:{C_BG1};border:1px solid {C_GRID};border-top:2px solid {color_sub};
                 border-radius:10px;padding:14px;text-align:center">
              <div style="font-size:10px;color:{C_MUTED};text-transform:uppercase">{nombre} ({peso})</div>
              <div style="font-size:22px;font-weight:700;color:{color_sub};margin-top:4px">{valor:.0f}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown('<div style="height:14px"></div>', unsafe_allow_html=True)

    fig_smas = go.Figure()
    vals_sma = [snap_hoy['pct20'], snap_hoy['pct50'], snap_hoy['pct200']]
    fig_smas.add_trace(go.Bar(
        x=['% > SMA20', '% > SMA50', '% > SMA200'], y=vals_sma,
        marker_color=[_bd_color_score(v) for v in vals_sma],
        text=[f'{v:.0f}%' for v in vals_sma], textposition='outside',
    ))
    fig_smas.add_hline(y=50, line_dash='dash', line_color=C_MUTED, opacity=0.5)
    fig_smas.update_layout(
        **PLOTLY_LAYOUT_BASE_BD, height=340,
        yaxis=dict(range=[0, 115], gridcolor=C_GRID, title='% de activos'),
        xaxis=dict(gridcolor=C_GRID),
        title=dict(text='Amplitud de Tendencia (Trend Breadth)', font=dict(color=C_TEXT, size=13)),
        margin=dict(l=10, r=10, t=45, b=10),
    )
    st.plotly_chart(fig_smas, use_container_width=True, config=PLOTLY_CONFIG, key='bd_fig_smas')

    # ── A/D Line histórica ───────────────────────────────────────────────
    st.markdown('### 📈 A/D Line histórica')
    ret_matrix = df_close.pct_change()
    adv_diaria = (ret_matrix > 0).sum(axis=1)
    dec_diaria = (ret_matrix < 0).sum(axis=1)
    ad_line = (adv_diaria - dec_diaria).cumsum()

    fig_ad = go.Figure()
    fig_ad.add_trace(go.Scatter(
        x=ad_line.index, y=ad_line.values, line=dict(color=C_MONSTER, width=2),
        fill='tozeroy', fillcolor='rgba(108,194,74,0.10)', name='A/D Line',
    ))
    fig_ad.update_layout(
        **PLOTLY_LAYOUT_BASE_BD, height=340,
        xaxis=dict(gridcolor=C_GRID), yaxis=dict(gridcolor=C_GRID, title='A/D acumulado'),
        title=dict(text='Advance/Decline Line', font=dict(color=C_TEXT, size=13)),
        margin=dict(l=10, r=10, t=45, b=10),
    )
    st.plotly_chart(fig_ad, use_container_width=True, config=PLOTLY_CONFIG, key='bd_fig_ad')

    if breadth_prev is not None:
        interp_tendencia = (
            'mejorando' if breadth_hoy > breadth_prev + 2 else
            'empeorando' if breadth_hoy < breadth_prev - 2 else
            'estable'
        )
        st.markdown(f"""
        <div style="background:{C_BG1};border:1px solid {C_GRID};border-left:3px solid {C_ACENT};
             border-radius:8px;padding:12px 16px;margin:10px 0;font-size:13px;line-height:1.7;color:#f5f7fa">
          <div style="color:{C_ACENT};font-weight:700;font-size:12px;margin-bottom:4px">📐 LECTURA</div>
          El Breadth Score pasó de {breadth_prev:.0f} a {breadth_hoy:.0f} en el último mes — la
          participación interna del mercado está <b>{interp_tendencia}</b>. Combinado con el estado
          "{estado}", esto {"confirma" if interp_tendencia != "estable" else "no cambia"} la lectura de arriba.
        </div>
        """, unsafe_allow_html=True)

    # ── Detalle por activo ───────────────────────────────────────────────
    st.markdown('---')
    st.markdown('### 📋 Detalle por activo')

    last_row = df_close.iloc[-1]
    n_tot = len(df_close)
    sma20_all = df_close.rolling(min(20, n_tot)).mean().iloc[-1]
    sma50_all = df_close.rolling(min(50, n_tot)).mean().iloc[-1] if n_tot >= 10 else sma20_all
    sma200_all = df_close.rolling(min(200, n_tot)).mean().iloc[-1] if n_tot >= 30 else sma50_all
    ret1d_all = ret_matrix.iloc[-1]
    ventana_hl2 = min(252, n_tot)
    max_all = df_close.rolling(ventana_hl2).max().iloc[-1]
    min_all = df_close.rolling(ventana_hl2).min().iloc[-1]

    filas = []
    for tk in df_close.columns:
        peso_tk = float(pesos_full.get(tk, 0)) * 100
        precio_tk = last_row.get(tk)
        r1d = ret1d_all.get(tk)
        filas.append({
            'Ticker': tk,
            'Precio': fmt_precio(precio_tk),
            'Ret 1D %': round(float(r1d) * 100, 2) if pd.notna(r1d) else None,
            '>SMA20': '✅' if pd.notna(precio_tk) and precio_tk > sma20_all.get(tk, np.inf) else '❌',
            '>SMA50': '✅' if pd.notna(precio_tk) and precio_tk > sma50_all.get(tk, np.inf) else '❌',
            '>SMA200': '✅' if pd.notna(precio_tk) and precio_tk > sma200_all.get(tk, np.inf) else '❌',
            'Máx 52s': '🔺' if pd.notna(precio_tk) and precio_tk >= max_all.get(tk, np.inf) else '',
            'Mín 52s': '🔻' if pd.notna(precio_tk) and precio_tk <= min_all.get(tk, -np.inf) else '',
            'Peso %': round(peso_tk, 2) if peso_tk else None,
        })

    df_detalle = pd.DataFrame(filas).sort_values('Ret 1D %', ascending=False, na_position='last')

    def _color_ret1d(val):
        try:
            v = float(val)
            return f'color:{"#3fb950" if v >= 0 else "#f85149"};font-weight:600'
        except Exception:
            return ''

    _map_bd = 'map' if hasattr(df_detalle.style, 'map') else 'applymap'
    styled_detalle = (df_detalle.style
        .pipe(lambda s: getattr(s, _map_bd)(_color_ret1d, subset=['Ret 1D %']))
        .set_properties(**{'background-color': C_BG1, 'color': C_TEXT, 'border': f'1px solid {C_GRID}'})
        .set_table_styles([
            {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', C_TEXT),
                ('font-weight', '700'), ('text-align', 'center'),
                ('border-bottom', f'2px solid {C_ACENT}'), ('font-size', '11px')]},
            {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]},
        ])
    )
    st.dataframe(styled_detalle, use_container_width=True, hide_index=True,
                 height=min(600, max(200, len(df_detalle) * 35 + 45)))

    if chips_navegacion:
        chips_navegacion(df_detalle['Ticker'].tolist(), 'bd_detalle')

    st.caption(
        '⚠️ Al no existir en Yahoo Finance una lista pública de constituyentes reales de un índice, '
        'este módulo usa como "universo de mercado" el grupo de tickers que elegiste arriba (industria '
        'predefinida o lista manual) a modo de proxy representativo. Cuantos más activos incluyas, '
        'más fiel es la lectura de amplitud real del mercado que estás mirando.'
    )
