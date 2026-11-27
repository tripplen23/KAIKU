"""Cliente HTTP con caché en disco. Solo stdlib (urllib).

Reglas que se cumplen aquí y no en los llamadores:
  - `Accept-Encoding: gzip` siempre y descompresión transparente. Digitraffic
    devuelve 406 sin ella (verificado, canal/iteracion_01/04_coo.md).
  - User-Agent identificable. Overpass devuelve 406 al UA por defecto de
    urllib (verificado 2026-11-09).
  - Reintento con backoff exponencial y jitter; nunca bucle infinito.
  - Caché por sha256 de (método, url, cuerpo). Una vez descargado, el build es
    reproducible sin red. `--refresh` la ignora.
"""
import gzip
import hashlib
import io
import json
import logging
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request

LOG = logging.getLogger("custody.net")
UA = os.environ.get("CUSTODY_USER_AGENT", "custody-mvp/0.1 (research prototype)")
# La ruta la fija config/custody.toml (o CUSTODY_PATHS_CACHE). Antes se
# construia aqui con __file__, lo que obligaba a editar codigo para mover la
# cache a otro disco.
try:
    from custody import paths as _paths
    CACHE_DIR = _paths.cache()
except Exception:                      # arranque sin config: el defecto
    CACHE_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")


def _key(method, url, body):
    h = hashlib.sha256()
    h.update(method.encode())
    h.update(url.encode())
    if body:
        h.update(body if isinstance(body, bytes) else body.encode())
    return h.hexdigest()[:24]


def fetch(url, body=None, headers=None, method=None, cache=True, refresh=False,
          timeout=180, retries=3, ext="bin", max_age=None):
    """Devuelve (bytes, from_cache). Lanza la última excepción si agota reintentos.

    `max_age` en segundos. None = para siempre, que es lo correcto para una
    línea de costa o unas capacidades WMTS.

    POR QUÉ EXISTE max_age. No lo había, y «existe el fichero» bastaba para
    servirlo. Para un PRONÓSTICO eso es un error silencioso y permanente:
    medido el 2026-11-13, la consulta de oleaje WAM de FMI devolvía desde
    caché una serie que terminaba a las 15:00Z mientras el reloj marcaba las
    20:21Z, y habría seguido envejeciendo para siempre. Una herramienta en
    tiempo real que sirve un pronóstico de hace cinco horas no está
    retrasada: está equivocada, y sin un solo error en el log.
    """
    method = method or ("POST" if body is not None else "GET")
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{_key(method, url, body)}.{ext}")
    if cache and not refresh and os.path.exists(path) and os.path.getsize(path) > 0:
        fresh = max_age is None or (time.time() - os.path.getmtime(path)) < max_age
        if fresh:
            with open(path, "rb") as fh:
                return fh.read(), True

    hdrs = {"User-Agent": UA, "Accept-Encoding": "gzip"}
    if headers:
        hdrs.update(headers)
    data = body.encode() if isinstance(body, str) else body
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            if cache:
                tmp = path + ".part"
                with open(tmp, "wb") as fh:
                    fh.write(raw)
                os.replace(tmp, path)
            return raw, False
        except Exception as exc:  # incluye HTTPError, URLError, timeout
            last = exc
            if attempt >= retries:
                break
            wait = min(60.0, (2 ** attempt) * 2.0) * (0.7 + 0.6 * random.random())
            LOG.warning("fetch %s falló (%s); reintento en %.1f s", url[:90], exc, wait)
            time.sleep(wait)
    raise last


def fetch_json(url, body=None, headers=None, **kw):
    hdrs = {"Accept": "application/json"}
    if body is not None and isinstance(body, (dict, list)):
        body = json.dumps(body)
        hdrs["Content-Type"] = "application/json"
    if headers:
        hdrs.update(headers)
    raw, cached = fetch(url, body=body, headers=hdrs, ext="json", **kw)
    return json.loads(raw.decode("utf-8")), cached
