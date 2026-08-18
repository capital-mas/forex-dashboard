# ==============================================================
#  CONFIGURACIÓN DE ACTIVOS
#  Diccionarios centrales usados por el módulo de Análisis Técnico
#  (y potencialmente por otros módulos de la app: rotación, etc.)
# ==============================================================

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
