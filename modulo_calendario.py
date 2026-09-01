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
# ==============================================================

import streamlit as st
import pandas as pd
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
    # Balanza/cuenta corriente: números "más altos" (más superávit o
    # menos déficit) son mejores → directa. Precio de importación =
    # inflación importada → inversa. Precio de exportación = mejores
    # términos de intercambio para el país → directa.
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
    # Inventarios: la señal es ambigua (puede ser reposición sana o
    # señal de demanda floja) → se dejan en "neutral" para no forzar
    # una lectura de bueno/malo que no está clara.
    "Gasto en construcción":                          {"categoria": "Industria", "unidad": "%", "impacto": "Medio", "polaridad": "directa"},
    "Pedidos de fábrica":                              {"categoria": "Industria", "unidad": "%", "impacto": "Medio", "polaridad": "directa"},
    "Producción manufacturera":                       {"categoria": "Industria", "unidad": "%", "impacto": "Medio", "polaridad": "directa"},
    "Inventarios de negocios":                        {"categoria": "Industria", "unidad": "%", "impacto": "Bajo",  "polaridad": "neutral"},
    "Inventarios de los minoristas exc. automóviles": {"categoria": "Industria", "unidad": "%", "impacto": "Bajo",  "polaridad": "neutral"},
    "Obras de construcción realizadas":               {"categoria": "Industria", "unidad": "%", "impacto": "Bajo",  "polaridad": "directa"},
    "Índice de Producción Industrial (China)":        {"categoria": "Industria", "unidad": "%", "impacto": "Medio", "polaridad": "directa"},

    # ---- Empleo ----
    # Regla del analista: los indicadores de CANTIDAD de empleo (más
    # empleos creados, más vacantes, más participación) son "directa".
    # Los de DESEMPLEO/costo laboral (más desempleo, más solicitudes,
    # más costo salarial de lo esperado) son "inversa".
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
    # El tipo hipotecario es una TASA: más alta = crédito más caro =
    # peor para el sector → inversa. El resto son indicadores de
    # actividad/precio de venta, donde más alto = sector más fuerte.
    "Índice Halifax de precios de la vivienda":       {"categoria": "Vivienda", "unidad": "%", "impacto": "Medio", "polaridad": "directa"},
    "Hipotecas sobre viviendas":                      {"categoria": "Vivienda", "unidad": "%", "impacto": "Bajo",  "polaridad": "directa"},
    "Venta de viviendas pendientes":                  {"categoria": "Vivienda", "unidad": "%", "impacto": "Medio", "polaridad": "directa"},
    "Precios de Vivienda S&P/Case-Shiller":           {"categoria": "Vivienda", "unidad": "%", "impacto": "Medio", "polaridad": "directa"},
    "Tipo hipotecario":                               {"categoria": "Vivienda", "unidad": "%", "impacto": "Bajo",  "polaridad": "inversa"},
    "Índice de precios de viviendas nuevas":          {"categoria": "Vivienda", "unidad": "%", "impacto": "Bajo",  "polaridad": "directa"},

    # ---- Política Monetaria / Crédito / Fiscal ----
    # Tasa del PBoC: igual que cualquier tasa de interés, más alta =
    # restrictivo = inversa. Balance fiscal: "más alto" (menos
    # negativo/superávit mayor) = mejor → directa (ver corrección de
    # signo en CATEGORIA_INTERPRETACION más abajo).
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
    # Se mantiene consistente con la lectura ya curada de "Inventarios
    # de petróleo crudo (EIA)": más oferta/inventario = presión
    # bajista sobre el precio del crudo = desinflacionario = directa
    # (bueno para el mercado en general, aunque sea malo puntualmente
    # para el sector energético).
    "Reservas semanales de crudo del API":            {"categoria": "Energía", "unidad": "M Barriles", "impacto": "Medio", "polaridad": "directa"},
    "Número de plataformas petrolíferas (Baker Hughes)": {"categoria": "Energía", "unidad": "u", "impacto": "Bajo", "polaridad": "directa"},
    "Informe mensual de la AIE":                      {"categoria": "Energía", "unidad": "", "impacto": "Bajo", "polaridad": "neutral"},
    "Informe mensual de la OPEP":                     {"categoria": "Energía", "unidad": "", "impacto": "Bajo", "polaridad": "neutral"},
    "Previsión energética a corto plazo de la EIA":   {"categoria": "Energía", "unidad": "", "impacto": "Bajo", "polaridad": "neutral"},

    # ---- Agricultura ----
    "Informe WASDE":                                  {"categoria": "Agricultura", "unidad": "", "impacto": "Bajo", "polaridad": "neutral"},

    # ---- Deuda pública ----
    # Subasta de deuda: rendimiento más alto de lo esperado = el
    # mercado exige más prima por el riesgo = inversa.
    "Subasta de deuda pública":                       {"categoria": "Deuda Pública", "unidad": "%", "impacto": "Medio", "polaridad": "inversa"},

    # ---- Posicionamiento especulativo (CFTC) ----
    # No es un dato de "salud económica": es posicionamiento de
    # traders. Se deja neutral para no mezclarlo con el puntaje de
    # fortaleza económica del comparador país vs país.
    "Posiciones netas especulativas (CFTC)":          {"categoria": "Posicionamiento Especulativo", "unidad": "K", "impacto": "Bajo", "polaridad": "neutral"},

    # ---- Comentarios de funcionarios / eventos especiales ----
    "Comparecencia de funcionario de banco central":  {"categoria": "Comentarios de Funcionarios", "unidad": "", "impacto": "Medio", "polaridad": "neutral"},
    "Rueda de prensa de la NBS":                       {"categoria": "Comentarios de Funcionarios", "unidad": "", "impacto": "Medio", "polaridad": "neutral"},
    "Declaraciones de Trump, presidente de EE.UU.":   {"categoria": "Comentarios Políticos", "unidad": "", "impacto": "Alto", "polaridad": "neutral"},
    "Simposio de Jackson Hole":                       {"categoria": "Evento Especial", "unidad": "", "impacto": "Alto", "polaridad": "neutral"},
}

EVENTOS.update(EVENTOS_EXTENDIDOS)

# Diccionario de interpretación macro (idéntico al de Apps Script).
# Se deja completo para no perder cobertura de eventos.
INTERPRETACION_MACRO = {
    "IPC (inflación general)": {
        "mayor": {"divisas": "🟢 Moneda fuerte por inflación elevada", "bonos": "🔴 Caída de bonos soberanos", "acciones": "🔴 Negativo para acciones e índices", "oro": "🟢 Oro favorecido como cobertura", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Política monetaria restrictiva", "riesgo": "🔴 Risk-off", "lectura": "La inflación supera lo esperado y aumenta la presión sobre el banco central."},
        "menor": {"divisas": "🔴 Debilidad monetaria", "bonos": "🟢 Suba de bonos", "acciones": "🟢 Positivo para índices", "oro": "🔴 Menor cobertura inflacionaria", "crypto": "🟢 Mejora del apetito por riesgo", "politica": "📉 Política monetaria flexible", "riesgo": "🟢 Risk-on", "lectura": "La inflación se desacelera y mejora el entorno financiero."},
    },
    "IPC núcleo (Core CPI)": {
        "mayor": {"divisas": "🟢 Fuerte apreciación monetaria", "bonos": "🔴 Rendimientos al alza", "acciones": "🔴 Muy negativo para tecnológicas", "oro": "🟢 Cobertura inflacionaria", "crypto": "🔴 Debilidad especulativa", "politica": "📈 Banco central agresivo", "riesgo": "🔴 Menor apetito por riesgo", "lectura": "La inflación subyacente sigue elevada."},
        "menor": {"divisas": "🔴 Debilidad monetaria", "bonos": "🟢 Rally de bonos", "acciones": "🟢 Recuperación bursátil", "oro": "🔴 Menor necesidad de cobertura", "crypto": "🟢 Recuperación de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🟢 Risk-on", "lectura": "La inflación núcleo se modera."},
    },
    "PPI (precios al productor)": {
        "mayor": {"divisas": "🟢 Fortaleza monetaria", "bonos": "🔴 Bonos presionados", "acciones": "🔴 Riesgo sobre márgenes empresariales", "oro": "🟢 Cobertura inflacionaria", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Riesgo de endurecimiento monetario", "riesgo": "🔴 Risk-off", "lectura": "Los costos de producción aumentan."},
        "menor": {"divisas": "🔴 Debilidad monetaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🟢 Mejora empresarial", "oro": "🔴 Menor presión inflacionaria", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🟢 Risk-on", "lectura": "Disminuyen las presiones sobre costos productivos."},
    },
    "PCE / PCE núcleo (EE. UU.)": {
        "mayor": {"divisas": "🟢 Dólar fortalecido", "bonos": "🔴 Rendimientos al alza", "acciones": "🔴 Negativo para Wall Street", "oro": "🟢 Oro favorecido", "crypto": "🔴 Debilidad cripto", "politica": "📈 Presión sobre la Reserva Federal", "riesgo": "🔴 Menor apetito por riesgo", "lectura": "El indicador preferido de inflación de la Fed sigue elevado."},
        "menor": {"divisas": "🔴 Dólar debilitado", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso bursátil", "oro": "🔴 Menor refugio", "crypto": "🟢 Recuperación cripto", "politica": "📉 Menor presión monetaria", "riesgo": "🟢 Risk-on", "lectura": "El PCE muestra moderación inflacionaria."},
    },
    "Decisión de tasas de interés (banco central)": {
        "mayor": {"divisas": "🟢 Moneda fortalecida", "bonos": "🔴 Caída de bonos", "acciones": "🔴 Presión sobre acciones", "oro": "🔴 Oro debilitado", "crypto": "🔴 Presión sobre criptomonedas", "politica": "📈 Política monetaria restrictiva", "riesgo": "🔴 Risk-off", "lectura": "La suba de tasas endurece las condiciones financieras."},
        "menor": {"divisas": "🔴 Debilidad monetaria", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Impulso positivo para acciones", "oro": "🟢 Oro favorecido", "crypto": "🟢 Liquidez favorable para criptomonedas", "politica": "📉 Política monetaria expansiva", "riesgo": "🟢 Risk-on", "lectura": "La baja de tasas mejora la liquidez."},
    },
    "Nóminas no agrícolas (NFP, EE. UU.)": {
        "mayor": {"divisas": "🟢 Dólar fortalecido", "bonos": "🔴 Rendimientos al alza", "acciones": "🟠 Riesgo de presión sobre índices", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor apetito por riesgo", "politica": "📈 Riesgo de tasas altas prolongadas", "riesgo": "⚠️ Mercado cauteloso", "lectura": "El mercado laboral continúa extremadamente sólido."},
        "menor": {"divisas": "🔴 Dólar debilitado", "bonos": "🟢 Recuperación de bonos", "acciones": "🟢 Mejora para tecnológicas", "oro": "🟢 Oro favorecido", "crypto": "🟢 Recuperación de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🟢 Mayor liquidez esperada", "lectura": "El mercado laboral comienza a enfriarse."},
    },
    "Tasa de desempleo": {
        "mayor": {"divisas": "🔴 Debilidad monetaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Risk-off", "politica": "📉 Posible flexibilización monetaria", "riesgo": "🔴 Aversión al riesgo", "lectura": "El deterioro laboral aumenta riesgos económicos."},
        "menor": {"divisas": "🟢 Fortaleza monetaria", "bonos": "🔴 Bonos presionados", "acciones": "🟠 Riesgo de política más restrictiva", "oro": "🔴 Menor demanda refugio", "crypto": "🔴 Menor liquidez", "politica": "📈 Riesgo de endurecimiento monetario", "riesgo": "⚠️ Mercado sensible a inflación salarial", "lectura": "El empleo sólido mantiene presión inflacionaria."},
    },
    "PMI manufacturero": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Ambiente favorable para acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Posible endurecimiento monetario", "riesgo": "🟢 Expansión económica", "lectura": "La actividad manufacturera muestra expansión."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Búsqueda de refugio", "crypto": "🔴 Debilidad de riesgo", "politica": "📉 Mayor probabilidad de flexibilización", "riesgo": "🔴 Contracción económica", "lectura": "La actividad manufacturera se debilita."},
    },
    "Ventas minoristas (headline)": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Consumo sólido favorece acciones", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo de inflación por consumo", "riesgo": "🟢 Risk-on", "lectura": "El consumo continúa sólido."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Mayor búsqueda defensiva", "crypto": "🔴 Debilidad de activos riesgosos", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "El consumo comienza a desacelerarse."},
    },
    "Inventarios de petróleo crudo (EIA)": {
        "mayor": {"divisas": "🔴 Debilidad de monedas petroleras", "bonos": "🟢 Menor presión inflacionaria", "acciones": "🔴 Debilidad energética", "oro": "🔴 Menor temor inflacionario", "crypto": "🟢 Riesgo moderadamente positivo", "politica": "📉 Menor presión inflacionaria", "riesgo": "🟢 Ambiente más estable", "lectura": "El aumento de inventarios reduce presión sobre el petróleo."},
        "menor": {"divisas": "🟢 Fortaleza de monedas ligadas a commodities", "bonos": "🔴 Riesgo inflacionario", "acciones": "🟢 Energéticas favorecidas", "oro": "🟢 Cobertura inflacionaria", "crypto": "🔴 Riesgo inflacionario", "politica": "📈 Mayor presión inflacionaria", "riesgo": "⚠️ Mayor volatilidad", "lectura": "La caída de inventarios impulsa precios energéticos."},
    },
    "ADP empleo privado": {
        "mayor": {"divisas": "🟢 Dólar fortalecido", "bonos": "🔴 Bonos presionados", "acciones": "🟠 Riesgo de tasas altas", "oro": "🔴 Oro debilitado", "crypto": "🔴 Menor liquidez", "politica": "📈 Mayor presión monetaria", "riesgo": "⚠️ Mercado cauteloso", "lectura": "El empleo privado continúa sólido."},
        "menor": {"divisas": "🔴 Dólar debilitado", "bonos": "🟢 Bonos favorecidos", "acciones": "🟢 Positivo para Nasdaq", "oro": "🟢 Oro favorecido", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🟢 Risk-on", "lectura": "El empleo privado comienza a desacelerarse."},
    },
    "Peticiones iniciales de desempleo": {
        "mayor": {"divisas": "🔴 Debilidad del dólar", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo económico", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Risk-off", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Aversión al riesgo", "lectura": "Aumentan las solicitudes de desempleo."},
        "menor": {"divisas": "🟢 Fortaleza del dólar", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Economía resiliente", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo inflacionario laboral", "riesgo": "🟢 Risk-on", "lectura": "El mercado laboral sigue fuerte."},
    },
    "JOLTS ofertas laborales": {
        "mayor": {"divisas": "🟢 Fortaleza monetaria", "bonos": "🔴 Rendimientos al alza", "acciones": "🔴 Riesgo de tasas altas", "oro": "🔴 Oro debilitado", "crypto": "🔴 Liquidez negativa", "politica": "📈 Mercado laboral sobrecalentado", "riesgo": "⚠️ Mercado sensible", "lectura": "Las vacantes laborales siguen elevadas."},
        "menor": {"divisas": "🔴 Debilidad monetaria", "bonos": "🟢 Bonos favorecidos", "acciones": "🟢 Positivo para acciones", "oro": "🟢 Oro favorecido", "crypto": "🟢 Recuperación cripto", "politica": "📉 Menor presión sobre la Fed", "riesgo": "🟢 Risk-on", "lectura": "El mercado laboral comienza a enfriarse."},
    },
    "ISM manufacturero": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Ambiente favorable", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Riesgo inflacionario", "riesgo": "🟢 Expansión económica", "lectura": "La industria manufacturera acelera crecimiento."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo recesivo", "oro": "🟢 Oro favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible flexibilización", "riesgo": "🔴 Risk-off", "lectura": "La actividad manufacturera se desacelera."},
    },
    "ISM servicios": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Consumo sólido", "oro": "🔴 Menor cobertura", "crypto": "🟢 Risk-on", "politica": "📈 Presión inflacionaria", "riesgo": "🟢 Expansión económica", "lectura": "El sector servicios mantiene fortaleza."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Mayor refugio", "crypto": "🔴 Menor apetito por riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "El sector servicios pierde impulso."},
    },
    "PIB trimestral": {
        "mayor": {"divisas": "🟢 Fortaleza del dólar", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Crecimiento sólido", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía sobrecalentada", "riesgo": "🟢 Risk-on", "lectura": "La economía crece por encima de lo esperado."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de recesión", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible estímulo monetario", "riesgo": "🔴 Risk-off", "lectura": "El crecimiento económico se desacelera."},
    },
    "Ingresos promedio por hora": {
        "mayor": {"divisas": "🟢 Fortaleza del dólar por presión salarial", "bonos": "🔴 Rendimientos en alza", "acciones": "🔴 Negativo para tecnológicas", "oro": "🟢 Cobertura inflacionaria", "crypto": "🔴 Menor liquidez", "politica": "📈 Riesgo de inflación salarial", "riesgo": "🔴 Menor apetito por riesgo", "lectura": "Los salarios aumentan y elevan riesgos inflacionarios."},
        "menor": {"divisas": "🔴 Dólar debilitado", "bonos": "🟢 Bonos favorecidos", "acciones": "🟢 Impulso bursátil", "oro": "🔴 Menor presión inflacionaria", "crypto": "🟢 Risk-on", "politica": "📉 Menor presión salarial", "riesgo": "🟢 Mayor apetito por riesgo", "lectura": "La inflación salarial comienza a moderarse."},
    },
    "PMI servicios": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Consumo sólido", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente positivo", "politica": "📈 Riesgo inflacionario", "riesgo": "🟢 Expansión económica", "lectura": "El sector servicios muestra expansión sólida."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Risk-off", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Desaceleración económica", "lectura": "El sector servicios pierde impulso."},
    },
    "PMI compuesto": {
        "mayor": {"divisas": "🟢 Fortaleza monetaria", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Expansión económica", "oro": "🔴 Menor demanda defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Economía fuerte", "riesgo": "🟢 Risk-on", "lectura": "La economía acelera crecimiento general."},
        "menor": {"divisas": "🔴 Debilidad monetaria", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo económico", "oro": "🟢 Oro favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Posible flexibilización", "riesgo": "🔴 Risk-off", "lectura": "La economía muestra señales de desaceleración."},
    },
    "Pedidos de bienes duraderos": {
        "mayor": {"divisas": "🟢 Fortaleza industrial", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para industriales", "oro": "🔴 Menor necesidad defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Actividad económica fuerte", "riesgo": "🟢 Expansión económica", "lectura": "Aumentan los pedidos industriales de largo plazo."},
        "menor": {"divisas": "🔴 Debilidad industrial", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo económico", "oro": "🟢 Mayor cobertura defensiva", "crypto": "🔴 Risk-off", "politica": "📉 Debilidad económica", "riesgo": "🔴 Menor crecimiento", "lectura": "La demanda industrial pierde fuerza."},
    },
    "Producción industrial": {
        "mayor": {"divisas": "🟢 Fortaleza económica", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Impulso industrial", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Economía fuerte", "riesgo": "🟢 Risk-on", "lectura": "La producción industrial acelera."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos demandados", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad de riesgo", "politica": "📉 Menor presión monetaria", "riesgo": "🔴 Risk-off", "lectura": "La actividad industrial se debilita."},
    },
    "Confianza del consumidor": {
        "mayor": {"divisas": "🟢 Consumo sólido", "bonos": "🔴 Bonos presionados", "acciones": "🟢 Ambiente favorable", "oro": "🔴 Menor búsqueda defensiva", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Fortaleza económica", "riesgo": "🟢 Risk-on", "lectura": "El consumidor mantiene confianza elevada."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Rally de bonos", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Menor apetito por riesgo", "politica": "📉 Riesgo económico", "riesgo": "🔴 Risk-off", "lectura": "La confianza del consumidor cae."},
    },
    "Confianza Universidad Michigan": {
        "mayor": {"divisas": "🟢 Fortaleza del consumo", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para acciones", "oro": "🔴 Menor refugio", "crypto": "🟢 Mayor apetito por riesgo", "politica": "📈 Fortaleza económica", "riesgo": "🟢 Risk-on", "lectura": "La confianza del consumidor mejora."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo de desaceleración", "oro": "🟢 Mayor cobertura", "crypto": "🔴 Risk-off", "politica": "📉 Riesgo de menor crecimiento", "riesgo": "🔴 Aversión al riesgo", "lectura": "La confianza del consumidor se deteriora."},
    },
    "Ventas de viviendas nuevas": {
        "mayor": {"divisas": "🟢 Fortaleza inmobiliaria", "bonos": "🔴 Rendimientos en alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor demanda refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Actividad económica sólida", "riesgo": "🟢 Risk-on", "lectura": "El mercado inmobiliario muestra fortaleza."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo inmobiliario", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Debilidad especulativa", "politica": "📉 Desaceleración económica", "riesgo": "🔴 Risk-off", "lectura": "El mercado inmobiliario pierde impulso."},
    },
    "Ventas de viviendas existentes": {
        "mayor": {"divisas": "🟢 Fortaleza inmobiliaria", "bonos": "🔴 Rendimientos al alza", "acciones": "🟢 Positivo para constructoras", "oro": "🔴 Menor refugio", "crypto": "🟢 Ambiente favorable", "politica": "📈 Economía sólida", "riesgo": "🟢 Risk-on", "lectura": "Las ventas inmobiliarias aumentan."},
        "menor": {"divisas": "🔴 Debilidad económica", "bonos": "🟢 Bonos favorecidos", "acciones": "🔴 Riesgo económico", "oro": "🟢 Refugio favorecido", "crypto": "🔴 Risk-off", "politica": "📉 Menor crecimiento", "riesgo": "🔴 Desaceleración", "lectura": "Las ventas inmobiliarias disminuyen."},
    },
}


# ==============================================================
#  INTERPRETACIÓN MACRO GENÉRICA POR CATEGORÍA (fallback)
#  Se usa para cualquier evento que no tenga una entrada propia en
#  INTERPRETACION_MACRO. Cubre todos los eventos agregados en
#  EVENTOS_EXTENDIDOS y cualquier evento futuro: solo hace falta
#  asignarle una categoría existente para que ya tenga lectura macro.
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
        # Nota de signo: el balance fiscal se carga como número negativo
        # cuando hay déficit (ej. real=-432B). Por eso "mayor" (número más
        # alto, es decir déficit MENOR o superávit) es la mejora, y "menor"
        # (número más bajo, déficit MÁS negativo) es el deterioro.
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

IMPACTO_COLOR = {"Muy Alto": "#f85149", "Alto": "#f0883e", "Medio": "#e3b341", "Bajo": "#8b949e"}


# ==============================================================
#  LÓGICA (portada 1:1 de interpretarMacro / guardarRegistro de GAS)
# ==============================================================

def interpretar_macro(evento, real, previsto):
    """Busca primero una interpretación puntual y curada para el evento
    (INTERPRETACION_MACRO). Si no existe, cae a la interpretación
    genérica de su categoría (CATEGORIA_INTERPRETACION), que cubre
    automáticamente todos los eventos agregados en EVENTOS_EXTENDIDOS
    y cualquier evento nuevo que se agregue a futuro."""
    info = INTERPRETACION_MACRO.get(evento)
    if not info:
        categoria = EVENTOS.get(evento, {}).get("categoria") if evento else None
        info = CATEGORIA_INTERPRETACION.get(categoria)

    vacio = {"divisas": "⚪ Sin interpretación", "bonos": "⚪ Sin interpretación",
             "acciones": "⚪ Sin interpretación", "oro": "⚪ Sin interpretación",
             "crypto": "⚪ Sin interpretación", "politica": "⚪ Sin interpretación",
             "riesgo": "⚪ Sin interpretación", "lectura": "No existe interpretación cargada para este evento."}
    if not info or real is None or previsto is None:
        return vacio
    resultado = "mayor" if real > previsto else "menor"
    return info.get(resultado, vacio)


def _calcular_analisis(previsto, anterior, real, polaridad="directa"):
    """Calcula el análisis del dato frente a lo previsto y al dato anterior.

    `polaridad` (ver EVENTOS[...]["polaridad"]) determina si un valor REAL
    más alto que el previsto/anterior es una buena o mala noticia:
      - "directa": más alto = mejor (PBI, PMI, ventas minoristas, empleo...).
      - "inversa": más alto = peor (desempleo, inflación, tasas de interés,
        costos laborales, rendimiento de subastas de deuda...).
      - "neutral": evento cualitativo, no se emite juicio de bueno/malo.

    El texto de vs_previsto / vs_anterior es SIEMPRE puramente factual
    (dirección numérica, sin juicio de valor); el juicio de bueno/malo vive
    exclusivamente en senal_previsto / senal_anterior / impacto_mercado, y
    es ahí donde se aplica la polaridad.
    """
    hay_prev, hay_ant, hay_real = previsto is not None, anterior is not None, real is not None
    vs_previsto = vs_anterior = senal_prev = senal_ant = impacto_mercado = ""

    # ── Comparación factual (no juzga si es bueno o malo) ──
    if hay_real and hay_prev:
        if real > previsto:   vs_previsto = "📈 Por encima del previsto"
        elif real < previsto: vs_previsto = "📉 Por debajo del previsto"
        else:                 vs_previsto = "➖ En línea con el previsto"

    if hay_real and hay_ant:
        if real > anterior:   vs_anterior = "📈 Subió vs. el dato anterior"
        elif real < anterior: vs_anterior = "📉 Bajó vs. el dato anterior"
        else:                 vs_anterior = "➖ Sin cambios vs. el anterior"

    # ── Eventos cualitativos: sin lectura de bueno/malo ──
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

    # ── Juicio de bueno/malo, ajustado por polaridad ──
    # signo = -1 invierte la comparación para eventos "inversa" (ej. un
    # desempleo real > previsto es negativo, no positivo).
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

    if hay_prev or hay_ant:
        if mej_p and mej_a:       impacto_mercado = "🟢 BUEN DATO PARA EL MERCADO"
        elif peor_p and peor_a:   impacto_mercado = "🔴 MAL DATO PARA EL MERCADO"
        elif mej_p or mej_a:      impacto_mercado = "🟡 BUEN DATO PARCIAL"
        elif peor_p or peor_a:    impacto_mercado = "🟠 MAL DATO PARCIAL"
        else:                     impacto_mercado = "⚪ NEUTRO PARA EL MERCADO"

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
    """Grilla completa de interpretación macro: divisas, bonos, acciones, oro,
    cripto, política monetaria y régimen de mercado — siempre visible, no
    escondida detrás de un badge genérico de 'bueno/malo para el mercado'."""
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
    macro = interpretar_macro(datos["evento"], real, previsto)
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


@st.cache_data(ttl=120, show_spinner=False)
def _obtener_registros(_supabase, limite=100):
    res = (_supabase.table(TABLA_REGISTRO).select("*")
           .order("created_at", desc=True).limit(limite).execute())
    return res.data or []


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
#  Solo ADMIN_EMAIL ve y usa el formulario de carga. El resto de los
#  usuarios ve un aviso y puede pasar a la pestaña Historial. Esta es
#  solo la barrera de UI: la protección real está en las políticas
#  RLS de Supabase (insert/update/delete solo para tu email).
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

    # ── análisis en vivo (se recalcula en cada rerun, como el JS del sidebar) ──
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
    macro = interpretar_macro(evento, real, previsto) if evento else interpretar_macro(None, None, None)
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
                    _obtener_registros.clear()
                    st.success("✅ Registro guardado.")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error al guardar: {e}")


# ==============================================================
#  RENDER — TAB CALENDARIO ECONÓMICO (solo lectura, para todos)
#  Cada evento se muestra como tarjeta expandible con el análisis
#  macro completo (no solo si fue "bueno" o "malo", sino para qué
#  activo y por qué), tal como se ve en vivo al cargar un registro.
# ==============================================================

def _tab_historial(supabase):
    top1, top2 = st.columns([3, 1])
    with top1:
        st.caption("Todos los eventos económicos cargados (solo lectura)")
    with top2:
        if st.button("↺ Actualizar", use_container_width=True, key="cal_hist_refresh"):
            _obtener_registros.clear()
            st.rerun()

    filas = _obtener_registros(supabase, 100)
    if not filas:
        st.info("Todavía no hay registros cargados.")
        return

    df = pd.DataFrame(filas)

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

    st.caption(f"{len(df_f)} registros mostrados de {len(df)} totales")
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    for _, row in df_f.iterrows():
        impacto = row.get("impacto_mercado") or "⚪ NEUTRO PARA EL MERCADO"
        bg, fg = _impacto_estilo(impacto)
        real, previsto, anterior = row.get("real"), row.get("previsto"), row.get("anterior")
        unidad = row.get("unidad") or ""

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


# ==============================================================
#  RENDER — TAB COMPARAR (registro puntual)
#  Permite elegir dos registros ya cargados y compararlos lado a
#  lado: puede ser el mismo país en dos fechas distintas (comparar
#  contra el mes anterior) o dos países distintos para el mismo tipo
#  de evento. El selector es genérico (País → Evento → Fecha) para
#  cubrir ambos casos sin duplicar UI.
# ==============================================================

def _selector_registro(df, key_prefix, label):
    col1, col2, col3 = st.columns(3)
    with col1:
        paises = sorted(df["pais"].dropna().unique().tolist())
        if not paises:
            st.selectbox(f"País ({label})", ["—"], key=f"{key_prefix}_pais", disabled=True)
            return None
        pais = st.selectbox(f"País ({label})", paises, key=f"{key_prefix}_pais")

    df_pais = df[df["pais"] == pais]
    with col2:
        eventos = sorted(df_pais["evento"].dropna().unique().tolist())
        if not eventos:
            st.selectbox(f"Evento ({label})", ["—"], key=f"{key_prefix}_evento", disabled=True)
            return None
        evento = st.selectbox(f"Evento ({label})", eventos, key=f"{key_prefix}_evento")

    df_ev = df_pais[df_pais["evento"] == evento].sort_values("fecha", ascending=False)
    with col3:
        opciones_fecha = df_ev["fecha"].tolist()
        if not opciones_fecha:
            st.selectbox(f"Fecha ({label})", ["—"], key=f"{key_prefix}_fecha", disabled=True)
            return None
        fecha_sel = st.selectbox(f"Fecha ({label})", opciones_fecha, key=f"{key_prefix}_fecha")

    return df_ev[df_ev["fecha"] == fecha_sel].iloc[0]


def _tab_comparar(supabase):
    st.caption(
        "Elegí dos registros para comparar: el mismo país en dos meses distintos, "
        "o dos países distintos para el mismo evento — lo que necesites."
    )

    filas = _obtener_registros(supabase, 200)
    if not filas:
        st.info("Todavía no hay registros cargados para comparar.")
        return

    df = pd.DataFrame(filas)

    colA, colB = st.columns(2)
    with colA:
        st.markdown("#### 🅰️ Registro A")
        fila_a = _selector_registro(df, "cmp_a", "A")
    with colB:
        st.markdown("#### 🅱️ Registro B")
        fila_b = _selector_registro(df, "cmp_b", "B")

    if fila_a is None or fila_b is None:
        st.info("Cargá al menos dos registros (pueden ser del mismo país o de países distintos) para poder comparar.")
        return

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    st.markdown("---")

    ca, cb = st.columns(2)
    for col, fila, etiqueta in [(ca, fila_a, "A"), (cb, fila_b, "B")]:
        with col:
            unidad = fila.get("unidad") or ""
            impacto = fila.get("impacto_mercado") or "⚪ NEUTRO PARA EL MERCADO"
            bg, fg = _impacto_estilo(impacto)
            st.markdown(f"**{etiqueta} · {fila.get('pais','')} · {fila.get('fecha','')}**")
            st.caption(fila.get("evento", ""))
            st.markdown(
                f'<div style="border-radius:10px;padding:10px 14px;margin-bottom:8px;'
                f'background:{bg};border:1px solid {fg}55">'
                f'<div style="font-size:10px;color:{fg};opacity:.8">Impacto para el Mercado</div>'
                f'<div style="font-size:13px;font-weight:800;color:{fg}">{impacto}</div></div>',
                unsafe_allow_html=True,
            )
            v1, v2, v3 = st.columns(3)
            v1.metric("Previsto", f"{fila.get('previsto')} {unidad}" if fila.get("previsto") is not None else "—")
            v2.metric("Anterior", f"{fila.get('anterior')} {unidad}" if fila.get("anterior") is not None else "—")
            v3.metric("Real", f"{fila.get('real')} {unidad}" if fila.get("real") is not None else "—")

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    st.markdown("#### 🔁 Diferencia (B respecto de A)")
    real_a, real_b = fila_a.get("real"), fila_b.get("real")
    if real_a is not None and real_b is not None:
        delta = real_b - real_a
        pct = (delta / abs(real_a) * 100) if real_a not in (0, None) else None
        color = "#3fb950" if delta > 0 else ("#f85149" if delta < 0 else "#8b949e")
        texto_pct = f" ({pct:+.2f}%)" if pct is not None else ""
        st.markdown(
            f'<div style="text-align:center;border-radius:10px;padding:14px;'
            f'background:#0d1117;border:1px solid #21262d">'
            f'<div style="font-size:22px;font-weight:800;color:{color}">{delta:+.4f}{texto_pct}</div>'
            f'<div style="font-size:11px;color:#6b7d9a;margin-top:4px">Valor REAL de B menos valor REAL de A</div></div>',
            unsafe_allow_html=True,
        )
    else:
        st.info("Alguno de los dos registros no tiene valor REAL cargado; no se puede calcular la diferencia numérica.")

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    cma, cmb = st.columns(2)
    for col, fila, etiqueta in [(cma, fila_a, "A"), (cmb, fila_b, "B")]:
        with col:
            st.markdown(f"**Interpretación macro — Registro {etiqueta}**")
            macro = {
                "divisas": fila.get("divisas"), "bonos": fila.get("bonos"),
                "acciones": fila.get("acciones"), "oro": fila.get("oro"),
                "crypto": fila.get("criptomonedas"), "politica": fila.get("politica_monetaria"),
                "riesgo": fila.get("regimen_mercado"), "lectura": fila.get("lectura_macro"),
            }
            _render_macro_grid(macro)


# ==============================================================
#  RENDER — TAB PAÍS VS PAÍS (nuevo)
#  Toma TODOS los registros cargados de dos países, los agrupa por
#  categoría (Inflación, Empleo, Actividad Económica, Comercio
#  Exterior, Vivienda, Energía, etc.) y calcula, para cada categoría,
#  un puntaje promedio a partir del "impacto_mercado" de cada
#  registro:
#     🟢 BUEN DATO PARA EL MERCADO   -> +1.0
#     🟡 BUEN DATO PARCIAL           -> +0.5
#     ⚪ NEUTRO                       ->  0.0
#     🟠 MAL DATO PARCIAL            -> -0.5
#     🔴 MAL DATO PARA EL MERCADO    -> -1.0
#  El país con mayor puntaje promedio en cada categoría "gana" esa
#  categoría, y al final se cuenta cuántas categorías ganó cada uno.
# ==============================================================

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


def _categoria_de_evento(evento):
    info = EVENTOS.get(evento)
    return info["categoria"] if info else "Otros"


def _tab_comparar_paises(supabase):
    st.caption(
        "Elegí dos países y compará, categoría por categoría, cuál viene "
        "mostrando datos económicos más fuertes según todo lo registrado hasta ahora. "
        "El puntaje surge del impacto para el mercado de cada dato cargado."
    )

    filas = _obtener_registros(supabase, 500)
    if not filas:
        st.info("Todavía no hay registros cargados para comparar.")
        return

    df = pd.DataFrame(filas)
    df["categoria"] = df["evento"].apply(_categoria_de_evento)
    df["score"] = df["impacto_mercado"].apply(_signal_score)

    paises_u = sorted(df["pais"].dropna().unique().tolist())
    if len(paises_u) < 2:
        st.info("Necesitás registros de al menos dos países distintos para poder comparar.")
        return

    c1, c2 = st.columns(2)
    with c1:
        pais_a = st.selectbox("🅰️ País A", paises_u, index=0, key="cmpp_pais_a")
    with c2:
        opciones_b = [p for p in paises_u if p != pais_a] or paises_u
        pais_b = st.selectbox("🅱️ País B", opciones_b, index=0, key="cmpp_pais_b")

    df_a = df[df["pais"] == pais_a]
    df_b = df[df["pais"] == pais_b]

    categorias = sorted(set(df_a["categoria"].unique().tolist()) | set(df_b["categoria"].unique().tolist()))
    if not categorias:
        st.info("No hay categorías en común para comparar todavía.")
        return

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    st.markdown(f"#### 📊 Resultado por categoría — {pais_a} vs {pais_b}")

    ganados_a = ganados_b = empates = 0

    for cat in categorias:
        sub_a = df_a[df_a["categoria"] == cat]
        sub_b = df_b[df_b["categoria"] == cat]
        n_a, n_b = len(sub_a), len(sub_b)
        prom_a = sub_a["score"].mean() if n_a else None
        prom_b = sub_b["score"].mean() if n_b else None

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
            if ganador == "Empate":
                st.markdown("⚖️ Empate")
            else:
                st.markdown(f"🏆 {ganador}")
        st.markdown("<hr style='margin:4px 0;border-color:#21262d'>", unsafe_allow_html=True)

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    st.markdown("#### 🏁 Resultado general")
    r1, r2, r3 = st.columns(3)
    r1.metric(f"Categorías ganadas · {pais_a}", ganados_a)
    r2.metric(f"Categorías ganadas · {pais_b}", ganados_b)
    r3.metric("Empates", empates)

    if ganados_a > ganados_b:
        st.success(f"📈 En conjunto, **{pais_a}** viene mostrando datos económicos más fuertes que **{pais_b}** según lo registrado hasta ahora.")
    elif ganados_b > ganados_a:
        st.success(f"📈 En conjunto, **{pais_b}** viene mostrando datos económicos más fuertes que **{pais_a}** según lo registrado hasta ahora.")
    else:
        st.info("📊 Ambos países muestran un desempeño económico parejo según lo registrado hasta ahora.")

    st.caption(
        "Nota: el puntaje se basa en si cada dato salió mejor o peor que lo previsto/anterior, "
        "no evalúa si 'mayor' es intrínsecamente bueno o malo para ese indicador puntual "
        "(por ejemplo, en tasa de desempleo 'mayor' ya se marca como dato negativo en el cálculo base)."
    )


# ==============================================================
#  RENDER — NOTICIAS (todos ven, solo admin publica/borra)
#  Ahora vive en su propio entry point, separado del calendario
#  (ver render_noticias más abajo).
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

    # Ordenar por fecha_noticia (si existe) y si no por created_at, ambas desc.
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

    Muestra el calendario económico (carga de eventos + historial con
    interpretación macro completa), una pestaña de comparación entre
    dos registros cualquiera (mismo país en otro mes, u otro país) y
    una pestaña de comparación país vs país agrupada por categoría.
    Las noticias son un módulo aparte, ver render_noticias() más abajo.
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
        (divisas, bonos, acciones, oro y cripto), su historial y comparación
        entre países o entre períodos.
      </div>
    </div>
    """, unsafe_allow_html=True)

    tab_reg, tab_cal, tab_cmp, tab_paises = st.tabs(
        ["📝 Registrar", "📅 Calendario Económico", "🔀 Comparar", "🌍 País vs País"]
    )
    with tab_reg:
        _tab_registrar(supabase, user_id, es_admin)
    with tab_cal:
        _tab_historial(supabase)
    with tab_cmp:
        _tab_comparar(supabase)
    with tab_paises:
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
