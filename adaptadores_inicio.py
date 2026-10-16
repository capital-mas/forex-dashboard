# ==============================================================
#  ADAPTADORES — datos reales para el dashboard de Inicio
#
#  Salida (formato que espera render_inicio_dashboard):
#     eventos  -> [{fecha, pais, evento, prev, consenso}]   (+ etiqueta)
#     noticias -> [{fecha, ticker, titular, link, sentimiento}]
# ==============================================================

from datetime import date, datetime, timedelta

import streamlit as st

TABLA_CALENDARIO = "calendario_registro"
TABLA_NOTICIAS = "mercado_eventos"

# "Clase A" = eventos de impacto Muy Alto y Alto (campo `relevancia`).
IMPACTOS_CLASE_A = ["Muy Alto", "Alto"]
_ORDEN_IMPACTO = {"Muy Alto": 0, "Alto": 1}

_SENTIMIENTO = {"Positivo": "Alcista", "Negativo": "Bajista"}  # el resto -> Neutro

# Ventana del calendario: días hacia atrás / adelante respecto de hoy
DIAS_ATRAS, DIAS_ADELANTE = 7, 14

# Nombres posibles de la columna con el link de la noticia
_LINK_KEYS = ("link", "url", "enlace", "fuente_url", "link_noticia", "url_noticia")


def _fmt_valor(v, unidad):
    """4.0 + 'M' -> '4M' · 0.3 + '%' -> '0.3%' · None/NaN -> '--'."""
    if v is None or v != v:
        return "--"
    try:
        num = f"{float(v):g}"
    except (TypeError, ValueError):
        return str(v)
    unidad = "" if unidad is None else str(unidad).strip()
    if unidad.lower() in ("", "nan", "none"):
        return num
    return f"{num}{unidad}" if unidad == "%" else f"{num} {unidad}"


def _fecha_corta(iso):
    try:
        return datetime.fromisoformat(str(iso)).strftime("%d/%m")
    except Exception:
        return str(iso)


def _extraer_link(r):
    for k in _LINK_KEYS:
        v = r.get(k)
        if v and str(v).strip().lower().startswith(("http://", "https://")):
            return str(v).strip()
    # respaldo: cualquier columna cuyo nombre contenga link/url
    for k, v in r.items():
        if ("link" in k.lower() or "url" in k.lower()) and v \
                and str(v).strip().lower().startswith(("http://", "https://")):
            return str(v).strip()
    return ""


# ==============================================================
#  CALENDARIO — eventos Clase A (ventana de fechas, se filtra en el dashboard)
# ==============================================================
@st.cache_data(ttl=120, show_spinner=False)
def obtener_eventos_clase_a(_supabase, limite=300):
    """Devuelve (lista_de_eventos, etiqueta).

    Trae los eventos Clase A de los últimos DIAS_ATRAS y próximos DIAS_ADELANTE
    días, para que el dashboard pueda filtrar por país y fecha.
    Si la ventana está vacía, cae al último día que tenga datos.
    """
    cols = "fecha,pais,evento,relevancia,previsto,anterior,real,unidad"
    try:
        hoy = date.today()
        desde = (hoy - timedelta(days=DIAS_ATRAS)).isoformat()
        hasta = (hoy + timedelta(days=DIAS_ADELANTE)).isoformat()
        res = (_supabase.table(TABLA_CALENDARIO).select(cols)
               .gte("fecha", desde).lte("fecha", hasta)
               .in_("relevancia", IMPACTOS_CLASE_A)
               .order("fecha").limit(limite).execute())
        filas = res.data or []

        if not filas:
            ult = (_supabase.table(TABLA_CALENDARIO).select("fecha")
                   .in_("relevancia", IMPACTOS_CLASE_A).lte("fecha", hoy.isoformat())
                   .order("fecha", desc=True).limit(1).execute())
            if ult.data:
                res = (_supabase.table(TABLA_CALENDARIO).select(cols)
                       .eq("fecha", ult.data[0]["fecha"])
                       .in_("relevancia", IMPACTOS_CLASE_A).execute())
                filas = res.data or []
    except Exception:
        return [], "Hoy"

    filas.sort(key=lambda r: (str(r.get("fecha") or ""),
                              _ORDEN_IMPACTO.get(r.get("relevancia"), 9),
                              r.get("evento") or ""))

    eventos = [{
        "fecha": str(r.get("fecha") or "")[:10],
        "pais": r.get("pais") or "",
        "evento": r.get("evento") or "",
        # En el panel: "Prev." = dato anterior · "Consenso" = previsto
        "prev": _fmt_valor(r.get("anterior"), r.get("unidad")),
        "consenso": _fmt_valor(r.get("previsto"), r.get("unidad")),
    } for r in filas]
    return eventos, "Hoy"


# ==============================================================
#  NOTICIAS — últimas de mercado_eventos (con fecha y link)
# ==============================================================
@st.cache_data(ttl=120, show_spinner=False)
def obtener_noticias_inicio(_supabase, limite=5):
    try:
        res = (_supabase.table(TABLA_NOTICIAS).select("*")
               .order("fecha_evento", desc=True).order("created_at", desc=True)
               .limit(limite).execute())
    except Exception:
        return []

    noticias = []
    for r in (res.data or []):
        noticias.append({
            "fecha": str(r.get("fecha_evento") or r.get("created_at") or "")[:10],
            "titular": r.get("titulo") or "",
            "link": _extraer_link(r),
            "sentimiento": _SENTIMIENTO.get(r.get("impacto"), "Neutro"),
        })
    return noticias
