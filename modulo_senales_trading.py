# ==============================================================
#  MÓDULO SEÑALES DE TRADING — Streamlit + Supabase
#  Solo ADMIN_EMAIL publica señales; todos pueden verlas y simular.
#  La protección real está en las políticas RLS de Supabase
#  (ver senales_trading_schema.sql). El email de acá abajo tiene que
#  coincidir EXACTAMENTE con el de esas políticas.
#
#  LÍMITES POR PLAN (NUEVO):
#   - Plan Pro / Admin: señales ilimitadas.
#   - Plan Básico y Trial: máximo 1 señal por día, solo lunes a viernes
#     (se ve la primera del día; configurable abajo).
#   - app.py decide qué plan es "pro para señales" y lo pasa en
#     render_senales_trading(..., tiene_acceso_pro=...).
#
#  MIGRACIÓN DE SUPABASE (si todavía no la hiciste):
#     ALTER TABLE senales_trading
#       ADD COLUMN IF NOT EXISTS categoria text DEFAULT '🔹 Otro',
#       ADD COLUMN IF NOT EXISTS riesgo_conservador float DEFAULT 1.0,
#       ADD COLUMN IF NOT EXISTS riesgo_moderado    float DEFAULT 2.0,
#       ADD COLUMN IF NOT EXISTS riesgo_agresivo    float DEFAULT 3.0,
#       ADD COLUMN IF NOT EXISTS entradas jsonb DEFAULT '[]'::jsonb,
#       ADD COLUMN IF NOT EXISTS hora_cierre text,
#       ADD COLUMN IF NOT EXISTS fecha_activacion date,
#       ADD COLUMN IF NOT EXISTS hora_activacion text;
#   Si la columna "estado" tiene un CHECK constraint, agregale 'PENDIENTE'.
#
#  FUNCIONALIDADES:
#   - Varias entradas por señal (precio, costo apertura, apalancamiento,
#     margen apertura, margen extra) → precio promedio real, apalancamiento
#     de apertura y precio de liquidación.
#   - Órdenes pendientes (entrada límite) que se activan solas cuando el
#     precio toca la entrada; TP/SL se evalúa desde la activación.
#   - Evaluación automática de TP/SL con velas horarias + diarias.
#   - P&L en vivo (cada 5 min) para señales abiertas.
#   - Réplica de la posición a tu margen, y Simulador de Capital.
# ==============================================================

import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, datetime, time as dt_time, timedelta
from streamlit_autorefresh import st_autorefresh

ADMIN_EMAIL = "brainferreyra@gmail.com"
TABLA_SENALES = "senales_trading"

# ── Límites por plan ──────────────────────────────────────────
# Plan Básico / Trial: máximo 1 señal por día, solo lunes a viernes.
# Plan Pro / Admin: sin límites.
BASICO_MAX_SENALES_POR_DIA = 1
BASICO_DIAS_HABILES = (0, 1, 2, 3, 4)   # 0=lunes ... 4=viernes (agregá 5, 6 para fin de semana)
BASICO_ELEGIR = "primera"               # "primera" o "ultima" señal del día

# Margen de mantenimiento que exige el bróker, como % del tamaño
# nominal de la posición. Se usa SOLO para calcular el precio de
# liquidación. Con 0.0 se asume que te liquidan cuando el margen
# (menos los costos de apertura) se consume por completo.
MARGEN_MANTENIMIENTO_PCT = 0.0

ESTADO_COLOR = {
    "PENDIENTE":            ("#a371f7", "rgba(163,113,247,0.12)", "🕓"),
    "ABIERTA":              ("#3a7bd5", "rgba(58,123,213,0.12)", "🔵"),
    "ACIERTO (TP)":         ("#3fb950", "rgba(63,185,80,0.12)",  "✅"),
    "DESACIERTO (SL)":      ("#f85149", "rgba(248,81,73,0.12)",  "❌"),
    "CERRADA MANUAL":       ("#e3b341", "rgba(227,179,65,0.12)", "⚪"),
}

CATEGORIAS = [
    "📈 Acción", "📊 Índice", "🛢️ Commodity", "💱 Forex",
    "₿ Cripto", "🏦 Bono/ETF", "🔹 Otro",
]

DEFAULT_UNIDADES_LOTE = {
    "💱 Forex":     100000.0,
    "₿ Cripto":     1.0,
    "📈 Acción":    100.0,
    "📊 Índice":    10.0,
    "🛢️ Commodity": 100.0,
    "🏦 Bono/ETF":  100.0,
    "🔹 Otro":      1.0,
}

LOTES_FOREX_PRESETS = {
    "Estándar (1 lote = 100.000 unidades)": 100000.0,
    "Mini (1 lote = 10.000 unidades)":      10000.0,
    "Micro (1 lote = 1.000 unidades)":      1000.0,
    "Nano (1 lote = 100 unidades)":         100.0,
}

PERFILES_RIESGO = {
    "conservador": {
        "label": "🟢 Conservador",
        "default_pct": 1.0,
        "desc": ("Prioriza cuidar el capital por sobre todo. Arriesga poco en cada "
                 "operación para amortiguar rachas de pérdidas — a cambio, las "
                 "ganancias en dólares también son más chicas."),
    },
    "moderado": {
        "label": "🟡 Moderado",
        "default_pct": 2.0,
        "desc": ("Un punto medio entre cuidar el capital y buscar rendimiento. "
                 "Asume más volatilidad que el conservador a cambio de un "
                 "potencial de ganancia mayor."),
    },
    "agresivo": {
        "label": "🔴 Agresivo",
        "default_pct": 3.0,
        "desc": ("Busca maximizar el retorno asumiendo el mayor riesgo por "
                 "operación. Tanto las pérdidas como las ganancias en dólares son "
                 "más grandes."),
    },
}
PERFILES_LABEL_A_KEY = {v["label"]: k for k, v in PERFILES_RIESGO.items()}


def _es_admin(user_email):
    return bool(user_email) and user_email.strip().lower() == ADMIN_EMAIL.strip().lower()


# ==============================================================
#  LÍMITES POR PLAN
# ==============================================================

def _filtrar_senales_por_plan(senales, es_pro):
    """Devuelve (senales_visibles, cantidad_ocultas).
    Pro: todas. Básico/Trial: solo lun-vie y máx. BASICO_MAX_SENALES_POR_DIA por día."""
    if es_pro or not senales:
        return senales, 0

    por_dia = {}
    for s in senales:
        try:
            f = datetime.strptime(str(s.get("fecha"))[:10], "%Y-%m-%d").date()
        except Exception:
            continue
        if f.weekday() not in BASICO_DIAS_HABILES:
            continue
        por_dia.setdefault(f, []).append(s)

    visibles = []
    for f, lista in por_dia.items():
        lista_ord = sorted(lista, key=lambda x: str(x.get("hora") or ""),
                           reverse=(BASICO_ELEGIR == "ultima"))
        visibles.extend(lista_ord[:BASICO_MAX_SENALES_POR_DIA])

    visibles.sort(key=lambda x: (str(x.get("fecha")), str(x.get("hora") or "")), reverse=True)
    return visibles, len(senales) - len(visibles)


def _banner_plan_basico(ocultas):
    if ocultas:
        msg = (f"🔒 **Plan Básico / Prueba**: ves 1 señal por día (lunes a viernes). "
               f"Hay **{ocultas}** señal(es) más que solo ve el plan Pro, que tiene señales ilimitadas.")
    else:
        msg = ("🔒 **Plan Básico / Prueba**: ves 1 señal por día (lunes a viernes). "
               "El plan Pro tiene señales ilimitadas.")
    st.info(msg)


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
    """Como fmt_precio_local pero sin redondear a entero los precios grandes."""
    if p is None:
        return "S/D"
    p = float(p)
    if p >= 10:
        return f"${p:,.2f}"
    return f"${p:.5f}"


def fmt_apal(x):
    try:
        return f"{round(float(x), 2):g}x"
    except (TypeError, ValueError):
        return "S/D"


def fmt_unidades(u):
    s = f"{float(u):,.6f}".rstrip("0").rstrip(".")
    return s or "0"


def _md_dolar(texto):
    """Escapa los '$' para que Streamlit no los interprete como LaTeX."""
    return texto.replace("$", r"\$")


# ==============================================================
#  ENTRADAS MÚLTIPLES — helpers de posición
# ==============================================================

def _entradas_de_senal(senal):
    """Lista de entradas normalizada. 'margen' = 0 significa señal vieja."""
    apal_senal = float(senal.get("apalancamiento") or 1.0) or 1.0
    default_activada = senal.get("estado") != "PENDIENTE"
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
                    "margen_extra": float(e.get("margen_extra") or 0.0),
                    "peso": float(e.get("peso") or 1.0),
                    "activada": bool(e.get("activada", default_activada)),
                    "fecha_activacion": e.get("fecha_activacion"),
                    "hora_activacion": e.get("hora_activacion"),
                })
            except (TypeError, ValueError, AttributeError):
                continue
        if limpio:
            return limpio
    precio_unico = float(senal.get("precio_entrada") or 0)
    if precio_unico > 0:
        return [{"precio": precio_unico, "costo_apertura": 0.0,
                 "apalancamiento": apal_senal, "margen": 0.0,
                 "margen_extra": 0.0, "peso": 1.0,
                 "activada": default_activada, "fecha_activacion": None,
                 "hora_activacion": None}]
    return []


def _resumen_posicion(entradas, es_largo, mantenimiento_pct=MARGEN_MANTENIMIENTO_PCT):
    """Calcula la posición total a partir de las entradas.

    nominal_i  = margen_i × apalancamiento_i (solo el margen de apertura define tamaño)
    unidades_i = nominal_i / precio_i
    precio promedio = Σ nominal / Σ unidades
    margen total = Σ margen apertura + Σ margen extra
    LARGO : liquidación = promedio − colchón / unidades
    CORTO : liquidación = promedio + colchón / unidades
    colchón = margen total − costos apertura − mantenimiento
    Devuelve None si no hay entradas válidas."""
    validas = [e for e in entradas
               if float(e.get("precio") or 0) > 0
               and float(e.get("margen") or 0) > 0
               and float(e.get("apalancamiento") or 0) > 0]
    if not validas:
        return None

    nominal = sum(e["margen"] * e["apalancamiento"] for e in validas)
    unidades = sum(e["margen"] * e["apalancamiento"] / e["precio"] for e in validas)
    margen_apertura_total = sum(e["margen"] for e in validas)
    margen_extra_total = sum(float(e.get("margen_extra") or 0.0) for e in validas)
    margen_total = margen_apertura_total + margen_extra_total
    costos_total = sum(float(e.get("costo_apertura") or 0.0) for e in validas)
    precio_prom = nominal / unidades
    apal_ef = nominal / margen_total
    apal_apertura = (nominal / margen_apertura_total) if margen_apertura_total else apal_ef

    mantenimiento_usd = nominal * mantenimiento_pct / 100.0
    colchon = margen_total - costos_total - mantenimiento_usd
    liquidada_al_abrir = colchon <= 0
    distancia = max(colchon, 0.0) / unidades

    if es_largo:
        liq_raw = precio_prom - distancia
        sin_liquidacion = liq_raw <= 0
        precio_liq = max(liq_raw, 0.0)
    else:
        precio_liq = precio_prom + distancia
        sin_liquidacion = False

    dist_pct = (precio_liq - precio_prom) / precio_prom * 100.0

    return dict(
        precio_promedio=precio_prom, unidades=unidades, nominal=nominal,
        margen_total=margen_total, margen_apertura=margen_apertura_total,
        margen_extra=margen_extra_total, costos_total=costos_total,
        apalancamiento_apertura=apal_apertura, apalancamiento_efectivo=apal_ef,
        colchon=colchon,
        precio_liquidacion=precio_liq, dist_liq_pct=dist_pct,
        sin_liquidacion=sin_liquidacion, liquidada_al_abrir=liquidada_al_abrir,
        n_entradas=len(validas),
    )


def _resumen_de_senal(senal):
    entradas = _entradas_de_senal(senal)
    if not entradas or not all(e["margen"] > 0 for e in entradas):
        return None
    es_largo = "LARGO" in str(senal.get("tipo", "")).upper()
    return _resumen_posicion(entradas, es_largo)


def _apalancamiento_apertura_de_senal(senal):
    """Apalancamiento realmente usado para ABRIR la posición (sin diluir por margen extra)."""
    res = _resumen_de_senal(senal)
    if res:
        return res["apalancamiento_apertura"]
    return float(senal.get("apalancamiento") or 1.0) or 1.0


def _sl_mas_alla_de_liquidacion(res, es_largo, stop_loss):
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
    s2 = dict(senal)
    s2["precio_entrada"] = precio_entrada
    return s2


def _texto_entradas(entradas):
    partes = []
    for i, e in enumerate(entradas):
        t = f"Entrada {i + 1}: {fmt_precio_exacto(e['precio'])}"
        if e["margen"] > 0:
            t += f" · margen ${e['margen']:,.2f} · {fmt_apal(e['apalancamiento'])}"
            if e.get("margen_extra", 0) > 0:
                t += f" · +${e['margen_extra']:,.2f} extra"
            if e["costo_apertura"] > 0:
                t += f" · costo ${e['costo_apertura']:,.2f}"
        elif abs(e["peso"] - 1.0) > 1e-9:
            t += f" (peso {e['peso']:.2f})"
        partes.append(t)
    return " | ".join(partes)


def _texto_cierre(estado, fecha_cierre, hora_cierre):
    if estado == "ABIERTA":
        return "Sigue abierta"
    if not fecha_cierre:
        return "—"
    if hora_cierre:
        return f"{fecha_cierre} {hora_cierre}"
    return str(fecha_cierre)


def _cierre_manual_fue_ganador(senal):
    """True/False según el signo del retorno al precio de cierre; None si no se puede determinar."""
    precio_cierre = senal.get("precio_cierre")
    if precio_cierre is None:
        return None
    try:
        precio_cierre = float(precio_cierre)
    except (TypeError, ValueError):
        return None
    _ret_precio, ret_apalancado = _calcular_retorno(senal, precio_cierre)
    return ret_apalancado > 0


def _render_resumen_posicion(res, es_largo, stop_loss=None):
    st.markdown("##### 🧮 Posición total y precio de liquidación")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Precio promedio", fmt_precio_exacto(res["precio_promedio"]))
    m2.metric("Margen de apertura", f"${res['margen_apertura']:,.2f}")
    m3.metric("Tamaño (nominal)", f"${res['nominal']:,.2f}")
    m4.metric("Apalancamiento usado", fmt_apal(res["apalancamiento_apertura"]))

    if res.get("margen_extra", 0) > 0:
        e1, e2, e3 = st.columns(3)
        e1.metric("Margen extra agregado", f"${res['margen_extra']:,.2f}")
        e2.metric("Margen total (apertura + extra)", f"${res['margen_total']:,.2f}")
        e3.metric("Apalanc. efectivo (con extra)", fmt_apal(res["apalancamiento_efectivo"]))
        st.caption(
            "El margen extra no suma tamaño a la posición (el nominal y las unidades se "
            "calculan solo con el margen de apertura): solo agranda el colchón contra la "
            "liquidación. Por eso el apalancamiento EFECTIVO queda más bajo que el que usaste "
            "al abrirla."
        )

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
        st.warning(_md_dolar(
            f"⚠️ El Stop Loss ({fmt_precio_exacto(stop_loss)}) queda más allá del precio de "
            f"liquidación ({fmt_precio_exacto(res['precio_liquidacion'])}): te liquidarían antes "
            "de que el SL se ejecute."))

    st.caption(
        "Fórmula: liquidación = precio promedio "
        f"{'−' if es_largo else '+'} (margen total [apertura + extra] − costos de apertura − "
        f"mantenimiento {MARGEN_MANTENIMIENTO_PCT:g}%) / unidades. Es una estimación con margen "
        "aislado; no incluye funding/swap ni comisión de cierre."
    )


# ----------------------------------------------------------------
#  Formulario dinámico de entradas (usado solo al publicar)
# ----------------------------------------------------------------

def _entrada_vacia(_id, apal=1.0):
    return {"id": _id, "precio": 0.0, "costo": 0.0, "apal": float(apal),
            "margen": 0.0, "margen_extra": 0.0}


def _limpiar_keys_entrada(ent):
    for pref in ("precio", "costo", "apal", "margen", "margen_extra"):
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


def _entradas_para_guardar(entradas_form, es_pendiente=False):
    return [
        {"precio": float(e["precio"]),
         "costo_apertura": float(e["costo"]),
         "apalancamiento": float(e["apal"]),
         "margen": float(e["margen"]),
         "margen_extra": float(e.get("margen_extra") or 0.0),
         "activada": not es_pendiente,
         "fecha_activacion": None,
         "hora_activacion": None}
        for e in entradas_form if e["precio"] > 0 and e["margen"] > 0
    ]


def _render_entradas_form(es_largo, es_pendiente=False):
    _init_entradas_state()
    entradas = st.session_state["sen_entradas"]

    st.markdown("#### 🎯💰 Entradas")
    if es_pendiente:
        st.caption(
            "Como marcaste **orden pendiente**, el precio que cargues acá es el precio "
            "OBJETIVO (de entrada límite): la posición todavía no está abierta. Cargá igual el "
            "costo de apertura, apalancamiento y margen que pensás usar CUANDO se active, para "
            "que la app te muestre una vista previa del precio de liquidación."
        )
    else:
        st.caption(
            "Cargá una entrada por cada compra/venta si vas a promediar precio. Para cada una "
            "indicá el **precio**, el **costo de apertura** en USD, el **apalancamiento** y el "
            "**margen de apertura** en USD (define el tamaño de la posición). Si después le "
            "agregaste capital a esa entrada YA ABIERTA solo para alejar la liquidación, cargalo "
            "en **margen extra**: no cambia el tamaño ni el apalancamiento, pero sí la liquidación."
        )

    a_borrar = None
    for i, ent in enumerate(entradas):
        ce1, ce2, ce3, ce4, ce5, ce6 = st.columns([1.3, 1.0, 0.9, 1.1, 1.1, 0.4])
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
                f"Margen apertura (USD) {i + 1}", min_value=0.0, step=10.0, format="%.2f",
                value=float(ent.get("margen", 0.0)), key=f"sen_entrada_margen_{ent['id']}",
                help="Margen con el que ABRISTE esta entrada. nominal = margen × apalancamiento.")
        with ce5:
            ent["margen_extra"] = st.number_input(
                f"Margen extra (USD) {i + 1}", min_value=0.0, step=10.0, format="%.2f",
                value=float(ent.get("margen_extra", 0.0)), key=f"sen_entrada_margen_extra_{ent['id']}",
                help="Margen agregado DESPUÉS de abrir, sin comprar más unidades (top-up).")
        with ce6:
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
        st.warning("⚠️ Completá precio **y** margen de apertura en la(s) entrada(s): "
                   + ", ".join(str(n) for n in incompletas)
                   + ". Las incompletas no se tienen en cuenta.")

    resumen = _resumen_posicion(_entradas_para_guardar(entradas, es_pendiente), es_largo)
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
        "estado": datos.get("estado", "ABIERTA"),
        "fecha_activacion": None, "hora_activacion": None,
        "precio_cierre": None, "fecha_cierre": None, "hora_cierre": None,
    }
    supabase.table(TABLA_SENALES).insert(row).execute()


@st.cache_data(ttl=120, show_spinner=False)
def _obtener_senales(_supabase, limite=200):
    res = (_supabase.table(TABLA_SENALES).select("*")
           .order("fecha", desc=True).order("hora", desc=True).limit(limite).execute())
    return res.data or []


def _actualizar_estado_senal(supabase, senal_id, estado, precio_cierre, fecha_cierre, hora_cierre=None):
    supabase.table(TABLA_SENALES).update({
        "estado": estado,
        "precio_cierre": precio_cierre,
        "fecha_cierre": str(fecha_cierre) if fecha_cierre else None,
        "hora_cierre": hora_cierre,
    }).eq("id", senal_id).execute()


def _borrar_senal(supabase, senal_id):
    supabase.table(TABLA_SENALES).delete().eq("id", senal_id).execute()


def _cerrar_senal_manual(supabase, senal_id, precio_cierre):
    supabase.table(TABLA_SENALES).update({
        "estado": "CERRADA MANUAL",
        "precio_cierre": precio_cierre,
        "fecha_cierre": str(date.today()),
        "hora_cierre": datetime.now().strftime("%H:%M:%S"),
    }).eq("id", senal_id).execute()


def _entradas_a_formato_guardado(entradas):
    return [
        {"precio": e["precio"], "costo_apertura": e["costo_apertura"],
         "apalancamiento": e["apalancamiento"], "margen": e["margen"],
         "margen_extra": e.get("margen_extra", 0.0),
         "activada": e.get("activada", True),
         "fecha_activacion": e.get("fecha_activacion"),
         "hora_activacion": e.get("hora_activacion")}
        for e in entradas
    ]


def _agregar_entrada_senal(supabase, senal_id, entradas, precio_entrada, apalancamiento):
    supabase.table(TABLA_SENALES).update({
        "entradas": entradas,
        "precio_entrada": precio_entrada,
        "apalancamiento": apalancamiento,
    }).eq("id", senal_id).execute()


# ==============================================================
#  EVALUACIÓN AUTOMÁTICA — TP/SL y activación de órdenes pendientes
#  Velas horarias (últimos 7 días, desde el momento de referencia)
#  + velas diarias para días siguientes. Si TP y SL se tocan en la
#  misma vela, se asume el peor caso (SL).
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


@st.cache_data(ttl=900, show_spinner=False)
def _historial_intradia_desde(ticker, fecha_str, hora_str):
    """Velas horarias de los últimos 7 días, desde fecha_str + hora_str.
    Se comparan sin ajustar zona horaria (aproximación)."""
    try:
        import yfinance as yf
        df = yf.download(ticker, period="7d", interval="1h",
                          auto_adjust=True, progress=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Close"])
        if df.empty:
            return None
        df = df.copy()
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        try:
            corte = pd.Timestamp(f"{fecha_str} {hora_str or '00:00:00'}")
        except Exception:
            return df
        df = df[df.index >= corte]
        return df if not df.empty else None
    except Exception:
        return None


def _construir_historial_activacion(ticker, fecha_anchor, hora_anchor):
    """Lista de tuplas (timestamp, high, low, es_intradia) ordenada cronológicamente."""
    filas = []
    hist_intra = _historial_intradia_desde(
        ticker, str(fecha_anchor), str(hora_anchor) if hora_anchor else None)
    if hist_intra is not None and not hist_intra.empty:
        for ts, fila in hist_intra.iterrows():
            hi = float(fila["High"]) if "High" in fila else float(fila["Close"])
            lo = float(fila["Low"]) if "Low" in fila else float(fila["Close"])
            filas.append((ts, hi, lo, True))

    try:
        fecha_dt = datetime.strptime(str(fecha_anchor), "%Y-%m-%d").date()
        fecha_desde_diario = str(fecha_dt + timedelta(days=1))
    except Exception:
        fecha_desde_diario = str(fecha_anchor)

    hist_d = _historial_desde_fecha(ticker, fecha_desde_diario)
    if hist_d is not None and not hist_d.empty:
        for ts, fila in hist_d.iterrows():
            hi = float(fila["High"]) if "High" in fila else float(fila["Close"])
            lo = float(fila["Low"]) if "Low" in fila else float(fila["Close"])
            filas.append((ts, hi, lo, False))

    filas.sort(key=lambda x: x[0])
    return filas


# ── P&L EN VIVO (caché de 5 minutos) ──────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def _precio_en_vivo(ticker):
    """Último precio disponible. Devuelve (precio, hora_consulta) o (None, None)."""
    try:
        import yfinance as yf
        df = yf.download(ticker, period="1d", interval="1m",
                          auto_adjust=True, progress=False)
        if df is None or df.empty:
            df = yf.download(ticker, period="5d", interval="1d",
                              auto_adjust=True, progress=False)
        if df is None or df.empty:
            return None, None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        serie = df["Close"].dropna()
        if serie.empty:
            return None, None
        return float(serie.iloc[-1]), datetime.now()
    except Exception:
        return None, None


def _pnl_vivo_senal(senal, precio_actual):
    if precio_actual is None or precio_actual <= 0:
        return None
    entrada = _precio_promedio_ponderado(senal)
    if not entrada or entrada <= 0:
        return None
    apalancamiento = _apalancamiento_apertura_de_senal(senal)
    es_largo = "LARGO" in str(senal.get("tipo", "")).upper()
    ret_precio = (precio_actual - entrada) / entrada
    if not es_largo:
        ret_precio = -ret_precio
    ret_apalancado = ret_precio * apalancamiento
    return dict(
        ret_precio=ret_precio * 100,
        ret_apalancado=ret_apalancado * 100,
        ganando=ret_apalancado > 0,
        entrada=entrada,
        precio_actual=precio_actual,
    )


def _render_badge_pnl_vivo(pnl, hora_actualizacion):
    if pnl is None:
        st.caption("⏳ No se pudo obtener el precio en vivo para esta señal en este momento.")
        return

    color = "#3fb950" if pnl["ganando"] else "#f85149"
    bg = "rgba(63,185,80,0.12)" if pnl["ganando"] else "rgba(248,81,73,0.12)"
    icono = "🟢" if pnl["ganando"] else "🔴"
    texto = "GANANDO" if pnl["ganando"] else "PERDIENDO"

    hace = ""
    if hora_actualizacion:
        mins = int((datetime.now() - hora_actualizacion).total_seconds() // 60)
        hace = "recién" if mins <= 0 else f"hace {mins} min"

    st.markdown(f"""
    <div style="background:{bg};border:1px solid {color};border-radius:10px;
         padding:10px 16px;margin:8px 0 4px 0;display:flex;align-items:center;
         justify-content:space-between;flex-wrap:wrap;gap:8px">
      <div>
        <div style="font-size:11px;color:{color};font-weight:700;letter-spacing:.5px">
          {icono} POSICIÓN EN VIVO — {texto}
        </div>
        <div style="font-size:10px;color:#8b949e;margin-top:2px">
          Precio actual: {fmt_precio_exacto(pnl['precio_actual'])} · Entrada: {fmt_precio_exacto(pnl['entrada'])}
          · actualizado {hace} (se refresca cada 5 min)
        </div>
      </div>
      <div style="font-size:20px;font-weight:800;color:{color};white-space:nowrap">
        {pnl['ret_apalancado']:+.2f}%
      </div>
    </div>
    """, unsafe_allow_html=True)


def _evaluar_pendiente(senal):
    """Marca qué entradas de una orden PENDIENTE ya fueron tocadas por el precio."""
    entradas = _entradas_de_senal(senal)
    pendientes_idx = [i for i, e in enumerate(entradas) if not e.get("activada")]
    if not pendientes_idx:
        return entradas, True, senal.get("fecha_activacion"), senal.get("hora_activacion")

    filas = _construir_historial_activacion(senal["ticker"], senal["fecha"], senal.get("hora"))
    ultima_fecha_act = senal.get("fecha_activacion")
    ultima_hora_act = senal.get("hora_activacion")

    for ts, hi, lo, es_intradia in filas:
        if not pendientes_idx:
            break
        for i in list(pendientes_idx):
            precio_obj = entradas[i]["precio"]
            if lo <= precio_obj <= hi:
                entradas[i]["activada"] = True
                entradas[i]["fecha_activacion"] = str(ts.date())
                entradas[i]["hora_activacion"] = ts.strftime("%H:%M:%S") if es_intradia else None
                ultima_fecha_act = entradas[i]["fecha_activacion"]
                ultima_hora_act = entradas[i]["hora_activacion"] or ultima_hora_act
                pendientes_idx.remove(i)

    todas = len(pendientes_idx) == 0
    return entradas, todas, ultima_fecha_act, ultima_hora_act


def _evaluar_senal(senal):
    """Evalúa si una señal tocó TP o SL primero."""
    if senal.get("estado") in ("CERRADA MANUAL",):
        return dict(estado_calc=senal["estado"], precio_ref=senal.get("precio_cierre"),
                    fecha_ref=senal.get("fecha_cierre"), hora_ref=senal.get("hora_cierre"),
                    es_final=True)

    ticker = senal["ticker"]
    tipo = senal["tipo"]
    entrada = _precio_promedio_ponderado(senal)
    sl = float(senal["stop_loss"])
    tp = float(senal["take_profit"])
    es_largo = tipo.startswith("🟢") or "LARGO" in tipo.upper()

    fecha_anchor = senal.get("fecha_activacion") or senal.get("fecha")
    hora_anchor = senal.get("hora_activacion") or senal.get("hora")

    filas = _construir_historial_activacion(ticker, fecha_anchor, hora_anchor)
    if not filas:
        return dict(estado_calc="ABIERTA", precio_ref=entrada, fecha_ref=None,
                    hora_ref=None, es_final=False)

    for ts, hi, lo, es_intradia in filas:
        if es_largo:
            toco_sl = lo <= sl
            toco_tp = hi >= tp
        else:
            toco_sl = hi >= sl
            toco_tp = lo <= tp
        if toco_sl:
            return dict(estado_calc="DESACIERTO (SL)", precio_ref=sl, fecha_ref=ts.date(),
                        hora_ref=ts.strftime("%H:%M:%S") if es_intradia else None, es_final=True)
        if toco_tp:
            return dict(estado_calc="ACIERTO (TP)", precio_ref=tp, fecha_ref=ts.date(),
                        hora_ref=ts.strftime("%H:%M:%S") if es_intradia else None, es_final=True)

    ultimo_precio, _ts = _precio_en_vivo(ticker)
    if ultimo_precio is None:
        ultimo_precio = entrada
    return dict(estado_calc="ABIERTA", precio_ref=ultimo_precio, fecha_ref=None,
                hora_ref=None, es_final=False)


def _sincronizar_estados(supabase, senales):
    """Activa órdenes pendientes y cierra señales abiertas que tocaron TP/SL."""
    actualizadas = False
    for s in senales:
        estado_s = s.get("estado")

        if estado_s == "PENDIENTE":
            entradas_act, todas, f_act, h_act = _evaluar_pendiente(s)
            entradas_fmt = _entradas_a_formato_guardado(entradas_act)
            if todas:
                es_largo_s = "LARGO" in str(s.get("tipo", "")).upper()
                res_final = _resumen_posicion(entradas_fmt, es_largo_s)
                supabase.table(TABLA_SENALES).update({
                    "entradas": entradas_fmt,
                    "estado": "ABIERTA",
                    "fecha_activacion": f_act,
                    "hora_activacion": h_act,
                    "precio_entrada": (res_final["precio_promedio"] if res_final
                                       else s.get("precio_entrada")),
                    "apalancamiento": (res_final["apalancamiento_apertura"] if res_final
                                       else s.get("apalancamiento")),
                }).eq("id", s["id"]).execute()
                actualizadas = True
            elif any(e.get("activada") for e in entradas_act):
                supabase.table(TABLA_SENALES).update(
                    {"entradas": entradas_fmt}).eq("id", s["id"]).execute()
                actualizadas = True
            continue

        if estado_s != "ABIERTA":
            continue
        ev = _evaluar_senal(s)
        if ev["es_final"] and ev["estado_calc"] != "ABIERTA":
            _actualizar_estado_senal(supabase, s["id"], ev["estado_calc"],
                                      ev["precio_ref"], ev["fecha_ref"],
                                      hora_cierre=ev.get("hora_ref") or datetime.now().strftime("%H:%M:%S"))
            actualizadas = True
    if actualizadas:
        _obtener_senales.clear()
    return actualizadas


# ==============================================================
#  CÁLCULO DE RETORNO / P&L
# ==============================================================

def _calcular_retorno(senal, precio_salida):
    entrada = float(senal["precio_entrada"])
    apalancamiento = _apalancamiento_apertura_de_senal(senal)
    es_largo = "LARGO" in senal["tipo"].upper()
    if entrada == 0:
        return 0.0, 0.0
    ret_precio = (precio_salida - entrada) / entrada
    if not es_largo:
        ret_precio = -ret_precio
    ret_apalancado = ret_precio * apalancamiento
    return ret_precio * 100, ret_apalancado * 100


def _calcular_pnl_lotes(senal, precio_salida, unidades):
    entrada = float(senal["precio_entrada"])
    apalancamiento = _apalancamiento_apertura_de_senal(senal)
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
    entrada = float(senal.get("precio_entrada") or 0)
    sl = float(senal.get("stop_loss") or 0)
    apalancamiento = _apalancamiento_apertura_de_senal(senal)
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
# ==============================================================

def _tab_publicar(supabase, user_id, user_email, es_admin):
    if not es_admin:
        st.info("🔒 Solo el administrador puede publicar señales de trading. "
                "Podés ver las señales y simular resultados en las otras pestañas.")
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

    es_pendiente_pub = st.checkbox(
        "🕓 Dejar como orden pendiente (se activa sola cuando el precio toque la entrada)",
        key="sen_es_pendiente",
        help="La señal queda PENDIENTE y no evalúa TP/SL hasta que TODAS las entradas se "
             "activen. Ahí pasa sola a ABIERTA y el TP/SL se evalúa desde esa activación.")

    st.divider()
    entradas_form = _render_entradas_form(es_largo_pub, es_pendiente_pub)
    entradas_guardar = _entradas_para_guardar(entradas_form, es_pendiente_pub)
    resumen_pub = _resumen_posicion(entradas_guardar, es_largo_pub)
    precio_entrada_pos = resumen_pub["precio_promedio"] if resumen_pub else 0.0
    apal_apertura_pub = resumen_pub["apalancamiento_apertura"] if resumen_pub else 1.0

    st.divider()
    p2, p3 = st.columns(2)
    with p2:
        stop_loss = st.number_input("🛑 Stop Loss", min_value=0.0, format="%.5f", key="sen_sl")
    with p3:
        take_profit = st.number_input("🎯 Take Profit", min_value=0.0, format="%.5f", key="sen_tp")

    notas = st.text_area("💬 Notas / justificación", key="sen_notas", height=80,
                          placeholder="Motivo de la señal, contexto técnico o fundamental...")

    if precio_entrada_pos > 0 and stop_loss > 0 and take_profit > 0:
        ok_niveles = (stop_loss < precio_entrada_pos < take_profit) if es_largo_pub \
            else (take_profit < precio_entrada_pos < stop_loss)
        if not ok_niveles:
            st.warning("⚠️ Revisá los niveles: para LARGO, SL < Entrada < TP. Para CORTO, TP < Entrada < SL. "
                       "(Se valida contra el precio promedio de las entradas.)")

    if resumen_pub and _sl_mas_alla_de_liquidacion(resumen_pub, es_largo_pub, stop_loss):
        st.error(_md_dolar(
            f"🚨 Tu Stop Loss ({fmt_precio_exacto(stop_loss)}) queda más allá del precio de "
            f"liquidación ({fmt_precio_exacto(resumen_pub['precio_liquidacion'])}): con el margen y "
            "apalancamiento cargados te liquidarían antes de que el SL se ejecute."))

    riesgo_conservador = PERFILES_RIESGO["conservador"]["default_pct"]
    riesgo_moderado = PERFILES_RIESGO["moderado"]["default_pct"]
    riesgo_agresivo = PERFILES_RIESGO["agresivo"]["default_pct"]

    label_btn_pub = "🕓 Dejar orden pendiente" if es_pendiente_pub else "📢 Publicar señal"
    if st.button(label_btn_pub, type="primary", key="sen_btn_publicar"):
        if not ticker or not resumen_pub or stop_loss <= 0 or take_profit <= 0:
            st.warning("⚠️ Completá ticker, al menos una entrada con precio y margen válidos, "
                       "stop loss y take profit.")
        else:
            datos = dict(ticker=ticker, categoria=categoria, tipo=tipo, fecha=fecha, hora=hora,
                         precio_entrada=precio_entrada_pos, entradas=entradas_guardar,
                         stop_loss=stop_loss, take_profit=take_profit,
                         apalancamiento=apal_apertura_pub, notas=notas,
                         riesgo_conservador=riesgo_conservador, riesgo_moderado=riesgo_moderado,
                         riesgo_agresivo=riesgo_agresivo,
                         estado="PENDIENTE" if es_pendiente_pub else "ABIERTA")
            try:
                _guardar_senal(supabase, datos, user_id, user_email)
                _obtener_senales.clear()
                if es_pendiente_pub:
                    st.success("✅ Orden pendiente creada. Se activará sola en cuanto el precio "
                               "toque cada entrada.")
                else:
                    st.success("✅ Señal publicada.")
                for k in ["sen_ticker", "sen_notas"]:
                    st.session_state.pop(k, None)
                _reset_entradas_state()
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error al publicar: {e}")

    # ----------------------------------------------------------
    #  Gestionar señales publicadas (el admin ve TODAS, sin límite)
    # ----------------------------------------------------------
    st.divider()
    st.markdown("#### 🗂️ Gestionar señales publicadas")
    st.caption("Eliminá cualquier señal —pendiente, abierta o cerrada— desde acá.")

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
            v4.metric("Apalancamiento", fmt_apal(_apalancamiento_apertura_de_senal(row.to_dict())))

            if estado_row == "PENDIENTE":
                n_act = sum(1 for e in entradas_lista if e.get("activada"))
                st.caption(f"🕓 Orden pendiente — {n_act}/{len(entradas_lista)} entradas activadas.")

            if len(entradas_lista) > 1:
                st.caption(_md_dolar(f"🧩 {len(entradas_lista)} entradas → {_texto_entradas(entradas_lista)}"))

            es_largo_row = "LARGO" in str(row.get("tipo", "")).upper()
            res_row = _resumen_de_senal(row.to_dict())
            if res_row:
                _render_resumen_posicion(res_row, es_largo_row,
                                          stop_loss=float(row.get("stop_loss") or 0))

            if row.get("precio_cierre") is not None:
                hora_cierre_txt = row.get("hora_cierre")
                st.caption(_md_dolar(
                    f"Cerrada el {row.get('fecha_cierre','')}"
                    + (f" a las {hora_cierre_txt}" if hora_cierre_txt else "")
                    + f" a {fmt_precio_local(row.get('precio_cierre'))}"
                ))
            if row.get("notas"):
                st.markdown(f"**Notas:** {row['notas']}")

            if estado_row == "ABIERTA":
                st.divider()
                with st.expander("➕ Agregar otra entrada a esta posición (promediar / alejar liquidación)"):
                    st.caption(
                        "Sumá una entrada nueva a esta posición ABIERTA. Se recalcula el precio "
                        "promedio y el apalancamiento de apertura de toda la posición."
                    )
                    ae1, ae2, ae3, ae4, ae5 = st.columns(5)
                    with ae1:
                        nueva_precio = st.number_input(
                            "Precio", min_value=0.0, format="%.5f", key=f"sen_add_precio_{row['id']}")
                    with ae2:
                        nueva_costo = st.number_input(
                            "Costo apertura (USD)", min_value=0.0, step=0.01, format="%.4f",
                            key=f"sen_add_costo_{row['id']}")
                    with ae3:
                        nueva_apal = st.number_input(
                            "Apalanc. (x)", min_value=1.0, max_value=125.0, step=1.0, format="%.1f",
                            value=1.0, key=f"sen_add_apal_{row['id']}")
                    with ae4:
                        nueva_margen = st.number_input(
                            "Margen apertura (USD)", min_value=0.0, step=10.0, format="%.2f",
                            key=f"sen_add_margen_{row['id']}")
                    with ae5:
                        nueva_margen_extra = st.number_input(
                            "Margen extra (USD)", min_value=0.0, step=10.0, format="%.2f",
                            key=f"sen_add_margen_extra_{row['id']}")

                    if st.button("➕ Agregar entrada a la posición", key=f"sen_add_btn_{row['id']}"):
                        if nueva_precio <= 0 or nueva_margen <= 0:
                            st.warning("⚠️ Completá al menos precio y margen de apertura de la nueva entrada.")
                        else:
                            entradas_actuales_fmt = _entradas_a_formato_guardado(entradas_lista)
                            entradas_nuevas = entradas_actuales_fmt + [{
                                "precio": nueva_precio, "costo_apertura": nueva_costo,
                                "apalancamiento": nueva_apal, "margen": nueva_margen,
                                "margen_extra": nueva_margen_extra,
                                "activada": True, "fecha_activacion": None, "hora_activacion": None,
                            }]
                            resumen_nuevo = _resumen_posicion(entradas_nuevas, es_largo_row)
                            if resumen_nuevo is None:
                                st.error("❌ No se pudo calcular la posición con esta entrada.")
                            else:
                                _agregar_entrada_senal(
                                    supabase, row["id"], entradas_nuevas,
                                    resumen_nuevo["precio_promedio"],
                                    resumen_nuevo["apalancamiento_apertura"])
                                _obtener_senales.clear()
                                st.success("✅ Entrada agregada. Se recalculó el precio promedio "
                                          "y el apalancamiento de apertura.")
                                st.rerun()

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

            if estado_row == "PENDIENTE":
                st.caption("🔧 Esta orden todavía no se puede cerrar ni ampliar manualmente: "
                           "esperá a que se active sola, o eliminala si ya no la querés.")

            st.divider()
            confirmar = st.checkbox("Confirmar eliminación", key=f"sen_admin_confirm_del_{row['id']}")
            if st.button("🗑️ Eliminar señal", key=f"sen_admin_btn_del_{row['id']}",
                         disabled=not confirmar):
                _borrar_senal(supabase, row["id"])
                _obtener_senales.clear()
                st.success("Señal eliminada.")
                st.rerun()


# ==============================================================
#  HELPERS DE RÉPLICA (usados en Señales y Resultados)
# ==============================================================

REPLICA_REF_PRIMERA = "Margen de la 1ª entrada (apertura + extra)"
REPLICA_REF_TOTAL = "Margen total de la posición"
MODO_REPLICA = "🔁 Replicar la posición del publicador (escalada a tu margen)"


def _factor_replica(res, entradas, base_usuario, referencia):
    if referencia == REPLICA_REF_PRIMERA:
        primera = entradas[0]
        ref = primera["margen"] + float(primera.get("margen_extra") or 0.0)
    else:
        ref = res["margen_total"]
    return (base_usuario / ref) if ref and ref > 0 else 0.0


def _filas_detalle_replica(s, entradas, factor):
    filas = []
    for i, e in enumerate(entradas):
        margen = e["margen"] * factor
        margen_extra = float(e.get("margen_extra") or 0.0) * factor
        nominal = margen * e["apalancamiento"]
        filas.append({
            "Fecha": s.get("fecha"), "Ticker": s.get("ticker"), "Entrada": i + 1,
            "Precio": fmt_precio_exacto(e["precio"]),
            "Apalanc.": fmt_apal(e["apalancamiento"]),
            "Tu margen apertura (USD)": round(margen, 2),
            "Tu margen extra (USD)": round(margen_extra, 2),
            "Tu costo de apertura (USD)": round(e["costo_apertura"] * factor, 4),
            "Tamaño nominal (USD)": round(nominal, 2),
            "Unidades": round(nominal / e["precio"], 6),
        })
    return filas


# ==============================================================
#  RENDER — TAB SEÑALES Y RESULTADOS (todos ven, con límite por plan)
# ==============================================================

def _tab_senales(supabase, es_admin, es_pro=True):
    st_autorefresh(interval=5 * 60 * 1000, key="sen_autorefresh_pnl_vivo")

    top1, top2 = st.columns([3, 1])
    with top1:
        st.caption("Historial de señales publicadas y órdenes pendientes, con evaluación "
                   "automática de resultado y P&L en vivo (se actualiza cada 5 min) para las "
                   "que siguen abiertas.")
    with top2:
        if st.button("↺ Actualizar y evaluar", use_container_width=True, key="sen_refresh"):
            _obtener_senales.clear()
            _historial_desde_fecha.clear()
            _historial_intradia_desde.clear()
            _precio_en_vivo.clear()
            st.rerun()

    senales_todas = _obtener_senales(supabase, 200)
    if not senales_todas:
        st.info("Todavía no hay señales publicadas.")
        return

    senales, ocultas = _filtrar_senales_por_plan(senales_todas, es_pro)
    if not es_pro:
        _banner_plan_basico(ocultas)
    if not senales:
        st.info("No hay señales disponibles en tu plan por ahora.")
        return

    with st.spinner("Evaluando señales pendientes y abiertas contra el precio de mercado..."):
        _sincronizar_estados(supabase, senales)
        senales, _ = _filtrar_senales_por_plan(_obtener_senales(supabase, 200), es_pro)

    df = pd.DataFrame(senales)
    if "categoria" not in df.columns:
        df["categoria"] = "🔹 Otro"
    df["categoria"] = df["categoria"].fillna("🔹 Otro")

    n_pendientes = int((df["estado"] == "PENDIENTE").sum())
    n_abiertas = int((df["estado"] == "ABIERTA").sum())
    n_acierto = int((df["estado"] == "ACIERTO (TP)").sum())
    n_desacierto = int((df["estado"] == "DESACIERTO (SL)").sum())

    df_manual = df[df["estado"] == "CERRADA MANUAL"]
    n_manual_ganadora = 0
    n_manual_perdedora = 0
    for _, row_m in df_manual.iterrows():
        gano = _cierre_manual_fue_ganador(row_m.to_dict())
        if gano is True:
            n_manual_ganadora += 1
        elif gano is False:
            n_manual_perdedora += 1

    n_acierto_total = n_acierto + n_manual_ganadora
    n_desacierto_total = n_desacierto + n_manual_perdedora
    n_cerradas_total = n_acierto_total + n_desacierto_total
    winrate = (n_acierto_total / n_cerradas_total * 100) if n_cerradas_total > 0 else 0.0

    df_abiertas_kpi = df[df["estado"] == "ABIERTA"]
    n_ganando_vivo = 0
    n_perdiendo_vivo = 0
    if not df_abiertas_kpi.empty:
        with st.spinner("Consultando precios en vivo..."):
            for _, row_ab in df_abiertas_kpi.iterrows():
                precio_vivo_kpi, _ts_kpi = _precio_en_vivo(row_ab.get("ticker"))
                pnl_vivo_kpi = _pnl_vivo_senal(row_ab.to_dict(), precio_vivo_kpi)
                if pnl_vivo_kpi:
                    if pnl_vivo_kpi["ganando"]:
                        n_ganando_vivo += 1
                    else:
                        n_perdiendo_vivo += 1

    k0, k1, k2, k3, k4, k5, k6 = st.columns(7)
    with k0: st.metric("🕓 Pendientes", n_pendientes)
    with k1: st.metric("🔵 Abiertas", n_abiertas)
    with k2: st.metric("✅ Aciertos (TP)", n_acierto_total,
                        f"{n_acierto} por TP + {n_manual_ganadora} manuales" if n_manual_ganadora else None)
    with k3: st.metric("❌ Desaciertos (SL)", n_desacierto_total,
                        f"{n_desacierto} por SL + {n_manual_perdedora} manuales" if n_manual_perdedora else None)
    with k4: st.metric("🎯 Win Rate", f"{winrate:.1f}%" if n_cerradas_total > 0 else "—")
    with k5: st.metric("🟢 Ganando ahora", n_ganando_vivo, "en vivo · cada 5 min")
    with k6: st.metric("🔴 Perdiendo ahora", n_perdiendo_vivo, "en vivo · cada 5 min")

    st.divider()

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

        if estado != "PENDIENTE":
            precio_ref = row.get("precio_cierre") if row.get("precio_cierre") is not None else None
            if precio_ref is None:
                ev = _evaluar_senal(row.to_dict())
                precio_ref = ev["precio_ref"]
            ret_precio, ret_apalancado = _calcular_retorno(row.to_dict(), precio_ref) if precio_ref else (0, 0)
        else:
            precio_ref = None
            ret_precio = ret_apalancado = 0

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

            if estado == "CERRADA MANUAL":
                gano_manual = _cierre_manual_fue_ganador(row.to_dict())
                if gano_manual is True:
                    st.caption("✅ Este cierre manual se contabiliza como **acierto** en el Win "
                               "Rate (cerró con ganancia).")
                elif gano_manual is False:
                    st.caption("❌ Este cierre manual se contabiliza como **desacierto** en el "
                               "Win Rate (cerró con pérdida).")

            if estado == "PENDIENTE":
                entradas_lista = _entradas_de_senal(row.to_dict())
                n_act = sum(1 for e in entradas_lista if e.get("activada"))
                st.info(f"🕓 Orden pendiente — {n_act}/{len(entradas_lista)} entradas activadas. "
                        "Se activa sola en cuanto el precio de mercado toque el precio de cada "
                        "entrada. Mientras está pendiente no cuenta para el Win Rate ni para el "
                        "Simulador de Capital.")
                for i, e in enumerate(entradas_lista):
                    if e.get("activada"):
                        detalle = f" el {e.get('fecha_activacion','')}"
                        if e.get("hora_activacion"):
                            detalle += f" {e['hora_activacion']}"
                        st.caption(f"✅ Entrada {i+1} ({fmt_precio_exacto(e['precio'])}) "
                                   f"activada{detalle}.")
                    else:
                        st.caption(f"⏳ Entrada {i+1} ({fmt_precio_exacto(e['precio'])}) "
                                   "esperando que el precio la toque.")
                v1, v2 = st.columns(2)
                v1.metric("Stop Loss", fmt_precio_local(row.get("stop_loss")))
                v2.metric("Take Profit", fmt_precio_local(row.get("take_profit")))
                es_largo_row = "LARGO" in str(row.get("tipo", "")).upper()
                res_preview = _resumen_de_senal(row.to_dict())
                if res_preview:
                    st.caption("Vista previa de la posición una vez que se activen todas las "
                               "entradas (con el margen y apalancamiento que se cargaron):")
                    _render_resumen_posicion(res_preview, es_largo_row,
                                              stop_loss=float(row.get("stop_loss") or 0))
                if row.get("notas"):
                    st.markdown(f"**Notas:** {row['notas']}")
                continue

            if estado == "ABIERTA":
                precio_vivo_row, ts_vivo_row = _precio_en_vivo(row.get("ticker"))
                pnl_vivo_row = _pnl_vivo_senal(row.to_dict(), precio_vivo_row)
                _render_badge_pnl_vivo(pnl_vivo_row, ts_vivo_row)

            entradas_lista = _entradas_de_senal(row.to_dict())
            v1, v2, v3, v4 = st.columns(4)
            v1.metric("Entrada (prom. ponderado)" if len(entradas_lista) > 1 else "Entrada",
                      fmt_precio_local(row.get("precio_entrada")))
            v2.metric("Stop Loss", fmt_precio_local(row.get("stop_loss")))
            v3.metric("Take Profit", fmt_precio_local(row.get("take_profit")))
            v4.metric("Apalancamiento", fmt_apal(_apalancamiento_apertura_de_senal(row.to_dict())))

            if row.get("fecha_activacion"):
                detalle_act = f"{row.get('fecha_activacion')}"
                if row.get("hora_activacion"):
                    detalle_act += f" {row.get('hora_activacion')}"
                st.caption(f"🕓 Esta posición venía de una orden pendiente: se activó el {detalle_act}. "
                           "El Take Profit / Stop Loss se evalúa desde ese momento en adelante.")

            if len(entradas_lista) > 1:
                st.caption(_md_dolar(f"🧩 {len(entradas_lista)} entradas cargadas → {_texto_entradas(entradas_lista)}"))
                st.caption("El precio de entrada de arriba es el promedio real de la posición "
                           "(ponderado por el tamaño de cada entrada).")

            es_largo_row = "LARGO" in str(row.get("tipo", "")).upper()
            res_row = _resumen_de_senal(row.to_dict())
            if res_row:
                _render_resumen_posicion(res_row, es_largo_row,
                                          stop_loss=float(row.get("stop_loss") or 0))

            v5, v6 = st.columns(2)
            v5.metric("Precio actual / cierre", fmt_precio_local(precio_ref))
            v6.metric("Retorno apalancado", f"{ret_apalancado:+.1f}%",
                      delta=f"{ret_precio:+.2f}% precio", delta_color="off")

            if row.get("precio_cierre") is not None:
                hora_cierre_txt = row.get("hora_cierre")
                st.caption(_md_dolar(
                    f"Cerrada el {row.get('fecha_cierre','')}"
                    + (f" a las {hora_cierre_txt}" if hora_cierre_txt else "")
                    + f" a {fmt_precio_local(row.get('precio_cierre'))}"
                ))

            if row.get("notas"):
                st.markdown(f"**Notas:** {row['notas']}")

            if estado == "ABIERTA" and res_row:
                st.divider()
                st.markdown("##### 🔁 Replicá la posición")
                st.caption(
                    "Poné un solo número (tu margen) y la app copia la posición del publicador "
                    "tal cual: mismas entradas, mismos precios y el mismo apalancamiento en cada "
                    "una. El margen de apertura y el margen extra se escalan en la misma "
                    "proporción, y el precio de liquidación te queda igual."
                )
                base_replica_row = st.number_input(
                    "Tu margen (USD) — margen de la 1ª entrada (apertura + extra)",
                    min_value=0.01, value=10.0, step=1.0, format="%.2f",
                    key=f"sen_hist_replica_base_{row['id']}")

                entradas_replica = _entradas_de_senal(row.to_dict())
                factor_replica_row = _factor_replica(res_row, entradas_replica, base_replica_row,
                                                       REPLICA_REF_PRIMERA)
                if factor_replica_row <= 0:
                    st.caption("Cargá un número mayor a 0 para calcular tu posición.")
                else:
                    rrm1, rrm2, rrm3, rrm4 = st.columns(4)
                    rrm1.metric("Margen de apertura a poner",
                                f"${res_row['margen_apertura'] * factor_replica_row:,.2f}")
                    rrm2.metric("Margen extra a poner",
                                f"${res_row['margen_extra'] * factor_replica_row:,.2f}")
                    rrm3.metric("Margen total a poner",
                                f"${res_row['margen_total'] * factor_replica_row:,.2f}")
                    rrm4.metric("Apalancamiento", fmt_apal(res_row["apalancamiento_apertura"]))

                    if res_row["liquidada_al_abrir"]:
                        st.error("🚨 Con este margen la posición nacería liquidada (los costos "
                                 "de apertura superan el margen total).")
                    elif res_row["sin_liquidacion"]:
                        st.caption("Con este apalancamiento y margen, el activo tendría que "
                                   "llegar a $0 para liquidarte.")
                    else:
                        rrl1, rrl2 = st.columns(2)
                        rrl1.metric("💀 Precio de liquidación",
                                    fmt_precio_exacto(res_row["precio_liquidacion"]))
                        rrl2.metric("Distancia a liquidación",
                                    f"{res_row['dist_liq_pct']:+.2f}%")

                    if _sl_mas_alla_de_liquidacion(res_row, es_largo_row,
                                                    float(row.get("stop_loss") or 0)):
                        st.warning("⚠️ Con este margen, el Stop Loss queda más allá del precio de "
                                   "liquidación: te liquidarían antes de que el SL se ejecute.")

                    detalle_replica_row = _filas_detalle_replica(row.to_dict(), entradas_replica,
                                                                   factor_replica_row)
                    if len(detalle_replica_row) > 1:
                        with st.expander("🔍 Ver el detalle por entrada"):
                            st.dataframe(pd.DataFrame(detalle_replica_row),
                                         use_container_width=True, hide_index=True)


# ==============================================================
#  HELPERS COMPARTIDOS DEL SIMULADOR
# ==============================================================

def _calcular_fila_simulacion(s, precio_ref, capital_total, modo_calculo,
                               monto_por_senal=None, pct_por_senal=None, riesgo_pct=None,
                               unidades_por_lote=None, cantidad_lotes=None,
                               fecha_cierre=None, hora_cierre=None):
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

    else:
        capital_asignado = monto_por_senal if monto_por_senal is not None else capital_total * (pct_por_senal / 100)
        liquidada = ret_apalancado_signal <= -100
        ret_mostrar = max(ret_apalancado_signal, -100)
        pnl_usd = capital_asignado * (ret_mostrar / 100)
        capital_final = capital_asignado + pnl_usd

    fila = {
        "Fecha": s.get("fecha"), "Ticker": s.get("ticker"), "Categoría": cat, "Tipo": s.get("tipo"),
        "Entrada usada (ponderada)": fmt_precio_local(s.get("precio_entrada")),
        "Estado": "💀 LIQUIDADA" if liquidada else estado,
        "Cierre": _texto_cierre(estado, fecha_cierre, hora_cierre),
        "Apalanc.": fmt_apal(_apalancamiento_apertura_de_senal(s)),
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
    if "Margen extra (según tu monto)" in df_sim.columns:
        format_dict["Margen extra (según tu monto)"] = "${:,.2f}"

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

    def _tarjeta_html(row, titulo, emoji):
        val = float(row["P&L (USD)"])
        positivo = val >= 0
        color = "#3fb950" if positivo else "#f85149"
        signo = "+" if positivo else ""
        cierre = row.get("Cierre")
        if cierre and cierre not in ("Sigue abierta", "—"):
            sub_cierre = f" · cierre {cierre}"
        elif cierre == "Sigue abierta":
            sub_cierre = " · sigue abierta"
        else:
            sub_cierre = ""
        return f"""
        <div style="background:#0d1117;border:1px solid #21262d;border-left:3px solid {color};
             border-radius:8px;padding:12px 16px">
          <div style="font-size:11px;color:{color};font-weight:700">{emoji} {titulo}</div>
          <div style="font-size:13px;color:#e6edf3;margin-top:4px">{row['Ticker']} · {row['Fecha']}{sub_cierre}</div>
          <div style="font-size:16px;font-weight:800;color:{color}">{signo}${val:,.2f}</div>
        </div>
        """

    cM, cP = st.columns(2)
    with cM:
        st.markdown(_tarjeta_html(mejor, "MEJOR OPERACIÓN", "🏆"), unsafe_allow_html=True)
    with cP:
        st.markdown(_tarjeta_html(peor, "PEOR OPERACIÓN", "📉"), unsafe_allow_html=True)


# ==============================================================
#  RENDER — TAB SIMULADOR (todos, con límite por plan)
# ==============================================================

def _tab_simulador(supabase, es_pro=True):
    st.caption(
        "Simulá cuánto hubieras ganado o perdido con las señales que elijas, asignándole a cada "
        "una el monto que quieras — siempre con el apalancamiento real con el que se publicó."
    )
    st.caption(
        "🧩 Para señales con varias entradas, acá se usa el precio promedio real de la posición "
        "(ponderado por el tamaño de cada entrada). Las órdenes pendientes (todavía no "
        "activadas) no se incluyen acá."
    )

    senales, ocultas = _filtrar_senales_por_plan(_obtener_senales(supabase, 200), es_pro)
    if not es_pro:
        _banner_plan_basico(ocultas)
    if not senales:
        st.info("Todavía no hay señales para simular en tu plan.")
        return

    with st.spinner("Evaluando señales..."):
        _sincronizar_estados(supabase, senales)
        senales, _ = _filtrar_senales_por_plan(_obtener_senales(supabase, 200), es_pro)

    df_base = pd.DataFrame(senales)
    if "categoria" not in df_base.columns:
        df_base["categoria"] = "🔹 Otro"
    df_base["categoria"] = df_base["categoria"].fillna("🔹 Otro")
    df_base = df_base[df_base["estado"] != "PENDIENTE"]

    incluir_abiertas = st.checkbox("Incluir señales abiertas (P&L flotante)", value=True,
                                    key="sim_incluir_abiertas")
    if not incluir_abiertas:
        df_base = df_base[df_base["estado"] != "ABIERTA"]

    if df_base.empty:
        st.info("No hay señales para incluir en la simulación con estos filtros.")
        return

    st.markdown("#### 🗂️ Elegí las señales a simular")
    opciones_label = {}
    for _, row in df_base.iterrows():
        estado_lbl = row.get("estado", "ABIERTA")
        _col, _bg, _emoji = ESTADO_COLOR.get(estado_lbl, ("#8b949e", "", "⚪"))
        label = (f"{_emoji} {row.get('fecha','')} · {row.get('ticker','')} · "
                 f"{row.get('tipo','')} · {estado_lbl}")
        opciones_label[label] = row["id"]

    labels_todas = list(opciones_label.keys())
    seleccionadas = st.multiselect(
        "Señales a incluir (por defecto, todas)", labels_todas, default=labels_todas,
        key="sim_senales_sel")

    if not seleccionadas:
        st.info("Seleccioná al menos una señal para simular.")
        return

    ids_sel = [opciones_label[l] for l in seleccionadas]
    df_base = df_base[df_base["id"].isin(ids_sel)]

    st.divider()
    modo_monto = st.radio(
        "💵 Monto a simular",
        ["Mismo monto para todas las señales elegidas", "Elegir un monto distinto por señal"],
        horizontal=True, key="sim_modo_monto")

    montos = {}
    if modo_monto == "Mismo monto para todas las señales elegidas":
        monto_fijo = st.number_input("Monto por señal (USD)", min_value=1.0, value=100.0,
                                      step=10.0, key="sim_monto_fijo",
                                      help="Se aplica el mismo monto a todas las señales "
                                           "seleccionadas arriba.")
        for sid in df_base["id"]:
            montos[sid] = monto_fijo
    else:
        st.caption("Cargá el monto que le vas a asignar a cada señal seleccionada:")
        for _, row in df_base.iterrows():
            estado_lbl = row.get("estado", "ABIERTA")
            _col, _bg, _emoji = ESTADO_COLOR.get(estado_lbl, ("#8b949e", "", "⚪"))
            label = f"{_emoji} {row.get('fecha','')} · {row.get('ticker','')} · {row.get('tipo','')}"
            montos[row["id"]] = st.number_input(
                f"Monto (USD) — {label}", min_value=1.0, value=100.0, step=10.0,
                key=f"sim_monto_ind_{row['id']}")

    filas = []
    margen_extra_total_usuario = 0.0
    for _, row in df_base.iterrows():
        s = row.to_dict()
        s = _senal_con_precio_entrada(s, _precio_promedio_ponderado(s))
        precio_ref = s.get("precio_cierre")
        if precio_ref is None:
            ev = _evaluar_senal(s)
            precio_ref = ev["precio_ref"]
        if precio_ref is None:
            continue
        monto_signal = montos.get(row["id"]) or 0.0
        if monto_signal <= 0:
            continue

        res_signal = _resumen_de_senal(s)
        margen_extra_usuario = 0.0
        if res_signal and res_signal.get("margen_apertura", 0) > 0:
            factor_monto = monto_signal / res_signal["margen_apertura"]
            margen_extra_usuario = res_signal["margen_extra"] * factor_monto
        margen_extra_total_usuario += margen_extra_usuario

        fila = _calcular_fila_simulacion(s, precio_ref, monto_signal, "monto_pct",
                                          monto_por_senal=monto_signal,
                                          fecha_cierre=s.get("fecha_cierre"),
                                          hora_cierre=s.get("hora_cierre"))
        if fila:
            fila["Margen extra (según tu monto)"] = round(margen_extra_usuario, 2)
            filas.append(fila)

    if not filas:
        st.info("No se pudo simular ninguna señal (faltan datos de entrada).")
        return

    df_sim = pd.DataFrame(filas)
    st.divider()
    _mostrar_metricas_sim(df_sim, "Capital total usado")
    st.metric("➕ Margen extra agregado (según el monto que pusiste)",
              f"USD {margen_extra_total_usuario:,.2f}")
    st.caption(
        "Si replicaras cada posición con el monto que elegiste —manteniendo la misma proporción "
        "que usó el publicador entre margen de apertura y margen extra— este sería el margen "
        "extra que te correspondería agregar. Es informativo: no afecta el P&L calculado."
    )
    _mostrar_tabla_estilizada(df_sim)
    _mostrar_mejor_peor(df_sim)

    st.caption("⚠️ Simulación educativa. No contempla comisiones, spread, financiamiento por "
               "apalancamiento, swap ni slippage. Cuando TP y SL se tocan en la misma vela se "
               "asume el peor caso (SL). No constituye asesoramiento financiero.")


# ==============================================================
#  ENTRY POINT — llamar desde app.py
# ==============================================================

def render_senales_trading(supabase, user_id, user_email, tiene_acceso_pro=False):
    """Uso desde app.py:
        render_senales_trading(supabase, USER_ID, st.session_state['usuario'].email,
                               tiene_acceso_pro=TIENE_SENALES_PRO)

    tiene_acceso_pro=True  → señales ilimitadas (Pro / Admin).
    tiene_acceso_pro=False → 1 señal por día, lunes a viernes (Básico / Trial).
    El admin siempre tiene acceso total.
    """
    es_admin = _es_admin(user_email)
    es_pro = bool(tiene_acceso_pro) or es_admin

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #bc5cff;
         border-radius:14px; padding:22px 28px; margin-bottom:20px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:4px">
        🎯 Señales de Trading
      </div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.6">
        Señales publicadas con fecha, hora, una o varias entradas, precio de liquidación,
        stop loss y take profit — o cargadas como órdenes pendientes (🕓) que se activan solas
        cuando el precio toca la entrada. Evaluación automática de aciertos/desaciertos, P&L en
        vivo para las abiertas, réplica de la posición a tu margen y simulador de capital.
        Plan Pro: señales ilimitadas · Plan Básico: 1 señal por día (lunes a viernes).
      </div>
    </div>
    """, unsafe_allow_html=True)

    tab_pub, tab_hist, tab_sim = st.tabs([
        "📢 Publicar Señal", "📋 Señales y Resultados", "🧮 Simulador de Capital",
    ])
    with tab_pub:
        _tab_publicar(supabase, user_id, user_email, es_admin)
    with tab_hist:
        _tab_senales(supabase, es_admin, es_pro)
    with tab_sim:
        _tab_simulador(supabase, es_pro)
