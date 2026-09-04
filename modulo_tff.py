# ==============================================================
#  MÓDULO TFF (Traders in Financial Futures) — Análisis de
#  Posicionamiento Institucional Moderno
#  Clon funcional y estético de modulo_cot.py, adaptado a la
#  clasificación TFF (Asset Manager / Leveraged Funds / Dealer /
#  Other Reportables), pensado para ÍNDICES BURSÁTILES, FOREX y
#  CRIPTOMONEDAS (CME Bitcoin / Ether Futures).
#
#  Misma filosofía de seguridad que modulo_cot.py: el cliente
#  `supabase`, el `user_id` y el `user_email` los pasa app.py.
#  Cualquiera que entre puede VER los datos; solo ADMIN_EMAIL puede
#  cargar, editar o borrar. La protección real está en las
#  políticas RLS de Supabase (ver tff_schema.sql).
#
#  Cómo integrarlo a la app principal (app.py):
#
#    from modulo_tff import modulo_tff
#    modulo_tff(supabase, USER_ID, st.session_state['usuario'].email)
#
#  Reutiliza las clases CSS globales ya definidas en la app
#  (.kpi-card, .interp-card, .sec-title, .signal-pill, etc.), por
#  eso no vuelve a inyectar CSS propio (salvo las constantes de
#  color, duplicadas acá para que el módulo sea 100% independiente).
#
#  NOTA DE DISEÑO — divergencia:
#  El enunciado original pide la firma
#    _tff_clasificar_divergencia(pct_am, pct_lev, lev_net, lev_chg, oi_pct_chg)
#  pero dos de los cuatro estados (A y B) exigen también el signo
#  del cambio semanal del Asset Manager Net (AM Net Chg > 0 / < 0),
#  que no estaba en esa lista de parámetros. Para que la función
#  sea realmente utilizable se agregó un sexto parámetro `am_chg`
#  al final (después de los 5 originales, sin romper el orden
#  pedido). Se deja esta nota para que quede trazable el único
#  punto donde el módulo se apartó levemente de la especificación.
# ==============================================================

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

# ⚠️ Tiene que coincidir EXACTAMENTE con el email de tu cuenta de
# Supabase Auth (el mismo que en modulo_cot.py / modulo_calendario.py)
# y con el que se usa en las políticas RLS del archivo tff_schema.sql.
ADMIN_EMAIL = "brainferreyra@gmail.com"

TABLA_TFF = "tff_data"

# ------------------------------------------------------------------
#  PALETA — coherente con el resto de Capital+ (idéntica a modulo_cot.py)
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

TFF_COLUMNAS = [
    'Report Date', 'Contract Market Name', 'Open Interest',
    'Asset Manager Long', 'Asset Manager Short', 'Asset Manager Spread',
    'Leveraged Funds Long', 'Leveraged Funds Short', 'Leveraged Funds Spread',
    'Dealer Long', 'Dealer Short', 'Dealer Spread',
    'Other Reportables Long', 'Other Reportables Short', 'Other Reportables Spread',
]

TFF_COLUMNAS_NUMERICAS = [c for c in TFF_COLUMNAS if c not in ('Report Date', 'Contract Market Name')]

# Mapeo columnas del DataFrame <-> columnas de la tabla en Supabase
TFF_COL_TO_DB = {
    'Report Date': 'report_date',
    'Contract Market Name': 'contract_market_name',
    'Open Interest': 'open_interest',
    'Asset Manager Long': 'asset_manager_long',
    'Asset Manager Short': 'asset_manager_short',
    'Asset Manager Spread': 'asset_manager_spread',
    'Leveraged Funds Long': 'leveraged_funds_long',
    'Leveraged Funds Short': 'leveraged_funds_short',
    'Leveraged Funds Spread': 'leveraged_funds_spread',
    'Dealer Long': 'dealer_long',
    'Dealer Short': 'dealer_short',
    'Dealer Spread': 'dealer_spread',
    'Other Reportables Long': 'other_reportables_long',
    'Other Reportables Short': 'other_reportables_short',
    'Other Reportables Spread': 'other_reportables_spread',
}
DB_COL_TO_TFF = {v: k for k, v in TFF_COL_TO_DB.items()}


def _tff_template_df():
    return pd.DataFrame(columns=TFF_COLUMNAS)


def _tff_normalizar(df):
    """Convierte tipos, ordena y descarta filas sin fecha o sin mercado."""
    df = df.copy()
    if df.empty:
        return df
    df['Report Date'] = pd.to_datetime(df['Report Date'], errors='coerce')
    df['Contract Market Name'] = df['Contract Market Name'].astype(str).str.strip()
    for c in TFF_COLUMNAS_NUMERICAS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        else:
            df[c] = np.nan
    df = df.dropna(subset=['Report Date'])
    df = df[df['Contract Market Name'].str.len() > 0]
    df = df.sort_values(['Contract Market Name', 'Report Date']).reset_index(drop=True)
    return df


def _tff_merge(df_existente, df_nuevo):
    """Combina datos nuevos con los existentes, reemplazando duplicados
    de la misma pareja (Contract Market Name, Report Date) por el valor
    más reciente cargado (permite corregir una semana ya ingresada)."""
    df_nuevo = _tff_normalizar(df_nuevo)
    if df_nuevo.empty:
        return df_existente
    combinado = pd.concat([df_existente, df_nuevo], ignore_index=True)
    combinado = combinado.drop_duplicates(subset=['Contract Market Name', 'Report Date'], keep='last')
    combinado = combinado.sort_values(['Contract Market Name', 'Report Date']).reset_index(drop=True)
    return combinado


def _tff_es_admin(user_email):
    return bool(user_email) and user_email.strip().lower() == ADMIN_EMAIL.strip().lower()


# ------------------------------------------------------------------
#  PERSISTENCIA EN SUPABASE (mismo patrón que modulo_cot.py)
# ------------------------------------------------------------------

def _tff_df_to_records(df):
    """Convierte un DataFrame (columnas del formato TFF_COLUMNAS) a una
    lista de dicts con nombres de columna aptos para Supabase."""
    df = _tff_normalizar(df)
    if df.empty:
        return []
    df = df.copy()
    df['Report Date'] = df['Report Date'].dt.strftime('%Y-%m-%d')
    registros = []
    for _, fila in df.iterrows():
        reg = {}
        for col_df, col_db in TFF_COL_TO_DB.items():
            valor = fila.get(col_df)
            if col_db in ('report_date', 'contract_market_name'):
                reg[col_db] = valor
            else:
                reg[col_db] = None if pd.isna(valor) else float(valor)
        registros.append(reg)
    return registros


def _tff_records_to_df(registros):
    if not registros:
        return _tff_template_df()
    filas = []
    for reg in registros:
        fila = {}
        for col_db, col_df in DB_COL_TO_TFF.items():
            fila[col_df] = reg.get(col_db)
        filas.append(fila)
    df = pd.DataFrame(filas, columns=TFF_COLUMNAS)
    return _tff_normalizar(df)


@st.cache_data(ttl=120, show_spinner=False)
def _tff_obtener_registros(_supabase):
    res = _supabase.table(TABLA_TFF).select("*").execute()
    return res.data or []


def _tff_guardar_upsert(supabase, df_nuevo):
    """Sube/actualiza (upsert) filas nuevas o modificadas, usando
    (contract_market_name, report_date) como clave de conflicto."""
    registros = _tff_df_to_records(df_nuevo)
    if not registros:
        return False
    supabase.table(TABLA_TFF).upsert(registros, on_conflict='contract_market_name,report_date').execute()
    _tff_obtener_registros.clear()
    return True


def _tff_reemplazar_todo(supabase, df_completo):
    """Reemplaza TODO el contenido de la tabla en Supabase. Se usa
    cuando se edita la tabla completa (num_rows='dynamic'), porque ahí
    puede haber filas borradas y un upsert no alcanza para reflejarlo."""
    supabase.table(TABLA_TFF).delete().gte('id', 0).execute()
    registros = _tff_df_to_records(df_completo)
    if registros:
        supabase.table(TABLA_TFF).insert(registros).execute()
    _tff_obtener_registros.clear()
    return True


def _tff_borrar_todo(supabase):
    supabase.table(TABLA_TFF).delete().gte('id', 0).execute()
    _tff_obtener_registros.clear()
    return True


# ------------------------------------------------------------------
#  CÁLCULOS — SOLO CON DATOS TFF (nunca precio)
# ------------------------------------------------------------------

def _tff_calcular_serie(df_market):
    """Recibe todas las semanas de UN mercado, ya ordenadas, y agrega
    las columnas derivadas necesarias para el análisis."""
    df = df_market.sort_values('Report Date').reset_index(drop=True).copy()

    df['AM Net'] = df['Asset Manager Long'] - df['Asset Manager Short']
    df['AM Net Chg'] = df['AM Net'].diff()
    df['AM Long Chg'] = df['Asset Manager Long'].diff()
    df['AM Short Chg'] = df['Asset Manager Short'].diff()

    df['LEV Net'] = df['Leveraged Funds Long'] - df['Leveraged Funds Short']
    df['LEV Net Chg'] = df['LEV Net'].diff()
    df['LEV Long Chg'] = df['Leveraged Funds Long'].diff()
    df['LEV Short Chg'] = df['Leveraged Funds Short'].diff()

    df['OI Chg'] = df['Open Interest'].diff()
    df['OI Pct Chg'] = np.where(
        (df['Open Interest'].notna()) & (df['Open Interest'] != 0),
        (df['OI Chg'] / df['Open Interest']) * 100,
        np.nan,
    )

    # Dealer y Other Reportables se muestran como contexto (liquidez /
    # flujo residual), nunca como señal direccional principal
    df['Dealer Net'] = df['Dealer Long'] - df['Dealer Short']
    df['Other Net'] = df['Other Reportables Long'] - df['Other Reportables Short']

    return df


def _tff_interp_cambio_semanal(delta_long, delta_short):
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


def _tff_interp_oi(delta_net, delta_oi):
    """Devuelve (texto probabilístico, etiqueta corta) cruzando el AM
    Net Chg con el OI Chg. Nunca certeza. Se usa además para el
    componente de 'Confirmación OI' del TFF Score."""
    if pd.isna(delta_net) or pd.isna(delta_oi):
        return None, None
    if delta_net > 0 and delta_oi > 0:
        return ('Probable entrada de exposición alcista institucional / acumulación con dinero fresco.', 'alcista')
    if delta_net < 0 and delta_oi > 0:
        return ('Probable aumento de exposición bajista institucional / distribución con dinero fresco.', 'bajista')
    if delta_net > 0 and delta_oi < 0:
        return ('Podría tratarse de cobertura / short covering institucional (recompra de cortos).', 'cierre_bajista')
    if delta_net < 0 and delta_oi < 0:
        return ('Podría tratarse de long liquidation institucional (cierre de posiciones compradoras).', 'cierre_alcista')
    return ('Sin variación conjunta relevante entre AM Net y Open Interest.', 'neutral')


def _tff_interp_combinacion(am_net_chg, lev_net_chg, oi_chg):
    """MÓDULO 2 — Matriz de combinación Net + Open Interest (dinero
    fresco vs. cobertura), específica de TFF: cruza primero el
    Asset Manager (capital estructural) y, si no aplica, el
    Leveraged Funds (especulativo) contra el Open Interest.
    Devuelve (tag, texto)."""
    if pd.isna(oi_chg):
        return None, None

    if pd.notna(am_net_chg) and am_net_chg > 0 and oi_chg > 0:
        return (
            'ACUMULACIÓN INSTITUCIONAL CON DINERO FRESCO',
            'El Asset Manager sube su Net al mismo tiempo que el Open Interest crece: entra capital '
            'estructural nuevo a comprar, no es solo recompra de cortos existentes.',
        )
    if pd.notna(am_net_chg) and am_net_chg > 0 and oi_chg < 0:
        return (
            'COBERTURA / SHORT COVERING INSTITUCIONAL',
            'El Asset Manager mejora su Net pero el Open Interest cae: la mejora luce más a cierre de '
            'posiciones vendedoras (cobertura) que a compra genuina con convicción.',
        )
    if pd.notna(lev_net_chg) and lev_net_chg < 0 and oi_chg < 0:
        return (
            'CAPITULACIÓN / COBERTURA DE CORTOS ESPECULATIVA',
            'Los Leveraged Funds reducen su Net y el Open Interest cae a la vez: son especuladores '
            'cerrando posiciones (capitulación), no vendedores nuevos entrando con fuerza.',
        )
    if pd.notna(lev_net_chg) and lev_net_chg < 0 and oi_chg > 0:
        return (
            'ENTRADA DE VENTA ESPECULATIVA AGRESIVA',
            'Los Leveraged Funds bajan su Net mientras el Open Interest sube: se abren posiciones '
            'vendedoras especulativas nuevas, con convicción y dinero fresco.',
        )
    return (
        'SIN COMBINACIÓN CLARA',
        'El cruce de esta semana entre Asset Manager, Leveraged Funds y Open Interest no encaja en '
        'ninguno de los cuatro patrones principales (dinero fresco, cobertura, capitulación o venta agresiva).',
    )


def _tff_tendencia(net_series, min_semanas=3):
    """Tendencia del Net (AM o LEV) en las últimas semanas (pendiente lineal)."""
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


def _tff_percentil(net_series, min_semanas=5):
    s = net_series.dropna()
    if len(s) < min_semanas:
        return None
    valor = s.iloc[-1]
    pct = float((s < valor).sum()) / len(s) * 100
    return round(pct, 1)


def _tff_clasificar_percentil(pct):
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


def _tff_clasificar_divergencia(pct_am, pct_lev, lev_net, lev_chg, oi_pct_chg, am_chg=None):
    """MÓDULO 3 — Divergencia entre Manos Fuertes (Asset Manager) y
    Especuladores (Leveraged Funds). Devuelve (tag, texto, color).

    Ver nota de diseño al inicio del archivo: se agregó `am_chg`
    (AM Net Chg) como sexto parámetro porque los estados A y B lo
    necesitan y no estaba en la firma original de 5 parámetros.

    A. DIVERGENCIA ALCISTA DE SUELO (short squeeze potencial)
    B. DIVERGENCIA BAJISTA DE TECHO (distribución / trampa alcista)
    C. DIVERGENCIA DE AGOTAMIENTO POR ILIQUIDEZ
    D. SIN DIVERGENCIA EXTREMA
    """
    lev_capitulando = (lev_net is not None and lev_chg is not None
                        and pd.notna(lev_net) and pd.notna(lev_chg)
                        and lev_net < 0 and lev_chg > 0)
    lev_euforico = (lev_net is not None and lev_chg is not None
                     and pd.notna(lev_net) and pd.notna(lev_chg)
                     and lev_net > 0 and lev_chg > 0)

    # A. Divergencia alcista de suelo
    if (am_chg is not None and pd.notna(am_chg) and am_chg > 0
            and ((pct_lev is not None and pct_lev <= 15) or lev_capitulando)):
        detalle_lev = f"percentil {pct_lev:.0f}%" if pct_lev is not None else "capitulando cortos"
        return (
            'DIVERGENCIA ALCISTA DE SUELO',
            f"Los Asset Managers están acumulando (AM Net subiendo) mientras los Leveraged Funds están "
            f"en venta extrema o cerrando cortos ({detalle_lev}). Es la firma clásica de un posible "
            "short squeeze: si el especulador tiene que cubrirse, el movimiento al alza puede ser violento.",
            C_GREEN,
        )

    # B. Divergencia bajista de techo
    if (am_chg is not None and pd.notna(am_chg) and am_chg < 0
            and ((pct_lev is not None and pct_lev >= 85) or lev_euforico)):
        detalle_lev = f"percentil {pct_lev:.0f}%" if pct_lev is not None else "comprando eufóricos"
        return (
            'DIVERGENCIA BAJISTA DE TECHO',
            f"Los Asset Managers están tomando ganancias / distribuyendo (AM Net bajando) mientras los "
            f"Leveraged Funds siguen comprando de forma eufórica ({detalle_lev}). Suele ser el patrón de "
            "una trampa alcista: capital estructural saliendo justo donde entra el especulador tardío.",
            C_RED,
        )

    # C. Divergencia de agotamiento por iliquidez
    if oi_pct_chg is not None and pd.notna(oi_pct_chg) and oi_pct_chg < -1.5:
        return (
            'DIVERGENCIA DE AGOTAMIENTO POR ILIQUIDEZ',
            f"El Open Interest cayó {oi_pct_chg:.1f}% en la semana, una caída drástica. El movimiento de "
            "precio actual carece de dinero nuevo detrás: hay riesgo elevado de falso quiebre (fakeout) "
            "mientras la liquidez se retira del mercado.",
            C_YELLOW,
        )

    # D. Sin divergencia extrema
    return (
        'SIN DIVERGENCIA EXTREMA',
        "El posicionamiento de Asset Managers y Leveraged Funds, y la variación del Open Interest, se "
        "mantienen dentro de parámetros normales, sin un choque extremo entre manos fuertes y especuladores.",
        C_MUTED,
    )


def _tff_consistencia(net_series, lookback=4):
    """Fracción de semanas recientes que se movieron en la misma dirección."""
    diffs = net_series.diff().dropna().tail(lookback)
    if len(diffs) < 2:
        return None
    signos = np.sign(diffs.values)
    signos = signos[signos != 0]
    if len(signos) == 0:
        return 0.5
    return max((signos > 0).sum(), (signos < 0).sum()) / len(signos)


def _tff_oi_confirmacion_score(oi_tag):
    """Traduce la interpretación conjunta AM Net + OI (_tff_interp_oi)
    a un puntaje 0-100 para el TFF Score."""
    mapa = {
        'alcista': 80,
        'bajista': 20,
        'cierre_bajista': 60,
        'cierre_alcista': 40,
        'neutral': 50,
    }
    return mapa.get(oi_tag)


def _tff_score(fila_actual, net_series, pct, tendencia, consistencia, oi_tag=None):
    """TFF Score 0-100. Pondera: Percentil AM Net (30%), Tendencia AM
    (18%), Cambio Semanal AM Net (13%), Consistencia (13%), Ratio
    Long/Short AM (13%), Confirmación OI (13%)."""
    long_ = fila_actual.get('Asset Manager Long')
    short_ = fila_actual.get('Asset Manager Short')
    ratio_ls = None
    if pd.notna(long_) and pd.notna(short_) and (long_ + short_) > 0:
        ratio_ls = long_ / (long_ + short_) * 100

    componentes, pesos = [], []

    if pct is not None:
        componentes.append(pct); pesos.append(0.30)
    if tendencia is not None:
        t_score = {'ALCISTA': 80, 'LATERAL': 50, 'BAJISTA': 20}[tendencia]
        componentes.append(t_score); pesos.append(0.18)

    net_chg = fila_actual.get('AM Net Chg')
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

    oi_score = _tff_oi_confirmacion_score(oi_tag)
    if oi_score is not None:
        componentes.append(oi_score); pesos.append(0.13)

    if not componentes:
        return None
    total_peso = sum(pesos)
    return round(sum(c * p for c, p in zip(componentes, pesos)) / total_peso, 1)


def _tff_clasificar_score(score):
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


def _tff_señal_final(score, cambio_interp, pct_class):
    if score is None:
        return 'DATOS INSUFICIENTES'
    label, _, _ = _tff_clasificar_score(score)
    extremo = pct_class in ('EXTREME LONG', 'EXTREME SHORT')

    if label == 'MUY ALCISTA' and extremo:
        return 'POSICIONAMIENTO EXTREMO ALCISTA'
    if label == 'MUY BAJISTA' and extremo:
        return 'POSICIONAMIENTO EXTREMO BAJISTA'
    if cambio_interp == 'ACUMULACIÓN ALCISTA FUERTE' and label in ('ALCISTA', 'MUY ALCISTA'):
        return 'FUERTE ACUMULACIÓN INSTITUCIONAL ALCISTA'
    if cambio_interp == 'DISTRIBUCIÓN / POSICIONAMIENTO BAJISTA FUERTE' and label in ('BAJISTA', 'MUY BAJISTA'):
        return 'FUERTE DISTRIBUCIÓN INSTITUCIONAL BAJISTA'
    if label == 'ALCISTA':
        if cambio_interp in ('ACUMULACIÓN ALCISTA FUERTE', 'AUMENTANDO EXPOSICIÓN ALCISTA'):
            return 'ACUMULACIÓN INSTITUCIONAL MODERADA'
        return 'POSICIONAMIENTO ALCISTA'
    if label == 'BAJISTA':
        if cambio_interp in ('DISTRIBUCIÓN / POSICIONAMIENTO BAJISTA FUERTE', 'AUMENTANDO EXPOSICIÓN BAJISTA'):
            return 'DISTRIBUCIÓN MODERADA'
        return 'POSICIONAMIENTO BAJISTA'
    if cambio_interp == 'REDUCCIÓN DE EXPOSICIÓN / CIERRE DE POSICIONES':
        return 'CIERRE DE POSICIONES'
    return 'POSICIONAMIENTO NEUTRAL'


def _tff_texto_interpretacion(market, fila_actual, tendencia, pct, pct_class, oi_texto, n_semanas):
    partes = []
    net = fila_actual.get('AM Net')
    net_chg = fila_actual.get('AM Net Chg')
    oi_chg = fila_actual.get('OI Chg')

    if pd.notna(net):
        signo = 'alcista' if net >= 0 else 'bajista'
        partes.append(f"Los Asset Managers mantienen un posicionamiento neto {signo} de {net:,.0f} contratos.")

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

    partes.append("Esta lectura es probabilística y se basa exclusivamente en datos de posicionamiento TFF, sin considerar precio.")
    return ' '.join(partes)


def _tff_guia_aprendizaje(r):
    """MÓDULO 4 — Guía de Aprendizaje Semanal (TFF), estructurada en
    los 4 bloques pedidos, reutilizando exactamente las mismas
    variables ya calculadas para el resto del informe, sin introducir
    ningún criterio nuevo ni usar precio."""
    fila = r['df'].iloc[-1]
    am_chg = fila.get('AM Net Chg')
    lev_chg = fila.get('LEV Net Chg')
    oi_chg = fila.get('OI Chg')
    tendencia = r['tendencia']
    pct = r['percentil']
    pct_class = r['pct_class']
    n = r['n_semanas']
    combinacion_tag = r.get('combinacion_tag')
    combinacion_texto = r.get('combinacion_texto')

    # ---- 1) Por qué se clasificó así esta semana ----
    partes_fase = []
    if n < 3:
        partes_fase.append(
            f"Con solo {n} semana(s) cargada(s) todavía no alcanza para hablar de una 'fase' de "
            "posicionamiento: la tendencia recién se calcula a partir de 3 semanas y el percentil a "
            "partir de 5, para no confundir el ruido de una sola semana con un giro real."
        )
    else:
        if pct is not None:
            if pct_class == 'EXTREME LONG':
                partes_fase.append(
                    f"El Asset Manager Net está en el percentil {pct:.0f}% de todo el historial cargado: "
                    "casi nunca estuvo más comprado que ahora. Es una zona de <b>posible saturación "
                    "compradora institucional</b> — no implica un giro inmediato, pero sí que queda poco "
                    "margen para que entre capital estructural nuevo."
                )
            elif pct_class == 'EXTREME SHORT':
                partes_fase.append(
                    f"El percentil {pct:.0f}% ubica al Asset Manager en una zona de <b>posible piso "
                    "institucional</b>: el posicionamiento vendedor está entre los más extremos del "
                    "historial disponible."
                )
            elif pct_class in ('HIGH POSITIONING', 'LOW POSITIONING'):
                partes_fase.append(
                    f"El percentil {pct:.0f}% ubica al Asset Manager en zona {pct_class}: sesgado pero sin "
                    "llegar todavía a un extremo histórico, propio de una fase de acumulación/distribución "
                    "institucional en curso."
                )
            else:
                partes_fase.append(
                    f"El percentil {pct:.0f}% del Asset Manager cae en zona NORMAL (entre 30% y 70%): el "
                    "posicionamiento institucional actual no es, por sí solo, señal de extremo."
                )
        if tendencia:
            partes_fase.append(
                f"La pendiente del Asset Manager Net en las últimas semanas es {tendencia.lower()}. Se usa "
                "la pendiente y no el último dato suelto para distinguir una fase sostenida de un rebote "
                "de una sola semana."
            )
        cambio_interp = r.get('cambio_interp')
        if cambio_interp:
            partes_fase.append(
                f"El cruce Long/Short del Asset Manager esta última semana ({cambio_interp}) confirma en "
                "qué lado se movió el capital estructural: nunca se mira el neto solo, sino si subieron "
                "los largos, bajaron los cortos, o ambos a la vez."
            )

    # ---- 2) Dinero fresco vs. Cobertura (choque AM / LEV / OI) ----
    partes_oi = []
    if combinacion_tag is None:
        partes_oi.append(
            "Todavía no hay dos semanas consecutivas completas para cruzar el cambio del Net (Asset "
            "Manager y Leveraged Funds) con el cambio del Open Interest, que es la clave del Módulo 2 "
            "para distinguir dinero fresco de simple cobertura."
        )
    else:
        partes_oi.append(
            "Se aplica la matriz del Módulo 2: se cruza primero el Asset Manager (capital estructural) y, "
            "si no aplica, el Leveraged Funds (especulativo) contra el Open Interest, porque el mismo "
            "movimiento de Net puede significar cosas opuestas según lo que haga el Open Interest."
        )
        if combinacion_tag == 'ACUMULACIÓN INSTITUCIONAL CON DINERO FRESCO':
            partes_oi.append(
                f"Esta semana el AM Net subió ({am_chg:+,.0f}) y el Open Interest también subió "
                f"({oi_chg:+,.0f}): <b>dinero fresco institucional entrando a comprar</b> — se abren "
                "contratos nuevos, no es solo recompra de cortos."
            )
        elif combinacion_tag == 'COBERTURA / SHORT COVERING INSTITUCIONAL':
            partes_oi.append(
                f"Esta semana el AM Net subió ({am_chg:+,.0f}) pero el Open Interest bajó ({oi_chg:+,.0f}): "
                "<b>cobertura / short covering institucional</b>. La mejora del Net es más frágil de lo "
                "que parece, porque no viene acompañada de dinero nuevo."
            )
        elif combinacion_tag == 'CAPITULACIÓN / COBERTURA DE CORTOS ESPECULATIVA':
            partes_oi.append(
                f"Esta semana el LEV Net bajó ({lev_chg:+,.0f}) y el Open Interest también bajó "
                f"({oi_chg:+,.0f}): <b>capitulación especulativa</b>. Son especuladores cerrando "
                "posiciones, no vendedores nuevos entrando con fuerza."
            )
        elif combinacion_tag == 'ENTRADA DE VENTA ESPECULATIVA AGRESIVA':
            partes_oi.append(
                f"Esta semana el LEV Net bajó ({lev_chg:+,.0f}) mientras el Open Interest subió "
                f"({oi_chg:+,.0f}): <b>venta especulativa agresiva</b>, con convicción y dinero fresco "
                "del lado vendedor."
            )
        else:
            partes_oi.append(f"{combinacion_texto}")

    # ---- 3) Divergencia Activa Institucional vs. Especulativa ----
    partes_divergencia = []
    div_tag = r.get('divergencia_tag')
    div_texto = r.get('divergencia_texto')
    if div_tag is None:
        partes_divergencia.append(
            "Todavía no hay suficiente historial para evaluar una divergencia confiable entre Asset "
            "Managers y Leveraged Funds."
        )
    else:
        partes_divergencia.append(
            "Se cruza la dirección del Asset Manager (manos fuertes / capital estructural) contra el "
            "percentil y el comportamiento reciente del Leveraged Funds (especuladores), además de la "
            "variación porcentual del Open Interest, para detectar un choque extremo de posturas (Módulo 3)."
        )
        if div_tag == 'SIN DIVERGENCIA EXTREMA':
            partes_divergencia.append(f"Por ahora no hay ese choque: {div_texto}")
        else:
            partes_divergencia.append(f"<b>{div_tag}</b>: {div_texto}")

    # ---- 4) Qué vigilar en el Open Interest la próxima semana ----
    partes_vigilar = []
    if combinacion_tag is None:
        partes_vigilar.append(
            "Por ahora, con el historial disponible, lo primero es simplemente sumar más semanas: recién "
            "con 3 se puede calcular la tendencia y con 5 el percentil de posicionamiento."
        )
    elif combinacion_tag == 'COBERTURA / SHORT COVERING INSTITUCIONAL':
        partes_vigilar.append(
            "Como el diagnóstico actual es cobertura / short covering institucional, vigilá si el próximo "
            "reporte muestra el Open Interest <b>volviendo a subir</b> mientras el AM Net sigue mejorando: "
            "eso confirmaría que después de cerrar cortos empieza a entrar capital estructural nuevo de "
            "verdad. Si el Open Interest sigue cayendo mientras el AM Net se estanca, el movimiento se está "
            "quedando sin combustible."
        )
    elif combinacion_tag == 'CAPITULACIÓN / COBERTURA DE CORTOS ESPECULATIVA':
        partes_vigilar.append(
            "Como el diagnóstico actual es capitulación especulativa, vigilá si el Open Interest <b>deja "
            "de caer y empieza a subir</b> junto con un Leveraged Funds Net que deja de retroceder: eso "
            "marcaría el fin de la liquidación. Si el Open Interest sigue en baja y el LEV Net sigue "
            "perforando mínimos, la capitulación todavía no terminó."
        )
    elif combinacion_tag == 'ACUMULACIÓN INSTITUCIONAL CON DINERO FRESCO':
        partes_vigilar.append(
            "Como el diagnóstico actual es entrada de dinero fresco institucional comprador, la alerta "
            "sería que el Open Interest crezca mucho más rápido que el AM Net (o que el AM Net se aplane): "
            "conviene revisar si ese nuevo interés abierto lo está tomando el lado vendedor (Leveraged "
            "Funds o Dealer como contraparte), lo que moderaría la lectura alcista."
        )
    elif combinacion_tag == 'ENTRADA DE VENTA ESPECULATIVA AGRESIVA':
        partes_vigilar.append(
            "Como el diagnóstico actual es venta especulativa agresiva, vigilá si el Open Interest sigue "
            "expandiéndose semana a semana junto con nuevas bajas del LEV Net: eso confirmaría presión "
            "bajista especulativa sostenida, y sobre todo si el Asset Manager empieza a acompañar esa baja "
            "(lo que le sumaría respaldo institucional real a la caída)."
        )
    else:
        partes_vigilar.append(
            "Vigilá el próximo cruce entre Asset Manager, Leveraged Funds y Open Interest: todavía no dio "
            "una combinación direccional clara como para anticipar qué mirar puntualmente."
        )
    if pct_class in ('EXTREME LONG', 'EXTREME SHORT') and pct is not None:
        partes_vigilar.append(
            f"Además, al estar el Asset Manager en {pct_class} (percentil {pct:.0f}%), cualquier próximo "
            "reporte que muestre el AM Net empezando a revertir —aunque sea levemente— desde este extremo "
            "es una alerta temprana de agotamiento de la fase actual."
        )

    return f"""
    <div class="interp-card">
      <div class="interp-header">💡 Guía de Aprendizaje Semanal — {r['market']}</div>
      <p><b>1. Por qué se clasificó así esta semana</b><br>{' '.join(partes_fase)}</p>
      <p><b>2. Dinero fresco vs. cobertura</b><br>{' '.join(partes_oi)}</p>
      <p><b>3. Divergencia Activa Institucional vs. Especulativa</b><br>{' '.join(partes_divergencia)}</p>
      <p><b>4. Qué vigilar en el Open Interest la próxima semana</b><br>{' '.join(partes_vigilar)}</p>
    </div>
    """


def _tff_resumen_market(df_market):
    """Procesa todas las semanas de un mercado y devuelve un dict con
    el resumen final + la serie completa (para graficar)."""
    df = _tff_calcular_serie(df_market)
    n = len(df)
    if n == 0:
        return None

    fila = df.iloc[-1]
    am_net_series = df['AM Net']
    lev_net_series = df['LEV Net']

    tendencia = _tff_tendencia(am_net_series) if n >= 3 else None
    pct = _tff_percentil(am_net_series) if n >= 5 else None
    pct_class, pct_color = _tff_clasificar_percentil(pct)
    consistencia = _tff_consistencia(am_net_series) if n >= 3 else None
    cambio_interp = _tff_interp_cambio_semanal(fila.get('AM Long Chg'), fila.get('AM Short Chg'))
    oi_texto, oi_tag = _tff_interp_oi(fila.get('AM Net Chg'), fila.get('OI Chg'))
    score = _tff_score(fila, am_net_series, pct, tendencia, consistencia, oi_tag)
    score_label, score_color, score_emoji = _tff_clasificar_score(score)

    señal = _tff_señal_final(score, cambio_interp, pct_class)

    combinacion_tag, combinacion_texto = _tff_interp_combinacion(
        fila.get('AM Net Chg'), fila.get('LEV Net Chg'), fila.get('OI Chg')
    )

    # MÓDULO 3 — Divergencia Asset Manager vs. Leveraged Funds
    pct_lev = _tff_percentil(lev_net_series) if n >= 5 else None
    divergencia_tag, divergencia_texto, divergencia_color = _tff_clasificar_divergencia(
        pct, pct_lev, fila.get('LEV Net'), fila.get('LEV Net Chg'), fila.get('OI Pct Chg'), fila.get('AM Net Chg')
    )

    texto = _tff_texto_interpretacion(
        df_market['Contract Market Name'].iloc[0], fila, tendencia, pct, pct_class, oi_texto, n
    )

    return dict(
        market=df_market['Contract Market Name'].iloc[0],
        n_semanas=n,
        fecha=fila['Report Date'],
        am_long=fila.get('Asset Manager Long'),
        am_short=fila.get('Asset Manager Short'),
        am_net=fila.get('AM Net'),
        am_net_chg=fila.get('AM Net Chg'),
        lev_long=fila.get('Leveraged Funds Long'),
        lev_short=fila.get('Leveraged Funds Short'),
        lev_net=fila.get('LEV Net'),
        lev_net_chg=fila.get('LEV Net Chg'),
        oi=fila.get('Open Interest'),
        oi_chg=fila.get('OI Chg'),
        oi_pct_chg=fila.get('OI Pct Chg'),
        tendencia=tendencia,
        percentil=pct,
        pct_class=pct_class,
        pct_color=pct_color,
        pct_lev=pct_lev,
        cambio_interp=cambio_interp,
        oi_texto=oi_texto,
        combinacion_tag=combinacion_tag,
        combinacion_texto=combinacion_texto,
        score=score,
        score_label=score_label,
        score_color=score_color,
        score_emoji=score_emoji,
        señal_final=señal,
        texto=texto,
        divergencia_tag=divergencia_tag,
        divergencia_texto=divergencia_texto,
        divergencia_color=divergencia_color,
        df=df,
    )


# ------------------------------------------------------------------
#  HELPERS DE UI (reutilizan clases CSS ya definidas en la app)
# ------------------------------------------------------------------

def _fmt_n(v, dec=0):
    if v is None or pd.isna(v):
        return 'N/A'
    return f'{v:,.{dec}f}'


def _tff_kpi_cards(items):
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


def _tff_fig_evolucion(df, columna, titulo, color):
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df['Report Date'], y=df[columna], mode='lines+markers',
        line=dict(color=color, width=2.2), marker=dict(size=5),
        fill='tozeroy', fillcolor='rgba(58,123,213,0.08)',
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
#  TAB 1 — CARGA DE DATOS (solo ADMIN_EMAIL)
# ------------------------------------------------------------------

def _tff_tab_carga(supabase, es_admin):
    if not es_admin:
        st.info("🔒 Solo el administrador puede cargar, editar o borrar datos TFF. "
                "Podés consultar todo lo cargado en las pestañas **Análisis General** e **Individual**.")
        return

    st.markdown("""
    <div class="info-banner">
      Los datos NO se descargan automáticamente. Cargá vos las semanas de cada mercado
      (índice, forex o cripto) con el formulario, la tabla editable o importando un CSV con las
      columnas exactas del reporte TFF.
    </div>
    """, unsafe_allow_html=True)

    df_actual = st.session_state['tff_data']

    # ── Plantilla descargable ──────────────────────────────────
    c_tpl1, c_tpl2 = st.columns([3, 1])
    with c_tpl2:
        st.download_button(
            '⬇️ Descargar plantilla CSV',
            data=_tff_template_df().to_csv(index=False).encode('utf-8'),
            file_name='plantilla_tff.csv', mime='text/csv',
            use_container_width=True, key='tff_download_tpl',
        )

    st.markdown('<div class="sec-title">📝 Cargar una semana</div>', unsafe_allow_html=True)

    markets_existentes = sorted(df_actual['Contract Market Name'].unique().tolist()) if not df_actual.empty else []
    opciones_market = ['➕ Nuevo mercado'] + markets_existentes
    sel_market = st.selectbox('Contract Market Name', opciones_market, key='tff_sel_market')
    if sel_market == '➕ Nuevo mercado':
        nombre_market = st.text_input('Nombre del nuevo mercado', key='tff_nuevo_nombre',
                                       placeholder='Ej: E-MINI S&P 500, EURO FX, BITCOIN')
    else:
        nombre_market = sel_market

    with st.form('tff_form_semana', clear_on_submit=False):
        c1, c2 = st.columns(2)
        with c1:
            fecha = st.date_input('Report Date', key='tff_fecha')
        with c2:
            oi = st.number_input('Open Interest', min_value=0.0, step=1.0, key='tff_oi')

        st.markdown('**Asset Manager / Institutional** (principal foco del análisis)')
        a1, a2, a3 = st.columns(3)
        with a1: am_l = st.number_input('Long', min_value=0.0, step=1.0, key='tff_am_l')
        with a2: am_s = st.number_input('Short', min_value=0.0, step=1.0, key='tff_am_s')
        with a3: am_sp = st.number_input('Spread', min_value=0.0, step=1.0, key='tff_am_sp')

        st.markdown('**Leveraged Funds** (especulativo)')
        l1, l2, l3 = st.columns(3)
        with l1: lev_l = st.number_input('Long ', min_value=0.0, step=1.0, key='tff_lev_l')
        with l2: lev_s = st.number_input('Short ', min_value=0.0, step=1.0, key='tff_lev_s')
        with l3: lev_sp = st.number_input('Spread ', min_value=0.0, step=1.0, key='tff_lev_sp')

        st.markdown('**Dealer Intermediary**')
        d1, d2, d3 = st.columns(3)
        with d1: deal_l = st.number_input('Long  ', min_value=0.0, step=1.0, key='tff_deal_l')
        with d2: deal_s = st.number_input('Short  ', min_value=0.0, step=1.0, key='tff_deal_s')
        with d3: deal_sp = st.number_input('Spread  ', min_value=0.0, step=1.0, key='tff_deal_sp')

        st.markdown('**Other Reportables**')
        o1, o2, o3 = st.columns(3)
        with o1: oth_l = st.number_input('Long   ', min_value=0.0, step=1.0, key='tff_oth_l')
        with o2: oth_s = st.number_input('Short   ', min_value=0.0, step=1.0, key='tff_oth_s')
        with o3: oth_sp = st.number_input('Spread   ', min_value=0.0, step=1.0, key='tff_oth_sp')

        enviado = st.form_submit_button('➕ Agregar semana', use_container_width=True)

    if enviado:
        if not nombre_market or not nombre_market.strip():
            st.error('Ingresá el nombre del mercado.')
        else:
            fila_nueva = pd.DataFrame([{
                'Report Date': pd.Timestamp(fecha), 'Contract Market Name': nombre_market.strip(),
                'Open Interest': oi,
                'Asset Manager Long': am_l, 'Asset Manager Short': am_s, 'Asset Manager Spread': am_sp,
                'Leveraged Funds Long': lev_l, 'Leveraged Funds Short': lev_s, 'Leveraged Funds Spread': lev_sp,
                'Dealer Long': deal_l, 'Dealer Short': deal_s, 'Dealer Spread': deal_sp,
                'Other Reportables Long': oth_l, 'Other Reportables Short': oth_s, 'Other Reportables Spread': oth_sp,
            }])
            try:
                _tff_guardar_upsert(supabase, fila_nueva)
                st.success(f'Semana del {fecha} agregada para {nombre_market.strip()}.')
                st.rerun()
            except Exception as e:
                st.error(f'❌ Error al guardar en Supabase: {e}')

    # ── Importar CSV propio (carga masiva) ─────────────────────
    st.markdown('<div class="sec-title">📂 Importar CSV (carga masiva)</div>', unsafe_allow_html=True)
    st.caption('Subí un CSV con varias filas (una por semana/mercado). Usá la plantilla de arriba para respetar el formato exacto de columnas.')
    archivo = st.file_uploader('Subí un CSV con las columnas de la plantilla', type=['csv'], key='tff_uploader')
    if archivo is not None:
        try:
            df_csv = pd.read_csv(archivo)
        except Exception as e:
            st.error(f'No se pudo leer el archivo: {e}')
            df_csv = None

        if df_csv is not None:
            faltantes = [c for c in TFF_COLUMNAS if c not in df_csv.columns]
            if faltantes:
                st.error(f'Faltan columnas requeridas: {", ".join(faltantes)}')
            else:
                df_csv = df_csv[TFF_COLUMNAS].copy()

                # --- Validación fila por fila ---
                fechas_parseadas = pd.to_datetime(df_csv['Report Date'], errors='coerce')
                markets_ok = df_csv['Contract Market Name'].astype(str).str.strip().str.len() > 0
                filas_invalidas = df_csv[fechas_parseadas.isna() | ~markets_ok]
                df_validas = df_csv[~(fechas_parseadas.isna() | ~markets_ok)].copy()

                # --- Duplicados dentro del mismo CSV (misma semana+mercado repetida) ---
                clave = (
                    df_validas['Contract Market Name'].astype(str).str.strip() + '|' +
                    fechas_parseadas[df_validas.index].dt.strftime('%Y-%m-%d')
                )
                dup_mask = clave.duplicated(keep='last')
                n_dup_internos = int(dup_mask.sum())

                # --- Nuevas vs. actualizaciones respecto a lo ya cargado en Supabase ---
                df_existente = st.session_state['tff_data']
                if not df_existente.empty:
                    clave_existente = set(
                        df_existente['Contract Market Name'].astype(str).str.strip() + '|' +
                        pd.to_datetime(df_existente['Report Date']).dt.strftime('%Y-%m-%d')
                    )
                else:
                    clave_existente = set()

                claves_finales = clave[~dup_mask]
                n_actualiza = int(claves_finales.isin(clave_existente).sum())
                n_nuevas = len(claves_finales) - n_actualiza

                # --- Resumen antes de confirmar ---
                c_r1, c_r2, c_r3, c_r4 = st.columns(4)
                c_r1.metric('Filas válidas', len(claves_finales))
                c_r2.metric('Semanas nuevas', n_nuevas)
                c_r3.metric('Semanas a actualizar', n_actualiza)
                c_r4.metric('Filas inválidas', len(filas_invalidas))

                if n_dup_internos > 0:
                    st.warning(f'⚠️ {n_dup_internos} fila(s) duplicada(s) dentro del mismo CSV (misma semana+mercado). Se usará la última de cada grupo.')

                if not filas_invalidas.empty:
                    st.error(f'❌ {len(filas_invalidas)} fila(s) con "Report Date" o "Contract Market Name" inválido — no se importarán:')
                    st.dataframe(filas_invalidas, use_container_width=True)

                st.markdown('**Vista previa de filas a importar:**')
                st.dataframe(df_validas.head(15), use_container_width=True)

                if st.button(f'✅ Importar {len(claves_finales)} fila(s) al dataset', key='tff_import_csv', disabled=df_validas.empty):
                    try:
                        _tff_guardar_upsert(supabase, df_validas)
                        st.success(f'{n_nuevas} semana(s) nueva(s) agregada(s) y {n_actualiza} actualizada(s).')
                        st.rerun()
                    except Exception as e:
                        st.error(f'❌ Error al importar a Supabase: {e}')

    # ── Editor de tabla completa ─────────────────────────────────
    st.markdown('<div class="sec-title">✏️ Editar datos cargados</div>', unsafe_allow_html=True)
    df_actual = st.session_state['tff_data']
    if df_actual.empty:
        st.info('Todavía no cargaste ninguna semana.')
        return

    df_editable = df_actual.copy()
    df_editable['Report Date'] = pd.to_datetime(df_editable['Report Date']).dt.date

    editado = st.data_editor(
        df_editable, use_container_width=True, num_rows='dynamic',
        key='tff_editor_tabla', height=min(500, max(150, len(df_editable) * 36 + 60)),
    )

    cg1, cg2 = st.columns(2)
    with cg1:
        if st.button('💾 Guardar cambios de la tabla', use_container_width=True, key='tff_guardar_tabla'):
            df_norm = _tff_normalizar(editado)
            try:
                # Reemplazo completo (no upsert) porque desde acá también
                # se pueden borrar filas.
                _tff_reemplazar_todo(supabase, df_norm)
                st.success('Cambios guardados.')
                st.rerun()
            except Exception as e:
                st.error(f'❌ Error al guardar en Supabase: {e}')
    with cg2:
        if st.button('🗑️ Borrar TODOS los datos cargados', use_container_width=True, key='tff_borrar_todo'):
            try:
                _tff_borrar_todo(supabase)
                st.warning('Se borraron todos los datos TFF cargados.')
                st.rerun()
            except Exception as e:
                st.error(f'❌ Error al borrar en Supabase: {e}')


# ------------------------------------------------------------------
#  TAB 2 — ANÁLISIS GENERAL (tabla final) — visible para todos
# ------------------------------------------------------------------

def _tff_tab_general():
    df = st.session_state['tff_data']
    if df.empty:
        st.info('Todavía no hay datos TFF cargados.')
        return

    resumenes = []
    for market, grupo in df.groupby('Contract Market Name'):
        r = _tff_resumen_market(grupo)
        if r:
            resumenes.append(r)

    if not resumenes:
        st.warning('No se pudo procesar ningún mercado.')
        return

    n_alcista = sum(1 for r in resumenes if r['score'] is not None and r['score'] > 60)
    n_bajista = sum(1 for r in resumenes if r['score'] is not None and r['score'] < 40)
    n_extremo = sum(1 for r in resumenes if r['pct_class'] in ('EXTREME LONG', 'EXTREME SHORT'))
    n_divergencia = sum(
        1 for r in resumenes
        if r.get('divergencia_tag') in ('DIVERGENCIA ALCISTA DE SUELO', 'DIVERGENCIA BAJISTA DE TECHO')
    )
    n_iliquidez = sum(1 for r in resumenes if r.get('divergencia_tag') == 'DIVERGENCIA DE AGOTAMIENTO POR ILIQUIDEZ')

    _tff_kpi_cards([
        ('Mercados cargados', str(len(resumenes)), 'Con al menos 1 semana', C_ACENT),
        ('🟢 Sesgo alcista', str(n_alcista), 'TFF Score > 60', C_GREEN),
        ('🔴 Sesgo bajista', str(n_bajista), 'TFF Score < 40', C_RED),
        ('⚡ Extremos', str(n_extremo), 'Percentil AM ≤10% o ≥90%', C_YELLOW),
        ('🔀 Divergencias', str(n_divergencia), 'AM vs. Leveraged Funds', C_LGREEN),
        ('⚠️ Agotamiento', str(n_iliquidez), 'Caída de OI > 1.5%', C_LRED),
    ])

    filas = []
    for r in resumenes:
        filas.append({
            'Mercado': r['market'],
            'Fecha': r['fecha'].strftime('%Y-%m-%d') if pd.notna(r['fecha']) else 'N/A',
            'AM Long': _fmt_n(r['am_long']),
            'AM Short': _fmt_n(r['am_short']),
            'AM Net': _fmt_n(r['am_net']),
            'Cambio AM Net': _fmt_n(r['am_net_chg']),
            'LEV Net': _fmt_n(r['lev_net']),
            'Open Interest': _fmt_n(r['oi']),
            'Cambio OI': _fmt_n(r['oi_chg']),
            'Tendencia AM': r['tendencia'] or 'N/A',
            'Percentil AM': f"{r['percentil']:.0f}%" if r['percentil'] is not None else 'N/A',
            'Estado': r['pct_class'],
            'TFF Score': r['score'] if r['score'] is not None else np.nan,
            'Señal Final': r['señal_final'],
            'Divergencia': r.get('divergencia_tag') or 'N/A',
            'Semanas': r['n_semanas'],
        })

    df_tabla = pd.DataFrame(filas).sort_values('TFF Score', ascending=False, na_position='last')

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

    def _color_divergencia(v):
        colores = {
            'DIVERGENCIA ALCISTA DE SUELO': C_GREEN,
            'DIVERGENCIA BAJISTA DE TECHO': C_RED,
            'DIVERGENCIA DE AGOTAMIENTO POR ILIQUIDEZ': C_YELLOW,
            'SIN DIVERGENCIA EXTREMA': C_MUTED,
        }
        return f'color:{colores.get(v, "#6b7d9a")};font-weight:700'

    _map = 'map' if hasattr(df_tabla.style, 'map') else 'applymap'
    styled = (df_tabla.style
              .pipe(lambda s: getattr(s, _map)(_color_score, subset=['TFF Score']))
              .pipe(lambda s: getattr(s, _map)(_color_estado, subset=['Estado']))
              .pipe(lambda s: getattr(s, _map)(_color_divergencia, subset=['Divergencia']))
              .format({'TFF Score': lambda v: f'{v:.0f}' if pd.notna(v) else 'N/A'})
              .set_properties(**{'background-color': '#0d1117', 'color': '#e6edf3', 'border': '1px solid #21262d'})
              .set_table_styles([
                  {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', '#e6edf3'),
                      ('font-weight', '700'), ('text-align', 'center'),
                      ('border-bottom', '2px solid #3a7bd5'), ('font-size', '11px')]},
                  {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]},
              ]))
    st.dataframe(styled, use_container_width=True, height=min(600, max(150, len(df_tabla) * 38 + 60)))
    st.caption('El TFF Score y las interpretaciones son estimaciones probabilísticas basadas únicamente en datos de posicionamiento TFF, no en precio.')


# ------------------------------------------------------------------
#  TAB 3 — ANÁLISIS INDIVIDUAL — visible para todos
# ------------------------------------------------------------------

def _tff_tab_individual():
    df = st.session_state['tff_data']
    if df.empty:
        st.info('Todavía no hay datos TFF cargados.')
        return

    markets = sorted(df['Contract Market Name'].unique().tolist())
    market_sel = st.selectbox('Seleccioná un mercado', markets, key='tff_ind_sel')

    grupo = df[df['Contract Market Name'] == market_sel]
    r = _tff_resumen_market(grupo)
    if r is None:
        st.warning('No hay datos válidos para este mercado.')
        return

    st.markdown(f"""
    <div style="text-align:center;margin-bottom:14px">
      <div style="font-size:20px;font-weight:800;color:#e6edf3">{r['market']}</div>
      <div style="font-size:12px;color:#6b7d9a">Última semana: {r['fecha'].strftime('%Y-%m-%d') if pd.notna(r['fecha']) else 'N/A'} · {r['n_semanas']} semana(s) cargada(s)</div>
    </div>
    """, unsafe_allow_html=True)

    score_txt = f"{r['score']:.0f}/100" if r['score'] is not None else 'N/A'
    _tff_kpi_cards([
        ('TFF Score', score_txt, f"{r['score_emoji']} {r['score_label']}", r['score_color']),
        ('Asset Manager Net', _fmt_n(r['am_net']), f"Cambio: {_fmt_n(r['am_net_chg'])}", C_ACENT),
        ('Leveraged Funds Net', _fmt_n(r['lev_net']), f"Cambio: {_fmt_n(r['lev_net_chg'])}", C_YELLOW),
        ('Percentil / Tendencia AM', f"{r['percentil']:.0f}%" if r['percentil'] is not None else 'N/A',
         r['tendencia'] or 'N/A', r['pct_color']),
    ])

    st.markdown(f"""
    <div class="interp-card">
      <div class="interp-header">{r['score_emoji']} {r['market']} · {r['señal_final']}</div>
      {r['texto']}
    </div>
    """, unsafe_allow_html=True)

    # ── Matriz Net + Open Interest (Módulo 2) ──
    if r.get('combinacion_tag'):
        st.markdown(f"""
        <div class="interp-card">
          <div class="interp-header">🔎 {r['combinacion_tag']}</div>
          {r['combinacion_texto']}
        </div>
        """, unsafe_allow_html=True)

    # ── Divergencia Institucional vs. Especulativa (Módulo 3) ──
    div_tag = r.get('divergencia_tag')
    if div_tag and div_tag != 'SIN DIVERGENCIA EXTREMA':
        div_emoji = {
            'DIVERGENCIA ALCISTA DE SUELO': '🟢',
            'DIVERGENCIA BAJISTA DE TECHO': '🔴',
            'DIVERGENCIA DE AGOTAMIENTO POR ILIQUIDEZ': '⚠️',
        }.get(div_tag, '⚪')
        st.markdown(f"""
        <div class="interp-card" style="border-left:3px solid {r['divergencia_color']}">
          <div class="interp-header">{div_emoji} {div_tag}</div>
          {r['divergencia_texto']}
        </div>
        """, unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1: st.metric('AM Long', _fmt_n(r['am_long']))
    with c2: st.metric('AM Short', _fmt_n(r['am_short']))
    with c3: st.metric('Estado de Posicionamiento', r['pct_class'])

    if r['n_semanas'] >= 2:
        tab_g1, tab_g2, tab_g3, tab_g4, tab_g5 = st.tabs([
            '📈 AM Long', '📉 AM Short', '⚖️ AM Net', '🎯 LEV Net', '📊 Open Interest',
        ])
        with tab_g1:
            st.plotly_chart(
                _tff_fig_evolucion(r['df'], 'Asset Manager Long', f"{r['market']} — Asset Manager Long", C_LGREEN),
                use_container_width=True, config=PLOTLY_CONFIG, key=f'tff_fig_amlong_{market_sel}',
            )
        with tab_g2:
            st.plotly_chart(
                _tff_fig_evolucion(r['df'], 'Asset Manager Short', f"{r['market']} — Asset Manager Short", C_LRED),
                use_container_width=True, config=PLOTLY_CONFIG, key=f'tff_fig_amshort_{market_sel}',
            )
        with tab_g3:
            st.plotly_chart(
                _tff_fig_evolucion(r['df'], 'AM Net', f"{r['market']} — Asset Manager Net", C_ACENT),
                use_container_width=True, config=PLOTLY_CONFIG, key=f'tff_fig_amnet_{market_sel}',
            )
        with tab_g4:
            st.plotly_chart(
                _tff_fig_evolucion(r['df'], 'LEV Net', f"{r['market']} — Leveraged Funds Net", C_YELLOW),
                use_container_width=True, config=PLOTLY_CONFIG, key=f'tff_fig_levnet_{market_sel}',
            )
        with tab_g5:
            st.plotly_chart(
                _tff_fig_evolucion(r['df'], 'Open Interest', f"{r['market']} — Open Interest", C_MONSTER),
                use_container_width=True, config=PLOTLY_CONFIG, key=f'tff_fig_oi_{market_sel}',
            )
    else:
        st.info('Se necesitan al menos 2 semanas cargadas para graficar la evolución.')

    # ── Guía de Aprendizaje Semanal (Módulo 4 — explicación didáctica) ──
    with st.expander('💡 Guía de Aprendizaje Semanal', expanded=False):
        st.markdown(_tff_guia_aprendizaje(r), unsafe_allow_html=True)

    # ── Complementarios: Leveraged Funds, Dealer, Other Reportables ──
    with st.expander('👥 Leveraged Funds, Dealer y Other Reportables (contexto)', expanded=False):
        st.caption('Leveraged Funds se usa además para el análisis de divergencias (Módulo 3, ver Guía de Aprendizaje Semanal); Dealer y Other Reportables son puramente contexto y no se interpretan como señal direccional principal.')
        fila = r['df'].iloc[-1]
        cc1, cc2, cc3 = st.columns(3)
        with cc1:
            st.markdown('**Leveraged Funds**')
            st.write(f"Long: {_fmt_n(fila.get('Leveraged Funds Long'))}")
            st.write(f"Short: {_fmt_n(fila.get('Leveraged Funds Short'))}")
            st.write(f"Spread: {_fmt_n(fila.get('Leveraged Funds Spread'))}")
            st.write(f"Net: {_fmt_n(fila.get('LEV Net'))}")
            if r.get('pct_lev') is not None:
                st.write(f"Percentil histórico: {r['pct_lev']:.0f}%")
        with cc2:
            st.markdown('**Dealer Intermediary**')
            st.write(f"Long: {_fmt_n(fila.get('Dealer Long'))}")
            st.write(f"Short: {_fmt_n(fila.get('Dealer Short'))}")
            st.write(f"Spread: {_fmt_n(fila.get('Dealer Spread'))}")
            st.write(f"Net: {_fmt_n(fila.get('Dealer Net'))}")
        with cc3:
            st.markdown('**Other Reportables**')
            st.write(f"Long: {_fmt_n(fila.get('Other Reportables Long'))}")
            st.write(f"Short: {_fmt_n(fila.get('Other Reportables Short'))}")
            st.write(f"Spread: {_fmt_n(fila.get('Other Reportables Spread'))}")
            st.write(f"Net: {_fmt_n(fila.get('Other Net'))}")

    with st.expander('📋 Ver tabla semanal completa', expanded=False):
        cols_show = [
            'Report Date', 'Asset Manager Long', 'Asset Manager Short', 'AM Net', 'AM Net Chg',
            'Leveraged Funds Long', 'Leveraged Funds Short', 'LEV Net', 'LEV Net Chg',
            'Open Interest', 'OI Chg', 'OI Pct Chg',
        ]
        df_show = r['df'][cols_show].copy()
        df_show['Report Date'] = df_show['Report Date'].dt.strftime('%Y-%m-%d')
        st.dataframe(df_show, use_container_width=True, height=min(400, len(df_show) * 36 + 60))


# ------------------------------------------------------------------
#  ENTRY POINT
# ------------------------------------------------------------------

def modulo_tff(supabase, user_id, user_email):
    """Uso desde app.py:
        from modulo_tff import modulo_tff
        modulo_tff(supabase, USER_ID, st.session_state['usuario'].email)

    Cualquiera que abra la app ve el análisis (Análisis General e
    Individual). Solo la cuenta ADMIN_EMAIL ve el formulario de carga,
    edición e importación en la pestaña "Cargar Datos" — la protección
    real está en las políticas RLS de tff_schema.sql.
    """
    es_admin = _tff_es_admin(user_email)

    try:
        registros = _tff_obtener_registros(supabase)
        st.session_state['tff_data'] = _tff_records_to_df(registros)
        error_carga = None
    except Exception as e:
        st.session_state.setdefault('tff_data', _tff_template_df())
        error_carga = str(e)

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1a2a 0%,#0a1c14 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #3a7bd5;
         border-radius:14px; padding:28px 32px; margin-bottom:24px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">
        📑 Análisis TFF — Traders in Financial Futures
      </div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Interpretación automática del posicionamiento de <b style="color:#3a7bd5">Asset Manager /
        Institutional</b> frente a <b style="color:#e3b341">Leveraged Funds</b>, a partir de los datos TFF
        que vos cargás manualmente (índices, forex y criptomonedas CME). No usa precio, RSI, MACD, medias
        móviles ni ningún dato externo — solo Open Interest y posicionamiento por categoría institucional.
      </div>
    </div>
    """, unsafe_allow_html=True)

    if error_carga:
        st.error(f'⚠️ No se pudo leer tff_data desde Supabase: {error_carga}')

    tab_carga, tab_general, tab_individual = st.tabs([
        '📥 Cargar Datos', '📊 Análisis General', '🔍 Análisis Individual',
    ])

    with tab_carga:
        _tff_tab_carga(supabase, es_admin)
    with tab_general:
        _tff_tab_general()
    with tab_individual:
        _tff_tab_individual()
