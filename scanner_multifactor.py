# ==============================================================
#  SCANNER MULTI-FACTOR + MOTOR DE BACKTESTING (Spot / Futuros)
#
#  Uso 1 — script independiente:
#      python scanner_multifactor.py NVDA BTC-USD GC=F --periodo 5y --modo spot
#      python scanner_multifactor.py BTC-USD ETH-USD --modo futuros --apalancamiento 3
#      python scanner_multifactor.py BTC-USD ETH-USD --modo futuros --tf 1h --periodo 365d
#
#  Uso 2 — dentro de la app (Señales → Publicar Señal):
#      from scanner_multifactor import render_scanner_multifactor
#      render_scanner_multifactor(on_cargar=_cargar_desde_multifactor)
#
#  Uso 3 — con presets guardados en Supabase (archivo aparte):
#      from scanner_presets_supabase import PresetStoreSupabase
#      render_scanner_multifactor(on_cargar=_cargar_desde_multifactor,
#                                 store=PresetStoreSupabase(supabase))
#
#  PRESETS
#   Guardan mercado, temporalidad, parámetros, tickers del Scanner y del
#   Backtest e histórico, con un nombre por grupo de activos. Por defecto se
#   guardan en un JSON local (scanner_presets.json); en Streamlit Cloud
#   el disco es efímero, por eso conviene el store de Supabase.
#
#  ESCANEAR PRESETS GUARDADOS
#   En la pestaña Scanner aparece la lista de todos los presets guardados.
#   Con "Escanear presets seleccionados" se escanean juntos y cada preset usa
#   SUS parámetros, SU temporalidad y SUS tickers del Scanner.
#   Los resultados se descartan solos si cambia la selección o el contenido
#   de algún preset elegido (evita ver resultados viejos).
#
#  TEMPORALIDAD
#   15 min, 30 min, 1 hora, 4 horas, Diario o Semanal (selector dentro de
#   Parámetros). Se aplica al Scanner y al Backtest y se guarda en cada
#   preset. Límites de Yahoo Finance: 15m/30m ≈ 60 días, 1h ≈ 2 años.
#   4h se arma agrupando velas de 1h. Con "solo velas cerradas" se
#   descarta la última vela si todavía no terminó.
#
#  FILTROS (todos deben cumplirse para generar señal)
#   1. Tendencia ADX/DI: bloquea compras si ADX > umbral y -DI domina
#      (espejo para cortos). Con MTF activo se lee en la temporalidad
#      SUPERIOR (ver MULTI-TIMEFRAME).
#   2. Scores 0-100: Acumulación y Sentimiento con rango (mín y máx) propio
#      para largos y para cortos; Anticipación (compresión BB/ATR) con mínimo.
#   3. Convicción: CMF > 0 y RVOL > 1.5.
#   4. Momento: histograma MACD positivo y creciendo + CCI en zona
#      (-100 a 200 y subiendo). Espejo para cortos.
#   5. Estructura macro (MTF): +DI/-DI y precio vs EMA 50 en la temporalidad
#      superior. Jamás se opera en contra de esa tendencia.
#   6. Fricción: el TP (tp_atr × ATR) debe superar N veces (3 por defecto) el
#      costo ida y vuelta (2 comisiones + 2 slippages). Si no, se descarta.
#
#  MULTI-TIMEFRAME (MTF)
#   Macro por temporalidad: 15m→1h · 30m→4h · 1h→4h · 4h→Diario · Diario→Semanal.
#   Semanal no tiene macro (usa su propia tendencia). El gatillo (Acumulación,
#   Anticipación, Sentimiento, CMF, RVOL, MACD, CCI) sigue en la temporalidad
#   elegida. Sin look-ahead: cada vela solo ve velas macro YA CERRADAS.
#   Si el macro no se puede descargar, el activo se omite (no se opera sin macro).
#
#  PERFILES AUTOMÁTICOS POR TEMPORALIDAD (un perfil propio por cada una, en PERFILES)
#   Altas (4h / Diario / Semanal): 70 velas · SL 2.0 / TP 3.0 × ATR · ADX 25 · RVOL 1.50
#   Bajas (15m / 30m / 1h):        135 velas · SL 1.2 / TP 2.0 × ATR · ADX 21 · RVOL 1.35
#   Se cargan al cambiar de temporalidad si "Auto-ajustar" está activo.
#
#  BACKTEST — supuestos (conservadores)
#   - La señal se evalúa al CIERRE de la vela y se ejecuta en la
#     APERTURA de la vela siguiente (sin look-ahead).
#   - Slippage adverso en entrada, Stop Loss y salidas a mercado.
#     El Take Profit se asume orden límite (sin slippage).
#   - Comisión por lado sobre el nocional (entrada y salida).
#   - SL = sl_atr × ATR y TP = tp_atr × ATR, fijados con el ATR de la
#     vela de la señal. Si en una misma vela se tocan SL y TP, se asume SL.
#   - Gaps: si la apertura ya perforó el SL, se sale a la apertura.
#   - Tamaño: arriesga riesgo_pct del equity hasta el SL, topeado por
#     el apalancamiento (spot = 1x). Una posición a la vez por activo.
#   - No incluye funding rate ni swaps (relevantes en futuros perpetuos).
# ==============================================================

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd


# ==============================================================
#  PARÁMETROS
# ==============================================================

@dataclass
class Params:
    # ── Scanner ──
    # Acumulación: rango permitido (0-100) para largos y para cortos
    acum_l_min: float = 50.0
    acum_l_max: float = 100.0
    acum_c_min: float = 0.0
    acum_c_max: float = 50.0
    # Sentimiento: rango permitido (0-100) para largos y para cortos (tope anti-euforia en largos)
    sent_l_min: float = 0.0
    sent_l_max: float = 85.0
    sent_c_min: float = 15.0
    sent_c_max: float = 100.0
    min_antic: float = 50.0       # Score Anticipación mínimo (largos y cortos)
    adx_umbral: float = 25.0
    cmf_min: float = 0.0
    rvol_min: float = 1.5
    cci_inf: float = -100.0       # zona CCI largos: (cci_inf, cci_sup) y subiendo
    cci_sup: float = 200.0
    exigir_volumen: bool = True   # False: activos sin volumen (forex) saltan CMF/RVOL
    # ── Backtest ──
    modo: str = "spot"            # 'spot' (solo largos) | 'futuros' (largos y cortos)
    sl_atr: float = 2.0
    tp_atr: float = 3.0
    comision_pct: float = 0.10    # % por lado
    slippage_pct: float = 0.05    # % por fill
    riesgo_pct: float = 1.0       # % del equity arriesgado por operación
    apalancamiento: float = 1.0
    capital: float = 10000.0
    max_barras: int = 70          # salida por tiempo (0 = sin límite), en velas
    intervalo: str = "1d"         # temporalidad: 15m, 30m, 1h, 4h, 1d, 1wk
    # ── Multi-timeframe y fricción ──
    mtf_activo: bool = True       # tendencia leída en la temporalidad superior
    mtf_estricto: bool = False    # True: exige macro A FAVOR; False: solo bloquea si es EN CONTRA
    ema_macro: int = 50           # EMA de estructura en la temporalidad superior
    friccion_mult: float = 3.0    # TP debe ser >= N × costo ida y vuelta (0 = desactivado)


# ==============================================================
#  DATOS
# ==============================================================

TEMPORALIDADES = {
    "15 min": dict(iv="15m", fuente="15m", resample=None, scan="30d",
                   periodos=["30d", "60d"], defecto="60d", delta=pd.Timedelta(minutes=15),
                   nota="Yahoo solo da ~60 días de velas de 15 min: pocas operaciones en el "
                        "backtest. Pensado para intradía."),
    "30 min": dict(iv="30m", fuente="30m", resample=None, scan="60d",
                   periodos=["30d", "60d"], defecto="60d", delta=pd.Timedelta(minutes=30),
                   nota="Yahoo solo da ~60 días de velas de 30 min: pocas operaciones en el "
                        "backtest. Pensado para intradía."),
    "1 hora": dict(iv="1h", fuente="1h", resample=None, scan="180d",
                   periodos=["90d", "180d", "365d", "730d"], defecto="730d",
                   delta=pd.Timedelta(hours=1),
                   nota="Yahoo da hasta ~2 años de velas de 1 hora."),
    "4 horas": dict(iv="4h", fuente="1h", resample="4h", scan="180d",
                    periodos=["90d", "180d", "365d", "730d"], defecto="730d",
                    delta=pd.Timedelta(hours=4),
                    nota="Se arma agrupando velas de 1 hora (hasta ~2 años). En acciones los "
                         "bloques no coinciden con la rueda; rinde mejor en cripto, forex y futuros."),
    "Diario": dict(iv="1d", fuente="1d", resample=None, scan="1y",
                   periodos=["2y", "5y", "10y"], defecto="5y", delta=pd.Timedelta(days=1),
                   nota="Configuración original: hasta 10 años de histórico."),
    "Semanal": dict(iv="1wk", fuente="1wk", resample=None, scan="5y",
                    periodos=["5y", "10y", "20y"], defecto="10y", delta=pd.Timedelta(days=7),
                    nota="Pocas operaciones por año: conviene histórico de 10 a 20 años."),
}

# Temporalidad superior que aporta la tendencia macro (None = sin macro)
_MACRO_DE = {"15 min": "1 hora", "30 min": "4 horas", "1 hora": "4 horas",
             "4 horas": "Diario", "Diario": "Semanal", "Semanal": None}
for _k, _v in _MACRO_DE.items():
    TEMPORALIDADES[_k]["macro"] = _v
TF_POR_CODIGO = {c["iv"]: c for c in TEMPORALIDADES.values()}

# Perfiles automáticos por temporalidad (editá los números acá)
PERFIL_ALTO = dict(max_barras=70, sl_atr=2.0, tp_atr=3.0, adx_umbral=25.0, rvol_min=1.50)
PERFIL_BAJO = dict(max_barras=135, sl_atr=1.2, tp_atr=2.0, adx_umbral=21.0, rvol_min=1.35)

# Un perfil PROPIO por temporalidad (arrancan con los valores base de arriba).
# Editá cada línea por separado para afinar cada temporalidad.
PERFILES = {
    "15m": dict(PERFIL_BAJO),
    "30m": dict(PERFIL_BAJO),
    "1h":  dict(PERFIL_BAJO),
    "4h":  dict(PERFIL_ALTO),
    "1d":  dict(PERFIL_ALTO),
    "1wk": dict(PERFIL_ALTO),
}
# sufijo del widget -> clave del perfil
_PERFIL_A_WIDGET = {"sl": "sl_atr", "tp": "tp_atr", "adx": "adx_umbral",
                    "rvol": "rvol_min", "maxbar": "max_barras"}


def perfil_para(iv: str) -> dict:
    """Perfil de parámetros según el intervalo ('15m', '1h', '1d'...)."""
    return PERFILES.get(iv, PERFIL_ALTO)


# Yahoo limita el histórico intradía (en días hacia atrás)
_MAX_DIAS_INTRADIA = {"15m": 59, "30m": 59, "1h": 729}


def _resamplear(df: pd.DataFrame, regla: str) -> pd.DataFrame:
    """Agrupa velas (ej. 1h -> 4h)."""
    out = df.resample(regla).agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"})
    out["Volume"] = df["Volume"].resample(regla).sum(min_count=1)
    return out.dropna(subset=["Close"])


def _vela_abierta(ts, delta) -> bool:
    """True si la vela que empieza en ts todavía no cerró."""
    ahora = pd.Timestamp.now(tz=ts.tz) if getattr(ts, "tz", None) is not None else pd.Timestamp.now()
    return ts + delta > ahora


def descargar_ohlcv(ticker: str, period: str = "2y", interval: str = "1d",
                    resample: str | None = None) -> pd.DataFrame | None:
    try:
        import yfinance as yf
        if period.endswith("d"):      # ej. "365d": se pasa como fecha de inicio
            dias = min(int(period[:-1]), _MAX_DIAS_INTRADIA.get(interval, 10 ** 6))
            inicio = (pd.Timestamp.now() - pd.Timedelta(days=dias)).strftime("%Y-%m-%d")
            df = yf.download(ticker, start=inicio, interval=interval,
                             auto_adjust=True, progress=False)
        else:
            df = yf.download(ticker, period=period, interval=interval,
                             auto_adjust=True, progress=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Close"])
        if not {"Open", "High", "Low", "Close"}.issubset(df.columns):
            return None
        if "Volume" not in df.columns:
            df["Volume"] = np.nan
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.loc[df["Volume"] == 0, "Volume"] = np.nan   # forex/índices reportan 0
        if resample:
            df = _resamplear(df, resample)
        return df
    except Exception:
        return None


def categoria_de(ticker: str) -> str:
    t = ticker.upper()
    if t.endswith("=X"): return "💱 Forex"
    if t.endswith("-USD"): return "₿ Cripto"
    if t.endswith("=F"): return "🛢️ Commodity"
    if t.startswith("^"): return "📊 Índice"
    return "📈 Acción"


# ==============================================================
#  INDICADORES (vectorizados, una fila por vela)
# ==============================================================

def _rank_pct(s: pd.Series, w: int) -> pd.Series:
    """Percentil (0-100) del valor actual dentro de su ventana rolling."""
    return s.rolling(w, min_periods=w).apply(lambda x: (x < x[-1]).mean() * 100, raw=True)


def _true_range(h: pd.Series, l: pd.Series, c: pd.Series) -> pd.Series:
    return pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)


def _adx_di(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14):
    """ADX, +DI y -DI (Wilder)."""
    tr = _true_range(h, l, c)
    up, dn = h.diff(), -l.diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=h.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=h.index)
    a = 1 / n
    atr_w = tr.ewm(alpha=a, adjust=False).mean()
    pdi = 100 * plus_dm.ewm(alpha=a, adjust=False).mean() / atr_w
    mdi = 100 * minus_dm.ewm(alpha=a, adjust=False).mean() / atr_w
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    adx = dx.ewm(alpha=a, adjust=False).mean()
    return adx, pdi, mdi


def calcular_indicadores(df: pd.DataFrame, ventana: int = 63) -> pd.DataFrame:
    o, h, l, c, v = df["Open"], df["High"], df["Low"], df["Close"], df["Volume"]
    out = pd.DataFrame(index=df.index)
    out["Open"], out["High"], out["Low"], out["Close"] = o, h, l, c

    # ATR (Wilder, 14)
    tr = _true_range(h, l, c)
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    out["atr"] = atr

    # ADX / +DI / -DI (Wilder, 14)
    out["adx"], out["pdi"], out["mdi"] = _adx_di(h, l, c)

    # CMF (20) y RVOL (20)
    rango = (h - l).replace(0, np.nan)
    mfv = ((c - l) - (h - c)) / rango * v
    out["cmf"] = mfv.rolling(20).sum() / v.rolling(20).sum().replace(0, np.nan)
    out["rvol"] = v / v.rolling(20).mean().shift(1)

    # Histograma MACD (12, 26, 9)
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    out["macd_hist"] = macd - macd.ewm(span=9, adjust=False).mean()

    # CCI (20)
    tp = (h + l + c) / 3
    sma = tp.rolling(20).mean()
    mad = tp.rolling(20).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    out["cci"] = (tp - sma) / (0.015 * mad.replace(0, np.nan))

    # ── Scores (misma lógica que el módulo de corto plazo, calculada vela a vela) ──
    d = c.diff()
    g = d.clip(lower=0).rolling(7).mean()
    ls = (-d.clip(upper=0)).rolling(7).mean()
    rsi7 = (100 - 100 / (1 + g / ls.replace(0, np.nan))).where(ls != 0, 100.0)
    vol10 = c.pct_change().rolling(10).std() * np.sqrt(252) * 100

    precio_pct = _rank_pct(c, ventana)
    rsi_inv = 100 - _rank_pct(rsi7, ventana)
    vol_inv = 100 - _rank_pct(vol10, ventana)
    out["acum"] = (100 - precio_pct) * 0.40 + rsi_inv * 0.35 + vol_inv * 0.25
    out["sent"] = precio_pct

    mom = (50 + c.pct_change(5) * 100 * 2.0).clip(0, 100)
    comp_atr = (100 - atr / atr.rolling(ventana).mean() * 50).clip(0, 100)
    bbw = c.rolling(10).std() / c.rolling(10).mean().replace(0, np.nan) * 100
    bb_c = 100 - _rank_pct(bbw, ventana)
    out["antic"] = mom * 0.40 + comp_atr * 0.30 + bb_c * 0.30
    return out


# ==============================================================
#  MULTI-TIMEFRAME (tendencia macro en la temporalidad superior)
# ==============================================================

def cfg_macro(intervalo: str):
    """Config de la temporalidad superior de un intervalo ('30m' -> la de 4 horas) o None."""
    lbl = TF_POR_CODIGO.get(intervalo, {}).get("macro")
    return TEMPORALIDADES[lbl] if lbl else None


def macro_requerido(p: Params) -> bool:
    """True si hay que leer la tendencia en una temporalidad superior."""
    return bool(p.mtf_activo) and cfg_macro(p.intervalo) is not None


def periodo_macro(cm: dict) -> str:
    """Histórico a bajar de la TF superior (incluye margen de calentamiento de ADX/EMA)."""
    return {"1h": "730d", "4h": "730d", "1d": "10y", "1wk": "20y"}.get(cm["iv"], "5y")


def obtener_macro(dl, ticker: str, p: Params):
    """Descarga la TF superior del ticker. dl = descargar_ohlcv o su versión cacheada."""
    if not macro_requerido(p):
        return None
    cm = cfg_macro(p.intervalo)
    return dl(ticker, periodo_macro(cm), cm["fuente"], cm["resample"])


def _a_utc_naive(idx) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(idx)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return idx.astype("datetime64[ns]")


_COLS_MACRO = ("m_adx", "m_pdi", "m_mdi", "m_close", "m_ema")


def agregar_macro(ind: pd.DataFrame, df_macro, p: Params) -> pd.DataFrame:
    """Suma a `ind` las columnas m_* de la TF superior, SIN look-ahead: cada vela usa
    solo la última vela macro que ya estaba CERRADA cuando esa vela cerró."""
    cm = cfg_macro(p.intervalo)
    if not p.mtf_activo or cm is None or df_macro is None:
        return ind
    try:
        dm = df_macro
        if len(dm) > 1 and _vela_abierta(dm.index[-1], cm["delta"]):
            dm = dm.iloc[:-1]                       # la vela macro en formación no cuenta
        if len(dm) < max(60, p.ema_macro + 14):
            return ind
        adx, pdi, mdi = _adx_di(dm["High"], dm["Low"], dm["Close"])
        ema = dm["Close"].ewm(span=p.ema_macro, adjust=False, min_periods=p.ema_macro).mean()
        m = pd.DataFrame({"m_adx": adx.to_numpy(), "m_pdi": pdi.to_numpy(),
                          "m_mdi": mdi.to_numpy(), "m_close": dm["Close"].to_numpy(),
                          "m_ema": ema.to_numpy()})
        # instante en que cada vela macro queda cerrada
        m["t"] = (_a_utc_naive(dm.index) + cm["delta"]).astype("datetime64[ns]").to_numpy()
        m = m.sort_values("t")
        delta_t = TF_POR_CODIGO[p.intervalo]["delta"]
        izq = pd.DataFrame({"t": (_a_utc_naive(ind.index) + delta_t)
                            .astype("datetime64[ns]").to_numpy()})
        j = pd.merge_asof(izq, m, on="t", direction="backward")
        out = ind.copy()
        for c in _COLS_MACRO:
            out[c] = j[c].to_numpy()
        return out
    except Exception:
        return ind


def etiqueta_macro(u) -> str:
    """Dirección macro de una fila de indicadores (▲ alcista / ▼ bajista / ◆ neutral)."""
    if pd.isna(u.get("m_adx")):
        return "—"
    if u["m_pdi"] > u["m_mdi"] and u["m_close"] > u["m_ema"]:
        return "▲ alcista"
    if u["m_mdi"] > u["m_pdi"] and u["m_close"] < u["m_ema"]:
        return "▼ bajista"
    return "◆ neutral"


def _usa_macro(ind: pd.DataFrame, p: Params) -> bool:
    return bool(p.mtf_activo) and "m_adx" in ind.columns


def coste_ida_vuelta_pct(p: Params) -> float:
    """Costo total de una operación completa, en % del precio: 2 comisiones + 2 slippages."""
    return 2 * (p.comision_pct + p.slippage_pct)


# ==============================================================
#  CONDICIONES / SEÑALES
# ==============================================================

def condiciones(ind: pd.DataFrame, p: Params):
    """Devuelve (dict_largo, dict_corto) de Series booleanas, una por filtro."""
    sin_vol = ind["cmf"].isna() | ind["rvol"].isna()
    saltar_vol = (sin_vol & (not p.exigir_volumen))
    hist, hist_prev = ind["macd_hist"], ind["macd_hist"].shift(1)
    cci, cci_prev = ind["cci"], ind["cci"].shift(1)

    # Tendencia: con MTF se lee en la temporalidad superior; si no, en la propia
    usa_macro = _usa_macro(ind, p)
    if usa_macro:
        adx_t, pdi_t, mdi_t = ind["m_adx"], ind["m_pdi"], ind["m_mdi"]
    else:
        adx_t, pdi_t, mdi_t = ind["adx"], ind["pdi"], ind["mdi"]

    largo = {"Tendencia ADX/DI": ~((adx_t > p.adx_umbral) & (mdi_t > pdi_t))}
    corto = {"Tendencia ADX/DI": ~((adx_t > p.adx_umbral) & (pdi_t > mdi_t))}

    if usa_macro:   # estructura macro: dirección (+DI/-DI) y precio vs EMA
        macro_alc = (ind["m_pdi"] > ind["m_mdi"]) & (ind["m_close"] > ind["m_ema"])
        macro_baj = (ind["m_mdi"] > ind["m_pdi"]) & (ind["m_close"] < ind["m_ema"])
        largo["Estructura macro"] = macro_alc if p.mtf_estricto else ~macro_baj
        corto["Estructura macro"] = macro_baj if p.mtf_estricto else ~macro_alc

    largo.update({
        "Acumulación": (ind["acum"] >= p.acum_l_min) & (ind["acum"] <= p.acum_l_max),
        "Anticipación": ind["antic"] >= p.min_antic,
        "Sentimiento": (ind["sent"] >= p.sent_l_min) & (ind["sent"] <= p.sent_l_max),
        "CMF": (ind["cmf"] > p.cmf_min) | saltar_vol,
        "RVOL": (ind["rvol"] > p.rvol_min) | saltar_vol,
        "MACD hist": (hist > 0) & (hist > hist_prev),
        "CCI": (cci > p.cci_inf) & (cci < p.cci_sup) & (cci > cci_prev),
    })
    corto.update({
        "Acumulación": (ind["acum"] >= p.acum_c_min) & (ind["acum"] <= p.acum_c_max),
        "Anticipación": ind["antic"] >= p.min_antic,
        "Sentimiento": (ind["sent"] >= p.sent_c_min) & (ind["sent"] <= p.sent_c_max),
        "CMF": (ind["cmf"] < -p.cmf_min) | saltar_vol,
        "RVOL": (ind["rvol"] > p.rvol_min) | saltar_vol,
        "MACD hist": (hist < 0) & (hist < hist_prev),
        "CCI": (cci < -p.cci_inf) & (cci > -p.cci_sup) & (cci < cci_prev),
    })

    # Filtro de fricción: el TP debe superar N veces el costo ida y vuelta
    if p.friccion_mult > 0:
        friccion = (p.tp_atr * ind["atr"]) >= (
            p.friccion_mult * ind["Close"] * coste_ida_vuelta_pct(p) / 100)
    else:
        friccion = pd.Series(True, index=ind.index)
    largo["Fricción"] = friccion
    corto["Fricción"] = friccion
    return largo, corto


def _validas(ind: pd.DataFrame, p: Params | None = None) -> pd.Series:
    cols = ["acum", "antic", "sent", "adx", "pdi", "mdi", "macd_hist", "cci", "atr"]
    if p is not None and _usa_macro(ind, p):
        cols = cols + list(_COLS_MACRO)
    return ind[cols].notna().all(axis=1)


def generar_senales(ind: pd.DataFrame, p: Params):
    cl, cs = condiciones(ind, p)
    valid = _validas(ind, p)
    sig_l = pd.concat(cl.values(), axis=1).all(axis=1) & valid
    if p.modo == "futuros":
        sig_s = pd.concat(cs.values(), axis=1).all(axis=1) & valid
    else:
        sig_s = pd.Series(False, index=ind.index)
    return sig_l, sig_s


# ==============================================================
#  MOTOR DE BACKTESTING
# ==============================================================

def backtest(df: pd.DataFrame, p: Params, df_macro=None) -> dict:
    ind = agregar_macro(calcular_indicadores(df), df_macro, p)
    if macro_requerido(p) and "m_adx" not in ind.columns:
        raise ValueError("Sin datos de la temporalidad superior (MTF)")
    sig_l, sig_s = generar_senales(ind, p)
    sig_l, sig_s = sig_l.to_numpy(), sig_s.to_numpy()
    O, H, L, C = (ind[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    ATR = ind["atr"].to_numpy()
    idx, n = ind.index, len(ind)

    fee, slip = p.comision_pct / 100, p.slippage_pct / 100
    equity = float(p.capital)
    pos, pending, trades = None, None, []
    curve = np.full(n, np.nan)

    def cerrar(i, salida, motivo):
        nonlocal equity, pos
        d = pos["dir"]
        bruto = d * (salida - pos["entry"]) * pos["qty"]
        fee_out = pos["qty"] * salida * fee
        equity += bruto - fee_out
        pnl = bruto - pos["fee_in"] - fee_out
        trades.append({
            "Entrada": idx[pos["i_in"]], "Salida": idx[i],
            "Lado": "LARGO" if d == 1 else "CORTO",
            "Precio entrada": pos["entry"], "Precio salida": salida,
            "Stop Loss": pos["sl"], "Take Profit": pos["tp"], "Cantidad": pos["qty"],
            "PnL": pnl, "R": pnl / pos["riesgo_usd"], "Motivo": motivo,
            "Barras": i - pos["i_in"],
        })
        pos = None

    for i in range(n):
        # 1) Ejecutar la entrada pendiente a la apertura de esta vela
        if pos is None and pending is not None:
            lado, atr_s = pending
            d = 1 if lado == "LARGO" else -1
            entry = O[i] * (1 + d * slip)
            sl_d, tp_d = p.sl_atr * atr_s, p.tp_atr * atr_s
            if sl_d > 0 and entry > 0 and equity > 0:
                qty = min(equity * p.riesgo_pct / 100 / sl_d,
                          equity * p.apalancamiento / entry)
                if qty > 0:
                    fee_in = qty * entry * fee
                    equity -= fee_in
                    pos = dict(dir=d, entry=entry, qty=qty, i_in=i, fee_in=fee_in,
                               sl=entry - d * sl_d, tp=entry + d * tp_d,
                               riesgo_usd=qty * sl_d)
        pending = None

        # 2) Gestionar posición abierta
        if pos is not None:
            d, sl, tp = pos["dir"], pos["sl"], pos["tp"]
            adverso = L[i] if d == 1 else H[i]
            favorable = H[i] if d == 1 else L[i]
            carry = i > pos["i_in"]
            if carry and d * (O[i] - sl) <= 0:
                cerrar(i, O[i] * (1 - d * slip), "SL (gap)")
            elif carry and d * (O[i] - tp) >= 0:
                cerrar(i, O[i], "TP (gap)")
            elif d * (adverso - sl) <= 0:
                cerrar(i, sl * (1 - d * slip), "SL")
            elif d * (favorable - tp) >= 0:
                cerrar(i, tp, "TP")
            elif p.max_barras and (i - pos["i_in"]) >= p.max_barras:
                cerrar(i, C[i] * (1 - d * slip), "Tiempo")

        # 3) Equity mark-to-market al cierre
        curve[i] = equity + (pos["dir"] * (C[i] - pos["entry"]) * pos["qty"] if pos else 0.0)

        # 4) Señal al cierre → entrada en la próxima apertura
        if pos is None and i < n - 1 and not np.isnan(ATR[i]):
            if sig_l[i]:
                pending = ("LARGO", ATR[i])
            elif sig_s[i]:
                pending = ("CORTO", ATR[i])

    if pos is not None:   # cierre forzado al final de los datos
        cerrar(n - 1, C[-1] * (1 - pos["dir"] * slip), "Fin de datos")
        curve[-1] = equity

    trades_df = pd.DataFrame(trades)
    equity_s = pd.Series(curve, index=idx).dropna()
    primer = ind["acum"].first_valid_index()
    bh = (C[-1] / ind.loc[primer, "Close"] - 1) * 100 if primer is not None else np.nan
    return dict(trades=trades_df, equity=equity_s, indicadores=ind,
                metricas=calcular_metricas(trades_df, equity_s, p.capital, bh))


# ==============================================================
#  MÉTRICAS
# ==============================================================

def calcular_metricas(trades: pd.DataFrame, equity: pd.Series, capital: float,
                      buy_hold_pct: float = np.nan) -> dict:
    m = {"Operaciones": int(len(trades))}
    dd = equity / equity.cummax() - 1 if len(equity) else pd.Series(dtype=float)
    m["Max Drawdown %"] = float(dd.min() * 100) if len(dd) else np.nan
    m["Max Drawdown USD"] = float((equity - equity.cummax()).min()) if len(equity) else np.nan
    m["Retorno total %"] = float((equity.iloc[-1] / capital - 1) * 100) if len(equity) else np.nan
    m["Buy & Hold %"] = float(buy_hold_pct)
    if trades.empty:
        for k in ("Win Rate %", "Profit Factor", "Expectativa USD", "Expectativa R",
                  "Ganancia media USD", "Pérdida media USD", "Payoff"):
            m[k] = np.nan
        return m
    pnl = trades["PnL"]
    gana, pierde = pnl[pnl > 0], pnl[pnl < 0]
    gw, gl = gana.sum(), -pierde.sum()
    wr = len(gana) / len(pnl)
    avg_w = gana.mean() if len(gana) else 0.0
    avg_l = pierde.mean() if len(pierde) else 0.0
    m["Win Rate %"] = wr * 100
    m["Profit Factor"] = gw / gl if gl > 0 else (np.inf if gw > 0 else np.nan)
    m["Expectativa USD"] = wr * avg_w + (1 - wr) * avg_l      # = PnL medio por operación
    m["Expectativa R"] = float(trades["R"].mean())
    m["Ganancia media USD"], m["Pérdida media USD"] = float(avg_w), float(avg_l)
    m["Payoff"] = avg_w / abs(avg_l) if avg_l < 0 else np.nan
    return m


def metricas_agrupadas(lista_trades: list) -> dict:
    """PF y expectativa de todas las operaciones juntas (cada activo con su propio capital)."""
    t = pd.concat([x for x in lista_trades if not x.empty], ignore_index=True) \
        if any(not x.empty for x in lista_trades) else pd.DataFrame()
    return calcular_metricas(t, pd.Series(dtype=float), 1.0)


def fmt_metrica(k: str, v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    if isinstance(v, float) and np.isinf(v):
        return "∞"
    if k == "Operaciones":
        return f"{int(v)}"
    if k in ("Profit Factor", "Expectativa R", "Payoff"):
        return f"{v:.2f}"
    if k.endswith("%"):
        return f"{v:+.2f}%" if "Retorno" in k or "Hold" in k else f"{v:.2f}%"
    return f"{v:,.2f}"


def imprimir_metricas(ticker: str, m: dict) -> None:
    print(f"\n{'=' * 52}\n  {ticker}\n{'=' * 52}")
    for k, v in m.items():
        print(f"  {k:<22} {fmt_metrica(k, v):>20}")


# ==============================================================
#  SCANNER (estado de los filtros en la última vela)
# ==============================================================

def evaluar_ultima(ticker: str, df: pd.DataFrame, p: Params, solo_cerradas: bool = True,
                   df_macro=None):
    delta = TF_POR_CODIGO.get(p.intervalo, TEMPORALIDADES["Diario"])["delta"]
    if solo_cerradas and len(df) > 1 and _vela_abierta(df.index[-1], delta):
        df = df.iloc[:-1]      # evita RVOL/CMF distorsionados por una vela a medio formar
    if len(df) < 150:
        return None
    ind = agregar_macro(calcular_indicadores(df), df_macro, p)
    if macro_requerido(p) and "m_adx" not in ind.columns:
        return None             # no se opera sin la tendencia de la temporalidad superior
    cl, cs = condiciones(ind, p)
    u = ind.iloc[-1]
    if not bool(_validas(ind, p).iloc[-1]):
        return None
    ok_l = {k: bool(v.iloc[-1]) for k, v in cl.items()}
    ok_s = {k: bool(v.iloc[-1]) for k, v in cs.items()}
    n_l, n_s = sum(ok_l.values()), sum(ok_s.values())
    senal = "—"
    if n_l == len(ok_l):
        senal = "🟢 LARGO"
    elif p.modo == "futuros" and n_s == len(ok_s):
        senal = "🔴 CORTO"
    lado_ref, ok_ref = ("LARGO", ok_l) if (p.modo != "futuros" or n_l >= n_s) else ("CORTO", ok_s)
    px, atr = float(u["Close"]), float(u["atr"])
    fallan = [k for k, v in ok_ref.items() if not v]
    usa_m = _usa_macro(ind, p)
    macro_lbl = etiqueta_macro(u) if usa_m else "—"
    adx_m = int(round(float(u["m_adx"]))) if usa_m else None
    cm = cfg_macro(p.intervalo)
    macro_nota = f" · Macro {cm['iv']}: {macro_lbl} (ADX {adx_m})" if usa_m else ""
    return {
        "Ticker": ticker, "Precio": px, "Señal": senal,
        "Filtros OK": f"{max(n_l, n_s) if p.modo == 'futuros' else n_l}/{len(ok_l)}",
        "_n": max(n_l, n_s) if p.modo == "futuros" else n_l,
        "Acum": float(u["acum"]), "Antic": float(u["antic"]), "Sent": float(u["sent"]),
        "ADX": float(u["adx"]), "+DI": float(u["pdi"]), "-DI": float(u["mdi"]),
        "CMF": None if pd.isna(u["cmf"]) else float(u["cmf"]),
        "RVOL": None if pd.isna(u["rvol"]) else float(u["rvol"]),
        "MACD hist": float(u["macd_hist"]), "CCI": float(u["cci"]),
        "Macro": macro_lbl, "ADX macro": adx_m,
        "Falta cumplir": ", ".join(fallan) if fallan else "—",
        # datos para cargar en el formulario de señales
        "ticker_yahoo": ticker, "categoria": categoria_de(ticker), "precio": px, "atr": atr,
        "temporalidad": p.intervalo,
        "sl_largo": px - p.sl_atr * atr, "tp_largo": px + p.tp_atr * atr,
        "sl_corto": px + p.sl_atr * atr, "tp_corto": px - p.tp_atr * atr,
        "notas": (f"Scanner multi-factor ({p.intervalo}) · ADX {u['adx']:.0f} (+DI {u['pdi']:.0f}/-DI {u['mdi']:.0f}) · "
                  f"Acum {u['acum']:.0f} / Antic {u['antic']:.0f} / Sent {u['sent']:.0f} · "
                  f"CMF {0 if pd.isna(u['cmf']) else u['cmf']:+.2f} · "
                  f"RVOL {0 if pd.isna(u['rvol']) else u['rvol']:.1f}x · CCI {u['cci']:.0f} · "
                  f"SL {p.sl_atr:g}×ATR / TP {p.tp_atr:g}×ATR (ATR {atr:,.4f})." + macro_nota),
    }


def _parse_tickers(txt: str) -> list:
    raw = [t.strip().upper() for t in txt.replace("\n", ",").replace(";", ",").split(",")]
    vistos = []
    for t in raw:
        if t and t not in vistos and len(t) <= 15:
            vistos.append(t)
    return vistos


# ==============================================================
#  PRESETS (guardar / cargar configuraciones por grupo de activos)
# ==============================================================

PRESETS_FILE = Path("scanner_presets.json")

MODOS_LBL = ["Spot (solo largos)", "Futuros (largos y cortos)"]
PERIODOS_VALIDOS = {x for c in TEMPORALIDADES.values() for x in c["periodos"]}

# sufijo del widget -> tipo (se usa para leer/validar/convertir al guardar y cargar)
_CAMPOS_PRESET = {
    "modo": str, "tf": str, "antic": float, "adx": float,
    "acum_lmin": float, "acum_lmax": float, "acum_cmin": float, "acum_cmax": float,
    "sent_lmin": float, "sent_lmax": float, "sent_cmin": float, "sent_cmax": float,
    "rvol": float, "cci_i": float, "cci_s": float, "exvol": bool,
    "sl": float, "tp": float, "com": float, "slip": float,
    "cap": float, "riesgo": float, "apal": float, "maxbar": int,
    "scan_tk": str, "cerradas": bool, "bt_tk": str, "bt_per": str,
    "mtf": bool, "mtf_est": bool, "fric": float, "perfil": bool,
}


class PresetStoreJSON:
    """Guarda los presets en un archivo JSON local.

    OJO: en Streamlit Cloud el disco es efímero y se pierde al reiniciar la app.
    Si desplegás ahí, usá PresetStoreSupabase (scanner_presets_supabase.py).

    Interfaz que debe cumplir cualquier store:
        listar()  -> dict {nombre: datos}
        guardar(nombre, datos)
        eliminar(nombre)
    """

    def __init__(self, path: Path = PRESETS_FILE):
        self.path = Path(path)

    def listar(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def guardar(self, nombre: str, datos: dict) -> None:
        todos = self.listar()
        todos[nombre] = datos
        self.path.write_text(json.dumps(todos, ensure_ascii=False, indent=2), encoding="utf-8")

    def eliminar(self, nombre: str) -> None:
        todos = self.listar()
        todos.pop(nombre, None)
        self.path.write_text(json.dumps(todos, ensure_ascii=False, indent=2), encoding="utf-8")


def _snapshot_preset(st, key: str) -> dict:
    """Lee el estado actual de los widgets y arma el dict a guardar."""
    datos = {}
    for suf, tipo in _CAMPOS_PRESET.items():
        v = st.session_state.get(f"{key}_{suf}")
        if v is not None:
            datos[suf] = tipo(v)
    return datos


def _migrar_preset(d: dict) -> dict:
    """Presets viejos guardaban un solo número de Acumulación ('acum') y de Sentimiento ('sent').
    Se convierten a los rangos nuevos con la misma lógica espejo que tenían."""
    d = dict(d)
    if "acum" in d and "acum_lmin" not in d:
        try:
            a = float(d["acum"])
            d.update(acum_lmin=a, acum_lmax=100.0, acum_cmin=0.0, acum_cmax=100.0 - a)
        except (TypeError, ValueError):
            pass
    if "sent" in d and "sent_lmax" not in d:
        try:
            s = float(d["sent"])
            d.update(sent_lmin=0.0, sent_lmax=s, sent_cmin=100.0 - s, sent_cmax=100.0)
        except (TypeError, ValueError):
            pass
    return d


def _aplicar_preset(st, key: str, datos: dict) -> None:
    """Vuelca un preset en los widgets (se llama desde un callback, antes del rerun)."""
    datos = {"tf": "Diario", **_migrar_preset(datos)}      # presets viejos: tf = diario, rangos nuevos
    for suf, tipo in _CAMPOS_PRESET.items():
        if suf not in datos:
            continue
        try:
            v = tipo(datos[suf])
        except Exception:
            continue
        if suf == "modo" and v not in MODOS_LBL:
            continue
        if suf == "tf" and v not in TEMPORALIDADES:
            continue
        if suf == "bt_per" and v not in PERIODOS_VALIDOS:
            continue
        st.session_state[f"{key}_{suf}"] = v


def _params_desde_preset(d: dict):
    """Arma (Params, cfg_temporalidad) a partir de un preset guardado, sin pasar por la pantalla.
    Lo que el preset no tenga guardado se completa con el perfil automático de su temporalidad."""
    d = _migrar_preset(d)
    tf = d.get("tf") if d.get("tf") in TEMPORALIDADES else "Diario"
    cfg = TEMPORALIDADES[tf]
    perf = perfil_para(cfg["iv"])

    def num(k, defecto):
        try:
            return float(d.get(k, defecto))
        except (TypeError, ValueError):
            return float(defecto)

    modo = "futuros" if str(d.get("modo", "")).startswith("Futuros") else "spot"
    p = Params(
        acum_l_min=num("acum_lmin", 50.0), acum_l_max=num("acum_lmax", 100.0),
        acum_c_min=num("acum_cmin", 0.0), acum_c_max=num("acum_cmax", 50.0),
        sent_l_min=num("sent_lmin", 0.0), sent_l_max=num("sent_lmax", 85.0),
        sent_c_min=num("sent_cmin", 15.0), sent_c_max=num("sent_cmax", 100.0),
        min_antic=num("antic", 50.0),
        adx_umbral=num("adx", perf["adx_umbral"]), rvol_min=num("rvol", perf["rvol_min"]),
        cci_inf=num("cci_i", -100.0), cci_sup=num("cci_s", 200.0),
        exigir_volumen=bool(d.get("exvol", True)),
        modo=modo, sl_atr=num("sl", perf["sl_atr"]), tp_atr=num("tp", perf["tp_atr"]),
        comision_pct=num("com", 0.10), slippage_pct=num("slip", 0.05),
        riesgo_pct=num("riesgo", 1.0),
        apalancamiento=num("apal", 1.0) if modo == "futuros" else 1.0,
        capital=num("cap", 10000.0), max_barras=int(num("maxbar", perf["max_barras"])),
        intervalo=cfg["iv"],
        mtf_activo=bool(d.get("mtf", True)), mtf_estricto=bool(d.get("mtf_est", False)),
        friccion_mult=num("fric", 3.0))
    return p, cfg


def _render_scan_presets(st, key: str, presets: dict, dl, on_cargar=None):
    """Escanea varios presets guardados de una vez: cada uno con SUS parámetros,
    SU temporalidad y SUS tickers del Scanner."""
    k_res = f"{key}_multi_res"
    k_fall = f"{key}_multi_fallidos"
    k_np = f"{key}_multi_npresets"
    k_sig = f"{key}_multi_sig"

    with st.container(border=True):
        st.markdown("**📚 Escanear presets guardados**")
        if not presets:
            st.caption("Guardá al menos un preset (💾 Presets) para escanearlo desde acá. "
                       "Cada preset se escanea con sus propios parámetros, temporalidad y tickers.")
            return

        nombres = sorted(presets.keys())
        k_ms = f"{key}_multi_sel"
        if k_ms not in st.session_state:
            st.session_state[k_ms] = list(nombres)      # por defecto, todos
        else:
            st.session_state[k_ms] = [n for n in st.session_state[k_ms] if n in nombres]
        elegidos = st.multiselect("Presets a escanear", nombres, key=k_ms)

        # ── Firma de lo que se va a escanear: selección + contenido de cada preset.
        #    Si cambia respecto del último escaneo, los resultados guardados quedan
        #    obsoletos y se descartan (evita ver tickers viejos con el nombre nuevo).
        firma = json.dumps({n: presets[n] for n in elegidos}, sort_keys=True,
                           ensure_ascii=False, default=str)
        if st.session_state.get(k_sig) != firma:
            for k in (k_res, k_fall, k_np):
                st.session_state.pop(k, None)

        resumen = []
        for n in elegidos:
            d = presets[n]
            tks = _parse_tickers(d.get("scan_tk", ""))
            resumen.append({
                "Preset": n,
                "Temporalidad": d.get("tf") if d.get("tf") in TEMPORALIDADES else "Diario",
                "Mercado": "Futuros" if str(d.get("modo", "")).startswith("Futuros") else "Spot",
                "Tickers del Scanner": ", ".join(tks) if tks else "— (vacío)",
            })
        if resumen:
            st.dataframe(pd.DataFrame(resumen), use_container_width=True, hide_index=True)
        st.caption("Se escanean los tickers de la pestaña Scanner que tenía cada preset al guardarlo. "
                   "Si los cargaste solo en Backtest, ponelos también acá y volvé a guardar el preset.")

        if st.button("▶ Escanear presets seleccionados", key=f"{key}_multi_run",
                     type="primary", disabled=not elegidos):
            tareas = []
            for n in elegidos:
                d = presets[n]
                p_n, cfg_n = _params_desde_preset(d)
                tf_n = d.get("tf") if d.get("tf") in TEMPORALIDADES else "Diario"
                solo = bool(d.get("cerradas", True))
                for tk in _parse_tickers(d.get("scan_tk", ""))[:60]:
                    tareas.append((n, tf_n, tk, p_n, cfg_n, solo))

            def _uno(t):
                n, tf_n, tk, p_n, cfg_n, solo = t
                df = dl(tk, cfg_n["scan"], cfg_n["fuente"], cfg_n["resample"])
                dm = obtener_macro(dl, tk, p_n)
                f = evaluar_ultima(tk, df, p_n, solo, dm) if df is not None else None
                if f is None:
                    return None
                f = dict(f)
                f["Preset"], f["TF"], f["_modo"] = n, tf_n, p_n.modo
                f["notas"] = f"[{n}] " + f["notas"]
                return f

            with st.spinner(f"Escaneando {len(tareas)} activos de {len(elegidos)} preset(s)..."):
                with ThreadPoolExecutor(max_workers=8) as ex:
                    res = list(ex.map(_uno, tareas))
            st.session_state[k_res] = [r for r in res if r]
            st.session_state[k_fall] = [f"{t[0]} · {t[2]}" for t, r in zip(tareas, res) if r is None]
            st.session_state[k_np] = len(elegidos)
            st.session_state[k_sig] = firma

        filas = st.session_state.get(k_res)
        if filas is None:
            return
        if st.session_state.get(k_fall):
            st.warning("Sin datos suficientes (~150 velas y su temporalidad superior): "
                       + ", ".join(st.session_state[k_fall]))
        if not filas:
            st.info("No hubo resultados.")
            return

        n_sig = sum(1 for r in filas if r["Señal"] != "—")
        solo_sig = st.checkbox("Mostrar solo activos con señal completa", key=f"{key}_multi_solo")
        vis = [r for r in filas if r["Señal"] != "—"] if solo_sig else list(filas)
        st.caption(f"{n_sig} activo(s) con señal completa de {len(filas)} analizados en "
                   f"{st.session_state.get(k_np, '?')} preset(s). "
                   "Exigir todos los filtros a la vez es estricto: lo normal es que pocos pasen.")
        if not vis:
            st.info("Ningún activo cumple todos los filtros en este momento.")
            return

        vis = sorted(vis, key=lambda r: (r["Señal"] == "—", -r["_n"]))
        cols = ["Preset", "TF", "Ticker", "Señal", "Filtros OK", "Macro", "ADX macro", "Precio", "Acum", "Antic", "Sent",
                "ADX", "+DI", "-DI", "CMF", "RVOL", "MACD hist", "CCI", "Falta cumplir"]
        st.dataframe(pd.DataFrame(vis)[cols], use_container_width=True, hide_index=True,
                     height=min(600, len(vis) * 36 + 45),
                     column_config={
                         "Precio": st.column_config.NumberColumn(format="%.4f"),
                         "Acum": st.column_config.NumberColumn(format="%.0f"),
                         "Antic": st.column_config.NumberColumn(format="%.0f"),
                         "Sent": st.column_config.NumberColumn(format="%.0f"),
                         "ADX": st.column_config.NumberColumn(format="%.0f"),
                         "+DI": st.column_config.NumberColumn(format="%.0f"),
                         "-DI": st.column_config.NumberColumn(format="%.0f"),
                         "CMF": st.column_config.NumberColumn(format="%+.2f"),
                         "RVOL": st.column_config.NumberColumn(format="%.2fx"),
                         "MACD hist": st.column_config.NumberColumn(format="%+.4f"),
                         "CCI": st.column_config.NumberColumn(format="%.0f"),
                     })

        if on_cargar is not None:
            st.divider()
            st.markdown("**Cargar un activo en el formulario de señal** "
                        "(SL/TP precalculados con los parámetros de su preset; revisalos antes de publicar)")
            por_lbl = {f"{r['Preset']} · {r['TF']} · {r['Ticker']}": r for r in vis}
            lbl_sel = st.selectbox("Activo", list(por_lbl.keys()), key=f"{key}_multi_sel_cargar")
            fila = por_lbl[lbl_sel]
            b1, b2 = st.columns(2)
            b1.button("🟢 Cargar como LARGO", key=f"{key}_multi_cargar_l", use_container_width=True,
                      on_click=on_cargar, args=(fila, "LARGO"))
            if fila.get("_modo") == "futuros":
                b2.button("🔴 Cargar como CORTO", key=f"{key}_multi_cargar_s",
                          use_container_width=True, on_click=on_cargar, args=(fila, "CORTO"))


# ==============================================================
#  UI STREAMLIT
# ==============================================================

def render_scanner_multifactor(on_cargar=None, key: str = "mf", store=None):
    """on_cargar(fila, lado) se ejecuta como callback de botón ('LARGO' / 'CORTO').
    store: objeto con listar()/guardar(nombre, datos)/eliminar(nombre).
           Por defecto usa un JSON local (PresetStoreJSON)."""
    import streamlit as st
    import plotly.graph_objects as go

    store = store or PresetStoreJSON()
    dl = st.cache_data(ttl=900, show_spinner=False)(descargar_ohlcv)

    st.markdown("#### 📊 Scanner Multi-Factor + Backtest")
    st.caption("Filtros de tendencia (ADX/DI), scores, convicción (CMF/RVOL) y momento (MACD/CCI). "
               "El backtest incluye comisiones, slippage y SL/TP dinámicos por ATR.")

    # ─────────────── PRESETS ───────────────
    k_sel, k_nom, k_msg = f"{key}_preset_sel", f"{key}_preset_nombre", f"{key}_preset_msg"

    def _cb_cargar():
        nombre = st.session_state.get(k_sel)
        datos = store.listar().get(nombre)
        if datos:
            _aplicar_preset(st, key, datos)
            st.session_state[k_nom] = nombre
            st.session_state[k_msg] = ("ok", f"Preset «{nombre}» cargado.")
        else:
            st.session_state[k_msg] = ("warn", "No se encontró el preset seleccionado.")

    def _cb_guardar():
        nombre = (st.session_state.get(k_nom) or "").strip()
        if not nombre:
            st.session_state[k_msg] = ("warn", "Escribí un nombre para el preset.")
            return
        try:
            store.guardar(nombre, _snapshot_preset(st, key))
            st.session_state[k_msg] = ("ok", f"Preset «{nombre}» guardado.")
        except Exception as e:
            st.session_state[k_msg] = ("warn", f"No se pudo guardar el preset: {e}")

    def _cb_eliminar():
        nombre = st.session_state.get(k_sel)
        if not nombre:
            return
        try:
            store.eliminar(nombre)
            st.session_state.pop(k_sel, None)
            st.session_state[k_msg] = ("ok", f"Preset «{nombre}» eliminado.")
        except Exception as e:
            st.session_state[k_msg] = ("warn", f"No se pudo eliminar el preset: {e}")

    presets = store.listar()
    with st.expander(f"💾 Presets ({len(presets)})", expanded=False):
        p1, p2 = st.columns([3, 1])
        if presets:
            p1.selectbox("Preset guardado", sorted(presets.keys()), key=k_sel)
            p2.write("")
            p2.button("📂 Cargar", key=f"{key}_pre_load", on_click=_cb_cargar,
                      use_container_width=True)
            p2.button("🗑️ Eliminar", key=f"{key}_pre_del", on_click=_cb_eliminar,
                      use_container_width=True)
        else:
            st.caption("Todavía no hay presets guardados.")
        n1, n2 = st.columns([3, 1])
        n1.text_input("Nombre para guardar (si ya existe, lo sobrescribe)", key=k_nom,
                      placeholder="Ej: Cripto futuros")
        n2.write("")
        n2.button("💾 Guardar", key=f"{key}_pre_save", on_click=_cb_guardar,
                  use_container_width=True)
        st.caption("Guarda mercado, temporalidad, parámetros, tickers del Scanner y del Backtest, "
                   "e histórico.")
        msg = st.session_state.pop(k_msg, None)
        if msg:
            (st.success if msg[0] == "ok" else st.warning)(msg[1])

    # ─────────────── PERFILES AUTOMÁTICOS POR TEMPORALIDAD ───────────────
    def _aplicar_perfil_actual():
        tf = st.session_state.get(f"{key}_tf", "Diario")
        perf = perfil_para(TEMPORALIDADES[tf]["iv"])
        for suf, campo in _PERFIL_A_WIDGET.items():
            st.session_state[f"{key}_{suf}"] = int(perf[campo]) if suf == "maxbar" else float(perf[campo])

    def _cb_tf():
        if st.session_state.get(f"{key}_perfil", True):
            _aplicar_perfil_actual()

    def _cb_perfil():
        if st.session_state.get(f"{key}_perfil", True):
            _aplicar_perfil_actual()

    # ─────────────── PARÁMETROS ───────────────
    with st.expander("⚙️ Parámetros", expanded=False):
        modo_lbl = st.radio("Mercado", MODOS_LBL, horizontal=True, key=f"{key}_modo")
        tf_lbl = st.radio("Temporalidad", list(TEMPORALIDADES.keys()),
                          index=list(TEMPORALIDADES.keys()).index("Diario"),
                          horizontal=True, key=f"{key}_tf", on_change=_cb_tf,
                          help="Se aplica al Scanner y al Backtest. Ojo: scores, ventanas e "
                               "indicadores se calculan en velas, así que los mismos números "
                               "cubren un tiempo distinto en cada temporalidad.")
        cfg = TEMPORALIDADES[tf_lbl]
        st.caption("⏱️ " + cfg["nota"])
        a1, a2, a3, a4 = st.columns(4)
        acum_l_min = a1.number_input("Acumulación LARGOS mín.", 0.0, 100.0, 50.0, 5.0, key=f"{key}_acum_lmin",
                                     help="Largos: el score de Acumulación debe estar entre el mínimo y el máximo.")
        acum_l_max = a2.number_input("Acumulación LARGOS máx.", 0.0, 100.0, 100.0, 5.0, key=f"{key}_acum_lmax")
        acum_c_min = a3.number_input("Acumulación CORTOS mín.", 0.0, 100.0, 0.0, 5.0, key=f"{key}_acum_cmin",
                                     help="Cortos: el score de Acumulación debe estar entre el mínimo y el máximo.")
        acum_c_max = a4.number_input("Acumulación CORTOS máx.", 0.0, 100.0, 50.0, 5.0, key=f"{key}_acum_cmax")
        s1, s2, s3, s4 = st.columns(4)
        sent_l_min = s1.number_input("Sentimiento LARGOS mín.", 0.0, 100.0, 0.0, 5.0, key=f"{key}_sent_lmin",
                                     help="Largos: el Sentimiento debe estar entre el mínimo y el máximo "
                                          "(el máximo es el tope anti-euforia).")
        sent_l_max = s2.number_input("Sentimiento LARGOS máx.", 0.0, 100.0, 85.0, 5.0, key=f"{key}_sent_lmax")
        sent_c_min = s3.number_input("Sentimiento CORTOS mín.", 0.0, 100.0, 15.0, 5.0, key=f"{key}_sent_cmin",
                                     help="Cortos: el Sentimiento debe estar entre el mínimo y el máximo "
                                          "(el mínimo es el piso anti-pánico).")
        sent_c_max = s4.number_input("Sentimiento CORTOS máx.", 0.0, 100.0, 100.0, 5.0, key=f"{key}_sent_cmax")
        if acum_l_min > acum_l_max or acum_c_min > acum_c_max or sent_l_min > sent_l_max or sent_c_min > sent_c_max:
            st.warning("Algún mínimo es mayor que su máximo: ese filtro nunca se va a cumplir.")
        c1, c2, c3, c4 = st.columns(4)
        min_antic = c1.number_input("Anticipación mín.", 0.0, 100.0, 50.0, 5.0, key=f"{key}_antic")
        adx_u = c2.number_input("ADX umbral", 5.0, 60.0, 25.0, 1.0, key=f"{key}_adx")
        c5, c6, c7, c8 = st.columns(4)
        rvol_min = c5.number_input("RVOL mín.", 0.5, 5.0, 1.5, 0.05, format="%.2f", key=f"{key}_rvol")
        cci_inf = c6.number_input("CCI inferior", -300.0, 0.0, -100.0, 25.0, key=f"{key}_cci_i")
        cci_sup = c7.number_input("CCI superior", 0.0, 400.0, 200.0, 25.0, key=f"{key}_cci_s")
        exig_vol = c8.checkbox("Exigir volumen", True, key=f"{key}_exvol",
                               help="Si lo desactivás, activos sin volumen (forex) saltan CMF/RVOL.")
        d1, d2, d3, d4 = st.columns(4)
        sl_atr = d1.number_input("SL (× ATR)", 0.5, 10.0, 2.0, 0.1, format="%.2f", key=f"{key}_sl")
        tp_atr = d2.number_input("TP (× ATR)", 0.5, 20.0, 3.0, 0.1, format="%.2f", key=f"{key}_tp")
        comision = d3.number_input("Comisión % por lado", 0.0, 2.0, 0.10, 0.01, format="%.3f", key=f"{key}_com")
        slippage = d4.number_input("Slippage % por fill", 0.0, 2.0, 0.05, 0.01, format="%.3f", key=f"{key}_slip")
        e1, e2, e3, e4 = st.columns(4)
        capital = e1.number_input("Capital (USD)", 100.0, 1e9, 10000.0, 500.0, key=f"{key}_cap")
        riesgo = e2.number_input("Riesgo % por operación", 0.1, 10.0, 1.0, 0.25, key=f"{key}_riesgo")
        apal = e3.number_input("Apalancamiento máx. (x)", 1.0, 125.0, 1.0, 1.0, key=f"{key}_apal")
        max_bar = e4.number_input("Máx. velas en operación", 0, 500, 70, 5, key=f"{key}_maxbar",
                                  help="En velas de la temporalidad elegida (30 velas = 30 horas en 1 hora, "
                                       "30 días en diario). 0 = sin salida por tiempo.")
        f1, f2, f3, f4 = st.columns(4)
        f1.checkbox("Auto-ajustar por temporalidad", True, key=f"{key}_perfil", on_change=_cb_perfil,
                    help="Al cambiar de temporalidad carga el perfil propio de esa temporalidad "
                         "(SL, TP, ADX, RVOL y máx. velas; se editan en PERFILES dentro del código). "
                         "Podés modificar los valores a mano en pantalla.")
        mtf_on = f2.checkbox("Filtro Multi-Timeframe", True, key=f"{key}_mtf",
                             help="La tendencia (ADX/DI + estructura vs EMA 50) se lee en la temporalidad "
                                  "superior y nunca se opera en contra. El gatillo (Acum, RVOL, etc.) "
                                  "sigue en la temporalidad elegida.")
        mtf_est = f3.checkbox("MTF estricto", False, key=f"{key}_mtf_est",
                              help="Desactivado: solo se bloquea operar EN CONTRA de la tendencia macro. "
                                   "Activado: además se exige que la macro esté claramente A FAVOR.")
        fric = f4.number_input("Fricción: TP ≥ N × costos", 0.0, 20.0, 3.0, 0.5, key=f"{key}_fric",
                               help="Descarta la señal si el TP (en % del precio) no supera N veces el costo "
                                    "ida y vuelta (2 comisiones + 2 slippages). 0 = desactivado.")
        _macro_lbl = cfg.get("macro")
        st.caption("🧭 Tendencia macro (MTF): "
                   + (f"**{_macro_lbl}**" if _macro_lbl else "no aplica en esta temporalidad (usa su propia tendencia)")
                   + f" · costo ida y vuelta {2 * (comision + slippage):.2f}%"
                   + (f" → el TP debe rendir al menos {fric * 2 * (comision + slippage):.2f}% del precio."
                      if fric > 0 else " · filtro de fricción desactivado."))

    modo = "futuros" if modo_lbl.startswith("Futuros") else "spot"
    p = Params(acum_l_min=acum_l_min, acum_l_max=acum_l_max, acum_c_min=acum_c_min, acum_c_max=acum_c_max,
               sent_l_min=sent_l_min, sent_l_max=sent_l_max, sent_c_min=sent_c_min, sent_c_max=sent_c_max,
               min_antic=min_antic, adx_umbral=adx_u,
               rvol_min=rvol_min, cci_inf=cci_inf, cci_sup=cci_sup, exigir_volumen=exig_vol,
               modo=modo, sl_atr=sl_atr, tp_atr=tp_atr, comision_pct=comision,
               slippage_pct=slippage, riesgo_pct=riesgo,
               apalancamiento=apal if modo == "futuros" else 1.0,
               capital=capital, max_barras=int(max_bar), intervalo=cfg["iv"],
               mtf_activo=mtf_on, mtf_estricto=mtf_est, friccion_mult=fric)

    tab_scan, tab_bt = st.tabs(["🔎 Scanner", "🧪 Backtest"])

    # ─────────────── SCANNER ───────────────
    with tab_scan:
        _render_scan_presets(st, key, presets, dl, on_cargar)
        st.markdown("**🔎 Escaneo con los parámetros actuales (los de la pantalla)**")
        txt = st.text_area("Tickers (separados por coma)", key=f"{key}_scan_tk", height=80,
                           value="NVDA, AAPL, MSFT, TSLA, BTC-USD, ETH-USD, SOL-USD, GC=F, CL=F")
        solo_cerr = st.checkbox("Usar solo velas cerradas", True, key=f"{key}_cerradas",
                                help="Recomendado: durante la rueda el volumen de hoy es parcial y "
                                     "distorsiona RVOL y CMF.")
        firma_man = repr((txt, solo_cerr, p))
        if st.button("▶ Escanear", key=f"{key}_scan_run", type="primary"):
            tks = _parse_tickers(txt)[:60]
            st.session_state[f"{key}_scan_sig"] = firma_man

            def _uno(tk):
                df = dl(tk, cfg["scan"], cfg["fuente"], cfg["resample"])
                dm = obtener_macro(dl, tk, p)
                return evaluar_ultima(tk, df, p, solo_cerr, dm) if df is not None else None

            with st.spinner(f"Escaneando {len(tks)} activos..."):
                with ThreadPoolExecutor(max_workers=8) as ex:
                    res = list(ex.map(_uno, tks))
            st.session_state[f"{key}_scan_res"] = [r for r in res if r]
            st.session_state[f"{key}_scan_fallidos"] = [t for t, r in zip(tks, res) if r is None]
            st.session_state[f"{key}_scan_tf"] = tf_lbl

        # Si cambiaron tickers, velas cerradas o parámetros desde el último escaneo,
        # los resultados guardados quedaron obsoletos: se descartan.
        if st.session_state.get(f"{key}_scan_sig") != firma_man:
            for sfx in ("scan_res", "scan_fallidos", "scan_tf"):
                st.session_state.pop(f"{key}_{sfx}", None)

        filas = st.session_state.get(f"{key}_scan_res")
        if filas is not None:
            st.caption("⏱️ Temporalidad de este escaneo: **"
                       + st.session_state.get(f"{key}_scan_tf", tf_lbl) + "**")
            if st.session_state.get(f"{key}_scan_fallidos"):
                st.warning("Sin datos suficientes (~150 velas y su temporalidad superior): "
                           + ", ".join(st.session_state[f"{key}_scan_fallidos"]))
            if not filas:
                st.info("No hubo resultados.")
            else:
                filas = sorted(filas, key=lambda r: (r["Señal"] == "—", -r["_n"]))
                cols = ["Ticker", "Señal", "Filtros OK", "Macro", "ADX macro", "Precio", "Acum", "Antic", "Sent", "ADX",
                        "+DI", "-DI", "CMF", "RVOL", "MACD hist", "CCI", "Falta cumplir"]
                st.dataframe(pd.DataFrame(filas)[cols], use_container_width=True, hide_index=True,
                             height=min(600, len(filas) * 36 + 45),
                             column_config={
                                 "Precio": st.column_config.NumberColumn(format="%.4f"),
                                 "Acum": st.column_config.NumberColumn(format="%.0f"),
                                 "Antic": st.column_config.NumberColumn(format="%.0f"),
                                 "Sent": st.column_config.NumberColumn(format="%.0f"),
                                 "ADX": st.column_config.NumberColumn(format="%.0f"),
                                 "+DI": st.column_config.NumberColumn(format="%.0f"),
                                 "-DI": st.column_config.NumberColumn(format="%.0f"),
                                 "CMF": st.column_config.NumberColumn(format="%+.2f"),
                                 "RVOL": st.column_config.NumberColumn(format="%.2fx"),
                                 "MACD hist": st.column_config.NumberColumn(format="%+.4f"),
                                 "CCI": st.column_config.NumberColumn(format="%.0f"),
                             })
                n_sig = sum(1 for r in filas if r["Señal"] != "—")
                st.caption(f"{n_sig} activo(s) con señal completa de {len(filas)} analizados. "
                           "Exigir todos los filtros a la vez es estricto: lo normal es que pocos pasen.")

                if on_cargar is not None:
                    st.divider()
                    st.markdown("**Cargar un activo en el formulario de señal** "
                                "(SL/TP precalculados con ATR; revisalos antes de publicar)")
                    por_tk = {r["Ticker"]: r for r in filas}
                    tk_sel = st.selectbox("Activo", list(por_tk.keys()), key=f"{key}_sel_cargar")
                    fila = por_tk[tk_sel]
                    b1, b2 = st.columns(2)
                    b1.button("🟢 Cargar como LARGO", key=f"{key}_cargar_l", use_container_width=True,
                              on_click=on_cargar, args=(fila, "LARGO"))
                    if modo == "futuros":
                        b2.button("🔴 Cargar como CORTO", key=f"{key}_cargar_s", use_container_width=True,
                                  on_click=on_cargar, args=(fila, "CORTO"))

    # ─────────────── BACKTEST ───────────────
    with tab_bt:
        cb1, cb2 = st.columns([3, 1])
        with cb1:
            txt_bt = st.text_input("Tickers a testear (coma)", "BTC-USD, ETH-USD, NVDA",
                                   key=f"{key}_bt_tk")
        with cb2:
            if st.session_state.get(f"{key}_bt_per") not in cfg["periodos"]:
                st.session_state[f"{key}_bt_per"] = cfg["defecto"]
            periodo = st.selectbox("Histórico", cfg["periodos"], key=f"{key}_bt_per")

        if st.button("▶ Correr backtest", key=f"{key}_bt_run", type="primary"):
            tks = _parse_tickers(txt_bt)[:15]
            salida, sin_datos = {}, []
            with st.spinner("Descargando y simulando..."):
                for tk in tks:
                    df = dl(tk, periodo, cfg["fuente"], cfg["resample"])
                    dm = obtener_macro(dl, tk, p)
                    if df is None or len(df) < 150 or (macro_requerido(p) and dm is None):
                        sin_datos.append(tk)
                        continue
                    try:
                        salida[tk] = backtest(df, p, dm)
                    except ValueError:      # sin datos suficientes de la TF superior
                        sin_datos.append(tk)
            st.session_state[f"{key}_bt_res"] = salida
            st.session_state[f"{key}_bt_sin"] = sin_datos
            st.session_state[f"{key}_bt_cap"] = p.capital
            st.session_state[f"{key}_bt_tf"] = tf_lbl

        res = st.session_state.get(f"{key}_bt_res")
        if res is None:
            return
        if st.session_state.get(f"{key}_bt_sin"):
            st.warning("Sin datos suficientes (o de la temporalidad superior): " + ", ".join(st.session_state[f"{key}_bt_sin"]))
        if not res:
            return

        tf_res = st.session_state.get(f"{key}_bt_tf", tf_lbl)
        st.caption(f"⏱️ Temporalidad de estos resultados: **{tf_res}**"
                   + ("" if tf_res == tf_lbl else
                      " · cambiaste la temporalidad: volvé a correr el backtest."))

        # Resumen por activo + total
        filas_r = []
        for tk, r in res.items():
            m = r["metricas"]
            filas_r.append({"Ticker": tk, **{k: m[k] for k in (
                "Operaciones", "Win Rate %", "Profit Factor", "Expectativa USD", "Expectativa R",
                "Max Drawdown %", "Retorno total %", "Buy & Hold %")}})
        mt = metricas_agrupadas([r["trades"] for r in res.values()])
        filas_r.append({"Ticker": "TOTAL (operaciones juntas)", "Operaciones": mt["Operaciones"],
                        "Win Rate %": mt.get("Win Rate %"), "Profit Factor": mt.get("Profit Factor"),
                        "Expectativa USD": mt.get("Expectativa USD"),
                        "Expectativa R": mt.get("Expectativa R"),
                        "Max Drawdown %": np.nan, "Retorno total %": np.nan, "Buy & Hold %": np.nan})
        df_r = pd.DataFrame(filas_r)
        st.dataframe(df_r, use_container_width=True, hide_index=True, column_config={
            "Win Rate %": st.column_config.NumberColumn(format="%.1f%%"),
            "Profit Factor": st.column_config.NumberColumn(format="%.2f"),
            "Expectativa USD": st.column_config.NumberColumn(format="%.2f"),
            "Expectativa R": st.column_config.NumberColumn(format="%.2f"),
            "Max Drawdown %": st.column_config.NumberColumn(format="%.2f%%"),
            "Retorno total %": st.column_config.NumberColumn(format="%+.2f%%"),
            "Buy & Hold %": st.column_config.NumberColumn(format="%+.2f%%"),
        })

        st.divider()
        tk_det = st.selectbox("Ver detalle de", list(res.keys()), key=f"{key}_bt_det")
        r = res[tk_det]
        m, tr, eq = r["metricas"], r["trades"], r["equity"]

        k = st.columns(4)
        k[0].metric("Profit Factor", fmt_metrica("Profit Factor", m["Profit Factor"]))
        k[1].metric("Expectativa por operación", fmt_metrica("Expectativa USD", m["Expectativa USD"]) + " USD",
                    fmt_metrica("Expectativa R", m["Expectativa R"]) + " R", delta_color="off")
        k[2].metric("Max Drawdown", fmt_metrica("Max Drawdown %", m["Max Drawdown %"]),
                    fmt_metrica("Max Drawdown USD", m["Max Drawdown USD"]) + " USD", delta_color="off")
        k[3].metric("Win Rate", fmt_metrica("Win Rate %", m["Win Rate %"]),
                    f"{m['Operaciones']} operaciones", delta_color="off")
        k2 = st.columns(4)
        k2[0].metric("Retorno total", fmt_metrica("Retorno total %", m["Retorno total %"]))
        k2[1].metric("Buy & Hold", fmt_metrica("Buy & Hold %", m["Buy & Hold %"]))
        k2[2].metric("Ganancia media", fmt_metrica("Ganancia media USD", m["Ganancia media USD"]))
        k2[3].metric("Pérdida media", fmt_metrica("Pérdida media USD", m["Pérdida media USD"]),
                     "Payoff " + fmt_metrica("Payoff", m["Payoff"]), delta_color="off")

        layout = dict(plot_bgcolor="#0d1117", paper_bgcolor="#07090f",
                      font=dict(color="#b0bcd0"), margin=dict(l=10, r=10, t=40, b=10),
                      xaxis=dict(gridcolor="#21262d"), yaxis=dict(gridcolor="#21262d"),
                      dragmode=False)
        fig = go.Figure(go.Scatter(x=eq.index, y=eq.values, line=dict(color="#6CC24A", width=2),
                                   name="Equity"))
        fig.add_hline(y=st.session_state.get(f"{key}_bt_cap", p.capital), line_dash="dot",
                      line_color="#6b7d9a")
        fig.update_layout(**layout, title="Curva de equity", height=340)
        st.plotly_chart(fig, use_container_width=True, config=dict(displayModeBar=False),
                        key=f"{key}_fig_eq_{tk_det}")
        dd = (eq / eq.cummax() - 1) * 100
        fig2 = go.Figure(go.Scatter(x=dd.index, y=dd.values, fill="tozeroy",
                                    line=dict(color="#f85149", width=1.3),
                                    fillcolor="rgba(248,81,73,0.3)", name="Drawdown"))
        fig2.update_layout(**layout, title="Drawdown (%)", height=260)
        st.plotly_chart(fig2, use_container_width=True, config=dict(displayModeBar=False),
                        key=f"{key}_fig_dd_{tk_det}")

        if tr.empty:
            st.info("Con estos filtros no hubo operaciones en el período. Probá aflojar RVOL, "
                    "los scores o el umbral de ADX.")
        else:
            st.dataframe(tr, use_container_width=True, hide_index=True,
                         height=min(500, len(tr) * 36 + 45),
                         column_config={
                             "PnL": st.column_config.NumberColumn(format="%+.2f"),
                             "R": st.column_config.NumberColumn(format="%+.2f"),
                             "Cantidad": st.column_config.NumberColumn(format="%.6g"),
                         })
        st.caption("⚠️ Backtest histórico (in-sample): no garantiza resultados futuros y los parámetros "
                   "ajustados a un período suelen empeorar fuera de él. No incluye funding/swaps. "
                   "Con pocas operaciones (< 30) las métricas no son estadísticamente confiables. "
                   "No es asesoramiento financiero.")


# ==============================================================
#  CLI
# ==============================================================

def main():
    ap = argparse.ArgumentParser(description="Scanner Multi-Factor + Backtest con fricciones")
    ap.add_argument("tickers", nargs="+")
    ap.add_argument("--tf", choices=list(TF_POR_CODIGO.keys()), default="1d",
                    help="temporalidad: 15m, 30m, 1h, 4h, 1d, 1wk")
    ap.add_argument("--periodo", default=None,
                    help="histórico (ej. 5y, 365d). Por defecto, el de la temporalidad.")
    ap.add_argument("--modo", choices=["spot", "futuros"], default="spot")
    ap.add_argument("--sl-atr", type=float, default=None, help="por defecto, el del perfil de la temporalidad")
    ap.add_argument("--tp-atr", type=float, default=None, help="por defecto, el del perfil de la temporalidad")
    ap.add_argument("--adx", type=float, default=None, help="por defecto, el del perfil de la temporalidad")
    ap.add_argument("--rvol", type=float, default=None, help="por defecto, el del perfil de la temporalidad")
    ap.add_argument("--max-barras", type=int, default=None, help="por defecto, el del perfil de la temporalidad")
    ap.add_argument("--comision", type=float, default=0.10, help="%% por lado")
    ap.add_argument("--slippage", type=float, default=0.05, help="%% por fill")
    ap.add_argument("--riesgo", type=float, default=1.0, help="%% del equity por operación")
    ap.add_argument("--apalancamiento", type=float, default=1.0)
    ap.add_argument("--capital", type=float, default=10000.0)
    ap.add_argument("--sin-mtf", action="store_true", help="desactiva el filtro multi-timeframe")
    ap.add_argument("--mtf-estricto", action="store_true", help="exige tendencia macro A FAVOR")
    ap.add_argument("--friccion", type=float, default=3.0, help="TP >= N x costos (0 = desactiva)")
    a = ap.parse_args()

    perf = perfil_para(a.tf)

    def pick(v, k):
        return perf[k] if v is None else v

    p = Params(modo=a.modo, sl_atr=pick(a.sl_atr, "sl_atr"), tp_atr=pick(a.tp_atr, "tp_atr"),
               adx_umbral=pick(a.adx, "adx_umbral"), rvol_min=pick(a.rvol, "rvol_min"),
               comision_pct=a.comision, slippage_pct=a.slippage, riesgo_pct=a.riesgo,
               apalancamiento=a.apalancamiento if a.modo == "futuros" else 1.0,
               capital=a.capital, max_barras=int(pick(a.max_barras, "max_barras")),
               intervalo=a.tf, mtf_activo=not a.sin_mtf, mtf_estricto=a.mtf_estricto,
               friccion_mult=a.friccion)
    cfg = TF_POR_CODIGO[a.tf]
    periodo = a.periodo or cfg["defecto"]

    print(f"\n--- SCANNER (última vela cerrada) · {a.tf} · SL {p.sl_atr:g} / TP {p.tp_atr:g} × ATR ---")
    todos = []
    for tk in a.tickers:
        df = descargar_ohlcv(tk, periodo, cfg["fuente"], cfg["resample"])
        dm = obtener_macro(descargar_ohlcv, tk, p)
        if df is None or len(df) < 150 or (macro_requerido(p) and dm is None):
            print(f"  {tk}: sin datos suficientes (o de la temporalidad superior)")
            continue
        fila = evaluar_ultima(tk, df, p, True, dm)
        if fila:
            print(f"  {tk:<10} {fila['Señal']:<10} filtros {fila['Filtros OK']:<5} macro {fila['Macro']:<10} "
                  f"falta: {fila['Falta cumplir']}")
        try:
            r = backtest(df, p, dm)
        except ValueError:
            print(f"  {tk}: sin datos de la temporalidad superior para el backtest")
            continue
        imprimir_metricas(tk, r["metricas"])
        todos.append(r["trades"])
    if len(todos) > 1:
        imprimir_metricas("TOTAL (operaciones juntas)", metricas_agrupadas(todos))


if __name__ == "__main__":
    main()
