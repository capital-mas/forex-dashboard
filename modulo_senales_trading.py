# ==============================================================
#  MÓDULO SEÑALES DE TRADING — Streamlit + Supabase
#  Mismo patrón que modulo_calendario.py: solo ADMIN_EMAIL publica
#  señales, todos los usuarios pueden verlas y simular resultados
#  con su propio capital. La protección real (a prueba de gente que
#  mire el código) está en las políticas RLS de Supabase — ver
#  senales_trading_schema.sql. El email de acá abajo tiene que
#  coincidir EXACTAMENTE con el de esas políticas.
#
#  CAMBIOS DE ESTA VERSIÓN:
#   - NUEVO modo en el Simulador de Capital: "🔁 Replicar la posición
#     del publicador". La persona pone UN solo número (su margen) y la
#     app copia la posición del admin tal cual: mismas entradas, mismos
#     precios, mismo apalancamiento en cada una, y el margen y el costo
#     de apertura de cada entrada se escalan en la misma proporción.
#     Ej: si el admin puso 100 de margen en cada una de sus 2 entradas y
#     el usuario pone 10 (referido a la 1ª entrada), su margen queda en
#     10 en cada entrada. El precio de liquidación resulta el mismo que
#     el del admin (la escala no lo cambia) y la simulación verifica
#     contra el historial si el precio llegó a tocarlo.
#   - CAMBIO: las entradas ya NO tienen "peso relativo". Ahora cada
#     entrada se carga con datos reales de la operación:
#       · Precio de la entrada
#       · Costo de apertura (USD: comisión/spread que pagaste)
#       · Apalancamiento que usaste en esa entrada
#       · Margen (USD) que agregaste a la posición con esa entrada
#     A partir de eso la app calcula sola, para toda la posición:
#       · Tamaño nominal = margen × apalancamiento (por entrada)
#       · Unidades = nominal / precio (por entrada)
#       · Precio promedio REAL = nominal total / unidades totales
#         (ponderado por el tamaño de cada entrada)
#       · Apalancamiento efectivo = nominal total / margen total
#       · PRECIO DE LIQUIDACIÓN con ese margen (ver _resumen_posicion
#         para la fórmula y los supuestos)
#     Además avisa si el Stop Loss queda más allá del precio de
#     liquidación (te liquidarían antes de que salte el SL).
#     NO requiere migrar Supabase: sigue usando la columna jsonb
#     "entradas" (ya creada). Las señales viejas (con "peso" o sin
#     entradas) siguen funcionando: usan su promedio de siempre y no
#     muestran precio de liquidación porque no tienen margen cargado.
#     El campo "precio_entrada" ahora se guarda como el precio
#     promedio real de la posición, y "apalancamiento" como el
#     apalancamiento efectivo — así el resto del código (SL/TP,
#     Señales y Resultados, evaluación automática, Simulador) sigue
#     funcionando sin tocar nada más.
#   - Múltiples entradas por señal (para promediar precio, ej.
#     compraste en 2 o 3 tandas a distinto precio), sin límite fijo.
#     Si todavía no la tenés, la columna se crea con:
#       ALTER TABLE senales_trading
#       ADD COLUMN IF NOT EXISTS entradas jsonb DEFAULT '[]'::jsonb;
#   - Se eliminó la pestaña independiente "Gestor de Riesgo". Su
#     cálculo (tamaño de posición a partir de un % de capital en
#     riesgo y la distancia al Stop Loss) ahora vive DENTRO del
#     Simulador de Capital, como el modo "🎯 % de riesgo por
#     operación (según Stop Loss)".
#   - Perfiles de riesgo (🟢 Conservador / 🟡 Moderado / 🔴 Agresivo).
#     El admin define, al publicar cada señal, qué % de capital
#     arriesgaría cada perfil si el precio llega al Stop Loss.
#     REQUIERE migrar la tabla en Supabase:
#       ALTER TABLE senales_trading
#       ADD COLUMN IF NOT EXISTS riesgo_conservador float DEFAULT 1.0,
#       ADD COLUMN IF NOT EXISTS riesgo_moderado    float DEFAULT 2.0,
#       ADD COLUMN IF NOT EXISTS riesgo_agresivo    float DEFAULT 3.0;
#     (además de la columna "categoria" agregada en versiones previas)
#   - En "Señales y Resultados", cada señal tiene un selector de
#     perfil de riesgo: el usuario elige con qué perfil quiere tomar
#     esa señal y la app calcula solo el tamaño de posición sugerido,
#     el capital que usaría de margen y el riesgo/premio en dólares.
#   - En el Simulador de Capital se agregó el modo "🎭 Comparar los
#     3 perfiles de riesgo": corre la simulación completa una vez
#     por perfil (usando el % que definió el admin en cada señal) y
#     muestra los resultados uno al lado del otro.
# ==============================================================

import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, datetime, time as dt_time

ADMIN_EMAIL = "brainferreyra@gmail.com"
TABLA_SENALES = "senales_trading"

# Margen de mantenimiento que exige el bróker, como % del tamaño
# nominal de la posición. Se usa SOLO para calcular el precio de
# liquidación. Con 0.0 se asume que te liquidan cuando el margen
# (menos los costos de apertura) se consume por completo. Cada bróker
# lo define distinto: si querés máxima exactitud, poné acá el valor
# que te indica tu bróker para el instrumento (ej. 0.5 = 0,5%).
MARGEN_MANTENIMIENTO_PCT = 0.0

ESTADO_COLOR = {
    "ABIERTA":              ("#3a7bd5", "rgba(58,123,213,0.12)", "🔵"),
    "ACIERTO (TP)":         ("#3fb950", "rgba(63,185,80,0.12)",  "✅"),
    "DESACIERTO (SL)":      ("#f85149", "rgba(248,81,73,0.12)",  "❌"),
    "CERRADA MANUAL":       ("#e3b341", "rgba(227,179,65,0.12)", "⚪"),
}

CATEGORIAS = [
    "📈 Acción", "📊 Índice", "🛢️ Commodity", "💱 Forex",
    "₿ Cripto", "🏦 Bono/ETF", "🔹 Otro",
]

# Unidades "típicas" por lote según el tipo de activo. Son valores de
# referencia habituales en la mayoría de los brókers de CFDs/Forex,
# pero cada bróker puede definirlo distinto — por eso son editables
# en el simulador, no fijos.
DEFAULT_UNIDADES_LOTE = {
    "💱 Forex":     100000.0,   # 1 lote estándar = 100.000 unidades de la divisa base
    "₿ Cripto":     1.0,        # 1 lote = 1 unidad del cripto (varía mucho por bróker)
    "📈 Acción":    100.0,      # 1 lote = 100 acciones (tamaño de contrato típico en CFDs)
    "📊 Índice":    10.0,       # 1 lote = 10 unidades del índice (valor por punto x contrato)
    "🛢️ Commodity": 100.0,      # ej. oro: 1 lote = 100 oz; ajustable según el instrumento
    "🏦 Bono/ETF":  100.0,
    "🔹 Otro":      1.0,
}

LOTES_FOREX_PRESETS = {
    "Estándar (1 lote = 100.000 unidades)": 100000.0,
    "Mini (1 lote = 10.000 unidades)":      10000.0,
    "Micro (1 lote = 1.000 unidades)":      1000.0,
    "Nano (1 lote = 100 unidades)":         100.0,
}

# Perfiles de riesgo: el % de cada perfil se define POR SEÑAL, al
# publicarla (así el admin puede ser más o menos permisivo según el
# instrumento o la convicción de la señal). Estos valores son solo
# los defaults que se muestran al cargar el formulario.
PERFILES_RIESGO = {
    "conservador": {
        "label": "🟢 Conservador",
        "default_pct": 1.0,
        "desc": ("Prioriza cuidar el capital por sobre todo. Arriesga poco en cada "
                 "operación para amortiguar rachas de pérdidas — a cambio, las "
                 "ganancias en dólares también son más chicas. Pensado para quien "
                 "recién empieza o no quiere sobresaltos grandes en su capital."),
    },
    "moderado": {
        "label": "🟡 Moderado",
        "default_pct": 2.0,
        "desc": ("Un punto medio entre cuidar el capital y buscar rendimiento. "
                 "Asume más volatilidad que el conservador a cambio de un "
                 "potencial de ganancia mayor. Es el perfil habitual para quien "
                 "ya tiene algo de experiencia gestionando riesgo."),
    },
    "agresivo": {
        "label": "🔴 Agresivo",
        "default_pct": 3.0,
        "desc": ("Busca maximizar el retorno asumiendo el mayor riesgo por "
                 "operación. Tanto las pérdidas como las ganancias en dólares son "
                 "más grandes. Conviene solo si tenés capital suficiente y buena "
                 "tolerancia psicológica a ver el capital moverse fuerte."),
    },
}
PERFILES_LABEL_A_KEY = {v["label"]: k for k, v in PERFILES_RIESGO.items()}


def _es_admin(user_email):
    return bool(user_email) and user_email.strip().lower() == ADMIN_EMAIL.strip().lower()


# ==============================================================
#  FORMATO
# ==============================================================

def fmt_precio_local(p):
    if p is None:
        return "S/D"
    p = float(p)
    if p >= 1000: return f"${p:,.0f}"
    if p >= 10:   return f"${p:.2f}"
    return f"${p:.5f}"


def fmt_precio_exacto(p):
    """Como fmt_precio_local pero sin redondear a entero los precios
    grandes. Se usa para promedio y precio de liquidación, donde los
    decimales importan."""
    if p is None:
        return "S/D"
    p = float(p)
    if p >= 10:
        return f"${p:,.2f}"
    return f"${p:.5f}"


def fmt_apal(x):
    """8.0 -> '8x', 7.5 -> '7.5x', 7.4286 -> '7.43x'."""
    try:
        return f"{round(float(x), 2):g}x"
    except (TypeError, ValueError):
        return "S/D"


def fmt_unidades(u):
    s = f"{float(u):,.6f}".rstrip("0").rstrip(".")
    return s or "0"


# ==============================================================
#  ENTRADAS MÚLTIPLES — helpers de posición
#  Cada señal puede tener 1 o más "entradas". Cada entrada guarda:
#     precio, costo_apertura (USD), apalancamiento, margen (USD)
#  en la columna jsonb "entradas". Los campos "precio_entrada" y
#  "apalancamiento" de la señal se guardan también, como el precio
#  promedio real y el apalancamiento efectivo de la posición, para
#  que todo el resto del código siga funcionando igual.
#  Compatibilidad: las señales viejas pueden tener entradas con
#  "peso" (versión anterior) o ninguna entrada; se siguen leyendo.
# ==============================================================

def _entradas_de_senal(senal):
    """Devuelve la lista de entradas normalizada:
    [{'precio','costo_apertura','apalancamiento','margen','peso'}, ...].
    'margen' = 0 significa que la señal es vieja y no tiene margen
    cargado. 'peso' es solo de señales viejas."""
    apal_senal = float(senal.get("apalancamiento") or 1.0) or 1.0
    entradas = senal.get("entradas")
    if entradas and isinstance(entradas, list):
        limpio = []
        for e in entradas:
            try:
                p = float(e.get("precio"))
                if p <= 0:
                    continue
                limpio.append({
                    "precio": p,
                    "costo_apertura": float(e.get("costo_apertura") or 0.0),
                    "apalancamiento": float(e.get("apalancamiento") or apal_senal) or 1.0,
                    "margen": float(e.get("margen") or 0.0),
                    "peso": float(e.get("peso") or 1.0),
                })
            except (TypeError, ValueError, AttributeError):
                continue
        if limpio:
            return limpio
    precio_unico = float(senal.get("precio_entrada") or 0)
    if precio_unico > 0:
        return [{"precio": precio_unico, "costo_apertura": 0.0,
                 "apalancamiento": apal_senal, "margen": 0.0, "peso": 1.0}]
    return []


def _resumen_posicion(entradas, es_largo, mantenimiento_pct=MARGEN_MANTENIMIENTO_PCT):
    """Calcula la posición total a partir de las entradas.

    Para cada entrada:
        nominal_i  = margen_i × apalancamiento_i
        unidades_i = nominal_i / precio_i
    Para la posición:
        precio promedio = Σ nominal / Σ unidades   (ponderado por tamaño)
        apalancamiento efectivo = Σ nominal / Σ margen

    PRECIO DE LIQUIDACIÓN (margen aislado):
        colchón = margen total − costos de apertura − mantenimiento
        LARGO : liquidación = precio promedio − colchón / unidades
        CORTO : liquidación = precio promedio + colchón / unidades
    donde mantenimiento = MARGEN_MANTENIMIENTO_PCT % × nominal.

    Supuestos (el bróker real puede variar):
      · El costo de apertura sale del margen (reduce el colchón).
      · No incluye funding/swap acumulado ni comisión de cierre.
      · Todas las entradas se tratan como UNA posición con margen
        aislado, como hace un exchange cuando promediás.
    Devuelve None si no hay entradas válidas (precio > 0 y margen > 0)."""
    validas = [e for e in entradas
               if float(e.get("precio") or 0) > 0
               and float(e.get("margen") or 0) > 0
               and float(e.get("apalancamiento") or 0) > 0]
    if not validas:
        return None

    nominal = sum(e["margen"] * e["apalancamiento"] for e in validas)
    unidades = sum(e["margen"] * e["apalancamiento"] / e["precio"] for e in validas)
    margen_total = sum(e["margen"] for e in validas)
    costos_total = sum(float(e.get("costo_apertura") or 0.0) for e in validas)
    precio_prom = nominal / unidades
    apal_ef = nominal / margen_total

    mantenimiento_usd = nominal * mantenimiento_pct / 100.0
    colchon = margen_total - costos_total - mantenimiento_usd
    liquidada_al_abrir = colchon <= 0
    distancia = max(colchon, 0.0) / unidades

    if es_largo:
        liq_raw = precio_prom - distancia
        sin_liquidacion = liq_raw <= 0     # el activo tendría que llegar a $0
        precio_liq = max(liq_raw, 0.0)
    else:
        precio_liq = precio_prom + distancia
        sin_liquidacion = False

    dist_pct = (precio_liq - precio_prom) / precio_prom * 100.0

    return dict(
        precio_promedio=precio_prom, unidades=unidades, nominal=nominal,
        margen_total=margen_total, costos_total=costos_total,
        apalancamiento_efectivo=apal_ef, colchon=colchon,
        precio_liquidacion=precio_liq, dist_liq_pct=dist_pct,
        sin_liquidacion=sin_liquidacion, liquidada_al_abrir=liquidada_al_abrir,
        n_entradas=len(validas),
    )


def _resumen_de_senal(senal):
    """Resumen de posición de una señal guardada, o None si es una
    señal vieja sin margen cargado en todas sus entradas."""
    entradas = _entradas_de_senal(senal)
    if not entradas or not all(e["margen"] > 0 for e in entradas):
        return None
    es_largo = "LARGO" in str(senal.get("tipo", "")).upper()
    return _resumen_posicion(entradas, es_largo)


def _sl_mas_alla_de_liquidacion(res, es_largo, stop_loss):
    """True si el Stop Loss queda más allá del precio de liquidación
    (te liquidarían antes de que el SL llegue a ejecutarse)."""
    if not res or not stop_loss or stop_loss <= 0 or res["sin_liquidacion"]:
        return False
    liq = res["precio_liquidacion"]
    return (stop_loss <= liq) if es_largo else (stop_loss >= liq)


def _precio_promedio_simple(senal):
    entradas = _entradas_de_senal(senal)
    if not entradas:
        return float(senal.get("precio_entrada") or 0)
    precios = [e["precio"] for e in entradas]
    return sum(precios) / len(precios)


def _precio_promedio_ponderado(senal):
    """Precio promedio real de la posición (ponderado por tamaño). Si la
    señal es vieja y no tiene margen, cae al promedio por 'peso' de la
    versión anterior (o al precio único)."""
    entradas = _entradas_de_senal(senal)
    if not entradas:
        return float(senal.get("precio_entrada") or 0)
    if all(e["margen"] > 0 for e in entradas):
        res = _resumen_posicion(entradas, True)
        if res:
            return res["precio_promedio"]
    suma_peso = sum(e["peso"] for e in entradas)
    if suma_peso <= 0:
        return _precio_promedio_simple(senal)
    return sum(e["precio"] * e["peso"] for e in entradas) / suma_peso


def _senal_con_precio_entrada(senal, precio_entrada):
    """Copia la señal pisando precio_entrada por el valor dado — para
    reusar _calcular_retorno / _calcular_pnl_lotes /
    _tamano_posicion_por_riesgo con el promedio que corresponda."""
    s2 = dict(senal)
    s2["precio_entrada"] = precio_entrada
    return s2


def _texto_entradas(entradas):
    partes = []
    for i, e in enumerate(entradas):
        t = f"Entrada {i + 1}: {fmt_precio_exacto(e['precio'])}"
        if e["margen"] > 0:
            t += f" · margen ${e['margen']:,.2f} · {fmt_apal(e['apalancamiento'])}"
            if e["costo_apertura"] > 0:
                t += f" · costo ${e['costo_apertura']:,.2f}"
        elif abs(e["peso"] - 1.0) > 1e-9:
            t += f" (peso {e['peso']:.2f})"
        partes.append(t)
    return " | ".join(partes)


def _render_resumen_posicion(res, es_largo, stop_loss=None):
    """Muestra la posición total y el precio de liquidación."""
    st.markdown("##### 🧮 Posición total y precio de liquidación")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Precio promedio", fmt_precio_exacto(res["precio_promedio"]))
    m2.metric("Margen total", f"${res['margen_total']:,.2f}")
    m3.metric("Tamaño (nominal)", f"${res['nominal']:,.2f}")
    m4.metric("Apalanc. efectivo", fmt_apal(res["apalancamiento_efectivo"]))

    n1, n2, n3, n4 = st.columns(4)
    n1.metric("Unidades", fmt_unidades(res["unidades"]))
    n2.metric("Costos de apertura", f"${res['costos_total']:,.2f}")
    if res["liquidada_al_abrir"]:
        n3.metric("💀 Precio de liquidación", fmt_precio_exacto(res["precio_promedio"]))
        n4.metric("Distancia a liquidación", "0.00%")
    elif res["sin_liquidacion"]:
        n3.metric("💀 Precio de liquidación", "Sin liquidación")
        n4.metric("Distancia a liquidación", "—")
    else:
        n3.metric("💀 Precio de liquidación", fmt_precio_exacto(res["precio_liquidacion"]))
        n4.metric("Distancia a liquidación", f"{res['dist_liq_pct']:+.2f}%")

    if res["liquidada_al_abrir"]:
        st.error("🚨 Los costos de apertura (más el margen de mantenimiento) igualan o superan el "
                 "margen total: la posición nacería liquidada.")
    elif res["sin_liquidacion"]:
        st.caption("Con este margen y apalancamiento el activo tendría que llegar a $0 para "
                   "liquidarte (efectivamente, no hay liquidación en un largo).")

    if _sl_mas_alla_de_liquidacion(res, es_largo, stop_loss):
        st.warning(
            f"⚠️ El Stop Loss ({fmt_precio_exacto(stop_loss)}) queda más allá del precio de "
            f"liquidación ({fmt_precio_exacto(res['precio_liquidacion'])}): te liquidarían antes "
            "de que el SL se ejecute.")

    st.caption(
        "Fórmula: liquidación = precio promedio "
        f"{'−' if es_largo else '+'} (margen total − costos de apertura − mantenimiento "
        f"{MARGEN_MANTENIMIENTO_PCT:g}%) / unidades. Es una estimación con margen aislado; no "
        "incluye funding/swap ni comisión de cierre. Cada bróker define su margen de "
        "mantenimiento (ajustá MARGEN_MANTENIMIENTO_PCT al de tu bróker para máxima exactitud)."
    )


# ----------------------------------------------------------------
#  Formulario dinámico de entradas (usado solo al publicar)
# ----------------------------------------------------------------

def _entrada_vacia(_id, apal=1.0):
    return {"id": _id, "precio": 0.0, "costo": 0.0, "apal": float(apal), "margen": 0.0}


def _limpiar_keys_entrada(ent):
    for pref in ("precio", "costo", "apal", "margen"):
        st.session_state.pop(f"sen_entrada_{pref}_{ent['id']}", None)


def _init_entradas_state():
    if "sen_entradas" not in st.session_state:
        st.session_state["sen_entradas"] = [_entrada_vacia(0)]
        st.session_state["sen_entrada_next_id"] = 1


def _reset_entradas_state():
    for e in st.session_state.get("sen_entradas", []):
        _limpiar_keys_entrada(e)
    st.session_state["sen_entradas"] = [_entrada_vacia(0)]
    st.session_state["sen_entrada_next_id"] = 1


def _entradas_para_guardar(entradas_form):
    """Solo las entradas completas (precio > 0 y margen > 0), en el
    formato que se guarda en la columna jsonb 'entradas'."""
    return [
        {"precio": float(e["precio"]),
         "costo_apertura": float(e["costo"]),
         "apalancamiento": float(e["apal"]),
         "margen": float(e["margen"])}
        for e in entradas_form if e["precio"] > 0 and e["margen"] > 0
    ]


def _render_entradas_form(es_largo):
    """Renderiza el formulario dinámico de entradas (1 o más, sin
    límite) y devuelve la lista de entradas cargadas en session_state."""
    _init_entradas_state()
    entradas = st.session_state["sen_entradas"]

    st.markdown("#### 🎯💰 Entradas")
    st.caption(
        "Cargá una entrada por cada compra/venta si vas a promediar precio (ej: entraste en 2 "
        "o 3 tandas). Para cada una indicá el **precio**, el **costo de apertura** en USD "
        "(comisión/spread), el **apalancamiento** que usaste y el **margen** en USD que "
        "agregaste a la posición. Con eso la app calcula el precio promedio real, el "
        "apalancamiento efectivo y el **precio de liquidación**."
    )

    a_borrar = None
    for i, ent in enumerate(entradas):
        ce1, ce2, ce3, ce4, ce5 = st.columns([1.5, 1.2, 1.1, 1.3, 0.5])
        with ce1:
            ent["precio"] = st.number_input(
                f"Precio — Entrada {i + 1}", min_value=0.0, format="%.5f",
                value=float(ent.get("precio", 0.0)), key=f"sen_entrada_precio_{ent['id']}")
        with ce2:
            ent["costo"] = st.number_input(
                f"Costo apertura (USD) {i + 1}", min_value=0.0, step=0.01, format="%.4f",
                value=float(ent.get("costo", 0.0)), key=f"sen_entrada_costo_{ent['id']}",
                help="Comisión/spread que pagaste al abrir esta entrada, en dólares.")
        with ce3:
            ent["apal"] = st.number_input(
                f"Apalanc. {i + 1} (x)", min_value=1.0, max_value=125.0, step=1.0, format="%.1f",
                value=float(ent.get("apal", 1.0)), key=f"sen_entrada_apal_{ent['id']}",
                help="Apalancamiento que usaste en esta entrada.")
        with ce4:
            ent["margen"] = st.number_input(
                f"Margen (USD) {i + 1}", min_value=0.0, step=10.0, format="%.2f",
                value=float(ent.get("margen", 0.0)), key=f"sen_entrada_margen_{ent['id']}",
                help="Margen en dólares que agregaste a la posición con esta entrada.")
        with ce5:
            st.write("")
            st.write("")
            if len(entradas) > 1 and st.button("🗑️", key=f"sen_entrada_del_{ent['id']}",
                                                help="Quitar esta entrada"):
                a_borrar = i

    if a_borrar is not None:
        eliminado = entradas.pop(a_borrar)
        _limpiar_keys_entrada(eliminado)
        st.rerun()

    if st.button("➕ Agregar otra entrada", key="sen_entrada_add"):
        nuevo_id = st.session_state["sen_entrada_next_id"]
        apal_prev = entradas[-1].get("apal", 1.0) if entradas else 1.0
        entradas.append(_entrada_vacia(nuevo_id, apal_prev))
        st.session_state["sen_entrada_next_id"] += 1
        st.rerun()

    incompletas = [i + 1 for i, e in enumerate(entradas) if (e["precio"] > 0) != (e["margen"] > 0)]
    if incompletas:
        st.warning("⚠️ Completá precio **y** margen en la(s) entrada(s): "
                   + ", ".join(str(n) for n in incompletas)
                   + ". Las incompletas no se tienen en cuenta.")

    resumen = _resumen_posicion(_entradas_para_guardar(entradas), es_largo)
    if resumen:
        _render_resumen_posicion(resumen, es_largo)

    return entradas


# ==============================================================
#  ACCESO A SUPABASE
# ==============================================================

def _guardar_senal(supabase, datos, user_id, user_email):
    row = {
        "autor_id": user_id, "autor_email": user_email,
        "ticker": datos["ticker"].strip().upper(),
        "categoria": datos.get("categoria", CATEGORIAS[-1]),
        "tipo": datos["tipo"],
        "fecha": str(datos["fecha"]), "hora": str(datos["hora"]),
        "precio_entrada": datos["precio_entrada"],
        "entradas": datos.get("entradas", []),
        "stop_loss": datos["stop_loss"], "take_profit": datos["take_profit"],
        "apalancamiento": datos["apalancamiento"],
        "riesgo_conservador": datos.get("riesgo_conservador", PERFILES_RIESGO["conservador"]["default_pct"]),
        "riesgo_moderado": datos.get("riesgo_moderado", PERFILES_RIESGO["moderado"]["default_pct"]),
        "riesgo_agresivo": datos.get("riesgo_agresivo", PERFILES_RIESGO["agresivo"]["default_pct"]),
        "notas": datos.get("notas", ""),
        "estado": "ABIERTA",
        "precio_cierre": None, "fecha_cierre": None,
    }
    supabase.table(TABLA_SENALES).insert(row).execute()


@st.cache_data(ttl=120, show_spinner=False)
def _obtener_senales(_supabase, limite=200):
    res = (_supabase.table(TABLA_SENALES).select("*")
           .order("fecha", desc=True).order("hora", desc=True).limit(limite).execute())
    return res.data or []


def _actualizar_estado_senal(supabase, senal_id, estado, precio_cierre, fecha_cierre):
    supabase.table(TABLA_SENALES).update({
        "estado": estado,
        "precio_cierre": precio_cierre,
        "fecha_cierre": str(fecha_cierre) if fecha_cierre else None,
    }).eq("id", senal_id).execute()


def _borrar_senal(supabase, senal_id):
    supabase.table(TABLA_SENALES).delete().eq("id", senal_id).execute()


def _cerrar_senal_manual(supabase, senal_id, precio_cierre):
    supabase.table(TABLA_SENALES).update({
        "estado": "CERRADA MANUAL",
        "precio_cierre": precio_cierre,
        "fecha_cierre": str(date.today()),
    }).eq("id", senal_id).execute()


# ==============================================================
#  EVALUACIÓN AUTOMÁTICA — ¿tocó TP o SL primero?
#  Usa High/Low diario desde la fecha de publicación de la señal.
#  Si TP y SL se tocan el mismo día, se asume el peor caso (SL)
#  porque no tenemos el orden intradiario exacto — es una
#  simplificación conservadora, no una garantía de precisión.
# ==============================================================

@st.cache_data(ttl=900, show_spinner=False)
def _historial_desde_fecha(ticker, fecha_inicio_str):
    try:
        import yfinance as yf
        df = yf.download(ticker, start=fecha_inicio_str, interval="1d",
                          auto_adjust=True, progress=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df.dropna(subset=["Close"])
    except Exception:
        return None


def _evaluar_senal(senal):
    """Devuelve dict con: estado_calc, precio_ref (cierre o último precio),
    fecha_ref, tocó_tp, tocó_sl. No escribe en Supabase — eso lo hace
    el caller si corresponde."""
    if senal.get("estado") in ("CERRADA MANUAL",):
        return dict(estado_calc=senal["estado"], precio_ref=senal.get("precio_cierre"),
                    fecha_ref=senal.get("fecha_cierre"), es_final=True)

    ticker = senal["ticker"]
    tipo = senal["tipo"]
    entrada = _precio_promedio_ponderado(senal)
    sl = float(senal["stop_loss"])
    tp = float(senal["take_profit"])

    hist = _historial_desde_fecha(ticker, senal["fecha"])
    if hist is None or hist.empty:
        return dict(estado_calc="ABIERTA", precio_ref=entrada, fecha_ref=None, es_final=False)

    es_largo = tipo.startswith("🟢") or "LARGO" in tipo.upper()

    for fecha_idx, fila in hist.iterrows():
        hi = float(fila["High"]) if "High" in fila else float(fila["Close"])
        lo = float(fila["Low"]) if "Low" in fila else float(fila["Close"])
        if es_largo:
            toco_sl = lo <= sl
            toco_tp = hi >= tp
        else:
            toco_sl = hi >= sl
            toco_tp = lo <= tp
        if toco_sl:  # peor caso primero si ambos ocurren el mismo día
            return dict(estado_calc="DESACIERTO (SL)", precio_ref=sl,
                        fecha_ref=fecha_idx.date(), es_final=True)
        if toco_tp:
            return dict(estado_calc="ACIERTO (TP)", precio_ref=tp,
                        fecha_ref=fecha_idx.date(), es_final=True)

    ultimo_precio = float(hist["Close"].iloc[-1])
    return dict(estado_calc="ABIERTA", precio_ref=ultimo_precio, fecha_ref=None, es_final=False)


def _sincronizar_estados(supabase, senales):
    """Recorre las señales ABIERTAS y, si la evaluación automática
    determinó un cierre (TP o SL), lo persiste en Supabase."""
    actualizadas = False
    for s in senales:
        if s.get("estado") != "ABIERTA":
            continue
        ev = _evaluar_senal(s)
        if ev["es_final"] and ev["estado_calc"] != "ABIERTA":
            _actualizar_estado_senal(supabase, s["id"], ev["estado_calc"],
                                      ev["precio_ref"], ev["fecha_ref"])
            actualizadas = True
    if actualizadas:
        _obtener_senales.clear()
    return actualizadas


# ==============================================================
#  CÁLCULO DE RETORNO / P&L
#  Estas funciones siguen leyendo senal["precio_entrada"] como
#  siempre. Ese campo se guarda como el precio PROMEDIO REAL de la
#  posición (ponderado por el tamaño de cada entrada), y
#  senal["apalancamiento"] como el apalancamiento efectivo, así
#  que todo queda consistente sin tocar nada más.
# ==============================================================

def _calcular_retorno(senal, precio_salida):
    """Modo 'capital': el retorno % se aplica directamente sobre el
    monto asignado, multiplicado por el apalancamiento de la señal."""
    entrada = float(senal["precio_entrada"])
    apalancamiento = float(senal["apalancamiento"])
    es_largo = "LARGO" in senal["tipo"].upper()
    if entrada == 0:
        return 0.0, 0.0
    ret_precio = (precio_salida - entrada) / entrada
    if not es_largo:
        ret_precio = -ret_precio
    ret_apalancado = ret_precio * apalancamiento
    return ret_precio * 100, ret_apalancado * 100


def _calcular_pnl_lotes(senal, precio_salida, unidades):
    """Cálculo de P&L como lo hace un bróker real. El resultado en
    dinero depende del movimiento de precio y del tamaño de la
    posición (unidades), NO directamente del apalancamiento. El
    apalancamiento solo define cuánto margen (capital) necesitás
    inmovilizar para abrir esa posición.

    Devuelve: (pnl_usd, margen_usado, retorno_%_sobre_margen)
    """
    entrada = float(senal["precio_entrada"])
    apalancamiento = float(senal.get("apalancamiento", 1)) or 1.0
    es_largo = "LARGO" in senal["tipo"].upper()
    if entrada == 0 or unidades <= 0:
        return 0.0, 0.0, 0.0
    diff = (precio_salida - entrada) if es_largo else (entrada - precio_salida)
    pnl_usd = diff * unidades
    nominal = entrada * unidades
    margen = nominal / apalancamiento if apalancamiento else nominal
    ret_pct_margen = (pnl_usd / margen * 100) if margen else 0.0
    return pnl_usd, margen, ret_pct_margen


def _tamano_posicion_por_riesgo(senal, capital, pct_riesgo):
    """Calcula el tamaño de posición para que, si el precio llega al
    Stop Loss, la pérdida sea exactamente pct_riesgo % del capital.
    Devuelve dict con riesgo_usd, unidades, nominal y margen (o None
    si faltan datos válidos)."""
    entrada = float(senal.get("precio_entrada") or 0)
    sl = float(senal.get("stop_loss") or 0)
    apalancamiento = float(senal.get("apalancamiento", 1)) or 1.0
    distancia_precio = abs(entrada - sl)
    if entrada <= 0 or distancia_precio <= 0:
        return None
    riesgo_usd = capital * pct_riesgo / 100
    unidades = riesgo_usd / distancia_precio
    nominal = unidades * entrada
    margen = nominal / apalancamiento
    return dict(riesgo_usd=riesgo_usd, unidades=unidades, nominal=nominal, margen=margen)


# ==============================================================
#  RENDER — TAB PUBLICAR (solo admin)
#  Ahora también incluye "Gestionar señales publicadas" (eliminar)
#  y la definición de los 3 perfiles de riesgo de la señal.
# ==============================================================

def _tab_publicar(supabase, user_id, user_email, es_admin):
    if not es_admin:
        st.info("🔒 Solo el administrador puede publicar señales de trading. "
                "Podés ver todas las señales y simular resultados en las otras pestañas.")
        return

    c1, c2, c3 = st.columns(3)
    with c1:
        ticker = st.text_input("🎯 Ticker", key="sen_ticker", placeholder="Ej: NVDA, BTC-USD, EURUSD=X")
    with c2:
        categoria = st.selectbox("🏷️ Categoría del activo", CATEGORIAS, key="sen_categoria")
    with c3:
        tipo = st.selectbox("Tipo de operación", ["🟢 LARGO (Compra)", "🔴 CORTO (Venta)"], key="sen_tipo")

    es_largo_pub = "LARGO" in tipo.upper()

    f1, f2 = st.columns(2)
    with f1:
        fecha = st.date_input("📅 Fecha", value=date.today(), key="sen_fecha")
    with f2:
        hora = st.time_input("🕐 Hora", value=datetime.now().time().replace(microsecond=0), key="sen_hora")

    st.divider()
    entradas_form = _render_entradas_form(es_largo_pub)
    entradas_guardar = _entradas_para_guardar(entradas_form)
    resumen_pub = _resumen_posicion(entradas_guardar, es_largo_pub)
    precio_entrada_pos = resumen_pub["precio_promedio"] if resumen_pub else 0.0
    apal_efectivo = resumen_pub["apalancamiento_efectivo"] if resumen_pub else 1.0

    st.divider()
    p2, p3 = st.columns(2)
    with p2:
        stop_loss = st.number_input("🛑 Stop Loss", min_value=0.0, format="%.5f", key="sen_sl")
    with p3:
        take_profit = st.number_input("🎯 Take Profit", min_value=0.0, format="%.5f", key="sen_tp")

    notas = st.text_area("💬 Notas / justificación", key="sen_notas", height=80,
                          placeholder="Motivo de la señal, contexto técnico o fundamental...")

    # Validación visual rápida antes de guardar (contra el precio promedio real)
    if precio_entrada_pos > 0 and stop_loss > 0 and take_profit > 0:
        ok_niveles = (stop_loss < precio_entrada_pos < take_profit) if es_largo_pub \
            else (take_profit < precio_entrada_pos < stop_loss)
        if not ok_niveles:
            st.warning("⚠️ Revisá los niveles: para LARGO, SL < Entrada < TP. Para CORTO, TP < Entrada < SL. "
                       "(Se valida contra el precio promedio de las entradas.)")

    if resumen_pub and _sl_mas_alla_de_liquidacion(resumen_pub, es_largo_pub, stop_loss):
        st.error(
            f"🚨 Tu Stop Loss ({fmt_precio_exacto(stop_loss)}) queda más allá del precio de "
            f"liquidación ({fmt_precio_exacto(resumen_pub['precio_liquidacion'])}): con el margen y "
            "apalancamiento cargados te liquidarían antes de que el SL se ejecute.")

    st.divider()
    st.markdown("#### 🎭 Perfiles de riesgo para esta señal")
    st.caption(
        "Definí qué % de capital arriesgaría cada perfil si el precio llega al Stop Loss. "
        "Quien vea esta señal va a poder elegir con qué perfil quiere tomarla, y la app le va "
        "a calcular sola el tamaño de posición sugerido."
    )
    rp1, rp2, rp3 = st.columns(3)
    with rp1:
        riesgo_conservador = st.number_input(
            f"{PERFILES_RIESGO['conservador']['label']} — % de riesgo", min_value=0.1, max_value=50.0,
            value=PERFILES_RIESGO['conservador']['default_pct'], step=0.1, key="sen_riesgo_conservador")
    with rp2:
        riesgo_moderado = st.number_input(
            f"{PERFILES_RIESGO['moderado']['label']} — % de riesgo", min_value=0.1, max_value=50.0,
            value=PERFILES_RIESGO['moderado']['default_pct'], step=0.1, key="sen_riesgo_moderado")
    with rp3:
        riesgo_agresivo = st.number_input(
            f"{PERFILES_RIESGO['agresivo']['label']} — % de riesgo", min_value=0.1, max_value=50.0,
            value=PERFILES_RIESGO['agresivo']['default_pct'], step=0.1, key="sen_riesgo_agresivo")

    if not (riesgo_conservador <= riesgo_moderado <= riesgo_agresivo):
        st.warning("⚠️ Lo lógico es que Conservador ≤ Moderado ≤ Agresivo en % de riesgo.")

    if st.button("📢 Publicar señal", type="primary", key="sen_btn_publicar"):
        if not ticker or not resumen_pub or stop_loss <= 0 or take_profit <= 0:
            st.warning("⚠️ Completá ticker, al menos una entrada con precio y margen válidos, "
                       "stop loss y take profit.")
        else:
            datos = dict(ticker=ticker, categoria=categoria, tipo=tipo, fecha=fecha, hora=hora,
                         precio_entrada=precio_entrada_pos, entradas=entradas_guardar,
                         stop_loss=stop_loss, take_profit=take_profit,
                         apalancamiento=apal_efectivo, notas=notas,
                         riesgo_conservador=riesgo_conservador, riesgo_moderado=riesgo_moderado,
                         riesgo_agresivo=riesgo_agresivo)
            try:
                _guardar_senal(supabase, datos, user_id, user_email)
                _obtener_senales.clear()
                st.success("✅ Señal publicada.")
                for k in ["sen_ticker", "sen_notas"]:
                    st.session_state.pop(k, None)
                _reset_entradas_state()
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error al publicar: {e}")

    # ----------------------------------------------------------
    #  Gestionar señales publicadas (eliminar) — todo desde acá
    # ----------------------------------------------------------
    st.divider()
    st.markdown("#### 🗂️ Gestionar señales publicadas")
    st.caption("Eliminá cualquier señal —abierta o cerrada— desde acá. El resto de los "
               "usuarios solo puede ver y simular, nunca borrar.")

    senales_admin = _obtener_senales(supabase, 200)
    if not senales_admin:
        st.info("Todavía no hay señales publicadas.")
        return

    df_admin = pd.DataFrame(senales_admin)
    if "categoria" not in df_admin.columns:
        df_admin["categoria"] = "🔹 Otro"
    df_admin["categoria"] = df_admin["categoria"].fillna("🔹 Otro")

    fa1, fa2, fa3 = st.columns(3)
    with fa1:
        tickers_admin = ["Todos"] + sorted(df_admin["ticker"].dropna().unique().tolist())
        f_tk_admin = st.selectbox("Filtrar ticker", tickers_admin, key="sen_admin_f_tk")
    with fa2:
        estados_admin = ["Todos"] + sorted(df_admin["estado"].dropna().unique().tolist())
        f_estado_admin = st.selectbox("Filtrar estado", estados_admin, key="sen_admin_f_estado")
    with fa3:
        categorias_admin = ["Todas"] + sorted(df_admin["categoria"].dropna().unique().tolist())
        f_cat_admin = st.selectbox("Filtrar categoría", categorias_admin, key="sen_admin_f_cat")

    df_admin_f = df_admin.copy()
    if f_tk_admin != "Todos": df_admin_f = df_admin_f[df_admin_f["ticker"] == f_tk_admin]
    if f_estado_admin != "Todos": df_admin_f = df_admin_f[df_admin_f["estado"] == f_estado_admin]
    if f_cat_admin != "Todas": df_admin_f = df_admin_f[df_admin_f["categoria"] == f_cat_admin]

    st.caption(f"{len(df_admin_f)} señales mostradas de {len(df_admin)} totales")

    for _, row in df_admin_f.iterrows():
        estado_row = row.get("estado", "ABIERTA")
        col, bg, emoji = ESTADO_COLOR.get(estado_row, ("#8b949e", "rgba(139,148,158,0.12)", "⚪"))
        categoria_row = row.get("categoria") or "🔹 Otro"
        titulo = (f"{row.get('fecha','')} {row.get('hora','')} · {row.get('ticker','')} · "
                  f"{categoria_row} · {row.get('tipo','')} · {estado_row}")
        with st.expander(f"{emoji} {titulo}"):
            entradas_lista = _entradas_de_senal(row.to_dict())
            v1, v2, v3, v4 = st.columns(4)
            v1.metric("Entrada (prom. ponderado)" if len(entradas_lista) > 1 else "Entrada",
                      fmt_precio_local(row.get("precio_entrada")))
            v2.metric("Stop Loss", fmt_precio_local(row.get("stop_loss")))
            v3.metric("Take Profit", fmt_precio_local(row.get("take_profit")))
            v4.metric("Apalancamiento", fmt_apal(row.get("apalancamiento", 1)))

            if len(entradas_lista) > 1:
                st.caption(f"🧩 {len(entradas_lista)} entradas → {_texto_entradas(entradas_lista)}")

            es_largo_row = "LARGO" in str(row.get("tipo", "")).upper()
            res_row = _resumen_de_senal(row.to_dict())
            if res_row:
                _render_resumen_posicion(res_row, es_largo_row,
                                          stop_loss=float(row.get("stop_loss") or 0))

            st.caption(
                f"Perfiles de riesgo → 🟢 {row.get('riesgo_conservador', PERFILES_RIESGO['conservador']['default_pct']):.1f}% · "
                f"🟡 {row.get('riesgo_moderado', PERFILES_RIESGO['moderado']['default_pct']):.1f}% · "
                f"🔴 {row.get('riesgo_agresivo', PERFILES_RIESGO['agresivo']['default_pct']):.1f}%"
            )
            if row.get("precio_cierre") is not None:
                st.caption(f"Cerrada el {row.get('fecha_cierre','')} a "
                           f"{fmt_precio_local(row.get('precio_cierre'))}")
            if row.get("notas"):
                st.markdown(f"**Notas:** {row['notas']}")

            confirmar = st.checkbox("Confirmar eliminación", key=f"sen_admin_confirm_del_{row['id']}")
            if st.button("🗑️ Eliminar señal", key=f"sen_admin_btn_del_{row['id']}",
                         disabled=not confirmar):
                _borrar_senal(supabase, row["id"])
                _obtener_senales.clear()
                st.success("Señal eliminada.")
                st.rerun()


# ==============================================================
#  RENDER — TAB SEÑALES Y RESULTADOS (todos ven)
#  Ya NO tiene botón de eliminar — eso vive en "Publicar Señal".
#  Cada señal tiene un selector de perfil de riesgo que calcula el
#  tamaño de posición sugerido. Si hay varias entradas, se muestran
#  todas (precio, margen, apalancamiento, costo), el precio promedio
#  real de la posición y el precio de liquidación.
# ==============================================================

def _tab_senales(supabase, es_admin):
    top1, top2 = st.columns([3, 1])
    with top1:
        st.caption("Historial de señales publicadas, con evaluación automática de resultado.")
    with top2:
        if st.button("↺ Actualizar y evaluar", use_container_width=True, key="sen_refresh"):
            _obtener_senales.clear()
            _historial_desde_fecha.clear()
            st.rerun()

    senales = _obtener_senales(supabase, 200)
    if not senales:
        st.info("Todavía no hay señales publicadas.")
        return

    with st.spinner("Evaluando señales abiertas contra el precio de mercado..."):
        _sincronizar_estados(supabase, senales)
        senales = _obtener_senales(supabase, 200)

    df = pd.DataFrame(senales)
    if "categoria" not in df.columns:
        df["categoria"] = "🔹 Otro"
    df["categoria"] = df["categoria"].fillna("🔹 Otro")

    n_abiertas = int((df["estado"] == "ABIERTA").sum())
    n_acierto = int((df["estado"] == "ACIERTO (TP)").sum())
    n_desacierto = int((df["estado"] == "DESACIERTO (SL)").sum())
    n_cerradas_total = n_acierto + n_desacierto
    winrate = (n_acierto / n_cerradas_total * 100) if n_cerradas_total > 0 else 0.0

    k1, k2, k3, k4 = st.columns(4)
    with k1: st.metric("🔵 Abiertas", n_abiertas)
    with k2: st.metric("✅ Aciertos (TP)", n_acierto)
    with k3: st.metric("❌ Desaciertos (SL)", n_desacierto)
    with k4: st.metric("🎯 Win Rate", f"{winrate:.1f}%" if n_cerradas_total > 0 else "—")

    st.divider()
    cap_col1, cap_col2 = st.columns([1, 3])
    with cap_col1:
        capital_usuario = st.number_input(
            "💰 Tu capital", min_value=100.0, value=1000.0, step=100.0, key="sen_hist_capital")
    with cap_col2:
        st.caption(
            "Con este capital calculamos el tamaño de posición sugerido cuando elijas un "
            "perfil de riesgo dentro de cada señal."
        )

    fc1, fc2, fc3, fc4 = st.columns(4)
    with fc1:
        tickers_u = ["Todos"] + sorted(df["ticker"].dropna().unique().tolist())
        f_tk = st.selectbox("Filtrar ticker", tickers_u, key="sen_hist_f_tk")
    with fc2:
        estados_u = ["Todos"] + sorted(df["estado"].dropna().unique().tolist())
        f_estado = st.selectbox("Filtrar estado", estados_u, key="sen_hist_f_estado")
    with fc3:
        tipos_u = ["Todos"] + sorted(df["tipo"].dropna().unique().tolist())
        f_tipo = st.selectbox("Filtrar tipo", tipos_u, key="sen_hist_f_tipo")
    with fc4:
        categorias_u = ["Todas"] + sorted(df["categoria"].dropna().unique().tolist())
        f_cat = st.selectbox("Filtrar categoría", categorias_u, key="sen_hist_f_cat")

    df_f = df.copy()
    if f_tk != "Todos": df_f = df_f[df_f["ticker"] == f_tk]
    if f_estado != "Todos": df_f = df_f[df_f["estado"] == f_estado]
    if f_tipo != "Todos": df_f = df_f[df_f["tipo"] == f_tipo]
    if f_cat != "Todas": df_f = df_f[df_f["categoria"] == f_cat]

    st.caption(f"{len(df_f)} señales mostradas de {len(df)} totales")

    for _, row in df_f.iterrows():
        estado = row.get("estado", "ABIERTA")
        col, bg, emoji = ESTADO_COLOR.get(estado, ("#8b949e", "rgba(139,148,158,0.12)", "⚪"))

        precio_ref = row.get("precio_cierre") if row.get("precio_cierre") is not None else None
        if precio_ref is None:
            ev = _evaluar_senal(row.to_dict())
            precio_ref = ev["precio_ref"]

        ret_precio, ret_apalancado = _calcular_retorno(row.to_dict(), precio_ref) if precio_ref else (0, 0)

        categoria_row = row.get("categoria") or "🔹 Otro"
        titulo = (f"{row.get('fecha','')} {row.get('hora','')} · {row.get('ticker','')} · "
                  f"{categoria_row} · {row.get('tipo','')}")
        with st.expander(f"{emoji} {titulo}"):
            st.markdown(
                f'<div style="border-radius:10px;padding:10px 14px;margin-bottom:10px;'
                f'background:{bg};border:1px solid {col}55">'
                f'<div style="font-size:10px;color:{col};opacity:.8">Estado</div>'
                f'<div style="font-size:14px;font-weight:800;color:{col}">{estado}</div></div>',
                unsafe_allow_html=True,
            )

            entradas_lista = _entradas_de_senal(row.to_dict())
            v1, v2, v3, v4 = st.columns(4)
            v1.metric("Entrada (prom. ponderado)" if len(entradas_lista) > 1 else "Entrada",
                      fmt_precio_local(row.get("precio_entrada")))
            v2.metric("Stop Loss", fmt_precio_local(row.get("stop_loss")))
            v3.metric("Take Profit", fmt_precio_local(row.get("take_profit")))
            v4.metric("Apalancamiento", fmt_apal(row.get("apalancamiento", 1)))

            if len(entradas_lista) > 1:
                st.caption(f"🧩 {len(entradas_lista)} entradas cargadas → {_texto_entradas(entradas_lista)}")
                st.caption("El precio de entrada de arriba es el promedio real de la posición "
                           "(ponderado por el tamaño de cada entrada). El Simulador de Capital usa "
                           "ese mismo precio.")

            es_largo_row = "LARGO" in str(row.get("tipo", "")).upper()
            res_row = _resumen_de_senal(row.to_dict())
            if res_row:
                _render_resumen_posicion(res_row, es_largo_row,
                                          stop_loss=float(row.get("stop_loss") or 0))

            v5, v6 = st.columns(2)
            v5.metric("Precio actual / cierre", fmt_precio_local(precio_ref))
            v6.metric("Retorno apalancado", f"{ret_apalancado:+.1f}%",
                      delta=f"{ret_precio:+.2f}% precio", delta_color="off")

            if row.get("notas"):
                st.markdown(f"**Notas:** {row['notas']}")

            # ------------------------------------------------------
            #  Selector de perfil de riesgo para esta señal puntual
            # ------------------------------------------------------
            st.divider()
            st.markdown("##### 🎯 Elegí con qué perfil querés tomar esta señal")
            perfil_label_sel = st.radio(
                "Perfil de riesgo", [info["label"] for info in PERFILES_RIESGO.values()],
                horizontal=True, key=f"sen_perfil_{row['id']}")
            perfil_key = PERFILES_LABEL_A_KEY[perfil_label_sel]
            pct_signal = float(row.get(f"riesgo_{perfil_key}") or PERFILES_RIESGO[perfil_key]["default_pct"])
            st.caption(PERFILES_RIESGO[perfil_key]["desc"])

            calc = _tamano_posicion_por_riesgo(row.to_dict(), capital_usuario, pct_signal)
            if calc is None:
                st.caption("No se puede calcular el tamaño sugerido: faltan precio de entrada o "
                           "stop loss válidos.")
            else:
                rc1, rc2, rc3 = st.columns(3)
                rc1.metric(f"Riesgo si toca el SL ({pct_signal:.1f}%)", f"${calc['riesgo_usd']:,.2f}")
                rc2.metric("Tamaño de posición sugerido", f"${calc['nominal']:,.2f}")
                rc3.metric("Capital que usarías (margen)", f"${calc['margen']:,.2f}")

                tp_row = float(row.get("take_profit") or 0)
                if tp_row > 0:
                    pnl_tp, _, _ = _calcular_pnl_lotes(row.to_dict(), tp_row, calc["unidades"])
                    st.caption(
                        f"Si el precio llega al Take Profit, ganarías aproximadamente "
                        f"**${pnl_tp:,.2f}**. Si en cambio llega al Stop Loss, perderías los "
                        f"**${calc['riesgo_usd']:,.2f}** que definís al elegir este perfil."
                    )

            if es_admin and estado == "ABIERTA":
                st.divider()
                precio_cierre_manual = st.number_input(
                    "Precio de cierre manual", min_value=0.0, format="%.5f",
                    key=f"sen_cierre_{row['id']}")
                if st.button("🔒 Cerrar manualmente", key=f"sen_btn_cerrar_{row['id']}"):
                    if precio_cierre_manual > 0:
                        _cerrar_senal_manual(supabase, row["id"], precio_cierre_manual)
                        _obtener_senales.clear()
                        st.rerun()
                    else:
                        st.warning("Ingresá un precio de cierre válido.")
                st.caption("🗑️ Para eliminar una señal, andá a la pestaña **Publicar Señal**.")


# ==============================================================
#  HELPERS COMPARTIDOS DEL SIMULADOR
# ==============================================================

def _calcular_fila_simulacion(s, precio_ref, capital_total, modo_calculo,
                               monto_por_senal=None, pct_por_senal=None, riesgo_pct=None,
                               unidades_por_lote=None, cantidad_lotes=None):
    """Arma la fila de la tabla del simulador para una señal, según el
    modo de cálculo elegido. Devuelve None si faltan datos para calcular.
    IMPORTANTE: 's' ya debe venir con precio_entrada = promedio real de
    la posición (ver _senal_con_precio_entrada)."""
    estado = s.get("estado", "ABIERTA")
    cat = s.get("categoria") or "🔹 Otro"
    ret_precio, ret_apalancado_signal = _calcular_retorno(s, precio_ref)
    extra_cols = {}

    if modo_calculo == "lotes":
        unidades = (unidades_por_lote or 1.0) * (cantidad_lotes or 0)
        pnl_usd, margen, ret_pct = _calcular_pnl_lotes(s, precio_ref, unidades)
        capital_asignado = margen
        liquidada = ret_pct <= -100
        if liquidada:
            pnl_usd = -capital_asignado
            ret_pct = -100.0
        capital_final = capital_asignado + pnl_usd
        extra_cols = {"Lotes": round(cantidad_lotes or 0, 2), "Unidades": round(unidades, 2)}
        ret_mostrar = ret_pct

    elif modo_calculo == "riesgo":
        if riesgo_pct is None:
            return None
        calc = _tamano_posicion_por_riesgo(s, capital_total, riesgo_pct)
        if calc is None:
            return None
        pnl_usd, margen, ret_pct = _calcular_pnl_lotes(s, precio_ref, calc["unidades"])
        capital_asignado = margen
        liquidada = ret_pct <= -100
        if liquidada:
            pnl_usd = -calc["riesgo_usd"]
            ret_pct = (pnl_usd / margen * 100) if margen else -100.0
        capital_final = capital_asignado + pnl_usd
        extra_cols = {"% Riesgo": round(riesgo_pct, 2)}
        ret_mostrar = ret_pct

    else:  # "monto_pct": monto fijo o % de capital por señal
        capital_asignado = monto_por_senal if monto_por_senal is not None else capital_total * (pct_por_senal / 100)
        liquidada = ret_apalancado_signal <= -100
        ret_mostrar = max(ret_apalancado_signal, -100)
        pnl_usd = capital_asignado * (ret_mostrar / 100)
        capital_final = capital_asignado + pnl_usd

    fila = {
        "Fecha": s.get("fecha"), "Ticker": s.get("ticker"), "Categoría": cat, "Tipo": s.get("tipo"),
        "Entrada usada (ponderada)": fmt_precio_local(s.get("precio_entrada")),
        "Estado": "💀 LIQUIDADA" if liquidada else estado,
        "Apalanc.": fmt_apal(s.get("apalancamiento", 1)),
    }
    fila.update(extra_cols)
    fila.update({
        "Ret. Precio %": round(ret_precio, 2),
        "Ret. Apalancado %": round(ret_mostrar, 2),
        "Capital Asignado": round(capital_asignado, 2),
        "P&L (USD)": round(pnl_usd, 2),
        "Capital Final": round(capital_final, 2),
    })
    return fila


REPLICA_REF_PRIMERA = "Margen de la 1ª entrada"
REPLICA_REF_TOTAL = "Margen total de la posición"
MODO_REPLICA = "🔁 Replicar la posición del publicador (escalada a tu margen)"


def _factor_replica(res, entradas, base_usuario, referencia):
    """Factor de escala entre la posición del admin y la del usuario.
    El usuario pone un número (base_usuario) que se compara contra el
    margen de la 1ª entrada del admin, o contra su margen total."""
    ref = entradas[0]["margen"] if referencia == REPLICA_REF_PRIMERA else res["margen_total"]
    return (base_usuario / ref) if ref and ref > 0 else 0.0


def _liquidacion_tocada(senal, res):
    """¿La posición habría sido liquidada antes de cerrarse?
    Si el SL queda ANTES que la liquidación (caso normal), el SL salta
    primero y no hay liquidación. Solo hay liquidación posible si el SL
    está más allá del precio de liquidación (o la posición nace
    liquidada). En ese caso se mira el High/Low diario desde la fecha
    de la señal hasta su cierre (o hasta hoy si sigue abierta)."""
    if res is None or res["sin_liquidacion"]:
        return False
    if res["liquidada_al_abrir"]:
        return True
    es_largo = "LARGO" in str(senal.get("tipo", "")).upper()
    sl = float(senal.get("stop_loss") or 0)
    if not _sl_mas_alla_de_liquidacion(res, es_largo, sl):
        return False
    hist = _historial_desde_fecha(senal["ticker"], senal["fecha"])
    if hist is None or hist.empty:
        return False
    fecha_fin = senal.get("fecha_cierre")
    liq = res["precio_liquidacion"]
    for fecha_idx, fila in hist.iterrows():
        if fecha_fin and str(fecha_idx.date()) > str(fecha_fin):
            break
        hi = float(fila["High"]) if "High" in fila else float(fila["Close"])
        lo = float(fila["Low"]) if "Low" in fila else float(fila["Close"])
        if (es_largo and lo <= liq) or ((not es_largo) and hi >= liq):
            return True
    return False


def _calcular_fila_replica(s, res, precio_ref, factor, liquidada):
    """Fila del simulador replicando la posición del admin a escala.
    unidades/margen/costos = los del admin × factor. El P&L es el de la
    posición completa (Σ unidades × movimiento de precio) menos los
    costos de apertura escalados; nunca pierde más que el margen. Si la
    posición se liquidó, se pierde todo el margen."""
    estado = s.get("estado", "ABIERTA")
    es_largo = "LARGO" in str(s.get("tipo", "")).upper()
    unidades = res["unidades"] * factor
    margen = res["margen_total"] * factor
    costos = res["costos_total"] * factor
    precio_prom = res["precio_promedio"]

    if liquidada:
        pnl_usd = -margen
    else:
        diff = (precio_ref - precio_prom) if es_largo else (precio_prom - precio_ref)
        pnl_usd = max(diff * unidades - costos, -margen)
    capital_final = margen + pnl_usd
    ret_precio, _ = _calcular_retorno(s, precio_ref)
    ret_sobre_margen = (pnl_usd / margen * 100) if margen else 0.0

    return {
        "Fecha": s.get("fecha"), "Ticker": s.get("ticker"),
        "Categoría": s.get("categoria") or "🔹 Otro", "Tipo": s.get("tipo"),
        "Entrada usada (ponderada)": fmt_precio_local(precio_prom),
        "Estado": "💀 LIQUIDADA" if liquidada else estado,
        "Apalanc.": fmt_apal(res["apalancamiento_efectivo"]),
        "Escala": f"x{factor:.4g}",
        "Costos apertura": round(costos, 2),
        "Ret. Precio %": round(ret_precio, 2),
        "Ret. Apalancado %": round(ret_sobre_margen, 2),
        "Capital Asignado": round(margen, 2),
        "P&L (USD)": round(pnl_usd, 2),
        "Capital Final": round(capital_final, 2),
    }


def _filas_detalle_replica(s, entradas, factor):
    """Detalle entrada por entrada de cómo queda replicada la posición."""
    filas = []
    for i, e in enumerate(entradas):
        margen = e["margen"] * factor
        nominal = margen * e["apalancamiento"]
        filas.append({
            "Fecha": s.get("fecha"), "Ticker": s.get("ticker"), "Entrada": i + 1,
            "Precio": fmt_precio_exacto(e["precio"]),
            "Apalanc.": fmt_apal(e["apalancamiento"]),
            "Tu margen (USD)": round(margen, 2),
            "Tu costo de apertura (USD)": round(e["costo_apertura"] * factor, 4),
            "Tamaño nominal (USD)": round(nominal, 2),
            "Unidades": round(nominal / e["precio"], 6),
        })
    return filas


MODOS_CON_MARGEN = ("📦 Por lotes (tamaño de posición)",
                    "🎯 % de riesgo por operación (según Stop Loss)",
                    MODO_REPLICA)


def _mostrar_metricas_sim(df_sim, label_capital):
    capital_asignado_total = df_sim["Capital Asignado"].sum()
    pnl_total = df_sim["P&L (USD)"].sum()
    n_ganadoras = int((df_sim["P&L (USD)"] > 0).sum())
    n_total_sim = len(df_sim)
    winrate_sim = (n_ganadoras / n_total_sim * 100) if n_total_sim else 0

    k1, k2, k3, k4 = st.columns(4)
    with k1: st.metric(label_capital, f"USD {capital_asignado_total:,.2f}")
    with k2: st.metric("P&L total", f"USD {pnl_total:+,.2f}",
                        delta=f"{(pnl_total/capital_asignado_total*100):+.1f}%" if capital_asignado_total else None)
    with k3: st.metric("Operaciones ganadoras", f"{n_ganadoras}/{n_total_sim}")
    with k4: st.metric("Win Rate simulado", f"{winrate_sim:.1f}%")
    return capital_asignado_total, pnl_total


def _mostrar_tabla_estilizada(df_sim):
    def _color_pnl(val):
        try:
            v = float(val)
            return "color:#3fb950;font-weight:700" if v >= 0 else "color:#f85149;font-weight:700"
        except Exception:
            return ""

    def _color_estado_sim(val):
        col, _bg, _e = ESTADO_COLOR.get(val, ("#8b949e", "", ""))
        if "LIQUIDADA" in str(val):
            col = "#f85149"
        return f"color:{col};font-weight:700"

    format_dict = {"Ret. Precio %": "{:+.2f}%", "Ret. Apalancado %": "{:+.2f}%",
                   "Capital Asignado": "${:,.2f}", "P&L (USD)": "${:+,.2f}",
                   "Capital Final": "${:,.2f}"}
    if "Lotes" in df_sim.columns:
        format_dict["Lotes"] = "{:.2f}"
        format_dict["Unidades"] = "{:,.2f}"
    if "% Riesgo" in df_sim.columns:
        format_dict["% Riesgo"] = "{:.2f}%"
    if "Costos apertura" in df_sim.columns:
        format_dict["Costos apertura"] = "${:,.2f}"

    _map = "map" if hasattr(df_sim.style, "map") else "applymap"
    styled = (df_sim.style
              .pipe(lambda s: getattr(s, _map)(_color_pnl, subset=["P&L (USD)", "Ret. Apalancado %"]))
              .pipe(lambda s: getattr(s, _map)(_color_estado_sim, subset=["Estado"]))
              .format(format_dict)
              .set_properties(**{"background-color": "#0d1117", "color": "#e6edf3", "border": "1px solid #21262d"})
              .set_table_styles([
                  {"selector": "th", "props": [("background-color", "#161b22"), ("color", "#e6edf3"),
                      ("font-weight", "700"), ("text-align", "center"),
                      ("border-bottom", "2px solid #3a7bd5"), ("font-size", "11px")]},
                  {"selector": "td", "props": [("text-align", "center"), ("font-size", "11px")]},
              ]))
    st.dataframe(styled, use_container_width=True, height=min(600, max(150, len(df_sim) * 38 + 45)))


def _mostrar_mejor_peor(df_sim):
    if df_sim.empty:
        return
    mejor = df_sim.loc[df_sim["P&L (USD)"].idxmax()]
    peor = df_sim.loc[df_sim["P&L (USD)"].idxmin()]
    cM, cP = st.columns(2)
    with cM:
        st.markdown(f"""
        <div style="background:#0d1117;border:1px solid #21262d;border-left:3px solid #3fb950;
             border-radius:8px;padding:12px 16px">
          <div style="font-size:11px;color:#3fb950;font-weight:700">🏆 MEJOR OPERACIÓN</div>
          <div style="font-size:13px;color:#e6edf3;margin-top:4px">{mejor['Ticker']} · {mejor['Fecha']}</div>
          <div style="font-size:16px;font-weight:800;color:#3fb950">+${mejor['P&L (USD)']:,.2f}</div>
        </div>
        """, unsafe_allow_html=True)
    with cP:
        st.markdown(f"""
        <div style="background:#0d1117;border:1px solid #21262d;border-left:3px solid #f85149;
             border-radius:8px;padding:12px 16px">
          <div style="font-size:11px;color:#f85149;font-weight:700">📉 PEOR OPERACIÓN</div>
          <div style="font-size:13px;color:#e6edf3;margin-top:4px">{peor['Ticker']} · {peor['Fecha']}</div>
          <div style="font-size:16px;font-weight:800;color:#f85149">${peor['P&L (USD)']:,.2f}</div>
        </div>
        """, unsafe_allow_html=True)


# ==============================================================
#  RENDER — TAB SIMULADOR (todos)
#  Incluye el cálculo que antes vivía en "Gestor de Riesgo" (modo
#  "% de riesgo por operación") y la comparación de los 3 perfiles.
#  Cuando una señal tiene varias entradas, acá se usa el precio
#  promedio real de la posición (ponderado por el tamaño de cada
#  entrada), el mismo que se muestra en "Señales y Resultados".
# ==============================================================

MODOS_SIM = [
    "💵 Monto fijo por señal",
    "📊 % del capital por señal",
    "🎯 % de riesgo por operación (según Stop Loss)",
    "📦 Por lotes (tamaño de posición)",
    MODO_REPLICA,
    "🎭 Comparar los 3 perfiles de riesgo",
]


def _tab_simulador(supabase):
    st.caption("Simulá cuánto hubieras ganado o perdido replicando las señales publicadas, "
               "con tu propio capital.")
    st.caption(
        "🧩 Para señales con varias entradas, acá se usa el precio promedio real de la posición "
        "(ponderado por el tamaño de cada entrada: margen × apalancamiento). Las señales viejas "
        "cargadas con 'peso relativo' siguen usando ese promedio."
    )

    senales = _obtener_senales(supabase, 200)
    if not senales:
        st.info("Todavía no hay señales para simular.")
        return

    with st.spinner("Evaluando señales..."):
        _sincronizar_estados(supabase, senales)
        senales = _obtener_senales(supabase, 200)

    c1, c2, c3 = st.columns(3)
    with c1:
        capital_total = st.number_input("💰 Capital total (USD)", min_value=100.0,
                                         value=1000.0, step=100.0, key="sim_capital")
    with c2:
        modo = st.selectbox("Modo de asignación", MODOS_SIM, key="sim_modo")
    with c3:
        incluir_abiertas = st.checkbox("Incluir señales abiertas (P&L flotante)", value=True, key="sim_incluir_abiertas")

    monto_por_senal = None
    pct_por_senal = None
    riesgo_pct_sim = None
    unidades_por_categoria = {}
    cantidad_lotes = None
    ref_replica = None
    base_replica = None

    df_base = pd.DataFrame(senales)
    if "categoria" not in df_base.columns:
        df_base["categoria"] = "🔹 Otro"
    df_base["categoria"] = df_base["categoria"].fillna("🔹 Otro")
    if not incluir_abiertas:
        df_base = df_base[df_base["estado"] != "ABIERTA"]

    if modo == "💵 Monto fijo por señal":
        monto_por_senal = st.number_input("Monto por señal (USD)", min_value=10.0,
                                           value=min(100.0, capital_total), step=10.0, key="sim_monto_fijo")

    elif modo == "📊 % del capital por señal":
        pct_por_senal = st.slider("% del capital por señal", 1, 100, 10, key="sim_pct")

    elif modo == "🎯 % de riesgo por operación (según Stop Loss)":
        riesgo_pct_sim = st.slider(
            "% de tu capital dispuesto a arriesgar por operación", 0.1, 20.0, 1.0, step=0.1,
            key="sim_riesgo_pct",
            help="Si el precio llega al Stop Loss, esto es lo máximo que perderías en esa señal.")
        st.caption(
            "El monto por señal ya no se define a mano: se calcula solo a partir de este % y de "
            "la distancia entre la entrada y el Stop Loss de cada señal (mismo cálculo que antes "
            "vivía en 'Gestor de Riesgo')."
        )

    elif modo == "📦 Por lotes (tamaño de posición)":
        st.markdown("#### 📦 Configuración de lotes")
        st.caption(
            "Un 'lote' es una cantidad estandarizada de unidades del activo. El P&L se calcula "
            "como en un bróker real: movimiento de precio × tamaño de la posición. El "
            "apalancamiento no cambia la ganancia/pérdida en dólares, solo el margen (capital) "
            "que necesitás inmovilizar para abrir esa posición. **Cada bróker define distinto "
            "cuántas unidades tiene 1 lote** (sobre todo en Forex, índices y commodities) — "
            "ajustá los valores de abajo según cómo opera el tuyo."
        )

        categorias_presentes = sorted(df_base["categoria"].dropna().unique().tolist())
        if not categorias_presentes:
            categorias_presentes = CATEGORIAS

        preset_fx = None
        if "💱 Forex" in categorias_presentes:
            preset_fx = st.selectbox(
                "Preset de lote Forex (tamaños comunes de bróker)",
                list(LOTES_FOREX_PRESETS.keys()) + ["Personalizado"],
                key="sim_lote_fx_preset",
            )

        n_cols = min(len(categorias_presentes), 3) or 1
        cols_upl = st.columns(n_cols)
        for i, cat in enumerate(categorias_presentes):
            default = DEFAULT_UNIDADES_LOTE.get(cat, 1.0)
            if cat == "💱 Forex" and preset_fx and preset_fx != "Personalizado":
                default = LOTES_FOREX_PRESETS[preset_fx]
            with cols_upl[i % n_cols]:
                unidades_por_categoria[cat] = st.number_input(
                    f"Unid./lote — {cat}", min_value=0.01, value=float(default),
                    step=1.0, key=f"sim_upl_{cat}",
                    help="Unidades del activo que representa 1 lote completo para este bróker."
                )

        cantidad_lotes = st.number_input(
            "Cantidad de lotes por operación", min_value=0.01, value=0.10, step=0.01,
            format="%.2f", key="sim_cant_lotes",
            help="Ej: 0.10 lotes en Forex estándar = 10.000 unidades de la divisa base."
        )

    elif modo == MODO_REPLICA:
        st.markdown("#### 🔁 Replicar la posición del publicador")
        ref_replica = st.radio(
            "El número que ponés corresponde a:", [REPLICA_REF_PRIMERA, REPLICA_REF_TOTAL],
            horizontal=True, key="sim_replica_ref")
        base_replica = st.number_input(
            f"Tu {ref_replica.lower()} (USD)", min_value=0.01, value=10.0, step=1.0,
            format="%.2f", key="sim_replica_base")
        st.caption(
            "Ponés un solo número y la app copia la posición del publicador tal cual: mismas "
            "entradas, mismos precios y mismo apalancamiento en cada una. El margen y el costo de "
            "apertura de cada entrada se escalan en la misma proporción. Ej: si el publicador puso "
            "100 de margen en cada una de sus 2 entradas y vos ponés 10 (referido a la 1ª entrada), "
            "tu margen queda en 10 en cada una — un décimo de su posición. El precio de "
            "liquidación es el mismo que el suyo. Las señales viejas, sin margen cargado, no se "
            "pueden replicar y quedan afuera."
        )

    else:  # Comparar los 3 perfiles de riesgo
        st.markdown("#### 🎭 Los 3 perfiles de riesgo")
        st.caption(
            "Cada señal ya tiene definido, desde que se publicó, qué % de capital arriesgaría "
            "cada perfil. Acá corremos la simulación completa una vez por perfil, para que "
            "compares el resultado."
        )
        for info in PERFILES_RIESGO.values():
            st.markdown(f"**{info['label']}** — {info['desc']}")

    if df_base.empty:
        st.info("No hay señales para incluir en la simulación con estos filtros.")
        return

    # ----------------------------------------------------------
    #  Modo especial: comparar los 3 perfiles lado a lado
    # ----------------------------------------------------------
    if modo == "🎭 Comparar los 3 perfiles de riesgo":
        st.divider()
        tabs_perfiles = st.tabs([info["label"] for info in PERFILES_RIESGO.values()])
        resumen_comparativo = []

        for (perfil_key, info), tab in zip(PERFILES_RIESGO.items(), tabs_perfiles):
            with tab:
                st.caption(info["desc"])
                filas = []
                for _, row in df_base.iterrows():
                    s = row.to_dict()
                    s = _senal_con_precio_entrada(s, _precio_promedio_ponderado(s))
                    precio_ref = s.get("precio_cierre")
                    if precio_ref is None:
                        ev = _evaluar_senal(s)
                        precio_ref = ev["precio_ref"]
                    if precio_ref is None:
                        continue
                    pct_signal = float(s.get(f"riesgo_{perfil_key}") or info["default_pct"])
                    fila = _calcular_fila_simulacion(s, precio_ref, capital_total, "riesgo",
                                                      riesgo_pct=pct_signal)
                    if fila:
                        filas.append(fila)

                if not filas:
                    st.info("No se pudo simular ninguna señal con este perfil (faltan datos de SL/entrada).")
                    continue

                df_perfil = pd.DataFrame(filas)
                capital_usado, pnl_total = _mostrar_metricas_sim(df_perfil, "Margen total usado")
                resumen_comparativo.append((info["label"], pnl_total, capital_usado))
                _mostrar_tabla_estilizada(df_perfil)
                _mostrar_mejor_peor(df_perfil)

        if resumen_comparativo:
            st.divider()
            st.markdown("##### 📊 Resumen comparativo")
            df_resumen = pd.DataFrame(
                resumen_comparativo, columns=["Perfil", "P&L Total (USD)", "Margen Usado (USD)"])
            df_resumen["Rendimiento %"] = df_resumen.apply(
                lambda r: round(r["P&L Total (USD)"] / r["Margen Usado (USD)"] * 100, 2)
                if r["Margen Usado (USD)"] else 0.0, axis=1)
            st.dataframe(df_resumen, use_container_width=True, hide_index=True)

        st.caption("⚠️ Simulación educativa. No contempla comisiones, spread, financiamiento por "
                   "apalancamiento, swap ni slippage. No constituye asesoramiento financiero.")
        return

    # ----------------------------------------------------------
    #  Resto de los modos: una sola tabla
    # ----------------------------------------------------------
    filas_sim = []
    filas_detalle = []
    omitidas_replica = 0
    for _, row in df_base.iterrows():
        s = row.to_dict()
        s = _senal_con_precio_entrada(s, _precio_promedio_ponderado(s))
        estado = s.get("estado", "ABIERTA")
        precio_ref = s.get("precio_cierre")
        if precio_ref is None:
            ev = _evaluar_senal(s)
            precio_ref = ev["precio_ref"]
        if precio_ref is None:
            continue

        cat = s.get("categoria") or "🔹 Otro"
        if modo == "📦 Por lotes (tamaño de posición)":
            unidades_por_lote = unidades_por_categoria.get(cat, DEFAULT_UNIDADES_LOTE.get(cat, 1.0))
            fila = _calcular_fila_simulacion(s, precio_ref, capital_total, "lotes",
                                              unidades_por_lote=unidades_por_lote,
                                              cantidad_lotes=cantidad_lotes)
        elif modo == MODO_REPLICA:
            fila = None
            res_rep = _resumen_de_senal(row.to_dict())
            if res_rep is None:
                omitidas_replica += 1
            else:
                entradas_rep = _entradas_de_senal(row.to_dict())
                factor_rep = _factor_replica(res_rep, entradas_rep, base_replica, ref_replica)
                if factor_rep <= 0:
                    omitidas_replica += 1
                else:
                    liquidada_rep = _liquidacion_tocada(row.to_dict(), res_rep)
                    fila = _calcular_fila_replica(s, res_rep, precio_ref, factor_rep, liquidada_rep)
                    filas_detalle.extend(_filas_detalle_replica(s, entradas_rep, factor_rep))
        elif modo == "🎯 % de riesgo por operación (según Stop Loss)":
            fila = _calcular_fila_simulacion(s, precio_ref, capital_total, "riesgo",
                                              riesgo_pct=riesgo_pct_sim)
        else:
            fila = _calcular_fila_simulacion(s, precio_ref, capital_total, "monto_pct",
                                              monto_por_senal=monto_por_senal,
                                              pct_por_senal=pct_por_senal)
        if fila:
            filas_sim.append(fila)

    if not filas_sim:
        if modo == MODO_REPLICA and omitidas_replica:
            st.info("No hay señales para replicar: las publicadas no tienen margen cargado en sus "
                    "entradas (son de la versión anterior).")
        else:
            st.info("No se pudo simular ninguna señal (faltan precios de referencia o datos de SL/entrada).")
        return

    df_sim = pd.DataFrame(filas_sim)
    label_capital = ("Margen total usado" if modo in MODOS_CON_MARGEN
                      else "Capital asignado total")

    capital_asignado_total, _ = _mostrar_metricas_sim(df_sim, label_capital)

    if modo in MODOS_CON_MARGEN and capital_asignado_total > capital_total:
        st.warning(
            f"⚠️ El margen total requerido (USD {capital_asignado_total:,.2f}) supera tu "
            f"capital declarado (USD {capital_total:,.2f}). Con esta configuración estarías "
            "sobre-apalancado si abrieras todas estas operaciones a la vez."
        )

    _mostrar_tabla_estilizada(df_sim)
    _mostrar_mejor_peor(df_sim)

    if modo == MODO_REPLICA:
        if omitidas_replica:
            st.caption(f"ℹ️ {omitidas_replica} señal(es) quedaron afuera porque son de la versión "
                       "anterior (sin margen cargado) y no se pueden replicar.")
        if filas_detalle:
            with st.expander("🔍 Ver cómo queda replicada cada entrada"):
                st.dataframe(pd.DataFrame(filas_detalle), use_container_width=True, hide_index=True)
        st.caption("En este modo el P&L ya descuenta los costos de apertura (escalados a tu margen) "
                   "y, si el precio tocó la liquidación, se pierde todo el margen. No incluye "
                   "funding/swap ni comisión de cierre.")

    st.caption("⚠️ Simulación educativa. No contempla comisiones, spread, financiamiento por apalancamiento, "
               "swap ni slippage. Cuando TP y SL se tocan el mismo día se asume el peor caso (SL). En los "
               "modos por lotes y por % de riesgo, los valores usados (unidades por lote, distancia al SL) "
               "son configurables o dependen de cada señal: verificá las especificaciones de tu bróker antes "
               "de usarlos como referencia real. No constituye asesoramiento financiero.")


# ==============================================================
#  ENTRY POINT — llamar desde app.py
# ==============================================================

def render_senales_trading(supabase, user_id, user_email):
    """Uso desde app.py:
        from modulo_senales_trading import render_senales_trading
        render_senales_trading(supabase, USER_ID, st.session_state['usuario'].email)

    NOTA DE MIGRACIÓN: si tu tabla en Supabase todavía no tiene estas
    columnas, corré en el SQL editor:
        ALTER TABLE senales_trading
        ADD COLUMN IF NOT EXISTS categoria text DEFAULT '🔹 Otro',
        ADD COLUMN IF NOT EXISTS riesgo_conservador float DEFAULT 1.0,
        ADD COLUMN IF NOT EXISTS riesgo_moderado    float DEFAULT 2.0,
        ADD COLUMN IF NOT EXISTS riesgo_agresivo    float DEFAULT 3.0,
        ADD COLUMN IF NOT EXISTS entradas jsonb DEFAULT '[]'::jsonb;
    (Los campos nuevos de cada entrada —costo_apertura, apalancamiento,
    margen— viven dentro del jsonb "entradas": no hace falta migrar nada más.)
    """
    es_admin = _es_admin(user_email)

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #bc5cff;
         border-radius:14px; padding:22px 28px; margin-bottom:20px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:4px">
        🎯 Señales de Trading
      </div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.6">
        Señales publicadas con fecha, hora, una o varias entradas (precio, costo de apertura,
        apalancamiento y margen), precio de liquidación, stop loss, take profit, categoría y
        perfiles de riesgo (🟢 Conservador / 🟡 Moderado / 🔴 Agresivo) — evaluación automática
        de aciertos/desaciertos y simulador de capital (por monto, %, riesgo, lotes o comparando
        los 3 perfiles) para cualquier usuario.
      </div>
    </div>
    """, unsafe_allow_html=True)

    tab_pub, tab_hist, tab_sim = st.tabs([
        "📢 Publicar Señal", "📋 Señales y Resultados", "🧮 Simulador de Capital",
    ])
    with tab_pub:
        _tab_publicar(supabase, user_id, user_email, es_admin)
    with tab_hist:
        _tab_senales(supabase, es_admin)
    with tab_sim:
        _tab_simulador(supabase)
