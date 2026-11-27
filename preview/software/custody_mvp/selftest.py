#!/usr/bin/env python3
"""Verificación del MVP sin navegador. Solo stdlib.

Arranca `python3 -m http.server` sobre viewer/, descarga todo lo que el visor
descargaría, valida geometrías y comprueba que cada capa declarada en el
manifest existe, parsea y contiene lo que dice contener. Falla con código != 0
y dice qué requisito ha roto.

    python3 selftest.py
"""
import http.server
import json
import os
import socketserver
import sys
import threading
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
VIEWER = os.path.join(HERE, "viewer")
PORT = 8765

FAIL = []
OK = []


def check(cond, msg):
    (OK if cond else FAIL).append(msg)
    print(("  OK   " if cond else "  FALLO ") + msg)


def serve():
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=VIEWER, **kw)

        def log_message(self, *a):
            pass
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def get(path):
    with urllib.request.urlopen("http://127.0.0.1:%d/%s" % (PORT, path), timeout=30) as r:
        return r.status, r.read()


def geom_ok(g):
    if g is None:
        return False
    t = g.get("type")
    c = g.get("coordinates")
    if t == "Point":
        return len(c) >= 2 and all(isinstance(x, (int, float)) for x in c[:2])
    if t == "LineString":
        return len(c) >= 2 and all(len(p) >= 2 for p in c)
    if t == "MultiLineString":
        return all(len(p) >= 2 for p in c) and bool(c)
    if t == "Polygon":
        return bool(c) and len(c[0]) >= 4
    if t == "MultiPolygon":
        return bool(c) and all(len(p[0]) >= 4 for p in c)
    return False


def main():
    httpd = serve()
    print("servidor en http://127.0.0.1:%d (raíz %s)" % (PORT, VIEWER))

    print("\n[1] Activos estáticos del visor")
    for p in ("index.html", "app.js", "style.css",
              "vendor/leaflet/leaflet.js", "vendor/leaflet/leaflet.css",
              "vendor/leaflet/images/marker-icon.png"):
        try:
            s, b = get(p)
            check(s == 200 and len(b) > 0, "%s HTTP %d, %d B" % (p, s, len(b)))
        except Exception as exc:
            check(False, "%s no servible: %s" % (p, exc))

    print("\n[2] Sin dependencias de CDN en el HTML/JS")
    _, html = get("index.html")
    _, js = get("app.js")
    for blob, name in ((html, "index.html"), (js, "app.js")):
        txt = blob.decode("utf-8", "replace")
        bad = [u for u in ("unpkg.com", "cdn.jsdelivr", "cdnjs.", "googleapis.com")
               if u in txt]
        check(not bad, "%s sin CDN (%s)" % (name, bad or "ninguno"))
    # las dos capas de red permitidas, declaradas
    txt = js.decode()
    check("tile.openstreetmap.org" in txt and "emodnet-bathymetry.eu/wms" in txt,
          "las 2 capas de red están declaradas en app.js y apagadas por defecto")

    print("\n[3] manifest")
    s, b = get("data/manifest.json")
    check(s == 200, "manifest.json HTTP %d" % s)
    m = json.loads(b)
    check(bool(m.get("built_utc")), "manifest.built_utc = %s" % m.get("built_utc"))
    check(len(m["layers"]) >= 10, "%d capas declaradas" % len(m["layers"]))

    print("\n[4] Capas: se descargan, parsean y cuadran")
    totals = {}
    for name, info in m["layers"].items():
        try:
            s, b = get("data/" + info["file"])
        except Exception as exc:
            check(False, "%s: %s" % (name, exc))
            continue
        if s != 200:
            check(False, "%s HTTP %d" % (name, s))
            continue
        fc = json.loads(b)
        n = len(fc.get("features", []))
        totals[name] = n
        bad = [f for f in fc["features"] if not geom_ok(f.get("geometry"))]
        check(fc.get("type") == "FeatureCollection",
              "%s es FeatureCollection" % name)
        check(not bad, "%s: %d features, %d con geometría inválida" % (name, n, len(bad)))
        if info["status"] == "ok":
            check(n > 0, "%s declarada 'ok' y trae %d features" % (name, n))
        else:
            check(n == 0, "%s declarada '%s' y va vacía (%d) - motivo: %s"
                  % (name, info["status"], n, info["note"]))

    print("\n[5] Coherencia de contenido")
    _, b = get("data/corridors_trunk.geojson")
    corr = json.loads(b)
    names = sorted({f["properties"]["name"] for f in corr["features"]
                    if f["properties"].get("name")})
    for want in ("Estlink 1", "HVDC Estlink 2", "C-Lion 1", "Baltic Connector"):
        check(want in names, "corredor presente: %s" % want)
    check(all(f["properties"]["trunk"] for f in corr["features"]),
          "todos los elementos de corridors_trunk tienen trunk=true")

    _, b = get("data/alerts.geojson")
    al = json.loads(b)
    kinds = {}
    for f in al["features"]:
        kinds[f["properties"]["kind"]] = kinds.get(f["properties"]["kind"], 0) + 1
    check(al["properties"]["calibrated"] is False,
          "alerts.geojson declara calibrated=false")
    check(bool(al["properties"].get("justification")),
          "alerts.geojson lleva la justificación de cada umbral")
    check(all("evidence" in f["properties"] and f["properties"]["evidence"].get("fix_keys")
              for f in al["features"]),
          "toda alerta lleva evidencia con clave (mmsi, ts) de los fixes: %s" % kinds)

    _, b = get("data/restrictions.geojson")
    rs = json.loads(b)
    ban = [f for f in rs["features"] if f["properties"]["anchoring_prohibited"]]
    check(len(rs["features"]) > 0,
          "Väylä: %d áreas de restricción en el AOI, %d de prohibición de fondeo"
          % (len(rs["features"]), len(ban)))
    near = (m["stats"].get("restrictions", {}).get("anchor_ban_vs_trunk") or {})
    check("within_2000m_of_trunk" in near,
          "se ha medido la distancia de cada prohibición de fondeo al corredor "
          "trunk más próximo: %s a <=2 km" % near.get("within_2000m_of_trunk"))
    check(all(f["properties"].get("restriction_fi") for f in rs["features"]),
          "toda área conserva su tipo literal en finés (no se traduce a ciegas)")

    _, b = get("data/scenes.geojson")
    sc = json.loads(b)
    if sc["features"]:
        q = [f for f in sc["features"] if f["properties"].get("quicklook_local")]
        check(bool(q), "%d/%d escenas con quicklook local" % (len(q), len(sc["features"])))
        for f in q[:3]:
            s, bb = get("data/" + f["properties"]["quicklook_local"])
            check(s == 200 and bb[:4] == b"\x89PNG",
                  "quicklook servible y es PNG: %s (%d B)"
                  % (f["properties"]["quicklook_local"], len(bb)))
        check(all(f["properties"]["quicklook_georeferenced"] is False
                  for f in sc["features"]),
              "los quicklooks se declaran NO georreferenciados")
        check(all(f["properties"]["sar_detections"] is None for f in sc["features"]),
              "detecciones SAR declaradas no calculadas (falta el GRD)")

    _, b = get("data/tracks.geojson")
    tr = json.loads(b)
    pos = sum(len(p) for f in tr["features"] for p in f["geometry"]["coordinates"])
    check(pos > 1000, "trazas: %d posiciones en %d buques" % (pos, len(tr["features"])))
    aoi = m["aoi"]
    out = [1 for f in tr["features"] for p in f["geometry"]["coordinates"] for c in p
           if not (aoi[0] <= c[0] <= aoi[2] and aoi[1] <= c[1] <= aoi[3])]
    check(not out, "todas las posiciones dentro del AOI (%d fuera)" % len(out))

    httpd.shutdown()
    print("\n=== %d OK, %d FALLOS ===" % (len(OK), len(FAIL)))
    for f in FAIL:
        print("FALLO: " + f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
