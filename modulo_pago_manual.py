"""
modulo_pago_manual.py
Pago manual de Capital+ — el usuario elige plan y método (Mercado Pago o
cripto), transfiere, y vos aprobás el acceso a mano (o desde el panel admin).

secrets.toml necesario:

[pago_manual]
alias = "tu.alias.mp"
cbu = "0000003100000000000000"
titular = "Tu Nombre"

[pago_manual.cripto]
red = "USDT (TRC-20)"
wallet = "T-tu-direccion-de-wallet-aca"
"""

import streamlit as st
from datetime import datetime, timezone, timedelta

# ── Planes disponibles: ajustá nombres, días y precios a gusto ──
PLANES = {
    "Mensual":    {"dias": 30,  "precio_ars": 15000, "precio_usd": 10},
    "Trimestral": {"dias": 90,  "precio_ars": 40000, "precio_usd": 27},
    "Semestral":  {"dias": 180, "precio_ars": 75000, "precio_usd": 50},
    "Anual":      {"dias": 365, "precio_ars": 135000, "precio_usd": 90},
}


def obtener_estado_perfil(supabase_client, user_id: str):
    """
    Devuelve el perfil del usuario, o None si todavía no tiene fila en
    'perfiles' (cuenta nueva sin inicializar, o cuenta deshabilitada a
    la que le borraste la fila). Usa maybe_single() en vez de single()
    para NO explotar con APIError cuando hay 0 filas.
    """
    res = (
        supabase_client.table("perfiles")
        .select("plan, trial_termina_en, plan_vence_en, es_admin")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    return res.data  # puede ser None


def _crear_perfil_default(supabase_client, user_id: str, email: str):
    """
    Crea una fila default (en trial) para un usuario que todavía no
    tiene perfil. Ajustá los días de trial a gusto.
    """
    trial_termina = datetime.now(timezone.utc) + timedelta(days=3)
    nuevo = {
        "id": user_id,
        "email": email,
        "plan": "trial",
        "trial_termina_en": trial_termina.isoformat(),
        "es_admin": False,
    }
    supabase_client.table("perfiles").upsert(nuevo).execute()
    return nuevo


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
    deja elegir plan y método de pago, y notificar cuando ya transfirió.
    Devuelve True si el usuario tiene acceso.
    """
    perfil = obtener_estado_perfil(supabase_client, user_id)

    # Cuenta sin fila en 'perfiles' todavía (nueva, o le borraste la fila
    # para "deshabilitarla"). Antes esto rompía la app con APIError.
    if perfil is None:
        st.warning("⛔ Tu cuenta no tiene un perfil activo. Contactá al administrador para habilitar el acceso.")
        # Si preferís que se autogenere un perfil en trial en vez de bloquear,
        # descomentá estas dos líneas y borrá el st.warning + return False de arriba:
        # perfil = _crear_perfil_default(supabase_client, user_id, email)
        return False

    plan = perfil["plan"]

    # Los admins tienen acceso completo sin pasar por el chequeo de pago
    if perfil.get("es_admin"):
        return True

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

    if _ya_tiene_solicitud_pendiente(supabase_client, user_id):
        st.info("🕐 Tu pago está en revisión. Se activa en poco tiempo una vez confirmado.")
        if st.button("🔄 Verificar de nuevo"):
            st.rerun()
        return False

    # ── 1. Elegir plan ──────────────────────────────────────────
    nombre_plan = st.radio(
        "Elegí tu plan",
        list(PLANES.keys()),
        horizontal=True,
        key="pago_manual_plan_sel",
    )
    datos_plan = PLANES[nombre_plan]
    st.markdown(f"**{nombre_plan}** — {datos_plan['dias']} días de acceso")

    # ── 2. Elegir método de pago ─────────────────────────────────
    tab_mp, tab_cripto = st.tabs(["💳 Mercado Pago", "₿ Cripto"])
    cfg = st.secrets["pago_manual"]

    with tab_mp:
        st.markdown(f"""
        <div style="background:#0d1117;border:1px solid #21262d;border-top:2px solid #6CC24A;
             border-radius:12px;padding:20px 24px;margin:12px 0">
          <div style="font-size:14px;color:#8b949e;margin-bottom:10px">Transferí por Mercado Pago a:</div>
          <div style="font-size:13px;color:#e6edf3;line-height:2">
            <b>Alias:</b> {cfg['alias']}<br>
            <b>CBU/CVU:</b> {cfg['cbu']}<br>
            <b>Titular:</b> {cfg['titular']}<br>
            <b>Monto:</b> ${datos_plan['precio_ars']:,} ARS
          </div>
        </div>
        """, unsafe_allow_html=True)
        nota_mp = st.text_input(
            "Número de operación o comentario (opcional)",
            key="pago_manual_nota_mp",
            placeholder="Ej: comprobante #123456",
        )
        if st.button("✅ Ya transferí por Mercado Pago", type="primary", use_container_width=True, key="btn_notif_mp"):
            supabase_client.table("solicitudes_pago").insert({
                "user_id": user_id,
                "email": email,
                "monto": datos_plan["precio_ars"],
                "moneda": "ARS",
                "nota": nota_mp,
                "estado": "pendiente",
                "plan_nombre": nombre_plan,
                "dias": datos_plan["dias"],
                "metodo": "mercadopago",
            }).execute()
            st.success("¡Recibido! Tu pago va a ser revisado y tu acceso se activa a la brevedad.")
            st.rerun()

    with tab_cripto:
        cripto_cfg = cfg.get("cripto", {})
        red = cripto_cfg.get("red", "USDT (TRC-20)")
        wallet = cripto_cfg.get("wallet", "")
        st.markdown(f"""
        <div style="background:#0d1117;border:1px solid #21262d;border-top:2px solid #e3b341;
             border-radius:12px;padding:20px 24px;margin:12px 0">
          <div style="font-size:14px;color:#8b949e;margin-bottom:10px">Transferí en cripto a:</div>
          <div style="font-size:13px;color:#e6edf3;line-height:2">
            <b>Red:</b> {red}<br>
            <b>Wallet:</b> <code style="font-size:11px">{wallet}</code><br>
            <b>Monto:</b> USD ${datos_plan['precio_usd']}
          </div>
        </div>
        """, unsafe_allow_html=True)
        nota_cripto = st.text_input(
            "Hash de la transacción o comentario (opcional)",
            key="pago_manual_nota_cripto",
            placeholder="Ej: hash 0xabc123...",
        )
        if st.button("✅ Ya transferí en cripto", type="primary", use_container_width=True, key="btn_notif_cripto"):
            supabase_client.table("solicitudes_pago").insert({
                "user_id": user_id,
                "email": email,
                "monto": datos_plan["precio_usd"],
                "moneda": "USD",
                "nota": nota_cripto,
                "estado": "pendiente",
                "plan_nombre": nombre_plan,
                "dias": datos_plan["dias"],
                "metodo": "cripto",
            }).execute()
            st.success("¡Recibido! Tu pago va a ser revisado y tu acceso se activa a la brevedad.")
            st.rerun()

    return False


def es_admin_usuario(supabase_client, user_id: str) -> bool:
    """Versión pública de _es_admin, para poder chequear el rol desde app.py
    antes de decidir si mostrar el ítem de menú del panel de pagos."""
    return _es_admin(supabase_client, user_id)


def _es_admin(supabase_client, user_id: str) -> bool:
    res = (
        supabase_client.table("perfiles")
        .select("es_admin")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    if not res.data:
        return False
    return bool(res.data.get("es_admin"))


def panel_admin_pagos(supabase_client, user_id: str):
    """
    Panel visible SOLO para cuentas marcadas como es_admin = true.
    Muestra las solicitudes de pago pendientes (con plan, días y método)
    con botones para aprobar o rechazar, sin tocar SQL.
    """
    if not _es_admin(supabase_client, user_id):
        return

    with st.expander("🛠️ Panel de aprobación de pagos", expanded=False):
        res = (
            supabase_client.table("solicitudes_pago")
            .select("id, user_id, email, monto, moneda, nota, creado_en, plan_nombre, dias, metodo")
            .eq("estado", "pendiente")
            .order("creado_en", desc=True)
            .execute()
        )
        pendientes = res.data

        if not pendientes:
            st.caption("No hay solicitudes pendientes.")
            return

        for sol in pendientes:
            with st.container(border=True):
                metodo_icono = "₿" if sol.get("metodo") == "cripto" else "💳"
                moneda = sol.get("moneda", "ARS")
                st.markdown(
                    f"**{sol['email']}** — {sol.get('plan_nombre', 'Mensual')} "
                    f"({sol.get('dias', 30)} días) — {moneda} ${sol['monto']} {metodo_icono}"
                )
                if sol.get("nota"):
                    st.caption(f"Nota: {sol['nota']}")
                st.caption(sol["creado_en"])
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ Aprobar", key=f"aprobar_{sol['id']}", use_container_width=True):
                        dias = sol.get("dias", 30)
                        vence = datetime.now(timezone.utc) + timedelta(days=dias)
                        supabase_client.table("perfiles").update({
                            "plan": "pro",
                            "plan_vence_en": vence.isoformat(),
                        }).eq("id", sol["user_id"]).execute()
                        supabase_client.table("solicitudes_pago").update({
                            "estado": "aprobado",
                            "revisado_en": datetime.now(timezone.utc).isoformat(),
                        }).eq("id", sol["id"]).execute()
                        st.success(f"Activado: {sol['email']} ({dias} días)")
                        st.rerun()
                with c2:
                    if st.button("❌ Rechazar", key=f"rechazar_{sol['id']}", use_container_width=True):
                        supabase_client.table("solicitudes_pago").update({
                            "estado": "rechazado",
                            "revisado_en": datetime.now(timezone.utc).isoformat(),
                        }).eq("id", sol["id"]).execute()
                        st.rerun()
