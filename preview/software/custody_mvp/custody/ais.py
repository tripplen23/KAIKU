"""Carga del almacén de `software/ais_recorder` y construcción de trazas.

Contrato de entrada: NDJSON.gz multimiembro, campos literales de la API de
Fintraffic Digitraffic. Ver software/ais_recorder/README.md.

Fuente: Fintraffic / digitraffic.fi, licencia CC 4.0 BY.

Centinelas AIS que NO son valores físicos y aquí se convierten a None
(el grabador los persiste tal cual por REQ-AIS-005; filtrarlos es trabajo de
este consumidor):
    sog = 102.3  -> no disponible
    cog = 360.0  -> no disponible
    heading = 511 -> no disponible
    rot = -128   -> no disponible
"""
import glob
import gzip
import math
import json
import os

SOG_NA = 102.3
COG_NA = 360.0
HDG_NA = 511
ROT_NA = -128

NAVSTAT = {0: "under way using engine", 1: "at anchor", 2: "not under command",
           3: "restricted manoeuvrability", 4: "constrained by draught",
           5: "moored", 6: "aground", 7: "engaged in fishing",
           8: "under way sailing", 11: "towing astern",
           12: "pushing ahead", 14: "AIS-SART", 15: "undefined"}


def _iter_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def _roots(root):
    """Acepta un directorio o varios. La grabadora ha vivido en dos sitios y
    leer solo uno es como se pierden horas de observacion primaria sin un
    solo error en el log: ver paths.records()."""
    if root is None:
        return []
    if isinstance(root, (str, bytes, os.PathLike)):
        return [root]
    return list(root)


def _files(root, stream):
    """Los ficheros de un stream, de TODOS los almacenes, ordenados por el
    nombre del fichero y no por la ruta: asi dos almacenes con el mismo dia
    salen juntos y el deduplicado por (mmsi, ts) hace su trabajo."""
    out = []
    for r in _roots(root):
        out.extend(glob.glob(os.path.join(r, "raw", stream, "*", "*", "*.ndjson.gz")))
    return sorted(out, key=lambda p: (os.path.basename(p), p))


def load_fixes(root, bbox=None, include_mqtt=False):
    """Devuelve (fixes, stats). fixes = lista de dicts normalizados.

    `root` es un directorio O una lista de ellos (paths.records()). Entre
    almacenes se deduplica con la misma clave (mmsi, ts) que dentro de uno:
    el mismo casco oido en el mismo instante es un fix, no dos.

    bbox = (minlon, minlat, maxlon, maxlat). El filtro geográfico es de
    consulta, nunca de grabación.
    """
    seen = set()
    out = []
    st = {"files": 0, "records_read": 0, "duplicates": 0, "outside_bbox": 0,
          "streams": {}}

    def push(rec, mmsi, ts, source, src_file=None):
        lon, lat = rec.get("lon"), rec.get("lat")
        if lon is None or lat is None:
            return
        if bbox and not (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]):
            st["outside_bbox"] += 1
            return
        key = (mmsi, ts)
        if key in seen:
            st["duplicates"] += 1
            return
        seen.add(key)
        sog = rec.get("sog")
        cog = rec.get("cog")
        hdg = rec.get("heading")
        rot = rec.get("rot")
        out.append({
            "mmsi": mmsi, "ts": ts, "lon": lon, "lat": lat,
            "sog": None if sog is None or abs(sog - SOG_NA) < 1e-6 else sog,
            "cog": None if cog is None or abs(cog - COG_NA) < 1e-6 else cog,
            "heading": None if hdg is None or hdg == HDG_NA else hdg,
            "rot": None if rot is None or rot == ROT_NA else rot,
            "navStat": rec.get("navStat"),
            "posAcc": rec.get("posAcc"),
            "src": source,
            "src_file": src_file,
        })

    for path in _files(root, "locations"):
        st["files"] += 1
        n = 0
        for rec in _iter_gz(path):
            n += 1
            push(rec, rec["mmsi"], rec["timestampExternal"], "rest",
                 os.path.basename(path))
        st["records_read"] += n
        st["streams"]["locations"] = st["streams"].get("locations", 0) + n

    if include_mqtt:
        for path in _files(root, "mqtt_locations"):
            st["files"] += 1
            n = 0
            for rec in _iter_gz(path):
                n += 1
                # `time` es epoch en segundos en el stream MQTT, no ms.
                push(rec, rec["mmsi"], int(rec["time"]) * 1000, "mqtt",
                     os.path.basename(path))
            st["records_read"] += n
            st["streams"]["mqtt_locations"] = st["streams"].get("mqtt_locations", 0) + n

    out.sort(key=lambda r: (r["mmsi"], r["ts"]))
    st["fixes_kept"] = len(out)
    return out, st


def load_vessels(root):
    """mmsi -> metadatos estáticos (el más reciente). `name` viene con relleno."""
    best = {}
    for path in _files(root, "vessels"):
        for rec in _iter_gz(path):
            m = rec.get("mmsi")
            if m is None:
                continue
            prev = best.get(m)
            if prev is None or rec.get("timestamp", 0) >= prev.get("timestamp", 0):
                best[m] = rec
    for m, v in best.items():
        for k in ("name", "callSign", "destination"):
            if isinstance(v.get(k), str):
                v[k] = v[k].strip()
        if v.get("draught") is not None:
            v["draught_m"] = v["draught"] / 10.0   # AIS: decímetros
    return best


def load_polls(root):
    """Ventanas en las que el grabador estuvo realmente escuchando.

    Trampa documentada en ais_recorder/README.md: un hueco en los datos no es
    un hueco en el AIS. Sin esto, R-B/IND-04 genera alertas para todos los
    buques a la vez cada vez que el grabador estuvo parado.
    """
    polls = []
    for path in _files(root, "polllog"):
        for rec in _iter_gz(path):
            if rec.get("stream") == "locations":
                polls.append(rec)
    polls.sort(key=lambda r: r["rx_ms"])
    return polls


def coverage_windows(polls, max_gap_ms=300_000):
    """Intervalos [t0, t1] de polling continuo sobre /locations.

    Un salto > max_gap_ms entre polls correctos abre una ventana nueva.
    """
    wins = []
    cur = None
    for p in polls:
        if p.get("http") not in (200, 304):
            continue
        t = p["rx_ms"]
        if cur is None:
            cur = [t, t]
        elif t - cur[1] > max_gap_ms:
            wins.append(tuple(cur))
            cur = [t, t]
        else:
            cur[1] = t
    if cur:
        wins.append(tuple(cur))
    return wins


def build_tracks(fixes, min_fixes=2):
    """mmsi -> lista de fixes ordenada por ts."""
    tracks = {}
    for f in fixes:
        tracks.setdefault(f["mmsi"], []).append(f)
    return {m: v for m, v in tracks.items() if len(v) >= min_fixes}


def tracks_geojson(tracks, vessels=None, gap_ms=None, since=None):
    """Trazas como MultiLineString partidas en los saltos de cobertura.

    UNA SOLA IMPLEMENTACION, usada por el build Y por el motor en vivo. Antes
    vivia dentro de build.py; el visor fusiona las dos en el mismo HIST, asi
    que si cada una partiera los segmentos con otro criterio la misma derrota
    cambiaria de forma al cruzar la frontera del build.

    Las marcas de tiempo por vertice viajan en `properties` porque GeoJSON no
    admite una cuarta ordenada portable.

    `since` recorta por la izquierda: el motor en vivo solo necesita lo que el
    build todavia no tiene.
    """
    vessels = vessels or {}
    if gap_ms is None:
        gap_ms = 1800 * 1000
    feats, n_seg, n_pts = [], 0, 0
    for mmsi, tr in tracks.items():
        if since:
            tr = [f for f in tr if f["ts"] >= since]
            if len(tr) < 2:
                continue
        parts, cur = [], [tr[0]]
        for a, b in zip(tr, tr[1:]):
            if b["ts"] - a["ts"] > gap_ms:
                parts.append(cur)
                cur = [b]
            else:
                cur.append(b)
        parts.append(cur)
        parts = [p for p in parts if len(p) >= 2]
        if not parts:
            continue
        n_seg += len(parts)
        n_pts += sum(len(p) for p in parts)
        meta = vessels.get(mmsi, {})
        sogs = [f["sog"] for f in tr if f["sog"] is not None]
        feats.append({
            "type": "Feature", "id": mmsi,
            "geometry": {"type": "MultiLineString",
                         "coordinates": [[[round(f["lon"], 5), round(f["lat"], 5)]
                                          for f in p] for p in parts]},
            "properties": {"mmsi": mmsi, "name": meta.get("name") or None,
                           "ship_type": meta.get("shipType"),
                           "destination": meta.get("destination") or None,
                           "draught_m": meta.get("draught_m"),
                           "fixes": len(tr), "segments": len(parts),
                           "sog_max_kn": max(sogs) if sogs else None,
                           "sog_min_kn": min(sogs) if sogs else None,
                           "t_start_ms": tr[0]["ts"], "t_end_ms": tr[-1]["ts"],
                           "times": [[f["ts"] for f in p] for p in parts],
                           "sogs": [[f["sog"] for f in p] for p in parts],
                           "hdgs": [[f["heading"] for f in p] for p in parts]}})
    return ({"type": "FeatureCollection", "features": feats},
            {"features": len(feats), "segments": n_seg, "vertices": n_pts})


def coverage_cells(fixes, step=0.5):
    """Dónde hemos visto AIS de verdad, en celdas de `step` grados.

    Al ampliar el AOI del golfo al Báltico entero, media superficie del mapa
    pasa a ser agua donde los receptores de Fintraffic NO llegan. Un mapa con
    el sur vacío se lee como «ahí no pasa nada», que es falso: lo que pasa es
    que no lo vemos. Esta rejilla es la diferencia entre las dos frases, y el
    visor la pinta para que nadie tenga que fiarse de recordarla.

    Medido el 2026-11-10: la cobertura muere en torno a 57°N.
    """
    cells = {}
    for f in fixes:
        key = (int(math.floor(f["lon"] / step)), int(math.floor(f["lat"] / step)))
        cells[key] = cells.get(key, 0) + 1
    feats = []
    for (i, j), n in sorted(cells.items()):
        lon0, lat0 = i * step, j * step
        feats.append({"type": "Feature", "properties": {"fixes": n},
                      "geometry": {"type": "Polygon", "coordinates": [[
                          [lon0, lat0], [lon0 + step, lat0],
                          [lon0 + step, lat0 + step], [lon0, lat0 + step],
                          [lon0, lat0]]]}})
    return ({"type": "FeatureCollection", "features": feats},
            {"cells": len(feats), "step_deg": step,
             "fixes": sum(cells.values())})
