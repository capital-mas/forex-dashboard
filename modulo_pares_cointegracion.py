"""
Módulo Streamlit — Scanner de Pares por Cointegración (Engle-Granger / Johansen)
Wrapea engine.cointegration_engine con UI, reutilizando helpers de app.py
(pasados como parámetros, igual que modulo_rotacion.py).
"""

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from itertools import combinations
from concurrent.futures import ThreadPoolExecutor, as_completed

from engine.cointegration_engine import (
    analyze_pair,
    scan_universe,
    calculate_spread,
    calculate_zscore,
    generate_signals,
    compute_strategy_returns,
    adf_test,
    johansen_test,
    hurst_exponent,
)


def _fig_spread_zscore(nombre_a, nombre_b, spread, zscore, entry_z, exit_z, palette):
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
        row_heights=[0.6, 0.4],
        subplot_titles=(f'Spread {nombre_a} - β·{nombre_b}', 'Z-Score del spread'),
    )
    fig.add_trace(go.Scatter(x=spread.index, y=spread, line=dict(color=palette['acent'], width=1.6),
                              name='Spread'), row=1, col=1)
    fig.add_hline(y=0, line_color=palette['muted'], opacity=0.4, row=1, col=1)

    fig.add_trace(go.Scatter(x=zscore.index, y=zscore, line=dict(color=palette['monster'], width=1.4),
                              name='Z-Score'), row=2, col=1)
    fig.add_hline(y=entry_z, line_dash='dash', line_color=palette['red'], opacity=0.6, row=2, col=1)
    fig.add_hline(y=-entry_z, line_dash='dash', line_color=palette['green'], opacity=0.6, row=2, col=1)
    fig.add_hline(y=exit_z, line_dash='dot', line_color=palette['yell'], opacity=0.4, row=2, col=1)
    fig.add_hline(y=-exit_z, line_dash='dot', line_color=palette['yell'], opacity=0.4, row=2, col=1)
    fig.add_hline(y=0, line_color=palette['muted'], opacity=0.4, row=2, col=1)

    fig.update_yaxes(gridcolor=palette['grid'], row=1, col=1)
    fig.update_yaxes(gridcolor=palette['grid'], row=2, col=1)
    fig.update_xaxes(gridcolor=palette['grid'])
    fig.update_layout(
        plot_bgcolor=palette['bg1'], paper_bgcolor=palette['bg2'],
        font=dict(color='#b0bcd0', family='Inter, sans-serif'), dragmode=False,
        height=520, hovermode='x unified',
        legend=dict(orientation='h', y=1.08, font=dict(size=9)),
        margin=dict(l=10, r=10, t=45, b=10),
    )
    fig.update_annotations(font=dict(color=palette['text'], size=12))
    return fig


def _fig_equity_backtest(strat_ret, palette, ticker_a, ticker_b):
    equity = (1 + strat_ret).cumprod()
    dd = equity / equity.cummax() - 1
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                         row_heights=[0.65, 0.35],
                         subplot_titles=(f'Equity — Long/Short {ticker_a}/{ticker_b}', 'Drawdown'))
    fig.add_trace(go.Scatter(x=equity.index, y=equity, line=dict(color=palette['monster'], width=2),
                              name='Equity (base 1.0)'), row=1, col=1)
    fig.add_trace(go.Scatter(x=dd.index, y=dd * 100, fill='tozeroy', line=dict(color=palette['red'], width=1.2),
                              fillcolor='rgba(248,81,73,0.3)', name='Drawdown %'), row=2, col=1)
    fig.update_yaxes(gridcolor=palette['grid'], row=1, col=1)
    fig.update_yaxes(gridcolor=palette['grid'], title='%', row=2, col=1)
    fig.update_xaxes(gridcolor=palette['grid'])
    fig.update_layout(
        plot_bgcolor=palette['bg1'], paper_bgcolor=palette['bg2'],
        font=dict(color='#b0bcd0', family='Inter, sans-serif'), dragmode=False,
        height=460, hovermode='x unified', margin=dict(l=10, r=10, t=45, b=10),
    )
    fig.update_annotations(font=dict(color=palette['text'], size=12))
    return fig, equity, dd


def _metricas_backtest(strat_ret):
    ret = strat_ret.dropna()
    if len(ret) < 20 or ret.std() == 0:
        return None
    equity = (1 + ret).cumprod()
    anios = len(ret) / 252
    cagr = equity.iloc[-1] ** (1 / anios) - 1 if anios > 0 else np.nan
    vol = ret.std() * np.sqrt(252)
    sharpe = cagr / vol if vol != 0 else np.nan
    dd = (equity / equity.cummax() - 1).min()
    win_rate = (ret[ret != 0] > 0).mean() if (ret != 0).any() else np.nan
    return dict(cagr=cagr, vol=vol, sharpe=sharpe, max_dd=dd, win_rate=win_rate,
                capital_final=float(equity.iloc[-1]))


def modulo_pares_cointegracion(
    descargar_datos, get_close_series, fmt_precio, kpi_cards_4,
    chips_navegacion, PLOTLY_CONFIG, selector_ticker_autocomplete,
):
    """Scanner de pares vía cointegración Engle-Granger/Johansen — motor propio
    en engine/cointegration_engine.py (testeado con pytest), separado del
    scanner simple de ratio+Z-score que ya tenés en 'Pares (Mean Reversion)'."""

    palette = dict(
        acent='#3a7bd5', monster='#6CC24A', text='#e6edf3', muted='#6b7d9a',
        green='#3fb950', red='#f85149', yell='#e3b341', grid='#21262d',
        bg1='#0d1117', bg2='#07090f',
    )

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1c20 0%,#0a2530 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #bc8cff;
         border-radius:14px; padding:28px 32px; margin-bottom:24px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">
        📐 Statistical Arbitrage — Cointegración
      </div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Test de Engle-Granger (y Johansen para 3+ activos), hedge ratio por OLS, half-life de
        reversión (Ornstein-Uhlenbeck), exponente de Hurst y backtest simplificado del spread.
        Motor separado y testeado (<code>engine/cointegration_engine.py</code>), distinto del
        scanner rápido de ratio+Z-score de la otra pestaña.
      </div>
    </div>
    """, unsafe_allow_html=True)

    tab_par, tab_universo = st.tabs(['🔎 Par puntual', '🌐 Escaneo de universo'])

    # ══════════════════════════════════════════════════════════════
    #  TAB 1 — Par puntual: cointegración + backtest completo
    # ══════════════════════════════════════════════════════════════
    with tab_par:
        c1, c2, c3 = st.columns(3)
        with c1:
            ticker_a = selector_ticker_autocomplete('coint_a', label='Activo A')
        with c2:
            ticker_b = selector_ticker_autocomplete('coint_b', label='Activo B')
        with c3:
            periodo = st.selectbox('Historial', ['1y', '2y', '5y'], index=1, key='coint_periodo')

        cp1, cp2, cp3, cp4 = st.columns(4)
        with cp1:
            z_window = st.slider('Ventana Z-Score', 10, 100, 30, 5, key='coint_zwin')
        with cp2:
            entry_z = st.slider('Z de entrada', 0.5, 3.5, 2.0, 0.1, key='coint_entry')
        with cp3:
            exit_z = st.slider('Z de salida', 0.1, 1.5, 0.5, 0.1, key='coint_exit')
        with cp4:
            significancia = st.selectbox('Significancia', [0.01, 0.05, 0.10], index=1, key='coint_sig')

        if not ticker_a or not ticker_b or ticker_a == ticker_b:
            st.info('Elegí dos activos distintos para testear cointegración.')
            return

        if st.button('▶ Analizar cointegración', key='coint_run', type='primary'):
            st.session_state['coint_run_flag'] = True

        if not st.session_state.get('coint_run_flag'):
            return

        with st.spinner(f'Descargando {ticker_a} / {ticker_b}...'):
            df_a = descargar_datos(ticker_a, periodo)
            df_b = descargar_datos(ticker_b, periodo)

        if df_a is None or df_b is None:
            st.error('No se pudieron descargar precios para uno o ambos activos.')
            return

        cl_a = get_close_series(df_a)
        cl_b = get_close_series(df_b)
        if cl_a is None or cl_b is None or len(cl_a) < 60 or len(cl_b) < 60:
            st.error('Historial insuficiente (mínimo ~60 ruedas) para el test de cointegración.')
            return

        stats = analyze_pair(cl_a, cl_b, ticker_a, ticker_b,
                              zscore_window=z_window, significance=significancia)

        badge_color = '#3fb950' if stats.is_cointegrated else '#f85149'
        badge_txt = 'COINTEGRADOS ✓' if stats.is_cointegrated else 'NO COINTEGRADOS ✗'

        kpi_cards_4([
            ('Engle-Granger p-value', f'{stats.pvalue:.4f}', badge_txt, badge_color),
            ('Hedge Ratio (β)', f'{stats.hedge_ratio:.4f}',
             f'{ticker_a} = β·{ticker_b} + {stats.intercept:.2f}', '#3a7bd5'),
            ('Half-Life', f'{stats.half_life:.1f} ruedas' if stats.half_life else 'N/A',
             'Reversión a la media (OU)', '#e3b341'),
            ('Hurst', f'{stats.hurst:.3f}' if stats.hurst is not None else 'N/A',
             'H<0.5 = mean-reverting' if (stats.hurst or 0.5) < 0.5 else 'H≥0.5 = trending/random',
             '#7ee787' if (stats.hurst or 0.5) < 0.5 else '#f0883e'),
        ])

        c4, c5 = st.columns(2)
        with c4:
            st.metric('ADF sobre el spread', 'Estacionario ✓' if stats.adf_is_stationary else 'No estacionario ✗',
                       f'p-value: {stats.adf_pvalue:.4f}' if stats.adf_pvalue is not None else '')
        with c5:
            st.metric('Z-Score actual', f'{stats.current_zscore:+.2f}' if stats.current_zscore is not None else 'N/A')

        if not stats.is_cointegrated:
            st.warning(
                f'⚠️ {ticker_a}/{ticker_b} NO pasan el test de Engle-Granger al {int((1-significancia)*100)}% '
                'de confianza. El spread puede no revertir a la media — el par no es un buen candidato '
                'para pairs trading con este historial. Podés seguir viendo el gráfico igual, con cautela.'
            )

        spread = calculate_spread(cl_a, cl_b, stats.hedge_ratio, stats.intercept)
        zscore = calculate_zscore(spread, window=z_window)
        signal = generate_signals(zscore, entry_z=entry_z, exit_z=exit_z)

        st.plotly_chart(
            _fig_spread_zscore(ticker_a, ticker_b, spread, zscore, entry_z, exit_z, palette),
            use_container_width=True, config=PLOTLY_CONFIG, key='coint_fig_spread',
        )

        st.markdown('---')
        st.markdown('### 📊 Backtest simplificado (sin costos/slippage)')
        strat_ret = compute_strategy_returns(cl_a, cl_b, stats.hedge_ratio, signal)
        metricas_bt = _metricas_backtest(strat_ret)

        if metricas_bt is None:
            st.info('No hubo suficientes señales de entrada/salida en este historial para backtestear.')
        else:
            kpi_cards_4([
                ('CAGR estrategia', f"{metricas_bt['cagr']*100:+.1f}%", 'Long/Short spread', '#3fb950'),
                ('Sharpe (aprox)', f"{metricas_bt['sharpe']:.2f}", 'Sin tasa libre de riesgo', '#3a7bd5'),
                ('Max Drawdown', f"{metricas_bt['max_dd']*100:.1f}%", '', '#f85149'),
                ('Capital final', f"{metricas_bt['capital_final']:.2f}x", 'Base 1.0 = capital inicial', '#e3b341'),
            ])
            fig_bt, _, _ = _fig_equity_backtest(strat_ret, palette, ticker_a, ticker_b)
            st.plotly_chart(fig_bt, use_container_width=True, config=PLOTLY_CONFIG, key='coint_fig_bt')
            st.caption(
                '⚠️ Backtest educativo: no incluye comisiones, slippage, ni costo de financiamiento '
                'de la posición corta. Los resultados históricos no garantizan resultados futuros.'
            )

        señal_actual = signal.iloc[-1] if len(signal) else 0
        if señal_actual == 1:
            txt_señal = f'🟢 LONG SPREAD — Comprar {ticker_a}, Vender {ticker_b} (β={stats.hedge_ratio:.3f})'
        elif señal_actual == -1:
            txt_señal = f'🔴 SHORT SPREAD — Vender {ticker_a}, Comprar {ticker_b} (β={stats.hedge_ratio:.3f})'
        else:
            txt_señal = '⚪ Sin posición — Z-Score dentro de rango neutral'

        st.markdown(f"""
        <div class="interp-card">
          <div class="interp-header">📍 Señal actual — {ticker_a}/{ticker_b}</div>
          {txt_señal}<br>
          <span style="color:#6b7d9a;font-size:11px">
            Half-life: {f'{stats.half_life:.1f} ruedas' if stats.half_life else 'no estimable'} ·
            No es asesoramiento financiero.
          </span>
        </div>
        """, unsafe_allow_html=True)

        chips_navegacion([(ticker_a, ticker_a), (ticker_b, ticker_b)], 'coint_par')

    # ══════════════════════════════════════════════════════════════
    #  TAB 2 — Escaneo de universo: todas las combinaciones
    # ══════════════════════════════════════════════════════════════
    with tab_universo:
        st.caption(
            'Ingresá una lista de tickers (separados por coma) y el motor testea TODAS las '
            'combinaciones de a pares, ordenando por p-value de Engle-Granger (más cointegrados primero).'
        )
        tickers_txt = st.text_area(
            'Tickers (separados por coma)', value='GGAL, BMA, SUPV, BBAR',
            key='coint_universo_txt', height=70,
        )
        cu1, cu2, cu3 = st.columns(3)
        with cu1:
            periodo_u = st.selectbox('Historial', ['1y', '2y', '5y'], index=1, key='coint_u_periodo')
        with cu2:
            sig_u = st.selectbox('Significancia', [0.01, 0.05, 0.10], index=1, key='coint_u_sig')
        with cu3:
            z_win_u = st.slider('Ventana Z-Score', 10, 100, 30, 5, key='coint_u_zwin')

        tickers_lista = sorted(set(t.strip().upper() for t in tickers_txt.split(',') if t.strip()))
        n_combos = len(list(combinations(tickers_lista, 2))) if len(tickers_lista) >= 2 else 0

        if len(tickers_lista) < 2:
            st.info('Ingresá al menos 2 tickers.')
            return
        if n_combos > 45:
            st.warning(f'⚠️ {n_combos} combinaciones — puede tardar. Con muchos tickers considerá menos activos.')

        if st.button('▶ Escanear universo', key='coint_u_run', type='primary'):
            st.session_state['coint_u_run_flag'] = True
        if not st.session_state.get('coint_u_run_flag'):
            return

        def _descargar_para_universo(tk):
            df = descargar_datos(tk, periodo_u)
            cl = get_close_series(df) if df is not None else None
            return tk, cl

        with st.spinner(f'Descargando {len(tickers_lista)} activos...'):
            precios = {}
            with ThreadPoolExecutor(max_workers=8) as ex:
                for tk, cl in ex.map(_descargar_para_universo, tickers_lista):
                    if cl is not None and len(cl) >= 60:
                        precios[tk] = cl

        faltantes = [t for t in tickers_lista if t not in precios]
        if faltantes:
            st.warning(f"Sin datos suficientes para: {', '.join(faltantes)}. Se excluyen del escaneo.")

        if len(precios) < 2:
            st.error('No hay suficientes activos con historial válido para escanear.')
            return

        price_df = pd.DataFrame(precios).dropna()

        with st.spinner(f'Testeando {len(list(combinations(price_df.columns, 2)))} combinaciones...'):
            df_scan = scan_universe(price_df, significance=sig_u, zscore_window=z_win_u)

        if df_scan.empty:
            st.error('No se pudo calcular ningún par (verificá el historial común entre activos).')
            return

        n_coint = int(df_scan['is_cointegrated'].sum())
        kpi_cards_4([
            ('Pares testeados', str(len(df_scan)), f'{len(price_df.columns)} activos', '#3a7bd5'),
            ('✓ Cointegrados', str(n_coint), f'p < {sig_u}', '#3fb950'),
            ('Mejor p-value', f"{df_scan['pvalue'].min():.4f}",
             f"{df_scan.iloc[0]['asset_a']}/{df_scan.iloc[0]['asset_b']}", '#e3b341'),
            ('Hurst prom. (cointegrados)',
             f"{df_scan[df_scan['is_cointegrated']]['hurst'].mean():.3f}" if n_coint else 'N/A',
             'H<0.5 = mean-reverting', '#7ee787'),
        ])

        df_show = df_scan.copy()
        df_show['pvalue'] = df_show['pvalue'].round(4)
        df_show['hedge_ratio'] = df_show['hedge_ratio'].round(4)
        df_show['half_life'] = df_show['half_life'].round(1)
        df_show['hurst'] = df_show['hurst'].round(3)
        df_show['current_zscore'] = df_show['current_zscore'].round(2)
        cols_mostrar = ['asset_a', 'asset_b', 'pvalue', 'is_cointegrated', 'hedge_ratio',
                         'half_life', 'hurst', 'adf_is_stationary', 'current_zscore']
        df_show = df_show[cols_mostrar]
        df_show.columns = ['Activo A', 'Activo B', 'p-value EG', 'Cointegrado', 'Hedge Ratio',
                            'Half-Life', 'Hurst', 'ADF Estac.', 'Z actual']

        def _color_coint(val):
            return 'color:#3fb950;font-weight:700' if val else 'color:#f85149'

        _map = 'map' if hasattr(df_show.style, 'map') else 'applymap'
        styled = (df_show.style
                  .pipe(lambda s: getattr(s, _map)(_color_coint, subset=['Cointegrado', 'ADF Estac.']))
                  .set_properties(**{'background-color': '#0d1117', 'color': '#e6edf3', 'border': '1px solid #21262d'})
                  .set_table_styles([
                      {'selector': 'th', 'props': [('background-color', '#161b22'), ('color', '#e6edf3'),
                          ('font-weight', '700'), ('text-align', 'center'),
                          ('border-bottom', '2px solid #bc8cff'), ('font-size', '11px')]},
                      {'selector': 'td', 'props': [('text-align', 'center'), ('font-size', '11px')]},
                  ]))
        st.dataframe(styled, use_container_width=True, height=min(600, max(150, len(df_show) * 35 + 45)))
        st.caption(
            '💡 Elegí un par de la tabla y andá a la pestaña "Par puntual" para ver el gráfico '
            'completo, el backtest y la señal actual.'
        )
