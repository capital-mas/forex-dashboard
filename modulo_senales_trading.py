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
#   - FIX IMPORTANTE: la evaluación automática de TP/SL contaba como
#     "tocado" cualquier movimiento de precio ocurrido en TODO el día
#     de publicación (porque usaba velas diarias, con el High/Low del
#     día completo) — incluyendo movimientos ANTERIORES al momento en
#     que se publicó la señal. Eso hacía que una señal se cerrara
#     "apenas publicada" si el precio ya había tocado el TP/SL esa
#     misma mañana, antes de cargarla. Ahora la evaluación arranca
#     estrictamente desde la fecha+hora de publicación: primero revisa
#     velas HORARIAS (últimas ~7 días, filtradas a partir de ese
#     momento exacto) y, para los días siguientes, sigue con velas
#     diarias como antes. Esto aplica tanto a señales publicadas como
#     posición ya abierta, como al momento en que se activa una orden
#     pendiente (ver el punto siguiente). NOTA: yfinance devuelve las
#     velas horarias en la zona horaria del mercado del ticker (ej.
#     hora de Nueva York para acciones de EE.UU.), mientras que la
#     fecha/hora que cargás al publicar es tu hora local — se comparan
#     sin ajustar zona horaria, así que puede haber un corrimiento de
#     algunas horas según el instrumento. Sigue siendo mucho más
#     preciso que antes (que ni siquiera miraba la hora).
#   - NUEVO: "🕓 Dejar como orden pendiente". Al publicar, ahora hay un
#     checkbox para cargar la señal como una ORDEN LÍMITE en vez de una
#     posición ya abierta: el/los precio(s) de "Entradas" se guardan
#     como precio objetivo, la señal queda en estado PENDIENTE y NO se
#     evalúa Take Profit / Stop Loss todavía. En segundo plano (cada
#     vez que se abre "Señales y Resultados" o se le da a "Actualizar y
#     evaluar") se revisa el precio de mercado desde la publicación en
#     adelante (con el mismo mecanismo horario+diario de arriba) y, en
#     cuanto el precio toca el precio de una entrada, esa entrada queda
#     "activada". Cuando TODAS las entradas de la orden se activaron,
#     la señal pasa sola a ABIERTA — y ahí arranca recién la evaluación
#     de TP/SL, contada desde el momento de esa activación (no desde la
#     publicación). Mientras una orden está PENDIENTE no cuenta para el
#     Win Rate ni se incluye en el Simulador de Capital, y no muestra
#     P&L en vivo ni la sección de "Replicar la posición" (no hay
#     margen puesto todavía) — sí muestra una vista previa de cómo
#     quedaría la posición (precio de liquidación estimado) una vez que
#     se llene, con el margen/apalancamiento que cargaste.
#     REQUIERE migrar la tabla en Supabase:
#       ALTER TABLE senales_trading
#       ADD COLUMN IF NOT EXISTS fecha_activacion date,
#       ADD COLUMN IF NOT EXISTS hora_activacion text;
#     (Los campos "activada"/"fecha_activacion"/"hora_activacion" de
#     CADA entrada viven dentro del jsonb "entradas": no hace falta
#     migrar nada más para eso.) Si tu columna "estado" tiene un CHECK
#     constraint con los valores permitidos, agregale "PENDIENTE" a la
#     lista. Las señales viejas (sin este campo) se siguen leyendo
#     igual que siempre: se tratan como ya abiertas/activadas.
#   - NUEVO: se eliminó, en "Señales y Resultados", el selector
#     "Elegí con qué perfil querés tomar esta señal" (el que sugería
#     un tamaño de posición a partir de un % de riesgo sobre el
#     Stop Loss). Ese cálculo ignoraba el precio de liquidación y
#     podía sugerir una posición que te liquidaba ANTES de que el SL
#     llegara a ejecutarse — quedaba un cartel de advertencia sin
#     forma de corregirlo desde ahí. Se reemplaza por lo de abajo.
#   - NUEVO: en "🔁 Replicá la posición", ahora se puede elegir CON
#     QUÉ APALANCAMIENTO replicarla: el de apertura original (default,
#     mismo comportamiento de siempre: escala TODAS las entradas tal
#     cual) o uno de los 3 apalancamientos sugeridos que el admin
#     carga por señal (🟢 Conservador / 🟡 Moderado / 🔴 Agresivo).
#     Si elegís un perfil, se arma una posición nueva (una sola
#     entrada) al precio promedio de la señal, con TU margen y el
#     apalancamiento de ese perfil — mostrando su propio precio de
#     liquidación — en vez de escalar las entradas originales.
#     REQUIERE migrar la tabla en Supabase:
#       ALTER TABLE senales_trading
#       ADD COLUMN IF NOT EXISTS apal_conservador float,
#       ADD COLUMN IF NOT EXISTS apal_moderado    float,
#       ADD COLUMN IF NOT EXISTS apal_agresivo    float;
#     Las señales viejas, sin estos campos, simplemente no ofrecen
#     esos 3 perfiles como opción de apalancamiento en la réplica
#     (solo queda disponible "Apertura").
#   - CAMBIO: en "Señales y Resultados" y en "Publicar Señal", el
#     cartel de posición ahora separa claramente el "Margen de
#     apertura" del "Margen extra" agregado para alejar la
#     liquidación (antes se mostraban sumados en un único "Margen
#     total"). Y el "Apalancamiento" que se muestra en TODOS lados
#     es el que usaste para ABRIR la posición: ya no baja solo
#     porque agregaste margen extra (antes mostraba el apalancamiento
#     "efectivo", diluido por ese extra). Este apalancamiento "de
#     apertura" se recalcula siempre desde las entradas guardadas, así
#     que también corrige — sin migrar nada — el cálculo que usan el
#     Simulador de Capital, el selector "Elegí con qué perfil" y el
#     P&L en vivo (antes todos leían el apalancamiento diluido que
#     había quedado guardado en la señal). El apalancamiento efectivo
#     (con el extra incluido) se sigue mostrando aparte, junto al
#     margen total, solo quando cargaste margen extra.
#   - FIX: el texto de "Si el precio llega al Take Profit, ganarías…"
#     al elegir un perfil de riesgo se veía roto (palabras pegadas
#     sin espacios). Era un bug de Streamlit: cuando un mismo texto
#     tiene más de un signo "$", lo interpreta como una fórmula LaTeX
#     en vez de texto. Se corrigió escapando los "$" en ese texto y en
#     los demás avisos que mezclaban varios montos en dólares (el
#     aviso de Stop Loss más allá de la liquidación y el detalle de
#     entradas múltiples).
#   - FIX: en el Simulador de Capital, la tarjeta "📉 Peor operación"
#     se pintaba de rojo (y sin el signo "+") aunque esa operación
#     hubiera sido ganadora — pasaba siempre que TODAS las operaciones
#     simuladas ganaban plata, porque igual hay que elegir una como
#     "la peor" del conjunto. Ahora el color y el signo de "Mejor" y
#     "Peor" dependen del resultado real de cada una (verde/"+" si
#     ganó, rojo/sin signo si perdió), así nunca se ve una ganancia
#     pintada como pérdida.
#   - NUEVO: "Mejor operación", "Peor operación" y la tabla del
#     Simulador ahora muestran también la fecha (y hora, cuando se
#     conoce) en que se cerró la señal. Para un cierre automático
#     (TP/SL detectado por el sistema) la hora es aproximada: es el
#     momento en que la app detectó el cierre, no el instante exacto
#     de mercado (el historial usado para evaluar TP/SL es diario, no
#     intradía). REQUIERE migrar la tabla en Supabase:
#       ALTER TABLE senales_trading
#       ADD COLUMN IF NOT EXISTS hora_cierre text;
#   - NUEVO: "Margen extra agregado" por entrada. Antes, cualquier
#     margen cargado en una entrada se multiplicaba por el
#     apalancamiento y agrandaba el tamaño (nominal) de la posición.
#     Eso está bien para el margen CON EL QUE ABRÍS, pero no sirve
#     para representar el caso real de "agregar margen a una posición
#     YA ABIERTA" (un top-up para alejar la liquidación), que no debe
#     sumar tamaño ni unidades. Ahora cada entrada separa:
#       · Margen apertura (USD): define el tamaño → nominal = margen
#         apertura × apalancamiento. Igual que antes.
#       · Margen extra (USD): NO suma nominal ni unidades. Solo se
#         suma al margen total de la posición, así que agranda el
#         colchón contra la liquidación (y por lo tanto baja el
#         apalancamiento EFECTIVO de la posición, porque el mismo
#         tamaño ahora está respaldado por más capital).
#     El precio de liquidación usa el margen total (apertura + extra)
#     igual que antes; lo único que cambió es que el extra ya no
#     infla el tamaño de la posición. Las señales viejas, guardadas
#     sin "margen_extra", se siguen leyendo con ese campo en 0.
#   - NUEVO: P&L en vivo para señales ABIERTAS en "Señales y Resultados".
#     Cada señal abierta muestra un cartel con 🟢 GANANDO / 🔴 PERDIENDO
#     y el % apalancado actual, calculado contra el precio más reciente
#     disponible (caché propia de 5 minutos, separada de la caché de
#     15 minutos que usa la evaluación automática de TP/SL). La pestaña
#     se autorefresca cada 5 minutos para que el cartel se actualice
#     solo. Arriba de la lista se agregó un resumen con cuántas
#     posiciones abiertas están ganando y perdiendo ahora mismo.
#   - NUEVO en el Simulador de Capital: "🔁 Replicar la posición
#     del publicador". La persona pone UN solo número (su margen) y la
#     app copia la posición del admin tal cual: mismas entradas, mismos
#     precios, mismo apalancamiento en cada una, y el margen y el costo
#     de apertura de cada entrada se escalan en la misma proporción.
#     Ej: si el admin puso 100 de margen en cada una de sus 2 entradas y
#     el usuario pone 10 (referido a la 1ª entrada), su margen queda en
#     10 en cada entrada. El precio de liquidación resulta el mismo que
#     el del admin (la escala no lo cambia) y la simulación verifica
#     contra el historial si el precio llegó a tocarlo.
#   - CAMBIO: las entradas ya NO tienen "peso relativo". Ahora cada
#     entrada se carga con datos reales de la operación:
#       · Precio de la entrada
#       · Costo de apertura (USD: comisión/spread que pagaste)
#       · Apalancamiento que usaste en esa entrada
#       · Margen (USD) que agregaste a la posición con esa entrada
#     A partir de eso la app calcula sola, para toda la posición:
#       · Tamaño nominal = margen × apalancamiento (por entrada)
#       · Unidades = nominal / precio (por entrada)
#       · Precio promedio REAL = nominal total / unidades totales
#         (ponderado por el tamaño de cada entrada)
#       · Apalancamiento efectivo = nominal total / margen total
#       · PRECIO DE LIQUIDACIÓN con ese margen (ver _resumen_posicion
#         para la fórmula y los supuestos)
#     Además avisa si el Stop Loss queda más allá del precio de
#     liquidación (te liquidarían antes de que salte el SL).
#     NO requiere migrar Supabase: sigue usando la columna jsonb
#     "entradas" (ya creada). Las señales viejas (con "peso" o sin
#     entradas) siguen funcionando: usan su promedio de siempre y no
#     muestran precio de liquidación porque no tienen margen cargado.
#     El campo "precio_entrada" ahora se guarda como el precio
#     promedio real de la posición, y "apalancamiento" como el
#     apalancamiento de apertura — así el resto del código (SL/TP,
#     Señales y Resultados, evaluación automática, Simulador) sigue
#     funcionando sin tocar nada más.
#   - Múltiples entradas por señal (para promediar precio, ej.
#     compraste en 2 o 3 tandas a distinto precio), sin límite fijo.
#     Si todavía no la tenés, la columna se crea con:
#       ALTER TABLE senales_trading
#       ADD COLUMN IF NOT EXISTS entradas jsonb DEFAULT '[]'::jsonb;
#   - Se eliminó la pestaña independiente "Gestor de Riesgo". Su
#     cálculo (tamaño de posición a partir de un % de capital en
#     riesgo y la distancia al Stop Loss) ahora vive DENTRO del
#     Simulador de Capital, como el modo "🎯 % de riesgo por
#     operación (según Stop Loss)".
#   - Perfiles de riesgo (🟢 Conservador / 🟡 Moderado / 🔴 Agresivo).
#     El admin define, al publicar cada señal, qué % de capital
#     arriesgaría cada perfil si el precio llega al Stop Loss.
#     REQUIERE migrar la tabla en Supabase:
#       ALTER TABLE senales_trading
#       ADD COLUMN IF NOT EXISTS riesgo_conservador float DEFAULT 1.0,
#       ADD COLUMN IF NOT EXISTS riesgo_moderado    float DEFAULT 2.0,
#       ADD COLUMN IF NOT EXISTS riesgo_agresivo    float DEFAULT 3.0;
#     (además de la columna "categoria" agregada en versiones previas)
#   - En el Simulador de Capital se agregó el modo "🎭 Comparar los
#     3 perfiles de riesgo": corre la simulación completa una vez
#     por perfil (usando el % que definió el admin en cada señal) y
#     muestra los resultados uno al lado del otro.
# ==============================================================

import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, datetime, time as dt_time, timedelta
from streamlit_autorefresh import st_autorefresh

ADMIN_EMAIL = "brainferreyra@gmail.com"
TABLA_SENALES = "senales_trading"

# Margen de mantenimiento que exige el bróker, como % del tamaño
# nominal de la posición. Se usa SOLO para calcular el precio de
# liquidación. Con 0.0 se asume que te liquidan cuando el margen
# (menos los costos de apertura) se consume por completo. Cada bróker
# lo define distinto: si querés máxima exactitud, poné acá el valor
# que te indica tu bróker para el instrumento (ej. 0.5 = 0,5%).
MARGEN_MANTENIMIENTO_PCT = 0.0

ESTADO_COLOR = {
    "PENDIENTE":            ("#a371f7", "rgba(163,113,247,0.12)", "🕓"),
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

# Perfiles de riesgo: el % de cada perfil se define POR SEÑAL, al
# publicarla (así el admin puede ser más o menos permisivo según el
# instrumento o la convicción de la señal). Estos valores son solo
# los defaults que se muestran al cargar el formulario. Se siguen
# usando para el Simulador de Capital (pestaña "Comparar los 3
# perfiles"). Para la réplica de una posición puntual en "Señales y
# Resultados", ver los campos apal_conservador/moderado/agresivo.
PERFILES_RIESGO = {
    "conservador": {
        "label": "🟢 Conservador",
        "default_pct": 1.0,
        "desc": ("Prioriza cuidar el capital por sobre todo. Arriesga poco en cada "
                 "operación para amortiguar rachas de pérdidas — a cambio, las "
                 "ganancias en dólares también son más chicas. Pensado para quien "
                 "recién empieza o no quiere sobresaltos grandes en su capital."),
    },
    "moderado": {
        "label": "🟡 Moderado",
        "default_pct": 2.0,
        "desc": ("Un punto medio entre cuidar el capital y buscar rendimiento. "
                 "Asume más volatilidad que el conservador a cambio de un "
                 "potencial de ganancia mayor. Es el perfil habitual para quien "
                 "ya tiene algo de experiencia gestionando riesgo."),
    },
    "agresivo": {
        "label": "🔴 Agresivo",
        "default_pct": 3.0,
        "desc": ("Busca maximizar el retorno asumiendo el mayor riesgo por "
                 "operación. Tanto las pérdidas como las ganancias en dólares son "
                 "más grandes. Conviene solo si tenés capital suficiente y buena "
                 "tolerancia psicológica a ver el capital moverse fuerte."),
    },
}
PERFILES_LABEL_A_KEY = {v["label"]: k for k, v in PERFILES_RIESGO.items()}


def _es_admin(user_email):
    return bool(user_email) and user_email.strip().lower() == ADMIN_EMAIL.strip().lower()


# ==============================================================
#  FORMATO
# ==============================================================

def fmt_precio_local(p):
    if p is None:
        return "S/D"
    p = float(p)
    if p >= 1000: return f"${p:,.0f}"
    if p >= 10:   return f"${p:.2f}"
    return f"${p:.5f}"


def fmt_precio_exacto(p):
    """Como fmt_precio_local pero sin redondear a entero los precios
    grandes. Se usa para promedio y precio de liquidación, donde los
    decimales importan."""
    if p is None:
        return "S/D"
    p = float(p)
    if p >= 10:
        return f"${p:,.2f}"
    return f"${p:.5f}"


def fmt_apal(x):
    """8.0 -> '8x', 7.5 -> '7.5x', 7.4286 -> '7.43x'."""
    try:
        return f"{round(float(x), 2):g}x"
    except (TypeError, ValueError):
        return "S/D"


def fmt_unidades(u):
    s = f"{float(u):,.6f}".rstrip("0").rstrip(".")
    return s or "0"


def _md_dolar(texto):
    """Escapa los signos '$' antes de pasar un texto a st.caption /
    st.warning / st.error / st.markdown. Streamlit interpreta lo que
    queda ENTRE dos signos "$" como una fórmula LaTeX; si un mismo
    texto tiene más de un monto en dólares (ej. "ganarías $X... y
    perderías $Y..."), todo lo que hay en el medio se renderiza mal
    (aparece pegado, sin espacios). Escapando el "$" como "\\$" se
    evita ese problema y el signo se sigue viendo normal."""
    return texto.replace("$", r"\$")


# ==============================================================
#  ENTRADAS MÚLTIPLES — helpers de posición
#  Cada señal puede tener 1 o más "entradas". Cada entrada guarda:
#     precio, costo_apertura (USD), apalancamiento, margen (USD),
#     margen_extra (USD), activada (bool), fecha_activacion,
#     hora_activacion
#  en la columna jsonb "entradas". Los campos "precio_entrada" y
#  "apalancamiento" de la señal se guardan también, como el precio
#  promedio real y el apalancamiento de apertura de la posición, para
#  que todo el resto del código siga funcionando igual.
#  "activada"/"fecha_activacion"/"hora_activacion" solo importan para
#  señales publicadas como orden PENDIENTE (ver más abajo): indican si
#  el precio ya tocó esa entrada y cuándo. Para una señal publicada
#  como posición YA ABIERTA (el caso de siempre), todas las entradas se
#  consideran activadas desde la publicación — por eso, si el campo no
#  está guardado (señales viejas), se asume activada=True salvo que la
#  señal esté en estado PENDIENTE.
#  Compatibilidad: las señales viejas pueden tener entradas con
#  "peso" (versión anterior), sin "margen_extra", o ninguna entrada;
#  se siguen leyendo (margen_extra cae a 0 si no está).
# ==============================================================

def _entradas_de_senal(senal):
    """Devuelve la lista de entradas normalizada:
    [{'precio','costo_apertura','apalancamiento','margen','margen_extra',
      'peso','activada','fecha_activacion','hora_activacion'}, ...].
    'margen' = 0 significa que la señal es vieja y no tiene margen
    cargado. 'peso' es solo de señales viejas."""
    apal_senal = float(senal.get("apalancamiento") or 1.0) or 1.0
    default_activada = senal.get("estado") != "PENDIENTE"
    entradas = senal.get("entradas")
    if entradas and isinstance(entradas, list):
        limpio = []
        for e in entradas:
            try:
                p = float(e.get("precio"))
                if p <= 0:
                    continue
                limpio.append({
                    "precio": p,
                    "costo_apertura": float(e.get("costo_apertura") or 0.0),
                    "apalancamiento": float(e.get("apalancamiento") or apal_senal) or 1.0,
                    "margen": float(e.get("margen") or 0.0),
                    "margen_extra": float(e.get("margen_extra") or 0.0),
                    "peso": float(e.get("peso") or 1.0),
                    "activada": bool(e.get("activada", default_activada)),
                    "fecha_activacion": e.get("fecha_activacion"),
                    "hora_activacion": e.get("hora_activacion"),
                })
            except (TypeError, ValueError, AttributeError):
                continue
        if limpio:
            return limpio
    precio_unico = float(senal.get("precio_entrada") or 0)
    if precio_unico > 0:
        return [{"precio": precio_unico, "costo_apertura": 0.0,
                 "apalancamiento": apal_senal, "margen": 0.0,
                 "margen_extra": 0.0, "peso": 1.0,
                 "activada": default_activada, "fecha_activacion": None,
                 "hora_activacion": None}]
    return []


def _resumen_posicion(entradas, es_largo, mantenimiento_pct=MARGEN_MANTENIMIENTO_PCT):
    """Calcula la posición total a partir de las entradas.

    Para cada entrada:
        nominal_i  = margen_i × apalancamiento_i   (SOLO el margen de
                     apertura define tamaño; el margen extra NO)
        unidades_i = nominal_i / precio_i
    Para la posición:
        precio promedio = Σ nominal / Σ unidades   (ponderado por tamaño)
        margen total = Σ margen de apertura + Σ margen extra
        apalancamiento de apertura = Σ nominal / Σ margen de apertura
            (el que realmente usaste para abrir la posición)
        apalancamiento efectivo = Σ nominal / margen total
            (el que queda una vez que sumás el margen extra — más bajo,
            porque el mismo tamaño queda respaldado por más capital)

    El "margen extra" es capital que agregaste DESPUÉS de abrir una
    entrada, para alejar la liquidación sin comprar más unidades —
    igual que hacer un top-up de margen a una posición ya abierta en
    un exchange real. No suma nominal ni unidades, pero sí suma al
    margen total: por eso agranda el colchón de liquidación y baja el
    apalancamiento efectivo (el mismo tamaño queda respaldado por más
    capital). El apalancamiento DE APERTURA no se toca por el extra:
    sigue siendo el que elegiste al abrir cada entrada.

    PRECIO DE LIQUIDACIÓN (margen aislado):
        colchón = margen total − costos de apertura − mantenimiento
        LARGO : liquidación = precio promedio − colchón / unidades
        CORTO : liquidación = precio promedio + colchón / unidades
    donde mantenimiento = MARGEN_MANTENIMIENTO_PCT % × nominal.

    Supuestos (el bróker real puede variar):
      · El costo de apertura sale del margen (reduce el colchón).
      · No incluye funding/swap acumulado ni comisión de cierre.
      · Todas las entradas se tratan como UNA posición con margen
        aislado, como hace un exchange cuando promediás.
    Devuelve None si no hay entradas válidas (precio > 0 y margen > 0)."""
    validas = [e for e in entradas
               if float(e.get("precio") or 0) > 0
               and float(e.get("margen") or 0) > 0
               and float(e.get("apalancamiento") or 0) > 0]
    if not validas:
        return None

    nominal = sum(e["margen"] * e["apalancamiento"] for e in validas)
    unidades = sum(e["margen"] * e["apalancamiento"] / e["precio"] for e in validas)
    margen_apertura_total = sum(e["margen"] for e in validas)
    margen_extra_total = sum(float(e.get("margen_extra") or 0.0) for e in validas)
    margen_total = margen_apertura_total + margen_extra_total
    costos_total = sum(float(e.get("costo_apertura") or 0.0) for e in validas)
    precio_prom = nominal / unidades
    apal_ef = nominal / margen_total
    apal_apertura = (nominal / margen_apertura_total) if margen_apertura_total else apal_ef

    mantenimiento_usd = nominal * mantenimiento_pct / 100.0
    colchon = margen_total - costos_total - mantenimiento_usd
    liquidada_al_abrir = colchon <= 0
    distancia = max(colchon, 0.0) / unidades

    if es_largo:
        liq_raw = precio_prom - distancia
        sin_liquidacion = liq_raw <= 0     # el activo tendría que llegar a $0
        precio_liq = max(liq_raw, 0.0)
    else:
        precio_liq = precio_prom + distancia
        sin_liquidacion = False

    dist_pct = (precio_liq - precio_prom) / precio_prom * 100.0

    return dict(
        precio_promedio=precio_prom, unidades=unidades, nominal=nominal,
        margen_total=margen_total, margen_apertura=margen_apertura_total,
        margen_extra=margen_extra_total, costos_total=costos_total,
        apalancamiento_apertura=apal_apertura, apalancamiento_efectivo=apal_ef,
        colchon=colchon,
        precio_liquidacion=precio_liq, dist_liq_pct=dist_pct,
        sin_liquidacion=sin_liquidacion, liquidada_al_abrir=liquidada_al_abrir,
        n_entradas=len(validas),
    )


def _resumen_de_senal(senal):
    """Resumen de posición de una señal guardada, o None si es una
    señal vieja sin margen cargado en todas sus entradas."""
    entradas = _entradas_de_senal(senal)
    if not entradas or not all(e["margen"] > 0 for e in entradas):
        return None
    es_largo = "LARGO" in str(senal.get("tipo", "")).upper()
    return _resumen_posicion(entradas, es_largo)


def _apalancamiento_apertura_de_senal(senal):
    """Apalancamiento realmente usado para ABRIR la posición de una
    señal: ignora la dilución que genera el margen extra agregado
    después (que solo existe para alejar la liquidación, no cambia
    cuánto se movió tu resultado por cada punto de precio). Se
    recalcula siempre desde las entradas cuando hay margen cargado —
    así corrige también señales viejas que se hubieran guardado con
    el apalancamiento efectivo (diluido). Si no hay margen cargado en
    las entradas (señal vieja de precio único), cae al apalancamiento
    guardado en la señal."""
    res = _resumen_de_senal(senal)
    if res:
        return res["apalancamiento_apertura"]
    return float(senal.get("apalancamiento") or 1.0) or 1.0


def _sl_mas_alla_de_liquidacion(res, es_largo, stop_loss):
    """True si el Stop Loss queda más allá del precio de liquidación
    (te liquidarían antes de que el SL llegue a ejecutarse)."""
    if not res or not stop_loss or stop_loss <= 0 or res["sin_liquidacion"]:
        return False
    liq = res["precio_liquidacion"]
    return (stop_loss <= liq) if es_largo else (stop_loss >= liq)


def _precio_promedio_simple(senal):
    entradas = _entradas_de_senal(senal)
    if not entradas:
        return float(senal.get("precio_entrada") or 0)
    precios = [e["precio"] for e in entradas]
    return sum(precios) / len(precios)


def _precio_promedio_ponderado(senal):
    """Precio promedio real de la posición (ponderado por tamaño). Si la
    señal es vieja y no tiene margen, cae al promedio por 'peso' de la
    versión anterior (o al precio único)."""
    entradas = _entradas_de_senal(senal)
    if not entradas:
        return float(senal.get("precio_entrada") or 0)
    if all(e["margen"] > 0 for e in entradas):
        res = _resumen_posicion(entradas, True)
        if res:
            return res["precio_promedio"]
    suma_peso = sum(e["peso"] for e in entradas)
    if suma_peso <= 0:
        return _precio_promedio_simple(senal)
    return sum(e["precio"] * e["peso"] for e in entradas) / suma_peso


def _senal_con_precio_entrada(senal, precio_entrada):
    """Copia la señal pisando precio_entrada por el valor dado — para
    reusar _calcular_retorno / _calcular_pnl_lotes /
    _tamano_posicion_por_riesgo con el promedio que corresponda."""
    s2 = dict(senal)
    s2["precio_entrada"] = precio_entrada
    return s2


def _texto_entradas(entradas):
    partes = []
    for i, e in enumerate(entradas):
        t = f"Entrada {i + 1}: {fmt_precio_exacto(e['precio'])}"
        if e["margen"] > 0:
            t += f" · margen ${e['margen']:,.2f} · {fmt_apal(e['apalancamiento'])}"
            if e.get("margen_extra", 0) > 0:
                t += f" · +${e['margen_extra']:,.2f} extra"
            if e["costo_apertura"] > 0:
                t += f" · costo ${e['costo_apertura']:,.2f}"
        elif abs(e["peso"] - 1.0) > 1e-9:
            t += f" (peso {e['peso']:.2f})"
        partes.append(t)
    return " | ".join(partes)


def _texto_cierre(estado, fecha_cierre, hora_cierre):
    """Texto legible de cuándo se cerró una señal, para la tabla y las
    tarjetas de mejor/peor operación del simulador. Si sigue abierta,
    lo dice explícitamente. La hora solo aparece si se guardó (señales
    cerradas antes de esta versión no la tienen)."""
    if estado == "ABIERTA":
        return "Sigue abierta"
    if not fecha_cierre:
        return "—"
    if hora_cierre:
        return f"{fecha_cierre} {hora_cierre}"
    return str(fecha_cierre)


def _render_resumen_posicion(res, es_largo, stop_loss=None):
    """Muestra la posición total y el precio de liquidación. El margen
    de apertura y el apalancamiento de apertura van primero (son los
    que reflejan cómo abriste la operación); el margen extra y el
    apalancamiento efectivo (diluido por ese extra) se muestran aparte,
    solo cuando corresponde, para no mezclarlos con lo anterior."""
    st.markdown("##### 🧮 Posición total y precio de liquidación")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Precio promedio", fmt_precio_exacto(res["precio_promedio"]))
    m2.metric("Margen de apertura", f"${res['margen_apertura']:,.2f}")
    m3.metric("Tamaño (nominal)", f"${res['nominal']:,.2f}")
    m4.metric("Apalancamiento usado", fmt_apal(res["apalancamiento_apertura"]))

    if res.get("margen_extra", 0) > 0:
        e1, e2, e3 = st.columns(3)
        e1.metric("Margen extra agregado", f"${res['margen_extra']:,.2f}")
        e2.metric("Margen total (apertura + extra)", f"${res['margen_total']:,.2f}")
        e3.metric("Apalanc. efectivo (con extra)", fmt_apal(res["apalancamiento_efectivo"]))
        st.caption(
            "El margen extra no suma tamaño a la posición (el nominal y las unidades se "
            "calculan solo con el margen de apertura): solo agranda el colchón contra la "
            "liquidación. Por eso el apalancamiento EFECTIVO de la posición queda más bajo que "
            "el apalancamiento que usaste al abrirla — no porque hayas cambiado de "
            "apalancamiento, sino porque el mismo tamaño ahora está respaldado por más capital."
        )

    n1, n2, n3, n4 = st.columns(4)
    n1.metric("Unidades", fmt_unidades(res["unidades"]))
    n2.metric("Costos de apertura", f"${res['costos_total']:,.2f}")
    if res["liquidada_al_abrir"]:
        n3.metric("💀 Precio de liquidación", fmt_precio_exacto(res["precio_promedio"]))
        n4.metric("Distancia a liquidación", "0.00%")
    elif res["sin_liquidacion"]:
        n3.metric("💀 Precio de liquidación", "Sin liquidación")
        n4.metric("Distancia a liquidación", "—")
    else:
        n3.metric("💀 Precio de liquidación", fmt_precio_exacto(res["precio_liquidacion"]))
        n4.metric("Distancia a liquidación", f"{res['dist_liq_pct']:+.2f}%")

    if res["liquidada_al_abrir"]:
        st.error("🚨 Los costos de apertura (más el margen de mantenimiento) igualan o superan el "
                 "margen total: la posición nacería liquidada.")
    elif res["sin_liquidacion"]:
        st.caption("Con este margen y apalancamiento el activo tendría que llegar a $0 para "
                   "liquidarte (efectivamente, no hay liquidación en un largo).")

    if _sl_mas_alla_de_liquidacion(res, es_largo, stop_loss):
        st.warning(_md_dolar(
            f"⚠️ El Stop Loss ({fmt_precio_exacto(stop_loss)}) queda más allá del precio de "
            f"liquidación ({fmt_precio_exacto(res['precio_liquidacion'])}): te liquidarían antes "
            "de que el SL se ejecute."))

    st.caption(
        "Fórmula: liquidación = precio promedio "
        f"{'−' if es_largo else '+'} (margen total [apertura + extra] − costos de apertura − "
        f"mantenimiento {MARGEN_MANTENIMIENTO_PCT:g}%) / unidades. Es una estimación con margen "
        "aislado; no incluye funding/swap ni comisión de cierre. Cada bróker define su margen de "
        "mantenimiento (ajustá MARGEN_MANTENIMIENTO_PCT al de tu bróker para máxima exactitud)."
    )


# ----------------------------------------------------------------
#  Formulario dinámico de entradas (usado solo al publicar)
# ----------------------------------------------------------------

def _entrada_vacia(_id, apal=1.0):
    return {"id": _id, "precio": 0.0, "costo": 0.0, "apal": float(apal),
            "margen": 0.0, "margen_extra": 0.0}


def _limpiar_keys_entrada(ent):
    for pref in ("precio", "costo", "apal", "margen", "margen_extra"):
        st.session_state.pop(f"sen_entrada_{pref}_{ent['id']}", None)


def _init_entradas_state():
    if "sen_entradas" not in st.session_state:
        st.session_state["sen_entradas"] = [_entrada_vacia(0)]
        st.session_state["sen_entrada_next_id"] = 1


def _reset_entradas_state():
    for e in st.session_state.get("sen_entradas", []):
        _limpiar_keys_entrada(e)
    st.session_state["sen_entradas"] = [_entrada_vacia(0)]
    st.session_state["sen_entrada_next_id"] = 1


def _entradas_para_guardar(entradas_form, es_pendiente=False):
    """Solo las entradas completas (precio > 0 y margen > 0), en el
    formato que se guarda en la columna jsonb 'entradas'. Si
    es_pendiente=True, se guardan como no activadas todavía (orden
    límite esperando que el precio las toque); si no, se guardan como
    ya activadas (posición ya abierta, comportamiento de siempre)."""
    return [
        {"precio": float(e["precio"]),
         "costo_apertura": float(e["costo"]),
         "apalancamiento": float(e["apal"]),
         "margen": float(e["margen"]),
         "margen_extra": float(e.get("margen_extra") or 0.0),
         "activada": not es_pendiente,
         "fecha_activacion": None,
         "hora_activacion": None}
        for e in entradas_form if e["precio"] > 0 and e["margen"] > 0
    ]


def _render_entradas_form(es_largo, es_pendiente=False):
    """Renderiza el formulario dinámico de entradas (1 o más, sin
    límite) y devuelve la lista de entradas cargadas en session_state."""
    _init_entradas_state()
    entradas = st.session_state["sen_entradas"]

    st.markdown("#### 🎯💰 Entradas")
    if es_pendiente:
        st.caption(
            "Como marcaste **orden pendiente**, el precio que cargues acá es el precio "
            "OBJETIVO (de entrada límite): la posición todavía no está abierta. Cargá igual el "
            "costo de apertura, apalancamiento y margen que pensás usar CUANDO se active, para "
            "que la app te muestre una vista previa del precio de liquidación que tendría."
        )
    else:
        st.caption(
            "Cargá una entrada por cada compra/venta si vas a promediar precio (ej: entraste en 2 "
            "o 3 tandas). Para cada una indicá el **precio**, el **costo de apertura** en USD "
            "(comisión/spread), el **apalancamiento** que usaste y el **margen de apertura** en USD "
            "con el que abriste esa entrada (define el tamaño de la posición). Si más adelante le "
            "agregaste capital a esa misma entrada YA ABIERTA (sin comprar más unidades, solo para "
            "alejar la liquidación), cargalo aparte en **margen extra**: no cambia el tamaño de la "
            "posición ni el apalancamiento con el que operás, pero sí el precio de liquidación. Con "
            "eso la app calcula el precio promedio real, el apalancamiento usado y el **precio de "
            "liquidación**."
        )

    a_borrar = None
    for i, ent in enumerate(entradas):
        ce1, ce2, ce3, ce4, ce5, ce6 = st.columns([1.3, 1.0, 0.9, 1.1, 1.1, 0.4])
        with ce1:
            ent["precio"] = st.number_input(
                f"Precio — Entrada {i + 1}", min_value=0.0, format="%.5f",
                value=float(ent.get("precio", 0.0)), key=f"sen_entrada_precio_{ent['id']}")
        with ce2:
            ent["costo"] = st.number_input(
                f"Costo apertura (USD) {i + 1}", min_value=0.0, step=0.01, format="%.4f",
                value=float(ent.get("costo", 0.0)), key=f"sen_entrada_costo_{ent['id']}",
                help="Comisión/spread que pagaste al abrir esta entrada, en dólares.")
        with ce3:
            ent["apal"] = st.number_input(
                f"Apalanc. {i + 1} (x)", min_value=1.0, max_value=125.0, step=1.0, format="%.1f",
                value=float(ent.get("apal", 1.0)), key=f"sen_entrada_apal_{ent['id']}",
                help="Apalancamiento que usaste en esta entrada.")
        with ce4:
            ent["margen"] = st.number_input(
                f"Margen apertura (USD) {i + 1}", min_value=0.0, step=10.0, format="%.2f",
                value=float(ent.get("margen", 0.0)), key=f"sen_entrada_margen_{ent['id']}",
                help="Margen en dólares con el que ABRISTE esta entrada. Define el tamaño de la "
                     "posición: nominal = margen apertura × apalancamiento.")
        with ce5:
            ent["margen_extra"] = st.number_input(
                f"Margen extra (USD) {i + 1}", min_value=0.0, step=10.0, format="%.2f",
                value=float(ent.get("margen_extra", 0.0)), key=f"sen_entrada_margen_extra_{ent['id']}",
                help="Margen que agregaste DESPUÉS de abrir esta entrada, sin comprar más "
                     "unidades (top-up). No suma tamaño a la posición ni cambia el apalancamiento "
                     "con el que operás: solo agranda el colchón y aleja el precio de liquidación.")
        with ce6:
            st.write("")
            st.write("")
            if len(entradas) > 1 and st.button("🗑️", key=f"sen_entrada_del_{ent['id']}",
                                                help="Quitar esta entrada"):
                a_borrar = i

    if a_borrar is not None:
        eliminado = entradas.pop(a_borrar)
        _limpiar_keys_entrada(eliminado)
        st.rerun()

    if st.button("➕ Agregar otra entrada", key="sen_entrada_add"):
        nuevo_id = st.session_state["sen_entrada_next_id"]
        apal_prev = entradas[-1].get("apal", 1.0) if entradas else 1.0
        entradas.append(_entrada_vacia(nuevo_id, apal_prev))
        st.session_state["sen_entrada_next_id"] += 1
        st.rerun()

    incompletas = [i + 1 for i, e in enumerate(entradas) if (e["precio"] > 0) != (e["margen"] > 0)]
    if incompletas:
        st.warning("⚠️ Completá precio **y** margen de apertura en la(s) entrada(s): "
                   + ", ".join(str(n) for n in incompletas)
                   + ". Las incompletas no se tienen en cuenta.")

    resumen = _resumen_posicion(_entradas_para_guardar(entradas, es_pendiente), es_largo)
    if resumen:
        _render_resumen_posicion(resumen, es_largo)

    return entradas


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
        "entradas": datos.get("entradas", []),
        "stop_loss": datos["stop_loss"], "take_profit": datos["take_profit"],
        "apalancamiento": datos["apalancamiento"],
        "riesgo_conservador": datos.get("riesgo_conservador", PERFILES_RIESGO["conservador"]["default_pct"]),
        "riesgo_moderado": datos.get("riesgo_moderado", PERFILES_RIESGO["moderado"]["default_pct"]),
        "riesgo_agresivo": datos.get("riesgo_agresivo", PERFILES_RIESGO["agresivo"]["default_pct"]),
        "apal_conservador": datos.get("apal_conservador"),
        "apal_moderado": datos.get("apal_moderado"),
        "apal_agresivo": datos.get("apal_agresivo"),
        "notas": datos.get("notas", ""),
        "estado": datos.get("estado", "ABIERTA"),
        "fecha_activacion": None, "hora_activacion": None,
        "precio_cierre": None, "fecha_cierre": None, "hora_cierre": None,
    }
    supabase.table(TABLA_SENALES).insert(row).execute()


@st.cache_data(ttl=120, show_spinner=False)
def _obtener_senales(_supabase, limite=200):
    res = (_supabase.table(TABLA_SENALES).select("*")
           .order("fecha", desc=True).order("hora", desc=True).limit(limite).execute())
    return res.data or []


def _actualizar_estado_senal(supabase, senal_id, estado, precio_cierre, fecha_cierre, hora_cierre=None):
    supabase.table(TABLA_SENALES).update({
        "estado": estado,
        "precio_cierre": precio_cierre,
        "fecha_cierre": str(fecha_cierre) if fecha_cierre else None,
        "hora_cierre": hora_cierre,
    }).eq("id", senal_id).execute()


def _borrar_senal(supabase, senal_id):
    supabase.table(TABLA_SENALES).delete().eq("id", senal_id).execute()


def _cerrar_senal_manual(supabase, senal_id, precio_cierre):
    supabase.table(TABLA_SENALES).update({
        "estado": "CERRADA MANUAL",
        "precio_cierre": precio_cierre,
        "fecha_cierre": str(date.today()),
        "hora_cierre": datetime.now().strftime("%H:%M:%S"),
    }).eq("id", senal_id).execute()


def _entradas_a_formato_guardado(entradas):
    """Convierte entradas normalizadas (con 'peso') al formato que se
    guarda en la columna jsonb 'entradas' (sin 'peso'), preservando el
    estado de activación de cada entrada (para órdenes pendientes)."""
    return [
        {"precio": e["precio"], "costo_apertura": e["costo_apertura"],
         "apalancamiento": e["apalancamiento"], "margen": e["margen"],
         "margen_extra": e.get("margen_extra", 0.0),
         "activada": e.get("activada", True),
         "fecha_activacion": e.get("fecha_activacion"),
         "hora_activacion": e.get("hora_activacion")}
        for e in entradas
    ]


def _agregar_entrada_senal(supabase, senal_id, entradas, precio_entrada, apalancamiento):
    supabase.table(TABLA_SENALES).update({
        "entradas": entradas,
        "precio_entrada": precio_entrada,
        "apalancamiento": apalancamiento,
    }).eq("id", senal_id).execute()


# ==============================================================
#  EVALUACIÓN AUTOMÁTICA — ¿tocó TP o SL primero? / ¿se activó la
#  entrada de una orden pendiente?
#  Usa velas HORARIAS (últimos 7 días, filtradas desde el momento
#  exacto de referencia) para no contar movimientos de precio
#  ANTERIORES a ese momento el mismo día, y velas diarias (High/Low)
#  para los días siguientes (yfinance no tiene 1h para rangos largos).
#  Si TP y SL se tocan en la misma vela, se asume el peor caso (SL)
#  porque no siempre tenemos el orden exacto dentro de la vela — es
#  una simplificación conservadora, no una garantía de precisión.
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


@st.cache_data(ttl=900, show_spinner=False)
def _historial_intradia_desde(ticker, fecha_str, hora_str):
    """Velas horarias (1h) de los últimos 7 días, filtradas a partir del
    momento de referencia (fecha_str + hora_str) en adelante. Sirve para
    no contar como 'tocado' un TP/SL/precio de entrada que el mercado ya
    había tocado ANTES de ese momento, si eso pasó el mismo día.
    NOTA: yfinance devuelve el índice en la zona horaria del mercado del
    ticker (ej. hora de Nueva York para acciones de EE.UU.), mientras que
    fecha_str/hora_str son la fecha/hora locales de quien publicó la
    señal. Se comparan como si fueran la misma zona horaria (se descarta
    el tz-info de ambos lados) — es una aproximación, igual que las
    demás simplificaciones horarias de este módulo; puede haber un
    corrimiento de algunas horas según el instrumento."""
    try:
        import yfinance as yf
        df = yf.download(ticker, period="7d", interval="1h",
                          auto_adjust=True, progress=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Close"])
        if df.empty:
            return None
        df = df.copy()
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        try:
            corte = pd.Timestamp(f"{fecha_str} {hora_str or '00:00:00'}")
        except Exception:
            return df
        df = df[df.index >= corte]
        return df if not df.empty else None
    except Exception:
        return None


def _construir_historial_activacion(ticker, fecha_anchor, hora_anchor):
    """Historial combinado (velas horarias recientes + velas diarias)
    desde un momento de referencia (fecha_anchor + hora_anchor) en
    adelante, como lista de tuplas (timestamp, high, low, es_intradia)
    ordenada cronológicamente. Se usa tanto para detectar cuándo se
    activa una orden pendiente como para evaluar TP/SL de una posición
    ya abierta, evitando contar movimientos de precio ANTERIORES al
    momento de referencia si eso pasó el mismo día."""
    filas = []
    hist_intra = _historial_intradia_desde(
        ticker, str(fecha_anchor), str(hora_anchor) if hora_anchor else None)
    if hist_intra is not None and not hist_intra.empty:
        for ts, fila in hist_intra.iterrows():
            hi = float(fila["High"]) if "High" in fila else float(fila["Close"])
            lo = float(fila["Low"]) if "Low" in fila else float(fila["Close"])
            filas.append((ts, hi, lo, True))

    try:
        fecha_dt = datetime.strptime(str(fecha_anchor), "%Y-%m-%d").date()
        fecha_desde_diario = str(fecha_dt + timedelta(days=1))
    except Exception:
        fecha_desde_diario = str(fecha_anchor)

    hist_d = _historial_desde_fecha(ticker, fecha_desde_diario)
    if hist_d is not None and not hist_d.empty:
        for ts, fila in hist_d.iterrows():
            hi = float(fila["High"]) if "High" in fila else float(fila["Close"])
            lo = float(fila["Low"]) if "Low" in fila else float(fila["Close"])
            filas.append((ts, hi, lo, False))

    filas.sort(key=lambda x: x[0])
    return filas


# ── P&L EN VIVO (precio actualizado cada 5 minutos) ──────────────
# Caché propia de 5 minutos, separada de la caché de 15 minutos que
# usa _historial_desde_fecha / _historial_intradia_desde (esas son
# para evaluar TP/SL y activaciones con datos horarios/diarios). Acá
# buscamos el precio más reciente posible para mostrar si la posición
# abierta viene ganando o perdiendo AHORA.

@st.cache_data(ttl=300, show_spinner=False)
def _precio_en_vivo(ticker):
    """Último precio disponible, refrescado cada 5 minutos. Intenta
    primero con velas de 1 minuto (intradía); si no hay datos
    (mercado cerrado, activo sin intradía en Yahoo, etc.) cae a la
    última vela diaria disponible. Devuelve (precio, hora_consulta)
    o (None, None) si no se pudo obtener nada."""
    try:
        import yfinance as yf
        df = yf.download(ticker, period="1d", interval="1m",
                          auto_adjust=True, progress=False)
        if df is None or df.empty:
            df = yf.download(ticker, period="5d", interval="1d",
                              auto_adjust=True, progress=False)
        if df is None or df.empty:
            return None, None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        serie = df["Close"].dropna()
        if serie.empty:
            return None, None
        return float(serie.iloc[-1]), datetime.now()
    except Exception:
        return None, None


def _pnl_vivo_senal(senal, precio_actual):
    """P&L en vivo (%) de una señal ABIERTA contra el precio actual,
    usando el precio promedio ponderado de las entradas y el
    apalancamiento DE APERTURA de la señal (el que realmente usaste,
    sin diluir por margen extra). Devuelve None si faltan datos
    válidos para calcularlo."""
    if precio_actual is None or precio_actual <= 0:
        return None
    entrada = _precio_promedio_ponderado(senal)
    if not entrada or entrada <= 0:
        return None
    apalancamiento = _apalancamiento_apertura_de_senal(senal)
    es_largo = "LARGO" in str(senal.get("tipo", "")).upper()
    ret_precio = (precio_actual - entrada) / entrada
    if not es_largo:
        ret_precio = -ret_precio
    ret_apalancado = ret_precio * apalancamiento
    return dict(
        ret_precio=ret_precio * 100,
        ret_apalancado=ret_apalancado * 100,
        ganando=ret_apalancado > 0,
        entrada=entrada,
        precio_actual=precio_actual,
    )


def _render_badge_pnl_vivo(pnl, hora_actualizacion):
    """Cartel grande de 🟢 GANANDO / 🔴 PERDIENDO con el % apalancado
    en vivo. Si no hay datos, muestra un aviso discreto en vez de
    romper el resto de la ficha de la señal."""
    if pnl is None:
        st.caption("⏳ No se pudo obtener el precio en vivo para esta señal en este momento.")
        return

    color = "#3fb950" if pnl["ganando"] else "#f85149"
    bg = "rgba(63,185,80,0.12)" if pnl["ganando"] else "rgba(248,81,73,0.12)"
    icono = "🟢" if pnl["ganando"] else "🔴"
    texto = "GANANDO" if pnl["ganando"] else "PERDIENDO"

    hace = ""
    if hora_actualizacion:
        mins = int((datetime.now() - hora_actualizacion).total_seconds() // 60)
        hace = "recién" if mins <= 0 else f"hace {mins} min"

    st.markdown(f"""
    <div style="background:{bg};border:1px solid {color};border-radius:10px;
         padding:10px 16px;margin:8px 0 4px 0;display:flex;align-items:center;
         justify-content:space-between;flex-wrap:wrap;gap:8px">
      <div>
        <div style="font-size:11px;color:{color};font-weight:700;letter-spacing:.5px">
          {icono} POSICIÓN EN VIVO — {texto}
        </div>
        <div style="font-size:10px;color:#8b949e;margin-top:2px">
          Precio actual: {fmt_precio_exacto(pnl['precio_actual'])} · Entrada: {fmt_precio_exacto(pnl['entrada'])}
          · actualizado {hace} (se refresca cada 5 min)
        </div>
      </div>
      <div style="font-size:20px;font-weight:800;color:{color};white-space:nowrap">
        {pnl['ret_apalancado']:+.2f}%
      </div>
    </div>
    """, unsafe_allow_html=True)


def _evaluar_pendiente(senal):
    """Recorre el historial desde la publicación de una orden PENDIENTE
    y marca qué entradas se activaron (el precio de mercado las tocó,
    dentro del rango High/Low de cada vela). Devuelve
    (entradas_actualizadas, todas_activadas, fecha_activacion,
    hora_activacion) — 'fecha_activacion'/'hora_activacion' son las de
    la ÚLTIMA entrada en activarse (el momento en que la posición queda
    completamente abierta, desde donde arranca después la evaluación
    de TP/SL). No escribe en Supabase, eso lo hace el caller."""
    entradas = _entradas_de_senal(senal)
    pendientes_idx = [i for i, e in enumerate(entradas) if not e.get("activada")]
    if not pendientes_idx:
        return entradas, True, senal.get("fecha_activacion"), senal.get("hora_activacion")

    filas = _construir_historial_activacion(senal["ticker"], senal["fecha"], senal.get("hora"))
    ultima_fecha_act = senal.get("fecha_activacion")
    ultima_hora_act = senal.get("hora_activacion")

    for ts, hi, lo, es_intradia in filas:
        if not pendientes_idx:
            break
        for i in list(pendientes_idx):
            precio_obj = entradas[i]["precio"]
            if lo <= precio_obj <= hi:
                entradas[i]["activada"] = True
                entradas[i]["fecha_activacion"] = str(ts.date())
                entradas[i]["hora_activacion"] = ts.strftime("%H:%M:%S") if es_intradia else None
                ultima_fecha_act = entradas[i]["fecha_activacion"]
                ultima_hora_act = entradas[i]["hora_activacion"] or ultima_hora_act
                pendientes_idx.remove(i)

    todas = len(pendientes_idx) == 0
    return entradas, todas, ultima_fecha_act, ultima_hora_act


def _evaluar_senal(senal):
    """Devuelve dict con: estado_calc, precio_ref (cierre o último
    precio), fecha_ref, hora_ref (si se pudo determinar con precisión
    horaria), es_final. No escribe en Supabase — eso lo hace el caller
    si corresponde. El punto de partida para buscar toques de TP/SL es
    'fecha_activacion'/'hora_activacion' si la señal viene de una orden
    pendiente que ya se llenó, o 'fecha'/'hora' (momento de
    publicación) si se publicó directamente como posición abierta."""
    if senal.get("estado") in ("CERRADA MANUAL",):
        return dict(estado_calc=senal["estado"], precio_ref=senal.get("precio_cierre"),
                    fecha_ref=senal.get("fecha_cierre"), hora_ref=senal.get("hora_cierre"),
                    es_final=True)

    ticker = senal["ticker"]
    tipo = senal["tipo"]
    entrada = _precio_promedio_ponderado(senal)
    sl = float(senal["stop_loss"])
    tp = float(senal["take_profit"])
    es_largo = tipo.startswith("🟢") or "LARGO" in tipo.upper()

    fecha_anchor = senal.get("fecha_activacion") or senal.get("fecha")
    hora_anchor = senal.get("hora_activacion") or senal.get("hora")

    filas = _construir_historial_activacion(ticker, fecha_anchor, hora_anchor)
    if not filas:
        return dict(estado_calc="ABIERTA", precio_ref=entrada, fecha_ref=None,
                    hora_ref=None, es_final=False)

    for ts, hi, lo, es_intradia in filas:
        if es_largo:
            toco_sl = lo <= sl
            toco_tp = hi >= tp
        else:
            toco_sl = hi >= sl
            toco_tp = lo <= tp
        if toco_sl:
            return dict(estado_calc="DESACIERTO (SL)", precio_ref=sl, fecha_ref=ts.date(),
                        hora_ref=ts.strftime("%H:%M:%S") if es_intradia else None, es_final=True)
        if toco_tp:
            return dict(estado_calc="ACIERTO (TP)", precio_ref=tp, fecha_ref=ts.date(),
                        hora_ref=ts.strftime("%H:%M:%S") if es_intradia else None, es_final=True)

    ultimo_precio, _ts = _precio_en_vivo(ticker)
    if ultimo_precio is None:
        ultimo_precio = entrada
    return dict(estado_calc="ABIERTA", precio_ref=ultimo_precio, fecha_ref=None,
                hora_ref=None, es_final=False)


def _sincronizar_estados(supabase, senales):
    """Recorre las señales PENDIENTES (órdenes límite todavía no
    ejecutadas) y las ABIERTAS. Para las pendientes, revisa si el
    precio ya tocó cada entrada desde la publicación y, cuando TODAS
    se activaron, pasa la señal a ABIERTA (recién ahí arranca la
    evaluación de TP/SL, desde el momento de esa activación). Para las
    abiertas, si la evaluación automática determinó un cierre (TP o
    SL), lo persiste. La hora de cierre es la exacta si se detectó con
    velas horarias recientes; si no, es la del momento en que ESTA
    función detectó el cierre (aproximada)."""
    actualizadas = False
    for s in senales:
        estado_s = s.get("estado")

        if estado_s == "PENDIENTE":
            entradas_act, todas, f_act, h_act = _evaluar_pendiente(s)
            entradas_fmt = _entradas_a_formato_guardado(entradas_act)
            if todas:
                es_largo_s = "LARGO" in str(s.get("tipo", "")).upper()
                res_final = _resumen_posicion(entradas_fmt, es_largo_s)
                supabase.table(TABLA_SENALES).update({
                    "entradas": entradas_fmt,
                    "estado": "ABIERTA",
                    "fecha_activacion": f_act,
                    "hora_activacion": h_act,
                    "precio_entrada": (res_final["precio_promedio"] if res_final
                                       else s.get("precio_entrada")),
                    "apalancamiento": (res_final["apalancamiento_apertura"] if res_final
                                       else s.get("apalancamiento")),
                }).eq("id", s["id"]).execute()
                actualizadas = True
            elif any(e.get("activada") for e in entradas_act):
                supabase.table(TABLA_SENALES).update(
                    {"entradas": entradas_fmt}).eq("id", s["id"]).execute()
                actualizadas = True
            continue

        if estado_s != "ABIERTA":
            continue
        ev = _evaluar_senal(s)
        if ev["es_final"] and ev["estado_calc"] != "ABIERTA":
            _actualizar_estado_senal(supabase, s["id"], ev["estado_calc"],
                                      ev["precio_ref"], ev["fecha_ref"],
                                      hora_cierre=ev.get("hora_ref") or datetime.now().strftime("%H:%M:%S"))
            actualizadas = True
    if actualizadas:
        _obtener_senales.clear()
    return actualizadas


# ==============================================================
#  CÁLCULO DE RETORNO / P&L
#  Estas funciones siguen leyendo senal["precio_entrada"] como
#  siempre. Ese campo se guarda como el precio PROMEDIO REAL de la
#  posición (ponderado por el tamaño de cada entrada). El
#  apalancamiento, en cambio, YA NO se lee directo de
#  senal["apalancamiento"]: se recalcula con
#  _apalancamiento_apertura_de_senal para no arrastrar la dilución
#  que genera el margen extra (ver esa función).
# ==============================================================

def _calcular_retorno(senal, precio_salida):
    """Modo 'capital': el retorno % se aplica directamente sobre el
    monto asignado, multiplicado por el apalancamiento de apertura de
    la señal."""
    entrada = float(senal["precio_entrada"])
    apalancamiento = _apalancamiento_apertura_de_senal(senal)
    es_largo = "LARGO" in senal["tipo"].upper()
    if entrada == 0:
        return 0.0, 0.0
    ret_precio = (precio_salida - entrada) / entrada
    if not es_largo:
        ret_precio = -ret_precio
    ret_apalancado = ret_precio * apalancamiento
    return ret_precio * 100, ret_apalancado * 100


def _calcular_pnl_lotes(senal, precio_salida, unidades):
    """Cálculo de P&L como lo hace un bróker real. El resultado en
    dinero depende del movimiento de precio y del tamaño de la
    posición (unidades), NO directamente del apalancamiento. El
    apalancamiento solo define cuánto margen (capital) necesitás
    inmovilizar para abrir esa posición.

    Devuelve: (pnl_usd, margen_usado, retorno_%_sobre_margen)
    """
    entrada = float(senal["precio_entrada"])
    apalancamiento = _apalancamiento_apertura_de_senal(senal)
    es_largo = "LARGO" in senal["tipo"].upper()
    if entrada == 0 or unidades <= 0:
        return 0.0, 0.0, 0.0
    diff = (precio_salida - entrada) if es_largo else (entrada - precio_salida)
    pnl_usd = diff * unidades
    nominal = entrada * unidades
    margen = nominal / apalancamiento if apalancamiento else nominal
    ret_pct_margen = (pnl_usd / margen * 100) if margen else 0.0
    return pnl_usd, margen, ret_pct_margen


def _tamano_posicion_por_riesgo(senal, capital, pct_riesgo):
    """Calcula el tamaño de posición para que, si el precio llega al
    Stop Loss, la pérdida sea exactamente pct_riesgo % del capital.
    Devuelve dict con riesgo_usd, unidades, nominal y margen (o None
    si faltan datos válidos)."""
    entrada = float(senal.get("precio_entrada") or 0)
    sl = float(senal.get("stop_loss") or 0)
    apalancamiento = _apalancamiento_apertura_de_senal(senal)
    distancia_precio = abs(entrada - sl)
    if entrada <= 0 or distancia_precio <= 0:
        return None
    riesgo_usd = capital * pct_riesgo / 100
    unidades = riesgo_usd / distancia_precio
    nominal = unidades * entrada
    margen = nominal / apalancamiento
    return dict(riesgo_usd=riesgo_usd, unidades=unidades, nominal=nominal, margen=margen)


# ==============================================================
#  RENDER — TAB PUBLICAR (solo admin)
#  Ahora también incluye "Gestionar señales publicadas" (eliminar)
#  y la definición de los 3 perfiles de riesgo de la señal.
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
        categoria = st.selectbox("🏷️ Categoría del activo", CATEGORIAS, key="sen_categoria")
    with c3:
        tipo = st.selectbox("Tipo de operación", ["🟢 LARGO (Compra)", "🔴 CORTO (Venta)"], key="sen_tipo")

    es_largo_pub = "LARGO" in tipo.upper()

    f1, f2 = st.columns(2)
    with f1:
        fecha = st.date_input("📅 Fecha", value=date.today(), key="sen_fecha")
    with f2:
        hora = st.time_input("🕐 Hora", value=datetime.now().time().replace(microsecond=0), key="sen_hora")

    es_pendiente_pub = st.checkbox(
        "🕓 Dejar como orden pendiente (se activa sola cuando el precio toque la entrada)",
        key="sen_es_pendiente",
        help="Si lo marcás, el/los precio(s) de 'Entradas' de abajo se guardan como una orden "
             "límite: la señal queda en estado PENDIENTE y NO empieza a evaluar Take Profit / "
             "Stop Loss todavía. En segundo plano se revisa el precio de mercado desde este "
             "momento en adelante y, apenas toca el precio de una entrada, esa entrada se marca "
             "activada. Cuando TODAS las entradas se activaron, la señal pasa sola a ABIERTA y "
             "recién ahí arranca la evaluación de TP/SL (desde el momento de esa activación, no "
             "desde ahora) — así se evita que el precio ya hubiera tocado el TP o el SL antes de "
             "que la orden se ejecutara.")

    st.divider()
    entradas_form = _render_entradas_form(es_largo_pub, es_pendiente_pub)
    entradas_guardar = _entradas_para_guardar(entradas_form, es_pendiente_pub)
    resumen_pub = _resumen_posicion(entradas_guardar, es_largo_pub)
    precio_entrada_pos = resumen_pub["precio_promedio"] if resumen_pub else 0.0
    apal_apertura_pub = resumen_pub["apalancamiento_apertura"] if resumen_pub else 1.0

    st.divider()
    p2, p3 = st.columns(2)
    with p2:
        stop_loss = st.number_input("🛑 Stop Loss", min_value=0.0, format="%.5f", key="sen_sl")
    with p3:
        take_profit = st.number_input("🎯 Take Profit", min_value=0.0, format="%.5f", key="sen_tp")

    notas = st.text_area("💬 Notas / justificación", key="sen_notas", height=80,
                          placeholder="Motivo de la señal, contexto técnico o fundamental...")

    # Validación visual rápida antes de guardar (contra el precio promedio real,
    # que en una orden pendiente es el precio OBJETIVO de entrada)
    if precio_entrada_pos > 0 and stop_loss > 0 and take_profit > 0:
        ok_niveles = (stop_loss < precio_entrada_pos < take_profit) if es_largo_pub \
            else (take_profit < precio_entrada_pos < stop_loss)
        if not ok_niveles:
            st.warning("⚠️ Revisá los niveles: para LARGO, SL < Entrada < TP. Para CORTO, TP < Entrada < SL. "
                       "(Se valida contra el precio promedio de las entradas.)")

    if resumen_pub and _sl_mas_alla_de_liquidacion(resumen_pub, es_largo_pub, stop_loss):
        st.error(_md_dolar(
            f"🚨 Tu Stop Loss ({fmt_precio_exacto(stop_loss)}) queda más allá del precio de "
            f"liquidación ({fmt_precio_exacto(resumen_pub['precio_liquidacion'])}): con el margen y "
                        "apalancamiento cargados te liquidarían antes de que el SL se ejecute."))

    st.divider()
    st.markdown("#### 🎭 Apalancamiento sugerido por perfil")
    st.caption(
        "Definí con qué apalancamiento sugerís tomar esta señal en cada perfil de riesgo "
        "(se usa en 'Señales y Resultados', al replicar la posición con un apalancamiento "
        "distinto al de apertura)."
    )
    rp1, rp2, rp3 = st.columns(3)
    with rp1:
        apal_conservador = st.number_input(
            f"{PERFILES_RIESGO['conservador']['label']} — apalancamiento sugerido", min_value=1.0,
            max_value=125.0, value=float(apal_apertura_pub), step=1.0, format="%.1f",
            key="sen_apal_conservador")
    with rp2:
        apal_moderado = st.number_input(
            f"{PERFILES_RIESGO['moderado']['label']} — apalancamiento sugerido", min_value=1.0,
            max_value=125.0, value=float(apal_apertura_pub), step=1.0, format="%.1f",
            key="sen_apal_moderado")
    with rp3:
        apal_agresivo = st.number_input(
            f"{PERFILES_RIESGO['agresivo']['label']} — apalancamiento sugerido", min_value=1.0,
            max_value=125.0, value=float(apal_apertura_pub), step=1.0, format="%.1f",
            key="sen_apal_agresivo")

    if not (apal_conservador <= apal_moderado <= apal_agresivo):
        st.warning("⚠️ Lo lógico es que Conservador ≤ Moderado ≤ Agresivo en el apalancamiento sugerido.")

    # El % de riesgo por perfil ya no se pide al publicar: se usan los defaults
    # (1% / 2% / 3%) solo para el Simulador de Capital, pestaña "Comparar perfiles".
    riesgo_conservador = PERFILES_RIESGO["conservador"]["default_pct"]
    riesgo_moderado = PERFILES_RIESGO["moderado"]["default_pct"]
    riesgo_agresivo = PERFILES_RIESGO["agresivo"]["default_pct"]

    label_btn_pub = "🕓 Dejar orden pendiente" if es_pendiente_pub else "📢 Publicar señal"
    if st.button(label_btn_pub, type="primary", key="sen_btn_publicar"):
        if not ticker or not resumen_pub or stop_loss <= 0 or take_profit <= 0:
            st.warning("⚠️ Completá ticker, al menos una entrada con precio y margen válidos, "
                       "stop loss y take profit.")
        else:
            datos = dict(ticker=ticker, categoria=categoria, tipo=tipo, fecha=fecha, hora=hora,
                         precio_entrada=precio_entrada_pos, entradas=entradas_guardar,
                         stop_loss=stop_loss, take_profit=take_profit,
                         apalancamiento=apal_apertura_pub, notas=notas,
                         riesgo_conservador=riesgo_conservador, riesgo_moderado=riesgo_moderado,
                         riesgo_agresivo=riesgo_agresivo,
                         apal_conservador=apal_conservador, apal_moderado=apal_moderado,
                         apal_agresivo=apal_agresivo,
                         estado="PENDIENTE" if es_pendiente_pub else "ABIERTA")
            try:
                _guardar_senal(supabase, datos, user_id, user_email)
                _obtener_senales.clear()
                if es_pendiente_pub:
                    st.success("✅ Orden pendiente creada. Se activará sola en cuanto el precio "
                               "toque cada entrada.")
                else:
                    st.success("✅ Señal publicada.")
                for k in ["sen_ticker", "sen_notas"]:
                    st.session_state.pop(k, None)
                _reset_entradas_state()
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error al publicar: {e}")

    # ----------------------------------------------------------
    #  Gestionar señales publicadas (eliminar) — todo desde acá
    # ----------------------------------------------------------
    st.divider()
    st.markdown("#### 🗂️ Gestionar señales publicadas")
    st.caption("Eliminá cualquier señal —pendiente, abierta o cerrada— desde acá. El resto de "
               "los usuarios solo puede ver y simular, nunca borrar.")

    senales_admin = _obtener_senales(supabase, 200)
    if not senales_admin:
        st.info("Todavía no hay señales publicadas.")
        return

    df_admin = pd.DataFrame(senales_admin)
    if "categoria" not in df_admin.columns:
        df_admin["categoria"] = "🔹 Otro"
    df_admin["categoria"] = df_admin["categoria"].fillna("🔹 Otro")

    fa1, fa2, fa3 = st.columns(3)
    with fa1:
        tickers_admin = ["Todos"] + sorted(df_admin["ticker"].dropna().unique().tolist())
        f_tk_admin = st.selectbox("Filtrar ticker", tickers_admin, key="sen_admin_f_tk")
    with fa2:
        estados_admin = ["Todos"] + sorted(df_admin["estado"].dropna().unique().tolist())
        f_estado_admin = st.selectbox("Filtrar estado", estados_admin, key="sen_admin_f_estado")
    with fa3:
        categorias_admin = ["Todas"] + sorted(df_admin["categoria"].dropna().unique().tolist())
        f_cat_admin = st.selectbox("Filtrar categoría", categorias_admin, key="sen_admin_f_cat")

    df_admin_f = df_admin.copy()
    if f_tk_admin != "Todos": df_admin_f = df_admin_f[df_admin_f["ticker"] == f_tk_admin]
    if f_estado_admin != "Todos": df_admin_f = df_admin_f[df_admin_f["estado"] == f_estado_admin]
    if f_cat_admin != "Todas": df_admin_f = df_admin_f[df_admin_f["categoria"] == f_cat_admin]

    st.caption(f"{len(df_admin_f)} señales mostradas de {len(df_admin)} totales")

    for _, row in df_admin_f.iterrows():
        estado_row = row.get("estado", "ABIERTA")
        col, bg, emoji = ESTADO_COLOR.get(estado_row, ("#8b949e", "rgba(139,148,158,0.12)", "⚪"))
        categoria_row = row.get("categoria") or "🔹 Otro"
        titulo = (f"{row.get('fecha','')} {row.get('hora','')} · {row.get('ticker','')} · "
                  f"{categoria_row} · {row.get('tipo','')} · {estado_row}")
        with st.expander(f"{emoji} {titulo}"):
            entradas_lista = _entradas_de_senal(row.to_dict())
            v1, v2, v3, v4 = st.columns(4)
            v1.metric("Entrada (prom. ponderado)" if len(entradas_lista) > 1 else "Entrada",
                      fmt_precio_local(row.get("precio_entrada")))
            v2.metric("Stop Loss", fmt_precio_local(row.get("stop_loss")))
            v3.metric("Take Profit", fmt_precio_local(row.get("take_profit")))
            v4.metric("Apalancamiento", fmt_apal(_apalancamiento_apertura_de_senal(row.to_dict())))

            if estado_row == "PENDIENTE":
                n_act = sum(1 for e in entradas_lista if e.get("activada"))
                st.caption(f"🕓 Orden pendiente — {n_act}/{len(entradas_lista)} entradas activadas.")

            if len(entradas_lista) > 1:
                st.caption(_md_dolar(f"🧩 {len(entradas_lista)} entradas → {_texto_entradas(entradas_lista)}"))

            es_largo_row = "LARGO" in str(row.get("tipo", "")).upper()
            res_row = _resumen_de_senal(row.to_dict())
            if res_row:
                _render_resumen_posicion(res_row, es_largo_row,
                                          stop_loss=float(row.get("stop_loss") or 0))

            st.caption(
                f"Perfiles de riesgo → 🟢 {row.get('riesgo_conservador', PERFILES_RIESGO['conservador']['default_pct']):.1f}% · "
                f"🟡 {row.get('riesgo_moderado', PERFILES_RIESGO['moderado']['default_pct']):.1f}% · "
                f"🔴 {row.get('riesgo_agresivo', PERFILES_RIESGO['agresivo']['default_pct']):.1f}%"
            )
            if row.get("precio_cierre") is not None:
                hora_cierre_txt = row.get("hora_cierre")
                st.caption(_md_dolar(
                    f"Cerrada el {row.get('fecha_cierre','')}"
                    + (f" a las {hora_cierre_txt}" if hora_cierre_txt else "")
                    + f" a {fmt_precio_local(row.get('precio_cierre'))}"
                ))
            if row.get("notas"):
                st.markdown(f"**Notas:** {row['notas']}")

            if estado_row == "ABIERTA":
                st.divider()
                with st.expander("➕ Agregar otra entrada a esta posición (promediar / alejar liquidación)"):
                    st.caption(
                        "Sumá una entrada nueva a esta posición ABIERTA: sirve para promediar a "
                        "un precio mejor (mueve el precio promedio) o para agregar margen y alejar "
                        "la liquidación. Se recalcula el precio de entrada (promedio ponderado) y "
                        "el apalancamiento de apertura de toda la posición."
                    )
                    ae1, ae2, ae3, ae4, ae5 = st.columns(5)
                    with ae1:
                        nueva_precio = st.number_input(
                            "Precio", min_value=0.0, format="%.5f", key=f"sen_add_precio_{row['id']}")
                    with ae2:
                        nueva_costo = st.number_input(
                            "Costo apertura (USD)", min_value=0.0, step=0.01, format="%.4f",
                            key=f"sen_add_costo_{row['id']}")
                    with ae3:
                        nueva_apal = st.number_input(
                            "Apalanc. (x)", min_value=1.0, max_value=125.0, step=1.0, format="%.1f",
                            value=1.0, key=f"sen_add_apal_{row['id']}")
                    with ae4:
                        nueva_margen = st.number_input(
                            "Margen apertura (USD)", min_value=0.0, step=10.0, format="%.2f",
                            key=f"sen_add_margen_{row['id']}")
                    with ae5:
                        nueva_margen_extra = st.number_input(
                            "Margen extra (USD)", min_value=0.0, step=10.0, format="%.2f",
                            key=f"sen_add_margen_extra_{row['id']}")

                    if st.button("➕ Agregar entrada a la posición", key=f"sen_add_btn_{row['id']}"):
                        if nueva_precio <= 0 or nueva_margen <= 0:
                            st.warning("⚠️ Completá al menos precio y margen de apertura de la nueva entrada.")
                        else:
                            entradas_actuales_fmt = _entradas_a_formato_guardado(entradas_lista)
                            entradas_nuevas = entradas_actuales_fmt + [{
                                "precio": nueva_precio, "costo_apertura": nueva_costo,
                                "apalancamiento": nueva_apal, "margen": nueva_margen,
                                "margen_extra": nueva_margen_extra,
                                "activada": True, "fecha_activacion": None, "hora_activacion": None,
                            }]
                            resumen_nuevo = _resumen_posicion(entradas_nuevas, es_largo_row)
                            if resumen_nuevo is None:
                                st.error("❌ No se pudo calcular la posición con esta entrada.")
                            else:
                                _agregar_entrada_senal(
                                    supabase, row["id"], entradas_nuevas,
                                    resumen_nuevo["precio_promedio"],
                                    resumen_nuevo["apalancamiento_apertura"])
                                _obtener_senales.clear()
                                st.success("✅ Entrada agregada. Se recalculó el precio promedio "
                                          "y el apalancamiento de apertura.")
                                st.rerun()

                st.divider()
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

            if estado_row == "PENDIENTE":
                st.caption("🔧 Esta orden todavía no se puede cerrar ni ampliar manualmente: "
                           "esperá a que se active sola, o eliminala si ya no la querés.")

            st.divider()
            confirmar = st.checkbox("Confirmar eliminación", key=f"sen_admin_confirm_del_{row['id']}")
            if st.button("🗑️ Eliminar señal", key=f"sen_admin_btn_del_{row['id']}",
                         disabled=not confirmar):
                _borrar_senal(supabase, row["id"])
                _obtener_senales.clear()
                st.success("Señal eliminada.")
                st.rerun()


# ==============================================================
#  RENDER — TAB SEÑALES Y RESULTADOS (todos ven)
#  Ya NO tiene botón de eliminar — eso vive en "Publicar Señal".
#  Ya NO tiene selector de "elegí con qué perfil tomar la señal"
#  (calculaba un tamaño de posición a partir de un % de riesgo, sin
#  chequear el precio de liquidación). En su lugar, "Replicá la
#  posición" deja elegir directamente el apalancamiento (apertura o
#  uno de los 3 sugeridos por el admin) con el que armar la posición.
#  Si hay varias entradas, se muestran todas (precio, margen,
#  apalancamiento, costo), el precio promedio real de la posición y
#  el precio de liquidación. Las señales ABIERTAS además muestran un
#  cartel de P&L en vivo (🟢/🔴), con precio actualizado cada 5 min.
#  Las señales PENDIENTES (órdenes límite) muestran en cambio qué
#  entradas ya se activaron y una vista previa de la posición, sin
#  P&L en vivo ni "Replicar" (todavía no hay margen puesto).
#  Ya NO permite agregar entradas ni cerrar manualmente una señal:
#  esa gestión (agregar entrada para promediar / cerrar la posición)
#  vive únicamente en "Publicar Señal", para que solo el admin la
#  haga desde un único lugar.
# ==============================================================

def _tab_senales(supabase, es_admin):
    # Autorefresh cada 5 min: recalcula el P&L en vivo de las señales
    # abiertas y revisa activaciones de órdenes pendientes sin que el
    # usuario tenga que tocar nada.
    st_autorefresh(interval=5 * 60 * 1000, key="sen_autorefresh_pnl_vivo")

    top1, top2 = st.columns([3, 1])
    with top1:
        st.caption("Historial de señales publicadas y órdenes pendientes, con evaluación "
                   "automática de resultado y P&L en vivo (se actualiza cada 5 min) para las "
                   "que siguen abiertas.")
    with top2:
        if st.button("↺ Actualizar y evaluar", use_container_width=True, key="sen_refresh"):
            _obtener_senales.clear()
            _historial_desde_fecha.clear()
            _historial_intradia_desde.clear()
            _precio_en_vivo.clear()
            st.rerun()

    senales = _obtener_senales(supabase, 200)
    if not senales:
        st.info("Todavía no hay señales publicadas.")
        return

    with st.spinner("Evaluando señales pendientes y abiertas contra el precio de mercado..."):
        _sincronizar_estados(supabase, senales)
        senales = _obtener_senales(supabase, 200)

    df = pd.DataFrame(senales)
    if "categoria" not in df.columns:
        df["categoria"] = "🔹 Otro"
    df["categoria"] = df["categoria"].fillna("🔹 Otro")

    n_pendientes = int((df["estado"] == "PENDIENTE").sum())
    n_abiertas = int((df["estado"] == "ABIERTA").sum())
    n_acierto = int((df["estado"] == "ACIERTO (TP)").sum())
    n_desacierto = int((df["estado"] == "DESACIERTO (SL)").sum())
    n_cerradas_total = n_acierto + n_desacierto
    winrate = (n_acierto / n_cerradas_total * 100) if n_cerradas_total > 0 else 0.0

    # ── Resumen de P&L en vivo de las posiciones ABIERTAS ──────────────
    df_abiertas_kpi = df[df["estado"] == "ABIERTA"]
    n_ganando_vivo = 0
    n_perdiendo_vivo = 0
    if not df_abiertas_kpi.empty:
        with st.spinner("Consultando precios en vivo..."):
            for _, row_ab in df_abiertas_kpi.iterrows():
                precio_vivo_kpi, _ts_kpi = _precio_en_vivo(row_ab.get("ticker"))
                pnl_vivo_kpi = _pnl_vivo_senal(row_ab.to_dict(), precio_vivo_kpi)
                if pnl_vivo_kpi:
                    if pnl_vivo_kpi["ganando"]:
                        n_ganando_vivo += 1
                    else:
                        n_perdiendo_vivo += 1

    k0, k1, k2, k3, k4, k5, k6 = st.columns(7)
    with k0: st.metric("🕓 Pendientes", n_pendientes)
    with k1: st.metric("🔵 Abiertas", n_abiertas)
    with k2: st.metric("✅ Aciertos (TP)", n_acierto)
    with k3: st.metric("❌ Desaciertos (SL)", n_desacierto)
    with k4: st.metric("🎯 Win Rate", f"{winrate:.1f}%" if n_cerradas_total > 0 else "—")
    with k5: st.metric("🟢 Ganando ahora", n_ganando_vivo, "en vivo · cada 5 min")
    with k6: st.metric("🔴 Perdiendo ahora", n_perdiendo_vivo, "en vivo · cada 5 min")

    st.divider()

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

        if estado != "PENDIENTE":
            precio_ref = row.get("precio_cierre") if row.get("precio_cierre") is not None else None
            if precio_ref is None:
                ev = _evaluar_senal(row.to_dict())
                precio_ref = ev["precio_ref"]
            ret_precio, ret_apalancado = _calcular_retorno(row.to_dict(), precio_ref) if precio_ref else (0, 0)
        else:
            precio_ref = None
            ret_precio = ret_apalancado = 0

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

            # ── Orden PENDIENTE: mostrar qué entradas se activaron y una
            #    vista previa de la posición, y cortar acá (sin P&L,
            #    replicar, etc. — todavía no hay posición real abierta) ──
            if estado == "PENDIENTE":
                entradas_lista = _entradas_de_senal(row.to_dict())
                n_act = sum(1 for e in entradas_lista if e.get("activada"))
                st.info(f"🕓 Orden pendiente — {n_act}/{len(entradas_lista)} entradas activadas. "
                        "Se activa sola en cuanto el precio de mercado toque el precio de cada "
                        "entrada. Mientras está pendiente no cuenta para el Win Rate ni para el "
                        "Simulador de Capital.")
                for i, e in enumerate(entradas_lista):
                    if e.get("activada"):
                        detalle = f" el {e.get('fecha_activacion','')}"
                        if e.get("hora_activacion"):
                            detalle += f" {e['hora_activacion']}"
                        st.caption(f"✅ Entrada {i+1} ({fmt_precio_exacto(e['precio'])}) "
                                   f"activada{detalle}.")
                    else:
                        st.caption(f"⏳ Entrada {i+1} ({fmt_precio_exacto(e['precio'])}) "
                                   "esperando que el precio la toque.")
                v1, v2 = st.columns(2)
                v1.metric("Stop Loss", fmt_precio_local(row.get("stop_loss")))
                v2.metric("Take Profit", fmt_precio_local(row.get("take_profit")))
                es_largo_row = "LARGO" in str(row.get("tipo", "")).upper()
                res_preview = _resumen_de_senal(row.to_dict())
                if res_preview:
                    st.caption("Vista previa de la posición una vez que se activen todas las "
                               "entradas (con el margen y apalancamiento que se cargaron):")
                    _render_resumen_posicion(res_preview, es_largo_row,
                                              stop_loss=float(row.get("stop_loss") or 0))
                if row.get("notas"):
                    st.markdown(f"**Notas:** {row['notas']}")
                continue

            # ── Cartel de P&L en vivo (solo para señales ABIERTAS) ──────
            if estado == "ABIERTA":
                precio_vivo_row, ts_vivo_row = _precio_en_vivo(row.get("ticker"))
                pnl_vivo_row = _pnl_vivo_senal(row.to_dict(), precio_vivo_row)
                _render_badge_pnl_vivo(pnl_vivo_row, ts_vivo_row)

            entradas_lista = _entradas_de_senal(row.to_dict())
            v1, v2, v3, v4 = st.columns(4)
            v1.metric("Entrada (prom. ponderado)" if len(entradas_lista) > 1 else "Entrada",
                      fmt_precio_local(row.get("precio_entrada")))
            v2.metric("Stop Loss", fmt_precio_local(row.get("stop_loss")))
            v3.metric("Take Profit", fmt_precio_local(row.get("take_profit")))
            v4.metric("Apalancamiento", fmt_apal(_apalancamiento_apertura_de_senal(row.to_dict())))

            if row.get("fecha_activacion"):
                detalle_act = f"{row.get('fecha_activacion')}"
                if row.get("hora_activacion"):
                    detalle_act += f" {row.get('hora_activacion')}"
                st.caption(f"🕓 Esta posición venía de una orden pendiente: se activó el {detalle_act}. "
                           "El Take Profit / Stop Loss se evalúa desde ese momento en adelante.")

            if len(entradas_lista) > 1:
                st.caption(_md_dolar(f"🧩 {len(entradas_lista)} entradas cargadas → {_texto_entradas(entradas_lista)}"))
                st.caption("El precio de entrada de arriba es el promedio real de la posición "
                           "(ponderado por el tamaño de cada entrada). El Simulador de Capital usa "
                           "ese mismo precio.")

            es_largo_row = "LARGO" in str(row.get("tipo", "")).upper()
            res_row = _resumen_de_senal(row.to_dict())
            if res_row:
                _render_resumen_posicion(res_row, es_largo_row,
                                          stop_loss=float(row.get("stop_loss") or 0))

            v5, v6 = st.columns(2)
            v5.metric("Precio actual / cierre", fmt_precio_local(precio_ref))
            v6.metric("Retorno apalancado", f"{ret_apalancado:+.1f}%",
                      delta=f"{ret_precio:+.2f}% precio", delta_color="off")

            if row.get("precio_cierre") is not None:
                hora_cierre_txt = row.get("hora_cierre")
                st.caption(_md_dolar(
                    f"Cerrada el {row.get('fecha_cierre','')}"
                    + (f" a las {hora_cierre_txt}" if hora_cierre_txt else "")
                    + f" a {fmt_precio_local(row.get('precio_cierre'))}"
                ))

            if row.get("notas"):
                st.markdown(f"**Notas:** {row['notas']}")

            # ------------------------------------------------------
            #  Replicar la posición — elegís CON QUÉ APALANCAMIENTO:
            #  el de apertura original (escala tal cual todas las
            #  entradas del admin) o uno de los 3 sugeridos por perfil
            #  (arma una posición nueva, de una sola entrada, al
            #  precio promedio de la señal, con tu margen).
            # ------------------------------------------------------
            if res_row:
                st.divider()
                st.markdown("##### 🔁 Replicá la posición")

                opciones_apal_replica = {
                    f"Apertura ({fmt_apal(res_row['apalancamiento_apertura'])})":
                        ("apertura", res_row["apalancamiento_apertura"]),
                }
                for perfil_key_r in PERFILES_RIESGO:
                    apal_perfil_r = row.get(f"apal_{perfil_key_r}")
                    if apal_perfil_r:
                        label_perfil_r = (f"{PERFILES_RIESGO[perfil_key_r]['label']} "
                                          f"({fmt_apal(apal_perfil_r)})")
                        opciones_apal_replica[label_perfil_r] = (perfil_key_r, float(apal_perfil_r))

                apal_sel_label = st.radio(
                    "Apalancamiento a usar", list(opciones_apal_replica.keys()),
                    horizontal=True, key=f"sen_hist_replica_apal_{row['id']}")
                modo_apal_sel, apal_valor_sel = opciones_apal_replica[apal_sel_label]

                if modo_apal_sel == "apertura":
                    st.caption(
                        "Poné un solo número (tu margen) y la app copia la posición del publicador "
                        "tal cual: mismas entradas, mismos precios y el mismo apalancamiento en cada "
                        "una. El margen de apertura y el margen extra de cada entrada se escalan en "
                        "la misma proporción, y el precio de liquidación te queda igual que el del "
                        "publicador (escalar la posición no lo cambia)."
                    )
                    rr1, rr2 = st.columns([1.3, 1])
                    with rr1:
                        ref_replica_row = st.radio(
                            "Tu número corresponde a:", [REPLICA_REF_PRIMERA, REPLICA_REF_TOTAL],
                            horizontal=True, key=f"sen_hist_replica_ref_{row['id']}")
                    with rr2:
                        base_replica_row = st.number_input(
                            "Tu margen (USD)", min_value=0.01, value=10.0, step=1.0, format="%.2f",
                            key=f"sen_hist_replica_base_{row['id']}")

                    entradas_replica = _entradas_de_senal(row.to_dict())
                    factor_replica_row = _factor_replica(res_row, entradas_replica, base_replica_row,
                                                           ref_replica_row)
                    if factor_replica_row <= 0:
                        st.caption("Cargá un número mayor a 0 para calcular tu posición.")
                    else:
                        rrm1, rrm2, rrm3, rrm4 = st.columns(4)
                        rrm1.metric("Margen de apertura a poner",
                                    f"${res_row['margen_apertura'] * factor_replica_row:,.2f}")
                        rrm2.metric("Margen extra a poner",
                                    f"${res_row['margen_extra'] * factor_replica_row:,.2f}")
                        rrm3.metric("Margen total a poner",
                                    f"${res_row['margen_total'] * factor_replica_row:,.2f}")
                        rrm4.metric("Apalancamiento", fmt_apal(res_row["apalancamiento_apertura"]))

                        if res_row["liquidada_al_abrir"]:
                            st.error("🚨 Con este margen la posición nacería liquidada (los costos "
                                     "de apertura superan el margen total).")
                        elif res_row["sin_liquidacion"]:
                            st.caption("Con este apalancamiento y margen, el activo tendría que "
                                       "llegar a $0 para liquidarte.")
                        else:
                            rrl1, rrl2 = st.columns(2)
                            rrl1.metric("💀 Precio de liquidación",
                                        fmt_precio_exacto(res_row["precio_liquidacion"]))
                            rrl2.metric("Distancia a liquidación",
                                        f"{res_row['dist_liq_pct']:+.2f}%")

                        if _sl_mas_alla_de_liquidacion(res_row, es_largo_row,
                                                        float(row.get("stop_loss") or 0)):
                            st.warning("⚠️ Con este margen, el Stop Loss queda más allá del precio de "
                                       "liquidación: te liquidarían antes de que el SL se ejecute.")

                        detalle_replica_row = _filas_detalle_replica(row.to_dict(), entradas_replica,
                                                                       factor_replica_row)
                        if len(detalle_replica_row) > 1:
                            with st.expander("🔍 Ver el detalle por entrada"):
                                st.dataframe(pd.DataFrame(detalle_replica_row),
                                             use_container_width=True, hide_index=True)
                else:
                    st.caption(
                        f"Se arma una posición nueva al precio promedio de la señal "
                        f"({fmt_precio_exacto(res_row['precio_promedio'])}), con el apalancamiento "
                        f"sugerido para el perfil {PERFILES_RIESGO[modo_apal_sel]['label']} "
                        f"({fmt_apal(apal_valor_sel)}) en vez del apalancamiento de apertura de la "
                        "señal. No es una escala de las entradas originales: es tu margen a ese "
                        "apalancamiento."
                    )
                    base_replica_perfil = st.number_input(
                        "Tu margen (USD)", min_value=0.01, value=10.0, step=1.0, format="%.2f",
                        key=f"sen_hist_replica_perfil_base_{row['id']}")
                    entrada_sintetica = [{
                        "precio": res_row["precio_promedio"], "costo_apertura": 0.0,
                        "apalancamiento": apal_valor_sel, "margen": base_replica_perfil,
                        "margen_extra": 0.0,
                    }]
                    res_perfil = _resumen_posicion(entrada_sintetica, es_largo_row)
                    if res_perfil:
                        _render_resumen_posicion(res_perfil, es_largo_row,
                                                  stop_loss=float(row.get("stop_loss") or 0))

            if estado == "ABIERTA":
                st.divider()
                st.caption("🔧 Para agregar otra entrada a esta posición (promediar / alejar "
                           "liquidación) o cerrarla manualmente, andá a la pestaña "
                           "**📢 Publicar Señal** → 'Gestionar señales publicadas'.")


# ==============================================================
#  HELPERS COMPARTIDOS DEL SIMULADOR
# ==============================================================

def _calcular_fila_simulacion(s, precio_ref, capital_total, modo_calculo,
                               monto_por_senal=None, pct_por_senal=None, riesgo_pct=None,
                               unidades_por_lote=None, cantidad_lotes=None,
                               fecha_cierre=None, hora_cierre=None):
    """Arma la fila de la tabla del simulador para una señal, según el
    modo de cálculo elegido. Devuelve None si faltan datos para calcular.
    IMPORTANTE: 's' ya debe venir con precio_entrada = promedio real de
    la posición (ver _senal_con_precio_entrada)."""
    estado = s.get("estado", "ABIERTA")
    cat = s.get("categoria") or "🔹 Otro"
    ret_precio, ret_apalancado_signal = _calcular_retorno(s, precio_ref)
    extra_cols = {}

    if modo_calculo == "lotes":
        unidades = (unidades_por_lote or 1.0) * (cantidad_lotes or 0)
        pnl_usd, margen, ret_pct = _calcular_pnl_lotes(s, precio_ref, unidades)
        capital_asignado = margen
        liquidada = ret_pct <= -100
        if liquidada:
            pnl_usd = -capital_asignado
            ret_pct = -100.0
        capital_final = capital_asignado + pnl_usd
        extra_cols = {"Lotes": round(cantidad_lotes or 0, 2), "Unidades": round(unidades, 2)}
        ret_mostrar = ret_pct

    elif modo_calculo == "riesgo":
        if riesgo_pct is None:
            return None
        calc = _tamano_posicion_por_riesgo(s, capital_total, riesgo_pct)
        if calc is None:
            return None
        pnl_usd, margen, ret_pct = _calcular_pnl_lotes(s, precio_ref, calc["unidades"])
        capital_asignado = margen
        liquidada = ret_pct <= -100
        if liquidada:
            pnl_usd = -calc["riesgo_usd"]
            ret_pct = (pnl_usd / margen * 100) if margen else -100.0
        capital_final = capital_asignado + pnl_usd
        extra_cols = {"% Riesgo": round(riesgo_pct, 2)}
        ret_mostrar = ret_pct

    else:  # "monto_pct": monto fijo o % de capital por señal
        capital_asignado = monto_por_senal if monto_por_senal is not None else capital_total * (pct_por_senal / 100)
        liquidada = ret_apalancado_signal <= -100
        ret_mostrar = max(ret_apalancado_signal, -100)
        pnl_usd = capital_asignado * (ret_mostrar / 100)
        capital_final = capital_asignado + pnl_usd

    fila = {
        "Fecha": s.get("fecha"), "Ticker": s.get("ticker"), "Categoría": cat, "Tipo": s.get("tipo"),
        "Entrada usada (ponderada)": fmt_precio_local(s.get("precio_entrada")),
        "Estado": "💀 LIQUIDADA" if liquidada else estado,
        "Cierre": _texto_cierre(estado, fecha_cierre, hora_cierre),
        "Apalanc.": fmt_apal(_apalancamiento_apertura_de_senal(s)),
    }
    fila.update(extra_cols)
    fila.update({
        "Ret. Precio %": round(ret_precio, 2),
        "Ret. Apalancado %": round(ret_mostrar, 2),
        "Capital Asignado": round(capital_asignado, 2),
        "P&L (USD)": round(pnl_usd, 2),
        "Capital Final": round(capital_final, 2),
    })
    return fila


REPLICA_REF_PRIMERA = "Margen de la 1ª entrada (apertura + extra)"
REPLICA_REF_TOTAL = "Margen total de la posición"
MODO_REPLICA = "🔁 Replicar la posición del publicador (escalada a tu margen)"


def _factor_replica(res, entradas, base_usuario, referencia):
    """Factor de escala entre la posición del admin y la del usuario.
    El usuario pone un número (base_usuario) que se compara contra el
    margen (apertura + extra) de la 1ª entrada del admin, o contra su
    margen total de la posición."""
    if referencia == REPLICA_REF_PRIMERA:
        primera = entradas[0]
        ref = primera["margen"] + float(primera.get("margen_extra") or 0.0)
    else:
        ref = res["margen_total"]
    return (base_usuario / ref) if ref and ref > 0 else 0.0


def _liquidacion_tocada(senal, res):
    """¿La posición habría sido liquidada antes de cerrarse?
    Si el SL queda ANTES que la liquidación (caso normal), el SL salta
    primero y no hay liquidación. Solo hay liquidación posible si el SL
    está más allá del precio de liquidación (o la posición nace
    liquidada). En ese caso se mira el High/Low diario desde la fecha
    de la señal hasta su cierre (o hasta hoy si sigue abierta)."""
    if res is None or res["sin_liquidacion"]:
        return False
    if res["liquidada_al_abrir"]:
        return True
    es_largo = "LARGO" in str(senal.get("tipo", "")).upper()
    sl = float(senal.get("stop_loss") or 0)
    if not _sl_mas_alla_de_liquidacion(res, es_largo, sl):
        return False
    hist = _historial_desde_fecha(senal["ticker"], senal["fecha"])
    if hist is None or hist.empty:
        return False
    fecha_fin = senal.get("fecha_cierre")
    liq = res["precio_liquidacion"]
    for fecha_idx, fila in hist.iterrows():
        if fecha_fin and str(fecha_idx.date()) > str(fecha_fin):
            break
        hi = float(fila["High"]) if "High" in fila else float(fila["Close"])
        lo = float(fila["Low"]) if "Low" in fila else float(fila["Close"])
        if (es_largo and lo <= liq) or ((not es_largo) and hi >= liq):
            return True
    return False


def _calcular_fila_replica(s, res, precio_ref, factor, liquidada, fecha_cierre=None, hora_cierre=None):
    """Fila del simulador replicando la posición del admin a escala.
    unidades/margen/costos = los del admin × factor. El P&L es el de la
    posición completa (Σ unidades × movimiento de precio) menos los
    costos de apertura escalados; nunca pierde más que el margen. Si la
    posición se liquidó, se pierde todo el margen."""
    estado = s.get("estado", "ABIERTA")
    es_largo = "LARGO" in str(s.get("tipo", "")).upper()
    unidades = res["unidades"] * factor
    margen = res["margen_total"] * factor
    costos = res["costos_total"] * factor
    precio_prom = res["precio_promedio"]

    if liquidada:
        pnl_usd = -margen
    else:
        diff = (precio_ref - precio_prom) if es_largo else (precio_prom - precio_ref)
        pnl_usd = max(diff * unidades - costos, -margen)
    capital_final = margen + pnl_usd
    ret_precio, _ = _calcular_retorno(s, precio_ref)
    ret_sobre_margen = (pnl_usd / margen * 100) if margen else 0.0

    return {
        "Fecha": s.get("fecha"), "Ticker": s.get("ticker"),
        "Categoría": s.get("categoria") or "🔹 Otro", "Tipo": s.get("tipo"),
        "Entrada usada (ponderada)": fmt_precio_local(precio_prom),
        "Estado": "💀 LIQUIDADA" if liquidada else estado,
        "Cierre": _texto_cierre(estado, fecha_cierre, hora_cierre),
        "Apalanc.": fmt_apal(res["apalancamiento_apertura"]),
        "Escala": f"x{factor:.4g}",
        "Costos apertura": round(costos, 2),
        "Ret. Precio %": round(ret_precio, 2),
        "Ret. Apalancado %": round(ret_sobre_margen, 2),
        "Capital Asignado": round(margen, 2),
        "P&L (USD)": round(pnl_usd, 2),
        "Capital Final": round(capital_final, 2),
    }


def _filas_detalle_replica(s, entradas, factor):
    """Detalle entrada por entrada de cómo queda replicada la posición.
    El margen de apertura y el margen extra se escalan por separado
    (el extra sigue sin sumar tamaño/unidades)."""
    filas = []
    for i, e in enumerate(entradas):
        margen = e["margen"] * factor
        margen_extra = float(e.get("margen_extra") or 0.0) * factor
        nominal = margen * e["apalancamiento"]
        filas.append({
            "Fecha": s.get("fecha"), "Ticker": s.get("ticker"), "Entrada": i + 1,
            "Precio": fmt_precio_exacto(e["precio"]),
            "Apalanc.": fmt_apal(e["apalancamiento"]),
            "Tu margen apertura (USD)": round(margen, 2),
            "Tu margen extra (USD)": round(margen_extra, 2),
            "Tu costo de apertura (USD)": round(e["costo_apertura"] * factor, 4),
            "Tamaño nominal (USD)": round(nominal, 2),
            "Unidades": round(nominal / e["precio"], 6),
        })
    return filas


MODOS_CON_MARGEN = ("📦 Por lotes (tamaño de posición)",
                    "🎯 % de riesgo por operación (según Stop Loss)",
                    MODO_REPLICA)


def _mostrar_metricas_sim(df_sim, label_capital):
    capital_asignado_total = df_sim["Capital Asignado"].sum()
    pnl_total = df_sim["P&L (USD)"].sum()
    n_ganadoras = int((df_sim["P&L (USD)"] > 0).sum())
    n_total_sim = len(df_sim)
    winrate_sim = (n_ganadoras / n_total_sim * 100) if n_total_sim else 0

    k1, k2, k3, k4 = st.columns(4)
    with k1: st.metric(label_capital, f"USD {capital_asignado_total:,.2f}")
    with k2: st.metric("P&L total", f"USD {pnl_total:+,.2f}",
                        delta=f"{(pnl_total/capital_asignado_total*100):+.1f}%" if capital_asignado_total else None)
    with k3: st.metric("Operaciones ganadoras", f"{n_ganadoras}/{n_total_sim}")
    with k4: st.metric("Win Rate simulado", f"{winrate_sim:.1f}%")
    return capital_asignado_total, pnl_total


def _mostrar_tabla_estilizada(df_sim):
    def _color_pnl(val):
        try:
            v = float(val)
            return "color:#3fb950;font-weight:700" if v >= 0 else "color:#f85149;font-weight:700"
        except Exception:
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
    if "% Riesgo" in df_sim.columns:
        format_dict["% Riesgo"] = "{:.2f}%"
    if "Costos apertura" in df_sim.columns:
        format_dict["Costos apertura"] = "${:,.2f}"

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


def _mostrar_mejor_peor(df_sim):
    """Tarjetas de mejor y peor operación. El color y el signo dependen
    del resultado REAL de cada una (verde/"+" si ganó plata, rojo/sin
    signo si perdió) — antes "peor" se pintaba siempre de rojo aunque
    esa operación hubiera sido ganadora (pasa cuando TODAS las
    operaciones simuladas ganan y aun así hay que elegir una como "la
    peor" del conjunto). También se muestra cuándo se cerró la señal."""
    if df_sim.empty:
        return
    mejor = df_sim.loc[df_sim["P&L (USD)"].idxmax()]
    peor = df_sim.loc[df_sim["P&L (USD)"].idxmin()]

    def _tarjeta_html(row, titulo, emoji):
        val = float(row["P&L (USD)"])
        positivo = val >= 0
        color = "#3fb950" if positivo else "#f85149"
        signo = "+" if positivo else ""
        cierre = row.get("Cierre")
        if cierre and cierre not in ("Sigue abierta", "—"):
            sub_cierre = f" · cierre {cierre}"
        elif cierre == "Sigue abierta":
            sub_cierre = " · sigue abierta"
        else:
            sub_cierre = ""
        return f"""
        <div style="background:#0d1117;border:1px solid #21262d;border-left:3px solid {color};
             border-radius:8px;padding:12px 16px">
          <div style="font-size:11px;color:{color};font-weight:700">{emoji} {titulo}</div>
          <div style="font-size:13px;color:#e6edf3;margin-top:4px">{row['Ticker']} · {row['Fecha']}{sub_cierre}</div>
          <div style="font-size:16px;font-weight:800;color:{color}">{signo}${val:,.2f}</div>
        </div>
        """

    cM, cP = st.columns(2)
    with cM:
        st.markdown(_tarjeta_html(mejor, "MEJOR OPERACIÓN", "🏆"), unsafe_allow_html=True)
    with cP:
        st.markdown(_tarjeta_html(peor, "PEOR OPERACIÓN", "📉"), unsafe_allow_html=True)


# ==============================================================
#  RENDER — TAB SIMULADOR (todos)
#  CAMBIO: se sacó el selector "Modo de asignación". Ahora el
#  Simulador solo trabaja de una forma: le ponés un MONTO FIJO POR
#  SEÑAL y te muestra 3 tablas (🟢 Conservador / 🟡 Moderado /
#  🔴 Agresivo), una por cada perfil de riesgo. Las 3 tablas parten
#  del MISMO monto fijo; lo que cambia entre ellas es el % de riesgo
#  de cada perfil (definido por el admin al publicar cada señal), que
#  determina el tamaño de posición sugerido — y por lo tanto cuánto
#  margen terminás usando realmente en cada una. El apalancamiento que
#  se usa en el cálculo es siempre el REAL de la señal (el que cargó
#  el admin al publicarla), igual en las 3 tablas.
#  Las órdenes PENDIENTES (todavía no activadas) se excluyen del
#  simulador: no hay una posición real para simular hasta que se
#  active.
#  El modo "Replicar la posición del publicador" y el resto de los
#  modos anteriores (% del capital, por lotes) se sacaron de acá: la
#  réplica exacta de una señal puntual ahora vive directamente en su
#  ficha, dentro de "Señales y Resultados".
# ==============================================================

def _tab_simulador(supabase):
    st.caption(
        "Simulá cuánto hubieras ganado o perdido con un monto fijo por señal, comparando los "
        "3 perfiles de riesgo. Cada perfil arriesga un % distinto de ese monto si el precio "
        "llega al Stop Loss — eso define el tamaño de posición sugerido de cada uno — pero "
        "los 3 usan siempre el apalancamiento real con el que se publicó la señal."
    )
    st.caption(
        "🧩 Para señales con varias entradas, acá se usa el precio promedio real de la posición "
        "(ponderado por el tamaño de cada entrada). El apalancamiento y el precio de "
        "liquidación exactos de cada señal están en 'Señales y Resultados'. Las órdenes "
        "pendientes (todavía no activadas) no se incluyen acá."
    )

    senales = _obtener_senales(supabase, 200)
    if not senales:
        st.info("Todavía no hay señales para simular.")
        return

    with st.spinner("Evaluando señales..."):
        _sincronizar_estados(supabase, senales)
        senales = _obtener_senales(supabase, 200)

    c1, c2 = st.columns(2)
    with c1:
        monto_fijo = st.number_input("💵 Monto fijo por señal (USD)", min_value=10.0,
                                      value=100.0, step=10.0, key="sim_monto_fijo")
    with c2:
        incluir_abiertas = st.checkbox("Incluir señales abiertas (P&L flotante)", value=True,
                                        key="sim_incluir_abiertas")

    df_base = pd.DataFrame(senales)
    if "categoria" not in df_base.columns:
        df_base["categoria"] = "🔹 Otro"
    df_base["categoria"] = df_base["categoria"].fillna("🔹 Otro")
    df_base = df_base[df_base["estado"] != "PENDIENTE"]
    if not incluir_abiertas:
        df_base = df_base[df_base["estado"] != "ABIERTA"]

    if df_base.empty:
        st.info("No hay señales para incluir en la simulación con estos filtros.")
        return

    st.divider()
    tabs_perfiles = st.tabs([info["label"] for info in PERFILES_RIESGO.values()])
    resumen_comparativo = []

    for (perfil_key, info), tab in zip(PERFILES_RIESGO.items(), tabs_perfiles):
        with tab:
            st.caption(info["desc"])
            filas = []
            for _, row in df_base.iterrows():
                s = row.to_dict()
                s = _senal_con_precio_entrada(s, _precio_promedio_ponderado(s))
                precio_ref = s.get("precio_cierre")
                if precio_ref is None:
                    ev = _evaluar_senal(s)
                    precio_ref = ev["precio_ref"]
                if precio_ref is None:
                    continue
                pct_signal = float(s.get(f"riesgo_{perfil_key}") or info["default_pct"])
                fila = _calcular_fila_simulacion(s, precio_ref, monto_fijo, "riesgo",
                                                  riesgo_pct=pct_signal,
                                                  fecha_cierre=s.get("fecha_cierre"),
                                                  hora_cierre=s.get("hora_cierre"))
                if fila:
                    filas.append(fila)

            if not filas:
                st.info("No se pudo simular ninguna señal con este perfil (faltan datos de "
                        "SL/entrada).")
                continue

            df_perfil = pd.DataFrame(filas)
            capital_usado, pnl_total = _mostrar_metricas_sim(df_perfil, "Margen total usado")
            resumen_comparativo.append((info["label"], pnl_total, capital_usado))
            _mostrar_tabla_estilizada(df_perfil)
            _mostrar_mejor_peor(df_perfil)

    if resumen_comparativo:
        st.divider()
        st.markdown("##### 📊 Resumen comparativo")
        df_resumen = pd.DataFrame(
            resumen_comparativo, columns=["Perfil", "P&L Total (USD)", "Margen Usado (USD)"])
        df_resumen["Rendimiento %"] = df_resumen.apply(
            lambda r: round(r["P&L Total (USD)"] / r["Margen Usado (USD)"] * 100, 2)
            if r["Margen Usado (USD)"] else 0.0, axis=1)
        st.dataframe(df_resumen, use_container_width=True, hide_index=True)

    st.caption("⚠️ Simulación educativa. No contempla comisiones, spread, financiamiento por "
               "apalancamiento, swap ni slippage. Cuando TP y SL se tocan en la misma vela se "
               "asume el peor caso (SL). El % de riesgo de cada perfil y el apalancamiento usado "
               "dependen de cómo se cargó cada señal: verificá las especificaciones de tu "
               "bróker antes de usarlos como referencia real. No constituye asesoramiento "
               "financiero.")


# ==============================================================
#  ENTRY POINT — llamar desde app.py
# ==============================================================

def render_senales_trading(supabase, user_id, user_email):
    """Uso desde app.py:
        from modulo_senales_trading import render_senales_trading
        render_senales_trading(supabase, USER_ID, st.session_state['usuario'].email)

    NOTA DE MIGRACIÓN: si tu tabla en Supabase todavía no tiene estas
    columnas, corré en el SQL editor:
        ALTER TABLE senales_trading
        ADD COLUMN IF NOT EXISTS categoria text DEFAULT '🔹 Otro',
        ADD COLUMN IF NOT EXISTS riesgo_conservador float DEFAULT 1.0,
        ADD COLUMN IF NOT EXISTS riesgo_moderado    float DEFAULT 2.0,
        ADD COLUMN IF NOT EXISTS riesgo_agresivo    float DEFAULT 3.0,
        ADD COLUMN IF NOT EXISTS apal_conservador   float,
        ADD COLUMN IF NOT EXISTS apal_moderado      float,
        ADD COLUMN IF NOT EXISTS apal_agresivo      float,
        ADD COLUMN IF NOT EXISTS entradas jsonb DEFAULT '[]'::jsonb,
        ADD COLUMN IF NOT EXISTS hora_cierre text,
        ADD COLUMN IF NOT EXISTS fecha_activacion date,
        ADD COLUMN IF NOT EXISTS hora_activacion text;
    (Los campos nuevos de cada entrada —costo_apertura, apalancamiento,
    margen, margen_extra, activada, fecha_activacion, hora_activacion—
    viven dentro del jsonb "entradas": no hace falta migrar nada más
    para esos. "fecha_activacion"/"hora_activacion" A NIVEL SEÑAL son
    nuevos en esta versión: guardan cuándo terminó de activarse una
    orden pendiente, para que la evaluación de TP/SL arranque desde
    ahí. "hora_cierre" guarda el momento del cierre; sin ella, las
    señales cerradas antes de correr esta migración van a mostrar el
    cierre solo con fecha, sin hora, y eso es normal.
    "apal_conservador/moderado/agresivo" son nuevos: sin ellos, las
    señales viejas solo ofrecen "Apertura" como apalancamiento al
    replicar la posición en "Señales y Resultados". IMPORTANTE: si tu
    columna "estado" tiene un CHECK constraint con los valores
    permitidos (ej. solo 'ABIERTA'/'ACIERTO (TP)'/etc.), agregale
    'PENDIENTE' a la lista para poder usar las órdenes pendientes.)
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
        Señales publicadas con fecha, hora, una o varias entradas (precio, costo de apertura,
        apalancamiento, margen de apertura y margen extra), precio de liquidación, stop loss,
        take profit, categoría y perfiles de riesgo (🟢 Conservador / 🟡 Moderado / 🔴 Agresivo)
        — o cargadas como órdenes pendientes (🕓) que se activan solas cuando el precio toca la
        entrada. Evaluación automática de aciertos/desaciertos (contada desde la publicación o
        desde la activación, según corresponda), P&L en vivo (actualizado cada 5 min) para las
        abiertas, réplica de la posición con distintos apalancamientos sugeridos, y simulador de
        capital (por monto, %, riesgo, lotes o comparando los 3 perfiles) para cualquier usuario.
      </div>
    </div>
    """, unsafe_allow_html=True)

    tab_pub, tab_hist, tab_sim = st.tabs([
        "📢 Publicar Señal", "📋 Señales y Resultados", "🧮 Simulador de Capital",
    ])
    with tab_pub:
        _tab_publicar(supabase, user_id, user_email, es_admin)
    with tab_hist:
        _tab_senales(supabase, es_admin)
    with tab_sim:
        _tab_simulador(supabase)
