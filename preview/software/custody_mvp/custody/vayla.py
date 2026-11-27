"""Áreas de restricción a la navegación de Väylävirasto (Finnish Transport
Infrastructure Agency), WFS abierto, sin clave.

    https://avoinapi.vaylapilvi.fi/vaylatiedot/ows
    typeNames = vesivaylatiedot:rajoitusalue_a_uusi

Licencia: datos abiertos de Väylä, CC BY 4.0.
Fuente del hallazgo: canal/iteracion_02/04_coo.md A.4.1.

POR QUÉ ESTÁ EN EL MVP. El tipo `Ankkurin käyttökielto` es *prohibición de
fondeo*: es la versión jurídica, publicada y citable de «aquí este buque no
debía haber fondeado». Un indicador conductual dice que un buque fue despacio
sobre un cable; esta capa dice si ese punto está dentro de un área donde fondear
está prohibido por decisión administrativa, con su `diaarinumero`. Esa es la
diferencia entre una sospecha y un hecho oponible.

RESULTADO MEDIDO (2026-11-09, bbox 22-30,5 E / 59-60,9 N): 521 áreas de
restricción, de las que **6** son de prohibición de fondeo. Cinco están en el
canal de Saimaa (vía interior) y la sexta a 4,3 km de un cable de telecom en la
aproximación del mar de Åland. **Ninguna sobre Estlink 1, Estlink 2, C-Lion 1 ni
Balticconnector en el golfo abierto.** No es un fallo de la capa: es el vacío
que hay que enseñar.

Nota de ejes: con `srsName=urn:ogc:def:crs:OGC:1.3:CRS84` el servidor devuelve
lon,lat (verificado). Con `EPSG:4326` GeoServer puede invertirlos; no se usa.
"""
import logging
import urllib.parse

from . import geo, net

LOG = logging.getLogger("custody.vayla")
WFS = "https://avoinapi.vaylapilvi.fi/vaylatiedot/ows"
LAYER = "vesivaylatiedot:rajoitusalue_a_uusi"
ATTRIBUTION = "Väylävirasto, datos abiertos, CC BY 4.0"
CRS84 = "urn:ogc:def:crs:OGC:1.3:CRS84"
ANCHOR_BAN = "Ankkurin käyttökielto"

# Traducción de los tipos observados. No es exhaustiva: lo que no esté aquí se
# publica con su cadena finlandesa literal, sin inventar traducción.
# El visor es ingles. El finlandes original se conserva aparte, porque es el
# termino legal y es lo que aparece en el expediente de Vaylavirasto.
TYPES_EN = {
    "Nopeusrajoitus": "speed limit",
    "Aluksen kulku moottorivoimaa käyttäen kielletty": "no engine-powered navigation",
    "Aallokon aiheuttamisen kielto": "no wake",
    "Vesiskootterilla ajo kielletty": "no personal watercraft",
    "Ankkurin käyttökielto": "ANCHORING PROHIBITED",
    "Tehorajoitus": "engine power limit",
    "Vesihiihtokielto": "no water skiing",
    "Pysäköimiskielto": "no mooring",
    "Tuntematon": "unknown",
}


def _ring_of(geom):
    """Primer anillo exterior de un Polygon o MultiPolygon."""
    if not geom:
        return []
    c = geom.get("coordinates") or []
    if geom["type"] == "Polygon":
        return c[0] if c else []
    if geom["type"] == "MultiPolygon":
        return c[0][0] if c and c[0] else []
    return []


def fetch_restrictions(bbox, refresh=False):
    """bbox = (minlon, minlat, maxlon, maxlat). Devuelve (GeoJSON, stats)."""
    url = WFS + "?" + urllib.parse.urlencode({
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": LAYER, "outputFormat": "application/json",
        "srsName": CRS84,
        "bbox": "%.4f,%.4f,%.4f,%.4f,%s" % (bbox[0], bbox[1], bbox[2], bbox[3], CRS84)})
    doc, cached = net.fetch_json(url, refresh=refresh, timeout=300, retries=3)

    feats = []
    st = {"from_cache": cached, "matched": doc.get("numberMatched"),
          "returned": doc.get("numberReturned"), "by_type": {}, "anchor_ban": 0}
    for f in doc.get("features", []):
        p = f.get("properties", {})
        t = p.get("rajoitustyyppi") or "Tuntematon"
        ban = ANCHOR_BAN in t
        st["by_type"][t] = st["by_type"].get(t, 0) + 1
        if ban:
            st["anchor_ban"] += 1
        feats.append({
            "type": "Feature", "id": p.get("id"),
            "geometry": f.get("geometry"),
            "properties": {
                "vayla_id": p.get("id"),
                "restriction_fi": t,
                "restriction_en": " + ".join(TYPES_EN.get(x.strip(), x.strip())
                                             for x in t.split(",")),
                "anchoring_prohibited": ban,
                "magnitude": p.get("suuruus"),
                "exception": p.get("poikkeus"),
                "extra": p.get("lisatieto"),
                "decision_state": p.get("paatostila"),
                "valid_from": p.get("alkupaivamaara"),
                "valid_to": p.get("loppupaivamaara"),
                "diaarinumero": p.get("diaarinumero"),
                "source_register": p.get("tietolahde"),
                "place": p.get("nimisijainti"),
            }})
    return {"type": "FeatureCollection", "features": feats,
            "properties": {"attribution": ATTRIBUTION, "source": "Väylävirasto WFS",
                           "layer": LAYER}}, st


def anchor_ban_mask(fc):
    """PolygonMask solo con las áreas de prohibición de fondeo."""
    m = geo.PolygonMask()
    for f in fc["features"]:
        if not f["properties"].get("anchoring_prohibited"):
            continue
        ring = _ring_of(f["geometry"])
        if len(ring) >= 3:
            m.add([(c[0], c[1]) for c in ring],
                  f["properties"].get("place") or "área de prohibición de fondeo")
    return m


def anchor_bans_near_corridors(fc, corridor_idx, max_m=2000.0):
    """Cuántas prohibiciones de fondeo caen a <= max_m de un corredor trunk.

    Es la comprobación que convierte la capa en un hallazgo: si sale 0, el
    corredor estratégico NO tiene cobertura jurídica de prohibición de fondeo.
    """
    hits, checked = [], 0
    for f in fc["features"]:
        if not f["properties"].get("anchoring_prohibited"):
            continue
        ring = _ring_of(f["geometry"])
        if not ring:
            continue
        checked += 1
        lon = sum(c[0] for c in ring) / len(ring)
        lat = sum(c[1] for c in ring) / len(ring)
        d, payload = corridor_idx.nearest(lon, lat, max_rings=4)
        hits.append({"place": f["properties"].get("place"),
                     "lon": round(lon, 5), "lat": round(lat, 5),
                     "nearest_trunk_corridor": payload[0] if payload else None,
                     "distance_m": round(d, 1) if d is not None else None,
                     "within_max_m": bool(d is not None and d <= max_m)})
    return {"anchor_ban_areas": checked,
            "within_%dm_of_trunk" % int(max_m): sum(1 for h in hits if h["within_max_m"]),
            "detail": hits}
