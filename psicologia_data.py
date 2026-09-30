# ============================================================
# psicologia_data.py
# Capa de datos del módulo Psicología (sin Streamlit).
# Reusa los helpers de finanzas_data (insertar/actualizar/eliminar).
# ============================================================

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

import finanzas_data as fd

EMOCIONES_ANTES = [
    "Calma", "Confianza", "Duda", "Ansiedad", "FOMO", "Euforia",
    "Miedo", "Venganza (revenge)", "Aburrimiento", "Cansancio",
]
EMOCIONES_DESPUES = [
    "Calma", "Alivio", "Orgullo", "Euforia", "Frustración", "Culpa",
    "Enojo", "Miedo", "Indiferencia",
]

# Reglas del checklist diario de disciplina (columna, texto)
REGLAS = [
    ("respeto_stop", "Respeté mis stop loss (no los moví ni los saqué)"),
    ("respeto_tamano", "Respeté el tamaño de posición / riesgo por operación"),
    ("espero_setup", "Solo entré con mi setup completo (sin entradas 'por las dudas')"),
    ("sin_revenge", "No operé para recuperar una pérdida (sin revenge trading)"),
    ("sin_overtrading", "No superé mi cantidad máxima de operaciones del día"),
]

# Opciones para los selects del editor de finanzas_ui._tabla_editable
OPCIONES_EDICION = {
    "psico_diario": {
        "emocion_antes": EMOCIONES_ANTES,
        "emocion_despues": [""] + EMOCIONES_DESPUES,
    },
}

# ------------------------------------------------------------
# TESTS
# ------------------------------------------------------------

ESCALA = {1: "Nunca", 2: "Casi nunca", 3: "A veces", 4: "Casi siempre", 5: "Siempre"}

# Test FOMO: puntaje alto = más FOMO
TEST_FOMO = [
    "Entro a una operación porque el precio ya se está moviendo y no quiero perdérmela.",
    "Me cuesta no comprar un activo del que todo el mundo habla en redes.",
    "Persigo el precio: compro bastante más arriba de mi entrada planeada.",
    "Me angustia ver que otros ganan con algo que yo no tengo.",
    "Miro redes o chats de trading antes de decidir una operación.",
    "Cambio mi plan cuando veo un movimiento fuerte.",
    "Siento que si hoy no opero, pierdo una oportunidad única.",
    "Me arrepiento más de las oportunidades que no tomé que de mis pérdidas.",
]

# Test hábitos: puntaje alto = mejor hábito (todas las frases son 'positivas')
TEST_HABITOS = {
    "Planificación": [
        "Tengo un presupuesto mensual y lo reviso.",
        "Sé aproximadamente cuánto gasté el mes pasado.",
        "Tengo metas financieras escritas y con fecha.",
    ],
    "Ahorro": [
        "Ahorro o invierto una parte apenas cobro.",
        "Tengo un fondo de emergencia de al menos 3 meses de gastos.",
        "Mi ahorro no depende de lo que 'sobre' a fin de mes.",
    ],
    "Gasto emocional": [
        "Puedo esperar 24 hs antes de una compra no planificada.",
        "No compro para sentirme mejor después de un mal día.",
        "Decido mis gastos sin compararme con lo que gastan otros.",
    ],
    "Manejo de deuda": [
        "Pago la tarjeta completa, no el mínimo.",
        "Antes de endeudarme calculo cuánto termino pagando en total.",
        "Mis cuotas mensuales no superan el 30% de mi ingreso.",
    ],
}

CONSEJOS_HABITOS = {
    "Planificación": "Armá un presupuesto simple (necesidades / deseos / ahorro) y dedicá 15 min por semana a revisarlo.",
    "Ahorro": "Automatizá: transferí un % fijo el día que cobrás. Lo que no ves, no lo gastás.",
    "Gasto emocional": "Regla de las 24 hs: anotá la compra no planificada y decidí al día siguiente.",
    "Manejo de deuda": "Listá tus deudas por tasa y atacá primero la más cara. Nada de pagar solo el mínimo.",
}


def puntaje_fomo(respuestas: list[int]) -> float:
    """Normaliza la suma (8–40) a 0–100."""
    n = len(respuestas)
    return round((sum(respuestas) - n) / (4 * n) * 100, 1)


def nivel_fomo(p: float) -> tuple[str, str]:
    if p < 30:
        return "🟢 Bajo", "Operás con bastante independencia del ruido. Mantené tu checklist de entrada."
    if p < 60:
        return "🟡 Moderado", "El FOMO aparece en momentos puntuales. Sumá una regla: no entrar si el precio ya se alejó X% de tu nivel."
    return "🔴 Alto", (
        "El mercado te está manejando a vos. Medidas concretas: órdenes límite en vez de a mercado, "
        "cero redes antes de operar y máximo de operaciones por día."
    )


def puntajes_habitos(respuestas: dict[str, list[int]]) -> dict[str, float]:
    out = {}
    for dim, vals in respuestas.items():
        n = len(vals)
        out[dim] = round((sum(vals) - n) / (4 * n) * 100, 1)
    return out


# ------------------------------------------------------------
# CRUD
# ------------------------------------------------------------

def insertar_diario(client, user_id: str, d: dict) -> dict:
    payload = {
        "user_id": user_id,
        "fecha": d["fecha"],
        "simbolo": (d.get("simbolo") or "").upper().strip() or None,
        "trade_id": int(d["trade_id"]) if d.get("trade_id") else None,
        "emocion_antes": d["emocion_antes"],
        "emocion_despues": d.get("emocion_despues") or None,
        "intensidad": int(d.get("intensidad") or 3),
        "siguio_plan": bool(d.get("siguio_plan", True)),
        "disparador": d.get("disparador", ""),
        "leccion": d.get("leccion", ""),
    }
    return fd._insertar_fila(client, "psico_diario", payload, "✅ Entrada del diario guardada")


def listar_diario(client, user_id: str) -> pd.DataFrame:
    return fd._df(client, "psico_diario", user_id)


def actualizar_diario(client, user_id: str, id_: int, cambios: dict) -> dict:
    return fd._actualizar_fila(client, "psico_diario", user_id, id_, cambios)


def eliminar_diario(client, user_id: str, id_: int) -> dict:
    return fd._eliminar_fila(client, "psico_diario", user_id, id_)


def guardar_disciplina(client, user_id: str, fecha: str, checks: dict, notas: str = "") -> dict:
    """Un registro por día: si ya existe, se pisa (upsert por user_id+fecha)."""
    puntaje = int(round(sum(bool(checks[c]) for c, _ in REGLAS) / len(REGLAS) * 100))
    payload = {"user_id": user_id, "fecha": fecha, "puntaje": puntaje, "notas": notas,
               **{c: bool(checks[c]) for c, _ in REGLAS}}
    try:
        resp = client.table("psico_disciplina").upsert(payload, on_conflict="user_id,fecha").execute()
        if not resp.data:
            return {"ok": False, "mensaje": "⚠️ No se pudo guardar (el servidor no confirmó)."}
        return {"ok": True, "mensaje": f"✅ Día registrado — disciplina {puntaje}%"}
    except Exception as e:
        return {"ok": False, "mensaje": f"❌ No se pudo guardar: {fd._mensaje_error_legible(e)}"}


def listar_disciplina(client, user_id: str) -> pd.DataFrame:
    df = fd._df(client, "psico_disciplina", user_id)
    return df.sort_values("fecha", ascending=False) if not df.empty else df


def insertar_test(client, user_id: str, tipo: str, puntaje: float, detalle: dict | None = None) -> dict:
    payload = {"user_id": user_id, "fecha": date.today().isoformat(),
               "tipo": tipo, "puntaje": float(puntaje), "detalle": detalle}
    return fd._insertar_fila(client, "psico_tests", payload, "✅ Resultado guardado")


def listar_tests(client, user_id: str, tipo: str) -> pd.DataFrame:
    df = fd._df(client, "psico_tests", user_id)
    if df.empty:
        return df
    df = df[df["tipo"] == tipo].copy()
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df.sort_values(["fecha", "id"])


# ------------------------------------------------------------
# ESTADÍSTICAS
# ------------------------------------------------------------

def racha_disciplina(df: pd.DataFrame, umbral: int = 80) -> int:
    """Días registrados consecutivos (del más reciente hacia atrás) con puntaje >= umbral."""
    if df.empty:
        return 0
    racha = 0
    for p in df.sort_values("fecha", ascending=False)["puntaje"]:
        if p >= umbral:
            racha += 1
        else:
            break
    return racha


def _trades_cerrados_con_pnl(client, user_id: str) -> pd.DataFrame:
    df = fd.listar_trading(client, user_id)
    if df.empty:
        return df
    c = df[(df["estado"] == "Cerrada") & df["precio_cierre"].notna()].copy()
    if c.empty:
        return c
    c["pnl"] = c.apply(
        lambda r: fd._pnl_operacion(r["direccion"], r["precio_entrada"], r["precio_cierre"], r["cantidad"]), axis=1
    )
    return c


def diario_vs_resultados(client, user_id: str) -> pd.DataFrame:
    """Por emoción previa: cantidad, % que siguió el plan y P&L promedio (solo
    entradas vinculadas a una operación cerrada)."""
    diario = listar_diario(client, user_id)
    if diario.empty:
        return diario
    cerrados = _trades_cerrados_con_pnl(client, user_id)
    pnl_map = {int(r["id"]): float(r["pnl"]) for _, r in cerrados.iterrows()} if not cerrados.empty else {}
    diario = diario.copy()
    diario["pnl"] = diario["trade_id"].map(lambda x: pnl_map.get(int(x)) if pd.notna(x) else None)
    g = diario.groupby("emocion_antes").agg(
        entradas=("id", "count"),
        plan_pct=("siguio_plan", lambda s: float(s.mean()) * 100),
        pnl_promedio=("pnl", "mean"),
    ).reset_index()
    return g.sort_values("entradas", ascending=False)


def efecto_disposicion(client, user_id: str) -> dict | None:
    """Compara cuánto tiempo aguantás las ganadoras vs las perdedoras (trading cerrado)."""
    c = _trades_cerrados_con_pnl(client, user_id)
    c = c[c["fecha_cierre"].notna()] if not c.empty else c
    if c.empty or len(c) < 5:
        return None
    c = c.copy()
    c["dias"] = (pd.to_datetime(c["fecha_cierre"]) - pd.to_datetime(c["fecha_entrada"])).dt.days
    gan, per = c[c["pnl"] > 0], c[c["pnl"] < 0]
    if gan.empty or per.empty:
        return None
    return {
        "n": len(c), "n_gan": len(gan), "n_per": len(per),
        "dias_gan": float(gan["dias"].mean()), "dias_per": float(per["dias"].mean()),
        "pnl_gan": float(gan["pnl"].mean()), "pnl_per": float(per["pnl"].mean()),
    }


# ------------------------------------------------------------
# SIMULACIONES
# ------------------------------------------------------------

def simular_resultado(ganancia: float, perdida: float, prob: float, n_ops: int,
                      n_sim: int = 2000, seed: int | None = None) -> np.ndarray:
    """Resultado final (suma de n_ops apuestas de monto fijo) en n_sim escenarios."""
    rng = np.random.default_rng(seed)
    gana = rng.random((n_sim, n_ops)) < prob
    return np.where(gana, ganancia, -perdida).sum(axis=1)


def racha_perdedora_max(prob_win: float, n_ops: int, n_sim: int = 3000, seed: int | None = None) -> np.ndarray:
    """Racha perdedora más larga en cada uno de n_sim escenarios de n_ops operaciones."""
    rng = np.random.default_rng(seed)
    pierde = rng.random((n_sim, n_ops)) >= prob_win
    actual = np.zeros(n_sim, dtype=int)
    maximo = np.zeros(n_sim, dtype=int)
    for j in range(n_ops):
        actual = (actual + 1) * pierde[:, j]
        maximo = np.maximum(maximo, actual)
    return maximo


def ganancia_para_recuperar(perdida_pct: float) -> float:
    """Pérdida 50% -> necesitás +100%."""
    if perdida_pct >= 100:
        return float("inf")
    return (1 / (1 - perdida_pct / 100) - 1) * 100


# ============================================================
# SALUD FINANCIERA, TEST DE ESTRÉS E IMPACTO
# ============================================================

def _puntos(valor: float, bueno: float, malo: float) -> float:
    """100 si valor está en 'bueno', 0 si está en 'malo', lineal en el medio.
    Sirve para 'menor es mejor' (bueno < malo) y para 'mayor es mejor' (bueno > malo)."""
    if bueno == malo:
        return 100.0
    return float(max(0.0, min(100.0, (valor - malo) / (bueno - malo) * 100)))


def _nivel_score(score: float) -> str:
    return "success" if score >= 70 else "warning" if score >= 40 else "error"


def salud_financiera(client, user_id: str, meses: int = 3) -> dict:
    """Indicadores de salud financiera con el promedio mensual de los últimos `meses`.
    - cuotas: cuota mensual de deudas activas (si no la cargaste, se usa lo gastado en la
      categoría 'Deudas' para no subestimar la carga).
    - capacidad = ingresos - gastos de vida (sin la categoría 'Deudas') - cuotas.
    - liquidez = efectivo de carteras + inversiones de corto plazo activas."""
    hoy = date.today()
    y, m = hoy.year, hoy.month - (meses - 1)
    while m <= 0:
        m += 12
        y -= 1
    inicio = date(y, m, 1)

    ing_df = fd._filtrar_rango(fd.listar_ingresos(client, user_id), "fecha", inicio, hoy)
    gas_df = fd._filtrar_rango(fd.listar_gastos(client, user_id), "fecha", inicio, hoy)
    ingresos = float(ing_df["monto"].sum()) / meses if not ing_df.empty else 0.0
    gastos_total = float(gas_df["monto"].sum()) / meses if not gas_df.empty else 0.0
    gastos_deuda = (float(gas_df[gas_df["categoria"] == "Deudas"]["monto"].sum()) / meses
                    if not gas_df.empty else 0.0)
    gastos_vida = gastos_total - gastos_deuda

    deudas = fd.listar_deudas(client, user_id)
    activas = deudas[deudas["estado"].isin(["Activa", "En mora"])] if not deudas.empty else deudas
    cuotas_deudas = float(activas["cuota_mensual"].fillna(0).sum()) if not activas.empty else 0.0
    deuda_total = float(activas["monto_pendiente"].fillna(0).sum()) if not activas.empty else 0.0
    en_mora = int((deudas["estado"] == "En mora").sum()) if not deudas.empty else 0
    cuotas = max(cuotas_deudas, gastos_deuda)

    carteras = fd.listar_carteras(client, user_id)
    liquidez = (float(carteras["efectivo"].fillna(0).sum()) if not carteras.empty else 0.0) \
        + fd.resumen_inv_corto(client, user_id)

    capacidad = ingresos - gastos_vida - cuotas
    base_egresos = gastos_vida + cuotas
    s = {
        "ingresos": ingresos, "gastos_vida": gastos_vida, "cuotas": cuotas, "cuotas_deudas": cuotas_deudas,
        "deuda_total": deuda_total, "en_mora": en_mora, "liquidez": liquidez, "capacidad": capacidad,
        "dti": cuotas / ingresos if ingresos > 0 else None,
        "ratio_gasto": gastos_vida / ingresos if ingresos > 0 else None,
        "ahorro": capacidad / ingresos if ingresos > 0 else None,
        "meses_autonomia": liquidez / base_egresos if base_egresos > 0 else None,
        "meses": meses, "score": None, "componentes": {}, "nivel": "info",
    }
    if ingresos > 0:
        comp = {
            "Carga de deuda": _puntos(s["dti"], 0.15, 0.40),
            "Ahorro": _puntos(s["ahorro"], 0.20, 0.0),
            "Gasto / Ingreso": _puntos(s["ratio_gasto"], 0.50, 0.90),
            "Sin mora": 100.0 if en_mora == 0 else 0.0,
        }
        pesos = {"Carga de deuda": 0.35, "Ahorro": 0.30, "Gasto / Ingreso": 0.20, "Sin mora": 0.15}
        s["componentes"] = comp
        s["score"] = sum(comp[k] * pesos[k] for k in comp)
        s["nivel"] = _nivel_score(s["score"])
    return s


def test_estres(s: dict, caida_ingresos_pct: float, suba_cuotas_pct: float, gasto_extra: float) -> dict:
    """Recalcula capacidad de inversión, carga de deuda y autonomía bajo un escenario adverso."""
    ing = s["ingresos"] * (1 - caida_ingresos_pct / 100)
    cuotas = s["cuotas"] * (1 + suba_cuotas_pct / 100)
    cap = ing - s["gastos_vida"] - cuotas - gasto_extra
    libre_sin_deuda = ing - s["gastos_vida"] - gasto_extra
    egresos = s["gastos_vida"] + cuotas + gasto_extra
    dti = cuotas / ing if ing > 0 else None
    pct_abs = (cuotas / libre_sin_deuda) if libre_sin_deuda > 0 else None
    if cap < 0:
        nivel = "error"
    elif (dti is not None and dti > 0.35) or cap < 0.05 * max(ing, 1) or (pct_abs is not None and pct_abs > 0.6):
        nivel = "warning"
    else:
        nivel = "success"
    return {
        "ingresos": ing, "cuotas": cuotas, "capacidad": cap, "dti": dti, "nivel": nivel,
        "pct_absorbido": pct_abs,
        "meses_autonomia": s["liquidez"] / egresos if egresos > 0 else None,
    }


def impacto_gasto(client, user_id: str, monto: float, fecha: str) -> dict:
    """Aviso de impacto de un gasto recién registrado sobre el mes en que cae."""
    f = date.fromisoformat(fecha)
    inicio, fin = fd.rango_mes(f.year, f.month)
    ing = fd.resumen_ingresos_periodo(client, user_id, inicio, fin)
    gas = fd.resumen_gastos_periodo(client, user_id, inicio, fin)
    if ing <= 0:
        return {"nivel": "info", "mensaje": "No hay ingresos cargados en ese mes: cargalos para medir el impacto de tus gastos."}
    antes = (ing - (gas - monto)) / ing * 100
    despues = (ing - gas) / ing * 100
    pct = monto / ing * 100
    msg = (f"Este gasto es el {pct:.1f}% de tus ingresos del mes. "
           f"Tu tasa de ahorro pasó de {antes:.1f}% a {despues:.1f}%.")
    if despues < 0:
        return {"nivel": "error", "mensaje": msg + " Ya gastaste más de lo que ingresó este mes: frená gastos no esenciales."}
    if pct >= 15 or despues < 10:
        return {"nivel": "warning", "mensaje": msg + " Antes de repetir un gasto así, preguntate si es necesidad o impulso (regla de las 24 hs)."}
    return {"nivel": "success", "mensaje": msg + " Sigue dentro de un margen sano."}


def impacto_deuda(client, user_id: str, cuota_mensual: float, monto_pendiente: float) -> dict:
    """Aviso de impacto de una deuda recién registrada sobre carga de deuda y capacidad de inversión."""
    s = salud_financiera(client, user_id)
    ing = s["ingresos"]
    if ing <= 0:
        return {"nivel": "info", "mensaje": "Cargá tus ingresos de los últimos meses para medir cuánto pesa esta deuda."}
    antes = max(s["cuotas_deudas"] - cuota_mensual, 0) / ing * 100
    despues = s["dti"] * 100
    cap_antes = s["capacidad"] + (s["cuotas"] - max(s["cuotas"] - cuota_mensual, 0))
    msg = (f"Tus cuotas pasan del {antes:.1f}% al {despues:.1f}% de tus ingresos. "
           f"Capacidad de inversión mensual: ${cap_antes:,.0f} → ${s['capacidad']:,.0f}.")
    if despues >= 35 or s["capacidad"] < 0:
        return {"nivel": "error", "mensaje": msg + " La deuda ya te quita libertad para invertir; hacé el Test de estrés antes de sumar más."}
    if despues >= 25:
        return {"nivel": "warning", "mensaje": msg + " Estás cerca del límite sano (30%). Priorizá cancelar la deuda más cara."}
    return {"nivel": "success", "mensaje": msg + " Carga de deuda manejable."}


# ============================================================
# PROYECCIONES (Psicología del Dinero)
# ============================================================

def proyeccion_compuesta(capital: float, aporte_mensual: float, tasa_anual_pct: float,
                         anios: int, inflacion_pct: float = 0.0) -> pd.DataFrame:
    """Evolución año a año con capitalización mensual y aporte al final de cada mes."""
    r_m = (1 + tasa_anual_pct / 100) ** (1 / 12) - 1
    i_m = (1 + inflacion_pct / 100) ** (1 / 12) - 1
    saldo = aportado = float(capital)
    filas = [{"anio": 0, "aportado": aportado, "total": saldo, "total_real": saldo}]
    for mes in range(1, int(anios) * 12 + 1):
        saldo = saldo * (1 + r_m) + aporte_mensual
        aportado += aporte_mensual
        if mes % 12 == 0:
            filas.append({"anio": mes // 12, "aportado": aportado, "total": saldo,
                          "total_real": saldo / ((1 + i_m) ** mes)})
    df = pd.DataFrame(filas)
    df["intereses"] = df["total"] - df["aportado"]
    df["interes_anio"] = df["total"].diff() - aporte_mensual * 12
    return df


def costo_de_esperar(capital: float, aporte: float, tasa: float, anios: int, espera: int) -> pd.DataFrame:
    """Empezar hoy vs. empezar dentro de `espera` años (mismo horizonte final)."""
    hoy = proyeccion_compuesta(capital, aporte, tasa, anios)
    tarde = proyeccion_compuesta(capital, aporte, tasa, max(anios - espera, 0))
    tarde["anio"] += espera
    previo = pd.DataFrame({"anio": range(0, int(espera)), "total": float(capital)})
    tarde_total = pd.concat([previo, tarde[["anio", "total"]]]).rename(columns={"total": "esperar"})
    df = pd.DataFrame({"anio": hoy["anio"], "empezar_hoy": hoy["total"].values})
    return df.merge(tarde_total, on="anio", how="left")


def montecarlo_proyeccion(capital: float, aporte_mensual: float, mu_pct: float, sigma_pct: float,
                          anios: int, n_sim: int = 1000, seed: int | None = 11):
    """Trayectorias con rendimientos anuales aleatorios. Devuelve (df percentiles,
    prob. de terminar por debajo de lo aportado, prob. de un año negativo)."""
    rng = np.random.default_rng(seed)
    rets = np.clip(rng.normal(mu_pct / 100, sigma_pct / 100, (n_sim, int(anios))), -0.95, None)
    saldo = np.full(n_sim, float(capital))
    cols = [saldo.copy()]
    for t in range(int(anios)):
        saldo = saldo * (1 + rets[:, t]) + aporte_mensual * 12
        cols.append(saldo.copy())
    M = np.vstack(cols).T
    df = pd.DataFrame({
        "anio": range(int(anios) + 1),
        "p10": np.percentile(M, 10, axis=0),
        "p50": np.percentile(M, 50, axis=0),
        "p90": np.percentile(M, 90, axis=0),
    })
    aportado = capital + aporte_mensual * 12 * anios
    return df, float((M[:, -1] < aportado).mean()), float((rets < 0).mean())


# ============================================================
# PRE-OPERATIVO Y CONTROL ANTI-OVERTRADING (Psicotrading)
# ============================================================

# estado -> (emoji, nivel, mensaje)
ESTADOS_PREOP = {
    "Calma": ("😌", "success", "Buen estado para operar. Mantené tu plan."),
    "Ansioso": ("😰", "warning", "La ansiedad acorta tu paciencia y te hace entrar antes de tiempo. Reducí el tamaño o esperá la confirmación."),
    "Eufórico": ("🤩", "warning", "La euforia sube el riesgo sin que lo notes. No aumentes el tamaño: operá igual que siempre o esperá."),
    "Enojado / Revenge": ("😡", "error", "Operar enojado es revenge trading. Levantate de la pantalla; hoy no se opera en este estado."),
    "Cansado / Distraído": ("😴", "warning", "Sin foco se te escapan stops y errores de ejecución. Si operás, tamaño mínimo."),
}

CHECKS_PRE = [
    ("setup", "Tengo mi setup completo y lo puedo explicar en una frase"),
    ("stop", "Definí stop loss y objetivo ANTES de entrar"),
    ("tamano", "El tamaño respeta mi riesgo por operación (no lo subí por emoción)"),
    ("no_revenge", "No busco recuperar una pérdida ni 'aprovechar la racha'"),
    ("pausa", "Esperé al menos 2 minutos desde que vi la señal"),
]

CFG_DEFAULT = {"max_ops_dia": 3, "max_perdidas_seguidas": 3, "max_ganancias_seguidas": 4, "perdida_diaria_max": 0.0}


def obtener_config(client, user_id: str) -> dict:
    try:
        resp = client.table("psico_config").select("*").eq("user_id", user_id).execute()
        if resp.data:
            fila = resp.data[0]
            return {k: (fila[k] if fila.get(k) is not None else v) for k, v in CFG_DEFAULT.items()}
    except Exception:
        pass
    return dict(CFG_DEFAULT)


def guardar_config(client, user_id: str, cfg: dict) -> dict:
    payload = {"user_id": user_id, **{k: cfg[k] for k in CFG_DEFAULT}}
    try:
        resp = client.table("psico_config").upsert(payload, on_conflict="user_id").execute()
        if not resp.data:
            return {"ok": False, "mensaje": "⚠️ No se pudo guardar (el servidor no confirmó)."}
        return {"ok": True, "mensaje": "✅ Límites guardados"}
    except Exception as e:
        return {"ok": False, "mensaje": f"❌ No se pudo guardar: {fd._mensaje_error_legible(e)}"}


def estado_control(client, user_id: str, cfg: dict, estado_emocional: str | None = None) -> dict:
    """Evalúa operaciones de hoy, racha actual y P&L del día contra tus límites.
    Devuelve alertas [(nivel, mensaje)] y un nivel global (success/warning/error)."""
    hoy = date.today()
    tr = fd.listar_trading(client, user_id)
    ops_hoy = 0
    if not tr.empty:
        vigentes = tr[tr["estado"] != "Cancelada"]
        ops_hoy = int((pd.to_datetime(vigentes["fecha_entrada"]).dt.date == hoy).sum()) if not vigentes.empty else 0

    racha_tipo, racha_n, pnl_hoy = None, 0, 0.0
    cerr = _trades_cerrados_con_pnl(client, user_id)
    if not cerr.empty:
        cerr = cerr.copy()
        cerr["_fc"] = pd.to_datetime(cerr["fecha_cierre"].fillna(cerr["fecha_entrada"]))
        cerr = cerr.sort_values(["_fc", "id"], ascending=False)
        signos = [1 if p > 0 else -1 if p < 0 else 0 for p in cerr["pnl"]]
        if signos and signos[0] != 0:
            for sg in signos:
                if sg == signos[0]:
                    racha_n += 1
                else:
                    break
            racha_tipo = "ganancias" if signos[0] > 0 else "perdidas"
        pnl_hoy = float(cerr[cerr["_fc"].dt.date == hoy]["pnl"].sum())

    alertas = []
    mx = int(cfg["max_ops_dia"])
    if ops_hoy >= mx:
        alertas.append(("error", f"Ya hiciste {ops_hoy} operaciones hoy (tu límite es {mx}). Cerrá la plataforma: más operaciones = overtrading."))
    elif ops_hoy == mx - 1:
        alertas.append(("warning", f"Llevás {ops_hoy} de {mx} operaciones permitidas hoy: te queda una. Que valga la pena."))

    if racha_tipo == "perdidas":
        lim = int(cfg["max_perdidas_seguidas"])
        if racha_n >= lim:
            alertas.append(("error", f"{racha_n} pérdidas seguidas (límite {lim}). Pausa obligatoria: caminá 30 min y revisá tu diario antes de volver."))
        elif racha_n == lim - 1:
            alertas.append(("warning", f"{racha_n} pérdidas seguidas: estás a una del límite. El impulso de 'recuperar' es el que arma la espiral."))
    elif racha_tipo == "ganancias":
        lim = int(cfg["max_ganancias_seguidas"])
        if racha_n >= lim:
            alertas.append(("warning", f"{racha_n} ganancias seguidas (aviso a {lim}). Es el momento de más exceso de confianza: no subas el tamaño ni operes de más."))

    pd_max = float(cfg["perdida_diaria_max"] or 0)
    if pd_max > 0 and pnl_hoy <= -pd_max:
        alertas.append(("error", f"Perdiste ${-pnl_hoy:,.2f} hoy y tu límite diario es ${pd_max:,.2f}. Día terminado."))

    if estado_emocional and estado_emocional in ESTADOS_PREOP:
        _, nivel_e, msg_e = ESTADOS_PREOP[estado_emocional]
        if nivel_e != "success":
            alertas.append((nivel_e, f"Estado emocional ({estado_emocional}): {msg_e}"))

    niveles = [a[0] for a in alertas]
    nivel = "error" if "error" in niveles else "warning" if "warning" in niveles else "success"
    return {"ops_hoy": ops_hoy, "racha_tipo": racha_tipo, "racha_n": racha_n,
            "pnl_hoy": pnl_hoy, "alertas": alertas, "nivel": nivel}


def decision_preop(nivel: str, checks_ok: bool) -> str:
    if nivel == "error":
        return "Esperar"
    if not checks_ok:
        return "Completar checklist"
    if nivel == "warning":
        return "Operar con tamaño reducido"
    return "Operar"


def insertar_preop(client, user_id: str, d: dict) -> dict:
    payload = {
        "user_id": user_id, "fecha": date.today().isoformat(),
        "estado": d["estado"], "intensidad": int(d.get("intensidad") or 3),
        "simbolo": (d.get("simbolo") or "").upper().strip() or None,
        "decision": d["decision"], "checks_ok": bool(d.get("checks_ok")),
        "semaforo": d.get("semaforo", ""), "nota": d.get("nota", ""),
    }
    return fd._insertar_fila(client, "psico_preop", payload, "✅ Check-in guardado")


def listar_preop(client, user_id: str) -> pd.DataFrame:
    df = fd._df(client, "psico_preop", user_id)
    return df.sort_values("id", ascending=False) if not df.empty else df
