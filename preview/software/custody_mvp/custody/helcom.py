"""Lineas vectoriales de HELCOM: costa e isobatas.

POR QUE ESTE FICHERO EXISTE, Y QUE BORRA.

La costa y las isobatas se derivaban del DTM de EMODnet con marching squares
sobre la rejilla de trabajo. Funcionaba, y era trabajo tirado: HELCOM publica
las dos, medidas, y el visor ya habla con ese servidor para las subcuencas,
los vertidos de municion y la planificacion espacial.

    costa derivada por nosotros   paso 0,03 grados  ~3 km
    costa de HELCOM (capa 13)     mediana entre vertices 8 m

Las isobatas derivadas salian de la misma rejilla de 3 km, asi que heredaban
su error; las de HELCOM (capa 14) vienen de la Baltic Sea Bathymetry Database
y traen el nivel en un campo, `CONTOUR`, lo que permite pedir SOLO las
profundidades que se usan en vez de bajarlas todas.

SE HORNEA EN EL BUILD, no se pide al navegar. Es la forma mas fuerte de
cache: una vez compilado no hay red, que es una propiedad que el producto
vende. La capa `coasthd` sigue existiendo para el detalle al acercarse; esto
es la version de conjunto.

EL COSTE NO SON LOS VERTICES, SON LAS ISLAS. Medido en un cuadro de 4x2
grados: 7.392 polilineas y 31.198 vertices, y simplificar mas no baja el
tamano porque lo domina el numero de piezas. Filtrar por longitud si:

    todas            7.392 lineas   1.029 kB
    islas >= 0,5 km  2.682 lineas     373 kB
    islas >= 2 km      538 lineas      75 kB

A escala de conjunto un islote de 300 m no se ve, asi que se tiran. El
detalle al acercarse lo trae `coasthd` desde el mismo servicio.
"""
import json
import logging
import math
import urllib.parse

from custody import net

LOG = logging.getLogger("custody.helcom")

BASE = "https://maps.helcom.fi/arcgis/rest/services/MADS/Background/MapServer"
COASTLINE_LAYER = 13
CONTOUR_LAYER = 14

# Los que publica HELCOM: -10, -20, -50, -100, -200, -300, -400, -500.
# Se piden los cuatro someros, que son los que deciden si un ancla alcanza.
ISOBATHS_M = [10, 20, 50, 100]


PAGE = 10000          # el maxRecordCount que declara el servicio


def _query(layer, bbox, offset, where="1=1", out_fields="*", timeout=300,
           refresh=False):
    """Una pagina tras otra hasta agotar el recuadro.

    El servicio corta en 10.000 registros y lo avisa con
    `exceededTransferLimit`. En el archipielago finlandes un solo recuadro de
    4x2 grados lo supera, asi que sin paginar se perdia costa en silencio --
    que es la peor forma de perderla.
    """
    feats, cached_all, offset_n = [], True, 0
    while True:
        url = (("%s/%d/query?" % (BASE, layer)) + "&".join([
            "where=" + urllib.parse.quote(where),
            "geometry=%g,%g,%g,%g" % bbox,
            "geometryType=esriGeometryEnvelope", "inSR=4326",
            "spatialRel=esriSpatialRelIntersects", "returnGeometry=true",
            "outSR=4326", "outFields=" + out_fields,
            "maxAllowableOffset=%g" % offset,
            "resultOffset=%d" % offset_n,
            "resultRecordCount=%d" % PAGE, "f=json"]))
        raw, cached = net.fetch(url, refresh=refresh, ext="json", timeout=timeout)
        cached_all = cached_all and cached
        d = json.loads(raw.decode("utf-8"))
        if d.get("error"):
            raise RuntimeError("HELCOM capa %d: %s" % (layer, d["error"]))
        got = d.get("features", [])
        feats.extend(got)
        if not d.get("exceededTransferLimit") or not got:
            break
        offset_n += len(got)
        if offset_n > 20 * PAGE:          # freno, no deberia darse
            LOG.warning("capa %d en %s: mas de %d registros, se corta",
                        layer, bbox, offset_n)
            break
    return feats, cached_all


def _len_km(path):
    s = 0.0
    for a, b in zip(path, path[1:]):
        s += math.hypot((a[0] - b[0]) * 55.0, (a[1] - b[1]) * 111.2)
    return s


def _tiles(aoi, step=4.0):
    minlon, minlat, maxlon, maxlat = aoi
    lon = minlon
    while lon < maxlon:
        lat = minlat
        while lat < maxlat:
            yield (lon, lat, min(lon + step, maxlon), min(lat + step, maxlat))
            lat += step
        lon += step


def _collect(layer, aoi, offset, min_km, where="1=1", out_fields="OBJECTID",
             prop=None, refresh=False):
    feats, seen, n_in, n_out = [], set(), 0, 0
    for bb in _tiles(aoi):
        got, _ = _query(layer, bb, offset, where=where, out_fields=out_fields,
                        refresh=refresh)
        for f in got:
            oid = (f.get("attributes") or {}).get("OBJECTID") or \
                  (f.get("attributes") or {}).get("OBJECTID_1")
            # Los recuadros se solapan en el borde: sin esto las costas
            # fronterizas salen por duplicado.
            if oid is not None:
                if oid in seen:
                    continue
                seen.add(oid)
            paths = [p for p in f["geometry"]["paths"]]
            n_in += len(paths)
            keep = [p for p in paths if _len_km(p) >= min_km and len(p) > 1]
            if not keep:
                continue
            n_out += len(keep)
            props = {}
            if prop:
                props[prop[1]] = (f.get("attributes") or {}).get(prop[0])
            feats.append({
                "type": "Feature", "properties": props,
                "geometry": {"type": "MultiLineString",
                             "coordinates": [[[round(c[0], 5), round(c[1], 5)]
                                              for c in p] for p in keep]}})
    return feats, {"paths_in": n_in, "paths_out": n_out, "features": len(feats)}


def coastline(aoi, offset=0.003, min_km=4.0, refresh=False):
    """Costa de HELCOM para toda el AOI, sin islotes."""
    feats, st = _collect(COASTLINE_LAYER, aoi, offset, min_km, refresh=refresh)
    st["vertices"] = sum(len(p) for f in feats
                         for p in f["geometry"]["coordinates"])
    return {"type": "FeatureCollection",
            "attribution": "HELCOM coastline (MADS/Background layer 13)",
            "note": "islets shorter than %g km dropped; simplified to %g deg"
                    % (min_km, offset),
            "features": feats}, st


def contours(aoi, levels=None, offset=0.002, min_km=2.0, refresh=False):
    """Isobatas de HELCOM, solo los niveles pedidos."""
    levels = levels or ISOBATHS_M
    # El campo guarda la profundidad en negativo.
    where = "CONTOUR IN (%s)" % ",".join(str(-abs(int(v))) for v in levels)
    feats, st = _collect(CONTOUR_LAYER, aoi, offset, min_km, where=where,
                         out_fields="OBJECTID_1,CONTOUR",
                         prop=("CONTOUR", "depth_m"), refresh=refresh)
    for f in feats:
        d = f["properties"].get("depth_m")
        if d is not None:
            f["properties"]["depth_m"] = abs(d)
    st["vertices"] = sum(len(p) for f in feats
                         for p in f["geometry"]["coordinates"])
    st["levels"] = levels
    return {"type": "FeatureCollection",
            "attribution": "HELCOM depth contours (MADS/Background layer 14), "
                           "from the Baltic Sea Bathymetry Database",
            "features": feats}, st


def segments(fc):
    """Las polilineas sueltas, para alimentar un SegmentIndex."""
    out = []
    for f in fc.get("features", []):
        out.extend(f["geometry"]["coordinates"])
    return out
