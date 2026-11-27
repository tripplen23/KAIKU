"""What every source module shares: the day loop, download bookkeeping, extraction driver.

A source module subclasses `Source` and implements four things:
  complete(day, man)   are all expected files for the day already held? (no network)
  remotes(day)         what upstream offers for the day: [Remote], or None if not yet
  extract_into(day, man, writer, stats)   read the held files, write region rows
  enabled()            (bool, reason)
Everything else (manifest, disk floor, idempotence, summaries) is here, once.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import time
from dataclasses import dataclass, field

import common
from common import (EXTRACTOR_VERSION, DiskFloor, HttpError, NdjsonGzWriter, atomic_write_json,
                    check_archive, doy, download, now_iso, shout)
from extract import DayStats, Outputs


@dataclass
class Remote:
    url: str
    name: str
    size: int | None = None          # bytes, if upstream says (used for the disk floor)
    md5: str | None = None
    extra: dict = field(default_factory=dict)  # copied into the manifest record
    headers: dict = field(default_factory=dict)


class Source:
    name = ""
    extracts = True                      # False: download and keep, nothing to extract
    validate = staticmethod(check_archive)  # run on the .part before it is accepted

    def __init__(self, cfg: dict, store: common.Store, regions: common.Regions, stop=lambda: False):
        self.cfg = cfg
        self.scfg = cfg["sources"][self.name]
        self.store = store
        self.regions = regions
        self.stop = stop
        self.ua = cfg["store"]["user_agent"]
        self.licence = self.scfg["licence"]
        self.terms_url = self.scfg["terms_url"]
        self.poll_s = 60 * float(self.scfg.get("poll_minutes", 60))
        self.lookback = int(self.scfg.get("lookback_days", 10))
        self.log = logging.getLogger(f"gnss_leo.{self.name}")
        self.state: dict = {"source": self.name}
        self.progress = lambda: None  # called after every day; the daemon writes state.json

    # ------------------------------------------------------------------ to implement
    def enabled(self) -> tuple[bool, str]:
        if not self.scfg.get("enabled", True):
            return False, "enabled = false in gnss_leo.toml"
        return True, ""

    def complete(self, day: dt.date, man: dict) -> bool:
        raise NotImplementedError

    def remotes(self, day: dt.date) -> list[Remote] | None:
        raise NotImplementedError

    def extract_into(self, day: dt.date, man: dict, writer, stats: DayStats) -> None:
        raise NotImplementedError

    def begin_cycle(self) -> None:
        """Drop per-cycle caches (upstream listings)."""

    # ------------------------------------------------------------------ shared
    def raw_path(self, day: dt.date, name: str) -> str:
        return os.path.join(self.store.raw_dir(self.name, day), name)

    def fetch_day(self, day: dt.date) -> int:
        """Download what is missing for `day`. Returns files downloaded. Raises DiskFloor."""
        man = self.store.manifest(self.name, day)
        rems = self.remotes(day)
        if rems is None:
            self.log.debug("%s: not published yet", day)
            return 0
        n = 0
        for rem in rems:
            if self.stop():
                break
            if self.store.have(self.name, day, rem.name, man):
                continue
            self.store.check_floor(rem.size or 0)
            rec = download(rem.url, self.store.raw_dir(self.name, day), rem.name, self.ua,
                           headers=rem.headers or None, expect_md5=rem.md5, stop=self.stop,
                           validate=self.validate)
            rec.update({"source": self.name, "day": day.isoformat(), "doy": doy(day),
                        "licence": self.licence, "terms_url": self.terms_url})
            rec.update(rem.extra)
            self.store.append_manifest(self.name, day, rec)
            man[rem.name] = rec
            n += 1
            self.log.info("%s: %s %.1f MB in %.0f s", day, rem.name, rec["bytes"] / 1e6, rec["seconds"])
            time.sleep(1.0)  # one file at a time, politely
        return n

    def needs_extract(self, day: dt.date, man: dict) -> bool:
        if not man or not self.extracts:
            return False
        s = self.store.read_summary(self.name, day)
        if s is None or s.get("extractor") != EXTRACTOR_VERSION:
            return True
        have = {(r["file"], r["sha256"]) for r in s.get("inputs", [])}
        now = {(r["file"], r["sha256"]) for r in man.values()
               if os.path.exists(self.raw_path(day, r["file"]))}
        return have != now

    def extract_day(self, day: dt.date, out_dir: str | None = None) -> dict:
        """Write region rows, global rows and the summary for `day`. `out_dir`: outside the store."""
        man = self.store.manifest(self.name, day)
        inputs = [{"file": r["file"], "sha256": r["sha256"], "bytes": r["bytes"]}
                  for r in sorted(man.values(), key=lambda r: r["file"])
                  if os.path.exists(self.raw_path(day, r["file"]))]
        paths = {"rows": self.store.extract_path(self.name, day),
                 "global": self.store.global_path(self.name, day),
                 "summary": self.store.summary_path(self.name, day)}
        if out_dir:
            paths = {k: os.path.join(out_dir, os.path.basename(v)) for k, v in paths.items()}
        dec = float(self.cfg.get("extract", {}).get("global_decimate_s", 10))
        t0 = time.time()
        stats = DayStats()
        rw = NdjsonGzWriter(paths["rows"])
        gw = NdjsonGzWriter(paths["global"]) if dec > 0 else None
        try:
            self.extract_into(day, man, Outputs(rw, gw, dec or 10.0), stats)
        except BaseException:
            rw.abort()
            if gw:
                gw.abort()
            raise
        rw.close()
        if gw:
            gw.close()
        summary = {
            "source": self.name, "day": day.isoformat(), "doy": doy(day),
            "extractor": EXTRACTOR_VERSION, "generated_utc": now_iso(),
            "seconds": round(time.time() - t0, 1),
            "inputs": inputs, "raw_bytes": sum(i["bytes"] for i in inputs),
            "complete": self.complete(day, man),
            "rows_file": os.path.basename(paths["rows"]), "rows_bytes": os.path.getsize(paths["rows"]),
            "global_file": os.path.basename(paths["global"]) if gw else None,
            "global_bytes": os.path.getsize(paths["global"]) if gw else 0,
            "global_decimate_s": dec,
            "regions": {k: {"lat": v["lat"], "lon": v["lon"]} for k, v in self.cfg.get("regions", {}).items()},
            "licence": self.licence, "terms_url": self.terms_url,
        }
        summary.update(stats.as_dict())
        atomic_write_json(paths["summary"], summary)
        t = summary["totals"]
        self.log.info("%s: extracted %d receivers, %d epochs (+%d duplicates, %d conflicting), "
                      "rows %s, global %d, %d without position, %d bad files, %.0f s",
                      day, t["receivers"], t["epochs"], t["duplicates"], t["duplicates_conflicting"],
                      t["rows"], t["global_rows"], t["no_position"], len(summary["bad_files"]),
                      summary["seconds"])
        return summary

    def cycle(self, since: dt.date, today: dt.date, full: bool) -> None:
        """One pass over [since, today]. Network only for incomplete days inside the
        lookback window, or for every incomplete day when `full` (startup, --since)."""
        ok, why = self.enabled()
        self.state.update({"enabled": ok, "reason": why, "last_cycle_utc": now_iso()})
        if not ok:
            return
        self.begin_cycle()
        floor_hit = False
        pending = []
        day = since
        while day <= today and not self.stop():
            try:
                man = self.store.manifest(self.name, day)
                if not self.complete(day, man) and not floor_hit and \
                        (full or day >= today - dt.timedelta(days=self.lookback)):
                    try:
                        self.fetch_day(day)
                    except DiskFloor as exc:
                        floor_hit = True
                        shout(f"DISK FLOOR - raw downloads STOPPED for {self.name}: {exc}. "
                              f"Nothing is deleted automatically; free space or move "
                              f"{self.store.raw_root}.")
                    except HttpError as exc:
                        self.log.warning("%s: %s", day, exc)
                        self.state.update({"last_error": str(exc), "last_error_utc": now_iso()})
                    man = self.store.manifest(self.name, day)
                if self.stop():
                    break
                if man and self.needs_extract(day, man):
                    self.extract_day(day)
                if not self.complete(day, man):
                    pending.append(day.isoformat())
            except Exception as exc:  # noqa: BLE001 - one bad day must not stop the others
                self.log.exception("%s: %s", day, exc)
                self.state.update({"last_error": f"{day}: {type(exc).__name__}: {exc}",
                                   "last_error_utc": now_iso()})
            day += dt.timedelta(days=1)
            self.state["working_on"] = day.isoformat() if day <= today else None
            self.progress()
        self.state.update({"pending_days": pending[-30:], "disk_floor": floor_hit,
                           "last_ok_utc": now_iso()})
        if not self.stop():  # an interrupted pass has not seen the newest days yet
            self.check_stale(today)

    def check_stale(self, today: dt.date) -> None:
        """Warn when upstream stops publishing: newest day held older than `stale_after_days`."""
        limit = self.scfg.get("stale_after_days")
        if not limit:
            return
        held = self.store.days_held(self.name)
        newest = held[-1] if held else None
        age = (today - newest).days if newest else None
        stale = age is None or age > int(limit)
        self.state.update({"newest_day": newest.isoformat() if newest else None, "stale": stale})
        if stale:
            self.log.warning("NO NEW FILES: newest day held is %s (%s days ago, limit %s). %s",
                             newest, age, limit, self.scfg.get("stale_note", ""))
