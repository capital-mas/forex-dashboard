# ==============================================================
#  MÓDULO GRÁFICO EN VIVO — multiusuario, SIN claves de API
#
#  CRIPTO (BTC, ETH):  gráfico Lightweight Charts (open source de TradingView)
#     · Velas en vivo por WebSocket de Binance, conectado desde el NAVEGADOR de
#       cada usuario (sin clave y sin carga en tu servidor).
#     · Niveles GEX dibujados + marcadores de lectura de velas.
#
#  ACCIONES / ETFs / FOREX / ÍNDICES:
#     · "📺 TradingView en vivo": widget oficial gratuito de TradingView
#       (en vivo, sin clave, para todos los usuarios). No admite líneas
#       externas, por eso al lado se muestra la ESCALERA DE NIVELES GEX.
#     · "📈 Gráfico con GEX y velas": el mismo gráfico con líneas GEX y
#       marcadores, alimentado por una función que le pasás vos
#       (parámetro fuente_velas). Es opcional.
#
#  Uso:
#      from modulo_grafico_live import modulo_grafico_live
#      modulo_grafico_live(
#          selector_ticker_autocomplete=selector_ticker_autocomplete,
#          kpi_cards_4=kpi_cards_4, fmt_precio=fmt_precio,
#          fuente_velas=mi_fuente,          # opcional, ver abajo
#      )
#  fuente_velas(simbolo, intervalo) -> DataFrame Open/High/Low/Close/Volume
#      con índice de fechas, o None.  intervalo: '1m','5m','15m','30m','1h','1d'.
# ==============================================================

import json
from datetime import datetime

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

from modulo_gex import (resolver_simbolo, _gex_descargar, preparar_cadena, reparar_delta,
                        calcular_gex_por_strike, gex_total_vs_spot, calcular_zonas_gex,
                        calcular_niveles_clasificados)
from modulo_velas import preparar_velas, _render_conclusion

TZ_AR = 'America/Argentina/Buenos_Aires'
LWC_URL = 'https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js'
TV_URL = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js'

TIMEFRAMES = {'1 min': '1m', '5 min': '5m', '15 min': '15m', '30 min': '30m', '1 hora': '1h', 'Diario': '1d'}
TV_INTERVALO = {'1m': '1', '5m': '5', '15m': '15', '30m': '30', '1h': '60', '1d': 'D'}

MODO_TV = '📺 TradingView en vivo'
MODO_LW = '📈 Gráfico con GEX y velas'

_INDICES_TV = {'SPX': 'SP:SPX', 'NDX': 'NASDAQ:NDX', 'RUT': 'RUSSELL:RUT', 'VIX': 'CBOE:VIX'}
_FOREX_TV = {'EURUSD', 'GBPUSD', 'AUDUSD', 'USDJPY', 'USDCAD', 'USDCHF', 'NZDUSD', 'EURGBP', 'EURJPY', 'GBPJPY'}


# ==============================================================
#  DATOS — Binance (cripto, sin clave)
# ==============================================================

@st.cache_data(ttl=15, show_spinner=False)
def _klines_binance(par, intervalo, limite=500):
    ultimo = None
    for host in ('https://data-api.binance.vision', 'https://api.binance.com'):
        try:
            r = requests.get(f'{host}/api/v3/klines',
                             params={'symbol': par, 'interval': intervalo, 'limit': limite}, timeout=15)
            r.raise_for_status()
            filas = r.json()
            if not filas:
                raise LookupError(f'Binance no devolvió velas para {par}.')
            df = pd.DataFrame(filas).iloc[:, :6]
            df.columns = ['t', 'Open', 'High', 'Low', 'Close', 'Volume']
            df.index = pd.to_datetime(df['t'], unit='ms', utc=True)
            return df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
        except Exception as e:
            ultimo = e
    raise RuntimeError(f'No se pudo leer Binance: {type(ultimo).__name__}: {ultimo}')


# ==============================================================
#  DETECCIÓN DE CRIPTO + FUENTE POR DEFECTO PARA EL RESTO
# ==============================================================

_SUFIJOS_CRIPTO = ('-USDT', '/USDT', 'USDT', '-USD')
_ALIAS_BINANCE = {'MATIC': 'POL'}
_INDICE_YF = {'SPX': '^GSPC', 'NDX': '^NDX', 'RUT': '^RUT', 'VIX': '^VIX'}
_PERIODO_YF = {'1m': '5d', '5m': '1mo', '15m': '1mo', '30m': '1mo', '1h': '6mo', '1d': '2y'}


def _cripto_base(entrada):
    """'BNB-USD', 'SOLUSDT', 'BTC' -> 'BNB', 'SOL', 'BTC'. None si no es una cripto."""
    e = (entrada or '').strip().upper().lstrip('^')
    if e in ('BTC', 'ETH'):
        return e
    for suf in _SUFIJOS_CRIPTO:
        if e.endswith(suf) and len(e) > len(suf):
            base = e[:-len(suf)]
            if base.isalnum():
                return _ALIAS_BINANCE.get(base, base)
    return None


@st.cache_data(ttl=30, show_spinner=False)
def _velas_yahoo(simbolo, intervalo):
    """Fuente por defecto para acciones, ETFs, forex e índices (única opción sin clave del lado servidor).
    Se cachea 30 s y se comparte entre todos los usuarios. Podés reemplazarla con fuente_velas=..."""
    import yfinance as yf
    sym = _INDICE_YF.get(simbolo, simbolo)
    d = yf.download(sym, period=_PERIODO_YF[intervalo], interval=intervalo, progress=False, auto_adjust=True)
    if d is None or d.empty:
        return None
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    if not {'Open', 'High', 'Low', 'Close'}.issubset(d.columns):
        return None
    if 'Volume' not in d.columns:
        d['Volume'] = 0
    return d[['Open', 'High', 'Low', 'Close', 'Volume']].dropna(subset=['Open', 'High', 'Low', 'Close'])


# ==============================================================
#  NIVELES GEX (reutiliza modulo_gex)
# ==============================================================

def _niveles_gex(simbolo_cboe, n_vtos, rango_pct=20, r=0.045, q=0.0, mult=100):
    if simbolo_cboe.startswith('DERIBIT:'):
        mult = 1
    try:
        datos = _gex_descargar(simbolo_cboe)
    except Exception as e:
        return None, f'GEX no disponible: {type(e).__name__}: {e}'
    S = datos['spot']
    df, diag = preparar_cadena(datos['df'], n_vtos)
    if df is None:
        return None, f"GEX sin cadena utilizable: {diag['motivo']}"
    df, _ = reparar_delta(df, S, r, q)
    piv = calcular_gex_por_strike(df, S, r, q, mult, rango_pct / 100)
    if piv.empty:
        return None, 'No hay strikes con interés abierto cerca del precio.'
    grid, total = gex_total_vs_spot(df, S, r, q, mult)
    z = calcular_zonas_gex(piv, grid, total, S)
    niv = calcular_niveles_clasificados(piv, S, n=5)
    return dict(S=S, z=z, niv=niv), None


def _armar_niveles(g):
    out = {}

    def add(precio, color, titulo, style=0, width=1):
        if precio is None or pd.isna(precio):
            return
        k = round(float(precio), 2)
        if k in out:
            out[k]['title'] += f' · {titulo}'
            return
        out[k] = dict(price=float(precio), color=color, title=titulo, style=style, width=width)

    z, niv = g['z'], g['niv']
    add(z['flip'], '#bc8cff', 'Flip gamma', 2, 2)
    add(z['call_wall'], '#3fb950', 'Call Wall', 0, 2)
    add(z['put_wall'], '#f85149', 'Put Wall', 0, 2)
    cols = {'Resistencia': ('#3fb950', 'R'), 'Soporte': ('#f85149', 'S'), 'Pivote': ('#e3b341', 'Pivote')}
    for _, f in niv.iterrows():
        color, pref = cols[f['tipo']]
        principal = f['rol'] == 'Principal'
        titulo = 'Pivote' if f['tipo'] == 'Pivote' else f"{pref}{'★' if principal else ''}"
        add(f['strike'], color, titulo, 0 if principal else 1, 2 if principal else 1)
    return list(out.values())


def _render_escalera(g, fmt_precio):
    """Escalera de niveles GEX (para acompañar al widget de TradingView)."""
    S = g['S']
    filas = [dict(Nivel=n['title'], Precio=n['price']) for n in _armar_niveles(g)]
    filas.append(dict(Nivel='━━ PRECIO ACTUAL (CBOE, ~15 min) ━━', Precio=S))
    esc = pd.DataFrame(filas).sort_values('Precio', ascending=False).reset_index(drop=True)
    esc['Distancia %'] = (esc['Precio'] / S - 1) * 100
    st.dataframe(esc, use_container_width=True, hide_index=True, height=min(520, len(esc) * 36 + 45),
                 column_config={'Precio': st.column_config.NumberColumn(format='%.2f'),
                                'Distancia %': st.column_config.NumberColumn(format='%+.2f')})


# ==============================================================
#  LECTURA DE VELAS -> MARCADORES (reutiliza modulo_velas)
# ==============================================================

_PATRONES = [('MARTILLO', 'Martillo', 'belowBar', '#7ee787'),
             ('ENV_ALCISTA', 'Env. alcista', 'belowBar', '#3fb950'),
             ('ESTRELLA_FUGAZ', 'Est. fugaz', 'aboveBar', '#f0883e'),
             ('ENV_BAJISTA', 'Env. bajista', 'aboveBar', '#f85149')]


def _tiempo(idx, diario):
    if diario:
        return [t.strftime('%Y-%m-%d') for t in idx]
    return [int(t.value // 10 ** 9) for t in idx]      # índice naive en hora Argentina, tratado como UTC


def _marcadores(d, tiempos, patrones_sueltos):
    mk = []
    for i, (_, row) in enumerate(d.iterrows()):
        s, t = row['SEÑAL_VELA'], tiempos[i]
        if s == 'FRENO DE CAIDA FUERTE':
            mk.append(dict(time=t, position='belowBar', color='#3fb950', shape='arrowUp', text='Freno caída ★'))
        elif s == 'POSIBLE FRENO DE CAIDA':
            mk.append(dict(time=t, position='belowBar', color='#7ee787', shape='arrowUp', text='caída?'))
        elif s == 'FRENO DE SUBA FUERTE':
            mk.append(dict(time=t, position='aboveBar', color='#f85149', shape='arrowDown', text='Freno suba ★'))
        elif s == 'POSIBLE FRENO DE SUBA':
            mk.append(dict(time=t, position='aboveBar', color='#f0883e', shape='arrowDown', text='suba?'))
        if patrones_sueltos:
            for col, txt, pos, color in _PATRONES:
                if bool(row[col]):
                    mk.append(dict(time=t, position=pos, color=color, shape='circle', text=txt))
    return mk


# ==============================================================
#  HTML — Lightweight Charts y widget TradingView
# ==============================================================

_HTML_LW = """
<div style="position:relative;background:#0d1117;border:1px solid #21262d;border-radius:10px;overflow:hidden">
  <div id="info" style="position:absolute;z-index:5;top:8px;left:12px;font:600 12px Inter,sans-serif;color:#e6edf3"></div>
  <div id="c"></div>
</div>
<script src="__LWC__"></script>
<script>
const cfg = __CFG__;
const el = document.getElementById('c'), info = document.getElementById('info');
const chart = LightweightCharts.createChart(el, {
  width: el.clientWidth, height: cfg.height,
  layout: {background: {color: '#0d1117'}, textColor: '#b0bcd0'},
  grid: {vertLines: {color: '#161b22'}, horzLines: {color: '#161b22'}},
  rightPriceScale: {borderColor: '#21262d'},
  timeScale: {borderColor: '#21262d', timeVisible: !cfg.diario, secondsVisible: false},
  crosshair: {mode: 0},
});
const series = chart.addCandlestickSeries({upColor:'#3fb950', downColor:'#f85149',
  wickUpColor:'#3fb950', wickDownColor:'#f85149', borderVisible:false});
series.setData(cfg.candles);
cfg.levels.forEach(l => series.createPriceLine({price:l.price, color:l.color, lineWidth:l.width,
  lineStyle:l.style, axisLabelVisible:true, title:l.title}));
series.setMarkers(cfg.markers);
chart.timeScale().fitContent();
function pintar(estado, precio){ info.innerHTML = cfg.titulo + ' &nbsp; <span>' + (precio||'') + '</span> &nbsp; ' + estado; }
const last = cfg.candles[cfg.candles.length-1];
pintar('<span style="color:#6b7d9a">' + cfg.estado + '</span>', last ? last.close : '');
function toT(ms){ return cfg.diario ? new Date(ms).toISOString().slice(0,10) : Math.floor(ms/1000) - 10800; }
function conectar(){
  if(!cfg.ws) return;
  const ws = new WebSocket(cfg.ws);
  ws.onmessage = (e) => {
    const k = JSON.parse(e.data).k; if(!k) return;
    series.update({time: toT(k.t), open:+k.o, high:+k.h, low:+k.l, close:+k.c});
    pintar('<span style="color:#3fb950">● EN VIVO</span>', (+k.c).toLocaleString('en-US',{maximumFractionDigits:6}));
  };
  ws.onclose = () => { pintar('<span style="color:#e3b341">reconectando…</span>',''); setTimeout(conectar, 3000); };
  ws.onerror = () => ws.close();
}
conectar();
window.addEventListener('resize', () => chart.applyOptions({width: el.clientWidth}));
</script>
"""

_HTML_TV = """
<style>html,body{height:100%;margin:0;background:#0d1117}</style>
<div class="tradingview-widget-container" style="height:__H__px;width:100%">
  <div class="tradingview-widget-container__widget" style="height:calc(100% - 22px);width:100%"></div>
  <div class="tradingview-widget-copyright" style="font:11px Inter,sans-serif">
    <a href="https://es.tradingview.com/" rel="noopener nofollow" target="_blank" style="color:#6b7d9a">Gráficos por TradingView</a>
  </div>
  <script type="text/javascript" src="__TV__" async>__CFG__</script>
</div>
"""


def _render_lw(candles, levels, markers, titulo, diario, ws, estado, altura):
    cfg = dict(candles=candles, levels=levels, markers=markers, titulo=titulo, diario=diario,
               ws=ws, estado=estado, height=altura)
    components.html(_HTML_LW.replace('__LWC__', LWC_URL).replace('__CFG__', json.dumps(cfg)), height=altura + 24)


def _render_tv(simbolo_tv, intervalo, altura):
    cfg = {'autosize': True, 'symbol': simbolo_tv, 'interval': TV_INTERVALO[intervalo],
           'timezone': TZ_AR, 'theme': 'dark', 'style': '1', 'locale': 'es',
           'backgroundColor': '#0d1117', 'gridColor': '#161b22',
           'allow_symbol_change': True, 'hide_side_toolbar': False, 'save_image': False,
           'support_host': 'https://www.tradingview.com'}
    html = _HTML_TV.replace('__H__', str(altura)).replace('__TV__', TV_URL).replace('__CFG__', json.dumps(cfg))
    components.html(html, height=altura + 8)


def _simbolo_tv(entrada, simbolo_cboe, simbolo, base_cripto=None):
    if base_cripto:
        return f'BINANCE:{base_cripto}USDT'
    e = (entrada or '').strip().upper().lstrip('^').replace('=X', '').replace('/', '')
    if e in _FOREX_TV:
        return f'FX:{e}'
    if e == 'XAUUSD':
        return 'OANDA:XAUUSD'
    return _INDICES_TV.get(simbolo, simbolo)


# ==============================================================
#  PANELES
# ==============================================================

def _panel_lw(base_cripto, cboe_gex, simbolo, tf_label, n_vtos, ver_niveles, ver_patrones, altura,
              kpi_cards_4, fmt_precio, fuente_velas):
    iv = TIMEFRAMES[tf_label]
    diario = iv == '1d'
    cripto = base_cripto is not None
    nombre = base_cripto or simbolo

    try:
        if cripto:
            df = _klines_binance(f'{base_cripto}USDT', iv)
        else:
            df = (fuente_velas or _velas_yahoo)(simbolo, iv)
    except Exception as e:
        if cripto:
            st.error(f'{base_cripto}USDT no está disponible en Binance ({type(e).__name__}).')
        else:
            st.error(f'No se pudieron obtener velas de {simbolo}: {type(e).__name__}: {e}')
        return
    if df is None or df.empty:
        st.error(f'No hay velas disponibles para {simbolo} en esta temporalidad. Probá con otra.')
        return

    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy().tail(500)
    if diario:
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df.index = df.index.normalize()
    else:
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC')
        df.index = df.index.tz_convert(TZ_AR).tz_localize(None)
    df = df[~df.index.duplicated()].sort_index()

    cerradas = df.iloc[:-1]
    if len(cerradas) < 25:
        st.warning('Muy pocas velas para leer patrones (se necesitan ≥ 25).')
        return
    umbral = {'1d': 0.03, '1h': 0.01, '30m': 0.007, '15m': 0.005, '5m': 0.003, '1m': 0.002}[iv]
    d = preparar_velas(cerradas, umbral_mov=umbral)
    marcadores = _marcadores(d, _tiempo(d.index, diario), ver_patrones)

    niveles, aviso, g = [], None, None
    if ver_niveles:
        if cboe_gex is None:
            aviso = 'Este activo no tiene opciones listadas (en cripto solo BTC y ETH): se muestran velas y señales, sin niveles GEX.'
        else:
            g, aviso = _niveles_gex(cboe_gex, n_vtos)
            if g:
                niveles = _armar_niveles(g)

    candles = [dict(time=t, open=float(o), high=float(h), low=float(l), close=float(c))
               for t, o, h, l, c in zip(_tiempo(df.index, diario), df['Open'], df['High'], df['Low'], df['Close'])]
    ws = f'wss://data-stream.binance.vision/ws/{base_cripto.lower()}usdt@kline_{iv}' if cripto else None
    estado = 'conectando…' if cripto else 'actualiza cada 60 s'
    _render_lw(candles, niveles, marcadores, f'{nombre} · {tf_label}', diario, ws, estado, altura)

    st.caption(f"🕐 Hora Argentina · {'Binance, en vivo desde tu navegador' if cripto else 'velas con el retraso de la fuente, recarga cada 60 s'} · "
               f"panel actualizado {datetime.now().strftime('%H:%M:%S')} · señales sobre velas cerradas")
    if aviso:
        st.info(f'ℹ️ {aviso}')
    elif g:
        z = g['z']
        c1, c2, c3, c4 = st.columns(4)
        with c1: st.metric('Régimen de gamma', z['regimen'].capitalize())
        with c2: st.metric('Flip gamma', fmt_precio(z['flip']) if z['flip'] else 'N/D')
        with c3: st.metric('Call Wall', fmt_precio(z['call_wall']) if z['call_wall'] else 'N/D')
        with c4: st.metric('Put Wall', fmt_precio(z['put_wall']) if z['put_wall'] else 'N/D')
        st.caption('Violeta = flip · verde = resistencias (R★ principal) · rojo = soportes (S★) · amarillo = pivote. '
                   'Los niveles fuera del rango visible no se dibujan: alejá el zoom.')
    _render_conclusion(d, nombre, fmt_precio, kpi_cards_4, not diario)


def _panel_tv(entrada, base_cripto, simbolo_cboe, cboe_gex, simbolo, tf_label, n_vtos, ver_niveles, altura, fmt_precio):
    _render_tv(_simbolo_tv(entrada, simbolo_cboe, simbolo, base_cripto), TIMEFRAMES[tf_label], altura)
    if not ver_niveles:
        return
    st.markdown('#### 🧲 Escalera de niveles GEX')
    if cboe_gex is None:
        st.info('Este activo no tiene opciones listadas (en cripto solo BTC y ETH).')
        return
    g, aviso = _niveles_gex(cboe_gex, n_vtos)
    if aviso:
        st.info(f'ℹ️ {aviso}')
        return
    z = g['z']
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric('Régimen de gamma', z['regimen'].capitalize())
    with c2: st.metric('Flip gamma', fmt_precio(z['flip']) if z['flip'] else 'N/D')
    with c3: st.metric('Call Wall', fmt_precio(z['call_wall']) if z['call_wall'] else 'N/D')
    with c4: st.metric('Put Wall', fmt_precio(z['put_wall']) if z['put_wall'] else 'N/D')
    _render_escalera(g, fmt_precio)
    st.caption('El widget de TradingView no permite dibujar líneas externas: por eso los niveles van en esta escalera.')


# ==============================================================
#  MÓDULO PRINCIPAL
# ==============================================================

def modulo_grafico_live(selector_ticker_autocomplete, kpi_cards_4, fmt_precio, fuente_velas=None):
    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #3a7bd5;
         border-radius:14px; padding:24px 30px; margin-bottom:20px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">📺 Gráfico en vivo + GEX + Velas</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        El mismo gráfico para todos los activos, con los niveles <b style="color:#bc8cff">GEX</b> dibujados y la
        <b style="color:#3fb950">lectura de velas</b> marcada. Cripto: velas en vivo de Binance (cualquier par).
        Acciones, ETFs, forex e índices: velas con el retraso de la fuente, recargadas cada 60 s.
      </div>
    </div>
    """, unsafe_allow_html=True)

    c1, c2, c3 = st.columns([3, 1.2, 1.2])
    with c1:
        entrada = selector_ticker_autocomplete('live_ticker', st.session_state.get('ticker_from_table', ''))
    with c2:
        tf_label = st.selectbox('Temporalidad', list(TIMEFRAMES), index=1, key='live_tf')
    with c3:
        altura = st.selectbox('Alto del gráfico', [520, 640, 760], index=1, key='live_alto')

    if not entrada:
        st.info('Elegí un activo para ver el gráfico.')
        return

    simbolo_cboe, simbolo, aviso = resolver_simbolo(entrada)
    if aviso:
        st.info(aviso)
    base_cripto = _cripto_base(entrada)
    # GEX solo si hay opciones: cualquier no-cripto (CBOE) o BTC/ETH (Deribit)
    cboe_gex = None if (base_cripto and not simbolo_cboe.startswith('DERIBIT:')) else simbolo_cboe

    modo = st.radio('Modo', [MODO_LW, MODO_TV], horizontal=True, key='live_modo',
                    help='El modo TradingView es el widget oficial: no admite líneas GEX ni marcadores de velas.')

    o1, o2, o3, o4 = st.columns(4)
    with o1:
        ver_niveles = st.checkbox('Niveles GEX', value=True, key='live_gex')
    with o2:
        ver_patrones = st.checkbox('Patrones sueltos', value=False, key='live_pat', disabled=(modo == MODO_TV),
                                   help='Martillo, envolventes y estrella fugaz.')
    with o3:
        n_vtos = st.slider('Vencimientos GEX', 1, 12, 6, key='live_nvtos', disabled=not ver_niveles)
    with o4:
        auto = st.checkbox('Auto-actualizar señales', value=True, key='live_auto', disabled=(modo == MODO_TV))

    if modo == MODO_TV:
        _panel_tv(entrada, base_cripto, simbolo_cboe, cboe_gex, simbolo, tf_label, n_vtos, ver_niveles, altura, fmt_precio)
    else:
        # cripto: el WebSocket mueve la vela; el panel solo recalcula señales y GEX cada 5 min
        run_every = (300 if base_cripto else 60) if auto else None
        st.fragment(run_every=run_every)(_panel_lw)(
            base_cripto, cboe_gex, simbolo, tf_label, n_vtos, ver_niveles, ver_patrones, altura,
            kpi_cards_4, fmt_precio, fuente_velas)

    st.markdown(
        '<div style="font-size:11px;color:#6b7d9a;margin-top:12px">GEX: opciones de CBOE/Deribit con ~15 min de '
        'retraso e interés abierto del día anterior. Las señales y niveles son herramientas de lectura, '
        'no asesoramiento financiero.</div>',
        unsafe_allow_html=True)
