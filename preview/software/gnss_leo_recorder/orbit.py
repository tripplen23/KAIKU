"""Receiver-satellite positions: SP3 and CPF readers, interpolation, WGS84 geodetic.

Standard library only. Positions are Earth-fixed (ITRF/IGS frames; the differences
between realisations are centimetres, irrelevant for a region box).
"""

from __future__ import annotations

import bisect
import math

from rinex import RinexError, gps_seconds, unix_to_gps

# WGS84
_A = 6378137.0
_F = 1 / 298.257223563
_E2 = _F * (2 - _F)
_B = _A * (1 - _F)
_EP2 = (_A * _A - _B * _B) / (_B * _B)


def geodetic(x: float, y: float, z: float) -> tuple[float, float, float]:
    """ECEF metres -> (lat deg, lon deg, height km above the WGS84 ellipsoid)."""
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - _E2))
    for _ in range(4):
        s = math.sin(lat)
        n = _A / math.sqrt(1 - _E2 * s * s)
        h = p * math.cos(lat) + z * s - _A * _A / n
        lat = math.atan2(z, p * (1 - _E2 * n / (n + h)))
    s = math.sin(lat)
    n = _A / math.sqrt(1 - _E2 * s * s)
    h = p * math.cos(lat) + z * s - _A * _A / n
    return math.degrees(lat), math.degrees(lon), h / 1000.0


class Ephemeris:
    """Tabulated ECEF positions of one satellite, interpolated with a Lagrange polynomial.

    The table is cut into runs wherever two samples are more than `max_gap` apart
    (default 2.5 nominal steps). `at(t)` interpolates inside a run only: a gap in the
    orbit is reported as "no position" (None), never bridged.
    """

    def __init__(self, samples: dict[float, tuple[float, float, float]], order: int = 9,
                 max_gap: float | None = None):
        self.t = sorted(samples)
        self.p = [samples[k] for k in self.t]
        self.order = order
        steps = sorted(b - a for a, b in zip(self.t, self.t[1:]))
        self.step = steps[len(steps) // 2] if steps else 0.0
        self.max_gap = max_gap if max_gap is not None else 2.5 * self.step
        self._exact = {k: i for i, k in enumerate(self.t)}
        # run boundaries: run r covers indices [starts[r], ends[r]]
        self.starts, self.ends = [], []
        for i, k in enumerate(self.t):
            if i == 0 or k - self.t[i - 1] > self.max_gap:
                self.starts.append(i)
                if i:
                    self.ends.append(i - 1)
        if self.t:
            self.ends.append(len(self.t) - 1)
        self._start_t = [self.t[i] for i in self.starts]

    def __len__(self):
        return len(self.t)

    def at(self, t: float):
        i = self._exact.get(t)
        if i is not None:
            return self.p[i]
        r = bisect.bisect_right(self._start_t, t) - 1
        if r < 0:
            return None
        lo_run, hi_run = self.starts[r], self.ends[r]
        if t > self.t[hi_run] or hi_run - lo_run < 3:
            return None
        n = hi_run - lo_run + 1
        m = min(self.order + 1, n)
        j = bisect.bisect_left(self.t, t, lo_run, hi_run + 1)
        lo = max(lo_run, min(j - m // 2, hi_run + 1 - m))
        ts = self.t[lo:lo + m]
        ps = self.p[lo:lo + m]
        x = y = z = 0.0
        for k in range(m):
            w = 1.0
            tk = ts[k]
            for q in range(m):
                if q != k:
                    w *= (t - ts[q]) / (tk - ts[q])
            x += w * ps[k][0]
            y += w * ps[k][1]
            z += w * ps[k][2]
        return (x, y, z)


def read_sp3(lines) -> tuple[dict[str, dict[float, tuple]], str]:
    """SP3-c/d positions -> ({sat id: {gps_s: (x, y, z) metres}}, time system).

    Bad positions (0.000000 or 999999 markers) are dropped. Velocities are ignored.
    """
    out: dict[str, dict[float, tuple]] = {}
    tsys = "GPS"
    t = None
    first = True
    seen_pc = False
    for raw in lines:
        if first:
            if not raw.startswith("#"):
                raise RinexError("not an SP3 file")
            if raw[1:2] not in ("c", "d", "a", "b"):
                raise RinexError(f"SP3 version {raw[1:2]!r} not supported")
            first = False
            continue
        c = raw[:1]
        if c == "%" and raw.startswith("%c") and not seen_pc:
            seen_pc = True  # only the first %c line carries the time system
            ts = raw[9:12].strip()
            if ts and ts not in ("cc", "ccc"):
                tsys = ts
        elif c == "*":
            t = gps_seconds(int(raw[3:7]), int(raw[8:10]), int(raw[11:13]),
                            int(raw[14:16]), int(raw[17:19]), float(raw[20:31]))
        elif c == "P" and t is not None:
            sid = raw[1:4]
            try:
                x, y, z = float(raw[4:18]), float(raw[18:32]), float(raw[32:46])
            except ValueError:
                continue
            if (x == 0.0 and y == 0.0 and z == 0.0) or abs(x) > 1e5:
                continue
            out.setdefault(sid, {})[t] = (x * 1000.0, y * 1000.0, z * 1000.0)
        elif raw.startswith("EOF"):
            break
    if first:
        raise RinexError("empty SP3 file")
    if tsys not in ("GPS", "GPST"):
        raise RinexError(f"SP3 time system {tsys} not handled")
    return out, tsys


def read_cpf(lines) -> tuple[str, dict[float, tuple]]:
    """ILRS CPF v1/v2 prediction -> (target name, {gps_s: (x, y, z) metres}).

    Record 10 carries MJD and seconds of day in UTC, Earth-fixed position in metres.
    """
    name = ""
    out: dict[float, tuple] = {}
    seen_h1 = False
    for raw in lines:
        f = raw.split()
        if not f:
            continue
        if f[0] in ("H1", "h1"):
            seen_h1 = True
            name = f[-1] if len(f) >= 10 else ""
        elif f[0] == "10" and len(f) >= 8:
            if f[1] != "0":
                continue  # only instantaneous vectors
            mjd, sod = int(f[2]), float(f[3])
            unix = (mjd - 40587) * 86400 + sod
            out[unix_to_gps(unix)] = (float(f[5]), float(f[6]), float(f[7]))
        elif f[0] == "99":
            break
    if not seen_h1:
        raise RinexError("not a CPF file (no H1 record)")
    return name, out
