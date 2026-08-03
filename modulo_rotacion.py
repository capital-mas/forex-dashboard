# ==============================================================
#  MÓDULO ROTACIÓN — Portfolio Rotation + Sector Rotation
#  v2: scoring multi-factor (momentum + tendencia + fuerza relativa
#  + salud de RSI + volatilidad) con explicación en texto de por qué
#  cada activo entra/sale, y clasificación de fase para sectores
#  (Liderando / Emergiendo / Perdiendo potencial / Rezagado).
# ==============================================================

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from datetime import datetime
from zoneinfo import ZoneInfo

ZONA_AR = ZoneInfo("America/Argentina/Buenos_Aires")
BENCHMARK_DEFAULT = 'SPY'


def _rot_ahora_ar():
    return datetime.now(ZONA_AR)


def _rot_semana_actual():
    """Etiqueta de la semana ISO actual (año-semana). Todos los usuarios que corran
    el módulo en la misma semana calendario comparten la misma etiqueta, así el
    rebalanceo es 'semanal' de verdad y no 'cada vez que tocás el botón'."""
    hoy = _rot_ahora_ar()
    y, w, _ = hoy.isocalendar()
    return f'{y}-W{w:02d}'


# ==============================================================
#  DESCARGA DE PRECIOS
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


# ==============================================================
#  INDICADORES DE APOYO (tendencia, RSI) — mismo criterio que el
#  resto de la app (Golden Cross, MACD, RSI 14)
# ==============================================================

def _rot_rsi(serie, periodo=14):
    delta = serie.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / periodo, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / periodo, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def _rot_macd_bull(serie):
    macd = serie.ewm(span=12, adjust=False).mean() - serie.ewm(span=26, adjust=False).mean()
    señal = macd.ewm(span=9, adjust=False).mean()
    try:
        return bool(float(macd.iloc[-1]) > float(señal.iloc[-1]))
    except Exception:
        return None


def _rot_golden_cross(serie):
    if len(serie) < 200:
        return None
    ma50 = serie.rolling(50).mean()
    ma200 = serie.rolling(200).mean()
    try:
        return bool(float(ma50.iloc[-1]) > float(ma200.iloc[-1]))
    except Exception:
        return None


# ==============================================================
#  ANÁLISIS POR ACTIVO — momentum + tendencia + RSI + fuerza relativa
# ==============================================================

def _rot_analizar_activo(precios, tk, ret_bench_medio=None):
    try:
        s = precios[tk].dropna()
        if len(s) < 30 * 5 + 10:  # ~30 semanas mínimo de historia
            return None

        semanas_cortas, semanas_medias, semanas_largas = 4, 12, 26
        ret_corto = float(s.pct_change(semanas_cortas * 5).iloc[-1])
        ret_medio = float(s.pct_change(semanas_medias * 5).iloc[-1])
        ret_largo = float(s.pct_change(semanas_largas * 5).iloc[-1]) if len(s) >= semanas_largas * 5 + 5 else None
        if any(pd.isna(x) for x in [ret_corto, ret_medio] + ([ret_largo] if ret_largo is not None else [])):
            return None
        if ret_largo is None:
            ret_largo = ret_medio  # fallback si aún no hay 26 semanas de historia

        vol_diaria = s.pct_change().rolling(semanas_medias * 5).std().iloc[-1]
        vol_anual = float(vol_diaria) * np.sqrt(252) if pd.notna(vol_diaria) and vol_diaria > 0 else 0.20

        rsi = float(_rot_rsi(s).iloc[-1])
        macd_bull = _rot_macd_bull(s)
        golden_cross = _rot_golden_cross(s)

        momentum_bruto = ret_corto * 0.20 + ret_medio * 0.35 + ret_largo * 0.45
        score_momentum = momentum_bruto / max(vol_anual, 0.05)

        alpha_medio = (ret_medio - ret_bench_medio) if ret_bench_medio is not None else None

        return dict(
            ticker=tk, precio=float(s.iloc[-1]),
            ret_corto=ret_corto * 100, ret_medio=ret_medio * 100, ret_largo=ret_largo * 100,
            vol_anual=vol_anual * 100, rsi=rsi, macd_bull=macd_bull, golden_cross=golden_cross,
            alpha_medio=(alpha_medio * 100 if alpha_medio is not None else None),
            score_momentum=score_momentum,
        )
    except Exception:
        return None


def _rot_score_tendencia(golden_cross, macd_bull):
    if golden_cross is True and macd_bull is True:
        return 100
    if golden_cross is None and macd_bull is None:
        return 50
    votos = [v for v in [golden_cross, macd_bull] if v is not None]
    if not votos:
        return 50
    return 100 * (sum(1 for v in votos if v) / len(votos))


def _rot_score_rsi_salud(rsi):
    """Zona ideal ~45-65 (momentum saludable sin excesos). Penaliza tanto la
    sobrecompra extrema (riesgo de reversión / toma de ganancias) como la
    debilidad (RSI bajo, sin presión compradora)."""
    return max(0.0, 100 - abs(rsi - 55) * 2.4)


@st.cache_data(ttl=3600, show_spinner=False)
def _rot_calcular_ranking(tickers_tuple, benchmark=BENCHMARK_DEFAULT, periodo='2y'):
    universo = tuple(sorted(set(tickers_tuple) | {benchmark}))
    precios = _rot_descargar_precios(universo, periodo)
    if precios is None or precios.empty or benchmark not in precios.columns:
        return pd.DataFrame(), precios

    s_bench = precios[benchmark].dropna()
    ret_bench_medio = float(s_bench.pct_change(60).iloc[-1]) if len(s_bench) >= 65 else None

    filas = []
    for tk in tickers_tuple:
        if tk == benchmark or tk not in precios.columns:
            continue
        r = _rot_analizar_activo(precios, tk, ret_bench_medio)
        if r:
            filas.append(r)
    if not filas:
        return pd.DataFrame(), precios

    df = pd.DataFrame(filas)

    # ── Percentiles de cada condición dentro del universo analizado ──────
    df['perc_momentum'] = df['score_momentum'].rank(pct=True) * 100
    df['perc_riesgo'] = (1 / df['vol_anual'].clip(lower=0.5)).rank(pct=True) * 100
    df['perc_tendencia'] = df.apply(lambda r: _rot_score_tendencia(r['golden_cross'], r['macd_bull']), axis=1)
    df['perc_rsi_salud'] = df['rsi'].apply(_rot_score_rsi_salud)
    if df['alpha_medio'].notna().any():
        df['perc_fuerza_relativa'] = df['alpha_medio'].rank(pct=True) * 100
    else:
        df['perc_fuerza_relativa'] = 50.0

    # ── Score compuesto de calidad — pondera las 5 condiciones ────────────
    df['score_pct'] = (
        df['perc_momentum'] * 0.40 +
        df['perc_tendencia'] * 0.20 +
        df['perc_fuerza_relativa'] * 0.20 +
        df['perc_rsi_salud'] * 0.10 +
        df['perc_riesgo'] * 0.10
    ).round(1)

    df = df.sort_values('score_pct', ascending=False).reset_index(drop=True)
    df['rank'] = df.index + 1
    return df, precios


# ==============================================================
#  NARRATIVA — por qué entra/sale cada activo
# ==============================================================

def _rot_razones(row):
    pos, alerta = [], []

    if row['perc_momentum'] >= 65:
        pos.append(f"Momentum fuerte: {row['ret_medio']:+.1f}% en 12 semanas (percentil {row['perc_momentum']:.0f})")
    elif row['perc_momentum'] <= 35:
        alerta.append(f"Momentum débil: {row['ret_medio']:+.1f}% en 12 semanas (percentil {row['perc_momentum']:.0f})")

    if row['golden_cross'] is True:
        pos.append('Tendencia de fondo alcista (MA50 > MA200)')
    elif row['golden_cross'] is False:
        alerta.append('Sin confirmación de tendencia de largo plazo (MA50 < MA200)')

    if row['macd_bull'] is True:
        pos.append('MACD en fase alcista')
    elif row['macd_bull'] is False:
        alerta.append('MACD en fase bajista')

    if row['alpha_medio'] is not None:
        if row['alpha_medio'] > 0:
            pos.append(f"Le gana al benchmark por {row['alpha_medio']:+.1f} pp en 12 semanas")
        else:
            alerta.append(f"Rinde por debajo del benchmark ({row['alpha_medio']:+.1f} pp en 12 semanas)")

    if row['rsi'] >= 75:
        alerta.append(f"RSI en {row['rsi']:.0f}: sobrecompra, riesgo de toma de ganancias")
    elif row['rsi'] <= 30:
        alerta.append(f"RSI en {row['rsi']:.0f}: débil, sin presión compradora")
    else:
        pos.append(f"RSI saludable en {row['rsi']:.0f}, sin excesos")

    if row['perc_riesgo'] >= 60:
        pos.append(f"Volatilidad controlada ({row['vol_anual']:.1f}% anual)")
    elif row['perc_riesgo'] <= 35:
        alerta.append(f"Volatilidad elevada ({row['vol_anual']:.1f}% anual)")

    return pos, alerta


def _rot_clasificar_fase(score_pct, delta):
    """Clasifica el activo en una fase de ciclo, comparando el score de esta
    semana contra el de la semana anterior (si hay historial)."""
    if delta is None:
        return '🆕 Primer registro', '#8b949e', 'Todavía no hay una semana previa registrada para comparar la tendencia del score.'
    if score_pct >= 60 and delta >= 2:
        return '🟢 Liderando y acelerando', '#3fb950', 'Está entre los mejores del universo y su score sigue subiendo semana a semana.'
    if score_pct >= 60 and delta < 2:
        return '🟠 Liderando pero perdiendo fuerza', '#f0883e', 'Sigue entre los mejores, pero el score dejó de acelerar — puede ser el comienzo de un techo.'
    if score_pct < 40 and delta >= 5:
        return '🟡 Emergiendo (rezagado que mejora)', '#e3b341', 'Todavía está débil en el ranking general, pero viene mejorando rápido semana a semana.'
    if score_pct < 40:
        return '🔴 Rezagado', '#f85149', 'Score bajo y sin señales claras de mejora respecto a la semana anterior.'
    return '⚪ Neutral / en transición', '#6b7d9a', 'Zona media del ranking, sin una tendencia clara de mejora ni de deterioro.'


# ==============================================================
#  PERSISTENCIA EN SUPABASE — ranking completo por semana
#  (no solo el Top N, así se puede clasificar TODO el universo,
#  no solo lo que está en cartera)
# ==============================================================

def _rot_guardar_estado(supabase, user_id, tipo, semana, ranking_completo, top_n):
    try:
        supabase.table('rotacion_estado').upsert({
            'user_id': user_id, 'tipo': tipo, 'semana': semana,
            'ranking': ranking_completo, 'top_n': top_n,
            'actualizado_en': _rot_ahora_ar().isoformat(),
        }, on_conflict='user_id,tipo,semana').execute()
    except Exception:
        pass


def _rot_leer_ranking_previo(supabase, user_id, tipo, semana_actual):
    try:
        res = (supabase.table('rotacion_estado')
               .select('semana, ranking')
               .eq('user_id', user_id).eq('tipo', tipo)
               .neq('semana', semana_actual)
               .order('semana', desc=True).limit(1).execute())
        if res.data:
            ranking_prev = {x['ticker']: x['score_pct'] for x in res.data[0]['ranking']}
            return ranking_prev, res.data[0]['semana']
    except Exception:
        pass
    return {}, None


def _rot_leer_historial(supabase, user_id, tipo, limite=12):
    try:
        res = (supabase.table('rotacion_estado')
               .select('semana, ranking, top_n')
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
        hovertemplate='%{y}<br>Score compuesto: %{x:.1f}<extra></extra>',
    ))
    fig.add_vline(x=df['score_pct'].iloc[top_n - 1] if len(df) >= top_n else 50,
                  line_dash='dash', line_color=C_MONSTER, opacity=0.5)
    fig.update_layout(
        plot_bgcolor=C_BG1, paper_bgcolor=C_BG2, font=dict(color='#b0bcd0', family='Inter, sans-serif'),
        title=dict(text=titulo, font=dict(color=C_TEXT, size=14)),
        xaxis=dict(title='Score compuesto (momentum + tendencia + fuerza relativa + RSI + riesgo)',
                   range=[0, 110], gridcolor=C_GRID),
        yaxis=dict(autorange='reversed'),
        height=max(320, len(df) * 26 + 90), margin=dict(l=10, r=30, t=45, b=30),
    )
    return fig


def _rot_tarjeta_activo(row, delta, mostrar_clasificacion=True):
    clasif, color_clasif, texto_clasif = _rot_clasificar_fase(row['score_pct'], delta)
    pos, alerta = _rot_razones(row)
    delta_txt = f"{delta:+.1f} pts vs. semana anterior" if delta is not None else 'sin historial previo'

    bloque_clasif = ''
    if mostrar_clasificacion:
        bloque_clasif = (
            f'<div style="margin-bottom:8px">'
            f'<span style="padding:3px 10px;border-radius:20px;font-size:10px;font-weight:700;'
            f'background:{color_clasif}22;border:1px solid {color_clasif};color:{color_clasif}">{clasif}</span>'
            f'<span style="color:#6b7d9a;font-size:11px;margin-left:8px">{delta_txt}</span>'
            f'</div>'
            f'<div style="font-size:11px;color:#8b949e;margin-bottom:8px">{texto_clasif}</div>'
        )

    lineas_pos = ''.join(f'<div style="font-size:11px;color:#3fb950;padding:2px 0">✅ {m}</div>' for m in pos)
    lineas_alt = ''.join(f'<div style="font-size:11px;color:#f85149;padding:2px 0">⚠️ {m}</div>' for m in alerta)

    st.markdown(f"""
    <div style="background:#0d1117;border:1px solid #21262d;border-left:3px solid #6CC24A;
         border-radius:8px;padding:14px 18px;margin-bottom:10px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;flex-wrap:wrap">
        <span style="color:#e6edf3;font-size:14px;font-weight:700;font-family:'JetBrains Mono',monospace">{row['ticker']}</span>
        <span style="color:#6CC24A;font-size:13px;font-weight:700">Score {row['score_pct']:.0f}/100</span>
        <span style="color:#6b7d9a;font-size:11px">#{int(row['rank'])} del ranking</span>
      </div>
      {bloque_clasif}
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:2px 16px">
        {lineas_pos}{lineas_alt}
      </div>
    </div>
    """, unsafe_allow_html=True)


def _rot_render_motor(
    universo_tickers, universo_nombre, tipo_clave, top_n_default, min_top_n, max_top_n,
    supabase, user_id, fmt_precio=None, kpi_cards_4=None, chips_navegacion=None, PLOTLY_CONFIG=None,
    benchmark=BENCHMARK_DEFAULT, mostrar_panel_fases=False,
):
    fmt_precio = fmt_precio or (lambda p: f'${p:,.2f}' if p else 'S/D')

    top_n = st.slider(
        f'Cuántos {universo_nombre.lower()} comprar cada semana (Top N)',
        min_top_n, max_top_n, top_n_default, 1, key=f'rot_topn_{tipo_clave}',
    )

    semana_actual = _rot_semana_actual()
    st.caption(f'📅 Semana de rebalanceo: **{semana_actual}** · Universo: {len(universo_tickers)} '
               f'{universo_nombre.lower()} · Benchmark de referencia: **{benchmark}**')

    correr = st.button('▶ Calcular ranking y rebalanceo', key=f'rot_run_{tipo_clave}', type='primary')

    if not correr and not st.session_state.get(f'rot_run_flag_{tipo_clave}'):
        st.info(f'Presioná el botón para calcular el ranking multi-factor (momentum, tendencia, fuerza '
                f'relativa vs. {benchmark}, RSI y volatilidad) de los {len(universo_tickers)} '
                f'{universo_nombre.lower()} del sistema.')
        return
    if correr:
        st.session_state[f'rot_run_flag_{tipo_clave}'] = True

    with st.spinner(f'Descargando precios y calculando el score multi-factor de {len(universo_tickers)} activos...'):
        df_rank, _precios = _rot_calcular_ranking(tuple(sorted(set(universo_tickers))), benchmark=benchmark)

    if df_rank.empty:
        st.error('No se pudo calcular el ranking (verificá conexión a Yahoo Finance, el universo elegido, '
                 'o si hay suficiente historial — se necesitan al menos ~30 semanas de precios).')
        return

    top_n_real = min(top_n, len(df_rank))
    cartera_nueva = df_rank.head(top_n_real).copy()

    ranking_completo = [
        {'ticker': r['ticker'], 'score_pct': round(float(r['score_pct']), 2), 'rank': int(r['rank'])}
        for _, r in df_rank.iterrows()
    ]
    ranking_previo, semana_previa = _rot_leer_ranking_previo(supabase, user_id, tipo_clave, semana_actual)

    tickers_previos_topn = set()
    if ranking_previo:
        ordenado_prev = sorted(ranking_previo.items(), key=lambda x: x[1], reverse=True)
        tickers_previos_topn = set(tk for tk, _sc in ordenado_prev[:top_n_real])

    tickers_nuevos = set(cartera_nueva['ticker'].tolist())
    comprar = sorted(tickers_nuevos - tickers_previos_topn)
    vender = sorted(tickers_previos_topn - tickers_nuevos)
    mantener = sorted(tickers_nuevos & tickers_previos_topn)

    _rot_guardar_estado(supabase, user_id, tipo_clave, semana_actual, ranking_completo, top_n_real)

    kpis = [
        ('Cartera actual', str(top_n_real), f'de {len(df_rank)} analizados', '#6CC24A'),
        ('🟢 Comprar', str(len(comprar)), 'nuevos ingresos', '#3fb950'),
        ('🔴 Vender', str(len(vender)), 'salen del Top', '#f85149'),
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
        st.caption('📊 Primer rebalanceo registrado para este universo — todavía no hay semana previa para comparar tendencia.')

    tabs_labels = ['🧾 Por qué se elige cada activo', '📋 Ranking completo', '📈 Historial']
    if mostrar_panel_fases:
        tabs_labels.insert(1, '🗺️ Mapa de fases (liderando/rezagado)')
    tabs = st.tabs(tabs_labels)
    tab_razones = tabs[0]
    tab_fases = tabs[1] if mostrar_panel_fases else None
    tab_ranking = tabs[2] if mostrar_panel_fases else tabs[1]
    tab_hist = tabs[3] if mostrar_panel_fases else tabs[2]

    # ── TAB: por qué se elige cada activo ────────────────────────────────
    with tab_razones:
        if comprar:
            st.markdown('#### 🟢 Entran a la cartera esta semana')
            for tk in comprar:
                fila = df_rank[df_rank['ticker'] == tk].iloc[0]
                delta = (fila['score_pct'] - ranking_previo[tk]) if tk in ranking_previo else None
                _rot_tarjeta_activo(fila, delta)
        if mantener:
            with st.expander(f'⏸️ Se mantienen en cartera ({len(mantener)})', expanded=False):
                for tk in mantener:
                    fila = df_rank[df_rank['ticker'] == tk].iloc[0]
                    delta = (fila['score_pct'] - ranking_previo[tk]) if tk in ranking_previo else None
                    _rot_tarjeta_activo(fila, delta)
        if vender:
            st.markdown('#### 🔴 Salen de la cartera esta semana')
            for tk in vender:
                fila_prev_score = ranking_previo.get(tk)
                fila_actual = df_rank[df_rank['ticker'] == tk]
                if not fila_actual.empty:
                    fila = fila_actual.iloc[0]
                    delta = (fila['score_pct'] - fila_prev_score) if fila_prev_score is not None else None
                    _rot_tarjeta_activo(fila, delta)
                else:
                    st.markdown(f"**{tk}** — ya no aparece en el universo analizado esta semana (sin datos suficientes).")
        if not (comprar or vender or mantener):
            st.info('No hay movimientos calculados todavía.')

        peso = round(100 / top_n_real, 2) if top_n_real else 0
        st.markdown(f"""
        <div style="background:#0d1117;border:1px solid #21262d;border-left:3px solid #6CC24A;
             border-radius:8px;padding:12px 16px;margin-top:6px;font-size:13px;color:#f5f7fa">
          <b style="color:#6CC24A">Peso sugerido por posición:</b> {peso}% (equal-weight sobre {top_n_real} activos).<br>
          <span style="color:#6b7d9a;font-size:11px">Modelo cuantitativo de momentum multi-factor, no asesoramiento financiero — verificá comisiones y slippage antes de operar.</span>
        </div>
        """, unsafe_allow_html=True)

    # ── TAB: mapa de fases (solo Sector Rotation) ────────────────────────
    if mostrar_panel_fases and tab_fases is not None:
        with tab_fases:
            st.caption('Clasificación de TODOS los activos del universo (no solo los que están en cartera), '
                       'comparando el score de esta semana contra el de la semana anterior.')
            filas_fase = []
            for _, r in df_rank.iterrows():
                delta = (r['score_pct'] - ranking_previo[r['ticker']]) if r['ticker'] in ranking_previo else None
                clasif, color, texto = _rot_clasificar_fase(r['score_pct'], delta)
                filas_fase.append({
                    'orden': {'🟢': 0, '🟠': 1, '🟡': 2, '⚪': 3, '🔴': 4, '🆕': 5}.get(clasif[0], 6),
                    'ticker': r['ticker'], 'clasificacion': clasif, 'color': color, 'texto': texto,
                    'score_pct': r['score_pct'], 'delta': delta,
                })
            df_fase = pd.DataFrame(filas_fase).sort_values(['orden', 'score_pct'], ascending=[True, False])

            for clasif_val in df_fase['clasificacion'].unique():
                grupo = df_fase[df_fase['clasificacion'] == clasif_val]
                color_g = grupo.iloc[0]['color']
                texto_g = grupo.iloc[0]['texto']
                st.markdown(f"""
                <div style="margin:14px 0 6px 0">
                  <span style="padding:4px 12px;border-radius:20px;font-size:12px;font-weight:700;
                    background:{color_g}22;border:1px solid {color_g};color:{color_g}">{clasif_val}</span>
                  <span style="color:#6b7d9a;font-size:11px;margin-left:8px">{texto_g}</span>
                </div>
                """, unsafe_allow_html=True)
                chips = ''.join(
                    f'<span style="display:inline-block;background:#0d1117;border:1px solid #21262d;'
                    f'border-radius:6px;padding:4px 10px;margin:3px 6px 3px 0;font-size:11px;color:#e6edf3;'
                    f'font-family:JetBrains Mono,monospace">{row["ticker"]} · {row["score_pct"]:.0f}'
                    f'{f" ({row["delta"]:+.1f})" if row["delta"] is not None else ""}</span>'
                    for _, row in grupo.iterrows()
                )
                st.markdown(f'<div>{chips}</div>', unsafe_allow_html=True)

    # ── TAB: ranking completo ────────────────────────────────────────────
    with tab_ranking:
        st.plotly_chart(
            _rot_fig_ranking(df_rank, top_n_real, f'Ranking de calidad — {universo_nombre}'),
            use_container_width=True, config=PLOTLY_CONFIG,
        )
        df_show = df_rank.copy()
        df_show['En cartera'] = df_show['ticker'].apply(lambda t: '✅' if t in tickers_nuevos else '')
        df_show['Tendencia'] = df_show.apply(
            lambda r: ('✅✅' if (r['golden_cross'] and r['macd_bull'])
                       else '✅' if (r['golden_cross'] or r['macd_bull']) else '—'), axis=1)
        cols_mostrar = ['rank', 'ticker', 'precio', 'ret_corto', 'ret_medio', 'ret_largo',
                        'vol_anual', 'rsi', 'Tendencia', 'alpha_medio', 'score_pct', 'En cartera']
        df_show_fmt = df_show[cols_mostrar].copy()
        df_show_fmt.columns = ['#', 'Ticker', 'Precio', 'Ret 4sem %', 'Ret 12sem %', 'Ret 26sem %',
                                'Vol Anual %', 'RSI', 'Tendencia', f'Alpha vs {benchmark} pp', 'Score', 'En cartera']
        df_show_fmt['Precio'] = df_show_fmt['Precio'].apply(fmt_precio)
        for c in ['Ret 4sem %', 'Ret 12sem %', 'Ret 26sem %', 'Vol Anual %', 'RSI', f'Alpha vs {benchmark} pp', 'Score']:
            df_show_fmt[c] = df_show_fmt[c].round(2)
        st.dataframe(df_show_fmt, use_container_width=True,
                     height=min(650, max(200, len(df_show_fmt) * 32 + 45)))
        st.caption('Score = 40% Momentum + 20% Tendencia (Golden Cross/MACD) + 20% Fuerza relativa vs. '
                   f'{benchmark} + 10% Salud del RSI + 10% Control de volatilidad — todo expresado en percentil (0-100) dentro del universo.')
        if chips_navegacion:
            chips_navegacion(cartera_nueva['ticker'].tolist(), f'rot_{tipo_clave}')

    # ── TAB: historial ────────────────────────────────────────────────────
    with tab_hist:
        historial = _rot_leer_historial(supabase, user_id, tipo_clave, limite=12)
        if not historial:
            st.info('Todavía no hay historial de rebalanceos guardado para este universo.')
        else:
            filas_hist = []
            for h in historial:
                tn = h.get('top_n') or 10
                ordenado = sorted(h['ranking'], key=lambda x: x['score_pct'], reverse=True)[:tn]
                tickers_h = ', '.join(x['ticker'] for x in ordenado)
                filas_hist.append({'Semana': h['semana'], 'Top N': tn, 'Cartera': tickers_h})
            df_hist = pd.DataFrame(filas_hist)
            st.dataframe(df_hist, use_container_width=True, hide_index=True,
                         height=min(400, len(df_hist) * 40 + 45))


# ==============================================================
#  ENTRY POINTS — llamar estos desde el archivo principal
# ==============================================================

def modulo_portfolio_rotation(
    acciones_por_industria, supabase, user_id,
    fmt_precio=None, kpi_cards_4=None, chips_navegacion=None, PLOTLY_CONFIG=None,
    benchmark=BENCHMARK_DEFAULT,
):
    """Portfolio Rotation: analiza TODAS las acciones del sistema (todas las
    industrias de ACCIONES_POR_INDUSTRIA). Cada activo se evalúa con 5
    condiciones (momentum multi-plazo, tendencia Golden Cross/MACD, fuerza
    relativa vs. benchmark, salud del RSI y control de volatilidad) y el
    módulo explica en texto por qué cada uno entra, se mantiene o sale."""
    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1c14 0%,#0a2818 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #6CC24A;
         border-radius:14px; padding:26px 30px; margin-bottom:22px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">📊 Portfolio Rotation</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Analiza todas las acciones del sistema y arma un score de calidad con 5 condiciones:
        <b style="color:#e6edf3">momentum multi-plazo</b> (4/12/26 semanas), <b style="color:#e6edf3">tendencia</b>
        (Golden Cross + MACD), <b style="color:#e6edf3">fuerza relativa</b> vs. benchmark, <b style="color:#e6edf3">salud del RSI</b>
        y <b style="color:#e6edf3">control de volatilidad</b>. Cada semana explica en texto por qué compra, mantiene o vende cada activo.
      </div>
    </div>
    """, unsafe_allow_html=True)

    universo = sorted(set(t for lst in acciones_por_industria.values() for t in lst))
    _rot_render_motor(
        universo_tickers=universo, universo_nombre='Acciones', tipo_clave='portfolio',
        top_n_default=10, min_top_n=3, max_top_n=25,
        supabase=supabase, user_id=user_id, fmt_precio=fmt_precio,
        kpi_cards_4=kpi_cards_4, chips_navegacion=chips_navegacion, PLOTLY_CONFIG=PLOTLY_CONFIG,
        benchmark=benchmark, mostrar_panel_fases=False,
    )


def modulo_sector_rotation(
    sectores_gics, supabase, user_id,
    fmt_precio=None, kpi_cards_4=None, chips_navegacion=None, PLOTLY_CONFIG=None,
    benchmark=BENCHMARK_DEFAULT,
):
    """Sector Rotation: rota entre los 11 sectores GICS (ETFs SPDR). Mismo
    motor de 5 condiciones que Portfolio Rotation, más un mapa de fases que
    clasifica TODOS los sectores (no solo los que están en cartera) en
    Liderando / Emergiendo / Perdiendo potencial / Rezagado, comparando el
    score de esta semana contra el de la semana anterior."""
    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1420 0%,#0a1c30 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #3a7bd5;
         border-radius:14px; padding:26px 30px; margin-bottom:22px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">🔄 Sector Rotation</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        En vez de elegir acciones individuales, rota entre los 11 sectores GICS del S&amp;P500.
        Además del ranking, clasifica cada sector en su <b style="color:#e6edf3">fase de ciclo</b>:
        🟢 liderando y acelerando, 🟠 liderando pero perdiendo fuerza, 🟡 emergiendo, 🔴 rezagado — comparando
        el score de esta semana contra el de la semana anterior.
      </div>
    </div>
    """, unsafe_allow_html=True)

    universo = sorted(set(tk for tk, _color in sectores_gics.values()))
    _rot_render_motor(
        universo_tickers=universo, universo_nombre='Sectores', tipo_clave='sector',
        top_n_default=3, min_top_n=1, max_top_n=6,
        supabase=supabase, user_id=user_id, fmt_precio=fmt_precio,
        kpi_cards_4=kpi_cards_4, chips_navegacion=chips_navegacion, PLOTLY_CONFIG=PLOTLY_CONFIG,
        benchmark=benchmark, mostrar_panel_fases=True,
    )
