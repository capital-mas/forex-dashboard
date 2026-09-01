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
#   - Se eliminó la pestaña independiente "Gestor de Riesgo". Su
#     cálculo (tamaño de posición a partir de un % de capital en
#     riesgo y la distancia al Stop Loss) ahora vive DENTRO del
#     Simulador de Capital, como el modo "🎯 % de riesgo por
#     operación (según Stop Loss)".
#   - Nuevo: Perfiles de riesgo (🟢 Conservador / 🟡 Moderado /
#     🔴 Agresivo). El admin define, al publicar cada señal, qué %
#     de capital arriesgaría cada perfil si el precio llega al
#     Stop Loss. REQUIERE migrar la tabla en Supabase:
#       ALTER TABLE senales_trading
#       ADD COLUMN IF NOT EXISTS riesgo_conservador float DEFAULT 1.0,
#       ADD COLUMN IF NOT EXISTS riesgo_moderado    float DEFAULT 2.0,
#       ADD COLUMN IF NOT EXISTS riesgo_agresivo    float DEFAULT 3.0;
#     (además de la columna "categoria" agregada en la versión anterior)
#   - En "Señales y Resultados", cada señal ahora tiene un selector
#     de perfil de riesgo: el usuario elige con qué perfil quiere
#     tomar esa señal y la app calcula solo el tamaño de posición
#     sugerido, el capital que usaría de margen y el riesgo/premio
#     en dólares.
#   - En el Simulador de Capital se agregó el modo "🎭 Comparar los
#     3 perfiles de riesgo": corre la simulación completa una vez
#     por perfil (usando el % que definió el admin en cada señal) y
#     muestra los resultados uno al lado del otro, con una
#     explicación de qué implica cada perfil.
# ==============================================================

import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, datetime, time as dt_time

ADMIN_EMAIL = "brainferreyra@gmail.com"
TABLA_SENALES = "senales_trading"

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
    entrada = float(senal["precio_entrada"])
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


def fmt_precio_local(p):
    if p is None:
        return "S/D"
    p = float(p)
    if p >= 1000: return f"${p:,.0f}"
    if p >= 10:   return f"${p:.2f}"
    return f"${p:.5f}"


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

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        ticker = st.text_input("🎯 Ticker", key="sen_ticker", placeholder="Ej: NVDA, BTC-USD, EURUSD=X")
    with c2:
        categoria = st.selectbox("🏷️ Categoría del activo", CATEGORIAS, key="sen_categoria")
    with c3:
        tipo = st.selectbox("Tipo de operación", ["🟢 LARGO (Compra)", "🔴 CORTO (Venta)"], key="sen_tipo")
    with c4:
        apalancamiento = st.number_input("Apalancamiento (x)", min_value=1.0, max_value=125.0,
                                          value=1.0, step=1.0, key="sen_apalancamiento")

    f1, f2 = st.columns(2)
    with f1:
        fecha = st.date_input("📅 Fecha", value=date.today(), key="sen_fecha")
    with f2:
        hora = st.time_input("🕐 Hora", value=datetime.now().time().replace(microsecond=0), key="sen_hora")

    p1, p2, p3 = st.columns(3)
    with p1:
        precio_entrada = st.number_input("Precio de entrada", min_value=0.0, format="%.5f", key="sen_entrada")
    with p2:
        stop_loss = st.number_input("🛑 Stop Loss", min_value=0.0, format="%.5f", key="sen_sl")
    with p3:
        take_profit = st.number_input("🎯 Take Profit", min_value=0.0, format="%.5f", key="sen_tp")

    notas = st.text_area("💬 Notas / justificación", key="sen_notas", height=80,
                          placeholder="Motivo de la señal, contexto técnico o fundamental...")

    # Validación visual rápida antes de guardar
    if precio_entrada > 0 and stop_loss > 0 and take_profit > 0:
        es_largo_preview = "LARGO" in tipo.upper()
        ok_niveles = (stop_loss < precio_entrada < take_profit) if es_largo_preview \
            else (take_profit < precio_entrada < stop_loss)
        if not ok_niveles:
            st.warning("⚠️ Revisá los niveles: para LARGO, SL < Entrada < TP. Para CORTO, TP < Entrada < SL.")

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
        if not ticker or precio_entrada <= 0 or stop_loss <= 0 or take_profit <= 0:
            st.warning("⚠️ Completá ticker, precio de entrada, stop loss y take profit.")
        else:
            datos = dict(ticker=ticker, categoria=categoria, tipo=tipo, fecha=fecha, hora=hora,
                         precio_entrada=precio_entrada, stop_loss=stop_loss,
                         take_profit=take_profit, apalancamiento=apalancamiento, notas=notas,
                         riesgo_conservador=riesgo_conservador, riesgo_moderado=riesgo_moderado,
                         riesgo_agresivo=riesgo_agresivo)
            try:
                _guardar_senal(supabase, datos, user_id, user_email)
                _obtener_senales.clear()
                st.success("✅ Señal publicada.")
                for k in ["sen_ticker", "sen_entrada", "sen_sl", "sen_tp", "sen_notas"]:
                    st.session_state.pop(k, None)
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
            v1, v2, v3, v4 = st.columns(4)
            v1.metric("Entrada", fmt_precio_local(row.get("precio_entrada")))
            v2.metric("Stop Loss", fmt_precio_local(row.get("stop_loss")))
            v3.metric("Take Profit", fmt_precio_local(row.get("take_profit")))
            v4.metric("Apalancamiento", f"{row.get('apalancamiento', 1):.0f}x")
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
#  Ahora cada señal tiene un selector de perfil de riesgo que
#  calcula el tamaño de posición sugerido.
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
            v1, v2, v3, v4 = st.columns(4)
            v1.metric("Entrada", fmt_precio_local(row.get("precio_entrada")))
            v2.metric("Stop Loss", fmt_precio_local(row.get("stop_loss")))
            v3.metric("Take Profit", fmt_precio_local(row.get("take_profit")))
            v4.metric("Apalancamiento", f"{row.get('apalancamiento', 1):.0f}x")

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
    modo de cálculo elegido. Devuelve None si faltan datos para calcular."""
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
        "Estado": "💀 LIQUIDADA" if liquidada else estado,
        "Apalanc.": f"{s.get('apalancamiento',1):.0f}x",
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
# ==============================================================

MODOS_SIM = [
    "💵 Monto fijo por señal",
    "📊 % del capital por señal",
    "🎯 % de riesgo por operación (según Stop Loss)",
    "📦 Por lotes (tamaño de posición)",
    "🎭 Comparar los 3 perfiles de riesgo",
]


def _tab_simulador(supabase):
    st.caption("Simulá cuánto hubieras ganado o perdido replicando las señales publicadas, "
               "con tu propio capital.")

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
    for _, row in df_base.iterrows():
        s = row.to_dict()
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
        st.info("No se pudo simular ninguna señal (faltan precios de referencia o datos de SL/entrada).")
        return

    df_sim = pd.DataFrame(filas_sim)
    label_capital = ("Margen total usado"
                      if modo in ("📦 Por lotes (tamaño de posición)", "🎯 % de riesgo por operación (según Stop Loss)")
                      else "Capital asignado total")

    capital_asignado_total, _ = _mostrar_metricas_sim(df_sim, label_capital)

    if modo in ("📦 Por lotes (tamaño de posición)", "🎯 % de riesgo por operación (según Stop Loss)") \
            and capital_asignado_total > capital_total:
        st.warning(
            f"⚠️ El margen total requerido (USD {capital_asignado_total:,.2f}) supera tu "
            f"capital declarado (USD {capital_total:,.2f}). Con esta configuración estarías "
            "sobre-apalancado si abrieras todas estas operaciones a la vez."
        )

    _mostrar_tabla_estilizada(df_sim)
    _mostrar_mejor_peor(df_sim)

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
        ADD COLUMN IF NOT EXISTS riesgo_agresivo    float DEFAULT 3.0;
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
        Señales publicadas con fecha, hora, stop loss, take profit, categoría, apalancamiento y
        perfiles de riesgo (🟢 Conservador / 🟡 Moderado / 🔴 Agresivo) — evaluación automática de
        aciertos/desaciertos y simulador de capital (por monto, %, riesgo, lotes o comparando
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
