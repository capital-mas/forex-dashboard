# ==============================================================
#  MÓDULO AGRO — Márgenes por hectárea, stock de granos,
#  insumos y precios de mercado (commodities)
# ==============================================================

import streamlit as st
import pandas as pd
from datetime import date

TABLA_LOTES   = 'agro_lotes'
TABLA_COSTOS  = 'agro_costos'
TABLA_STOCK   = 'agro_stock'
TABLA_INSUMOS = 'agro_insumos'

CULTIVOS = ['Soja', 'Maíz', 'Trigo', 'Girasol', 'Sorgo', 'Cebada', 'Otro']

# Tickers de futuros usados por el resto de la app (MERCADOS_REALES)
TICKERS_GRANOS = {
    'Soja': 'ZS=F', 'Maíz': 'ZC=F', 'Trigo': 'ZW=F', 'Girasol': 'ZS=F',  # aprox
}

SQL_SETUP = """
create table if not exists agro_lotes (
    id bigint generated always as identity primary key,
    user_id uuid not null,
    nombre text not null,
    hectareas numeric not null,
    cultivo text,
    campana text,
    creado_en timestamptz default now()
);

create table if not exists agro_costos (
    id bigint generated always as identity primary key,
    user_id uuid not null,
    lote text,
    campana text,
    cultivo text,
    hectareas numeric not null,
    rinde_qq_ha numeric,
    precio_venta_ton numeric,
    costo_insumos_ha numeric default 0,
    costo_labores_ha numeric default 0,
    costo_otros_ha numeric default 0,
    creado_en timestamptz default now()
);

create table if not exists agro_stock (
    id bigint generated always as identity primary key,
    user_id uuid not null,
    cultivo text not null,
    toneladas numeric not null,
    ubicacion text,
    fecha date default current_date,
    precio_fijado_ton numeric,
    creado_en timestamptz default now()
);

create table if not exists agro_insumos (
    id bigint generated always as identity primary key,
    user_id uuid not null,
    nombre text not null,
    categoria text,       -- 'Semilla' | 'Fertilizante' | 'Agroquímico' | 'Combustible' | 'Otro'
    cantidad numeric,
    unidad text,
    costo_total numeric,
    fecha_compra date default current_date,
    lote text,
    creado_en timestamptz default now()
);

alter table agro_lotes   enable row level security;
alter table agro_costos  enable row level security;
alter table agro_stock   enable row level security;
alter table agro_insumos enable row level security;

create policy "usuario ve sus lotes"   on agro_lotes   for all using (auth.uid() = user_id);
create policy "usuario ve sus costos"  on agro_costos  for all using (auth.uid() = user_id);
create policy "usuario ve su stock"    on agro_stock   for all using (auth.uid() = user_id);
create policy "usuario ve sus insumos" on agro_insumos for all using (auth.uid() = user_id);
"""


# ── Helpers Supabase ──────────────────────────────────────────────────

def _fetch(supabase, tabla, user_id, order_col=None, desc=True):
    try:
        q = supabase.table(tabla).select('*').eq('user_id', user_id)
        if order_col:
            q = q.order(order_col, desc=desc)
        res = q.execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _insert(supabase, tabla, payload):
    try:
        supabase.table(tabla).insert(payload).execute()
        return True
    except Exception as e:
        st.error(f'⚠️ No se pudo guardar. Puede que falte crear la tabla `{tabla}` en Supabase. Detalle: {e}')
        return False


def _delete(supabase, tabla, row_id):
    try:
        supabase.table(tabla).delete().eq('id', row_id).execute()
        return True
    except Exception as e:
        st.error(f'⚠️ No se pudo eliminar: {e}')
        return False


def _kpi_row(items):
    cols = st.columns(len(items))
    for col, (label, value, sub, color) in zip(cols, items):
        with col:
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-accent" style="background:{color}"></div>'
                f'<div class="kpi-label">{label}</div>'
                f'<div class="kpi-value">{value}</div>'
                f'<div class="kpi-sub">{sub}</div></div>',
                unsafe_allow_html=True,
            )
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)


def _fmt_money(v):
    try:
        return f'${float(v):,.2f}'
    except Exception:
        return '$0.00'


def _setup_expander():
    with st.expander('🛠️ ¿Primera vez? Crear tablas en Supabase', expanded=False):
        st.markdown(
            'Si las tablas todavía no existen, corré este SQL una vez en el '
            '**SQL Editor** de tu proyecto Supabase:'
        )
        st.code(SQL_SETUP, language='sql')


# ── TAB: Lotes / Campos ────────────────────────────────────────────────

def _tab_lotes(supabase, user_id):
    with st.form('agro_lote_form', clear_on_submit=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            nombre = st.text_input('Nombre del lote/campo', key='agro_lote_nombre')
        with c2:
            hectareas = st.number_input('Hectáreas', min_value=0.0, step=1.0, key='agro_lote_ha')
        with c3:
            cultivo = st.selectbox('Cultivo actual', CULTIVOS, key='agro_lote_cultivo')
        with c4:
            campana = st.text_input('Campaña', placeholder='Ej: 2025/26', key='agro_lote_campana')
        if st.form_submit_button('➕ Agregar lote', use_container_width=True):
            if nombre and hectareas > 0:
                ok = _insert(supabase, TABLA_LOTES, {
                    'user_id': user_id, 'nombre': nombre, 'hectareas': float(hectareas),
                    'cultivo': cultivo, 'campana': campana,
                })
                if ok:
                    st.success('Lote agregado.')
                    st.rerun()
            else:
                st.warning('Completá nombre y hectáreas mayores a 0.')

    df = _fetch(supabase, TABLA_LOTES, user_id, order_col='nombre', desc=False)
    if df.empty:
        st.info('Todavía no hay lotes cargados.')
        _setup_expander()
        return

    df['hectareas'] = pd.to_numeric(df['hectareas'], errors='coerce').fillna(0)
    _kpi_row([
        ('Lotes registrados', str(len(df)), 'Total', '#3fb950'),
        ('Hectáreas totales', f"{df['hectareas'].sum():,.1f} ha", 'Suma de todos los lotes', '#3a7bd5'),
        ('Cultivos distintos', str(df['cultivo'].nunique()), 'Diversidad', '#e3b341'),
        ('Ha promedio/lote', f"{df['hectareas'].mean():,.1f} ha", 'Tamaño medio', '#bc8cff'),
    ])

    st.markdown('<div class="sec-title">Lotes registrados</div>', unsafe_allow_html=True)
    st.dataframe(df[['nombre', 'hectareas', 'cultivo', 'campana']], use_container_width=True,
                 hide_index=True, height=min(400, len(df) * 38 + 45))

    with st.expander('🗑️ Eliminar un lote'):
        opciones = {f"#{r['id']} · {r['nombre']} · {r['hectareas']} ha · {r.get('cultivo','')}": r['id']
                    for _, r in df.iterrows()}
        if opciones:
            sel = st.selectbox('Elegí el lote', list(opciones.keys()), key='agro_lote_del_sel')
            if st.button('Eliminar', key='agro_lote_del_btn'):
                if _delete(supabase, TABLA_LOTES, opciones[sel]):
                    st.success('Eliminado.')
                    st.rerun()

    _setup_expander()


# ── TAB: Costos y Márgenes ─────────────────────────────────────────────

def _tab_margenes(supabase, user_id):
    df_lotes = _fetch(supabase, TABLA_LOTES, user_id)
    nombres_lotes = df_lotes['nombre'].tolist() if not df_lotes.empty else []

    with st.form('agro_costo_form', clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            lote = st.selectbox('Lote (opcional)', ['(sin asignar)'] + nombres_lotes, key='agro_costo_lote')
        with c2:
            cultivo = st.selectbox('Cultivo', CULTIVOS, key='agro_costo_cultivo')
        with c3:
            campana = st.text_input('Campaña', placeholder='Ej: 2025/26', key='agro_costo_campana')
        c4, c5 = st.columns(2)
        with c4:
            hectareas = st.number_input('Hectáreas de este lote/cultivo', min_value=0.1, step=1.0, value=1.0, key='agro_costo_ha')
        with c5:
            rinde = st.number_input('Rinde esperado/real (qq/ha)', min_value=0.0, step=1.0, key='agro_costo_rinde')
        c6, c7, c8, c9 = st.columns(4)
        with c6:
            precio_ton = st.number_input('Precio de venta (USD/ton)', min_value=0.0, step=1.0, key='agro_costo_precio')
        with c7:
            costo_insumos = st.number_input('Costo insumos (USD/ha)', min_value=0.0, step=1.0, key='agro_costo_insumos')
        with c8:
            costo_labores = st.number_input('Costo labores (USD/ha)', min_value=0.0, step=1.0, key='agro_costo_labores')
        with c9:
            costo_otros = st.number_input('Otros costos (USD/ha)', min_value=0.0, step=1.0, key='agro_costo_otros')

        if st.form_submit_button('➕ Guardar campaña de costos', use_container_width=True):
            ok = _insert(supabase, TABLA_COSTOS, {
                'user_id': user_id,
                'lote': None if lote == '(sin asignar)' else lote,
                'campana': campana, 'cultivo': cultivo, 'hectareas': float(hectareas),
                'rinde_qq_ha': float(rinde), 'precio_venta_ton': float(precio_ton),
                'costo_insumos_ha': float(costo_insumos), 'costo_labores_ha': float(costo_labores),
                'costo_otros_ha': float(costo_otros),
            })
            if ok:
                st.success('Campaña guardada.')
                st.rerun()

    df = _fetch(supabase, TABLA_COSTOS, user_id, order_col='campana', desc=True)
    if df.empty:
        st.info('Todavía no hay campañas de costos cargadas.')
        return

    for c in ['hectareas', 'rinde_qq_ha', 'precio_venta_ton', 'costo_insumos_ha', 'costo_labores_ha', 'costo_otros_ha']:
        df[c] = pd.to_numeric(df.get(c, 0), errors='coerce').fillna(0)

    # 1 quintal (qq) = 100 kg = 0.1 tonelada
    df['ingreso_ha'] = df['rinde_qq_ha'] * 0.1 * df['precio_venta_ton']
    df['costo_total_ha'] = df['costo_insumos_ha'] + df['costo_labores_ha'] + df['costo_otros_ha']
    df['margen_ha'] = df['ingreso_ha'] - df['costo_total_ha']
    df['margen_total'] = df['margen_ha'] * df['hectareas']
    df['ingreso_total'] = df['ingreso_ha'] * df['hectareas']
    df['margen_pct'] = (df['margen_ha'] / df['ingreso_ha'].replace(0, pd.NA) * 100).fillna(0)

    margen_total = df['margen_total'].sum()
    ingreso_total = df['ingreso_total'].sum()
    ha_totales = df['hectareas'].sum()
    margen_ha_prom = margen_total / ha_totales if ha_totales else 0

    _kpi_row([
        ('Margen total', _fmt_money(margen_total), f'{len(df)} campañas', '#3fb950' if margen_total >= 0 else '#f85149'),
        ('Ingreso total', _fmt_money(ingreso_total), 'Bruto estimado', '#3a7bd5'),
        ('Margen promedio/ha', _fmt_money(margen_ha_prom), 'Ponderado por hectáreas', '#e3b341'),
        ('Hectáreas totales', f'{ha_totales:,.1f} ha', 'Suma de campañas', '#bc8cff'),
    ])

    st.markdown('<div class="sec-title">Detalle por campaña / lote / cultivo</div>', unsafe_allow_html=True)
    cols_show = ['id', 'lote', 'campana', 'cultivo', 'hectareas', 'rinde_qq_ha', 'precio_venta_ton',
                 'ingreso_ha', 'costo_total_ha', 'margen_ha', 'margen_pct', 'margen_total']
    df_show = df[cols_show].copy()
    df_show.columns = ['#', 'Lote', 'Campaña', 'Cultivo', 'Ha', 'Rinde qq/ha', 'Precio USD/ton',
                        'Ingreso USD/ha', 'Costo USD/ha', 'Margen USD/ha', 'Margen %', 'Margen Total USD']
    for c in ['Ingreso USD/ha', 'Costo USD/ha', 'Margen USD/ha', 'Margen Total USD']:
        df_show[c] = df_show[c].apply(lambda v: f'${v:,.1f}')
    df_show['Margen %'] = df_show['Margen %'].apply(lambda v: f'{v:+.1f}%')
    st.dataframe(df_show.drop(columns=['#']), use_container_width=True, hide_index=True,
                 height=min(450, len(df_show) * 38 + 45))

    st.markdown('<div class="sec-title">Margen por hectárea, por cultivo</div>', unsafe_allow_html=True)
    resumen_cultivo = df.groupby('cultivo')['margen_ha'].mean().sort_values(ascending=False)
    st.bar_chart(resumen_cultivo, height=280)

    with st.expander('🗑️ Eliminar una campaña'):
        opciones = {f"#{r['#']} · {r['Lote']} · {r['Campaña']} · {r['Cultivo']}": r['#']
                    for _, r in df_show.iterrows()}
        if opciones:
            sel = st.selectbox('Elegí la campaña', list(opciones.keys()), key='agro_costo_del_sel')
            if st.button('Eliminar', key='agro_costo_del_btn'):
                if _delete(supabase, TABLA_COSTOS, opciones[sel]):
                    st.success('Eliminado.')
                    st.rerun()

    st.markdown(f"""
    <div class="interp-card">
      <div class="interp-header">🧭 Lectura rápida</div>
      El margen se calcula como (Rinde qq/ha × 0.1 × Precio USD/ton) − (Insumos + Labores + Otros costos por ha).
      El margen promedio ponderado por hectáreas de todas las campañas cargadas es {_fmt_money(margen_ha_prom)}/ha.
    </div>
    """, unsafe_allow_html=True)


# ── TAB: Stock de Granos ────────────────────────────────────────────────

def _tab_stock(supabase, user_id):
    with st.form('agro_stock_form', clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            cultivo = st.selectbox('Cultivo', CULTIVOS, key='agro_stock_cultivo')
        with c2:
            toneladas = st.number_input('Toneladas', min_value=0.0, step=1.0, key='agro_stock_ton')
        with c3:
            ubicacion = st.text_input('Ubicación (silo/acopio)', key='agro_stock_ubic')
        c4, c5 = st.columns(2)
        with c4:
            fecha = st.date_input('Fecha', value=date.today(), key='agro_stock_fecha')
        with c5:
            precio_fijado = st.number_input('Precio fijado (USD/ton, opcional)', min_value=0.0, step=1.0, key='agro_stock_precio')
        if st.form_submit_button('➕ Registrar stock', use_container_width=True):
            if toneladas > 0:
                ok = _insert(supabase, TABLA_STOCK, {
                    'user_id': user_id, 'cultivo': cultivo, 'toneladas': float(toneladas),
                    'ubicacion': ubicacion, 'fecha': str(fecha),
                    'precio_fijado_ton': float(precio_fijado) if precio_fijado > 0 else None,
                })
                if ok:
                    st.success('Stock registrado.')
                    st.rerun()
            else:
                st.warning('Las toneladas deben ser mayores a 0.')

    df = _fetch(supabase, TABLA_STOCK, user_id, order_col='fecha', desc=True)
    if df.empty:
        st.info('Todavía no hay stock cargado.')
        return

    df['toneladas'] = pd.to_numeric(df['toneladas'], errors='coerce').fillna(0)
    df['precio_fijado_ton'] = pd.to_numeric(df.get('precio_fijado_ton'), errors='coerce')

    con_precio = df.dropna(subset=['precio_fijado_ton'])
    valor_fijado = (con_precio['toneladas'] * con_precio['precio_fijado_ton']).sum()
    sin_fijar = df['precio_fijado_ton'].isna().sum()

    _kpi_row([
        ('Toneladas totales', f"{df['toneladas'].sum():,.1f} tn", f'{len(df)} lotes de stock', '#3fb950'),
        ('Valor de lo fijado', _fmt_money(valor_fijado), f'{len(con_precio)} con precio', '#3a7bd5'),
        ('Sin precio fijar', str(sin_fijar), 'Expuesto a variación de mercado', '#e3b341'),
        ('Cultivos en stock', str(df['cultivo'].nunique()), 'Diversidad', '#bc8cff'),
    ])

    st.markdown('<div class="sec-title">Stock por cultivo</div>', unsafe_allow_html=True)
    resumen = df.groupby('cultivo')['toneladas'].sum().sort_values(ascending=False)
    st.bar_chart(resumen, height=280)

    st.markdown('<div class="sec-title">Detalle de stock</div>', unsafe_allow_html=True)
    cols_show = ['id', 'cultivo', 'toneladas', 'ubicacion', 'fecha', 'precio_fijado_ton']
    cols_show = [c for c in cols_show if c in df.columns]
    st.dataframe(df[cols_show].drop(columns=['id']), use_container_width=True, hide_index=True,
                 height=min(400, len(df) * 38 + 45))

    with st.expander('🗑️ Eliminar un registro de stock'):
        opciones = {f"#{r['id']} · {r['cultivo']} · {r['toneladas']} tn · {r.get('ubicacion','')}": r['id']
                    for _, r in df.iterrows()}
        if opciones:
            sel = st.selectbox('Elegí el registro', list(opciones.keys()), key='agro_stock_del_sel')
            if st.button('Eliminar', key='agro_stock_del_btn'):
                if _delete(supabase, TABLA_STOCK, opciones[sel]):
                    st.success('Eliminado.')
                    st.rerun()


# ── TAB: Insumos ──────────────────────────────────────────────────────

def _tab_insumos(supabase, user_id):
    with st.form('agro_insumo_form', clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            nombre = st.text_input('Nombre del insumo', key='agro_ins_nombre')
        with c2:
            categoria = st.selectbox('Categoría', ['Semilla', 'Fertilizante', 'Agroquímico', 'Combustible', 'Otro'], key='agro_ins_cat')
        with c3:
            lote = st.text_input('Lote (opcional)', key='agro_ins_lote')
        c4, c5, c6 = st.columns(3)
        with c4:
            cantidad = st.number_input('Cantidad', min_value=0.0, step=1.0, key='agro_ins_cant')
        with c5:
            unidad = st.text_input('Unidad', placeholder='kg, lts, bolsas', key='agro_ins_unidad')
        with c6:
            costo_total = st.number_input('Costo total (USD)', min_value=0.0, step=10.0, key='agro_ins_costo')
        fecha = st.date_input('Fecha de compra', value=date.today(), key='agro_ins_fecha')
        if st.form_submit_button('➕ Registrar insumo', use_container_width=True):
            if nombre and costo_total >= 0:
                ok = _insert(supabase, TABLA_INSUMOS, {
                    'user_id': user_id, 'nombre': nombre, 'categoria': categoria,
                    'cantidad': float(cantidad), 'unidad': unidad, 'costo_total': float(costo_total),
                    'fecha_compra': str(fecha), 'lote': lote,
                })
                if ok:
                    st.success('Insumo registrado.')
                    st.rerun()
            else:
                st.warning('Completá al menos el nombre del insumo.')

    df = _fetch(supabase, TABLA_INSUMOS, user_id, order_col='fecha_compra', desc=True)
    if df.empty:
        st.info('Todavía no hay insumos cargados.')
        return

    df['costo_total'] = pd.to_numeric(df['costo_total'], errors='coerce').fillna(0)

    _kpi_row([
        ('Gasto total en insumos', _fmt_money(df['costo_total'].sum()), f'{len(df)} compras', '#f85149'),
        ('Categorías', str(df['categoria'].nunique()), 'Distintas', '#3a7bd5'),
        ('Compra promedio', _fmt_money(df['costo_total'].mean()), 'Por registro', '#e3b341'),
        ('Última compra', str(df['fecha_compra'].iloc[0]) if len(df) else '-', '', '#bc8cff'),
    ])

    st.markdown('<div class="sec-title">Gasto por categoría</div>', unsafe_allow_html=True)
    resumen = df.groupby('categoria')['costo_total'].sum().sort_values(ascending=False)
    st.bar_chart(resumen, height=280)

    st.markdown('<div class="sec-title">Detalle de insumos</div>', unsafe_allow_html=True)
    cols_show = ['id', 'nombre', 'categoria', 'cantidad', 'unidad', 'costo_total', 'fecha_compra', 'lote']
    cols_show = [c for c in cols_show if c in df.columns]
    st.dataframe(df[cols_show].drop(columns=['id']), use_container_width=True, hide_index=True,
                 height=min(400, len(df) * 38 + 45))

    with st.expander('🗑️ Eliminar un insumo'):
        opciones = {f"#{r['id']} · {r['nombre']} · {_fmt_money(r['costo_total'])}": r['id']
                    for _, r in df.iterrows()}
        if opciones:
            sel = st.selectbox('Elegí el insumo', list(opciones.keys()), key='agro_ins_del_sel')
            if st.button('Eliminar', key='agro_ins_del_btn'):
                if _delete(supabase, TABLA_INSUMOS, opciones[sel]):
                    st.success('Eliminado.')
                    st.rerun()


# ── TAB: Precios de Mercado ──────────────────────────────────────────

def _tab_precios(descargar_datos, get_close_series):
    st.markdown(
        '<div class="info-banner">Precios de futuros de granos (Yahoo Finance / CME), '
        'para contrastar contra tus costos y decidir cuándo fijar precio.</div>',
        unsafe_allow_html=True,
    )

    if descargar_datos is None or get_close_series is None:
        st.info('Esta sección requiere conexión con los datos de mercado de la app principal.')
        return

    cultivo_sel = st.selectbox('Cultivo', list(TICKERS_GRANOS.keys()), key='agro_precio_cultivo')
    periodo = st.selectbox('Período', ['1mo', '3mo', '6mo', '1y', '2y'], index=2, key='agro_precio_periodo')
    ticker = TICKERS_GRANOS[cultivo_sel]

    with st.spinner(f'Descargando precios de {cultivo_sel} ({ticker})...'):
        df_precio = descargar_datos(ticker, periodo)
        cl = get_close_series(df_precio) if df_precio is not None else None

    if cl is None or len(cl) < 2:
        st.warning(f'No se pudieron obtener precios para {cultivo_sel} ({ticker}).')
        return

    precio_actual = float(cl.iloc[-1])
    precio_inicial = float(cl.iloc[0])
    variacion = (precio_actual / precio_inicial - 1) * 100 if precio_inicial else 0

    _kpi_row([
        ('Precio actual', f'${precio_actual:,.2f}', ticker, '#3fb950' if variacion >= 0 else '#f85149'),
        ('Variación período', f'{variacion:+.2f}%', periodo, '#3fb950' if variacion >= 0 else '#f85149'),
        ('Máximo período', f'${float(cl.max()):,.2f}', '', '#3a7bd5'),
        ('Mínimo período', f'${float(cl.min()):,.2f}', '', '#e3b341'),
    ])

    st.line_chart(cl, height=320)
    st.caption(
        f'Nota: el precio de futuros ({ticker}) suele cotizar en centavos de USD por bushel (granos CBOT); '
        'usalo como referencia de tendencia, no como precio físico exacto en tu zona.'
    )


def render_agro(supabase, user_id, descargar_datos=None, get_close_series=None):
    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1a10 0%,#0a2015 50%,#0d1117 100%);
         border:1px solid #21262d;border-top:2px solid #3fb950;border-radius:14px;
         padding:24px 28px;margin-bottom:20px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">🌾 Módulo Agro</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Márgenes por hectárea, stock de granos y seguimiento de insumos, con precios de mercado en tiempo real.
      </div>
    </div>
    """, unsafe_allow_html=True)

    tab_lotes, tab_margenes, tab_stock, tab_insumos, tab_precios = st.tabs(
        ['🗺️ Lotes', '💰 Costos y Márgenes', '🌾 Stock de Granos', '🧪 Insumos', '📈 Precios de Mercado']
    )
    with tab_lotes:
        _tab_lotes(supabase, user_id)
    with tab_margenes:
        _tab_margenes(supabase, user_id)
    with tab_stock:
        _tab_stock(supabase, user_id)
    with tab_insumos:
        _tab_insumos(supabase, user_id)
    with tab_precios:
        _tab_precios(descargar_datos, get_close_series)
