"""Spire navigation-receiver data bought by NOAA, served by UCAR COSMIC (no account).

  level1a/YYYY/DDD/podCrx_nrt_YYYY_DDD.tar.gz   ~90 MB  one Compact RINEX 2.11 file per
                                                         receiver pass (S1C, S2L as S1, S2)
  level1b/YYYY/DDD/leoOrb_nrt_YYYY_DDD.tar.gz   ~2.5 MB one SP3 orbit per pass, 60 s step

Optional, off by default (config `products`): level1a leoAtt (attitude, ~80 MB/day).
Not taken: opnGns (~2 GB/day, raw occultation), conPhs (~1 GB), podTec (~545 MB, netCDF).
Published once a day, ~07:40 UTC the next day.
"""

from __future__ import annotations

import datetime as dt
import re

from common import HttpError, http_bytes, tar_members, text_lines
from extract import run_epochs, s_codes
from orbit import Ephemeris, read_sp3
from rinex import RinexError, iter_epochs, read_header
from source_base import Remote, Source

_POD = re.compile(r"^podCrx_\d{4}\.\d{3}\.(\d{3})\.(\d{2})\.\d{2}_crx(\.gz)?$")
_ORB = re.compile(r"^leoOrb_\d{4}\.\d{3}\.(\d{3})\.(\d{2})_\d{4}\.\d{4}_sp3$")
_INDEX = re.compile(r'href="([A-Za-z0-9_.\-]+)">[^<]*</a>\s+(\S+ \S+)\s+(\S+)')
_UNIT = {"K": 1e3, "M": 1e6, "G": 1e9}


def _size(s: str) -> int | None:
    try:
        if s[-1] in _UNIT:
            return int(float(s[:-1]) * _UNIT[s[-1]])
        return int(s)
    except (ValueError, IndexError):
        return None


class Spire(Source):
    name = "spire_ucar"

    NEVER = {"opnGns"}  # ~2 GB/day of open-loop occultation samples: refused even if configured

    def products(self) -> list[tuple[str, str]]:
        """[(level, stem)] e.g. [('level1a', 'podCrx'), ('level1b', 'leoOrb')]."""
        out = []
        for p in self.scfg.get("products", ["level1a/podCrx", "level1b/leoOrb"]):
            level, stem = p.split("/", 1)
            if stem in self.NEVER:
                if not self.state.get("refused"):
                    self.log.error("%s is in products but never downloaded (~2 GB/day); "
                                   "remove it from gnss_leo.toml", p)
                self.state["refused"] = p
                continue
            out.append((level, stem))
        return out

    @staticmethod
    def fname(stem: str, day: dt.date) -> str:
        return f"{stem}_nrt_{day.year}_{day.timetuple().tm_yday:03d}.tar.gz"

    def complete(self, day, man) -> bool:
        return all(self.store.have(self.name, day, self.fname(stem, day), man)
                   for _, stem in self.products())

    def remotes(self, day):
        base = self.scfg["base_url"].rstrip("/")
        out = []
        listed_any = False
        for level in sorted({lv for lv, _ in self.products()}):
            url = f"{base}/{level}/{day.year}/{day.timetuple().tm_yday:03d}/"
            status, _ct, body = http_bytes(url, self.ua)
            if status == 404:
                continue
            if status != 200:
                raise HttpError(f"{url}: HTTP {status}", status)
            listed_any = True
            index = {m.group(1): _size(m.group(3)) for m in _INDEX.finditer(body.decode("utf-8", "replace"))}
            for lv, stem in self.products():
                name = self.fname(stem, day)
                if lv == level and name in index:
                    out.append(Remote(url + name, name, index[name]))
            others = sorted(n for n in index if n.endswith(".tar.gz")
                            and not any(n == self.fname(s, day) for _, s in self.products()))
            self.state.setdefault("upstream_not_taken", {})[level] = others
        if not listed_any:
            return None
        # orbit first: small, and the observations are useless without it
        out.sort(key=lambda r: 0 if r.name.startswith("leoOrb") else 1)
        return out

    def extract_into(self, day, man, writer, stats) -> None:
        orb_name = self.fname("leoOrb", day)
        pod_name = self.fname("podCrx", day)
        samples: dict[str, dict] = {}
        if orb_name in man:
            for name, fh in tar_members(self.raw_path(day, orb_name), _ORB):
                fm = _ORB.match(name).group(1)
                try:
                    sats, _ts = read_sp3(text_lines(fh))
                except RinexError as exc:
                    stats.bad(name, exc)
                    continue
                if len(sats) != 1:
                    stats.bad(name, RinexError(f"{len(sats)} satellites in a one-receiver SP3"))
                    continue
                samples.setdefault(fm, {}).update(next(iter(sats.values())))
        ephs = {fm: Ephemeris(s, order=9) for fm, s in samples.items()}
        if pod_name not in man:
            return
        for name, fh in tar_members(self.raw_path(day, pod_name), _POD):
            fm = _POD.match(name).group(1)
            lines = text_lines(fh, gz=name.endswith(".gz"))
            try:
                h = read_header(lines)
                stats.saw_header(h)
                run_epochs(iter_epochs(lines, h, s_codes(h)), ephs.get(fm), f"spire-{fm}",
                           self.name, name, self.regions, h, writer, stats)
            except (RinexError, ValueError, EOFError, OSError) as exc:
                stats.bad(name, exc)
