# modulo_ia_asistente.py
# ==============================================================
#  ASISTENTE IA — v2
#  Cubre: análisis de ticker, comparador, oportunidades (sectores/
#  países/mercados/subsectores), simulador, glosario, finanzas
#  personales (lectura + REGISTRO de movimientos con confirmación),
#  Top-Down Cuantitativo, F-Score, Salud del Mercado, Renta Fija/
#  Macro, Opciones, Rotación/Pares, Optimizador de Cartera.
#
#  Todo lo que el asistente puede "computar" directamente depende
#  de qué funciones le pasás en `ctx` (ver diccionario CTX_IA en el
#  script principal). Si una función no está en ctx, el asistente
#  degrada con gracia: explica el módulo y te dice dónde encontrarlo
#  en la app en vez de fallar.
# ==============================================================

import re
import random
import difflib
from datetime import datetime, date
import streamlit as st

# ==============================================================
#  INTENCIONES
# ==============================================================

_PATRONES_INTENCION = [
    ('registrar_movimiento', [
        r'\banot[aá]', r'\bregistr[aá]', r'\bcarg[aá]\s+(un\s+)?(gasto|ingreso|movimiento|deuda)',
        r'\bagreg[aá]\s+(un\s+)?(gasto|ingreso|movimiento|deuda)', r'\bsum[aá]\s+(esto|este\s+gasto|este\s+ingreso)',
        r'\bmet[eé]lo\b', r'\bpon[eé]lo\s+en\s+mis?\s+finanzas\b',
    ]),
    ('finanzas', [
        r'\bmis?\s+finanzas\b', r'\bfinanzas\b', r'\bmis?\s+gastos?\b', r'\bgastos?\b',
        r'\bmi\s+presupuesto\b', r'\bpresupuesto\b', r'\bcu[aá]nto\s+gast',
        r'\bmis?\s+deudas?\b', r'\bdeudas?\b', r'\bmi\s+ahorro\b', r'\bahorros?\b',
        r'\bmis?\s+ingresos?\b', r'\bingresos?\b', r'\bmi\s+situaci[oó]n\s+financiera\b',
        r'\bmi\s+balance\b', r'\balertas?\s+financieras?\b',
    ]),
    ('comparar', [r'\bcompar', r'\bvs\.?\b', r'\bcu[aá]l\s+es\s+mejor\b', r'\bo\s+\w+\?']),
    ('tdc', [
        r'\btop[\s\-]?down\b', r'\bmediano\s+plazo\b', r'\blargo\s+plazo\b.*\bscore\b',
        r'\bcuantitativo\b',
    ]),
    ('fscore', [r'\bf[\s\-]?score\b', r'\bpiotroski\b', r'\bcalidad\s+financiera\b']),
    ('breadth', [r'\bsalud\s+del\s+mercado\b', r'\bbreadth\b', r'\bamplitud\s+de\s+mercado\b',
                 r'\bavance\s*/?\s*declive\b']),
    ('macro', [r'\brenta\s+fija\b', r'\btasas?\s+del\s+tesoro\b', r'\bmacro\b', r'\bbonos?\b',
               r'\bcr[eé]dito\s+corporativo\b']),
    ('opciones', [r'\bopciones\b', r'\bblack[\s\-]?scholes\b', r'\bgriegas?\b', r'\bcall\b', r'\bput\b',
                  r'\bpayoff\b', r'\bstrike\b']),
    ('pares', [r'\brotaci[oó]n\b', r'\bpares?\b(?!.*\bde\s+un)', r'\bmean\s+reversion\b', r'\bz[\s\-]?score\s+de\s+ratio\b',
               r'\bcointegraci[oó]n\b']),
    ('optimizador', [r'\boptimiz', r'\bmonte\s+carlo\b', r'\bfrontera\s+eficiente\b', r'\brebalance',
                      r'\bmi\s+cartera\b']),
    ('oportunidades', [r'\boportunidad', r'\brecomend', r'\bqu[eé]\s+me\s+recomend', r'\bideas?\s+de\s+inversi[oó]n\b',
                        r'\bd[oó]nde\s+invert', r'\bqu[eé]\s+comprar',
                        r'\bbarat', r'\b(m[aá]s|menos)\s+car[oa]s?\b', r'\bsectores?\s+(est[aá]n|con)\b',
                        r'\bpa[ií]ses?\s+(est[aá]n|con)\b', r'\bqu[eé]\s+sector', r'\bqu[eé]\s+pa[ií]s']),
    ('simular', [r'\bsi\s+invi[eé]rto\b', r'\bcu[aá]nto\s+tendr[ií]a\b', r'\bhubiera\s+invertido\b',
                 r'\bsimul']),
    ('glosario', [r'\bqu[eé]\s+significa\b', r'\bqu[eé]\s+es\s+(el|la|un|una)\b', r'\bexplic[aá]']),
    ('sistema', [r'\bqu[eé]\s+m[oó]dulos\b', r'\btodo\s+lo\s+que\s+(pod[eé]s|puede)\s+hacer\s+la\s+app\b',
                 r'\bfunciones?\s+de\s+la\s+app\b']),
    ('ayuda', [r'\bhola\b', r'\bqu[eé]\s+pod[eé]s\s+hacer\b', r'\bayuda\b', r'\bmenu\b', r'^\s*$']),
]

def detectar_intencion(texto):
    t = texto.lower()
    # 'registrar_movimiento' solo dispara con verbos de acción explícitos
    # (anotá/registrá/cargá/agregá/sumá/metelo/ponelo), así que no hace falta
    # una segunda pasada para distinguirlo de una pregunta: si el usuario
    # escribió "anotá que gasté...", la palabra "que" no debe confundirse
    # con una consulta tipo "¿en qué gasté más?".
    for intencion, patrones in _PATRONES_INTENCION:
        if any(re.search(p, t) for p in patrones):
            return intencion
    return 'analizar_ticker'


# ==============================================================
#  EXTRACCIÓN DE ENTIDADES
# ==============================================================

_STOPWORDS_TICKER = {
    'EL','LA','LOS','LAS','UN','UNA','UNOS','UNAS','DE','DEL','AL','EN','Y','O','U',
    'ES','SE','SU','SUS','TU','TUS','MI','MIS','LO','LE','LES','NO','SI','SOY','ERES',
    'CON','SIN','POR','PARA','QUE','COMO','CUAL','QUIEN','CUANTO','CUANDO','DONDE',
    'ESTA','ESTE','ESTO','ESA','ESE','ESO','HAY','MAS','MUY','TAN','SOBRE','ENTRE',
    'HOY','AYER','AHORA','BIEN','MAL','TODO','TODA','TODOS','TODAS','OK','ASI','SOLO',
    'ME','TE','NOS','OS','YA','VA','VE','DA','DI','EH','AH','OH','IR','VER','SER','A',
}

_ALIAS_ACTIVOS = {
    'nvidia': 'NVDA', 'nvidea': 'NVDA',
    'apple': 'AAPL',
    'tesla': 'TSLA',
    'google': 'GOOGL', 'alphabet': 'GOOGL',
    'amazon': 'AMZN',
    'microsoft': 'MSFT',
    'facebook': 'META',
    'netflix': 'NFLX',
    'bitcoin': 'BTC-USD',
    'ethereum': 'ETH-USD',
    'oro': 'GC=F',
    'plata': 'SI=F',
    'petroleo': 'CL=F', 'petróleo': 'CL=F',
    'mercadolibre': 'MELI',
    'cocacola': 'KO',
    'galicia': 'GGAL',
    'ypf': 'YPF',
}


def _detectar_alias(texto):
    t = texto.lower()
    encontrados = []
    for alias, tk in _ALIAS_ACTIVOS.items():
        if alias in t:
            encontrados.append(tk)
    palabras = re.findall(r'\b[a-záéíóúñ]{4,}\b', t)
    claves = list(_ALIAS_ACTIVOS.keys())
    for palabra in palabras:
        match = difflib.get_close_matches(palabra, claves, n=1, cutoff=0.8)
        if match:
            encontrados.append(_ALIAS_ACTIVOS[match[0]])
    return encontrados


def _detectar_industria(texto, industrias_validas):
    t = texto.lower()
    for ind in sorted(industrias_validas, key=len, reverse=True):
        if ind.lower() in t:
            return ind
    return None


def extraer_tickers(texto, universo_valido, ctx_validar):
    encontrados = []
    encontrados.extend(_detectar_alias(texto))
    candidatos = re.findall(r'\b[A-Za-z]{1,6}(?:[.\-=\^][A-Za-z0-9]{1,4})?\b', texto)
    for c in candidatos:
        c_norm = c.upper()
        if c_norm in _STOPWORDS_TICKER:
            continue
        if c_norm in universo_valido:
            if len(c_norm) <= 3 and not c.isupper():
                continue
            encontrados.append(c_norm)
            continue
        if c.isupper() and len(c) >= 2:
            val = ctx_validar(c)
            if val:
                encontrados.append(val)
    return list(dict.fromkeys(encontrados))


def extraer_monto(texto):
    m = re.search(r'(\d[\d\.,]*)\s*(?:usd|dolares|dólares|d[oó]lares|pesos|\$)?', texto.lower())
    if not m:
        return None
    val = m.group(1)
    # Heurística simple: si hay coma y punto, el último separador es el decimal.
    if ',' in val and '.' in val:
        if val.rfind(',') > val.rfind('.'):
            val = val.replace('.', '').replace(',', '.')
        else:
            val = val.replace(',', '')
    elif ',' in val:
        # asumimos que la coma es decimal solo si tiene <=2 dígitos después
        partes = val.split(',')
        if len(partes[-1]) <= 2:
            val = val.replace(',', '.')
        else:
            val = val.replace(',', '')
    try:
        return float(val)
    except ValueError:
        return None


def extraer_periodo(texto):
    t = texto.lower()
    if 'mes' in t: return '1mo'
    if '3 mes' in t or 'trimestre' in t: return '3mo'
    if '6 mes' in t or 'semestre' in t: return '6mo'
    if '2 a' in t or 'dos a' in t: return '2y'
    if '5 a' in t or 'cinco a' in t: return '5y'
    if re.search(r'\ba[ñn]o\b', t): return '1y'
    return '1y'


_CATEGORIAS_KEYWORDS = {
    'Alimentación': [r'comida', r'super(mercado)?', r'almuerzo', r'cena', r'restaur', r'delivery', r'kiosco'],
    'Transporte':   [r'nafta', r'combustible', r'uber', r'taxi', r'colectivo', r'transporte', r'subte', r'peaje'],
    'Vivienda':     [r'alquiler', r'expensas', r'hipoteca', r'inmobiliaria'],
    'Servicios':    [r'luz', r'gas\b', r'internet', r'celular', r'telefono', r'teléfono', r'agua\b', r'streaming', r'netflix', r'spotify'],
    'Salud':        [r'medico', r'médico', r'farmacia', r'obra\s+social', r'prepaga', r'dentista'],
    'Entretenimiento': [r'cine', r'salida', r'bar\b', r'boliche', r'juego'],
    'Educación':    [r'curso', r'colegio', r'universidad', r'facultad', r'libro'],
    'Ropa':         [r'ropa', r'zapatillas', r'indumentaria'],
    'Ahorro/Inversión': [r'ahorro', r'invert', r'plazo\s+fijo', r'compr[eé]\s+d[oó]lares'],
    'Sueldo':       [r'sueldo', r'salario', r'nómina', r'nomina'],
    'Freelance':    [r'freelance', r'changa', r'laburo\s+extra', r'proyecto'],
}


def extraer_categoria(texto):
    t = texto.lower()
    for cat, patrones in _CATEGORIAS_KEYWORDS.items():
        if any(re.search(p, t) for p in patrones):
            return cat
    return 'Otros'


def detectar_tipo_movimiento(texto):
    t = texto.lower()
    if re.search(r'\bdeuda\b|\bpr[eé]stamo\b|\bdebo\b|\bcuota\b', t):
        return 'deuda'
    if re.search(r'\bcobr[eé]\b|\bingres[eé]\b|\bme\s+pagaron\b|\bsueldo\b|\bsalario\b|\bfacturaci[oó]n\b', t):
        return 'ingreso'
    if re.search(r'\bgast[eé]\b|\bpagu[eé]\b|\bcompr[eé]\b|\bsale?\b', t):
        return 'gasto'
    return None


def extraer_fecha(texto):
    t = texto.lower()
    if 'ayer' in t:
        from datetime import timedelta
        return (date.today() - timedelta(days=1)).isoformat()
    return date.today().isoformat()


# ==============================================================
#  ADAPTADOR DE ESCRITURA — Finanzas Personales
#  ⚠️ AJUSTAR: el nombre/firma exacto de la función depende de tu
#  finanzas_data.py. Se prueban varios nombres/firmas comunes; si
#  ninguno coincide, decilo y actualizamos esta función una sola vez.
# ==============================================================

def _registrar_movimiento_fd(ctx, tipo, monto, categoria, descripcion, fecha):
    fd = ctx.get('fd')
    supabase = ctx.get('supabase')
    user_id = ctx.get('user_id')
    if fd is None or supabase is None or user_id is None:
        return False, "No tengo conexión con el módulo de Finanzas Personales desde acá."

    intentos = [
        ('agregar_movimiento', (supabase, user_id, tipo, monto, categoria, descripcion, fecha)),
        ('registrar_movimiento', (supabase, user_id, tipo, monto, categoria, descripcion, fecha)),
        ('agregar_transaccion', (supabase, user_id, tipo, monto, categoria, descripcion, fecha)),
        ('crear_movimiento', (supabase, user_id, tipo, monto, categoria, descripcion, fecha)),
        ('insertar_movimiento', (supabase, user_id, tipo, monto, categoria, descripcion, fecha)),
        ('agregar_movimiento', (supabase, user_id, {
            'tipo': tipo, 'monto': monto, 'categoria': categoria,
            'descripcion': descripcion, 'fecha': fecha,
        })),
    ]
    ultimo_error = None
    for nombre_fn, args in intentos:
        fn = getattr(fd, nombre_fn, None)
        if fn is None:
            continue
        try:
            fn(*args)
            return True, None
        except Exception as e:
            ultimo_error = str(e)
            continue

    return False, (
        "No encontré una función compatible en finanzas_data.py para guardar el movimiento "
        f"(probé agregar_movimiento / registrar_movimiento / agregar_transaccion / crear_movimiento / "
        f"insertar_movimiento). Último error: {ultimo_error or 'ninguna función existe con esos nombres'}. "
        "Decime el nombre exacto de la función que usa el módulo de Finanzas y lo ajusto."
    )


# ==============================================================
#  RESPUESTAS
# ==============================================================

_APERTURAS_TICKER = [
    "Mirando {tk} ahora mismo:",
    "Che, esto es lo que muestra {tk}:",
    "Te tiro el panorama de {tk}:",
    "Esto encontré sobre {tk}:",
]


def responder(texto_usuario, ctx):
    # ── 1) ¿Hay una confirmación pendiente de un movimiento a registrar? ──
    pendiente = st.session_state.get('ia_pendiente_mov')
    if pendiente:
        t = texto_usuario.lower().strip()
        if re.search(r'\b(s[ií]|confirmo|dale|ok|correcto|s[ií]\s+dale)\b', t):
            ok, err = _registrar_movimiento_fd(
                ctx, pendiente['tipo'], pendiente['monto'], pendiente['categoria'],
                pendiente['descripcion'], pendiente['fecha'],
            )
            st.session_state['ia_pendiente_mov'] = None
            if ok:
                signo = {'gasto': '🔴', 'ingreso': '🟢', 'deuda': '🟠'}.get(pendiente['tipo'], '⚪')
                return (f"{signo} Listo, registré **{pendiente['tipo']}** de **${pendiente['monto']:,.2f}** "
                        f"en **{pendiente['categoria']}** ({pendiente['fecha']}). "
                        f"Lo vas a ver reflejado en Finanzas Personales.")
            return f"⚠️ No pude guardarlo. {err}"
        if re.search(r'\b(no|cancel[aá]|cancelar)\b', t):
            st.session_state['ia_pendiente_mov'] = None
            return "Listo, no registré nada."
        # Si el mensaje no es ni sí ni no, cancelamos el pendiente y seguimos
        # procesando el nuevo mensaje normalmente (para no bloquear la charla).
        st.session_state['ia_pendiente_mov'] = None

    intencion = detectar_intencion(texto_usuario)
    tickers = extraer_tickers(texto_usuario, ctx['UNIVERSO_TICKERS_VALIDOS'], ctx['validar_ticker'])

    industrias_validas = set(ctx.get('TICKER_INDUSTRY', {}).values())
    industria_detectada = _detectar_industria(texto_usuario, industrias_validas) if not tickers else None

    if (not tickers and not industria_detectada and st.session_state.get('ia_ultimo_ticker')
            and intencion in ('analizar_ticker', 'simular', 'tdc', 'fscore')):
        tickers = [st.session_state['ia_ultimo_ticker']]
    if tickers:
        st.session_state['ia_ultimo_ticker'] = tickers[0]

    if intencion == 'ayuda' and not tickers and not industria_detectada:
        return _respuesta_ayuda()

    if intencion == 'sistema':
        return _respuesta_sistema()

    if intencion == 'registrar_movimiento':
        return _iniciar_registro_movimiento(texto_usuario, ctx)

    if intencion == 'finanzas':
        return _responder_finanzas(ctx)

    if intencion == 'glosario':
        return _responder_glosario(texto_usuario, ctx)

    if intencion == 'comparar':
        if len(tickers) < 2:
            return "Decime al menos dos activos para comparar (ej: *'compará NVDA vs AMD'*)."
        return _responder_comparar(tickers, ctx)

    if intencion == 'tdc':
        if not tickers:
            return "¿Para qué ticker querés el Score Top-Down Cuantitativo (Mediano/Largo Plazo)?"
        return _responder_tdc(tickers[0], ctx)

    if intencion == 'fscore':
        if not tickers:
            return "¿Para qué ticker calculo el F-Score (Piotroski)?"
        return _responder_fscore(tickers[0], ctx)

    if intencion == 'breadth':
        return _responder_breadth(ctx)

    if intencion == 'macro':
        return _responder_macro(ctx)

    if intencion == 'opciones':
        return _responder_opciones(tickers[0] if tickers else None, ctx)

    if intencion == 'pares':
        return _responder_pares(ctx)

    if intencion == 'optimizador':
        return _responder_optimizador(tickers, ctx)

    if industria_detectada and not tickers:
        return _responder_industria(industria_detectada, ctx)

    if intencion == 'oportunidades':
        return _responder_oportunidades(texto_usuario, ctx)

    if intencion == 'simular':
        if not tickers:
            return "¿Sobre qué activo querés simular la inversión? Decime el ticker."
        monto = extraer_monto(texto_usuario) or 1000
        periodo = extraer_periodo(texto_usuario)
        return _responder_simular(tickers[0], monto, periodo, ctx)

    if not tickers:
        return ("No detecté ningún ticker en tu mensaje. Probá algo como *'analizame NVDA'*, "
                "*'compará YPF y GGAL'*, *'semiconductores'*, *'F-Score de KO'*, "
                "*'anotá que gasté 5000 en comida'*, o *'qué significa el Sharpe'*. "
                "Escribí *ayuda* para ver todo lo que puedo hacer.")
    return _responder_analizar(tickers[0], ctx)


def _respuesta_ayuda():
    return """¡Hola! 👋 Soy el asistente de Capital+. Puedo ayudarte con:

- **📊 Análisis de un activo** — *"analizame NVDA"*, *"cómo está el Bitcoin"*
- **⚖️ Comparaciones** — *"comparar YPF vs GGAL"*
- **🎯 Oportunidades** — *"qué sectores están baratos"*, *"dame ideas en tecnología"*
- **📐 Top-Down Cuantitativo** — *"score de mediano plazo de AAPL"*
- **🧮 F-Score (Piotroski)** — *"F-Score de KO"*
- **📡 Salud del mercado** — *"cómo está la amplitud del mercado"*
- **📉 Renta Fija / Macro** — *"cómo están las tasas del Tesoro"*
- **🎲 Opciones** — *"explicame griegas"*, *"opciones de TSLA"*
- **🔄 Rotación y Pares** — *"scanner de pares"*
- **🧮 Optimizador de cartera** — *"optimizame una cartera con NVDA, AAPL y KO"*
- **💰 Tus finanzas** — *"cómo está mi presupuesto"*, *"cuánto debo"*
- **✍️ Registrar movimientos** — *"anotá que gasté 5000 en comida"*, *"registrá un ingreso de 200000 por sueldo"*
- **📐 Simulaciones** — *"si invierto 1000 en AAPL en el último año"*
- **📖 Glosario** — *"qué significa el Sharpe"*

Escribí *"qué módulos tiene la app"* para el mapa completo. ⚠️ Todo esto sale de datos reales de la app — no es asesoramiento financiero, son datos para que decidas vos."""


def _respuesta_sistema():
    return """Capital+ tiene estos módulos (todos accesibles desde la barra superior):

**Corto plazo** — Forex · Países · Sectores · Sub-sectores · Mercados (commodities/cripto) · Acciones por industria
**Largo plazo** — Ranking cuantitativo · Reversión a la media · Por industria · Ticker individual · Fundamental · Top-Down Cuantitativo (MP/LP) · COT · TFF
**Herramientas** — 🔍 Buscador universal · ⚖️ Comparador · 🧮 Optimizador de cartera · 📐 Promediador + Stop Loss · 📊 F-Score (Piotroski) · 📡 Salud del Mercado · 📉 Renta Fija y Macro · 🤖 este asistente
**Trading** — 🔄 Rotación y Pares (mean reversion) · 🎯 Señales de Trading · 🎲 Valuación de Opciones
**Cuenta** — 💰 Finanzas Personales · 📆 Calendario Económico · 📰 Noticias

Preguntame por cualquiera de estos y te doy lo que pueda calcular directo acá, o te digo en qué sección de la app conviene abrirlo (por ejemplo, el Optimizador y el Scanner de Pares tienen muchos parámetros y conviene usarlos en su pantalla dedicada)."""


# ── Registro de movimientos en Finanzas ──────────────────────────

def _iniciar_registro_movimiento(texto, ctx):
    monto = extraer_monto(texto)
    if not monto:
        return "¿Cuánto fue el monto? Decime algo como *'anotá que gasté 5000 en comida'*."
    tipo = detectar_tipo_movimiento(texto) or 'gasto'
    categoria = extraer_categoria(texto)
    fecha = extraer_fecha(texto)

    st.session_state['ia_pendiente_mov'] = dict(
        tipo=tipo, monto=monto, categoria=categoria, descripcion=texto, fecha=fecha,
    )
    signo = {'gasto': '🔴', 'ingreso': '🟢', 'deuda': '🟠'}.get(tipo, '⚪')
    return (f"{signo} Voy a registrar un **{tipo}** de **${monto:,.2f}** en **{categoria}** "
            f"({fecha}). ¿Confirmás? (respondé *sí* o *no*)")


def _obtener_resumen_finanzas_fd(ctx):
    """Prueba varios nombres/firmas comunes para leer el resumen financiero,
    igual que el adaptador de escritura. Devuelve (resumen, error)."""
    fd = ctx.get('fd')
    supabase = ctx.get('supabase')
    user_id = ctx.get('user_id')
    if fd is None or supabase is None or user_id is None:
        return None, "Falta la conexión con Supabase o el user_id en ctx."

    intentos = [
        ('obtener_resumen_completo', (supabase, user_id)),
        ('obtener_resumen', (supabase, user_id)),
        ('resumen_completo', (supabase, user_id)),
        ('obtener_resumen_financiero', (supabase, user_id)),
        ('get_resumen', (supabase, user_id)),
    ]
    ultimo_error = None
    for nombre_fn, args in intentos:
        fn = getattr(fd, nombre_fn, None)
        if fn is None:
            continue
        try:
            return fn(*args), None
        except Exception as e:
            ultimo_error = f"{nombre_fn}() -> {e}"
            continue
    return None, (
        "No encontré una función compatible en finanzas_data.py para leer el resumen "
        f"(probé obtener_resumen_completo / obtener_resumen / resumen_completo / "
        f"obtener_resumen_financiero / get_resumen). "
        + (f"Último error: {ultimo_error}. " if ultimo_error else "Ninguna de esas funciones existe. ")
        + "Decime el nombre exacto de la función que devuelve el resumen y lo ajusto."
    )


def _responder_finanzas(ctx):
    resumen, err = _obtener_resumen_finanzas_fd(ctx)
    if err:
        return f"⚠️ {err}"
    if not resumen:
        return ("Todavía no cargaste datos en Finanzas Personales. Podés decirme algo como "
                "*'anotá que gasté 5000 en comida'* para empezar, o ir directo a esa sección.")
    return f"Tu resumen financiero:\n\n{resumen}"


# ── Análisis de ticker (corto + largo + fundamental) ─────────────

def _responder_analizar(tk, ctx):
    r_corto, r_largo, r_fund = None, None, None

    df_v = ctx['descargar_datos'](tk, '3mo'); df_m = ctx['descargar_datos'](tk, '1mo')
    if df_v is not None and df_m is not None:
        cl_v = ctx['get_close_series'](df_v); cl_m = ctx['get_close_series'](df_m)
        if cl_v is not None and cl_m is not None and len(cl_v.dropna()) >= 15:
            atr = ctx['calcular_atr'](df_m)
            sa, sn, ss = ctx['scores_corto'](cl_v, cl_m, atr)
            r_corto = dict(sa=sa, sn=sn, ss=ss, señal=ctx['señal_accion_corto'](sa, sn, ss),
                           precio=float(cl_m.iloc[-1]))

    df_l = ctx['descargar_datos'](tk, '2y')
    cl_l = ctx['get_close_series'](df_l) if df_l is not None else None
    if cl_l is not None and len(cl_l) >= 150:
        r_largo = ctx['analizar_largo'](tk, cl_l)

    if not ctx['_es_activo_sin_fundamentals'](tk):
        industria = ctx['TICKER_INDUSTRY'].get(tk, 'Sin Clasificar')
        r_fund = ctx['analizar_fundamental'](tk, industria)

    if not r_corto and not r_largo:
        return f"No pude encontrar datos suficientes para **{tk}**. Verificá que el símbolo sea correcto."

    partes = [random.choice(_APERTURAS_TICKER).format(tk=tk)]

    if r_corto:
        partes.append(f"\n**Corto plazo** ({r_corto['precio']:.2f} USD): Score Acumulación {r_corto['sa']:.0f}/100, "
                       f"Anticipación {r_corto['sn']:.0f}/100 → señal **{r_corto['señal']}**.")

    if r_largo:
        partes.append(f"\n**Largo plazo**: Global Score {int(r_largo['global_score'])}/100 ({r_largo['sesgo']}), "
                       f"Sharpe {r_largo['sharpe']:.2f}, retorno anual {r_largo['ret_anual']:+.1f}%, "
                       f"máxima caída histórica {r_largo['max_dd']:.1f}%.")
        partes.append(f"\n{ctx['interpretar_largo'](r_largo)}")

    if r_fund:
        roe_txt = f"{r_fund.get('roe')*100:.1f}%" if r_fund.get('roe') else 'N/D'
        partes.append(f"\n**Fundamental**: señal **{r_fund['senal_final']}** "
                       f"(PER {r_fund.get('per','N/D')}, ROE {roe_txt}). "
                       f"Recomendación de analistas: {r_fund.get('recommendation') or 'N/D'}.")

    partes.append("\n\n*¿Querés que lo compare con otro activo, vea su F-Score, o su Top-Down Cuantitativo?*")
    return "\n".join(partes)


def _responder_comparar(tickers, ctx):
    filas = []
    for tk in tickers[:5]:
        df_l = ctx['descargar_datos'](tk, '2y')
        cl_l = ctx['get_close_series'](df_l) if df_l is not None else None
        if cl_l is not None and len(cl_l) >= 150:
            r = ctx['analizar_largo'](tk, cl_l)
            if r:
                filas.append((tk, r))
    if not filas:
        return "No pude calcular el análisis cuantitativo para esos activos (historial insuficiente)."

    filas.sort(key=lambda x: x[1]['global_score'], reverse=True)
    lineas = [f"Comparando {', '.join(tk for tk,_ in filas)}:\n"]
    for tk, r in filas:
        lineas.append(f"- **{tk}**: Global Score {int(r['global_score'])}/100 ({r['sesgo']}), "
                       f"Sharpe {r['sharpe']:.2f}, retorno anual {r['ret_anual']:+.1f}%")
    ganador = filas[0]
    lineas.append(f"\n🏆 **{ganador[0]}** lidera el grupo por Global Score, pero fijate el drawdown "
                   f"({ganador[1]['max_dd']:.1f}%) antes de sacar conclusiones — más score no siempre es menos riesgo.")
    return "\n".join(lineas)


def _responder_industria(industria_nombre, ctx):
    cargar_acciones = ctx.get('cargar_acciones_corto')
    if not cargar_acciones:
        return (f"Detecté que preguntás por **{industria_nombre}**, pero no tengo acceso a esos datos "
                f"desde acá ahora mismo. Probá con *'analizame <ticker>'* de esa industria puntual.")

    datos_ind = cargar_acciones((industria_nombre,))
    tickers_data = datos_ind.get(industria_nombre, {})
    if not tickers_data:
        return f"No pude obtener datos de corto plazo para la industria **{industria_nombre}** en este momento."

    top = sorted(tickers_data.items(), key=lambda x: x[1]['sa'], reverse=True)[:6]
    lineas = [f"Esto es lo que muestra **{industria_nombre}** ahora mismo (top por Score de Acumulación):\n"]
    for tk, d in top:
        lineas.append(f"- **{tk}**: Acum {d['sa']:.0f}/100, Antic {d['sn']:.0f}/100 → {d.get('accion','')}")
    lineas.append(f"\n*Hay {len(tickers_data)} activos en total en {industria_nombre} en la app. "
                   f"Decime 'analizame <ticker>' para ver el detalle completo de alguno de ellos.*")
    return "\n".join(lineas)


def _responder_oportunidades(texto, ctx):
    t = texto.lower()
    if 'sector' in t:
        datos = ctx['cargar_sectores_corto'](); etiqueta = 'sectores'
    elif re.search(r'\bpa[ií]s', t):
        datos = ctx['cargar_paises_corto'](); etiqueta = 'países'
    elif ctx.get('cargar_mercados_corto') and re.search(r'commodit|cripto|oro|petr[oó]leo|metal', t):
        datos = ctx['cargar_mercados_corto'](); etiqueta = 'mercados'
    else:
        datos = ctx['cargar_sectores_corto'](); etiqueta = 'sectores'

    top = sorted(datos.items(), key=lambda x: x[1]['sa'], reverse=True)[:5]
    lineas = [f"Los {etiqueta} con mejor Score de Acumulación ahora mismo:\n"]
    for n, d in top:
        lineas.append(f"- **{n}**: Acum {d['sa']:.0f}/100, Antic {d['sn']:.0f}/100 → {d.get('accion','')}")
    lineas.append("\n*Recordá: score alto = relativamente barato en su propio historial reciente, no es una garantía de suba.*")
    return "\n".join(lineas)


def _responder_simular(tk, monto, periodo, ctx):
    df = ctx['descargar_datos'](tk, periodo)
    cl = ctx['get_close_series'](df) if df is not None else None
    if cl is None or len(cl) < 2:
        return f"No tengo datos suficientes para simular {tk} en ese período."
    ret = float(cl.iloc[-1] / cl.iloc[0] - 1)
    final = monto * (1 + ret)
    signo = "ganado" if ret >= 0 else "perdido"
    return (f"Si hubieras invertido **USD {monto:,.0f}** en **{tk}** hace {periodo}, "
            f"hoy tendrías **USD {final:,.2f}** — habrías {signo} {abs(ret)*100:.1f}%.\n\n"
            f"*(Esto es retorno histórico puro, sin comisiones ni impuestos.)*")


def _responder_glosario(texto, ctx):
    t = texto.lower()
    match = next((k for k in ctx['GLOSARIO'] if k.lower() in t), None)
    if not match:
        palabras = re.findall(r'\b\w{3,}\b', t)
        for p in palabras:
            match = next((k for k in ctx['GLOSARIO'] if p in k.lower()), None)
            if match: break
    if not match:
        return "No identifiqué el término. Probá con el nombre exacto, ej: *'qué significa el Sharpe'* o *'qué es el PER'*."
    return f"**{match}**: {ctx['GLOSARIO'][match]}"


# ── Nuevos módulos ────────────────────────────────────────────────

def _responder_tdc(tk, ctx):
    fn = ctx.get('_tdc_analizar_ticker')
    horizontes = ctx.get('HORIZONTES_TDC')
    if not fn or not horizontes:
        return ("El Top-Down Cuantitativo (Mediano/Largo Plazo) no está conectado directamente acá todavía. "
                "Lo encontrás en 📈 Largo Plazo → Top-Down Cuantitativo, eligiendo el horizonte y el activo.")
    texto_fn = ctx.get('_tdc_texto_interpretacion')
    partes = [f"**Top-Down Cuantitativo — {tk}**\n"]
    for hz_key, cfg in horizontes.items():
        d = fn(tk, cfg)
        if not d:
            partes.append(f"\n**{cfg['nombre']}**: historial insuficiente.")
            continue
        partes.append(f"\n**{cfg['nombre']}**: Acum {d['sa']:.0f} · Antic {d['sn']:.0f} · Sent {d['ss']:.0f} "
                       f"→ {d['accion']}")
        if texto_fn:
            partes.append(f"\n_{texto_fn(d['sa'], d['sn'], d['ss'])}_")
    return "\n".join(partes)


def _responder_fscore(tk, ctx):
    fn = ctx.get('calcular_fscore')
    if not fn:
        return (f"El F-Score (Piotroski) de **{tk}** no está conectado directo acá — andá a "
                f"🧰 Herramientas → F-Score (Piotroski) y buscalo ahí, te muestra el desglose de los 9 criterios.")
    try:
        r = fn(tk)
    except Exception:
        r = None
    if not r:
        return f"No pude calcular el F-Score de {tk} (puede no tener suficientes estados financieros disponibles)."
    return f"**F-Score (Piotroski) de {tk}**: {r}"


def _responder_breadth(ctx):
    fn = ctx.get('resumen_breadth')
    if not fn:
        return ("La Salud del Mercado (amplitud, avance/declive, máximos/mínimos, concentración) se calcula "
                "sobre todo el universo de acciones de la app y conviene verla en su pantalla dedicada: "
                "🧰 Herramientas → Salud del Mercado.")
    try:
        return fn()
    except Exception:
        return "No pude calcular la Salud del Mercado ahora mismo."


def _responder_macro(ctx):
    return ("📉 **Renta Fija y Macro** incluye tasas del Tesoro (3m/5y/10y/30y), bonos soberanos y corporativos, "
            "crédito de alto rendimiento, deuda emergente, y 12 ratios macro estratégicos (curva de tasas, "
            "spreads de crédito, etc.). Es una pantalla con muchos gráficos, así que te conviene abrirla directo: "
            "🧰 Herramientas → Renta Fija y Macro. Si me decís un ticker de bono/ETF puntual (ej. TLT, HYG, ^TNX) "
            "te puedo dar el análisis cuantitativo de corto/largo plazo igual que con cualquier otro activo.")


def _responder_opciones(tk, ctx):
    base = ("🎲 **Valuación de Opciones** calcula precios con Black-Scholes y modelo binomial, muestra las "
            "griegas (Delta, Gamma, Theta, Vega, Rho), tiene un catálogo de estrategias armadas (spreads, "
            "straddles, etc.) y grafica el payoff. Como necesita que elijas strike, vencimiento y tipo de opción, "
            "es mejor usarla directo en 📈 Trading → Valuación de Opciones.")
    if tk:
        base += f"\n\nPara arrancar ya con **{tk}** cargado, andá a esa sección y buscalo ahí."
    return base


def _responder_pares(ctx):
    return ("🔄 **Rotación y Pares** tiene: Análisis Técnico, un Scanner de Pares por Mean Reversion (ratio entre "
            "un benchmark sectorial y sus empresas, con Z-Score), Cointegración (Engle-Granger) y Volatilidad (VIX). "
            "Elegís sectores y parámetros (ventana, Z de entrada/salida), así que conviene abrirlo directo en "
            "📈 Trading → Rotación y Pares. Si querés, te puedo tirar oportunidades por sector o país desde acá mismo "
            "con *'qué sectores están baratos'*.")


def _responder_optimizador(tickers, ctx):
    base = ("🧮 **Optimizador de Cartera** corre una simulación Monte Carlo sobre los activos que elijas y te "
            "devuelve 5 carteras candidatas (más rentable, mejor Sharpe, mejor Sortino, menor drawdown y la "
            "recomendada por Score Global), comparadas contra un benchmark. También tiene rebalanceo de tu "
            "cartera actual, riesgo avanzado (VaR/CVaR), simulador de crisis y ajuste por inflación.")
    if tickers:
        base += (f"\n\nDetecté que mencionaste {', '.join(tickers)} — andá a 🧰 Herramientas → Optimizar cartera, "
                  f"agregalos ahí y corré la simulación (necesita elegir benchmark, capital y cantidad de "
                  f"simulaciones, por eso conviene hacerlo en esa pantalla).")
    else:
        base += "\n\nEs una herramienta interactiva — abrila en 🧰 Herramientas → Optimizar cartera."
    return base


# ==============================================================
#  UI DE CHAT
# ==============================================================

_SUGERENCIAS_RAPIDAS = [
    "¿Qué sectores están baratos?",
    "Analizame NVDA",
    "¿Cómo está mi presupuesto?",
    "Anotá que gasté 5000 en comida",
]


def modulo_ia_asistente(ctx):
    if not ctx.get('tiene_acceso_pro'):
        st.markdown("""
        <div style="background:linear-gradient(135deg,#1a0d20 0%,#150a30 50%,#0d1117 100%);
             border:1px solid #21262d; border-top:2px solid #bc8cff;
             border-radius:14px; padding:40px 32px; text-align:center; margin-top:20px;">
          <div style="font-size:40px;margin-bottom:12px">🔒🤖</div>
          <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:8px">
            El Asistente IA es exclusivo del plan Pro
          </div>
          <div style="font-size:13px;color:#8b949e;max-width:480px;margin:0 auto">
            Actualizá tu plan para acceder al asistente que analiza activos, compara opciones,
            revisa tus finanzas personales y te deja registrar movimientos por chat.
          </div>
        </div>
        """, unsafe_allow_html=True)
        return

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#1a0d30 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #bc8cff;
         border-radius:14px; padding:22px 26px; margin-bottom:18px;">
      <div style="font-size:17px;font-weight:700;color:#e6edf3;margin-bottom:4px">🤖 Asistente Capital+</div>
      <div style="font-size:12px;color:#6b7d9a">Preguntame por cualquier módulo de la app, o pedime que registre un gasto/ingreso. ⚠️ No es asesoramiento financiero.</div>
    </div>
    """, unsafe_allow_html=True)

    if 'ia_mensajes' not in st.session_state:
        st.session_state['ia_mensajes'] = []

    cols_sug = st.columns(len(_SUGERENCIAS_RAPIDAS))
    sugerencia_click = None
    for col, sug in zip(cols_sug, _SUGERENCIAS_RAPIDAS):
        with col:
            if st.button(sug, use_container_width=True, key=f'ia_sug_{sug}'):
                sugerencia_click = sug

    for msg in st.session_state['ia_mensajes']:
        with st.chat_message(msg['role'], avatar='🤖' if msg['role'] == 'assistant' else None):
            st.markdown(msg['content'])

    chat_val = st.chat_input("Preguntame algo...")
    prompt = sugerencia_click or chat_val
    if prompt:
        st.session_state['ia_mensajes'].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant", avatar='🤖'):
            with st.spinner("Analizando..."):
                resp = responder(prompt, ctx)
            st.markdown(resp)
        st.session_state['ia_mensajes'].append({"role": "assistant", "content": resp})

    if st.button('🗑️ Limpiar conversación', key='ia_clear'):
        st.session_state['ia_mensajes'] = []
        st.session_state['ia_pendiente_mov'] = None
        st.rerun()
