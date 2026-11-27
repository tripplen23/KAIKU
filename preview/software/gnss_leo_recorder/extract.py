"""Epochs + orbit -> region rows, a decimated global series and a day summary.
No interpretation, no detection.

Two outputs per source and day, same row format:
  region rows  every epoch whose sub-satellite point falls in a configured box (1 Hz)
  global rows  one epoch per receiver per `global_decimate_s` window (default 10 s,
               0.1 Hz), everywhere; `reg` null outside the boxes, position null when
               the orbit is missing
Duplicate epochs (same receiver, same instant: Spire's pass files overlap) are written
once, the first read; the summary counts them, and how many carried different values.

Row:

  t       UTC, ISO-8601 (converted from the file's GPS time, GPS-UTC = 18 s)
  gps_s   the same instant in GPS seconds since 1980-01-06, exact
  src     source module          rx      receiver satellite ("spire-173", "swarm-A", ...)
  reg     region name            lat/lon/alt_km  sub-satellite point, WGS84
  n_sv    navigation satellites in the epoch record (tracked)
  cn0     {navigation satellite: {observable: value}}: only the S (signal strength)
          observables, RINEX 3 names, file units (dB-Hz in all three sources so far);
          zero or blank values are omitted
  file    upstream file the epoch came from
"""

from __future__ import annotations

import logging

from orbit import geodetic
from rinex import gps_to_unix, iso

LOG = logging.getLogger("gnss_leo.extract")


class Outputs:
    """The writers one extraction feeds: region rows always, global rows if enabled."""

    def __init__(self, region, global_=None, decimate_s: float = 10.0):
        self.region = region
        self.global_ = global_
        self.decimate_s = decimate_s


class DayStats:
    def __init__(self):
        self.receivers: dict[str, dict] = {}
        self.bad_files: list[dict] = []
        self.header_obs_types: dict[str, int] = {}  # "RINEX 3.00 G: C1C,L1C,..." -> files
        self._seen: dict[str, dict[int, int]] = {}  # rx -> {deciseconds: hash of values}
        self._bins: dict[str, set[int]] = {}        # rx -> global windows already written

    def rx(self, rx: str) -> dict:
        r = self.receivers.get(rx)
        if r is None:
            r = self.receivers[rx] = {
                "epochs": 0, "no_position": 0, "rows": {}, "first_gps_s": None,
                "last_gps_s": None, "hours_utc": set(), "cn0_codes": set(), "files": 0,
                "duplicates": 0, "duplicates_conflicting": 0, "global_rows": 0,
            }
        return r

    def saw_header(self, h) -> None:
        for sys_, types in sorted(h.obs_types.items()):
            key = f"RINEX {h.version:.2f} {sys_}: {','.join(types)}"
            if h.crinex:
                key = f"Compact {key}"
            self.header_obs_types[key] = self.header_obs_types.get(key, 0) + 1

    def bad(self, name: str, err: Exception) -> None:
        self.bad_files.append({"file": name, "error": f"{type(err).__name__}: {err}"})
        LOG.warning("%s: %s", name, err)

    def as_dict(self) -> dict:
        rec = {}
        tot = {"epochs": 0, "no_position": 0, "rows": {}, "duplicates": 0,
               "duplicates_conflicting": 0, "global_rows": 0}
        for rx, r in sorted(self.receivers.items()):
            d = dict(r)
            d["hours_utc"] = sorted(r["hours_utc"])
            d["cn0_codes"] = sorted(r["cn0_codes"])
            d["first_utc"] = iso(gps_to_unix(r["first_gps_s"])) if r["first_gps_s"] is not None else None
            d["last_utc"] = iso(gps_to_unix(r["last_gps_s"])) if r["last_gps_s"] is not None else None
            rec[rx] = d
            for k in ("epochs", "no_position", "duplicates", "duplicates_conflicting", "global_rows"):
                tot[k] += r[k]
            for k, v in r["rows"].items():
                tot["rows"][k] = tot["rows"].get(k, 0) + v
        tot["receivers"] = len(rec)
        tot["receivers_in_regions"] = sum(1 for r in rec.values() if r["rows"])
        return {"receivers": rec, "totals": tot, "bad_files": self.bad_files,
                "header_obs_types": self.header_obs_types}


def run_epochs(epochs, eph, rx: str, src: str, fname: str, regions, header, out: Outputs,
               stats: DayStats) -> None:
    """Consume one file's epochs. `eph` may be None (no orbit): epochs count as no_position."""
    r = stats.rx(rx)
    r["files"] += 1
    canon: dict = {}  # per file: (system, code) -> RINEX 3 name
    classify = regions.classify
    rows = r["rows"]
    seen = stats._seen.setdefault(rx, {})
    bins = stats._bins.setdefault(rx, set())
    gw = out.global_
    dec = out.decimate_s
    for gps_s, _flag, sats in epochs:
        key = int(round(gps_s * 10))
        sig = hash(repr(sats))
        prev = seen.get(key)
        if prev is not None:
            r["duplicates"] += 1
            if prev != sig:
                r["duplicates_conflicting"] += 1
            continue
        seen[key] = sig
        r["epochs"] += 1
        if r["first_gps_s"] is None or gps_s < r["first_gps_s"]:
            r["first_gps_s"] = gps_s
        if r["last_gps_s"] is None or gps_s > r["last_gps_s"]:
            r["last_gps_s"] = gps_s
        unix = gps_to_unix(gps_s)
        r["hours_utc"].add(int(unix // 3600) % 24)
        pos = eph.at(gps_s) if eph is not None else None
        if pos is None:
            r["no_position"] += 1
            lat = lon = alt = reg = None
        else:
            lat, lon, alt = geodetic(*pos)
            reg = classify(lat, lon)
        gbin = int(gps_s // dec) if gw is not None else None
        to_global = gbin is not None and gbin not in bins
        if reg is None and not to_global:
            continue
        cn0 = {}
        for sv, vals in sats:
            d = {}
            for code, v in vals.items():
                if not v:
                    continue
                k = (sv[0], code)
                c = canon.get(k)
                if c is None:
                    c = canon[k] = header.canonical(sv[0], code)
                    r["cn0_codes"].add(c)
                d[c] = v
            if d:
                cn0[sv] = d
        row = {
            "t": iso(unix), "gps_s": gps_s, "src": src, "rx": rx, "reg": reg,
            "lat": round(lat, 5) if lat is not None else None,
            "lon": round(lon, 5) if lon is not None else None,
            "alt_km": round(alt, 3) if alt is not None else None,
            "n_sv": len(sats), "cn0": cn0, "file": fname,
        }
        if reg is not None:
            out.region.write(row)
            rows[reg] = rows.get(reg, 0) + 1
        if to_global:
            bins.add(gbin)
            gw.write(row)
            r["global_rows"] += 1


def s_codes(header) -> set[str]:
    """Signal-strength observable codes present in a header (RINEX 2 'S1', RINEX 3 'S1C')."""
    out = set()
    for types in header.obs_types.values():
        out.update(c for c in types if c.startswith("S"))
    return out
