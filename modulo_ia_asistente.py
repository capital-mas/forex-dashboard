# modulo_ia_asistente.py
import re
import random
import difflib
import streamlit as st

# ── Palabras clave por intención (orden de prioridad) ──
_PATRONES_INTENCION = [
    ('finanzas',      [r'\bmis?\s+finanzas\b', r'\bfinanzas\b', r'\bmis?\s+gastos?\b', r'\bgastos?\b',
                        r'\bmi\s+presupuesto\b', r'\bpresupuesto\b', r'\bcu[aá]nto\s+gast',
                        r'\bmis?\s+deudas?\b', r'\bdeudas?\b', r'\bmi\s+ahorro\b', r'\bahorros?\b',
                        r'\bmis?\s+ingresos?\b', r'\bingresos?\b', r'\bmi\s+situaci[oó]n\s+financiera\b']),
    ('comparar',      [r'\bcompar', r'\bvs\.?\b', r'\bcu[aá]l\s+es\s+mejor\b', r'\bo\s+\w+\?']),
    ('oportunidades', [r'\boportunidad', r'\brecomend', r'\bqu[eé]\s+me\s+recomend', r'\bideas?\s+de\s+inversi[oó]n\b',
                        r'\bd[oó]nde\s+invert', r'\bqu[eé]\s+comprar']),
    ('simular',       [r'\bsi\s+invi[eé]rto\b', r'\bcu[aá]nto\s+tendr[ií]a\b', r'\bhubiera\s+invertido\b',
                        r'\bsimul']),
    ('glosario',      [r'\bqu[eé]\s+significa\b', r'\bqu[eé]\s+es\s+(el|la|un|una)\b', r'\bexplic[aá]']),
    ('ayuda',         [r'\bhola\b', r'\bqu[eé]\s+pod[eé]s\s+hacer\b', r'\bayuda\b', r'\bmenu\b', r'^\s*$']),
]

def detectar_intencion(texto):
    t = texto.lower()
    for intencion, patrones in _PATRONES_INTENCION:
        if any(re.search(p, t) for p in patrones):
            return intencion
    return 'analizar_ticker'  # default: si no matchea nada, asumimos que pregunta por un activo


# ── Palabras comunes del español que coinciden con tickers reales
#    (ej. "EL" = Estée Lauder, "A" = Agilent, "ON" = ON Semiconductor).
#    Si no se filtran, frases normales generan falsos positivos. ──
_STOPWORDS_TICKER = {
    'EL','LA','LOS','LAS','UN','UNA','UNOS','UNAS','DE','DEL','AL','EN','Y','O','U',
    'ES','SE','SU','SUS','TU','TUS','MI','MIS','LO','LE','LES','NO','SI','SOY','ERES',
    'CON','SIN','POR','PARA','QUE','COMO','CUAL','QUIEN','CUANTO','CUANDO','DONDE',
    'ESTA','ESTE','ESTO','ESA','ESE','ESO','HAY','MAS','MUY','TAN','SOBRE','ENTRE',
    'HOY','AYER','AHORA','BIEN','MAL','TODO','TODA','TODOS','TODAS','OK','ASI','SOLO',
    'ME','TE','NOS','OS','YA','VA','VE','DA','DI','EH','AH','OH','IR','VER','SER','A',
}

# ── Nombres de empresas/activos en lenguaje natural → ticker real.
#    Cubre además errores de tipeo comunes (ej. "nvdia") vía fuzzy matching. ──
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
    """Detecta nombres de empresas/activos escritos en lenguaje natural (con o sin
    errores de tipeo) y los traduce al ticker real."""
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
    """Detecta si el usuario mencionó el nombre de una industria/sector conocido
    por la app (ej. 'semiconductores', 'bancos', 'energía renovable')."""
    t = texto.lower()
    # Ordena por longitud descendente para priorizar coincidencias más específicas
    # (ej. 'bancos regionales' antes que 'bancos').
    for ind in sorted(industrias_validas, key=len, reverse=True):
        if ind.lower() in t:
            return ind
    return None


def extraer_tickers(texto, universo_valido, ctx_validar):
    """Busca tokens que parezcan tickers y los valida contra el universo conocido de la app
    (evita falsos positivos con palabras comunes en mayúscula), y además reconoce nombres
    de empresas/activos escritos en lenguaje natural (ej. 'nvidia', 'bitcoin')."""
    encontrados = []

    # 1) Nombres de empresas/activos en lenguaje natural (con tolerancia a typos)
    encontrados.extend(_detectar_alias(texto))

    # 2) Tickers explícitos (formato tipo NVDA, BTC-USD, EURUSD=X, etc.)
    candidatos = re.findall(r'\b[A-Za-z]{1,6}(?:[.\-=\^][A-Za-z0-9]{1,4})?\b', texto)
    for c in candidatos:
        c_norm = c.upper()
        if c_norm in _STOPWORDS_TICKER:
            continue
        if c_norm in universo_valido:
            # Palabras cortas escritas en minúscula son casi siempre palabras
            # comunes del idioma, no tickers — solo las aceptamos si el usuario
            # las escribió en mayúsculas (como se tipea un ticker real).
            if len(c_norm) <= 3 and not c.isupper():
                continue
            encontrados.append(c_norm)
            continue
        # Si el usuario lo escribió tal cual en mayúsculas (ej "NVDA"), lo aceptamos
        # aunque no esté en el universo local (podría ser un ticker externo válido)
        if c.isupper() and len(c) >= 2:
            val = ctx_validar(c)
            if val:
                encontrados.append(val)

    return list(dict.fromkeys(encontrados))  # dedup preservando orden


def extraer_monto(texto):
    m = re.search(r'(\d[\d\.,]*)\s*(?:usd|dolares|dólares|d[oó]lares|\$)?', texto.lower())
    if not m:
        return None
    val = m.group(1).replace('.', '').replace(',', '.')
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
    if 'a[ñn]o' in t or re.search(r'\ba[ñn]o\b', t): return '1y'
    return '1y'


# ==============================================================
#  Composición de respuestas (con variedad de frases, para que no suene a robot)
# ==============================================================

_APERTURAS_TICKER = [
    "Mirando {tk} ahora mismo:",
    "Che, esto es lo que muestra {tk}:",
    "Te tiro el panorama de {tk}:",
    "Esto encontré sobre {tk}:",
]

def responder(texto_usuario, ctx):
    """ctx: dict con funciones y datos del módulo principal (igual que antes)."""
    intencion = detectar_intencion(texto_usuario)
    tickers = extraer_tickers(texto_usuario, ctx['UNIVERSO_TICKERS_VALIDOS'], ctx['validar_ticker'])

    # Detecta mención de una industria/sector (ej. "semiconductores") — solo si no
    # hay ya un ticker explícito, para no pisar el análisis de un ticker puntual.
    industrias_validas = set(ctx.get('TICKER_INDUSTRY', {}).values())
    industria_detectada = _detectar_industria(texto_usuario, industrias_validas) if not tickers else None

    # Usa el último ticker mencionado si esta pregunta no trae uno nuevo NI una industria
    # (contexto conversacional simple, ej. seguir preguntando por el mismo activo)
    if (not tickers and not industria_detectada and st.session_state.get('ia_ultimo_ticker')
            and intencion in ('analizar_ticker', 'simular')):
        tickers = [st.session_state['ia_ultimo_ticker']]
    if tickers:
        st.session_state['ia_ultimo_ticker'] = tickers[0]

    if intencion == 'ayuda' and not tickers and not industria_detectada:
        return _respuesta_ayuda()

    if intencion == 'finanzas':
        return _responder_finanzas(ctx)

    if intencion == 'glosario':
        return _responder_glosario(texto_usuario, ctx)

    if intencion == 'comparar':
        if len(tickers) < 2:
            return "Decime al menos dos activos para comparar (ej: *'compará NVDA vs AMD'*)."
        return _responder_comparar(tickers, ctx)

    # Si mencionó una industria/sector conocido (y no un ticker puntual), le mostramos
    # el panorama de ese sector en vez de reutilizar el último ticker analizado.
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

    # default: analizar_ticker
    if not tickers:
        return ("No detecté ningún ticker en tu mensaje. Probá algo como *'analizame NVDA'*, "
                "*'compará YPF y GGAL'*, *'semiconductores'*, o *'qué significa el Sharpe'*. "
                "Escribí *ayuda* para ver todo lo que puedo hacer.")
    return _responder_analizar(tickers[0], ctx)


def _respuesta_ayuda():
    return """¡Hola! 👋 Soy el asistente de Capital+. Puedo ayudarte con:

- **📊 Análisis de un activo** — *"analizame NVDA"*, *"cómo está el Bitcoin"*
- **⚖️ Comparaciones** — *"comparar YPF vs GGAL"*
- **🎯 Oportunidades** — *"qué sectores están baratos"*, *"dame ideas en tecnología"*
- **💰 Tus finanzas** — *"cómo está mi presupuesto"*, *"cuánto debo"*
- **📐 Simulaciones** — *"si invierto 1000 en AAPL en el último año"*
- **📖 Glosario** — *"qué significa el Sharpe"*

⚠️ Todo lo que te muestro sale de datos reales de la app — no es asesoramiento financiero, son datos para que decidas vos."""


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
        partes.append(f"\n**Fundamental**: señal **{r_fund['senal_final']}** "
                       f"(PER {r_fund.get('per','N/D')}, ROE {r_fund.get('roe',0)*100 if r_fund.get('roe') else 'N/D'}%). "
                       f"Recomendación de analistas: {r_fund.get('recommendation') or 'N/D'}.")

    partes.append("\n\n*¿Querés que compare este activo con otro, o que te explique algún término?*")
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
    """Muestra el top de la industria/sector mencionado (ej. 'Semiconductores'),
    usando los mismos tickers de esa industria que ya tiene la app."""
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
        datos = ctx['cargar_sectores_corto']()
        etiqueta = 'sectores'
    elif 'pa[ií]s' in t or re.search(r'\bpa[ií]s', t):
        datos = ctx['cargar_paises_corto']()
        etiqueta = 'países'
    else:
        datos = ctx['cargar_sectores_corto']()
        etiqueta = 'sectores'

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
        # buscar por palabra suelta
        palabras = re.findall(r'\b\w{3,}\b', t)
        for p in palabras:
            match = next((k for k in ctx['GLOSARIO'] if p in k.lower()), None)
            if match: break
    if not match:
        return "No identifiqué el término. Probá con el nombre exacto, ej: *'qué significa el Sharpe'* o *'qué es el PER'*."
    return f"**{match}**: {ctx['GLOSARIO'][match]}"


def _responder_finanzas(ctx):
    try:
        resumen = ctx['fd'].obtener_resumen_completo(ctx['supabase'], ctx['user_id'])
    except Exception:
        return "No pude acceder a tus datos de finanzas personales ahora mismo."
    if not resumen:
        return "Todavía no cargaste datos en Finanzas Personales. Andá a esa sección para empezar a cargar ingresos y gastos."
    # Formateá según la forma real de tu resumen — placeholder genérico:
    return f"Tu resumen financiero:\n\n{resumen}"


# ==============================================================
#  UI de chat
# ==============================================================

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
            Actualizá tu plan para acceder al asistente que analiza activos, compara opciones
            y revisa tus finanzas personales por vos.
          </div>
        </div>
        """, unsafe_allow_html=True)
        return

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#1a0d30 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #bc8cff;
         border-radius:14px; padding:22px 26px; margin-bottom:18px;">
      <div style="font-size:17px;font-weight:700;color:#e6edf3;margin-bottom:4px">🤖 Asistente Capital+</div>
      <div style="font-size:12px;color:#6b7d9a">Preguntame por un activo, comparación, finanzas o cualquier término. ⚠️ No es asesoramiento financiero.</div>
    </div>
    """, unsafe_allow_html=True)

    if 'ia_mensajes' not in st.session_state:
        st.session_state['ia_mensajes'] = []

    for msg in st.session_state['ia_mensajes']:
        with st.chat_message(msg['role'], avatar='🤖' if msg['role']=='assistant' else None):
            st.markdown(msg['content'])

    prompt = st.chat_input("Preguntame algo...")
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
        st.rerun()
