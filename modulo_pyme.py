# ==============================================================
#  MÓDULO PyMEs — v2 (MODO SIMULACIÓN, sin base de datos)
#
#  Todo el estado vive en st.session_state (prefijo "pyme_sim_").
#  Nada se persiste entre sesiones todavía: es a propósito, para
#  poder terminar de cerrar toda la parte visual/UX antes de
#  conectar Supabase. Cuando esté todo aprobado, cada función
#  _sim_agregar / _sim_eliminar / _sim_actualizar de más abajo se
#  reemplaza por su equivalente real (insert/delete/update contra
#  las tablas pyme_ventas, pyme_gastos, pyme_inventario, etc. — el
#  esquema SQL de referencia queda comentado al final del archivo).
#
#  Navegación: igual que la barra superior de la app (pills +
#  popovers agrupados), para que la experiencia sea consistente:
#
#     📝 Registros   → Registro de ventas / gastos / inventarios
#     🧭 Gestión     → Clientes / Proveedores / Control de deudas
#     📈 Análisis    → Estadísticas / Reportes / Variación de productos
# ==============================================================

import streamlit as st
import pandas as pd
from datetime import date, datetime, timedelta

SIM_PREFIX = 'pyme_sim_'


def _key(nombre):
    return f'{SIM_PREFIX}{nombre}'


# ==============================================================
#  ESTADO SIMULADO — inicialización con datos de ejemplo
# ==============================================================

def _seed_inicial():
    """Datos de ejemplo para que el módulo se pueda demostrar y probar
    sin tener que cargar todo a mano. Se puede reiniciar en cualquier
    momento con el botón '🔄 Reiniciar datos de ejemplo'."""
    hoy = date.today()

    inventario = [
        {'id': 1, 'producto': 'Notebook 15" i5', 'categoria': 'Informática', 'stock_actual': 8,  'stock_minimo': 5, 'precio_costo': 450000, 'precio_venta': 620000},
        {'id': 2, 'producto': 'Monitor 24" FHD',  'categoria': 'Informática', 'stock_actual': 3,  'stock_minimo': 4, 'precio_costo': 120000, 'precio_venta': 165000},
        {'id': 3, 'producto': 'Mouse Inalámbrico','categoria': 'Accesorios', 'stock_actual': 25, 'stock_minimo': 10,'precio_costo': 6000,   'precio_venta': 11000},
        {'id': 4, 'producto': 'Teclado Mecánico', 'categoria': 'Accesorios', 'stock_actual': 12, 'stock_minimo': 6, 'precio_costo': 18000,  'precio_venta': 32000},
        {'id': 5, 'producto': 'Silla Ergonómica', 'categoria': 'Mobiliario','stock_actual': 2,  'stock_minimo': 3, 'precio_costo': 95000,  'precio_venta': 145000},
    ]

    clientes = [
        {'id': 1, 'nombre': 'Comercial del Sur SRL', 'contacto': 'Marcos Díaz', 'telefono': '011-4555-1234', 'email': 'compras@comercialsur.com', 'condicion_pago': 'Cuenta corriente', 'limite_credito': 800000},
        {'id': 2, 'nombre': 'Librería Central',        'contacto': 'Ana Gómez',  'telefono': '011-4777-5566', 'email': 'ana@libreriacentral.com', 'condicion_pago': 'Contado', 'limite_credito': 0},
        {'id': 3, 'nombre': 'Estudio Contable Pérez',  'contacto': 'Juan Pérez', 'telefono': '011-4999-8877', 'email': 'juan@estudioperez.com', 'condicion_pago': 'Cuenta corriente', 'limite_credito': 500000},
    ]

    proveedores = [
        {'id': 1, 'nombre': 'Distribuidora TecnoMax', 'contacto': 'Laura Fernández', 'telefono': '011-4333-2211', 'email': 'ventas@tecnomax.com', 'categoria': 'Informática', 'condiciones_pago': '30 días'},
        {'id': 2, 'nombre': 'Muebles del Norte',        'contacto': 'Carlos Ruiz',    'telefono': '011-4222-1100', 'email': 'carlos@mueblesnorte.com', 'categoria': 'Mobiliario', 'condiciones_pago': 'Contado'},
    ]

    ventas = [
        {'id': 1, 'fecha': str(hoy - timedelta(days=12)), 'cliente': 'Comercial del Sur SRL', 'producto': 'Notebook 15" i5', 'cantidad': 2, 'precio_unitario': 620000, 'total': 1240000, 'medio_pago': 'Cuenta corriente'},
        {'id': 2, 'fecha': str(hoy - timedelta(days=9)),  'cliente': 'Librería Central',        'producto': 'Mouse Inalámbrico', 'cantidad': 6, 'precio_unitario': 11000,  'total': 66000,   'medio_pago': 'Efectivo'},
        {'id': 3, 'fecha': str(hoy - timedelta(days=6)),  'cliente': 'Estudio Contable Pérez',  'producto': 'Monitor 24" FHD',   'cantidad': 3, 'precio_unitario': 165000, 'total': 495000,  'medio_pago': 'Cuenta corriente'},
        {'id': 4, 'fecha': str(hoy - timedelta(days=3)),  'cliente': 'Librería Central',        'producto': 'Teclado Mecánico',  'cantidad': 4, 'precio_unitario': 32000,  'total': 128000,  'medio_pago': 'Transferencia'},
        {'id': 5, 'fecha': str(hoy - timedelta(days=1)),  'cliente': 'Comercial del Sur SRL',   'producto': 'Silla Ergonómica',  'cantidad': 1, 'precio_unitario': 145000, 'total': 145000,  'medio_pago': 'Efectivo'},
    ]

    gastos = [
        {'id': 1, 'fecha': str(hoy - timedelta(days=20)), 'categoria': 'Alquiler',  'proveedor': '',                    'monto': 350000, 'descripcion': 'Alquiler del local — mes'},
        {'id': 2, 'fecha': str(hoy - timedelta(days=15)), 'categoria': 'Insumos',   'proveedor': 'Distribuidora TecnoMax', 'monto': 480000, 'descripcion': 'Compra de mercadería informática'},
        {'id': 3, 'fecha': str(hoy - timedelta(days=10)), 'categoria': 'Servicios', 'proveedor': '',                    'monto': 65000,  'descripcion': 'Luz, agua, internet'},
        {'id': 4, 'fecha': str(hoy - timedelta(days=4)),  'categoria': 'Sueldos',   'proveedor': '',                    'monto': 620000, 'descripcion': 'Sueldos del personal'},
    ]

    deudas = [
        {'id': 1, 'tipo': 'A pagar', 'contraparte': 'Distribuidora TecnoMax', 'monto': 480000, 'fecha_emision': str(hoy - timedelta(days=15)), 'fecha_vencimiento': str(hoy + timedelta(days=15)), 'estado': 'Pendiente', 'notas': 'Factura #A-0021'},
        {'id': 2, 'tipo': 'A cobrar', 'contraparte': 'Comercial del Sur SRL', 'monto': 1240000, 'fecha_emision': str(hoy - timedelta(days=12)), 'fecha_vencimiento': str(hoy + timedelta(days=18)), 'estado': 'Pendiente', 'notas': 'Factura #B-0104'},
        {'id': 3, 'tipo': 'A cobrar', 'contraparte': 'Estudio Contable Pérez', 'monto': 495000, 'fecha_emision': str(hoy - timedelta(days=6)), 'fecha_vencimiento': str(hoy - timedelta(days=1)), 'estado': 'Pendiente', 'notas': 'Vencida — reclamar'},
    ]

    historial_precios = [
        {'id': 1, 'fecha': str(hoy - timedelta(days=40)), 'producto': 'Notebook 15" i5', 'precio_anterior': 590000, 'precio_nuevo': 620000},
        {'id': 2, 'fecha': str(hoy - timedelta(days=25)), 'producto': 'Monitor 24" FHD', 'precio_anterior': 150000, 'precio_nuevo': 165000},
    ]

    movimientos_stock = [
        {'id': 1, 'fecha': str(hoy - timedelta(days=15)), 'producto': 'Notebook 15" i5', 'tipo': 'Entrada', 'cantidad': 10, 'nota': 'Reposición inicial'},
        {'id': 2, 'fecha': str(hoy - timedelta(days=12)), 'producto': 'Notebook 15" i5', 'tipo': 'Salida',  'cantidad': 2,  'nota': 'Venta #1'},
    ]

    st.session_state[_key('ventas')] = ventas
    st.session_state[_key('gastos')] = gastos
    st.session_state[_key('inventario')] = inventario
    st.session_state[_key('clientes')] = clientes
    st.session_state[_key('proveedores')] = proveedores
    st.session_state[_key('deudas')] = deudas
    st.session_state[_key('historial_precios')] = historial_precios
    st.session_state[_key('movimientos_stock')] = movimientos_stock

    for nombre in ['ventas', 'gastos', 'inventario', 'clientes', 'proveedores',
                   'deudas', 'historial_precios', 'movimientos_stock']:
        ids = [r['id'] for r in st.session_state[_key(nombre)]]
        st.session_state[_key(f'seq_{nombre}')] = max(ids) if ids else 0

    st.session_state[_key('init')] = True


def _init_sim():
    if not st.session_state.get(_key('init')):
        _seed_inicial()


# ── Helpers CRUD (en memoria) ───────────────────────────────────────

def _tabla(nombre):
    return st.session_state[_key(nombre)]


def _siguiente_id(nombre):
    nueva = st.session_state.get(_key(f'seq_{nombre}'), 0) + 1
    st.session_state[_key(f'seq_{nombre}')] = nueva
    return nueva


def _agregar(nombre, registro):
    registro = dict(registro)
    registro['id'] = _siguiente_id(nombre)
    _tabla(nombre).append(registro)
    return registro['id']


def _eliminar(nombre, id_):
    st.session_state[_key(nombre)] = [r for r in _tabla(nombre) if r['id'] != id_]


def _actualizar(nombre, id_, cambios):
    for r in _tabla(nombre):
        if r['id'] == id_:
            r.update(cambios)
            return True
    return False


def _df(nombre):
    datos = _tabla(nombre)
    return pd.DataFrame(datos) if datos else pd.DataFrame()


# ==============================================================
#  HELPERS DE UI
# ==============================================================

def _fmt_money(v):
    try:
        return f'${float(v):,.0f}'.replace(',', '.')
    except Exception:
        return '$0'


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


def _selector_o_texto(label, opciones, key, placeholder=''):
    """Selectbox con las opciones existentes + una opción para escribir
    un valor nuevo a mano (cliente/proveedor/producto que todavía no
    está cargado en su gestión)."""
    OTRO = '✏️ Otro (escribir)'
    elegido = st.selectbox(label, [OTRO] + opciones, key=f'{key}_sel')
    if elegido == OTRO:
        return st.text_input(f'{label} (nuevo)', key=f'{key}_manual', placeholder=placeholder)
    return elegido


def _tabla_con_borrado(nombre, columnas, titulo, formato_money_cols=None, key_sufijo=''):
    """Renderiza la tabla de una entidad simulada + un expander para
    borrar filas por selección."""
    df = _df(nombre)
    st.markdown(f'<div class="sec-title">{titulo}</div>', unsafe_allow_html=True)
    if df.empty:
        st.info('Todavía no hay registros cargados.')
        return df

    cols_mostrar = [c for c in columnas if c in df.columns]
    df_show = df[cols_mostrar].copy()
    if formato_money_cols:
        for c in formato_money_cols:
            if c in df_show.columns:
                df_show[c] = df_show[c].apply(_fmt_money)

    st.dataframe(df_show, use_container_width=True, hide_index=True,
                 height=min(420, len(df_show) * 38 + 45))

    with st.expander(f'🗑️ Eliminar un registro — {titulo.lower()}'):
        etiqueta_col = cols_mostrar[1] if len(cols_mostrar) > 1 else cols_mostrar[0]
        opciones = {f"#{r['id']} · {r.get(etiqueta_col, '')}": r['id'] for r in df.to_dict('records')}
        if opciones:
            sel = st.selectbox('Elegí el registro', list(opciones.keys()), key=f'{nombre}_del_sel_{key_sufijo}')
            if st.button('Eliminar', key=f'{nombre}_del_btn_{key_sufijo}'):
                _eliminar(nombre, opciones[sel])
                st.success('Eliminado (esto es una simulación, no se guarda de forma permanente).')
                st.rerun()
    return df


# ==============================================================
#  📝 REGISTRO DE VENTAS
# ==============================================================

def _tab_ventas():
    st.caption('🧪 Registro de ventas — simulación en memoria. Cada venta puede descontar stock automáticamente del inventario simulado.')

    df_inv = _df('inventario')
    df_cli = _df('clientes')
    nombres_prod = df_inv['producto'].tolist() if not df_inv.empty else []
    nombres_cli = df_cli['nombre'].tolist() if not df_cli.empty else []

    with st.form('pyme_form_ventas', clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            fecha = st.date_input('Fecha', value=date.today(), key='v_fecha')
        with c2:
            cliente = _selector_o_texto('Cliente', nombres_cli, 'v_cliente', 'Nombre del cliente')
        with c3:
            medio_pago = st.selectbox('Medio de pago', ['Efectivo', 'Transferencia', 'Tarjeta', 'Cuenta corriente'], key='v_medio')

        c4, c5, c6 = st.columns(3)
        with c4:
            producto = _selector_o_texto('Producto', nombres_prod, 'v_producto', 'Nombre del producto')
        with c5:
            cantidad = st.number_input('Cantidad', min_value=1, step=1, value=1, key='v_cant')
        with c6:
            precio_sugerido = 0.0
            if not df_inv.empty and producto in df_inv['producto'].values:
                precio_sugerido = float(df_inv.loc[df_inv['producto'] == producto, 'precio_venta'].iloc[0])
            precio_unitario = st.number_input('Precio unitario', min_value=0.0, step=100.0,
                                               value=precio_sugerido, key='v_precio')

        descontar_stock = st.checkbox('Descontar del inventario simulado', value=True, key='v_descontar')

        if st.form_submit_button('➕ Registrar venta', use_container_width=True, type='primary'):
            if producto and cliente and precio_unitario > 0:
                total = cantidad * precio_unitario
                _agregar('ventas', {
                    'fecha': str(fecha), 'cliente': cliente, 'producto': producto,
                    'cantidad': int(cantidad), 'precio_unitario': precio_unitario,
                    'total': total, 'medio_pago': medio_pago,
                })
                if descontar_stock and not df_inv.empty and producto in df_inv['producto'].values:
                    row = df_inv.loc[df_inv['producto'] == producto].iloc[0]
                    nuevo_stock = max(0, int(row['stock_actual']) - int(cantidad))
                    _actualizar('inventario', int(row['id']), {'stock_actual': nuevo_stock})
                    _agregar('movimientos_stock', {
                        'fecha': str(fecha), 'producto': producto, 'tipo': 'Salida',
                        'cantidad': int(cantidad), 'nota': 'Venta registrada',
                    })
                st.success('Venta registrada.')
                st.rerun()
            else:
                st.warning('Completá cliente, producto y un precio mayor a 0.')

    df = _df('ventas')
    if df.empty:
        st.info('Todavía no hay ventas cargadas.')
        return

    df['total'] = pd.to_numeric(df['total'], errors='coerce').fillna(0)
    total_vendido = df['total'].sum()
    ticket_prom = df['total'].mean()
    mejor_cliente = df.groupby('cliente')['total'].sum().idxmax() if not df.empty else '-'

    _kpi_row([
        ('Ventas totales', _fmt_money(total_vendido), f'{len(df)} ventas registradas', '#3fb950'),
        ('Ticket promedio', _fmt_money(ticket_prom), 'Por venta', '#3a7bd5'),
        ('Mejor cliente', mejor_cliente, 'Por monto total comprado', '#e3b341'),
        ('Unidades vendidas', str(int(pd.to_numeric(df['cantidad'], errors='coerce').fillna(0).sum())), 'Total acumulado', '#bc8cff'),
    ])

    df_ord = df.sort_values('fecha')
    serie_diaria = df_ord.groupby('fecha')['total'].sum()
    st.line_chart(serie_diaria, height=260)

    _tabla_con_borrado('ventas', ['id', 'fecha', 'cliente', 'producto', 'cantidad', 'precio_unitario', 'total', 'medio_pago'],
                        'Ventas registradas', formato_money_cols=['precio_unitario', 'total'])


# ==============================================================
#  📝 REGISTRO DE GASTOS
# ==============================================================

def _tab_gastos():
    st.caption('🧪 Registro de gastos — simulación en memoria.')

    df_prov = _df('proveedores')
    nombres_prov = df_prov['nombre'].tolist() if not df_prov.empty else []
    categorias_gasto = ['Alquiler', 'Sueldos', 'Servicios', 'Insumos', 'Impuestos', 'Marketing', 'Otros']

    with st.form('pyme_form_gastos', clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            fecha = st.date_input('Fecha', value=date.today(), key='g_fecha')
        with c2:
            categoria = st.selectbox('Categoría', categorias_gasto, key='g_categoria')
        with c3:
            monto = st.number_input('Monto', min_value=0.0, step=100.0, key='g_monto')
        proveedor = _selector_o_texto('Proveedor (opcional)', nombres_prov, 'g_proveedor', 'Nombre del proveedor')
        descripcion = st.text_input('Descripción', key='g_desc', placeholder='Ej: Compra de insumos de oficina')

        if st.form_submit_button('➕ Registrar gasto', use_container_width=True, type='primary'):
            if monto > 0:
                _agregar('gastos', {
                    'fecha': str(fecha), 'categoria': categoria, 'proveedor': proveedor or '',
                    'monto': monto, 'descripcion': descripcion,
                })
                st.success('Gasto registrado.')
                st.rerun()
            else:
                st.warning('El monto debe ser mayor a 0.')

    df = _df('gastos')
    if df.empty:
        st.info('Todavía no hay gastos cargados.')
        return

    df['monto'] = pd.to_numeric(df['monto'], errors='coerce').fillna(0)
    total_gastado = df['monto'].sum()
    gasto_prom = df['monto'].mean()
    cat_top = df.groupby('categoria')['monto'].sum().idxmax()

    _kpi_row([
        ('Gastos totales', _fmt_money(total_gastado), f'{len(df)} gastos registrados', '#f85149'),
        ('Gasto promedio', _fmt_money(gasto_prom), 'Por registro', '#f0883e'),
        ('Categoría principal', cat_top, 'Mayor gasto acumulado', '#e3b341'),
        ('Proveedores con gasto', str(df.loc[df['proveedor'] != '', 'proveedor'].nunique()), 'Distintos', '#3a7bd5'),
    ])

    resumen_cat = df.groupby('categoria')['monto'].sum().sort_values(ascending=False)
    st.bar_chart(resumen_cat, height=260)

    _tabla_con_borrado('gastos', ['id', 'fecha', 'categoria', 'proveedor', 'monto', 'descripcion'],
                        'Gastos registrados', formato_money_cols=['monto'])


# ==============================================================
#  📝 REGISTRO DE INVENTARIOS
# ==============================================================

def _tab_inventario():
    st.caption('🧪 Registro de inventarios — simulación en memoria. Los cambios de precio y stock quedan reflejados en "Variación de productos".')

    with st.form('pyme_form_inventario', clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            producto = st.text_input('Producto', key='i_producto', placeholder='Ej: Notebook 15" i5')
        with c2:
            categoria = st.text_input('Categoría', key='i_categoria', placeholder='Ej: Informática')
        c3, c4, c5, c6 = st.columns(4)
        with c3:
            stock_actual = st.number_input('Stock actual', min_value=0, step=1, key='i_stock')
        with c4:
            stock_minimo = st.number_input('Stock mínimo', min_value=0, step=1, key='i_stockmin')
        with c5:
            precio_costo = st.number_input('Precio costo', min_value=0.0, step=100.0, key='i_costo')
        with c6:
            precio_venta = st.number_input('Precio venta', min_value=0.0, step=100.0, key='i_venta')

        if st.form_submit_button('➕ Agregar producto', use_container_width=True, type='primary'):
            if producto:
                _agregar('inventario', {
                    'producto': producto, 'categoria': categoria,
                    'stock_actual': int(stock_actual), 'stock_minimo': int(stock_minimo),
                    'precio_costo': precio_costo, 'precio_venta': precio_venta,
                })
                st.success('Producto agregado.')
                st.rerun()
            else:
                st.warning('El nombre del producto es obligatorio.')

    df = _df('inventario')
    if df.empty:
        st.info('Todavía no hay productos cargados.')
        return

    for c in ['stock_actual', 'stock_minimo', 'precio_costo', 'precio_venta']:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)

    valor_costo = (df['stock_actual'] * df['precio_costo']).sum()
    valor_venta = (df['stock_actual'] * df['precio_venta']).sum()
    n_bajo_stock = int((df['stock_actual'] <= df['stock_minimo']).sum())

    _kpi_row([
        ('Productos', str(len(df)), 'Total en catálogo', '#3a7bd5'),
        ('Valor a costo', _fmt_money(valor_costo), 'Inventario valorizado', '#e3b341'),
        ('Valor a venta', _fmt_money(valor_venta), 'Potencial de venta', '#3fb950'),
        ('Bajo stock mínimo', str(n_bajo_stock), 'Requieren reposición', '#f85149' if n_bajo_stock else '#6b7d9a'),
    ])

    if n_bajo_stock:
        st.warning(f'⚠️ Hay {n_bajo_stock} producto(s) en o por debajo del stock mínimo.')

    def _color_stock(row):
        if row['stock_actual'] <= row['stock_minimo']:
            return ['background-color:#2a0a0a;color:#f85149;font-weight:600'] * len(row)
        return [''] * len(row)

    df_show = df[['id', 'producto', 'categoria', 'stock_actual', 'stock_minimo', 'precio_costo', 'precio_venta']].copy()
    styled = (df_show.drop(columns=['id']).style
              .apply(_color_stock, axis=1)
              .format({'precio_costo': _fmt_money, 'precio_venta': _fmt_money}))
    st.markdown('<div class="sec-title">Catálogo de productos</div>', unsafe_allow_html=True)
    st.dataframe(styled, use_container_width=True, hide_index=True, height=min(420, len(df_show) * 38 + 45))

    with st.expander('✏️ Ajustar stock o precio de un producto'):
        opciones = {f"#{r['id']} · {r['producto']}": r['id'] for r in df.to_dict('records')}
        if opciones:
            sel = st.selectbox('Producto', list(opciones.keys()), key='inv_ajuste_sel')
            row_id = opciones[sel]
            row = df.loc[df['id'] == row_id].iloc[0]

            ca1, ca2 = st.columns(2)
            with ca1:
                st.markdown('##### 📦 Ajustar stock')
                tipo_mov = st.selectbox('Tipo de movimiento', ['Entrada', 'Salida'], key='inv_tipo_mov')
                cantidad_mov = st.number_input('Cantidad', min_value=1, step=1, value=1, key='inv_cant_mov')
                if st.button('Aplicar movimiento de stock', key='inv_aplicar_stock'):
                    delta = cantidad_mov if tipo_mov == 'Entrada' else -cantidad_mov
                    nuevo_stock = max(0, int(row['stock_actual']) + delta)
                    _actualizar('inventario', row_id, {'stock_actual': nuevo_stock})
                    _agregar('movimientos_stock', {
                        'fecha': str(date.today()), 'producto': row['producto'],
                        'tipo': tipo_mov, 'cantidad': int(cantidad_mov), 'nota': 'Ajuste manual',
                    })
                    st.success('Stock actualizado.')
                    st.rerun()

            with ca2:
                st.markdown('##### 💲 Ajustar precio de venta')
                nuevo_precio = st.number_input('Nuevo precio de venta', min_value=0.0, step=100.0,
                                                value=float(row['precio_venta']), key='inv_nuevo_precio')
                if st.button('Aplicar nuevo precio', key='inv_aplicar_precio'):
                    if nuevo_precio != row['precio_venta']:
                        _agregar('historial_precios', {
                            'fecha': str(date.today()), 'producto': row['producto'],
                            'precio_anterior': float(row['precio_venta']), 'precio_nuevo': float(nuevo_precio),
                        })
                        _actualizar('inventario', row_id, {'precio_venta': nuevo_precio})
                        st.success('Precio actualizado. Se registró la variación.')
                        st.rerun()
                    else:
                        st.info('El precio nuevo es igual al actual.')

    with st.expander('🗑️ Eliminar un producto del catálogo'):
        opciones = {f"#{r['id']} · {r['producto']}": r['id'] for r in df.to_dict('records')}
        if opciones:
            sel = st.selectbox('Producto a eliminar', list(opciones.keys()), key='inv_del_sel')
            if st.button('Eliminar producto', key='inv_del_btn'):
                _eliminar('inventario', opciones[sel])
                st.success('Producto eliminado.')
                st.rerun()


# ==============================================================
#  🧭 GESTIÓN DE CLIENTES
# ==============================================================

def _tab_clientes():
    st.caption('🧪 Gestión de clientes — simulación en memoria.')

    with st.form('pyme_form_clientes', clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            nombre = st.text_input('Nombre / Razón social', key='cl_nombre')
        with c2:
            contacto = st.text_input('Persona de contacto', key='cl_contacto')
        c3, c4, c5 = st.columns(3)
        with c3:
            telefono = st.text_input('Teléfono', key='cl_tel')
        with c4:
            email = st.text_input('Email', key='cl_email')
        with c5:
            condicion = st.selectbox('Condición de pago', ['Contado', 'Cuenta corriente'], key='cl_cond')
        limite = st.number_input('Límite de crédito (si aplica)', min_value=0.0, step=1000.0, key='cl_limite')

        if st.form_submit_button('➕ Agregar cliente', use_container_width=True, type='primary'):
            if nombre:
                _agregar('clientes', {
                    'nombre': nombre, 'contacto': contacto, 'telefono': telefono,
                    'email': email, 'condicion_pago': condicion, 'limite_credito': limite,
                })
                st.success('Cliente agregado.')
                st.rerun()
            else:
                st.warning('El nombre es obligatorio.')

    df = _df('clientes')
    if df.empty:
        st.info('Todavía no hay clientes cargados.')
        return

    df_ventas = _df('ventas')
    if not df_ventas.empty:
        df_ventas['total'] = pd.to_numeric(df_ventas['total'], errors='coerce').fillna(0)
        compras_por_cliente = df_ventas.groupby('cliente')['total'].sum()
    else:
        compras_por_cliente = pd.Series(dtype=float)

    df['total_comprado'] = df['nombre'].map(compras_por_cliente).fillna(0)

    _kpi_row([
        ('Clientes activos', str(len(df)), 'Total cargados', '#3a7bd5'),
        ('Cuenta corriente', str(int((df['condicion_pago'] == 'Cuenta corriente').sum())), 'De este tipo', '#e3b341'),
        ('Compras totales', _fmt_money(df['total_comprado'].sum()), 'Histórico simulado', '#3fb950'),
        ('Mejor cliente', df.loc[df['total_comprado'].idxmax(), 'nombre'] if df['total_comprado'].max() > 0 else '-',
         'Por monto comprado', '#bc8cff'),
    ])

    df_show = df[['id', 'nombre', 'contacto', 'telefono', 'email', 'condicion_pago', 'limite_credito', 'total_comprado']].copy()
    df_show['limite_credito'] = df_show['limite_credito'].apply(_fmt_money)
    df_show['total_comprado'] = df_show['total_comprado'].apply(_fmt_money)
    st.markdown('<div class="sec-title">Clientes registrados</div>', unsafe_allow_html=True)
    st.dataframe(df_show.drop(columns=['id']), use_container_width=True, hide_index=True,
                 height=min(420, len(df_show) * 38 + 45))

    with st.expander('🗑️ Eliminar un cliente'):
        opciones = {f"#{r['id']} · {r['nombre']}": r['id'] for r in df.to_dict('records')}
        if opciones:
            sel = st.selectbox('Cliente', list(opciones.keys()), key='cl_del_sel')
            if st.button('Eliminar', key='cl_del_btn'):
                _eliminar('clientes', opciones[sel])
                st.success('Eliminado.')
                st.rerun()


# ==============================================================
#  🧭 GESTIÓN DE PROVEEDORES
# ==============================================================

def _tab_proveedores():
    st.caption('🧪 Gestión de proveedores — simulación en memoria.')

    with st.form('pyme_form_proveedores', clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            nombre = st.text_input('Nombre / Razón social', key='pr_nombre')
        with c2:
            contacto = st.text_input('Persona de contacto', key='pr_contacto')
        c3, c4, c5 = st.columns(3)
        with c3:
            telefono = st.text_input('Teléfono', key='pr_tel')
        with c4:
            email = st.text_input('Email', key='pr_email')
        with c5:
            categoria = st.text_input('Categoría / Rubro', key='pr_categoria')
        condiciones = st.selectbox('Condiciones de pago', ['Contado', '15 días', '30 días', '60 días'], key='pr_cond')

        if st.form_submit_button('➕ Agregar proveedor', use_container_width=True, type='primary'):
            if nombre:
                _agregar('proveedores', {
                    'nombre': nombre, 'contacto': contacto, 'telefono': telefono,
                    'email': email, 'categoria': categoria, 'condiciones_pago': condiciones,
                })
                st.success('Proveedor agregado.')
                st.rerun()
            else:
                st.warning('El nombre es obligatorio.')

    df = _df('proveedores')
    if df.empty:
        st.info('Todavía no hay proveedores cargados.')
        return

    df_gastos = _df('gastos')
    if not df_gastos.empty:
        df_gastos['monto'] = pd.to_numeric(df_gastos['monto'], errors='coerce').fillna(0)
        gastos_por_prov = df_gastos.groupby('proveedor')['monto'].sum()
    else:
        gastos_por_prov = pd.Series(dtype=float)

    df['total_comprado'] = df['nombre'].map(gastos_por_prov).fillna(0)

    _kpi_row([
        ('Proveedores activos', str(len(df)), 'Total cargados', '#3a7bd5'),
        ('Gasto total con proveedores', _fmt_money(df['total_comprado'].sum()), 'Histórico simulado', '#f85149'),
        ('Categorías distintas', str(df['categoria'].nunique()), 'Rubros', '#e3b341'),
        ('Proveedor principal', df.loc[df['total_comprado'].idxmax(), 'nombre'] if df['total_comprado'].max() > 0 else '-',
         'Por monto comprado', '#bc8cff'),
    ])

    df_show = df[['id', 'nombre', 'contacto', 'telefono', 'email', 'categoria', 'condiciones_pago', 'total_comprado']].copy()
    df_show['total_comprado'] = df_show['total_comprado'].apply(_fmt_money)
    st.markdown('<div class="sec-title">Proveedores registrados</div>', unsafe_allow_html=True)
    st.dataframe(df_show.drop(columns=['id']), use_container_width=True, hide_index=True,
                 height=min(420, len(df_show) * 38 + 45))

    with st.expander('🗑️ Eliminar un proveedor'):
        opciones = {f"#{r['id']} · {r['nombre']}": r['id'] for r in df.to_dict('records')}
        if opciones:
            sel = st.selectbox('Proveedor', list(opciones.keys()), key='pr_del_sel')
            if st.button('Eliminar', key='pr_del_btn'):
                _eliminar('proveedores', opciones[sel])
                st.success('Eliminado.')
                st.rerun()


# ==============================================================
#  🧭 CONTROL DE DEUDAS
# ==============================================================

def _tab_deudas():
    st.caption('🧪 Control de deudas — cuentas a cobrar (clientes) y a pagar (proveedores). Simulación en memoria.')

    df_cli = _df('clientes')
    df_prov = _df('proveedores')

    with st.form('pyme_form_deudas', clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            tipo = st.selectbox('Tipo', ['A cobrar', 'A pagar'], key='d_tipo')
        with c2:
            opciones_contraparte = (df_cli['nombre'].tolist() if tipo == 'A cobrar' and not df_cli.empty
                                     else df_prov['nombre'].tolist() if not df_prov.empty else [])
            contraparte = _selector_o_texto('Contraparte', opciones_contraparte, 'd_contra', 'Nombre')
        with c3:
            monto = st.number_input('Monto', min_value=0.0, step=1000.0, key='d_monto')
        c4, c5, c6 = st.columns(3)
        with c4:
            f_emi = st.date_input('Fecha emisión', value=date.today(), key='d_femi')
        with c5:
            f_ven = st.date_input('Fecha vencimiento', value=date.today() + timedelta(days=30), key='d_fven')
        with c6:
            estado = st.selectbox('Estado', ['Pendiente', 'Saldado'], key='d_estado')
        notas = st.text_input('Notas (opcional)', key='d_notas')

        if st.form_submit_button('➕ Registrar deuda', use_container_width=True, type='primary'):
            if contraparte and monto > 0:
                _agregar('deudas', {
                    'tipo': tipo, 'contraparte': contraparte, 'monto': monto,
                    'fecha_emision': str(f_emi), 'fecha_vencimiento': str(f_ven),
                    'estado': estado, 'notas': notas,
                })
                st.success('Deuda registrada.')
                st.rerun()
            else:
                st.warning('Completá contraparte y un monto mayor a 0.')

    df = _df('deudas')
    if df.empty:
        st.info('Todavía no hay cuentas por cobrar/pagar cargadas.')
        return

    df['monto'] = pd.to_numeric(df['monto'], errors='coerce').fillna(0)
    df['fecha_vencimiento_dt'] = pd.to_datetime(df['fecha_vencimiento'], errors='coerce')
    hoy_ts = pd.Timestamp(date.today())
    vencidas = (df['estado'] == 'Pendiente') & (df['fecha_vencimiento_dt'] < hoy_ts)

    cobrar_pend = df.loc[(df['tipo'] == 'A cobrar') & (df['estado'] == 'Pendiente'), 'monto'].sum()
    pagar_pend = df.loc[(df['tipo'] == 'A pagar') & (df['estado'] == 'Pendiente'), 'monto'].sum()

    _kpi_row([
        ('Por cobrar', _fmt_money(cobrar_pend), 'Clientes', '#3fb950'),
        ('Por pagar', _fmt_money(pagar_pend), 'Proveedores', '#f85149'),
        ('Posición neta', _fmt_money(cobrar_pend - pagar_pend), 'Cobrar - Pagar', '#3a7bd5'),
        ('Vencidas sin saldar', str(int(vencidas.sum())), 'Requieren atención', '#f0883e' if vencidas.sum() else '#6b7d9a'),
    ])
    if vencidas.sum():
        st.warning(f'⚠️ Hay {int(vencidas.sum())} cuenta(s) vencida(s) sin saldar.')

    f1, f2 = st.columns(2)
    with f1:
        f_tipo = st.selectbox('Filtrar por tipo', ['Todas', 'A cobrar', 'A pagar'], key='d_f_tipo')
    with f2:
        f_estado = st.selectbox('Filtrar por estado', ['Todos', 'Pendiente', 'Saldado'], key='d_f_estado')

    df_f = df.copy()
    if f_tipo != 'Todas':
        df_f = df_f[df_f['tipo'] == f_tipo]
    if f_estado != 'Todos':
        df_f = df_f[df_f['estado'] == f_estado]

    st.markdown('<div class="sec-title">Cuentas registradas</div>', unsafe_allow_html=True)
    cols_show = ['id', 'tipo', 'contraparte', 'monto', 'fecha_emision', 'fecha_vencimiento', 'estado', 'notas']
    df_show = df_f[cols_show].copy()
    df_show['monto'] = df_show['monto'].apply(_fmt_money)
    st.dataframe(df_show.drop(columns=['id']), use_container_width=True, hide_index=True,
                 height=min(420, len(df_show) * 38 + 45))

    with st.expander('✏️ Marcar como saldada / eliminar'):
        opciones = {f"#{r['id']} · {r['tipo']} · {r['contraparte']} · {_fmt_money(r['monto'])}": r['id']
                    for r in df_f.to_dict('records')}
        if opciones:
            sel = st.selectbox('Cuenta', list(opciones.keys()), key='d_edit_sel')
            row_id = opciones[sel]
            ce1, ce2 = st.columns(2)
            with ce1:
                if st.button('✅ Marcar como Saldado', key='d_saldar_btn'):
                    _actualizar('deudas', row_id, {'estado': 'Saldado'})
                    st.success('Actualizado.')
                    st.rerun()
            with ce2:
                if st.button('🗑️ Eliminar', key='d_del_btn'):
                    _eliminar('deudas', row_id)
                    st.success('Eliminado.')
                    st.rerun()


# ==============================================================
#  📈 MÓDULO DE ESTADÍSTICAS
# ==============================================================

def _tab_estadisticas():
    st.caption('🧪 Estadísticas consolidadas a partir de los datos simulados de ventas, gastos e inventario.')

    df_v = _df('ventas')
    df_g = _df('gastos')
    df_i = _df('inventario')

    if df_v.empty and df_g.empty:
        st.info('Cargá ventas y/o gastos para ver estadísticas.')
        return

    if not df_v.empty:
        df_v['total'] = pd.to_numeric(df_v['total'], errors='coerce').fillna(0)
        df_v['fecha_dt'] = pd.to_datetime(df_v['fecha'], errors='coerce')
    if not df_g.empty:
        df_g['monto'] = pd.to_numeric(df_g['monto'], errors='coerce').fillna(0)
        df_g['fecha_dt'] = pd.to_datetime(df_g['fecha'], errors='coerce')

    total_ventas = df_v['total'].sum() if not df_v.empty else 0
    total_gastos = df_g['monto'].sum() if not df_g.empty else 0
    margen = total_ventas - total_gastos
    producto_top = (df_v.groupby('producto')['cantidad'].sum().idxmax()
                     if not df_v.empty and 'cantidad' in df_v.columns else '-')

    _kpi_row([
        ('Ventas totales', _fmt_money(total_ventas), 'Acumulado simulado', '#3fb950'),
        ('Gastos totales', _fmt_money(total_gastos), 'Acumulado simulado', '#f85149'),
        ('Margen bruto', _fmt_money(margen), 'Ventas - Gastos', '#3fb950' if margen >= 0 else '#f85149'),
        ('Producto más vendido', str(producto_top), 'Por unidades', '#e3b341'),
    ])

    st.markdown('<div class="sec-title">Ventas vs. Gastos por mes</div>', unsafe_allow_html=True)
    piezas = []
    if not df_v.empty:
        mensual_v = df_v.groupby(df_v['fecha_dt'].dt.to_period('M'))['total'].sum()
        piezas.append(mensual_v.rename('Ventas'))
    if not df_g.empty:
        mensual_g = df_g.groupby(df_g['fecha_dt'].dt.to_period('M'))['monto'].sum()
        piezas.append(mensual_g.rename('Gastos'))
    if piezas:
        df_mensual = pd.concat(piezas, axis=1).fillna(0)
        df_mensual.index = df_mensual.index.astype(str)
        st.bar_chart(df_mensual, height=300)

    if not df_v.empty and 'cantidad' in df_v.columns:
        st.markdown('<div class="sec-title">Top 5 productos por unidades vendidas</div>', unsafe_allow_html=True)
        top5 = df_v.groupby('producto')['cantidad'].sum().sort_values(ascending=False).head(5)
        st.bar_chart(top5, height=260)

    if not df_i.empty:
        st.markdown('<div class="sec-title">Valor de inventario por categoría</div>', unsafe_allow_html=True)
        df_i['valor'] = pd.to_numeric(df_i['stock_actual'], errors='coerce').fillna(0) * pd.to_numeric(df_i['precio_venta'], errors='coerce').fillna(0)
        valor_cat = df_i.groupby('categoria')['valor'].sum().sort_values(ascending=False)
        st.bar_chart(valor_cat, height=260)


# ==============================================================
#  📈 REPORTES
# ==============================================================

def _tab_reportes():
    st.caption('🧪 Reportes filtrados por rango de fechas. En esta etapa de simulación se muestran en pantalla; '
               'la exportación a Excel/PDF se agrega cuando se conecte la base de datos.')

    tipo_reporte = st.selectbox('Tipo de reporte', ['Ventas', 'Gastos', 'Cuentas por cobrar/pagar'], key='rep_tipo')

    c1, c2 = st.columns(2)
    with c1:
        f_desde = st.date_input('Desde', value=date.today() - timedelta(days=30), key='rep_desde')
    with c2:
        f_hasta = st.date_input('Hasta', value=date.today(), key='rep_hasta')

    if tipo_reporte == 'Ventas':
        df = _df('ventas')
        col_fecha = 'fecha'
        col_monto = 'total'
    elif tipo_reporte == 'Gastos':
        df = _df('gastos')
        col_fecha = 'fecha'
        col_monto = 'monto'
    else:
        df = _df('deudas')
        col_fecha = 'fecha_emision'
        col_monto = 'monto'

    if df.empty:
        st.info('No hay datos cargados para este reporte todavía.')
        return

    df[col_monto] = pd.to_numeric(df[col_monto], errors='coerce').fillna(0)
    df['_f'] = pd.to_datetime(df[col_fecha], errors='coerce')
    df_f = df[(df['_f'] >= pd.Timestamp(f_desde)) & (df['_f'] <= pd.Timestamp(f_hasta))].drop(columns=['_f'])

    _kpi_row([
        ('Período', f'{f_desde.strftime("%d/%m")} → {f_hasta.strftime("%d/%m")}', tipo_reporte, '#3a7bd5'),
        ('Registros', str(len(df_f)), 'En el período', '#e3b341'),
        ('Total', _fmt_money(df_f[col_monto].sum()), 'Suma del período', '#3fb950'),
        ('Promedio', _fmt_money(df_f[col_monto].mean() if len(df_f) else 0), 'Por registro', '#bc8cff'),
    ])

    df_show = df_f.copy()
    df_show[col_monto] = df_show[col_monto].apply(_fmt_money)
    st.markdown(f'<div class="sec-title">Detalle — {tipo_reporte}</div>', unsafe_allow_html=True)
    st.dataframe(df_show.drop(columns=['id']) if 'id' in df_show.columns else df_show,
                 use_container_width=True, hide_index=True, height=min(450, len(df_show) * 38 + 45))


# ==============================================================
#  📈 VARIACIÓN DE PRODUCTOS
# ==============================================================

def _tab_variacion():
    st.caption('🧪 Variación de precios y movimientos de stock. Se completa a medida que ajustás precios o stock desde "Registro de inventarios".')

    df_hist = _df('historial_precios')
    df_mov = _df('movimientos_stock')

    if df_hist.empty and df_mov.empty:
        st.info('Todavía no hay variaciones registradas. Probá ajustar el precio o el stock de un producto en "Registro de inventarios".')
        return

    if not df_hist.empty:
        df_hist['precio_anterior'] = pd.to_numeric(df_hist['precio_anterior'], errors='coerce').fillna(0)
        df_hist['precio_nuevo'] = pd.to_numeric(df_hist['precio_nuevo'], errors='coerce').fillna(0)
        df_hist['variacion_%'] = ((df_hist['precio_nuevo'] - df_hist['precio_anterior']) /
                                   df_hist['precio_anterior'].replace(0, pd.NA) * 100).fillna(0).round(2)

        _kpi_row([
            ('Cambios de precio', str(len(df_hist)), 'Registrados', '#3a7bd5'),
            ('Mayor suba %', f"{df_hist['variacion_%'].max():+.1f}%" if not df_hist.empty else '-', 'Variación puntual', '#f0883e'),
            ('Mayor baja %', f"{df_hist['variacion_%'].min():+.1f}%" if not df_hist.empty else '-', 'Variación puntual', '#3fb950'),
            ('Productos con cambios', str(df_hist['producto'].nunique()), 'Distintos', '#bc8cff'),
        ])

        st.markdown('<div class="sec-title">Historial de cambios de precio</div>', unsafe_allow_html=True)
        df_show = df_hist[['id', 'fecha', 'producto', 'precio_anterior', 'precio_nuevo', 'variacion_%']].copy()
        df_show['precio_anterior'] = df_show['precio_anterior'].apply(_fmt_money)
        df_show['precio_nuevo'] = df_show['precio_nuevo'].apply(_fmt_money)

        def _color_var(val):
            try:
                v = float(str(val).replace('%', ''))
                return f'color:{"#3fb950" if v >= 0 else "#f85149"};font-weight:700'
            except Exception:
                return ''

        styled = (df_show.drop(columns=['id']).style
                  .format({'variacion_%': '{:+.2f}%'})
                  .applymap(_color_var, subset=['variacion_%'])
                  if hasattr(df_show.style, 'applymap')
                  else df_show.drop(columns=['id']).style.format({'variacion_%': '{:+.2f}%'}))
        st.dataframe(styled, use_container_width=True, hide_index=True, height=min(400, len(df_show) * 38 + 45))

        productos_con_hist = df_hist['producto'].unique().tolist()
        if productos_con_hist:
            prod_sel = st.selectbox('Ver evolución de precio de un producto', productos_con_hist, key='var_prod_sel')
            serie = df_hist[df_hist['producto'] == prod_sel].sort_values('fecha')
            if not serie.empty:
                serie_chart = serie.set_index('fecha')['precio_nuevo']
                st.line_chart(serie_chart, height=260)

    if not df_mov.empty:
        st.markdown('<div class="sec-title">Movimientos de stock</div>', unsafe_allow_html=True)
        df_mov_show = df_mov[['id', 'fecha', 'producto', 'tipo', 'cantidad', 'nota']].sort_values('fecha', ascending=False)
        st.dataframe(df_mov_show.drop(columns=['id']), use_container_width=True, hide_index=True,
                     height=min(350, len(df_mov_show) * 38 + 45))


# ==============================================================
#  NAVEGACIÓN — pills agrupadas en popovers (mismo criterio visual
#  que la barra superior de la app)
# ==============================================================

GRUPOS_NAV = {
    '📝 Registros': {
        'Registro de ventas': 'ventas',
        'Registro de gastos': 'gastos',
        'Registro de inventarios': 'inventario',
    },
    '🧭 Gestión': {
        'Gestión de clientes': 'clientes',
        'Gestión de proveedores': 'proveedores',
        'Control de deudas': 'deudas',
    },
    '📈 Análisis': {
        'Módulo de estadísticas': 'estadisticas',
        'Reportes': 'reportes',
        'Variación de productos': 'variacion',
    },
}

# clave interna -> (label completo, grupo al que pertenece)
_SECCION_A_LABEL = {}
_SECCION_A_GRUPO = {}
for _grupo, _items in GRUPOS_NAV.items():
    for _label, _clave in _items.items():
        _SECCION_A_LABEL[_clave] = _label
        _SECCION_A_GRUPO[_clave] = _grupo

RENDER_SECCION = {
    'ventas': _tab_ventas,
    'gastos': _tab_gastos,
    'inventario': _tab_inventario,
    'clientes': _tab_clientes,
    'proveedores': _tab_proveedores,
    'deudas': _tab_deudas,
    'estadisticas': _tab_estadisticas,
    'reportes': _tab_reportes,
    'variacion': _tab_variacion,
}


def _render_nav_pyme():
    seccion_activa = st.session_state.get('pyme_seccion_activa', 'ventas')
    grupo_activo = _SECCION_A_GRUPO.get(seccion_activa)

    cols = st.columns(len(GRUPOS_NAV))
    for col, (nombre_grupo, items) in zip(cols, GRUPOS_NAV.items()):
        with col:
            cont_key = f'navcont_pyme_{nombre_grupo}'
            es_grupo_activo = (nombre_grupo == grupo_activo)
            label_boton = (f'{nombre_grupo} ▾' if not es_grupo_activo
                            else f'{nombre_grupo}: {_SECCION_A_LABEL[seccion_activa].split(" ", 1)[-1]} ▾')
            with st.container(key=cont_key):
                with st.popover(label_boton, use_container_width=True):
                    st.markdown(
                        f'<div style="font-size:11px;color:#6b7d9a;padding:2px 4px 8px 4px">{nombre_grupo}</div>',
                        unsafe_allow_html=True,
                    )
                    for label, clave in items.items():
                        if st.button(label, use_container_width=True, key=f'pyme_nav_{clave}'):
                            st.session_state['pyme_seccion_activa'] = clave
                            st.rerun()
            if es_grupo_activo:
                st.markdown(f"""
                <style>
                .st-key-{cont_key} button {{
                    background: #0d1117 !important;
                    color: var(--verde-monster) !important;
                    border: 1.5px solid var(--verde-monster) !important;
                    font-weight: 700 !important;
                    box-shadow: 0 0 0 2px rgba(108,194,74,0.15) !important;
                }}
                </style>
                """, unsafe_allow_html=True)


# ==============================================================
#  ENTRY POINT
# ==============================================================

def render_pyme(supabase, user_id, **kwargs):
    """Uso desde app.py:
        from modulo_pyme import render_pyme
        render_pyme(supabase, USER_ID)

    NOTA — modo simulación: por ahora `supabase` y `user_id` no se usan
    para leer/escribir nada; todo el estado vive en st.session_state.
    Cuando se apruebe la parte visual, cada función _agregar/_eliminar/
    _actualizar de este archivo pasa a hablar con Supabase (ver el
    esquema SQL de referencia al final del archivo, comentado)."""
    _init_sim()

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d;border-top:2px solid #3a7bd5;border-radius:14px;
         padding:22px 28px;margin-bottom:18px;">
      <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px">
        <div>
          <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:4px">🏢 Módulo PyMEs</div>
          <div style="font-size:12px;color:#6b7d9a;line-height:1.6">
            Ventas, gastos, inventario, clientes, proveedores, deudas, estadísticas, reportes y
            variación de productos — todo en un solo lugar.
          </div>
        </div>
        <div style="padding:5px 12px;border-radius:20px;font-size:10px;font-weight:700;
             letter-spacing:.6px;text-transform:uppercase;background:rgba(227,179,65,0.12);
             border:1px solid #e3b341;color:#e3b341;white-space:nowrap">
          🧪 Modo simulación — los datos no se guardan
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    _render_nav_pyme()

    seccion_activa = st.session_state.get('pyme_seccion_activa', 'ventas')
    label_activo = _SECCION_A_LABEL.get(seccion_activa, '')
    grupo_activo = _SECCION_A_GRUPO.get(seccion_activa, '')

    st.markdown(
        f'<div style="font-size:12px;color:#6b7d9a;margin:6px 0 14px 0">'
        f'{grupo_activo} <span style="color:#3a4a5f">›</span> '
        f'<span style="color:#e6edf3;font-weight:700">{label_activo}</span></div>',
        unsafe_allow_html=True,
    )

    with st.expander('🔄 Reiniciar datos de ejemplo (simulación)'):
        st.caption('Vuelve a cargar los datos de ejemplo iniciales y descarta todo lo que hayas cargado en esta sesión.')
        if st.button('Reiniciar ahora', key='pyme_reset_btn'):
            for k in list(st.session_state.keys()):
                if k.startswith(SIM_PREFIX):
                    st.session_state.pop(k, None)
            _init_sim()
            st.success('Datos de ejemplo reiniciados.')
            st.rerun()

    RENDER_SECCION[seccion_activa]()


# ==============================================================
#  ESQUEMA SQL DE REFERENCIA — para cuando se conecte Supabase.
#  No se ejecuta desde acá; queda documentado para esa etapa.
# ==============================================================
#
# create table if not exists pyme_ventas (
#     id bigint generated always as identity primary key,
#     user_id uuid not null,
#     fecha date not null default current_date,
#     cliente text, producto text, cantidad int, precio_unitario numeric,
#     total numeric, medio_pago text, creado_en timestamptz default now()
# );
#
# create table if not exists pyme_gastos (
#     id bigint generated always as identity primary key,
#     user_id uuid not null,
#     fecha date not null default current_date,
#     categoria text, proveedor text, monto numeric, descripcion text,
#     creado_en timestamptz default now()
# );
#
# create table if not exists pyme_inventario (
#     id bigint generated always as identity primary key,
#     user_id uuid not null,
#     producto text not null, categoria text,
#     stock_actual int default 0, stock_minimo int default 0,
#     precio_costo numeric, precio_venta numeric,
#     creado_en timestamptz default now()
# );
#
# create table if not exists pyme_clientes (
#     id bigint generated always as identity primary key,
#     user_id uuid not null,
#     nombre text not null, contacto text, telefono text, email text,
#     condicion_pago text, limite_credito numeric,
#     creado_en timestamptz default now()
# );
#
# create table if not exists pyme_proveedores (
#     id bigint generated always as identity primary key,
#     user_id uuid not null,
#     nombre text not null, contacto text, telefono text, email text,
#     categoria text, condiciones_pago text,
#     creado_en timestamptz default now()
# );
#
# create table if not exists pyme_deudas (
#     id bigint generated always as identity primary key,
#     user_id uuid not null,
#     tipo text not null,           -- 'A cobrar' | 'A pagar'
#     contraparte text, monto numeric,
#     fecha_emision date, fecha_vencimiento date,
#     estado text default 'Pendiente', notas text,
#     creado_en timestamptz default now()
# );
#
# create table if not exists pyme_historial_precios (
#     id bigint generated always as identity primary key,
#     user_id uuid not null,
#     fecha date not null default current_date,
#     producto text, precio_anterior numeric, precio_nuevo numeric,
#     creado_en timestamptz default now()
# );
#
# create table if not exists pyme_movimientos_stock (
#     id bigint generated always as identity primary key,
#     user_id uuid not null,
#     fecha date not null default current_date,
#     producto text, tipo text, cantidad int, nota text,
#     creado_en timestamptz default now()
# );
#
# -- Row Level Security: la misma política en las 7 tablas
# -- alter table pyme_x enable row level security;
# -- create policy "usuario ve lo suyo" on pyme_x for all using (auth.uid() = user_id);
