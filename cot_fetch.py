# ==============================================================
#  cot_fetch.py — Trae COT (Disaggregated) y TFF desde la API
#  pública de la CFTC y los sube a Supabase con las funciones
#  de upsert de modulo_cot.py / modulo_tff.py
# ==============================================================
import requests
import pandas as pd
import numpy as np
import streamlit as st

CFTC_BASE = "https://publicreporting.cftc.gov/resource/{ds}.json"
DS_COT = "72hh-3qpy"   # Disaggregated Futures Only
DS_TFF = "gpe5-46if"   # TFF Futures Only

# Nombre que se guarda en tu app -> código de contrato CFTC.
# ⚠️ Verificá los códigos con la columna cftc_contract_market_code
# la primera vez; agregá/sacá los que uses.
WATCHLIST_COT = {
    "GOLD": "088691",
    "SILVER": "084691",
    "COPPER": "085692",
    "WTI": "067651",
}
WATCHLIST_TFF = {
    "E-MINI S&P 500": "13874A",
    "NASDAQ MINI": "209742",
    "EURO FX": "099741",
    "BITCOIN": "133741",
}

# Columna de tu DataFrame -> lista de nombres posibles en la CFTC
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


def _cftc_descargar(dataset, watchlist, desde="2020-01-01"):
    codigos = ",".join(f"'{c}'" for c in watchlist.values())
    params = {
        "$where": f"cftc_contract_market_code in({codigos}) "
                  f"AND report_date_as_yyyy_mm_dd >= '{desde}T00:00:00.000'",
        "$order": "report_date_as_yyyy_mm_dd ASC",
        "$limit": 50000,
    }
    r = requests.get(CFTC_BASE.format(ds=dataset), params=params, timeout=60)
    r.raise_for_status()
    return pd.DataFrame(r.json())


def _cftc_a_formato_app(df_raw, watchlist, mapa, col_nombre):
    """Convierte el DataFrame crudo de la CFTC al formato de columnas
    de tu app (COT_COLUMNAS / TFF_COLUMNAS)."""
    if df_raw.empty:
        return pd.DataFrame()
    code_to_name = {v: k for k, v in watchlist.items()}
    out = pd.DataFrame()
    out['Report Date'] = pd.to_datetime(df_raw['report_date_as_yyyy_mm_dd'], errors='coerce')
    out[col_nombre] = df_raw['cftc_contract_market_code'].map(code_to_name)
    for col_app, candidatas in mapa.items():
        origen = next((c for c in candidatas if c in df_raw.columns), None)
        out[col_app] = pd.to_numeric(df_raw[origen], errors='coerce') if origen else np.nan
    return out.dropna(subset=['Report Date', col_nombre])


def sync_cot(supabase, desde="2020-01-01"):
    from modulo_cot import _cot_guardar_upsert, COT_COLUMNAS
    raw = _cftc_descargar(DS_COT, WATCHLIST_COT, desde)
    df = _cftc_a_formato_app(raw, WATCHLIST_COT, MAP_COT, 'Commodity')
    if df.empty:
        return 0, list(raw.columns)
    df = df[COT_COLUMNAS]
    _cot_guardar_upsert(supabase, df)
    return len(df), list(raw.columns)


def sync_tff(supabase, desde="2020-01-01"):
    from modulo_tff import _tff_guardar_upsert, TFF_COLUMNAS
    raw = _cftc_descargar(DS_TFF, WATCHLIST_TFF, desde)
    df = _cftc_a_formato_app(raw, WATCHLIST_TFF, MAP_TFF, 'Contract Market Name')
    if df.empty:
        return 0, list(raw.columns)
    df = df[TFF_COLUMNAS]
    _tff_guardar_upsert(supabase, df)
    return len(df), list(raw.columns)


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def _sync_diario(_supabase, clave_dia):
    """Se ejecuta como máximo UNA vez por día (cache de 24 h) cuando
    alguien abre la app. Pide solo los últimos 60 días: liviano."""
    desde = (pd.Timestamp.today() - pd.Timedelta(days=60)).strftime('%Y-%m-%d')
    n1, _ = sync_cot(_supabase, desde)
    n2, _ = sync_tff(_supabase, desde)
    return n1, n2


def auto_sync(supabase, es_admin):
    """Llamala UNA vez en app.py (solo corre si el que entra es admin,
    porque las políticas RLS solo le dejan escribir a ADMIN_EMAIL)."""
    if not es_admin:
        return
    try:
        _sync_diario(supabase, pd.Timestamp.today().strftime('%Y-%m-%d'))
    except Exception as e:
        st.warning(f'No se pudo sincronizar con la CFTC: {e}')
