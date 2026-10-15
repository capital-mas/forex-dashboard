# ==============================================================
#  MÓDULO UNIFICADO: ANÁLISIS FUNDAMENTAL + F-SCORE (PIOTROSKI)
#  100% desde CSV — NO llama a Yahoo Finance.
#
#  El CSV (una fila por empresa) ya trae: F-Score, los 9 criterios,
#  ratios, scores 0-10, veredicto, señales y valores base.
#
#  Uso desde app.py:
#      from modulo_fundamental_fscore import modulo_fundamental_fscore
#      modulo_fundamental_fscore(supabase, puede_cargar=ES_ADMIN,
#                                PLOTLY_CONFIG=PLOTLY_CONFIG)
# ==============================================================

import datetime as dt
import io

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

TABLA_SUPABASE = 'fundamental_csv'   # ver SQL al final del archivo

# ---------------------------------------------------------------
#  ESQUEMA DEL CSV
# ---------------------------------------------------------------
COLS_TEXTO = {
    'Ticker', 'Nombre', 'Sectores', 'Base de datos', 'Último período',
    'Comparado con', 'Veredicto', 'Veredicto sin compuerta', 'recommendation',
    'sector_yahoo', 'industria_yahoo', 'pais', 'moneda_estados',
    'moneda_cotizacion', 'Señales positivas', 'Señales alerta', 'Avisos',
}
COLS_BOOL = {'ebitda_negativo', 'patrimonio_negativo'}
COLS_OBLIGATORIAS = ['Ticker', 'F-Score']

# criterio -> (columna crit_, texto, col actual, col previo, tipo)
#  tipo: 'prev' compara contra año previo · 'umbral' contra 1 ·
#        'vs_ni' OCF contra Net Income
CRITERIOS = [
    ('C1 Net Income ↑',       'crit_net_income',     'Utilidad neta ≥ año anterior',          'fs_net_income',     'fs_net_income_prev', 'money'),
    ('C2 ROA ↑',              'crit_roa',            'ROA ≥ ROA del año anterior',            'fs_roa',            'fs_roa_prev',        'pct'),
    ('C3 OCF ↑',              'crit_ocf_growth',     'Flujo operativo ≥ año anterior',        'fs_ocf',            'fs_ocf_prev',        'money'),
    ('C4 OCF > NI',           'crit_ocf_vs_ni',      'Flujo operativo > utilidad neta',       'fs_ocf',            'fs_net_income',      'money'),
    ('C5 Deuda ↓',            'crit_debt',           'Deuda total < año anterior',            'fs_debt',           'fs_debt_prev',       'money'),
    ('C6 Current Ratio > 1',  'crit_current_ratio',  'Activo corriente / pasivo corriente > 1','fs_current_ratio', None,                 'x'),
    ('C7 Sin dilución',       'crit_shares',         'Acciones ≤ año anterior',               'fs_shares',         'fs_shares_prev',     'num'),
    ('C8 Margen Bruto ↑',     'crit_gross_margin',   'Utilidad bruta ≥ año anterior',         'fs_gross_profit',   'fs_gross_profit_prev','money'),
    ('C9 Asset Turnover ≥ 1', 'crit_asset_turnover', 'Ingresos / activos previos ≥ 1',        'fs_asset_turnover', None,                 'x'),
]
NOMBRES_CRIT = [c[0] for c in CRITERIOS]

# (label, columna, tipo, mult para filtro)   tipo: pct | x | money | num | int
GRUPOS_METRICAS = {
    '📐 Valuación': [
        ('PER', 'per', 'x'), ('P/B', 'pb', 'x'), ('P/S', 'ps', 'x'), ('PEG', 'peg', 'x'),
        ('EV/EBITDA', 'ev_ebitda', 'x'), ('EV/Sales', 'ev_sales', 'x'), ('P/FCF', 'p_fcf', 'x'),
    ],
    '📈 Rentabilidad / Márgenes': [
        ('ROE', 'roe', 'pct'), ('ROA', 'roa', 'pct'), ('ROIC', 'roic', 'pct'),
        ('Mg. Bruto', 'gross_margin', 'pct'), ('Mg. Operativo', 'op_margin', 'pct'),
        ('Mg. Neto', 'profit_margin', 'pct'),
    ],
    '🚀 Crecimiento': [
        ('Rev. Growth (interanual)', 'revenue_growth', 'pct'),
        ('Rev. Growth (trimestral)', 'revenue_growth_qoq', 'pct'),
        ('EPS Growth', 'eps_growth', 'pct'), ('Earnings Growth', 'earnings_growth', 'pct'),
        ('Alza YTD %', 'alza_ytd', 'pctpts'),
    ],
    '🔒 Solvencia y Riesgo': [
        ('D/E', 'debt_equity', 'x'), ('Net Debt/EBITDA', 'net_debt_ebitda', 'x'),
        ('Current Ratio', 'curr_ratio', 'x'), ('Interest Coverage', 'interest_coverage', 'x'),
        ('Beta', 'beta', 'num'),
    ],
    '💰 Retorno al accionista': [
        ('Div. Yield', 'div_yield', 'pct'), ('Payout Ratio', 'payout_ratio', 'pct'),
        ('Shares Change YoY', 'shares_change_yoy', 'pctpts'), ('FCF Conversion', 'fcf_conversion', 'pct'),
    ],
    '🏦 Balance / Flujos (TTM)': [
        ('Market Cap', 'market_cap', 'money'), ('Enterprise Value', 'enterprise_value', 'money'),
        ('Ingresos TTM', 'revenue_ttm', 'money'), ('EBITDA TTM', 'ebitda_ttm', 'money'),
        ('Utilidad neta TTM', 'net_income_ttm', 'money'), ('OCF TTM', 'ocf_ttm', 'money'),
        ('FCF TTM', 'fcf_ttm', 'money'), ('Deuda total', 'total_debt', 'money'),
        ('Caja', 'cash', 'money'), ('Patrimonio', 'equity', 'money'),
        ('Activos totales', 'total_assets', 'money'),
    ],
}

# métricas para el comparador: (label, col, tipo, mejor)  mejor: 'menor' | 'mayor' | None
METRICAS_COMPARAR = [
    ('F-Score', 'F-Score', 'num', 'mayor'), ('Score combinado', 'Score combinado', 'num', 'mayor'),
    ('Score fundamental', 'Score fundamental (0-10)', 'num', 'mayor'),
    ('Score calidad', 'Score calidad', 'num', 'mayor'), ('Score valoración', 'Score valoración', 'num', 'mayor'),
    ('Score crecimiento', 'Score crecimiento', 'num', 'mayor'), ('Score riesgo (↓ mejor)', 'Score riesgo', 'num', 'menor'),
    ('PER', 'per', 'x', 'menor'), ('P/B', 'pb', 'x', 'menor'), ('EV/EBITDA', 'ev_ebitda', 'x', 'menor'),
    ('P/FCF', 'p_fcf', 'x', 'menor'), ('PEG', 'peg', 'x', 'menor'),
    ('ROE', 'roe', 'pct', 'mayor'), ('ROIC', 'roic', 'pct', 'mayor'),
    ('Mg. Bruto', 'gross_margin', 'pct', 'mayor'), ('Mg. Operativo', 'op_margin', 'pct', 'mayor'),
    ('Mg. Neto', 'profit_margin', 'pct', 'mayor'), ('Rev. Growth', 'revenue_growth', 'pct', 'mayor'),
    ('D/E', 'debt_equity', 'x', 'menor'), ('Net Debt/EBITDA', 'net_debt_ebitda', 'x', 'menor'),
    ('Current Ratio', 'curr_ratio', 'x', 'mayor'), ('Interest Coverage', 'interest_coverage', 'x', 'mayor'),
    ('Beta', 'beta', 'num', 'menor'), ('Div. Yield', 'div_yield', 'pct', 'mayor'),
    ('Alza YTD %', 'alza_ytd', 'pctpts', 'mayor'), ('Market Cap', 'market_cap', 'money', None),
]

COLOR_VEREDICTO = {
    'COMPRA FUERTE': '#3fb950', 'COMPRA': '#3fb950', 'MANTENER': '#e3b341',
    'RIESGO': '#f0883e', 'EVITAR': '#f85149',
}


# ---------------------------------------------------------------
#  FORMATO
# ---------------------------------------------------------------
def _nd(v):
    return v is None or (isinstance(v, float) and np.isnan(v)) or (not isinstance(v, str) and pd.isna(v))


def _fmt(v, tipo):
    if _nd(v):
        return 'N/D'
    try:
        v = float(v)
    except Exception:
        return str(v)
    if tipo == 'pct':
        return f'{v * 100:.1f}%'
    if tipo == 'pctpts':
        return f'{v:.1f}%'
    if tipo == 'x':
        return f'{v:.2f}x'
    if tipo == 'int':
        return f'{int(v)}'
    if tipo == 'money':
        a = abs(v)
        if a >= 1e12: return f'{v / 1e12:,.2f}T'
        if a >= 1e9:  return f'{v / 1e9:,.2f}B'
        if a >= 1e6:  return f'{v / 1e6:,.1f}M'
        return f'{v:,.0f}'
    return f'{v:.2f}'


def _fmt_precio(p):
    if _nd(p) or p <= 0:
        return 'S/D'
    return f'${p:,.0f}' if p >= 1000 else (f'${p:.2f}' if p >= 10 else f'${p:.4f}')


def _chk(v):
    if _nd(v):
        return '—'
    return '✅' if int(v) == 1 else '❌'


def _kpi_cards(items):
    cols = st.columns(len(items))
    for col, (label, value, sub, color) in zip(cols, items):
        with col:
            st.markdown(
                f'<div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;'
                f'padding:16px 18px;position:relative;overflow:hidden">'
                f'<div style="position:absolute;top:0;left:0;width:100%;height:2px;background:{color}"></div>'
                f'<div style="color:#f5f7fa;font-size:12px;font-weight:700;text-transform:uppercase;'
                f'letter-spacing:1px;margin-bottom:6px">{label}</div>'
                f'<div style="color:#e6edf3;font-size:22px;font-weight:700;'
                f'font-family:\'JetBrains Mono\',monospace">{value}</div>'
                f'<div style="color:#f5f7fa;font-size:13px;margin-top:4px">{sub}</div></div>',
                unsafe_allow_html=True)
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)


def _color_fscore(val):
    try:
        v = float(val)
    except Exception:
        return ''
    if v <= 3:   return 'background-color:#2a0a0a;color:#f85149;font-weight:700'
    if v <= 5:   return 'background-color:#2a1a05;color:#f0883e;font-weight:700'
    if v <= 6.5: return 'background-color:#1e1a05;color:#e3b341;font-weight:700'
    if v <= 8:   return 'background-color:#081a0a;color:#7ee787;font-weight:700'
    return 'background-color:#051505;color:#3fb950;font-weight:700'


def _color_score10(val):
    try:
        v = float(val)
    except Exception:
        return ''
    c = '#f85149' if v < 4 else '#f0883e' if v < 5.5 else '#e3b341' if v < 7 else '#7ee787' if v < 8.5 else '#3fb950'
    return f'color:{c};font-weight:700'


def _color_veredicto(val):
    return f'color:{COLOR_VEREDICTO.get(str(val), "#e6edf3")};font-weight:700'


def _color_chk(val):
    return {'✅': 'background-color:#081a0a', '❌': 'background-color:#2a0a0a'}.get(val, 'color:#6b7d9a')


def _estilizar(df, cols_f=(), cols_s10=(), cols_ver=(), cols_chk=()):
    _map = 'map' if hasattr(df.style, 'map') else 'applymap'
    s = df.style
    for cols, fn in ((cols_f, _color_fscore), (cols_s10, _color_score10),
                     (cols_ver, _color_veredicto), (cols_chk, _color_chk)):
        cols = [c for c in cols if c in df.columns]
        if cols:
            s = getattr(s, _map)(fn, subset=cols)
    return (s.set_properties(**{'background-color': '#0d1117', 'color': '#e6edf3',
                                'border': '1px solid #21262d'})
             .set_table_styles([
                 {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', '#e6edf3'),
                  ('font-weight', '700'), ('text-align', 'center'),
                  ('border-bottom', '2px solid #3a7bd5'), ('font-size', '11px')]},
                 {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]}]))


# ---------------------------------------------------------------
#  LECTURA Y VALIDACIÓN DEL CSV
# ---------------------------------------------------------------
def leer_csv(archivo):
    """Lee un CSV (UploadedFile, bytes o path) y devuelve un DataFrame normalizado."""
    if hasattr(archivo, 'getvalue'):
        archivo = io.BytesIO(archivo.getvalue())
    elif isinstance(archivo, (bytes, bytearray)):
        archivo = io.BytesIO(archivo)
    df = pd.read_csv(archivo, encoding='utf-8-sig', sep=None, engine='python')
    df.columns = [str(c).strip() for c in df.columns]
    faltan = [c for c in COLS_OBLIGATORIAS if c not in df.columns]
    if faltan:
        raise ValueError(f'Al CSV le faltan columnas obligatorias: {", ".join(faltan)}')
    df['Ticker'] = df['Ticker'].astype(str).str.strip().str.upper()
    df = df[df['Ticker'].ne('') & df['Ticker'].ne('NAN')].copy()
    if 'Sectores' not in df.columns:
        df['Sectores'] = 'Sin sector'
    for c in df.columns:
        if c in COLS_TEXTO:
            df[c] = df[c].astype('object').where(df[c].notna(), None)
        elif c in COLS_BOOL:
            df[c] = df[c].astype(str).str.lower().isin(['true', '1', 'verdadero', 'si', 'sí'])
        else:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    return df.reset_index(drop=True)


def combinar(df_actual, df_nuevo):
    """Une dos tablas: la clave es (Ticker, Sectores); gana la fila nueva."""
    if df_actual is None or df_actual.empty:
        return df_nuevo
    todo = pd.concat([df_actual, df_nuevo], ignore_index=True)
    return todo.drop_duplicates(subset=['Ticker', 'Sectores'], keep='last').reset_index(drop=True)


# ---------------------------------------------------------------
#  PERSISTENCIA OPCIONAL EN SUPABASE (para que todos los usuarios vean lo mismo)
# ---------------------------------------------------------------
def _json_limpio(v):
    if isinstance(v, (np.floating, float)):
        return None if pd.isna(v) else float(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return None if (not isinstance(v, str) and pd.isna(v)) else v


def guardar_en_supabase(client, df):
    if client is None:
        return False, 'Sin conexión a Supabase.'
    try:
        ahora = dt.datetime.now(dt.timezone.utc).isoformat()
        filas = [{
            'id': f"{r['Ticker']}|{r.get('Sectores', '')}",
            'ticker': r['Ticker'], 'sectores': r.get('Sectores'),
            'datos': {k: _json_limpio(v) for k, v in r.items()},
            'actualizado_en': ahora,
        } for r in df.to_dict('records')]
        for i in range(0, len(filas), 200):
            client.table(TABLA_SUPABASE).upsert(filas[i:i + 200]).execute()
        return True, f'{len(filas)} filas guardadas.'
    except Exception as e:
        return False, f'No se pudo guardar en Supabase ({e}). ¿Creaste la tabla {TABLA_SUPABASE}?'


def leer_de_supabase(client):
    if client is None:
        return None
    try:
        filas, desde = [], 0
        while True:
            res = (client.table(TABLA_SUPABASE).select('datos')
                   .range(desde, desde + 999).execute())
            lote = [r['datos'] for r in (res.data or [])]
            filas += lote
            if len(lote) < 1000:
                break
            desde += 1000
        if not filas:
            return None
        return leer_csv(io.BytesIO(pd.DataFrame(filas).to_csv(index=False).encode('utf-8')))
    except Exception:
        return None


def borrar_de_supabase(client):
    try:
        client.table(TABLA_SUPABASE).delete().neq('id', '').execute()
    except Exception:
        pass


def obtener_base(client=None):
    """DataFrame vigente: sesión -> Supabase (una sola vez por sesión) -> None."""
    if 'ffs_df' in st.session_state and st.session_state['ffs_df'] is not None:
        return st.session_state['ffs_df']
    if not st.session_state.get('ffs_supabase_intentado'):
        st.session_state['ffs_supabase_intentado'] = True
        df = leer_de_supabase(client)
        if df is not None:
            st.session_state['ffs_df'] = df
            return df
    return None


# ---------------------------------------------------------------
#  PUENTE PARA EL RESTO DE LA APP (Buscador / Comparador / IA)
#  Reemplaza a analizar_fundamental() sin tocar Yahoo.
# ---------------------------------------------------------------
def fundamental_desde_csv(ticker, df=None):
    """Devuelve un dict con las mismas claves que analizar_fundamental() o None.
    En app.py:
        def analizar_fundamental(ticker, industria):
            return fundamental_desde_csv(ticker)
    """
    if df is None:
        df = st.session_state.get('ffs_df')
    if df is None or df.empty:
        return None
    sub = df[df['Ticker'] == str(ticker).upper()]
    if sub.empty:
        return None
    r = sub.iloc[0].to_dict()
    g = lambda k: None if _nd(r.get(k)) else r.get(k)
    partir = lambda k: [s.strip() for s in str(r.get(k) or '').split('|') if s.strip()]
    senales = [('OK', m) for m in partir('Señales positivas')] + [('ALT', m) for m in partir('Señales alerta')]
    ver = r.get('Veredicto') or ''
    out = dict(
        ticker=r['Ticker'], nombre=r.get('Nombre') or r['Ticker'], sector=r.get('sector_yahoo') or 'Sin Clasificar',
        industria=r.get('Sectores'), precio=g('precio'), market_cap=g('market_cap'), ev=g('enterprise_value'),
        per=g('per'), pb=g('pb'), ps=g('ps'), peg=g('peg'), ev_ebitda=g('ev_ebitda'),
        roe=g('roe'), roa=g('roa'), gross_margin=g('gross_margin'), op_margin=g('op_margin'),
        profit_margin=g('profit_margin'), debt_equity=g('debt_equity'), curr_ratio=g('curr_ratio'),
        beta=g('beta'), div_yield=g('div_yield'), revenue_growth=g('revenue_growth'),
        eps_growth=g('eps_growth'), earnings_growth=g('earnings_growth'),
        fcf=g('fcf_ttm'), op_cf=g('ocf_ttm'), target_price=g('target_price'), cash=g('cash'),
        alza_ytd=g('alza_ytd'), recommendation=g('recommendation'),
        p_fcf=g('p_fcf'), ev_sales=g('ev_sales'), roic=g('roic'), net_debt_ebitda=g('net_debt_ebitda'),
        interest_coverage=g('interest_coverage'), payout_ratio=g('payout_ratio'),
        shares_change_yoy=g('shares_change_yoy'), fcf_conversion=g('fcf_conversion'),
        senales=senales, senal_final=ver, sector_senales=[],
        bench={'descripcion': 'Datos desde CSV.', 'metricas_clave': []},
        n_ok=int(r.get('Señales OK') or 0), n_alt=int(r.get('Alertas') or 0),
        f_score=g('F-Score'), score_combinado=g('Score combinado'), fuente='CSV',
    )
    return out


# ---------------------------------------------------------------
#  SEMÁFORO (a partir de las columnas del CSV)
# ---------------------------------------------------------------
def _semaforo(r):
    def v(k):
        x = r.get(k)
        return None if _nd(x) else float(x)

    def rango(val, cortes, etiquetas, emojis):
        for c, e, em in zip(cortes, etiquetas, emojis):
            if val >= c:
                return em, e
        return emojis[-1], etiquetas[-1]

    filas = []
    roe = v('roe')
    if roe is not None:
        e, l = rango(roe * 100, [25, 15, 8, -1e9], ['Excepcional', 'Buena', 'Aceptable', 'Débil'], ['🟢', '🟢', '🟡', '🔴'])
        filas.append(('Rentabilidad (ROE)', e, l))
    gm = v('gross_margin')
    if gm is not None:
        e, l = rango(gm * 100, [60, 40, 20, -1e9], ['Excelente', 'Bueno', 'Moderado', 'Bajo'], ['🟢', '🟢', '🟡', '🔴'])
        filas.append(('Margen Bruto', e, l))
    fcf = v('fcf_ttm')
    if fcf is not None:
        filas.append(('Flujo de Caja (FCF)', '🟢' if fcf > 0 else '🔴', 'Positivo' if fcf > 0 else 'Negativo'))
    rg = v('revenue_growth')
    if rg is not None:
        e, l = rango(rg * 100, [20, 10, 0, -1e9], ['Muy alto', 'Bueno', 'Moderado', 'Contracción'], ['🟢', '🟢', '🟡', '🔴'])
        filas.append(('Crecimiento', e, l))
    de = v('debt_equity')
    if de is not None:
        e, l = ('🟢', 'Muy bajo') if de < .5 else ('🟢', 'Conservador') if de < 1 else ('🟡', 'Elevado') if de < 2 else ('🔴', 'Muy elevado')
        filas.append(('Endeudamiento', e, l))
    cr = v('curr_ratio')
    if cr is not None:
        e, l = rango(cr, [2, 1.5, 1, -1e9], ['Excelente', 'Saludable', 'Ajustada', 'Riesgo de liquidez'], ['🟢', '🟢', '🟡', '🔴'])
        filas.append(('Liquidez', e, l))
    per = v('per')
    if per is not None and per > 0:
        e, l = (('🟢', 'Muy barata') if per < 10 else ('🟢', 'Barata') if per < 15 else
                ('🟡', 'Normal') if per < 25 else ('🟠', 'Exigente') if per < 40 else ('🔴', 'Muy exigente'))
        filas.append(('Valoración (PER)', e, l))
    beta = v('beta')
    if beta is not None:
        e, l = (('🟢', 'Baja (defensiva)') if beta < .8 else ('🟡', 'En línea con el mercado') if beta < 1.2 else
                ('🟠', 'Alta') if beta < 1.5 else ('🔴', 'Muy alta'))
        filas.append(('Volatilidad (Beta)', e, l))
    return filas


COLOR_EMOJI = {'🟢': '#3fb950', '🟡': '#e3b341', '🟠': '#f0883e', '🔴': '#f85149'}


# ---------------------------------------------------------------
#  TAB 1 — RANKING (tabla unificada + filtros)
# ---------------------------------------------------------------
def _tabla_ranking(df, PLOTLY_CONFIG):
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        sect = st.multiselect('Sector', sorted(df['Sectores'].dropna().unique()), key='ffs_f_sect')
    with c2:
        vers = st.multiselect('Veredicto', sorted(df['Veredicto'].dropna().unique()), key='ffs_f_ver')
    with c3:
        f_rng = st.slider('Rango F-Score', 0.0, 9.0, (0.0, 9.0), 0.5, key='ffs_f_fs')
    with c4:
        sc_rng = st.slider('Score combinado', 0.0, 10.0, (0.0, 10.0), 0.1, key='ffs_f_sc')

    avanzado = st.toggle('🎛️ Modo avanzado (filtros mín/máx y todas las columnas)', key='ffs_avanzado')

    d = df.copy()
    if sect: d = d[d['Sectores'].isin(sect)]
    if vers: d = d[d['Veredicto'].isin(vers)]
    d = d[d['F-Score'].between(*f_rng)]
    if 'Score combinado' in d.columns:
        d = d[d['Score combinado'].between(*sc_rng) | d['Score combinado'].isna() & (sc_rng == (0.0, 10.0))]

    if avanzado:
        with st.expander('🎛️ Filtros mín / máx por métrica (solo se aplican si los modificás)', expanded=False):
            for grupo, mets in GRUPOS_METRICAS.items():
                if grupo.startswith('🏦'):
                    continue
                st.markdown(f'<div style="font-size:11px;color:#6CC24A;font-weight:700;margin-top:8px">'
                            f'{grupo.upper()}</div>', unsafe_allow_html=True)
                cols = st.columns(4)
                for i, (label, col, tipo) in enumerate(mets):
                    if col not in df.columns or df[col].notna().sum() == 0:
                        continue
                    mult = 100 if tipo == 'pct' else 1
                    lo_d = float(np.floor(df[col].min() * mult * 10) / 10)
                    hi_d = float(np.ceil(df[col].max() * mult * 10) / 10)
                    with cols[i % 4]:
                        st.caption(label + (' %' if tipo == 'pct' else ''))
                        a, b = st.columns(2)
                        lo = a.number_input('Mín', value=lo_d, key=f'ffs_lo_{col}', label_visibility='collapsed', format='%.2f')
                        hi = b.number_input('Máx', value=hi_d, key=f'ffs_hi_{col}', label_visibility='collapsed', format='%.2f')
                    if (lo, hi) != (lo_d, hi_d):
                        d = d[(d[col] * mult).between(lo, hi)]

    d = d.sort_values(['F-Score', 'Score combinado'], ascending=False)

    # KPIs
    _kpi_cards([
        ('Empresas', str(len(d)), f'de {len(df)} cargadas', '#3a7bd5'),
        ('🟢 F-Score ≥ 8', str(int((d['F-Score'] >= 8).sum())), 'Calidad fuerte', '#3fb950'),
        ('🟡 F-Score 5-8', str(int(d['F-Score'].between(5, 7.99).sum())), 'Calidad mixta', '#e3b341'),
        ('🔴 F-Score < 5', str(int((d['F-Score'] < 5).sum())), 'Señales de alerta', '#f85149'),
    ])

    # Tabla de display
    out = pd.DataFrame({
        'Ticker': d['Ticker'], 'Nombre': d.get('Nombre'), 'Sector': d['Sectores'],
        'F-Score': d['F-Score'], 'Crit.': d.get('Criterios evaluados'),
        'Score fund.': d.get('Score fundamental (0-10)'), 'Score comb.': d.get('Score combinado'),
        'Veredicto': d.get('Veredicto'),
    })
    for nombre, col, *_ in CRITERIOS:
        if col in d.columns:
            out[nombre] = d[col].apply(_chk)
    mets = [(l, c, t) for g, ms in GRUPOS_METRICAS.items() for l, c, t in ms]
    if not avanzado:
        mets = [(l, c, t) for l, c, t in mets if c in ('precio', 'per', 'roe', 'revenue_growth', 'alza_ytd', 'market_cap')]
        out['Precio'] = d['precio'].apply(_fmt_precio) if 'precio' in d.columns else 'S/D'
    else:
        out['Precio'] = d['precio'].apply(_fmt_precio) if 'precio' in d.columns else 'S/D'
        for extra in ('Score calidad', 'Score valoración', 'Score crecimiento', 'Score riesgo'):
            if extra in d.columns:
                out[extra] = d[extra]
    for l, c, t in mets:
        if c in d.columns:
            out[l] = d[c].apply(lambda v, t=t: _fmt(v, t))
    if 'recommendation' in d.columns and avanzado:
        out['Analistas'] = d['recommendation'].fillna('N/D')

    if not avanzado:  # vista simple: solo lo esencial
        simple = ['Ticker', 'Nombre', 'Sector', 'F-Score', 'Score comb.', 'Veredicto', 'Precio', 'PER', 'ROE', 'Alza YTD %']
        out = out[[c for c in simple if c in out.columns]]

    st.caption('↔️ Deslizá horizontalmente para ver todas las columnas.' if avanzado else
               '💡 Vista simple. Activá el modo avanzado para ver los 9 criterios y todos los ratios.')
    st.dataframe(_estilizar(out, cols_f=['F-Score'], cols_s10=['Score fund.', 'Score comb.', 'Score calidad',
                                                              'Score valoración', 'Score crecimiento'],
                            cols_ver=['Veredicto'], cols_chk=NOMBRES_CRIT)
                 .format({'F-Score': '{:.2f}', 'Score fund.': '{:.1f}', 'Score comb.': '{:.1f}'}, na_rep='N/D'),
                 use_container_width=True, hide_index=True,
                 height=min(700, max(200, len(out) * 35 + 45)))

    # Gráfico F-Score vs Score fundamental
    if len(d) >= 2 and 'Score fundamental (0-10)' in d.columns:
        fig = go.Figure(go.Scatter(
            x=d['F-Score'], y=d['Score fundamental (0-10)'], mode='markers+text', text=d['Ticker'],
            textposition='top center', textfont=dict(size=10, color='#b0bcd0'),
            marker=dict(size=14, color=d['Score combinado'], colorscale='RdYlGn', cmin=0, cmax=10,
                        colorbar=dict(title='Comb.'), line=dict(width=1, color='#07090f')),
            hovertemplate='%{text}<br>F-Score %{x:.1f}<br>Fund. %{y:.1f}<extra></extra>'))
        fig.update_layout(plot_bgcolor='#0d1117', paper_bgcolor='#07090f', font=dict(color='#b0bcd0'),
                          title=dict(text='Calidad contable (F-Score) vs. Score fundamental', font=dict(color='#e6edf3', size=13)),
                          xaxis=dict(title='F-Score (0-9)', gridcolor='#21262d', range=[-0.3, 9.5]),
                          yaxis=dict(title='Score fundamental (0-10)', gridcolor='#21262d'),
                          height=420, margin=dict(l=10, r=10, t=45, b=10), dragmode=False)
        st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG, key='ffs_scatter')

    st.download_button('⬇️ Descargar tabla filtrada (CSV)', data=d.to_csv(index=False).encode('utf-8'),
                       file_name='fundamental_fscore_filtrado.csv', mime='text/csv', key='ffs_dl_filtrado')
    return d


# ---------------------------------------------------------------
#  TAB 2 — FICHA POR EMPRESA
# ---------------------------------------------------------------
def _lista_pipes(txt):
    return [s.strip() for s in str(txt or '').split('|') if s.strip()]


def _ficha(df):
    etiquetas = {f"{r.Ticker} · {r.Nombre or ''} ({r.Sectores})": i for i, r in df.iterrows()}
    ticker_pre = st.session_state.get('ffs_ticker_ficha')
    keys = list(etiquetas.keys())
    idx = next((i for i, k in enumerate(keys) if k.startswith(f'{ticker_pre} ·')), 0) if ticker_pre else 0
    sel = st.selectbox('Empresa', keys, index=idx, key='ffs_ficha_sel')
    r = df.loc[etiquetas[sel]].to_dict()
    g = lambda k, t='num': _fmt(r.get(k), t)

    ver = r.get('Veredicto') or 'N/D'
    col_ver = COLOR_VEREDICTO.get(ver, '#8b949e')
    st.markdown(f"""
    <div style="background:#0d1117;border:1px solid #21262d;border-top:2px solid #3a7bd5;border-radius:12px;
         padding:18px 24px;margin:8px 0 14px 0;text-align:center">
      <div style="font-size:17px;font-weight:700;color:#e6edf3">{r.get('Nombre') or r['Ticker']}
        <span style="color:#6b7d9a;font-size:12px">({r['Ticker']})</span></div>
      <div style="font-size:12px;color:#f5f7fa;margin-top:2px">
        {r.get('Sectores') or ''} · {r.get('industria_yahoo') or ''} · {r.get('pais') or ''}</div>
      <div style="font-size:11px;color:#6b7d9a;margin-top:6px">
        Datos {r.get('Base de datos') or ''} · último período {r.get('Último período') or 'N/D'}
        vs. {r.get('Comparado con') or 'N/D'}</div>
    </div>""", unsafe_allow_html=True)

    for aviso in _lista_pipes(r.get('Avisos')):
        st.info(f'ℹ️ {aviso}')

    fs = r.get('F-Score')
    _kpi_cards([
        ('F-Score', f'{fs:.1f}/9' if not _nd(fs) else 'N/D', f"{int(r.get('Criterios evaluados') or 0)} de 9 criterios evaluados",
         _color_fscore(fs).split('color:')[-1].split(';')[0] if not _nd(fs) else '#8b949e'),
        ('Score combinado', g('Score combinado'), f"Fundamental {g('Score fundamental (0-10)')}/10", '#3a7bd5'),
        ('Veredicto', ver, f"Sin compuerta: {r.get('Veredicto sin compuerta') or 'N/D'}", col_ver),
        ('Precio', _fmt_precio(r.get('precio')), f"Objetivo {_fmt_precio(r.get('target_price'))} · {r.get('recommendation') or 'N/D'}", '#e3b341'),
    ])

    m1, m2, m3, m4 = st.columns(4)
    m1.metric('⭐ Calidad', f"{g('Score calidad')}/10")
    m2.metric('💰 Valoración', f"{g('Score valoración')}/10")
    m3.metric('📈 Crecimiento', f"{g('Score crecimiento')}/10")
    m4.metric('⚠️ Riesgo', f"{g('Score riesgo')}/10")

    # F-Score por criterio
    st.markdown('#### 🧮 Los 9 criterios de Piotroski')
    filas = []
    for nombre, ccrit, desc, c_act, c_prev, tipo in CRITERIOS:
        act, prev = r.get(c_act) if c_act else None, r.get(c_prev) if c_prev else None
        if nombre.startswith('C6') or nombre.startswith('C9'):
            prev_txt = '1.00x (umbral)'
        else:
            prev_txt = _fmt(prev, tipo)
        filas.append({'Criterio': nombre, 'Qué mide': desc, 'Actual': _fmt(act, tipo),
                      'Referencia': prev_txt, 'Resultado': _chk(r.get(ccrit))})
    st.dataframe(_estilizar(pd.DataFrame(filas), cols_chk=['Resultado']), use_container_width=True,
                 hide_index=True, height=9 * 36 + 45)
    st.caption('— = no evaluable (dato faltante). El F-Score se escala a base 9 según los criterios evaluados. '
               'C4 compara OCF contra utilidad neta del mismo período.')

    # Semáforo
    sem = _semaforo(r)
    if sem:
        st.markdown('#### 🚦 Semáforo fundamental')
        html = ''.join(
            f'<tr style="border-bottom:1px solid #21262d"><td style="padding:8px 14px;text-align:left;color:#e6edf3;font-size:13px">'
            f'{em} {n}</td><td style="padding:8px 14px;text-align:right;font-weight:700;font-size:13px;'
            f'color:{COLOR_EMOJI.get(em, "#8b949e")}">{lb}</td></tr>' for n, em, lb in sem)
        st.markdown(f'<div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;overflow:hidden">'
                    f'<table style="width:100%;border-collapse:collapse">{html}</table></div>', unsafe_allow_html=True)

    # Señales
    pos, alt = _lista_pipes(r.get('Señales positivas')), _lista_pipes(r.get('Señales alerta'))
    cs1, cs2 = st.columns(2)
    with cs1:
        st.markdown('<div style="font-size:11px;font-weight:700;color:#3fb950;margin:10px 0 4px 0">✅ SEÑALES POSITIVAS</div>', unsafe_allow_html=True)
        for m in pos:
            st.markdown(f'<div style="font-size:11px;color:#3fb950;padding:2px 0;border-bottom:1px solid #21262d">• {m}</div>', unsafe_allow_html=True)
    with cs2:
        st.markdown('<div style="font-size:11px;font-weight:700;color:#f85149;margin:10px 0 4px 0">⚠️ ALERTAS</div>', unsafe_allow_html=True)
        for m in alt:
            st.markdown(f'<div style="font-size:11px;color:#f85149;padding:2px 0;border-bottom:1px solid #21262d">• {m}</div>', unsafe_allow_html=True)

    # Todos los datos por categoría
    st.markdown('#### 📋 Todos los datos')
    tabs = st.tabs(list(GRUPOS_METRICAS.keys()))
    for tab, (grupo, mets) in zip(tabs, GRUPOS_METRICAS.items()):
        with tab:
            cols = st.columns(4)
            for i, (label, col, tipo) in enumerate(mets):
                cols[i % 4].metric(label, _fmt(r.get(col), tipo))
    mon = r.get('moneda_cotizacion') or ''
    st.caption(f'Montos en {mon}. Fuente: archivo CSV cargado (sin consulta a Yahoo Finance).')

    # Cross-link opcional hacia el Buscador de la app
    if st.button(f"🔍 Abrir {r['Ticker']} en el Buscador (precio, técnico, estados)", key='ffs_goto_buscador'):
        st.session_state['ticker_from_table'] = r['Ticker']
        st.session_state['nav_horizonte'] = 'buscador'
        st.session_state['nav_modulo'] = 'buscador'
        st.rerun()


# ---------------------------------------------------------------
#  TAB 3 — COMPARADOR
# ---------------------------------------------------------------
def _comparar(df, PLOTLY_CONFIG):
    tickers = df['Ticker'].tolist()
    defecto = df.sort_values('Score combinado', ascending=False)['Ticker'].head(3).tolist()
    sel = st.multiselect('Elegí de 2 a 5 empresas', tickers, default=defecto, max_selections=5, key='ffs_comp_sel')
    if len(sel) < 2:
        st.info('Elegí al menos 2 empresas.')
        return
    sub = df[df['Ticker'].isin(sel)].drop_duplicates('Ticker').set_index('Ticker').loc[sel]

    filas, mejores = [], {}
    for label, col, tipo, mejor in METRICAS_COMPARAR:
        if col not in sub.columns:
            continue
        vals = pd.to_numeric(sub[col], errors='coerce')
        filas.append({'Métrica': label, **{t: _fmt(vals[t], tipo) for t in sel}})
        if mejor and vals.notna().sum() >= 2:
            mejores[label] = vals.idxmin() if mejor == 'menor' else vals.idxmax()
    tabla = pd.DataFrame(filas).set_index('Métrica')
    tabla.loc['Veredicto'] = [sub.loc[t, 'Veredicto'] for t in sel]

    def _resaltar(fila):
        return ['background-color:#0d2410;color:#3fb950;font-weight:700' if mejores.get(fila.name) == t else ''
                for t in fila.index]
    st.dataframe(tabla.style.apply(_resaltar, axis=1)
                 .set_properties(**{'background-color': '#0d1117', 'color': '#e6edf3', 'border': '1px solid #21262d'})
                 .set_table_styles([{'selector': 'th', 'props': [('background-color', '#161b22'), ('color', '#e6edf3'),
                                     ('border-bottom', '2px solid #3a7bd5'), ('font-size', '11px')]},
                                    {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]}]),
                 use_container_width=True, height=min(900, len(tabla) * 36 + 45))
    st.caption('🟢 = mejor valor del grupo (menor es mejor en múltiplos, deuda, beta y riesgo).')

    # Radar
    ejes = [('Calidad', 'Score calidad'), ('Valoración', 'Score valoración'),
            ('Crecimiento', 'Score crecimiento'), ('Seguridad', None), ('F-Score', 'F-Score')]
    paleta = ['#6CC24A', '#3a7bd5', '#f0883e', '#bc8cff', '#e3b341']
    fig = go.Figure()
    for i, t in enumerate(sel):
        vals = []
        for nombre, col in ejes:
            if nombre == 'Seguridad':
                v = sub.loc[t, 'Score riesgo']; vals.append(10 - v if not _nd(v) else 0)
            elif nombre == 'F-Score':
                v = sub.loc[t, 'F-Score']; vals.append(v / 9 * 10 if not _nd(v) else 0)
            else:
                v = sub.loc[t, col]; vals.append(v if not _nd(v) else 0)
        fig.add_trace(go.Scatterpolar(r=vals + vals[:1], theta=[e[0] for e in ejes] + [ejes[0][0]],
                                      fill='toself', name=t, opacity=.55,
                                      line=dict(color=paleta[i % 5], width=2), fillcolor=paleta[i % 5]))
    fig.update_layout(plot_bgcolor='#0d1117', paper_bgcolor='#07090f', font=dict(color='#b0bcd0'),
                      polar=dict(bgcolor='#0d1117', radialaxis=dict(range=[0, 10], gridcolor='#21262d'),
                                 angularaxis=dict(gridcolor='#21262d')),
                      title=dict(text='Perfil comparado (0-10) · Seguridad = 10 − Score riesgo', font=dict(color='#e6edf3', size=13)),
                      height=440, legend=dict(orientation='h', y=-0.1), margin=dict(l=40, r=40, t=50, b=40), dragmode=False)
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG, key='ffs_radar')

    # Criterios lado a lado
    st.markdown('##### 🧮 Criterios de Piotroski lado a lado')
    crit = pd.DataFrame({'Criterio': NOMBRES_CRIT})
    for t in sel:
        crit[t] = [_chk(sub.loc[t, c[1]]) if c[1] in sub.columns else '—' for c in CRITERIOS]
    st.dataframe(_estilizar(crit, cols_chk=sel), use_container_width=True, hide_index=True, height=9 * 36 + 45)


# ---------------------------------------------------------------
#  TAB 4 — CARGA DE DATOS
# ---------------------------------------------------------------
def _cargar_datos(df, client, puede_cargar):
    if df is not None:
        per = df['Último período'].dropna().unique() if 'Último período' in df.columns else []
        st.success(f"✅ {len(df)} filas · {df['Ticker'].nunique()} tickers · sectores: "
                   f"{', '.join(sorted(df['Sectores'].dropna().unique()))}"
                   + (f" · períodos: {', '.join(sorted(map(str, per))[:4])}" if len(per) else ''))
    if not puede_cargar:
        st.info('Solo el administrador puede cargar o reemplazar los datos.')
        return

    archivos = st.file_uploader('Subí uno o varios CSV (uno por sector sirve)', type=['csv'],
                                accept_multiple_files=True, key='ffs_uploader')
    modo = st.radio('Si ya hay datos cargados', ['Agregar / actualizar empresas', 'Reemplazar todo'],
                    horizontal=True, key='ffs_modo_carga')
    persistir = st.checkbox('Guardar también en Supabase (para que lo vean todos los usuarios)',
                            value=client is not None, disabled=client is None, key='ffs_persistir')

    if archivos and st.button('📥 Procesar archivos', type='primary', key='ffs_procesar'):
        nuevo = None
        for f in archivos:
            try:
                nuevo = combinar(nuevo, leer_csv(f))
                st.write(f'✔️ {f.name}: leído correctamente')
            except Exception as e:
                st.error(f'❌ {f.name}: {e}')
        if nuevo is not None and not nuevo.empty:
            base = None if modo.startswith('Reemplazar') else df
            final = combinar(base, nuevo)
            st.session_state['ffs_df'] = final
            if persistir:
                if modo.startswith('Reemplazar'):
                    borrar_de_supabase(client)
                ok, msg = guardar_en_supabase(client, final if modo.startswith('Reemplazar') else nuevo)
                (st.success if ok else st.warning)(msg)
            st.rerun()

    if df is not None:
        cA, cB = st.columns(2)
        cA.download_button('⬇️ Descargar base unificada (CSV)', df.to_csv(index=False).encode('utf-8'),
                           'base_fundamental_fscore.csv', 'text/csv', key='ffs_dl_base')
        if cB.button('🗑️ Vaciar datos de esta sesión', key='ffs_vaciar'):
            st.session_state.pop('ffs_df', None)
            st.session_state['ffs_supabase_intentado'] = True
            st.rerun()


# ---------------------------------------------------------------
#  PUNTO DE ENTRADA
# ---------------------------------------------------------------
def modulo_fundamental_fscore(supabase=None, puede_cargar=True, PLOTLY_CONFIG=None):
    PLOTLY_CONFIG = PLOTLY_CONFIG or dict(displayModeBar=False, scrollZoom=False)

    st.markdown("""
    <div style="background:linear-gradient(135deg,#151d0d 0%,#0f2410 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #3fb950; border-radius:14px;
         padding:22px 28px; margin-bottom:20px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:4px">
        📊 Fundamental + F-Score (Piotroski) — desde CSV
      </div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.6">
        Ranking, ficha por empresa y comparador usando <b style="color:#e6edf3">solo el archivo CSV</b>:
        no se consulta Yahoo Finance, así que es instantáneo y no hay límites de uso.
      </div>
    </div>""", unsafe_allow_html=True)

    df = obtener_base(supabase)

    if df is None or df.empty:
        st.warning('Todavía no hay datos cargados.')
        _cargar_datos(None, supabase, puede_cargar)
        return

    t_rank, t_ficha, t_comp, t_datos = st.tabs(['🏭 Ranking', '🔍 Ficha por empresa', '⚖️ Comparar', '📥 Datos'])
    with t_rank:
        d_filtrado = _tabla_ranking(df, PLOTLY_CONFIG)
        if len(d_filtrado):
            st.caption('Para ver el detalle de una empresa, elegila en la pestaña "Ficha por empresa".')
    with t_ficha:
        _ficha(df)
    with t_comp:
        _comparar(df, PLOTLY_CONFIG)
    with t_datos:
        _cargar_datos(df, supabase, puede_cargar)


# ==============================================================
#  SQL para Supabase (opcional, solo si querés persistir el CSV)
# ==============================================================
#   create table if not exists fundamental_csv (
#       id             text primary key,        -- 'TICKER|Sector'
#       ticker         text not null,
#       sectores       text,
#       datos          jsonb not null,
#       actualizado_en timestamptz default now()
#   );
#   alter table fundamental_csv enable row level security;  -- la app usa service_role
# ==============================================================
