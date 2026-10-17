# ==============================================================
#  MICRO APP — INICIO DASHBOARD
#  Franja de cotizaciones + Calendario Económico + Noticias
#
#  Contrato:
#      render_inicio_dashboard(descargar_bulk, get_close_from_bulk,
#                              eventos=None, noticias=None,
#                              watchlist=None, eventos_tag="Hoy")
#
#  - No importa nada de app.py: todo entra por parámetro.
#  - watchlist: [{nombre, ticker, tipo}]  tipo: precio | indice | fx | yield
#  - eventos  : [{pais|hora, evento, prev, consenso}]
#  - noticias : [{ticker, titular, sentimiento}]  (Alcista|Bajista|Neutro)
#  Si eventos/noticias son None se muestran datos de ejemplo.
# ==============================================================

import html
import streamlit as st

WATCHLIST_DEFAULT = [
    {"nombre": "S&P 500 (ETF)",    "ticker": "SPY",      "tipo": "precio"},
    {"nombre": "NASDAQ 100 (ETF)", "ticker": "QQQ",      "tipo": "precio"},
    {"nombre": "Dow Jones (ETF)",  "ticker": "DIA",      "tipo": "precio"},
    {"nombre": "Russell 2000",     "ticker": "IWM",      "tipo": "precio"},
    {"nombre": "Volatilidad",      "ticker": "^VIX",     "tipo": "indice"},
    {"nombre": "Nvidia",           "ticker": "NVDA",     "tipo": "precio"},
    {"nombre": "Bitcoin",          "ticker": "BTC-USD",  "tipo": "precio"},
    {"nombre": "Ethereum",         "ticker": "ETH-USD",  "tipo": "precio"},
    {"nombre": "Oro",              "ticker": "GC=F",     "tipo": "precio"},
    {"nombre": "Petróleo WTI",     "ticker": "CL=F",     "tipo": "precio"},
    {"nombre": "EUR/USD",          "ticker": "EURUSD=X", "tipo": "fx"},
    {"nombre": "Bono US 10 años",  "ticker": "^TNX",     "tipo": "yield"},
]

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

_CSS = """
<style>
.ci-root {
  --ci-bg: #0d1117; --ci-card: #0d1117; --ci-border: #21262d;
  --ci-text: #e6edf3; --ci-muted: #6b7d9a;
  --ci-up: #3fb950; --ci-down: #f85149; --ci-warn: #e3b341;
  font-family: 'Inter', sans-serif;
}
/* Cotizaciones: mismo diseño que las tarjetas de Índices */
.ci-kpis { display:grid; grid-template-columns:repeat(auto-fill,minmax(148px,1fr));
           gap:8px; margin-bottom:16px; }
.ci-kpi  { background:var(--ci-card); border:1px solid var(--ci-border);
           border-radius:8px; padding:12px 14px; min-width:0; }
.ci-kpi-tk   { font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:700;
               color:var(--ci-text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.ci-kpi-name { font-size:10px; color:var(--ci-muted); margin-bottom:8px;
               white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.ci-kpi-value{ font-family:'JetBrains Mono',monospace; font-size:15px; font-weight:700; color:var(--ci-text); }
.ci-kpi-delta{ font-size:12px; font-weight:700; margin-top:3px; }
.ci-kpi-abs  { font-size:10px; color:var(--ci-muted); margin-top:1px; }

.ci-panel { background:var(--ci-card); border:1px solid var(--ci-border);
            border-radius:14px; padding:16px 18px; height:100%; }
.ci-panel-head { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:10px; }
.ci-panel-title { font-size:15px; font-weight:700; color:var(--ci-text); }
.ci-panel-tag   { font-family:'JetBrains Mono',monospace; font-size:11px; color:var(--ci-muted); }

.ci-table { width:100%; border-collapse:collapse; }
.ci-table th { font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:400;
               color:var(--ci-muted); text-align:left; padding:6px 8px; border-bottom:1px solid var(--ci-border); }
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
#  DATOS — cotizaciones
# ==============================================================
def _fmt_valor(v, tipo):
    if tipo == "yield":
        return f"{v:.2f}%"
    if tipo == "fx":
        return f"{v:.4f}"
    if tipo == "indice":
        return f"{v:,.2f}"
    return f"${v:,.0f}" if v >= 1000 else f"${v:,.2f}"


@st.cache_data(ttl=300, show_spinner=False)
def _calcular_kpis(items, _descargar_bulk, _get_close):
    """items: tupla de (nombre, ticker, tipo)."""
    df = _descargar_bulk([t for _, t, _ in items], period="inicio")
    salida = []
    for nombre, tk, tipo in items:
        fila = {"nombre": nombre, "ticker": tk, "valor": "S/D", "delta": "", "abs": "", "up": None}
        try:
            close = _get_close(df, tk)
            if close is not None and len(close) >= 2:
                actual, previo = float(close.iloc[-1]), float(close.iloc[-2])
                if tipo == "yield" and actual > 20:      # Yahoo a veces cotiza x10
                    actual, previo = actual / 10, previo / 10
                dif = actual - previo
                fila["valor"] = _fmt_valor(actual, tipo)
                if tipo == "yield":
                    fila["delta"] = f"{'▲' if dif >= 0 else '▼'} {abs(dif) * 100:.0f} bps"
                    fila["abs"] = f"{dif:+.2f} pp"
                else:
                    pct = (actual / previo - 1) * 100
                    fila["delta"] = f"{'▲' if pct >= 0 else '▼'} {abs(pct):.2f}%"
                    fila["abs"] = f"{dif:+.4f}" if tipo == "fx" else f"{dif:+,.2f}"
                fila["up"] = dif >= 0
        except Exception:
            pass
        salida.append(fila)
    return salida


# ==============================================================
#  RENDER — piezas
# ==============================================================
def _html_kpis(kpis):
    celdas = []
    for k in kpis:
        color = "#21262d" if k["up"] is None else ("#3fb950" if k["up"] else "#f85149")
        celdas.append(
            f'<div class="ci-kpi" style="border-top:2px solid {color}">'
            f'<div class="ci-kpi-tk">{html.escape(k["ticker"])}</div>'
            f'<div class="ci-kpi-name" title="{html.escape(k["nombre"])}">{html.escape(k["nombre"])}</div>'
            f'<div class="ci-kpi-value">{html.escape(k["valor"])}</div>'
            f'<div class="ci-kpi-delta" style="color:{color}">{html.escape(k["delta"])}</div>'
            f'<div class="ci-kpi-abs">{html.escape(k["abs"])}</div>'
            f'</div>'
        )
    return f'<div class="ci-kpis">{"".join(celdas)}</div>'


def _html_calendario(eventos, tag="Hoy"):
    if not eventos:
        cuerpo = '<div class="ci-empty">Sin eventos relevantes.</div>'
    else:
        filas = "".join(
            f'<tr><td class="ci-mono">{html.escape(str(e.get("hora") or e.get("pais") or ""))}</td>'
            f'<td>{html.escape(str(e.get("evento", "")))}</td>'
            f'<td class="ci-mono">{html.escape(str(e.get("prev", "--")))}</td>'
            f'<td class="ci-mono">{html.escape(str(e.get("consenso", "--")))}</td></tr>'
            for e in eventos
        )
        primera = "Hora" if any(e.get("hora") for e in eventos) else "País"
        cuerpo = (
            '<table class="ci-table"><thead><tr>'
            f'<th>{primera}</th><th>Evento</th><th>Prev.</th><th>Consenso</th>'
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
#  ENTRADA PÚBLICA
# ==============================================================
def render_inicio_dashboard(descargar_bulk, get_close_from_bulk,
                            eventos=None, noticias=None, watchlist=None, eventos_tag="Hoy"):
    wl = watchlist or WATCHLIST_DEFAULT
    items = tuple((w.get("nombre") or w.get("label"), w["ticker"], w.get("tipo", "precio")) for w in wl)

    st.markdown(_CSS, unsafe_allow_html=True)

    try:
        kpis = _calcular_kpis(items, descargar_bulk, get_close_from_bulk)
    except Exception:
        kpis = [{"nombre": n, "ticker": t, "valor": "S/D", "delta": "", "abs": "", "up": None}
                for n, t, _ in items]
    st.markdown(f'<div class="ci-root">{_html_kpis(kpis)}</div>', unsafe_allow_html=True)

    col_cal, col_news = st.columns(2, gap="medium")
    with col_cal:
        st.markdown(
            f'<div class="ci-root">{_html_calendario(EVENTOS_DEMO if eventos is None else eventos, eventos_tag)}</div>',
            unsafe_allow_html=True)
    with col_news:
        st.markdown(
            f'<div class="ci-root">{_html_noticias(NOTICIAS_DEMO if noticias is None else noticias)}</div>',
            unsafe_allow_html=True)
