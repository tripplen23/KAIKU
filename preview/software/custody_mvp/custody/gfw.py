"""Global Fishing Watch API v3: eventos de comportamiento y presencia SAR.

QUE APORTA Y QUE NO
-------------------
GFW NO entrega posiciones AIS crudas. Entrega DERIVADOS, y ese es justamente
su valor aquí: son una segunda opinión independiente sobre los mismos buques
que ya vemos por Fintraffic.

  GAP        apagado de AIS que el modelo de GFW marca como INTENCIONADO.
             Es IND-04 calculado por otro equipo, con otro modelo y cobertura
             global. Si GFW y nosotros coincidimos en un hueco, la alerta deja
             de depender de nuestro umbral.
  ENCOUNTER  dos buques juntos en el mar el tiempo suficiente. Corrobora
             IND-06.
  LOITERING  buque merodeando a baja velocidad. Relevante sobre un cable.
  PORT_VISIT escala en puerto, con nivel de confianza 2-4.
  FISHING    pesca. En el golfo de Finlandia será casi vacío; se deja porque
             cuesta una línea y el AOI puede moverse.

REJILLAS 4WINGS
---------------
El mapa de calor que publica GFW en su web sale de `4wings/report`: una rejilla
de celdas con horas de actividad. Tres datasets, y el que importa aquí NO es
el de pesca:

  public-global-fishing-effort  horas de pesca aparente. En el golfo de
      Finlandia hay algo (arrastreros polacos y estonios) pero no es la
      amenaza: los cables los rompe un mercante, no un pesquero.
  public-global-presence        horas de presencia de CUALQUIER buque. Esto sí:
      es la LÍNEA BASE de tráfico normal por celda. Todo lo que mide este
      proyecto hasta ahora es absoluto («lento sobre un cable = alerta»); con
      una línea base se puede decir «esta celda ve 0,3 buque-hora de media y
      hoy ha visto 6», que es anomalía contra historia y no contra un umbral
      inventado.
  public-global-sar-presence    detecciones Sentinel-1. Con `filters[0]` a
      `matched = 'false'` son detecciones de radar SIN AIS asociado: buque
      oscuro. Es el producto más caro de replicar por cuenta propia.

Contrato (gfwr/R/gfw_4wings.R, comprobado contra el gateway el 2026-11-10:
responde 401 sin token, o sea URL correcta):

  POST /v3/4wings/report?datasets[0]=..&spatial-resolution=LOW|HIGH
       &temporal-resolution=HOURLY|DAILY|MONTHLY|YEARLY
       &group-by=..&date-range=INI,FIN&format=CSV
  Authorization: Bearer <GFW_TOKEN>
  {"geojson": {FeatureCollection}}
  -> ZIP con un CSV dentro.

Resolución espacial: LOW = 0,1 grados, HIGH = 0,01. El rango no puede pasar de
366 días; se valida antes de salir a la red.

CONTRATO VERIFICADO
-------------------
Endpoints y nombres de dataset tomados del cliente oficial de GFW
(github.com/GlobalFishingWatch/gfwr, R/gfw_endpoint.R y R/gfw_event.R) y
comprobados contra el gateway el 2026-11-10: los tres responden 401
{"error":"invalid token"} sin cabecera Authorization, o sea que la URL es
correcta y lo único que falta es la credencial.

  POST https://gateway.api.globalfishingwatch.org/v3/events
       ?limit=N&offset=0&sort=%2Bstart
  Authorization: Bearer <GFW_TOKEN>
  {"datasets":["public-global-gaps-events:latest"],
   "startDate":"2025-01-01","endDate":"2026-01-01","duration":1,
   "geometry":{GeoJSON}}

El token se pide en globalfishingwatch.org/our-apis/tokens y vive en
secrets.env como GFW_TOKEN. Nunca se escribe en el manifest ni en la caché:
net.py hashea (método, url, cuerpo) y las cabeceras quedan fuera de la clave.

LICENCIA: CC BY-SA 4.0. La atribución es obligatoria y está en el visor.
"""
import logging

from urllib.parse import urlencode

from . import creds, net

LOG = logging.getLogger("custody.gfw")
BASE = "https://gateway.api.globalfishingwatch.org/v3"

DATASETS = {
    "GAP": "public-global-gaps-events:latest",
    "ENCOUNTER": "public-global-encounters-events:latest",
    "LOITERING": "public-global-loitering-events:latest",
    "PORT_VISIT": "public-global-port-visits-events:latest",
    "FISHING": "public-global-fishing-events:latest",
}
# Lo que tiene sentido en el golfo: tráfico mercante, no pesca.
DEFAULT_EVENTS = ("GAP", "ENCOUNTER", "LOITERING", "PORT_VISIT")

PAGE = 1000

RASTERS = {
    "fishing":  "public-global-fishing-effort:latest",
    "presence": "public-global-presence:latest",
    "sar":      "public-global-sar-presence:latest",
}
CELL_DEG = {"LOW": 0.1, "HIGH": 0.01}


def token():
    return creds.secret("GFW_TOKEN")


def _bbox_geometry(bbox):
    minlon, minlat, maxlon, maxlat = bbox
    ring = [[minlon, minlat], [maxlon, minlat], [maxlon, maxlat],
            [minlon, maxlat], [minlon, minlat]]
    return {"type": "Polygon", "coordinates": [ring]}


def fetch_events(event_type, bbox, start, end, tok=None, duration=1,
                 refresh=False, max_pages=20):
    """Lista de `entries` crudas de la API. Pagina hasta agotar o max_pages."""
    tok = tok or token()
    if not tok:
        raise RuntimeError("falta GFW_TOKEN (secrets.env o entorno)")
    ds = DATASETS[event_type]
    out, offset, total = [], 0, None
    for _ in range(max_pages):
        url = "%s/events?limit=%d&offset=%d&sort=%%2Bstart" % (BASE, PAGE, offset)
        body = {"datasets": [ds], "startDate": start, "endDate": end,
                "duration": duration, "geometry": _bbox_geometry(bbox)}
        doc, cached = net.fetch_json(
            url, body=body, headers={"Authorization": "Bearer " + tok},
            refresh=refresh, timeout=180)
        entries = doc.get("entries") or []
        total = doc.get("total", total)
        out.extend(entries)
        if len(entries) < PAGE:
            break
        offset += PAGE
    LOG.info("gfw %-10s %4d eventos (total declarado %s)", event_type, len(out), total)
    return out, {"returned": len(out), "total": total}


def _vessel(e):
    """La forma de `vessel` cambia entre tipos de evento. Se normaliza aquí."""
    v = e.get("vessel") or {}
    return {
        "gfw_vessel_id": v.get("id"),
        "name": (v.get("name") or "").strip() or None,
        "mmsi": v.get("ssvid"),
        "flag": v.get("flag"),
        "ship_type": v.get("type") or v.get("vesselType"),
    }


def to_geojson(by_type):
    """{tipo: [entries]} -> FeatureCollection de puntos."""
    feats = []
    for etype, entries in by_type.items():
        for e in entries:
            pos = e.get("position") or {}
            lon, lat = pos.get("lon"), pos.get("lat")
            if lon is None or lat is None:
                continue
            p = {"source": "gfw", "event_type": etype, "event_id": e.get("id"),
                 "start": e.get("start"), "end": e.get("end")}
            p.update(_vessel(e))
            # Cada tipo trae su bloque propio con el detalle que lo justifica.
            for k in ("gap", "encounter", "loitering", "port_visit", "fishing"):
                if isinstance(e.get(k), dict):
                    p["detail"] = {kk: vv for kk, vv in e[k].items()
                                   if not isinstance(vv, (dict, list))}
            p["ts_ms"] = _ms(e.get("start"))
            p["end_ms"] = _ms(e.get("end"))
            if p["ts_ms"] and p["end_ms"]:
                p["duration_h"] = round((p["end_ms"] - p["ts_ms"]) / 3600000.0, 2)
            feats.append({"type": "Feature", "properties": p,
                          "geometry": {"type": "Point", "coordinates": [lon, lat]}})
    feats.sort(key=lambda f: f["properties"].get("ts_ms") or 0)
    return {"type": "FeatureCollection", "features": feats}


def _ms(iso):
    if not iso:
        return None
    import datetime as dt
    try:
        s = iso.replace("Z", "+00:00")
        return int(dt.datetime.fromisoformat(s).timestamp() * 1000)
    except ValueError:
        return None


# --------------------------------------------------------------- rejillas
def _feature_collection(bbox):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {},
         "geometry": _bbox_geometry(bbox)}]}


def report(kind, bbox, start, end, spatial="LOW", temporal="MONTHLY",
           group_by=None, filter_by=None, tok=None, refresh=False):
    """Rejilla 4wings. Devuelve (filas, stats). Cada fila es un dict del CSV."""
    import csv
    import datetime as dt
    import io
    import zipfile

    tok = tok or token()
    if not tok:
        raise RuntimeError("falta GFW_TOKEN (secrets.env o entorno)")
    if kind not in RASTERS:
        raise ValueError("dataset desconocido: %s" % kind)
    d0 = dt.date.fromisoformat(start)
    d1 = dt.date.fromisoformat(end)
    if (d1 - d0).days > 366:
        raise ValueError("4wings admite 366 dias como maximo; pedidos %d"
                         % (d1 - d0).days)

    q = [("datasets[0]", RASTERS[kind]),
         ("spatial-resolution", spatial),
         ("temporal-resolution", temporal),
         ("date-range", "%s,%s" % (start, end)),
         ("format", "CSV")]
    if group_by:
        q.append(("group-by", group_by))
    if filter_by:
        q.append(("filters[0]", filter_by))
    url = BASE + "/4wings/report?" + urlencode(q)

    raw, cached_ = net.fetch(url, body=json.dumps({"geojson": _feature_collection(bbox)}),
                             headers={"Authorization": "Bearer " + tok,
                                      "Content-Type": "application/json"},
                             refresh=refresh, timeout=300, ext="zip")
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise RuntimeError("el ZIP de 4wings no trae CSV: %s" % zf.namelist())
        with zf.open(names[0]) as fh:
            rows = list(csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig")))
    st = {"rows": len(rows), "from_cache": cached_, "dataset": RASTERS[kind],
          "spatial": spatial, "temporal": temporal,
          # El encabezado se guarda literal: los nombres de columna de GFW no
          # estan documentados de forma estable y asi el manifest dice que
          # llego de verdad en vez de obligar a abrir el ZIP.
          "columns": list(rows[0].keys()) if rows else []}
    LOG.info("gfw raster %-8s %5d celdas  cols=%s", kind, len(rows), st["columns"])
    return rows, st


def _col(cols, *wanted):
    """Primera columna cuyo nombre normalizado contenga alguno de `wanted`."""
    norm = {c: c.lower().replace("_", " ").strip() for c in cols}
    for w in wanted:
        for c, n in norm.items():
            if w in n:
                return c
    return None


def grid_to_geojson(rows, spatial="LOW"):
    """Filas del CSV -> celdas cuadradas con su valor.

    Los nombres de columna de 4wings no estan publicados de forma estable, asi
    que se detectan por contenido en vez de fijarlos: lat/lon por nombre, y el
    valor como la primera columna numerica que hable de horas o detecciones.
    Si no se reconoce nada se devuelve vacio y el motivo, que es mejor que
    inventarse una capa.
    """
    if not rows:
        return {"type": "FeatureCollection", "features": []}, "sin filas"
    cols = list(rows[0].keys())
    c_lat = _col(cols, "lat")
    c_lon = _col(cols, "lon")
    if not c_lat or not c_lon:
        return ({"type": "FeatureCollection", "features": []},
                "sin columnas lat/lon en %s" % cols)
    c_val = _col(cols, "hours", "detections", "presence", "count", "value")
    half = CELL_DEG.get(spatial, 0.1) / 2.0
    feats = []
    for r in rows:
        try:
            lat, lon = float(r[c_lat]), float(r[c_lon])
        except (TypeError, ValueError):
            continue
        try:
            val = float(r.get(c_val)) if c_val else 1.0
        except (TypeError, ValueError):
            val = 0.0
        props = {"value": val, "value_field": c_val}
        for k, v in r.items():
            if k not in (c_lat, c_lon) and v not in (None, ""):
                props[k] = v
        feats.append({"type": "Feature", "properties": props, "geometry": {
            "type": "Polygon", "coordinates": [[
                [lon - half, lat - half], [lon + half, lat - half],
                [lon + half, lat + half], [lon - half, lat + half],
                [lon - half, lat - half]]]}})
    return ({"type": "FeatureCollection", "features": feats},
            "valor = %s, celda %.2f grados" % (c_val or "recuento", half * 2))


def collect(bbox, start, end, types=DEFAULT_EVENTS, refresh=False):
    """Todos los tipos pedidos. Un fallo por tipo no tumba el resto."""
    by_type, st = {}, {"types": {}, "errors": {}}
    for etype in types:
        try:
            entries, s = fetch_events(etype, bbox, start, end, refresh=refresh)
            by_type[etype] = entries
            st["types"][etype] = s
        except Exception as exc:                      # noqa: BLE001
            st["errors"][etype] = str(exc)[:200]
            LOG.warning("gfw %s falló: %s", etype, str(exc)[:160])
    return to_geojson(by_type), st


def _selftest():
    """`python3 -m custody.gfw` — comprueba el token con una consulta mínima.

    Pide 90 días de huecos de AIS en el golfo. Devuelve 0 si el token sirve,
    1 si no. No escribe nada en el visor.
    """
    import datetime as dt
    import logging as _lg
    _lg.basicConfig(level=_lg.INFO, format="%(levelname)s %(message)s")
    tok = token()
    if not tok:
        print("GFW_TOKEN no está. Ponlo en secrets.env:\n"
              "    GFW_TOKEN=<el JWT de globalfishingwatch.org/our-apis/tokens>")
        return 1
    print("token encontrado (%d caracteres, empieza por %s…)" % (len(tok), tok[:8]))
    end = dt.datetime.now(dt.timezone.utc).date()
    start = end - dt.timedelta(days=90)
    aoi = (22.0, 59.0, 30.5, 60.9)
    try:
        entries, st = fetch_events("GAP", aoi, start.isoformat(), end.isoformat(),
                                   refresh=True, max_pages=1)
    except Exception as exc:                          # noqa: BLE001
        msg = str(exc)
        print("FALLO: %s" % msg[:300])
        if "401" in msg:
            print("  401 = el token no vale o caducó. Genera otro.")
        elif "403" in msg:
            print("  403 = el token es válido pero sin permiso sobre ese dataset.")
        return 1
    print("OK · %d eventos GAP en el golfo entre %s y %s (total declarado %s)"
          % (st["returned"], start, end, st.get("total")))
    for e in entries[:3]:
        v = _vessel(e)
        print("   %s  %s  MMSI %s  %s" % (e.get("start"), (v["name"] or "sin nombre")[:22],
                                          v["mmsi"], v["flag"]))
    return 0


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(_selftest())
