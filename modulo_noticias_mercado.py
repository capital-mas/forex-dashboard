# ==============================================================
#  MÓDULO "NOTICIAS + EVENTOS DE MERCADO" — Streamlit + Supabase
#  Sigue el mismo patrón que modulo_calendario.py: se integra como
#  un módulo nativo más de app.py.
#
#  Idea central: cada noticia NO es solo texto libre. Al elegir un
#  "tipo de evento" (ej. "Recompra de acciones (buyback)"), el
#  sistema autocompleta:
#
#       Evento → Grupo → Factor → Activos típicos → Impacto esperado
#
#  a partir de la taxonomía TIPOS_EVENTO de abajo. Eso permite
#  filtrar el feed por grupo (Macro / Empresas / Gobiernos / Bancos
#  Centrales / Geopolítica / Commodities / Mercados) y, con el
#  tiempo, comparar eventos del mismo tipo entre sí.
#
#  CLASIFICACIÓN — la ingesta automática (ingest_noticias.py) YA NO
#  intenta adivinar el tipo de evento de cada noticia: trae TODAS
#  las que encuentra y las guarda como "Sin clasificar". El
#  glosario (TIPOS_EVENTO) queda como referencia para que el propio
#  usuario, si tiene dudas sobre cómo interpretar una noticia, la
#  reclasifique a mano desde el feed (ver _tab_feed / "🏷️
#  Reclasificar" más abajo) — igual que cuando se carga un evento
#  manualmente.
#
#  "Reacción histórica": el sistema NO inventa estadísticas de
#  mercado. Lo que hace es dejar un campo (reaccion_pct) para que,
#  días después del evento, el admin cargue qué hizo el activo
#  principal. A partir de ahí, cada vez que se carga un evento
#  nuevo, el sistema busca eventos pasados del MISMO tipo (y, si
#  hay, del mismo ticker/país) que ya tengan reacción cargada, y
#  muestra el promedio real — no una cifra inventada. Al principio
#  va a estar vacío; se va llenando solo con el uso.
# ==============================================================

import streamlit as st
import pandas as pd
from datetime import date, datetime, timedelta

# ⚠️ Mismo criterio que en modulo_calendario.py: solo esta cuenta ve
# el formulario de carga. La protección real está en las políticas
# RLS de Supabase (ver mercado_eventos_schema.sql) — tiene que
# coincidir EXACTO con el email usado ahí.
ADMIN_EMAIL = "brainferreyra@gmail.com"

TABLA_EVENTOS = "mercado_eventos"

# Tipo de evento comodín para lo que llega sin clasificar (ver
# ingest_noticias.py) o lo que el admin todavía no reclasificó.
TIPO_SIN_CLASIFICAR = "Sin clasificar"

GRUPOS = ["Todas", "Macro", "Empresas", "Gobiernos", "Bancos Centrales",
          "Geopolítica", "Commodities", "Mercados"]

GRUPO_META = {
    "Macro":            {"emoji": "🌐", "color": "#8957e5"},
    "Empresas":         {"emoji": "🏢", "color": "#3a7bd5"},
    "Gobiernos":        {"emoji": "🏛️", "color": "#e3b341"},
    "Bancos Centrales": {"emoji": "🏦", "color": "#2ea043"},
    "Geopolítica":      {"emoji": "🌍", "color": "#f85149"},
    "Commodities":      {"emoji": "🛢️", "color": "#d29922"},
    "Mercados":         {"emoji": "📊", "color": "#6b7d9a"},
}

IMPACTO_META = {
    "Positivo":          {"emoji": "🟢", "color": "#2ea043"},
    "Negativo":          {"emoji": "🔴", "color": "#f85149"},
    "Mixto":             {"emoji": "🟡", "color": "#e3b341"},
    "Depende del caso":  {"emoji": "⚪", "color": "#8b949e"},
}


# ==============================================================
#  TAXONOMÍA — Evento → Grupo / Factor / Impacto / Activos típicos
#  Esto es lo que reemplaza el "tipear todo a mano" por una carga
#  guiada. Se puede seguir ampliando con el tiempo.
# ==============================================================
TIPOS_EVENTO = {
    # ---------------- SIN CLASIFICAR ----------------
    # Tipo comodín: lo usa la ingesta automática para TODA noticia
    # que trae (ya no intenta adivinar el tipo — ver nota arriba),
    # y también sirve si un admin quiere cargar algo a mano sin
    # decidir todavía en qué categoría entra. La idea es que el
    # usuario, mirando el resto del glosario de abajo, elija a mano
    # el tipo correcto cuando tenga tiempo de revisarla.
    "Sin clasificar": {
        "grupo": "Mercados",
        "factor": "Noticia sin clasificar — consultar el glosario para interpretarla y reclasificarla manualmente",
        "impacto": "Depende del caso", "activos": []},

    # ---------------- EMPRESAS ----------------
    "Recompra de acciones (buyback)": {
        "grupo": "Empresas", "factor": "Demanda de acciones / mejora de EPS",
        "impacto": "Positivo", "activos": ["Acción de la empresa"]},
    "Aumento de dividendo": {
        "grupo": "Empresas", "factor": "Retorno al accionista / señal de solidez de caja",
        "impacto": "Positivo", "activos": ["Acción de la empresa"]},
    "Recorte o suspensión de dividendo": {
        "grupo": "Empresas", "factor": "Deterioro de caja / señal de estrés financiero",
        "impacto": "Negativo", "activos": ["Acción de la empresa"]},
    "Insider buying (compra de directivos)": {
        "grupo": "Empresas", "factor": "Señal de confianza interna",
        "impacto": "Positivo", "activos": ["Acción de la empresa"]},
    "Insider selling (venta de directivos)": {
        "grupo": "Empresas", "factor": "Señal de cautela interna (o diversificación personal)",
        "impacto": "Depende del caso", "activos": ["Acción de la empresa"]},
    "M&A - Anuncio de adquisición (empresa objetivo)": {
        "grupo": "Empresas", "factor": "Prima de adquisición sobre el precio de mercado",
        "impacto": "Positivo", "activos": ["Acción de la empresa objetivo"]},
    "M&A - Anuncio de adquisición (empresa compradora)": {
        "grupo": "Empresas", "factor": "Riesgo de integración / mayor apalancamiento",
        "impacto": "Mixto", "activos": ["Acción de la empresa compradora"]},
    "M&A - Ruptura o cancelación de acuerdo": {
        "grupo": "Empresas", "factor": "Pérdida de la prima / sinergias esperadas",
        "impacto": "Negativo", "activos": ["Ambas empresas involucradas"]},
    "Spin-off / escisión de una división": {
        "grupo": "Empresas", "factor": "Desbloqueo de valor / mayor foco estratégico",
        "impacto": "Positivo", "activos": ["Empresa madre", "Nueva empresa escindida"]},
    "IPO / salida a bolsa": {
        "grupo": "Empresas", "factor": "Nueva oferta de acciones al mercado",
        "impacto": "Depende del caso", "activos": ["Nueva acción", "Sector comparable"]},
    "Emisión de deuda corporativa": {
        "grupo": "Empresas", "factor": "Mayor apalancamiento / costo de financiamiento",
        "impacto": "Depende del caso", "activos": ["Bonos de la empresa", "Acción de la empresa"]},
    "Recompra o cancelación anticipada de deuda": {
        "grupo": "Empresas", "factor": "Reducción de apalancamiento",
        "impacto": "Positivo", "activos": ["Bonos de la empresa", "Acción de la empresa"]},
    "Cambio de calificación crediticia - upgrade": {
        "grupo": "Empresas", "factor": "Menor costo de financiamiento futuro",
        "impacto": "Positivo", "activos": ["Bonos del emisor", "Acción o moneda del emisor"]},
    "Cambio de calificación crediticia - downgrade": {
        "grupo": "Empresas", "factor": "Mayor costo de financiamiento futuro",
        "impacto": "Negativo", "activos": ["Bonos del emisor", "Acción o moneda del emisor"]},
    "Cambio de CEO / alta gerencia": {
        "grupo": "Empresas", "factor": "Gobierno corporativo / continuidad estratégica",
        "impacto": "Depende del caso", "activos": ["Acción de la empresa"]},
    "Resultados trimestrales - superan expectativas": {
        "grupo": "Empresas", "factor": "Sorpresa positiva de utilidades",
        "impacto": "Positivo", "activos": ["Acción de la empresa"]},
    "Resultados trimestrales - debajo de expectativas": {
        "grupo": "Empresas", "factor": "Sorpresa negativa de utilidades",
        "impacto": "Negativo", "activos": ["Acción de la empresa"]},
    "Guidance corporativo - mejora de proyecciones": {
        "grupo": "Empresas", "factor": "Expectativas futuras de ganancias",
        "impacto": "Positivo", "activos": ["Acción de la empresa"]},
    "Guidance corporativo - recorte de proyecciones": {
        "grupo": "Empresas", "factor": "Expectativas futuras de ganancias",
        "impacto": "Negativo", "activos": ["Acción de la empresa"]},
    "Litigio o demanda relevante": {
        "grupo": "Empresas", "factor": "Riesgo legal / contingencias",
        "impacto": "Negativo", "activos": ["Acción de la empresa"]},
    "Retiro de producto / recall": {
        "grupo": "Empresas", "factor": "Riesgo reputacional y de costos",
        "impacto": "Negativo", "activos": ["Acción de la empresa"]},
    "Aprobación regulatoria de producto (ej. FDA)": {
        "grupo": "Empresas", "factor": "Habilitación de nuevos ingresos",
        "impacto": "Positivo", "activos": ["Acción de la empresa"]},
    "Rechazo regulatorio de producto": {
        "grupo": "Empresas", "factor": "Pérdida de ingresos esperados",
        "impacto": "Negativo", "activos": ["Acción de la empresa"]},
    "Huelga o conflicto sindical": {
        "grupo": "Empresas", "factor": "Interrupción operativa / costos laborales",
        "impacto": "Negativo", "activos": ["Acción de la empresa", "Sector"]},
    "Quiebra / concurso de acreedores": {
        "grupo": "Empresas", "factor": "Riesgo de crédito extremo",
        "impacto": "Negativo", "activos": ["Acción y bonos de la empresa"]},
    "Ciberataque / brecha de seguridad": {
        "grupo": "Empresas", "factor": "Riesgo operativo y reputacional",
        "impacto": "Negativo", "activos": ["Acción de la empresa"]},

    # ---------------- GOBIERNOS ----------------
    "Regulación nueva o más estricta": {
        "grupo": "Gobiernos", "factor": "Costos de cumplimiento / barreras de entrada",
        "impacto": "Depende del caso", "activos": ["Sector regulado"]},
    "Desregulación / flexibilización normativa": {
        "grupo": "Gobiernos", "factor": "Reducción de costos de cumplimiento",
        "impacto": "Positivo", "activos": ["Sector desregulado"]},
    "Subsidio sectorial": {
        "grupo": "Gobiernos", "factor": "Ayuda estatal directa",
        "impacto": "Positivo", "activos": ["Sector beneficiado"]},
    "Inversión pública / obra de infraestructura": {
        "grupo": "Gobiernos", "factor": "Gasto público / demanda agregada",
        "impacto": "Positivo", "activos": ["Sector construcción", "Sector industrial"]},
    "Suba de impuestos": {
        "grupo": "Gobiernos", "factor": "Presión sobre la rentabilidad neta",
        "impacto": "Negativo", "activos": ["Sector afectado", "Consumo"]},
    "Baja de impuestos": {
        "grupo": "Gobiernos", "factor": "Mejora de la rentabilidad neta",
        "impacto": "Positivo", "activos": ["Sector afectado", "Consumo"]},
    "Suba de retenciones a las exportaciones": {
        "grupo": "Gobiernos", "factor": "Mayor costo sobre exportadores",
        "impacto": "Negativo", "activos": ["Sector exportador", "Moneda local"]},
    "Baja de retenciones a las exportaciones": {
        "grupo": "Gobiernos", "factor": "Alivio sobre exportadores",
        "impacto": "Positivo", "activos": ["Sector exportador", "Moneda local"]},
    "Riesgo país - suba": {
        "grupo": "Gobiernos", "factor": "Riesgo soberano / costo de financiamiento externo",
        "impacto": "Negativo",
        "activos": ["Bonos soberanos", "Bancos", "Índice bursátil local", "Moneda local"]},
    "Riesgo país - baja": {
        "grupo": "Gobiernos", "factor": "Riesgo soberano / costo de financiamiento externo",
        "impacto": "Positivo",
        "activos": ["Bonos soberanos", "Bancos", "Índice bursátil local", "Moneda local"]},
    "Default soberano": {
        "grupo": "Gobiernos", "factor": "Evento de crédito soberano",
        "impacto": "Negativo", "activos": ["Bonos soberanos", "Bancos", "Moneda local"]},
    "Reestructuración de deuda soberana": {
        "grupo": "Gobiernos", "factor": "Extensión de plazos / quita sobre la deuda",
        "impacto": "Depende del caso", "activos": ["Bonos soberanos", "Moneda local"]},
    "Control de capitales / cepo cambiario": {
        "grupo": "Gobiernos", "factor": "Restricción de acceso a divisas",
        "impacto": "Negativo", "activos": ["Moneda local", "Bonos soberanos"]},
    "Congelamiento de depósitos / corralito": {
        "grupo": "Gobiernos", "factor": "Pérdida de confianza en el sistema financiero",
        "impacto": "Negativo", "activos": ["Bancos", "Moneda local"]},
    "Nacionalización de empresa o activo": {
        "grupo": "Gobiernos", "factor": "Pérdida de control privado / riesgo expropiatorio",
        "impacto": "Negativo", "activos": ["Empresa afectada", "Sector"]},
    "Privatización de empresa estatal": {
        "grupo": "Gobiernos", "factor": "Apertura a capital privado",
        "impacto": "Positivo", "activos": ["Empresa privatizada", "Índice bursátil local"]},
    "Elecciones / cambio de gobierno": {
        "grupo": "Gobiernos", "factor": "Incertidumbre o certidumbre sobre el rumbo económico",
        "impacto": "Depende del caso", "activos": ["Moneda local", "Bonos soberanos", "Índice bursátil local"]},
    "Golpe de Estado / crisis institucional": {
        "grupo": "Gobiernos", "factor": "Riesgo institucional extremo",
        "impacto": "Negativo", "activos": ["Moneda local", "Bonos soberanos", "Índice bursátil local"]},

    # ---------------- BANCOS CENTRALES ----------------
    "Suba de tasas de interés": {
        "grupo": "Bancos Centrales", "factor": "Costo del dinero",
        "impacto": "Depende del caso", "activos": ["Moneda local", "Bonos", "Acciones"]},
    "Baja de tasas de interés": {
        "grupo": "Bancos Centrales", "factor": "Costo del dinero",
        "impacto": "Depende del caso", "activos": ["Moneda local", "Bonos", "Acciones"]},
    "Emisión monetaria / expansión de balance (QE)": {
        "grupo": "Bancos Centrales", "factor": "Mayor oferta de dinero",
        "impacto": "Depende del caso", "activos": ["Moneda local", "Oro", "Acciones", "Cripto"]},
    "Contracción monetaria (QT)": {
        "grupo": "Bancos Centrales", "factor": "Menor oferta de dinero",
        "impacto": "Depende del caso", "activos": ["Moneda local", "Oro", "Acciones", "Cripto"]},
    "Intervención cambiaria - venta de reservas": {
        "grupo": "Bancos Centrales", "factor": "Mayor oferta de divisas en el mercado",
        "impacto": "Positivo", "activos": ["Moneda local"]},
    "Intervención cambiaria - compra de divisas": {
        "grupo": "Bancos Centrales", "factor": "Menor oferta de divisas en el mercado",
        "impacto": "Negativo", "activos": ["Moneda local"]},
    "Comunicado con sesgo restrictivo (hawkish)": {
        "grupo": "Bancos Centrales", "factor": "Expectativas de política monetaria más dura",
        "impacto": "Depende del caso", "activos": ["Moneda local", "Bonos", "Acciones"]},
    "Comunicado con sesgo expansivo (dovish)": {
        "grupo": "Bancos Centrales", "factor": "Expectativas de política monetaria más laxa",
        "impacto": "Depende del caso", "activos": ["Moneda local", "Bonos", "Acciones"]},
    "Cambio de titular del banco central": {
        "grupo": "Bancos Centrales", "factor": "Expectativas de continuidad de la política monetaria",
        "impacto": "Depende del caso", "activos": ["Moneda local", "Bonos"]},

    # ---------------- GEOPOLÍTICA ----------------
    "Guerra o conflicto armado - inicio / escalada": {
        "grupo": "Geopolítica", "factor": "Riesgo geopolítico / disrupción de oferta",
        "impacto": "Negativo", "activos": ["Oro", "Dólar", "Petróleo", "Defensa", "Acciones globales"]},
    "Acuerdo de paz / desescalada de conflicto": {
        "grupo": "Geopolítica", "factor": "Reducción del riesgo geopolítico",
        "impacto": "Positivo", "activos": ["Acciones globales", "Petróleo"]},
    "Sanciones económicas - imposición": {
        "grupo": "Geopolítica", "factor": "Restricción de acceso a mercados o capital",
        "impacto": "Negativo", "activos": ["País/empresas sancionadas", "Commodities relacionados"]},
    "Sanciones económicas - levantamiento": {
        "grupo": "Geopolítica", "factor": "Reapertura de acceso a mercados o capital",
        "impacto": "Positivo", "activos": ["País/empresas beneficiadas"]},
    "Aranceles - imposición": {
        "grupo": "Geopolítica", "factor": "Mayor costo del comercio internacional",
        "impacto": "Depende del caso", "activos": ["Sector afectado", "Competidores locales"]},
    "Aranceles - eliminación o reducción": {
        "grupo": "Geopolítica", "factor": "Menor costo del comercio internacional",
        "impacto": "Positivo", "activos": ["Sector beneficiado"]},
    "Acuerdo comercial - firma": {
        "grupo": "Geopolítica", "factor": "Apertura comercial entre países",
        "impacto": "Positivo", "activos": ["Sectores exportadores de ambos países"]},
    "Acuerdo comercial - ruptura": {
        "grupo": "Geopolítica", "factor": "Cierre comercial entre países",
        "impacto": "Negativo", "activos": ["Sectores exportadores de ambos países"]},
    "Atentado o ataque de alto impacto": {
        "grupo": "Geopolítica", "factor": "Shock de aversión al riesgo",
        "impacto": "Negativo", "activos": ["Oro", "Dólar", "Acciones globales"]},

    # ---------------- COMMODITIES ----------------
    "OPEP - recorte de producción": {
        "grupo": "Commodities", "factor": "Menor oferta de petróleo",
        "impacto": "Positivo", "activos": ["Petróleo", "Monedas petroleras"]},
    "OPEP - aumento de producción": {
        "grupo": "Commodities", "factor": "Mayor oferta de petróleo",
        "impacto": "Negativo", "activos": ["Petróleo", "Monedas petroleras"]},
    "Problemas de suministro / cuello de botella logístico": {
        "grupo": "Commodities", "factor": "Restricción de oferta",
        "impacto": "Positivo", "activos": ["Commodity afectado"]},
    "Catástrofe natural con impacto en producción": {
        "grupo": "Commodities", "factor": "Shock de oferta (huracán, sequía, terremoto)",
        "impacto": "Positivo", "activos": ["Commodity afectado"]},
    "Huelga en sector productor de commodities": {
        "grupo": "Commodities", "factor": "Interrupción de oferta (minería, energía)",
        "impacto": "Positivo", "activos": ["Commodity afectado"]},
    "Descubrimiento de nuevas reservas o yacimientos": {
        "grupo": "Commodities", "factor": "Expectativa de mayor oferta futura",
        "impacto": "Negativo", "activos": ["Commodity afectado"]},
    "Cambio de cuotas o aranceles a un commodity": {
        "grupo": "Commodities", "factor": "Oferta / demanda relativa del commodity",
        "impacto": "Depende del caso", "activos": ["Commodity afectado"]},

    # ---------------- MERCADOS / MACRO ----------------
    "Pandemia / emergencia sanitaria global": {
        "grupo": "Mercados", "factor": "Shock simultáneo de oferta y demanda",
        "impacto": "Negativo", "activos": ["Acciones globales", "Petróleo", "Bonos refugio"]},
    "Corte de suministro energético (gas, electricidad)": {
        "grupo": "Mercados", "factor": "Shock de costos energéticos",
        "impacto": "Negativo", "activos": ["Sector industrial", "Consumo"]},
    "Corrección abrupta / burbuja de mercado": {
        "grupo": "Mercados", "factor": "Reversión de expectativas",
        "impacto": "Negativo", "activos": ["Acciones", "Cripto"]},
    "Cambio regulatorio sistémico (ej. requisitos de capital bancario)": {
        "grupo": "Mercados", "factor": "Costo de capital del sistema financiero",
        "impacto": "Negativo", "activos": ["Bancos"]},
}

# "Sin clasificar" se ordena aparte, primero, para que sea fácil de
# encontrar en el selectbox de carga/reclasificación manual — el
# resto sigue ordenado por grupo y nombre como antes.
TIPOS_EVENTO_ORDENADOS = [TIPO_SIN_CLASIFICAR] + sorted(
    (e for e in TIPOS_EVENTO.keys() if e != TIPO_SIN_CLASIFICAR),
    key=lambda e: (TIPOS_EVENTO[e]["grupo"], e),
)


# ==============================================================
#  HELPERS
# ==============================================================

def _es_admin(user_email):
    return bool(user_email) and user_email.strip().lower() == ADMIN_EMAIL.strip().lower()


def _badge(texto, color, bg_alpha="22"):
    return (f'<span style="display:inline-block;padding:3px 10px;border-radius:12px;'
            f'font-size:11px;font-weight:700;background:{color}{bg_alpha};color:{color};'
            f'border:1px solid {color}55;margin-right:6px;margin-bottom:4px">{texto}</span>')


def _badges_evento(tipo_evento_info):
    grupo = tipo_evento_info.get("grupo", "")
    impacto = tipo_evento_info.get("impacto", "")
    gm = GRUPO_META.get(grupo, {"emoji": "", "color": "#8b949e"})
    im = IMPACTO_META.get(impacto, {"emoji": "", "color": "#8b949e"})
    html = _badge(f'{gm["emoji"]} {grupo}', gm["color"])
    html += _badge(f'{im["emoji"]} {impacto}', im["color"])
    return html


@st.cache_data(ttl=120, show_spinner=False)
def _obtener_eventos(_supabase, limite=500):
    res = (_supabase.table(TABLA_EVENTOS).select("*")
           .order("fecha_evento", desc=True).order("created_at", desc=True)
           .limit(limite).execute())
    return res.data or []


def _limpiar_cache_eventos():
    _obtener_eventos.clear()
    _obtener_eventos_calendario.clear()


# ==============================================================
#  PUENTE CON EL CALENDARIO ECONÓMICO
#  El Calendario Económico (modulo_calendario.py) ya tiene su propia
#  carga de datos macro (IPC, tasas, PBI, PMI...) con previsto/real e
#  interpretación calculada. En vez de volver a cargar esos mismos
#  eventos acá, los leemos directo de su tabla (calendario_registro)
#  y los mostramos como eventos de solo lectura dentro de este feed,
#  clasificados automáticamente en un grupo de Noticias + Eventos de
#  Mercado. Así el admin carga el dato UNA sola vez, en el Calendario.
# ==============================================================

TABLA_CALENDARIO = "calendario_registro"

# Categoría del Calendario Económico -> Grupo de este módulo.
CATEGORIA_CALENDARIO_A_GRUPO = {
    "Inflación": "Macro", "Empleo": "Macro", "Actividad Económica": "Macro",
    "Consumo": "Macro", "Crecimiento": "Macro", "Industria": "Macro",
    "Vivienda": "Macro", "Comercio Exterior": "Macro", "Sentimiento Empresarial": "Macro",
    "Agricultura": "Commodities", "Energía": "Commodities",
    "Política Monetaria": "Bancos Centrales", "Crédito": "Bancos Centrales",
    "Deuda Pública": "Bancos Centrales",
    "Política Fiscal": "Gobiernos",
    "Posicionamiento Especulativo": "Mercados",
    "Comentarios de Funcionarios": "Bancos Centrales",
    "Comentarios Políticos": "Geopolítica",
    "Evento Especial": "Bancos Centrales",
}


def _impacto_desde_impacto_mercado(impacto_mercado):
    """Traduce el texto de impacto_mercado del Calendario (ej. '🟢 BUEN DATO
    PARA EL MERCADO') al vocabulario de impacto de este módulo."""
    txt = (impacto_mercado or "").upper()
    if "BUEN DATO" in txt:
        return "Positivo"
    if "MAL DATO" in txt:
        return "Negativo"
    if "NEUTRO" in txt or "CUALITATIVO" in txt:
        return "Depende del caso"
    return "Depende del caso"


@st.cache_data(ttl=120, show_spinner=False)
def _obtener_eventos_calendario(_supabase, limite=200):
    """Trae los últimos eventos ya cargados en el Calendario Económico y
    los adapta al formato de este feed — solo lectura, no se guarda nada
    nuevo en la base."""
    try:
        res = (_supabase.table(TABLA_CALENDARIO).select("*")
               .order("fecha", desc=True).order("created_at", desc=True)
               .limit(limite).execute())
    except Exception:
        return []

    filas = []
    for row in (res.data or []):
        categoria = ""  # el registro del calendario no guarda la categoría directamente
        evento_nombre = row.get("evento") or ""
        filas.append({
            "id": f"cal_{row.get('id')}",
            "es_calendario": True,
            "fecha_evento": row.get("fecha"),
            "titulo": f"{evento_nombre} — {row.get('pais','')}",
            "contenido": row.get("lectura_macro") or row.get("notas") or "",
            "tipo_evento": evento_nombre,
            "grupo": "Macro",  # se podría refinar cruzando con EVENTOS de modulo_calendario si se importa
            "factor": "Dato económico programado (Calendario Económico)",
            "impacto": _impacto_desde_impacto_mercado(row.get("impacto_mercado")),
            "empresa": "", "ticker": "", "pais": row.get("pais") or "",
            "sector": "", "activos_afectados": row.get("divisas") or "",
            "monto": None, "moneda_monto": "", "fuente_url": "",
            "reaccion_pct": None, "reaccion_activo": "", "reaccion_plazo": "",
            "notas": row.get("notas") or "",
        })
    return filas


def _guardar_evento(supabase, datos, user_id, user_email):
    info = TIPOS_EVENTO.get(datos["tipo_evento"], {})
    row = {
        "autor_id": user_id, "autor_email": user_email,
        "fecha_evento": str(datos["fecha_evento"]),
        "titulo": datos["titulo"].strip(),
        "contenido": (datos.get("contenido") or "").strip(),
        "tipo_evento": datos["tipo_evento"],
        "grupo": info.get("grupo", "Mercados"),
        "factor": info.get("factor", ""),
        "impacto": datos.get("impacto_override") or info.get("impacto", "Depende del caso"),
        "empresa": (datos.get("empresa") or "").strip(),
        "ticker": (datos.get("ticker") or "").strip().upper(),
        "pais": (datos.get("pais") or "").strip(),
        "sector": (datos.get("sector") or "").strip(),
        "activos_afectados": datos.get("activos_afectados") or ", ".join(info.get("activos", [])),
        "monto": None,
        "moneda_monto": "",
        "fuente_url": (datos.get("fuente_url") or "").strip(),
        "reaccion_pct": datos.get("reaccion_pct"),
        "reaccion_activo": (datos.get("reaccion_activo") or "").strip(),
        "reaccion_plazo": (datos.get("reaccion_plazo") or "").strip(),
        "notas": (datos.get("notas") or "").strip(),
    }
    supabase.table(TABLA_EVENTOS).insert(row).execute()


def _actualizar_reaccion(supabase, evento_id, reaccion_pct, reaccion_activo, reaccion_plazo):
    supabase.table(TABLA_EVENTOS).update({
        "reaccion_pct": reaccion_pct,
        "reaccion_activo": (reaccion_activo or "").strip(),
        "reaccion_plazo": (reaccion_plazo or "").strip(),
    }).eq("id", evento_id).execute()


def _reclasificar_evento(supabase, evento_id, nuevo_tipo, impacto_override=None):
    """Aplica un tipo de evento del glosario a una noticia ya cargada
    (típicamente una que llegó como 'Sin clasificar' desde la ingesta
    automática). Recalcula grupo/factor/activos igual que en el alta
    manual; el impacto se puede pisar puntualmente si el caso concreto
    lo amerita, igual que en _tab_registrar."""
    info = TIPOS_EVENTO.get(nuevo_tipo, {})
    supabase.table(TABLA_EVENTOS).update({
        "tipo_evento": nuevo_tipo,
        "grupo": info.get("grupo", "Mercados"),
        "factor": info.get("factor", ""),
        "impacto": impacto_override or info.get("impacto", "Depende del caso"),
        "activos_afectados": ", ".join(info.get("activos", [])),
    }).eq("id", evento_id).execute()


def _borrar_evento(supabase, evento_id):
    supabase.table(TABLA_EVENTOS).delete().eq("id", evento_id).execute()

def _eliminar_noticias_antiguas(supabase, dias=7):
    """Elimina de mercado_eventos las noticias cuya fecha_evento tiene
    más de `dias` días respecto de hoy. No afecta a calendario_registro
    (esos eventos se manejan y se borran desde el Calendario Económico)."""
    fecha_limite = date.today() - timedelta(days=dias)
    try:
        supabase.table(TABLA_EVENTOS).delete().lt("fecha_evento", str(fecha_limite)).execute()
    except Exception as e:
        print(f"[modulo_noticias_mercado] Error al limpiar noticias antiguas: {e}")


def _limpieza_automatica(supabase):
    hoy = date.today().isoformat()
    if st.session_state.get("me_limpieza_hecha") != hoy:
        _eliminar_noticias_antiguas(supabase, dias=7)
        _limpiar_cache_eventos()
        st.session_state["me_limpieza_hecha"] = hoy

def _eventos_similares(df_todos, tipo_evento, ticker=None, pais=None, excluir_id=None):
    """Busca eventos pasados del MISMO tipo (y, si hay ticker/país
    cargado, prioriza esos también) que ya tengan una reacción
    observada cargada. Devuelve (df_con_reaccion, df_mismo_tipo_total,
    promedio_reaccion_o_None)."""
    df = df_todos[df_todos["tipo_evento"] == tipo_evento].copy()
    if excluir_id is not None:
        df = df[df["id"] != excluir_id]

    df_con_reaccion = df[df["reaccion_pct"].notna()].copy()

    # Si hay ticker o país, se muestra primero ese recorte más
    # específico; si no hay suficientes casos, se cae al total del
    # tipo de evento.
    df_especifico = df_con_reaccion
    if ticker:
        df_esp_ticker = df_con_reaccion[df_con_reaccion["ticker"].str.upper() == ticker.upper()]
        if not df_esp_ticker.empty:
            df_especifico = df_esp_ticker
    elif pais:
        df_esp_pais = df_con_reaccion[df_con_reaccion["pais"] == pais]
        if not df_esp_pais.empty:
            df_especifico = df_esp_pais

    promedio = df_especifico["reaccion_pct"].mean() if not df_especifico.empty else None
    return df_especifico.sort_values("fecha_evento", ascending=False), df, promedio


def _render_similares(df_todos, tipo_evento, ticker=None, pais=None, excluir_id=None, key_sufijo=""):
    df_similares, df_mismo_tipo, promedio = _eventos_similares(
        df_todos, tipo_evento, ticker, pais, excluir_id
    )
    total_mismo_tipo = len(df_mismo_tipo)

    if total_mismo_tipo == 0:
        st.caption("📊 Este es el primer evento cargado de este tipo — todavía no hay histórico para comparar.")
        return

    if promedio is None:
        st.caption(
            f"📊 Hay {total_mismo_tipo} evento(s) previo(s) de **{tipo_evento}**, pero ninguno "
            "tiene todavía una reacción de mercado cargada. En cuanto se complete ese dato en "
            "alguno, acá va a aparecer el promedio real."
        )
        return

    emoji = "🟢" if promedio > 0 else ("🔴" if promedio < 0 else "⚪")
    st.markdown(
        f"📊 **Reacción histórica real** de {len(df_similares)} evento(s) similares "
        f"de **{tipo_evento}**{' (mismo ticker/país cuando fue posible)' if (ticker or pais) else ''}: "
        f"{emoji} **{promedio:+.2f}%** promedio."
    )
    tabla = df_similares[["fecha_evento", "empresa", "pais", "ticker", "reaccion_activo",
                           "reaccion_pct", "reaccion_plazo"]].rename(columns={
        "fecha_evento": "Fecha", "empresa": "Empresa", "pais": "País", "ticker": "Ticker",
        "reaccion_activo": "Activo medido", "reaccion_pct": "Reacción %", "reaccion_plazo": "Plazo",
    })
    st.dataframe(tabla, use_container_width=True, hide_index=True)


# ==============================================================
#  FORMULARIO DE CARGA (solo admin)
# ==============================================================

def _tab_registrar(supabase, user_id, user_email):
    st.caption(
        "Elegí el tipo de evento: el sistema autocompleta grupo, factor de impacto y activos "
        "típicos. Podés ajustar el impacto puntual si el caso concreto lo amerita. Si no estás "
        "seguro todavía, podés dejarlo como \"Sin clasificar\" y reclasificarlo después desde el feed."
    )

    c1, c2 = st.columns([1, 2])
    with c1:
        fecha_evento = st.date_input("📅 Fecha del evento", value=date.today(), key="me_fecha")
    with c2:
        titulo = st.text_input("Título de la noticia", key="me_titulo",
                                placeholder="Ej: Apple anuncia recompra de USD 10.000 M")

    tipo_evento = st.selectbox("🏷️ Tipo de evento", TIPOS_EVENTO_ORDENADOS, key="me_tipo")
    info = TIPOS_EVENTO.get(tipo_evento, {})

    # Cuando cambia el tipo de evento, forzamos el impacto y los activos
    # afectados a los valores de la taxonomía ANTES de instanciar los
    # widgets de abajo. Si no se hace así, Streamlit conserva el último
    # valor tipeado/seleccionado en esos widgets (porque tienen "key")
    # y el autocompletado no se nota al cambiar de tipo de evento.
    if st.session_state.get("me_tipo_anterior") != tipo_evento:
        st.session_state["me_impacto"] = info.get("impacto", "Depende del caso")
        st.session_state["me_tipo_anterior"] = tipo_evento

    st.markdown(_badges_evento(info), unsafe_allow_html=True)
    st.caption(f"**Factor:** {info.get('factor','')}")

    impactos = list(IMPACTO_META.keys())
    impacto_override = st.selectbox(
        "⚡ Impacto para este caso puntual", impactos, key="me_impacto",
        help="Precargado según el tipo de evento; ajustalo si este caso concreto es distinto al típico.",
    )

    st.markdown("##### 🎯 Contexto del evento")
    e1, e2 = st.columns([1, 2])
    with e1:
        tipo_entidad = st.radio(
            "¿A qué afecta principalmente?", ["Empresa", "País / países", "No aplica"],
            key="me_tipo_entidad", horizontal=True,
        )
    with e2:
        if tipo_entidad == "Empresa":
            empresa = st.text_input(
                "Empresa(s) / ticker(s)", key="me_empresa",
                placeholder="Ej: Apple (AAPL) — separá con comas si son varias",
            )
        elif tipo_entidad == "País / países":
            empresa = st.text_input(
                "País(es)", key="me_empresa",
                placeholder="Ej: Argentina, Brasil — separá con comas si son varios",
            )
        else:
            empresa = ""

    e3, e4 = st.columns(2)
    with e3:
        ticker = st.text_input(
            "Ticker principal (opcional)", key="me_ticker", placeholder="Ej: AAPL",
            disabled=(tipo_entidad != "Empresa"),
        )
    with e4:
        sector = st.text_input("Sector", key="me_sector", placeholder="Ej: Tecnología, Energía, Bancos...")

    # El país sigue existiendo como campo propio (se usa para cruzar
    # con la reacción histórica y con el Calendario Económico), pero
    # solo se pide cuando el evento afecta a un país/países.
    if tipo_entidad == "País / países":
        pais = st.selectbox("País principal (para el cruce con el histórico)", [""] + [
            "Alemania", "Arabia Saudita", "Argentina", "Australia", "Brasil", "Canadá", "Chile",
            "China", "Colombia", "Corea del Sur", "España", "Estados Unidos", "Europa", "Francia",
            "India", "Indonesia", "Italia", "Japón", "México", "Perú", "Reino Unido", "Rusia",
            "Sudáfrica", "Turquía", "Otro",
        ], key="me_pais")
    else:
        pais = ""

    # Los activos afectados vienen SOLOS de la taxonomía, según el tipo
    # de evento elegido. No es un campo que carga el analista.
    st.markdown(
        f"**Activos afectados (automático según el tipo de evento):** "
        f"{', '.join(info.get('activos', [])) or '—'}"
    )
    activos_afectados = ", ".join(info.get("activos", []))

    fuente_url = st.text_input("Fuente (URL)", key="me_fuente")

    contenido = st.text_area("Contenido / detalle de la noticia", key="me_contenido", height=110)
    notas = st.text_input("Notas del analista (opcional)", key="me_notas")

    with st.expander("📈 Reacción de mercado observada (completar más adelante si todavía no se sabe)"):
        r1, r2, r3 = st.columns(3)
        with r1:
            reaccion_pct = st.number_input("Reacción (%)", value=None, format="%.2f", key="me_reaccion_pct")
        with r2:
            reaccion_activo = st.text_input("Activo medido", key="me_reaccion_activo", value=ticker)
        with r3:
            reaccion_plazo = st.selectbox(
                "Plazo", ["", "Intradía", "1 día", "1 semana", "1 mes"], key="me_reaccion_plazo",
            )

    # Vista previa de eventos similares ANTES de guardar, para que el
    # analista tenga contexto histórico mientras carga el evento nuevo.
    df_actual = pd.DataFrame(_obtener_eventos(supabase))
    if not df_actual.empty:
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
        _render_similares(df_actual, tipo_evento, ticker=ticker or None, pais=pais or None,
                           key_sufijo="registrar")

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    b1, b2 = st.columns(2)
    with b1:
        if st.button("🗑️ Limpiar", use_container_width=True, key="me_btn_limpiar"):
            for k in list(st.session_state.keys()):
                if k.startswith("me_"):
                    st.session_state.pop(k, None)
            st.rerun()
    with b2:
        if st.button("📰 Publicar evento", type="primary", use_container_width=True, key="me_btn_guardar"):
            if not titulo.strip():
                st.warning("⚠️ El título es obligatorio.")
            else:
                datos = dict(
                    fecha_evento=fecha_evento, titulo=titulo, contenido=contenido,
                    tipo_evento=tipo_evento, impacto_override=impacto_override,
                    empresa=empresa, ticker=ticker, pais=pais, sector=sector,
                    activos_afectados=activos_afectados,
                    fuente_url=fuente_url, reaccion_pct=reaccion_pct,
                    reaccion_activo=reaccion_activo, reaccion_plazo=reaccion_plazo, notas=notas,
                )
                try:
                    _guardar_evento(supabase, datos, user_id, user_email)
                    _limpiar_cache_eventos()
                    st.success("✅ Evento publicado.")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error al guardar: {e}")


# ==============================================================
#  FEED (todos ven; admin puede editar reacción / reclasificar / borrar)
# ==============================================================

def _form_reaccion(supabase, row):
    eid = row["id"]
    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
    r1, r2, r3, r4 = st.columns([1, 1, 1, 1])
    with r1:
        pct = st.number_input("Reacción (%)", value=row.get("reaccion_pct"), format="%.2f", key=f"me_r_pct_{eid}")
    with r2:
        activo = st.text_input("Activo medido", value=row.get("reaccion_activo") or "", key=f"me_r_act_{eid}")
    with r3:
        plazos = ["", "Intradía", "1 día", "1 semana", "1 mes"]
        actual = row.get("reaccion_plazo") or ""
        idx = plazos.index(actual) if actual in plazos else 0
        plazo = st.selectbox("Plazo", plazos, index=idx, key=f"me_r_plazo_{eid}")
    with r4:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if st.button("💾 Guardar reacción", key=f"me_r_btn_{eid}"):
            try:
                _actualizar_reaccion(supabase, eid, pct, activo, plazo)
                _limpiar_cache_eventos()
                st.success("✅ Reacción actualizada.")
                st.rerun()
            except Exception as e:
                st.error(f"❌ {e}")


def _form_reclasificar(supabase, row):
    """Panel para que el admin, consultando el glosario, le asigne a
    mano el tipo de evento correcto a una noticia — típicamente una
    que llegó 'Sin clasificar' desde la ingesta automática, pero sirve
    para cualquier evento cargado en este módulo."""
    eid = row["id"]
    tipo_actual = row.get("tipo_evento") or TIPO_SIN_CLASIFICAR
    idx_actual = (TIPOS_EVENTO_ORDENADOS.index(tipo_actual)
                  if tipo_actual in TIPOS_EVENTO_ORDENADOS else 0)

    nuevo_tipo = st.selectbox(
        "🏷️ Tipo de evento (glosario)", TIPOS_EVENTO_ORDENADOS,
        index=idx_actual, key=f"me_rc_tipo_{eid}",
        help="Elegí el tipo que mejor describe esta noticia — grupo, factor e "
             "impacto típico se completan solos según el glosario.",
    )
    info_nuevo = TIPOS_EVENTO.get(nuevo_tipo, {})
    st.markdown(_badges_evento(info_nuevo), unsafe_allow_html=True)
    st.caption(f"**Factor:** {info_nuevo.get('factor','') or '—'}")
    st.caption(
        f"**Activos afectados (automático):** {', '.join(info_nuevo.get('activos', [])) or '—'}"
    )

    impactos = list(IMPACTO_META.keys())
    idx_impacto = impactos.index(row.get("impacto")) if row.get("impacto") in impactos else impactos.index(
        info_nuevo.get("impacto", "Depende del caso")
    )
    impacto_override = st.selectbox(
        "⚡ Impacto para este caso puntual", impactos, index=idx_impacto, key=f"me_rc_impacto_{eid}",
        help="Precargado según el tipo elegido; ajustalo si este caso concreto es distinto al típico.",
    )

    if st.button("💾 Guardar clasificación", key=f"me_rc_btn_{eid}", type="primary"):
        try:
            _reclasificar_evento(supabase, eid, nuevo_tipo, impacto_override)
            _limpiar_cache_eventos()
            st.success("✅ Reclasificado.")
            st.rerun()
        except Exception as e:
            st.error(f"❌ {e}")


def _tab_feed(supabase, es_admin):
    top1, top2, top3 = st.columns([2.4, 1, 1])
    with top1:
        st.caption("Feed de noticias y eventos de mercado")
    with top2:
        incluir_calendario = st.toggle(
            "📅 Incluir Calendario", value=True, key="me_feed_incluir_calendario",
            help="Suma automáticamente los eventos macro (IPC, tasas, PBI, PMI...) ya cargados "
                 "en el Calendario Económico — no hace falta volver a cargarlos acá.",
        )
    with top3:
        if st.button("↺ Actualizar", use_container_width=True, key="me_feed_refresh"):
            _limpiar_cache_eventos()
            st.rerun()

    filas = list(_obtener_eventos(supabase))
    filas_calendario = _obtener_eventos_calendario(supabase) if incluir_calendario else []
    if incluir_calendario:
        filas = filas + filas_calendario

    if not filas:
        st.info("Todavía no hay eventos cargados.")
        return

    df = pd.DataFrame(filas)

    # Nos aseguramos de que TODAS las columnas que se usan más abajo
    # existan siempre, sin importar si vienen de un evento manual, de
    # un evento del Calendario, o de una fila vieja con algún campo
    # sin cargar. Esto evita KeyError si en algún momento falta una
    # columna (por ejemplo "es_calendario", que no es una columna real
    # de la tabla — solo la agregan los eventos del Calendario).
    columnas_por_defecto = {
        "es_calendario": False, "id": None, "fecha_evento": "", "titulo": "",
        "contenido": "", "tipo_evento": "", "grupo": "", "factor": "",
        "impacto": "", "empresa": "", "ticker": "", "pais": "", "sector": "",
        "activos_afectados": "", "monto": None, "moneda_monto": "", "fuente_url": "",
        "reaccion_pct": None, "reaccion_activo": "", "reaccion_plazo": "", "notas": "",
    }
    for columna, valor_por_defecto in columnas_por_defecto.items():
        if columna not in df.columns:
            df[columna] = valor_por_defecto
        else:
            df[columna] = df[columna].where(df[columna].notna(), valor_por_defecto)
    df["es_calendario"] = df["es_calendario"].astype(bool)

    # Sin filtros por grupo/impacto/tipo de evento a propósito: las
    # noticias entran sin clasificar y esos campos no son fiables como
    # filtro hasta que alguien las reclasifique a mano. Solo queda
    # buscar por texto y filtrar por fecha.
    b1, b4 = st.columns([1.6, 1.4])
    with b1:
        f_texto = st.text_input("🔎 Buscar (empresa, ticker, país, título)", key="me_feed_busq")
    with b4:
        fechas_validas = pd.to_datetime(df["fecha_evento"], errors="coerce").dropna()
        if not fechas_validas.empty:
            fmin_disp, fmax_disp = fechas_validas.min().date(), fechas_validas.max().date()
        else:
            fmin_disp = fmax_disp = date.today()

        modo_fecha = st.radio(
            "Filtro de fecha", ["Un día", "Rango"], key="me_feed_fecha_modo",
            horizontal=True, label_visibility="collapsed",
        )
        if modo_fecha == "Un día":
            f_fecha_unica = st.date_input(
                "📅 Fecha", value=fmax_disp,
                min_value=fmin_disp, max_value=fmax_disp,
                key="me_feed_fecha_unica",
            )
            f_rango_fecha = None
        else:
            f_fecha_unica = None
            f_rango_fecha = st.date_input(
                "📅 Rango de fechas",
                value=(fmin_disp, fmax_disp),
                min_value=fmin_disp, max_value=fmax_disp,
                key="me_feed_fecha_rango",
            )

    df_f = df.copy()
    df_f["_fecha_dt"] = pd.to_datetime(df_f["fecha_evento"], errors="coerce")

    if modo_fecha == "Un día" and f_fecha_unica is not None:
        df_f = df_f[df_f["_fecha_dt"].dt.date == f_fecha_unica]
    elif modo_fecha == "Rango":
        # date_input devuelve una sola fecha mientras el usuario todavía
        # no eligió el segundo extremo del rango — contemplamos los dos casos.
        if isinstance(f_rango_fecha, (tuple, list)) and len(f_rango_fecha) == 2:
            f_desde, f_hasta = f_rango_fecha
            df_f = df_f[
                (df_f["_fecha_dt"].dt.date >= f_desde) & (df_f["_fecha_dt"].dt.date <= f_hasta)
            ]
        elif isinstance(f_rango_fecha, date):
            df_f = df_f[df_f["_fecha_dt"].dt.date == f_rango_fecha]

    df_f = df_f.drop(columns=["_fecha_dt"])

    if f_texto.strip():
        t = f_texto.strip().lower()
        mascara = (
            df_f["titulo"].fillna("").str.lower().str.contains(t, regex=False)
            | df_f["contenido"].fillna("").str.lower().str.contains(t, regex=False)
            | df_f["empresa"].fillna("").str.lower().str.contains(t, regex=False)
            | df_f["ticker"].fillna("").str.lower().str.contains(t, regex=False)
            | df_f["pais"].fillna("").str.lower().str.contains(t, regex=False)
        )
        df_f = df_f[mascara]

    st.caption(f"{len(df_f)} evento(s) mostrados de {len(df)} totales")
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    for _, row in df_f.iterrows():
        origen_calendario = bool(row.get("es_calendario"))
        sin_clasificar = (row.get("tipo_evento") == TIPO_SIN_CLASIFICAR)
        icono_origen = "📅 " if origen_calendario else ("🟡 " if sin_clasificar else "")
        titulo_exp = f"{icono_origen}{row.get('fecha_evento','')} · {row.get('titulo','')}"
        with st.expander(titulo_exp):
            try:
                if row.get("activos_afectados"):
                    st.markdown(f"**Activos afectados:** {row['activos_afectados']}")
                if row.get("monto"):
                    st.markdown(f"**Monto:** {row['monto']} {row.get('moneda_monto') or ''}")
                if row.get("contenido"):
                    st.markdown(row["contenido"])
                if row.get("fuente_url"):
                    st.markdown(f"[🔗 Fuente]({row['fuente_url']})")

                if row.get("reaccion_pct") is not None:
                    emoji_r = "🟢" if row["reaccion_pct"] > 0 else ("🔴" if row["reaccion_pct"] < 0 else "⚪")
                    st.markdown(
                        f"**Reacción observada:** {emoji_r} {row['reaccion_pct']:+.2f}% "
                        f"en {row.get('reaccion_activo') or row.get('ticker') or 'el activo principal'} "
                        f"({row.get('reaccion_plazo') or 'plazo no especificado'})"
                    )

                if origen_calendario:
                    st.caption(
                        "📅 Este evento viene del Calendario Económico — para editarlo, cargar la "
                        "reacción de mercado o borrarlo, hacelo desde esa sección (Historial)."
                    )
                else:
                    if es_admin:
                        st.markdown("<hr style='margin:8px 0;border-color:#21262d'>", unsafe_allow_html=True)
                        if st.button("🗑️ Eliminar evento", key=f"me_del_{row['id']}"):
                            try:
                                _borrar_evento(supabase, row["id"])
                                _limpiar_cache_eventos()
                                st.success("✅ Eliminado.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ {e}")
            except Exception as e:
                st.error(f"⚠️ No se pudo mostrar este evento completo ({e}).")


# ==============================================================
#  ENTRY POINT
# ==============================================================

def render_noticias_mercado(supabase, user_id, user_email):
    """Uso desde app.py:
        from modulo_noticias_mercado import render_noticias_mercado
        render_noticias_mercado(supabase, USER_ID, st.session_state['usuario'].email)

    Requiere la tabla mercado_eventos (ver mercado_eventos_schema.sql).

    Puente con el Calendario Económico: el feed lee también, de forma
    automática y de solo lectura, la tabla calendario_registro (la que ya
    llena modulo_calendario.py). Así los datos macro programados (IPC,
    tasas, PBI, PMI...) se cargan UNA sola vez desde el Calendario y
    aparecen acá solos, sin volver a tipearlos. El botón "📅 Incluir
    Calendario" del feed prende/apaga esa mezcla. Lo que sí se carga
    manualmente en este módulo es lo que el Calendario no cubre: eventos
    puntuales de empresas, gobiernos, geopolítica y commodities.

    Clasificación: la ingesta automática (ingest_noticias.py) trae TODAS
    las noticias que encuentra, sin intentar adivinar de qué se tratan —
    quedan cargadas como "Sin clasificar". El glosario (TIPOS_EVENTO) es
    la referencia para que el admin, cuando lea una noticia y quiera
    entender o etiquetar de qué tipo de evento se trata, la reclasifique
    a mano desde el feed (panel "🏷️ Reclasificar" dentro de cada evento).
    """
    es_admin = _es_admin(user_email)
    _limpieza_automatica(supabase)   # ← nuevo: borra noticias con +7 días

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #8957e5;
         border-radius:14px; padding:22px 28px; margin-bottom:20px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:4px">
        🧠 Noticias + Eventos de Mercado
      </div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.6">
        Trae todas las noticias de mercado disponibles. El glosario (Evento → Grupo →
        Factor → Activos afectados → Impacto) queda como referencia para interpretarlas:
        las que llegan automáticamente entran como "Sin clasificar" y podés reclasificarlas
        a mano cuando quieras, consultando ese glosario. Filtrá por Macro, Empresas,
        Gobiernos, Bancos Centrales, Geopolítica, Commodities o Mercados, y consultá la
        reacción histórica real de eventos similares (a medida que se va cargando).
      </div>
    </div>
    """, unsafe_allow_html=True)

    if es_admin:
        opciones = ["📰 Feed", "📝 Registrar Evento"]
        seccion = st.radio("Sección", opciones, horizontal=True,
                            label_visibility="collapsed", key="me_seccion_activa")
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        if seccion == opciones[1]:
            _tab_registrar(supabase, user_id, user_email)
        else:
            _tab_feed(supabase, es_admin)
    else:
        _tab_feed(supabase, es_admin)
