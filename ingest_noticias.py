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

# Ya no se agrega ningún texto de referencia al glosario en las
# notas — el feed no muestra ese campo.
GLOSARIO_AYUDA = ""

# Tickers que seguimos en Finnhub (noticias por empresa). Sumá o
# sacá los que quieras separados por coma en la env var WATCHLIST;
# si no se define, se usa esta lista por defecto.
WATCHLIST_DEFAULT = "AAPL,MSFT,GOOGL,AMZN,META,NVDA,TSLA,JPM,XOM,KO"
WATCHLIST = [t.strip() for t in os.environ.get("WATCHLIST", WATCHLIST_DEFAULT).split(",") if t.strip()]

# Cuántos minutos hacia atrás buscar en cada corrida (un poco más
# que el intervalo del cron, para no perder noticias si una corrida
# se retrasa o falla).
VENTANA_MINUTOS = int(os.environ.get("VENTANA_MINUTOS", "30"))

# Cuántos días hacia atrás pedirle a Finnhub en las noticias POR
# TICKER (company-news, que sí soporta rango "from"/"to" — a
# diferencia del endpoint general, que solo da lo más reciente sin
# rango). Normalmente 2 días alcanza con el cron corriendo cada hora;
# en una corrida manual de backfill se puede subir (ver
# ingest_noticias.yml, input "ventana_minutos" del workflow_dispatch).
DIAS_TICKER = int(os.environ.get("DIAS_TICKER", "2"))

# Tope opcional de cuántas noticias candidatas procesar (traducir +
# guardar) en ESTA corrida. Pensado para un backfill grande: en vez
# de una corrida de varias horas, se puede correr varias veces con un
# tope chico (ej. 150) — como los duplicados se evitan por URL, cada
# corrida sucesiva retoma donde quedó la anterior sin repetir nada.
# 0 (default) = sin tope, procesa todo lo que haya.
LIMITE_POR_CORRIDA = int(os.environ.get("LIMITE_POR_CORRIDA", "0"))

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

    def _traducir_lote_textos(self, textos, tamano_lote=16):
        """Traduce una lista de textos en lotes (batch), en vez de uno
        por uno — mucho más rápido, incluso en CPU, porque aprovecha
        el paralelismo interno del modelo en cada llamada a generate()
        en vez de pagar el overhead de una llamada por texto."""
        resultados = [""] * len(textos)
        indices_con_texto = [i for i, t in enumerate(textos) if (t or "").strip()]
        if not indices_con_texto:
            return resultados

        for inicio in range(0, len(indices_con_texto), tamano_lote):
            idxs = indices_con_texto[inicio:inicio + tamano_lote]
            lote = [textos[i].strip() for i in idxs]
            try:
                entradas = self.tokenizer(
                    lote, return_tensors="pt", truncation=True, max_length=400,
                    padding=True,
                )
                salidas = self.modelo.generate(**entradas, max_length=400)
                decodificados = self.tokenizer.batch_decode(salidas, skip_special_tokens=True)
                for i, texto_traducido in zip(idxs, decodificados):
                    resultados[i] = texto_traducido
            except Exception as e:
                print(f"⚠️ No se pudo traducir un lote de {len(lote)} textos: {e}")
                # Si falla el lote, mejor guardar el original que perder
                # las noticias de ese lote.
                for i in idxs:
                    resultados[i] = textos[i]

        return resultados

    def traducir_lote(self, noticias):
        """Traduce títulos y resúmenes de una lista de noticias (dicts
        con 'titulo' y 'resumen') EN LOTES. Devuelve una lista de
        (titulo_es, resumen_es) en el mismo orden."""
        titulos = [n["titulo"] for n in noticias]
        resumenes = [n["resumen"] for n in noticias]
        titulos_es = self._traducir_lote_textos(titulos)
        resumenes_es = self._traducir_lote_textos(resumenes)
        return list(zip(titulos_es, resumenes_es))


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
    desde = hoy - dt.timedelta(days=DIAS_TICKER)
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

    # Filtramos duplicados y armamos la lista de candidatas ANTES de
    # traducir, para no gastar tiempo de cómputo en noticias que ya
    # están guardadas o que van a quedar afuera por el tope.
    candidatas, descartadas_dup = [], 0
    for noticia in noticias:
        if not noticia["titulo"] or not noticia["fuente_url"]:
            continue
        if ya_existe(noticia["fuente_url"]):
            descartadas_dup += 1
            continue
        candidatas.append(noticia)

    total_candidatas = len(candidatas)
    recortadas_por_limite = 0
    if LIMITE_POR_CORRIDA and total_candidatas > LIMITE_POR_CORRIDA:
        recortadas_por_limite = total_candidatas - LIMITE_POR_CORRIDA
        candidatas = candidatas[:LIMITE_POR_CORRIDA]
        print(
            f"✂️ Hay {total_candidatas} candidatas, se procesan {LIMITE_POR_CORRIDA} en esta "
            f"corrida (LIMITE_POR_CORRIDA). Las {recortadas_por_limite} restantes quedan para la "
            f"próxima corrida — no se pierden, solo no están duplicadas así que se van a volver "
            f"a encontrar y procesar entonces."
        )

    print(f"🌐 Traduciendo {len(candidatas)} noticia(s) en lotes...")
    traducciones = traductor.traducir_lote(candidatas)

    nuevas = 0
    for i, (noticia, (titulo_es, resumen_es)) in enumerate(zip(candidatas, traducciones), start=1):
        noticia["titulo"] = titulo_es
        noticia["resumen"] = resumen_es
        try:
            guardar(noticia)
            nuevas += 1
            print(f"✅ [{i}/{len(candidatas)}] {noticia['titulo'][:70]}")
        except Exception as e:
            print(f"❌ [{i}/{len(candidatas)}] Error guardando '{noticia['titulo'][:50]}': {e}")

        # Progreso cada 25 noticias, para poder ver en el log de GitHub
        # Actions que la corrida sigue avanzando (no está trabada).
        if i % 25 == 0:
            print(f"—  progreso: {i}/{len(candidatas)} procesadas hasta ahora  —")

    print(
        f"—\n{nuevas} nuevas guardadas | {descartadas_dup} duplicadas"
        + (f" | {recortadas_por_limite} pendientes para la próxima corrida (por LIMITE_POR_CORRIDA)"
           if recortadas_por_limite else "")
    )


if __name__ == "__main__":
    main()
