"""Append-only, crash-safe store for AIS records.

Format: one gzip-compressed NDJSON file per UTC day and per stream.
Each write batch is an INDEPENDENT gzip member appended to the file
(RFC 1952 allows member concatenation; gzip/zcat/python-gzip read them
transparently). Consequences:

  * worst-case data loss on hard kill = one poll cycle, never the file;
  * every member carries its own CRC32 + ISIZE -> corruption is detectable
    with `gzip -t` without any sidecar;
  * resume is "open in append mode". No rewrite, no compaction, no lock
    held across restarts.

Source of truth is the raw NDJSON. Any columnar derivative (Parquet) is a
downstream, regenerable artefact. See README.md section "Formato".
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
from datetime import datetime, timezone
from typing import Iterable, Iterator

SCHEMA_VERSION = 1

# Streams written by the recorder.
STREAM_LOCATIONS = "locations"
STREAM_VESSELS = "vessels"
STREAM_POLLLOG = "polllog"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def day_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def stream_path(root: str, stream: str, dt: datetime) -> str:
    """<root>/raw/<stream>/YYYY/MM/<stream>-YYYY-MM-DD.ndjson.gz"""
    return os.path.join(
        root, "raw", stream, dt.strftime("%Y"), dt.strftime("%m"),
        f"{stream}-{dt.strftime('%Y-%m-%d')}.ndjson.gz",
    )


def _encode_member(records: Iterable[dict]) -> bytes:
    """Serialise records as NDJSON and wrap them in one gzip member."""
    buf = io.BytesIO()
    # mtime=0 -> byte-identical output for identical input (reproducible).
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6, mtime=0) as gz:
        for rec in records:
            gz.write(json.dumps(rec, separators=(",", ":"),
                                ensure_ascii=False).encode("utf-8"))
            gz.write(b"\n")
    return buf.getvalue()


def append_batch(root: str, stream: str, dt: datetime,
                 records: list[dict]) -> tuple[int, str]:
    """Append records as one gzip member. Returns (bytes_written, sha256).

    Durability: write() + flush() + os.fsync() on the file, then fsync on the
    containing directory the first time the file is created, so the directory
    entry itself survives a power cut.
    """
    if not records:
        return 0, ""
    path = stream_path(root, stream, dt)
    directory = os.path.dirname(path)
    is_new = not os.path.exists(path)
    os.makedirs(directory, exist_ok=True)
    blob = _encode_member(records)
    with open(path, "ab") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    if is_new:
        dfd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    return len(blob), hashlib.sha256(blob).hexdigest()


def iter_records(path: str) -> Iterator[dict]:
    """Yield every record of a day file. Tolerates a truncated final member:
    a half-written tail is reported, not raised, so a crashed file still
    yields all complete records before it."""
    if not os.path.exists(path):
        return
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    # only legitimate at EOF after a hard kill
                    return
    except (EOFError, OSError, gzip.BadGzipFile):
        return


def day_files(root: str, stream: str) -> list[str]:
    base = os.path.join(root, "raw", stream)
    out = []
    for dirpath, _dirnames, filenames in os.walk(base):
        for name in sorted(filenames):
            if name.endswith(".ndjson.gz"):
                out.append(os.path.join(dirpath, name))
    return sorted(out)


def verify_file(path: str) -> dict:
    """Decompress fully and report integrity. Pure read, no mutation."""
    members = 0
    records = 0
    truncated = False
    raw_bytes = 0
    try:
        with open(path, "rb") as fh:
            data = fh.read()
        raw_bytes = len(data)
        pos = 0
        while pos < len(data):
            if data[pos:pos + 2] != b"\x1f\x8b":
                truncated = True
                break
            d = __import__("zlib").decompressobj(31)
            try:
                chunk = d.decompress(data[pos:])
            except Exception:
                truncated = True
                break
            if not d.eof:
                truncated = True
                break
            members += 1
            records += chunk.count(b"\n")
            consumed = len(data) - pos - len(d.unused_data)
            pos += consumed
    except OSError as exc:
        return {"path": path, "ok": False, "error": str(exc)}
    return {
        "path": path,
        "ok": not truncated,
        "members": members,
        "records": records,
        "bytes": raw_bytes,
        "truncated_tail": truncated,
    }
