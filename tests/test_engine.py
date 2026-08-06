"""
Tests básicos del motor de cointegración usando series sintéticas.
Ejecutar con: pytest tests/
"""

import numpy as np
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.cointegration_engine import (
    analyze_pair,
    calculate_spread,
    calculate_zscore,
    generate_signals,
    adf_test,
    johansen_test,
    hurst_exponent,
)


def _make_cointegrated_pair(n=500, seed=42):
    rng = np.random.default_rng(seed)
    common = np.cumsum(rng.normal(0, 1, n))
    a = 100 + common + rng.normal(0, 1, n)
    b = 50 + 0.5 * common + rng.normal(0, 1, n)
    idx = pd.date_range("2023-01-01", periods=n)
    return pd.Series(a, index=idx, name="A"), pd.Series(b, index=idx, name="B")


def test_cointegrated_pair_detected():
    a, b = _make_cointegrated_pair()
    stats = analyze_pair(a, b, "A", "B")
    assert stats.is_cointegrated
    assert stats.pvalue < 0.05


def test_independent_series_not_cointegrated():
    rng = np.random.default_rng(1)
    n = 500
    idx = pd.date_range("2023-01-01", periods=n)
    a = pd.Series(100 + np.cumsum(rng.normal(0, 1, n)), index=idx)
    b = pd.Series(50 + np.cumsum(rng.normal(0, 1, n)), index=idx)
    stats = analyze_pair(a, b, "A", "B")
    assert stats.pvalue > 0.05


def test_signals_are_valid_states():
    a, b = _make_cointegrated_pair()
    stats = analyze_pair(a, b, "A", "B")
    spread = calculate_spread(a, b, stats.hedge_ratio, stats.intercept)
    zscore = calculate_zscore(spread, window=30)
    signal = generate_signals(zscore, entry_z=2.0, exit_z=0.5)
    assert set(signal.unique()).issubset({-1, 0, 1})


def test_no_lookahead_flat_start():
    a, b = _make_cointegrated_pair()
    stats = analyze_pair(a, b, "A", "B")
    spread = calculate_spread(a, b, stats.hedge_ratio, stats.intercept)
    zscore = calculate_zscore(spread, window=30)
    signal = generate_signals(zscore, entry_z=2.0, exit_z=0.5)
    # Antes de completarse la ventana de z-score no debe haber señal
    assert (signal.iloc[:29] == 0).all()


def test_adf_on_stationary_spread():
    a, b = _make_cointegrated_pair()
    stats = analyze_pair(a, b, "A", "B")
    spread = calculate_spread(a, b, stats.hedge_ratio, stats.intercept)
    result = adf_test(spread)
    assert result["is_stationary"]
    assert result["pvalue"] < 0.05


def test_johansen_multivariate():
    a, b = _make_cointegrated_pair()
    df = pd.DataFrame({"A": a, "B": b})
    result = johansen_test(df, significance=0.05)
    assert result["n_cointegrating_relations"] >= 1
    assert result["is_cointegrated"]


def test_hurst_mean_reverting_spread_below_half():
    a, b = _make_cointegrated_pair()
    stats = analyze_pair(a, b, "A", "B")
    spread = calculate_spread(a, b, stats.hedge_ratio, stats.intercept)
    h = hurst_exponent(spread)
    assert h is not None
    assert h < 0.5  # el spread cointegrado debe ser anti-persistente


def test_hurst_random_walk_near_half():
    rng = np.random.default_rng(7)
    idx = pd.date_range("2023-01-01", periods=500)
    rw = pd.Series(np.cumsum(rng.normal(0, 1, 500)), index=idx)
    h = hurst_exponent(rw)
    assert 0.35 < h < 0.75  # random walk puro ronda 0.5


if __name__ == "__main__":
    test_cointegrated_pair_detected()
    test_independent_series_not_cointegrated()
    test_signals_are_valid_states()
    test_no_lookahead_flat_start()
    test_adf_on_stationary_spread()
    test_johansen_multivariate()
    test_hurst_mean_reverting_spread_below_half()
    test_hurst_random_walk_near_half()
    print("Todos los tests pasaron ✅")
