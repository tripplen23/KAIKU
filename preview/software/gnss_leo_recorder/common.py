"""Shared plumbing: configuration, store layout, lock, disk floor, HTTP, manifest, archives.

Standard library only (Python >= 3.11 for tomllib).
"""

from __future__ import annotations

import datetime as dt
import fcntl
import gzip
import hashlib
import io
import json
import logging
import os
import re
import shutil
import socket
import sys
import tarfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(HERE, "gnss_leo.toml")
LOG = logging.getLogger("gnss_leo")

# Bump when the extract format or its content changes: the daemon re-extracts every day
# whose summary carries an older version.
EXTRACTOR_VERSION = "2"  # 2: dedup of repeated epochs, 0.1 Hz global series

MAX_MEMBER_BYTES = 1 << 30  # 1 GiB uncompressed per archive member: a decompression-bomb fuse


class HttpError(Exception):
    def __init__(self, msg: str, status: int | None = None):
        super().__init__(msg)
        self.status = status


class DiskFloor(Exception):
    pass


# ----------------------------------------------------------------------------- config

def load_config(path: str | None = None) -> dict:
    path = path or os.environ.get("GNSS_LEO_CONFIG") or DEFAULT_CONFIG
    with open(path, "rb") as fh:
        cfg = tomllib.load(fh)
    st = cfg.setdefault("store", {})
    st["raw_root"] = os.path.expanduser(os.environ.get("GNSS_LEO_RAW", st["raw_root"]))
    st["extract_root"] = os.path.expanduser(os.environ.get("GNSS_LEO_EXTRACT", st["extract_root"]))
    st.setdefault("min_free_gb", 15.0)
    st.setdefault("user_agent", "gnss-leo-recorder/1.0 (research prototype)")
    cfg["_path"] = os.path.abspath(path)
    return cfg


def parse_day(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def doy(day: dt.date) -> int:
    return day.timetuple().tm_yday


def day_from_doy(year: int, d: int) -> dt.date:
    return dt.date(year, 1, 1) + dt.timedelta(days=d - 1)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def now_iso() -> str:
    return utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------------------- store layout

class Store:
    """Where everything lives. Raw outside Dropbox, extract + manifest inside it."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.raw_root = cfg["store"]["raw_root"]
        self.extract_root = cfg["store"]["extract_root"]
        self.min_free = float(cfg["store"]["min_free_gb"]) * 1e9

    def raw_dir(self, source: str, day: dt.date) -> str:
        return os.path.join(self.raw_root, "raw", source, f"{day.year}", f"{doy(day):03d}")

    def manifest_path(self, source: str, day: dt.date) -> str:
        return os.path.join(self.extract_root, "manifest", source, f"{day.year}",
                            f"{source}-{day.year}-{doy(day):03d}.manifest.ndjson")

    def extract_path(self, source: str, day: dt.date) -> str:
        return os.path.join(self.extract_root, "extract", source, f"{day.year}",
                            f"{source}-{day.isoformat()}.ndjson.gz")

    def global_path(self, source: str, day: dt.date) -> str:
        return os.path.join(self.extract_root, "extract", source, f"{day.year}",
                            f"{source}-{day.isoformat()}.global.ndjson.gz")

    def summary_path(self, source: str, day: dt.date) -> str:
        return os.path.join(self.extract_root, "extract", source, f"{day.year}",
                            f"{source}-{day.isoformat()}.summary.json")

    def state_path(self) -> str:
        return os.path.join(self.extract_root, "state.json")

    def log_path(self) -> str:
        return os.path.join(self.raw_root, "gnss_leo.log")

    def free_bytes(self) -> int:
        os.makedirs(self.raw_root, exist_ok=True)
        return shutil.disk_usage(self.raw_root).free

    def check_floor(self, upcoming: int = 0) -> None:
        free = self.free_bytes()
        if free - upcoming < self.min_free:
            raise DiskFloor(f"{free / 1e9:.1f} GB free on {self.raw_root}, floor is "
                            f"{self.min_free / 1e9:.0f} GB (next file {upcoming / 1e6:.0f} MB)")

    # -- manifest: one NDJSON line per downloaded file, append-only
    def manifest(self, source: str, day: dt.date) -> dict[str, dict]:
        """{file name: latest record}."""
        out: dict[str, dict] = {}
        p = self.manifest_path(source, day)
        try:
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        rec = json.loads(line)
                        out[rec["file"]] = rec
        except FileNotFoundError:
            pass
        return out

    def append_manifest(self, source: str, day: dt.date, rec: dict) -> None:
        p = self.manifest_path(source, day)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def have(self, source: str, day: dt.date, name: str, man: dict | None = None) -> bool:
        """True when the file is in the manifest AND on disk with the recorded size."""
        man = man if man is not None else self.manifest(source, day)
        rec = man.get(name)
        if not rec:
            return False
        p = os.path.join(self.raw_dir(source, day), name)
        try:
            return os.path.getsize(p) == rec["bytes"]
        except OSError:
            return False

    def days_held(self, source: str) -> list[dt.date]:
        """Days with a manifest (at least one file downloaded), from the file names."""
        base = os.path.join(self.extract_root, "manifest", source)
        out = []
        for _root, _dirs, files in os.walk(base):
            for f in files:
                if f.endswith(".manifest.ndjson"):
                    y, d = f[len(source) + 1:].split(".")[0].split("-")
                    out.append(day_from_doy(int(y), int(d)))
        return sorted(out)

    def read_summary(self, source: str, day: dt.date) -> dict | None:
        try:
            with open(self.summary_path(source, day), encoding="utf-8") as fh:
                return json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            return None


def atomic_write_bytes(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def atomic_write_json(path: str, obj) -> None:
    atomic_write_bytes(path, (json.dumps(obj, indent=1, sort_keys=True) + "\n").encode())


class NdjsonGzWriter:
    """Write rows to <path>.tmp and rename on close: a day file is either whole or absent."""

    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self.tmp = path + ".tmp"
        self._fh = open(self.tmp, "wb")
        self._gz = gzip.GzipFile(fileobj=self._fh, mode="wb", compresslevel=6, mtime=0)
        self.rows = 0

    def write(self, row: dict) -> None:
        self._gz.write((json.dumps(row, separators=(",", ":")) + "\n").encode())
        self.rows += 1

    def close(self) -> None:
        self._gz.close()
        self._fh.flush()
        os.fsync(self._fh.fileno())
        self._fh.close()
        os.replace(self.tmp, self.path)

    def abort(self) -> None:
        try:
            self._gz.close()
            self._fh.close()
        except OSError:
            pass


# ----------------------------------------------------------------------------- lock

def acquire_lock(root: str, name: str = "gnss_leo.lock"):
    """One writer per store, flock-based like the AIS recorder. Exit 3 if held."""
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, name)
    fh = open(path, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.seek(0)
        holder = fh.read().strip()
        sys.stderr.write(f"another gnss_leo writer holds {path} (pid {holder or '?'})\n")
        sys.exit(3)
    fh.seek(0)
    fh.truncate()
    fh.write(f"{os.getpid()}\n")
    fh.flush()
    return fh


def lock_holder(root: str, name: str = "gnss_leo.lock") -> int | None:
    """PID holding the lock, or None if free. Never takes the lock for long."""
    path = os.path.join(root, name)
    try:
        fh = open(path, "r")
    except FileNotFoundError:
        return None
    with fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            try:
                return int(fh.read().strip() or 0) or -1
            except ValueError:
                return -1
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        return None


# ----------------------------------------------------------------------------- HTTP

def _request(url: str, ua: str, headers: dict | None = None, data: bytes | None = None,
             method: str = "GET"):
    h = {"User-Agent": ua, "Accept-Encoding": "identity"}
    if headers:
        h.update(headers)
    return urllib.request.Request(url, headers=h, data=data, method=method)


def http_bytes(url: str, ua: str, headers: dict | None = None, max_bytes: int = 32 << 20,
               timeout: float = 60.0, data: bytes | None = None, method: str = "GET") -> tuple[int, str, bytes]:
    """Small GET (indexes, JSON). Returns (status, content-type, body). 404 -> (404, ct, b'')."""
    req = _request(url, ua, headers, data, method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise HttpError(f"{url}: response larger than {max_bytes} bytes")
            return resp.status, resp.headers.get("Content-Type", ""), body
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return 404, exc.headers.get("Content-Type", "") if exc.headers else "", b""
        raise HttpError(f"HTTP {exc.code} {exc.reason} for {redact(url)}", exc.code) from exc
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
        raise HttpError(f"{redact(url)}: {exc}") from exc


def redact(url: str) -> str:
    return re.sub(r"(access_token|token|key|secret)=[^&]+", r"\1=***", url)


def download(url: str, dest_dir: str, name: str, ua: str, headers: dict | None = None,
             expect_md5: str | None = None, timeout: float = 120.0,
             stop=lambda: False, validate=None) -> dict:
    """Stream to <name>.part, hash on the fly, fsync, rename. Returns the manifest record.

    A `.part` left by a crash is a temporary, overwritten on the next attempt.
    `validate(part_path, name)` may raise to refuse the file (damaged archive).
    `expect_md5` is advisory: a mismatch is recorded and logged, the file is kept
    (the size and archive checks are what refuse a damaged download).
    Raises HttpError (404 included, with status) on any failure; nothing is renamed then.
    """
    os.makedirs(dest_dir, exist_ok=True)
    final = os.path.join(dest_dir, name)
    part = final + ".part"
    req = _request(url, ua, headers)
    sha = hashlib.sha256()
    md5 = hashlib.md5() if expect_md5 else None
    n = 0
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(part, "wb") as out:
            status = resp.status
            ctype = resp.headers.get("Content-Type", "")
            clen = resp.headers.get("Content-Length")
            last_mod = resp.headers.get("Last-Modified")
            while True:
                if stop():
                    raise HttpError(f"stopped while downloading {name}")
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                sha.update(chunk)
                if md5:
                    md5.update(chunk)
                n += len(chunk)
            out.flush()
            os.fsync(out.fileno())
    except urllib.error.HTTPError as exc:
        raise HttpError(f"HTTP {exc.code} {exc.reason} for {redact(url)}", exc.code) from exc
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
        raise HttpError(f"{redact(url)}: {exc}") from exc
    if clen is not None and int(clen) != n:
        raise HttpError(f"{name}: got {n} bytes, Content-Length said {clen}")
    if n == 0:
        raise HttpError(f"{name}: empty response")
    md5_ok = None
    if md5:
        md5_ok = md5.hexdigest() == expect_md5.lower()
        if not md5_ok:
            LOG.warning("%s: md5 %s differs from the catalogue's %s (kept; size and "
                        "archive checks passed)", name, md5.hexdigest(), expect_md5)
    if validate is not None:
        try:
            validate(part, name)
        except Exception as exc:  # noqa: BLE001 - any parse failure means "damaged"
            raise HttpError(f"{name}: damaged download ({type(exc).__name__}: {exc})") from exc
    os.replace(part, final)
    rec = {
        "file": name,
        "url": redact(url),
        "bytes": n,
        "sha256": sha.hexdigest(),
        "http": status,
        "content_type": ctype,
        "last_modified": last_mod,
        "received_utc": now_iso(),
        "seconds": round(time.time() - t0, 1),
    }
    if md5:
        rec["upstream_md5"] = expect_md5
        rec["md5_match"] = md5_ok
    return rec


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ----------------------------------------------------------------------------- archives
# Downloads are read in memory, member by member. Nothing from an archive is ever written
# to disk by this tool, so a member name cannot escape a directory; names are still
# validated, and only regular files of bounded size are opened.

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._+\-]+(/[A-Za-z0-9._+\-]+)*$")


def safe_member_name(name: str) -> bool:
    return (bool(_SAFE_NAME.match(name)) and not name.startswith("/")
            and ".." not in name.split("/"))


class _Bounded(io.RawIOBase):
    """Read at most `limit` bytes from `fh`, then raise: bounds a decompressing reader."""

    def __init__(self, fh, limit: int):
        self.fh, self.left = fh, limit

    def readable(self):
        return True

    def readinto(self, b):
        data = self.fh.read(len(b))
        if len(data) > self.left:
            raise ValueError("archive member exceeds the size fuse")
        self.left -= len(data)
        b[:len(data)] = data
        return len(data)


def text_lines(binary_fh, gz: bool = False):
    """Iterator of text lines over a binary file object, optionally gunzipping, size-bounded."""
    fh = gzip.GzipFile(fileobj=binary_fh, mode="rb") if gz else binary_fh
    fh = io.BufferedReader(_Bounded(fh, MAX_MEMBER_BYTES), 1 << 20)
    return iter(io.TextIOWrapper(fh, encoding="ascii", errors="replace", newline=None))


def tar_members(path: str, pattern: re.Pattern):
    """Yield (name, binary file object) for regular-file members whose basename matches."""
    with tarfile.open(path, mode="r|gz") as tf:
        for m in tf:
            base = os.path.basename(m.name)
            if not m.isreg() or not safe_member_name(m.name) or not pattern.match(base):
                continue
            if m.size > MAX_MEMBER_BYTES:
                LOG.warning("%s: member %s is %d bytes, skipped", path, m.name, m.size)
                continue
            fh = tf.extractfile(m)
            if fh is not None:
                yield base, fh


def zip_members(path: str, pattern: re.Pattern):
    """Yield (name, binary file object) for zip members whose basename matches."""
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            base = os.path.basename(info.filename)
            if info.is_dir() or not safe_member_name(info.filename) or not pattern.match(base):
                continue
            if info.file_size > MAX_MEMBER_BYTES:
                LOG.warning("%s: member %s is %d bytes, skipped", path, info.filename, info.file_size)
                continue
            with zf.open(info) as fh:
                yield base, fh


def check_archive(path: str, name: str | None = None) -> None:
    """Integrity test right after download, on the .part file. Raises on a damaged archive.
    `name` is the final file name, which decides the archive type."""
    name = name or path
    if name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(path, mode="r|gz") as tf:
            for _ in tf:
                pass
    elif name.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            if bad:
                raise zipfile.BadZipFile(f"bad member {bad}")
    elif name.endswith(".gz"):
        with gzip.open(path, "rb") as fh:
            while fh.read(1 << 20):
                pass


# ----------------------------------------------------------------------------- regions

class Regions:
    def __init__(self, cfg: dict):
        self.boxes = []
        for name, r in cfg.get("regions", {}).items():
            (la0, la1), (lo0, lo1) = r["lat"], r["lon"]
            self.boxes.append((name, float(la0), float(la1), float(lo0), float(lo1)))

    def classify(self, lat: float, lon: float) -> str | None:
        if lon >= 180.0:
            lon -= 360.0
        for name, la0, la1, lo0, lo1 in self.boxes:
            if la0 <= lat <= la1 and lo0 <= lon <= lo1:
                return name
        return None


# ----------------------------------------------------------------------------- logging

def setup_logging(log_file: str | None, verbose: bool = False) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s",
                            "%Y-%m-%dT%H:%M:%SZ")
    fmt.converter = time.gmtime
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)


def shout(msg: str) -> None:
    """For conditions that stop recording: impossible to miss in the journal or the log."""
    bar = "!" * 72
    LOG.critical(bar)
    LOG.critical("!!! %s", msg)
    LOG.critical(bar)
