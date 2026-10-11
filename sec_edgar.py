# ==============================================================
#  sec_edgar.py — Datos fundamentales desde la SEC (EDGAR / XBRL)
#
#  Se usa como reemplazo "drop-in" de yf.Ticker: expone .info,
#  .financials, .balance_sheet, .cashflow y .history() con los
#  mismos nombres de filas/claves que usa Yahoo, así el resto de
#  la app (señales, métricas extra, histórico) no cambia.
#
#  Cubre empresas que presentan 10-K / 10-Q en USD (us-gaap).
#  ADRs y extranjeras (20-F / IFRS) devuelven None -> la app cae
#  a Yahoo como respaldo.
# ==============================================================
import threading
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests
import streamlit as st

# ⚠️ OBLIGATORIO: la SEC bloquea pedidos sin identificación real.
# Poné tu nombre/empresa y un mail tuyo.
SEC_USER_AGENT = "Capital+ TuNombre tuemail@dominio.com"
_HEADERS = {"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}

# ── Límite de la SEC: 10 pedidos/seg. Acá ~8/seg compartido entre hilos ──
_lock = threading.Lock()
_ultimo_req = [0.0]


def _get_json(url, intentos=3):
    for i in range(intentos):
        with _lock:
            espera = 0.12 - (time.time() - _ultimo_req[0])
            if espera > 0:
                time.sleep(espera)
            _ultimo_req[0] = time.time()
        try:
            r = requests.get(url, headers=_HEADERS, timeout=25)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
            time.sleep(1.5 * (i + 1))
        except Exception:
            time.sleep(1.0 * (i + 1))
    return None


@st.cache_data(ttl=86400, show_spinner=False)
def _mapa_cik():
    j = _get_json("https://www.sec.gov/files/company_tickers.json")
    if not j:
        raise RuntimeError("No se pudo bajar company_tickers.json")  # no se cachea
    return {str(v["ticker"]).upper(): str(v["cik_str"]).zfill(10) for v in j.values()}


def _cik_de(ticker):
    m = _mapa_cik()
    t = ticker.upper()
    return m.get(t) or m.get(t.replace(".", "-"))


# ── Etiquetas XBRL por concepto: (unidad, [tags por prioridad]) ──
_TAGS = {
    # Flujos (estado de resultados / flujo de caja)
    'rev':    ('USD', ['Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax',
                       'RevenueFromContractWithCustomerIncludingAssessedTax', 'SalesRevenueNet',
                       'SalesRevenueGoodsNet', 'RevenuesNetOfInterestExpense']),
    'cogs':   ('USD', ['CostOfRevenue', 'CostOfGoodsAndServicesSold', 'CostOfGoodsSold']),
    'gp':     ('USD', ['GrossProfit']),
    'opinc':  ('USD', ['OperatingIncomeLoss']),
    'ni':     ('USD', ['NetIncomeLoss', 'NetIncomeLossAvailableToCommonStockholdersBasic', 'ProfitLoss']),
    'pretax': ('USD', ['IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest',
                       'IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments']),
    'tax':    ('USD', ['IncomeTaxExpenseBenefit']),
    'int':    ('USD', ['InterestExpense', 'InterestExpenseDebt', 'InterestAndDebtExpense',
                       'InterestExpenseNonoperating']),
    'da':     ('USD', ['DepreciationDepletionAndAmortization', 'DepreciationAndAmortization',
                       'DepreciationAmortizationAndAccretionNet', 'Depreciation']),
    'eps':    ('USD/shares', ['EarningsPerShareDiluted', 'EarningsPerShareBasicAndDiluted',
                              'EarningsPerShareBasic']),
    'sh_dil': ('shares', ['WeightedAverageNumberOfDilutedSharesOutstanding',
                          'WeightedAverageNumberOfSharesOutstandingBasic']),
    'ocf':    ('USD', ['NetCashProvidedByUsedInOperatingActivities',
                       'NetCashProvidedByUsedInOperatingActivitiesContinuingOperations']),
    'capex':  ('USD', ['PaymentsToAcquirePropertyPlantAndEquipment', 'PaymentsToAcquireProductiveAssets',
                       'PaymentsForCapitalImprovements']),
    'dps':    ('USD/shares', ['CommonStockDividendsPerShareDeclared', 'CommonStockDividendsPerShareCashPaid']),
    'div':    ('USD', ['PaymentsOfDividendsCommonStock', 'PaymentsOfDividends', 'PaymentsOfOrdinaryDividends']),
    # Instantes (balance)
    'assets': ('USD', ['Assets']),
    'ca':     ('USD', ['AssetsCurrent']),
    'cl':     ('USD', ['LiabilitiesCurrent']),
    'equity': ('USD', ['StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest']),
    'cash':   ('USD', ['CashAndCashEquivalentsAtCarryingValue',
                       'CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents', 'Cash']),
    'sti':    ('USD', ['ShortTermInvestments', 'MarketableSecuritiesCurrent',
                       'AvailableForSaleSecuritiesDebtSecuritiesCurrent']),
    'ltd':    ('USD', ['LongTermDebt']),
    'ltd_nc': ('USD', ['LongTermDebtNoncurrent', 'LongTermDebtAndCapitalLeaseObligations',
                       'ConvertibleNotesPayableNoncurrent', 'LongTermNotesPayable', 'SeniorNotes']),
    'ltd_c':  ('USD', ['LongTermDebtCurrent']),
    'dc':     ('USD', ['DebtCurrent']),
    'stb1':   ('USD', ['ShortTermBorrowings']),
    'stb2':   ('USD', ['CommercialPaper']),
    'fl_nc':  ('USD', ['FinanceLeaseLiabilityNoncurrent']),
    'fl_c':   ('USD', ['FinanceLeaseLiabilityCurrent']),
}


def _reducir(j, anios):
    """Del JSON gigante de la SEC nos quedamos solo con lo necesario (liviano para el caché)."""
    facts = j.get('facts') or {}
    us = facts.get('us-gaap')
    if not us:
        return {}
    corte = date.today() - timedelta(days=int(365 * anios) + 120)
    out = {'nombre': j.get('entityName')}
    for nombre, (unidad, tags) in _TAGS.items():
        cands = []
        for prio, tag in enumerate(tags):
            lst = ((us.get(tag) or {}).get('units') or {}).get(unidad)
            if not lst:
                continue
            ds = {}
            for x in lst:
                try:
                    e = date.fromisoformat(x['end'])
                    if e < corte:
                        continue
                    s = date.fromisoformat(x['start']) if x.get('start') else None
                    f = x.get('filed') or ''
                    k = (s, e)
                    if k not in ds or f >= ds[k]['f']:      # se queda con lo último presentado
                        ds[k] = {'s': s, 'e': e, 'v': float(x['val']), 'f': f}
                except Exception:
                    continue
            if ds:
                ents = list(ds.values())
                cands.append((max(z['e'] for z in ents), -prio, ents))
        if cands:
            # el tag con datos más recientes; si empatan, el de mayor prioridad
            out[nombre] = max(cands, key=lambda c: (c[0], c[1]))[2]
    try:   # acciones en circulación (tapa del 10-K/10-Q), suma todas las clases
        dei = (((facts.get('dei') or {}).get('EntityCommonStockSharesOutstanding') or {})
               .get('units') or {}).get('shares')
        if dei:
            ult = max(x['end'] for x in dei)
            grupo = [x for x in dei if x['end'] == ult]
            accn = max(grupo, key=lambda z: z.get('filed', ''))['accn']
            total = sum(float(x['val']) for x in grupo if x.get('accn') == accn)
            out['shares_dei'] = (total, date.fromisoformat(ult))
    except Exception:
        pass
    return out


@st.cache_data(ttl=6 * 3600, show_spinner=False, max_entries=400)
def _datos_sec(ticker, anios=4):
    cik = _cik_de(ticker)
    if not cik:
        return {}                       # no figura en la SEC
    j = _get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    if j is None:
        raise RuntimeError("SEC sin respuesta")   # error transitorio: no se cachea
    return _reducir(j, anios)


# ── Helpers de series ──────────────────────────────────────────
def _dur(x):
    return (x['e'] - x['s']).days


def _div(a, b):
    return a / b if (a is not None and b not in (None, 0)) else None


def _resumen(ents):
    """Último año fiscal, TTM (último FY + YTD actual − YTD año anterior) y crecimiento."""
    if not ents:
        return None
    L = [x for x in ents if x['s'] is not None]
    an = sorted([x for x in L if 340 <= _dur(x) <= 390], key=lambda z: z['e'])
    if not an:
        return None
    fy = an[-1]
    fy_prev = an[-2] if len(an) > 1 and 300 <= (fy['e'] - an[-2]['e']).days <= 430 else None
    ttm, fin, cur, prev = fy['v'], fy['e'], None, None
    cands = [x for x in L if x['e'] > fy['e'] and 20 <= _dur(x) <= 300
             and abs((x['s'] - fy['e']).days) <= 6]
    if cands:
        c = max(cands, key=lambda z: z['e'])
        pr = [x for x in L if abs((c['e'] - x['e']).days - 365) <= 10
              and abs((x['s'] - fy['s']).days) <= 7 and _dur(x) < 300]
        if pr:
            cur = c
            prev = min(pr, key=lambda z: abs((c['e'] - z['e']).days - 365))
            ttm = fy['v'] + cur['v'] - prev['v']
            fin = cur['e']
    crec = None
    if cur and prev and prev['v'] > 0:
        crec = cur['v'] / prev['v'] - 1
    elif fy_prev and fy_prev['v'] > 0:
        crec = fy['v'] / fy_prev['v'] - 1
    return {'ttm': ttm, 'fy': fy['v'], 'fin': fin, 'fy_end': fy['e'], 'crec': crec, 'anuales': an,
            'cur_v': cur['v'] if cur else None, 'prev_v': prev['v'] if prev else None}


def _inst(ents):
    """Último valor de balance (sin fecha de inicio) -> (valor, fecha)."""
    L = [x for x in (ents or []) if x['s'] is None]
    if not L:
        return None
    x = max(L, key=lambda z: (z['e'], z['f']))
    return x['v'], x['e']


def _inst_en(ents, fecha, tol=10):
    best = None
    for x in ents or []:
        if x['s'] is None and abs((x['e'] - fecha).days) <= tol:
            if best is None or x['f'] >= best['f']:
                best = x
    return best['v'] if best else None


def _anual_en(r, fecha, tol=10):
    for x in (r['anuales'] if r else []):
        if abs((x['e'] - fecha).days) <= tol:
            return x['v']
    return None


def _ult_dur(ents):
    L = [x for x in (ents or []) if x['s'] is not None]
    if not L:
        return None
    return max(L, key=lambda z: (z['e'], -_dur(z)))['v']


def _beta(c, spy):
    """Beta con retornos SEMANALES (más estable que diarios, evita desfasajes)."""
    try:
        if c is None or spy is None:
            return None
        j = pd.concat([c, spy], axis=1, join='inner').dropna()
        j = j.resample('W-FRI').last().pct_change().dropna()
        if len(j) < 50:
            return None
        cov = np.cov(j.iloc[:, 0], j.iloc[:, 1])
        return float(cov[0, 1] / cov[1, 1])
    except Exception:
        return None


# ── Datos que la SEC no tiene: se piden a Yahoo (1 sola llamada por ticker, cacheada) ──
_ylock = threading.Lock()
_yultimo = [0.0]


@st.cache_data(ttl=6 * 3600, show_spinner=False, max_entries=600)
def _yahoo_extra(ticker):
    with _ylock:                                   # separa los pedidos para no saturar a Yahoo
        espera = 0.4 - (time.time() - _yultimo[0])
        if espera > 0:
            time.sleep(espera)
        _yultimo[0] = time.time()
    import yfinance as yf
    info = yf.Ticker(ticker).info or {}
    out = {
        'pegRatio': info.get('pegRatio') if info.get('pegRatio') is not None else info.get('trailingPegRatio'),
        'beta': info.get('beta'),
        'trailingEps': info.get('trailingEps'),
        'earningsQuarterlyGrowth': info.get('earningsQuarterlyGrowth'),
        'recommendationKey': info.get('recommendationKey'),
        'targetMeanPrice': info.get('targetMeanPrice'),
    }
    if all(v is None for v in out.values()):
        raise RuntimeError("Yahoo vacío")           # no se cachea el fallo
    return out


# ==============================================================
#  Adaptador: se comporta como yf.Ticker
# ==============================================================
class SecTicker:
    es_sec = True

    def __init__(self, ticker, d, close=None, close_spy=None, precio=None,
                 ttm_first=True, max_cols=6, usar_yahoo=True):
        self.ticker = ticker
        self._usar_yahoo = usar_yahoo
        self._d = d
        self._close = close.dropna() if close is not None else None
        if precio is None and self._close is not None and len(self._close):
            precio = float(self._close.iloc[-1])
        self._precio = precio
        self._beta = _beta(self._close, close_spy.dropna() if close_spy is not None else None)
        self._ttm_first = ttm_first
        self._max_cols = max_cols
        self._cache = {}
        a = _inst(d.get('assets')) or _inst(d.get('equity'))
        self._ref = a[1] if a else None

    # ---------- utilidades internas ----------
    def _R(self, n):
        if n not in self._cache:
            self._cache[n] = _resumen(self._d.get(n))
        return self._cache[n]

    def _I(self, n, tol=200):
        r = _inst(self._d.get(n))
        if r is None:
            return None
        if self._ref is not None and (self._ref - r[1]).days > tol:
            return None
        return r[0]

    def valido(self):
        base = self._R('ni') or self._R('rev')
        if not base or self._ref is None:
            return False
        if (date.today() - base['fin']).days > 600:
            return False
        return self._I('equity') is not None or self._I('assets') is not None

    def _acc(self, modo, fecha):
        """Devuelve (F, I): funciones para leer flujos e instantes de una columna."""
        if modo == 'ttm':
            def F(n):
                r = self._R(n)
                if r is None:
                    return None
                return r['cur_v'] if n == 'sh_dil' else r['ttm']

            def I(n):
                return self._I(n)
        else:
            def F(n):
                return _anual_en(self._R(n), fecha)

            def I(n):
                return _inst_en(self._d.get(n), fecha)
        return F, I

    @staticmethod
    def _deuda(I):
        ltd = I('ltd')
        if ltd is None:
            ltd = I('ltd_nc')
            cur = I('ltd_c') if I('ltd_c') is not None else I('dc')
            if cur is not None:
                ltd = (ltd or 0.0) + cur
        extra = [I('stb1'), I('stb2'), I('fl_nc'), I('fl_c')]
        if I('equity') is None and I('assets') is None:
            return None                      # no hay balance para esa fecha
        return (ltd or 0.0) + sum(x for x in extra if x is not None)

    def _fila_income(self, F):
        rev, op, da, gp = F('rev'), F('opinc'), F('da'), F('gp')
        if gp is None and rev is not None and F('cogs') is not None:
            gp = rev - F('cogs')
        sh = F('sh_dil')
        return {
            'Total Revenue': rev, 'Gross Profit': gp, 'Operating Income': op, 'EBIT': op,
            'EBITDA': (op + da) if (op is not None and da is not None) else None,
            'Net Income': F('ni'), 'Pretax Income': F('pretax'), 'Tax Provision': F('tax'),
            'Interest Expense': F('int'), 'Basic EPS': F('eps'), 'Diluted EPS': F('eps'),
            'Reconciled Depreciation': da,
            'Basic Average Shares': sh, 'Diluted Average Shares': sh,
        }

    def _fila_balance(self, I):
        cash, sti = I('cash'), I('sti')
        total = ((cash or 0.0) + (sti or 0.0)) if (cash is not None or sti is not None) else None
        eq = I('equity')
        return {
            'Total Debt': self._deuda(I), 'Cash': total, 'Cash And Cash Equivalents': cash,
            'Cash Cash Equivalents And Short Term Investments': total,
            'Stockholders Equity': eq, 'Common Stock Equity': eq,
            'Total Assets': I('assets'), 'Current Assets': I('ca'), 'Current Liabilities': I('cl'),
        }

    @staticmethod
    def _fila_cash(F):
        ocf, cap, div = F('ocf'), F('capex'), F('div')
        capex = -abs(cap) if cap is not None else None
        return {
            'Operating Cash Flow': ocf, 'Capital Expenditure': capex,
            'Free Cash Flow': (ocf + (capex or 0.0)) if ocf is not None else None,
            'Cash Dividends Paid': -abs(div) if div is not None else None,
            'Depreciation And Amortization': F('da'),
        }

    def _armar(self, tipo):
        base = self._R('ni') or self._R('rev')
        if not base:
            return pd.DataFrame()
        fy = [x['e'] for x in base['anuales']][-self._max_cols:]
        cols = [('fy', f) for f in fy]
        con_ttm = self._ttm_first and base['fin'] > base['fy_end']
        if con_ttm:
            cols.append(('ttm', base['fin']))
        datos = {}
        for modo, f in cols:
            F, I = self._acc(modo, f)
            if tipo == 'inc':
                fila = self._fila_income(F)
            elif tipo == 'bal':
                fila = self._fila_balance(I)
            else:
                fila = self._fila_cash(F)
            datos[pd.Timestamp(f)] = fila
        df = pd.DataFrame(datos)
        df = df.reindex(columns=sorted(df.columns, reverse=True))   # más reciente primero (como Yahoo)
        df = df.apply(pd.to_numeric, errors='coerce').dropna(how='all')
        if self._ttm_first and not df.empty:
            df = df[df.iloc[:, 0].notna()]      # que la 1ª columna (TTM) nunca tenga NaN
        # Acciones: col 0 = último período, col 1 = mismo período del año anterior (cambio interanual real)
        if tipo == 'inc' and con_ttm and df.shape[1] >= 2:
            r = self._R('sh_dil')
            if r and r.get('cur_v') is not None and r.get('prev_v') is not None:
                for fila in ('Basic Average Shares', 'Diluted Average Shares'):
                    if fila in df.index:
                        df.loc[fila, df.columns[0]] = r['cur_v']
                        df.loc[fila, df.columns[1]] = r['prev_v']
        return df

    def _acciones(self):
        dei = self._d.get('shares_dei')
        dil = _ult_dur(self._d.get('sh_dil'))
        if dei and (date.today() - dei[1]).days < 450:
            if dil and not (0.6 <= dei[0] / dil <= 1.6):   # multi-clase raras (ej. BRK): usa diluidas
                return dil
            return dei[0]
        return dil

    # ---------- interfaz tipo yfinance ----------
    @property
    def financials(self):
        if '__inc' not in self._cache:
            self._cache['__inc'] = self._armar('inc')
        return self._cache['__inc']

    @property
    def balance_sheet(self):
        if '__bal' not in self._cache:
            self._cache['__bal'] = self._armar('bal')
        return self._cache['__bal']

    @property
    def cashflow(self):
        if '__cf' not in self._cache:
            self._cache['__cf'] = self._armar('cf')
        return self._cache['__cf']

    def history(self, start=None, **kw):
        if self._close is None or self._close.empty:
            return pd.DataFrame()
        s = self._close
        if start:
            s = s.loc[str(start):]
        return pd.DataFrame({'Close': s})

    @property
    def info(self):
        if '__info' in self._cache:
            return self._cache['__info']
        F, I = self._acc('ttm', None)
        inc, bal, cf = self._fila_income(F), self._fila_balance(I), self._fila_cash(F)
        px, acc = self._precio, self._acciones()
        mcap = px * acc if (px and acc) else None
        deuda, caja = bal['Total Debt'], bal['Cash']
        ev = (mcap + deuda - (caja or 0.0)) if (mcap is not None and deuda is not None) else None
        rev, ni, eps = inc['Total Revenue'], inc['Net Income'], inc['Diluted EPS']
        eq, assets = bal['Stockholders Equity'], bal['Total Assets']
        eq_pos = eq if (eq and eq > 0) else None
        divp = cf['Cash Dividends Paid']
        g = lambda n: (self._R(n) or {}).get('crec')
        g_eps = g('eps')
        dps = F('dps')
        if dps is not None and px:
            dy = dps / px
        elif divp is not None and mcap:
            dy = abs(divp) / mcap
        else:
            dy = None

        y = {}
        if self._usar_yahoo:
            try:
                y = _yahoo_extra(self.ticker) or {}
            except Exception:
                y = {}                                # si Yahoo falla, se usa lo calculado con SEC
        if y.get('earningsQuarterlyGrowth') is not None:
            g_eps = y['earningsQuarterlyGrowth']      # crecimiento de EPS: Yahoo
        eps_y = y.get('trailingEps')

        per = None
        if px and eps_y and eps_y > 0:
            per = px / eps_y                          # EPS: Yahoo
        elif px and eps and eps > 0:
            per = px / eps
        elif mcap and ni and ni > 0:
            per = mcap / ni
        peg_sec = per / (g_eps * 100) if (per and g_eps and 0.01 < g_eps <= 0.35) else None
        peg = y.get('pegRatio') if y.get('pegRatio') is not None else peg_sec   # PEG: Yahoo
        pre, tax = F('pretax'), F('tax')
        tasa = tax / pre if (pre and pre > 0 and tax is not None) else None

        info = {
            'longName': self._d.get('nombre') or self.ticker,
            'currentPrice': px, 'regularMarketPrice': px,
            'marketCap': mcap, 'enterpriseValue': ev,
            'trailingPE': per,
            'priceToBook': _div(mcap, eq_pos),
            'priceToSalesTrailing12Months': _div(mcap, rev if (rev and rev > 0) else None),
            'pegRatio': peg,
            'returnOnEquity': _div(ni, eq_pos), 'returnOnAssets': _div(ni, assets),
            'currentRatio': _div(bal['Current Assets'], bal['Current Liabilities']),
            'debtToEquity': (deuda / eq_pos * 100) if (eq_pos and deuda is not None) else None,
            'beta': y.get('beta') if y.get('beta') is not None else self._beta,   # Beta: Yahoo
            'grossMargins': _div(inc['Gross Profit'], rev), 'operatingMargins': _div(inc['Operating Income'], rev),
            'profitMargins': _div(ni, rev),
            'dividendYield': dy,
            'payoutRatio': (abs(divp) / ni) if (divp is not None and ni and ni > 0) else None,
            'earningsQuarterlyGrowth': g_eps, 'revenueGrowth': g('rev'), 'earningsGrowth': g('ni'),
            'freeCashflow': cf['Free Cash Flow'], 'operatingCashflow': cf['Operating Cash Flow'],
            'enterpriseToRevenue': _div(ev, rev if (rev and rev > 0) else None),
            'totalRevenue': rev, 'ebitda': inc['EBITDA'],
            'effectiveTaxRate': tasa,
            # Analistas: solo Yahoo (la SEC no los publica)
            'recommendationKey': y.get('recommendationKey'), 'targetMeanPrice': y.get('targetMeanPrice'),
        }
        self._cache['__info'] = info
        return info


def crear_ticker_sec(ticker, close=None, close_spy=None, precio=None, ttm_first=True, anios=4,
                     usar_yahoo=True):
    """Devuelve un SecTicker (parecido a yf.Ticker) o None si la empresa no es
    10-K/USD o la SEC no responde. Usar None como señal para caer a Yahoo.

    close / close_spy: Series de precios de cierre (para beta, YTD y market cap).
    precio: último precio (si no se pasa, se toma el último de `close`).
    ttm_first: True = 1ª columna de los estados = últimos 12 meses (análisis).
               False = solo años fiscales (para el histórico anual).
    """
    try:
        d = _datos_sec(str(ticker).upper(), anios)
    except Exception:
        return None
    if not d or ('rev' not in d and 'ni' not in d):
        return None
    try:
        t = SecTicker(str(ticker).upper(), d, close, close_spy, precio, ttm_first,
                      max_cols=anios + 5 if anios > 4 else 6, usar_yahoo=usar_yahoo)
        return t if t.valido() else None
    except Exception:
        return None
