import streamlit as st
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import seaborn as sb
import warnings
warnings.filterwarnings('ignore')

# ── Configuración de página ───────────────────────────────
st.set_page_config(
    page_title="Forex Top-Down",
    page_icon="💱",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS personalizado ─────────────────────────────────────
st.markdown("""
<style>
    /* Fondo general */
    .stApp { background-color: #0d1117; }
    section[data-testid="stSidebar"] { background-color: #161b22; }

    /* Títulos */
    h1, h2, h3, h4 { color: #e6edf3 !important; }
    p, label, .stMarkdown { color: #c9d1d9 !important; }

    /* Métricas */
    [data-testid="stMetric"] {
        background: #161b22;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 12px 16px;
    }
    [data-testid="stMetricLabel"] { color: #8b949e !important; font-size: 12px; }
    [data-testid="stMetricValue"] { color: #e6edf3 !important; }

    /* Tablas */
    .stDataFrame { background: #161b22; }
    thead tr th { background-color: #21262d !important; color: #e6edf3 !important; }

    /* Botones */
    .stButton > button {
        background: #238636; color: white; border: none;
        border-radius: 6px; font-weight: 600;
    }
    .stButton > button:hover { background: #2ea043; }

    /* Selectbox / multiselect */
    .stSelectbox > div > div { background: #161b22; color: #e6edf3; border-color: #30363d; }

    /* Spinner */
    .stSpinner > div { border-top-color: #58a6ff !important; }

    /* Separador */
    hr { border-color: #30363d; }

    /* Info box */
    .info-box {
        background: #161b22;
        border: 1px solid #30363d;
        border-left: 4px solid #58a6ff;
        border-radius: 6px;
        padding: 12px 16px;
        margin: 8px 0;
        color: #c9d1d9;
        font-size: 13px;
    }
    .signal-badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

plt.rcParams.update({
    'figure.facecolor': '#0d1117', 'axes.facecolor': '#161b22',
    'text.color': 'white', 'axes.labelcolor': 'white',
    'xtick.color': 'white', 'ytick.color': 'white',
    'grid.color': '#21262d', 'axes.edgecolor': '#30363d',
})

# ═══════════════════════════════════════════════════════════
#  FUNCIONES DE ANÁLISIS
# ═══════════════════════════════════════════════════════════

@st.cache_data(ttl=1800, show_spinner=False)  # cache 30 min
def descargar_datos(ticker, period='3mo'):
    try:
        import yfinance as yf
        d = yf.download(ticker, period=period, interval='1d',
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


def get_close(df):
    if df is None:
        return None
    try:
        if isinstance(df, pd.Series):
            return df.dropna()
        if 'Close' in df.columns:
            c = df['Close']
            if isinstance(c, pd.DataFrame):
                c = c.iloc[:, 0]
            return c.dropna()
        for col in df.columns:
            if 'close' in str(col).lower():
                return df[col].dropna()
        return None
    except Exception:
        return None


def calcular_atr(df, p=14):
    if df is None:
        return None
    try:
        h = df['High'] if 'High' in df.columns else None
        l = df['Low']  if 'Low'  in df.columns else None
        c = get_close(df)
        if h is None or l is None or c is None:
            return None
        tr = pd.concat([h - l, abs(h - c.shift(1)), abs(l - c.shift(1))], axis=1).max(axis=1)
        return tr.rolling(p).mean()
    except Exception:
        return None


def pct_rank(serie):
    s = pd.Series(serie).dropna()
    if len(s) < 5:
        return 50.0
    return float((s < s.iloc[-1]).sum() / len(s) * 100)


def calcular_rsi(close, p=14):
    s = pd.Series(close).dropna()
    d = s.diff()
    g = d.clip(lower=0).rolling(p).mean()
    l = (-d.clip(upper=0)).rolling(p).mean()
    rs = g / l.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)


def vol_anual(close, v=20):
    s = pd.Series(close).dropna()
    return s.pct_change().rolling(v).std() * np.sqrt(252) * 100


def clasificar(s):
    if   s <= 20: return 'Miedo Extremo',  '#f85149', '🔴'
    elif s <= 40: return 'Miedo',           '#f0883e', '🟠'
    elif s <= 60: return 'Neutral',         '#e3b341', '🟡'
    elif s <= 80: return 'Codicia',         '#7ee787', '🟢'
    else:         return 'Codicia Extrema', '#3fb950', '💚'


def scores_activo(close_vol, close_mp, atr):
    cv = pd.Series(close_vol).dropna()
    cm = pd.Series(close_mp).dropna()
    if len(cv) < 15 or len(cm) < 5:
        return 50.0, 50.0, 50.0
    precio_pct = pct_rank(cv)
    rsi_serie  = calcular_rsi(cv, p=7)
    rsi_pct    = 100 - pct_rank(rsi_serie)
    vol_serie  = vol_anual(cv, 10)
    vol_pct    = 100 - pct_rank(vol_serie)
    sc_acum    = (100 - precio_pct) * 0.40 + rsi_pct * 0.35 + vol_pct * 0.25
    ret20 = float(cm.pct_change(5).iloc[-1] * 100) if len(cm) >= 6 else 0
    if np.isnan(ret20): ret20 = 0
    mom = min(100, max(0, 50 + ret20 * 2.0))
    if atr is not None:
        atr_s = pd.Series(atr).dropna()
        comp_atr = max(0, min(100, 100 - (float(atr_s.iloc[-1]) / float(atr_s.mean()) * 50))) if len(atr_s) > 5 else 50
    else:
        comp_atr = 50
    ma20  = cm.rolling(10).mean()
    std20 = cm.rolling(10).std()
    bbw   = (std20 / ma20.replace(0, np.nan) * 100).dropna()
    bb_c  = 100 - pct_rank(bbw) if len(bbw) > 5 else 50
    sc_antic = mom * 0.40 + comp_atr * 0.30 + bb_c * 0.30
    sc_sent  = pct_rank(cv)
    return round(sc_acum, 1), round(sc_antic, 1), round(sc_sent, 1)


def señal_accion(sa, sn, ss):
    if   sa >= 62 and sn >= 55:               return '🟢 ACUMULAR'
    elif sa >= 62 and sn >= 40:               return '🟡 VIGILAR'
    elif sa >= 58 and sn <  40:               return '🔵 ACUMULAR GRADUAL'
    elif sa <  45 and sn >= 62 and ss >= 62:  return '🚀 TENDENCIA ALCISTA'
    elif sn >= 65 and 40 <= sa < 62:          return '⚡ MOVIMIENTO INMINENTE'
    elif sa <  38 and sn <  42 and ss >= 65:  return '⚠️ MÁXIMOS'
    elif sa >= 55 and sn <  35 and ss <  35:  return '🔴 EVITAR'
    elif sa <  38 and sn >= 55 and ss <  40:  return '🟠 REBOTE'
    else:                                      return '⏸️ ESPERAR'


# ═══════════════════════════════════════════════════════════
#  PARES
# ═══════════════════════════════════════════════════════════

FOREX = {
    'EUR/USD': ('EURUSD=X', 'Majors'),
    'GBP/USD': ('GBPUSD=X', 'Majors'),
    'USD/JPY': ('USDJPY=X', 'Majors'),
    'USD/CHF': ('USDCHF=X', 'Majors'),
    'USD/CAD': ('USDCAD=X', 'Majors'),
    'AUD/USD': ('AUDUSD=X', 'Majors'),
    'NZD/USD': ('NZDUSD=X', 'Majors'),
    'USD/CNY': ('USDCNY=X', 'Majors'),
    'EUR/GBP': ('EURGBP=X', 'Crosses EUR'),
    'EUR/JPY': ('EURJPY=X', 'Crosses EUR'),
    'EUR/CHF': ('EURCHF=X', 'Crosses EUR'),
    'EUR/AUD': ('EURAUD=X', 'Crosses EUR'),
    'EUR/CAD': ('EURCAD=X', 'Crosses EUR'),
    'EUR/NZD': ('EURNZD=X', 'Crosses EUR'),
    'GBP/JPY': ('GBPJPY=X', 'Crosses GBP'),
    'GBP/CHF': ('GBPCHF=X', 'Crosses GBP'),
    'GBP/AUD': ('GBPAUD=X', 'Crosses GBP'),
    'GBP/CAD': ('GBPCAD=X', 'Crosses GBP'),
    'GBP/NZD': ('GBPNZD=X', 'Crosses GBP'),
    'AUD/JPY': ('AUDJPY=X', 'Crosses AUD/NZD'),
    'AUD/CAD': ('AUDCAD=X', 'Crosses AUD/NZD'),
    'AUD/CHF': ('AUDCHF=X', 'Crosses AUD/NZD'),
    'AUD/NZD': ('AUDNZD=X', 'Crosses AUD/NZD'),
    'NZD/JPY': ('NZDJPY=X', 'Crosses AUD/NZD'),
    'NZD/CAD': ('NZDCAD=X', 'Crosses AUD/NZD'),
    'NZD/CHF': ('NZDCHF=X', 'Crosses AUD/NZD'),
    'CAD/JPY': ('CADJPY=X', 'Crosses JPY'),
    'CHF/JPY': ('CHFJPY=X', 'Crosses JPY'),
    'USD/ARS': ('USDARS=X', 'LatAm'),
    'USD/BRL': ('USDBRL=X', 'LatAm'),
    'USD/MXN': ('USDMXN=X', 'LatAm'),
    'USD/CLP': ('USDCLP=X', 'LatAm'),
    'USD/COP': ('USDCOP=X', 'LatAm'),
    'USD/PEN': ('USDPEN=X', 'LatAm'),
    'USD/UYU': ('USDUYU=X', 'LatAm'),
}

COLORES_GRUPO = {
    'Majors':           '#58a6ff',
    'Crosses EUR':      '#f0883e',
    'Crosses GBP':      '#7ee787',
    'Crosses AUD/NZD':  '#bc8cff',
    'Crosses JPY':      '#e3b341',
    'LatAm':            '#f85149',
}

# ═══════════════════════════════════════════════════════════
#  DESCARGA DE DATOS (con barra de progreso)
# ═══════════════════════════════════════════════════════════

@st.cache_data(ttl=1800, show_spinner=False)
def cargar_todos_los_pares():
    resultados = {}
    for nombre, (tk, grupo) in FOREX.items():
        try:
            df_v = descargar_datos(tk, '3mo')
            df_m = descargar_datos(tk, '1mo')
            if df_v is None:
                continue
            cl_v = get_close(df_v)
            cl_m = get_close(df_m)
            if cl_v is None or cl_m is None or len(cl_v.dropna()) < 15:
                continue
            atr        = calcular_atr(df_m)
            sa, sn, ss = scores_activo(cl_v, cl_m, atr)
            sf         = sa * 0.45 + sn * 0.35 + ss * 0.20
            accion     = señal_accion(sa, sn, ss)
            rsi        = float(calcular_rsi(cl_m, p=7).iloc[-1])
            ret_5d     = float(cl_m.pct_change(5).iloc[-1] * 100)  if len(cl_m) >= 6  else 0
            ret_10d    = float(cl_m.pct_change(10).iloc[-1] * 100) if len(cl_m) >= 11 else 0
            precio     = float(cl_m.iloc[-1])
            for v in [ret_5d, ret_10d, rsi]:
                if np.isnan(v): v = 0
            # Guardar historial de cierre para el gráfico de línea
            hist = cl_m.reset_index()
            hist.columns = ['Fecha', 'Precio']
            resultados[nombre] = {
                'tk': tk, 'grupo': grupo,
                'sa': sa, 'sn': sn, 'ss': ss, 'sf': sf,
                'rsi': rsi, 'ret_5d': ret_5d, 'ret_10d': ret_10d,
                'precio': precio, 'accion': accion,
                'hist': hist,
            }
        except Exception:
            continue
    return resultados


def fmt_precio_fx(p):
    if p is None: return "—"
    if p >= 100:  return f"{p:.3f}"
    if p >= 10:   return f"{p:.4f}"
    return f"{p:.5f}"


# ═══════════════════════════════════════════════════════════
#  SIDEBAR
# ═══════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## 💱 Forex Top-Down")
    st.markdown("---")

    grupos_disponibles = list(dict.fromkeys(v[1] for v in FOREX.values()))
    grupos_sel = st.multiselect(
        "Grupos a analizar",
        options=grupos_disponibles,
        default=grupos_disponibles,
    )

    st.markdown("---")
    actualizar = st.button("🔄 Actualizar datos", use_container_width=True)
    if actualizar:
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    st.markdown("""
    <div style='color:#8b949e; font-size:12px;'>
    <b>Scores (0–100):</b><br>
    🟢 >80 Muy alto<br>
    🟢 61–80 Alto<br>
    🟡 41–60 Neutral<br>
    🟠 21–40 Bajo<br>
    🔴 0–20 Muy bajo<br><br>
    Datos: Yahoo Finance<br>
    Caché: 30 minutos<br>
    Solo informativo.
    </div>
    """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════
#  HEADER
# ═══════════════════════════════════════════════════════════

st.markdown("# 💱 Análisis Top-Down Forex")
st.markdown("**Majors · Crosses · LatAm** — Scores por percentil histórico 3 meses")
st.markdown("---")


# ═══════════════════════════════════════════════════════════
#  CARGA
# ═══════════════════════════════════════════════════════════

with st.spinner("⏳ Descargando datos de mercado... (puede tardar ~30 segundos)"):
    datos = cargar_todos_los_pares()

# Filtrar por grupos seleccionados
datos_filtrados = {n: d for n, d in datos.items() if d['grupo'] in grupos_sel}

if not datos_filtrados:
    st.error("No hay datos disponibles. Verificá tu conexión o seleccioná al menos un grupo.")
    st.stop()

total = len(datos_filtrados)
ok    = sum(1 for d in datos_filtrados.values() if d['sa'] > 0)

# ── KPIs globales ─────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)
mejores = sorted(datos_filtrados.items(), key=lambda x: x[1]['sa'], reverse=True)
peores  = sorted(datos_filtrados.items(), key=lambda x: x[1]['sa'])

with col1:
    st.metric("Pares analizados", f"{total}")
with col2:
    st.metric("🟢 Mejor oportunidad", mejores[0][0], f"Acum: {mejores[0][1]['sa']:.0f}")
with col3:
    st.metric("⚡ Mayor momentum", 
              max(datos_filtrados.items(), key=lambda x: x[1]['sn'])[0],
              f"Antic: {max(datos_filtrados.items(), key=lambda x: x[1]['sn'])[1]['sn']:.0f}")
with col4:
    st.metric("⚠️ Mayor riesgo", peores[0][0], f"Acum: {peores[0][1]['sa']:.0f}")

st.markdown("---")


# ═══════════════════════════════════════════════════════════
#  TABS
# ═══════════════════════════════════════════════════════════

tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Scores por grupo",
    "📈 Momentum",
    "🗺️ Mapa cuadrante",
    "📋 Ranking completo",
])


# ── TAB 1: Barras por grupo ───────────────────────────────
with tab1:
    st.markdown("### Score Acumulación y Anticipación por grupo")
    st.markdown("""
    <div class='info-box'>
    🔵 Barra larga = <b>Acumulación</b> alta (precio barato históricamente) — buena zona de entrada.<br>
    💙 Barra fina = <b>Anticipación</b> (momentum actual del par).
    </div>
    """, unsafe_allow_html=True)

    grupos_en_datos = [g for g in grupos_disponibles if g in grupos_sel and
                       any(d['grupo'] == g for d in datos_filtrados.values())]

    # Dos columnas de grupos
    for i in range(0, len(grupos_en_datos), 2):
        cols = st.columns(2)
        for j, grupo in enumerate(grupos_en_datos[i:i+2]):
            items = [(n, d) for n, d in datos_filtrados.items() if d['grupo'] == grupo]
            if not items:
                continue
            items_ord = sorted(items, key=lambda x: x[1]['sa'], reverse=True)
            ns   = [n for n, _ in items_ord]
            sas  = [d['sa'] for _, d in items_ord]
            sns_ = [d['sn'] for _, d in items_ord]
            col_bars = [clasificar(s)[1] for s in sas]
            y = np.arange(len(ns))

            fig, ax = plt.subplots(figsize=(6, max(3, len(ns) * 0.55)))
            fig.patch.set_facecolor('#0d1117')
            ax.set_facecolor('#161b22')

            brs = ax.barh(y, sas, color=col_bars, edgecolor='none', height=0.55, alpha=.9, label='Acum')
            ax.barh(y, sns_, color='#58a6ff', edgecolor='none', height=0.28, alpha=0.45, label='Antic')
            ax.axvline(62, color='#3fb950', ls=':', alpha=.5, lw=1)
            ax.axvline(38, color='#f85149', ls=':', alpha=.5, lw=1)
            ax.fill_betweenx([-0.5, len(ns) - 0.5], 62, 100, alpha=.05, color='#3fb950')
            ax.fill_betweenx([-0.5, len(ns) - 0.5],  0,  38, alpha=.05, color='#f85149')
            ax.set_xlim(0, 118)
            ax.set_yticks(y)
            ax.set_yticklabels(ns, fontsize=9)
            ax.set_title(grupo, color='white', fontsize=11, pad=6)
            for b, s in zip(brs, sas):
                ax.text(s + 1, b.get_y() + b.get_height() / 2, f'{s:.0f}',
                        va='center', color='white', fontsize=8)
            ax.grid(axis='x', alpha=.2)
            ax.tick_params(colors='white')
            ax.legend(facecolor='#161b22', labelcolor='white', fontsize=8)
            plt.tight_layout()

            with cols[j]:
                st.pyplot(fig, use_container_width=True)
            plt.close(fig)


# ── TAB 2: Momentum ───────────────────────────────────────
with tab2:
    st.markdown("### Momentum 5d vs 10d")
    st.markdown("""
    <div class='info-box'>
    Verde = retorno positivo · Rojo = retorno negativo<br>
    Barra más oscura = 5 días · Barra más clara = 10 días.
    </div>
    """, unsafe_allow_html=True)

    pares_ord = sorted(datos_filtrados.items(), key=lambda x: x[1]['ret_5d'], reverse=True)
    ns_all    = [n for n, _ in pares_ord]
    r5_all    = [d['ret_5d']  for _, d in pares_ord]
    r10_all   = [d['ret_10d'] for _, d in pares_ord]
    x_all     = np.arange(len(ns_all))

    fig2, ax2 = plt.subplots(figsize=(max(12, len(ns_all) * 0.52), 5))
    fig2.patch.set_facecolor('#0d1117')
    ax2.set_facecolor('#161b22')

    ax2.bar(x_all - 0.2, r5_all,  width=0.38,
            color=['#3fb950' if v >= 0 else '#f85149' for v in r5_all],  alpha=.9,  label='5 días')
    ax2.bar(x_all + 0.2, r10_all, width=0.38,
            color=['#58a6ff' if v >= 0 else '#bc8cff' for v in r10_all], alpha=.75, label='10 días')
    ax2.axhline(0, color='white', lw=.8, alpha=.5)
    ax2.set_xticks(x_all)
    ax2.set_xticklabels(ns_all, rotation=45, ha='right', fontsize=8)
    ax2.set_ylabel('Retorno %', color='#8b949e')
    ax2.legend(facecolor='#161b22', labelcolor='white', fontsize=9)
    ax2.grid(axis='y', alpha=.2)
    ax2.tick_params(colors='white')
    plt.tight_layout()
    st.pyplot(fig2, use_container_width=True)
    plt.close(fig2)

    # Heatmap de scores
    st.markdown("### Heatmap de scores")
    df_heat = pd.DataFrame({
        'Acum':  {n: d['sa'] for n, d in datos_filtrados.items()},
        'Antic': {n: d['sn'] for n, d in datos_filtrados.items()},
        'Sent':  {n: d['ss'] for n, d in datos_filtrados.items()},
    }).sort_values('Acum', ascending=False)

    fig_h, ax_h = plt.subplots(figsize=(6, max(5, len(datos_filtrados) * 0.36)))
    fig_h.patch.set_facecolor('#0d1117')
    sb.heatmap(df_heat, annot=True, fmt='.0f', cmap='RdYlGn',
               vmin=0, vmax=100, ax=ax_h, linewidths=.5,
               cbar_kws={'label': 'Score'})
    ax_h.set_title('Scores por par (verde = oportunidad)', color='white', fontsize=11, pad=10)
    ax_h.tick_params(colors='white')
    ax_h.set_xticklabels(ax_h.get_xticklabels(), rotation=0, fontsize=9)
    ax_h.set_yticklabels(ax_h.get_yticklabels(), rotation=0, fontsize=8)
    plt.tight_layout()
    st.pyplot(fig_h, use_container_width=True)
    plt.close(fig_h)


# ── TAB 3: Mapa cuadrante ─────────────────────────────────
with tab3:
    st.markdown("### Mapa de oportunidades: Acumulación vs Anticipación")
    st.markdown("""
    <div class='info-box'>
    🟢 <b>Arriba-derecha</b>: precio barato + momentum alcista → mejor zona de entrada en la divisa base.<br>
    🔴 <b>Abajo-izquierda</b>: precio caro + momentum bajista → evitar o considerar venta.
    </div>
    """, unsafe_allow_html=True)

    fig3, ax3 = plt.subplots(figsize=(9, 7))
    fig3.patch.set_facecolor('#0d1117')
    ax3.set_facecolor('#161b22')

    for nombre, d in datos_filtrados.items():
        col_p = COLORES_GRUPO.get(d['grupo'], 'white')
        ax3.scatter(d['sn'], d['sa'], color=col_p, s=140, zorder=5,
                    edgecolors='white', linewidths=.5)
        ax3.annotate(nombre, (d['sn'], d['sa']),
                     xytext=(5, 3), textcoords='offset points',
                     fontsize=7.5, color='#c9d1d9')

    ax3.axhline(62, color='#3fb950', ls='--', alpha=.4)
    ax3.axhline(38, color='#f85149', ls='--', alpha=.4)
    ax3.axvline(55, color='#e3b341', ls='--', alpha=.4)
    ax3.fill_between([55, 100], [62, 62], [100, 100], alpha=.07, color='#3fb950')
    ax3.fill_between([0, 55],   [0, 0],   [38, 38],   alpha=.07, color='#f85149')
    ax3.text(77, 95, 'Comprar BASE\n(barato + momentum)', color='#3fb950', fontsize=8, alpha=0.8, ha='center')
    ax3.text(25,  5, 'Vender BASE\n(caro + bajista)',    color='#f85149', fontsize=8, alpha=0.8, ha='center')

    ax3.set_xlabel('Score Anticipación →', color='#8b949e')
    ax3.set_ylabel('← Score Acumulación',  color='#8b949e')
    ax3.set_xlim(0, 100)
    ax3.set_ylim(0, 100)
    ax3.grid(alpha=.2)
    ax3.tick_params(colors='white')

    handles = [plt.scatter([], [], color=c, s=60, label=g)
               for g, c in COLORES_GRUPO.items() if g in grupos_sel]
    ax3.legend(handles=handles, facecolor='#161b22', labelcolor='white', fontsize=8)
    plt.tight_layout()
    st.pyplot(fig3, use_container_width=True)
    plt.close(fig3)


# ── TAB 4: Tabla completa ─────────────────────────────────
with tab4:
    st.markdown("### Ranking completo de pares")

    # Construir tabla
    filas = []
    for nombre, d in sorted(datos_filtrados.items(), key=lambda x: x[1]['sa'], reverse=True):
        lbl, col, em = clasificar(d['sa'])
        filas.append({
            'Par':       nombre,
            'Grupo':     d['grupo'],
            'Acum':      round(d['sa'], 1),
            'Antic':     round(d['sn'], 1),
            'Sent':      round(d['ss'], 1),
            'RSI':       round(d['rsi'], 1),
            'Ret 5d %':  round(d['ret_5d'], 2),
            'Ret 10d %': round(d['ret_10d'], 2),
            'Precio':    fmt_precio_fx(d['precio']),
            'Señal':     d['accion'],
        })

    df_tabla = pd.DataFrame(filas)

    # Filtro rápido por señal
    señales_unicas = ['Todas'] + sorted(df_tabla['Señal'].unique().tolist())
    señal_sel = st.selectbox("Filtrar por señal", señales_unicas)
    if señal_sel != 'Todas':
        df_tabla = df_tabla[df_tabla['Señal'] == señal_sel]

    # Colorear con gradient
    def color_score_cell(val):
        try:
            v = float(val)
            if   v <= 20: bg = '#5a1e1e'
            elif v <= 40: bg = '#5a3a1e'
            elif v <= 60: bg = '#3a3a1e'
            elif v <= 80: bg = '#1e3a1e'
            else:         bg = '#1e5a1e'
            return f'background-color: {bg}; color: white'
        except:
            return ''

    def color_ret(val):
        try:
            v = float(val)
            color = '#3fb950' if v >= 0 else '#f85149'
            return f'color: {color}; font-weight: bold'
        except:
            return ''

    styled = (df_tabla.style
              .applymap(color_score_cell, subset=['Acum', 'Antic', 'Sent'])
              .applymap(color_ret, subset=['Ret 5d %', 'Ret 10d %'])
              .set_properties(**{'background-color': '#161b22', 'color': '#e6edf3',
                                 'border': '1px solid #30363d'})
              .set_table_styles([{
                  'selector': 'th',
                  'props': [('background-color', '#21262d'), ('color', '#e6edf3'),
                             ('font-weight', 'bold'), ('text-align', 'center')]
              }]))

    st.dataframe(styled, use_container_width=True, height=600)

    # Detalle de un par
    st.markdown("---")
    st.markdown("### 🔍 Detalle de par")
    par_sel = st.selectbox("Seleccioná un par", list(datos_filtrados.keys()))
    if par_sel and par_sel in datos_filtrados:
        d = datos_filtrados[par_sel]
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Acumulación", f"{d['sa']:.1f}")
        c2.metric("Anticipación", f"{d['sn']:.1f}")
        c3.metric("Sentimiento", f"{d['ss']:.1f}")
        c4.metric("RSI", f"{d['rsi']:.1f}")
        c5.metric("Precio actual", fmt_precio_fx(d['precio']))

        st.markdown(f"**Señal:** {d['accion']}  |  **Grupo:** {d['grupo']}")

        # Mini gráfico de precio
        hist = d.get('hist')
        if hist is not None and len(hist) > 2:
            fig_line, ax_line = plt.subplots(figsize=(10, 3))
            fig_line.patch.set_facecolor('#0d1117')
            ax_line.set_facecolor('#161b22')
            ax_line.plot(hist['Fecha'], hist['Precio'],
                        color='#58a6ff', lw=1.5)
            ax_line.fill_between(hist['Fecha'], hist['Precio'],
                                 alpha=0.1, color='#58a6ff')
            ax_line.set_title(f'{par_sel} — Precio últimos 30 días', color='white', fontsize=10)
            ax_line.tick_params(colors='white', labelsize=8)
            ax_line.grid(alpha=.2)
            plt.tight_layout()
            st.pyplot(fig_line, use_container_width=True)
            plt.close(fig_line)

# ── Footer ────────────────────────────────────────────────
st.markdown("---")
st.markdown("""
<div style='text-align:center; color:#8b949e; font-size:12px;'>
💱 Forex Top-Down · Datos: Yahoo Finance · Caché: 30 min · Solo informativo, no constituye asesoramiento financiero.
</div>
""", unsafe_allow_html=True)
