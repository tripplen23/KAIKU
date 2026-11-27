"""Copernicus Data Space Ecosystem: catálogo STAC y descarga de productos.

Endpoint STAC verificado (iteración 01, canal/iteracion_01/04_coo.md, y de
nuevo el 2026-11-09): https://stac.dataspace.copernicus.eu/v1/search
responde SIN autenticación. El endpoint que citaba el documento `06` no es el
que funciona; este sí.

Lo que se obtiene sin cuenta (verificado 2026-11-09):
  - metadatos completos del item y el FOOTPRINT exacto;
  - el asset `thumbnail` (quicklook PNG, p.ej. 297x191) servido por
    datahub.creodias.eu en HTTP 200 sin cabecera de autorización.

Lo que NO se obtiene sin cuenta:
  - el asset `Product` (SAFE completo, ~1,2 GB) en download.dataspace.copernicus.eu
  - los assets `vv`/`vh` por S3 (s3://eodata/...), que exigen credenciales S3.

El quicklook está en geometría imagen (range/azimuth), no es un raster
norte-arriba. Aquí se publica como miniatura y como footprint vectorial
exacto. NO se georreferencia al bbox y se presenta como si estuviera medido.
"""
import json
import logging
import os
import urllib.parse

from . import net

LOG = logging.getLogger("custody.sentinel")
STAC = "https://stac.dataspace.copernicus.eu/v1/search"
TOKEN_URL = ("https://identity.dataspace.copernicus.eu/auth/realms/CDSE/"
             "protocol/openid-connect/token")
CREDS_FILE_HINT = "cdse_credentials.json"


def search(bbox, start, end, collections=("sentinel-1-grd",), limit=20, refresh=False,
           extra=None):
    """POST /v1/search. bbox = (minlon, minlat, maxlon, maxlat), fechas ISO-8601."""
    body = {"collections": list(collections),
            "bbox": list(bbox),
            "datetime": "%s/%s" % (start, end),
            "limit": limit}
    if extra:
        body.update(extra)
    doc, cached = net.fetch_json(STAC, body=body, refresh=refresh, timeout=120)
    items = doc.get("features", [])
    st = {"returned": len(items), "from_cache": cached,
          "matched": doc.get("numberMatched")}
    return items, st


def item_summary(it):
    p = it.get("properties", {})
    assets = it.get("assets", {})
    return {
        "id": it.get("id"),
        "collection": it.get("collection"),
        "datetime": p.get("datetime"),
        "platform": p.get("platform"),
        "product_type": p.get("product:type"),
        "polarizations": p.get("sar:polarizations"),
        "orbit_state": p.get("sat:orbit_state"),
        "relative_orbit": p.get("sat:relative_orbit"),
        "absolute_orbit": p.get("sat:absolute_orbit"),
        "processing_level": p.get("processing:level"),
        "thumbnail_href": (assets.get("thumbnail") or {}).get("href"),
        "product_href": (assets.get("Product") or {}).get("href"),
        "s3_vv": (assets.get("vv") or {}).get("href"),
        "s3_vh": (assets.get("vh") or {}).get("href"),
        "product_size_bytes": (p.get("_private") or {}).get("product_size"),
    }


def to_geojson(items, quicklooks=None):
    """FeatureCollection con los footprints exactos."""
    feats = []
    for it in items:
        s = item_summary(it)
        if quicklooks:
            s["quicklook_local"] = quicklooks.get(s["id"])
        s["quicklook_georeferenced"] = False
        feats.append({"type": "Feature", "id": s["id"],
                      "geometry": it.get("geometry"), "properties": s})
    return {"type": "FeatureCollection", "features": feats,
            "properties": {"source": "Copernicus Data Space Ecosystem STAC",
                           "attribution": "Contains modified Copernicus Sentinel data",
                           "endpoint": STAC}}


def fetch_quicklook(item, outdir, refresh=False):
    """Descarga el quicklook público. Devuelve la ruta relativa o None."""
    s = item_summary(item)
    href = s["thumbnail_href"]
    if not href:
        return None
    try:
        raw, _ = net.fetch(href, refresh=refresh, ext="png", timeout=180)
    except Exception as exc:
        LOG.warning("quicklook %s no descargable: %s", s["id"], exc)
        return None
    if raw[:8] != b"\x89PNG\r\n\x1a\n" and raw[:2] != b"\xff\xd8":
        LOG.warning("quicklook %s no es PNG/JPEG (%r)", s["id"], raw[:8])
        return None
    os.makedirs(outdir, exist_ok=True)
    ext = "png" if raw[:8] == b"\x89PNG\r\n\x1a\n" else "jpg"
    name = "%s.%s" % (s["id"], ext)
    with open(os.path.join(outdir, name), "wb") as fh:
        fh.write(raw)
    return name


# ------------------------------------------------------------------ descarga

def load_credentials(path):
    """Credenciales CDSE. Orden: entorno > secrets.env > JSON heredado.

    secrets.env es el formato preferido porque toma el valor literal tras el
    primer '=': un password con comillas dobles rompe el JSON (visto en
    produccion) y aqui no necesita escape. Permisos 600, en .gitignore.
    """
    u, p = os.environ.get("CDSE_USERNAME"), os.environ.get("CDSE_PASSWORD")
    if u and p:
        return u, p

    env_path = os.path.join(os.path.dirname(os.path.abspath(path or ".")), "secrets.env") \
        if path else "secrets.env"
    for cand in (os.environ.get("CUSTODY_SECRETS"), env_path, "secrets.env"):
        if cand and os.path.exists(cand):
            vals = {}
            with open(cand, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    vals[k.strip()] = v.strip().strip("'").strip('"') if (
                        v.strip()[:1] == v.strip()[-1:] and v.strip()[:1] in "'\"") else v.strip()
            if vals.get("CDSE_USERNAME") and vals.get("CDSE_PASSWORD"):
                return vals["CDSE_USERNAME"], vals["CDSE_PASSWORD"]

    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
        except (ValueError, OSError) as exc:
            # Un password con comillas dobles aterriza aqui. No se vuelca el
            # fichero en el log: solo el motivo.
            LOG.warning("%s ilegible (%s). Usa secrets.env o las variables de entorno.",
                        path, exc)
            return None, None
        if d.get("username") and d.get("password") and \
           not d["username"].startswith("PON_AQUI"):
            return d["username"], d["password"]
    return None, None


def get_token(username, password):
    """OAuth2 Resource Owner Password Credentials contra el realm CDSE.

    NO VERIFICADO EN EJECUCIÓN: no existe cuenta CDSE para este proyecto. El
    flujo y el client_id 'cdse-public' son los documentados por CDSE.
    """
    body = urllib.parse.urlencode({
        "client_id": "cdse-public", "grant_type": "password",
        "username": username, "password": password}).encode()
    doc, _ = net.fetch_json(TOKEN_URL, body=body,
                            headers={"Content-Type": "application/x-www-form-urlencoded"},
                            cache=False, timeout=60)
    return doc["access_token"]


def download_product(item, outdir, creds_path=None):
    """Descarga el SAFE completo (~1,2 GB). Requiere cuenta CDSE.

    Devuelve (ruta, None) o (None, motivo). Nunca lanza por falta de
    credenciales: el build debe continuar y dejar la capa etiquetada.
    """
    s = item_summary(item)
    if not s["product_href"]:
        return None, "el item no expone asset 'Product'"
    user, pwd = load_credentials(creds_path)
    if not user:
        return None, ("sin credenciales CDSE: rellena %s o exporta "
                      "CDSE_USERNAME/CDSE_PASSWORD" % (creds_path or CREDS_FILE_HINT))
    try:
        tok = get_token(user, pwd)
    except Exception as exc:
        return None, "fallo de autenticación CDSE: %s" % exc
    os.makedirs(outdir, exist_ok=True)
    dest = os.path.join(outdir, s["id"] + ".zip")
    try:
        raw, _ = net.fetch(s["product_href"], headers={"Authorization": "Bearer " + tok},
                           cache=False, timeout=3600)
    except Exception as exc:
        return None, "fallo de descarga: %s" % exc
    with open(dest, "wb") as fh:
        fh.write(raw)
    return dest, None
