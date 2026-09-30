# ============================================================
# psicologia_ui.py
# Pestaña "🧠 Psicología" del sistema de Finanzas Personales.
#
#     import psicologia_ui as psi
#     psi.render_psicologia(client, user_id, _tabla_editable)
#
# Recibe _tabla_editable de finanzas_ui por parámetro para evitar
# imports circulares (finanzas_ui importa este módulo).
# ============================================================

from datetime import date

import pandas as pd
import streamlit as st

import finanzas_data as fd
import psicologia_data as psd

OPCIONES_EDICION = psd.OPCIONES_EDICION


def _flash(ok: bool, msg: str) -> None:
    st.session_state["_psi_flash"] = (ok, msg)


def _mostrar_flash() -> None:
    f = st.session_state.pop("_psi_flash", None)
    if f:
        (st.success if f[0] else st.error)(f[1])


# ============================================================
# 1) PSICOLOGÍA DEL DINERO — sesgos + simulaciones
# ============================================================

SESGOS = [
    ("😖 Aversión a la pérdida",
     "Una pérdida duele ~2 veces más de lo que una ganancia equivalente alegra.",
     "Cortás ganancias rápido por miedo a devolverlas y dejás correr las pérdidas esperando que vuelva.",
     "Definí stop y objetivo ANTES de entrar. Medí el resultado en series de 20+ operaciones, no una por una."),
    ("🪤 Efecto disposición",
     "Tendencia a vender ganadoras demasiado pronto y aguantar perdedoras demasiado tiempo.",
     "Tus ganadoras duran días y tus perdedoras semanas (mirá la pestaña 'Tu efecto disposición').",
     "Regla de tiempo: si la tesis se invalidó, se sale, sin importar cuánto pierda."),
    ("⚓ Anclaje",
     "Te aferrás al primer número que viste (tu precio de compra, un máximo previo).",
     "'No vendo hasta recuperar lo que pagué'. Al mercado no le importa tu precio de entrada.",
     "Preguntate: 'Si hoy tuviera el efectivo, ¿compraría esto a este precio?'"),
    ("🔍 Sesgo de confirmación",
     "Buscás información que confirma lo que ya pensás e ignorás la que lo contradice.",
     "Seguís solo cuentas que piensan como vos y descartás el gráfico que te contradice.",
     "Escribí el caso en contra de tu operación antes de entrar. Si no podés, no entiendes el riesgo."),
    ("🦚 Exceso de confianza",
     "Después de una racha ganadora sobreestimás tu habilidad y subís el riesgo.",
     "Tras 4 ganadoras seguidas aumentás tamaño y aparece la pérdida grande.",
     "Riesgo fijo por operación (% del capital), que NO cambia por cómo te sentís."),
    ("🕳️ Costo hundido",
     "Seguís invirtiendo en algo por lo ya gastado, no por lo que viene.",
     "Promediás a la baja para 'mejorar el precio' de una posición que ya falló.",
     "Cada decisión se evalúa solo con lo que puede pasar de ahora en adelante."),
    ("🐑 Efecto manada (FOMO)",
     "Copiar lo que hace la mayoría por miedo a quedar afuera.",
     "Comprás después de una suba fuerte porque 'todos están ganando'.",
     "Hacé el test de FOMO (Psicología Financiera) y poné un máximo de operaciones por día."),
]


def _sesgos() -> None:
    st.caption("Conocer el sesgo no alcanza: cada uno tiene su señal en tu operatoria y su antídoto concreto.")
    for nombre, que, senal, antidoto in SESGOS:
        with st.expander(nombre):
            st.markdown(f"**Qué es:** {que}")
            st.markdown(f"**Cómo se ve en la práctica:** {senal}")
            st.markdown(f"**Antídoto:** {antidoto}")


def _sim_apuestas() -> None:
    st.markdown("###### 🎲 ¿Aceptarías esta apuesta… muchas veces?")
    c1, c2, c3, c4 = st.columns(4)
    g = c1.number_input("Ganás ($)", min_value=1.0, value=150.0, step=10.0, key="sim_g")
    p = c2.number_input("Perdés ($)", min_value=1.0, value=100.0, step=10.0, key="sim_p")
    prob = c3.slider("Prob. de ganar %", 5, 95, 50, key="sim_prob") / 100
    n = c4.slider("Nº de operaciones", 10, 500, 100, key="sim_n")

    ev = prob * g - (1 - prob) * p
    res = psd.simular_resultado(g, p, prob, n, seed=42)
    m1, m2, m3 = st.columns(3)
    m1.metric("Esperanza por operación", f"${ev:,.2f}")
    m2.metric("Escenarios con ganancia", f"{(res > 0).mean() * 100:.0f}%")
    m3.metric("Peor 5% de escenarios", f"${pd.Series(res).quantile(0.05):,.0f}")
    st.bar_chart(pd.Series(res).round(-1).value_counts().sort_index(), height=220)
    if ev > 0:
        st.info("Esperanza positiva: una sola operación puede salir mal, pero la repetición juega a tu favor. "
                "El sesgo te hace rechazar (o abandonar) ventajas reales por el dolor de la pérdida individual.")
    else:
        st.warning("Esperanza negativa: aunque ganes seguido, en el largo plazo la matemática juega en contra.")


def _sim_recuperacion() -> None:
    st.markdown("###### 📉 Cuánto necesitás ganar para volver a cero")
    perdida = st.slider("Pérdida (drawdown) %", 1, 90, 30, key="rec_dd")
    st.metric("Ganancia necesaria para recuperar", f"+{psd.ganancia_para_recuperar(perdida):.1f}%")
    tabla = pd.DataFrame({"Pérdida %": [10, 20, 30, 40, 50, 60, 70, 80, 90]})
    tabla["Ganancia necesaria %"] = tabla["Pérdida %"].map(lambda x: round(psd.ganancia_para_recuperar(x), 1))
    st.dataframe(tabla, hide_index=True, use_container_width=True)
    st.caption("Perder 50% exige ganar 100%. Por eso proteger el capital pesa más que perseguir retornos: "
               "evitar la pérdida grande es la ventaja psicológica y matemática más barata.")


def _sim_rachas() -> None:
    st.markdown("###### 🔥 ¿Qué racha perdedora es normal?")
    c1, c2, c3 = st.columns(3)
    wr = c1.slider("Win rate %", 20, 80, 50, key="rach_wr") / 100
    n = c2.slider("Operaciones", 20, 500, 100, key="rach_n")
    k = c3.slider("Racha a evaluar (≥ k pérdidas seguidas)", 2, 15, 6, key="rach_k")
    rachas = pd.Series(psd.racha_perdedora_max(wr, n, seed=7))
    m1, m2, m3 = st.columns(3)
    m1.metric("Racha máxima típica (mediana)", int(rachas.median()))
    m2.metric("Racha en el 5% de peores casos", int(rachas.quantile(0.95)))
    m3.metric(f"Prob. de ≥ {k} pérdidas seguidas", f"{(rachas >= k).mean() * 100:.0f}%")
    st.caption("Si no sabés que estas rachas son normales, las vivís como 'mi sistema dejó de funcionar' "
               "y abandonás justo antes de que la estadística se acomode. Anotá tu racha esperada en tu plan.")


def _efecto_disposicion(client, user_id: str) -> None:
    st.markdown("###### 🪞 Tu efecto disposición (con tus operaciones cerradas)")
    r = psd.efecto_disposicion(client, user_id)
    if not r:
        st.caption("Necesitás al menos 5 operaciones de Trading cerradas (con ganadoras y perdedoras) para medirlo.")
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Días promedio ganadoras", f"{r['dias_gan']:.1f}")
    c2.metric("Días promedio perdedoras", f"{r['dias_per']:.1f}")
    c3.metric("P&L prom. ganadoras", f"${r['pnl_gan']:,.2f}")
    c4.metric("P&L prom. perdedoras", f"${r['pnl_per']:,.2f}")
    if r["dias_per"] > r["dias_gan"] * 1.5:
        st.error("⚠️ Aguantás las perdedoras bastante más que las ganadoras: señal de efecto disposición. "
                 "Probá una regla de salida por tiempo o por invalidación de la tesis.")
    elif r["dias_gan"] > r["dias_per"] * 1.5:
        st.success("Dejás correr las ganadoras más que las perdedoras: es el patrón sano.")
    else:
        st.info("Tiempos parecidos entre ganadoras y perdedoras: no se ve un sesgo marcado.")
    if abs(r["pnl_per"]) > r["pnl_gan"]:
        st.warning("Además, tu pérdida promedio es mayor que tu ganancia promedio: revisá stops y objetivos.")
    st.caption(f"Basado en {r['n']} operaciones cerradas ({r['n_gan']} ganadoras, {r['n_per']} perdedoras).")


def _render_dinero(client, user_id: str) -> None:
    vista = st.radio(
        "", ["📚 Sesgos", "🎲 Apuestas", "📉 Recuperación", "🔥 Rachas", "🪞 Tu efecto disposición"],
        horizontal=True, label_visibility="collapsed", key="psi_din_vista",
    )
    if vista == "📚 Sesgos":
        _sesgos()
    elif vista == "🎲 Apuestas":
        _sim_apuestas()
    elif vista == "📉 Recuperación":
        _sim_recuperacion()
    elif vista == "🔥 Rachas":
        _sim_rachas()
    else:
        _efecto_disposicion(client, user_id)


# ============================================================
# 2) PSICOLOGÍA FINANCIERA — hábitos + test FOMO
# ============================================================

def _preguntas_form(form_key: str, preguntas: list[str], prefijo: str) -> list[int]:
    resp = []
    for i, q in enumerate(preguntas):
        resp.append(st.select_slider(
            q, options=list(psd.ESCALA.keys()), value=3,
            format_func=lambda v: psd.ESCALA[v], key=f"{prefijo}_{i}",
        ))
    return resp


def _historial_test(client, user_id: str, tipo: str) -> pd.DataFrame:
    hist = psd.listar_tests(client, user_id, tipo)
    if not hist.empty:
        st.markdown("###### Evolución")
        st.line_chart(hist.set_index("fecha")["puntaje"], height=200)
    return hist


def _test_fomo(client, user_id: str) -> None:
    st.markdown("###### 🐑 Test de FOMO (8 preguntas)")
    st.caption("Respondé pensando en tus últimas operaciones/compras, no en cómo te gustaría ser.")
    with st.form("form_fomo"):
        resp = _preguntas_form("fomo", psd.TEST_FOMO, "fomo_q")
        enviado = st.form_submit_button("📊 Calcular y guardar")
    if enviado:
        p = psd.puntaje_fomo(resp)
        nivel, consejo = psd.nivel_fomo(p)
        r = psd.insertar_test(client, user_id, "fomo", p)
        st.metric("Nivel de FOMO", f"{p:.0f}/100 — {nivel}")
        st.info(consejo)
        if not r["ok"]:
            st.error(r["mensaje"])
    _historial_test(client, user_id, "fomo")


def _test_habitos(client, user_id: str) -> None:
    st.markdown("###### 🧾 Evaluación de hábitos financieros (12 preguntas)")
    with st.form("form_habitos"):
        respuestas = {}
        for dim, preguntas in psd.TEST_HABITOS.items():
            st.markdown(f"**{dim}**")
            respuestas[dim] = _preguntas_form("hab", preguntas, f"hab_{dim}")
        enviado = st.form_submit_button("📊 Calcular y guardar")
    if enviado:
        por_dim = psd.puntajes_habitos(respuestas)
        total = round(sum(por_dim.values()) / len(por_dim), 1)
        r = psd.insertar_test(client, user_id, "habitos", total, por_dim)
        st.metric("Puntaje global de hábitos", f"{total:.0f}/100")
        st.bar_chart(pd.Series(por_dim), height=220)
        debil = min(por_dim, key=por_dim.get)
        st.info(f"Tu punto más débil es **{debil}** ({por_dim[debil]:.0f}/100). {psd.CONSEJOS_HABITOS[debil]}")
        if not r["ok"]:
            st.error(r["mensaje"])
    hist = _historial_test(client, user_id, "habitos")
    if not hist.empty and isinstance(hist.iloc[-1].get("detalle"), dict):
        st.caption("Último resultado por dimensión:")
        st.bar_chart(pd.Series(hist.iloc[-1]["detalle"]), height=200)


def _render_financiera(client, user_id: str) -> None:
    vista = st.radio(
        "", ["🧾 Hábitos", "🐑 Test de FOMO"],
        horizontal=True, label_visibility="collapsed", key="psi_fin_vista",
    )
    if vista == "🧾 Hábitos":
        _test_habitos(client, user_id)
    else:
        _test_fomo(client, user_id)


# ============================================================
# 3) PSICOTRADING — diario emocional + disciplina
# ============================================================

def _diario(client, user_id: str, tabla_editable) -> None:
    st.markdown("###### 📓 Diario emocional")
    trades = fd.listar_trading(client, user_id)
    opciones_trade = {"— (sin vincular)": None}
    if not trades.empty:
        for _, t in trades.sort_values("fecha_entrada", ascending=False).head(50).iterrows():
            opciones_trade[f"{t['fecha_entrada']} · {t['simbolo']} · {t['direccion']} · {t['estado']} · #{int(t['id'])}"] = int(t["id"])

    with st.form("form_diario", clear_on_submit=True):
        c1, c2 = st.columns(2)
        fecha = c1.date_input("Fecha *", value=date.today())
        vinculo = c2.selectbox("Operación vinculada", list(opciones_trade.keys()))
        simbolo = st.text_input("Símbolo (si no vinculás operación)", placeholder="AAPL, BTC-USD…")
        c1, c2 = st.columns(2)
        antes = c1.selectbox("¿Cómo te sentías ANTES de entrar? *", psd.EMOCIONES_ANTES)
        despues = c2.selectbox("¿Y DESPUÉS?", [""] + psd.EMOCIONES_DESPUES)
        intensidad = st.slider("Intensidad de la emoción", 1, 5, 3)
        siguio = st.radio("¿Seguiste tu plan? *", ["Sí", "No"], horizontal=True) == "Sí"
        disparador = st.text_input("¿Qué disparó la emoción?", placeholder="Ej: vi una vela fuerte, perdí la anterior…")
        leccion = st.text_area("Lección / qué harías distinto")
        enviado = st.form_submit_button("📓 Guardar entrada")

    if enviado:
        r = psd.insertar_diario(client, user_id, {
            "fecha": fecha.isoformat(), "simbolo": simbolo, "trade_id": opciones_trade[vinculo],
            "emocion_antes": antes, "emocion_despues": despues, "intensidad": intensidad,
            "siguio_plan": siguio, "disparador": disparador, "leccion": leccion,
        })
        _flash(r["ok"], r["mensaje"])
        st.rerun()

    _mostrar_flash()

    g = psd.diario_vs_resultados(client, user_id)
    if not g.empty:
        st.markdown("###### 🔬 Qué emociones te cuestan plata")
        st.dataframe(
            g, use_container_width=True, hide_index=True,
            column_config={
                "emocion_antes": "Emoción previa", "entradas": "Entradas",
                "plan_pct": st.column_config.NumberColumn("Siguió el plan", format="%.0f%%"),
                "pnl_promedio": st.column_config.NumberColumn("P&L promedio", format="$%.2f"),
            },
        )
        st.caption("El P&L promedio solo cuenta entradas vinculadas a una operación cerrada.")

    df = psd.listar_diario(client, user_id)
    if not df.empty:
        st.markdown("###### Tus entradas (editar / eliminar)")
        tabla_editable(
            client, user_id, "psico_diario", df.sort_values("fecha", ascending=False),
            psd.actualizar_diario, psd.eliminar_diario,
            label_fn=lambda r: f"{r['fecha']} · {r['emocion_antes']} · {'plan ✔' if r['siguio_plan'] else 'fuera de plan'}",
            solo_lectura=("trade_id",),
        )


def _disciplina(client, user_id: str) -> None:
    st.markdown("###### ✅ Checklist de disciplina del día")
    fecha = st.date_input("Día", value=date.today(), key="disc_fecha")
    with st.form("form_disciplina"):
        checks = {c: st.checkbox(txt, key=f"disc_{c}") for c, txt in psd.REGLAS}
        notas = st.text_input("Notas del día")
        enviado = st.form_submit_button("💾 Guardar día")
    if enviado:
        r = psd.guardar_disciplina(client, user_id, fecha.isoformat(), checks, notas)
        _flash(r["ok"], r["mensaje"])
        st.rerun()
    _mostrar_flash()

    df = psd.listar_disciplina(client, user_id)
    if df.empty:
        st.caption("Todavía no registraste ningún día.")
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("Racha de días disciplinados (≥80%)", psd.racha_disciplina(df))
    c2.metric("Disciplina promedio (últimos 30)", f"{df.head(30)['puntaje'].mean():.0f}%")
    c3.metric("Días registrados", len(df))
    graf = df.head(60).copy()
    graf["fecha"] = pd.to_datetime(graf["fecha"])
    st.line_chart(graf.set_index("fecha")["puntaje"].sort_index(), height=200)
    st.caption("Para corregir un día, volvé a guardarlo con la misma fecha.")
    cols = ["fecha", "puntaje"] + [c for c, _ in psd.REGLAS] + ["notas"]
    st.dataframe(df[cols], use_container_width=True, hide_index=True)


def _render_psicotrading(client, user_id: str, tabla_editable) -> None:
    vista = st.radio(
        "", ["📓 Diario emocional", "✅ Disciplina"],
        horizontal=True, label_visibility="collapsed", key="psi_trd_vista",
    )
    if vista == "📓 Diario emocional":
        _diario(client, user_id, tabla_editable)
    else:
        _disciplina(client, user_id)


# ============================================================
# ENTRYPOINT
# ============================================================

SUBSECCIONES = {
    "💰 Psicología del Dinero": "dinero",
    "🧾 Psicología Financiera": "financiera",
    "🎯 Psicotrading": "psicotrading",
}


def render_psicologia(client, user_id: str, tabla_editable) -> None:
    st.subheader("🧠 Psicología (Mindset)")
    sub = st.radio(
        "Sección de psicología", list(SUBSECCIONES.keys()),
        horizontal=True, label_visibility="collapsed", key="psi_sub",
    )
    st.divider()
    clave = SUBSECCIONES[sub]
    if clave == "dinero":
        _render_dinero(client, user_id)
    elif clave == "financiera":
        _render_financiera(client, user_id)
    else:
        _render_psicotrading(client, user_id, tabla_editable)
