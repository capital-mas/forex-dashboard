# modulo_ia_asistente.py
# ==============================================================
#  ASISTENTE IA — v4
#  Cubre: análisis COMPLETO de ticker (todos los módulos + resumen
#  compuesto), comparador, oportunidades (sectores/países/mercados/
#  subsectores), simulador, glosario, finanzas personales (lectura +
#  REGISTRO de movimientos con confirmación y botones rápidos),
#  Top-Down Cuantitativo, F-Score, Salud del Mercado, Renta Fija/
#  Macro, Opciones, Rotación/Pares, Optimizador de Cartera, y el
#  pipeline de armado de cartera end-to-end (F-Score + TDC corto/
#  largo + Optimizador Monte Carlo).
#
#  Todo lo que el asistente puede "computar" directamente depende
#  de qué funciones le pasás en `ctx` (ver diccionario CTX_IA en el
#  script principal). Si una función no está en ctx, el asistente
#  degrada con gracia: explica el módulo y te dice dónde encontrarlo
#  en la app en vez de fallar.
#
#  ⚠️ CTX_IA necesita (además de lo que ya tenías):
#      ACCIONES_POR_INDUSTRIA, calcular_rsi, calcular_regimen_hmm,
#      obtener_perfil_empresa, resumen_visual_fundamental
#  Opcionales (una línea de texto por ticker, o None):
#      gex_resumen, cot_resumen, velas_resumen, opciones_resumen
# ==============================================================

import re
import random
import difflib
from datetime import datetime, date
import numpy as np
import pandas as pd
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    # OJO: acá van tanto formas verbales (cobré, ingresé) como sustantivos
    # (ingreso, cobro) — el bug original solo cubría el verbo y por eso
    # "anotá un ingreso de 200000" caía siempre en 'gasto' por default.
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
#  RESPUESTAS
# ==============================================================

def responder(texto_usuario, ctx):
    # ── 0) ¿El asistente le preguntó qué ticker analizar? ──
    if st.session_state.pop('ia_esperando_ticker', False):
        tks = extraer_tickers(texto_usuario, ctx['UNIVERSO_TICKERS_VALIDOS'], ctx['validar_ticker'])
        if not tks:
            v = ctx['validar_ticker'](texto_usuario.strip())
            tks = [v] if v else []
        if tks:
            st.session_state['ia_ultimo_ticker'] = tks[0]
            return _responder_analizar(tks[0], ctx)
        if len(texto_usuario.split()) <= 2:
            return "No reconocí ese símbolo. Probá con algo como *NVDA*, *GGAL* o *BTC-USD*."
        # si escribió una frase larga, seguimos como mensaje normal

    # chip "📊 Analizar Acción": pregunta el ticker en vez de fallar
    if texto_usuario.strip().lower() in ('analizar acción', 'analizar accion', '📊 analizar acción'):
        st.session_state['ia_esperando_ticker'] = True
        return "¿Qué activo querés analizar? Escribime el ticker (ej: *NVDA*, *GGAL*, *BTC-USD*)."

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
                "*'armame una cartera con semiconductores y bancos'*, "
                "*'anotá que gasté 5000 en comida'*, o *'qué significa el Sharpe'*. "
                "Escribí *ayuda* para ver todo lo que puedo hacer.")
    return _responder_analizar(tickers[0], ctx)


def _respuesta_ayuda():
    return """¡Hola! 👋 Soy el asistente de Capital+. Puedo ayudarte con:

- **📊 Análisis COMPLETO de un activo** — *"analizame NVDA"*, *"cómo está el Bitcoin"*: junto corto plazo, largo plazo, Top-Down, fundamental, F-Score, régimen HMM y perfil de la empresa, y te dejo un resumen con un score compuesto
- **⚖️ Comparaciones** — *"comparar YPF vs GGAL"*
- **🎯 Oportunidades** — *"qué sectores están baratos"*, *"dame ideas en tecnología"*
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


# ── Análisis COMPLETO de ticker (todos los módulos + resumen) ────

def _a_safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:
        return None


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


def _responder_analizar(tk, ctx):
    fmt = ctx.get('fmt_precio') or (lambda p: f'{p:,.2f}')
    sin_fund = ctx['_es_activo_sin_fundamentals'](tk)
    industria = ctx['TICKER_INDUSTRY'].get(tk, 'Sin Clasificar')

    señales = []          # (nombre, score 0-100, peso)
    pros, contras = [], []
    perfil = r_corto = r_largo = res_f = hmm = fscore = None
    tdc = {}

    with ThreadPoolExecutor(max_workers=1) as ex:
        # F-Score en paralelo (solo usa yfinance, no toca Streamlit)
        fut_fs = None if sin_fund else ex.submit(_car_calcular_fscore, tk)

        # ── Perfil ───────────────────────────────────────────
        if not sin_fund and ctx.get('obtener_perfil_empresa'):
            perfil = _a_safe(ctx['obtener_perfil_empresa'], tk)

        # ── Corto plazo ──────────────────────────────────────
        df_v = _a_safe(ctx['descargar_datos'], tk, '3mo')
        df_m = _a_safe(ctx['descargar_datos'], tk, '1mo')
        if df_v is not None and df_m is not None:
            cl_v = ctx['get_close_series'](df_v)
            cl_m = ctx['get_close_series'](df_m)
            if cl_v is not None and cl_m is not None and len(cl_v.dropna()) >= 15:
                atr = ctx['calcular_atr'](df_m)
                sa, sn, ss = ctx['scores_corto'](cl_v, cl_m, atr)
                rsi = None
                if ctx.get('calcular_rsi'):
                    rsi = _a_safe(lambda: float(ctx['calcular_rsi'](cl_m, p=7).iloc[-1]))
                r_corto = dict(
                    sa=sa, sn=sn, ss=ss, sf=sa * 0.45 + sn * 0.35 + ss * 0.20,
                    señal=ctx['señal_accion_corto'](sa, sn, ss), precio=float(cl_m.iloc[-1]), rsi=rsi,
                    ret5=float(cl_m.pct_change(5).iloc[-1] * 100) if len(cl_m) >= 6 else None,
                    ret10=float(cl_m.pct_change(10).iloc[-1] * 100) if len(cl_m) >= 11 else None,
                )

        # ── Régimen HMM ──────────────────────────────────────
        if ctx.get('calcular_regimen_hmm'):
            df_6 = _a_safe(ctx['descargar_datos'], tk, '6mo')
            cl_6 = ctx['get_close_series'](df_6) if df_6 is not None else None
            if cl_6 is not None:
                hmm = _a_safe(ctx['calcular_regimen_hmm'], cl_6)

        # ── Largo plazo ──────────────────────────────────────
        df_l = _a_safe(ctx['descargar_datos'], tk, '2y')
        cl_l = ctx['get_close_series'](df_l) if df_l is not None else None
        if cl_l is not None and len(cl_l) >= 150:
            r_largo = _a_safe(ctx['analizar_largo'], tk, cl_l)

        # ── Top-Down Cuantitativo (MP / LP) ──────────────────
        fn_tdc, hz_cfg = ctx.get('_tdc_analizar_ticker'), ctx.get('HORIZONTES_TDC')
        if fn_tdc and hz_cfg:
            for hz in ('MP', 'LP'):
                if hz in hz_cfg:
                    d = _a_safe(fn_tdc, tk, hz_cfg[hz])
                    if d:
                        tdc[hz] = d

        # ── Fundamental ──────────────────────────────────────
        if not sin_fund:
            res_f = _a_safe(ctx['analizar_fundamental'], tk, industria)

        fscore = _a_safe(fut_fs.result) if fut_fs else None

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
    nombre = (perfil or {}).get('nombre') or tk
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
        upside = None
        if res_f.get('target_price') and res_f.get('precio'):
            upside = (res_f['target_price'] / res_f['precio'] - 1) * 100
        L.append(f"\n**📊 Fundamental:** señal **{res_f['senal_final']}** "
                 f"({res_f['n_ok']} positivas · {res_f['n_alt']} alertas) · analistas: {res_f.get('recommendation') or 'N/D'}"
                 + (f" · precio objetivo {fmt(res_f['target_price'])} ({upside:+.1f}%)" if upside is not None else ''))
        L.append(f"- Valuación: PER {_n(res_f.get('per'))}x · P/B {_n(res_f.get('pb'))}x · "
                 f"EV/EBITDA {_n(res_f.get('ev_ebitda'))}x · P/FCF {_n(res_f.get('p_fcf'))}x · PEG {_n(res_f.get('peg'))}")
        L.append(f"- Rentabilidad: ROE {_pf(res_f.get('roe'))} · ROIC {_pf(res_f.get('roic'))} · "
                 f"Mg. bruto {_pf(res_f.get('gross_margin'))} · Mg. neto {_pf(res_f.get('profit_margin'))}")
        L.append(f"- Crecimiento y solvencia: Ingresos {_pf(res_f.get('revenue_growth'))} · "
                 f"D/E {_n(res_f.get('debt_equity'))}x · Net Debt/EBITDA {_n(res_f.get('net_debt_ebitda'))}x · "
                 f"Beta {_n(res_f.get('beta'))} · Div. yield {_pf(res_f.get('div_yield'))}")
        if resumen_f:
            L.append(f"- Scores 0-10: Calidad {_n(resumen_f.get('calidad'), 1)} · Valoración {_n(resumen_f.get('valoracion'), 1)} · "
                     f"Crecimiento {_n(resumen_f.get('crecimiento'), 1)} · Riesgo {_n(resumen_f.get('riesgo'), 1)} "
                     f"→ {resumen_f.get('v_emoji', '')} {resumen_f.get('veredicto', '')}")
    elif not sin_fund:
        L.append("\n**📊 Fundamental:** sin datos disponibles en Yahoo Finance para este activo.")
    else:
        L.append("\n_(Cripto/forex/commodity: no tiene balance, por eso no hay Fundamental ni F-Score.)_")

    if fscore is not None:
        L.append(f"\n**🧮 F-Score (Piotroski):** {fscore:.1f}/9")

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
        r = _car_calcular_fscore(tk)
    if r is None:
        return (f"No pude calcular el F-Score de {tk} (puede no tener suficientes estados financieros "
                f"disponibles, o ser cripto/forex/commodity sin balance sheet). También lo encontrás en "
                f"🧰 Herramientas → F-Score (Piotroski).")
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
#    1) Sectores y/o tickers de interés (texto libre)
#    2) F-Score mínimo aceptable (0-9)
#    3) F-Score máximo aceptable (0-9)
#  Con eso corre TODO el pipeline y devuelve las 5 carteras candidatas.
#
#  ⚠️ Requiere que ctx tenga 'ACCIONES_POR_INDUSTRIA' (dict industria ->
#  lista de tickers).
# ==============================================================

_CAR_MAX_UNIVERSO = 25   # tope de tickers a evaluar con F-Score (evita timeouts)
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
    """F-Score de Piotroski (0-9) para UN ticker, calculado on-demand (sin
    caché de Streamlit), pensado para correr dentro de un ThreadPoolExecutor.
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


def _car_construir_universo(texto, ctx):
    """Convierte texto libre ('Semiconductores, Bancos y NVDA') en una lista
    de tickers, combinando industrias conocidas (ctx['ACCIONES_POR_INDUSTRIA'])
    y tickers sueltos validados."""
    industrias = ctx.get('ACCIONES_POR_INDUSTRIA', {})
    industrias_lower = {k.lower(): k for k in industrias.keys()}
    tickers = []
    partes = re.split(r'[,;]|\by\b|\be\b', texto, flags=re.IGNORECASE)
    for parte in partes:
        p = parte.strip(' .')
        if not p:
            continue
        pl = p.lower()
        match_ind = next(
            (real for low, real in industrias_lower.items() if low == pl or low in pl or pl in low),
            None,
        )
        if match_ind:
            tickers.extend(industrias[match_ind])
            continue
        tk_val = ctx['validar_ticker'](p)
        if tk_val:
            tickers.append(tk_val)
    return list(dict.fromkeys(tickers))


def _car_simular_cartera(tickers, ctx, simulaciones=4000, periodo='2y', rf=0.0):
    """Descarga precios (reutilizando ctx['descargar_datos']/['get_close_series'])
    y corre una simulación Monte Carlo simplificada. Devuelve (dict de 5
    carteras candidatas, lista de tickers realmente usados) o (None, None)
    si no hay suficiente historial en común."""
    precios = {}
    for tk in tickers:
        df = ctx['descargar_datos'](tk, periodo)
        cl = ctx['get_close_series'](df) if df is not None else None
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
    return ("Dale, armemos una cartera automática 🧩. Decime **sectores** (ej: *'Semiconductores, Bancos'*) "
            "y/o **tickers puntuales** (ej: *'NVDA, AAPL, KO'*) — podés combinar ambos, separados por coma.\n\n"
            "_(Voy a correr F-Score → Top-Down Cuantitativo corto/largo plazo → Optimizador Monte Carlo, "
            "así que puede tardar un rato con universos grandes — hasta 25 tickers)_")


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
        return ("No pude identificar sectores ni tickers válidos en lo que escribiste. Probá con nombres de "
                "industria tal cual aparecen en la app (ej: *'Semiconductores, Bancos'*) o tickers "
                "(ej: *'NVDA, AAPL, KO'*).")

    truncado = len(tickers_universo) > _CAR_MAX_UNIVERSO
    if truncado:
        tickers_universo = tickers_universo[:_CAR_MAX_UNIVERSO]

    # ── 1) F-Score (en paralelo) ──────────────────────────────────────
    fscores = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futuros = {ex.submit(_car_calcular_fscore, tk): tk for tk in tickers_universo}
        for fut in as_completed(futuros):
            tk = futuros[fut]
            r = fut.result()
            if r is not None:
                fscores[tk] = r

    aprobados = [tk for tk, sc in fscores.items() if fscore_min <= sc <= fscore_max]
    if len(aprobados) < 2:
        detalle = ', '.join(f'{tk} ({sc:.1f})' for tk, sc in sorted(fscores.items(), key=lambda x: -x[1])[:12])
        sin_datos = ('ninguno disponible (puede que sean cripto/forex/commodities '
                     'sin estados financieros, o poco líquidos en Yahoo Finance)')
        return (f"Con F-Score entre **{fscore_min:.1f}** y **{fscore_max:.1f}** quedaron solo "
                f"**{len(aprobados)}** activo(s) de los {len(tickers_universo)} analizados "
                f"({len(fscores)} con F-Score calculable) — necesito al menos 2 para armar una cartera.\n\n"
                f"F-Scores calculados: {detalle or sin_datos}.\n\n"
                f"Probá ampliar el rango de F-Score o sumar más sectores/tickers.")

    # ── 2) Top-Down Cuantitativo: corto plazo (scores_corto) + largo plazo (Global Score) ──
    ranking = []
    for tk in aprobados:
        sa = None
        df_v = ctx['descargar_datos'](tk, '3mo')
        df_m = ctx['descargar_datos'](tk, '1mo')
        if df_v is not None and df_m is not None:
            cl_v = ctx['get_close_series'](df_v)
            cl_m = ctx['get_close_series'](df_m)
            if cl_v is not None and cl_m is not None and len(cl_v.dropna()) >= 15:
                atr = ctx['calcular_atr'](df_m)
                sa, sn, ss = ctx['scores_corto'](cl_v, cl_m, atr)

        global_score = None
        df_l = ctx['descargar_datos'](tk, '2y')
        cl_l = ctx['get_close_series'](df_l) if df_l is not None else None
        if cl_l is not None and len(cl_l) >= 150:
            r_l = ctx['analizar_largo'](tk, cl_l)
            if r_l:
                global_score = r_l['global_score']

        if sa is None and global_score is None:
            continue
        valores_validos = [v for v in (sa, global_score) if v is not None]
        combinado = float(np.mean(valores_validos)) if valores_validos else 0.0
        ranking.append(dict(tk=tk, fscore=fscores[tk], sa=sa, global_score=global_score, combinado=combinado))

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
        f"**{len(aprobados)}** pasaron el filtro F-Score ({fscore_min:.1f}–{fscore_max:.1f}) → "
        f"top **{len(tickers_finales)}** por score cuantitativo → cartera optimizada con **{len(tickers_ok)}** activos "
        f"(los que tenían historial de precios en común)."
    )

    partes.append("\n**Ranking usado (F-Score · Corto Acum. · Largo Global Score):**")
    for r in ranking[:_CAR_TOP_N_RANKING]:
        sa_txt = f"{r['sa']:.0f}" if r['sa'] is not None else 'N/D'
        gl_txt = f"{r['global_score']:.0f}" if r['global_score'] is not None else 'N/D'
        marca = " ✅ (en cartera final)" if r['tk'] in tickers_ok else ""
        partes.append(f"- **{r['tk']}**: F-Score {r['fscore']:.1f} · Corto {sa_txt}/100 · Largo {gl_txt}/100{marca}")

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
        st.rerun()

    if st.button('🗑️ Limpiar conversación', key='ia_clear', use_container_width=True):
        st.session_state['ia_mensajes'] = []
        st.session_state['ia_pendiente_mov'] = None
        st.session_state['ia_pendiente_tipo'] = None
        st.session_state['ia_pendiente_registro'] = None
        st.session_state['ia_wizard'] = None
        st.session_state['ia_cartera_wizard'] = None
        st.session_state['ia_registro_menu_pendiente'] = False
        st.session_state['ia_esperando_ticker'] = False
        st.rerun()

# ==============================================================
#  SNIPPET DE INTEGRACIÓN EN app.py (referencia, no se ejecuta)
# ==============================================================
#
# Al diccionario CTX_IA de app.py agregarle estas claves:
#
#   CTX_IA = dict(
#       ...,
#       ACCIONES_POR_INDUSTRIA=ACCIONES_POR_INDUSTRIA,
#       calcular_rsi=calcular_rsi,
#       calcular_regimen_hmm=calcular_regimen_hmm,
#       obtener_perfil_empresa=obtener_perfil_empresa,
#       resumen_visual_fundamental=_resumen_visual_fundamental,
#       # Opcionales (reciben el ticker y devuelven UNA línea de texto o None):
#       # gex_resumen=..., cot_resumen=..., velas_resumen=..., opciones_resumen=...,
#   )
# ==============================================================
