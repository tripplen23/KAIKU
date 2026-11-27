"""SAT-JAM (DTU, sat-jam.com): the interference map built from Sentinel-1/2/3 receivers,
captured once a night as the external reference the CTO compares against.

Nine public JSON files, one per satellite and constellation, each a rolling 30-day
aggregate (~2.3 MB each, ~21 MB a night). It is a snapshot: yesterday's version cannot be
fetched today, so only today's capture is attempted, after `after_utc_hour`.
No licence is published; the site asks to be cited. See the MANUAL.
"""

from __future__ import annotations

import json

from common import utcnow
from source_base import Remote, Source


def _json_ok(path: str, name: str) -> None:
    with open(path, "rb") as fh:
        json.loads(fh.read())


class SatJam(Source):
    name = "satjam"
    extracts = False
    validate = staticmethod(_json_ok)

    def complete(self, day, man) -> bool:
        return all(self.store.have(self.name, day, n, man) for n in self.scfg["files"])

    def cycle(self, since, today, full):
        # a snapshot exists only for today
        super().cycle(today, today, full)

    def remotes(self, day):
        now = utcnow()
        if day != now.date() or now.hour < int(self.scfg.get("after_utc_hour", 4)):
            return None
        base = self.scfg["base_url"].rstrip("/")
        return [Remote(f"{base}/{n}", n) for n in self.scfg["files"]]

    def extract_into(self, day, man, out, stats) -> None:
        pass
