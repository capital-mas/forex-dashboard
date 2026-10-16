# ==============================================================
#  MICRO APP — INICIO DASHBOARD
#  Cotizaciones destacadas (agrupadas, con resumen) + Calendario
#  Económico + Noticias + Cotizaciones por categoría (desplegable).
#
#  Contrato (sin cambios):
#      render_inicio_dashboard(descargar_bulk, get_close_from_bulk,
#                              eventos=None, noticias=None, watchlist=None,
#                              eventos_tag="Hoy", universo=None)
#      limpiar_cache_inicio()
#
#  - watchlist: [{label, ticker, grupo(opcional)}]
#  - universo : dict con claves opcionales:
#        'paises','etfs','sectores','mercados','forex','acciones'
# ==============================================================

import html
import streamlit as st

# ── Watchlist de la franja superior (editable) ──
WATCHLIST_DEFAULT = [
    {"label": "S&P 500 (SPY)",  "ticker": "SPY",      "grupo": "Índices"},
    {"label": "Nasdaq (QQQ)",   "ticker": "QQQ",      "grupo": "Índices"},
    {"label": "Dow (DIA)",      "ticker": "DIA",      "grupo": "Índices"},
    {"label": "Russell (IWM)",  "ticker": "IWM",      "grupo": "Índices"},
    {"label": "NVIDIA",         "ticker": "NVDA",     "grupo": "Acciones"},
    {"label": "Apple",          "ticker": "AAPL",     "grupo": "Acciones"},
    {"label": "Microsoft",      "ticker": "MSFT",     "grupo": "Acciones"},
    {"label": "Tesla",          "ticker": "TSLA",     "grupo": "Acciones"},
    {"label": "Bitcoin",        "ticker": "BTC-USD",  "grupo": "Cripto"},
    {"label": "Ethereum",       "ticker": "ETH-USD",  "grupo": "Cripto"},
    {"label": "Oro",            "ticker": "GC=F",     "grupo": "Commodities"},
    {"label": "Petróleo WTI",   "ticker": "CL=F",     "grupo": "Commodities"},
    {"label": "Dólar (DXY)",    "ticker": "DX-Y.NYB", "grupo": "Divisas y Tasas"},
    {"label": "EUR/USD",        "ticker": "EURUSD=X", "grupo": "Divisas y Tasas"},
    {"label": "Tasa 10 años",   "ticker": "^TNX",     "grupo": "Divisas y Tasas"},
]

COLORES_GRUPO_WL = {
    "Índices": "#3a7bd5", "Acciones": "#6CC24A", "Cripto": "#f0883e",
    "Commodities": "#e3b341", "Divisas y Tasas": "#bc8cff", "Destacados": "#6CC24A",
}

EVENTOS_DEMO = [
    {"hora": "14:30", "evento": "IPC EE.UU. (MoM)", "prev": "0.3%",  "consenso": "0.2%"},
    {"hora": "16:00", "evento": "Ventas Viviendas", "prev": "4.00M", "consenso": "3.97M"},
    {"hora": "20:00", "evento": "Minutas de la Fed", "prev": "--",   "consenso": "--"},
]

NOTICIAS_DEMO = [
    {"ticker": "NVDA",  "titular": "Aumento de demanda en chips H100/H200 en Data Centers.", "sentimiento": "Alcista"},
    {"ticker": "AAPL",  "titular": "Lanzamiento de nuevas integraciones IA en WWDC.",        "sentimiento": "Alcista"},
    {"ticker": "US10Y", "titular": "Subasta de bonos a 10 años muestra demanda moderada.",   "sentimiento": "Neutro"},
]

_COLOR_SENT = {"alcista": "var(--ci-up)", "bajista": "var(--ci-down)", "neutro": "var(--ci-warn)"}

_UP, _DOWN, _WARN, _MUTED = "#3fb950", "#f85149", "#e3b341", "#6b7d9a"
_MONO = "font-family:'JetBrains Mono',monospace"

YIELD_TICKERS = {"^IRX", "^FVX", "^TNX", "^TYX"}

COLORES_REGION = {"América": "#3a7bd5", "Asia": "#f0883e", "Europa": "#7ee787", "Global": "#bc8cff"}
COLORES_GRUPO_FX = {"Majors": "#3a7bd5", "Crosses EUR": "#f0883e", "Crosses GBP": "#7ee787",
                    "Crosses AUD": "#bc8cff", "Crosses NZD": "#bc8cff", "Crosses JPY": "#79c0ff",
                    "LatAm": "#f85149"}


# ==============================================================
#  ESTILOS (scoped con prefijo ci-)
# ==============================================================
_CSS = """
<style>
.ci-root {
  --ci-bg: #0d1117; --ci-card: #11161d; --ci-border: #21262d;
  --ci-text: #e6edf3; --ci-muted: #8b949e;
  --ci-up: #3fb950; --ci-down: #f85149; --ci-warn: #e3b341;
  font-family: 'Inter', sans-serif;
}
.ci-panel { background:var(--ci-card); border:1px solid var(--ci-border);
            border-radius:14px; padding:16px 18px; height:100%; }
.ci-panel-head { display:flex; justify-content:space-between; align-items:baseline;
                 margin-bottom:10px; }
.ci-panel-title { font-size:15px; font-weight:700; color:var(--ci-text); }
.ci-panel-tag   { font-family:'JetBrains Mono',monospace; font-size:11px; color:var(--ci-muted); }

.ci-table { width:100%; border-collapse:collapse; }
.ci-table th { font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:400;
               color:var(--ci-muted); text-align:left; padding:6px 8px;
               border-bottom:1px solid var(--ci-border); }
.ci-table td { font-size:13px; color:var(--ci-text); padding:10px 8px;
               border-bottom:1px solid var(--ci-border); vertical-align:top; }
.ci-table tr:last-child td { border-bottom:none; }
.ci-mono { font-family:'JetBrains Mono',monospace; color:var(--ci-muted); }
.ci-tk   { font-family:'JetBrains Mono',monospace; font-weight:700; }
.ci-sent { font-family:'JetBrains Mono',monospace; font-weight:600; font-size:12px; }
.ci-empty { color:var(--ci-muted); font-size:12px; padding:18px 0; text-align:center; }
</style>
"""


# ==============================================================
#  DATOS — precios del día (un solo bulk por conjunto de tickers)
# ==============================================================
def _tipo(tk):
    if tk in YIELD_TICKERS:
        return "yield"
    if tk.endswith("=X"):
        return "fx"
    if tk.startswith("^"):
        return "indice"
    return "precio"


@st.cache_data(ttl=300, show_spinner=False)
def _precios(tickers, _descargar_bulk, _get_close):
    """tickers: tupla ordenada. Devuelve {tk: {precio, pct, abs, tipo}}."""
    out = {}
    if not tickers:
        return out
    try:
        df = _descargar_bulk(list(tickers), period="inicio")
    except Exception:
        return out
    if df is None or getattr(df, "empty", False):
        return out
    for tk in tickers:
        try:
            close = _get_close(df, tk)
            if close is None or len(close) < 2:
                continue
            actual, previo = float(close.iloc[-1]), float(close.iloc[-2])
            tipo = _tipo(tk)
            if tipo == "yield" and actual > 20:   # Yahoo a veces cotiza x10
                actual, previo = actual / 10, previo / 10
            if previo == 0:
                continue
            out[tk] = {
                "precio": actual,
                "pct": (actual / previo - 1) * 100,
                "abs": actual - previo,
                "tipo": tipo,
            }
        except Exception:
            continue
    return out


def limpiar_cache_inicio():
    """Llamar desde el botón '↺ Actualizar' de app.py."""
    try:
        _precios.clear()
    except Exception:
        pass


# ==============================================================
#  FORMATO
# ==============================================================
def _fmt_valor(valor, tipo):
    if tipo == "yield":
        return f"{valor:.2f}%"
    if tipo == "fx":
        return f"{valor:.5f}" if valor < 100 else f"{valor:,.2f}"
    if tipo == "indice":
        return f"{valor:,.0f}" if valor >= 1000 else f"{valor:,.2f}"
    if valor >= 1000:
        return f"${valor:,.0f}"
    if valor >= 10:
        return f"${valor:,.2f}"
    return f"${valor:,.4f}"


def _fmt_abs(abs_c, precio, tipo):
    if tipo == "yield":
        return f"{abs_c:+.3f}"
    if abs(precio) >= 1000:
        return f"{abs_c:+.2f}"
    if abs(precio) >= 1:
        return f"{abs_c:+.3f}"
    return f"{abs_c:+.6f}"


def _fmt_delta(d):
    if d["tipo"] == "yield":
        return f"{d['abs'] * 100:+.0f} bps"
    flecha = "▲" if d["pct"] >= 0 else "▼"
    return f"{flecha} {abs(d['pct']):.2f}%"


# ==============================================================
#  RENDER — cards de cotización
# ==============================================================
def _card(nombre, tk, d):
    tk_h, nom_h = html.escape(tk), html.escape(str(nombre))
    if not d:
        return (
            '<div style="background:#0d1117;border:1px solid #21262d;border-top:2px solid #21262d;'
            'border-radius:8px;padding:12px 14px;min-width:0">'
            f'<div style="font-size:11px;font-weight:700;color:#8b949e;{_MONO}">{tk_h}</div>'
            f'<div style="font-size:10px;color:#3a4a5f;margin-bottom:6px;white-space:nowrap;'
            f'overflow:hidden;text-overflow:ellipsis">{nom_h[:22]}</div>'
            '<div style="font-size:14px;color:#3a4a5f">S/D</div></div>'
        )
    color = _UP if d["pct"] >= 0 else _DOWN
    return (
        f'<div style="background:#0d1117;border:1px solid #21262d;border-top:2px solid {color};'
        'border-radius:8px;padding:12px 14px;min-width:0">'
        f'<div style="font-size:11px;font-weight:700;color:#e6edf3;{_MONO};white-space:nowrap;'
        f'overflow:hidden;text-overflow:ellipsis">{tk_h}</div>'
        f'<div style="font-size:10px;color:{_MUTED};margin-bottom:8px;white-space:nowrap;'
        f'overflow:hidden;text-overflow:ellipsis" title="{nom_h}">{nom_h[:22]}</div>'
        f'<div style="font-size:15px;font-weight:700;color:#e6edf3;{_MONO}">'
        f'{html.escape(_fmt_valor(d["precio"], d["tipo"]))}</div>'
        f'<div style="font-size:12px;font-weight:700;color:{color};margin-top:3px">{_fmt_delta(d)}</div>'
        f'<div style="font-size:10px;color:{_MUTED};margin-top:1px">'
        f'{_fmt_abs(d["abs"], d["precio"], d["tipo"])}</div></div>'
    )


def _grid(items, datos):
    """items: [(nombre, tk)]"""
    cards = "".join(_card(n, tk, datos.get(tk)) for n, tk in items)
    return ('<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(148px,1fr));'
            f'gap:8px;margin-bottom:4px">{cards}</div>')


def _titulo_grupo(texto, color):
    return (f'<div style="font-size:11px;font-weight:700;color:{color};text-transform:uppercase;'
            f'letter-spacing:.8px;margin:14px 0 8px 0">◆ {html.escape(texto)}</div>')


def _kpi_resumen(datos_sub, sufijo=""):
    """Subiendo / Bajando / Neutros / Mejor del día para un subconjunto."""
    if not datos_sub:
        st.info("Sin datos disponibles para esta sección.")
        return
    pcts = [d["pct"] for d in datos_sub.values()]
    n_sub = sum(1 for v in pcts if v > 0.05)
    n_baj = sum(1 for v in pcts if v < -0.05)
    n_neu = len(pcts) - n_sub - n_baj
    mejor_tk, mejor_d = max(datos_sub.items(), key=lambda x: x[1]["pct"])

    def caja(label, valor, sub, color):
        return (
            f'<div style="background:#0d1117;border:1px solid #21262d;border-top:2px solid {color};'
            'border-radius:10px;padding:14px 16px">'
            f'<div style="font-size:11px;font-weight:700;color:#f5f7fa;text-transform:uppercase;'
            f'letter-spacing:1px;margin-bottom:6px">{label}</div>'
            f'<div style="font-size:20px;font-weight:700;color:#e6edf3;{_MONO}">{html.escape(str(valor))}</div>'
            f'<div style="font-size:12px;color:#f5f7fa;margin-top:4px">{html.escape(str(sub))}</div></div>'
        )
    suf = f" {sufijo}" if sufijo else ""
    st.markdown(
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));'
        'gap:12px;margin-bottom:12px">'
        + caja("Subiendo hoy", n_sub, f"de {len(pcts)}{suf}", _UP)
        + caja("Bajando hoy", n_baj, f"de {len(pcts)}{suf}", _DOWN)
        + caja("Neutros", n_neu, "variación < ±0.05%", _WARN)
        + caja("Mejor del día", mejor_tk, f"{mejor_d['pct']:+.2f}%", _UP)
        + "</div>",
        unsafe_allow_html=True,
    )


def _render_grupos(grupos, datos):
    """grupos: [(titulo, color, [(nombre, tk), ...])]"""
    for titulo, color, items in grupos:
        if not items:
            continue
        st.markdown(_titulo_grupo(titulo, color), unsafe_allow_html=True)
        st.markdown(_grid(items, datos), unsafe_allow_html=True)


# ==============================================================
#  RENDER — calendario y noticias
# ==============================================================
def _html_calendario(eventos, tag="Hoy"):
    if not eventos:
        cuerpo = '<div class="ci-empty">Sin eventos relevantes hoy.</div>'
    else:
        usa_hora = any(e.get("hora") for e in eventos)
        filas = "".join(
            f'<tr><td class="ci-mono">{html.escape(str(e.get("hora") or e.get("pais") or ""))}</td>'
            f'<td>{html.escape(str(e.get("evento", "")))}</td>'
            f'<td class="ci-mono">{html.escape(str(e.get("prev", "--")))}</td>'
            f'<td class="ci-mono">{html.escape(str(e.get("consenso", "--")))}</td></tr>'
            for e in eventos
        )
        cuerpo = (
            '<table class="ci-table"><thead><tr>'
            f'<th>{"Hora" if usa_hora else "País"}</th><th>Evento</th><th>Prev.</th><th>Consenso</th>'
            f'</tr></thead><tbody>{filas}</tbody></table>'
        )
    return (
        '<div class="ci-panel"><div class="ci-panel-head">'
        '<span class="ci-panel-title">Calendario Económico Clase A</span>'
        f'<span class="ci-panel-tag">{html.escape(tag)}</span></div>'
        f'{cuerpo}</div>'
    )


def _html_noticias(noticias):
    if not noticias:
        cuerpo = '<div class="ci-empty">Sin noticias por ahora.</div>'
    else:
        filas = []
        for n in noticias:
            sent = str(n.get("sentimiento", "Neutro"))
            color = _COLOR_SENT.get(sent.lower(), "var(--ci-muted)")
            filas.append(
                f'<tr><td class="ci-tk">{html.escape(str(n.get("ticker", "")))}</td>'
                f'<td>{html.escape(str(n.get("titular", "")))}</td>'
                f'<td class="ci-sent" style="color:{color}">{html.escape(sent)}</td></tr>'
            )
        cuerpo = (
            '<table class="ci-table"><thead><tr>'
            '<th>Ticker</th><th>Titular</th><th>Sentimiento</th>'
            f'</tr></thead><tbody>{"".join(filas)}</tbody></table>'
        )
    return (
        '<div class="ci-panel"><div class="ci-panel-head">'
        '<span class="ci-panel-title">Noticias &amp; Flujos Relevantes</span>'
        '<span class="ci-panel-tag">Tiempo Real</span></div>'
        f'{cuerpo}</div>'
    )


# ==============================================================
#  AGRUPADORES por categoría
# ==============================================================
def _grupos_paises(paises):
    reg = {}
    for nombre, (tk, region) in paises.items():
        reg.setdefault(region, []).append((nombre, tk))
    return [(r, COLORES_REGION.get(r, "#6CC24A"), its) for r, its in reg.items()]


def _grupos_con_categoria(universo_dict, color_default="#6CC24A"):
    """Para {nombre: (tk, cat, color)} -> agrupa por cat (toma el color del primero)."""
    cats, colores = {}, {}
    for nombre, (tk, cat, color) in universo_dict.items():
        cats.setdefault(cat, []).append((nombre, tk))
        colores.setdefault(cat, color or color_default)
    return [(c, colores[c], its) for c, its in cats.items()]


def _grupos_sectores(sectores):
    gics = [(n, tk) for n, (tk, cat, _c) in sectores.items() if cat == "Sectores"]
    sub = [(n, tk) for n, (tk, cat, _c) in sectores.items() if cat == "Sub-sectores"]
    return [("Sectores GICS (11 sectores)", "#3a7bd5", gics),
            ("Sub-sectores / Temáticos", "#bc8cff", sub)]


def _grupos_forex(forex):
    gr = {}
    for nombre, (tk, grupo) in forex.items():
        gr.setdefault(grupo, []).append((nombre, tk))
    return [(g, COLORES_GRUPO_FX.get(g, "#6CC24A"), its) for g, its in gr.items()]


def _grupos_watchlist(wl):
    """Agrupa la watchlist por su campo 'grupo' (conserva el orden)."""
    gr = {}
    for w in wl:
        gr.setdefault(w.get("grupo") or "Destacados", []).append((w["label"], w["ticker"]))
    return [(g, COLORES_GRUPO_WL.get(g, "#6CC24A"), its) for g, its in gr.items()]


def _tickers_de(grupos):
    return sorted({tk for _t, _c, items in grupos for _n, tk in items})


# ==============================================================
#  RENDER — cotizaciones por categoría (DESPLEGABLE)
# ==============================================================
def _render_cotizaciones(universo, descargar_bulk, get_close):
    st.markdown('<div class="sec-title">📊 Cotizaciones del día</div>', unsafe_allow_html=True)

    secciones = {}   # label -> (grupos, sufijo)
    if universo.get("paises"):
        secciones["🌍 Índices"] = (_grupos_paises(universo["paises"]), "índices")
    if universo.get("etfs"):
        secciones["📦 ETFs y Bonos"] = (_grupos_con_categoria(universo["etfs"]), "ETFs")
    if universo.get("sectores"):
        secciones["📊 Sectores"] = (_grupos_sectores(universo["sectores"]), "sectores")
    if universo.get("mercados"):
        secciones["🛢️ Mercados"] = (_grupos_con_categoria(universo["mercados"], "#f0883e"), "mercados")
    if universo.get("forex"):
        secciones["💱 Forex"] = (_grupos_forex(universo["forex"]), "pares")

    acciones = universo.get("acciones") or {}
    LABEL_ACC = "📈 Acciones"
    opciones = list(secciones.keys()) + ([LABEL_ACC] if acciones else [])
    if not opciones:
        return

    # ── Desplegables: categoría (+ industria al lado si es Acciones) ──
    es_acc_sel = st.session_state.get("ci_cat_sel") == LABEL_ACC
    if es_acc_sel:
        c1, c2, _ = st.columns([1.3, 1.6, 2.1])
    else:
        c1, _ = st.columns([1.3, 3.7])
        c2 = None

    with c1:
        categoria = st.selectbox("Categoría", opciones, key="ci_cat_sel")

    # ── Categorías normales ──
    if categoria != LABEL_ACC:
        grupos, sufijo = secciones[categoria]
        with st.spinner("Cargando cotizaciones..."):
            datos = _precios(tuple(_tickers_de(grupos)), descargar_bulk, get_close)
        tks = set(_tickers_de(grupos))
        _kpi_resumen({tk: d for tk, d in datos.items() if tk in tks}, sufijo)
        _render_grupos(grupos, datos)
        return

    # ── Acciones: segundo desplegable con cada industria ──
    industrias = list(acciones.keys())
    if c2 is None:   # primer render justo después de elegir Acciones
        st.rerun()
    with c2:
        industria = st.selectbox("Industria", industrias, key="ci_ind_one")

    tks_acc = sorted(set(acciones.get(industria, [])))
    with st.spinner("Cargando precios de acciones..."):
        datos_acc = _precios(tuple(tks_acc), descargar_bulk, get_close)
    _kpi_resumen(datos_acc, f"acciones de {industria}")

    direccion = st.radio("Dirección", ["Todas", "▲ Subiendo", "▼ Bajando"],
                         horizontal=True, key="ci_acc_dir")
    items = []
    for tk in tks_acc:
        d = datos_acc.get(tk)
        if not d:
            continue
        if direccion == "▲ Subiendo" and d["pct"] <= 0:
            continue
        if direccion == "▼ Bajando" and d["pct"] >= 0:
            continue
        items.append((tk, tk, d["pct"]))
    items.sort(key=lambda x: x[2], reverse=True)
    if not items:
        st.info("No hay acciones que cumplan ese filtro.")
        return
    st.markdown(_titulo_grupo(f"{industria} ({len(items)})", "#6CC24A"), unsafe_allow_html=True)
    st.markdown(_grid([(n, tk) for n, tk, _p in items], datos_acc), unsafe_allow_html=True)


# ==============================================================
#  ENTRADA PÚBLICA
# ==============================================================
def render_inicio_dashboard(descargar_bulk, get_close_from_bulk,
                            eventos=None, noticias=None, watchlist=None,
                            eventos_tag="Hoy", universo=None):
    wl = watchlist or WATCHLIST_DEFAULT

    st.markdown(_CSS, unsafe_allow_html=True)

    # ── 1) Cotizaciones destacadas: mismo formato que la sección de Índices ──
    grupos_wl = _grupos_watchlist(wl)
    try:
        datos_wl = _precios(tuple(_tickers_de(grupos_wl)), descargar_bulk, get_close_from_bulk)
    except Exception:
        datos_wl = {}
    st.markdown('<div class="sec-title">⭐ Cotizaciones destacadas</div>', unsafe_allow_html=True)
    _kpi_resumen(datos_wl, "destacados")
    _render_grupos(grupos_wl, datos_wl)
    st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)

    # ── 2) Calendario + Noticias ──
    col_cal, col_news = st.columns(2, gap="medium")
    with col_cal:
        st.markdown(
            f'<div class="ci-root">{_html_calendario(EVENTOS_DEMO if eventos is None else eventos, eventos_tag)}</div>',
            unsafe_allow_html=True)
    with col_news:
        st.markdown(
            f'<div class="ci-root">{_html_noticias(NOTICIAS_DEMO if noticias is None else noticias)}</div>',
            unsafe_allow_html=True)

    # ── 3) Todo el universo de app.py, con desplegable ──
    if universo:
        st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)
        _render_cotizaciones(universo, descargar_bulk, get_close_from_bulk)
