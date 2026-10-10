# ==============================================================
#  MÓDULO SEÑALES DE TRADING — Streamlit + Supabase
#  Solo ADMIN_EMAIL publica señales; todos pueden verlas y simular.
#  La protección real está en las políticas RLS de Supabase
#  (ver senales_trading_schema.sql). El email de acá abajo tiene que
#  coincidir EXACTAMENTE con el de esas políticas.
#
#  LÍMITES POR PLAN:
#   - Plan Pro / Admin: señales ilimitadas.
#   - Plan Básico y Trial: ven UNA sola señal, la que el admin marque como
#     "gratuita" (columna visible_basico, solo una a la vez).
#   - app.py decide qué plan es "pro para señales" y lo pasa en
#     render_senales_trading(..., tiene_acceso_pro=...).
#
#  PUBLICAR (solo admin), dos modos:
#   - Manual: cargás ticker, precio(s) de entrada y gestión de salida
#     (Stop Loss Manual / ATR / % Fijo y Take Profit). Sin capital,
#     riesgo ni apalancamiento.
#   - Scanner GEX: cargás una lista de tickers, el módulo scanner_gex.py
#     los escanea y desde ahí cargás el activo en el formulario manual.
#   Requiere scanner_gex.py y modulo_gex.py en la misma carpeta.
#
#  FUNCIONALIDADES:
#   - Varias entradas por señal → precio promedio.
#   - Órdenes pendientes (entrada límite) que se activan solas cuando el
#     precio toca la entrada; TP/SL se evalúa desde la activación.
#   - Evaluación automática de TP/SL con velas horarias + diarias.
#     OJO: como solo el admin puede escribir en la tabla (RLS), la evaluación
#     se GUARDA cuando el admin abre la app. Los demás usuarios la ven
#     calculada en pantalla pero no pueden persistirla.
#   - P&L en vivo (cada 5 min) para señales abiertas.
#   - Simulador de Operación: el usuario elige una señal y simula la
#     operación con su cuenta (plataforma, tipo de operación, capital
#     total, % de riesgo, capital para la operación y apalancamiento).
# ==============================================================

import math

import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, datetime, time as dt_time, timedelta
from streamlit_autorefresh import st_autorefresh
from zoneinfo import ZoneInfo          # en Windows: pip install tzdata

from scanner_gex import render_scanner_gex

# Todas las fechas y horas de las señales se guardan en hora de Argentina,
# sin importar en qué zona horaria esté el servidor.
TZ_AR = ZoneInfo("America/Argentina/Buenos_Aires")


def _ahora_ar():
    return datetime.now(TZ_AR)

ADMIN_EMAIL = "brainferreyra@gmail.com"
TABLA_SENALES = "senales_trading"

MODO_MANUAL = "✍️ Cargar señal manual"
MODO_SCANNER = "🧲 Scanner GEX (lista de activos)"

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

# Valores por defecto que se guardan en las columnas de riesgo (la tabla las espera,
# pero ya no se cargan desde el formulario).
RIESGO_DEFAULT_CONSERVADOR = 1.0
RIESGO_DEFAULT_MODERADO = 2.0
RIESGO_DEFAULT_AGRESIVO = 3.0


def _es_admin(user_email):
    return bool(user_email) and user_email.strip().lower() == ADMIN_EMAIL.strip().lower()


# ==============================================================
#  LÍMITES POR PLAN
# ==============================================================

def _es_gratis(d):
    """True si la señal está marcada como gratuita (visible para Básico/Prueba)."""
    v = d.get("visible_basico")
    return (v is not None) and (not pd.isna(v)) and bool(v)


def _filtrar_senales_por_plan(senales, es_pro):
    """Devuelve (senales_visibles, cantidad_ocultas).
    Pro/Admin: todas. Básico/Prueba: solo la señal marcada como gratuita."""
    if es_pro or not senales:
        return senales, 0
    visibles = [s for s in senales if _es_gratis(s)][:1]
    return visibles, len(senales) - len(visibles)


def _banner_plan_basico(ocultas):
    if ocultas:
        msg = (f"🔒 **Plan Básico / Prueba**: ves 1 señal destacada. "
               f"Hay **{ocultas}** señal(es) más que solo ve el plan Pro, que tiene señales ilimitadas.")
    else:
        msg = ("🔒 **Plan Básico / Prueba**: ves 1 señal destacada. "
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


def _h(texto):
    """Escapa '$' dentro de bloques HTML para que Streamlit no los lea como LaTeX."""
    return str(texto).replace("$", "&#36;")


def _set_state(clave, valor):
    """Callback para botones: pisa el valor de un input antes del próximo rerun."""
    st.session_state[clave] = valor


# ==============================================================
#  ENTRADAS MÚLTIPLES — helpers
# ==============================================================

def _entradas_de_senal(senal):
    """Lista de entradas normalizada."""
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
                 "margen_extra": 0.0,
                 "activada": default_activada, "fecha_activacion": None,
                 "hora_activacion": None}]
    return []


def _promedio_de_entradas(entradas):
    """Precio promedio de una lista de entradas.
    Señales viejas (con margen y apalancamiento): promedio ponderado por tamaño.
    Señales nuevas (sin margen): promedio simple de los precios."""
    validas = [e for e in entradas if float(e.get("precio") or 0) > 0]
    if not validas:
        return 0.0
    if all(float(e.get("margen") or 0) > 0 and float(e.get("apalancamiento") or 0) > 0
           for e in validas):
        nominal = sum(e["margen"] * e["apalancamiento"] for e in validas)
        unidades = sum(e["margen"] * e["apalancamiento"] / e["precio"] for e in validas)
        if unidades > 0:
            return nominal / unidades
    return sum(float(e["precio"]) for e in validas) / len(validas)


def _precio_promedio_ponderado(senal):
    entradas = _entradas_de_senal(senal)
    if not entradas:
        return float(senal.get("precio_entrada") or 0)
    return _promedio_de_entradas(entradas)


def _apalancamiento_de_senal(senal):
    """Las señales nuevas se guardan con 1x; las viejas conservan su apalancamiento."""
    try:
        return float(senal.get("apalancamiento") or 1.0) or 1.0
    except (TypeError, ValueError):
        return 1.0


def _texto_entradas(entradas):
    return " | ".join(f"Entrada {i + 1}: {fmt_precio_exacto(e['precio'])}"
                      for i, e in enumerate(entradas))


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


def _ratio_rb_de_senal(senal):
    """Riesgo/Beneficio = distancia al TP / distancia al SL, medidas desde el precio promedio.
    Devuelve None si los niveles no permiten calcularlo."""
    try:
        prom = _precio_promedio_ponderado(senal)
        sl = float(senal.get("stop_loss") or 0)
        tp = float(senal.get("take_profit") or 0)
    except (TypeError, ValueError):
        return None
    if prom <= 0 or sl <= 0 or tp <= 0:
        return None
    riesgo = abs(prom - sl)
    beneficio = abs(tp - prom)
    if riesgo <= 0 or beneficio <= 0:
        return None
    return beneficio / riesgo


def _render_niveles(senal, entradas_lista):
    """Entrada, Stop Loss, Take Profit, Riesgo/Beneficio y (si hay más de una entrada) Precio promedio."""
    multiples = len(entradas_lista) > 1
    cols = st.columns(5 if multiples else 4)
    if entradas_lista:
        precio_primera = entradas_lista[0]["precio"]
    else:
        precio_primera = senal.get("precio_entrada")
    cols[0].metric("Primera entrada" if multiples else "Entrada", fmt_precio_exacto(precio_primera))
    cols[1].metric("Stop Loss", fmt_precio_exacto(senal.get("stop_loss")))
    cols[2].metric("Take Profit", fmt_precio_exacto(senal.get("take_profit")))
    rr = _ratio_rb_de_senal(senal)
    cols[3].metric("Riesgo / Beneficio", f"1:{rr:.1f}" if rr is not None else "—",
                   help="Cuánto buscás ganar por cada $1 que arriesgás (medido desde el precio promedio).")
    if multiples:
        cols[4].metric("Precio promedio", fmt_precio_exacto(_precio_promedio_ponderado(senal)))
        st.caption(_md_dolar(f"🧩 {len(entradas_lista)} entradas → {_texto_entradas(entradas_lista)}"))


# ----------------------------------------------------------------
#  Helpers de stop
# ----------------------------------------------------------------

def sugerir_stop_atr(precio_entrada, atr, direccion='long', multiplo=1.5):
    if not atr or atr <= 0 or not precio_entrada:
        return None
    if direccion == 'long':
        return precio_entrada - multiplo * atr
    return precio_entrada + multiplo * atr


def sugerir_stop_pct(precio_entrada, pct, direccion='long'):
    if not precio_entrada or precio_entrada <= 0 or not pct or pct <= 0:
        return None
    if direccion == 'long':
        return precio_entrada * (1 - pct / 100)
    return precio_entrada * (1 + pct / 100)


@st.cache_data(ttl=900, show_spinner=False)
def _atr_y_precio_actual(ticker, periodo=14):
    """(ATR diario de 14 períodos, último precio). (None, None) si no hay datos."""
    try:
        import yfinance as yf
        df = yf.download(ticker, period="6mo", interval="1d", auto_adjust=True, progress=False)
        if df is None or df.empty:
            return None, None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Close"])
        if df.empty:
            return None, None
        precio = float(df["Close"].iloc[-1])
        atr = None
        if {"High", "Low"}.issubset(df.columns) and len(df) > periodo:
            c = df["Close"]
            tr = pd.concat([df["High"] - df["Low"],
                            (df["High"] - c.shift(1)).abs(),
                            (df["Low"] - c.shift(1)).abs()], axis=1).max(axis=1)
            serie = tr.rolling(periodo).mean().dropna()
            if len(serie) > 0:
                atr = float(serie.iloc[-1])
        return atr, precio
    except Exception:
        return None, None


# ----------------------------------------------------------------
#  Formulario dinámico de entradas (solo precio)
# ----------------------------------------------------------------

def _entrada_vacia(_id):
    return {"id": _id, "precio": 0.0}


def _limpiar_keys_entrada(ent):
    st.session_state.pop(f"sen_entrada_precio_{ent['id']}", None)


def _init_entradas_state():
    if "sen_entradas" not in st.session_state:
        st.session_state["sen_entradas"] = [_entrada_vacia(0)]
        st.session_state["sen_entrada_next_id"] = 1


def _reset_entradas_state():
    for e in st.session_state.get("sen_entradas", []):
        _limpiar_keys_entrada(e)
    st.session_state["sen_entradas"] = [_entrada_vacia(0)]
    st.session_state["sen_entrada_next_id"] = 1


def _entradas_para_guardar(precios, es_pendiente=False):
    """Arma las entradas en el formato que guarda el módulo (sin margen ni costos)."""
    return [
        {"precio": float(p), "costo_apertura": 0.0,
         "apalancamiento": 1.0, "margen": 0.0, "margen_extra": 0.0,
         "activada": not es_pendiente,
         "fecha_activacion": None, "hora_activacion": None}
        for p in precios
    ]


def _render_entradas_form(es_pendiente=False, precio_actual=None):
    """Devuelve la lista de precios de entrada cargados (> 0)."""
    _init_entradas_state()
    entradas = st.session_state["sen_entradas"]

    if es_pendiente:
        st.caption("Como marcaste **orden pendiente**, cada precio es un precio OBJETIVO (entrada "
                   "límite): la posición todavía no está abierta y se activa sola cuando el precio lo toque.")
    else:
        st.caption("Cargá una entrada por cada compra/venta si vas a promediar.")

    a_borrar = None
    for i, ent in enumerate(entradas):
        ce1, ce2 = st.columns([5, 1])
        with ce1:
            ent["precio"] = st.number_input(
                f"Precio — Entrada {i + 1}", min_value=0.0, format="%.5f",
                value=float(ent.get("precio", 0.0)), key=f"sen_entrada_precio_{ent['id']}")
        with ce2:
            st.write("")
            st.write("")
            if len(entradas) > 1 and st.button("🗑️", key=f"sen_entrada_del_{ent['id']}",
                                                help="Quitar esta entrada"):
                a_borrar = i

    if a_borrar is not None:
        eliminado = entradas.pop(a_borrar)
        _limpiar_keys_entrada(eliminado)
        st.rerun()

    if precio_actual:
        st.button(f"📍 Usar precio actual en la 1ª entrada ({fmt_precio_exacto(precio_actual)})",
                  key="sen_btn_px", on_click=_set_state,
                  args=(f"sen_entrada_precio_{entradas[0]['id']}", round(float(precio_actual), 5)))

    if st.button("➕ Agregar otra entrada", key="sen_entrada_add"):
        nuevo_id = st.session_state["sen_entrada_next_id"]
        entradas.append(_entrada_vacia(nuevo_id))
        st.session_state["sen_entrada_next_id"] += 1
        st.rerun()

    return [float(e["precio"]) for e in entradas if e["precio"] > 0]


def _validar_niveles_pub(precios, stop_loss, take_profit, es_largo):
    """Valida entradas / SL / TP y muestra un resumen simple.
    Devuelve el precio promedio de las entradas (0.0 si todavía no se puede calcular)."""
    faltan = []
    if not precios:
        faltan.append("al menos un precio de entrada")
    if stop_loss <= 0:
        faltan.append("el Stop Loss")
    if faltan:
        st.info("Cargá " + " y ".join(faltan) + " para ver el resumen.")
        return 0.0

    if es_largo and any(p <= stop_loss for p in precios):
        st.error("En una señal LARGO el Stop Loss debe estar por DEBAJO de todas las entradas.")
        return 0.0
    if (not es_largo) and any(p >= stop_loss for p in precios):
        st.error("En una señal CORTO el Stop Loss debe estar por ENCIMA de todas las entradas.")
        return 0.0

    dist_max = max(abs(p - stop_loss) / p * 100 for p in precios)
    if dist_max > 85:
        st.error(f"Tu stop está a {dist_max:.1f}% de una entrada. Parece un error de tipeo "
                 "o de decimales; corregilo.")
        return 0.0

    prom = sum(precios) / len(precios)
    dist_sl = abs(prom - stop_loss) / prom * 100

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Precio promedio", fmt_precio_exacto(prom))
    c2.metric("Stop Loss", f"{dist_sl:.2f}%", help="Distancia del stop al precio promedio")

    if take_profit and take_profit > 0:
        tp_ok = (take_profit > prom) if es_largo else (take_profit < prom)
        if not tp_ok:
            st.warning("⚠️ El Take Profit está del lado equivocado de la entrada "
                       "(en LARGO va por encima, en CORTO por debajo).")
        else:
            dist_tp = abs(take_profit - prom) / prom * 100
            c3.metric("Take Profit", f"{dist_tp:.2f}%", help="Distancia del TP al precio promedio")
            rr = dist_tp / dist_sl if dist_sl > 0 else None
            if rr is not None:
                c4.metric("Riesgo / Beneficio", f"1:{rr:.1f}")
                if rr < 1:
                    st.caption("⚠️ Arriesgás más de lo que buscás ganar.")
    return prom


# ==============================================================
#  ACCESO A SUPABASE
# ==============================================================

def _quitar_visible_basico(supabase):
    """Desmarca cualquier señal gratuita (solo puede haber una)."""
    supabase.table(TABLA_SENALES).update({"visible_basico": False}).eq("visible_basico", True).execute()


def _marcar_visible_basico(supabase, senal_id):
    """Hace de esta señal la única gratuita."""
    _quitar_visible_basico(supabase)
    supabase.table(TABLA_SENALES).update({"visible_basico": True}).eq("id", senal_id).execute()


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
        "apalancamiento": datos.get("apalancamiento", 1.0),
        "riesgo_conservador": RIESGO_DEFAULT_CONSERVADOR,
        "riesgo_moderado": RIESGO_DEFAULT_MODERADO,
        "riesgo_agresivo": RIESGO_DEFAULT_AGRESIVO,
        "notas": datos.get("notas", ""),
        "estado": datos.get("estado", "ABIERTA"),
        "visible_basico": bool(datos.get("visible_basico", False)),
        "fecha_activacion": None, "hora_activacion": None,
        "precio_cierre": None, "fecha_cierre": None, "hora_cierre": None,
    }
    if row["visible_basico"]:
        _quitar_visible_basico(supabase)
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
        "fecha_cierre": str(_ahora_ar().date()),
        "hora_cierre": _ahora_ar().strftime("%H:%M:%S"),
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
    Las velas se convierten a hora de Argentina antes de comparar."""
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
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df.index = df.index.tz_convert(TZ_AR).tz_localize(None)
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
    apalancamiento = _apalancamiento_de_senal(senal)
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
    """Activa órdenes pendientes y cierra señales abiertas que tocaron TP/SL.
    Solo debe llamarse como admin: el resto de los usuarios no tiene permiso de
    escritura (RLS), así que sus updates no se guardarían."""
    actualizadas = False
    for s in senales:
        estado_s = s.get("estado")

        if estado_s == "PENDIENTE":
            entradas_act, todas, f_act, h_act = _evaluar_pendiente(s)
            entradas_fmt = _entradas_a_formato_guardado(entradas_act)
            if todas:
                promedio = _promedio_de_entradas(entradas_fmt)
                supabase.table(TABLA_SENALES).update({
                    "entradas": entradas_fmt,
                    "estado": "ABIERTA",
                    "fecha_activacion": f_act,
                    "hora_activacion": h_act,
                    "precio_entrada": promedio if promedio > 0 else s.get("precio_entrada"),
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
                                      hora_cierre=ev.get("hora_ref") or _ahora_ar().strftime("%H:%M:%S"))
            actualizadas = True
    if actualizadas:
        _obtener_senales.clear()
    return actualizadas


# ==============================================================
#  CÁLCULO DE RETORNO
# ==============================================================

def _calcular_retorno(senal, precio_salida):
    entrada = float(senal["precio_entrada"])
    apalancamiento = _apalancamiento_de_senal(senal)
    es_largo = "LARGO" in senal["tipo"].upper()
    if entrada == 0:
        return 0.0, 0.0
    ret_precio = (precio_salida - entrada) / entrada
    if not es_largo:
        ret_precio = -ret_precio
    ret_apalancado = ret_precio * apalancamiento
    return ret_precio * 100, ret_apalancado * 100


# ==============================================================
#  RENDER — TAB PUBLICAR (solo admin)
# ==============================================================

def _cargar_desde_scanner(fila, lado):
    """on_click del scanner: pasa el activo elegido al formulario manual."""
    es_largo = (lado == "LARGO")
    st.session_state["sen_modo_pub"] = MODO_MANUAL
    st.session_state["sen_ticker"] = fila["ticker_yahoo"]
    if fila.get("categoria") in CATEGORIAS:
        st.session_state["sen_categoria"] = fila["categoria"]
    st.session_state["sen_tipo"] = "🟢 LARGO (Compra)" if es_largo else "🔴 CORTO (Venta)"
    st.session_state["sen_modo_stop"] = "Manual"   # el SL del scanner se carga a mano

    sup, inf = fila.get("nivel_sup"), fila.get("nivel_inf")
    sup = float(sup) if sup is not None and not pd.isna(sup) else 0.0
    inf = float(inf) if inf is not None and not pd.isna(inf) else 0.0
    st.session_state["sen_sl"] = inf if es_largo else sup
    st.session_state["sen_tp"] = sup if es_largo else inf

    # Precio de la 1ª entrada = precio actual
    _init_entradas_state()
    ent0 = st.session_state["sen_entradas"][0]
    ent0["precio"] = float(fila["precio"])
    st.session_state[f"sen_entrada_precio_{ent0['id']}"] = float(fila["precio"])

    flip = fila.get("flip")
    st.session_state["sen_notas"] = (
        f"Gamma {fila['regimen']}"
        + (f" · punto de cambio {flip:,.2f}" if flip is not None and not pd.isna(flip) else "")
        + (f" · resistencia {sup:,.2f}" if sup else "")
        + (f" · soporte {inf:,.2f}" if inf else "")
        + f" · Squeeze Score {fila['squeeze']:.0f} ({fila['sq_nivel']})."
    )


def _form_publicar_manual(supabase, user_id, user_email):
    st.markdown("#### 📥 Parámetros de la señal")

    with st.container(border=True):
        st.markdown("**① Activo y publicación**")
        c1, c2 = st.columns(2)
        with c1:
            ticker = st.text_input("🎯 Ticker", key="sen_ticker",
                                   placeholder="Ej: NVDA, BTC-USD, EURUSD=X")
        with c2:
            categoria = st.selectbox("🏷️ Categoría del activo", CATEGORIAS, key="sen_categoria")
        tipo = st.selectbox("Tipo de operación", ["🟢 LARGO (Compra)", "🔴 CORTO (Venta)"],
                            key="sen_tipo")
        es_largo_pub = "LARGO" in tipo.upper()
        direccion = "long" if es_largo_pub else "short"

        f1, f2 = st.columns(2)
        with f1:
            fecha = st.date_input("📅 Fecha", value=_ahora_ar().date(), key="sen_fecha")
        with f2:
            hora = st.time_input("🕐 Hora", value=_ahora_ar().time().replace(microsecond=0),
                                 key="sen_hora")

        es_pendiente_pub = st.checkbox(
            "🕓 Dejar como orden pendiente (se activa sola cuando el precio toque la entrada)",
            key="sen_es_pendiente",
            help="La señal queda PENDIENTE y no evalúa TP/SL hasta que TODAS las entradas se "
                 "activen. Ahí pasa sola a ABIERTA y el TP/SL se evalúa desde esa activación.")
        es_gratis_pub = st.checkbox(
            "⭐ Marcar como señal gratuita (la ven los planes Básico y Prueba)",
            key="sen_es_gratis",
            help="Solo puede haber una señal gratuita a la vez: si marcás esta, la anterior deja "
                 "de serlo. Los usuarios Pro ven todas las señales igual.")

    ticker_u = (ticker or "").strip().upper()
    atr_val, px_actual = None, None
    if ticker_u:
        with st.spinner(f"Analizando {ticker_u}..."):
            atr_val, px_actual = _atr_y_precio_actual(ticker_u)

    with st.container(border=True):
        st.markdown("**② Entradas**")
        precios = _render_entradas_form(es_pendiente_pub, px_actual)
    precio_ref_stop = (sum(precios) / len(precios)) if precios else 0.0

    with st.container(border=True):
        st.markdown("**③ Gestión de salida**")
        modo_stop = st.radio("Modo de Stop Loss", ["Manual", "Por ATR / Volatilidad", "% Fijo"],
                             horizontal=True, key="sen_modo_stop")
        stop_loss = 0.0

        if modo_stop == "Manual":
            stop_loss = st.number_input("🛑 Stop Loss", min_value=0.0, format="%.5f", key="sen_sl")

        elif modo_stop == "Por ATR / Volatilidad":
            mult = st.select_slider("Múltiplo de ATR", options=[1.0, 1.5, 2.0, 3.0], value=1.5,
                                    key="sen_mult_atr", format_func=lambda m_: f"{m_:g}× ATR",
                                    help="Cuántas volatilidades diarias normales separan el stop "
                                         "de tu entrada. Más alto = stop más holgado.")
            if not ticker_u:
                st.info("Ingresá un ticker para calcular el ATR.")
            elif not atr_val:
                st.warning("No hay ATR disponible para este activo. Usá el modo Manual o % Fijo.")
            elif precio_ref_stop <= 0:
                st.info("Cargá el precio de entrada para calcular el stop por ATR.")
            else:
                sug = sugerir_stop_atr(precio_ref_stop, atr_val, direccion, mult)
                if sug and sug > 0:
                    stop_loss = round(sug, 5)
                    st.success(_md_dolar(f"🛑 Stop calculado: **${stop_loss:,.5f}** "
                                         f"({mult:g} × ATR de {atr_val:,.5f})"))
                else:
                    st.warning("El stop por ATR quedaría en un precio inválido (≤ 0). "
                               "Probá un múltiplo menor.")

        else:  # % Fijo
            pct_stop = st.radio("Distancia del stop", [2, 3, 5], horizontal=True, key="sen_pct_stop",
                                format_func=lambda p: f"-{p}%" if es_largo_pub else f"+{p}%")
            if precio_ref_stop <= 0:
                st.info("Cargá el precio de entrada para calcular el stop.")
            else:
                stop_loss = round(sugerir_stop_pct(precio_ref_stop, pct_stop, direccion), 5)
                st.success(_md_dolar(
                    f"🛑 Stop calculado: **${stop_loss:,.5f}** ({pct_stop}% "
                    f"{'por debajo' if es_largo_pub else 'por encima'} de la entrada)"))

        take_profit = st.number_input("🎯 Take Profit", min_value=0.0, format="%.5f", key="sen_tp")

    # ── Resumen / validación de niveles ──
    precio_entrada_pos = _validar_niveles_pub(precios, stop_loss, take_profit, es_largo_pub)

    # ══════════════════ NOTAS Y PUBLICAR ══════════════════
    st.divider()
    notas = st.text_area("💬 Notas / justificación", key="sen_notas", height=80,
                         placeholder="Motivo de la señal, contexto técnico o fundamental...")

    if precio_entrada_pos > 0 and stop_loss > 0 and take_profit > 0:
        ok_niveles = (stop_loss < precio_entrada_pos < take_profit) if es_largo_pub \
            else (take_profit < precio_entrada_pos < stop_loss)
        if not ok_niveles:
            st.warning("⚠️ Revisá los niveles: para LARGO, SL < Entrada < TP. Para CORTO, TP < Entrada < SL. "
                       "(Se valida contra el precio promedio de las entradas.)")

    label_btn_pub = "🕓 Dejar orden pendiente" if es_pendiente_pub else "📢 Publicar señal"
    if st.button(label_btn_pub, type="primary", key="sen_btn_publicar"):
        if not ticker or precio_entrada_pos <= 0 or stop_loss <= 0 or take_profit <= 0:
            st.warning("⚠️ Completá ticker, al menos una entrada válida, stop loss y take profit.")
        else:
            datos = dict(ticker=ticker, categoria=categoria, tipo=tipo, fecha=fecha, hora=hora,
                         precio_entrada=precio_entrada_pos,
                         entradas=_entradas_para_guardar(precios, es_pendiente_pub),
                         stop_loss=stop_loss, take_profit=take_profit,
                         apalancamiento=1.0, notas=notas,
                         estado="PENDIENTE" if es_pendiente_pub else "ABIERTA",
                         visible_basico=es_gratis_pub)
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


def _tab_publicar(supabase, user_id, user_email, es_admin):
    if not es_admin:
        st.info("🔒 Solo el administrador puede publicar señales de trading. "
                "Podés ver las señales y simular operaciones en las otras pestañas.")
        return

    modo = st.radio("Cómo querés armar la señal", [MODO_MANUAL, MODO_SCANNER],
                    horizontal=True, key="sen_modo_pub")
    if modo == MODO_SCANNER:
        render_scanner_gex(on_cargar=_cargar_desde_scanner)
    else:
        _form_publicar_manual(supabase, user_id, user_email)

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
                  f"{categoria_row} · {row.get('tipo','')} · {estado_row}"
                  + (" · ⭐ GRATIS" if _es_gratis(row) else ""))
        with st.expander(f"{emoji} {titulo}"):
            senal_row = row.to_dict()
            entradas_lista = _entradas_de_senal(senal_row)
            _render_niveles(senal_row, entradas_lista)

            if estado_row == "PENDIENTE":
                n_act = sum(1 for e in entradas_lista if e.get("activada"))
                st.caption(f"🕓 Orden pendiente — {n_act}/{len(entradas_lista)} entradas activadas.")

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
                with st.expander("➕ Agregar otra entrada a esta posición"):
                    st.caption("Cargá el precio de la nueva entrada. Se recalcula el precio "
                               "promedio de la posición.")
                    nueva_precio = st.number_input(
                        "Precio de la nueva entrada", min_value=0.0, format="%.5f",
                        key=f"sen_add_precio_{row['id']}")

                    if st.button("➕ Agregar entrada", key=f"sen_add_btn_{row['id']}"):
                        if nueva_precio <= 0:
                            st.warning("⚠️ Ingresá el precio de la nueva entrada.")
                        else:
                            entradas_actuales_fmt = _entradas_a_formato_guardado(entradas_lista)
                            margenes_previos = [e["margen"] for e in entradas_actuales_fmt
                                                if e["margen"] > 0]
                            # Señales viejas con margen: la nueva entrada usa el margen promedio.
                            # Señales nuevas (sin margen): queda en 0 y el promedio es simple.
                            margen_nuevo = (sum(margenes_previos) / len(margenes_previos)
                                            if len(margenes_previos) == len(entradas_actuales_fmt)
                                            else 0.0)
                            apal_nueva = _apalancamiento_de_senal(senal_row)
                            entradas_nuevas = entradas_actuales_fmt + [{
                                "precio": float(nueva_precio), "costo_apertura": 0.0,
                                "apalancamiento": apal_nueva, "margen": margen_nuevo,
                                "margen_extra": 0.0,
                                "activada": True, "fecha_activacion": None,
                                "hora_activacion": None,
                            }]
                            promedio_nuevo = _promedio_de_entradas(entradas_nuevas)
                            _agregar_entrada_senal(supabase, row["id"], entradas_nuevas,
                                                   promedio_nuevo, apal_nueva)
                            _obtener_senales.clear()
                            st.success("✅ Entrada agregada. Se recalculó el precio promedio.")
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
            if _es_gratis(row):
                st.success("⭐ Esta es la señal gratuita: la ven los planes Básico y Prueba.")
                if st.button("Quitar como señal gratuita", key=f"sen_admin_quitar_gratis_{row['id']}"):
                    _quitar_visible_basico(supabase)
                    _obtener_senales.clear()
                    st.rerun()
            else:
                if st.button("⭐ Hacer esta la señal gratuita", key=f"sen_admin_hacer_gratis_{row['id']}"):
                    _marcar_visible_basico(supabase, row["id"])
                    _obtener_senales.clear()
                    st.rerun()

            st.divider()
            confirmar = st.checkbox("Confirmar eliminación", key=f"sen_admin_confirm_del_{row['id']}")
            if st.button("🗑️ Eliminar señal", key=f"sen_admin_btn_del_{row['id']}",
                         disabled=not confirmar):
                _borrar_senal(supabase, row["id"])
                _obtener_senales.clear()
                st.success("Señal eliminada.")
                st.rerun()


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
        if es_admin:                       # solo el admin puede escribir (RLS)
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
        senal_row = row.to_dict()

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
                gano_manual = _cierre_manual_fue_ganador(senal_row)
                if gano_manual is True:
                    st.caption("✅ Este cierre manual se contabiliza como **acierto** en el Win "
                               "Rate (cerró con ganancia).")
                elif gano_manual is False:
                    st.caption("❌ Este cierre manual se contabiliza como **desacierto** en el "
                               "Win Rate (cerró con pérdida).")

            entradas_lista = _entradas_de_senal(senal_row)

            if estado == "PENDIENTE":
                n_act = sum(1 for e in entradas_lista if e.get("activada"))
                st.info(f"🕓 Orden pendiente — {n_act}/{len(entradas_lista)} entradas activadas. "
                        "Se activa sola en cuanto el precio de mercado toque el precio de cada "
                        "entrada. Mientras está pendiente no cuenta para el Win Rate.")
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
                _render_niveles(senal_row, entradas_lista)
                if row.get("notas"):
                    st.markdown(f"**Notas:** {row['notas']}")
                continue

            if estado == "ABIERTA":
                precio_vivo_row, ts_vivo_row = _precio_en_vivo(row.get("ticker"))
                pnl_vivo_row = _pnl_vivo_senal(senal_row, precio_vivo_row)
                _render_badge_pnl_vivo(pnl_vivo_row, ts_vivo_row)

            # Entrada, Stop Loss, Take Profit, R/B y Precio promedio (si hay más de una entrada)
            _render_niveles(senal_row, entradas_lista)

            if row.get("fecha_activacion"):
                detalle_act = f"{row.get('fecha_activacion')}"
                if row.get("hora_activacion"):
                    detalle_act += f" {row.get('hora_activacion')}"
                st.caption(f"🕓 Esta posición venía de una orden pendiente: se activó el {detalle_act}. "
                           "El Take Profit / Stop Loss se evalúa desde ese momento en adelante.")

            if row.get("precio_cierre") is not None:
                hora_cierre_txt = row.get("hora_cierre")
                st.caption(_md_dolar(
                    f"Cerrada el {row.get('fecha_cierre','')}"
                    + (f" a las {hora_cierre_txt}" if hora_cierre_txt else "")
                    + f" a {fmt_precio_local(row.get('precio_cierre'))}"
                ))

            if row.get("notas"):
                st.markdown(f"**Notas:** {row['notas']}")


# ==============================================================
#  SIMULADOR DE OPERACIÓN
#  El usuario elige una señal publicada y simula la operación con SU
#  cuenta: plataforma, tipo de operación, capital total, % de riesgo,
#  capital para la operación y apalancamiento. Entrada, SL y TP vienen
#  de la señal.
# ==============================================================

PLATAFORMAS = ["Exchange · unidades", "Broker · lotes"]
TIPOS_OPERACION = ["Inversión", "Trade"]

CONTRATO_FOREX = 100_000.0  # 1 lote estándar = 100.000 unidades de la divisa base

# Tamaño de contrato estándar (unidades por 1 lote) de los commodities más comunes.
CONTRATOS_COMMODITY = {
    "GC=F": 100.0, "XAUUSD=X": 100.0, "XAUUSD": 100.0, "MGC=F": 10.0,   # Oro (onzas)
    "SI=F": 5000.0, "XAGUSD=X": 5000.0, "XAGUSD": 5000.0,               # Plata (onzas)
    "CL=F": 1000.0, "BZ=F": 1000.0, "USOIL": 1000.0,                    # Petróleo (barriles)
    "NG=F": 10000.0,                                                    # Gas natural
    "HG=F": 25000.0,                                                    # Cobre (libras)
    "PL=F": 50.0, "PA=F": 100.0,                                        # Platino / Paladio
}

# Techo absoluto: perder más que esto de TODA la cuenta en una operación siempre es ALTO.
PERDIDA_PCT_CUENTA_ALTO_ABSOLUTO = 15.0

_NIVELES_UI = {
    "ok":     ("#3fb950", "🟢"),
    "warn":   ("#f0883e", "🟠"),
    "danger": ("#f85149", "🔴"),
    "info":   ("#3a7bd5", "ℹ️"),
}


def _banner_calc(nivel, texto):
    color, icono = _NIVELES_UI[nivel]
    return (f'<div style="background:{color}22;border:1px solid {color};border-left:5px solid {color};'
            f'border-radius:10px;padding:14px 18px;margin-bottom:14px;font-size:14px;font-weight:600;'
            f'color:#e6edf3;line-height:1.5">{icono} {_h(texto)}</div>')


def _kpi_card(titulo, valor, detalle="", color="#e6edf3", destacado=False):
    borde = f"2px solid {color}" if destacado else "1px solid #21262d"
    tam = "28px" if destacado else "19px"
    return (f'<div style="background:#0d1117;border:{borde};border-radius:10px;padding:12px 14px;'
            f'min-height:98px;margin-bottom:10px">'
            f'<div style="font-size:11px;color:#6b7d9a;margin-bottom:4px">{_h(titulo)}</div>'
            f'<div style="font-size:{tam};font-weight:700;color:{color};line-height:1.2">{_h(valor)}</div>'
            f'<div style="font-size:11px;color:#8b949e;margin-top:4px">{_h(detalle)}</div></div>')


def _floor_dec(x, decimales):
    """Redondea hacia ABAJO (la cantidad nunca pasa tu límite de riesgo)."""
    f = 10 ** decimales
    return math.floor(x * f + 1e-9) / f


def _config_activo_sim(categoria, ticker, usa_lotes):
    """Decimales de cantidad y tamaño de lote según la categoría del activo y la plataforma."""
    t = (ticker or "").upper().strip()
    if categoria == "💱 Forex":
        dec_unid, contrato, conocido = 0, CONTRATO_FOREX, True
    elif categoria == "🛢️ Commodity":
        c = CONTRATOS_COMMODITY.get(t)
        dec_unid, contrato, conocido = 2, (c or 100.0), c is not None
    elif categoria == "₿ Cripto":
        dec_unid, contrato, conocido = 6, 1.0, False
    else:
        dec_unid, contrato, conocido = 0, 1.0, False
    if usa_lotes:
        return dict(dec_cant=2, es_lotes=True, contrato=contrato, contrato_conocido=conocido)
    return dict(dec_cant=dec_unid, es_lotes=False, contrato=1.0, contrato_conocido=True)


def _cantidad_automatica(capital_op, apal, entrada, cfg):
    """Devuelve (cantidad en su unidad [lotes o unidades], cantidad en unidades)."""
    if entrada <= 0 or capital_op <= 0:
        return 0.0, 0.0
    exposicion = capital_op * apal
    if cfg["es_lotes"]:
        lotes = _floor_dec(exposicion / (entrada * cfg["contrato"]), cfg["dec_cant"])
        return lotes, lotes * cfg["contrato"]
    unidades = _floor_dec(exposicion / entrada, cfg["dec_cant"])
    return unidades, unidades


def _calcular_stop_loss(entrada, stop, cantidad, apal, es_largo, capital_cuenta,
                        take_profit=None, atr=None):
    """Pérdida al stop, precio de liquidación aproximado y ganancia/ratio al TP."""
    distancia_stop_pct = abs(stop - entrada) / entrada * 100
    exposicion = entrada * cantidad
    capital_propio = exposicion / apal
    perdida = abs(entrada - stop) * cantidad
    perdida_pct_cuenta = perdida / capital_cuenta * 100 if capital_cuenta > 0 else None

    liq = entrada * (1 - 1 / apal) if es_largo else entrada * (1 + 1 / apal)
    dist_liq_pct = abs(liq - entrada) / entrada * 100
    stop_antes_de_liquidar = (stop > liq) if es_largo else (stop < liq)

    ganancia = rr = None
    if take_profit and take_profit > 0:
        ganancia = (take_profit - entrada) * cantidad if es_largo else (entrada - take_profit) * cantidad
        if perdida > 0:
            rr = ganancia / perdida

    return dict(
        distancia_stop_pct=distancia_stop_pct, exposicion=exposicion, capital_propio=capital_propio,
        perdida=perdida, perdida_pct_cuenta=perdida_pct_cuenta, precio_liquidacion=liq,
        dist_liq_pct=dist_liq_pct, stop_antes_de_liquidar=stop_antes_de_liquidar,
        ganancia=ganancia, rr=rr,
        dist_stop_en_atr=(abs(entrada - stop) / atr) if atr and atr > 0 else None,
    )


def _avisos_riesgo(info, horizonte, pct_riesgo):
    """Avisos en criollo sobre el riesgo de la operación simulada."""
    avisos = []
    p = info["perdida_pct_cuenta"]
    if p is not None:
        if p > PERDIDA_PCT_CUENTA_ALTO_ABSOLUTO:
            avisos.append(f"🚨 Si te toca el stop, perdés {p:.1f}% de TODA tu cuenta. Es una pérdida "
                          "enorme para una sola operación.")
        elif p > pct_riesgo * 2:
            avisos.append(f"Si te toca el stop, perdés {p:.1f}% de tu cuenta, muy por encima del "
                          f"{pct_riesgo:g}% que definiste. La posición es demasiado grande.")
        elif p > pct_riesgo * 1.0001:
            avisos.append(f"Si te toca el stop, perdés {p:.1f}% de tu cuenta, un poco por encima del "
                          f"{pct_riesgo:g}% que te propusiste.")
        else:
            avisos.append(f"Si te toca el stop, perdés {p:.1f}% de tu cuenta, dentro de lo que "
                          "dijiste que estabas dispuesto a arriesgar. ✅")

    if not info["stop_antes_de_liquidar"]:
        avisos.append("⚠️ Con este apalancamiento, el precio de liquidación llega ANTES que el stop: "
                      "te cerrarían la posición por la fuerza antes de que el stop actúe.")
    elif (info["dist_liq_pct"] - info["distancia_stop_pct"]) < 2:
        avisos.append("El stop está muy cerca del precio de liquidación: casi no hay margen para un "
                      "movimiento brusco.")

    if info["dist_stop_en_atr"] is not None:
        minimo = 1.0 if horizonte == "corto" else 1.5
        if info["dist_stop_en_atr"] < minimo:
            avisos.append(f"El stop está muy pegado al precio (a solo {info['dist_stop_en_atr']:.2f} "
                          "veces la volatilidad normal del activo): puede saltar por un vaivén normal.")

    rr = info["rr"]
    if rr is not None:
        if rr < 1:
            avisos.append(f"Por cada $1 que arriesgás, buscás ganar ${rr:.2f}: arriesgás más de lo "
                          "que buscás ganar.")
        elif rr < 1.5:
            avisos.append(f"Por cada $1 que arriesgás, buscás ganar ${rr:.2f}. Aceptable, aunque lo "
                          "ideal es apuntar a $2 o más.")
        else:
            avisos.append(f"Por cada $1 que arriesgás, buscás ganar ${rr:.2f}. Relación favorable. ✅")
    return avisos


def _panel_resultados_sim(capital, pct_max, horizonte, es_largo, apal, entrada, cant_u,
                          cant_mostrar, cfg, stop, tp, atr_val):
    if cant_u <= 0:
        st.markdown(_banner_calc("info", "Cargá el capital para la operación para ver los resultados "
                                         "(tiene que alcanzar para la cantidad mínima operable)."),
                    unsafe_allow_html=True)
        return

    info = _calcular_stop_loss(entrada, stop, cant_u, apal, es_largo, capital, tp, atr_val)
    perdida, perdida_pct = info["perdida"], info["perdida_pct_cuenta"]
    dinero_max = capital * pct_max / 100
    sobre = perdida > dinero_max * 1.0001

    # ── Banner ──
    if not info["stop_antes_de_liquidar"]:
        lado = "por debajo" if es_largo else "por encima"
        st.markdown(_banner_calc("danger", f"Peligro: el Stop Loss está {lado} del precio de liquidación"),
                    unsafe_allow_html=True)
    elif perdida_pct > PERDIDA_PCT_CUENTA_ALTO_ABSOLUTO:
        st.markdown(_banner_calc("danger", f"Peligro: si salta el stop perdés {perdida_pct:.1f}% de TODA "
                                           "tu cuenta — demasiado para una sola operación"),
                    unsafe_allow_html=True)
    elif perdida > dinero_max * 2:
        st.markdown(_banner_calc("danger", f"Sobre-riesgo fuerte: perdés ${perdida:,.2f} ({perdida_pct:.1f}%) "
                                           f"y tu límite es ${dinero_max:,.2f} ({pct_max:g}%). Reducí el capital."),
                    unsafe_allow_html=True)
    elif sobre:
        st.markdown(_banner_calc("warn", f"Sobre-riesgo: perdés ${perdida:,.2f} ({perdida_pct:.1f}%) y tu "
                                         f"límite es ${dinero_max:,.2f} ({pct_max:g}%). Reducí el capital."),
                    unsafe_allow_html=True)
    else:
        st.markdown(_banner_calc("ok", f"Riesgo dentro del límite: arriesgás ${perdida:,.2f} "
                                       f"({perdida_pct:.1f}% de tu cuenta) de un máximo de ${dinero_max:,.2f}"),
                    unsafe_allow_html=True)

    # ── KPIs ──
    gan, rr = info["ganancia"], info["rr"]

    if gan is None:
        card_gan = _kpi_card("Ganancia estimada (Take Profit)", "—",
                             "La señal no tiene Take Profit", "#6b7d9a", True)
    elif gan <= 0:
        card_gan = _kpi_card("Ganancia estimada (Take Profit)", "—",
                             "⚠️ El Take Profit de la señal está del lado equivocado de la entrada",
                             "#f0883e", True)
    else:
        dist_tp = abs(tp - entrada) / entrada * 100
        card_gan = _kpi_card("Ganancia estimada (Take Profit)", f"+${gan:,.2f}",
                             f"+{gan / capital * 100:.1f}% de tu cuenta · TP a {dist_tp:.2f}% de la entrada · "
                             f"neto vs. pérdida del stop: +${gan - perdida:,.2f}", "#3fb950", True)

    card_perd = _kpi_card("Pérdida máxima (si salta el Stop)", f"-${perdida:,.2f}",
                          f"{perdida_pct:.1f}% de tu cuenta · límite ${dinero_max:,.2f} · "
                          f"stop a {info['distancia_stop_pct']:.2f}%",
                          "#f85149" if sobre else "#e6edf3")

    if rr is None or (gan is not None and gan <= 0):
        card_rr = _kpi_card("Ratio Riesgo / Beneficio", "—", "Sin Take Profit válido para calcularlo", "#6b7d9a")
    else:
        col_rr = "#3fb950" if rr >= 2 else ("#e3b341" if rr >= 1 else "#f85149")
        txt_rr = ("Relación favorable" if rr >= 2 else
                  ("Aceptable, ideal ≥ 1:2" if rr >= 1 else "Arriesgás más de lo que buscás ganar"))
        card_rr = _kpi_card("Ratio Riesgo / Beneficio", f"1:{rr:.1f}", txt_rr, col_rr)

    margen = info["capital_propio"]
    card_marg = _kpi_card("Margen requerido", f"${margen:,.2f}",
                          f"{margen / capital * 100:.1f}% de tu cuenta · exposición ${info['exposicion']:,.2f}"
                          + (" · ⚠️ supera tu capital" if margen > capital else ""),
                          "#f85149" if margen > capital else "#e6edf3")

    if apal > 1:
        card_liq = _kpi_card("Precio de liquidación aprox.", fmt_precio_exacto(info["precio_liquidacion"]),
                             f"a {info['dist_liq_pct']:.2f}% de la entrada",
                             "#e6edf3" if info["stop_antes_de_liquidar"] else "#f85149")
    else:
        card_liq = _kpi_card("Precio de liquidación aprox.", "No aplica",
                             "Sin apalancamiento (1x) nadie te puede liquidar", "#6b7d9a")

    unidad = "lotes" if cfg["es_lotes"] else "unidades"
    detalle_pos = f"{fmt_unidades(cant_u)} unidades" if cfg["es_lotes"] else f"a {fmt_precio_exacto(entrada)}"
    card_pos = _kpi_card("Posición simulada", f"{cant_mostrar:,.{cfg['dec_cant']}f} {unidad}", detalle_pos)

    fila1, fila2, fila3 = st.columns(2), st.columns(2), st.columns(2)
    for col, card in zip(fila1 + fila2 + fila3,
                         [card_gan, card_perd, card_rr, card_marg, card_liq, card_pos]):
        with col:
            st.markdown(card, unsafe_allow_html=True)

    with st.expander("Ver detalle de los avisos de riesgo"):
        for aviso in _avisos_riesgo(info, horizonte, pct_max):
            st.markdown(f"- {_md_dolar(aviso)}")


def _tab_simulador(supabase, es_pro=True, es_admin=False):
    st.caption(
        "Elegí una señal y simulá la operación con tu cuenta: la entrada, el Stop Loss y el Take "
        "Profit son los de la señal; vos solo cargás tu plataforma, tu capital y tu riesgo."
    )

    senales, ocultas = _filtrar_senales_por_plan(_obtener_senales(supabase, 200), es_pro)
    if not es_pro:
        _banner_plan_basico(ocultas)
    if not senales:
        st.info("Todavía no hay señales para simular en tu plan.")
        return

    # ── Elegir la señal ──
    por_id, labels = {}, {}
    for s in senales:
        sid = s["id"]
        por_id[sid] = s
        emoji = ESTADO_COLOR.get(s.get("estado"), ("", "", "⚪"))[2]
        labels[sid] = (f"{emoji} {s.get('fecha','')} · {s.get('ticker','')} · "
                       f"{s.get('tipo','')} · {s.get('estado','')}")
    sid_sel = st.selectbox("🗂️ Señal a simular", list(por_id.keys()),
                           format_func=lambda i: labels[i], key="sim_senal_sel")
    senal = por_id[sid_sel]

    ticker = str(senal.get("ticker") or "")
    categoria = senal.get("categoria") or "🔹 Otro"
    es_largo = "LARGO" in str(senal.get("tipo", "")).upper()
    entradas_senal = _entradas_de_senal(senal)
    entrada = _precio_promedio_ponderado(senal)
    sl = float(senal.get("stop_loss") or 0)
    tp = float(senal.get("take_profit") or 0)

    if entrada <= 0 or sl <= 0:
        st.error("Esta señal no tiene entrada o Stop Loss válidos, no se puede simular.")
        return
    if (es_largo and sl >= entrada) or ((not es_largo) and sl <= entrada):
        st.error("El Stop Loss de esta señal está del lado equivocado de la entrada, no se puede simular.")
        return

    if senal.get("estado") == "PENDIENTE":
        st.caption("🕓 Esta señal es una orden pendiente: la simulación asume que se activa en el "
                   "precio de entrada.")

    atr_val, _px = _atr_y_precio_actual(ticker.upper()) if ticker else (None, None)

    col_in, col_out = st.columns([1, 1.25], gap="large")

    # ══════════════════ IZQUIERDA: INPUTS ══════════════════
    with col_in:
        st.markdown("#### 📥 Parámetros de tu operación")

        # ── ① Activo y cuenta ──
        with st.container(border=True):
            st.markdown("**① Activo y cuenta**")
            st.caption(f"🎯 **{ticker}** · {categoria} · {'🟢 LARGO' if es_largo else '🔴 CORTO'}")
            usa_lotes = st.radio(
                "Plataforma donde operás", PLATAFORMAS, horizontal=True, key="sim_plataforma",
                help="Exchange: operás en unidades/tokens. Broker CFD (MT4/MT5, cTrader, etc.): operás "
                     "en lotes. Las dos permiten apalancamiento.") == "Broker · lotes"
            tipo_op = st.radio(
                "Tipo de operación", TIPOS_OPERACION, horizontal=True, key="sim_tipo_op",
                help="Inversión: comprar y conservar meses/años (normalmente sin apalancar). "
                     "Trade: operación acotada de días o semanas. Ajusta los avisos de riesgo.")
            horizonte = "largo" if tipo_op == "Inversión" else "corto"

            b1, b2 = st.columns(2)
            with b1:
                capital_cuenta = st.number_input(
                    "💰 Capital total (USD)", min_value=1.0, value=1000.0, step=100.0,
                    key="sim_capital_cuenta",
                    help="NO es lo que ponés en esta operación: es TODO tu dinero operable. Sirve solo "
                         "de base para calcular qué porción de tu cuenta arriesgás.")
            with b2:
                pct_riesgo = st.number_input(
                    "% de riesgo deseado", min_value=0.1, max_value=25.0, value=2.0, step=0.5,
                    key="sim_pct_riesgo",
                    help="% de tu capital TOTAL que aceptás perder si salta el stop. Regla clásica: 1-2%.")
            dinero_max = capital_cuenta * pct_riesgo / 100
            st.caption(_md_dolar(f"Máximo a perder: **${dinero_max:,.2f}**")
                       + (" · ⚠️ por encima del 5% que suele recomendarse" if pct_riesgo > 5 else ""))

        cfg = _config_activo_sim(categoria, ticker, usa_lotes)

        # ── ② Parámetros de entrada ──
        with st.container(border=True):
            st.markdown("**② Parámetros de entrada**")
            capital_op = st.number_input(
                "💵 Capital para la operación (USD)", min_value=0.0, value=0.0, step=10.0,
                format="%.2f", key="sim_capital_op",
                help="Cuánta plata tuya (margen) ponés en ESTA operación. Con el apalancamiento se "
                     "calcula la cantidad. Es distinto del capital total de tu cuenta.")
            apal = st.number_input(
                "Apalancamiento (x)", min_value=1.0, max_value=1000.0, value=1.0, step=1.0,
                key="sim_apal",
                help="1x = con tu propia plata, sin margen."
                     + (" Para inversión de largo plazo lo normal es 1x." if horizonte == "largo" else ""))

            cant_mostrar, cant_u = _cantidad_automatica(capital_op, apal, entrada, cfg)
            etiqueta_entrada = (f"promedio de {len(entradas_senal)} entradas"
                                if len(entradas_senal) > 1 else "entrada de la señal")
            st.caption(f"📍 Precio de entrada: **{fmt_precio_exacto(entrada)}** ({etiqueta_entrada})")
            if cfg["es_lotes"]:
                st.caption(f"📦 Cantidad automática: **{cant_mostrar:,.{cfg['dec_cant']}f} lotes** "
                           f"(1 lote = {cfg['contrato']:,.8g} unidades → {fmt_unidades(cant_u)} unidades)")
                if not cfg["contrato_conocido"]:
                    st.caption("⚠️ El tamaño de lote es un valor típico, no un dato seguro: verificalo "
                               "en la especificación del contrato de tu bróker.")
            else:
                st.caption(f"📦 Cantidad automática: **{fmt_unidades(cant_u)} unidades**")

            if horizonte == "largo" and apal > 1:
                st.info('Marcaste "Inversión" pero usás apalancamiento: existe precio de liquidación '
                        "aunque tu plan sea conservar.")

            # Capital máximo (margen) que respeta tu riesgo con el stop de la señal
            rec_u = dinero_max / abs(entrada - sl)
            cap_rec = math.floor(rec_u * entrada / apal * 100) / 100

            if capital_op > capital_cuenta:
                st.warning(_md_dolar(f"⚠️ El capital de la operación (${capital_op:,.2f}) supera el "
                                     f"capital total de tu cuenta (${capital_cuenta:,.2f})."))
            if cant_u > 0:
                perd = abs(entrada - sl) * cant_u
                if perd > dinero_max * 1.0001:
                    msg = _md_dolar(
                        f"🚨 Con **${capital_op:,.2f}** de capital ({apal:g}x) te pasás de tu riesgo "
                        f"deseado: si salta el stop perdés **${perd:,.2f}** "
                        f"({perd / capital_cuenta * 100:.1f}% de tu cuenta) y tu límite es "
                        f"**${dinero_max:,.2f}** ({pct_riesgo:g}%). "
                        f"Capital máximo para respetarlo: **${cap_rec:,.2f}**.")
                    (st.error if perd > dinero_max * 2 else st.warning)(msg)
            elif capital_op > 0:
                st.warning("Con este capital y apalancamiento no alcanza ni para la mínima cantidad "
                           "operable. Subí el capital o el apalancamiento.")

            if cap_rec > 0:
                st.button(_md_dolar(f"⚡ Usar capital recomendado (${cap_rec:,.2f})"),
                          key="sim_usar_recomendado", on_click=_set_state,
                          args=("sim_capital_op", cap_rec))
            else:
                st.caption("Con el stop de esta señal y tu % de riesgo no alcanza ni para la mínima "
                           "cantidad operable. Subí el % de riesgo.")

        # ── ③ Gestión de salida (de la señal) ──
        with st.container(border=True):
            st.markdown("**③ Gestión de salida**")
            g1, g2 = st.columns(2)
            g1.metric("🛑 Stop Loss", fmt_precio_exacto(sl),
                      delta=f"{abs(entrada - sl) / entrada * 100:.2f}% de la entrada", delta_color="off")
            if tp > 0:
                g2.metric("🎯 Take Profit", fmt_precio_exacto(tp),
                          delta=f"{abs(tp - entrada) / entrada * 100:.2f}% de la entrada", delta_color="off")
            else:
                g2.metric("🎯 Take Profit", "—")
            st.caption("El Stop Loss y el Take Profit son los que publicó el administrador en la señal.")

    # ══════════════════ DERECHA: RESULTADOS ══════════════════
    with col_out:
        st.markdown("#### 📊 Resultados posibles")
        _panel_resultados_sim(capital_cuenta, pct_riesgo, horizonte, es_largo, apal, entrada,
                              cant_u, cant_mostrar, cfg, sl, tp, atr_val)

    st.caption("⚠️ Simulación educativa, no asesoramiento financiero. El precio de liquidación es "
               "aproximado (no incluye fees ni margen de mantenimiento del bróker/exchange). No "
               "contempla comisiones, spread, financiamiento, swap ni slippage. En Forex y "
               "Commodities la pérdida se expresa en USD asumiendo que la moneda de cotización es el dólar.")


# ==============================================================
#  ENTRY POINT — llamar desde app.py
# ==============================================================

def render_senales_trading(supabase, user_id, user_email, tiene_acceso_pro=False):
    """Uso desde app.py:
        render_senales_trading(supabase, USER_ID, st.session_state['usuario'].email,
                               tiene_acceso_pro=TIENE_SENALES_PRO)

    tiene_acceso_pro=True  → señales ilimitadas (Pro / Admin).
    tiene_acceso_pro=False → solo la señal gratuita (Básico / Trial).
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
        Señales publicadas con fecha, hora, una o varias entradas, stop loss y take profit
        — o cargadas como órdenes pendientes (🕓) que se activan solas cuando el precio toca
        la entrada. Evaluación automática de aciertos/desaciertos, P&L en vivo para las
        abiertas y simulador de operación.
        Plan Pro: señales ilimitadas · Plan Básico/Prueba: 1 señal destacada.
      </div>
    </div>
    """, unsafe_allow_html=True)

    tab_pub, tab_hist, tab_sim = st.tabs([
        "📢 Publicar Señal", "📋 Señales y Resultados", "🧮 Simulador de Operación",
    ])
    with tab_pub:
        _tab_publicar(supabase, user_id, user_email, es_admin)
    with tab_hist:
        _tab_senales(supabase, es_admin, es_pro)
    with tab_sim:
        _tab_simulador(supabase, es_pro, es_admin)
