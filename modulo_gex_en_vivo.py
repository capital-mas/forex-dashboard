# ==============================================================
#  MÓDULO GEX EN VIVO — velas en tiempo real + niveles de GEX dibujados en el gráfico
#  Une modulo_gex.py y modulo_velas.py (los dos deben estar en la misma carpeta).
#  NO usa Yahoo Finance.
#
#  Fuentes de precio en vivo (se conectan desde el navegador, sin recargar Streamlit):
#   · BTC / ETH  → Binance (REST para el historial + WebSocket de velas). Gratis, sin clave.
#   · Acciones, ETFs, ADRs, divisas/commodities vía ETF → Alpaca, feed IEX (tiempo real, GRATIS).
#       Requiere cuenta gratuita en alpaca.markets (alcanza la de paper trading).
#       Cargá las claves en .streamlit/secrets.toml:
#           ALPACA_KEY = "..."
#           ALPACA_SECRET = "..."
#       (o pegalas en el desplegable del módulo; valen solo para la sesión).
#   · Índices (SPX, NDX, RUT, XSP, DJX) → se grafica el ETF equivalente (SPY, QQQ, IWM, SPY, DIA)
#       y los niveles se reescalan automáticamente (precio ETF / precio del índice).
#
#  Los niveles GEX salen de la cadena de CBOE/Deribit (modulo_gex) y se dibujan como líneas de
#  precio dentro del gráfico: punto de cambio de gamma, paredes, resistencias/soportes,
#  pivotes, movimiento esperado y Max Pain (cada grupo se prende/apaga desde el gráfico).
#
#  Uso:   from modulo_gex_en_vivo import modulo_gex_en_vivo
#         modulo_gex_en_vivo()
#  Requiere: streamlit (>= 1.37), pandas, numpy, scipy, plotly, requests
# ==============================================================

import json
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

from modulo_gex import (
    ATAJOS_MERCADOS, LIQUIDEZ_BAJA, resolver_simbolo, fmt_precio, _gex_descargar, preparar_cadena,
    reparar_delta, calcular_gex_por_strike, gex_total_vs_spot, calcular_zonas_gex,
    calcular_niveles_clasificados, calcular_top_niveles, calcular_movimiento_esperado,
    calcular_max_pain, _subset_vtos, publicar_puente_gex, render_squeeze,
    render_niveles_clasificados, lectura_personalizada_gex)
from modulo_velas import (
    preparar_velas, _SENAL_STYLE, _patrones_detectados, _texto_conclusion, _retornos_mc,
    _simular_mc, _prob_toque, MC_MIN_RETORNOS, fmt_px_mc)

C_GREEN, C_RED, C_YELL, C_ACENT, C_MUTED = '#3fb950', '#f85149', '#e3b341', '#3a7bd5', '#6b7d9a'
ALTURA_GRAFICO = 620

# Índices sin precio en vivo gratuito → ETF equivalente (los niveles se reescalan)
PROXY_GRAFICO = {'SPX': 'SPY', 'NDX': 'QQQ', 'RUT': 'IWM', 'XSP': 'SPY', 'DJX': 'DIA'}
SIN_GRAFICO = {'VIX'}                           # no hay ETF que replique su precio

TF_SEG = {'1m': 60, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600, '1d': 86400}
TF_ALPACA = {'1m': '1Min', '5m': '5Min', '15m': '15Min', '30m': '30Min', '1h': '1Hour', '1d': '1Day'}
DIAS_ATRAS = {'1m': 5, '5m': 12, '15m': 25, '30m': 40, '1h': 80, '1d': 900}
BINANCE_HOSTS = ['https://data-api.binance.vision', 'https://api.binance.com', 'https://api.binance.us']
UMBRAL_MOV = {'1m': 0.003, '5m': 0.004, '15m': 0.005, '30m': 0.007, '1h': 0.01, '1d': 0.03}


# ==============================================================
#  DATOS EN VIVO: historial por REST (Binance / Alpaca)
# ==============================================================

def _fuente_grafico(simbolo):
    """Devuelve (fuente, simbolo_del_grafico) o (None, motivo)."""
    if simbolo in ('BTC', 'ETH'):
        return 'binance', f'{simbolo}USDT'
    if simbolo in SIN_GRAFICO:
        return None, f'{simbolo} no tiene un precio en vivo gratuito equivalente (no hay ETF que lo replique).'
    return 'alpaca', PROXY_GRAFICO.get(simbolo, simbolo)


def _claves_alpaca():
    ak = st.session_state.get('gv_alpaca_key', '').strip()
    sk = st.session_state.get('gv_alpaca_secret', '').strip()
    if ak and sk:
        return ak, sk
    try:
        return str(st.secrets['ALPACA_KEY']), str(st.secrets['ALPACA_SECRET'])
    except Exception:
        return None, None


@st.cache_data(ttl=20, show_spinner=False)
def _hist_binance(par, tf, limite=500):
    ultimo = None
    for host in BINANCE_HOSTS:
        try:
            r = requests.get(f'{host}/api/v3/klines', params={'symbol': par, 'interval': tf, 'limit': limite},
                             timeout=15)
            r.raise_for_status()
            filas = r.json()
            if not filas:
                raise ValueError('Binance respondió sin velas.')
            h = pd.DataFrame(filas).iloc[:, :6]
            h.columns = ['t', 'Open', 'High', 'Low', 'Close', 'Volume']
            h['t'] = h['t'].astype('int64') // 1000
            for c in ('Open', 'High', 'Low', 'Close', 'Volume'):
                h[c] = h[c].astype(float)
            return h
        except Exception as e:
            ultimo = e
    raise RuntimeError(f'No se pudo leer Binance ({type(ultimo).__name__}: {ultimo})')


@st.cache_data(ttl=20, show_spinner=False)
def _hist_alpaca(sym, tf, ak, sk, limite=500):
    desde = (datetime.utcnow() - timedelta(days=DIAS_ATRAS[tf])).strftime('%Y-%m-%dT%H:%M:%SZ')
    cab = {'APCA-API-KEY-ID': ak, 'APCA-API-SECRET-KEY': sk, 'accept': 'application/json'}
    params = {'symbols': sym, 'timeframe': TF_ALPACA[tf], 'start': desde, 'limit': 10000,
              'feed': 'iex', 'adjustment': 'raw', 'sort': 'asc'}
    barras, token = [], None
    for _ in range(8):
        if token:
            params['page_token'] = token
        r = requests.get('https://data.alpaca.markets/v2/stocks/bars', params=params, headers=cab, timeout=20)
        if r.status_code in (401, 403):
            raise PermissionError('Alpaca rechazó las claves (revisá ALPACA_KEY / ALPACA_SECRET).')
        r.raise_for_status()
        js = r.json()
        barras += (js.get('bars') or {}).get(sym, [])
        token = js.get('next_page_token')
        if not token:
            break
    if not barras:
        raise LookupError(f'Alpaca no devolvió velas para {sym} (¿símbolo sin cotización en IEX o mercado sin operaciones?).')
    h = pd.DataFrame(barras).rename(columns={'o': 'Open', 'h': 'High', 'l': 'Low', 'c': 'Close', 'v': 'Volume'})
    h['t'] = pd.to_datetime(h['t'], utc=True).map(lambda x: int(x.timestamp()))
    h = h[['t', 'Open', 'High', 'Low', 'Close', 'Volume']].astype(
        {'Open': float, 'High': float, 'Low': float, 'Close': float, 'Volume': float})
    return h.tail(limite).reset_index(drop=True)


def _cargar_hist(fuente, par, tf, ak=None, sk=None):
    if fuente == 'binance':
        return _hist_binance(par, tf)
    if not ak or not sk:
        raise PermissionError('Faltan las claves gratuitas de Alpaca para las acciones y ETFs.')
    return _hist_alpaca(par, tf, ak, sk)


def _a_dataframe(h):
    """Historial → DataFrame con índice horario Argentina (sin zona), como espera modulo_velas."""
    idx = pd.to_datetime(h['t'], unit='s', utc=True).dt.tz_convert('America/Argentina/Buenos_Aires').dt.tz_localize(None)
    d = h[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
    d.index = pd.DatetimeIndex(idx)
    return d


# ==============================================================
#  NIVELES GEX → líneas del gráfico
# ==============================================================

def construir_niveles(z, niv, t_em, t_mp, escala):
    """Lista de niveles listos para dibujar. 'estilo' de lightweight-charts: 0 sólida · 1 punteada · 2 guiones · 3 guiones largos."""
    out = []

    def add(grupo, nombre, precio, color, ancho, estilo):
        if precio is None or not np.isfinite(precio):
            return
        txt = nombre if escala == 1.0 else f'{nombre} [{precio:,.0f}]'
        out.append({'grupo': grupo, 'nombre': txt, 'precio': round(float(precio) * escala, 6),
                    'real': float(precio), 'color': color, 'ancho': ancho, 'estilo': estilo})

    add('flip', 'Gamma Flip', z['flip'], '#bc8cff', 2, 2)
    add('paredes', 'Call Wall', z['call_wall'], C_GREEN, 3, 0)
    add('paredes', 'Put Wall', z['put_wall'], C_RED, 3, 0)

    paredes = {z['call_wall'], z['put_wall']}
    if niv is not None and not niv.empty:
        for _, r in niv.iterrows():
            if r['strike'] in paredes:
                continue
            est = '★ ' if r['rol'] == 'Principal' else ''
            if r['tipo'] == 'Resistencia':
                add('niveles', f'{est}Resistencia', r['strike'], C_GREEN, 2 if est else 1, 1)
            elif r['tipo'] == 'Soporte':
                add('niveles', f'{est}Soporte', r['strike'], C_RED, 2 if est else 1, 1)
            else:
                add('pivotes', f'{est}Pivote / Pinning', r['strike'], C_YELL, 2, 2)

    if t_em is not None and not t_em.empty:
        c = t_em[t_em['dias'] >= 1]
        f = (c if not c.empty else t_em).iloc[0]
        add('em', 'Techo esperado', f['alto'], C_MUTED, 1, 3)
        add('em', 'Piso esperado', f['bajo'], C_MUTED, 1, 3)
    if t_mp is not None and not t_mp.empty:
        c = t_mp[t_mp['dias'] >= 1]
        f = (c if not c.empty else t_mp).iloc[0]
        add('maxpain', 'Max Pain', f['max_pain'], '#58a6ff', 2, 2)
    return out


# ==============================================================
#  GRÁFICO EN VIVO (lightweight-charts + WebSocket en el navegador)
# ==============================================================

_HTML = """
<style>
  body{margin:0;background:#07090f;font-family:Inter,system-ui,sans-serif;color:#b0bcd0}
  #bar{display:flex;flex-wrap:wrap;gap:14px;align-items:center;padding:8px 10px;font-size:12px;
       border:1px solid #21262d;border-bottom:none;border-radius:10px 10px 0 0;background:#0d1117}
  #sym{font-weight:700;color:#e6edf3;font-size:14px}
  #px{font-weight:800;font-size:16px;color:#e6edf3}
  #estado{font-size:11px}
  #msg{color:#e3b341;font-size:11px;padding:0 10px}
  label{cursor:pointer;display:flex;align-items:center;gap:4px;font-size:11px}
  #chart{border:1px solid #21262d;border-radius:0 0 10px 10px;overflow:hidden}
</style>
<div id="bar"><span id="sym"></span><span id="px">…</span><span id="pct"></span><span id="estado">conectando…</span>
  <span id="tg" style="display:flex;gap:10px;flex-wrap:wrap;margin-left:auto"></span></div>
<div id="msg"></div>
<div id="chart"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/lightweight-charts/4.1.3/lightweight-charts.standalone.production.js"></script>
<script>
(function(){
const CFG = __CFG__;
const $ = id => document.getElementById(id);
if (typeof LightweightCharts === 'undefined'){ $('estado').textContent='No se pudo cargar la librería del gráfico (cdnjs).'; return; }

const fDia = new Intl.DateTimeFormat('es-AR',{timeZone:'America/Argentina/Buenos_Aires',day:'2-digit',month:'2-digit'});
const fHora = new Intl.DateTimeFormat('es-AR',{timeZone:'America/Argentina/Buenos_Aires',hour:'2-digit',minute:'2-digit',hour12:false});
const fmtT = t => { const d=new Date(t*1000); return CFG.seg>=86400 ? fDia.format(d) : fDia.format(d)+' '+fHora.format(d); };

$('sym').textContent = CFG.titulo;
const el = $('chart');
const chart = LightweightCharts.createChart(el, {
  width: el.clientWidth, height: CFG.altura,
  layout:{background:{type:'solid',color:'#0d1117'},textColor:'#b0bcd0'},
  grid:{vertLines:{color:'#161b22'},horzLines:{color:'#161b22'}},
  crosshair:{mode:0},
  rightPriceScale:{borderColor:'#21262d'},
  timeScale:{borderColor:'#21262d',timeVisible:true,secondsVisible:false,rightOffset:8,
             tickMarkFormatter:(t,type)=>{const d=new Date(t*1000); return type>=3 ? fHora.format(d) : fDia.format(d);}},
  localization:{timeFormatter:fmtT}
});
const vela = chart.addCandlestickSeries({upColor:'#3fb950',downColor:'#f85149',borderUpColor:'#3fb950',
  borderDownColor:'#f85149',wickUpColor:'#3fb950',wickDownColor:'#f85149',
  priceFormat:{type:'price',precision:CFG.prec,minMove:Math.pow(10,-CFG.prec)}});
const vol = chart.addHistogramSeries({priceFormat:{type:'volume'},priceScaleId:'',lastValueVisible:false,priceLineVisible:false});
vol.priceScale().applyOptions({scaleMargins:{top:0.84,bottom:0}});
const s20 = chart.addLineSeries({color:'#e3b341',lineWidth:1,priceLineVisible:false,lastValueVisible:false});
const s50 = chart.addLineSeries({color:'#3a7bd5',lineWidth:1,priceLineVisible:false,lastValueVisible:false});

let velas = CFG.velas.slice(), vols = CFG.vol.slice();
vela.setData(velas); vol.setData(vols);
const colVol = c => c.close>=c.open ? 'rgba(63,185,80,.45)' : 'rgba(248,81,73,.45)';
function smaSerie(n){const o=[];let s=0;for(let i=0;i<velas.length;i++){s+=velas[i].close;if(i>=n)s-=velas[i-n].close;if(i>=n-1)o.push({time:velas[i].time,value:s/n});}return o;}
s20.setData(smaSerie(20)); s50.setData(smaSerie(50));
function smaUlt(n){ if(velas.length<n) return null; let s=0; for(let i=velas.length-n;i<velas.length;i++) s+=velas[i].close; return {time:velas[velas.length-1].time,value:s/n}; }
function refrescarSMA(){ const a=smaUlt(20), b=smaUlt(50); if(a) s20.update(a); if(b) s50.update(b); }

// ── niveles GEX como líneas de precio ──
const GRUPOS = {flip:['Gamma Flip',true],paredes:['Paredes',true],niveles:['Resist./Soportes',true],
                pivotes:['Pivotes',true],em:['Mov. esperado',false],maxpain:['Max Pain',false]};
const ultimoPx = () => velas[velas.length-1].close;
function dibujar(g,on){
  CFG.niveles.filter(n=>n.grupo===g).forEach(n=>{
    if(on && !n._l){ n._l = vela.createPriceLine({price:n.precio,color:n.color,lineWidth:n.ancho,lineStyle:n.estilo,axisLabelVisible:true,title:n.nombre}); }
    else if(!on && n._l){ vela.removePriceLine(n._l); n._l=null; }
  });
}
vela.applyOptions({autoscaleInfoProvider: orig => {
  const r = orig(); if(!r) return r;
  const p = ultimoPx();
  const ps = CFG.niveles.filter(n=>n._l && Math.abs(n.precio/p-1)<=0.08).map(n=>n.precio);
  if(!ps.length) return r;
  return {priceRange:{minValue:Math.min(r.priceRange.minValue,...ps),maxValue:Math.max(r.priceRange.maxValue,...ps)},margins:r.margins};
}});
Object.keys(GRUPOS).forEach(g=>{
  if(!CFG.niveles.some(n=>n.grupo===g)) return;
  const l=document.createElement('label'); const cb=document.createElement('input');
  cb.type='checkbox'; cb.checked=GRUPOS[g][1];
  cb.onchange=()=>{dibujar(g,cb.checked); chart.priceScale('right').applyOptions({autoScale:true});};
  l.appendChild(cb); l.appendChild(document.createTextNode(GRUPOS[g][0])); $('tg').appendChild(l);
  dibujar(g,cb.checked);
});
chart.timeScale().scrollToRealTime();

// ── precio y estado ──
let abierto=false, ultMsg=0;
function mostrarPrecio(p){
  const ref = velas.length>1 ? velas[velas.length-2].close : velas[0].open;
  const pct=(p/ref-1)*100;
  $('px').textContent = p.toFixed(CFG.prec);
  $('pct').textContent = (pct>=0?'+':'')+pct.toFixed(2)+'%';
  $('pct').style.color = pct>=0 ? '#3fb950' : '#f85149';
}
mostrarPrecio(ultimoPx());
setInterval(()=>{
  const e=$('estado');
  if(abierto && Date.now()-ultMsg<20000){ e.textContent='🟢 EN VIVO'; e.style.color='#3fb950'; }
  else if(abierto){ e.textContent='🟡 conectado, sin operaciones recientes (¿mercado cerrado?)'; e.style.color='#e3b341'; }
  else { e.textContent='🔴 conectando…'; e.style.color='#f85149'; }
},1000);

// ── actualización de velas ──
function tick(price,size,tSec){
  const last=velas[velas.length-1]; let c,v;
  if(tSec < last.time) return;
  if(tSec < last.time + CFG.seg){
    c={time:last.time,open:last.open,high:Math.max(last.high,price),low:Math.min(last.low,price),close:price};
    v={time:last.time,value:(vols[vols.length-1].value||0)+size,color:colVol(c)};
    velas[velas.length-1]=c; vols[vols.length-1]=v;
  } else {
    const t=last.time+Math.floor((tSec-last.time)/CFG.seg)*CFG.seg;
    c={time:t,open:price,high:price,low:price,close:price};
    v={time:t,value:size,color:colVol(c)};
    velas.push(c); vols.push(v);
  }
  vela.update(c); vol.update(v); refrescarSMA(); mostrarPrecio(price);
}
function kline(k){
  const t=Math.floor(k.t/1000);
  const c={time:t,open:+k.o,high:+k.h,low:+k.l,close:+k.c};
  const v={time:t,value:+k.v,color:colVol(c)};
  const last=velas[velas.length-1];
  if(t===last.time){velas[velas.length-1]=c; vols[vols.length-1]=v;}
  else if(t>last.time){velas.push(c); vols.push(v);} else return;
  vela.update(c); vol.update(v); refrescarSMA(); mostrarPrecio(c.close);
}

// ── conexiones ──
function binance(i){
  const hosts=['wss://stream.binance.com:9443/ws/','wss://data-stream.binance.vision/ws/'];
  const ws=new WebSocket(hosts[i%hosts.length]+CFG.par.toLowerCase()+'@kline_'+CFG.tf);
  ws.onopen=()=>{abierto=true;};
  ws.onmessage=e=>{const m=JSON.parse(e.data); if(m.k){ultMsg=Date.now(); kline(m.k);}};
  ws.onclose=()=>{abierto=false; setTimeout(()=>binance(i+1),2000);};
  ws.onerror=()=>ws.close();
}
function alpaca(){
  const ws=new WebSocket('wss://stream.data.alpaca.markets/v2/iex');
  let espera=3000;
  ws.onopen=()=>ws.send(JSON.stringify({action:'auth',key:CFG.key,secret:CFG.secret}));
  ws.onmessage=e=>{ JSON.parse(e.data).forEach(m=>{
    if(m.T==='success' && m.msg==='authenticated'){abierto=true; $('msg').textContent=''; ws.send(JSON.stringify({action:'subscribe',trades:[CFG.par]}));}
    else if(m.T==='error'){ $('msg').textContent='Alpaca: '+m.msg+' (código '+m.code+')'+(m.code===406?' — solo se permite 1 conexión por cuenta: cerrá otras pestañas.':''); espera=10000; }
    else if(m.T==='t'){ ultMsg=Date.now(); tick(m.p,m.s,Date.parse(m.t.replace(/(\\.\\d{3})\\d+/,'$1'))/1000); }
  });};
  ws.onclose=()=>{abierto=false; setTimeout(alpaca,espera);};
  ws.onerror=()=>ws.close();
}
if(CFG.fuente==='binance') binance(0); else alpaca();
new ResizeObserver(()=>chart.applyOptions({width:el.clientWidth})).observe(el);
})();
</script>
"""


def _render_grafico(h, fuente, par, tf, titulo, niveles, ak, sk):
    precio_ref = float(h['Close'].iloc[-1])
    cfg = {
        'fuente': fuente, 'par': par, 'tf': tf, 'seg': TF_SEG[tf], 'altura': ALTURA_GRAFICO,
        'prec': 2 if precio_ref >= 1 else 5, 'titulo': titulo,
        'velas': [{'time': int(r.t), 'open': r.Open, 'high': r.High, 'low': r.Low, 'close': r.Close}
                  for r in h.itertuples()],
        'vol': [{'time': int(r.t), 'value': r.Volume,
                 'color': 'rgba(63,185,80,.45)' if r.Close >= r.Open else 'rgba(248,81,73,.45)'}
                for r in h.itertuples()],
        'niveles': niveles,
        'key': ak if fuente == 'alpaca' else '', 'secret': sk if fuente == 'alpaca' else '',
    }
    html = _HTML.replace('__CFG__', json.dumps(cfg))
    components.html(html, height=ALTURA_GRAFICO + 75)


# ==============================================================
#  PESTAÑAS INFERIORES
# ==============================================================

def _tab_velas(h, tf, niveles, S0):
    d = _a_dataframe(h)
    if d.index[-1] + pd.Timedelta(seconds=TF_SEG[tf]) > pd.Timestamp.now():      # vela en formación
        d = d.iloc[:-1]
    d = preparar_velas(d, umbral_mov=UMBRAL_MOV[tf])
    if len(d) < 25:
        st.info('Hay muy poco historial para leer las velas con indicadores confiables (se necesitan ≥ 25 velas).')
        return
    u = d.iloc[-1]
    emoji, color = _SENAL_STYLE.get(u['SEÑAL_VELA'], ('⚪', '#8b949e'))
    cuerpo, lvl = _texto_conclusion(u, fmt_px_mc)
    pats = _patrones_detectados(u)
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric('Último cierre (vela completa)', fmt_px_mc(u['Close']))
    with c2: st.metric('RSI 14', f"{u['RSI14']:.1f}")
    with c3: st.metric('Score freno de caída', f"{int(u['SCORE_ALCISTA'])}/8")
    with c4: st.metric('Score freno de suba', f"{int(u['SCORE_BAJISTA'])}/8")
    st.markdown(f"""
    <div style="background:{color}15;border:1.5px solid {color};border-radius:12px;padding:16px 20px;text-align:center;margin:10px 0">
      <div style="font-size:11px;color:#8b949e;text-transform:uppercase;letter-spacing:1px">Señal de la última vela completa</div>
      <div style="font-size:21px;font-weight:800;color:{color}">{emoji} {u['SEÑAL_VELA']}</div>
    </div>""", unsafe_allow_html=True)
    st.markdown(f"**Patrones:** {', '.join(pats) if pats else 'ninguno relevante'}")
    st.markdown(f'{cuerpo}<br><br>{lvl}', unsafe_allow_html=True)

    arriba = sorted([n for n in niveles if n['precio'] > S0], key=lambda n: n['precio'])
    abajo = sorted([n for n in niveles if n['precio'] < S0], key=lambda n: -n['precio'])
    st.markdown('**Contexto GEX alrededor del precio:**')
    if arriba:
        n = arriba[0]
        st.markdown(f"- Nivel GEX más cercano **arriba**: {n['nombre']} en **{fmt_px_mc(n['precio'])}** ({(n['precio']/S0-1)*100:+.2f}%)")
    if abajo:
        n = abajo[0]
        st.markdown(f"- Nivel GEX más cercano **abajo**: {n['nombre']} en **{fmt_px_mc(n['precio'])}** ({(n['precio']/S0-1)*100:+.2f}%)")
    st.caption('Una señal de vela pegada a un nivel GEX pesa más que una aislada. No es asesoramiento financiero.')


def _tab_prob(fuente, par, ak, sk, niveles, S0):
    h_mc = st.radio('Horizonte', ['1h', '1d'], horizontal=True, key='gv_mc_h',
                    format_func=lambda k: {'1h': 'Próxima 1 hora', '1d': 'Próximo 1 día'}[k])
    try:
        dmc = _a_dataframe(_cargar_hist(fuente, par, h_mc, ak, sk))
    except Exception as e:
        st.warning(f'No se pudo bajar el historial para el Monte Carlo: {e}')
        return
    ret = _retornos_mc(dmc, h_mc)
    if len(ret) < MC_MIN_RETORNOS:
        st.warning(f'Hay muy pocos retornos ({len(ret)}) para estimar la volatilidad.')
        return
    sigma = float(ret.std(ddof=1))
    paths = _simular_mc(S0, -0.5 * sigma ** 2, sigma, 5000)
    fin = paths[-1]
    filas = []
    for n in sorted(niveles, key=lambda n: -n['precio']):
        p = n['precio']
        arriba = p > S0
        filas.append({'Nivel': n['nombre'], 'Precio': fmt_px_mc(p), 'Distancia': f'{(p / S0 - 1) * 100:+.2f}%',
                      'Sentido': '▲ Arriba' if arriba else '▼ Abajo',
                      'Prob. de tocarlo': f'{_prob_toque(paths, p, sigma):.1f}%',
                      'Prob. de terminar más allá': f"{(np.mean(fin >= p) if arriba else np.mean(fin <= p)) * 100:.1f}%"})
    if not filas:
        st.info('No hay niveles GEX para evaluar.')
        return
    st.metric('Volatilidad por ' + ('hora' if h_mc == '1h' else 'día'), f'{sigma * 100:.2f}%')
    st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)
    st.caption('Monte Carlo (movimiento browniano, sin drift) desde el último precio. Es la probabilidad de que el precio '
               'toque cada nivel GEX dentro del horizonte. No contempla gaps ni cambios de régimen.')


# ==============================================================
#  UI PRINCIPAL
# ==============================================================

def _aplicar_atajo_gv():
    sym = ATAJOS_MERCADOS.get(st.session_state.get('gv_atajo'))
    if sym:
        st.session_state['gv_ticker'] = sym


def modulo_gex_en_vivo():
    st.markdown("""
    <div style="background:linear-gradient(135deg,#1c1020 0%,#2a0a30 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #bc8cff; border-radius:14px; padding:24px 30px; margin-bottom:20px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">📡 GEX en vivo — velas en tiempo real + niveles de gamma</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Gráfico con precio en vivo (Binance para cripto, Alpaca-IEX para acciones y ETFs; sin Yahoo) y los niveles de
        <b style="color:#bc8cff">punto de cambio de gamma</b>, <b style="color:#3fb950">paredes</b>,
        <b style="color:#f85149">soportes/resistencias</b>, pivotes, movimiento esperado y Max Pain dibujados adentro.
      </div>
    </div>""", unsafe_allow_html=True)

    st.selectbox('Atajos por mercado', list(ATAJOS_MERCADOS), key='gv_atajo', on_change=_aplicar_atajo_gv)
    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    with c1:
        entrada = st.text_input('Símbolo (SPY, NVDA, GGAL, GLD, FXE, BTC, ETH; EURUSD, XAUUSD, GC=F...)', value='SPY', key='gv_ticker')
    with c2:
        tf = st.selectbox('Temporalidad', list(TF_SEG), index=1, key='gv_tf',
                          format_func=lambda x: {'1m': '1 min', '5m': '5 min', '15m': '15 min', '30m': '30 min',
                                                 '1h': '1 hora', '1d': 'Diaria'}[x])
    with c3:
        n_vtos = st.slider('Vencimientos', 1, 12, 6, key='gv_nvtos',
                           help='Vencimientos que entran en el cálculo del GEX.')
    with c4:
        rango_pct = st.slider('Rango (±%)', 5, 30, 20, key='gv_rango')

    with st.expander('⚙️ Parámetros avanzados', expanded=False):
        a1, a2, a3 = st.columns(3)
        with a1: r = st.number_input('Tasa de interés anual', 0.0, 1.0, 0.045, 0.005, format='%.4f', key='gv_r')
        with a2: q = st.number_input('Rendimiento por dividendos', 0.0, 0.5, 0.0, 0.005, format='%.4f', key='gv_q')
        with a3: mult = st.number_input('Multiplicador de contrato', 1, 1000, 100, 1, key='gv_mult')

    with st.expander('🔑 Claves gratuitas de Alpaca (solo para acciones / ETFs)', expanded=False):
        st.caption('Creá una cuenta gratis en alpaca.markets (sirve la de paper trading) y copiá la API key y el secret. '
                   'Lo ideal es ponerlas en .streamlit/secrets.toml como ALPACA_KEY y ALPACA_SECRET. '
                   'Las claves viajan al navegador para abrir el WebSocket: usá claves de paper trading.')
        k1, k2 = st.columns(2)
        with k1: st.text_input('API key', type='password', key='gv_alpaca_key')
        with k2: st.text_input('Secret', type='password', key='gv_alpaca_secret')

    if not entrada.strip():
        st.info('Ingresá un símbolo para continuar.')
        return

    simbolo_cboe, simbolo, aviso = resolver_simbolo(entrada)
    if aviso:
        st.info(aviso)
    es_cripto = simbolo_cboe.startswith('DERIBIT:')
    if es_cripto:
        mult = 1
    if simbolo in LIQUIDEZ_BAJA:
        st.warning(f'⚠️ Las opciones de **{simbolo}** suelen tener poco interés abierto: los niveles pueden ser poco confiables.')

    if st.button('🔄 Actualizar datos', key='gv_refresh'):
        _gex_descargar.clear()
        _hist_binance.clear()
        _hist_alpaca.clear()
        st.rerun()

    # ── 1) GEX ──
    try:
        with st.spinner(f"Descargando cadena de {simbolo} ({'Deribit' if es_cripto else 'CBOE'})..."):
            datos = _gex_descargar(simbolo_cboe)
    except Exception as e:
        st.error(f'No se pudieron obtener datos de opciones de {simbolo}.')
        st.code(f'{type(e).__name__}: {e}')
        return

    S = datos['spot']
    df, diag = preparar_cadena(datos['df'], n_vtos)
    if df is None:
        st.warning(f"No hay cadena utilizable: {diag['motivo']}")
        return
    df, _ = reparar_delta(df, S, r, q)
    piv = calcular_gex_por_strike(df, S, r, q, mult, rango_pct / 100)
    if piv.empty:
        st.warning('No hay strikes con interés abierto cerca del precio. Ampliá el rango o sumá vencimientos.')
        return
    grid, total = gex_total_vs_spot(df, S, r, q, mult)
    z = calcular_zonas_gex(piv, grid, total, S)
    niv = calcular_niveles_clasificados(piv, S, n=5)
    top_c, top_p = calcular_top_niveles(piv, S, n=5)
    d_sub = _subset_vtos(datos['df'], n_vtos)
    t_em = calcular_movimiento_esperado(d_sub, S)
    t_mp, _ = calcular_max_pain(d_sub, S, mult)

    publicar_puente_gex(simbolo, S, z, extra={
        'top_calls': top_c['strike'].tolist(), 'top_puts': top_p['strike'].tolist(),
        'resistencias': sorted(niv.loc[niv['tipo'] == 'Resistencia', 'strike'].tolist()),
        'pivotes': niv.loc[niv['tipo'] == 'Pivote', 'strike'].tolist(),
        'soportes': sorted(niv.loc[niv['tipo'] == 'Soporte', 'strike'].tolist(), reverse=True)})

    st.caption(f"📡 Opciones: {datos.get('fuente', 'CBOE')} (retraso ~15 min, interés abierto del día anterior) · {simbolo} · "
               f"precio de referencia {fmt_precio(S)} · {diag['vtos']} vencimientos · {diag['filas']:,} contratos. "
               'Los niveles GEX se mueven despacio; el precio del gráfico sí es en vivo.')
    m1, m2, m3, m4 = st.columns(4)
    with m1: st.metric('Régimen de gamma', z['regimen'].capitalize())
    with m2: st.metric('Punto de cambio de gamma', fmt_precio(z['flip']) if z['flip'] else 'N/D')
    with m3: st.metric('Pared de Calls', fmt_precio(z['call_wall']) if z['call_wall'] else 'N/D')
    with m4: st.metric('Pared de Puts', fmt_precio(z['put_wall']) if z['put_wall'] else 'N/D')

    # ── 2) Historial en vivo + gráfico ──
    fuente, par = _fuente_grafico(simbolo)
    ak, sk = _claves_alpaca()
    h, err = None, None
    if fuente is None:
        err = par
    else:
        try:
            with st.spinner(f'Cargando velas de {par} ({tf})...'):
                h = _cargar_hist(fuente, par, tf, ak, sk)
        except Exception as e:
            err = f'{type(e).__name__}: {e}'

    escala = 1.0
    S0 = S
    if h is not None:
        S0 = float(h['Close'].iloc[-1])
        if simbolo in PROXY_GRAFICO:
            escala = S0 / S
    niveles = construir_niveles(z, niv, t_em, t_mp, escala)

    if err:
        st.error('No se pudo armar el gráfico en vivo.')
        st.code(err)
        if fuente == 'alpaca' and not ak:
            st.info('Para acciones y ETFs hace falta una cuenta gratuita de Alpaca (feed IEX en tiempo real). '
                    'Cargá las claves en el desplegable de arriba o en secrets.toml.')
    else:
        if simbolo in PROXY_GRAFICO:
            st.info(f'{simbolo} no tiene precio en vivo gratuito: se grafica **{par}** y los niveles GEX se reescalaron '
                    f'(×{escala:.4f}). Entre corchetes está el strike original del índice.')
        titulo = f'{par} · {tf}' + (' · Binance' if fuente == 'binance' else ' · Alpaca IEX')
        _render_grafico(h, fuente, par, tf, titulo, niveles, ak, sk)
        if fuente == 'alpaca':
            st.caption('ℹ️ El feed IEX gratuito refleja solo operaciones de la bolsa IEX: el precio es en tiempo real, '
                       'pero el volumen es menor al consolidado. Fuera de horario de mercado no llegan ticks.')

    # ── 3) Análisis debajo ──
    tabs = st.tabs(['🚨 Squeeze Score', '🏆 Niveles GEX', '🕯️ Lectura de velas', '🎲 Prob. de tocar niveles'])
    with tabs[0]:
        sq_auto = st.checkbox('🔔 Auto-actualizar cada 5 min y avisar al entrar en Zona de Squeeze Inminente',
                              value=False, key='gv_sq_auto')
        render_squeeze(simbolo_cboe, simbolo, n_vtos, rango_pct, r, q, mult, auto=sq_auto)
    with tabs[1]:
        render_niveles_clasificados(niv, S)
        st.markdown('**Lectura con los datos de hoy:**')
        for linea in lectura_personalizada_gex(z, S):
            st.markdown(f'- {linea}')
    with tabs[2]:
        if h is None:
            st.info('Necesita el gráfico en vivo funcionando.')
        else:
            _tab_velas(h, tf, niveles, S0)
    with tabs[3]:
        if h is None:
            st.info('Necesita el gráfico en vivo funcionando.')
        else:
            _tab_prob(fuente, par, ak, sk, niveles, S0)

    st.caption('⚠️ Los niveles asumen creadores de mercado largos calls / cortos puts y usan el interés abierto del día '
               'anterior. Son una referencia, no una señal de compra o venta ni asesoramiento financiero.')
