# ==============================================================
#  MÓDULO — ACCIONISTAS PRINCIPALES + ESTADOS FINANCIEROS
#  (Balance · Estado de Resultados · Flujo de Fondos — Anual/Trimestral)
#  Diseñado para integrarse al Analizador Cuantitativo Unificado.
# ==============================================================

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

# ── Paleta (idéntica a la del script principal) ────────────────────────
C_ACENT   = '#3a7bd5'
C_MONSTER = '#6CC24A'
C_TEXT    = '#e6edf3'
C_MUTED   = '#6b7d9a'
C_GREEN   = '#3fb950'
C_RED     = '#f85149'
C_YELL    = '#e3b341'
C_GRID    = '#21262d'
C_BG1     = '#0d1117'
C_BG2     = '#07090f'

PLOTLY_LAYOUT_BASE = dict(
    plot_bgcolor=C_BG1, paper_bgcolor=C_BG2,
    font=dict(color='#b0bcd0', family='Inter, sans-serif'),
    dragmode=False,
)
PLOTLY_CONFIG = dict(displayModeBar=False, scrollZoom=False)


def _fmt_big(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return 'N/D'
    av = abs(v)
    if av >= 1e12: return f'{v/1e12:.2f}T'
    if av >= 1e9:  return f'{v/1e9:.2f}B'
    if av >= 1e6:  return f'{v/1e6:.2f}M'
    if av >= 1e3:  return f'{v/1e3:.2f}K'
    return f'{v:.2f}'


def _pct(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return 'N/D'
    return f'{v*100:.2f}%' if abs(v) <= 5 else f'{v:.2f}%'


def _es_activo_sin_estados(ticker):
    t = ticker.upper()
    return t.endswith('=X') or t.endswith('-USD') or t.endswith('=F')


# ==============================================================
#  ACCIONISTAS PRINCIPALES
# ==============================================================

@st.cache_data(ttl=86400, show_spinner=False)
def obtener_accionistas(ticker):
    """Devuelve dict con: resumen (major_holders), institucionales,
    fondos mutuos e info agregada (%institucional, %insiders, float, acciones totales).
    None si el ticker no tiene datos de accionistas (ETFs simples, forex, cripto, etc.)."""
    if _es_activo_sin_estados(ticker):
        return None
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)

        resumen = None
        try:
            resumen = stock.major_holders
        except Exception:
            pass

        institucionales = None
        try:
            institucionales = stock.institutional_holders
        except Exception:
            pass

        fondos = None
        try:
            fondos = stock.mutualfund_holders
        except Exception:
            pass

        info_extra = {}
        try:
            info = stock.info or {}
            info_extra = {
                'pct_institucional': info.get('heldPercentInstitutions'),
                'pct_insiders': info.get('heldPercentInsiders'),
                'acciones_flotantes': info.get('floatShares'),
                'acciones_totales': info.get('sharesOutstanding'),
            }
        except Exception:
            pass

        vacio_res = resumen is None or (hasattr(resumen, 'empty') and resumen.empty)
        vacio_ins = institucionales is None or (hasattr(institucionales, 'empty') and institucionales.empty)
        vacio_fon = fondos is None or (hasattr(fondos, 'empty') and fondos.empty)
        if vacio_res and vacio_ins and vacio_fon and not info_extra.get('pct_institucional'):
            return None

        return {
            'resumen': resumen, 'institucionales': institucionales,
            'fondos': fondos, 'info': info_extra,
        }
    except Exception:
        return None


def _tabla_holders(df, tipo='institucional'):
    """Normaliza nombres de columnas variables de yfinance a español."""
    if df is None or (hasattr(df, 'empty') and df.empty):
        return None
    d = df.copy()
    col_map = {}
    for c in d.columns:
        lc = str(c).lower()
        if 'holder' in lc:                     col_map[c] = 'Fondo' if tipo == 'fondo' else 'Institución'
        elif 'shares' in lc:                    col_map[c] = 'Acciones'
        elif 'date' in lc:                      col_map[c] = 'Fecha reportada'
        elif 'out' in lc or lc.strip() == '%':  col_map[c] = '% en circulación'
        elif 'value' in lc:                     col_map[c] = 'Valor (USD)'
    d = d.rename(columns=col_map)
    if 'Acciones' in d.columns:
        d['Acciones'] = d['Acciones'].apply(lambda v: _fmt_big(v) if pd.notna(v) else 'N/D')
    if 'Valor (USD)' in d.columns:
        d['Valor (USD)'] = d['Valor (USD)'].apply(lambda v: _fmt_big(v) if pd.notna(v) else 'N/D')
    if '% en circulación' in d.columns:
        d['% en circulación'] = d['% en circulación'].apply(
            lambda v: (f'{v*100:.2f}%' if pd.notna(v) and abs(v) <= 5 else (f'{v:.2f}%' if pd.notna(v) else 'N/D'))
        )
    return d


def render_accionistas(ticker, key_suffix=''):
    """Card de estructura de propiedad + tablas de institucionales y fondos."""
    if _es_activo_sin_estados(ticker):
        return
    with st.spinner('Cargando accionistas principales...'):
        datos = obtener_accionistas(ticker)

    if datos is None:
        st.info(f'ℹ️ No hay datos de accionistas disponibles para {ticker} '
                '(frecuente en ETFs simples, ADRs de algunos países, forex, cripto o commodities).')
        return

    info = datos.get('info', {}) or {}
    pct_inst = info.get('pct_institucional')
    pct_ins  = info.get('pct_insiders')
    acc_tot  = info.get('acciones_totales')
    acc_flot = info.get('acciones_flotantes')

    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric('% Institucional', _pct(pct_inst))
    with c2: st.metric('% Insiders', _pct(pct_ins))
    with c3: st.metric('Acciones en circulación', _fmt_big(acc_tot))
    with c4: st.metric('Free Float', _fmt_big(acc_flot))

    if pct_inst is not None or pct_ins is not None:
        p_inst = (pct_inst or 0) * 100
        p_ins  = (pct_ins or 0) * 100
        p_pub  = max(0.0, 100 - p_inst - p_ins)
        fig = go.Figure(data=[go.Pie(
            labels=['Institucional', 'Insiders', 'Público / Otros'],
            values=[p_inst, p_ins, p_pub],
            marker=dict(colors=[C_ACENT, C_YELL, C_MUTED]),
            hole=0.55, textinfo='label+percent',
        )])
        fig.update_layout(
            **PLOTLY_LAYOUT_BASE, height=340, showlegend=False,
            title=dict(text='Estructura de propiedad', font=dict(color=C_TEXT, size=13)),
            margin=dict(l=10, r=10, t=45, b=10),
        )
        st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG,
                         key=f'acc_pie_{ticker}_{key_suffix}')

    df_inst = _tabla_holders(datos.get('institucionales'), tipo='institucional')
    if df_inst is not None:
        st.markdown('#### 🏦 Principales tenedores institucionales')
        st.dataframe(df_inst, use_container_width=True, hide_index=True)

    df_fondos = _tabla_holders(datos.get('fondos'), tipo='fondo')
    if df_fondos is not None:
        st.markdown('#### 💼 Principales fondos mutuos')
        st.dataframe(df_fondos, use_container_width=True, hide_index=True)

    lecturas = []
    if pct_inst is not None:
        if pct_inst > 0.70:
            lecturas.append('Participación institucional muy alta (>70%): fuerte respaldo de inversores '
                             'profesionales, pero también más sensibilidad a flujos de entrada/salida grandes.')
        elif pct_inst > 0.40:
            lecturas.append('Participación institucional moderada: mezcla equilibrada entre inversores '
                             'profesionales y público general.')
        else:
            lecturas.append('Participación institucional baja: la acción está mayormente en manos de '
                             'inversores individuales o del management.')
    if pct_ins is not None:
        if pct_ins > 0.20:
            lecturas.append('Los insiders (directivos/fundadores) mantienen una porción significativa '
                             '(>20%): sus intereses suelen estar alineados con los del resto de los accionistas.')
        elif pct_ins < 0.02:
            lecturas.append('Insiders con participación muy baja (<2%): conviene monitorear el '
                             'alineamiento de incentivos con los accionistas minoritarios.')
    if lecturas:
        st.markdown(f"""
        <div class="interp-card">
          <div class="interp-header">📋 Lectura de la estructura de propiedad</div>
          {' '.join(lecturas)}
        </div>
        """, unsafe_allow_html=True)


# ==============================================================
#  ESTADOS FINANCIEROS — Balance / Resultados / Flujo de Fondos
# ==============================================================

@st.cache_data(ttl=3600, show_spinner=False)
def obtener_estados_financieros(ticker):
    """Descarga balance, estado de resultados y flujo de fondos, anual y trimestral."""
    if _es_activo_sin_estados(ticker):
        return None
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        data = {}
        for clave, attr in [
            ('balance_anual', 'balance_sheet'), ('balance_trim', 'quarterly_balance_sheet'),
            ('resultados_anual', 'financials'),  ('resultados_trim', 'quarterly_financials'),
            ('flujo_anual', 'cashflow'),         ('flujo_trim', 'quarterly_cashflow'),
        ]:
            try:
                data[clave] = getattr(stock, attr)
            except Exception:
                data[clave] = pd.DataFrame()

        if all(df is None or df.empty for df in data.values()):
            return None
        return data
    except Exception:
        return None


def _buscar_fila(df, nombres):
    """Busca una fila por nombre exacto o por coincidencia parcial (case-insensitive)."""
    if df is None or df.empty:
        return None
    for n in nombres:
        if n in df.index:
            return df.loc[n]
    for idx in df.index:
        for n in nombres:
            if n.lower() in str(idx).lower():
                return df.loc[idx]
    return None


def _cols_cronologico(fila):
    """yfinance entrega columnas de más reciente a más antigua; las invertimos."""
    return list(fila.index)[::-1]


def _tabla_estado(df, max_periodos=6):
    if df is None or df.empty:
        return None
    d = df.copy()
    d = d[d.columns[:max_periodos]]
    d.columns = [c.strftime('%Y-%m-%d') if hasattr(c, 'strftime') else str(c) for c in d.columns]
    return d.applymap(lambda v: _fmt_big(v) if pd.notna(v) else '-')


def fig_resultados(df_res):
    ventas  = _buscar_fila(df_res, ['Total Revenue', 'Revenue'])
    neto    = _buscar_fila(df_res, ['Net Income', 'Net Income Common Stockholders'])
    if ventas is None:
        return None
    cols = _cols_cronologico(ventas)
    labels = [str(c)[:10] for c in cols]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=[ventas.get(c) for c in cols], name='Ingresos', marker_color=C_ACENT))
    if neto is not None:
        fig.add_trace(go.Bar(x=labels, y=[neto.get(c) for c in cols], name='Ganancia Neta', marker_color=C_MONSTER))
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE, barmode='group', height=380,
        title=dict(text='Ingresos vs. Ganancia Neta', font=dict(color=C_TEXT, size=13)),
        xaxis=dict(gridcolor=C_GRID), yaxis=dict(gridcolor=C_GRID),
        margin=dict(l=10, r=10, t=45, b=10), legend=dict(orientation='h', y=1.12),
    )
    return fig


def fig_margenes(df_res):
    ventas    = _buscar_fila(df_res, ['Total Revenue', 'Revenue'])
    bruto     = _buscar_fila(df_res, ['Gross Profit'])
    operativo = _buscar_fila(df_res, ['Operating Income', 'Total Operating Income As Reported'])
    neto      = _buscar_fila(df_res, ['Net Income', 'Net Income Common Stockholders'])
    if ventas is None:
        return None
    cols = _cols_cronologico(ventas)
    labels = [str(c)[:10] for c in cols]

    def _margen(fila):
        if fila is None:
            return [None] * len(cols)
        out = []
        for c in cols:
            v, base = fila.get(c), ventas.get(c)
            out.append(v / base * 100 if (base not in (None, 0) and pd.notna(v)) else None)
        return out

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=labels, y=_margen(bruto),     name='Mg. Bruto %',     line=dict(color=C_ACENT, width=2)))
    fig.add_trace(go.Scatter(x=labels, y=_margen(operativo), name='Mg. Operativo %', line=dict(color=C_YELL, width=2)))
    fig.add_trace(go.Scatter(x=labels, y=_margen(neto),      name='Mg. Neto %',      line=dict(color=C_MONSTER, width=2)))
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE, height=380,
        title=dict(text='Evolución de márgenes', font=dict(color=C_TEXT, size=13)),
        xaxis=dict(gridcolor=C_GRID), yaxis=dict(gridcolor=C_GRID, title='%'),
        margin=dict(l=10, r=10, t=45, b=10), legend=dict(orientation='h', y=1.12),
    )
    return fig


def fig_balance(df_bal):
    activos = _buscar_fila(df_bal, ['Total Assets'])
    pasivos = _buscar_fila(df_bal, ['Total Liabilities Net Minority Interest', 'Total Liab'])
    equity  = _buscar_fila(df_bal, ['Stockholders Equity', 'Total Stockholders Equity', 'Common Stock Equity'])
    if activos is None:
        return None
    cols = _cols_cronologico(activos)
    labels = [str(c)[:10] for c in cols]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=[activos.get(c) for c in cols], name='Activos Totales', marker_color=C_ACENT))
    if pasivos is not None:
        fig.add_trace(go.Bar(x=labels, y=[pasivos.get(c) for c in cols], name='Pasivos Totales', marker_color=C_RED))
    if equity is not None:
        fig.add_trace(go.Bar(x=labels, y=[equity.get(c) for c in cols], name='Patrimonio Neto', marker_color=C_MONSTER))
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE, barmode='group', height=380,
        title=dict(text='Composición del Balance', font=dict(color=C_TEXT, size=13)),
        xaxis=dict(gridcolor=C_GRID), yaxis=dict(gridcolor=C_GRID),
        margin=dict(l=10, r=10, t=45, b=10), legend=dict(orientation='h', y=1.12),
    )
    return fig


def fig_flujo(df_cf):
    cfo = _buscar_fila(df_cf, ['Operating Cash Flow', 'Total Cash From Operating Activities'])
    cfi = _buscar_fila(df_cf, ['Investing Cash Flow', 'Total Cashflows From Investing Activities'])
    cff = _buscar_fila(df_cf, ['Financing Cash Flow', 'Total Cash From Financing Activities'])
    fcf = _buscar_fila(df_cf, ['Free Cash Flow'])
    if cfo is None:
        return None
    cols = _cols_cronologico(cfo)
    labels = [str(c)[:10] for c in cols]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=[cfo.get(c) for c in cols], name='Flujo Operativo', marker_color=C_MONSTER))
    if cfi is not None:
        fig.add_trace(go.Bar(x=labels, y=[cfi.get(c) for c in cols], name='Flujo Inversión', marker_color=C_YELL))
    if cff is not None:
        fig.add_trace(go.Bar(x=labels, y=[cff.get(c) for c in cols], name='Flujo Financiación', marker_color=C_ACENT))
    if fcf is not None:
        fig.add_trace(go.Scatter(x=labels, y=[fcf.get(c) for c in cols], name='Free Cash Flow',
                                  line=dict(color=C_RED, width=2.4)))
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE, barmode='group', height=380,
        title=dict(text='Flujo de Fondos', font=dict(color=C_TEXT, size=13)),
        xaxis=dict(gridcolor=C_GRID), yaxis=dict(gridcolor=C_GRID),
        margin=dict(l=10, r=10, t=45, b=10), legend=dict(orientation='h', y=1.12),
    )
    return fig


def _variacion_pct(fila):
    """% de variación entre el primer y el último valor no nulo de una fila cronológica."""
    if fila is None:
        return None
    cols = _cols_cronologico(fila)
    vals = [fila.get(c) for c in cols if pd.notna(fila.get(c))]
    if len(vals) < 2 or vals[0] == 0:
        return None
    return (vals[-1] - vals[0]) / abs(vals[0]) * 100


def _serie_valores(fila):
    """Lista cronológica (más antiguo → más reciente) de valores no nulos."""
    if fila is None:
        return []
    cols = _cols_cronologico(fila)
    return [fila.get(c) for c in cols if pd.notna(fila.get(c))]


def _cagr(vals, periodos_por_año=1.0):
    """Tasa de crecimiento anual compuesta entre el primer y el último valor de la serie."""
    if len(vals) < 2 or vals[0] is None or vals[0] <= 0 or vals[-1] is None:
        return None
    n_años = (len(vals) - 1) / periodos_por_año
    if n_años <= 0:
        return None
    try:
        base = vals[-1] / vals[0]
        if base <= 0:
            return None
        return (base ** (1 / n_años) - 1) * 100
    except Exception:
        return None


def _tendencia_serie(vals, umbral=0.03):
    """Compara el promedio de la primera mitad vs la segunda mitad de la serie.
    Devuelve 'expansion', 'contraccion' o 'estable'."""
    if len(vals) < 3:
        return None
    mitad = len(vals) // 2
    prom1 = np.mean(vals[:mitad]) if mitad > 0 else None
    prom2 = np.mean(vals[mitad:])
    if prom1 in (None, 0) or prom2 is None:
        return None
    var = (prom2 - prom1) / abs(prom1)
    if var > umbral:
        return 'expansion'
    elif var < -umbral:
        return 'contraccion'
    return 'estable'


def interpretar_estados_detallado(df_res, df_bal, df_cf, es_trimestral=False):
    """Análisis detallado por categoría (Crecimiento, Rentabilidad, Solvencia,
    Liquidez, Calidad de Caja). Devuelve lista de dicts:
    {'categoria': str, 'texto': str, 'tipo': 'OK'|'ALERTA'|'INFO'}"""
    señales = []
    periodos_año = 4.0 if es_trimestral else 1.0

    # ── CRECIMIENTO ──────────────────────────────────────────────────
    ventas = _buscar_fila(df_res, ['Total Revenue', 'Revenue'])
    neto   = _buscar_fila(df_res, ['Net Income', 'Net Income Common Stockholders'])
    ebitda = _buscar_fila(df_res, ['EBITDA', 'Normalized EBITDA'])

    v_ventas = _serie_valores(ventas)
    if len(v_ventas) >= 2:
        cagr_v = _cagr(v_ventas, periodos_año)
        ult_var = (v_ventas[-1] - v_ventas[-2]) / abs(v_ventas[-2]) * 100 if len(v_ventas) >= 2 and v_ventas[-2] != 0 else None
        etiqueta_periodo = 'trimestre' if es_trimestral else 'año'
        if cagr_v is not None:
            if cagr_v > 15:
                señales.append({'categoria': '📈 Crecimiento', 'tipo': 'OK',
                    'texto': f'Ingresos con crecimiento anualizado fuerte de {cagr_v:.1f}% (CAGR) '
                              f'a lo largo del historial disponible.'})
            elif cagr_v > 0:
                señales.append({'categoria': '📈 Crecimiento', 'tipo': 'OK',
                    'texto': f'Ingresos creciendo a un ritmo moderado de {cagr_v:.1f}% anualizado (CAGR).'})
            else:
                señales.append({'categoria': '📈 Crecimiento', 'tipo': 'ALERTA',
                    'texto': f'Ingresos con caída anualizada de {abs(cagr_v):.1f}% (CAGR): negocio en contracción '
                              'en el período analizado.'})
        if ult_var is not None:
            if ult_var > 0:
                señales.append({'categoria': '📈 Crecimiento', 'tipo': 'OK',
                    'texto': f'Último {etiqueta_periodo} informado con ingresos {ult_var:+.1f}% vs. el anterior.'})
            else:
                señales.append({'categoria': '📈 Crecimiento', 'tipo': 'ALERTA',
                    'texto': f'Último {etiqueta_periodo} informado con ingresos {ult_var:+.1f}% vs. el anterior: '
                              'desaceleración o retroceso reciente.'})

    v_neto = _serie_valores(neto)
    if len(v_ventas) >= 2 and len(v_neto) >= 2:
        cagr_n = _cagr(v_neto, periodos_año)
        if cagr_v is not None and cagr_n is not None:
            if cagr_n > cagr_v + 3:
                señales.append({'categoria': '📈 Crecimiento', 'tipo': 'OK',
                    'texto': f'La ganancia neta crece más rápido que los ingresos ({cagr_n:.1f}% vs. '
                              f'{cagr_v:.1f}% anualizado): apalancamiento operativo positivo, la empresa gana '
                              'eficiencia a medida que crece.'})
            elif cagr_n < cagr_v - 3:
                señales.append({'categoria': '📈 Crecimiento', 'tipo': 'ALERTA',
                    'texto': f'La ganancia neta crece más lento que los ingresos ({cagr_n:.1f}% vs. '
                              f'{cagr_v:.1f}% anualizado): la rentabilidad se está diluyendo pese a la expansión '
                              'del negocio (más costos, más competencia o mayor carga financiera).'})

    # ── RENTABILIDAD Y MÁRGENES ──────────────────────────────────────
    bruto     = _buscar_fila(df_res, ['Gross Profit'])
    operativo = _buscar_fila(df_res, ['Operating Income', 'Total Operating Income As Reported'])

    def _margen_serie(fila_num, fila_den):
        vn, vd = _serie_valores(fila_num), _serie_valores(fila_den)
        n = min(len(vn), len(vd))
        if n == 0: return []
        return [vn[-n+i] / vd[-n+i] * 100 for i in range(n) if vd[-n+i] not in (0, None)]

    for nombre_m, fila_m in [('Margen Bruto', bruto), ('Margen Operativo', operativo), ('Margen Neto', neto)]:
        serie_m = _margen_serie(fila_m, ventas)
        if len(serie_m) >= 3:
            tend = _tendencia_serie(serie_m)
            ultimo_m = serie_m[-1]
            if tend == 'expansion':
                señales.append({'categoria': '💰 Rentabilidad', 'tipo': 'OK',
                    'texto': f'{nombre_m} en expansión: pasó de un promedio de {np.mean(serie_m[:len(serie_m)//2]):.1f}% '
                              f'a {np.mean(serie_m[len(serie_m)//2:]):.1f}% — mejora de eficiencia sostenida.'})
            elif tend == 'contraccion':
                señales.append({'categoria': '💰 Rentabilidad', 'tipo': 'ALERTA',
                    'texto': f'{nombre_m} en contracción: pasó de un promedio de {np.mean(serie_m[:len(serie_m)//2]):.1f}% '
                              f'a {np.mean(serie_m[len(serie_m)//2:]):.1f}% — presión sobre costos o precios.'})
            else:
                señales.append({'categoria': '💰 Rentabilidad', 'tipo': 'INFO',
                    'texto': f'{nombre_m} estable, en torno al {ultimo_m:.1f}% en el último período.'})

    # ── SOLVENCIA ─────────────────────────────────────────────────────
    deuda  = _buscar_fila(df_bal, ['Total Debt'])
    equity = _buscar_fila(df_bal, ['Stockholders Equity', 'Total Stockholders Equity', 'Common Stock Equity'])
    v_deuda, v_equity = _serie_valores(deuda), _serie_valores(equity)
    if v_deuda and v_equity:
        de_actual = v_deuda[-1] / v_equity[-1] if v_equity[-1] not in (0, None) else None
        de_inicial = v_deuda[0] / v_equity[0] if v_equity[0] not in (0, None) and len(v_deuda) > 1 else None
        if de_actual is not None:
            if de_actual > 2:
                señales.append({'categoria': '🔒 Solvencia', 'tipo': 'ALERTA',
                    'texto': f'Deuda/Patrimonio (D/E) actual de {de_actual:.2f}x: apalancamiento elevado, '
                              'mayor sensibilidad a subas de tasas o caídas de resultados.'})
            elif de_actual < 0.5:
                señales.append({'categoria': '🔒 Solvencia', 'tipo': 'OK',
                    'texto': f'Deuda/Patrimonio (D/E) actual de {de_actual:.2f}x: balance conservador, '
                              'bajo apalancamiento financiero.'})
            else:
                señales.append({'categoria': '🔒 Solvencia', 'tipo': 'INFO',
                    'texto': f'Deuda/Patrimonio (D/E) actual de {de_actual:.2f}x: nivel de deuda moderado.'})
        if de_actual is not None and de_inicial is not None:
            if de_actual > de_inicial * 1.3:
                señales.append({'categoria': '🔒 Solvencia', 'tipo': 'ALERTA',
                    'texto': f'El apalancamiento aumentó respecto al inicio del historial ({de_inicial:.2f}x → '
                              f'{de_actual:.2f}x): la empresa se está financiando más con deuda.'})
            elif de_actual < de_inicial * 0.7:
                señales.append({'categoria': '🔒 Solvencia', 'tipo': 'OK',
                    'texto': f'El apalancamiento se redujo respecto al inicio del historial ({de_inicial:.2f}x → '
                              f'{de_actual:.2f}x): la empresa se desapalancó, típicamente una señal saludable.'})

    ebit = _buscar_fila(df_res, ['EBIT', 'Operating Income'])
    interes = _buscar_fila(df_res, ['Interest Expense'])
    v_ebit, v_interes = _serie_valores(ebit), _serie_valores(interes)
    if v_ebit and v_interes and v_interes[-1] not in (0, None):
        cobertura = abs(v_ebit[-1] / v_interes[-1])
        if cobertura < 2:
            señales.append({'categoria': '🔒 Solvencia', 'tipo': 'ALERTA',
                'texto': f'Cobertura de intereses (EBIT/Intereses) de {cobertura:.1f}x: la ganancia operativa '
                          'cubre los intereses con poco margen — riesgo si sube el costo de la deuda.'})
        elif cobertura > 8:
            señales.append({'categoria': '🔒 Solvencia', 'tipo': 'OK',
                'texto': f'Cobertura de intereses (EBIT/Intereses) de {cobertura:.1f}x: amplio margen para '
                          'afrontar el pago de intereses de la deuda.'})

    # ── LIQUIDEZ ──────────────────────────────────────────────────────
    activos_c = _buscar_fila(df_bal, ['Current Assets', 'Total Current Assets'])
    pasivos_c = _buscar_fila(df_bal, ['Current Liabilities', 'Total Current Liabilities'])
    v_ac, v_pc = _serie_valores(activos_c), _serie_valores(pasivos_c)
    if v_ac and v_pc and v_pc[-1] not in (0, None):
        cr = v_ac[-1] / v_pc[-1]
        if cr < 1:
            señales.append({'categoria': '💧 Liquidez', 'tipo': 'ALERTA',
                'texto': f'Current Ratio de {cr:.2f}x (por debajo de 1x): los pasivos de corto plazo superan a '
                          'los activos corrientes — posible tensión de liquidez.'})
        elif cr > 2:
            señales.append({'categoria': '💧 Liquidez', 'tipo': 'OK',
                'texto': f'Current Ratio de {cr:.2f}x: liquidez muy holgada para cubrir obligaciones de corto plazo.'})
        else:
            señales.append({'categoria': '💧 Liquidez', 'tipo': 'INFO',
                'texto': f'Current Ratio de {cr:.2f}x: liquidez de corto plazo en un rango saludable.'})
        if len(v_ac) >= 2 and len(v_pc) >= 2:
            kw_actual = v_ac[-1] - v_pc[-1]
            kw_inicial = v_ac[0] - v_pc[0]
            if kw_actual < 0:
                señales.append({'categoria': '💧 Liquidez', 'tipo': 'ALERTA',
                    'texto': f'Capital de trabajo negativo ({_fmt_big(kw_actual)}): estructuralmente depende de '
                              'financiar su operación con pasivos de corto plazo.'})
            elif kw_actual > kw_inicial * 1.3 and kw_inicial > 0:
                señales.append({'categoria': '💧 Liquidez', 'tipo': 'OK',
                    'texto': f'El capital de trabajo se fortaleció respecto al inicio del historial '
                              f'({_fmt_big(kw_inicial)} → {_fmt_big(kw_actual)}).'})

    # ── CALIDAD DE LA CAJA ───────────────────────────────────────────
    fcf  = _buscar_fila(df_cf, ['Free Cash Flow'])
    cfo  = _buscar_fila(df_cf, ['Operating Cash Flow', 'Total Cash From Operating Activities'])
    capex = _buscar_fila(df_cf, ['Capital Expenditure', 'Capital Expenditures'])
    v_fcf, v_cfo = _serie_valores(fcf), _serie_valores(cfo)

    if v_fcf:
        if v_fcf[-1] > 0:
            señales.append({'categoria': '💵 Calidad de Caja', 'tipo': 'OK',
                'texto': f'Free Cash Flow del último período positivo ({_fmt_big(v_fcf[-1])}): la empresa genera '
                          'caja real, más allá del resultado contable.'})
        else:
            señales.append({'categoria': '💵 Calidad de Caja', 'tipo': 'ALERTA',
                'texto': f'Free Cash Flow del último período negativo ({_fmt_big(v_fcf[-1])}): revisar si '
                          'responde a un ciclo fuerte de inversión (expansión) o a un problema estructural de caja.'})

    if v_fcf and v_neto and v_neto[-1] not in (0, None):
        ratio_calidad = v_fcf[-1] / v_neto[-1] if v_neto[-1] > 0 else None
        if ratio_calidad is not None:
            if ratio_calidad > 1.2:
                señales.append({'categoria': '💵 Calidad de Caja', 'tipo': 'OK',
                    'texto': f'FCF/Ganancia Neta de {ratio_calidad:.2f}x: la empresa convierte sus ganancias '
                              'contables en caja de forma eficiente (o incluso mejor) — buena calidad de resultados.'})
            elif ratio_calidad < 0.6:
                señales.append({'categoria': '💵 Calidad de Caja', 'tipo': 'ALERTA',
                    'texto': f'FCF/Ganancia Neta de {ratio_calidad:.2f}x: la ganancia contable no se está '
                              'traduciendo en caja en la misma proporción — revisar capital de trabajo o CAPEX elevado.'})

    if capex is not None and ventas is not None:
        v_capex = _serie_valores(capex)
        if v_capex and v_ventas and v_ventas[-1] not in (0, None):
            intensidad = abs(v_capex[-1]) / v_ventas[-1] * 100
            if intensidad > 15:
                señales.append({'categoria': '💵 Calidad de Caja', 'tipo': 'INFO',
                    'texto': f'CAPEX equivalente a {intensidad:.1f}% de las ventas: negocio intensivo en capital, '
                              'con fuerte reinversión en activos fijos.'})

    return señales


def interpretar_estados(df_res, df_bal, df_cf):
    """Versión resumida en un solo párrafo (compatibilidad hacia atrás / uso rápido)."""
    detalle = interpretar_estados_detallado(df_res, df_bal, df_cf)
    if not detalle:
        return 'No hay suficientes datos históricos disponibles para armar una interpretación completa.'
    return ' '.join(s['texto'] for s in detalle[:6])


def render_estados_financieros(ticker, key_suffix=''):
    """Bloque completo: selector Anual/Trimestral + interpretación +
    3 tabs (Resultados, Balance, Flujo de Fondos) con gráfico y tabla detallada."""
    if _es_activo_sin_estados(ticker):
        return
    with st.spinner(f'Descargando estados financieros de {ticker}...'):
        data = obtener_estados_financieros(ticker)

    if data is None:
        st.info(f'ℹ️ {ticker} no tiene estados financieros disponibles en Yahoo Finance '
                '(frecuente en ETFs, forex, cripto o commodities sin balance propio).')
        return

    periodo = st.radio('Periodicidad', ['Anual', 'Trimestral'], horizontal=True,
                        key=f'ef_periodo_{ticker}_{key_suffix}')
    suf = 'anual' if periodo == 'Anual' else 'trim'

    df_bal = data.get(f'balance_{suf}')
    df_res = data.get(f'resultados_{suf}')
    df_cf  = data.get(f'flujo_{suf}')

    sin_datos = all(df is None or df.empty for df in [df_bal, df_res, df_cf])
    if sin_datos:
        st.warning(f'No hay datos {periodo.lower()}es disponibles para {ticker}.')
        return

    es_trim = (suf == 'trim')
    señales = interpretar_estados_detallado(df_res, df_bal, df_cf, es_trimestral=es_trim)
    n_ok  = sum(1 for s in señales if s['tipo'] == 'OK')
    n_alt = sum(1 for s in señales if s['tipo'] == 'ALERTA')

    if n_ok >= n_alt + 3:
        veredicto, v_color = 'PERFIL SÓLIDO', '#3fb950'
    elif n_alt >= n_ok + 3:
        veredicto, v_color = 'PUNTOS DE ATENCIÓN', '#f85149'
    else:
        veredicto, v_color = 'PERFIL MIXTO', '#e3b341'

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            f'<div class="kpi-card"><div class="kpi-accent" style="background:{v_color}"></div>'
            f'<div class="kpi-label">Veredicto {periodo}</div>'
            f'<div class="kpi-value" style="font-size:16px">{veredicto}</div>'
            f'<div class="kpi-sub">✅ {n_ok} positivas · ⚠️ {n_alt} alertas</div></div>',
            unsafe_allow_html=True)
    with c2:
        st.markdown(
            f'<div class="kpi-card"><div class="kpi-accent" style="background:#3a7bd5"></div>'
            f'<div class="kpi-label">Períodos analizados</div>'
            f'<div class="kpi-value" style="font-size:16px">{len(_cols_cronologico(_buscar_fila(df_res, ["Total Revenue","Revenue"]) or _buscar_fila(df_bal, ["Total Assets"])))}</div>'
            f'<div class="kpi-sub">{periodo.lower()}es disponibles</div></div>',
            unsafe_allow_html=True)
    with c3:
        st.markdown(
            f'<div class="kpi-card"><div class="kpi-accent" style="background:#bc8cff"></div>'
            f'<div class="kpi-label">Categorías evaluadas</div>'
            f'<div class="kpi-value" style="font-size:16px">{len(set(s["categoria"] for s in señales))}</div>'
            f'<div class="kpi-sub">Crecimiento · Rentabilidad · Solvencia · Liquidez · Caja</div></div>',
            unsafe_allow_html=True)

    st.markdown('<div style="height:6px"></div>', unsafe_allow_html=True)

    if señales:
        col_ok, col_alt = st.columns(2)
        with col_ok:
            st.markdown('<div style="font-size:11px;font-weight:700;color:#3fb950;margin-bottom:4px">✅ SEÑALES POSITIVAS</div>', unsafe_allow_html=True)
            ok_list = [s for s in señales if s['tipo'] == 'OK']
            if ok_list:
                for s in ok_list:
                    st.markdown(f'<div style="font-size:11.5px;color:#3fb950;padding:4px 0;border-bottom:1px solid #21262d">'
                                f'<b>{s["categoria"]}</b> — {s["texto"]}</div>', unsafe_allow_html=True)
            else:
                st.markdown('<div style="font-size:11px;color:#6b7d9a">Sin señales positivas detectadas.</div>', unsafe_allow_html=True)
        with col_alt:
            st.markdown('<div style="font-size:11px;font-weight:700;color:#f85149;margin-bottom:4px">⚠️ PUNTOS DE ATENCIÓN</div>', unsafe_allow_html=True)
            alt_list = [s for s in señales if s['tipo'] == 'ALERTA']
            if alt_list:
                for s in alt_list:
                    st.markdown(f'<div style="font-size:11.5px;color:#f85149;padding:4px 0;border-bottom:1px solid #21262d">'
                                f'<b>{s["categoria"]}</b> — {s["texto"]}</div>', unsafe_allow_html=True)
            else:
                st.markdown('<div style="font-size:11px;color:#6b7d9a">Sin alertas detectadas.</div>', unsafe_allow_html=True)

        info_list = [s for s in señales if s['tipo'] == 'INFO']
        if info_list:
            with st.expander('ℹ️ Datos adicionales de contexto'):
                for s in info_list:
                    st.markdown(f'<div style="font-size:11.5px;color:#8b949e;padding:3px 0">'
                                f'<b>{s["categoria"]}</b> — {s["texto"]}</div>', unsafe_allow_html=True)
    else:
        st.info('Historial insuficiente para generar señales detalladas (se necesitan al menos 2-3 períodos).')

    tab_res, tab_bal, tab_cf = st.tabs(['📄 Estado de Resultados', '🏦 Balance', '💵 Flujo de Fondos'])

    with tab_res:
        if df_res is not None and not df_res.empty:
            fig_r = fig_resultados(df_res)
            if fig_r:
                st.plotly_chart(fig_r, use_container_width=True, config=PLOTLY_CONFIG,
                                 key=f'ef_res_{ticker}_{suf}_{key_suffix}')
            fig_m = fig_margenes(df_res)
            if fig_m:
                st.plotly_chart(fig_m, use_container_width=True, config=PLOTLY_CONFIG,
                                 key=f'ef_mg_{ticker}_{suf}_{key_suffix}')
            with st.expander('📋 Ver tabla completa de resultados'):
                tabla = _tabla_estado(df_res)
                if tabla is not None:
                    st.dataframe(tabla, use_container_width=True)
        else:
            st.info('Sin datos de resultados para este período.')

    with tab_bal:
        if df_bal is not None and not df_bal.empty:
            fig_b = fig_balance(df_bal)
            if fig_b:
                st.plotly_chart(fig_b, use_container_width=True, config=PLOTLY_CONFIG,
                                 key=f'ef_bal_{ticker}_{suf}_{key_suffix}')
            with st.expander('📋 Ver tabla completa de balance'):
                tabla = _tabla_estado(df_bal)
                if tabla is not None:
                    st.dataframe(tabla, use_container_width=True)
        else:
            st.info('Sin datos de balance para este período.')

    with tab_cf:
        if df_cf is not None and not df_cf.empty:
            fig_c = fig_flujo(df_cf)
            if fig_c:
                st.plotly_chart(fig_c, use_container_width=True, config=PLOTLY_CONFIG,
                                 key=f'ef_cf_{ticker}_{suf}_{key_suffix}')
            with st.expander('📋 Ver tabla completa de flujo de fondos'):
                tabla = _tabla_estado(df_cf)
                if tabla is not None:
                    st.dataframe(tabla, use_container_width=True)
        else:
            st.info('Sin datos de flujo de fondos para este período.')


# ==============================================================
#  COMPARATIVA MULTI-TICKER (para usar en modulo_comparador)
# ==============================================================

def _snapshot_ticker(ticker, periodo='Anual'):
    """Extrae un snapshot de métricas clave (último período + crecimiento)
    para comparar varios tickers lado a lado."""
    if _es_activo_sin_estados(ticker):
        return None
    data = obtener_estados_financieros(ticker)
    if data is None:
        return None
    suf = 'anual' if periodo == 'Anual' else 'trim'
    df_res = data.get(f'resultados_{suf}')
    df_bal = data.get(f'balance_{suf}')
    df_cf  = data.get(f'flujo_{suf}')
    if df_res is None or df_res.empty:
        return None

    periodos_año = 4.0 if suf == 'trim' else 1.0

    ventas = _buscar_fila(df_res, ['Total Revenue', 'Revenue'])
    neto   = _buscar_fila(df_res, ['Net Income', 'Net Income Common Stockholders'])
    ebitda = _buscar_fila(df_res, ['EBITDA', 'Normalized EBITDA'])
    bruto  = _buscar_fila(df_res, ['Gross Profit'])
    deuda  = _buscar_fila(df_bal, ['Total Debt']) if df_bal is not None else None
    equity = _buscar_fila(df_bal, ['Stockholders Equity', 'Total Stockholders Equity', 'Common Stock Equity']) if df_bal is not None else None
    ac     = _buscar_fila(df_bal, ['Current Assets', 'Total Current Assets']) if df_bal is not None else None
    pc     = _buscar_fila(df_bal, ['Current Liabilities', 'Total Current Liabilities']) if df_bal is not None else None
    fcf    = _buscar_fila(df_cf, ['Free Cash Flow']) if df_cf is not None else None

    v_ventas = _serie_valores(ventas)
    v_neto   = _serie_valores(neto)
    v_ebitda = _serie_valores(ebitda)
    v_bruto  = _serie_valores(bruto)
    v_deuda  = _serie_valores(deuda)
    v_equity = _serie_valores(equity)
    v_ac     = _serie_valores(ac)
    v_pc     = _serie_valores(pc)
    v_fcf    = _serie_valores(fcf)

    if not v_ventas:
        return None

    return {
        'Ticker': ticker,
        'Ingresos (últ.)': v_ventas[-1],
        'CAGR Ingresos %': _cagr(v_ventas, periodos_año),
        'Ganancia Neta (últ.)': v_neto[-1] if v_neto else None,
        'CAGR Ganancia Neta %': _cagr(v_neto, periodos_año) if v_neto else None,
        'EBITDA (últ.)': v_ebitda[-1] if v_ebitda else None,
        'Margen EBITDA %': (v_ebitda[-1] / v_ventas[-1] * 100) if v_ebitda and v_ventas[-1] not in (0, None) else None,
        'Margen Bruto %': (v_bruto[-1] / v_ventas[-1] * 100) if v_bruto and v_ventas[-1] not in (0, None) else None,
        'Margen Neto %': (v_neto[-1] / v_ventas[-1] * 100) if v_neto and v_ventas[-1] not in (0, None) else None,
        'D/E': (v_deuda[-1] / v_equity[-1]) if v_deuda and v_equity and v_equity[-1] not in (0, None) else None,
        'Current Ratio': (v_ac[-1] / v_pc[-1]) if v_ac and v_pc and v_pc[-1] not in (0, None) else None,
        'FCF (últ.)': v_fcf[-1] if v_fcf else None,
        'FCF/Neto': (v_fcf[-1] / v_neto[-1]) if v_fcf and v_neto and v_neto[-1] not in (0, None) and v_neto[-1] > 0 else None,
    }


@st.cache_data(ttl=3600, show_spinner=False)
def tabla_comparativa_estados(tickers_tuple, periodo='Anual'):
    """tickers_tuple: tupla de tickers. Devuelve DataFrame con snapshot comparativo
    (una fila por ticker) o DataFrame vacío si ninguno tiene datos."""
    filas = []
    for tk in tickers_tuple:
        snap = _snapshot_ticker(tk, periodo)
        if snap:
            filas.append(snap)
    if not filas:
        return pd.DataFrame()
    return pd.DataFrame(filas)


def render_comparativo_estados(tickers, key_suffix=''):
    """Tabla + lectura comparativa de estados financieros para varios tickers.
    Pensado para insertarse en modulo_comparador(), junto a la comparación fundamental."""
    tickers_validos = [t for t in tickers if not _es_activo_sin_estados(t)]
    if not tickers_validos:
        st.info('Ninguno de los activos seleccionados tiene estados financieros propios '
                '(son forex, cripto o commodities).')
        return

    periodo = st.radio('Periodicidad', ['Anual', 'Trimestral'], horizontal=True,
                        key=f'cmp_ef_periodo_{key_suffix}')

    with st.spinner('Descargando estados financieros comparados...'):
        df_cmp = tabla_comparativa_estados(tuple(sorted(tickers_validos)), periodo)

    if df_cmp.empty:
        st.warning('No se pudieron obtener estados financieros para estos activos.')
        return

    # Reordenar según el orden original de selección
    df_cmp['_orden'] = df_cmp['Ticker'].apply(lambda t: tickers_validos.index(t) if t in tickers_validos else 999)
    df_cmp = df_cmp.sort_values('_orden').drop(columns=['_orden']).reset_index(drop=True)

    df_show = df_cmp.copy()
    for col in ['Ingresos (últ.)', 'Ganancia Neta (últ.)', 'EBITDA (últ.)', 'FCF (últ.)']:
        if col in df_show.columns:
            df_show[col] = df_show[col].apply(lambda v: _fmt_big(v) if pd.notna(v) else 'N/D')
    for col in ['CAGR Ingresos %', 'CAGR Ganancia Neta %', 'Margen EBITDA %', 'Margen Bruto %', 'Margen Neto %']:
        if col in df_show.columns:
            df_show[col] = df_show[col].apply(lambda v: f'{v:+.1f}%' if pd.notna(v) else 'N/D')
    for col in ['D/E', 'Current Ratio', 'FCF/Neto']:
        if col in df_show.columns:
            df_show[col] = df_show[col].apply(lambda v: f'{v:.2f}x' if pd.notna(v) else 'N/D')

    columnas_directivas = [
        ('CAGR Ingresos %', 'mayor'), ('CAGR Ganancia Neta %', 'mayor'),
        ('Margen EBITDA %', 'mayor'), ('Margen Bruto %', 'mayor'), ('Margen Neto %', 'mayor'),
        ('D/E', 'menor'), ('Current Ratio', 'mayor'), ('FCF/Neto', 'mayor'),
    ]

    def _highlight_mejor(df_num, col, direccion):
        vals = pd.to_numeric(df_cmp[col], errors='coerce')
        if vals.notna().sum() == 0:
            return [''] * len(df_num)
        best_idx = vals.idxmin() if direccion == 'menor' else vals.idxmax()
        return ['background-color:#0d2410;color:#3fb950;font-weight:700' if i == best_idx else '' for i in range(len(df_num))]

    styled = df_show.style
    for col, direccion in columnas_directivas:
        if col in df_show.columns:
            styled = styled.apply(lambda s, c=col, d=direccion: _highlight_mejor(s, c, d), subset=[col])
    styled = (styled
        .set_properties(**{'background-color': '#0d1117', 'color': '#e6edf3', 'border': '1px solid #21262d'})
        .set_table_styles([
            {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', '#e6edf3'),
                ('font-weight', '700'), ('text-align', 'center'),
                ('border-bottom', '2px solid #3a7bd5'), ('font-size', '11px')]},
            {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]},
        ]))
    st.caption('↔️ Desliza horizontalmente para ver todas las columnas. 🟢 resaltado = mejor valor del grupo en esa métrica.')
    st.dataframe(styled, use_container_width=True, height=min(400, len(df_show) * 45 + 90))

    # ── Gráfico comparativo de crecimiento e ingresos ────────────────
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df_cmp['Ticker'], y=df_cmp['Ingresos (últ.)'],
                          name='Ingresos (último período)', marker_color=C_ACENT))
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE, height=340,
        title=dict(text='Ingresos del último período — comparativa', font=dict(color=C_TEXT, size=13)),
        xaxis=dict(gridcolor=C_GRID), yaxis=dict(gridcolor=C_GRID),
        margin=dict(l=10, r=10, t=45, b=10), showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG, key=f'cmp_ef_ingresos_{key_suffix}')

    fig2 = go.Figure()
    for col_m, color_m in [('CAGR Ingresos %', C_ACENT), ('Margen Neto %', C_MONSTER)]:
        fig2.add_trace(go.Bar(x=df_cmp['Ticker'], y=df_cmp[col_m], name=col_m, marker_color=color_m))
    fig2.add_hline(y=0, line_color=C_MUTED, opacity=0.4)
    fig2.update_layout(
        **PLOTLY_LAYOUT_BASE, barmode='group', height=340,
        title=dict(text='Crecimiento (CAGR) vs. Margen Neto — comparativa', font=dict(color=C_TEXT, size=13)),
        xaxis=dict(gridcolor=C_GRID), yaxis=dict(gridcolor=C_GRID, title='%'),
        margin=dict(l=10, r=10, t=45, b=10), legend=dict(orientation='h', y=1.12),
    )
    st.plotly_chart(fig2, use_container_width=True, config=PLOTLY_CONFIG, key=f'cmp_ef_cagr_margen_{key_suffix}')

    # ── Lectura automática: líder por métrica ────────────────────────
    lecturas = []
    for col, direccion, etiqueta in [
        ('CAGR Ingresos %', 'mayor', 'mejor crecimiento de ingresos'),
        ('Margen Neto %', 'mayor', 'mejor margen neto'),
        ('D/E', 'menor', 'balance más conservador (menor D/E)'),
        ('FCF/Neto', 'mayor', 'mejor calidad de conversión de ganancias en caja'),
    ]:
        vals = pd.to_numeric(df_cmp[col], errors='coerce')
        if vals.notna().sum() == 0:
            continue
        idx = vals.idxmin() if direccion == 'menor' else vals.idxmax()
        tk_lider = df_cmp.loc[idx, 'Ticker']
        val_lider = vals.loc[idx]
        sufijo = '%' if '%' in col else 'x'
        lecturas.append(f'<b>{tk_lider}</b> lidera en {etiqueta} ({val_lider:.2f}{sufijo}).')

    if lecturas:
        st.markdown(f"""
        <div class="interp-card">
          <div class="interp-header">🏆 Liderazgo por métrica ({periodo})</div>
          {'<br>'.join(lecturas)}
        </div>
        """, unsafe_allow_html=True)


def render_analisis_profundo(ticker, key_suffix=''):
    """Punto de entrada único: Accionistas + Estados Financieros, con sub-tabs.
    Es lo que hay que llamar desde el script principal."""
    if _es_activo_sin_estados(ticker):
        st.info(f'ℹ️ {ticker} no tiene accionistas ni estados financieros propios '
                '(es forex, cripto o commodity).')
        return
    tab_acc, tab_ef = st.tabs(['👥 Accionistas Principales', '📑 Estados Financieros'])
    with tab_acc:
        render_accionistas(ticker, key_suffix=key_suffix)
    with tab_ef:
        render_estados_financieros(ticker, key_suffix=key_suffix)
