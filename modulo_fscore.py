# ==============================================================
#  MÓDULO F-SCORE (PIOTROSKI) — Streamlit
#  Convertido desde el script de Google Colab (ipywidgets) al
#  mismo patrón que el resto de los módulos de Capital+
#  (modulo_senales_trading.py, modulo_promediador.py, etc.):
#  una función `modulo_fscore()` autocontenida que se importa y
#  se llama desde app.py, sin más dependencias que streamlit,
#  pandas, numpy y yfinance.
#
#  USO DESDE app.py:
#      from modulo_fscore import modulo_fscore
#      ...
#      elif MODULO == 'fscore':
#          if TIENE_ACCESO_PRO:
#              modulo_fscore()
#          else:
#              _mostrar_bloqueo_pro('F-Score (Piotroski)')
#
#  Y agregar 'fscore' a los mapas de navegación (_TRADING_MAP o
#  donde prefieras colgarlo), a MODULOS_SOLO_PRO si querés que
#  sea Pro, y a `titulos` / `badge_map` para el page header.
#  Ver bloque comentado al final de este archivo con el snippet
#  completo de integración.
#
#  CAMBIOS respecto al script de Colab:
#   - Los checkboxes de ipywidgets se reemplazan por un
#     st.multiselect + checkbox "Universo completo" (equivalente
#     funcional, pero nativo de Streamlit).
#   - La descarga secuencial con prints se reemplaza por
#     ThreadPoolExecutor (misma lógica de paralelismo que el
#     resto de la app) + una barra de progreso st.progress.
#   - El resultado se cachea con st.cache_data (TTL 1h) por
#     combinación de sectores elegidos, para no volver a pegarle
#     a Yahoo Finance en cada rerun de Streamlit.
#   - Se agrega estilo de tabla (fondo oscuro, resaltado de
#     F-Score) igual al de las demás tablas de la app, un botón
#     de descarga CSV y tarjetas KPI de resumen.
#   - La lógica de cálculo del F-Score (calculate_fscore) es la
#     misma que en el script original — no se tocó el criterio
#     financiero, solo el envoltorio de ejecución/UI.
# ==============================================================

import time
import random
import datetime as dt

import numpy as np
import pandas as pd
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------------------------------

FSC_MIN_CRITERIOS_VALIDOS = 6
FSC_UMBRAL_HISTORIAL_ANIOS = 4.5
FSC_MAX_REINTENTOS = 3
FSC_SLEEP_ENTRE_REQUESTS = (0.4, 0.9)   # más corto que en Colab: acá corre en paralelo
FSC_TOP_N_DEFAULT = 15

# ---------------------------------------------------------------------------
# UNIVERSO DE ACTIVOS POR INDUSTRIA
#  (mismo universo que el script de Colab; prefijado FSC_ para no
#  colisionar con ACCIONES_POR_INDUSTRIA de app.py si en algún
#  momento se importan ambos módulos en el mismo namespace)
# ---------------------------------------------------------------------------

FSC_ACCIONES_POR_INDUSTRIA = {
    'Semiconductores':    ['NVDA','AMD','AVGO','TSM','ASML','QCOM','TXN','ADI','NXPI','MCHP','MRVL','ON','MU','INTC','ARM','GFS','STM','UMC','SNDK','MPWR','SYNA','QRVO','CRUS','LSCC','DIOD','RMBS','CEVA','AEHR','ALAB','ACLS','AMAT','LRCX','KLAC','TER','ONTO','UCTT','FORM','KLIC','CAMT','COHR','ENTG','SMTC','MTSI','POWI','VECO','HIMX','SIMO','INDI','ICHR'],
    'Software':           ['MSFT','ORCL','CRM','ADBE','SAP','NOW','INTU','WDAY','SNOW','PLTR','TEAM','HUBS','DOCU','MDB','DDOG','ESTC','BOX','ASAN','SMAR','PATH','PAYC','PAYX','TYL','PTC','ADSK','GWRE','MANH','PEGA','APPF','NCNO','QTWO','SPSC','WK','FIVN','BILL','DUOL','GTLB','BL','CVLT','PD','DBX','PCOR','RELY','MNDY','TWLO','FRSH'],
    'Ciberseguridad':     ['CRWD','PANW','ZS','FTNT','OKTA','QLYS','TENB','RPD','VRNS','NET','CHKP','GEN','AKAM','CSCO','FFIV','EXTR','RDWR','BB','OSIS','TLS','S','NABL','MSI','LDOS','LHX','SAIC','CACI','MRCY','ANET','VRSN','DOCN','BLZE','AI','IBM'],
    'Cloud/AI':           ['MSFT','AMZN','GOOGL','META','ORCL','IBM','SNOW','MDB','DDOG','NET','PLTR','AI','CFLT','ESTC','SMCI','DELL','NVDA','AMD','CRM','SAP','NOW','INTU','ADBE','PATH','AKAM','GTLB','APP','ANET','HPE','NTAP','PSTG','BOX','ASAN','ARM','TSM','AVGO','COHR','VRT','EQIX','DLR','CIEN','SNPS','CDNS','MU','SNDK','WDC','CRWV','DOCN','FSLY','RBRK'],
    'Hardware/Equipos':   ['AAPL','DELL','HPE','HPQ','SMCI','CSCO','ANET','NTAP','PSTG','STX','WDC','SNDK','GLW','LOGI','JNPR','CIEN','KEYS','ZBRA','FLEX','SANM','ARW','JBL','APH','TEL','PLXS','FN','COMM','CRDO','LITE','COHR','IPGP','VSH','TTMI','KLIC','CAMT','AEIS','MTSI','OLED','VRT','CDNS','SNPS','TER','ENTG','RMBS','SIMO','HIMX','AZTA','SMTC','FORM'],
    'Fintech':            ['XYZ','PYPL','AFRM','SOFI','UPST','LC','ENVA','NU','STNE','PAGS','DLO','PAYO','MQ','FOUR','COIN','HOOD','GPN','FI','FIS','JKHY','EEFT','PAY','FLT','WU','NVEI','PSFE','BILL','MARA','RIOT','CIFR','CLSK','IREN','BTDR','CORZ','GLXY','BMNR','HUT'],
    'Biotecnología':      ['AMGN','REGN','VRTX','GILD','BIIB','MRNA','BNTX','ALNY','INCY','EXEL','NBIX','HALO','IONS','LEGN','SRPT','CRSP','NTLA','BEAM','EDIT','RXRX','RNA','DNLI','ADPT','XENE','SANA','VERV','ARWR','FOLD','BMRN','TECH','ABCL','NTRA','GH','CDNA','PACB','TWST','ILMN','RARE','ACAD','KYMR','IMVT','APLS','RVMD','MRUS','AUTL','BLUE','KROS','XNCR'],
    'Farmacéuticas':      ['LLY','JNJ','PFE','MRK','ABBV','BMY','AZN','NVO','NVS','SNY','GSK','TAK','TEVA','VTRS','OGN','BHC','RDY','ZTS','ELV','CVS','HIMS','SUPN','ITCI','ACAD','ARRY','CPRX','BCRX','AMRX','PRGO','AMPH','ANIP','COLL','KNSA','MYOV','NGM','TVTX','XERS','ZYME','SLNO','ADMA','PTGX','ARDX','CRNX','MNKD','HROW','ETON'],
    'Equipos Médicos':    ['ISRG','ABT','SYK','BSX','MDT','EW','ZBH','BDX','BAX','HOLX','DXCM','PODD','MASI','RMD','STE','TFX','ICUI','HAE','OMCL','PEN','GKOS','INSP','NVCR','ALGN','XRAY','SEM','LIVN','IRTC','TMDX','LNTH','NEOG','OSUR','AXNX','SIBN','NARI','OFIX','AVNS','AORT','PHG','GEHC','SOLV','STER','MMSI','ENVX','ATRC','OM'],
    'Servicios de Salud': ['UNH','ELV','CI','HUM','CVS','CNC','MOH','OSCR','DVA','HCA','UHS','THC','EHC','ACHC','SEM','LFST','PGNY','DOCS','AMED','ENSG','CHE','PNTG','FMS','OPCH','ADUS','SGRY','BKD','PACS','GH','DGX','LH','NEO','MEDP','IQV','ICON','SYNH','CRL','CTLT','TDOC','VEEV','EVH','AGL','ALHC','PRVA','ACCD','SHC','HIMS','LFMD'],
    'Bancos':             ['JPM','BAC','WFC','C','GS','MS','USB','PNC','TFC','COF','BK','STT','MTB','FITB','HBAN','RF','CFG','KEY','CMA','ZION','FHN','WTFC','EWBC','ONB','SNV','BPOP','FULT','FFIN','CADE','UBSI','ASB','OZK','PNFP','WBS','HOMB','BKU','SBSI','IBOC','TCBI','COLB','WAL','FIBK','FCNCA','CVBF','CATY','BANF','NBHC','GBCI','SFNC','FNB'],
    'Seguros':            ['BRK-B','PGR','CB','TRV','ALL','AFL','MET','PRU','AIG','HIG','CINF','WRB','RGA','LNC','GL','UNM','EG','MKL','BRO','AON','MMC','AJG','WTW','ACGL','RLI','ORI','KNSL','THG','AXS','RE','PFG','VOYA','SLF','MFC','EQH','AMP','FNF','FAF','AIZ','CNO','PIPR','JRVR','UFCS','NMIH','ESNT','MTG','RDN','HCI','TRUP','ROOT'],
    'Mercados Capitales': ['BX','KKR','APO','ARES','CG','OWL','BAM','BN','SCHW','IBKR','CME','ICE','NDAQ','MKTX','MS','GS','RJF','EVR','LAZ','PIPR','SF','LPLA','HOOD','COIN','SEIC','BEN','TROW','BLK','IVZ','AMG','JHG','PFG','CNS','PJT','HLI','TREE','OPY','VIRT','XP','STNE','NMR','DB','UBS'],
    'Petróleo Integrado': ['XOM','CVX','COP','EOG','OXY','DVN','MRO','APA','FANG','HES','CTRA','EQT','AR','RRC','CNX','CIVI','SM','MTDR','PR','MPC','PSX','VLO','PBF','DK','SUN','MUSA','SLB','HAL','BKR','NOV','CHX','LBRT','NBR','PTEN','HP','WTTR','TDW','RIG','VAL','PBR','SHEL','BP','TTE','EQNR','ENI','YPF','VIST','EC'],
    'Energía Renovable':  ['NEE','BEP','BEPC','CWEN','NEP','AES','ORA','AY','ENPH','FSLR','SEDG','RUN','ARRY','NXT','SHLS','FLNC','STEM','BE','PLUG','GEV','VRT','CSIQ','JKS','MAXN','NOVA','SPWR','AMRC','HASI','RNW','BLDP','HYLN','EVGO','CHPT','FREY','SES','EOSE','ENVX','SLDP','QS','MVST','LICY','LAC','ALTM','PLL'],
    'Gas Natural':        ['LNG','EQT','AR','RRC','CNX','KMI','WMB','OKE','TRGP','ET','EPD','MPLX','PAA','AM','DTM','HESM','MGY','CRK','GPOR','CTRA','OVV','SM','CIVI','EXE','NFG','SWX','ATO','NWN','UGI','NI','OGS','POR','SJI','SR','CPK','ENLC','WES','PAGP','GLNG','FLNG','TGS','ENB','TRP','KNTK','HUN'],
    'Energía Solar':      ['FSLR','ENPH','SEDG','RUN','ARRY','NXT','SHLS','CSIQ','JKS','MAXN','NOVA','SPWR','BE','PLUG','FLNC','STEM','AMRC','ORA','NEE','CWEN','BEP','BEPC','NEP','AES','GEV','VRT','HASI','RNW','BLDP','CHPT','EVGO','EOSE','FREY','SES','SLDP','QS','ENVX','MVST'],
    'Aeroespacial':       ['BA','RTX','LMT','NOC','GD','HII','TDG','HEI','CW','TXT','KTOS','AVAV','BWXT','LHX','LDOS','MRCY','OSIS','SPR','HON','AER','IRDM','MAXR','RKLB','SPCE','ASTS','DRS','VSEC','ATRO','HXL','KAMN','TGI','MOG-A','DCO','ESLT','ARL','AIM','JOBY','ACHR','EH','NNDM','PL'],
    'Transporte':         ['UPS','FDX','UNP','CSX','NSC','JBHT','ODFL','XPO','CHRW','EXPD','KEX','MATX','ZIM','DAC','SBLK','GOGL','GNK','TRTN','SFL','CAI','NM','DSX','LPG','STNG','INSW','TNK','EURN','FRO'],
    'Construcción':       ['CAT','DE','EMR','ETN','HON','GE','ROK','PH','ITW','MMM','VMC','MLM','EXP','BLDR','NVR','DHI','LEN','PHM','KBH','TOL','JCI','TT','URI','PWR','FIX','MTZ','ACM','FLR','HUBG','MAS'],
    'Defensa':            ['LMT','RTX','NOC','GD','HII','BA','TDG','HEI','CW','TXT','KTOS','AVAV','BWXT','LHX','LDOS','MRCY','OSIS','CACI','SAIC'],
    'Retail':             ['AMZN','WMT','TGT','COST','HD','LOW','TJX','ROST','DG','DLTR','BBY','KR','BJ','WBA','CVS','ULTA','M','KSS','JWN','GPS','BURL','FIVE','WSM','RH','ORLY','AZO','AAP','TSCO','OLLI','FND','TPR','RL','NKE','DECK','CROX','LEVI','PVH','URBN','AEO'],
    'Autos':              ['TSLA','GM','F','TM','HMC','STLA','RIVN','LCID','NIO','XPEV','LI','RACE','APTV','BWA','VC','GT','LEA','ALV','HOG','PII','THO','MBLY','ZK','XPEL'],
    'Hotelería/Viajes':   ['MAR','HLT','H','IHG','ABNB','BKNG','EXPE','RCL','CCL','NCLH','TRIP','DESP','TCOM','LVS','MGM','WYNN','CZR','SIX','PLAY','DKNG','BALY','VAC','WH','HGV','SVC','PK'],
    'E-commerce':         ['AMZN','SHOP','ETSY','EBAY','MELI','SE','PDD','BABA','JD','CPNG','W','CVNA','OSTK','WISH','EXFY','GRPN','WIX','DOCN','FVRR','UPWK','RBLX','TTD','APP','NET','GTLB','FSLY','BIGC','BOX'],
    'Alimentos':          ['KO','PEP','MDLZ','KHC','GIS','CPB','SJM','K','KDP','HSY','TSN','HRL','ADM','BG','CHD','CLX','CAG','POST','MKC','EL','PG','UL','LANC','COKE','FLO','DAR','INGR','SMPL'],
    'Bebidas':            ['KO','PEP','MNST','STZ','BUD','TAP','DEO','KDP','CELH','FIZZ','PRMW','CCEP','FMX','SAM','BFB','WULF','COKE','VIV','BRBR','SPB','SOVO','REX','KOF','ABEV','CCU','COTY'],
    'Minería Oro':        ['NEM','GOLD','AEM','WPM','KGC','PAAS','AG','CDE','HL','SSRM','NGD','AUX','DRD','BTG','EGO','HMY','IAG','AU','SA','GFI','OR','FNV','RGLD','KNT','WDO','EQX','TGB','SILV','BVN','CGAU'],
    'Cobre/Metales':      ['FCX','SCCO','TECK','HBM','NUE','STLD','CLF','AA','CDE','KGC','PAAS','AG','HL','WPM','AEM','NEM','GOLD','SSRM','NGD','ERO','LAC','ALB','PLL','MP','CRS','ATI','X'],
    'Químicos':           ['LIN','APD','DD','DOW','LYB','EMN','CE','IFF','PPG','SHW','ECL','ALB','FMC','CF','MOS','NTR','OLN','ASH','AVNT','HUN','X','BC','RPM','WLK','SXT','SCL','NEU','IOSP','CBT'],
    'Acero':              ['NUE','STLD','CLF','X','MT','RS','CMC','SID','GGB','TX','PKX','NWL','CRS','ATI','SCHN','ZEUS','NBR'],
    'Eléctricas':         ['NEE','DUK','SO','D','AEP','EXC','XEL','ED','ETR','PEG','PCG','PPL','FE','ES','EIX','AES','CNP','NI','ATO','LNT','WEC','CMS','DTE','SRE','EVRG','IDA','BEP','BEPC','NEP','ORA','UGI','BIP','BIPC','AVA','PNW','NRG'],
    'Agua':               ['AWK','WTRG','AWR','YORW','MSEX','SJW','CWCO','GWRS','ARTNA','PNW','CWT','WSO','AQUA','ECL','XYL','PUMP','GRC','MEG'],
    'REIT Comercial':     ['SPG','O','VICI','NNN','BXP','KIM','REG','MAC','PEAK','FRT','SLG','EPR','WPC','ARE','HST','PK','VNO','CUZ','HIW','KRC','DEI','BRX','ADC','STAG','PLD','EQIX','DLR','CONE','COR','AMT','CCI','SBAC','WY','IRM','GOOD','LAND'],
    'REIT Industrial':    ['PLD','AMT','CCI','DLR','EQIX','STAG','EGP','FR','REXR','TRNO','PLYM','LXP','COLD','ILPT','PSTL','IRM','CUBE','GOOD','O'],
    'REIT Residencial':   ['EQR','AVB','ESS','MAA','UDR','CPT','ELS','AIV','NXRT','INVH','IRT','AMH','BRG','SUI','UMH','AIRC','CUBE'],
    'Telecomunicaciones': ['T','VZ','TMUS','S','CHTR','CMCSA','LUMN','FYBR','VOD','BT','ORAN','TEF','TU','BCE','RCI','SKM','ZL','AMX','TIGO','TDS','ATUS','WOW','CNSL','QCOM','AMT','CCI','SBAC','WBD','NFLX','DIS'],
    'Internet':           ['GOOGL','META','NFLX','SNAP','PINS','RDDT','SPOT','ROKU','IAC','MTCH','BMBL','YELP','DASH','UBER','LYFT','SHOP','SE','MELI','ETSY','EBAY','BABA','JD','PDD','BIDU','NTES','WB','IQ','TME','WIX','RBLX','DUOL','TTD','PUBM','APP','NET','AKAM','DOCN','GTLB','BOX','ZI','YEXT','COUR','CHGG','RUM','VKTX','CRWV','FSLY','CFLT','DBX'],
    'Argentina':          ['GGAL','BMA','BBAR','SUPV','CEPU','YPF','PAM','TGS','CRESY','LOMA','VIST','IRCP','EDN','TRAN','IRS','DESP','GLOB','BIOX','MTR','AGRO','PGR','SBS'],
    'Brasil':             ['VALE','ITUB','PBR','BBD','ABEV','NU'],
    'China':              ['BABA','TCEHY','BIDU','JD','NIO','LI','XPEV','BYDDF','PDD','NTES'],
    'India':              ['INFY','WIT','HDB','IBN','VEDL','RDY','TTM'],
    'Europa Tecnología':  ['SAP','ASML','IFNNY','NXPI'],
    'Europa Finanzas':    ['HSBC','BBVA','SAN','DBK.DE','LLOY.L','UBS','ING'],
    'Agro/Fertilizantes': ['MOS','NTR','CF','ADM','BG','FMC','CTVA'],
    # 'Cripto (ETF/Coin)' queda excluida a propósito: sin balance sheet /
    # income statement, el F-Score no se puede calcular sobre estos activos.
}

_FSC_SECTORES_ORDENADOS = sorted(FSC_ACCIONES_POR_INDUSTRIA.keys())


# ---------------------------------------------------------------------------
# ARMADO DEL UNIVERSO SEGÚN SECTOR(ES) ELEGIDOS
# ---------------------------------------------------------------------------

def _fsc_construir_universo(sectores_elegidos):
    """sectores_elegidos: lista de nombres de industria (ya validados).
    Devuelve (ticker_list, ticker_a_sectores)."""
    ticker_a_sectores = {}
    for sector in sectores_elegidos:
        for ticker in FSC_ACCIONES_POR_INDUSTRIA[sector]:
            ticker_a_sectores.setdefault(ticker, []).append(sector)
    return list(ticker_a_sectores.keys()), ticker_a_sectores


# ---------------------------------------------------------------------------
# HELPERS ROBUSTOS PARA yfinance
# ---------------------------------------------------------------------------

def _fsc_pausa():
    time.sleep(random.uniform(*FSC_SLEEP_ENTRE_REQUESTS))


def _fsc_con_reintentos(func, *args, **kwargs):
    ultimo_error = None
    for intento in range(FSC_MAX_REINTENTOS):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            ultimo_error = e
            time.sleep(2 ** intento + random.uniform(0, 1))
    raise ultimo_error


def _fsc_safe_row(df, key, col_idx):
    if df is None or df.empty or key not in df.index:
        return None
    try:
        val = df.loc[key]
        if col_idx >= len(val):
            return None
        v = val.iloc[col_idx]
        return None if pd.isna(v) else v
    except Exception:
        return None


_FSC_ALIASES = {
    'Total Debt': ['Total Debt', 'Net Debt'],
    'Current Assets': ['Current Assets'],
    'Current Liabilities': ['Current Liabilities'],
    'Shares Outstanding': ['Ordinary Shares Number', 'Share Issued'],
    'Operating Cash Flow': ['Operating Cash Flow', 'Cash Flow From Continuing Operating Activities'],
}


def _fsc_get_alias(df, canonical_key, col_idx):
    for key in _FSC_ALIASES.get(canonical_key, [canonical_key]):
        val = _fsc_safe_row(df, key, col_idx)
        if val is not None:
            return val
    return None


# ---------------------------------------------------------------------------
# CÁLCULO DEL F-SCORE (tolerante a datos faltantes)
#  Misma lógica financiera que el script de Colab: 9 criterios de
#  Piotroski (los que se puedan calcular con lo que devuelve
#  yfinance), escalados a una nota sobre 9 según cuántos criterios
#  hayan podido evaluarse.
# ---------------------------------------------------------------------------

def _fsc_calculate(ticker, ticker_a_sectores):
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        income_statement = _fsc_con_reintentos(lambda: stock.financials)
        balance_sheet = _fsc_con_reintentos(lambda: stock.balance_sheet)
        cash_flow = _fsc_con_reintentos(lambda: stock.cashflow)
        _fsc_pausa()

        if income_statement is None or income_statement.empty or \
           balance_sheet is None or balance_sheet.empty or \
           cash_flow is None or cash_flow.empty:
            return None

        net_income_0 = _fsc_safe_row(income_statement, 'Net Income', 0)
        net_income_1 = _fsc_safe_row(income_statement, 'Net Income', 1)
        total_assets_0 = _fsc_safe_row(balance_sheet, 'Total Assets', 0)
        total_assets_1 = _fsc_safe_row(balance_sheet, 'Total Assets', 1)
        ocf_0 = _fsc_get_alias(cash_flow, 'Operating Cash Flow', 0)
        ocf_1 = _fsc_get_alias(cash_flow, 'Operating Cash Flow', 1)
        debt_0 = _fsc_get_alias(balance_sheet, 'Total Debt', 0)
        debt_1 = _fsc_get_alias(balance_sheet, 'Total Debt', 1)
        curr_assets_0 = _fsc_get_alias(balance_sheet, 'Current Assets', 0)
        curr_liab_0 = _fsc_get_alias(balance_sheet, 'Current Liabilities', 0)
        shares_0 = _fsc_get_alias(balance_sheet, 'Shares Outstanding', 0)
        shares_1 = _fsc_get_alias(balance_sheet, 'Shares Outstanding', 1)
        gross_profit_0 = _fsc_safe_row(income_statement, 'Gross Profit', 0)
        gross_profit_1 = _fsc_safe_row(income_statement, 'Gross Profit', 1)
        total_revenue_0 = _fsc_safe_row(income_statement, 'Total Revenue', 0)

        criterios = {}

        if net_income_0 is not None and net_income_1 is not None:
            criterios['net_income'] = net_income_0 >= net_income_1

        roa_0 = roa_1 = None
        if net_income_0 is not None and total_assets_0 and net_income_1 is not None and total_assets_1:
            roa_0 = net_income_0 / total_assets_0
            roa_1 = net_income_1 / total_assets_1
            criterios['roa'] = roa_0 >= roa_1

        if ocf_0 is not None and ocf_1 is not None:
            criterios['ocf_growth'] = ocf_0 >= ocf_1
        if ocf_0 is not None and net_income_0 is not None:
            criterios['ocf_vs_ni'] = ocf_0 > net_income_0

        if debt_0 is not None and debt_1 is not None:
            criterios['debt'] = debt_0 < debt_1

        current_ratio = None
        if curr_assets_0 is not None and curr_liab_0:
            current_ratio = curr_assets_0 / curr_liab_0
            criterios['current_ratio'] = current_ratio > 1

        if shares_0 is not None and shares_1 is not None:
            criterios['shares'] = shares_0 <= shares_1

        if gross_profit_0 is not None and gross_profit_1 is not None:
            criterios['gross_margin'] = gross_profit_0 >= gross_profit_1

        asset_turnover = None
        if total_revenue_0 is not None and total_assets_1:
            asset_turnover = total_revenue_0 / total_assets_1
            criterios['asset_turnover'] = asset_turnover >= 1

        if len(criterios) < FSC_MIN_CRITERIOS_VALIDOS:
            return None

        f_score = sum(criterios.values())
        f_score_escalado = round(f_score / len(criterios) * 9, 2)

        return {
            'Ticker': ticker,
            'Sectores': ', '.join(ticker_a_sectores.get(ticker, [])),
            'F-Score': f_score_escalado,
            'Criterios evaluados': len(criterios),
            'Net Income': net_income_0,
            'Last Year Net Income': net_income_1,
            'ROA': roa_0,
            'Last Year ROA': roa_1,
            'Operating Cash Flow': ocf_0,
            'Last Year Operating Cash Flow': ocf_1,
            'Total Debt': debt_0,
            'Last Year Total Debt': debt_1,
            'Current Ratio': current_ratio,
            'Shares Outstanding': shares_0,
            'Last Year Shares Outstanding': shares_1,
            'Gross Profit': gross_profit_0,
            'Last Year Gross Profit': gross_profit_1,
            'Asset Turnover': asset_turnover,
        }
    except Exception:
        return None

FSC_TTL_SEGUNDOS = 6 * 3600  # F-Score no cambia intra-día; 6h alcanza de sobra

def _fsc_supabase_leer(client, ticker):
    if client is None:
        return None, None
    try:
        res = (client.table('fscore_cache')
               .select('datos, actualizado_en')
               .eq('ticker', ticker).limit(1).execute())
        if res.data:
            return res.data[0]['datos'], res.data[0]['actualizado_en']
    except Exception:
        pass
    return None, None


def _fsc_supabase_guardar(client, ticker, datos):
    if client is None:
        return
    try:
        payload = {}
        for k, v in datos.items():
            if isinstance(v, float) and pd.isna(v):
                payload[k] = None
            elif isinstance(v, (np.floating,)):
                payload[k] = None if np.isnan(v) else float(v)
            elif isinstance(v, (np.integer,)):
                payload[k] = int(v)
            else:
                payload[k] = v
        client.table('fscore_cache').upsert({
            'ticker': ticker,
            'datos': payload,
            'actualizado_en': dt.datetime.now().isoformat(),
        }).execute()
    except Exception:
        pass


def _fsc_es_dato_fresco(ts_iso, ttl_segundos):
    if not ts_iso:
        return False
    try:
        ts = dt.datetime.fromisoformat(ts_iso.replace('Z', '+00:00'))
        ahora = dt.datetime.now(ts.tzinfo) if ts.tzinfo else dt.datetime.now()
        return (ahora - ts).total_seconds() < ttl_segundos
    except Exception:
        return False

def _fsc_validate_price_history(ticker, fecha_inicio, fecha_fin, umbral_ruedas):
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        hist = _fsc_con_reintentos(stock.history, start=fecha_inicio, end=fecha_fin)
        _fsc_pausa()
        return len(hist) >= umbral_ruedas
    except Exception:
        return False


def _fsc_procesar_ticker(client, ticker, ticker_a_sectores, fecha_inicio, fecha_fin, umbral_ruedas):
    """Caché compartido primero (Supabase, TTL 6h) -> cálculo en vivo si está
    vencido/no existe -> Supabase vencido como último respaldo si Yahoo falla."""
    datos_db, ts_db = _fsc_supabase_leer(client, ticker)

    if datos_db is not None and _fsc_es_dato_fresco(ts_db, FSC_TTL_SEGUNDOS):
        datos_db = dict(datos_db)
        datos_db['Sectores'] = ', '.join(ticker_a_sectores.get(ticker, [])) or datos_db.get('Sectores', '')
        return datos_db

    if not _fsc_validate_price_history(ticker, fecha_inicio, fecha_fin, umbral_ruedas):
        if datos_db is not None:
            datos_db = dict(datos_db)
            datos_db['Sectores'] = ', '.join(ticker_a_sectores.get(ticker, [])) or datos_db.get('Sectores', '')
            return datos_db
        return None

    resultado = _fsc_calculate(ticker, ticker_a_sectores)
    if resultado is not None:
        _fsc_supabase_guardar(client, ticker, resultado)
        return resultado

    if datos_db is not None:
        datos_db = dict(datos_db)
        datos_db['Sectores'] = ', '.join(ticker_a_sectores.get(ticker, [])) or datos_db.get('Sectores', '')
        return datos_db

    return None


# ---------------------------------------------------------------------------
# EJECUCIÓN CACHEADA
# ---------------------------------------------------------------------------

def _fsc_ejecutar_analisis(client, sectores_elegidos, max_workers=8):
    """Ya NO está cacheado con @st.cache_data — el caché real ahora vive en
    Supabase por ticker (compartido entre usuarios y entre combinaciones de
    sectores). Devuelve (lista_de_dicts, n_total, n_ok)."""
    ticker_list, ticker_a_sectores = _fsc_construir_universo(sectores_elegidos)

    fecha_fin = dt.date.today()
    fecha_inicio = fecha_fin - dt.timedelta(days=5 * 365)
    umbral_ruedas = int(252 * FSC_UMBRAL_HISTORIAL_ANIOS)

    resultados = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futuros = {
            ex.submit(_fsc_procesar_ticker, client, tk, ticker_a_sectores, fecha_inicio, fecha_fin, umbral_ruedas): tk
            for tk in ticker_list
        }
        for fut in as_completed(futuros):
            r = fut.result()
            if r:
                resultados.append(r)

    return resultados, len(ticker_list), len(resultados)


# ---------------------------------------------------------------------------
# ESTILO DE TABLA (mismo look & feel que el resto de la app)
# ---------------------------------------------------------------------------

def _fsc_color_fscore(val):
    try:
        v = float(val)
    except Exception:
        return ''
    if v <= 3:   return 'background-color:#2a0a0a;color:#f85149;font-weight:700'
    if v <= 5:   return 'background-color:#2a1a05;color:#f0883e;font-weight:700'
    if v <= 6.5: return 'background-color:#1e1a05;color:#e3b341;font-weight:700'
    if v <= 8:   return 'background-color:#081a0a;color:#7ee787;font-weight:700'
    return 'background-color:#051505;color:#3fb950;font-weight:700'


def _fsc_estilizar_tabla(df):
    _map = 'map' if hasattr(df.style, 'map') else 'applymap'
    styled = (
        df.style
        .pipe(lambda s: getattr(s, _map)(_fsc_color_fscore, subset=['F-Score']))
        .format({'F-Score': '{:.2f}'})
        .set_properties(**{'background-color': '#0d1117', 'color': '#e6edf3', 'border': '1px solid #21262d'})
        .set_table_styles([
            {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', '#e6edf3'),
                ('font-weight', '700'), ('text-align', 'center'),
                ('border-bottom', '2px solid #3a7bd5'), ('font-size', '11px')]},
            {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]},
        ])
    )
    return styled


def _fsc_kpi_cards_4(items):
    """Copia liviana del helper kpi_cards_4 de app.py, para que este
    módulo no dependa de ningún import cruzado. items = (label, value, sub, color)."""
    cols = st.columns(len(items))
    for col, (label, value, sub, color) in zip(cols, items):
        with col:
            st.markdown(
                f'<div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;'
                f'padding:16px 18px;position:relative;overflow:hidden">'
                f'<div style="position:absolute;top:0;left:0;width:100%;height:2px;'
                f'background:{color};border-radius:10px 10px 0 0"></div>'
                f'<div style="color:#f5f7fa;font-size:12px;font-weight:700;text-transform:uppercase;'
                f'letter-spacing:1px;margin-bottom:6px">{label}</div>'
                f'<div style="color:#e6edf3;font-size:22px;font-weight:700;letter-spacing:-0.5px;'
                f'font-family:\'JetBrains Mono\',monospace">{value}</div>'
                f'<div style="color:#f5f7fa;font-size:13px;margin-top:4px">{sub}</div></div>',
                unsafe_allow_html=True,
            )
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# RENDER — módulo Streamlit
# ---------------------------------------------------------------------------

def modulo_fscore(supabase=None):
    """Punto de entrada del módulo. Llamar desde app.py:
        from modulo_fscore import modulo_fscore
        modulo_fscore(supabase)
    Si no se pasa `supabase`, funciona igual pero sin caché compartido
    (solo memoria dentro del mismo cálculo, como antes).
    """
    st.markdown("""
    <div style="background:linear-gradient(135deg,#151d0d 0%,#0f2410 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #3fb950;
         border-radius:14px; padding:22px 28px; margin-bottom:20px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:4px">
        🧮 F-Score (Piotroski)
      </div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.6">
        Calcula el <b style="color:#e6edf3">F-Score de Piotroski</b> (0-9) para las empresas de los
        sectores que elijas: rentabilidad, apalancamiento/liquidez y eficiencia operativa,
        comparando el último ejercicio contra el anterior. Se excluyen cripto, forex y
        commodities porque no tienen balance sheet / income statement en Yahoo Finance.
      </div>
    </div>
    """, unsafe_allow_html=True)

    c1, c2 = st.columns([3, 1])
    with c1:
        sectores_sel = st.multiselect(
            'Sectores a analizar', _FSC_SECTORES_ORDENADOS,
            default=st.session_state.get('fsc_sectores_sel', _FSC_SECTORES_ORDENADOS[:1]),
            key='fsc_sectores_sel_widget',
            help='Podés elegir uno o varios sectores, o tildar "Universo completo" abajo.',
        )
        st.session_state['fsc_sectores_sel'] = sectores_sel
    with c2:
        universo_completo = st.checkbox('Universo completo', key='fsc_universo_completo',
                                         help='Analiza TODOS los sectores disponibles (puede tardar varios minutos).')

    cparam1, cparam2 = st.columns(2)
    with cparam1:
        top_n = st.slider('Top N a mostrar', 5, 50, FSC_TOP_N_DEFAULT, 1, key='fsc_top_n')
    with cparam2:
        max_workers = st.slider('Descargas en paralelo', 2, 16, 8, 1, key='fsc_max_workers',
                                 help='Más paralelismo = más rápido, pero mayor riesgo de rate-limit de Yahoo Finance.')

    sectores_a_usar = _FSC_SECTORES_ORDENADOS if universo_completo else sectores_sel

    if not sectores_a_usar:
        st.info('Elegí al menos un sector (o tildá "Universo completo") para poder ejecutar el análisis.')
        return

    n_tickers_estimado = len(_fsc_construir_universo(sectores_a_usar)[0])
    st.caption(f'Universo a analizar: ~{n_tickers_estimado} tickers en {len(sectores_a_usar)} sector(es).')

    correr = st.button('▶ Ejecutar F-Score', key='fsc_run', type='primary')

    if not correr and not st.session_state.get('fsc_run_flag'):
        st.markdown("""
        <div style='background:#0d1117;border:1px dashed #21262d;border-radius:10px;padding:40px;text-align:center'>
          <div style='font-size:40px;margin-bottom:12px'>🧮</div>
          <div style='color:#e6edf3;font-size:14px;font-weight:600;margin-bottom:6px'>F-Score (Piotroski)</div>
          <div style='color:#6b7d9a;font-size:12px'>Elegí sectores y presioná "Ejecutar F-Score" para calcular el ranking.</div>
        </div>
        """, unsafe_allow_html=True)
        return
    if correr:
        st.session_state['fsc_run_flag'] = True

    with st.spinner(f'Validando historial y calculando F-Score para ~{n_tickers_estimado} tickers...'):
        resultados, n_total, n_ok = _fsc_ejecutar_analisis(supabase, sectores_a_usar, max_workers=max_workers)

    if not resultados:
        st.error(
            'No se pudo calcular el F-Score para ningún ticker.\n\n'
            'Causas más probables: Yahoo Finance rate-limiteando las requests '
            '(probá con menos sectores o menos paralelismo), o falta de historial '
            'suficiente (se requieren ~4.5 años de precios) para los tickers elegidos.'
        )
        return

    df_fsc = pd.DataFrame(resultados).sort_values('F-Score', ascending=False).reset_index(drop=True)

    n_alto = int((df_fsc['F-Score'] >= 8).sum())
    n_medio = int(df_fsc['F-Score'].between(5, 7.99).sum())
    n_bajo = int((df_fsc['F-Score'] < 5).sum())
    _fsc_kpi_cards_4([
        ('Con F-Score calculado', f'{n_ok}/{n_total}', f'{len(sectores_a_usar)} sector(es)', '#3a7bd5'),
        ('🟢 F-Score alto (≥8)', str(n_alto), 'Calidad financiera fuerte', '#3fb950'),
        ('🟡 F-Score medio (5-8)', str(n_medio), 'Calidad mixta', '#e3b341'),
        ('🔴 F-Score bajo (<5)', str(n_bajo), 'Señales de alerta', '#f85149'),
    ])

    fc1, fc2 = st.columns(2)
    with fc1:
        sectores_disp_f = ['Todos'] + sectores_a_usar
        f_sector = st.selectbox('Filtrar por sector', sectores_disp_f, key='fsc_f_sector')
    with fc2:
        f_score_rng = st.slider('Rango F-Score', 0.0, 9.0, (0.0, 9.0), 0.5, key='fsc_f_score_rng')

    df_f = df_fsc.copy()
    if f_sector != 'Todos':
        df_f = df_f[df_f['Sectores'].str.contains(f_sector, regex=False)]
    df_f = df_f[df_f['F-Score'].between(*f_score_rng)]

    cols_mostrar = ['Ticker', 'Sectores', 'F-Score', 'Criterios evaluados', 'ROA', 'Current Ratio', 'Asset Turnover']
    df_show = df_f[cols_mostrar].copy()
    df_show['ROA'] = df_show['ROA'].apply(lambda v: f'{v*100:.1f}%' if pd.notna(v) else 'N/D')
    df_show['Current Ratio'] = df_show['Current Ratio'].apply(lambda v: f'{v:.2f}x' if pd.notna(v) else 'N/D')
    df_show['Asset Turnover'] = df_show['Asset Turnover'].apply(lambda v: f'{v:.2f}x' if pd.notna(v) else 'N/D')

    st.dataframe(_fsc_estilizar_tabla(df_show), use_container_width=True,
                 height=min(700, max(200, len(df_show) * 32 + 45)))
    st.caption(f'{len(df_show)} empresas mostradas de {len(df_fsc)} totales')

    st.markdown(f'### 🏆 Top {top_n} por F-Score')
    st.dataframe(_fsc_estilizar_tabla(df_show.head(top_n)), use_container_width=True,
                 height=min(600, top_n * 35 + 45))

    csv_bytes = df_fsc.to_csv(index=False).encode('utf-8')
    nombre_sectores = '_'.join(sectores_a_usar) if not universo_completo else 'universo_completo'
    nombre_archivo = f"f_score_{nombre_sectores}.csv".replace('/', '-').replace(' ', '_')[:120]
    st.download_button(
        '⬇️ Descargar CSV completo', data=csv_bytes, file_name=nombre_archivo,
        mime='text/csv', key='fsc_download',
    )


# ==============================================================
#  SNIPPET DE INTEGRACIÓN EN app.py (referencia, no se ejecuta)
# ==============================================================
#
# 1) Import, junto a los demás módulos:
#       from modulo_fscore import modulo_fscore
#
# 2) Mapa de navegación (por ejemplo, dentro de _TRADING_MAP o
#    _HERRAMIENTAS_MAP, junto al resto de las opciones):
#       '🧮 F-Score (Piotroski)': ('fscore', 'fscore'),
#
# 3) Si querés que sea exclusivo de Pro, agregar 'fscore' al set:
#       MODULOS_SOLO_PRO = {'optimizador', 'senales', 'pares', 'fscore'}
#
# 4) Título y badge para el page header:
#       titulos['fscore'] = ('F-Score (Piotroski)', '🧮',
#           'Calidad financiera 0-9 por sector — Piotroski Score')
#       badge_map['fscore'] = ('#3fb950', 'rgba(63,185,80,0.12)', 'F-SCORE')
#
# 5) Renderizado, junto a los otros `elif MODULO == '...':`:
#       elif MODULO == 'fscore':
#           if TIENE_ACCESO_PRO:
#               modulo_fscore(supabase)
#           else:
#               _mostrar_bloqueo_pro('F-Score (Piotroski)')
# ==============================================================
