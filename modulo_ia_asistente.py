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
            "Respondé con el número o el nombre. Te voy a ir pidiendo los datos uno por uno.")


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
    marca_opcional = " _(opcional — escribí '-' para dejarlo vacío/por defecto)_" if campo.get('opcional') else ""
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
#  ⚠️ AJUSTAR: el nombre/firma exacto de la función depende de tu
#  finanzas_data.py. Se prueban varios nombres/firmas comunes; si
#  ninguno coincide, decilo y actualizamos esta función una sola vez.
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

    # ── 1.7) ¿Hay un wizard de carga de datos en curso? ──
    if st.session_state.get('ia_wizard'):
        return _continuar_wizard(texto_usuario, ctx)

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
- **✍️ Registrar movimientos** — *"anotá que gasté 5000 en comida"*, *"registrá un ingreso de 200000 por sueldo"*, o simplemente escribí *"registrar"* para elegir entre Ingreso, Gasto, Deuda, Inversión Corto/Largo Plazo, Trading u Objetivo y te voy pidiendo los datos uno por uno
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
        # Sin monto no hay forma de armar el registro rápido en una sola frase
        # (ej: click en el botón "Registrar"), así que mostramos el menú
        # completo de qué se puede cargar y arrancamos el wizard campo a campo.
        st.session_state['ia_registro_menu_pendiente'] = True
        return _texto_menu_registro()

    tipo = detectar_tipo_movimiento(texto)

    # Antes esto caía silenciosamente en 'gasto' cuando no se detectaba nada,
    # lo cual cargaba ingresos como gastos. Ahora, si es ambiguo, preguntamos
    # en vez de adivinar mal.
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
    "📉 Sectores más baratos",
    "📊 Analizar una acción",
    "✍️ Registrar",
]

MESES_ES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
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
        st.session_state['ia_pendiente_tipo'] = None
        st.session_state['ia_pendiente_registro'] = None
        st.session_state['ia_wizard'] = None
        st.session_state['ia_registro_menu_pendiente'] = False
        st.rerun()
