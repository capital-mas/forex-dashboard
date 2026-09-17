# modulo_ia_asistente.py
import re
import random
import streamlit as st

# ── Palabras clave por intención (orden de prioridad) ──
_PATRONES_INTENCION = [
    ('finanzas',      [r'\bmis?\s+finanzas\b', r'\bmis?\s+gastos?\b', r'\bmi\s+presupuesto\b',
                        r'\bcu[aá]nto\s+gast', r'\bmis?\s+deudas?\b', r'\bmi\s+ahorro\b',
                        r'\bmis?\s+ingresos?\b', r'\bmi\s+situaci[oó]n\s+financiera\b']),
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


def extraer_tickers(texto, universo_valido, ctx_validar):
    """Busca tokens que parezcan tickers y los valida contra el universo conocido de la app
    (evita falsos positivos con palabras comunes en mayúscula)."""
    candidatos = re.findall(r'\b[A-Za-z]{1,6}(?:[.\-=\^][A-Za-z0-9]{1,4})?\b', texto)
    encontrados = []
    for c in candidatos:
        c_norm = c.upper()
        if c_norm in universo_valido:
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
