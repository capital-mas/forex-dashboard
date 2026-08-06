# ==============================================================
#  MÓDULO BOT DE INVERSIÓN — v10: Motor de DOBLE BANDA DE BOLLINGER
#  (una "rápida" y una "estructural", más larga y más ancha) con
#  objetivo y Stop PROGRESIVOS. Reemplaza el motor anterior de
#  Bollinger + VWAP (el VWAP se sacó por completo: en varios activos
#  no traía volumen fiable de Yahoo Finance y quedaba en N/D).
#  Estrategia de REVERSIÓN A LA MEDIA en zonas de sobreventa/
#  sobrecompra confirmadas por DOS bandas de Bollinger de distinto
#  período/ancho (confluencia de corto y largo plazo dentro del
#  mismo timeframe), pensada para maximizar el win rate: se entra
#  recién cuando el precio ya dio señales de reversión, no cuando
#  "cae el cuchillo".
#
#  Indicadores usados:
#    · Banda de Bollinger 1 ("rápida"): SMA(bb1_length) ± bb1_std
#      desvíos. Por defecto 20 y 2.0 — la banda "de gatillo".
#    · Banda de Bollinger 2 ("estructural"): SMA(bb2_length) ±
#      bb2_std desvíos. Por defecto 50 y 2.5 — más lenta y más
#      ancha, confirma que la sobreventa/sobrecompra no es solo
#      ruido de corto plazo.
#    · RSI(14) como confirmación de que el precio venía de un
#      extremo y está girando.
#
#  📈 ENTRADA EN LARGO (COMPRA):
#     El precio toca (mínimo de la vela) la banda INFERIOR de la
#     Bollinger 2 (estructural) — dispara apenas toca, sin esperar
#     reclamo/cierre de vuelta. Confirmaciones que se mantienen:
#     el RSI(14) venía de zona de sobreventa (<30) en las últimas N
#     velas (`cruce_lookback_barras`), y opcionalmente no se compra
#     si el régimen de mercado es BAJISTA.
#
#  📉 ENTRADA EN CORTO (VENTA):
#     El precio toca (máximo de la vela) la banda SUPERIOR de la
#     Bollinger 2 (estructural) — dispara apenas toca. RSI(14) venía
#     de zona de sobrecompra (>70) en esas últimas N velas, y
#     opcionalmente no se vende en corto si el régimen es ALCISTA.
#
#  🎯 OBJETIVO (Take Profit) FIJO
#     Largo:  Objetivo = banda SUPERIOR de la Bollinger 1 (rápida).
#     Corto:  Objetivo = banda INFERIOR de la Bollinger 1 (rápida).
#     Al llegar el precio a ese nivel, se cierra la operación ahí
#     mismo (no hay escalera progresiva).
#
#  🛑 STOP inicial fijo: ±STOP_INICIAL_PCT% desde el precio de
#     entrada (no es trailing).
#
#  📉 SALIDA (pérdida de fuerza / señal opuesta): si estando en
#     largo aparece una señal de VENTA, se cierra la posición aunque
#     el Stop todavía no se haya tocado. Si estando en corto aparece
#     una señal de COMPRA, se cubre.
#
#  Entrada real: al precio de APERTURA de la vela siguiente a la
#  señal (no al cierre de la vela de la señal), para no incurrir en
#  look-ahead: la señal se conoce recién al cierre de esa vela.
#
#  Timeframes: 15, 30, 45 minutos, 1h, 4h y 1 día.
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
# 15m y 60m respectivamente. '1 día' usa 2 años de historia.
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
C_ALCISTA       = '#3fb950'
C_BAJISTA       = '#f85149'
C_LATERAL       = '#e3b341'

# ── Parámetros de la estrategia (defaults) ──────────────────────
BB1_LENGTH_DEFAULT = 20   # Bollinger "rápida" (banda de gatillo)
BB1_STD_DEFAULT = 2.0
BB2_LENGTH_DEFAULT = 50   # Bollinger "estructural" (confirmación de largo plazo)
BB2_STD_DEFAULT = 2.5
RSI_PERIODO_DEFAULT = 14
CRUCE_LOOKBACK_DEFAULT = 5  # ventana para "toque reciente de banda" y "venía de sobreventa/sobrecompra"
STOP_INICIAL_PCT_DEFAULT = 1.5  # % de distancia del Stop inicial respecto al precio de entrada
REGIMEN_PENDIENTE_BARRAS = 10  # barras para medir la pendiente de la media estructural (régimen de mercado)


# ── Indicadores ─────────────────────────────────────────────────

def _rsi_wilder(close, length=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(length).mean()
    avg_loss = loss.rolling(length).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def _bollinger(close, length, num_std):
    """Bandas de Bollinger clásicas: SMA(length) ± num_std desvíos
    estándar (población, ddof=0). Devuelve también el ancho de banda
    en % (usado para detectar "squeeze" ≈ mercado lateral)."""
    basis = close.rolling(length, min_periods=length).mean()
    dev = close.rolling(length, min_periods=length).std(ddof=0)
    upper = basis + num_std * dev
    lower = basis - num_std * dev
    bandwidth = (upper - lower) / basis.replace(0, np.nan) * 100
    return basis, upper, lower, bandwidth


# ── Motor de señales (doble Bollinger) ───────────────────────────

def _calcular_bot_dataframe_bb(close, high, low, volume, opens,
                                 bb1_length, bb1_std, bb2_length, bb2_std, rsi_periodo,
                                 cruce_lookback_barras, exigir_filtro_regimen):
    """Calcula todos los indicadores y las señales de COMPRA/VENTA
    para cada barra según la estrategia de doble Banda de Bollinger.
    No mira hacia adelante: todo se calcula con datos disponibles
    hasta la barra actual.

    COMPRA: la vela toca (mínimo <=) la banda INFERIOR de la
    Bollinger 2 (estructural) — dispara apenas toca, sin esperar
    reclamo. Confirma el RSI(14): venía de zona de sobreventa (<30)
    dentro de las últimas `cruce_lookback_barras` velas. Si
    `exigir_filtro_regimen`, no compra si el régimen es BAJISTA.

    VENTA: exactamente lo simétrico, tocando la banda SUPERIOR de la
    Bollinger 2 con RSI viniendo de sobrecompra (>70).
    """
    cl = close.dropna()
    hi = high.reindex(cl.index)
    lo = low.reindex(cl.index)
    op = opens.reindex(cl.index) if opens is not None else cl
    vol = volume.reindex(cl.index) if volume is not None else None

    bb1_basis, bb1_upper, bb1_lower, bb1_bandwidth = _bollinger(cl, bb1_length, bb1_std)
    bb2_basis, bb2_upper, bb2_lower, bb2_bandwidth = _bollinger(cl, bb2_length, bb2_std)
    rsi_valor = _rsi_wilder(cl, rsi_periodo)

    if vol is not None and vol.fillna(0).sum() > 0:
        vol_prom20 = vol.rolling(20, min_periods=5).mean()
        volumen_alto = vol > vol_prom20
    else:
        volumen_alto = pd.Series(True, index=cl.index)  # sin datos de volumen: solo informativo

    # ── Toque de la banda estructural (BB2) en la vela actual — gatillo directo ──
    toco_bb2_inferior = lo <= bb2_lower
    toco_bb2_superior = hi >= bb2_upper

    # ── RSI: confirma que venía de un extremo dentro de la ventana de lookback ──
    rsi_ok_compra = (rsi_valor < 30).rolling(cruce_lookback_barras, min_periods=1).max().astype(bool)
    rsi_ok_venta = (rsi_valor > 70).rolling(cruce_lookback_barras, min_periods=1).max().astype(bool)

    # ── Régimen de mercado (informativo + filtro opcional): media rápida vs
    #    media estructural y pendiente de la estructural, con squeeze = LATERAL ──
    pendiente_bb2_basis = bb2_basis - bb2_basis.shift(REGIMEN_PENDIENTE_BARRAS)
    bandwidth_pctl = bb1_bandwidth.rolling(100, min_periods=20).rank(pct=True)
    en_squeeze = bandwidth_pctl < 0.20  # Bollinger rápida muy angosta → mercado comprimido/lateral
    regimen_alcista = (bb1_basis > bb2_basis) & (pendiente_bb2_basis > 0) & (~en_squeeze)
    regimen_bajista = (bb1_basis < bb2_basis) & (pendiente_bb2_basis < 0) & (~en_squeeze)
    regimen_mercado = pd.Series('LATERAL', index=cl.index)
    regimen_mercado[regimen_alcista.fillna(False)] = 'ALCISTA'
    regimen_mercado[regimen_bajista.fillna(False)] = 'BAJISTA'

    entrada_compra = toco_bb2_inferior & rsi_ok_compra
    if exigir_filtro_regimen:
        entrada_compra = entrada_compra & (regimen_mercado != 'BAJISTA')

    entrada_venta = toco_bb2_superior & rsi_ok_venta
    if exigir_filtro_regimen:
        entrada_venta = entrada_venta & (regimen_mercado != 'ALCISTA')

    estado = pd.Series('—', index=cl.index)
    estado[entrada_compra] = 'COMPRA'
    estado[entrada_venta] = 'VENTA'
    disparo = (estado != '—') & (estado != estado.shift(1))

    df = pd.DataFrame({
        'precio': cl, 'high': hi, 'low': lo, 'open': op,
        'bb1_basis': bb1_basis, 'bb1_upper': bb1_upper, 'bb1_lower': bb1_lower, 'bb1_bandwidth': bb1_bandwidth,
        'bb2_basis': bb2_basis, 'bb2_upper': bb2_upper, 'bb2_lower': bb2_lower, 'bb2_bandwidth': bb2_bandwidth,
        'rsi': rsi_valor, 'volumen_alto': volumen_alto, 'regimen_mercado': regimen_mercado,
        'senal_compra': entrada_compra, 'senal_venta': entrada_venta,
        'estado': estado, 'disparo': disparo,
    })
    return df


# ── Simulación de operaciones — entrada al abrir la vela siguiente ──
#  1) La señal (COMPRA o VENTA) se conoce al CIERRE de la vela que la
#     dispara (toque de la banda estructural BB2). Para no incurrir
#     en look-ahead, la entrada real es al precio de APERTURA de la
#     vela siguiente.
#  2) Stop FIJO: ±STOP_INICIAL_PCT% desde el precio de entrada
#     (no es trailing).
#  3) Objetivo (Take Profit) FIJO: banda opuesta de la Bollinger 1
#     (rápida) — superior en un largo, inferior en un corto. Al
#     llegar el precio a ese nivel se cierra la operación ahí mismo.
#  4) Salida por pérdida de fuerza: si la posición es larga y aparece
#     la señal de VENTA, se cierra; si es corta y aparece la señal de
#     COMPRA, se cubre.

def _simular_operaciones_bb(df, stop_inicial_pct=STOP_INICIAL_PCT_DEFAULT):
    df = df.copy()
    n = len(df)
    idx = df.index
    precio_arr = df['precio'].values
    high_arr = df['high'].values
    low_arr = df['low'].values
    open_arr = df['open'].values
    estado_arr = df['estado'].values
    disparo_arr = df['disparo'].values
    senal_compra_arr = df['senal_compra'].values
    senal_venta_arr = df['senal_venta'].values
    bb1_upper_arr = df['bb1_upper'].values
    bb1_lower_arr = df['bb1_lower'].values

    resultado = [''] * n
    resultado_teorico = [''] * n
    fecha_cierre = [pd.NaT] * n
    fecha_entrada = [pd.NaT] * n
    precio_entrada_arr = [np.nan] * n
    retorno_pct = [np.nan] * n
    tomada = [False] * n
    motivo_cierre = [''] * n
    stop_final_arr = [np.nan] * n
    nivel_alcanzado_arr = [''] * n
    direccion_arr = [''] * n

    ocupado_hasta = -1

    for i in range(n):
        if not disparo_arr[i] or estado_arr[i] not in ('COMPRA', 'VENTA'):
            continue

        es_largo = estado_arr[i] == 'COMPRA'
        direccion_arr[i] = 'compra' if es_largo else 'venta'
        fue_elegible = i > ocupado_hasta

        j_fill = i + 1
        if j_fill >= n or pd.isna(open_arr[j_fill]):
            resultado_val = '⌛'
            motivo = 'Señal disparada en la última vela disponible — sin vela siguiente para entrar'
            if fue_elegible:
                resultado[i] = resultado_val
                motivo_cierre[i] = motivo
            else:
                resultado[i] = '⛔'
                resultado_teorico[i] = resultado_val
                motivo_cierre[i] = motivo
            continue

        entry = open_arr[j_fill]
        fecha_entrada_val = idx[j_fill]
        stop = entry * (1 - stop_inicial_pct / 100.0) if es_largo else entry * (1 + stop_inicial_pct / 100.0)
        nivel_texto = (f'Stop fijo {stop_inicial_pct:.1f}% desde la entrada · '
                       f'Objetivo Banda {"Superior" if es_largo else "Inferior"} BB1')

        j_exit = n - 1
        precio_exit = precio_arr[n - 1]
        motivo = 'Fin de datos (operación en curso)'

        for j in range(j_fill + 1, n):
            hi_j, lo_j, cl_j = high_arr[j], low_arr[j], precio_arr[j]
            objetivo_val = bb1_upper_arr[j] if es_largo else bb1_lower_arr[j]

            # 1) ¿Tocó el Stop fijo?
            if (es_largo and lo_j <= stop) or ((not es_largo) and hi_j >= stop):
                precio_exit, j_exit, motivo = stop, j, f'Tocó Stop (fijo {stop_inicial_pct:.1f}%)'
                break

            # 2) ¿Llegó al Objetivo (banda opuesta de BB1)?
            if not pd.isna(objetivo_val):
                alcanzo_objetivo = (hi_j >= objetivo_val) if es_largo else (lo_j <= objetivo_val)
                if alcanzo_objetivo:
                    precio_exit, j_exit, motivo = objetivo_val, j, 'Alcanzó Objetivo (Banda opuesta BB1)'
                    nivel_texto = f'Objetivo alcanzado: Banda {"Superior" if es_largo else "Inferior"} BB1'
                    break

            # 3) ¿Señal opuesta (pérdida de fuerza / se cubre el corto)?
            if es_largo and senal_venta_arr[j]:
                precio_exit, j_exit, motivo = cl_j, j, 'Señal de venta (toque de BB2 superior) — se cierra el largo'
                break
            if (not es_largo) and senal_compra_arr[j]:
                precio_exit, j_exit, motivo = cl_j, j, 'Señal de compra (toque de BB2 inferior) — se cubre el corto'
                break

        if motivo != 'Fin de datos (operación en curso)':
            ret = (precio_exit - entry) / entry * 100 if es_largo else (entry - precio_exit) / entry * 100
            res = '✅' if ret > 0 else ('❌' if ret < 0 else '➖')
            fecha_cierre_val = idx[j_exit]
        else:
            ret = np.nan
            res = '⏳'
            fecha_cierre_val = pd.NaT

        if fue_elegible:
            resultado[i] = res
            tomada[i] = True
            ocupado_hasta = j_exit if motivo != 'Fin de datos (operación en curso)' else ocupado_hasta
        else:
            resultado[i] = '⛔'
            resultado_teorico[i] = res

        fecha_entrada[i] = fecha_entrada_val
        precio_entrada_arr[i] = entry
        retorno_pct[i] = ret
        fecha_cierre[i] = fecha_cierre_val
        motivo_cierre[i] = motivo
        stop_final_arr[i] = stop
        nivel_alcanzado_arr[i] = nivel_texto

    df['direccion'] = direccion_arr
    df['resultado'] = resultado
    df['resultado_teorico'] = resultado_teorico
    df['fecha_entrada'] = fecha_entrada
    df['precio_entrada'] = precio_entrada_arr
    df['fecha_cierre'] = fecha_cierre
    df['retorno_pct'] = retorno_pct
    df['tomada'] = tomada
    df['motivo_cierre'] = motivo_cierre
    df['stop_final'] = stop_final_arr
    df['nivel_alcanzado'] = nivel_alcanzado_arr
    return df


def _color_resultado(val):
    return {'✅': 'color:#3fb950;font-weight:700', '❌': 'color:#f85149;font-weight:700',
            '⏳': 'color:#e3b341;font-weight:600', '➖': 'color:#8b949e;font-weight:600',
            '⌛': 'color:#58a6ff;font-weight:600'}.get(val, '')


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
    fig.add_trace(go.Scatter(x=df.index, y=df['precio'], line=dict(color='#3a7bd5', width=1.4), name='Precio'))

    # Bollinger 1 (rápida)
    fig.add_trace(go.Scatter(x=df.index, y=df['bb1_upper'], line=dict(color='#e3b341', width=1, dash='dot'), name='BB1 Superior'))
    fig.add_trace(go.Scatter(x=df.index, y=df['bb1_basis'], line=dict(color='#e3b341', width=1.3), name='BB1 Media'))
    fig.add_trace(go.Scatter(x=df.index, y=df['bb1_lower'], line=dict(color='#e3b341', width=1, dash='dot'), name='BB1 Inferior'))

    # Bollinger 2 (estructural)
    fig.add_trace(go.Scatter(x=df.index, y=df['bb2_upper'], line=dict(color='#a371f7', width=1, dash='dash'), name='BB2 Superior'))
    fig.add_trace(go.Scatter(x=df.index, y=df['bb2_basis'], line=dict(color='#a371f7', width=1.3, dash='dash'), name='BB2 Media'))
    fig.add_trace(go.Scatter(x=df.index, y=df['bb2_lower'], line=dict(color='#a371f7', width=1, dash='dash'), name='BB2 Inferior'))

    for tipo, color, symbol in [
        ('COMPRA', C_COMPRA, 'triangle-up'),
        ('VENTA', C_VENTA, 'triangle-down'),
    ]:
        sub = df[(df['disparo']) & (df['estado'] == tipo)]
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(
            x=sub.index, y=sub['precio'], mode='markers', name=f'Señal {tipo}',
            marker=dict(size=10, color=color, symbol=symbol, line=dict(width=1, color='#0d1117'), opacity=0.55),
        ))
    entradas_reales = df[df['tomada'] == True]
    if not entradas_reales.empty:
        fig.add_trace(go.Scatter(
            x=entradas_reales['fecha_entrada'], y=entradas_reales['precio_entrada'], mode='markers',
            name='Entrada real (apertura sig.)',
            marker=dict(size=11, color='#e6edf3', symbol='circle', line=dict(width=2, color='#3a7bd5')),
        ))
    fig.update_layout(
        **PLOTLY_LAYOUT_BASE,
        title=dict(text=f'{ticker} — Señales del Bot de Inversión (doble Bollinger)', font=dict(size=14)),
        height=500, hovermode='x unified',
        legend=dict(orientation='h', y=1.1, font=dict(size=10)),
        xaxis=dict(gridcolor='#21262d'), yaxis=dict(gridcolor='#21262d'),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    return fig


def _color_estado(estado):
    return {'COMPRA': C_COMPRA, 'VENTA': C_VENTA, '—': '#8b949e'}.get(estado, '#8b949e')


def _color_señal_bot(val):
    c = {'COMPRA': C_COMPRA, 'VENTA': C_VENTA}.get(val, '#e6edf3')
    return f'color:{c};font-weight:700'


def _color_regimen_bot(val):
    c = {'ALCISTA': C_ALCISTA, 'BAJISTA': C_BAJISTA, 'LATERAL': C_LATERAL}.get(val, '#e6edf3')
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
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">🤖 Bot de Inversión — Doble Banda de Bollinger</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Estrategia de <b style="color:#e3b341">reversión a la media</b> con
        <b style="color:#a371f7">dos Bandas de Bollinger de distinto período</b> (una rápida y una
        estructural, más larga). Entra en <b style="color:#3fb950">largo</b> apenas el precio toca la
        banda <b style="color:#a371f7">inferior de la Bollinger estructural (BB2)</b>, confirmado por
        RSI; entra en <b style="color:#f85149">corto</b> apenas toca la banda superior de la BB2. La
        entrada real es a la apertura de la vela siguiente a la señal (sin look-ahead), con Stop fijo
        inicial de <b style="color:#a371f7">1.5%</b> (configurable) y Objetivo (Take Profit) fijo en la
        banda opuesta de la Bollinger rápida (BB1): superior en un largo, inferior en un corto. Cada
        activo muestra además si el mercado está <b style="color:#3fb950">ALCISTA</b>,
        <b style="color:#f85149">BAJISTA</b> o <b style="color:#e3b341">LATERAL</b>. Analizá hasta
        <b style="color:#e3b341">10 activos</b> en
        <b style="color:#e3b341">15, 30, 45 min, 1h, 4h o 1 día</b>.
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
            st.markdown('**Bollinger 1 (rápida — banda de gatillo)**')
            bb1_length = st.number_input('Longitud (SMA)', value=BB1_LENGTH_DEFAULT, min_value=5, key='bot_bb1_length')
            bb1_std = st.number_input('Desvíos estándar', value=BB1_STD_DEFAULT, min_value=0.5, max_value=4.0, step=0.1, key='bot_bb1_std')
        with p2:
            st.markdown('**Bollinger 2 (estructural — confirmación)**')
            bb2_length = st.number_input('Longitud (SMA)', value=BB2_LENGTH_DEFAULT, min_value=10, key='bot_bb2_length')
            bb2_std = st.number_input('Desvíos estándar ', value=BB2_STD_DEFAULT, min_value=0.5, max_value=4.0, step=0.1, key='bot_bb2_std')
        with p3:
            st.markdown('**RSI y confirmación**')
            rsi_periodo = st.number_input('Período RSI', value=RSI_PERIODO_DEFAULT, min_value=2, key='bot_rsi_periodo')
            cruce_lookback_barras = st.number_input(
                'Ventana de "toque reciente" (barras)', value=CRUCE_LOOKBACK_DEFAULT, min_value=1,
                key='bot_lookback',
                help='Cuántas barras hacia atrás se admite que el RSI haya estado en sobreventa/'
                     'sobrecompra antes del toque de la banda, para no perder señales por un '
                     'desfasaje de 1-2 velas.',
            )

        p4, p5 = st.columns(2)
        with p4:
            st.markdown('**Filtros de calidad (opcional, sube el win rate)**')
            exigir_filtro_regimen = st.checkbox(
                'No comprar en régimen BAJISTA / no vender en corto en régimen ALCISTA',
                value=True, key='bot_exigir_regimen',
                help='Evita operar en contra de una tendencia de fondo fuerte, donde el precio puede '
                     '"caminar" la banda en vez de revertir.',
            )
        with p5:
            st.markdown('**Stop inicial**')
            stop_inicial_pct = st.number_input(
                'Stop inicial (% desde el precio de entrada)', value=STOP_INICIAL_PCT_DEFAULT,
                min_value=0.1, max_value=10.0, step=0.1, key='bot_stop_inicial_pct',
                help='La entrada es a la apertura de la vela siguiente a la señal. El Stop arranca a '
                     'esta distancia fija desde ese precio de entrada y no se mueve.',
            )
        st.caption(
            'Entrada: toque de la banda estructural BB2 (inferior para largo, superior para corto), '
            'confirmado por RSI. Objetivo (Take Profit) fijo en la banda opuesta de la Bollinger 1 '
            '(rápida): superior en un largo, inferior en un corto.'
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
    min_barras_necesarias = max(int(bb1_length), int(bb2_length)) * 3 + 50

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
        if cl is None or len(cl.dropna()) < min_barras_necesarias:
            fallidos.append(tk)
            continue
        hi = df_raw['High'] if 'High' in df_raw.columns else cl
        lo = df_raw['Low'] if 'Low' in df_raw.columns else cl
        op = df_raw['Open'] if 'Open' in df_raw.columns else cl
        vol = df_raw['Volume'] if 'Volume' in df_raw.columns else None
        df_bot = _calcular_bot_dataframe_bb(
            cl, hi, lo, vol, op,
            int(bb1_length), float(bb1_std), int(bb2_length), float(bb2_std), int(rsi_periodo),
            int(cruce_lookback_barras), exigir_filtro_regimen,
        )
        df_bot = _simular_operaciones_bb(df_bot, stop_inicial_pct)
        resultados_bot[tk] = df_bot

    if fallidos:
        st.warning(f"⚠️ No se pudo descargar/calcular para: {', '.join(fallidos)} "
                    f"(datos insuficientes — hacen falta al menos {min_barras_necesarias} velas —, "
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
            'Ticker': tk, 'Señal': u['estado'], 'Régimen': u['regimen_mercado'], 'Precio': fmt_precio(u['precio']),
            'Última vela': df_bot.index[-1].strftime('%Y-%m-%d %H:%M'),
            'RSI': round(u['rsi'], 1),
            'BB1 Ancho %': round(u['bb1_bandwidth'], 2) if pd.notna(u['bb1_bandwidth']) else None,
            'BB1 Media': fmt_precio(u['bb1_basis']),
            'BB2 Media': fmt_precio(u['bb2_basis']),
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
        .pipe(lambda s: getattr(s, _map)(_color_regimen_bot, subset=['Régimen']))
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

    regimen_actual = ultimo['regimen_mercado']
    color_regimen = {'ALCISTA': C_ALCISTA, 'BAJISTA': C_BAJISTA, 'LATERAL': C_LATERAL}.get(regimen_actual, '#8b949e')
    kpi_cards_4([
        ('Señal Actual', estado_actual, f'{ticker_detalle} · {horizonte_bot}', color_estado),
        ('Precio', fmt_precio(ultimo['precio']),
         f"BB1 Media: {fmt_precio(ultimo['bb1_basis'])} · BB2 Media: {fmt_precio(ultimo['bb2_basis'])}", '#3a7bd5'),
        ('RSI / Ancho BB1', f"{ultimo['rsi']:.1f} / {ultimo['bb1_bandwidth']:.2f}%" if pd.notna(ultimo['bb1_bandwidth']) else f"{ultimo['rsi']:.1f} / N/D",
         'Sobrecompra/sobreventa · compresión de banda', score_color_hex(ultimo['rsi'])),
        ('Régimen de mercado', regimen_actual, f"BB1 Sup: {fmt_precio(ultimo['bb1_upper'])} · BB1 Inf: {fmt_precio(ultimo['bb1_lower'])}", color_regimen),
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

        def _precio_entrada_fmt(v):
            return fmt_precio(v) if pd.notna(v) else '—'

        df_hist_show = pd.DataFrame({
            'Fecha/Hora señal': df_hist.index.strftime('%Y-%m-%d %H:%M'),
            'Señal': df_hist['estado'],
            'Dirección': df_hist['direccion'].map({'compra': 'Largo', 'venta': 'Corto'}).fillna('—'),
            'Tomada': df_hist['tomada'].apply(lambda v: 'Sí' if v else 'No'),
            'Resultado': df_hist['resultado'].apply(lambda v: 'No tomada' if v == '⛔' else v),
            'Si no se tomó': df_hist.apply(_resultado_si_no_tomada, axis=1),
            'Precio señal': df_hist['precio'].apply(fmt_precio),
            'Fecha entrada': df_hist['fecha_entrada'].apply(_fecha_fmt),
            'Precio entrada': df_hist['precio_entrada'].apply(_precio_entrada_fmt),
            'Fecha cierre': df_hist['fecha_cierre'].apply(_fecha_fmt),
            'Motivo cierre': df_hist['motivo_cierre'],
            'Nivel alcanzado': df_hist['nivel_alcanzado'],
            'Ganancia/Pérdida (USD)': [_ganancia_perdida_usd(ts, df_hist.loc[ts]) for ts in df_hist.index],
            'Retorno %': df_hist['retorno_pct'].apply(lambda v: f'{v:+.2f}%' if pd.notna(v) else '—'),
            'Monto operado': [_monto(ts) for ts in df_hist.index],
            'Stop final': df_hist['stop_final'].apply(lambda v: fmt_precio(v) if pd.notna(v) else '—'),
            'RSI': df_hist['rsi'].round(1),
            'Volumen alto': df_hist['volumen_alto'].apply(lambda v: 'Sí' if v else 'No'),
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
        n_bloqueadas = int((df_hist['resultado'] == '⛔').sum())
        n_pendientes = int(((df_hist['resultado'] == '⌛') | (df_hist['resultado_teorico'] == '⌛')).sum())
        st.caption(
            f'{len(df_hist_show)} señales disparadas en el historial analizado ({cfg["periodo_descarga"]} · '
            f'{horizonte_bot}) · {n_bloqueadas} ⛔ no tomadas por tener otra operación abierta · '
            f'{n_pendientes} ⌛ disparadas en la última vela disponible (sin vela siguiente para entrar). '
            'Para las bloqueadas se muestra igual, en "Si no se tomó" y "Ganancia/Pérdida (USD)", qué '
            'hubiera pasado de forma hipotética.'
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
        st.markdown(f"""
        **1) Señal (dispara apenas toca la banda, en la misma vela)**
        - **COMPRA** (largo): el precio toca (mínimo de la vela ≤) la banda **inferior de la Bollinger 2
          (estructural)**. Confirma el RSI({rsi_periodo}): venía de zona de sobreventa (<30) dentro de
          las últimas {cruce_lookback_barras} velas.
        - **VENTA** (corto / pérdida de fuerza en un largo): exactamente lo simétrico — toca la banda
          **superior de la Bollinger 2**, con RSI viniendo de sobrecompra (>70).
        - Filtro opcional activo por defecto: no operar en contra del régimen de mercado de fondo.

        **2) Entrada real: apertura de la siguiente vela**
        La señal se conoce recién al cierre de su vela, así que para no adelantarse a datos que
        todavía no existían, la entrada real es a la **apertura de la vela siguiente**.

        **3) Stop inicial fijo**
        Apenas se entra, el Stop queda fijo a **{stop_inicial_pct:.1f}%** de distancia del precio de
        entrada (por debajo en un largo, por encima en un corto) y no se mueve.

        **4) Objetivo (Take Profit) fijo**
        - Largo → Objetivo = banda **superior de la Bollinger 1 (rápida)**.
        - Corto → Objetivo = banda **inferior de la Bollinger 1 (rápida)**.
        Al llegar el precio a ese nivel, se cierra la operación ahí mismo.

        **5) Salida por pérdida de fuerza**
        Si es un largo y aparece la señal de VENTA (toque de BB2 superior), se cierra. Si es un corto y
        aparece la señal de COMPRA (toque de BB2 inferior), se cubre. Esto puede cerrar la operación
        aunque no se haya tocado el Stop ni el Objetivo.

        **📊 Régimen de mercado** (informativo + filtro opcional): compara la media de la Bollinger 1
        contra la media de la Bollinger 2 y su pendiente en las últimas {REGIMEN_PENDIENTE_BARRAS}
        barras, y descarta como LATERAL los momentos de compresión fuerte de la Bollinger 1 (squeeze).
        **ALCISTA** si la media rápida está sobre la estructural con pendiente positiva y sin squeeze,
        **BAJISTA** si es al revés, **LATERAL** en cualquier otro caso.

        **⌛ / ⛔** en la tabla de historial: ⌛ = la señal se disparó en la última vela disponible, sin
        vela siguiente todavía para entrar; ⛔ = señal válida pero no tomada porque ya había otra
        operación abierta en ese momento (igual se calcula qué hubiera pasado, de forma hipotética).

        Usalo como medida de calidad de la señal, no como tu resultado real de trading. Ningún backtest
        garantiza resultados futuros.
        """)
