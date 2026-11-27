"""Compact RINEX (Hatanaka) decoder, CRINEX 1.0 and 3.0, standard library only.

Decodes straight to values instead of rebuilding RINEX text. Why not the `hatanaka`
package at run time: its decoder is C code fed with untrusted downloads, and this one
is ~100 lines of Python that cannot overflow a buffer. The C decoder is kept, pinned,
as the reference the tests compare against (tests/test_parsers.py).

Format (Y. Hatanaka, "Compact RINEX format", v1.0 and v3.0):
  epoch line   text-differenced against the previous one (' ' = same char, '&' = blank);
               a line starting with '&' (v1) or '>' (v3) is a fresh one. The satellite
               list sits on the same line: column 33 (v1) / 42 (v3).
  clock line   one differenced integer, or blank. Not used here.
  data lines   one per satellite, fields separated by one blank, blank field = missing.
               "k&v" starts an arc of difference order k with value v; a bare integer
               is the next difference. Values are observation x 1000. After the last
               field come the LLI/SSI flags, not used here.
"""

from __future__ import annotations

from rinex import Header, RinexError, gps_seconds, take, _sv


def _repair(old: str, diff: str) -> str:
    if len(diff) > len(old):
        old = old.ljust(len(diff))
    out = list(old)
    for i, ch in enumerate(diff):
        if ch == " ":
            continue
        out[i] = " " if ch == "&" else ch
    return "".join(out)


def iter_crx_epochs(lines, h: Header, want: set[str] | None = None):
    """Yield (gps_s, flag, [(sv, {code: value})]) like rinex.iter_epochs."""
    v3 = h.crinex.startswith("3")
    if not v3 and not h.crinex.startswith("1"):
        raise RinexError(f"unsupported CRINEX version {h.crinex!r}")
    if v3 and h.version < 3 or (not v3 and h.version >= 3):
        raise RinexError(f"CRINEX {h.crinex} wrapping RINEX {h.version}")
    off = 41 if v3 else 32
    dsys = "G" if v3 else (h.sat_system if h.sat_system and h.sat_system != "M" else "G")
    # per system: list of (field index, code) wanted, and field count
    wanted: dict[str, list[tuple[int, str]]] = {}
    ntypes: dict[str, int] = {}
    for sys_, types in h.obs_types.items():
        wanted[sys_] = [(i, c) for i, c in enumerate(types) if want is None or c in want]
        ntypes[sys_] = len(types)
    state: dict[str, dict[int, list | None]] = {}
    prev = ""
    nxt = lines.__next__
    lineno = h.lines
    for raw in lines:
        lineno += 1
        line = raw.rstrip("\r\n")
        if v3:
            if line.startswith(">"):
                cur = line
            else:
                cur = _repair(prev, line)
        else:
            if line.startswith("&"):
                cur = " " + line[1:]
            else:
                cur = _repair(prev, line)
        prev = cur
        try:
            if v3:
                flag = int(cur[31:32] or 0)
                n = int(cur[32:35])
            else:
                flag = int(cur[28:29] or 0)
                n = int(cur[29:32])
        except ValueError as exc:
            raise RinexError(f"line {lineno}: bad epoch line {cur[:40]!r}") from exc
        if flag > 1:
            # event: n special records follow as plain text, no clock line;
            # the next epoch line is always a fresh one
            for _ in range(n):
                take(nxt, "event records")
                lineno += 1
            prev = ""
            continue
        if v3:
            t = gps_seconds(int(cur[2:6]), int(cur[7:9]), int(cur[10:12]),
                            int(cur[13:15]), int(cur[16:18]), float(cur[18:29]))
            sys_key = None
        else:
            yy = int(cur[1:3])
            t = gps_seconds(yy + (2000 if yy < 80 else 1900), int(cur[4:6]), int(cur[7:9]),
                            int(cur[10:12]), int(cur[13:15]), float(cur[15:26]))
            sys_key = "*"
        svtxt = cur[off:off + 3 * n].ljust(3 * n)
        svs = [_sv(svtxt[3 * k:3 * k + 3], dsys) for k in range(n)]
        take(nxt, "an epoch")  # receiver clock line
        lineno += 1
        new_state: dict[str, dict[int, list | None]] = {}
        sats = []
        for sv in svs:
            data = take(nxt, "an epoch").rstrip("\r\n")
            lineno += 1
            key = sys_key or sv[0]
            nt = ntypes.get(key)
            if nt is None:
                raise RinexError(f"line {lineno}: no observation types for system {sv[0]}")
            parts = data.split(" ", nt)
            st = state.get(sv, {})
            vals = {}
            for i, code in wanted[key]:
                f = parts[i] if i < len(parts) and i < nt else ""
                if not f:
                    st[i] = None
                    continue
                amp = f.find("&")
                if amp >= 0:
                    order = int(f[:amp])
                    v = int(f[amp + 1:])
                    st[i] = [order, 0, [v] + [0] * order]
                else:
                    s = st.get(i)
                    if s is None:
                        raise RinexError(f"line {lineno}: {sv} {code} difference without "
                                         f"an initialised arc")
                    order, k, d = s
                    if k < order:
                        k += 1
                        s[1] = k
                    d[k] = int(f)
                    for j in range(k - 1, -1, -1):
                        d[j] += d[j + 1]
                    v = d[0]
                vals[code] = v / 1000.0
            new_state[sv] = st
            sats.append((sv, vals))
        # a satellite absent from this epoch must restart its arcs when it returns
        state = new_state
        yield t, flag, sats
