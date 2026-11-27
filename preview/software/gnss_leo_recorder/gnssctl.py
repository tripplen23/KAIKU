#!/usr/bin/env python3
"""Control and inspection for gnss_leo_recorder. Reads the store; writes only with `extract`.

  python3 -I gnssctl.py status                 service, lock, sources, last log lines
  python3 -I gnssctl.py stats                  disk used, measured MB/day, 30-day projection
  python3 -I gnssctl.py verify                 sha256 of every raw file against its manifest,
                                               gzip CRC and row count of every extract
  python3 -I gnssctl.py gaps                   days missing or partial; hours without data
  python3 -I gnssctl.py extract --date 2026-11-13 [--source spire_ucar] [--out DIR]
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import argparse  # noqa: E402
import datetime as dt  # noqa: E402
import gzip  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
import zlib  # noqa: E402

import common  # noqa: E402
from gnss_leo import SOURCES  # noqa: E402

UNIT = "gnss-leo-recorder.service"
# days after which a day should be complete upstream (published latency + margin)
LATENCY = {"spire_ucar": 2, "swarm_esa": 5, "sentinel6_eum": 1, "igs_orbits": 2, "satjam": 1}


def _days(store: common.Store, source: str):
    return store.days_held(source)


def _sources(cfg, store, which):
    regions = common.Regions(cfg)
    names = [which] if which else list(SOURCES)
    return [SOURCES[n](cfg, store, regions) for n in names]


def cmd_status(cfg, store, args) -> int:
    try:
        act = subprocess.run(["systemctl", "--user", "is-active", UNIT], capture_output=True,
                             text=True, timeout=10).stdout.strip()
        ena = subprocess.run(["systemctl", "--user", "is-enabled", UNIT], capture_output=True,
                             text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        act = ena = "unknown"
    print(f"service   {UNIT}: {act}, {ena}")
    for root in (store.extract_root, store.raw_root):
        pid = common.lock_holder(root)
        print(f"lock      {root}: {'held by pid ' + str(pid) if pid else 'free'}")
    free = store.free_bytes()
    print(f"disk      {free / 1e9:.1f} GB free on {store.raw_root} (floor {store.min_free / 1e9:.0f} GB)"
          + ("   !!! BELOW FLOOR: raw downloads stopped !!!" if free < store.min_free else ""))
    try:
        with open(store.state_path(), encoding="utf-8") as fh:
            st = json.load(fh)
        print(f"state     updated {st.get('updated_utc')} by pid {st.get('pid')} (started {st.get('started_utc')})")
        for name, s in st.get("sources", {}).items():
            on = "ENABLED" if s.get("enabled") else "DISABLED"
            print(f"  {name:14s} {on:8s} last cycle {s.get('last_cycle_utc', '-')}"
                  + (f"  disk floor hit" if s.get("disk_floor") else "")
                  + (f"  working on {s['working_on']}" if s.get("working_on") else ""))
            if not s.get("enabled"):
                print(f"    why: {s.get('reason')}")
            if s.get("pending_days"):
                print(f"    incomplete days: {', '.join(s['pending_days'][-8:])}")
            if s.get("stale"):
                print(f"    !!! NO NEW FILES: newest day held {s.get('newest_day')}")
            if s.get("last_error"):
                print(f"    last error {s.get('last_error_utc')}: {s['last_error'][:160]}")
            if s.get("upstream_not_taken"):
                print(f"    upstream also offers (not taken): "
                      f"{sorted({n.split('_nrt')[0] for v in s['upstream_not_taken'].values() for n in v})}")
    except FileNotFoundError:
        print("state     no state.json yet: the recorder has not completed a cycle")
    for src in _sources(cfg, store, None):
        days = _days(store, src.name)
        last_x = None
        for d in reversed(days):
            if os.path.exists(store.summary_path(src.name, d)):
                last_x = d
                break
        print(f"  {src.name:14s} days held {len(days):3d}, last {days[-1] if days else '-'}, "
              f"last extracted {last_x or '-'}")
    log = store.log_path()
    if os.path.exists(log) and args.lines > 0:
        print(f"--- last lines of {log}")
        with open(log, encoding="utf-8", errors="replace") as fh:
            for line in fh.readlines()[-args.lines:]:
                print("  " + line.rstrip())
    return 0


def _du(path: str) -> int:
    n = 0
    for root, _d, files in os.walk(path):
        for f in files:
            try:
                n += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return n


def cmd_stats(cfg, store, args) -> int:
    print(f"{'source':14s} {'days':>4s} {'complete':>8s} {'raw MB':>8s} {'raw MB/day':>10s} "
          f"{'regions MB/d':>12s} {'global MB/d':>11s} {'epochs/day':>10s} {'dup %':>6s} {'rx':>3s}")
    total_rate = 0.0
    total_x = 0.0
    for src in _sources(cfg, store, None):
        days = _days(store, src.name)
        raw, xb, gb, eps, dups, rxs = [], [], [], [], [], []
        tot = 0
        for d in days:
            man = store.manifest(src.name, d)
            b = sum(r["bytes"] for r in man.values())
            tot += b
            if not src.complete(d, man):
                continue
            raw.append(b)
            s = store.read_summary(src.name, d) if src.extracts else None
            if s:
                xb.append(s.get("rows_bytes", 0))
                gb.append(s.get("global_bytes", 0))
                eps.append(s["totals"]["epochs"])
                dups.append(s["totals"].get("duplicates", 0))
                rxs.append(s["totals"]["receivers"])
        n = len(raw)
        rate = sum(raw) / n / 1e6 if n else 0.0
        xr = sum(xb) / len(xb) / 1e6 if xb else 0.0
        gr = sum(gb) / len(gb) / 1e6 if gb else 0.0
        total_rate += rate
        total_x += xr + gr
        dp = 100 * sum(dups) / (sum(eps) + sum(dups)) if eps else 0.0
        print(f"{src.name:14s} {len(days):4d} {n:8d} {tot / 1e6:8.0f} {rate:10.1f} "
              f"{xr:12.2f} {gr:11.2f} {(sum(eps) / len(eps) if eps else 0):10.0f} {dp:6.1f} "
              f"{(max(rxs) if rxs else 0):3d}")
    raw_now = _du(os.path.join(store.raw_root, "raw"))
    x_now = _du(store.extract_root)
    free = store.free_bytes()
    print(f"\nraw store      {raw_now / 1e9:.2f} GB in {store.raw_root}")
    print(f"extract store  {x_now / 1e6:.1f} MB in {store.extract_root}")
    print(f"measured rate  {total_rate:.0f} MB/day raw, {total_x:.1f} MB/day extract "
          f"(mean over complete days, enabled sources only)")
    print(f"projection     {total_rate * 30 / 1e3:.1f} GB raw and {total_x * 30:.0f} MB extract per 30 days")
    if total_rate > 0:
        days_left = (free - store.min_free) / (total_rate * 1e6)
        print(f"disk           {free / 1e9:.1f} GB free, floor {store.min_free / 1e9:.0f} GB: "
              f"{max(0, days_left):.0f} days of raw before downloads stop")
    return 0


def cmd_verify(cfg, store, args) -> int:
    bad = 0
    files = 0
    for src in _sources(cfg, store, args.source):
        for d in _days(store, src.name):
            for name, rec in sorted(store.manifest(src.name, d).items()):
                p = os.path.join(store.raw_dir(src.name, d), name)
                files += 1
                if not os.path.exists(p):
                    print(f"MISSING  {src.name} {d} {name}")
                    bad += 1
                    continue
                if os.path.getsize(p) != rec["bytes"]:
                    print(f"SIZE     {src.name} {d} {name}: {os.path.getsize(p)} != {rec['bytes']}")
                    bad += 1
                    continue
                if common.sha256_file(p) != rec["sha256"]:
                    print(f"SHA256   {src.name} {d} {name}")
                    bad += 1
            xp = store.extract_path(src.name, d)
            s = store.read_summary(src.name, d)
            if s is None or not os.path.exists(xp):
                continue
            try:
                with gzip.open(xp, "rb") as fh:
                    n = sum(1 for _ in fh)
            except (OSError, EOFError, zlib.error) as exc:
                print(f"GZIP     {src.name} {d} {os.path.basename(xp)}: {exc}")
                bad += 1
                continue
            want = sum(s["totals"]["rows"].values())
            if n != want:
                print(f"ROWS     {src.name} {d}: {n} rows, summary says {want}")
                bad += 1
            gp = store.global_path(src.name, d)
            if s.get("global_file") and os.path.exists(gp):
                try:
                    with gzip.open(gp, "rb") as fh:
                        n = sum(1 for _ in fh)
                except (OSError, EOFError, zlib.error) as exc:
                    print(f"GZIP     {src.name} {d} {os.path.basename(gp)}: {exc}")
                    bad += 1
                    continue
                if n != s["totals"].get("global_rows"):
                    print(f"ROWS     {src.name} {d}: {n} global rows, summary says {s['totals'].get('global_rows')}")
                    bad += 1
    print(f"verify: {files} raw files checked, {bad} problems")
    return 1 if bad else 0


def cmd_gaps(cfg, store, args) -> int:
    since = common.parse_day(args.since or cfg["store"]["history_start"])
    today = common.utcnow().date()
    problems = 0
    for src in _sources(cfg, store, args.source):
        ok, why = src.enabled()
        last_due = today - dt.timedelta(days=LATENCY.get(src.name, 2))
        if not ok:
            print(f"== {src.name}  DISABLED, not counted: {why[:100]}...")
            continue
        print(f"== {src.name}")
        d = since
        held = _days(store, src.name)
        if src.name == "satjam":  # a snapshot: gaps only count from the first capture
            d = max(since, held[0]) if held else last_due + dt.timedelta(days=1)
        while d <= last_due:
            man = store.manifest(src.name, d)
            s = store.read_summary(src.name, d)
            if not man:
                print(f"  {d}  MISSING   nothing downloaded")
                problems += 1
            elif not src.complete(d, man):
                print(f"  {d}  PARTIAL   {len(man)} files held")
                problems += 1
            elif s is None and src.extracts:
                print(f"  {d}  NOT EXTRACTED")
                problems += 1
            if s:
                if s["totals"].get("duplicates"):
                    t = s["totals"]
                    print(f"  {d}  {t['duplicates']} repeated epochs dropped "
                          f"({100 * t['duplicates'] / (t['epochs'] + t['duplicates']):.1f} %), "
                          f"{t.get('duplicates_conflicting', 0)} with different values")
                for rx, r in sorted(s["receivers"].items()):
                    miss = 24 - len(r["hours_utc"])
                    if miss >= args.hours:
                        print(f"  {d}  {rx:12s} no data in {miss:2d} of 24 UTC hours"
                              + (f", {r['no_position']} epochs without orbit" if r["no_position"] else ""))
                if s.get("bad_files"):
                    print(f"  {d}  {len(s['bad_files'])} unreadable files: "
                          f"{', '.join(b['file'] for b in s['bad_files'][:4])}")
            d += dt.timedelta(days=1)
    print(f"gaps: {problems} day-level problems from {since} to the expected publication date")
    return 1 if problems else 0


def cmd_extract(cfg, store, args) -> int:
    day = common.parse_day(args.date)
    locks = []
    if not args.out:
        holder = common.lock_holder(store.extract_root)
        if holder:
            print(f"the recorder (pid {holder}) holds the store. Either write elsewhere with "
                  f"--out DIR, or stop it: systemctl --user stop gnss-leo-recorder")
            return 2
        locks = [common.acquire_lock(store.extract_root), common.acquire_lock(store.raw_root)]
    else:
        os.makedirs(args.out, exist_ok=True)
    common.setup_logging(None)
    rc = 0
    for src in _sources(cfg, store, args.source):
        if not store.manifest(src.name, day):
            print(f"{src.name}: nothing held for {day}")
            continue
        s = src.extract_day(day, out_dir=args.out)
        t = s["totals"]
        print(f"{src.name} {day}: {t['receivers']} receivers, {t['epochs']} epochs, rows {t['rows']}, "
              f"{t['no_position']} without orbit -> {args.out or os.path.dirname(store.extract_path(src.name, day))}")
    del locks
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="gnss_leo_recorder control")
    ap.add_argument("--config")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("status")
    p.add_argument("--lines", type=int, default=12)
    sub.add_parser("stats")
    p = sub.add_parser("verify")
    p.add_argument("--source", choices=list(SOURCES))
    p = sub.add_parser("gaps")
    p.add_argument("--source", choices=list(SOURCES))
    p.add_argument("--since")
    p.add_argument("--hours", type=int, default=6, help="report receivers missing >= N hours")
    p = sub.add_parser("extract")
    p.add_argument("--date", required=True)
    p.add_argument("--source", choices=list(SOURCES))
    p.add_argument("--out", help="write here instead of the store (no lock needed)")
    args = ap.parse_args(argv)
    cfg = common.load_config(args.config)
    store = common.Store(cfg)
    return {"status": cmd_status, "stats": cmd_stats, "verify": cmd_verify, "gaps": cmd_gaps,
            "extract": cmd_extract}[args.cmd](cfg, store, args)


if __name__ == "__main__":
    sys.exit(main())
