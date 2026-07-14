"""
modulo_pago_manual.py
Pago manual de Capital+ — el usuario transfiere por alias/CBU de MP y vos
aprobás el acceso a mano en Supabase. Sin webhooks, sin API de pagos.

secrets.toml necesario:

[pago_manual]
alias = "tu.alias.mp"
cbu = "0000003100000000000000"
titular = "Tu Nombre"
monto = "1000"
"""

import streamlit as st
from datetime import datetime, timezone


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


def _dias_plan_restantes(plan_vence_en: str):
    if not plan_vence_en:
        return None
    venc = datetime.fromisoformat(plan_vence_en.replace("Z", "+00:00"))
    restante = venc - datetime.now(timezone.utc)
    return max(0, restante.days)


def _ya_tiene_solicitud_pendiente(supabase_client, user_id: str) -> bool:
    res = (
        supabase_client.table("solicitudes_pago")
        .select("id")
        .eq("user_id", user_id)
        .eq("estado", "pendiente")
        .limit(1)
        .execute()
    )
    return len(res.data) > 0


def pantalla_suscripcion(supabase_client, user_id: str, email: str):
    """
    Bloque de UI: chequea trial / plan pago vigente. Si no hay acceso,
    muestra los datos para transferir y el botón "Ya transferí".
    Devuelve True si el usuario tiene acceso.
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

    cfg = st.secrets["pago_manual"]

    if _ya_tiene_solicitud_pendiente(supabase_client, user_id):
        st.info("🕐 Tu pago está en revisión. Se activa en poco tiempo una vez confirmado.")
        if st.button("🔄 Verificar de nuevo"):
            st.rerun()
        return False

    st.markdown(f"""
    <div style="background:#0d1117;border:1px solid #21262d;border-top:2px solid #6CC24A;
         border-radius:12px;padding:20px 24px;margin-bottom:16px">
      <div style="font-size:14px;color:#8b949e;margin-bottom:10px">Transferí por Mercado Pago a:</div>
      <div style="font-size:13px;color:#e6edf3;line-height:2">
        <b>Alias:</b> {cfg['alias']}<br>
        <b>CBU/CVU:</b> {cfg['cbu']}<br>
        <b>Titular:</b> {cfg['titular']}<br>
        <b>Monto:</b> ${cfg['monto']}
      </div>
    </div>
    """, unsafe_allow_html=True)

    nota = st.text_input(
        "Número de operación o comentario (opcional)",
        key="pago_manual_nota",
        placeholder="Ej: comprobante #123456",
    )

    if st.button("✅ Ya transferí, notificar", type="primary", use_container_width=True):
        supabase_client.table("solicitudes_pago").insert({
            "user_id": user_id,
            "email": email,
            "monto": cfg["monto"],
            "nota": nota,
            "estado": "pendiente",
        }).execute()
        st.success("¡Recibido! Tu pago va a ser revisado y tu acceso se activa a la brevedad.")
        st.rerun()

    return False
