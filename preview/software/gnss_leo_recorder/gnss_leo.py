#!/usr/bin/env python3
"""GNSS-from-orbit recorder: Spire (NOAA/UCAR), Swarm (ESA), Sentinel-6 (EUMETSAT).

Downloads the free navigation-receiver files of these satellites, keeps them, and extracts
the carrier-to-noise observables over the Baltic and a control region. Architecture:
README.md. Operation: ../MANUAL.md Part 0-bis. Standard library only, Python >= 3.11.

Run with `python3 -I` (it reads untrusted downloads): -I drops the script directory from
sys.path, so it is put back explicitly below - this directory only, never the data's.

  python3 -I gnss_leo.py                      run forever (what the systemd unit does)
  python3 -I gnss_leo.py --once               one pass over every source, then exit
  python3 -I gnss_leo.py --since 2026-11-09   backfill from that day (also: the config's
                                              history_start is always the floor)
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import argparse  # noqa: E402
import datetime as dt  # noqa: E402
import logging  # noqa: E402
import signal  # noqa: E402
import time  # noqa: E402

import common  # noqa: E402
from src_igs import IgsOrbits  # noqa: E402
from src_satjam import SatJam  # noqa: E402
from src_sentinel6 import Sentinel6  # noqa: E402
from src_spire import Spire  # noqa: E402
from src_swarm import Swarm  # noqa: E402

SOURCES = {c.name: c for c in (Spire, Swarm, Sentinel6, IgsOrbits, SatJam)}
LOG = logging.getLogger("gnss_leo")
_stop = False


def _handle(signum, _frame):
    global _stop
    _stop = True
    LOG.info("signal %s: stopping after the current file", signum)


def write_state(store: common.Store, sources, started: str) -> None:
    try:
        free = store.free_bytes()
    except OSError:
        free = None
    common.atomic_write_json(store.state_path(), {
        "pid": os.getpid(), "started_utc": started, "updated_utc": common.now_iso(),
        "raw_root": store.raw_root, "extract_root": store.extract_root,
        "free_gb": round(free / 1e9, 1) if free is not None else None,
        "min_free_gb": store.min_free / 1e9,
        "sources": {s.name: s.state for s in sources},
    })


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", help="TOML (default: gnss_leo.toml next to this file)")
    ap.add_argument("--since", help="first day YYYY-MM-DD (default: store.history_start)")
    ap.add_argument("--once", action="store_true", help="one pass, then exit")
    ap.add_argument("--sources", help="comma list, default all: " + ",".join(SOURCES))
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    cfg = common.load_config(args.config)
    store = common.Store(cfg)
    common.setup_logging(store.log_path(), args.verbose)
    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    locks = [common.acquire_lock(store.extract_root), common.acquire_lock(store.raw_root)]  # noqa: F841

    since = common.parse_day(args.since or cfg["store"]["history_start"])
    floor = common.parse_day(cfg["store"]["history_start"])
    if since > floor:
        since = floor  # the configured history is always kept complete
    wanted = [s.strip() for s in args.sources.split(",")] if args.sources else list(SOURCES)
    regions = common.Regions(cfg)
    sources = [SOURCES[n](cfg, store, regions, stop=lambda: _stop) for n in wanted]
    started = common.now_iso()

    LOG.info("start pid %d, config %s", os.getpid(), cfg["_path"])
    LOG.info("raw store %s (%.1f GB free, floor %.0f GB); extract store %s",
             store.raw_root, store.free_bytes() / 1e9, store.min_free / 1e9, store.extract_root)
    LOG.info("history from %s; regions %s", since, [b[0] for b in regions.boxes])
    for s in sources:
        ok, why = s.enabled()
        s.state.update({"enabled": ok, "reason": why})
        s.progress = lambda: write_state(store, sources, started)
        if ok:
            LOG.info("source %s: enabled, every %.0f min, lookback %d days",
                     s.name, s.poll_s / 60, s.lookback)
        else:
            LOG.warning("source %s: DISABLED - %s", s.name, why)

    write_state(store, sources, started)
    due = {s.name: 0.0 for s in sources}
    first = {s.name: True for s in sources}
    warned = {s.name: time.time() for s in sources}
    while not _stop:
        for s in sources:
            if _stop or time.time() < due[s.name]:
                continue
            today = common.utcnow().date()
            try:
                s.cycle(since, today, full=first[s.name])
            except Exception as exc:  # noqa: BLE001 - a source never takes the others down
                LOG.exception("source %s: cycle failed: %s", s.name, exc)
                s.state.update({"last_error": f"cycle: {exc}", "last_error_utc": common.now_iso()})
            first[s.name] = False
            due[s.name] = time.time() + s.poll_s
            st = s.state
            if not st.get("enabled"):
                if time.time() - warned[s.name] > 86400:
                    LOG.warning("source %s: still DISABLED - %s", s.name, st.get("reason"))
                    warned[s.name] = time.time()
            else:
                LOG.info("source %s: cycle done, incomplete days %s", s.name,
                         st.get("pending_days", [])[-6:])
            write_state(store, sources, started)
        if args.once:
            break
        nxt = min(due.values())
        while not _stop and time.time() < nxt:
            time.sleep(min(5.0, max(0.1, nxt - time.time())))
    write_state(store, sources, started)
    LOG.info("stopped cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
