# ==============================================================
#  MÓDULO CALENDARIO ECONÓMICO — versión Streamlit + Supabase
#  Puerto 1:1 de la lógica que estaba en Google Apps Script/Sheets.
#  Se integra como un módulo nativo más de app.py (mismo patrón que
#  modulo_opciones.py / finanzas_ui.py).
#
#  ── Cambios de esta versión ──────────────────────────────────
#  1) EVENTOS ampliado: se agregaron todos los tipos de dato que
#     aparecen en el calendario económico real (PMI de distintos
#     países, subastas de deuda, comparecencias de bancos centrales,
#     PIB mensual/anualizado, comercio exterior, vivienda, energía,
#     posicionamiento CFTC, etc.), cada uno con su categoría, unidad
#     e impacto — ver EVENTOS_EXTENDIDOS más abajo.
#  2) Interpretación macro por categoría (CATEGORIA_INTERPRETACION):
#     los eventos curados a mano que ya tenías siguen funcionando
#     igual. Los eventos nuevos usan una interpretación genérica
#     según su categoría, así no hace falta escribir una entrada
#     manual por cada uno (y cualquier evento que agregues a futuro
#     ya tiene interpretación automática con solo asignarle categoría).
#  3) Nueva pestaña "🌍 País vs País": compara todo lo cargado de dos
#     países, categoría por categoría, y dice cuál viene mostrando
#     datos económicos más fuertes.
#  4) POLARIDAD ECONÓMICA (criterio de analista, corrige un sesgo real
#     del cálculo anterior): antes, "real > previsto" se marcaba SIEMPRE
#     como "buen dato", lo cual es incorrecto para media tabla de
#     eventos. Un desempleo, unas peticiones de subsidio, una inflación
#     o una tasa de interés que salen MÁS ALTAS de lo esperado son
#     malas noticias económicas, no buenas. Cada evento ahora tiene un
#     campo "polaridad":
#       - "directa"  → un dato más alto de lo esperado es positivo
#                       (PBI, PMI, ventas minoristas, empleo creado...).
#       - "inversa"  → un dato más alto de lo esperado es negativo
#                       (desempleo, inflación, tasas, costos laborales,
#                       rendimiento de subastas de deuda...).
#       - "neutral"  → evento cualitativo sin una lectura clara de
#                       "bueno/malo" (comparecencias, actas, Jackson
#                       Hole, posicionamiento CFTC, informes sin cifra
#                       comparable).
#     _calcular_analisis() usa este campo para no confundir "el número
#     fue más alto" con "es un buen dato". El texto de comparación
#     (vs_previsto / vs_anterior) queda puramente factual (📈/📉), y la
#     lectura de "bueno/malo" (impacto_mercado) es la que se ajusta
#     según la polaridad de cada evento.
#  5) NUEVO: pestaña "📦 Carga Masiva" — permite subir muchos eventos
#     de una sola vez desde un Excel/CSV, con plantilla descargable
#     (incluye hojas de referencia con los países y eventos válidos),
#     validación fila por fila antes de tocar la base, y un insert
#     único a Supabase en lugar de uno por fila.
#  6) FIX carga de datos: _obtener_registros ahora pagina con .range()
#     en vez de un .limit() fijo, así trae SIEMPRE el total real de
#     registros sin importar cuántos haya (antes Historial se cortaba
#     en 100 aunque hubiera más). Además admite filtrar por rango de
#     fechas directo en la query de Supabase (columna 'fecha'), para
#     no traer de más cuando la tabla crezca mucho — usado en la
#     pestaña de Historial.
#  7) NUEVO: edición y borrado de eventos ya cargados, directamente
#     desde "Historial" (solo admin) — por si se cargó un país, evento
#     o valor equivocado. Editar recalcula análisis + interpretación
#     macro con los valores nuevos antes de guardar.
#  8) NUEVO: interpretación "de analista senior" mucho más completa en
#     "Perfil de País" y "País vs País" — gráficos (barras por
#     categoría, radar de activos) + un párrafo narrativo generado con
#     lenguaje de research macro (no solo "sesgo positivo/negativo"),
#     que menciona el dato más relevante, la categoría más fuerte/débil
#     y la implicancia para cada activo.
#  9) NUEVO (esta versión): panorama económico graficado (barras por
#     categoría visibles apenas se elige el país), gráficos de
#     evolución mensual (general y por categoría, incluyendo la
#     comparación entre dos países), e informe de analista mucho más
#     completo: agrega volatilidad de las sorpresas económicas y
#     racha de meses consecutivos mejorando/empeorando, además de lo
#     ya existente (categoría más fuerte/débil, dato más relevante,
#     impacto en la moneda, evolución mes a mes y outlook de tasas).
# ==============================================================

import io
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, datetime

# ⚠️ Cambiá esto por tu email real (el mismo con el que iniciás sesión
# en la app vía Supabase Auth). Solo esa cuenta ve el formulario de
# registrar eventos y de publicar/borrar noticias. La protección real
# (a prueba de gente que mire el código) está en las políticas RLS de
# Supabase — ver el archivo calendario_schema.sql. Tiene que coincidir
# EXACTAMENTE con el email usado en las políticas de ese archivo.
ADMIN_EMAIL = "brainferreyra@gmail.com"

TABLA_REGISTRO = "calendario_registro"
TABLA_NOTICIAS = "calendario_noticias"


# ==============================================================
#  DATOS ESTÁTICOS (idénticos a los que tenías en Apps Script)
# ==============================================================

PAISES = [
    "Alemania", "Arabia Saudita", "Argentina", "Australia", "Austria", "Bélgica",
    "Brasil", "Canadá", "Chile", "China", "Colombia", "Corea del Sur", "Chequia",
    "Dinamarca", "Egipto", "Emiratos Árabes", "España", "Estados Unidos", "Europa",
    "Filipinas", "Francia", "Grecia", "Hong Kong", "Hungría", "India", "Indonesia",
    "Irlanda", "Israel", "Italia", "Japón", "Malasia", "México", "Nigeria",
    "Noruega", "Nueva Zelanda", "Países Bajos", "Perú", "Polonia", "Portugal",
    "Reino Unido", "Rusia", "Singapur", "Sudáfrica", "Suecia", "Suiza",
    "Tailandia", "Turquía", "Vietnam",
]

EVENTOS = {
    "IPC (inflación general)":               {"categoria": "Inflación",            "unidad": "%",         "impacto": "Alto",     "polaridad": "inversa"},
    "IPC núcleo (Core CPI)":                  {"categoria": "Inflación",            "unidad": "%",         "impacto": "Alto",     "polaridad": "inversa"},
    "PPI (precios al productor)":             {"categoria": "Inflación",            "unidad": "%",         "impacto": "Medio",    "polaridad": "inversa"},
    "PCE / PCE núcleo (EE. UU.)":             {"categoria": "Inflación",            "unidad": "%",         "impacto": "Muy Alto", "polaridad": "inversa"},
    "Decisión de tasas de interés (banco central)": {"categoria": "Política Monetaria", "unidad": "%",    "impacto": "Muy Alto", "polaridad": "inversa"},
    "Nóminas no agrícolas (NFP, EE. UU.)":    {"categoria": "Empleo",               "unidad": "K",         "impacto": "Muy Alto", "polaridad": "directa"},
    "Tasa de desempleo":                      {"categoria": "Empleo",               "unidad": "%",         "impacto": "Alto",     "polaridad": "inversa"},
    "PMI manufacturero":                      {"categoria": "Actividad Económica",  "unidad": "Pts",       "impacto": "Alto",     "polaridad": "directa"},
    "Ventas minoristas (headline)":           {"categoria": "Consumo",              "unidad": "%",         "impacto": "Alto",     "polaridad": "directa"},
    "Inventarios de petróleo crudo (EIA)":    {"categoria": "Energía",              "unidad": "M Barriles","impacto": "Medio",    "polaridad": "directa"},
    "ADP empleo privado":                     {"categoria": "Empleo",               "unidad": "K",         "impacto": "Alto",     "polaridad": "directa"},
    "Peticiones iniciales de desempleo":      {"categoria": "Empleo",               "unidad": "K",         "impacto": "Alto",     "polaridad": "inversa"},
    "JOLTS ofertas laborales":                {"categoria": "Empleo",               "unidad": "M",         "impacto": "Alto",     "polaridad": "directa"},
    "Ingresos promedio por hora":             {"categoria": "Empleo",               "unidad": "%",         "impacto": "Muy Alto", "polaridad": "inversa"},
    "PMI servicios":                          {"categoria": "Actividad Económica",  "unidad": "Pts",       "impacto": "Alto",     "polaridad": "directa"},
    "PMI compuesto":                          {"categoria": "Actividad Económica",  "unidad": "Pts",       "impacto": "Alto",     "polaridad": "directa"},
    "ISM manufacturero":                      {"categoria": "Actividad Económica",  "unidad": "Pts",       "impacto": "Muy Alto", "polaridad": "directa"},
    "ISM servicios":                          {"categoria": "Actividad Económica",  "unidad": "Pts",       "impacto": "Muy Alto", "polaridad": "directa"},
    "PIB trimestral":                         {"categoria": "Crecimiento",          "unidad": "%",         "impacto": "Muy Alto", "polaridad": "directa"},
    "Pedidos de bienes duraderos":            {"categoria": "Industria",            "unidad": "%",         "impacto": "Alto",     "polaridad": "directa"},
    "Producción industrial":                  {"categoria": "Industria",            "unidad": "%",         "impacto": "Medio",    "polaridad": "directa"},
    "Confianza del consumidor":               {"categoria": "Consumo",              "unidad": "Pts",       "impacto": "Alto",     "polaridad": "directa"},
    "Confianza Universidad Michigan":         {"categoria": "Consumo",              "unidad": "Pts",       "impacto": "Alto",     "polaridad": "directa"},
    "Ventas de viviendas nuevas":             {"categoria": "Vivienda",             "unidad": "K",         "impacto": "Medio",    "polaridad": "directa"},
    "Ventas de viviendas existentes":         {"categoria": "Vivienda",             "unidad": "M",         "impacto": "Medio",    "polaridad": "directa"},
    "Permisos de construcción":               {"categoria": "Vivienda",             "unidad": "K",         "impacto": "Medio",    "polaridad": "directa"},
    "Inicios de viviendas":                   {"categoria": "Vivienda",             "unidad": "K",         "impacto": "Medio",    "polaridad": "directa"},
    "FOMC Minutes":                           {"categoria": "Política Monetaria",   "unidad": "",          "impacto": "Muy Alto", "polaridad": "neutral"},
    "Conferencia de prensa de la Fed":        {"categoria": "Política Monetaria",   "unidad": "",          "impacto": "Muy Alto", "polaridad": "neutral"},
    "Dot Plot de la Fed":                     {"categoria": "Política Monetaria",   "unidad": "",          "impacto": "Muy Alto", "polaridad": "neutral"},
}

# ==============================================================
#  EVENTOS ADICIONALES — cobertura ampliada a partir de todos los
#  tipos de dato que aparecen en el calendario económico real
#  (PMIs de distintos países, comercio exterior, vivienda, energía,
#  subastas de deuda, comparecencias, posicionamiento CFTC, etc.)
# ==============================================================
EVENTOS_EXTENDIDOS = {
    # ---- Comercio Exterior ----
    "Balanza comercial":                              {"categoria": "Comercio Exterior", "unidad": "B", "impacto": "Alto",  "polaridad": "directa"},
    "Exportaciones (Anual)":                          {"categoria": "Comercio Exterior", "unidad": "%", "impacto": "Medio", "polaridad": "directa"},
    "Importaciones (Anual)":                          {"categoria": "Comercio Exterior", "unidad": "%", "impacto": "Medio", "polaridad": "directa"},
    "Balanza comercial de bienes":                    {"categoria": "Comercio Exterior", "unidad": "B", "impacto": "Medio", "polaridad": "directa"},
    "Balanza comercial no comunitaria":               {"categoria": "Comercio Exterior", "unidad": "B", "impacto": "Bajo",  "polaridad": "directa"},
    "Cuenta corriente":                               {"categoria": "Comercio Exterior", "unidad": "B", "impacto": "Medio", "polaridad": "directa"},
    "Índice de precios de exportación":               {"categoria": "Comercio Exterior", "unidad": "%", "impacto": "Bajo",  "polaridad": "directa"},
    "Índice de Precios de Importación":               {"categoria": "Comercio Exterior", "unidad": "%", "impacto": "Bajo",  "polaridad": "inversa"},
    "Inversión en activos extranjeros":               {"categoria": "Comercio Exterior", "unidad": "B", "impacto": "Bajo",  "polaridad": "directa"},
    "Flujos de capital en productos a largo plazo":   {"categoria": "Comercio Exterior", "unidad": "B", "impacto": "Bajo",  "polaridad": "directa"},

    # ---- Industria ----
    "Gasto en construcción":                          {"categoria": "Industria", "unidad": "%", "impacto": "Medio", "polaridad": "directa"},
    "Pedidos de fábrica":                              {"categoria": "Industria", "unidad": "%", "impacto": "Medio", "polaridad": "directa"},
    "Producción manufacturera":                       {"categoria": "Industria", "unidad": "%", "impacto": "Medio", "polaridad": "directa"},
    "Inventarios de negocios":                        {"categoria": "Industria", "unidad": "%", "impacto": "Bajo",  "polaridad": "neutral"},
    "Inventarios de los minoristas exc. automóviles": {"categoria": "Industria", "unidad": "%", "impacto": "Bajo",  "polaridad": "neutral"},
    "Obras de construcción realizadas":               {"categoria": "Industria", "unidad": "%", "impacto": "Bajo",  "polaridad": "directa"},
    "Índice de Producción Industrial (China)":        {"categoria": "Industria", "unidad": "%", "impacto": "Medio", "polaridad": "directa"},

    # ---- Empleo ----
    "Costes laborales unitarios":                     {"categoria": "Empleo", "unidad": "%", "impacto": "Medio", "polaridad": "inversa"},
    "Productividad no agrícola":                      {"categoria": "Empleo", "unidad": "%", "impacto": "Medio", "polaridad": "directa"},
    "Renovaciones de los subsidios por desempleo":    {"categoria": "Empleo", "unidad": "K", "impacto": "Medio", "polaridad": "inversa"},
    "Nóminas privadas no agrícolas":                  {"categoria": "Empleo", "unidad": "K", "impacto": "Alto",  "polaridad": "directa"},
    "Tasa de participación laboral":                  {"categoria": "Empleo", "unidad": "%", "impacto": "Bajo",  "polaridad": "directa"},
    "Tasa de desempleo U6":                           {"categoria": "Empleo", "unidad": "%", "impacto": "Medio", "polaridad": "inversa"},
    "Evolución del desempleo (Claimant Count)":       {"categoria": "Empleo", "unidad": "K", "impacto": "Alto",  "polaridad": "inversa"},
    "Ingresos medios de los trabajadores (con bonus)":{"categoria": "Empleo", "unidad": "%", "impacto": "Alto",  "polaridad": "inversa"},
    "Productividad laboral":                          {"categoria": "Empleo", "unidad": "%", "impacto": "Bajo",  "polaridad": "directa"},
    "Índice de costes salariales":                    {"categoria": "Empleo", "unidad": "%", "impacto": "Medio", "polaridad": "inversa"},
    "Tasa de desempleo de China":                     {"categoria": "Empleo", "unidad": "%", "impacto": "Medio", "polaridad": "inversa"},
    "Cambio del desempleo en Alemania":               {"categoria": "Empleo", "unidad": "K", "impacto": "Medio", "polaridad": "inversa"},
    "Evolución del número de empleos a tiempo completo": {"categoria": "Empleo", "unidad": "K", "impacto": "Medio", "polaridad": "directa"},
    "Cambio del empleo":                              {"categoria": "Empleo", "unidad": "K", "impacto": "Alto",  "polaridad": "directa"},
    "Variación semanal del empleo según ADP":         {"categoria": "Empleo", "unidad": "K", "impacto": "Medio", "polaridad": "directa"},
    "Referencia salarial (no desestacionalizada)":    {"categoria": "Empleo", "unidad": "K", "impacto": "Bajo",  "polaridad": "neutral"},

    # ---- Actividad Económica (PMIs regionales/sectoriales) ----
    "PMI de la construcción":                         {"categoria": "Actividad Económica", "unidad": "Pts", "impacto": "Medio", "polaridad": "directa"},
    "PMI de Ivey":                                    {"categoria": "Actividad Económica", "unidad": "Pts", "impacto": "Medio", "polaridad": "directa"},
    "Índice manufacturero Empire State":              {"categoria": "Actividad Económica", "unidad": "Pts", "impacto": "Medio", "polaridad": "directa"},
    "Índice manufacturero de la Fed de Filadelfia":   {"categoria": "Actividad Económica", "unidad": "Pts", "impacto": "Medio", "polaridad": "directa"},
    "Informe de empleo de la Fed de Filadelfia":      {"categoria": "Actividad Económica", "unidad": "Pts", "impacto": "Bajo",  "polaridad": "directa"},
    "PMI de Chicago":                                 {"categoria": "Actividad Económica", "unidad": "Pts", "impacto": "Medio", "polaridad": "directa"},

    # ---- Sentimiento Empresarial ----
    "Índice NAB de confianza empresarial":            {"categoria": "Sentimiento Empresarial", "unidad": "Pts", "impacto": "Medio", "polaridad": "directa"},
    "Índice ZEW de confianza inversora":              {"categoria": "Sentimiento Empresarial", "unidad": "Pts", "impacto": "Alto",  "polaridad": "directa"},
    "Índice Ifo de confianza empresarial":            {"categoria": "Sentimiento Empresarial", "unidad": "Pts", "impacto": "Alto",  "polaridad": "directa"},
    "Indicadores adelantados del KOF":                {"categoria": "Sentimiento Empresarial", "unidad": "Pts", "impacto": "Bajo",  "polaridad": "directa"},

    # ---- Consumo ----
    "Índice Gfk de clima de consumo":                 {"categoria": "Consumo", "unidad": "Pts", "impacto": "Medio", "polaridad": "directa"},
    "Confianza del consumidor de la SECO":            {"categoria": "Consumo", "unidad": "Pts", "impacto": "Medio", "polaridad": "directa"},
    "Ventas mayoristas":                              {"categoria": "Consumo", "unidad": "%", "impacto": "Medio", "polaridad": "directa"},
    "Expectativas del consumidor de la Universidad de Michigan": {"categoria": "Consumo", "unidad": "Pts", "impacto": "Medio", "polaridad": "directa"},
    "Gasto personal":                                 {"categoria": "Consumo", "unidad": "%", "impacto": "Alto", "polaridad": "directa"},
    "Ventas minoristas subyacentes":                  {"categoria": "Consumo", "unidad": "%", "impacto": "Alto", "polaridad": "directa"},
    "Previsiones de ventas de la industria minorista":{"categoria": "Consumo", "unidad": "%", "impacto": "Bajo", "polaridad": "directa"},

    # ---- Vivienda ----
    "Índice Halifax de precios de la vivienda":       {"categoria": "Vivienda", "unidad": "%", "impacto": "Medio", "polaridad": "directa"},
    "Hipotecas sobre viviendas":                      {"categoria": "Vivienda", "unidad": "%", "impacto": "Bajo",  "polaridad": "directa"},
    "Venta de viviendas pendientes":                  {"categoria": "Vivienda", "unidad": "%", "impacto": "Medio", "polaridad": "directa"},
    "Precios de Vivienda S&P/Case-Shiller":           {"categoria": "Vivienda", "unidad": "%", "impacto": "Medio", "polaridad": "directa"},
    "Tipo hipotecario":                               {"categoria": "Vivienda", "unidad": "%", "impacto": "Bajo",  "polaridad": "inversa"},
    "Índice de precios de viviendas nuevas":          {"categoria": "Vivienda", "unidad": "%", "impacto": "Bajo",  "polaridad": "directa"},

    # ---- Política Monetaria / Crédito / Fiscal ----
    "Balance general de la Fed":                      {"categoria": "Política Monetaria", "unidad": "B", "impacto": "Medio", "polaridad": "directa"},
    "Nuevos préstamos (China)":                       {"categoria": "Crédito", "unidad": "B", "impacto": "Alto", "polaridad": "directa"},
    "Tasa de préstamo preferencial del PBoC":         {"categoria": "Política Monetaria", "unidad": "%", "impacto": "Alto", "polaridad": "inversa"},
    "Balance presupuestario federal":                 {"categoria": "Política Fiscal", "unidad": "B", "impacto": "Medio", "polaridad": "directa"},
    "Actas de la reunión de política monetaria (Banco Central)": {"categoria": "Política Monetaria", "unidad": "", "impacto": "Alto", "polaridad": "neutral"},

    # ---- Inflación (adicionales) ----
    "Expectativas de inflación":                      {"categoria": "Inflación", "unidad": "%", "impacto": "Medio", "polaridad": "inversa"},
    "Expectativas de inflación de la Universidad de Michigan": {"categoria": "Inflación", "unidad": "%", "impacto": "Alto", "polaridad": "inversa"},
    "Previsiones de inflación a 5 años (Universidad de Michigan)": {"categoria": "Inflación", "unidad": "%", "impacto": "Medio", "polaridad": "inversa"},
    "IPC subyacente de Tokio":                        {"categoria": "Inflación", "unidad": "%", "impacto": "Medio", "polaridad": "inversa"},
    "Índice de precios de bienes y servicios del PIB (Deflactor)": {"categoria": "Inflación", "unidad": "%", "impacto": "Medio", "polaridad": "inversa"},

    # ---- Crecimiento (adicionales) ----
    "PIB mensual":                                    {"categoria": "Crecimiento", "unidad": "%", "impacto": "Alto", "polaridad": "directa"},
    "PIB anualizado (Trimestral)":                    {"categoria": "Crecimiento", "unidad": "%", "impacto": "Alto", "polaridad": "directa"},
    "Inversión empresarial":                          {"categoria": "Crecimiento", "unidad": "%", "impacto": "Medio", "polaridad": "directa"},
    "Gasto en capital fijo (China)":                  {"categoria": "Crecimiento", "unidad": "%", "impacto": "Medio", "polaridad": "directa"},
    "Nuevas inversiones privadas en bienes de capital": {"categoria": "Crecimiento", "unidad": "%", "impacto": "Medio", "polaridad": "directa"},
    "Índice principal de EE.UU. (Leading Index)":     {"categoria": "Crecimiento", "unidad": "%", "impacto": "Medio", "polaridad": "directa"},
    "Resultado bruto de explotación de las empresas": {"categoria": "Crecimiento", "unidad": "%", "impacto": "Bajo", "polaridad": "directa"},

    # ---- Energía ----
    "Reservas semanales de crudo del API":            {"categoria": "Energía", "unidad": "M Barriles", "impacto": "Medio", "polaridad": "directa"},
    "Número de plataformas petrolíferas (Baker Hughes)": {"categoria": "Energía", "unidad": "u", "impacto": "Bajo", "polaridad": "directa"},
    "Informe mensual de la AIE":                      {"categoria": "Energía", "unidad": "", "impacto": "Bajo", "polaridad": "neutral"},
    "Informe mensual de la OPEP":                     {"categoria": "Energía", "unidad": "", "impacto": "Bajo", "polaridad": "neutral"},
    "Previsión energética a corto plazo de la EIA":   {"categoria": "Energía", "unidad": "", "impacto": "Bajo", "polaridad": "neutral"},

    # ---- Agricultura ----
    "Informe WASDE":                                  {"categoria": "Agricultura", "unidad": "", "impacto": "Bajo", "polaridad": "neutral"},

    # ---- Deuda pública ----
    "Subasta de deuda pública":                       {"categoria": "Deuda Pública", "unidad": "%", "impacto": "Medio", "polaridad": "inversa"},

    # ---- Posicionamiento especulativo (CFTC) ----
    "Posiciones netas especulativas (CFTC)":          {"categoria": "Posicionamiento Especulativo", "unidad": "K", "impacto": "Bajo", "polaridad": "neutral"},

    # ---- Comentarios de funcionarios / eventos especiales ----
    "Comparecencia de funcionario de banco central":  {"categoria": "Comentarios de Funcionarios", "unidad": "", "impacto": "Medio", "polaridad": "neutral"},
    "Rueda de prensa de la NBS":                       {"categoria": "Comentarios de Funcionarios", "unidad": "", "impacto": "Medio", "polaridad": "neutral"},
    "Declaraciones de Trump, presidente de EE.UU.":   {"categoria": "Comentarios Políticos", "unidad": "", "impacto": "Alto", "polaridad": "neutral"},
    "Simposio de Jackson Hole":                       {"categoria": "Evento Especial", "unidad": "", "impacto": "Alto", "polaridad": "neutral"},
}

EVENTOS.update(EVENTOS_EXTENDIDOS)

# Diccionario de interpretación macro (idéntico al de Apps Script).
INTERPRETACION_MACRO = {
    "ADP empleo privado": {
        "mayor": {"divisas": "🟢 Dólar fortalecido", "bonos": "🔴 Bonos presionados", "acciones": "🟠 Riesgo de tasas altas", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor liquidez", "politica": "📈 Mayor presión monetaria", "riesgo": "⚠️ Mercado cauteloso", "lectura": "El empleo privado continúa sólido."},
        "menor": {"divisas": "🔴 Dólar debilitado", "bonos": "🟢 Bonos favorecidos", "acciones": "🟢 Positivo para Nasdaq", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🟢 Risk-on", "lectura": "El empleo privado comienza a desacelerarse."},
    },
    "Actas de la reunión de política monetaria (Banco Central)": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Actas de la reunión de política monetaria (Banco Central)» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Política Monetaria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Actas de la reunión de política monetaria (Banco Central)» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Política Monetaria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Actas de la reunión de política monetaria del BCE": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Actas de la reunión de política monetaria del BCE» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Política Monetaria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Actas de la reunión de política monetaria del BCE» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Política Monetaria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Actas de la reunión de política monetaria del Banco de Japón": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Actas de la reunión de política monetaria del Banco de Japón» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Política Monetaria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Actas de la reunión de política monetaria del Banco de Japón» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Política Monetaria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Actas de la reunión de política monetaria del Banco de la Reserva de Australia": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Actas de la reunión de política monetaria del Banco de la Reserva de Australia» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Política Monetaria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Actas de la reunión de política monetaria del Banco de la Reserva de Australia» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Política Monetaria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Actas de la reunión del FOMC": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Actas de la reunión del FOMC» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Política Monetaria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Actas de la reunión del FOMC» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Política Monetaria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Balance general de la Fed": {
        "mayor": {"divisas": "🔴 Sesgo más expansivo debilita la moneda", "bonos": "🟢 Bonos favorecidos", "acciones": "🟢 Impulso para acciones", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mayor liquidez favorable", "politica": "📉 Sesgo monetario más expansivo", "riesgo": "🟢 Risk-on", "lectura": "«Balance general de la Fed»: el dato de política monetaria resulta más expansivo de lo esperado."},
        "menor": {"divisas": "🟢 Sesgo más restrictivo favorece la moneda", "bonos": "🔴 Presión sobre bonos", "acciones": "🔴 Presión sobre acciones", "oro": "🔴 Oro debilitado en el corto plazo", "crypto": "🔴 Menor liquidez para activos de riesgo", "politica": "📈 Sesgo monetario más restrictivo", "riesgo": "🔴 Risk-off", "lectura": "«Balance general de la Fed»: el dato de política monetaria resulta más restrictivo de lo esperado."},
    },
    "Balance presupuestario federal": {
        "mayor": {"divisas": "🟢 Mejora la percepción fiscal", "bonos": "🟢 Menor emisión relativa favorece bonos", "acciones": "⚪ Impacto mixto", "oro": "🔴 Menor necesidad de cobertura", "crypto": "⚪ Impacto limitado", "politica": "📈 Mejora de las cuentas públicas", "riesgo": "🟢 Menor riesgo fiscal", "lectura": "«Balance presupuestario federal»: el resultado fiscal es mejor (déficit menor al esperado) de lo esperado."},
        "menor": {"divisas": "🔴 Mayor déficit genera cautela sobre la moneda", "bonos": "🔴 Mayor emisión presiona bonos", "acciones": "⚪ Impacto mixto", "oro": "🟢 Cobertura ante riesgo fiscal", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro de las cuentas públicas", "riesgo": "🔴 Riesgo fiscal", "lectura": "«Balance presupuestario federal»: el resultado fiscal es peor (déficit mayor al esperado)."},
    },
    "Balanza comercial": {
        "mayor": {"divisas": "🟢 Moneda favorecida por mejora comercial", "bonos": "⚪ Impacto limitado", "acciones": "🟢 Positivo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📈 Sector externo saludable", "riesgo": "🟢 Levemente positivo", "lectura": "«Balanza comercial»: la balanza comercial mejora respecto de lo esperado."},
        "menor": {"divisas": "🔴 Moneda presionada por deterioro comercial", "bonos": "⚪ Impacto limitado", "acciones": "🔴 Riesgo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro del sector externo", "riesgo": "🔴 Levemente negativo", "lectura": "«Balanza comercial»: la balanza comercial se deteriora más de lo esperado."},
    },
    "Balanza comercial (Anual)": {
        "mayor": {"divisas": "🟢 Moneda favorecida por mejora comercial", "bonos": "⚪ Impacto limitado", "acciones": "🟢 Positivo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📈 Sector externo saludable", "riesgo": "🟢 Levemente positivo", "lectura": "«Balanza comercial (Anual)»: la balanza comercial mejora respecto de lo esperado."},
        "menor": {"divisas": "🔴 Moneda presionada por deterioro comercial", "bonos": "⚪ Impacto limitado", "acciones": "🔴 Riesgo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro del sector externo", "riesgo": "🔴 Levemente negativo", "lectura": "«Balanza comercial (Anual)»: la balanza comercial se deteriora más de lo esperado."},
    },
    "Balanza comercial (Mensual)": {
        "mayor": {"divisas": "🟢 Moneda favorecida por mejora comercial", "bonos": "⚪ Impacto limitado", "acciones": "🟢 Positivo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📈 Sector externo saludable", "riesgo": "🟢 Levemente positivo", "lectura": "«Balanza comercial (Mensual)»: la balanza comercial mejora respecto de lo esperado."},
        "menor": {"divisas": "🔴 Moneda presionada por deterioro comercial", "bonos": "⚪ Impacto limitado", "acciones": "🔴 Riesgo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro del sector externo", "riesgo": "🔴 Levemente negativo", "lectura": "«Balanza comercial (Mensual)»: la balanza comercial se deteriora más de lo esperado."},
    },
    "Balanza comercial (USD)": {
        "mayor": {"divisas": "🟢 Moneda favorecida por mejora comercial", "bonos": "⚪ Impacto limitado", "acciones": "🟢 Positivo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📈 Sector externo saludable", "riesgo": "🟢 Levemente positivo", "lectura": "«Balanza comercial (USD)»: la balanza comercial mejora respecto de lo esperado."},
        "menor": {"divisas": "🔴 Moneda presionada por deterioro comercial", "bonos": "⚪ Impacto limitado", "acciones": "🔴 Riesgo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro del sector externo", "riesgo": "🔴 Levemente negativo", "lectura": "«Balanza comercial (USD)»: la balanza comercial se deteriora más de lo esperado."},
    },
    "Balanza comercial de Alemania": {
        "mayor": {"divisas": "🟢 Moneda favorecida por mejora comercial", "bonos": "⚪ Impacto limitado", "acciones": "🟢 Positivo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📈 Sector externo saludable", "riesgo": "🟢 Levemente positivo", "lectura": "«Balanza comercial de Alemania»: la balanza comercial mejora respecto de lo esperado."},
        "menor": {"divisas": "🔴 Moneda presionada por deterioro comercial", "bonos": "⚪ Impacto limitado", "acciones": "🔴 Riesgo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro del sector externo", "riesgo": "🔴 Levemente negativo", "lectura": "«Balanza comercial de Alemania»: la balanza comercial se deteriora más de lo esperado."},
    },
    "Balanza comercial de España": {
        "mayor": {"divisas": "🟢 Moneda favorecida por mejora comercial", "bonos": "⚪ Impacto limitado", "acciones": "🟢 Positivo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📈 Sector externo saludable", "riesgo": "🟢 Levemente positivo", "lectura": "«Balanza comercial de España»: la balanza comercial mejora respecto de lo esperado."},
        "menor": {"divisas": "🔴 Moneda presionada por deterioro comercial", "bonos": "⚪ Impacto limitado", "acciones": "🔴 Riesgo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro del sector externo", "riesgo": "🔴 Levemente negativo", "lectura": "«Balanza comercial de España»: la balanza comercial se deteriora más de lo esperado."},
    },
    "Balanza comercial de bienes": {
        "mayor": {"divisas": "🟢 Moneda favorecida por mejora comercial", "bonos": "⚪ Impacto limitado", "acciones": "🟢 Positivo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📈 Sector externo saludable", "riesgo": "🟢 Levemente positivo", "lectura": "«Balanza comercial de bienes»: la balanza comercial mejora respecto de lo esperado."},
        "menor": {"divisas": "🔴 Moneda presionada por deterioro comercial", "bonos": "⚪ Impacto limitado", "acciones": "🔴 Riesgo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro del sector externo", "riesgo": "🔴 Levemente negativo", "lectura": "«Balanza comercial de bienes»: la balanza comercial se deteriora más de lo esperado."},
    },
    "Balanza comercial de la zona euro": {
        "mayor": {"divisas": "🟢 Moneda favorecida por mejora comercial", "bonos": "⚪ Impacto limitado", "acciones": "🟢 Positivo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📈 Sector externo saludable", "riesgo": "🟢 Levemente positivo", "lectura": "«Balanza comercial de la zona euro»: la balanza comercial mejora respecto de lo esperado."},
        "menor": {"divisas": "🔴 Moneda presionada por deterioro comercial", "bonos": "⚪ Impacto limitado", "acciones": "🔴 Riesgo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro del sector externo", "riesgo": "🔴 Levemente negativo", "lectura": "«Balanza comercial de la zona euro»: la balanza comercial se deteriora más de lo esperado."},
    },
    "Balanza comercial desestacionalizada": {
        "mayor": {"divisas": "🟢 Moneda favorecida por mejora comercial", "bonos": "⚪ Impacto limitado", "acciones": "🟢 Positivo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📈 Sector externo saludable", "riesgo": "🟢 Levemente positivo", "lectura": "«Balanza comercial desestacionalizada»: la balanza comercial mejora respecto de lo esperado."},
        "menor": {"divisas": "🔴 Moneda presionada por deterioro comercial", "bonos": "⚪ Impacto limitado", "acciones": "🔴 Riesgo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro del sector externo", "riesgo": "🔴 Levemente negativo", "lectura": "«Balanza comercial desestacionalizada»: la balanza comercial se deteriora más de lo esperado."},
    },
    "Balanza comercial no comunitaria": {
        "mayor": {"divisas": "🟢 Moneda favorecida por mejora comercial", "bonos": "⚪ Impacto limitado", "acciones": "🟢 Positivo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📈 Sector externo saludable", "riesgo": "🟢 Levemente positivo", "lectura": "«Balanza comercial no comunitaria»: la balanza comercial mejora respecto de lo esperado."},
        "menor": {"divisas": "🔴 Moneda presionada por deterioro comercial", "bonos": "⚪ Impacto limitado", "acciones": "🔴 Riesgo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro del sector externo", "riesgo": "🔴 Levemente negativo", "lectura": "«Balanza comercial no comunitaria»: la balanza comercial se deteriora más de lo esperado."},
    },
    "Balanza por cuenta corriente desestacionalizada": {
        "mayor": {"divisas": "🟢 Moneda favorecida por mejora comercial", "bonos": "⚪ Impacto limitado", "acciones": "🟢 Positivo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📈 Sector externo saludable", "riesgo": "🟢 Levemente positivo", "lectura": "«Balanza por cuenta corriente desestacionalizada»: la balanza comercial mejora respecto de lo esperado."},
        "menor": {"divisas": "🔴 Moneda presionada por deterioro comercial", "bonos": "⚪ Impacto limitado", "acciones": "🔴 Riesgo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro del sector externo", "riesgo": "🔴 Levemente negativo", "lectura": "«Balanza por cuenta corriente desestacionalizada»: la balanza comercial se deteriora más de lo esperado."},
    },
    "Boletín Económico del BCE": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Boletín Económico del BCE» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios de Funcionarios; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Boletín Económico del BCE» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios de Funcionarios; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Cambio del desempleo en Alemania": {
        "mayor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Cambio del desempleo en Alemania»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
        "menor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Cambio del desempleo en Alemania»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
    },
    "Cambio del empleo": {
        "mayor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Cambio del empleo»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Cambio del empleo»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
    },
    "Cambio del empleo no agrícola ADP": {
        "mayor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Cambio del empleo no agrícola ADP»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Cambio del empleo no agrícola ADP»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
    },
    "Comparecencia de Balz, del Buba alemán": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Comparecencia de Balz, del Buba alemán» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios de Funcionarios; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Comparecencia de Balz, del Buba alemán» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios de Funcionarios; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Comparecencia de Bowman, miembro del FOMC": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Comparecencia de Bowman, miembro del FOMC» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios de Funcionarios; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Comparecencia de Bowman, miembro del FOMC» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios de Funcionarios; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Comparecencia de Daly, miembro del FOMC": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Comparecencia de Daly, miembro del FOMC» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios de Funcionarios; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Comparecencia de Daly, miembro del FOMC» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios de Funcionarios; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Comparecencia de Lagarde, presidenta del BCE": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Comparecencia de Lagarde, presidenta del BCE» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios de Funcionarios; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Comparecencia de Lagarde, presidenta del BCE» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios de Funcionarios; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Comparecencia de Lane, del BCE": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Comparecencia de Lane, del BCE» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios de Funcionarios; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Comparecencia de Lane, del BCE» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios de Funcionarios; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Comparecencia de Mann, miembro del CPM del BoE": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Comparecencia de Mann, miembro del CPM del BoE» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios de Funcionarios; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Comparecencia de Mann, miembro del CPM del BoE» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios de Funcionarios; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Comparecencia de Schnabel, del BCE": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Comparecencia de Schnabel, del BCE» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios de Funcionarios; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Comparecencia de Schnabel, del BCE» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios de Funcionarios; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Comparecencia de funcionario de banco central": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Comparecencia de funcionario de banco central» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios de Funcionarios; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Comparecencia de funcionario de banco central» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios de Funcionarios; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Comunicado sobre tipos del RBA": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Comunicado sobre tipos del RBA» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Política Monetaria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Comunicado sobre tipos del RBA» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Política Monetaria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Conferencia de prensa de la Fed": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Conferencia de prensa de la Fed» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Política Monetaria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Conferencia de prensa de la Fed» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Política Monetaria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Confianza Universidad Michigan": {
        "mayor": {"divisas": "🟢 Fortaleza del consumo", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor refugio", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Fortaleza económica", "riesgo": "🟢 Risk-on", "lectura": "La confianza del consumidor mejora."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Mayor cobertura", "crypto": "🔴 Risk-off", "politica": "📉 Riesgo de menor crecimiento", "riesgo": "🔴 Aversión al riesgo", "lectura": "La confianza del consumidor se deteriora."},
    },
    "Confianza del consumidor": {
        "mayor": {"divisas": "🟢 Consumo sólido", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Ambiente favorable", "oro": "🔴 Menor búsqueda defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Fortaleza económica", "riesgo": "🟢 Risk-on", "lectura": "El consumidor mantiene confianza elevada."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Menor apetito por riesgo", "politica": "📉 Riesgo económico", "riesgo": "🔴 Risk-off", "lectura": "La confianza del consumidor cae."},
    },
    "Confianza del consumidor de The Conference Board": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Confianza del consumidor de The Conference Board»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Confianza del consumidor de The Conference Board»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Confianza del consumidor de la SECO": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Confianza del consumidor de la SECO»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Confianza del consumidor de la SECO»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Confianza del consumidor de la Universidad de Michigan": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Confianza del consumidor de la Universidad de Michigan»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Confianza del consumidor de la Universidad de Michigan»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Costes laborales unitarios": {
        "mayor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Costes laborales unitarios»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
        "menor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Costes laborales unitarios»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
    },
    "Costes laborales unitarios (Trimestral)": {
        "mayor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Costes laborales unitarios (Trimestral)»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
        "menor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Costes laborales unitarios (Trimestral)»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
    },
    "Cuenta corriente": {
        "mayor": {"divisas": "🟢 Moneda favorecida por mejora comercial", "bonos": "⚪ Impacto limitado", "acciones": "🟢 Positivo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📈 Sector externo saludable", "riesgo": "🟢 Levemente positivo", "lectura": "«Cuenta corriente»: la balanza comercial mejora respecto de lo esperado."},
        "menor": {"divisas": "🔴 Moneda presionada por deterioro comercial", "bonos": "⚪ Impacto limitado", "acciones": "🔴 Riesgo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro del sector externo", "riesgo": "🔴 Levemente negativo", "lectura": "«Cuenta corriente»: la balanza comercial se deteriora más de lo esperado."},
    },
    "Cuenta corriente (no desestacionalizada)": {
        "mayor": {"divisas": "🟢 Moneda favorecida por mejora comercial", "bonos": "⚪ Impacto limitado", "acciones": "🟢 Positivo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📈 Sector externo saludable", "riesgo": "🟢 Levemente positivo", "lectura": "«Cuenta corriente (no desestacionalizada)»: la balanza comercial mejora respecto de lo esperado."},
        "menor": {"divisas": "🔴 Moneda presionada por deterioro comercial", "bonos": "⚪ Impacto limitado", "acciones": "🔴 Riesgo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro del sector externo", "riesgo": "🔴 Levemente negativo", "lectura": "«Cuenta corriente (no desestacionalizada)»: la balanza comercial se deteriora más de lo esperado."},
    },
    "Decisión de política monetaria del Banco de la Reserva de Australia": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Decisión de política monetaria del Banco de la Reserva de Australia» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Política Monetaria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Decisión de política monetaria del Banco de la Reserva de Australia» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Política Monetaria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Decisión de tasas de interés (banco central)": {
        "mayor": {"divisas": "🟢 Moneda fortalecida", "bonos": "🔴 Caída de bonos", "acciones": "🔴 Presión sobre acciones", "oro": "🔴 Oro debilitado", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Política monetaria restrictiva", "riesgo": "🔴 Risk-off", "lectura": "La suba de tasas endurece las condiciones financieras."},
        "menor": {"divisas": "🔴 Debilidad monetaria", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso positivo para acciones", "oro": "🟢 Oro favorecido", "crypto": "🟢 Liquidez favorable para criptomonedas", "politica": "📉 Política monetaria expansiva", "riesgo": "🟢 Risk-on", "lectura": "La baja de tasas mejora la liquidez."},
    },
    "Decisión de tipos de interés": {
        "mayor": {"divisas": "🟢 Sesgo más restrictivo favorece la moneda", "bonos": "🔴 Presión sobre bonos", "acciones": "🔴 Presión sobre acciones", "oro": "🔴 Oro debilitado en el corto plazo", "crypto": "🔴 Menor liquidez para activos de riesgo", "politica": "📈 Sesgo monetario más restrictivo", "riesgo": "🔴 Risk-off", "lectura": "«Decisión de tipos de interés»: el dato de política monetaria resulta más restrictivo de lo esperado."},
        "menor": {"divisas": "🔴 Sesgo más expansivo debilita la moneda", "bonos": "🟢 Bonos favorecidos", "acciones": "🟢 Impulso para acciones", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mayor liquidez favorable", "politica": "📉 Sesgo monetario más expansivo", "riesgo": "🟢 Risk-on", "lectura": "«Decisión de tipos de interés»: el dato de política monetaria resulta más expansivo de lo esperado."},
    },
    "Declaraciones de Kent, vicegobernador del Banco de la Reserva de Australia": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Declaraciones de Kent, vicegobernador del Banco de la Reserva de Australia» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios de Funcionarios; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Declaraciones de Kent, vicegobernador del Banco de la Reserva de Australia» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios de Funcionarios; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Declaraciones de Trump, presidente de EE.UU.": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Declaraciones de Trump, presidente de EE.UU.» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios Políticos; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Declaraciones de Trump, presidente de EE.UU.» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios Políticos; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Declaraciones de Warsh, del Consejo de Gobierno de la Fed": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Declaraciones de Warsh, del Consejo de Gobierno de la Fed» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios de Funcionarios; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Declaraciones de Warsh, del Consejo de Gobierno de la Fed» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios de Funcionarios; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Demandantes de empleo en Francia": {
        "mayor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Demandantes de empleo en Francia»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
        "menor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Demandantes de empleo en Francia»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
    },
    "Dot Plot de la Fed": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Dot Plot de la Fed» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Política Monetaria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Dot Plot de la Fed» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Política Monetaria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Encuesta JOLTS de ofertas de empleo": {
        "mayor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Encuesta JOLTS de ofertas de empleo»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Encuesta JOLTS de ofertas de empleo»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
    },
    "Evolución del desempleo": {
        "mayor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Evolución del desempleo»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
        "menor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Evolución del desempleo»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
    },
    "Evolución del desempleo (Claimant Count)": {
        "mayor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Evolución del desempleo (Claimant Count)»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
        "menor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Evolución del desempleo (Claimant Count)»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
    },
    "Evolución del número de empleos a tiempo completo": {
        "mayor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Evolución del número de empleos a tiempo completo»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Evolución del número de empleos a tiempo completo»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
    },
    "Evolución trimestral del empleo (Mensual)": {
        "mayor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Evolución trimestral del empleo (Mensual)»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Evolución trimestral del empleo (Mensual)»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
    },
    "Expectativas de inflación": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«Expectativas de inflación»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«Expectativas de inflación»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "Expectativas de inflación (Trimestral)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«Expectativas de inflación (Trimestral)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«Expectativas de inflación (Trimestral)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "Expectativas de inflación de la Universidad de Michigan": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«Expectativas de inflación de la Universidad de Michigan»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«Expectativas de inflación de la Universidad de Michigan»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "Expectativas del consumidor de la Universidad de Michigan": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Expectativas del consumidor de la Universidad de Michigan»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Expectativas del consumidor de la Universidad de Michigan»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Expectativas empresariales de Alemania": {
        "mayor": {"divisas": "🟢 Confianza empresarial en alza", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor refugio", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Expectativas económicas favorables", "riesgo": "🟢 Risk-on", "lectura": "«Expectativas empresariales de Alemania»: la confianza empresarial mejora más de lo esperado."},
        "menor": {"divisas": "🔴 Confianza empresarial deteriorada", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Risk-off", "politica": "📉 Expectativas económicas más débiles", "riesgo": "🔴 Aversión al riesgo", "lectura": "«Expectativas empresariales de Alemania»: la confianza empresarial cae más de lo esperado."},
    },
    "Exportaciones": {
        "mayor": {"divisas": "🟢 Moneda favorecida por mejora comercial", "bonos": "⚪ Impacto limitado", "acciones": "🟢 Positivo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📈 Sector externo saludable", "riesgo": "🟢 Levemente positivo", "lectura": "«Exportaciones»: la balanza comercial mejora respecto de lo esperado."},
        "menor": {"divisas": "🔴 Moneda presionada por deterioro comercial", "bonos": "⚪ Impacto limitado", "acciones": "🔴 Riesgo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro del sector externo", "riesgo": "🔴 Levemente negativo", "lectura": "«Exportaciones»: la balanza comercial se deteriora más de lo esperado."},
    },
    "Exportaciones (Anual)": {
        "mayor": {"divisas": "🟢 Moneda favorecida por mejora comercial", "bonos": "⚪ Impacto limitado", "acciones": "🟢 Positivo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📈 Sector externo saludable", "riesgo": "🟢 Levemente positivo", "lectura": "«Exportaciones (Anual)»: la balanza comercial mejora respecto de lo esperado."},
        "menor": {"divisas": "🔴 Moneda presionada por deterioro comercial", "bonos": "⚪ Impacto limitado", "acciones": "🔴 Riesgo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro del sector externo", "riesgo": "🔴 Levemente negativo", "lectura": "«Exportaciones (Anual)»: la balanza comercial se deteriora más de lo esperado."},
    },
    "FOMC Minutes": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«FOMC Minutes» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Política Monetaria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«FOMC Minutes» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Política Monetaria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Flujos de capital en productos a largo plazo": {
        "mayor": {"divisas": "🟢 Moneda favorecida por mejora comercial", "bonos": "⚪ Impacto limitado", "acciones": "🟢 Positivo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📈 Sector externo saludable", "riesgo": "🟢 Levemente positivo", "lectura": "«Flujos de capital en productos a largo plazo»: la balanza comercial mejora respecto de lo esperado."},
        "menor": {"divisas": "🔴 Moneda presionada por deterioro comercial", "bonos": "⚪ Impacto limitado", "acciones": "🔴 Riesgo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro del sector externo", "riesgo": "🔴 Levemente negativo", "lectura": "«Flujos de capital en productos a largo plazo»: la balanza comercial se deteriora más de lo esperado."},
    },
    "GDPNow de la Fed de Atlanta": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "«GDPNow de la Fed de Atlanta»: el dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "«GDPNow de la Fed de Atlanta»: el dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
    "Gasto de los hogares (Anual)": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Gasto de los hogares (Anual)»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Gasto de los hogares (Anual)»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Gasto de los hogares (Mensual)": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Gasto de los hogares (Mensual)»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Gasto de los hogares (Mensual)»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Gasto del consumidor de Francia (Mensual)": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Gasto del consumidor de Francia (Mensual)»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Gasto del consumidor de Francia (Mensual)»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Gasto en capital fijo (Anual)": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "«Gasto en capital fijo (Anual)»: el dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "«Gasto en capital fijo (Anual)»: el dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
    "Gasto en capital fijo (China)": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "«Gasto en capital fijo (China)»: el dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "«Gasto en capital fijo (China)»: el dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
    "Gasto en construcción": {
        "mayor": {"divisas": "🟢 Fortaleza industrial", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para industriales", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Actividad industrial en expansión", "riesgo": "🟢 Risk-on", "lectura": "«Gasto en construcción»: la actividad industrial sorprende positivamente."},
        "menor": {"divisas": "🔴 Debilidad industrial", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el sector industrial", "oro": "🟢 Mayor cobertura defensiva", "crypto": "🔴 Risk-off", "politica": "📉 Debilidad económica", "riesgo": "🔴 Contracción", "lectura": "«Gasto en construcción»: la actividad industrial decepciona."},
    },
    "Gasto en construcción (Mensual)": {
        "mayor": {"divisas": "🟢 Fortaleza industrial", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para industriales", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Actividad industrial en expansión", "riesgo": "🟢 Risk-on", "lectura": "«Gasto en construcción (Mensual)»: la actividad industrial sorprende positivamente."},
        "menor": {"divisas": "🔴 Debilidad industrial", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el sector industrial", "oro": "🟢 Mayor cobertura defensiva", "crypto": "🔴 Risk-off", "politica": "📉 Debilidad económica", "riesgo": "🔴 Contracción", "lectura": "«Gasto en construcción (Mensual)»: la actividad industrial decepciona."},
    },
    "Gasto personal": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Gasto personal»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Gasto personal»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Gasto personal (Mensual)": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Gasto personal (Mensual)»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Gasto personal (Mensual)»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Gastos de consumo personal - subyacente": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«Gastos de consumo personal - subyacente»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«Gastos de consumo personal - subyacente»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "Hipotecas sobre viviendas": {
        "mayor": {"divisas": "🟢 Mercado inmobiliario fuerte", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Sector inmobiliario firme", "riesgo": "🟢 Risk-on", "lectura": "«Hipotecas sobre viviendas»: el indicador inmobiliario sorprende al alza."},
        "menor": {"divisas": "🔴 Debilidad inmobiliaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para constructoras", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Sector inmobiliario debilitado", "riesgo": "🔴 Risk-off", "lectura": "«Hipotecas sobre viviendas»: el indicador inmobiliario decepciona."},
    },
    "Hipotecas sobre viviendas (Mensual)": {
        "mayor": {"divisas": "🟢 Mercado inmobiliario fuerte", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Sector inmobiliario firme", "riesgo": "🟢 Risk-on", "lectura": "«Hipotecas sobre viviendas (Mensual)»: el indicador inmobiliario sorprende al alza."},
        "menor": {"divisas": "🔴 Debilidad inmobiliaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para constructoras", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Sector inmobiliario debilitado", "riesgo": "🔴 Risk-off", "lectura": "«Hipotecas sobre viviendas (Mensual)»: el indicador inmobiliario decepciona."},
    },
    "IPC (Anual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPC (Anual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPC (Anual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPC (Mensual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPC (Mensual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPC (Mensual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPC (inflación general)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por inflación elevada", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Negativo para acciones e índices", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Política monetaria restrictiva", "riesgo": "🔴 Risk-off", "lectura": "La inflación supera lo esperado y aumenta la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Debilidad monetaria", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para índices", "oro": "🔴 Menor cobertura inflacionaria", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Política monetaria flexible", "riesgo": "🟢 Risk-on", "lectura": "La inflación se desacelera y mejora el entorno financiero."},
    },
    "IPC armonizado de España (Anual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPC armonizado de España (Anual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPC armonizado de España (Anual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPC armonizado de España (Mensual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPC armonizado de España (Mensual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPC armonizado de España (Mensual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPC armonizado de Francia (Mensual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPC armonizado de Francia (Mensual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPC armonizado de Francia (Mensual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPC de Alemania (Anual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPC de Alemania (Anual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPC de Alemania (Anual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPC de Alemania (Mensual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPC de Alemania (Mensual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPC de Alemania (Mensual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPC de España (Anual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPC de España (Anual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPC de España (Anual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPC de España (Mensual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPC de España (Mensual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPC de España (Mensual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPC de Francia (Mensual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPC de Francia (Mensual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPC de Francia (Mensual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPC en la zona euro (Anual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPC en la zona euro (Anual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPC en la zona euro (Anual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPC en la zona euro (Mensual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPC en la zona euro (Mensual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPC en la zona euro (Mensual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPC nacional (Mensual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPC nacional (Mensual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPC nacional (Mensual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPC núcleo (Core CPI)": {
        "mayor": {"divisas": "🟢 Fuerte apreciación monetaria", "bonos": "🔴 Rendimientos al alza", "acciones": "🔴 Muy negativo para tecnológicas", "oro": "🟢 Cobertura inflacionaria", "crypto": "🔴 Debilidad especulativa", "politica": "📈 Banco central agresivo", "riesgo": "🔴 Menor apetito por riesgo", "lectura": "La inflación subyacente sigue elevada."},
        "menor": {"divisas": "🔴 Debilidad monetaria", "bonos": "🟢 Rally de bonos", "acciones": "🟢 Recuperación bursátil", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Recuperación de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🟢 Risk-on", "lectura": "La inflación núcleo se modera."},
    },
    "IPC subyacente (Anual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPC subyacente (Anual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPC subyacente (Anual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPC subyacente (Mensual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPC subyacente (Mensual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPC subyacente (Mensual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPC subyacente de Tokio": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPC subyacente de Tokio»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPC subyacente de Tokio»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPC subyacente de Tokio (Anual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPC subyacente de Tokio (Anual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPC subyacente de Tokio (Anual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPC subyacente del BoJ (Anual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPC subyacente del BoJ (Anual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPC subyacente del BoJ (Anual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPC subyacente en la zona euro (Anual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPC subyacente en la zona euro (Anual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPC subyacente en la zona euro (Anual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPP (Anual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPP (Anual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPP (Anual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPP (Mensual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPP (Mensual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPP (Mensual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPP - entrada (Mensual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPP - entrada (Mensual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPP - entrada (Mensual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPP - entrada (Trimestral)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPP - entrada (Trimestral)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPP - entrada (Trimestral)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPP de Alemania (Mensual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPP de Alemania (Mensual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPP de Alemania (Mensual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPP de España (Anual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPP de España (Anual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPP de España (Anual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "IPP subyacente (Mensual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«IPP subyacente (Mensual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«IPP subyacente (Mensual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "ISM manufacturero": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Ambiente favorable", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo inflacionario", "riesgo": "🟢 Expansión económica", "lectura": "La industria manufacturera acelera crecimiento."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo recesivo", "oro": "🟢 Oro favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible flexibilización", "riesgo": "🔴 Risk-off", "lectura": "La actividad manufacturera se desacelera."},
    },
    "ISM servicios": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Consumo sólido", "oro": "🔴 Menor cobertura", "crypto": "🟢 Risk-on", "politica": "📈 Presión inflacionaria", "riesgo": "🟢 Expansión económica", "lectura": "El sector servicios mantiene fortaleza."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Mayor refugio", "crypto": "🔴 Menor apetito por riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "El sector servicios pierde impulso."},
    },
    "Importaciones": {
        "mayor": {"divisas": "🟢 Moneda favorecida por mejora comercial", "bonos": "⚪ Impacto limitado", "acciones": "🟢 Positivo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📈 Sector externo saludable", "riesgo": "🟢 Levemente positivo", "lectura": "«Importaciones»: la balanza comercial mejora respecto de lo esperado."},
        "menor": {"divisas": "🔴 Moneda presionada por deterioro comercial", "bonos": "⚪ Impacto limitado", "acciones": "🔴 Riesgo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro del sector externo", "riesgo": "🔴 Levemente negativo", "lectura": "«Importaciones»: la balanza comercial se deteriora más de lo esperado."},
    },
    "Importaciones (Anual)": {
        "mayor": {"divisas": "🟢 Moneda favorecida por mejora comercial", "bonos": "⚪ Impacto limitado", "acciones": "🟢 Positivo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📈 Sector externo saludable", "riesgo": "🟢 Levemente positivo", "lectura": "«Importaciones (Anual)»: la balanza comercial mejora respecto de lo esperado."},
        "menor": {"divisas": "🔴 Moneda presionada por deterioro comercial", "bonos": "⚪ Impacto limitado", "acciones": "🔴 Riesgo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro del sector externo", "riesgo": "🔴 Levemente negativo", "lectura": "«Importaciones (Anual)»: la balanza comercial se deteriora más de lo esperado."},
    },
    "Indicadores adelantados del KOF": {
        "mayor": {"divisas": "🟢 Confianza empresarial en alza", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor refugio", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Expectativas económicas favorables", "riesgo": "🟢 Risk-on", "lectura": "«Indicadores adelantados del KOF»: la confianza empresarial mejora más de lo esperado."},
        "menor": {"divisas": "🔴 Confianza empresarial deteriorada", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Risk-off", "politica": "📉 Expectativas económicas más débiles", "riesgo": "🔴 Aversión al riesgo", "lectura": "«Indicadores adelantados del KOF»: la confianza empresarial cae más de lo esperado."},
    },
    "Informe WASDE": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Informe WASDE» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Agricultura; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Informe WASDE» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Agricultura; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Informe WASDE sobre oferta y demanda de productos agrícolas": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Informe WASDE sobre oferta y demanda de productos agrícolas» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Agricultura; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Informe WASDE sobre oferta y demanda de productos agrícolas» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Agricultura; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Informe de empleo de la Fed de Filadelfia": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«Informe de empleo de la Fed de Filadelfia»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«Informe de empleo de la Fed de Filadelfia»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "Informe mensual de la AIE": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Informe mensual de la AIE» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Energía; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Informe mensual de la AIE» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Energía; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Informe mensual de la OPEP": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Informe mensual de la OPEP» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Energía; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Informe mensual de la OPEP» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Energía; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Ingresos medios de los trabajadores (con bonus)": {
        "mayor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Ingresos medios de los trabajadores (con bonus)»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
        "menor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Ingresos medios de los trabajadores (con bonus)»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
    },
    "Ingresos medios de los trabajadores, bonus incluidos": {
        "mayor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Ingresos medios de los trabajadores, bonus incluidos»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
        "menor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Ingresos medios de los trabajadores, bonus incluidos»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
    },
    "Ingresos medios por hora (Mensual)": {
        "mayor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Ingresos medios por hora (Mensual)»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
        "menor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Ingresos medios por hora (Mensual)»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
    },
    "Ingresos medios por hora (interanual) (Anual)": {
        "mayor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Ingresos medios por hora (interanual) (Anual)»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
        "menor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Ingresos medios por hora (interanual) (Anual)»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
    },
    "Ingresos promedio por hora": {
        "mayor": {"divisas": "🟢 Fortaleza del dólar por presión salarial", "bonos": "🔴 Rendimientos en alza", "acciones": "🔴 Negativo para tecnológicas", "oro": "🟢 Cobertura inflacionaria", "crypto": "🔴 Menor liquidez", "politica": "📈 Riesgo de inflación salarial", "riesgo": "🔴 Menor apetito por riesgo", "lectura": "Los salarios aumentan y elevan riesgos inflacionarios."},
        "menor": {"divisas": "🔴 Dólar debilitado", "bonos": "🟢 Bonos favorecidos", "acciones": "🟢 Impulso bursátil", "oro": "🔴 Menor presión inflacionaria", "crypto": "🟢 Risk-on", "politica": "📉 Menor presión salarial", "riesgo": "🟢 Mayor apetito por riesgo", "lectura": "La inflación salarial comienza a moderarse."},
    },
    "Inicios de construcción de viviendas (Mensual)": {
        "mayor": {"divisas": "🟢 Mercado inmobiliario fuerte", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Sector inmobiliario firme", "riesgo": "🟢 Risk-on", "lectura": "«Inicios de construcción de viviendas (Mensual)»: el indicador inmobiliario sorprende al alza."},
        "menor": {"divisas": "🔴 Debilidad inmobiliaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para constructoras", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Sector inmobiliario debilitado", "riesgo": "🔴 Risk-off", "lectura": "«Inicios de construcción de viviendas (Mensual)»: el indicador inmobiliario decepciona."},
    },
    "Inicios de viviendas": {
        "mayor": {"divisas": "🟢 Mercado inmobiliario fuerte", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Sector inmobiliario firme", "riesgo": "🟢 Risk-on", "lectura": "«Inicios de viviendas»: el indicador inmobiliario sorprende al alza."},
        "menor": {"divisas": "🔴 Debilidad inmobiliaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para constructoras", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Sector inmobiliario debilitado", "riesgo": "🔴 Risk-off", "lectura": "«Inicios de viviendas»: el indicador inmobiliario decepciona."},
    },
    "Inventarios de crudo semanales en Cushing de la AIE": {
        "mayor": {"divisas": "🔴 Debilidad de monedas petroleras (mayor oferta)", "bonos": "🟢 Menor presión inflacionaria", "acciones": "🔴 Debilidad del sector energético", "oro": "🔴 Menor temor inflacionario", "crypto": "🟢 Riesgo moderadamente positivo", "politica": "📉 Menor presión inflacionaria por energía", "riesgo": "🟢 Ambiente más estable", "lectura": "«Inventarios de crudo semanales en Cushing de la AIE»: el dato energético sugiere mayor oferta/holgura de lo esperado."},
        "menor": {"divisas": "🟢 Fortaleza de monedas ligadas a commodities", "bonos": "🔴 Riesgo inflacionario", "acciones": "🟢 Energéticas favorecidas", "oro": "🟢 Cobertura inflacionaria", "crypto": "🔴 Riesgo inflacionario", "politica": "📈 Mayor presión inflacionaria por energía", "riesgo": "⚠️ Mayor volatilidad", "lectura": "«Inventarios de crudo semanales en Cushing de la AIE»: el dato energético sugiere mayor ajuste de oferta de lo esperado."},
    },
    "Inventarios de los minoristas exc. automóviles": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Inventarios de los minoristas exc. automóviles» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Industria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Inventarios de los minoristas exc. automóviles» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Industria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Inventarios de negocios": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Inventarios de negocios» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Industria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Inventarios de negocios» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Industria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Inventarios de negocios (Mensual)": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Inventarios de negocios (Mensual)» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Industria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Inventarios de negocios (Mensual)» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Industria; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Inventarios de petróleo crudo (EIA)": {
        "mayor": {"divisas": "🔴 Debilidad de monedas petroleras", "bonos": "🟢 Menor presión inflacionaria", "acciones": "🔴 Debilidad energética", "oro": "🔴 Menor temor inflacionario", "crypto": "🟢 Riesgo moderadamente positivo", "politica": "📉 Menor presión inflacionaria", "riesgo": "🟢 Ambiente más estable", "lectura": "El aumento de inventarios reduce presión sobre el petróleo."},
        "menor": {"divisas": "🟢 Fortaleza de monedas ligadas a commodities", "bonos": "🔴 Riesgo inflacionario", "acciones": "🟢 Energéticas favorecidas", "oro": "🟢 Cobertura inflacionaria", "crypto": "🔴 Riesgo inflacionario", "politica": "📈 Mayor presión inflacionaria", "riesgo": "⚠️ Mayor volatilidad", "lectura": "La caída de inventarios impulsa precios energéticos."},
    },
    "Inventarios de petróleo crudo de la AIE": {
        "mayor": {"divisas": "🔴 Debilidad de monedas petroleras (mayor oferta)", "bonos": "🟢 Menor presión inflacionaria", "acciones": "🔴 Debilidad del sector energético", "oro": "🔴 Menor temor inflacionario", "crypto": "🟢 Riesgo moderadamente positivo", "politica": "📉 Menor presión inflacionaria por energía", "riesgo": "🟢 Ambiente más estable", "lectura": "«Inventarios de petróleo crudo de la AIE»: el dato energético sugiere mayor oferta/holgura de lo esperado."},
        "menor": {"divisas": "🟢 Fortaleza de monedas ligadas a commodities", "bonos": "🔴 Riesgo inflacionario", "acciones": "🟢 Energéticas favorecidas", "oro": "🟢 Cobertura inflacionaria", "crypto": "🔴 Riesgo inflacionario", "politica": "📈 Mayor presión inflacionaria por energía", "riesgo": "⚠️ Mayor volatilidad", "lectura": "«Inventarios de petróleo crudo de la AIE»: el dato energético sugiere mayor ajuste de oferta de lo esperado."},
    },
    "Inversión empresarial": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "«Inversión empresarial»: el dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "«Inversión empresarial»: el dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
    "Inversión empresarial (Trimestral)": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "«Inversión empresarial (Trimestral)»: el dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "«Inversión empresarial (Trimestral)»: el dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
    "Inversión en activos extranjeros": {
        "mayor": {"divisas": "🟢 Moneda favorecida por mejora comercial", "bonos": "⚪ Impacto limitado", "acciones": "🟢 Positivo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📈 Sector externo saludable", "riesgo": "🟢 Levemente positivo", "lectura": "«Inversión en activos extranjeros»: la balanza comercial mejora respecto de lo esperado."},
        "menor": {"divisas": "🔴 Moneda presionada por deterioro comercial", "bonos": "⚪ Impacto limitado", "acciones": "🔴 Riesgo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro del sector externo", "riesgo": "🔴 Levemente negativo", "lectura": "«Inversión en activos extranjeros»: la balanza comercial se deteriora más de lo esperado."},
    },
    "Inversión en bienes de capital (Capex) (Anual)": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "«Inversión en bienes de capital (Capex) (Anual)»: el dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "«Inversión en bienes de capital (Capex) (Anual)»: el dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
    "JOLTS ofertas laborales": {
        "mayor": {"divisas": "🟢 Fortaleza monetaria", "bonos": "🔴 Rendimientos al alza", "acciones": "🔴 Riesgo de tasas altas", "oro": "🔴 Oro debilitado", "crypto": "🔴 Liquidez negativa", "politica": "📈 Mercado laboral sobrecalentado", "riesgo": "⚠️ Mercado sensible", "lectura": "Las vacantes laborales siguen elevadas."},
        "menor": {"divisas": "🔴 Debilidad monetaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🟢 Positivo para acciones", "oro": "🟢 Oro favorecido", "crypto": "🟢 Recuperación cripto", "politica": "📉 Menor presión sobre la Fed", "riesgo": "🟢 Risk-on", "lectura": "El mercado laboral comienza a enfriarse."},
    },
    "Nivel de empleo": {
        "mayor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Nivel de empleo»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Nivel de empleo»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
    },
    "Nuevas construcciones de viviendas": {
        "mayor": {"divisas": "🟢 Mercado inmobiliario fuerte", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Sector inmobiliario firme", "riesgo": "🟢 Risk-on", "lectura": "«Nuevas construcciones de viviendas»: el indicador inmobiliario sorprende al alza."},
        "menor": {"divisas": "🔴 Debilidad inmobiliaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para constructoras", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Sector inmobiliario debilitado", "riesgo": "🔴 Risk-off", "lectura": "«Nuevas construcciones de viviendas»: el indicador inmobiliario decepciona."},
    },
    "Nuevas inversiones privadas en bienes de capital": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "«Nuevas inversiones privadas en bienes de capital»: el dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "«Nuevas inversiones privadas en bienes de capital»: el dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
    "Nuevas inversiones privadas en bienes de capital (Trimestral)": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "«Nuevas inversiones privadas en bienes de capital (Trimestral)»: el dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "«Nuevas inversiones privadas en bienes de capital (Trimestral)»: el dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
    "Nuevas peticiones de subsidio por desempleo": {
        "mayor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Nuevas peticiones de subsidio por desempleo»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
        "menor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Nuevas peticiones de subsidio por desempleo»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
    },
    "Nuevos préstamos": {
        "mayor": {"divisas": "⚪ Impacto mixto", "bonos": "🔴 Riesgo de sobrecalentamiento crediticio", "acciones": "🟢 Mayor liquidez favorece activos de riesgo", "oro": "⚪ Impacto limitado", "crypto": "🟢 Mayor liquidez disponible", "politica": "📈 Fuerte expansión del crédito", "riesgo": "🟢 Risk-on de corto plazo", "lectura": "«Nuevos préstamos»: el crédito se expande más de lo esperado."},
        "menor": {"divisas": "⚪ Impacto mixto", "bonos": "🟢 Menor riesgo de sobrecalentamiento", "acciones": "🔴 Menor liquidez disponible", "oro": "⚪ Impacto limitado", "crypto": "🔴 Menor liquidez disponible", "politica": "📉 Contracción del crédito", "riesgo": "🔴 Menor impulso crediticio", "lectura": "«Nuevos préstamos»: el crédito se expande menos de lo esperado."},
    },
    "Nuevos préstamos (China)": {
        "mayor": {"divisas": "⚪ Impacto mixto", "bonos": "🔴 Riesgo de sobrecalentamiento crediticio", "acciones": "🟢 Mayor liquidez favorece activos de riesgo", "oro": "⚪ Impacto limitado", "crypto": "🟢 Mayor liquidez disponible", "politica": "📈 Fuerte expansión del crédito", "riesgo": "🟢 Risk-on de corto plazo", "lectura": "«Nuevos préstamos (China)»: el crédito se expande más de lo esperado."},
        "menor": {"divisas": "⚪ Impacto mixto", "bonos": "🟢 Menor riesgo de sobrecalentamiento", "acciones": "🔴 Menor liquidez disponible", "oro": "⚪ Impacto limitado", "crypto": "🔴 Menor liquidez disponible", "politica": "📉 Contracción del crédito", "riesgo": "🔴 Menor impulso crediticio", "lectura": "«Nuevos préstamos (China)»: el crédito se expande menos de lo esperado."},
    },
    "Nóminas no agrícolas": {
        "mayor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Nóminas no agrícolas»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Nóminas no agrícolas»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
    },
    "Nóminas no agrícolas (NFP, EE. UU.)": {
        "mayor": {"divisas": "🟢 Dólar fortalecido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de presión sobre índices", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "El mercado laboral continúa extremadamente sólido."},
        "menor": {"divisas": "🔴 Dólar debilitado", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Mejora para tecnológicas", "oro": "🟢 Oro favorecido", "crypto": "🟢 Recuperación de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🟢 Mayor liquidez esperada", "lectura": "El mercado laboral comienza a enfriarse."},
    },
    "Nóminas privadas no agrícolas": {
        "mayor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Nóminas privadas no agrícolas»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Nóminas privadas no agrícolas»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
    },
    "Número de plataformas petrolíferas (Baker Hughes)": {
        "mayor": {"divisas": "🔴 Debilidad de monedas petroleras (mayor oferta)", "bonos": "🟢 Menor presión inflacionaria", "acciones": "🔴 Debilidad del sector energético", "oro": "🔴 Menor temor inflacionario", "crypto": "🟢 Riesgo moderadamente positivo", "politica": "📉 Menor presión inflacionaria por energía", "riesgo": "🟢 Ambiente más estable", "lectura": "«Número de plataformas petrolíferas (Baker Hughes)»: el dato energético sugiere mayor oferta/holgura de lo esperado."},
        "menor": {"divisas": "🟢 Fortaleza de monedas ligadas a commodities", "bonos": "🔴 Riesgo inflacionario", "acciones": "🟢 Energéticas favorecidas", "oro": "🟢 Cobertura inflacionaria", "crypto": "🔴 Riesgo inflacionario", "politica": "📈 Mayor presión inflacionaria por energía", "riesgo": "⚠️ Mayor volatilidad", "lectura": "«Número de plataformas petrolíferas (Baker Hughes)»: el dato energético sugiere mayor ajuste de oferta de lo esperado."},
    },
    "Número de plataformas petrolíferas, Baker Hughes": {
        "mayor": {"divisas": "🔴 Debilidad de monedas petroleras (mayor oferta)", "bonos": "🟢 Menor presión inflacionaria", "acciones": "🔴 Debilidad del sector energético", "oro": "🔴 Menor temor inflacionario", "crypto": "🟢 Riesgo moderadamente positivo", "politica": "📉 Menor presión inflacionaria por energía", "riesgo": "🟢 Ambiente más estable", "lectura": "«Número de plataformas petrolíferas, Baker Hughes»: el dato energético sugiere mayor oferta/holgura de lo esperado."},
        "menor": {"divisas": "🟢 Fortaleza de monedas ligadas a commodities", "bonos": "🔴 Riesgo inflacionario", "acciones": "🟢 Energéticas favorecidas", "oro": "🟢 Cobertura inflacionaria", "crypto": "🔴 Riesgo inflacionario", "politica": "📈 Mayor presión inflacionaria por energía", "riesgo": "⚠️ Mayor volatilidad", "lectura": "«Número de plataformas petrolíferas, Baker Hughes»: el dato energético sugiere mayor ajuste de oferta de lo esperado."},
    },
    "Obras de construcción realizadas": {
        "mayor": {"divisas": "🟢 Fortaleza industrial", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para industriales", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Actividad industrial en expansión", "riesgo": "🟢 Risk-on", "lectura": "«Obras de construcción realizadas»: la actividad industrial sorprende positivamente."},
        "menor": {"divisas": "🔴 Debilidad industrial", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el sector industrial", "oro": "🟢 Mayor cobertura defensiva", "crypto": "🔴 Risk-off", "politica": "📉 Debilidad económica", "riesgo": "🔴 Contracción", "lectura": "«Obras de construcción realizadas»: la actividad industrial decepciona."},
    },
    "Obras de construcción realizadas (Trimestral)": {
        "mayor": {"divisas": "🟢 Fortaleza industrial", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para industriales", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Actividad industrial en expansión", "riesgo": "🟢 Risk-on", "lectura": "«Obras de construcción realizadas (Trimestral)»: la actividad industrial sorprende positivamente."},
        "menor": {"divisas": "🔴 Debilidad industrial", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el sector industrial", "oro": "🟢 Mayor cobertura defensiva", "crypto": "🔴 Risk-off", "politica": "📉 Debilidad económica", "riesgo": "🔴 Contracción", "lectura": "«Obras de construcción realizadas (Trimestral)»: la actividad industrial decepciona."},
    },
    "PCE / PCE núcleo (EE. UU.)": {
        "mayor": {"divisas": "🟢 Dólar fortalecido", "bonos": "🔴 Rendimientos al alza", "acciones": "🔴 Negativo para Wall Street", "oro": "🟢 Oro favorecido", "crypto": "🔴 Debilidad cripto", "politica": "📈 Presión sobre la Reserva Federal", "riesgo": "🔴 Menor apetito por riesgo", "lectura": "El indicador preferido de inflación de la Fed sigue elevado."},
        "menor": {"divisas": "🔴 Dólar debilitado", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso bursátil", "oro": "🔴 Menor refugio", "crypto": "🟢 Recuperación cripto", "politica": "📉 Menor presión monetaria", "riesgo": "🟢 Risk-on", "lectura": "El PCE muestra moderación inflacionaria."},
    },
    "PIB (Anual)": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "«PIB (Anual)»: el dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "«PIB (Anual)»: el dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
    "PIB (Mensual)": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "«PIB (Mensual)»: el dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "«PIB (Mensual)»: el dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
    "PIB (Trimestral)": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "«PIB (Trimestral)»: el dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "«PIB (Trimestral)»: el dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
    "PIB anualizado (Trimestral)": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "«PIB anualizado (Trimestral)»: el dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "«PIB anualizado (Trimestral)»: el dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
    "PIB de Alemania (Anual)": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "«PIB de Alemania (Anual)»: el dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "«PIB de Alemania (Anual)»: el dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
    "PIB de Alemania (Trimestral)": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "«PIB de Alemania (Trimestral)»: el dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "«PIB de Alemania (Trimestral)»: el dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
    "PIB de Francia (Anual)": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "«PIB de Francia (Anual)»: el dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "«PIB de Francia (Anual)»: el dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
    "PIB de Francia (Trimestral)": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "«PIB de Francia (Trimestral)»: el dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "«PIB de Francia (Trimestral)»: el dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
    "PIB en la zona euro (Anual)": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "«PIB en la zona euro (Anual)»: el dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "«PIB en la zona euro (Anual)»: el dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
    "PIB en la zona euro (Trimestral)": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "«PIB en la zona euro (Trimestral)»: el dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "«PIB en la zona euro (Trimestral)»: el dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
    "PIB mensual": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "«PIB mensual»: el dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "«PIB mensual»: el dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
    "PIB mensual a 3M / Evolución a 3M": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "«PIB mensual a 3M / Evolución a 3M»: el dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "«PIB mensual a 3M / Evolución a 3M»: el dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
    "PIB trimestral": {
        "mayor": {"divisas": "🟢 Fortaleza del dólar", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "La economía crece por encima de lo esperado."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "El crecimiento económico se desacelera."},
    },
    "PMI compuesto": {
        "mayor": {"divisas": "🟢 Fortaleza monetaria", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Expansión económica", "oro": "🔴 Menor demanda defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía fuerte", "riesgo": "🟢 Risk-on", "lectura": "La economía acelera crecimiento general."},
        "menor": {"divisas": "🔴 Debilidad monetaria", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo económico", "oro": "🟢 Oro favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible flexibilización", "riesgo": "🔴 Risk-off", "lectura": "La economía muestra señales de desaceleración."},
    },
    "PMI compuesto chino": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI compuesto chino»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI compuesto chino»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI compuesto de S&P Global": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI compuesto de S&P Global»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI compuesto de S&P Global»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI compuesto de S&P Global en la zona euro": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI compuesto de S&P Global en la zona euro»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI compuesto de S&P Global en la zona euro»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI de Chicago": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI de Chicago»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI de Chicago»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI de Ivey": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI de Ivey»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI de Ivey»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI de la construcción": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI de la construcción»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI de la construcción»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI de servicios": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI de servicios»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI de servicios»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI de servicios de Alemania": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI de servicios de Alemania»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI de servicios de Alemania»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI de servicios de Caixin": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI de servicios de Caixin»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI de servicios de Caixin»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI de servicios de España": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI de servicios de España»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI de servicios de España»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI de servicios de Francia": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI de servicios de Francia»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI de servicios de Francia»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI de servicios de Italia": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI de servicios de Italia»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI de servicios de Italia»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI de servicios en la zona euro": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI de servicios en la zona euro»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI de servicios en la zona euro»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI del sector de la construcción": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI del sector de la construcción»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI del sector de la construcción»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI del sector servicios": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI del sector servicios»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI del sector servicios»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI manufacturero": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Posible endurecimiento monetario", "riesgo": "🟢 Expansión económica", "lectura": "La actividad manufacturera muestra expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de riesgo", "politica": "📉 Mayor probabilidad de flexibilización", "riesgo": "🔴 Contracción económica", "lectura": "La actividad manufacturera se debilita."},
    },
    "PMI manufacturero de Alemania": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI manufacturero de Alemania»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI manufacturero de Alemania»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI manufacturero de Caixin (Mensual)": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI manufacturero de Caixin (Mensual)»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI manufacturero de Caixin (Mensual)»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI manufacturero de España": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI manufacturero de España»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI manufacturero de España»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI manufacturero de Francia": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI manufacturero de Francia»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI manufacturero de Francia»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI manufacturero de Italia": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI manufacturero de Italia»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI manufacturero de Italia»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI manufacturero de la zona euro": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI manufacturero de la zona euro»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI manufacturero de la zona euro»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI manufacturero del Business NZ": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI manufacturero del Business NZ»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI manufacturero del Business NZ»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI manufacturero del ISM": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI manufacturero del ISM»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI manufacturero del ISM»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI no manufacturero": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI no manufacturero»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI no manufacturero»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI no manufacturero del ISM": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI no manufacturero del ISM»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI no manufacturero del ISM»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI procure.ch": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«PMI procure.ch»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«PMI procure.ch»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "PMI servicios": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Consumo sólido", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente positivo", "politica": "📈 Riesgo inflacionario", "riesgo": "🟢 Expansión económica", "lectura": "El sector servicios muestra expansión sólida."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Risk-off", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Desaceleración económica", "lectura": "El sector servicios pierde impulso."},
    },
    "PPI (precios al productor)": {
        "mayor": {"divisas": "🟢 Fortaleza monetaria", "bonos": "🔴 Bonos presionados", "acciones": "🔴 Riesgo sobre márgenes empresariales", "oro": "🟢 Cobertura inflacionaria", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Riesgo de endurecimiento monetario", "riesgo": "🔴 Risk-off", "lectura": "Los costos de producción aumentan."},
        "menor": {"divisas": "🔴 Debilidad monetaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🟢 Mejora empresarial", "oro": "🔴 Menor presión inflacionaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🟢 Risk-on", "lectura": "Disminuyen las presiones sobre costos productivos."},
    },
    "Pedidos de bienes duraderos": {
        "mayor": {"divisas": "🟢 Fortaleza industrial", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para industriales", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica fuerte", "riesgo": "🟢 Expansión económica", "lectura": "Aumentan los pedidos industriales de largo plazo."},
        "menor": {"divisas": "🔴 Debilidad industrial", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo económico", "oro": "🟢 Mayor cobertura defensiva", "crypto": "🔴 Risk-off", "politica": "📉 Debilidad económica", "riesgo": "🔴 Menor crecimiento", "lectura": "La demanda industrial pierde fuerza."},
    },
    "Pedidos de bienes duraderos (Mensual)": {
        "mayor": {"divisas": "🟢 Fortaleza industrial", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para industriales", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Actividad industrial en expansión", "riesgo": "🟢 Risk-on", "lectura": "«Pedidos de bienes duraderos (Mensual)»: la actividad industrial sorprende positivamente."},
        "menor": {"divisas": "🔴 Debilidad industrial", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el sector industrial", "oro": "🟢 Mayor cobertura defensiva", "crypto": "🔴 Risk-off", "politica": "📉 Debilidad económica", "riesgo": "🔴 Contracción", "lectura": "«Pedidos de bienes duraderos (Mensual)»: la actividad industrial decepciona."},
    },
    "Pedidos de bienes duraderos (subyacente) (Mensual)": {
        "mayor": {"divisas": "🟢 Fortaleza industrial", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para industriales", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Actividad industrial en expansión", "riesgo": "🟢 Risk-on", "lectura": "«Pedidos de bienes duraderos (subyacente) (Mensual)»: la actividad industrial sorprende positivamente."},
        "menor": {"divisas": "🔴 Debilidad industrial", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el sector industrial", "oro": "🟢 Mayor cobertura defensiva", "crypto": "🔴 Risk-off", "politica": "📉 Debilidad económica", "riesgo": "🔴 Contracción", "lectura": "«Pedidos de bienes duraderos (subyacente) (Mensual)»: la actividad industrial decepciona."},
    },
    "Pedidos de fábrica": {
        "mayor": {"divisas": "🟢 Fortaleza industrial", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para industriales", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Actividad industrial en expansión", "riesgo": "🟢 Risk-on", "lectura": "«Pedidos de fábrica»: la actividad industrial sorprende positivamente."},
        "menor": {"divisas": "🔴 Debilidad industrial", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el sector industrial", "oro": "🟢 Mayor cobertura defensiva", "crypto": "🔴 Risk-off", "politica": "📉 Debilidad económica", "riesgo": "🔴 Contracción", "lectura": "«Pedidos de fábrica»: la actividad industrial decepciona."},
    },
    "Pedidos de fábrica (Mensual)": {
        "mayor": {"divisas": "🟢 Fortaleza industrial", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para industriales", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Actividad industrial en expansión", "riesgo": "🟢 Risk-on", "lectura": "«Pedidos de fábrica (Mensual)»: la actividad industrial sorprende positivamente."},
        "menor": {"divisas": "🔴 Debilidad industrial", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el sector industrial", "oro": "🟢 Mayor cobertura defensiva", "crypto": "🔴 Risk-off", "politica": "📉 Debilidad económica", "riesgo": "🔴 Contracción", "lectura": "«Pedidos de fábrica (Mensual)»: la actividad industrial decepciona."},
    },
    "Pedidos de fábrica de Alemania (Mensual)": {
        "mayor": {"divisas": "🟢 Fortaleza industrial", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para industriales", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Actividad industrial en expansión", "riesgo": "🟢 Risk-on", "lectura": "«Pedidos de fábrica de Alemania (Mensual)»: la actividad industrial sorprende positivamente."},
        "menor": {"divisas": "🔴 Debilidad industrial", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el sector industrial", "oro": "🟢 Mayor cobertura defensiva", "crypto": "🔴 Risk-off", "politica": "📉 Debilidad económica", "riesgo": "🔴 Contracción", "lectura": "«Pedidos de fábrica de Alemania (Mensual)»: la actividad industrial decepciona."},
    },
    "Permisos de construcción": {
        "mayor": {"divisas": "🟢 Mercado inmobiliario fuerte", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Sector inmobiliario firme", "riesgo": "🟢 Risk-on", "lectura": "«Permisos de construcción»: el indicador inmobiliario sorprende al alza."},
        "menor": {"divisas": "🔴 Debilidad inmobiliaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para constructoras", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Sector inmobiliario debilitado", "riesgo": "🔴 Risk-off", "lectura": "«Permisos de construcción»: el indicador inmobiliario decepciona."},
    },
    "Permisos de construcción (Mensual)": {
        "mayor": {"divisas": "🟢 Mercado inmobiliario fuerte", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Sector inmobiliario firme", "riesgo": "🟢 Risk-on", "lectura": "«Permisos de construcción (Mensual)»: el indicador inmobiliario sorprende al alza."},
        "menor": {"divisas": "🔴 Debilidad inmobiliaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para constructoras", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Sector inmobiliario debilitado", "riesgo": "🔴 Risk-off", "lectura": "«Permisos de construcción (Mensual)»: el indicador inmobiliario decepciona."},
    },
    "Peticiones iniciales de desempleo": {
        "mayor": {"divisas": "🔴 Debilidad del dólar", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo económico", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Risk-off", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Aversión al riesgo", "lectura": "Aumentan las solicitudes de desempleo."},
        "menor": {"divisas": "🟢 Fortaleza del dólar", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Economía resiliente", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo inflacionario laboral", "riesgo": "🟢 Risk-on", "lectura": "El mercado laboral sigue fuerte."},
    },
    "Posiciones netas especulativas (CFTC)": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Posiciones netas especulativas (CFTC)» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Posicionamiento Especulativo; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Posiciones netas especulativas (CFTC)» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Posicionamiento Especulativo; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Posiciones netas especulativas en el AUD de la CFTC": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Posiciones netas especulativas en el AUD de la CFTC» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Posicionamiento Especulativo; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Posiciones netas especulativas en el AUD de la CFTC» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Posicionamiento Especulativo; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Posiciones netas especulativas en el EUR de la CFTC": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Posiciones netas especulativas en el EUR de la CFTC» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Posicionamiento Especulativo; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Posiciones netas especulativas en el EUR de la CFTC» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Posicionamiento Especulativo; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Posiciones netas especulativas en el GBP de la CFTC": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Posiciones netas especulativas en el GBP de la CFTC» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Posicionamiento Especulativo; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Posiciones netas especulativas en el GBP de la CFTC» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Posicionamiento Especulativo; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Posiciones netas especulativas en el JPY de la CFTC": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Posiciones netas especulativas en el JPY de la CFTC» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Posicionamiento Especulativo; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Posiciones netas especulativas en el JPY de la CFTC» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Posicionamiento Especulativo; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Posiciones netas especulativas en el Nasdaq 100 de la CFTC": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Posiciones netas especulativas en el Nasdaq 100 de la CFTC» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Posicionamiento Especulativo; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Posiciones netas especulativas en el Nasdaq 100 de la CFTC» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Posicionamiento Especulativo; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Posiciones netas especulativas en el S&P 500 de la CFTC": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Posiciones netas especulativas en el S&P 500 de la CFTC» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Posicionamiento Especulativo; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Posiciones netas especulativas en el S&P 500 de la CFTC» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Posicionamiento Especulativo; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Posiciones netas especulativas en el oro de la CFTC": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Posiciones netas especulativas en el oro de la CFTC» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Posicionamiento Especulativo; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Posiciones netas especulativas en el oro de la CFTC» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Posicionamiento Especulativo; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Posiciones netas especulativas en el petróleo de la CFTC": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Posiciones netas especulativas en el petróleo de la CFTC» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Posicionamiento Especulativo; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Posiciones netas especulativas en el petróleo de la CFTC» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Posicionamiento Especulativo; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Precios de Vivienda S&P/Case-Shiller": {
        "mayor": {"divisas": "🟢 Mercado inmobiliario fuerte", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Sector inmobiliario firme", "riesgo": "🟢 Risk-on", "lectura": "«Precios de Vivienda S&P/Case-Shiller»: el indicador inmobiliario sorprende al alza."},
        "menor": {"divisas": "🔴 Debilidad inmobiliaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para constructoras", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Sector inmobiliario debilitado", "riesgo": "🔴 Risk-off", "lectura": "«Precios de Vivienda S&P/Case-Shiller»: el indicador inmobiliario decepciona."},
    },
    "Precios de Vivienda S&P/Case-Shiller 20 no destacionalizado (Anual)": {
        "mayor": {"divisas": "🟢 Mercado inmobiliario fuerte", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Sector inmobiliario firme", "riesgo": "🟢 Risk-on", "lectura": "«Precios de Vivienda S&P/Case-Shiller 20 no destacionalizado (Anual)»: el indicador inmobiliario sorprende al alza."},
        "menor": {"divisas": "🔴 Debilidad inmobiliaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para constructoras", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Sector inmobiliario debilitado", "riesgo": "🔴 Risk-off", "lectura": "«Precios de Vivienda S&P/Case-Shiller 20 no destacionalizado (Anual)»: el indicador inmobiliario decepciona."},
    },
    "Precios de vivienda S&P/CS Composite-20 (no destacionalizado) (Mensual)": {
        "mayor": {"divisas": "🟢 Mercado inmobiliario fuerte", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Sector inmobiliario firme", "riesgo": "🟢 Risk-on", "lectura": "«Precios de vivienda S&P/CS Composite-20 (no destacionalizado) (Mensual)»: el indicador inmobiliario sorprende al alza."},
        "menor": {"divisas": "🔴 Debilidad inmobiliaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para constructoras", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Sector inmobiliario debilitado", "riesgo": "🔴 Risk-off", "lectura": "«Precios de vivienda S&P/CS Composite-20 (no destacionalizado) (Mensual)»: el indicador inmobiliario decepciona."},
    },
    "Precios del gasto en consumo personal subyacente (Anual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«Precios del gasto en consumo personal subyacente (Anual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«Precios del gasto en consumo personal subyacente (Anual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "Precios del gasto en consumo personal subyacente (Mensual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«Precios del gasto en consumo personal subyacente (Mensual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«Precios del gasto en consumo personal subyacente (Mensual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "Previsiones de inflación a 5 años (Universidad de Michigan)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«Previsiones de inflación a 5 años (Universidad de Michigan)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«Previsiones de inflación a 5 años (Universidad de Michigan)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "Previsiones de inflación a 5 años de la Universidad de Michigan": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«Previsiones de inflación a 5 años de la Universidad de Michigan»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«Previsiones de inflación a 5 años de la Universidad de Michigan»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "Previsiones de ventas de la industria minorista": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Previsiones de ventas de la industria minorista»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Previsiones de ventas de la industria minorista»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Previsiones de ventas de la industria minorista (Mensual)": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Previsiones de ventas de la industria minorista (Mensual)»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Previsiones de ventas de la industria minorista (Mensual)»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Previsión energética a corto plazo de la EIA": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Previsión energética a corto plazo de la EIA» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Energía; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Previsión energética a corto plazo de la EIA» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Energía; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Producción industrial": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Impulso industrial", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Economía fuerte", "riesgo": "🟢 Risk-on", "lectura": "La producción industrial acelera."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "La actividad industrial se debilita."},
    },
    "Producción industrial (Anual)": {
        "mayor": {"divisas": "🟢 Fortaleza industrial", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para industriales", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Actividad industrial en expansión", "riesgo": "🟢 Risk-on", "lectura": "«Producción industrial (Anual)»: la actividad industrial sorprende positivamente."},
        "menor": {"divisas": "🔴 Debilidad industrial", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el sector industrial", "oro": "🟢 Mayor cobertura defensiva", "crypto": "🔴 Risk-off", "politica": "📉 Debilidad económica", "riesgo": "🔴 Contracción", "lectura": "«Producción industrial (Anual)»: la actividad industrial decepciona."},
    },
    "Producción industrial (Mensual)": {
        "mayor": {"divisas": "🟢 Fortaleza industrial", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para industriales", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Actividad industrial en expansión", "riesgo": "🟢 Risk-on", "lectura": "«Producción industrial (Mensual)»: la actividad industrial sorprende positivamente."},
        "menor": {"divisas": "🔴 Debilidad industrial", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el sector industrial", "oro": "🟢 Mayor cobertura defensiva", "crypto": "🔴 Risk-off", "politica": "📉 Debilidad económica", "riesgo": "🔴 Contracción", "lectura": "«Producción industrial (Mensual)»: la actividad industrial decepciona."},
    },
    "Producción industrial de Alemania (Mensual)": {
        "mayor": {"divisas": "🟢 Fortaleza industrial", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para industriales", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Actividad industrial en expansión", "riesgo": "🟢 Risk-on", "lectura": "«Producción industrial de Alemania (Mensual)»: la actividad industrial sorprende positivamente."},
        "menor": {"divisas": "🔴 Debilidad industrial", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el sector industrial", "oro": "🟢 Mayor cobertura defensiva", "crypto": "🔴 Risk-off", "politica": "📉 Debilidad económica", "riesgo": "🔴 Contracción", "lectura": "«Producción industrial de Alemania (Mensual)»: la actividad industrial decepciona."},
    },
    "Producción industrial de China YTD (Anual)": {
        "mayor": {"divisas": "🟢 Fortaleza industrial", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para industriales", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Actividad industrial en expansión", "riesgo": "🟢 Risk-on", "lectura": "«Producción industrial de China YTD (Anual)»: la actividad industrial sorprende positivamente."},
        "menor": {"divisas": "🔴 Debilidad industrial", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el sector industrial", "oro": "🟢 Mayor cobertura defensiva", "crypto": "🔴 Risk-off", "politica": "📉 Debilidad económica", "riesgo": "🔴 Contracción", "lectura": "«Producción industrial de China YTD (Anual)»: la actividad industrial decepciona."},
    },
    "Producción industrial de España (Anual)": {
        "mayor": {"divisas": "🟢 Fortaleza industrial", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para industriales", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Actividad industrial en expansión", "riesgo": "🟢 Risk-on", "lectura": "«Producción industrial de España (Anual)»: la actividad industrial sorprende positivamente."},
        "menor": {"divisas": "🔴 Debilidad industrial", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el sector industrial", "oro": "🟢 Mayor cobertura defensiva", "crypto": "🔴 Risk-off", "politica": "📉 Debilidad económica", "riesgo": "🔴 Contracción", "lectura": "«Producción industrial de España (Anual)»: la actividad industrial decepciona."},
    },
    "Producción industrial en la zona euro (Mensual)": {
        "mayor": {"divisas": "🟢 Fortaleza industrial", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para industriales", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Actividad industrial en expansión", "riesgo": "🟢 Risk-on", "lectura": "«Producción industrial en la zona euro (Mensual)»: la actividad industrial sorprende positivamente."},
        "menor": {"divisas": "🔴 Debilidad industrial", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el sector industrial", "oro": "🟢 Mayor cobertura defensiva", "crypto": "🔴 Risk-off", "politica": "📉 Debilidad económica", "riesgo": "🔴 Contracción", "lectura": "«Producción industrial en la zona euro (Mensual)»: la actividad industrial decepciona."},
    },
    "Producción manufacturera": {
        "mayor": {"divisas": "🟢 Fortaleza industrial", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para industriales", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Actividad industrial en expansión", "riesgo": "🟢 Risk-on", "lectura": "«Producción manufacturera»: la actividad industrial sorprende positivamente."},
        "menor": {"divisas": "🔴 Debilidad industrial", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el sector industrial", "oro": "🟢 Mayor cobertura defensiva", "crypto": "🔴 Risk-off", "politica": "📉 Debilidad económica", "riesgo": "🔴 Contracción", "lectura": "«Producción manufacturera»: la actividad industrial decepciona."},
    },
    "Producción manufacturera (Mensual)": {
        "mayor": {"divisas": "🟢 Fortaleza industrial", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para industriales", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Actividad industrial en expansión", "riesgo": "🟢 Risk-on", "lectura": "«Producción manufacturera (Mensual)»: la actividad industrial sorprende positivamente."},
        "menor": {"divisas": "🔴 Debilidad industrial", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el sector industrial", "oro": "🟢 Mayor cobertura defensiva", "crypto": "🔴 Risk-off", "politica": "📉 Debilidad económica", "riesgo": "🔴 Contracción", "lectura": "«Producción manufacturera (Mensual)»: la actividad industrial decepciona."},
    },
    "Productividad laboral": {
        "mayor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Productividad laboral»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Productividad laboral»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
    },
    "Productividad no agrícola": {
        "mayor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Productividad no agrícola»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Productividad no agrícola»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
    },
    "Productividad no agrícola (Trimestral)": {
        "mayor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Productividad no agrícola (Trimestral)»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Productividad no agrícola (Trimestral)»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
    },
    "Recuento de yacimientos activos en EE.UU. de Baker Hughes": {
        "mayor": {"divisas": "🔴 Debilidad de monedas petroleras (mayor oferta)", "bonos": "🟢 Menor presión inflacionaria", "acciones": "🔴 Debilidad del sector energético", "oro": "🔴 Menor temor inflacionario", "crypto": "🟢 Riesgo moderadamente positivo", "politica": "📉 Menor presión inflacionaria por energía", "riesgo": "🟢 Ambiente más estable", "lectura": "«Recuento de yacimientos activos en EE.UU. de Baker Hughes»: el dato energético sugiere mayor oferta/holgura de lo esperado."},
        "menor": {"divisas": "🟢 Fortaleza de monedas ligadas a commodities", "bonos": "🔴 Riesgo inflacionario", "acciones": "🟢 Energéticas favorecidas", "oro": "🟢 Cobertura inflacionaria", "crypto": "🔴 Riesgo inflacionario", "politica": "📈 Mayor presión inflacionaria por energía", "riesgo": "⚠️ Mayor volatilidad", "lectura": "«Recuento de yacimientos activos en EE.UU. de Baker Hughes»: el dato energético sugiere mayor ajuste de oferta de lo esperado."},
    },
    "Referencia salarial (no desestacionalizada)": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Referencia salarial (no desestacionalizada)» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Empleo; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Referencia salarial (no desestacionalizada)» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Empleo; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Referencia salarial (no desestacionalizado)": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Referencia salarial (no desestacionalizado)» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Empleo; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Referencia salarial (no desestacionalizado)» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Empleo; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Renovaciones de los subsidios por desempleo": {
        "mayor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Renovaciones de los subsidios por desempleo»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
        "menor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Renovaciones de los subsidios por desempleo»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
    },
    "Reservas semanales de crudo del API": {
        "mayor": {"divisas": "🔴 Debilidad de monedas petroleras (mayor oferta)", "bonos": "🟢 Menor presión inflacionaria", "acciones": "🔴 Debilidad del sector energético", "oro": "🔴 Menor temor inflacionario", "crypto": "🟢 Riesgo moderadamente positivo", "politica": "📉 Menor presión inflacionaria por energía", "riesgo": "🟢 Ambiente más estable", "lectura": "«Reservas semanales de crudo del API»: el dato energético sugiere mayor oferta/holgura de lo esperado."},
        "menor": {"divisas": "🟢 Fortaleza de monedas ligadas a commodities", "bonos": "🔴 Riesgo inflacionario", "acciones": "🟢 Energéticas favorecidas", "oro": "🟢 Cobertura inflacionaria", "crypto": "🔴 Riesgo inflacionario", "politica": "📈 Mayor presión inflacionaria por energía", "riesgo": "⚠️ Mayor volatilidad", "lectura": "«Reservas semanales de crudo del API»: el dato energético sugiere mayor ajuste de oferta de lo esperado."},
    },
    "Resultado bruto de explotación de las empresas": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "«Resultado bruto de explotación de las empresas»: el dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "«Resultado bruto de explotación de las empresas»: el dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
    "Resultado bruto de explotación de las empresas (Trimestral)": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "«Resultado bruto de explotación de las empresas (Trimestral)»: el dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "«Resultado bruto de explotación de las empresas (Trimestral)»: el dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
    "Reunión de la OPEP": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Reunión de la OPEP» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Energía; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Reunión de la OPEP» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Energía; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Rueda de prensa de la NBS": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Rueda de prensa de la NBS» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios de Funcionarios; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Rueda de prensa de la NBS» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Comentarios de Funcionarios; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Simposio de Jackson Hole": {
        "mayor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Simposio de Jackson Hole» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Evento Especial; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
        "menor": {"divisas": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "bonos": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "acciones": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "oro": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "crypto": "⚪ Evento cualitativo, sin sesgo direccional predefinido", "politica": "⚪ No aplica un sesgo automático de política monetaria", "riesgo": "⚪ NEUTRO / EVENTO CUALITATIVO", "lectura": "«Simposio de Jackson Hole» es un evento cualitativo (comparecencia, informe, acta u otro dato sin cifra directamente comparable) dentro de Evento Especial; no se le asigna una lectura automática de bueno/malo — conviene leer el contenido puntual del evento en vez de basarse en si el número quedó por encima o por debajo de lo previsto."},
    },
    "Situación actual de Alemania": {
        "mayor": {"divisas": "🟢 Confianza empresarial en alza", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor refugio", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Expectativas económicas favorables", "riesgo": "🟢 Risk-on", "lectura": "«Situación actual de Alemania»: la confianza empresarial mejora más de lo esperado."},
        "menor": {"divisas": "🔴 Confianza empresarial deteriorada", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Risk-off", "politica": "📉 Expectativas económicas más débiles", "riesgo": "🔴 Aversión al riesgo", "lectura": "«Situación actual de Alemania»: la confianza empresarial cae más de lo esperado."},
    },
    "Subasta de bonos a 20 años": {
        "mayor": {"divisas": "🟢 Mayor rendimiento atrae capitales", "bonos": "🔴 Mayor rendimiento exigido, precio de bonos a la baja", "acciones": "🔴 Costo de financiamiento más alto", "oro": "🔴 Mayor costo de oportunidad para el oro", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 El mercado exige mayor prima por el riesgo de la deuda", "riesgo": "⚠️ Mercado de bonos exigente", "lectura": "«Subasta de bonos a 20 años»: la subasta se colocó con un rendimiento mayor al esperado."},
        "menor": {"divisas": "🔴 Menor rendimiento resta atractivo", "bonos": "🟢 Buena demanda, precio de bonos al alza", "acciones": "🟢 Menor costo de financiamiento", "oro": "🟢 Menor costo de oportunidad", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📉 Buena demanda por la deuda soberana", "riesgo": "🟢 Mercado de bonos tranquilo", "lectura": "«Subasta de bonos a 20 años»: la subasta se colocó con un rendimiento menor al esperado, señal de buena demanda."},
    },
    "Subasta de deuda a 10 años (JGB)": {
        "mayor": {"divisas": "🟢 Mayor rendimiento atrae capitales", "bonos": "🔴 Mayor rendimiento exigido, precio de bonos a la baja", "acciones": "🔴 Costo de financiamiento más alto", "oro": "🔴 Mayor costo de oportunidad para el oro", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 El mercado exige mayor prima por el riesgo de la deuda", "riesgo": "⚠️ Mercado de bonos exigente", "lectura": "«Subasta de deuda a 10 años (JGB)»: la subasta se colocó con un rendimiento mayor al esperado."},
        "menor": {"divisas": "🔴 Menor rendimiento resta atractivo", "bonos": "🟢 Buena demanda, precio de bonos al alza", "acciones": "🟢 Menor costo de financiamiento", "oro": "🟢 Menor costo de oportunidad", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📉 Buena demanda por la deuda soberana", "riesgo": "🟢 Mercado de bonos tranquilo", "lectura": "«Subasta de deuda a 10 años (JGB)»: la subasta se colocó con un rendimiento menor al esperado, señal de buena demanda."},
    },
    "Subasta de deuda a 3 años (T-Note)": {
        "mayor": {"divisas": "🟢 Mayor rendimiento atrae capitales", "bonos": "🔴 Mayor rendimiento exigido, precio de bonos a la baja", "acciones": "🔴 Costo de financiamiento más alto", "oro": "🔴 Mayor costo de oportunidad para el oro", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 El mercado exige mayor prima por el riesgo de la deuda", "riesgo": "⚠️ Mercado de bonos exigente", "lectura": "«Subasta de deuda a 3 años (T-Note)»: la subasta se colocó con un rendimiento mayor al esperado."},
        "menor": {"divisas": "🔴 Menor rendimiento resta atractivo", "bonos": "🟢 Buena demanda, precio de bonos al alza", "acciones": "🟢 Menor costo de financiamiento", "oro": "🟢 Menor costo de oportunidad", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📉 Buena demanda por la deuda soberana", "riesgo": "🟢 Mercado de bonos tranquilo", "lectura": "«Subasta de deuda a 3 años (T-Note)»: la subasta se colocó con un rendimiento menor al esperado, señal de buena demanda."},
    },
    "Subasta de deuda a 30 años ligada a inflación (TIPS)": {
        "mayor": {"divisas": "🟢 Mayor rendimiento atrae capitales", "bonos": "🔴 Mayor rendimiento exigido, precio de bonos a la baja", "acciones": "🔴 Costo de financiamiento más alto", "oro": "🔴 Mayor costo de oportunidad para el oro", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 El mercado exige mayor prima por el riesgo de la deuda", "riesgo": "⚠️ Mercado de bonos exigente", "lectura": "«Subasta de deuda a 30 años ligada a inflación (TIPS)»: la subasta se colocó con un rendimiento mayor al esperado."},
        "menor": {"divisas": "🔴 Menor rendimiento resta atractivo", "bonos": "🟢 Buena demanda, precio de bonos al alza", "acciones": "🟢 Menor costo de financiamiento", "oro": "🟢 Menor costo de oportunidad", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📉 Buena demanda por la deuda soberana", "riesgo": "🟢 Mercado de bonos tranquilo", "lectura": "«Subasta de deuda a 30 años ligada a inflación (TIPS)»: la subasta se colocó con un rendimiento menor al esperado, señal de buena demanda."},
    },
    "Subasta de deuda a 7 años (T-Note)": {
        "mayor": {"divisas": "🟢 Mayor rendimiento atrae capitales", "bonos": "🔴 Mayor rendimiento exigido, precio de bonos a la baja", "acciones": "🔴 Costo de financiamiento más alto", "oro": "🔴 Mayor costo de oportunidad para el oro", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 El mercado exige mayor prima por el riesgo de la deuda", "riesgo": "⚠️ Mercado de bonos exigente", "lectura": "«Subasta de deuda a 7 años (T-Note)»: la subasta se colocó con un rendimiento mayor al esperado."},
        "menor": {"divisas": "🔴 Menor rendimiento resta atractivo", "bonos": "🟢 Buena demanda, precio de bonos al alza", "acciones": "🟢 Menor costo de financiamiento", "oro": "🟢 Menor costo de oportunidad", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📉 Buena demanda por la deuda soberana", "riesgo": "🟢 Mercado de bonos tranquilo", "lectura": "«Subasta de deuda a 7 años (T-Note)»: la subasta se colocó con un rendimiento menor al esperado, señal de buena demanda."},
    },
    "Subasta de deuda italiana a 10 años ligada a la inflación (BTP)": {
        "mayor": {"divisas": "🟢 Mayor rendimiento atrae capitales", "bonos": "🔴 Mayor rendimiento exigido, precio de bonos a la baja", "acciones": "🔴 Costo de financiamiento más alto", "oro": "🔴 Mayor costo de oportunidad para el oro", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 El mercado exige mayor prima por el riesgo de la deuda", "riesgo": "⚠️ Mercado de bonos exigente", "lectura": "«Subasta de deuda italiana a 10 años ligada a la inflación (BTP)»: la subasta se colocó con un rendimiento mayor al esperado."},
        "menor": {"divisas": "🔴 Menor rendimiento resta atractivo", "bonos": "🟢 Buena demanda, precio de bonos al alza", "acciones": "🟢 Menor costo de financiamiento", "oro": "🟢 Menor costo de oportunidad", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📉 Buena demanda por la deuda soberana", "riesgo": "🟢 Mercado de bonos tranquilo", "lectura": "«Subasta de deuda italiana a 10 años ligada a la inflación (BTP)»: la subasta se colocó con un rendimiento menor al esperado, señal de buena demanda."},
    },
    "Subasta de deuda pública": {
        "mayor": {"divisas": "🟢 Mayor rendimiento atrae capitales", "bonos": "🔴 Mayor rendimiento exigido, precio de bonos a la baja", "acciones": "🔴 Costo de financiamiento más alto", "oro": "🔴 Mayor costo de oportunidad para el oro", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 El mercado exige mayor prima por el riesgo de la deuda", "riesgo": "⚠️ Mercado de bonos exigente", "lectura": "«Subasta de deuda pública»: la subasta se colocó con un rendimiento mayor al esperado."},
        "menor": {"divisas": "🔴 Menor rendimiento resta atractivo", "bonos": "🟢 Buena demanda, precio de bonos al alza", "acciones": "🟢 Menor costo de financiamiento", "oro": "🟢 Menor costo de oportunidad", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📉 Buena demanda por la deuda soberana", "riesgo": "🟢 Mercado de bonos tranquilo", "lectura": "«Subasta de deuda pública»: la subasta se colocó con un rendimiento menor al esperado, señal de buena demanda."},
    },
    "Subasta de deuda pública a 10 años (Bund)": {
        "mayor": {"divisas": "🟢 Mayor rendimiento atrae capitales", "bonos": "🔴 Mayor rendimiento exigido, precio de bonos a la baja", "acciones": "🔴 Costo de financiamiento más alto", "oro": "🔴 Mayor costo de oportunidad para el oro", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 El mercado exige mayor prima por el riesgo de la deuda", "riesgo": "⚠️ Mercado de bonos exigente", "lectura": "«Subasta de deuda pública a 10 años (Bund)»: la subasta se colocó con un rendimiento mayor al esperado."},
        "menor": {"divisas": "🔴 Menor rendimiento resta atractivo", "bonos": "🟢 Buena demanda, precio de bonos al alza", "acciones": "🟢 Menor costo de financiamiento", "oro": "🟢 Menor costo de oportunidad", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📉 Buena demanda por la deuda soberana", "riesgo": "🟢 Mercado de bonos tranquilo", "lectura": "«Subasta de deuda pública a 10 años (Bund)»: la subasta se colocó con un rendimiento menor al esperado, señal de buena demanda."},
    },
    "Subasta de deuda pública a 10 años (T-Note)": {
        "mayor": {"divisas": "🟢 Mayor rendimiento atrae capitales", "bonos": "🔴 Mayor rendimiento exigido, precio de bonos a la baja", "acciones": "🔴 Costo de financiamiento más alto", "oro": "🔴 Mayor costo de oportunidad para el oro", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 El mercado exige mayor prima por el riesgo de la deuda", "riesgo": "⚠️ Mercado de bonos exigente", "lectura": "«Subasta de deuda pública a 10 años (T-Note)»: la subasta se colocó con un rendimiento mayor al esperado."},
        "menor": {"divisas": "🔴 Menor rendimiento resta atractivo", "bonos": "🟢 Buena demanda, precio de bonos al alza", "acciones": "🟢 Menor costo de financiamiento", "oro": "🟢 Menor costo de oportunidad", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📉 Buena demanda por la deuda soberana", "riesgo": "🟢 Mercado de bonos tranquilo", "lectura": "«Subasta de deuda pública a 10 años (T-Note)»: la subasta se colocó con un rendimiento menor al esperado, señal de buena demanda."},
    },
    "Subasta de deuda pública a 30 años (T-Bond)": {
        "mayor": {"divisas": "🟢 Mayor rendimiento atrae capitales", "bonos": "🔴 Mayor rendimiento exigido, precio de bonos a la baja", "acciones": "🔴 Costo de financiamiento más alto", "oro": "🔴 Mayor costo de oportunidad para el oro", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 El mercado exige mayor prima por el riesgo de la deuda", "riesgo": "⚠️ Mercado de bonos exigente", "lectura": "«Subasta de deuda pública a 30 años (T-Bond)»: la subasta se colocó con un rendimiento mayor al esperado."},
        "menor": {"divisas": "🔴 Menor rendimiento resta atractivo", "bonos": "🟢 Buena demanda, precio de bonos al alza", "acciones": "🟢 Menor costo de financiamiento", "oro": "🟢 Menor costo de oportunidad", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📉 Buena demanda por la deuda soberana", "riesgo": "🟢 Mercado de bonos tranquilo", "lectura": "«Subasta de deuda pública a 30 años (T-Bond)»: la subasta se colocó con un rendimiento menor al esperado, señal de buena demanda."},
    },
    "Subasta de deuda pública a 5 años (T-Note)": {
        "mayor": {"divisas": "🟢 Mayor rendimiento atrae capitales", "bonos": "🔴 Mayor rendimiento exigido, precio de bonos a la baja", "acciones": "🔴 Costo de financiamiento más alto", "oro": "🔴 Mayor costo de oportunidad para el oro", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 El mercado exige mayor prima por el riesgo de la deuda", "riesgo": "⚠️ Mercado de bonos exigente", "lectura": "«Subasta de deuda pública a 5 años (T-Note)»: la subasta se colocó con un rendimiento mayor al esperado."},
        "menor": {"divisas": "🔴 Menor rendimiento resta atractivo", "bonos": "🟢 Buena demanda, precio de bonos al alza", "acciones": "🟢 Menor costo de financiamiento", "oro": "🟢 Menor costo de oportunidad", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📉 Buena demanda por la deuda soberana", "riesgo": "🟢 Mercado de bonos tranquilo", "lectura": "«Subasta de deuda pública a 5 años (T-Note)»: la subasta se colocó con un rendimiento menor al esperado, señal de buena demanda."},
    },
    "Tasa de desempleo": {
        "mayor": {"divisas": "🔴 Debilidad monetaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Risk-off", "politica": "📉 Posible flexibilización monetaria", "riesgo": "🔴 Aversión al riesgo", "lectura": "El deterioro laboral aumenta riesgos económicos."},
        "menor": {"divisas": "🟢 Fortaleza monetaria", "bonos": "🔴 Bonos presionados", "acciones": "🟠 Riesgo de política más restrictiva", "oro": "🔴 Menor demanda refugio", "crypto": "🔴 Menor liquidez", "politica": "📈 Riesgo de endurecimiento monetario", "riesgo": "⚠️ Mercado sensible a inflación salarial", "lectura": "El empleo sólido mantiene presión inflacionaria."},
    },
    "Tasa de desempleo U6": {
        "mayor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Tasa de desempleo U6»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
        "menor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Tasa de desempleo U6»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
    },
    "Tasa de desempleo de China": {
        "mayor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Tasa de desempleo de China»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
        "menor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Tasa de desempleo de China»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
    },
    "Tasa de desempleo en Alemania": {
        "mayor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Tasa de desempleo en Alemania»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
        "menor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Tasa de desempleo en Alemania»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
    },
    "Tasa de participación laboral": {
        "mayor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Tasa de participación laboral»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Tasa de participación laboral»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
    },
    "Tasa de préstamo preferencial del PBoC": {
        "mayor": {"divisas": "🟢 Sesgo más restrictivo favorece la moneda", "bonos": "🔴 Presión sobre bonos", "acciones": "🔴 Presión sobre acciones", "oro": "🔴 Oro debilitado en el corto plazo", "crypto": "🔴 Menor liquidez para activos de riesgo", "politica": "📈 Sesgo monetario más restrictivo", "riesgo": "🔴 Risk-off", "lectura": "«Tasa de préstamo preferencial del PBoC»: el dato de política monetaria resulta más restrictivo de lo esperado."},
        "menor": {"divisas": "🔴 Sesgo más expansivo debilita la moneda", "bonos": "🟢 Bonos favorecidos", "acciones": "🟢 Impulso para acciones", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mayor liquidez favorable", "politica": "📉 Sesgo monetario más expansivo", "riesgo": "🟢 Risk-on", "lectura": "«Tasa de préstamo preferencial del PBoC»: el dato de política monetaria resulta más expansivo de lo esperado."},
    },
    "Tipo hipotecario": {
        "mayor": {"divisas": "🔴 Debilidad inmobiliaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para constructoras", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Sector inmobiliario debilitado", "riesgo": "🔴 Risk-off", "lectura": "«Tipo hipotecario»: el indicador inmobiliario decepciona."},
        "menor": {"divisas": "🟢 Mercado inmobiliario fuerte", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Sector inmobiliario firme", "riesgo": "🟢 Risk-on", "lectura": "«Tipo hipotecario»: el indicador inmobiliario sorprende al alza."},
    },
    "Tipo hipotecario (GBP)": {
        "mayor": {"divisas": "🔴 Debilidad inmobiliaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para constructoras", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Sector inmobiliario debilitado", "riesgo": "🔴 Risk-off", "lectura": "«Tipo hipotecario (GBP)»: el indicador inmobiliario decepciona."},
        "menor": {"divisas": "🟢 Mercado inmobiliario fuerte", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Sector inmobiliario firme", "riesgo": "🟢 Risk-on", "lectura": "«Tipo hipotecario (GBP)»: el indicador inmobiliario sorprende al alza."},
    },
    "Variación del desempleo en España": {
        "mayor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Variación del desempleo en España»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
        "menor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Variación del desempleo en España»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
    },
    "Variación semanal del empleo según ADP": {
        "mayor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Variación semanal del empleo según ADP»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Variación semanal del empleo según ADP»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
    },
    "Venta de viviendas pendientes": {
        "mayor": {"divisas": "🟢 Mercado inmobiliario fuerte", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Sector inmobiliario firme", "riesgo": "🟢 Risk-on", "lectura": "«Venta de viviendas pendientes»: el indicador inmobiliario sorprende al alza."},
        "menor": {"divisas": "🔴 Debilidad inmobiliaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para constructoras", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Sector inmobiliario debilitado", "riesgo": "🔴 Risk-off", "lectura": "«Venta de viviendas pendientes»: el indicador inmobiliario decepciona."},
    },
    "Venta de viviendas pendientes (Mensual)": {
        "mayor": {"divisas": "🟢 Mercado inmobiliario fuerte", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Sector inmobiliario firme", "riesgo": "🟢 Risk-on", "lectura": "«Venta de viviendas pendientes (Mensual)»: el indicador inmobiliario sorprende al alza."},
        "menor": {"divisas": "🔴 Debilidad inmobiliaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para constructoras", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Sector inmobiliario debilitado", "riesgo": "🔴 Risk-off", "lectura": "«Venta de viviendas pendientes (Mensual)»: el indicador inmobiliario decepciona."},
    },
    "Ventas de viviendas de segunda mano": {
        "mayor": {"divisas": "🟢 Mercado inmobiliario fuerte", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Sector inmobiliario firme", "riesgo": "🟢 Risk-on", "lectura": "«Ventas de viviendas de segunda mano»: el indicador inmobiliario sorprende al alza."},
        "menor": {"divisas": "🔴 Debilidad inmobiliaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para constructoras", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Sector inmobiliario debilitado", "riesgo": "🔴 Risk-off", "lectura": "«Ventas de viviendas de segunda mano»: el indicador inmobiliario decepciona."},
    },
    "Ventas de viviendas de segunda mano (Mensual)": {
        "mayor": {"divisas": "🟢 Mercado inmobiliario fuerte", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Sector inmobiliario firme", "riesgo": "🟢 Risk-on", "lectura": "«Ventas de viviendas de segunda mano (Mensual)»: el indicador inmobiliario sorprende al alza."},
        "menor": {"divisas": "🔴 Debilidad inmobiliaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para constructoras", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Sector inmobiliario debilitado", "riesgo": "🔴 Risk-off", "lectura": "«Ventas de viviendas de segunda mano (Mensual)»: el indicador inmobiliario decepciona."},
    },
    "Ventas de viviendas existentes": {
        "mayor": {"divisas": "🟢 Fortaleza inmobiliaria", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Economía sólida", "riesgo": "🟢 Risk-on", "lectura": "Las ventas inmobiliarias aumentan."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo económico", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Risk-off", "politica": "📉 Menor crecimiento", "riesgo": "🔴 Desaceleración", "lectura": "Las ventas inmobiliarias disminuyen."},
    },
    "Ventas de viviendas nuevas": {
        "mayor": {"divisas": "🟢 Fortaleza inmobiliaria", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Actividad económica sólida", "riesgo": "🟢 Risk-on", "lectura": "El mercado inmobiliario muestra fortaleza."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo inmobiliario", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Desaceleración económica", "riesgo": "🔴 Risk-off", "lectura": "El mercado inmobiliario pierde impulso."},
    },
    "Ventas de viviendas nuevas (Mensual)": {
        "mayor": {"divisas": "🟢 Mercado inmobiliario fuerte", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Sector inmobiliario firme", "riesgo": "🟢 Risk-on", "lectura": "«Ventas de viviendas nuevas (Mensual)»: el indicador inmobiliario sorprende al alza."},
        "menor": {"divisas": "🔴 Debilidad inmobiliaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para constructoras", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Sector inmobiliario debilitado", "riesgo": "🔴 Risk-off", "lectura": "«Ventas de viviendas nuevas (Mensual)»: el indicador inmobiliario decepciona."},
    },
    "Ventas mayoristas": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Ventas mayoristas»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Ventas mayoristas»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Ventas mayoristas (Mensual)": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Ventas mayoristas (Mensual)»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Ventas mayoristas (Mensual)»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Ventas minoristas (Anual)": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Ventas minoristas (Anual)»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Ventas minoristas (Anual)»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Ventas minoristas (Mensual)": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Ventas minoristas (Mensual)»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Ventas minoristas (Mensual)»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Ventas minoristas (Trimestral)": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Ventas minoristas (Trimestral)»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Ventas minoristas (Trimestral)»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Ventas minoristas (headline)": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Consumo sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de inflación por consumo", "riesgo": "🟢 Risk-on", "lectura": "El consumo continúa sólido."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos riesgosos", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "El consumo comienza a desacelerarse."},
    },
    "Ventas minoristas abonadas con tarjeta de crédito o débito (Mensual)": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Ventas minoristas abonadas con tarjeta de crédito o débito (Mensual)»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Ventas minoristas abonadas con tarjeta de crédito o débito (Mensual)»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Ventas minoristas de Alemania (Mensual)": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Ventas minoristas de Alemania (Mensual)»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Ventas minoristas de Alemania (Mensual)»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Ventas minoristas en España (Anual)": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Ventas minoristas en España (Anual)»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Ventas minoristas en España (Anual)»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Ventas minoristas en la zona euro (Mensual)": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Ventas minoristas en la zona euro (Mensual)»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Ventas minoristas en la zona euro (Mensual)»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Ventas minoristas subyacentes": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Ventas minoristas subyacentes»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Ventas minoristas subyacentes»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Ventas minoristas subyacentes (Anual)": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Ventas minoristas subyacentes (Anual)»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Ventas minoristas subyacentes (Anual)»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Ventas minoristas subyacentes (Mensual)": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Ventas minoristas subyacentes (Mensual)»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Ventas minoristas subyacentes (Mensual)»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Ventas minoristas subyacentes (Trimestral)": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Ventas minoristas subyacentes (Trimestral)»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Ventas minoristas subyacentes (Trimestral)»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Índice Gfk de clima de consumo": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Índice Gfk de clima de consumo»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Índice Gfk de clima de consumo»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Índice Gfk de clima de consumo en Alemania": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Índice Gfk de clima de consumo en Alemania»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Índice Gfk de clima de consumo en Alemania»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Índice Halifax de precios de la vivienda": {
        "mayor": {"divisas": "🟢 Mercado inmobiliario fuerte", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Sector inmobiliario firme", "riesgo": "🟢 Risk-on", "lectura": "«Índice Halifax de precios de la vivienda»: el indicador inmobiliario sorprende al alza."},
        "menor": {"divisas": "🔴 Debilidad inmobiliaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para constructoras", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Sector inmobiliario debilitado", "riesgo": "🔴 Risk-off", "lectura": "«Índice Halifax de precios de la vivienda»: el indicador inmobiliario decepciona."},
    },
    "Índice Halifax de precios de la vivienda (Anual)": {
        "mayor": {"divisas": "🟢 Mercado inmobiliario fuerte", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Sector inmobiliario firme", "riesgo": "🟢 Risk-on", "lectura": "«Índice Halifax de precios de la vivienda (Anual)»: el indicador inmobiliario sorprende al alza."},
        "menor": {"divisas": "🔴 Debilidad inmobiliaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para constructoras", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Sector inmobiliario debilitado", "riesgo": "🔴 Risk-off", "lectura": "«Índice Halifax de precios de la vivienda (Anual)»: el indicador inmobiliario decepciona."},
    },
    "Índice Halifax de precios de la vivienda (Mensual)": {
        "mayor": {"divisas": "🟢 Mercado inmobiliario fuerte", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Sector inmobiliario firme", "riesgo": "🟢 Risk-on", "lectura": "«Índice Halifax de precios de la vivienda (Mensual)»: el indicador inmobiliario sorprende al alza."},
        "menor": {"divisas": "🔴 Debilidad inmobiliaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para constructoras", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Sector inmobiliario debilitado", "riesgo": "🔴 Risk-off", "lectura": "«Índice Halifax de precios de la vivienda (Mensual)»: el indicador inmobiliario decepciona."},
    },
    "Índice ISM de empleo en el sector manufacturero": {
        "mayor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Índice ISM de empleo en el sector manufacturero»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Índice ISM de empleo en el sector manufacturero»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
    },
    "Índice ISM de empleo en el sector no manufacturero": {
        "mayor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Índice ISM de empleo en el sector no manufacturero»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Índice ISM de empleo en el sector no manufacturero»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
    },
    "Índice ISM de precios del sector no manufacturero": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«Índice ISM de precios del sector no manufacturero»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«Índice ISM de precios del sector no manufacturero»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "Índice Ifo de confianza empresarial": {
        "mayor": {"divisas": "🟢 Confianza empresarial en alza", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor refugio", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Expectativas económicas favorables", "riesgo": "🟢 Risk-on", "lectura": "«Índice Ifo de confianza empresarial»: la confianza empresarial mejora más de lo esperado."},
        "menor": {"divisas": "🔴 Confianza empresarial deteriorada", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Risk-off", "politica": "📉 Expectativas económicas más débiles", "riesgo": "🔴 Aversión al riesgo", "lectura": "«Índice Ifo de confianza empresarial»: la confianza empresarial cae más de lo esperado."},
    },
    "Índice Ifo de confianza empresarial en Alemania": {
        "mayor": {"divisas": "🟢 Confianza empresarial en alza", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor refugio", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Expectativas económicas favorables", "riesgo": "🟢 Risk-on", "lectura": "«Índice Ifo de confianza empresarial en Alemania»: la confianza empresarial mejora más de lo esperado."},
        "menor": {"divisas": "🔴 Confianza empresarial deteriorada", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Risk-off", "politica": "📉 Expectativas económicas más débiles", "riesgo": "🔴 Aversión al riesgo", "lectura": "«Índice Ifo de confianza empresarial en Alemania»: la confianza empresarial cae más de lo esperado."},
    },
    "Índice NAB de confianza empresarial": {
        "mayor": {"divisas": "🟢 Confianza empresarial en alza", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor refugio", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Expectativas económicas favorables", "riesgo": "🟢 Risk-on", "lectura": "«Índice NAB de confianza empresarial»: la confianza empresarial mejora más de lo esperado."},
        "menor": {"divisas": "🔴 Confianza empresarial deteriorada", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Risk-off", "politica": "📉 Expectativas económicas más débiles", "riesgo": "🔴 Aversión al riesgo", "lectura": "«Índice NAB de confianza empresarial»: la confianza empresarial cae más de lo esperado."},
    },
    "Índice ZEW de confianza inversora": {
        "mayor": {"divisas": "🟢 Confianza empresarial en alza", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor refugio", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Expectativas económicas favorables", "riesgo": "🟢 Risk-on", "lectura": "«Índice ZEW de confianza inversora»: la confianza empresarial mejora más de lo esperado."},
        "menor": {"divisas": "🔴 Confianza empresarial deteriorada", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Risk-off", "politica": "📉 Expectativas económicas más débiles", "riesgo": "🔴 Aversión al riesgo", "lectura": "«Índice ZEW de confianza inversora»: la confianza empresarial cae más de lo esperado."},
    },
    "Índice ZEW de confianza inversora en Alemania": {
        "mayor": {"divisas": "🟢 Confianza empresarial en alza", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor refugio", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Expectativas económicas favorables", "riesgo": "🟢 Risk-on", "lectura": "«Índice ZEW de confianza inversora en Alemania»: la confianza empresarial mejora más de lo esperado."},
        "menor": {"divisas": "🔴 Confianza empresarial deteriorada", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Risk-off", "politica": "📉 Expectativas económicas más débiles", "riesgo": "🔴 Aversión al riesgo", "lectura": "«Índice ZEW de confianza inversora en Alemania»: la confianza empresarial cae más de lo esperado."},
    },
    "Índice ZEW de confianza inversora en Alemania - situación actual": {
        "mayor": {"divisas": "🟢 Confianza empresarial en alza", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor refugio", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Expectativas económicas favorables", "riesgo": "🟢 Risk-on", "lectura": "«Índice ZEW de confianza inversora en Alemania - situación actual»: la confianza empresarial mejora más de lo esperado."},
        "menor": {"divisas": "🔴 Confianza empresarial deteriorada", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Risk-off", "politica": "📉 Expectativas económicas más débiles", "riesgo": "🔴 Aversión al riesgo", "lectura": "«Índice ZEW de confianza inversora en Alemania - situación actual»: la confianza empresarial cae más de lo esperado."},
    },
    "Índice ZEW de confianza inversora en la zona euro": {
        "mayor": {"divisas": "🟢 Confianza empresarial en alza", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor refugio", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Expectativas económicas favorables", "riesgo": "🟢 Risk-on", "lectura": "«Índice ZEW de confianza inversora en la zona euro»: la confianza empresarial mejora más de lo esperado."},
        "menor": {"divisas": "🔴 Confianza empresarial deteriorada", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Risk-off", "politica": "📉 Expectativas económicas más débiles", "riesgo": "🔴 Aversión al riesgo", "lectura": "«Índice ZEW de confianza inversora en la zona euro»: la confianza empresarial cae más de lo esperado."},
    },
    "Índice de Precios de Importación": {
        "mayor": {"divisas": "🔴 Moneda presionada por deterioro comercial", "bonos": "⚪ Impacto limitado", "acciones": "🔴 Riesgo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro del sector externo", "riesgo": "🔴 Levemente negativo", "lectura": "«Índice de Precios de Importación»: la balanza comercial se deteriora más de lo esperado."},
        "menor": {"divisas": "🟢 Moneda favorecida por mejora comercial", "bonos": "⚪ Impacto limitado", "acciones": "🟢 Positivo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📈 Sector externo saludable", "riesgo": "🟢 Levemente positivo", "lectura": "«Índice de Precios de Importación»: la balanza comercial mejora respecto de lo esperado."},
    },
    "Índice de Precios de Importación (Mensual)": {
        "mayor": {"divisas": "🔴 Moneda presionada por deterioro comercial", "bonos": "⚪ Impacto limitado", "acciones": "🔴 Riesgo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro del sector externo", "riesgo": "🔴 Levemente negativo", "lectura": "«Índice de Precios de Importación (Mensual)»: la balanza comercial se deteriora más de lo esperado."},
        "menor": {"divisas": "🟢 Moneda favorecida por mejora comercial", "bonos": "⚪ Impacto limitado", "acciones": "🟢 Positivo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📈 Sector externo saludable", "riesgo": "🟢 Levemente positivo", "lectura": "«Índice de Precios de Importación (Mensual)»: la balanza comercial mejora respecto de lo esperado."},
    },
    "Índice de Precios del Gasto en Consumo Personal (PCE) (Mensual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«Índice de Precios del Gasto en Consumo Personal (PCE) (Mensual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«Índice de Precios del Gasto en Consumo Personal (PCE) (Mensual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "Índice de Producción Industrial (Anual)": {
        "mayor": {"divisas": "🟢 Fortaleza industrial", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para industriales", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Actividad industrial en expansión", "riesgo": "🟢 Risk-on", "lectura": "«Índice de Producción Industrial (Anual)»: la actividad industrial sorprende positivamente."},
        "menor": {"divisas": "🔴 Debilidad industrial", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el sector industrial", "oro": "🟢 Mayor cobertura defensiva", "crypto": "🔴 Risk-off", "politica": "📉 Debilidad económica", "riesgo": "🔴 Contracción", "lectura": "«Índice de Producción Industrial (Anual)»: la actividad industrial decepciona."},
    },
    "Índice de Producción Industrial (China)": {
        "mayor": {"divisas": "🟢 Fortaleza industrial", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para industriales", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Actividad industrial en expansión", "riesgo": "🟢 Risk-on", "lectura": "«Índice de Producción Industrial (China)»: la actividad industrial sorprende positivamente."},
        "menor": {"divisas": "🔴 Debilidad industrial", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el sector industrial", "oro": "🟢 Mayor cobertura defensiva", "crypto": "🔴 Risk-off", "politica": "📉 Debilidad económica", "riesgo": "🔴 Contracción", "lectura": "«Índice de Producción Industrial (China)»: la actividad industrial decepciona."},
    },
    "Índice de costes salariales": {
        "mayor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Índice de costes salariales»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
        "menor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Índice de costes salariales»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
    },
    "Índice de costes salariales (Trimestral)": {
        "mayor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "«Índice de costes salariales (Trimestral)»: el dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
        "menor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "«Índice de costes salariales (Trimestral)»: el dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
    },
    "Índice de precios PCE (Anual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«Índice de precios PCE (Anual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«Índice de precios PCE (Anual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "Índice de precios de bienes y servicios del PIB (Deflactor)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«Índice de precios de bienes y servicios del PIB (Deflactor)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«Índice de precios de bienes y servicios del PIB (Deflactor)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "Índice de precios de bienes y servicios incluidos en el PIB (Anual)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«Índice de precios de bienes y servicios incluidos en el PIB (Anual)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«Índice de precios de bienes y servicios incluidos en el PIB (Anual)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "Índice de precios de bienes y servicios incluidos en el PIB (Trimestral)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«Índice de precios de bienes y servicios incluidos en el PIB (Trimestral)»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«Índice de precios de bienes y servicios incluidos en el PIB (Trimestral)»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "Índice de precios de exportación": {
        "mayor": {"divisas": "🟢 Moneda favorecida por mejora comercial", "bonos": "⚪ Impacto limitado", "acciones": "🟢 Positivo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📈 Sector externo saludable", "riesgo": "🟢 Levemente positivo", "lectura": "«Índice de precios de exportación»: la balanza comercial mejora respecto de lo esperado."},
        "menor": {"divisas": "🔴 Moneda presionada por deterioro comercial", "bonos": "⚪ Impacto limitado", "acciones": "🔴 Riesgo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro del sector externo", "riesgo": "🔴 Levemente negativo", "lectura": "«Índice de precios de exportación»: la balanza comercial se deteriora más de lo esperado."},
    },
    "Índice de precios de exportación (Mensual)": {
        "mayor": {"divisas": "🟢 Moneda favorecida por mejora comercial", "bonos": "⚪ Impacto limitado", "acciones": "🟢 Positivo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📈 Sector externo saludable", "riesgo": "🟢 Levemente positivo", "lectura": "«Índice de precios de exportación (Mensual)»: la balanza comercial mejora respecto de lo esperado."},
        "menor": {"divisas": "🔴 Moneda presionada por deterioro comercial", "bonos": "⚪ Impacto limitado", "acciones": "🔴 Riesgo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro del sector externo", "riesgo": "🔴 Levemente negativo", "lectura": "«Índice de precios de exportación (Mensual)»: la balanza comercial se deteriora más de lo esperado."},
    },
    "Índice de precios de materias primas (Mensual)": {
        "mayor": {"divisas": "🟢 Fortaleza industrial", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para industriales", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Actividad industrial en expansión", "riesgo": "🟢 Risk-on", "lectura": "«Índice de precios de materias primas (Mensual)»: la actividad industrial sorprende positivamente."},
        "menor": {"divisas": "🔴 Debilidad industrial", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el sector industrial", "oro": "🟢 Mayor cobertura defensiva", "crypto": "🔴 Risk-off", "politica": "📉 Debilidad económica", "riesgo": "🔴 Contracción", "lectura": "«Índice de precios de materias primas (Mensual)»: la actividad industrial decepciona."},
    },
    "Índice de precios de viviendas nuevas": {
        "mayor": {"divisas": "🟢 Mercado inmobiliario fuerte", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Sector inmobiliario firme", "riesgo": "🟢 Risk-on", "lectura": "«Índice de precios de viviendas nuevas»: el indicador inmobiliario sorprende al alza."},
        "menor": {"divisas": "🔴 Debilidad inmobiliaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para constructoras", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Sector inmobiliario debilitado", "riesgo": "🔴 Risk-off", "lectura": "«Índice de precios de viviendas nuevas»: el indicador inmobiliario decepciona."},
    },
    "Índice de precios de viviendas nuevas (Mensual)": {
        "mayor": {"divisas": "🟢 Mercado inmobiliario fuerte", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Sector inmobiliario firme", "riesgo": "🟢 Risk-on", "lectura": "«Índice de precios de viviendas nuevas (Mensual)»: el indicador inmobiliario sorprende al alza."},
        "menor": {"divisas": "🔴 Debilidad inmobiliaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para constructoras", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Sector inmobiliario debilitado", "riesgo": "🔴 Risk-off", "lectura": "«Índice de precios de viviendas nuevas (Mensual)»: el indicador inmobiliario decepciona."},
    },
    "Índice de precios del sector manufacturero ISM": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "«Índice de precios del sector manufacturero ISM»: el dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "«Índice de precios del sector manufacturero ISM»: el dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "Índice de producción industrial (Mensual)": {
        "mayor": {"divisas": "🟢 Fortaleza industrial", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para industriales", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Actividad industrial en expansión", "riesgo": "🟢 Risk-on", "lectura": "«Índice de producción industrial (Mensual)»: la actividad industrial sorprende positivamente."},
        "menor": {"divisas": "🔴 Debilidad industrial", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el sector industrial", "oro": "🟢 Mayor cobertura defensiva", "crypto": "🔴 Risk-off", "politica": "📉 Debilidad económica", "riesgo": "🔴 Contracción", "lectura": "«Índice de producción industrial (Mensual)»: la actividad industrial decepciona."},
    },
    "Índice de ventas al por menor del BRC (Anual)": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "«Índice de ventas al por menor del BRC (Anual)»: el consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "«Índice de ventas al por menor del BRC (Anual)»: el consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Índice manufacturero Empire State": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«Índice manufacturero Empire State»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«Índice manufacturero Empire State»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "Índice manufacturero de la Fed de Filadelfia": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "«Índice manufacturero de la Fed de Filadelfia»: el indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "«Índice manufacturero de la Fed de Filadelfia»: el indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "Índice principal de EE.UU. (Leading Index)": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "«Índice principal de EE.UU. (Leading Index)»: el dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "«Índice principal de EE.UU. (Leading Index)»: el dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
    "Índice principal de EE.UU. (Mensual)": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "«Índice principal de EE.UU. (Mensual)»: el dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "«Índice principal de EE.UU. (Mensual)»: el dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
}

# ==============================================================
#  INTERPRETACIÓN MACRO GENÉRICA POR CATEGORÍA (fallback)
# ==============================================================
CATEGORIA_INTERPRETACION = {
    "Inflación": {
        "mayor": {"divisas": "🟢 Moneda fuerte por sorpresa inflacionaria", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Presión sobre acciones", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Presión hacia una política monetaria más restrictiva", "riesgo": "🔴 Risk-off", "lectura": "El dato de inflación sorprende al alza y reaviva la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Espacio para una política monetaria más flexible", "riesgo": "🟢 Risk-on", "lectura": "El dato de inflación sorprende a la baja y mejora el entorno financiero."},
    },
    "Empleo": {
        "mayor": {"divisas": "🟢 Moneda fortalecida por mercado laboral sólido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de tasas más altas por más tiempo", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Mercado laboral firme, riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "El dato laboral sorprende positivamente y muestra un mercado de trabajo firme."},
        "menor": {"divisas": "🔴 Moneda debilitada", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso para acciones por expectativa de recortes", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Mayor probabilidad de flexibilización monetaria", "riesgo": "🟢 Risk-on", "lectura": "El dato laboral decepciona y sugiere un mercado de trabajo enfriándose."},
    },
    "Actividad Económica": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica en expansión", "riesgo": "🟢 Expansión económica", "lectura": "El indicador de actividad supera lo esperado y confirma expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Mayor probabilidad de estímulo", "riesgo": "🔴 Contracción económica", "lectura": "El indicador de actividad decepciona y sugiere pérdida de impulso."},
    },
    "Consumo": {
        "mayor": {"divisas": "🟢 Consumo interno sólido", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para el consumo discrecional", "oro": "🔴 Menor cobertura necesaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de presión inflacionaria por demanda", "riesgo": "🟢 Risk-on", "lectura": "El consumo sorprende al alza y sostiene el crecimiento económico."},
        "menor": {"divisas": "🔴 Consumo débil", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el consumo discrecional", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "El consumo decepciona y enciende alertas sobre la demanda interna."},
    },
    "Crecimiento": {
        "mayor": {"divisas": "🟢 Fortaleza del crecimiento", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "El dato de crecimiento supera expectativas."},
        "menor": {"divisas": "🔴 Debilidad del crecimiento", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración/recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "El dato de crecimiento decepciona y enciende alertas de desaceleración."},
    },
    "Industria": {
        "mayor": {"divisas": "🟢 Fortaleza industrial", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para industriales", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Actividad industrial en expansión", "riesgo": "🟢 Risk-on", "lectura": "La actividad industrial sorprende positivamente."},
        "menor": {"divisas": "🔴 Debilidad industrial", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para el sector industrial", "oro": "🟢 Mayor cobertura defensiva", "crypto": "🔴 Risk-off", "politica": "📉 Debilidad económica", "riesgo": "🔴 Contracción", "lectura": "La actividad industrial decepciona."},
    },
    "Vivienda": {
        "mayor": {"divisas": "🟢 Mercado inmobiliario fuerte", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Sector inmobiliario firme", "riesgo": "🟢 Risk-on", "lectura": "El indicador inmobiliario sorprende al alza."},
        "menor": {"divisas": "🔴 Debilidad inmobiliaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo para constructoras", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Sector inmobiliario debilitado", "riesgo": "🔴 Risk-off", "lectura": "El indicador inmobiliario decepciona."},
    },
    "Comercio Exterior": {
        "mayor": {"divisas": "🟢 Moneda favorecida por mejora comercial", "bonos": "⚪ Impacto limitado", "acciones": "🟢 Positivo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📈 Sector externo saludable", "riesgo": "🟢 Levemente positivo", "lectura": "La balanza comercial mejora respecto de lo esperado."},
        "menor": {"divisas": "🔴 Moneda presionada por deterioro comercial", "bonos": "⚪ Impacto limitado", "acciones": "🔴 Riesgo para exportadoras", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro del sector externo", "riesgo": "🔴 Levemente negativo", "lectura": "La balanza comercial se deteriora más de lo esperado."},
    },
    "Sentimiento Empresarial": {
        "mayor": {"divisas": "🟢 Confianza empresarial en alza", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor refugio", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Expectativas económicas favorables", "riesgo": "🟢 Risk-on", "lectura": "La confianza empresarial mejora más de lo esperado."},
        "menor": {"divisas": "🔴 Confianza empresarial deteriorada", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Risk-off", "politica": "📉 Expectativas económicas más débiles", "riesgo": "🔴 Aversión al riesgo", "lectura": "La confianza empresarial cae más de lo esperado."},
    },
    "Energía": {
        "mayor": {"divisas": "🔴 Debilidad de monedas petroleras (mayor oferta)", "bonos": "🟢 Menor presión inflacionaria", "acciones": "🔴 Debilidad del sector energético", "oro": "🔴 Menor temor inflacionario", "crypto": "🟢 Riesgo moderadamente positivo", "politica": "📉 Menor presión inflacionaria por energía", "riesgo": "🟢 Ambiente más estable", "lectura": "El dato energético sugiere mayor oferta/holgura de lo esperado."},
        "menor": {"divisas": "🟢 Fortaleza de monedas ligadas a commodities", "bonos": "🔴 Riesgo inflacionario", "acciones": "🟢 Energéticas favorecidas", "oro": "🟢 Cobertura inflacionaria", "crypto": "🔴 Riesgo inflacionario", "politica": "📈 Mayor presión inflacionaria por energía", "riesgo": "⚠️ Mayor volatilidad", "lectura": "El dato energético sugiere mayor ajuste de oferta de lo esperado."},
    },
    "Política Monetaria": {
        "mayor": {"divisas": "🟢 Sesgo más restrictivo favorece la moneda", "bonos": "🔴 Presión sobre bonos", "acciones": "🔴 Presión sobre acciones", "oro": "🔴 Oro debilitado en el corto plazo", "crypto": "🔴 Menor liquidez para activos de riesgo", "politica": "📈 Sesgo monetario más restrictivo", "riesgo": "🔴 Risk-off", "lectura": "El dato de política monetaria resulta más restrictivo de lo esperado."},
        "menor": {"divisas": "🔴 Sesgo más expansivo debilita la moneda", "bonos": "🟢 Bonos favorecidos", "acciones": "🟢 Impulso para acciones", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mayor liquidez favorable", "politica": "📉 Sesgo monetario más expansivo", "riesgo": "🟢 Risk-on", "lectura": "El dato de política monetaria resulta más expansivo de lo esperado."},
    },
    "Política Fiscal": {
        "mayor": {"divisas": "🟢 Mejora la percepción fiscal", "bonos": "🟢 Menor emisión relativa favorece bonos", "acciones": "⚪ Impacto mixto", "oro": "🔴 Menor necesidad de cobertura", "crypto": "⚪ Impacto limitado", "politica": "📈 Mejora de las cuentas públicas", "riesgo": "🟢 Menor riesgo fiscal", "lectura": "El resultado fiscal es mejor (déficit menor al esperado) de lo esperado."},
        "menor": {"divisas": "🔴 Mayor déficit genera cautela sobre la moneda", "bonos": "🔴 Mayor emisión presiona bonos", "acciones": "⚪ Impacto mixto", "oro": "🟢 Cobertura ante riesgo fiscal", "crypto": "⚪ Impacto limitado", "politica": "📉 Deterioro de las cuentas públicas", "riesgo": "🔴 Riesgo fiscal", "lectura": "El resultado fiscal es peor (déficit mayor al esperado)."},
    },
    "Crédito": {
        "mayor": {"divisas": "⚪ Impacto mixto", "bonos": "🔴 Riesgo de sobrecalentamiento crediticio", "acciones": "🟢 Mayor liquidez favorece activos de riesgo", "oro": "⚪ Impacto limitado", "crypto": "🟢 Mayor liquidez disponible", "politica": "📈 Fuerte expansión del crédito", "riesgo": "🟢 Risk-on de corto plazo", "lectura": "El crédito se expande más de lo esperado."},
        "menor": {"divisas": "⚪ Impacto mixto", "bonos": "🟢 Menor riesgo de sobrecalentamiento", "acciones": "🔴 Menor liquidez disponible", "oro": "⚪ Impacto limitado", "crypto": "🔴 Menor liquidez disponible", "politica": "📉 Contracción del crédito", "riesgo": "🔴 Menor impulso crediticio", "lectura": "El crédito se expande menos de lo esperado."},
    },
    "Deuda Pública": {
        "mayor": {"divisas": "🟢 Mayor rendimiento atrae capitales", "bonos": "🔴 Mayor rendimiento exigido, precio de bonos a la baja", "acciones": "🔴 Costo de financiamiento más alto", "oro": "🔴 Mayor costo de oportunidad para el oro", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 El mercado exige mayor prima por el riesgo de la deuda", "riesgo": "⚠️ Mercado de bonos exigente", "lectura": "La subasta se colocó con un rendimiento mayor al esperado."},
        "menor": {"divisas": "🔴 Menor rendimiento resta atractivo", "bonos": "🟢 Buena demanda, precio de bonos al alza", "acciones": "🟢 Menor costo de financiamiento", "oro": "🟢 Menor costo de oportunidad", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📉 Buena demanda por la deuda soberana", "riesgo": "🟢 Mercado de bonos tranquilo", "lectura": "La subasta se colocó con un rendimiento menor al esperado, señal de buena demanda."},
    },
    "Posicionamiento Especulativo": {
        "mayor": {"divisas": "⚪ Posicionamiento más largo/alcista neto", "bonos": "⚪ Impacto limitado", "acciones": "⚪ Impacto limitado", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "⚪ No aplica", "riesgo": "⚠️ Posicionamiento extendido, riesgo de corrección técnica", "lectura": "Los especuladores aumentan su posición neta larga más de lo esperado."},
        "menor": {"divisas": "⚪ Posicionamiento más corto/bajista neto", "bonos": "⚪ Impacto limitado", "acciones": "⚪ Impacto limitado", "oro": "⚪ Impacto limitado", "crypto": "⚪ Impacto limitado", "politica": "⚪ No aplica", "riesgo": "⚠️ Posicionamiento más defensivo", "lectura": "Los especuladores reducen (o acortan) su posición neta larga más de lo esperado."},
    },
}

# ==============================================================
#  EXPLICACIÓN EN LENGUAJE SIMPLE DE CADA CATEGORÍA — para que el
#  informe narrativo no de por sentado que el lector sabe qué mide
#  cada categoría ni qué significa "un dato mejor" en cada caso.
# ==============================================================
CATEGORIA_EXPLICACION = {
    "Inflación": "mide cuánto suben los precios; acá \"mejor\" significa que la inflación salió más baja de lo esperado",
    "Empleo": "mide la fortaleza del mercado laboral; acá \"mejor\" significa más empleo creado o menos desempleo del esperado",
    "Actividad Económica": "mide el pulso de fábricas y servicios (PMI/ISM); acá \"mejor\" significa mayor expansión de la actividad",
    "Consumo": "mide cuánto gasta y cuánto confía el consumidor; acá \"mejor\" significa consumidores más activos o confiados",
    "Crecimiento": "mide la expansión total de la economía (PBI); acá \"mejor\" significa que el país creció más de lo previsto",
    "Industria": "mide la producción de fábricas y pedidos industriales; acá \"mejor\" significa mayor actividad industrial",
    "Vivienda": "mide la actividad del sector inmobiliario; acá \"mejor\" significa más ventas, permisos o inicios de obra",
    "Comercio Exterior": "mide el balance entre lo que el país exporta e importa; acá \"mejor\" significa mayor superávit comercial",
    "Sentimiento Empresarial": "mide qué tan optimistas están las empresas sobre el futuro; acá \"mejor\" significa mayor confianza",
    "Energía": "mide oferta y demanda de petróleo y combustibles; la lectura de \"mejor/peor\" depende del indicador puntual",
    "Política Monetaria": "agrupa eventos ligados a decisiones o comunicación del banco central",
    "Política Fiscal": "mide el resultado de las cuentas públicas del gobierno (déficit o superávit)",
    "Crédito": "mide qué tan rápido se expande el crédito bancario en la economía",
    "Deuda Pública": "mide el resultado de las subastas de deuda del gobierno (tasa que exige el mercado)",
    "Posicionamiento Especulativo": "mide cómo están posicionados los especuladores en el mercado de futuros",
    "Agricultura": "mide oferta y demanda de productos agrícolas",
    "Comentarios de Funcionarios": "agrupa comparecencias y declaraciones de funcionarios de bancos centrales; no tiene cifra comparable, así que no aplica un criterio de \"mejor/peor\"",
    "Comentarios Políticos": "agrupa declaraciones de líderes políticos con potencial impacto en mercados; no tiene cifra comparable, así que no aplica un criterio de \"mejor/peor\"",
    "Evento Especial": "agrupa eventos puntuales de alto impacto (simposios, cumbres) sin cifra comparable, así que no aplica un criterio de \"mejor/peor\"",
}


def _explicacion_categoria(categoria):
    return CATEGORIA_EXPLICACION.get(
        categoria, "agrupa datos económicos relacionados con este sector"
    )


_POLARIDAD_EXPLICACION = {
    "directa": "un dato por ENCIMA de lo previsto se lee como positivo para la economía (y por debajo, como negativo)",
    "inversa": "un dato por ENCIMA de lo previsto se lee como negativo para la economía (y por debajo, como positivo) — es el caso típico de desempleo, inflación, tasas o costos",
    "neutral": "es un evento cualitativo (comparecencia, actas, etc.) sin una lectura automática de bueno/malo",
}


def _detalle_eventos_categoria(sub_df):
    """Arma una tabla legible con cada evento puntuable que compone una
    categoría — de qué se trata cada uno, qué criterio de polaridad se
    le aplicó y qué puntaje individual terminó aportando al promedio.
    Es el desglose que justifica el puntaje agregado que se ve arriba."""
    if sub_df.empty:
        return pd.DataFrame(columns=["Fecha", "Evento", "Impacto", "Previsto", "Anterior", "Real",
                                      "Unidad", "Criterio aplicado", "Lectura", "Puntaje", "Peso"])
    df_ord = sub_df.sort_values("fecha_dt", ascending=False)
    filas = []
    for _, r in df_ord.iterrows():
        evento = r.get("evento")
        info = EVENTOS.get(evento, {})
        polaridad = info.get("polaridad", "directa")
        criterio = {"directa": "Mayor = mejor", "inversa": "Mayor = peor", "neutral": "Cualitativo"}.get(polaridad, "—")
        unidad = r.get("unidad") or info.get("unidad") or ""
        score_val = r.get("score")
        peso_val = r.get("peso")
        filas.append({
            "Fecha": r.get("fecha"),
            "Evento": evento,
            "Impacto": info.get("impacto", r.get("relevancia") or "—"),
            "Previsto": r.get("previsto") if r.get("previsto") is not None else "—",
            "Anterior": r.get("anterior") if r.get("anterior") is not None else "—",
            "Real": r.get("real") if r.get("real") is not None else "—",
            "Unidad": unidad or "—",
            "Criterio aplicado": criterio,
            "Lectura": r.get("impacto_mercado") or "⚪ Sin datos suficientes",
            "Puntaje": f"{score_val:+.2f}" if pd.notna(score_val) else "—",
            "Peso": f"{peso_val:.1f}x" if pd.notna(peso_val) else "—",
        })
    return pd.DataFrame(filas)


IMPACTO_COLOR = {"Muy Alto": "#f85149", "Alto": "#f0883e", "Medio": "#e3b341", "Bajo": "#8b949e"}

MESES_NOMBRE = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}


def _formato_mes(m):
    return "Todos" if m == "Todos" else MESES_NOMBRE[m]


# ==============================================================
#  LÓGICA (portada 1:1 de interpretarMacro / guardarRegistro de GAS)
# ==============================================================

def interpretar_macro(evento, real, previsto, anterior=None):
    info = INTERPRETACION_MACRO.get(evento)
    if not info:
        categoria = EVENTOS.get(evento, {}).get("categoria") if evento else None
        info = CATEGORIA_INTERPRETACION.get(categoria)

    vacio = {"divisas": "⚪ Sin interpretación", "bonos": "⚪ Sin interpretación",
             "acciones": "⚪ Sin interpretación", "oro": "⚪ Sin interpretación",
             "crypto": "⚪ Sin interpretación", "politica": "⚪ Sin interpretación",
             "riesgo": "⚪ Sin interpretación", "lectura": "No existe interpretación cargada para este evento."}
    if not info or real is None:
        return vacio

    # Si no hay sorpresa contra el previsto (o directamente no hay previsto
    # cargado), en vez de devolver "sin sorpresa" para todos los activos,
    # usamos la comparación contra el dato ANTERIOR como base de la
    # interpretación macro — así el dato dice algo útil siempre que haya
    # algo con qué compararlo, y solo queda mudo cuando de verdad no hay
    # ninguna referencia (ni previsto ni anterior).
    sin_sorpresa_previsto = previsto is None or real == previsto

    if sin_sorpresa_previsto:
        if anterior is not None and real != anterior:
            resultado = "mayor" if real > anterior else "menor"
            base = info.get(resultado, vacio)
            ajustado = dict(base)
            aviso = (
                "El dato salió en línea con lo previsto" if previsto is not None
                else "No hay dato de 'previsto' cargado para este evento"
            )
            ajustado["lectura"] = (
                f"{aviso}, sin sorpresa respecto al consenso, pero muestra una variación frente al "
                f"dato anterior. {base.get('lectura', '')} Nota: como no hubo sorpresa contra lo "
                "previsto, esta lectura macro se basa en la comparación contra el dato anterior "
                "(tendencia), no contra el consenso del mercado, y suele tener un impacto más "
                "moderado que una sorpresa real contra el previsto."
            )
            return ajustado

        # Ni previsto (con sorpresa) ni anterior (con variación) dan una
        # dirección: ahí sí no hay nada de qué agarrarse.
        en_linea = {campo: "⚪ Sin sorpresa vs. lo previsto ni variación vs. lo anterior" for campo in
                    ("divisas", "bonos", "acciones", "oro", "crypto", "politica", "riesgo")}
        en_linea["lectura"] = (
            "El dato no muestra sorpresa respecto a lo previsto ni variación respecto al dato "
            "anterior, así que por sí solo no aporta una dirección clara para el mercado."
        )
        return en_linea

    resultado = "mayor" if real > previsto else "menor"
    return info.get(resultado, vacio)


def _calcular_analisis(previsto, anterior, real, polaridad="directa"):
    hay_prev, hay_ant, hay_real = previsto is not None, anterior is not None, real is not None
    vs_previsto = vs_anterior = senal_prev = senal_ant = impacto_mercado = ""

    if hay_real and hay_prev:
        if real > previsto:   vs_previsto = "📈 Por encima del previsto"
        elif real < previsto: vs_previsto = "📉 Por debajo del previsto"
        else:                 vs_previsto = "➖ En línea con el previsto"

    if hay_real and hay_ant:
        if real > anterior:   vs_anterior = "📈 Subió vs. el dato anterior"
        elif real < anterior: vs_anterior = "📉 Bajó vs. el dato anterior"
        else:                 vs_anterior = "➖ Sin cambios vs. el anterior"

    if polaridad == "neutral":
        if vs_previsto:
            senal_prev = "⚪ SIN LECTURA DE POLARIDAD"
        if vs_anterior:
            senal_ant = "⚪ SIN LECTURA DE POLARIDAD"
        if hay_prev or hay_ant:
            impacto_mercado = "⚪ NEUTRO / EVENTO CUALITATIVO"
        return dict(vs_previsto=vs_previsto, vs_anterior=vs_anterior,
                    senal_previsto=senal_prev, senal_anterior=senal_ant,
                    impacto_mercado=impacto_mercado)

    signo = -1 if polaridad == "inversa" else 1

    if hay_real and hay_prev:
        diff = (real - previsto) * signo
        if diff > 0:   senal_prev = "🔺 POSITIVO"
        elif diff < 0: senal_prev = "🔻 NEGATIVO"
        else:          senal_prev = "⚖️ NEUTRO"

    if hay_real and hay_ant:
        diff = (real - anterior) * signo
        if diff > 0:   senal_ant = "📈 TENDENCIA POSITIVA"
        elif diff < 0: senal_ant = "📉 TENDENCIA NEGATIVA"
        else:          senal_ant = "➡️ LATERAL"

    mej_p = hay_real and hay_prev and (real - previsto) * signo > 0
    mej_a = hay_real and hay_ant and (real - anterior) * signo > 0
    peor_p = hay_real and hay_prev and (real - previsto) * signo < 0
    peor_a = hay_real and hay_ant and (real - anterior) * signo < 0
    empate_p = hay_real and hay_prev and real == previsto

    if hay_prev or hay_ant:
        if empate_p:
            impacto_mercado = "⚪ NEUTRO PARA EL MERCADO (sin sorpresa vs. lo previsto)"
        elif mej_p and mej_a:       impacto_mercado = "🟢 BUEN DATO PARA EL MERCADO"
        elif peor_p and peor_a:     impacto_mercado = "🔴 MAL DATO PARA EL MERCADO"
        elif mej_p or mej_a:        impacto_mercado = "🟡 BUEN DATO PARCIAL"
        elif peor_p or peor_a:      impacto_mercado = "🟠 MAL DATO PARCIAL"
        else:                       impacto_mercado = "⚪ NEUTRO PARA EL MERCADO"

    return dict(vs_previsto=vs_previsto, vs_anterior=vs_anterior,
                senal_previsto=senal_prev, senal_anterior=senal_ant,
                impacto_mercado=impacto_mercado)


def _impacto_estilo(impacto_mercado):
    if "BUEN DATO PARA" in impacto_mercado:   return "#C6EFCE", "#276221"
    if "MAL DATO PARA" in impacto_mercado:    return "#FFC7CE", "#9C0006"
    if "BUEN DATO PAR" in impacto_mercado:    return "#FFEB9C", "#7F5500"
    if "MAL DATO PAR" in impacto_mercado:     return "#FFD966", "#7F4F00"
    return "#21262d", "#8b949e"


def _es_admin(user_email):
    return bool(user_email) and user_email.strip().lower() == ADMIN_EMAIL.strip().lower()


def _renglon_macro(label, texto):
    return (f'<div style="background:#0d1117;border:1px solid #21262d;border-radius:8px;'
            f'padding:10px 12px;min-height:54px">'
            f'<div style="font-size:10px;color:#6b7d9a;text-transform:uppercase;'
            f'letter-spacing:.5px;margin-bottom:4px">{label}</div>'
            f'<div style="font-size:13px;font-weight:700;color:#e6edf3">{texto or "⚪ Sin interpretación"}</div></div>')


def _render_macro_grid(macro):
    st.markdown("###### 🔎 Por qué es bueno o malo, y para qué activos")
    g1, g2, g3, g4 = st.columns(4)
    with g1:
        st.markdown(_renglon_macro("Divisas", macro.get("divisas")), unsafe_allow_html=True)
    with g2:
        st.markdown(_renglon_macro("Bonos", macro.get("bonos")), unsafe_allow_html=True)
    with g3:
        st.markdown(_renglon_macro("Acciones / Índices", macro.get("acciones")), unsafe_allow_html=True)
    with g4:
        st.markdown(_renglon_macro("Oro", macro.get("oro")), unsafe_allow_html=True)

    g5, g6, g7 = st.columns(3)
    with g5:
        st.markdown(_renglon_macro("Criptomonedas", macro.get("crypto") or macro.get("criptomonedas")), unsafe_allow_html=True)
    with g6:
        st.markdown(_renglon_macro("Política Monetaria", macro.get("politica") or macro.get("politica_monetaria")), unsafe_allow_html=True)
    with g7:
        st.markdown(_renglon_macro("Régimen de Mercado", macro.get("riesgo") or macro.get("regimen_mercado")), unsafe_allow_html=True)

    lectura = macro.get("lectura") or macro.get("lectura_macro")
    if lectura:
        st.info(lectura)


# ==============================================================
#  ACCESO A SUPABASE
# ==============================================================

def _guardar_registro(supabase, datos, user_id):
    real, previsto, anterior = datos.get("real"), datos.get("previsto"), datos.get("anterior")
    polaridad = EVENTOS.get(datos["evento"], {}).get("polaridad", "directa")
    analisis = _calcular_analisis(previsto, anterior, real, polaridad)
    macro = interpretar_macro(datos["evento"], real, previsto, anterior)
    row = {
        "user_id": user_id,
        "fecha": str(datos["fecha"]),
        "pais": datos["pais"],
        "evento": datos["evento"],
        "relevancia": datos.get("relevancia", ""),
        "previsto": previsto, "anterior": anterior, "real": real,
        "unidad": datos.get("unidad", ""),
        "vs_previsto": analisis["vs_previsto"], "vs_anterior": analisis["vs_anterior"],
        "senal_previsto": analisis["senal_previsto"], "senal_anterior": analisis["senal_anterior"],
        "impacto_mercado": analisis["impacto_mercado"],
        "divisas": macro["divisas"], "bonos": macro["bonos"], "acciones": macro["acciones"],
        "oro": macro["oro"], "criptomonedas": macro["crypto"],
        "politica_monetaria": macro["politica"], "regimen_mercado": macro["riesgo"],
        "lectura_macro": macro["lectura"], "notas": datos.get("notas", ""),
    }
    supabase.table(TABLA_REGISTRO).insert(row).execute()
    return analisis, macro


def _actualizar_registro(supabase, registro_id, datos):
    """Recalcula análisis + interpretación macro con los valores nuevos
    y actualiza la fila existente en Supabase (usado por la edición de
    eventos ya cargados, desde Historial)."""
    real, previsto, anterior = datos.get("real"), datos.get("previsto"), datos.get("anterior")
    polaridad = EVENTOS.get(datos["evento"], {}).get("polaridad", "directa")
    analisis = _calcular_analisis(previsto, anterior, real, polaridad)
    macro = interpretar_macro(datos["evento"], real, previsto, anterior)
    row = {
        "fecha": str(datos["fecha"]),
        "pais": datos["pais"],
        "evento": datos["evento"],
        "relevancia": EVENTOS.get(datos["evento"], {}).get("impacto", datos.get("relevancia", "")),
        "previsto": previsto, "anterior": anterior, "real": real,
        "unidad": datos.get("unidad", ""),
        "vs_previsto": analisis["vs_previsto"], "vs_anterior": analisis["vs_anterior"],
        "senal_previsto": analisis["senal_previsto"], "senal_anterior": analisis["senal_anterior"],
        "impacto_mercado": analisis["impacto_mercado"],
        "divisas": macro["divisas"], "bonos": macro["bonos"], "acciones": macro["acciones"],
        "oro": macro["oro"], "criptomonedas": macro["crypto"],
        "politica_monetaria": macro["politica"], "regimen_mercado": macro["riesgo"],
        "lectura_macro": macro["lectura"], "notas": datos.get("notas", ""),
    }
    supabase.table(TABLA_REGISTRO).update(row).eq("id", registro_id).execute()
    return analisis, macro


def _borrar_registro(supabase, registro_id):
    supabase.table(TABLA_REGISTRO).delete().eq("id", registro_id).execute()


@st.cache_data(ttl=120, show_spinner=False)
def _obtener_registros(_supabase, limite=None, fecha_desde=None, fecha_hasta=None):
    """Trae registros paginando con .range() (Supabase/PostgREST limita
    cada request a ~1000 filas, así que se piden de a tandas hasta
    agotarlos, sin importar cuántos haya en total).

    - limite: si se pasa un número, corta ahí el total acumulado.
      Si se deja en None (default), trae todo.
    - fecha_desde / fecha_hasta: si se pasan (objetos date), filtran
      directo en la query de Supabase (columna 'fecha'), así no hace
      falta traer registros que después se van a descartar en pandas.
      Muy útil cuando la tabla crece mucho.
    """
    PAGINA = 1000
    todas = []
    desde = 0
    while True:
        hasta = desde + PAGINA - 1
        q = (_supabase.table(TABLA_REGISTRO).select("*")
             .order("created_at", desc=True))
        if fecha_desde:
            q = q.gte("fecha", str(fecha_desde))
        if fecha_hasta:
            q = q.lte("fecha", str(fecha_hasta))
        res = q.range(desde, hasta).execute()

        lote = res.data or []
        todas.extend(lote)

        if limite is not None and len(todas) >= limite:
            return todas[:limite]

        if len(lote) < PAGINA:
            break  # ya no hay más filas
        desde += PAGINA

    return todas


def _limpiar_cache_registros():
    """Limpia TODAS las cachés que dependen de la tabla de registros.
    Usar esto (y no clear() sobre una sola caché) después de cualquier
    insert/update/delete, porque Historial lee de _obtener_registros
    directamente mientras que Perfil de País y País vs País leen de
    _df_registros_procesado — si solo se limpia una, la otra pantalla
    sigue mostrando datos viejos hasta que expire el TTL de 2 minutos.
    Este bug fue el motivo por el que un evento recién editado/corregido
    podía seguir viéndose con el valor anterior en Historial."""
    _obtener_registros.clear()
    _df_registros_procesado.clear()


def _recalcular_fila(row):
    """A partir de una fila ya guardada en Supabase, vuelve a calcular
    el análisis (vs. previsto/anterior, señales, impacto de mercado) y
    la interpretación macro (divisas, bonos, acciones, oro, cripto,
    política monetaria, régimen de mercado, lectura) con la lógica
    VIGENTE del código. Devuelve (cambio: bool, campos_nuevos: dict) —
    cambio es True si al menos un campo calculado difiere de lo que
    hoy está guardado en la base (por ejemplo, porque se corrigió un
    bug de cálculo después de haber cargado el evento)."""
    evento = row.get("evento")
    real, previsto, anterior = row.get("real"), row.get("previsto"), row.get("anterior")
    polaridad = EVENTOS.get(evento, {}).get("polaridad", "directa")

    analisis = _calcular_analisis(previsto, anterior, real, polaridad)
    macro = interpretar_macro(evento, real, previsto, anterior)

    nuevo = {
        "vs_previsto": analisis["vs_previsto"], "vs_anterior": analisis["vs_anterior"],
        "senal_previsto": analisis["senal_previsto"], "senal_anterior": analisis["senal_anterior"],
        "impacto_mercado": analisis["impacto_mercado"],
        "divisas": macro["divisas"], "bonos": macro["bonos"], "acciones": macro["acciones"],
        "oro": macro["oro"], "criptomonedas": macro["crypto"],
        "politica_monetaria": macro["politica"], "regimen_mercado": macro["riesgo"],
        "lectura_macro": macro["lectura"],
    }
    cambio = any((row.get(k) or "") != (v or "") for k, v in nuevo.items())
    return cambio, nuevo


def _recalcular_todos_los_registros(supabase, progreso_cb=None):
    """Recorre TODOS los eventos ya guardados, recalcula análisis +
    interpretación macro con la lógica vigente, y actualiza en Supabase
    ÚNICAMENTE los que cambiaron respecto a lo guardado — pensado para
    correr una sola vez después de corregir un bug de cálculo, en lugar
    de tener que editar evento por evento a mano.

    progreso_cb(hecho, total), si se pasa, se llama después de procesar
    cada fila para poder mostrar una barra de progreso en la UI.

    Devuelve (total_revisados, total_actualizados)."""
    filas = _obtener_registros(supabase)
    total = len(filas)
    actualizados = 0
    for i, row in enumerate(filas):
        cambio, nuevo = _recalcular_fila(row)
        if cambio:
            supabase.table(TABLA_REGISTRO).update(nuevo).eq("id", row["id"]).execute()
            actualizados += 1
        if progreso_cb:
            progreso_cb(i + 1, total)
    return total, actualizados

def _encontrar_duplicados(supabase):
    """Agrupa todos los registros por (fecha, pais, evento) y devuelve
    los ids a borrar cuando hay más de un registro para la misma
    combinación — se conserva el más reciente (por created_at) y se
    marcan los demás para eliminar. Devuelve (ids_a_borrar, detalle)."""
    filas = _obtener_registros(supabase)
    grupos = {}
    for row in filas:
        clave = (row.get("fecha"), row.get("pais"), row.get("evento"))
        grupos.setdefault(clave, []).append(row)

    ids_a_borrar = []
    detalle = []
    for (fecha, pais, evento), filas_grupo in grupos.items():
        if len(filas_grupo) > 1:
            filas_ordenadas = sorted(
                filas_grupo, key=lambda r: r.get("created_at") or "", reverse=True
            )
            conservar = filas_ordenadas[0]
            borrar = filas_ordenadas[1:]
            ids_a_borrar.extend([r["id"] for r in borrar])
            detalle.append({
                "Fecha": fecha, "País": pais, "Evento": evento,
                "Copias encontradas": len(filas_grupo),
                "Se eliminan": len(borrar),
                "Se conserva (más reciente)": conservar.get("created_at", "—"),
            })
    detalle.sort(key=lambda d: (d["Fecha"] or "", d["País"] or ""), reverse=True)
    return ids_a_borrar, detalle


def _borrar_duplicados(supabase, ids_a_borrar):
    """Borra en Supabase la lista de ids pasada, en lotes."""
    LOTE = 200
    total = 0
    for i in range(0, len(ids_a_borrar), LOTE):
        lote = ids_a_borrar[i:i + LOTE]
        supabase.table(TABLA_REGISTRO).delete().in_("id", lote).execute()
        total += len(lote)
    return total

def _borrar_toda_la_base(supabase):
    """Elimina TODOS los registros de la tabla de eventos económicos.
    Operación irreversible — pensada para poder recargar todo de cero."""
    # Supabase/PostgREST exige un filtro en el delete; con neq a un id
    # imposible (0) se borran todas las filas sin excepción.
    supabase.table(TABLA_REGISTRO).delete().neq("id", 0).execute()

@st.cache_data(ttl=120, show_spinner=False)
def _obtener_noticias(_supabase, limite=100):
    res = (_supabase.table(TABLA_NOTICIAS).select("*")
           .order("created_at", desc=True).limit(limite).execute())
    return res.data or []


def _guardar_noticia(supabase, titulo, contenido, categoria, fecha_noticia, user_id, user_email):
    supabase.table(TABLA_NOTICIAS).insert({
        "autor_id": user_id, "autor_email": user_email,
        "titulo": titulo.strip(), "contenido": (contenido or "").strip(),
        "categoria": (categoria or "").strip(),
        "fecha_noticia": str(fecha_noticia) if fecha_noticia else None,
    }).execute()


def _borrar_noticia(supabase, noticia_id):
    supabase.table(TABLA_NOTICIAS).delete().eq("id", noticia_id).execute()


# ==============================================================
#  RENDER — TAB REGISTRAR
# ==============================================================

def _tab_registrar(supabase, user_id, es_admin):
    if not es_admin:
        st.info("🔒 Solo el administrador puede registrar eventos económicos. "
                "Podés consultar todos los registros ya cargados en la pestaña **Historial**.")
        return

    c1, c2 = st.columns(2)
    with c1:
        fecha = st.date_input("📅 Fecha", value=date.today(), key="cal_fecha")
    with c2:
        pais = st.selectbox("🌍 País", [""] + PAISES, key="cal_pais")

    evento = st.selectbox("📊 Evento económico", [""] + list(EVENTOS.keys()), key="cal_evento")
    info_evento = EVENTOS.get(evento)
    if info_evento:
        col_badge = IMPACTO_COLOR.get(info_evento["impacto"], "#8b949e")
        st.markdown(
            f'<span style="display:inline-block;padding:3px 12px;border-radius:12px;'
            f'font-size:12px;font-weight:700;background:{col_badge}22;color:{col_badge};'
            f'border:1px solid {col_badge}55">{info_evento["impacto"]} · {info_evento["categoria"]}</span>',
            unsafe_allow_html=True,
        )

    n1, n2, n3 = st.columns(3)
    with n1:
        previsto = st.number_input("PREVISTO", value=None, format="%.4f", key="cal_previsto", placeholder="0.0")
    with n2:
        anterior = st.number_input("ANTERIOR", value=None, format="%.4f", key="cal_anterior", placeholder="0.0")
    with n3:
        real = st.number_input("REAL ★", value=None, format="%.4f", key="cal_real", placeholder="0.0")

    u1, u2 = st.columns([1, 2])
    with u1:
        unidad = st.selectbox("📐 Unidad", ["%", "pts", "k", "M", "B", "USD", "índice", "otro"], key="cal_unidad")
    with u2:
        notas = st.text_input("💬 Notas", key="cal_notas", placeholder="Observaciones adicionales...")

    st.markdown("#### 📈 Análisis automático")
    polaridad_evento = info_evento.get("polaridad", "directa") if info_evento else "directa"
    analisis = _calcular_analisis(previsto, anterior, real, polaridad_evento)

    if info_evento and info_evento.get("polaridad") == "inversa":
        st.caption("↕️ Polaridad **inversa**: un dato por encima de lo previsto se lee como negativo para la economía (ej. desempleo, inflación, tasas).")
    elif info_evento and info_evento.get("polaridad") == "neutral":
        st.caption("⚪ Evento cualitativo: no se emite juicio automático de bueno/malo.")

    ac1, ac2, ac3, ac4 = st.columns(4)
    for col, label, val in [
        (ac1, "Real vs Previsto", analisis["vs_previsto"] or "—"),
        (ac2, "Real vs Anterior", analisis["vs_anterior"] or "—"),
        (ac3, "Señal (vs Prev.)", analisis["senal_previsto"] or "—"),
        (ac4, "Señal (vs Ant.)", analisis["senal_anterior"] or "—"),
    ]:
        with col:
            st.markdown(
                f'<div style="background:#0d1117;border:1px solid #21262d;border-radius:8px;'
                f'padding:10px 12px;min-height:58px">'
                f'<div style="font-size:10px;color:#6b7d9a;text-transform:uppercase;'
                f'letter-spacing:.5px;margin-bottom:4px">{label}</div>'
                f'<div style="font-size:13px;font-weight:700;color:#e6edf3">{val}</div></div>',
                unsafe_allow_html=True,
            )

    impacto = analisis["impacto_mercado"] or "—"
    bg, fg = _impacto_estilo(impacto)
    st.markdown(
        f'<div style="margin-top:10px;border-radius:10px;padding:14px;text-align:center;'
        f'background:{bg};border:1px solid {fg}55">'
        f'<div style="font-size:11px;color:{fg};opacity:.8">Impacto para el Mercado</div>'
        f'<div style="font-size:16px;font-weight:800;color:{fg}">{impacto}</div></div>',
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    macro = interpretar_macro(evento, real, previsto, anterior) if evento else interpretar_macro(None, None, None)
    _render_macro_grid(macro)

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    b1, b2 = st.columns(2)
    with b1:
        if st.button("🗑️ Limpiar", use_container_width=True, key="cal_btn_limpiar"):
            for k in ["cal_pais", "cal_evento", "cal_previsto", "cal_anterior", "cal_real", "cal_notas"]:
                st.session_state.pop(k, None)
            st.rerun()
    with b2:
        if st.button("💾 Registrar", type="primary", use_container_width=True, key="cal_btn_guardar"):
            if not pais or not evento:
                st.warning("⚠️ Completá País y Evento.")
            else:
                datos = dict(fecha=fecha, pais=pais, evento=evento,
                             relevancia=info_evento["impacto"] if info_evento else "",
                             previsto=previsto, anterior=anterior, real=real,
                             unidad=unidad, notas=notas)
                try:
                    _guardar_registro(supabase, datos, user_id)
                    _limpiar_cache_registros()
                    st.success("✅ Registro guardado.")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error al guardar: {e}")


    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("### 🛠️ Mantenimiento")

    # ── Recalcular todos los eventos ──
    with st.expander("🔄 Recalcular todos los eventos"):
        st.caption(
            "Vuelve a calcular el análisis (vs. previsto/anterior, señales, impacto de mercado) "
            "y la interpretación macro (divisas, bonos, acciones, oro, cripto, política monetaria, "
            "régimen de mercado) de **todos** los eventos ya cargados, con la lógica que está hoy "
            "en el código. Útil después de corregir un bug de cálculo, para no tener que entrar "
            "evento por evento a Editar → Guardar. Solo se actualiza en la base lo que realmente "
            "cambió; los eventos ya correctos quedan intactos y esto no borra ni modifica Fecha, "
            "País, Evento, Previsto, Anterior, Real ni Notas."
        )
        if st.button("🔄 Recalcular todos los eventos ahora", key="cal_reg_btn_recalcular_todo"):
            barra = st.progress(0.0, text="Recalculando eventos...")

            def _cb(hecho, total):
                frac = hecho / total if total else 1.0
                barra.progress(frac, text=f"Recalculando eventos... {hecho}/{total}")

            try:
                total, actualizados = _recalcular_todos_los_registros(supabase, progreso_cb=_cb)
                barra.empty()
                _limpiar_cache_registros()
                if actualizados:
                    st.success(
                        f"✅ Listo: se revisaron {total} evento(s) y se corrigieron **{actualizados}**, "
                        "que tenían una lectura distinta a la que da la lógica actual."
                    )
                else:
                    st.info(f"✅ Se revisaron {total} evento(s) y ya estaban todos al día.")
                st.rerun()
            except Exception as e:
                barra.empty()
                st.error(f"❌ Error al recalcular: {e}")

    # ── Borrar duplicados ──
    with st.expander("🧹 Borrar eventos duplicados"):
        st.caption(
            "Busca registros que compartan la misma **Fecha + País + Evento** y, cuando encuentra "
            "más de uno, muestra una vista previa antes de borrar nada. Al confirmar, conserva el "
            "registro más reciente de cada grupo (el de carga más nueva) y elimina el resto."
        )
        if st.button("🔍 Buscar duplicados", key="cal_reg_btn_buscar_dup"):
            with st.spinner("Buscando duplicados..."):
                ids_a_borrar, detalle = _encontrar_duplicados(supabase)
            st.session_state["cal_reg_dup_ids"] = ids_a_borrar
            st.session_state["cal_reg_dup_detalle"] = detalle

        ids_a_borrar = st.session_state.get("cal_reg_dup_ids")
        detalle = st.session_state.get("cal_reg_dup_detalle")

        if ids_a_borrar is not None:
            if not ids_a_borrar:
                st.success("✅ No se encontraron eventos duplicados.")
            else:
                st.warning(
                    f"⚠️ Se encontraron **{len(detalle)}** grupo(s) con duplicados, "
                    f"totalizando **{len(ids_a_borrar)}** registro(s) a eliminar:"
                )
                st.dataframe(pd.DataFrame(detalle), use_container_width=True, hide_index=True)

                bd1, bd2 = st.columns(2)
                with bd1:
                    if st.button(
                        f"🗑️ Confirmar y eliminar {len(ids_a_borrar)} duplicado(s)",
                        type="primary", use_container_width=True, key="cal_reg_btn_confirmar_dup",
                    ):
                        try:
                            n = _borrar_duplicados(supabase, ids_a_borrar)
                            _limpiar_cache_registros()
                            st.session_state.pop("cal_reg_dup_ids", None)
                            st.session_state.pop("cal_reg_dup_detalle", None)
                            st.success(f"✅ Se eliminaron {n} registro(s) duplicado(s).")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error al eliminar duplicados: {e}")
                with bd2:
                    if st.button("✖️ Cancelar", use_container_width=True, key="cal_reg_btn_cancelar_dup"):
                        st.session_state.pop("cal_reg_dup_ids", None)
                        st.session_state.pop("cal_reg_dup_detalle", None)
                        st.rerun()

    
    # ── Borrar TODA la base (reinicio total) ──
    with st.expander("☠️ Borrar TODA la base de datos"):
        st.error(
            "⚠️ Esto elimina **absolutamente todos** los eventos económicos cargados hasta "
            "ahora, sin posibilidad de deshacerlo. Usalo solo si querés arrancar de cero para "
            "recargar todo el historial desde archivos nuevos."
        )
        cantidad_actual = len(_obtener_registros(supabase))
        st.caption(f"Actualmente hay **{cantidad_actual}** registro(s) en la base.")

        confirmacion = st.text_input(
            "Para confirmar, escribí exactamente: BORRAR TODO",
            key="cal_reg_confirm_borrar_todo",
            placeholder="BORRAR TODO",
        )

        if st.button(
            "☠️ Eliminar toda la base de datos",
            type="primary", key="cal_reg_btn_borrar_todo",
            disabled=(confirmacion.strip() != "BORRAR TODO"),
        ):
            try:
                _borrar_toda_la_base(supabase)
                _limpiar_cache_registros()
                st.session_state.pop("cal_reg_confirm_borrar_todo", None)
                st.success("✅ Se eliminó toda la base de eventos. Ya podés recargar todo de nuevo.")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error al borrar la base: {e}")

# ==============================================================
#  CARGA MASIVA
#  Permite subir muchos eventos de una sola vez desde un Excel/CSV,
#  con plantilla descargable (incluye hojas de referencia con los
#  países y eventos válidos), validación fila por fila antes de
#  tocar la base, y un insert único a Supabase.
# ==============================================================

COLUMNAS_PLANTILLA = ["fecha", "pais", "evento", "previsto", "anterior", "real", "unidad", "notas"]


def _generar_plantilla_excel():
    """Arma el .xlsx de plantilla con una fila de ejemplo y dos hojas
    de referencia (países y eventos válidos) para copiar/pegar."""
    ejemplo = pd.DataFrame([
        {
            "fecha": "15/01/2026",
            "pais": "Estados Unidos",
            "evento": "IPC (inflación general)",
            "previsto": 3.1,
            "anterior": 3.0,
            "real": "",
            "unidad": "%",
            "notas": "",
        }
    ], columns=COLUMNAS_PLANTILLA)

    ref_paises = pd.DataFrame({"Países válidos": PAISES})
    ref_eventos = pd.DataFrame({
        "Eventos válidos": list(EVENTOS.keys()),
        "Categoría": [EVENTOS[e]["categoria"] for e in EVENTOS],
        "Impacto": [EVENTOS[e]["impacto"] for e in EVENTOS],
        "Unidad sugerida": [EVENTOS[e]["unidad"] for e in EVENTOS],
        "Polaridad": [EVENTOS[e]["polaridad"] for e in EVENTOS],
    })

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        ejemplo.to_excel(writer, sheet_name="Carga", index=False)
        ref_paises.to_excel(writer, sheet_name="Países válidos", index=False)
        ref_eventos.to_excel(writer, sheet_name="Eventos válidos", index=False)

        wb = writer.book
        fmt_header = wb.add_format({"bold": True, "bg_color": "#0d1117", "font_color": "#e6edf3"})

        ws = writer.sheets["Carga"]
        for col_num, col_name in enumerate(COLUMNAS_PLANTILLA):
            ws.write(0, col_num, col_name, fmt_header)
            ws.set_column(col_num, col_num, 24)

        for hoja in ("Países válidos", "Eventos válidos"):
            ws2 = writer.sheets[hoja]
            ws2.set_column(0, 4, 26)

    buffer.seek(0)
    return buffer


def _parsear_fecha_masiva(valor):
    if pd.isna(valor) or str(valor).strip() == "":
        return None, "Fecha vacía"
    if isinstance(valor, datetime):
        return valor.date(), None
    if isinstance(valor, date):
        return valor, None
    texto = str(valor).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto, fmt).date(), None
        except ValueError:
            continue
    return None, f"Formato de fecha no reconocido: '{texto}'"


def _num_o_none(valor):
    """None si viene vacío, 'ERROR' si viene algo no numérico,
    o el float correspondiente."""
    if pd.isna(valor) or str(valor).strip() == "":
        return None
    try:
        return float(str(valor).replace(",", "."))
    except ValueError:
        return "ERROR"

import re

_SUFIJO_MES_RE = re.compile(
    r"\s*\((ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)\.?\)\s*$",
    re.IGNORECASE,
)


def _normalizar_evento_masivo(nombre_crudo):
    """Devuelve el nombre de evento tal como está en EVENTOS, probando:
    1) el nombre tal cual viene en el archivo
    2) el nombre sin un sufijo de mes pegado al final, tipo " (Mar)"
       — típico de calendarios económicos que traen el mes incrustado
       en el nombre del evento en vez de en una columna aparte.
    3) si tampoco está en EVENTOS pero SÍ está en INTERPRETACION_MACRO
       (evento con lectura macro cargada pero nunca dado de alta en
       EVENTOS con categoría/impacto/polaridad), se acepta igual con
       una categoría/impacto genéricos de respaldo.

    Devuelve (nombre_final, info_evento) o (None, None) si no matchea
    de ninguna forma.
    """
    nombre = (nombre_crudo or "").strip()
    if nombre in EVENTOS:
        return nombre, EVENTOS[nombre]

    sin_mes = _SUFIJO_MES_RE.sub("", nombre).strip()
    if sin_mes and sin_mes in EVENTOS:
        return sin_mes, EVENTOS[sin_mes]

    # Existe la lectura macro pero nunca se dio de alta en EVENTOS —
    # lo aceptamos con valores de respaldo en vez de rechazarlo.
    for candidato in (nombre, sin_mes):
        if candidato and candidato in INTERPRETACION_MACRO:
            info_respaldo = {"categoria": "Otros", "unidad": "", "impacto": "Medio", "polaridad": "directa"}
            return candidato, info_respaldo

    return None, None
    
def _validar_fila_masiva(row):
    """Valida una fila del archivo subido. Devuelve (errores, datos)
    donde datos es el dict listo para _guardar_registro / _guardar_registros_masivo,
    o None si hay errores."""
    errores = []

    fecha, err_fecha = _parsear_fecha_masiva(row.get("fecha"))
    if err_fecha:
        errores.append(err_fecha)

    pais = str(row.get("pais") or "").strip()
    if not pais:
        errores.append("País vacío")
    elif pais not in PAISES:
        errores.append(f"País no reconocido: '{pais}'")

    evento_crudo = str(row.get("evento") or "").strip()
    if not evento_crudo:
        errores.append("Evento vacío")
        evento, info_evento_ok = None, None
    else:
        evento, info_evento_ok = _normalizar_evento_masivo(evento_crudo)
        if evento is None:
            errores.append(f"Evento no reconocido: '{evento_crudo}'")

    previsto = _num_o_none(row.get("previsto"))
    anterior = _num_o_none(row.get("anterior"))
    real = _num_o_none(row.get("real"))
    for nombre, val in [("previsto", previsto), ("anterior", anterior), ("real", real)]:
        if val == "ERROR":
            errores.append(f"Valor numérico inválido en '{nombre}'")

    unidad = str(row.get("unidad") or "").strip()
    notas = str(row.get("notas") or "").strip()

    if errores:
        return errores, None

    datos = dict(
        fecha=fecha,
        pais=pais,
        evento=evento,
        relevancia=info_evento_ok["impacto"],
        previsto=None if previsto == "ERROR" else previsto,
        anterior=None if anterior == "ERROR" else anterior,
        real=None if real == "ERROR" else real,
        unidad=unidad or info_evento_ok["unidad"],
        notas=notas,
    )
    return [], datos


def _guardar_registros_masivo(supabase, lista_datos, user_id):
    """Igual que _guardar_registro pero arma todas las filas primero
    y hace un insert por lote a Supabase (mucho más rápido que insertar
    de a una cuando son decenas o cientos de eventos)."""
    filas = []
    for datos in lista_datos:
        real, previsto, anterior = datos.get("real"), datos.get("previsto"), datos.get("anterior")
        polaridad = EVENTOS.get(datos["evento"], {}).get("polaridad", "directa")
        analisis = _calcular_analisis(previsto, anterior, real, polaridad)
        macro = interpretar_macro(datos["evento"], real, previsto, anterior)
        filas.append({
            "user_id": user_id,
            "fecha": str(datos["fecha"]),
            "pais": datos["pais"],
            "evento": datos["evento"],
            "relevancia": datos.get("relevancia", ""),
            "previsto": previsto, "anterior": anterior, "real": real,
            "unidad": datos.get("unidad", ""),
            "vs_previsto": analisis["vs_previsto"], "vs_anterior": analisis["vs_anterior"],
            "senal_previsto": analisis["senal_previsto"], "senal_anterior": analisis["senal_anterior"],
            "impacto_mercado": analisis["impacto_mercado"],
            "divisas": macro["divisas"], "bonos": macro["bonos"], "acciones": macro["acciones"],
            "oro": macro["oro"], "criptomonedas": macro["crypto"],
            "politica_monetaria": macro["politica"], "regimen_mercado": macro["riesgo"],
            "lectura_macro": macro["lectura"], "notas": datos.get("notas", ""),
        })

    if not filas:
        return 0

    # Se trocea en lotes de 500 por si algún día subís miles de filas
    # de una sola vez y el payload queda muy pesado.
    LOTE = 500
    for i in range(0, len(filas), LOTE):
        supabase.table(TABLA_REGISTRO).insert(filas[i:i + LOTE]).execute()

    return len(filas)


def _tab_carga_masiva(supabase, user_id, es_admin):
    if not es_admin:
        st.info("🔒 Solo el administrador puede hacer carga masiva de eventos.")
        return

    st.caption(
        "Cargá muchos eventos económicos de una sola vez desde un Excel o CSV. "
        "Descargá la plantilla, completala (una fila por evento) y subila acá abajo. "
        "Antes de guardar nada te muestro una vista previa con los errores detectados, "
        "para que puedas corregir el archivo y volver a subirlo."
    )

    st.download_button(
        "⬇️ Descargar plantilla (Excel)",
        data=_generar_plantilla_excel(),
        file_name="plantilla_carga_masiva_calendario.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="cal_masiva_plantilla",
    )

    st.caption(
        "Columnas obligatorias: **fecha** (DD/MM/AAAA), **pais**, **evento**. "
        "Opcionales: **previsto**, **anterior**, **real**, **unidad**, **notas**. "
        "El país y el evento tienen que coincidir EXACTO con las hojas "
        "*Países válidos* / *Eventos válidos* de la plantilla — de ahí podés "
        "copiar y pegar los nombres para evitar errores de tipeo."
    )

    archivo = st.file_uploader(
        "📤 Subir archivo (.xlsx o .csv)", type=["xlsx", "csv"], key="cal_masiva_uploader"
    )
    if archivo is None:
        return

    try:
        if archivo.name.lower().endswith(".csv"):
            df_masivo = pd.read_csv(archivo)
        else:
            df_masivo = pd.read_excel(archivo, sheet_name=0)
    except Exception as e:
        st.error(f"❌ No pude leer el archivo: {e}")
        return

    faltantes = [c for c in COLUMNAS_PLANTILLA if c not in df_masivo.columns]
    if faltantes:
        st.error(f"❌ Al archivo le faltan estas columnas obligatorias: {', '.join(faltantes)}")
        return

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    st.markdown(f"#### 🔍 Vista previa — {len(df_masivo)} fila(s) detectadas")

    filas_ok, filas_error = [], []
    for idx, row in df_masivo.iterrows():
        errores, datos = _validar_fila_masiva(row)
        if errores:
            filas_error.append({"Fila (Excel)": idx + 2, "Errores": "; ".join(errores)})
        else:
            filas_ok.append(datos)

    c1, c2 = st.columns(2)
    c1.metric("✅ Filas válidas", len(filas_ok))
    c2.metric("❌ Filas con error", len(filas_error))

    if filas_error:
        st.warning(
            "Estas filas NO se van a importar hasta que corrijas el archivo original "
            "y lo vuelvas a subir (la numeración de fila corresponde a la planilla, "
            "contando el encabezado como fila 1):"
        )
        st.dataframe(pd.DataFrame(filas_error), use_container_width=True, hide_index=True)

    if filas_ok:
        vista = pd.DataFrame([
            {
                "Fecha": d["fecha"], "País": d["pais"], "Evento": d["evento"],
                "Previsto": d["previsto"], "Anterior": d["anterior"], "Real": d["real"],
                "Unidad": d["unidad"], "Notas": d["notas"],
            }
            for d in filas_ok
        ])
        st.markdown("##### Filas listas para importar")
        st.dataframe(vista, use_container_width=True, hide_index=True)

        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
        if st.button(
            f"💾 Confirmar e importar {len(filas_ok)} evento(s)",
            type="primary", use_container_width=True, key="cal_masiva_btn_confirmar",
        ):
            try:
                n = _guardar_registros_masivo(supabase, filas_ok, user_id)
                _limpiar_cache_registros()
                st.success(f"✅ Se importaron {n} evento(s) correctamente.")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error al importar: {e}")
    else:
        st.info("No hay filas válidas para importar todavía.")


# ==============================================================
#  RENDER — TAB CALENDARIO ECONÓMICO (solo lectura para no-admin;
#  el admin puede además editar o eliminar cada registro)
# ==============================================================

def _form_editar_registro(supabase, row):
    """Formulario de edición para un registro existente. Vive dentro
    del expander de Historial, debajo del detalle del evento. Al
    guardar, recalcula análisis + interpretación macro y refresca."""
    registro_id = row["id"]
    key_pref = f"cal_edit_{registro_id}"

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    st.markdown("###### ✏️ Editar este evento")

    e1, e2 = st.columns(2)
    with e1:
        try:
            fecha_actual = datetime.strptime(str(row.get("fecha")), "%Y-%m-%d").date()
        except Exception:
            fecha_actual = date.today()
        fecha_edit = st.date_input("📅 Fecha", value=fecha_actual, key=f"{key_pref}_fecha")
    with e2:
        pais_actual = row.get("pais") or ""
        idx_pais = PAISES.index(pais_actual) if pais_actual in PAISES else 0
        pais_edit = st.selectbox("🌍 País", PAISES, index=idx_pais, key=f"{key_pref}_pais")

    eventos_lista = list(EVENTOS.keys())
    evento_actual = row.get("evento") or ""
    idx_evento = eventos_lista.index(evento_actual) if evento_actual in eventos_lista else 0
    evento_edit = st.selectbox("📊 Evento económico", eventos_lista, index=idx_evento, key=f"{key_pref}_evento")

    n1, n2, n3 = st.columns(3)
    with n1:
        previsto_edit = st.number_input("PREVISTO", value=row.get("previsto"), format="%.4f", key=f"{key_pref}_previsto")
    with n2:
        anterior_edit = st.number_input("ANTERIOR", value=row.get("anterior"), format="%.4f", key=f"{key_pref}_anterior")
    with n3:
        real_edit = st.number_input("REAL ★", value=row.get("real"), format="%.4f", key=f"{key_pref}_real")

    u1, u2 = st.columns([1, 2])
    unidades_disp = ["%", "pts", "k", "M", "B", "USD", "índice", "otro"]
    with u1:
        unidad_actual = row.get("unidad") or "%"
        idx_unidad = unidades_disp.index(unidad_actual) if unidad_actual in unidades_disp else 0
        unidad_edit = st.selectbox("📐 Unidad", unidades_disp, index=idx_unidad, key=f"{key_pref}_unidad")
    with u2:
        notas_edit = st.text_input("💬 Notas", value=row.get("notas") or "", key=f"{key_pref}_notas")

    b1, b2 = st.columns(2)
    with b1:
        if st.button("💾 Guardar cambios", type="primary", use_container_width=True, key=f"{key_pref}_btn_guardar"):
            datos = dict(
                fecha=fecha_edit, pais=pais_edit, evento=evento_edit,
                previsto=previsto_edit, anterior=anterior_edit, real=real_edit,
                unidad=unidad_edit, notas=notas_edit,
            )
            try:
                _actualizar_registro(supabase, registro_id, datos)
                _limpiar_cache_registros()
                st.success("✅ Evento actualizado.")
                st.session_state.pop(f"cal_hist_editando_{registro_id}", None)
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error al actualizar: {e}")
    with b2:
        if st.button("✖️ Cancelar", use_container_width=True, key=f"{key_pref}_btn_cancelar"):
            st.session_state.pop(f"cal_hist_editando_{registro_id}", None)
            st.rerun()


def _confirmar_borrado_registro(supabase, row):
    registro_id = row["id"]
    st.warning(
        f"¿Seguro que querés eliminar **{row.get('evento','')}** de **{row.get('pais','')}** "
        f"({row.get('fecha','')})? Esta acción no se puede deshacer."
    )
    b1, b2 = st.columns(2)
    with b1:
        if st.button("🗑️ Sí, eliminar", type="primary", use_container_width=True, key=f"cal_del_{registro_id}_confirmar"):
            try:
                _borrar_registro(supabase, registro_id)
                _limpiar_cache_registros()
                st.success("✅ Evento eliminado.")
                st.session_state.pop(f"cal_hist_borrando_{registro_id}", None)
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error al eliminar: {e}")
    with b2:
        if st.button("✖️ Cancelar", use_container_width=True, key=f"cal_del_{registro_id}_cancelar"):
            st.session_state.pop(f"cal_hist_borrando_{registro_id}", None)
            st.rerun()


def _tab_historial(supabase, es_admin=False):
    top1, top2 = st.columns([3, 1])
    with top1:
        st.caption("Todos los eventos económicos cargados" + (" (el admin puede editar o eliminar cada evento)" if es_admin else " (solo lectura)"))
    with top2:
        if st.button("↺ Actualizar", use_container_width=True, key="cal_hist_refresh"):
            _limpiar_cache_registros()
            st.rerun()


    # El filtro de fecha se resuelve ANTES de pedir los datos, así el
    # rango se manda directo a la query de Supabase (más rápido cuando
    # la tabla crece mucho, en vez de traer todo y filtrar en pandas).
    f_fechas = st.date_input(
        "📅 Filtrar por fecha",
        value=(),
        key="cal_hist_f_fecha",
        format="DD/MM/YYYY",
        help="Elegí un día puntual, o dos fechas para filtrar por rango. Dejalo vacío para ver todo.",
    )

    fecha_desde = fecha_hasta = None
    if f_fechas:
        if isinstance(f_fechas, (list, tuple)):
            if len(f_fechas) == 1:
                fecha_desde = fecha_hasta = f_fechas[0]
            elif len(f_fechas) == 2:
                fecha_desde, fecha_hasta = f_fechas
        else:
            fecha_desde = fecha_hasta = f_fechas

    filas = _obtener_registros(supabase, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
    if not filas:
        st.info("No hay registros para el período seleccionado." if fecha_desde else "Todavía no hay registros cargados.")
        return

    df = pd.DataFrame(filas)
    df["fecha_dt"] = pd.to_datetime(df["fecha"], errors="coerce").dt.date

    fc1, fc2 = st.columns(2)
    with fc1:
        paises_u = ["Todos"] + sorted(df["pais"].dropna().unique().tolist())
        f_pais = st.selectbox("Filtrar país", paises_u, key="cal_hist_f_pais")
    with fc2:
        impactos_u = ["Todos"] + sorted(df["impacto_mercado"].dropna().unique().tolist()) if "impacto_mercado" in df.columns else ["Todos"]
        f_imp = st.selectbox("Filtrar impacto", impactos_u, key="cal_hist_f_imp")

    df_f = df.copy()
    if f_pais != "Todos":
        df_f = df_f[df_f["pais"] == f_pais]
    if f_imp != "Todos":
        df_f = df_f[df_f["impacto_mercado"] == f_imp]

    st.caption(
        f"{len(df_f)} registros mostrados de {len(df)} totales"
        + (" en el período seleccionado" if fecha_desde else "")
    )

    POR_PAGINA = 20
    total_paginas = max(1, -(-len(df_f) // POR_PAGINA))  # redondeo hacia arriba
    if "cal_hist_pagina" not in st.session_state:
        st.session_state["cal_hist_pagina"] = 1
    # si cambió el filtro y la página quedó fuera de rango, la reacomodamos
    if st.session_state["cal_hist_pagina"] > total_paginas:
        st.session_state["cal_hist_pagina"] = 1

    pcol1, pcol2, pcol3 = st.columns([1, 2, 1])
    with pcol2:
        pagina = st.number_input(
            "Página", min_value=1, max_value=total_paginas,
            step=1, key="cal_hist_pagina",
        )
    ini = (pagina - 1) * POR_PAGINA
    df_pagina = df_f.iloc[ini:ini + POR_PAGINA]
    st.caption(f"Mostrando {ini + 1}–{min(ini + POR_PAGINA, len(df_f))} · Página {pagina} de {total_paginas}")

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    for _, row in df_pagina.iterrows():
        impacto = row.get("impacto_mercado") or "⚪ NEUTRO PARA EL MERCADO"
        bg, fg = _impacto_estilo(impacto)
        real, previsto, anterior = row.get("real"), row.get("previsto"), row.get("anterior")
        unidad = row.get("unidad") or ""
        registro_id = row.get("id")

        titulo = f"{row.get('fecha','')} · {row.get('pais','')} · {row.get('evento','')}"
        with st.expander(titulo):
            st.markdown(
                f'<div style="border-radius:10px;padding:10px 14px;margin-bottom:10px;'
                f'background:{bg};border:1px solid {fg}55">'
                f'<div style="font-size:10px;color:{fg};opacity:.8">Impacto para el Mercado</div>'
                f'<div style="font-size:14px;font-weight:800;color:{fg}">{impacto}</div></div>',
                unsafe_allow_html=True,
            )

            v1, v2, v3 = st.columns(3)
            v1.metric("Previsto", f"{previsto} {unidad}" if previsto is not None else "—")
            v2.metric("Anterior", f"{anterior} {unidad}" if anterior is not None else "—")
            v3.metric("Real", f"{real} {unidad}" if real is not None else "—")

            s1, s2 = st.columns(2)
            s1.markdown(f"**Real vs Previsto:** {row.get('vs_previsto') or '—'}  \n**Señal:** {row.get('senal_previsto') or '—'}")
            s2.markdown(f"**Real vs Anterior:** {row.get('vs_anterior') or '—'}  \n**Señal:** {row.get('senal_anterior') or '—'}")

            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
            macro = {
                "divisas": row.get("divisas"), "bonos": row.get("bonos"),
                "acciones": row.get("acciones"), "oro": row.get("oro"),
                "crypto": row.get("criptomonedas"), "politica": row.get("politica_monetaria"),
                "riesgo": row.get("regimen_mercado"), "lectura": row.get("lectura_macro"),
            }
            _render_macro_grid(macro)

            if row.get("notas"):
                st.markdown(f"**Notas:** {row['notas']}")

            if es_admin and registro_id is not None:
                st.markdown("<hr style='margin:10px 0;border-color:#21262d'>", unsafe_allow_html=True)
                key_editando = f"cal_hist_editando_{registro_id}"
                key_borrando = f"cal_hist_borrando_{registro_id}"

                if st.session_state.get(key_editando):
                    _form_editar_registro(supabase, row)
                elif st.session_state.get(key_borrando):
                    _confirmar_borrado_registro(supabase, row)
                else:
                    ba1, ba2 = st.columns(2)
                    with ba1:
                        if st.button("✏️ Editar", use_container_width=True, key=f"cal_hist_btn_editar_{registro_id}"):
                            st.session_state[key_editando] = True
                            st.rerun()
                    with ba2:
                        if st.button("🗑️ Eliminar", use_container_width=True, key=f"cal_hist_btn_eliminar_{registro_id}"):
                            st.session_state[key_borrando] = True
                            st.rerun()


# ==============================================================
#  SCORING COMPARTIDO — categorías y activos financieros
#  (usado tanto por el perfil de un país como por País vs País)
# ==============================================================

PESO_IMPACTO = {"Muy Alto": 3.0, "Alto": 2.0, "Medio": 1.0, "Bajo": 0.5}

# Campos de activos tal como están guardados en la tabla de Supabase,
# junto con su etiqueta legible.
ASSET_FIELDS = [
    ("divisas", "💱 Divisas / Moneda"),
    ("bonos", "📜 Bonos"),
    ("acciones", "📊 Acciones / Índices"),
    ("oro", "🥇 Oro"),
    ("criptomonedas", "₿ Criptomonedas"),
]

# Puntaje según el emoji con el que arranca cada texto de interpretación
# macro (divisas/bonos/acciones/oro/cripto). Los diccionarios de arriba
# son consistentes: 🟢 favorable, 🔴 desfavorable, 🟠 desfavorable parcial,
# ⚪ sin impacto claro / sin datos.
ASSET_EMOJI_SCORE = {"🟢": 1.0, "🟠": -0.5, "🔴": -1.0, "⚪": 0.0}


def _signal_score(impacto_mercado):
    if not impacto_mercado:
        return 0.0
    if "BUEN DATO PARA" in impacto_mercado:
        return 1.0
    if "MAL DATO PARA" in impacto_mercado:
        return -1.0
    if "BUEN DATO PAR" in impacto_mercado:   # parcial
        return 0.5
    if "MAL DATO PAR" in impacto_mercado:    # parcial
        return -0.5
    return 0.0


def _asset_score_from_text(texto):
    """Convierte el texto de interpretación de un activo (ej. "🟢 Moneda
    fuerte...") en un puntaje -1..+1 según el emoji con el que arranca."""
    if not texto:
        return 0.0
    texto = texto.strip()
    for emoji, score in ASSET_EMOJI_SCORE.items():
        if texto.startswith(emoji):
            return score
    return 0.0


def _categoria_de_evento(evento):
    info = EVENTOS.get(evento)
    return info["categoria"] if info else "Otros"


def _es_evento_neutral(evento):
    info = EVENTOS.get(evento)
    return bool(info) and info.get("polaridad") == "neutral"


def _peso_de_evento(evento):
    info = EVENTOS.get(evento)
    if not info:
        return 1.0
    return PESO_IMPACTO.get(info.get("impacto"), 1.0)


def _promedio_ponderado_score(sub_df):
    """Promedio del score de cada dato, ponderado por el impacto del
    evento (Muy Alto/Alto/Medio/Bajo)."""
    if sub_df.empty:
        return None, 0
    peso_total = sub_df["peso"].sum()
    if peso_total == 0:
        return None, len(sub_df)
    return (sub_df["score"] * sub_df["peso"]).sum() / peso_total, len(sub_df)


def _resumen_activos_pais(df_pais):
    """Para cada activo financiero (divisas/moneda, bonos, acciones, oro,
    cripto) calcula un puntaje ponderado -1..+1 a partir de TODOS los
    registros cargados para ese país, ponderando cada dato por el impacto
    de su evento — mismo criterio que se usa para las categorías."""
    resultados = {}
    for campo, _ in ASSET_FIELDS:
        if df_pais.empty:
            resultados[campo] = (None, 0)
            continue
        pesos = df_pais["peso"]
        scores = df_pais[campo].apply(_asset_score_from_text)
        peso_total = pesos.sum()
        if peso_total == 0:
            resultados[campo] = (None, 0)
        else:
            resultados[campo] = ((scores * pesos).sum() / peso_total, len(df_pais))
    return resultados


def _asset_verdict(score):
    if score is None:
        return "⚪", "Sin datos suficientes"
    if score >= 0.5:
        return "🟢", "Sesgo claramente positivo"
    if score >= 0.15:
        return "🟡", "Sesgo levemente positivo"
    if score <= -0.5:
        return "🔴", "Sesgo claramente negativo"
    if score <= -0.15:
        return "🟠", "Sesgo levemente negativo"
    return "⚪", "Sesgo neutro / mixto"


def _render_tarjeta_activo(nombre, score, n, destacar=False):
    emoji, texto = _asset_verdict(score)
    detalle = f"Puntaje ponderado: {score:+.2f} sobre {n} dato(s)" if score is not None else "Todavía no hay datos cargados para este activo"
    borde = "#e3b341" if destacar else "#21262d"
    st.markdown(
        f'<div style="border-radius:10px;padding:12px 16px;margin-bottom:10px;'
        f'background:#0d1117;border:1px solid #21262d;border-left:4px solid {borde}">'
        f'<div style="font-size:11px;color:#6b7d9a;text-transform:uppercase;letter-spacing:.5px">{nombre}</div>'
        f'<div style="font-size:15px;font-weight:800;color:#e6edf3">{emoji} {texto}</div>'
        f'<div style="font-size:11px;color:#6b7d9a;margin-top:4px">{detalle}</div></div>',
        unsafe_allow_html=True,
    )


def _texto_resumen_pais(pais, categorias, df_pais_puntuable, moneda_score):
    positivas, negativas = [], []
    for cat in categorias:
        sub = df_pais_puntuable[df_pais_puntuable["categoria"] == cat]
        prom, _ = _promedio_ponderado_score(sub)
        if prom is None:
            continue
        if prom >= 0.15:
            positivas.append(cat)
        elif prom <= -0.15:
            negativas.append(cat)

    partes = []
    if positivas:
        partes.append(f"muestra fortaleza en {', '.join(positivas)}")
    if negativas:
        partes.append(f"muestra debilidad en {', '.join(negativas)}")
    cuerpo = " y ".join(partes) if partes else "muestra un panorama mixto, sin un sesgo claro en ninguna categoría"

    if moneda_score is None:
        moneda_txt = "todavía no hay datos suficientes para estimar el impacto sobre su moneda."
    elif moneda_score >= 0.15:
        moneda_txt = "el saldo de los datos macro favorece a su moneda."
    elif moneda_score <= -0.15:
        moneda_txt = "el saldo de los datos macro presiona a la baja a su moneda."
    else:
        moneda_txt = "el saldo de los datos macro no marca un sesgo claro sobre su moneda."

    return f"📌 {pais} {cuerpo}. En cuanto al mercado de cambios, {moneda_txt}"


# ==============================================================
#  INFORME "SENIOR ANALYST" — narrativa larga + gráficos
#  Usado por Perfil de País y País vs País para dar una lectura
#  mucho más completa y profesional que el resumen de una línea.
# ==============================================================

def _chart_barras_categorias(nombres, valores, colores, titulo):
    fig = go.Figure(go.Bar(
        x=valores, y=nombres, orientation="h",
        marker=dict(color=colores),
        text=[f"{v:+.2f}" for v in valores],
        textposition="outside",
    ))
    fig.update_layout(
        title=titulo,
        xaxis=dict(range=[-1.2, 1.2], title="Puntaje ponderado (−1 a +1)", zerolinecolor="#3a3a3a"),
        yaxis=dict(autorange="reversed"),
        height=max(260, 46 * len(nombres)),
        margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e6edf3"),
    )
    return fig


def _color_de_score(score):
    if score is None:
        return "#6b7d9a"
    if score >= 0.5:
        return "#2ea043"
    if score >= 0.15:
        return "#d4a72c"
    if score <= -0.5:
        return "#f85149"
    if score <= -0.15:
        return "#f0883e"
    return "#6b7d9a"


def _chart_radar_activos(activos, nombre_serie, color):
    labels = [nombre for _, nombre in ASSET_FIELDS]
    valores = [activos.get(campo, (0.0, 0))[0] or 0.0 for campo, _ in ASSET_FIELDS]
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=valores + [valores[0]], theta=labels + [labels[0]],
        fill="toself", name=nombre_serie, line=dict(color=color),
    ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[-1, 1], color="#8b949e"),
            angularaxis=dict(color="#e6edf3"),
            bgcolor="rgba(0,0,0,0)",
        ),
        showlegend=True,
        height=380,
        margin=dict(l=30, r=30, t=30, b=30),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e6edf3"),
    )
    return fig


def _dato_mas_reciente_relevante(df_pais):
    """Devuelve la fila del dato puntuable de mayor impacto y más
    reciente, para citarlo en el informe como 'lo último a destacar'."""
    if df_pais.empty:
        return None
    orden = {"Muy Alto": 3, "Alto": 2, "Medio": 1, "Bajo": 0}
    df_ordenable = df_pais.copy()
    df_ordenable["peso_orden"] = df_ordenable["evento"].apply(
        lambda e: orden.get(EVENTOS.get(e, {}).get("impacto"), 0)
    )
    df_ordenable = df_ordenable.sort_values(
        by=["fecha_dt", "peso_orden"], ascending=[False, False]
    )
    return df_ordenable.iloc[0] if not df_ordenable.empty else None


# ── Evolución mes a mes (¿mejoró o empeoró respecto al mes anterior?) ──

def _serie_mensual(df_puntuable):
    """Agrupa un df puntuable por período (año-mes) y devuelve el
    puntaje ponderado de cada mes, ordenado cronológicamente. Se usa
    tanto a nivel país completo como por categoría."""
    if df_puntuable.empty:
        return pd.DataFrame(columns=["periodo", "score", "n"])
    df = df_puntuable.copy()
    df["periodo"] = df["fecha_dt"].dt.to_period("M")
    filas = []
    for periodo, sub in df.groupby("periodo"):
        prom, n = _promedio_ponderado_score(sub)
        filas.append({"periodo": periodo, "score": prom, "n": n})
    return pd.DataFrame(filas).sort_values("periodo").reset_index(drop=True)


def _comparar_ultimos_meses(serie_mensual):
    """A partir de una serie mensual ya armada, compara el último
    período con datos contra el anterior. Devuelve None si no hay
    ningún período, o un dict con lo que haya disponible."""
    if serie_mensual.empty:
        return None
    ultimo = serie_mensual.iloc[-1]
    resultado = {
        "periodo_actual": ultimo["periodo"], "score_actual": ultimo["score"], "n_actual": ultimo["n"],
        "periodo_anterior": None, "score_anterior": None, "n_anterior": None, "diff": None,
    }
    if len(serie_mensual) >= 2:
        anterior = serie_mensual.iloc[-2]
        resultado["periodo_anterior"] = anterior["periodo"]
        resultado["score_anterior"] = anterior["score"]
        resultado["n_anterior"] = anterior["n"]
        if ultimo["score"] is not None and anterior["score"] is not None:
            resultado["diff"] = ultimo["score"] - anterior["score"]
    return resultado


def _periodo_legible(periodo):
    return f"{MESES_NOMBRE.get(periodo.month, periodo.month)} {periodo.year}"


def _movimientos_mensuales_por_categoria(df_puntuable_completo):
    """Para cada categoría con datos en al menos dos meses distintos,
    devuelve (categoria, score_actual, score_anterior, diff), para
    poder señalar cuál fue la que más mejoró o empeoró en el margen."""
    if df_puntuable_completo.empty:
        return []
    resultados = []
    for cat in sorted(df_puntuable_completo["categoria"].unique().tolist()):
        sub = df_puntuable_completo[df_puntuable_completo["categoria"] == cat]
        serie = _serie_mensual(sub)
        comp = _comparar_ultimos_meses(serie)
        if comp and comp["score_actual"] is not None and comp["score_anterior"] is not None:
            resultados.append((cat, comp["score_actual"], comp["score_anterior"], comp["diff"]))
    return resultados


def _texto_evolucion_mensual(pais, df_puntuable_completo):
    """Párrafo narrativo: ¿el conjunto de datos del país mejoró o
    empeoró respecto al mes anterior? Usa TODO el historial cargado
    (no el recorte por año/mes que haya elegido el usuario en el
    filtro), porque comparar meses requiere ver más de un período."""
    if df_puntuable_completo.empty:
        return (f"Todavía no hay eventos cuantitativos cargados para {pais} como para evaluar "
                "su evolución mes a mes.")

    serie = _serie_mensual(df_puntuable_completo)
    comp = _comparar_ultimos_meses(serie)
    if comp is None:
        return (f"Todavía no hay suficientes meses distintos cargados para {pais} "
                "como para evaluar su evolución mes a mes.")
    if comp["periodo_anterior"] is None:
        return (f"Por ahora los datos de {pais} están concentrados en un solo mes "
                f"({_periodo_legible(comp['periodo_actual'])}), así que todavía no se puede decir "
                "si la economía viene mejorando o empeorando mes a mes; hace falta cargar al menos "
                "un mes más para tener ese contraste.")

    p_act, p_ant = _periodo_legible(comp["periodo_actual"]), _periodo_legible(comp["periodo_anterior"])
    s_act, s_ant, diff = comp["score_actual"], comp["score_anterior"], comp["diff"]

    if diff is None:
        base = f"No hay suficiente información comparable entre {p_ant} y {p_act} para {pais}."
    elif diff >= 0.15:
        base = (f"Comparando {p_ant} ({s_ant:+.2f}) contra {p_act} ({s_act:+.2f}), el conjunto de datos "
                f"de {pais} **mejoró** respecto al mes anterior ({diff:+.2f} puntos) — el saldo de "
                "sorpresas económicas viene siendo más favorable.")
    elif diff <= -0.15:
        base = (f"Comparando {p_ant} ({s_ant:+.2f}) contra {p_act} ({s_act:+.2f}), el conjunto de datos "
                f"de {pais} **empeoró** respecto al mes anterior ({diff:+.2f} puntos) — el saldo de "
                "sorpresas económicas viene siendo más desfavorable.")
    else:
        base = (f"Comparando {p_ant} ({s_ant:+.2f}) contra {p_act} ({s_act:+.2f}), el panorama de {pais} "
                f"se mantiene **prácticamente sin cambios** de un mes a otro ({diff:+.2f} puntos).")

    movimientos = _movimientos_mensuales_por_categoria(df_puntuable_completo)
    if movimientos:
        movimientos.sort(key=lambda x: abs(x[3]), reverse=True)
        cat, s_a, s_p, d = movimientos[0]
        if abs(d) >= 0.1:
            verbo = "mejoró" if d > 0 else "empeoró"
            base += (f" La categoría que más {verbo} en el margen fue **{cat}** "
                     f"({s_p:+.2f} → {s_a:+.2f}), que {_explicacion_categoria(cat)}.")

    return base


# ── Implicancia sobre tasas de interés a futuro ──

# Categorías cuyo puntaje ya viene "corregido" para que positivo =
# economía fuerte / inflación alta (o sea, hay que invertir el signo
# para que "positivo" signifique lo mismo que en el resto: presión
# hacia una política monetaria más dura).
_CATS_HAWKISH_INVERTIR = ["Inflación"]
# Categorías donde un puntaje positivo (economía fuerte) ya apunta
# directo hacia una política monetaria más dura, sin invertir signo.
_CATS_HAWKISH_DIRECTO = ["Empleo", "Crecimiento", "Actividad Económica", "Consumo", "Industria", "Sentimiento Empresarial"]


def _outlook_tasas(df_puntuable_completo):
    """Heurística simple de research: combina inflación (invertida),
    empleo, crecimiento, actividad, consumo, industria y sentimiento
    empresarial en un único puntaje -1..+1. Positivo = la economía
    empuja hacia una política monetaria más dura (tasas más altas o
    sin apuro para bajarlas); negativo = empuja hacia una política
    más laxa (más margen para recortar tasas)."""
    aportes, pesos, detalle = [], [], []

    for cat in _CATS_HAWKISH_INVERTIR:
        sub = df_puntuable_completo[df_puntuable_completo["categoria"] == cat]
        prom, n = _promedio_ponderado_score(sub)
        if prom is not None:
            aportes.append(-prom * n)
            pesos.append(n)
            detalle.append((cat, -prom, n))

    for cat in _CATS_HAWKISH_DIRECTO:
        sub = df_puntuable_completo[df_puntuable_completo["categoria"] == cat]
        prom, n = _promedio_ponderado_score(sub)
        if prom is not None:
            aportes.append(prom * n)
            pesos.append(n)
            detalle.append((cat, prom, n))

    if not pesos or sum(pesos) == 0:
        return None
    return sum(aportes) / sum(pesos), detalle


def _texto_outlook_tasas(pais, resultado_outlook):
    if resultado_outlook is None:
        return (f"Todavía no hay suficientes datos de inflación, empleo, crecimiento, actividad, "
                f"consumo o industria de {pais} como para estimar qué implica esta información "
                "para sus tasas de interés a futuro.")

    hawkish_score, _detalle = resultado_outlook

    if hawkish_score >= 0.4:
        lectura = (
            "el conjunto de datos empuja con fuerza hacia una política monetaria **más restrictiva**: "
            "una economía firme (empleo, crecimiento y/o actividad sólidos) combinada con presión "
            "inflacionaria le da poco margen al banco central para bajar tasas, y aumenta la "
            "probabilidad de que se mantengan altas por más tiempo o incluso suban."
        )
    elif hawkish_score >= 0.15:
        lectura = (
            "el sesgo es moderadamente **hacia tasas más altas, o al menos sin apuro para recortar**: "
            "los datos no muestran ni una economía débil ni una inflación totalmente controlada."
        )
    elif hawkish_score <= -0.4:
        lectura = (
            "el conjunto de datos abre la puerta con fuerza a una política monetaria **más laxa**: "
            "la combinación de actividad o empleo débil con inflación contenida le da margen al "
            "banco central para recortes de tasas más marcados o más próximos en el tiempo."
        )
    elif hawkish_score <= -0.15:
        lectura = (
            "el sesgo es moderadamente **hacia tasas más bajas**: empieza a aparecer cierta "
            "debilidad económica y/o alivio inflacionario que amplía el margen de maniobra del "
            "banco central."
        )
    else:
        lectura = (
            "el balance entre inflación, empleo, crecimiento y actividad es **mixto**, sin un sesgo "
            "claro sobre la dirección de las tasas de interés a futuro."
        )

    return (f"En cuanto a la implicancia sobre las **tasas de interés a futuro**, {lectura} "
            f"(puntaje combinado: {hawkish_score:+.2f}, sobre una escala de −1 a +1).")


# ── Volatilidad y racha (para un informe más profesional) ──

def _volatilidad_score(serie_mensual):
    """Desvío estándar del puntaje mensual — mide qué tan errático o
    estable viene siendo el flujo de sorpresas económicas mes a mes.
    Un valor bajo describe un ciclo consistente; uno alto, un ciclo
    con datos contradictorios de un mes a otro."""
    if serie_mensual.empty:
        return None, 0
    datos = serie_mensual["score"].dropna()
    if len(datos) < 2:
        return None, len(datos)
    return float(datos.std()), len(datos)


def _texto_volatilidad(volatilidad, n_meses):
    if volatilidad is None:
        return None
    if volatilidad < 0.25:
        calif = "**baja** — el ciclo de sorpresas viene siendo consistente mes a mes"
    elif volatilidad < 0.55:
        calif = "**moderada** — conviven meses buenos y flojos sin un patrón demasiado errático"
    else:
        calif = "**alta** — el flujo de datos viene siendo contradictorio de un mes a otro, lo que resta previsibilidad a la lectura"
    return f"La volatilidad del puntaje mensual es {calif} (desvío estándar {volatilidad:.2f} sobre {n_meses} mes(es) con datos)."


def _racha_actual(serie_mensual):
    """Cuenta cuántos meses consecutivos (desde el más reciente hacia
    atrás) el puntaje viene moviéndose en la misma dirección."""
    datos = serie_mensual["score"].dropna().tolist()
    if len(datos) < 2:
        return 0, None
    diffs = [datos[i] - datos[i - 1] for i in range(1, len(datos))]
    racha, direccion = 0, None
    for d in reversed(diffs):
        signo = "mejora" if d > 0.05 else ("empeora" if d < -0.05 else None)
        if signo is None:
            break
        if direccion is None:
            direccion = signo
            racha = 1
        elif signo == direccion:
            racha += 1
        else:
            break
    return racha, direccion


def _texto_racha(racha, direccion, pais):
    if not racha or not direccion:
        return None
    verbo = "mejorando" if direccion == "mejora" else "empeorando"
    plural = "meses consecutivos" if racha > 1 else "mes"
    return (f"Además, {pais} lleva **{racha} {plural} {verbo}** en su puntaje agregado, lo que "
            + ("es un indicio de que el ciclo actual tiene continuidad, más allá del dato puntual "
               "del último mes." if racha >= 2 else
               "todavía es un movimiento reciente y conviene confirmarlo con el próximo dato."))

# ==============================================================
#  FASE DEL CICLO ECONÓMICO
#  Ubica a cada país en el clásico "reloj del ciclo económico"
#  (Recuperación / Expansión / Sobrecalentamiento / Desaceleración-
#  Contracción) cruzando el nivel y el momentum del crecimiento con
#  el comportamiento de la inflación — versión simplificada del
#  Investment Clock, calculada 100% con los datos ya cargados.
# ==============================================================

_CATS_CRECIMIENTO_CICLO = ["Crecimiento", "Actividad Económica", "Empleo", "Consumo", "Industria", "Sentimiento Empresarial"]
_CAT_INFLACION_CICLO = "Inflación"

_UMBRAL_FUERTE_CICLO = 0.15
_UMBRAL_MOMENTUM_CICLO = 0.10


def _score_compuesto_crecimiento(df_puntuable):
    """Promedio ponderado del crecimiento, pooleando todos los eventos
    de las categorías de crecimiento juntas (no promedio de promedios),
    para que una categoría con más datos pese más que una con uno solo
    — mismo criterio que _promedio_ponderado_score."""
    if df_puntuable.empty:
        return None, 0
    sub = df_puntuable[df_puntuable["categoria"].isin(_CATS_CRECIMIENTO_CICLO)]
    return _promedio_ponderado_score(sub)


def _score_inflacion_ciclo(df_puntuable):
    if df_puntuable.empty:
        return None, 0
    sub = df_puntuable[df_puntuable["categoria"] == _CAT_INFLACION_CICLO]
    return _promedio_ponderado_score(sub)


def _momentum_crecimiento(df_puntuable):
    """Compara el puntaje de crecimiento del último mes contra el
    anterior (mismo criterio que _comparar_ultimos_meses, pero
    pooleando directamente las categorías de crecimiento)."""
    if df_puntuable.empty:
        return None
    sub = df_puntuable[df_puntuable["categoria"].isin(_CATS_CRECIMIENTO_CICLO)]
    serie = _serie_mensual(sub)
    comp = _comparar_ultimos_meses(serie)
    if comp is None:
        return None
    return comp["diff"]


_FASES_CICLO = {
    "recuperacion": {
        "nombre": "🌱 Recuperación",
        "color": "#2ea043",
        "resumen": "el crecimiento viene débil pero mejorando, con la inflación todavía controlada",
        "detalle": (
            "Es la fase típica de salida de un piso económico: la actividad todavía no muestra "
            "fortaleza plena, pero la tendencia reciente es de mejora y la inflación no genera "
            "una restricción adicional. Suele ser la etapa donde el banco central tiene más margen "
            "para sostener una política monetaria laxa, y donde los activos de riesgo locales "
            "empiezan a anticipar la mejora antes de que se confirme en los datos duros."
        ),
    },
    "expansion": {
        "nombre": "🚀 Expansión",
        "color": "#3a7bd5",
        "resumen": "el crecimiento se muestra fuerte y sostenido, con la inflación todavía razonable",
        "detalle": (
            "Es el tramo más benigno del ciclo ('goldilocks'): actividad firme sin que la inflación "
            "se dispare. El banco central suele tener margen para mantener una postura neutral, y "
            "es la fase históricamente más favorable para activos de riesgo (acciones, moneda local) "
            "por sobre los refugios."
        ),
    },
    "sobrecalentamiento": {
        "nombre": "🔥 Sobrecalentamiento",
        "color": "#e3b341",
        "resumen": "el crecimiento sigue firme, pero la inflación viene acelerando",
        "detalle": (
            "Es la etapa tardía del ciclo expansivo: la economía sigue mostrando fortaleza, pero "
            "empieza a convivir con presión de precios al alza. Es el escenario que típicamente "
            "obliga al banco central a endurecer la política monetaria, lo que eleva el riesgo de "
            "que la propia suba de tasas termine frenando la actividad más adelante."
        ),
    },
    "desaceleracion": {
        "nombre": "🥶 Desaceleración / Contracción",
        "color": "#f85149",
        "resumen": "el crecimiento viene débil y sigue perdiendo impulso",
        "detalle": (
            "Es la fase más adversa del ciclo: la actividad se debilita y la tendencia reciente "
            "confirma el deterioro, en lugar de mostrar señales de piso. Si además la inflación "
            "sigue alta, es la combinación más difícil de manejar para la política económica "
            "(estanflación); si la inflación cede, el banco central gana margen para bajar tasas "
            "y empezar a estimular la economía."
        ),
    },
}


def _clasificar_fase(growth_score, inflacion_score, momentum):
    """Clasifica una combinación puntual de (crecimiento, inflación,
    momentum) en una de las 4 fases del ciclo — reutilizable tanto para
    el puntaje agregado de todo el historial como para el de un mes
    puntual."""
    crecimiento_fuerte = growth_score >= _UMBRAL_FUERTE_CICLO
    crecimiento_debil = growth_score <= -_UMBRAL_FUERTE_CICLO
    inflacion_acelerando = (inflacion_score is not None) and (inflacion_score <= -_UMBRAL_FUERTE_CICLO)
    inflacion_controlada = (inflacion_score is None) or (inflacion_score > -_UMBRAL_FUERTE_CICLO)
    momentum_positivo = (momentum is not None) and (momentum >= _UMBRAL_MOMENTUM_CICLO)
    momentum_negativo = (momentum is not None) and (momentum <= -_UMBRAL_MOMENTUM_CICLO)

    if crecimiento_fuerte and inflacion_acelerando:
        return "sobrecalentamiento"
    if crecimiento_fuerte:
        return "expansion"
    if crecimiento_debil and momentum_negativo:
        return "desaceleracion"
    if crecimiento_debil and momentum_positivo:
        return "recuperacion"
    if crecimiento_debil:
        return "desaceleracion"
    if momentum_positivo:
        return "recuperacion"
    if momentum_negativo:
        return "sobrecalentamiento" if inflacion_acelerando else "desaceleracion"
    return "expansion" if inflacion_controlada else "sobrecalentamiento"


def _fase_ciclo_economico(pais, df_puntuable_completo):
    """Devuelve un dict con la fase del ciclo estimada para el país, o
    None si no hay datos de crecimiento suficientes como para opinar."""
    growth_score, n_growth = _score_compuesto_crecimiento(df_puntuable_completo)
    if growth_score is None:
        return None

    inflacion_score, n_inflacion = _score_inflacion_ciclo(df_puntuable_completo)
    momentum = _momentum_crecimiento(df_puntuable_completo)

    clave = _clasificar_fase(growth_score, inflacion_score, momentum)
    fase = dict(_FASES_CICLO[clave])
    fase["clave"] = clave
    fase["growth_score"] = growth_score
    fase["n_growth"] = n_growth
    fase["inflacion_score"] = inflacion_score
    fase["n_inflacion"] = n_inflacion
    fase["momentum"] = momentum
    return fase


def _texto_fase_ciclo(pais, fase):
    if fase is None:
        return (f"Todavía no hay suficientes eventos de crecimiento, empleo, actividad o consumo "
                f"cargados para {pais} como para ubicarlo en el ciclo económico.")

    momentum_txt = "sin datos suficientes de tendencia reciente"
    if fase["momentum"] is not None:
        if fase["momentum"] >= _UMBRAL_MOMENTUM_CICLO:
            momentum_txt = f"mejorando en el margen ({fase['momentum']:+.2f} vs. el mes anterior)"
        elif fase["momentum"] <= -_UMBRAL_MOMENTUM_CICLO:
            momentum_txt = f"perdiendo impulso en el margen ({fase['momentum']:+.2f} vs. el mes anterior)"
        else:
            momentum_txt = f"prácticamente estable en el margen ({fase['momentum']:+.2f} vs. el mes anterior)"

    inflacion_txt = "sin datos de inflación suficientes"
    if fase["inflacion_score"] is not None:
        if fase["inflacion_score"] >= _UMBRAL_FUERTE_CICLO:
            inflacion_txt = f"cediendo ({fase['inflacion_score']:+.2f})"
        elif fase["inflacion_score"] <= -_UMBRAL_FUERTE_CICLO:
            inflacion_txt = f"acelerando ({fase['inflacion_score']:+.2f})"
        else:
            inflacion_txt = f"relativamente estable ({fase['inflacion_score']:+.2f})"

    return (
        f"Con un puntaje de crecimiento agregado de {fase['growth_score']:+.2f} "
        f"(sobre {fase['n_growth']} dato(s) de empleo, actividad, consumo, industria y crecimiento), "
        f"{momentum_txt}, y una inflación {inflacion_txt}, {pais} se ubica en la fase de "
        f"**{fase['nombre']}** dentro del ciclo económico: {fase['resumen']}. {fase['detalle']}"
    )


def _chart_reloj_ciclo(paises_fases):
    """Grafica a uno o más países en el plano Crecimiento (eje X) x
    Inflación (eje Y) para ubicarlos visualmente en el reloj del ciclo.
    paises_fases: lista de tuplas (nombre_pais, fase_dict, color)."""
    fig = go.Figure()

    fig.add_shape(type="rect", x0=0, x1=1.3, y0=0, y1=1.3, fillcolor="#3a7bd511", line=dict(width=0))
    fig.add_shape(type="rect", x0=0, x1=1.3, y0=-1.3, y1=0, fillcolor="#e3b34111", line=dict(width=0))
    fig.add_shape(type="rect", x0=-1.3, x1=0, y0=0, y1=1.3, fillcolor="#2ea04311", line=dict(width=0))
    fig.add_shape(type="rect", x0=-1.3, x1=0, y0=-1.3, y1=0, fillcolor="#f8514911", line=dict(width=0))

    anotaciones = [
        ("Expansión", 0.65, 0.65, "#3a7bd5"),
        ("Sobrecalentamiento", 0.65, -0.65, "#e3b341"),
        ("Recuperación", -0.65, 0.65, "#2ea043"),
        ("Desaceleración / Contracción", -0.65, -0.65, "#f85149"),
    ]
    for texto, x, y, color in anotaciones:
        fig.add_annotation(x=x, y=y, text=texto, showarrow=False,
                            font=dict(size=11, color=color), opacity=0.85)

    for nombre, fase, color in paises_fases:
        if fase is None:
            continue
        x = fase["growth_score"]
        y = fase["inflacion_score"] if fase["inflacion_score"] is not None else 0.0
        fig.add_trace(go.Scatter(
            x=[x], y=[y], mode="markers+text", name=nombre,
            text=[nombre], textposition="top center",
            marker=dict(size=18, color=color, line=dict(width=2, color="#0d1117")),
        ))

    fig.add_hline(y=0, line_dash="dot", line_color="#3a3a3a")
    fig.add_vline(x=0, line_dash="dot", line_color="#3a3a3a")
    fig.update_layout(
        title="Ubicación en el reloj del ciclo económico",
        xaxis=dict(title="◀ Crecimiento débil   |   Crecimiento fuerte ▶", range=[-1.3, 1.3], zerolinecolor="#3a3a3a", color="#e6edf3"),
        yaxis=dict(title="◀ Inflación acelerando   |   Inflación controlada ▶", range=[-1.3, 1.3], zerolinecolor="#3a3a3a", color="#e6edf3"),
        height=440,
        margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e6edf3"),
        showlegend=False,
    )
    return fig


def _render_fase_ciclo_pais(pais, df_puntuable_completo):
    st.markdown(f"#### 🔄 Fase del ciclo económico — {pais}")
    fase = _fase_ciclo_economico(pais, df_puntuable_completo)

    if fase is None:
        st.info(_texto_fase_ciclo(pais, fase))
        return

    st.markdown(
        f'<div style="border-radius:10px;padding:14px 16px;margin-bottom:10px;'
        f'background:#0d1117;border:1px solid #21262d;border-left:4px solid {fase["color"]}">'
        f'<div style="font-size:11px;color:#6b7d9a;text-transform:uppercase;letter-spacing:.5px">Fase estimada</div>'
        f'<div style="font-size:18px;font-weight:800;color:#e6edf3">{fase["nombre"]}</div>'
        f'<div style="font-size:12px;color:#8b949e;margin-top:4px">{fase["resumen"].capitalize()}</div></div>',
        unsafe_allow_html=True,
    )
    st.markdown(_texto_fase_ciclo(pais, fase))

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    st.plotly_chart(
        _chart_reloj_ciclo([(pais, fase, fase["color"])]),
        use_container_width=True, key=f"ciclo_chart_{pais}",
    )
    st.caption(
        "La ubicación es una estimación basada en el puntaje agregado de crecimiento (empleo, "
        "actividad económica, consumo, industria, sentimiento empresarial y PBI) y de inflación, "
        "más el momentum del crecimiento contra el mes anterior — no reemplaza el juicio de un "
        "analista sobre el ciclo completo del país."
    )


def _render_fase_ciclo_comparada(pais_a, pais_b, df_full_a, df_full_b):
    st.markdown(f"#### 🔄 Fase del ciclo económico — {pais_a} vs {pais_b}")
    fase_a = _fase_ciclo_economico(pais_a, df_full_a)
    fase_b = _fase_ciclo_economico(pais_b, df_full_b)

    c1, c2 = st.columns(2)
    for col, pais_x, fase_x in [(c1, pais_a, fase_a), (c2, pais_b, fase_b)]:
        with col:
            if fase_x is None:
                st.info(_texto_fase_ciclo(pais_x, fase_x))
            else:
                st.markdown(
                    f'<div style="border-radius:10px;padding:14px 16px;margin-bottom:10px;'
                    f'background:#0d1117;border:1px solid #21262d;border-left:4px solid {fase_x["color"]}">'
                    f'<div style="font-size:11px;color:#6b7d9a;text-transform:uppercase;letter-spacing:.5px">{pais_x}</div>'
                    f'<div style="font-size:17px;font-weight:800;color:#e6edf3">{fase_x["nombre"]}</div>'
                    f'<div style="font-size:12px;color:#8b949e;margin-top:4px">{fase_x["resumen"].capitalize()}</div></div>',
                    unsafe_allow_html=True,
                )

    if fase_a is not None or fase_b is not None:
        st.plotly_chart(
            _chart_reloj_ciclo([(pais_a, fase_a, "#3a7bd5"), (pais_b, fase_b, "#f0883e")]),
            use_container_width=True, key=f"ciclo_chart_cmp_{pais_a}_{pais_b}",
        )

    if fase_a is not None and fase_b is not None and fase_a["clave"] != fase_b["clave"]:
        st.info(
            f"📌 {pais_a} y {pais_b} están en **fases distintas** del ciclo económico "
            f"({fase_a['nombre']} vs. {fase_b['nombre']}), lo que suele traducirse en necesidades "
            "de política monetaria distintas entre ambos bancos centrales."
        )
    elif fase_a is not None and fase_b is not None:
        st.info(
            f"📌 {pais_a} y {pais_b} se ubican en la **misma fase** del ciclo económico "
            f"({fase_a['nombre']})."
        )

    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
    for pais_x, fase_x in [(pais_a, fase_a), (pais_b, fase_b)]:
        with st.expander(f"Ver detalle — {pais_x}"):
            st.markdown(_texto_fase_ciclo(pais_x, fase_x))

def _chart_evolucion_mensual(serie_mensual, nombre_serie, color, titulo=None):
    """Línea de tiempo con el puntaje ponderado mes a mes."""
    if serie_mensual is None or serie_mensual.empty:
        return None
    sm = serie_mensual.dropna(subset=["score"])
    if sm.empty:
        return None
    x = [_periodo_legible(p) for p in sm["periodo"]]
    y = sm["score"].tolist()
    n = sm["n"].tolist()
    fig = go.Figure(go.Scatter(
        x=x, y=y, mode="lines+markers",
        line=dict(color=color, width=3),
        marker=dict(size=9, color=[_color_de_score(v) for v in y], line=dict(width=1, color="#0d1117")),
        text=[f"{n_i} dato(s)" for n_i in n],
        hovertemplate="%{x}<br>Puntaje: %{y:+.2f}<br>%{text}<extra></extra>",
    ))
    fig.add_hline(y=0, line_dash="dot", line_color="#3a3a3a")
    fig.update_layout(
        title=titulo or f"Evolución mensual — {nombre_serie}",
        xaxis=dict(title="", color="#e6edf3"),
        yaxis=dict(title="Puntaje ponderado (−1 a +1)", range=[-1.15, 1.15], zerolinecolor="#3a3a3a", color="#e6edf3"),
        height=320,
        margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e6edf3"),
        showlegend=False,
    )
    return fig


def _chart_evolucion_categorias(df_puntuable_completo, max_categorias=5):
    """Multi-línea con la evolución mensual de las categorías con más
    datos, para ver a simple vista qué sectores vienen mejorando o
    empeorando el ciclo."""
    if df_puntuable_completo is None or df_puntuable_completo.empty:
        return None
    categorias = df_puntuable_completo["categoria"].value_counts().index.tolist()[:max_categorias]
    palette = ["#3a7bd5", "#e3b341", "#2ea043", "#f0883e", "#a371f7", "#f85149"]
    fig = go.Figure()
    tuvo_datos = False
    for i, cat in enumerate(categorias):
        sub = df_puntuable_completo[df_puntuable_completo["categoria"] == cat]
        serie = _serie_mensual(sub).dropna(subset=["score"])
        if len(serie) < 2:
            continue
        tuvo_datos = True
        fig.add_trace(go.Scatter(
            x=[_periodo_legible(p) for p in serie["periodo"]], y=serie["score"].tolist(),
            mode="lines+markers", name=cat,
            line=dict(color=palette[i % len(palette)], width=2.5), marker=dict(size=6),
        ))
    if not tuvo_datos:
        return None
    fig.add_hline(y=0, line_dash="dot", line_color="#3a3a3a")
    fig.update_layout(
        title="Evolución mensual por categoría",
        yaxis=dict(title="Puntaje ponderado", range=[-1.15, 1.15], zerolinecolor="#3a3a3a", color="#e6edf3"),
        xaxis=dict(color="#e6edf3"),
        height=360,
        margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e6edf3"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    return fig


def _chart_evolucion_comparada(serie_a, serie_b, nombre_a, nombre_b, titulo=None):
    """Overlay de la evolución mensual de dos países (o de dos países
    dentro de una misma categoría), para País vs País."""
    sa = serie_a.dropna(subset=["score"]) if serie_a is not None else pd.DataFrame()
    sb = serie_b.dropna(subset=["score"]) if serie_b is not None else pd.DataFrame()
    if sa.empty and sb.empty:
        return None
    fig = go.Figure()
    if not sa.empty:
        fig.add_trace(go.Scatter(
            x=[_periodo_legible(p) for p in sa["periodo"]], y=sa["score"].tolist(),
            mode="lines+markers", name=nombre_a, line=dict(color="#3a7bd5", width=3), marker=dict(size=8),
        ))
    if not sb.empty:
        fig.add_trace(go.Scatter(
            x=[_periodo_legible(p) for p in sb["periodo"]], y=sb["score"].tolist(),
            mode="lines+markers", name=nombre_b, line=dict(color="#f0883e", width=3), marker=dict(size=8),
        ))
    fig.add_hline(y=0, line_dash="dot", line_color="#3a3a3a")
    fig.update_layout(
        title=titulo or f"Evolución mensual comparada — {nombre_a} vs {nombre_b}",
        yaxis=dict(title="Puntaje ponderado", range=[-1.15, 1.15], zerolinecolor="#3a3a3a", color="#e6edf3"),
        xaxis=dict(color="#e6edf3"),
        height=360,
        margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e6edf3"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    return fig


def _informe_analista_pais(pais, df_pais_todo, df_pais_puntuable, categorias, activos,
                            df_puntuable_completo=None):
    """Arma un informe narrativo de varios párrafos, con tono de
    research/analista senior, a partir de los puntajes ya calculados."""
    moneda_score, moneda_n = activos.get("divisas", (None, 0))
    base_evolucion = df_puntuable_completo if df_puntuable_completo is not None else df_pais_puntuable

    # Categoría más fuerte / más débil
    scores_cat = []
    for cat in categorias:
        sub = df_pais_puntuable[df_pais_puntuable["categoria"] == cat]
        prom, n = _promedio_ponderado_score(sub)
        if prom is not None:
            scores_cat.append((cat, prom, n))
    scores_cat.sort(key=lambda x: x[1], reverse=True)

    parrafos = []

    # Párrafo 1: panorama general
    n_total, n_punt = len(df_pais_todo), len(df_pais_puntuable)
    if scores_cat:
        mejor_cat, mejor_val, mejor_n = scores_cat[0]
        peor_cat, peor_val, peor_n = scores_cat[-1]
        if len(scores_cat) == 1:
            parrafos.append(
                f"Con {n_total} evento(s) registrado(s) para {pais} ({n_punt} con lectura cuantitativa), "
                f"la única categoría con información suficiente es **{mejor_cat}** (que {_explicacion_categoria(mejor_cat)}), "
                f"con un puntaje de {mejor_val:+.2f} sobre {mejor_n} dato(s). Todavía no hay cobertura como para "
                f"trazar un panorama comparativo entre sectores de la economía."
            )
        else:
            parrafos.append(
                f"Con {n_total} evento(s) registrado(s) para {pais} ({n_punt} con lectura cuantitativa), "
                f"el frente más sólido es **{mejor_cat}** (puntaje {mejor_val:+.2f} sobre {mejor_n} dato(s)) "
                f"— esta categoría {_explicacion_categoria(mejor_cat)} —, "
                f"mientras que el punto más débil del panorama macro pasa por **{peor_cat}** "
                f"({peor_val:+.2f} sobre {peor_n} dato(s)), que {_explicacion_categoria(peor_cat)}. "
                + ("La dispersión entre ambos extremos sugiere una economía con sectores a distintas "
                   "velocidades, más que un ciclo homogéneo." if (mejor_val - peor_val) > 0.6 else
                   "La distancia entre ambos extremos es moderada, compatible con un ciclo relativamente "
                   "parejo entre sectores.")
            )
    else:
        parrafos.append(
            f"{pais} todavía no cuenta con eventos cuantitativos (con lectura de bueno/malo) suficientes "
            "como para armar un panorama por categoría; los registros cargados hasta ahora son cualitativos "
            "(comparecencias, actas u otros eventos sin cifra comparable)."
        )

    # Párrafo 2: dato más relevante reciente
    dato_top = _dato_mas_reciente_relevante(df_pais_puntuable)
    if dato_top is not None:
        signo = dato_top.get("senal_previsto") or dato_top.get("senal_anterior") or ""
        cat_top_dato = _categoria_de_evento(dato_top.get("evento"))
        parrafos.append(
            f"El dato de mayor jerarquía informativa cargado hasta el momento es **{dato_top.get('evento')}** "
            f"({dato_top.get('fecha')}), con una lectura de *{dato_top.get('impacto_mercado') or 'sin impacto claro'}* "
            + (f"y señal {signo.lower()}" if signo else "") + f". En criollo: este indicador {_explicacion_categoria(cat_top_dato)}, "
            "y este tipo de sorpresas —por encima o por debajo del consenso— suele ser lo primero que el mercado "
            "reacomoda en el precio, por lo que conviene monitorear si el próximo dato de la misma serie confirma "
            "o corrige la tendencia."
        )

    # Párrafo 3: implicancia en moneda / activos
    if moneda_score is not None:
        if moneda_score >= 0.5:
            lectura_moneda = (
                f"El balance de los fundamentos macro es **claramente favorable** para la moneda de {pais} "
                f"(+{moneda_score:.2f}); en un contexto así, lo habitual es ver flujos que buscan aprovechar "
                "el diferencial de tasas o de crecimiento relativo frente a otras economías."
            )
        elif moneda_score >= 0.15:
            lectura_moneda = (
                f"El sesgo fundamental sobre la moneda de {pais} es **levemente positivo** (+{moneda_score:.2f}); "
                "no alcanza para hablar de una tendencia consolidada, pero inclina la balanza a favor en el margen."
            )
        elif moneda_score <= -0.5:
            lectura_moneda = (
                f"El cuadro macro presiona **claramente a la baja** sobre la moneda de {pais} ({moneda_score:.2f}); "
                "este tipo de deterioro suele preceder o acompañar salidas de capital y mayor volatilidad cambiaria."
            )
        elif moneda_score <= -0.15:
            lectura_moneda = (
                f"Se observa un sesgo **levemente negativo** sobre la moneda de {pais} ({moneda_score:.2f}), "
                "más ligado a un deterioro incipiente que a una tendencia bajista firme."
            )
        else:
            lectura_moneda = (
                f"El saldo neto sobre la moneda de {pais} es **prácticamente neutro** ({moneda_score:+.2f}); "
                "los datos publicados se compensan entre sí y no ofrecen, por ahora, un driver fundamental claro "
                "en una u otra dirección."
            )
        parrafos.append(lectura_moneda)
    else:
        parrafos.append(
            f"Todavía no hay eventos con impacto directo sobre divisas cargados para {pais}, por lo que "
            "no es posible emitir una lectura fundamental sobre su moneda con la información disponible."
        )

    # Párrafo 4: evolución mes a mes (¿mejoró o empeoró?) — usa TODO el
    # historial cargado del país, independiente del filtro de año/mes
    # que haya elegido el usuario más arriba en la pantalla.
    parrafos.append(_texto_evolucion_mensual(pais, base_evolucion))

    # Párrafo 5: volatilidad y racha — le dan al informe un vistazo de
    # "calidad" del ciclo, no solo de dirección.
    serie_general = _serie_mensual(base_evolucion)
    volatilidad, n_meses_vol = _volatilidad_score(serie_general)
    texto_vol = _texto_volatilidad(volatilidad, n_meses_vol)
    racha, direccion = _racha_actual(serie_general)
    texto_racha = _texto_racha(racha, direccion, pais)
    extra = " ".join([t for t in [texto_vol, texto_racha] if t])
    if extra:
        parrafos.append(extra)

    # Párrafo 6: implicancia sobre tasas de interés a futuro
    parrafos.append(_texto_outlook_tasas(pais, _outlook_tasas(base_evolucion)))

    return parrafos


def _render_informe_analista_pais(pais, df_pais_todo, df_pais_puntuable, categorias, activos,
                                   df_puntuable_completo=None):
    st.markdown("#### 🧠 Informe de analista senior")
    for p in _informe_analista_pais(pais, df_pais_todo, df_pais_puntuable, categorias, activos,
                                     df_puntuable_completo):
        st.markdown(p)

    base_evolucion = df_puntuable_completo if df_puntuable_completo is not None else df_pais_puntuable
    serie_general = _serie_mensual(base_evolucion)

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    g1, g2 = st.columns(2)
    with g1:
        st.plotly_chart(
            _chart_radar_activos(activos, pais, "#3a7bd5"),
            use_container_width=True, key=f"perfil_chart_radar_{pais}",
        )
    with g2:
        fig_evol = _chart_evolucion_mensual(serie_general, pais, "#3a7bd5", titulo=f"Evolución mensual — {pais}")
        if fig_evol is not None:
            st.plotly_chart(fig_evol, use_container_width=True, key=f"perfil_chart_evol_{pais}")
        else:
            st.info("Todavía no hay al menos dos meses distintos cargados como para graficar la evolución mensual.")


# ==============================================================
#  RENDER — TAB PERFIL DE PAÍS (reemplaza al viejo "Comparar" A/B)
#  Elegís un país y ves, con todo lo cargado hasta ahora:
#    1) cómo viene la economía categoría por categoría, con gráfico
#    2) de qué forma esos datos impactan en cada activo financiero,
#       empezando por su moneda
#    3) evolución mensual (general y por categoría) con gráficos
#    4) un informe narrativo de analista senior + gráficos adicionales
# ==============================================================

@st.cache_data(ttl=120, show_spinner=False)
def _df_registros_procesado(_supabase):
    """Trae los registros y les agrega categoria/score/peso/es_neutral/fecha_dt
    ya calculados, todo cacheado 2 min. Evita que Perfil de País y País vs País
    vuelvan a recorrer con .apply() todo el historial en cada interacción
    (cambiar país, cambiar filtro de año/mes, etc.)."""
    filas = _obtener_registros(_supabase)
    if not filas:
        return pd.DataFrame()
    df = pd.DataFrame(filas)
    df["categoria"] = df["evento"].map(lambda e: EVENTOS.get(e, {}).get("categoria", "Otros"))
    df["peso"] = df["evento"].map(lambda e: PESO_IMPACTO.get(EVENTOS.get(e, {}).get("impacto"), 1.0))
    df["es_neutral"] = df["evento"].map(lambda e: EVENTOS.get(e, {}).get("polaridad") == "neutral")
    df["score"] = df["impacto_mercado"].map(_signal_score)
    df["fecha_dt"] = pd.to_datetime(df["fecha"], errors="coerce")
    return df

def _tab_perfil_pais(supabase):
    st.caption(
        "Elegí un país para ver cómo viene mostrándose su economía con todo lo "
        "registrado hasta ahora, de qué forma esos datos impactan en cada tipo "
        "de activo financiero — empezando por su moneda —, cómo evolucionó mes "
        "a mes, y un informe narrativo de análisis fundamental con gráficos."
    )

    df = _df_registros_procesado(supabase)
    if df.empty:
        st.info("Todavía no hay registros cargados.")
        return

    paises_u = sorted(df["pais"].dropna().unique().tolist())
    if not paises_u:
        st.info("Todavía no hay países con registros cargados.")
        return

    pais = st.selectbox("🌎 País", paises_u, key="perfil_pais_sel")
    df_pais_todo = df[df["pais"] == pais].copy()

    if df_pais_todo.empty:
        st.info("Este país todavía no tiene registros cargados.")
        return


    # Se guarda el historial completo del país (sin el recorte por año/mes
    # de abajo) porque la evolución mes a mes y el outlook de tasas
    # necesitan ver más de un período para poder comparar.
    df_pais_puntuable_completo = df_pais_todo[~df_pais_todo["es_neutral"]].copy()

    fp1, fp2 = st.columns(2)
    with fp1:
        anios_u = ["Todos"] + sorted(
            df_pais_todo["fecha_dt"].dt.year.dropna().unique().astype(int).tolist(), reverse=True
        )
        f_anio = st.selectbox("📅 Filtrar por año", anios_u, key="perfil_f_anio")
    with fp2:
        f_mes = st.selectbox(
            "🗓️ Filtrar por mes", ["Todos"] + list(range(1, 13)),
            format_func=_formato_mes, key="perfil_f_mes",
        )

    if f_anio != "Todos":
        df_pais_todo = df_pais_todo[df_pais_todo["fecha_dt"].dt.year == f_anio]
    if f_mes != "Todos":
        df_pais_todo = df_pais_todo[df_pais_todo["fecha_dt"].dt.month == f_mes]

    if df_pais_todo.empty:
        st.info("No hay registros de este país para el período seleccionado.")
        return

    df_pais_puntuable = df_pais_todo[~df_pais_todo["es_neutral"]]

    st.markdown(f"#### 🧭 Panorama económico de {pais}")
    st.caption(
        f"Basado en {len(df_pais_todo)} evento(s) registrado(s) "
        f"({len(df_pais_puntuable)} con lectura de bueno/malo)."
    )

    categorias = sorted(df_pais_puntuable["categoria"].unique().tolist())
    if categorias:
        st.caption("👇 Desplegá cada categoría para ver qué mide, cómo se calculó su puntaje y qué eventos concretos lo componen.")
        for cat in categorias:
            sub = df_pais_puntuable[df_pais_puntuable["categoria"] == cat]
            prom, n = _promedio_ponderado_score(sub)
            emoji, texto = _asset_verdict(prom)
            resumen = f"{prom:+.2f} sobre {n} dato{'s' if n != 1 else ''}" if prom is not None else "sin datos"
            with st.expander(f"{cat}  ·  {emoji} {texto}  ({resumen})"):
                st.markdown(f"**📖 Qué mide esta categoría:** {_explicacion_categoria(cat)}.")

                if prom is not None:
                    st.markdown(
                        f"**🧮 Por qué da este puntaje ({prom:+.2f}):** cada uno de los {n} evento(s) "
                        "cargados en esta categoría aporta un puntaje individual —🟢 +1 si fue un buen "
                        "dato, 🟡 +0.5 si fue parcialmente bueno, ⚪ 0 si fue neutro, 🟠 −0.5 si fue "
                        "parcialmente malo, 🔴 −1 si fue un mal dato— según si el resultado (Real) quedó "
                        "por encima o por debajo de lo previsto y de lo anterior, ya corregido por el "
                        "criterio de cada indicador puntual (ver columna *Criterio aplicado* en la tabla "
                        "de abajo: no es lo mismo un dato donde 'más' es mejor —como el PBI o el PMI— que "
                        "uno donde 'más' es peor —como el desempleo o la inflación—). Esos puntajes "
                        "individuales se promedian ponderando por el impacto de cada evento (Muy Alto "
                        "pesa 3 veces más que uno Bajo), así una sorpresa en un dato de alta relevancia "
                        f"mueve más el resultado final que una en un dato secundario. Resultado: {emoji} "
                        f"**{texto}**."
                    )
                else:
                    st.markdown(
                        "Todavía no hay eventos con lectura cuantitativa de bueno/malo cargados en esta "
                        "categoría para el período seleccionado (puede que solo haya eventos cualitativos, "
                        "como comparecencias o actas)."
                    )

                st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
                st.markdown("**📋 Eventos que componen esta categoría** (de más reciente a más antiguo):")
                st.dataframe(_detalle_eventos_categoria(sub), use_container_width=True, hide_index=True)

        # Gráfico de barras del panorama, visible apenas se elige el
        # país — antes este gráfico solo aparecía más abajo, en el
        # informe de analista.
        nombres_panorama, valores_panorama = [], []
        for cat in categorias:
            sub = df_pais_puntuable[df_pais_puntuable["categoria"] == cat]
            prom, _ = _promedio_ponderado_score(sub)
            if prom is not None:
                nombres_panorama.append(cat)
                valores_panorama.append(prom)
        if nombres_panorama:
            orden = sorted(zip(nombres_panorama, valores_panorama), key=lambda x: x[1])
            nombres_panorama, valores_panorama = [x[0] for x in orden], [x[1] for x in orden]
            colores_panorama = [_color_de_score(v) for v in valores_panorama]
            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
            st.plotly_chart(
                _chart_barras_categorias(nombres_panorama, valores_panorama, colores_panorama,
                                          f"Panorama por categoría — {pais}"),
                use_container_width=True, key=f"panorama_barras_{pais}",
            )

        st.markdown("<hr style='margin:6px 0;border-color:#21262d'>", unsafe_allow_html=True)
    else:
        st.info("Este país solo tiene eventos cualitativos cargados (sin lectura de bueno/malo por categoría).")

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    st.markdown("#### 💹 Cómo impactan estos datos en los activos financieros")

    activos = _resumen_activos_pais(df_pais_todo)

    moneda_score, moneda_n = activos.get("divisas", (None, 0))
    _render_tarjeta_activo("💱 Su moneda (Divisas)", moneda_score, moneda_n, destacar=True)

    resto = [c for c in ASSET_FIELDS if c[0] != "divisas"]
    cols = st.columns(len(resto))
    for col, (campo, nombre) in zip(cols, resto):
        score, n = activos.get(campo, (None, 0))
        with col:
            _render_tarjeta_activo(nombre, score, n)

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    st.info(_texto_resumen_pais(pais, categorias, df_pais_puntuable, moneda_score))

    # ── Evolución mensual (general y por categoría) ──
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    st.markdown(f"#### 📈 Evolución mensual de {pais}")
    st.caption(
        "Puntaje ponderado agregado de cada mes, calculado con TODO el historial "
        "cargado del país (no se ve afectado por el filtro de año/mes elegido arriba), "
        "para poder comparar un período contra otro de forma consistente."
    )
    serie_general_pais = _serie_mensual(df_pais_puntuable_completo)
    fig_evol_general = _chart_evolucion_mensual(serie_general_pais, pais, "#3a7bd5",
                                                  titulo=f"Puntaje mensual agregado — {pais}")
    if fig_evol_general is not None:
        st.plotly_chart(fig_evol_general, use_container_width=True, key=f"panorama_evol_general_{pais}")
    else:
        st.info("Todavía no hay al menos dos meses distintos cargados para este país como para graficar su evolución.")

    fig_evol_cat_pais = _chart_evolucion_categorias(df_pais_puntuable_completo)
    if fig_evol_cat_pais is not None:
        st.plotly_chart(fig_evol_cat_pais, use_container_width=True, key=f"panorama_evol_cat_{pais}")

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    _render_fase_ciclo_pais(pais, df_pais_puntuable_completo)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    _render_informe_analista_pais(pais, df_pais_todo, df_pais_puntuable, categorias, activos,
                                   df_puntuable_completo=df_pais_puntuable_completo)

    st.caption(
        "Metodología: cada dato puntúa 🟢+1 / 🟡+0.5 / 🟠−0.5 / 🔴−1 según su lectura para cada "
        "activo (ya corregida por polaridad del evento), promediado ponderando por el impacto de "
        "cada evento (Muy Alto pesa 3x, Alto 2x, Medio 1x, Bajo 0.5x). La evolución mensual, la "
        "volatilidad, la racha de meses consecutivos y el outlook de tasas de interés se calculan "
        "sobre todo el historial cargado del país, independientemente del filtro de año/mes elegido "
        "arriba."
    )


# ==============================================================
#  CALIFICACIÓN DE LA DIFERENCIA ENTRE DOS PAÍSES
#  No alcanza con decir "quién gana": un +0.10 contra un -0.05 no es lo
#  mismo que un +1.00 contra un -1.00. Esta escala traduce la distancia
#  entre los dos puntajes (rango típico 0 a 2, ya que cada puntaje va de
#  -1 a +1) en una lectura de qué tan marcada es la ventaja fundamental.
# ==============================================================

def _calificar_diferencia(diff_abs):
    if diff_abs < 0.15:
        return "prácticamente parejo"
    if diff_abs < 0.5:
        return "ventaja leve"
    if diff_abs < 1.0:
        return "ventaja clara"
    return "ventaja muy fuerte"


def _etiqueta_ganador(ganador, val_a, val_b):
    """Arma el texto de la columna 'ganador' incluyendo qué tan fuerte es
    la diferencia, no solo quién quedó arriba."""
    if ganador == "Empate":
        return "⚖️ Empate"
    if val_a is None or val_b is None:
        return f"🏆 {ganador} (único con datos)"
    diff_abs = abs(val_a - val_b)
    return f"🏆 {ganador} — {_calificar_diferencia(diff_abs)}"


def _informe_analista_comparacion(pais_a, pais_b, categorias, df_a, df_b, activos_a, activos_b,
                                   ganados_a, ganados_b, empates,
                                   df_full_a=None, df_full_b=None):
    """Informe narrativo para la comparación entre dos países,
    resaltando el diferencial más marcado categoría por categoría, la
    implicancia relativa sobre cada moneda, quién viene mejorando más
    mes a mes (con volatilidad y racha de cada uno) y qué implica el
    conjunto de datos de cada uno sobre sus tasas de interés a futuro."""
    parrafos = []
    df_full_a = df_full_a if df_full_a is not None else df_a
    df_full_b = df_full_b if df_full_b is not None else df_b

    diffs = []
    for cat in categorias:
        prom_a, n_a = _promedio_ponderado_score(df_a[df_a["categoria"] == cat])
        prom_b, n_b = _promedio_ponderado_score(df_b[df_b["categoria"] == cat])
        if prom_a is not None and prom_b is not None:
            diffs.append((cat, prom_a - prom_b, prom_a, prom_b))

    if diffs:
        diffs.sort(key=lambda x: abs(x[1]), reverse=True)
        cat_top, diff_top, val_a_top, val_b_top = diffs[0]
        favorito = pais_a if diff_top > 0 else pais_b
        calif = _calificar_diferencia(abs(diff_top))
        parrafos.append(
            f"La diferencia fundamental más marcada entre ambas economías aparece en **{cat_top}** "
            f"(que {_explicacion_categoria(cat_top)}), donde "
            f"{favorito} muestra una {calif} ({val_a_top:+.2f} vs. {val_b_top:+.2f}). "
            + (f"Si el resto de las categorías se mantiene sin cambios, ese sector debería seguir siendo el "
               f"principal argumento a favor de {favorito} en la comparación relativa." if calif != "prácticamente parejo"
               else "Sin embargo, la distancia es chica y no alcanza para hablar de una ventaja estructural.")
        )
    else:
        parrafos.append(
            f"Todavía no hay categorías con datos cuantitativos en común entre {pais_a} y {pais_b} como "
            "para identificar dónde está la mayor brecha fundamental."
        )

    if ganados_a != ganados_b:
        lider = pais_a if ganados_a > ganados_b else pais_b
        rezagado = pais_b if ganados_a > ganados_b else pais_a
        n_lider = max(ganados_a, ganados_b)
        n_rezagado = min(ganados_a, ganados_b)
        parrafos.append(
            f"En el conteo agregado por categoría, **{lider}** se impone en {n_lider} de "
            f"{n_lider + n_rezagado + empates} categoría(s) comparables frente a {n_rezagado} de {rezagado} "
            f"({empates} empate(s)). Esto sugiere que la fortaleza relativa de {lider} no depende de un solo "
            "dato aislado, sino que se sostiene en más de un frente de la economía."
        )
    else:
        parrafos.append(
            f"El conteo agregado por categoría queda parejo entre {pais_a} y {pais_b} "
            f"({ganados_a} categoría(s) cada uno, {empates} empate(s)), lo que describe un cuadro "
            "fundamental sin un favorito claro por ahora."
        )

    moneda_a, _ = activos_a.get("divisas", (None, 0))
    moneda_b, _ = activos_b.get("divisas", (None, 0))
    if moneda_a is not None and moneda_b is not None:
        diff_m = moneda_a - moneda_b
        if abs(diff_m) < 0.15:
            parrafos.append(
                "En el mercado de cambios, ninguna de las dos monedas parte con una ventaja fundamental "
                "clara según lo cargado hasta ahora — el diferencial de tasas/crecimiento relativo no "
                "alcanza, por sí solo, para anticipar un ganador en el cruce entre ambas divisas."
            )
        else:
            favorito_m = pais_a if diff_m > 0 else pais_b
            calif_m = _calificar_diferencia(abs(diff_m))
            parrafos.append(
                f"Trasladado al cruce cambiario, el diferencial fundamental favorece a la moneda de "
                f"**{favorito_m}** ({calif_m}), en línea con el resultado agregado por categoría."
            )

    # Evolución mes a mes de cada país (usa todo el historial cargado
    # de cada uno, no el recorte de año/mes elegido en la pantalla),
    # más volatilidad y racha para describir la "calidad" del ciclo.
    serie_full_a = _serie_mensual(df_full_a)
    serie_full_b = _serie_mensual(df_full_b)
    comp_a = _comparar_ultimos_meses(serie_full_a)
    comp_b = _comparar_ultimos_meses(serie_full_b)
    diff_a = comp_a["diff"] if comp_a else None
    diff_b = comp_b["diff"] if comp_b else None

    if diff_a is None and diff_b is None:
        parrafos.append(
            f"Todavía no hay al menos dos meses distintos cargados para {pais_a} y/o {pais_b} como "
            "para comparar cuál de las dos economías viene mejorando más rápido mes a mes."
        )
    else:
        partes_evol = []
        for pais_x, comp_x, diff_x in [(pais_a, comp_a, diff_a), (pais_b, comp_b, diff_b)]:
            if diff_x is None:
                partes_evol.append(f"{pais_x} todavía no tiene dos meses comparables")
            elif diff_x >= 0.15:
                partes_evol.append(f"{pais_x} mejoró ({diff_x:+.2f}) respecto al mes previo")
            elif diff_x <= -0.15:
                partes_evol.append(f"{pais_x} empeoró ({diff_x:+.2f}) respecto al mes previo")
            else:
                partes_evol.append(f"{pais_x} se mantuvo estable ({diff_x:+.2f}) respecto al mes previo")
        texto_evol = " y ".join(partes_evol) + "."
        if diff_a is not None and diff_b is not None:
            if diff_a > diff_b + 0.1:
                texto_evol += f" En el margen, {pais_a} viene mejorando más rápido que {pais_b}."
            elif diff_b > diff_a + 0.1:
                texto_evol += f" En el margen, {pais_b} viene mejorando más rápido que {pais_a}."
            else:
                texto_evol += " El ritmo de mejora (o deterioro) reciente es parecido entre ambos."
        parrafos.append(f"En cuanto a la evolución mes a mes, {texto_evol}")

    # Volatilidad y racha comparadas
    vol_a, nmv_a = _volatilidad_score(serie_full_a)
    vol_b, nmv_b = _volatilidad_score(serie_full_b)
    racha_a, dir_a = _racha_actual(serie_full_a)
    racha_b, dir_b = _racha_actual(serie_full_b)
    partes_calidad = []
    if vol_a is not None and vol_b is not None:
        if abs(vol_a - vol_b) >= 0.1:
            mas_volatil = pais_a if vol_a > vol_b else pais_b
            mas_estable = pais_b if vol_a > vol_b else pais_a
            partes_calidad.append(
                f"el ciclo de {mas_estable} viene siendo más consistente mes a mes que el de {mas_volatil} "
                f"(desvíos de {min(vol_a, vol_b):.2f} vs. {max(vol_a, vol_b):.2f} respectivamente)"
            )
        else:
            partes_calidad.append(
                f"ambos países muestran una consistencia mes a mes similar (desvíos de {vol_a:.2f} y {vol_b:.2f})"
            )
    for pais_x, racha_x, dir_x in [(pais_a, racha_a, dir_a), (pais_b, racha_b, dir_b)]:
        if racha_x and dir_x:
            verbo = "mejorando" if dir_x == "mejora" else "empeorando"
            partes_calidad.append(f"{pais_x} lleva {racha_x} mes(es) consecutivo(s) {verbo}")
    if partes_calidad:
        parrafos.append(("En términos de calidad del ciclo, " + "; ".join(partes_calidad) + ".").capitalize())

    # Implicancia comparada sobre tasas de interés a futuro
    outlook_a = _outlook_tasas(df_full_a)
    outlook_b = _outlook_tasas(df_full_b)
    hawkish_a = outlook_a[0] if outlook_a else None
    hawkish_b = outlook_b[0] if outlook_b else None
    if hawkish_a is None and hawkish_b is None:
        parrafos.append(
            f"Todavía no hay datos suficientes de inflación, empleo, crecimiento o actividad de "
            f"{pais_a} y {pais_b} como para comparar la implicancia sobre sus tasas de interés a futuro."
        )
    else:
        def _describir_outlook(pais_x, score_x):
            if score_x is None:
                return f"{pais_x} no tiene datos suficientes para estimar su outlook de tasas"
            if score_x >= 0.15:
                return f"{pais_x} muestra un sesgo hacia tasas más altas o sin apuro para recortar ({score_x:+.2f})"
            if score_x <= -0.15:
                return f"{pais_x} muestra un sesgo hacia tasas más bajas ({score_x:+.2f})"
            return f"{pais_x} muestra un balance mixto sin sesgo claro sobre tasas ({score_x:+.2f})"

        parrafos.append(
            "En cuanto a política monetaria futura, " + _describir_outlook(pais_a, hawkish_a) + ", mientras que "
            + _describir_outlook(pais_b, hawkish_b) + ". "
            + ("Esto sugiere un diferencial de tasas que podría ampliarse a favor de la moneda con el sesgo "
               "más restrictivo, todo lo demás constante." if hawkish_a is not None and hawkish_b is not None else "")
        )

    return parrafos


def _render_informe_analista_comparacion(pais_a, pais_b, categorias, df_a, df_b, activos_a, activos_b,
                                          ganados_a, ganados_b, empates,
                                          df_full_a=None, df_full_b=None):
    st.markdown("#### 🧠 Informe de analista senior")
    for p in _informe_analista_comparacion(pais_a, pais_b, categorias, df_a, df_b, activos_a, activos_b,
                                            ganados_a, ganados_b, empates, df_full_a, df_full_b):
        st.markdown(p)

    g1, g2 = st.columns(2)
    with g1:
        nombres_cat, dif_valores = [], []
        for cat in categorias:
            prom_a, _ = _promedio_ponderado_score(df_a[df_a["categoria"] == cat])
            prom_b, _ = _promedio_ponderado_score(df_b[df_b["categoria"] == cat])
            if prom_a is not None and prom_b is not None:
                nombres_cat.append(cat)
                dif_valores.append(prom_a - prom_b)
        if nombres_cat:
            orden = sorted(zip(nombres_cat, dif_valores), key=lambda x: x[1])
            nombres_cat, dif_valores = [x[0] for x in orden], [x[1] for x in orden]
            colores = ["#3a7bd5" if v >= 0 else "#f0883e" for v in dif_valores]
            fig = go.Figure(go.Bar(
                x=dif_valores, y=nombres_cat, orientation="h",
                marker=dict(color=colores),
                text=[f"{v:+.2f}" for v in dif_valores], textposition="outside",
            ))
            fig.update_layout(
                title=f"Diferencial por categoría ({pais_a} − {pais_b})",
                xaxis=dict(range=[-2, 2], title=f"◀ favorece a {pais_b}   |   favorece a {pais_a} ▶", zerolinecolor="#3a3a3a"),
                yaxis=dict(autorange="reversed"),
                height=max(260, 46 * len(nombres_cat)),
                margin=dict(l=10, r=10, t=40, b=40),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#e6edf3"),
            )
            st.plotly_chart(fig, use_container_width=True, key=f"cmpp_chart_diff_{pais_a}_{pais_b}")
    with g2:
        labels = [nombre for _, nombre in ASSET_FIELDS]
        valores_a = [activos_a.get(campo, (0.0, 0))[0] or 0.0 for campo, _ in ASSET_FIELDS]
        valores_b = [activos_b.get(campo, (0.0, 0))[0] or 0.0 for campo, _ in ASSET_FIELDS]
        fig2 = go.Figure()
        fig2.add_trace(go.Scatterpolar(r=valores_a + [valores_a[0]], theta=labels + [labels[0]],
                                        fill="toself", name=pais_a, line=dict(color="#3a7bd5")))
        fig2.add_trace(go.Scatterpolar(r=valores_b + [valores_b[0]], theta=labels + [labels[0]],
                                        fill="toself", name=pais_b, line=dict(color="#f0883e")))
        fig2.update_layout(
            title=f"Activos financieros — {pais_a} vs {pais_b}",
            polar=dict(radialaxis=dict(visible=True, range=[-1, 1], color="#8b949e"),
                       angularaxis=dict(color="#e6edf3"), bgcolor="rgba(0,0,0,0)"),
            showlegend=True, height=420, margin=dict(l=30, r=30, t=40, b=30),
            paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#e6edf3"),
        )
        st.plotly_chart(fig2, use_container_width=True, key=f"cmpp_chart_radar_{pais_a}_{pais_b}")


# ==============================================================
#  RENDER — TAB PAÍS VS PAÍS
#  Compara todo lo cargado de dos países, categoría por categoría, y
#  además de qué forma esos mismos datos impactan en cada activo
#  financiero (divisas/moneda, bonos, acciones, oro y cripto) de cada
#  país, para saber no solo quién viene "mejor" en lo económico sino
#  qué activo de cada país se ve más favorecido o perjudicado — y con
#  qué contundencia (fundamentalmente) según la magnitud de la
#  diferencia entre los dos puntajes.
# ==============================================================

def _tab_comparar_paises(supabase):
    st.caption(
        "Elegí dos países y compará, categoría por categoría, cuál viene "
        "mostrando datos económicos más fuertes según todo lo registrado hasta ahora, "
        "cómo impactan esos datos en cada activo financiero — incluida su moneda —, "
        "cómo evolucionó cada uno mes a mes, y un informe narrativo de análisis "
        "fundamental comparado. "
        "El puntaje ya tiene en cuenta si 'mayor' es bueno o malo para cada indicador "
        "(desempleo, inflación y tasas puntúan al revés que PBI o PMI) y pondera más los "
        "eventos de mayor impacto. Los eventos cualitativos (comparecencias, actas, etc.) "
        "no entran en el cálculo por categoría económica."
    )

    df = _df_registros_procesado(supabase)
    if df.empty:
        st.info("Todavía no hay registros cargados para comparar.")
        return

    # Se guarda el histórico completo (sin el recorte por año/mes de
    # abajo) porque la evolución mes a mes y el outlook de tasas de
    # cada país necesitan ver más de un período para poder comparar.
    df_puntuable_completo_global = df[~df["es_neutral"]].copy()

    fp1, fp2 = st.columns(2)
    with fp1:
        anios_u = ["Todos"] + sorted(
            df["fecha_dt"].dt.year.dropna().unique().astype(int).tolist(), reverse=True
        )
        f_anio = st.selectbox("📅 Filtrar por año", anios_u, key="cmpp_f_anio")
    with fp2:
        f_mes = st.selectbox(
            "🗓️ Filtrar por mes", ["Todos"] + list(range(1, 13)),
            format_func=_formato_mes, key="cmpp_f_mes",
        )

    if f_anio != "Todos":
        df = df[df["fecha_dt"].dt.year == f_anio]
    if f_mes != "Todos":
        df = df[df["fecha_dt"].dt.month == f_mes]

    if df.empty:
        st.info("No hay registros para el período seleccionado.")
        return

    df_puntuable = df[~df["es_neutral"]].copy()

    paises_u = sorted(df["pais"].dropna().unique().tolist())
    if len(paises_u) < 2:
        st.info("Necesitás registros de al menos dos países distintos (en el período elegido) para poder comparar.")
        return

    c1, c2 = st.columns(2)
    with c1:
        pais_a = st.selectbox("🅰️ País A", paises_u, index=0, key="cmpp_pais_a")
    with c2:
        opciones_b = [p for p in paises_u if p != pais_a] or paises_u
        pais_b = st.selectbox("🅱️ País B", opciones_b, index=0, key="cmpp_pais_b")

    df_a = df_puntuable[df_puntuable["pais"] == pais_a]
    df_b = df_puntuable[df_puntuable["pais"] == pais_b]

    categorias = sorted(set(df_a["categoria"].unique().tolist()) | set(df_b["categoria"].unique().tolist()))

    ganados_a = ganados_b = empates = 0

    if categorias:
        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        st.markdown(f"#### 📊 Resultado por categoría — {pais_a} vs {pais_b}")

        for cat in categorias:
            sub_a = df_a[df_a["categoria"] == cat]
            sub_b = df_b[df_b["categoria"] == cat]
            prom_a, n_a = _promedio_ponderado_score(sub_a)
            prom_b, n_b = _promedio_ponderado_score(sub_b)

            if prom_a is None and prom_b is None:
                continue

            if prom_a is None:
                ganador = pais_b
                ganados_b += 1
            elif prom_b is None:
                ganador = pais_a
                ganados_a += 1
            elif abs(prom_a - prom_b) < 1e-9:
                ganador = "Empate"
                empates += 1
            elif prom_a > prom_b:
                ganador = pais_a
                ganados_a += 1
            else:
                ganador = pais_b
                ganados_b += 1

            col_cat, col_a, col_b, col_gan = st.columns([2, 2, 2, 1.6])
            with col_cat:
                st.markdown(f"**{cat}**")
            with col_a:
                txt_a = f"{prom_a:+.2f}  ({n_a} dato{'s' if n_a != 1 else ''})" if prom_a is not None else "Sin datos"
                st.caption(f"{pais_a}: {txt_a}")
            with col_b:
                txt_b = f"{prom_b:+.2f}  ({n_b} dato{'s' if n_b != 1 else ''})" if prom_b is not None else "Sin datos"
                st.caption(f"{pais_b}: {txt_b}")
            with col_gan:
                st.markdown(_etiqueta_ganador(ganador, prom_a, prom_b))
            st.markdown("<hr style='margin:4px 0;border-color:#21262d'>", unsafe_allow_html=True)

        # Gráfico comparativo por categoría — visible apenas se ven los
        # resultados, no solo dentro del informe de analista más abajo.
        nombres_cmp, val_a_cmp, val_b_cmp = [], [], []
        for cat in categorias:
            prom_a, _ = _promedio_ponderado_score(df_a[df_a["categoria"] == cat])
            prom_b, _ = _promedio_ponderado_score(df_b[df_b["categoria"] == cat])
            if prom_a is not None or prom_b is not None:
                nombres_cmp.append(cat)
                val_a_cmp.append(prom_a if prom_a is not None else 0.0)
                val_b_cmp.append(prom_b if prom_b is not None else 0.0)
        if nombres_cmp:
            fig_barras_cmp = go.Figure()
            fig_barras_cmp.add_trace(go.Bar(y=nombres_cmp, x=val_a_cmp, name=pais_a, orientation="h", marker=dict(color="#3a7bd5")))
            fig_barras_cmp.add_trace(go.Bar(y=nombres_cmp, x=val_b_cmp, name=pais_b, orientation="h", marker=dict(color="#f0883e")))
            fig_barras_cmp.update_layout(
                title=f"Panorama por categoría — {pais_a} vs {pais_b}",
                barmode="group",
                xaxis=dict(range=[-1.2, 1.2], title="Puntaje ponderado (−1 a +1)", zerolinecolor="#3a3a3a"),
                yaxis=dict(autorange="reversed"),
                height=max(280, 50 * len(nombres_cmp)),
                margin=dict(l=10, r=10, t=40, b=10),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#e6edf3"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            )
            st.plotly_chart(fig_barras_cmp, use_container_width=True, key=f"cmpp_panorama_barras_{pais_a}_{pais_b}")
    else:
        st.info("No hay categorías con eventos puntuables en común todavía (comparecencias, actas y "
                 "posicionamiento CFTC no cuentan para el puntaje por categoría).")

    # ── Impacto en activos financieros ──
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    st.markdown(f"#### 💹 Impacto en activos financieros — {pais_a} vs {pais_b}")
    st.caption(
        "Mismo criterio de ponderación por impacto del evento, aplicado directamente sobre la "
        "lectura de cada activo (divisas, bonos, acciones, oro y cripto) de cada país."
    )

    df_todos_a = df[df["pais"] == pais_a]
    df_todos_b = df[df["pais"] == pais_b]
    activos_a = _resumen_activos_pais(df_todos_a)
    activos_b = _resumen_activos_pais(df_todos_b)

    ganados_activos_a = ganados_activos_b = empates_activos = 0

    for campo, nombre in ASSET_FIELDS:
        score_a, n_a = activos_a.get(campo, (None, 0))
        score_b, n_b = activos_b.get(campo, (None, 0))
        if score_a is None and score_b is None:
            continue

        if score_a is None:
            ganador = pais_b
            ganados_activos_b += 1
        elif score_b is None:
            ganador = pais_a
            ganados_activos_a += 1
        elif abs(score_a - score_b) < 1e-9:
            ganador = "Empate"
            empates_activos += 1
        elif score_a > score_b:
            ganador = pais_a
            ganados_activos_a += 1
        else:
            ganador = pais_b
            ganados_activos_b += 1

        etiqueta = f"**{nombre}**" if campo == "divisas" else nombre
        col_act, col_a, col_b, col_gan = st.columns([2, 2, 2, 1.6])
        with col_act:
            st.markdown(etiqueta)
        with col_a:
            txt_a = f"{score_a:+.2f}  ({n_a} dato{'s' if n_a != 1 else ''})" if score_a is not None else "Sin datos"
            st.caption(f"{pais_a}: {txt_a}")
        with col_b:
            txt_b = f"{score_b:+.2f}  ({n_b} dato{'s' if n_b != 1 else ''})" if score_b is not None else "Sin datos"
            st.caption(f"{pais_b}: {txt_b}")
        with col_gan:
            st.markdown(_etiqueta_ganador(ganador, score_a, score_b))
        st.markdown("<hr style='margin:4px 0;border-color:#21262d'>", unsafe_allow_html=True)

    moneda_a, _ = activos_a.get("divisas", (None, 0))
    moneda_b, _ = activos_b.get("divisas", (None, 0))
    if moneda_a is not None and moneda_b is not None:
        diff = moneda_a - moneda_b
        diff_abs = abs(diff)
        if diff_abs < 0.15:
            st.info(
                "💱 En términos fundamentales, ambas monedas muestran un sesgo macro "
                "prácticamente parejo — ninguna se ve claramente más fuerte que la otra por ahora."
            )
        else:
            favorecido = pais_a if diff > 0 else pais_b
            otro = pais_b if diff > 0 else pais_a
            if diff_abs >= 1.0:
                calif = "mucho más fuerte"
            elif diff_abs >= 0.5:
                calif = "claramente más fuerte"
            else:
                calif = "levemente más fuerte"
            st.success(
                f"💱 En términos fundamentales, la moneda de **{favorecido}** viene **{calif}** "
                f"que la de **{otro}** según los datos macro cargados "
                f"(diferencia de {diff_abs:.2f} puntos sobre una escala de 0 a 2)."
            )
    elif moneda_a is not None or moneda_b is not None:
        unico = pais_a if moneda_a is not None else pais_b
        st.info(
            f"💱 Todavía solo hay datos de moneda cargados para **{unico}**; falta más información "
            "del otro país para poder comparar la fortaleza fundamental entre ambas monedas."
        )

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    st.markdown("#### 🏁 Resultado general")
    r1, r2, r3 = st.columns(3)
    r1.metric(f"Categorías ganadas · {pais_a}", ganados_a)
    r2.metric(f"Categorías ganadas · {pais_b}", ganados_b)
    r3.metric("Empates", empates)

    r4, r5, r6 = st.columns(3)
    r4.metric(f"Activos favorables · {pais_a}", ganados_activos_a)
    r5.metric(f"Activos favorables · {pais_b}", ganados_activos_b)
    r6.metric("Activos parejos", empates_activos)

    if ganados_a > ganados_b:
        st.success(f"📈 En conjunto, **{pais_a}** viene mostrando datos económicos más fuertes que **{pais_b}** según lo registrado hasta ahora.")
    elif ganados_b > ganados_a:
        st.success(f"📈 En conjunto, **{pais_b}** viene mostrando datos económicos más fuertes que **{pais_a}** según lo registrado hasta ahora.")
    else:
        st.info("📊 Ambos países muestran un desempeño económico parejo según lo registrado hasta ahora.")

    df_full_a = df_puntuable_completo_global[df_puntuable_completo_global["pais"] == pais_a]
    df_full_b = df_puntuable_completo_global[df_puntuable_completo_global["pais"] == pais_b]

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    _render_fase_ciclo_comparada(pais_a, pais_b, df_full_a, df_full_b)

    # ── Evolución mensual comparada, categoría por categoría ──
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    st.markdown(f"#### 📈 Evolución mensual por categoría — {pais_a} vs {pais_b}")
    st.caption(
        "Elegí una categoría para ver cómo vino evolucionando mes a mes en cada país. Se calcula "
        "sobre todo el historial cargado de cada uno (no se ve afectado por el filtro de año/mes "
        "elegido arriba), para poder comparar un período contra otro de forma consistente."
    )

    categorias_evol = sorted(
        set(df_full_a["categoria"].unique().tolist()) | set(df_full_b["categoria"].unique().tolist())
    )
    if categorias_evol:
        conteos_cat = {
            cat: len(df_full_a[df_full_a["categoria"] == cat]) + len(df_full_b[df_full_b["categoria"] == cat])
            for cat in categorias_evol
        }
        cat_default = max(conteos_cat, key=conteos_cat.get)
        idx_default = categorias_evol.index(cat_default)
        cat_elegida = st.selectbox(
            "📂 Categoría a graficar", categorias_evol, index=idx_default, key="cmpp_evol_cat_sel",
        )
        st.caption(f"ℹ️ {cat_elegida}: {_explicacion_categoria(cat_elegida)}.")

        sub_a_cat = df_full_a[df_full_a["categoria"] == cat_elegida]
        sub_b_cat = df_full_b[df_full_b["categoria"] == cat_elegida]
        fig_evol_cat_cmp = _chart_evolucion_comparada(
            _serie_mensual(sub_a_cat), _serie_mensual(sub_b_cat), pais_a, pais_b,
            titulo=f"Evolución mensual — {cat_elegida} ({pais_a} vs {pais_b})",
        )
        if fig_evol_cat_cmp is not None:
            st.plotly_chart(
                fig_evol_cat_cmp, use_container_width=True,
                key=f"cmpp_evol_cat_{pais_a}_{pais_b}_{cat_elegida}",
            )
        else:
            st.info(
                f"Todavía no hay al menos dos meses distintos cargados en **{cat_elegida}** para "
                f"{pais_a} y/o {pais_b} como para graficar su evolución comparada en esta categoría."
            )
    else:
        st.info("Todavía no hay categorías con eventos puntuables cargados para estos dos países.")

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    _render_informe_analista_comparacion(
        pais_a, pais_b, categorias, df_a, df_b, activos_a, activos_b,
        ganados_a, ganados_b, empates, df_full_a, df_full_b,
    )

    st.caption(
        "Metodología: cada dato puntúa 🟢+1 / 🟡+0.5 / 🟠−0.5 / 🔴−1 según si fue mejor o peor "
        "para la economía del país (ya corregido por polaridad: en desempleo, inflación, tasas de "
        "interés, costos laborales y rendimientos de deuda, 'mayor' puntúa negativo; en PBI, PMI, "
        "empleo creado, ventas y vivienda, 'mayor' puntúa positivo). Ese puntaje se promedia "
        "ponderando por el impacto del evento (Muy Alto pesa 3x, Alto 2x, Medio 1x, Bajo 0.5x). "
        "Para el impacto en activos financieros se aplica la misma ponderación, pero directamente "
        "sobre la lectura de cada activo (divisas, bonos, acciones, oro, cripto) en lugar del "
        "veredicto general de bueno/malo, y los eventos cualitativos sin lectura de bueno/malo "
        "quedan afuera del cálculo por categoría. La evolución mensual, la volatilidad y la racha "
        "de cada país se calculan sobre todo su historial cargado, independientemente del filtro "
        "de año/mes elegido arriba. Además de decir quién queda arriba, cada fila indica qué tan "
        "grande es esa diferencia (prácticamente parejo / ventaja leve / ventaja clara / ventaja "
        "muy fuerte) según la distancia entre los dos puntajes, para distinguir un dato ajustado de "
        "una diferencia fundamental real."
    )


# ==============================================================
#  RENDER — NOTICIAS (todos ven, solo admin publica/borra)
# ==============================================================

def _tab_noticias(supabase, es_admin, user_id, user_email):
    if es_admin:
        with st.expander("✏️ Publicar noticia", expanded=True):
            f1, f2 = st.columns([1, 2])
            with f1:
                fecha_noticia = st.date_input("📅 Fecha de la noticia", value=date.today(), key="cal_noti_fecha")
            with f2:
                titulo = st.text_input("Título", key="cal_noti_titulo")
            categoria = st.text_input("Categoría (opcional)", key="cal_noti_categoria",
                                       placeholder="Ej: Fed, Inflación, Mercados...")
            contenido = st.text_area("Contenido", key="cal_noti_contenido", height=120)
            if st.button("📰 Publicar", type="primary", key="cal_noti_btn_publicar"):
                if not titulo.strip():
                    st.warning("⚠️ El título es obligatorio.")
                else:
                    try:
                        _guardar_noticia(supabase, titulo, contenido, categoria, fecha_noticia, user_id, user_email)
                        _obtener_noticias.clear()
                        st.success("✅ Noticia publicada.")
                        for k in ["cal_noti_titulo", "cal_noti_categoria", "cal_noti_contenido"]:
                            st.session_state.pop(k, None)
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error al publicar: {e}")

    top1, top2 = st.columns([3, 1])
    with top1:
        st.caption("Noticias y análisis")
    with top2:
        if st.button("↺ Actualizar", use_container_width=True, key="cal_noti_refresh"):
            _obtener_noticias.clear()
            st.rerun()

    noticias = _obtener_noticias(supabase, 100)
    if not noticias:
        st.info("Todavía no hay noticias publicadas.")
        return

    def _clave_orden(n):
        return n.get("fecha_noticia") or (n.get("created_at") or "")

    noticias = sorted(noticias, key=_clave_orden, reverse=True)

    for n in noticias:
        fecha_noticia = n.get("fecha_noticia")
        if fecha_noticia:
            try:
                fecha_txt = datetime.fromisoformat(fecha_noticia).strftime("%d/%m/%Y")
            except Exception:
                fecha_txt = fecha_noticia
        else:
            fecha_txt = n.get("created_at", "")
            try:
                fecha_txt = datetime.fromisoformat(fecha_txt.replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M")
            except Exception:
                pass

        col_txt, col_del = st.columns([6, 1]) if es_admin else (st.container(), None)
        with (col_txt if es_admin else st.container()):
            st.markdown(
                f'<div style="background:#0d1117;border:1px solid #21262d;border-left:4px solid #3a7bd5;'
                f'border-radius:8px;padding:14px 16px;margin-bottom:10px">'
                f'<div style="font-size:14px;font-weight:700;color:#e6edf3">{n.get("titulo","")}</div>'
                f'<div style="font-size:10.5px;color:#6b7d9a;margin:2px 0 8px 0">'
                f'{fecha_txt} · {n.get("autor_email","")}</div>'
                f'<div style="font-size:12.5px;color:#c9d1d9;line-height:1.6;white-space:pre-wrap">'
                f'{n.get("contenido","")}</div>'
                + (f'<span style="display:inline-block;margin-top:8px;font-size:10px;font-weight:700;'
                   f'padding:2px 9px;border-radius:10px;background:#3a7bd522;color:#3a7bd5">'
                   f'{n["categoria"]}</span>' if n.get("categoria") else "")
                + "</div>",
                unsafe_allow_html=True,
            )
        if es_admin:
            with col_del:
                if st.button("🗑️", key=f"cal_noti_del_{n['id']}", help="Eliminar noticia"):
                    try:
                        _borrar_noticia(supabase, n["id"])
                        _obtener_noticias.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ {e}")


# ==============================================================
#  ENTRY POINT — llamar desde app.py
# ==============================================================

def render_calendario_economico(supabase, user_id, user_email):
    """Uso desde app.py:
        from modulo_calendario import render_calendario_economico
        render_calendario_economico(supabase, USER_ID, st.session_state['usuario'].email)

    Muestra el calendario económico (carga de eventos + carga masiva +
    historial con interpretación macro completa, editable/eliminable
    por el admin), una pestaña de "Perfil de País" (cómo está un país,
    graficado por categoría y en el tiempo, cómo impacta en cada activo
    financiero, e informe de analista senior con gráficos) y una
    pestaña de comparación país vs país agrupada por categoría, por
    activo financiero, con evolución mensual comparada e informe
    narrativo. Las noticias son un módulo aparte, ver render_noticias()
    más abajo.
    """
    es_admin = _es_admin(user_email)

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #e3b341;
         border-radius:14px; padding:22px 28px; margin-bottom:20px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:4px">
        📊 Calendario Económico
      </div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.6">
        Registro de eventos macro con interpretación automática completa
        (divisas, bonos, acciones, oro y cripto), carga masiva desde
        Excel/CSV, su historial editable, el perfil macro de cada país
        con gráficos de panorama y evolución mensual, un informe de
        analista senior, y su comparación frente a otros países.
      </div>
    </div>
    """, unsafe_allow_html=True)

    _OPCIONES_CAL = ["📝 Registrar", "📦 Carga Masiva", "📅 Calendario Económico",
                      "🌎 Perfil de País", "🌍 País vs País"]
    _seccion_cal = st.radio(
        "Sección del calendario", _OPCIONES_CAL, horizontal=True,
        label_visibility="collapsed", key="cal_seccion_activa",
    )
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    if _seccion_cal == _OPCIONES_CAL[0]:
        _tab_registrar(supabase, user_id, es_admin)
    elif _seccion_cal == _OPCIONES_CAL[1]:
        _tab_carga_masiva(supabase, user_id, es_admin)
    elif _seccion_cal == _OPCIONES_CAL[2]:
        _tab_historial(supabase, es_admin)
    elif _seccion_cal == _OPCIONES_CAL[3]:
        _tab_perfil_pais(supabase)
    elif _seccion_cal == _OPCIONES_CAL[4]:
        _tab_comparar_paises(supabase)


def render_noticias(supabase, user_id, user_email):
    """Uso desde app.py:
        from modulo_calendario import render_noticias
        render_noticias(supabase, USER_ID, st.session_state['usuario'].email)

    Módulo independiente de Noticias — llamalo desde otra sección/página
    de tu app, separado del Calendario Económico.
    """
    es_admin = _es_admin(user_email)

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d1520 0%,#0a1830 50%,#0d1117 100%);
         border:1px solid #21262d; border-top:2px solid #3a7bd5;
         border-radius:14px; padding:22px 28px; margin-bottom:20px;">
      <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:4px">
        📰 Noticias
      </div>
      <div style="font-size:12px;color:#6b7d9a;line-height:1.6">
        Noticias y análisis de mercado.
      </div>
    </div>
    """, unsafe_allow_html=True)

    _tab_noticias(supabase, es_admin, user_id, user_email)
