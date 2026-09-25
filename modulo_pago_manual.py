"""
modulo_pago_manual.py — v2: multi-producto
Cada vertical (mercados, pyme, agro) tiene su propio ciclo de vida:
trial de 7 días -> vence -> elegir nivel + duración -> pagar en cripto
-> aprobación admin -> perfiles.modulos_plan[<modulo>] actualizado.

Un usuario puede tener 0, 1, 2 o 3 módulos activos a la vez, cada uno
con su propio nivel y vencimiento.

SUPABASE — agregar una vez:
  alter table perfiles add column if not exists modulos_plan jsonb not null default '{}'::jsonb;
  alter table solicitudes_pago add column if not exists modulo text not null default 'mercados';

secrets.toml (sin cambios):
[pago_manual.cripto]
red = "USDT (TRC-20)"
wallet = "T-tu-direccion-de-wallet-aca"
"""

import streamlit as st
from datetime import datetime, timezone, timedelta

TRIAL_DIAS = 7

# ── Catálogo de productos ──────────────────────────────────────────
PRODUCTOS = {
    "mercados": dict(nombre="Mercados & Finanzas", icono="📡", niveles={
        "Básico": dict(
            descripcion="Acceso a los módulos esenciales de mercados.",
            duraciones={
                "Mensual": dict(
                    dias=30, precio_usd=9, precio_ars=14000,
                    link_mp="https://mpago.la/2PJHTtJ",
                ),
                "Trimestral": dict(
                    dias=90, precio_usd=24, precio_ars=37000,
                    link_mp="https://mpago.la/1vKQM87",
                ),
                "Anual": dict(
                    dias=365, precio_usd=80, precio_ars=125000,
                    link_mp="https://mpago.la/2HNUb4x",
                ),
            },
        ),
        "Pro": dict(
            descripcion="Acceso completo: Optimizador, Opciones, Señales, Asistente IA y más.",
            duraciones={
                "Mensual": dict(
                    dias=30, precio_usd=13, precio_ars=20000,
                    link_mp="https://mpago.la/2s6N6LS",
                ),
                "Trimestral": dict(
                    dias=90, precio_usd=48, precio_ars=56000,
                    link_mp="https://mpago.la/xxxxx-pro-trimestral",
                ),
                "Anual": dict(
                    dias=365, precio_usd=160, precio_ars=187000,
                    link_mp="https://mpago.la/xxxxx-pro-anual",
                ),
            },
        ),
    }),
    "pyme": dict(nombre="PyMEs", icono="🏢", niveles={
        "Básico": dict(
            descripcion="Cashflow y cuentas por cobrar/pagar.",
            duraciones={
                "Mensual":    dict(dias=30,  precio_usd=8),
                "Trimestral": dict(dias=90,  precio_usd=21),
                "Anual":      dict(dias=365, precio_usd=70),
            },
        ),
        "Pro": dict(
            descripcion="Todo lo de Básico + cartera de cheques y reportes avanzados.",
            duraciones={
                "Mensual":    dict(dias=30,  precio_usd=15),
                "Trimestral": dict(dias=90,  precio_usd=40),
                "Anual":      dict(dias=365, precio_usd=135),
            },
        ),
    }),
    "agro": dict(nombre="Agro", icono="🌾", niveles={
        "Único": dict(
            descripcion="Márgenes por hectárea, stock de granos y seguimiento de insumos.",
            duraciones={
                "Mensual":    dict(dias=30,  precio_usd=12),
                "Trimestral": dict(dias=90,  precio_usd=32),
                "Anual":      dict(dias=365, precio_usd=110),
            },
        ),
    }),
}

NOMBRE_NIVEL_DISPLAY = {"trial": "Prueba gratuita", "basico": "Básico", "pro": "Pro", "unico": "Único"}


# ── Helpers de perfil / vencimientos ───────────────────────────────

def _leer_perfil(data_client, user_id: str):
    res = (
        data_client.table("perfiles")
        .select("modulos_plan, plan, plan_vence_en, es_admin, habilitado")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    return res.data


def _modulos_plan_normalizado(perfil: dict) -> dict:
    """Copia modulos_plan y, si falta 'mercados' pero existen las columnas
    legacy (plan/plan_vence_en de la v1), las usa como compat."""
    mp = dict(perfil.get("modulos_plan") or {})
    if "mercados" not in mp and perfil.get("plan"):
        mp["mercados"] = {"nivel": perfil["plan"], "vence_en": perfil.get("plan_vence_en")}
    return mp


def _dias_restantes(vence_en: str):
    if not vence_en:
        return None
    venc = datetime.fromisoformat(vence_en.replace("Z", "+00:00"))
    return (venc - datetime.now(timezone.utc)).total_seconds() / 86400


def _iniciar_trial_modulo(data_client, user_id: str, mp: dict, modulo: str) -> dict:
    """Si la cuenta nunca activó este módulo, le da el trial gratuito.
    Solo pasa una vez por módulo: una vez que queda una entrada en
    modulos_plan[modulo], no se vuelve a tocar acá."""
    if modulo in mp:
        return mp
    vence = datetime.now(timezone.utc) + timedelta(days=TRIAL_DIAS)
    mp = dict(mp)
    mp[modulo] = {"nivel": "trial", "vence_en": vence.isoformat()}
    data_client.table("perfiles").update({"modulos_plan": mp}).eq("id", user_id).execute()
    return mp


def estado_modulo(data_client, user_id: str, modulo: str) -> dict:
    """Chequeo liviano de estado (para nav, badges, gating de sub-features).
    NO inicia trial ni renderiza nada — solo informa."""
    perfil = _leer_perfil(data_client, user_id)
    if perfil is None:
        return dict(activo=False, nivel=None, dias_restantes=None, es_trial=False)
    if perfil.get("es_admin"):
        return dict(activo=True, nivel="admin", dias_restantes=None, es_trial=False)
    if not perfil.get("habilitado", True):
        return dict(activo=False, nivel=None, dias_restantes=None, es_trial=False, deshabilitado=True)
    mp = _modulos_plan_normalizado(perfil)
    info = mp.get(modulo)
    if info is None:
        return dict(activo=False, nivel=None, dias_restantes=None, es_trial=False, nunca_iniciado=True)
    dias = _dias_restantes(info.get("vence_en"))
    return dict(
        activo=dias is not None and dias > 0,
        nivel=info.get("nivel"), dias_restantes=dias,
        es_trial=info.get("nivel") == "trial",
    )


def es_admin_usuario(data_client, user_id: str) -> bool:
    res = data_client.table("perfiles").select("es_admin").eq("id", user_id).maybe_single().execute()
    return bool(res.data and res.data.get("es_admin"))


# ── Pantalla de gate por módulo ────────────────────────────────────

def pantalla_suscripcion_modulo(data_client, user_id: str, email: str, modulo: str) -> bool:
    """Bloque de UI para UN módulo puntual. Arranca el trial la primera vez
    que el usuario entra a ese workspace. Devuelve True si tiene acceso
    (admin, trial vigente o plan pago vigente); False si mostró el paywall."""
    perfil = _leer_perfil(data_client, user_id)
    if perfil is None:
        st.error("⛔ No se encontró tu perfil. Contactá al administrador.")
        return False
    if perfil.get("es_admin"):
        return True
    if not perfil.get("habilitado", True):
        st.error("⛔ Tu cuenta está deshabilitada. Contactá al administrador.")
        return False

    mp = _modulos_plan_normalizado(perfil)
    mp = _iniciar_trial_modulo(data_client, user_id, mp, modulo)
    info = mp[modulo]
    dias = _dias_restantes(info.get("vence_en"))
    nombre_prod = PRODUCTOS[modulo]["nombre"]
    nivel = info.get("nivel")

    if dias is not None and dias > 0:
        dias_i = int(dias) if dias >= 1 else 0
        if nivel == "trial":
            st.success(f"🎁 Prueba gratuita de **{nombre_prod}** — te quedan {dias_i} día(s).")
        else:
            st.success(f"✅ Tu plan **{NOMBRE_NIVEL_DISPLAY.get(nivel, nivel)}** de {nombre_prod} está activo — vence en {dias_i} día(s).")
        return True

    mensaje = (
        f"🕐 Tu prueba gratuita de {nombre_prod} finalizó. Elegí un plan para continuar."
        if nivel == "trial" else
        f"⏰ Tu plan de {nombre_prod} venció. Elegí uno para renovar."
    )
    mostrar_selector_planes(data_client, user_id, email, modulo, mensaje_previo=mensaje)
    return False


def _ya_tiene_solicitud_pendiente(data_client, user_id: str, modulo: str) -> bool:
    res = (
        data_client.table("solicitudes_pago")
        .select("id").eq("user_id", user_id).eq("modulo", modulo).eq("estado", "pendiente")
        .limit(1).execute()
    )
    return len(res.data) > 0


def _bloque_nivel(data_client, user_id, email, modulo, nombre_nivel, datos_nivel, red, wallet):
    nombre_duracion = st.radio(
        "Elegí la duración", list(datos_nivel["duraciones"].keys()),
        horizontal=True, key=f"pago_{modulo}_duracion_{nombre_nivel}",
    )
    datos_duracion = datos_nivel["duraciones"][nombre_duracion]
    st.markdown(f"**{nombre_nivel} · {nombre_duracion}** — {datos_duracion['dias']} días de acceso")

    metodo = st.radio(
        "Método de pago",
        ["💳 Mercado Pago (ARS)", "🪙 Cripto (USDT)"],
        horizontal=True, key=f"pago_{modulo}_metodo_{nombre_nivel}_{nombre_duracion}",
    )

    if metodo.startswith("💳"):
        precio_ars = datos_duracion.get("precio_ars")
        link_mp = datos_duracion.get("link_mp")
        st.markdown(f"""
        <div style="background:#0d1117;border:1px solid #21262d;border-top:2px solid #3a7bd5;
             border-radius:12px;padding:20px 24px;margin:12px 0">
          <div style="font-size:14px;color:#8b949e;margin-bottom:10px">Pagá con tarjeta, débito o dinero en cuenta:</div>
          <div style="font-size:13px;color:#e6edf3;line-height:2">
            <b>Monto:</b> ARS ${precio_ars:,.0f}
          </div>
        </div>
        """, unsafe_allow_html=True)

        if link_mp:
            st.link_button("💳 Pagar con Mercado Pago", link_mp, use_container_width=True, type="primary")
        else:
            st.warning("Este plan todavía no tiene link de Mercado Pago configurado.")

        nota_mp = st.text_input(
            "Email o número de operación de Mercado Pago (opcional)",
            key=f"pago_{modulo}_nota_mp_{nombre_nivel}_{nombre_duracion}",
            placeholder="Ej: operación #123456789",
        )
        if st.button(f"✅ Ya pagué — {nombre_nivel} {nombre_duracion}", type="primary",
                     use_container_width=True, key=f"btn_notif_mp_{modulo}_{nombre_nivel}_{nombre_duracion}"):
            data_client.table("solicitudes_pago").insert({
                "user_id": user_id, "email": email, "modulo": modulo,
                "monto": precio_ars, "moneda": "ARS",
                "nota": nota_mp, "estado": "pendiente",
                "plan_nombre": f"{nombre_nivel} - {nombre_duracion}",
                "dias": datos_duracion["dias"], "metodo": "mercadopago",
            }).execute()
            st.success("¡Recibido! Tu pago va a ser revisado y tu acceso se activa a la brevedad.")
            st.rerun()

    else:
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
            key=f"pago_{modulo}_nota_{nombre_nivel}_{nombre_duracion}", placeholder="Ej: hash 0xabc123...",
        )
        if st.button(f"✅ Ya transferí — {nombre_nivel} {nombre_duracion}", type="primary",
                     use_container_width=True, key=f"btn_notif_{modulo}_{nombre_nivel}_{nombre_duracion}"):
            data_client.table("solicitudes_pago").insert({
                "user_id": user_id, "email": email, "modulo": modulo,
                "monto": datos_duracion["precio_usd"], "moneda": "USD",
                "nota": nota_cripto, "estado": "pendiente",
                "plan_nombre": f"{nombre_nivel} - {nombre_duracion}",
                "dias": datos_duracion["dias"], "metodo": "cripto",
            }).execute()
            st.success("¡Recibido! Tu pago va a ser revisado y tu acceso se activa a la brevedad.")
            st.rerun()

def mostrar_selector_planes(data_client, user_id: str, email: str, modulo: str, mensaje_previo: str = None):
    """Pantalla para elegir NIVEL y DURACIÓN de UN módulo puntual, pagar en
    cripto y notificar la transferencia. Se usa cuando vence su trial/plan,
    y también como botón de 'contratar' para un módulo que el usuario
    todavía no tiene (ej. clic en '🔒 PyMEs' desde el switcher)."""
    producto = PRODUCTOS[modulo]
    if mensaje_previo:
        st.warning(mensaje_previo)

    st.markdown(f"### {producto['icono']} Elegí tu plan — {producto['nombre']}")
    st.caption("💰 Los pagos se realizan exclusivamente en criptomonedas.")

    if _ya_tiene_solicitud_pendiente(data_client, user_id, modulo):
        st.info("🕐 Tu pago está en revisión. Se activa en poco tiempo una vez confirmado.")
        if st.button("🔄 Verificar de nuevo", key=f"verif_{modulo}"):
            st.rerun()
        return

    cfg_cripto = st.secrets["pago_manual"]["cripto"]
    red = cfg_cripto.get("red", "USDT (TRC-20)")
    wallet = cfg_cripto.get("wallet", "")
    niveles = producto["niveles"]

    if len(niveles) == 1:
        # Un solo plan (caso Agro): sin tabs, directo.
        nombre_nivel, datos_nivel = list(niveles.items())[0]
        st.markdown(f"<div style='color:#8b949e;font-size:13px;margin-bottom:12px'>{datos_nivel['descripcion']}</div>", unsafe_allow_html=True)
        _bloque_nivel(data_client, user_id, email, modulo, nombre_nivel, datos_nivel, red, wallet)
    else:
        tabs_nivel = st.tabs([f"⭐ {n}" for n in niveles])
        for tab_nivel, (nombre_nivel, datos_nivel) in zip(tabs_nivel, niveles.items()):
            with tab_nivel:
                st.markdown(f"<div style='color:#8b949e;font-size:13px;margin-bottom:12px'>{datos_nivel['descripcion']}</div>", unsafe_allow_html=True)
                _bloque_nivel(data_client, user_id, email, modulo, nombre_nivel, datos_nivel, red, wallet)


# ── Panel admin: cuentas ───────────────────────────────────────────

def _listar_cuentas(data_client):
    res = (
        data_client.table("perfiles")
        .select("id, email, modulos_plan, plan, plan_vence_en, es_admin, habilitado")
        .order("email").execute()
    )
    return res.data


def _toggle_habilitado(data_client, cuenta_id: str, nuevo_estado: bool):
    data_client.table("perfiles").update({"habilitado": nuevo_estado}).eq("id", cuenta_id).execute()


def _revocar_modulo(data_client, cuenta_id: str, modulos_plan: dict, modulo: str):
    """Fuerza el vencimiento de un módulo puntual (no toca los demás)."""
    mp = dict(modulos_plan)
    if modulo in mp:
        mp[modulo] = dict(mp[modulo])
        mp[modulo]["vence_en"] = datetime.now(timezone.utc).isoformat()
        data_client.table("perfiles").update({"modulos_plan": mp}).eq("id", cuenta_id).execute()


def panel_gestion_cuentas(data_client, user_id: str):
    """Panel visible SOLO para admins. Lista cuentas con el estado de CADA
    módulo (mercados/pyme/agro) por separado, más el toggle global de
    habilitar/deshabilitar la cuenta entera."""
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
            mp_cuenta = dict(cuenta.get("modulos_plan") or {})
            if "mercados" not in mp_cuenta and cuenta.get("plan"):
                mp_cuenta["mercados"] = {"nivel": cuenta["plan"], "vence_en": cuenta.get("plan_vence_en")}

            with st.container(border=True):
                c1, c2 = st.columns([4, 1])
                with c1:
                    estado_cta = "🟢 Habilitada" if cuenta.get("habilitado") else "🔴 Deshabilitada"
                    admin_tag = " · 🛠️ admin" if cuenta.get("es_admin") else ""
                    st.markdown(f"**{cuenta['email']}** — {estado_cta}{admin_tag}")
                    partes = []
                    for mod_key, mod_cfg in PRODUCTOS.items():
                        info = mp_cuenta.get(mod_key)
                        if not info:
                            partes.append(f"{mod_cfg['icono']} {mod_cfg['nombre']}: sin activar")
                            continue
                        dias_rest = _dias_restantes(info.get("vence_en"))
                        vig = dias_rest is not None and dias_rest > 0
                        nivel_txt = NOMBRE_NIVEL_DISPLAY.get(info.get("nivel"), info.get("nivel"))
                        venc_txt = f"vence en {int(dias_rest)}d" if vig else "vencido"
                        color = "#3fb950" if vig else "#f85149"
                        partes.append(f"<span style='color:{color}'>{mod_cfg['icono']} {mod_cfg['nombre']}: {nivel_txt} · {venc_txt}</span>")
                    st.markdown(" &nbsp;·&nbsp; ".join(partes), unsafe_allow_html=True)
                with c2:
                    if cuenta.get("habilitado"):
                        if st.button("🚫 Deshabilitar cuenta", key=f"deshab_{cuenta['id']}", use_container_width=True):
                            _toggle_habilitado(data_client, cuenta["id"], False); st.rerun()
                    else:
                        if st.button("✅ Habilitar cuenta", key=f"habil_{cuenta['id']}", use_container_width=True):
                            _toggle_habilitado(data_client, cuenta["id"], True); st.rerun()

                cols_rev = st.columns(len(PRODUCTOS))
                for col_r, (mod_key, mod_cfg) in zip(cols_rev, PRODUCTOS.items()):
                    info = mp_cuenta.get(mod_key)
                    dias_rest = _dias_restantes(info.get("vence_en")) if info else None
                    vig = dias_rest is not None and dias_rest > 0
                    with col_r:
                        if vig and st.button(f"Revocar {mod_cfg['icono']}", key=f"rev_{mod_key}_{cuenta['id']}", use_container_width=True):
                            _revocar_modulo(data_client, cuenta["id"], mp_cuenta, mod_key)
                            st.rerun()


# ── Panel admin: aprobación de pagos ───────────────────────────────

def _extraer_nivel_de_plan_nombre(modulo: str, plan_nombre: str) -> str:
    if modulo == "agro":
        return "unico"
    if not plan_nombre:
        return "basico"
    primera_parte = plan_nombre.split(" - ")[0].strip().lower()
    return "pro" if "pro" in primera_parte else "basico"


def panel_admin_pagos(data_client, user_id: str):
    """Panel visible SOLO para es_admin = true. Solicitudes de pago
    pendientes de CUALQUIER módulo, con botones para aprobar/rechazar.
    Al aprobar, escribe solo la entrada de ESE módulo en modulos_plan,
    sin tocar los otros dos."""
    if not es_admin_usuario(data_client, user_id):
        return

    with st.expander("🛠️ Panel de aprobación de pagos", expanded=False):
        res = (
            data_client.table("solicitudes_pago")
            .select("id, user_id, email, modulo, monto, moneda, nota, creado_en, plan_nombre, dias")
            .eq("estado", "pendiente").order("creado_en", desc=True).execute()
        )
        pendientes = res.data
        if not pendientes:
            st.caption("No hay solicitudes pendientes.")
            return

        for sol in pendientes:
            modulo_sol = sol.get("modulo", "mercados")
            icono_sol = PRODUCTOS.get(modulo_sol, {}).get("icono", "📦")
            nombre_prod_sol = PRODUCTOS.get(modulo_sol, {}).get("nombre", modulo_sol)
            with st.container(border=True):
                st.markdown(
                    f"**{sol['email']}** — {icono_sol} {nombre_prod_sol} · {sol.get('plan_nombre', '—')} "
                    f"({sol.get('dias', 30)} días) — {sol.get('moneda','USD')} ${sol['monto']} ₿"
                )
                if sol.get("nota"):
                    st.caption(f"Nota: {sol['nota']}")
                st.caption(sol["creado_en"])
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ Aprobar", key=f"aprobar_{sol['id']}", use_container_width=True):
                        dias = sol.get("dias", 30)
                        nivel = _extraer_nivel_de_plan_nombre(modulo_sol, sol.get("plan_nombre"))
                        vence = datetime.now(timezone.utc) + timedelta(days=dias)

                        perfil_u = _leer_perfil(data_client, sol["user_id"]) or {}
                        mp_u = _modulos_plan_normalizado(perfil_u)
                        mp_u[modulo_sol] = {"nivel": nivel, "vence_en": vence.isoformat()}

                        data_client.table("perfiles").update({
                            "modulos_plan": mp_u, "habilitado": True,
                        }).eq("id", sol["user_id"]).execute()
                        data_client.table("solicitudes_pago").update({
                            "estado": "aprobado", "revisado_en": datetime.now(timezone.utc).isoformat(),
                        }).eq("id", sol["id"]).execute()
                        st.success(f"Activado: {sol['email']} — {nombre_prod_sol} ({sol.get('plan_nombre')} · {dias} días)")
                        st.rerun()
                with c2:
                    if st.button("❌ Rechazar", key=f"rechazar_{sol['id']}", use_container_width=True):
                        data_client.table("solicitudes_pago").update({
                            "estado": "rechazado", "revisado_en": datetime.now(timezone.utc).isoformat(),
                        }).eq("id", sol["id"]).execute()
                        st.rerun()
