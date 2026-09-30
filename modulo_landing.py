# ==============================================================
#  MÓDULO LANDING — página de entrada de Capital+
#  Todo lo visual/textual de la portada vive acá. Para cambiar la
#  landing solo se edita este archivo, sin tocar el principal.
#
#  Uso desde el archivo principal:
#      from modulo_landing import pantalla_landing
#      ...
#      pantalla_landing(auth_client, cookies)
# ==============================================================

import streamlit as st


def pantalla_landing(auth_client, cookies):
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
        st.markdown("""
        <div class="landing-badge">📡 Análisis Cuantitativo de Mercados</div>
        <div class="landing-title">Invertí con datos,<br>no con <span>corazonadas</span></div>
        <div class="landing-sub">
          Capital+ combina scores cuantitativos, análisis fundamental, optimización de
          cartera y valuación de opciones en una sola herramienta — para acciones, ETFs,
          forex, commodities y cripto.
        </div>
        <div class="landing-sub" style="margin-top:18px">
          🎁 <b style="color:#e6edf3">7 días de prueba gratis</b>, sin tarjeta. Cancelás cuando quieras.
        </div>
        """, unsafe_allow_html=True)

    with col_auth:
        st.markdown('<div class="landing-auth-card">', unsafe_allow_html=True)
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
                        st.rerun()
                    except Exception:
                        st.error("Email o contraseña incorrectos.")

        with tab_registro:
            st.markdown('<div class="landing-auth-sub">Empezá gratis en 30 segundos</div>', unsafe_allow_html=True)
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
                        auth_client.auth.sign_up({"email": email_r, "password": password_r})
                        st.success("¡Cuenta creada! Revisá tu email para confirmarla y después iniciá sesión.")
                    except Exception as e:
                        st.error(f"Error al registrarse: {e}")
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

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
        display:grid;
        grid-template-columns:repeat(4,1fr);
        gap:16px;
        max-width:1080px;
        margin:0 auto;
        padding:0 20px;
        align-items:stretch;
    }
    .pricing-card {
        position:relative;
        background:#0d1117; border:1px solid #21262d; border-top:2px solid #21262d;
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
    .pricing-price {
        font-size:26px; font-weight:800; color:#e6edf3; line-height:1.15;
    }
    .pricing-price small { font-size:13px; color:#8b949e; font-weight:500; }
    .pricing-permes {
        font-size:12px; color:#6CC24A; font-weight:700; margin-top:6px;
    }
    .pricing-sub { font-size:11.5px; color:#8b949e; margin:10px 0 16px 0; flex-grow:1; }
    .pricing-trial { font-size:11.5px; color:#6CC24A; font-weight:700; margin-bottom:3px; }
    .pricing-cancel { font-size:10.5px; color:#6b7d9a; }
    @media (max-width:900px) {
        .pricing-grid { grid-template-columns:repeat(2,1fr); }
    }
    @media (max-width:560px) {
        .pricing-grid { grid-template-columns:1fr; }
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown('<div class="landing-section-title">Elegí tu plan</div>', unsafe_allow_html=True)
    st.markdown('<div class="landing-section-sub">Dos niveles de acceso, pagando en criptomonedas</div>', unsafe_allow_html=True)

    st.markdown("""
    <div class="pricing-grid" style="grid-template-columns:repeat(2,1fr);max-width:640px">
      <div class="pricing-card">
        <div class="pricing-name">Básico</div>
        <div class="pricing-price">U$S10<br><small>/ mes</small></div>
        <div class="pricing-permes">Trimestral U$S25 · Anual U$S80</div>
        <div class="pricing-sub">Acceso a los módulos esenciales</div>
        <div class="pricing-trial">🎁 7 días gratis</div>
        <div class="pricing-cancel">Pago en cripto</div>
      </div>
      <div class="pricing-card featured">
        <div class="pricing-badge">Recomendado</div>
        <div class="pricing-name">Pro</div>
        <div class="pricing-price">U$S15<br><small>/ mes</small></div>
        <div class="pricing-permes">Trimestral U$S40 · Anual U$S130</div>
        <div class="pricing-sub">Acceso completo: Optimizador, Opciones, Señales y más</div>
        <div class="pricing-trial">🎁 7 días gratis</div>
        <div class="pricing-cancel">Pago en cripto</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── FAQ ──────────────────────────────────────────────────────────
    st.markdown('<div class="landing-section-title">Preguntas frecuentes</div>', unsafe_allow_html=True)
    _, col_faq, _ = st.columns([1, 3, 1])
    with col_faq:
        with st.expander("¿Necesito tarjeta para probarlo?"):
            st.write("No. Te registrás con tu email y arrancás el trial de 7 días sin cargar ningún método de pago.")
        with st.expander("¿Qué pasa cuando termina el trial?"):
            st.write("Te pedimos que elijas un plan (Básico o Pro) para seguir con acceso. El pago se realiza en criptomonedas.")
        with st.expander("¿Puedo cancelar cuando quiera?"):
            st.write("Sí, la suscripción se puede cancelar en cualquier momento, sin permanencia mínima.")
        with st.expander("¿Los datos son en tiempo real?"):
            st.write("Los precios se actualizan con caché de hasta 30 minutos según el módulo, usando datos de Yahoo Finance.")
        with st.expander("¿Esto es asesoramiento financiero?"):
            st.write("No. Capital+ es una herramienta de análisis cuantitativo con fines informativos, no constituye recomendación de inversión.")

    st.markdown("""
    <div class="landing-footer">
      📡 Capital+ · Análisis cuantitativo de mercados · Solo informativo, no constituye asesoramiento financiero.
    </div>
    """, unsafe_allow_html=True)
