"""
modulo_pago_manual.py
Pago manual de Capital+ — el usuario elige NIVEL (Básico o Pro) y DURACIÓN
(Mensual, Trimestral o Anual), transfiere en cripto, y vos aprobás el acceso
a mano desde el panel admin.

IMPORTANTE: todas las funciones de este módulo reciben `data_client`,
que es el cliente de Supabase creado con la service_role key (ver
clientes_supabase.py). Ese cliente bypassea RLS por completo, así que
no hace falta ninguna política de RLS en 'perfiles' ni 'solicitudes_pago'
para que esto funcione. La seguridad la maneja el propio código Python
(chequeando es_admin antes de dejar hacer nada administrativo).

secrets.toml necesario:

[supabase]
url = "..."
anon_key = "..."
service_role_key = "..."

[pago_manual.cripto]
red = "USDT (TRC-20)"
wallet = "T-tu-direccion-de-wallet-aca"
"""

import streamlit as st
from datetime import datetime, timezone, timedelta

# ── Niveles y duraciones disponibles — ajustá nombres, días y precios a gusto ──
PLANES_NIVELES = {
    "Básico": {
        "descripcion": "Acceso a los módulos esenciales de Capital+.",
        "duraciones": {
            "Mensual":    {"dias": 30,  "precio_usd": 10},
            "Trimestral": {"dias": 90,  "precio_usd": 27},
            "Anual":      {"dias": 365, "precio_usd": 90},
        },
    },
    "Pro": {
        "descripcion": "Acceso completo: Optimizador de cartera, Opciones, Señales y más.",
        "duraciones": {
            "Mensual":    {"dias": 30,  "precio_usd": 18},
            "Trimestral": {"dias": 90,  "precio_usd": 48},
            "Anual":      {"dias": 365, "precio_usd": 160},
        },
    },
}


def obtener_estado_perfil(data_client, user_id: str):
    """
    Devuelve el perfil del usuario, o None si todavía no tiene fila en
    'perfiles' (raro, porque el trigger de auth.users lo crea solo,
    pero por las dudas). Usa maybe_single() para no explotar si hay 0 filas.
    """
    res = (
        data_client.table("perfiles")
        .select("plan, plan_vence_en, es_admin, habilitado")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    return res.data


def _dias_plan_restantes(plan_vence_en: str):
    if not plan_vence_en:
        return None
    venc = datetime.fromisoformat(plan_vence_en.replace("Z", "+00:00"))
    restante = venc - datetime.now(timezone.utc)
    return max(0, restante.days)


def _ya_tiene_solicitud_pendiente(data_client, user_id: str) -> bool:
    res = (
        data_client.table("solicitudes_pago")
        .select("id")
        .eq("user_id", user_id)
        .eq("estado", "pendiente")
        .limit(1)
        .execute()
    )
    return len(res.data) > 0


def pantalla_suscripcion(data_client, user_id: str, email: str):
    """
    Bloque de UI: chequea si la cuenta está habilitada. Si no, deja
    elegir nivel (Básico/Pro) y duración, y notificar cuando ya transfirió
    en cripto. Devuelve True si el usuario tiene acceso.
    """
    perfil = obtener_estado_perfil(data_client, user_id)

    if perfil is None:
        st.error("⛔ No se encontró tu perfil. Contactá al administrador.")
        return False

    # Los admins tienen acceso completo siempre
    if perfil.get("es_admin"):
        return True

    if perfil.get("habilitado"):
        dias_restantes = _dias_plan_restantes(perfil.get("plan_vence_en"))
        nombre_plan_actual = (perfil.get("plan") or "").capitalize() or "activo"
        if dias_restantes is None:
            st.success(f"✅ Tu acceso a Capital+ ({nombre_plan_actual}) está activo.")
            return True
        if dias_restantes > 0:
            st.success(f"✅ Tu acceso a Capital+ ({nombre_plan_actual}) está activo — vence en {dias_restantes} día(s).")
            return True
        # se venció el plan: lo tratamos como deshabilitado más abajo
        st.warning("Tu acceso pago venció.")

    st.markdown("### Suscribite a Capital+")
    st.caption("💰 Los pagos se realizan exclusivamente en criptomonedas.")

    if _ya_tiene_solicitud_pendiente(data_client, user_id):
        st.info("🕐 Tu pago está en revisión. Se activa en poco tiempo una vez confirmado.")
        if st.button("🔄 Verificar de nuevo"):
            st.rerun()
        return False

    # ── 1. Elegir nivel ──────────────────────────────────────────
    tabs_nivel = st.tabs([f"⭐ {n}" for n in PLANES_NIVELES.keys()])
    cfg_cripto = st.secrets["pago_manual"]["cripto"]
    red = cfg_cripto.get("red", "USDT (TRC-20)")
    wallet = cfg_cripto.get("wallet", "")

    for tab_nivel, (nombre_nivel, datos_nivel) in zip(tabs_nivel, PLANES_NIVELES.items()):
        with tab_nivel:
            st.markdown(f"<div style='color:#8b949e;font-size:13px;margin-bottom:12px'>{datos_nivel['descripcion']}</div>", unsafe_allow_html=True)

            # ── 2. Elegir duración ────────────────────────────────
            nombre_duracion = st.radio(
                "Elegí la duración",
                list(datos_nivel["duraciones"].keys()),
                horizontal=True,
                key=f"pago_manual_duracion_{nombre_nivel}",
            )
            datos_duracion = datos_nivel["duraciones"][nombre_duracion]
            st.markdown(f"**{nombre_nivel} · {nombre_duracion}** — {datos_duracion['dias']} días de acceso")

            st.markdown(f"""
            <div style="background:#0d1117;border:1px solid #21262d;border-top:2px solid #e3b341;
                 border-radius:12px;padding:20px 24px;margin:12px 0">
              <div style="font-size:14px;color:#8b949e;margin-bottom:10px">Transferí en cripto a:</div>
              <div style="font-size:13px;color:#e6edf3;line-height:2">
                <b>Red:</b> {red}<br>
                <b>Wallet:</b> <code style="font-size:11px">{wallet}</code><br>
                <b>Monto:</b> USD ${datos_duracion['precio_usd']}
              </div>
            </div>
            """, unsafe_allow_html=True)

            nota_cripto = st.text_input(
                "Hash de la transacción o comentario (opcional)",
                key=f"pago_manual_nota_{nombre_nivel}",
                placeholder="Ej: hash 0xabc123...",
            )
            if st.button(f"✅ Ya transferí — {nombre_nivel} {nombre_duracion}", type="primary",
                         use_container_width=True, key=f"btn_notif_{nombre_nivel}"):
                data_client.table("solicitudes_pago").insert({
                    "user_id": user_id,
                    "email": email,
                    "monto": datos_duracion["precio_usd"],
                    "moneda": "USD",
                    "nota": nota_cripto,
                    "estado": "pendiente",
                    "nivel": nombre_nivel,
                    "plan_nombre": f"{nombre_nivel} - {nombre_duracion}",
                    "dias": datos_duracion["dias"],
                    "metodo": "cripto",
                }).execute()
                st.success("¡Recibido! Tu pago va a ser revisado y tu acceso se activa a la brevedad.")
                st.rerun()

    return False


def es_admin_usuario(data_client, user_id: str) -> bool:
    """Chequea el rol admin, para poder mostrar u ocultar el ítem
    de menú del panel de pagos desde app.py."""
    res = (
        data_client.table("perfiles")
        .select("es_admin")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    if not res.data:
        return False
    return bool(res.data.get("es_admin"))


def _listar_cuentas(data_client):
    res = (
        data_client.table("perfiles")
        .select("id, email, plan, es_admin, habilitado")
        .order("email")
        .execute()
    )
    return res.data


def _toggle_habilitado(data_client, cuenta_id: str, nuevo_estado: bool):
    data_client.table("perfiles").update(
        {"habilitado": nuevo_estado}
    ).eq("id", cuenta_id).execute()


def panel_gestion_cuentas(data_client, user_id: str):
    """Panel visible SOLO para admins. Lista todas las cuentas y permite
    habilitar/deshabilitar el acceso de cualquiera con un click."""
    if not es_admin_usuario(data_client, user_id):
        return

    with st.expander("👥 Gestión de cuentas", expanded=False):
        cuentas = _listar_cuentas(data_client)

        if not cuentas:
            st.caption("No hay cuentas cargadas.")
            return

        filtro = st.text_input("Buscar por email", key="filtro_cuentas", placeholder="Ej: juan@")
        if filtro:
            cuentas = [c for c in cuentas if filtro.lower() in (c.get("email") or "").lower()]

        for cuenta in cuentas:
            with st.container(border=True):
                c1, c2, c3 = st.columns([3, 1, 1])
                with c1:
                    estado = "🟢 Habilitada" if cuenta.get("habilitado") else "🔴 Deshabilitada"
                    admin_tag = " · 🛠️ admin" if cuenta.get("es_admin") else ""
                    st.markdown(f"**{cuenta['email']}** — nivel: {cuenta.get('plan', '-')} — {estado}{admin_tag}")
                with c2:
                    if cuenta.get("habilitado"):
                        if st.button("🚫 Deshabilitar", key=f"deshab_{cuenta['id']}", use_container_width=True):
                            _toggle_habilitado(data_client, cuenta["id"], False)
                            st.rerun()
                    else:
                        if st.button("✅ Habilitar", key=f"habil_{cuenta['id']}", use_container_width=True):
                            _toggle_habilitado(data_client, cuenta["id"], True)
                            st.rerun()


def panel_admin_pagos(data_client, user_id: str):
    """Panel visible SOLO para cuentas es_admin = true. Muestra las
    solicitudes de pago pendientes (siempre en cripto) con botones
    para aprobar o rechazar."""
    if not es_admin_usuario(data_client, user_id):
        return

    with st.expander("🛠️ Panel de aprobación de pagos", expanded=False):
        res = (
            data_client.table("solicitudes_pago")
            .select("id, user_id, email, monto, moneda, nota, creado_en, nivel, plan_nombre, dias")
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
                st.markdown(
                    f"**{sol['email']}** — {sol.get('plan_nombre', 'Básico - Mensual')} "
                    f"({sol.get('dias', 30)} días) — {sol.get('moneda','USD')} ${sol['monto']} ₿"
                )
                if sol.get("nota"):
                    st.caption(f"Nota: {sol['nota']}")
                st.caption(sol["creado_en"])
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ Aprobar", key=f"aprobar_{sol['id']}", use_container_width=True):
                        dias = sol.get("dias", 30)
                        nivel = (sol.get("nivel") or "basico").lower()
                        vence = datetime.now(timezone.utc) + timedelta(days=dias)
                        data_client.table("perfiles").update({
                            "plan": nivel,
                            "plan_vence_en": vence.isoformat(),
                            "habilitado": True,
                        }).eq("id", sol["user_id"]).execute()
                        data_client.table("solicitudes_pago").update({
                            "estado": "aprobado",
                            "revisado_en": datetime.now(timezone.utc).isoformat(),
                        }).eq("id", sol["id"]).execute()
                        st.success(f"Activado: {sol['email']} ({sol.get('plan_nombre')} · {dias} días)")
                        st.rerun()
                with c2:
                    if st.button("❌ Rechazar", key=f"rechazar_{sol['id']}", use_container_width=True):
                        data_client.table("solicitudes_pago").update({
                            "estado": "rechazado",
                            "revisado_en": datetime.now(timezone.utc).isoformat(),
                        }).eq("id", sol["id"]).execute()
                        st.rerun()
