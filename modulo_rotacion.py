# ==============================================================
#  MÓDULO ANÁLISIS TÉCNICO — Weinstein / O'Neil / Darvas Box / Wyckoff
#  Reemplaza al módulo de Rotación (Sector/Commodities/Cripto/Índices).
#
#  Diferencia clave: acá NO hay un universo fijo de activos ni ranking
#  entre varios — el usuario elige el activo desde las categorías ya
#  definidas en tu archivo de configuración (acciones por industria,
#  forex, índices/países, ETFs de sector/subsector, mercados reales),
#  o tipea cualquier ticker manual soportado por Yahoo Finance.
#  El ADX de Wilder se calcula siempre como dato/filtro transversal
#  (se usa fuerte dentro de O'Neil).
#
#  Sin persistencia: no se guarda nada en Supabase. Cada análisis
#  vive solo en la sesión actual.
# ==============================================================

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from datetime import datetime
from zoneinfo import ZoneInfo

# --------------------------------------------------------------
# Ajustá este import al nombre real de tu archivo de configuración
# de activos (el que contiene ACCIONES_POR_INDUSTRIA, FOREX, PAISES,
# ETFS, SECTORES_TOTAL, MERCADOS_REALES, etc.)
# --------------------------------------------------------------
==========================================================

ACCIONES_POR_INDUSTRIA = {
    'Semiconductores':    ['NVDA','AMD','AVGO','TSM','ASML','QCOM','TXN','ADI','NXPI','MCHP', 'MRVL','ON','MU','INTC','ARM','GFS','STM','UMC','SNDK','MPWR', 'SYNA','QRVO','CRUS','LSCC','DIOD','RMBS','CEVA','AEHR','ALAB','ACLS', 'AMAT','LRCX','KLAC','TER','ONTO','UCTT','FORM','KLIC','CAMT','COHR', 'ENTG','SMTC','MTSI','POWI','VECO','HIMX','SIMO','INDI','ICHR'],
    'Software':           ['MSFT','ORCL','CRM','ADBE','SAP','NOW','INTU','WDAY','SNOW','PLTR', 'TEAM','HUBS','DOCU','MDB','DDOG','ESTC','BOX','ASAN','SMAR','PATH', 'PAYC','PAYX','TYL','PTC','ADSK','GWRE','MANH','PEGA','APPF', 'NCNO','QTWO','SPSC','WK','FIVN','BILL','DUOL','GTLB','BL','CVLT','PD','DBX','PCOR','RELY','MNDY','TWLO','FRSH'],
    'Ciberseguridad':     ['CRWD','PANW','ZS','FTNT','OKTA','QLYS','TENB','RPD','VRNS','NET', 'CHKP','GEN','AKAM','CSCO','FFIV','EXTR','RDWR','BB','OSIS','TLS','S','NABL','MSI','LDOS','LHX','SAIC','CACI', 'MRCY','ANET','VRSN','DOCN','BLZE','AI','IBM','ORCL','DDOG','NET'],
    'Cloud/AI':           ['MSFT','AMZN','GOOGL','META','ORCL','IBM','SNOW','MDB','DDOG','NET', 'PLTR','AI','CFLT','ESTC','SMCI','DELL','NVDA','AMD','CRM','SAP', 'NOW','INTU','ADBE','PATH','AKAM','GTLB','APP','ANET','HPE','NTAP', 'PSTG','BOX','ASAN','ARM','TSM','AVGO','COHR','VRT','EQIX','DLR', 'CIEN','SNPS','CDNS','MU','SNDK','WDC','CRWV','DOCN','FSLY','RBRK'],
    'Hardware/Equipos':   ['AAPL','DELL','HPE','HPQ','SMCI','CSCO','ANET','NTAP','PSTG','STX', 'WDC','SNDK','GLW','LOGI','JNPR','CIEN','KEYS','ZBRA','FLEX','SANM', 'ARW','JBL','APH','TEL','PLXS','FN','COMM','CRDO','LITE','COHR', 'IPGP','VSH','BELFA','TTMI','KLIC','CAMT','AEIS','MTSI','OLED','VRT', 'CDNS','SNPS','TER','ENTG','RMBS','SIMO','HIMX','AZTA','SMTC','FORM'],
    'Fintech':            ['XYZ','PYPL','AFRM','SOFI','UPST','LC','ENVA','NU','STNE','PAGS', 'DLO','PAYO','MQ','FOUR','COIN','HOOD','GPN','FI','FIS','JKHY', 'EEFT','PAY','FLT','WU','RM','NVEI','PSFE','BILL','MARA','RIOT', 'CIFR','CLSK','IREN','BTDR','CORZ','GLXY','BMNR','HUT','BTM','ML'],
    'Biotecnología':      ['AMGN','REGN','VRTX','GILD','BIIB','MRNA','BNTX','ALNY','INCY','EXEL', 'NBIX','HALO','IONS','LEGN','SRPT','CRSP','NTLA','BEAM','EDIT','RXRX', 'RNA','DNLI','ADPT','XENE','SANA','VERV','ARWR','FOLD','BMRN','TECH', 'ABCL','NTRA','GH','CDNA','PACB','TWST','ILMN','OMIC','RARE','ACAD', 'KYMR','CGON','IMVT','APLS','RVMD','MRUS','AUTL','BLUE','KROS','XNCR'],
    'Farmacéuticas':      ['LLY','JNJ','PFE','MRK','ABBV','BMY','AZN','NVO','NVS','SNY', 'GSK','TAK','TEVA','VTRS','OGN','BHC','RDY','EYPT','ZTS','ELV', 'CVS','HIMS','PHR','SUPN','ITCI','ACAD','ARRY','CPRX','BCRX','AMRX', 'PRGO','EOLS','AMPH','ANIP','COLL','EGRX','KNSA','MYOV','NGM','TVTX', 'XERS','ZYME','SLNO','ADMA','PTGX','ARDX','CRNX','MNKD','HROW','ETON'],
    'Equipos Médicos':    ['ISRG','ABT','SYK','BSX','MDT','EW','ZBH','BDX','BAX','HOLX', 'DXCM','PODD','MASI','RMD','STE','TFX','ICUI','HAE','OMCL','PEN', 'GKOS','INSP','NVCR','ALGN','XRAY','SEM','LIVN','IRTC','TMDX','PROF', 'LNTH','NEOG','OSUR','AXNX','SIBN','NARI','OFIX','AVNS','AORT','CVAC', 'PHG','SONVY','GEHC','SOLV','STER','MMSI','ENVX','ATRC','OM','SKTX'],
    'Servicios de Salud': ['UNH','ELV','CI','HUM','CVS','CNC','MOH','OSCR','DVA','HCA', 'UHS','THC','EHC','ACHC','SEM','LFST','PGNY','DOCS','AMED','ENSG', 'CHE','PNTG','FMS','OPCH','ADUS','SGRY','BKD','PACS','GH','DGX', 'LH','NEO','MEDP','IQV','ICON','SYNH','CRL','CTLT','TDOC','VEEV', 'EVH','AGL','ALHC','PRVA','ACCD','ONEM','SHC','ARDT','HIMS','LFMD'],
    'Bancos':             ['JPM','BAC','WFC','C','GS','MS','USB','PNC','TFC','COF', 'BK','STT','MTB','FITB','HBAN','RF','CFG','KEY','CMA','ZION', 'FHN','WTFC','EWBC','ONB','SNV','BPOP','FULT','FFIN','CADE','UBSI', 'ASB','OZK','PNFP','WBS','HOMB','BKU','SBSI','IBOC','TCBI','COLB', 'WAL','FIBK','FCNCA','CVBF','CATY','BANF','NBHC','GBCI','SFNC','FNB'],
    'Seguros':            ['BRK-B','PGR','CB','TRV','ALL','AFL','MET','PRU','AIG','HIG', 'CINF','WRB','RGA','LNC','GL','UNM','EG','MKL','BRO','AON', 'MMC','AJG','WTW','ACGL','RLI','ORI','KNSL','THG','AXS','RE', 'PFG','VOYA','SLF','MFC','EQH','AMP','FNF','FAF','AIZ','CNO', 'PIPR','JRVR','UFCS','NMIH','ESNT','MTG','RDN','HCI','TRUP','ROOT'],
    'Mercados Capitales': ['BX','KKR','APO','ARES','CG','OWL','BAM','BN','SCHW','IBKR', 'CME','ICE','NDAQ','MKTX','MS','GS','RJF','EVR','LAZ','PIPR', 'SF','LPLA','HOOD','COIN','SEIC','BEN','TROW','BLK','IVZ','AMG', 'JHG','PFG','CNS','MC','PJT','HLI','TREE','OPY','VIRT','XP', 'STNE','NMR','NOMD','DB','UBS','CS','RY','TD','BMO','BNS'],
    'Bancos Regionales':  ['FITB','HBAN','RF','CFG','ZION','FHN','WTFC','KEY','CMA','MTB', 'EWBC','ONB','SNV','FULT','FFIN','CADE','UBSI','ASB','OZK','PNFP', 'WBS','HOMB','BKU','SBSI','IBOC','TCBI','COLB','WAL','FIBK','FCNCA', 'CVBF','BANF','NBHC','GBCI','SFNC','FNB','CATY','PACW','UCBI','INDB'],
    'Finanzas Diversif.': ['V','MA','AXP','DFS','SYF','ALLY','COF','CACC','SLM','NAVI', 'RKT','OMF','WU','GPN','FI','FIS','JKHY','FLT','EEFT','PAY', 'PYPL','XYZ','AFRM','SOFI','UPST','LC','HOOD','COIN','NU','STNE', 'PAGS','DLO','PAYO','MQ','FOUR','TRU','EFX','EXPGY','SPGI','MCO', 'FICO','CINF','AMP','VOYA','EQH','BEN','TROW','BLK','IVZ','JHG'],
    'Petróleo Integrado': ['XOM','CVX','COP','EOG','OXY','DVN','MRO','APA','FANG','HES', 'PXD','CTRA','EQT','AR','RRC','CNX','CIVI','SM','MTDR','PR', 'MPC','PSX','VLO','PBF','DK','SUN','MUSA','SLB','HAL','BKR', 'NOV','CHX','LBRT','NBR','PTEN','HP','WTTR','TDW','RIG','VAL', 'PBR','SHEL','BP','TTE','EQNR','ENI','REPYY','YPF','VIST','EC'],
    'Energía Renovable':  ['NEE','BEP','BEPC','CWEN','CWEN-A','NEP','AES','ORA','AY', 'ENPH','FSLR','SEDG','RUN','ARRY','NXT','SHLS','FLNC','STEM', 'BE','PLUG','GEV','VRT','CSIQ','JKS','MAXN','NOVA','SPWR', 'AMRC','HASI','RNW','BLDP','HYLN','EVGO','CHPT','FREY', 'SES','EOSE','ENVX','SLDP','QS','MVST','LICY','LAC','ALTM','PLL'],
    'Gas Natural':        ['LNG','EQT','AR','RRC','CNX','KMI','WMB','OKE','TRGP','ET', 'EPD','MPLX','PAA','AM','DTM','HESM','KGS','MGY','CRK','GPOR', 'CTRA','OVV','SM','CIVI','EXE','NFG','SWX','ATO','NWN','UGI', 'NI','OGS','POR','SJI','SR','CPK','MMP','ENLC','WES','PAGP', 'GLNG','FLNG','GLOP','TGS','TGNP','ENB','TRP','KEYUF','KNTK','HUN'],
    'Energía Solar':      ['FSLR','ENPH','SEDG','RUN','ARRY','NXT','SHLS','CSIQ','JKS','MAXN', 'NOVA','SPWR','EMBK','BE','PLUG','FLNC','STEM','AMRC','ORA', 'NEE','CWEN','BEP','BEPC','NEP','AES','GEV','VRT','HASI','RNW', 'BLDP','CHPT','EVGO','EOSE','FREY','SES','SLDP','QS','ENVX','MVST'],
    'Aeroespacial':       ['BA','RTX','LMT','NOC','GD','HII','TDG','HEI','HEI-A','CW','TXT','KTOS','AVAV','BWXT','LHX','LDOS','MRCY','OSIS','SPR','COL','HON','AER','AJRD','IRDM','MAXR','RKLB','SPCE','ASTS','DRS','NOC','LMT','RTX','GD','BA','HII','TDG','HEI','CW','VSEC','ATRO','HXL','CWST','KAMN','TGI','MOG-A','DCO','ESLT','ARL','AVX','HEI-A','AIM','JOBY','ACHR','EH','LILAK','NNDM','PL'],
    'Transporte':         ['UPS','FDX','UNP','CSX','NSC','JBHT','ODFL','XPO','CHRW','EXPD', 'KEX','MATX','ZIM','DAC','SBLK','GOGL','PANL','GNK','TRTN','SFL', 'CAI','SINO','NM','DSX','LPG','STNG','INSW','TNK','EURN','FRO'],
    'Construcción':       ['CAT','DE','EMR','ETN','HON','GE','ROK','PH','ITW','MMM', 'VMC','MLM','EXP','BLDR','NVR','DHI','LEN','PHM','KBH','TOL', 'JCI','TT','URI','PWR','FIX','MTZ','ACM','FLR','HUBG','MAS'],
    'Defensa':            ['LMT','RTX','NOC','GD','HII','BA','TDG','HEI','CW','TXT', 'KTOS','AVAV','BWXT','LHX','LDOS','MRCY','OSIS','CACI','SAIC','NOC', 'GD','RTX','LMT','HII','BA','TDG','CW','HEI','TXT','KTOS'],
    'Retail':             ['AMZN','WMT','TGT','COST','HD','LOW','TJX','ROST','DG','DLTR', 'BBY','KR','BJ','WBA','CVS','ULTA','M','KSS','JWN','GPS', 'BURL','FIVE','WSM','RH','ORLY','AZO','AAP','TSCO','Ollies','OLLI', 'FND','TPR','RL','NKE','DECK','CROX','LEVI','PVH','URBN','AEO'],
    'Autos':              ['TSLA','GM','F','TM','HMC','STLA','RIVN','LCID','NIO','XPEV', 'LI','FCAU','MBGYY','BMWYY','VWAGY','RACE','GM','F','APTV','BWA', 'VC','GT','LEA','ALV','HOG','PII','THO','MBLY','ZK','XPEL'],
    'Hotelería/Viajes':   ['MAR','HLT','H','IHG','ABNB','BKNG','EXPE','RCL','CCL','NCLH', 'TRIP','DESP','TCOM','LVS','MGM','WYNN','CZR','SIX','SIXF','PLAY', 'DKNG','BALY','WYNN','HLT','MAR','VAC','WH','HGV','SVC','PK'],
    'E-commerce':         ['AMZN','SHOP','ETSY','EBAY','MELI','SE','PDD','BABA','JD','CPNG', 'W','CVNA','OSTK','WISH','BZUN','EXFY','REAL','GRPN','WIX','DOCN', 'FVRR','UPWK','RBLX','TTD','APP','NET','GTLB','FSLY','BIGC','BOX'],
    'Alimentos':          ['KO','PEP','MDLZ','KHC','GIS','CPB','SJM','K','KDP','HSY', 'MDLZ','TSN','HRL','ADM','BG','CHD','CLX','CAG','POST','MKC', 'EL','PG','UL','NOMD','LANC','COKE','FLO','DAR','INGR','SMPL'],
    'Bebidas':            ['KO','PEP','MNST','STZ','BUD','TAP','DEO','KDP','CELH','FIZZ', 'PRMW','CCEP','FMX','SAM','BFB','BUD','TAP','WULF','COKE','NAPA', 'VIV','BRBR','SPB','SOVO','REX','KOF','ABEV','CCU','AGRO','COTY'],
    'Minería Oro':        ['NEM','GOLD','AEM','WPM','KGC','PAAS','AG','CDE','HL','SSRM', 'NGD','AUX','DRD','BTG','EGO','HMY','IAG','AU','SA','GFI', 'OR','FNV','RGLD','KNT','WDO','EQX','TGB','SILV','BVN','CGAU'],
    'Cobre/Metales':      ['FCX','SCCO','TECK','HBM','NUE','STLD','CLF','NUE','AA','CDE', 'KGC','PAAS','AG','HL','WPM','AEM','NEM','GOLD','SSRM','NGD', 'ERO','LUNMF','LAC','ALB','PLL','MP','CRS','ATI','X','HBM','TECK'],
    'Químicos':           ['LIN','APD','DD','DOW','LYB','EMN','CE','IFF','PPG','SHW', 'ECL','ALB','FMC','CF','MOS','NTR','OLN','ASH','AVNT','HUN', 'X','BC','RPM','WLK','TSE','SXT','SCL','NEU','IOSP','CBT'],
    'Acero':              ['NUE','STLD','CLF','X','MT','RS','CMC','SID','GGB','TX', 'PKX','NWL','CRS','ATI','SCHN','ZEUS','NBR','X','STLD','CLF', 'CLF','NUE','STLD','CMC','MT','RS','X','PKX','SID','GGB'],
    'Eléctricas':         ['NEE','DUK','SO','D','AEP','EXC','XEL','ED','ETR','PEG', 'PCG','PPL','FE','ES','EIX','AES','CNP','NI','ATO','LNT', 'WEC','CMS','DTE','SRE','XEL','EVRG','IDA','BEP','BEPC','NEP', 'ORA','PEGI','UGI','BIP','BIPC','AVA','PNW','NRG','NRZ','CVA'],
    'Agua':               ['AWK','WTRG','WTR','AWR','YORW','MSEX','SJW','CWCO','GWRS','ARTNA', 'PNW','AWK','AWK','WTRG','SJW','CWT','CWT','SJW','AWR','YORW', 'WSO','AQUA','ECL','XYL','PUMP','GRC','MEG','H2O','CWCO','PRMW'],
    'REIT Comercial':     ['SPG','O','VICI','NNN','BXP','KIM','REG','MAC','PEAK','FRT', 'SLG','EPR','WPC','ARE','HST','PK','VNO','CUZ','HIW','KRC', 'DEI','BRX','ADC','STAG','PLD','EQIX','DLR','CONE','COR','AMT', 'CCI','SBAC','WY','IRM','GOOD','LAND','SLG','BXP','O','SPG'],
    'REIT Industrial':    ['PLD','AMT','CCI','DLR','EQIX','STAG','EGP','FR','REXR','TRNO', 'PLYM','LXP','COLD','ILPT','PSTL','STAG','IRM','CUBE','GOOD','O', 'PLD','EQIX','DLR','AMT','CCI','SBAC','CONE','COR','DLR','PLD'],
    'REIT Residencial':   ['EQR','AVB','ESS','MAA','UDR','CPT','ELS','AIV','NXRT','INVH', 'IRT','AMH','BRG','SUI','NXRT','MHC','UMH','ESS','EQR','AVB', 'UDR','MAA','CPT','INVH','AMH','SUI','ELS','AIRC','CUBE','CPT'],
    'Telecomunicaciones': ['T','VZ','TMUS','S','CHTR','CMCSA','LUMN','FYBR','VOD','BT', 'ORAN','TEF','TU','BCE','RCI','SKM','ZL','AMX','TIGO','TDS', 'ATUS','WOW','CNSL','QCOM','AMT','CCI','SBAC','WBD','NFLX','DIS', 'TMUS','VZ','T','CMCSA','CHTR','S','LUMN','VOD','BT','TEF'],
    'Internet':           ['GOOGL','META','NFLX','SNAP','PINS','RDDT','SPOT','ROKU','IAC','MTCH', 'BMBL','YELP','DASH','UBER','LYFT','SHOP','SE','MELI','ETSY','EBAY', 'BABA','JD','PDD','BIDU','NTES','WB','IQ','TME','WIX','RBLX', 'DUOL','TTD','PUBM','APP','NET','AKAM','DOCN','GTLB','BOX','ZI', 'YEXT','COUR','CHGG','RUM','VKTX','CRWV','FSLY','CFLT','DBX','TASK'],
    'Argentina':          ['GGAL', 'BMA', 'BBAR', 'SUPV', 'CEPU', 'YPF', 'PAM', 'TGS', 'CRESY', 'LOMA', 'VIST', 'IRCP', 'EDN', 'TRAN', 'IRS', 'DESP', 'GLOB', 'BIOX', 'MTR', 'AGRO', 'PGR', 'SBS'],
    'Brasil':             ['VALE','ITUB','PBR','BBD','ABEV','NU'],
    'China':              ['BABA','TCEHY','BIDU','JD','NIO','LI','XPEV','BYDDF','PDD','NTES'],
    'India':              ['INFY','WIT','HDB','IBN','VEDL','RDY','TTM'],
    'Europa Tecnología':  ['SAP','ASML','IFNNY','NXPI'],
    'Europa Finanzas':    ['HSBC','BBVA','SAN','DBK.DE','LLOY.L','UBS','ING'],
    'Agro/Fertilizantes': ['MOS','NTR','CF','ADM','BG','FMC','CTVA'],
    'Cripto (ETF/Coin)':  ['BTC-USD','ETH-USD','SOL-USD','BNB-USD','XRP-USD','ADA-USD','DOGE-USD','AVAX-USD','DOT-USD','MATIC-USD', 'LINK-USD','LTC-USD','ATOM-USD','ETC-USD','XLM-USD','FIL-USD','ICP-USD','HBAR-USD','NEAR-USD','ARB-USD', 'COIN','MARA','RIOT','CLSK','HUT','BITF','BTDR','IREN','CAN','WULF'],
}


TICKER_INDUSTRY = {}
for ind, lst in ACCIONES_POR_INDUSTRIA.items():
    for t in lst:
        if t not in TICKER_INDUSTRY:
            TICKER_INDUSTRY[t] = ind


ALL_TICKERS = sorted(set(t for lst in ACCIONES_POR_INDUSTRIA.values() for t in lst))


FOREX = {
    # --- Majors ---
    'EUR/USD': ('EURUSD=X', 'Majors'),
    'GBP/USD': ('GBPUSD=X', 'Majors'),
    'USD/JPY': ('USDJPY=X', 'Majors'),
    'USD/CHF': ('USDCHF=X', 'Majors'),
    'USD/CAD': ('USDCAD=X', 'Majors'),
    'AUD/USD': ('AUDUSD=X', 'Majors'),
    'NZD/USD': ('NZDUSD=X', 'Majors'),
    'USD/CNY': ('USDCNY=X', 'Majors'),

    # --- Crosses EUR ---
    'EUR/GBP': ('EURGBP=X', 'Crosses EUR'),
    'EUR/JPY': ('EURJPY=X', 'Crosses EUR'),
    'EUR/CHF': ('EURCHF=X', 'Crosses EUR'),
    'EUR/AUD': ('EURAUD=X', 'Crosses EUR'),
    'EUR/CAD': ('EURCAD=X', 'Crosses EUR'),

    # --- Crosses GBP ---
    'GBP/JPY': ('GBPJPY=X', 'Crosses GBP'),
    'GBP/AUD': ('GBPAUD=X', 'Crosses GBP'),
    'GBP/CAD': ('GBPCAD=X', 'Crosses GBP'),

    # --- Crosses AUD/NZD ---
    'AUD/JPY': ('AUDJPY=X', 'Crosses AUD'),
    'AUD/CAD': ('AUDCAD=X', 'Crosses AUD'),
    'AUD/NZD': ('AUDNZD=X', 'Crosses AUD'),
    'NZD/JPY': ('NZDJPY=X', 'Crosses NZD'),

    # --- Crosses JPY/CHF ---
    'CAD/JPY': ('CADJPY=X', 'Crosses JPY'),
    'CHF/JPY': ('CHFJPY=X', 'Crosses JPY'),

    # --- LatAm ---
    'USD/ARS': ('USDARS=X', 'LatAm'),
    'USD/BRL': ('USDBRL=X', 'LatAm'),
    'USD/MXN': ('USDMXN=X', 'LatAm'),
    'USD/CLP': ('USDCLP=X', 'LatAm'),
    'USD/COP': ('USDCOP=X', 'LatAm'),
    'USD/PEN': ('USDPEN=X', 'LatAm'),
    'USD/UYU': ('USDUYU=X', 'LatAm'),
}


PAISES = {
    'EE.UU. S&P500':    ('^GSPC',  'América'),
    'EE.UU. NASDAQ':    ('^NDX',   'América'),
    'EE.UU. DOW':       ('^DJI',   'América'),
    'EE.UU. Russell':   ('^RUT',   'América'),
    'Argentina':        ('^MERV',  'América'),
    'Brasil':           ('^BVSP',  'América'),
    'Japón':            ('^N225',  'Asia'),
    'China':            ('^HSI',   'Asia'),
    'Corea del Sur':    ('^KS11',  'Asia'),
    'India':            ('^NSEI',  'Asia'),
    'Alemania':         ('^GDAXI', 'Europa'),
    'Europa general':   ('^STOXX50E', 'Europa'),
    'Gran Bretaña':   ('^FTSE',  'Europa'),
    'Francia':   ('^FCHI',  'Europa'),
}

# --- ETFs (Índices + Sectores, todo junto) ---
ETFS = {
    # Índices (ETF que los replica)
    'EE.UU. S&P500':    ('SPY',  'Índices', '#3a7bd5'),
    'EE.UU. NASDAQ':    ('QQQ',  'Índices', '#79c0ff'),
    'EE.UU. DOW':       ('DIA',  'Índices', '#8b949e'),
    'EE.UU. Russell':   ('IWM',  'Índices', '#bc8cff'),
    'Argentina':        ('ARGT', 'Índices', '#6cb6ff'),
    'Brasil':           ('EWZ',  'Índices', '#3fb950'),
    'Japón':            ('EWJ',  'Índices', '#f0883e'),
    'China':            ('FXI',  'Índices', '#f85149'),
    'Corea del Sur':    ('EWY',  'Índices', '#e3b341'),
    'India':            ('INDA', 'Índices', '#ffa657'),
    'Alemania':         ('EWG',  'Índices', '#d2a8ff'),
    'Europa general':   ('VGK',  'Índices', '#3a7bd5'),
    'Mercados Emerg.':  ('EEM',  'Índices', '#8b949e'),
}

SECTORES_TOTAL = {
    # --- Sectores (SPDR, vista macro - 11 sectores GICS) ---
    'Tecnología':     ('XLK',  'Sectores', '#3a7bd5'),
    'Salud':          ('XLV',  'Sectores', '#3fb950'),
    'Finanzas':       ('XLF',  'Sectores', '#e3b341'),
    'Consumo Discr.': ('XLY',  'Sectores', '#f0883e'),
    'Consumo Básico': ('XLP',  'Sectores', '#bc8cff'),
    'Energía':        ('XLE',  'Sectores', '#ffa657'),
    'Industriales':   ('XLI',  'Sectores', '#79c0ff'),
    'Materiales':     ('XLB',  'Sectores', '#8b949e'),
    'Utilities':      ('XLU',  'Sectores', '#3fb950'),
    'Real Estate':    ('XLRE', 'Sectores', '#f85149'),
    'Comunicaciones': ('XLC',  'Sectores', '#d2a8ff'),

    # --- Sub-sectores (vista granular / temática) ---
    'Semiconductores':    ('SMH',  'Sub-sectores', '#3a7bd5'),
    'Software':           ('IGV',  'Sub-sectores', '#79c0ff'),
    'Ciberseguridad':     ('CIBR', 'Sub-sectores', '#f85149'),
    'Cloud/AI':           ('SKYY', 'Sub-sectores', '#bc8cff'),
    'Fintech':            ('FINX', 'Sub-sectores', '#3fb950'),
    'Biotecnología':      ('XBI',  'Sub-sectores', '#f0883e'),
    'Farmacéuticas':      ('PPH',  'Sub-sectores', '#e3b341'),
    'Equipos Médicos':    ('IHI',  'Sub-sectores', '#79c0ff'),
    'Servicios de Salud': ('IHF',  'Sub-sectores', '#3fb950'),
    'Bancos':             ('KBE',  'Sub-sectores', '#e3b341'),
    'Seguros':            ('KIE',  'Sub-sectores', '#8b949e'),
    'Mercados Capitales': ('KCE',  'Sub-sectores', '#d2a8ff'),
    'Bancos Regionales':  ('KRE',  'Sub-sectores', '#f0883e'),
    'Finanzas Diversif.': ('IYG',  'Sub-sectores', '#3a7bd5'),
    'Petróleo Integrado': ('XOP',  'Sub-sectores', '#ffa657'),
    'Energía Renovable':  ('ICLN', 'Sub-sectores', '#3fb950'),
    'Gas Natural':        ('FCG',  'Sub-sectores', '#79c0ff'),
    'Energía Solar':      ('TAN',  'Sub-sectores', '#e3b341'),
    'Aeroespacial':       ('ITA',  'Sub-sectores', '#8b949e'),
    'Transporte':         ('IYT',  'Sub-sectores', '#f0883e'),
    'Defensa':            ('XAR',  'Sub-sectores', '#6c5ce7'),
    'Retail':             ('XRT',  'Sub-sectores', '#f85149'),
    'Autos':              ('CARZ', 'Sub-sectores', '#3a7bd5'),
    'Hotelería/Viajes':   ('PEJ',  'Sub-sectores', '#ffa657'),
    'E-commerce':         ('IBUY', 'Sub-sectores', '#bc8cff'),
    'Alimentos':          ('PBJ',  'Sub-sectores', '#3fb950'),
    'Minería Oro':        ('GDX',  'Sub-sectores', '#e3b341'),
    'Cobre/Metales':      ('COPX', 'Sub-sectores', '#cd7f32'),
    'Acero':              ('SLX',  'Sub-sectores', '#79c0ff'),
    'Eléctricas':         ('XLU',  'Sub-sectores', '#3fb950'),
    'Agua':               ('PHO',  'Sub-sectores', '#3a7bd5'),
    'REIT Industrial':    ('INDS', 'Sub-sectores', '#8b949e'),
    'REIT Residencial':   ('REZ',  'Sub-sectores', '#3fb950'),
    'Telecomunicaciones': ('IYZ',  'Sub-sectores', '#d2a8ff'),
    'Internet':           ('FDN',  'Sub-sectores', '#3a7bd5'),
}

# ← AGREGAR ESTA LÍNEA:
SECTORES = {nombre: (tk, color) for nombre, (tk, cat, color) in SECTORES_TOTAL.items()}
SECTORES_GICS = {nombre: (tk, color) for nombre, (tk, cat, color) in SECTORES_TOTAL.items() if cat == 'Sectores'}
SUBSECTORES   = {nombre: (tk, color) for nombre, (tk, cat, color) in SECTORES_TOTAL.items() if cat == 'Sub-sectores'}

SUBSECTOR_A_SECTOR = {
    'Semiconductores': 'Tecnología', 'Software': 'Tecnología',
    'Ciberseguridad': 'Tecnología', 'Cloud/AI': 'Tecnología',
    'Fintech': 'Finanzas', 'Bancos': 'Finanzas', 'Seguros': 'Finanzas',
    'Mercados Capitales': 'Finanzas', 'Bancos Regionales': 'Finanzas',
    'Finanzas Diversif.': 'Finanzas',
    'Biotecnología': 'Salud', 'Farmacéuticas': 'Salud',
    'Equipos Médicos': 'Salud', 'Servicios de Salud': 'Salud',
    'Petróleo Integrado': 'Energía', 'Energía Renovable': 'Energía',
    'Gas Natural': 'Energía', 'Energía Solar': 'Energía',
    'Aeroespacial': 'Industriales', 'Transporte': 'Industriales', 'Defensa': 'Industriales',
    'Retail': 'Consumo Discr.', 'Autos': 'Consumo Discr.',
    'Hotelería/Viajes': 'Consumo Discr.', 'E-commerce': 'Consumo Discr.',
    'Alimentos': 'Consumo Básico',
    'Minería Oro': 'Materiales', 'Cobre/Metales': 'Materiales', 'Acero': 'Materiales',
    'Eléctricas': 'Utilities', 'Agua': 'Utilities',
    'REIT Industrial': 'Real Estate', 'REIT Residencial': 'Real Estate',
    'Telecomunicaciones': 'Comunicaciones', 'Internet': 'Comunicaciones',
}

COLORES_SECTOR_PADRE = {nombre: color for nombre, (tk, color) in SECTORES_GICS.items()}


# --- Mercados reales: energía, metales, minería, agro, blandos, cripto ---
MERCADOS_REALES = {
    # --- Energía ---
    'Petróleo WTI':   ('CL=F',    'Energía',      '#f0883e'),
    'Petróleo Brent': ('BZ=F',    'Energía',      '#ffa657'),
    'Gas Natural':    ('NG=F',    'Energía',      '#79c0ff'),
    'Gasolina RBOB':  ('RB=F',    'Energía',      '#ff9e64'),
    'Heating Oil':    ('HO=F',    'Energía',      '#ff7b72'),
    'Uranio (ETF)':   ('URA',     'Energía',      '#56d364'),

    # --- Metales Preciosos ---
    'Oro':     ('GC=F', 'Met. Prec.', '#e3b341'),
    'Plata':   ('SI=F', 'Met. Prec.', '#8b949e'),
    'Platino': ('PL=F', 'Met. Prec.', '#bc8cff'),
    'Paladio': ('PA=F', 'Met. Prec.', '#d2a8ff'),

    # --- Metales Industriales / Tierras Raras ---
    'Cobre':          ('HG=F',  'Met. Ind.', '#cd7f32'),
    'Litio (ETF)':    ('LIT',   'Met. Ind.', '#79c0ff'),
    'Acero (ETF)':    ('SLX',   'Met. Ind.', '#8b949e'),

    # --- Minería ---
    'Mineras Oro':   ('GDX',  'Minería', '#e3b341'),
    'Mineras Plata': ('SIL',  'Minería', '#8b949e'),
    'Mineras Cobre': ('COPX', 'Minería', '#cd7f32'),

    # --- Agro (granos) ---
    'Soja':  ('ZS=F', 'Agro', '#3fb950'),
    'Maíz':  ('ZC=F', 'Agro', '#7ee787'),
    'Trigo': ('ZW=F', 'Agro', '#ffa657'),
    'Avena': ('ZO=F', 'Agro', '#a4e494'),
    'Arroz': ('ZR=F', 'Agro', '#c9e88c'),

    # --- Blandos (Softs) ---
    'Café':             ('KC=F', 'Blandos', '#a0754b'),
    'Azúcar':           ('SB=F', 'Blandos', '#f3d9a4'),
    'Algodón':          ('CT=F', 'Blandos', '#eaeaea'),
    'Cacao':            ('CC=F', 'Blandos', '#7a4b2a'),

    # --- Cripto (Coins) ---
    'Bitcoin':    ('BTC-USD',  'Cripto', '#f0883e'),
    'Ethereum':   ('ETH-USD',  'Cripto', '#7ee787'),
    'Solana':     ('SOL-USD',  'Cripto', '#bc8cff'),
    'BNB':        ('BNB-USD',  'Cripto', '#f3ba2f'),
    'XRP':        ('XRP-USD',  'Cripto', '#3a7bd5'),
    'Cardano':    ('ADA-USD',  'Cripto', '#2a71d0'),
    'Dogecoin':   ('DOGE-USD', 'Cripto', '#e8b923'),
    'Avalanche':  ('AVAX-USD', 'Cripto', '#e84142'),
    'Polkadot':   ('DOT-USD',  'Cripto', '#e6007a'),
    'Chainlink':  ('LINK-USD', 'Cripto', '#2a5ada'),
    'Litecoin':   ('LTC-USD',  'Cripto', '#bebebe'),
    'Cosmos':     ('ATOM-USD', 'Cripto', '#2e3148'),
    'Ethereum Classic':('ETC-USD','Cripto','#328332'),
    'Stellar':    ('XLM-USD',  'Cripto', '#08b5e5'),
    'Filecoin':   ('FIL-USD',  'Cripto', '#0090ff'),
    'Internet Computer':('ICP-USD','Cripto','#3b00b9'),
    'Hedera':     ('HBAR-USD', 'Cripto', '#4b4b4b'),
    'Near':       ('NEAR-USD', 'Cripto', '#000000'),
    'Arbitrum':   ('ARB-USD',  'Cripto', '#28a0f0'),

    # --- Cripto (ETF / Mineras) ---
    'Coinbase':   ('COIN',  'Cripto ETF', '#0052ff'),
    'Marathon Digital':('MARA','Cripto ETF','#f7931a'),
    'Riot Platforms':  ('RIOT', 'Cripto ETF', '#e8412f'),
    'CleanSpark':      ('CLSK', 'Cripto ETF', '#00b894'),
    'Hut 8':           ('HUT',  'Cripto ETF', '#6c5ce7'),
    'Bitdeer':         ('BTDR', 'Cripto ETF', '#fdcb6e'),
    'Iris Energy':     ('IREN', 'Cripto ETF', '#74b9ff'),
    'Canaan':          ('CAN',  'Cripto ETF', '#a29bfe'),
    'TeraWulf':        ('WULF', 'Cripto ETF', '#fab1a0'),
}

ZONA_AR = ZoneInfo("America/Argentina/Buenos_Aires")
BENCHMARK_DEFAULT = '^GSPC'  # S&P 500, referencia general de mercado (usado por O'Neil)

METODOS_DISPONIBLES = {
    "Stan Weinstein — Fases de mercado": "weinstein",
    "William O'Neil — CANSLIM técnico / Fuerza relativa": "oneil",
    "Darvas Box — Cajas de consolidación + breakout": "darvas",
    "Wyckoff — Acumulación / Distribución": "wyckoff",
}

# --------------------------------------------------------------
# Categorías de selección de activo → cómo resolver el ticker
# --------------------------------------------------------------
CATEGORIAS_ACTIVO = [
    "Acción (por industria)",
    "Forex",
    "Índice / País",
    "ETF de Índice",
    "ETF Sector / Subsector",
    "Mercado real (commodity / cripto)",
    "Ticker manual (cualquiera)",
]


def _at_ahora_ar():
    return datetime.now(ZONA_AR)


# ==============================================================
#  SELECTOR DE ACTIVO (reemplaza al text_input libre)
# ==============================================================

def _at_seleccionar_ticker():
    """Devuelve (ticker, etiqueta_legible) según la categoría elegida."""
    categoria = st.selectbox('Tipo de activo', CATEGORIAS_ACTIVO, key='at_categoria')

    if categoria == "Acción (por industria)":
        industria = st.selectbox('Industria', sorted(ACCIONES_POR_INDUSTRIA.keys()), key='at_industria')
        ticker = st.selectbox('Ticker', sorted(set(ACCIONES_POR_INDUSTRIA[industria])), key='at_ticker_industria')
        return ticker, f"{ticker} ({industria})"

    elif categoria == "Forex":
        par = st.selectbox('Par de divisas', sorted(FOREX.keys()), key='at_forex_par')
        ticker, sub = FOREX[par]
        return ticker, f"{par} ({sub})"

    elif categoria == "Índice / País":
        pais = st.selectbox('País / Índice', sorted(PAISES.keys()), key='at_pais')
        ticker, region = PAISES[pais]
        return ticker, f"{pais} ({region})"

    elif categoria == "ETF de Índice":
        nombre = st.selectbox('Índice (vía ETF)', sorted(ETFS.keys()), key='at_etf_indice')
        ticker, cat, _color = ETFS[nombre]
        return ticker, f"{nombre} ({cat})"

    elif categoria == "ETF Sector / Subsector":
        nombre = st.selectbox('Sector / Subsector', sorted(SECTORES_TOTAL.keys()), key='at_etf_sector')
        ticker, cat, _color = SECTORES_TOTAL[nombre]
        return ticker, f"{nombre} ({cat})"

    elif categoria == "Mercado real (commodity / cripto)":
        nombre = st.selectbox('Mercado', sorted(MERCADOS_REALES.keys()), key='at_mercado_real')
        ticker, cat, _color = MERCADOS_REALES[nombre]
        return ticker, f"{nombre} ({cat})"

    else:  # Ticker manual
        ticker = st.text_input(
            'Ticker manual (cualquier activo soportado por Yahoo Finance)',
            value='AAPL', key='at_ticker_manual',
        ).strip().upper()
        return ticker, ticker


# ==============================================================
#  DESCARGA DE DATOS
# ==============================================================

@st.cache_data(ttl=3600, show_spinner=False)
def _at_descargar(ticker, periodo='2y', intervalo='1d'):
    try:
        import yfinance as yf
        data = yf.Ticker(ticker).history(period=periodo, interval=intervalo, auto_adjust=True)
        data = data[["Open", "High", "Low", "Close", "Volume"]].dropna()
        return data if not data.empty else None
    except Exception:
        return None


def _at_agregar_medias(data):
    data = data.copy()
    data["MM30"] = data["Close"].rolling(window=30).mean()
    data["MM50"] = data["Close"].rolling(window=50).mean()
    data["MM150"] = data["Close"].rolling(window=150).mean()
    data["MM200"] = data["Close"].rolling(window=200).mean()
    return data


# ==============================================================
#  ADX DE WILDER (filtro de tendencia, uso transversal)
# ==============================================================

def _at_calcular_adx(data, periodo=14):
    """ADX (Average Directional Index) de Welles Wilder. Filtro objetivo de
    '¿hay tendencia establecida o no?', reutilizado dentro de O'Neil y como
    dato informativo en Weinstein/Darvas/Wyckoff. ADX >= 25 = umbral clásico
    de tendencia establecida."""
    high, low, close = data["High"], data["Low"], data["Close"]
    prev_close, prev_high, prev_low = close.shift(1), high.shift(1), low.shift(1)

    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)

    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=data.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=data.index)

    tr_s = tr.ewm(alpha=1 / periodo, adjust=False).mean()
    plus_dm_s = plus_dm.ewm(alpha=1 / periodo, adjust=False).mean()
    minus_dm_s = minus_dm.ewm(alpha=1 / periodo, adjust=False).mean()

    plus_di = 100 * (plus_dm_s / tr_s)
    minus_di = 100 * (minus_dm_s / tr_s)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.ewm(alpha=1 / periodo, adjust=False).mean()

    return plus_di, minus_di, adx


# ==============================================================
#  MÉTODO 1: STAN WEINSTEIN
# ==============================================================

def _at_analizar_weinstein(data):
    mm30_actual = data["MM30"].iloc[-1]
    pendiente_mm30 = data["MM30"].diff().iloc[-5:].mean()
    precio = data["Close"].iloc[-1]

    if precio > mm30_actual and pendiente_mm30 > 0:
        fase = "Fase 2 – Tendencia alcista"
        descripcion = "El precio está por encima de la MM30 y la media sube. Señal alcista."
    elif precio < mm30_actual and pendiente_mm30 < 0:
        fase = "Fase 4 – Tendencia bajista"
        descripcion = "El precio está por debajo de la MM30 y la media baja. Señal bajista."
    elif abs(precio - mm30_actual) / mm30_actual < 0.03 and abs(pendiente_mm30) < 0.01:
        fase = "Fase 1 – Acumulación"
        descripcion = "El precio y la MM30 se mueven lateralmente sin tendencia clara."
    else:
        fase = "Fase 3 – Distribución"
        descripcion = "El precio pierde fuerza, lateraliza cerca de la MM30. Posible techo."

    if "Fase 2" in fase:
        conclusion = ("El activo está en tendencia alcista confirmada. Es la fase que Weinstein "
                      "considera apta para comprar o mantener posiciones ya abiertas.")
    elif "Fase 4" in fase:
        conclusion = ("El activo está en tendencia bajista confirmada. Weinstein recomienda evitar "
                      "compras acá y, si tenés posición, priorizar la salida o esperar una nueva Fase 1.")
    elif "Fase 1" in fase:
        conclusion = ("El activo está lateralizando, sin tendencia definida. Es una fase de espera: "
                      "conviene monitorear hasta que se confirme una ruptura al alza (Fase 2) o a la baja (Fase 4).")
    else:
        conclusion = ("El activo muestra señales de agotamiento tras una suba. Es momento de cautela, "
                      "ya que suele preceder a un cambio de tendencia hacia la Fase 4.")

    resumen = {
        "Método": "Stan Weinstein", "Señal principal": fase, "Descripción": descripcion,
        "MM30 actual": mm30_actual, "Pendiente MM30 (5d)": pendiente_mm30,
        "ADX(14)": data["ADX"].iloc[-1],
        "+DI / -DI": f"{data['+DI'].iloc[-1]:.1f} / {data['-DI'].iloc[-1]:.1f}",
        "Conclusión": conclusion,
    }
    return resumen, [("MM30", data["MM30"])], []


# ==============================================================
#  FUERZA RELATIVA (usada por O'Neil)
# ==============================================================

def _at_calcular_rs_rating(data, benchmark_data):
    """Fuerza relativa simplificada estilo IBD: compara el retorno del activo
    contra el benchmark en distintas ventanas, ponderando más lo reciente.
    No es el RS Rating oficial de IBD, pero sigue la misma lógica."""
    activo = data["Close"]
    bench = benchmark_data["Close"].reindex(activo.index, method="nearest")

    ventanas, pesos = [63, 126, 189, 252], [0.4, 0.2, 0.2, 0.2]
    score = 0
    for w, p in zip(ventanas, pesos):
        w = min(w, len(activo) - 1)
        if w <= 0:
            continue
        ret_activo = activo.iloc[-1] / activo.iloc[-w] - 1
        ret_bench = bench.iloc[-1] / bench.iloc[-w] - 1
        score += p * (ret_activo - ret_bench)

    return int(np.clip(50 + score * 200, 1, 99))


# ==============================================================
#  MÉTODO 2: WILLIAM O'NEIL
# ==============================================================

def _at_analizar_oneil(data, benchmark_data):
    precio = data["Close"].iloc[-1]
    mm50, mm150 = data["MM50"].iloc[-1], data["MM150"].iloc[-1]

    maximo_52 = data["Close"].rolling(window=252, min_periods=50).max().iloc[-1]
    minimo_52 = data["Close"].rolling(window=252, min_periods=50).min().iloc[-1]
    distancia_maximo = (precio / maximo_52 - 1) * 100
    distancia_minimo = (precio / minimo_52 - 1) * 100

    vol_mm50 = data["Volume"].rolling(50).mean().iloc[-1]
    vol_mm10 = data["Volume"].rolling(10).mean().iloc[-1]
    volumen_creciente = bool(vol_mm10 > vol_mm50)

    rs_rating = None
    if benchmark_data is not None:
        try:
            rs_rating = _at_calcular_rs_rating(data, benchmark_data)
        except Exception:
            rs_rating = None

    adx_actual = data["ADX"].iloc[-1]
    plus_di_actual, minus_di_actual = data["+DI"].iloc[-1], data["-DI"].iloc[-1]
    tendencia_confirmada_adx = bool(
        not np.isnan(adx_actual) and adx_actual >= 25 and plus_di_actual > minus_di_actual
    )

    condiciones = {
        "Precio sobre MM50": bool(precio > mm50),
        "Precio sobre MM150": bool(precio > mm150),
        "Cerca del máximo de 52 semanas (dentro del 15%)": bool(distancia_maximo >= -15),
        "Lejos del mínimo de 52 semanas (>=30% sobre el piso)": bool(distancia_minimo >= 30),
        "Volumen en expansión (promedio 10d > promedio 50d)": volumen_creciente,
        "ADX(14) >= 25 con +DI > -DI (tendencia alcista confirmada por Wilder)": tendencia_confirmada_adx,
    }
    if rs_rating is not None:
        condiciones["RS Rating aproximado >= 70 (fuerte vs mercado)"] = bool(rs_rating >= 70)

    cumplidas, total = sum(condiciones.values()), len(condiciones)

    if cumplidas == total:
        senal = "Configuración O'Neil COMPLETA – Candidato de compra / líder de mercado"
    elif cumplidas >= total - 1:
        senal = "Configuración O'Neil casi completa – Vigilar de cerca"
    elif cumplidas >= total / 2:
        senal = "Configuración parcial – Falta confirmar fuerza"
    else:
        senal = "No cumple criterios O'Neil – Débil frente al mercado"

    rs_texto = f"un RS Rating aproximado de {rs_rating}" if rs_rating is not None else "sin dato de RS Rating"
    if cumplidas == total:
        conclusion = (f"El activo cumple todos los criterios de O'Neil: está por encima de sus medias "
                      f"móviles clave, cerca de máximos de 52 semanas, con volumen en expansión, tendencia "
                      f"confirmada por ADX y {rs_texto}. Es el perfil de 'líder de mercado' que busca CANSLIM.")
    elif cumplidas >= total - 1:
        conclusion = ("Al activo le falta un solo criterio para el perfil O'Neil completo. Vale la pena "
                      "seguirlo de cerca, está muy cerca de mostrar fuerza relativa frente al mercado.")
    elif cumplidas >= total / 2:
        conclusion = ("El activo cumple parte de los criterios, pero todavía no muestra la fuerza y el "
                      "acompañamiento de volumen que O'Neil exige para considerarlo un líder claro.")
    else:
        conclusion = ("El activo está débil frente al criterio O'Neil: lejos de máximos, sin acompañamiento "
                      "de volumen o por debajo de sus medias móviles clave. No es el momento para este método.")

    resumen = {
        "Método": "William O'Neil (CANSLIM técnico)", "Señal principal": senal,
        "Criterios cumplidos": f"{cumplidas}/{total}", "Detalle": condiciones,
        "% respecto al máximo 52 sem": distancia_maximo, "% respecto al mínimo 52 sem": distancia_minimo,
        "RS Rating (aprox., no oficial IBD)": rs_rating, "ADX(14)": adx_actual, "Conclusión": conclusion,
    }
    return resumen, [("MM50", data["MM50"]), ("MM150", data["MM150"])], []


# ==============================================================
#  MÉTODO 3: DARVAS BOX
# ==============================================================

def _at_detectar_darvas_box(data, ventana=130, dias_confirmacion=3, tolerancia_pct=1.0):
    """Detección algorítmica simplificada de Cajas de Darvas: techo confirmado
    tras N días sin ser superado, piso = mínimo posterior mientras el precio
    se mantenga dentro de la caja, breakout = cierre sobre el techo con
    volumen por encima del promedio."""
    sub = data.tail(ventana).copy()
    highs, lows, closes, fechas, n = sub["High"].values, sub["Low"].values, sub["Close"].values, sub.index, len(sub)

    cajas, i = [], 0
    while i < n:
        max_local, idx_max, j, confirmado = highs[i], i, i + 1, 0
        while j < n and confirmado < dias_confirmacion:
            if highs[j] > max_local:
                max_local, idx_max, confirmado = highs[j], j, 0
            else:
                confirmado += 1
            j += 1
        if confirmado < dias_confirmacion:
            break

        techo, idx_techo = max_local, idx_max
        piso, idx_piso = lows[idx_techo], idx_techo
        k = idx_techo + 1
        while k < n:
            if closes[k] > techo * (1 + tolerancia_pct / 100):
                break
            if lows[k] < piso:
                piso, idx_piso = lows[k], k
            if closes[k] < piso * (1 - tolerancia_pct / 100):
                break
            k += 1

        cajas.append({"techo": techo, "piso": piso, "fecha_techo": fechas[idx_techo],
                       "fecha_piso": fechas[idx_piso], "fin_idx": k})
        i = k if k > idx_techo else idx_techo + 1

    if not cajas:
        return {"detectado": False, "caja_actual": None}

    caja_actual = cajas[-1]
    techo, piso = caja_actual["techo"], caja_actual["piso"]
    precio_actual, volumen_actual = data["Close"].iloc[-1], data["Volume"].iloc[-1]
    vol_mm50 = data["Volume"].rolling(50).mean().iloc[-1]

    ancho_caja_pct = (techo - piso) / piso * 100
    breakout = bool(precio_actual > techo and volumen_actual > vol_mm50 * 1.3)
    dentro_de_caja = bool(piso <= precio_actual <= techo * (1 + tolerancia_pct / 100))

    criterios = {
        "Caja angosta (ancho <= 15%, consolidación real)": bool(ancho_caja_pct <= 15),
        "Precio dentro o rompiendo la caja actual": bool(dentro_de_caja or breakout),
        "Breakout con volumen (> 1.3x MM50 de volumen)": breakout,
    }

    return {"detectado": True, "caja_actual": caja_actual, "techo": techo, "piso": piso,
            "ancho_caja_pct": ancho_caja_pct, "breakout": breakout, "criterios": criterios}


def _at_analizar_darvas(data):
    resultado = _at_detectar_darvas_box(data)
    adx_actual = data["ADX"].iloc[-1]

    if not resultado["detectado"]:
        resumen = {
            "Método": "Darvas Box",
            "Señal principal": "No se pudo identificar una Caja de Darvas clara con los datos disponibles",
            "ADX(14)": adx_actual,
            "Conclusión": ("No se detectó una secuencia de techo/piso confirmada en la ventana analizada. "
                          "Puede que el activo esté en tendencia demasiado limpia o con demasiada "
                          "volatilidad para formar una caja clásica de Darvas."),
        }
        return resumen, [], []

    criterios = resultado["criterios"]
    cumplidas, total = sum(criterios.values()), len(criterios)
    breakout = resultado["breakout"]

    if breakout and cumplidas == total:
        senal = "BREAKOUT confirmado de la Caja de Darvas – Señal de compra clásica"
    elif breakout:
        senal = "Breakout del techo, pero sin confirmación total (revisar volumen/ancho)"
    elif cumplidas >= total - 1:
        senal = "Precio dentro de una caja angosta – Vigilar breakout inminente"
    else:
        senal = "Caja identificada pero todavía amplia / sin condiciones de breakout"

    if breakout and cumplidas == total:
        conclusion = (f"El precio rompió el techo de la caja (USD {resultado['techo']:.2f}) con volumen por "
                      f"encima del promedio, cumpliendo la regla clásica de Darvas: comprar en la ruptura de "
                      f"una caja angosta con más volumen que lo normal, usando el piso (USD {resultado['piso']:.2f}) "
                      f"como referencia de stop.")
    elif breakout:
        conclusion = ("Hay ruptura del techo, pero la caja no era lo suficientemente angosta o el volumen no "
                      "acompañó del todo. Darvas exigía ambas condiciones; conviene ser cauteloso.")
    else:
        conclusion = (f"El precio se mantiene dentro de la caja actual (piso USD {resultado['piso']:.2f} – "
                      f"techo USD {resultado['techo']:.2f}, ancho {resultado['ancho_caja_pct']:.1f}%). "
                      f"Conviene esperar la ruptura del techo con volumen antes de actuar.")

    resumen = {
        "Método": "Darvas Box", "Señal principal": senal, "Criterios cumplidos": f"{cumplidas}/{total}",
        "Detalle": criterios, "Techo de la caja actual": resultado["techo"],
        "Piso de la caja actual": resultado["piso"], "Ancho de la caja (%)": resultado["ancho_caja_pct"],
        "ADX(14)": adx_actual, "Conclusión": conclusion,
    }
    marcadores = [
        (resultado["caja_actual"]["fecha_techo"], resultado["techo"], "pico"),
        (resultado["caja_actual"]["fecha_piso"], resultado["piso"], "valle"),
    ]
    return resumen, [], marcadores


# ==============================================================
#  MÉTODO 4: WYCKOFF (Acumulación/Distribución)
# ==============================================================

def _at_analizar_wyckoff(data, ventana=90):
    """Aproximación heurística al esquema de Wyckoff usando volumen, spread
    y posición del precio dentro del rango reciente. No sustituye una
    lectura barra-por-barra de eventos (Spring, Test, UTAD, SOS, SOW)."""
    sub = data.tail(ventana).copy()
    precio, mm50 = data["Close"].iloc[-1], data["MM50"].iloc[-1]
    mm50_hace_20 = data["MM50"].iloc[-21] if len(data) > 21 else np.nan
    tendencia_mm50 = "ascendente" if (not np.isnan(mm50_hace_20) and mm50 > mm50_hace_20) else "descendente"

    maximo_rango, minimo_rango = sub["High"].max(), sub["Low"].min()
    rango_total = maximo_rango - minimo_rango
    posicion_en_rango = (precio - minimo_rango) / rango_total * 100 if rango_total > 0 else 50

    spread = sub["High"] - sub["Low"]
    compresion = bool(spread.tail(15).mean() < spread.mean() * 0.8)

    vol_mm50_serie = data["Volume"].rolling(50).mean()
    dias_climax = sub[sub["Volume"] > vol_mm50_serie.reindex(sub.index) * 2]
    hay_climax_reciente = bool(len(dias_climax.tail(15)) > 0)

    if compresion and posicion_en_rango <= 35 and tendencia_mm50 == "descendente":
        fase = "Posible Acumulación"
        descripcion = ("El precio lateraliza en la parte baja de su rango reciente, con contracción de "
                       "volatilidad tras una tendencia bajista. " +
                       ("Se detectó volumen de clímax reciente (posible Selling Climax / Spring)."
                        if hay_climax_reciente else "Todavía sin un clímax de volumen claro que confirme el piso."))
    elif not compresion and posicion_en_rango >= 60 and tendencia_mm50 == "ascendente" and precio > mm50:
        fase = "Markup (Tendencia alcista)"
        descripcion = ("El precio está en la parte alta de su rango reciente, con la MM50 ascendente. "
                       "Fase de tendencia alcista activa (expansión de rango).")
    elif compresion and posicion_en_rango >= 65 and tendencia_mm50 == "ascendente":
        fase = "Posible Distribución"
        descripcion = ("El precio lateraliza en la parte alta de su rango tras una suba, con contracción de "
                       "volatilidad. " +
                       ("Se detectó volumen de clímax reciente (posible Buying Climax / UTAD)."
                        if hay_climax_reciente else "Todavía sin un clímax de volumen claro que confirme el techo."))
    elif not compresion and posicion_en_rango <= 40 and tendencia_mm50 == "descendente" and precio < mm50:
        fase = "Markdown (Tendencia bajista)"
        descripcion = ("El precio está en la parte baja de su rango reciente, con la MM50 descendente. "
                       "Fase de tendencia bajista activa.")
    else:
        fase = "Fase indefinida / transición"
        descripcion = ("La combinación de rango, volumen y tendencia no encaja claramente en ninguna de las "
                       "4 fases clásicas de Wyckoff con los umbrales usados acá.")

    conclusiones = {
        "Posible Acumulación": ("El activo muestra señales compatibles con una fase de Acumulación: "
                                 "lateralización tras la baja, con contracción de volatilidad. Si aparece un "
                                 "clímax de volumen seguido de un Spring y un Test exitoso, sería la "
                                 "confirmación clásica para buscar el inicio del Markup."),
        "Markup (Tendencia alcista)": ("El activo está en Markup: tendencia alcista confirmada con expansión "
                                        "de rango y precio en la parte alta de su banda reciente. Es la fase "
                                        "que Wyckoff considera para mantener o sumar posiciones."),
        "Posible Distribución": ("El activo muestra señales compatibles con una fase de Distribución: "
                                  "lateralización tras la suba, en la parte alta del rango, con contracción "
                                  "de volatilidad. Si aparece un clímax de volumen y luego un UTAD fallido, "
                                  "sería la confirmación clásica de un techo antes del Markdown."),
        "Markdown (Tendencia bajista)": ("El activo está en Markdown: tendencia bajista confirmada, con "
                                          "precio en la parte baja de su rango reciente. Conviene evitar "
                                          "compras y esperar señales de Acumulación."),
        "Fase indefinida / transición": ("No hay una fase de Wyckoff clara todavía. Conviene esperar más "
                                          "definición en el rango y el volumen antes de sacar conclusiones."),
    }

    resumen = {
        "Método": "Wyckoff (Acumulación/Distribución) — aproximación algorítmica", "Señal principal": fase,
        "Descripción": descripcion, "Posición dentro del rango reciente (%)": posicion_en_rango,
        "Tendencia MM50": tendencia_mm50, "Compresión de volatilidad reciente": compresion,
        "Clímax de volumen detectado (últimos 15d)": hay_climax_reciente,
        "Máximo del rango analizado": maximo_rango, "Mínimo del rango analizado": minimo_rango,
        "ADX(14)": data["ADX"].iloc[-1], "Conclusión": conclusiones[fase],
    }
    return resumen, [("MM50", data["MM50"])], []


# ==============================================================
#  DISPATCH
# ==============================================================

def _at_analizar(metodo, data, benchmark_data=None):
    if metodo == "weinstein":
        return _at_analizar_weinstein(data)
    elif metodo == "oneil":
        return _at_analizar_oneil(data, benchmark_data)
    elif metodo == "darvas":
        return _at_analizar_darvas(data)
    elif metodo == "wyckoff":
        return _at_analizar_wyckoff(data)
    raise ValueError("Método no reconocido")


# ==============================================================
#  GRÁFICO (Plotly, mismo estilo oscuro que el resto de la app)
# ==============================================================

def _at_fig_precio(data, lineas_extra, marcadores_extra, titulo):
    paleta = ['#3a7bd5', '#e3b341', '#a371f7', '#39c5cf']
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=data.index, y=data["Close"], mode='lines', name='Precio cierre',
                              line=dict(color='#e6edf3', width=1.6)))
    for i, (etiqueta, serie) in enumerate(lineas_extra):
        fig.add_trace(go.Scatter(x=data.index, y=serie, mode='lines', name=etiqueta,
                                  line=dict(color=paleta[i % len(paleta)], width=1.2, dash='dash')))
    for fecha, precio_marca, tipo in marcadores_extra:
        es_pico = tipo == "pico"
        fig.add_trace(go.Scatter(x=[fecha], y=[precio_marca], mode='markers',
                                  marker=dict(color='#f85149' if es_pico else '#3fb950',
                                              symbol='triangle-down' if es_pico else 'triangle-up', size=12),
                                  name='Techo caja' if es_pico else 'Piso caja', showlegend=True))
    fig.update_layout(
        plot_bgcolor='#0d1117', paper_bgcolor='#07090f', font=dict(color='#b0bcd0', family='Inter, sans-serif'),
        title=dict(text=titulo, font=dict(color='#e6edf3', size=14)),
        xaxis=dict(title='Fecha', gridcolor='#21262d'), yaxis=dict(title='Precio', gridcolor='#21262d'),
        height=460, margin=dict(l=10, r=10, t=45, b=30), legend=dict(orientation='h', y=-0.2),
    )
    return fig


# ==============================================================
#  TARJETA DE RESUMEN (mismo lenguaje visual que el resto de la app)
# ==============================================================

def _at_tarjeta_resumen(resumen):
    detalle = resumen.get("Detalle")
    lineas_check = ''
    if isinstance(detalle, dict):
        lineas_check = ''.join(
            f'<div style="font-size:11px;color:{"#3fb950" if cumple else "#f85149"};padding:2px 0">'
            f'{"✅" if cumple else "❌"} {cond}</div>'
            for cond, cumple in detalle.items()
        )

    metricas = []
    for k, v in resumen.items():
        if k in ("Método", "Señal principal", "Detalle", "Conclusión", "Descripción"):
            continue
        if v is None:
            continue
        val_fmt = f"{v:,.2f}" if isinstance(v, float) else str(v)
        metricas.append(f'<span style="display:inline-block;background:#0d1117;border:1px solid #21262d;'
                         f'border-radius:6px;padding:4px 10px;margin:3px 6px 3px 0;font-size:11px;'
                         f'color:#e6edf3;font-family:JetBrains Mono,monospace">{k}: {val_fmt}</span>')

    descripcion_html = f'<div style="font-size:12px;color:#8b949e;margin:8px 0">{resumen["Descripción"]}</div>' \
        if resumen.get("Descripción") else ''
    criterios_html = f'<div style="font-size:12px;color:#6b7d9a;margin:4px 0 8px 0">' \
                     f'Criterios cumplidos: <b style="color:#e6edf3">{resumen["Criterios cumplidos"]}</b></div>' \
        if resumen.get("Criterios cumplidos") else ''

    st.markdown(f"""
    <div style="background:#0d1117;border:1px solid #21262d;border-left:3px solid #6CC24A;
         border-radius:8px;padding:16px 20px;margin-bottom:14px">
      <div style="color:#6b7d9a;font-size:11px;text-transform:uppercase;letter-spacing:0.5px">{resumen['Método']}</div>
      <div style="color:#e6edf3;font-size:16px;font-weight:700;margin:4px 0 8px 0">{resumen['Señal principal']}</div>
      {descripcion_html}
      {criterios_html}
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:2px 16px;margin-bottom:8px">{lineas_check}</div>
      <div>{''.join(metricas)}</div>
      <div style="margin-top:12px;padding-top:12px;border-top:1px solid #21262d;font-size:13px;color:#f5f7fa">
        <b style="color:#6CC24A">Conclusión:</b> {resumen['Conclusión']}
      </div>
    </div>
    """, unsafe_allow_html=True)


# ==============================================================
#  ENTRY POINT — llamar esto desde el archivo principal
#  (reemplaza a modulo_sector_rotation / modulo_commodities_rotation /
#   modulo_cripto_rotation / modulo_indices_rotation)
#
#  Sin Supabase: no recibe supabase/user_id y no persiste nada.
# ==============================================================

def modulo_analisis_tecnico(PLOTLY_CONFIG=None, benchmark=BENCHMARK_DEFAULT):
    """Análisis técnico de un activo con 4 métodos clásicos: Stan Weinstein,
    William O'Neil, Darvas Box y Wyckoff. El ADX de Wilder se calcula
    siempre como filtro/dato transversal. El activo se elige desde las
    categorías de tu configuración (acciones por industria, forex,
    índices/países, ETFs de índice, ETFs de sector/subsector, mercados
    reales) o como ticker manual. No se guarda ningún historial."""

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1420 0%,#0a1c30 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #6CC24A;
         border-radius:14px; padding:26px 30px; margin-bottom:22px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">📐 Análisis Técnico</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Analizá cualquier activo de tu universo con 4 métodos técnicos clásicos:
        <b style="color:#e6edf3">Stan Weinstein</b> (fases de mercado), <b style="color:#e6edf3">William O'Neil</b>
        (CANSLIM técnico / fuerza relativa), <b style="color:#e6edf3">Darvas Box</b> (cajas de consolidación +
        breakout) y <b style="color:#e6edf3">Wyckoff</b> (acumulación/distribución). El ADX de Wilder se calcula
        siempre como filtro de tendencia. Este análisis no se guarda: vive solo en la sesión actual.
      </div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns([2, 2])
    with col1:
        ticker, etiqueta_activo = _at_seleccionar_ticker()
    with col2:
        metodo_label = st.selectbox('Método de análisis', list(METODOS_DISPONIBLES.keys()), key='at_metodo')
    metodo = METODOS_DISPONIBLES[metodo_label]

    if not ticker:
        st.info('Seleccioná o ingresá un activo para analizar.')
        return

    with st.spinner(f'Descargando datos de {ticker}...'):
        data = _at_descargar(ticker)

    if data is None or data.empty:
        st.error(f'No se pudieron descargar datos para {ticker}. Verificá el ticker.')
        return
    if len(data) < 60:
        st.error(f'{ticker} tiene muy poca historia ({len(data)} velas) para un análisis técnico confiable.')
        return
    if len(data) < 210:
        st.warning(f'⚠️ {ticker} tiene solo {len(data)} velas diarias de historial. Los criterios que usan '
                   f'MM150/MM200 pueden no ser confiables (activo joven / poca historia).')

    data = _at_agregar_medias(data)
    data["+DI"], data["-DI"], data["ADX"] = _at_calcular_adx(data)

    benchmark_data = None
    if metodo == 'oneil':
        with st.spinner('Descargando benchmark de mercado...'):
            benchmark_data = _at_descargar(benchmark)
        if benchmark_data is None:
            st.info('No se pudo descargar el benchmark — el RS Rating no estará disponible para este análisis.')

    resumen, lineas_extra, marcadores_extra = _at_analizar(metodo, data, benchmark_data)

    cols = st.columns(3)
    with cols[0]:
        st.metric('Último cierre', f"${data['Close'].iloc[-1]:,.2f}")
    with cols[1]:
        st.metric('ADX(14)', f"{data['ADX'].iloc[-1]:.1f}")
    with cols[2]:
        st.metric('Fecha del dato', data.index[-1].strftime('%Y-%m-%d'))

    tab_resumen, tab_grafico = st.tabs(['🧾 Resumen y señal', '📈 Gráfico'])

    with tab_resumen:
        _at_tarjeta_resumen(resumen)

    with tab_grafico:
        fig = _at_fig_precio(data, lineas_extra, marcadores_extra, f"{resumen['Método']} — {etiqueta_activo}")
        st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
