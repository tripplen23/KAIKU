"""AISHub: el mapa de estaciones, que es el argumento de cobertura.

QUE SE PUEDE HACER HOY Y QUE NO.

AISHub es una cooperativa: contribuyes el NMEA crudo de tu propio receptor y
recibes el agregado de 1.500+ estaciones. El AGREGADO exige clave de API, y
la clave exige tener una estacion aprobada. Eso no se puede hacer desde aqui.

La LISTA DE ESTACIONES, en cambio, es publica y se exporta sin cuenta. Y es
justamente lo que contesta la pregunta que tiene el producto abierta: nuestra
cobertura AIS es el 21 % del AOI y muere hacia los 57 N, lo que deja los
cortes de cable de noviembre de 2024 cerca de Gotland en el punto ciego.

Medido el 2026-11-13 sobre la exportacion publica:

    estaciones en la red          1.797
    dentro de nuestro AOI           204
    en el hueco (56-60 N, 16-24 E)   32

Las que importan: Visby y Faro en Gotland, Karlskrona, Kalmar, Oskarshamn,
Liepaja, Klaipeda, Kuressaare, el archipielago de Estocolmo, Ust-Luga y San
Petersburgo. Gotland es el dato: ahi se cortaron los cables y ahi no vemos
nada; dos estaciones de voluntarios si.

Asi que esta capa no es decorado. Dibuja, sobre el mapa, cuanta cobertura
existe que no tenemos, que es el caso de negocio de pedir el acceso.

REDISTRIBUCION PROHIBIDA, y conviene saberlo antes de prometerle nada a un
cliente: el agregado se puede USAR, no revender. La lista de estaciones es
otra cosa --es publica-- pero la atribucion se cita igual.
"""
import json
import logging
import os
import time
import urllib.parse

from custody import creds, net

LOG = logging.getLogger("custody.aishub")

URL = "https://www.aishub.net/stations/export-json"
API = "https://data.aishub.net/ws.php"

# Una peticion por minuto, que es el limite del servicio y tambien la
# cadencia del grabador. Encaja exacto.
MIN_INTERVAL_S = 60
_last_call = [0.0]

# El hueco: donde nuestros receptores no llegan y se cortaron los cables.
GAP = (16.0, 56.0, 24.0, 60.0)


def _in(bbox, lon, lat):
    return bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]


def fetch(aoi, refresh=False):
    raw, cached = net.fetch(URL, refresh=refresh, ext="json", timeout=120)
    d = json.loads(raw.decode("utf-8", "replace"))
    rows = d if isinstance(d, list) else (d.get("stations") or d.get("data") or [])

    feats, n_aoi, n_gap = [], 0, 0
    by_country = {}
    for r in rows:
        try:
            lon, lat = float(r["longitude"]), float(r["latitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if not _in(aoi, lon, lat):
            continue
        n_aoi += 1
        gap = _in(GAP, lon, lat)
        if gap:
            n_gap += 1
        c = (r.get("country") or "?").strip()
        by_country[c] = by_country.get(c, 0) + 1
        feats.append({
            "type": "Feature",
            "properties": {
                "id": r.get("id"), "country": c,
                "location": (r.get("location") or "").strip(),
                "in_gap": gap,
                "last_seen_ms": (int(r["unix_time"]) * 1000
                                 if str(r.get("unix_time") or "").isdigit() else None),
            },
            "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
        })

    return {
        "type": "FeatureCollection",
        "attribution": "Data: AISHub contributors (https://www.aishub.net)",
        "note": ("Station locations only, from the public export. The aggregated "
                 "vessel feed needs an API key, which needs a contributing "
                 "receiver. Redistribution of the feed is prohibited."),
        "gap_bbox": list(GAP),
        "features": feats,
    }, {"network_total": len(rows), "in_aoi": n_aoi, "in_gap": n_gap,
        "by_country": dict(sorted(by_country.items(), key=lambda x: -x[1])),
        "from_cache": cached}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    fc, st = fetch((9.0, 53.5, 30.5, 66.0))
    print("red %d · en el AOI %d · en el hueco %d"
          % (st["network_total"], st["in_aoi"], st["in_gap"]))
    print("por pais:", ", ".join("%s %d" % kv for kv in
                                 list(st["by_country"].items())[:12]))
    print("\nlas del hueco, que son las que faltan:")
    for f in fc["features"]:
        if f["properties"]["in_gap"]:
            p = f["properties"]
            print("   %-28s %-4s %7.2f %6.2f" % (p["location"][:28], p["country"],
                                                 f["geometry"]["coordinates"][0],
                                                 f["geometry"]["coordinates"][1]))


# ------------------------------------------------------------- el agregado
#
# COMPROBADO EL 2026-11-13: sin clave la API devuelve 200 con CERO bytes.
# Con un usuario inventado, lo mismo. Exige una clave valida, y la clave
# exige un receptor propio aprobado. No hay forma de rodearlo, y conviene
# decirlo asi en vez de dejar un cliente que parece funcionar y no trae nada.
#
# El cliente esta entero igualmente: el dia que exista la clave, se pega en
# secrets.env como AISHUB_USERNAME y el motor en vivo pasa a tener 204
# estaciones mas, 32 de ellas donde hoy no vemos nada.
#
# LA RESTRICCION QUE HAY QUE RESPETAR: el agregado se puede USAR, no
# redistribuir, ni gratis ni de pago. O sea: alimenta nuestras alertas, no
# sale por una API nuestra.


def have_key():
    return bool(creds.secret("AISHUB_USERNAME"))


def fetch_vessels(aoi, refresh=False):
    """El agregado de la red, acotado al AOI. Devuelve (fixes, stats).

    fixes sale ya en la forma que usa custody/ais.py, para que el motor en
    vivo pueda mezclarlo con Fintraffic sin traducir nada.
    """
    user = creds.secret("AISHUB_USERNAME")
    if not user:
        return [], {"ok": False, "reason": "no_key",
                    "note": "AISHub needs an API key, and the key needs a "
                            "contributing receiver. Set AISHUB_USERNAME in "
                            "secrets.env once you have one."}

    # El limite de la cooperativa es una peticion por minuto. Pasarse es la
    # forma mas rapida de que te retiren la clave.
    wait = MIN_INTERVAL_S - (time.time() - _last_call[0])
    if wait > 0:
        return [], {"ok": False, "reason": "rate_limit",
                    "note": "one request per minute; %.0f s to go" % wait}

    url = API + "?" + urllib.parse.urlencode({
        "username": user, "format": 1, "output": "json", "compress": 0,
        "lonmin": aoi[0], "latmin": aoi[1], "lonmax": aoi[2], "latmax": aoi[3]})
    raw, _ = net.fetch(url, refresh=True, ext="json", timeout=90)
    _last_call[0] = time.time()
    if not raw.strip():
        return [], {"ok": False, "reason": "empty",
                    "note": "AISHub answered 200 with no body, which is what "
                            "it does when the key is missing or not approved."}
    try:
        d = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return [], {"ok": False, "reason": "bad_json", "note": raw[:120].decode(
            "utf-8", "replace")}

    # El formato 1 devuelve [cabecera, [buques...]].
    rows = d[1] if isinstance(d, list) and len(d) > 1 and isinstance(d[1], list) else d
    if isinstance(d, list) and d and isinstance(d[0], dict) and d[0].get("ERROR"):
        return [], {"ok": False, "reason": "api_error",
                    "note": str(d[0].get("ERROR_MESSAGE") or d[0])[:160]}

    out = []
    for r in rows if isinstance(rows, list) else []:
        try:
            out.append({
                "mmsi": int(r["MMSI"]),
                "ts": int(r["TIME"]) * 1000 if str(r.get("TIME", "")).isdigit()
                      else _epoch(r.get("TIME")),
                "lon": float(r["LONGITUDE"]), "lat": float(r["LATITUDE"]),
                "sog": float(r["SOG"]) if r.get("SOG") not in (None, "") else None,
                "cog": float(r["COG"]) if r.get("COG") not in (None, "") else None,
                "hdg": int(r["HEADING"]) if str(r.get("HEADING", "")).isdigit() else None,
                "navStat": r.get("NAVSTAT"),
                "src": "aishub",
            })
        except (KeyError, TypeError, ValueError):
            continue
    return out, {"ok": True, "vessels": len(out)}


def _epoch(s):
    import datetime as dt
    try:
        return int(dt.datetime.strptime(str(s), "%Y-%m-%d %H:%M:%S")
                   .replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    except Exception:
        return 0
