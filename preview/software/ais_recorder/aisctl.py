"""Read-side CLI for the AIS store: summary, stats, integrity, export.

    python3 aisctl.py summary [--date YYYY-MM-DD] [--write]
    python3 aisctl.py stats                      # whole store, disk + projection
    python3 aisctl.py verify                     # gzip CRC over every day file
    python3 aisctl.py track --mmsi 273273150 [--date YYYY-MM-DD]
    python3 aisctl.py export --date YYYY-MM-DD --out tracks.csv [--bbox ...]
    python3 aisctl.py sqlite --out ais.sqlite     # SQL interface for the custody engine (C3)
    python3 aisctl.py gaps [--threshold 1800]     # continuity report against C1

Standard library only. Never writes into raw/.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import store

GULF_OF_FINLAND_BBOX = (22.0, 59.0, 30.5, 60.8)  # lon_min, lat_min, lon_max, lat_max


def _dates_in_store(root: str) -> list[str]:
    out = []
    for p in store.day_files(root, store.STREAM_LOCATIONS):
        out.append(os.path.basename(p).removeprefix("locations-").removesuffix(".ndjson.gz"))
    return out


def _load_day(root: str, stream: str, date: str) -> list[dict]:
    dt = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return list(store.iter_records(store.stream_path(root, stream, dt)))


def _du(root: str, stream: str) -> int:
    return sum(os.path.getsize(p) for p in store.day_files(root, stream))


def cmd_summary(args) -> int:
    root = args.root
    date = args.date or (_dates_in_store(root) or [None])[-1]
    if not date:
        print("no data in store", file=sys.stderr)
        return 1
    locs = _load_day(root, store.STREAM_LOCATIONS, date)
    polls = [p for p in _load_day(root, store.STREAM_POLLLOG, date)
             if p.get("stream") == store.STREAM_LOCATIONS]
    meta = {v["mmsi"]: v for v in _load_day(root, store.STREAM_VESSELS, date) if "mmsi" in v}

    ok = [p for p in polls if p.get("http") in (200, 304)]
    failed = [p for p in polls if p.get("http") == 0]
    mmsis = {r["mmsi"] for r in locs if r.get("mmsi") is not None}

    times = sorted(r["timestampExternal"] for r in locs if r.get("timestampExternal"))
    span_min = (times[-1] - times[0]) / 60000.0 if len(times) > 1 else 0.0

    in_bbox = [r for r in locs if r.get("lon") is not None
               and GULF_OF_FINLAND_BBOX[0] <= r["lon"] <= GULF_OF_FINLAND_BBOX[2]
               and GULF_OF_FINLAND_BBOX[1] <= r["lat"] <= GULF_OF_FINLAND_BBOX[3]]

    moving = [r for r in locs if (r.get("sog") or 0) >= 0.5 and (r.get("sog") or 0) < 102.3]
    slow = [r for r in locs if r.get("sog") is not None and 0.1 <= r["sog"] < 3.0]

    loc_bytes = os.path.getsize(store.stream_path(
        root, store.STREAM_LOCATIONS,
        datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)))

    # Ingest rate must be measured over the recording window, not over the
    # AIS timestamp span: the first poll of a session backfills the upstream
    # 24 h window and would otherwise dominate the statistic.
    written = [p for p in polls if p.get("new")]
    cold_start = written[0]["new"] if written else 0
    if len(written) >= 2:
        win_s = (written[-1]["rx_ms"] - written[0]["rx_ms"]) / 1000.0
        steady_new = sum(p["new"] for p in written[1:])
        steady_rate = round(steady_new / (win_s / 60.0), 1) if win_s else None
    else:
        win_s, steady_new, steady_rate = 0.0, 0, None

    out = {
        "date": date,
        "generated": store.utc_now().isoformat(timespec="seconds"),
        "source": "Fintraffic / digitraffic.fi, licence CC 4.0 BY",
        "polls": {
            "attempted": len(polls),
            "ok": len(ok),
            "http_304_no_change": sum(1 for p in polls if p.get("http") == 304),
            "failed": len(failed),
            "availability_pct": round(100.0 * len(ok) / len(polls), 2) if polls else None,
        },
        "position_reports": len(locs),
        "unique_mmsi": len(mmsis),
        "reports_per_vessel_mean": round(len(locs) / len(mmsis), 2) if mmsis else 0,
        "ais_timestamp_span_minutes": round(span_min, 1),
        "cold_start_backfill_reports": cold_start,
        "steady_state_window_seconds": round(win_s, 1),
        "steady_state_new_reports": steady_new,
        "new_position_reports_per_minute": steady_rate,
        "reports_in_gulf_of_finland_bbox": len(in_bbox),
        "reports_moving_sog_ge_0_5kn": len(moving),
        "reports_slow_0_1_to_3kn": len(slow),
        "vessels_with_metadata": len(meta),
        "disk_bytes_locations_day": loc_bytes,
        "bytes_per_position_report": round(loc_bytes / len(locs), 2) if locs else None,
    }
    text = json.dumps(out, indent=2)
    print(text)
    if args.write:
        d = os.path.join(root, "summary")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, f"{date}.json")
        with open(p, "w") as fh:
            fh.write(text + "\n")
        print(f"\nwritten: {p}", file=sys.stderr)
    return 0


def cmd_stats(args) -> int:
    root = args.root
    dates = _dates_in_store(root)
    if not dates:
        print("no data in store", file=sys.stderr)
        return 1
    totals = {s: _du(root, s) for s in
              (store.STREAM_LOCATIONS, store.STREAM_VESSELS, store.STREAM_POLLLOG)}
    total = sum(totals.values())

    # Projection uses the measured elapsed wall time of the poll log, not the
    # number of calendar days, so a 10-minute test projects honestly.
    polls = []
    for d in dates:
        polls += [p for p in _load_day(root, store.STREAM_POLLLOG, d)
                  if p.get("stream") == store.STREAM_LOCATIONS]
    if len(polls) >= 2:
        elapsed_s = (max(p["rx_ms"] for p in polls) - min(p["rx_ms"] for p in polls)) / 1000.0
        elapsed_s += args.interval  # last cycle counts as a full interval
    else:
        elapsed_s = args.interval

    rate = total / elapsed_s if elapsed_s else 0.0
    print(json.dumps({
        "days_present": dates,
        "bytes": totals,
        "bytes_total": total,
        "elapsed_seconds_measured": round(elapsed_s, 1),
        "bytes_per_hour": round(rate * 3600),
        "projected_MiB_per_day": round(rate * 86400 / 2**20, 1),
        "projected_MiB_per_30_days": round(rate * 86400 * 30 / 2**20, 1),
        "projected_GiB_per_year": round(rate * 86400 * 365 / 2**30, 2),
        "poll_cycles": len(polls),
        "poll_failures": sum(1 for p in polls if p.get("http") == 0),
    }, indent=2))
    return 0


def cmd_verify(args) -> int:
    bad = 0
    for stream in (store.STREAM_LOCATIONS, store.STREAM_VESSELS, store.STREAM_POLLLOG):
        for p in store.day_files(args.root, stream):
            r = store.verify_file(p)
            flag = "OK " if r.get("ok") else "BAD"
            if not r.get("ok"):
                bad += 1
            print(f"{flag} {os.path.relpath(p, args.root)} "
                  f"members={r.get('members')} records={r.get('records')} bytes={r.get('bytes')}")
    print(f"\n{bad} file(s) with a truncated or corrupt tail")
    return 1 if bad else 0


def cmd_track(args) -> int:
    dates = [args.date] if args.date else _dates_in_store(args.root)
    rows = []
    for d in dates:
        for r in _load_day(args.root, store.STREAM_LOCATIONS, d):
            if r.get("mmsi") == args.mmsi:
                rows.append(r)
    rows.sort(key=lambda r: r.get("timestampExternal") or 0)
    for r in rows:
        ts = datetime.fromtimestamp((r.get("timestampExternal") or 0) / 1000, timezone.utc)
        print(f"{ts.isoformat(timespec='seconds')} lat={r.get('lat')} lon={r.get('lon')} "
              f"sog={r.get('sog')} cog={r.get('cog')} nav={r.get('navStat')}")
    print(f"# {len(rows)} fixes for MMSI {args.mmsi}", file=sys.stderr)
    return 0


def cmd_export(args) -> int:
    bbox = tuple(float(x) for x in args.bbox.split(",")) if args.bbox else None
    dates = [args.date] if args.date else _dates_in_store(args.root)
    meta = {}
    for d in dates:
        for v in _load_day(args.root, store.STREAM_VESSELS, d):
            if "mmsi" in v:
                meta[v["mmsi"]] = v
    cols = ["time_utc", "mmsi", "lat", "lon", "sog", "cog", "heading",
            "navStat", "rot", "posAcc", "name", "shipType", "destination", "imo"]
    n = 0
    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for d in dates:
            for r in _load_day(args.root, store.STREAM_LOCATIONS, d):
                if r.get("lon") is None or r.get("lat") is None:
                    continue
                if bbox and not (bbox[0] <= r["lon"] <= bbox[2] and bbox[1] <= r["lat"] <= bbox[3]):
                    continue
                m = meta.get(r.get("mmsi"), {})
                ts = r.get("timestampExternal")
                w.writerow({
                    "time_utc": datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat(
                        timespec="seconds") if ts else "",
                    "mmsi": r.get("mmsi"), "lat": r.get("lat"), "lon": r.get("lon"),
                    "sog": r.get("sog"), "cog": r.get("cog"), "heading": r.get("heading"),
                    "navStat": r.get("navStat"), "rot": r.get("rot"), "posAcc": r.get("posAcc"),
                    "name": (m.get("name") or "").strip(), "shipType": m.get("shipType"),
                    "destination": (m.get("destination") or "").strip(), "imo": m.get("imo"),
                })
                n += 1
    print(f"{n} rows -> {args.out}", file=sys.stderr)
    return 0



def cmd_sqlite(args) -> int:
    """Materialise the store as a SQLite file for C3 (custody engine).

    Interface contract for the custody engine (COO 04_coo.md A.2, C1):
    table `locations(mmsi, t_utc, ts_ms, lat, lon, sog, cog, heading, nav_stat, rot, pos_acc)`
    and `vessels(mmsi, name, ship_type, imo, call_sign, destination, draught, t_ms)`.
    Regenerable at will; the NDJSON remains the source of truth.
    """
    if os.path.exists(args.out):
        os.remove(args.out)
    con = sqlite3.connect(args.out)
    con.executescript("""
        PRAGMA journal_mode=OFF;
        CREATE TABLE locations(mmsi INTEGER, t_utc TEXT, ts_ms INTEGER, lat REAL, lon REAL,
                               sog REAL, cog REAL, heading INTEGER, nav_stat INTEGER,
                               rot INTEGER, pos_acc INTEGER,
                               PRIMARY KEY (mmsi, ts_ms)) WITHOUT ROWID;
        CREATE TABLE vessels(mmsi INTEGER, name TEXT, ship_type INTEGER, imo INTEGER,
                             call_sign TEXT, destination TEXT, draught REAL, t_ms INTEGER);
        CREATE TABLE polls(seq INTEGER, rx_ms INTEGER, http INTEGER, received INTEGER,
                           new INTEGER, error TEXT);
    """)
    dates = [args.date] if args.date else _dates_in_store(args.root)
    n = 0
    for d in dates:
        rows = []
        for r in _load_day(args.root, store.STREAM_LOCATIONS, d):
            ts = r.get("timestampExternal")
            if ts is None or r.get("lat") is None:
                continue
            rows.append((r.get("mmsi"),
                         datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat(timespec="seconds"),
                         ts, r["lat"], r["lon"], r.get("sog"), r.get("cog"),
                         r.get("heading"), r.get("navStat"), r.get("rot"),
                         1 if r.get("posAcc") else 0))
        con.executemany("INSERT OR IGNORE INTO locations VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        n += len(rows)
        con.executemany("INSERT INTO vessels VALUES (?,?,?,?,?,?,?,?)",
                        [(v.get("mmsi"), (v.get("name") or "").strip(), v.get("shipType"),
                          v.get("imo"), (v.get("callSign") or "").strip(),
                          (v.get("destination") or "").strip(), v.get("draught"),
                          v.get("timestamp"))
                         for v in _load_day(args.root, store.STREAM_VESSELS, d) if "mmsi" in v])
        con.executemany("INSERT INTO polls VALUES (?,?,?,?,?,?)",
                        [(p.get("seq"), p.get("rx_ms"), p.get("http"), p.get("received"),
                          p.get("new"), p.get("error"))
                         for p in _load_day(args.root, store.STREAM_POLLLOG, d)
                         if p.get("stream") == store.STREAM_LOCATIONS])
    con.executescript("CREATE INDEX i_loc_t ON locations(ts_ms);"
                      "CREATE INDEX i_loc_m ON locations(mmsi, ts_ms);"
                      "CREATE INDEX i_ves_m ON vessels(mmsi);")
    con.commit()
    q = con.execute("SELECT count(DISTINCT mmsi), count(*), min(t_utc), max(t_utc) FROM locations").fetchone()
    con.close()
    print(json.dumps({"file": args.out, "distinct_mmsi": q[0], "rows": q[1],
                      "t_min": q[2], "t_max": q[3],
                      "bytes": os.path.getsize(args.out)}, indent=2))
    return 0


def cmd_gaps(args) -> int:
    """Continuity report: the C1 acceptance criterion is 'no gap > 30 min'.

    A gap is measured on the POLL LOG, not on the data: the endpoint keeps
    serving a vessel's last fix for ~24 h, so an absence of new fixes is not
    evidence of an outage, but an absence of successful polls is.
    """
    polls = []
    for d in (_dates_in_store(args.root)):
        polls += [p for p in _load_day(args.root, store.STREAM_POLLLOG, d)
                  if p.get("stream") == store.STREAM_LOCATIONS and p.get("http") in (200, 304)]
    polls.sort(key=lambda p: p["rx_ms"])
    if len(polls) < 2:
        print("not enough polls", file=sys.stderr)
        return 1
    gaps = []
    for a, b in zip(polls, polls[1:]):
        dt_s = (b["rx_ms"] - a["rx_ms"]) / 1000.0
        if dt_s > args.threshold:
            gaps.append({
                "from": datetime.fromtimestamp(a["rx_ms"] / 1000, timezone.utc).isoformat(timespec="seconds"),
                "to": datetime.fromtimestamp(b["rx_ms"] / 1000, timezone.utc).isoformat(timespec="seconds"),
                "seconds": round(dt_s),
            })
    total_s = (polls[-1]["rx_ms"] - polls[0]["rx_ms"]) / 1000.0
    lost = sum(g["seconds"] for g in gaps)
    print(json.dumps({
        "window_start": datetime.fromtimestamp(polls[0]["rx_ms"] / 1000, timezone.utc).isoformat(timespec="seconds"),
        "window_end": datetime.fromtimestamp(polls[-1]["rx_ms"] / 1000, timezone.utc).isoformat(timespec="seconds"),
        "window_hours": round(total_s / 3600, 2),
        "successful_polls": len(polls),
        "gap_threshold_seconds": args.threshold,
        "gaps": gaps,
        "total_gap_seconds": lost,
        "coverage_pct": round(100.0 * (1 - lost / total_s), 3) if total_s else None,
    }, indent=2))
    return 0


def main(argv=None) -> int:
    # La ruta del almacen la fija config/custody.toml, igual que para el
    # build y el visor: una sola fuente de verdad. El 2026-11-13 el almacen se
    # movio a Dropbox y este CLI seguia mirando a ./data, asi que informaba
    # «no data in store» sobre 25 MB de grabacion intacta.
    default_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    try:
        import sys as _sys
        _sys.path.insert(0, os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "custody_mvp")))
        from custody import paths as _paths
        default_root = _paths.record() or default_root
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="AIS store query tool")
    ap.add_argument("--root", default=os.environ.get("AIS_DATA_ROOT", default_root))
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("summary"); s.add_argument("--date"); s.add_argument("--write", action="store_true")
    s.set_defaults(func=cmd_summary)
    s = sub.add_parser("stats"); s.add_argument("--interval", type=float, default=60.0)
    s.set_defaults(func=cmd_stats)
    s = sub.add_parser("verify"); s.set_defaults(func=cmd_verify)
    s = sub.add_parser("track"); s.add_argument("--mmsi", type=int, required=True)
    s.add_argument("--date"); s.set_defaults(func=cmd_track)
    s = sub.add_parser("export"); s.add_argument("--date"); s.add_argument("--out", required=True)
    s.add_argument("--bbox", help="lon_min,lat_min,lon_max,lat_max")
    s.set_defaults(func=cmd_export)
    s = sub.add_parser("sqlite"); s.add_argument("--date")
    s.add_argument("--out", default="ais.sqlite"); s.set_defaults(func=cmd_sqlite)
    s = sub.add_parser("gaps"); s.add_argument("--threshold", type=float, default=1800.0)
    s.set_defaults(func=cmd_gaps)

    args = ap.parse_args(argv)
    args.root = os.path.abspath(args.root)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
