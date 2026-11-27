# gnss_leo_recorder — navigation receivers in orbit, recorded

> **How to run it is in [../MANUAL.md, Part 0-bis](../MANUAL.md#part-0-bis--the-gnss-from-orbit-recorder),
> and only there.** This file is **architecture**: layout, formats, decisions, requirements.
> What changed and why: [../CHANGELOG.md](../CHANGELOG.md).

Records the free navigation-receiver data of satellites flying over the Baltic, so that
a drop in carrier-to-noise density (the RINEX `S` observables) over the Gulf of Finland
can be measured against a control region at the same latitude. It records and extracts;
**it does not interpret or detect** — that is the CTO's analysis, downstream.

Python ≥ 3.11, **standard library only**. The pinned environment (`../requirements-dev.txt`, built by `../venv.sh dev`)
holds the reference decoder the tests compare against; the recorder never imports it.

## Modules

| File | Role |
|---|---|
| `gnss_leo.py` | the daemon: one loop, one cycle per source, each isolated in `try` |
| `gnssctl.py` | `status`, `stats`, `verify`, `gaps`, `extract` — reads the store, writes only on `extract` |
| `source_base.py` | the day loop, manifest, disk floor, idempotence, summaries — written once |
| `src_spire.py` · `src_swarm.py` · `src_sentinel6.py` | one module per receiver source: what upstream offers, what a complete day is, how to read it |
| `src_igs.py` · `src_satjam.py` | download-only sources: navigation-satellite orbits; DTU's interference map |
| `rinex.py` · `crx.py` | RINEX 2/3 observation reader; Compact RINEX (Hatanaka) 1.0/3.0 decoder |
| `orbit.py` | SP3 and laser-ranging prediction (CPF) readers, Lagrange interpolation, WGS84 geodetic |
| `extract.py` | epochs + orbit → deduplicated region rows, 0.1 Hz global rows, day statistics |
| `common.py` | config, store layout, lock, HTTP, manifest, safe archive reading |
| `gnss_leo.toml` | every path, region, URL, cadence and licence string |
| `gnss-leo-recorder.service` | the systemd user unit |

## Data flow

```
every poll_minutes, per source, per day from history_start:
  complete? ──no──▶ remotes(day) ──▶ download → .part, sha256 on the fly, archive check,
     │                                rename, one manifest line            (disk floor first)
     ▼
  inputs changed or extractor version changed? ──yes──▶ extract_day → region rows, global rows, summary
```

A day is *complete* when every expected file is in the manifest **and** on disk at the
recorded size. Network is touched only for incomplete days inside `lookback_days`, or
for every incomplete day on the first cycle after a start and with `--since`: that is
what makes a restart resume rather than repeat.

## Store

Two roots, on purpose (sizes measured, see the MANUAL):

```
~/Documents/space_startup_datos/gnss_leo/      raw: ~210 MB/day, reproducible
  gnss_leo.lock   gnss_leo.log
  raw/<source>/YYYY/DDD/<upstream file, byte for byte>
~/Documents/space_startup_datos/gnss_leo_record/  extract: ~9 MB/day, NOT synced
  gnss_leo.lock   state.json
  manifest/<source>/YYYY/<source>-YYYY-DDD.manifest.ndjson
  extract/<source>/YYYY/<source>-YYYY-MM-DD.ndjson.gz          boxes, 1 Hz
  extract/<source>/YYYY/<source>-YYYY-MM-DD.global.ndjson.gz   everywhere, 0.1 Hz
  extract/<source>/YYYY/<source>-YYYY-MM-DD.summary.json
```

- **The manifest lives with the extract, in Dropbox.** It is the provenance — URL,
  bytes, sha256, HTTP code, content type, reception time, licence, terms URL — and it is
  what lets the raw files be re-fetched and checked if the laptop dies. Append-only.
- **The raw store is not synced.** ~6 GB/month is not worth syncing, and two of the
  three receiver sources keep their archive (Swarm since 2013; the Sentinel-6 catalogue since 2025).
  Spire's near-real-time archive retention is unknown: Spire raw is the one to back up.
- **Nothing is ever deleted** by this program. Below `min_free_gb` it stops downloading
  and shouts in the log; extraction continues.
- **One writer per store**: `flock` on `gnss_leo.lock` in *both* roots, exit code 3 if
  held — the AIS recorder's scheme.

## Sources

| | Spire (NOAA, served by UCAR) | Swarm A, B, C (ESA) | Sentinel-6A, -6B (EUMETSAT) |
|---|---|---|---|
| Observations | `level1a/…/podCrx_nrt_YYYY_DDD.tar.gz`: one Compact RINEX 2.11 per receiver pass | `GPSx_RO_1B`: one RINEX 3.00 per satellite-day, in a ZIP | `GN_1B_RNXH_AX`: one RINEX 3 (`MO`, gzip) per satellite-hour, in a ZIP |
| Orbit | `level1b/…/leoOrb_nrt_YYYY_DDD.tar.gz`: SP3 per pass, 60 s | `MODx_SC_1B`: SP3, 1 s — the epochs themselves | laser-ranging prediction (CPF) issued daily by EUMETSAT, served by EDC, 180 s |
| Sampling | 1 s | 1 s | 1 s |
| Published | once a day, D+1 ~07:40 UTC | once a day, D+4 ~00:20 UTC | hourly, ~45 min after the hour |
| Account | no | no | **yes** (free): disabled until credentials exist |
| Listing | Apache index per day | JSON listing, read in 80-entry pages near the date | public OpenSearch catalogue |

**Not taken from UCAR** (`status` lists them): `leoAtt` (attitude, ~80 MB/day; a one-line
config change), `conPhs` (~1 GB), `podTec` (~545 MB, netCDF) and `opnGns` (~2 GB/day,
open-loop occultation) — the last one **refused in code** even if added to the config.

**Download-only, not extracted:**

| | What | Size | Why |
|---|---|---|---|
| `igs_orbits` | `IGS0OPSRAP` (IGS rapid, GPS, 15 min, BKG) and `GFZ0OPSRAP` (GFZ rapid, GPS + Galileo + GLONASS, 5 min, GFZ ISDC), daily, ~17 h after the day | 0.78 MB/day | elevation of each navigation satellite seen from the receiver. IGS's rapid has no Galileo, hence GFZ's |
| `satjam` | the 9 public JSON of sat-jam.com (DTU), rolling 30-day aggregates per Sentinel satellite and constellation | 20.9 MB/night | external reference. A snapshot: only today's can be fetched, so it is taken once a UTC day after 04:00 |

## Extract format — the contract with the CTO

Two gzip NDJSON per source and **upstream product day** (Spire's directory day, Swarm's
file date, Sentinel-6's GPS day), same row format:

- **region rows**, `.ndjson.gz`: every epoch whose sub-satellite point is in a box, 1 Hz;
- **global rows**, `.global.ndjson.gz`: one epoch per receiver per 10 s window
  (`global_decimate_s`), everywhere — the baseline outside Europe and the Atlantic
  horizon test need it. `reg` is null outside the boxes; position is null when the orbit
  is missing (the epoch is still there).

**Repeated epochs are written once.** Spire's pass files overlap: on 13-Nov, 255,666 of
875,661 epochs read (29.2 %) were repeats of the same receiver and instant; all but 101
identical. The first read is kept; the summary counts `duplicates` and
`duplicates_conflicting`. Within a day only: a handful of rows near midnight carry the
neighbouring UTC date, so deduplicate on `(rx, gps_s)` when joining days.

| field | meaning |
|---|---|
| `t` | UTC, ISO-8601 ms. Files are in GPS time; GPS − UTC = 18 s |
| `gps_s` | the same instant, GPS seconds since 1980-01-06 — exact, use it for joins |
| `src`, `rx` | source module; receiver satellite: `spire-173`, `swarm-A`, `sentinel6-B` |
| `reg` | region box the sub-satellite point falls in (`baltic`, `control`); null in global rows outside both |
| `lat`, `lon`, `alt_km` | sub-satellite point and height, WGS84, from the orbit; null if no orbit (global rows only) |
| `n_sv` | navigation satellites in the epoch record (tracked) |
| `cn0` | `{"G05": {"S1C": 44.5, "S2L": 30.2}}`: every `S` observable, **RINEX 3 names**, file units, as written. Zero or blank omitted |
| `file` | upstream file the epoch came from (its sha256 is in the manifest) |

An epoch whose orbit is missing is counted as `no_position`, never guessed. The summary also records, per
receiver: epochs, rows per region, UTC hours with data, `S` codes seen; per day: inputs
with sha256, header observable lists, unreadable files with the reason.

**Values are stored literally**, including the non-physical ones the sources do write:

| Source | Signal-strength observables | What the data does |
|---|---|---|
| Spire | `S1C`, `S2L` (written as RINEX 2 `S1`, `S2`; mapped back from the conversion table in the header) | two independent frequencies; ~1 value in 12,000 is non-physical (−164 to +338 dB-Hz); 29 % of epochs repeated across files (dropped, counted) |
| Swarm | `S1C`, `S1W`, `S2W` | **`S1W` and `S2W` are one number written twice**: equal in 637,454 of 637,454 pairs on 13-Nov. `S1W` takes a constant −3.68 when L2 is lost (1.3 % of the day). Only `S1C` is a clean C/A carrier-to-noise |
| Sentinel-6 | unknown until the first file: the catalogue says `MO` (mixed constellations), 1 s, RINEX 3 gzip | the parser takes every `S` code the header declares, per system `[VERIFICAR with the first file]` |

## Decisions

- **Our own Hatanaka decoder, not the `hatanaka` package at run time.** The package is a
  C decoder fed with untrusted bytes; ours is ~100 lines of Python that cannot overflow a
  buffer. It decodes to values instead of rebuilding RINEX text. Checked value by value
  against the pinned C reference on all 298 non-empty Spire files of 13-Nov: **875,661
  epochs, zero differences**; CRINEX 3 checked by round trip through the reference
  compressor. A Spire day decodes in ~30 s.
- **Archives are read in memory, member by member; nothing from a download is ever
  written to disk except the download itself.** A member cannot escape a directory that
  is never extracted to. Names are still validated, links and devices skipped, and every
  member read through a 1 GiB decompression fuse.
- **`python3 -I`** for everything that reads downloads; the scripts put back only their
  own directory on `sys.path`.
- **A gap in the orbit is not bridged.** Interpolation runs inside a contiguous run of
  samples only (gap > 2.5 steps cuts). Measured on Swarm's 1 s orbit, decimated:
  9th-order Lagrange reproduces it to 1 cm at Spire's 60 s step and 0.37 m at the
  Sentinel-6 prediction's 180 s. Over 10 days, **1.3 % of unique Spire epochs have no
  orbit** — passes UCAR published without `leoOrb` — counted, kept in the global series
  with null position, never in the boxes.
- **Sentinel-6's orbit comes from the laser-ranging prediction** because the RINEX has no
  position, EUMETSAT publishes no open orbit product (none among the 197 collections
  of its Data Store; 26 are Sentinel-6, all altimetry, radiometry or occultation besides
  this one), and the CPF is open, daily, Earth-fixed and issued by EUMETSAT itself.
  Predicted, not reconstructed: metres to tens of metres on its first day, far below
  what decides a region box.
- **Sentinel-6 checksum is advisory.** The catalogue's md5 cannot be checked against a
  real download without an account; a mismatch is recorded in the manifest and logged,
  while size and ZIP integrity are what refuse a file.

## Requirements

| # | Requirement | Verification |
|---|---|---|
| REQ-GNSS-001 | Each source runs isolated: an exception in one never stops the others | `try` per source cycle and per day; Sentinel-6 disabled while the others record |
| REQ-GNSS-002 | Every downloaded file has one manifest line: url, bytes, sha256, HTTP, content type, reception time, licence, terms URL | `gnssctl verify` |
| REQ-GNSS-003 | A file is renamed into the store only whole: size = Content-Length, archive test passed | `download()`; `.part` otherwise |
| REQ-GNSS-004 | Nothing is deleted automatically. Below 15 GB free, raw downloads stop with a CRITICAL banner every cycle | `test_disk_floor_blocks_download_and_shouts` |
| REQ-GNSS-005 | Idempotent and resumable: a held file is never fetched again; a day is re-extracted only when its inputs or the extractor version change | `needs_extract`; restart and compare |
| REQ-GNSS-006 | One writer per store | `test_single_writer_lock` (exit 3) |
| REQ-GNSS-007 | Downloads are never executed and never unpacked to disk; member names validated; size fuse | `TestArchiveSafety` |
| REQ-GNSS-008 | Generic user agent, no names or addresses | `user_agent` in the TOML |
| REQ-GNSS-009 | The Compact RINEX decoder equals the reference decoder | `TestCrxAgainstReference` (`GNSS_LEO_FULL_TESTS=1`: all files) |
| REQ-GNSS-010 | Every extracted row is inside its region box; values are the file's, unconverted | `_check_rows` |
| REQ-GNSS-011 | Missing credentials disable Sentinel-6 with the reason in log, state and `status` | `test_disabled_without_credentials` |
| REQ-GNSS-012 | Upstream silence is visible: no new Spire day for > 3 days logs `NO NEW FILES` | `test_stale_upstream_is_logged` |
| REQ-GNSS-013 | An epoch is written once per receiver and instant; repeats and conflicting repeats are counted | `TestExtractSpire` (255,666 and 101 on 13-Nov) |
| REQ-GNSS-014 | A 0.1 Hz global series, one row per receiver per 10 s window, with or without position | `_check_global` |
| REQ-GNSS-015 | `opnGns` is never downloaded | `test_opngns_is_refused` |

### What these requirements do not cover

- **No interference detection, no thresholds, no elevation or antenna-gain correction.**
  Carrier-to-noise from orbit depends on the navigation satellite's elevation and the
  receiving antenna's pattern; the extract keeps what is needed to compute both later
  (receiver position, time, satellite numbers) and `igs_orbits` keeps the navigation
  satellites' orbits, but **elevation is not in the rows** (pending, MANUAL Part 0-bis).
- **Spire attitude is not recorded by default**, so antenna orientation is unknown for
  Spire unless `leoAtt` is switched on.
- **Spire raw has no guaranteed upstream archive.** If UCAR stops publishing — NOAA's
  delivery order covers data until 2026-12-01 — what is in `raw/` is all there is.
