# ==============================================================
#  MÓDULO COT (Commitment of Traders) — Análisis de Posicionamiento
#  100% basado en datos cargados manualmente por el usuario.
#  NO descarga datos de CFTC. NO usa precio. NO usa internet.
#
#  Cómo integrarlo a tu app principal (analizador.py):
#
#    from modulo_cot import modulo_cot
#
#    # en el diccionario de módulos de navegación (por ejemplo dentro
#    # de _TRADING_MAP, junto a Rotación/Señales/Opciones) agregá:
#    #   '📑 Análisis COT': ('cot', 'cot')
#
#    # y en el bloque de renderizado de módulos (elif MODULO == ...):
#    elif MODULO == 'cot':
#        modulo_cot()
#
#  El módulo reutiliza las clases CSS globales ya definidas en tu
#  app (.kpi-card, .interp-card, .sec-title, .signal-pill, etc.),
#  por eso no vuelve a inyectar CSS propio.
# ==============================================================

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

# ------------------------------------------------------------------
#  PALETA — coherente con el resto de Capital+
# ------------------------------------------------------------------
C_GREEN   = '#3fb950'
C_LGREEN  = '#7ee787'
C_YELLOW  = '#e3b341'
C_LRED    = '#f0883e'
C_RED     = '#f85149'
C_MUTED   = '#6b7d9a'
C_TEXT    = '#e6edf3'
C_ACENT   = '#3a7bd5'
C_MONSTER = '#6CC24A'
C_GRID    = '#21262d'
C_BG1     = '#0d1117'
C_BG2     = '#07090f'

PLOTLY_LAYOUT_BASE = dict(
    plot_bgcolor=C_BG1, paper_bgcolor=C_BG2,
    font=dict(color='#b0bcd0', family='Inter, sans-serif'),
    dragmode=False,
)
PLOTLY_CONFIG = dict(displayModeBar=False, scrollZoom=False)

# ------------------------------------------------------------------
#  ESTRUCTURA DE DATOS
# ------------------------------------------------------------------

COT_COLUMNAS = [
    'Report Date', 'Commodity', 'Open Interest',
    'Producer/Merchant Long', 'Producer/Merchant Short', 'Producer/Merchant Spread',
    'Swap Dealers Long', 'Swap Dealers Short', 'Swap Dealers Spread',
    'Managed Money Long', 'Managed Money Short', 'Managed Money Spread',
    'Other Reportables Long', 'Other Reportables Short', 'Other Reportables Spread',
]

COT_COLUMNAS_NUMERICAS = [c for c in COT_COLUMNAS if c not in ('Report Date', 'Commodity')]


def _cot_template_df():
    return pd.DataFrame(columns=COT_COLUMNAS)


def _cot_init_state():
    if 'cot_data' not in st.session_state:
        st.session_state['cot_data'] = _cot_template_df()


def _cot_normalizar(df):
    """Convierte tipos, ordena y descarta filas sin fecha o sin commodity."""
    df = df.copy()
    if df.empty:
        return df
    df['Report Date'] = pd.to_datetime(df['Report Date'], errors='coerce')
    df['Commodity'] = df['Commodity'].astype(str).str.strip()
    for c in COT_COLUMNAS_NUMERICAS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        else:
            df[c] = np.nan
    df = df.dropna(subset=['Report Date'])
    df = df[df['Commodity'].str.len() > 0]
    df = df.sort_values(['Commodity', 'Report Date']).reset_index(drop=True)
    return df


def _cot_merge(df_existente, df_nuevo):
    """Combina datos nuevos con los existentes, reemplazando duplicados
    de la misma pareja (Commodity, Report Date) por el valor más reciente
    cargado (permite corregir una semana ya ingresada)."""
    df_nuevo = _cot_normalizar(df_nuevo)
    if df_nuevo.empty:
        return df_existente
    combinado = pd.concat([df_existente, df_nuevo], ignore_index=True)
    combinado = combinado.drop_duplicates(subset=['Commodity', 'Report Date'], keep='last')
    combinado = combinado.sort_values(['Commodity', 'Report Date']).reset_index(drop=True)
    return combinado


# ------------------------------------------------------------------
#  CÁLCULOS — SOLO CON DATOS COT (nunca precio)
# ------------------------------------------------------------------

def _cot_calcular_serie(df_commodity):
    """Recibe todas las semanas de UN commodity, ya ordenadas, y agrega
    las columnas derivadas necesarias para el análisis."""
    df = df_commodity.sort_values('Report Date').reset_index(drop=True).copy()

    df['MM Net'] = df['Managed Money Long'] - df['Managed Money Short']
    df['MM Net Chg'] = df['MM Net'].diff()
    df['MM Long Chg'] = df['Managed Money Long'].diff()
    df['MM Short Chg'] = df['Managed Money Short'].diff()
    df['OI Chg'] = df['Open Interest'].diff()

    df['Swap Net'] = df['Swap Dealers Long'] - df['Swap Dealers Short']
    df['Other Net'] = df['Other Reportables Long'] - df['Other Reportables Short']
    # Producer/Merchant se muestra como contexto (hedging), nunca como señal direccional
    df['Producer Net'] = df['Producer/Merchant Long'] - df['Producer/Merchant Short']

    return df


def _cot_interp_cambio_semanal(delta_long, delta_short):
    if pd.isna(delta_long) or pd.isna(delta_short):
        return None
    if delta_long > 0 and delta_short < 0:
        return 'ACUMULACIÓN ALCISTA FUERTE'
    if delta_long > 0 and delta_short > 0:
        return 'POSICIONAMIENTO MIXTO'
    if delta_long < 0 and delta_short > 0:
        return 'DISTRIBUCIÓN / POSICIONAMIENTO BAJISTA FUERTE'
    if delta_long < 0 and delta_short < 0:
        return 'REDUCCIÓN DE EXPOSICIÓN / CIERRE DE POSICIONES'
    if delta_long == 0 and delta_short == 0:
        return 'SIN CAMBIOS SIGNIFICATIVOS'
    if delta_long > 0 and delta_short == 0:
        return 'AUMENTANDO EXPOSICIÓN ALCISTA'
    if delta_long < 0 and delta_short == 0:
        return 'REDUCIENDO EXPOSICIÓN ALCISTA'
    if delta_long == 0 and delta_short > 0:
        return 'AUMENTANDO EXPOSICIÓN BAJISTA'
    if delta_long == 0 and delta_short < 0:
        return 'CERRANDO POSICIONES BAJISTAS'
    return 'NEUTRALES'


def _cot_interp_oi(delta_net, delta_oi):
    """Devuelve (texto probabilístico, etiqueta corta). Nunca certeza."""
    if pd.isna(delta_net) or pd.isna(delta_oi):
        return None, None
    if delta_net > 0 and delta_oi > 0:
        return ('Probable entrada de exposición alcista / acumulación potencial.', 'alcista')
    if delta_net < 0 and delta_oi > 0:
        return ('Probable aumento de exposición bajista / distribución potencial.', 'bajista')
    if delta_net > 0 and delta_oi < 0:
        return ('Podría tratarse de un cierre de posiciones bajistas (short covering).', 'cierre_bajista')
    if delta_net < 0 and delta_oi < 0:
        return ('Podría tratarse de un cierre de posiciones alcistas (long liquidation).', 'cierre_alcista')
    return ('Sin variación conjunta relevante entre Net y Open Interest.', 'neutral')


def _cot_tendencia(net_series, min_semanas=3):
    """Tendencia del Managed Money Net en las últimas semanas (pendiente lineal)."""
    s = net_series.dropna()
    if len(s) < min_semanas:
        return None
    x = np.arange(len(s))
    pendiente = np.polyfit(x, s.values, 1)[0]
    umbral = s.std() * 0.15 if s.std() > 0 else 0
    if pendiente > umbral:
        return 'ALCISTA'
    if pendiente < -umbral:
        return 'BAJISTA'
    return 'LATERAL'


def _cot_percentil(net_series, min_semanas=5):
    s = net_series.dropna()
    if len(s) < min_semanas:
        return None
    valor = s.iloc[-1]
    pct = float((s < valor).sum()) / len(s) * 100
    return round(pct, 1)


def _cot_clasificar_percentil(pct):
    if pct is None:
        return 'INSUFFICIENT HISTORY', C_MUTED
    if pct <= 10:
        return 'EXTREME SHORT', C_RED
    if pct <= 30:
        return 'LOW POSITIONING', C_LRED
    if pct <= 70:
        return 'NORMAL', C_YELLOW
    if pct <= 90:
        return 'HIGH POSITIONING', C_LGREEN
    return 'EXTREME LONG', C_GREEN


def _cot_consistencia(net_series, lookback=4):
    """Fracción de semanas recientes que se movieron en la misma dirección."""
    diffs = net_series.diff().dropna().tail(lookback)
    if len(diffs) < 2:
        return None
    signos = np.sign(diffs.values)
    signos = signos[signos != 0]
    if len(signos) == 0:
        return 0.5
    return max((signos > 0).sum(), (signos < 0).sum()) / len(signos)


def _cot_oi_confirmacion_score(oi_tag):
    """Traduce la interpretación conjunta Net+OI (_cot_interp_oi) a un
    puntaje 0-100 para el COT Score. Confirma o modera la señal según
    si el Open Interest acompaña (o no) el movimiento del Net.
    - 'alcista'        -> Net sube y OI sube: confirmación fuerte alcista
    - 'bajista'        -> Net baja y OI sube: confirmación fuerte bajista
    - 'cierre_bajista' -> Net sube y OI baja: short covering, sesgo leve alcista
    - 'cierre_alcista' -> Net baja y OI baja: long liquidation, sesgo leve bajista
    - 'neutral'         -> sin variación conjunta relevante
    """
    mapa = {
        'alcista': 80,
        'bajista': 20,
        'cierre_bajista': 60,
        'cierre_alcista': 40,
        'neutral': 50,
    }
    return mapa.get(oi_tag)


def _cot_score(fila_actual, net_series, pct, tendencia, consistencia, oi_tag=None):
    """COT Score 0-100. Combina únicamente variables derivadas del COT:
    Managed Money Net (vía percentil), Cambio semanal del Net, Tendencia,
    Relación Long/Short, Open Interest y su cambio semanal (vía confirmación
    Net+OI), Percentil del posicionamiento y Consistencia."""
    long_ = fila_actual.get('Managed Money Long')
    short_ = fila_actual.get('Managed Money Short')
    ratio_ls = None
    if pd.notna(long_) and pd.notna(short_) and (long_ + short_) > 0:
        ratio_ls = long_ / (long_ + short_) * 100

    componentes, pesos = [], []

    if pct is not None:
        componentes.append(pct); pesos.append(0.30)
    if tendencia is not None:
        t_score = {'ALCISTA': 80, 'LATERAL': 50, 'BAJISTA': 20}[tendencia]
        componentes.append(t_score); pesos.append(0.18)

    net_chg = fila_actual.get('MM Net Chg')
    if pd.notna(net_chg):
        s = net_series.diff().dropna()
        std_chg = s.std() if len(s) > 1 else 0
        if std_chg and std_chg > 0:
            z = net_chg / std_chg
            chg_score = max(0, min(100, 50 + z * 20))
        else:
            chg_score = 50
        componentes.append(chg_score); pesos.append(0.13)

    if consistencia is not None:
        componentes.append(consistencia * 100); pesos.append(0.13)
    if ratio_ls is not None:
        componentes.append(ratio_ls); pesos.append(0.13)

    # Open Interest + su cambio semanal, vía la confirmación Net+OI
    oi_score = _cot_oi_confirmacion_score(oi_tag)
    if oi_score is not None:
        componentes.append(oi_score); pesos.append(0.13)

    if not componentes:
        return None
    total_peso = sum(pesos)
    return round(sum(c * p for c, p in zip(componentes, pesos)) / total_peso, 1)


def _cot_clasificar_score(score):
    if score is None:
        return 'N/A', C_MUTED, '⚪'
    if score <= 20:
        return 'MUY BAJISTA', C_RED, '🔴'
    if score <= 40:
        return 'BAJISTA', C_LRED, '🟠'
    if score <= 60:
        return 'NEUTRAL', C_YELLOW, '🟡'
    if score <= 80:
        return 'ALCISTA', C_LGREEN, '🟢'
    return 'MUY ALCISTA', C_GREEN, '💚'


def _cot_señal_final(score, cambio_interp, pct_class):
    if score is None:
        return 'DATOS INSUFICIENTES'
    label, _, _ = _cot_clasificar_score(score)
    extremo = pct_class in ('EXTREME LONG', 'EXTREME SHORT')

    if label == 'MUY ALCISTA' and extremo:
        return 'POSICIONAMIENTO EXTREMO ALCISTA'
    if label == 'MUY BAJISTA' and extremo:
        return 'POSICIONAMIENTO EXTREMO BAJISTA'
    if cambio_interp == 'ACUMULACIÓN ALCISTA FUERTE' and label in ('ALCISTA', 'MUY ALCISTA'):
        return 'FUERTE ACUMULACIÓN ALCISTA'
    if cambio_interp == 'DISTRIBUCIÓN / POSICIONAMIENTO BAJISTA FUERTE' and label in ('BAJISTA', 'MUY BAJISTA'):
        return 'FUERTE POSICIONAMIENTO BAJISTA'
    if label == 'ALCISTA':
        if cambio_interp in ('ACUMULACIÓN ALCISTA FUERTE', 'AUMENTANDO EXPOSICIÓN ALCISTA'):
            return 'ACUMULACIÓN ALCISTA MODERADA'
        return 'POSICIONAMIENTO ALCISTA'
    if label == 'BAJISTA':
        if cambio_interp in ('DISTRIBUCIÓN / POSICIONAMIENTO BAJISTA FUERTE', 'AUMENTANDO EXPOSICIÓN BAJISTA'):
            return 'DISTRIBUCIÓN MODERADA'
        return 'POSICIONAMIENTO BAJISTA'
    if cambio_interp == 'REDUCCIÓN DE EXPOSICIÓN / CIERRE DE POSICIONES':
        return 'CIERRE DE POSICIONES'
    return 'POSICIONAMIENTO NEUTRAL'


def _cot_texto_interpretacion(commodity, fila_actual, tendencia, pct, pct_class, oi_texto, n_semanas):
    partes = []
    net = fila_actual.get('MM Net')
    net_chg = fila_actual.get('MM Net Chg')
    oi = fila_actual.get('Open Interest')
    oi_chg = fila_actual.get('OI Chg')

    if pd.notna(net):
        signo = 'alcista' if net >= 0 else 'bajista'
        partes.append(f"Los Managed Money mantienen un posicionamiento neto {signo} de {net:,.0f} contratos.")

    if pd.notna(net_chg):
        direccion = 'aumentaron' if net_chg > 0 else ('redujeron' if net_chg < 0 else 'mantuvieron sin cambios')
        partes.append(f"En la última semana {direccion} su exposición neta ({net_chg:+,.0f}).")

    if n_semanas == 1:
        partes.append("Solo hay una semana cargada: no se puede calcular tendencia ni percentil.")
    elif n_semanas == 2:
        partes.append("Con solo dos semanas cargadas, el historial es insuficiente para evaluar tendencia o extremos de posicionamiento.")
    else:
        if tendencia:
            partes.append(f"La tendencia del posicionamiento en las últimas semanas es {tendencia.lower()}.")
        if pct is not None:
            partes.append(f"El posicionamiento actual se ubica en el percentil {pct:.0f}% del historial disponible ({pct_class}).")
        else:
            partes.append("Historial insuficiente para calcular el percentil de posicionamiento (INSUFFICIENT HISTORY).")

    if pd.notna(oi_chg):
        direccion_oi = 'aumentó' if oi_chg > 0 else ('disminuyó' if oi_chg < 0 else 'se mantuvo estable')
        partes.append(f"El Open Interest {direccion_oi} en la semana ({oi_chg:+,.0f}).")
    if oi_texto:
        partes.append(oi_texto)

    partes.append("Esta lectura es probabilística y se basa exclusivamente en datos de posicionamiento COT, sin considerar precio.")
    return ' '.join(partes)


def _cot_resumen_commodity(df_commodity):
    """Procesa todas las semanas de un commodity y devuelve un dict con
    el resumen final + la serie completa (para graficar)."""
    df = _cot_calcular_serie(df_commodity)
    n = len(df)
    if n == 0:
        return None

    fila = df.iloc[-1]
    net_series = df['MM Net']

    tendencia = _cot_tendencia(net_series) if n >= 3 else None
    pct = _cot_percentil(net_series) if n >= 5 else None
    pct_class, pct_color = _cot_clasificar_percentil(pct)
    consistencia = _cot_consistencia(net_series) if n >= 3 else None
    cambio_interp = _cot_interp_cambio_semanal(fila.get('MM Long Chg'), fila.get('MM Short Chg'))
    oi_texto, oi_tag = _cot_interp_oi(fila.get('MM Net Chg'), fila.get('OI Chg'))
    score = _cot_score(fila, net_series, pct, tendencia, consistencia, oi_tag)
    score_label, score_color, score_emoji = _cot_clasificar_score(score)

    señal = _cot_señal_final(score, cambio_interp, pct_class)

    texto = _cot_texto_interpretacion(
        df_commodity['Commodity'].iloc[0], fila, tendencia, pct, pct_class, oi_texto, n
    )

    return dict(
        commodity=df_commodity['Commodity'].iloc[0],
        n_semanas=n,
        fecha=fila['Report Date'],
        mm_long=fila.get('Managed Money Long'),
        mm_short=fila.get('Managed Money Short'),
        mm_net=fila.get('MM Net'),
        mm_net_chg=fila.get('MM Net Chg'),
        oi=fila.get('Open Interest'),
        oi_chg=fila.get('OI Chg'),
        tendencia=tendencia,
        percentil=pct,
        pct_class=pct_class,
        pct_color=pct_color,
        cambio_interp=cambio_interp,
        oi_texto=oi_texto,
        score=score,
        score_label=score_label,
        score_color=score_color,
        score_emoji=score_emoji,
        señal_final=señal,
        texto=texto,
        df=df,
    )


# ------------------------------------------------------------------
#  HELPERS DE UI (reutilizan clases CSS ya definidas en la app)
# ------------------------------------------------------------------

def _fmt_n(v, dec=0):
    if v is None or pd.isna(v):
        return 'N/A'
    return f'{v:,.{dec}f}'


def _cot_kpi_cards(items):
    cols = st.columns(len(items))
    for col, (label, value, sub, color) in zip(cols, items):
        with col:
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-accent" style="background:{color}"></div>'
                f'<div class="kpi-label">{label}</div>'
                f'<div class="kpi-value">{value}</div>'
                f'<div class="kpi-sub">{sub}</div></div>',
                unsafe_allow_html=True,
            )
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)


def _cot_fig_evolucion(df, columna, titulo, color):
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df['Report Date'], y=df[columna], mode='lines+markers',
        line=dict(color=color, width=2.2), marker=dict(size=5),
        fill='tozeroy', fillcolor=f'rgba(58,123,213,0.08)',
    ))
    fig.add_hline(y=0, line_color=C_MUTED, opacity=0.4)
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE,
        title=dict(text=titulo, font=dict(color=C_TEXT, size=13)),
        xaxis=dict(gridcolor=C_GRID), yaxis=dict(gridcolor=C_GRID),
        height=320, margin=dict(l=10, r=10, t=45, b=10),
    )
    return fig


# ------------------------------------------------------------------
#  TAB 1 — CARGA DE DATOS
# ------------------------------------------------------------------

def _cot_tab_carga():
    st.markdown("""
    <div class="info-banner">
      Los datos NO se descargan automáticamente. Cargá vos las semanas de cada commodity
      con el formulario, la tabla editable o importando un CSV con las columnas exactas del reporte COT.
    </div>
    """, unsafe_allow_html=True)

    df_actual = st.session_state['cot_data']

    # ── Plantilla descargable ──────────────────────────────────
    c_tpl1, c_tpl2 = st.columns([3, 1])
    with c_tpl2:
        st.download_button(
            '⬇️ Descargar plantilla CSV',
            data=_cot_template_df().to_csv(index=False).encode('utf-8'),
            file_name='plantilla_cot.csv', mime='text/csv',
            use_container_width=True, key='cot_download_tpl',
        )

    st.markdown('<div class="sec-title">📝 Cargar una semana</div>', unsafe_allow_html=True)

    commodities_existentes = sorted(df_actual['Commodity'].unique().tolist()) if not df_actual.empty else []
    opciones_commodity = ['➕ Nuevo commodity'] + commodities_existentes
    sel_commodity = st.selectbox('Commodity', opciones_commodity, key='cot_sel_commodity')
    if sel_commodity == '➕ Nuevo commodity':
        nombre_commodity = st.text_input('Nombre del nuevo commodity', key='cot_nuevo_nombre', placeholder='Ej: GOLD, WTI, SOYBEANS')
    else:
        nombre_commodity = sel_commodity

    with st.form('cot_form_semana', clear_on_submit=False):
        c1, c2 = st.columns(2)
        with c1:
            fecha = st.date_input('Report Date', key='cot_fecha')
        with c2:
            oi = st.number_input('Open Interest', min_value=0.0, step=1.0, key='cot_oi')

        st.markdown('**Producer / Merchant**')
        p1, p2, p3 = st.columns(3)
        with p1: prod_l = st.number_input('Long', min_value=0.0, step=1.0, key='cot_prod_l')
        with p2: prod_s = st.number_input('Short', min_value=0.0, step=1.0, key='cot_prod_s')
        with p3: prod_sp = st.number_input('Spread', min_value=0.0, step=1.0, key='cot_prod_sp')

        st.markdown('**Swap Dealers**')
        s1, s2, s3 = st.columns(3)
        with s1: swap_l = st.number_input('Long ', min_value=0.0, step=1.0, key='cot_swap_l')
        with s2: swap_s = st.number_input('Short ', min_value=0.0, step=1.0, key='cot_swap_s')
        with s3: swap_sp = st.number_input('Spread ', min_value=0.0, step=1.0, key='cot_swap_sp')

        st.markdown('**Managed Money** (principal foco del análisis)')
        m1, m2, m3 = st.columns(3)
        with m1: mm_l = st.number_input('Long  ', min_value=0.0, step=1.0, key='cot_mm_l')
        with m2: mm_s = st.number_input('Short  ', min_value=0.0, step=1.0, key='cot_mm_s')
        with m3: mm_sp = st.number_input('Spread  ', min_value=0.0, step=1.0, key='cot_mm_sp')

        st.markdown('**Other Reportables**')
        o1, o2, o3 = st.columns(3)
        with o1: oth_l = st.number_input('Long   ', min_value=0.0, step=1.0, key='cot_oth_l')
        with o2: oth_s = st.number_input('Short   ', min_value=0.0, step=1.0, key='cot_oth_s')
        with o3: oth_sp = st.number_input('Spread   ', min_value=0.0, step=1.0, key='cot_oth_sp')

        enviado = st.form_submit_button('➕ Agregar semana', use_container_width=True)

    if enviado:
        if not nombre_commodity or not nombre_commodity.strip():
            st.error('Ingresá el nombre del commodity.')
        else:
            fila_nueva = pd.DataFrame([{
                'Report Date': pd.Timestamp(fecha), 'Commodity': nombre_commodity.strip(),
                'Open Interest': oi,
                'Producer/Merchant Long': prod_l, 'Producer/Merchant Short': prod_s, 'Producer/Merchant Spread': prod_sp,
                'Swap Dealers Long': swap_l, 'Swap Dealers Short': swap_s, 'Swap Dealers Spread': swap_sp,
                'Managed Money Long': mm_l, 'Managed Money Short': mm_s, 'Managed Money Spread': mm_sp,
                'Other Reportables Long': oth_l, 'Other Reportables Short': oth_s, 'Other Reportables Spread': oth_sp,
            }])
            st.session_state['cot_data'] = _cot_merge(st.session_state['cot_data'], fila_nueva)
            st.success(f'Semana del {fecha} agregada para {nombre_commodity.strip()}.')
            st.rerun()

    # ── Importar CSV propio ─────────────────────────────────────
    st.markdown('<div class="sec-title">📂 Importar CSV</div>', unsafe_allow_html=True)
    archivo = st.file_uploader('Subí un CSV con las columnas de la plantilla', type=['csv'], key='cot_uploader')
    if archivo is not None:
        try:
            df_csv = pd.read_csv(archivo)
        except Exception as e:
            st.error(f'No se pudo leer el archivo: {e}')
            df_csv = None
        if df_csv is not None:
            faltantes = [c for c in COT_COLUMNAS if c not in df_csv.columns]
            if faltantes:
                st.error(f'Faltan columnas requeridas: {", ".join(faltantes)}')
            else:
                st.dataframe(df_csv.head(10), use_container_width=True)
                if st.button('✅ Importar al dataset', key='cot_import_csv'):
                    st.session_state['cot_data'] = _cot_merge(st.session_state['cot_data'], df_csv[COT_COLUMNAS])
                    st.success(f'{len(df_csv)} filas importadas/actualizadas.')
                    st.rerun()

    # ── Editor de tabla completa ─────────────────────────────────
    st.markdown('<div class="sec-title">✏️ Editar datos cargados</div>', unsafe_allow_html=True)
    df_actual = st.session_state['cot_data']
    if df_actual.empty:
        st.info('Todavía no cargaste ninguna semana.')
        return

    df_editable = df_actual.copy()
    df_editable['Report Date'] = pd.to_datetime(df_editable['Report Date']).dt.date

    editado = st.data_editor(
        df_editable, use_container_width=True, num_rows='dynamic',
        key='cot_editor_tabla', height=min(500, max(150, len(df_editable) * 36 + 60)),
    )

    cg1, cg2 = st.columns(2)
    with cg1:
        if st.button('💾 Guardar cambios de la tabla', use_container_width=True, key='cot_guardar_tabla'):
            df_norm = _cot_normalizar(editado)
            st.session_state['cot_data'] = df_norm
            st.success('Cambios guardados.')
            st.rerun()
    with cg2:
        if st.button('🗑️ Borrar TODOS los datos cargados', use_container_width=True, key='cot_borrar_todo'):
            st.session_state['cot_data'] = _cot_template_df()
            st.warning('Se borraron todos los datos COT cargados.')
            st.rerun()


# ------------------------------------------------------------------
#  TAB 2 — ANÁLISIS GENERAL (tabla final)
# ------------------------------------------------------------------

def _cot_tab_general():
    df = st.session_state['cot_data']
    if df.empty:
        st.info('Cargá datos en la pestaña "Cargar Datos" para ver el análisis.')
        return

    resumenes = []
    for commodity, grupo in df.groupby('Commodity'):
        r = _cot_resumen_commodity(grupo)
        if r:
            resumenes.append(r)

    if not resumenes:
        st.warning('No se pudo procesar ningún commodity.')
        return

    n_alcista = sum(1 for r in resumenes if r['score'] is not None and r['score'] > 60)
    n_bajista = sum(1 for r in resumenes if r['score'] is not None and r['score'] < 40)
    n_extremo = sum(1 for r in resumenes if r['pct_class'] in ('EXTREME LONG', 'EXTREME SHORT'))

    _cot_kpi_cards([
        ('Commodities cargados', str(len(resumenes)), 'Con al menos 1 semana', C_ACENT),
        ('🟢 Sesgo alcista', str(n_alcista), 'COT Score > 60', C_GREEN),
        ('🔴 Sesgo bajista', str(n_bajista), 'COT Score < 40', C_RED),
        ('⚡ Extremos', str(n_extremo), 'Percentil ≤10% o ≥90%', C_YELLOW),
    ])

    filas = []
    for r in resumenes:
        filas.append({
            'Commodity': r['commodity'],
            'Fecha': r['fecha'].strftime('%Y-%m-%d') if pd.notna(r['fecha']) else 'N/A',
            'MM Long': _fmt_n(r['mm_long']),
            'MM Short': _fmt_n(r['mm_short']),
            'MM Net': _fmt_n(r['mm_net']),
            'Cambio Net': _fmt_n(r['mm_net_chg']),
            'Open Interest': _fmt_n(r['oi']),
            'Cambio OI': _fmt_n(r['oi_chg']),
            'Tendencia': r['tendencia'] or 'N/A',
            'Percentil': f"{r['percentil']:.0f}%" if r['percentil'] is not None else 'N/A',
            'Estado': r['pct_class'],
            'COT Score': r['score'] if r['score'] is not None else np.nan,
            'Señal Final': r['señal_final'],
            'Semanas': r['n_semanas'],
        })

    df_tabla = pd.DataFrame(filas).sort_values('COT Score', ascending=False, na_position='last')

    def _color_score(v):
        try:
            v = float(v)
        except Exception:
            return 'color:#6b7d9a'
        if v <= 20: return 'background-color:#2a0a0a;color:#f85149;font-weight:700'
        if v <= 40: return 'background-color:#2a1a05;color:#f0883e;font-weight:700'
        if v <= 60: return 'background-color:#1e1a05;color:#e3b341;font-weight:700'
        if v <= 80: return 'background-color:#081a0a;color:#7ee787;font-weight:700'
        return 'background-color:#051505;color:#3fb950;font-weight:700'

    def _color_estado(v):
        colores = {
            'EXTREME LONG': C_GREEN, 'HIGH POSITIONING': C_LGREEN, 'NORMAL': C_YELLOW,
            'LOW POSITIONING': C_LRED, 'EXTREME SHORT': C_RED, 'INSUFFICIENT HISTORY': C_MUTED,
        }
        return f'color:{colores.get(v, "#e6edf3")};font-weight:700'

    _map = 'map' if hasattr(df_tabla.style, 'map') else 'applymap'
    styled = (df_tabla.style
              .pipe(lambda s: getattr(s, _map)(_color_score, subset=['COT Score']))
              .pipe(lambda s: getattr(s, _map)(_color_estado, subset=['Estado']))
              .format({'COT Score': lambda v: f'{v:.0f}' if pd.notna(v) else 'N/A'})
              .set_properties(**{'background-color': '#0d1117', 'color': '#e6edf3', 'border': '1px solid #21262d'})
              .set_table_styles([
                  {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', '#e6edf3'),
                      ('font-weight', '700'), ('text-align', 'center'),
                      ('border-bottom', '2px solid #3a7bd5'), ('font-size', '11px')]},
                  {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]},
              ]))
    st.dataframe(styled, use_container_width=True, height=min(600, max(150, len(df_tabla) * 38 + 60)))
    st.caption('El COT Score y las interpretaciones son estimaciones probabilísticas basadas únicamente en datos de posicionamiento COT, no en precio.')


# ------------------------------------------------------------------
#  TAB 3 — ANÁLISIS INDIVIDUAL
# ------------------------------------------------------------------

def _cot_tab_individual():
    df = st.session_state['cot_data']
    if df.empty:
        st.info('Cargá datos en la pestaña "Cargar Datos" para ver el análisis individual.')
        return

    commodities = sorted(df['Commodity'].unique().tolist())
    commodity_sel = st.selectbox('Seleccioná un commodity', commodities, key='cot_ind_sel')

    grupo = df[df['Commodity'] == commodity_sel]
    r = _cot_resumen_commodity(grupo)
    if r is None:
        st.warning('No hay datos válidos para este commodity.')
        return

    st.markdown(f"""
    <div style="text-align:center;margin-bottom:14px">
      <div style="font-size:20px;font-weight:800;color:#e6edf3">{r['commodity']}</div>
      <div style="font-size:12px;color:#6b7d9a">Última semana: {r['fecha'].strftime('%Y-%m-%d') if pd.notna(r['fecha']) else 'N/A'} · {r['n_semanas']} semana(s) cargada(s)</div>
    </div>
    """, unsafe_allow_html=True)

    score_txt = f"{r['score']:.0f}/100" if r['score'] is not None else 'N/A'
    _cot_kpi_cards([
        ('COT Score', score_txt, f"{r['score_emoji']} {r['score_label']}", r['score_color']),
        ('Managed Money Net', _fmt_n(r['mm_net']), f"Cambio: {_fmt_n(r['mm_net_chg'])}", C_ACENT),
        ('Open Interest', _fmt_n(r['oi']), f"Cambio: {_fmt_n(r['oi_chg'])}", C_YELLOW),
        ('Percentil / Tendencia', f"{r['percentil']:.0f}%" if r['percentil'] is not None else 'N/A',
         r['tendencia'] or 'N/A', r['pct_color']),
    ])

    st.markdown(f"""
    <div class="interp-card">
      <div class="interp-header">{r['score_emoji']} {r['commodity']} · {r['señal_final']}</div>
      {r['texto']}
    </div>
    """, unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1: st.metric('MM Long', _fmt_n(r['mm_long']))
    with c2: st.metric('MM Short', _fmt_n(r['mm_short']))
    with c3: st.metric('Estado de Posicionamiento', r['pct_class'])

    if r['n_semanas'] >= 2:
        tab_g1, tab_g2, tab_g3, tab_g4 = st.tabs([
            '📈 MM Long', '📉 MM Short', '⚖️ MM Net', '📊 Open Interest',
        ])
        with tab_g1:
            st.plotly_chart(
                _cot_fig_evolucion(r['df'], 'Managed Money Long', f"{r['commodity']} — Managed Money Long", C_LGREEN),
                use_container_width=True, config=PLOTLY_CONFIG, key=f'cot_fig_mmlong_{commodity_sel}',
            )
        with tab_g2:
            st.plotly_chart(
                _cot_fig_evolucion(r['df'], 'Managed Money Short', f"{r['commodity']} — Managed Money Short", C_LRED),
                use_container_width=True, config=PLOTLY_CONFIG, key=f'cot_fig_mmshort_{commodity_sel}',
            )
        with tab_g3:
            st.plotly_chart(
                _cot_fig_evolucion(r['df'], 'MM Net', f"{r['commodity']} — Managed Money Net", C_ACENT),
                use_container_width=True, config=PLOTLY_CONFIG, key=f'cot_fig_net_{commodity_sel}',
            )
        with tab_g4:
            st.plotly_chart(
                _cot_fig_evolucion(r['df'], 'Open Interest', f"{r['commodity']} — Open Interest", C_YELLOW),
                use_container_width=True, config=PLOTLY_CONFIG, key=f'cot_fig_oi_{commodity_sel}',
            )
    else:
        st.info('Se necesitan al menos 2 semanas cargadas para graficar la evolución.')

    # ── Complementarios: Producer/Merchant, Swap Dealers, Other Reportables ──
    with st.expander('👥 Producer/Merchant, Swap Dealers y Other Reportables (contexto)', expanded=False):
        st.caption('Se muestran como información complementaria. El Producer/Merchant suele usar futuros para cobertura (hedging) y no se interpreta como señal direccional.')
        fila = r['df'].iloc[-1]
        cc1, cc2, cc3 = st.columns(3)
        with cc1:
            st.markdown('**Producer/Merchant**')
            st.write(f"Long: {_fmt_n(fila.get('Producer/Merchant Long'))}")
            st.write(f"Short: {_fmt_n(fila.get('Producer/Merchant Short'))}")
            st.write(f"Spread: {_fmt_n(fila.get('Producer/Merchant Spread'))}")
            st.write(f"Net: {_fmt_n(fila.get('Producer Net'))}")
        with cc2:
            st.markdown('**Swap Dealers**')
            st.write(f"Long: {_fmt_n(fila.get('Swap Dealers Long'))}")
            st.write(f"Short: {_fmt_n(fila.get('Swap Dealers Short'))}")
            st.write(f"Spread: {_fmt_n(fila.get('Swap Dealers Spread'))}")
            st.write(f"Net: {_fmt_n(fila.get('Swap Net'))}")
        with cc3:
            st.markdown('**Other Reportables**')
            st.write(f"Long: {_fmt_n(fila.get('Other Reportables Long'))}")
            st.write(f"Short: {_fmt_n(fila.get('Other Reportables Short'))}")
            st.write(f"Spread: {_fmt_n(fila.get('Other Reportables Spread'))}")
            st.write(f"Net: {_fmt_n(fila.get('Other Net'))}")

    with st.expander('📋 Ver tabla semanal completa', expanded=False):
        cols_show = [
            'Report Date', 'Managed Money Long', 'Managed Money Short', 'MM Net', 'MM Net Chg',
            'Open Interest', 'OI Chg',
        ]
        df_show = r['df'][cols_show].copy()
        df_show['Report Date'] = df_show['Report Date'].dt.strftime('%Y-%m-%d')
        st.dataframe(df_show, use_container_width=True, height=min(400, len(df_show) * 36 + 60))


# ------------------------------------------------------------------
#  ENTRY POINT
# ------------------------------------------------------------------

def modulo_cot():
    """Punto de entrada del módulo — llamar desde el router principal
    de la app (elif MODULO == 'cot': modulo_cot())."""
    _cot_init_state()

    st.markdown("""
    <div style="background:linear-gradient(135deg,#150d20 0%,#1c1a0a 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #e3b341;
         border-radius:14px; padding:28px 32px; margin-bottom:24px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">
        📑 Análisis COT — Commitment of Traders
      </div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Interpretación automática del posicionamiento de <b style="color:#f0883e">Managed Money</b>
        a partir de los datos COT que vos cargás manualmente. No usa precio, RSI, MACD, medias móviles
        ni ningún dato externo — solo Open Interest y posicionamiento por categoría de trader.
      </div>
    </div>
    """, unsafe_allow_html=True)

    tab_carga, tab_general, tab_individual = st.tabs([
        '📥 Cargar Datos', '📊 Análisis General', '🔍 Análisis Individual',
    ])

    with tab_carga:
        _cot_tab_carga()
    with tab_general:
        _cot_tab_general()
    with tab_individual:
        _cot_tab_individual()
