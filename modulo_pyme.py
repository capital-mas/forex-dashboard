# ==============================================================
#  MÓDULO PyMEs — Cashflow, Cuentas por Cobrar/Pagar y Cheques
# ==============================================================

import streamlit as st
import pandas as pd
from datetime import datetime, date

TABLA_CASH = 'pyme_cashflow'
TABLA_CXC  = 'pyme_cuentas'
TABLA_CHQ  = 'pyme_cheques'

SQL_SETUP = """
create table if not exists pyme_cashflow (
    id bigint generated always as identity primary key,
    user_id uuid not null,
    fecha date not null default current_date,
    tipo text not null,              -- 'Ingreso' | 'Egreso'
    categoria text,
    monto numeric not null,
    descripcion text,
    creado_en timestamptz default now()
);

create table if not exists pyme_cuentas (
    id bigint generated always as identity primary key,
    user_id uuid not null,
    tipo text not null,              -- 'Cobrar' | 'Pagar'
    contraparte text,
    monto numeric not null,
    fecha_emision date,
    fecha_vencimiento date,
    estado text default 'Pendiente', -- 'Pendiente' | 'Saldado' | 'Vencido'
    notas text,
    creado_en timestamptz default now()
);

create table if not exists pyme_cheques (
    id bigint generated always as identity primary key,
    user_id uuid not null,
    tipo text not null,              -- 'Propio' | 'Tercero'
    numero text,
    banco text,
    contraparte text,
    monto numeric not null,
    fecha_emision date,
    fecha_cobro date,
    estado text default 'En cartera',-- 'En cartera' | 'Depositado' | 'Cobrado' | 'Rechazado'
    creado_en timestamptz default now()
);

alter table pyme_cashflow enable row level security;
alter table pyme_cuentas  enable row level security;
alter table pyme_cheques  enable row level security;

create policy "usuario ve su cashflow" on pyme_cashflow for all using (auth.uid() = user_id);
create policy "usuario ve su cxc"      on pyme_cuentas  for all using (auth.uid() = user_id);
create policy "usuario ve sus cheques" on pyme_cheques  for all using (auth.uid() = user_id);
"""


# ── Helpers genéricos Supabase ───────────────────────────────────────

def _fetch(supabase, tabla, user_id, order_col=None, desc=True):
    try:
        q = supabase.table(tabla).select('*').eq('user_id', user_id)
        if order_col:
            q = q.order(order_col, desc=desc)
        res = q.execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception as e:
        st.session_state[f'_pyme_error_{tabla}'] = str(e)
        return pd.DataFrame()


def _insert(supabase, tabla, payload):
    try:
        supabase.table(tabla).insert(payload).execute()
        return True
    except Exception as e:
        st.error(f'⚠️ No se pudo guardar. Puede que falte crear la tabla `{tabla}` en Supabase. Detalle: {e}')
        return False


def _update(supabase, tabla, row_id, payload):
    try:
        supabase.table(tabla).update(payload).eq('id', row_id).execute()
        return True
    except Exception as e:
        st.error(f'⚠️ No se pudo actualizar: {e}')
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


# ── TAB: Cashflow ─────────────────────────────────────────────────────

def _tab_cashflow(supabase, user_id):
    with st.form('pyme_cash_form', clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([1, 1, 1.3, 1])
        with c1:
            fecha = st.date_input('Fecha', value=date.today(), key='pyme_cash_fecha')
        with c2:
            tipo = st.selectbox('Tipo', ['Ingreso', 'Egreso'], key='pyme_cash_tipo')
        with c3:
            categoria = st.text_input('Categoría', placeholder='Ej: Ventas, Alquiler, Sueldos', key='pyme_cash_cat')
        with c4:
            monto = st.number_input('Monto', min_value=0.0, step=100.0, key='pyme_cash_monto')
        descripcion = st.text_input('Descripción (opcional)', key='pyme_cash_desc')
        if st.form_submit_button('➕ Registrar movimiento', use_container_width=True):
            if monto > 0:
                ok = _insert(supabase, TABLA_CASH, {
                    'user_id': user_id, 'fecha': str(fecha), 'tipo': tipo,
                    'categoria': categoria, 'monto': float(monto), 'descripcion': descripcion,
                })
                if ok:
                    st.success('Movimiento registrado.')
                    st.rerun()
            else:
                st.warning('El monto debe ser mayor a 0.')

    df = _fetch(supabase, TABLA_CASH, user_id, order_col='fecha', desc=True)
    if df.empty:
        st.info('Todavía no hay movimientos cargados.')
        _setup_expander()
        return

    df['monto'] = pd.to_numeric(df['monto'], errors='coerce').fillna(0)
    ingresos = df.loc[df['tipo'] == 'Ingreso', 'monto'].sum()
    egresos  = df.loc[df['tipo'] == 'Egreso', 'monto'].sum()
    saldo    = ingresos - egresos

    _kpi_row([
        ('Ingresos totales', _fmt_money(ingresos), f'{(df["tipo"]=="Ingreso").sum()} movimientos', '#3fb950'),
        ('Egresos totales',  _fmt_money(egresos),  f'{(df["tipo"]=="Egreso").sum()} movimientos', '#f85149'),
        ('Saldo neto', _fmt_money(saldo), 'Ingresos - Egresos', '#3fb950' if saldo >= 0 else '#f85149'),
        ('Movimientos', str(len(df)), 'Total registrado', '#3a7bd5'),
    ])

    # Evolución acumulada
    df_ord = df.sort_values('fecha').copy()
    df_ord['signo'] = df_ord['tipo'].map({'Ingreso': 1, 'Egreso': -1})
    df_ord['flujo'] = df_ord['monto'] * df_ord['signo']
    df_ord['acumulado'] = df_ord['flujo'].cumsum()
    st.line_chart(df_ord.set_index('fecha')['acumulado'], height=280)

    st.markdown('<div class="sec-title">Movimientos registrados</div>', unsafe_allow_html=True)
    df_show = df[['id', 'fecha', 'tipo', 'categoria', 'monto', 'descripcion']].sort_values('fecha', ascending=False)
    st.dataframe(df_show.drop(columns=['id']), use_container_width=True, hide_index=True, height=min(400, len(df_show) * 38 + 45))

    with st.expander('🗑️ Eliminar un movimiento'):
        opciones = {f"#{r['id']} · {r['fecha']} · {r['tipo']} · {_fmt_money(r['monto'])} · {r.get('categoria','')}": r['id']
                    for _, r in df_show.iterrows()}
        if opciones:
            sel = st.selectbox('Elegí el movimiento', list(opciones.keys()), key='pyme_cash_del_sel')
            if st.button('Eliminar', key='pyme_cash_del_btn'):
                if _delete(supabase, TABLA_CASH, opciones[sel]):
                    st.success('Eliminado.')
                    st.rerun()

    _setup_expander()


# ── TAB: Cuentas por Cobrar / Pagar ──────────────────────────────────

def _tab_cuentas(supabase, user_id):
    with st.form('pyme_cxc_form', clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            tipo = st.selectbox('Tipo', ['Cobrar', 'Pagar'], key='pyme_cxc_tipo')
        with c2:
            contraparte = st.text_input('Cliente / Proveedor', key='pyme_cxc_contra')
        with c3:
            monto = st.number_input('Monto', min_value=0.0, step=100.0, key='pyme_cxc_monto')
        c4, c5, c6 = st.columns(3)
        with c4:
            f_emision = st.date_input('Fecha emisión', value=date.today(), key='pyme_cxc_femi')
        with c5:
            f_venc = st.date_input('Fecha vencimiento', value=date.today(), key='pyme_cxc_fven')
        with c6:
            estado = st.selectbox('Estado', ['Pendiente', 'Saldado', 'Vencido'], key='pyme_cxc_estado')
        notas = st.text_input('Notas (opcional)', key='pyme_cxc_notas')
        if st.form_submit_button('➕ Registrar cuenta', use_container_width=True):
            if monto > 0 and contraparte:
                ok = _insert(supabase, TABLA_CXC, {
                    'user_id': user_id, 'tipo': tipo, 'contraparte': contraparte,
                    'monto': float(monto), 'fecha_emision': str(f_emision),
                    'fecha_vencimiento': str(f_venc), 'estado': estado, 'notas': notas,
                })
                if ok:
                    st.success('Cuenta registrada.')
                    st.rerun()
            else:
                st.warning('Completá contraparte y un monto mayor a 0.')

    df = _fetch(supabase, TABLA_CXC, user_id, order_col='fecha_vencimiento', desc=False)
    if df.empty:
        st.info('Todavía no hay cuentas por cobrar/pagar cargadas.')
        return

    df['monto'] = pd.to_numeric(df['monto'], errors='coerce').fillna(0)
    hoy = pd.Timestamp(date.today())
    df['fecha_vencimiento_dt'] = pd.to_datetime(df['fecha_vencimiento'], errors='coerce')
    vencidas_auto = (df['estado'] == 'Pendiente') & (df['fecha_vencimiento_dt'] < hoy)

    cobrar_pend = df.loc[(df['tipo'] == 'Cobrar') & (df['estado'] != 'Saldado'), 'monto'].sum()
    pagar_pend  = df.loc[(df['tipo'] == 'Pagar')  & (df['estado'] != 'Saldado'), 'monto'].sum()
    n_venc = int(vencidas_auto.sum())

    _kpi_row([
        ('Por cobrar (pendiente)', _fmt_money(cobrar_pend), 'Clientes', '#3fb950'),
        ('Por pagar (pendiente)',  _fmt_money(pagar_pend),  'Proveedores', '#f85149'),
        ('Posición neta', _fmt_money(cobrar_pend - pagar_pend), 'Cobrar - Pagar', '#3a7bd5'),
        ('Vencidas sin saldar', str(n_venc), 'Requieren atención', '#f0883e' if n_venc else '#6b7d9a'),
    ])

    if n_venc:
        st.warning(f'⚠️ Tenés {n_venc} cuenta(s) pendiente(s) con fecha de vencimiento ya pasada.')

    f1, f2 = st.columns(2)
    with f1:
        f_tipo = st.selectbox('Filtrar por tipo', ['Todas', 'Cobrar', 'Pagar'], key='pyme_cxc_f_tipo')
    with f2:
        f_estado = st.selectbox('Filtrar por estado', ['Todos', 'Pendiente', 'Saldado', 'Vencido'], key='pyme_cxc_f_estado')

    df_f = df.copy()
    if f_tipo != 'Todas':
        df_f = df_f[df_f['tipo'] == f_tipo]
    if f_estado != 'Todos':
        df_f = df_f[df_f['estado'] == f_estado]

    st.markdown('<div class="sec-title">Cuentas registradas</div>', unsafe_allow_html=True)
    cols_show = ['id', 'tipo', 'contraparte', 'monto', 'fecha_emision', 'fecha_vencimiento', 'estado', 'notas']
    cols_show = [c for c in cols_show if c in df_f.columns]
    st.dataframe(df_f[cols_show].drop(columns=['id']), use_container_width=True, hide_index=True,
                 height=min(400, len(df_f) * 38 + 45))

    with st.expander('✏️ Marcar como saldada / eliminar'):
        opciones = {f"#{r['id']} · {r['tipo']} · {r.get('contraparte','')} · {_fmt_money(r['monto'])} · {r.get('estado','')}": r['id']
                    for _, r in df_f.iterrows()}
        if opciones:
            sel = st.selectbox('Elegí la cuenta', list(opciones.keys()), key='pyme_cxc_edit_sel')
            row_id = opciones[sel]
            ce1, ce2 = st.columns(2)
            with ce1:
                if st.button('✅ Marcar como Saldado', key='pyme_cxc_saldar_btn'):
                    if _update(supabase, TABLA_CXC, row_id, {'estado': 'Saldado'}):
                        st.success('Actualizado.')
                        st.rerun()
            with ce2:
                if st.button('🗑️ Eliminar', key='pyme_cxc_del_btn'):
                    if _delete(supabase, TABLA_CXC, row_id):
                        st.success('Eliminado.')
                        st.rerun()


# ── TAB: Cartera de Cheques ───────────────────────────────────────────

def _tab_cheques(supabase, user_id):
    with st.form('pyme_chq_form', clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            tipo = st.selectbox('Tipo', ['Propio', 'Tercero'], key='pyme_chq_tipo')
        with c2:
            numero = st.text_input('Número de cheque', key='pyme_chq_num')
        with c3:
            banco = st.text_input('Banco', key='pyme_chq_banco')
        c4, c5, c6 = st.columns(3)
        with c4:
            contraparte = st.text_input('Beneficiario / Librador', key='pyme_chq_contra')
        with c5:
            monto = st.number_input('Monto', min_value=0.0, step=100.0, key='pyme_chq_monto')
        with c6:
            estado = st.selectbox('Estado', ['En cartera', 'Depositado', 'Cobrado', 'Rechazado'], key='pyme_chq_estado')
        c7, c8 = st.columns(2)
        with c7:
            f_emision = st.date_input('Fecha de emisión', value=date.today(), key='pyme_chq_femi')
        with c8:
            f_cobro = st.date_input('Fecha de cobro', value=date.today(), key='pyme_chq_fcob')
        if st.form_submit_button('➕ Registrar cheque', use_container_width=True):
            if monto > 0:
                ok = _insert(supabase, TABLA_CHQ, {
                    'user_id': user_id, 'tipo': tipo, 'numero': numero, 'banco': banco,
                    'contraparte': contraparte, 'monto': float(monto),
                    'fecha_emision': str(f_emision), 'fecha_cobro': str(f_cobro), 'estado': estado,
                })
                if ok:
                    st.success('Cheque registrado.')
                    st.rerun()
            else:
                st.warning('El monto debe ser mayor a 0.')

    df = _fetch(supabase, TABLA_CHQ, user_id, order_col='fecha_cobro', desc=False)
    if df.empty:
        st.info('Todavía no hay cheques cargados.')
        return

    df['monto'] = pd.to_numeric(df['monto'], errors='coerce').fillna(0)
    en_cartera = df.loc[df['estado'] == 'En cartera', 'monto'].sum()
    depositado = df.loc[df['estado'] == 'Depositado', 'monto'].sum()
    rechazado  = df.loc[df['estado'] == 'Rechazado', 'monto'].sum()

    _kpi_row([
        ('En cartera', _fmt_money(en_cartera), f"{(df['estado']=='En cartera').sum()} cheques", '#e3b341'),
        ('Depositados', _fmt_money(depositado), f"{(df['estado']=='Depositado').sum()} cheques", '#3a7bd5'),
        ('Rechazados', _fmt_money(rechazado), f"{(df['estado']=='Rechazado').sum()} cheques", '#f85149'),
        ('Total cartera', _fmt_money(df['monto'].sum()), f'{len(df)} cheques', '#3fb950'),
    ])

    f1, f2 = st.columns(2)
    with f1:
        f_tipo = st.selectbox('Filtrar por tipo', ['Todos', 'Propio', 'Tercero'], key='pyme_chq_f_tipo')
    with f2:
        f_estado = st.selectbox('Filtrar por estado', ['Todos', 'En cartera', 'Depositado', 'Cobrado', 'Rechazado'], key='pyme_chq_f_estado')

    df_f = df.copy()
    if f_tipo != 'Todos':
        df_f = df_f[df_f['tipo'] == f_tipo]
    if f_estado != 'Todos':
        df_f = df_f[df_f['estado'] == f_estado]

    st.markdown('<div class="sec-title">Cheques registrados</div>', unsafe_allow_html=True)
    cols_show = ['id', 'tipo', 'numero', 'banco', 'contraparte', 'monto', 'fecha_emision', 'fecha_cobro', 'estado']
    cols_show = [c for c in cols_show if c in df_f.columns]
    st.dataframe(df_f[cols_show].drop(columns=['id']), use_container_width=True, hide_index=True,
                 height=min(400, len(df_f) * 38 + 45))

    with st.expander('✏️ Cambiar estado / eliminar cheque'):
        opciones = {f"#{r['id']} · {r.get('numero','')} · {r.get('banco','')} · {_fmt_money(r['monto'])} · {r.get('estado','')}": r['id']
                    for _, r in df_f.iterrows()}
        if opciones:
            sel = st.selectbox('Elegí el cheque', list(opciones.keys()), key='pyme_chq_edit_sel')
            row_id = opciones[sel]
            nuevo_estado = st.selectbox('Nuevo estado', ['En cartera', 'Depositado', 'Cobrado', 'Rechazado'], key='pyme_chq_nuevo_estado')
            ce1, ce2 = st.columns(2)
            with ce1:
                if st.button('✅ Actualizar estado', key='pyme_chq_upd_btn'):
                    if _update(supabase, TABLA_CHQ, row_id, {'estado': nuevo_estado}):
                        st.success('Actualizado.')
                        st.rerun()
            with ce2:
                if st.button('🗑️ Eliminar', key='pyme_chq_del_btn'):
                    if _delete(supabase, TABLA_CHQ, row_id):
                        st.success('Eliminado.')
                        st.rerun()


# ── TAB: Resumen ───────────────────────────────────────────────────────

def _tab_resumen(supabase, user_id):
    df_cash = _fetch(supabase, TABLA_CASH, user_id)
    df_cxc  = _fetch(supabase, TABLA_CXC, user_id)
    df_chq  = _fetch(supabase, TABLA_CHQ, user_id)

    for df in (df_cash, df_cxc, df_chq):
        if not df.empty and 'monto' in df.columns:
            df['monto'] = pd.to_numeric(df['monto'], errors='coerce').fillna(0)

    saldo_caja = 0.0
    if not df_cash.empty:
        ingresos = df_cash.loc[df_cash['tipo'] == 'Ingreso', 'monto'].sum()
        egresos = df_cash.loc[df_cash['tipo'] == 'Egreso', 'monto'].sum()
        saldo_caja = ingresos - egresos

    cobrar_pend = df_cxc.loc[(df_cxc.get('tipo') == 'Cobrar') & (df_cxc.get('estado') != 'Saldado'), 'monto'].sum() if not df_cxc.empty else 0.0
    pagar_pend  = df_cxc.loc[(df_cxc.get('tipo') == 'Pagar')  & (df_cxc.get('estado') != 'Saldado'), 'monto'].sum() if not df_cxc.empty else 0.0
    cheques_cartera = df_chq.loc[df_chq.get('estado') == 'En cartera', 'monto'].sum() if not df_chq.empty else 0.0

    posicion_proyectada = saldo_caja + cobrar_pend - pagar_pend + cheques_cartera

    st.markdown('<div class="sec-title">Posición financiera consolidada</div>', unsafe_allow_html=True)
    _kpi_row([
        ('Saldo de caja', _fmt_money(saldo_caja), 'Cashflow acumulado', '#3fb950' if saldo_caja >= 0 else '#f85149'),
        ('Por cobrar pendiente', _fmt_money(cobrar_pend), 'Cuentas por cobrar', '#3a7bd5'),
        ('Por pagar pendiente', _fmt_money(pagar_pend), 'Cuentas por pagar', '#f85149'),
        ('Posición proyectada', _fmt_money(posicion_proyectada), 'Caja + cobrar - pagar + cheques', '#e3b341'),
    ])

    st.markdown(f"""
    <div class="interp-card">
      <div class="interp-header">🧭 Lectura</div>
      La posición proyectada considera el saldo actual de caja, sumando lo que se espera cobrar
      de clientes y los cheques en cartera, y restando lo pendiente de pago a proveedores.
      {'Es una posición saludable.' if posicion_proyectada >= 0 else 'Atención: la posición proyectada es negativa, revisá vencimientos próximos.'}
    </div>
    """, unsafe_allow_html=True)

    if not df_cash.empty:
        st.markdown('<div class="sec-title">Ingresos vs Egresos por categoría</div>', unsafe_allow_html=True)
        resumen_cat = df_cash.groupby(['categoria', 'tipo'])['monto'].sum().unstack(fill_value=0)
        st.bar_chart(resumen_cat, height=300)


def render_pyme(supabase, user_id):
    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d;border-top:2px solid #3a7bd5;border-radius:14px;
         padding:24px 28px;margin-bottom:20px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:6px">🏢 Módulo PyMEs</div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.7">
        Cashflow, cuentas por cobrar/pagar y cartera de cheques en un solo lugar.
      </div>
    </div>
    """, unsafe_allow_html=True)

    tab_cash, tab_cxc, tab_cheques, tab_resumen = st.tabs(
        ['💵 Cashflow', '📋 Cuentas por Cobrar/Pagar', '🧾 Cartera de Cheques', '📊 Resumen']
    )
    with tab_cash:
        _tab_cashflow(supabase, user_id)
    with tab_cxc:
        _tab_cuentas(supabase, user_id)
    with tab_cheques:
        _tab_cheques(supabase, user_id)
    with tab_resumen:
        _tab_resumen(supabase, user_id)
