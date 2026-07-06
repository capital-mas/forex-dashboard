# ============================================================
# finanzas_ui.py
# Interfaz Streamlit del sistema de Finanzas Personales.
#
# Uso desde tu app principal (ej. analizador_cuantitativo_v3.py):
#
#     from finanzas_ui import render_finanzas_personales
#     render_finanzas_personales(supabase_client, user_id)
#
# No maneja login: recibe el client de Supabase y el user_id ya
# autenticados desde afuera.
# ============================================================

from datetime import date

import streamlit as st

import finanzas_data as fd

ACCENT = "#6CC24A"
POS = "#00e676"
NEG = "#ff5252"


# ============================================================
# HELPERS DE FORMATO
# ============================================================

def _money(v: float) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _toast_ok(msg: str) -> None:
    st.success(msg)


def _toast_err(msg: str) -> None:
    st.error(msg)


# ============================================================
# DASHBOARD
# ============================================================

def _render_dashboard(client, user_id: str) -> None:
    st.subheader("📊 Dashboard Financiero")
    if st.button("🔄 Actualizar dashboard", key="fin_dash_refresh"):
        st.cache_data.clear()

    d = fd.obtener_dashboard_data(client, user_id)

    st.markdown("##### 💵 Finanzas del mes")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ingresos", _money(d["ingresos"]))
    c2.metric("Gastos", _money(d["gastos"]))
    c3.metric("Balance", _money(d["balance"]), delta=_money(d["balance"]))
    c4.metric("Tasa de ahorro", d["tasa_ahorro"])

    st.markdown("##### 💳 Deudas")
    c1, c2, c3 = st.columns(3)
    c1.metric("Total deudas activas", _money(d["deudas"]))
    c2.metric("Deuda más alta", d["deuda_max"])
    c3.metric("Próximo vencimiento", d["proximo_vencimiento"])

    st.markdown("##### 📈 Inversiones")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Corto plazo", _money(d["inv_corto"]))
    c2.metric("Largo plazo", _money(d["inv_largo"]))
    c3.metric("Ganancia/Pérdida", _money(d["ganancia"]))
    c4.metric("Rendimiento %", d["rendimiento"])

    st.markdown("##### ⚡ Trading")
    c1, c2, c3 = st.columns(3)
    c1.metric("P&L realizado", _money(d["trading_pnl"]))
    c2.metric("Win rate", d["win_rate"])
    c3.metric("Operaciones abiertas", d["abiertas"])

    st.markdown("##### 🎯 Objetivos de ahorro")
    c1, c2, c3 = st.columns(3)
    c1.metric("Objetivos activos", d["obj_activos"])
    c2.metric("Total ahorrado", _money(d["obj_ahorrado"]))
    c3.metric("Total faltante", _money(d["obj_faltante"]))

    progreso = fd.objetivos_con_progreso(client, user_id)
    if progreso:
        st.markdown("###### Progreso por objetivo")
        for o in progreso:
            st.progress(min(o["pct"], 1.0), text=f"{o['nombre']} — {o['pct'] * 100:.1f}%")


# ============================================================
# INGRESOS
# ============================================================

def _render_ingresos(client, user_id: str) -> None:
    st.subheader("📥 Registrar Ingreso")
    with st.form("form_ingreso", clear_on_submit=True):
        fecha = st.date_input("Fecha *", value=date.today())
        descripcion = st.text_input("Descripción *", placeholder="Ej: Salario mayo…")
        col1, col2 = st.columns(2)
        categoria = col1.selectbox(
            "Categoría *",
            ["", "Salario", "Freelance", "Negocio", "Inversiones", "Alquiler", "Trading", "Regalo", "Otros"],
        )
        cuenta = col2.selectbox("Cuenta", ["Efectivo", "Banco", "Mercado Pago", "Crypto", "Otro"])
        monto = st.number_input("Monto *", min_value=0.0, step=0.01)
        notas = st.text_area("Notas")
        enviado = st.form_submit_button("📥 Registrar Ingreso")

    if enviado:
        if not descripcion or not categoria or not monto:
            _toast_err("⚠️ Completá los campos obligatorios (*)")
            return
        fd.insertar_ingreso(client, user_id, {
            "fecha": fecha.isoformat(), "descripcion": descripcion, "categoria": categoria,
            "monto": monto, "cuenta": cuenta, "notas": notas,
        })
        _toast_ok("✅ Ingreso guardado")

    df = fd.listar_ingresos(client, user_id)
    if not df.empty:
        st.dataframe(df.sort_values("fecha", ascending=False), use_container_width=True, hide_index=True)


# ============================================================
# GASTOS
# ============================================================

SUBCATEGORIAS = {
    "Vivienda": ["Alquiler", "Expensas", "Gas", "Luz", "Agua", "Internet", "Mantenimiento", "Otros"],
    "Alimentación": ["Supermercado", "Verdulería", "Carnicería", "Delivery", "Restaurante", "Café", "Otros"],
    "Transporte": ["Nafta", "SUBE/Colectivo", "Taxi/Uber", "Seguro Auto", "Peajes", "Otros"],
    "Salud": ["Medicamentos", "Consulta médica", "Análisis", "Odontología", "Psicología", "Otros"],
    "Educación": ["Colegio/Uni", "Cursos", "Libros", "Material", "Otros"],
    "Entretenimiento": ["Streaming", "Cine/Teatro", "Salidas", "Viajes", "Deporte", "Otros"],
    "Ropa": ["Ropa", "Calzado", "Accesorios", "Otros"],
    "Tecnología": ["Celular", "Computadora", "Software", "Periféricos", "Otros"],
    "Servicios": ["Teléfono", "Seguro", "Banco (comisiones)", "Otros"],
    "Deudas": ["Cuota préstamo", "Tarjeta de crédito", "Hipoteca", "Otros"],
    "Otros": ["Regalos", "Donaciones", "Sin categoría"],
}


def _render_gastos(client, user_id: str) -> None:
    st.subheader("📤 Registrar Gasto")
    categoria = st.selectbox("Categoría *", [""] + list(SUBCATEGORIAS.keys()), key="gas_cat")
    with st.form("form_gasto", clear_on_submit=True):
        fecha = st.date_input("Fecha *", value=date.today())
        descripcion = st.text_input("Descripción *", placeholder="Ej: Supermercado…")
        subcategoria = st.selectbox("Subcategoría", ["—"] + SUBCATEGORIAS.get(categoria, []))
        col1, col2 = st.columns(2)
        monto = col1.number_input("Monto *", min_value=0.0, step=0.01)
        cuenta = col2.selectbox("Cuenta", ["Efectivo", "Débito", "Crédito", "Mercado Pago", "Otro"])
        notas = st.text_area("Notas")
        enviado = st.form_submit_button("📤 Registrar Gasto")

    if enviado:
        if not descripcion or not categoria or not monto:
            _toast_err("⚠️ Completá los campos obligatorios (*)")
            return
        fd.insertar_gasto(client, user_id, {
            "fecha": fecha.isoformat(), "descripcion": descripcion, "categoria": categoria,
            "subcategoria": subcategoria if subcategoria != "—" else "",
            "monto": monto, "cuenta": cuenta, "notas": notas,
        })
        _toast_ok("✅ Gasto guardado")

    df = fd.listar_gastos(client, user_id)
    if not df.empty:
        st.dataframe(df.sort_values("fecha", ascending=False), use_container_width=True, hide_index=True)


# ============================================================
# DEUDAS
# ============================================================

def _render_deudas(client, user_id: str) -> None:
    st.subheader("💳 Registrar Deuda")
    with st.form("form_deuda", clear_on_submit=True):
        acreedor = st.text_input("Acreedor / Institución *", placeholder="Ej: Banco Nación…")
        col1, col2 = st.columns(2)
        tipo = col1.selectbox(
            "Tipo *",
            ["", "Préstamo Personal", "Tarjeta de Crédito", "Hipoteca", "Auto", "Estudiante", "Familiar", "Otros"],
        )
        estado = col2.selectbox("Estado", ["Activa", "En mora", "Pagada", "Refinanciada"])
        col1, col2 = st.columns(2)
        monto_original = col1.number_input("Monto Original *", min_value=0.0, step=0.01)
        monto_pendiente = col2.number_input("Monto Pendiente *", min_value=0.0, step=0.01)
        col1, col2, col3 = st.columns(3)
        cuotas_totales = col1.number_input("Cuotas Total", min_value=0, step=1)
        cuotas_pagadas = col2.number_input("Cuotas Pagadas", min_value=0, step=1)
        cuota_mensual = col3.number_input("Cuota Mensual", min_value=0.0, step=0.01)
        col1, col2 = st.columns(2)
        tasa_interes = col1.number_input("Tasa Anual %", step=0.01)
        fecha_inicio = col2.date_input("Fecha Inicio *", value=date.today())
        fecha_vencimiento = st.date_input("Fecha Vencimiento *")
        notas = st.text_area("Notas")
        enviado = st.form_submit_button("💳 Registrar Deuda")

    if enviado:
        if not acreedor or not tipo or not monto_original:
            _toast_err("⚠️ Completá los campos obligatorios (*)")
            return
        fd.insertar_deuda(client, user_id, {
            "acreedor": acreedor, "tipo": tipo, "estado": estado,
            "montoOriginal": monto_original, "montoPendiente": monto_pendiente,
            "cuotasTotales": cuotas_totales, "cuotasPagadas": cuotas_pagadas,
            "cuotaMensual": cuota_mensual, "tasaInteres": tasa_interes,
            "fechaInicio": fecha_inicio.isoformat(), "fechaVencimiento": fecha_vencimiento.isoformat(),
            "notas": notas,
        })
        _toast_ok("✅ Deuda guardada")

    df = fd.listar_deudas(client, user_id)
    if not df.empty:
        st.dataframe(df.sort_values("fecha_vencimiento"), use_container_width=True, hide_index=True)


# ============================================================
# INVERSIONES CORTO PLAZO
# ============================================================

def _render_inv_corto(client, user_id: str) -> None:
    st.subheader("⚡ Inversión Corto Plazo")
    with st.form("form_inv_corto", clear_on_submit=True):
        nombre = st.text_input("Nombre *", placeholder="Ej: Plazo Fijo Banco Nación…")
        col1, col2 = st.columns(2)
        tipo = col1.selectbox(
            "Tipo *", ["", "Plazo Fijo", "Crypto", "Fondos Comunes", "Bonos Corto", "Cuenta Remunerada", "Otros"]
        )
        estado = col2.selectbox("Estado", ["Activa", "Vencida", "Cancelada", "Renovada"])
        col1, col2 = st.columns(2)
        monto = col1.number_input("Monto *", min_value=0.0, step=0.01)
        tasa = col2.number_input("Tasa Anual % *", step=0.01)
        col1, col2 = st.columns(2)
        fecha_inicio = col1.date_input("Fecha Inicio *", value=date.today())
        fecha_vencimiento = col2.date_input("Fecha Vencimiento *")
        notas = st.text_area("Notas")
        enviado = st.form_submit_button("⚡ Registrar Inversión")

    if enviado:
        if not nombre or not tipo or not monto:
            _toast_err("⚠️ Completá los campos obligatorios (*)")
            return
        fd.insertar_inv_corto(client, user_id, {
            "nombre": nombre, "tipo": tipo, "monto": monto, "tasa": tasa,
            "fechaInicio": fecha_inicio.isoformat(), "fechaVencimiento": fecha_vencimiento.isoformat(),
            "estado": estado, "notas": notas,
        })
        _toast_ok("✅ Inversión corto plazo guardada")

    df = fd.listar_inv_corto(client, user_id)
    if not df.empty:
        df = df.copy()
        df["monto_proyectado"] = df.apply(lambda r: fd.monto_proyectado_inv_corto(r), axis=1)
        st.dataframe(df, use_container_width=True, hide_index=True)


# ============================================================
# INVERSIONES LARGO PLAZO
# ============================================================

SIMBOLOS_COMUNES = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META",
                    "SPY", "QQQ", "BTC-USD", "ETH-USD", "MELI", "YPFD"]


def _render_inv_largo(client, user_id: str) -> None:
    st.subheader("📈 Inversión Largo Plazo")
    st.info("📡 El precio actual se trae en vivo con yfinance al cargar la sección.")

    with st.form("form_inv_largo", clear_on_submit=True):
        activo = st.text_input("Nombre del Activo *", placeholder="Ej: Apple Inc., Tesla…")
        col1, col2 = st.columns(2)
        tipo = col1.selectbox("Tipo *", ["", "Acción", "ETF", "Crypto", "Bono", "Fondo", "REIT", "Otro"])
        simbolo = col2.text_input("Símbolo (Ticker) *", placeholder="AAPL, TSLA…").upper()
        col1, col2 = st.columns(2)
        cantidad = col1.number_input("Cantidad *", min_value=0.0, step=0.0001, format="%.4f")
        precio_compra = col2.number_input("Precio Compra *", min_value=0.0, step=0.01)
        col1, col2 = st.columns(2)
        fecha_compra = col1.date_input("Fecha Compra *", value=date.today())
        estado = col2.selectbox("Estado", ["Activo", "Vendido", "En espera"])
        notas = st.text_area("Notas")
        enviado = st.form_submit_button("📈 Registrar Inversión")

    st.caption("Símbolos comunes: " + ", ".join(SIMBOLOS_COMUNES))

    if enviado:
        if not activo or not tipo or not simbolo or not cantidad or not precio_compra:
            _toast_err("⚠️ Completá los campos obligatorios (*)")
            return
        fd.insertar_inv_largo(client, user_id, {
            "activo": activo, "tipo": tipo, "simbolo": simbolo, "cantidad": cantidad,
            "precioCompra": precio_compra, "fechaCompra": fecha_compra.isoformat(),
            "estado": estado, "notas": notas,
        })
        _toast_ok(f"✅ {activo} ({simbolo}) guardado")

    df = fd.listar_inv_largo_con_precios(client, user_id)
    if not df.empty:
        st.dataframe(df, use_container_width=True, hide_index=True)


# ============================================================
# TRADING
# ============================================================

def _render_trading(client, user_id: str) -> None:
    st.subheader("⚡ Registrar Operación de Trading")
    st.info("⚡ Para operaciones abiertas, el precio actual se trae en vivo y el P&L se calcula solo.")

    estado_sel = st.selectbox("Estado *", ["Abierta", "Cerrada", "Cancelada"], key="tr_estado_sel")

    with st.form("form_trading", clear_on_submit=True):
        simbolo = st.text_input("Par / Activo *", placeholder="AAPL, BTC-USD, EUR/USD…").upper()
        col1, col2 = st.columns(2)
        tipo = col1.selectbox("Tipo *", ["", "Acción", "ETF", "Crypto", "Forex", "Futuros", "CFD", "Opción"])
        direccion = col2.selectbox("Dirección *", ["", "Long (Compra)", "Short (Venta)"])
        col1, col2 = st.columns(2)
        cantidad = col1.number_input("Cantidad *", min_value=0.0, step=0.0001, format="%.4f")
        precio_entrada = col2.number_input("Precio Entrada *", min_value=0.0, step=0.0001, format="%.4f")

        precio_cierre = fecha_cierre = None
        if estado_sel == "Cerrada":
            col1, col2 = st.columns(2)
            precio_cierre = col1.number_input("Precio Cierre", min_value=0.0, step=0.0001, format="%.4f")
            fecha_cierre = col2.date_input("Fecha Cierre", value=date.today())

        col1, col2 = st.columns(2)
        stop_loss = col1.number_input("Stop Loss", min_value=0.0, step=0.0001, format="%.4f")
        take_profit = col2.number_input("Take Profit", min_value=0.0, step=0.0001, format="%.4f")

        fecha_entrada = st.date_input("Fecha Entrada *", value=date.today())
        estrategia = st.selectbox(
            "Estrategia", ["", "Scalping", "Day Trade", "Swing", "Posición", "Tendencia", "Ruptura", "Reversión", "Otros"]
        )
        notas = st.text_area("Notas / Setup")
        enviado = st.form_submit_button("⚡ Registrar Operación")

    if enviado:
        if not simbolo or not tipo or not direccion or not cantidad or not precio_entrada:
            _toast_err("⚠️ Completá los campos obligatorios (*)")
            return
        fd.insertar_trading(client, user_id, {
            "simbolo": simbolo, "tipo": tipo, "direccion": direccion, "estado": estado_sel,
            "cantidad": cantidad, "precioEntrada": precio_entrada,
            "precioCierre": precio_cierre, "fechaEntrada": fecha_entrada.isoformat(),
            "fechaCierre": fecha_cierre.isoformat() if fecha_cierre else "",
            "stopLoss": stop_loss, "takeProfit": take_profit,
            "estrategia": estrategia, "notas": notas,
        })
        _toast_ok(f"✅ Operación {simbolo} guardada")

    st.divider()
    st.markdown("##### 📋 Cerrar Operación Abierta")
    abiertas = fd.operaciones_abiertas(client, user_id)
    if not abiertas:
        st.caption("No hay operaciones abiertas.")
        return

    opciones = {
        f"{o['simbolo']} | {o['direccion']} | {o['cantidad']} u. @ ${o['precio_entrada']:.4f} | {o['fecha_entrada']}": o
        for o in abiertas
    }
    seleccion = st.selectbox("Operación a cerrar", ["—"] + list(opciones.keys()))

    if seleccion != "—":
        op = opciones[seleccion]
        if op["pnl_no_realizado"] is not None:
            color = POS if op["pnl_no_realizado"] >= 0 else NEG
            st.markdown(
                f"P&L no realizado (a precio actual): "
                f"<span style='color:{color};font-weight:700'>{_money(op['pnl_no_realizado'])}</span>",
                unsafe_allow_html=True,
            )
        col1, col2 = st.columns(2)
        precio_cierre_final = col1.number_input("Precio Cierre *", min_value=0.0, step=0.0001, format="%.4f", key="cierre_precio")
        fecha_cierre_final = col2.date_input("Fecha Cierre *", value=date.today(), key="cierre_fecha")
        if st.button("✅ Confirmar Cierre"):
            if not precio_cierre_final:
                _toast_err("⚠️ Ingresá el precio de cierre")
            else:
                r = fd.cerrar_operacion(client, user_id, op["id"], precio_cierre_final, fecha_cierre_final.isoformat())
                _toast_ok(r["mensaje"]) if r["ok"] else _toast_err(r["mensaje"])

    df = fd.listar_trading(client, user_id)
    if not df.empty:
        st.dataframe(df.sort_values("fecha_entrada", ascending=False), use_container_width=True, hide_index=True)


# ============================================================
# OBJETIVOS DE AHORRO
# ============================================================

def _render_objetivos(client, user_id: str) -> None:
    st.subheader("🎯 Objetivos de Ahorro")
    sub = st.radio("", ["Nuevo Objetivo", "Registrar Aporte"], horizontal=True, label_visibility="collapsed")

    if sub == "Nuevo Objetivo":
        with st.form("form_objetivo", clear_on_submit=True):
            nombre = st.text_input("Nombre del Objetivo *", placeholder="Ej: Viaje a Europa, Auto nuevo…")
            col1, col2 = st.columns(2)
            categoria = col1.selectbox(
                "Categoría *",
                ["", "Viaje", "Auto", "Casa", "Fondo Emergencia", "Educación", "Tecnología",
                 "Inversión", "Boda", "Jubilación", "Otros"],
            )
            estado = col2.selectbox("Estado", ["Activo", "Pausado", "Cumplido", "Cancelado"])
            meta = st.number_input("Monto Meta *", min_value=0.0, step=0.01)
            col1, col2 = st.columns(2)
            fecha_inicio = col1.date_input("Fecha Inicio *", value=date.today())
            fecha_meta = col2.date_input("Fecha Meta *")
            notas = st.text_area("Notas")
            enviado = st.form_submit_button("🎯 Crear Objetivo")

        if meta and fecha_meta and fecha_meta > date.today():
            meses = max((fecha_meta.year - date.today().year) * 12 + fecha_meta.month - date.today().month, 1)
            st.caption(f"💡 Aporte mensual sugerido: {_money(meta / meses)} / mes durante {meses} meses")

        if enviado:
            if not nombre or not categoria or not meta:
                _toast_err("⚠️ Completá los campos obligatorios (*)")
                return
            fd.insertar_objetivo(client, user_id, {
                "nombre": nombre, "categoria": categoria, "meta": meta,
                "fechaInicio": fecha_inicio.isoformat(), "fechaMeta": fecha_meta.isoformat(),
                "estado": estado, "notas": notas,
            })
            _toast_ok(f"✅ Objetivo '{nombre}' guardado")

    else:
        progreso = fd.objetivos_con_progreso(client, user_id)
        if not progreso:
            st.caption("Sin objetivos activos aún.")
            return
        for o in progreso:
            st.progress(min(o["pct"], 1.0), text=f"{o['nombre']} — {o['pct'] * 100:.1f}%")
            st.caption(f"Aportado: {_money(o['aportado'])} / Meta: {_money(o['meta'])}")

        opciones = {o["nombre"]: o["id"] for o in progreso}
        with st.form("form_aporte", clear_on_submit=True):
            fecha = st.date_input("Fecha *", value=date.today())
            objetivo_nombre = st.selectbox("Objetivo *", ["—"] + list(opciones.keys()))
            categoria = st.selectbox(
                "Categoría", ["Transferencia", "Efectivo", "Débito automático", "Redondeo", "Premio / Bonus", "Otro"]
            )
            monto = st.number_input("Monto *", min_value=0.0, step=0.01)
            notas = st.text_area("Notas")
            enviado = st.form_submit_button("💸 Registrar Aporte")

        if enviado:
            if objetivo_nombre == "—" or not monto:
                _toast_err("⚠️ Completá los campos obligatorios (*)")
                return
            fd.insertar_aporte(client, user_id, {
                "objetivoId": opciones[objetivo_nombre], "fecha": fecha.isoformat(),
                "categoria": categoria, "monto": monto, "notas": notas,
            })
            _toast_ok(f"✅ Aporte de {_money(monto)} guardado")


# ============================================================
# ENTRYPOINT — llamar desde la app principal
# ============================================================

def render_finanzas_personales(client, user_id: str) -> None:
    """Punto de entrada único. Llamar desde analizador_cuantitativo_v3.py
    dentro del tab/página correspondiente, con el client de Supabase
    y el user_id ya autenticados."""
    st.markdown(f"<h2 style='color:{ACCENT}'>💰 Finanzas Personales</h2>", unsafe_allow_html=True)

    tabs = st.tabs([
        "📊 Dashboard", "📥 Ingresos", "📤 Gastos", "💳 Deudas",
        "⚡ Corto Plazo", "📈 Largo Plazo", "🎯 Trading", "🏆 Objetivos",
    ])
    with tabs[0]:
        _render_dashboard(client, user_id)
    with tabs[1]:
        _render_ingresos(client, user_id)
    with tabs[2]:
        _render_gastos(client, user_id)
    with tabs[3]:
        _render_deudas(client, user_id)
    with tabs[4]:
        _render_inv_corto(client, user_id)
    with tabs[5]:
        _render_inv_largo(client, user_id)
    with tabs[6]:
        _render_trading(client, user_id)
    with tabs[7]:
        _render_objetivos(client, user_id)


if __name__ == "__main__":
    st.warning(
        "Este módulo no se ejecuta solo: importalo desde tu app principal y llamá a "
        "render_finanzas_personales(client, user_id)."
    )
