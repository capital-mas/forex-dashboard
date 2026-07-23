# ============================================================
# finanzas_data.py
# Capa de datos del sistema de Finanzas Personales.
# Habla directo con Supabase (supabase-py) y con yfinance
# para precios en vivo. No contiene nada de Streamlit: se puede
# testear o reusar desde cualquier interfaz.
# ============================================================

from __future__ import annotations

from calendar import monthrange
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import pandas as pd

try:
    import yfinance as yf
except ImportError:  # yfinance es opcional si solo se usan módulos sin precios en vivo
    yf = None


# ============================================================
# CATEGORÍAS — fuente única de verdad, compartida por la capa
# de datos (para agrupar/desglosar) y la UI (para los selects).
# ============================================================

CATEGORIAS_INGRESOS = [
    "Salario", "Freelance", "Negocio", "Inversiones", "Alquiler", "Trading", "Regalo", "Otros",
]

SUBCATEGORIAS_GASTOS = {
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

CATEGORIAS_GASTOS = list(SUBCATEGORIAS_GASTOS.keys())


# ============================================================
# HELPERS INTERNOS
# ============================================================

def _rows(client, tabla: str, user_id: str) -> list[dict]:
    """Trae todas las filas de una tabla para un usuario."""
    resp = client.table(tabla).select("*").eq("user_id", user_id).execute()
    return resp.data or []


def _df(client, tabla: str, user_id: str) -> pd.DataFrame:
    """Igual que _rows pero como DataFrame (vacío con columnas si no hay datos)."""
    data = _rows(client, tabla, user_id)
    return pd.DataFrame(data)


def _mes_actual() -> tuple[int, int]:
    hoy = date.today()
    return hoy.month, hoy.year


def _filtrar_mes(df: pd.DataFrame, col_fecha: str, mes: int, anio: int) -> pd.DataFrame:
    if df.empty:
        return df
    fechas = pd.to_datetime(df[col_fecha])
    return df[(fechas.dt.month == mes) & (fechas.dt.year == anio)]


def _filtrar_rango(df: pd.DataFrame, col_fecha: str, inicio: date, fin: date) -> pd.DataFrame:
    """Filtra un DataFrame a un rango de fechas [inicio, fin] inclusive."""
    if df.empty:
        return df
    fechas = pd.to_datetime(df[col_fecha])
    return df[(fechas >= pd.Timestamp(inicio)) & (fechas <= pd.Timestamp(fin))]


def rango_dia(dia: date) -> tuple[date, date]:
    return dia, dia


def rango_mes(anio: int, mes: int) -> tuple[date, date]:
    return date(anio, mes, 1), date(anio, mes, monthrange(anio, mes)[1])


def rango_anio(anio: int) -> tuple[date, date]:
    return date(anio, 1, 1), date(anio, 12, 31)


def _mensaje_error_legible(e: Exception) -> str:
    """Traduce errores típicos de Supabase/Postgrest/red a un mensaje que
    tiene sentido para alguien que no sabe qué es un RLS o un JWT."""
    texto = str(e)
    bajo = texto.lower()
    if "row-level security" in bajo or "permission denied" in bajo:
        return "no tenés permiso para esta operación. Probá recargar la página e iniciar sesión de nuevo."
    if "jwt" in bajo or "expired" in bajo or "invalid token" in bajo or "unauthorized" in bajo or "401" in bajo:
        return "tu sesión expiró. Recargá la página e iniciá sesión de nuevo."
    if "violates foreign key" in bajo:
        return "el registro relacionado (por ejemplo, el objetivo) ya no existe."
    if "duplicate key" in bajo or "unique constraint" in bajo:
        return "ya existe un registro igual."
    if "timeout" in bajo or "connection" in bajo or "network" in bajo or "getaddrinfo" in bajo:
        return "problema de conexión con el servidor. Probá de nuevo en unos segundos."
    return texto[:200] if texto else "error desconocido."


def _insertar_fila(client, tabla: str, payload: dict, mensaje_ok: str) -> dict:
    """Inserta una fila. Nunca lanza excepción: siempre devuelve
    {'ok': bool, 'mensaje': str, 'id': int|None}."""
    try:
        resp = client.table(tabla).insert(payload).execute()
        if not resp.data:
            return {"ok": False, "mensaje": "⚠️ No se pudo guardar (el servidor no confirmó el registro).", "id": None}
        return {"ok": True, "mensaje": mensaje_ok, "id": resp.data[0].get("id")}
    except Exception as e:
        return {"ok": False, "mensaje": f"❌ No se pudo guardar: {_mensaje_error_legible(e)}", "id": None}


def _actualizar_fila(client, tabla: str, user_id: str, id_: int, cambios: dict) -> dict:
    """Actualiza una fila por id, acotado al propio user_id (además de la RLS).
    Nunca lanza excepción: siempre devuelve {'ok': bool, 'mensaje': str}."""
    if not cambios:
        return {"ok": False, "mensaje": "No había cambios para guardar."}
    try:
        resp = client.table(tabla).update(cambios).eq("id", id_).eq("user_id", user_id).execute()
        if not resp.data:
            return {"ok": False, "mensaje": "⚠️ No se pudo actualizar (¿el registro sigue existiendo?)."}
        return {"ok": True, "mensaje": "✅ Actualizado"}
    except Exception as e:
        return {"ok": False, "mensaje": f"❌ No se pudo actualizar: {_mensaje_error_legible(e)}"}


def _eliminar_fila(client, tabla: str, user_id: str, id_: int) -> dict:
    """Elimina una fila por id. Nunca lanza excepción: siempre devuelve
    {'ok': bool, 'mensaje': str}."""
    try:
        resp = client.table(tabla).delete().eq("id", id_).eq("user_id", user_id).execute()
        if not resp.data:
            return {"ok": False, "mensaje": "⚠️ No se pudo eliminar (¿el registro sigue existiendo?)."}
        return {"ok": True, "mensaje": "🗑️ Eliminado"}
    except Exception as e:
        return {"ok": False, "mensaje": f"❌ No se pudo eliminar: {_mensaje_error_legible(e)}"}


def precio_actual(simbolo: str) -> float | None:
    """Precio spot vía yfinance. Devuelve None si falla (símbolo inválido, sin conexión, etc.)."""
    if not simbolo or yf is None:
        return None
    try:
        t = yf.Ticker(simbolo)
        precio = t.fast_info.get("lastPrice") if hasattr(t, "fast_info") else None
        if not precio:
            hist = t.history(period="1d")
            if hist.empty:
                return None
            precio = float(hist["Close"].iloc[-1])
        return float(precio)
    except Exception:
        return None


def precios_actuales(simbolos: list[str]) -> dict[str, float | None]:
    """Versión en paralelo de precio_actual: pide todos los símbolos al
    mismo tiempo en vez de uno por uno. Para una cartera con varias
    posiciones, esto es la diferencia entre esperar 1 pedido o esperar N."""
    simbolos_unicos = sorted(set(s for s in simbolos if s))
    if not simbolos_unicos:
        return {}
    resultados: dict[str, float | None] = {}
    with ThreadPoolExecutor(max_workers=min(10, len(simbolos_unicos))) as ex:
        futuros = {ex.submit(precio_actual, s): s for s in simbolos_unicos}
        for fut in as_completed(futuros):
            simbolo = futuros[fut]
            resultados[simbolo] = fut.result()
    return resultados


# ============================================================
# INGRESOS
# ============================================================

def insertar_ingreso(client, user_id: str, d: dict) -> dict:
    payload = {
        "user_id": user_id,
        "fecha": d["fecha"],
        "descripcion": d["descripcion"],
        "categoria": d["categoria"],
        "monto": float(d["monto"]),
        "cuenta": d.get("cuenta", ""),
        "notas": d.get("notas", ""),
    }
    return _insertar_fila(client, "ingresos", payload, "✅ Ingreso guardado")


def listar_ingresos(client, user_id: str) -> pd.DataFrame:
    return _df(client, "ingresos", user_id)


def actualizar_ingreso(client, user_id: str, id_: int, cambios: dict) -> dict:
    return _actualizar_fila(client, "ingresos", user_id, id_, cambios)


def eliminar_ingreso(client, user_id: str, id_: int) -> dict:
    return _eliminar_fila(client, "ingresos", user_id, id_)


def resumen_ingresos_periodo(client, user_id: str, inicio: date, fin: date) -> float:
    df = listar_ingresos(client, user_id)
    df = _filtrar_rango(df, "fecha", inicio, fin)
    return float(df["monto"].sum()) if not df.empty else 0.0


def resumen_ingresos_mes(client, user_id: str, mes: int | None = None, anio: int | None = None) -> float:
    mes = mes or _mes_actual()[0]
    anio = anio or _mes_actual()[1]
    inicio, fin = rango_mes(anio, mes)
    return resumen_ingresos_periodo(client, user_id, inicio, fin)


def ingresos_por_categoria(client, user_id: str, inicio: date, fin: date) -> pd.DataFrame:
    """Desglose por TODAS las categorías de ingreso (incluye las que
    tuvieron $0 en el período, para que el listado quede completo)."""
    df = listar_ingresos(client, user_id)
    df = _filtrar_rango(df, "fecha", inicio, fin)
    if df.empty:
        montos = pd.Series(0.0, index=CATEGORIAS_INGRESOS, name="monto")
    else:
        montos = df.groupby("categoria")["monto"].sum()
        montos = montos.reindex(CATEGORIAS_INGRESOS, fill_value=0.0)
    montos.index.name = "categoria"
    return montos.reset_index().sort_values("monto", ascending=False)


# ============================================================
# GASTOS
# ============================================================

def insertar_gasto(client, user_id: str, d: dict) -> dict:
    payload = {
        "user_id": user_id,
        "fecha": d["fecha"],
        "descripcion": d["descripcion"],
        "categoria": d["categoria"],
        "subcategoria": d.get("subcategoria", ""),
        "monto": float(d["monto"]),
        "cuenta": d.get("cuenta", ""),
        "notas": d.get("notas", ""),
    }
    return _insertar_fila(client, "gastos", payload, "✅ Gasto guardado")


def listar_gastos(client, user_id: str) -> pd.DataFrame:
    return _df(client, "gastos", user_id)


def actualizar_gasto(client, user_id: str, id_: int, cambios: dict) -> dict:
    return _actualizar_fila(client, "gastos", user_id, id_, cambios)


def eliminar_gasto(client, user_id: str, id_: int) -> dict:
    return _eliminar_fila(client, "gastos", user_id, id_)


def resumen_gastos_periodo(client, user_id: str, inicio: date, fin: date) -> float:
    df = listar_gastos(client, user_id)
    df = _filtrar_rango(df, "fecha", inicio, fin)
    return float(df["monto"].sum()) if not df.empty else 0.0


def resumen_gastos_mes(client, user_id: str, mes: int | None = None, anio: int | None = None) -> float:
    mes = mes or _mes_actual()[0]
    anio = anio or _mes_actual()[1]
    inicio, fin = rango_mes(anio, mes)
    return resumen_gastos_periodo(client, user_id, inicio, fin)


def gastos_por_categoria(client, user_id: str, inicio: date, fin: date) -> pd.DataFrame:
    """Desglose por TODAS las categorías de gasto (incluye las que
    tuvieron $0 en el período, para que el listado quede completo)."""
    df = listar_gastos(client, user_id)
    df = _filtrar_rango(df, "fecha", inicio, fin)
    if df.empty:
        montos = pd.Series(0.0, index=CATEGORIAS_GASTOS, name="monto")
    else:
        montos = df.groupby("categoria")["monto"].sum()
        montos = montos.reindex(CATEGORIAS_GASTOS, fill_value=0.0)
    montos.index.name = "categoria"
    return montos.reset_index().sort_values("monto", ascending=False)


def balance_periodo(client, user_id: str, inicio: date, fin: date) -> float:
    return resumen_ingresos_periodo(client, user_id, inicio, fin) - resumen_gastos_periodo(client, user_id, inicio, fin)


def tasa_ahorro_periodo(client, user_id: str, inicio: date, fin: date) -> str:
    ing = resumen_ingresos_periodo(client, user_id, inicio, fin)
    if ing <= 0:
        return "0%"
    bal = balance_periodo(client, user_id, inicio, fin)
    return f"{(bal / ing) * 100:.1f}%"


def balance_mes(client, user_id: str) -> float:
    return resumen_ingresos_mes(client, user_id) - resumen_gastos_mes(client, user_id)


def tasa_ahorro(client, user_id: str) -> str:
    ing = resumen_ingresos_mes(client, user_id)
    if ing <= 0:
        return "0%"
    bal = balance_mes(client, user_id)
    return f"{(bal / ing) * 100:.1f}%"


# ============================================================
# DEUDAS
# ============================================================

def insertar_deuda(client, user_id: str, d: dict) -> dict:
    payload = {
        "user_id": user_id,
        "acreedor": d["acreedor"],
        "tipo": d["tipo"],
        "monto_original": float(d["montoOriginal"]),
        "monto_pendiente": float(d["montoPendiente"]),
        "cuotas_totales": int(d.get("cuotasTotales") or 0),
        "cuotas_pagadas": int(d.get("cuotasPagadas") or 0),
        "cuota_mensual": float(d.get("cuotaMensual") or 0),
        "tasa_interes": float(d.get("tasaInteres") or 0) / 100,
        "fecha_inicio": d["fechaInicio"],
        "fecha_vencimiento": d["fechaVencimiento"],
        "estado": d.get("estado", "Activa"),
        "notas": d.get("notas", ""),
    }
    return _insertar_fila(client, "deudas", payload, "✅ Deuda guardada")


def listar_deudas(client, user_id: str) -> pd.DataFrame:
    return _df(client, "deudas", user_id)


def actualizar_deuda(client, user_id: str, id_: int, cambios: dict) -> dict:
    return _actualizar_fila(client, "deudas", user_id, id_, cambios)


def eliminar_deuda(client, user_id: str, id_: int) -> dict:
    return _eliminar_fila(client, "deudas", user_id, id_)


def resumen_deudas(client, user_id: str) -> float:
    df = listar_deudas(client, user_id)
    if df.empty:
        return 0.0
    activas = df[df["estado"].isin(["Activa", "En mora"])]
    return float(activas["monto_pendiente"].sum())


def deuda_max(client, user_id: str) -> str:
    df = listar_deudas(client, user_id)
    if df.empty:
        return "Sin deudas"
    activas = df[df["estado"].isin(["Activa", "En mora"])]
    if activas.empty:
        return "Sin deudas"
    fila = activas.loc[activas["monto_pendiente"].idxmax()]
    return f"{fila['acreedor']}: ${fila['monto_pendiente']:.2f}"


def proximo_vencimiento_deuda(client, user_id: str) -> str:
    df = listar_deudas(client, user_id)
    if df.empty:
        return "Sin vencimientos"
    activas = df[df["estado"].isin(["Activa", "En mora"])].copy()
    if activas.empty:
        return "Sin vencimientos"
    activas["fecha_vencimiento"] = pd.to_datetime(activas["fecha_vencimiento"])
    futuras = activas[activas["fecha_vencimiento"] > pd.Timestamp.today()]
    if futuras.empty:
        return "Sin vencimientos"
    fila = futuras.loc[futuras["fecha_vencimiento"].idxmin()]
    return f"{fila['acreedor']}: {fila['fecha_vencimiento'].strftime('%d/%m/%Y')}"


# ============================================================
# INVERSIONES CORTO PLAZO
# ============================================================

def insertar_inv_corto(client, user_id: str, d: dict) -> dict:
    payload = {
        "user_id": user_id,
        "nombre": d["nombre"],
        "tipo": d["tipo"],
        "monto": float(d["monto"]),
        "tasa_anual": float(d.get("tasa") or 0) / 100,
        "fecha_inicio": d["fechaInicio"],
        "fecha_vencimiento": d["fechaVencimiento"],
        "estado": d.get("estado", "Activa"),
        "notas": d.get("notas", ""),
    }
    return _insertar_fila(client, "inversiones_corto", payload, "✅ Inversión corto plazo guardada")


def listar_inv_corto(client, user_id: str) -> pd.DataFrame:
    return _df(client, "inversiones_corto", user_id)


def actualizar_inv_corto(client, user_id: str, id_: int, cambios: dict) -> dict:
    return _actualizar_fila(client, "inversiones_corto", user_id, id_, cambios)


def eliminar_inv_corto(client, user_id: str, id_: int) -> dict:
    return _eliminar_fila(client, "inversiones_corto", user_id, id_)


def resumen_inv_corto(client, user_id: str) -> float:
    df = listar_inv_corto(client, user_id)
    if df.empty:
        return 0.0
    return float(df[df["estado"] == "Activa"]["monto"].sum())


def monto_proyectado_inv_corto(fila: dict) -> float:
    """Réplica de la fórmula de Sheets: monto * (1 + tasa * dias/365)."""
    inicio = pd.to_datetime(fila["fecha_inicio"])
    venc = pd.to_datetime(fila["fecha_vencimiento"])
    dias = (venc - inicio).days
    return float(fila["monto"]) * (1 + float(fila["tasa_anual"]) * (dias / 365))


# ============================================================
# INVERSIONES LARGO PLAZO
# El precio actual y la ganancia se calculan en vivo (no se guardan).
# ============================================================

def insertar_inv_largo(client, user_id: str, d: dict) -> dict:
    payload = {
        "user_id": user_id,
        "activo": d["activo"],
        "tipo": d["tipo"],
        "simbolo": str(d["simbolo"]).upper().strip(),
        "cantidad": float(d["cantidad"]),
        "precio_compra": float(d["precioCompra"]),
        "fecha_compra": d["fechaCompra"],
        "estado": d.get("estado", "Activo"),
        "notas": d.get("notas", ""),
    }
    return _insertar_fila(client, "inversiones_largo", payload, "✅ Inversión guardada")


def listar_inv_largo(client, user_id: str) -> pd.DataFrame:
    """Versión cruda (solo columnas de la tabla), para editar/eliminar sin
    arrastrar las columnas calculadas en vivo (precio_hoy, ganancia, etc.)."""
    return _df(client, "inversiones_largo", user_id)


def listar_inv_largo_con_precios(client, user_id: str) -> pd.DataFrame:
    """Devuelve la cartera de largo plazo con precio actual, valor
    actual, ganancia $ y ganancia % calculados en vivo con yfinance."""
    data = _rows(client, "inversiones_largo", user_id)
    if not data:
        return pd.DataFrame(
            columns=[
                "id", "activo", "tipo", "simbolo", "cantidad", "precio_compra",
                "precio_hoy", "inversion_total", "valor_actual",
                "ganancia_perdida", "ganancia_pct", "fecha_compra", "estado", "notas",
            ]
        )
    filas = []
    precios = precios_actuales([row["simbolo"] for row in data])
    for row in data:
        precio_hoy = precios.get(row["simbolo"])
        inversion_total = row["cantidad"] * row["precio_compra"]
        valor_actual = row["cantidad"] * precio_hoy if precio_hoy is not None else None
        ganancia = (valor_actual - inversion_total) if valor_actual is not None else None
        ganancia_pct = (ganancia / inversion_total) if (ganancia is not None and inversion_total) else None
        filas.append({
            **row,
            "precio_hoy": precio_hoy,
            "inversion_total": inversion_total,
            "valor_actual": valor_actual,
            "ganancia_perdida": ganancia,
            "ganancia_pct": ganancia_pct,
        })
    return pd.DataFrame(filas)


def actualizar_inv_largo(client, user_id: str, id_: int, cambios: dict) -> dict:
    return _actualizar_fila(client, "inversiones_largo", user_id, id_, cambios)


def eliminar_inv_largo(client, user_id: str, id_: int) -> dict:
    return _eliminar_fila(client, "inversiones_largo", user_id, id_)


def resumen_inv_largo(client, user_id: str) -> float:
    df = _df(client, "inversiones_largo", user_id)
    if df.empty:
        return 0.0
    activos = df[df["estado"] == "Activo"]
    return float((activos["cantidad"] * activos["precio_compra"]).sum())


def ganancia_total_inv_largo(client, user_id: str) -> float:
    df = listar_inv_largo_con_precios(client, user_id)
    if df.empty:
        return 0.0
    activos = df[df["estado"] == "Activo"]
    return float(activos["ganancia_perdida"].dropna().sum())


def rendimiento_total_inv(client, user_id: str) -> str:
    base = resumen_inv_corto(client, user_id) + resumen_inv_largo(client, user_id)
    if base <= 0:
        return "0%"
    return f"{(ganancia_total_inv_largo(client, user_id) / base) * 100:.2f}%"


# ============================================================
# TRADING
# ============================================================

def insertar_trading(client, user_id: str, d: dict) -> dict:
    payload = {
        "user_id": user_id,
        "fecha_entrada": d["fechaEntrada"],
        "fecha_cierre": d.get("fechaCierre") or None,
        "simbolo": str(d["simbolo"]).upper().strip(),
        "tipo": d["tipo"],
        "direccion": d["direccion"],
        "cantidad": float(d["cantidad"]),
        "precio_entrada": float(d["precioEntrada"]),
        "precio_cierre": float(d["precioCierre"]) if d.get("precioCierre") else None,
        "stop_loss": float(d.get("stopLoss") or 0) or None,
        "take_profit": float(d.get("takeProfit") or 0) or None,
        "estado": d.get("estado", "Abierta"),
        "estrategia": d.get("estrategia", ""),
        "notas": d.get("notas", ""),
    }
    return _insertar_fila(client, "trading", payload, "✅ Operación guardada")


def listar_trading(client, user_id: str) -> pd.DataFrame:
    return _df(client, "trading", user_id)


def actualizar_trading(client, user_id: str, id_: int, cambios: dict) -> dict:
    return _actualizar_fila(client, "trading", user_id, id_, cambios)


def eliminar_trading(client, user_id: str, id_: int) -> dict:
    return _eliminar_fila(client, "trading", user_id, id_)


def _pnl_operacion(direccion: str, precio_entrada: float, precio_ref: float, cantidad: float) -> float:
    if direccion == "Long (Compra)":
        return (precio_ref - precio_entrada) * cantidad
    return (precio_entrada - precio_ref) * cantidad


def operaciones_abiertas(client, user_id: str) -> list[dict]:
    """Lista de operaciones abiertas con precio actual y P&L no realizado, para el selector de cierre."""
    df = listar_trading(client, user_id)
    if df.empty:
        return []
    abiertas = df[df["estado"] == "Abierta"]
    precios = precios_actuales(abiertas["simbolo"].tolist())
    resultado = []
    for _, r in abiertas.iterrows():
        precio_hoy = precios.get(r["simbolo"])
        pnl = _pnl_operacion(r["direccion"], r["precio_entrada"], precio_hoy, r["cantidad"]) if precio_hoy else None
        resultado.append({
            "id": r["id"],
            "simbolo": r["simbolo"],
            "direccion": r["direccion"],
            "cantidad": r["cantidad"],
            "precio_entrada": r["precio_entrada"],
            "precio_actual": precio_hoy,
            "pnl_no_realizado": pnl,
            "fecha_entrada": r["fecha_entrada"],
        })
    return resultado


def cerrar_operacion(client, user_id: str, trade_id: int, precio_cierre: float, fecha_cierre: str) -> dict:
    """Cierra una operación de trading y devuelve el P&L realizado. Nunca
    lanza excepción: siempre devuelve {'ok': bool, 'mensaje': str}."""
    try:
        resp = client.table("trading").select("*").eq("id", trade_id).eq("user_id", user_id).execute()
        if not resp.data:
            return {"ok": False, "mensaje": f"❌ No se encontró la operación {trade_id}"}
        op = resp.data[0]
        pnl = _pnl_operacion(op["direccion"], op["precio_entrada"], precio_cierre, op["cantidad"])
        resp_upd = client.table("trading").update({
            "estado": "Cerrada",
            "precio_cierre": precio_cierre,
            "fecha_cierre": fecha_cierre,
        }).eq("id", trade_id).eq("user_id", user_id).execute()
        if not resp_upd.data:
            return {"ok": False, "mensaje": "⚠️ No se pudo confirmar el cierre (¿la operación sigue existiendo?)."}
        signo = "+" if pnl >= 0 else ""
        return {"ok": True, "mensaje": f"✅ Operación cerrada | P&L: {signo}${pnl:.2f}", "pnl": pnl}
    except Exception as e:
        return {"ok": False, "mensaje": f"❌ No se pudo cerrar la operación: {_mensaje_error_legible(e)}"}


def trading_pnl_realizado(client, user_id: str) -> float:
    df = listar_trading(client, user_id)
    if df.empty:
        return 0.0
    cerradas = df[df["estado"] == "Cerrada"].dropna(subset=["precio_cierre"])
    if cerradas.empty:
        return 0.0
    pnl = cerradas.apply(
        lambda r: _pnl_operacion(r["direccion"], r["precio_entrada"], r["precio_cierre"], r["cantidad"]), axis=1
    )
    return float(pnl.sum())


def trading_win_rate(client, user_id: str) -> str:
    df = listar_trading(client, user_id)
    if df.empty:
        return "0%"
    cerradas = df[df["estado"] == "Cerrada"].dropna(subset=["precio_cierre"])
    if cerradas.empty:
        return "0%"
    pnl = cerradas.apply(
        lambda r: _pnl_operacion(r["direccion"], r["precio_entrada"], r["precio_cierre"], r["cantidad"]), axis=1
    )
    wins = (pnl > 0).sum()
    return f"{(wins / len(cerradas)) * 100:.1f}%"


def trading_abiertas_count(client, user_id: str) -> int:
    df = listar_trading(client, user_id)
    if df.empty:
        return 0
    return int((df["estado"] == "Abierta").sum())


# ============================================================
# OBJETIVOS DE AHORRO + APORTES
# ============================================================

def insertar_objetivo(client, user_id: str, d: dict) -> dict:
    payload = {
        "user_id": user_id,
        "nombre": d["nombre"],
        "categoria": d["categoria"],
        "monto_meta": float(d["meta"]),
        "fecha_inicio": d["fechaInicio"],
        "fecha_meta": d["fechaMeta"],
        "estado": d.get("estado", "Activo"),
        "notas": d.get("notas", ""),
    }
    return _insertar_fila(client, "objetivos", payload, "✅ Objetivo guardado")


def listar_objetivos(client, user_id: str) -> pd.DataFrame:
    return _df(client, "objetivos", user_id)


def insertar_aporte(client, user_id: str, d: dict) -> dict:
    payload = {
        "user_id": user_id,
        "objetivo_id": int(d["objetivoId"]),
        "fecha": d["fecha"],
        "categoria": d.get("categoria", ""),
        "monto": float(d["monto"]),
        "notas": d.get("notas", ""),
    }
    return _insertar_fila(client, "aportes", payload, "✅ Aporte guardado")


def listar_aportes(client, user_id: str) -> pd.DataFrame:
    return _df(client, "aportes", user_id)


def actualizar_objetivo(client, user_id: str, id_: int, cambios: dict) -> dict:
    return _actualizar_fila(client, "objetivos", user_id, id_, cambios)


def eliminar_objetivo(client, user_id: str, id_: int) -> dict:
    """Al borrar un objetivo, sus aportes se eliminan en cascada (definido en el schema SQL)."""
    return _eliminar_fila(client, "objetivos", user_id, id_)


def actualizar_aporte(client, user_id: str, id_: int, cambios: dict) -> dict:
    return _actualizar_fila(client, "aportes", user_id, id_, cambios)


def eliminar_aporte(client, user_id: str, id_: int) -> dict:
    return _eliminar_fila(client, "aportes", user_id, id_)


def objetivos_con_progreso(client, user_id: str) -> list[dict]:
    """Objetivos activos con total aportado, faltante, % avance y aporte mensual sugerido."""
    objetivos = listar_objetivos(client, user_id)
    if objetivos.empty:
        return []
    aportes = listar_aportes(client, user_id)
    activos = objetivos[objetivos["estado"] == "Activo"]
    resultado = []
    hoy = pd.Timestamp.today()
    for _, o in activos.iterrows():
        propios = aportes[aportes["objetivo_id"] == o["id"]] if not aportes.empty else pd.DataFrame()
        aportado = float(propios["monto"].sum()) if not propios.empty else 0.0
        meta = float(o["monto_meta"])
        faltante = max(meta - aportado, 0.0)
        pct = min(aportado / meta, 1.0) if meta > 0 else 0.0
        fecha_meta = pd.to_datetime(o["fecha_meta"])
        dias_restantes = max((fecha_meta - hoy).days, 0)
        aporte_mensual = (
            "¡Meta cumplida!" if (faltante == 0 or dias_restantes <= 0)
            else faltante / max(dias_restantes / 30, 1)
        )
        resultado.append({
            "id": o["id"],
            "nombre": o["nombre"],
            "meta": meta,
            "aportado": aportado,
            "faltante": faltante,
            "pct": pct,
            "dias_restantes": dias_restantes,
            "aporte_mensual_sugerido": aporte_mensual,
        })
    return resultado


def objetivos_activos_count(client, user_id: str) -> int:
    df = listar_objetivos(client, user_id)
    if df.empty:
        return 0
    return int((df["estado"] == "Activo").sum())


def objetivos_ahorrado_total(client, user_id: str) -> float:
    progreso = objetivos_con_progreso(client, user_id)
    return sum(o["aportado"] for o in progreso)


def objetivos_faltante_total(client, user_id: str) -> float:
    progreso = objetivos_con_progreso(client, user_id)
    return sum(o["faltante"] for o in progreso)


def objetivo_mas_proximo(client, user_id: str) -> str:
    progreso = objetivos_con_progreso(client, user_id)
    candidatos = [o for o in progreso if o["pct"] < 1]
    if not candidatos:
        return "Sin objetivos"
    mejor = max(candidatos, key=lambda o: o["pct"])
    return f"{mejor['nombre']} ({mejor['pct'] * 100:.0f}%)"


# ============================================================
# DASHBOARD - RESUMEN GENERAL
# ============================================================

_ORDEN_NIVEL_ALERTA = {"error": 0, "warning": 1, "success": 2, "info": 3}


def obtener_alertas(client, user_id: str) -> list[dict]:
    """Junta alertas de deudas, inversiones, trading y objetivos en una sola
    lista, ordenada por severidad (errores primero). Cada alerta es
    {'nivel': 'error'|'warning'|'success'|'info', 'icono': str, 'mensaje': str}."""
    alertas: list[dict] = []
    hoy = pd.Timestamp.today().normalize()
    en_7_dias = hoy + pd.Timedelta(days=7)

    # ---- Deudas: en mora + vencimientos próximos ----
    deudas = listar_deudas(client, user_id)
    if not deudas.empty:
        deudas = deudas.copy()
        deudas["fecha_vencimiento"] = pd.to_datetime(deudas["fecha_vencimiento"])
        for _, d in deudas[deudas["estado"] == "En mora"].iterrows():
            alertas.append({
                "nivel": "error", "icono": "🔴",
                "mensaje": f"Deuda en mora: {d['acreedor']} — ${d['monto_pendiente']:,.2f} pendientes",
            })
        activas = deudas[deudas["estado"].isin(["Activa", "En mora"])]
        proximas = activas[(activas["fecha_vencimiento"] >= hoy) & (activas["fecha_vencimiento"] <= en_7_dias)]
        for _, d in proximas.iterrows():
            dias = (d["fecha_vencimiento"] - hoy).days
            cuando = "hoy" if dias == 0 else f"en {dias} día(s)"
            alertas.append({
                "nivel": "warning", "icono": "⏰",
                "mensaje": f"Vence {cuando}: {d['acreedor']} — ${d['monto_pendiente']:,.2f}",
            })

    # ---- Inversiones corto plazo por vencer ----
    inv_corto = listar_inv_corto(client, user_id)
    if not inv_corto.empty:
        inv_corto = inv_corto.copy()
        inv_corto["fecha_vencimiento"] = pd.to_datetime(inv_corto["fecha_vencimiento"])
        activas_ic = inv_corto[inv_corto["estado"] == "Activa"]
        proximas_ic = activas_ic[(activas_ic["fecha_vencimiento"] >= hoy) & (activas_ic["fecha_vencimiento"] <= en_7_dias)]
        for _, r in proximas_ic.iterrows():
            dias = (r["fecha_vencimiento"] - hoy).days
            cuando = "hoy" if dias == 0 else f"en {dias} día(s)"
            alertas.append({
                "nivel": "info", "icono": "💰",
                "mensaje": f"Vence {cuando}: {r['nombre']} — ${r['monto']:,.2f}",
            })

    # ---- Trading: operaciones abiertas que tocaron SL/TP ----
    trading = listar_trading(client, user_id)
    if not trading.empty:
        abiertas = trading[trading["estado"] == "Abierta"]
        if not abiertas.empty:
            precios = precios_actuales(abiertas["simbolo"].tolist())
            for _, r in abiertas.iterrows():
                precio = precios.get(r["simbolo"])
                if precio is None:
                    continue
                sl, tp = r.get("stop_loss"), r.get("take_profit")
                long = r["direccion"] == "Long (Compra)"
                toco_sl = sl and ((long and precio <= sl) or (not long and precio >= sl))
                toco_tp = tp and ((long and precio >= tp) or (not long and precio <= tp))
                if toco_sl:
                    alertas.append({
                        "nivel": "error", "icono": "🛑",
                        "mensaje": f"{r['simbolo']} tocó el Stop Loss (precio actual ${precio:.4f})",
                    })
                elif toco_tp:
                    alertas.append({
                        "nivel": "success", "icono": "🎯",
                        "mensaje": f"{r['simbolo']} alcanzó el Take Profit (precio actual ${precio:.4f})",
                    })

    # ---- Objetivos: atrasados, vencidos sin cumplir, recién cumplidos ----
    for o in objetivos_con_progreso(client, user_id):
        if o["pct"] >= 1:
            alertas.append({
                "nivel": "success", "icono": "🏆",
                "mensaje": f"¡Objetivo '{o['nombre']}' cumplido!",
            })
        elif o["dias_restantes"] <= 0:
            alertas.append({
                "nivel": "warning", "icono": "⌛",
                "mensaje": f"Objetivo '{o['nombre']}' venció sin completarse ({o['pct'] * 100:.0f}%)",
            })
        elif o["dias_restantes"] <= 30 and o["pct"] < 0.8:
            alertas.append({
                "nivel": "warning", "icono": "📉",
                "mensaje": f"Objetivo '{o['nombre']}' va atrasado: {o['pct'] * 100:.0f}% completado, quedan {o['dias_restantes']} días",
            })

    alertas.sort(key=lambda a: _ORDEN_NIVEL_ALERTA.get(a["nivel"], 9))
    return alertas


def obtener_dashboard_data(client, user_id: str, inicio: date | None = None, fin: date | None = None) -> dict:
    """Datos del dashboard para el período [inicio, fin]. Si no se pasa
    período, usa el mes actual (comportamiento previo por defecto)."""
    if inicio is None or fin is None:
        mes, anio = _mes_actual()
        inicio, fin = rango_mes(anio, mes)

    ingresos = resumen_ingresos_periodo(client, user_id, inicio, fin)
    gastos = resumen_gastos_periodo(client, user_id, inicio, fin)
    balance = ingresos - gastos
    tasa = f"{(balance / ingresos) * 100:.1f}%" if ingresos > 0 else "0%"

    return {
        "ingresos": ingresos,
        "gastos": gastos,
        "balance": balance,
        "tasa_ahorro": tasa,
        "gastos_por_categoria": gastos_por_categoria(client, user_id, inicio, fin),
        "ingresos_por_categoria": ingresos_por_categoria(client, user_id, inicio, fin),
        "deudas": resumen_deudas(client, user_id),
        "deuda_max": deuda_max(client, user_id),
        "proximo_vencimiento": proximo_vencimiento_deuda(client, user_id),
        "inv_corto": resumen_inv_corto(client, user_id),
        "inv_largo": resumen_inv_largo(client, user_id),
        "ganancia": ganancia_total_inv_largo(client, user_id),
        "rendimiento": rendimiento_total_inv(client, user_id),
        "trading_pnl": trading_pnl_realizado(client, user_id),
        "win_rate": trading_win_rate(client, user_id),
        "abiertas": trading_abiertas_count(client, user_id),
        "obj_activos": objetivos_activos_count(client, user_id),
        "obj_ahorrado": objetivos_ahorrado_total(client, user_id),
        "obj_faltante": objetivos_faltante_total(client, user_id),
        "obj_proximo": objetivo_mas_proximo(client, user_id),
    }
