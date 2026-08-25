# ==============================================================
#  MÓDULO SEÑALES DE TRADING — Streamlit + Supabase
#  Mismo patrón que modulo_calendario.py: solo ADMIN_EMAIL publica
#  señales, todos los usuarios pueden verlas y simular resultados
#  con su propio capital. La protección real (a prueba de gente que
#  mire el código) está en las políticas RLS de Supabase — ver
#  senales_trading_schema.sql. El email de acá abajo tiene que
#  coincidir EXACTAMENTE con el de esas políticas.
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


def _es_admin(user_email):
    return bool(user_email) and user_email.strip().lower() == ADMIN_EMAIL.strip().lower()


# ==============================================================
#  ACCESO A SUPABASE
# ==============================================================

def _guardar_senal(supabase, datos, user_id, user_email):
    row = {
        "autor_id": user_id, "autor_email": user_email,
        "ticker": datos["ticker"].strip().upper(),
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

    c1, c2, c3 = st.columns(3)
    with c1:
        ticker = st.text_input("🎯 Ticker", key="sen_ticker", placeholder="Ej: NVDA, BTC-USD, EURUSD=X")
    with c2:
        tipo = st.selectbox("Tipo de operación", ["🟢 LARGO (Compra)", "🔴 CORTO (Venta)"], key="sen_tipo")
    with c3:
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
            datos = dict(ticker=ticker, tipo=tipo, fecha=fecha, hora=hora,
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

    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        tickers_u = ["Todos"] + sorted(df["ticker"].dropna().unique().tolist())
        f_tk = st.selectbox("Filtrar ticker", tickers_u, key="sen_hist_f_tk")
    with fc2:
        estados_u = ["Todos"] + sorted(df["estado"].dropna().unique().tolist())
        f_estado = st.selectbox("Filtrar estado", estados_u, key="sen_hist_f_estado")
    with fc3:
        tipos_u = ["Todos"] + sorted(df["tipo"].dropna().unique().tolist())
        f_tipo = st.selectbox("Filtrar tipo", tipos_u, key="sen_hist_f_tipo")

    df_f = df.copy()
    if f_tk != "Todos": df_f = df_f[df_f["ticker"] == f_tk]
    if f_estado != "Todos": df_f = df_f[df_f["estado"] == f_estado]
    if f_tipo != "Todos": df_f = df_f[df_f["tipo"] == f_tipo]

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

        titulo = f"{row.get('fecha','')} {row.get('hora','')} · {row.get('ticker','')} · {row.get('tipo','')}"
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
                    if st.button("🗑️ Eliminar señal", key=f"sen_btn_del_{row['id']}"):
                        _borrar_senal(supabase, row["id"])
                        _obtener_senales.clear()
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
            "Monto fijo por señal", "% del capital por señal",
        ], key="sim_modo")
    with c3:
        incluir_abiertas = st.checkbox("Incluir señales abiertas (P&L flotante)", value=True, key="sim_incluir_abiertas")

    if modo == "Monto fijo por señal":
        monto_por_senal = st.number_input("Monto por señal (USD)", min_value=10.0,
                                           value=min(100.0, capital_total), step=10.0, key="sim_monto_fijo")
    else:
        pct_por_senal = st.slider("% del capital por señal", 1, 100, 10, key="sim_pct")
        monto_por_senal = None

    df = pd.DataFrame(senales)
    if not incluir_abiertas:
        df = df[df["estado"] != "ABIERTA"]

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

        ret_precio, ret_apalancado = _calcular_retorno(s, precio_ref)
        capital_asignado = monto_por_senal if monto_por_senal is not None else capital_total * (pct_por_senal / 100)

        liquidada = ret_apalancado <= -100
        ret_apalancado_efectivo = max(ret_apalancado, -100)
        pnl_usd = capital_asignado * (ret_apalancado_efectivo / 100)
        capital_final = capital_asignado + pnl_usd

        filas_sim.append({
            "Fecha": s.get("fecha"), "Ticker": s.get("ticker"), "Tipo": s.get("tipo"),
            "Estado": "💀 LIQUIDADA" if liquidada else estado,
            "Apalanc.": f"{s.get('apalancamiento',1):.0f}x",
            "Ret. Precio %": round(ret_precio, 2),
            "Ret. Apalancado %": round(ret_apalancado_efectivo, 2),
            "Capital Asignado": round(capital_asignado, 2),
            "P&L (USD)": round(pnl_usd, 2),
            "Capital Final": round(capital_final, 2),
        })

    if not filas_sim:
        st.info("No se pudo simular ninguna señal (faltan precios de referencia).")
        return

    df_sim = pd.DataFrame(filas_sim)

    capital_asignado_total = df_sim["Capital Asignado"].sum()
    pnl_total = df_sim["P&L (USD)"].sum()
    n_ganadoras = int((df_sim["P&L (USD)"] > 0).sum())
    n_perdedoras = int((df_sim["P&L (USD)"] < 0).sum())
    n_total_sim = len(df_sim)
    winrate_sim = (n_ganadoras / n_total_sim * 100) if n_total_sim else 0

    k1, k2, k3, k4 = st.columns(4)
    with k1: st.metric("Capital asignado total", f"USD {capital_asignado_total:,.2f}")
    with k2: st.metric("P&L total", f"USD {pnl_total:+,.2f}",
                        delta=f"{(pnl_total/capital_asignado_total*100):+.1f}%" if capital_asignado_total else None)
    with k3: st.metric("Operaciones ganadoras", f"{n_ganadoras}/{n_total_sim}")
    with k4: st.metric("Win Rate simulado", f"{winrate_sim:.1f}%")

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

    _map = "map" if hasattr(df_sim.style, "map") else "applymap"
    styled = (df_sim.style
              .pipe(lambda s: getattr(s, _map)(_color_pnl, subset=["P&L (USD)", "Ret. Apalancado %"]))
              .pipe(lambda s: getattr(s, _map)(_color_estado_sim, subset=["Estado"]))
              .format({"Ret. Precio %": "{:+.2f}%", "Ret. Apalancado %": "{:+.2f}%",
                       "Capital Asignado": "${:,.2f}", "P&L (USD)": "${:+,.2f}",
                       "Capital Final": "${:,.2f}"})
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

    st.caption("⚠️ Simulación educativa. No contempla comisiones, spread, financiamiento por apalancamiento "
               "ni slippage. Cuando TP y SL se tocan el mismo día se asume el peor caso (SL). No constituye "
               "asesoramiento financiero.")


# ==============================================================
#  ENTRY POINT — llamar desde app.py
# ==============================================================

def render_senales_trading(supabase, user_id, user_email):
    """Uso desde app.py:
        from modulo_senales_trading import render_senales_trading
        render_senales_trading(supabase, USER_ID, st.session_state['usuario'].email)
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
        Señales publicadas con fecha, hora, stop loss, take profit y apalancamiento —
        evaluación automática de aciertos/desaciertos y simulador de capital para
        cualquier usuario.
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
