"""Sentinel-6A and -6B hourly RINEX (EUMETSAT Data Store, collection EO:EUM:DAT:0274).

What the public catalogue says (no account needed to search):
  product  S6x_GN_1B_RNXH_AX_<start>_<end>_<created>___CPOD_OPE_NR____.SEN6, ~1.07 MB,
           one per satellite and GPS hour, published ~40-50 min after the hour ends
  content  S6xP00EUM_R_<YYYYDDDHHMM>_01H_01S_MO.rnx.gz: RINEX 3, 1 hour, 1 s sampling,
           mixed constellations (MO), gzip, NOT Hatanaka; plus xfdumanifest.xml
  The observable list is only visible inside the file: the parser takes whatever S
  observables the header declares, per system.

Downloading needs a free EUMETSAT account: consumer key and secret, from
~/.config/gnss_leo_recorder/eumetsat.toml or EUMETSAT_CONSUMER_KEY / _SECRET.
Without them this source is disabled and says so; the others are unaffected.

The RINEX carries no position. The orbit comes from the ILRS laser-ranging prediction
(CPF) that EUMETSAT issues daily for both satellites, served openly by EDC (DGFI-TUM):
Earth-fixed positions every 180 s, interpolated to each epoch.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import time
import tomllib
import urllib.parse

from common import HttpError, http_bytes, text_lines, zip_members
from extract import run_epochs, s_codes
from orbit import Ephemeris, read_cpf
from rinex import RinexError, iter_epochs, read_header
from source_base import Remote, Source

_ENTRY = re.compile(r"(S6[AB])P00EUM_R_(\d{4})(\d{3})(\d{2})(\d{2})_01H_\d{2}S_MO\.rnx(\.gz)?$")
_RNX = re.compile(r"^S6[AB]P00EUM_R_\d{11}_01H_\d{2}S_MO\.rnx(\.gz)?$")
_CPF_RE = re.compile(r"^(sentinel6[ab])_cpf_(\d{6})_(\d{3})(\d{2})\.\w+$")
_EDC_INDEX = re.compile(r"(sentinel6[ab]_cpf_\d{6}_\d{5}\.\w+)")

ENV_KEY, ENV_SECRET = "EUMETSAT_CONSUMER_KEY", "EUMETSAT_CONSUMER_SECRET"


def _letter(sat: str) -> str:
    return sat[-1].upper()  # "Sentinel-6A" -> "A"


class Sentinel6(Source):
    name = "sentinel6_eum"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._token: tuple[str, float] | None = None
        self._cpf_index: dict[str, list[str]] = {}

    def sats(self) -> list[str]:
        return list(self.scfg.get("satellites", ["Sentinel-6A", "Sentinel-6B"]))

    # ------------------------------------------------------------------ credentials
    def credentials(self) -> tuple[str, str] | None:
        key, secret = os.environ.get(ENV_KEY), os.environ.get(ENV_SECRET)
        if key and secret:
            return key, secret
        path = os.path.expanduser(self.scfg.get("credentials_file",
                                                "~/.config/gnss_leo_recorder/eumetsat.toml"))
        try:
            with open(path, "rb") as fh:
                d = tomllib.load(fh)
        except FileNotFoundError:
            return None
        except (OSError, tomllib.TOMLDecodeError) as exc:
            self.log.error("cannot read %s: %s", path, exc)
            return None
        if os.stat(path).st_mode & 0o077:
            self.log.warning("%s is readable by other users: chmod 600 it", path)
        key, secret = d.get("consumer_key"), d.get("consumer_secret")
        if key and secret:
            return str(key), str(secret)
        return None

    def enabled(self):
        ok, why = super().enabled()
        if not ok:
            return ok, why
        if self.credentials() is None:
            return False, ("no EUMETSAT credentials: put consumer_key and consumer_secret in "
                           f"{self.scfg.get('credentials_file')} (chmod 600) or set {ENV_KEY} and "
                           f"{ENV_SECRET}; free account at https://eoportal.eumetsat.int, "
                           "key at https://api.eumetsat.int/api-key. See MANUAL Part 0-bis.")
        return True, ""

    def token(self) -> str:
        if self._token and self._token[1] > time.time() + 60:
            return self._token[0]
        key, secret = self.credentials()
        basic = base64.b64encode(f"{key}:{secret}".encode()).decode()
        status, _ct, body = http_bytes(self.scfg["token_url"], self.ua,
                                       headers={"Authorization": f"Basic {basic}",
                                                "Content-Type": "application/x-www-form-urlencoded"},
                                       data=b"grant_type=client_credentials", method="POST")
        if status != 200:
            raise HttpError(f"token endpoint: HTTP {status}", status)
        d = json.loads(body)
        self._token = (d["access_token"], time.time() + float(d.get("expires_in", 3600)))
        return self._token[0]

    # ------------------------------------------------------------------ catalogue
    def search(self, day: dt.date, sat: str) -> list[dict]:
        """Hourly products whose RINEX file starts on `day` (GPS time, from its name)."""
        t0 = dt.datetime.combine(day, dt.time()) - dt.timedelta(hours=1)
        t1 = t0 + dt.timedelta(hours=26)
        q = urllib.parse.urlencode({
            "format": "json", "pi": self.scfg["collection"], "type": self.scfg["product_type"],
            "sat": sat, "dtstart": t0.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "dtend": t1.strftime("%Y-%m-%dT%H:%M:%SZ"), "c": 100, "si": 0})
        status, _ct, body = http_bytes(f"{self.scfg['search_url']}?{q}", self.ua)
        if status != 200:
            raise HttpError(f"search: HTTP {status}", status)
        out = []
        for f in json.loads(body).get("features", []):
            p = f.get("properties", {})
            entries = [e.get("title", "") for e in p.get("links", {}).get("sip-entries", [])]
            rnx = next((e for e in entries if _ENTRY.search(e)), None)
            if not rnx:
                continue
            m = _ENTRY.search(rnx)
            fday = dt.date(int(m.group(2)), 1, 1) + dt.timedelta(days=int(m.group(3)) - 1)
            if fday != day:
                continue
            data = p.get("links", {}).get("data", [{}])[0].get("href")
            out.append({"id": p["identifier"], "href": data, "entry": rnx.split("/")[-1],
                        "md5": (p.get("extraInformation") or {}).get("md5"),
                        "size": int(p.get("productInformation", {}).get("size", 0)) * 1000,
                        "hour": int(m.group(4))})
        return out

    def _cpf_names(self, sat: str, year: int) -> list[str]:
        key = f"{sat}/{year}"
        if key not in self._cpf_index:
            obj = f"sentinel6{_letter(sat).lower()}"
            url = f"{self.scfg['orbit_url'].rstrip('/')}/{year}/{obj}/"
            status, _ct, body = http_bytes(url, self.ua)
            names = sorted(set(_EDC_INDEX.findall(body.decode("utf-8", "replace")))) if status == 200 else []
            self._cpf_index[key] = names
        return self._cpf_index[key]

    def cpf_for(self, sat: str, day: dt.date) -> tuple[str, str] | None:
        """(url, name) of the newest prediction issued on `day`, else up to 3 days before."""
        cands = []
        for year in {day.year, (day - dt.timedelta(days=3)).year}:
            for n in self._cpf_names(sat, year):
                m = _CPF_RE.match(n)
                issued = dt.datetime.strptime(m.group(2), "%y%m%d").date()
                if day - dt.timedelta(days=3) <= issued <= day:
                    cands.append((issued, n, year))
        if not cands:
            return None
        issued, name, year = max(cands)
        obj = f"sentinel6{_letter(sat).lower()}"
        return f"{self.scfg['orbit_url'].rstrip('/')}/{year}/{obj}/{name}", name

    def begin_cycle(self) -> None:
        self._cpf_index.clear()

    # ------------------------------------------------------------------ Source API
    def complete(self, day, man) -> bool:
        per_sat = {}
        for n in man:
            m = re.match(r"^S6([AB])_GN_1B_RNXH", n)
            if m and self.store.have(self.name, day, n, man):
                per_sat[m.group(1)] = per_sat.get(m.group(1), 0) + 1
        cpf = {m.group(1)[-1].upper() for n in man if (m := _CPF_RE.match(n))}
        return all(per_sat.get(_letter(s), 0) >= 24 and _letter(s) in cpf for s in self.sats())

    def remotes(self, day):
        out = []
        tok = None
        man = self.store.manifest(self.name, day)
        for sat in self.sats():
            prods = self.search(day, sat)
            if not prods:
                continue
            held_cpf = any((m := _CPF_RE.match(n)) and m.group(1)[-1].upper() == _letter(sat)
                           for n in man)
            cpf = None if held_cpf else self.cpf_for(sat, day)
            if cpf:
                out.append(Remote(cpf[0], cpf[1], None, extra={
                    "licence": self.scfg["orbit_licence"], "terms_url": self.scfg["orbit_terms_url"]}))
            tok = tok or self.token()
            for p in prods:
                out.append(Remote(p["href"], p["id"] + ".zip", p["size"], md5=p["md5"],
                                  headers={"Authorization": f"Bearer {tok}"},
                                  extra={"product_id": p["id"], "rinex_entry": p["entry"]}))
        return out or None

    def extract_into(self, day, man, writer, stats) -> None:
        for sat in self.sats():
            L = _letter(sat)
            cpfs = sorted((n for n in man if (m := _CPF_RE.match(n)) and m.group(1)[-1].upper() == L),
                          key=lambda n: _CPF_RE.match(n).group(2) + _CPF_RE.match(n).group(4))
            eph = None
            if cpfs:
                with open(self.raw_path(day, cpfs[-1]), "rb") as fh:
                    try:
                        _name, samples = read_cpf(text_lines(fh))
                        eph = Ephemeris(samples, order=9)
                    except RinexError as exc:
                        stats.bad(cpfs[-1], exc)
            for zname in sorted(n for n in man if n.startswith(f"S6{L}_GN_1B_RNXH")):
                for name, fh in zip_members(self.raw_path(day, zname), _RNX):
                    lines = text_lines(fh, gz=name.endswith(".gz"))
                    try:
                        h = read_header(lines)
                        stats.saw_header(h)
                        run_epochs(iter_epochs(lines, h, s_codes(h)), eph, f"sentinel6-{L}",
                                   self.name, zname, self.regions, h, writer, stats)
                    except (RinexError, ValueError, EOFError, OSError) as exc:
                        stats.bad(name, exc)
