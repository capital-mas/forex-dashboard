# ==============================================================
#  INGESTA AUTOMÁTICA DE NOTICIAS DE MERCADO
#  Corre desde GitHub Actions cada ~20 minutos (ver
#  .github/workflows/ingest_noticias.yml).
#
#  Flujo:
#    1. Trae noticias nuevas de Finnhub (por ticker + generales de
#       mercado). Marketaux queda comentado para sumarlo más
#       adelante si hace falta más cobertura macro/global.
#    2. Para cada noticia calcula qué TIPO_EVENTO de la taxonomía
#       (la misma que ya usa modulo_noticias_mercado.py) es más
#       parecido, usando similitud de embeddings — corre un modelo
#       chico localmente, no llama a ninguna API de IA paga.
#    3. Si la similitud supera un umbral mínimo, inserta el evento
#       en mercado_eventos con autor_email = AUTOR_AUTOMATICO, para
#       poder distinguirlo de lo cargado a mano.
#    4. Evita duplicados chequeando la URL fuente antes de insertar.
#
#  IMPORTANTE: este script asume que vive en el MISMO repo que
#  modulo_noticias_mercado.py (importa TIPOS_EVENTO y TABLA_EVENTOS
#  desde ahí, para no duplicar la taxonomía en dos lugares que se
#  puedan desincronizar). Si lo ponés en otra carpeta, ajustá el
#  import de abajo.
#
#  OJO CON EL ESQUENA DE LA TABLA: si tu columna autor_id tiene una
#  restricción NOT NULL con Foreign Key a auth.users, insertar
#  autor_id=None va a fallar. Si te pasa eso, o (a) hacé la columna
#  nullable, o (b) creá un usuario "sistema" fijo en Supabase y
#  poné ese UUID en AUTOR_ID_SISTEMA más abajo.
# ==============================================================

import os
import sys
import datetime as dt

import requests
import numpy as np
from supabase import create_client

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from modulo_noticias_mercado import TIPOS_EVENTO, TABLA_EVENTOS  # noqa: E402

from sentence_transformers import SentenceTransformer

# ----------------------------------------------------------------
# CONFIG — todo esto sale de env vars / GitHub Secrets
# ----------------------------------------------------------------
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
FINNHUB_KEY = os.environ["FINNHUB_API_KEY"]

AUTOR_AUTOMATICO = "auto-noticias@sistema.local"
AUTOR_ID_SISTEMA = os.environ.get("AUTOR_ID_SISTEMA")  # dejalo vacío si autor_id acepta NULL

# Tickers que seguimos en Finnhub (noticias por empresa). Sumá o
# sacá los que quieras separados por coma en la env var WATCHLIST;
# si no se define, se usa esta lista por defecto.
WATCHLIST_DEFAULT = "AAPL,MSFT,GOOGL,AMZN,META,NVDA,TSLA,JPM,XOM,KO"
WATCHLIST = [t.strip() for t in os.environ.get("WATCHLIST", WATCHLIST_DEFAULT).split(",") if t.strip()]

# Umbral mínimo de similitud (0 a 1) para aceptar una clasificación.
# Si no llega, la noticia se descarta en vez de cargarse mal
# clasificada. Empezá con 0.38 y ajustalo mirando los logs: si ves
# clasificaciones raras, subilo; si se descarta casi todo, bajalo.
UMBRAL_SIMILITUD = float(os.environ.get("UMBRAL_SIMILITUD", "0.38"))

# Cuántos minutos hacia atrás buscar en cada corrida (un poco más
# que el intervalo del cron, para no perder noticias si una corrida
# se retrasa o falla).
VENTANA_MINUTOS = int(os.environ.get("VENTANA_MINUTOS", "30"))

# Modelo multilingüe chico (funciona bien español/inglés mezclados,
# que es justo el caso: taxonomía en español, noticias en inglés).
MODELO_EMBEDDINGS = "paraphrase-multilingual-MiniLM-L12-v2"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ----------------------------------------------------------------
# CLASIFICADOR — embeddings locales, sin costo por noticia
# ----------------------------------------------------------------
class Clasificador:
    def __init__(self):
        print("Cargando modelo de embeddings...")
        self.modelo = SentenceTransformer(MODELO_EMBEDDINGS)
        self.tipos = list(TIPOS_EVENTO.keys())
        textos = [f"{tipo}. {TIPOS_EVENTO[tipo]['factor']}" for tipo in self.tipos]
        self.emb_tipos = self.modelo.encode(textos, normalize_embeddings=True)

    def clasificar(self, titulo, resumen):
        texto = f"{titulo}. {resumen or ''}".strip()
        emb_noticia = self.modelo.encode([texto], normalize_embeddings=True)[0]
        similitudes = self.emb_tipos @ emb_noticia
        idx_mejor = int(np.argmax(similitudes))
        return self.tipos[idx_mejor], float(similitudes[idx_mejor])


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


def guardar(noticia, tipo_evento, score):
    info = TIPOS_EVENTO[tipo_evento]
    row = {
        "autor_id": AUTOR_ID_SISTEMA,
        "autor_email": AUTOR_AUTOMATICO,
        "fecha_evento": str(noticia["fecha"]),
        "titulo": noticia["titulo"],
        "contenido": noticia["resumen"],
        "tipo_evento": tipo_evento,
        "grupo": info["grupo"],
        "factor": info["factor"],
        "impacto": info["impacto"],
        "empresa": noticia["empresa"],
        "ticker": noticia["ticker"].upper() if noticia["ticker"] else "",
        "pais": noticia["pais"],
        "sector": "",
        "activos_afectados": ", ".join(info.get("activos", [])),
        "fuente_url": noticia["fuente_url"],
        "notas": f"Clasificado automáticamente (similitud {score:.2f}).",
    }
    supabase.table(TABLA_EVENTOS).insert(row).execute()


# ----------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------
def main():
    clasificador = Clasificador()

    noticias = traer_finnhub_general()
    for ticker in WATCHLIST:
        noticias += traer_finnhub_por_ticker(ticker)
    # noticias += traer_marketaux()  # descomentar cuando sumes Marketaux

    print(f"📥 {len(noticias)} noticias encontradas en la ventana de {VENTANA_MINUTOS} min.")

    nuevas = descartadas_dup = descartadas_score = 0
    for noticia in noticias:
        if not noticia["titulo"] or not noticia["fuente_url"]:
            continue
        if ya_existe(noticia["fuente_url"]):
            descartadas_dup += 1
            continue

        tipo_evento, score = clasificador.clasificar(noticia["titulo"], noticia["resumen"])
        if score < UMBRAL_SIMILITUD:
            descartadas_score += 1
            continue

        try:
            guardar(noticia, tipo_evento, score)
            nuevas += 1
            print(f"✅ {noticia['titulo'][:70]}  →  {tipo_evento} ({score:.2f})")
        except Exception as e:
            print(f"❌ Error guardando '{noticia['titulo'][:50]}': {e}")

    print(f"—\n{nuevas} nuevas | {descartadas_dup} duplicadas | {descartadas_score} bajo umbral de confianza")


if __name__ == "__main__":
    main()
