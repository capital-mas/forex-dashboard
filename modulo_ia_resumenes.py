# ==============================================================
#  RESÚMENES DE UNA LÍNEA para el Asistente IA
#  (GEX, COT, Velas, Opciones). Cada función recibe el ticker y
#  devuelve un str o None. Si algo falla, el asistente la omite
#  (responder() ya las llama dentro de _a_safe).
#
#  Uso en app.py:
#      from modulo_ia_resumenes import crear_resumenes
#      RES_IA = crear_resumenes(supabase, descargar_datos)
# ==============================================================

from datetime import date, datetime

import numpy as np
import pandas as pd

_SIN_OPCIONES = ('=X', '=F', '-USD')   # forex, futuros y cripto no tienen cadena de opciones


# ──────────────────────────────────────────────────────────────
#  GEX
# ──────────────────────────────────────────────────────────────
def _gex_calc(tk, n_vtos=6, rango=0.20, r=0.045, q=0.0, mult=100):
    import modulo_gex as G
    t = tk.upper()
    if t.endswith(_SIN_OPCIONES):
        return None

    cboe, simbolo, _ = G.resolver_simbolo(t)
    datos = G._gex_descargar(cboe)            # cacheado 5 min
    S = datos['spot']
    df, _ = G.preparar_cadena(datos['df'], n_vtos)
    if df is None:
        return None
    df, _ = G.reparar_delta(df, S, r, q)

    piv = G.calcular_gex_por_strike(df, S, r, q, mult, rango)
    piv_d = G.calcular_dex_por_strike(df, S, mult, rango)
    if piv.empty or piv_d.empty:
        return None

    grid, total = G.gex_total_vs_spot(df, S, r, q, mult)
    z = G.calcular_zonas_gex(piv, grid, total, S)
    _, tot_pc = G.calcular_put_call(G._subset_vtos(datos['df'], n_vtos))
    res_v, _ = G.calcular_gex_por_vto(df, S, r, q, mult, rango)
    sq = G.calcular_squeeze_score(piv, piv_d, tot_pc, z, S, res_v)
    return dict(S=S, z=z, sq=sq, pc=tot_pc.get('P/C OI'), simbolo=simbolo)


def _gex_resumen(tk):
    d = _gex_calc(tk)
    if not d:
        return None
    z, sq, S = d['z'], d['sq'], d['S']
    partes = [f"gamma {z['regimen']}"]
    if z['flip']:
        partes.append(f"punto de cambio {z['flip']:,.2f} ({(S / z['flip'] - 1) * 100:+.1f}% vs precio)")
    if z['call_wall']:
        partes.append(f"pared de Calls {z['call_wall']:,.2f}")
    if z['put_wall']:
        partes.append(f"pared de Puts {z['put_wall']:,.2f}")
    pc = d['pc']
    if pc is not None and not pd.isna(pc):
        partes.append(f"P/C {pc:.2f}")
    txt = f"Squeeze Score {sq['score']:.0f}/100 ({sq['nivel']})"
    if sq['inminente']:
        txt = "🚨 " + txt
    partes.append(txt)
    return " · ".join(partes) + f" · fuente {d['simbolo']} (CBOE)"


def _gex_niveles(tk):
    """Versión numérica para que el asistente arme la conclusión."""
    d = _gex_calc(tk)
    if not d:
        return None
    z, sq = d['z'], d['sq']
    return dict(spot=d['S'], flip=z['flip'], call_wall=z['call_wall'], put_wall=z['put_wall'],
                regimen=z['regimen'], squeeze_score=sq['score'], squeeze_nivel=sq['nivel'],
                inminente=sq['inminente'])

# ──────────────────────────────────────────────────────────────
#  COT  (los commodities son texto libre en tu tabla, ver mapeo)
# ──────────────────────────────────────────────────────────────
# ticker -> palabras clave que pueden aparecer en el nombre del commodity que cargaste.
# ⚠️ AJUSTALO a los nombres reales que usás en cot_data (ej. "GOLD", "WTI", "EURO FX"...).
_COT_KEYWORDS = {
    'GC=F': ['gold', 'oro'], 'GLD': ['gold', 'oro'], 'GDX': ['gold', 'oro'],
    'SI=F': ['silver', 'plata'], 'SLV': ['silver', 'plata'],
    'PL=F': ['platinum', 'platino'], 'PA=F': ['palladium', 'paladio'],
    'HG=F': ['copper', 'cobre'], 'CPER': ['copper', 'cobre'],
    'CL=F': ['wti', 'crude', 'oil', 'petroleo', 'petróleo'], 'USO': ['wti', 'crude', 'oil'],
    'BZ=F': ['brent'], 'NG=F': ['natural gas', 'gas natural', 'natgas'], 'UNG': ['natural gas', 'gas natural'],
    'ZS=F': ['soy', 'soja'], 'ZC=F': ['corn', 'maiz', 'maíz'], 'ZW=F': ['wheat', 'trigo'],
    'KC=F': ['coffee', 'cafe', 'café'], 'SB=F': ['sugar', 'azucar', 'azúcar'],
    'CT=F': ['cotton', 'algodon', 'algodón'], 'CC=F': ['cocoa', 'cacao'],
    'BTC-USD': ['bitcoin', 'btc'], 'ETH-USD': ['ether', 'eth'],
    'EURUSD=X': ['euro', 'eur'], 'GBPUSD=X': ['pound', 'gbp', 'libra'],
    'USDJPY=X': ['yen', 'jpy'], 'AUDUSD=X': ['aud', 'australian'],
    'USDCAD=X': ['cad', 'canadian'], 'USDCHF=X': ['chf', 'franc'],
    'SPY': ['s&p', 'sp500', 'e-mini'], '^GSPC': ['s&p', 'sp500', 'e-mini'],
    'QQQ': ['nasdaq'], '^NDX': ['nasdaq'],
}


def _cot_resumen(tk, supabase):
    from modulo_cot import _cot_obtener_registros, _cot_records_to_df, _cot_resumen_commodity
    kws = _COT_KEYWORDS.get(tk.upper())
    if not kws:
        return None

    df = _cot_records_to_df(_cot_obtener_registros(supabase))   # cacheado 2 min
    if df.empty:
        return None

    elegido = None
    for nombre in df['Commodity'].unique():
        if any(k in str(nombre).lower() for k in kws):
            elegido = nombre
            break
    if elegido is None:
        return None

    r = _cot_resumen_commodity(df[df['Commodity'] == elegido])
    if not r or r['score'] is None:
        return None

    txt = (f"{r['commodity']}: COT Score {r['score']:.0f}/100 ({r['score_label']}) · {r['señal_final']}"
           f" · MM Net {r['mm_net']:,.0f}")
    if r['percentil'] is not None:
        txt += f" (percentil {r['percentil']:.0f}%, {r['pct_class']})"
    if r.get('divergencia_tag') and r['divergencia_tag'] != 'SIN DIVERGENCIA RELEVANTE':
        txt += f" · {r['divergencia_tag']}"
    return txt + f" · semana {r['fecha']:%d/%m/%Y}"


# ──────────────────────────────────────────────────────────────
#  VELAS (+ rango Monte Carlo a 1 día)
# ──────────────────────────────────────────────────────────────
def _velas_resumen(tk, descargar_datos):
    import modulo_velas as V
    df = descargar_datos(tk, '6mo')
    if df is None or df.empty or not {'Open', 'High', 'Low', 'Close'}.issubset(df.columns):
        return None
    d = V.preparar_velas(df)
    if len(d) < 25:
        return None

    u = d.iloc[-1]
    pats = V._patrones_detectados(u)
    txt = (f"vela diaria {u['SEÑAL_VELA']} (score caída {int(u['SCORE_ALCISTA'])}/8, "
           f"score suba {int(u['SCORE_BAJISTA'])}/8) · RSI14 {u['RSI14']:.0f}")
    if pats:
        txt += f" · patrones: {', '.join(pats)}"

    # Monte Carlo a 1 día (mismo método que el módulo: sin drift)
    try:
        df1 = descargar_datos(tk, '1y')
        ret = V._retornos_mc(df1, '1d')
        if len(ret) >= V.MC_MIN_RETORNOS:
            S0 = float(pd.to_numeric(df1['Close'], errors='coerce').dropna().iloc[-1])
            sigma = float(ret.std(ddof=1))
            fin = V._simular_mc(S0, -0.5 * sigma ** 2, sigma, 2000)[-1]
            p5, p95 = np.percentile(fin, [5, 95])
            txt += f" · Monte Carlo 1 día: 90% entre {p5:,.2f} y {p95:,.2f} (σ diaria {sigma * 100:.2f}%)"
    except Exception:
        pass
    return txt


# ──────────────────────────────────────────────────────────────
#  OPCIONES (Yahoo): IV ATM ~30 días vs vol. histórica + straddle
# ──────────────────────────────────────────────────────────────
def _opciones_resumen(tk):
    import modulo_opciones as O
    t = tk.upper()
    if t.endswith(_SIN_OPCIONES):
        return None
    datos = O._opc_datos_activo(t)
    if datos is None:
        return None
    vtos = O._opc_vencimientos_cached(t)       # lanza si no hay cadena
    hoy = date.today()
    cands = []
    for v in vtos:
        dias = (datetime.strptime(v, '%Y-%m-%d').date() - hoy).days
        if dias >= 7:
            cands.append((abs(dias - 30), dias, v))
    if not cands:
        return None
    _, dias, vto = min(cands)

    cadena = O._opc_cadena_opciones(t, vto)
    S = datos['S']
    ivs, mids = [], []
    for lado in ('calls', 'puts'):
        f = O._opc_fila_strike_mas_cercano(cadena[lado], S)
        if f is None:
            continue
        iv = f['impliedVolatility']
        if pd.notna(iv) and 0.01 < iv < 5:
            ivs.append(float(iv))
        if pd.notna(f['bid']) and pd.notna(f['ask']) and f['bid'] > 0 and f['ask'] >= f['bid']:
            mids.append((float(f['bid']) + float(f['ask'])) / 2)
    if not ivs:
        return None

    iv_atm = float(np.mean(ivs)) * 100
    hv = datos['vol_hist'] * 100
    dif = iv_atm - hv
    lectura = ('opciones caras vs. lo que se movió' if dif > 5 else
               'opciones baratas vs. lo que se movió' if dif < -5 else 'vol. implícita en línea con la histórica')
    txt = f"vto {vto} ({dias}d): IV ATM {iv_atm:.0f}% vs vol. histórica {hv:.0f}% ({dif:+.0f} pts, {lectura})"
    if len(mids) == 2:
        txt += f" · straddle ATM ±{sum(mids) / S * 100:.1f}%"
    return txt


# ──────────────────────────────────────────────────────────────
#  FÁBRICA: devuelve el dict para sumar a CTX_IA
# ──────────────────────────────────────────────────────────────
def crear_resumenes(supabase, descargar_datos):
    return {
        'gex_resumen': _gex_resumen,
        'gex_niveles': _gex_niveles,          # ← nueva
        'cot_resumen': lambda tk: _cot_resumen(tk, supabase),
        'velas_resumen': lambda tk: _velas_resumen(tk, descargar_datos),
        'opciones_resumen': _opciones_resumen,
    }
