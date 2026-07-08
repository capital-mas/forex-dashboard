# ==============================================================
#  MÓDULO CALENDARIO ECONÓMICO — versión Streamlit + Supabase
#  Puerto 1:1 de la lógica que estaba en Google Apps Script/Sheets.
#  Se integra como un módulo nativo más de app.py (mismo patrón que
#  modulo_opciones.py / finanzas_ui.py).
# ==============================================================

import streamlit as st
import pandas as pd
from datetime import date, datetime

# ⚠️ Cambiá esto por tu email real (el mismo con el que iniciás sesión
# en la app vía Supabase Auth). Solo esa cuenta ve el formulario de
# publicar/borrar noticias. La protección real (a prueba de gente que
# mire el código) está en las políticas RLS de Supabase — ver el
# archivo calendario_schema.sql.
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
    "IPC (inflación general)":               {"categoria": "Inflación",            "unidad": "%",         "impacto": "Alto"},
    "IPC núcleo (Core CPI)":                  {"categoria": "Inflación",            "unidad": "%",         "impacto": "Alto"},
    "PPI (precios al productor)":             {"categoria": "Inflación",            "unidad": "%",         "impacto": "Medio"},
    "PCE / PCE núcleo (EE. UU.)":             {"categoria": "Inflación",            "unidad": "%",         "impacto": "Muy Alto"},
    "Decisión de tasas de interés (banco central)": {"categoria": "Política Monetaria", "unidad": "%",    "impacto": "Muy Alto"},
    "Nóminas no agrícolas (NFP, EE. UU.)":    {"categoria": "Empleo",               "unidad": "K",         "impacto": "Muy Alto"},
    "Tasa de desempleo":                      {"categoria": "Empleo",               "unidad": "%",         "impacto": "Alto"},
    "PMI manufacturero":                      {"categoria": "Actividad Económica",  "unidad": "Pts",       "impacto": "Alto"},
    "Ventas minoristas (headline)":           {"categoria": "Consumo",              "unidad": "%",         "impacto": "Alto"},
    "Inventarios de petróleo crudo (EIA)":    {"categoria": "Energía",              "unidad": "M Barriles","impacto": "Medio"},
    "ADP empleo privado":                     {"categoria": "Empleo",               "unidad": "K",         "impacto": "Alto"},
    "Peticiones iniciales de desempleo":      {"categoria": "Empleo",               "unidad": "K",         "impacto": "Alto"},
    "JOLTS ofertas laborales":                {"categoria": "Empleo",               "unidad": "M",         "impacto": "Alto"},
    "Ingresos promedio por hora":             {"categoria": "Empleo",               "unidad": "%",         "impacto": "Muy Alto"},
    "PMI servicios":                          {"categoria": "Actividad Económica",  "unidad": "Pts",       "impacto": "Alto"},
    "PMI compuesto":                          {"categoria": "Actividad Económica",  "unidad": "Pts",       "impacto": "Alto"},
    "ISM manufacturero":                      {"categoria": "Actividad Económica",  "unidad": "Pts",       "impacto": "Muy Alto"},
    "ISM servicios":                          {"categoria": "Actividad Económica",  "unidad": "Pts",       "impacto": "Muy Alto"},
    "PIB trimestral":                         {"categoria": "Crecimiento",          "unidad": "%",         "impacto": "Muy Alto"},
    "Pedidos de bienes duraderos":            {"categoria": "Industria",            "unidad": "%",         "impacto": "Alto"},
    "Producción industrial":                  {"categoria": "Industria",            "unidad": "%",         "impacto": "Medio"},
    "Confianza del consumidor":               {"categoria": "Consumo",              "unidad": "Pts",       "impacto": "Alto"},
    "Confianza Universidad Michigan":         {"categoria": "Consumo",              "unidad": "Pts",       "impacto": "Alto"},
    "Ventas de viviendas nuevas":             {"categoria": "Vivienda",             "unidad": "K",         "impacto": "Medio"},
    "Ventas de viviendas existentes":         {"categoria": "Vivienda",             "unidad": "M",         "impacto": "Medio"},
    "Permisos de construcción":               {"categoria": "Vivienda",             "unidad": "K",         "impacto": "Medio"},
    "Inicios de viviendas":                   {"categoria": "Vivienda",             "unidad": "K",         "impacto": "Medio"},
    "FOMC Minutes":                           {"categoria": "Política Monetaria",   "unidad": "",          "impacto": "Muy Alto"},
    "Conferencia de prensa de la Fed":        {"categoria": "Política Monetaria",   "unidad": "",          "impacto": "Muy Alto"},
    "Dot Plot de la Fed":                     {"categoria": "Política Monetaria",   "unidad": "",          "impacto": "Muy Alto"},
}

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

IMPACTO_COLOR = {"Muy Alto": "#f85149", "Alto": "#f0883e", "Medio": "#e3b341", "Bajo": "#8b949e"}


# ==============================================================
#  LÓGICA (portada 1:1 de interpretarMacro / guardarRegistro de GAS)
# ==============================================================

def interpretar_macro(evento, real, previsto):
    info = INTERPRETACION_MACRO.get(evento)
    vacio = {"divisas": "⚪ Sin interpretación", "bonos": "⚪ Sin interpretación",
             "acciones": "⚪ Sin interpretación", "oro": "⚪ Sin interpretación",
             "crypto": "⚪ Sin interpretación", "politica": "⚪ Sin interpretación",
             "riesgo": "⚪ Sin interpretación", "lectura": "No existe interpretación cargada para este evento."}
    if not info or real is None or previsto is None:
        return vacio
    resultado = "mayor" if real > previsto else "menor"
    return info.get(resultado, vacio)


def _calcular_analisis(previsto, anterior, real):
    hay_prev, hay_ant, hay_real = previsto is not None, anterior is not None, real is not None
    vs_previsto = vs_anterior = senal_prev = senal_ant = impacto_mercado = ""

    if hay_real and hay_prev:
        if real > previsto:   vs_previsto, senal_prev = "✅ Mayor al previsto", "🔺 POSITIVO"
        elif real < previsto: vs_previsto, senal_prev = "❌ Menor al previsto", "🔻 NEGATIVO"
        else:                 vs_previsto, senal_prev = "➖ Igual al previsto", "⚖️ NEUTRO"

    if hay_real and hay_ant:
        if real > anterior:   vs_anterior, senal_ant = "✅ Subió vs anterior", "📈 TENDENCIA ALCISTA"
        elif real < anterior: vs_anterior, senal_ant = "❌ Bajó vs anterior", "📉 TENDENCIA BAJISTA"
        else:                 vs_anterior, senal_ant = "➖ Sin cambio", "➡️ LATERAL"

    mej_p = hay_real and hay_prev and real > previsto
    mej_a = hay_real and hay_ant and real > anterior
    peor_p = hay_real and hay_prev and real < previsto
    peor_a = hay_real and hay_ant and real < anterior

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


# ==============================================================
#  ACCESO A SUPABASE
# ==============================================================

def _guardar_registro(supabase, datos, user_id):
    real, previsto, anterior = datos.get("real"), datos.get("previsto"), datos.get("anterior")
    analisis = _calcular_analisis(previsto, anterior, real)
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


def _guardar_noticia(supabase, titulo, contenido, categoria, user_id, user_email):
    supabase.table(TABLA_NOTICIAS).insert({
        "autor_id": user_id, "autor_email": user_email,
        "titulo": titulo.strip(), "contenido": (contenido or "").strip(),
        "categoria": (categoria or "").strip(),
    }).execute()


def _borrar_noticia(supabase, noticia_id):
    supabase.table(TABLA_NOTICIAS).delete().eq("id", noticia_id).execute()


# ==============================================================
#  RENDER — TAB REGISTRAR
# ==============================================================

def _tab_registrar(supabase, user_id):
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
    analisis = _calcular_analisis(previsto, anterior, real)

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

    if evento and real is not None and previsto is not None:
        macro = interpretar_macro(evento, real, previsto)
        with st.expander("🔎 Ver interpretación macro completa (divisas, bonos, acciones, oro, cripto...)"):
            mc1, mc2, mc3 = st.columns(3)
            with mc1:
                st.markdown(f"**Divisas:** {macro['divisas']}")
                st.markdown(f"**Bonos:** {macro['bonos']}")
            with mc2:
                st.markdown(f"**Acciones:** {macro['acciones']}")
                st.markdown(f"**Oro:** {macro['oro']}")
            with mc3:
                st.markdown(f"**Cripto:** {macro['crypto']}")
                st.markdown(f"**Política:** {macro['politica']}")
            st.markdown(f"**Régimen de mercado:** {macro['riesgo']}")
            st.info(macro["lectura"])

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
#  RENDER — TAB HISTORIAL (solo lectura, para todos)
# ==============================================================

def _tab_historial(supabase):
    top1, top2 = st.columns([3, 1])
    with top1:
        st.caption("Últimos registros cargados (solo lectura)")
    with top2:
        if st.button("↺ Actualizar", use_container_width=True, key="cal_hist_refresh"):
            _obtener_registros.clear()
            st.rerun()

    filas = _obtener_registros(supabase, 100)
    if not filas:
        st.info("Todavía no hay registros cargados.")
        return

    df = pd.DataFrame(filas)
    cols_mostrar = ["fecha", "pais", "evento", "previsto", "anterior", "real", "impacto_mercado"]
    cols_mostrar = [c for c in cols_mostrar if c in df.columns]
    df_show = df[cols_mostrar].rename(columns={
        "fecha": "Fecha", "pais": "País", "evento": "Evento",
        "previsto": "Previsto", "anterior": "Anterior", "real": "Real",
        "impacto_mercado": "Impacto",
    })

    fc1, fc2 = st.columns(2)
    with fc1:
        paises_u = ["Todos"] + sorted(df_show["País"].dropna().unique().tolist())
        f_pais = st.selectbox("Filtrar país", paises_u, key="cal_hist_f_pais")
    with fc2:
        impactos_u = ["Todos"] + sorted(df_show["Impacto"].dropna().unique().tolist())
        f_imp = st.selectbox("Filtrar impacto", impactos_u, key="cal_hist_f_imp")

    df_f = df_show.copy()
    if f_pais != "Todos":
        df_f = df_f[df_f["País"] == f_pais]
    if f_imp != "Todos":
        df_f = df_f[df_f["Impacto"] == f_imp]

    st.dataframe(df_f, use_container_width=True, height=min(600, max(150, len(df_f) * 35 + 45)), hide_index=True)
    st.caption(f"{len(df_f)} registros mostrados de {len(df_show)} totales")


# ==============================================================
#  RENDER — TAB NOTICIAS (todos ven, solo admin publica/borra)
# ==============================================================

def _tab_noticias(supabase, es_admin, user_id, user_email):
    if es_admin:
        with st.expander("✏️ Publicar noticia", expanded=True):
            titulo = st.text_input("Título", key="cal_noti_titulo")
            categoria = st.text_input("Categoría (opcional)", key="cal_noti_categoria",
                                       placeholder="Ej: Fed, Inflación, Mercados...")
            contenido = st.text_area("Contenido", key="cal_noti_contenido", height=120)
            if st.button("📰 Publicar", type="primary", key="cal_noti_btn_publicar"):
                if not titulo.strip():
                    st.warning("⚠️ El título es obligatorio.")
                else:
                    try:
                        _guardar_noticia(supabase, titulo, contenido, categoria, user_id, user_email)
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

    for n in noticias:
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
        Registro de eventos macro con interpretación automática (divisas, bonos, acciones,
        oro y cripto), historial y noticias.
      </div>
    </div>
    """, unsafe_allow_html=True)

    tab_reg, tab_hist, tab_noti = st.tabs(["📝 Registrar", "📋 Historial", "📰 Noticias"])
    with tab_reg:
        _tab_registrar(supabase, user_id)
    with tab_hist:
        _tab_historial(supabase)
    with tab_noti:
        _tab_noticias(supabase, es_admin, user_id, user_email)
