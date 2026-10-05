# ==============================================================
#  MÓDULO LANDING — página de entrada de Capital+
#  Todo lo visual/textual de la portada vive acá. Para cambiar la
#  landing solo se edita este archivo, sin tocar el principal.
#
#  Uso desde el archivo principal:
#      from modulo_landing import pantalla_landing, buscar_uid_por_email
#      ...
#      pantalla_landing(auth_client, cookies, supabase)
#
#  NOVEDAD: el usuario elige el servicio que quiere probar
#  (Mercados / PyMEs). La elección:
#    - se guarda en st.session_state['servicio_elegido']
#    - se guarda en el perfil de Supabase Auth (user_metadata)
#      al registrarse, así sobrevive a la confirmación por email
#    - se vuelve a leer al iniciar sesión
#  El archivo principal usa ese valor para decidir a qué módulo
#  mandarlo y de qué módulo darle la prueba gratis.
#
#  RECUPERAR CONTRASEÑA (manual, sin mails):
#    1) El usuario pide el reseteo con su email  -> tabla solicitudes_reset (pendiente)
#    2) El admin lo habilita desde el panel      -> se genera un código de 6 dígitos
#    3) El usuario ingresa email + código + contraseña nueva
# ==============================================================

import streamlit as st
import secrets
from datetime import datetime, timezone


# ──────────────────────────────────────────────────────────────
#  CATÁLOGO DE SERVICIOS — para habilitar/deshabilitar uno,
#  solo cambiá 'disponible'. El id debe coincidir con las claves
#  de PRODUCTOS en modulo_pago_manual ('mercados', 'pyme', ...).
# ──────────────────────────────────────────────────────────────
SERVICIOS = {
    'mercados': {
        'icono': '📈',
        'nombre': 'Mercados & Inversiones',
        'desc': 'Scoring cuantitativo, fundamental, optimizador de cartera, opciones y más.',
        'disponible': True,
        'badge': '📡 Análisis Cuantitativo de Mercados',
        'titulo_html': 'Invertí con datos,<br>no con <span>corazonadas</span>',
        'subtitulo': ('Capital+ combina scores cuantitativos, análisis fundamental, optimización de '
                      'cartera y valuación de opciones en una sola herramienta — para acciones, ETFs, '
                      'forex, commodities y cripto.'),
    },
    'pyme': {
        'icono': '🏢',
        'nombre': 'PyMEs',
        'desc': 'Gestión de tu negocio: ventas, stock, clientes y caja en un solo lugar.',
        'disponible': False,   # ← ponelo en True cuando lo abras al público
        'badge': '🏢 Gestión para PyMEs',
        'titulo_html': 'Ordená tu negocio,<br>tomá decisiones con <span>números</span>',
        'subtitulo': ('Controlá ventas, stock, clientes y caja desde un solo lugar, '
                      'con acceso para todo tu equipo.'),
    },
}
SERVICIO_DEFAULT = 'mercados'


def _servicio_actual():
    """Devuelve el id del servicio elegido, validando que exista y esté disponible."""
    sel = st.session_state.get('landing_servicio', SERVICIO_DEFAULT)
    if sel not in SERVICIOS or not SERVICIOS[sel]['disponible']:
        sel = SERVICIO_DEFAULT
        st.session_state['landing_servicio'] = sel
    return sel


def _render_selector_servicio():
    """Tarjetas clickeables para elegir el servicio. Devuelve el id elegido."""
    st.markdown(
        '<div style="font-size:12px;font-weight:700;color:#8b949e;text-transform:uppercase;'
        'letter-spacing:.8px;margin:22px 0 8px 0">¿Qué servicio querés probar?</div>',
        unsafe_allow_html=True,
    )
    actual = _servicio_actual()
    cols = st.columns(len(SERVICIOS))
    css_extra = ''
    for col, (sid, info) in zip(cols, SERVICIOS.items()):
        with col:
            cont_key = f'landing_svc_{sid}'
            with st.container(key=cont_key):
                etiqueta = f"{info['icono']} {info['nombre']}"
                if not info['disponible']:
                    etiqueta += ' · Próximamente'
                if st.button(etiqueta, key=f'landing_btn_svc_{sid}',
                             use_container_width=True, disabled=not info['disponible']):
                    st.session_state['landing_servicio'] = sid
                    st.rerun()
            st.markdown(
                f'<div style="font-size:11.5px;color:#6b7d9a;line-height:1.5;margin-top:4px">{info["desc"]}</div>',
                unsafe_allow_html=True,
            )
        if sid == actual:
            css_extra += f"""
            .st-key-{cont_key} button {{
                border: 1.5px solid #6CC24A !important;
                background: rgba(108,194,74,0.10) !important;
                color: #6CC24A !important;
                font-weight: 700 !important;
                box-shadow: 0 0 0 2px rgba(108,194,74,0.15) !important;
            }}"""
    if css_extra:
        st.markdown(f'<style>{css_extra}</style>', unsafe_allow_html=True)
    return actual


# ──────────────────────────────────────────────────────────────
#  RECUPERAR CONTRASEÑA — flujo manual con aprobación del admin
# ──────────────────────────────────────────────────────────────
def buscar_uid_por_email(data_client, email):
    """Devuelve el id del usuario de Auth con ese email, o None."""
    email = (email or "").strip().lower()
    page = 1
    while True:
        usuarios = data_client.auth.admin.list_users(page=page, per_page=200)
        if not usuarios:
            return None
        for u in usuarios:
            if (u.email or "").lower() == email:
                return u.id
        page += 1


def _render_recuperar_contrasena(data_client):
    """Recuperación manual: el usuario pide, el admin habilita y le pasa un código."""
    if data_client is None:
        st.caption("Para recuperar tu contraseña escribinos a **capitalmas88@gmail.com**.")
        return

    paso = st.radio("¿Qué necesitás?", ["Pedir reseteo", "Ya tengo mi código"],
                    horizontal=True, key="rec_paso", label_visibility="collapsed")

    if paso == "Pedir reseteo":
        email_p = st.text_input("Tu email", key="rec_email_pedir")
        if st.button("Solicitar reseteo", key="rec_btn_pedir", use_container_width=True):
            email_p = email_p.strip().lower()
            if not email_p:
                st.error("Escribí tu email.")
            else:
                try:
                    ya = (data_client.table("solicitudes_reset").select("id")
                          .eq("email", email_p).eq("estado", "pendiente").limit(1).execute())
                    if not ya.data:
                        data_client.table("solicitudes_reset").insert({"email": email_p}).execute()
                    st.success("Solicitud enviada. Te vamos a contactar para verificar tu identidad "
                               "y pasarte un código. Con ese código volvé acá y elegí \"Ya tengo mi código\".")
                except Exception:
                    st.error("No pudimos registrar la solicitud. Escribinos a capitalmas88@gmail.com.")
    else:
        email_c = st.text_input("Tu email", key="rec_email_cod")
        codigo = st.text_input("Código de 6 dígitos", key="rec_codigo", max_chars=6)
        nueva = st.text_input("Contraseña nueva", type="password", key="rec_nueva")
        nueva2 = st.text_input("Confirmar contraseña", type="password", key="rec_nueva2")
        if st.button("Cambiar contraseña", key="rec_btn_cambiar", use_container_width=True, type="primary"):
            email_c = email_c.strip().lower()
            codigo = codigo.strip()
            if not email_c or not codigo:
                st.error("Completá email y código.")
            elif len(nueva) < 6:
                st.error("La contraseña debe tener al menos 6 caracteres.")
            elif nueva != nueva2:
                st.error("Las contraseñas no coinciden.")
            else:
                msg_generico = "Email o código incorrecto, o la solicitud venció. Pedí una nueva si hace falta."
                try:
                    res = (data_client.table("solicitudes_reset").select("*")
                           .eq("email", email_c).eq("estado", "habilitada")
                           .order("id", desc=True).limit(1).execute())
                    sol = res.data[0] if res.data else None

                    vencida = True
                    if sol and sol.get("vence_en"):
                        vence = datetime.fromisoformat(sol["vence_en"].replace("Z", "+00:00"))
                        vencida = datetime.now(timezone.utc) > vence

                    if sol is None or vencida:
                        st.error(msg_generico)
                    elif (sol.get("intentos") or 0) >= 5:
                        st.error("Demasiados intentos. Pedí un reseteo nuevo.")
                    elif not secrets.compare_digest(str(sol.get("codigo") or ""), codigo):
                        (data_client.table("solicitudes_reset")
                         .update({"intentos": (sol.get("intentos") or 0) + 1})
                         .eq("id", sol["id"]).execute())
                        st.error(msg_generico)
                    else:
                        uid = buscar_uid_por_email(data_client, email_c)
                        if uid is None:
                            st.error(msg_generico)
                        else:
                            data_client.auth.admin.update_user_by_id(uid, {"password": nueva})
                            (data_client.table("solicitudes_reset")
                             .update({"estado": "usada"}).eq("id", sol["id"]).execute())
                            st.success("¡Listo! Contraseña actualizada. Ya podés iniciar sesión.")
                except Exception as e:
                    st.error(f"Error: {e}")


def pantalla_landing(auth_client, cookies, data_client=None):
    """data_client: cliente de Supabase con service_role (el mismo `supabase` del
    principal). Se usa para: guardar perfiles.servicio_elegido al registrarse y
    para el flujo de recuperación de contraseña (tabla solicitudes_reset)."""
    st.markdown("""
    <style>
    .landing-hero-wrap { max-width:1100px; margin:40px auto 0 auto; padding:0 20px; }
    .landing-badge {
        display:inline-block; padding:5px 14px; border-radius:20px; font-size:11px;
        font-weight:700; letter-spacing:.8px; text-transform:uppercase;
        background:rgba(108,194,74,0.12); border:1px solid #6CC24A; color:#6CC24A;
        margin-bottom:18px;
    }
    .landing-title {
        font-size:34px; font-weight:800; color:#e6edf3; letter-spacing:-1px;
        line-height:1.18; margin-bottom:14px;
    }
    .landing-title span { color:#6CC24A; }
    .landing-sub { font-size:14.5px; color:#8b949e; line-height:1.7; margin-bottom:6px; }
    .landing-auth-card {
        background:#0d1117; border:1px solid #21262d; border-top:2px solid #6CC24A;
        border-radius:14px; padding:26px 26px 18px 26px;
    }
    .landing-auth-title { font-size:16px; font-weight:700; color:#e6edf3; margin-bottom:2px; }
    .landing-auth-sub { font-size:12px; color:#6CC24A; margin-bottom:16px; }
    .landing-section-title {
        text-align:center; font-size:24px; font-weight:800; color:#e6edf3;
        margin:70px 0 8px 0; letter-spacing:-0.5px;
    }
    .landing-section-sub { text-align:center; font-size:13.5px; color:#8b949e; margin-bottom:36px; }
    .landing-features {
        display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
        gap:16px; max-width:1080px; margin:0 auto; padding:0 20px;
    }
    .landing-card {
        background:#0d1117; border:1px solid #21262d; border-radius:12px;
        padding:22px 20px; transition:border-color .2s;
    }
    .landing-card:hover { border-color:#3a7bd5; }
    .landing-card-icon { font-size:26px; margin-bottom:10px; }
    .landing-card-title { font-size:14px; font-weight:700; color:#e6edf3; margin-bottom:6px; }
    .landing-card-desc { font-size:12.5px; color:#8b949e; line-height:1.6; }
    .landing-steps {
        display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
        gap:20px; max-width:900px; margin:0 auto; padding:0 20px;
    }
    .landing-step { text-align:center; padding:10px; }
    .landing-step-num {
        width:36px; height:36px; border-radius:50%; background:rgba(108,194,74,0.12);
        border:1px solid #6CC24A; color:#6CC24A; font-weight:800; font-size:15px;
        display:flex; align-items:center; justify-content:center; margin:0 auto 12px auto;
    }
    .landing-step-title { font-size:13.5px; font-weight:700; color:#e6edf3; margin-bottom:6px; }
    .landing-step-desc { font-size:12px; color:#8b949e; line-height:1.6; }
    .landing-pricing {
        max-width:380px; margin:0 auto; background:#0d1117; border:1px solid #21262d;
        border-top:2px solid #6CC24A; border-radius:16px; padding:32px 28px; text-align:center;
    }
    .landing-price { font-size:42px; font-weight:800; color:#e6edf3; margin:10px 0 2px 0; }
    .landing-price-sub { font-size:12px; color:#8b949e; margin-bottom:20px; }
    .landing-trial { font-size:12px; color:#6CC24A; font-weight:700; margin-bottom:4px; }
    .landing-cancel { font-size:11px; color:#6b7d9a; margin-bottom:4px; }
    .landing-footer { text-align:center; color:#3a4a5a; font-size:11px; padding:50px 20px 30px 20px; }
    </style>
    """, unsafe_allow_html=True)

    # ── HERO + LOGIN/REGISTRO lado a lado ──────────────────────────────
    st.markdown('<div class="landing-hero-wrap">', unsafe_allow_html=True)
    col_hero, col_auth = st.columns([1.15, 1], gap="large")

    with col_hero:
        servicio = _servicio_actual()
        info = SERVICIOS[servicio]
        st.markdown(f"""
        <div class="landing-badge">{info['badge']}</div>
        <div class="landing-title">{info['titulo_html']}</div>
        <div class="landing-sub">{info['subtitulo']}</div>
        <div class="landing-sub" style="margin-top:18px">
          🎁 <b style="color:#e6edf3">7 días de prueba gratis</b>, sin tarjeta. Cancelás cuando quieras.
        </div>
        """, unsafe_allow_html=True)
        # Selector de servicio (si cambia, rerun y se actualiza todo el hero)
        servicio = _render_selector_servicio()
        info = SERVICIOS[servicio]

    with col_auth:
        st.markdown('<div class="landing-auth-card">', unsafe_allow_html=True)
        st.markdown(
            f'<div style="font-size:11.5px;color:#8b949e;margin-bottom:8px">'
            f'Servicio elegido: <b style="color:#6CC24A">{info["icono"]} {info["nombre"]}</b></div>',
            unsafe_allow_html=True,
        )
        tab_login, tab_registro = st.tabs(["Iniciar sesión", "Crear cuenta gratis"])

        with tab_login:
            st.markdown('<div class="landing-auth-sub">Bienvenido de nuevo</div>', unsafe_allow_html=True)
            email = st.text_input("Email", key="landing_login_email")
            password = st.text_input("Contraseña", type="password", key="landing_login_pass")
            if st.button("Entrar", use_container_width=True, key="landing_btn_login", type="primary"):
                if not email or not password:
                    st.error("Completá email y contraseña.")
                else:
                    try:
                        res = auth_client.auth.sign_in_with_password({"email": email, "password": password})
                        st.session_state["usuario"] = res.user
                        cookies.set("sb_refresh_token", res.session.refresh_token)
                        meta = getattr(res.user, "user_metadata", None) or {}
                        st.session_state["servicio_elegido"] = meta.get("servicio_elegido") or servicio
                        st.rerun()
                    except Exception:
                        st.error("Email o contraseña incorrectos.")
            with st.expander("¿Olvidaste tu contraseña?"):
                _render_recuperar_contrasena(data_client)

        with tab_registro:
            st.markdown(
                f'<div class="landing-auth-sub">Empezá tu prueba gratis de {info["nombre"]} en 30 segundos</div>',
                unsafe_allow_html=True,
            )
            email_r = st.text_input("Email", key="landing_reg_email")
            password_r = st.text_input("Contraseña", type="password", key="landing_reg_pass")
            password_r2 = st.text_input("Confirmar contraseña", type="password", key="landing_reg_pass2")
            if st.button("Crear cuenta gratis", use_container_width=True, key="landing_btn_registro", type="primary"):
                if not email_r or not password_r:
                    st.error("Completá email y contraseña.")
                elif password_r != password_r2:
                    st.error("Las contraseñas no coinciden.")
                elif len(password_r) < 6:
                    st.error("La contraseña debe tener al menos 6 caracteres.")
                else:
                    try:
                        res_reg = auth_client.auth.sign_up({
                            "email": email_r,
                            "password": password_r,
                            # 1) Metadata de Auth: persiste aunque confirme el mail desde otro dispositivo
                            "options": {"data": {"servicio_elegido": servicio}},
                        })
                        st.session_state["servicio_elegido"] = servicio

                        # 2) Tabla perfiles: queda visible en Supabase y consultable desde el panel admin.
                        #    Si la fila de perfiles todavía no existe o la columna falta, no rompe el registro.
                        user_nuevo = getattr(res_reg, "user", None)
                        if data_client is not None and user_nuevo is not None:
                            try:
                                (data_client.table("perfiles")
                                 .update({"servicio_elegido": servicio})
                                 .eq("id", user_nuevo.id).execute())
                            except Exception:
                                pass
                        st.success("¡Cuenta creada! Revisá tu email para confirmarla y después iniciá sesión.")
                    except Exception as e:
                        st.error(f"Error al registrarse: {e}")
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

    # ── CONTENIDO SEGÚN SERVICIO ─────────────────────────────────────
    # Por ahora solo Mercados tiene secciones propias. Cuando abras PyMEs
    # agregá acá un bloque _seccion_pyme() y listo.
    if servicio == 'mercados':
        _seccion_mercados()
    else:
        st.markdown("""
        <div class="landing-section-title">Muy pronto</div>
        <div class="landing-section-sub">Estamos terminando de preparar este servicio.</div>
        """, unsafe_allow_html=True)

    # ── FAQ ──────────────────────────────────────────────────────────
    st.markdown('<div class="landing-section-title">Preguntas frecuentes</div>', unsafe_allow_html=True)
    _, col_faq, _ = st.columns([1, 3, 1])
    with col_faq:
        with st.expander("¿Necesito tarjeta para probarlo?"):
            st.write("No. Te registrás con tu email y arrancás el trial de 7 días sin cargar ningún método de pago.")
        with st.expander("¿Qué pasa cuando termina el trial?"):
            st.write("Te pedimos que elijas un plan para seguir con acceso. El pago se realiza en criptomonedas.")
        with st.expander("¿Puedo cancelar cuando quiera?"):
            st.write("Sí, la suscripción se puede cancelar en cualquier momento, sin permanencia mínima.")
        with st.expander("¿Puedo probar más de un servicio?"):
            st.write("Cada servicio tiene su propia prueba gratuita. Podés sumar otro más adelante desde tu cuenta.")
        with st.expander("¿Los datos son en tiempo real?"):
            st.write("En Mercados, los precios se actualizan con caché de hasta 30 minutos según el módulo, usando datos de Yahoo Finance.")
        with st.expander("¿Esto es asesoramiento financiero?"):
            st.write("No. Capital+ es una herramienta de análisis cuantitativo con fines informativos, no constituye recomendación de inversión.")

    st.markdown("""
    <div class="landing-footer">
      📡 Capital+ · Análisis cuantitativo de mercados · Solo informativo, no constituye asesoramiento financiero.
    </div>
    """, unsafe_allow_html=True)


def _seccion_mercados():
    # ── FEATURES ─────────────────────────────────────────────────────
    st.markdown("""
    <div class="landing-section-title">Todo lo que necesitás para decidir</div>
    <div class="landing-section-sub">Seis módulos integrados, sin saltar entre herramientas distintas</div>
    <div class="landing-features">
      <div class="landing-card">
        <div class="landing-card-icon">⚡</div>
        <div class="landing-card-title">Scoring cuantitativo</div>
        <div class="landing-card-desc">Percentiles históricos, tendencia, reversión a la media y riesgo — corto y largo plazo, en un ranking claro.</div>
      </div>
      <div class="landing-card">
        <div class="landing-card-icon">📊</div>
        <div class="landing-card-title">Análisis fundamental</div>
        <div class="landing-card-desc">Ratios financieros comparados contra benchmarks por sector, con señales automáticas de valuación.</div>
      </div>
      <div class="landing-card">
        <div class="landing-card-icon">🧮</div>
        <div class="landing-card-title">Optimizador de cartera</div>
        <div class="landing-card-desc">Simulación Monte Carlo: encontrá la combinación de activos con mejor relación riesgo-retorno.</div>
      </div>
      <div class="landing-card">
        <div class="landing-card-icon">🎲</div>
        <div class="landing-card-title">Valuación de opciones</div>
        <div class="landing-card-desc">Black-Scholes, binomial, griegas y catálogo de estrategias, con payoff visual.</div>
      </div>
      <div class="landing-card">
        <div class="landing-card-icon">🔗</div>
        <div class="landing-card-title">Scanner de pares</div>
        <div class="landing-card-desc">Detectá oportunidades de reversión a la media entre activos del mismo sector.</div>
      </div>
      <div class="landing-card">
        <div class="landing-card-icon">📆</div>
        <div class="landing-card-title">Calendario económico</div>
        <div class="landing-card-desc">Eventos macro relevantes y su impacto esperado en los mercados, todo en un solo lugar.</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── CÓMO FUNCIONA ────────────────────────────────────────────────
    st.markdown("""
    <div class="landing-section-title">Empezá en 3 pasos</div>
    <div class="landing-section-sub">Sin instalar nada, todo desde el navegador</div>
    <div class="landing-steps">
      <div class="landing-step">
        <div class="landing-step-num">1</div>
        <div class="landing-step-title">Creá tu cuenta</div>
        <div class="landing-step-desc">Registrate gratis con tu email arriba. Sin tarjeta, sin compromiso.</div>
      </div>
      <div class="landing-step">
        <div class="landing-step-num">2</div>
        <div class="landing-step-title">Probá 7 días gratis</div>
        <div class="landing-step-desc">Acceso completo a todos los módulos, sin restricciones.</div>
      </div>
      <div class="landing-step">
        <div class="landing-step-num">3</div>
        <div class="landing-step-title">Elegí tu plan</div>
        <div class="landing-step-desc">Básico o Pro, pagando en cripto. Cancelás cuando quieras, sin ataduras.</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── PRICING ──────────────────────────────────────────────────────
    st.markdown("""
    <style>
    .pricing-grid {
        display:grid; grid-template-columns:repeat(4,1fr); gap:16px;
        max-width:1080px; margin:0 auto; padding:0 20px; align-items:stretch;
    }
    .pricing-card {
        position:relative; background:#0d1117; border:1px solid #21262d; border-top:2px solid #21262d;
        border-radius:14px; padding:26px 20px 22px 20px;
        text-align:center; display:flex; flex-direction:column;
        transition:border-color .2s, transform .2s;
    }
    .pricing-card:hover { border-color:#3a7bd5; transform:translateY(-2px); }
    .pricing-card.featured {
        border-color:#6CC24A; border-top:2px solid #6CC24A;
        box-shadow:0 0 0 1px rgba(108,194,74,0.25);
    }
    .pricing-badge {
        position:absolute; top:-11px; left:50%; transform:translateX(-50%);
        background:#6CC24A; color:#07090f; font-size:10px; font-weight:800;
        letter-spacing:.6px; text-transform:uppercase;
        padding:4px 14px; border-radius:20px; white-space:nowrap;
    }
    .pricing-name {
        font-size:12px; color:#8b949e; font-weight:700;
        text-transform:uppercase; letter-spacing:1px; margin-bottom:14px;
    }
    .pricing-price { font-size:26px; font-weight:800; color:#e6edf3; line-height:1.15; }
    .pricing-price small { font-size:13px; color:#8b949e; font-weight:500; }
    .pricing-permes { font-size:12px; color:#6CC24A; font-weight:700; margin-top:6px; }
    .pricing-sub { font-size:11.5px; color:#8b949e; margin:10px 0 16px 0; flex-grow:1; }
    .pricing-trial { font-size:11.5px; color:#6CC24A; font-weight:700; margin-bottom:3px; }
    .pricing-cancel { font-size:10.5px; color:#6b7d9a; }
    @media (max-width:900px) { .pricing-grid { grid-template-columns:repeat(2,1fr); } }
    @media (max-width:560px) { .pricing-grid { grid-template-columns:1fr; } }
    </style>
    """, unsafe_allow_html=True)

    st.markdown('<div class="landing-section-title">Elegí tu plan</div>', unsafe_allow_html=True)
    st.markdown('<div class="landing-section-sub">Dos niveles de acceso, pagando en criptomonedas</div>', unsafe_allow_html=True)

    st.markdown("""
    <div class="pricing-grid" style="grid-template-columns:repeat(2,1fr);max-width:640px">
      <div class="pricing-card">
        <div class="pricing-name">Básico</div>
        <div class="pricing-price">U$S14<br><small>/ mes</small></div>
        <div class="pricing-permes">Anual U$S120</div>
        <div class="pricing-sub">Acceso a los módulos esenciales</div>
        <div class="pricing-trial">🎁 7 días gratis</div>
        <div class="pricing-cancel">Pago en cripto</div>
      </div>
      <div class="pricing-card featured">
        <div class="pricing-badge">Recomendado</div>
        <div class="pricing-name">Pro</div>
        <div class="pricing-price">U$S20<br><small>/ mes</small></div>
        <div class="pricing-permes">Anual U$S160</div>
        <div class="pricing-sub">Acceso completo: Optimizador, Opciones, Señales y más</div>
        <div class="pricing-trial">🎁 7 días gratis</div>
        <div class="pricing-cancel">Pago en cripto</div>
      </div>
    </div>
    """, unsafe_allow_html=True)
