"""Swarm A, B and C (ESA), served by swarm-diss.eo.esa.int (no account).

Per satellite and day:
  Level1b/Latest_baselines/GPSx_RO/Sat_X/SW_OPER_GPSX_RO_1B_<day>..ZIP  ~27 MB
      RINEX 3.00, GPS only, 1 s: C1C L1C S1C C1W S1W C2W L2W S2W
  Level1b/Latest_baselines/MODx_SC/Sat_X/SW_OPER_MODX_SC_1B_<day>..ZIP  ~4.3 MB
      SP3-c, 1 s, Earth-fixed: the orbit at every observation epoch, no interpolation
Published ~00:20 UTC four days later (day D appears on D+4).

The server's JSON listing is ordered by name, i.e. by date, from 2013-11-25. It is read
in small pages around the wanted date rather than whole (the whole is ~1 MB per call).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import urllib.parse

from common import HttpError, http_bytes, text_lines, zip_members
from extract import run_epochs, s_codes
from orbit import Ephemeris, read_sp3
from rinex import RinexError, iter_epochs, read_header
from source_base import Remote, Source

_FIRST = dt.date(2013, 11, 25)
_PRODUCTS = {  # listing directory -> file prefix (X = satellite letter)
    "GPSx_RO": "SW_OPER_GPS{X}_RO_1B_",
    "MODx_SC": "SW_OPER_MOD{X}_SC_1B_",
}
_RNX = re.compile(r"^SW_OPER_GPS[A-C]_RO_1B_.*\.rnx$")
_SP3 = re.compile(r"^SW_OPER_MOD[A-C]_SC_1B_.*\.sp3$")
_DATE = re.compile(r"_1B_(\d{8})T")


class Swarm(Source):
    name = "swarm_esa"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._pages: dict[tuple[str, str], dict[str, dict]] = {}
        self._end: set[tuple[str, str]] = set()  # listings read to their last entry

    def sats(self) -> list[str]:
        return list(self.scfg.get("satellites", ["A", "B", "C"]))

    @staticmethod
    def prefix(product: str, sat: str, day: dt.date) -> str:
        return _PRODUCTS[product].replace("{X}", sat) + day.strftime("%Y%m%d")

    def complete(self, day, man) -> bool:
        for sat in self.sats():
            for prod in _PRODUCTS:
                p = self.prefix(prod, sat, day)
                if not any(n.startswith(p) and self.store.have(self.name, day, n, man) for n in man):
                    return False
        return True

    def begin_cycle(self) -> None:
        self._pages.clear()
        self._end.clear()

    def _listing(self, product: str, sat: str, day: dt.date) -> dict[str, dict]:
        """{file name: entry} for a window of dates around `day`, cached per cycle."""
        key = (product, sat)
        cache = self._pages.setdefault(key, {})
        want = day.strftime("%Y%m%d")
        if any(_DATE.search(n) and _DATE.search(n).group(1) == want for n in cache):
            return cache
        if cache:
            dates = sorted(_DATE.search(n).group(1) for n in cache if _DATE.search(n))
            if dates and (dates[0] <= want <= dates[-1] or (want > dates[-1] and key in self._end)):
                return cache  # inside the window and absent, or not published yet
        base = self.scfg["base_url"].rstrip("/")
        folder = f"swarm/Level1b/Latest_baselines/{product}/Sat_{sat}"
        pos = max(0, (day - _FIRST).days - 40)
        page = 80
        for _ in range(8):
            q = urllib.parse.urlencode({"do": "list", "maxfiles": page, "pos": pos, "file": folder})
            status, _ct, body = http_bytes(f"{base}/?{q}", self.ua)
            if status != 200:
                raise HttpError(f"{folder} listing: HTTP {status}", status)
            res = json.loads(body).get("results", [])
            names = [r for r in res if not r.get("is_dir") and _DATE.search(r.get("name", ""))]
            if not names and pos == 0:
                break
            if not names:
                pos = max(0, pos - page)  # past the end of the listing
                continue
            first = _DATE.search(names[0]["name"]).group(1)
            for r in names:
                cache[r["name"]] = r
            if len(res) < page:
                self._end.add(key)
            if first > want and pos > 0:
                pos = max(0, pos - page)
                continue
            break
        return cache

    def remotes(self, day):
        base = self.scfg["base_url"].rstrip("/")
        out = []
        for sat in self.sats():
            for prod in _PRODUCTS:
                p = self.prefix(prod, sat, day)
                cands = sorted(n for n in self._listing(prod, sat, day)
                               if n.startswith(p) and n.upper().endswith(".ZIP"))
                if not cands:
                    continue
                name = cands[-1]  # highest baseline if several
                ent = self._pages[(prod, sat)][name]
                q = urllib.parse.urlencode({"do": "download", "file": ent["path"]})
                out.append(Remote(f"{base}/?{q}", name, ent.get("size")))
        if not out:
            return None
        out.sort(key=lambda r: 0 if "_MOD" in r.name else 1)
        return out

    def extract_into(self, day, man, writer, stats) -> None:
        for sat in self.sats():
            mod = sorted(n for n in man if n.startswith(self.prefix("MODx_SC", sat, day)))
            obs = sorted(n for n in man if n.startswith(self.prefix("GPSx_RO", sat, day)))
            eph = None
            if mod:
                for name, fh in zip_members(self.raw_path(day, mod[-1]), _SP3):
                    try:
                        sats, _ts = read_sp3(text_lines(fh))
                    except RinexError as exc:
                        stats.bad(name, exc)
                        continue
                    if len(sats) == 1:
                        eph = Ephemeris(next(iter(sats.values())), order=9)
                    else:
                        stats.bad(name, RinexError(f"{len(sats)} satellites in a one-receiver SP3"))
            if not obs:
                continue
            for name, fh in zip_members(self.raw_path(day, obs[-1]), _RNX):
                lines = text_lines(fh)
                try:
                    h = read_header(lines)
                    stats.saw_header(h)
                    run_epochs(iter_epochs(lines, h, s_codes(h)), eph, f"swarm-{sat}",
                               self.name, obs[-1], self.regions, h, writer, stats)
                except (RinexError, ValueError, EOFError, OSError) as exc:
                    stats.bad(name, exc)
