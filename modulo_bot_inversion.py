# ==============================================================
#  MÓDULO BOT DE INVERSIÓN — v8: Motor de Pila de EMAs (9/20/50/200/
#  300/400/500) con objetivo y Stop PROGRESIVOS. Reemplaza por
#  completo el motor anterior de puntaje (SMA50/200/300 + Stop
#  "método Andy" con ATR). Estrategia LONG-ONLY, de tendencia pura.
#
#  Medias usadas: EMA9 (muy corto plazo), EMA20 (confirmación de
#  impulso), EMA50 (activación de la operación / primer Stop),
#  EMA200 (1er objetivo), EMA300 (2do objetivo), EMA400 (3er
#  objetivo), EMA500 (tendencia de muy largo plazo).
#
#  📈 ENTRADA (COMPRA) — solo si se cumple TODO:
#     1) Cruce alcista reciente: EMA9 cruza por encima de EMA20.
#     2) Pila alcista corta:     EMA9 > EMA20 > EMA50.
#     3) Precio > EMA50.
#     4) RSI(14) > 55 (veto si > 75, demasiado extendido).
#     5) MACD alcista: cruce de la línea MACD sobre la señal
#        (reciente) con histograma positivo.
#     Opcional (recomendado): exigir además que las medias largas
#     estén alineadas — EMA50 > EMA200 > EMA300 > EMA400 > EMA500 —
#     para evitar señales falsas en mercados laterales.
#
#  🎯 OBJETIVO Y STOP PROGRESIVOS (nunca baja, solo sube)
#     Al comprar:            Stop = EMA50   · Objetivo = EMA200.
#     Cierra sobre EMA200 →  Stop = EMA200  · Objetivo = EMA300.
#     Cierra sobre EMA300 →  Stop = EMA300  · Objetivo = EMA400.
#     Cierra sobre EMA400 →  Stop = EMA400  · Objetivo = EMA500.
#     Cierra sobre EMA500 →  Stop = EMA500  · Sin objetivo fijo:
#       se mantiene la posición mientras el precio siga sobre la
#       EMA500 (podría seguir subiendo mucho más).
#     Mientras el precio no supere el objetivo vigente, NO se
#     vende — simplemente se mantiene la posición. El Stop en cada
#     tramo sigue el valor actual de su EMA (trailing), pero jamás
#     se afloja hacia abajo.
#
#  📉 SALIDA (VENTA) — pérdida de fuerza de la tendencia:
#     EMA9 cruza por debajo de EMA20 Y además EMA9 < EMA50 Y
#     EMA20 < EMA50 (pila EMA9 < EMA20 < EMA50). Esto cierra la
#     posición aunque el Stop todavía no se haya tocado.
#
#  Timeframes: 15, 30, 45 minutos, 1h, 4h y 1 día. Pensá 1 día como
#  marco de tendencia principal y 4h como marco de entrada — si
#  coinciden, mejor probabilidad.
#
#  Auto-actualización: si está instalado streamlit-autorefresh
#  (pip install streamlit-autorefresh), la pantalla se refresca sola
#  cada 5 minutos mientras haya un análisis corriendo, sin tocar el
#  botón "Actualizar".
#
#  Selección por sector: además de elegir activos uno por uno, se
#  puede elegir una industria completa (ACCIONES_POR_INDUSTRIA) y el
#  bot analiza automáticamente todos los tickers de esa lista.
# ==============================================================

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

try:
    from streamlit_autorefresh import st_autorefresh
    _AUTOREFRESH_DISPONIBLE = True
except ImportError:
    _AUTOREFRESH_DISPONIBLE = False

MAX_ACTIVOS_BOT = 10
MAX_ACTIVOS_SECTOR = 40  # tope al elegir "por sector/industria" (las listas tienen hasta ~50 tickers)

CAPITAL_MINIMO_BOT = 50.0
CAPITAL_INICIAL_BOT_DEFAULT = 100.0
APALANCAMIENTOS_BOT = [1, 2, 3, 4, 5]

# yfinance: hasta 60 días de historia para 15m/30m, hasta 730 días
# para 60m. Sin intervalos nativos de 45min/4h: se resamplean desde
# 15m y 60m respectivamente. '1 día' usa 2 años de historia (~500
# velas), suficiente para la SMA300.
HORIZONTES_BOT = {
    '15 minutos': dict(interval='15m', periodo_descarga='60d', resample=None, minutos_vela=15),
    '30 minutos': dict(interval='30m', periodo_descarga='60d', resample=None, minutos_vela=30),
    '45 minutos': dict(interval='15m', periodo_descarga='60d', resample='45min', minutos_vela=45),
    '1 hora': dict(interval='60m', periodo_descarga='730d', resample=None, minutos_vela=60),
    '4 horas': dict(interval='60m', periodo_descarga='730d', resample='4h', minutos_vela=240),
    '1 día': dict(interval='1d', periodo_descarga='2y', resample=None, minutos_vela=1440),
}

# ── Activos por sector/industria — para el modo "elegir por sector" ────
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
    'Retail':             ['AMZN','WMT','TGT','COST','HD','LOW','TJX','ROST','DG','DLTR', 'BBY','KR','BJ','WBA','CVS','ULTA','M','KSS','JWN','GPS', 'BURL','FIVE','WSM','RH','ORLY','AZO','AAP','TSCO','OLLI', 'FND','TPR','RL','NKE','DECK','CROX','LEVI','PVH','URBN','AEO'],
    'Autos':              ['TSLA','GM','F','TM','HMC','STLA','RIVN','LCID','NIO','XPEV', 'LI','FCAU','MBGYY','BMWYY','VWAGY','RACE','APTV','BWA', 'VC','GT','LEA','ALV','HOG','PII','THO','MBLY','ZK','XPEL'],
    'Hotelería/Viajes':   ['MAR','HLT','H','IHG','ABNB','BKNG','EXPE','RCL','CCL','NCLH', 'TRIP','DESP','TCOM','LVS','MGM','WYNN','CZR','SIX','PLAY', 'DKNG','BALY','VAC','WH','HGV','SVC','PK'],
    'E-commerce':         ['AMZN','SHOP','ETSY','EBAY','MELI','SE','PDD','BABA','JD','CPNG', 'W','CVNA','OSTK','WISH','BZUN','EXFY','REAL','GRPN','WIX','DOCN', 'FVRR','UPWK','RBLX','TTD','APP','NET','GTLB','FSLY','BIGC','BOX'],
    'Alimentos':          ['KO','PEP','MDLZ','KHC','GIS','CPB','SJM','K','KDP','HSY', 'TSN','HRL','ADM','BG','CHD','CLX','CAG','POST','MKC', 'EL','PG','UL','NOMD','LANC','COKE','FLO','DAR','INGR','SMPL'],
    'Bebidas':            ['KO','PEP','MNST','STZ','BUD','TAP','DEO','KDP','CELH','FIZZ', 'PRMW','CCEP','FMX','SAM','BFB','WULF','COKE','NAPA', 'VIV','BRBR','SPB','SOVO','REX','KOF','ABEV','CCU','AGRO','COTY'],
    'Minería Oro':        ['NEM','GOLD','AEM','WPM','KGC','PAAS','AG','CDE','HL','SSRM', 'NGD','AUX','DRD','BTG','EGO','HMY','IAG','AU','SA','GFI', 'OR','FNV','RGLD','KNT','WDO','EQX','TGB','SILV','BVN','CGAU'],
    'Cobre/Metales':      ['FCX','SCCO','TECK','HBM','NUE','STLD','CLF','AA','CDE', 'KGC','PAAS','AG','HL','WPM','AEM','NEM','GOLD','SSRM','NGD', 'ERO','LUNMF','LAC','ALB','PLL','MP','CRS','ATI','X','HBM','TECK'],
    'Químicos':           ['LIN','APD','DD','DOW','LYB','EMN','CE','IFF','PPG','SHW', 'ECL','ALB','FMC','CF','MOS','NTR','OLN','ASH','AVNT','HUN', 'X','BC','RPM','WLK','TSE','SXT','SCL','NEU','IOSP','CBT'],
    'Acero':              ['NUE','STLD','CLF','X','MT','RS','CMC','SID','GGB','TX', 'PKX','NWL','CRS','ATI','SCHN','ZEUS','NBR'],
    'Eléctricas':         ['NEE','DUK','SO','D','AEP','EXC','XEL','ED','ETR','PEG', 'PCG','PPL','FE','ES','EIX','AES','CNP','NI','ATO','LNT', 'WEC','CMS','DTE','SRE','EVRG','IDA','BEP','BEPC','NEP', 'ORA','UGI','BIP','BIPC','AVA','PNW','NRG','CVA'],
    'Agua':               ['AWK','WTRG','AWR','YORW','MSEX','SJW','CWCO','GWRS','ARTNA', 'PNW','CWT','WSO','AQUA','ECL','XYL','PUMP','GRC','MEG','H2O','PRMW'],
    'REIT Comercial':     ['SPG','O','VICI','NNN','BXP','KIM','REG','MAC','PEAK','FRT', 'SLG','EPR','WPC','ARE','HST','PK','VNO','CUZ','HIW','KRC', 'DEI','BRX','ADC','STAG','PLD','EQIX','DLR','CONE','COR','AMT', 'CCI','SBAC','WY','IRM','GOOD','LAND'],
    'REIT Industrial':    ['PLD','AMT','CCI','DLR','EQIX','STAG','EGP','FR','REXR','TRNO', 'PLYM','LXP','COLD','ILPT','PSTL','IRM','CUBE','GOOD','O'],
    'REIT Residencial':   ['EQR','AVB','ESS','MAA','UDR','CPT','ELS','AIV','NXRT','INVH', 'IRT','AMH','BRG','SUI','MHC','UMH','AIRC','CUBE'],
    'Telecomunicaciones': ['T','VZ','TMUS','S','CHTR','CMCSA','LUMN','FYBR','VOD','BT', 'ORAN','TEF','TU','BCE','RCI','SKM','ZL','AMX','TIGO','TDS', 'ATUS','WOW','CNSL','QCOM','AMT','CCI','SBAC','WBD','NFLX','DIS'],
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

C_COMPRA        = '#3fb950'
C_VENTA         = '#f85149'
C_EN_POSICION   = '#2dd4bf'

# Niveles de objetivo/Stop progresivos, en orden. El índice 0 es el
# tramo inicial (Stop=EMA50, Objetivo=EMA200); al superar el objetivo
# de un tramo se pasa al siguiente. El último tramo (EMA500) no tiene
# objetivo: se mantiene la posición sin techo fijo.
NIVELES_STOP     = ['ema50', 'ema200', 'ema300', 'ema400', 'ema500']
NIVELES_OBJETIVO = ['ema200', 'ema300', 'ema400', 'ema500', None]

MIN_BARRAS_NECESARIAS = 520  # EMA500 + margen de calentamiento


# ── Indicadores ─────────────────────────────────────────────────

def _ema(series, length):
    return series.ewm(span=length, adjust=False).mean()


def _rsi_wilder(close, length=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(length).mean()
    avg_loss = loss.rolling(length).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def _macd(close, fast=12, slow=26, signal=9):
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist





# ── Motor de señales (pila de EMAs 9/20/50/200/300/400/500) ─────

def _calcular_bot_dataframe_ma(close, high, low, volume,
                                 rsi_periodo, macd_fast, macd_slow, macd_signal,
                                 cruce_lookback_barras, exigir_alineacion_larga):
    """Calcula todos los indicadores y las señales de COMPRA/VENTA
    para cada barra según la estrategia de pila de EMAs. No mira
    hacia adelante: todo se calcula con datos disponibles hasta la
    barra actual.

    COMPRA: cruce alcista reciente EMA9/EMA20, pila EMA9>EMA20>EMA50,
    precio sobre EMA50, RSI>55 (veto si RSI>75) y MACD alcista
    (cruce reciente + histograma positivo). Si `exigir_alineacion_larga`
    está activo, además pide EMA50>EMA200>EMA300>EMA400>EMA500.

    VENTA (pérdida de fuerza): cruce bajista reciente EMA9/EMA20 y
    pila EMA9<EMA20<EMA50. Esta señal también se usa, barra a barra
    (no solo en el disparo), como gatillo de salida dentro de la
    simulación de operaciones.
    """
    cl = close.dropna()
    hi = high.reindex(cl.index)
    lo = low.reindex(cl.index)
    volume = volume.reindex(cl.index) if volume is not None else None  # se conserva el parámetro por compatibilidad, no se usa como filtro

    ema9 = _ema(cl, 9)
    ema20 = _ema(cl, 20)
    ema50 = _ema(cl, 50)
    ema200 = _ema(cl, 200)
    ema300 = _ema(cl, 300)
    ema400 = _ema(cl, 400)
    ema500 = _ema(cl, 500)
    rsi_valor = _rsi_wilder(cl, rsi_periodo)
    macd_line, macd_signal_line, macd_hist = _macd(cl, macd_fast, macd_slow, macd_signal)

    # ── Paso 1: cruce de EMA9/EMA20 (confirmación de entrada/salida) ──
    cross_up_9_20 = (ema9 > ema20) & (ema9.shift(1) <= ema20.shift(1))
    cross_up_9_20_reciente = cross_up_9_20.rolling(cruce_lookback_barras, min_periods=1).max().astype(bool)
    cross_down_9_20 = (ema9 < ema20) & (ema9.shift(1) >= ema20.shift(1))
    cross_down_9_20_reciente = cross_down_9_20.rolling(cruce_lookback_barras, min_periods=1).max().astype(bool)

    # ── Pila corta de EMAs ──
    pila_alcista = (ema9 > ema20) & (ema20 > ema50)
    pila_bajista = (ema9 < ema20) & (ema20 < ema50)

    precio_sobre_ema50 = cl > ema50
    precio_bajo_ema50 = cl < ema50

    # ── RSI: solo veta malas entradas ──
    rsi_ok_compra = rsi_valor > 55
    rsi_veto_compra = rsi_valor > 75

    # ── MACD: debe confirmar ──
    macd_cross_up = (macd_line > macd_signal_line) & (macd_line.shift(1) <= macd_signal_line.shift(1))
    macd_cross_up_reciente = macd_cross_up.rolling(cruce_lookback_barras, min_periods=1).max().astype(bool)
    macd_alcista = macd_cross_up_reciente & (macd_hist > 0)

    macd_cross_down = (macd_line < macd_signal_line) & (macd_line.shift(1) >= macd_signal_line.shift(1))
    macd_cross_down_reciente = macd_cross_down.rolling(cruce_lookback_barras, min_periods=1).max().astype(bool)
    macd_bajista = macd_cross_down_reciente & (macd_hist < 0)

    # ── Mejora opcional: alineación de las medias largas ──
    alineacion_larga_alcista = (ema50 > ema200) & (ema200 > ema300) & (ema300 > ema400) & (ema400 > ema500)
    alineacion_larga_bajista = (ema50 < ema200) & (ema200 < ema300) & (ema300 < ema400) & (ema400 < ema500)

    entrada_compra = (
        cross_up_9_20_reciente & pila_alcista & precio_sobre_ema50 &
        rsi_ok_compra & (~rsi_veto_compra) & macd_alcista
    )
    if exigir_alineacion_larga:
        entrada_compra = entrada_compra & alineacion_larga_alcista

    # La señal de venta (pérdida de fuerza) es la condición "dura" del
    # enunciado: cruce bajista EMA9/EMA20 + pila EMA9<EMA20<EMA50. No
    # se le exige RSI/MACD para no demorar una salida de riesgo.
    senal_venta = cross_down_9_20_reciente & pila_bajista & precio_bajo_ema50

    estado = pd.Series('—', index=cl.index)
    estado[entrada_compra] = 'COMPRA'
    estado[senal_venta] = 'VENTA'
    disparo = (estado != '—') & (estado != estado.shift(1))

    df = pd.DataFrame({
        'precio': cl, 'high': hi, 'low': lo,
        'ema9': ema9, 'ema20': ema20, 'ema50': ema50,
        'ema200': ema200, 'ema300': ema300, 'ema400': ema400, 'ema500': ema500,
        'rsi': rsi_valor, 'macd': macd_line, 'macd_signal': macd_signal_line, 'macd_hist': macd_hist,
        'pila_alcista': pila_alcista, 'pila_bajista': pila_bajista,
        'alineacion_larga_alcista': alineacion_larga_alcista,
        'alineacion_larga_bajista': alineacion_larga_bajista,
        'rsi_veto_compra': rsi_veto_compra,
        'macd_alcista': macd_alcista, 'macd_bajista': macd_bajista,
        'senal_venta': senal_venta,
        'estado': estado, 'disparo': disparo,
    })
    return df


# ── Simulación de operaciones — Objetivo y Stop progresivos ──────
#  Compra → Stop=EMA50, Objetivo=EMA200
#  Cierra sobre EMA200 → Stop=EMA200, Objetivo=EMA300
#  Cierra sobre EMA300 → Stop=EMA300, Objetivo=EMA400
#  Cierra sobre EMA400 → Stop=EMA400, Objetivo=EMA500
#  Cierra sobre EMA500 → Stop=EMA500, sin objetivo (se mantiene)
#  El Stop de cada tramo sigue el valor actual de su EMA (trailing)
#  pero JAMÁS se afloja hacia abajo. La posición se cierra si el
#  precio toca el Stop vigente, o si aparece la señal de venta
#  (pérdida de fuerza: EMA9<EMA20<EMA50), lo que ocurra primero.

def _simular_operaciones_ma(df):
    df = df.copy()
    n = len(df)
    idx = df.index
    precio_arr = df['precio'].values
    high_arr = df['high'].values
    low_arr = df['low'].values
    estado_arr = df['estado'].values
    disparo_arr = df['disparo'].values
    senal_venta_arr = df['senal_venta'].values

    arr_por_nombre = {
        'ema50': df['ema50'].values, 'ema200': df['ema200'].values,
        'ema300': df['ema300'].values, 'ema400': df['ema400'].values,
        'ema500': df['ema500'].values,
    }

    resultado = [''] * n
    resultado_teorico = [''] * n
    fecha_cierre = [pd.NaT] * n
    retorno_pct = [np.nan] * n
    tomada = [False] * n
    motivo_cierre = [''] * n
    stop_final_arr = [np.nan] * n
    nivel_alcanzado_arr = [''] * n

    ocupado_hasta = -1

    for i in range(n):
        if not disparo_arr[i] or estado_arr[i] != 'COMPRA':
            continue
        if pd.isna(arr_por_nombre['ema50'][i]):
            continue

        fue_tomada = i > ocupado_hasta
        tomada[i] = fue_tomada

        entry = precio_arr[i]
        nivel_idx = 0
        stop_col = NIVELES_STOP[nivel_idx]        # 'ema50'
        objetivo_col = NIVELES_OBJETIVO[nivel_idx]  # 'ema200'
        stop = arr_por_nombre[stop_col][i]
        nivel_texto = 'Inicial (Stop EMA50 · Objetivo EMA200)'

        j_exit = n - 1
        precio_exit = precio_arr[n - 1]
        motivo = 'Fin de datos (operación en curso)'

        for j in range(i + 1, n):
            hi_j, lo_j, cl_j = high_arr[j], low_arr[j], precio_arr[j]

            # 1) Actualizar el Stop del tramo vigente (trailing, solo sube)
            candidato_stop = arr_por_nombre[stop_col][j]
            if not pd.isna(candidato_stop):
                stop = max(stop, candidato_stop)

            # 2) ¿Tocó el Stop?
            if lo_j <= stop:
                precio_exit, j_exit, motivo = stop, j, f'Tocó Stop ({stop_col.upper()})'
                break

            # 3) ¿Señal de venta por pérdida de fuerza?
            if senal_venta_arr[j]:
                precio_exit, j_exit, motivo = cl_j, j, 'Señal de venta (EMA9<EMA20<EMA50)'
                break

            # 4) ¿Rompió el objetivo vigente? → sube de tramo
            if objetivo_col is not None:
                objetivo_val = arr_por_nombre[objetivo_col][j]
                if not pd.isna(objetivo_val) and cl_j > objetivo_val:
                    nivel_idx += 1
                    stop_col = NIVELES_STOP[nivel_idx]
                    objetivo_col = NIVELES_OBJETIVO[nivel_idx]
                    nuevo_stop_val = arr_por_nombre[stop_col][j]
                    if not pd.isna(nuevo_stop_val):
                        stop = max(stop, nuevo_stop_val)
                    nivel_texto = (f'Rompió {stop_col.upper()} · Objetivo {objetivo_col.upper()}'
                                   if objetivo_col else f'Rompió {stop_col.upper()} · sin objetivo fijo (tendencia)')

        if motivo != 'Fin de datos (operación en curso)':
            ret = (precio_exit - entry) / entry * 100
            res = '✅' if ret > 0 else ('❌' if ret < 0 else '➖')
            fecha_cierre_val = idx[j_exit]
        else:
            ret = np.nan
            res = '⏳'
            fecha_cierre_val = pd.NaT

        if fue_tomada:
            resultado[i] = res
            ocupado_hasta = j_exit if motivo != 'Fin de datos (operación en curso)' else ocupado_hasta
        else:
            resultado[i] = '⛔'
            resultado_teorico[i] = res

        retorno_pct[i] = ret
        fecha_cierre[i] = fecha_cierre_val
        motivo_cierre[i] = motivo
        stop_final_arr[i] = stop
        nivel_alcanzado_arr[i] = nivel_texto

    df['direccion'] = ['compra' if e == 'COMPRA' else '' for e in estado_arr]
    df['resultado'] = resultado
    df['resultado_teorico'] = resultado_teorico
    df['fecha_cierre'] = fecha_cierre
    df['retorno_pct'] = retorno_pct
    df['tomada'] = tomada
    df['motivo_cierre'] = motivo_cierre
    df['stop_final'] = stop_final_arr
    df['nivel_alcanzado'] = nivel_alcanzado_arr
    return df


def _color_resultado(val):
    return {'✅': 'color:#3fb950;font-weight:700', '❌': 'color:#f85149;font-weight:700',
            '⏳': 'color:#e3b341;font-weight:600', '➖': 'color:#8b949e;font-weight:600'}.get(val, '')


# ── Persistencia en Supabase: configuración del usuario ─────────

def _bot_obtener_config(supabase, user_id):
    try:
        res = supabase.table('bot_config_usuario').select('*').eq('user_id', user_id).limit(1).execute()
        if res.data:
            return res.data[0]
    except Exception:
        pass
    return {'capital_inicial': CAPITAL_INICIAL_BOT_DEFAULT, 'pct_por_operacion': 10.0, 'apalancamiento': 1}


def _bot_guardar_config(supabase, user_id, capital_inicial, pct_por_operacion, apalancamiento):
    try:
        supabase.table('bot_config_usuario').upsert({
            'user_id': user_id, 'capital_inicial': float(capital_inicial),
            'pct_por_operacion': pct_por_operacion,
            'apalancamiento': int(apalancamiento),
            'actualizado_en': datetime.now().isoformat(),
        }).execute()
    except Exception:
        pass


# ── Simulación de capital — 100% en memoria ─────────────────────

def _bot_simular_en_memoria(df_bot, capital_inicial, pct_por_operacion, apalancamiento):
    disparos = df_bot[df_bot['disparo'] & (df_bot['estado'] != '—') & (df_bot['tomada'] == True)]
    equity = capital_inicial
    curva = [{'fecha': 'Inicio', 'equity': equity}]
    cerradas = ganadoras = abiertas = 0
    montos = {}
    pnl_por_señal = {}

    for ts, row in disparos.iterrows():
        capital_operado = equity * (pct_por_operacion / 100.0)
        montos[ts] = capital_operado
        ret = row['retorno_pct']

        if pd.isna(ret):
            abiertas += 1
            continue

        ganancia = capital_operado * (ret / 100.0) * apalancamiento
        ganancia = max(ganancia, -capital_operado)
        equity += ganancia
        pnl_por_señal[ts] = ganancia
        if ganancia > 0:
            ganadoras += 1
        cerradas += 1
        curva.append({'fecha': ts.strftime('%Y-%m-%d %H:%M'), 'equity': equity})

    return {
        'capital_inicial': capital_inicial, 'capital_actual': equity,
        'rendimiento_pct': (equity / capital_inicial - 1) * 100 if capital_inicial else 0.0,
        'win_rate': (ganadoras / cerradas * 100) if cerradas > 0 else None,
        'cerradas': cerradas, 'ganadoras': ganadoras, 'perdedoras': cerradas - ganadoras,
        'abiertas': abiertas, 'total_señales': len(disparos), 'curva': curva,
        'apalancamiento': apalancamiento, 'montos': montos, 'pnl_por_señal': pnl_por_señal,
    }


# ── Descarga intradía/diaria — TTL corto para que se sienta "en vivo" ──

@st.cache_data(ttl=20, show_spinner=False)
def _descargar_intradia(ticker, periodo, intervalo):
    try:
        import yfinance as yf
        d = yf.download(ticker, period=periodo, interval=intervalo,
                         progress=False, auto_adjust=True)
        if d is None or d.empty:
            return None
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
        if 'Close' not in d.columns:
            cols_close = [c for c in d.columns if 'close' in str(c).lower()]
            if cols_close:
                d = d.rename(columns={cols_close[0]: 'Close'})
            else:
                return None
        return d.dropna(subset=['Close'])
    except Exception:
        return None


def _resamplear_ohlc(df, regla):
    if df is None or df.empty:
        return None
    try:
        agregado = {}
        if 'Open' in df.columns:
            agregado['Open'] = 'first'
        if 'High' in df.columns:
            agregado['High'] = 'max'
        if 'Low' in df.columns:
            agregado['Low'] = 'min'
        if 'Close' not in df.columns:
            return None
        agregado['Close'] = 'last'
        if 'Volume' in df.columns:
            agregado['Volume'] = 'sum'
        out = df.resample(regla).agg(agregado)
        return out.dropna(subset=['Close'])
    except Exception:
        return None


def _fetch_paralelo_bot(tickers, cfg):
    resultados = {}
    with ThreadPoolExecutor(max_workers=min(10, max(len(tickers), 1))) as ex:
        futuros = {
            ex.submit(_descargar_intradia, tk, cfg['periodo_descarga'], cfg['interval']): tk
            for tk in tickers
        }
        for fut in as_completed(futuros):
            tk = futuros[fut]
            resultados[tk] = fut.result()
    return resultados


# ── Gráfico de señales ──────────────────────────────────────────

def _fig_bot_señales(ticker, df, PLOTLY_LAYOUT_BASE):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df['precio'], line=dict(color='#3a7bd5', width=1.3), name='Precio'))
    fig.add_trace(go.Scatter(x=df.index, y=df['ema9'], line=dict(color='#f778ba', width=1, dash='dot'), name='EMA9'))
    fig.add_trace(go.Scatter(x=df.index, y=df['ema20'], line=dict(color='#e3b341', width=1, dash='dot'), name='EMA20'))
    fig.add_trace(go.Scatter(x=df.index, y=df['ema50'], line=dict(color='#a371f7', width=1.2, dash='dot'), name='EMA50 (Stop inicial)'))
    fig.add_trace(go.Scatter(x=df.index, y=df['ema200'], line=dict(color='#3fb950', width=1.2, dash='dash'), name='EMA200 (Obj. 1)'))
    fig.add_trace(go.Scatter(x=df.index, y=df['ema300'], line=dict(color='#2dd4bf', width=1, dash='dash'), name='EMA300 (Obj. 2)'))
    fig.add_trace(go.Scatter(x=df.index, y=df['ema400'], line=dict(color='#58a6ff', width=1, dash='dash'), name='EMA400 (Obj. 3)'))
    fig.add_trace(go.Scatter(x=df.index, y=df['ema500'], line=dict(color='#8b949e', width=1, dash='dash'), name='EMA500 (largo plazo)'))
    for tipo, color, symbol in [
        ('COMPRA', C_COMPRA, 'triangle-up'),
        ('VENTA', C_VENTA, 'triangle-down'),
    ]:
        sub = df[(df['disparo']) & (df['estado'] == tipo)]
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(
            x=sub.index, y=sub['precio'], mode='markers', name=tipo,
            marker=dict(size=12, color=color, symbol=symbol, line=dict(width=1, color='#0d1117')),
        ))
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE,
        title=dict(text=f'{ticker} — Señales del Bot de Inversión (pila de EMAs)', font=dict(size=14)),
        height=480, hovermode='x unified',
        legend=dict(orientation='h', y=1.1),
        xaxis=dict(gridcolor='#21262d'), yaxis=dict(gridcolor='#21262d'),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    return fig


def _color_estado(estado):
    return {'COMPRA': C_COMPRA, 'VENTA': C_VENTA, '—': '#8b949e'}.get(estado, '#8b949e')


def _color_señal_bot(val):
    c = {'COMPRA': C_COMPRA, 'VENTA': C_VENTA}.get(val, '#e6edf3')
    return f'color:{c};font-weight:700'


# ── Módulo principal ────────────────────────────────────────────

def modulo_bot_inversion(
    get_close_series, fmt_precio, score_color_hex, kpi_cards_4,
    chips_navegacion, PLOTLY_LAYOUT_BASE, PLOTLY_CONFIG,
    universo_opciones, universo_mapa, supabase, user_id,
):
    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #6CC24A;
         border-radius:14px; padding:28px 32px; margin-bottom:24px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">🤖 Bot de Inversión — Pila de EMAs (9/20/50/200/300/400/500)</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Estrategia de <b style="color:#e3b341">tendencia pura (long-only)</b>. <b style="color:#e3b341">COMPRA</b>
        cuando hay cruce alcista EMA9/EMA20, se forma la pila EMA9 &gt; EMA20 &gt; EMA50, el precio está
        sobre la EMA50, el RSI supera 55 (se veta si supera 75) y el MACD confirma al alza.
        El <b style="color:#a371f7">objetivo y el Stop son progresivos</b>: arranca con Stop en EMA50 y
        objetivo en EMA200; al cerrar por encima de cada objetivo, el Stop sube a esa misma EMA y el
        objetivo pasa a la siguiente (EMA200 → EMA300 → EMA400 → EMA500) — el Stop nunca baja. Al superar
        la EMA500 ya no hay objetivo fijo: se mantiene la posición mientras el precio siga arriba.
        <b style="color:#e3b341">VENTA</b> (pérdida de fuerza) cuando la pila se invierte: EMA9 cruza
        debajo de EMA20 y ambas quedan debajo de EMA50. Analizá hasta <b style="color:#e3b341">10
        activos</b> en <b style="color:#e3b341">15, 30, 45 min, 1h, 4h o 1 día</b> — comparar la
        tendencia diaria con la entrada en 4h suele dar más probabilidad.
      </div>
    </div>
    """, unsafe_allow_html=True)

    c1, c2 = st.columns([2, 1])
    with c1:
        horizonte_bot = st.selectbox(
            'Temporalidad', list(HORIZONTES_BOT.keys()), index=1, key='bot_horizonte',
        )
    with c2:
        st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)
        if st.button('🔄 Actualizar precios ahora', key='bot_refresh_btn', use_container_width=True):
            _descargar_intradia.clear()
            st.rerun()

    st.markdown('#### 🎯 Activos a analizar')
    modo_seleccion = st.radio(
        '¿Cómo elegís los activos?',
        ['Manual (buscar por nombre/ticker)', 'Por sector/industria (analiza todos)'],
        key='bot_modo_seleccion', horizontal=True,
    )

    if modo_seleccion.startswith('Por sector'):
        sector_elegido = st.selectbox(
            'Elegí un sector/industria', sorted(ACCIONES_POR_INDUSTRIA.keys()),
            key='bot_sector_elegido',
        )
        tickers_bot = list(dict.fromkeys(ACCIONES_POR_INDUSTRIA[sector_elegido]))
        st.caption(f'📦 "{sector_elegido}" tiene {len(tickers_bot)} tickers.')
        if len(tickers_bot) > MAX_ACTIVOS_SECTOR:
            st.warning(
                f'El sector tiene más de {MAX_ACTIVOS_SECTOR} tickers — se analizan solo los '
                f'primeros {MAX_ACTIVOS_SECTOR} (más que eso hace la descarga muy lenta).'
            )
            tickers_bot = tickers_bot[:MAX_ACTIVOS_SECTOR]
        else:
            st.caption(f'Se van a analizar los {len(tickers_bot)} activos completos de este sector.')
    else:
        seleccion = st.multiselect(
            f'Elegí hasta {MAX_ACTIVOS_BOT} activos', universo_opciones,
            default=st.session_state.get('bot_activos_sel', []),
            max_selections=MAX_ACTIVOS_BOT, key='bot_activos_multiselect',
            help='Buscá por nombre o ticker: acciones, ETFs, forex, cripto o commodities.',
        )
        st.session_state['bot_activos_sel'] = seleccion

        manual_extra = st.text_input(
            'Agregar tickers manuales (separados por coma, opcional)',
            key='bot_activos_manual', placeholder='Ej: XYZ, ABC-USD',
        )

        tickers_bot = [universo_mapa.get(s, s) for s in seleccion]
        if manual_extra:
            tickers_bot += [t.strip().upper() for t in manual_extra.split(',') if t.strip()]
        tickers_bot = list(dict.fromkeys(tickers_bot))

        if len(tickers_bot) > MAX_ACTIVOS_BOT:
            st.warning(f'Se seleccionaron más de {MAX_ACTIVOS_BOT} activos — se van a analizar solo los primeros {MAX_ACTIVOS_BOT}.')
            tickers_bot = tickers_bot[:MAX_ACTIVOS_BOT]

    with st.expander('⚙️ Parámetros de la estrategia (opcional, aplican a todos los activos)', expanded=False):
        p1, p2, p3 = st.columns(3)
        with p1:
            st.markdown('**RSI**')
            rsi_periodo = st.number_input('Período RSI', value=14, min_value=2, key='bot_rsi_periodo')
        with p2:
            st.markdown('**MACD**')
            macd_fast = st.number_input('EMA rápida', value=12, min_value=2, key='bot_macd_fast')
            macd_slow = st.number_input('EMA lenta', value=26, min_value=3, key='bot_macd_slow')
            macd_signal = st.number_input('Señal', value=9, min_value=2, key='bot_macd_signal')
        with p3:
            st.markdown('**Confirmación de cruce MACD**')
            cruce_lookback_barras = st.number_input(
                'Válido si el cruce ocurrió en las últimas N barras', value=3, min_value=1,
                key='bot_macd_lookback',
                help='Da un poco de margen para que el resto de las condiciones (medias, RSI) alcancen al cruce.',
            )

        p4, = st.columns(1)
        with p4:
            st.markdown('**Filtro de calidad (opcional)**')
            exigir_alineacion_larga = st.checkbox(
                'Exigir alineación de EMAs largas para comprar (EMA50 > EMA200 > EMA300 > EMA400 > EMA500)',
                value=False, key='bot_exigir_alineacion',
                help='Reduce señales falsas en mercados laterales, a costa de entrar más tarde en la tendencia.',
            )
        st.caption(
            'El Stop y el objetivo NO se configuran acá: son progresivos por diseño de la estrategia '
            '(Stop inicial en EMA50, objetivo EMA200 → EMA300 → EMA400 → EMA500, el Stop nunca baja).'
        )

    analizar_bot = st.button('▶ Analizar', key='bot_run', type='primary')
    if not analizar_bot and not st.session_state.get('bot_run_flag'):
        st.info('Elegí la temporalidad y los activos (manual o por sector), después presioná "Analizar".')
        return
    if analizar_bot:
        st.session_state['bot_run_flag'] = True

    if st.session_state.get('bot_run_flag'):
        if _AUTOREFRESH_DISPONIBLE:
            st_autorefresh(interval=5 * 60 * 1000, key='bot_autorefresh_tick')
        else:
            st.caption(
                '⏱️ Para que esta pantalla se actualice sola cada 5 minutos, instalá el paquete '
                '`streamlit-autorefresh` (`pip install streamlit-autorefresh`) y volvé a cargar la app. '
                'Mientras tanto, seguís pudiendo usar "🔄 Actualizar precios ahora".'
            )

    with st.expander('💰 Capital simulado y apalancamiento', expanded=True):
        cfg_bot_user = _bot_obtener_config(supabase, user_id)
        cb1, cb2, cb3 = st.columns(3)
        with cb1:
            capital_inicial_bot = st.number_input(
                'Capital inicial simulado (USD)', min_value=CAPITAL_MINIMO_BOT,
                value=float(cfg_bot_user.get('capital_inicial', CAPITAL_INICIAL_BOT_DEFAULT)),
                step=10.0, key='bot_capital_inicial',
            )
        with cb2:
            pct_por_operacion_bot = st.number_input(
                '% de capital por operación', min_value=1.0, max_value=100.0,
                value=float(cfg_bot_user.get('pct_por_operacion', 10.0)), step=1.0, key='bot_pct_operacion',
            )
        with cb3:
            apalancamiento_bot = st.select_slider(
                'Apalancamiento a visualizar', options=APALANCAMIENTOS_BOT,
                value=int(cfg_bot_user.get('apalancamiento', 1)) if int(cfg_bot_user.get('apalancamiento', 1)) in APALANCAMIENTOS_BOT else 1,
                key='bot_apalancamiento',
            )
        if st.button('💾 Guardar configuración', key='bot_guardar_config'):
            _bot_guardar_config(supabase, user_id, capital_inicial_bot, pct_por_operacion_bot, apalancamiento_bot)
            st.success('Configuración guardada.')

    if not tickers_bot:
        st.warning('Seleccioná al menos un activo.')
        return

    cfg = HORIZONTES_BOT[horizonte_bot]

    with st.spinner(f'Descargando velas de {horizonte_bot} para {len(tickers_bot)} activo(s)...'):
        precios_raw = _fetch_paralelo_bot(tickers_bot, cfg)

    resultados_bot = {}
    fallidos = []
    for tk in tickers_bot:
        df_raw = precios_raw.get(tk)
        if df_raw is None or df_raw.empty:
            fallidos.append(tk)
            continue
        if cfg.get('resample'):
            df_raw = _resamplear_ohlc(df_raw, cfg['resample'])
            if df_raw is None or df_raw.empty:
                fallidos.append(tk)
                continue
        cl = get_close_series(df_raw)
        if cl is None or len(cl.dropna()) < MIN_BARRAS_NECESARIAS:
            fallidos.append(tk)
            continue
        hi = df_raw['High'] if 'High' in df_raw.columns else cl
        lo = df_raw['Low'] if 'Low' in df_raw.columns else cl
        vol = df_raw['Volume'] if 'Volume' in df_raw.columns else None
        df_bot = _calcular_bot_dataframe_ma(
            cl, hi, lo, vol,
            int(rsi_periodo), int(macd_fast), int(macd_slow), int(macd_signal),
            int(cruce_lookback_barras), exigir_alineacion_larga,
        )
        df_bot = _simular_operaciones_ma(df_bot)
        resultados_bot[tk] = df_bot

    if fallidos:
        st.warning(f"⚠️ No se pudo descargar/calcular para: {', '.join(fallidos)} "
                    f"(datos insuficientes para EMA500 — hacen falta al menos {MIN_BARRAS_NECESARIAS} velas —, "
                    "o símbolo sin datos en Yahoo Finance).")

    if not resultados_bot:
        st.error('No se pudo calcular ninguna señal con los activos seleccionados.')
        return

    st.caption(
        f"🕐 {datetime.now().strftime('%H:%M:%S')} · Temporalidad {horizonte_bot} · "
        f"caché de precios: 20s · tocá '🔄 Actualizar precios ahora' para forzar la recarga."
    )

    # ── Resumen multi-activo ─────────────────────────────────────
    st.markdown('### 📋 Resumen — señal actual por activo')
    filas_resumen = []
    for tk, df_bot in resultados_bot.items():
        u = df_bot.iloc[-1]
        disparos_tk = df_bot[df_bot['disparo'] & (df_bot['estado'] != '—') & (df_bot['tomada'] == True)]
        n_no_tomadas_tk = int((df_bot['disparo'] & (df_bot['estado'] != '—') & (~df_bot['tomada'])).sum())
        n_ok = int((disparos_tk['resultado'] == '✅').sum())
        n_bad = int((disparos_tk['resultado'] == '❌').sum())
        n_open = int((disparos_tk['resultado'] == '⏳').sum())
        cerradas = n_ok + n_bad
        winrate = f'{n_ok / cerradas * 100:.0f}%' if cerradas > 0 else 'N/D'
        filas_resumen.append({
            'Ticker': tk, 'Señal': u['estado'], 'Precio': fmt_precio(u['precio']),
            'Última vela': df_bot.index[-1].strftime('%Y-%m-%d %H:%M'),
            'RSI': round(u['rsi'], 1),
            'MACD Hist': round(u['macd_hist'], 4),
            'EMA9': fmt_precio(u['ema9']), 'EMA20': fmt_precio(u['ema20']), 'EMA50': fmt_precio(u['ema50']),
            'EMA200': fmt_precio(u['ema200']),
            'Track record': f'{n_ok}✅ {n_bad}❌ {n_open}⏳' + (f' · {n_no_tomadas_tk}⛔' if n_no_tomadas_tk else ''),
            'Win rate': winrate,
        })
    df_resumen = pd.DataFrame(filas_resumen)
    orden_prioridad = {'COMPRA': 0, 'VENTA': 1, '—': 2}
    df_resumen['_orden'] = df_resumen['Señal'].map(orden_prioridad)
    df_resumen = df_resumen.sort_values('_orden').drop(columns=['_orden'])

    _map = 'map' if hasattr(df_resumen.style, 'map') else 'applymap'
    styled_resumen = (df_resumen.style
        .pipe(lambda s: getattr(s, _map)(_color_señal_bot, subset=['Señal']))
        .set_properties(**{'background-color': '#0d1117', 'color': '#e6edf3', 'border': '1px solid #21262d'})
        .set_table_styles([
            {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', '#e6edf3'),
                ('font-weight', '700'), ('text-align', 'center'),
                ('border-bottom', '2px solid #3a7bd5'), ('font-size', '11px')]},
            {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]},
        ]))
    st.dataframe(styled_resumen, use_container_width=True, height=min(400, len(df_resumen) * 40 + 45))
    chips_navegacion([(tk, tk) for tk in resultados_bot.keys()], 'bot_inversion_resumen')

    n_señales = int((df_resumen['Señal'] != '—').sum())
    if n_señales > 0:
        st.success(f'⚡ {n_señales} activo(s) con señal activa ahora mismo.')

    # ── Detalle de un activo ─────────────────────────────────────
    st.markdown('---')
    st.markdown('### 🔍 Detalle por activo')
    ticker_detalle = st.selectbox(
        'Elegí un activo para ver el gráfico y el historial completo',
        list(resultados_bot.keys()), key='bot_detalle_sel',
    )
    df_bot_sel = resultados_bot[ticker_detalle]
    ultimo = df_bot_sel.iloc[-1]
    estado_actual = ultimo['estado']
    color_estado = _color_estado(estado_actual)

    pila_corta_txt = 'EMA9>EMA20>EMA50 ✅' if ultimo['pila_alcista'] else ('EMA9<EMA20<EMA50 ❌' if ultimo['pila_bajista'] else 'Mixta')
    pila_larga_txt = 'EMA50>200>300>400>500 ✅' if ultimo['alineacion_larga_alcista'] else ('Invertida ❌' if ultimo['alineacion_larga_bajista'] else 'Mixta')
    kpi_cards_4([
        ('Señal Actual', estado_actual, f'{ticker_detalle} · {horizonte_bot}', color_estado),
        ('Precio', fmt_precio(ultimo['precio']),
         f"EMA20: {fmt_precio(ultimo['ema20'])} · EMA50: {fmt_precio(ultimo['ema50'])}", '#3a7bd5'),
        ('RSI / MACD Hist', f"{ultimo['rsi']:.1f} / {ultimo['macd_hist']:+.4f}",
         'Sobrecompra/sobreventa · momentum', score_color_hex(ultimo['rsi'])),
        ('Pila de EMAs', pila_corta_txt, f'Largas: {pila_larga_txt}', '#e3b341'),
    ])

    st.plotly_chart(_fig_bot_señales(ticker_detalle, df_bot_sel, PLOTLY_LAYOUT_BASE),
                     use_container_width=True, config=PLOTLY_CONFIG, key=f'bot_fig_señales_{ticker_detalle}')

    rend = _bot_simular_en_memoria(df_bot_sel, capital_inicial_bot, pct_por_operacion_bot, apalancamiento_bot)
    montos = rend['montos']

    st.markdown('#### 📋 Historial de señales disparadas')
    df_hist = df_bot_sel[df_bot_sel['disparo']].copy().sort_index(ascending=False)
    if df_hist.empty:
        st.info('No se disparó ninguna señal en el período analizado con los parámetros actuales.')
    else:
        def _monto(ts):
            m = montos.get(ts)
            return f"USD {m:,.2f}" if m is not None else '—'

        def _fecha_fmt(v):
            return v.strftime('%Y-%m-%d %H:%M') if pd.notna(v) else '—'

        def _ganancia_perdida_usd(ts, row):
            if row['tomada']:
                val = rend['pnl_por_señal'].get(ts)
                return f"USD {val:+,.2f}" if val is not None else '—'
            if pd.isna(row['retorno_pct']):
                return '—'
            capital_ref = capital_inicial_bot * (pct_por_operacion_bot / 100.0)
            val = capital_ref * (row['retorno_pct'] / 100.0) * apalancamiento_bot
            return f"USD {val:+,.2f} (hipot.)"

        def _resultado_si_no_tomada(row):
            return '—' if row['tomada'] else (row['resultado_teorico'] or '—')

        df_hist_show = pd.DataFrame({
            'Fecha/Hora': df_hist.index.strftime('%Y-%m-%d %H:%M'),
            'Señal': df_hist['estado'],
            'Tomada': df_hist['tomada'].apply(lambda v: 'Sí' if v else 'No'),
            'Resultado': df_hist['resultado'].apply(lambda v: 'No tomada' if v == '⛔' else v),
            'Si no se tomó': df_hist.apply(_resultado_si_no_tomada, axis=1),
            'Fecha cierre': df_hist['fecha_cierre'].apply(_fecha_fmt),
            'Motivo cierre': df_hist['motivo_cierre'],
            'Nivel alcanzado': df_hist['nivel_alcanzado'],
            'Ganancia/Pérdida (USD)': [_ganancia_perdida_usd(ts, df_hist.loc[ts]) for ts in df_hist.index],
            'Retorno %': df_hist['retorno_pct'].apply(lambda v: f'{v:+.2f}%' if pd.notna(v) else '—'),
            'Precio entrada': df_hist['precio'].apply(fmt_precio),
            'Monto operado': [_monto(ts) for ts in df_hist.index],
            'Stop final': df_hist['stop_final'].apply(lambda v: fmt_precio(v) if pd.notna(v) else '—'),
            'RSI': df_hist['rsi'].round(1),
            'MACD Hist': df_hist['macd_hist'].round(4),
        })
        _color_tomada = lambda v: 'color:#8b949e' if v == 'No' else 'color:#3fb950;font-weight:700'
        styled_hist = (df_hist_show.style
            .pipe(lambda s: getattr(s, _map)(_color_señal_bot, subset=['Señal']))
            .pipe(lambda s: getattr(s, _map)(_color_resultado, subset=['Resultado']))
            .pipe(lambda s: getattr(s, _map)(_color_resultado, subset=['Si no se tomó']))
            .pipe(lambda s: getattr(s, _map)(_color_tomada, subset=['Tomada']))
            .set_properties(**{'background-color': '#0d1117', 'color': '#e6edf3', 'border': '1px solid #21262d'})
            .set_table_styles([
                {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', '#e6edf3'),
                    ('font-weight', '700'), ('text-align', 'center'),
                    ('border-bottom', '2px solid #3a7bd5'), ('font-size', '11px')]},
                {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]},
            ]))
        st.dataframe(styled_hist, use_container_width=True, height=min(500, len(df_hist_show) * 38 + 45))
        n_no_tomadas = int((~df_hist['tomada']).sum())
        st.caption(
            f'{len(df_hist_show)} señales disparadas en el historial analizado ({cfg["periodo_descarga"]} · '
            f'{horizonte_bot}) · {n_no_tomadas} no tomadas por tener otra operación abierta en ese momento '
            '(para esas se muestra igual, en "Si no se tomó" y "Ganancia/Pérdida (USD)", qué hubiera pasado '
            'de forma hipotética).'
        )

    st.markdown('---')
    st.markdown(f'### 📈 Rendimiento simulado — {ticker_detalle} (apalancamiento {apalancamiento_bot}x)')

    if rend['total_señales'] == 0:
        st.info('No se disparó ninguna señal de este activo en el período analizado — el rendimiento se arma solo cuando aparecen operaciones.')
    else:
        color_rend = '#3fb950' if rend['rendimiento_pct'] >= 0 else '#f85149'
        kpi_cards_4([
            ('Capital Simulado', f"USD {rend['capital_actual']:,.2f}",
             f"Inicial: USD {rend['capital_inicial']:,.2f} · {apalancamiento_bot}x", color_rend),
            ('Rendimiento', f"{rend['rendimiento_pct']:+.2f}%", 'Sobre capital inicial', color_rend),
            ('Win Rate', f"{rend['win_rate']:.0f}%" if rend['win_rate'] is not None else 'N/D',
             f"{rend['ganadoras']}✅ / {rend['perdedoras']}❌ cerradas", '#3a7bd5'),
            ('Operaciones', str(rend['total_señales']),
             f"{rend['cerradas']} cerradas · {rend['abiertas']} en curso", '#e3b341'),
        ])

        fig_eq = go.Figure()
        eq_x = [str(c['fecha'])[:16] for c in rend['curva']]
        eq_y = [c['equity'] for c in rend['curva']]
        fig_eq.add_trace(go.Scatter(x=eq_x, y=eq_y, mode='lines+markers', line=dict(color=color_rend, width=2)))
        fig_eq.update_layout(
            **PLOTLY_LAYOUT_BASE, height=340,
            title=dict(text=f'Evolución del capital simulado ({apalancamiento_bot}x)', font=dict(size=13)),
            xaxis=dict(gridcolor='#21262d'), yaxis=dict(gridcolor='#21262d', title='USD'),
            margin=dict(l=10, r=10, t=45, b=10),
        )
        st.plotly_chart(fig_eq, use_container_width=True, config=PLOTLY_CONFIG, key='bot_equity_fig')

        st.markdown('#### ⚖️ Comparativa por apalancamiento')
        filas_comp = []
        for lev in APALANCAMIENTOS_BOT:
            r_lev = rend if lev == apalancamiento_bot else \
                _bot_simular_en_memoria(df_bot_sel, capital_inicial_bot, pct_por_operacion_bot, lev)
            filas_comp.append({
                'Apalancamiento': f'{lev}x' + (' ← actual' if lev == apalancamiento_bot else ''),
                'Capital final (USD)': round(r_lev['capital_actual'], 2),
                'Rendimiento': f"{r_lev['rendimiento_pct']:+.2f}%",
                'Cerradas': r_lev['cerradas'],
                'Win Rate': f"{r_lev['win_rate']:.0f}%" if r_lev['win_rate'] is not None else 'N/D',
            })
        df_comp = pd.DataFrame(filas_comp)
        st.dataframe(df_comp, use_container_width=True, height=min(260, len(df_comp) * 38 + 45), hide_index=True)

    with st.expander('❓ Cómo funciona esta estrategia'):
        st.markdown("""
        **📈 COMPRA** — se necesita, en este orden: (1) cruce alcista reciente de EMA9 sobre EMA20;
        (2) pila EMA9 &gt; EMA20 &gt; EMA50; (3) precio sobre la EMA50; (4) RSI(14) &gt; 55 (se veta si
        supera 75, demasiado extendido); (5) MACD alcista (cruce reciente + histograma positivo). Si
        activaste el filtro opcional, además exige EMA50 &gt; EMA200 &gt; EMA300 &gt; EMA400 &gt; EMA500.

        **🎯 Objetivo y Stop progresivos** (nunca bajan, solo suben):
        - Al comprar: Stop = EMA50 · Objetivo = EMA200. Mientras el precio no cierre sobre la EMA200,
          no se vende — se mantiene la posición.
        - Cierra sobre EMA200 → Stop sube a EMA200 · nuevo Objetivo = EMA300.
        - Cierra sobre EMA300 → Stop sube a EMA300 · nuevo Objetivo = EMA400.
        - Cierra sobre EMA400 → Stop sube a EMA400 · nuevo Objetivo = EMA500.
        - Cierra sobre EMA500 → Stop sube a EMA500 · ya no hay objetivo fijo: acá empieza la
          verdadera tendencia y se sigue comprado mientras el precio no toque la EMA500.
        - En cada tramo el Stop sigue el valor actual de su EMA (trailing), pero nunca se afloja
          hacia abajo.

        **📉 VENTA (pérdida de fuerza)** — se cierra la posición si EMA9 cruza por debajo de EMA20 Y
        además EMA9 &lt; EMA50 Y EMA20 &lt; EMA50 (la pila se invierte por completo). Esto puede cerrar
        la operación aunque el Stop todavía no se haya tocado — es la salida por "se acabó el
        impulso", no por precio.

        **🚫 Sin solapamiento**: si aparece una señal nueva mientras hay una operación abierta del
        mismo activo, no se toma (⛔) — pero igual se calcula qué hubiera pasado, de forma hipotética,
        en "Si no se tomó" y "Ganancia/Pérdida (USD)".

        **Long-only**: esta versión solo simula compras. La señal de VENTA es un aviso de salida /
        pérdida de fuerza, no una posición corta.

        Usalo como medida de calidad de la señal, no como tu resultado real de trading.
        """)
