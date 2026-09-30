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

import altair as alt
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


def _m(v) -> str:
    return f"${v:,.0f}"


def _sel_nearest(campo: str):
    # Compatibilidad Altair 5 (selection_point) y Altair 4 (selection_single).
    if hasattr(alt, "selection_point"):
        sel = alt.selection_point(nearest=True, on="mouseover", fields=[campo], empty=False)
        return sel, (lambda ch: ch.add_params(sel))
    sel = alt.selection_single(nearest=True, on="mouseover", fields=[campo], empty="none")
    return sel, (lambda ch: ch.add_selection(sel))


def _grafico_lineas(df: pd.DataFrame, mapa: dict, alto: int = 320) -> None:
    """Líneas interactivas: al pasar el mouse, una regla vertical muestra todos los valores del año."""
    largo = df.melt(id_vars="anio", value_vars=list(mapa), var_name="k", value_name="monto")
    largo["serie"] = largo["k"].map(mapa)
    nearest, aplicar = _sel_nearest("anio")
    lineas = alt.Chart(largo).mark_line(strokeWidth=3).encode(
        x=alt.X("anio:Q", title="Años"), y=alt.Y("monto:Q", title="$"),
        color=alt.Color("serie:N", legend=alt.Legend(title=None, orient="bottom")),
    )
    base = alt.Chart(df)
    selector = aplicar(base.mark_point().encode(x="anio:Q", opacity=alt.value(0)))
    tips = [alt.Tooltip("anio:Q", title="Año")] + [
        alt.Tooltip(f"{k}:Q", title=t, format="$,.0f") for k, t in mapa.items()
    ]
    regla = base.mark_rule(color="#808495").encode(x="anio:Q", tooltip=tips).transform_filter(nearest)
    st.altair_chart(alt.layer(lineas, selector, regla).properties(height=alto), use_container_width=True)


def _interes_compuesto(client, user_id: str) -> None:
    st.markdown("###### 📈 El tiempo hace el trabajo pesado")
    c1, c2, c3, c4 = st.columns(4)
    capital = c1.number_input("Capital inicial ($)", min_value=0.0, value=1000.0, step=100.0, key="psi_ic_cap")
    aporte = c2.number_input("Aporte mensual ($)", min_value=0.0, value=200.0, step=50.0, key="psi_ic_aporte")
    tasa = c3.slider("Rendimiento anual %", 0.0, 30.0, 8.0, 0.5, key="psi_ic_tasa")
    anios = c4.slider("Años", 1, 50, 20, key="psi_ic_anios")
    infl = st.slider("Inflación anual % (para ver el valor real)", 0.0, 10.0, 3.0, 0.5, key="psi_ic_infl")

    df = psd.proyeccion_compuesta(capital, aporte, tasa, anios, infl)
    f = df.iloc[-1]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Valor final", _m(f["total"]))
    m2.metric("Lo que pusiste", _m(f["aportado"]))
    m3.metric("Generado por intereses", _m(f["intereses"]))
    m4.metric("Valor real (con inflación)", _m(f["total_real"]))

    _grafico_lineas(df, {"aportado": "Lo que pusiste", "total": "Valor nominal", "total_real": "Valor real"})

    cruce = df[(df["anio"] > 0) & (df["interes_anio"] > aporte * 12)]
    if aporte > 0 and not cruce.empty:
        st.info(f"⏳ Desde el **año {int(cruce.iloc[0]['anio'])}**, tu plata genera en un año más de lo que vos aportás "
                "en ese año. Los primeros años parecen lentos: ahí es donde la impaciencia hace abandonar.")
    if tasa > 0:
        st.caption(f"Regla del 72: a {tasa:.1f}% anual, tu capital se duplica cada ~{72 / tasa:.1f} años.")

    tabla = pd.DataFrame({
        "Escenario": ["Pesimista (−3 pp)", "Base", "Optimista (+3 pp)"],
        "Valor final": [
            psd.proyeccion_compuesta(capital, aporte, max(tasa + d, 0), anios)["total"].iloc[-1]
            for d in (-3, 0, 3)
        ],
    })
    st.dataframe(tabla, hide_index=True, use_container_width=True,
                 column_config={"Valor final": st.column_config.NumberColumn(format="$%.0f")})

    s = psd.salud_financiera(client, user_id)
    if s["ingresos"] > 0 and s["capacidad"] > 0:
        st.caption(f"💡 Tu capacidad de inversión mensual estimada hoy es ~{_m(s['capacidad'])}: probá ese valor como aporte.")


def _costo_esperar() -> None:
    st.markdown("###### ⏳ ¿Cuánto cuesta esperar 'el momento perfecto'?")
    c1, c2, c3, c4 = st.columns(4)
    capital = c1.number_input("Capital inicial ($)", min_value=0.0, value=1000.0, step=100.0, key="psi_ce_cap")
    aporte = c2.number_input("Aporte mensual ($)", min_value=0.0, value=200.0, step=50.0, key="psi_ce_aporte")
    tasa = c3.slider("Rendimiento anual %", 0.0, 30.0, 8.0, 0.5, key="psi_ce_tasa")
    anios = c4.slider("Horizonte (años)", 5, 50, 25, key="psi_ce_anios")
    espera = st.slider("Si esperás (años) antes de empezar", 1, anios - 1, min(5, anios - 1), key="psi_ce_espera")

    df = psd.costo_de_esperar(capital, aporte, tasa, anios, espera)
    hoy_final, tarde_final = float(df["empezar_hoy"].iloc[-1]), float(df["esperar"].iloc[-1])
    m1, m2, m3 = st.columns(3)
    m1.metric("Empezando hoy", _m(hoy_final))
    m2.metric(f"Empezando en {espera} años", _m(tarde_final))
    m3.metric("Costo de esperar", _m(hoy_final - tarde_final))
    _grafico_lineas(df, {"empezar_hoy": "Empezar hoy", "esperar": f"Esperar {espera} años"})
    st.info("No esperás 'una mejor entrada': esperás perder los años de capitalización, que son los más valiosos. "
            "Si te cuesta decidir, empezá con un monto chico y constante: el hábito importa más que el timing.")


def _volatilidad() -> None:
    st.markdown("###### 🌫️ La proyección real no es una línea recta")
    c1, c2, c3 = st.columns(3)
    capital = c1.number_input("Capital inicial ($)", min_value=0.0, value=1000.0, step=100.0, key="psi_mc_cap")
    aporte = c2.number_input("Aporte mensual ($)", min_value=0.0, value=200.0, step=50.0, key="psi_mc_aporte")
    anios = c3.slider("Años", 5, 40, 20, key="psi_mc_anios")
    c1, c2 = st.columns(2)
    mu = c1.slider("Rendimiento anual esperado %", 0.0, 20.0, 8.0, 0.5, key="psi_mc_mu")
    sigma = c2.slider("Volatilidad anual %", 1.0, 40.0, 15.0, 1.0, key="psi_mc_sigma")

    df, p_perd, p_neg = psd.montecarlo_proyeccion(capital, aporte, mu, sigma, anios)
    f = df.iloc[-1]
    m1, m2, m3 = st.columns(3)
    m1.metric("Caso pesimista (10%)", _m(f["p10"]))
    m2.metric("Caso mediano", _m(f["p50"]))
    m3.metric("Caso optimista (90%)", _m(f["p90"]))
    _grafico_lineas(df, {"p10": "Pesimista (p10)", "p50": "Mediana", "p90": "Optimista (p90)"})
    st.warning(f"En {p_neg * 100:.0f}% de los años el resultado es negativo: es normal, no una señal para salir. "
               f"Aun así, solo en {p_perd * 100:.1f}% de los escenarios terminás por debajo de lo que aportaste.")
    st.caption("Simulación con 1000 trayectorias y rendimientos anuales aleatorios (distribución normal). "
               "Es una ilustración, no una predicción.")


def _render_dinero(client, user_id: str) -> None:
    vista = st.radio(
        "", ["📚 Sesgos", "📈 Interés compuesto", "⏳ Costo de esperar", "🌫️ Volatilidad",
             "🎲 Apuestas", "📉 Recuperación", "🔥 Rachas", "🪞 Efecto disposición"],
        horizontal=True, label_visibility="collapsed", key="psi_din_vista",
    )
    if vista == "📚 Sesgos":
        _sesgos()
    elif vista == "📈 Interés compuesto":
        _interes_compuesto(client, user_id)
    elif vista == "⏳ Costo de esperar":
        _costo_esperar()
    elif vista == "🌫️ Volatilidad":
        _volatilidad()
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


def _msg_nivel(nivel: str, texto: str) -> None:
    {"success": st.success, "warning": st.warning, "error": st.error}.get(nivel, st.info)(texto)


def mostrar_impacto_gasto(client, user_id: str, monto: float, fecha_iso: str) -> None:
    """Aviso de impacto tras registrar un gasto (se llama desde finanzas_ui)."""
    try:
        r = psd.impacto_gasto(client, user_id, float(monto), fecha_iso)
        _msg_nivel(r["nivel"], f"🧠 Impacto: {r['mensaje']}")
    except Exception:
        pass


def mostrar_impacto_deuda(client, user_id: str, cuota_mensual: float, monto_pendiente: float) -> None:
    """Aviso de impacto tras registrar una deuda (se llama desde finanzas_ui)."""
    try:
        r = psd.impacto_deuda(client, user_id, float(cuota_mensual or 0), float(monto_pendiente or 0))
        _msg_nivel(r["nivel"], f"🧠 Impacto: {r['mensaje']}")
    except Exception:
        pass


def _salud_financiera(client, user_id: str) -> None:
    st.markdown("###### ❤️ Indicadores de salud financiera (promedio de los últimos 3 meses)")
    s = psd.salud_financiera(client, user_id)
    if s["ingresos"] <= 0:
        st.info("Cargá ingresos y gastos de los últimos meses para calcular tus indicadores.")
        return
    etiqueta = {"success": "🟢 Sana", "warning": "🟡 En alerta", "error": "🔴 Tensionada"}[s["nivel"]]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Salud financiera", f"{s['score']:.0f}/100", etiqueta, delta_color="off")
    c2.metric("Carga de deuda", f"{s['dti'] * 100:.1f}%", "sana ≤ 30%", delta_color="off")
    c3.metric("Tasa de ahorro", f"{s['ahorro'] * 100:.1f}%", "meta ≥ 20%", delta_color="off")
    c4.metric("Autonomía", "—" if s["meses_autonomia"] is None else f"{s['meses_autonomia']:.1f} meses", "meta ≥ 3", delta_color="off")
    st.progress(min(s["score"] / 100, 1.0))

    c1, c2, c3 = st.columns(3)
    c1.metric("Capacidad de inversión mensual", _m(s["capacidad"]))
    c2.metric("Cuotas de deuda por mes", _m(s["cuotas"]))
    c3.metric("Deuda pendiente total", _m(s["deuda_total"]))
    st.bar_chart(pd.Series(s["componentes"]), height=200)
    st.caption("Puntaje = carga de deuda (35%) + ahorro (30%) + gasto/ingreso (20%) + ausencia de mora (15%). "
               "La capacidad de inversión descuenta gastos de vida y cuotas.")

    if s["dti"] > 0.30:
        st.warning(f"Tus cuotas se llevan el {s['dti'] * 100:.0f}% del ingreso. Con esa carga cada decisión se toma bajo presión, "
                   "y la presión es lo que empuja a operar para 'zafar'. Atacá primero la deuda más cara.")
    if s["ahorro"] < 0.10:
        st.warning("Ahorrás menos del 10%: automatizá un aporte el día que cobrás, antes de poder gastarlo.")
    if s["meses_autonomia"] is not None and s["meses_autonomia"] < 3:
        st.warning("Tu liquidez cubre menos de 3 meses: sin colchón, una mala racha te obliga a vender en el peor momento.")
    if s["en_mora"]:
        st.error(f"Tenés {s['en_mora']} deuda(s) en mora: es la prioridad antes de invertir.")
    if s["nivel"] == "success":
        st.success("Tus números dan margen para decidir con calma. Cuidá que siga así.")


def _test_estres(client, user_id: str) -> None:
    st.markdown("###### 🧪 Test de estrés financiero")
    st.caption("¿Qué pasa con tu capacidad de invertir si las cosas salen mal?")
    s = psd.salud_financiera(client, user_id)
    if s["ingresos"] <= 0:
        st.info("Cargá ingresos y gastos de los últimos meses para correr el test.")
        return
    c1, c2, c3 = st.columns(3)
    caida = c1.slider("Caída de ingresos %", 0, 60, 20, key="psi_est_caida")
    suba = c2.slider("Suba de cuotas %", 0, 100, 25, key="psi_est_suba")
    extra = c3.number_input("Gasto imprevisto mensual ($)", min_value=0.0, value=0.0, step=50.0, key="psi_est_extra")

    e = psd.test_estres(s, caida, suba, extra)
    base = psd.test_estres(s, 0, 0, 0)
    tabla = pd.DataFrame({
        "Indicador": ["Ingresos", "Cuotas", "Capacidad de inversión", "Carga de deuda", "Autonomía (meses)"],
        "Hoy": [base["ingresos"], base["cuotas"], base["capacidad"], (base["dti"] or 0) * 100, base["meses_autonomia"]],
        "Escenario": [e["ingresos"], e["cuotas"], e["capacidad"], (e["dti"] or 0) * 100, e["meses_autonomia"]],
    })
    st.dataframe(tabla, hide_index=True, use_container_width=True, column_config={
        "Hoy": st.column_config.NumberColumn(format="%.1f"),
        "Escenario": st.column_config.NumberColumn(format="%.1f"),
    })
    if base["pct_absorbido"] is not None:
        st.metric("Parte de tu dinero libre que hoy se come la deuda", f"{base['pct_absorbido'] * 100:.0f}%")
    textos = {
        "error": "🔴 En este escenario no te alcanza: tu capacidad de inversión pasa a negativo. La deuda te dejaría sin margen y con presión para tomar decisiones apuradas.",
        "warning": "🟡 Aguantás, pero casi sin margen para invertir. Bajá cuotas o armá colchón antes de asumir más riesgo.",
        "success": "🟢 Aun bajo este escenario conservás capacidad de inversión. Buen margen de seguridad.",
    }
    _msg_nivel(e["nivel"], textos[e["nivel"]])


def _render_financiera(client, user_id: str) -> None:
    vista = st.radio(
        "", ["❤️ Salud financiera", "🧪 Test de estrés", "🧾 Hábitos", "🐑 Test de FOMO"],
        horizontal=True, label_visibility="collapsed", key="psi_fin_vista",
    )
    if vista == "❤️ Salud financiera":
        _salud_financiera(client, user_id)
    elif vista == "🧪 Test de estrés":
        _test_estres(client, user_id)
    elif vista == "🧾 Hábitos":
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


def _mostrar_alertas_control(ctl: dict, cfg: dict) -> None:
    c1, c2, c3 = st.columns(3)
    c1.metric("Operaciones hoy", f"{ctl['ops_hoy']} / {int(cfg['max_ops_dia'])}")
    racha = "—" if not ctl["racha_tipo"] else f"{ctl['racha_n']} {ctl['racha_tipo']}"
    c2.metric("Racha actual", racha)
    c3.metric("P&L realizado hoy", f"${ctl['pnl_hoy']:,.2f}")
    if not ctl["alertas"]:
        st.success("Sin alertas: estás dentro de tus límites.")
    for nivel, msg in ctl["alertas"]:
        _msg_nivel(nivel, msg)


def _limites(client, user_id: str, cfg: dict, prefijo: str) -> dict:
    # (checkbox y no expander: este panel ya se muestra dentro de un expander en Trading)
    if not st.checkbox("⚙️ Editar mis límites anti-overtrading", key=f"{prefijo}_lim_toggle"):
        return cfg
    c1, c2, c3, c4 = st.columns(4)
    nuevo = {
        "max_ops_dia": c1.number_input("Máx. operaciones por día", 1, 50, int(cfg["max_ops_dia"]), key=f"{prefijo}_lim_ops"),
        "max_perdidas_seguidas": c2.number_input("Pausa tras N pérdidas seguidas", 1, 20, int(cfg["max_perdidas_seguidas"]), key=f"{prefijo}_lim_per"),
        "max_ganancias_seguidas": c3.number_input("Aviso tras N ganancias seguidas", 1, 20, int(cfg["max_ganancias_seguidas"]), key=f"{prefijo}_lim_gan"),
        "perdida_diaria_max": c4.number_input("Pérdida diaria máx. ($, 0 = sin límite)", 0.0, value=float(cfg["perdida_diaria_max"]), step=10.0, key=f"{prefijo}_lim_usd"),
    }
    if st.button("💾 Guardar límites", key=f"{prefijo}_lim_btn"):
        r = psd.guardar_config(client, user_id, {k: (int(v) if k != "perdida_diaria_max" else float(v)) for k, v in nuevo.items()})
        _flash(r["ok"], r["mensaje"])
        st.rerun()
    return nuevo


def _preoperativo(client, user_id: str, prefijo: str = "psi") -> None:
    st.markdown("###### 🧭 Check-in pre-operativo")
    _mostrar_flash()
    cfg = psd.obtener_config(client, user_id)
    cfg = _limites(client, user_id, cfg, prefijo)

    estado = st.radio(
        "¿Cómo estás AHORA, antes de operar?", list(psd.ESTADOS_PREOP), horizontal=True,
        format_func=lambda e: f"{psd.ESTADOS_PREOP[e][0]} {e}", key=f"{prefijo}_estado",
    )
    c1, c2 = st.columns(2)
    intensidad = c1.slider("Intensidad de la emoción", 1, 5, 3, key=f"{prefijo}_intens")
    simbolo = c2.text_input("Activo que estás mirando (opcional)", key=f"{prefijo}_simb")

    ctl = psd.estado_control(client, user_id, cfg, estado)
    st.markdown("**Control de overtrading**")
    _mostrar_alertas_control(ctl, cfg)

    st.markdown("**Checklist antes de entrar**")
    marcas = {c: st.checkbox(txt, key=f"{prefijo}_chk_{c}") for c, txt in psd.CHECKS_PRE}
    checks_ok = all(marcas.values())
    decision = psd.decision_preop(ctl["nivel"], checks_ok)
    _msg_nivel(
        {"Operar": "success", "Operar con tamaño reducido": "warning"}.get(decision, "error" if decision == "Esperar" else "warning"),
        f"**Decisión sugerida: {decision}**",
    )
    nota = st.text_input("Nota (opcional)", key=f"{prefijo}_nota")
    if st.button("💾 Guardar check-in", key=f"{prefijo}_guardar"):
        r = psd.insertar_preop(client, user_id, {
            "estado": estado, "intensidad": intensidad, "simbolo": simbolo, "decision": decision,
            "checks_ok": checks_ok, "semaforo": ctl["nivel"], "nota": nota,
        })
        _flash(r["ok"], r["mensaje"])
        st.rerun()

    hist = psd.listar_preop(client, user_id)
    if not hist.empty:
        st.markdown("###### Tus últimos check-ins")
        st.bar_chart(hist["estado"].value_counts(), height=180)
        st.dataframe(hist[["fecha", "estado", "intensidad", "simbolo", "decision", "checks_ok"]].head(10),
                     use_container_width=True, hide_index=True)
        fuera = hist[hist["estado"] != "Calma"]
        st.caption(f"Empezaste a operar sin estar en calma en {len(fuera)} de {len(hist)} check-ins.")


def render_panel_pretrading(client, user_id: str) -> None:
    """Semáforo compacto + check-in completo. Se muestra arriba del formulario de Trading."""
    try:
        cfg = psd.obtener_config(client, user_id)
        ctl = psd.estado_control(client, user_id, cfg)
        titulo = {"success": "🟢 Luz verde para operar", "warning": "🟡 Precaución", "error": "🔴 Pausa recomendada"}[ctl["nivel"]]
        _msg_nivel(ctl["nivel"], f"🧠 {titulo} · {ctl['ops_hoy']}/{int(cfg['max_ops_dia'])} operaciones hoy"
                   + (f" · racha: {ctl['racha_n']} {ctl['racha_tipo']}" if ctl["racha_tipo"] else ""))
        with st.expander("🧭 Check-in pre-operativo y control anti-overtrading"):
            _preoperativo(client, user_id, prefijo="trd")
    except Exception:
        pass


def _render_psicotrading(client, user_id: str, tabla_editable) -> None:
    vista = st.radio(
        "", ["🧭 Pre-operativo y control", "📓 Diario emocional", "✅ Disciplina"],
        horizontal=True, label_visibility="collapsed", key="psi_trd_vista",
    )
    if vista == "🧭 Pre-operativo y control":
        _preoperativo(client, user_id, prefijo="psi")
    elif vista == "📓 Diario emocional":
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
