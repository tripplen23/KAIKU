"""Corredores de infraestructura submarina y máscara de puerto/fondeadero.

Fuente: OpenStreetMap vía Overpass API. Licencia ODbL 1.0, atribución
obligatoria: "(c) OpenStreetMap contributors, ODbL 1.0".

Por qué OSM y no EMODnet Human Activities: verificado en iteración 01
(canal/iteracion_01/04_coo.md, H3) que los datasets de cables de EMODnet
cubren DE/ES/FR/MT/NL/NO/UK y tienen CERO cobertura finlandesa o báltica
oriental. OSM sí tiene Estlink 1, Estlink 2, C-Lion 1 y Balticconnector.

Overpass devuelve HTTP 406 con el User-Agent por defecto de urllib: el
User-Agent de custody.net es obligatorio, no cosmético.
"""
import logging

from . import geo, net

LOG = logging.getLogger("custody.corridors")
OVERPASS = "https://overpass-api.de/api/interpreter"
# Overpass es notoriamente inestable bajo carga: en la prueba de caché fría del
# 2026-11-09 devolvió 502 Bad Gateway tras 3 reintentos mientras la segunda
# consulta (puertos) pasaba. Con 5 reintentos y backoff hasta 60 s la ventana
# de recuperación es de ~2 min, que es el tiempo típico de su cola de slots.
OVERPASS_RETRIES = 5
OVERPASS_TIMEOUT = 300
ATTRIBUTION = "(c) OpenStreetMap contributors, ODbL 1.0"

# bbox por defecto: (min_lat, min_lon, max_lat, max_lon) -- orden de Overpass.
# OJO: es un valor de cortesia para pruebas sueltas, NO el AOI del proyecto.
# build.py pasa siempre el suyo. Quien olvide pasarlo recibe el golfo de
# Finlandia y un build que parece correcto mientras consulta otra zona: paso
# exactamente eso al ampliar el alcance al Baltico el 2026-11-10.
AOI_OVERPASS = (59.0, 19.0, 60.9, 30.5)

Q_CORRIDORS = """[out:json][timeout:240];
(
  way["submarine"="yes"]({bbox});
  way["location"="underwater"]["power"]({bbox});
  way["location"="underwater"]["man_made"="pipeline"]({bbox});
  way["submarine"="yes"]["man_made"="pipeline"]({bbox});
);
out tags geom;
"""

Q_PORTS = """[out:json][timeout:240];
(
  way["seamark:type"="harbour"]({bbox});
  way["seamark:type"="anchorage"]({bbox});
  way["seamark:type"="harbour_basin"]({bbox});
  way["landuse"="harbour"]({bbox});
  way["waterway"="dock"]({bbox});
  way["seamark:type"="pilot_boarding_place"]({bbox});
  node["seamark:type"="anchorage"]({bbox});
  node["seamark:type"="anchor_berth"]({bbox});
  node["seamark:type"="pilot_boarding_place"]({bbox});
  node["seamark:type"="harbour"]({bbox});
);
out tags geom;
"""


def _classify(tags):
    if tags.get("power") in ("cable", "line") or tags.get("cable:type") == "power":
        return "power"
    if tags.get("man_made") == "pipeline" or tags.get("pipeline"):
        return "pipeline"
    if tags.get("communication") == "line" or tags.get("telecom") or \
       tags.get("communication:data") == "yes" or tags.get("cable") == "communication":
        return "telecom"
    if tags.get("seamark:type") == "cable_submarine":
        return "cable_unspecified"
    return "unspecified"


def fetch_corridors(bbox=AOI_OVERPASS, refresh=False, trunk_min_len_m=5000.0):
    """GeoJSON FeatureCollection de corredores + estadísticas.

    `trunk` = corredor con nombre y longitud >= trunk_min_len_m. Es el
    criterio que separa los enlaces internacionales (Estlink, C-Lion,
    Balticconnector) de los cientos de ramales portuarios sin nombre. Es un
    criterio sobre el dato, no una lista blanca de nombres.
    """
    q = Q_CORRIDORS.format(bbox="%.4f,%.4f,%.4f,%.4f" % bbox)
    doc, cached = net.fetch_json(OVERPASS, body=q.encode(),
                                 headers={"Content-Type": "text/plain; charset=utf-8"},
                                 refresh=refresh, retries=OVERPASS_RETRIES,
                                 timeout=OVERPASS_TIMEOUT)
    feats = []
    st = {"elements": len(doc.get("elements", [])), "named": 0, "trunk": 0,
          "from_cache": cached, "osm_timestamp": doc.get("osm3s", {}).get("timestamp_osm_base"),
          "by_class": {}, "trunk_names": [], "total_km": 0.0, "trunk_km": 0.0}

    for el in doc.get("elements", []):
        gm = el.get("geometry")
        if not gm or len(gm) < 2:
            continue
        coords = [(p["lon"], p["lat"]) for p in gm]
        tags = el.get("tags", {})
        name = (tags.get("name") or "").strip()
        length = geo.polyline_length_m(coords)
        cls = _classify(tags)
        trunk = bool(name) and length >= trunk_min_len_m
        if name:
            st["named"] += 1
        st["by_class"][cls] = st["by_class"].get(cls, 0) + 1
        st["total_km"] += length / 1000.0
        if trunk:
            st["trunk"] += 1
            st["trunk_km"] += length / 1000.0
            st["trunk_names"].append(name)
        feats.append({
            "type": "Feature",
            "id": "%s/%s" % (el["type"], el["id"]),
            "geometry": {"type": "LineString", "coordinates": [list(c) for c in coords]},
            "properties": {
                "name": name or None,
                "asset_class": cls,
                "operator": tags.get("operator"),
                "owner": tags.get("owner"),
                "vayla_id": tags.get("vayla_id") or tags.get("ref:vayla"),
                "length_m": round(length, 1),
                "trunk": trunk,
                "osm_id": "%s/%s" % (el["type"], el["id"]),
            },
        })

    st["trunk_names"] = sorted(set(st["trunk_names"]))
    return {"type": "FeatureCollection", "features": feats,
            "properties": {"attribution": ATTRIBUTION, "source": "OSM Overpass",
                           "query": q.strip()}}, st


def build_index(fc, trunk_only=True):
    """SegmentIndex sobre los corredores. payload = (name, asset_class, osm_id)."""
    idx = geo.SegmentIndex()
    n = 0
    for f in fc["features"]:
        p = f["properties"]
        if trunk_only and not p.get("trunk"):
            continue
        idx.add_polyline(f["geometry"]["coordinates"],
                         (p.get("name"), p.get("asset_class"), p.get("osm_id")))
        n += 1
    return idx, n


def fetch_port_mask(bbox=AOI_OVERPASS, refresh=False, node_radius_m=1500.0):
    """Máscara de puertos, fondeaderos y estaciones de práctico.

    Necesaria por un resultado medido en iteración 01: sin máscara, un filtro
    ingenuo de loitering da ~13 % de falsos positivos, casi todos buques
    atracados que mantienen navStat=0
    (canal/iteracion_01/01_systems_engineer.md §4).

    `seamark:type=pilot_boarding_place` se añadió tras medir IND-06: las flotas
    de prácticos amarradas en sus bases (Harmaja, Emäsalo) están a 2,6 y 7,5 km
    de la costa, o sea «en la mar» para cualquier criterio geométrico, y
    producían 16 de 16 falsos positivos de encuentro barco a barco.
    """
    q = Q_PORTS.format(bbox="%.4f,%.4f,%.4f,%.4f" % bbox)
    doc, cached = net.fetch_json(OVERPASS, body=q.encode(),
                                 headers={"Content-Type": "text/plain; charset=utf-8"},
                                 refresh=refresh, retries=OVERPASS_RETRIES,
                                 timeout=OVERPASS_TIMEOUT)
    mask = geo.PolygonMask()
    feats = []
    st = {"elements": len(doc.get("elements", [])), "polygons": 0, "nodes": 0,
          "degenerate_rings": 0, "from_cache": cached}
    for el in doc.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name") or tags.get("seamark:name") or el.get("type")
        if el["type"] == "node":
            mask.add_circle(el["lon"], el["lat"], node_radius_m, name)
            st["nodes"] += 1
            feats.append({"type": "Feature",
                          "geometry": {"type": "Point", "coordinates": [el["lon"], el["lat"]]},
                          "properties": {"name": name, "kind": tags.get("seamark:type"),
                                         "buffer_m": node_radius_m}})
        else:
            gm = el.get("geometry") or []
            ring = [(p["lon"], p["lat"]) for p in gm if p]
            if len(ring) < 3:
                continue
            mask.add(ring, name)
            st["polygons"] += 1
            # RFC 7946: un anillo lineal se cierra y tiene >= 4 posiciones.
            # Overpass devuelve la geometría sin cerrar en algunas vías.
            closed = list(ring)
            if closed[0] != closed[-1]:
                closed.append(closed[0])
            if len(closed) < 4:
                st["polygons"] -= 1
                st["degenerate_rings"] = st.get("degenerate_rings", 0) + 1
                continue
            feats.append({"type": "Feature",
                          "geometry": {"type": "Polygon", "coordinates": [[list(c) for c in closed]]},
                          "properties": {"name": name,
                                         "kind": tags.get("seamark:type") or tags.get("landuse")}})
    return mask, {"type": "FeatureCollection", "features": feats,
                  "properties": {"attribution": ATTRIBUTION}}, st
