# ==============================================================
#  INGESTA AUTOMÁTICA DE NOTICIAS DE MERCADO
#  Corre desde GitHub Actions cada ~20-60 minutos (ver
#  .github/workflows/ingest_noticias.yml).
#
#  Flujo (SIN clasificación automática):
#    1. Trae TODAS las noticias nuevas de Finnhub (por ticker +
#       generales de mercado) dentro de la ventana de tiempo,
#       excepto las de fuentes de opinión/columnas (ver
#       FUENTES_EXCLUIDAS) que no son noticias de un evento puntual.
#    2. Las traduce al español (esto es solo para que se lean
#       cómodas en el feed — NO intenta interpretar ni clasificar
#       el contenido).
#    3. Las inserta en mercado_eventos con tipo_evento = "Sin
#       clasificar" y autor_email = AUTOR_AUTOMATICO, para
#       distinguirlas de lo cargado a mano.
#    4. Evita duplicados chequeando la URL fuente antes de insertar.
#
#  IMPORTANTE — este script YA NO intenta adivinar el tipo de
#  evento, grupo, factor ni impacto de cada noticia. El glosario
#  (TIPOS_EVENTO, en modulo_noticias_mercado.py) sigue existiendo
#  como referencia de consulta: si el usuario lee una noticia y no
#  está seguro de cómo interpretarla, puede buscar ahí el tipo de
#  evento que más se parezca y así entender el factor de impacto y
#  los activos típicamente afectados. Pero ese mapeo NO se hace
#  automáticamente — queda a criterio de quien lee la noticia (o,
#  si más adelante lo agregás, de una reclasificación manual desde
#  el feed).
#
#  Este script asume que vive en el MISMO repo que
#  modulo_noticias_mercado.py (importa TABLA_EVENTOS desde ahí,
#  para no duplicar el nombre de tabla en dos lugares). Si lo
#  ponés en otra carpeta, ajustá el import de abajo.
#
#  REQUIERE que TIPOS_EVENTO en modulo_noticias_mercado.py tenga
#  una entrada "Sin clasificar" (grupo "Mercados", impacto
#  "Depende del caso", activos []). Si no está, agregala — sin
#  eso este script va a fallar con KeyError al guardar.
#
#  OJO CON EL ESQUEMA DE LA TABLA: si tu columna autor_id tiene una
#  restricción NOT NULL con Foreign Key a auth.users, insertar
#  autor_id=None va a fallar. Si te pasa eso, o (a) hacé la columna
#  nullable, o (b) creá un usuario "sistema" fijo en Supabase y
#  poné ese UUID en AUTOR_ID_SISTEMA más abajo.
# ==============================================================

import os
import sys
import datetime as dt

import requests
from supabase import create_client

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from modulo_noticias_mercado import TIPOS_EVENTO, TABLA_EVENTOS  # noqa: E402

from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

# ----------------------------------------------------------------
# CONFIG — todo esto sale de env vars / GitHub Secrets
# ----------------------------------------------------------------
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
FINNHUB_KEY = os.environ["FINNHUB_API_KEY"]

AUTOR_AUTOMATICO = "auto-noticias@sistema.local"
AUTOR_ID_SISTEMA = os.environ.get("AUTOR_ID_SISTEMA")  # dejalo vacío si autor_id acepta NULL

# Tipo de evento fijo para TODO lo que trae este script. Tiene que
# existir como key en TIPOS_EVENTO (ver nota arriba). El usuario
# consulta el glosario por su cuenta si quiere interpretar la
# noticia — este script no elige ningún tipo específico por ella.
TIPO_SIN_CLASIFICAR = "Sin clasificar"

# Texto de ayuda que queda en notas, recordando que el glosario
# existe como referencia manual (no como algo que el script usa).
GLOSARIO_AYUDA = (
    "Para interpretar esta noticia, consultá el glosario de tipos de "
    "evento (TIPOS_EVENTO) y elegí manualmente el que más se parezca."
)

# Tickers que seguimos en Finnhub (noticias por empresa). Sumá o
# sacá los que quieras separados por coma en la env var WATCHLIST;
# si no se define, se usa esta lista por defecto.
WATCHLIST_DEFAULT = "AAPL,MSFT,GOOGL,AMZN,META,NVDA,TSLA,JPM,XOM,KO"
WATCHLIST = [t.strip() for t in os.environ.get("WATCHLIST", WATCHLIST_DEFAULT).split(",") if t.strip()]

# Cuántos minutos hacia atrás buscar en cada corrida (un poco más
# que el intervalo del cron, para no perder noticias si una corrida
# se retrasa o falla).
VENTANA_MINUTOS = int(os.environ.get("VENTANA_MINUTOS", "30"))

# Fuentes que en la práctica publican columnas de opinión / listas
# tipo "3 acciones para comprar" en vez de noticias de un evento
# puntual. Estas se siguen excluyendo (no son "noticias de un
# evento", son contenido editorial). Sumá más nombres acá si ves
# que se cuelan (fijate el campo "source" en los logs 🔍).
FUENTES_EXCLUIDAS = {
    "motley fool", "zacks", "zacks investment research", "zacks.com",
    "24/7 wall st", "24/7 wall st.", "insider monkey", "simply wall st",
    "simply wall st.", "tipranks", "investorplace", "gurufocus",
    "seeking alpha", "smarteranalyst", "barchart",
}


def _es_fuente_excluida(source):
    return (source or "").strip().lower() in FUENTES_EXCLUIDAS

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ----------------------------------------------------------------
# TRADUCTOR — modelo local (Helsinki-NLP/opus-mt-en-es), sin costo
# por noticia. Las noticias de Finnhub vienen en inglés; se
# traducen solo para que se lean cómodas en el feed — esto NO
# clasifica ni interpreta nada, es puramente para legibilidad.
# ----------------------------------------------------------------
class Traductor:
    def __init__(self):
        print("Cargando modelo de traducción (inglés → español)...")
        nombre_modelo = "Helsinki-NLP/opus-mt-en-es"
        self.tokenizer = AutoTokenizer.from_pretrained(nombre_modelo)
        self.modelo = AutoModelForSeq2SeqLM.from_pretrained(nombre_modelo)

    def _traducir_texto(self, texto):
        texto = (texto or "").strip()
        if not texto:
            return texto
        try:
            # Los modelos Marian truncan alrededor de 512 tokens; de
            # sobra para un título o resumen de noticia.
            entradas = self.tokenizer(texto, return_tensors="pt", truncation=True, max_length=400)
            salida = self.modelo.generate(**entradas, max_length=400)
            return self.tokenizer.decode(salida[0], skip_special_tokens=True)
        except Exception as e:
            print(f"⚠️ No se pudo traducir ('{texto[:40]}...'): {e}")
            return texto  # si falla, mejor guardar el original que perder la noticia

    def traducir(self, titulo, resumen):
        return self._traducir_texto(titulo), self._traducir_texto(resumen)


# ----------------------------------------------------------------
# FUENTES DE NOTICIAS
# ----------------------------------------------------------------
def _desde_hace_minutos(minutos):
    return dt.datetime.utcnow() - dt.timedelta(minutes=minutos)


def traer_finnhub_general():
    """Noticias generales de mercado (no requieren ticker puntual)."""
    try:
        r = requests.get(
            "https://finnhub.io/api/v1/news",
            params={"category": "general", "token": FINNHUB_KEY},
            timeout=20,
        )
        r.raise_for_status()
        items = r.json()
    except Exception as e:
        print(f"⚠️ Error trayendo noticias generales de Finnhub: {e}")
        return []

    if items:
        fechas_todas = [dt.datetime.utcfromtimestamp(it.get("datetime", 0)) for it in items]
        print(f"🔍 [general] la API devolvió {len(items)} noticias en total, "
              f"la más reciente es de {max(fechas_todas)} UTC.")
    else:
        print("🔍 [general] la API no devolvió ninguna noticia.")

    limite = _desde_hace_minutos(VENTANA_MINUTOS)
    resultado = []
    for it in items:
        if _es_fuente_excluida(it.get("source")):
            continue
        fecha = dt.datetime.utcfromtimestamp(it.get("datetime", 0))
        if fecha < limite:
            continue
        resultado.append({
            "titulo": (it.get("headline") or "").strip(),
            "resumen": it.get("summary", ""),
            "fecha": fecha.date(),
            "fuente_url": it.get("url", ""),
            "empresa": "", "ticker": "", "pais": "",
        })
    return resultado


def traer_finnhub_por_ticker(ticker):
    hoy = dt.date.today()
    desde = hoy - dt.timedelta(days=2)
    try:
        r = requests.get(
            "https://finnhub.io/api/v1/company-news",
            params={"symbol": ticker, "from": str(desde), "to": str(hoy), "token": FINNHUB_KEY},
            timeout=20,
        )
        r.raise_for_status()
        items = r.json()
    except Exception as e:
        print(f"⚠️ Error trayendo noticias de {ticker}: {e}")
        return []

    if items:
        fechas_todas = [dt.datetime.utcfromtimestamp(it.get("datetime", 0)) for it in items]
        print(f"🔍 [{ticker}] la API devolvió {len(items)} noticias (últimos 2 días), "
              f"la más reciente es de {max(fechas_todas)} UTC.")
    else:
        print(f"🔍 [{ticker}] la API no devolvió ninguna noticia en los últimos 2 días.")

    limite = _desde_hace_minutos(VENTANA_MINUTOS)
    resultado = []
    for it in items:
        if _es_fuente_excluida(it.get("source")):
            continue
        fecha = dt.datetime.utcfromtimestamp(it.get("datetime", 0))
        if fecha < limite:
            continue
        resultado.append({
            "titulo": (it.get("headline") or "").strip(),
            "resumen": it.get("summary", ""),
            "fecha": fecha.date(),
            "fuente_url": it.get("url", ""),
            "empresa": ticker, "ticker": ticker, "pais": "",
        })
    return resultado


# Marketaux queda listo para sumarlo más adelante (mejora la
# cobertura de Macro/Gobiernos/Geopolítica, que Finnhub no cubre).
# Para activarlo: descomentar esta función, agregar de nuevo
# MARKETAUX_KEY arriba, sumar `+ traer_marketaux()` en main(), y
# el secret MARKETAUX_API_KEY en el workflow.
#
# def traer_marketaux():
#     publicado_desde = _desde_hace_minutos(VENTANA_MINUTOS).strftime("%Y-%m-%dT%H:%M")
#     try:
#         r = requests.get(
#             "https://api.marketaux.com/v1/news/all",
#             params={
#                 "api_token": MARKETAUX_KEY,
#                 "language": "en,es",
#                 "published_after": publicado_desde,
#                 "limit": 3,  # tope del plan free
#             },
#             timeout=20,
#         )
#         r.raise_for_status()
#         data = r.json().get("data", [])
#     except Exception as e:
#         print(f"⚠️ Error trayendo noticias de Marketaux: {e}")
#         return []
#
#     resultado = []
#     for it in data:
#         entidades = it.get("entities", [])
#         primera = entidades[0] if entidades else {}
#         try:
#             fecha = dt.datetime.fromisoformat(it["published_at"].replace("Z", "+00:00")).date()
#         except Exception:
#             fecha = dt.date.today()
#         resultado.append({
#             "titulo": (it.get("title") or "").strip(),
#             "resumen": it.get("description", ""),
#             "fecha": fecha,
#             "fuente_url": it.get("url", ""),
#             "empresa": primera.get("name", "") or "",
#             "ticker": primera.get("symbol", "") or "",
#             "pais": primera.get("country", "") or "",
#         })
#     return resultado


# ----------------------------------------------------------------
# GUARDADO EN SUPABASE
# ----------------------------------------------------------------
def ya_existe(fuente_url):
    if not fuente_url:
        return False
    res = (supabase.table(TABLA_EVENTOS).select("id")
           .eq("fuente_url", fuente_url).limit(1).execute())
    return bool(res.data)


def guardar(noticia):
    # Todo entra igual: sin tipo de evento adivinado, sin grupo ni
    # impacto ni factor inventados. El usuario decide, consultando
    # el glosario, si quiere reclasificar esta noticia a mano.
    info = TIPOS_EVENTO[TIPO_SIN_CLASIFICAR]
    row = {
        "autor_id": AUTOR_ID_SISTEMA,
        "autor_email": AUTOR_AUTOMATICO,
        "fecha_evento": str(noticia["fecha"]),
        "titulo": noticia["titulo"],
        "contenido": noticia["resumen"],
        "tipo_evento": TIPO_SIN_CLASIFICAR,
        "grupo": info["grupo"],
        "factor": info["factor"],
        "impacto": info["impacto"],
        "empresa": noticia["empresa"],
        "ticker": noticia["ticker"].upper() if noticia["ticker"] else "",
        "pais": noticia["pais"],
        "sector": "",
        "activos_afectados": "",
        "fuente_url": noticia["fuente_url"],
        "notas": f"Traducido del inglés. {GLOSARIO_AYUDA}",
    }
    supabase.table(TABLA_EVENTOS).insert(row).execute()


# ----------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------
def main():
    traductor = Traductor()

    noticias = traer_finnhub_general()
    for ticker in WATCHLIST:
        noticias += traer_finnhub_por_ticker(ticker)
    # noticias += traer_marketaux()  # descomentar cuando sumes Marketaux

    print(f"📥 {len(noticias)} noticias encontradas en la ventana de {VENTANA_MINUTOS} min.")

    nuevas = descartadas_dup = 0
    for noticia in noticias:
        if not noticia["titulo"] or not noticia["fuente_url"]:
            continue
        if ya_existe(noticia["fuente_url"]):
            descartadas_dup += 1
            continue

        titulo_es, resumen_es = traductor.traducir(noticia["titulo"], noticia["resumen"])
        noticia["titulo"] = titulo_es
        noticia["resumen"] = resumen_es

        try:
            guardar(noticia)
            nuevas += 1
            print(f"✅ {noticia['titulo'][:70]}")
        except Exception as e:
            print(f"❌ Error guardando '{noticia['titulo'][:50]}': {e}")

    print(f"—\n{nuevas} nuevas guardadas | {descartadas_dup} duplicadas")


if __name__ == "__main__":
    main()
