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
