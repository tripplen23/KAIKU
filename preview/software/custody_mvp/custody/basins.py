"""Subcuencas del Baltico, de HELCOM y no inventadas.

La primera version dibujaba seis rectangulos a mano. Funcionaban para
encuadrar, pero no teselaban el mar: medido sobre la rejilla de profundidad,
el 9,4 % del mar del AOI no caia en ninguna caja y 2.218 celdas caian en dos.
Un filtro que esconde dato por un limite inventado no es un filtro, es una
fuente de error.

Esto usa la division REAL: `HELCOM subbasins level 2`, 17 unidades, que es la
que HELCOM emplea en sus evaluaciones HOLAS y la que citan los informes del
Baltico. Misma casa de la que ya tomamos vertidos de municion y planificacion
espacial, asi que el visor no suma una fuente nueva.

    https://maps.helcom.fi/arcgis/rest/services/MADS/Monitoring/MapServer/107

HELCOM agrupa esas 17 en 7 cuencas mayores para los techos de nutrientes del
Plan de Accion (capa 228 del mismo servidor: BOB, BOS, GUF, GUR, BAP, DS,
KAT). Esa agrupacion se replica abajo para que la interfaz no obligue a
elegir entre diecisiete botones.

EL TAMANO ES EL PROBLEMA. El servicio devuelve 2,9 millones de vertices y
115 MB: eso no entra en un visor. Se simplifica con Douglas-Peucker y se
tiran los anillos minusculos (islotes), que no cambian a que cuenca pertenece
un buque pero si multiplican el coste de cada consulta punto-en-poligono.
"""
import json
import logging
import math

from custody import net

LOG = logging.getLogger("custody.basins")

URL = ("https://maps.helcom.fi/arcgis/rest/services/MADS/Monitoring/"
       "MapServer/107/query")

# 17 -> 7. La agrupacion es la de HELCOM para los techos de nutrientes del
# Plan de Accion (capa 228). Se guarda el codigo para poder citarlo.
MAJOR = {
    "SEA-001": ("KAT", "Kattegat"),
    "SEA-002": ("DS", "Danish Straits"),
    "SEA-003": ("DS", "Danish Straits"),
    "SEA-004": ("DS", "Danish Straits"),
    "SEA-005": ("DS", "Danish Straits"),
    "SEA-006": ("BAP", "Baltic Proper"),
    "SEA-007": ("BAP", "Baltic Proper"),
    "SEA-008": ("BAP", "Baltic Proper"),
    "SEA-009": ("BAP", "Baltic Proper"),
    "SEA-010": ("BAP", "Baltic Proper"),
    "SEA-011": ("GUR", "Gulf of Riga"),
    "SEA-012": ("BAP", "Baltic Proper"),
    "SEA-013": ("GUF", "Gulf of Finland"),
    "SEA-014": ("BOS", "Bothnian Sea"),
    "SEA-015": ("BOS", "Bothnian Sea"),
    "SEA-016": ("BOB", "Bothnian Bay"),
    "SEA-017": ("BOB", "Bothnian Bay"),
}

MAJOR_ORDER = ["KAT", "DS", "BAP", "GUR", "GUF", "BOS", "BOB"]


def _perp(p, a, b):
    """Distancia perpendicular de p al segmento a-b, en grados."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == 0.0 and dy == 0.0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def simplify(pts, tol):
    """Douglas-Peucker iterativo. Recursivo desborda la pila con 500k puntos."""
    if len(pts) < 3:
        return pts[:]
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i0, i1 = stack.pop()
        if i1 <= i0 + 1:
            continue
        worst, wi = -1.0, i0
        for k in range(i0 + 1, i1):
            d = _perp(pts[k], pts[i0], pts[i1])
            if d > worst:
                worst, wi = d, k
        if worst > tol:
            keep[wi] = True
            stack.append((i0, wi))
            stack.append((wi, i1))
    return [p for p, k in zip(pts, keep) if k]


def _ring_area(r):
    """Area con signo, en grados cuadrados. Sirve para ordenar y para tirar."""
    a = 0.0
    for i in range(len(r) - 1):
        a += r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1]
    return a / 2.0


def fetch(tol=0.004, min_ring_deg2=2e-4, refresh=False):
    """Devuelve (geojson, stats). tol en grados; 0,004 son unos 250 m."""
    url = (URL + "?where=1%3D1&outFields=level_2,HELCOM_ID,area_new_k"
           "&returnGeometry=true&outSR=4326&f=json")
    raw, cached = net.fetch(url, refresh=refresh, ext="json", timeout=600)
    d = json.loads(raw.decode("utf-8"))
    if d.get("error"):
        raise RuntimeError("HELCOM: %s" % d["error"])

    feats, v_in, v_out, dropped = [], 0, 0, 0
    for f in d.get("features", []):
        a = f["attributes"]
        hid = a.get("HELCOM_ID")
        rings_out = []
        for r in f["geometry"]["rings"]:
            v_in += len(r)
            # Islotes: no cambian a que cuenca pertenece un punto del mar y
            # cuestan lo mismo que el contorno principal en cada consulta.
            if abs(_ring_area(r)) < min_ring_deg2:
                dropped += 1
                continue
            s = simplify(r, tol)
            if len(s) < 4:
                dropped += 1
                continue
            if s[0] != s[-1]:
                s.append(s[0])
            rings_out.append([[round(p[0], 5), round(p[1], 5)] for p in s])
            v_out += len(s)
        if not rings_out:
            continue
        rings_out.sort(key=lambda r: -abs(_ring_area(r)))
        xs = [p[0] for r in rings_out for p in r]
        ys = [p[1] for r in rings_out for p in r]
        maj = MAJOR.get(hid, ("OTHER", "Other"))
        feats.append({
            "type": "Feature",
            "properties": {
                "helcom_id": hid, "name": a.get("level_2"),
                "major": maj[0], "major_name": maj[1],
                "area_km2": a.get("area_new_k"),
                "bbox": [min(xs), min(ys), max(xs), max(ys)],
            },
            "geometry": {"type": "Polygon", "coordinates": rings_out},
        })

    feats.sort(key=lambda f: (MAJOR_ORDER.index(f["properties"]["major"])
                              if f["properties"]["major"] in MAJOR_ORDER else 99,
                              -(f["properties"]["area_km2"] or 0)))
    gj = {"type": "FeatureCollection",
          "attribution": "HELCOM subbasins level 2 (HOLAS assessment units)",
          "source": URL, "simplify_deg": tol, "features": feats}
    return gj, {"from_cache": cached, "basins": len(feats),
                "vertices_in": v_in, "vertices_out": v_out,
                "rings_dropped": dropped}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    gj, st = fetch(tol=float(sys.argv[2]) if len(sys.argv) > 2 else 0.004)
    with open(sys.argv[1], "w") as fh:
        json.dump(gj, fh, separators=(",", ":"))
    import os
    print("%s  %d subcuencas · %d -> %d vertices (%.1f%%) · %d anillos fuera · %.0f kB"
          % (sys.argv[1], st["basins"], st["vertices_in"], st["vertices_out"],
             100.0 * st["vertices_out"] / st["vertices_in"], st["rings_dropped"],
             os.path.getsize(sys.argv[1]) / 1024.0))
    for f in gj["features"]:
        p = f["properties"]
        print("   %-8s %-26s %-16s %5.0f km2 %5d vert"
              % (p["helcom_id"], p["name"], p["major_name"], p["area_km2"] or 0,
                 sum(len(r) for r in f["geometry"]["coordinates"])))
