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

from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

import finanzas_data as fd

ACCENT = "#6CC24A"
POS = "#00e676"
NEG = "#ff5252"

# Categorías: fuente única en finanzas_data.py, se reusan acá para
# que los selects de carga y los desgloses del dashboard coincidan
# siempre con la misma lista completa.
CATEGORIAS_INGRESOS = fd.CATEGORIAS_INGRESOS
SUBCATEGORIAS = fd.SUBCATEGORIAS_GASTOS
CATEGORIAS_GASTOS = fd.CATEGORIAS_GASTOS

MESES_NOMBRES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


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


# Mensaje "flash": sobrevive al st.rerun() para que se vea el resultado de una acción.
def _flash(ok: bool, msg: str) -> None:
    st.session_state["_fin_flash"] = (ok, msg)


def _mostrar_flash() -> None:
    f = st.session_state.pop("_fin_flash", None)
    if f:
        (st.success if f[0] else st.error)(f[1])


# ============================================================
# TABLA EDITABLE — editar y eliminar registros existentes
# Se reutiliza en las secciones para no duplicar la lógica de
# diff (qué cambió) y de borrado con confirmación.
# ============================================================

def _valores_distintos(a, b) -> bool:
    """Compara dos valores de celda tolerando tipos que cambian al pasar
    por el editor (NaN vs None, floats con distinta precisión, fechas
    como str vs date)."""
    a_vacio = a is None or (isinstance(a, float) and pd.isna(a))
    b_vacio = b is None or (isinstance(b, float) and pd.isna(b))
    if a_vacio and b_vacio:
        return False
    if a_vacio != b_vacio:
        return True
    if isinstance(a, float) or isinstance(b, float):
        try:
            return round(float(a), 6) != round(float(b), 6)
        except (TypeError, ValueError):
            pass
    return str(a) != str(b)


# Opciones de los selects al editar (por sección) y columnas guardadas como
# fracción que se editan en % (tasa_anual 0.08 -> 8 %).
OPCIONES_EDICION = {
    "ingresos": {
        "categoria": CATEGORIAS_INGRESOS,
        "cuenta": ["Efectivo", "Banco", "Mercado Pago", "Crypto", "Otro"],
    },
    "gastos": {
        "categoria": CATEGORIAS_GASTOS,
        "cuenta": ["Efectivo", "Débito", "Crédito", "Mercado Pago", "Otro"],
    },
    "deudas": {
        "tipo": ["Préstamo Personal", "Tarjeta de Crédito", "Hipoteca", "Auto", "Estudiante", "Familiar", "Otros"],
        "estado": ["Activa", "En mora", "Pagada", "Refinanciada"],
    },
    "inv_corto": {
        "tipo": ["Plazo Fijo", "Crypto", "Fondos Comunes", "Bonos Corto", "Cuenta Remunerada", "Otros"],
        "estado": ["Activa", "Vencida", "Cancelada", "Renovada", "Cobrada"],
    },
    "inv_largo": {
        "tipo": ["Acción", "ETF", "Crypto", "Bono", "Fondo", "REIT", "Otro"],
        "estado": ["Activo", "Vendido", "En espera"],
    },
    "trading": {
        "tipo": ["Acción", "ETF", "Crypto", "Forex", "Futuros", "CFD", "Opción"],
        "direccion": ["Long (Compra)", "Short (Venta)"],
        "estado": ["Abierta", "Cerrada", "Cancelada"],
        "estrategia": ["", "Scalping", "Day Trade", "Swing", "Posición", "Tendencia", "Ruptura", "Reversión", "Otros"],
    },
    "objetivos": {
        "categoria": ["Viaje", "Auto", "Casa", "Fondo Emergencia", "Educación", "Tecnología",
                      "Inversión", "Boda", "Jubilación", "Otros"],
        "estado": ["Activo", "Pausado", "Cumplido", "Cancelado"],
    },
    "aportes": {
        "categoria": ["Transferencia", "Efectivo", "Débito automático", "Redondeo", "Premio / Bonus", "Otro"],
    },
}
PCT_EDICION = {"inv_corto": ("tasa_anual",), "deudas": ("tasa_interes",)}
COLUMNAS_ENTERAS = ("cuotas_totales", "cuotas_pagadas")


def _a_python(v):
    """Convierte valores de pandas/numpy a tipos que Supabase (JSON) acepta:
    numpy → nativo, NaN/NaT → None, fechas → 'AAAA-MM-DD'."""
    if v is None or v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        try:
            v = v.item()
        except Exception:
            pass
    if isinstance(v, float) and pd.isna(v):
        return None
    return v


def _es_nulo(v) -> bool:
    if v is None or v is pd.NaT:
        return True
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _campo_edicion(df: pd.DataFrame, col: str, orig, key: str, opciones: dict, pct_cols: tuple):
    """Dibuja el campo de edición adecuado para una columna y devuelve el valor ingresado."""
    etiqueta = col.replace("_", " ").capitalize()
    nulo = _es_nulo(orig)

    if col in opciones:
        ops = list(opciones[col])
        actual = "" if nulo else str(orig)
        if actual and actual not in ops:
            ops = [actual] + ops
        return st.selectbox(etiqueta, ops, index=ops.index(actual) if actual in ops else 0, key=key)

    if "fecha" in col:
        val = None
        if not nulo:
            try:
                val = pd.to_datetime(orig).date()
            except Exception:
                val = None
        if val is None:
            t = st.text_input(f"{etiqueta} (AAAA-MM-DD, vacío = sin fecha)", value="" if nulo else str(orig), key=key)
            return t.strip() or None
        return st.date_input(etiqueta, value=val, key=key).isoformat()

    serie = df[col]
    if pd.api.types.is_bool_dtype(serie):
        return st.checkbox(etiqueta, value=False if nulo else bool(orig), key=key)

    if pd.api.types.is_numeric_dtype(serie):
        if col in COLUMNAS_ENTERAS or col.endswith("_id"):
            return int(st.number_input(etiqueta, value=0 if nulo else int(orig), step=1, key=key))
        v = 0.0 if nulo else float(orig)
        if col in pct_cols:
            v *= 100
            etiqueta += " %"
        return float(st.number_input(etiqueta, value=v, step=0.01, format="%.4f", key=key))

    txt = "" if nulo else str(orig)
    if col == "notas":
        return st.text_area(etiqueta, value=txt, key=key)
    return st.text_input(etiqueta, value=txt, key=key)


def _form_editar(client, user_id, seccion_key, df, actualizar_fn, etiquetas, columnas, opciones, pct_cols) -> None:
    sel = st.selectbox("Registro a editar", ["—"] + list(etiquetas.keys()), key=f"ed_sel_{seccion_key}")
    if sel == "—":
        return
    fila = etiquetas[sel]
    rid = int(fila["id"])

    nuevos = {}
    with st.form(f"form_edit_{seccion_key}_{rid}"):
        cols_ui = st.columns(2)
        for i, col in enumerate(columnas):
            with cols_ui[i % 2]:
                nuevos[col] = _campo_edicion(df, col, fila[col], f"ed_{seccion_key}_{rid}_{col}", opciones, pct_cols)
        guardar = st.form_submit_button("💾 Guardar cambios")

    if not guardar:
        return

    cambios = {}
    for col, nuevo in nuevos.items():
        orig = fila[col]
        nulo = _es_nulo(orig)
        if "fecha" in col:
            if nuevo is not None:
                try:
                    date.fromisoformat(str(nuevo))
                except ValueError:
                    st.error(f"⚠️ La fecha de '{col}' no es válida (usá AAAA-MM-DD).")
                    return
            orig_iso = None if nulo else pd.to_datetime(orig).date().isoformat()
            if nuevo != orig_iso:
                cambios[col] = nuevo
        elif isinstance(nuevo, bool):
            if nuevo != (False if nulo else bool(orig)):
                cambios[col] = nuevo
        elif isinstance(nuevo, (int, float)):
            valor = nuevo / 100 if (col in pct_cols and isinstance(nuevo, float)) else nuevo
            if nulo and valor == 0:
                continue
            if nulo or round(float(valor), 6) != round(float(orig), 6):
                cambios[col] = valor
        else:
            if nulo and nuevo in ("", None):
                continue
            if str(nuevo) != ("" if nulo else str(orig)):
                cambios[col] = nuevo

    if not cambios:
        st.info("No había cambios para guardar.")
        return
    r = actualizar_fn(client, user_id, rid, {k: _a_python(v) for k, v in cambios.items()})
    _flash(r["ok"], "✅ Registro actualizado" if r["ok"] else r["mensaje"])
    st.rerun()


def _editor_rapido(client, user_id, seccion_key, df_mostrado, actualizar_fn, bloqueadas) -> None:
    """Edición celda por celda directo en la tabla (con conversión de tipos segura)."""
    editado = st.data_editor(
        df_mostrado, key=f"editor_{seccion_key}", num_rows="fixed",
        disabled=bloqueadas, use_container_width=True, hide_index=True,
    )
    if st.button("💾 Guardar cambios de la tabla", key=f"guardar_{seccion_key}"):
        filas_actualizadas = 0
        errores = []
        for _, fila_nueva in editado.iterrows():
            fila_id = int(fila_nueva["id"])
            fila_original = df_mostrado[df_mostrado["id"] == fila_id]
            if fila_original.empty:
                continue
            fila_original = fila_original.iloc[0]
            cambios = {
                col: _a_python(fila_nueva[col]) for col in editado.columns
                if col not in bloqueadas and _valores_distintos(fila_nueva[col], fila_original[col])
            }
            if cambios:
                r = actualizar_fn(client, user_id, fila_id, cambios)
                if r["ok"]:
                    filas_actualizadas += 1
                else:
                    errores.append(f"Fila {fila_id}: {r['mensaje']}")
        if errores:
            st.error("⚠️ Algunos cambios no se pudieron guardar:\n" + "\n".join(errores))
        if filas_actualizadas:
            _flash(True, f"✅ {filas_actualizadas} registro(s) actualizado(s)")
            st.rerun()
        elif not errores:
            st.info("No había cambios para guardar.")


def _tabla_editable(
    client, user_id: str, seccion_key: str, df: pd.DataFrame,
    actualizar_fn, eliminar_fn, label_fn,
    columnas_ocultas: tuple = ("user_id", "created_at"), solo_lectura: tuple = (),
) -> None:
    """Editar / eliminar registros de cualquier sección.
    - ✏️ Editar: elegís el registro y se abre un formulario con todos sus
      campos (selects, fechas, números). Además hay una 'edición rápida'
      celda por celda en la tabla.
    - 🗑️ Eliminar: elegís el registro y confirmás.
    'solo_lectura' = columnas que se muestran pero no se pueden editar."""
    _mostrar_flash()
    if df.empty:
        st.caption("Todavía no hay registros cargados.")
        return

    df = df.reset_index(drop=True)
    df_mostrado = df.drop(columns=[c for c in columnas_ocultas if c in df.columns])
    bloqueadas = ["id"] + [c for c in solo_lectura if c in df_mostrado.columns]
    columnas_form = [c for c in df_mostrado.columns if c not in bloqueadas]
    opciones = OPCIONES_EDICION.get(seccion_key, {})
    pct_cols = PCT_EDICION.get(seccion_key, ())
    etiquetas = {f"{label_fn(r)} · #{int(r['id'])}": r for _, r in df.iterrows()}

    modo = st.radio("Acción", ["✏️ Editar", "🗑️ Eliminar"], horizontal=True, key=f"modo_{seccion_key}")

    if modo == "✏️ Editar":
        _form_editar(client, user_id, seccion_key, df, actualizar_fn, etiquetas, columnas_form, opciones, pct_cols)
        # (checkbox y no expander: algunas secciones ya llaman a esta tabla dentro de un expander)
        if st.checkbox("⚡ Edición rápida en la tabla (celda por celda)", key=f"rapida_{seccion_key}"):
            _editor_rapido(client, user_id, seccion_key, df_mostrado, actualizar_fn, bloqueadas)
        return

    st.dataframe(df_mostrado, use_container_width=True, hide_index=True)
    seleccion = st.selectbox(
        "Registro a eliminar", ["—"] + list(etiquetas.keys()), key=f"del_sel_{seccion_key}",
    )
    if seleccion != "—":
        id_a_borrar = int(etiquetas[seleccion]["id"])
        confirmado = st.checkbox(
            f"Confirmo que quiero eliminar: {seleccion}", key=f"del_confirm_{seccion_key}_{id_a_borrar}",
        )
        if confirmado and st.button("🗑️ Eliminar definitivamente", key=f"del_btn_{seccion_key}"):
            r = eliminar_fn(client, user_id, id_a_borrar)
            if r["ok"]:
                _flash(True, r["mensaje"])
                st.rerun()
            else:
                st.error(r["mensaje"])


# ============================================================
# DASHBOARD
# ============================================================

def _selector_periodo() -> tuple[date, date, str]:
    """Selector de período para el dashboard: Día, Mes o Año.
    Devuelve (fecha_inicio, fecha_fin, etiqueta_legible)."""
    hoy = date.today()

    col_tipo, col_valor = st.columns([1, 2])
    tipo = col_tipo.selectbox(
        "Filtrar por", ["Mes", "Año", "Día"], key="fin_dash_periodo_tipo",
    )

    if tipo == "Día":
        dia = col_valor.date_input("Día", value=hoy, key="fin_dash_periodo_dia")
        inicio, fin = fd.rango_dia(dia)
        return inicio, fin, dia.strftime("%d/%m/%Y")

    if tipo == "Año":
        anio = col_valor.number_input(
            "Año", min_value=2000, max_value=2100, value=hoy.year, step=1, key="fin_dash_periodo_anio",
        )
        inicio, fin = fd.rango_anio(int(anio))
        return inicio, fin, str(int(anio))

    # Mes (default)
    with col_valor:
        c1, c2 = st.columns(2)
        mes_nombre = c1.selectbox(
            "Mes", MESES_NOMBRES, index=hoy.month - 1, key="fin_dash_periodo_mes",
        )
        anio = c2.number_input(
            "Año", min_value=2000, max_value=2100, value=hoy.year, step=1, key="fin_dash_periodo_mes_anio",
        )
    mes_num = MESES_NOMBRES.index(mes_nombre) + 1
    inicio, fin = fd.rango_mes(int(anio), mes_num)
    return inicio, fin, f"{mes_nombre} {int(anio)}"


def _render_alertas(client, user_id: str) -> None:
    """Panel de alertas: deudas en mora/por vencer, inversiones por vencer,
    trading que tocó SL/TP, y objetivos atrasados/vencidos/cumplidos."""
    alertas = fd.obtener_alertas(client, user_id)
    if not alertas:
        return

    hay_urgentes = any(a["nivel"] in ("error", "warning") for a in alertas)
    with st.expander(f"🔔 {len(alertas)} alerta(s)", expanded=hay_urgentes):
        por_nivel: dict[str, list[str]] = {}
        for a in alertas:
            por_nivel.setdefault(a["nivel"], []).append(f"{a['icono']} {a['mensaje']}")

        renderers = {
            "error": st.error, "warning": st.warning,
            "success": st.success, "info": st.info,
        }
        for nivel in ("error", "warning", "success", "info"):
            mensajes = por_nivel.get(nivel)
            if mensajes:
                renderers[nivel]("\n\n".join(mensajes))


def _pie(df: pd.DataFrame, cat_col: str, val_col: str, alto: int = 320) -> None:
    """Gráfico de torta (donut) con Altair. Ignora categorías en $0 o negativas.
    - En el centro: monto total y 100%.
    - Al hacer clic en una porción: el centro muestra el nombre, el monto y
      el porcentaje de esa porción (la porción se resalta con un borde).
    - Clic afuera de la torta: vuelve al total."""
    if df is None or df.empty:
        st.caption("Sin datos para graficar.")
        return
    d = df[[cat_col, val_col]].copy()
    d = d[d[val_col] > 0]
    if d.empty:
        st.caption("Sin datos para graficar.")
        return

    total = float(d[val_col].sum())
    d["pct"] = d[val_col] / total
    d["monto_txt"] = d[val_col].map(lambda v: f"${v:,.2f}")
    d["pct_txt"] = d["pct"].map(lambda v: f"{v * 100:.1f}%")
    d["tot_txt"] = f"${total:,.2f}"
    d["lbl"] = d[cat_col].astype(str).str.slice(0, 22)

    # Color del texto central según el tema (oscuro por defecto).
    try:
        base_tema = st.get_option("theme.base")
    except Exception:
        base_tema = None
    color_txt = "#31333F" if base_tema == "light" else "#fafafa"
    color_sec = "#808495"

    # Compatibilidad Altair 5 (selection_point) y Altair 4 (selection_single).
    if hasattr(alt, "selection_point"):
        sel = alt.selection_point(name="sel_pie", fields=[cat_col], on="click", empty=False)
        def _aplicar(ch):
            return ch.add_params(sel)
    else:
        sel = alt.selection_single(name="sel_pie", fields=[cat_col], on="click", empty="none")
        def _aplicar(ch):
            return ch.add_selection(sel)

    # Verdadero solo cuando NO hay ninguna porción seleccionada (global, no por fila).
    sin_seleccion = "length(data('sel_pie_store')) == 0"

    base = alt.Chart(d)

    arco = base.mark_arc(innerRadius=75).encode(
        theta=alt.Theta(f"{val_col}:Q", stack=True),
        color=alt.Color(f"{cat_col}:N", legend=alt.Legend(title=None)),
        order=alt.Order(f"{val_col}:Q", sort="descending"),
        stroke=alt.value(color_txt),
        strokeWidth=alt.condition(sel, alt.value(3), alt.value(0)),
        tooltip=[
            alt.Tooltip(f"{cat_col}:N", title="Detalle"),
            alt.Tooltip("monto_txt:N", title="Monto"),
            alt.Tooltip("pct_txt:N", title="Porcentaje"),
        ],
    )

    def _texto(valor, size, dy, filtro, bold=False, color=color_txt, unico=False):
        """Texto centrado. 'valor' es un campo del DataFrame o un literal
        (alt.value). 'unico' deja una sola fila para no superponer textos."""
        ch = base.mark_text(
            align="center", baseline="middle", fontSize=size, dy=dy,
            fontWeight="bold" if bold else "normal", color=color,
        )
        ch = ch.encode(text=valor).transform_filter(filtro)
        if unico:
            ch = ch.transform_window(rn="row_number()").transform_filter("datum.rn == 1")
        return ch

    capas = [
        arco,
        # Sin selección: total
        _texto(alt.value("Total"), 12, -26, sin_seleccion, color=color_sec, unico=True),
        _texto("tot_txt:N", 17, 0, sin_seleccion, bold=True, unico=True),
        _texto(alt.value("100%"), 14, 24, sin_seleccion, color=color_sec, unico=True),
        # Con selección: detalle de la porción elegida
        _texto("lbl:N", 12, -26, sel, color=color_sec),
        _texto("monto_txt:N", 17, 0, sel, bold=True),
        _texto("pct_txt:N", 14, 24, sel, color=color_sec),
    ]

    chart = _aplicar(alt.layer(*capas)).properties(height=alto)
    st.altair_chart(chart, use_container_width=True)


def _render_categoria_breakdown(titulo: str, df: pd.DataFrame) -> None:
    """Muestra el desglose por categoría (todas las categorías, incluso
    en $0) como gráfico de torta + tabla."""
    st.markdown(f"##### {titulo}")
    if df.empty or df["monto"].sum() == 0:
        st.caption("Sin movimientos en el período seleccionado.")
        st.dataframe(df, use_container_width=True, hide_index=True)
        return
    _pie(df, "categoria", "monto")
    st.dataframe(df, use_container_width=True, hide_index=True)


# Si tu Streamlit soporta fragments, cambiar el selector de abajo solo
# re-ejecuta esa parte (no recarga todo el dashboard ni los precios).
_fragment = getattr(st, "fragment", None) or getattr(st, "experimental_fragment", None)


def _como_fragment(fn):
    return _fragment(fn) if _fragment else fn


def _pct_txt(v) -> str:
    return f"{v:.2f}%" if v is not None and pd.notna(v) else "—"


@_como_fragment
def _render_inversiones_detalle(client, user_id: str) -> None:
    """Composición de las inversiones con selector: General, Corto plazo,
    Largo plazo o cada cartera por individual."""
    vista = st.radio(
        "Ver composición de", ["General", "Corto plazo", "Largo plazo", "Carteras"],
        horizontal=True, key="dash_inv_vista",
    )

    # ---------------- GENERAL ----------------
    if vista == "General":
        carteras = fd.listar_carteras(client, user_id)
        liquidez = float(carteras["efectivo"].sum()) if not carteras.empty else 0.0
        datos = pd.DataFrame({
            "concepto": ["Corto plazo", "Largo plazo (a costo)", "Liquidez en carteras"],
            "monto": [fd.resumen_inv_corto(client, user_id), fd.resumen_inv_largo(client, user_id), liquidez],
        })
        _pie(datos, "concepto", "monto")
        return

    # ---------------- CORTO PLAZO ----------------
    if vista == "Corto plazo":
        df = fd.listar_inv_corto(client, user_id)
        activas = df[df["estado"] == "Activa"] if not df.empty else df
        if activas.empty:
            st.caption("No hay inversiones de corto plazo activas.")
            return
        agrupar = st.radio("Agrupar por", ["Tipo", "Inversión"], horizontal=True, key="dash_corto_group")
        col = "tipo" if agrupar == "Tipo" else "nombre"
        datos = activas.groupby(col, as_index=False)["monto"].sum()
        c1, c2 = st.columns(2)
        with c1:
            _pie(datos, col, "monto")
        with c2:
            t = activas.copy()
            t["monto_proyectado"] = t.apply(lambda r: fd.monto_proyectado_inv_corto(r), axis=1)
            t["tasa_anual"] = t["tasa_anual"] * 100
            st.dataframe(
                t[["nombre", "tipo", "monto", "tasa_anual", "fecha_vencimiento", "monto_proyectado"]],
                use_container_width=True, hide_index=True,
                column_config={
                    "monto": st.column_config.NumberColumn("Monto", format="$%.2f"),
                    "tasa_anual": st.column_config.NumberColumn("Tasa anual", format="%.2f%%"),
                    "monto_proyectado": st.column_config.NumberColumn("Proyectado", format="$%.2f"),
                },
            )
        return

    # ---------------- LARGO PLAZO ----------------
    if vista == "Largo plazo":
        df = fd.listar_inv_largo_con_precios(client, user_id)
        activos = df[df["estado"] == "Activo"].copy() if not df.empty else df
        if activos.empty:
            st.caption("No hay inversiones de largo plazo activas.")
            return
        carteras = fd.listar_carteras(client, user_id)
        nombres = {int(r["id"]): r["nombre"] for _, r in carteras.iterrows()} if not carteras.empty else {}
        activos["cartera"] = activos["cartera_id"].map(
            lambda x: nombres.get(int(x), "Sin cartera") if pd.notna(x) else "Sin cartera"
        )
        sin_precio = int(activos["valor_actual"].isna().sum())
        con_precio = activos.dropna(subset=["valor_actual"])
        if con_precio.empty:
            st.caption("No se pudieron traer los precios actuales.")
            return
        agrupar = st.radio("Agrupar por", ["Activo", "Tipo", "Cartera"], horizontal=True, key="dash_largo_group")
        col = {"Activo": "activo", "Tipo": "tipo", "Cartera": "cartera"}[agrupar]
        datos = con_precio.groupby(col, as_index=False)["valor_actual"].sum()
        c1, c2 = st.columns(2)
        with c1:
            _pie(datos, col, "valor_actual")
        with c2:
            t = con_precio.copy()
            t["ganancia_pct"] = t["ganancia_pct"] * 100
            st.dataframe(
                t[["activo", "simbolo", "cartera", "valor_actual", "ganancia_perdida", "ganancia_pct"]],
                use_container_width=True, hide_index=True,
                column_config={
                    "valor_actual": st.column_config.NumberColumn("Valor actual", format="$%.2f"),
                    "ganancia_perdida": st.column_config.NumberColumn("Ganancia $", format="$%.2f"),
                    "ganancia_pct": st.column_config.NumberColumn("Ganancia %", format="%.2f%%"),
                },
            )
        if sin_precio:
            st.caption(f"⚠️ {sin_precio} activo(s) sin precio en vivo no se incluyeron en el gráfico.")
        return

    # ---------------- CARTERAS (individual) ----------------
    res = fd.carteras_resumen(client, user_id)
    if res.empty:
        st.caption("Todavía no hay carteras ni activos de largo plazo.")
        return

    opciones = ["Todas (comparar)"] + res["cartera"].tolist()
    sel = st.selectbox("Cartera", opciones, key="dash_inv_cartera")

    if sel == "Todas (comparar)":
        st.caption("Total por cartera (valor actual de los activos + liquidez).")
        _pie(res, "cartera", "total")
        st.dataframe(
            res.drop(columns=["cartera_id"]), use_container_width=True, hide_index=True,
            column_config={
                "cartera": "Cartera", "activos": "Activos",
                "invertido": st.column_config.NumberColumn("Invertido", format="$%.2f"),
                "valor_actual": st.column_config.NumberColumn("Valor actual", format="$%.2f"),
                "ganancia": st.column_config.NumberColumn("Ganancia $", format="$%.2f"),
                "rend_promedio_pct": st.column_config.NumberColumn("Rend. (promedio)", format="%.2f%%"),
                "rend_ponderado_pct": st.column_config.NumberColumn("Rend. (ponderado)", format="%.2f%%"),
                "efectivo": st.column_config.NumberColumn("Liquidez", format="$%.2f"),
                "total": st.column_config.NumberColumn("Total", format="$%.2f"),
            },
        )
        return

    fila = res[res["cartera"] == sel].iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Valor actual", _money(fila["valor_actual"]))
    c2.metric("Ganancia/Pérdida", _money(fila["ganancia"]))
    c3.metric("Rendimiento (promedio)", _pct_txt(fila["rend_promedio_pct"]))
    c4.metric("Rendimiento (ponderado)", _pct_txt(fila["rend_ponderado_pct"]))
    c1, c2, c3 = st.columns(3)
    c1.metric("Invertido", _money(fila["invertido"]))
    c2.metric("Liquidez", _money(fila["efectivo"]))
    c3.metric("Total (valor + liquidez)", _money(fila["total"]))

    pos = fd.listar_inv_largo_con_precios(client, user_id)
    activos = pos[pos["estado"] == "Activo"] if not pos.empty else pos
    if not activos.empty:
        if pd.isna(fila["cartera_id"]):
            activos = activos[activos["cartera_id"].isna()]
        else:
            activos = activos[activos["cartera_id"] == fila["cartera_id"]]
    activos = activos.dropna(subset=["valor_actual"]) if not activos.empty else activos

    incluir_liq = st.checkbox("Incluir liquidez en el gráfico", value=True, key=f"dash_cart_liq_{sel}")
    partes = [{"concepto": r["activo"], "monto": float(r["valor_actual"])} for _, r in activos.iterrows()]
    if incluir_liq and float(fila["efectivo"]) > 0:
        partes.append({"concepto": "💵 Liquidez", "monto": float(fila["efectivo"])})

    g1, g2 = st.columns(2)
    with g1:
        _pie(pd.DataFrame(partes), "concepto", "monto")
    with g2:
        if activos.empty:
            st.caption("Esta cartera no tiene activos activos con precio.")
        else:
            t = activos.copy()
            t["ganancia_pct"] = t["ganancia_pct"] * 100
            st.dataframe(
                t[["activo", "simbolo", "cantidad", "precio_compra", "precio_hoy", "ganancia_perdida", "ganancia_pct"]],
                use_container_width=True, hide_index=True,
                column_config={
                    "precio_compra": st.column_config.NumberColumn("Compra", format="$%.4f"),
                    "precio_hoy": st.column_config.NumberColumn("Actual", format="$%.4f"),
                    "ganancia_perdida": st.column_config.NumberColumn("Ganancia $", format="$%.2f"),
                    "ganancia_pct": st.column_config.NumberColumn("Ganancia %", format="%.2f%%"),
                },
            )


def _render_dashboard(client, user_id: str) -> None:
    st.subheader("📊 Dashboard Financiero")

    col_periodo, col_refresh = st.columns([4, 1])
    with col_periodo:
        inicio, fin, etiqueta = _selector_periodo()
    with col_refresh:
        st.write("")
        st.write("")
        if st.button("🔄 Actualizar", key="fin_dash_refresh"):
            st.cache_data.clear()

    st.caption(f"Mostrando datos de: **{etiqueta}**")

    _render_alertas(client, user_id)

    d = fd.obtener_dashboard_data(client, user_id, inicio, fin)

    st.markdown("##### 💵 Finanzas del período")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ingresos", _money(d["ingresos"]))
    c2.metric("Gastos", _money(d["gastos"]))
    c3.metric("Balance", _money(d["balance"]), delta=_money(d["balance"]))
    c4.metric("Tasa de ahorro", d["tasa_ahorro"])

    col1, col2 = st.columns(2)
    with col1:
        _render_categoria_breakdown("📤 Gastos por categoría", d["gastos_por_categoria"])
    with col2:
        _render_categoria_breakdown("📥 Ingresos por categoría", d["ingresos_por_categoria"])

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

    st.markdown("###### 🔍 Composición de inversiones")
    _render_inversiones_detalle(client, user_id)

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
        categoria = col1.selectbox("Categoría *", [""] + CATEGORIAS_INGRESOS)
        cuenta = col2.selectbox("Cuenta", ["Efectivo", "Banco", "Mercado Pago", "Crypto", "Otro"])
        monto = st.number_input("Monto *", min_value=0.0, step=0.01)
        notas = st.text_area("Notas")
        enviado = st.form_submit_button("📥 Registrar Ingreso")

    if enviado:
        if not descripcion or not categoria or not monto:
            _toast_err("⚠️ Completá los campos obligatorios (*)")
            return
        r = fd.insertar_ingreso(client, user_id, {
            "fecha": fecha.isoformat(), "descripcion": descripcion, "categoria": categoria,
            "monto": monto, "cuenta": cuenta, "notas": notas,
        })
        _toast_ok(r["mensaje"]) if r["ok"] else _toast_err(r["mensaje"])

    df = fd.listar_ingresos(client, user_id)
    if not df.empty:
        st.markdown("###### Tus ingresos (editar / eliminar)")
        _tabla_editable(
            client, user_id, "ingresos", df.sort_values("fecha", ascending=False),
            fd.actualizar_ingreso, fd.eliminar_ingreso,
            label_fn=lambda r: f"{r['fecha']} · {r['descripcion']} · {_money(r['monto'])}",
        )


# ============================================================
# GASTOS
# ============================================================

def _render_gastos(client, user_id: str) -> None:
    st.subheader("📤 Registrar Gasto")
    categoria = st.selectbox("Categoría *", [""] + CATEGORIAS_GASTOS, key="gas_cat")
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
        r = fd.insertar_gasto(client, user_id, {
            "fecha": fecha.isoformat(), "descripcion": descripcion, "categoria": categoria,
            "subcategoria": subcategoria if subcategoria != "—" else "",
            "monto": monto, "cuenta": cuenta, "notas": notas,
        })
        _toast_ok(r["mensaje"]) if r["ok"] else _toast_err(r["mensaje"])

    df = fd.listar_gastos(client, user_id)
    if not df.empty:
        st.markdown("###### Tus gastos (editar / eliminar)")
        _tabla_editable(
            client, user_id, "gastos", df.sort_values("fecha", ascending=False),
            fd.actualizar_gasto, fd.eliminar_gasto,
            label_fn=lambda r: f"{r['fecha']} · {r['descripcion']} · {_money(r['monto'])}",
        )


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
        r = fd.insertar_deuda(client, user_id, {
            "acreedor": acreedor, "tipo": tipo, "estado": estado,
            "montoOriginal": monto_original, "montoPendiente": monto_pendiente,
            "cuotasTotales": cuotas_totales, "cuotasPagadas": cuotas_pagadas,
            "cuotaMensual": cuota_mensual, "tasaInteres": tasa_interes,
            "fechaInicio": fecha_inicio.isoformat(), "fechaVencimiento": fecha_vencimiento.isoformat(),
            "notas": notas,
        })
        _toast_ok(r["mensaje"]) if r["ok"] else _toast_err(r["mensaje"])

    df = fd.listar_deudas(client, user_id)
    if not df.empty:
        st.markdown("###### Tus deudas (editar / eliminar)")
        _tabla_editable(
            client, user_id, "deudas", df.sort_values("fecha_vencimiento"),
            fd.actualizar_deuda, fd.eliminar_deuda,
            label_fn=lambda r: f"{r['acreedor']} · {r['tipo']} · {_money(r['monto_pendiente'])} pendiente",
        )


# ============================================================
# INVERSIONES CORTO PLAZO
# ============================================================

def _render_inv_corto(client, user_id: str) -> None:
    st.subheader("⚡ Inversión Corto Plazo")
    _mostrar_flash()
    sub = st.radio(
        "", ["➕ Nueva", "📋 Mis inversiones", "🔁 Renovar / Cobrar"],
        horizontal=True, label_visibility="collapsed", key="ic_sub",
    )

    if sub == "➕ Nueva":
        with st.form("form_inv_corto", clear_on_submit=True):
            nombre = st.text_input("Nombre *", placeholder="Ej: Plazo Fijo Banco Nación…")
            col1, col2 = st.columns(2)
            tipo = col1.selectbox(
                "Tipo *", ["", "Plazo Fijo", "Crypto", "Fondos Comunes", "Bonos Corto", "Cuenta Remunerada", "Otros"]
            )
            estado = col2.selectbox("Estado", ["Activa", "Vencida", "Cancelada", "Renovada", "Cobrada"])
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
            r = fd.insertar_inv_corto(client, user_id, {
                "nombre": nombre, "tipo": tipo, "monto": monto, "tasa": tasa,
                "fechaInicio": fecha_inicio.isoformat(), "fechaVencimiento": fecha_vencimiento.isoformat(),
                "estado": estado, "notas": notas,
            })
            _toast_ok(r["mensaje"]) if r["ok"] else _toast_err(r["mensaje"])
        return

    df = fd.listar_inv_corto(client, user_id)

    if sub == "📋 Mis inversiones":
        if df.empty:
            st.caption("Todavía no hay inversiones cargadas.")
            return
        df_t = df.copy()
        df_t["monto_proyectado"] = df_t.apply(lambda r: fd.monto_proyectado_inv_corto(r), axis=1)
        st.caption("Podés editar las celdas directo en la tabla (el monto proyectado se calcula solo).")
        _tabla_editable(
            client, user_id, "inv_corto", df_t.sort_values("fecha_vencimiento"),
            fd.actualizar_inv_corto, fd.eliminar_inv_corto,
            label_fn=lambda r: f"{r['nombre']} · {r['tipo']} · {_money(r['monto'])} · {r['estado']}",
            solo_lectura=("monto_proyectado",),
        )
        return

    # ---- Renovar / Cobrar ----
    if df.empty:
        st.caption("No hay inversiones para renovar o cobrar.")
        return
    candidatas = df[df["estado"].isin(["Activa", "Vencida"])]
    if candidatas.empty:
        st.caption("No hay inversiones activas o vencidas.")
        return

    opciones = {
        f"{r['nombre']} · {_money(r['monto'])} · vence {r['fecha_vencimiento']}": r
        for _, r in candidatas.sort_values("fecha_vencimiento").iterrows()
    }
    sel = st.selectbox("Inversión", ["—"] + list(opciones.keys()), key="ic_sel")
    if sel == "—":
        return

    fila = opciones[sel]
    fid = int(fila["id"])
    proyectado = fd.monto_proyectado_inv_corto(fila)
    venc_actual = pd.to_datetime(fila["fecha_vencimiento"]).date()
    st.info(f"Capital: {_money(fila['monto'])} · Monto proyectado al vencimiento: **{_money(proyectado)}**")

    col_ren, col_cob = st.columns(2)

    with col_ren:
        st.markdown("###### 🔁 Renovar")
        nueva_venc = st.date_input(
            "Nuevo vencimiento", value=venc_actual + timedelta(days=30), key=f"ic_ren_venc_{fid}",
        )
        nueva_tasa = st.number_input(
            "Nueva tasa anual %", value=float(fila["tasa_anual"]) * 100, step=0.01, key=f"ic_ren_tasa_{fid}",
        )
        capitalizar = st.checkbox(
            "Capitalizar intereses (reinvertir capital + intereses)", value=True, key=f"ic_ren_cap_{fid}",
        )
        st.caption(f"Nuevo monto: {_money(proyectado if capitalizar else float(fila['monto']))}")
        if st.button("🔁 Confirmar renovación", key=f"ic_ren_btn_{fid}"):
            r = fd.renovar_inv_corto(client, user_id, fid, nueva_venc.isoformat(), nueva_tasa, capitalizar)
            _flash(r["ok"], r["mensaje"])
            st.rerun()

    with col_cob:
        st.markdown("###### ✅ Cobrar / Cerrar")
        cobrado = st.number_input(
            "Monto cobrado", min_value=0.0, value=float(round(proyectado, 2)), step=0.01, key=f"ic_cob_monto_{fid}",
        )
        carteras = fd.listar_carteras(client, user_id)
        nombres = {r["nombre"]: int(r["id"]) for _, r in carteras.iterrows()} if not carteras.empty else {}
        destino = st.selectbox(
            "Acreditar liquidez en cartera", ["— (no acreditar)"] + list(nombres.keys()), key=f"ic_cob_cart_{fid}",
        )
        if st.button("✅ Confirmar cobro", key=f"ic_cob_btn_{fid}"):
            r = fd.cobrar_inv_corto(client, user_id, fid, cobrado, nombres.get(destino))
            _flash(r["ok"], r["mensaje"])
            st.rerun()


# ============================================================
# INVERSIONES LARGO PLAZO
# ============================================================

SIMBOLOS_COMUNES = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META",
                    "SPY", "QQQ", "BTC-USD", "ETH-USD", "MELI", "YPFD"]


def _render_inv_largo(client, user_id: str) -> None:
    st.subheader("📈 Inversión Largo Plazo")
    _mostrar_flash()
    sub = st.radio(
        "", ["📋 Posiciones", "🗂️ Carteras", "💸 Vender / Cerrar"],
        horizontal=True, label_visibility="collapsed", key="il_sub",
    )

    df_cart = fd.listar_carteras(client, user_id)
    cart_por_nombre = {r["nombre"]: int(r["id"]) for _, r in df_cart.iterrows()} if not df_cart.empty else {}
    cart_por_id = {v: k for k, v in cart_por_nombre.items()}

    # ---------------- POSICIONES ----------------
    if sub == "📋 Posiciones":
        st.info("📡 El precio actual se trae en vivo con yfinance al cargar la sección.")
        with st.form("form_inv_largo", clear_on_submit=True):
            activo = st.text_input("Nombre del Activo *", placeholder="Ej: Apple Inc., Tesla…")
            col1, col2 = st.columns(2)
            tipo = col1.selectbox("Tipo *", ["", "Acción", "ETF", "Crypto", "Bono", "Fondo", "REIT", "Otro"])
            simbolo = col2.text_input("Símbolo (Ticker) *", placeholder="AAPL, TSLA…").upper()
            col1, col2 = st.columns(2)
            cantidad = col1.number_input("Cantidad *", min_value=0.0, step=0.0001, format="%.4f")
            precio_compra = col2.number_input("Precio Compra *", min_value=0.0, step=0.01)
            col1, col2, col3 = st.columns(3)
            fecha_compra = col1.date_input("Fecha Compra *", value=date.today())
            estado = col2.selectbox("Estado", ["Activo", "En espera"])
            cartera_sel = col3.selectbox("Cartera", ["Sin cartera"] + list(cart_por_nombre.keys()))
            notas = st.text_area("Notas")
            enviado = st.form_submit_button("📈 Registrar Inversión")

        st.caption("Símbolos comunes: " + ", ".join(SIMBOLOS_COMUNES))

        if enviado:
            if not activo or not tipo or not simbolo or not cantidad or not precio_compra:
                _toast_err("⚠️ Completá los campos obligatorios (*)")
                return
            r = fd.insertar_inv_largo(client, user_id, {
                "activo": activo, "tipo": tipo, "simbolo": simbolo, "cantidad": cantidad,
                "precioCompra": precio_compra, "fechaCompra": fecha_compra.isoformat(),
                "estado": estado, "notas": notas, "carteraId": cart_por_nombre.get(cartera_sel),
            })
            _toast_ok(f"✅ {activo} ({simbolo}) guardado") if r["ok"] else _toast_err(r["mensaje"])

        df = fd.listar_inv_largo_con_precios(client, user_id)
        if df.empty:
            return

        df_v = df.copy()
        df_v["ganancia_pct"] = df_v["ganancia_pct"] * 100
        df_v["cartera"] = df_v["cartera_id"].map(
            lambda x: cart_por_id.get(int(x), "—") if pd.notna(x) else "—"
        )
        columnas = ["activo", "simbolo", "cartera", "estado", "cantidad", "precio_compra", "precio_hoy",
                    "inversion_total", "valor_actual", "ganancia_perdida", "ganancia_pct"]
        st.dataframe(
            df_v[columnas], use_container_width=True, hide_index=True,
            column_config={
                "precio_hoy": st.column_config.NumberColumn("Precio actual / venta", format="$%.4f"),
                "precio_compra": st.column_config.NumberColumn("Precio compra", format="$%.4f"),
                "inversion_total": st.column_config.NumberColumn("Invertido", format="$%.2f"),
                "valor_actual": st.column_config.NumberColumn("Valor actual", format="$%.2f"),
                "ganancia_perdida": st.column_config.NumberColumn("Ganancia $", format="$%.2f"),
                "ganancia_pct": st.column_config.NumberColumn("Ganancia %", format="%.2f%%"),
            },
        )

        with st.expander("🗂️ Asignar un activo a una cartera"):
            activos_df = df[df["estado"].isin(["Activo", "En espera"])]
            if activos_df.empty or not cart_por_nombre:
                st.caption("Necesitás al menos un activo y una cartera creada.")
            else:
                ops = {
                    f"{r['activo']} ({r['simbolo']}) · {r['cantidad']} u.": int(r["id"])
                    for _, r in activos_df.iterrows()
                }
                a_sel = st.selectbox("Activo", list(ops.keys()), key="il_asig_activo")
                c_sel = st.selectbox("Cartera", ["Sin cartera"] + list(cart_por_nombre.keys()), key="il_asig_cart")
                if st.button("Asignar", key="il_asig_btn"):
                    r = fd.actualizar_inv_largo(client, user_id, ops[a_sel], {"cartera_id": cart_por_nombre.get(c_sel)})
                    _flash(r["ok"], r["mensaje"])
                    st.rerun()

        with st.expander("✏️ Editar / eliminar"):
            df_raw = fd.listar_inv_largo(client, user_id)
            _tabla_editable(
                client, user_id, "inv_largo", df_raw,
                fd.actualizar_inv_largo, fd.eliminar_inv_largo,
                label_fn=lambda r: f"{r['activo']} ({r['simbolo']}) · {r['cantidad']} u. · {r['estado']}",
                solo_lectura=("cartera_id",),
            )
        return

    # ---------------- CARTERAS ----------------
    if sub == "🗂️ Carteras":
        with st.form("form_cartera", clear_on_submit=True):
            col1, col2 = st.columns(2)
            nombre = col1.text_input("Nombre de la cartera *", placeholder="Ej: Largo plazo USA, Cripto…")
            efectivo = col2.number_input("Liquidez inicial", min_value=0.0, step=0.01)
            descripcion = st.text_input("Descripción")
            enviado = st.form_submit_button("🗂️ Crear cartera")
        if enviado:
            if not nombre:
                _toast_err("⚠️ Poné un nombre a la cartera")
            else:
                r = fd.insertar_cartera(client, user_id, {"nombre": nombre, "descripcion": descripcion, "efectivo": efectivo})
                _flash(r["ok"], r["mensaje"])
                st.rerun()

        res = fd.carteras_resumen(client, user_id)
        if res.empty:
            st.caption("Todavía no hay carteras.")
            return

        st.markdown("###### Resumen de carteras")
        st.dataframe(
            res.drop(columns=["cartera_id"]), use_container_width=True, hide_index=True,
            column_config={
                "cartera": "Cartera", "activos": "Activos",
                "invertido": st.column_config.NumberColumn("Invertido", format="$%.2f"),
                "valor_actual": st.column_config.NumberColumn("Valor actual", format="$%.2f"),
                "ganancia": st.column_config.NumberColumn("Ganancia $", format="$%.2f"),
                "rend_promedio_pct": st.column_config.NumberColumn("Rendimiento (promedio)", format="%.2f%%"),
                "rend_ponderado_pct": st.column_config.NumberColumn("Rendimiento (ponderado)", format="%.2f%%"),
                "efectivo": st.column_config.NumberColumn("Liquidez", format="$%.2f"),
                "total": st.column_config.NumberColumn("Total (valor + liquidez)", format="$%.2f"),
            },
        )
        st.caption(
            "Rendimiento (promedio) = promedio de (precio actual − compra) / compra de cada activo. "
            "Rendimiento (ponderado) = ganancia total $ / total invertido."
        )

        if cart_por_nombre:
            st.markdown("###### 💵 Ajustar liquidez")
            c1, c2, c3 = st.columns([2, 1.3, 1.3])
            c_liq = c1.selectbox("Cartera", list(cart_por_nombre.keys()), key="il_liq_cart")
            mov = c2.selectbox("Movimiento", ["Depositar", "Retirar"], key="il_liq_mov")
            m_liq = c3.number_input("Monto", min_value=0.0, step=0.01, key="il_liq_monto")
            if st.button("Aplicar", key="il_liq_btn"):
                if not m_liq:
                    _toast_err("⚠️ Ingresá un monto")
                else:
                    r = fd.ajustar_liquidez(
                        client, user_id, cart_por_nombre[c_liq], m_liq if mov == "Depositar" else -m_liq,
                    )
                    _flash(r["ok"], r["mensaje"])
                    st.rerun()

            st.markdown("###### Detalle por cartera")
            df_pos = fd.listar_inv_largo_con_precios(client, user_id)
            for nombre_c, cid in cart_por_nombre.items():
                with st.expander(f"🗂️ {nombre_c}"):
                    sub_df = (
                        df_pos[(df_pos["estado"] == "Activo") & (df_pos["cartera_id"] == cid)]
                        if not df_pos.empty else df_pos
                    )
                    if sub_df.empty:
                        st.caption("Sin activos en esta cartera.")
                    else:
                        d_v = sub_df[[
                            "activo", "simbolo", "cantidad", "precio_compra", "precio_hoy",
                            "ganancia_perdida", "ganancia_pct",
                        ]].copy()
                        d_v["ganancia_pct"] = d_v["ganancia_pct"] * 100
                        st.dataframe(
                            d_v, use_container_width=True, hide_index=True,
                            column_config={
                                "precio_compra": st.column_config.NumberColumn("Compra", format="$%.4f"),
                                "precio_hoy": st.column_config.NumberColumn("Actual", format="$%.4f"),
                                "ganancia_perdida": st.column_config.NumberColumn("Ganancia $", format="$%.2f"),
                                "ganancia_pct": st.column_config.NumberColumn("Ganancia %", format="%.2f%%"),
                            },
                        )

        with st.expander("✏️ Editar / eliminar carteras"):
            st.caption("Si eliminás una cartera, sus activos quedan 'Sin cartera' y se pierde su liquidez registrada.")
            _tabla_editable(
                client, user_id, "carteras", df_cart,
                fd.actualizar_cartera, fd.eliminar_cartera,
                label_fn=lambda r: f"{r['nombre']} · liquidez {_money(r['efectivo'])}",
                solo_lectura=("efectivo",),
            )
        return

    # ---------------- VENDER / CERRAR ----------------
    df = fd.listar_inv_largo(client, user_id)
    activos_df = df[df["estado"] == "Activo"] if not df.empty else df
    if activos_df.empty:
        st.caption("No hay posiciones activas para vender.")
    else:
        opciones = {
            f"{r['activo']} ({r['simbolo']}) · {r['cantidad']} u. @ {_money(r['precio_compra'])}": r
            for _, r in activos_df.iterrows()
        }
        sel = st.selectbox("Posición a vender", ["—"] + list(opciones.keys()), key="il_venta_sel")
        if sel != "—":
            pos = opciones[sel]
            pid = int(pos["id"])
            total = float(pos["cantidad"])
            precio_ref = fd.precio_actual(pos["simbolo"]) or float(pos["precio_compra"])

            col1, col2 = st.columns(2)
            cant_v = col1.number_input(
                "Cantidad a vender", min_value=0.0, max_value=total, value=total,
                step=0.0001, format="%.4f", key=f"il_v_cant_{pid}",
            )
            precio_v = col2.number_input(
                "Precio de venta", min_value=0.0, value=float(precio_ref),
                step=0.0001, format="%.4f", key=f"il_v_precio_{pid}",
            )
            col1, col2 = st.columns(2)
            fecha_v = col1.date_input("Fecha de venta", value=date.today(), key=f"il_v_fecha_{pid}")
            opciones_cart = ["— (no acreditar)"] + list(cart_por_nombre.keys())
            idx_def = 0
            if pd.notna(pos.get("cartera_id")) and int(pos["cartera_id"]) in cart_por_id:
                idx_def = opciones_cart.index(cart_por_id[int(pos["cartera_id"])])
            destino = col2.selectbox("Acreditar liquidez en", opciones_cart, index=idx_def, key=f"il_v_cart_{pid}")

            pnl = (precio_v - float(pos["precio_compra"])) * cant_v
            color = POS if pnl > 0 else NEG if pnl < 0 else "#9e9e9e"
            st.markdown(
                f"Producido: **{_money(cant_v * precio_v)}** · P&L realizado: "
                f"<span style='color:{color};font-weight:700'>{_money(pnl)}</span>",
                unsafe_allow_html=True,
            )
            if st.button("💸 Confirmar venta", key=f"il_v_btn_{pid}"):
                if not cant_v or not precio_v:
                    _toast_err("⚠️ Completá cantidad y precio de venta")
                else:
                    r = fd.vender_inv_largo(
                        client, user_id, pid, cant_v, precio_v, fecha_v.isoformat(), cart_por_nombre.get(destino),
                    )
                    _flash(r["ok"], r["mensaje"])
                    st.rerun()

    if not df.empty:
        vendidos = df[df["estado"] == "Vendido"].copy()
        if not vendidos.empty:
            st.markdown("###### 📜 Historial de ventas")
            vendidos["pnl_realizado"] = (vendidos["precio_venta"] - vendidos["precio_compra"]) * vendidos["cantidad"]
            st.dataframe(
                vendidos[["activo", "simbolo", "cantidad", "precio_compra", "precio_venta", "fecha_venta", "pnl_realizado"]],
                use_container_width=True, hide_index=True,
                column_config={"pnl_realizado": st.column_config.NumberColumn("P&L realizado", format="$%.2f")},
            )


# ============================================================
# TRADING
# ============================================================

def _estilizar_trading(df: pd.DataFrame):
    """Verde = ganando, rojo = perdiendo, gris = igual. Sin precio → sin color."""
    def _fila(fila):
        pnl = fila.get("pnl")
        if pnl is None or pd.isna(pnl):
            return [""] * len(fila)
        if abs(pnl) < 1e-9:
            estilo = "background-color: rgba(158,158,158,0.25); color: #e0e0e0"
        elif pnl > 0:
            estilo = "background-color: rgba(0,230,118,0.22)"
        else:
            estilo = "background-color: rgba(255,82,82,0.25)"
        return [estilo] * len(fila)

    return (
        df.style.apply(_fila, axis=1)
        .format({
            "cantidad": "{:,.4f}", "precio_entrada": "{:,.4f}", "precio_ref": "{:,.4f}",
            "pnl": "${:,.2f}", "pnl_pct": "{:+.2f}%",
        }, na_rep="—")
    )


def _render_trading(client, user_id: str) -> None:
    st.subheader("⚡ Registrar Operación de Trading")
    _mostrar_flash()
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
        r = fd.insertar_trading(client, user_id, {
            "simbolo": simbolo, "tipo": tipo, "direccion": direccion, "estado": estado_sel,
            "cantidad": cantidad, "precioEntrada": precio_entrada,
            "precioCierre": precio_cierre, "fechaEntrada": fecha_entrada.isoformat(),
            "fechaCierre": fecha_cierre.isoformat() if fecha_cierre else "",
            "stopLoss": stop_loss, "takeProfit": take_profit,
            "estrategia": estrategia, "notas": notas,
        })
        _toast_ok(f"✅ Operación {simbolo} guardada") if r["ok"] else _toast_err(r["mensaje"])

    st.divider()
    st.markdown("##### 📋 Cerrar Operación Abierta")
    abiertas = fd.operaciones_abiertas(client, user_id)
    if not abiertas:
        st.caption("No hay operaciones abiertas.")

    if abiertas:
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
                    _flash(r["ok"], r["mensaje"])
                    st.rerun()

    st.divider()
    st.markdown("##### 📊 Operaciones — 🟢 ganando · 🔴 perdiendo · ⚪ igual")
    df = fd.listar_trading_con_pnl(client, user_id)
    if df.empty:
        st.caption("Todavía no hay operaciones cargadas.")
        return

    df = df.sort_values("fecha_entrada", ascending=False)

    abiertas_df = df[df["estado"] == "Abierta"].dropna(subset=["pnl"])
    if not abiertas_df.empty:
        total_pnl = float(abiertas_df["pnl"].sum())
        st.metric("P&L no realizado (abiertas)", _money(total_pnl))

    columnas = ["fecha_entrada", "simbolo", "direccion", "estado", "cantidad",
                "precio_entrada", "precio_ref", "pnl", "pnl_pct", "resultado"]
    st.dataframe(
        _estilizar_trading(df[columnas]), use_container_width=True, hide_index=True,
        column_config={
            "precio_ref": "Precio actual / cierre",
            "pnl": "P&L $",
            "pnl_pct": "P&L %",
        },
    )

    with st.expander("✏️ Editar / eliminar operaciones"):
        _tabla_editable(
            client, user_id, "trading",
            df.drop(columns=["precio_ref", "pnl", "pnl_pct", "resultado"]),
            fd.actualizar_trading, fd.eliminar_trading,
            label_fn=lambda r: f"{r['simbolo']} · {r['direccion']} · {r['fecha_entrada']}",
        )


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
            r = fd.insertar_objetivo(client, user_id, {
                "nombre": nombre, "categoria": categoria, "meta": meta,
                "fechaInicio": fecha_inicio.isoformat(), "fechaMeta": fecha_meta.isoformat(),
                "estado": estado, "notas": notas,
            })
            _toast_ok(f"✅ Objetivo '{nombre}' guardado") if r["ok"] else _toast_err(r["mensaje"])

        df_obj = fd.listar_objetivos(client, user_id)
        if not df_obj.empty:
            st.markdown("###### Tus objetivos (editar / eliminar)")
            _tabla_editable(
                client, user_id, "objetivos", df_obj,
                fd.actualizar_objetivo, fd.eliminar_objetivo,
                label_fn=lambda r: f"{r['nombre']} · meta {_money(r['monto_meta'])}",
            )

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
            r = fd.insertar_aporte(client, user_id, {
                "objetivoId": opciones[objetivo_nombre], "fecha": fecha.isoformat(),
                "categoria": categoria, "monto": monto, "notas": notas,
            })
            _toast_ok(f"✅ Aporte de {_money(monto)} guardado") if r["ok"] else _toast_err(r["mensaje"])

        df_ap = fd.listar_aportes(client, user_id)
        if not df_ap.empty:
            st.markdown("###### Historial de aportes (editar / eliminar)")
            nombres_obj = {o["id"]: o["nombre"] for o in progreso}

            def _label_aporte(r):
                nombre_obj = nombres_obj.get(r["objetivo_id"], f"objetivo #{r['objetivo_id']}")
                return f"{r['fecha']} · {nombre_obj} · {_money(r['monto'])}"

            _tabla_editable(
                client, user_id, "aportes", df_ap.sort_values("fecha", ascending=False),
                fd.actualizar_aporte, fd.eliminar_aporte,
                label_fn=_label_aporte,
            )


# ============================================================
# ENTRYPOINT — llamar desde la app principal
# ============================================================

SECCIONES_FINANZAS = {
    "📊 Dashboard": "dashboard",
    "📥 Ingresos": "ingresos",
    "📤 Gastos": "gastos",
    "💳 Deudas": "deudas",
    "⚡ Corto Plazo": "inv_corto",
    "📈 Largo Plazo": "inv_largo",
    "🎯 Trading": "trading",
    "🏆 Objetivos": "objetivos",
}


def render_finanzas_personales(client, user_id: str) -> None:
    """Punto de entrada único. Llamar desde analizador_cuantitativo_v3.py
    con el client de Supabase y el user_id ya autenticados.

    No imprime título propio: el título/badge de la página ya los pone
    app.py a través del diccionario `titulos`/`badge_map`.

    Usa un selector explícito (no st.tabs) para que, al elegir una
    sección, se ejecute ÚNICAMENTE la función de esa sección — nada
    de otra sección corre ni se renderiza."""
    if "fin_seccion" not in st.session_state:
        st.session_state["fin_seccion"] = "📊 Dashboard"

    st.radio(
        "Sección", list(SECCIONES_FINANZAS.keys()),
        key="fin_seccion", horizontal=True, label_visibility="collapsed",
    )
    st.divider()

    seccion = SECCIONES_FINANZAS[st.session_state["fin_seccion"]]

    if seccion == "dashboard":
        _render_dashboard(client, user_id)
    elif seccion == "ingresos":
        _render_ingresos(client, user_id)
    elif seccion == "gastos":
        _render_gastos(client, user_id)
    elif seccion == "deudas":
        _render_deudas(client, user_id)
    elif seccion == "inv_corto":
        _render_inv_corto(client, user_id)
    elif seccion == "inv_largo":
        _render_inv_largo(client, user_id)
    elif seccion == "trading":
        _render_trading(client, user_id)
    elif seccion == "objetivos":
        _render_objetivos(client, user_id)


if __name__ == "__main__":
    st.warning(
        "Este módulo no se ejecuta solo: importalo desde tu app principal y llamá a "
        "render_finanzas_personales(client, user_id)."
    )
