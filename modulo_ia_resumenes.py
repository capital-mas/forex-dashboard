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
# índices de Yahoo -> símbolo que entiende CBOE
_MAPA_INDICES = {'^GSPC': 'SPX', '^SPX': 'SPX', '^NDX': 'NDX', '^RUT': 'RUT',
                 '^VIX': 'VIX', '^DJI': 'DJX'}


# ──────────────────────────────────────────────────────────────
#  GEX
# ──────────────────────────────────────────────────────────────
def _gex_calc(tk, n_vtos=6, rango=0.20, r=0.045, q=0.0, mult=100):
    import modulo_gex as G
    t = _MAPA_INDICES.get(tk.upper(), tk.upper())

    cboe, simbolo, _ = G.resolver_simbolo(t)
    # forex / futuros / cripto SIN equivalente (ETF o Deribit) no tienen cadena: se omiten
    if t.endswith(_SIN_OPCIONES) and cboe in (t, t.lstrip('^')):
        return None
    if cboe.startswith('DERIBIT:'):
        mult = 1                                  # cada contrato de Deribit = 1 unidad

    datos = G._gex_descargar(cboe)                # cacheado 5 min
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
    niv = G.calcular_niveles_clasificados(piv, S, n=5)      # ← Niveles clave de gamma
    return dict(S=S, z=z, sq=sq, pc=tot_pc.get('P/C OI'), simbolo=simbolo, niv=niv,
                proxy=(simbolo.upper() != tk.upper().lstrip('^')))


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
    """Versión numérica para la conclusión + niveles clasificados para el detalle."""
    d = _gex_calc(tk)
    if not d:
        return None
    z, sq = d['z'], d['sq']
    return dict(spot=d['S'], flip=z['flip'], call_wall=z['call_wall'], put_wall=z['put_wall'],
                regimen=z['regimen'], squeeze_score=sq['score'], squeeze_nivel=sq['nivel'],
                inminente=sq['inminente'], niveles=d['niv'],
                simbolo=d['simbolo'], proxy=d['proxy'])

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

    # Monte Carlo a 1 día (mismo método que el módulo: sin drift).
    # Los precios van con decimales completos (V.fmt_px_mc), igual que en la pestaña Monte Carlo.
    try:
        df1 = descargar_datos(tk, '1y')
        ret = V._retornos_mc(df1, '1d')
        if len(ret) >= V.MC_MIN_RETORNOS:
            S0 = float(pd.to_numeric(df1['Close'], errors='coerce').dropna().iloc[-1])
            sigma = float(ret.std(ddof=1))
            fin = V._simular_mc(S0, -0.5 * sigma ** 2, sigma, 2000)[-1]
            p5, p95 = np.percentile(fin, [5, 95])
            txt += (f" · Monte Carlo 1 día: 90% entre {V.fmt_px_mc(p5)} y {V.fmt_px_mc(p95)} "
                    f"(σ diaria {sigma * 100:.2f}%)")
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
#  POSICIONAMIENTO DETALLADO (COT / TFF) — explicación clara
#  Aparece debajo de GEX en el análisis de un activo.
# ──────────────────────────────────────────────────────────────
# ticker -> nombre (alias) con el que modulo_tff guarda el mercado (ver WATCHLIST_TFF)
_TFF_ALIAS = {
    'SPY': 'SP500', '^GSPC': 'SP500', 'ES=F': 'SP500',
    'QQQ': 'NASDAQ 100', '^NDX': 'NASDAQ 100', 'NQ=F': 'NASDAQ 100',
    'DIA': 'DOW JONES', '^DJI': 'DOW JONES', 'YM=F': 'DOW JONES',
    'IWM': 'RUSSELL 2000', '^RUT': 'RUSSELL 2000', 'RTY=F': 'RUSSELL 2000',
    '^N225': 'NIKKEI', 'EWJ': 'NIKKEI',
    'BTC-USD': 'BITCOIN', 'ETH-USD': 'ETHEREUM', 'SOL-USD': 'SOLANA',
    'AVAX-USD': 'AVALANCHE', 'LINK-USD': 'CHAINLINK',
    'EURUSD=X': 'EURO FX', 'GBPUSD=X': 'BRITISH POUND', 'USDJPY=X': 'JAPANESE YEN',
    'AUDUSD=X': 'AUSTRALIAN DOLLAR', 'NZDUSD=X': 'NZ DOLLAR',
    'USDCAD=X': 'CANADIAN DOLLAR', 'USDCHF=X': 'SWISS FRANC',
    'DX-Y.NYB': 'USD INDEX', 'UUP': 'USD INDEX',
}
# En estos pares el dólar va primero, pero el futuro es sobre la OTRA moneda (se lee al revés)
_TFF_INVERSOS = {'USDJPY=X': 'yen', 'USDCAD=X': 'dólar canadiense', 'USDCHF=X': 'franco suizo'}

_PCT_TXT = {
    'EXTREME LONG': "los fondos están **más comprados que casi nunca** en el historial cargado: queda poco margen para nuevos compradores y crece el riesgo de un techo.",
    'HIGH POSITIONING': "posicionamiento comprador alto, pero todavía sin llegar a un extremo histórico.",
    'NORMAL': "posicionamiento normal, sin extremos: por sí solo no da una señal fuerte.",
    'LOW POSITIONING': "posicionamiento vendedor marcado, pero todavía sin llegar a un extremo histórico.",
    'EXTREME SHORT': "los fondos están **más vendidos que casi nunca** en el historial cargado: es la zona típica donde un catalizador puede disparar un short squeeze.",
}


def _f(v, dec=0, signo=False):
    if v is None or pd.isna(v):
        return 'N/D'
    return f'{v:+,.{dec}f}' if signo else f'{v:,.{dec}f}'


def _cruce_net_oi(net_chg, oi_chg, quien):
    """Dinero fresco vs. cobertura: cruza el cambio del neto con el cambio del Open Interest."""
    if net_chg is None or oi_chg is None or pd.isna(net_chg) or pd.isna(oi_chg):
        return None
    if net_chg > 0 and oi_chg > 0:
        return (f"💰 **Dinero fresco comprador:** el neto de {quien} sube ({net_chg:+,.0f}) y el Open Interest "
                f"también ({oi_chg:+,.0f}). Se están abriendo contratos nuevos: hay convicción real detrás de la suba.")
    if net_chg < 0 and oi_chg > 0:
        return (f"💰 **Dinero fresco vendedor:** el neto de {quien} baja ({net_chg:+,.0f}) y el Open Interest "
                f"sube ({oi_chg:+,.0f}). Se abren posiciones vendedoras nuevas, no solo se cierran compras.")
    if net_chg > 0 and oi_chg < 0:
        return (f"🔄 **Cobertura (short covering):** el neto de {quien} mejora ({net_chg:+,.0f}) pero el Open Interest "
                f"cae ({oi_chg:+,.0f}). Mejora porque se cierran ventas, no porque entren compradores nuevos: es una suba más frágil.")
    if net_chg < 0 and oi_chg < 0:
        return (f"🔄 **Liquidación de largos:** el neto de {quien} baja ({net_chg:+,.0f}) y el Open Interest también "
                f"({oi_chg:+,.0f}). Son compradores saliendo, no vendedores nuevos entrando con fuerza.")
    return None


def _cot_buscar(tk, supabase):
    from modulo_cot import _cot_obtener_registros, _cot_records_to_df, _cot_resumen_commodity
    kws = _COT_KEYWORDS.get(tk.upper())
    if not kws:
        return None
    df = _cot_records_to_df(_cot_obtener_registros(supabase))
    if df.empty:
        return None
    elegido = next((n for n in df['Commodity'].unique()
                    if any(k in str(n).lower() for k in kws)), None)
    if elegido is None:
        return None
    r = _cot_resumen_commodity(df[df['Commodity'] == elegido])
    return r if r and r['score'] is not None else None


def _cot_detalle(tk, supabase):
    r = _cot_buscar(tk, supabase)
    if not r:
        return None
    fila = r['df'].iloc[-1]
    L = [f"---\n### 📑 COT — {r['commodity']}: ¿qué están haciendo los grandes fondos?",
         "**¿Qué es el COT?** Es el informe semanal de la CFTC (el regulador de futuros de EE.UU.) que muestra "
         "cuántos contratos tiene abierto cada tipo de trader. Sale los viernes con datos del martes, así que es "
         "una foto con unos días de atraso, y **no usa precio**: mira solo posicionamiento.",
         "- **Managed Money** = fondos especulativos (hedge funds, CTAs). Son los que empujan la tendencia, "
         "por eso el análisis se centra en ellos.\n"
         "- **Producer/Merchant** = productores y comerciales que usan los futuros para cubrir mercadería real "
         "(la \"industria\")."]

    L.append(f"\n**📊 Lectura de la semana del {r['fecha']:%d/%m/%Y}** _({r['n_semanas']} semanas cargadas)_\n\n"
             "| Dato | Valor |\n|---|--:|\n"
             f"| Managed Money Largos | {_f(r['mm_long'])} |\n"
             f"| Managed Money Cortos | {_f(r['mm_short'])} |\n"
             f"| **Neto (Largos − Cortos)** | **{_f(r['mm_net'])}** |\n"
             f"| Cambio del neto vs. semana anterior | {_f(r['mm_net_chg'], signo=True)} |\n"
             f"| Open Interest | {_f(r['oi'])} |\n"
             f"| Cambio del Open Interest | {_f(r['oi_chg'], signo=True)} |\n"
             f"| Percentil histórico | {f'{r['percentil']:.0f}%' if r['percentil'] is not None else 'N/D'} |\n"
             f"| Tendencia del neto | {r['tendencia'] or 'N/D'} |")

    L.append("\n**🧠 Cómo leerlo:**")
    net = r['mm_net']
    if net is not None and not pd.isna(net):
        lado = "apuestan a la **suba**" if net >= 0 else "apuestan a la **baja**"
        L.append(f"- **Neto:** es Largos menos Cortos. Positivo = los fondos apuestan a la suba; negativo = a la baja. "
                 f"Hoy es {net:,.0f}, o sea {lado}.")
    if r['percentil'] is not None:
        L.append(f"- **Percentil {r['percentil']:.0f}%:** compara el neto de hoy con todas las semanas cargadas — {_PCT_TXT.get(r['pct_class'], '')}")
    else:
        L.append("- **Percentil:** todavía no hay al menos 5 semanas cargadas para compararlo con su historial.")
    if r['tendencia']:
        L.append(f"- **Tendencia {r['tendencia'].lower()}:** es la pendiente del neto en las últimas semanas; sirve para "
                 "distinguir una fase sostenida de un rebote de una sola semana.")
    cruce = _cruce_net_oi(r['mm_net_chg'], r['oi_chg'], 'los fondos')
    if cruce:
        L.append(f"- {cruce}")
    if r.get('divergencia_tag') in ('DIVERGENCIA ALCISTA DE SUELO', 'DIVERGENCIA BAJISTA DE TECHO'):
        L.append(f"- 🔀 **{r['divergencia_tag']}:** {r['divergencia_texto']}")
    elif r.get('pct_producer') is not None:
        L.append(f"- **Fondos vs. industria:** no están enfrentados de forma extrema (fondos en percentil "
                 f"{r['percentil']:.0f}%, comerciales en {r['pct_producer']:.0f}%).")

    L.append(f"\n**🎯 En resumen:** {r['score_emoji']} COT Score **{r['score']:.0f}/100** ({r['score_label']}) · "
             f"señal: **{r['señal_final']}**. _0 = muy bajista, 100 = muy alcista; combina percentil, tendencia, "
             "cambio semanal, consistencia, relación largos/cortos y Open Interest._")
    L.append("_Es una lectura probabilística de posicionamiento, no una predicción de precio. El percentil se calcula "
             f"sobre las {r['n_semanas']} semanas cargadas: con poco historial hay que tomarlo con cautela._")
    return "\n".join(L)


def _tff_detalle(tk, supabase):
    from modulo_tff import _tff_obtener_registros, _tff_records_to_df, _tff_resumen_market
    alias = _TFF_ALIAS.get(tk.upper())
    if not alias:
        return None
    df = _tff_records_to_df(_tff_obtener_registros(supabase))
    if df.empty:
        return None
    g = df[df['Contract Market Name'].str.upper() == alias]
    if g.empty:
        return None
    r = _tff_resumen_market(g)
    if not r or r['score'] is None:
        return None

    L = [f"---\n### 📑 TFF — {r['market']}: ¿qué hacen los institucionales vs. los especuladores?",
         "**¿Qué es el TFF?** (Traders in Financial Futures) Es el informe semanal de la CFTC para futuros "
         "financieros: índices, divisas y cripto. Sale los viernes con datos del martes, así que tiene unos días "
         "de atraso, y **no usa precio**: mira solo posicionamiento.",
         "- **Asset Managers** = fondos institucionales de largo plazo (\"manos fuertes\"). Es el foco del análisis.\n"
         "- **Leveraged Funds** = hedge funds especulativos, más rápidos y con apalancamiento.\n"
         "- **Dealers** = bancos que dan liquidez y suelen estar del lado contrario (contexto, no señal)."]

    if tk.upper() in _TFF_INVERSOS:
        L.append(f"⚠️ **Ojo con la lectura:** el contrato es sobre el **{_TFF_INVERSOS[tk.upper()]}**. Si los "
                 f"institucionales compran {_TFF_INVERSOS[tk.upper()]}, {tk.upper().replace('=X', '')} tiende a **bajar** (y viceversa).")

    L.append(f"\n**📊 Lectura de la semana del {r['fecha']:%d/%m/%Y}** _({r['n_semanas']} semanas cargadas)_\n\n"
             "| Dato | Valor |\n|---|--:|\n"
             f"| Asset Managers Largos | {_f(r['am_long'])} |\n"
             f"| Asset Managers Cortos | {_f(r['am_short'])} |\n"
             f"| **Neto Asset Managers** | **{_f(r['am_net'])}** |\n"
             f"| Cambio del neto vs. semana anterior | {_f(r['am_net_chg'], signo=True)} |\n"
             f"| Neto Leveraged Funds | {_f(r['lev_net'])} ({_f(r['lev_net_chg'], signo=True)}) |\n"
             f"| Open Interest | {_f(r['oi'])} ({_f(r['oi_chg'], signo=True)}) |\n"
             f"| Percentil histórico (Asset Managers) | {f'{r['percentil']:.0f}%' if r['percentil'] is not None else 'N/D'} |\n"
             f"| Tendencia del neto (Asset Managers) | {r['tendencia'] or 'N/D'} |")

    L.append("\n**🧠 Cómo leerlo:**")
    net = r['am_net']
    if net is not None and not pd.isna(net):
        lado = "están posicionados para la **suba**" if net >= 0 else "están posicionados para la **baja**"
        L.append(f"- **Neto:** es Largos menos Cortos. Positivo = suba, negativo = baja. Hoy los institucionales "
                 f"tienen {net:,.0f} y {lado}.")
    if r['percentil'] is not None:
        L.append(f"- **Percentil {r['percentil']:.0f}%:** compara el neto institucional de hoy con todas las semanas cargadas — {_PCT_TXT.get(r['pct_class'], '')}")
    else:
        L.append("- **Percentil:** todavía no hay al menos 5 semanas cargadas para compararlo con su historial.")
    if r['tendencia']:
        L.append(f"- **Tendencia {r['tendencia'].lower()}:** es la pendiente del neto institucional en las últimas semanas.")
    if r.get('combinacion_tag') and r['combinacion_tag'] != 'SIN COMBINACIÓN CLARA':
        L.append(f"- 💰 **{r['combinacion_tag']}:** {r['combinacion_texto']}")
    else:
        cruce = _cruce_net_oi(r['am_net_chg'], r['oi_chg'], 'los institucionales')
        if cruce:
            L.append(f"- {cruce}")
    if r.get('divergencia_tag') and r['divergencia_tag'] != 'SIN DIVERGENCIA EXTREMA':
        L.append(f"- 🔀 **{r['divergencia_tag']}:** {r['divergencia_texto']}")
    else:
        L.append("- **Institucionales vs. especuladores:** no hay un choque extremo de posturas esta semana.")

    L.append(f"\n**🎯 En resumen:** {r['score_emoji']} TFF Score **{r['score']:.0f}/100** ({r['score_label']}) · "
             f"señal: **{r['señal_final']}**. _0 = muy bajista, 100 = muy alcista; está basado en el comportamiento "
             "de los Asset Managers (percentil, tendencia, cambio semanal, consistencia, largos/cortos y Open Interest)._")
    L.append("_Es una lectura probabilística de posicionamiento, no una predicción de precio. El percentil se calcula "
             f"sobre las {r['n_semanas']} semanas cargadas: con poco historial hay que tomarlo con cautela._")
    return "\n".join(L)


def _posicionamiento_detalle(tk, supabase):
    """TFF para índices/divisas/cripto, COT para commodities. Devuelve markdown o None."""
    primero, segundo = ((_tff_detalle, _cot_detalle) if tk.upper() in _TFF_ALIAS
                        else (_cot_detalle, _tff_detalle))
    for fn in (primero, segundo):
        try:
            txt = fn(tk, supabase)
        except Exception:
            txt = None
        if txt:
            return txt
    return None

# ──────────────────────────────────────────────────────────────
#  FÁBRICA: devuelve el dict para sumar a CTX_IA
# ──────────────────────────────────────────────────────────────
def crear_resumenes(supabase, descargar_datos):
    return {
        'gex_resumen': _gex_resumen,
        'gex_niveles': _gex_niveles,
        'cot_resumen': lambda tk: _cot_resumen(tk, supabase),
        'posicionamiento_detalle': lambda tk: _posicionamiento_detalle(tk, supabase),   # ← nueva
        'velas_resumen': lambda tk: _velas_resumen(tk, descargar_datos),
        'opciones_resumen': _opciones_resumen,
    }
