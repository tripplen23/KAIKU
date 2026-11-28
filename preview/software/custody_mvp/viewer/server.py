#!/usr/bin/env python3
"""Servidor del visor con caché de teselas en disco. Solo stdlib.

    python3 server.py [puerto]

POR QUE EXISTE
--------------
`python3 -m http.server` tenía dos problemas que se notaban al hacer zoom:

1. ES DE UN SOLO HILO. Con dos capas de imagen y seis escenas cada una, el
   navegador abre decenas de peticiones en paralelo y el servidor las
   serializa. El mapa se arrastra aunque la red vaya bien.
2. NO CACHEA NADA. Cada zoom volvía a pedir a Planetary Computer las mismas
   teselas de las mismas escenas. Un píxel de Sentinel-2 de una fecha pasada
   no cambia nunca: volver a bajarlo es trabajo tirado.

Este servidor es multihilo y añade un proxy con caché en disco.

QUE SE CACHEA Y DURANTE CUANTO
------------------------------
  /cache/tile/{z}/{x}/{y}?tpl=<plantilla>   PERMANENTE. Los píxeles de una
      escena ya adquirida son inmutables. La plantilla de Planetary Computer
      no lleva token: verificado el 2026-11-10, es
      .../item/tiles/WebMercatorQuad/{z}/{x}/{y}@1x?collection=..&item=..
      Si algún día llevara firma, se normaliza en `_norm` antes de hashear.
  /cache/meta?u=<url>                       PERMANENTE. tilejson por escena.
  /cache/stac  (POST)                       TTL 6 h. El catálogo sí cambia:
      aparecen escenas nuevas. Seis horas es menos que la revisita de
      Sentinel-1 sobre el golfo.

  /cache/stats  (GET)     cuántos ficheros y cuántos bytes, por tipo
  /cache/purge  (POST)    vacía la caché

LIMITES
-------
No hay tope de tamaño automático: una caché que se borra sola a mitad de una
demo es peor que una caché grande. `./serve.sh cache` dice cuánto ocupa y
`./serve.sh purge` la vacía.

La caché NO se versiona (está en .gitignore) y no contiene nada personal: son
teselas públicas de Copernicus servidas por Microsoft sin autenticación.
"""
import gzip
import hashlib
import io
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
# El detector vive en custody/, junto al resto del procesado.
sys.path.insert(0, os.path.dirname(HERE))
# Misma config que el build: una sola fuente de verdad para las rutas.
try:
    sys.path.insert(0, os.path.dirname(HERE))
    from custody import paths as _paths
    CACHE = _paths.cache("tiles")
    DATA = _paths.data()
except Exception:
    CACHE = os.path.join(os.path.dirname(HERE), "cache", "tiles")
    DATA = os.path.join(HERE, "data")
STAC_TTL = 6 * 3600
UA = "custody-mvp/0.1 (research prototype)"
# Hosts a los que este proxy acepta salir. Un proxy abierto en localhost es
# un pivote hacia la red local; la lista blanca lo cierra.
# Wikimedia entra aquí por una razón de producto, no de velocidad: si el
# navegador pidiera la foto directamente, cada clic en un buque le diría a
# Wikimedia qué barco está mirando el operador. Pasando por el proxy la
# petición sale una vez, se queda en disco y las siguientes son locales.
ALLOWED = ("planetarycomputer.microsoft.com",
           "commons.wikimedia.org", "upload.wikimedia.org",
           # La leyenda del WMS batimetrico: se pide una vez y se cachea.
           "ows.emodnet-bathymetry.eu",
           # HELCOM: subcuencas y linea de costa. La costa se pide por
           # recuadro mientras se mueve el mapa, asi que la cache de disco es
           # lo que hace que la segunda vuelta sea gratis.
           "maps.helcom.fi",
           # Copernicus Marine: corriente, ola y hielo del Baltico. El WMTS no
           # pide credenciales; son teselas, asi que la cache de disco las
           # convierte en gratis a la segunda vista.
           "wmts.marine.copernicus.eu",
           # FMI: viento HARMONIE y ola WAM. Abierto, sin clave, CC BY 4.0.
           # Es fuente ORIGINAL de sus modelos, no un proxy de Copernicus.
           "opendata.fmi.fi",
           # EMODnet Human Activities: densidad de trafico y la agregacion
           # oficial de cables. Las teselas WMS van directas --- Leaflet las
           # pide por recuadro, no por {z}/{x}/{y}--- pero la leyenda pasa por
           # aqui para que se pida una vez y se quede en disco.
           "ows.emodnet-humanactivities.eu")

COVERAGE_TTL_S = 20
SRC_TTL_S = 120
_SRC = {"raw": None, "at": 0}

# El motor de alertas en vivo. Se arranca perezosamente en el primer uso y
# vive en un hilo propio: si el almacen no esta o el contexto no carga, el
# visor sigue sirviendo el build y lo dice, en vez de no arrancar.
_ENGINE = {"obj": None, "thread": None, "err": None}


def _sources(eng):
    """De donde salieron los fixes de este ciclo, en una linea."""
    own = eng.stats.get("fixes_own") or 0
    hub = eng.stats.get("fixes_aishub") or 0
    ah = eng.stats.get("aishub") or {}
    out = "Fintraffic %d" % own
    if hub:
        out += " + AISHub %d" % hub
    elif ah.get("reason") == "no_key":
        out += " · AISHub idle (needs a key)"
    elif ah.get("reason"):
        out += " · AISHub %s" % ah["reason"]
    return out


def _engine():
    if _ENGINE["obj"] is not None or _ENGINE["err"]:
        return _ENGINE["obj"]
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from custody import live as _live
        eng = _live.Engine()
        t = threading.Thread(target=eng.run_forever, daemon=True)
        t.start()
        _ENGINE["obj"], _ENGINE["thread"] = eng, t
    except Exception as exc:
        _ENGINE["err"] = str(exc)
    return _ENGINE["obj"]

_COV = {"raw": None, "at": 0}

_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
STATS = {"hit": 0, "miss": 0, "error": 0}


def _lock_for(key):
    """Un candado por clave: dos teselas iguales pedidas a la vez se bajan una."""
    with _LOCKS_GUARD:
        if key not in _LOCKS:
            _LOCKS[key] = threading.Lock()
        return _LOCKS[key]


def _norm(url):
    """URL canónica para hashear: sin parámetros de firma ni volátiles."""
    u = urllib.parse.urlsplit(url)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True)
         if not k.lower().startswith(("sig", "se", "sp", "sv", "st", "sr", "skoid",
                                      "sktid", "skt", "ske", "sks", "skv"))]
    q.sort()
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path,
                                    urllib.parse.urlencode(q), ""))


def _allowed(url):
    return urllib.parse.urlsplit(url).hostname in ALLOWED


def _path_for(kind, key, ext):
    d = os.path.join(CACHE, kind, key[:2])
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, key + "." + ext)


def _upstream(url, body=None, ctype=None):
    hdrs = {"User-Agent": UA}
    if ctype:
        hdrs["Content-Type"] = ctype
    req = urllib.request.Request(url, data=body, headers=hdrs,
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read(), r.headers.get("Content-Type", "application/octet-stream")


def _read(path, meta):
    ct = "application/octet-stream"
    if os.path.exists(meta):
        with open(meta) as fh:
            ct = fh.read().strip() or ct
    with open(path, "rb") as fh:
        return fh.read(), ct


def cached(kind, url, ext, ttl=None, body=None, ctype=None):
    """(bytes, content_type, from_cache). Lanza si el upstream falla y no hay copia."""
    key = hashlib.sha256((_norm(url) + (body.decode("utf-8", "replace") if body else ""))
                         .encode()).hexdigest()[:32]
    path = _path_for(kind, key, ext)
    meta = path + ".ct"
    fresh = (lambda: os.path.exists(path) and
             (ttl is None or time.time() - os.path.getmtime(path) < ttl))
    if fresh():
        STATS["hit"] += 1
        raw, ct = _read(path, meta)
        return raw, ct, True
    with _lock_for(key):
        # Otro hilo pudo bajarla mientras esperábamos el candado.
        if fresh():
            STATS["hit"] += 1
            raw, ct = _read(path, meta)
            return raw, ct, True
        try:
            raw, ct = _upstream(url, body=body, ctype=ctype)
        except Exception:
            STATS["error"] += 1
            # Una copia caducada vale más que un hueco en el mapa.
            if os.path.exists(path):
                raw, ct = _read(path, meta)
                return raw, ct, True
            raise
        STATS["miss"] += 1
        tmp = path + ".part"
        with open(tmp, "wb") as fh:
            fh.write(raw)
        os.replace(tmp, path)
        with open(meta, "w") as fh:
            fh.write(ct)
        return raw, ct, False


def cache_stats():
    out = {"dir": CACHE, "bytes": 0, "files": 0, "by_kind": {}}
    for root, _d, files in os.walk(CACHE):
        kind = os.path.relpath(root, CACHE).split(os.sep)[0]
        for f in files:
            if f.endswith((".part", ".ct")):
                continue
            n = os.path.getsize(os.path.join(root, f))
            out["bytes"] += n
            out["files"] += 1
            k = out["by_kind"].setdefault(kind, {"files": 0, "bytes": 0})
            k["files"] += 1
            k["bytes"] += n
    out.update(STATS)
    return out


TILE_RE = re.compile(r"^/cache/tile/(\d+)/(\d+)/(\d+)$")


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        """Los ficheros PROPIOS del visor nunca se cachean en el navegador.

        Sin esto, cambiar un .js y recargar deja una mezcla de ficheros viejos
        y nuevos, y el sintoma es «el fallo sigue ahi» cuando en realidad el
        navegador esta ejecutando la version anterior. Paso de verdad.

        No afecta a /cache/*, que sirve teselas y recortes de satelite y SI
        debe cachearse: esos pasan por _send(), que pone su propia cabecera
        antes de llegar aqui.
        """
        if "Cache-Control" not in self._headers_buffer_names():
            self.send_header("Cache-Control", "no-cache, must-revalidate")
        SimpleHTTPRequestHandler.end_headers(self)

    def _headers_buffer_names(self):
        return b"".join(getattr(self, "_headers_buffer", []) or []).decode(
            "latin-1", "replace")

    protocol_version = "HTTP/1.1"

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    def log_message(self, fmt, *args):
        if args and "/cache/" in str(args[0]):
            return
        super().log_message(fmt, *args)

    # -------------------------------------------------------------- helpers
    def _send(self, raw, ctype, cache_header=None, code=200):
        # GZIP cuando el cliente lo acepta y la carga lo merece.
        #
        # Medido en /vessels/live, que ahora se pide en cada ciclo del motor:
        # 5,7 MB en claro, 1,2 MB comprimido. Sin esto, un visor abierto
        # mueve casi 6 MB por minuto por la interfaz de bucle local --- el
        # tiempo de serializar y escribir compite con el propio motor.
        if (len(raw) > 4096 and "gzip" in
                (self.headers.get("Accept-Encoding") or "").lower()
                and not ctype.startswith("image/")):
            buf = io.BytesIO()
            with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as fh:
                fh.write(raw)
            raw = buf.getvalue()
            self._gz = True
        else:
            self._gz = False
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if self._gz:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(raw)))
        if cache_header:
            self.send_header("X-Custody-Cache", cache_header)
            # Que el navegador tampoco vuelva a preguntar durante la sesión.
            self.send_header("Cache-Control", "public, max-age=604800")
        self.end_headers()
        self.wfile.write(raw)

    def _fail(self, code, msg):
        self._send(json.dumps({"error": msg}).encode(), "application/json", code=code)

    def translate_path(self, path):
        """`/data/...` sale de la ruta configurada, no de viewer/data.

        La salida del build vive fuera del arbol del proyecto (ver
        config/custody.toml): es reproducible, asi que no tiene por que
        sincronizarse a la nube con el codigo. El navegador sigue pidiendo
        `data/x.geojson` como siempre; la indireccion ocurre aqui.
        """
        clean = urllib.parse.urlsplit(path).path
        if clean.startswith("/data/"):
            rel = urllib.parse.unquote(clean[len("/data/"):])
            # Sin salirse del directorio de datos, venga lo que venga.
            safe = os.path.normpath(os.path.join(DATA, rel))
            if os.path.commonpath([safe, DATA]) == DATA:
                return safe
            return os.path.join(DATA, "__fuera_de_rango__")
        return SimpleHTTPRequestHandler.translate_path(self, path)

    # ------------------------------------------------------------------ GET
    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        if u.path == "/cache/stats":
            return self._send(json.dumps(cache_stats(), indent=1).encode(),
                              "application/json")
        q = urllib.parse.parse_qs(u.query)

        m = TILE_RE.match(u.path)
        if m:
            tpl = (q.get("tpl") or [""])[0]
            if not tpl:
                return self._fail(400, "falta tpl")
            z, x, y = m.groups()
            url = (tpl.replace("{z}", z).replace("{x}", x).replace("{y}", y)
                      .replace("{r}", "").replace("{s}", "a"))
            if not _allowed(url):
                return self._fail(403, "host no permitido")
            try:
                raw, ct, hit = cached("tile", url, "img")
            except Exception as exc:
                return self._fail(502, str(exc)[:200])
            return self._send(raw, ct, "HIT" if hit else "MISS")

        # Geometria vectorial por recuadro (ArcGIS REST). Igual que /cache/img
        # pero devolviendo JSON y con TTL largo: una linea de costa no cambia
        # entre sesiones, y el visor la pide trozo a trozo al navegar.
        if u.path == "/cache/geo":
            url = (q.get("u") or [""])[0]
            if not url or not _allowed(url):
                return self._fail(403, "host no permitido")
            try:
                raw, ct, hit = cached("geo", url, "json", ttl=30 * 86400)
            except Exception as exc:
                return self._fail(502, str(exc)[:200])
            return self._send(raw, ct or "application/json",
                              "HIT" if hit else "MISS")

        # ALERTAS EN TIEMPO DE EJECUCION.
        #
        # Los siete indicadores corren aqui, con el MISMO custody/indicators.py
        # del build. Calcularlas solo al compilar convertia una herramienta de
        # vigilancia en una de informes: con un build de 42 h, «que esta
        # pasando ahora» se respondia con anteayer.
        # El forzamiento en un punto, y si explica una deriva. Esto es lo
        # que convierte IND-02 de sospecha en evidencia: viento y ola
        # producen exactamente el angulo que el indicador marca.
        if u.path == "/forcing":
            try:
                lat = float((q.get("lat") or ["0"])[0])
                lon = float((q.get("lon") or ["0"])[0])
            except ValueError:
                return self._fail(400, "lat/lon")
            try:
                sys.path.insert(0, os.path.dirname(HERE))
                from custody import fmi as _fmi
                f = _fmi.forcing(lat, lon)
                out = {"lat": lat, "lon": lon, "forcing": f,
                       "source": "FMI open data (WAM wave model, HARMONIE wind)"}
                hd = (q.get("hdg") or [None])[0]
                cg = (q.get("cog") or [None])[0]
                if hd is not None and cg is not None:
                    try:
                        out["drift"] = _fmi.explain_drift(float(hd), float(cg), f)
                    except ValueError:
                        pass
            except Exception as exc:
                return self._fail(502, str(exc)[:200])
            return self._send(json.dumps(out).encode(), "application/json", "FMI")

        if u.path == "/alerts/live":
            eng = _engine()
            if eng is None:
                return self._fail(503, "motor en vivo no disponible")
            body = json.dumps(eng.geojson()).encode()
            return self._send(body, "application/json",
                              "LIVE %d" % eng.stats.get("alerts", 0))

        # LOS BUQUES DE LA VENTANA EN VIVO, en el formato de tracks.geojson.
        #
        # Esto es lo que quita de en medio el «hay que compilar otra vez». El
        # visor los fusiona en su propio HIST, asi que el deslizador, la
        # instantanea, el historial de un buque y los recuentos cubren tambien
        # el tramo que el build no ha visto. Mismo constructor que el build
        # (ais.tracks_geojson), para que una derrota no cambie de forma al
        # cruzar esa frontera.
        if u.path == "/vessels/live":
            eng = _engine()
            if eng is None:
                return self._fail(503, "motor en vivo no disponible")
            try:
                since = int((q.get("since") or ["0"])[0]) or None
            except ValueError:
                since = None
            fc = eng.tracks_geojson(since=since)
            body = json.dumps(fc).encode()
            return self._send(body, "application/json",
                              "LIVE %d" % len(fc.get("features") or []))

        if u.path == "/alerts/status":
            eng = _engine()
            if eng is None:
                return self._fail(503, "motor en vivo no disponible")
            return self._send(json.dumps(eng.stats).encode(), "application/json")

        # Push, no sondeo. El valor del producto es disparar EN EL MOMENTO en
        # que se descubre; hacer que el navegador pregunte cada minuto añade
        # hasta un minuto de retardo por nada.
        if u.path == "/events":
            eng = _engine()
            if eng is None:
                return self._fail(503, "motor en vivo no disponible")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            last = -1
            try:
                while True:
                    if eng.at != last:
                        last = eng.at
                        payload = json.dumps({
                            "at": eng.at,
                            "alerts": eng.stats.get("alerts", 0),
                            "new": eng.stats.get("new", 0),
                            "newest_fix_ms": eng.stats.get("newest_fix_ms"),
                            "eval_s": eng.stats.get("eval_s"),
                            # QUE disparo el ciclo. Un operador tiene que
                            # poder distinguir «llego dato y se comprobo» de
                            # «no llego nada y se repaso por si acaso»: son
                            # dos estados muy distintos de una herramienta de
                            # vigilancia y antes se veian igual.
                            "trigger": eng.stats.get("trigger"),
                            "window_h": eng.stats.get("window_h"),
                            "sources": _sources(eng),
                        })
                        self.wfile.write(("event: cycle\ndata: %s\n\n" % payload).encode())
                    else:
                        self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    time.sleep(2)
            except (BrokenPipeError, ConnectionResetError):
                return

        # La cobertura AIS, EN VIVO, leida del almacen y no del build.
        #
        # La pista de cobertura venia del manifest, asi que se quedaba en el
        # instante en que se compilo: a las 42 h de un build parecia que se
        # habian perdido datos, cuando lo que pasaba es que la grabadora
        # habia seguido. Esto lo lee del polllog, que es lo que registra
        # CUANDO estabamos sondeando -- 31 kB al dia comprimido, asi que se
        # puede recalcular a peticion en vez de congelarlo.
        #
        # No se cachea en disco a proposito: su valor es justamente estar al
        # dia. Se guarda unos segundos en memoria para que varias pestanas
        # abiertas no relean el almacen entero cada una.
        if u.path == "/coverage":
            now = time.time()
            if _COV["at"] and now - _COV["at"] < COVERAGE_TTL_S:
                return self._send(_COV["raw"], "application/json", "HIT")
            try:
                sys.path.insert(0, os.path.dirname(HERE))
                from custody import ais as _ais, paths as _p
                roots = _p.records()
                if not roots:
                    return self._fail(503, "no hay almacen AIS")
                # TODOS los almacenes. Leer solo el primero dejo 4,6 h de
                # grabacion invisibles el 2026-11-13: ver paths.records().
                polls = _ais.load_polls(roots)
                wins = _ais.coverage_windows(polls)
                body = json.dumps({
                    "windows_ms": [[int(a), int(b)] for a, b in wins],
                    "newest_ms": int(wins[-1][1]) if wins else None,
                    "polls": len(polls), "roots": roots, "root": roots[0],
                }).encode()
            except Exception as exc:
                return self._fail(502, str(exc)[:200])
            _COV["raw"], _COV["at"] = body, now
            return self._send(body, "application/json", "MISS")

        # CUANDO TIENE DATO CADA FUENTE.
        #
        # Es lo que contesta «puedo superponer estas dos capas en el mismo
        # instante». Antes habia que saberselo: el AIS esta en una pista, las
        # pasadas Sentinel en otra, y la cadencia de los modelos en ningun
        # sitio. Aqui se junta, y cada ventana se LEE de su servicio en vez de
        # escribirse a mano:
        #   AIS      del polllog, que registra cuando sondeabamos de verdad
        #   CMEMS    de la dimension `time` de sus capacidades WMTS
        #   FMI      del eje de tiempos que trae su propia respuesta
        #   AISHub   de si hay clave
        # Las pasadas Sentinel las anade el navegador, que ya tiene el
        # catalogo STAC cargado.
        if u.path == "/sources/time":
            now = time.time()
            if _SRC["at"] and now - _SRC["at"] < SRC_TTL_S and not q.get("refresh"):
                return self._send(_SRC["raw"], "application/json", "HIT")
            sys.path.insert(0, os.path.dirname(HERE))
            out = {"generated_ms": int(now * 1000), "sources": []}
            add = out["sources"].append

            # --- lo nuestro: la grabacion
            try:
                from custody import ais as _ais, paths as _p
                roots = _p.records()
                polls = _ais.load_polls(roots)
                wins = [[int(a), int(b)] for a, b in _ais.coverage_windows(polls)]
                add({"id": "ais_fintraffic", "group": "ours",
                     "name": "AIS · Fintraffic", "kind": "windows",
                     "windows_ms": wins, "step_s": 60,
                     "newest_ms": wins[-1][1] if wins else None,
                     "licence": "CC BY 4.0",
                     "note": "Our own recording, from %s." % roots[0]})
                out["stores"] = roots
                out["strays"] = _p.stray_records()
            except Exception as exc:
                add({"id": "ais_fintraffic", "group": "ours",
                     "name": "AIS · Fintraffic", "kind": "windows",
                     "windows_ms": [], "state": "error", "note": str(exc)[:160]})

            # --- lo nuestro: el motor en vivo (la ventana que SI esta evaluada)
            eng = _engine()
            if eng is not None and eng.stats.get("window_start_ms"):
                add({"id": "alerts_live", "group": "ours",
                     "name": "Alerts evaluated", "kind": "windows",
                     "windows_ms": [[int(eng.stats["window_start_ms"]),
                                     int(eng.stats.get("newest_fix_ms") or
                                         eng.stats["window_start_ms"])]],
                     "step_s": None,
                     "note": ("Rolling window the engine re-checks on every "
                              "new fix: %.1f h." % (eng.stats.get("window_h") or 0))})

            # --- AISHub
            ah = (eng.stats.get("aishub") if eng is not None else None) or {}
            add({"id": "aishub", "group": "ours", "name": "AIS · AISHub",
                 "kind": "windows", "windows_ms": [], "step_s": 60,
                 "state": "needs_key" if ah.get("reason") == "no_key" else
                          ("ok" if ah.get("ok") else "idle"),
                 "licence": "AISHub terms · no redistribution",
                 "note": "32 stations in the Gotland gap. Needs a contributing receiver."})

            # --- forzamiento: FMI, medido
            try:
                from custody import fmi as _fmi
                hz = _fmi.horizon()
                for k, nm in (("wind", "FMI HARMONIE · wind"),
                              ("wave", "FMI WAM · wave")):
                    h = hz.get(k) or {}
                    add({"id": "fmi_" + k, "group": "forcing", "name": nm,
                         "kind": "span", "start_ms": h.get("start_ms"),
                         "end_ms": h.get("end_ms"), "step_s": h.get("step_s"),
                         "forecast": True, "licence": "CC BY 4.0",
                         "note": ("Point query returns FORECAST only: it starts "
                                  "at the next whole hour, so it cannot "
                                  "reconstruct the past.")})
            except Exception as exc:
                add({"id": "fmi", "group": "forcing", "name": "FMI",
                     "kind": "span", "state": "error", "note": str(exc)[:160]})

            _SRC["raw"] = json.dumps(out).encode()
            _SRC["at"] = now
            return self._send(_SRC["raw"], "application/json", "MISS")

        if u.path == "/cache/img":
            url = (q.get("u") or [""])[0]
            if not url or not _allowed(url):
                return self._fail(403, "host no permitido")
            try:
                raw, ct, hit = cached("img", url, "bin")
            except Exception as exc:
                return self._fail(502, str(exc)[:200])
            return self._send(raw, ct, "HIT" if hit else "MISS")

        if u.path == "/cache/detect":
            """CFAR sobre un recorte GeoTIFF. El recorte se cachea igual que
            una tesela, asi que repetir la deteccion sobre la misma escena y
            el mismo encuadre no vuelve a salir a la red."""
            url = (q.get("u") or [""])[0]
            if not url or not _allowed(url):
                return self._fail(403, "host no permitido")
            try:
                raw, _ct, hit = cached("crop", url, "tif")
                from custody import sardetect
                opt = {}
                if q.get("k"):
                    opt["k"] = float(q["k"][0])
                fc, st = sardetect.detect(raw, opt)
                fc["properties"] = dict(st, crop_from_cache=hit)
                body = json.dumps(fc).encode()
            except Exception as exc:
                return self._fail(502, str(exc)[:300])
            return self._send(body, "application/json", "HIT" if hit else "MISS")

        if u.path == "/cache/meta":
            url = (q.get("u") or [""])[0]
            if not url or not _allowed(url):
                return self._fail(403, "host no permitido")
            try:
                raw, ct, hit = cached("meta", url, "json")
            except Exception as exc:
                return self._fail(502, str(exc)[:200])
            return self._send(raw, ct, "HIT" if hit else "MISS")

        if u.path.startswith("/data/") and u.path.endswith((".json", ".geojson")):
            fpath = self.translate_path(u.path)
            if os.path.isfile(fpath):
                with open(fpath, "rb") as fh:
                    raw = fh.read()
                return self._send(raw, "application/json")

        return super().do_GET()

    # ----------------------------------------------------------------- POST
    def do_POST(self):
        u = urllib.parse.urlsplit(self.path)
        if u.path == "/cache/purge":
            import shutil
            shutil.rmtree(CACHE, ignore_errors=True)
            os.makedirs(CACHE, exist_ok=True)
            return self._send(json.dumps({"purged": True}).encode(), "application/json")
        if u.path != "/cache/stac":
            return self._fail(404, "no")
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        target = (urllib.parse.parse_qs(u.query).get("u") or [""])[0]
        if not target or not _allowed(target):
            return self._fail(403, "host no permitido")
        # EL REGISTRO DE UN MOSAICO NO SE CACHEA.
        #
        # /mosaic/register no devuelve datos: devuelve el IDENTIFICADOR de un
        # recurso que Planetary Computer crea en su lado y caduca en unas
        # horas. Cachear el identificador de algo temporal durante 6 h es el
        # error, y se veia asi: pasado ese rato TODAS las teselas del mosaico
        # devolvian «HTTP Error 410: Gone» y el radar desaparecia del mapa sin
        # que nada dijera por que. Medido el 2026-11-13: 58 % de las teselas
        # en 410 con un id de tres horas, servido desde nuestra propia cache.
        #
        # Una busqueda STAC normal SI se cachea: esa devuelve datos.
        is_reg = target.rstrip("/").endswith("/mosaic/register")
        try:
            raw, ct, hit = cached("stac", target, "json",
                                  ttl=0 if is_reg else STAC_TTL,
                                  body=body, ctype="application/json")
        except Exception as exc:
            return self._fail(502, str(exc)[:200])
        return self._send(raw, ct, "HIT" if hit else "MISS")


class Server(ThreadingHTTPServer):
    # ThreadingHTTPServer ya trae el ThreadingMixIn.
    daemon_threads = True
    allow_reuse_address = True


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    os.makedirs(CACHE, exist_ok=True)
    srv = Server(("127.0.0.1", port), Handler)
    st = cache_stats()
    print("visor en http://127.0.0.1:%d  ·  cache %d ficheros, %.1f MB en %s"
          % (port, st["files"], st["bytes"] / 1e6, CACHE), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
