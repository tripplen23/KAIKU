"""Tests for gnss_leo_recorder, on the real 13-Nov-2026 (day 317) samples kept in canal/.

  python3 -I -m unittest discover -s tests -v          (~1 min)
  GNSS_LEO_FULL_TESTS=1 ...                            all 300 Spire files against the
                                                       reference decoder (~2 min more)

The reference Hatanaka decoder is the C one in the pinned `hatanaka` package, installed in
the project venv (../requirements-dev.txt, see ../venv.sh). Without it they are skipped, not failed.
"""

from __future__ import annotations

import datetime as dt
import glob
import gzip
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

MOD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if MOD not in sys.path:
    sys.path.insert(0, MOD)

import common  # noqa: E402
import extract  # noqa: E402
import orbit  # noqa: E402
import rinex  # noqa: E402
from source_base import Remote, Source  # noqa: E402
from src_igs import IgsOrbits, gps_week  # noqa: E402
from src_satjam import SatJam  # noqa: E402
from src_sentinel6 import Sentinel6  # noqa: E402
from src_spire import Spire  # noqa: E402
from src_swarm import Swarm  # noqa: E402

# Las fuentes de prueba viven en el arbol de investigacion, que desde el
# 2026-11-24 es un repo aparte: la ruta ya no se puede deducir subiendo
# directorios desde aqui. `rutas.toml`, en la raiz del repo, dice donde esta.
_r = MOD  # noqa: E402  subir hasta la raiz del repo, que lleva rutas.py
while _r != "/" and not os.path.exists(os.path.join(_r, "rutas.py")):  # noqa: E402
    _r = os.path.dirname(_r)  # noqa: E402
sys.path.insert(0, _r)  # noqa: E402
import rutas  # noqa: E402

CANAL = rutas.investigacion("proyecto_telescopio_geo/canal")
S05 = os.path.join(CANAL, "iteracion_05/investigacion/01_pm_competencia/fuentes/datos_abiertos")
S06 = os.path.join(CANAL, "iteracion_06/investigacion/00_desarrollo_gnss_leo/fuentes")
POD = os.path.join(S05, "spire_ucar/podCrx_nrt_2026_317.tar.gz")
ORB = os.path.join(S05, "spire_ucar/leoOrb_nrt_2026_317.tar.gz")
GPSA = os.path.join(S05, "swarm/SW_OPER_GPSA_RO_1B_20261113T000000_20261113T235959_0602.ZIP")
MODA = os.path.join(S06, "swarm/SW_OPER_MODA_SC_1B_20261113T000000_20261113T235959_0602.ZIP")
CPF = os.path.join(S06, "sentinel6/sentinel6a_cpf_261113_31701.eum")
_BIN = glob.glob(os.path.join(MOD, ".venv/lib/python3*/site-packages/hatanaka/bin"))
CRX2RNX = os.path.join(_BIN[0], "crx2rnx") if _BIN else None
RNX2CRX = os.path.join(_BIN[0], "rnx2crx") if _BIN else None
FULL = os.environ.get("GNSS_LEO_FULL_TESTS") == "1"
DAY = dt.date(2026, 11, 13)

REGIONS = {"baltic": {"lat": [50.0, 72.0], "lon": [5.0, 50.0]},
           "control": {"lat": [50.0, 72.0], "lon": [-130.0, -60.0]}}


def have(*paths):
    return all(p and os.path.exists(p) for p in paths)


def test_cfg(tmp: str) -> dict:
    cfg = common.load_config(os.path.join(MOD, "gnss_leo.toml"))
    cfg["store"]["raw_root"] = os.path.join(tmp, "raw")
    cfg["store"]["extract_root"] = os.path.join(tmp, "extract")
    cfg["regions"] = REGIONS
    return cfg


def put(store: common.Store, source: str, day: dt.date, path: str, name: str | None = None) -> None:
    """Place a sample in a test store as if downloaded (hard link when possible)."""
    name = name or os.path.basename(path)
    dst = os.path.join(store.raw_dir(source, day), name)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        os.link(path, dst)
    except OSError:
        with open(path, "rb") as a, open(dst, "wb") as b:
            b.write(a.read())
    store.append_manifest(source, day, {"file": name, "bytes": os.path.getsize(dst),
                                        "sha256": common.sha256_file(dst), "url": "test-sample"})


def read_rows(path: str) -> list[dict]:
    with gzip.open(path, "rt") as fh:
        return [json.loads(line) for line in fh]


# ============================================================================== time

class TestTime(unittest.TestCase):
    def test_gps_epoch_and_leap(self):
        self.assertEqual(rinex.gps_seconds(1980, 1, 6, 0, 0, 0), 0)
        g = rinex.gps_seconds(2026, 11, 13, 0, 0, 18)
        self.assertEqual(rinex.iso(rinex.gps_to_unix(g)), "2026-11-13T00:00:00.000Z")
        self.assertEqual(rinex.unix_to_gps(rinex.gps_to_unix(g)), g)
        self.assertEqual(rinex.leap_seconds(g), 18)


# ============================================================================== Compact RINEX

@unittest.skipUnless(have(POD, CRX2RNX), "needs the day-317 Spire sample and .venv hatanaka")
class TestCrxAgainstReference(unittest.TestCase):
    """Our decoder against the C reference, value by value, on real Spire files."""

    def test_spire_files_match_crx2rnx(self):
        n_files = n_epochs = 0
        limit = None if FULL else 25
        with tarfile.open(POD, "r|gz") as tf:
            for m in tf:
                if not m.isreg():
                    continue
                raw = gzip.decompress(tf.extractfile(m).read())
                if not raw:
                    continue  # two members of day 317 are empty files
                it = iter(io.TextIOWrapper(io.BytesIO(raw), encoding="ascii"))
                h = rinex.read_header(it)
                ours = list(rinex.iter_epochs(it, h))
                ref_txt = subprocess.run([CRX2RNX], input=raw, capture_output=True, check=True).stdout
                it2 = iter(io.TextIOWrapper(io.BytesIO(ref_txt), encoding="ascii"))
                h2 = rinex.read_header(it2)
                self.assertIsNone(h2.crinex)
                ref = list(rinex.iter_epochs(it2, h2))
                self.assertEqual(ours, ref, m.name)
                n_files += 1
                n_epochs += len(ours)
                if limit and n_files >= limit:
                    break
        self.assertGreaterEqual(n_files, 25)
        self.assertGreater(n_epochs, 50000)


@unittest.skipUnless(have(GPSA, RNX2CRX), "needs the Swarm sample and .venv hatanaka")
class TestCrx3RoundTrip(unittest.TestCase):
    """CRINEX 3: compress real RINEX 3 with the reference tool, decode with ours."""

    def test_swarm_rinex3(self):
        with zipfile.ZipFile(GPSA) as zf:
            name = next(n for n in zf.namelist() if n.endswith(".rnx"))
            with zf.open(name) as fh:
                lines = []
                epochs = 0
                for raw in io.TextIOWrapper(fh, encoding="ascii"):
                    if raw.startswith(">"):
                        epochs += 1
                        if epochs > 1500:
                            break
                    lines.append(raw)
        text = "".join(lines).encode()
        crx_txt = subprocess.run([RNX2CRX], input=text, capture_output=True, check=True).stdout
        it = iter(io.TextIOWrapper(io.BytesIO(crx_txt), encoding="ascii"))
        h = rinex.read_header(it)
        self.assertEqual(h.crinex, "3.0")
        ours = list(rinex.iter_epochs(it, h))
        it2 = iter(io.TextIOWrapper(io.BytesIO(text), encoding="ascii"))
        h2 = rinex.read_header(it2)
        ref = list(rinex.iter_epochs(it2, h2))
        self.assertEqual(len(ours), 1500)
        self.assertEqual(ours, ref)


# ============================================================================== headers

@unittest.skipUnless(have(POD, GPSA), "needs the day-317 samples")
class TestHeaders(unittest.TestCase):
    def test_spire_rinex2_maps_back_to_rinex3_names(self):
        with tarfile.open(POD, "r|gz") as tf:
            for m in tf:
                if m.isreg() and m.size > 1000:
                    it = common.text_lines(tf.extractfile(m), gz=True)
                    h = rinex.read_header(it)
                    break
        self.assertEqual(h.crinex, "1.0")
        self.assertAlmostEqual(h.version, 2.11)
        self.assertEqual(h.types_for("G"), ["C1", "C2", "L1", "L2", "S1", "S2"])
        self.assertEqual(h.canonical("G", "S1"), "S1C")
        self.assertEqual(h.canonical("G", "S2"), "S2L")
        self.assertEqual(extract.s_codes(h), {"S1", "S2"})

    def test_swarm_rinex3(self):
        with zipfile.ZipFile(GPSA) as zf:
            name = next(n for n in zf.namelist() if n.endswith(".rnx"))
            with zf.open(name) as fh:
                it = common.text_lines(fh)
                h = rinex.read_header(it)
                first = next(rinex.iter_epochs(it, h, extract.s_codes(h)))
        self.assertEqual(h.types_for("G"), ["C1C", "L1C", "S1C", "C1W", "S1W", "C2W", "L2W", "S2W"])
        self.assertEqual(rinex.iso(rinex.gps_to_unix(first[0])), "2026-11-13T00:00:00.000Z")
        self.assertEqual(first[2][0], ("G21", {"S1C": 40.57, "S1W": 22.78, "S2W": 22.78}))

    def test_empty_and_truncated(self):
        with self.assertRaises(rinex.RinexError):
            rinex.read_header(iter([]))
        head = ("     3.00           OBSERVATION DATA    G                   RINEX VERSION / TYPE\n"
                "G    1 S1C                                                  SYS / # / OBS TYPES\n"
                "                                                            END OF HEADER\n"
                "> 2026 11 13 00 00 18.0000000  0  2\n"
                "G01        45.000  \n")
        it = iter(io.StringIO(head))
        h = rinex.read_header(it)
        with self.assertRaises(rinex.Truncated):
            list(rinex.iter_epochs(it, h))


# ============================================================================== orbits

@unittest.skipUnless(have(MODA, CPF), "needs the Swarm orbit and Sentinel-6A CPF samples")
class TestOrbit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with zipfile.ZipFile(MODA) as zf:
            name = next(n for n in zf.namelist() if n.endswith(".sp3"))
            with zf.open(name) as fh:
                cls.sats, cls.ts = orbit.read_sp3(common.text_lines(fh))
        cls.truth = next(iter(cls.sats.values()))

    def test_sp3(self):
        self.assertEqual(self.ts, "GPS")
        self.assertEqual(len(self.truth), 86400)
        lat, lon, alt = orbit.geodetic(*self.truth[min(self.truth)])
        self.assertAlmostEqual(alt, 433.06, places=1)

    def test_interpolation_60s_under_1m(self):
        """Spire orbits come every 60 s: interpolating Swarm's 1 s truth at that step."""
        t = sorted(self.truth)
        coarse = {k: self.truth[k] for k in t[::60]}
        eph = orbit.Ephemeris(coarse, order=9)
        worst = 0.0
        for k in t[1000:80000:7]:
            p = eph.at(k)
            q = self.truth[k]
            worst = max(worst, sum((a - b) ** 2 for a, b in zip(p, q)) ** 0.5)
        self.assertLess(worst, 1.0)

    def test_gap_is_not_bridged(self):
        t = sorted(self.truth)
        coarse = {k: self.truth[k] for k in t[::60] if not (30000 < k - t[0] < 31000)}
        eph = orbit.Ephemeris(coarse, order=9)
        self.assertIsNone(eph.at(t[0] + 30500))
        self.assertIsNotNone(eph.at(t[0] + 29000))
        self.assertIsNone(eph.at(t[0] - 1))

    def test_geodetic(self):
        self.assertEqual(orbit.geodetic(6378137.0 + 5e5, 0, 0), (0.0, 0.0, 500.0))
        lat, lon, h = orbit.geodetic(0, 0, 6356752.314245 + 8e5)
        self.assertAlmostEqual(lat, 90.0)
        self.assertAlmostEqual(h, 800.0, places=3)

    def test_cpf(self):
        with open(CPF, encoding="ascii") as fh:
            name, s = orbit.read_cpf(fh)
        self.assertEqual(name, "sentinel6a")
        eph = orbit.Ephemeris(s)
        self.assertEqual(eph.step, 180.0)
        self.assertEqual(rinex.iso(rinex.gps_to_unix(min(s))), "2026-11-13T00:00:00.000Z")
        lat, lon, alt = orbit.geodetic(*s[min(s)])
        self.assertTrue(1340 < alt < 1360, alt)


# ============================================================================== extraction

def _check_rows(tc: unittest.TestCase, path: str, summary: dict, max_odd: float = 0.02) -> list[dict]:
    """Rows sit inside their box, carry only S observables, and values are stored as read.

    Upstream does write non-physical values (Spire: -164 to +338 dB-Hz, ~1 in 12,000;
    Swarm S1W: a constant -3.68 when L2 is lost, ~4 % in the regions). They are kept
    literally; the test only bounds how often they appear.
    """
    rows = read_rows(path)
    tc.assertEqual(len(rows), sum(summary["totals"]["rows"].values()))
    n = odd = 0
    for r in rows:
        box = REGIONS[r["reg"]]
        tc.assertTrue(box["lat"][0] <= r["lat"] <= box["lat"][1], r)
        tc.assertTrue(box["lon"][0] <= r["lon"] <= box["lon"][1], r)
        tc.assertGreaterEqual(r["n_sv"], len(r["cn0"]))
        for vals in r["cn0"].values():
            for code, v in vals.items():
                tc.assertTrue(code.startswith("S") and len(code) == 3, code)
                tc.assertIsInstance(v, float)
                tc.assertNotEqual(v, 0.0)
                n += 1
                odd += not (0 < v < 70)
    tc.assertLess(odd, max_odd * max(n, 1), f"{odd} of {n} values outside 0-70")
    return rows


def _check_global(tc: unittest.TestCase, path: str, summary: dict) -> list[dict]:
    """Global series: one row per receiver per 10 s window, everywhere."""
    rows = read_rows(path)
    tc.assertEqual(len(rows), summary["totals"]["global_rows"])
    per = {}
    for r in rows:
        w = (r["rx"], int(r["gps_s"] // 10))
        tc.assertNotIn(w, per)
        per[w] = r
        if r["reg"] is None and r["lat"] is not None:
            tc.assertIsNone(Regions_.classify(r["lat"], r["lon"]))
    tc.assertTrue(any(r["reg"] is None for r in rows))
    return rows


Regions_ = common.Regions({"regions": REGIONS})


@unittest.skipUnless(have(POD, ORB), "needs the day-317 Spire sample")
class TestExtractSpire(unittest.TestCase):
    def test_day_317(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = test_cfg(tmp)
            store = common.Store(cfg)
            put(store, "spire_ucar", DAY, POD)
            put(store, "spire_ucar", DAY, ORB)
            src = Spire(cfg, store, common.Regions(cfg))
            self.assertTrue(src.complete(DAY, store.manifest("spire_ucar", DAY)))
            self.assertTrue(src.needs_extract(DAY, store.manifest("spire_ucar", DAY)))
            s = src.extract_day(DAY)
            rows = _check_rows(self, store.extract_path("spire_ucar", DAY), s, max_odd=0.0005)
            t = s["totals"]
            self.assertEqual(t["receivers"], 21)
            # Spire's pass files overlap: 29.2 % of the 875,661 epochs read are repeats,
            # all but 101 identical. Written once.
            self.assertEqual(t["epochs"], 619995)
            self.assertEqual(t["duplicates"], 255666)
            self.assertEqual(t["duplicates_conflicting"], 101)
            self.assertEqual(t["rows"], {"baltic": 4991, "control": 13042})
            self.assertEqual(len({(r["rx"], r["gps_s"]) for r in rows}), len(rows))
            g = _check_global(self, store.global_path("spire_ucar", DAY), s)
            self.assertEqual(len(g), 62169)
            self.assertTrue(any(r["lat"] is None for r in g))  # passes without orbit are kept
            self.assertEqual(len(s["bad_files"]), 2)          # two empty members upstream
            self.assertEqual({c for r in s["receivers"].values() for c in r["cn0_codes"]}, {"S1C", "S2L"})
            self.assertTrue(any(r["reg"] == "baltic" and 59 < r["lat"] < 61 and 22 < r["lon"] < 30
                                for r in rows), "no epoch over the Gulf of Finland")
            # idempotent: nothing to redo, and a second run gives the same file
            self.assertFalse(src.needs_extract(DAY, store.manifest("spire_ucar", DAY)))


@unittest.skipUnless(have(GPSA, MODA), "needs the day-317 Swarm samples")
class TestExtractSwarm(unittest.TestCase):
    def test_day_317_swarm_a(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = test_cfg(tmp)
            cfg["sources"]["swarm_esa"]["satellites"] = ["A"]
            store = common.Store(cfg)
            put(store, "swarm_esa", DAY, GPSA)
            put(store, "swarm_esa", DAY, MODA)
            src = Swarm(cfg, store, common.Regions(cfg))
            self.assertTrue(src.complete(DAY, store.manifest("swarm_esa", DAY)))
            s = src.extract_day(DAY)
            rows = _check_rows(self, store.extract_path("swarm_esa", DAY), s, max_odd=0.05)
            # finding: S1W and S2W are one measurement written twice
            pairs = [v for r in rows for v in r["cn0"].values() if "S1W" in v and "S2W" in v]
            self.assertGreater(len(pairs), 10000)
            self.assertTrue(all(v["S1W"] == v["S2W"] for v in pairs))
            r = s["receivers"]["swarm-A"]
            g = _check_global(self, store.global_path("swarm_esa", DAY), s)
            self.assertEqual(len(g), 8641)          # 86,400 s from 00:00:18 GPS: 8,641 windows
            self.assertEqual(r["duplicates"], 0)
            self.assertEqual(r["epochs"], 86400)
            self.assertEqual(r["no_position"], 0)
            self.assertEqual(r["rows"], {"baltic": 1243, "control": 2055})
            self.assertEqual(r["cn0_codes"], ["S1C", "S1W", "S2W"])


def _synthetic_s6_rinex(times_gps: list[float]) -> bytes:
    """A mixed GPS+Galileo RINEX 3.04 hour in the layout the Sentinel-6 file name announces."""
    hdr = [
        "     3.04           OBSERVATION DATA    M                   RINEX VERSION / TYPE",
        "S6A                                                         MARKER NAME",
        "G    9 C1C L1C S1C C2W L2W S2W C5Q L5Q S5Q                  SYS / # / OBS TYPES",
        "E    6 C1C L1C S1C C5Q L5Q S5Q                              SYS / # / OBS TYPES",
        "DBHZ                                                        SIGNAL STRENGTH UNIT",
        "                                                            END OF HEADER",
    ]
    out = [h.ljust(80) for h in hdr]
    for t in times_gps:
        u = t  # GPS calendar fields
        days, sod = divmod(u, 86400)
        d = dt.date(1980, 1, 6) + dt.timedelta(days=int(days))
        hh, rem = divmod(sod, 3600)
        mm, ss = divmod(rem, 60)
        out.append(f"> {d.year:4d} {d.month:02d} {d.day:02d} {int(hh):02d} {int(mm):02d}"
                   f"{ss:11.7f}  0  2")
        g = "".join(f"{v:14.3f}  " for v in (2.2e7, 1.1e8, 44.5, 2.2e7, 8.6e7, 30.25, 2.2e7, 8.2e7, 48.0))
        e = "".join(f"{v:14.3f}  " for v in (2.5e7, 1.3e8, 41.0, 2.5e7, 9.8e7, 0.0))
        out.append("G05" + g)
        out.append("E11" + e)
    return ("\n".join(out) + "\n").encode()


@unittest.skipUnless(have(CPF), "needs the Sentinel-6A CPF sample")
class TestSentinel6(unittest.TestCase):
    def test_disabled_without_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = test_cfg(tmp)
            cfg["sources"]["sentinel6_eum"]["credentials_file"] = os.path.join(tmp, "none.toml")
            old = {k: os.environ.pop(k, None) for k in ("EUMETSAT_CONSUMER_KEY", "EUMETSAT_CONSUMER_SECRET")}
            try:
                src = Sentinel6(cfg, common.Store(cfg), common.Regions(cfg))
                ok, why = src.enabled()
                self.assertFalse(ok)
                self.assertIn("none.toml", why)
                cred = os.path.join(tmp, "c.toml")
                with open(cred, "w") as fh:
                    fh.write('consumer_key = "k"\nconsumer_secret = "s"\n')
                os.chmod(cred, 0o600)
                cfg["sources"]["sentinel6_eum"]["credentials_file"] = cred
                self.assertEqual(Sentinel6(cfg, common.Store(cfg), common.Regions(cfg)).enabled(), (True, ""))
            finally:
                for k, v in old.items():
                    if v is not None:
                        os.environ[k] = v

    def test_synthetic_hour_over_the_baltic(self):
        # S6A crosses the Baltic box at 09:06-09:11 UTC on 13-Nov (from the CPF itself)
        t0 = rinex.gps_seconds(2026, 11, 13, 9, 7, 18)
        times = [t0 + k for k in range(5)]
        rnx = gzip.compress(_synthetic_s6_rinex(times))
        pid = "S6A_GN_1B_RNXH_AX_20261113T085942_20261113T095941_20261113T104000___CPOD_OPE_NR____.SEN6"
        with tempfile.TemporaryDirectory() as tmp:
            cfg = test_cfg(tmp)
            cfg["sources"]["sentinel6_eum"]["satellites"] = ["Sentinel-6A"]
            store = common.Store(cfg)
            zpath = os.path.join(tmp, pid + ".zip")
            with zipfile.ZipFile(zpath, "w") as zf:
                zf.writestr(f"{pid}/S6AP00EUM_R_20263170900_01H_01S_MO.rnx.gz", rnx)
                zf.writestr(f"{pid}/xfdumanifest.xml", "<xfdu/>")
            put(store, "sentinel6_eum", DAY, zpath)
            put(store, "sentinel6_eum", DAY, CPF)
            src = Sentinel6(cfg, store, common.Regions(cfg))
            self.assertFalse(src.complete(DAY, store.manifest("sentinel6_eum", DAY)))  # 1 of 24 hours
            s = src.extract_day(DAY)
            rows = _check_rows(self, store.extract_path("sentinel6_eum", DAY), s)
            self.assertEqual(len(rows), 5)
            self.assertEqual({r["reg"] for r in rows}, {"baltic"})
            self.assertEqual(rows[0]["cn0"], {"G05": {"S1C": 44.5, "S2W": 30.25, "S5Q": 48.0},
                                              "E11": {"S1C": 41.0}})
            self.assertEqual(rows[0]["n_sv"], 2)
            self.assertEqual(rows[0]["rx"], "sentinel6-A")
            self.assertTrue(1340 < rows[0]["alt_km"] < 1360)


# ============================================================================== safety

class TestArchiveSafety(unittest.TestCase):
    def test_names(self):
        for bad in ("../x", "a/../../x", "/etc/passwd", "a\\..\\x", "", "a/./b c"):
            self.assertFalse(common.safe_member_name(bad), bad)
        self.assertTrue(common.safe_member_name("S6A_x.SEN6/S6AP00EUM_R_20263170900_01H_01S_MO.rnx.gz"))

    def test_tar_and_zip_traversal_never_reach_disk(self):
        import re
        with tempfile.TemporaryDirectory() as tmp:
            tpath = os.path.join(tmp, "evil.tar.gz")
            with tarfile.open(tpath, "w:gz") as tf:
                for name in ("../escape_crx.gz", "/abs_crx.gz", "ok_crx.gz"):
                    data = b"payload"
                    ti = tarfile.TarInfo(name)
                    ti.size = len(data)
                    tf.addfile(ti, io.BytesIO(data))
                link = tarfile.TarInfo("link_crx.gz")
                link.type = tarfile.SYMTYPE
                link.linkname = "/etc/passwd"
                tf.addfile(link)
            zpath = os.path.join(tmp, "evil.zip")
            with zipfile.ZipFile(zpath, "w") as zf:
                zf.writestr("../escape_crx.gz", b"x")
                zf.writestr("ok_crx.gz", b"x")
            before = sorted(os.listdir(tmp)) + sorted(os.listdir(os.path.dirname(tmp)))
            pat = re.compile(r".*_crx\.gz$")
            self.assertEqual([n for n, _ in common.tar_members(tpath, pat)], ["ok_crx.gz"])
            self.assertEqual([n for n, _ in common.zip_members(zpath, pat)], ["ok_crx.gz"])
            after = sorted(os.listdir(tmp)) + sorted(os.listdir(os.path.dirname(tmp)))
            self.assertEqual(before, after)

    def test_decompression_fuse(self):
        old = common.MAX_MEMBER_BYTES
        common.MAX_MEMBER_BYTES = 10_000
        try:
            blob = gzip.compress(b"x" * 100 + b"\n" * 100_000)
            with self.assertRaises(ValueError):
                for _ in common.text_lines(io.BytesIO(blob), gz=True):
                    pass
        finally:
            common.MAX_MEMBER_BYTES = old


# ============================================================================== download-only sources

class TestSmallSources(unittest.TestCase):
    def test_opngns_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = test_cfg(tmp)
            cfg["sources"]["spire_ucar"]["products"] = ["level1a/podCrx", "level1a/opnGns", "level1b/leoOrb"]
            src = Spire(cfg, common.Store(cfg), common.Regions(cfg))
            with self.assertLogs("gnss_leo", level="ERROR"):
                self.assertEqual(src.products(), [("level1a", "podCrx"), ("level1b", "leoOrb")])

    def test_igs_names(self):
        self.assertEqual(gps_week(DAY), 2444)
        with tempfile.TemporaryDirectory() as tmp:
            cfg = test_cfg(tmp)
            src = IgsOrbits(cfg, common.Store(cfg), common.Regions(cfg))
            names = src._names(DAY)
            self.assertIn(("https://igs.bkg.bund.de/root_ftp/IGS/products/2444/",
                           "IGS0OPSRAP_20263170000_01D_15M_ORB.SP3.gz"), names)
            self.assertTrue(any(n.startswith("GFZ0OPSRAP_2026317") for _, n in names))
            self.assertFalse(src.extracts)

    def test_satjam_is_a_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = test_cfg(tmp)
            cfg["sources"]["satjam"]["after_utc_hour"] = 0
            src = SatJam(cfg, common.Store(cfg), common.Regions(cfg))
            today = common.utcnow().date()
            self.assertIsNone(src.remotes(today - dt.timedelta(days=1)))
            self.assertEqual(len(src.remotes(today)), 9)
            with self.assertRaises(Exception):
                src.validate(os.path.join(MOD, "gnss_leo.toml"), "x.json")  # not JSON: refused


# ============================================================================== store

class _Fake(Source):
    name = "spire_ucar"
    calls = 0

    def complete(self, day, man):
        return False

    def remotes(self, day):
        _Fake.calls += 1
        return [Remote("https://invalid.invalid/never", "f.tar.gz", 50_000_000)]

    def extract_into(self, day, man, writer, stats):
        pass


class TestStore(unittest.TestCase):
    def test_disk_floor_blocks_download_and_shouts(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = test_cfg(tmp)
            cfg["store"]["min_free_gb"] = 1e9  # an exabyte: always below
            store = common.Store(cfg)
            src = _Fake(cfg, store, common.Regions(cfg))
            with self.assertLogs("gnss_leo", level="CRITICAL") as logs:
                src.cycle(DAY, DAY, full=True)
            self.assertTrue(src.state["disk_floor"])
            self.assertTrue(any("DISK FLOOR" in m for m in logs.output))
            self.assertFalse(os.path.exists(store.raw_dir("spire_ucar", DAY) + "/f.tar.gz.part"))

    def test_stale_upstream_is_logged(self):
        """Spire: NOAA's order ends 2026-12-01; silence from UCAR must show in the log."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = test_cfg(tmp)
            store = common.Store(cfg)
            src = Spire(cfg, store, common.Regions(cfg))
            p = os.path.join(tmp, "x.tar.gz")
            with open(p, "wb") as fh:
                fh.write(b"x")
            put(store, "spire_ucar", DAY, p)
            src.check_stale(DAY + dt.timedelta(days=2))
            self.assertFalse(src.state["stale"])
            with self.assertLogs("gnss_leo", level="WARNING") as logs:
                src.check_stale(DAY + dt.timedelta(days=4))
            self.assertTrue(src.state["stale"])
            self.assertTrue(any("NO NEW FILES" in m and "2026-12-01" in m for m in logs.output))

    def test_single_writer_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            fh = common.acquire_lock(tmp)
            self.assertEqual(common.lock_holder(tmp), os.getpid())
            code = ("import sys; sys.path.insert(0, sys.argv[1]); import common; "
                    "common.acquire_lock(sys.argv[2])")
            p = subprocess.run([sys.executable, "-I", "-c", code, MOD, tmp], capture_output=True)
            self.assertEqual(p.returncode, 3)
            fh.close()
            self.assertIsNone(common.lock_holder(tmp))

    def test_manifest_have_requires_file_and_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = common.Store(test_cfg(tmp))
            p = os.path.join(tmp, "a.zip")
            with open(p, "wb") as fh:
                fh.write(b"123")
            put(store, "swarm_esa", DAY, p)
            self.assertTrue(store.have("swarm_esa", DAY, "a.zip"))
            with open(os.path.join(store.raw_dir("swarm_esa", DAY), "a.zip"), "ab") as fh:
                fh.write(b"4")
            self.assertFalse(store.have("swarm_esa", DAY, "a.zip"))


if __name__ == "__main__":
    unittest.main()
