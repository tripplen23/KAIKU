"""AIS recorder for Fintraffic Digitraffic Marine (meri.digitraffic.fi).

Requirements implemented here: REQ-AIS-001..014 (see README.md).
Standard library only. Python >= 3.9.

Data source: Fintraffic / digitraffic.fi, licence CC 4.0 BY.
"""

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import logging
import os
import random
import signal
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import store

LOCATIONS_URL = "https://meri.digitraffic.fi/api/ais/v1/locations"
VESSELS_URL = "https://meri.digitraffic.fi/api/ais/v1/vessels"

# REQ-AIS-003: identify the client. Digitraffic raises the per-IP quota for
# requests carrying this header. No PII (explicit instruction in the API ToS).
DIGITRAFFIC_USER = os.environ.get("DIGITRAFFIC_USER", "ais-recorder/1.0 (research prototype)")

LOG = logging.getLogger("ais")

_stop = False


def _handle_signal(signum, _frame):
    global _stop
    _stop = True
    LOG.info("signal %s received, stopping after current cycle", signum)


class HttpError(Exception):
    pass


def fetch(url: str, etag: str | None, timeout: float = 30.0) -> tuple[int, dict | list | None, str | None, int]:
    """GET with gzip and conditional request.

    Returns (status, parsed_body_or_None, etag, wire_bytes).
    status 304 -> body is None, nothing changed upstream.
    """
    headers = {
        "Accept-Encoding": "gzip",          # mandatory per Digitraffic ToS
        "Digitraffic-User": DIGITRAFFIC_USER,
        "Accept": "application/json",
    }
    if etag:
        headers["If-None-Match"] = etag
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            wire = len(raw)
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return resp.status, json.loads(raw.decode("utf-8")), resp.headers.get("ETag"), wire
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return 304, None, etag, 0
        raise HttpError(f"HTTP {exc.code} {exc.reason}") from exc
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
        raise HttpError(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HttpError(f"malformed JSON: {exc}") from exc


def location_records(payload: dict, rx_ms: int) -> list[dict]:
    """Flatten the GeoJSON FeatureCollection into NDJSON records.

    Field names are kept verbatim from the API (REQ-AIS-005: no renaming,
    no unit conversion, no derived fields in the raw stream) except for the
    two recorder-added fields prefixed `rx_`.
    """
    out = []
    data_updated = payload.get("dataUpdatedTime")
    for feat in payload.get("features", ()):
        props = feat.get("properties") or {}
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates") or [None, None]
        rec = {
            "mmsi": feat.get("mmsi", props.get("mmsi")),
            "lon": coords[0],
            "lat": coords[1],
            "sog": props.get("sog"),
            "cog": props.get("cog"),
            "navStat": props.get("navStat"),
            "rot": props.get("rot"),
            "posAcc": props.get("posAcc"),
            "raim": props.get("raim"),
            "heading": props.get("heading"),
            "timestamp": props.get("timestamp"),
            "timestampExternal": props.get("timestampExternal"),
            "rx_ms": rx_ms,
            "rx_dataUpdatedTime": data_updated,
        }
        out.append(rec)
    return out


def vessel_records(payload: list, rx_ms: int) -> list[dict]:
    out = []
    for v in payload or ():
        rec = dict(v)
        rec["rx_ms"] = rx_ms
        out.append(rec)
    return out


class DedupIndex:
    """REQ-AIS-006: a position report is written at most once.

    Key = (mmsi, timestampExternal). The upstream endpoint returns the LATEST
    known fix per vessel over a ~24 h window, so ~60-70 % of every poll is
    data we already hold. Keyed dedup is what makes the disk budget work.

    The index is rebuilt from the day file on start (REQ-AIS-008). The file is
    the only state; there is no sidecar that can disagree with it.
    """

    def __init__(self):
        self.day: str | None = None
        self.keys: set[tuple] = set()

    def roll(self, root: str, stream: str, dt: datetime) -> None:
        key = store.day_key(dt)
        if key == self.day:
            return
        self.day = key
        self.keys = set()
        path = store.stream_path(root, stream, dt)
        n = 0
        for rec in store.iter_records(path):
            self.keys.add(self._key(rec, stream))
            n += 1
        if n:
            LOG.info("resume: %s records already in %s", n, os.path.basename(path))

    @staticmethod
    def _key(rec: dict, stream: str) -> tuple:
        if stream == store.STREAM_LOCATIONS:
            return (rec.get("mmsi"), rec.get("timestampExternal"))
        if stream == store.STREAM_VESSELS:
            # Static reports are re-broadcast every ~6 min with an updated
            # `timestamp` and otherwise identical content: measured 2026-10-27,
            # 837 content-distinct rows out of 1731 timestamp-distinct ones.
            # Key on content so the metadata stream records CHANGES, not
            # heartbeats. "When did this vessel last transmit" is already
            # answered by the locations stream and the poll log.
            body = {k: v for k, v in rec.items() if k not in ("timestamp", "rx_ms")}
            return (rec.get("mmsi"),
                    hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest())
        return (rec.get("mmsi"), rec.get("timestamp"))

    def filter_new(self, records: list[dict], stream: str) -> list[dict]:
        fresh = []
        for rec in records:
            k = self._key(rec, stream)
            if k in self.keys:
                continue
            self.keys.add(k)
            fresh.append(rec)
        return fresh


def acquire_lock(root: str, name: str = "recorder.lock"):
    """REQ-AIS-011: exactly one writer per data root and stream group."""
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, name)
    fh = open(path, "w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.stderr.write(f"another recorder already holds {path}\n")
        sys.exit(3)
    fh.write(f"{os.getpid()}\n")
    fh.flush()
    return fh


def run(root: str, interval: float, vessels_interval: float) -> int:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    lock = acquire_lock(root)

    loc_index = DedupIndex()
    ves_index = DedupIndex()
    loc_etag = None
    ves_etag = None
    seq = 0
    next_vessels = 0.0
    backoff = 0.0
    consecutive_failures = 0

    LOG.info("recorder start root=%s interval=%.0fs ua=%r", root, interval, DIGITRAFFIC_USER)

    while not _stop:
        cycle_start = time.time()
        seq += 1
        now = store.utc_now()
        rx_ms = int(cycle_start * 1000)

        loc_index.roll(root, store.STREAM_LOCATIONS, now)
        ves_index.roll(root, store.STREAM_VESSELS, now)

        entry = {
            "seq": seq,
            "rx_ms": rx_ms,
            "rx_iso": now.isoformat(timespec="seconds"),
            "stream": store.STREAM_LOCATIONS,
        }
        try:
            status, payload, etag, wire = fetch(LOCATIONS_URL, loc_etag)
            entry["http"] = status
            entry["wire_bytes"] = wire
            if status == 304:
                entry.update(received=0, new=0, written_bytes=0, sha256="")
            else:
                loc_etag = etag
                recs = location_records(payload, rx_ms)
                fresh = loc_index.filter_new(recs, store.STREAM_LOCATIONS)
                nbytes, digest = store.append_batch(root, store.STREAM_LOCATIONS, now, fresh)
                entry.update(received=len(recs), new=len(fresh),
                             written_bytes=nbytes, sha256=digest,
                             dataUpdatedTime=payload.get("dataUpdatedTime"))
            consecutive_failures = 0
            backoff = 0.0
        except HttpError as exc:
            # REQ-AIS-007: a network failure is recorded, never fatal, never
            # silently swallowed. The next successful poll recovers the latest
            # fix of every vessel that reported during the outage, because the
            # endpoint's default window is 24 h wide.
            consecutive_failures += 1
            entry.update(http=0, error=str(exc)[:200], received=0, new=0,
                         written_bytes=0, consecutive_failures=consecutive_failures)
            backoff = min(300.0, (2 ** min(consecutive_failures, 8)) * random.uniform(0.5, 1.0))
            LOG.warning("poll %d failed (%s); backoff %.0fs", seq, exc, backoff)

        store.append_batch(root, store.STREAM_POLLLOG, now, [entry])
        if entry.get("new"):
            LOG.info("poll %d: %d received, %d new, %d B on disk",
                     seq, entry["received"], entry["new"], entry["written_bytes"])

        # vessel metadata: slow stream, polled independently
        if cycle_start >= next_vessels and not _stop:
            vent = {"seq": seq, "rx_ms": rx_ms, "rx_iso": entry["rx_iso"],
                    "stream": store.STREAM_VESSELS}
            try:
                status, payload, etag, wire = fetch(VESSELS_URL, ves_etag)
                vent["http"] = status
                vent["wire_bytes"] = wire
                if status == 304:
                    vent.update(received=0, new=0, written_bytes=0)
                else:
                    ves_etag = etag
                    recs = vessel_records(payload, rx_ms)
                    fresh = ves_index.filter_new(recs, store.STREAM_VESSELS)
                    nbytes, digest = store.append_batch(root, store.STREAM_VESSELS, now, fresh)
                    vent.update(received=len(recs), new=len(fresh),
                                written_bytes=nbytes, sha256=digest)
                next_vessels = cycle_start + vessels_interval
            except HttpError as exc:
                vent.update(http=0, error=str(exc)[:200], received=0, new=0, written_bytes=0)
                next_vessels = cycle_start + min(vessels_interval, 120.0)
            store.append_batch(root, store.STREAM_POLLLOG, now, [vent])

        # REQ-AIS-002: wall-clock aligned cadence; drift does not accumulate.
        sleep_for = backoff if backoff else max(0.0, interval - (time.time() - cycle_start))
        deadline = time.time() + sleep_for
        while not _stop and time.time() < deadline:
            time.sleep(min(1.0, deadline - time.time()))

    LOG.info("recorder stopped cleanly after %d cycles", seq)
    lock.close()
    return 0


# Donde escribe, por defecto: LO QUE DIGA LA CONFIGURACION DEL PROYECTO.
#
# Antes el defecto era `<directorio del grabador>/data` y nada mas, asi que el
# escritor y el lector tenian cada uno su propia idea de donde vive el
# almacen. El 2026-11-13 eso costo 4,6 h de grabacion invisible: la grabadora
# arranco con --root ~/ais_data y la aplicacion seguia mirando en Dropbox, sin
# un solo error en ningun log. Ahora los dos leen `paths.record` del mismo
# config/custody.toml.
#
# Sigue funcionando sin la aplicacion al lado --- es un componente propio, con
# sus propios requisitos REQ-AIS--- pero en ese caso lo DICE en el arranque en
# vez de inventarse una ruta en silencio.
CONFIG_HINT = os.environ.get(
    "CUSTODY_CONFIG",
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "..", "custody_mvp", "config", "custody.toml"))


def configured_root() -> tuple[str, str]:
    """(ruta, de donde sale). Nunca falla: si no hay config, su propio data/."""
    own = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    try:
        import tomllib
    except ImportError:
        return own, "sin tomllib (py<3.11): data/ propio"
    path = os.path.abspath(CONFIG_HINT)
    if not os.path.exists(path):
        return own, "sin %s: data/ propio" % path
    try:
        with open(path, "rb") as fh:
            cfg = tomllib.load(fh)
        r = (cfg.get("paths") or {}).get("record")
        if not r:
            return own, "%s no declara paths.record: data/ propio" % path
        return os.path.expanduser(r), path
    except Exception as exc:                       # noqa: BLE001
        return own, "%s ilegible (%s): data/ propio" % (path, exc)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Digitraffic AIS recorder")
    default_root, root_src = configured_root()
    ap.add_argument("--root", default=os.environ.get("AIS_DATA_ROOT", default_root),
                    help="data directory (default: %(default)s)")
    ap.add_argument("--interval", type=float, default=60.0,
                    help="locations poll period in seconds; upstream cache TTL is 60 s "
                         "so going below that returns identical bytes (default: %(default)s)")
    ap.add_argument("--vessels-interval", type=float, default=600.0,
                    help="metadata poll period in seconds (default: %(default)s)")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)sZ %(levelname)s %(message)s",
    )
    logging.Formatter.converter = time.gmtime
    if args.interval < 60.0:
        LOG.warning("interval %.0fs < upstream cache TTL 60s: wasted requests", args.interval)
    root = os.path.abspath(os.path.expanduser(args.root))
    LOG.info("store root %s (from %s)", root,
             "--root" if any(a.startswith("--root") for a in (argv or sys.argv[1:]))
             else "AIS_DATA_ROOT" if os.environ.get("AIS_DATA_ROOT") else root_src)
    # Un --root que no es el configurado es la receta exacta de los datos
    # dispersos. No se bloquea --- puede ser deliberado--- pero se dice.
    if os.path.realpath(root) != os.path.realpath(os.path.expanduser(default_root)):
        LOG.warning("ESTE NO ES EL ALMACEN CONFIGURADO (%s). La aplicacion no "
                    "leera lo que escribas aqui; para unirlo despues: "
                    "python3 merge_store.py --from %s --apply",
                    default_root, root)
    return run(root, args.interval, args.vessels_interval)


if __name__ == "__main__":
    raise SystemExit(main())
