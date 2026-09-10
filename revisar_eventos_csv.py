"""
Diagnóstico de eventos no reconocidos en un CSV de carga masiva
================================================================

Qué hace:
  1) Importa EVENTOS e INTERPRETACION_MACRO desde tu módulo real
     (modulo_calendario.py), para comparar contra la fuente de verdad,
     no contra una copia manual.
  2) Para cada fila del CSV, prueba el nombre del evento tal cual viene.
  3) Si no matchea, prueba quitándole un sufijo de mes pegado al final,
     tipo " (Mar)", " (Ene)", etc. — que es la causa más común de error
     en cargas masivas armadas a partir de calendarios económicos que
     traen el mes incrustado en el nombre del evento.
  4) Lo que ni así matchea, lo lista aparte: esos son los que hay que
     decidir a mano (renombrar en el Excel al existente más parecido,
     o dar de alta el evento nuevo en EVENTOS).

Uso:
  1. Copiá este archivo a la carpeta donde tenés modulo_calendario.py
  2. Ajustá RUTA_CSV más abajo (o pasala como argumento de línea de comandos)
  3. Corré:  python revisar_eventos_csv.py tu_archivo.csv
"""

import re
import sys
import csv
from collections import Counter

try:
    from modulo_calendario import EVENTOS, INTERPRETACION_MACRO
except ImportError:
    print(
        "❌ No pude importar EVENTOS / INTERPRETACION_MACRO desde "
        "modulo_calendario.py.\n"
        "   Poné este script en la MISMA carpeta que tu módulo real y "
        "volvé a correrlo."
    )
    sys.exit(1)

# Sufijo de mes tipo " (Mar)", " (Ene)", " (May)" pegado al final del
# nombre del evento — con o sin punto, mayúsculas/minúsculas.
SUFIJO_MES = re.compile(
    r"\s*\((ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)\.?\)\s*$",
    re.IGNORECASE,
)


def quitar_sufijo_mes(nombre: str) -> str:
    return SUFIJO_MES.sub("", nombre).strip()


def main():
    ruta = sys.argv[1] if len(sys.argv) > 1 else "RUTA_CSV_ACA.csv"

    with open(ruta, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        filas = list(reader)

    if not filas or "evento" not in filas[0]:
        print("❌ El CSV no tiene columna 'evento' (o está vacío).")
        sys.exit(1)

    ok_directo = 0
    ok_sin_sufijo = 0
    sin_match = Counter()

    todos_los_nombres_validos = set(EVENTOS.keys()) | set(INTERPRETACION_MACRO.keys())

    for row in filas:
        evento = (row.get("evento") or "").strip()
        if not evento:
            continue

        if evento in EVENTOS:
            ok_directo += 1
            continue

        sin_mes = quitar_sufijo_mes(evento)
        if sin_mes != evento and sin_mes in EVENTOS:
            ok_sin_sufijo += 1
            continue

        # Ni directo ni sacándole el mes está en EVENTOS. Puede que
        # SÍ esté en INTERPRETACION_MACRO (tiene lectura macro pero
        # nunca se dio de alta en EVENTOS con categoría/impacto).
        candidato = sin_mes if sin_mes in INTERPRETACION_MACRO else evento
        if candidato in INTERPRETACION_MACRO:
            sin_match[f"[EN INTERPRETACION_MACRO, FALTA EN EVENTOS] {candidato}"] += 1
        else:
            sin_match[f"[NO EXISTE EN NINGÚN LADO] {sin_mes if sin_mes != evento else evento}"] += 1

    total = len(filas)
    print(f"Total de filas: {total}")
    print(f"✅ Matchean directo contra EVENTOS: {ok_directo}")
    print(f"✅ Matchean después de sacarles el sufijo de mes: {ok_sin_sufijo}")
    print(f"❌ Sin match de ninguna forma: {sum(sin_match.values())}")
    print()

    if sin_match:
        print("Detalle de los que quedan sin resolver (nombre único → veces que aparece):")
        for nombre, cant in sorted(sin_match.items(), key=lambda x: -x[1]):
            print(f"  {cant:>3}x  {nombre}")
        print()
        print(
            "Para los que dicen '[EN INTERPRETACION_MACRO, FALTA EN EVENTOS]': "
            "ya tenés la lectura macro escrita, solo falta agregarlos a EVENTOS "
            "(o EVENTOS_EXTENDIDOS) con categoría/impacto/polaridad, y listo — "
            "el parche que te paso ya los acepta igual sin que tengas que hacer "
            "nada más ahí.\n"
            "Para los que dicen '[NO EXISTE EN NINGÚN LADO]': son eventos "
            "realmente nuevos (o mal tipeados) — o los renombrás en el Excel al "
            "más parecido que ya tengas, o los das de alta desde cero."
        )
    else:
        print("🎉 No quedó ningún evento sin resolver.")


if __name__ == "__main__":
    main()
