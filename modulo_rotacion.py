# ==============================================================
#  MÓDULO ROTACIÓN — Portfolio Rotation + Sector Rotation
#  Se integra con analizador_cuantitativo_v3.py igual que
#  modulo_bot_inversion.py: recibe los helpers/estilos ya armados
#  y el cliente de Supabase para persistir el estado semanal.
# ==============================================================

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ZONA_AR = ZoneInfo("America/Argentina/Buenos_Aires")


def _rot_ahora_ar():
    return datetime.now(ZONA_AR)


def _rot_semana_actual():
    """Etiqueta de la semana ISO actual (año-semana), usada como clave de rebalanceo.
    Todos los usuarios que corran el módulo en la misma semana calendario comparten
    la misma etiqueta, así el rebalanceo es realmente 'semanal' y no 'cada vez que tocás el botón'."""
    hoy = _rot_ahora_ar()
    y, w, _ = hoy.isocalendar()
    return f'{y}-W{w:02d}'


# ==============================================================
#  DESCARGA Y CÁLCULO DE SCORE DE MOMENTUM (semanal, ajustado por riesgo)
# ==============================================================

@st.cache_data(ttl=3600, show_spinner=False)
def _rot_descargar_precios(tickers_tuple, periodo='2y'):
    try:
        import yfinance as yf
        tickers = sorted(set(tickers_tuple))
        data = yf.download(tickers, period=periodo, interval='1d',
                            auto_adjust=True, progress=False, group_by='ticker')
        if data is None or data.empty:
            return None
        precios = pd.DataFrame()
        for tk in tickers:
            try:
                if isinstance(data.columns, pd.MultiIndex):
                    if (tk, 'Close') in data.columns:
                        s = data[(tk, 'Close')]
                    elif ('Close', tk) in data.columns:
                        s = data[('Close', tk)]
                    else:
                        continue
                else:
                    s = data['Close'] if 'Close' in data.columns else None
                    if s is None:
                        continue
                precios[tk] = s
            except Exception:
                continue
        return precios.dropna(how='all')
    except Exception:
        return None


def _rot_score_momentum(precios, tk, semanas_cortas=4, semanas_medias=12, semanas_largas=26):
    """Momentum ajustado por riesgo: combina retornos a 3 plazos (corto/medio/largo)
    y penaliza por volatilidad reciente, igual filosofía que el resto de la app
    (percentiles + retorno, no solo 'lo que más subió')."""
    try:
        s = precios[tk].dropna()
        if len(s) < semanas_largas * 5 + 10:
            return None
        ret_corto = float(s.pct_change(semanas_cortas * 5).iloc[-1])
        ret_medio = float(s.pct_change(semanas_medias * 5).iloc[-1])
        ret_largo = float(s.pct_change(semanas_largas * 5).iloc[-1])
        if any(pd.isna(x) for x in [ret_corto, ret_medio, ret_largo]):
            return None
        vol_diaria = s.pct_change().rolling(semanas_medias * 5).std().iloc[-1]
        vol_anual = float(vol_diaria) * np.sqrt(252) if pd.notna(vol_diaria) and vol_diaria > 0 else 0.20
        momentum_bruto = ret_corto * 0.20 + ret_medio * 0.35 + ret_largo * 0.45
        score_ajustado = momentum_bruto / max(vol_anual, 0.05)
        precio_actual = float(s.iloc[-1])
        return dict(
            ticker=tk, precio=precio_actual, ret_corto=ret_corto * 100, ret_medio=ret_medio * 100,
            ret_largo=ret_largo * 100, vol_anual=vol_anual * 100, score=score_ajustado,
        )
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def _rot_calcular_ranking(tickers_tuple, periodo='2y'):
    precios = _rot_descargar_precios(tickers_tuple, periodo)
    if precios is None or precios.empty:
        return pd.DataFrame(), None
    filas = []
    for tk in tickers_tuple:
        if tk not in precios.columns:
            continue
        r = _rot_score_momentum(precios, tk)
        if r:
            filas.append(r)
    if not filas:
        return pd.DataFrame(), precios
    df = pd.DataFrame(filas).sort_values('score', ascending=False).reset_index(drop=True)
    df['rank'] = df.index + 1
    # Normalizamos el score a 0-100 (percentil dentro del universo) para que
    # sea comparable visualmente con el resto de los scores de la app.
    df['score_pct'] = df['score'].rank(pct=True) * 100
    return df, precios


# ==============================================================
#  PERSISTENCIA EN SUPABASE (estado semanal, por usuario y por tipo)
# ==============================================================

def _rot_guardar_estado(supabase, user_id, tipo, semana, holdings):
    """holdings: lista de dicts {ticker, score, rank} de los activos en cartera esta semana."""
    try:
        supabase.table('rotacion_estado').upsert({
            'user_id': user_id, 'tipo': tipo, 'semana': semana,
            'holdings': holdings, 'actualizado_en': _rot_ahora_ar().isoformat(),
        }, on_conflict='user_id,tipo,semana').execute()
    except Exception:
        pass  # si falla el guardado, igual mostramos el resultado en pantalla


def _rot_leer_estado_previo(supabase, user_id, tipo, semana_actual):
    """Devuelve el último holdings guardado ANTES de la semana actual (para poder
    mostrar qué se compra/vende en el rebalanceo)."""
    try:
        res = (supabase.table('rotacion_estado')
               .select('semana, holdings, actualizado_en')
               .eq('user_id', user_id).eq('tipo', tipo)
               .neq('semana', semana_actual)
               .order('semana', desc=True).limit(1).execute())
        if res.data:
            return res.data[0]['holdings'], res.data[0]['semana']
    except Exception:
        pass
    return None, None


def _rot_leer_historial(supabase, user_id, tipo, limite=12):
    try:
        res = (supabase.table('rotacion_estado')
               .select('semana, holdings')
               .eq('user_id', user_id).eq('tipo', tipo)
               .order('semana', desc=True).limit(limite).execute())
        return res.data or []
    except Exception:
        return []


# ==============================================================
#  UI COMPARTIDA
# ==============================================================

def _rot_fig_ranking(df, top_n, titulo, C_MONSTER='#6CC24A', C_MUTED='#6b7d9a', C_GRID='#21262d',
                      C_TEXT='#e6edf3', C_BG1='#0d1117', C_BG2='#07090f'):
    colores = [C_MONSTER if i < top_n else '#f85149' if i >= len(df) - max(top_n // 2, 1) else C_MUTED
               for i in range(len(df))]
    fig = go.Figure(go.Bar(
        x=df['score_pct'], y=df['ticker'], orientation='h',
        marker_color=colores,
        text=[f"{v:.0f}" for v in df['score_pct']], textposition='outside',
        hovertemplate='%{y}<br>Score percentil: %{x:.1f}<extra></extra>',
    ))
    fig.add_vline(x=df['score_pct'].iloc[top_n - 1] if len(df) >= top_n else 50,
                  line_dash='dash', line_color=C_MONSTER, opacity=0.5)
    fig.update_layout(
        plot_bgcolor=C_BG1, paper_bgcolor=C_BG2, font=dict(color='#b0bcd0', family='Inter, sans-serif'),
        title=dict(text=titulo, font=dict(color=C_TEXT, size=14)),
        xaxis=dict(title='Score de Momentum (percentil 0-100)', range=[0, 110], gridcolor=C_GRID),
        yaxis=dict(autorange='reversed'),
        height=max(320, len(df) * 26 + 90), margin=dict(l=10, r=30, t=45, b=30),
    )
    return fig


def _rot_render_motor(
    universo_tickers, universo_nombre, tipo_clave, top_n_default, min_top_n, max_top_n,
    supabase, user_id, get_close_series=None, fmt_precio=None, score_color_hex=None,
    kpi_cards_4=None, chips_navegacion=None, PLOTLY_CONFIG=None,
):
    """Motor genérico: sirve tanto para Portfolio Rotation (muchas acciones) como
    para Sector Rotation (11 ETFs sectoriales) — cambia el universo y los N."""
    fmt_precio = fmt_precio or (lambda p: f'${p:,.2f}' if p else 'S/D')

    top_n = st.slider(
        f'Cuántos {universo_nombre.lower()} comprar cada semana (Top N)',
        min_top_n, max_top_n, top_n_default, 1, key=f'rot_topn_{tipo_clave}',
    )

    semana_actual = _rot_semana_actual()
    st.caption(f'📅 Semana de rebalanceo: **{semana_actual}** (etiqueta ISO año-semana) · '
               f'Universo: {len(universo_tickers)} {universo_nombre.lower()}')

    correr = st.button(f'▶ Calcular ranking y rebalanceo', key=f'rot_run_{tipo_clave}', type='primary')

    if not correr and not st.session_state.get(f'rot_run_flag_{tipo_clave}'):
        st.info(f'Presioná el botón para calcular el ranking de momentum de los {len(universo_tickers)} '
                f'{universo_nombre.lower()} del sistema y ver qué comprar/vender esta semana.')
        return
    if correr:
        st.session_state[f'rot_run_flag_{tipo_clave}'] = True

    with st.spinner(f'Descargando precios y calculando momentum de {len(universo_tickers)} activos...'):
        df_rank, _precios = _rot_calcular_ranking(tuple(sorted(set(universo_tickers))))

    if df_rank.empty:
        st.error('No se pudo calcular el ranking (verificá conexión a Yahoo Finance o el universo elegido).')
        return

    top_n_real = min(top_n, len(df_rank))
    cartera_nueva = df_rank.head(top_n_real).copy()
    holdings_nuevos = [
        {'ticker': r['ticker'], 'score': round(float(r['score_pct']), 2), 'rank': int(r['rank'])}
        for _, r in cartera_nueva.iterrows()
    ]

    holdings_previos, semana_previa = _rot_leer_estado_previo(supabase, user_id, tipo_clave, semana_actual)
    tickers_previos = set(h['ticker'] for h in holdings_previos) if holdings_previos else set()
    tickers_nuevos = set(h['ticker'] for h in holdings_nuevos)

    comprar = sorted(tickers_nuevos - tickers_previos)
    vender = sorted(tickers_previos - tickers_nuevos)
    mantener = sorted(tickers_nuevos & tickers_previos)

    _rot_guardar_estado(supabase, user_id, tipo_clave, semana_actual, holdings_nuevos)

    kpis = [
        (f'Cartera actual', str(top_n_real), f'de {len(df_rank)} analizados', '#6CC24A'),
        ('🟢 Comprar', str(len(comprar)), 'nuevos ingresos', '#3fb950'),
        ('🔴 Vender', str(len(vender)), 'salen del ranking', '#f85149'),
        ('⏸️ Mantener', str(len(mantener)), 'siguen en cartera', '#e3b341'),
    ]
    if kpi_cards_4:
        kpi_cards_4(kpis)
    else:
        cols = st.columns(4)
        for c, (lbl, val, sub, _color) in zip(cols, kpis):
            with c:
                st.metric(lbl, val, sub)

    if semana_previa:
        st.caption(f'📊 Comparando contra el rebalanceo de la semana {semana_previa}.')
    else:
        st.caption('📊 Este es el primer rebalanceo registrado para este universo — no hay semana previa con la cual comparar.')

    tab1, tab2, tab3 = st.tabs(['📋 Ranking completo', '🔄 Movimientos de la semana', '📈 Historial'])

    with tab1:
        st.plotly_chart(
            _rot_fig_ranking(df_rank, top_n_real, f'Ranking de Momentum — {universo_nombre}'),
            use_container_width=True, config=PLOTLY_CONFIG,
        )
        df_show = df_rank.copy()
        df_show['En cartera'] = df_show['ticker'].apply(lambda t: '✅' if t in tickers_nuevos else '')
        df_show_fmt = df_show[['rank', 'ticker', 'precio', 'ret_corto', 'ret_medio', 'ret_largo',
                                'vol_anual', 'score_pct', 'En cartera']].copy()
        df_show_fmt.columns = ['#', 'Ticker', 'Precio', 'Ret 4sem %', 'Ret 12sem %', 'Ret 26sem %',
                                'Vol Anual %', 'Score', 'En cartera']
        df_show_fmt['Precio'] = df_show_fmt['Precio'].apply(fmt_precio)
        for c in ['Ret 4sem %', 'Ret 12sem %', 'Ret 26sem %', 'Vol Anual %', 'Score']:
            df_show_fmt[c] = df_show_fmt[c].round(2)
        st.dataframe(df_show_fmt, use_container_width=True,
                     height=min(650, max(200, len(df_show_fmt) * 32 + 45)))
        if chips_navegacion:
            chips_navegacion(cartera_nueva['ticker'].tolist(), f'rot_{tipo_clave}')

    with tab2:
        if not (comprar or vender or mantener):
            st.info('No hay movimientos calculados todavía.')
        else:
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown('##### 🟢 Comprar')
                if comprar:
                    for tk in comprar:
                        fila = df_rank[df_rank['ticker'] == tk].iloc[0]
                        st.markdown(f"**{tk}** — score {fila['score_pct']:.0f} · {fmt_precio(fila['precio'])}")
                else:
                    st.caption('Sin nuevos ingresos esta semana.')
            with c2:
                st.markdown('##### 🔴 Vender')
                if vender:
                    for tk in vender:
                        st.markdown(f"**{tk}** — salió del Top {top_n_real}")
                else:
                    st.caption('Nadie salió del ranking esta semana.')
            with c3:
                st.markdown('##### ⏸️ Mantener')
                if mantener:
                    for tk in mantener:
                        fila = df_rank[df_rank['ticker'] == tk].iloc[0]
                        st.markdown(f"**{tk}** — score {fila['score_pct']:.0f}")
                else:
                    st.caption('Sin activos que se mantengan de la semana previa.')

            peso = round(100 / top_n_real, 2) if top_n_real else 0
            st.markdown(f"""
            <div style="background:#0d1117;border:1px solid #21262d;border-left:3px solid #6CC24A;
                 border-radius:8px;padding:12px 16px;margin-top:14px;font-size:13px;color:#f5f7fa">
              <b style="color:#6CC24A">Peso sugerido por posición:</b> {peso}% (equal-weight sobre {top_n_real} activos).<br>
              <span style="color:#6b7d9a;font-size:11px">Esto es un modelo cuantitativo de momentum, no asesoramiento financiero — verificá comisiones y slippage antes de operar.</span>
            </div>
            """, unsafe_allow_html=True)

    with tab3:
        historial = _rot_leer_historial(supabase, user_id, tipo_clave, limite=12)
        if not historial:
            st.info('Todavía no hay historial de rebalanceos guardado para este universo.')
        else:
            filas_hist = []
            for h in historial:
                tickers_h = ', '.join(sorted(x['ticker'] for x in h['holdings']))
                filas_hist.append({'Semana': h['semana'], 'Cantidad': len(h['holdings']), 'Tickers': tickers_h})
            df_hist = pd.DataFrame(filas_hist)
            st.dataframe(df_hist, use_container_width=True, hide_index=True,
                         height=min(400, len(df_hist) * 40 + 45))


# ==============================================================
#  ENTRY POINTS — llamar estos desde el archivo principal
# ==============================================================

def modulo_portfolio_rotation(
    acciones_por_industria, supabase, user_id,
    get_close_series=None, fmt_precio=None, score_color_hex=None,
    kpi_cards_4=None, chips_navegacion=None, PLOTLY_CONFIG=None,
):
    """Portfolio Rotation: analiza TODAS las acciones del sistema (todas las
    industrias de ACCIONES_POR_INDUSTRIA), rankea por momentum ajustado por riesgo,
    compra semanalmente el Top N y vende lo que sale del ranking."""
    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1c14 0%,#0a2818 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #6CC24A;
         border-radius:14px; padding:26px 30px; margin-bottom:22px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">📊 Portfolio Rotation</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Analiza todas las acciones del sistema (todas las industrias cargadas), calcula un score
        de momentum ajustado por riesgo (retorno a 4/12/26 semanas ponderado, dividido por
        volatilidad reciente) y cada semana compra los mejores activos del ranking y vende los peores.
      </div>
    </div>
    """, unsafe_allow_html=True)

    universo = sorted(set(t for lst in acciones_por_industria.values() for t in lst))
    _rot_render_motor(
        universo_tickers=universo, universo_nombre='Acciones', tipo_clave='portfolio',
        top_n_default=10, min_top_n=3, max_top_n=25,
        supabase=supabase, user_id=user_id, get_close_series=get_close_series,
        fmt_precio=fmt_precio, score_color_hex=score_color_hex,
        kpi_cards_4=kpi_cards_4, chips_navegacion=chips_navegacion, PLOTLY_CONFIG=PLOTLY_CONFIG,
    )


def modulo_sector_rotation(
    sectores_gics, supabase, user_id,
    get_close_series=None, fmt_precio=None, score_color_hex=None,
    kpi_cards_4=None, chips_navegacion=None, PLOTLY_CONFIG=None,
):
    """Sector Rotation: en vez de elegir acciones individuales, rota entre los
    11 sectores GICS (ETFs SPDR: XLK, XLV, XLF, etc.) — mismo motor de momentum,
    pero aplicado a un universo mucho más chico y menos ruidoso."""
    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1420 0%,#0a1c30 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #3a7bd5;
         border-radius:14px; padding:26px 30px; margin-bottom:22px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">🔄 Sector Rotation</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        En vez de elegir acciones individuales, rota entre los 11 sectores GICS del S&amp;P500
        (ETFs SPDR: Tecnología, Salud, Finanzas, Energía, etc.). Mismo motor de momentum
        ajustado por riesgo, aplicado a un universo más chico y menos ruidoso que Portfolio Rotation.
      </div>
    </div>
    """, unsafe_allow_html=True)

    universo = sorted(set(tk for tk, _color in sectores_gics.values()))
    _rot_render_motor(
        universo_tickers=universo, universo_nombre='Sectores', tipo_clave='sector',
        top_n_default=3, min_top_n=1, max_top_n=6,
        supabase=supabase, user_id=user_id, get_close_series=get_close_series,
        fmt_precio=fmt_precio, score_color_hex=score_color_hex,
        kpi_cards_4=kpi_cards_4, chips_navegacion=chips_navegacion, PLOTLY_CONFIG=PLOTLY_CONFIG,
    )
