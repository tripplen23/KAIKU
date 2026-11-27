"""RINEX 2/3 observation reader, Compact RINEX (Hatanaka) included, standard library only.

Reads untrusted downloads: nothing here executes, evaluates or writes what it reads.
Every function takes an iterator of text lines and yields plain Python values.

Time is carried as float GPS seconds since 1980-01-06 00:00:00 GPS ("gps_s").
All three sources timestamp their observations in GPS time (header TIME OF FIRST OBS / SP3 %c).
"""

from __future__ import annotations

import time

GPS_UNIX_OFFSET = 315964800  # unix seconds at 1980-01-06T00:00:00Z

# GPS - UTC, seconds, with the GPS second at which it took effect. 18 s since 2017-01-01.
_LEAPS = [
    (1119744016, 18),  # 2017-01-01
    (1119744016 - 47174400, 17),  # 2015-07-01
    (0, 16),
]


class RinexError(ValueError):
    pass


# ----------------------------------------------------------------------------- time

def days_from_civil(y: int, m: int, d: int) -> int:
    """Days since 1970-01-01 for a proleptic Gregorian date (H. Hinnant)."""
    y -= m <= 2
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


_GPS_DAY0 = days_from_civil(1980, 1, 6)


def gps_seconds(y: int, mo: int, d: int, h: int, mi: int, s: float) -> float:
    return (days_from_civil(y, mo, d) - _GPS_DAY0) * 86400 + h * 3600 + mi * 60 + s


def leap_seconds(gps_s: float) -> int:
    for start, leap in _LEAPS:
        if gps_s >= start:
            return leap
    return _LEAPS[-1][1]


def gps_to_unix(gps_s: float) -> float:
    return gps_s + GPS_UNIX_OFFSET - leap_seconds(gps_s)


def unix_to_gps(unix_s: float) -> float:
    g = unix_s - GPS_UNIX_OFFSET
    return g + leap_seconds(g + 18)


def iso(unix_s: float) -> str:
    """ISO-8601 with milliseconds and Z. Fast path: no datetime objects."""
    whole = int(unix_s // 1)
    ms = int(round((unix_s - whole) * 1000))
    if ms == 1000:
        whole, ms = whole + 1, 0
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(whole)) + f".{ms:03d}Z"


# ----------------------------------------------------------------------------- header

class Header:
    """The parts of a RINEX observation header this tool uses."""

    def __init__(self):
        self.crinex: str | None = None    # "1.0" / "3.0" when Hatanaka-compressed
        self.version: float = 0.0
        self.file_type = ""
        self.sat_system = ""
        self.marker = ""
        self.receiver = ""
        self.time_system = "GPS"
        self.interval: float | None = None
        self.signal_strength_unit = ""
        # RINEX 3: {"G": ["C1C", ...], "E": [...]}; RINEX 2: {"*": ["C1", ...]}
        self.obs_types: dict[str, list[str]] = {}
        # RINEX 3 -> 2 conversion recorded by gfzrnx in COMMENT lines: {"G": {"S1": "S1C"}}
        self.rnx2_to_rnx3: dict[str, dict[str, str]] = {}
        self.lines = 0

    def types_for(self, system: str) -> list[str]:
        if self.version < 3:
            return self.obs_types.get("*", [])
        return self.obs_types.get(system, [])

    def canonical(self, system: str, code: str) -> str:
        """RINEX 3 name of an observable. RINEX 2 codes are mapped back when the file says how."""
        if self.version >= 3:
            return code
        return self.rnx2_to_rnx3.get(system, {}).get(code, code)


def read_header(lines) -> Header:
    """Consume header lines up to END OF HEADER. `lines` must be an iterator."""
    h = Header()
    pending_sys = None
    pending_n = 0
    rnx2_n = 0
    in_conv = False
    for raw in lines:
        h.lines += 1
        if h.lines > 5000:
            raise RinexError("header longer than 5000 lines")
        line = raw.rstrip("\r\n")
        label = line[60:80].strip()
        if h.lines == 1 and "COMPACT RINEX FORMAT" in line:
            h.crinex = line[:20].strip()
            continue
        if label == "CRINEX PROG / DATE":
            continue
        if label == "RINEX VERSION / TYPE":
            h.version = float(line[:9])
            h.file_type = line[20:21]
            h.sat_system = line[40:41]
            continue
        if label == "MARKER NAME":
            h.marker = line[:60].strip()
        elif label == "REC # / TYPE / VERS":
            h.receiver = line[20:40].strip()
        elif label == "INTERVAL":
            try:
                h.interval = float(line[:10])
            except ValueError:
                pass
        elif label == "SIGNAL STRENGTH UNIT":
            h.signal_strength_unit = line[:20].strip()
        elif label == "TIME OF FIRST OBS":
            ts = line[48:51].strip()
            if ts:
                h.time_system = ts
        elif label == "SYS / # / OBS TYPES":
            if line[0] != " ":
                pending_sys = line[0]
                pending_n = int(line[3:6])
                h.obs_types[pending_sys] = []
            if pending_sys is None:
                raise RinexError("SYS / # / OBS TYPES continuation without a system")
            h.obs_types[pending_sys].extend(line[7:60].split())
        elif label == "# / TYPES OF OBSERV":
            if line[:6].strip():
                rnx2_n = int(line[:6])
                h.obs_types["*"] = []
            h.obs_types.setdefault("*", []).extend(line[6:60].split())
        elif label == "COMMENT":
            body = line[:60]
            if "RINEX 3 -> 2 TYPE CONVERSION" in body:
                in_conv = True
            elif in_conv:
                parts = body.split()
                # "   G S1C -> S1"
                if len(parts) == 4 and parts[2] == "->" and len(parts[0]) == 1:
                    h.rnx2_to_rnx3.setdefault(parts[0], {})[parts[3]] = parts[1]
                elif parts and set(body.strip()) <= {"-"} and h.rnx2_to_rnx3:
                    in_conv = False
        elif label == "END OF HEADER":
            break
    else:
        raise RinexError("empty file" if h.lines == 0 else "no END OF HEADER")
    if h.version == 0.0:
        raise RinexError("no RINEX VERSION / TYPE line")
    if h.file_type not in ("O", ""):
        raise RinexError(f"not an observation file (type {h.file_type!r})")
    for sys_, types in h.obs_types.items():
        want = rnx2_n if sys_ == "*" else None
        if want is not None and len(types) != want:
            raise RinexError(f"# / TYPES OF OBSERV says {want}, found {len(types)}")
    if pending_sys is not None and len(h.obs_types[pending_sys]) != pending_n:
        raise RinexError(f"SYS / # / OBS TYPES for {pending_sys} says {pending_n}, "
                         f"found {len(h.obs_types[pending_sys])}")
    return h


class Truncated(RinexError):
    """The file ends inside a record. Epochs yielded before it are good."""


def take(nxt, what: str) -> str:
    try:
        return nxt()
    except StopIteration:
        raise Truncated(f"file ends inside {what}") from None


def _sv(token: str, default_sys: str) -> str:
    """Normalise a satellite token: ' 1' -> 'G01', 'G 1' -> 'G01'."""
    s = token[0] if token[0] != " " else default_sys
    return f"{s}{int(token[1:3]):02d}"


def _default_sys(h: Header) -> str:
    return h.sat_system if h.sat_system in "GRECJSI" and h.sat_system != "" else "G"


# ----------------------------------------------------------------------------- plain RINEX

def _float16(field: str):
    f = field[:14].strip()
    if not f:
        return None
    return float(f)


def iter_epochs(lines, h: Header, want: set[str] | None = None):
    """Yield (gps_s, flag, [(sv, {code: value})]) for every data epoch.

    `want`: observation codes to return (as written in the file). None = all.
    Values are floats in the file's units; blank fields are omitted.
    Epochs with event flags > 1 (header records follow) are skipped, not yielded.
    """
    if h.crinex:
        from crx import iter_crx_epochs
        yield from iter_crx_epochs(lines, h, want)
        return
    if h.version >= 3:
        yield from _iter_rnx3(lines, h, want)
    else:
        yield from _iter_rnx2(lines, h, want)


def _iter_rnx3(lines, h: Header, want):
    cols: dict[str, list[tuple[str, int]]] = {}
    for sys_, types in h.obs_types.items():
        cols[sys_] = [(c, 3 + 16 * i) for i, c in enumerate(types) if want is None or c in want]
    nxt = lines.__next__
    for line in lines:
        if not line.startswith(">"):
            continue  # tolerate stray lines between records
        flag = int(line[31:32] or 0)
        n = int(line[32:35])
        if flag > 1:
            for _ in range(n):
                take(nxt, "event records")
            continue
        t = gps_seconds(int(line[2:6]), int(line[7:9]), int(line[10:12]),
                        int(line[13:15]), int(line[16:18]), float(line[18:29]))
        sats = []
        for _ in range(n):
            rec = take(nxt, "an epoch")
            sv = _sv(rec[0:3], "G")
            vals = {}
            for code, c0 in cols.get(sv[0], ()):
                f = rec[c0:c0 + 14].strip()
                if f:
                    vals[code] = float(f)
            sats.append((sv, vals))
        yield t, flag, sats


def _iter_rnx2(lines, h: Header, want):
    types = h.obs_types.get("*", [])
    ntype = len(types)
    nlines = (ntype + 4) // 5
    idx = [(i, c) for i, c in enumerate(types) if want is None or c in want]
    dsys = _default_sys(h)
    nxt = lines.__next__
    for line in lines:
        line = line.rstrip("\r\n")
        if len(line) < 32 or line[28:29] == "" or not line[1:3].strip():
            continue
        flag = int(line[28:29] or 0)
        n = int(line[29:32])
        if flag > 1:
            for _ in range(n):
                take(nxt, "event records")
            continue
        yy = int(line[1:3])
        t = gps_seconds(yy + (2000 if yy < 80 else 1900), int(line[4:6]), int(line[7:9]),
                        int(line[10:12]), int(line[13:15]), float(line[15:26]))
        # up to 12 satellites per line in columns 33-68, continuation lines after
        txt = line[32:68].ljust(36)
        k = min(n, 12)
        svs = [_sv(txt[3 * i:3 * i + 3], dsys) for i in range(k)]
        left = n - k
        while left > 0:
            txt = take(nxt, "a satellite list").rstrip("\r\n")[32:68].ljust(36)
            m = min(left, 12)
            svs += [_sv(txt[3 * i:3 * i + 3], dsys) for i in range(m)]
            left -= m
        sats = []
        for sv in svs:
            body = "".join(take(nxt, "an epoch").rstrip("\r\n").ljust(80) for _ in range(nlines))
            vals = {}
            for i, code in idx:
                f = body[16 * i:16 * i + 14].strip()
                if f:
                    vals[code] = float(f)
            sats.append((sv, vals))
        yield t, flag, sats
