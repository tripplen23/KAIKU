"""GPSJAM: interferencia de GPS vista desde las aeronaves.

QUE ES.

John Wiseman publica un mapa diario de interferencia probable de GPS
derivado de lo que las propias aeronaves emiten. Un avion difunde, junto a su
posicion, **cuanta precision declara tener**. Si el GPS se degrada, esa
incertidumbre declarada sube. Agregando todos los aviones de un dia sobre una
rejilla hexagonal sale un mapa de donde el GPS iba mal.

Fuente de las emisiones: airplanes.live y ADS-B Exchange.

LO QUE HAY QUE DECIR ANTES DE ENSENARLO, Y QUE NO ES POCO.

Esta capa aporta contexto, no prueba. Cuatro limites, los cuatro del autor o
medidos aqui:

  1. **AGREGA VEINTICUATRO HORAS.** Una interferencia de cinco minutos pinta
     la celda entera de rojo todo el dia. Cruzar eso con un salto de posicion
     AIS con marca de tiempo al segundo es una coincidencia debil, no una
     correlacion: la capa dice «ese dia, por esa zona, habia interferencia»,
     y nada mas fino que eso.
  2. **LLEGA UNO O DOS DIAS TARDE.** Medido el 2026-11-14: el fichero del
     dia 12 estaba, el del 13 devolvia 404. No sirve para vigilar ahora.
  3. **NO CUBRE DONDE NO VUELAN AVIONES.** Es el punto ciego que mas duele:
     el Baltico abierto y el Golfo de Botnia tienen menos trafico aereo que
     los corredores continentales. Nuestra cobertura AIS muere hacia los
     57 N; esta muere en otro sitio, lo que es bueno --- se complementan--- y
     malo: hay mar donde no llega ninguna de las dos. `coverage()` dibuja
     ese limite: el contorno de lo observado, para que un hueco se lea como
     hueco y no como calma.
  4. **UN AVION NO ES UN BUQUE.** A diez kilometros de altura se ve un emisor
     terrestre que un barco a veinte millas de la costa quiza no ve, y al
     reves: la curvatura y el horizonte no son los mismos.

Y lo que el autor dice en su pagina de preguntas: **no distingue bloqueo de
suplantacion.** «The data doesn't tell me what's causing the low accuracy.»
Puede recoger pruebas militares y sistemas antidrón, no solo ataques.

CELDAS. Rejilla hexagonal H3 de resolucion 4: unos 1.770 km2 por celda, como
22 km de lado. Convertir el identificador de celda en un poligono necesita la
biblioteca `h3`, que es la unica dependencia de todo el proyecto y es
OPCIONAL: sin ella esta capa se queda vacia y lo dice, el resto del build
sigue igual.

FORMATO, con una trampa. `https://gpsjam.org/data/YYYY-MM-DD-h3_4.csv`
devuelve un CSV **comprimido con gzip pero servido sin extension `.gz`**: hay
que descomprimir aunque la URL diga `.csv`. Columnas:
`hex,count_good_aircraft,count_bad_aircraft`.

LICENCIA: **no publicada.** Ni en la pagina principal ni en la de «about».
Fuentes secundarias dicen CC BY, pero el sitio no lo dice en ninguna parte, y
las emisiones vienen de ADS-B Exchange, que tiene sus propios terminos. Entra
en el registro como sin licencia declarada: se dibuja y se cita, no se
revende, y hay que escribir al autor antes de publicar nada derivado.
"""
import datetime as dt
import gzip
import io
import logging
import math

from custody import net

LOG = logging.getLogger("custody.gpsjam")

URL = "https://gpsjam.org/data/%s-h3_4.csv"
# Un dia: el fichero de una fecha pasada no cambia nunca, pero el de la mas
# reciente aparece cuando aparece, asi que no se cachea para siempre.
MAX_AGE_S = 86400
LOOKBACK_DAYS = 4       # cuanto se retrocede buscando el dia mas reciente


def _fetch_day(day, refresh=False):
    raw, cached = net.fetch(URL % day, ext="csvgz", timeout=180,
                            max_age=MAX_AGE_S, refresh=refresh, retries=0)
    # Servido como .csv y comprimido igualmente. Se comprueba el numero magico
    # en vez de fiarse de la extension ni del Content-Type.
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
    return raw.decode("utf-8", "replace"), cached


def latest_day(today=None, refresh=False):
    """La fecha mas reciente que existe. Devuelve (fecha, texto) o (None, None).

    Se retrocede dia a dia porque la latencia no es fija: el fichero se
    reconstruye hacia medianoche UTC y a veces tarda dos dias.
    """
    d0 = today or dt.datetime.now(dt.timezone.utc).date()
    for back in range(LOOKBACK_DAYS):
        day = (d0 - dt.timedelta(days=back)).isoformat()
        try:
            txt, _ = _fetch_day(day, refresh=refresh)
            if txt.startswith("hex,"):
                return day, txt
        except Exception as exc:
            LOG.debug("gpsjam %s: %s", day, str(exc)[:60])
    return None, None


def cells(aoi, day=None, min_aircraft=1):
    """Celdas del area con su fraccion de aeronaves degradadas.

    `min_aircraft` descarta celdas con un solo avion en todo el dia: una sola
    aeronave degradada da 100 % y pinta 1.770 km2 de rojo sobre una muestra de
    uno. Es ruido con aspecto de senal.
    """
    try:
        import h3
    except ImportError:
        raise RuntimeError("falta la biblioteca h3: correr software/venv.sh")
    if day:
        txt, _ = _fetch_day(day)
        got = day
    else:
        got, txt = latest_day()
    if not txt:
        raise RuntimeError("gpsjam: ningun fichero disponible en %d dias"
                           % LOOKBACK_DAYS)
    out, total, skipped = [], 0, 0
    for line in txt.splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 3:
            continue
        total += 1
        try:
            good, bad = int(parts[1]), int(parts[2])
        except ValueError:
            continue
        cell = parts[0]
        try:
            lat, lon = h3.cell_to_latlng(cell)
        except Exception:
            continue
        if not (aoi[0] <= lon <= aoi[2] and aoi[1] <= lat <= aoi[3]):
            continue
        n = good + bad
        if n < min_aircraft:
            continue
        if n < 2:
            skipped += 1
            continue
        out.append({"cell": cell, "lat": lat, "lon": lon,
                    "good": good, "bad": bad,
                    "frac_bad": round(bad / n, 3) if n else 0.0})
    return out, {"day": got, "cells_global": total, "cells_in_aoi": len(out),
                 "cells_single_aircraft_dropped": skipped}


def geojson(aoi, day=None):
    """Hexagonos listos para el mapa. Solo celdas con alguna degradada."""
    import h3
    cs, st = cells(aoi, day=day)
    feats = []
    for c in cs:
        if not c["bad"]:
            continue
        ring = h3.cell_to_boundary(c["cell"])          # [(lat, lon), ...]
        coords = [[round(lon, 5), round(lat, 5)] for lat, lon in ring]
        coords.append(coords[0])
        feats.append({"type": "Feature", "properties": {
            "cell": c["cell"], "day": st["day"],
            "aircraft_good": c["good"], "aircraft_degraded": c["bad"],
            "fraction_degraded": c["frac_bad"],
            "aggregation": "whole UTC day: five minutes of interference "
                           "paints the cell for twenty-four hours",
            "caveat": "Aircraft at altitude, not vessels at sea level. Says "
                      "'there was interference around here that day', not "
                      "when and not what caused it.",
        }, "geometry": {"type": "Polygon", "coordinates": [coords]}})
    feats.sort(key=lambda f: -f["properties"]["fraction_degraded"])
    st["cells_with_degraded"] = len(feats)
    return ({"type": "FeatureCollection", "features": feats,
             "properties": {
                 "source": "gpsjam.org (John Wiseman), from airplanes.live and "
                           "ADS-B Exchange aircraft reports",
                 "grid": "H3 resolution 4, about 1770 km2 per cell",
                 "licence": "not published by the site; cite, do not resell",
                 **st}}, st)


def _aoi_area_km2(aoi):
    """Area de la caja en km2 sobre la esfera. Un rectangulo en grados no es
    un rectangulo en km: a 60 N un grado de longitud mide la mitad que en el
    ecuador, y el AOI del Baltico va de 53 N a 66 N."""
    R = 6371.0088
    lon0, lat0, lon1, lat1 = aoi
    return (math.radians(lon1 - lon0) * R * R
            * abs(math.sin(math.radians(lat1)) - math.sin(math.radians(lat0))))


def coverage(aoi, day=None):
    """EL CONTORNO DE LO QUE ESTA CAPA PUEDE VER, que no es el AOI.

    `geojson()` dibuja solo las celdas CON alguna aeronave degradada. Sin esto,
    el mapa no distingue dos cosas opuestas: una celda sin hexagono porque los
    aviones de ese dia volaron bien, y una celda sin hexagono porque por ahi no
    volo nadie. La primera es un dato; la segunda es un hueco, y el Baltico
    abierto esta lleno de ellos.

    Se devuelve el perimetro de las celdas OBSERVADAS --- las que tuvieron al
    menos dos aeronaves en el dia, el mismo umbral que usa `cells()` --- y su
    area real, sumando celda a celda: un hexagono H3 de resolucion 4 no mide lo
    mismo a 53 N que a 66 N, asi que el promedio de 1.770 km2 no vale para
    totalizar.

    El borde se queda fuera del AOI hasta unos 11 km, porque una celda entra
    por su centro y luego se dibuja entera. No se recorta: recortar pediria una
    biblioteca de geometria, y el error es menor que la propia celda.
    """
    import h3
    cs, st = cells(aoi, day=day)
    ids = [c["cell"] for c in cs]
    area = sum(h3.cell_area(c, unit="km^2") for c in ids)
    area_aoi = _aoi_area_km2(aoi)
    degradadas = [c for c in cs if c["bad"]]
    area_bad = sum(h3.cell_area(c["cell"], unit="km^2") for c in degradadas)
    st.update({
        "area_observed_km2": round(area),
        "area_aoi_km2": round(area_aoi),
        "aoi_fraction_observed": round(area / area_aoi, 3) if area_aoi else None,
        "cells_with_degraded": len(degradadas),
        "area_degraded_km2": round(area_bad),
        "observed_fraction_degraded": round(area_bad / area, 3) if area else None,
    })
    feats = []
    if ids:
        geo = h3.h3shape_to_geo(h3.cells_to_h3shape(ids, tight=False))
        # Una pieza por poligono: el area observada no es un solo trozo, y
        # dibujar los huecos interiores es la mitad del valor de la capa.
        for poly in geo["coordinates"]:
            feats.append({"type": "Feature", "properties": {
                "day": st["day"],
                "cells_observed": len(ids),
                "area_observed_km2": st["area_observed_km2"],
                "aoi_fraction_observed": st["aoi_fraction_observed"],
                "meaning": "Inside this outline the layer saw at least two "
                           "aircraft that day, so the absence of a red hexagon "
                           "means the GPS was fine. Outside it, nothing was "
                           "measured at all.",
            }, "geometry": {"type": "Polygon",
                            "coordinates": [[[round(x, 5), round(y, 5)]
                                             for x, y in ring]
                                            for ring in poly]}})
    return ({"type": "FeatureCollection", "features": feats,
             "properties": {
                 "source": "gpsjam.org (John Wiseman), from airplanes.live and "
                           "ADS-B Exchange aircraft reports",
                 "grid": "H3 resolution 4; area summed cell by cell, not from "
                         "the 1770 km2 average",
                 "edge": "cells enter by their centre and are drawn whole, so "
                         "the outline overshoots the AOI by up to ~11 km",
                 **st}}, st)


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    from custody import paths
    fc, st = geojson(paths.aoi())
    print(json.dumps(st, indent=1))
    for f in fc["features"][:12]:
        p = f["properties"]
        c = f["geometry"]["coordinates"][0][0]
        print("  %5.1f N %5.1f E   %2d degradadas de %2d  (%.0f %%)"
              % (c[1], c[0], p["aircraft_degraded"],
                 p["aircraft_degraded"] + p["aircraft_good"],
                 100 * p["fraction_degraded"]))
