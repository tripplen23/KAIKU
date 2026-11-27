"""Optional high-fidelity ingester: Digitraffic MQTT-over-WebSocket.

Why this exists (REQ-AIS-013): the REST endpoint returns only the LATEST fix
per vessel, so polling at the upstream cache TTL of 60 s captures ~18 % of the
position reports the broadcast stream carries (measured 2026-10-27:
381 new fixes/min via REST vs 2138 location msgs/min via MQTT). For anchor-drag
and loitering detection 60 s is enough; for manoeuvre reconstruction it is not.

Run it ALONGSIDE recorder.py, not instead of it. They are independent failure
domains writing to separate streams; recorder.py is the zero-dependency
guarantee, this is the fidelity upgrade.

Requires: paho-mqtt (pip install paho-mqtt). If it is not importable this
module exits 4 and the REST recorder is unaffected.

Endpoint verified 2026-10-27: wss://meri.digitraffic.fi:443/mqtt, anonymous,
TLS required. Observed topic leaves are `location` (SINGULAR), `metadata`, and
`vessels-v2/status` -- the portal text says `vessels-v2/<mmsi>/locations`,
which does not match the wire. We subscribe to `vessels-v2/#` and dispatch on
what actually arrives.

Data source: Fintraffic / digitraffic.fi, licence CC 4.0 BY.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import ssl
import sys
import threading
import time

import store
from recorder import DedupIndex, acquire_lock

try:
    import paho.mqtt.client as mqtt
except ImportError:
    sys.stderr.write("paho-mqtt not installed: pip install paho-mqtt\n")
    raise SystemExit(4)

HOST = "meri.digitraffic.fi"
PORT = 443
WS_PATH = "/mqtt"
TOPIC = "vessels-v2/#"

STREAM_MQTT_LOC = "mqtt_locations"
STREAM_MQTT_META = "mqtt_metadata"

LOG = logging.getLogger("mqtt")
_stop = threading.Event()


def _handle_signal(signum, _frame):
    LOG.info("signal %s received, flushing and stopping", signum)
    _stop.set()


class Ingester:
    def __init__(self, root: str, flush_seconds: float):
        self.root = root
        self.flush_seconds = flush_seconds
        self.lock = threading.Lock()
        self.buf_loc: list[dict] = []
        self.buf_meta: list[dict] = []
        self.loc_index = DedupIndex()
        self.meta_index = DedupIndex()
        self.last_msg = time.time()
        self.counters = {"location": 0, "metadata": 0, "status": 0,
                         "dropped_dup": 0, "flushes": 0, "bytes": 0,
                         "reconnects": 0}

    # ---- MQTT callbacks -------------------------------------------------
    def on_connect(self, client, _u, _flags, reason, _props=None):
        LOG.info("connected: %s", reason)
        client.subscribe(TOPIC, qos=0)

    def on_disconnect(self, _c, _u, *a, **kw):
        self.counters["reconnects"] += 1
        LOG.warning("disconnected; paho will reconnect")

    def on_message(self, _c, _u, msg):
        self.last_msg = time.time()
        rx_ms = int(self.last_msg * 1000)
        parts = msg.topic.split("/")
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            return
        self.counters["bytes"] += len(msg.payload)
        if len(parts) == 2 and parts[1] == "status":
            self.counters["status"] += 1
            return
        if len(parts) != 3:
            return
        mmsi_s, leaf = parts[1], parts[2]
        try:
            mmsi = int(mmsi_s)
        except ValueError:
            return
        rec = dict(payload)
        rec["mmsi"] = mmsi
        rec["rx_ms"] = rx_ms
        with self.lock:
            if leaf.startswith("location"):
                self.counters["location"] += 1
                self.buf_loc.append(rec)
            elif leaf.startswith("metadata"):
                self.counters["metadata"] += 1
                self.buf_meta.append(rec)

    # ---- writer ---------------------------------------------------------
    def flush(self) -> None:
        with self.lock:
            loc, self.buf_loc = self.buf_loc, []
            meta, self.buf_meta = self.buf_meta, []
        now = store.utc_now()
        if loc:
            self.loc_index.roll(self.root, STREAM_MQTT_LOC, now)
            # On reconnect the broker replays retained messages; key on
            # (mmsi, time) so a replay cannot duplicate a fix on disk.
            fresh = []
            for r in loc:
                k = (r.get("mmsi"), r.get("time"))
                if k in self.loc_index.keys:
                    continue
                self.loc_index.keys.add(k)
                fresh.append(r)
            self.counters["dropped_dup"] += len(loc) - len(fresh)
            store.append_batch(self.root, STREAM_MQTT_LOC, now, fresh)
        if meta:
            self.meta_index.roll(self.root, STREAM_MQTT_META, now)
            fresh = []
            for r in meta:
                k = (r.get("mmsi"), r.get("timestamp"))
                if k in self.meta_index.keys:
                    continue
                self.meta_index.keys.add(k)
                fresh.append(r)
            store.append_batch(self.root, STREAM_MQTT_META, now, fresh)
        if loc or meta:
            self.counters["flushes"] += 1


def run(root: str, flush_seconds: float, stale_seconds: float) -> int:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    lock = acquire_lock(root, "mqtt_ingest.lock")
    ing = Ingester(root, flush_seconds)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id=f"ais-recorder-{int(time.time())}",
                         transport="websockets", clean_session=True)
    client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    client.ws_set_options(path=WS_PATH)
    client.reconnect_delay_set(min_delay=1, max_delay=120)
    client.on_connect = ing.on_connect
    client.on_disconnect = ing.on_disconnect
    client.on_message = ing.on_message
    client.connect_async(HOST, PORT, keepalive=60)
    client.loop_start()

    LOG.info("mqtt ingest start root=%s flush=%.0fs", root, flush_seconds)
    t0 = time.time()
    try:
        while not _stop.wait(flush_seconds):
            ing.flush()
            # REQ-AIS-014 watchdog: a silent TCP half-open is the classic MQTT
            # failure. If nothing arrives for `stale_seconds`, force a reconnect.
            if time.time() - ing.last_msg > stale_seconds:
                LOG.warning("no message for %.0fs, forcing reconnect",
                            time.time() - ing.last_msg)
                ing.last_msg = time.time()
                try:
                    client.reconnect()
                except Exception as exc:
                    LOG.warning("reconnect failed: %s", exc)
            LOG.info("counters %s", ing.counters)
    finally:
        client.loop_stop()
        try:
            client.disconnect()
        except Exception:
            pass
        ing.flush()
        lock.close()
    el = time.time() - t0
    LOG.info("stopped after %.0fs; %s; %.0f location msgs/min",
             el, ing.counters, ing.counters["location"] / (el / 60) if el else 0)
    return 0


def main(argv=None) -> int:
    default_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    ap = argparse.ArgumentParser(description="Digitraffic AIS MQTT ingester")
    ap.add_argument("--root", default=os.environ.get("AIS_DATA_ROOT", default_root))
    ap.add_argument("--flush-seconds", type=float, default=30.0,
                    help="max data at risk on hard kill (default: %(default)s)")
    ap.add_argument("--stale-seconds", type=float, default=180.0)
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)sZ %(levelname)s %(message)s")
    logging.Formatter.converter = time.gmtime
    return run(os.path.abspath(args.root), args.flush_seconds, args.stale_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
