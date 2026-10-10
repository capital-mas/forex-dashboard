# ==============================================================
#  SCANNER GEX — para la pestaña "Publicar Señal" (modulo_senales_trading.py)
#  Escanea una lista de tickers (~40) con los datos de modulo_gex (CBOE / Deribit)
#  y muestra un panel con filtros: régimen de gamma, distancia al punto de cambio,
#  Squeeze Score, dirección y niveles (resistencias, soportes, pivote, paredes).
#
#  Reutiliza las funciones de modulo_gex.py (mismo cálculo, misma caché de 5 min),
#  así que los números coinciden con los de la pestaña GEX.
#
#  Uso desde modulo_senales_trading.py:
#       from scanner_gex import render_scanner_gex
#       render_scanner_gex(on_cargar=_cargar_desde_scanner)
# ==============================================================

import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

import modulo_gex as gx

TZ_AR = ZoneInfo("America/Argentina/Buenos_Aires")

CLAVE_RES = "sen_scan_res"          # resultados del último escaneo (en session_state)
MAX_TICKERS = 60

LISTA_EJEMPLO = ("SPY, QQQ, IWM, NVDA, TSLA, AAPL, MSFT, AMZN, META, GOOGL, AMD, "
                 "MELI, GGAL, GLD, SLV, USO, TLT, BTC, ETH")

DIR_TXT = {1: "⬆️ Alcista", -1: "⬇️ Bajista", 0: "↔️ Neutra"}


# ==============================================================
#  UTILIDADES
# ==============================================================

def _parsear_lista(txt, maximo=MAX_TICKERS):
    """Separa por coma, espacio, salto de línea o punto y coma. Quita duplicados."""
    toks = [t.strip().upper() for t in re.split(r"[,\s;]+", txt or "") if t.strip()]
    vistos, out = set(), []
    for t in toks:
        if t not in vistos:
            vistos.add(t)
            out.append(t)
    return out[:maximo]


def _ticker_para_senal(entrada, simbolo):
    """Ticker en formato Yahoo (el que usa la evaluación automática de TP/SL de las señales)."""
    if simbolo in gx.CRIPTOS_DERIBIT:
        return f"{simbolo}-USD"
    if simbolo in gx.INDICES_CBOE:
        return f"^{simbolo}"
    return entrada.strip().upper()


def _categoria_sugerida(simbolo):
    if simbolo in gx.CRIPTOS_DERIBIT:
        return "₿ Cripto"
    if simbolo in gx.INDICES_CBOE:
        return "📊 Índice"
    return "📈 Acción"


# ==============================================================
#  ANÁLISIS DE UN TICKER
# ==============================================================

def analizar_ticker(entrada, n_vtos, rango_pct, r, q):
    """Devuelve un dict con régimen de gamma, niveles y squeeze score. Lanza excepción si falla."""
    simbolo_cboe, simbolo, _aviso = gx.resolver_simbolo(entrada)
    es_cripto = simbolo_cboe.startswith("DERIBIT:")
    mult = 1 if es_cripto else 100

    datos = gx._gex_descargar(simbolo_cboe)              # caché de 5 min
    S = datos["spot"]
    df, diag = gx.preparar_cadena(datos["df"], n_vtos)
    if df is None:
        raise LookupError(diag["motivo"] or "Sin cadena utilizable.")
    df, _ = gx.reparar_delta(df, S, r, q)

    rango = rango_pct / 100
    piv = gx.calcular_gex_por_strike(df, S, r, q, mult, rango)
    if piv.empty:
        raise LookupError("Sin strikes con interés abierto cerca del precio.")
    grid, total = gx.gex_total_vs_spot(df, S, r, q, mult)
    z = gx.calcular_zonas_gex(piv, grid, total, S)
    niv = gx.calcular_niveles_clasificados(piv, S, n=3)

    piv_d = gx.calcular_dex_por_strike(df, S, mult, rango)
    _, tot_pc = gx.calcular_put_call(gx._subset_vtos(datos["df"], n_vtos))
    res_v, _ = gx.calcular_gex_por_vto(df, S, r, q, mult, rango)
    sq = gx.calcular_squeeze_score(piv, piv_d, tot_pc, z, S, res_v)

    res = niv[niv["tipo"] == "Resistencia"]
    sop = niv[niv["tipo"] == "Soporte"]
    pvt = niv[niv["tipo"] == "Pivote"]

    res_p = float(res.sort_values("calls", ascending=False).iloc[0]["strike"]) if not res.empty else np.nan
    sop_p = float(sop.sort_values("puts", ascending=False).iloc[0]["strike"]) if not sop.empty else np.nan
    pvt_p = float(pvt.assign(_a=pvt["dist_pct"].abs()).sort_values("_a").iloc[0]["strike"]) if not pvt.empty else np.nan

    # Niveles sugeridos para SL/TP: principal de cada lado; si no hay, la pared (solo si está del lado correcto)
    cw, pw = z["call_wall"], z["put_wall"]
    nivel_sup = res_p if not np.isnan(res_p) else (cw if cw and cw > S else np.nan)
    nivel_inf = sop_p if not np.isnan(sop_p) else (pw if pw and pw < S else np.nan)

    flip = z["flip"]
    dist_flip = (S / flip - 1) * 100 if flip else np.nan

    tot_oi = float(df["openInterest"].sum())

    return {
        "ticker": simbolo,
        "entrada": entrada,
        "ticker_yahoo": _ticker_para_senal(entrada, simbolo),
        "categoria": _categoria_sugerida(simbolo),
        "fuente": datos.get("fuente", "CBOE"),
        "precio": float(S),
        "regimen": z["regimen"],
        "gex_total": float(z["gex_total"]) / 1e6,
        "flip": flip if flip else np.nan,
        "dist_flip": dist_flip,
        "call_wall": cw if cw else np.nan,
        "put_wall": pw if pw else np.nan,
        "res_principal": res_p,
        "sop_principal": sop_p,
        "pivote": pvt_p,
        "nivel_sup": nivel_sup,
        "nivel_inf": nivel_inf,
        "dist_res": (res_p / S - 1) * 100 if not np.isnan(res_p) else np.nan,
        "dist_sop": (sop_p / S - 1) * 100 if not np.isnan(sop_p) else np.nan,
        "squeeze": float(sq["score"]),
        "sq_nivel": sq["nivel"],
        "sq_inminente": bool(sq["inminente"]),
        "direccion": int(sq["direccion"]),
        "oi_total": tot_oi,
        "niveles": niv[["tipo", "rol", "strike", "dist_pct", "calls", "puts"]].to_dict("records"),
    }


def _escanear(lista, n_vtos, rango_pct, r, q):
    filas, errores = [], {}
    barra = st.progress(0.0, text="Escaneando...")
    for i, t in enumerate(lista):
        barra.progress(i / len(lista), text=f"Escaneando {t} ({i + 1}/{len(lista)})")
        try:
            filas.append(analizar_ticker(t, n_vtos, rango_pct, r, q))
        except Exception as e:
            errores[t] = f"{type(e).__name__}: {e}"
    barra.empty()
    return {"filas": filas, "errores": errores, "hora": datetime.now(TZ_AR).strftime("%H:%M:%S"),
            "ts": time.time(), "n_vtos": n_vtos, "rango": rango_pct, "cambios": []}


def _detectar_cambios(prev, nuevo):
    """Compara dos escaneos y devuelve los avisos: cruces de régimen y nuevos squeeze inminentes."""
    if not prev:
        return []
    antes = {f["ticker"]: f for f in prev["filas"]}
    msgs = []
    for f in nuevo["filas"]:
        a = antes.get(f["ticker"])
        if a is None:
            continue
        t = f["ticker"]
        if a["regimen"] != "negativo" and f["regimen"] == "negativo":
            msgs.append(f"🔴 {t}: pasó a gamma NEGATIVA")
        elif a["regimen"] == "negativo" and f["regimen"] != "negativo":
            msgs.append(f"🟢 {t}: volvió a gamma positiva")
        if not a["sq_inminente"] and f["sq_inminente"]:
            msgs.append(f"🚨 {t}: entró en Zona de Squeeze Inminente (score {f['squeeze']:.0f})")
    return msgs


# ==============================================================
#  FILTROS Y TABLA
# ==============================================================

def _aplicar_filtros(df, f):
    d = df.copy()
    if f["regimen"] == "Solo gamma negativa":
        cond = d["regimen"] == "negativo"
        if f["incluir_cerca"]:
            cond = cond | ((d["regimen"] == "positivo") & (d["dist_flip"] <= f["cerca_pct"]))
        d = d[cond]
    elif f["regimen"] == "Solo gamma positiva":
        d = d[d["regimen"] == "positivo"]

    d = d[d["squeeze"] >= f["sq_min"]]
    if f["solo_inminente"]:
        d = d[d["sq_inminente"]]
    if f["direccion"] != "Todas":
        d = d[d["direccion"] == {"Alcista": 1, "Bajista": -1, "Neutra": 0}[f["direccion"]]]
    if f["dist_nivel_max"] < 30:
        cerca = (d["dist_res"].abs() <= f["dist_nivel_max"]) | (d["dist_sop"].abs() <= f["dist_nivel_max"])
        d = d[cerca]

    orden = f["orden"]
    if orden == "Squeeze Score (mayor)":
        d = d.sort_values("squeeze", ascending=False)
    elif orden == "Más por debajo del punto de cambio":
        d = d.sort_values("dist_flip", ascending=True, na_position="last")
    elif orden == "GEX más negativo":
        d = d.sort_values("gex_total", ascending=True)
    else:
        d = d.sort_values("ticker")
    return d


def _tabla(d):
    t = pd.DataFrame({
        "Ticker": d["ticker"],
        "Precio": d["precio"],
        "Régimen": np.where(d["regimen"] == "negativo", "🔴 Negativa", "🟢 Positiva"),
        "Dist. al flip %": d["dist_flip"],
        "Punto de cambio": d["flip"],
        "Resist. principal": d["res_principal"],
        "Soporte principal": d["sop_principal"],
        "Pivote": d["pivote"],
        "Pared Calls": d["call_wall"],
        "Pared Puts": d["put_wall"],
        "Squeeze": d["squeeze"],
        "Alerta": np.where(d["sq_inminente"], "🚨 Inminente", d["sq_nivel"]),
        "Dirección": d["direccion"].map(DIR_TXT),
        "GEX (M US$)": d["gex_total"],
    })
    nf = lambda: st.column_config.NumberColumn(format="%.2f")
    st.dataframe(t, use_container_width=True, hide_index=True,
                 column_config={
                     "Precio": nf(), "Punto de cambio": nf(), "Resist. principal": nf(),
                     "Soporte principal": nf(), "Pivote": nf(), "Pared Calls": nf(), "Pared Puts": nf(),
                     "Dist. al flip %": st.column_config.NumberColumn(format="%+.1f"),
                     "Squeeze": st.column_config.NumberColumn(format="%.0f"),
                     "GEX (M US$)": st.column_config.NumberColumn(format="%+,.1f"),
                 })


def _detalle(fila, on_cargar):
    S = fila["precio"]
    st.markdown(f"##### 🔎 {fila['ticker']} — {'🔴 gamma NEGATIVA' if fila['regimen'] == 'negativo' else '🟢 gamma positiva'}")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Precio", gx.fmt_precio(S))
    m2.metric("Punto de cambio de gamma", gx.fmt_precio(fila["flip"]) if not pd.isna(fila["flip"]) else "N/D",
              f"{fila['dist_flip']:+.1f}% vs precio" if not pd.isna(fila["dist_flip"]) else None, delta_color="off")
    m3.metric("Squeeze Score", f"{fila['squeeze']:.0f}", fila["sq_nivel"], delta_color="off")
    m4.metric("Dirección probable", DIR_TXT[fila["direccion"]])

    # Escalera de niveles: mayor strike arriba, precio en el medio
    filas = []
    for n in fila["niveles"]:
        icono = {"Resistencia": "🟢", "Soporte": "🔴", "Pivote": "🟡"}[n["tipo"]]
        estrella = "★ " if n["rol"] == "Principal" else ""
        filas.append({"_k": n["strike"], "Nivel": f"{icono} {estrella}{n['tipo']} ({n['rol'].lower()})",
                      "Strike": f"{n['strike']:,.2f}", "Dist. %": f"{n['dist_pct']:+.1f}%"})
    for nombre, k in (("🧱 Pared de Calls", fila["call_wall"]), ("🧱 Pared de Puts", fila["put_wall"]),
                      ("🟣 Punto de cambio de gamma", fila["flip"])):
        if not pd.isna(k):
            filas.append({"_k": k, "Nivel": nombre, "Strike": f"{k:,.2f}", "Dist. %": f"{(k / S - 1) * 100:+.1f}%"})
    filas.append({"_k": S, "Nivel": "━━ PRECIO ACTUAL ━━", "Strike": f"{S:,.2f}", "Dist. %": "0.0%"})
    esc = pd.DataFrame(filas).sort_values("_k", ascending=False).drop(columns="_k").reset_index(drop=True)
    st.dataframe(esc, use_container_width=True, hide_index=True)

    st.caption("Al cargarla en el formulario se completan ticker, entrada (precio actual), SL, TP y notas. "
               "SL/TP salen de los niveles principales (largo: SL = soporte, TP = resistencia; "
               "corto: al revés). Es un punto de partida: revisalos antes de publicar.")
    b1, b2 = st.columns(2)
    with b1:
        st.button("🟢 Cargar como LARGO en el formulario", key=f"scan_largo_{fila['ticker']}",
                  on_click=on_cargar, args=(fila, "LARGO"), use_container_width=True)
    with b2:
        st.button("🔴 Cargar como CORTO en el formulario", key=f"scan_corto_{fila['ticker']}",
                  on_click=on_cargar, args=(fila, "CORTO"), use_container_width=True)


# ==============================================================
#  RENDER PRINCIPAL
# ==============================================================

def render_scanner_gex(on_cargar):
    st.caption("Cargá tu lista de activos (hasta 60), escaneá y filtrá cuáles están en **gamma negativa** "
               "con sus niveles. Los datos son los de la pestaña GEX (CBOE retrasado ~15 min / Deribit para BTC y ETH).")

    lista_txt = st.text_area("📋 Lista de tickers (separados por coma, espacio o salto de línea)",
                             value=st.session_state.get("sen_scan_lista", LISTA_EJEMPLO),
                             height=110, key="sen_scan_lista_input",
                             help="Aceptan los mismos formatos que la pestaña GEX: SPY, NVDA, SPX, BTC, EURUSD, GC=F, GGAL.BA...")
    st.session_state["sen_scan_lista"] = lista_txt
    lista = _parsear_lista(lista_txt)

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        n_vtos = st.slider("Vencimientos a incluir", 1, 12, 4, key="sen_scan_nvtos",
                           help="Menos vencimientos = lectura más táctica (corto plazo).")
    with c2:
        rango_pct = st.slider("Rango de precios (±%)", 5, 30, 20, key="sen_scan_rango")
    with c3:
        st.write("")
        st.write("")
        escanear = st.button(f"🔍 Escanear {len(lista)} activos", type="primary",
                             key="sen_scan_btn", disabled=not lista, use_container_width=True)

    with st.expander("⚙️ Parámetros avanzados", expanded=False):
        a1, a2 = st.columns(2)
        with a1:
            r = st.number_input("Tasa de interés anual (decimal)", 0.0, 1.0, 0.045, 0.005,
                                format="%.4f", key="sen_scan_r")
        with a2:
            q = st.number_input("Rendimiento por dividendos (decimal)", 0.0, 0.5, 0.0, 0.005,
                                format="%.4f", key="sen_scan_q")

    auto = st.checkbox("🔔 Auto-actualizar cada 5 min y avisar cuando un activo pase a gamma negativa "
                       "o entre en Zona de Squeeze Inminente", value=False, key="sen_scan_auto",
                       help="Vuelve a descargar y analizar toda la lista cada 5 minutos mientras "
                            "estés en el modo Scanner. Necesitás haber hecho un primer escaneo.")
    if auto:
        st_autorefresh(interval=5 * 60 * 1000, key="sen_scan_autorefresh")

    prev = st.session_state.get(CLAVE_RES)
    toca_auto = (auto and prev is not None and bool(lista)
                 and (time.time() - prev.get("ts", 0)) >= 290)
    if escanear or toca_auto:
        if toca_auto and not escanear:
            gx._gex_descargar.clear()          # fuerza datos frescos (la caché dura 5 min)
        nuevo = _escanear(lista, n_vtos, rango_pct, r, q)
        nuevo["cambios"] = _detectar_cambios(prev, nuevo)
        for msg in nuevo["cambios"][:5]:
            st.toast(msg)
        st.session_state[CLAVE_RES] = nuevo

    res = st.session_state.get(CLAVE_RES)
    if not res:
        st.info("Cargá la lista y tocá **Escanear** para ver el panel.")
        return
    if not res["filas"]:
        st.warning("No se pudo analizar ningún activo de la lista.")
        _mostrar_errores(res)
        return

    st.caption(f"📡 Último escaneo a las {res['hora']} · {len(res['filas'])} activos analizados · "
               f"{res['n_vtos']} vencimientos · rango ±{res['rango']}%"
               + (" · se vuelve a escanear solo cada 5 min" if auto else ""))
    if res.get("cambios"):
        st.info("**Cambios desde el escaneo anterior:**\n\n" + "\n".join(f"- {m}" for m in res["cambios"]))
    df = pd.DataFrame(res["filas"])

    n_neg = int((df["regimen"] == "negativo").sum())
    n_inm = int(df["sq_inminente"].sum())
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Analizados", len(df))
    k2.metric("🔴 En gamma negativa", n_neg)
    k3.metric("🟢 En gamma positiva", len(df) - n_neg)
    k4.metric("🚨 Squeeze inminente", n_inm)

    st.markdown("##### 🎛️ Filtros")
    f1, f2, f3 = st.columns(3)
    with f1:
        regimen = st.selectbox("Régimen de gamma", ["Solo gamma negativa", "Todos", "Solo gamma positiva"],
                               key="sen_scan_f_regimen")
        incluir_cerca, cerca_pct = False, 2.0
        if regimen == "Solo gamma negativa":
            incluir_cerca = st.checkbox("Incluir los que están por encima del flip, pero cerca",
                                        key="sen_scan_f_cerca",
                                        help="Activos en gamma positiva a punto de cruzar al régimen negativo.")
            if incluir_cerca:
                cerca_pct = st.number_input("Hasta qué % sobre el flip", 0.5, 10.0, 2.0, 0.5, key="sen_scan_f_cerca_pct")
    with f2:
        sq_min = st.slider("Squeeze Score mínimo", 0, 100, 0, 5, key="sen_scan_f_sq")
        solo_inminente = st.checkbox("Solo 🚨 Zona de Squeeze Inminente", key="sen_scan_f_inm")
    with f3:
        direccion = st.selectbox("Dirección probable", ["Todas", "Alcista", "Bajista", "Neutra"], key="sen_scan_f_dir")
        dist_nivel_max = st.slider("Precio a ≤ X% de una resistencia o soporte principal", 1, 30, 30,
                                   key="sen_scan_f_dist",
                                   help="En 30 no filtra. Bajalo para ver solo activos pegados a un nivel.")
    orden = st.selectbox("Ordenar por", ["Squeeze Score (mayor)", "Más por debajo del punto de cambio",
                                          "GEX más negativo", "Ticker (A-Z)"], key="sen_scan_f_orden")

    filtro = dict(regimen=regimen, incluir_cerca=incluir_cerca, cerca_pct=cerca_pct, sq_min=sq_min,
                  solo_inminente=solo_inminente, direccion=direccion, dist_nivel_max=dist_nivel_max, orden=orden)
    d = _aplicar_filtros(df, filtro)

    st.caption(f"{len(d)} activos cumplen los filtros de {len(df)} analizados.")
    if d.empty:
        st.info("Ningún activo cumple los filtros actuales. Aflojalos para ver más.")
    else:
        _tabla(d)
        st.divider()
        elegido = st.selectbox("Elegí un activo para ver sus niveles y cargarlo en el formulario",
                               d["ticker"].tolist(), key="sen_scan_sel")
        _detalle(d[d["ticker"] == elegido].iloc[0].to_dict(), on_cargar)

    _mostrar_errores(res)

    st.caption("⚠️ El GEX asume creadores de mercado largos calls / cortos puts y usa el interés abierto del día "
               "anterior. Es una referencia de contexto, no una señal por sí sola. Los índices y ETFs con "
               "vencimientos diarios (SPX, SPY, QQQ) tienden a mostrar mucha gamma concentrada en el primer vencimiento.")


def _mostrar_errores(res):
    if res["errores"]:
        with st.expander(f"⚠️ {len(res['errores'])} activos sin datos (sin opciones listadas o error de descarga)"):
            for t, msg in res["errores"].items():
                st.caption(f"**{t}**: {msg}")
