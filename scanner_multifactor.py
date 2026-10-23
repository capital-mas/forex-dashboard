# ==============================================================
#  SCANNER ADX + CMF + CRUCE DE MEDIAS MÓVILES  /  MOTOR DE BACKTESTING
#
#  Uso 1 — script independiente:
#      python scanner_multifactor.py NVDA BTC-USD GC=F --periodo 5y --modo spot
#      python scanner_multifactor.py BTC-USD ETH-USD --modo futuros --ma-rapida 20 --ma-lenta 50
#      python scanner_multifactor.py BTC-USD --tipo-rapida EMA --tipo-lenta SMA --ma-rapida 9 --ma-lenta 21
#
#  Uso 2 — dentro de la app:
#      from scanner_multifactor import render_scanner_multifactor
#      render_scanner_multifactor(on_cargar=_cargar_desde_multifactor)
#
#  Uso 3 — con presets en Supabase:
#      render_scanner_multifactor(on_cargar=..., store=PresetStoreSupabase(supabase))
#
#  SEÑALES (todos los filtros deben cumplirse)
#   1. Cruce de medias (gatillo):
#        - la media RÁPIDA cruza por ENCIMA de la LENTA  -> LARGO
#        - la media RÁPIDA cruza por DEBAJO de la LENTA  -> CORTO (solo en Futuros)
#      Cada media se configura aparte: tipo (SMA / EMA) y período.
#      "Velas de validez del cruce": 1 = el cruce tiene que ser en la última vela;
#      con 2 o más, sigue valiendo hasta N velas después (siempre que la rápida
#      siga del lado correcto de la lenta).
#   2. Tendencia ADX/DI: bloquea compras si ADX > umbral y -DI domina
#      (espejo para cortos).
#   3. CMF: > mínimo en largos / < -mínimo en cortos.
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
#   - No incluye funding rate ni swaps.
# ==============================================================

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd


# ==============================================================
#  PARÁMETROS
# ==============================================================

@dataclass
class Params:
    # ── Medias móviles ──
    ma_rapida: int = 20
    ma_rapida_tipo: str = "EMA"       # 'SMA' | 'EMA'
    ma_lenta: int = 50
    ma_lenta_tipo: str = "EMA"
    cruce_ventana: int = 1            # velas durante las que vale un cruce
    # ── Filtros ──
    adx_umbral: float = 18.0
    cmf_min: float = 0.0
    exigir_volumen: bool = True       # False: activos sin volumen (forex) saltan CMF
    # ── Backtest ──
    modo: str = "futuros"             # 'spot' (solo largos) | 'futuros' (largos y cortos)
    sl_atr: float = 1.5
    tp_atr: float = 2.0
    comision_pct: float = 0.10        # % por lado
    slippage_pct: float = 0.05        # % por fill
    riesgo_pct: float = 1.0           # % del equity arriesgado por operación
    apalancamiento: float = 1.0
    capital: float = 10000.0
    max_barras: int = 70              # salida por tiempo (0 = sin límite), en velas
    intervalo: str = "1d"             # 1d, 1wk


# ==============================================================
#  DATOS
# ==============================================================

TEMPORALIDADES = {
    "Diario": dict(iv="1d", fuente="1d", resample=None, scan="2y",
                   periodos=["2y", "5y", "10y"], defecto="5y", delta=pd.Timedelta(days=1),
                   nota="Hasta 10 años de histórico."),
    "Semanal": dict(iv="1wk", fuente="1wk", resample=None, scan="10y",
                    periodos=["5y", "10y", "20y"], defecto="10y", delta=pd.Timedelta(days=7),
                    nota="Pocas operaciones por año: conviene histórico de 10 a 20 años."),
}
TF_POR_CODIGO = {c["iv"]: c for c in TEMPORALIDADES.values()}

PERFIL_BASE = dict(max_barras=70, sl_atr=1.5, tp_atr=2.0, adx_umbral=18.0)
PERFILES = {"1d": dict(PERFIL_BASE), "1wk": dict(PERFIL_BASE)}
_PERFIL_A_WIDGET = {"sl": "sl_atr", "tp": "tp_atr", "adx": "adx_umbral", "maxbar": "max_barras"}

TIPOS_MA = ["SMA", "EMA"]


def perfil_para(iv: str) -> dict:
    return PERFILES.get(iv, PERFIL_BASE)


def min_velas(p: Params) -> int:
    """Velas mínimas para que la media lenta y el ADX estén calculados."""
    return max(60, p.ma_lenta + 30, p.ma_rapida + 30)


def _vela_abierta(ts, delta) -> bool:
    """True si la vela que empieza en ts todavía no cerró."""
    ahora = pd.Timestamp.now(tz=ts.tz) if getattr(ts, "tz", None) is not None else pd.Timestamp.now()
    return ts + delta > ahora


def descargar_ohlcv(ticker: str, period: str = "2y", interval: str = "1d",
                    resample: str | None = None) -> pd.DataFrame | None:
    try:
        import yfinance as yf
        if period.endswith("d"):
            dias = int(period[:-1])
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


def _media(c: pd.Series, tipo: str, n: int) -> pd.Series:
    n = max(1, int(n))
    if str(tipo).upper() == "EMA":
        return c.ewm(span=n, adjust=False, min_periods=n).mean()
    return c.rolling(n).mean()


def calcular_indicadores(df: pd.DataFrame, p: Params) -> pd.DataFrame:
    o, h, l, c, v = df["Open"], df["High"], df["Low"], df["Close"], df["Volume"]
    out = pd.DataFrame(index=df.index)
    out["Open"], out["High"], out["Low"], out["Close"] = o, h, l, c

    # ATR (Wilder, 14)
    out["atr"] = _true_range(h, l, c).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    # ADX / +DI / -DI (Wilder, 14)
    out["adx"], out["pdi"], out["mdi"] = _adx_di(h, l, c)

    # CMF (20)
    rango = (h - l).replace(0, np.nan)
    mfv = ((c - l) - (h - c)) / rango * v
    out["cmf"] = mfv.rolling(20).sum() / v.rolling(20).sum().replace(0, np.nan)

    # Medias móviles y cruces
    out["ma_r"] = _media(c, p.ma_rapida_tipo, p.ma_rapida)
    out["ma_l"] = _media(c, p.ma_lenta_tipo, p.ma_lenta)
    d = out["ma_r"] - out["ma_l"]
    prev = d.shift(1)
    out["cruce_up"] = (prev <= 0) & (d > 0)     # rápida cruza por encima de la lenta
    out["cruce_dn"] = (prev >= 0) & (d < 0)     # rápida cruza por debajo de la lenta
    return out


def etiqueta_cruce(u) -> str:
    if bool(u.get("cruce_up", False)):
        return "▲ cruce alcista"
    if bool(u.get("cruce_dn", False)):
        return "▼ cruce bajista"
    return "—"


# ==============================================================
#  CONDICIONES / SEÑALES
# ==============================================================

def condiciones(ind: pd.DataFrame, p: Params):
    """Devuelve (dict_largo, dict_corto) de Series booleanas, una por filtro."""
    sin_vol = ind["cmf"].isna()
    saltar_vol = (sin_vol & (not p.exigir_volumen))

    n = max(1, int(p.cruce_ventana))
    up_w = ind["cruce_up"].astype(float).rolling(n, min_periods=1).max() > 0
    dn_w = ind["cruce_dn"].astype(float).rolling(n, min_periods=1).max() > 0

    largo = {
        "Cruce MA": up_w & (ind["ma_r"] > ind["ma_l"]),
        "Tendencia ADX/DI": ~((ind["adx"] > p.adx_umbral) & (ind["mdi"] > ind["pdi"])),
        "CMF": (ind["cmf"] > p.cmf_min) | saltar_vol,
    }
    corto = {
        "Cruce MA": dn_w & (ind["ma_r"] < ind["ma_l"]),
        "Tendencia ADX/DI": ~((ind["adx"] > p.adx_umbral) & (ind["pdi"] > ind["mdi"])),
        "CMF": (ind["cmf"] < -p.cmf_min) | saltar_vol,
    }
    return largo, corto


def _validas(ind: pd.DataFrame) -> pd.Series:
    return ind[["ma_r", "ma_l", "adx", "pdi", "mdi", "atr"]].notna().all(axis=1)


def generar_senales(ind: pd.DataFrame, p: Params):
    cl, cs = condiciones(ind, p)
    valid = _validas(ind)
    sig_l = pd.concat(cl.values(), axis=1).all(axis=1) & valid
    if p.modo == "futuros":
        sig_s = pd.concat(cs.values(), axis=1).all(axis=1) & valid
    else:
        sig_s = pd.Series(False, index=ind.index)
    return sig_l, sig_s


# ==============================================================
#  MOTOR DE BACKTESTING
# ==============================================================

def backtest(df: pd.DataFrame, p: Params) -> dict:
    ind = calcular_indicadores(df, p)
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
    primer = ind["ma_l"].first_valid_index()
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
    m["Expectativa USD"] = wr * avg_w + (1 - wr) * avg_l
    m["Expectativa R"] = float(trades["R"].mean())
    m["Ganancia media USD"], m["Pérdida media USD"] = float(avg_w), float(avg_l)
    m["Payoff"] = avg_w / abs(avg_l) if avg_l < 0 else np.nan
    return m


def metricas_agrupadas(lista_trades: list) -> dict:
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

def evaluar_ultima(ticker: str, df: pd.DataFrame, p: Params, solo_cerradas: bool = True):
    delta = TF_POR_CODIGO.get(p.intervalo, TEMPORALIDADES["Diario"])["delta"]
    if solo_cerradas and len(df) > 1 and _vela_abierta(df.index[-1], delta):
        df = df.iloc[:-1]
    if len(df) < min_velas(p):
        return None
    ind = calcular_indicadores(df, p)
    cl, cs = condiciones(ind, p)
    u = ind.iloc[-1]
    if not bool(_validas(ind).iloc[-1]):
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
    n_ok = max(n_l, n_s) if p.modo == "futuros" else n_l
    rel = "rápida > lenta" if u["ma_r"] > u["ma_l"] else "rápida < lenta"
    return {
        "Ticker": ticker, "Precio": px, "Señal": senal,
        "Filtros OK": f"{n_ok}/{len(ok_l)}", "_n": n_ok,
        "Cruce": etiqueta_cruce(u), "Medias": rel,
        "MA rápida": float(u["ma_r"]), "MA lenta": float(u["ma_l"]),
        "ADX": float(u["adx"]), "+DI": float(u["pdi"]), "-DI": float(u["mdi"]),
        "CMF": None if pd.isna(u["cmf"]) else float(u["cmf"]),
        "Falta cumplir": ", ".join(fallan) if fallan else "—",
        # datos para cargar en el formulario de señales
        "ticker_yahoo": ticker, "categoria": categoria_de(ticker), "precio": px, "atr": atr,
        "temporalidad": p.intervalo,
        "sl_largo": px - p.sl_atr * atr, "tp_largo": px + p.tp_atr * atr,
        "sl_corto": px + p.sl_atr * atr, "tp_corto": px - p.tp_atr * atr,
        "notas": (f"Scanner MA+ADX+CMF ({p.intervalo}) · {p.ma_rapida_tipo}{p.ma_rapida} vs "
                  f"{p.ma_lenta_tipo}{p.ma_lenta}: {etiqueta_cruce(u)} · "
                  f"ADX {u['adx']:.0f} (+DI {u['pdi']:.0f}/-DI {u['mdi']:.0f}) · "
                  f"CMF {0 if pd.isna(u['cmf']) else u['cmf']:+.2f} · "
                  f"SL {p.sl_atr:g}×ATR / TP {p.tp_atr:g}×ATR (ATR {atr:,.4f})."),
    }


def _parse_tickers(txt: str) -> list:
    raw = [t.strip().upper() for t in txt.replace("\n", ",").replace(";", ",").split(",")]
    vistos = []
    for t in raw:
        if t and t not in vistos and len(t) <= 15:
            vistos.append(t)
    return vistos


# ==============================================================
#  PRESETS
# ==============================================================

PRESETS_FILE = Path("scanner_presets.json")

MODOS_LBL = ["Spot (solo largos)", "Futuros (largos y cortos)"]
PERIODOS_VALIDOS = {x for c in TEMPORALIDADES.values() for x in c["periodos"]}

# sufijo del widget -> tipo
_CAMPOS_PRESET = {
    "modo": str, "tf": str,
    "ma_r_tipo": str, "ma_r": int, "ma_l_tipo": str, "ma_l": int, "ventana": int,
    "adx": float, "cmf": float, "exvol": bool,
    "sl": float, "tp": float, "com": float, "slip": float,
    "cap": float, "riesgo": float, "apal": float, "maxbar": int,
    "scan_tk": str, "cerradas": bool, "bt_tk": str, "bt_per": str, "perfil": bool,
}


class PresetStoreJSON:
    """Guarda los presets en un JSON local (en Streamlit Cloud el disco es efímero:
    ahí conviene PresetStoreSupabase).
    Interfaz de cualquier store: listar() -> dict, guardar(nombre, datos), eliminar(nombre)."""

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
    datos = {}
    for suf, tipo in _CAMPOS_PRESET.items():
        v = st.session_state.get(f"{key}_{suf}")
        if v is not None:
            datos[suf] = tipo(v)
    return datos


def _aplicar_preset(st, key: str, datos: dict) -> None:
    """Vuelca un preset en los widgets. Los campos de presets viejos que ya no existen se ignoran."""
    datos = {"tf": "Diario", **datos}
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
            v = "Diario"
        if suf in ("ma_r_tipo", "ma_l_tipo") and v not in TIPOS_MA:
            continue
        if suf == "bt_per" and v not in PERIODOS_VALIDOS:
            continue
        st.session_state[f"{key}_{suf}"] = v


def _params_desde_preset(d: dict):
    """Arma (Params, cfg_temporalidad) desde un preset guardado."""
    tf = d.get("tf") if d.get("tf") in TEMPORALIDADES else "Diario"
    cfg = TEMPORALIDADES[tf]
    perf = perfil_para(cfg["iv"])

    def num(k, defecto):
        try:
            return float(d.get(k, defecto))
        except (TypeError, ValueError):
            return float(defecto)

    def tipo(k):
        v = str(d.get(k, "EMA")).upper()
        return v if v in TIPOS_MA else "EMA"

    modo = "futuros" if str(d.get("modo", "")).startswith("Futuros") else "spot"
    p = Params(
        ma_rapida=int(num("ma_r", 20)), ma_rapida_tipo=tipo("ma_r_tipo"),
        ma_lenta=int(num("ma_l", 50)), ma_lenta_tipo=tipo("ma_l_tipo"),
        cruce_ventana=max(1, int(num("ventana", 1))),
        adx_umbral=num("adx", perf["adx_umbral"]), cmf_min=num("cmf", 0.0),
        exigir_volumen=bool(d.get("exvol", True)),
        modo=modo, sl_atr=num("sl", perf["sl_atr"]), tp_atr=num("tp", perf["tp_atr"]),
        comision_pct=num("com", 0.10), slippage_pct=num("slip", 0.05),
        riesgo_pct=num("riesgo", 1.0),
        apalancamiento=num("apal", 1.0) if modo == "futuros" else 1.0,
        capital=num("cap", 10000.0), max_barras=int(num("maxbar", perf["max_barras"])),
        intervalo=cfg["iv"])
    return p, cfg


_COLS_SCAN = ["Ticker", "Señal", "Filtros OK", "Cruce", "Medias", "Precio", "MA rápida", "MA lenta",
              "ADX", "+DI", "-DI", "CMF", "Falta cumplir"]


def _cfg_cols_scan(st):
    nf = st.column_config.NumberColumn
    return {"Precio": nf(format="%.4f"), "MA rápida": nf(format="%.4f"), "MA lenta": nf(format="%.4f"),
            "ADX": nf(format="%.0f"), "+DI": nf(format="%.0f"), "-DI": nf(format="%.0f"),
            "CMF": nf(format="%+.2f")}


def _render_scan_presets(st, key: str, presets: dict, dl, on_cargar=None):
    """Escanea varios presets: cada uno con SUS parámetros, SU temporalidad y SUS tickers."""
    k_res, k_fall = f"{key}_multi_res", f"{key}_multi_fallidos"
    k_np, k_sig = f"{key}_multi_npresets", f"{key}_multi_sig"

    with st.container(border=True):
        st.markdown("**📚 Escanear presets guardados**")
        if not presets:
            st.caption("Guardá al menos un preset (💾 Presets) para escanearlo desde acá.")
            return

        nombres = sorted(presets.keys())
        k_ms = f"{key}_multi_sel"
        if k_ms not in st.session_state:
            st.session_state[k_ms] = list(nombres)
        else:
            st.session_state[k_ms] = [n for n in st.session_state[k_ms] if n in nombres]
        elegidos = st.multiselect("Presets a escanear", nombres, key=k_ms)

        firma = json.dumps({n: presets[n] for n in elegidos}, sort_keys=True,
                           ensure_ascii=False, default=str)
        if st.session_state.get(k_sig) != firma:
            for k in (k_res, k_fall, k_np):
                st.session_state.pop(k, None)

        resumen = []
        for n in elegidos:
            d = presets[n]
            p_n, _ = _params_desde_preset(d)
            tks = _parse_tickers(d.get("scan_tk", ""))
            resumen.append({
                "Preset": n,
                "Temporalidad": d.get("tf") if d.get("tf") in TEMPORALIDADES else "Diario",
                "Mercado": "Futuros" if p_n.modo == "futuros" else "Spot",
                "Medias": f"{p_n.ma_rapida_tipo}{p_n.ma_rapida} / {p_n.ma_lenta_tipo}{p_n.ma_lenta}",
                "Tickers del Scanner": ", ".join(tks) if tks else "— (vacío)",
            })
        if resumen:
            st.dataframe(pd.DataFrame(resumen), use_container_width=True, hide_index=True)

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
                f = evaluar_ultima(tk, df, p_n, solo) if df is not None else None
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
            st.warning("Sin datos suficientes: " + ", ".join(st.session_state[k_fall]))
        if not filas:
            st.info("No hubo resultados.")
            return

        n_sig = sum(1 for r in filas if r["Señal"] != "—")
        solo_sig = st.checkbox("Mostrar solo activos con señal completa", key=f"{key}_multi_solo")
        vis = [r for r in filas if r["Señal"] != "—"] if solo_sig else list(filas)
        st.caption(f"{n_sig} activo(s) con señal completa de {len(filas)} analizados en "
                   f"{st.session_state.get(k_np, '?')} preset(s).")
        if not vis:
            st.info("Ningún activo cumple todos los filtros en este momento.")
            return

        vis = sorted(vis, key=lambda r: (r["Señal"] == "—", -r["_n"]))
        cols = ["Preset", "TF"] + _COLS_SCAN
        st.dataframe(pd.DataFrame(vis)[cols], use_container_width=True, hide_index=True,
                     height=min(600, len(vis) * 36 + 45), column_config=_cfg_cols_scan(st))

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

def _render_historial(st, key: str, p: Params, dl):
    """Pestaña Historial: indicadores y cumplimiento de cada filtro vela a vela."""
    st.markdown("**📜 Historial del activo (para calibrar parámetros)**")
    st.caption("Elegí un activo, la temporalidad y cuántos días hacia atrás traer. Se marca, vela a vela, "
               "qué filtros se cumplieron con los parámetros cargados arriba.")
    c1, c2, c3 = st.columns([2, 2, 2])
    tk_txt = c1.text_input("Activo", "BTC-USD", key=f"{key}_hist_tk")
    tf_sel = c2.radio("Temporalidad", list(TEMPORALIDADES.keys()), horizontal=True,
                      key=f"{key}_hist_tf")
    dias_sel = int(c3.number_input("Días a traer", 30, 7300, 180, 30, key=f"{key}_hist_dias"))
    excl = st.checkbox("Excluir la vela en formación", True, key=f"{key}_hist_excl")
    es_fut = p.modo == "futuros"
    st.caption("🔁 Mercado **Futuros**: se evalúan largos y cortos a la vez." if es_fut else
               "📈 Mercado **Spot**: solo largos.")

    if st.button("▶ Traer historial", key=f"{key}_hist_run", type="primary"):
        tks = _parse_tickers(tk_txt)
        if not tks:
            st.warning("Escribí un ticker.")
        else:
            st.session_state[f"{key}_hist_args"] = (tks[0], tf_sel, dias_sel, excl)

    a = st.session_state.get(f"{key}_hist_args")
    if not a:
        return
    ticker, tf_h, dias, excl_h = a
    cfg_h = TEMPORALIDADES[tf_h]
    ph = replace(p, intervalo=cfg_h["iv"])
    warm = 600 if cfg_h["iv"] == "1d" else 1500

    with st.spinner(f"Descargando {ticker}..."):
        df = dl(ticker, f"{dias + warm}d", cfg_h["fuente"], cfg_h["resample"])
    if df is None or len(df) < min_velas(ph):
        st.warning(f"No hay datos suficientes de {ticker} en {tf_h}.")
        return
    if excl_h and len(df) > 1 and _vela_abierta(df.index[-1], cfg_h["delta"]):
        df = df.iloc[:-1]

    ind = calcular_indicadores(df, ph)
    cl, cs = condiciones(ind, ph)
    lados = {"L": ("Largos", cl)}
    if es_fut:
        lados["C"] = ("Cortos", cs)

    valid = _validas(ind).to_numpy()
    corte = ind.index[-1] - pd.Timedelta(days=dias)
    mask = (ind.index >= corte) & valid
    if not mask.any():
        st.warning("No hay velas con indicadores calculables en ese rango. Probá con más días.")
        return

    W = ind.loc[mask]
    Ms = {k: pd.DataFrame({f: v.loc[mask] for f, v in filt.items()}).astype(bool)
          for k, (_n, filt) in lados.items()}
    comp = {k: M.all(axis=1) for k, M in Ms.items()}

    st.caption(f"**{ticker}** · {tf_h} · {len(W)} velas entre {W.index[0].date()} y {W.index[-1].date()}.")
    if W["cmf"].isna().all():
        st.info("Este activo no informa volumen: el CMF queda vacío y ese filtro falla siempre "
                "salvo que desactives «Exigir volumen» en Parámetros.")

    # ── Resumen ──
    cols_k = st.columns(1 + 2 * len(lados))
    cols_k[0].metric("Velas analizadas", f"{len(W)}")
    j = 1
    for k, (nom, _f) in lados.items():
        pasa_k = Ms[k].mean() * 100
        cuello = pasa_k.idxmin()
        cols_k[j].metric(f"Señales {nom.lower()}", f"{int(comp[k].sum())}",
                         f"{comp[k].mean() * 100:.1f}% de las velas", delta_color="off")
        cols_k[j + 1].metric(f"Más restrictivo ({nom.lower()})", cuello,
                             f"lo cumple el {pasa_k[cuello]:.0f}%", delta_color="off")
        j += 2

    # ── Tabla vela a vela ──
    sen = pd.Series("—", index=W.index)
    sen[comp["L"]] = "🟢 LARGO"
    if "C" in comp:
        sen[comp["C"] & ~comp["L"]] = "🔴 CORTO"
        sen[comp["C"] & comp["L"]] = "⚠️ AMBAS"

    t = pd.DataFrame(index=W.index)
    t["Fecha"] = W.index.strftime("%Y-%m-%d")
    t["Close"] = W["Close"]
    t["ATR"] = W["atr"]
    t["MA rápida"], t["MA lenta"] = W["ma_r"], W["ma_l"]
    t["Cruce"] = [etiqueta_cruce(r) for _, r in W.iterrows()]
    t["ADX"], t["+DI"], t["-DI"] = W["adx"], W["pdi"], W["mdi"]
    t["CMF"] = W["cmf"]
    t["Señal"] = sen.to_numpy()
    for k, (nom, _f) in lados.items():
        M = Ms[k]
        t[f"OK {nom.lower()}"] = M.sum(axis=1).astype(int).astype(str) + f"/{M.shape[1]}"
        t[f"Falta ({nom.lower()})"] = M.apply(
            lambda r: ", ".join([c for c, v in r.items() if not v]) or "—", axis=1)
    for k, (nom, _f) in lados.items():
        for c in Ms[k].columns:
            t[f"{k} · {c}"] = np.where(Ms[k][c], "✔", "✘")
    t = t.iloc[::-1].reset_index(drop=True)

    fmt = {"Close": "%.4f", "ATR": "%.4f", "MA rápida": "%.4f", "MA lenta": "%.4f",
           "ADX": "%.1f", "+DI": "%.1f", "-DI": "%.1f", "CMF": "%+.2f"}
    cfg_cols = {c: st.column_config.NumberColumn(format=f) for c, f in fmt.items() if c in t.columns}
    st.markdown("**Vela a vela** (más reciente primero · «L ·» = filtros de largos, «C ·» = de cortos)")
    st.dataframe(t, use_container_width=True, hide_index=True,
                 height=min(600, len(t) * 36 + 45), column_config=cfg_cols)
    st.download_button("⬇️ Descargar CSV", t.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"historial_{ticker}_{cfg_h['iv']}_{dias}d.csv",
                       mime="text/csv", key=f"{key}_hist_csv")

    # ── Distribución de cada indicador vs. el parámetro actual ──
    umb_l = {"ADX": f"bloquea si > {ph.adx_umbral:g} y domina -DI", "CMF": f"> {ph.cmf_min:g}"}
    umb_c = {"ADX": f"bloquea si > {ph.adx_umbral:g} y domina +DI", "CMF": f"< {-ph.cmf_min:g}"}
    filas = []
    for nom, c in [("ADX", "adx"), ("+DI", "pdi"), ("-DI", "mdi"), ("CMF", "cmf")]:
        sr = W[c].dropna()
        if sr.empty:
            continue
        fila = {"Indicador": nom, "Mín": sr.min(), "P25": sr.quantile(.25), "Mediana": sr.median(),
                "P75": sr.quantile(.75), "P90": sr.quantile(.90), "Máx": sr.max(),
                "Último": sr.iloc[-1], "Parámetro largos": umb_l.get(nom, "—")}
        if es_fut:
            fila["Parámetro cortos"] = umb_c.get(nom, "—")
        filas.append(fila)
    st.markdown("**Distribución de cada indicador vs. tus parámetros actuales**")
    st.dataframe(pd.DataFrame(filas).round(3), use_container_width=True, hide_index=True)

    n_up, n_dn = int(W["cruce_up"].sum()), int(W["cruce_dn"].sum())
    st.caption(f"Cruces en el período — {ph.ma_rapida_tipo}{ph.ma_rapida} / "
               f"{ph.ma_lenta_tipo}{ph.ma_lenta}: {n_up} alcistas · {n_dn} bajistas.")

    # ── Cumplimiento de cada filtro ──
    filas_f = []
    for k, (nom, _f) in lados.items():
        M = Ms[k]
        n_f = M.shape[1]
        n_ok = M.sum(axis=1)
        for c in M.columns:
            filas_f.append({"Lado": nom, "Filtro": c,
                            "% de velas que lo cumple": float(M[c].mean() * 100),
                            "% de velas donde es el ÚNICO que falla":
                                float(((n_ok == n_f - 1) & ~M[c]).mean() * 100)})
    df_f = pd.DataFrame(filas_f).sort_values(["Lado", "% de velas que lo cumple"]).round(1)
    st.markdown("**Cumplimiento de cada filtro**")
    st.dataframe(df_f, use_container_width=True, hide_index=True)
    st.caption("Aflojar demasiado los parámetros para ver más señales puede sobreajustar al período. "
               "No es asesoramiento financiero.")


def render_scanner_multifactor(on_cargar=None, key: str = "mf", store=None):
    """on_cargar(fila, lado) se ejecuta como callback de botón ('LARGO' / 'CORTO').
    store: objeto con listar()/guardar(nombre, datos)/eliminar(nombre)."""
    import streamlit as st
    import plotly.graph_objects as go

    store = store or PresetStoreJSON()
    dl = st.cache_data(ttl=900, show_spinner=False)(descargar_ohlcv)

    st.markdown("#### 📊 Scanner Medias Móviles + ADX + CMF · Backtest")
    st.caption("Señal por cruce de dos medias móviles, filtrada por tendencia (ADX/DI) y convicción (CMF). "
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
            p2.button("📂 Cargar", key=f"{key}_pre_load", on_click=_cb_cargar, use_container_width=True)
            p2.button("🗑️ Eliminar", key=f"{key}_pre_del", on_click=_cb_eliminar, use_container_width=True)
        else:
            st.caption("Todavía no hay presets guardados.")
        n1, n2 = st.columns([3, 1])
        n1.text_input("Nombre para guardar (si ya existe, lo sobrescribe)", key=k_nom,
                      placeholder="Ej: Cripto futuros")
        n2.write("")
        n2.button("💾 Guardar", key=f"{key}_pre_save", on_click=_cb_guardar, use_container_width=True)
        st.caption("Guarda mercado, temporalidad, medias, parámetros y tickers del Scanner y del Backtest. "
                   "Los presets viejos se cargan igual: los campos que ya no existen se ignoran.")
        msg = st.session_state.pop(k_msg, None)
        if msg:
            (st.success if msg[0] == "ok" else st.warning)(msg[1])

    # ─────────────── PERFIL AUTOMÁTICO ───────────────
    def _aplicar_perfil_actual():
        tf = st.session_state.get(f"{key}_tf", "Diario")
        perf = perfil_para(TEMPORALIDADES[tf]["iv"])
        for suf, campo in _PERFIL_A_WIDGET.items():
            st.session_state[f"{key}_{suf}"] = int(perf[campo]) if suf == "maxbar" else float(perf[campo])

    def _cb_perfil():
        if st.session_state.get(f"{key}_perfil", True):
            _aplicar_perfil_actual()

    # ─────────────── PARÁMETROS ───────────────
    with st.expander("⚙️ Parámetros", expanded=False):
        modo_lbl = st.radio("Mercado", MODOS_LBL, index=1, horizontal=True, key=f"{key}_modo")
        tf_lbl = st.radio("Temporalidad", list(TEMPORALIDADES.keys()), index=0, horizontal=True,
                          key=f"{key}_tf", on_change=_cb_perfil,
                          help="Se aplica al Scanner y al Backtest.")
        cfg = TEMPORALIDADES[tf_lbl]
        st.caption("⏱️ " + cfg["nota"])

        st.markdown("**Medias móviles** — rápida cruza por encima de la lenta → LARGO · "
                    "rápida cruza por debajo → CORTO")
        m1, m2, m3, m4, m5 = st.columns(5)
        ma_r_tipo = m1.selectbox("Rápida: tipo", TIPOS_MA, index=1, key=f"{key}_ma_r_tipo")
        ma_r = int(m2.number_input("Rápida: período", 2, 500, 20, 1, key=f"{key}_ma_r"))
        ma_l_tipo = m3.selectbox("Lenta: tipo", TIPOS_MA, index=1, key=f"{key}_ma_l_tipo")
        ma_l = int(m4.number_input("Lenta: período", 2, 1000, 50, 1, key=f"{key}_ma_l"))
        ventana = int(m5.number_input("Velas de validez del cruce", 1, 50, 1, 1, key=f"{key}_ventana",
                                      help="1 = el cruce debe ocurrir en la última vela. Con N > 1 la señal "
                                           "sigue vigente hasta N velas después del cruce."))
        if ma_r >= ma_l:
            st.warning("La media rápida debería tener un período menor que la lenta.")

        c1, c2, c3 = st.columns(3)
        adx_u = c1.number_input("ADX umbral", 5.0, 60.0, 18.0, 1.0, key=f"{key}_adx",
                                help="Bloquea largos si ADX > umbral y domina -DI (espejo en cortos).")
        cmf_min = c2.number_input("CMF mínimo", 0.0, 1.0, 0.0, 0.01, format="%.2f", key=f"{key}_cmf",
                                  help="Largos: CMF > mínimo · Cortos: CMF < -mínimo.")
        exig_vol = c3.checkbox("Exigir volumen", True, key=f"{key}_exvol",
                               help="Si lo desactivás, activos sin volumen (forex) saltan el filtro CMF.")
        d1, d2, d3, d4 = st.columns(4)
        sl_atr = d1.number_input("SL (× ATR)", 0.5, 10.0, 1.5, 0.1, format="%.2f", key=f"{key}_sl")
        tp_atr = d2.number_input("TP (× ATR)", 0.5, 20.0, 2.0, 0.1, format="%.2f", key=f"{key}_tp")
        comision = d3.number_input("Comisión % por lado", 0.0, 2.0, 0.10, 0.01, format="%.3f", key=f"{key}_com")
        slippage = d4.number_input("Slippage % por fill", 0.0, 2.0, 0.05, 0.01, format="%.3f", key=f"{key}_slip")
        e1, e2, e3, e4 = st.columns(4)
        capital = e1.number_input("Capital (USD)", 100.0, 1e9, 10000.0, 500.0, key=f"{key}_cap")
        riesgo = e2.number_input("Riesgo % por operación", 0.1, 10.0, 1.0, 0.25, key=f"{key}_riesgo")
        apal = e3.number_input("Apalancamiento máx. (x)", 1.0, 125.0, 1.0, 1.0, key=f"{key}_apal")
        max_bar = e4.number_input("Máx. velas en operación", 0, 500, 70, 5, key=f"{key}_maxbar",
                                  help="En velas de la temporalidad elegida. 0 = sin salida por tiempo.")
        st.checkbox("Auto-ajustar por temporalidad", True, key=f"{key}_perfil", on_change=_cb_perfil,
                    help="Al cambiar de temporalidad carga el perfil de esa temporalidad "
                         "(SL, TP, ADX y máx. velas; se editan en PERFILES dentro del código).")

    modo = "futuros" if modo_lbl.startswith("Futuros") else "spot"
    p = Params(ma_rapida=ma_r, ma_rapida_tipo=ma_r_tipo, ma_lenta=ma_l, ma_lenta_tipo=ma_l_tipo,
               cruce_ventana=ventana, adx_umbral=adx_u, cmf_min=cmf_min, exigir_volumen=exig_vol,
               modo=modo, sl_atr=sl_atr, tp_atr=tp_atr, comision_pct=comision,
               slippage_pct=slippage, riesgo_pct=riesgo,
               apalancamiento=apal if modo == "futuros" else 1.0,
               capital=capital, max_barras=int(max_bar), intervalo=cfg["iv"])

    tab_scan, tab_bt, tab_hist = st.tabs(["🔎 Scanner", "🧪 Backtest", "📜 Historial"])

    # ─────────────── SCANNER ───────────────
    with tab_scan:
        _render_scan_presets(st, key, presets, dl, on_cargar)
        st.markdown("**🔎 Escaneo con los parámetros actuales (los de la pantalla)**")
        txt = st.text_area("Tickers (separados por coma)", key=f"{key}_scan_tk", height=80,
                           value="NVDA, AAPL, MSFT, TSLA, BTC-USD, ETH-USD, SOL-USD, GC=F, CL=F")
        solo_cerr = st.checkbox("Usar solo velas cerradas", True, key=f"{key}_cerradas",
                                help="Recomendado: durante la rueda el volumen de hoy es parcial y "
                                     "distorsiona el CMF.")
        firma_man = repr((txt, solo_cerr, p))
        if st.button("▶ Escanear", key=f"{key}_scan_run", type="primary"):
            tks = _parse_tickers(txt)[:60]
            st.session_state[f"{key}_scan_sig"] = firma_man

            def _uno(tk):
                df = dl(tk, cfg["scan"], cfg["fuente"], cfg["resample"])
                return evaluar_ultima(tk, df, p, solo_cerr) if df is not None else None

            with st.spinner(f"Escaneando {len(tks)} activos..."):
                with ThreadPoolExecutor(max_workers=8) as ex:
                    res = list(ex.map(_uno, tks))
            st.session_state[f"{key}_scan_res"] = [r for r in res if r]
            st.session_state[f"{key}_scan_fallidos"] = [t for t, r in zip(tks, res) if r is None]
            st.session_state[f"{key}_scan_tf"] = tf_lbl

        if st.session_state.get(f"{key}_scan_sig") != firma_man:
            for sfx in ("scan_res", "scan_fallidos", "scan_tf"):
                st.session_state.pop(f"{key}_{sfx}", None)

        filas = st.session_state.get(f"{key}_scan_res")
        if filas is not None:
            st.caption("⏱️ Temporalidad de este escaneo: **"
                       + st.session_state.get(f"{key}_scan_tf", tf_lbl) + "**")
            if st.session_state.get(f"{key}_scan_fallidos"):
                st.warning("Sin datos suficientes (velas mínimas): "
                           + ", ".join(st.session_state[f"{key}_scan_fallidos"]))
            if not filas:
                st.info("No hubo resultados.")
            else:
                filas = sorted(filas, key=lambda r: (r["Señal"] == "—", -r["_n"]))
                st.dataframe(pd.DataFrame(filas)[_COLS_SCAN], use_container_width=True, hide_index=True,
                             height=min(600, len(filas) * 36 + 45), column_config=_cfg_cols_scan(st))
                n_sig = sum(1 for r in filas if r["Señal"] != "—")
                st.caption(f"{n_sig} activo(s) con señal completa de {len(filas)} analizados. "
                           "Un cruce es un evento puntual: lo normal es que pocos activos lo tengan justo ahora.")

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

    # ─────────────── HISTORIAL ───────────────
    # (va ANTES del Backtest: ese bloque termina con 'return')
    with tab_hist:
        _render_historial(st, key, p, dl)

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
                    if df is None or len(df) < min_velas(p):
                        sin_datos.append(tk)
                        continue
                    salida[tk] = backtest(df, p)
            st.session_state[f"{key}_bt_res"] = salida
            st.session_state[f"{key}_bt_sin"] = sin_datos
            st.session_state[f"{key}_bt_cap"] = p.capital
            st.session_state[f"{key}_bt_tf"] = tf_lbl

        res = st.session_state.get(f"{key}_bt_res")
        if res is None:
            return
        if st.session_state.get(f"{key}_bt_sin"):
            st.warning("Sin datos suficientes: " + ", ".join(st.session_state[f"{key}_bt_sin"]))
        if not res:
            return

        tf_res = st.session_state.get(f"{key}_bt_tf", tf_lbl)
        st.caption(f"⏱️ Temporalidad de estos resultados: **{tf_res}**"
                   + ("" if tf_res == tf_lbl else
                      " · cambiaste la temporalidad: volvé a correr el backtest."))

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
        st.dataframe(pd.DataFrame(filas_r), use_container_width=True, hide_index=True, column_config={
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
            st.info("Con estos filtros no hubo operaciones en el período. Probá con medias más cortas, "
                    "más velas de validez del cruce o un umbral de ADX más alto.")
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
    ap = argparse.ArgumentParser(description="Scanner MA + ADX + CMF con backtest")
    ap.add_argument("tickers", nargs="+")
    ap.add_argument("--tf", choices=list(TF_POR_CODIGO.keys()), default="1d", help="temporalidad: 1d, 1wk")
    ap.add_argument("--periodo", default=None, help="histórico (ej. 5y, 10y)")
    ap.add_argument("--modo", choices=["spot", "futuros"], default="spot")
    ap.add_argument("--ma-rapida", type=int, default=20)
    ap.add_argument("--tipo-rapida", choices=TIPOS_MA, default="EMA")
    ap.add_argument("--ma-lenta", type=int, default=50)
    ap.add_argument("--tipo-lenta", choices=TIPOS_MA, default="EMA")
    ap.add_argument("--ventana-cruce", type=int, default=1, help="velas de validez del cruce")
    ap.add_argument("--sl-atr", type=float, default=None)
    ap.add_argument("--tp-atr", type=float, default=None)
    ap.add_argument("--adx", type=float, default=None)
    ap.add_argument("--cmf", type=float, default=0.0, help="CMF mínimo")
    ap.add_argument("--max-barras", type=int, default=None)
    ap.add_argument("--comision", type=float, default=0.10, help="%% por lado")
    ap.add_argument("--slippage", type=float, default=0.05, help="%% por fill")
    ap.add_argument("--riesgo", type=float, default=1.0, help="%% del equity por operación")
    ap.add_argument("--apalancamiento", type=float, default=1.0)
    ap.add_argument("--capital", type=float, default=10000.0)
    a = ap.parse_args()

    perf = perfil_para(a.tf)
    pick = lambda v, k: perf[k] if v is None else v

    p = Params(ma_rapida=a.ma_rapida, ma_rapida_tipo=a.tipo_rapida,
               ma_lenta=a.ma_lenta, ma_lenta_tipo=a.tipo_lenta,
               cruce_ventana=max(1, a.ventana_cruce),
               modo=a.modo, sl_atr=pick(a.sl_atr, "sl_atr"), tp_atr=pick(a.tp_atr, "tp_atr"),
               adx_umbral=pick(a.adx, "adx_umbral"), cmf_min=a.cmf,
               comision_pct=a.comision, slippage_pct=a.slippage, riesgo_pct=a.riesgo,
               apalancamiento=a.apalancamiento if a.modo == "futuros" else 1.0,
               capital=a.capital, max_barras=int(pick(a.max_barras, "max_barras")),
               intervalo=a.tf)
    cfg = TF_POR_CODIGO[a.tf]
    periodo = a.periodo or cfg["defecto"]

    print(f"\n--- SCANNER (última vela cerrada) · {a.tf} · "
          f"{p.ma_rapida_tipo}{p.ma_rapida}/{p.ma_lenta_tipo}{p.ma_lenta} · "
          f"SL {p.sl_atr:g} / TP {p.tp_atr:g} × ATR ---")
    todos = []
    for tk in a.tickers:
        df = descargar_ohlcv(tk, periodo, cfg["fuente"], cfg["resample"])
        if df is None or len(df) < min_velas(p):
            print(f"  {tk}: sin datos suficientes")
            continue
        fila = evaluar_ultima(tk, df, p, True)
        if fila:
            print(f"  {tk:<10} {fila['Señal']:<10} filtros {fila['Filtros OK']:<5} "
                  f"{fila['Cruce']:<16} falta: {fila['Falta cumplir']}")
        r = backtest(df, p)
        imprimir_metricas(tk, r["metricas"])
        todos.append(r["trades"])
    if len(todos) > 1:
        imprimir_metricas("TOTAL (operaciones juntas)", metricas_agrupadas(todos))


if __name__ == "__main__":
    main()
