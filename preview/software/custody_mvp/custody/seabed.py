"""Lo que hay EN el fondo y lo que pasa ENCIMA: pecios, munición, zonas militares.

POR QUE ESTAS TRES CAPAS Y NO OTRAS
-----------------------------------
Las tres responden a preguntas que el visor ya se hacía y no sabía contestar.

  PECIOS (`wwshipwrecks`). 693 en el golfo, 347 catalogados «dangerous wreck»,
      y entre ellos CUATRO SUBMARINOS: el U-26 alemán (1915), el S-5, el NO 9
      hundido el 22-05-1931 y uno británico sin nombre. Un pecio es un retorno
      radar permanente y un obstáculo fijo: importa porque una detección SAR
      junto a un pecio puede ser el pecio, y porque un buque que se para justo
      encima puede estar buceando sobre él y no saboteando un cable.

  ZONAS MILITARES (`militaryareaspoly`). 24 Áreas de Defensa Nacional de
      Finlandia y Estonia, con enlace a la fuente oficial. Esto ataca de
      frente el problema del NATO WARSHIP: un buque de guerra merodeando
      DENTRO de un área de defensa declarada no es una anomalía, es un martes.
      No se suprime la alerta — se anota, que es la norma de este proyecto.

  MUNICIÓN (`munitionspoly`). 3 vertederos rusos de explosivo convencional en
      el golfo, procedentes de HELCOM. Fondear ahí está prohibido y es
      peligroso, así que cambia por completo la lectura de un fondeo.

LO QUE NO EXISTE, Y CONVIENE DECIRLO
------------------------------------
NO hay base de datos abierta de POSICIONES de submarinos, ni la habrá. Un
submarino sumergido no emite AIS porque el VHF no atraviesa el agua, y en
superficie las armadas lo apagan. La posición de un submarino es de lo más
reservado que tiene cualquier marina. Lo que sí es abierto son los
INVENTARIOS (Wikidata tiene las clases y los cascos por armada) y los PECIOS,
que es lo que trae este módulo.

Fuente: EMODnet Human Activities WFS, comprobado el 2026-11-10 contra el AOI
del golfo. Términos EMODnet, uso abierto con atribución.
"""
import json
import logging
import urllib.parse

from . import geo, net

LOG = logging.getLogger("custody.seabed")
WFS = "https://ows.emodnet-humanactivities.eu/wfs"
ATTRIBUTION = "EMODnet Human Activities"

LAYERS = {
    "wrecks":    "emodnet:wwshipwrecks",
    "military":  "emodnet:militaryareaspoly",
    "munitions": "emodnet:munitionspoly",
}
# Un pecio a menos de esto de una alerta es candidato a explicarla.
WRECK_NEAR_M = 500.0
# Campos de `wwshipwrecks` que valen algo. El resto son metadatos de sondeo.
WRECK_KEEP = ("wreck_id", "wreck_cate", "name", "type", "flag", "date_sunk",
              "length", "width", "depth", "water_dept", "tonnage", "cargo",
              "circumstan", "conspic_ra", "orientatio")


def _na(v):
    """EMODnet escribe 'n/a' en vez de dejar el campo vacío."""
    if v is None:
        return None
    s = str(v).strip()
    return None if s in ("", " ", "n/a", "N/A", "Unknown", "unknown") else v


def fetch(layer, bbox, count=5000, refresh=False, max_pages=12):
    """Descarga paginada. El WFS corta en `count` por peticion y al ampliar el
    AOI al Baltico los pecios tocaron ese techo: 5.000 exactos, que es el
    numero que devuelve un servidor truncando, no el numero de pecios que hay.
    Se pagina con startIndex hasta agotar."""
    feats, cached_all, start, truncated = [], True, 0, False
    for _page in range(max_pages):
        q = {"service": "WFS", "version": "2.0.0", "request": "GetFeature",
             "typeNames": LAYERS[layer], "outputFormat": "application/json",
             "srsName": "EPSG:4326", "count": str(count),
             "startIndex": str(start),
             "bbox": "%s,%s,%s,%s,EPSG:4326" % tuple(bbox)}
        url = WFS + "?" + urllib.parse.urlencode(q)
        raw, cached = net.fetch(url, refresh=refresh, timeout=240, ext="json")
        cached_all = cached_all and cached
        doc = json.loads(raw.decode("utf-8"))
        page = doc.get("features", [])
        feats.extend(page)
        if len(page) < count:
            break
        start += count
    else:
        truncated = True
        LOG.warning("%s: %d elementos y seguia habiendo mas tras %d paginas",
                    layer, len(feats), max_pages)
    return feats, {"returned": len(feats), "from_cache": cached_all,
                   "pages": start // count + 1, "truncated": truncated}


def wrecks(bbox, refresh=False):
    feats, st = fetch("wrecks", bbox, refresh=refresh)
    out, subs = [], 0
    for f in feats:
        p = {k: _na(v) for k, v in f["properties"].items() if k in WRECK_KEEP}
        p = {k: v for k, v in p.items() if v is not None}
        p["source"] = ATTRIBUTION
        if "sub" in str(p.get("type", "")).lower():
            p["is_submarine"] = True
            subs += 1
        p["dangerous"] = "danger" in str(p.get("wreck_cate", "")).lower()
        out.append({"type": "Feature", "properties": p, "geometry": f["geometry"]})
    st["submarines"] = subs
    st["dangerous"] = sum(1 for f in out if f["properties"]["dangerous"])
    if st.get("truncated"):
        st["warning"] = ("la descarga se corto tras %d paginas; hay mas pecios "
                         "de los que se muestran" % st.get("pages", 0))
    LOG.info("pecios: %d (%d peligrosos, %d submarinos)", len(out),
             st["dangerous"], subs)
    return {"type": "FeatureCollection", "features": out}, st


def _polys(layer, bbox, name_of, refresh=False):
    feats, st = fetch(layer, bbox, refresh=refresh)
    out = []
    for f in feats:
        p = {k: _na(v) for k, v in f["properties"].items()}
        p = {k: v for k, v in p.items() if v is not None}
        p["name"] = name_of(p)
        p["source"] = ATTRIBUTION
        out.append({"type": "Feature", "properties": p, "geometry": f["geometry"]})
    LOG.info("%s: %d poligonos", layer, len(out))
    return {"type": "FeatureCollection", "features": out}, st


def military_areas(bbox, refresh=False):
    return _polys("military", bbox, lambda p: "%s — %s" % (
        p.get("country", "?"), p.get("type_1", "military area")), refresh=refresh)


def munitions(bbox, refresh=False):
    return _polys("munitions", bbox, lambda p: p.get("description")
                  or ("%s munitions dumping area" % p.get("munition_type", "")),
                  refresh=refresh)


def _rings(geom):
    """Todos los anillos exteriores de un Polygon o MultiPolygon."""
    t = geom.get("type")
    if t == "Polygon":
        return [geom["coordinates"][0]]
    if t == "MultiPolygon":
        return [poly[0] for poly in geom["coordinates"]]
    return []


def mask_of(fc):
    m = geo.PolygonMask()
    for f in fc["features"]:
        for ring in _rings(f["geometry"]):
            if len(ring) >= 3:
                m.add([(c[0], c[1]) for c in ring], f["properties"].get("name") or "?")
    return m


def wreck_index(fc):
    """Lista plana (lon, lat, nombre) para la consulta de cercanía."""
    out = []
    for f in fc["features"]:
        g = f["geometry"]
        if g.get("type") != "Point":
            continue
        p = f["properties"]
        label = p.get("name") or p.get("type") or p.get("wreck_cate") or "wreck"
        if p.get("is_submarine"):
            label = "submarine wreck " + str(p.get("name") or "")
        out.append((g["coordinates"][0], g["coordinates"][1], label.strip(),
                    bool(p.get("dangerous"))))
    return out


def nearest_wreck(idx, lon, lat, max_m=WRECK_NEAR_M):
    """(nombre, metros, peligroso) del pecio más próximo, o None."""
    best = None
    dlat = max_m / 111320.0
    for wlon, wlat, name, dang in idx:
        if abs(wlat - lat) > dlat:
            continue                       # descarte barato antes del haversine
        d = geo.haversine_m(lon, lat, wlon, wlat)
        if d <= max_m and (best is None or d < best[1]):
            best = (name, round(d, 1), dang)
    return best


# ------------------------------------------------ por qué un área es especial
# El atributo que publica EMODnet es escueto: país, tipo y superficie. Eso
# dice QUE está designada, no POR QUÉ importa. La justificación util se
# calcula contra lo que ya tenemos en el build: qué infraestructura cruza el
# polígono, qué hay en el fondo, cuánta prohibición de fondeo lo respalda y
# cuánto tráfico pasa. Es específica de cada área y la puede comprobar un
# tercero con los mismos ficheros.

# Instrumento legal por país. Se cita lo verificado y se marca lo que no.
LEGAL_BASIS = {
    "Finland": {
        "instrument": "Aluevalvontalaki 755/2000 (Territorial Surveillance Act)",
        "note": "Finnish territorial surveillance law provides for protected areas "
                "(suoja-alue) in territorial waters where anchoring, diving and "
                "underwater activity require permission. The polygon shown here comes "
                "from the Finnish Maritime Spatial Plan via EMODnet, NOT from the "
                "statute text: treat the boundary as indicative and the specific "
                "article as unverified until checked against Finlex.",
        "verify": "https://www.finlex.fi/fi/laki/ajantasa/2000/20000755",
    },
    "Estonia": {
        "instrument": "Estonian Ministry of Defence designation",
        "note": "Boundary published through EMODnet from the Estonian Ministry of "
                "Defence. The designating instrument is not carried in the dataset.",
        "verify": "https://www.kaitseministeerium.ee/en",
    },
}


def _bbox_of(ring):
    xs = [c[0] for c in ring]
    ys = [c[1] for c in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _area_km2(ring):
    """Área por la fórmula del polígono, en proyección equirectangular local."""
    if len(ring) < 3:
        return 0.0
    lat0 = sum(c[1] for c in ring) / len(ring)
    kx = geo.m_per_deg_lon(lat0) / 1000.0
    ky = geo.M_PER_DEG_LAT / 1000.0
    a = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i][0] * kx, ring[i][1] * ky
        x2, y2 = ring[(i + 1) % len(ring)][0] * kx, ring[(i + 1) % len(ring)][1] * ky
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def _in_any_ring(lon, lat, rings):
    for bb, ring in rings:
        if bb[0] <= lon <= bb[2] and bb[1] <= lat <= bb[3] and \
           geo.point_in_ring(lon, lat, ring):
            return True
    return False


def _coords_of(geom):
    """Todos los vértices de cualquier geometría, aplanados."""
    t, c = geom.get("type"), geom.get("coordinates")
    if t == "Point":
        return [c]
    if t in ("LineString", "MultiPoint"):
        return list(c)
    if t in ("Polygon", "MultiLineString"):
        return [p for part in c for p in part]
    if t == "MultiPolygon":
        return [p for poly in c for part in poly for p in part]
    return []


def justify_areas(mil_fc, corridors=None, wrecks_fc=None, restrictions=None,
                  depth_grid=None, tracks=None):
    """Añade a cada área militar el porqué: qué contiene y cuánto se usa."""
    for f in mil_fc["features"]:
        rings = [(_bbox_of(r), r) for r in _rings(f["geometry"]) if len(r) >= 3]
        if not rings:
            continue
        p = f["properties"]
        p["area_km2"] = round(sum(_area_km2(r) for _b, r in rings), 1)
        why = {}

        # Infraestructura submarina que cruza el area. Es la razon numero uno
        # por la que un area de defensa esta donde esta.
        if corridors:
            names = {}
            for c in corridors.get("features", []):
                cp = c["properties"]
                for lon, lat in _coords_of(c["geometry"]):
                    if _in_any_ring(lon, lat, rings):
                        key = cp.get("name") or "unnamed"
                        names[key] = {"kind": cp.get("asset_class"),
                                      "operator": cp.get("operator")}
                        break
            if names:
                why["corridors"] = [dict(v, name=k) for k, v in
                                    sorted(names.items())][:12]

        if wrecks_fc:
            n = subs = 0
            for w in wrecks_fc.get("features", []):
                g = w["geometry"]
                if g.get("type") != "Point":
                    continue
                if _in_any_ring(g["coordinates"][0], g["coordinates"][1], rings):
                    n += 1
                    if w["properties"].get("is_submarine"):
                        subs += 1
            if n:
                why["wrecks"] = {"count": n, "submarines": subs}

        # Prohibicion de fondeo dentro: es la cobertura juridica REAL, la que
        # convierte «zona sensible» en «conducta sancionable».
        if restrictions:
            bans = 0
            for r in restrictions.get("features", []):
                if not r["properties"].get("anchoring_prohibited"):
                    continue
                for lon, lat in _coords_of(r["geometry"]):
                    if _in_any_ring(lon, lat, rings):
                        bans += 1
                        break
            why["anchoring_bans_inside"] = bans

        if depth_grid:
            ds = []
            for bb, _r in rings:
                steps = 7
                for i in range(steps + 1):
                    for j in range(steps + 1):
                        lon = bb[0] + (bb[2] - bb[0]) * i / steps
                        lat = bb[1] + (bb[3] - bb[1]) * j / steps
                        if not _in_any_ring(lon, lat, rings):
                            continue
                        d = depth_grid.depth_at(lon, lat)
                        if d is not None and d > 0:
                            ds.append(d)
            if ds:
                why["depth_m"] = {"min": round(min(ds), 1), "max": round(max(ds), 1),
                                  "samples": len(ds)}

        # Trafico propio: cuantos buques distintos lo han atravesado en la
        # ventana grabada. Dice si es un area dormida o un cruce vivo.
        if tracks:
            seen = set()
            for mmsi, fixes in tracks.items():
                for fx in fixes:
                    if _in_any_ring(fx["lon"], fx["lat"], rings):
                        seen.add(mmsi)
                        break
            why["vessels_seen"] = len(seen)

        p["why"] = why
        p["legal"] = LEGAL_BASIS.get(p.get("country"))
    return mil_fc
