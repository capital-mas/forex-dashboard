# ==============================================================
#  ADAPTADORES — datos reales para el dashboard de Inicio
#
#  Leen DIRECTO de las tablas de Supabase (no importan nada de
#  modulo_calendario.py ni modulo_noticias_mercado.py), así el
#  Inicio queda desacoplado.
#
#  Salida (formato que espera render_inicio_dashboard):
#     eventos  -> [{pais, evento, prev, consenso}]   (+ etiqueta)
#     noticias -> [{ticker, titular, sentimiento}]
# ==============================================================

from datetime import date, datetime

import streamlit as st

TABLA_CALENDARIO = "calendario_registro"
TABLA_NOTICIAS = "mercado_eventos"

# "Clase A" = eventos de impacto Muy Alto y Alto (campo `relevancia`).
IMPACTOS_CLASE_A = ["Muy Alto", "Alto"]
_ORDEN_IMPACTO = {"Muy Alto": 0, "Alto": 1}

_SENTIMIENTO = {"Positivo": "Alcista", "Negativo": "Bajista"}  # el resto -> Neutro


def _fmt_valor(v, unidad):
    """4.0 + 'M' -> '4M' · 0.3 + '%' -> '0.3%' · None/NaN -> '--'."""
    if v is None or v != v:          # None o NaN
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


# ==============================================================
#  CALENDARIO — eventos Clase A del día
# ==============================================================
@st.cache_data(ttl=120, show_spinner=False)
def obtener_eventos_clase_a(_supabase, limite=6):
    """Devuelve (lista_de_eventos, etiqueta).

    - Si hay eventos Clase A con fecha de HOY -> los muestra, etiqueta 'Hoy'.
    - Si hoy no hay ninguno, cae al último día que sí tenga datos
      y lo avisa en la etiqueta ('Último: 14/10').
    """
    cols = "fecha,pais,evento,relevancia,previsto,anterior,real,unidad"
    try:
        hoy = date.today().isoformat()
        res = (_supabase.table(TABLA_CALENDARIO).select(cols)
               .eq("fecha", hoy).in_("relevancia", IMPACTOS_CLASE_A).execute())
        filas, etiqueta = res.data or [], "Hoy"

        if not filas:
            ult = (_supabase.table(TABLA_CALENDARIO).select("fecha")
                   .in_("relevancia", IMPACTOS_CLASE_A).lte("fecha", hoy)
                   .order("fecha", desc=True).limit(1).execute())
            if ult.data:
                fecha_ult = ult.data[0]["fecha"]
                res = (_supabase.table(TABLA_CALENDARIO).select(cols)
                       .eq("fecha", fecha_ult).in_("relevancia", IMPACTOS_CLASE_A).execute())
                filas, etiqueta = res.data or [], f"Último: {_fecha_corta(fecha_ult)}"
    except Exception:
        return [], "Hoy"

    filas.sort(key=lambda r: (_ORDEN_IMPACTO.get(r.get("relevancia"), 9), r.get("evento") or ""))

    eventos = [{
        "pais": r.get("pais") or "",
        "evento": r.get("evento") or "",
        # En el panel: "Prev." = dato anterior · "Consenso" = previsto
        "prev": _fmt_valor(r.get("anterior"), r.get("unidad")),
        "consenso": _fmt_valor(r.get("previsto"), r.get("unidad")),
    } for r in filas[:limite]]
    return eventos, etiqueta


# ==============================================================
#  NOTICIAS — últimas de mercado_eventos
# ==============================================================
@st.cache_data(ttl=120, show_spinner=False)
def obtener_noticias_inicio(_supabase, limite=5):
    try:
        res = (_supabase.table(TABLA_NOTICIAS)
               .select("ticker,empresa,pais,titulo,impacto,fecha_evento,created_at")
               .order("fecha_evento", desc=True).order("created_at", desc=True)
               .limit(limite).execute())
    except Exception:
        return []

    noticias = []
    for r in (res.data or []):
        etiqueta = (r.get("ticker") or "").strip() \
            or (r.get("empresa") or "").strip()[:12] \
            or (r.get("pais") or "").strip() or "—"
        noticias.append({
            "ticker": etiqueta,
            "titular": r.get("titulo") or "",
            "sentimiento": _SENTIMIENTO.get(r.get("impacto"), "Neutro"),
        })
    return noticias
