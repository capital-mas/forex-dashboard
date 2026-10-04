# ==============================================================
#  MOTOR DE VALORACIÓN CUANTITATIVA — 4 motores de valor
#  1) Crecimiento de ingresos anual   2) Margen neto objetivo
#  3) Recompra de acciones anual      4) Múltiplo P/E (PER) objetivo
#  Datos: Yahoo Finance (yfinance). Pensado para Capital+ (Streamlit).
#
#  Uso en app principal (misma firma que antes):
#    from modulo_valuacion import modulo_valuacion
#    modulo_valuacion(selector_ticker_autocomplete=selector_ticker_autocomplete,
#                     kpi_cards_4=kpi_cards_4, fmt_precio=fmt_precio,
#                     PLOTLY_CONFIG=PLOTLY_CONFIG, validar_ticker=validar_ticker)
#
#  Modelo:
#    Ingresos_N = Ingresos_0 × (1+g)^N
#    Resultado neto_N = Ingresos_N × margen neto
#    Acciones_N = Acciones_0 × (1−recompra)^N
#    EPS_N = Resultado neto_N / Acciones_N
#    Precio objetivo en N = EPS_N × PER
#    Valor estimado hoy = Precio objetivo / (1+Ke)^N      (N = 5 años)
# ==============================================================

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

N_ANIOS = 5
PER_MIN, PER_MAX = 5.0, 80.0

ESC_CLAVES = ['Bajista', 'Base', 'Alcista']
OPC_RADIO = ['Bajista', 'Base', 'Alcista', 'Personalizado']
ETQ_RADIO = {'Bajista': '🔴 Bajista', 'Base': '🎯 Base', 'Alcista': '🟢 Alcista',
             'Personalizado': '⚙️ Personalizado'}

# Riesgo país por defecto (puntos básicos) según país de la empresa
RIESGO_PAIS = {
    'United States': ('US', 0), 'USA': ('US', 0),
    'Germany': ('DE', 0), 'Japan': ('JP', 0),
    'South Korea': ('KR', 60), 'Korea, Republic of': ('KR', 60),
    'Brazil': ('BR', 220), 'Mexico': ('MX', 300), 'Argentina': ('AR', 655),
}
RF_DEF, ERP_DEF = 4.00, 5.50      # % por defecto
MEGA_CAP = 500e9                   # USD
CRECIMIENTO_ALTO = 0.15
ESCALA_MAX_ALCISTA = 2.5           # valor alcista / precio

DISCLAIMER_VAL = ("Las valoraciones resultantes son estimaciones teóricas basadas en modelos financieros e "
                  "hipótesis asumidas. No constituyen recomendaciones financieras ni predicciones seguras del mercado.")


# ──────────────────────────────────────────────────────────────
#  1) DATOS (Yahoo Finance)
# ──────────────────────────────────────────────────────────────

def _serie(df, nombres, n=5):
    """Valores de una fila contable (más reciente primero)."""
    try:
        if df is None or df.empty:
            return []
        for nm in nombres:
            if nm in df.index:
                vals = [float(v) for v in df.loc[nm].iloc[:n] if pd.notna(v)]
                if vals:
                    return vals
    except Exception:
        pass
    return []


def _val_cargar(ticker):
    """Descarga cruda. Levanta ValueError si faltan datos (así el fallo NO se cachea)."""
    import time
    import yfinance as yf
    s = yf.Ticker(ticker)

    info = {}
    for _ in range(3):
        try:
            info = s.info or {}
        except Exception:
            info = {}
        if info:
            break
        time.sleep(1.5)

    def _fin(attr):
        try:
            df = getattr(s, attr)
            return df if df is not None else pd.DataFrame()
        except Exception:
            return pd.DataFrame()

    inc, bal = _fin('financials'), _fin('balance_sheet')

    # Precio: info → fast_info → historial
    price = info.get('currentPrice') or info.get('regularMarketPrice')
    fi = None
    try:
        fi = s.fast_info
    except Exception:
        pass
    if not price and fi is not None:
        price = getattr(fi, 'last_price', None)
    if not price:
        try:
            h = s.history(period='5d')
            if h is not None and not h.empty:
                price = float(h['Close'].dropna().iloc[-1])
        except Exception:
            pass

    # Acciones
    shares = info.get('sharesOutstanding')
    mcap = info.get('marketCap')
    if not shares and fi is not None:
        shares = getattr(fi, 'shares', None)
    if not mcap and fi is not None:
        mcap = getattr(fi, 'market_cap', None)
    if not shares and mcap and price:
        shares = mcap / price
    if not shares:
        sh_l = _serie(bal, ['Ordinary Shares Number', 'Share Issued'], 1)
        shares = sh_l[0] if sh_l else None

    # Ventas y resultado neto
    rev_l = _serie(inc, ['Total Revenue', 'Revenue'])
    rev0 = info.get('totalRevenue') or (rev_l[0] if rev_l else None)
    ni_l = _serie(inc, ['Net Income Common Stockholders', 'Net Income'])
    ni0 = info.get('netIncomeToCommon') or (ni_l[0] if ni_l else None)

    faltan = [n for n, v in [('precio', price), ('acciones en circulación', shares),
                             ('ventas', rev0)] if not v]
    if faltan:
        raise ValueError('Yahoo no devolvió: ' + ', '.join(faltan)
                         + (' (respuesta vacía, probable rate limit)' if not info else ''))

    margen = (ni0 / rev0) if ni0 is not None and rev0 else None

    # Crecimiento histórico: CAGR y volatilidad interanual
    cagr, vol_g = None, None
    if len(rev_l) >= 2 and rev_l[-1] > 0:
        cagr = (rev_l[0] / rev_l[-1]) ** (1 / (len(rev_l) - 1)) - 1
        yoy = [rev_l[i] / rev_l[i + 1] - 1 for i in range(len(rev_l) - 1) if rev_l[i + 1] > 0]
        if len(yoy) >= 2:
            vol_g = float(np.std(yoy))
    if cagr is None:
        cagr = info.get('revenueGrowth')

    # Recompras históricas (reducción anualizada del conteo de acciones)
    bb_hist = 0.0
    sh_h = _serie(inc, ['Basic Average Shares', 'Diluted Average Shares'], 4)
    if len(sh_h) >= 2 and sh_h[-1] > 0 and sh_h[0] > 0:
        bb_hist = 1 - (sh_h[0] / sh_h[-1]) ** (1 / (len(sh_h) - 1))
    bb_hist = float(min(max(bb_hist, 0.0), 0.10))

    # Consensus de analistas
    per_info = info.get('trailingPE') or info.get('forwardPE')

    return dict(
        ticker=ticker, nombre=info.get('longName') or ticker,
        sector=info.get('sector'), pais=info.get('country'),
        moneda=info.get('currency'), moneda_fin=info.get('financialCurrency'),
        precio=float(price), acciones=float(shares), mcap=float(mcap or price * shares),
        rev0=float(rev0), ni0=float(ni0) if ni0 is not None else None, margen=margen,
        cagr=cagr, vol_g=vol_g, bb_hist=bb_hist, per_info=per_info,
        beta=info.get('beta'),
        g_analistas=info.get('revenueGrowth'),
        target_analistas=info.get('targetMeanPrice'),
        n_analistas=info.get('numberOfAnalystOpinions'),
        recomendacion=info.get('recommendationKey'),
    )


@st.cache_data(ttl=3600, show_spinner=False)
def _val_cargar_ok(ticker):
    return _val_cargar(ticker)


def _val_cargar_seguro(ticker):
    try:
        return _val_cargar_ok(ticker), None
    except Exception as e:
        return None, str(e) or e.__class__.__name__


# ──────────────────────────────────────────────────────────────
#  2) MOTOR DE CÁLCULO
# ──────────────────────────────────────────────────────────────

def _valor(g, m, bb, per, rev0, acciones, ke):
    """Valor teórico por acción hoy con los 4 motores."""
    rev_n = rev0 * (1 + g) ** N_ANIOS
    ni_n = rev_n * m
    sh_n = acciones * (1 - bb) ** N_ANIOS
    eps_n = ni_n / sh_n
    return max(eps_n * per, 0.0) / (1 + ke) ** N_ANIOS


def _per_implicito(g, m, bb, precio, rev0, acciones, ke):
    """PER que iguala exactamente el valor al precio (forma cerrada)."""
    eps_n = rev0 * (1 + g) ** N_ANIOS * m / (acciones * (1 - bb) ** N_ANIOS)
    if eps_n <= 0:
        return None
    return precio * (1 + ke) ** N_ANIOS / eps_n


def _bisec(f, lo, hi, target, it=80):
    flo, fhi = f(lo) - target, f(hi) - target
    if np.isnan(flo) or np.isnan(fhi) or flo * fhi > 0:
        return None
    for _ in range(it):
        mid = (lo + hi) / 2
        fm = f(mid) - target
        if flo * fm <= 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


def _calibrar_base(d, ke):
    """Ingeniería inversa: fija los 4 supuestos para que valor = precio (upside 0%).
    1) Ancla g, margen y recompra en datos históricos y despeja el PER implícito.
    2) Si ese PER es inverosímil, ancla el PER y despeja g (y si no alcanza, el margen)."""
    precio, rev0, acc = d['precio'], d['rev0'], d['acciones']
    g0 = float(np.clip(d['cagr'] if d['cagr'] is not None else 0.05, -0.05, 0.25))
    m0 = d['margen'] if d['margen'] and d['margen'] > 0 else 0.10
    m0 = float(np.clip(m0, 0.01, 0.60))
    b0 = d['bb_hist']
    avisos = []
    if not d['margen'] or d['margen'] <= 0:
        avisos.append('Margen neto actual negativo o no disponible: se parte de un margen de 10% como ancla.')

    per = _per_implicito(g0, m0, b0, precio, rev0, acc, ke)
    if per is not None and PER_MIN <= per <= PER_MAX:
        return dict(g=g0, m=m0, bb=b0, per=per), avisos

    per_anc = float(np.clip(d['per_info'] if d['per_info'] and d['per_info'] > 0 else 20.0, 8.0, 60.0))
    f_g = lambda x: _valor(x, m0, b0, per_anc, rev0, acc, ke)
    g_s = _bisec(f_g, -0.30, 0.80, precio)
    if g_s is not None:
        avisos.append(f'El PER implícito con los anclas históricos ({per:.1f}x) era inverosímil: '
                      f'se fijó PER {per_anc:.1f}x y se despejó el crecimiento.' if per else
                      f'Se fijó PER {per_anc:.1f}x y se despejó el crecimiento.')
        return dict(g=g_s, m=m0, bb=b0, per=per_anc), avisos
    f_m = lambda x: _valor(g0, x, b0, per_anc, rev0, acc, ke)
    m_s = _bisec(f_m, 0.01, 0.85, precio)
    if m_s is not None:
        avisos.append(f'Se fijó PER {per_anc:.1f}x y se despejó el margen neto.')
        return dict(g=g0, m=m_s, bb=b0, per=per_anc), avisos
    # último recurso: PER implícito sin acotar (siempre iguala el precio si EPS > 0)
    if per is not None:
        avisos.append(f'El PER implícito ({per:.1f}x) queda fuera del rango habitual: el mercado descuenta '
                      'supuestos extremos, o el modelo no encaja bien con esta empresa.')
        return dict(g=g0, m=m0, bb=b0, per=per), avisos
    return None, ['No se pudo calibrar: el resultado neto proyectado es ≤ 0.']


def _riesgo_pais(nombre):
    """(código, puntos) para el país detectado; (None, 0) si no está mapeado."""
    return RIESGO_PAIS.get((nombre or '').strip(), (None, 0))


def _calc_ke(rf_pct, beta, erp_pct, rp_pts):
    """Ke = Rf + β × ERP + Riesgo país (puntos / 100). Devuelve decimal."""
    return (rf_pct + beta * erp_pct + rp_pts / 100.0) / 100.0


def _generar_presets(d, base, ke):
    """Bajista / Base / Alcista normalizados para cualquier empresa global."""
    sg = float(np.clip(d['vol_g'] if d['vol_g'] is not None else 0.04, 0.02, 0.06))
    g, m, bb, per = base['g'], base['m'], base['bb'], base['per']

    g_bull = g + sg
    if d['g_analistas'] is not None and np.isfinite(d['g_analistas']):
        g_bull = max(g_bull, float(np.clip(d['g_analistas'], -0.05, 0.40)))
    g_bear = g - sg

    if g > CRECIMIENTO_ALTO:                         # alto crecimiento
        g_bull = min(g_bull, g * 1.30)
        g_bear = max(g_bear, g * 0.50)
    elif d['mcap'] > MEGA_CAP:                       # mega-cap / madura
        g_bull = min(g_bull, g + 0.035)
        g_bear = max(g_bear, -0.035)                 # piso de contracción (entre -2% y -5%)

    bear = dict(g=g_bear, m=max(0.005, m * 0.90), bb=bb * 0.5, per=max(PER_MIN, per * 0.80))
    bull = dict(g=g_bull, m=min(0.85, m * 1.08), bb=max(bb * 1.30, bb + 0.005),
                per=min(PER_MAX * 1.5, per * 1.15))

    # Control visual de escala: el alcista no puede superar 2.5x el precio
    f = lambda p: _valor(p['g'], p['m'], p['bb'], p['per'], d['rev0'], d['acciones'], ke)
    tope = ESCALA_MAX_ALCISTA * d['precio']
    if f(bull) > tope:
        mezcla = lambda t: {k: base[k] + t * (bull[k] - base[k]) for k in ('g', 'm', 'bb', 'per')}
        t = _bisec(lambda x: f(mezcla(x)), 0.0, 1.0, tope)
        bull = mezcla(t if t is not None else 0.0)
    return {'Bajista': bear, 'Base': dict(base), 'Alcista': bull}


# ──────────────────────────────────────────────────────────────
#  3) DIAGNÓSTICO
# ──────────────────────────────────────────────────────────────

def _diagnostico(up):
    if up is None or not np.isfinite(up):
        return 'N/D'
    if up > 15:
        return '🟢 ALCISTA FUERTE'
    if up > 5:
        return '🟢 ALCISTA'
    if up >= -5:
        return '🟡 NEUTRAL / PRECIO JUSTO'
    if up >= -15:
        return '🔴 BAJISTA'
    return '🔴 MUY BAJISTA'


def _color_diag(up):
    if up is None or not np.isfinite(up):
        return '#6b7d9a'
    if up > 5:
        return '#3fb950'
    if up >= -5:
        return '#e3b341'
    return '#f85149'


def _n(x, nd=2):
    try:
        if x is None or not np.isfinite(x):
            return None
        return round(float(x), nd)
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────
#  4) GRÁFICOS
# ──────────────────────────────────────────────────────────────

def _fig_escenarios(vals, precio, base_layout):
    colores = {'Bajista': '#f85149', 'Base': '#e3b341', 'Alcista': '#3fb950', 'Personalizado': '#bc8cff'}
    fig = go.Figure(go.Bar(
        x=[ETQ_RADIO[k] for k in vals], y=list(vals.values()),
        marker_color=[colores[k] for k in vals],
        text=[f'{v:.2f}' for v in vals.values()], textposition='outside'))
    fig.add_hline(y=precio, line_dash='dash', line_color='#3a7bd5',
                  annotation_text=f'Precio actual {precio:.2f}', annotation_position='top left')
    fig.update_layout(**base_layout, height=400,
                      title=dict(text='Valor estimado por acción vs precio de mercado',
                                 font=dict(size=14, color='#e6edf3')),
                      yaxis=dict(gridcolor='#21262d'), xaxis=dict(gridcolor='#21262d'),
                      margin=dict(l=10, r=10, t=60, b=10), showlegend=False)
    return fig


def _fig_heatmap(p, d, ke, base_layout):
    # Eje horizontal: crecimiento centrado en el del escenario activo (±2pp)
    dg = [-0.04, -0.02, 0.0, 0.02, 0.04]
    gs = [p['g'] + x for x in dg]

    # Eje vertical: el PER activo es la fila central, escalones simétricos
    per_c = p['per']
    paso = max(0.5, round(per_c * 0.10 * 2) / 2)
    paso = min(paso, per_c / 2.5)
    pers = [per_c + k * paso for k in (-2, -1, 0, 1, 2)]

    z = [[_valor(g, p['m'], p['bb'], pe, d['rev0'], d['acciones'], ke) for g in gs] for pe in pers]

    x_lbl = [f'{g*100:.1f}%' for g in gs]
    y_lbl = [f'{pe:.1f}x' for pe in pers]
    fig = go.Figure(go.Heatmap(
        z=z, x=x_lbl, y=y_lbl,
        colorscale='RdYlGn', zmid=d['precio'],
        text=np.round(z, 2), texttemplate='%{text}', colorbar=dict(title='Valor/acc.')))

    # Recuadro de la celda central (índice 2 de 0 a 4 -> 1.5 a 2.5)
    fig.add_shape(type='rect', xref='x', yref='y',
                  x0=1.5, x1=2.5, y0=1.5, y1=2.5,
                  line=dict(color='#e6edf3', width=3), fillcolor='rgba(0,0,0,0)')

    fig.update_layout(**base_layout, height=380,
                      title=dict(text='Sensibilidad — PER (vertical) × crecimiento de ingresos (horizontal)',
                                 font=dict(size=14, color='#e6edf3')),
                      xaxis=dict(title='Crecimiento anual de ingresos', type='category'),
                      yaxis=dict(title=f'PER objetivo (centro = {per_c:.1f}x, paso {paso:.1f}x)',
                                 type='category', autorange='reversed'),
                      margin=dict(l=10, r=10, t=55, b=10))
    return fig


# ──────────────────────────────────────────────────────────────
#  5) ESTADO E INTERACCIÓN
# ──────────────────────────────────────────────────────────────

def _claves(tk):
    return dict(g=f'v_g_{tk}', m=f'v_m_{tk}', bb=f'v_b_{tk}', per=f'v_p_{tk}',
                rf=f'v_rf_{tk}', beta=f'v_beta_{tk}', erp=f'v_erp_{tk}', rp=f'v_rp_{tk}',
                esc=f'v_esc_{tk}', presets=f'v_presets_{tk}', sig=f'v_sig_{tk}')


def _volcar_preset(tk, p):
    K = _claves(tk)
    st.session_state[K['g']] = round(p['g'] * 100, 2)
    st.session_state[K['m']] = round(p['m'] * 100, 2)
    st.session_state[K['bb']] = round(p['bb'] * 100, 2)
    st.session_state[K['per']] = round(p['per'], 2)


def _cb_escenario(tk):
    K = _claves(tk)
    sel = st.session_state.get(K['esc'])
    if sel in ESC_CLAVES:
        _volcar_preset(tk, st.session_state[K['presets']][sel])


def _cb_custom(tk):
    st.session_state[_claves(tk)['esc']] = 'Personalizado'


def _leer(tk, clave, base_val, escala=1.0):
    """Lee un input; si está vacío/None, restaura el valor del Escenario Base."""
    v = st.session_state.get(_claves(tk)[clave])
    if v is None:
        return base_val, True
    try:
        v = float(v)
        if not np.isfinite(v):
            return base_val, True
    except Exception:
        return base_val, True
    return v / escala, False


def _sec(titulo):
    st.markdown(f'<div style="margin:14px 0 6px 0;font-size:11px;color:#6CC24A;font-weight:700;'
                f'letter-spacing:.6px;text-transform:uppercase">{titulo}</div>', unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────
#  6) UI
# ──────────────────────────────────────────────────────────────

def modulo_valuacion(selector_ticker_autocomplete, kpi_cards_4, fmt_precio, PLOTLY_CONFIG,
                     validar_ticker=None):
    PLOTLY_BASE = dict(plot_bgcolor='#0d1117', paper_bgcolor='#07090f',
                       font=dict(color='#b0bcd0', family='Inter, sans-serif'), dragmode=False)

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #6CC24A; border-radius:14px;
         padding:28px 32px; margin-bottom:24px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">🏦 Motor de Valoración Cuantitativa</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        4 motores de valor: crecimiento de ingresos, margen neto, recompra de acciones y PER objetivo.
        El escenario Base se calibra por ingeniería inversa para igualar el precio de mercado (upside 0%);
        los escenarios Bajista y Alcista se generan automáticamente. Podés editar cualquier supuesto.
      </div>
    </div>
    """, unsafe_allow_html=True)

    c_in, c_btn = st.columns([4, 1])
    with c_in:
        tk = selector_ticker_autocomplete('val_ticker', label='Ticker a valuar')
    with c_btn:
        st.markdown('<div style="height:6px"></div>', unsafe_allow_html=True)
        if st.button('▶ Valuar', use_container_width=True, key='val_btn') and tk:
            st.session_state['val_ticker_ok'] = tk

    ticker = st.session_state.get('val_ticker_ok')
    if not ticker:
        st.info('Elegí un ticker y presioná "Valuar".')
        return

    with st.spinner(f'Descargando datos fundamentales de {ticker}...'):
        d, err = _val_cargar_seguro(ticker)
    if d is None:
        st.error(f'No se pudieron cargar los datos de {ticker}. Motivo: {err}')
        if st.button('🔄 Reintentar', key=f'val_retry_{ticker}'):
            st.rerun()
        st.caption('Si dice "rate limit", esperá 1-2 minutos y reintentá. Con tickers sin estados '
                   'financieros en Yahoo (cripto, forex, commodities) el módulo no puede valuar.')
        return

    if d['sector'] == 'Financial Services':
        st.warning('⚠️ Empresa financiera: el modelo por resultado neto/PER funciona razonablemente, pero '
                   'conviene contrastarlo con P/B y ROE.')
    if d['moneda_fin'] and d['moneda'] and d['moneda_fin'] != d['moneda']:
        st.warning(f"⚠️ Moneda de los estados financieros ({d['moneda_fin']}) distinta a la de cotización "
                   f"({d['moneda']}). Típico en ADRs: el valor por acción queda mal escalado sin convertir.")

    st.markdown(f"**{d['nombre']}** ({ticker}) · {d['sector'] or 'N/D'} · {d['pais'] or 'N/D'} · "
                f"Precio: **{fmt_precio(d['precio'])}** · Ventas: {d['rev0']/1e9:,.2f}B · "
                f"Margen neto actual: "
                f"{(d['margen']*100 if d['margen'] is not None else float('nan')):.1f}%")

    K = _claves(ticker)

    # ── Inicialización por ticker: Ke por defecto, calibración y presets ──
    sig = (ticker, round(d['precio'], 2))
    if st.session_state.get(K['sig']) != sig:
        beta0 = round(float(np.clip(d['beta'] if d['beta'] else 1.0, 0.0, 4.0)), 2)
        cod_pais, rp0 = _riesgo_pais(d['pais'])
        defs = dict(rf=RF_DEF, beta=beta0, erp=ERP_DEF, rp=int(rp0), pais=cod_pais)
        st.session_state[f'v_kedef_{ticker}'] = defs
        st.session_state[K['rf']] = defs['rf']
        st.session_state[K['beta']] = defs['beta']
        st.session_state[K['erp']] = defs['erp']
        st.session_state[K['rp']] = defs['rp']
        ke0 = _calc_ke(defs['rf'], beta0, defs['erp'], rp0)
        st.session_state[f'v_ke0_{ticker}'] = ke0
        base, avisos = _calibrar_base(d, ke0)
        if base is None:
            st.error(' '.join(avisos))
            return
        presets = _generar_presets(d, base, ke0)
        st.session_state[K['presets']] = presets
        st.session_state[f'v_avisos_{ticker}'] = avisos
        st.session_state[K['esc']] = 'Base'
        _volcar_preset(ticker, presets['Base'])
        st.session_state[K['sig']] = sig

    defs = st.session_state[f'v_kedef_{ticker}']
    presets = st.session_state[K['presets']]
    base = presets['Base']

    # ── Ke multimercado (en vivo) ──
    _sec('🌎 Tasa de descuento Ke (multimercado)')
    r1, r2, r3, r4, r5 = st.columns([1, 1, 1, 1.2, 1.2])
    with r1:
        st.number_input('Tasa libre de riesgo Rf %', 0.0, 20.0, value=None, step=0.1, format='%.2f',
                        key=K['rf'], placeholder=f"{defs['rf']:.2f}")
    with r2:
        st.number_input('Beta β', 0.0, 4.0, value=None, step=0.05, format='%.2f',
                        key=K['beta'], placeholder=f"{defs['beta']:.2f}")
    with r3:
        st.number_input('Prima de riesgo ERP %', 0.0, 20.0, value=None, step=0.1, format='%.2f',
                        key=K['erp'], placeholder=f"{defs['erp']:.2f}")
    with r4:
        st.number_input('Riesgo país (puntos)', 0, 10000, value=None, step=5, format='%d',
                        key=K['rp'], placeholder=f"{defs['rp']}",
                        help='Se ingresa en puntos básicos (ej. 1200 o 220) y se divide por 100: '
                             '1200 pts → 12.00%. Se autocompleta según el país de la empresa.')
    rf, _ = _leer(ticker, 'rf', defs['rf'])
    beta, _ = _leer(ticker, 'beta', defs['beta'])
    erp, _ = _leer(ticker, 'erp', defs['erp'])
    rp, _ = _leer(ticker, 'rp', float(defs['rp']))
    rp = int(round(rp))
    ke = max(_calc_ke(rf, beta, erp, rp), 0.01)
    with r5:
        st.metric('Ke', f'{ke*100:.2f}%')
    pais_txt = (f"País detectado: {d['pais']} ({defs['pais']})" if defs['pais']
                else f"País detectado: {d['pais'] or 'N/D'} (sin riesgo país predefinido: 0 pts)")
    st.caption(f"{pais_txt} · Riesgo país {rp} pts → {rp/100:.2f}% · "
               f"Ke = Rf + β × ERP + Riesgo país = {rf:.2f}% + {beta:.2f} × {erp:.2f}% + {rp/100:.2f}% "
               f"= **{ke*100:.2f}%**. El escenario Base se calibró con el Ke inicial "
               f"({st.session_state[f'v_ke0_{ticker}']*100:.2f}%); si lo modificás, todos los valores se "
               f"actualizan en vivo y el upside del Base puede dejar de ser 0%.")
    for a in st.session_state.get(f'v_avisos_{ticker}', []):
        st.info('ℹ️ ' + a)

    # ── Selector de escenario ──
    _sec('🎛️ Escenario')
    st.radio('Escenario', OPC_RADIO, key=K['esc'], horizontal=True,
             format_func=lambda x: ETQ_RADIO[x], label_visibility='collapsed',
             on_change=_cb_escenario, args=(ticker,))

    # ── Los 4 motores (editables) ──
    _sec('🚀 Los 4 motores de valor')
    i1, i2, i3, i4 = st.columns(4)
    with i1:
        st.number_input('Crecimiento de ingresos anual %', -50.0, 100.0, value=None, step=0.5,
                        format='%.2f', key=K['g'], on_change=_cb_custom, args=(ticker,),
                        placeholder=f"{base['g']*100:.2f}")
    with i2:
        st.number_input('Margen neto objetivo %', -50.0, 90.0, value=None, step=0.5,
                        format='%.2f', key=K['m'], on_change=_cb_custom, args=(ticker,),
                        placeholder=f"{base['m']*100:.2f}")
    with i3:
        st.number_input('Recompra de acciones anual %', -10.0, 30.0, value=None, step=0.25,
                        format='%.2f', key=K['bb'], on_change=_cb_custom, args=(ticker,),
                        placeholder=f"{base['bb']*100:.2f}")
    with i4:
        st.number_input('Múltiplo P/E objetivo (x)', 1.0, 200.0, value=None, step=0.5,
                        format='%.2f', key=K['per'], on_change=_cb_custom, args=(ticker,),
                        placeholder=f"{base['per']:.2f}")

    # Fallback de seguridad: casillas vacías → valor del Escenario Base
    g, v1 = _leer(ticker, 'g', base['g'], 100)
    m, v2 = _leer(ticker, 'm', base['m'], 100)
    bb, v3 = _leer(ticker, 'bb', base['bb'], 100)
    per, v4 = _leer(ticker, 'per', base['per'])
    if any([v1, v2, v3, v4]):
        st.caption('↩️ Alguna casilla quedó vacía: se usa el valor del Escenario Base para ese motor.')
    activo = dict(g=g, m=m, bb=bb, per=per)

    esc_activo = st.session_state.get(K['esc'], 'Base')
    if esc_activo not in OPC_RADIO:
        esc_activo = 'Base'

    # ── Valuación de todos los escenarios ──
    def _eval(p):
        v = _valor(p['g'], p['m'], p['bb'], p['per'], d['rev0'], d['acciones'], ke)
        up = (v / d['precio'] - 1) * 100
        return v, up

    res = {}
    for nm in ESC_CLAVES:
        v, up = _eval(presets[nm])
        res[nm] = dict(p=presets[nm], v=v, up=up)
    if esc_activo == 'Personalizado':
        v, up = _eval(activo)
        res['Personalizado'] = dict(p=activo, v=v, up=up)
        act = res['Personalizado']
    else:
        # si hay escenario preset activo, el valor mostrado sale de los inputs vigentes (== preset)
        v, up = _eval(activo)
        act = dict(p=activo, v=v, up=up)

    diag = _diagnostico(act['up'])
    kpi_cards_4([
        ('Precio de mercado', fmt_precio(d['precio']), ticker, '#3a7bd5'),
        (f'Valor estimado ({ETQ_RADIO[esc_activo]})', fmt_precio(act['v']),
         f'PER {act["p"]["per"]:.1f}x · {N_ANIOS} años · Ke {ke*100:.1f}%', '#6CC24A'),
        ('Upside / Downside', f'{act["up"]:+.1f}%', 'vs precio actual', _color_diag(act['up'])),
        ('Diagnóstico', diag, 'según escala de upside', _color_diag(act['up'])),
    ])

    tab_esc, tab_sens = st.tabs(['📊 Escenarios', '🔥 Sensibilidad'])

    with tab_esc:
        filas = []
        for nm, r in res.items():
            filas.append({
                'Escenario': ETQ_RADIO[nm],
                'Crec. ingresos %': r['p']['g'] * 100, 'Margen neto %': r['p']['m'] * 100,
                'Recompra %': r['p']['bb'] * 100, 'PER (x)': r['p']['per'],
                'Valor estimado': r['v'], 'Upside %': r['up'], 'Diagnóstico': _diagnostico(r['up']),
            })
        st.dataframe(pd.DataFrame(filas).style.format({
            'Crec. ingresos %': '{:.2f}', 'Margen neto %': '{:.2f}', 'Recompra %': '{:.2f}',
            'PER (x)': '{:.2f}', 'Valor estimado': '{:.2f}', 'Upside %': '{:+.2f}%'}),
            use_container_width=True, hide_index=True)
        st.plotly_chart(_fig_escenarios({k: r['v'] for k, r in res.items()}, d['precio'], PLOTLY_BASE),
                        use_container_width=True, config=PLOTLY_CONFIG, key='val_fig_esc')

        # Proyección del escenario activo
        p = act['p']
        filas_p = []
        for t in range(1, N_ANIOS + 1):
            rev_t = d['rev0'] * (1 + p['g']) ** t
            ni_t = rev_t * p['m']
            sh_t = d['acciones'] * (1 - p['bb']) ** t
            filas_p.append({'Año': f'Año {t}', 'Ventas (M)': rev_t / 1e6, 'Resultado neto (M)': ni_t / 1e6,
                            'Acciones (M)': sh_t / 1e6, 'EPS': ni_t / sh_t})
        st.markdown(f'##### Proyección — escenario {ETQ_RADIO[esc_activo]}')
        st.dataframe(pd.DataFrame(filas_p).set_index('Año').style.format(
            {'Ventas (M)': '{:,.1f}', 'Resultado neto (M)': '{:,.1f}', 'Acciones (M)': '{:,.1f}', 'EPS': '{:.2f}'}),
            use_container_width=True)
        extra = ''
        if d['target_analistas']:
            extra = (f" · Precio objetivo medio de analistas: {fmt_precio(d['target_analistas'])}"
                     f"{' (' + str(d['n_analistas']) + ' analistas)' if d['n_analistas'] else ''}"
                     f"{' · consenso: ' + str(d['recomendacion']) if d['recomendacion'] else ''}")
        st.caption(f"Valor = EPS año {N_ANIOS} × PER, descontado a Ke. Los presets Bajista/Alcista se derivan del "
                   f"escenario Base según la volatilidad histórica del crecimiento "
                   f"({(d['vol_g'] if d['vol_g'] is not None else 0.04)*100:.1f}pp) y el consensus de crecimiento."
                   + extra)

    with tab_sens:
        st.plotly_chart(_fig_heatmap(act['p'], d, ke, PLOTLY_BASE), use_container_width=True,
                        config=PLOTLY_CONFIG, key='val_fig_heat')
        st.caption('Valor por acción para el escenario activo variando crecimiento y PER. '
                   'Verde = por encima del precio de mercado, rojo = por debajo.')

    st.markdown('---')
    st.caption('⚠️ ' + DISCLAIMER_VAL)
