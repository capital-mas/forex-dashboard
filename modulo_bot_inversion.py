# ==============================================================
#  MÓDULO BOT DE INVERSIÓN — v7: Motor de Medias Móviles + RSI + MACD
#  Reemplaza por completo el motor anterior (Fractal/Sentimiento/
#  Z-Score/RSI de conteo 4/4). Estrategia de TENDENCIA con sistema
#  de puntaje y Stop dinámico (estilo "Andy": 2×ATR inicial,
#  breakeven al +5%, trailing al +10%).
#
#  📈 COMPRA (tendencia fuerte)
#     Medias:  EMA20 > SMA50 > SMA200 > SMA300, precio > EMA20,
#              EMA20 con pendiente positiva.
#     RSI(14): entre 55 y 70 (veto si > 75).
#     MACD:    cruce alcista de la línea MACD sobre la señal,
#              histograma positivo (preferible cruce sobre 0).
#     Filtros: volumen > SMA20(volumen); no comprar si el precio
#              está > 8-10% por encima de la EMA20 (evita entrar tarde).
#     Puntaje: EMA20>SMA50 +20, SMA50>SMA200 +20, SMA200>SMA300 +20,
#              RSI 55-70 +15, cruce alcista MACD +15, histograma +10.
#              80-100 = COMPRA FUERTE · 65-79 = COMPRA MODERADA.
#
#  📉 VENTA (con medias 9/20/50/200)
#     Medias:  EMA9 < EMA20 < SMA50 < SMA200, precio < EMA20.
#     RSI(14): < 45 (más fuerte si < 40).
#     MACD:    cruce bajista, histograma negativo.
#     Puntaje: EMA9<EMA20 +25, EMA20<SMA50 +20, precio<SMA200 +20,
#              RSI<45 +15, cruce bajista MACD +20.
#              80-100 = VENTA INMEDIATA · 60-79 = REDUCIR POSICIÓN.
#
#  🛑 Stop dinámico ("método Andy")
#     Inicial: 2×ATR(14) en contra del precio de entrada.
#     +5% de ganancia  → mover Stop a breakeven (precio de entrada).
#     +10% de ganancia → trailing: Stop sube/baja hasta el máximo
#                        entre EMA20 actual y 2×ATR actual (nunca
#                        se afloja, solo se ajusta a favor).
#     Salida anticipada: si el precio cierra en contra de la EMA20
#                        Y el histograma del MACD confirma el giro,
#                        se cierra ahí mismo, sin esperar al Stop.
#
#  Timeframes: 15, 30, 45 minutos, 1h, 4h y 1 día (se sacó 5min, se
#  agregó 45min). Pensá 1 día como marco de tendencia principal y
#  4h como marco de entrada — si coinciden, mejor probabilidad.
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

C_COMPRA_FUERTE     = '#3fb950'
C_COMPRA_MODERADA   = '#2dd4bf'
C_VENTA_INMEDIATA   = '#f85149'
C_REDUCIR_POSICION  = '#f0883e'

MIN_BARRAS_NECESARIAS = 320  # SMA300 + margen


# ── Indicadores ─────────────────────────────────────────────────

def _ema(series, length):
    return series.ewm(span=length, adjust=False).mean()


def _sma(series, length):
    return series.rolling(length).mean()


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


def _atr(high, low, close, length=14):
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(length).mean()


# ── Motor de señales (puntaje de tendencia) ─────────────────────

def _calcular_bot_dataframe_ma(close, high, low, volume,
                                 rsi_periodo, macd_fast, macd_slow, macd_signal,
                                 atr_periodo, pendiente_ema20_barras,
                                 extension_max_pct, cruce_lookback_barras,
                                 usar_filtro_volumen):
    """Calcula todos los indicadores y el puntaje de COMPRA/VENTA para
    cada barra. No mira hacia adelante: todo se calcula con datos
    disponibles hasta la barra actual."""
    cl = close.dropna()
    hi = high.reindex(cl.index)
    lo = low.reindex(cl.index)
    vol = volume.reindex(cl.index) if volume is not None else None

    ema9 = _ema(cl, 9)
    ema20 = _ema(cl, 20)
    sma50 = _sma(cl, 50)
    sma200 = _sma(cl, 200)
    sma300 = _sma(cl, 300)
    rsi_valor = _rsi_wilder(cl, rsi_periodo)
    macd_line, macd_signal_line, macd_hist = _macd(cl, macd_fast, macd_slow, macd_signal)
    atr_valor = _atr(hi, lo, cl, atr_periodo)

    # Volumen: si no hay dato confiable (None, todo NaN o todo cero),
    # se desactiva el filtro automáticamente para no bloquear todo.
    volumen_disponible = (vol is not None) and (vol.fillna(0).sum() > 0)
    if volumen_disponible:
        vol_sma20 = vol.rolling(20).mean()
        volumen_ok = vol > vol_sma20
    else:
        volumen_ok = pd.Series(True, index=cl.index)

    ema20_pendiente_pos = ema20 > ema20.shift(pendiente_ema20_barras)
    precio_sobre_ema20 = cl > ema20
    precio_bajo_ema20 = cl < ema20
    extendido = cl > ema20 * (1 + extension_max_pct / 100.0)
    rsi_veto_compra = rsi_valor > 75

    macd_cross_up = (macd_line > macd_signal_line) & (macd_line.shift(1) <= macd_signal_line.shift(1))
    macd_cross_up_reciente = macd_cross_up.rolling(cruce_lookback_barras, min_periods=1).max().astype(bool)
    macd_cross_down = (macd_line < macd_signal_line) & (macd_line.shift(1) >= macd_signal_line.shift(1))
    macd_cross_down_reciente = macd_cross_down.rolling(cruce_lookback_barras, min_periods=1).max().astype(bool)

    # ── Puntaje COMPRA (máx. 100) ──
    pts_compra = (
        (ema20 > sma50).astype(int) * 20 +
        (sma50 > sma200).astype(int) * 20 +
        (sma200 > sma300).astype(int) * 20 +
        ((rsi_valor >= 55) & (rsi_valor <= 70)).astype(int) * 15 +
        macd_cross_up_reciente.astype(int) * 15 +
        (macd_hist > 0).astype(int) * 10
    )
    # Requisitos que NO puntúan pero vetan la señal aunque el puntaje sea alto
    gate_compra = precio_sobre_ema20 & ema20_pendiente_pos & (~rsi_veto_compra) & (~extendido) & volumen_ok

    # ── Puntaje VENTA (máx. 100) ──
    pts_venta = (
        (ema9 < ema20).astype(int) * 25 +
        (ema20 < sma50).astype(int) * 20 +
        (cl < sma200).astype(int) * 20 +
        (rsi_valor < 45).astype(int) * 15 +
        macd_cross_down_reciente.astype(int) * 20
    )
    gate_venta = precio_bajo_ema20

    estado = pd.Series('—', index=cl.index)
    estado[gate_compra & (pts_compra >= 65) & (pts_compra < 80)] = 'COMPRA MODERADA'
    estado[gate_compra & (pts_compra >= 80)] = 'COMPRA FUERTE'
    estado[gate_venta & (pts_venta >= 60) & (pts_venta < 80)] = 'REDUCIR POSICIÓN'
    estado[gate_venta & (pts_venta >= 80)] = 'VENTA INMEDIATA'
    disparo = (estado != '—') & (estado != estado.shift(1))

    df = pd.DataFrame({
        'precio': cl, 'high': hi, 'low': lo,
        'ema9': ema9, 'ema20': ema20, 'sma50': sma50, 'sma200': sma200, 'sma300': sma300,
        'rsi': rsi_valor, 'macd': macd_line, 'macd_signal': macd_signal_line, 'macd_hist': macd_hist,
        'atr': atr_valor,
        'pts_compra': pts_compra, 'pts_venta': pts_venta,
        'gate_compra': gate_compra, 'gate_venta': gate_venta,
        'rsi_veto_compra': rsi_veto_compra, 'extendido': extendido,
        'volumen_ok': volumen_ok,
        'estado': estado, 'disparo': disparo,
    })
    df.attrs['volumen_disponible'] = volumen_disponible
    return df


# ── Simulación de operaciones con Stop dinámico (2×ATR + trailing) ──

def _simular_operaciones_ma(df, atr_mult_inicial=2.0, gatillo_breakeven_pct=5.0,
                              gatillo_trailing_pct=10.0, atr_mult_trailing=2.0):
    """Recorre cada señal disparada y simula la operación vela a vela:
    Stop inicial a 2×ATR, breakeven al +5%, trailing (EMA20 o 2×ATR,
    lo que proteja más) al +10%, y salida anticipada si el precio
    cierra en contra de la EMA20 con el MACD confirmando el giro.
    Se calcula para TODAS las señales (incluidas las bloqueadas por
    solapamiento ⛔, de forma hipotética), pero solo las señales
    REALMENTE tomadas bloquean señales nuevas del mismo activo."""
    df = df.copy()
    n = len(df)
    idx = df.index
    precio_arr = df['precio'].values
    high_arr = df['high'].values
    low_arr = df['low'].values
    ema20_arr = df['ema20'].values
    atr_arr = df['atr'].values
    hist_arr = df['macd_hist'].values
    estado_arr = df['estado'].values
    disparo_arr = df['disparo'].values

    resultado = [''] * n
    resultado_teorico = [''] * n
    fecha_cierre = [pd.NaT] * n
    retorno_pct = [np.nan] * n
    tomada = [False] * n
    motivo_cierre = [''] * n
    stop_final_arr = [np.nan] * n
    direccion_arr = [''] * n

    ocupado_hasta = -1

    for i in range(n):
        if not disparo_arr[i] or estado_arr[i] == '—':
            continue
        if pd.isna(atr_arr[i]) or pd.isna(ema20_arr[i]):
            continue

        fue_tomada = i > ocupado_hasta
        tomada[i] = fue_tomada
        es_compra = 'COMPRA' in estado_arr[i]
        direccion_arr[i] = 'compra' if es_compra else 'venta'

        entry = precio_arr[i]
        stop = entry - atr_mult_inicial * atr_arr[i] if es_compra else entry + atr_mult_inicial * atr_arr[i]
        breakeven_hecho = False

        j_exit = n - 1
        precio_exit = precio_arr[n - 1]
        motivo = 'Fin de datos (operación en curso)'

        for j in range(i + 1, n):
            hi_j, lo_j, cl_j = high_arr[j], low_arr[j], precio_arr[j]
            ema20_j, atr_j, hist_j = ema20_arr[j], atr_arr[j], hist_arr[j]

            # 1) ¿Tocó el Stop vigente en esta vela?
            if es_compra and lo_j <= stop:
                precio_exit, j_exit, motivo = stop, j, 'Tocó Stop'
                break
            if (not es_compra) and hi_j >= stop:
                precio_exit, j_exit, motivo = stop, j, 'Tocó Stop'
                break

            # 2) Salida anticipada: cierre en contra de la EMA20 + MACD confirma el giro
            if not pd.isna(ema20_j) and not pd.isna(hist_j):
                giro_confirmado = (cl_j < ema20_j and hist_j < 0) if es_compra \
                    else (cl_j > ema20_j and hist_j > 0)
                if giro_confirmado:
                    precio_exit, j_exit, motivo = cl_j, j, 'Cierre en contra de EMA20 + giro MACD'
                    break

            # 3) Actualizar Stop dinámico (breakeven / trailing)
            if not pd.isna(atr_j) and not pd.isna(ema20_j):
                ganancia_pct = ((cl_j - entry) / entry * 100) if es_compra else ((entry - cl_j) / entry * 100)
                if not breakeven_hecho and ganancia_pct >= gatillo_breakeven_pct:
                    stop = entry
                    breakeven_hecho = True
                if ganancia_pct >= gatillo_trailing_pct:
                    if es_compra:
                        candidato = max(ema20_j, cl_j - atr_mult_trailing * atr_j)
                        stop = max(stop, candidato)
                    else:
                        candidato = min(ema20_j, cl_j + atr_mult_trailing * atr_j)
                        stop = min(stop, candidato)

        if motivo != 'Fin de datos (operación en curso)':
            ret = ((precio_exit - entry) / entry * 100) if es_compra else ((entry - precio_exit) / entry * 100)
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

    df['direccion'] = direccion_arr
    df['resultado'] = resultado
    df['resultado_teorico'] = resultado_teorico
    df['fecha_cierre'] = fecha_cierre
    df['retorno_pct'] = retorno_pct
    df['tomada'] = tomada
    df['motivo_cierre'] = motivo_cierre
    df['stop_final'] = stop_final_arr
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
    """Recorre en orden cronológico las señales TOMADAS y compone el
    capital: cada operación cerrada arriesga 'pct_por_operacion' % del
    capital ACTUAL, multiplicado por el apalancamiento, aplicado sobre
    el % de retorno real que arrojó el Stop dinámico. La pérdida de
    una operación nunca supera el 100% del capital arriesgado en ella."""
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
    fig.add_trace(go.Scatter(x=df.index, y=df['ema20'], line=dict(color='#e3b341', width=1, dash='dot'), name='EMA20'))
    fig.add_trace(go.Scatter(x=df.index, y=df['sma50'], line=dict(color='#a371f7', width=1, dash='dot'), name='SMA50'))
    fig.add_trace(go.Scatter(x=df.index, y=df['sma200'], line=dict(color='#8b949e', width=1, dash='dot'), name='SMA200'))
    for tipo, color, symbol in [
        ('COMPRA FUERTE', C_COMPRA_FUERTE, 'triangle-up'),
        ('COMPRA MODERADA', C_COMPRA_MODERADA, 'triangle-up'),
        ('VENTA INMEDIATA', C_VENTA_INMEDIATA, 'triangle-down'),
        ('REDUCIR POSICIÓN', C_REDUCIR_POSICION, 'triangle-down'),
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
        title=dict(text=f'{ticker} — Señales del Bot de Inversión', font=dict(size=14)),
        height=480, hovermode='x unified',
        legend=dict(orientation='h', y=1.1),
        xaxis=dict(gridcolor='#21262d'), yaxis=dict(gridcolor='#21262d'),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    return fig


def _color_estado(estado):
    return {
        'COMPRA FUERTE': C_COMPRA_FUERTE, 'COMPRA MODERADA': C_COMPRA_MODERADA,
        'VENTA INMEDIATA': C_VENTA_INMEDIATA, 'REDUCIR POSICIÓN': C_REDUCIR_POSICION, '—': '#8b949e',
    }.get(estado, '#8b949e')


def _color_señal_bot(val):
    c = {'COMPRA FUERTE': C_COMPRA_FUERTE, 'COMPRA MODERADA': C_COMPRA_MODERADA,
         'VENTA INMEDIATA': C_VENTA_INMEDIATA, 'REDUCIR POSICIÓN': C_REDUCIR_POSICION}.get(val, '#e6edf3')
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
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">🤖 Bot de Inversión — Tendencia (EMA/SMA + RSI + MACD)</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Estrategia de <b style="color:#e3b341">tendencia</b> con sistema de puntaje:
        <b style="color:#e3b341">COMPRA</b> cuando EMA20 &gt; SMA50 &gt; SMA200 &gt; SMA300, el precio
        está sobre la EMA20 con pendiente positiva, el RSI está entre 55-70 y el MACD cruza al alza.
        <b style="color:#e3b341">VENTA</b> con el set EMA9/EMA20/SMA50/SMA200, precio bajo la EMA20,
        RSI &lt; 45 y MACD cruzando a la baja. El Stop es <b style="color:#a371f7">dinámico</b>:
        arranca en 2×ATR, pasa a breakeven al +5% y hace trailing al +10% (EMA20 o 2×ATR, lo que más
        proteja). Se sale antes si el precio cierra en contra de la EMA20 y el MACD confirma el giro.
        Analizá hasta <b style="color:#e3b341">10 activos</b> en <b style="color:#e3b341">5, 15, 30 min,
        1h, 4h o 1 día</b> — comparar la tendencia diaria con la entrada en 4h suele dar más probabilidad.
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

        p4, p5 = st.columns(2)
        with p4:
            st.markdown('**Filtro de tendencia (EMA20)**')
            pendiente_ema20_barras = st.number_input(
                'Pendiente positiva: comparar contra hace N barras', value=3, min_value=1, key='bot_ema20_pendiente',
            )
            extension_max_pct = st.number_input(
                'No comprar si el precio está más de X% sobre la EMA20', value=9.0,
                min_value=1.0, max_value=20.0, step=0.5, key='bot_extension_max',
                help='Evita comprar demasiado tarde, con el precio ya muy estirado.',
            )
        with p5:
            st.markdown('**Volumen y ATR**')
            usar_filtro_volumen = st.checkbox(
                'Exigir volumen > SMA20(volumen) para comprar', value=True, key='bot_usar_volumen',
                help='Si el ticker no trae volumen confiable (común en forex/cripto vía Yahoo Finance), se ignora automáticamente.',
            )
            atr_periodo = st.number_input('Período ATR', value=14, min_value=2, key='bot_atr_periodo')

        p6, p7 = st.columns(2)
        with p6:
            st.markdown('**Stop inicial**')
            atr_mult_inicial = st.number_input('Múltiplo de ATR para el Stop inicial', value=2.0, min_value=0.5, step=0.25, key='bot_atr_mult_inicial')
        with p7:
            st.markdown('**Trailing Stop**')
            gatillo_breakeven_pct = st.number_input('Mover a breakeven al ganar (%)', value=5.0, min_value=0.5, step=0.5, key='bot_gatillo_breakeven')
            gatillo_trailing_pct = st.number_input('Empezar trailing al ganar (%)', value=10.0, min_value=1.0, step=0.5, key='bot_gatillo_trailing')
            atr_mult_trailing = st.number_input('Múltiplo de ATR para el trailing', value=2.0, min_value=0.5, step=0.25, key='bot_atr_mult_trailing')

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
            int(atr_periodo), int(pendiente_ema20_barras),
            extension_max_pct, int(cruce_lookback_barras), usar_filtro_volumen,
        )
        df_bot = _simular_operaciones_ma(
            df_bot, atr_mult_inicial, gatillo_breakeven_pct, gatillo_trailing_pct, atr_mult_trailing,
        )
        resultados_bot[tk] = df_bot

    if fallidos:
        st.warning(f"⚠️ No se pudo descargar/calcular para: {', '.join(fallidos)} "
                    f"(datos insuficientes para SMA300 — hacen falta al menos {MIN_BARRAS_NECESARIAS} velas —, "
                    "o símbolo sin datos en Yahoo Finance).")

    if not resultados_bot:
        st.error('No se pudo calcular ninguna señal con los activos seleccionados.')
        return

    if not any(df.attrs.get('volumen_disponible', False) for df in resultados_bot.values()) and usar_filtro_volumen:
        st.caption('ℹ️ Ninguno de los activos analizados trae volumen confiable — el filtro de volumen se ignoró automáticamente para todos.')

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
        pts = int(u['pts_compra']) if 'COMPRA' in u['estado'] else (int(u['pts_venta']) if u['estado'] in ('VENTA INMEDIATA', 'REDUCIR POSICIÓN') else max(int(u['pts_compra']), int(u['pts_venta'])))
        filas_resumen.append({
            'Ticker': tk, 'Señal': u['estado'], 'Puntaje': f'{pts}/100', 'Precio': fmt_precio(u['precio']),
            'Última vela': df_bot.index[-1].strftime('%Y-%m-%d %H:%M'),
            'RSI': round(u['rsi'], 1),
            'MACD Hist': round(u['macd_hist'], 4),
            'EMA20': fmt_precio(u['ema20']), 'SMA50': fmt_precio(u['sma50']),
            'SMA200': fmt_precio(u['sma200']), 'SMA300': fmt_precio(u['sma300']),
            'Track record': f'{n_ok}✅ {n_bad}❌ {n_open}⏳' + (f' · {n_no_tomadas_tk}⛔' if n_no_tomadas_tk else ''),
            'Win rate': winrate,
        })
    df_resumen = pd.DataFrame(filas_resumen)
    orden_prioridad = {'COMPRA FUERTE': 0, 'VENTA INMEDIATA': 0, 'COMPRA MODERADA': 1, 'REDUCIR POSICIÓN': 1, '—': 2}
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

    kpi_cards_4([
        ('Señal Actual', estado_actual, f'{ticker_detalle} · {horizonte_bot}', color_estado),
        ('Precio', fmt_precio(ultimo['precio']),
         f"EMA20: {fmt_precio(ultimo['ema20'])} · SMA50: {fmt_precio(ultimo['sma50'])}", '#3a7bd5'),
        ('RSI / MACD Hist', f"{ultimo['rsi']:.1f} / {ultimo['macd_hist']:+.4f}",
         'Sobrecompra/sobreventa · momentum', score_color_hex(ultimo['rsi'])),
        ('Puntaje', f"{int(ultimo['pts_compra'])}/100 🟢 · {int(ultimo['pts_venta'])}/100 🔴",
         'Compra · Venta', '#e3b341'),
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

        def _puntaje_col(row):
            return f"{int(row['pts_compra'])}/100" if 'COMPRA' in row['estado'] else f"{int(row['pts_venta'])}/100"

        df_hist_show = pd.DataFrame({
            'Fecha/Hora': df_hist.index.strftime('%Y-%m-%d %H:%M'),
            'Señal': df_hist['estado'],
            'Puntaje': df_hist.apply(_puntaje_col, axis=1),
            'Tomada': df_hist['tomada'].apply(lambda v: 'Sí' if v else 'No'),
            'Resultado': df_hist['resultado'].apply(lambda v: 'No tomada' if v == '⛔' else v),
            'Si no se tomó': df_hist.apply(_resultado_si_no_tomada, axis=1),
            'Fecha cierre': df_hist['fecha_cierre'].apply(_fecha_fmt),
            'Motivo cierre': df_hist['motivo_cierre'],
            'Ganancia/Pérdida (USD)': [_ganancia_perdida_usd(ts, df_hist.loc[ts]) for ts in df_hist.index],
            'Retorno %': df_hist['retorno_pct'].apply(lambda v: f'{v:+.2f}%' if pd.notna(v) else '—'),
            'Precio entrada': df_hist['precio'].apply(fmt_precio),
            'Monto operado': [_monto(ts) for ts in df_hist.index],
            'Stop final': df_hist['stop_final'].apply(lambda v: fmt_precio(v) if pd.notna(v) else '—'),
            'RSI': df_hist['rsi'].round(1),
            'MACD Hist': df_hist['macd_hist'].round(4),
            'ATR': df_hist['atr'].round(4),
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
        **📈 COMPRA** — se necesita EMA20 &gt; SMA50 &gt; SMA200 &gt; SMA300, precio sobre la EMA20 con
        pendiente positiva, RSI entre 55-70 (se veta si supera 75) y volumen sobre su promedio de 20
        ruedas. Tampoco se compra si el precio ya está demasiado estirado sobre la EMA20. El puntaje
        (EMA20&gt;SMA50 +20, SMA50&gt;SMA200 +20, SMA200&gt;SMA300 +20, RSI 55-70 +15, cruce alcista MACD +15,
        histograma positivo +10) define **COMPRA FUERTE** (80-100) o **COMPRA MODERADA** (65-79).

        **📉 VENTA** — con EMA9 &lt; EMA20 &lt; SMA50 &lt; SMA200 y precio bajo la EMA20. Puntaje (EMA9&lt;EMA20
        +25, EMA20&lt;SMA50 +20, precio&lt;SMA200 +20, RSI&lt;45 +15, cruce bajista MACD +20) define
        **VENTA INMEDIATA** (80-100) o **REDUCIR POSICIÓN** (60-79).

        **🛑 Stop dinámico**: arranca en 2×ATR(14) en contra de la entrada. Al ganar 5% pasa a
        breakeven. Al ganar 10% empieza el trailing: el Stop sigue al mayor entre la EMA20 actual y
        2×ATR actual (nunca se afloja). Además, si el precio cierra en contra de la EMA20 Y el
        histograma del MACD confirma el giro, se sale ahí mismo sin esperar al Stop.

        **🚫 Sin solapamiento**: si aparece una señal nueva mientras hay una operación abierta del
        mismo activo, no se toma (⛔) — pero igual se calcula qué hubiera pasado, de forma hipotética,
        en "Si no se tomó" y "Ganancia/Pérdida (USD)".

        **⚠️ Nota sobre el rebalanceo**: esta versión ya NO promedia en pérdida — es una estrategia de
        tendencia con Stop, no de promediar. Si el precio toca el Stop, la operación se cierra.

        Usalo como medida de calidad de la señal, no como tu resultado real de trading.
        """)
