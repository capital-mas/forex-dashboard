# modulo_ia_asistente.py
# ==============================================================
#  ASISTENTE IA — v7 (países completos + mercados reales + índices/ETFs)
#  Cubre: análisis COMPLETO de ticker (todos los módulos + resumen
#  compuesto + conclusión), comparador, oportunidades (sectores/
#  países/mercados/subsectores), simulador, glosario, finanzas
#  personales (lectura + REGISTRO de movimientos con confirmación y
#  botones rápidos), Top-Down Cuantitativo, F-Score, Salud del
#  Mercado, Renta Fija/Macro, Opciones, Rotación/Pares, Optimizador
#  de Cartera, y el pipeline de armado de cartera end-to-end
#  (F-Score + TDC corto/largo + Optimizador Monte Carlo).
#
#  Novedades v7:
#    - Países que además son industria (Argentina, Brasil, China,
#      India): al nombrarlos devuelve el panorama COMPLETO: análisis
#      del ETF, índice local, divisa, TODAS las acciones del país y
#      el calendario económico. Se configura en _PAIS_COMPLETO.
#    - _responder_industria acepta top=None para listar todas.
#    - _detectar_industria ahora respeta límites de palabra
#      ("india" ya no matchea dentro de otra palabra).
#
#  Novedades v6:
#    - Soporta TODO MERCADOS_REALES (energía, metales, mineras, agro,
#      blandos, cripto, cripto ETF) por nombre o ticker, con alias
#      con límites de palabra ("oro" ya no matchea dentro de "tesoro").
#    - Alias de índices: nasdaq -> QQQ, s&p 500 -> SPY, dow -> DIA...
#    - Futuros, cripto, índices y ETFs se tratan como "sin balance":
#      no piden Fundamental/F-Score y quedan exentos del filtro de
#      F-Score en el armado de cartera.
#    - Tickers cortos en minúscula ("spy", "pbr") se aceptan en
#      mensajes breves; un ticker que falló no se arrastra al
#      siguiente mensaje.
#    - Nueva intención 'mercados' ("cómo están los granos").
#    - Armado de cartera acepta grupos: cripto, metales, granos,
#      commodities, energía, blandos...
#
#  Novedades v5 (velocidad):
#    - El chat corre como @st.fragment.
#    - _responder_analizar paraleliza descargas y cálculos y cachea
#      el resultado 10 min por ticker.
#    - F-Score cacheado 6 h (st.cache_data).
#    - Armado de cartera: ranking y descargas de precios en paralelo.
#
#  Todo lo que el asistente puede "computar" directamente depende
#  de qué funciones le pasás en `ctx` (ver diccionario CTX_IA en el
#  script principal). Si una función no está en ctx, el asistente
#  degrada con gracia.
#
#  ⚠️ CTX_IA necesita (además de lo que ya tenías):
#      ACCIONES_POR_INDUSTRIA, calcular_rsi, calcular_regimen_hmm,
#      obtener_perfil_empresa, resumen_visual_fundamental,
#      MERCADOS_REALES, ETFS, SECTORES_TOTAL, UNIVERSO_TICKERS_VALIDOS
#  Opcionales (una línea de texto por ticker, o None):
#      gex_resumen, cot_resumen, velas_resumen, opciones_resumen
#  Opcional para la Conclusión con niveles de GEX:
#      gex_niveles -> dict(spot, call_wall, put_wall, flip,
#                          regimen, squeeze_score, inminente)
#
#  Requiere Streamlit >= 1.37 (st.fragment / st.rerun(scope=...)).
# ==============================================================

import re
import time
import random
import difflib
import threading
import unicodedata
from datetime import datetime, date
import numpy as np
import pandas as pd
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
except Exception:  # versiones viejas de Streamlit
    add_script_run_ctx = None
    get_script_run_ctx = None


# ==============================================================
#  HELPERS DE MERCADOS / ACTIVOS SIN BALANCE
# ==============================================================

def _norm(s):
    """Minúsculas y sin acentos."""
    return ''.join(c for c in unicodedata.normalize('NFD', s.lower())
                   if unicodedata.category(c) != 'Mn')


_ETFS_SIN_BALANCE = {'URA', 'LIT', 'SLX', 'GDX', 'SIL', 'COPX'}


_CATALOGOS_CTX = ('MERCADOS_REALES', 'FOREX', 'ETFS', 'SECTORES_TOTAL', 'PAISES')


def _catalogos(ctx):
    """[(clave, {nombre: (ticker, grupo, ...)})] de todos los catálogos conectados."""
    return [(k, ctx.get(k) or {}) for k in _CATALOGOS_CTX]


def _universo_completo(ctx):
    """TODOS los tickers que conoce la app: acciones por industria + forex +
    países + ETFs + sectores + mercados reales (+ lo que venga en ctx)."""
    u = set(ctx.get('UNIVERSO_TICKERS_VALIDOS') or ())
    for _, cat in _catalogos(ctx):
        u |= {v[0] for v in cat.values()}
    for lst in (ctx.get('ACCIONES_POR_INDUSTRIA') or {}).values():
        u |= set(lst)
    return u


def _tickers_etf(ctx):
    out = set()
    for d in (ctx.get('ETFS'), ctx.get('SECTORES_TOTAL')):
        out |= {v[0] for v in (d or {}).values()}
    return out


def _es_sin_fundamentals(tk, ctx):
    """Futuros, forex, cripto, índices y ETFs no tienen balance."""
    if (tk.endswith('=F') or tk.endswith('=X') or tk.endswith('-USD') or tk.startswith('^')
            or tk in _ETFS_SIN_BALANCE or tk in _tickers_etf(ctx)):
        return True
    fn = ctx.get('_es_activo_sin_fundamentals')
    return bool(fn and fn(tk))


def _info_mercado(tk, ctx):
    """(nombre, grupo) si el ticker está en algún catálogo (mercados, forex,
    ETFs, sectores, países), si no None."""
    for _, cat in _catalogos(ctx):
        for nombre, v in cat.items():
            if v[0] == tk:
                return nombre, v[1]
    return None


# ==============================================================
#  INTENCIONES
# ==============================================================

_PATRONES_INTENCION = [
    ('registrar_movimiento', [
        r'\banot[aá]', r'\bregistr[aá]', r'\bcarg[aá]\s+(un\s+)?(gasto|ingreso|movimiento|deuda)',
        r'\bagreg[aá]\s+(un\s+)?(gasto|ingreso|movimiento|deuda)', r'\bsum[aá]\s+(esto|este\s+gasto|este\s+ingreso)',
        r'\bmet[eé]lo\b', r'\bpon[eé]lo\s+en\s+mis?\s+finanzas\b',
    ]),
    ('plan_trading', [
        r'\bplan\s+(de\s+)?trading\b', r'\bscalping\b', r'\bday[\s\-]?trad', r'\bswing\b',
        r'\bstop[\s\-]?loss\b', r'\btake[\s\-]?profit\b', r'\bmarco\s+temporal\b',
        r'\bd[oó]nde\s+entr', r'\bcu[aá]ndo\s+entr', r'\bsetup\b',
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
    # Pipeline de armado de cartera (F-Score + TDC + Optimizador).
    # Va ANTES de 'optimizador' a propósito: "armame una cartera con X" debe
    # disparar el pipeline completo, no la explicación genérica del módulo.
    ('armar_cartera_ia', [
        r'\barm[ao]?[áa]?r?(?:me)?\s+(?:una\s+)?cartera\b',
        r'\barm[ao]?[áa]?r?(?:me)?\s+(?:un\s+)?portafolio\b',
        r'\bconstru[iy]\w*\s+(?:una\s+)?cartera\b', r'\bhaceme\s+una\s+cartera\b',
        r'\bmontame\s+una\s+cartera\b', r'\barmame\s+una\s+cartera\s+con\b',
        r'\bpipeline\s+de\s+cartera\b', r'\barma\s+un\s+portafolio\s+con\b',
    ]),
    ('optimizador', [r'\boptimiz', r'\bmonte\s+carlo\b', r'\bfrontera\s+eficiente\b', r'\brebalance',
                      r'\bmi\s+cartera\b']),
    # Ranking de ETFs (más caros / más baratos)
    ('etfs', [r'\betfs\b', r'\banaliz\w*\s+(los\s+)?etfs?\b']),
    # Grupos de MERCADOS_REALES (commodities, metales, granos, cripto...)
    ('mercados', [r'\bcommodit', r'\bmaterias\s+primas\b', r'\bgranos\b', r'\bcereales\b',
                  r'\bblandos\b', r'\bsofts?\b', r'\bmetales\b', r'\bcriptos?\b',
                  r'\bcriptomonedas?\b', r'\bcrypto', r'\benerg[eé]ticos\b',
                  r'\bmercados\s+reales\b', r'\bforex\b', r'\bdivisas\b', r'\bmonedas\b']),
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
    # una segunda pasada para distinguirlo de una pregunta.
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

# Índices: nombre -> ETF que los replica (los índices crudos no siempre tienen datos)
_ALIAS_ACTIVOS.update({
    'nasdaq': 'QQQ', 'nasdaq 100': 'QQQ',
    's&p 500': 'SPY', 's&p500': 'SPY', 'sp500': 'SPY', 's&p': 'SPY',
    'dow jones': 'DIA', 'russell': 'IWM',
})

# Alias extra de MERCADOS_REALES (los nombres exactos se generan solos desde el dict)
_ALIAS_EXTRA_MERCADOS = {
    'wti': 'CL=F', 'crudo': 'CL=F', 'brent': 'BZ=F', 'gasolina': 'RB=F',
    'uranio': 'URA', 'litio': 'LIT', 'soya': 'ZS=F', 'maiz': 'ZC=F',
    'cafe': 'KC=F', 'azucar': 'SB=F', 'algodon': 'CT=F',
    'btc': 'BTC-USD', 'eth': 'ETH-USD', 'ripple': 'XRP-USD', 'doge': 'DOGE-USD',
}
# Nombres que existen como commodity Y como industria de acciones:
# por defecto gana el commodity, salvo que el mensaje hable de acciones/empresas/industria.
_AMBIGUOS = {'oro', 'plata', 'cobre', 'acero', 'gas natural', 'petroleo'}
_RE_CTX_INDUSTRIA = re.compile(
    r'\b(acciones|empresas|industria|sector|subsector|mineria|mineras|integrado)\b')


_ALIAS_BLOQUEADOS = {'valor', 'crecimiento'}   # palabras comunes: darían falsos positivos


def _limpiar_alias(n):
    n = re.sub(r'\(.*?\)', '', _norm(n))
    n = re.sub(r'[^a-z0-9& ]', ' ', n)
    return re.sub(r'\s+', ' ', n).strip()


def _alias_catalogos(ctx):
    """Nombre -> ticker para MERCADOS_REALES, ETFS y PAISES (los nombres de
    sectores/sub-sectores no, porque los resuelve la lógica de industrias;
    los nombres que chocan con una industria tampoco)."""
    ctx = ctx or {}
    ind = {_norm(k) for k in (ctx.get('ACCIONES_POR_INDUSTRIA') or {})}
    ind |= {_norm(v) for v in (ctx.get('TICKER_INDUSTRY') or {}).values()}
    out = {}
    for clave in ('PAISES', 'ETFS', 'MERCADOS_REALES'):   # el último gana
        for nombre, v in (ctx.get(clave) or {}).items():
            n = _limpiar_alias(nombre)
            if not n or n in _ALIAS_BLOQUEADOS:
                continue
            if clave != 'MERCADOS_REALES' and n in ind:
                continue
            out[n] = v[0]
    out.update(_ALIAS_EXTRA_MERCADOS)
    return out


def _pares_forex(ctx):
    """{('eur','usd'): 'EURUSD=X'} a partir de FOREX ('EUR/USD' -> ('EURUSD=X', grupo))."""
    out = {}
    for nombre, v in ((ctx or {}).get('FOREX') or {}).items():
        a, _, b = nombre.partition('/')
        if a and b:
            out[(a.lower(), b.lower())] = v[0]
    return out


def _detectar_alias(texto, ctx=None):
    ctx = ctx or {}
    t = _norm(texto)
    encontrados = []
    # Forex: acepta eur/usd, eur-usd, eur usd, eurusd, eurusd=x
    for (a, b), tk in _pares_forex(ctx).items():
        m = re.search(rf'(?<![a-z0-9]){a}[\s/\-_]?{b}(?:=x)?(?![a-z0-9])', t)
        if m:
            encontrados.append(tk)
            t = t[:m.start()] + ' ' * (m.end() - m.start()) + t[m.end():]
    alias = {_norm(k): v for k, v in _ALIAS_ACTIVOS.items()}
    alias.update(_alias_catalogos(ctx))
    hay_ctx_ind = bool(_RE_CTX_INDUSTRIA.search(t))
    # Más largos primero y se "consume" lo ya matcheado: "mineras oro" -> GDX, no GC=F
    for a in sorted(alias, key=len, reverse=True):
        if a in _AMBIGUOS and hay_ctx_ind:
            continue
        m = re.search(rf'\b{re.escape(a)}\b', t)
        if m:
            encontrados.append(alias[a])
            t = t[:m.start()] + ' ' * (m.end() - m.start()) + t[m.end():]
    claves = [a for a in alias if ' ' not in a and len(a) >= 5]
    for palabra in re.findall(r'\b[a-z]{5,}\b', t):
        match = difflib.get_close_matches(palabra, claves, n=1, cutoff=0.85)
        if match:
            encontrados.append(alias[match[0]])
    return list(dict.fromkeys(encontrados))


def _detectar_industria(texto, industrias_validas):
    """Industria nombrada en el mensaje (más largas primero, con límites de
    palabra para que 'india' no matchee dentro de otra palabra)."""
    t = texto.lower()
    for ind in sorted(industrias_validas, key=len, reverse=True):
        if re.search(rf'(?<!\w){re.escape(ind.lower())}(?!\w)', t):
            return ind
    return None


def extraer_tickers(texto, universo_valido, ctx_validar, ctx=None):
    encontrados = []
    encontrados.extend(_detectar_alias(texto, ctx))
    candidatos = re.findall(r'\b[A-Za-z]{1,6}(?:[.\-=\^][A-Za-z0-9]{1,4})?\b', texto)
    # En mensajes cortos ("spy", "analizame pbr") aceptamos tickers en minúscula
    corto = len(texto.split()) <= 3
    for c in candidatos:
        c_norm = c.upper()
        if c_norm in _STOPWORDS_TICKER:
            continue
        if c_norm in universo_valido:
            if len(c_norm) <= 3 and not c.isupper() and not (corto and len(c_norm) >= 2):
                continue
            encontrados.append(c_norm)
            continue
        # Índices con ^ (^GSPC, ^TNX): aceptamos "GSPC" si el mensaje trae el ^ o es corto
        if f'^{c_norm}' in universo_valido and (corto or f'^{c_norm}' in texto.upper()):
            encontrados.append(f'^{c_norm}')
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
    if '3 mes' in t or 'trimestre' in t: return '3mo'
    if '6 mes' in t or 'semestre' in t: return '6mo'
    if '2 a' in t or 'dos a' in t: return '2y'
    if '5 a' in t or 'cinco a' in t: return '5y'
    if re.search(r'\ba[ñn]o\b', t): return '1y'
    if 'mes' in t: return '1mo'
    return '1y'


_CATEGORIAS_GASTO_KEYWORDS = {
    'Alimentación':     [r'comida', r'super(mercado)?', r'almuerzo', r'cena', r'restaur', r'delivery', r'kiosco', r'verduler', r'carnicer'],
    'Transporte':       [r'nafta', r'combustible', r'uber', r'taxi', r'colectivo', r'transporte', r'subte', r'peaje', r'sube\b'],
    'Vivienda':         [r'alquiler', r'expensas', r'hipoteca', r'inmobiliaria', r'mantenimiento\s+casa'],
    'Servicios':        [r'\bluz\b', r'\bgas\b', r'internet', r'celular', r'telefono', r'teléfono', r'\bagua\b', r'streaming', r'netflix', r'spotify', r'comisi[oó]n\s+banco'],
    'Salud':            [r'medico', r'médico', r'farmacia', r'obra\s+social', r'prepaga', r'dentista', r'psicolog', r'an[aá]lisis\s+cl[ií]nico'],
    'Entretenimiento':  [r'cine', r'salida', r'bar\b', r'boliche', r'juego', r'teatro', r'viaje'],
    'Educación':        [r'curso', r'colegio', r'universidad', r'facultad', r'libro'],
    'Ropa':             [r'ropa', r'zapatillas', r'calzado', r'indumentaria'],
    'Tecnología':       [r'celular\s+nuevo', r'computadora', r'notebook', r'software', r'perif[eé]ric'],
    'Deudas':           [r'cuota\s+pr[eé]stamo', r'tarjeta\s+de\s+cr[eé]dito', r'pagu[eé]\s+la\s+tarjeta'],
}

_CATEGORIAS_INGRESO_KEYWORDS = {
    'Salario':      [r'sueldo', r'salario', r'n[oó]mina', r'\btrabajo\b'],
    'Freelance':    [r'freelance', r'changa', r'laburo\s+extra', r'proyecto'],
    'Negocio':      [r'negocio', r'\bventas?\b'],
    'Inversiones':  [r'dividendo', r'inter[eé]s(es)?\s+cobrado'],
    'Alquiler':     [r'alquiler.*cobr', r'renta\s+de\s+depto'],
    'Trading':      [r'trading', r'operaci[oó]n\s+cerrada'],
    'Regalo':       [r'regalo'],
}


def extraer_categoria(texto, tipo):
    t = texto.lower()
    mapa = _CATEGORIAS_GASTO_KEYWORDS if tipo == 'gasto' else _CATEGORIAS_INGRESO_KEYWORDS
    for cat, patrones in mapa.items():
        if any(re.search(p, t) for p in patrones):
            return cat
    return 'Otros'


def extraer_cuenta(texto, tipo):
    t = texto.lower()
    if re.search(r'tarjeta|cr[eé]dito', t):
        return 'Crédito' if tipo == 'gasto' else 'Banco'
    if re.search(r'd[eé]bito', t):
        return 'Débito' if tipo == 'gasto' else 'Banco'
    if re.search(r'mercado\s*pago|\bmp\b', t):
        return 'Mercado Pago'
    if re.search(r'crypto|cripto', t):
        return 'Crypto' if tipo == 'ingreso' else 'Otro'
    if re.search(r'transferencia|banco', t):
        return 'Banco'
    return 'Efectivo'


def detectar_tipo_movimiento(texto):
    t = texto.lower()
    if re.search(r'\bdeudas?\b|\bpr[eé]stamos?\b|\bdebo\b|\bcuotas?\b', t):
        return 'deuda'
    # Formas verbales (cobré, ingresé) y sustantivos (ingreso, cobro).
    if re.search(
        r'\bcobr[eé]\b|\bcobros?\b|\bingres[eé]\b|\bingresos?\b|\bme\s+pagaron\b|'
        r'\bsueldo\b|\bsalario\b|\bfacturaci[oó]n\b|\brecib[ií]\b|\bgan[eé]\b',
        t,
    ):
        return 'ingreso'
    if re.search(
        r'\bgast[eé]\b|\bgastos?\b|\bpagu[eé]\b|\bpagos?\b|\bcompr[eé]\b|\bcompras?\b|\bsale?\b',
        t,
    ):
        return 'gasto'
    return None


def extraer_fecha(texto):
    t = texto.lower()
    if 'ayer' in t:
        from datetime import timedelta
        return (date.today() - timedelta(days=1)).isoformat()
    return date.today().isoformat()


# ==============================================================
#  WIZARD DE REGISTRO — Deudas / Corto Plazo / Largo Plazo /
#  Trading / Objetivos (además de Ingreso y Gasto que ya tenían
#  el flujo rápido de una sola frase). Pregunta campo por campo,
#  como un formulario, y al final pide confirmación antes de
#  guardar en Supabase vía finanzas_data.py.
# ==============================================================

_NOMBRE_TIPO_REGISTRO = {
    'ingreso': 'Ingreso',
    'gasto': 'Gasto',
    'deuda': 'Deuda',
    'inv_corto': 'Inversión Corto Plazo',
    'inv_largo': 'Inversión Largo Plazo',
    'trading': 'Operación de Trading',
    'objetivo': 'Objetivo de Ahorro',
}

_OPCIONES_MENU_REGISTRO = [
    ('ingreso', ['1', 'ingreso', 'ingresos']),
    ('gasto', ['2', 'gasto', 'gastos']),
    ('deuda', ['3', 'deuda', 'deudas']),
    ('inv_corto', ['4', 'corto', 'corto plazo', 'inversion corto plazo', 'inversión corto plazo']),
    ('inv_largo', ['5', 'largo', 'largo plazo', 'inversion largo plazo', 'inversión largo plazo']),
    ('trading', ['6', 'trading']),
    ('objetivo', ['7', 'objetivo', 'objetivos', 'ahorro']),
]


def _texto_menu_registro():
    return ("¿Qué querés registrar?\n\n"
            "1️⃣ Ingreso\n2️⃣ Gasto\n3️⃣ Deuda\n4️⃣ Inversión Corto Plazo\n"
            "5️⃣ Inversión Largo Plazo\n6️⃣ Operación de Trading\n7️⃣ Objetivo de Ahorro\n\n"
            "Tocá un botón de abajo o respondé con el número o el nombre. Te voy a ir pidiendo los datos uno por uno.")


def _resolver_tipo_menu(texto):
    t = texto.strip().lower()
    for tipo, alias in _OPCIONES_MENU_REGISTRO:
        if t in alias:
            return tipo
    for tipo, alias in _OPCIONES_MENU_REGISTRO:
        if any(len(a) > 2 and a in t for a in alias):
            return tipo
    return None


def _campos_registro(tipo, ctx):
    """Devuelve la lista de campos a pedir para cada tipo de registro,
    en el mismo orden y con las mismas opciones que usan los formularios
    de finanzas_ui.py, para que lo cargado por chat sea consistente con
    lo que se ve ahí."""
    fd = ctx.get('fd')
    hoy = date.today().isoformat()
    cat_ingresos = list(fd.CATEGORIAS_INGRESOS) if fd else list(_CATEGORIAS_INGRESO_KEYWORDS.keys()) + ['Otros']
    cat_gastos = list(fd.CATEGORIAS_GASTOS) if fd else list(_CATEGORIAS_GASTO_KEYWORDS.keys())

    if tipo == 'ingreso':
        return [
            dict(key='fecha', label='Fecha', tipo='fecha', opcional=True, default=hoy),
            dict(key='descripcion', label='Descripción', tipo='texto', opcional=False),
            dict(key='categoria', label='Categoría', tipo='opciones', opciones=cat_ingresos, opcional=False),
            dict(key='monto', label='Monto', tipo='monto', opcional=False),
            dict(key='cuenta', label='Cuenta', tipo='opciones',
                 opciones=['Efectivo', 'Banco', 'Mercado Pago', 'Crypto', 'Otro'],
                 opcional=True, default='Efectivo'),
            dict(key='notas', label='Notas', tipo='texto', opcional=True, default=''),
        ]
    if tipo == 'gasto':
        return [
            dict(key='fecha', label='Fecha', tipo='fecha', opcional=True, default=hoy),
            dict(key='descripcion', label='Descripción', tipo='texto', opcional=False),
            dict(key='categoria', label='Categoría', tipo='opciones', opciones=cat_gastos, opcional=False),
            dict(key='subcategoria', label='Subcategoría', tipo='texto', opcional=True, default=''),
            dict(key='monto', label='Monto', tipo='monto', opcional=False),
            dict(key='cuenta', label='Cuenta', tipo='opciones',
                 opciones=['Efectivo', 'Débito', 'Crédito', 'Mercado Pago', 'Otro'],
                 opcional=True, default='Efectivo'),
            dict(key='notas', label='Notas', tipo='texto', opcional=True, default=''),
        ]
    if tipo == 'deuda':
        return [
            dict(key='acreedor', label='Acreedor / Institución', tipo='texto', opcional=False),
            dict(key='tipo', label='Tipo de deuda', tipo='opciones',
                 opciones=['Préstamo Personal', 'Tarjeta de Crédito', 'Hipoteca', 'Auto', 'Estudiante',
                           'Familiar', 'Otros'], opcional=False),
            dict(key='montoOriginal', label='Monto Original', tipo='monto', opcional=False),
            dict(key='montoPendiente', label='Monto Pendiente', tipo='monto', opcional=False),
            dict(key='cuotasTotales', label='Cuotas Totales', tipo='numero', opcional=True, default=0),
            dict(key='cuotasPagadas', label='Cuotas Pagadas', tipo='numero', opcional=True, default=0),
            dict(key='cuotaMensual', label='Cuota Mensual', tipo='monto', opcional=True, default=0),
            dict(key='tasaInteres', label='Tasa Anual %', tipo='monto', opcional=True, default=0),
            dict(key='fechaInicio', label='Fecha Inicio', tipo='fecha', opcional=True, default=hoy),
            dict(key='fechaVencimiento', label='Fecha Vencimiento', tipo='fecha', opcional=False),
            dict(key='estado', label='Estado', tipo='opciones',
                 opciones=['Activa', 'En mora', 'Pagada', 'Refinanciada'], opcional=True, default='Activa'),
            dict(key='notas', label='Notas', tipo='texto', opcional=True, default=''),
        ]
    if tipo == 'inv_corto':
        return [
            dict(key='nombre', label='Nombre', tipo='texto', opcional=False),
            dict(key='tipo', label='Tipo', tipo='opciones',
                 opciones=['Plazo Fijo', 'Crypto', 'Fondos Comunes', 'Bonos Corto', 'Cuenta Remunerada', 'Otros'],
                 opcional=False),
            dict(key='monto', label='Monto', tipo='monto', opcional=False),
            dict(key='tasa', label='Tasa Anual %', tipo='monto', opcional=True, default=0),
            dict(key='fechaInicio', label='Fecha Inicio', tipo='fecha', opcional=True, default=hoy),
            dict(key='fechaVencimiento', label='Fecha Vencimiento', tipo='fecha', opcional=False),
            dict(key='estado', label='Estado', tipo='opciones',
                 opciones=['Activa', 'Vencida', 'Cancelada', 'Renovada'], opcional=True, default='Activa'),
            dict(key='notas', label='Notas', tipo='texto', opcional=True, default=''),
        ]
    if tipo == 'inv_largo':
        return [
            dict(key='activo', label='Nombre del Activo', tipo='texto', opcional=False),
            dict(key='tipo', label='Tipo', tipo='opciones',
                 opciones=['Acción', 'ETF', 'Crypto', 'Bono', 'Fondo', 'REIT', 'Otro'], opcional=False),
            dict(key='simbolo', label='Símbolo (Ticker)', tipo='texto', opcional=False),
            dict(key='cantidad', label='Cantidad', tipo='monto', opcional=False),
            dict(key='precioCompra', label='Precio de Compra', tipo='monto', opcional=False),
            dict(key='fechaCompra', label='Fecha de Compra', tipo='fecha', opcional=True, default=hoy),
            dict(key='estado', label='Estado', tipo='opciones',
                 opciones=['Activo', 'Vendido', 'En espera'], opcional=True, default='Activo'),
            dict(key='notas', label='Notas', tipo='texto', opcional=True, default=''),
        ]
    if tipo == 'trading':
        return [
            dict(key='simbolo', label='Par / Activo', tipo='texto', opcional=False),
            dict(key='tipo', label='Tipo', tipo='opciones',
                 opciones=['Acción', 'ETF', 'Crypto', 'Forex', 'Futuros', 'CFD', 'Opción'], opcional=False),
            dict(key='direccion', label='Dirección', tipo='opciones',
                 opciones=['Long (Compra)', 'Short (Venta)'], opcional=False),
            dict(key='cantidad', label='Cantidad', tipo='monto', opcional=False),
            dict(key='precioEntrada', label='Precio de Entrada', tipo='monto', opcional=False),
            dict(key='fechaEntrada', label='Fecha de Entrada', tipo='fecha', opcional=True, default=hoy),
            dict(key='stopLoss', label='Stop Loss', tipo='monto', opcional=True, default=0),
            dict(key='takeProfit', label='Take Profit', tipo='monto', opcional=True, default=0),
            dict(key='estrategia', label='Estrategia', tipo='opciones',
                 opciones=['Scalping', 'Day Trade', 'Swing', 'Posición', 'Tendencia', 'Ruptura', 'Reversión',
                           'Otros'], opcional=True, default=''),
            dict(key='notas', label='Notas / Setup', tipo='texto', opcional=True, default=''),
        ]
    if tipo == 'objetivo':
        return [
            dict(key='nombre', label='Nombre del Objetivo', tipo='texto', opcional=False),
            dict(key='categoria', label='Categoría', tipo='opciones',
                 opciones=['Viaje', 'Auto', 'Casa', 'Fondo Emergencia', 'Educación', 'Tecnología', 'Inversión',
                           'Boda', 'Jubilación', 'Otros'], opcional=False),
            dict(key='meta', label='Monto Meta', tipo='monto', opcional=False),
            dict(key='fechaInicio', label='Fecha Inicio', tipo='fecha', opcional=True, default=hoy),
            dict(key='fechaMeta', label='Fecha Meta', tipo='fecha', opcional=False),
            dict(key='estado', label='Estado', tipo='opciones',
                 opciones=['Activo', 'Pausado', 'Cumplido', 'Cancelado'], opcional=True, default='Activo'),
            dict(key='notas', label='Notas', tipo='texto', opcional=True, default=''),
        ]
    return []


def _formatear_pregunta_campo(campo):
    extra = ""
    if campo['tipo'] == 'opciones':
        lista = "\n".join(f"{i+1}. {o}" for i, o in enumerate(campo['opciones']))
        extra = f"\n{lista}"
    marca_opcional = " _(opcional — tocá 'Omitir' o escribí '-' para dejarlo vacío/por defecto)_" if campo.get('opcional') else ""
    return f"**{campo['label']}**{marca_opcional}:{extra}"


def _parsear_fecha_usuario(texto):
    t = texto.strip().lower()
    if t == 'hoy':
        return date.today().isoformat()
    if t == 'ayer':
        from datetime import timedelta
        return (date.today() - timedelta(days=1)).isoformat()
    m = re.match(r'^(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})$', t)
    if m:
        d, mo, y = m.groups()
        if len(y) == 2:
            y = '20' + y
        try:
            return date(int(y), int(mo), int(d)).isoformat()
        except ValueError:
            return None
    m2 = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', t)
    if m2:
        y, mo, d = m2.groups()
        try:
            return date(int(y), int(mo), int(d)).isoformat()
        except ValueError:
            return None
    return None


def _parsear_respuesta_campo(campo, texto):
    t = texto.strip()
    tl = t.lower()
    if campo.get('opcional') and tl in ('-', 'no', 'ninguna', 'ninguno', 'omitir', 'salteo', 'salta', 'skip', ''):
        return True, campo.get('default', '')

    if campo['tipo'] == 'texto':
        if not t and not campo.get('opcional'):
            return False, None
        return True, t

    if campo['tipo'] == 'monto':
        val = extraer_monto(t)
        if val is None:
            return False, None
        return True, val

    if campo['tipo'] == 'numero':
        try:
            return True, int(re.sub(r'[^\d\-]', '', t) or 0)
        except ValueError:
            return False, None

    if campo['tipo'] == 'fecha':
        val = _parsear_fecha_usuario(t)
        if val is None:
            return False, None
        return True, val

    if campo['tipo'] == 'opciones':
        opts = campo['opciones']
        if t.isdigit():
            idx = int(t) - 1
            if 0 <= idx < len(opts):
                return True, opts[idx]
            return False, None
        match = next((o for o in opts if o.lower() == tl), None)
        if not match:
            cercanos = difflib.get_close_matches(tl, [o.lower() for o in opts], n=1, cutoff=0.5)
            if cercanos:
                match = next(o for o in opts if o.lower() == cercanos[0])
        if match:
            return True, match
        return False, None

    return True, t


def _iniciar_wizard(tipo, ctx):
    campos = _campos_registro(tipo, ctx)
    if not campos:
        return "No reconocí ese tipo de registro. Probá de nuevo con uno de los números del menú."
    st.session_state['ia_wizard'] = dict(tipo=tipo, paso=0, datos={})
    return (f"Dale, vamos a cargar un **{_NOMBRE_TIPO_REGISTRO[tipo]}**. Te voy preguntando los datos uno "
            f"por uno (podés escribir *cancelar* en cualquier momento).\n\n"
            f"{_formatear_pregunta_campo(campos[0])}")


def _continuar_wizard(texto_usuario, ctx):
    wizard = st.session_state['ia_wizard']
    tipo = wizard['tipo']
    campos = _campos_registro(tipo, ctx)
    campo = campos[wizard['paso']]

    if texto_usuario.strip().lower() in ('cancelar', 'cancela', 'cancelá'):
        st.session_state['ia_wizard'] = None
        return "Listo, cancelé la carga."

    ok, valor = _parsear_respuesta_campo(campo, texto_usuario)
    if not ok:
        pista = ""
        if campo['tipo'] == 'monto':
            pista = " Decime solo el número (ej: 15000)."
        elif campo['tipo'] == 'numero':
            pista = " Decime un número entero (ej: 12)."
        elif campo['tipo'] == 'fecha':
            pista = " Usá el formato DD/MM/AAAA, o escribí 'hoy'."
        elif campo['tipo'] == 'opciones':
            pista = " Elegí uno de la lista, por número o por nombre."
        return f"No entendí ese valor.{pista}\n\n{_formatear_pregunta_campo(campo)}"

    wizard['datos'][campo['key']] = valor
    wizard['paso'] += 1

    if wizard['paso'] < len(campos):
        st.session_state['ia_wizard'] = wizard
        return _formatear_pregunta_campo(campos[wizard['paso']])

    st.session_state['ia_wizard'] = None
    st.session_state['ia_pendiente_registro'] = dict(tipo=tipo, datos=wizard['datos'])
    resumen = "\n".join(f"- **{c['label']}**: {wizard['datos'].get(c['key'], '')}" for c in campos)
    return (f"Listo, esto es lo que voy a guardar como **{_NOMBRE_TIPO_REGISTRO[tipo]}**:\n\n{resumen}\n\n"
            f"¿Confirmás? (respondé *sí* o *no*)")


def _guardar_registro(ctx, tipo, datos):
    fd = ctx.get('fd')
    supabase = ctx.get('supabase')
    user_id = ctx.get('user_id')
    if fd is None or supabase is None or user_id is None:
        return False, "No tengo conexión con Finanzas Personales desde acá."
    try:
        if tipo == 'ingreso':
            r = fd.insertar_ingreso(supabase, user_id, datos)
        elif tipo == 'gasto':
            r = fd.insertar_gasto(supabase, user_id, datos)
        elif tipo == 'deuda':
            r = fd.insertar_deuda(supabase, user_id, datos)
        elif tipo == 'inv_corto':
            r = fd.insertar_inv_corto(supabase, user_id, datos)
        elif tipo == 'inv_largo':
            r = fd.insertar_inv_largo(supabase, user_id, datos)
        elif tipo == 'trading':
            r = fd.insertar_trading(supabase, user_id, datos)
        elif tipo == 'objetivo':
            r = fd.insertar_objetivo(supabase, user_id, datos)
        else:
            return False, "Tipo de registro desconocido."
    except Exception as e:
        return False, f"Error inesperado al guardar: {e}"
    if r.get("ok"):
        return True, None
    return False, r.get("mensaje", "No se pudo guardar por un motivo desconocido.")


# ==============================================================
#  ADAPTADOR DE ESCRITURA — Finanzas Personales (flujo rápido de
#  una sola frase para Ingreso/Gasto: "anotá que gasté 5000 en comida")
# ==============================================================

def _registrar_movimiento_fd(ctx, tipo, monto, categoria, subcategoria, cuenta, descripcion, fecha):
    fd = ctx.get('fd')
    supabase = ctx.get('supabase')
    user_id = ctx.get('user_id')
    if fd is None or supabase is None or user_id is None:
        return False, "No tengo conexión con el módulo de Finanzas Personales desde acá."

    try:
        if tipo == 'gasto':
            r = fd.insertar_gasto(supabase, user_id, {
                "fecha": fecha, "descripcion": descripcion, "categoria": categoria,
                "subcategoria": subcategoria, "monto": monto, "cuenta": cuenta, "notas": "",
            })
        elif tipo == 'ingreso':
            r = fd.insertar_ingreso(supabase, user_id, {
                "fecha": fecha, "descripcion": descripcion, "categoria": categoria,
                "monto": monto, "cuenta": cuenta, "notas": "",
            })
        else:
            return False, "Las deudas necesitan más datos (acreedor, cuotas, vencimiento) — cargala directo en 💰 Finanzas → Deudas."
    except Exception as e:
        return False, f"Error inesperado al guardar: {e}"

    if r.get("ok"):
        return True, None
    return False, r.get("mensaje", "No se pudo guardar por un motivo desconocido.")


# ==============================================================
#  PERFIL DE PAÍS desde el CALENDARIO ECONÓMICO
#  Se activa cuando el mensaje nombra un país. Usa solo los eventos
#  COMPLETOS (previsto + anterior + real, sin None) con lectura,
#  y toma los más recientes.
# ==============================================================

_CAL_MAX_EVENTOS = 15      # cuántos datos completos recientes usa
_CAL_VENTANA_CICLO_DIAS = 180

_PAISES_ALIAS_CAL = {
    'eeuu': 'Estados Unidos', 'ee uu': 'Estados Unidos', 'united states': 'Estados Unidos',
    'uk': 'Reino Unido', 'gran bretana': 'Reino Unido', 'inglaterra': 'Reino Unido',
    'eurozona': 'Europa', 'zona euro': 'Europa', 'union europea': 'Europa',
    'holanda': 'Países Bajos', 'corea': 'Corea del Sur', 'republica checa': 'Chequia',
    'emiratos': 'Emiratos Árabes', 'arabia': 'Arabia Saudita',
}


def _limpiar_cal(s):
    s = re.sub(r'[^a-z0-9 ]', ' ', _norm(s))
    return re.sub(r'\s+', ' ', s).strip()


def _detectar_paises_calendario(texto):
    """Países del calendario nombrados en el mensaje (sin acentos, con alias)."""
    try:
        from modulo_calendario import PAISES
    except Exception:
        return []
    t = f' {_limpiar_cal(texto)} '
    mapa = {_limpiar_cal(p): p for p in PAISES}
    mapa.update(_PAISES_ALIAS_CAL)
    encontrados = []
    for clave in sorted(mapa, key=len, reverse=True):   # más largos primero
        patron = f' {clave} '
        if patron in t:
            encontrados.append(mapa[clave])
            t = t.replace(patron, ' ')                  # se "consume" lo ya matcheado
    if re.search(r'\bUSA\b', texto) and 'Estados Unidos' not in encontrados:
        encontrados.append('Estados Unidos')            # "usa" en minúscula es el verbo
    return list(dict.fromkeys(encontrados))


def _fmt_cal(v, unidad):
    try:
        x = float(v)
        txt = f'{x:,.2f}'.rstrip('0').rstrip('.')
    except Exception:
        return 'N/D'
    u = (unidad or '').strip()
    return f'{txt}{u}' if u in ('%', 'K', 'M', 'B') else (f'{txt} {u}' if u else txt)


def _perfil_calendario_pais(pais, ctx):
    supabase = ctx.get('supabase')
    if supabase is None:
        return f"No tengo conexión con el calendario económico para armar el perfil de **{pais}**."
    try:
        import modulo_calendario as mc
        df = mc._df_registros_procesado(supabase)
    except Exception as e:
        return f"⚠️ No pude leer el calendario económico: {e}"
    if df is None or df.empty:
        return "El calendario económico todavía no tiene eventos cargados."

    d = df[df['pais'] == pais]
    if d.empty:
        return f"Todavía no hay eventos del calendario económico cargados para **{pais}**."

    # Solo datos completos (sin None), con lectura de bueno/malo, y los más recientes
    completos = d.dropna(subset=['previsto', 'anterior', 'real', 'fecha_dt'])
    completos = completos[~completos['es_neutral']]
    completos = completos[completos['impacto_mercado'].fillna('').astype(str).str.strip() != '']
    if completos.empty:
        return (f"**{pais}** tiene eventos cargados, pero ninguno con previsto, anterior y real "
                f"completos y con lectura todavía.")

    rec = (completos.sort_values(['fecha_dt', 'peso'], ascending=[False, False])
                    .head(_CAL_MAX_EVENTOS))
    ultima = rec['fecha_dt'].max()

    L = [f"### 🗓️ Calendario económico — {pais}",
         f"_Perfil armado con los {len(rec)} datos completos más recientes "
         f"(previsto, anterior y real cargados), hasta el {ultima:%d/%m/%Y}._"]

    # ── Tabla de eventos ──
    L.append("\n| Fecha | Evento | Previsto | Anterior | Real | Lectura |\n|---|---|---|---|---|---|")
    for _, r in rec.iterrows():
        u = r.get('unidad') or ''
        evento = str(r['evento']).replace('|', '/')
        L.append(f"| {r['fecha_dt']:%d/%m/%Y} | {evento} | {_fmt_cal(r['previsto'], u)} | "
                 f"{_fmt_cal(r['anterior'], u)} | {_fmt_cal(r['real'], u)} | {r['impacto_mercado']} |")

    # ── Panorama por categoría ──
    L.append("\n**🧭 Panorama por categoría (sobre estos datos):**")
    filas_cat = []
    for cat in sorted(rec['categoria'].unique()):
        prom, n = mc._promedio_ponderado_score(rec[rec['categoria'] == cat])
        if prom is not None:
            filas_cat.append((cat, prom, n))
    for cat, prom, n in sorted(filas_cat, key=lambda x: x[1], reverse=True):
        emo, txt = mc._asset_verdict(prom)
        L.append(f"- **{cat}**: {emo} {txt} ({prom:+.2f}, {n} dato{'s' if n != 1 else ''})")

    # ── Impacto en activos ──
    L.append("\n**💹 Impacto en activos financieros:**")
    activos = mc._resumen_activos_pais(rec)
    for campo, nombre in mc.ASSET_FIELDS:
        score, n = activos.get(campo, (None, 0))
        emo, txt = mc._asset_verdict(score)
        L.append(f"- {nombre}: {emo} {txt}" + (f" ({score:+.2f})" if score is not None else ""))

    # ── Fase del ciclo y tasas (ventana reciente) ──
    punt = d[~d['es_neutral']].dropna(subset=['fecha_dt'])
    ventana = punt[punt['fecha_dt'] >= ultima - pd.Timedelta(days=_CAL_VENTANA_CICLO_DIAS)]
    try:
        fase = mc._fase_ciclo_economico(pais, ventana)
    except Exception:
        fase = None
    if fase:
        L.append(f"\n**🔄 Fase del ciclo:** {fase['nombre']} — {fase['resumen']}.")
    try:
        out = mc._outlook_tasas(ventana)
    except Exception:
        out = None
    if out:
        s = out[0]
        txt = ("sesgo a tasas más altas / sin apuro para recortar" if s >= 0.15 else
               "sesgo a tasas más bajas" if s <= -0.15 else "balance mixto, sin sesgo claro")
        L.append(f"**🏦 Tasas a futuro:** {txt} ({s:+.2f}).")

    # ── Lectura macro de los 3 datos más recientes ──
    L.append("\n**💬 Lectura de los datos más recientes:**")
    for _, r in rec.head(3).iterrows():
        lect = str(r.get('lectura_macro') or '').strip()
        if lect:
            L.append(f"- *{r['evento']}* ({r['fecha_dt']:%d/%m}): {lect[:220]}")
    return "\n".join(L)


def _responder_perfil_pais(paises, ctx):
    return "\n\n---\n\n".join(_perfil_calendario_pais(p, ctx) for p in paises[:2])


def _unir_perfil_pais(resp, paises, ctx):
    if not paises:
        return resp
    return f"{resp}\n\n---\n\n{_responder_perfil_pais(paises, ctx)}"


# ==============================================================
#  PAÍS COMPLETO (países que además son industria de acciones):
#  ETF + índice local + divisa + TODAS las acciones + calendario.
#  Para sumar otro país que también sea industria, agregalo acá
#  con su ETF, su índice y su par de divisa en Yahoo Finance.
# ==============================================================

_PAIS_COMPLETO = {
    'Argentina': dict(etf='ARGT', indice='^MERV', fx='USDARS=X'),
    'Brasil':    dict(etf='EWZ',  indice='^BVSP', fx='USDBRL=X'),
    'China':     dict(etf='FXI',  indice='^HSI',  fx='USDCNY=X'),
    'India':     dict(etf='INDA', indice='^NSEI', fx='USDINR=X'),
}


def _linea_corto(nombre, tk, ctx):
    """Una línea con los scores de corto plazo de un ticker."""
    r = _a_safe(_calc_corto, tk, ctx)
    if not r:
        return f"- **{nombre}** ({tk}): sin datos suficientes."
    fmt = ctx.get('fmt_precio') or (lambda p: f'{p:,.2f}')
    precio = fmt(r['precio']).replace('$', '\\$')   # Streamlit interpreta $...$ como fórmula
    return (f"- **{nombre}** ({tk}) {precio}: Acum {r['sa']:.0f} · Antic {r['sn']:.0f} · "
            f"Sent {r['ss']:.0f} → {r['señal']} · Ret 5d {_n(r['ret5'], 2, '%')} · "
            f"Ret 10d {_n(r['ret10'], 2, '%')}")


def _responder_pais_completo(pais, ctx):
    cfg = _PAIS_COMPLETO[pais]
    L = [f"# 🌎 {pais} — panorama completo"]

    # 1) ETF: análisis completo, igual que los demás países
    L.append(f"\n## 📦 ETF del país ({cfg['etf']})")
    L.append(_responder_analizar(cfg['etf'], ctx))

    # 2) Índice local + divisa
    L.append("\n---\n## 📈 Índice local y divisa")
    L.append(_linea_corto(f"Índice {pais}", cfg['indice'], ctx))
    L.append(_linea_corto(f"USD/{cfg['fx'][3:6]}", cfg['fx'], ctx))

    # 3) TODAS las acciones del país
    L.append("\n---\n## 🏭 Acciones")
    L.append(_responder_industria(pais, ctx, top=None))

    # 4) Calendario económico
    L.append("\n---")
    cal = _detectar_paises_calendario(pais)
    L.append(_responder_perfil_pais(cal, ctx) if cal
             else f"No encontré **{pais}** en el calendario económico.")
    return "\n".join(L)


# ==============================================================
#  RESPUESTAS
# ==============================================================

def responder(texto_usuario, ctx):
    universo = _universo_completo(ctx)

    # ── 0-bis) Plan de Trading (solo admin) ──
    if st.session_state.pop('ia_esperando_plan', False) and ctx.get('es_admin'):
        tks_p = extraer_tickers(texto_usuario, universo, ctx['validar_ticker'], ctx)
        if not tks_p:
            v_p = ctx['validar_ticker'](texto_usuario.strip())
            tks_p = [v_p] if v_p else []
        if tks_p:
            st.session_state['ia_ultimo_ticker'] = tks_p[0]
            return _responder_plan_trading(tks_p[0], ctx, texto_usuario)
        if len(texto_usuario.split()) <= 2:
            return "No reconocí ese símbolo. Probá con *NVDA*, *GGAL*, *BTC-USD*, *EUR/USD* o *oro*."

    if ctx.get('es_admin') and texto_usuario.strip().lower() in ('🎯 plan trading', 'plan trading', 'plan de trading'):
        st.session_state['ia_esperando_plan'] = True
        return ("¿Para qué activo armo el plan? Escribime el ticker o nombre (ej: *NVDA*, *BTC-USD*, *EUR/USD*). "
                "Podés agregar *capital 10000 riesgo 1%* o forzar un marco: *scalping*, *day trading* o *swing*.")

    # ── 0) ¿El asistente le preguntó qué ticker analizar? ──
    if st.session_state.pop('ia_esperando_ticker', False):
        tks = extraer_tickers(texto_usuario, universo, ctx['validar_ticker'], ctx)
        paises_0 = _detectar_paises_calendario(texto_usuario)
        if not tks and not paises_0:
            v = ctx['validar_ticker'](texto_usuario.strip())
            tks = [v] if v else []
        if tks:
            st.session_state['ia_ultimo_ticker'] = tks[0]
            return _unir_perfil_pais(_responder_analizar(tks[0], ctx), paises_0, ctx)
        if paises_0:
            return _responder_perfil_pais(paises_0, ctx)
        if len(texto_usuario.split()) <= 2:
            return "No reconocí ese símbolo. Probá con algo como *NVDA*, *GGAL*, *BTC-USD* o *oro*."
        # si escribió una frase larga, seguimos como mensaje normal

    # chip "📊 Analizar Acción": pregunta el ticker en vez de fallar
    if texto_usuario.strip().lower() in ('analizar acción', 'analizar accion', '📊 analizar acción'):
        st.session_state['ia_esperando_ticker'] = True
        return "¿Qué activo querés analizar? Escribime el ticker o el nombre (ej: *NVDA*, *GGAL*, *BTC-USD*, *oro*, *nasdaq*)."

    # ── 1) ¿Hay una confirmación pendiente de un movimiento a registrar? ──
    pendiente = st.session_state.get('ia_pendiente_mov')
    if pendiente:
        t = texto_usuario.lower().strip()
        if re.search(r'\b(s[ií]|confirmo|dale|ok|correcto|s[ií]\s+dale)\b', t):
            ok, err = _registrar_movimiento_fd(
                ctx, pendiente['tipo'], pendiente['monto'], pendiente['categoria'],
                pendiente.get('subcategoria', ''), pendiente.get('cuenta', 'Efectivo'),
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

    # ── 1.5) ¿Hay una pregunta pendiente de "¿qué tipo de movimiento es?"? ──
    pendiente_tipo = st.session_state.get('ia_pendiente_tipo')
    if pendiente_tipo:
        t = texto_usuario.lower().strip()
        tipo_resuelto = None
        if re.search(r'\b(1|ingreso)\b', t):
            tipo_resuelto = 'ingreso'
        elif re.search(r'\b(2|gasto)\b', t):
            tipo_resuelto = 'gasto'
        elif re.search(r'\b(3|deuda)\b', t):
            tipo_resuelto = 'deuda'

        st.session_state['ia_pendiente_tipo'] = None
        if tipo_resuelto:
            return _armar_pendiente_movimiento(
                tipo_resuelto, pendiente_tipo['texto'], pendiente_tipo['monto'], ctx,
            )
        # Si no contestó con una opción válida, dejamos que siga como mensaje normal.

    # ── 1.6) ¿Hay un registro completo (wizard) esperando confirmación? ──
    pendiente_reg = st.session_state.get('ia_pendiente_registro')
    if pendiente_reg:
        t = texto_usuario.lower().strip()
        if re.search(r'\b(s[ií]|confirmo|dale|ok|correcto)\b', t):
            ok, err = _guardar_registro(ctx, pendiente_reg['tipo'], pendiente_reg['datos'])
            st.session_state['ia_pendiente_registro'] = None
            nombre = _NOMBRE_TIPO_REGISTRO.get(pendiente_reg['tipo'], pendiente_reg['tipo'])
            if ok:
                return f"✅ Listo, guardé el **{nombre}**. Ya lo vas a ver reflejado en Finanzas Personales."
            return f"⚠️ No pude guardarlo. {err}"
        if re.search(r'\b(no|cancel[aá]|cancelar)\b', t):
            st.session_state['ia_pendiente_registro'] = None
            return "Listo, no registré nada."
        st.session_state['ia_pendiente_registro'] = None
        # sigue como mensaje nuevo

    # ── 1.7) ¿Hay un wizard de carga de datos (registro) en curso? ──
    if st.session_state.get('ia_wizard'):
        return _continuar_wizard(texto_usuario, ctx)

    # ── 1.75) ¿Hay un wizard de ARMADO DE CARTERA en curso? ──
    if st.session_state.get('ia_cartera_wizard'):
        return _continuar_wizard_cartera(texto_usuario, ctx)

    # ── 1.8) ¿Está esperando que elijas qué tipo de registro querés cargar? ──
    if st.session_state.get('ia_registro_menu_pendiente'):
        st.session_state['ia_registro_menu_pendiente'] = False
        tipo_sel = _resolver_tipo_menu(texto_usuario)
        if tipo_sel:
            return _iniciar_wizard(tipo_sel, ctx)
        st.session_state['ia_registro_menu_pendiente'] = True
        return "No identifiqué esa opción. " + _texto_menu_registro()

    intencion = detectar_intencion(texto_usuario)
    if intencion == 'plan_trading' and not ctx.get('es_admin'):
        intencion = 'analizar_ticker'     # para el resto de usuarios no existe
    tickers = extraer_tickers(texto_usuario, universo, ctx['validar_ticker'], ctx)
    paises_cal = (_detectar_paises_calendario(texto_usuario)
                  if intencion in ('analizar_ticker', 'ayuda') else [])

    industrias_validas = set(ctx.get('TICKER_INDUSTRY', {}).values())
    industria_detectada = _detectar_industria(texto_usuario, industrias_validas) if not tickers else None

    # Fallback al último ticker: solo en mensajes de más de una palabra
    # (si escribís una sola palabra que no reconoce, mejor decir que no la encontró).
    if (not tickers and not industria_detectada and not paises_cal
            and st.session_state.get('ia_ultimo_ticker')
            and len(texto_usuario.split()) > 1
            and intencion in ('analizar_ticker', 'simular', 'tdc', 'fscore', 'plan_trading')):
        tickers = [st.session_state['ia_ultimo_ticker']]
    # "anotá que gasté 5000 en café" no debe fijar KC=F como último ticker
    if tickers and intencion not in ('registrar_movimiento', 'finanzas'):
        st.session_state['ia_ultimo_ticker'] = tickers[0]

    if intencion == 'ayuda' and not tickers and not industria_detectada:
        return _respuesta_ayuda() + (_AYUDA_ADMIN if ctx.get('es_admin') else '')

    if intencion == 'sistema':
        return _respuesta_sistema()

    if intencion == 'plan_trading':
        if not tickers:
            st.session_state['ia_esperando_plan'] = True
            return ("¿Para qué activo armo el plan? Escribime el ticker o nombre "
                    "(ej: *NVDA*, *BTC-USD*, *EUR/USD*).")
        return _responder_plan_trading(tickers[0], ctx, texto_usuario)

    if intencion == 'registrar_movimiento':
        return _iniciar_registro_movimiento(texto_usuario, ctx)

    if intencion == 'armar_cartera_ia':
        return _iniciar_wizard_cartera(texto_usuario, ctx)

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

    if intencion == 'etfs' and not tickers:
        return _responder_etfs(ctx)
        
    if intencion == 'mercados' and not tickers:
        return _responder_mercados(texto_usuario, ctx)

    # Países que también son industria (Argentina, Brasil, China, India):
    # panorama completo en vez del top 6 de acciones.
    if (industria_detectada in _PAIS_COMPLETO and not tickers
            and intencion in ('analizar_ticker', 'ayuda')):
        return _responder_pais_completo(industria_detectada, ctx)

    if industria_detectada and not tickers:
        return _unir_perfil_pais(_responder_industria(industria_detectada, ctx), paises_cal, ctx)

    if intencion == 'oportunidades':
        return _responder_oportunidades(texto_usuario, ctx)

    if intencion == 'simular':
        if not tickers:
            return "¿Sobre qué activo querés simular la inversión? Decime el ticker."
        monto = extraer_monto(texto_usuario) or 1000
        periodo = extraer_periodo(texto_usuario)
        return _responder_simular(tickers[0], monto, periodo, ctx)

    if not tickers:
        if paises_cal:
            return _responder_perfil_pais(paises_cal, ctx)
        return ("No detecté ningún ticker en tu mensaje. Probá algo como *'analizame NVDA'*, "
                "*'compará YPF y GGAL'*, *'semiconductores'*, *'analizame el oro'*, *'EUR/USD'*, *'cómo están los granos'*, "
                "*'F-Score de KO'*, *'armame una cartera con semiconductores y bancos'*, "
                "*'anotá que gasté 5000 en comida'*, o *'qué significa el Sharpe'*. "
                "Escribí *ayuda* para ver todo lo que puedo hacer.")
    return _unir_perfil_pais(_responder_analizar(tickers[0], ctx), paises_cal, ctx)


def _respuesta_ayuda():
    return """¡Hola! 👋 Soy el asistente de Capital+. Puedo ayudarte con:

- **📊 Análisis COMPLETO de un activo** — *"analizame NVDA"*, *"cómo está el Bitcoin"*: junto corto plazo, largo plazo, Top-Down, fundamental, F-Score, régimen HMM y perfil de la empresa, y te dejo un resumen con un score compuesto
- **🌎 Panorama completo de un país** — *"Argentina"*, *"Brasil"*, *"China"*, *"India"*: análisis del ETF, índice local, divisa, todas las acciones del país y su calendario económico
- **🛢️ Commodities y cripto** — *"cómo están los granos"*, *"qué metales están baratos"*, *"analizame el oro"*, *"armame una cartera con oro, cripto y semiconductores"*
- **💱 Forex, ETFs e índices** — *"analizame EUR/USD"*, *"cómo está el nasdaq"*, *"analizame SPY"*, *"qué pares de forex hay"*
- **⚖️ Comparaciones** — *"comparar YPF vs GGAL"*
- **🎯 Oportunidades** — *"qué sectores están baratos"* (sectores y subsectores, 5 para comprar y 5 para vender), *"analizar ETFs"* (los más caros y los más baratos), *"qué países están baratos"*
- **🗓️ Perfil de un país (calendario económico)** — *"Estados Unidos"*, *"cómo está Japón"*: te muestro los datos más recientes con previsto, anterior y real, su lectura y el impacto en cada activo
- **📐 Top-Down Cuantitativo** — *"score de mediano plazo de AAPL"*
- **🧮 F-Score (Piotroski)** — *"F-Score de KO"*
- **📡 Salud del mercado** — *"cómo está la amplitud del mercado"*
- **📉 Renta Fija / Macro** — *"cómo están las tasas del Tesoro"*
- **🎲 Opciones** — *"explicame griegas"*, *"opciones de TSLA"*
- **🔄 Rotación y Pares** — *"scanner de pares"*
- **🧮 Optimizador de cartera** — *"optimizame una cartera con NVDA, AAPL y KO"*
- **🧩 Armar cartera automática** — *"armame una cartera con semiconductores y bancos"*: corro F-Score (con el mínimo/máximo que me digas), filtro por score cuantitativo de corto y largo plazo, y termino con el optimizador Monte Carlo — te doy las 5 carteras candidatas
- **💰 Tus finanzas** — *"cómo está mi presupuesto"*, *"cuánto debo"*
- **✍️ Registrar movimientos** — *"anotá que gasté 5000 en comida"*, *"registrá un ingreso de 200000 por sueldo"*, o simplemente escribí *"registrar"* para elegir entre Ingreso, Gasto, Deuda, Inversión Corto/Largo Plazo, Trading u Objetivo y te voy pidiendo los datos uno por uno (con botones para elegir opciones)
- **📐 Simulaciones** — *"si invierto 1000 en AAPL en el último año"*
- **📖 Glosario** — *"qué significa el Sharpe"*

Escribí *"qué módulos tiene la app"* para el mapa completo. ⚠️ Todo esto sale de datos reales de la app — no es asesoramiento financiero, son datos para que decidas vos."""


def _respuesta_sistema():
    return """Capital+ tiene estos módulos (todos accesibles desde la barra superior):

**Corto plazo** — Forex · Países · Sectores · Sub-sectores · Mercados (commodities/cripto) · Acciones por industria
**Largo plazo** — Ranking cuantitativo · Reversión a la media · Por industria · Ticker individual · Fundamental · Top-Down Cuantitativo (MP/LP) · COT · TFF
**Herramientas** — 🔍 Buscador universal · ⚖️ Comparador · 🧮 Optimizador de cartera · 📐 Promediador + Stop Loss · 📊 F-Score (Piotroski) · 📡 Salud del Mercado · 📉 Renta Fija y Macro · 🤖 este asistente (incluye armado de cartera automático)
**Trading** — 🔄 Rotación y Pares (mean reversion) · 🎯 Señales de Trading · 🎲 Valuación de Opciones
**Cuenta** — 💰 Finanzas Personales · 📆 Calendario Económico · 📰 Noticias

Preguntame por cualquiera de estos y te doy lo que pueda calcular directo acá, o te digo en qué sección de la app conviene abrirlo (por ejemplo, el Optimizador y el Scanner de Pares tienen muchos parámetros y conviene usarlos en su pantalla dedicada)."""


# ── Registro de movimientos en Finanzas ──────────────────────────

def _iniciar_registro_movimiento(texto, ctx):
    monto = extraer_monto(texto)
    if not monto:
        # Sin monto no hay forma de armar el registro rápido en una sola frase
        # (ej: click en el botón "Registrar"), así que mostramos el menú
        # completo de qué se puede cargar y arrancamos el wizard campo a campo.
        st.session_state['ia_registro_menu_pendiente'] = True
        return _texto_menu_registro()

    tipo = detectar_tipo_movimiento(texto)

    # Si es ambiguo, preguntamos en vez de adivinar mal.
    if tipo is None:
        st.session_state['ia_pendiente_tipo'] = dict(texto=texto, monto=monto)
        return (f"Detecté un monto de **${monto:,.2f}** pero no me quedó claro qué tipo de movimiento es. "
                f"¿Qué es?\n\n1️⃣ Ingreso\n2️⃣ Gasto\n3️⃣ Deuda\n\n"
                f"_(las deudas necesitan cargarse en 💰 Finanzas Personales → Deudas, tienen más campos)_")

    return _armar_pendiente_movimiento(tipo, texto, monto, ctx)


def _armar_pendiente_movimiento(tipo, texto, monto, ctx):
    if tipo == 'deuda':
        return ("Las deudas necesitan más datos que no puedo inferir de forma segura desde un mensaje "
                "(acreedor, cuotas, tasa, fecha de vencimiento) — cargala directo en "
                "💰 Finanzas Personales → Deudas, tiene un formulario para eso.")

    categoria = extraer_categoria(texto, tipo)
    cuenta = extraer_cuenta(texto, tipo)
    fecha = extraer_fecha(texto)

    subcategoria = ''
    if tipo == 'gasto':
        fd = ctx.get('fd')
        subs = fd.SUBCATEGORIAS_GASTOS.get(categoria, []) if fd else []
        subcategoria = 'Otros' if 'Otros' in subs else (subs[0] if subs else '')

    st.session_state['ia_pendiente_mov'] = dict(
        tipo=tipo, monto=monto, categoria=categoria, subcategoria=subcategoria,
        cuenta=cuenta, descripcion=texto, fecha=fecha,
    )
    signo = {'gasto': '🔴', 'ingreso': '🟢'}.get(tipo, '⚪')
    extra = f" (subcategoría: {subcategoria})" if subcategoria else ""
    return (f"{signo} Voy a registrar un **{tipo}** de **${monto:,.2f}** en **{categoria}**{extra}, "
            f"cuenta **{cuenta}** ({fecha}). ¿Confirmás? (respondé *sí* o *no*)")


def _responder_finanzas(ctx):
    fd = ctx.get('fd')
    supabase = ctx.get('supabase')
    user_id = ctx.get('user_id')
    if fd is None or supabase is None or user_id is None:
        return "No tengo conexión con tus datos de Finanzas Personales desde acá."

    hoy = date.today()
    inicio, fin = fd.rango_mes(hoy.year, hoy.month)
    try:
        d = fd.obtener_dashboard_data(supabase, user_id, inicio, fin)
    except Exception as e:
        return f"⚠️ No pude leer tus datos de Finanzas Personales: {e}"

    if not d or (d.get('ingresos', 0) == 0 and d.get('gastos', 0) == 0 and d.get('deudas', 0) == 0):
        return ("Todavía no veo movimientos cargados este mes. Podés decirme algo como "
                "*'anotá que gasté 5000 en comida'* para empezar, o ir directo a 💰 Finanzas Personales.")

    partes = [f"**Tu resumen financiero — {MESES_ES[hoy.month-1]} {hoy.year}**\n"]
    partes.append(f"- 📥 Ingresos: ${d['ingresos']:,.2f}  ·  📤 Gastos: ${d['gastos']:,.2f}")
    signo_bal = "🟢" if d['balance'] >= 0 else "🔴"
    partes.append(f"- {signo_bal} Balance: ${d['balance']:,.2f}  ·  Tasa de ahorro: {d['tasa_ahorro']}")

    if d.get('deudas', 0) > 0:
        partes.append(f"- 💳 Deudas activas: ${d['deudas']:,.2f} ({d.get('deuda_max','')})  ·  "
                       f"Próx. vencimiento: {d.get('proximo_vencimiento','')}")

    if d.get('inv_corto', 0) or d.get('inv_largo', 0):
        partes.append(f"- 📈 Inversiones: ${d.get('inv_corto',0)+d.get('inv_largo',0):,.2f} "
                       f"(ganancia/pérdida: ${d.get('ganancia',0):,.2f}, {d.get('rendimiento','0%')})")

    if d.get('abiertas', 0) or d.get('trading_pnl', 0):
        partes.append(f"- ⚡ Trading: P&L realizado ${d.get('trading_pnl',0):,.2f}  ·  "
                       f"Win rate {d.get('win_rate','0%')}  ·  {d.get('abiertas',0)} operación(es) abierta(s)")

    if d.get('obj_activos', 0):
        partes.append(f"- 🎯 Objetivos activos: {d['obj_activos']}  ·  Ahorrado ${d.get('obj_ahorrado',0):,.2f}  ·  "
                       f"Falta ${d.get('obj_faltante',0):,.2f}  ·  Más próximo: {d.get('obj_proximo','')}")

    try:
        alertas = fd.obtener_alertas(supabase, user_id)
    except Exception:
        alertas = []
    if alertas:
        urgentes = [a for a in alertas if a['nivel'] in ('error', 'warning')][:3]
        if urgentes:
            partes.append("\n**⚠️ Alertas:**")
            for a in urgentes:
                partes.append(f"- {a['icono']} {a['mensaje']}")
            if len(alertas) > len(urgentes):
                partes.append(f"_...y {len(alertas) - len(urgentes)} más en la sección de Finanzas._")

    return "\n".join(partes)


# ==============================================================
#  HELPERS DE VELOCIDAD — pool con contexto de Streamlit, F-Score
#  cacheado y cálculos por módulo (para correr en paralelo)
# ==============================================================

def _pool_con_ctx(max_workers):
    """ThreadPool cuyos hilos conservan el contexto de Streamlit
    (necesario para st.cache_data / st.session_state dentro de los hilos)."""
    if add_script_run_ctx is None or get_script_run_ctx is None:
        return ThreadPoolExecutor(max_workers=max_workers)
    ctx_st = get_script_run_ctx()

    def _init():
        add_script_run_ctx(threading.current_thread(), ctx_st)

    return ThreadPoolExecutor(max_workers=max_workers, initializer=_init)


def _a_safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:
        return None


def _calc_corto(tk, ctx):
    df_v = ctx['descargar_datos'](tk, '3mo')
    df_m = ctx['descargar_datos'](tk, '1mo')
    if df_v is None or df_m is None:
        return None
    cl_v = ctx['get_close_series'](df_v)
    cl_m = ctx['get_close_series'](df_m)
    if cl_v is None or cl_m is None or len(cl_v.dropna()) < 15:
        return None
    atr = ctx['calcular_atr'](df_m)
    sa, sn, ss = ctx['scores_corto'](cl_v, cl_m, atr)
    rsi = None
    if ctx.get('calcular_rsi'):
        rsi = _a_safe(lambda: float(ctx['calcular_rsi'](cl_m, p=7).iloc[-1]))
    return dict(
        sa=sa, sn=sn, ss=ss, sf=sa * 0.45 + sn * 0.35 + ss * 0.20,
        señal=ctx['señal_accion_corto'](sa, sn, ss), precio=float(cl_m.iloc[-1]), rsi=rsi,
        ret5=float(cl_m.pct_change(5).iloc[-1] * 100) if len(cl_m) >= 6 else None,
        ret10=float(cl_m.pct_change(10).iloc[-1] * 100) if len(cl_m) >= 11 else None,
    )


def _calc_hmm(tk, ctx):
    if not ctx.get('calcular_regimen_hmm'):
        return None
    df_6 = ctx['descargar_datos'](tk, '6mo')
    cl_6 = ctx['get_close_series'](df_6) if df_6 is not None else None
    return ctx['calcular_regimen_hmm'](cl_6) if cl_6 is not None else None


def _calc_largo(tk, ctx):
    df_l = ctx['descargar_datos'](tk, '2y')
    cl_l = ctx['get_close_series'](df_l) if df_l is not None else None
    if cl_l is not None and len(cl_l) >= 150:
        return ctx['analizar_largo'](tk, cl_l)
    return None

# ==============================================================
#  PLAN DE TRADING (solo admin) — marco temporal + SL/TP
#  Usa TODO el sistema: corto, largo, TDC, HMM, F-Score, ATR y GEX.
#  Con datos DIARIOS: los niveles de scalping/day son estimaciones
#  sobre ATR; confirmar en gráfico intradía.
# ==============================================================

_TF_CFG = {
    'scalping': dict(nombre='Scalping', icono='⚡', sl=0.20, tp1=0.30, tp2=0.50,
                     dur='minutos a pocas horas, cerrando el mismo día'),
    'day':      dict(nombre='Day Trading', icono='🌅', sl=0.50, tp1=1.00, tp2=1.50,
                     dur='intradía, cerrando antes del cierre de la rueda'),
    'swing':    dict(nombre='Swing Trading', icono='🌊', sl=1.50, tp1=3.00, tp2=4.50,
                     dur='de varios días a unas semanas'),
}

_AYUDA_ADMIN = ("\n\n**🔐 Solo admin — 🎯 Plan de Trading** — *\"plan de trading de NVDA\"*, *\"scalping de BTC\"*, "
                "*\"swing de GGAL capital 10000 riesgo 1%\"*: uso todo el sistema para decirte qué marco temporal "
                "conviene (scalping / day trading / swing) con entrada, stop loss y take profit.")


def _fmt_px(p):
    if p is None:
        return 'N/D'
    p = float(p)
    if abs(p) >= 1000: return f'{p:,.2f}'
    if abs(p) >= 10:   return f'{p:.2f}'
    if abs(p) >= 1:    return f'{p:.4f}'
    return f'{p:.5f}'


def _mix(pares):
    v = [(x, w) for x, w in pares if x is not None]
    if not v:
        return None
    tw = sum(w for _, w in v)
    return sum(x * w for x, w in v) / tw


def _dir_de(b):
    if b is None: return 'NEUTRAL'
    return 'LARGO' if b >= 0.15 else ('CORTO' if b <= -0.15 else 'NEUTRAL')


def _recolectar_trading(tk, ctx):
    sin_fund = _es_sin_fundamentals(tk, ctx)
    fn_tdc, hz_cfg = ctx.get('_tdc_analizar_ticker'), ctx.get('HORIZONTES_TDC')
    with _pool_con_ctx(10) as ex:
        f_fs = None if sin_fund else ex.submit(_car_fscore_rapido, tk)
        f_gex = ex.submit(_a_safe, ctx['gex_niveles'], tk) if ctx.get('gex_niveles') else None
        periodos = ['3mo', '1mo', '6mo', '2y'] + (['10y'] if fn_tdc else [])
        for f in [ex.submit(_a_safe, ctx['descargar_datos'], tk, p) for p in periodos]:
            f.result()
        f_corto = ex.submit(_a_safe, _calc_corto, tk, ctx)
        f_hmm = ex.submit(_a_safe, _calc_hmm, tk, ctx)
        f_largo = ex.submit(_a_safe, _calc_largo, tk, ctx)
        f_tdc = {hz: ex.submit(_a_safe, fn_tdc, tk, hz_cfg[hz])
                 for hz in ('MP', 'LP') if fn_tdc and hz_cfg and hz in hz_cfg}

    df_v = _a_safe(ctx['descargar_datos'], tk, '3mo')
    if df_v is None or df_v.empty:
        return None
    atr_s = _a_safe(ctx['calcular_atr'], df_v)
    atr_s = pd.Series(atr_s).dropna() if atr_s is not None else pd.Series(dtype=float)
    if atr_s.empty or float(atr_s.iloc[-1]) <= 0:
        return None

    tdc = {}
    for hz, f in f_tdc.items():
        r = f.result()
        if r:
            tdc[hz] = r
    rc, rl = f_corto.result(), f_largo.result()
    cl = _a_safe(ctx['get_close_series'], df_v)
    precio = (rc or {}).get('precio') or (rl or {}).get('precio') or (float(cl.iloc[-1]) if cl is not None else None)
    if not precio:
        return None
    hi20 = lo20 = None
    try:
        hi20, lo20 = float(df_v['High'].tail(20).max()), float(df_v['Low'].tail(20).min())
    except Exception:
        pass
    return dict(rc=rc, rl=rl, hmm=f_hmm.result(), tdc=tdc, gex=f_gex.result() if f_gex else None,
                fscore=f_fs.result() if f_fs else None, atr=float(atr_s.iloc[-1]),
                precio=float(precio), hi20=hi20, lo20=lo20, sin_fund=sin_fund)


def _niveles_estructurales(d):
    """[(precio_nivel, etiqueta)] de soportes/resistencias reales del activo."""
    L = []
    rl, gex, precio = d['rl'], d['gex'], d['precio']
    if rl:
        for k, lab in (('ma20', 'Media de 20 ruedas'), ('lower_bb', 'Banda de Bollinger inferior'),
                       ('upper_bb', 'Banda de Bollinger superior')):
            if rl.get(k):
                L.append((float(rl[k]), lab))
    if d.get('hi20'): L.append((d['hi20'], 'Máximo de 20 ruedas'))
    if d.get('lo20'): L.append((d['lo20'], 'Mínimo de 20 ruedas'))
    # Niveles GEX: solo si son del propio activo (con proxy el precio no es comparable)
    if gex and gex.get('spot') and not gex.get('proxy'):
        f = precio / gex['spot']
        for k, lab in (('call_wall', 'Pared de Calls'), ('put_wall', 'Pared de Puts'),
                       ('flip', 'Punto de cambio de gamma')):
            if gex.get(k):
                L.append((float(gex[k]) * f, lab))
        niv = gex.get('niveles')
        if niv is not None and not niv.empty:
            for _, r in niv.iterrows():
                if r['tipo'] in ('Resistencia', 'Soporte', 'Pivote'):
                    L.append((float(r['strike']) * f, f"{r['tipo']} de gamma"))
    return L


def _plan_niveles(direccion, precio, atr, niveles, cfg):
    s = 1 if direccion == 'LARGO' else -1
    k_sl, k1, k2 = cfg['sl'], cfg['tp1'], cfg['tp2']
    notas = []

    # ── Stop loss: ATR, ajustado detrás de un nivel real si hay uno en la zona ──
    sl = precio - s * k_sl * atr
    base_sl = f"{k_sl:g}×ATR"
    cand = [(lv, lab) for lv, lab in niveles
            if 0.7 * k_sl * atr <= s * (precio - lv) <= 1.4 * k_sl * atr]
    if cand:
        lv, lab = min(cand, key=lambda x: abs(s * (precio - x[0]) - k_sl * atr))
        sl = lv - s * 0.15 * atr
        base_sl = f"{'debajo' if s > 0 else 'encima'} de {lab} ({_fmt_px(lv)})"

    # ── Take profits: ATR, frenados antes del primer obstáculo ──
    tp1 = precio + s * k1 * atr
    tp2 = precio + s * k2 * atr
    obst = sorted([(s * (lv - precio), lv, lab) for lv, lab in niveles
                   if 0.5 * k1 * atr <= s * (lv - precio) < k2 * atr])
    if obst:
        dist, lv, lab = obst[0]
        if dist < k1 * atr:
            tp1 = lv - s * 0.05 * atr
            notas.append(f"TP1 limitado por {lab} ({_fmt_px(lv)}); TP2 exige romperlo")
        else:
            dist2 = max(dist - 0.05 * atr, k1 * atr * 1.1)
            tp2 = precio + s * dist2
            notas.append(f"TP2 limitado por {lab} ({_fmt_px(lv)})")

    riesgo = abs(precio - sl)
    r1, r2 = abs(tp1 - precio) / riesgo, abs(tp2 - precio) / riesgo
    if r1 < 1.0:
        notas.append("⚠️ R:R de TP1 menor a 1: el recorrido hasta el primer obstáculo no compensa el riesgo")
    elif r2 < 1.5:
        notas.append("⚠️ R:R de TP2 bajo (<1.5): setup poco atractivo")
    return dict(dir=direccion, entrada=precio, sl=sl, base_sl=base_sl, tp1=tp1, tp2=tp2,
                riesgo=riesgo, r1=r1, r2=r2, notas=notas)


def _responder_plan_trading(tk, ctx, texto=''):
    d = _recolectar_trading(tk, ctx)
    if d is None:
        return (f"No pude calcular el plan de **{tk}**: faltan precios o ATR suficientes. "
                f"Verificá el símbolo.")
    rc, rl, hmm, tdc, gex, fscore = d['rc'], d['rl'], d['hmm'], d['tdc'], d['gex'], d['fscore']
    precio, atr = d['precio'], d['atr']
    atr_pct = atr / precio * 100

    # ── Opciones del mensaje ──
    t = _norm(texto)
    forzado = ('scalping' if re.search(r'scalp', t) else
               'day' if re.search(r'day\s*-?\s*trad|intradia', t) else
               'swing' if re.search(r'swing', t) else None)
    m_cap = re.search(r'capital\s*(?:de\s*)?(\d[\d\.,]*)', t)
    capital = extraer_monto(m_cap.group(1)) if m_cap else None
    m_r = (re.search(r'riesg\w*\s*(?:del?\s*)?(\d+(?:[.,]\d+)?)\s*%', t)
           or re.search(r'(\d+(?:[.,]\d+)?)\s*%\s*de\s*riesgo', t))
    riesgo_pct = float(m_r.group(1).replace(',', '.')) if m_r else (1.0 if capital else None)

    # ── Componentes direccionales (-1 bajista … +1 alcista) ──
    corto_dir = (rc['sf'] - 50) / 50 if rc else None
    largo_dir = (rl['global_score'] - 50) / 50 if rl else None
    hmm_dir = ({'ALCISTA': 1, 'BAJISTA': -1}.get(hmm['regimen'], 0) * hmm['prob'] / 100) if hmm else None
    tdc_dir = (float(np.mean([x['sf'] for x in tdc.values()])) - 50) / 50 if tdc else None
    macd_dir = (1 if rl['macd_bull'] else -1) if rl else None
    tec = (((1 if rl['golden_cross'] else -1) + macd_dir) / 2) if rl else None
    mom = None
    if rc and rc.get('ret5') is not None:
        mom = max(-1.0, min(1.0, rc['ret5'] / (3 * atr_pct)))

    bias = {
        'scalping': _mix([(mom, .35), (corto_dir, .25), (macd_dir, .20), (hmm_dir, .20)]),
        'day':      _mix([(corto_dir, .30), (mom, .20), (tec, .20), (hmm_dir, .15), (largo_dir, .15)]),
        'swing':    _mix([(largo_dir, .30), (tdc_dir, .25), (tec, .20), (hmm_dir, .15), (corto_dir, .10)]),
    }
    dirs = {k: _dir_de(v) for k, v in bias.items()}

    # ── Qué tan adecuado es cada marco (0-100) ──
    razones = {k: [] for k in _TF_CFG}
    gamma_pos = bool(gex and gex.get('regimen') == 'positivo')
    pivote_cerca = False
    if gex and not gex.get('proxy') and gex.get('niveles') is not None and not gex['niveles'].empty:
        pv = gex['niveles'][gex['niveles']['tipo'] == 'Pivote']
        pivote_cerca = bool((pv['dist_pct'].abs() <= 1.0).any()) if not pv.empty else False

    sc = 20
    if atr_pct >= 2:   sc += 25; razones['scalping'].append(f"ATR diario {atr_pct:.1f}%: rango intradía amplio")
    elif atr_pct >= 1: sc += 12; razones['scalping'].append(f"ATR diario {atr_pct:.1f}%: rango intradía aceptable")
    elif atr_pct < 0.6: sc -= 20; razones['scalping'].append(f"ATR {atr_pct:.2f}%: el rango no cubre costos de operar")
    if gex:
        if gamma_pos: sc += 15; razones['scalping'].append("Gamma positiva: el precio tiende a oscilar en rango")
        else:         sc -= 10; razones['scalping'].append("Gamma negativa: movimientos bruscos, mal contexto para scalping")
        if gex.get('inminente'): sc -= 15; razones['scalping'].append("Squeeze inminente: riesgo de ruptura violenta")
    if pivote_cerca: sc += 10; razones['scalping'].append("Pivote de gamma pegado al precio (efecto ancla)")
    if rl and rl['hurst'] < 0.5: sc += 10; razones['scalping'].append(f"Hurst {rl['hurst']:.2f}: comportamiento reversivo")
    if bias['scalping'] is None or abs(bias['scalping']) < 0.15:
        sc -= 15; razones['scalping'].append("Sin sesgo direccional claro de muy corto plazo")
    sc = max(0, min(70, sc))   # tope: no hay datos intradía

    dy = 35
    if 1 <= atr_pct <= 4: dy += 20; razones['day'].append(f"ATR {atr_pct:.1f}%: volatilidad ideal para intradía")
    elif atr_pct > 4:     dy += 5;  razones['day'].append(f"ATR {atr_pct:.1f}%: muy alto, ojo con gaps y ruido")
    else:                 dy -= 15; razones['day'].append(f"ATR {atr_pct:.2f}%: poco movimiento diario")
    if rc and rc['sn'] >= 65: dy += 15; razones['day'].append(f"Anticipación {rc['sn']:.0f}: movimiento inminente")
    if gex and (gex.get('regimen') == 'negativo' or gex.get('squeeze_score', 0) >= 50):
        dy += 10; razones['day'].append("Gamma negativa / squeeze elevado: favorece tendencia intradía")
    if bias['day'] is not None and abs(bias['day']) >= 0.3:
        dy += 10; razones['day'].append("Sesgo direccional claro de corto plazo")
    if dirs['day'] == dirs['swing'] != 'NEUTRAL':
        dy += 10; razones['day'].append("Dirección alineada con el swing")
    dy = max(0, min(100, dy))

    sw = 40
    if rl is None: sw -= 30; razones['swing'].append("Historial insuficiente para largo plazo")
    ab = abs(bias['swing']) if bias['swing'] is not None else 0
    if ab >= 0.3:    sw += 20; razones['swing'].append(f"Sesgo de fondo claro ({bias['swing']:+.2f})")
    elif ab >= 0.15: sw += 10; razones['swing'].append(f"Sesgo de fondo moderado ({bias['swing']:+.2f})")
    else:            sw -= 10; razones['swing'].append("Sin dirección clara de fondo")
    if rl and rl['hurst'] > 0.55: sw += 10; razones['swing'].append(f"Hurst {rl['hurst']:.2f}: tendencia persistente")
    if corto_dir is not None and largo_dir is not None:
        if corto_dir * largo_dir > 0 and min(abs(corto_dir), abs(largo_dir)) > 0.1:
            sw += 15; razones['swing'].append("Corto y largo plazo alineados")
        elif corto_dir * largo_dir < 0 and min(abs(corto_dir), abs(largo_dir)) > 0.15:
            sw -= 15; razones['swing'].append("Corto y largo plazo se contradicen")
    if hmm and ((hmm['regimen'] == 'ALCISTA' and dirs['swing'] == 'LARGO')
                or (hmm['regimen'] == 'BAJISTA' and dirs['swing'] == 'CORTO')):
        sw += 10; razones['swing'].append(f"Régimen HMM {hmm['regimen'].lower()} a favor ({hmm['prob']}%)")
    if fscore is not None and dirs['swing'] == 'LARGO':
        if fscore >= 6:   sw += 5;  razones['swing'].append(f"F-Score {fscore:.1f}/9: negocio sólido")
        elif fscore <= 3: sw -= 10; razones['swing'].append(f"F-Score {fscore:.1f}/9: calidad financiera baja")
    if atr_pct > 6: sw -= 10; razones['swing'].append(f"ATR {atr_pct:.1f}%: volatilidad muy alta para swing")
    sw = max(0, min(100, sw))
    puntaje = {'scalping': sc, 'day': dy, 'swing': sw}

    # ── Elegir marco ──
    if forzado:
        elegido = forzado
    else:
        direccionales = [k for k in puntaje if dirs[k] != 'NEUTRAL']
        pool = direccionales or list(puntaje)
        elegido = max(pool, key=lambda k: puntaje[k])

    niveles = _niveles_estructurales(d)
    planes = {k: (_plan_niveles(dirs[k], precio, atr, niveles, _TF_CFG[k]) if dirs[k] != 'NEUTRAL' else None)
              for k in _TF_CFG}

    # ══ Armado de la respuesta ══
    cfg = _TF_CFG[elegido]
    dir_e, plan = dirs[elegido], planes[elegido]
    b = bias[elegido]
    conv = 'ALTA' if b is not None and abs(b) >= .5 else ('MEDIA' if b is not None and abs(b) >= .3 else 'BAJA')
    nombre = (_info_mercado(tk, ctx) or (tk,))[0]
    L = [f"## 🎯 Plan de Trading — {nombre} ({tk})",
         f"_Precio {_fmt_px(precio)} · ATR(14) {_fmt_px(atr)} ({atr_pct:.2f}% diario) · 🔐 solo admin_"]

    if plan:
        flecha = '🟢 COMPRA (largo)' if dir_e == 'LARGO' else '🔴 VENTA (corto)'
        L.append(f"\n### {cfg['icono']} Marco recomendado: **{cfg['nombre']}** — {flecha}\n"
                 f"Convicción **{conv}** · adecuación del marco **{puntaje[elegido]}/100** · "
                 f"duración típica: {cfg['dur']}." + (" _(marco elegido por vos)_" if forzado else ""))
    else:
        L.append(f"\n### ⏸️ Sin ventaja direccional en {cfg['nombre']}\n"
                 f"Las señales del sistema no se inclinan con claridad (sesgo {b:+.2f}). "
                 f"Lo prudente es **esperar**." if b is not None else
                 f"\n### ⏸️ Sin datos suficientes para definir dirección")
        k = cfg['sl'] / 3 * atr
        L.append(f"Disparadores a vigilar: compra si cierra sobre **{_fmt_px(precio + k)}**, "
                 f"venta si cierra bajo **{_fmt_px(precio - k)}**.")

    # Tabla de los 3 marcos
    L.append("\n**📊 Los 3 marcos temporales:**\n")
    L.append("| Marco | Adecuación | Dirección | Entrada | Stop Loss | TP1 | TP2 | R:R (TP1 / TP2) |\n|---|---|---|---|---|---|---|---|")
    for k, c in _TF_CFG.items():
        p = planes[k]
        marca = ' ⭐' if k == elegido else ''
        if p:
            ico = '🟢 Largo' if p['dir'] == 'LARGO' else '🔴 Corto'
            L.append(f"| {c['icono']} {c['nombre']}{marca} | {puntaje[k]}/100 | {ico} | {_fmt_px(p['entrada'])} | "
                     f"{_fmt_px(p['sl'])} | {_fmt_px(p['tp1'])} | {_fmt_px(p['tp2'])} | "
                     f"{p['r1']:.1f} / {p['r2']:.1f} |")
        else:
            L.append(f"| {c['icono']} {c['nombre']}{marca} | {puntaje[k]}/100 | ⏸️ Neutral | — | — | — | — | — |")

    # Detalle del plan elegido
    if plan:
        pct = lambda x: abs(x - precio) / precio * 100
        L.append(f"\n**🧭 Plan {cfg['nombre']} paso a paso:**")
        L.append(f"- **Entrada:** {_fmt_px(plan['entrada'])} (precio actual)")
        L.append(f"- **Stop loss:** {_fmt_px(plan['sl'])} (-{pct(plan['sl']):.2f}%) — {plan['base_sl']}")
        L.append(f"- **Take profit 1:** {_fmt_px(plan['tp1'])} (+{pct(plan['tp1']):.2f}%) · R:R {plan['r1']:.1f}")
        L.append(f"- **Take profit 2:** {_fmt_px(plan['tp2'])} (+{pct(plan['tp2']):.2f}%) · R:R {plan['r2']:.1f}")
        for n in plan['notas']:
            L.append(f"- {n}")
        if elegido == 'swing' and rl:
            if dir_e == 'LARGO' and (rl['rsi'] > 70 or (rl.get('upper_bb') and precio >= rl['upper_bb'])) and rl.get('ma20'):
                L.append(f"- 💡 Está extendido (RSI {rl['rsi']:.0f}): mejor entrada alternativa en un retroceso hacia "
                         f"**{_fmt_px(rl['ma20'])}** (media de 20).")
            if dir_e == 'CORTO' and (rl['rsi'] < 30 or (rl.get('lower_bb') and precio <= rl['lower_bb'])) and rl.get('ma20'):
                L.append(f"- 💡 Está sobrevendido (RSI {rl['rsi']:.0f}): mejor entrada alternativa en un rebote hacia "
                         f"**{_fmt_px(rl['ma20'])}**.")
        if elegido == 'swing':
            L.append("- **Gestión:** al llegar a TP1 cerrá ~50% y llevá el stop a la entrada (break-even); el resto apunta a TP2. "
                     "Invalidación: cierre diario más allá del stop.")
        else:
            L.append("- **Gestión:** al llegar a TP1 cerrá ~50% y llevá el stop a break-even. "
                     "Cerrá todo antes del cierre de la rueda; no lo dejes pasar la noche.")
        if dir_e == 'CORTO':
            L.append("- ⚠️ Operar en corto requiere margen o CFDs y expone a pérdidas mayores al capital.")
        if capital and riesgo_pct:
            r_usd = capital * riesgo_pct / 100
            unid = r_usd / plan['riesgo']
            valor = unid * plan['entrada']
            txt = (f"\n**💼 Tamaño de posición:** capital {capital:,.0f} · riesgo {riesgo_pct:g}% = {r_usd:,.2f} "
                   f"→ ≈ **{unid:,.4f} unidades** (posición ≈ {valor:,.0f}, {valor / capital * 100:.0f}% del capital).")
            if valor > capital:
                txt += f" ⚠️ Requiere apalancamiento ≈ {valor / capital:.1f}x."
            L.append(txt)
        else:
            L.append("\n_Tip: sumá «capital 10000 riesgo 1%» al mensaje y te calculo el tamaño de la posición._")

    # Por qué
    L.append(f"\n**🧠 Por qué {cfg['nombre']}:**")
    for r in razones[elegido][:6]:
        L.append(f"- {r}")
    if not razones[elegido]:
        L.append("- Sin factores destacados a favor ni en contra.")

    # Contexto de todo el sistema
    ctx_l = []
    if rc: ctx_l.append(f"Corto: Acum {rc['sa']:.0f} · Antic {rc['sn']:.0f} → {rc['señal']}")
    if rl: ctx_l.append(f"Largo: Global {int(rl['global_score'])}/100 ({rl['sesgo']}) · RSI {rl['rsi']:.0f} · Hurst {rl['hurst']:.2f}")
    if tdc:  ctx_l.append("TDC: " + " · ".join(f"{hz} {x['sf']:.0f}/100" for hz, x in tdc.items()))
    if hmm:  ctx_l.append(f"HMM: {hmm['regimen']} ({hmm['prob']}%)")
    if fscore is not None: ctx_l.append(f"F-Score: {fscore:.1f}/9")
    if gex:
        g = f"Gamma {gex['regimen']} · Squeeze {gex['squeeze_score']:.0f}/100"
        if gex.get('proxy'):
            g += f" (medido en {gex['simbolo']}; sus niveles no se usan para SL/TP)"
        ctx_l.append(g)
    L.append("\n**🔎 Señales del sistema usadas:** " + " | ".join(ctx_l))

    # Conflictos entre marcos
    activas = {dirs[k] for k in dirs if dirs[k] != 'NEUTRAL'}
    if len(activas) > 1:
        L.append("\n⚠️ **Marcos en conflicto:** el corto plazo y el largo plazo apuntan a lados opuestos. "
                 "Operá solo el marco elegido y no mezcles posiciones.")

    L.append("\n---\n*Los niveles se calculan sobre datos **diarios** (ATR y estructura); para scalping y day trading "
             "confirmá la entrada en un gráfico de 1–15 min. Revisá también el calendario económico y los resultados "
             "de la empresa antes de operar. Es un cálculo cuantitativo, no asesoramiento financiero.*")
    return "\n".join(L)

# ── Análisis COMPLETO de ticker (todos los módulos + resumen) ────

def _n(v, d=2, suf=''):
    try:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return 'N/D'
        return f'{float(v):,.{d}f}{suf}'
    except Exception:
        return 'N/D'


def _pf(v, d=1):
    """Fracción (0.25) -> '25.0%'."""
    return 'N/D' if v is None else _n(float(v) * 100, d, '%')


def _big(v):
    if v is None:
        return 'N/D'
    av = abs(v)
    for lim, suf in ((1e12, 'T'), (1e9, 'B'), (1e6, 'M')):
        if av >= lim:
            return f'{v / lim:.2f}{suf}'
    return f'{v:,.0f}'


def _veredicto_compuesto(score):
    if score >= 70: return '🟢 PERFIL FAVORABLE'
    if score >= 55: return '🟢 MODERADAMENTE FAVORABLE'
    if score >= 45: return '🟡 NEUTRAL / MIXTO'
    if score >= 30: return '🟠 PERFIL DÉBIL'
    return '🔴 PERFIL DESFAVORABLE'


def _s10(v):
    """Score 0-10 -> entero 'N/10'."""
    return 'N/D' if v is None else f'{round(float(v))}/10'

_REC_ES = {
    'strong_buy': '🟢 Compra fuerte', 'buy': '🟢 Compra', 'hold': '🟡 Mantener',
    'underperform': '🟠 Rendimiento inferior', 'sell': '🔴 Venta',
    'strong_sell': '🔴 Venta fuerte', 'none': 'Sin cobertura',
}


def _rec_es(k):
    if not k:
        return 'N/D'
    return _REC_ES.get(str(k).lower().replace(' ', '_'), str(k))


def _nivel(v, cortes, etiquetas):
    """etiquetas tiene un elemento más que cortes. Devuelve (emoji, texto) o None."""
    if v is None:
        return None
    for c, e in zip(cortes, etiquetas):
        if v < c:
            return e
    return etiquetas[-1]


def _lm(nombre, valor_txt, nivel, explicacion):
    nv = f" {nivel[0]} **{nivel[1]}**" if nivel else ''
    return f"- **{nombre}: {valor_txt}**{nv} — {explicacion}"


def _div_pct(v):
    """Rendimiento por dividendo en %. Las versiones nuevas de yfinance devuelven
    el valor ya en porcentaje (0.4 = 0.4%) y las viejas como fracción (0.004).
    Una fracción mayor a 0.2 (20%) es poco creíble, así que se trata como porcentaje."""
    if v is None:
        return None
    v = float(v)
    return v if v > 0.2 else v * 100


def _fila(nombre, valor, fmt, cortes, etiquetas, expl):
    """Línea con nivel; si no hay dato muestra N/D."""
    if valor is None:
        return f"- **{nombre}: N/D** — sin dato en Yahoo Finance para este activo."
    return _lm(nombre, fmt(valor), _nivel(valor, cortes, etiquetas), expl)


def _bloque_fundamental(res_f, resumen_f, fmt):
    g = res_f.get
    L = []

    # ── Encabezado ──
    upside = None
    if g('target_price') and g('precio'):
        upside = (g('target_price') / g('precio') - 1) * 100
    cab = (f"\n**📊 Fundamental:** señal **{res_f['senal_final']}** "
           f"({res_f['n_ok']} positivas · {res_f['n_alt']} alertas) · "
           f"analistas: {_rec_es(g('recommendation'))}")
    if upside is not None:
        cab += f" · precio objetivo {fmt(g('target_price'))} ({upside:+.1f}% vs. precio actual)"
    L.append(cab)
    L.append("_La señal cuenta cuántos criterios fundamentales se cumplen (positivas vs. alertas). "
             "El veredicto de abajo pondera los scores 0-10 y puede diferir._")

    x = lambda v: f"{v:.1f}x"
    p = lambda v: f"{v*100:.1f}%"          # fracción -> %
    p0 = lambda v: f"{v*100:.0f}%"
    pp = lambda v: f"{v:+.1f}%"            # ya viene en %

    # ── Valuación ──
    L.append("\n**💰 Valuación — ¿está cara o barata?**")
    L.append(_fila('PER', g('per'), x, [10, 15, 25, 40],
        [('🟢','Muy barato'),('🟢','Barato'),('🟡','Normal'),('🟠','Exigente'),('🔴','Muy exigente')],
        "años de ganancias actuales que pagás por acción. Más bajo = más barata."))
    L.append(_fila('P/B', g('pb'), x, [1, 2.5, 6],
        [('🟢','Bajo'),('🟡','Razonable'),('🟠','Elevado'),('🔴','Muy elevado')],
        "precio vs. patrimonio contable. Con muchas recompras el P/B sube sin ser necesariamente malo."))
    L.append(_fila('EV/EBITDA', g('ev_ebitda'), x, [10, 15, 20],
        [('🟢','Atractivo'),('🟡','Normal'),('🟠','Elevado'),('🔴','Muy elevado')],
        "valor de la empresa completa (con deuda) vs. su ganancia operativa."))
    L.append(_fila('EV/Sales', g('ev_sales'), x, [1, 3, 8],
        [('🟢','Bajo'),('🟡','Normal'),('🟠','Elevado'),('🔴','Muy elevado')],
        "valor de la empresa vs. sus ventas. Útil si las ganancias son bajas o volátiles."))
    L.append(_fila('P/FCF', g('p_fcf'), x, [15, 25, 40],
        [('🟢','Atractivo'),('🟡','Normal'),('🟠','Elevado'),('🔴','Muy elevado')],
        "precio vs. la caja libre que genera el negocio."))
    L.append(_fila('PEG', g('peg'), lambda v: f"{v:.2f}", [1, 2],
        [('🟢','Barato'),('🟡','Razonable'),('🔴','Caro')],
        "PER ajustado por crecimiento. Menor a 1 = barato; mayor a 2 = caro."))

    # ── Rentabilidad / márgenes ──
    L.append("\n**📈 Rentabilidad y márgenes — ¿qué tan bien gana plata?**")
    def _f100(nombre, v, cortes, etiquetas, expl):
        L.append(_fila(nombre, None if v is None else v * 100, lambda z: f"{z:.1f}%", cortes, etiquetas, expl))
    _f100('ROE', g('roe'), [8, 15, 25],
          [('🔴','Débil'),('🟡','Aceptable'),('🟢','Bueno'),('🟢','Excepcional')],
          "ganancia sobre el patrimonio. Más de 100% suele deberse a recompras.")
    _f100('ROIC', g('roic'), [5, 10, 15],
          [('🔴','Débil'),('🟡','Aceptable'),('🟢','Bueno'),('🟢','Excepcional')],
          "retorno sobre todo el capital invertido. Más de 15% es muy bueno.")
    _f100('Margen bruto', g('gross_margin'), [20, 40, 60],
          [('🔴','Bajo'),('🟡','Moderado'),('🟢','Bueno'),('🟢','Excelente')],
          "lo que queda de cada venta tras el costo de producir.")
    _f100('Margen operativo', g('op_margin'), [10, 20, 30],
          [('🔴','Bajo'),('🟡','Moderado'),('🟢','Bueno'),('🟢','Excelente')],
          "ganancia del negocio antes de intereses e impuestos.")
    _f100('Margen neto', g('profit_margin'), [5, 10, 20],
          [('🔴','Bajo'),('🟡','Moderado'),('🟢','Bueno'),('🟢','Excelente')],
          "ganancia final por cada 100 de ventas.")
    _f100('Crecimiento de ingresos', g('revenue_growth'), [0, 10, 20],
          [('🔴','Contracción'),('🟡','Moderado'),('🟢','Bueno'),('🟢','Excelente')],
          "cuánto crecieron las ventas vs. el año anterior.")
    _f100('Crecimiento de EPS', g('eps_growth'), [0, 10, 20],
          [('🔴','Contracción'),('🟡','Moderado'),('🟢','Bueno'),('🟢','Excelente')],
          "cuánto crecieron las ganancias por acción.")

    # ── Solvencia y riesgo ──
    L.append("\n**🔒 Solvencia y riesgo — ¿aguanta?**")
    L.append(_fila('Deuda/Patrimonio (D/E)', g('debt_equity'), lambda v: f"{v:.2f}x", [0.5, 1, 2],
        [('🟢','Conservador'),('🟡','Moderado'),('🟠','Elevado'),('🔴','Muy elevado')],
        "cuánta deuda usa por cada peso de capital propio."))
    nde = g('net_debt_ebitda')
    L.append(_fila('Deuda neta/EBITDA', nde, lambda v: f"{v:.2f}x", [1, 3],
        [('🟢','Bajo'),('🟡','Moderado'),('🔴','Alto')],
        "tiene más caja que deuda." if (nde is not None and nde < 0)
        else (f"con su ganancia operativa tardaría ~{nde:.1f} años en pagar la deuda neta." if nde is not None else "")))
    L.append(_fila('Current Ratio', g('curr_ratio'), lambda v: f"{v:.2f}x", [1, 1.5, 2],
        [('🔴','Riesgo de liquidez'),('🟡','Ajustado'),('🟢','Saludable'),('🟢','Muy líquido')],
        "activos de corto plazo vs. deudas de corto plazo. Menor a 1 = puede costarle pagar."))
    L.append(_fila('Cobertura de intereses', g('interest_coverage'), x, [2, 3, 8],
        [('🔴','Riesgoso'),('🟠','Ajustado'),('🟡','Cómodo'),('🟢','Muy holgado')],
        "cuántas veces la ganancia operativa cubre los intereses de la deuda."))
    L.append(_fila('Beta', g('beta'), lambda v: f"{v:.2f}", [0.8, 1.2, 1.5],
        [('🟢','Defensiva'),('🟡','Como el mercado'),('🟠','Más volátil'),('🔴','Muy volátil')],
        "sensibilidad al mercado: con beta 1.2, si el mercado se mueve 10% la acción tiende a moverse ~12%."))

    # ── Retorno al accionista ──
    L.append("\n**💰 Retorno al accionista**")
    dy = _div_pct(g('div_yield'))
    if dy is None:
        L.append("- **Dividendo: N/D** — sin dato.")
    elif dy == 0:
        L.append("- **Dividendo:** no paga dividendos (reinvierte las ganancias).")
    else:
        L.append(_lm('Rendimiento por dividendo', f"{dy:.2f}%",
                     _nivel(dy, [2, 4, 6], [('🟡','Bajo'),('🟢','Moderado'),('🟢','Atractivo'),('🟠','Muy alto')]),
                     "dividendo anual sobre el precio. Si supera 6%, verificá que sea sostenible."))
    po = g('payout_ratio')
    L.append(_fila('Payout Ratio', None if po is None else po * 100, lambda v: f"{v:.0f}%", [30, 60, 90],
        [('🟢','Conservador'),('🟢','Sano'),('🟡','Alto'),('🔴','Insostenible')],
        "qué parte de las ganancias reparte como dividendo. Más de 90% deja poco margen."))
    L.append(_fila('Variación de acciones (YoY)', g('shares_change_yoy'), pp, [-2, 1, 5],
        [('🟢','Recompra acciones'),('🟡','Estable'),('🟠','Dilución leve'),('🔴','Dilución fuerte')],
        "si baja, recompra acciones (bueno); si sube, emite nuevas y diluye."))

    # ── Rendimiento y flujos ──
    L.append("\n**🚀 Rendimiento y flujos**")
    L.append(_fila('Alza YTD', g('alza_ytd'), pp, [-15, 0, 15, 30],
        [('🔴','Bajista fuerte'),('🟠','Bajista / lateral'),('🟢','Alcista moderado'),
         ('🟢','Alcista fuerte'),('🟡','Muy fuerte, verificar sostenibilidad')],
        "lo que sube o baja la acción en lo que va del año."))
    fc = g('fcf_conversion')
    L.append(_fila('Conversión a FCF', None if fc is None else fc * 100, lambda v: f"{v:.0f}%", [30, 60, 80],
        [('🔴','Baja'),('🟡','Regular'),('🟢','Buena'),('🟢','Excelente')],
        "qué parte del EBITDA se convierte en caja libre real."))
    fcf = g('fcf')
    if fcf is None:
        L.append("- **Flujo de caja libre: N/D**")
    else:
        L.append(f"- **Flujo de caja libre: {'🟢 positivo' if fcf > 0 else '🔴 negativo'}** ({_big(fcf)})")

    # ── Señales ──
    L.append(f"\n**✅ Señales OK:** {res_f['n_ok']} positivas · {res_f['n_alt']} alertas")

    # ── Scores 0-10 ──
    if resumen_f:
        L.append("\n**🎯 Scores (0 a 10):**")
        L.append(f"- **Calidad {_s10(resumen_f.get('calidad'))}** — rentabilidad, márgenes, caja y deuda del negocio. Más alto = mejor negocio.")
        L.append(f"- **Valoración {_s10(resumen_f.get('valoracion'))}** — qué tan barata está. 10 = muy barata, 0 = muy cara.")
        L.append(f"- **Crecimiento {_s10(resumen_f.get('crecimiento'))}** — ritmo de ventas y ganancias.")
        L.append(f"- **Riesgo {_s10(resumen_f.get('riesgo'))}** — volatilidad, deuda y liquidez. Acá más alto = MÁS riesgoso.")
        L.append(f"- **Veredicto: {resumen_f.get('v_emoji', '')} {resumen_f.get('veredicto', '')}**")
        cal, val = resumen_f.get('calidad'), resumen_f.get('valoracion')
        if cal is not None and val is not None:
            if cal >= 7 and val <= 3:
                L.append("_Lectura: es un gran negocio, pero el precio ya lo refleja. El problema no es la empresa sino lo que pagás por ella._")
            elif cal >= 7 and val >= 7:
                L.append("_Lectura: buen negocio a un precio atractivo, la combinación más buscada._")
            elif cal < 5 and val >= 7:
                L.append("_Lectura: está barata, pero por algo: la calidad del negocio es floja (posible trampa de valor)._")
    return L

def _bloque_niveles_gamma(gex, tk):
    """Niveles clave de gamma (igual que el módulo GEX): Resistencia / Pivote / Soporte / Mixto."""
    niv = gex.get('niveles')
    if niv is None or niv.empty:
        return []
    S = gex['spot']
    L = ["\n**🏆 Niveles clave de gamma** _(cada strike clasificado una sola vez)_"]
    if gex.get('proxy'):
        L.append(f"_⚠️ {tk} no tiene opciones propias: los niveles salen de **{gex['simbolo']}** "
                 f"y están en el precio de ese instrumento. Fijate en la distancia %, no en el valor absoluto._")

    def _linea(r):
        return (f"  - **{r['strike']:,.2f}** ({r['dist_pct']:+.1f}% del precio) · "
                f"Calls {r['calls'] / 1e6:+,.1f} M · Puts {-r['puts'] / 1e6:+,.1f} M · "
                f"dominio ×{r['dominio']:.1f}")

    resist = niv[niv['tipo'] == 'Resistencia'].sort_values('bruto', ascending=False)
    pivote = niv[niv['tipo'] == 'Pivote'].assign(_a=lambda d: d['dist_pct'].abs()).sort_values('_a')
    soport = niv[niv['tipo'] == 'Soporte'].sort_values('bruto', ascending=False)
    mixto = niv[niv['tipo'] == 'Mixto'].sort_values('bruto', ascending=False)

    for titulo, sub, vacio in (
            ('🟢 Resistencia Absoluta (techo)', resist, 'ningún strike con calls dominantes'),
            ('🟡 Pivote / Pinning (ancla)', pivote, 'ningún strike con calls y puts altos pegado al precio'),
            ('🔴 Soporte Absoluto (piso)', soport, 'ningún strike con puts dominantes'),
            ('⚪ Mixtos (sin dominio claro)', mixto, None)):
        if sub.empty:
            if vacio:
                L.append(f"- {titulo}: _{vacio}_")
            continue
        L.append(f"- {titulo}:")
        L.extend(_linea(r) for _, r in sub.iterrows())

    ra = resist[resist['strike'] > S].sort_values('strike')
    sa = soport[soport['strike'] < S].sort_values('strike', ascending=False)
    lect = []
    if not ra.empty:
        lect.append(f"resistencia más cercana sobre el precio en {ra.iloc[0]['strike']:,.2f} ({ra.iloc[0]['dist_pct']:+.1f}%)")
    if not sa.empty:
        lect.append(f"soporte más cercano bajo el precio en {sa.iloc[0]['strike']:,.2f} ({sa.iloc[0]['dist_pct']:+.1f}%)")
    if not pivote.empty:
        lect.append(f"pivote en {pivote.iloc[0]['strike']:,.2f} ({pivote.iloc[0]['dist_pct']:+.1f}%)")
    if lect:
        L.append("_Lectura: " + " · ".join(lect) + "._")
    return L
    
def _m(p):
    """Precio con $ escapado (Streamlit interpreta $...$ como fórmula)."""
    return f'\\${p:,.2f}'


def _generar_conclusion(nombre, precio, compuesto, resumen_f, r_largo, r_corto, gex):
    S = gex['spot'] if gex else precio
    if not S:
        return None
    cal = (resumen_f or {}).get('calidad')
    val = (resumen_f or {}).get('valoracion')

    # ── 1) El negocio ──
    if cal is not None:
        if cal >= 8:     n = 'un negocio extraordinario a nivel fundamental'
        elif cal >= 6.5: n = 'un buen negocio a nivel fundamental'
        elif cal >= 5:   n = 'un negocio de calidad fundamental aceptable'
        else:            n = 'un negocio con fundamentos débiles'
        if val is not None and cal >= 5:
            if val <= 4.5:   n += ', pero con una valuación exigente'
            elif val >= 7:   n += ' y con una valuación atractiva'
        buen_neg = cal >= 6.5
        s1 = f"**{nombre}** es {n}."
    else:
        buen_neg = compuesto >= 55
        s1 = f"**{nombre}** tiene un perfil compuesto de {compuesto:.0f}/100 (sin datos fundamentales)."

    # ── 2) Técnico ──
    rsi = r_largo['rsi'] if r_largo else None
    lim_hi, lim_lo = 70, 30
    if rsi is None and r_corto and r_corto.get('rsi') is not None:
        rsi, lim_hi, lim_lo = r_corto['rsi'], 80, 20
    sobrecompra = rsi is not None and rsi > lim_hi
    sobreventa = rsi is not None and rsi < lim_lo

    # ── 3) Niveles GEX ──
    cw = gex.get('call_wall') if gex else None
    pw = gex.get('put_wall') if gex else None
    flip = gex.get('flip') if gex else None
    d_cw = (cw / S - 1) * 100 if cw else None
    d_pw = (S / pw - 1) * 100 if pw else None
    cerca_techo = d_cw is not None and 0 <= d_cw <= 1.5
    sobre_techo = cw is not None and S > cw
    cerca_piso = d_pw is not None and 0 <= d_pw <= 1.5

    partes = []
    if cerca_techo:
        partes.append(f"el precio actual ({_m(S)}) está comprimido contra la Pared de Calls ({_m(cw)})")
    elif sobre_techo:
        partes.append(f"el precio actual ({_m(S)}) ya superó la Pared de Calls ({_m(cw)})")
    elif cw:
        partes.append(f"el precio actual ({_m(S)}) tiene la Pared de Calls en {_m(cw)} ({d_cw:+.1f}%) como posible techo")
    else:
        partes.append(f"el precio actual es {_m(S)}")
    if cerca_piso:
        partes.append(f"está apoyado sobre la Pared de Puts ({_m(pw)})")
    if sobrecompra:
        partes.append(f"hay sobrecompra técnica (RSI {rsi:.0f})")
    elif sobreventa:
        partes.append(f"hay sobreventa técnica (RSI {rsi:.0f})")
    s2 = ("En lo táctico, " if cal is None else ("" if 'exigente' in s1 else "En lo táctico, ")) + \
         (", ".join(partes[:-1]) + " y " + partes[-1] if len(partes) > 1 else partes[0]) + "."
    if 'exigente' in s1:
        s2 = s2[0].upper() + s2[1:]

    # ── 4) Sugerencia ──
    abajo = []
    if pw and pw < S:   abajo.append((pw, 'la Pared de Puts'))
    if flip and flip < S: abajo.append((flip, 'el punto de inflexión Gamma'))
    if not gex and r_largo and r_largo.get('ma20') and r_largo['ma20'] < S:
        abajo.append((r_largo['ma20'], 'la media de 20 ruedas'))
    abajo.sort(key=lambda x: -x[0])
    txt_abajo = ' o '.join(f"{lbl} ({_m(v)})" for v, lbl in abajo)

    if cal is not None and not buen_neg:
        s3 = ("El modelo no ve respaldo fundamental suficiente: conviene evitarlo o limitarse a "
              "operaciones tácticas de corto plazo.")
    elif buen_neg and (sobrecompra or cerca_techo or sobre_techo):
        s3 = ("La sugerencia del modelo es esperar un pullback o recorte"
              + (f" hacia {txt_abajo}" if txt_abajo else "")
              + " antes de armar nuevas posiciones.")
    elif buen_neg and (sobreventa or cerca_piso):
        s3 = ("Es una zona razonable para acumular de forma escalonada"
              + (f"; perder {_m(pw)} (Pared de Puts) sería una señal de cautela." if pw and pw < S else "."))
    elif buen_neg:
        s3 = ("No hay una señal táctica extrema: se puede acumular de forma gradual"
              + (f", priorizando entradas cerca de {txt_abajo}." if txt_abajo else "."))
    else:
        s3 = "Sin ventaja clara por ahora: conviene esperar confirmación antes de actuar."

    if gex and gex.get('regimen') == 'negativo':
        s3 += " Ojo: el régimen de gamma es negativo, así que los movimientos pueden amplificarse en ambos sentidos."
    if gex and gex.get('inminente'):
        s3 += f" 🚨 Además el Squeeze Score marca zona inminente ({gex['squeeze_score']:.0f}/100)."

    return f"{s1} {s2}\n\n{s3}"


def _responder_analizar(tk, ctx):
    """Wrapper con caché de sesión de 10 minutos: pedir el mismo ticker
    otra vez es instantáneo. Si el ticker falla, no se arrastra como
    'último ticker' al siguiente mensaje."""
    cache = st.session_state.setdefault('ia_cache_analisis', {})
    hit = cache.get(tk)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    texto = _responder_analizar_sin_cache(tk, ctx)
    if 'No pude encontrar datos suficientes' in texto:
        if st.session_state.get('ia_ultimo_ticker') == tk:
            st.session_state['ia_ultimo_ticker'] = None
    else:
        cache[tk] = (time.time(), texto)
    return texto


def _responder_analizar_sin_cache(tk, ctx):
    fmt = ctx.get('fmt_precio') or (lambda p: f'{p:,.2f}')
    sin_fund = _es_sin_fundamentals(tk, ctx)
    info_m = _info_mercado(tk, ctx)
    industria = ctx['TICKER_INDUSTRY'].get(tk) or (info_m[1] if info_m else 'Sin Clasificar')

    señales = []          # (nombre, score 0-100, peso)
    pros, contras = [], []
    tdc = {}
    fn_tdc, hz_cfg = ctx.get('_tdc_analizar_ticker'), ctx.get('HORIZONTES_TDC')

    with _pool_con_ctx(12) as ex:
        # 1) lo que no depende de precios arranca ya
        f_perfil = (ex.submit(_a_safe, ctx['obtener_perfil_empresa'], tk)
                    if (not sin_fund and ctx.get('obtener_perfil_empresa')) else None)
        f_fund = None if sin_fund else ex.submit(_a_safe, ctx['analizar_fundamental'], tk, industria)
        f_fs = None if sin_fund else ex.submit(_car_fscore_rapido, tk)
        f_gex = ex.submit(_a_safe, ctx['gex_niveles'], tk) if ctx.get('gex_niveles') else None

        # 2) precalentar cada período de precios UNA sola vez, en paralelo
        periodos = ['3mo', '1mo', '6mo', '2y'] + (['10y'] if fn_tdc else [])
        for f in [ex.submit(_a_safe, ctx['descargar_datos'], tk, p) for p in periodos]:
            f.result()

        # 3) cálculos (ya con los precios en caché)
        f_corto = ex.submit(_a_safe, _calc_corto, tk, ctx)
        f_hmm = ex.submit(_a_safe, _calc_hmm, tk, ctx)
        f_largo = ex.submit(_a_safe, _calc_largo, tk, ctx)
        f_tdc = {hz: ex.submit(_a_safe, fn_tdc, tk, hz_cfg[hz])
                 for hz in ('MP', 'LP') if fn_tdc and hz_cfg and hz in hz_cfg}

    perfil = f_perfil.result() if f_perfil else None
    res_f = f_fund.result() if f_fund else None
    fscore = f_fs.result() if f_fs else None
    gex = f_gex.result() if f_gex else None
    r_corto = f_corto.result()
    hmm = f_hmm.result()
    r_largo = f_largo.result()
    for hz, f in f_tdc.items():
        d = f.result()
        if d:
            tdc[hz] = d

    if not r_corto and not r_largo:
        return f"No pude encontrar datos suficientes para **{tk}**. Verificá que el símbolo sea correcto."

    precio = (r_corto or {}).get('precio') or (r_largo or {}).get('precio')

    # ══ Señales para el score compuesto + pros/contras ═══════
    if r_corto:
        señales.append(('Corto plazo', r_corto['sf'], 0.15))
        if r_corto['sa'] >= 62: pros.append(f"Precio en zona de acumulación de corto plazo (Acum {r_corto['sa']:.0f}/100)")
        elif r_corto['sa'] <= 38: contras.append(f"Caro dentro de su rango reciente (Acum {r_corto['sa']:.0f}/100)")
        if r_corto['sn'] >= 60: pros.append(f"Momentum/compresión favorable (Antic {r_corto['sn']:.0f}/100)")
        elif r_corto['sn'] <= 35: contras.append(f"Momentum de corto plazo débil (Antic {r_corto['sn']:.0f}/100)")

    if r_largo:
        señales.append(('Largo plazo', r_largo['global_score'], 0.20))
        if r_largo['golden_cross']: pros.append("Golden Cross activo (MA50 > MA200)")
        else: contras.append("Sin Golden Cross (MA50 < MA200)")
        if r_largo['macd_bull']: pros.append("MACD alcista")
        else: contras.append("MACD bajista")
        if r_largo['sharpe'] >= 1: pros.append(f"Buen retorno ajustado por riesgo (Sharpe {r_largo['sharpe']:.2f})")
        elif r_largo['sharpe'] < 0: contras.append(f"Sharpe negativo ({r_largo['sharpe']:.2f})")
        if r_largo['max_dd'] <= -35: contras.append(f"Drawdown histórico severo ({r_largo['max_dd']:.1f}%)")
        if r_largo['vol_anual'] >= 45: contras.append(f"Volatilidad muy alta ({r_largo['vol_anual']:.1f}% anual)")
        if r_largo['reversion_signal']: pros.append(f"Señal de sobreventa estadística ({r_largo['reversion_reasons']})")

    if tdc:
        señales.append(('Top-Down Cuant.', float(np.mean([d['sf'] for d in tdc.values()])), 0.15))
        if 'LP' in tdc and tdc['LP']['sa'] >= 62: pros.append(f"Barato en perspectiva de 1-2 años (TDC Acum {tdc['LP']['sa']:.0f})")
        if 'LP' in tdc and tdc['LP']['sa'] <= 38: contras.append(f"Caro en perspectiva de 1-2 años (TDC Acum {tdc['LP']['sa']:.0f})")

    resumen_f = None
    if res_f:
        if ctx.get('resumen_visual_fundamental'):
            resumen_f = _a_safe(ctx['resumen_visual_fundamental'], res_f)
        if resumen_f and resumen_f.get('conclusion') is not None:
            señales.append(('Fundamental', resumen_f['conclusion'] * 10, 0.25))
        else:
            señales.append(('Fundamental', {'COMPRA FUERTE': 80, 'MANTENER': 55}.get(res_f['senal_final'], 30), 0.25))
        for t, m in res_f.get('senales', []):
            if t == 'OK' and len(pros) < 9: pros.append(m)
        for t, m in res_f.get('senales', []):
            if t == 'ALT' and len(contras) < 9: contras.append(m)

    if fscore is not None:
        señales.append(('F-Score', fscore / 9 * 100, 0.15))
        if fscore >= 7: pros.append(f"Calidad financiera alta (F-Score {fscore:.1f}/9)")
        elif fscore <= 3: contras.append(f"Calidad financiera baja (F-Score {fscore:.1f}/9)")

    if hmm:
        mapa_h = {'ALCISTA': 75, 'NEUTRAL': 50, 'BAJISTA': 25}
        señales.append(('Régimen HMM', mapa_h.get(hmm['regimen'], 50), 0.10))
        txt_hmm = f"Régimen {hmm['regimen'].lower()} ({hmm['prob']}% de confianza, {hmm['duracion']} ruedas)"
        if hmm['regimen'] == 'ALCISTA': pros.append(txt_hmm)
        elif hmm['regimen'] == 'BAJISTA': contras.append(txt_hmm)

    peso_total = sum(p for _, _, p in señales) or 1
    compuesto = sum(s * p for _, s, p in señales) / peso_total

    # ══ Armado de la respuesta ═══════════════════════════════
    L = []
    nombre = (perfil or {}).get('nombre') or (info_m[0] if info_m else tk)
    L.append(f"## 📊 {nombre} ({tk}) — {fmt(precio) if precio else ''}")
    L.append(f"_{industria}_" + (f" · {perfil['sector']}" if perfil and perfil.get('sector') else ''))

    # ── RESUMEN (arriba de todo) ──
    L.append(f"\n### 🎯 Resumen\n**{_veredicto_compuesto(compuesto)}** — score compuesto **{compuesto:.0f}/100** "
             f"(sobre {len(señales)} módulos con datos).")
    L.append("\n".join(f"- {n}: **{s:.0f}/100**" for n, s, _ in señales))
    if len(señales) >= 2:
        mx, mn = max(señales, key=lambda x: x[1]), min(señales, key=lambda x: x[1])
        if mx[1] - mn[1] >= 35:
            L.append(f"\n⚠️ **Señales divergentes:** {mx[0]} ({mx[1]:.0f}) vs {mn[0]} ({mn[1]:.0f}). "
                     f"El veredicto promedia visiones distintas — mirá el detalle antes de concluir.")
    if pros:
        L.append("\n**✅ A favor**\n" + "\n".join(f"- {p}" for p in pros[:5]))
    if contras:
        L.append("\n**⚠️ En contra / riesgos**\n" + "\n".join(f"- {c}" for c in contras[:5]))
    concl = _a_safe(_generar_conclusion, nombre, precio, compuesto, resumen_f, r_largo, r_corto,
                    None if (gex and gex.get('proxy')) else gex)
    if concl:
        L.append("\n### 🧭 Conclusión\n" + concl)

    # ── Detalle ──
    L.append("\n---\n### 🔎 Detalle por módulo")

    if perfil:
        extra = []
        if perfil.get('market_cap'): extra.append(f"Market Cap {_big(perfil['market_cap'])}")
        if perfil.get('pct_desde_max52') is not None: extra.append(f"{perfil['pct_desde_max52']:+.1f}% vs máx. 52 sem.")
        if perfil.get('pct_desde_min52') is not None: extra.append(f"{perfil['pct_desde_min52']:+.1f}% vs mín. 52 sem.")
        if perfil.get('pct_institucional') is not None: extra.append(f"Institucional {_pf(perfil['pct_institucional'], 0)}")
        if extra:
            L.append("**🏢 Perfil:** " + " · ".join(extra))
        desc = (perfil.get('descripcion') or '')
        if desc and desc != 'Descripción no disponible.':
            L.append(f"_{desc[:260].rstrip()}…_")

    if r_corto:
        r = r_corto
        L.append(f"\n**⚡ Corto plazo:** Acum {r['sa']:.0f} · Antic {r['sn']:.0f} · Sent {r['ss']:.0f} → **{r['señal']}**"
                 f"\nRSI(7) {_n(r['rsi'], 1)} · Ret 5d {_n(r['ret5'], 2, '%')} · Ret 10d {_n(r['ret10'], 2, '%')}")

    if hmm:
        L.append(f"\n**🌀 Régimen HMM:** {hmm['regimen']} ({hmm['prob']}% prob.) · retorno anual del régimen "
                 f"{hmm['ret_anual_regimen']:+.1f}% · vol {hmm['vol_regimen']:.1f}%")

    if r_largo:
        r = r_largo
        L.append(f"\n**📈 Largo plazo (2 años):** Global **{int(r['global_score'])}/100** ({r['sesgo']}) — "
                 f"Trend {int(r['trend_score'])} · MR {int(r['mr_score'])} · Risk {int(r['risk_score'])}"
                 f"\nRet. anual {r['ret_anual']:+.1f}% · Vol {r['vol_anual']:.1f}% · Sharpe {r['sharpe']:.2f} · "
                 f"Sortino {_n(r['sortino'])} · Max DD {r['max_dd']:.1f}%"
                 f"\nRSI {r['rsi']:.1f} · Z-Score {r['zscore']:+.2f} · Hurst {r['hurst']:.2f}")

    for hz, d in tdc.items():
        cfg = ctx['HORIZONTES_TDC'][hz]
        L.append(f"\n**📐 Top-Down {cfg['nombre'].title()}:** Acum {d['sa']:.0f} · Antic {d['sn']:.0f} · "
                 f"Sent {d['ss']:.0f} → {d['accion']}")

    if res_f:
        L.extend(_bloque_fundamental(res_f, resumen_f, fmt))
    elif not sin_fund:
        L.append("\n**📊 Fundamental:** sin datos disponibles en Yahoo Finance para este activo.")
    else:
        L.append("\n_(Futuro, cripto, forex, índice o ETF: no tiene balance, por eso no hay Fundamental ni F-Score.)_")

    if fscore is not None:
        L.append(f"\n**🧮 F-Score (Piotroski):** {fscore:.1f}/9")

    # ── Niveles clave de gamma (para TODOS los activos que tengan cadena de opciones) ──
    if gex and gex.get('niveles') is not None:
        L.extend(_bloque_niveles_gamma(gex, tk))

    # ── Módulos opcionales (GEX, COT, Velas, Opciones) — se muestran si los conectás ──
    for etiqueta, clave in (('🧲 GEX', 'gex_resumen'), ('📑 COT', 'cot_resumen'),
                            ('🕯️ Velas', 'velas_resumen'), ('🎲 Opciones', 'opciones_resumen')):
        if ctx.get(clave):
            txt = _a_safe(ctx[clave], tk)
            if txt:
                L.append(f"\n**{etiqueta}:** {txt}")

    L.append(f"\n---\n*Cálculo cuantitativo sobre datos históricos de Yahoo Finance — no es asesoramiento financiero. "
             f"Decime «comparalo con X» o «armame una cartera con {tk}» para seguir.*")
    return "\n".join(L)


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


def _responder_industria(industria_nombre, ctx, top=6):
    """Acciones de una industria ordenadas por Score de Acumulación.
    top=None lista TODAS las acciones de la industria."""
    cargar_acciones = ctx.get('cargar_acciones_corto')
    if not cargar_acciones:
        return (f"Detecté que preguntás por **{industria_nombre}**, pero no tengo acceso a esos datos "
                f"desde acá ahora mismo. Probá con *'analizame <ticker>'* de esa industria puntual.")

    datos_ind = cargar_acciones((industria_nombre,))
    tickers_data = datos_ind.get(industria_nombre, {})
    if not tickers_data:
        return f"No pude obtener datos de corto plazo para la industria **{industria_nombre}** en este momento."

    ordenados = sorted(tickers_data.items(), key=lambda x: x[1]['sa'], reverse=True)
    top_items = ordenados if top is None else ordenados[:top]
    titulo = "todas las acciones" if top is None else "top"
    lineas = [f"Esto es lo que muestra **{industria_nombre}** ahora mismo ({titulo}, por Score de Acumulación):\n"]
    for tk, d in top_items:
        lineas.append(f"- **{tk}**: Acum {d['sa']:.0f}/100, Antic {d['sn']:.0f}/100 → {d.get('accion','')}")
    lineas.append(f"\n*Hay {len(tickers_data)} activos en total en {industria_nombre} en la app. "
                   f"Decime 'analizame <ticker>' para ver el detalle completo de alguno de ellos.*")
    return "\n".join(lineas)


# ── Mercados reales (commodities, metales, agro, blandos, cripto) ─────

_GRUPOS_MERCADO = [  # (etiqueta, grupos de MERCADOS_REALES, regex sobre texto normalizado)
    ('Cripto', ('Cripto', 'Cripto ETF'), r'cripto|crypto'),
    ('Metales', ('Met. Prec.', 'Met. Ind.', 'Minería'), r'metales|mineras|mineria'),
    ('Energía', ('Energía',), r'energeticos|combustibles|petroleo|brent|wti|uranio'),
    ('Granos', ('Agro',), r'granos|cereales|agricola'),
    ('Blandos', ('Blandos',), r'blandos|softs?'),
]


def _grupo_mercado(texto):
    t = _norm(texto)
    for etiqueta, grupos, pat in _GRUPOS_MERCADO:
        if re.search(pat, t):
            return etiqueta, grupos
    return None


def _responder_forex(ctx):
    forex = ctx.get('FOREX') or {}
    if not forex:
        return "No tengo el catálogo de Forex conectado desde acá. Mirá la sección 💱 Forex."
    por_grupo = {}
    for nombre, v in forex.items():
        por_grupo.setdefault(v[1], []).append(nombre)
    L = ["**💱 Pares de Forex disponibles:**\n"]
    for g, nombres in por_grupo.items():
        L.append(f"- **{g}**: " + " · ".join(nombres))
    L.append("\nPedime uno puntual: *'analizame EUR/USD'*, *'GBP-JPY'*, *'usdars'*. "
             "También podés armar una cartera con *'forex'*, *'majors'* o *'latam'*.")
    return "\n".join(L)


def _responder_mercados(texto, ctx):
    if re.search(r'forex|divisas|monedas', _norm(texto)):
        return _responder_forex(ctx)
    fn = ctx.get('cargar_mercados_corto')
    mercados = ctx.get('MERCADOS_REALES') or {}
    if not fn:
        return "No tengo acceso a los datos de mercados desde acá. Mirá la sección 🌐 Mercados."
    datos = fn()
    if not datos:
        return "No pude cargar los datos de mercados ahora mismo."
    sel = _grupo_mercado(texto)
    L = []
    if sel:
        etiqueta, grupos = sel
        datos = {k: d for k, d in datos.items() if mercados.get(k, (None, None))[1] in grupos}
        if not datos:
            return f"No encontré datos de {etiqueta} en este momento."
        ordenados = sorted(datos.items(), key=lambda x: x[1]['sa'], reverse=True)
        L.append(f"**{etiqueta}** — mejores por Score de Acumulación:\n")
        for n, d in ordenados[:5]:
            L.append(f"- **{n}** ({mercados[n][0]}): Acum {d['sa']:.0f} · Antic {d['sn']:.0f} → {d.get('accion','')}")
        if len(ordenados) > 8:
            L.append("\n**Más extendidos (score más bajo):**")
            for n, d in ordenados[-3:]:
                L.append(f"- **{n}** ({mercados[n][0]}): Acum {d['sa']:.0f} → {d.get('accion','')}")
    else:
        L.append("**Mercados reales — los 2 mejores por grupo (Acumulación):**\n")
        por_grupo = {}
        for n, d in datos.items():
            g = mercados.get(n, (None, 'Otros'))[1]
            por_grupo.setdefault(g, []).append((n, d))
        for g, items in por_grupo.items():
            items.sort(key=lambda x: x[1]['sa'], reverse=True)
            txt = " · ".join(f"{n} {d['sa']:.0f}" for n, d in items[:2])
            L.append(f"- **{g}**: {txt}")
        L.append("\nPedime un grupo puntual: *'cripto'*, *'metales'*, *'granos'*, *'blandos'*, *'energía'*.")
    L.append("\n*Score alto = barato dentro de su propio rango reciente, no garantía de suba. "
             "Decime 'analizame <nombre>' para el detalle.*")
    return "\n".join(L)


# ── Ranking Comprar / Vender (sectores, subsectores, países, ETFs) ──

_TOP_COMPRA_VENTA = 5


def _filas_desde_loader(datos, catalogo=None):
    """Convierte la salida de cargar_*_corto() a filas uniformes.
    Esos loaders ya traen tk, rsi, ret_5d y grupo/cat/region."""
    tk_por_nombre = {n: v[0] for n, v in (catalogo or {}).items()}
    return [dict(
        nombre=n,
        tk=d.get('tk') or tk_por_nombre.get(n, ''),
        grupo=d.get('grupo') or d.get('cat') or d.get('region') or '',
        sa=d['sa'], sn=d['sn'], accion=d.get('accion', ''),
        rsi=d.get('rsi'), ret5=d.get('ret_5d'),
    ) for n, d in (datos or {}).items()]


def _linea_item(f):
    info = ' · '.join(x for x in (f.get('tk'), f.get('grupo')) if x)
    info = f" ({info})" if info else ''
    extra = ''
    if f.get('rsi') is not None:
        extra += f" · RSI(7) {f['rsi']:.0f}"
    if f.get('ret5') is not None:
        extra += f" · Ret 5d {f['ret5']:+.1f}%"
    return (f"- **{f['nombre']}**{info}: Acum {f['sa']:.0f} · Antic {f['sn']:.0f}{extra}"
            + (f" → {f['accion']}" if f.get('accion') else ''))


def _bloque_compra_venta(titulo, filas, top=_TOP_COMPRA_VENTA):
    """5 para comprar (Acumulación más alta = más barato) y
    5 para vender (Acumulación más baja = más caro/extendido)."""
    if len(filas) < 2:
        return f"**{titulo}**: sin datos suficientes en este momento."
    orden = sorted(filas, key=lambda x: x['sa'], reverse=True)
    n = min(top, len(orden) // 2)      # evita que un item salga en ambas listas
    L = [f"### {titulo}",
         f"**🟢 Para comprar (los {n} más baratos):**"]
    L += [_linea_item(f) for f in orden[:n]]
    L.append(f"\n**🔴 Para vender / evitar (los {n} más caros):**")
    L += [_linea_item(f) for f in orden[::-1][:n]]
    return "\n".join(L)


def _responder_sectores_subsectores(ctx):
    fn_sec, fn_sub = ctx.get('cargar_sectores_corto'), ctx.get('cargar_subsectores_corto')
    datos_s = _a_safe(fn_sec) if fn_sec else None
    datos_ss = _a_safe(fn_sub) if fn_sub else None
    cat = ctx.get('SECTORES_TOTAL')
    filas_s = _filas_desde_loader(datos_s, cat)
    filas_ss = _filas_desde_loader(datos_ss, cat)

    if not filas_s and not filas_ss:
        return "No pude cargar datos de sectores ni subsectores en este momento."

    partes = []
    if filas_s:
        partes.append(_bloque_compra_venta("🏷️ Sectores (GICS)", filas_s))
    if filas_ss:
        partes.append(_bloque_compra_venta("🔬 Subsectores", filas_ss))
    partes.append("*Acumulación alta = barato dentro de su propio rango reciente; baja = caro/extendido. "
                  "No es garantía de suba ni de baja, ni asesoramiento financiero.*")
    return "\n\n---\n\n".join(partes)


_CATS_ETF_ACCIONARIOS = {'Índices', 'Factores', 'Global'}


def _responder_etfs(ctx):
    fn = ctx.get('cargar_etfs_corto')
    if not fn:
        return "No tengo conectado el análisis de ETFs desde acá. Mirá la sección 📦 ETFs y Bonos."
    datos = _a_safe(fn)
    if not datos:
        return "No pude cargar los ETFs en este momento. Probá de nuevo en un rato."

    # Solo ETFs de renta variable: Índices, Factores y Global (sin bonos ni tasas)
    datos = {n: d for n, d in datos.items() if d.get('cat') in _CATS_ETF_ACCIONARIOS}
    filas = _filas_desde_loader(datos, ctx.get('ETFS'))
    if len(filas) < 4:
        return "No hay suficientes ETFs con datos para armar el ranking."

    orden = sorted(filas, key=lambda x: x['sa'], reverse=True)
    n = min(_TOP_COMPRA_VENTA, len(orden) // 2)

    L = [f"## 🏦 ETFs (Índices, Factores y Global) — {len(filas)} analizados",
         f"\n**🟢 Los {n} más baratos (Acumulación más alta):**"]
    L += [_linea_item(f) for f in orden[:n]]
    L.append(f"\n**🔴 Los {n} más caros (Acumulación más baja):**")
    L += [_linea_item(f) for f in orden[::-1][:n]]

    L.append("\n*Barato/caro es relativo al propio rango reciente de cada ETF. "
             "Decime 'analizame <ticker>' para el detalle.*")
    return "\n".join(L)


def _responder_oportunidades(texto, ctx):
    t = texto.lower()
    if re.search(r'\betfs?\b', t):
        return _responder_etfs(ctx)
    if re.search(r'\bpa[ií]s', t):
        datos = _a_safe(ctx['cargar_paises_corto'])
        return (_bloque_compra_venta("🌎 Países / Índices", _filas_desde_loader(datos, ctx.get('PAISES')))
                + "\n\n*Score alto = relativamente barato en su propio historial reciente, "
                  "no es garantía de suba.*")
    if _grupo_mercado(t) or re.search(r'commodit|mercados|materias', t):
        return _responder_mercados(texto, ctx)
    # "sectores baratos", "qué sector...", o cualquier otra consulta de oportunidades
    return _responder_sectores_subsectores(ctx)


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


# ── Otros módulos ────────────────────────────────────────────────

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
    if _es_sin_fundamentals(tk, ctx):
        return (f"**{tk}** es un futuro, cripto, índice o ETF: no tiene balance, así que no hay F-Score. "
                f"Usá *'analizame {tk}'* para el análisis de corto/largo plazo, Top-Down y régimen HMM.")
    fn = ctx.get('calcular_fscore')
    r = None
    if fn:
        try:
            r = fn(tk)
        except Exception:
            r = None
    if r is None:
        # Fallback: calculamos nosotros mismos el F-Score (misma lógica que el
        # pipeline de armado de cartera), así funciona aunque la app principal
        # no haya conectado 'calcular_fscore' en el ctx.
        r = _car_fscore_rapido(tk)
    if r is None:
        return (f"No pude calcular el F-Score de {tk} (puede no tener suficientes estados financieros "
                f"disponibles). También lo encontrás en 🧰 Herramientas → F-Score (Piotroski).")
    return f"**F-Score (Piotroski) de {tk}**: {r:.2f}/9"


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
        base += (f"\n\nDetecté que mencionaste {', '.join(tickers)}. Si querés que corra el optimizador acá mismo "
                  f"con F-Score y Top-Down Cuantitativo incluidos, decime *'armame una cartera con {', '.join(tickers)}'*. "
                  f"Si preferís el optimizador completo con benchmark, capital e inflación, andá a "
                  f"🧰 Herramientas → Optimizar cartera.")
    else:
        base += ("\n\nEs una herramienta interactiva — abrila en 🧰 Herramientas → Optimizar cartera, o pedime acá "
                  "*'armame una cartera con <sectores o tickers>'* para el pipeline automático con F-Score incluido.")
    return base


# ==============================================================
#  ARMADO DE CARTERA (IA) — PIPELINE: F-Score → Top-Down Cuantitativo
#  (corto + largo plazo) → Optimizador de Cartera (Monte Carlo)
#  ==============================================================
#  Flujo conversacional (wizard, 3 pasos):
#    1) Sectores, tickers o grupos de mercado (texto libre)
#    2) F-Score mínimo aceptable (0-9)
#    3) F-Score máximo aceptable (0-9)
#  Con eso corre TODO el pipeline y devuelve las 5 carteras candidatas.
#  Los activos sin balance (futuros, cripto, índices, ETFs) quedan
#  exentos del filtro de F-Score.
#
#  ⚠️ Requiere que ctx tenga 'ACCIONES_POR_INDUSTRIA' (dict industria ->
#  lista de tickers) y, para commodities/cripto, 'MERCADOS_REALES'.
# ==============================================================

_CAR_MAX_UNIVERSO = 40   # tope de tickers a evaluar (evita timeouts)
_CAR_TOP_N_RANKING = 10  # cuántos activos, tras filtrar por F-Score, pasan al optimizador


def _car_safe_row(df, key, col_idx):
    if df is None or df.empty or key not in df.index:
        return None
    try:
        val = df.loc[key]
        if col_idx >= len(val):
            return None
        v = val.iloc[col_idx]
        return None if pd.isna(v) else v
    except Exception:
        return None


_CAR_ALIASES = {
    'Total Debt': ['Total Debt', 'Net Debt'],
    'Current Assets': ['Current Assets'],
    'Current Liabilities': ['Current Liabilities'],
    'Shares Outstanding': ['Ordinary Shares Number', 'Share Issued'],
    'Operating Cash Flow': ['Operating Cash Flow', 'Cash Flow From Continuing Operating Activities'],
}


def _car_get_alias(df, canonical_key, col_idx):
    for key in _CAR_ALIASES.get(canonical_key, [canonical_key]):
        val = _car_safe_row(df, key, col_idx)
        if val is not None:
            return val
    return None


def _car_calcular_fscore(ticker):
    """F-Score de Piotroski (0-9) para UN ticker, calculado on-demand,
    pensado para correr dentro de un ThreadPoolExecutor.
    Misma lógica financiera que modulo_fscore.py, con umbral algo más laxo
    (5 criterios evaluables en vez de 6) porque acá se corre sobre universos
    más chicos elegidos por el usuario."""
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        income_statement = stock.financials
        balance_sheet = stock.balance_sheet
        cash_flow = stock.cashflow

        if income_statement is None or income_statement.empty or \
           balance_sheet is None or balance_sheet.empty or \
           cash_flow is None or cash_flow.empty:
            return None

        net_income_0 = _car_safe_row(income_statement, 'Net Income', 0)
        net_income_1 = _car_safe_row(income_statement, 'Net Income', 1)
        total_assets_0 = _car_safe_row(balance_sheet, 'Total Assets', 0)
        total_assets_1 = _car_safe_row(balance_sheet, 'Total Assets', 1)
        ocf_0 = _car_get_alias(cash_flow, 'Operating Cash Flow', 0)
        ocf_1 = _car_get_alias(cash_flow, 'Operating Cash Flow', 1)
        debt_0 = _car_get_alias(balance_sheet, 'Total Debt', 0)
        debt_1 = _car_get_alias(balance_sheet, 'Total Debt', 1)
        curr_assets_0 = _car_get_alias(balance_sheet, 'Current Assets', 0)
        curr_liab_0 = _car_get_alias(balance_sheet, 'Current Liabilities', 0)
        shares_0 = _car_get_alias(balance_sheet, 'Shares Outstanding', 0)
        shares_1 = _car_get_alias(balance_sheet, 'Shares Outstanding', 1)
        gross_profit_0 = _car_safe_row(income_statement, 'Gross Profit', 0)
        gross_profit_1 = _car_safe_row(income_statement, 'Gross Profit', 1)
        total_revenue_0 = _car_safe_row(income_statement, 'Total Revenue', 0)

        criterios = {}
        if net_income_0 is not None and net_income_1 is not None:
            criterios['net_income'] = net_income_0 >= net_income_1
        if net_income_0 is not None and total_assets_0 and net_income_1 is not None and total_assets_1:
            criterios['roa'] = (net_income_0 / total_assets_0) >= (net_income_1 / total_assets_1)
        if ocf_0 is not None and ocf_1 is not None:
            criterios['ocf_growth'] = ocf_0 >= ocf_1
        if ocf_0 is not None and net_income_0 is not None:
            criterios['ocf_vs_ni'] = ocf_0 > net_income_0
        if debt_0 is not None and debt_1 is not None:
            criterios['debt'] = debt_0 < debt_1
        if curr_assets_0 is not None and curr_liab_0:
            criterios['current_ratio'] = (curr_assets_0 / curr_liab_0) > 1
        if shares_0 is not None and shares_1 is not None:
            criterios['shares'] = shares_0 <= shares_1
        if gross_profit_0 is not None and gross_profit_1 is not None:
            criterios['gross_margin'] = gross_profit_0 >= gross_profit_1
        if total_revenue_0 is not None and total_assets_1:
            criterios['asset_turnover'] = (total_revenue_0 / total_assets_1) >= 1

        if len(criterios) < 5:
            return None

        f_score = sum(criterios.values())
        return round(f_score / len(criterios) * 9, 2)
    except Exception:
        return None


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _car_fscore_cached_ok(ticker):
    r = _car_calcular_fscore(ticker)
    if r is None:
        raise ValueError('sin fscore')   # así no se cachean los fallos
    return r


def _car_fscore_rapido(ticker):
    """F-Score con caché de 6 horas (los fallos no se cachean)."""
    try:
        return _car_fscore_cached_ok(ticker)
    except Exception:
        return None


_COMMODITIES = ('Energía', 'Met. Prec.', 'Met. Ind.', 'Minería', 'Agro', 'Blandos')
_GRUPOS_ALIAS_CARTERA = {
    'commodities': _COMMODITIES, 'commodity': _COMMODITIES, 'materias primas': _COMMODITIES,
    'energia': ('Energía',), 'energeticos': ('Energía',),
    'metales': ('Met. Prec.', 'Met. Ind.', 'Minería'),
    'metales preciosos': ('Met. Prec.',), 'metales industriales': ('Met. Ind.',),
    'mineria': ('Minería',), 'agro': ('Agro',), 'granos': ('Agro',),
    'blandos': ('Blandos',), 'softs': ('Blandos',),
    'cripto': ('Cripto',), 'criptos': ('Cripto',), 'criptomonedas': ('Cripto',),
    'crypto': ('Cripto',), 'cripto etf': ('Cripto ETF',),
}


def _grupos_dinamicos(ctx):
    """alias de grupo -> lista de tickers (mercados, forex y categorías de ETFs)."""
    g = {}
    mercados = ctx.get('MERCADOS_REALES') or {}
    for alias, grupos in _GRUPOS_ALIAS_CARTERA.items():
        g[alias] = [v[0] for v in mercados.values() if v[1] in grupos]
    forex = ctx.get('FOREX') or {}
    if forex:
        todos = [v[0] for v in forex.values()]
        for a in ('forex', 'divisas', 'monedas', 'fx'):
            g[a] = todos
        for cat in {v[1] for v in forex.values()}:
            g[_norm(cat)] = [v[0] for v in forex.values() if v[1] == cat]
    etfs = ctx.get('ETFS') or {}
    if etfs:
        for cat in {v[1] for v in etfs.values()}:
            g[_norm(cat)] = [v[0] for v in etfs.values() if v[1] == cat]
        renta = ('Tasas Tesoro', 'Bonos EE.UU.', 'Crédito Corporativo', 'Renta Fija Global')
        g['bonos'] = g['renta fija'] = [v[0] for v in etfs.values() if v[1] in renta]
        g['etfs'] = [v[0] for v in etfs.values()]
    return {k: v for k, v in g.items() if v}


def _car_construir_universo(texto, ctx):
    """Convierte texto libre ('Semiconductores, oro, cripto y NVDA') en una
    lista de tickers, combinando: nombres de MERCADOS_REALES, grupos
    (cripto, metales, granos...), industrias de acciones, alias y tickers
    sueltos validados."""
    industrias = ctx.get('ACCIONES_POR_INDUSTRIA', {})
    industrias_lower = {k.lower(): k for k in industrias}
    mercados = ctx.get('MERCADOS_REALES') or {}
    por_nombre = {_norm(re.sub(r'\(.*?\)', '', n)).strip(): v[0] for n, v in mercados.items()}
    grupos = _grupos_dinamicos(ctx)
    universo = _universo_completo(ctx)
    tickers = []
    for parte in re.split(r'[,;]|\by\b|\be\b', texto, flags=re.IGNORECASE):
        p = parte.strip(' .')
        if not p:
            continue
        pn, pl = _norm(p), p.lower()
        if pn in por_nombre:
            tickers.append(por_nombre[pn])
            continue
        if pn in grupos:
            tickers.extend(grupos[pn])
            continue
        match_ind = next((real for low, real in industrias_lower.items()
                          if low == pl or (len(pl) >= 3 and (low in pl or pl in low))), None)
        if match_ind:
            tickers.extend(industrias[match_ind])
            continue
        al = _detectar_alias(p, ctx)
        if al:
            tickers.extend(al)
            continue
        if p.upper() in universo:
            tickers.append(p.upper())
            continue
        tk_val = ctx['validar_ticker'](p)
        if tk_val:
            tickers.append(tk_val)
    return list(dict.fromkeys(tickers))


def _car_simular_cartera(tickers, ctx, simulaciones=4000, periodo='2y', rf=0.0):
    """Descarga precios en paralelo (reutilizando ctx['descargar_datos']/
    ['get_close_series']) y corre una simulación Monte Carlo simplificada.
    Devuelve (dict de 5 carteras candidatas, lista de tickers realmente
    usados) o (None, None) si no hay suficiente historial en común."""
    def _bajar(tk):
        df = ctx['descargar_datos'](tk, periodo)
        cl = ctx['get_close_series'](df) if df is not None else None
        return tk, cl

    precios = {}
    with _pool_con_ctx(8) as ex:
        for tk, cl in ex.map(_bajar, tickers):
            if cl is not None and len(cl.dropna()) > 100:
                precios[tk] = cl.dropna()

    if len(precios) < 2:
        return None, None

    df_precios = pd.DataFrame(precios).dropna()
    if len(df_precios) < 100:
        return None, None

    tickers_ok = list(df_precios.columns)
    retornos = df_precios.pct_change().dropna()
    if len(retornos) < 50:
        return None, None

    rng = np.random.default_rng(42)
    n = len(tickers_ok)
    pesos = rng.dirichlet(np.ones(n), size=simulaciones)
    ret_mat = retornos[tickers_ok].values
    ret_cart = ret_mat @ pesos.T

    equity = np.cumprod(1 + ret_cart, axis=0)
    anios = ret_cart.shape[0] / 252
    with np.errstate(invalid='ignore'):
        cagr = equity[-1, :] ** (1 / anios) - 1
    vol = ret_cart.std(axis=0, ddof=1) * np.sqrt(252)
    with np.errstate(invalid='ignore', divide='ignore'):
        sharpe = np.where(vol != 0, (cagr - rf) / vol, np.nan)

    neg = np.where(ret_cart < 0, ret_cart, np.nan)
    with np.errstate(invalid='ignore'):
        downside = np.nanstd(neg, axis=0) * np.sqrt(252)
        sortino = np.where(downside != 0, (cagr - rf) / downside, np.nan)

    running_max = np.maximum.accumulate(equity, axis=0)
    dd = equity / running_max - 1
    max_dd = dd.min(axis=0)
    with np.errstate(invalid='ignore', divide='ignore'):
        calmar = np.where(max_dd != 0, cagr / np.abs(max_dd), np.nan)

    df_sim = pd.DataFrame({
        'CAGR': cagr, 'Volatilidad': vol, 'Sharpe': sharpe,
        'Sortino': sortino, 'Max Drawdown': max_dd, 'Calmar': calmar,
    })
    for i, tk in enumerate(tickers_ok):
        df_sim[tk] = pesos[:, i]

    df_sim['Score Global'] = (
        df_sim['CAGR'].rank(pct=True) * 0.35
        + df_sim['Sharpe'].rank(pct=True) * 0.25
        + df_sim['Sortino'].rank(pct=True) * 0.20
        + df_sim['Calmar'].rank(pct=True) * 0.10
        + (1 - df_sim['Max Drawdown'].abs().rank(pct=True)) * 0.10
    )

    candidatas_idx = {
        'Más Rentable': df_sim['CAGR'].idxmax(),
        'Mejor Sharpe': df_sim['Sharpe'].idxmax(),
        'Mejor Sortino': df_sim['Sortino'].idxmax(),
        'Menor Drawdown': df_sim['Max Drawdown'].idxmax(),
        'Recomendada (Score Global)': df_sim['Score Global'].idxmax(),
    }
    carteras = {nombre: df_sim.loc[idx] for nombre, idx in candidatas_idx.items()}
    return carteras, tickers_ok


def _texto_pregunta_cartera_universo():
    return ("Dale, armemos una cartera automática 🧩. Decime **sectores** (ej: *'Semiconductores, Bancos'*), "
            "**tickers puntuales** (ej: *'NVDA, AAPL, KO'*) o **grupos** como *'cripto'*, *'metales'*, "
            "*'granos'*, *'commodities'*, *'oro'*, *'forex'*, *'majors'*, *'bonos'*, *'EUR/USD'* — podés combinar todo, separado por coma.\n\n"
            "_(Voy a correr F-Score → Top-Down Cuantitativo corto/largo plazo → Optimizador Monte Carlo, "
            "así que puede tardar un rato con universos grandes — hasta 40 tickers. Futuros, cripto y ETFs "
            "no tienen balance, así que quedan exentos del filtro de F-Score)_")


def _texto_pregunta_cartera_fscore_min():
    return "¿Cuál es el **F-Score (Piotroski) mínimo** aceptable? Va de 0 a 9 — escribí '-' para no poner piso."


def _texto_pregunta_cartera_fscore_max():
    return "¿Y el **F-Score máximo**? También de 0 a 9 — escribí '-' para no poner techo (9 = sin límite)."


def _iniciar_wizard_cartera(texto, ctx):
    st.session_state['ia_cartera_wizard'] = dict(paso='universo', universo=None, fscore_min=None, fscore_max=None)
    return _texto_pregunta_cartera_universo()


def _continuar_wizard_cartera(texto_usuario, ctx):
    wizard = st.session_state['ia_cartera_wizard']
    t = texto_usuario.strip()

    if t.lower() in ('cancelar', 'cancela', 'cancelá'):
        st.session_state['ia_cartera_wizard'] = None
        return "Listo, cancelé el armado de la cartera."

    if wizard['paso'] == 'universo':
        wizard['universo'] = t
        wizard['paso'] = 'fscore_min'
        st.session_state['ia_cartera_wizard'] = wizard
        return _texto_pregunta_cartera_fscore_min()

    if wizard['paso'] == 'fscore_min':
        val = extraer_monto(t)
        wizard['fscore_min'] = 0.0 if (t == '-' or val is None) else max(0.0, min(9.0, val))
        wizard['paso'] = 'fscore_max'
        st.session_state['ia_cartera_wizard'] = wizard
        return _texto_pregunta_cartera_fscore_max()

    if wizard['paso'] == 'fscore_max':
        val = extraer_monto(t)
        wizard['fscore_max'] = 9.0 if (t == '-' or val is None) else max(0.0, min(9.0, val))
        if wizard['fscore_max'] < wizard['fscore_min']:
            wizard['fscore_min'], wizard['fscore_max'] = wizard['fscore_max'], wizard['fscore_min']
        st.session_state['ia_cartera_wizard'] = None
        return _responder_armar_cartera(wizard, ctx)

    st.session_state['ia_cartera_wizard'] = None
    return "Se desincronizó el asistente de carteras — probemos de nuevo: escribí *'armame una cartera'*."


def _responder_armar_cartera(datos, ctx):
    universo_texto = datos['universo']
    fscore_min = datos['fscore_min']
    fscore_max = datos['fscore_max']

    tickers_universo = _car_construir_universo(universo_texto, ctx)
    if not tickers_universo:
        return ("No pude identificar sectores, grupos ni tickers válidos en lo que escribiste. Probá con nombres de "
                "industria tal cual aparecen en la app (ej: *'Semiconductores, Bancos'*), grupos "
                "(*'cripto'*, *'metales'*, *'granos'*) o tickers (ej: *'NVDA, AAPL, KO'*).")

    truncado = len(tickers_universo) > _CAR_MAX_UNIVERSO
    if truncado:
        tickers_universo = tickers_universo[:_CAR_MAX_UNIVERSO]

    # ── 1) F-Score (en paralelo, con caché de 6 h). Los activos sin balance
    #       (futuros, cripto, índices, ETFs) se eximen del filtro. ─────────
    exentos = [tk for tk in tickers_universo if _es_sin_fundamentals(tk, ctx)]
    a_calcular = [tk for tk in tickers_universo if tk not in exentos]
    txt_ex = (f" (+{len(exentos)} sin balance —commodities/cripto/ETFs— exentos del F-Score)"
              if exentos else "")

    fscores = {}
    with _pool_con_ctx(8) as ex:
        futuros = {ex.submit(_car_fscore_rapido, tk): tk for tk in a_calcular}
        for fut in as_completed(futuros):
            tk = futuros[fut]
            r = fut.result()
            if r is not None:
                fscores[tk] = r

    aprobados = [tk for tk, sc in fscores.items() if fscore_min <= sc <= fscore_max] + exentos
    if len(aprobados) < 2:
        detalle = ', '.join(f'{tk} ({sc:.1f})' for tk, sc in sorted(fscores.items(), key=lambda x: -x[1])[:12])
        sin_datos = ('ninguno disponible (puede que sean poco líquidos o sin estados financieros '
                     'en Yahoo Finance)')
        return (f"Con F-Score entre **{fscore_min:.1f}** y **{fscore_max:.1f}** quedaron solo "
                f"**{len(aprobados)}** activo(s) de los {len(tickers_universo)} analizados "
                f"({len(fscores)} con F-Score calculable) — necesito al menos 2 para armar una cartera.\n\n"
                f"F-Scores calculados: {detalle or sin_datos}.\n\n"
                f"Probá ampliar el rango de F-Score o sumar más sectores/tickers.")

    # ── 2) Top-Down Cuantitativo: corto plazo (scores_corto) + largo plazo (Global Score) ──
    def _rank_uno(tk):
        sa = None
        df_v = ctx['descargar_datos'](tk, '3mo')
        df_m = ctx['descargar_datos'](tk, '1mo')
        if df_v is not None and df_m is not None:
            cl_v = ctx['get_close_series'](df_v)
            cl_m = ctx['get_close_series'](df_m)
            if cl_v is not None and cl_m is not None and len(cl_v.dropna()) >= 15:
                atr = ctx['calcular_atr'](df_m)
                sa, _sn, _ss = ctx['scores_corto'](cl_v, cl_m, atr)

        global_score = None
        df_l = ctx['descargar_datos'](tk, '2y')
        cl_l = ctx['get_close_series'](df_l) if df_l is not None else None
        if cl_l is not None and len(cl_l) >= 150:
            r_l = ctx['analizar_largo'](tk, cl_l)
            if r_l:
                global_score = r_l['global_score']

        if sa is None and global_score is None:
            return None
        valores_validos = [v for v in (sa, global_score) if v is not None]
        combinado = float(np.mean(valores_validos)) if valores_validos else 0.0
        return dict(tk=tk, fscore=fscores.get(tk), sa=sa, global_score=global_score, combinado=combinado)

    ranking = []
    with _pool_con_ctx(8) as ex:
        for r in ex.map(lambda t: _a_safe(_rank_uno, t), aprobados):
            if r:
                ranking.append(r)

    if len(ranking) < 2:
        return ("Los activos pasaron el filtro de F-Score, pero no pude calcular scores de corto/largo plazo "
                "suficientes para ninguno (historial insuficiente). Probá con otros sectores/tickers.")

    ranking.sort(key=lambda x: x['combinado'], reverse=True)
    tickers_finales = [r['tk'] for r in ranking[:_CAR_TOP_N_RANKING]]

    # ── 3) Optimizador de Cartera (Monte Carlo) ───────────────────────
    carteras, tickers_ok = _car_simular_cartera(tickers_finales, ctx)
    if carteras is None:
        return ("Filtré los activos por F-Score y por score cuantitativo de corto/largo plazo, pero no logré "
                "descargar suficiente historial de precios en común entre ellos para correr el optimizador "
                "Monte Carlo. Probá con otra combinación de sectores/tickers.")

    # ── Armado de la respuesta ─────────────────────────────────────────
    partes = []
    aviso_trunc = f" _(se truncó a los primeros {_CAR_MAX_UNIVERSO} para no demorar demasiado)_" if truncado else ""
    partes.append(
        f"**Pipeline ejecutado** 🧩 sobre {len(tickers_universo)} activos{aviso_trunc} → "
        f"**{len(aprobados)}** pasaron el filtro F-Score ({fscore_min:.1f}–{fscore_max:.1f}){txt_ex} → "
        f"top **{len(tickers_finales)}** por score cuantitativo → cartera optimizada con **{len(tickers_ok)}** activos "
        f"(los que tenían historial de precios en común)."
    )

    partes.append("\n**Ranking usado (F-Score · Corto Acum. · Largo Global Score):**")
    for r in ranking[:_CAR_TOP_N_RANKING]:
        sa_txt = f"{r['sa']:.0f}" if r['sa'] is not None else 'N/D'
        gl_txt = f"{r['global_score']:.0f}" if r['global_score'] is not None else 'N/D'
        fs_txt = f"{r['fscore']:.1f}" if r['fscore'] is not None else 'n/a (sin balance)'
        marca = " ✅ (en cartera final)" if r['tk'] in tickers_ok else ""
        partes.append(f"- **{r['tk']}**: F-Score {fs_txt} · Corto {sa_txt}/100 · Largo {gl_txt}/100{marca}")

    partes.append("\n**Las 5 carteras candidatas (Monte Carlo, 2 años de historial):**")
    for nombre, cart in carteras.items():
        pesos_txt = ' · '.join(
            f"{tk}: {cart[tk]*100:.1f}%" for tk in tickers_ok if cart[tk] > 0.01
        )
        partes.append(
            f"\n**{nombre}** — CAGR {cart['CAGR']*100:+.1f}% · Sharpe {cart['Sharpe']:.2f} · "
            f"Sortino {cart['Sortino']:.2f} · Vol {cart['Volatilidad']*100:.1f}% · "
            f"Max Drawdown {cart['Max Drawdown']*100:.1f}%\n"
            f"_{pesos_txt}_"
        )

    partes.append(
        "\n\n*Todo esto es un cálculo cuantitativo sobre datos históricos — no es asesoramiento financiero. "
        "Si querés afinar parámetros (benchmark, capital, más simulaciones, rebalanceo, VaR, inflación) usá "
        "🧰 Herramientas → Optimizar cartera con estos mismos tickers cargados.*"
    )
    return "\n".join(partes)


# ==============================================================
#  BOTONES RÁPIDOS — evita tener que escribir cuando el asistente
#  está esperando una opción de una lista fija (menú de registro,
#  tipo de movimiento, campos con `tipo='opciones'` del wizard,
#  confirmaciones sí/no, y los F-Score min/máx del armado de
#  cartera). Devuelve una lista de (etiqueta, valor_a_enviar) o
#  None si el siguiente paso espera texto libre (monto, fecha, texto,
#  sectores/tickers).
# ==============================================================

def _opciones_pendientes_botones(ctx):
    if st.session_state.get('ia_pendiente_mov'):
        return [('✅ Sí, confirmar', 'sí'), ('❌ No, cancelar', 'no')]

    if st.session_state.get('ia_pendiente_tipo'):
        return [('1️⃣ Ingreso', 'Ingreso'), ('2️⃣ Gasto', 'Gasto'), ('3️⃣ Deuda', 'Deuda')]

    if st.session_state.get('ia_pendiente_registro'):
        return [('✅ Sí, confirmar', 'sí'), ('❌ No, cancelar', 'no')]

    if st.session_state.get('ia_registro_menu_pendiente'):
        return [
            ('1️⃣ Ingreso', 'Ingreso'),
            ('2️⃣ Gasto', 'Gasto'),
            ('3️⃣ Deuda', 'Deuda'),
            ('4️⃣ Inversión Corto Plazo', 'Inversión Corto Plazo'),
            ('5️⃣ Inversión Largo Plazo', 'Inversión Largo Plazo'),
            ('6️⃣ Trading', 'Trading'),
            ('7️⃣ Objetivo de Ahorro', 'Objetivo de Ahorro'),
        ]

    car_wizard = st.session_state.get('ia_cartera_wizard')
    if car_wizard and car_wizard.get('paso') in ('fscore_min', 'fscore_max'):
        return [
            ('0 (sin piso/techo)', '0'), ('3', '3'), ('5', '5'),
            ('6', '6'), ('7', '7'), ('9 (sin límite)', '9'),
        ]

    wizard = st.session_state.get('ia_wizard')
    if wizard:
        campos = _campos_registro(wizard['tipo'], ctx)
        if wizard['paso'] < len(campos):
            campo = campos[wizard['paso']]
            if campo['tipo'] == 'opciones':
                pares = [(o, o) for o in campo['opciones']]
                if campo.get('opcional'):
                    pares.append(('➖ Omitir / usar por defecto', '-'))
                return pares

    return None


def _render_botones_rapidos(pares, turno):
    """Dibuja los botones en filas y devuelve el valor del que se haya
    tocado en esta ejecución (o None). `turno` (largo del historial de
    mensajes) entra en la key para que cada tanda de botones sea única."""
    seleccion = None
    n_cols = 2 if len(pares) <= 2 else 3
    for i in range(0, len(pares), n_cols):
        fila = pares[i:i + n_cols]
        cols = st.columns(len(fila))
        for j, (label, valor) in enumerate(fila):
            with cols[j]:
                if st.button(label, use_container_width=True, key=f'ia_btn_{turno}_{i}_{j}'):
                    seleccion = valor
    return seleccion


# ==============================================================
#  UI DE CHAT
# ==============================================================

# Labels cortos para que no se corten con "..." en el panel flotante
_SUGERENCIAS_RAPIDAS = [
    "📉 Sectores Baratos",
    "🏦 Analizar ETFs",
    "📊 Analizar Acción",
    "🧩 Armar Cartera",
    "✍️ Registrar",
]

MESES_ES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]

_CSS_CHIPS_IA = """
<style>
/* Chips de sugerencia: texto completo, sin puntos suspensivos */
html body div[class*="st-key-ia_sug_"] .stButton > button {
    padding: 6px 6px !important;
    min-height: 36px !important;
    white-space: nowrap !important;
}
html body div[class*="st-key-ia_sug_"] .stButton > button p,
html body div[class*="st-key-ia_sug_"] .stButton > button div {
    font-size: 11.5px !important;
    white-space: nowrap !important;
    overflow: visible !important;
    text-overflow: clip !important;
}
.ia-badge {
    display:inline-flex; align-items:center; gap:6px;
    font-size:11px; color:#7ee787;
    background:rgba(63,185,80,0.10); border:1px solid rgba(63,185,80,0.35);
    border-radius:999px; padding:3px 10px; margin:2px 0 8px 0;
}
.ia-badge-dot { width:7px; height:7px; border-radius:50%; background:#3fb950;
                box-shadow:0 0 6px #3fb950; display:inline-block; }
</style>
"""

# (nombre, claves de ctx que deben existir). Los que tienen [] son propios del asistente.
_MODULOS_IA = [
    ('Corto Plazo', ['scores_corto']),
    ('Largo Plazo', ['analizar_largo']),
    ('Fundamental', ['analizar_fundamental']),
    ('Top-Down Cuant.', ['_tdc_analizar_ticker']),
    ('Régimen HMM', ['calcular_regimen_hmm']),
    ('Perfil de empresa', ['obtener_perfil_empresa']),
    ('Sectores / Países / Mercados', ['cargar_sectores_corto', 'cargar_paises_corto']),
    ('Mercados reales', ['MERCADOS_REALES', 'cargar_mercados_corto']),
    ('Finanzas Personales', ['fd', 'supabase']),
    ('Glosario', ['GLOSARIO']),
    ('F-Score', []),
    ('Optimizador Monte Carlo', []),
    ('GEX', ['gex_resumen']),
    ('COT', ['cot_resumen']),
    ('Velas', ['velas_resumen']),
    ('Opciones', ['opciones_resumen']),
]


def _render_badge_modulos(ctx):
    activos = [n for n, claves in _MODULOS_IA if all(ctx.get(c) is not None for c in claves)]
    st.markdown(
        f'<div class="ia-badge" title="{" · ".join(activos)}">'
        f'<span class="ia-badge-dot"></span>Conectado a {len(activos)} módulos en vivo</div>',
        unsafe_allow_html=True,
    )


# El chat corre como fragmento: escribir un mensaje o tocar un botón solo
# re-ejecuta este bloque y no toda la página de fondo (mucho más rápido).
@st.fragment
def modulo_ia_asistente(ctx, compacto=False):
    if not ctx.get('tiene_acceso_pro'):
        st.markdown("""
        <div style="background:linear-gradient(135deg,#1a0d20 0%,#150a30 50%,#0d1117 100%);
             border:1px solid #21262d; border-top:2px solid #bc8cff;
             border-radius:14px; padding:24px 18px; text-align:center; margin-top:10px;">
          <div style="font-size:32px;margin-bottom:8px">🔒🤖</div>
          <div style="font-size:15px;font-weight:700;color:#e6edf3;margin-bottom:6px">
            El Asistente IA es exclusivo del plan Pro
          </div>
          <div style="font-size:12px;color:#8b949e">
            Actualizá tu plan para analizar activos, armar carteras automáticas y registrar movimientos por chat.
          </div>
        </div>
        """, unsafe_allow_html=True)
        return

    if not compacto:
        st.markdown("""
        <div style="background:linear-gradient(135deg,#0d1520 0%,#1a0d30 50%,#0d1117 100%);
             border:1px solid #21262d; border-top:2px solid #bc8cff;
             border-radius:14px; padding:22px 26px; margin-bottom:18px;">
          <div style="font-size:17px;font-weight:700;color:#e6edf3;margin-bottom:4px">🤖 Asistente Capital+</div>
          <div style="font-size:12px;color:#6b7d9a">Preguntame por cualquier módulo de la app, pedime que registre un gasto/ingreso, o decime "armame una cartera con..." para el pipeline automático. ⚠️ No es asesoramiento financiero.</div>
        </div>
        """, unsafe_allow_html=True)

    if 'ia_mensajes' not in st.session_state:
        st.session_state['ia_mensajes'] = []

    st.markdown(_CSS_CHIPS_IA, unsafe_allow_html=True)
    _render_badge_modulos(ctx)

    pares_botones = _opciones_pendientes_botones(ctx)

    sugerencia_click = None
    if not pares_botones:
        n_cols_sug = 2 if compacto else len(_SUGERENCIAS_RAPIDAS)
        for i in range(0, len(_SUGERENCIAS_RAPIDAS), n_cols_sug):
            fila = _SUGERENCIAS_RAPIDAS[i:i + n_cols_sug]
            cols_sug = st.columns(len(fila))
            for j, (col, sug) in enumerate(zip(cols_sug, fila)):
                with col:
                    if st.button(sug, use_container_width=True, key=f'ia_sug_{i + j}'):
                        sugerencia_click = sug

    # Caja con scroll fija en modo flotante; normal en pantalla completa
    caja = st.container(height=340) if compacto else st.container()

    with caja:
        for msg in st.session_state['ia_mensajes']:
            with st.chat_message(msg['role'], avatar='🤖' if msg['role'] == 'assistant' else None):
                st.markdown(msg['content'])

    boton_click = None
    if pares_botones:
        boton_click = _render_botones_rapidos(pares_botones, len(st.session_state['ia_mensajes']))

    chat_val = st.chat_input(
        "Preguntame algo..." if not pares_botones else "...o escribí tu respuesta acá"
    )
    prompt = sugerencia_click or boton_click or chat_val
    if prompt:
        st.session_state['ia_mensajes'].append({"role": "user", "content": prompt})
        with caja:
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant", avatar='🤖'):
                with st.spinner("Analizando..."):
                    resp = responder(prompt, ctx)
                st.markdown(resp)
        st.session_state['ia_mensajes'].append({"role": "assistant", "content": resp})
        st.rerun(scope="fragment")

    if st.button('🗑️ Limpiar conversación', key='ia_clear', use_container_width=True):
        st.session_state['ia_mensajes'] = []
        st.session_state['ia_pendiente_mov'] = None
        st.session_state['ia_pendiente_tipo'] = None
        st.session_state['ia_pendiente_registro'] = None
        st.session_state['ia_wizard'] = None
        st.session_state['ia_cartera_wizard'] = None
        st.session_state['ia_registro_menu_pendiente'] = False
        st.session_state['ia_esperando_ticker'] = False
        st.session_state['ia_ultimo_ticker'] = None
        st.session_state['ia_esperando_plan'] = False
        st.session_state['ia_cache_analisis'] = {}
        st.rerun(scope="fragment")

# ==============================================================
#  SNIPPET DE INTEGRACIÓN EN app.py (referencia, no se ejecuta)
# ==============================================================
#
#   UNIVERSO_TICKERS_VALIDOS = (
#       set(ALL_TICKERS)
#       | {v[0] for v in MERCADOS_REALES.values()}
#       | {v[0] for v in ETFS.values()}
#       | {v[0] for v in SECTORES_TOTAL.values()}
#       | {v[0] for v in PAISES.values()}
#   )
#
#   CTX_IA = dict(
#       ...,
#       ACCIONES_POR_INDUSTRIA=ACCIONES_POR_INDUSTRIA,
#       MERCADOS_REALES=MERCADOS_REALES,
#       FOREX=FOREX,
#       PAISES=PAISES,
#       ETFS=ETFS,
#       SECTORES_TOTAL=SECTORES_TOTAL,
#       UNIVERSO_TICKERS_VALIDOS=UNIVERSO_TICKERS_VALIDOS,
#       calcular_rsi=calcular_rsi,
#       calcular_regimen_hmm=calcular_regimen_hmm,
#       obtener_perfil_empresa=obtener_perfil_empresa,
#       resumen_visual_fundamental=_resumen_visual_fundamental,
#       # Opcionales (reciben el ticker y devuelven UNA línea de texto o None):
#       # gex_resumen=..., cot_resumen=..., velas_resumen=..., opciones_resumen=...,
#       # gex_niveles=...  (dict con spot, call_wall, put_wall, flip, regimen,
#       #                   squeeze_score, inminente) para la Conclusión con GEX
#   )
#
# En app.py también:
#   - pausar st_autorefresh cuando st.session_state['ia_chat_abierto'] sea True
#   - cachear cargar_precios_inicio_base / cargar_precios_acciones_inicio
#     con @st.cache_data(ttl=300, show_spinner=False)
# ==============================================================
