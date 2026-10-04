#!/usr/bin/env python3
"""
Aplica a modulo_ia_asistente.py los cambios del "Perfil de país desde el
calendario económico".

Uso (en la carpeta donde está tu modulo_ia_asistente.py):
    python aplicar_cambios_calendario.py
    python aplicar_cambios_calendario.py ruta/a/modulo_ia_asistente.py

- Hace un backup: modulo_ia_asistente.py.bak
- Cada reemplazo exige que el texto original aparezca EXACTAMENTE una vez;
  si alguno no coincide, aborta sin modificar el archivo.
- Es idempotente: si ya está aplicado, avisa y no hace nada.
"""
import shutil
import sys

RUTA = sys.argv[1] if len(sys.argv) > 1 else 'modulo_ia_asistente.py'

BLOQUE_NUEVO = r'''# ==============================================================
#  PERFIL DE PAÍS desde el CALENDARIO ECONÓMICO
#  Se activa cuando el mensaje nombra un país. Usa solo los eventos
#  COMPLETOS (previsto + anterior + real, sin None) con lectura,
#  y toma los más recientes.
# ==============================================================

_CAL_MAX_EVENTOS = 15      # cuántos datos completos recientes usa
_CAL_VENTANA_CICLO_DIAS = 180

_PAISES_ALIAS_CAL = {
    'eeuu': 'Estados Unidos', 'ee uu': 'Estados Unidos', 'united states': 'Estados Unidos',
    'uk': 'Reino Unido', 'gran bretana': 'Reino Unido', 'inglaterra': 'Reino Unido',
    'eurozona': 'Europa', 'zona euro': 'Europa', 'union europea': 'Europa',
    'holanda': 'Países Bajos', 'corea': 'Corea del Sur', 'republica checa': 'Chequia',
    'emiratos': 'Emiratos Árabes', 'arabia': 'Arabia Saudita',
}


def _limpiar_cal(s):
    s = re.sub(r'[^a-z0-9 ]', ' ', _norm(s))
    return re.sub(r'\s+', ' ', s).strip()


def _detectar_paises_calendario(texto):
    """Países del calendario nombrados en el mensaje (sin acentos, con alias)."""
    try:
        from modulo_calendario import PAISES
    except Exception:
        return []
    t = f' {_limpiar_cal(texto)} '
    mapa = {_limpiar_cal(p): p for p in PAISES}
    mapa.update(_PAISES_ALIAS_CAL)
    encontrados = []
    for clave in sorted(mapa, key=len, reverse=True):   # más largos primero
        patron = f' {clave} '
        if patron in t:
            encontrados.append(mapa[clave])
            t = t.replace(patron, ' ')                  # se "consume" lo ya matcheado
    if re.search(r'\bUSA\b', texto) and 'Estados Unidos' not in encontrados:
        encontrados.append('Estados Unidos')            # "usa" en minúscula es el verbo
    return list(dict.fromkeys(encontrados))


def _fmt_cal(v, unidad):
    try:
        x = float(v)
        txt = f'{x:,.2f}'.rstrip('0').rstrip('.')
    except Exception:
        return 'N/D'
    u = (unidad or '').strip()
    return f'{txt}{u}' if u in ('%', 'K', 'M', 'B') else (f'{txt} {u}' if u else txt)


def _perfil_calendario_pais(pais, ctx):
    supabase = ctx.get('supabase')
    if supabase is None:
        return f"No tengo conexión con el calendario económico para armar el perfil de **{pais}**."
    try:
        import modulo_calendario as mc
        df = mc._df_registros_procesado(supabase)
    except Exception as e:
        return f"⚠️ No pude leer el calendario económico: {e}"
    if df is None or df.empty:
        return "El calendario económico todavía no tiene eventos cargados."

    d = df[df['pais'] == pais]
    if d.empty:
        return f"Todavía no hay eventos del calendario económico cargados para **{pais}**."

    # Solo datos completos (sin None), con lectura de bueno/malo, y los más recientes
    completos = d.dropna(subset=['previsto', 'anterior', 'real', 'fecha_dt'])
    completos = completos[~completos['es_neutral']]
    completos = completos[completos['impacto_mercado'].fillna('').astype(str).str.strip() != '']
    if completos.empty:
        return (f"**{pais}** tiene eventos cargados, pero ninguno con previsto, anterior y real "
                f"completos y con lectura todavía.")

    rec = (completos.sort_values(['fecha_dt', 'peso'], ascending=[False, False])
                    .head(_CAL_MAX_EVENTOS))
    ultima = rec['fecha_dt'].max()

    L = [f"### 🗓️ Calendario económico — {pais}",
         f"_Perfil armado con los {len(rec)} datos completos más recientes "
         f"(previsto, anterior y real cargados), hasta el {ultima:%d/%m/%Y}._"]

    # ── Tabla de eventos ──
    L.append("\n| Fecha | Evento | Previsto | Anterior | Real | Lectura |\n|---|---|---|---|---|---|")
    for _, r in rec.iterrows():
        u = r.get('unidad') or ''
        evento = str(r['evento']).replace('|', '/')
        L.append(f"| {r['fecha_dt']:%d/%m/%Y} | {evento} | {_fmt_cal(r['previsto'], u)} | "
                 f"{_fmt_cal(r['anterior'], u)} | {_fmt_cal(r['real'], u)} | {r['impacto_mercado']} |")

    # ── Panorama por categoría ──
    L.append("\n**🧭 Panorama por categoría (sobre estos datos):**")
    filas_cat = []
    for cat in sorted(rec['categoria'].unique()):
        prom, n = mc._promedio_ponderado_score(rec[rec['categoria'] == cat])
        if prom is not None:
            filas_cat.append((cat, prom, n))
    for cat, prom, n in sorted(filas_cat, key=lambda x: x[1], reverse=True):
        emo, txt = mc._asset_verdict(prom)
        L.append(f"- **{cat}**: {emo} {txt} ({prom:+.2f}, {n} dato{'s' if n != 1 else ''})")

    # ── Impacto en activos ──
    L.append("\n**💹 Impacto en activos financieros:**")
    activos = mc._resumen_activos_pais(rec)
    for campo, nombre in mc.ASSET_FIELDS:
        score, n = activos.get(campo, (None, 0))
        emo, txt = mc._asset_verdict(score)
        L.append(f"- {nombre}: {emo} {txt}" + (f" ({score:+.2f})" if score is not None else ""))

    # ── Fase del ciclo y tasas (ventana reciente) ──
    punt = d[~d['es_neutral']].dropna(subset=['fecha_dt'])
    ventana = punt[punt['fecha_dt'] >= ultima - pd.Timedelta(days=_CAL_VENTANA_CICLO_DIAS)]
    try:
        fase = mc._fase_ciclo_economico(pais, ventana)
    except Exception:
        fase = None
    if fase:
        L.append(f"\n**🔄 Fase del ciclo:** {fase['nombre']} — {fase['resumen']}.")
    try:
        out = mc._outlook_tasas(ventana)
    except Exception:
        out = None
    if out:
        s = out[0]
        txt = ("sesgo a tasas más altas / sin apuro para recortar" if s >= 0.15 else
               "sesgo a tasas más bajas" if s <= -0.15 else "balance mixto, sin sesgo claro")
        L.append(f"**🏦 Tasas a futuro:** {txt} ({s:+.2f}).")

    # ── Lectura macro de los 3 datos más recientes ──
    L.append("\n**💬 Lectura de los datos más recientes:**")
    for _, r in rec.head(3).iterrows():
        lect = str(r.get('lectura_macro') or '').strip()
        if lect:
            L.append(f"- *{r['evento']}* ({r['fecha_dt']:%d/%m}): {lect[:220]}")
    return "\n".join(L)


def _responder_perfil_pais(paises, ctx):
    return "\n\n---\n\n".join(_perfil_calendario_pais(p, ctx) for p in paises[:2])


def _unir_perfil_pais(resp, paises, ctx):
    if not paises:
        return resp
    return f"{resp}\n\n---\n\n{_responder_perfil_pais(paises, ctx)}"


'''

# (descripción, texto original, texto nuevo)
REEMPLAZOS = [
    # 2a) Paso 0
    ("2a) Paso 0 (ia_esperando_ticker)",
     """        tks = extraer_tickers(texto_usuario, universo, ctx['validar_ticker'], ctx)
        if not tks:
            v = ctx['validar_ticker'](texto_usuario.strip())
            tks = [v] if v else []
        if tks:
            st.session_state['ia_ultimo_ticker'] = tks[0]
            return _responder_analizar(tks[0], ctx)
        if len(texto_usuario.split()) <= 2:""",
     """        tks = extraer_tickers(texto_usuario, universo, ctx['validar_ticker'], ctx)
        paises_0 = _detectar_paises_calendario(texto_usuario)
        if not tks and not paises_0:
            v = ctx['validar_ticker'](texto_usuario.strip())
            tks = [v] if v else []
        if tks:
            st.session_state['ia_ultimo_ticker'] = tks[0]
            return _unir_perfil_pais(_responder_analizar(tks[0], ctx), paises_0, ctx)
        if paises_0:
            return _responder_perfil_pais(paises_0, ctx)
        if len(texto_usuario.split()) <= 2:"""),

    # 2b) paises_cal
    ("2b) paises_cal tras extraer_tickers",
     """    intencion = detectar_intencion(texto_usuario)
    tickers = extraer_tickers(texto_usuario, universo, ctx['validar_ticker'], ctx)
""",
     """    intencion = detectar_intencion(texto_usuario)
    tickers = extraer_tickers(texto_usuario, universo, ctx['validar_ticker'], ctx)
    paises_cal = (_detectar_paises_calendario(texto_usuario)
                  if intencion in ('analizar_ticker', 'ayuda') else [])
"""),

    # 2c) fallback último ticker
    ("2c) fallback del último ticker",
     """    if (not tickers and not industria_detectada and st.session_state.get('ia_ultimo_ticker')""",
     """    if (not tickers and not industria_detectada and not paises_cal
            and st.session_state.get('ia_ultimo_ticker')"""),

    # 2d-1) industria
    ("2d-1) industria + país",
     """    if industria_detectada and not tickers:
        return _responder_industria(industria_detectada, ctx)
""",
     """    if industria_detectada and not tickers:
        return _unir_perfil_pais(_responder_industria(industria_detectada, ctx), paises_cal, ctx)
"""),

    # 2d-2) sin tickers
    ("2d-2) sin tickers -> perfil de país",
     """    if not tickers:
        return ("No detecté ningún ticker en tu mensaje.""",
     """    if not tickers:
        if paises_cal:
            return _responder_perfil_pais(paises_cal, ctx)
        return ("No detecté ningún ticker en tu mensaje."""),

    # 2d-3) análisis final
    ("2d-3) análisis final + país",
     """\n    return _responder_analizar(tickers[0], ctx)\n""",
     """\n    return _unir_perfil_pais(_responder_analizar(tickers[0], ctx), paises_cal, ctx)\n"""),

    # 2e) ayuda
    ("2e) línea en _respuesta_ayuda",
     """- **📐 Top-Down Cuantitativo** — *"score de mediano plazo de AAPL"*""",
     """- **🗓️ Perfil de un país (calendario económico)** — *"Estados Unidos"*, *"cómo está Japón"*: te muestro los datos más recientes con previsto, anterior y real, su lectura y el impacto en cada activo
- **📐 Top-Down Cuantitativo** — *"score de mediano plazo de AAPL"*"""),
]


def main():
    with open(RUTA, encoding='utf-8') as f:
        src = f.read()

    if '_detectar_paises_calendario' in src:
        print('Ya parece estar aplicado (existe _detectar_paises_calendario). No hago nada.')
        return

    # 1) Insertar el bloque nuevo antes de la sección "# RESPUESTAS"
    marca = '#  RESPUESTAS\n'
    if src.count(marca) != 1:
        sys.exit(f'ERROR: no encontré una única sección "{marca.strip()}" '
                 f'(encontradas: {src.count(marca)}). No modifiqué nada.')
    i = src.index(marca)
    ini = src.rfind('# ====', 0, i)          # línea "# =====" que abre la sección
    ini = src.rfind('\n', 0, ini) + 1
    nuevo = src[:ini] + BLOQUE_NUEVO + src[ini:]

    # 2) Reemplazos dentro de responder() y ayuda
    for desc, viejo, reemp in REEMPLAZOS:
        n = nuevo.count(viejo)
        if n != 1:
            sys.exit(f'ERROR en {desc}: el texto original aparece {n} veces (debería ser 1). '
                     f'No modifiqué nada.')
        nuevo = nuevo.replace(viejo, reemp)
        print(f'OK  {desc}')

    shutil.copyfile(RUTA, RUTA + '.bak')
    with open(RUTA, 'w', encoding='utf-8') as f:
        f.write(nuevo)
    print(f'\nListo. Backup en {RUTA}.bak')


if __name__ == '__main__':
    main()
