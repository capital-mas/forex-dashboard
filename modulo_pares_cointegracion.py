"""
Módulo Streamlit — Scanner de Pares por Cointegración (Engle-Granger / Johansen)
Wrapea engine.cointegration_engine con UI, reutilizando helpers de app.py
(pasados como parámetros, igual que modulo_rotacion.py).
"""

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from itertools import combinations
from concurrent.futures import ThreadPoolExecutor, as_completed
from math import erf, sqrt

from engine.cointegration_engine import (
    analyze_pair,
    scan_universe,
    calculate_spread,
    calculate_zscore,
    generate_signals,
    adf_test,
    johansen_test,
    hurst_exponent,
)

try:
    from hmmlearn.hmm import GaussianHMM
    _HMM_DISPONIBLE = True
except ImportError:
    _HMM_DISPONIBLE = False

# TODO: ajustá este import al path real donde vive el dict en tu repo
PARES_SECTORES = {
    # ============================================================
    #  GRUPOS ORIGINALES (sin cambios)
    # ============================================================
    "Metales Preciosos": {
        "benchmark": "GLD",
        "empresas": ["B", "AEM", "KGC", "CDE", "NG", "HL", "HMY", "PAAS"],
        "tickers": {
            "GLD": "GLD", "SLV": "SLV", "GDX": "GDX",
            "B": "GOLD", "AEM": "AEM", "KGC": "KGC", "CDE": "CDE",
            "NG": "NG", "HL": "HL", "HMY": "HMY", "PAAS": "PAAS",
        },
    },
    "Tecnología": {
        "benchmark": "XLK",
        "empresas": ["AAPL", "MSFT", "GOOGL", "META", "NVDA", "ORCL", "CRM", "ADBE", "AMD"],
        "tickers": {
            "XLK": "XLK", "AAPL": "AAPL", "MSFT": "MSFT", "GOOGL": "GOOGL",
            "META": "META", "NVDA": "NVDA", "ORCL": "ORCL", "CRM": "CRM",
            "ADBE": "ADBE", "AMD": "AMD",
        },
    },
    "Semiconductores": {
        "benchmark": "SOXX",
        "empresas": ["NVDA", "AMD", "INTC", "TSM", "QCOM", "AVGO", "MU", "TXN", "ASML"],
        "tickers": {
            "SOXX": "SOXX", "NVDA": "NVDA", "AMD": "AMD", "INTC": "INTC",
            "TSM": "TSM", "QCOM": "QCOM", "AVGO": "AVGO", "MU": "MU",
            "TXN": "TXN", "ASML": "ASML",
        },
    },
    "Financieras": {
        "benchmark": "XLF",
        "empresas": ["JPM", "BAC", "WFC", "C", "GS", "MS", "USB", "PNC", "TFC"],
        "tickers": {
            "XLF": "XLF", "JPM": "JPM", "BAC": "BAC", "WFC": "WFC", "C": "C",
            "GS": "GS", "MS": "MS", "USB": "USB", "PNC": "PNC", "TFC": "TFC",
        },
    },
    "Energía": {
        "benchmark": "XLE",
        "empresas": ["XOM", "CVX", "COP", "SLB", "EOG", "PSX", "MPC", "OXY", "HAL"],
        "tickers": {
            "XLE": "XLE", "XOM": "XOM", "CVX": "CVX", "COP": "COP", "SLB": "SLB",
            "EOG": "EOG", "PSX": "PSX", "MPC": "MPC", "OXY": "OXY", "HAL": "HAL",
        },
    },
    "Salud": {
        "benchmark": "XLV",
        "empresas": ["JNJ", "PFE", "MRK", "ABBV", "LLY", "UNH", "BMY", "GILD", "AMGN"],
        "tickers": {
            "XLV": "XLV", "JNJ": "JNJ", "PFE": "PFE", "MRK": "MRK", "ABBV": "ABBV",
            "LLY": "LLY", "UNH": "UNH", "BMY": "BMY", "GILD": "GILD", "AMGN": "AMGN",
        },
    },
    "Consumo Discrecional": {
        "benchmark": "XLY",
        "empresas": ["AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "LOW", "TJX", "BKNG"],
        "tickers": {
            "XLY": "XLY", "AMZN": "AMZN", "TSLA": "TSLA", "HD": "HD", "MCD": "MCD",
            "NKE": "NKE", "SBUX": "SBUX", "LOW": "LOW", "TJX": "TJX", "BKNG": "BKNG",
        },
    },
    "Consumo Básico": {
        "benchmark": "XLP",
        "empresas": ["PG", "KO", "PEP", "WMT", "COST", "PM", "MO", "CL", "KMB"],
        "tickers": {
            "XLP": "XLP", "PG": "PG", "KO": "KO", "PEP": "PEP", "WMT": "WMT",
            "COST": "COST", "PM": "PM", "MO": "MO", "CL": "CL", "KMB": "KMB",
        },
    },
    "Industriales": {
        "benchmark": "XLI",
        "empresas": ["BA", "CAT", "GE", "HON", "UPS", "RTX", "LMT", "DE", "MMM"],
        "tickers": {
            "XLI": "XLI", "BA": "BA", "CAT": "CAT", "GE": "GE", "HON": "HON",
            "UPS": "UPS", "RTX": "RTX", "LMT": "LMT", "DE": "DE", "MMM": "MMM",
        },
    },
    "Utilities": {
        "benchmark": "XLU",
        "empresas": ["NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE", "XEL", "ED"],
        "tickers": {
            "XLU": "XLU", "NEE": "NEE", "DUK": "DUK", "SO": "SO", "D": "D",
            "AEP": "AEP", "EXC": "EXC", "SRE": "SRE", "XEL": "XEL", "ED": "ED",
        },
    },
    "Real Estate": {
        "benchmark": "XLRE",
        "empresas": ["AMT", "PLD", "CCI", "EQIX", "PSA", "O", "SPG", "DLR", "WELL"],
        "tickers": {
            "XLRE": "XLRE", "AMT": "AMT", "PLD": "PLD", "CCI": "CCI", "EQIX": "EQIX",
            "PSA": "PSA", "O": "O", "SPG": "SPG", "DLR": "DLR", "WELL": "WELL",
        },
    },
    "Comunicaciones": {
        "benchmark": "XLC",
        "empresas": ["GOOGL", "META", "NFLX", "DIS", "CMCSA", "T", "VZ", "TMUS", "EA"],
        "tickers": {
            "XLC": "XLC", "GOOGL": "GOOGL", "META": "META", "NFLX": "NFLX",
            "DIS": "DIS", "CMCSA": "CMCSA", "T": "T", "VZ": "VZ", "TMUS": "TMUS", "EA": "EA",
        },
    },
    "Materiales": {
        "benchmark": "XLB",
        "empresas": ["LIN", "APD", "SHW", "ECL", "FCX", "NEM", "DOW", "DD", "PPG"],
        "tickers": {
            "XLB": "XLB", "LIN": "LIN", "APD": "APD", "SHW": "SHW", "ECL": "ECL",
            "FCX": "FCX", "NEM": "NEM", "DOW": "DOW", "DD": "DD", "PPG": "PPG",
        },
    },
    "Argentina": {
        "benchmark": "ARGT",
        "empresas": ["GGAL", "YPF", "PAM", "BMA", "CRESY", "IRS", "LOMA", "EDN", "SUPV", "CEPU", "TGS"],
        "tickers": {
            "ARGT": "ARGT", "GGAL": "GGAL", "YPF": "YPF", "PAM": "PAM", "BMA": "BMA",
            "CRESY": "CRESY", "IRS": "IRSA", "LOMA": "LOMA", "EDN": "EDN",
            "SUPV": "SUPV", "CEPU": "CEPU", "TGS": "TGS",
        },
    },
    "Brasil": {
        "benchmark": "EWZ",
        "empresas": ["VALE", "PBR", "ITUB", "BBD", "ABEV", "SBS", "UGP", "BSBR", "ERJ", "GGB", "CIG", "VIV"],
        "tickers": {
            "EWZ": "EWZ", "VALE": "VALE", "PBR": "PBR", "ITUB": "ITUB", "BBD": "BBD",
            "ABEV": "ABEV", "SBS": "SBS", "UGP": "UGP", "BSBR": "BSBR", "ERJ": "ERJ",
            "GGB": "GGB", "CIG": "CIG", "VIV": "VIV",
        },
    },
    "Criptomonedas": {
        "benchmark": "BTC",
        "empresas": ["ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "DOT", "LINK", "LTC",
                     "ATOM", "ETC", "XLM", "FIL", "ICP", "HBAR", "NEAR", "ARB"],
        "tickers": {
            "BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD", "BNB": "BNB-USD",
            "XRP": "XRP-USD", "ADA": "ADA-USD", "DOGE": "DOGE-USD", "AVAX": "AVAX-USD",
            "DOT": "DOT-USD", "LINK": "LINK-USD", "LTC": "LTC-USD",
            "ATOM": "ATOM-USD", "ETC": "ETC-USD", "XLM": "XLM-USD", "FIL": "FIL-USD",
            "ICP": "ICP-USD", "HBAR": "HBAR-USD", "NEAR": "NEAR-USD", "ARB": "ARB-USD",
        },
    },

    # ============================================================
    #  GRUPOS NUEVOS — sub-sectores tecnológicos
    # ============================================================
    "Cloud/AI": {
        "benchmark": "SKYY",
        "empresas": ["PLTR", "SNOW", "DDOG", "NET", "MDB", "ESTC", "CFLT", "DOCN", "APP"],
        "tickers": {
            "SKYY": "SKYY", "PLTR": "PLTR", "SNOW": "SNOW", "DDOG": "DDOG", "NET": "NET",
            "MDB": "MDB", "ESTC": "ESTC", "CFLT": "CFLT", "DOCN": "DOCN", "APP": "APP",
        },
    },
    "Software": {
        "benchmark": "IGV",
        "empresas": ["ORCL", "CRM", "ADBE", "NOW", "INTU", "WDAY", "SNOW", "PLTR", "TEAM"],
        "tickers": {
            "IGV": "IGV", "ORCL": "ORCL", "CRM": "CRM", "ADBE": "ADBE", "NOW": "NOW",
            "INTU": "INTU", "WDAY": "WDAY", "SNOW": "SNOW", "PLTR": "PLTR", "TEAM": "TEAM",
        },
    },
    "Ciberseguridad": {
        "benchmark": "CIBR",
        "empresas": ["CRWD", "PANW", "ZS", "FTNT", "OKTA", "QLYS", "TENB", "RPD", "VRNS"],
        "tickers": {
            "CIBR": "CIBR", "CRWD": "CRWD", "PANW": "PANW", "ZS": "ZS", "FTNT": "FTNT",
            "OKTA": "OKTA", "QLYS": "QLYS", "TENB": "TENB", "RPD": "RPD", "VRNS": "VRNS",
        },
    },
    "Fintech": {
        "benchmark": "FINX",
        "empresas": ["PYPL", "AFRM", "SOFI", "UPST", "LC", "NU", "COIN", "HOOD", "BILL"],
        "tickers": {
            "FINX": "FINX", "PYPL": "PYPL", "AFRM": "AFRM", "SOFI": "SOFI", "UPST": "UPST",
            "LC": "LC", "NU": "NU", "COIN": "COIN", "HOOD": "HOOD", "BILL": "BILL",
        },
    },
    "Internet": {
        "benchmark": "FDN",
        "empresas": ["GOOGL", "META", "NFLX", "SNAP", "PINS", "RDDT", "SPOT", "ROKU", "DASH"],
        "tickers": {
            "FDN": "FDN", "GOOGL": "GOOGL", "META": "META", "NFLX": "NFLX", "SNAP": "SNAP",
            "PINS": "PINS", "RDDT": "RDDT", "SPOT": "SPOT", "ROKU": "ROKU", "DASH": "DASH",
        },
    },
    "E-commerce": {
        "benchmark": "IBUY",
        "empresas": ["AMZN", "SHOP", "ETSY", "EBAY", "MELI", "SE", "PDD", "BABA", "JD"],
        "tickers": {
            "IBUY": "IBUY", "AMZN": "AMZN", "SHOP": "SHOP", "ETSY": "ETSY", "EBAY": "EBAY",
            "MELI": "MELI", "SE": "SE", "PDD": "PDD", "BABA": "BABA", "JD": "JD",
        },
    },

    # ============================================================
    #  GRUPOS NUEVOS — salud
    # ============================================================
    "Biotecnología": {
        "benchmark": "XBI",
        "empresas": ["AMGN", "REGN", "VRTX", "GILD", "BIIB", "MRNA", "ALNY", "CRSP", "BEAM"],
        "tickers": {
            "XBI": "XBI", "AMGN": "AMGN", "REGN": "REGN", "VRTX": "VRTX", "GILD": "GILD",
            "BIIB": "BIIB", "MRNA": "MRNA", "ALNY": "ALNY", "CRSP": "CRSP", "BEAM": "BEAM",
        },
    },
    "Farmacéuticas": {
        "benchmark": "PPH",
        "empresas": ["LLY", "JNJ", "PFE", "MRK", "ABBV", "BMY", "AZN", "NVO", "SNY"],
        "tickers": {
            "PPH": "PPH", "LLY": "LLY", "JNJ": "JNJ", "PFE": "PFE", "MRK": "MRK",
            "ABBV": "ABBV", "BMY": "BMY", "AZN": "AZN", "NVO": "NVO", "SNY": "SNY",
        },
    },
    "Equipos Médicos": {
        "benchmark": "IHI",
        "empresas": ["ISRG", "ABT", "SYK", "BSX", "MDT", "EW", "ZBH", "BDX", "DXCM"],
        "tickers": {
            "IHI": "IHI", "ISRG": "ISRG", "ABT": "ABT", "SYK": "SYK", "BSX": "BSX",
            "MDT": "MDT", "EW": "EW", "ZBH": "ZBH", "BDX": "BDX", "DXCM": "DXCM",
        },
    },
    "Servicios de Salud": {
        "benchmark": "IHF",
        "empresas": ["UNH", "ELV", "CI", "HUM", "CVS", "CNC", "MOH", "DVA", "HCA"],
        "tickers": {
            "IHF": "IHF", "UNH": "UNH", "ELV": "ELV", "CI": "CI", "HUM": "HUM",
            "CVS": "CVS", "CNC": "CNC", "MOH": "MOH", "DVA": "DVA", "HCA": "HCA",
        },
    },

    # ============================================================
    #  GRUPOS NUEVOS — financieras granulares
    # ============================================================
    "Seguros": {
        "benchmark": "KIE",
        "empresas": ["PGR", "CB", "TRV", "ALL", "AFL", "MET", "PRU", "AIG", "HIG"],
        "tickers": {
            "KIE": "KIE", "PGR": "PGR", "CB": "CB", "TRV": "TRV", "ALL": "ALL",
            "AFL": "AFL", "MET": "MET", "PRU": "PRU", "AIG": "AIG", "HIG": "HIG",
        },
    },
    "Mercados Capitales": {
        "benchmark": "KCE",
        "empresas": ["SCHW", "CME", "ICE", "NDAQ", "MS", "GS", "IBKR", "HOOD", "COIN"],
        "tickers": {
            "KCE": "KCE", "SCHW": "SCHW", "CME": "CME", "ICE": "ICE", "NDAQ": "NDAQ",
            "MS": "MS", "GS": "GS", "IBKR": "IBKR", "HOOD": "HOOD", "COIN": "COIN",
        },
    },
    "Bancos Regionales": {
        "benchmark": "KRE",
        "empresas": ["FITB", "HBAN", "RF", "CFG", "ZION", "KEY", "CMA", "MTB", "WAL"],
        "tickers": {
            "KRE": "KRE", "FITB": "FITB", "HBAN": "HBAN", "RF": "RF", "CFG": "CFG",
            "ZION": "ZION", "KEY": "KEY", "CMA": "CMA", "MTB": "MTB", "WAL": "WAL",
        },
    },
    "Finanzas Diversif.": {
        "benchmark": "IYG",
        "empresas": ["V", "MA", "AXP", "DFS", "SYF", "ALLY", "COF", "FI", "PYPL"],
        "tickers": {
            "IYG": "IYG", "V": "V", "MA": "MA", "AXP": "AXP", "DFS": "DFS",
            "SYF": "SYF", "ALLY": "ALLY", "COF": "COF", "FI": "FI", "PYPL": "PYPL",
        },
    },

    # ============================================================
    #  GRUPOS NUEVOS — energía granular
    # ============================================================
    "Petróleo Integrado": {
        "benchmark": "XOP",
        "empresas": ["XOM", "CVX", "COP", "EOG", "OXY", "DVN", "MRO", "APA", "PXD"],
        "tickers": {
            "XOP": "XOP", "XOM": "XOM", "CVX": "CVX", "COP": "COP", "EOG": "EOG",
            "OXY": "OXY", "DVN": "DVN", "MRO": "MRO", "APA": "APA", "PXD": "PXD",
        },
    },
    "Gas Natural": {
        "benchmark": "FCG",
        "empresas": ["LNG", "EQT", "AR", "RRC", "CNX", "KMI", "WMB", "OKE", "TRGP"],
        "tickers": {
            "FCG": "FCG", "LNG": "LNG", "EQT": "EQT", "AR": "AR", "RRC": "RRC",
            "CNX": "CNX", "KMI": "KMI", "WMB": "WMB", "OKE": "OKE", "TRGP": "TRGP",
        },
    },
    "Energía Renovable": {
        "benchmark": "ICLN",
        "empresas": ["NEE", "BEP", "BEPC", "AES", "ORA", "PLUG", "BE", "GEV", "RUN"],
        "tickers": {
            "ICLN": "ICLN", "NEE": "NEE", "BEP": "BEP", "BEPC": "BEPC", "AES": "AES",
            "ORA": "ORA", "PLUG": "PLUG", "BE": "BE", "GEV": "GEV", "RUN": "RUN",
        },
    },
    "Energía Solar": {
        "benchmark": "TAN",
        "empresas": ["FSLR", "ENPH", "SEDG", "RUN", "ARRY", "SHLS", "CSIQ", "JKS", "NOVA"],
        "tickers": {
            "TAN": "TAN", "FSLR": "FSLR", "ENPH": "ENPH", "SEDG": "SEDG", "RUN": "RUN",
            "ARRY": "ARRY", "SHLS": "SHLS", "CSIQ": "CSIQ", "JKS": "JKS", "NOVA": "NOVA",
        },
    },
    "Litio/Baterías": {
        "benchmark": "LIT",
        "empresas": ["ALB", "LAC", "PLL", "SES", "QS", "MVST", "LICY", "ALTM", "ENVX"],
        "tickers": {
            "LIT": "LIT", "ALB": "ALB", "LAC": "LAC", "PLL": "PLL", "SES": "SES",
            "QS": "QS", "MVST": "MVST", "LICY": "LICY", "ALTM": "ALTM", "ENVX": "ENVX",
        },
    },

    # ============================================================
    #  GRUPOS NUEVOS — industriales / defensa / transporte
    # ============================================================
    "Aeroespacial": {
        "benchmark": "ITA",
        "empresas": ["BA", "RTX", "LMT", "NOC", "GD", "HII", "TDG", "HEI", "LHX"],
        "tickers": {
            "ITA": "ITA", "BA": "BA", "RTX": "RTX", "LMT": "LMT", "NOC": "NOC",
            "GD": "GD", "HII": "HII", "TDG": "TDG", "HEI": "HEI", "LHX": "LHX",
        },
    },
    "Defensa": {
        "benchmark": "XAR",
        "empresas": ["LMT", "RTX", "NOC", "GD", "HII", "TDG", "KTOS", "AVAV", "LDOS"],
        "tickers": {
            "XAR": "XAR", "LMT": "LMT", "RTX": "RTX", "NOC": "NOC", "GD": "GD",
            "HII": "HII", "TDG": "TDG", "KTOS": "KTOS", "AVAV": "AVAV", "LDOS": "LDOS",
        },
    },
    "Transporte": {
        "benchmark": "IYT",
        "empresas": ["UPS", "FDX", "UNP", "CSX", "NSC", "JBHT", "ODFL", "XPO", "CHRW"],
        "tickers": {
            "IYT": "IYT", "UPS": "UPS", "FDX": "FDX", "UNP": "UNP", "CSX": "CSX",
            "NSC": "NSC", "JBHT": "JBHT", "ODFL": "ODFL", "XPO": "XPO", "CHRW": "CHRW",
        },
    },

    # ============================================================
    #  GRUPOS NUEVOS — consumo
    # ============================================================
    "Retail": {
        "benchmark": "XRT",
        "empresas": ["AMZN", "WMT", "TGT", "COST", "HD", "LOW", "TJX", "ROST", "DG"],
        "tickers": {
            "XRT": "XRT", "AMZN": "AMZN", "WMT": "WMT", "TGT": "TGT", "COST": "COST",
            "HD": "HD", "LOW": "LOW", "TJX": "TJX", "ROST": "ROST", "DG": "DG",
        },
    },
    "Autos": {
        "benchmark": "CARZ",
        "empresas": ["TSLA", "GM", "F", "TM", "HMC", "STLA", "RIVN", "LCID", "NIO"],
        "tickers": {
            "CARZ": "CARZ", "TSLA": "TSLA", "GM": "GM", "F": "F", "TM": "TM",
            "HMC": "HMC", "STLA": "STLA", "RIVN": "RIVN", "LCID": "LCID", "NIO": "NIO",
        },
    },
    "Hotelería/Viajes": {
        "benchmark": "PEJ",
        "empresas": ["MAR", "HLT", "ABNB", "BKNG", "EXPE", "RCL", "CCL", "NCLH", "MGM"],
        "tickers": {
            "PEJ": "PEJ", "MAR": "MAR", "HLT": "HLT", "ABNB": "ABNB", "BKNG": "BKNG",
            "EXPE": "EXPE", "RCL": "RCL", "CCL": "CCL", "NCLH": "NCLH", "MGM": "MGM",
        },
    },
    "Alimentos": {
        "benchmark": "PBJ",
        "empresas": ["KO", "PEP", "MDLZ", "KHC", "GIS", "CPB", "SJM", "K", "HSY"],
        "tickers": {
            "PBJ": "PBJ", "KO": "KO", "PEP": "PEP", "MDLZ": "MDLZ", "KHC": "KHC",
            "GIS": "GIS", "CPB": "CPB", "SJM": "SJM", "K": "K", "HSY": "HSY",
        },
    },

    # ============================================================
    #  GRUPOS NUEVOS — materiales / commodities
    # ============================================================
    "Cobre/Metales": {
        "benchmark": "COPX",
        "empresas": ["FCX", "SCCO", "TECK", "HBM", "NUE", "STLD", "CLF", "AA", "ERO"],
        "tickers": {
            "COPX": "COPX", "FCX": "FCX", "SCCO": "SCCO", "TECK": "TECK", "HBM": "HBM",
            "NUE": "NUE", "STLD": "STLD", "CLF": "CLF", "AA": "AA", "ERO": "ERO",
        },
    },
    "Acero": {
        "benchmark": "SLX",
        "empresas": ["NUE", "STLD", "CLF", "X", "MT", "RS", "CMC", "PKX", "ATI"],
        "tickers": {
            "SLX": "SLX", "NUE": "NUE", "STLD": "STLD", "CLF": "CLF", "X": "X",
            "MT": "MT", "RS": "RS", "CMC": "CMC", "PKX": "PKX", "ATI": "ATI",
        },
    },
    "Agua": {
        "benchmark": "PHO",
        "empresas": ["AWK", "WTRG", "AWR", "YORW", "MSEX", "SJW", "CWCO", "GWRS", "ARTNA"],
        "tickers": {
            "PHO": "PHO", "AWK": "AWK", "WTRG": "WTRG", "AWR": "AWR", "YORW": "YORW",
            "MSEX": "MSEX", "SJW": "SJW", "CWCO": "CWCO", "GWRS": "GWRS", "ARTNA": "ARTNA",
        },
    },
    "Agro/Fertilizantes": {
        "benchmark": "MOS",
        "empresas": ["NTR", "CF", "ADM", "BG", "FMC", "CTVA"],
        "tickers": {
            "MOS": "MOS", "NTR": "NTR", "CF": "CF", "ADM": "ADM",
            "BG": "BG", "FMC": "FMC", "CTVA": "CTVA",
        },
    },

    # ============================================================
    #  GRUPOS NUEVOS — REITs granulares
    # ============================================================
    "REIT Industrial": {
        "benchmark": "INDS",
        "empresas": ["PLD", "AMT", "CCI", "DLR", "EQIX", "STAG", "EGP", "FR", "REXR"],
        "tickers": {
            "INDS": "INDS", "PLD": "PLD", "AMT": "AMT", "CCI": "CCI", "DLR": "DLR",
            "EQIX": "EQIX", "STAG": "STAG", "EGP": "EGP", "FR": "FR", "REXR": "REXR",
        },
    },
    "REIT Residencial": {
        "benchmark": "REZ",
        "empresas": ["EQR", "AVB", "ESS", "MAA", "UDR", "CPT", "ELS", "INVH", "AMH"],
        "tickers": {
            "REZ": "REZ", "EQR": "EQR", "AVB": "AVB", "ESS": "ESS", "MAA": "MAA",
            "UDR": "UDR", "CPT": "CPT", "ELS": "ELS", "INVH": "INVH", "AMH": "AMH",
        },
    },

    # ============================================================
    #  GRUPOS NUEVOS — telecom
    # ============================================================
    "Telecomunicaciones": {
        "benchmark": "IYZ",
        "empresas": ["T", "VZ", "TMUS", "S", "CHTR", "CMCSA", "LUMN", "VOD", "BT"],
        "tickers": {
            "IYZ": "IYZ", "T": "T", "VZ": "VZ", "TMUS": "TMUS", "S": "S",
            "CHTR": "CHTR", "CMCSA": "CMCSA", "LUMN": "LUMN", "VOD": "VOD", "BT": "BT",
        },
    },

    # ============================================================
    #  GRUPOS NUEVOS — países / regiones
    # ============================================================
    "China": {
        "benchmark": "FXI",
        "empresas": ["BABA", "TCEHY", "BIDU", "JD", "NIO", "LI", "XPEV", "PDD", "NTES"],
        "tickers": {
            "FXI": "FXI", "BABA": "BABA", "TCEHY": "TCEHY", "BIDU": "BIDU", "JD": "JD",
            "NIO": "NIO", "LI": "LI", "XPEV": "XPEV", "PDD": "PDD", "NTES": "NTES",
        },
    },
    "India": {
        "benchmark": "INDA",
        "empresas": ["INFY", "WIT", "HDB", "IBN", "VEDL", "RDY", "TTM"],
        "tickers": {
            "INDA": "INDA", "INFY": "INFY", "WIT": "WIT", "HDB": "HDB", "IBN": "IBN",
            "VEDL": "VEDL", "RDY": "RDY", "TTM": "TTM",
        },
    },
    "Europa Tecnología": {
        "benchmark": "VGK",
        "empresas": ["SAP", "ASML", "NXPI"],
        "tickers": {
            "VGK": "VGK", "SAP": "SAP", "ASML": "ASML", "NXPI": "NXPI",
        },
    },
    "Europa Finanzas": {
        "benchmark": "VGK",
        "empresas": ["HSBC", "BBVA", "SAN", "UBS", "ING"],
        "tickers": {
            "VGK": "VGK", "HSBC": "HSBC", "BBVA": "BBVA", "SAN": "SAN",
            "UBS": "UBS", "ING": "ING",
        },
    },

    # ============================================================
    #  GRUPOS NUEVOS — cripto mineras
    # ============================================================
    "Cripto Mineras": {
        "benchmark": "COIN",
        "empresas": ["MARA", "RIOT", "CLSK", "HUT", "BTDR", "IREN", "CAN", "WULF"],
        "tickers": {
            "COIN": "COIN", "MARA": "MARA", "RIOT": "RIOT", "CLSK": "CLSK", "HUT": "HUT",
            "BTDR": "BTDR", "IREN": "IREN", "CAN": "CAN", "WULF": "WULF",
        },
    },
}


def _fig_spread_zscore(nombre_a, nombre_b, spread, zscore, entry_z, exit_z, palette):
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
        row_heights=[0.6, 0.4],
        subplot_titles=(f'Spread {nombre_a} - β·{nombre_b}', 'Z-Score del spread'),
    )
    fig.add_trace(go.Scatter(x=spread.index, y=spread, line=dict(color=palette['acent'], width=1.6),
                              name='Spread'), row=1, col=1)
    fig.add_hline(y=0, line_color=palette['muted'], opacity=0.4, row=1, col=1)

    fig.add_trace(go.Scatter(x=zscore.index, y=zscore, line=dict(color=palette['monster'], width=1.4),
                              name='Z-Score'), row=2, col=1)
    fig.add_hline(y=entry_z, line_dash='dash', line_color=palette['red'], opacity=0.6, row=2, col=1)
    fig.add_hline(y=-entry_z, line_dash='dash', line_color=palette['green'], opacity=0.6, row=2, col=1)
    fig.add_hline(y=exit_z, line_dash='dot', line_color=palette['yell'], opacity=0.4, row=2, col=1)
    fig.add_hline(y=-exit_z, line_dash='dot', line_color=palette['yell'], opacity=0.4, row=2, col=1)
    fig.add_hline(y=0, line_color=palette['muted'], opacity=0.4, row=2, col=1)

    fig.update_yaxes(gridcolor=palette['grid'], row=1, col=1)
    fig.update_yaxes(gridcolor=palette['grid'], row=2, col=1)
    fig.update_xaxes(gridcolor=palette['grid'])
    fig.update_layout(
        plot_bgcolor=palette['bg1'], paper_bgcolor=palette['bg2'],
        font=dict(color='#b0bcd0', family='Inter, sans-serif'), dragmode=False,
        height=520, hovermode='x unified',
        legend=dict(orientation='h', y=1.08, font=dict(size=9)),
        margin=dict(l=10, r=10, t=45, b=10),
    )
    fig.update_annotations(font=dict(color=palette['text'], size=12))
    return fig


def _norm_cdf(v):
    """CDF de la normal estándar sin depender de scipy."""
    return 0.5 * (1 + erf(v / sqrt(2)))


def _ar1_sigma_eq(spread):
    """Ajusta un AR(1) sobre el spread y devuelve sigma de equilibrio
    (dispersión estacionaria). None si no hay suficiente historial."""
    s = spread.dropna().values
    if len(s) < 30:
        return None
    x, y = s[:-1], s[1:]
    b, a = np.polyfit(x, y, 1)
    resid = y - (a + b * x)
    sigma_eps = float(np.std(resid, ddof=2)) if len(resid) > 2 else float(np.std(resid))
    if 0 < b < 1:
        return sigma_eps / np.sqrt(1 - b ** 2)
    return float(np.std(s))


def _ou_time_and_prob(theta, current_zscore):
    """Percentiles de tiempo de convergencia (50/75/95%) y probabilidad
    aproximada de cruce de cero del z-score en 20/40/80 ruedas. Solo
    necesita theta y el z-score actual — no requiere el spread completo."""
    def _t_percentil(p):
        return np.log(1 / (1 - p)) / theta

    def _prob_cruce(t):
        var_t = max(1 - np.exp(-2 * theta * t), 1e-6)
        media_t = current_zscore * np.exp(-theta * t)
        return _norm_cdf(-abs(media_t) / np.sqrt(var_t))

    return dict(
        t50=_t_percentil(0.5), t75=_t_percentil(0.75), t95=_t_percentil(0.95),
        p20=_prob_cruce(20), p40=_prob_cruce(40), p80=_prob_cruce(80),
    )


def _ou_extended_stats(spread, current_zscore, half_life):
    """Combina sigma_eq (necesita el spread) + theta/percentiles/probabilidad
    (no lo necesitan) en un solo dict. None si falta algún insumo."""
    if half_life is None or half_life <= 0 or current_zscore is None:
        return None
    sigma_eq = _ar1_sigma_eq(spread)
    if sigma_eq is None:
        return None
    theta = np.log(2) / half_life  # consistente con el half-life ya mostrado
    out = dict(theta=theta, sigma_eq=sigma_eq)
    out.update(_ou_time_and_prob(theta, current_zscore))
    return out


def _fit_hmm_regimenes(feature_series, n_states=2, n_iter=200, random_state=42):
    """Ajusta un Hidden Markov Model Gaussiano de n_states regímenes sobre una
    serie 1D (típicamente el Z-Score del spread o sus variaciones diarias).

    Devuelve un dict con:
      - states: array de régimen (0..n_states-1) asignado a cada rueda (Viterbi)
      - state_probs: DataFrame con la probabilidad posterior de cada régimen por rueda
      - means / stds: media y desvío de la feature en cada régimen (para etiquetarlos)
      - trans_mat: matriz de transición (fila = régimen actual, columna = régimen siguiente)
      - stay_prob: probabilidad de permanecer en el régimen actual (diagonal de trans_mat)
      - expected_duration: duración esperada (en ruedas) de cada régimen = 1/(1-stay_prob)
      - current_state: régimen vigente en la última rueda
      - current_state_prob: probabilidad posterior del régimen vigente
      - model: objeto GaussianHMM ya entrenado

    None si hmmlearn no está instalado o no hay suficiente historial.
    """
    if not _HMM_DISPONIBLE:
        return None

    serie = feature_series.dropna()
    if len(serie) < 50:
        return None

    X = serie.values.reshape(-1, 1)

    modelo = GaussianHMM(
        n_components=n_states, covariance_type='diag',
        n_iter=n_iter, random_state=random_state,
    )
    modelo.fit(X)

    states = modelo.predict(X)
    state_probs = modelo.predict_proba(X)

    means = modelo.means_.flatten()
    stds = np.sqrt(np.array([np.diag(c) for c in modelo.covars_]).flatten())
    trans_mat = modelo.transmat_
    stay_prob = np.diag(trans_mat)
    expected_duration = 1.0 / np.clip(1.0 - stay_prob, 1e-6, None)

    return dict(
        states=pd.Series(states, index=serie.index, name='regime'),
        state_probs=pd.DataFrame(state_probs, index=serie.index,
                                  columns=[f'P(régimen {i})' for i in range(n_states)]),
        means=means, stds=stds, trans_mat=trans_mat,
        stay_prob=stay_prob, expected_duration=expected_duration,
        current_state=int(states[-1]), current_state_prob=float(state_probs[-1, states[-1]]),
        model=modelo,
    )


def _etiquetas_regimen(means, stds):
    """Ordena los regímenes de menor a mayor volatilidad/dispersión relativa
    y les pone una etiqueta legible. El de menor |media|+std suele ser el
    régimen 'calmo/mean-reverting'; el más disperso, el 'volátil/trending'."""
    orden = np.argsort(np.abs(means) + stds)
    etiquetas = {}
    nombres_base = ['🟢 Calmo / reversión', '🟡 Intermedio', '🔴 Volátil / ruptura']
    for rank, idx in enumerate(orden):
        etiquetas[idx] = nombres_base[rank] if rank < len(nombres_base) else f'Régimen {idx}'
    return etiquetas


def _fig_hmm_regimenes(feature_series, hmm_result, etiquetas, palette, feature_label):
    """Serie coloreada por régimen (arriba) + probabilidad posterior apilada (abajo)."""
    serie = feature_series.reindex(hmm_result['states'].index)
    states = hmm_result['states']
    colores_estado = ['#3fb950', '#e3b341', '#f85149', '#3a7bd5', '#bc8cff']

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
        row_heights=[0.6, 0.4],
        subplot_titles=(f'{feature_label} coloreada por régimen', 'Probabilidad posterior de cada régimen'),
    )

    fig.add_trace(go.Scatter(x=serie.index, y=serie, mode='lines',
                              line=dict(color=palette['muted'], width=1), showlegend=False),
                  row=1, col=1)
    for est in sorted(states.unique()):
        mask = states == est
        fig.add_trace(go.Scatter(
            x=serie.index[mask], y=serie[mask], mode='markers',
            marker=dict(color=colores_estado[est % len(colores_estado)], size=5),
            name=etiquetas.get(est, f'Régimen {est}'),
        ), row=1, col=1)
    fig.add_hline(y=0, line_color=palette['muted'], opacity=0.4, row=1, col=1)

    n_states = hmm_result['state_probs'].shape[1]
    for i in range(n_states):
        fig.add_trace(go.Scatter(
            x=hmm_result['state_probs'].index, y=hmm_result['state_probs'].iloc[:, i],
            mode='lines', stackgroup='probs', name=etiquetas.get(i, f'Régimen {i}'),
            line=dict(width=0.5, color=colores_estado[i % len(colores_estado)]), showlegend=False,
        ), row=2, col=1)

    fig.update_yaxes(gridcolor=palette['grid'], row=1, col=1)
    fig.update_yaxes(gridcolor=palette['grid'], range=[0, 1], row=2, col=1)
    fig.update_xaxes(gridcolor=palette['grid'])
    fig.update_layout(
        plot_bgcolor=palette['bg1'], paper_bgcolor=palette['bg2'],
        font=dict(color='#b0bcd0', family='Inter, sans-serif'), dragmode=False,
        height=560, hovermode='x unified',
        legend=dict(orientation='h', y=1.1, font=dict(size=9)),
        margin=dict(l=10, r=10, t=45, b=10),
    )
    fig.update_annotations(font=dict(color=palette['text'], size=12))
    return fig


def modulo_pares_cointegracion(
    descargar_datos, get_close_series, fmt_precio, kpi_cards_4,
    chips_navegacion, PLOTLY_CONFIG, selector_ticker_autocomplete,
):
    """Scanner de pares vía cointegración Engle-Granger/Johansen — motor propio
    en engine/cointegration_engine.py (testeado con pytest), separado del
    scanner simple de ratio+Z-score que ya tenés en 'Pares (Mean Reversion)'."""

    palette = dict(
        acent='#3a7bd5', monster='#6CC24A', text='#e6edf3', muted='#6b7d9a',
        green='#3fb950', red='#f85149', yell='#e3b341', grid='#21262d',
        bg1='#0d1117', bg2='#07090f',
    )

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1c20 0%,#0a2530 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #bc8cff;
         border-radius:14px; padding:28px 32px; margin-bottom:24px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">
        📐 Statistical Arbitrage — Cointegración
      </div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Test de Engle-Granger (y Johansen para 3+ activos), hedge ratio por OLS, half-life de
        reversión (Ornstein-Uhlenbeck), exponente de Hurst y dinámica de reversión del spread.
        Motor separado y testeado (<code>engine/cointegration_engine.py</code>), distinto del
        scanner rápido de ratio+Z-score de la otra pestaña.
      </div>
    </div>
    """, unsafe_allow_html=True)

    tab_par, tab_universo, tab_hmm = st.tabs(
        ['🔎 Par puntual', '🌐 Escaneo de universo', '🔮 Regímenes HMM']
    )

    # ══════════════════════════════════════════════════════════════
    #  TAB 1 — Par puntual: cointegración + dinámica de reversión
    # ══════════════════════════════════════════════════════════════
    with tab_par:
        c1, c2, c3 = st.columns(3)
        with c1:
            ticker_a = selector_ticker_autocomplete('coint_a', label='Activo A')
        with c2:
            ticker_b = selector_ticker_autocomplete('coint_b', label='Activo B')
        with c3:
            periodo = st.selectbox('Historial', ['1y', '2y', '5y'], index=1, key='coint_periodo')

        cp1, cp2, cp3, cp4 = st.columns(4)
        with cp1:
            z_window = st.slider('Ventana Z-Score', 10, 100, 30, 5, key='coint_zwin')
        with cp2:
            entry_z = st.slider('Z de entrada', 0.5, 3.5, 2.0, 0.1, key='coint_entry')
        with cp3:
            exit_z = st.slider('Z de salida', 0.1, 1.5, 0.5, 0.1, key='coint_exit')
        with cp4:
            significancia = st.selectbox('Significancia', [0.01, 0.05, 0.10], index=1, key='coint_sig')

        if not ticker_a or not ticker_b or ticker_a == ticker_b:
            st.info('Elegí dos activos distintos para testear cointegración.')
            return

        if st.button('▶ Analizar cointegración', key='coint_run', type='primary'):
            st.session_state['coint_run_flag'] = True

        if not st.session_state.get('coint_run_flag'):
            return

        with st.spinner(f'Descargando {ticker_a} / {ticker_b}...'):
            df_a = descargar_datos(ticker_a, periodo)
            df_b = descargar_datos(ticker_b, periodo)

        if df_a is None or df_b is None:
            st.error('No se pudieron descargar precios para uno o ambos activos.')
            return

        cl_a = get_close_series(df_a)
        cl_b = get_close_series(df_b)
        if cl_a is None or cl_b is None or len(cl_a) < 60 or len(cl_b) < 60:
            st.error('Historial insuficiente (mínimo ~60 ruedas) para el test de cointegración.')
            return

        stats = analyze_pair(cl_a, cl_b, ticker_a, ticker_b,
                              zscore_window=z_window, significance=significancia)

        badge_color = '#3fb950' if stats.is_cointegrated else '#f85149'
        badge_txt = 'COINTEGRADOS ✓' if stats.is_cointegrated else 'NO COINTEGRADOS ✗'

        kpi_cards_4([
            ('Engle-Granger p-value', f'{stats.pvalue:.4f}', badge_txt, badge_color),
            ('Hedge Ratio (β)', f'{stats.hedge_ratio:.4f}',
             f'{ticker_a} = β·{ticker_b} + {stats.intercept:.2f}', '#3a7bd5'),
            ('Half-Life', f'{stats.half_life:.1f} ruedas' if stats.half_life else 'N/A',
             'Reversión a la media (OU)', '#e3b341'),
            ('Hurst', f'{stats.hurst:.3f}' if stats.hurst is not None else 'N/A',
             'H<0.5 = mean-reverting' if (stats.hurst or 0.5) < 0.5 else 'H≥0.5 = trending/random',
             '#7ee787' if (stats.hurst or 0.5) < 0.5 else '#f0883e'),
        ])

        with st.expander('📖 ¿Cómo se interpreta cada indicador?', expanded=False):
            st.markdown("""
**Engle-Granger (p-value):** testea si existe una combinación lineal estacionaria entre los
dos precios (el spread). Un p-value por debajo del umbral de significancia elegido (ej. 0.05)
rechaza la hipótesis nula de "no cointegración" — sugiere que el spread revierte a la media en
el largo plazo. Un p-value alto **no prueba** que no cointegren, solo que no hay evidencia
suficiente con este historial y ventana.

**Hedge Ratio (β):** cuánto del Activo B hay que tener (en la dirección opuesta al Activo A)
por cada unidad del Activo A para que el spread quede neutral a movimientos direccionales
conjuntos del mercado. Sale de una regresión OLS: A = β·B + intercepto.

**Half-Life:** cuántas ruedas tarda, en promedio, el spread en recorrer la mitad de la
distancia hacia su valor de equilibrio, asumiendo un proceso Ornstein-Uhlenbeck. Half-life
corto implica reversión rápida (más apto para horizontes cortos); muy largo o indefinido
implica que la fuerza de reversión es débil.

**Hurst:** mide la "memoria" de la serie del spread. H < 0.5 indica comportamiento
mean-reverting (anti-persistente); H ≈ 0.5 se parece a un random walk; H > 0.5 indica
tendencia/persistencia. Para pairs trading conviene un Hurst bien por debajo de 0.5.

**ADF (Augmented Dickey-Fuller):** test de raíz unitaria aplicado directamente sobre el
spread. Un resultado "estacionario" respalda al Engle-Granger — en un par bien cointegrado,
ambos tests deberían coincidir. Si dan resultados contradictorios, tratá la señal con cautela.

**θ, σ, percentiles y probabilidad de cruce (más abajo):** ver la sección "Dinámica de
reversión" — θ es la velocidad de reversión (deriva del half-life), σ es cuánto ruido tiene
el spread alrededor de su equilibrio, y los percentiles/probabilidades traducen todo eso a
"cuánto tiempo puede tardar" y "qué tan probable es" la convergencia.
            """)

        c4, c5 = st.columns(2)
        with c4:
            st.metric('ADF sobre el spread', 'Estacionario ✓' if stats.adf_is_stationary else 'No estacionario ✗',
                       f'p-value: {stats.adf_pvalue:.4f}' if stats.adf_pvalue is not None else '')
        with c5:
            st.metric('Z-Score actual', f'{stats.current_zscore:+.2f}' if stats.current_zscore is not None else 'N/A')

        if not stats.is_cointegrated:
            st.warning(
                f'⚠️ {ticker_a}/{ticker_b} NO pasan el test de Engle-Granger al {int((1-significancia)*100)}% '
                'de confianza. El spread puede no revertir a la media — el par no es un buen candidato '
                'para pairs trading con este historial. Podés seguir viendo el gráfico igual, con cautela.'
            )

        spread = calculate_spread(cl_a, cl_b, stats.hedge_ratio, stats.intercept)
        zscore = calculate_zscore(spread, window=z_window)
        signal = generate_signals(zscore, entry_z=entry_z, exit_z=exit_z)

        st.plotly_chart(
            _fig_spread_zscore(ticker_a, ticker_b, spread, zscore, entry_z, exit_z, palette),
            use_container_width=True, config=PLOTLY_CONFIG, key='coint_fig_spread',
        )

        # ── Dinámica de reversión (Ornstein-Uhlenbeck) ──────────────
        st.markdown('---')
        st.markdown('### 🌀 Dinámica de reversión (Ornstein-Uhlenbeck)')

        ou = _ou_extended_stats(spread, stats.current_zscore, stats.half_life)
        if ou is None:
            st.info('No se pudo estimar el proceso de reversión (half-life no disponible o historial insuficiente).')
        else:
            co1, co2 = st.columns(2)
            with co1:
                st.metric('Velocidad de reversión (θ)', f"{ou['theta']:.4f}",
                           'Por rueda — mayor = revierte más rápido')
            with co2:
                st.metric('σ de equilibrio', f"{ou['sigma_eq']:.4f}",
                           'Dispersión del spread en torno a la media')

            st.markdown('**Tiempo esperado para recorrer % del camino hacia el equilibrio:**')
            ct1, ct2, ct3 = st.columns(3)
            ct1.metric('50% del recorrido', f"{ou['t50']:.0f} ruedas")
            ct2.metric('75% del recorrido', f"{ou['t75']:.0f} ruedas")
            ct3.metric('95% del recorrido', f"{ou['t95']:.0f} ruedas")

            st.markdown('**Probabilidad aproximada de que el z-score haya cruzado cero:**')
            cp1b, cp2b, cp3b = st.columns(3)
            cp1b.metric('En 20 ruedas', f"{ou['p20']*100:.0f}%")
            cp2b.metric('En 40 ruedas', f"{ou['p40']*100:.0f}%")
            cp3b.metric('En 80 ruedas', f"{ou['p80']*100:.0f}%")

            st.caption(
                '⚠️ Estimación basada en un ajuste Ornstein-Uhlenbeck sobre el spread histórico '
                '(θ derivado del half-life, σ vía AR(1) sobre el spread). La probabilidad de cruce es '
                'una aproximación direccional por horizonte, no una probabilidad exacta de primer '
                'cruce (first-passage time). No es asesoramiento financiero.'
            )

        # ── Señal actual ─────────────────────────────────────────────
        if not stats.is_cointegrated or not stats.adf_is_stationary:
            st.markdown(f"""
            <div class="interp-card">
              <div class="interp-header">📍 Señal actual — {ticker_a}/{ticker_b}</div>
              ❌ Sin señal<br>
              <span style="color:#6b7d9a;font-size:11px">
                Motivo: el spread no cumple los requisitos estadísticos mínimos (Engle-Granger
                y/o ADF) con este historial y significancia — no es estacionario, por lo que no
                hay base para asumir que va a revertir a la media.<br>
                No es asesoramiento financiero.
              </span>
            </div>
            """, unsafe_allow_html=True)
        else:
            señal_actual = signal.iloc[-1] if len(signal) else 0
            if señal_actual == 1:
                txt_señal = f'🟢 LONG SPREAD — Comprar {ticker_a}, Vender {ticker_b} (β={stats.hedge_ratio:.3f})'
            elif señal_actual == -1:
                txt_señal = f'🔴 SHORT SPREAD — Vender {ticker_a}, Comprar {ticker_b} (β={stats.hedge_ratio:.3f})'
            else:
                txt_señal = '⚪ Sin posición — Z-Score dentro de rango neutral'

            st.markdown(f"""
            <div class="interp-card">
              <div class="interp-header">📍 Señal actual — {ticker_a}/{ticker_b}</div>
              {txt_señal}<br>
              <span style="color:#6b7d9a;font-size:11px">
                Half-life: {f'{stats.half_life:.1f} ruedas' if stats.half_life else 'no estimable'} ·
                No es asesoramiento financiero.
              </span>
            </div>
            """, unsafe_allow_html=True)

        chips_navegacion([(ticker_a, ticker_a), (ticker_b, ticker_b)], 'coint_par')

    # ══════════════════════════════════════════════════════════════
    #  TAB 2 — Escaneo de universo: sectores predefinidos + métricas OU
    # ══════════════════════════════════════════════════════════════
    with tab_universo:
        st.caption(
            'Elegí un sector/grupo predefinido para autocompletar los tickers, o cargalos a mano. '
            'El motor testea TODAS las combinaciones de a pares, ordenando por p-value de '
            'Engle-Granger (más cointegrados primero).'
        )

        cs1, cs2 = st.columns([3, 1])
        with cs1:
            sector_sel = st.selectbox(
                'Cargar desde sector/grupo',
                ['— Selección manual —'] + sorted(PARES_SECTORES.keys()),
                key='coint_u_sector_sel',
            )
        with cs2:
            st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)
            cargar_sector = st.button('⬇ Cargar tickers', key='coint_u_cargar_sector')

        if cargar_sector and sector_sel != '— Selección manual —':
            tickers_del_sector = sorted(set(PARES_SECTORES[sector_sel]['tickers'].values()))
            st.session_state['coint_universo_txt'] = ', '.join(tickers_del_sector)
            st.rerun()

        tickers_txt = st.text_area(
            'Tickers (separados por coma)',
            value=st.session_state.get('coint_universo_txt', 'GGAL, BMA, SUPV, BBAR'),
            key='coint_universo_txt', height=70,
        )
        cu1, cu2, cu3 = st.columns(3)
        with cu1:
            periodo_u = st.selectbox('Historial', ['1y', '2y', '5y'], index=1, key='coint_u_periodo')
        with cu2:
            sig_u = st.selectbox('Significancia', [0.01, 0.05, 0.10], index=1, key='coint_u_sig')
        with cu3:
            z_win_u = st.slider('Ventana Z-Score', 10, 100, 30, 5, key='coint_u_zwin')

        tickers_lista = sorted(set(t.strip().upper() for t in tickers_txt.split(',') if t.strip()))
        n_combos = len(list(combinations(tickers_lista, 2))) if len(tickers_lista) >= 2 else 0

        if len(tickers_lista) < 2:
            st.info('Ingresá al menos 2 tickers o cargá un sector.')
            return
        if n_combos > 45:
            st.warning(f'⚠️ {n_combos} combinaciones — puede tardar. Con muchos tickers considerá menos activos.')

        if st.button('▶ Escanear universo', key='coint_u_run', type='primary'):
            st.session_state['coint_u_run_flag'] = True
        if not st.session_state.get('coint_u_run_flag'):
            return

        def _descargar_para_universo(tk):
            df = descargar_datos(tk, periodo_u)
            cl = get_close_series(df) if df is not None else None
            return tk, cl

        with st.spinner(f'Descargando {len(tickers_lista)} activos...'):
            precios = {}
            with ThreadPoolExecutor(max_workers=8) as ex:
                for tk, cl in ex.map(_descargar_para_universo, tickers_lista):
                    if cl is not None and len(cl) >= 60:
                        precios[tk] = cl

        faltantes = [t for t in tickers_lista if t not in precios]
        if faltantes:
            st.warning(f"Sin datos suficientes para: {', '.join(faltantes)}. Se excluyen del escaneo.")

        if len(precios) < 2:
            st.error('No hay suficientes activos con historial válido para escanear.')
            return

        price_df = pd.DataFrame(precios).dropna()

        with st.spinner(f'Testeando {len(list(combinations(price_df.columns, 2)))} combinaciones...'):
            df_scan = scan_universe(price_df, significance=sig_u, zscore_window=z_win_u)

        if df_scan.empty:
            st.error('No se pudo calcular ningún par (verificá el historial común entre activos).')
            return

        # ── Métricas OU extendidas por par (θ, σ, percentiles, probabilidad) ──
        def _fila_ou(row):
            vacio = pd.Series({k: np.nan for k in
                                ['theta', 'sigma_eq', 't50', 't75', 't95', 'p20', 'p40', 'p80']})
            hedge, half_life, current_z = row['hedge_ratio'], row['half_life'], row['current_zscore']
            if pd.isna(hedge) or pd.isna(half_life) or half_life <= 0 or pd.isna(current_z):
                return vacio
            a, b = row['asset_a'], row['asset_b']
            cl_a, cl_b = price_df[a], price_df[b]
            intercept = float(cl_a.mean() - hedge * cl_b.mean())  # exacto si hedge_ratio es la pendiente OLS
            spread_par = calculate_spread(cl_a, cl_b, hedge, intercept)
            ou = _ou_extended_stats(spread_par, current_z, half_life)
            return pd.Series(ou) if ou is not None else vacio

        with st.spinner('Calculando dinámica de reversión (θ, σ, convergencia) por par...'):
            ou_cols = df_scan.apply(_fila_ou, axis=1)
        df_scan = pd.concat([df_scan, ou_cols], axis=1)

        n_coint = int(df_scan['is_cointegrated'].sum())
        kpi_cards_4([
            ('Pares testeados', str(len(df_scan)), f'{len(price_df.columns)} activos', '#3a7bd5'),
            ('✓ Cointegrados', str(n_coint), f'p < {sig_u}', '#3fb950'),
            ('Mejor p-value', f"{df_scan['pvalue'].min():.4f}",
             f"{df_scan.iloc[0]['asset_a']}/{df_scan.iloc[0]['asset_b']}", '#e3b341'),
            ('Hurst prom. (cointegrados)',
             f"{df_scan[df_scan['is_cointegrated']]['hurst'].mean():.3f}" if n_coint else 'N/A',
             'H<0.5 = mean-reverting', '#7ee787'),
        ])

        with st.expander('📖 ¿Cómo se interpreta cada columna?', expanded=False):
            st.markdown("""
**p-value EG / Cointegrado / ADF Estac.:** ver test de Engle-Granger y ADF — un par sólido
debería tener p-value bajo y ADF estacionario a la vez.

**Hedge Ratio / Half-Life / Hurst:** ver explicación en la pestaña "Par puntual".

**θ (theta):** velocidad de reversión del spread, derivada del half-life (θ = ln(2)/half-life).

**σ eq.:** dispersión del spread alrededor de su equilibrio (AR(1) sobre el spread histórico
del par). A igual half-life, un σ más alto implica un spread más ruidoso/volátil.

**T 50%/75%/95%:** ruedas esperadas para recorrer ese % del camino hacia el equilibrio.

**Prob. 20/40/80r:** probabilidad *aproximada* (no first-passage-time exacta) de que el
z-score del par haya cruzado cero en ese horizonte. No es asesoramiento financiero.
            """)

        df_show = df_scan.copy()
        df_show['pvalue'] = df_show['pvalue'].round(4)
        df_show['hedge_ratio'] = df_show['hedge_ratio'].round(4)
        df_show['half_life'] = df_show['half_life'].round(1)
        df_show['hurst'] = df_show['hurst'].round(3)
        df_show['current_zscore'] = df_show['current_zscore'].round(2)
        df_show['theta'] = df_show['theta'].round(4)
        df_show['sigma_eq'] = df_show['sigma_eq'].round(4)
        df_show['t50'] = df_show['t50'].round(0)
        df_show['t75'] = df_show['t75'].round(0)
        df_show['t95'] = df_show['t95'].round(0)
        df_show['p20'] = (df_show['p20'] * 100).round(0)
        df_show['p40'] = (df_show['p40'] * 100).round(0)
        df_show['p80'] = (df_show['p80'] * 100).round(0)

        cols_mostrar = ['asset_a', 'asset_b', 'pvalue', 'is_cointegrated', 'hedge_ratio',
                         'half_life', 'hurst', 'adf_is_stationary', 'current_zscore',
                         'theta', 'sigma_eq', 't50', 't75', 't95', 'p20', 'p40', 'p80']
        df_show = df_show[cols_mostrar]
        df_show.columns = ['Activo A', 'Activo B', 'p-value EG', 'Cointegrado', 'Hedge Ratio',
                            'Half-Life', 'Hurst', 'ADF Estac.', 'Z actual',
                            'θ', 'σ eq.', 'T 50%', 'T 75%', 'T 95%',
                            'Prob. 20r', 'Prob. 40r', 'Prob. 80r']

        def _color_coint(val):
            return 'color:#3fb950;font-weight:700' if val else 'color:#f85149'

        _map = 'map' if hasattr(df_show.style, 'map') else 'applymap'
        styled = (df_show.style
                  .pipe(lambda s: getattr(s, _map)(_color_coint, subset=['Cointegrado', 'ADF Estac.']))
                  .set_properties(**{'background-color': '#0d1117', 'color': '#e6edf3', 'border': '1px solid #21262d'})
                  .set_table_styles([
                      {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', '#e6edf3'),
                          ('font-weight', '700'), ('text-align', 'center'),
                          ('border-bottom', '2px solid #bc8cff'), ('font-size', '11px')]},
                      {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]},
                  ]))
        st.dataframe(styled, use_container_width=True, height=min(600, max(150, len(df_show) * 35 + 45)))
        st.caption(
            '💡 Elegí un par de la tabla y andá a la pestaña "Par puntual" para ver el gráfico '
            'completo y el detalle de la dinámica de reversión.'
        )

    # ══════════════════════════════════════════════════════════════
    #  TAB 3 — Regímenes con Hidden Markov Model
    # ══════════════════════════════════════════════════════════════
    with tab_hmm:
        st.markdown("""
        <div style="background:#0d1117;border:1px solid #21262d;border-left:3px solid #bc8cff;
             border-radius:8px;padding:16px 20px;margin-bottom:18px;font-size:12px;
             color:#b0bcd0;line-height:1.7">
        <b style="color:#e6edf3">¿Qué es esto?</b> Un Hidden Markov Model (HMM) es un modelo
        estadístico que asume que el spread del par se mueve entre unos pocos "estados ocultos"
        (regímenes) — por ejemplo un régimen <b>calmo</b>, donde el spread revierte a la media
        de forma predecible, y un régimen <b>volátil/de ruptura</b>, donde se aleja y el modelo
        de reversión (Engle-Granger, OU) deja de ser confiable. El modelo no ve directamente en
        qué régimen estás — lo infiere a partir de cómo se comporta la serie — y te devuelve,
        para cada rueda, la probabilidad de estar en cada régimen. Es un motor separado y
        adicional a la cointegración: te sirve para saber <i>cuándo confiar</i> en la señal de
        pairs trading y cuándo no.
        </div>
        """, unsafe_allow_html=True)

        if not _HMM_DISPONIBLE:
            st.error(
                '⚠️ Falta instalar la librería **hmmlearn** para usar esta pestaña. '
                'Agregá `hmmlearn` a tu requirements.txt (`pip install hmmlearn`) y redeployá.'
            )
            return

        # Precarga (una sola vez) los tickers elegidos en "Par puntual", si existen
        if 'coint_hmm_a' not in st.session_state and st.session_state.get('coint_a'):
            st.session_state['coint_hmm_a'] = st.session_state['coint_a']
        if 'coint_hmm_b' not in st.session_state and st.session_state.get('coint_b'):
            st.session_state['coint_hmm_b'] = st.session_state['coint_b']

        ch1, ch2, ch3 = st.columns(3)
        with ch1:
            ticker_a_h = selector_ticker_autocomplete('coint_hmm_a', label='Activo A')
        with ch2:
            ticker_b_h = selector_ticker_autocomplete('coint_hmm_b', label='Activo B')
        with ch3:
            periodo_h = st.selectbox('Historial', ['1y', '2y', '5y'], index=1, key='coint_hmm_periodo')

        ch4, ch5, ch6 = st.columns(3)
        with ch4:
            n_states = st.selectbox('Cantidad de regímenes', [2, 3], index=0, key='coint_hmm_nstates')
        with ch5:
            feature_sel = st.selectbox(
                'Sobre qué serie corre el HMM',
                ['Z-Score del spread', 'Variación diaria del spread'],
                index=0, key='coint_hmm_feature',
            )
        with ch6:
            z_window_h = st.slider('Ventana Z-Score', 10, 100, 30, 5, key='coint_hmm_zwin')

        if not ticker_a_h or not ticker_b_h or ticker_a_h == ticker_b_h:
            st.info('Elegí dos activos distintos (o corré primero "Par puntual" para autocompletar).')
            return

        if st.button('▶ Detectar regímenes', key='coint_hmm_run', type='primary'):
            st.session_state['coint_hmm_run_flag'] = True

        if not st.session_state.get('coint_hmm_run_flag'):
            return

        with st.spinner(f'Descargando {ticker_a_h} / {ticker_b_h}...'):
            df_a_h = descargar_datos(ticker_a_h, periodo_h)
            df_b_h = descargar_datos(ticker_b_h, periodo_h)

        if df_a_h is None or df_b_h is None:
            st.error('No se pudieron descargar precios para uno o ambos activos.')
            return

        cl_a_h = get_close_series(df_a_h)
        cl_b_h = get_close_series(df_b_h)
        if cl_a_h is None or cl_b_h is None or len(cl_a_h) < 80 or len(cl_b_h) < 80:
            st.error('Historial insuficiente (mínimo ~80 ruedas) para ajustar el HMM.')
            return

        stats_h = analyze_pair(cl_a_h, cl_b_h, ticker_a_h, ticker_b_h,
                                zscore_window=z_window_h, significance=0.05)
        spread_h = calculate_spread(cl_a_h, cl_b_h, stats_h.hedge_ratio, stats_h.intercept)
        zscore_h = calculate_zscore(spread_h, window=z_window_h)

        if feature_sel == 'Z-Score del spread':
            feature_series = zscore_h
            feature_label = 'Z-Score del spread'
        else:
            feature_series = spread_h.diff()
            feature_label = 'Δ Spread diario'

        with st.spinner(f'Ajustando HMM de {n_states} regímenes...'):
            hmm_res = _fit_hmm_regimenes(feature_series, n_states=n_states)

        if hmm_res is None:
            st.error('No se pudo ajustar el HMM (historial insuficiente tras descartar NaNs).')
            return

        etiquetas = _etiquetas_regimen(hmm_res['means'], hmm_res['stds'])
        regimen_actual = etiquetas.get(hmm_res['current_state'], f"Régimen {hmm_res['current_state']}")
        duracion_actual = hmm_res['expected_duration'][hmm_res['current_state']]

        kpi_cards_4([
            ('Régimen actual', regimen_actual, f"{ticker_a_h}/{ticker_b_h}", '#3a7bd5'),
            ('Confianza del régimen', f"{hmm_res['current_state_prob']*100:.0f}%",
             'Probabilidad posterior', '#3fb950'),
            ('Duración esperada', f"{duracion_actual:.1f} ruedas",
             'De permanencia en este régimen', '#e3b341'),
            ('Prob. de quedarse', f"{hmm_res['stay_prob'][hmm_res['current_state']]*100:.0f}%",
             'Por rueda (diagonal transición)', '#7ee787'),
        ])

        st.plotly_chart(
            _fig_hmm_regimenes(feature_series, hmm_res, etiquetas, palette, feature_label),
            use_container_width=True, config=PLOTLY_CONFIG, key='coint_hmm_fig',
        )

        st.markdown('#### 📊 Caracterización de cada régimen')
        filas_reg = []
        for idx in range(n_states):
            filas_reg.append({
                'Régimen': etiquetas.get(idx, f'Régimen {idx}'),
                f'Media ({feature_label})': round(float(hmm_res['means'][idx]), 4),
                'Desvío': round(float(hmm_res['stds'][idx]), 4),
                'Prob. de quedarse (por rueda)': f"{hmm_res['stay_prob'][idx]*100:.1f}%",
                'Duración esperada (ruedas)': round(float(hmm_res['expected_duration'][idx]), 1),
            })
        df_regimenes = pd.DataFrame(filas_reg)
        st.dataframe(df_regimenes, use_container_width=True, hide_index=True)

        st.markdown('#### 🔀 Matriz de transición')
        df_trans = pd.DataFrame(
            hmm_res['trans_mat'],
            index=[etiquetas.get(i, f'Régimen {i}') for i in range(n_states)],
            columns=[etiquetas.get(i, f'Régimen {i}') for i in range(n_states)],
        ).round(3)
        st.dataframe(df_trans, use_container_width=True)
        st.caption(
            'Fila = régimen actual, columna = régimen siguiente. Cada valor es la probabilidad '
            'de pasar de un régimen a otro en la próxima rueda.'
        )

        if hmm_res['current_state'] == int(np.argmin(np.abs(hmm_res['means']) + hmm_res['stds'])):
            st.success(
                f'✅ El par está en el régimen más calmo — mayor confianza en las señales de '
                f'cointegración/OU de las otras pestañas.'
            )
        else:
            st.warning(
                '⚠️ El par está en un régimen más disperso/volátil — tratá con cautela las '
                'señales de reversión a la media hasta que el HMM marque vuelta al régimen calmo. '
                'No es asesoramiento financiero.'
            )

        with st.expander('📖 ¿Cómo se calcula esto?', expanded=False):
            st.markdown("""
Se ajusta un **Gaussian HMM** (vía `hmmlearn`) sobre la serie elegida (Z-Score del spread o su
variación diaria). El modelo estima, para `n_states` regímenes:

- Una **media** y **desvío** por régimen (qué tan disperso es el spread en ese estado).
- Una **matriz de transición**: probabilidad de pasar de un régimen a otro rueda a rueda.
- El **régimen más probable en cada rueda** (algoritmo de Viterbi) y su **probabilidad posterior**
  (algoritmo forward-backward).

Los regímenes se etiquetan automáticamente de "más calmo" a "más volátil" según |media| + desvío
— el modelo en sí no sabe qué régimen es cuál, eso es una interpretación posterior. Con pocos
datos o series muy ruidosas el ajuste puede ser inestable; usalo como complemento de la
cointegración y la dinámica OU, no como señal aislada. No es asesoramiento financiero.
            """)
