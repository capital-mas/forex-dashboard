"""
modulo_pagos_mp.py
Suscripciones mensuales de Capital+ vía Mercado Pago.

secrets.toml necesario:

[mercadopago]
access_token = "APP_USR-..."       # o TEST-... mientras probás
preapproval_plan_id = ""           # se completa después de correr crear_plan_suscripcion() UNA vez
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


def crear_suscripcion(user_id: str, email: str, monto: float = 1000, moneda: str = "ARS", dias_trial: int = 3):
    """
    Crea la suscripción para un usuario puntual, en modo "sin plan asociado,
    pago pendiente" — este modo SÍ devuelve un init_point para mandar al
    usuario al checkout y que complete el pago ahí (a diferencia del modo
    "con plan asociado", que exige tener ya el card_token_id).
    Devuelve (init_point, preapproval_id).
    """
    payload = {
        "reason": "Suscripción Capital+",
        "external_reference": user_id,
        "payer_email": email,
        "back_url": st.secrets["mercadopago"]["back_url"],
        "notification_url": st.secrets["mercadopago"]["webhook_url"],
        "status": "pending",
        "auto_recurring": {
            "frequency": 1,
            "frequency_type": "months",
            "transaction_amount": monto,
            "currency_id": moneda,
            "free_trial": {"frequency": dias_trial, "frequency_type": "days"},
        },
    }
    r = requests.post(f"{MP_API}/preapproval", json=payload, headers=_headers())
    if not r.ok:
        st.error(f"Mercado Pago rechazó la suscripción: {r.status_code} — {r.text}")
        r.raise_for_status()
    data = r.json()
    return data["init_point"], data["id"]


def obtener_estado_perfil(supabase_client, user_id: str):
    res = (
        supabase_client.table("perfiles")
        .select("plan, trial_termina_en")
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


def pantalla_suscripcion(supabase_client, user_id: str, email: str):
    """
    Bloque de UI: muestra el estado del trial, y si venció, el botón
    para suscribirse con Mercado Pago. Llamalo donde quieras mostrar
    esto (ej. arriba de todo, o como pantalla bloqueante si plan != pro).
    """
    perfil = obtener_estado_perfil(supabase_client, user_id)
    plan = perfil["plan"]

    if plan == "pro":
        st.success("✅ Tu suscripción a Capital+ está activa.")
        return True

    if plan == "trial":
        restantes = _dias_trial_restantes(perfil["trial_termina_en"])
        if restantes > 0:
            st.info(f"🎁 Estás en período de prueba — te quedan {restantes} día(s).")
            st.progress(min(1.0, restantes / 3))
            return True
        st.warning("Tu período de prueba terminó.")

    st.markdown("### Suscribite a Capital+")

    if st.button("💳 Suscribirme ahora", type="primary"):
        with st.spinner("Generando link de pago..."):
            init_point, preapproval_id = crear_suscripcion(user_id, email)
            st.session_state["mp_preapproval_id"] = preapproval_id
            st.session_state["mp_init_point"] = init_point

    if "mp_init_point" in st.session_state:
        st.link_button("Ir a pagar en Mercado Pago", st.session_state["mp_init_point"], use_container_width=True)
        st.caption("Después de autorizar el pago, volvé acá y tocá el botón de abajo.")
        if st.button("🔄 Ya pagué, verificar"):
            perfil_actualizado = obtener_estado_perfil(supabase_client, user_id)
            if perfil_actualizado["plan"] == "pro":
                st.success("¡Listo! Tu plan ya está activo.")
                st.rerun()
            else:
                st.info("Todavía no se acreditó. Puede tardar unos segundos, probá de nuevo en un momento.")

    return False
