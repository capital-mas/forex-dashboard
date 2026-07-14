"""
modulo_pagos_mp.py
Pagos de Capital+ vía Mercado Pago — Checkout Pro (pago único, renovación manual).

En vez de una suscripción que MP cobra sola cada mes, el usuario paga 30 días
de acceso por vez. Cuando se vence (plan_vence_en), la app le vuelve a pedir
el pago. Esto evita las restricciones de tarjetas que tiene el modo
"suscripción recurrente" y usa el checkout más simple y estable de MP.

secrets.toml necesario:

[mercadopago]
access_token = "APP_USR-..."
webhook_url = "https://<tu-proyecto>.functions.supabase.co/mp-webhook"
back_url = "https://tu-app.streamlit.app"
"""

import streamlit as st
import requests
from datetime import datetime, timezone

MP_API = "https://api.mercadopago.com"


def _headers():
    token = st.secrets["mercadopago"]["access_token"]
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def crear_pago(user_id: str, email: str, monto: float = 15, moneda: str = "ARS"):
    """
    Crea una preferencia de pago único (Checkout Pro) por 30 días de acceso.
    Devuelve (init_point, preference_id).
    """
    back = st.secrets["mercadopago"]["back_url"]
    payload = {
        "items": [{
            "title": "Suscripción Capital+ (30 días)",
            "quantity": 1,
            "unit_price": float(monto),
            "currency_id": moneda,
        }],
        "external_reference": user_id,  # clave para que el webhook sepa quién pagó
        "payer": {"email": email},
        "back_urls": {"success": back, "failure": back, "pending": back},
        "auto_return": "approved",
        "notification_url": st.secrets["mercadopago"]["webhook_url"],
    }
    r = requests.post(f"{MP_API}/checkout/preferences", json=payload, headers=_headers())
    if not r.ok:
        st.error(f"Mercado Pago rechazó el pago: {r.status_code} — {r.text}")
        r.raise_for_status()
    data = r.json()
    return data["init_point"], data["id"]


def obtener_estado_perfil(supabase_client, user_id: str):
    res = (
        supabase_client.table("perfiles")
        .select("plan, trial_termina_en, plan_vence_en")
        .eq("id", user_id)
        .single()
        .execute()
    )
    return res.data


def _dias_trial_restantes(trial_termina_en: str) -> int:
    if not trial_termina_en:
        return 0
    venc = datetime.fromisoformat(trial_termina_en.replace("Z", "+00:00"))
    restante = venc - datetime.now(timezone.utc)
    return max(0, restante.days)


def _dias_plan_restantes(plan_vence_en: str) -> int:
    if not plan_vence_en:
        return None  # sin fecha de vencimiento = acceso indefinido (ej. cuentas activadas a mano)
    venc = datetime.fromisoformat(plan_vence_en.replace("Z", "+00:00"))
    restante = venc - datetime.now(timezone.utc)
    return max(0, restante.days)


def pantalla_suscripcion(supabase_client, user_id: str, email: str):
    """
    Bloque de UI: chequea trial / plan pago vigente, y si no hay acceso,
    muestra el botón de pago. Devuelve True si el usuario tiene acceso.
    """
    perfil = obtener_estado_perfil(supabase_client, user_id)
    plan = perfil["plan"]

    if plan == "pro":
        dias_restantes = _dias_plan_restantes(perfil.get("plan_vence_en"))
        if dias_restantes is None:
            st.success("✅ Tu acceso a Capital+ está activo.")
            return True
        if dias_restantes > 0:
            st.success(f"✅ Tu acceso a Capital+ está activo — vence en {dias_restantes} día(s).")
            return True
        st.warning("Tu acceso pago venció.")

    elif plan == "trial":
        restantes = _dias_trial_restantes(perfil["trial_termina_en"])
        if restantes > 0:
            st.info(f"🎁 Estás en período de prueba — te quedan {restantes} día(s).")
            st.progress(min(1.0, restantes / 3))
            return True
        st.warning("Tu período de prueba terminó.")

    st.markdown("### Suscribite a Capital+")

    if st.button("💳 Pagar 30 días de acceso", type="primary"):
        with st.spinner("Generando link de pago..."):
            init_point, preference_id = crear_pago(user_id, email)
            st.session_state["mp_preference_id"] = preference_id
            st.session_state["mp_init_point"] = init_point

    if "mp_init_point" in st.session_state:
        st.link_button("Ir a pagar en Mercado Pago", st.session_state["mp_init_point"], use_container_width=True)
        st.caption("Después de pagar, volvé acá y tocá el botón de abajo.")

    if st.button("🔄 Ya pagué, verificar"):
        perfil_actualizado = obtener_estado_perfil(supabase_client, user_id)
        dias = _dias_plan_restantes(perfil_actualizado.get("plan_vence_en"))
        if perfil_actualizado["plan"] == "pro" and (dias is None or dias > 0):
            st.success("¡Listo! Tu acceso ya está activo.")
            st.rerun()
        else:
            st.info("Todavía no se acreditó. Puede tardar unos segundos, probá de nuevo en un momento.")

    return False
