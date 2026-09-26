"""
Worker de actualización de precios — corre fuera de la app Streamlit,
disparado por GitHub Actions con cron. No depende de que haya usuarios
conectados: refresca precios_cache de forma centralizada.
"""
import os
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import yfinance as yf
from supabase import create_client

# ── Conexión a Supabase (usa variables de entorno, NO hardcodear claves) ──
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# ── Núcleo fijo de tickers que SIEMPRE se mantienen frescos ──
# (los más consultados: sectores, países principales, algunas acciones top)
NUCLEO_FIJO = [
    'SPY', 'QQQ', 'DIA', 'IWM',
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'TSLA',
    'XLK', 'XLF', 'XLV', 'XLE', 'XLY', 'XLP', 'XLI', 'XLB', 'XLU', 'XLRE', 'XLC',
    'BTC-USD', 'ETH-USD',
    'GC=F', 'CL=F', 'SI=F',
    'EURUSD=X', 'USDJPY=X',
]

PERIODOS_A_REFRESCAR = ['3mo', '2y']  # los más usados por la app


def obtener_tickers_ya_cacheados():
    """Trae todos los tickers que ya están en precios_cache (los que
    algún usuario real consultó alguna vez)."""
    try:
        res = supabase.table('precios_cache').select('ticker').execute()
        return sorted(set(row['ticker'] for row in (res.data or [])))
    except Exception as e:
        print(f'⚠️ Error leyendo tickers cacheados: {e}')
        return []


def serializar_precios(df):
    if df is None or df.empty:
        return None
    df2 = df.copy()
    df2.index = df2.index.strftime('%Y-%m-%d')
    payload = {'index': df2.index.tolist()}
    for col in df2.columns:
        payload[col] = df2[col].astype(float).tolist()
    return payload


def actualizar_ticker(ticker, period):
    try:
        d = yf.download(ticker, period=period, interval='1d',
                         progress=False, auto_adjust=True)
        if d is None or d.empty:
            return False
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
        if 'Close' not in d.columns:
            return False
        d = d.dropna(subset=['Close'])
        payload = serializar_precios(d)
        if payload is None:
            return False

        supabase.table('precios_cache').upsert({
            'ticker': ticker, 'period': period, 'datos': payload,
            'actualizado_en': datetime.now(timezone.utc).isoformat(),
        }).execute()
        return True
    except Exception as e:
        print(f'❌ {ticker} ({period}): {e}')
        return False


def limpiar_viejos(dias=3):
    try:
        corte = (datetime.now(timezone.utc) - pd.Timedelta(days=dias)).isoformat()
        supabase.table('precios_cache').delete().lt('actualizado_en', corte).execute()
        print('🧹 Limpieza de filas viejas completada.')
    except Exception as e:
        print(f'⚠️ Error en limpieza: {e}')


def main():
    tickers_cacheados = obtener_tickers_ya_cacheados()
    universo = sorted(set(NUCLEO_FIJO) | set(tickers_cacheados))
    print(f'📡 Universo a actualizar: {len(universo)} tickers '
          f'({len(NUCLEO_FIJO)} núcleo fijo + {len(tickers_cacheados)} cacheados)')

    total_ok, total_fail = 0, 0
    for period in PERIODOS_A_REFRESCAR:
        print(f'\n--- Período {period} ---')
        with ThreadPoolExecutor(max_workers=6) as ex:
            futuros = {ex.submit(actualizar_ticker, tk, period): tk for tk in universo}
            for fut in as_completed(futuros):
                tk = futuros[fut]
                ok = fut.result()
                if ok:
                    total_ok += 1
                else:
                    total_fail += 1
                time.sleep(0.05)  # pequeño respiro para no saturar a Yahoo

    limpiar_viejos(dias=3)
    print(f'\n✅ Listo. OK: {total_ok} · Fallidos: {total_fail}')


if __name__ == '__main__':
    main()
