# ==============================================================
#  SIMULADOR DE VALUACIÓN — DCF + Múltiplos + Sensibilidad + Ingeniería inversa
#  Datos: Yahoo Finance (yfinance). Pensado para Capital+ (Streamlit).
#
#  Uso en app principal:
#    from modulo_valuacion import modulo_valuacion
#    modulo_valuacion(selector_ticker_autocomplete=selector_ticker_autocomplete,
#                     kpi_cards_4=kpi_cards_4, fmt_precio=fmt_precio,
#                     PLOTLY_CONFIG=PLOTLY_CONFIG, validar_ticker=validar_ticker)
# ==============================================================

import json
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

HORIZONTE_PROY = 5

ESCENARIOS_VAL = {
    'conservador': dict(d_growth=-0.03, d_margin=-0.02, d_wacc=+0.005, d_g=-0.005, f_mult=0.85),
    'base':        dict(d_growth=0.0,   d_margin=0.0,   d_wacc=0.0,    d_g=0.0,    f_mult=1.00),
    'expansivo':   dict(d_growth=+0.03, d_margin=+0.02, d_wacc=-0.005, d_g=+0.005, f_mult=1.15),
}

METODOS_MULT = {'EV/EBITDA': 'ev_ebitda', 'PER': 'per', 'P/FCF': 'pfcf'}
ETIQUETA_METODO = {'ev_ebitda': 'EV/EBITDA', 'per': 'PER', 'pfcf': 'P/FCF'}

DISCLAIMER_VAL = ("Las valoraciones resultantes son estimaciones teóricas basadas en modelos financieros e "
                  "hipótesis asumidas. No constituyen recomendaciones financieras ni predicciones seguras del mercado.")


# ──────────────────────────────────────────────────────────────
#  1) EXTRACCIÓN DE DATOS (Yahoo Finance)
# ──────────────────────────────────────────────────────────────

def _serie(df, nombres, n=4):
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


def _prom_ratio(num, den):
    r = [a / b for a, b in zip(num, den) if b and b > 0]
    return float(np.mean(r)) if r else None


def _val_cargar(ticker):
    """Descarga cruda. NO usar directo: usar _val_cargar_seguro().
    Levanta ValueError con el motivo si faltan datos (así el fallo NO se cachea)."""
    import time
    import yfinance as yf
    s = yf.Ticker(ticker)

    info = {}
    for _ in range(3):                      # reintenta: Yahoo a veces devuelve {} por rate limit
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

    inc, bal, cf = _fin('financials'), _fin('balance_sheet'), _fin('cashflow')

    # ── Precio: info → fast_info → historial ──
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

    # ── Acciones: info → fast_info → mcap/precio → balance ──
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

    # ── Ventas: info → estados contables ──
    rev_l = _serie(inc, ['Total Revenue', 'Revenue'])
    rev0 = info.get('totalRevenue') or (rev_l[0] if rev_l else None)

    faltan = [n for n, v in [('precio', price), ('acciones en circulación', shares),
                             ('ventas', rev0)] if not v]
    if faltan:
        raise ValueError('Yahoo no devolvió: ' + ', '.join(faltan)
                         + (' (respuesta vacía, probable rate limit)' if not info else ''))

    ebitda_l = _serie(inc, ['EBITDA', 'Normalized EBITDA'])
    ebitda = info.get('ebitda') or (ebitda_l[0] if ebitda_l else None)

    # Estructura de capital
    debt_l = _serie(bal, ['Total Debt'])
    debt = info.get('totalDebt') if info.get('totalDebt') is not None else (debt_l[0] if debt_l else 0.0)
    cash_l = _serie(bal, ['Cash Cash Equivalents And Short Term Investments',
                          'Cash And Cash Equivalents', 'Cash'])
    cash = info.get('totalCash') if info.get('totalCash') is not None else (cash_l[0] if cash_l else 0.0)
    equity_l = _serie(bal, ['Stockholders Equity', 'Total Stockholders Equity', 'Common Stock Equity'])

    # Ratios operativos históricos
    da_l = _serie(cf, ['Depreciation And Amortization', 'Depreciation Amortization Depletion', 'Depreciation']) \
        or _serie(inc, ['Reconciled Depreciation'])
    capex_l = [abs(x) for x in _serie(cf, ['Capital Expenditure', 'Capital Expenditures', 'Purchase Of PPE'])]
    da_pct = _prom_ratio(da_l, rev_l[:len(da_l)] if rev_l else [])
    capex_pct = _prom_ratio(capex_l, rev_l[:len(capex_l)] if rev_l else [])

    # NWC operativo / ventas
    nwc_pct = None
    try:
        ca = _serie(bal, ['Current Assets', 'Total Current Assets'], 1)
        cl = _serie(bal, ['Current Liabilities', 'Total Current Liabilities'], 1)
        cdebt = _serie(bal, ['Current Debt', 'Current Debt And Capital Lease Obligation'], 1)
        if ca and cl and rev_l:
            nwc = ca[0] - (cash_l[0] if cash_l else 0.0) - (cl[0] - (cdebt[0] if cdebt else 0.0))
            nwc_pct = nwc / rev_l[0]
    except Exception:
        pass

    # Crecimiento histórico (CAGR de ventas)
    cagr = None
    if len(rev_l) >= 2 and rev_l[-1] > 0:
        cagr = (rev_l[0] / rev_l[-1]) ** (1 / (len(rev_l) - 1)) - 1
    if cagr is None:
        cagr = info.get('revenueGrowth')

    interest_l = [abs(x) for x in _serie(inc, ['Interest Expense', 'Interest Expense Non Operating'], 1)]

    # Múltiplos de mercado actuales (para defaults)
    per_info = info.get('trailingPE') or info.get('forwardPE')
    fcf_info = info.get('freeCashflow')
    pfcf_info = (mcap / fcf_info) if (mcap and fcf_info and fcf_info > 0) else None

    # Retorno al accionista (defaults)
    div_rate = info.get('dividendRate')
    if div_rate and price:
        div_y = div_rate / price
    else:
        div_y = info.get('trailingAnnualDividendYield') or 0.0
    div_y = float(min(max(div_y, 0.0), 0.20))

    bb_def = 0.0
    sh_l2 = _serie(inc, ['Basic Average Shares', 'Diluted Average Shares'], 2)
    if len(sh_l2) >= 2 and sh_l2[1] > 0:
        bb_def = float(min(max(-(sh_l2[0] / sh_l2[1] - 1), 0.0), 0.10))

    return dict(
        ticker=ticker, nombre=info.get('longName') or ticker,
        sector=info.get('sector'), pais=info.get('country'),
        moneda=info.get('currency'), moneda_fin=info.get('financialCurrency'),
        precio=float(price), acciones=float(shares), mcap=float(mcap or price * shares),
        rev0=float(rev0), ebitda=float(ebitda) if ebitda else None,
        margen_ebitda=(ebitda / rev0) if ebitda and rev0 else None,
        deuda=float(debt or 0.0), caja=float(cash or 0.0),
        patrimonio=equity_l[0] if equity_l else None,
        beta=info.get('beta'), mult_ev_ebitda=info.get('enterpriseToEbitda'),
        per_info=per_info, pfcf_info=pfcf_info,
        da_pct=da_pct, capex_pct=capex_pct, nwc_pct=nwc_pct, cagr=cagr,
        interes=interest_l[0] if interest_l else None,
        div_yield=div_y, buyback=bb_def,
    )


@st.cache_data(ttl=3600, show_spinner=False)
def _val_cargar_ok(ticker):
    # Si _val_cargar levanta excepción, Streamlit NO cachea el resultado.
    return _val_cargar(ticker)


def _val_cargar_seguro(ticker):
    """Devuelve (datos, error). Los errores no quedan cacheados."""
    try:
        return _val_cargar_ok(ticker), None
    except Exception as e:
        return None, str(e) or e.__class__.__name__


# ──────────────────────────────────────────────────────────────
#  2) MOTOR DE CÁLCULO
# ──────────────────────────────────────────────────────────────

def _proyectar(p):
    """Proyecta 5 años y devuelve FCFF, EBITDA, NOPAT, ventas y EBIT por año.
    El exceso de crecimiento sobre g terminal decae a la tasa p['decay'] cada año."""
    rev_prev = p['rev0']
    fcff, nopat_l, ebitda_l, rev_l, ebit_l = [], [], [], [], []
    for t in range(1, HORIZONTE_PROY + 1):
        gr = p['g'] + (p['growth0'] - p['g']) * (1 - p['decay']) ** (t - 1)
        rev = rev_prev * (1 + gr)
        ebitda = rev * p['margen']
        da = rev * p['da_pct']
        ebit = ebitda - da
        nopat = ebit * (1 - p['tax']) if ebit > 0 else ebit
        capex = rev * p['capex_pct']
        d_nwc = p['nwc_pct'] * (rev - rev_prev)
        fcff.append(nopat + da - capex - d_nwc)
        nopat_l.append(nopat); ebitda_l.append(ebitda); rev_l.append(rev); ebit_l.append(ebit)
        rev_prev = rev
    return dict(fcff=fcff, nopat=nopat_l, ebitda=ebitda_l, rev=rev_l, ebit=ebit_l)


def _dcf_por_accion(fcff, wacc, g, deuda, caja, acciones):
    if wacc <= g:
        return np.nan
    pv = sum(f / (1 + wacc) ** (i + 1) for i, f in enumerate(fcff))
    tv = fcff[-1] * (1 + g) / (wacc - g)                     # Gordon
    ev = pv + tv / (1 + wacc) ** HORIZONTE_PROY
    return (ev - deuda + caja) / acciones


def _valuar(p, w_dcf=0.5):
    """Valor por acción: DCF, múltiplos (promedio de los métodos elegidos) y combinado."""
    proy = _proyectar(p)
    v_dcf = _dcf_por_accion(proy['fcff'], p['wacc'], p['g'], p['deuda'], p['caja'], p['acciones'])

    ebitda1 = proy['ebitda'][0]
    interes = p['deuda'] * p['kd']
    ebt1 = proy['ebit'][0] - interes
    ni1 = ebt1 * (1 - p['tax']) if ebt1 > 0 else ebt1               # resultado neto año 1
    fcfe1 = proy['fcff'][0] - interes * (1 - p['tax'])              # flujo al accionista año 1

    vals = {}
    if 'ev_ebitda' in p['metodos']:
        vals['ev_ebitda'] = (ebitda1 * p['mult'] - p['deuda'] + p['caja']) / p['acciones']
    if 'per' in p['metodos']:
        vals['per'] = ni1 * p['per'] / p['acciones']
    if 'pfcf' in p['metodos']:
        vals['pfcf'] = fcfe1 * p['pfcf'] / p['acciones']
    # el patrimonio no puede valer menos que 0: se acota (mantiene monotonía para la ingeniería inversa)
    vals = {k: max(v, 0.0) for k, v in vals.items()}
    v_mult = float(np.mean(list(vals.values()))) if vals else np.nan

    comb = v_dcf * w_dcf + v_mult * (1 - w_dcf) if not (np.isnan(v_dcf) or np.isnan(v_mult)) else np.nan
    return dict(dcf=v_dcf, mult=v_mult, comb=comb, proy=proy, vals=vals)


def _params_escenario(base, nombre):
    e = ESCENARIOS_VAL[nombre]
    q = dict(base)
    q['growth0'] = base['growth0'] + e['d_growth']
    q['margen'] = max(0.01, base['margen'] + e['d_margin'])
    q['wacc'] = base['wacc'] + e['d_wacc']
    q['g'] = base['g'] + e['d_g']
    for k in ('mult', 'per', 'pfcf'):
        q[k] = base[k] * e['f_mult']
    return q


def _matriz_sensibilidad(base):
    proy = _proyectar(base)
    d_w = [-0.01, -0.005, 0.0, 0.005, 0.01]
    waccs = [base['wacc'] + d for d in d_w]
    gs = [base['g'] + d for d in d_w]
    M = []
    for w in waccs:
        fila = []
        for g in gs:
            fila.append(_dcf_por_accion(proy['fcff'], w, g, base['deuda'], base['caja'], base['acciones']))
        M.append(fila)
    return waccs, gs, M


def _bisec(f, lo, hi, target, it=70):
    flo, fhi = f(lo) - target, f(hi) - target
    if np.isnan(flo) or np.isnan(fhi) or flo * fhi > 0:
        return None
    for _ in range(it):
        mid = (lo + hi) / 2
        fm = f(mid) - target
        if np.isnan(fm):
            return None
        if flo * fm <= 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


def _ingenieria_inversa(base, w_dcf, target):
    """Resuelve qué supuestos hacen que el valor combinado = target."""
    def val(growth0=None, margen=None):
        q = dict(base)
        if growth0 is not None: q['growth0'] = growth0
        if margen is not None: q['margen'] = margen
        return _valuar(q, w_dcf)['comb']

    g_req = _bisec(lambda x: val(growth0=x), -0.30, 0.80, target)
    m_req = _bisec(lambda x: val(margen=x), 0.01, 0.85, target)

    # Solución conjunta: crecimiento y margen se mueven juntos (margen = 0.5 × shift de crecimiento)
    def joint(k):
        return val(growth0=base['growth0'] + k,
                   margen=min(0.85, max(0.01, base['margen'] + 0.5 * k)))
    k = _bisec(joint, -0.40, 0.60, target)
    conj = None
    if k is not None:
        gj = base['growth0'] + k
        mj = min(0.85, max(0.01, base['margen'] + 0.5 * k))
        q = dict(base); q['growth0'] = gj; q['margen'] = mj
        proy = _proyectar(q)
        cap_inv = (base['deuda'] + (base['patrimonio'] or 0.0) - base['caja'])
        roic = proy['nopat'][0] / cap_inv * 100 if cap_inv > 0 else None
        conj = dict(growth=gj, margen=mj, roic=roic)
    return dict(g_req=g_req, m_req=m_req, conj=conj)


def _retorno_accionista(base, div_y, bb, mcap, acciones, ke):
    """Salida de caja directa al accionista durante los 5 años proyectados.
    Dividendos y recompras escalan con las ventas proyectadas (mismo índice de crecimiento)."""
    proy = _proyectar(base)
    filas, pv_dps = [], 0.0
    for t in range(1, HORIZONTE_PROY + 1):
        idx = proy['rev'][t - 1] / base['rev0']
        div_cash = div_y * mcap * idx
        bb_cash = bb * mcap * idx
        acc_ini = acciones * (1 - bb) ** (t - 1)
        dps = div_cash / acc_ini
        pv_dps += dps / (1 + ke) ** t
        fcff = proy['fcff'][t - 1]
        filas.append({
            'Año': f'Año {t}', 'Dividendos': div_cash, 'Recompras': bb_cash,
            'Total distribuido': div_cash + bb_cash, 'FCFF': fcff,
            '% del FCFF': (div_cash + bb_cash) / fcff * 100 if fcff > 0 else np.nan,
            'Div. por acción': dps,
        })
    df = pd.DataFrame(filas)
    return df, pv_dps, 1 - (1 - bb) ** HORIZONTE_PROY


# ──────────────────────────────────────────────────────────────
#  3) JSON (formato para la interfaz web — no se muestra en pantalla)
# ──────────────────────────────────────────────────────────────

def _n(x, nd=2):
    try:
        if x is None or not np.isfinite(x):
            return None
        return round(float(x), nd)
    except Exception:
        return None


def _armar_json(ticker, precio, res, waccs, gs, M, target, conj):
    return {
        'ticker': ticker,
        'precio_mercado': _n(precio),
        'escenarios': {
            n: {
                'valor_dcf': _n(r['dcf']),
                'valor_multiplos': _n(r['mult']),
                'valor_combinado': _n(r['comb']),
                'upside_pct': _n(r['upside']),
            } for n, r in res.items()
        },
        'matriz_sensibilidad_wacc_g': {
            'filas_wacc': [_n(w * 100) for w in waccs],
            'columnas_g': [_n(g * 100) for g in gs],
            'valores_matriz': [[_n(v) for v in fila] for fila in M],
        },
        'ingenieria_inversa': {
            'precio_objetivo_analizado': _n(target),
            'supuestos_requeridos': {
                'rev_growth_anual_req': _n(conj['growth'] * 100) if conj else None,
                'margen_ebitda_req': _n(conj['margen'] * 100) if conj else None,
                'roica_estimado': _n(conj['roic']) if conj else None,
            },
        },
        'nota_disclaimer': DISCLAIMER_VAL,
    }


# ──────────────────────────────────────────────────────────────
#  4) GRÁFICOS
# ──────────────────────────────────────────────────────────────

def _fig_escenarios(res, precio, base_layout):
    nombres = list(res.keys())
    fig = go.Figure()
    for clave, etiqueta, color in [('dcf', 'DCF', '#3a7bd5'), ('mult', 'Múltiplos', '#bc8cff'),
                                   ('comb', 'Combinado', '#6CC24A')]:
        fig.add_trace(go.Bar(x=[n.capitalize() for n in nombres],
                             y=[res[n][clave] for n in nombres], name=etiqueta, marker_color=color,
                             text=[f'{res[n][clave]:.2f}' for n in nombres], textposition='outside'))
    fig.add_hline(y=precio, line_dash='dash', line_color='#e3b341',
                  annotation_text=f'Precio actual {precio:.2f}', annotation_position='top left')
    fig.update_layout(**base_layout, barmode='group', height=420,
                      title=dict(text='Valor por acción por escenario', font=dict(size=14, color='#e6edf3')),
                      yaxis=dict(gridcolor='#21262d'), xaxis=dict(gridcolor='#21262d'),
                      legend=dict(orientation='h', y=1.12), margin=dict(l=10, r=10, t=60, b=10))
    return fig


def _fig_heatmap(waccs, gs, M, precio, base_layout):
    z = np.array(M, dtype=float)
    fig = go.Figure(go.Heatmap(
        z=z, x=[f'{g*100:.1f}%' for g in gs], y=[f'{w*100:.1f}%' for w in waccs],
        colorscale='RdYlGn', zmid=precio,
        text=np.round(z, 2), texttemplate='%{text}',
        colorbar=dict(title='USD/acc.')))
    fig.update_layout(**base_layout, height=380,
                      title=dict(text='Valor DCF por acción — WACC (vertical) × g (horizontal)',
                                 font=dict(size=14, color='#e6edf3')),
                      xaxis=dict(title='g terminal'), yaxis=dict(title='WACC', autorange='reversed'),
                      margin=dict(l=10, r=10, t=55, b=10))
    return fig


def _fig_retorno(df, base_layout):
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df['Año'], y=df['Dividendos'] / 1e6, name='Dividendos', marker_color='#3a7bd5'))
    fig.add_trace(go.Bar(x=df['Año'], y=df['Recompras'] / 1e6, name='Recompras', marker_color='#bc8cff'))
    fig.add_trace(go.Scatter(x=df['Año'], y=df['FCFF'] / 1e6, name='FCFF', mode='lines+markers',
                             line=dict(color='#6CC24A', width=2.5)))
    fig.update_layout(**base_layout, barmode='stack', height=380,
                      title=dict(text='Caja distribuida al accionista vs. FCFF (millones)',
                                 font=dict(size=14, color='#e6edf3')),
                      yaxis=dict(gridcolor='#21262d'), xaxis=dict(gridcolor='#21262d'),
                      legend=dict(orientation='h', y=1.12), margin=dict(l=10, r=10, t=60, b=10))
    return fig


# ──────────────────────────────────────────────────────────────
#  5) UI
# ──────────────────────────────────────────────────────────────

def _pct_input(label, key, valor, minv=-50.0, maxv=100.0, step=0.5, help=None):
    minv, maxv, step = float(minv), float(maxv), float(step)
    v = float(round(valor * 100, 2))
    v = min(max(v, minv), maxv)          # evita que un valor por defecto quede fuera de rango
    return st.number_input(label, min_value=minv, max_value=maxv, value=v,
                           step=step, key=key, format='%.2f', help=help) / 100


def _sec(titulo):
    st.markdown(f'<div style="margin:14px 0 6px 0;font-size:11px;color:#6CC24A;font-weight:700;'
                f'letter-spacing:.6px;text-transform:uppercase">{titulo}</div>', unsafe_allow_html=True)


def modulo_valuacion(selector_ticker_autocomplete, kpi_cards_4, fmt_precio, PLOTLY_CONFIG,
                     validar_ticker=None):
    PLOTLY_BASE = dict(plot_bgcolor='#0d1117', paper_bgcolor='#07090f',
                       font=dict(color='#b0bcd0', family='Inter, sans-serif'), dragmode=False)

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #6CC24A; border-radius:14px;
         padding:28px 32px; margin-bottom:24px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">🏦 Simulador de Valuación de Empresas</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        DCF a 5 años (WACC por CAPM + riesgo país + valor terminal de Gordon), múltiplos EV/EBITDA, PER y P/FCF,
        valor combinado, matriz de sensibilidad WACC × g, ingeniería inversa y retorno al accionista.
        Todo parte de los datos fundamentales de Yahoo Finance y podés editar cada supuesto.
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

    # ── Advertencias de calidad del modelo ──
    if d['sector'] == 'Financial Services':
        st.warning('⚠️ Es una empresa financiera: el FCFF/DCF no aplica bien a bancos y aseguradoras '
                   '(la deuda es parte del negocio). Tomá el resultado con mucha cautela; es mejor P/B y ROE.')
    if d['moneda_fin'] and d['moneda'] and d['moneda_fin'] != d['moneda']:
        st.warning(f"⚠️ Moneda de los estados financieros ({d['moneda_fin']}) distinta a la de cotización "
                   f"({d['moneda']}). Típico en ADRs: el valor por acción queda mal escalado sin convertir.")
    if not d['ebitda'] or d['ebitda'] <= 0:
        st.warning('⚠️ EBITDA negativo o no disponible: el método de múltiplos pierde sentido y el DCF depende '
                   'enteramente del margen que asumas abajo.')

    st.markdown(f"**{d['nombre']}** ({ticker}) · {d['sector'] or 'N/D'} · {d['pais'] or 'N/D'} · "
                f"Precio: **{fmt_precio(d['precio'])}** · Ventas: {d['rev0']/1e9:,.2f}B · EBITDA: "
                f"{(d['ebitda'] or 0)/1e9:,.2f}B · Deuda: {d['deuda']/1e9:,.2f}B · Caja: {d['caja']/1e9:,.2f}B")

    # ── Supuestos editables ──
    k = ticker
    with st.expander('⚙️ Supuestos del modelo (editables)', expanded=True):

        _sec('🌎 Macro y riesgo')
        a1, a2, a3, a4 = st.columns(4)
        with a1:
            rf = _pct_input('Tasa libre de riesgo Rf %', f'val_rf_{k}', 0.042, 0, 20)
        with a2:
            rp = _pct_input('Riesgo país (EMBI) %', f'val_rp_{k}', 0.0, 0, 100, 0.5,
                            help='Para emergentes (Argentina, Brasil, México...). Se suma a Rf: '
                                 'Ke = Rf + Riesgo país + β × (Rm − Rf). Ej: 700 puntos básicos = 7%.')
        with a3:
            erp = _pct_input('Prima de riesgo (Rm − Rf) %', f'val_erp_{k}', 0.055, 0, 20)
        with a4:
            beta_def = float(min(max(d['beta'] if d['beta'] else 1.0, 0.0), 4.0))
            beta = st.number_input('Beta', 0.0, 4.0, round(beta_def, 2), 0.05, key=f'val_beta_{k}')

        _sec('🏗️ Estructura de capital y costo de deuda')
        s1, s2, s3, s4 = st.columns(4)
        with s1:
            tax = _pct_input('Tasa impositiva %', f'val_tax_{k}', 0.25, 0, 60)
        with s2:
            kd_def = (d['interes'] / d['deuda']) if d['interes'] and d['deuda'] > 0 else 0.055
            kd = _pct_input('Costo de deuda Kd (antes de imp.) %', f'val_kd_{k}',
                            min(max(kd_def, 0.02), 0.15), 0, 30)
        with s3:
            modo_pesos = st.selectbox('Ponderación D/V — E/V',
                                      ['Mercado (cap. bursátil)', 'Balance (patrimonio contable)', 'Manual'],
                                      key=f'val_modo_{k}')
        E_mkt, D = d['mcap'], d['deuda']
        dv_mkt = D / (D + E_mkt) if (D + E_mkt) > 0 else 0.0
        eq_book = d['patrimonio']
        dv_book = D / (D + eq_book) if (eq_book and eq_book > 0 and (D + eq_book) > 0) else None
        with s4:
            if modo_pesos.startswith('Manual'):
                dv = _pct_input('% Deuda / Valor (D/V)', f'val_dv_{k}', dv_mkt, 0, 95, 1.0)
            elif modo_pesos.startswith('Balance'):
                if dv_book is None:
                    st.caption('Sin patrimonio contable válido en Yahoo: se usa ponderación de mercado.')
                dv = dv_book if dv_book is not None else dv_mkt
                st.metric('D/V (balance)', f'{dv*100:.1f}%')
            else:
                dv = dv_mkt
                st.metric('D/V (mercado)', f'{dv*100:.1f}%')
        st.caption(f'Estructura aplicada: **D/V {dv*100:.1f}%** · **E/V {(1-dv)*100:.1f}%**')

        _sec('📈 Crecimiento y operación')
        b1, b2, b3, b4 = st.columns(4)
        g_hist = d['cagr'] if d['cagr'] is not None else 0.05
        with b1:
            growth0 = _pct_input('Crecimiento ventas año 1 %', f'val_gr_{k}', float(np.clip(g_hist, -0.05, 0.25)),
                                 -50, 100)
            decay = st.slider('Desaceleración anual del crecimiento %', 0, 100, 30, 5, key=f'val_decay_{k}',
                              help='Cada año, el exceso de crecimiento sobre el g terminal se reduce este %. '
                                   '0% = crecimiento plano (poco realista); 100% = cae al g terminal en el año 2.') / 100
        with b2:
            margen = _pct_input('Margen EBITDA %', f'val_mg_{k}',
                                float(np.clip(d['margen_ebitda'] if d['margen_ebitda'] else 0.15, 0.01, 0.85)), -50, 90)
            g_term = _pct_input('Crecimiento terminal g %', f'val_g_{k}', 0.025, -2, 6, 0.1)
        with b3:
            da_pct = _pct_input('D&A / ventas %', f'val_da_{k}', d['da_pct'] if d['da_pct'] is not None else 0.04, 0, 40)
            capex_pct = _pct_input('CAPEX / ventas %', f'val_cx_{k}',
                                   d['capex_pct'] if d['capex_pct'] is not None else 0.05, 0, 50)
        with b4:
            nwc_pct = _pct_input('NWC / ventas %', f'val_nwc_{k}',
                                 float(np.clip(d['nwc_pct'], -0.1, 0.4)) if d['nwc_pct'] is not None else 0.10,
                                 -20, 60, help='Cada $ de crecimiento de ventas inmoviliza este % en capital de trabajo.')
            wacc_man = _pct_input('WACC manual % (0 = calcular)', f'val_wm_{k}', 0.0, 0, 30)

        _sec('⚖️ Valoración relativa (múltiplos)')
        m0, m1, m2, m3 = st.columns([1.4, 1, 1, 1])
        with m0:
            metodos_lbl = st.multiselect('Múltiplos a usar (se promedian)', list(METODOS_MULT.keys()),
                                         default=list(METODOS_MULT.keys()), key=f'val_metodos_{k}')
            w_dcf = st.slider('Peso DCF en el valor combinado %', 0, 100, 50, 5, key=f'val_w_{k}') / 100
        mult_def = d['mult_ev_ebitda'] if d['mult_ev_ebitda'] and d['mult_ev_ebitda'] > 0 else 12.0
        mult_def = float(min(max(mult_def, 1.0), 80.0))
        per_def = float(min(max(d['per_info'] if d['per_info'] and d['per_info'] > 0 else 20.0, 3.0), 120.0))
        pfcf_def = float(min(max(d['pfcf_info'] if d['pfcf_info'] else 20.0, 3.0), 150.0))
        with m1:
            mult = st.number_input('EV/EBITDA objetivo (x)', 1.0, 80.0, round(mult_def, 1), 0.5, key=f'val_mult_{k}')
        with m2:
            per_obj = st.number_input('PER objetivo (x)', 3.0, 120.0, round(per_def, 1), 0.5, key=f'val_per_{k}')
        with m3:
            pfcf_obj = st.number_input('P/FCF objetivo (x)', 3.0, 150.0, round(pfcf_def, 1), 0.5, key=f'val_pfcf_{k}')

        _sec('💰 Retorno al accionista')
        r1, r2, r3 = st.columns(3)
        with r1:
            div_y = _pct_input('Dividend yield %', f'val_dy_{k}', d['div_yield'], 0, 20, 0.1)
        with r2:
            bb = _pct_input('Recompras (% de acciones por año)', f'val_bb_{k}', d['buyback'], 0, 30, 0.1,
                            help='Default: reducción de acciones del último año según Yahoo.')

    if not metodos_lbl:
        st.warning('Elegiste ningún múltiplo: se usa EV/EBITDA por defecto.')
        metodos_lbl = ['EV/EBITDA']
    metodos = [METODOS_MULT[m] for m in metodos_lbl]

    # ── WACC (CAPM + riesgo país) ──
    rf_aj = rf + rp
    ke = rf_aj + beta * erp
    kd_net = kd * (1 - tax)
    wacc_calc = (1 - dv) * ke + dv * kd_net
    wacc = wacc_man if wacc_man > 0 else wacc_calc

    if wacc - g_term < 0.01:
        st.error('WACC − g es menor a 1 punto: el valor terminal explota. Subí el WACC o bajá g.')
        return

    base = dict(rev0=d['rev0'], growth0=growth0, decay=decay, g=g_term, margen=margen, da_pct=da_pct,
                capex_pct=capex_pct, nwc_pct=nwc_pct, tax=tax, wacc=wacc, kd=kd,
                mult=mult, per=per_obj, pfcf=pfcf_obj, metodos=metodos,
                deuda=d['deuda'], caja=d['caja'], acciones=d['acciones'], patrimonio=d['patrimonio'])

    # ── Escenarios ──
    res = {n: _valuar(_params_escenario(base, n), w_dcf) for n in ESCENARIOS_VAL}
    for n in res:
        res[n]['upside'] = ((res[n]['comb'] / d['precio'] - 1) * 100
                            if not np.isnan(res[n]['comb']) else np.nan)

    rb = res['base']
    if rb['proy']['fcff'][-1] <= 0:
        st.warning('⚠️ El FCFF del año 5 es ≤ 0: el valor terminal es negativo/nulo. Revisá margen, CAPEX o NWC.')
    if any(v <= 0 for v in rb['vals'].values()):
        st.warning('⚠️ Algún múltiplo da valor 0 (resultado neto o flujo negativo en el año 1): '
                   'esa fila se acota en 0 y arrastra el promedio hacia abajo. Sacalo del selector si no aplica.')

    up = rb['upside']
    kpi_cards_4([
        ('Precio de mercado', fmt_precio(d['precio']), ticker, '#3a7bd5'),
        ('Valor estimado (base)', fmt_precio(rb['comb']) if not np.isnan(rb['comb']) else 'N/D',
         f'DCF {w_dcf*100:.0f}% / Múltiplos {(1-w_dcf)*100:.0f}%', '#6CC24A'),
        ('Upside / Downside', f'{up:+.1f}%' if not np.isnan(up) else 'N/D',
         'vs precio actual', '#3fb950' if (not np.isnan(up) and up > 0) else '#f85149'),
        ('WACC / Ke', f'{wacc*100:.2f}% / {ke*100:.2f}%',
         f'Rf+país {rf_aj*100:.2f}% · Kd neto {kd_net*100:.2f}%', '#e3b341'),
    ])

    tab_esc, tab_sens, tab_rev, tab_ret = st.tabs(
        ['📊 Escenarios', '🔥 Sensibilidad WACC × g', '🎯 Ingeniería inversa', '💰 Retorno al accionista'])

    with tab_esc:
        filas = [{'Escenario': n.capitalize(), 'Valor DCF': r['dcf'], 'Valor Múltiplos': r['mult'],
                  'Valor Combinado': r['comb'], 'Upside %': r['upside']} for n, r in res.items()]
        df_e = pd.DataFrame(filas)
        st.dataframe(df_e.style.format({'Valor DCF': '{:.2f}', 'Valor Múltiplos': '{:.2f}',
                                        'Valor Combinado': '{:.2f}', 'Upside %': '{:+.1f}%'}, na_rep='N/D'),
                     use_container_width=True, hide_index=True)
        st.plotly_chart(_fig_escenarios(res, d['precio'], PLOTLY_BASE), use_container_width=True,
                        config=PLOTLY_CONFIG, key='val_fig_esc')

        st.markdown('##### Detalle por método — por escenario')
        det = []
        for n, r in res.items():
            fila = {'Escenario': n.capitalize(), 'DCF': r['dcf']}
            for mk in ('ev_ebitda', 'per', 'pfcf'):
                fila[ETIQUETA_METODO[mk]] = r['vals'].get(mk, np.nan)
            det.append(fila)
        st.dataframe(pd.DataFrame(det).style.format({c: '{:.2f}' for c in ['DCF', 'EV/EBITDA', 'PER', 'P/FCF']},
                                                    na_rep='—'),
                     use_container_width=True, hide_index=True)

        pr = rb['proy']
        df_p = pd.DataFrame({
            'Año': [f'Año {i}' for i in range(1, 6)],
            'Ventas': pr['rev'], 'EBITDA': pr['ebitda'], 'NOPAT': pr['nopat'], 'FCFF': pr['fcff'],
        }).set_index('Año')
        st.markdown('##### Proyección — escenario base (en millones)')
        st.dataframe((df_p / 1e6).style.format('{:,.1f}'), use_container_width=True)
        gr_path = [(pr['rev'][0] / d['rev0'] - 1) * 100] + \
                  [(pr['rev'][i] / pr['rev'][i - 1] - 1) * 100 for i in range(1, 5)]
        st.caption('Crecimiento de ventas proyectado: ' + ' → '.join(f'{x:.1f}%' for x in gr_path) +
                   f' · g terminal {g_term*100:.1f}%.')
        st.caption('Escenarios: conservador = crecimiento −3pp, margen −2pp, WACC +0.5pp, g −0.5pp, múltiplos ×0.85 · '
                   'expansivo = lo inverso (múltiplos ×1.15). PER usa resultado neto del año 1 (EBIT − intereses, '
                   'después de impuestos); P/FCF usa FCFF año 1 − intereses después de impuestos.')

    with tab_sens:
        waccs, gs, M = _matriz_sensibilidad(base)
        st.plotly_chart(_fig_heatmap(waccs, gs, M, d['precio'], PLOTLY_BASE), use_container_width=True,
                        config=PLOTLY_CONFIG, key='val_fig_heat')
        df_m = pd.DataFrame(M, index=[f'{w*100:.1f}%' for w in waccs], columns=[f'{g*100:.1f}%' for g in gs])
        st.dataframe(df_m.style.format('{:.2f}', na_rep='N/D'), use_container_width=True)
        celdas_sobre = int((np.array(M, dtype=float) > d['precio']).sum())
        st.caption(f'En {celdas_sobre} de 25 combinaciones el DCF supera el precio actual. '
                   'Verde = por encima del precio de mercado, rojo = por debajo.')

    target = float(round(d['precio'] * 1.3, 2))
    conj_sel = None
    with tab_rev:
        st.markdown('##### ¿Qué tiene que pasar para valer $X?')
        target = st.number_input('Precio objetivo ($X por acción)', min_value=0.01,
                                 value=float(round(d['precio'] * 1.3, 2)), step=1.0, key=f'val_target_{k}')
        ir = _ingenieria_inversa(base, w_dcf, target)
        conj_sel = ir['conj']

        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric('Crecimiento año 1 requerido (margen fijo)',
                      f"{ir['g_req']*100:.1f}%" if ir['g_req'] is not None else 'Sin solución',
                      f"vs {growth0*100:.1f}% base" if ir['g_req'] is not None else None)
        with c2:
            st.metric('Margen EBITDA requerido (crecimiento fijo)',
                      f"{ir['m_req']*100:.1f}%" if ir['m_req'] is not None else 'Sin solución',
                      f"vs {margen*100:.1f}% base" if ir['m_req'] is not None else None)
        with c3:
            if ir['conj']:
                st.metric('Combinación conjunta', f"{ir['conj']['growth']*100:.1f}% / {ir['conj']['margen']*100:.1f}%",
                          'crecimiento / margen')
            else:
                st.metric('Combinación conjunta', 'Sin solución')
        if ir['conj'] and ir['conj']['roic'] is not None:
            st.caption(f"ROIC estimado con la combinación conjunta (NOPAT año 1 / capital invertido): "
                       f"{ir['conj']['roic']:.1f}%.")
        st.caption('La ecuación tiene dos incógnitas, así que se resuelve de tres formas: moviendo solo el crecimiento, '
                   'solo el margen, o ambos juntos (el margen se mueve la mitad que el crecimiento). '
                   '"Sin solución" = ni siquiera con valores extremos se llega a ese precio.')
        if ir['g_req'] is not None and ir['g_req'] > 0.40:
            st.warning('Un crecimiento tan alto durante años es poco realista: el precio objetivo exige mucho.')

    with tab_ret:
        st.markdown('##### Salida de caja directa al accionista (5 años)')
        if div_y == 0 and bb == 0:
            st.info('Dividend yield y recompras están en 0%. Cargalos arriba para modelar la distribución de caja.')
        else:
            df_r, pv_dps, red_acc = _retorno_accionista(base, div_y, bb, d['mcap'], d['acciones'], ke)
            shy = div_y + bb
            k1, k2, k3, k4 = st.columns(4)
            with k1: st.metric('Shareholder yield', f'{shy*100:.2f}%', f'Div {div_y*100:.2f}% + Recompras {bb*100:.2f}%')
            with k2: st.metric('Dividendos acumulados / acción', fmt_precio(df_r['Div. por acción'].sum()),
                               f'VP al Ke: {fmt_precio(pv_dps)}')
            with k3: st.metric('Reducción de acciones (5 años)', f'{red_acc*100:.1f}%')
            with k4:
                prom = df_r['% del FCFF'].mean()
                st.metric('% del FCFF distribuido (prom.)', f'{prom:.0f}%' if not np.isnan(prom) else 'N/D')
            if (df_r['% del FCFF'] > 100).any():
                st.warning('⚠️ En algún año la distribución supera el 100% del FCFF: no sería sostenible sin '
                           'endeudarse o usar caja acumulada.')
            st.plotly_chart(_fig_retorno(df_r, PLOTLY_BASE), use_container_width=True,
                            config=PLOTLY_CONFIG, key='val_fig_ret')
            df_show = df_r.set_index('Año').copy()
            for c in ['Dividendos', 'Recompras', 'Total distribuido', 'FCFF']:
                df_show[c] = df_show[c] / 1e6
            st.dataframe(df_show.style.format({'Dividendos': '{:,.1f}', 'Recompras': '{:,.1f}',
                                               'Total distribuido': '{:,.1f}', 'FCFF': '{:,.1f}',
                                               '% del FCFF': '{:.0f}%', 'Div. por acción': '{:.3f}'}, na_rep='N/D'),
                         use_container_width=True)
            st.caption('Importes en millones. Dividendos y recompras escalan con las ventas proyectadas. '
                       'No se suman al valor del DCF a propósito: el FCFF ya es la caja que la empresa puede '
                       'repartir, así que sumarlos contaría el mismo flujo dos veces. Este panel muestra '
                       'cuánto de ese flujo sale al accionista y si es sostenible.')

    # ── JSON para la interfaz web: NO se muestra, solo se descarga ──
    waccs, gs, M = _matriz_sensibilidad(base)
    salida = _armar_json(ticker, d['precio'], res, waccs, gs, M, target, conj_sel)
    st.markdown('---')
    cj1, cj2 = st.columns([3, 1])
    with cj1:
        st.caption('⚠️ ' + DISCLAIMER_VAL)
    with cj2:
        st.download_button('⬇️ Descargar JSON', json.dumps(salida, ensure_ascii=False, indent=2),
                           file_name=f'valuacion_{ticker}.json', mime='application/json',
                           use_container_width=True, key='val_dl_json')
