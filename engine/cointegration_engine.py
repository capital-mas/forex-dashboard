"""
Statistical Arbitrage - Cointegration Trading Engine
======================================================
Motor de señales para arbitraje estadístico basado en cointegración
(Engle-Granger) y z-score del spread entre pares de activos.

Uso típico:
    stats = analyze_pair(price_a, price_b, "AAPL", "MSFT")
    zscore = calculate_zscore(spread, window=30)
    signals = generate_signals(zscore, entry_z=2.0, exit_z=0.5)
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Optional

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.stattools import coint, adfuller
from statsmodels.tsa.vector_ar.vecm import coint_johansen


@dataclass
class PairStats:
    asset_a: str
    asset_b: str
    pvalue: float                 # p-value del test de Engle-Granger
    is_cointegrated: bool
    hedge_ratio: float
    intercept: float
    half_life: Optional[float]
    adf_pvalue: Optional[float] = None     # ADF aplicado directo al spread
    adf_is_stationary: Optional[bool] = None
    hurst: Optional[float] = None          # Hurst exponent del spread
    current_zscore: Optional[float] = None


# ---------------------------------------------------------------------------
# Tests estadísticos y cálculo del spread
# ---------------------------------------------------------------------------

def test_cointegration(series_a: pd.Series, series_b: pd.Series, significance: float = 0.05):
    """Test de cointegración de Engle-Granger entre dos series de precios.

    Devuelve (p_value, es_cointegrado).
    """
    series_a, series_b = series_a.align(series_b, join="inner")
    _, pvalue, _ = coint(series_a, series_b)
    return float(pvalue), pvalue < significance


def adf_test(series: pd.Series, significance: float = 0.05) -> dict:
    """Test de Dickey-Fuller Aumentado (ADF) de estacionariedad, aplicado
    directamente sobre una serie (típicamente el spread de un par).

    H0: la serie tiene raíz unitaria (NO es estacionaria / no revierte a la media)
    Si pvalue < significance -> se rechaza H0 -> la serie ES estacionaria.
    """
    series = series.dropna()
    stat, pvalue, _, _, crit_values, _ = adfuller(series, autolag="AIC")
    return {
        "adf_statistic": float(stat),
        "pvalue": float(pvalue),
        "critical_values": {k: float(v) for k, v in crit_values.items()},
        "is_stationary": pvalue < significance,
    }


def johansen_test(price_df: pd.DataFrame, significance: float = 0.05,
                   det_order: int = 0, k_ar_diff: int = 1) -> dict:
    """Test de Johansen: cointegración multivariada (2 o más series a la vez).

    A diferencia de Engle-Granger (que solo compara 2 series y depende de
    cuál se usa como variable dependiente), Johansen evalúa TODAS las
    combinaciones lineales posibles entre N series simultáneamente y es
    la herramienta correcta para canastas de 3+ activos (ej. arbitraje
    de ETF vs. sus componentes, o cestas sectoriales).

    Devuelve cuántas relaciones de cointegración existen (trace test) y
    los vectores de cointegración (pesos) de cada una.
    """
    df = price_df.dropna()
    result = coint_johansen(df, det_order, k_ar_diff)

    sig_col = {0.10: 0, 0.05: 1, 0.01: 2}.get(significance, 1)
    trace_stat = result.lr1
    crit_values = result.cvt[:, sig_col]
    n_relations = int(np.sum(trace_stat > crit_values))

    return {
        "columns": list(df.columns),
        "trace_statistic": trace_stat.tolist(),
        "critical_values": crit_values.tolist(),
        "n_cointegrating_relations": n_relations,
        "is_cointegrated": n_relations > 0,
        "eigenvectors": result.evec.tolist(),  # pesos de cada combinación lineal
    }


def hurst_exponent(series: pd.Series, max_lag: int = 100) -> Optional[float]:
    """Exponente de Hurst de una serie (ej. el spread), vía método de rango
    reescalado aproximado sobre diferencias.

    H < 0.5  -> mean-reverting (anti-persistente, ideal para pairs trading)
    H = 0.5  -> random walk (sin estructura explotable)
    H > 0.5  -> trending / persistente (no apto para mean reversion)
    """
    series = series.dropna().values
    n = len(series)
    max_lag = min(max_lag, n // 2)
    if max_lag < 5:
        return None
    lags = range(2, max_lag)
    tau = [np.std(series[lag:] - series[:-lag]) for lag in lags]
    tau = [t if t > 1e-12 else 1e-12 for t in tau]
    # Para un random walk, std(diff) ~ sqrt(lag) * sigma, así que la pendiente
    # de log(tau) vs log(lag) ES el exponente de Hurst directamente (H=0.5 para RW).
    poly = np.polyfit(np.log(list(lags)), np.log(tau), 1)
    return float(poly[0])


def calculate_hedge_ratio(series_a: pd.Series, series_b: pd.Series):
    """Ratio de cobertura (beta) vía regresión OLS: A = beta * B + intercept."""
    series_a, series_b = series_a.align(series_b, join="inner")
    x = sm.add_constant(series_b)
    model = sm.OLS(series_a, x).fit()
    intercept, beta = model.params.iloc[0], model.params.iloc[1]
    return float(beta), float(intercept)


def calculate_spread(series_a: pd.Series, series_b: pd.Series,
                      hedge_ratio: float, intercept: float = 0.0) -> pd.Series:
    """Spread = A - (beta * B + intercept)."""
    series_a, series_b = series_a.align(series_b, join="inner")
    return series_a - hedge_ratio * series_b - intercept


def calculate_half_life(spread: pd.Series) -> Optional[float]:
    """Vida media de reversión a la media, asumiendo un proceso Ornstein-Uhlenbeck.

    Se estima por regresión: delta_spread(t) = theta * spread(t-1) + eps
    half_life = -ln(2) / theta
    Devuelve None si theta >= 0 (no hay reversión a la media).
    """
    spread = spread.dropna()
    lag = spread.shift(1)
    delta = spread - lag
    df = pd.concat([lag, delta], axis=1).dropna()
    df.columns = ["lag", "delta"]
    if len(df) < 10:
        return None
    x = sm.add_constant(df["lag"])
    model = sm.OLS(df["delta"], x).fit()
    theta = model.params.iloc[1]
    if theta >= 0:
        return None
    return float(-np.log(2) / theta)


# ---------------------------------------------------------------------------
# Z-score y señales
# ---------------------------------------------------------------------------

def calculate_zscore(spread: pd.Series, window: int = 30) -> pd.Series:
    """Z-score móvil del spread sobre una ventana dada."""
    mean = spread.rolling(window).mean()
    std = spread.rolling(window).std()
    return (spread - mean) / std


def generate_signals(zscore: pd.Series, entry_z: float = 2.0, exit_z: float = 0.5) -> pd.Series:
    """Genera señales de posición a partir del z-score del spread.

     1  -> long spread  (comprar A, vender B)
    -1  -> short spread (vender A, comprar B)
     0  -> flat / sin posición

    Reglas:
      - Entra en short si z > entry_z
      - Entra en long  si z < -entry_z
      - Cierra long  cuando z sube hasta -exit_z
      - Cierra short cuando z baja hasta  exit_z
    """
    signal = pd.Series(0, index=zscore.index, dtype=int)
    position = 0
    for i in range(len(zscore)):
        z = zscore.iloc[i]
        if pd.isna(z):
            signal.iloc[i] = position
            continue
        if position == 0:
            if z > entry_z:
                position = -1
            elif z < -entry_z:
                position = 1
        elif position == 1 and z >= -exit_z:
            position = 0
        elif position == -1 and z <= exit_z:
            position = 0
        signal.iloc[i] = position
    return signal


# ---------------------------------------------------------------------------
# Análisis de un par y escaneo de universo
# ---------------------------------------------------------------------------

def analyze_pair(price_a: pd.Series, price_b: pd.Series, name_a: str, name_b: str,
                  zscore_window: int = 30, significance: float = 0.05) -> PairStats:
    """Corre el pipeline completo de cointegración para un par de activos."""
    pvalue, is_coint = test_cointegration(price_a, price_b, significance)
    hedge_ratio, intercept = calculate_hedge_ratio(price_a, price_b)
    spread = calculate_spread(price_a, price_b, hedge_ratio, intercept)
    hl = calculate_half_life(spread)
    adf_result = adf_test(spread, significance)
    hurst = hurst_exponent(spread)
    zscore = calculate_zscore(spread, zscore_window)
    valid_z = zscore.dropna()
    current_z = float(valid_z.iloc[-1]) if len(valid_z) else None
    return PairStats(
        asset_a=name_a, asset_b=name_b, pvalue=pvalue, is_cointegrated=is_coint,
        hedge_ratio=hedge_ratio, intercept=intercept, half_life=hl,
        adf_pvalue=adf_result["pvalue"], adf_is_stationary=adf_result["is_stationary"],
        hurst=hurst, current_zscore=current_z,
    )


def scan_universe(price_df: pd.DataFrame, significance: float = 0.05,
                   zscore_window: int = 30) -> pd.DataFrame:
    """Escanea todas las combinaciones de pares en price_df y devuelve
    un DataFrame ordenado por p-value (los más cointegrados primero).
    """
    results = []
    tickers = list(price_df.columns)
    for a, b in combinations(tickers, 2):
        try:
            series_a = price_df[a].dropna()
            series_b = price_df[b].dropna()
            stats = analyze_pair(series_a, series_b, a, b, zscore_window, significance)
            results.append(stats)
        except Exception:
            continue
    if not results:
        return pd.DataFrame()
    df = pd.DataFrame([r.__dict__ for r in results])
    return df.sort_values("pvalue").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Evaluación rápida de la señal (P&L simplificado, sin costos/slippage)
# ---------------------------------------------------------------------------

def compute_strategy_returns(price_a: pd.Series, price_b: pd.Series,
                              hedge_ratio: float, signal: pd.Series) -> pd.Series:
    """Retorno diario aproximado de la estrategia long/short spread.

    position=1  -> long A, short (hedge_ratio) B
    position=-1 -> short A, long (hedge_ratio) B
    Nota: es una aproximación educativa, no incluye comisiones, slippage
    ni financiamiento de posiciones cortas.
    """
    price_a, price_b = price_a.align(price_b, join="inner")
    ret_a = price_a.pct_change()
    ret_b = price_b.pct_change()
    signal = signal.reindex(price_a.index).ffill().fillna(0)
    strat_ret = signal.shift(1) * (ret_a - hedge_ratio * ret_b)
    return strat_ret.fillna(0)
