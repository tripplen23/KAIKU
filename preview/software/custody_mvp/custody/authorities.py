"""Quién prohíbe qué, y en qué aguas. Registro de autoridades del Báltico.

EL PROBLEMA QUE RESUELVE
------------------------
`vayla.py` trae las restricciones a la navegación de Finlandia. Mientras el
AOI era el golfo de Finlandia eso cubría casi todo el mapa. Al ampliar al
Báltico entero cubre una franja, y el hallazgo «hay cable y no hay prohibición
de fondeo» se vuelve una afirmación sobre Finlandia disfrazada de afirmación
sobre el Báltico.

El Báltico lo vigilan nueve países. Este módulo es el REGISTRO: una entrada por
autoridad, con su cobertura, su licencia y cómo se descarga. Añadir Suecia el
día que publiquen un endpoint es añadir una fila, no reescribir un módulo.

LO QUE SE ENCONTRÓ (comprobado el 2026-11-10)
---------------------------------------------
  FI  Väylävirasto, WFS propio. Ya integrado, es el más detallado de todos:
      521 restricciones en el golfo, con tipo y número de expediente.
  EE LT LV DE
      HELCOM «MSP Restricted Use», ArcGIS REST pan-báltico: 75 áreas de los
      planes de ordenación marítima, con país, uso y qué está prohibido.
      Estonia 30, Alemania 28, Lituania 10, Letonia 7.
  --- resto del Báltico, con la razón ---
  SE  Sjöfartsverket y Havs- och vattenmyndigheten: no respondieron ninguno de
      los tres endpoints probados (geodata.havochvatten.se 404,
      inspire.sjofartsverket.se sin respuesta, geodata.se 500). Suecia NO está
      en la capa MSP de HELCOM. Es el hueco más importante que queda: es el
      otro país que vive el problema de los cables.
  PL DK
      Tienen plan de ordenación marítima aprobado pero no aparecen en la capa
      de HELCOM. Sin endpoint localizado.
  RU  Sin fuente abierta. No se espera que la haya.

Nada de esto se inventa: lo que no se pudo descargar se declara como hueco y
sale en pantalla como hueco.
"""
import json
import logging
import urllib.parse

from . import geo, net

LOG = logging.getLogger("custody.authorities")

HELCOM_MSP = ("https://maps.helcom.fi/arcgis/rest/services/MADS/"
              "Human_Activities/MapServer/158/query")

# Estado de cada ribereño. `wired` dice si HOY entra dato en el build.
REGISTRY = [
    {"cc": "FI", "country": "Finland", "wired": True, "via": "vayla",
     "authority": "Väylävirasto (Finnish Transport Infrastructure Agency)",
     "licence": "CC BY 4.0", "url": "https://vayla.fi",
     "note": "WFS propio. La fuente más detallada del Báltico: tipo de "
             "restricción, número de expediente y estado de la decisión."},
    {"cc": "EE", "country": "Estonia", "wired": True, "via": "helcom_msp",
     "authority": "Estonian maritime spatial plan, via HELCOM",
     "licence": "HELCOM terms", "url": "https://maps.helcom.fi",
     "note": None},
    {"cc": "DE", "country": "Germany", "wired": True, "via": "helcom_msp",
     "authority": "German maritime spatial plan, via HELCOM",
     "licence": "HELCOM terms", "url": "https://maps.helcom.fi", "note": None},
    {"cc": "LT", "country": "Lithuania", "wired": True, "via": "helcom_msp",
     "authority": "Lithuanian maritime spatial plan, via HELCOM",
     "licence": "HELCOM terms", "url": "https://maps.helcom.fi", "note": None},
    {"cc": "LV", "country": "Latvia", "wired": True, "via": "helcom_msp",
     "authority": "Latvian maritime spatial plan, via HELCOM",
     "licence": "HELCOM terms", "url": "https://maps.helcom.fi", "note": None},
    {"cc": "SE", "country": "Sweden", "wired": False, "via": None,
     "authority": "Sjöfartsverket / Havs- och vattenmyndigheten",
     "licence": None, "url": "https://www.havochvatten.se",
     "note": "Tres endpoints probados el 2026-11-10, ninguno respondió, y "
             "Suecia no está en la capa MSP de HELCOM. EL HUECO MÁS IMPORTANTE: "
             "es el otro país con el problema de los cables encima."},
    {"cc": "PL", "country": "Poland", "wired": False, "via": None,
     "authority": "Urząd Morski", "licence": None, "url": None,
     "note": "Plan de ordenación aprobado, sin endpoint localizado."},
    {"cc": "DK", "country": "Denmark", "wired": False, "via": None,
     "authority": "Søfartsstyrelsen (Danish Maritime Authority)",
     "licence": None, "url": "https://www.dma.dk",
     "note": "Sin endpoint localizado; no aparece en la capa MSP de HELCOM."},
    {"cc": "RU", "country": "Russia", "wired": False, "via": None,
     "authority": None, "licence": None, "url": None,
     "note": "Sin fuente abierta, y no se espera que la haya. Las aguas rusas "
             "del golfo y de Kaliningrado quedan sin capa jurídica."},
]


def coverage():
    """Resumen para el manifest y para enseñar el hueco en pantalla."""
    wired = [r for r in REGISTRY if r["wired"]]
    return {
        "countries_total": len(REGISTRY),
        "countries_wired": len(wired),
        "wired": [r["cc"] for r in wired],
        "missing": [{"cc": r["cc"], "country": r["country"],
                     "authority": r["authority"], "note": r["note"]}
                    for r in REGISTRY if not r["wired"]],
        "registry": REGISTRY,
    }


def _esri_rings_to_geojson(geom):
    """ArcGIS devuelve `rings`; GeoJSON quiere Polygon/MultiPolygon.

    Esri no distingue anillo exterior de agujero por el orden del array sino
    por el sentido de giro: horario = exterior, antihorario = agujero. Se
    respeta, porque tratar un agujero como polígono suelto pinta tierra firme
    donde hay un hueco.
    """
    rings = geom.get("rings") or []
    if not rings:
        return None
    polys, holes = [], []
    for r in rings:
        if len(r) < 4:
            continue
        area2 = 0.0
        for i in range(len(r) - 1):
            area2 += r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1]
        (polys if area2 < 0 else holes).append([[c[0], c[1]] for c in r])
    if not polys:
        polys, holes = [[[c[0], c[1]] for c in rings[0]]], []
    if len(polys) == 1:
        return {"type": "Polygon", "coordinates": [polys[0]] + holes}
    return {"type": "MultiPolygon", "coordinates": [[p] for p in polys]}


def helcom_msp(bbox, refresh=False):
    """Áreas de uso restringido de los planes de ordenación del Báltico."""
    q = {
        "where": "1=1", "outFields": "*", "returnGeometry": "true",
        "f": "json", "outSR": "4326", "resultRecordCount": "5000",
        "geometryType": "esriGeometryEnvelope", "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "geometry": "%s,%s,%s,%s" % tuple(bbox),
    }
    url = HELCOM_MSP + "?" + urllib.parse.urlencode(q)
    raw, cached = net.fetch(url, refresh=refresh, timeout=240, ext="json")
    doc = json.loads(raw.decode("utf-8"))
    if "error" in doc:
        raise RuntimeError("HELCOM MSP: %s" % str(doc["error"])[:160])
    feats = []
    for f in doc.get("features", []):
        g = _esri_rings_to_geojson(f.get("geometry") or {})
        if not g:
            continue
        a = f.get("attributes", {})
        def _s(k):
            v = a.get(k)
            v = (str(v).strip() if v is not None else "")
            return v or None
        forbidden = _s("forbidden_info")
        feats.append({"type": "Feature", "geometry": g, "properties": {
            "source": "HELCOM MADS · maritime spatial plans",
            "country": _s("country"),
            "use": _s("useDsc"),
            "plan_id": _s("planId"),
            "restricted": _s("restricted_info"),
            "forbidden": forbidden,
            "allowed": _s("allowed_info"),
            "priority": _s("priority_info"),
            # Lo que importa para este proyecto: ¿prohíbe algo que toque el
            # fondo? Se marca, no se filtra.
            "bottom_impact_forbidden": bool(
                forbidden and any(w in forbidden.lower() for w in
                                  ("anchor", "dredg", "infrastructure",
                                   "installation", "cable", "pipeline"))),
        }})
    by_cc = {}
    for f in feats:
        cc = f["properties"]["country"] or "??"
        by_cc[cc] = by_cc.get(cc, 0) + 1
    LOG.info("HELCOM MSP: %d áreas restringidas %s (cache=%s)",
             len(feats), by_cc, cached)
    return ({"type": "FeatureCollection", "features": feats},
            {"areas": len(feats), "by_country": by_cc, "from_cache": cached})


def mask_of(fc):
    """PolygonMask de las áreas que prohíben tocar el fondo."""
    m = geo.PolygonMask()
    for f in fc["features"]:
        if not f["properties"].get("bottom_impact_forbidden"):
            continue
        g = f["geometry"]
        rings = ([g["coordinates"][0]] if g["type"] == "Polygon"
                 else [p[0] for p in g["coordinates"]])
        for ring in rings:
            if len(ring) >= 3:
                m.add([(c[0], c[1]) for c in ring],
                      "%s — %s" % (f["properties"].get("country") or "?",
                                   (f["properties"].get("use") or "restricted")[:60]))
    return m
