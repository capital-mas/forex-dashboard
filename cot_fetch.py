# ==============================================================
#  cot_fetch.py — Trae COT (Disaggregated) y TFF desde la API
#  pública de la CFTC (desde mayo 2026) y los sube a Supabase
# ==============================================================
import requests
import pandas as pd
import numpy as np
import streamlit as st

CFTC_BASE = "https://publicreporting.cftc.gov/resource/{ds}.json"
DS_COT = "72hh-3qpy"   # Disaggregated Futures Only
DS_TFF = "gpe5-46if"   # TFF Futures Only

FECHA_DESDE = "2026-05-01"

# Alias que se guarda en tu app -> lista de nombres CFTC posibles
# (se compara contra el INICIO del nombre oficial, en mayúsculas;
#  se usa el primer candidato que exista)
WATCHLIST_COT = {
    "SOYBEANS":    ["SOYBEANS - CHICAGO BOARD OF TRADE"],
    "WTI":         ["WTI-PHYSICAL - NEW YORK MERCANTILE", "CRUDE OIL, LIGHT SWEET - NEW YORK MERCANTILE"],
    "SILVER":      ["SILVER - COMMODITY EXCHANGE"],
    "CORN":        ["CORN - CHICAGO BOARD OF TRADE"],
    "COPPER":      ["COPPER- #1 - COMMODITY EXCHANGE", "COPPER-GRADE #1 - COMMODITY EXCHANGE", "COPPER - COMMODITY EXCHANGE"],
    "GOLD":        ["GOLD - COMMODITY EXCHANGE"],
    "PLATINUM":    ["PLATINUM - NEW YORK MERCANTILE"],
    "NATURAL GAS": ["NAT GAS NYME - NEW YORK MERCANTILE", "NATURAL GAS - NEW YORK MERCANTILE"],
    "WHEAT":       ["WHEAT-SRW - CHICAGO BOARD OF TRADE", "WHEAT - CHICAGO BOARD OF TRADE"],
    "BRENT":       ["BRENT LAST DAY - NEW YORK MERCANTILE", "BRENT"],
}

WATCHLIST_TFF = {
    "RUSSELL 2000":      ["RUSSELL E-MINI - CHICAGO MERCANTILE", "RUSSELL 2000"],
    "ETHEREUM":          ["ETHER CASH SETTLED - CHICAGO MERCANTILE", "ETHER - CHICAGO MERCANTILE", "ETHER"],
    "SOLANA":            ["SOLANA", "SOL - CHICAGO MERCANTILE"],
    "BITCOIN":           ["BITCOIN - CHICAGO MERCANTILE"],
    "DOW JONES":         ["DJIA", "DOW JONES"],
    "NASDAQ 100":        ["NASDAQ MINI - CHICAGO MERCANTILE", "NASDAQ-100 CONSOLIDATED"],
    "NIKKEI":            ["NIKKEI STOCK AVERAGE - CHICAGO MERCANTILE", "NIKKEI"],
    "SP500":             ["S&P 500 CONSOLIDATED"],
    "AUSTRALIAN DOLLAR": ["AUSTRALIAN DOLLAR - CHICAGO MERCANTILE", "AUSTRALIAN DOLLAR"],
    "AVALANCHE":         ["AVALANCHE", "AVAX"],
    "EURO FX":           ["EURO FX - CHICAGO MERCANTILE", "EURO FX"],
    "BRITISH POUND":     ["BRITISH POUND - CHICAGO MERCANTILE", "BRITISH POUND"],
    "CANADIAN DOLLAR":   ["CANADIAN DOLLAR - CHICAGO MERCANTILE", "CANADIAN DOLLAR"],
    "CHAINLINK":         ["CHAINLINK", "LINK - CHICAGO MERCANTILE"],
    "JAPANESE YEN":      ["JAPANESE YEN - CHICAGO MERCANTILE", "JAPANESE YEN"],
    "NZ DOLLAR":         ["NZ DOLLAR", "NEW ZEALAND DOLLAR"],
    "SWISS FRANC":       ["SWISS FRANC - CHICAGO MERCANTILE", "SWISS FRANC"],
    "USD INDEX":         ["USD INDEX - ICE FUTURES U.S.", "U.S. DOLLAR INDEX", "USD INDEX"],
}
# Todos los mercados que empiecen con esto se incluyen (E-mini S&P 500 + todos los sectores)
PREFIJOS_MULTI_TFF = ["E-MINI S&P"]

MAP_COT = {
    'Open Interest': ['open_interest_all'],
    'Producer/Merchant Long': ['prod_merc_positions_long', 'prod_merc_positions_long_all'],
    'Producer/Merchant Short': ['prod_merc_positions_short', 'prod_merc_positions_short_all'],
    'Producer/Merchant Spread': [],  # la CFTC no lo publica
    'Swap Dealers Long': ['swap_positions_long_all', 'swap__positions_long_all'],
    'Swap Dealers Short': ['swap__positions_short_all', 'swap_positions_short_all'],
    'Swap Dealers Spread': ['swap__positions_spread_all', 'swap_positions_spread_all'],
    'Managed Money Long': ['m_money_positions_long_all', 'm_money_positions_long'],
    'Managed Money Short': ['m_money_positions_short_all', 'm_money_positions_short'],
    'Managed Money Spread': ['m_money_positions_spread', 'm_money_positions_spread_all'],
    'Other Reportables Long': ['other_rept_positions_long', 'other_rept_positions_long_all'],
    'Other Reportables Short': ['other_rept_positions_short', 'other_rept_positions_short_all'],
    'Other Reportables Spread': ['other_rept_positions_spread', 'other_rept_positions_spread_all'],
}
MAP_TFF = {
    'Open Interest': ['open_interest_all'],
    'Asset Manager Long': ['asset_mgr_positions_long', 'asset_mgr_positions_long_all'],
    'Asset Manager Short': ['asset_mgr_positions_short', 'asset_mgr_positions_short_all'],
    'Asset Manager Spread': ['asset_mgr_positions_spread', 'asset_mgr_positions_spread_all'],
    'Leveraged Funds Long': ['lev_money_positions_long', 'lev_money_positions_long_all'],
    'Leveraged Funds Short': ['lev_money_positions_short', 'lev_money_positions_short_all'],
    'Leveraged Funds Spread': ['lev_money_positions_spread', 'lev_money_positions_spread_all'],
    'Dealer Long': ['dealer_positions_long_all', 'dealer_positions_long'],
    'Dealer Short': ['dealer_positions_short_all', 'dealer_positions_short'],
    'Dealer Spread': ['dealer_positions_spread_all', 'dealer_positions_spread'],
    'Other Reportables Long': ['other_rept_positions_long', 'other_rept_positions_long_all'],
    'Other Reportables Short': ['other_rept_positions_short', 'other_rept_positions_short_all'],
    'Other Reportables Spread': ['other_rept_positions_spread', 'other_rept_positions_spread_all'],
}


def _like(pref):
    return pref.upper().replace("'", "''") + "%"


def _cftc_descargar(dataset, watchlist, prefijos_multi=(), desde=FECHA_DESDE):
    prefijos = [p for cands in watchlist.values() for p in cands] + list(prefijos_multi)
    filtro_nombres = " OR ".join(f"upper(market_and_exchange_names) like '{_like(p)}'" for p in prefijos)
    params = {
        "$where": f"report_date_as_yyyy_mm_dd >= '{desde}T00:00:00.000' AND ({filtro_nombres})",
        "$order": "report_date_as_yyyy_mm_dd ASC",
        "$limit": 50000,
    }
    r = requests.get(CFTC_BASE.format(ds=dataset), params=params, timeout=90)
    r.raise_for_status()
    return pd.DataFrame(r.json())


def _resolver_nombres(df_raw, watchlist, prefijos_multi=()):
    """Devuelve ({nombre_cftc_en_mayusculas: alias}, [alias_no_encontrados])."""
    nombres = sorted(df_raw['market_and_exchange_names'].astype(str).str.upper().unique()) if not df_raw.empty else []
    asignados, faltantes = {}, []
    for alias, candidatos in watchlist.items():
        for pref in candidatos:
            coincide = [n for n in nombres if n.startswith(pref.upper())]
            if coincide:
                asignados[coincide[0]] = alias   # un solo mercado por alias
                break
        else:
            faltantes.append(alias)
    for pref in prefijos_multi:
        for n in nombres:
            if n.startswith(pref.upper()):
                asignados.setdefault(n, n.split(' - ')[0].strip())
    return asignados, faltantes


def _cftc_a_formato_app(df_raw, asignados, mapa, col_nombre):
    if df_raw.empty or not asignados:
        return pd.DataFrame()
    df_raw = df_raw.copy()
    df_raw['_n'] = df_raw['market_and_exchange_names'].astype(str).str.upper()
    df_raw = df_raw[df_raw['_n'].isin(asignados.keys())]
    out = pd.DataFrame(index=df_raw.index)
    out['Report Date'] = pd.to_datetime(df_raw['report_date_as_yyyy_mm_dd'], errors='coerce')
    out[col_nombre] = df_raw['_n'].map(asignados)
    for col_app, candidatas in mapa.items():
        origen = next((c for c in candidatas if c in df_raw.columns), None)
        out[col_app] = pd.to_numeric(df_raw[origen], errors='coerce') if origen else np.nan
    out = out.dropna(subset=['Report Date', col_nombre])
    return out.drop_duplicates(subset=[col_nombre, 'Report Date'], keep='last')


def _sync(supabase, dataset, watchlist, multi, mapa, col_nombre, columnas, guardar):
    raw = _cftc_descargar(dataset, watchlist, multi)
    asignados, faltantes = _resolver_nombres(raw, watchlist, multi)
    df = _cftc_a_formato_app(raw, asignados, mapa, col_nombre)
    reporte = {'encontrados': {a: n for n, a in asignados.items()}, 'faltantes': faltantes}
    if df.empty:
        return 0, reporte
    guardar(supabase, df[columnas])
    return len(df), reporte


def sync_cot(supabase):
    from modulo_cot import _cot_guardar_upsert, COT_COLUMNAS
    return _sync(supabase, DS_COT, WATCHLIST_COT, (), MAP_COT, 'Commodity', COT_COLUMNAS, _cot_guardar_upsert)


def sync_tff(supabase):
    from modulo_tff import _tff_guardar_upsert, TFF_COLUMNAS
    return _sync(supabase, DS_TFF, WATCHLIST_TFF, PREFIJOS_MULTI_TFF, MAP_TFF,
                 'Contract Market Name', TFF_COLUMNAS, _tff_guardar_upsert)


def buscar_mercados(tipo, texto):
    """Busca en la CFTC cómo figura exactamente un mercado (para ajustar la watchlist)."""
    ds = DS_COT if tipo == 'cot' else DS_TFF
    t = texto.upper().replace("'", "''").strip()
    params = {
        "$select": "market_and_exchange_names,cftc_contract_market_code",
        "$where": f"report_date_as_yyyy_mm_dd >= '{FECHA_DESDE}T00:00:00.000' "
                  f"AND upper(market_and_exchange_names) like '%{t}%'",
        "$limit": 5000,
    }
    r = requests.get(CFTC_BASE.format(ds=ds), params=params, timeout=60)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    return df.drop_duplicates().reset_index(drop=True) if not df.empty else df


def ui_sincronizar(supabase, tipo):
    """Botón de sincronización + reporte + buscador de nombres. tipo = 'cot' | 'tff'."""
    k_rep = f'{tipo}_sync_rep'
    if st.button(f'🔄 Sincronizar con CFTC (desde {FECHA_DESDE})', key=f'{tipo}_sync_cftc'):
        try:
            fn = sync_cot if tipo == 'cot' else sync_tff
            n, rep = fn(supabase)
            st.session_state[k_rep] = (n, rep)
            st.rerun()
        except Exception as e:
            st.error(f'❌ Error al sincronizar: {e}')

    if k_rep in st.session_state:
        n, rep = st.session_state[k_rep]
        st.success(f'{n} filas sincronizadas desde la CFTC.')
        if rep['faltantes']:
            st.warning('No encontré en la CFTC: ' + ', '.join(rep['faltantes']) +
                       '. Usá el buscador de abajo para ver cómo figura el nombre exacto.')
        with st.expander('Ver qué mercado de la CFTC se usó para cada activo'):
            st.dataframe(pd.DataFrame(
                [{'Activo en tu app': a, 'Mercado CFTC': n_} for a, n_ in rep['encontrados'].items()]
            ), use_container_width=True, hide_index=True)

    with st.expander('🔎 Buscar el nombre exacto de un mercado en la CFTC'):
        txt = st.text_input('Texto a buscar (ej: gold, solana, yen)', key=f'{tipo}_buscar_txt')
        if txt.strip():
            try:
                res = buscar_mercados(tipo, txt)
                if res.empty:
                    st.info('Sin resultados.')
                else:
                    st.dataframe(res, use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(f'Error al buscar: {e}')


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def _sync_diario(_supabase, clave_dia):
    n1, _ = sync_cot(_supabase)
    n2, _ = sync_tff(_supabase)
    return n1, n2


def auto_sync(supabase, es_admin):
    """Una vez por día como máximo, solo si entra el admin (RLS)."""
    if not es_admin:
        return
    try:
        _sync_diario(supabase, pd.Timestamp.today().strftime('%Y-%m-%d'))
    except Exception as e:
        st.warning(f'No se pudo sincronizar con la CFTC: {e}')
