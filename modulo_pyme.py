# ==============================================================
#  MÓDULO PyMEs — v3 (DASHBOARD ÚNICO, MODO SIMULACIÓN, sin base de datos)
#
#  Dashboard con 4 módulos, cada uno accesible con su botón (render_nav_pyme):
#
#     KPIs (arriba)  Caja chica · Bancos/Digital · Stock crítico · Resultado neto del mes
#     A) Registradora exprés   Venta · Compra · Gasto · Cobro · Pago
#     B) Inventario + Calculadora de costos (escandallo / BOM)
#     C) Historial de transacciones (anular / editar)
#     D) Reportes en tiempo real: Estado de Resultados (P&L) + Flujo de Caja
#
#  Todo el estado vive en st.session_state (prefijo "pyme_sim_" para los
#  datos y "pw_" para los widgets). Nada se persiste entre sesiones: es a
#  propósito, para cerrar primero la parte visual/UX y recién después
#  conectar la base de datos.
#
#  Los nombres de campos de productos / transacciones / insumos ya son los
#  del esquema SQL (ver comentario al final), así que el día que se conecte
#  Supabase, solo hay que reemplazar _siguiente_id / _nueva_tx / los
#  updates en memoria por insert/update contra las tablas.
#
#  Atajos de teclado: Enter confirma (formularios y buscador),
#  F2 salta al buscador de productos.
# ==============================================================

import math
from html import escape as _esc
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

SIM_PREFIX = 'pyme_sim_'      # datos simulados
WIDGET_PREFIX = 'pw_'         # keys de widgets (se limpian al reiniciar)

TIPOS_MOV = {
    'SALE':       ('🛒', 'Venta'),
    'PURCHASE':   ('📥', 'Compra'),
    'EXPENSE':    ('💸', 'Gasto'),
    'COLLECTION': ('💰', 'Cobro'),
    'PAYMENT':    ('🏦', 'Pago'),
}
INGRESOS = ('SALE', 'COLLECTION')   # tipos que suman al "monto" visual del historial

C_VERDE, C_ROJO, C_AZUL, C_AMARILLO, C_NARANJA, C_VIOLETA, C_GRIS = (
    '#3fb950', '#f85149', '#3a7bd5', '#e3b341', '#f0883e', '#bc8cff', '#6b7d9a')


def _key(nombre):
    return f'{SIM_PREFIX}{nombre}'


def _s(nombre):
    return st.session_state[_key(nombre)]


# ==============================================================
#  ESTADO SIMULADO — datos de ejemplo
# ==============================================================

def _siguiente_id(nombre):
    k = _key(f'seq_{nombre}')
    st.session_state[k] = st.session_state.get(k, 0) + 1
    return st.session_state[k]


def _seed_inicial():
    """Carga datos de ejemplo (una cafetería/kiosco) para poder probar todo
    sin cargar nada a mano. Se puede reiniciar desde el pie de la pantalla."""
    ss = st.session_state
    ss[_key('medios')] = [
        {'id': 1, 'name': 'Efectivo',               'tipo': 'caja',    'is_active': True},
        {'id': 2, 'name': 'Mercado Pago',           'tipo': 'banco',   'is_active': True},
        {'id': 3, 'name': 'Transferencia Bancaria', 'tipo': 'banco',   'is_active': True},
        {'id': 4, 'name': 'Fiado / Cta Corriente',  'tipo': 'credito', 'is_active': True},
    ]
    ss[_key('seq_medios')] = 4

    ss[_key('insumos')] = [
        {'id': 1, 'name': 'Café molido',    'cost_per_unit': 28000, 'unit_measure': 'kg'},
        {'id': 2, 'name': 'Leche',          'cost_per_unit': 1400,  'unit_measure': 'lt'},
        {'id': 3, 'name': 'Harina 000',     'cost_per_unit': 1100,  'unit_measure': 'kg'},
        {'id': 4, 'name': 'Manteca',        'cost_per_unit': 9000,  'unit_measure': 'kg'},
        {'id': 5, 'name': 'Jamón cocido',   'cost_per_unit': 12000, 'unit_measure': 'kg'},
        {'id': 6, 'name': 'Queso',          'cost_per_unit': 11000, 'unit_measure': 'kg'},
        {'id': 7, 'name': 'Pan de miga',    'cost_per_unit': 300,   'unit_measure': 'unidad'},
    ]
    ss[_key('seq_insumos')] = 7

    def _p(id_, name, stock, minimo, costo, precio, barcode='', receta=None, mo=0.0, margen=40.0):
        return {'id': id_, 'barcode': barcode, 'name': name, 'current_stock': stock,
                'min_stock': minimo, 'unit_cost': float(costo), 'sale_price': float(precio),
                'receta': receta or [], 'mano_obra': float(mo), 'margen': float(margen)}

    productos = [
        _p(1, 'Medialuna', 36, 12, 0, 900,
           receta=[{'insumo_id': 3, 'qty': 0.03}, {'insumo_id': 4, 'qty': 0.01}], mo=120),
        _p(2, 'Tostado J&Q', 15, 6, 0, 4200,
           receta=[{'insumo_id': 7, 'qty': 2}, {'insumo_id': 5, 'qty': 0.05}, {'insumo_id': 6, 'qty': 0.06}], mo=300),
        _p(3, 'Café con leche', 50, 15, 0, 2800,
           receta=[{'insumo_id': 1, 'qty': 0.02}, {'insumo_id': 2, 'qty': 0.15}], mo=150),
        _p(4, 'Alfajor', 30, 10, 700, 1300, barcode='7790001000011'),
        _p(5, 'Gaseosa 500ml', 10, 12, 1100, 2000, barcode='7790001000028'),
        _p(6, 'Agua mineral 500ml', 24, 12, 600, 1400, barcode='7790001000035'),
    ]
    for p in productos:
        _recalcular_costo(p)
    ss[_key('productos')] = productos
    ss[_key('seq_productos')] = 6

    ss[_key('transacciones')] = []
    ss[_key('seq_transacciones')] = 0
    ss[_key('carrito')] = {}
    ss[_key('saldo_caja')] = 60000.0
    ss[_key('saldo_banco')] = 600000.0
    ss[_key('init')] = True

    ahora = datetime.now()
    hoy = date.today()
    # Movimientos de ejemplo (pasan por las mismas funciones que usa la UI)
    _reg_gasto('Alquiler', 'Alquiler del local', 350000, 'Transferencia Bancaria', 'PAID', None, ahora - timedelta(days=2))
    _reg_compra(4, 24, 700, 'Fiado / Cta Corriente', 'PENDING', hoy + timedelta(days=10), ahora - timedelta(days=1))
    _reg_venta({2: 5, 3: 5}, 'Fiado / Cta Corriente', 'PENDING', hoy - timedelta(days=1), 'Oficina García', ahora - timedelta(days=3))
    _reg_venta({3: 2, 1: 4}, 'Efectivo', 'PAID', None, '', ahora - timedelta(days=1, hours=2))
    _reg_venta({3: 1, 1: 2}, 'Efectivo', 'PAID', None, '', ahora - timedelta(hours=5))
    _reg_venta({2: 2, 6: 2}, 'Mercado Pago', 'PAID', None, '', ahora - timedelta(hours=4))
    _reg_venta({5: 3, 4: 3}, 'Efectivo', 'PAID', None, '', ahora - timedelta(hours=3))
    _reg_venta({3: 4, 1: 6}, 'Fiado / Cta Corriente', 'PENDING', hoy + timedelta(days=7), 'Estudio Pérez', ahora - timedelta(hours=2))
    _reg_gasto('Servicios', 'Luz y gas', 18500, 'Efectivo', 'PAID', None, ahora - timedelta(hours=1))


def _init_sim():
    if not st.session_state.get(_key('init')):
        _seed_inicial()


# ==============================================================
#  LECTURA DE ENTIDADES
# ==============================================================

def _producto(pid):
    return next((p for p in _s('productos') if p['id'] == pid), None)


def _insumo(iid):
    return next((i for i in _s('insumos') if i['id'] == iid), None)


def _tx(tx_id):
    return next((t for t in _s('transacciones') if t['id'] == tx_id), None)


def _tipo_medio(nombre):
    m = next((m for m in _s('medios') if m['name'] == nombre), None)
    return m['tipo'] if m else 'banco'


def _medios_activos(incluir_credito=True):
    return [m['name'] for m in _s('medios')
            if m['is_active'] and (incluir_credito or m['tipo'] != 'credito')]


def _costo_receta(prod):
    total = 0.0
    for l in prod.get('receta', []):
        ins = _insumo(l['insumo_id'])
        if ins:
            total += ins['cost_per_unit'] * l['qty']
    return total + float(prod.get('mano_obra') or 0)


def _recalcular_costo(prod):
    """Si el producto tiene receta o mano de obra, su costo es el del escandallo."""
    if prod.get('receta') or prod.get('mano_obra'):
        prod['unit_cost'] = round(_costo_receta(prod), 2)


# ==============================================================
#  OPERACIONES (cada una es el equivalente de un insert/update futuro)
# ==============================================================

def _nueva_tx(tipo, descripcion, monto, medio, estado, vence=None, costo=0.0,
              items=None, cuando=None, liquida_a=None):
    tx = {
        'id': _siguiente_id('transacciones'), 'type': tipo, 'description': descripcion,
        'amount': float(monto), 'cost_amount': float(costo), 'payment_method': medio,
        'status': estado, 'due_date': vence if estado == 'PENDING' else None,
        'created_at': cuando or datetime.now(), 'items': items or [],
        'anulada': False, 'liquidado_por': None, 'liquida_a': liquida_a,
    }
    _s('transacciones').append(tx)
    return tx


def _estado_efectivo(medio, estado):
    """Un medio tipo 'crédito' (fiado) siempre deja el movimiento pendiente."""
    return 'PENDING' if _tipo_medio(medio) == 'credito' else estado


def _reg_venta(carrito, medio, estado, vence, nota='', cuando=None):
    if not carrito:
        return False, 'El ticket está vacío.'
    for pid, qty in carrito.items():
        p = _producto(pid)
        if p is None:
            return False, 'Un producto del ticket ya no existe.'
        if p['current_stock'] < qty:
            return False, f"Stock insuficiente de {p['name']} (hay {p['current_stock']})."
    items, monto, costo = [], 0.0, 0.0
    for pid, qty in carrito.items():
        p = _producto(pid)
        items.append({'product_id': pid, 'name': p['name'], 'quantity': int(qty),
                      'unit_price': p['sale_price'], 'unit_cost': p['unit_cost']})
        monto += qty * p['sale_price']
        costo += qty * p['unit_cost']
        p['current_stock'] -= int(qty)
    desc = ', '.join(f"{i['quantity']}× {i['name']}" for i in items)
    if nota:
        desc += f' — {nota}'
    estado = _estado_efectivo(medio, estado)
    _nueva_tx('SALE', desc, monto, medio, estado, vence, costo, items, cuando)
    return True, f'Venta registrada por {_fmt_money(monto)}.'


def _reg_compra(pid, cantidad, costo_unit, medio, estado, vence, cuando=None):
    p = _producto(pid)
    if p is None:
        return False, 'Producto inexistente.'
    stock_prev = p['current_stock']
    if not p.get('receta') and not p.get('mano_obra'):
        # costo promedio ponderado (los productos con escandallo mantienen su costo de receta)
        total_u = stock_prev + cantidad
        p['unit_cost'] = round((stock_prev * p['unit_cost'] + cantidad * costo_unit) / total_u, 2) if total_u else costo_unit
    p['current_stock'] = stock_prev + int(cantidad)
    items = [{'product_id': pid, 'name': p['name'], 'quantity': int(cantidad),
              'unit_price': 0.0, 'unit_cost': float(costo_unit)}]
    estado = _estado_efectivo(medio, estado)
    _nueva_tx('PURCHASE', f"{int(cantidad)}× {p['name']} (compra)", cantidad * costo_unit,
              medio, estado, vence, 0.0, items, cuando)
    return True, f'Compra registrada por {_fmt_money(cantidad * costo_unit)}.'


def _reg_gasto(categoria, descripcion, monto, medio, estado, vence, cuando=None):
    desc = f'{categoria}: {descripcion}' if descripcion else categoria
    estado = _estado_efectivo(medio, estado)
    _nueva_tx('EXPENSE', desc, monto, medio, estado, vence, 0.0, None, cuando)
    return True, f'Gasto registrado por {_fmt_money(monto)}.'


def _reg_liquidacion(tx_id, medio, cuando=None):
    orig = _tx(tx_id)
    if orig is None or orig['anulada'] or orig['status'] != 'PENDING':
        return False, 'Esa cuenta ya no está pendiente.'
    es_cobro = orig['type'] == 'SALE'
    tipo = 'COLLECTION' if es_cobro else 'PAYMENT'
    nueva = _nueva_tx(tipo, f"{'Cobro' if es_cobro else 'Pago'} de #{orig['id']} · {orig['description']}",
                      orig['amount'], medio, 'PAID', None, 0.0, None, cuando, liquida_a=orig['id'])
    orig['status'] = 'PAID'
    orig['liquidado_por'] = nueva['id']
    return True, f"{'Cobro' if es_cobro else 'Pago'} registrado por {_fmt_money(orig['amount'])}."


def _anular(tx_id):
    t = _tx(tx_id)
    if t is None or t['anulada']:
        return False, 'La operación no existe o ya está anulada.'
    if t['liquidado_por']:
        return False, f"Primero anulá el cobro/pago #{t['liquidado_por']} que la liquidó."
    if t['type'] == 'SALE':
        for it in t['items']:
            p = _producto(it['product_id'])
            if p:
                p['current_stock'] += it['quantity']
    elif t['type'] == 'PURCHASE':
        for it in t['items']:
            p = _producto(it['product_id'])
            if p:
                p['current_stock'] = max(0, p['current_stock'] - it['quantity'])
    elif t['type'] in ('COLLECTION', 'PAYMENT'):
        orig = _tx(t['liquida_a'])
        if orig:
            orig['status'] = 'PENDING'
            orig['liquidado_por'] = None
    t['anulada'] = True
    return True, f"Operación #{tx_id} anulada. El stock y la caja se ajustaron."


# ==============================================================
#  CÁLCULOS: caja, cuentas, resultados
# ==============================================================

def _movimientos_caja():
    """[(medio, monto con signo)] de todo lo que realmente movió plata."""
    out = []
    for t in _s('transacciones'):
        if t['anulada']:
            continue
        tp, pagado, liq = t['type'], t['status'] == 'PAID', t['liquidado_por']
        if tp == 'COLLECTION':
            out.append((t['payment_method'], t['amount']))
        elif tp == 'PAYMENT':
            out.append((t['payment_method'], -t['amount']))
        elif tp == 'SALE' and pagado and not liq:
            out.append((t['payment_method'], t['amount']))
        elif tp in ('PURCHASE', 'EXPENSE') and pagado and not liq:
            out.append((t['payment_method'], -t['amount']))
    return out


def _saldos():
    caja, banco = _s('saldo_caja'), _s('saldo_banco')
    for medio, monto in _movimientos_caja():
        tipo = _tipo_medio(medio)
        if tipo == 'caja':
            caja += monto
        elif tipo == 'banco':
            banco += monto
    return caja, banco


def _por_cobrar():
    return [t for t in _s('transacciones') if t['type'] == 'SALE' and t['status'] == 'PENDING' and not t['anulada']]


def _por_pagar():
    return [t for t in _s('transacciones') if t['type'] in ('PURCHASE', 'EXPENSE') and t['status'] == 'PENDING' and not t['anulada']]


def _vencida(t):
    return bool(t['due_date']) and t['due_date'] < date.today()


def _rango_periodo(opcion):
    hoy = date.today()
    return {
        'Hoy': (hoy, hoy),
        '7 días': (hoy - timedelta(days=6), hoy),
        'Mes actual': (hoy.replace(day=1), hoy),
        'Todo': (None, None),
    }[opcion]


def _en_periodo(t, desde, hasta):
    d = t['created_at'].date()
    return (desde is None or d >= desde) and (hasta is None or d <= hasta)


def _pyl(desde, hasta):
    """(ventas, costo de ventas, gastos operativos) — criterio devengado."""
    ventas = cogs = gastos = 0.0
    for t in _s('transacciones'):
        if t['anulada'] or not _en_periodo(t, desde, hasta):
            continue
        if t['type'] == 'SALE':
            ventas += t['amount']
            cogs += t['cost_amount']
        elif t['type'] == 'EXPENSE':
            gastos += t['amount']
    return ventas, cogs, gastos


def _top_vendidos(n=8):
    unidades = {}
    for t in _s('transacciones'):
        if t['type'] == 'SALE' and not t['anulada']:
            for it in t['items']:
                unidades[it['product_id']] = unidades.get(it['product_id'], 0) + it['quantity']
    prods = sorted(_s('productos'), key=lambda p: (-unidades.get(p['id'], 0), p['name']))
    return prods[:n]


# ==============================================================
#  HELPERS DE UI
# ==============================================================

def _fmt_money(v):
    try:
        v = float(v)
    except Exception:
        return '$0'
    signo = '-' if v < 0 else ''
    return f'{signo}${abs(v):,.0f}'.replace(',', '.')


def _fmt_fecha(dt):
    return dt.strftime('%d/%m %H:%M')


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


def _titulo(texto):
    st.markdown(f'<div class="sec-title">{texto}</div>', unsafe_allow_html=True)


def _flash(msg, kind='success'):
    st.session_state['pw_flash'] = (kind, msg)


def _mostrar_flash():
    f = st.session_state.pop('pw_flash', None)
    if not f:
        return
    kind, msg = f
    if kind == 'success':
        st.toast(msg, icon='✅')
    elif kind == 'warning':
        st.warning(msg)
    else:
        st.error(msg)


def _fila_html(label, valor, color='#e6edf3', fuerte=False, tenue=False, linea=False):
    peso = 700 if fuerte else 500
    col_label = C_GRIS if tenue else '#c9d1d9'
    borde = 'border-top:1px solid #21262d;margin-top:4px;padding-top:8px;' if linea else ''
    return (f'<div style="display:flex;justify-content:space-between;padding:4px 2px;{borde}">'
            f'<span style="color:{col_label};font-size:13px;font-weight:{peso}">{label}</span>'
            f'<span style="color:{color};font-size:{15 if fuerte else 13}px;font-weight:{peso}">{valor}</span></div>')


def _etiqueta_pendiente(t):
    venc = ''
    if t['due_date']:
        venc = f" · vence {t['due_date'].strftime('%d/%m')}" + (' ⚠️ VENCIDA' if _vencida(t) else '')
    return f"#{t['id']} · {t['description'][:45]} · {_fmt_money(t['amount'])}{venc}"


# ==============================================================
#  CALLBACKS (se ejecutan antes del rerun)
# ==============================================================

def _cart_add(pid, n=1):
    carrito = _s('carrito')
    p = _producto(pid)
    if not p:
        return
    if carrito.get(pid, 0) + n > p['current_stock']:
        st.toast(f"Sin stock suficiente de {p['name']} (hay {p['current_stock']}).", icon='⚠️')
        return
    carrito[pid] = carrito.get(pid, 0) + n
    if carrito[pid] <= 0:
        carrito.pop(pid, None)


def _cart_quitar(pid):
    _s('carrito').pop(pid, None)


def _cart_vaciar():
    st.session_state[_key('carrito')] = {}


def _on_busqueda():
    """Enter en el buscador: código de barras exacto o única coincidencia → agrega al ticket."""
    q = (st.session_state.get('pw_busq') or '').strip()
    if not q:
        return
    prods = _s('productos')
    hit = [p for p in prods if p['barcode'] and p['barcode'] == q]
    if not hit:
        coinc = [p for p in prods if q.lower() in p['name'].lower()]
        if len(coinc) == 1:
            hit = coinc
    if hit:
        _cart_add(hit[0]['id'])
        st.session_state['pw_busq'] = ''


def _bom_quitar(pid, idx):
    p = _producto(pid)
    if p and 0 <= idx < len(p['receta']):
        p['receta'].pop(idx)
        _recalcular_costo(p)


def _bom_agregar(pid, key_ins, key_qty):
    p = _producto(pid)
    iid = st.session_state.get(key_ins)
    qty = float(st.session_state.get(key_qty) or 0)
    if not p or iid is None:
        return
    if qty <= 0:
        st.toast('Ingresá una cantidad mayor a 0.', icon='⚠️')
        return
    for l in p['receta']:
        if l['insumo_id'] == iid:
            l['qty'] += qty
            break
    else:
        p['receta'].append({'insumo_id': iid, 'qty': qty})
    _recalcular_costo(p)


# ==============================================================
#  HEADER — KPIs
# ==============================================================

def _kpis_header():
    caja, banco = _saldos()
    productos = _s('productos')
    bajos = [p for p in productos if p['current_stock'] < p['min_stock']]
    sin_stock = [p for p in productos if p['current_stock'] <= 0]
    hoy = date.today()
    v, c, g = _pyl(hoy.replace(day=1), hoy)
    neto = v - c - g

    _kpi_row([
        ('💵 Caja chica', _fmt_money(caja), 'Efectivo disponible', C_VERDE if caja >= 0 else C_ROJO),
        ('🏦 Bancos / Digital', _fmt_money(banco), 'Mercado Pago + transferencias', C_AZUL if banco >= 0 else C_ROJO),
        ('📦 Stock crítico', str(len(bajos)), f'{len(sin_stock)} sin stock' if bajos else 'Todo en orden',
         C_ROJO if bajos else C_GRIS),
        ('📊 Resultado neto del mes', _fmt_money(neto), f"Ventas {_fmt_money(v)}", C_VERDE if neto >= 0 else C_ROJO),
    ])


# ==============================================================
#  MÓDULO A — REGISTRADORA EXPRÉS
# ==============================================================

def _form_venta():
    izq, der = st.columns([1, 1], gap='medium')
    with izq:
        _venta_busqueda()
    with der:
        _venta_ticket()


def _venta_busqueda():
    productos = _s('productos')

    st.text_input('Buscar producto o código de barras (F2)', key='pw_busq',
                  placeholder='Escaneá o escribí y presioná Enter', on_change=_on_busqueda)
    q = (st.session_state.get('pw_busq') or '').strip().lower()
    if q:
        res = [p for p in productos if q in p['name'].lower() or (p['barcode'] and q in p['barcode'])][:6]
        if res:
            cols = st.columns(min(3, len(res)))
            for i, p in enumerate(res):
                with cols[i % len(cols)]:
                    st.button(f"{p['name']} · {_fmt_money(p['sale_price'])}", key=f"pw_r_{p['id']}",
                              use_container_width=True, disabled=p['current_stock'] <= 0,
                              on_click=_cart_add, args=(p['id'],))
        else:
            st.caption('Sin coincidencias.')

    st.caption('⚡ Venta rápida — 1 toque = 1 unidad')
    top = _top_vendidos(9)
    with st.container(key='pw_quick'):
        cols = st.columns(3)
        for i, p in enumerate(top):
            with cols[i % 3]:
                st.button(f"{p['name']} · {_fmt_money(p['sale_price'])}", key=f"pw_q_{p['id']}",
                          use_container_width=True, disabled=p['current_stock'] <= 0,
                          on_click=_cart_add, args=(p['id'],),
                          help=f"Stock: {p['current_stock']}")



def _venta_ticket():
    carrito = _s('carrito')

    _titulo('🧾 Ticket actual')
    if not carrito:
        st.caption('Tocá un producto para agregarlo al ticket.')
        total = 0.0
    else:
        total = 0.0
        for pid, qty in list(carrito.items()):
            p = _producto(pid)
            if p is None:
                continue
            sub = qty * p['sale_price']
            total += sub
            c1, c2, c3, c4 = st.columns([5, 1, 1, 1])
            with c1:
                st.markdown(f"**{qty}×** {_esc(p['name'])} "
                            f"<span style='color:{C_GRIS};float:right'>{_fmt_money(sub)}</span>",
                            unsafe_allow_html=True)
            with c2:
                st.button('➖', key=f'pw_m_{pid}', on_click=_cart_add, args=(pid, -1))
            with c3:
                st.button('➕', key=f'pw_p_{pid}', on_click=_cart_add, args=(pid, 1))
            with c4:
                st.button('✕', key=f'pw_x_{pid}', on_click=_cart_quitar, args=(pid,))
        st.markdown(
            f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f'border-top:1px solid #21262d;margin-top:6px;padding-top:8px">'
            f'<span style="color:{C_GRIS};font-size:12px;text-transform:uppercase;letter-spacing:.6px">Total</span>'
            f'<span style="font-size:26px;font-weight:800;color:#e6edf3">{_fmt_money(total)}</span></div>',
            unsafe_allow_html=True)
        st.button('🗑️ Vaciar ticket', key='pw_vaciar', on_click=_cart_vaciar)

    with st.form('pw_form_venta', clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            medio = st.selectbox('Medio de pago', _medios_activos(), key='pw_v_medio')
        with c2:
            estado = st.radio('Estado', ['Pagado', 'Pendiente'], horizontal=True, key='pw_v_estado')
        c3, c4 = st.columns(2)
        with c3:
            nota = st.text_input('Cliente / nota (opcional)', key='pw_v_nota')
        with c4:
            vence = st.date_input('Vence (si queda pendiente)', value=date.today() + timedelta(days=15), key='pw_v_vence')
        enviar = st.form_submit_button(
            f'✅ Confirmar venta · {_fmt_money(total)}' if carrito else '✅ Confirmar venta',
            type='primary', use_container_width=True, disabled=not carrito)

    if enviar:
        ok, msg = _reg_venta(dict(carrito), medio, 'PAID' if estado == 'Pagado' else 'PENDING', vence, nota.strip())
        if ok:
            st.session_state[_key('carrito')] = {}
            if _tipo_medio(medio) == 'credito' or estado == 'Pendiente':
                msg += ' Quedó pendiente de cobro.'
            _flash(msg)
            st.rerun()
        else:
            st.error(msg)


def _form_compra():
    productos = _s('productos')
    if not productos:
        st.info('Primero creá un producto en Inventario.')
        return
    opciones = {f"{p['name']} (stock {p['current_stock']})": p['id'] for p in productos}
    sel = st.selectbox('Producto', list(opciones), key='pw_c_prod')
    pid = opciones[sel]
    p = _producto(pid)

    with st.form('pw_form_compra', clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            cantidad = st.number_input('Cantidad', min_value=1, step=1, value=1, key='pw_c_qty')
        with c2:
            costo = st.number_input('Costo unitario', min_value=0.0, step=10.0,
                                    value=float(p['unit_cost']), key=f'pw_c_costo_{pid}')
        c3, c4, c5 = st.columns(3)
        with c3:
            medio = st.selectbox('Medio de pago', _medios_activos(), key='pw_c_medio')
        with c4:
            estado = st.radio('Estado', ['Pagado', 'Pendiente'], horizontal=True, key='pw_c_estado')
        with c5:
            vence = st.date_input('Vence (si queda pendiente)', value=date.today() + timedelta(days=15), key='pw_c_vence')
        enviar = st.form_submit_button('📥 Registrar compra', type='primary', use_container_width=True)
    st.caption('Suma stock y recalcula el costo del producto (promedio ponderado).')

    if enviar:
        ok, msg = _reg_compra(pid, int(cantidad), float(costo), medio,
                              'PAID' if estado == 'Pagado' else 'PENDING', vence)
        _flash(msg)
        st.rerun()


def _form_gasto():
    categorias = ['Alquiler', 'Sueldos', 'Servicios', 'Impuestos', 'Marketing', 'Mantenimiento', 'Otros']
    with st.form('pw_form_gasto', clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            categoria = st.selectbox('Categoría', categorias, key='pw_g_cat')
        with c2:
            monto = st.number_input('Monto', min_value=0.0, step=100.0, key='pw_g_monto')
        descripcion = st.text_input('Descripción', key='pw_g_desc', placeholder='Ej: Factura de luz')
        c3, c4, c5 = st.columns(3)
        with c3:
            medio = st.selectbox('Medio de pago', _medios_activos(), key='pw_g_medio')
        with c4:
            estado = st.radio('Estado', ['Pagado', 'Pendiente'], horizontal=True, key='pw_g_estado')
        with c5:
            vence = st.date_input('Vence (si queda pendiente)', value=date.today() + timedelta(days=15), key='pw_g_vence')
        enviar = st.form_submit_button('💸 Registrar gasto', type='primary', use_container_width=True)

    if enviar:
        if monto <= 0:
            st.warning('El monto debe ser mayor a 0.')
        else:
            ok, msg = _reg_gasto(categoria, descripcion.strip(), float(monto), medio,
                                 'PAID' if estado == 'Pagado' else 'PENDING', vence)
            _flash(msg)
            st.rerun()


def _form_liquidacion(es_cobro):
    pend = _por_cobrar() if es_cobro else _por_pagar()
    sufijo = 'cobro' if es_cobro else 'pago'
    if not pend:
        st.info('No hay cuentas por cobrar pendientes. 🎉' if es_cobro else 'No hay cuentas por pagar pendientes. 🎉')
        return
    pend = sorted(pend, key=lambda t: (t['due_date'] is None, t['due_date'] or date.max))
    opciones = {_etiqueta_pendiente(t): t['id'] for t in pend}
    sel = st.selectbox('Cuenta por cobrar' if es_cobro else 'Cuenta por pagar', list(opciones), key=f'pw_l_sel_{sufijo}')
    tx_id = opciones[sel]
    with st.form(f'pw_form_liq_{sufijo}', clear_on_submit=True):
        medio = st.selectbox('Medio de cobro' if es_cobro else 'Medio de pago',
                             _medios_activos(incluir_credito=False), key=f'pw_l_medio_{sufijo}')
        enviar = st.form_submit_button('💰 Registrar cobro' if es_cobro else '🏦 Registrar pago',
                                       type='primary', use_container_width=True)
    if enviar:
        ok, msg = _reg_liquidacion(tx_id, medio)
        _flash(msg, 'success' if ok else 'warning')
        st.rerun()


def _modulo_a():
    with st.container(border=True):
        _titulo('⚡ A · Registradora exprés')
        tipo = st.radio('Tipo de movimiento', list(TIPOS_MOV), key='pw_tipo_mov', horizontal=True,
                        format_func=lambda k: f'{TIPOS_MOV[k][0]} {TIPOS_MOV[k][1]}',
                        label_visibility='collapsed')
        if tipo == 'SALE':
            _form_venta()
        elif tipo == 'PURCHASE':
            _form_compra()
        elif tipo == 'EXPENSE':
            _form_gasto()
        elif tipo == 'COLLECTION':
            _form_liquidacion(True)
        else:
            _form_liquidacion(False)


# ==============================================================
#  MÓDULO B — INVENTARIO + CALCULADORA DE COSTOS
# ==============================================================

def _bloque_catalogo():
    productos = _s('productos')
    filtro = st.text_input('Filtrar catálogo', key='pw_inv_filtro', placeholder='Nombre o código…',
                           label_visibility='collapsed')
    f = filtro.strip().lower()
    vistos = [p for p in productos if not f or f in p['name'].lower() or (p['barcode'] and f in p['barcode'])]
    if not vistos:
        st.info('Todavía no hay productos.' if not productos else 'Sin resultados para ese filtro.')
        return
    filas = []
    for p in vistos:
        margen = (p['sale_price'] - p['unit_cost']) / p['sale_price'] * 100 if p['sale_price'] else 0
        filas.append({'Código': p['barcode'] or '—', 'Producto': p['name'], 'Stock': p['current_stock'],
                      'Mínimo': p['min_stock'], 'Costo': p['unit_cost'], 'Precio': p['sale_price'],
                      'Margen': margen})
    df = pd.DataFrame(filas)

    def _rojo(row):
        if row['Stock'] < row['Mínimo']:
            return ['background-color:#2a0a0a;color:#f85149;font-weight:600'] * len(row)
        return [''] * len(row)

    styled = (df.style.apply(_rojo, axis=1)
              .format({'Costo': _fmt_money, 'Precio': _fmt_money, 'Margen': '{:.0f}%'}))
    st.dataframe(styled, use_container_width=True, hide_index=True, height=min(320, len(df) * 36 + 42))
    n = sum(1 for p in productos if p['current_stock'] < p['min_stock'])
    if n:
        st.caption(f'🔴 {n} producto(s) por debajo del stock mínimo.')


def _bloque_nuevo_producto():
    with st.form('pw_form_prod', clear_on_submit=True):
        c1, c2 = st.columns([3, 2])
        with c1:
            nombre = st.text_input('Nombre del producto', key='pw_p_nombre')
        with c2:
            precio = st.number_input('Precio de venta', min_value=0.0, step=100.0, key='pw_p_precio')
        with st.expander('Más datos (opcional)'):
            o1, o2 = st.columns(2)
            with o1:
                barcode = st.text_input('Código de barras', key='pw_p_barcode')
                stock = st.number_input('Stock inicial', min_value=0, step=1, key='pw_p_stock')
            with o2:
                minimo = st.number_input('Stock mínimo', min_value=0, step=1, value=5, key='pw_p_min')
                costo = st.number_input('Costo (si no usás escandallo)', min_value=0.0, step=10.0, key='pw_p_costo')
        enviar = st.form_submit_button('➕ Crear producto', type='primary', use_container_width=True)
    st.caption('Solo pide nombre y precio. El costo se calcula solo con el escandallo o con las compras.')

    if enviar:
        barcode = barcode.strip()
        if not nombre.strip() or precio <= 0:
            st.warning('Completá el nombre y un precio de venta mayor a 0.')
        elif barcode and any(p['barcode'] == barcode for p in _s('productos')):
            st.warning('Ya existe un producto con ese código de barras.')
        else:
            _s('productos').append({
                'id': _siguiente_id('productos'), 'barcode': barcode, 'name': nombre.strip(),
                'current_stock': int(stock), 'min_stock': int(minimo), 'unit_cost': float(costo),
                'sale_price': float(precio), 'receta': [], 'mano_obra': 0.0, 'margen': 40.0,
            })
            _flash(f'Producto «{nombre.strip()}» creado.')
            st.rerun()


def _bloque_ajustes():
    productos = _s('productos')
    if not productos:
        return
    with st.expander('✏️ Ajustar stock / precio / eliminar'):
        opciones = {p['name']: p['id'] for p in productos}
        sel = st.selectbox('Producto', list(opciones), key='pw_adj_sel')
        pid = opciones[sel]
        p = _producto(pid)
        a1, a2 = st.columns(2)
        with a1:
            st.markdown('##### 📦 Stock')
            st.caption(f"Actual: {p['current_stock']} · no mueve la caja")
            mov = st.radio('Movimiento', ['Entrada', 'Salida'], horizontal=True, key='pw_adj_tipo')
            cant = st.number_input('Cantidad', min_value=1, step=1, value=1, key='pw_adj_cant')
            if st.button('Aplicar stock', key='pw_adj_stock_btn'):
                delta = cant if mov == 'Entrada' else -cant
                p['current_stock'] = max(0, p['current_stock'] + int(delta))
                _flash('Stock actualizado.')
                st.rerun()
        with a2:
            st.markdown('##### 💲 Precio y mínimo')
            nuevo_precio = st.number_input('Precio de venta', min_value=0.0, step=100.0,
                                           value=float(p['sale_price']), key=f'pw_adj_precio_{pid}')
            nuevo_min = st.number_input('Stock mínimo', min_value=0, step=1,
                                        value=int(p['min_stock']), key=f'pw_adj_min_{pid}')
            if st.button('Guardar', key='pw_adj_precio_btn'):
                p['sale_price'] = float(nuevo_precio)
                p['min_stock'] = int(nuevo_min)
                _flash('Producto actualizado.')
                st.rerun()
        if st.button('🗑️ Eliminar este producto', key='pw_adj_del_btn'):
            st.session_state[_key('productos')] = [x for x in productos if x['id'] != pid]
            _s('carrito').pop(pid, None)
            _flash('Producto eliminado (el historial conserva su nombre).')
            st.rerun()


def _bloque_escandallo():
    productos = _s('productos')
    insumos = _s('insumos')
    with st.expander('🧮 Calculadora de costos (escandallo / BOM)'):
        if not productos:
            st.info('Creá un producto primero.')
            return
        opciones = {p['name']: p['id'] for p in productos}
        sel = st.selectbox('Producto', list(opciones), key='pw_bom_prod')
        pid = opciones[sel]
        p = _producto(pid)

        st.markdown('**Insumos de la receta**')
        if p['receta']:
            for i, l in enumerate(list(p['receta'])):
                ins = _insumo(l['insumo_id'])
                if not ins:
                    continue
                c1, c2 = st.columns([8, 1])
                with c1:
                    st.markdown(f"{l['qty']:g} {ins['unit_measure']} de **{_esc(ins['name'])}** "
                                f"<span style='color:{C_GRIS};float:right'>{_fmt_money(ins['cost_per_unit'] * l['qty'])}</span>",
                                unsafe_allow_html=True)
                with c2:
                    st.button('✕', key=f'pw_bom_del_{pid}_{i}', on_click=_bom_quitar, args=(pid, i))
        else:
            st.caption('Este producto todavía no tiene insumos cargados.')

        if insumos:
            k_ins, k_qty = f'pw_bom_ins_{pid}', f'pw_bom_qty_{pid}'
            a1, a2, a3 = st.columns([3, 2, 1])
            with a1:
                etiq_ins = {i['id']: f"{i['name']} ({i['unit_measure']})" for i in insumos}
                st.selectbox('Insumo', list(etiq_ins), key=k_ins, format_func=etiq_ins.get)
            with a2:
                st.number_input('Cantidad por unidad', min_value=0.0, step=0.01, format='%.3f', key=k_qty)
            with a3:
                st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)
                st.button('➕', key=f'pw_bom_add_{pid}', on_click=_bom_agregar, args=(pid, k_ins, k_qty))
        else:
            st.caption('Cargá insumos en el bloque «Insumos» de más abajo.')

        m1, m2 = st.columns(2)
        with m1:
            mo = st.number_input('Mano de obra por unidad ($)', min_value=0.0, step=10.0,
                                 value=float(p['mano_obra']), key=f'pw_bom_mo_{pid}')
        with m2:
            mg = st.number_input('Margen deseado sobre el precio (%)', min_value=0.0, max_value=95.0, step=1.0,
                                 value=float(p['margen']), key=f'pw_bom_mg_{pid}')

        suma_insumos = sum((_insumo(l['insumo_id'])['cost_per_unit'] * l['qty'])
                           for l in p['receta'] if _insumo(l['insumo_id']))
        usa_bom = bool(p['receta']) or mo > 0
        costo = suma_insumos + mo if usa_bom else p['unit_cost']
        sugerido = math.ceil(costo / (1 - mg / 100) / 10) * 10 if costo > 0 else 0
        margen_actual = (p['sale_price'] - costo) / p['sale_price'] * 100 if p['sale_price'] else 0

        _kpi_row([
            ('Costo unitario', _fmt_money(costo), 'Insumos + mano de obra' if usa_bom else 'Costo actual', C_AMARILLO),
            ('Precio sugerido', _fmt_money(sugerido), f'Para {mg:.0f}% de margen', C_VERDE),
            ('Precio actual', _fmt_money(p['sale_price']), f'Margen actual {margen_actual:.0f}%',
             C_AZUL if margen_actual >= mg else C_NARANJA),
        ])
        b1, b2 = st.columns(2)
        with b1:
            if st.button('💾 Guardar costo y receta', key=f'pw_bom_save_{pid}', use_container_width=True):
                p['mano_obra'], p['margen'] = float(mo), float(mg)
                _recalcular_costo(p)
                _flash('Costo del producto actualizado.')
                st.rerun()
        with b2:
            if st.button('💲 Usar precio sugerido', key=f'pw_bom_price_{pid}', use_container_width=True,
                         disabled=sugerido <= 0):
                p['mano_obra'], p['margen'] = float(mo), float(mg)
                _recalcular_costo(p)
                p['sale_price'] = float(sugerido)
                _flash(f'Precio de venta actualizado a {_fmt_money(sugerido)}.')
                st.rerun()
        st.caption('Margen calculado sobre el precio de venta: precio = costo ÷ (1 − margen).')


def _bloque_insumos():
    insumos = _s('insumos')
    with st.expander('🥣 Insumos (materias primas)'):
        if insumos:
            df = pd.DataFrame([{'Insumo': i['name'], 'Unidad': i['unit_measure'],
                                'Costo por unidad': _fmt_money(i['cost_per_unit'])} for i in insumos])
            st.dataframe(df, use_container_width=True, hide_index=True, height=min(260, len(df) * 36 + 42))

            st.markdown('**Actualizar costo de un insumo**')
            u1, u2, u3 = st.columns([3, 2, 2])
            with u1:
                etiq_upd = {i['id']: i['name'] for i in insumos}
                iid = st.selectbox('Insumo', list(etiq_upd), key='pw_ins_upd_sel',
                                   format_func=etiq_upd.get, label_visibility='collapsed')
            with u2:
                nuevo = st.number_input('Nuevo costo', min_value=0.0, step=50.0,
                                        value=float(_insumo(iid)['cost_per_unit']), key=f'pw_ins_upd_{iid}',
                                        label_visibility='collapsed')
            with u3:
                if st.button('Actualizar', key='pw_ins_upd_btn', use_container_width=True):
                    _insumo(iid)['cost_per_unit'] = float(nuevo)
                    for p in _s('productos'):
                        if any(l['insumo_id'] == iid for l in p['receta']):
                            _recalcular_costo(p)
                    _flash('Costo actualizado. Se recalcularon los productos que lo usan.')
                    st.rerun()

        with st.form('pw_form_insumo', clear_on_submit=True):
            n1, n2, n3 = st.columns([3, 2, 2])
            with n1:
                nombre = st.text_input('Nuevo insumo', key='pw_ins_nombre')
            with n2:
                unidad = st.selectbox('Unidad', ['kg', 'gr', 'lt', 'ml', 'unidad'], key='pw_ins_unidad')
            with n3:
                costo = st.number_input('Costo por unidad', min_value=0.0, step=50.0, key='pw_ins_costo')
            if st.form_submit_button('➕ Agregar insumo', use_container_width=True):
                if nombre.strip() and costo > 0:
                    insumos.append({'id': _siguiente_id('insumos'), 'name': nombre.strip(),
                                    'cost_per_unit': float(costo), 'unit_measure': unidad})
                    _flash('Insumo agregado.')
                    st.rerun()
                else:
                    st.warning('Completá el nombre y un costo mayor a 0.')


def _modulo_b():
    with st.container(border=True):
        _titulo('📦 B · Inventario y costos')
        izq, der = st.columns([1, 1], gap='medium')
        with izq:
            _bloque_catalogo()
            _bloque_nuevo_producto()
        with der:
            _bloque_ajustes()
            _bloque_escandallo()
            _bloque_insumos()


# ==============================================================
#  MÓDULO C — HISTORIAL DE TRANSACCIONES
# ==============================================================

def _estado_txt(t):
    if t['anulada']:
        return '❌ Anulada'
    if t['status'] == 'PAID':
        return '✅ Pagado'
    return '⚠️ Pendiente (vencida)' if _vencida(t) else '⏳ Pendiente'


def _modulo_c():
    with st.container(border=True):
        _titulo('🧾 C · Historial de transacciones')
        alcance = st.radio('Mostrar', ['Hoy', 'Últimas 50'], horizontal=True, key='pw_hist_alcance',
                           label_visibility='collapsed')
        todas = sorted(_s('transacciones'), key=lambda t: (t['created_at'], t['id']), reverse=True)
        if alcance == 'Hoy':
            hoy = date.today()
            lista = [t for t in todas if t['created_at'].date() == hoy]
        else:
            lista = todas[:50]

        if not lista:
            st.info('No hay operaciones para mostrar.')
            return

        filas = []
        for t in lista:
            signo = '+' if t['type'] in INGRESOS else '−'
            emoji, nombre = TIPOS_MOV[t['type']]
            filas.append({'#': t['id'], 'Fecha': _fmt_fecha(t['created_at']), 'Tipo': f'{emoji} {nombre}',
                          'Detalle': t['description'], 'Medio': t['payment_method'],
                          'Estado': _estado_txt(t), 'Monto': f"{signo}{_fmt_money(t['amount'])}"})
        st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True,
                     height=min(360, len(filas) * 36 + 42))

        activas = [t for t in lista if not t['anulada']]
        with st.expander('✏️ Editar o anular una operación'):
            if not activas:
                st.caption('No hay operaciones activas en esta vista.')
                return
            opciones = {f"#{t['id']} · {TIPOS_MOV[t['type']][0]} {t['description'][:40]} · {_fmt_money(t['amount'])}": t['id']
                        for t in activas}
            sel = st.selectbox('Operación', list(opciones), key='pw_hist_sel')
            tx_id = opciones[sel]
            t = _tx(tx_id)

            solo_no_credito = t['status'] == 'PAID' and not t['liquidado_por'] or t['type'] in ('COLLECTION', 'PAYMENT')
            medios = _medios_activos(incluir_credito=not solo_no_credito)
            if t['payment_method'] not in medios:
                medios = [t['payment_method']] + medios

            with st.form('pw_form_edit_tx'):
                desc = st.text_input('Descripción', value=t['description'], key=f'pw_e_desc_{tx_id}')
                e1, e2 = st.columns(2)
                with e1:
                    medio = st.selectbox('Medio', medios, index=medios.index(t['payment_method']), key=f'pw_e_medio_{tx_id}')
                with e2:
                    if t['status'] == 'PENDING':
                        vence = st.date_input('Vencimiento', value=t['due_date'] or date.today(), key=f'pw_e_vence_{tx_id}')
                    else:
                        vence = t['due_date']
                        st.caption('Sin vencimiento (ya está pagado).')
                guardar = st.form_submit_button('💾 Guardar cambios', use_container_width=True)
            if guardar:
                t['description'] = desc.strip() or t['description']
                t['payment_method'] = medio
                if t['status'] == 'PENDING':
                    t['due_date'] = vence
                _flash('Operación actualizada.')
                st.rerun()
            st.caption('El monto y los productos no se editan: anulá la operación y volvé a registrarla.')

            if st.button('❌ Anular esta operación', key='pw_hist_anular'):
                ok, msg = _anular(tx_id)
                _flash(msg, 'success' if ok else 'warning')
                st.rerun()


# ==============================================================
#  MÓDULO D — REPORTES FINANCIEROS EN TIEMPO REAL
# ==============================================================

def _modulo_d():
    with st.container(border=True):
        _titulo('📊 D · Reportes financieros')
        periodo = st.radio('Período', ['Hoy', '7 días', 'Mes actual', 'Todo'], horizontal=True,
                           index=2, key='pw_periodo', label_visibility='collapsed')
        desde, hasta = _rango_periodo(periodo)

        ventas, cogs, gastos = _pyl(desde, hasta)
        bruta = ventas - cogs
        neta = bruta - gastos
        margen_neto = (neta / ventas * 100) if ventas else 0

        caja, banco = _saldos()
        cobrar, pagar = _por_cobrar(), _por_pagar()
        t_cobrar, t_pagar = sum(t['amount'] for t in cobrar), sum(t['amount'] for t in pagar)
        disponible = caja + banco
        proyectado = disponible + t_cobrar - t_pagar

        izq, der = st.columns([1, 1], gap='medium')
        with izq:
            st.markdown('**Estado de Resultados (P&L)**')
            st.markdown(
                _fila_html('Ventas totales', _fmt_money(ventas), C_VERDE)
                + _fila_html('(−) Costo de ventas (COGS)', _fmt_money(cogs), C_ROJO, tenue=True)
                + _fila_html('= Utilidad bruta', _fmt_money(bruta), '#e6edf3', fuerte=True, linea=True)
                + _fila_html('(−) Gastos operativos', _fmt_money(gastos), C_ROJO, tenue=True)
                + _fila_html('= Utilidad / Pérdida neta', _fmt_money(neta), C_VERDE if neta >= 0 else C_ROJO,
                             fuerte=True, linea=True)
                + _fila_html('Margen neto', f'{margen_neto:.1f}%', C_GRIS, tenue=True),
                unsafe_allow_html=True)

            if periodo != 'Hoy':
                v_d, g_d = {}, {}
                for t in _s('transacciones'):
                    if t['anulada'] or not _en_periodo(t, desde, hasta):
                        continue
                    d = t['created_at'].date().isoformat()
                    if t['type'] == 'SALE':
                        v_d[d] = v_d.get(d, 0) + t['amount']
                    elif t['type'] == 'EXPENSE':
                        g_d[d] = g_d.get(d, 0) + t['amount']
                if v_d or g_d:
                    st.markdown('<div style="height:10px"></div>**Ventas vs. gastos por día**', unsafe_allow_html=True)
                    df = pd.DataFrame({'Ventas': pd.Series(v_d, dtype=float),
                                       'Gastos': pd.Series(g_d, dtype=float)}).fillna(0).sort_index()
                    st.bar_chart(df, height=220)

        with der:
            st.markdown('**Flujo de Caja** (a hoy)')
            st.markdown(
                _fila_html('Caja chica', _fmt_money(caja), tenue=True)
                + _fila_html('Bancos / Digital', _fmt_money(banco), tenue=True)
                + _fila_html('= Dinero disponible', _fmt_money(disponible), C_AZUL, fuerte=True, linea=True)
                + _fila_html(f'(+) Cuentas por cobrar ({len(cobrar)})', _fmt_money(t_cobrar), C_VERDE, tenue=True)
                + _fila_html(f'(−) Cuentas por pagar ({len(pagar)})', _fmt_money(t_pagar), C_ROJO, tenue=True)
                + _fila_html('= Posición proyectada', _fmt_money(proyectado), C_VERDE if proyectado >= 0 else C_ROJO,
                             fuerte=True, linea=True),
                unsafe_allow_html=True)

            venc = [t for t in cobrar + pagar if _vencida(t)]
            if venc:
                st.warning(f'⚠️ Hay {len(venc)} cuenta(s) vencida(s) sin saldar.')

            pend = sorted(cobrar + pagar, key=lambda t: (t['due_date'] is None, t['due_date'] or date.max))[:6]
            if pend:
                st.markdown('<div style="height:10px"></div>**Próximos vencimientos**', unsafe_allow_html=True)
                df = pd.DataFrame([{
                    '': '⚠️' if _vencida(t) else '',
                    'Tipo': 'Por cobrar' if t['type'] == 'SALE' else 'Por pagar',
                    'Detalle': t['description'][:45],
                    'Vence': t['due_date'].strftime('%d/%m') if t['due_date'] else '—',
                    'Monto': _fmt_money(t['amount']),
                } for t in pend])
                st.dataframe(df, use_container_width=True, hide_index=True, height=min(260, len(df) * 36 + 42))


# ==============================================================
#  CONFIGURACIÓN Y REINICIO
# ==============================================================

def _bloque_config():
    with st.expander('⚙️ Configuración (saldos iniciales y medios de pago)'):
        st.markdown('**Saldos iniciales**')
        s1, s2, s3 = st.columns([2, 2, 1])
        with s1:
            caja0 = st.number_input('Caja chica inicial', min_value=0.0, step=1000.0,
                                    value=float(_s('saldo_caja')), key='pw_cfg_caja')
        with s2:
            banco0 = st.number_input('Bancos / Digital inicial', min_value=0.0, step=1000.0,
                                     value=float(_s('saldo_banco')), key='pw_cfg_banco')
        with s3:
            st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)
            if st.button('Guardar', key='pw_cfg_saldos_btn', use_container_width=True):
                st.session_state[_key('saldo_caja')] = float(caja0)
                st.session_state[_key('saldo_banco')] = float(banco0)
                _flash('Saldos iniciales actualizados.')
                st.rerun()

        st.markdown('**Medios de pago**')
        etiquetas_tipo = {'caja': 'Caja (efectivo)', 'banco': 'Banco / Digital', 'credito': 'Crédito (fiado: queda pendiente)'}
        for m in _s('medios'):
            st.checkbox(f"{m['name']} — {etiquetas_tipo[m['tipo']]}", value=m['is_active'], key=f"pw_cfg_act_{m['id']}")
        if st.button('Guardar medios activos', key='pw_cfg_medios_btn'):
            nuevos = {m['id']: st.session_state.get(f"pw_cfg_act_{m['id']}", m['is_active']) for m in _s('medios')}
            if not any(act for mid, act in nuevos.items() if next(x for x in _s('medios') if x['id'] == mid)['tipo'] != 'credito'):
                st.warning('Dejá activo al menos un medio que no sea de crédito.')
            else:
                for m in _s('medios'):
                    m['is_active'] = nuevos[m['id']]
                _flash('Medios de pago actualizados.')
                st.rerun()

        with st.form('pw_form_medio', clear_on_submit=True):
            n1, n2 = st.columns(2)
            with n1:
                nombre = st.text_input('Nuevo medio de pago', key='pw_cfg_nuevo_nombre', placeholder='Ej: Tarjeta de débito')
            with n2:
                tipo = st.selectbox('Se acredita en', list(etiquetas_tipo), format_func=etiquetas_tipo.get, index=1,
                                    key='pw_cfg_nuevo_tipo')
            if st.form_submit_button('➕ Agregar medio', use_container_width=True):
                if not nombre.strip():
                    st.warning('Escribí un nombre.')
                elif any(m['name'].lower() == nombre.strip().lower() for m in _s('medios')):
                    st.warning('Ya existe un medio con ese nombre.')
                else:
                    _s('medios').append({'id': _siguiente_id('medios'), 'name': nombre.strip(), 'tipo': tipo, 'is_active': True})
                    _flash('Medio de pago agregado.')
                    st.rerun()

    with st.expander('🔄 Reiniciar datos de ejemplo (simulación)'):
        st.caption('Vuelve a cargar los datos de ejemplo y descarta todo lo que hayas cargado en esta sesión.')
        if st.button('Reiniciar ahora', key='pw_reset_btn'):
            for k in list(st.session_state.keys()):
                if k.startswith(SIM_PREFIX) or k.startswith(WIDGET_PREFIX):
                    st.session_state.pop(k, None)
            _init_sim()
            _flash('Datos de ejemplo reiniciados.')
            st.rerun()


# ==============================================================
#  ATAJOS DE TECLADO + ESTILO TÁCTIL
# ==============================================================

def _inyectar_extras():
    st.markdown("""
    <style>
    .st-key-pw_quick button { min-height: 58px; font-weight: 600; }
    div[class*="st-key-pw_"] [data-testid="stRadio"] label { padding: 4px 6px; }
    </style>
    """, unsafe_allow_html=True)
    # F2 → foco en el buscador. Se registra una sola vez sobre el documento padre.
    components.html("""
    <script>
    try {
      const doc = window.parent.document;
      if (!doc.__pymeF2) {
        doc.__pymeF2 = true;
        doc.addEventListener('keydown', function (e) {
          if (e.key === 'F2') {
            const el = doc.querySelector('input[aria-label*="Buscar producto"]');
            if (el) { e.preventDefault(); el.focus(); el.select(); }
          }
        });
      }
    } catch (err) {}
    </script>
    """, height=0)


# ==============================================================
#  NAVEGACIÓN — 4 botones (uno por módulo)
# ==============================================================

SECCIONES = {
    'A': '⚡ Registradora exprés',
    'B': '📦 Inventario y costos',
    'C': '🧾 Historial de transacciones',
    'D': '📊 Reportes financieros',
}
RENDER_SECCION = {'A': _modulo_a, 'B': _modulo_b, 'C': _modulo_c, 'D': _modulo_d}
NAV_KEY = 'pyme_seccion_activa'


def _ir_a(seccion):
    st.session_state[NAV_KEY] = seccion


def render_nav_pyme(columnas=None):
    """Dibuja los 4 botones de navegación del módulo PyMEs.

    - Con `columnas` (lista de 4 columnas creadas en la barra superior de app.py),
      los botones se dibujan ahí, al lado del selector "PyMEs ▾".
    - Sin `columnas`, render_pyme() los dibuja arriba del contenido.
    """
    activa = st.session_state.get(NAV_KEY, 'A')
    cols = columnas if columnas is not None else st.columns(len(SECCIONES))
    st.session_state['_pyme_nav_externa'] = columnas is not None
    for col, (clave, label) in zip(cols, SECCIONES.items()):
        with col:
            cont_key = f'navpyme_{clave}'
            with st.container(key=cont_key):
                st.button(label, key=f'pyme_nav_{clave}', use_container_width=True,
                          on_click=_ir_a, args=(clave,))
            if clave == activa:
                st.markdown(f"""
                <style>
                .st-key-{cont_key} button {{
                    background: #0d1117 !important;
                    color: var(--verde-monster, #6cc24a) !important;
                    border: 1.5px solid var(--verde-monster, #6cc24a) !important;
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

    NOTA — modo simulación: `supabase` y `user_id` todavía no se usan; todo
    vive en st.session_state. Al conectar la base, se reemplazan las
    operaciones _reg_* / _anular / _bom_* / altas de productos e insumos."""
    _init_sim()

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d;border-top:2px solid #3a7bd5;border-radius:14px;
         padding:18px 26px;margin-bottom:16px;">
      <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px">
        <div>
          <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:4px">🏢 Módulo PyMEs</div>
          <div style="font-size:12px;color:#6b7d9a;line-height:1.6">
            Cada venta, compra o gasto impacta al instante en stock, caja y resultados.
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

    _mostrar_flash()
    _kpis_header()

    # Si app.py no dibujó los botones en la barra superior, los dibujamos acá.
    if not st.session_state.pop('_pyme_nav_externa', False):
        render_nav_pyme()

    activa = st.session_state.get(NAV_KEY, 'A')
    if activa not in RENDER_SECCION:
        activa = 'A'
    RENDER_SECCION[activa]()

    _bloque_config()
    _inyectar_extras()


# ==============================================================
#  ESQUEMA SQL DE REFERENCIA — para cuando se conecte Supabase.
#  No se ejecuta desde acá. Es el esquema del prompt original, con los
#  campos extra que usa la simulación (marcados con ★) y user_id + RLS.
# ==============================================================
#
# create table payment_methods (
#     id serial primary key, user_id uuid not null,
#     name varchar(50) not null, is_active boolean default true,
#     tipo text not null default 'banco'        -- ★ 'caja' | 'banco' | 'credito'
# );
#
# create table products (
#     id serial primary key, user_id uuid not null,
#     barcode varchar(50), name varchar(100) not null,
#     current_stock int default 0, min_stock int default 5,
#     unit_cost numeric(12,2) default 0, sale_price numeric(12,2) not null,
#     mano_obra numeric(12,2) default 0,        -- ★ mano de obra por unidad (escandallo)
#     margen numeric(5,2) default 40,           -- ★ margen deseado sobre precio
#     created_at timestamp default now(),
#     unique (user_id, barcode)
# );
#
# create table raw_materials (
#     id serial primary key, user_id uuid not null,
#     name varchar(100) not null, cost_per_unit numeric(12,2) not null, unit_measure varchar(20) not null
# );
#
# create table product_ingredients (
#     id serial primary key,
#     product_id int references products(id) on delete cascade,
#     raw_material_id int references raw_materials(id) on delete cascade,
#     quantity_required numeric(10,3) not null
# );
#
# create type transaction_type as enum ('SALE','PURCHASE','EXPENSE','COLLECTION','PAYMENT');
# create type transaction_status as enum ('PAID','PENDING');
#
# create table transactions (
#     id serial primary key, user_id uuid not null,
#     type transaction_type not null, description varchar(255),
#     amount numeric(12,2) not null, cost_amount numeric(12,2) default 0,
#     payment_method_id int references payment_methods(id),
#     status transaction_status default 'PAID', due_date date,
#     anulada boolean default false,                          -- ★ anulación lógica
#     liquidado_por int references transactions(id),          -- ★ cobro/pago que saldó esta cuenta
#     liquida_a int references transactions(id),              -- ★ cuenta que salda este cobro/pago
#     created_at timestamp default now()
# );
#
# create table transaction_items (
#     id serial primary key,
#     transaction_id int references transactions(id) on delete cascade,
#     product_id int references products(id),
#     product_name varchar(100),                              -- ★ conserva el nombre si se borra el producto
#     quantity int not null, unit_price numeric(12,2) not null, unit_cost numeric(12,2) not null
# );
#
# -- Row Level Security: la misma política en todas las tablas con user_id
# -- alter table <tabla> enable row level security;
# -- create policy "usuario ve lo suyo" on <tabla> for all using (auth.uid() = user_id);
