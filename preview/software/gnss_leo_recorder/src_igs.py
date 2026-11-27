"""Navigation-satellite orbits, daily: what the CTO needs to compute each GPS/Galileo
satellite's elevation as seen from the receiver. Stored, not used by the extractor.

  IGS0OPSRAP  IGS rapid combination, GPS only, 15 min, ~100 kB/day   (BKG mirror)
  GFZ0OPSRAP  GFZ rapid, GPS + Galileo + GLONASS, 5 min, ~670 kB/day  (GFZ ISDC)
IGS's own rapid product has no Galileo, hence the second file. Both appear ~17 h after
the day ends. No account. Directory per GPS week; the week index is read once a cycle.
"""

from __future__ import annotations

import datetime as dt

from common import HttpError, http_bytes
from source_base import Remote, Source

_GPS0 = dt.date(1980, 1, 6)


def gps_week(day: dt.date) -> int:
    return (day - _GPS0).days // 7


class IgsOrbits(Source):
    name = "igs_orbits"
    extracts = False

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._index: dict[str, str] = {}

    def begin_cycle(self) -> None:
        self._index.clear()

    def _names(self, day: dt.date) -> list[tuple[str, str]]:
        """[(directory URL, file name)] for the configured products."""
        out = []
        for p in self.scfg["products"]:
            f = dict(yyyy=f"{day.year}", ddd=f"{day.timetuple().tm_yday:03d}", week=gps_week(day))
            out.append((p["dir"].format(**f), p["name"].format(**f)))
        return out

    def complete(self, day, man) -> bool:
        return all(self.store.have(self.name, day, n, man) for _, n in self._names(day))

    def remotes(self, day):
        out = []
        for d, n in self._names(day):
            if d not in self._index:
                status, _ct, body = http_bytes(d, self.ua)
                if status not in (200, 404):
                    raise HttpError(f"{d}: HTTP {status}", status)
                self._index[d] = body.decode("utf-8", "replace") if status == 200 else ""
            if n in self._index[d]:
                out.append(Remote(d + n, n))
        return out or None

    def extract_into(self, day, man, out, stats) -> None:
        pass
