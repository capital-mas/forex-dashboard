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
#   - Nuevo campo "categoria" (Acción / Índice / Commodity / Forex /
#     Cripto / Bono-ETF / Otro) al publicar señales, con filtro en
#     el historial. REQUIERE migrar la tabla en Supabase:
#       ALTER TABLE senales_trading
#       ADD COLUMN IF NOT EXISTS categoria text DEFAULT '🔹 Otro';
#   - Simulador de capital con dos familias de modos:
#       a) por monto fijo / % de capital (igual que antes, basado
#          en el % de retorno apalancado)
#       b) por LOTES: tamaño de posición en unidades reales, donde
#          el P&L depende del movimiento de precio y del tamaño de
#          la posición (no del apalancamiento). El apalancamiento
#          solo define el margen necesario. Es el cálculo que usan
#          los brókers de verdad. Como cada bróker define distinto
#          cuántas unidades tiene 1 lote (sobre todo en Forex,
#          índices y commodities), el valor "unidades por lote" es
#          editable por categoría.
#   - Eliminar señal ahora pide confirmación explícita (checkbox)
#     antes de habilitar el botón, para evitar borrados accidentales.
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
    """Modo 'lotes': cálculo de P&L como lo hace un bróker real. El
    resultado en dinero depende del movimiento de precio y del
    tamaño de la posición (unidades), NO directamente del
    apalancamiento. El apalancamiento solo define cuánto margen
    (capital) necesitás inmovilizar para abrir esa posición — por
    eso a mayor apalancamiento, menor margen usado y mayor
    rendimiento % sobre ese margen, aunque el P&L en dólares sea
    el mismo.

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


def fmt_precio_local(p):
    if p is None:
        return "S/D"
    p = float(p)
    if p >= 1000: return f"${p:,.0f}"
    if p >= 10:   return f"${p:.2f}"
    return f"${p:.5f}"


# ==============================================================
#  RENDER — TAB PUBLICAR (solo admin)
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

    if st.button("📢 Publicar señal", type="primary", key="sen_btn_publicar"):
        if not ticker or precio_entrada <= 0 or stop_loss <= 0 or take_profit <= 0:
            st.warning("⚠️ Completá ticker, precio de entrada, stop loss y take profit.")
        else:
            datos = dict(ticker=ticker, categoria=categoria, tipo=tipo, fecha=fecha, hora=hora,
                         precio_entrada=precio_entrada, stop_loss=stop_loss,
                         take_profit=take_profit, apalancamiento=apalancamiento, notas=notas)
            try:
                _guardar_senal(supabase, datos, user_id, user_email)
                _obtener_senales.clear()
                st.success("✅ Señal publicada.")
                for k in ["sen_ticker", "sen_entrada", "sen_sl", "sen_tp", "sen_notas"]:
                    st.session_state.pop(k, None)
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error al publicar: {e}")


# ==============================================================
#  RENDER — TAB SEÑALES Y RESULTADOS (todos ven)
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
        color_ret = "#3fb950" if ret_apalancado >= 0 else "#f85149"

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

            if es_admin and estado == "ABIERTA":
                cc1, cc2 = st.columns(2)
                with cc1:
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
                with cc2:
                    st.write("")
                    confirmar = st.checkbox("Confirmar eliminación", key=f"sen_confirm_del_{row['id']}")
                    if st.button("🗑️ Eliminar señal", key=f"sen_btn_del_{row['id']}",
                                 disabled=not confirmar):
                        _borrar_senal(supabase, row["id"])
                        _obtener_senales.clear()
                        st.success("Señal eliminada.")
                        st.rerun()
            elif es_admin and estado != "ABIERTA":
                # También se puede borrar una señal ya cerrada (ej. cargada por error)
                confirmar_cerrada = st.checkbox("Confirmar eliminación de esta señal cerrada",
                                                 key=f"sen_confirm_del_c_{row['id']}")
                if st.button("🗑️ Eliminar señal", key=f"sen_btn_del_c_{row['id']}",
                             disabled=not confirmar_cerrada):
                    _borrar_senal(supabase, row["id"])
                    _obtener_senales.clear()
                    st.success("Señal eliminada.")
                    st.rerun()


# ==============================================================
#  RENDER — TAB SIMULADOR (todos)
# ==============================================================

def _tab_simulador(supabase):
    st.caption("Simulá cuánto hubieras ganado o perdido replicando las señales publicadas, "
               "con tu propio capital y el apalancamiento definido en cada señal.")

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
        modo = st.selectbox("Modo de asignación", [
            "💵 Monto fijo por señal",
            "📊 % del capital por señal",
            "📦 Por lotes (tamaño de posición)",
        ], key="sim_modo")
    with c3:
        incluir_abiertas = st.checkbox("Incluir señales abiertas (P&L flotante)", value=True, key="sim_incluir_abiertas")

    monto_por_senal = None
    pct_por_senal = None
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

    else:
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

    df = df_base.copy()
    if df.empty:
        st.info("No hay señales para incluir en la simulación con estos filtros.")
        return

    filas_sim = []
    for _, row in df.iterrows():
        s = row.to_dict()
        estado = s.get("estado", "ABIERTA")
        precio_ref = s.get("precio_cierre")
        if precio_ref is None:
            ev = _evaluar_senal(s)
            precio_ref = ev["precio_ref"]
        if precio_ref is None:
            continue

        cat = s.get("categoria") or "🔹 Otro"
        ret_precio, _ = _calcular_retorno(s, precio_ref)
        extra_cols = {}

        if modo == "📦 Por lotes (tamaño de posición)":
            unidades_por_lote = unidades_por_categoria.get(cat, DEFAULT_UNIDADES_LOTE.get(cat, 1.0))
            unidades = unidades_por_lote * cantidad_lotes
            pnl_usd, margen, ret_apalancado = _calcular_pnl_lotes(s, precio_ref, unidades)
            capital_asignado = margen
            liquidada = ret_apalancado <= -100
            if liquidada:
                pnl_usd = -capital_asignado
                ret_apalancado = -100.0
            capital_final = capital_asignado + pnl_usd
            extra_cols = {"Lotes": round(cantidad_lotes, 2), "Unidades": round(unidades, 2)}
        else:
            _, ret_apalancado = _calcular_retorno(s, precio_ref)
            capital_asignado = monto_por_senal if monto_por_senal is not None else capital_total * (pct_por_senal / 100)
            liquidada = ret_apalancado <= -100
            ret_apalancado = max(ret_apalancado, -100)
            pnl_usd = capital_asignado * (ret_apalancado / 100)
            capital_final = capital_asignado + pnl_usd

        fila = {
            "Fecha": s.get("fecha"), "Ticker": s.get("ticker"), "Categoría": cat, "Tipo": s.get("tipo"),
            "Estado": "💀 LIQUIDADA" if liquidada else estado,
            "Apalanc.": f"{s.get('apalancamiento',1):.0f}x",
        }
        fila.update(extra_cols)
        fila.update({
            "Ret. Precio %": round(ret_precio, 2),
            "Ret. Apalancado %": round(ret_apalancado, 2),
            "Capital Asignado": round(capital_asignado, 2),
            "P&L (USD)": round(pnl_usd, 2),
            "Capital Final": round(capital_final, 2),
        })
        filas_sim.append(fila)

    if not filas_sim:
        st.info("No se pudo simular ninguna señal (faltan precios de referencia).")
        return

    df_sim = pd.DataFrame(filas_sim)

    capital_asignado_total = df_sim["Capital Asignado"].sum()
    pnl_total = df_sim["P&L (USD)"].sum()
    n_ganadoras = int((df_sim["P&L (USD)"] > 0).sum())
    n_total_sim = len(df_sim)
    winrate_sim = (n_ganadoras / n_total_sim * 100) if n_total_sim else 0

    label_capital = "Margen total usado" if modo == "📦 Por lotes (tamaño de posición)" else "Capital asignado total"

    k1, k2, k3, k4 = st.columns(4)
    with k1: st.metric(label_capital, f"USD {capital_asignado_total:,.2f}")
    with k2: st.metric("P&L total", f"USD {pnl_total:+,.2f}",
                        delta=f"{(pnl_total/capital_asignado_total*100):+.1f}%" if capital_asignado_total else None)
    with k3: st.metric("Operaciones ganadoras", f"{n_ganadoras}/{n_total_sim}")
    with k4: st.metric("Win Rate simulado", f"{winrate_sim:.1f}%")

    if modo == "📦 Por lotes (tamaño de posición)" and capital_asignado_total > capital_total:
        st.warning(
            f"⚠️ El margen total requerido (USD {capital_asignado_total:,.2f}) supera tu "
            f"capital declarado (USD {capital_total:,.2f}). Con este tamaño de lote estarías "
            "sobre-apalancado si abrieras todas estas operaciones a la vez."
        )

    def _color_pnl(val):
        try:
            v = float(val)
            return "color:#3fb950;font-weight:700" if v >= 0 else "color:#f85149;font-weight:700"
        except:
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

    mejor = df_sim.loc[df_sim["P&L (USD)"].idxmax()] if not df_sim.empty else None
    peor = df_sim.loc[df_sim["P&L (USD)"].idxmin()] if not df_sim.empty else None
    if mejor is not None and peor is not None:
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

    st.caption("⚠️ Simulación educativa. No contempla comisiones, spread, financiamiento por apalancamiento, "
               "swap ni slippage. Cuando TP y SL se tocan el mismo día se asume el peor caso (SL). En el modo "
               "por lotes, las 'unidades por lote' son configurables porque varían según el bróker: verificá "
               "las especificaciones del contrato en el tuyo antes de usarlas como referencia real. No "
               "constituye asesoramiento financiero.")


# ==============================================================
#  ENTRY POINT — llamar desde app.py
# ==============================================================

def render_senales_trading(supabase, user_id, user_email):
    """Uso desde app.py:
        from modulo_senales_trading import render_senales_trading
        render_senales_trading(supabase, USER_ID, st.session_state['usuario'].email)

    NOTA DE MIGRACIÓN: si tu tabla en Supabase todavía no tiene la
    columna "categoria", corré en el SQL editor:
        ALTER TABLE senales_trading
        ADD COLUMN IF NOT EXISTS categoria text DEFAULT '🔹 Otro';
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
        Señales publicadas con fecha, hora, stop loss, take profit, categoría y apalancamiento —
        evaluación automática de aciertos/desaciertos y simulador de capital (por monto, % o
        lotes) para cualquier usuario.
      </div>
    </div>
    """, unsafe_allow_html=True)

    tab_pub, tab_hist, tab_sim = st.tabs(["📢 Publicar Señal", "📋 Señales y Resultados", "🧮 Simulador de Capital"])
    with tab_pub:
        _tab_publicar(supabase, user_id, user_email, es_admin)
    with tab_hist:
        _tab_senales(supabase, es_admin)
    with tab_sim:
        _tab_simulador(supabase)
