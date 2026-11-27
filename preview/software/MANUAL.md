# Custody — User Manual

**One manual for the whole system.** Two programs, one job:

| | | |
|---|---|---|
| `ais_recorder/` | the **writer** | records AIS continuously; the only irreplaceable thing here |
| `custody_mvp/` | the **reader** | builds, serves and draws everything derived from it |

They were documented separately until 2026-11-14, and that is exactly how the
writer and the reader ended up with different ideas of where the store lives —
4.6 hours of recording invisible, with no error in any log. One manual, one
changelog, one `config/custody.toml`.

A research prototype that fuses open data over the Baltic and asks one question:
**where should expensive satellite imagery be pointed, and what can open data actually prove?**

It records AIS continuously, overlays Copernicus Sentinel-1 radar and Sentinel-2 optical on
demand, maps the subsea cables and pipelines underneath, and raises six behavioural indicators
over them. Every vessel carries a dossier: exact dimensions from its own AIS broadcast, a
photograph where one exists under a free licence, and a match against sanctions lists.

Not an operational system. Every number on screen traces to a named public source, the
thresholds are first guesses clearly labelled as such, and anything that failed to load says so
with its literal reason instead of being hidden.

Changes and the reasoning behind them: [CHANGELOG.md](CHANGELOG.md).

---

## Contents

**Part 0 — The recorder**

0. [The recorder — the only irreplaceable part](#0-the-recorder--the-only-irreplaceable-part)

**Part 0-bis — The GNSS-from-orbit recorder**

0-bis. [Navigation receivers in orbit, recorded](#0-bis-navigation-receivers-in-orbit-recorded)

**Part I — Running it**

1. [Start it](#1-start-it)
1b. [Python and its two dependencies](#1b-python-and-its-two-dependencies)
2. [The satellite tile cache](#2-the-satellite-tile-cache)
2b. [Where things live on disk, and what to back up](#2b-where-things-live-on-disk-and-what-to-back-up)
2c. [Tests](#2c-tests)
2d. ["The timeline looks empty at the right"](#2d-the-timeline-looks-empty-at-the-right)
2e. [Alerts in real time](#2e-alerts-in-real-time)
2f. [The forcing — wind, wave, current and ice](#2f-the-forcing--wind-wave-current-and-ice)
2g. [Coverage held by others](#2g-coverage-held-by-others)
3. [Troubleshooting](#3-troubleshooting)

**Part II — Using it**

4. [The interface](#4-the-interface)
4b. [How far the map reaches, and how far we can hear](#4b-how-far-the-map-reaches-and-how-far-we-can-hear)
4c. [Focusing on one basin](#4c-focusing-on-one-basin)
4d. [Depth, painted for this sea](#4d-depth-painted-for-this-sea)
5. [First five minutes](#5-first-five-minutes)
6. [Time — what instant am I looking at](#6-time--what-instant-am-i-looking-at)
7. [Sentinel-1 and Sentinel-2 on the map](#7-sentinel-1-and-sentinel-2-on-the-map)
8. [Vessel situation — one click](#8-vessel-situation--one-click)
8b. [Vessel history — the Pathfinder view](#8b-vessel-history--the-pathfinder-view)
9. [The declared route](#9-the-declared-route)
10. [Reading an alert](#10-reading-an-alert)
11. [Colour and ordering of alerts](#11-colour-and-ordering-of-alerts)
12. [Filters — the operator console](#12-filters--the-operator-console)
13. [Large files load on demand](#13-large-files-load-on-demand)
14. [Suppressed detections — what the layer is, and is not](#14-suppressed-detections--what-the-layer-is-and-is-not)

**Part III — The data**

15. [The seven indicators](#15-the-seven-indicators)
16. [What is "NATO WARSHIP"?](#16-what-is-nato-warship)
17. [Showing the provenance](#17-showing-the-provenance)
17b. [Adding another HELCOM layer](#17b-adding-another-helcom-layer)
17c. [Licences — what can actually be sold](#17c-licences--what-can-actually-be-sold)
18. [Copernicus CDSE — what it is, and whether you need it](#18-copernicus-cdse--what-it-is-and-whether-you-need-it)
19. [Global Fishing Watch — a second opinion](#19-global-fishing-watch--a-second-opinion)
20. [Vessel dossier — size, photos, sanctions](#20-vessel-dossier--size-photos-sanctions)
21. [The seabed, and the submarine question](#21-the-seabed-and-the-submarine-question)
22. [Detecting ships in the SAR image](#22-detecting-ships-in-the-sar-image)
23. [Reconstructing the cable incidents](#23-reconstructing-the-cable-incidents)
24. [What this tool cannot do](#24-what-this-tool-cannot-do)
25. [Making it yours](#25-making-it-yours)
26. [Skylight — can I integrate it, and is it free?](#26-skylight--can-i-integrate-it-and-is-it-free)
27. [Where the data comes from](#27-where-the-data-comes-from)

---

# Part 0 — The recorder

## 0. The recorder — the only irreplaceable part

Everything else in this repository can be rebuilt. The recording cannot: nobody
can re-record 10 November 2026. This is the part that matters most and changes
least.

Source: **Fintraffic / digitraffic.fi, CC BY 4.0**. That literal string must
appear in any derived material, hackathon pitch included.

### Running it

```bash
cd software/ais_recorder
python3 recorder.py                          # 60 s cadence, store from the config
setsid nohup python3 -u recorder.py > recorder.log 2>&1 < /dev/null &   # survives the terminal
./stop.sh                                    # clean stop: finishes the cycle, fsyncs, verifies
pgrep -af 'recorder\.py'                     # alive?
```

**Where every path lives.** Two config files, and nothing hardcoded anywhere else:

| File | Read by | Holds |
|---|---|---|
| `custody_mvp/config/custody.toml` | the app and the AIS recorder | `record`, `cache`, `data`, and the watch list |
| `gnss_leo_recorder/gnss_leo.toml` | the orbit recorder | `raw_root`, `extract_root`, the sources |
| `<repo>/rutas.toml` | the analysis scripts, in **both** repos | the other two trees, and each store by name |

The third one exists because the research scripts moved to a separate repo on
2026-11-24 and can no longer reach these two by walking up directories. It lives
**inside the repo**, not in `~/.config`: the project is self-contained and moves to
another machine by copying folders. `repo` is not in it — that is derived from where
`rutas.py` sits. The research tree's own root carries a one-line `rutas_enlace.toml`
saying where the repo is, which is the only other pointer in the system.

`python3 rutas.py` prints what it resolves and names the path that is missing;
`SPACE_STARTUP_RUTAS=other.toml` points it elsewhere for a dry run.
**When something moves, one of these files changes and no code does.**

**It takes its store from `custody_mvp/config/custody.toml`**, the same file the
app reads, and logs which root it used and where that came from:

```
store root /home/jona/Documents/space_startup_datos/ais_record (from .../config/custody.toml)
resume: 340594 records already in locations-2026-11-13.ndjson.gz
```

A `--root` that is not the configured one is **not blocked** — it may be
deliberate — but it logs a warning with the command to merge the result back.
That warning exists because its absence cost 4.6 hours of invisible recording.

`AIS_DATA_ROOT` still overrides, then `--root`. Order, strongest first:
`--root` → `AIS_DATA_ROOT` → `config/custody.toml` → the recorder's own `data/`.

**Restarting does not duplicate or lose anything**: the dedup index is rebuilt
from the day's file and writing resumes in append mode. Verified again on
2026-11-14, resuming onto a file that had just been merged into.

### Surviving a laptop reboot — it does not, and that is the decision

**Nothing is installed, and nothing is to be installed.** Standing instruction from the
owner, 2026-11-24: no service, no daemon, nothing that runs on its own. Both recorders are
started by hand, in a terminal, and they stop when that terminal or the session does.

Price, stated plainly so nobody is surprised by it later: **a reboot stops the recording
and nothing starts it again.** The archive gap that follows is silent until somebody looks.
Before trusting any date, check coverage:

```bash
cd software/ais_recorder && python3 aisctl.py gaps
cd software/gnss_leo_recorder && python3 -I gnssctl.py status   # incomplete days
```

Upstream retention is the deadline for noticing: Fintraffic keeps **no history at all**, so
an AIS gap is lost the moment it happens; Spire keeps about 10 days, so an orbit gap caught
inside that window can still be filled.

An example unit is kept in the repo at
`gnss_leo_recorder/gnss-leo-recorder.service.ejemplo`, uninstalled, in case that decision
is ever reversed.

### What it writes

```
<record>/
  recorder.lock                 exclusive flock, one writer per root
  raw/<stream>/YYYY/MM/<stream>-YYYY-MM-DD.ndjson.gz
  summary/YYYY-MM-DD.json       written by aisctl, not by the recorder
```

| stream | source | one record is |
|---|---|---|
| `locations` | REST `/api/ais/v1/locations`, 60 s | one position fix |
| `vessels` | REST `/api/ais/v1/vessels`, 600 s | static metadata, deduplicated by content |
| `polllog` | — | one poll attempt: HTTP, bytes, new, sha256 of the block |
| `mqtt_locations` / `mqtt_metadata` | MQTT `vessels-v2/+/…` | one emitted message (optional, needs `paho-mqtt`) |

**NDJSON, gzip, one independent gzip member per write cycle.** Field names are
the API's, unrenamed and unconverted; the recorder only adds `rx_ms` and
`rx_dataUpdatedTime`. That format choice is what makes the merge below a
non-event — see `ais_recorder/README.md` for why NDJSON.gz and not Parquet.

### Querying it

```bash
cd software/ais_recorder
python3 aisctl.py summary --write            # last day, written into summary/
python3 aisctl.py stats                      # disk used and measured monthly projection
python3 aisctl.py verify                     # gzip CRC over every file
python3 aisctl.py track --mmsi 273273150     # one vessel, chronologically
python3 aisctl.py export --date 2026-10-28 --out gof.csv --bbox 22.0,59.0,30.5,60.8
python3 aisctl.py sqlite --out ais.sqlite    # SQL interface for the custody engine
python3 aisctl.py gaps --threshold 1800      # continuity report
```

It reads the configured store by default and **never writes into `raw/`**. The
one tool that does is `merge_store.py` — §2b.

---

# Part 0-bis — The GNSS-from-orbit recorder

## 0-bis. Navigation receivers in orbit, recorded

Spire, Swarm and Sentinel-6 carry navigation receivers whose raw observations are
published free. Their signal-strength observables (carrier-to-noise density, RINEX `S`)
are what the CTO's test needs: does it drop when the satellite is over the Gulf of
Finland, against a control region at the same latitude? This recorder builds that series,
continuous and with provenance. **It records and extracts; it interprets nothing.**
Architecture, extract format and requirements: [gnss_leo_recorder/README.md](gnss_leo_recorder/README.md).

Like the AIS store, what it records from Spire may become unrecoverable (below).

### Running it

You start it yourself, from a terminal. There is **no service**: the systemd unit was
removed on 2026-11-24 — nothing of this project is installed on the machine any more.

```bash
cd software/gnss_leo_recorder
python3 -I -u gnss_leo.py                          # run forever, in the foreground
python3 -I gnss_leo.py --once                      # one pass over every source, then exit
python3 -I gnssctl.py status                       # what it has, what is missing
tail -f ~/Documents/space_startup_datos/gnss_leo/gnss_leo.log
```

**What you give up by not running it as a service, and it is the whole point of a
recorder:** nothing restarts it after a crash or a reboot, so a gap in the archive is now
a gap nobody is told about. `gnssctl.py status` lists the incomplete days — run it before
you trust a date. Spire keeps about 10 days upstream (`lookback_days`), so a gap noticed
within that window can still be filled; after that it is gone.

If you ever want it supervised again, the unit is kept in the repo, not installed:

```bash
cp gnss-leo-recorder.service.ejemplo ~/.config/systemd/user/gnss-leo-recorder.service
systemctl --user daemon-reload && systemctl --user enable --now gnss-leo-recorder
```

**Backfill.** Lower `history_start` in `gnss_leo.toml` and restart: the first cycle after
a start fetches every incomplete day from there. Or, with the service stopped,
`python3 -I gnss_leo.py --once --since 2026-11-01`. One writer per store: a second
instance exits with code 3.

**`-I` is not optional** on any command that reads downloads (all of them do): it keeps
Python from importing anything from the current directory or the environment.

### What it writes

| | Where | Size, measured | Backed up |
|---|---|---|---|
| raw | `~/Documents/space_startup_datos/gnss_leo/raw/<source>/YYYY/DDD/`, upstream bytes unchanged | 191 MB/day (Spire 95, Swarm 95, orbits 0.8); +21 SAT-JAM from its first night, +51 with Sentinel-6 | **no** |
| manifest | `~/Documents/space_startup_datos/gnss_leo_record/manifest/` — url, bytes, sha256, HTTP code, content type, reception time, licence, terms URL, one line per file | ~1 KB/day | **no** |
| extract, boxes | `…/gnss_leo_record/extract/<source>/YYYY/<source>-YYYY-MM-DD.ndjson.gz` | 1.7 MB/day (Spire 0.97, Swarm 0.75) | **no** |
| extract, global | `….global.ndjson.gz` next to it | 6.9 MB/day (Spire 4.5, Swarm 2.4) | **no** |
| summary | `….summary.json`: inputs with sha256, epochs, repeats, rows, hours with data | ~10 KB/day | **no** |

That last column used to read *yes* for everything but `raw`, because `gnss_leo_record`
lived inside Dropbox. Since 2026-11-24 it does not: **nothing here has a second copy
anywhere.** The raw downloads can be fetched again and the extracts rebuilt from them;
the AIS store in `ais_record/` cannot be recovered by anyone, and it is the one thing to
back up by hand.

The box extract holds every epoch (1 Hz) whose sub-satellite point is in **`baltic`**
(50–72 N, 5–50 E: Baltic, Gulf of Finland, Kaliningrad, St Petersburg) or **`control`**
(50–72 N, 130–60 W: Canada, no known interference); boxes in `gnss_leo.toml`. The
**global** extract holds one epoch per receiver every 10 s (0.1 Hz) everywhere, for
baselines outside Europe — asked by the CTO on 20-Nov after finding that a source near
51 N 36 E dominates and its horizon reaches Norway (`canal/iteracion_06/02_cto_datos_abiertos.md`).
**Repeated epochs are written once**: Spire's pass files overlap and ~30 % of its epochs
arrive twice; the summary counts them (`duplicates`, and `duplicates_conflicting` for the
few whose values differ). Field list in the README. Quick look:

```bash
zcat ~/Documents/space_startup_datos/gnss_leo_record/extract/swarm_esa/2026/swarm_esa-2026-11-13.ndjson.gz \
  | jq -c 'select(.reg=="baltic" and .lon>22 and .lat>59) | {t, rx, lat, lon, cn0}' | head
```

**Nothing is ever deleted automatically.** Below **15 GB** free on the raw disk, raw
downloads stop and every cycle writes a `!!! DISK FLOOR` banner at CRITICAL; extraction
continues. `gnssctl stats` gives the days left. On 20-Nov: 61.6 GB free, **244 days** at 191 MB/day; ~180 with SAT-JAM and Sentinel-6.

### Querying it

```bash
python3 -I gnssctl.py status                       # service, locks, each source, last log lines
python3 -I gnssctl.py stats                        # disk, measured MB/day per source, 30-day projection
python3 -I gnssctl.py verify                       # sha256 of every raw file vs manifest; extract CRC and rows
python3 -I gnssctl.py gaps                         # days missing or partial; receivers silent >= 6 UTC hours
python3 -I gnssctl.py extract --date 2026-11-13 --out /tmp/x   # re-extract while the service runs
```

`extract` without `--out` writes into the store, so it refuses while the service holds the
lock. The service re-extracts a day by itself when its inputs or the extractor version change.

### Sources and licences

| Source | Account | Day D appears | Raw, MB/day measured | Signal strength |
|---|---|---|---|---|
| **Spire**, bought by NOAA, served by UCAR | no | D+1, ~07:40 UTC | 95 | `S1C`, `S2L`, 21 receivers |
| **Swarm** A, B, C (ESA) | no, to download | D+4, ~00:20 UTC | 95 (3 × 27.3 observations + 3 × 4.3 orbit) | `S1C`; `S1W` = `S2W`, one value |
| **Sentinel-6** A, B (EUMETSAT) | **yes** | ~45 min after each hour | 51 (catalogue: 2 × 24 × ~1.07 MB) | unknown until the first file |
| **Navigation-satellite orbits**: IGS rapid (GPS, BKG) + GFZ rapid (GPS, Galileo, GLONASS) | no | D+1, ~17:00 UTC | 0.78 | — (kept for elevation, not extracted) |
| **SAT-JAM** (DTU), 9 JSON, rolling 30 days | no | captured once a night after 04:00 UTC | 20.9 | — (external reference, not extracted) |

Licences, as concluded by Compliance on 2026-11-20 ([canal/iteracion_06/07_compliance.md](../canal/iteracion_06/07_compliance.md) §A):

| | Commercial use | Raw redistributed | Derived (our extract, an index) | Attribution |
|---|---|---|---|---|
| **Spire-NOAA** | yes | yes | yes | cite doi:10.5065/1a8d-yh72 (UCAR) |
| **Swarm** | yes, under an ESA account and its terms | **only to whoever accepts ESA's terms — never openly** | yes | «© ESA (year)»; *"Data provided by the European Space Agency (ESA)"* |
| **Sentinel-6** | yes, Copernicus licence | yes | yes | *"Contains modified Copernicus Sentinel data [year]"* |

Two conditions that change what you do:

- **Swarm raw stays out of anything public** — repository, hackathon, web. `raw/` is
  outside Dropbox for size; this is a second reason. Publish the extract or a derived
  index with «© ESA», or link to ESA. Two raw Swarm files do live in `canal/`, as test
  fixtures (iteration 05's `GPSA_RO` and iteration 06's `MODA_SC`, both 13-Nov): internal
  only, never in a public copy of the repository.
- **Spire after 1 December 2026 is not settled.** NOAA's current order (delivery order 6) delivers until then;
  whether UCAR keeps publishing, and under which licence, is `[VERIFICAR]`. The recorder
  logs `NO NEW FILES` at WARNING every cycle once no new Spire day has arrived for
  3 days, and `status` shows it. Until then, Spire raw has no known upstream archive:
  **it is the one part of `raw/` worth backing up.**

Three auxiliary sources, not yet reviewed by Compliance (`[VERIFICAR]`):

- **Sentinel-6 orbit**: the laser-ranging prediction EUMETSAT issues daily, served by EDC
  (DGFI-TUM). Neither site publishes a licence: silence, not permission — ask before
  selling (same rule as §17c).
- **IGS rapid orbit**: *"openly available for use without restriction … free of cost or
  obligation"*, citing IGS and the providers (IGS terms of use, 2020). The GFZ file is
  GFZ's IGS analysis-centre product; its own terms were not found.
- **SAT-JAM**: *"a research product made available to the public free-of-charge"*, no
  licence, asks to be cited as *Bostani Nezhad, K. (2026). SAT-JAM: Satellite GNSS
  Interference Map. https://sat-jam.com*; contains modified Copernicus Sentinel data.
  Internal reference only: ask DTU before redistributing or selling.

The licence strings copied into each manifest line are those of `gnss_leo.toml` at
download time and still carry the earlier `[VERIFICAR]` wording; the table above prevails.

### Turning Sentinel-6 on

Disabled until credentials exist. The log says so at start and every 24 h, and `status`
prints the reason; Spire and Swarm are unaffected.

1. Free account at EUMETSAT: <https://eoportal.eumetsat.int>. An account is personal and
   accepts the Copernicus terms: the company's, not borrowed.
2. Consumer key and secret: <https://api.eumetsat.int/api-key>.
3. Store them outside the repository, readable only by you:
   ```bash
   mkdir -p ~/.config/gnss_leo_recorder
   cat > ~/.config/gnss_leo_recorder/eumetsat.toml <<'EOF'
   consumer_key = "…"
   consumer_secret = "…"
   EOF
   chmod 600 ~/.config/gnss_leo_recorder/eumetsat.toml
   systemctl --user restart gnss-leo-recorder
   ```
   (`EUMETSAT_CONSUMER_KEY` / `EUMETSAT_CONSUMER_SECRET` in the environment also work.)
4. `gnssctl status` shows `sentinel6_eum ENABLED`. The first cycle fetches the last 3 days
   (`lookback_days`); to go further back, lower `history_start`. The catalogue holds
   data since November 2025.
5. **Check the first file**: the extract summary lists the header's observables under
   `header_obs_types`. The parser takes every `S` code per system, but which ones
   Sentinel-6 writes is unknown until then.

### Limits

- **Latency is the source's**: Spire a day, Swarm four, Sentinel-6 an hour. Today's
  Baltic is never in the record today, except Sentinel-6 once enabled.
- **1.3 % of Spire epochs have no orbit** (passes published without `leoOrb`): counted in
  the summary, kept in the global series without position, never in the boxes. Spire attitude is not recorded (`leoAtt`, +80 MB/day, one
  config line), so the antenna's orientation is unknown.
- **Values are stored as written**, including the non-physical ones: Spire ~1 in 12,000
  values between −164 and +338 dB-Hz; Swarm `S1W` a constant −3.68 when L2 is lost.
  **Swarm's `S1W` and `S2W` are the same number** (637,454 of 637,454 pairs): one
  semi-codeless measurement, not two frequencies. Use `S1C` for Swarm.
- **Spire records in passes, not continuously**: each receiver has data in roughly 3–16
  of 24 UTC hours. `gnssctl gaps` lists them per receiver; they are upstream's, not ours.
- **Day files follow the upstream product day**; a few rows near midnight carry the
  neighbouring UTC date. Join on `gps_s`.
- **The laptop must be on.** Upstream keeps Swarm (since 2013) and the Sentinel-6
  catalogue, so a gap there is refilled on the next start; for Spire, only while UCAR
  keeps the day; for SAT-JAM, never — a missed night is lost.
- **Never downloaded:** Spire `opnGns` (~2 GB/day), refused in code even if configured.

### Pending

| Asked by | What | Why not yet |
|---|---|---|
| CTO, 20-Nov | Elevation of each navigation satellite in every row | The orbits are stored daily (`igs_orbits`) but arrive ~17 h after the day; putting elevation in the rows means re-extracting each day once its orbit lands. Today the CTO computes it from the stored orbits |
| CTO, 20-Nov | GPSJAM every day | Custody already reads it (§2f-ter); not duplicated here |

---

# Part I — Running it

## 1. Start it


One entrypoint runs everything — recorder, build, viewer:

```bash
cd software
./custody.sh up        # start recorder, build if missing, serve the map
./custody.sh status    # what is running, how much data, how fresh, credentials
./custody.sh down      # stop viewer and recorder
./custody.sh build     # rebuild the fused layers only
./custody.sh serve stop # viewer only
./custody.sh logs      # tail the recorder log
```

`CUSTODY_PORT` changes the port (default 8000). **The store and the build output come from
`custody_mvp/config/custody.toml`**, not from this script: it hardcoded
`${AIS_DATA_ROOT:-$HOME/ais_data}` and passed it to the recorder with `--root`, which made
the launcher a third opinion on where the data lives — and the one that won. `AIS_DATA_ROOT`
still overrides, deliberately, but only when you set it.

Under the hood: `custody_mvp/viewer/serve.sh` keeps a PID file per port, so `stop` always kills
the right process and a second `start` is a no-op instead of a second server. It runs
`viewer/server.py`, which is multi-threaded and caches satellite tiles on disk — see §2. The
recorder stops through `ais_recorder/stop.sh`, which waits for the current cycle to `fsync`
before exiting.

Open <http://127.0.0.1:8000>. No account, no API key, no internet needed after the build —
everything is local, including the map library.

**Every time in this tool is UTC**, and the offset label is glued to it — `2026-11-12
21:47Z`. That is how AIS reports, how Sentinel acquisitions are stamped and how an incident
report is written, so it is the default and it is what you should quote. If you would
rather read wall-clock time, **Settings → Time zone** offers this computer's offset, EET,
CET and MSK; the label changes with it (`+02:00`) so you always know which clock you are
on. The thing this prevents is not reading the wrong hour — it is correlating a radar pass
against an AIS fix two hours apart without noticing.

**Sentinel-1 radar is on from the first second**, in mosaic mode — most recent pass wins
wherever they overlap — with *Follow the time cursor* off. It is the layer that answers the
product's question (what is on the water that AIS does not report), so starting with it off
meant three clicks before seeing anything. Sentinel-2 stays off: optical is useless at night
and under cloud, which above 60°N is most of the year.

> **It does not draw at the opening zoom, and it says so on the map.** Planetary Computer's
> mosaic tiler renders nothing below zoom 8 — from z3 to z7 it answers `204 No Content`
> whatever the tilejson's `minzoom` claims. Below z8 Leaflet therefore requests z8 tiles and
> scales them, and each level out quadruples how many it needs: **96 tiles at z7, 168 at z6,
> 241 at z5**. At z5 — the opening view — it does not fail, it just takes minutes and looks
> like a chequerboard while it loads. So the floor is z6, and at z5 an amber note on the map
> says the radar is on and one scroll away. The note stays until the condition clears; a
> six-second flash is for events, not for states.

Two layers *do* reach the network and are **off by default**: the OSM basemap and the EMODnet
bathymetry WMS. They live in the **Layers** tab, labelled with the host they call.

### The coastline and the depth contours are HELCOM's

Both used to be derived in the build from the EMODnet depth grid with marching squares —
at **0.03°, about 3 km**. HELCOM publishes both, measured, so the derivations were deleted.

| | source | detail |
|---|---|---|
| **Coastline** | HELCOM `MADS/Background` layer 13 | 8 m between vertices at source |
| **Depth contours** | HELCOM layer 14, from the Baltic Sea Bathymetry Database | 10, 20, 50 and 100 m |

The 80 m contour the old code drew does not exist in HELCOM's data; 10 m appears instead,
which is the level that marks where a medium-draught hull starts having a problem.

**Both are baked into the build, not fetched while you pan.** That is the strongest form
of cache: once compiled there is no network, which is a property this tool sells. Islets
shorter than 4 km are dropped, because the cost of a coastline is the *number of pieces*
rather than the number of vertices — one 4°×2° box is 7,392 separate polylines — and at
overview scale a 300 m islet is smaller than a pixel. Whole Baltic: coastline 984 kB,
contours 402 kB.

**HELCOM coastline, full detail** is the same source without the islet filter, fetched by
the square as you pan once you zoom past 8. It is not imported whole because at native
detail one 1°×0.5° square is 3.7 MB and the AOI would be around **1.8 GB**; generalised
server-side to match the zoom the same square is 254 kB, and each square is cached on disk,
so the second visit to a stretch of coast costs nothing.

**One thing this changed beyond the map.** The coastal index that stops IND-03 flagging
loitering within 1 NM of shore is built from this coastline, so it went from 11,417
segments to **35,945**. The indicator got better by deleting code, not by adding any.

### Finding a layer among sixty-six

There are **66 toggleable layers**. They used to be four flat lists in one scroll —
the build's, Copernicus Marine's 22, EMODnet's 12 and eight written by hand in the
HTML — with three separate grouping loops doing the same job. Finding one meant
reading all of them.

Now there is one catalogue and one panel, with **collapsible groups**. The rule is
**three clicks to anywhere**: tab → open the group → tick the layer. Nothing is
further away than that. Typing in the search box cuts it to one click plus two
letters, which for sixty-six layers is what actually gets used — and search
auto-expands the matching groups, because hiding a result behind a triangle is the
opposite of searching. It matches the name, the explanation *and* the source, so
`cable` finds the OSM corridors and EMODnet's telecom and power cables together,
even though none of them share a name.

**Two axes, not one.**

| | Groups by | Use it for |
|---|---|---|
| **By purpose** (default) | what question the layer answers | Finding something. An operator looks for "the cables", not "the EMODnet ones" |
| **By source** | who publishes it | Provenance and licensing. All of EMODnet together, all of Copernicus Marine together |

They are two views of the **same** catalogue — switching changes one grouping key.
Having both costs a line of code and settles the argument about which is right,
because it depends on the question. The choice is remembered, and so is which
groups you left open.

Each group header carries two numbers: **how many layers it holds** and **how many
are on**, the second visible while the group is closed. That is what stops you
opening nine groups to find the one you left enabled. **Turn all off** is there for
the same reason: switching layers on is easy and remembering which you switched on
is not.

Inside a group, the heading states the provenance and the licence once rather than
per layer, and large groups get a third level — the 22 forcing layers are split by
Copernicus dataset, because a flat list of 22 is not accessible whatever you call it.

**A layer this build did not produce still appears**, disabled, with the literal
reason from the build: *"GFW_TOKEN missing from secrets.env"*. An empty row would be
indistinguishable from the layer not existing.

> **What grouping by source caught.** The isobaths were labelled *"Depth contours
> 10/20/50/100 m (HELCOM)"*. They are ours, derived from the EMODnet DTM — and
> HELCOM's own contour layer is deliberately **not** used because it prohibits
> commercial use. Crediting the wrong party, on the one layer dropped for its
> licence, is the most expensive mistake a label can carry. The levels were wrong
> too: 20/50/80/100. A check now fails if any layer name credits a source that is
> not its own.

### Ours or somebody else's

The distinction that decides what you may put in front of a third party is still
there, now as the first two groups of the **By source** axis:

**Produced by Custody** — thresholds we chose, geometry we computed, judgements we made.
Alerts and exposures, the radar ship detection, the coastline and isobaths derived from the
DTM, the depth map, and the views built from our own AIS recording. The source line under
each group says what they were computed *from*; nobody else publishes them. Cite one and
you are citing us.

**Published by others, drawn as published** — authoritative data from the organisation
named under each group, fetched and drawn without alteration: Fintraffic AIS, EMODnet
Human Activities, Väylävirasto, HELCOM, OpenStreetMap, ESA Copernicus, Global Fishing
Watch. Nothing here is our conclusion.

Two placements are deliberate and worth stating. **AIS tracks and last positions sit under
external** although we assemble them: what is drawn are Fintraffic broadcasts, not a
finding of ours. **Coastline and isobaths sit under ours** for the opposite reason — that
geometry is computed here from the DTM; it is not an EMODnet product.

### Where the vessels come from

One layer, and the **time cursor governs it**. Whatever instant the cursor points to is
what the map draws. There is nothing to synchronise and nothing to choose.

**Live is not a separate layer.** It is the cursor parked on the newest fix while the
viewer polls digitraffic every 60 seconds. Each poll appends to the same recorded history
the cursor reads, so the timeline grows while the tab is open. Drag the cursor back and
the same layer draws that instant; press **Latest** to re-engage. Moving the cursor by
hand disengages the follow without switching live off — polling continues, so you lose
nothing by looking at the past.

This used to be three layers — *Live AIS*, *At the time cursor* and *Last position per
vessel* — and they were the same database at three instants. The live layer was the newest
point of the timeline drawn twice; *Last position* was another point of it, with **884 of
its 1,207 markers sitting exactly on the last fix of the vessel's own track**. The one
thing it genuinely carried was **103 vessels heard exactly once**, which never reach two
points and so never get a track; those are seeded into the history as single-point tracks,
so nothing was lost in removing the layer.

**One clock.** The timeline is the only thing that decides which instant the map shows,
including from inside a vessel. Picking a range in the vessel panel frames the bar on that
same span, and **Replay track** drives the global cursor, so the whole map moves with the
vessel instead of the rest of it staying frozen somewhere else. Only one playback runs at
a time, and either of them disengages live follow so the next poll does not yank the
cursor back to the present. **Latest** is the single way back to live.

**The map key, bottom left, says what is on screen**: whether the cursor is following the
newest fix or parked, the instant it is showing, and how many vessels are **under way**,
**stopped** and **without heading**. If some of them are last-known rather than current
positions it says how many.

**Reading a marker.** Two things carry meaning:

- **Shape** — an **arrow** means the vessel broadcast a bow heading and the arrow is
  rotated to it. A **circle** means the message carried no heading (12.6% of fixes), so
  the marker states position and nothing about where the bow points.
- **Dim and small** means stopped under 0.5 kn, or a fix too old to trust at this cursor
  time. The map key gives the live count of each.

**A frozen scene is sometimes the right answer.** The store holds 8 coverage windows
across 15.5 days. Scrub into a gap and every marker becomes a last known position rather
than a current one, so two instants inside the same gap draw the identical scene. The time
panel says *between coverage windows — nothing was recorded at this instant* when that is
what is happening (§4b).

### "ESA CDSE catalogue" and its column of zeros

Off by default. It marks where a Sentinel-1 radar scene exists and whether our own AIS
heard anything inside it — provenance, not observation, and twelve rectangles covering half
the Baltic is a lot of ink for a question nobody asks while working.

Every footprint currently reads **0 AIS**, and that is the finding rather than a fault. The
twelve scenes span **4.8–22.8°E**; our AIS coverage runs **15.5–30.5°E**, and **10 of the
12 do not overlap a single cell where our receivers have ever heard a message** (§4b). At
the acquisition hour the store held ten positions in the entire AOI. A radar satellite
passed over water we cannot hear — which is the gap this product exists to argue about.

---

## 1b. Python and its two dependencies

Python ≥ 3.11 and, beyond the standard library, **two packages** — both optional
in the sense that what fails without them is one feature, not the system:

| | For | Without it |
|---|---|---|
| `h3` | the hexagons of the `gps_interference` layer (§2f-ter) | that layer builds empty and says so |
| `paho-mqtt` | the MQTT AIS ingest (`ais_recorder/mqtt_ingest.py`) | the 60 s HTTP polling, which is the normal path, is unaffected |

Three more are needed only by the tests: the reference Hatanaka decoder the
orbit recorder is checked against (§0-bis).

```bash
cd software
./venv.sh              # build or update the environment
./venv.sh dev          # the same, plus what the tests need
./venv.sh where        # where it is, what is in it, how big
./venv.sh rm           # delete it — it is regenerable
```

**The environment is not in the repository.** It holds binaries compiled for
this machine, it does not travel, and the repository is in Dropbox, which is
full. It lives where `rutas.toml` says, beside the rest of the regenerable
things: `~/Documents/space_startup_datos/venv`. What does travel is the recipe,
`requirements.txt` — pinned, because a build that worked has to work again in
six months.

`./custody.sh` finds the environment by itself through `rutas.venv()`, and
falls back to the system `python3` when there is none; `./custody.sh status`
says which of the two it is using. Nothing is installed on the machine and
nothing stays running.

## 2. The satellite tile cache


Zooming used to crawl, for two reasons that had nothing to do with your connection:
`python3 -m http.server` serves **one request at a time**, and nothing was cached, so every zoom
re-fetched the same tiles from Planetary Computer.

`viewer/server.py` fixes both. It is multi-threaded, and it proxies everything that goes to
Planetary Computer through a disk cache:

| What | Cached for | Why |
|---|---|---|
| Image tiles | **Forever** | The pixels of an already-acquired scene never change |
| tilejson per scene | **Forever** | Same reason |
| STAC catalogue searches | **6 hours** | New scenes do appear; six hours is shorter than Sentinel-1's revisit over the Gulf |

Measured on four tiles: **1558 ms cold, 139 ms warm — 11× faster**, and the warm pass makes no
network request at all. Work offline on anything you have already looked at.

```bash
cd software/custody_mvp/viewer
./serve.sh cache     # how many files, how many MB, hit rate this session
./serve.sh purge     # empty it
```

The cache lives in `custody_mvp/cache/tiles/`, is gitignored, and holds nothing personal: public
Copernicus tiles served by Microsoft without authentication. There is **no automatic size cap** —
a cache that deletes itself halfway through a demo is worse than a large cache. Check it with
`./serve.sh cache` and empty it when you want to.

The proxy only accepts `planetarycomputer.microsoft.com`. An open proxy on localhost is a pivot
into the local network, and the allowlist closes it. If you serve the viewer with plain
`python3 -m http.server`, the viewer detects the missing proxy on first use and falls back to
direct connections: everything still works, just slowly.

---

## 2b. Where things live on disk, and what to back up

**One store, and one place that says where it is.** `paths.record` in
`config/custody.toml` is the only answer to "where is the data", and both the
reader (`custody/paths.py`) and the writer (`ais_recorder/recorder.py`) read it,
so they cannot disagree.

Three categories, and the difference is what is lost by deleting them:

| | What it is | Deleting it costs | Back up? |
|---|---|---|---|
| **cache** | A pure function of an external source. Tiles, GeoTIFFs, capabilities. | Time and bandwidth. Never information. | No |
| **data** | A pure function of (cache + code + config). The build's output. | One build. | No |
| **venv** | A pure function of `requirements.txt` plus this machine. | One `./venv.sh`, about a minute. | No |
| **record** | Primary observation: the AIS messages our receivers heard at a given hour. Not a function of anything. | **Information, permanently.** Nobody can re-record 10 November 2026. | **Yes, this one only** |

That is why `record` points outside the project tree and into Dropbox, and the
other two do not: 1.9 GB of regenerable tiles were syncing to the cloud while the
25 MB nobody can ever capture again sat outside it.

### What `record_fallbacks` cost, and what replaced it

There used to be a list of places to *look* if the configured store was missing.
That sounds prudent and is not: it turns a configuration error into silence.

On 2026-11-13 the recorder was restarted with `--root ~/ais_data` while the
configured root in Dropbox still existed. The fallback was therefore never
consulted. The recorder wrote, the disk filled, and the timeline sat at 09:07Z
for **4.6 hours** with no error in any log.

Reading every root fixed the blindness and left a worse problem: an application
reading from two places nobody asked for. So now:

- `record` — the one store. The recorder writes here by default too.
- `record_extra` — empty. For mounting a read-only historical archive beside the
  current one, and nothing else.
- `record_watch` — places the recorder has lived. **Not read. Watched.** If
  recording turns up there, the app says so in the Health panel, in
  `/alerts/status` and in `python3 -m custody.paths`, with the command to merge
  it. Reading it quietly is how the data got scattered.
- A recorder started with a `--root` that is not the configured one **logs a
  warning**: it is not blocked, because it may be deliberate, but it is said.

### Merging a store that drifted

```bash
python3 ais_recorder/merge_store.py --from ~/ais_data            # dry run
python3 ais_recorder/merge_store.py --from ~/ais_data --apply
```

**It does not need the recorder stopped**, because the store's format already
works this way — from `store.py`: *"Each write batch is an INDEPENDENT gzip
member appended to the file (RFC 1952 allows member concatenation) ... resume is
'open in append mode'. No rewrite, no compaction."* Merging is therefore the
store's native operation, not an exception to it. A batch half-written in the
source is simply not copied yet; the next pass picks it up.

**It is idempotent**, comparing record by record on natural identity
(`locations` → `(mmsi, timestampExternal)`, `vessels` → `(mmsi, timestamp)`,
`polllog` → `(stream, rx_ms, seq)`), so it can be run twice, or again after the
recorder has written more. The second pass copies zero.

**It does not delete the source.** That is primary observation; a person decides,
after reading the count it prints.

Measured on the 2026-11-13 unification: 960,446 + 124,884 = **1,085,330 records**,
gzip CRC clean on every file, 129 records already present and correctly skipped,
and a second pass copying nothing.

---

## 2c. Tests

`./tests/run.sh` runs everything and exits non-zero if anything fails. Three levels,
fastest first, because a failure at the bottom makes noise in everything above it:

| | What it covers | Needs |
|---|---|---|
| `tests/test_indicators.py` | The seven indicators, unit level: thresholds, suppression, counters | Nothing — no network, no build |
| `tests/test_licences.py` | **That nothing in the product carries a licence that forbids selling it** | A manifest |
| `tests/smoke.js` | Loads the real build and renders every panel and layer | A completed build |

The licence check exists because of a specific failure, written up in §17c. The second
level is the one to run before any demo that someone might pay for.

---

## 2d. "The timeline looks empty at the right"

**Nothing in the viewer waits for a build any more.** Three separate things used to stop at
the moment the build ran; all three now reach the present.

| What | Where it comes from now |
|---|---|
| Coverage windows | the **polllog** — the file recording when we were polling, 31 kB a day — recalculated by the server on request, refreshed every five minutes |
| Vessels and their tracks | the runtime engine, over a rolling window that reaches back to the build's edge, pushed to the browser on every cycle |
| Alerts | the same engine, same `custody/indicators.py` the build uses |

The viewer merges the engine's tracks into the **same** `HIST` the build fills, so the
slider, the snapshot, a vessel's own history, the counts and the basin focus all cover the
uncompiled stretch too. There is one vessel model, fed by two sources — not two models.

**The engine's window is not a constant.** It sizes itself to the gap: build ended 11 h
ago, window is 11.5 h. A fixed 6 h window with an 11 h build left **five hours with
neither** — not from the build, which had not reached them, and not from the engine, which
did not look that far back. That hole is what the lane used to draw hollow.

- Floor: 6 h, because no indicator looks further back than 30 minutes.
- Ceiling: 36 h. Past that the cost grows and the value does not, so it **says** the window
  is capped instead of quietly coming up short.

Cost measured on this store: **7.0 s** for an 11.9 h window, 118,275 fixes, 722 tracks. The
recorder writes every 60 s, so there is room.

**What a build still buys you:** the long history (18 days here, versus the engine's hours),
the derived layers that do not change minute to minute — depth raster, coastline, corridors,
ports — and a viewer that works with no server behind it. The split is: *observation and
detection are live; cartography and the long archive are build work.*

### If you suspect data really is missing

```bash
python3 -m custody.paths                   # every store it reads, with file counts
python3 ais_recorder/aisctl.py summary     # what the store actually holds
curl -s localhost:8000/alerts/status       # window, coverage, stores, per-indicator counts
```

**Read every store, not the first one.** `paths.records()` returns all of them. It used to
return the first directory that existed and ignore the rest, and that cost 4.6 hours of
invisible recording on 2026-11-13: the recorder was restarted with `--root ~/ais_data` while
the configured root in Dropbox still existed, so the fallback was never consulted. The
recorder wrote, the disk filled, and the timeline sat at nine in the morning **with no error
in any log**. A primary observation is not discarded because it is in another folder: they
are all read and unioned, deduplicated by `(mmsi, timestamp)` — the same key used within a
single store, and the right one across stores, because the same hull heard at the same
instant is one fix, not two.

Fix the configuration too, or the stores keep multiplying: point `record` in
`config/custody.toml` at where the recorder actually writes, or restart the recorder with
that root.

---

## 2e. Alerts in real time

The seven indicators run **in the server, the moment new data lands**, not only at build
time and no longer on a timer. The alert panel says so: *LIVE · 610 alerts recomputed over
the last 11.9 h · last cycle: new data*. If that line is grey, you are being served without
the proxy and the alerts are the build's.

**It fires on arrival, not on a clock.** The loop used to sleep 60 s between passes; with
the recorder also writing every 60 s, a fix could wait a full minute before being checked,
and in the worst case an alert surfaced a minute late. Now the engine stats the newest file
of each store every 3 seconds — **0.1 ms a check**, so it is free — and evaluates the
instant the signature changes. The delay stops being "up to 60 s" and becomes the
evaluation itself. A 300-second idle pass still runs when nothing moves, because the window
advances with the clock and what no longer fits in it has to stop counting.

**It is the same engine.** `custody/live.py` calls the same `custody/indicators.py` that
`build.py` calls, and both build their tracks with the same `ais.tracks_geojson()`. There is
no JavaScript copy of the detection rules, on purpose: two implementations is how a demo and
a report stop agreeing, and a smoke check fails if the viewer starts computing thresholds or
distances of its own.

**Push, not poll.** The browser subscribes to `/events`, a Server-Sent Events stream, and is
told the moment a cycle finishes — alerts *and* vessels in the same push, so an alert can
never point at a vessel the map does not have yet.

**The coverage it passes to the indicators is the real one.** This is the bug worth knowing
about. The engine used to hand the indicators `[(window start, now)]` — one continuous
window, which is the claim *we were listening the whole time*. IND-04 fires when a vessel
stops transmitting **inside** coverage, so that claim turns every recorder outage into one
alert per hull. Measured on 2026-11-13, with the recorder down for 6.5 hours:

| coverage passed to the indicators | IND-04 alerts |
|---|---|
| one continuous window (the claim) | **909** — one per hull, all false |
| the real windows from the polllog | **157** |

The build had always applied this correction (T2 in `indicators.py`); the runtime engine had
not. `/alerts/status` now reports both numbers — `window_h` and `coverage_h` — and a test
fails if they are ever equal.

**Why a window rather than the whole store.** Reading all stored positions costs seconds in
I/O alone, and no indicator looks further back than its own window — the longest is IND-01's
30 sustained minutes. The floor is set with margin over that, and the ceiling where cost
stops buying value:

| window | fixes | tracks | alerts | time |
|---|---|---|---|---|
| 1 h | 21,679 | 590 | 163 | 0.63 s |
| 6 h | 120,369 | 626 | 524 | 3.97 s |
| 11.9 h (sized to an 11.4 h build gap) | 118,275 | 722 | 610 | 7.0 s |

Seven seconds of CPU against a 60-second recorder cadence.

**What stays build work, and why.** The context — cables, bathymetry, the port mask, the
coastline index — does not change between polls, so it loads once in 0.17 s and is reused.
**The build still owns everything older than the live window**; the two are merged by time,
so before the window the build's alerts stand and inside it the live engine's do. Nothing is
counted twice.

Endpoints: `/alerts/live` (GeoJSON), `/vessels/live` (tracks, same shape as
`tracks.geojson`), `/alerts/status` (engine stats), `/sources/time` (each source's time
axis), `/events` (SSE).

**Traffic.** `/vessels/live` is 5.8 MB of JSON for a 12-hour window. Sending that on every
cycle would be 6 MB a minute to rediscover that 99 % of it is already in memory, so the
browser asks for the whole window once and then only for the tail — last 30 minutes, with
the overlap deduplicated by timestamp. The server also gzips anything over 4 kB. Per cycle:
**5.8 MB → 130 kB.**

---

## 2f. The forcing — wind, wave, current and ice

IND-02 flags a vessel pointing one way and moving another. **Wind, wave and current
produce exactly that picture**, so without them the indicator cannot tell drift from
steering. Two sources answer that, and they are complementary rather than duplicates.

**Who makes what, because it gets asked and the answer is not the obvious one.**
**Mercator Ocean International** implements and operates the Copernicus Marine
Service as a whole, and produces its **global** products. The **Baltic** product
this tool runs on is produced by **SMHI** (Norrköping) inside the Baltic
Monitoring and Forecasting Centre, with DMI (Copenhagen) as local service desk.
So the current already on the map comes from the service Mercator operates, but
the model is SMHI's: NEMO v4.0 at **1 nautical mile**, up to 56 vertical levels,
assimilating satellite SST, ice concentration and in-situ T/S profiles, forced
with Stokes drift from the Baltic wave product, **updated twice daily with a new
six-day forecast**.

**Copernicus Marine** — 22 layers from four products, under *Copernicus Marine*
in the Layers tab:

| Group | What | Why it is there |
|---|---|---|
| **Current** | surface current, as a vector | The one thing FMI cannot give |
| **Waves** | height, direction, period, swell/wind-sea split, Stokes drift | Swell comes from elsewhere, wind sea is local — two different explanations for the same drift |
| **Ice** | concentration, thickness, drift velocity | A track that follows the ice is not navigating |
| **Water column** | temperature, salinity, sea level, mixed layer | Context, and surge changes the depth under a hull |
| **Reanalysis** | current, ice, temperature, sea level | What the water was doing *on the day*, for reconstructing an incident |
| **Global cross-check** | total surface current, tidal current | Mercator Ocean's own global model. See below — a cross-check, not an upgrade |

**On the global product, and why it is a cross-check.** Its resolution is 1/12°,
about 8 km, against the Baltic model's 1 nm (1.85 km). The Gulf of Finland is
50–100 km wide: at 8 km that is six to twelve cells across, with the coast inside
the cell. For this sea the Baltic model is better, and switching would lose
detail.

What the global model *does* add, and the Baltic one does not publish, is **total
velocity — Eulerian flow, waves and tide added together**, which is what actually
transports a hull; the Baltic product publishes the Eulerian current (even though
it is forced with Stokes). That one variable is the whole reason it is here.

And the honest limit: **the Baltic is microtidal**, a few centimetres of range.
The tidal component the global model contributes weighs little in this sea. The
tidal layer is worth one look to confirm exactly that — if tide is small, wind and
pressure explain the rest, and that is the useful conclusion.

Both layers are pinned to the `merged-uv` dataset rather than chosen by the usual
picker, because what makes them useful is that dataset and not the variable: the
picker takes the highest version tag, and here that would select `0.083deg`
(tag 202406), which carries the Eulerian current only, over `merged-uv`
(tag 202211), which carries the total. Pinning a tag is the thing the picker
exists to avoid, so it is **checked**: if the dataset disappears from the
capabilities the build reports it as missing instead of serving empty tiles.

**Every one follows the time cursor, rounded to its own cadence.** That is half the value:
the current at the instant something happened, not the current now.

**The cadence is read from the service, and that mattered.** Copernicus publishes the same
variable as a 15-minute series, an hourly series, a daily mean and a monthly mean, with the
same version tag. The picker only compared version tags, so between them it kept **whichever
appeared first in the XML** — and by that accident the current painted beside a vessel track
was a **24-hour mean** and sea level a **30-day mean**, in a tool whose point is saying what
is happening now. It now prefers the newest tag and, within it, the **finest cadence**:

| Layers | Cadence now | Was |
|---|---|---|
| Surface current, sea level | **15 min** | 24 h / 30 days |
| Waves, ice, temperature, salinity, mixed layer | **1 h** | 24 h |
| Reanalysis | 1 d | 1 d |

Rounding the cursor to the hour for all of them would throw away three quarters of the
resolution we are already paying for, so each layer snaps to its own step. A test fails if
any analysis layer ever resolves to a daily or monthly mean again.

**The limit, stated where it applies.** Surface current direction carries **87° of RMS
error**, validated against seven moorings for the whole sea. It supports *"there was a
current"*, not a computed drift. The figure is printed beside the current layers rather
than in a footnote, because it is the kind of thing a reviewer asks about.

**FMI** gives wind, which Copernicus Marine does not publish because it is not a marine
variable. FMI is an original source here, not a proxy: WAM and HARMONIE are its own models.
Open, no key, CC BY 4.0. Measured horizons, hourly steps both:

| Model | Steps | Window |
|---|---|---|
| HARMONIE, wind | 50 | next whole hour → **+49 h** |
| WAM, wave | 12 | next whole hour → **+11 h** |

**Both start at the next whole hour.** The point query serves *forecast*, not history — so
it cannot reconstruct a past incident, and its lane always shows `→`. For a past day the
source is the Copernicus reanalysis or FMI's observation queries, not this one.

**Its cache expires now.** `net.fetch` had no TTL: if the file existed it was served. For a
forecast that is a silent, permanent error — on 2026-11-13 it was handing back a wave series
that ended at 15:00Z while the clock read 20:21Z, and it would have kept ageing forever. A
real-time tool serving a five-hour-old forecast is not late, it is wrong, with nothing in the
log. FMI answers now expire after **15 minutes**, finer than the hourly data itself.
Coastlines and WMTS capabilities keep the permanent cache, which is correct for them.

**What it produces: `drift_explained`.** Open an IND-02 alert and the panel asks FMI for
the wind and wave at that point, then says whether the forcing explains the angle:

- Crabbing **to the side the forcing pushes**, with enough wind or sea → *likely drift,
  not steering*.
- Crabbing **against** it → **the forcing does not explain this, and that is the
  interesting case.**

That is what turns IND-02 from a suspicion into either evidence or a dismissal. Two traps
are worth knowing: **wave buoys return NaN from November**, withdrawn before the ice
season, so the WAM model is the primary source and the buoys seasonal validation only; and
**a point outside the useful grid returns NaN with HTTP 200**, so absence has to be
checked rather than inferred from the status code.

---

## 2f-bis. EMODnet — the traffic baseline for the whole AOI

**The problem it solves.** Our own receivers cover **21 % of the AOI** and die
around 57°N. Over the other 79 % the tool cannot say whether what it sees is
unusual, because it does not know what usual looks like there. An indicator that
flags *"this vessel is off the normal route"* needs a reference for where the
normal route is, and that reference cannot come from our own recording — it is
precisely what we are missing.

EMODnet publishes that reference for the whole sea, built from AIS we do not
have. It is **not** a live source: monthly, aggregated, 1 km cells. It does not
say what is happening now; it says what happens always.

### Two products, and the difference decides which you can use

| | Built by | From | Cells | Covers | Refreshed |
|---|---|---|---|---|---|
| **Route density** | **EMSA** (European Maritime Safety Agency) | the EU's own AIS | 1 km | 2019-01 → **2026-10** | monthly |
| **Vessel density** | **Cogea**, for EMODnet | AIS *purchased* from CLS, ORBCOMM, vesseltracker.com | 1 km | 2017-01 → **2024-12** | once a year |

**Route density is the operational baseline.** In November 2026 it already holds
October: one month behind. Use it for *"is this route normally used"*, *"is this
cable corridor normally crossed"*.

**Vessel density is the climatology.** About eleven months behind, so useless for
now — but it splits traffic into **thirteen ship types**, including *Military and
Law Enforcement*, which EMSA does not break out. Units are **hours per square
kilometre per month**, so it answers *"has traffic here changed"* across years.

> **The caveat the service publishes itself, repeated here because it decides a
> comparison:** in 2024 its AIS provider lost satellite data from June onwards.
> The second half of 2024 is thinner than previous years. **Compare a November
> against 2023, not 2024.** The panel prints this next to the layers.

### Infrastructure: a second opinion on the cables

Our corridors come from **OpenStreetMap** — 6,754 elements, 133 named. That is
community-mapped, and for a product whose entire subject is the cable it is a
weak point. EMODnet publishes the **official EU aggregation** that Cogea
maintains for the Commission, as separate telecom and power datasets, refreshed
yearly. Both are drawn as layers; neither replaces the other, because which one
to trust is decided by looking at them together, not silently.

Also there: pipelines (Balticconnector was a pipeline, not a cable — same threat,
same seabed, different dataset) and wind farms, each of which has export cables
running to shore.

### How it behaves in the viewer

- **The instant is picked from the declared list, never rounded.** EMODnet
  enumerates each available month one by one; ask for anything else and the
  service returns an empty tile, which on the map reads as *"nobody passes here"*
  — the exact opposite of what the layer exists to say. The viewer finds the
  nearest declared month to the cursor, requests that, **and prints which month
  it is and how far it is from the cursor**, in amber past 45 days.
- WMS, not WMTS, so Leaflet requests it by bounding box and the tiles go direct.
  Only the legend passes through the proxy, to be fetched once.
- Off by default, drawn under the vessels at 0.55 opacity. It is background.
- Capabilities are cached for **one day**, not forever: a new month appears every
  month, and an eternal cache would freeze the baseline at the month it was built
  — the same bug the FMI forecast had.

**Licence: CC BY 4.0, commercial use permitted.** Attribution must name **both
EMODnet Human Activities and CLS** — the AIS behind vessel density was purchased,
so that credit is not optional. Route density credits EMSA. All three are in the
footer and in `config/licences.toml`.

---

## 2f-ter. Interference with satellite navigation

**Why this group exists.** IND-07 fires on a position jump — a vessel that
appears somewhere it cannot have reached. There are two explanations and the
indicator cannot choose between them: a tampered transponder, or a receiver
being interfered with. Without this group the alert is a shrug. Traficom states
the premise plainly: the problem is real, it is daily, and it is in the Gulf of
Finland around Kotka–Hamina.

Two sources, and they measure **different things on purpose**:

| | What it measures | Where | Cadence | Covers |
|---|---|---|---|---|
| **GNSS-Finland** | carrier-to-noise ratio at fixed ground stations | sea level, on land | **every 30 s** | Finland only, 33 stations in the area |
| **GPSJAM** | accuracy that aircraft declare over the air | 10 km up | whole day, **2 days late** | the whole Baltic, wherever aircraft fly |

Turn both on and you see the overlap and both blind spots at once. Where only
one measures, the other is confirming nothing.

### GNSS-Finland — the only source here that measures *now*

Open service from the Finnish Geospatial Research Institute, commissioned by
Traficom, over the 47 reference stations of the FinnRef network. **33 of them
fall inside the area of interest, eight along the Gulf of Finland** — including
Virolahti at 60.54 N 27.54 E, on the border, and Loviisa, Metsähovi and
Raasepori.

The data interface is **not documented anywhere**; it was found by watching what
the service's own page requests:

```bash
curl https://gnss-finland.nls.fi:8080/api/capabilities     # stations, thresholds, scale
curl 'https://gnss-finland.nls.fi:8080/api/sigstatus?stations=VIR2,LOV3,MET3'
```

No credentials. Per station and per constellation (GPS, Galileo, GLONASS,
BeiDou) it gives satellites in view, and per signal the satellite count, the
average carrier-to-noise ratio in decibel-hertz, and a three-level quality
indicator. The scale and the thresholds come from the service itself — GPS L1
counts as good at 40 dB-Hz or above, poor below 37 — so we are not inventing a
cut-off.

**The worst signal wins, never the average.** Interference typically hits one
band, almost always GPS L1 because that is the one worth attacking. Averaging it
with four healthy constellations erases it. What matters is whether *anything*
is degraded, and which.

**Two things it does not tell you, stated on the layer itself:**

- **Degradation, not cause.** Deliberate interference looks identical to a wet
  antenna, an ionospheric storm, or a tree that grew.
- **It is measured on land.** That a coastal station sees degradation makes it
  *plausible* a vessel 30 miles out did too. Not certain. Same honesty as the
  AIS coverage grid.

### GPSJAM — context, never proof

Aircraft broadcast how much accuracy they claim to have. When GPS degrades, that
declared uncertainty rises. Aggregate every aircraft over a day onto a hexagonal
grid and you get a map of where GPS was going wrong. Source: airplanes.live and
ADS-B Exchange, published by John Wiseman.

Measured on the 2026-11-12 file: 48,244 cells worldwide, **1,019 inside the area,
316 with at least one degraded aircraft.** The strongest is 56.0 N 22.3 E with
**10 of 17 aircraft degraded** — the Kaliningrad corridor.

**Four limits, and they decide how it is presented:**

1. **It aggregates a whole day.** Five minutes of interference paints a cell of
   about 1,770 km² for twenty-four hours. Against an AIS position jump stamped
   to the second, that is a weak coincidence, not a correlation. It answers
   *"there was interference around here that day"* and nothing finer.
2. **It arrives one to two days late.** Measured: on the 14th, the file for the
   13th was still a 404. Useless for watching now.
3. **It is blind where aircraft do not fly** — which over the open Baltic and the
   Gulf of Bothnia is most of it. Our AIS coverage dies around 57°N; this dies
   somewhere else, which is good (they complement) and bad (there is sea covered
   by neither).
4. **An aircraft is not a vessel.** At 10 km you see a ground transmitter a ship
   20 miles offshore may not, and the reverse.

And the author's own caveat: it does not separate jamming from spoofing, and it
can pick up military exercises and counter-drone systems rather than attacks.

Cells with a single aircraft all day are dropped: one degraded aircraft out of
one gives 100 % and paints 1,770 km² red on a sample of one. That is noise
shaped like signal.

The hexagons need the `h3` library — one of the project's two dependencies
(§1b), and an optional one. Without it this layer is empty and says so; nothing
else changes.

#### What was measured, and what was not: the outline

The hexagon layer draws **only cells with at least one degraded aircraft**. On
its own that is unreadable, because a cell with no hexagon can mean two
opposite things: the aircraft that flew there had good GPS, or no aircraft flew
there at all. A second layer, **`gps_interference_coverage`**, draws the border
between the two — the perimeter of the cells that saw at least two aircraft
that day, dashed and unfilled, under the hexagons.

For 25 November 2026:

| | km² | Of the AOI |
|---|---|---|
| **Measured** (≥ 2 aircraft) | 1,353,795 | **81 %** |
| Of that, with some degradation | 486,011 | 36 % of what was measured |
| **Not measured at all** | 316,887 | **19 %** |

The 19 % is not a quiet sea: it is the Gulf of Bothnia and the open Baltic,
where airliners do not fly. It is also, in part, exactly where our own AIS
coverage dies (§2b) — the two blind spots do not coincide, which is why having
both is worth something, but they do overlap.

Two cautions that the layer states in its own popup. The area is summed cell by
cell, not from the 1,770 km² average: an H3 resolution-4 hexagon at 66 °N is
noticeably smaller than one at 53 °N. And a cell enters the area of interest by
its **centre** and is then drawn whole, so the outline overshoots the AOI edge
by up to ~11 km; clipping it would need a geometry library for an error smaller
than one cell.

### What is not integrable, and why

| Source | Verdict |
|---|---|
| **Traficom statistics** | Annual national totals in narrative form — no file, no interface, no geography. A citation, not a layer. Two breaks in the series to quote if you use it: aviation reporting criteria narrowed on 1 May 2024, and from 1 January 2026 the maritime count changed from *interference reports* to *vessels experiencing interference* |
| **Navigational warnings** | **There was an interface** — `/api/v1/nautical-warnings/*` on Digitraffic Marine. It is on the November 2022 deprecated list and is now gone: the current specification has 18 paths and none is warnings. Confirmed with a request: 404. The replacement, **Vilkku**, is being built by Traficom and Fintraffic on the **S-124** standard, announced for early 2026 and not confirmed in service. Today warnings go out over NAVTEX and VHF radio: broadcast text, not something you can query. **The source with the most legal authority on the list is the least integrable**, and Traficom is on the hackathon expert list — worth asking in person |
| **NAVCEN** | United States reports. Out of area |

### Licences: a third state, because silence is not prohibition

Neither source publishes terms. GPSJAM states no licence on its front or about
page, and its underlying reports come from ADS-B Exchange, which has its own —
two parties to ask. The institute's page says the service "can be used by
anyone" and nothing more.

That is **not** the same as HELCOM's depth contours, which say *"any commercial
use is prohibited"*. So `config/licences.toml` now has three states rather than
two:

| | Meaning | What the check does |
|---|---|---|
| `commercial = true` | can be sold | passes |
| `commercial = false` | **explicitly prohibited** by the publisher | **fails the build** |
| `ask_before_selling = true` | the publisher says **nothing** | passes, and is **listed at the end** so it cannot be forgotten |

Treating silence as prohibition would throw away useful public data; treating it
as permission is how you sign a contract you cannot honour. Both of these are in
the third state: draw them, cite them, and write to the publisher before selling
anything built on them.

---

## 2g. Coverage held by others

Our AIS coverage is **21% of the area of interest and dies around 57°N**, which puts the
November 2024 cable cuts near Gotland in the blind spot. The **AISHub receiver stations**
layer draws who else has receivers there: **204 stations inside the AOI, 32 of them in the
56–60°N band where ours stops** — including **Visby and Fårö on Gotland**, beside the cut
cables. Those are drawn larger and amber. The layer is not decoration; it is the case for
requesting access, on the map.

Station positions only. The aggregated feed needs a contributing receiver of your own, and
**its redistribution is prohibited** — it may be used, never resold.

**Two sources are deliberately absent**, and the reasons are on record in
`config/licences.toml`:

- **Kystverket** covers the Norwegian economic zone, not the Baltic, and **excludes
  fishing vessels under 15 m and recreational craft under 45 m**. That exclusion matters
  beyond coverage: there, the absence of a small vessel is not evidence it was not
  present. The live feed needs a registered BarentsWatch client.
- **aisstream.io** publishes no licence, no redistribution terms and no station list, so
  its coverage cannot be verified — unusable both for a thesis that must cite provenance
  and for a product that must know what it may redistribute. Worth noting since the name
  misleads: its `StandardSearchAndRescueAircraftReport` is AIS message type 9, a search and
  rescue **aircraft**, not Synthetic Aperture Radar.

---

## 3. Troubleshooting


| Symptom | Cause and fix |
|---|---|
| Blank panel, "Load failed" | You opened `index.html` as a file. Serve it: `python3 -m http.server` from `viewer/` |
| A layer says *no data* | Expected and deliberate. **Sources ▸ Build health** gives the literal reason. Usually Overpass returned 502 or a credential is missing |
| SAR or optical progress sticks part-way | Fixed. It was a counting bug: Leaflet has **three** ways a tile request ends — load, error and **abort** — and aborts were not counted, so panning away mid-load left the bar permanently short of 100%. If it now stalls for real, after 15 s it turns amber and says how many tiles are unanswered, with a **Stop loading imagery** button. That means the server is slow, not that the viewer is stuck |
| No Sentinel-1 detections | Needs a free CDSE account; put credentials in `cdse_credentials.json`. The OAuth2 flow is written but **not verified in execution** |
| Alerts list empty | No AIS in the store. `python3 -m custody.paths` says where it is; start the recorder with `./custody.sh up` |
| Map popup button did nothing | Fixed. The handler is bound on `popupopen` now; an earlier build put the call in an inline `onclick` whose quoting broke the attribute |
| Map shows only OSM and bathymetry, no vessels | Was a script load-order bug: `app.js` called a function defined in a file loaded after it, so the bootstrap died. Fixed, and `node smoke.js` from `viewer/` now catches that class of bug before you open a browser |
| Ships do not move with the slider | Fixed. If it recurs, check that the `Snapshot` layer is on and `Last position per vessel` is off |
| **Show SAR** says failed | The scene is outside Planetary Computer's catalogue, or the network is off. Tiles outside the scene footprint return 404 by design |
| Everything is dim grey | The cursor is between coverage windows, so every marker is a last known position. Press **Latest** or `→` |
| IND-04 fires everywhere | The recorder was stopped during the window. A gap in our data is not a gap in the AIS — measured at 30 % false positives from our own downtime |

---

# Part II — Using it

## 4. The interface


### The shell

The layout follows a code editor, for the same reason an editor uses it: the content deserves
the screen.

- **Icon rail**, far left, always visible. One icon per section, Settings pinned at the bottom.
- **Click the icon of the section you are already in and the sidebar collapses.** Click any icon
  to bring it back. `Ctrl+B` (or `Cmd+B`) toggles it too, and so does the `‹` in the panel header.
  Collapsed, the map runs from the 54 px rail to the right edge.
- **Drag the edge between sidebar and map** to resize it. The width is remembered in your browser.
- The map re-centres on what you were looking at after every resize, so collapsing the panel
  never makes you hunt for your scene again.

In rail order, top to bottom:

| Tab | What it is for |
|---|---|
| **Alerts** | The list, and the self-explaining detail view. §10 |
| **Vessels** | Every hull seen, classified by type, size and flag. **Ticked = visible on the map**, so the facets are a selection tool, not just a list filter. Click one for its dossier and its track; press one button for the tracks of the whole selection. §8, §20 |
| **Learn** | Every indicator in plain language, the glossary, and what the tool cannot do |
| **Filters** | The operator console: hot filters, the alert time window, and the build's thresholds. §12 |
| **Layers** | All 66 layers, in **collapsible groups** with a search box. Group them **by purpose** (default — what question each answers) or **by source** (all of EMODnet together, all of Copernicus Marine together). Each header shows how many layers it holds and how many are on, visible while closed. Three clicks to anywhere; search cuts it to one. See §2 *Finding a layer among sixty-six* |
| **Sources** | **Where every number came from, split into EU Space Programme, European open data, space-derived non-EU, and terrestrial — plus build health and licences.** Start here when a jury asks. §17 |
| **Settings** | Team name and language |

There is no Status tab any more. It showed a green `ok` per layer without saying what `ok`
meant, and the two things in it that were worth reading had better homes: layer health and
licences now sit under **Sources**, where the question "where did this come from, and what is
missing" is already being answered, and the detection thresholds sit under **Filters**, next to
the controls that act on them.

**Keyboard:** alerts are focusable — `Tab` to move, `Enter` or `Space` to open.
**Deep links:** `index.html#sources` opens straight to Sources. `#status` still works and
redirects there.

---

## 4b. How far the map reaches, and how far we can hear

The area of interest is **the whole Baltic**: 9–30.5 E, 53.5–66 N. It used to be the Gulf
of Finland, and the change was not cosmetic — the Fintraffic feed was already delivering
vessels across the whole sea and the old box discarded half of them. Tracks went from 592
to **1,250**.

```bash
./custody.sh build -- --aoi gulf          # one minute, for iterating on an indicator
./custody.sh build -- --aoi north-baltic  # where coverage is actually dense
./custody.sh build -- --aoi baltic        # default
./custody.sh build -- --aoi 16,57,24,61   # an explicit box
```

### The part you must not skip

**Only 21% of that area has ever produced an AIS position.** The receiver network feeding
Fintraffic is terrestrial VHF, and its reach dies around **57°N**. North of that the Gulf
of Finland, the Gulf of Bothnia, Åland and the northern Baltic are dense. South of it —
Gotland, Gdansk, Kaliningrad, the Danish straits — there is nothing at all.

So **Layers ▸ AIS coverage** draws exactly the cells where the recorder has heard
something. Turn it on before you read anything into an empty stretch of sea. An empty
southern Baltic means *we are deaf there*, not *it is quiet there*.

The practical consequence, worth stating once: **the two November 2024 cable cuts near
Öland and Gotland are in the blind spot.** Widening the area does not reach them. That is
a limit of the source, not of the box, and it is the argument for the constellation.

### Legal cover is no longer Finnish-only

Väylävirasto covers Finland. While the map was the Gulf that was nearly everything; across
the Baltic it is a strip, and claiming Baltic coverage on Finnish law alone would be a
Finnish statement in Baltic clothing.

**Sources ▸ Legal cover around the Baltic** lists all nine riparians:

| | |
|---|---|
| **With data** | **FI** (Väylävirasto, the most detailed of the lot) · **EE DE LT LV** (national maritime spatial plans, via HELCOM) |
| **Without** | **SE** — three endpoints tried, none answered, and Sweden is not in the HELCOM layer. The important gap: the other country living the cable problem · **PL DK** — plans approved, no endpoint found · **RU** — no open source, and none expected |

`custody/authorities.py` is a registry, not a hard-coded list. Adding Sweden the day they
publish an endpoint is one row.

---

## 4c. Focusing on one basin

The Baltic is 1.7 million km² and over a thousand tracks. Looking at all of it at once is
not looking. **Focus on a basin** — the bar at the top left — narrows it.

**The boundaries are HELCOM's, not ours.** The division is
[`HELCOM subbasins level 2`](https://maps.helcom.fi/arcgis/rest/services/MADS/Monitoring/MapServer/107),
the **17 units HELCOM uses in its own HOLAS assessments**, fetched at build time from the
same map server this tool already queries for munitions dumps and marine spatial planning.
They are grouped into the **7 major basins** of the Baltic Sea Action Plan nutrient
ceilings, because seventeen buttons is a form rather than a choice. Pick a group and the
panel names the level-2 units inside it, so the claim can be checked.

| Group | HELCOM level-2 units inside | What is there |
|---|---|---|
| **Kattegat** | Kattegat | The approach from the North Sea |
| **Danish Straits** | Great Belt, the Sound, Kiel Bay, Bay of Mecklenburg | The only way in or out. Every vessel entering the Baltic passes here, and we have no AIS coverage of our own |
| **Baltic Proper** | Arkona, Bornholm, Gdansk, Eastern and Western Gotland, Northern Baltic Proper | The open centre. The November 2024 cable cuts were here — and so is the edge of our AIS coverage |
| **Gulf of Riga** | Gulf of Riga | Riga, Pärnu, the Irbe Strait |
| **Gulf of Finland** | Gulf of Finland | Helsinki–Tallinn and the St Petersburg approaches. Balticconnector, Estlink 1 and 2, C-Lion 1. Where the 2023 and 2024 incidents happened |
| **Bothnian Sea** | Bothnian Sea, Åland Sea | The narrows between Sweden and Finland, dense ferry traffic through a demilitarised archipelago |
| **Bothnian Bay** | Bothnian Bay, the Quark | Fenno-Skan 1 and 2, the Finland–Sweden power links. Ice-covered in winter |
| **Inland waters and lakes** | *none — this one is ours* | Lake Ladoga, the Saimaa canal, Lake Mälaren |

That last row is marked differently on purpose. It is **not** a HELCOM sub-basin: AIS
reaches us from inland water that is not the Baltic, and 51 vessels sit there. Before it
existed they vanished from the map the moment you focused anything. **Nothing is
unclassified now** — every vessel lands in one of the eight.

**Focusing filters, it does not just zoom.** Everything outside the basin leaves the alert
list, the vessel list and the map. A line in the alert panel says how many alerts the
focus is hiding, with one click back to the whole Baltic; the Vessels tab says the same
for hulls. A filter that hides without saying how much is how someone reads one gulf and
believes they have read a sea.

**Two honest limits.** The polygons are **simplified from 2.9 million vertices to 26
thousand** so the browser can test a point against them, which puts quays and archipelago
channels a few metres outside their own basin — without a margin **20.6% of vessels went
unclassified, and they were precisely the berthed ones**. Anything within **5 km** of a
sub-basin is assigned to it; that number is the error the simplification introduces, not a
licence to move boundaries. And they are sub-basins, not jurisdictions: do not read a
maritime boundary into them.

---

## 4d. Depth, painted for this sea

There are two depth layers in **Layers**, and they come from the same EMODnet DTM. The
difference is the palette.

**EMODnet bathymetry WMS** is the official one, served by EMODnet through
`GetLegendGraphic` and not redrawn here. Turn it on and the legend explains itself: the
ramp spans **6,000 m**, magenta at the bottom, red at the shoreline. It is a good scale for
open ocean and a useless one here, because the Baltic does not use it. The service ignores
`COLORSCALERANGE`, so it cannot be rescaled from outside.

**Baltic depth map** is the same DTM with the ramp cut to this sea. Nine bands, chosen by
**quantiles of our own grid** rather than by eye, measured over 20,524 water cells:

| | | |
|---|---|---|
| median depth | **48 m** | p75 **89 m**, p90 **152 m** |
| under 120 m | **85%** of the sea | the whole operational range |
| past 460 m | the Skagerrak lip of the AOI | Landsort, the deepest Baltic point, is 459 m |

The bands were cut on the 0.03° grid and re-measured on the native raster: the shares moved
by under 1.3 points, which is the evidence that the cuts describe the sea and not the
sampling.

Each band therefore carries between **2.9% and 18.8%** of the sea: no colour is wasted and
none swamps the map. The violet that the official ramp spends on 6,000 m trenches now means
the Baltic deeps.

One cut is not statistical. **100 m** is where anchoring a merchant stops being practical,
which is the question this whole tool exists to answer (§15, IND-05), so the legend marks
it with a rule rather than another colour.

**Only the sea is painted.** The grid carries no value on land, and nothing is invented to
fill it — the basemap shows through. That is also how you can tell the layer is drawing
real measurements and not a styled coastline.

**Where the pixels come from.** Not from the 0.03° working grid — from EMODnet's native
GeoTIFF blocks at **~116 m**, which the build already downloads to make that grid, so the
better picture costs no extra network. The published image is **4096 x 4793 px, ~292 m per
pixel, 745 kB**. For exact contours still use the **Isobaths** layer, cut at 20, 50, 80 and
100 m. It renders with hard pixel edges on purpose: with nine discrete bands, letting the
browser smooth between them would invent colours that are not in the legend.

**It is pre-projected.** The PNG is written in **EPSG:3857**, with its rows spaced evenly
in Mercator y rather than in latitude. That is not a detail: Leaflet stretches an image
overlay linearly across the projected rectangle, so rows spaced evenly in latitude land in
the wrong place — up to **66 km out** in the middle of the Baltic and exactly right at the
top and bottom edges, which is what "the layer does not line up" looks like from outside.
A regression check compares the published PNG against the independently built depth grid
and requires **99%** agreement away from the coast, and requires the old mapping to score
clearly worse, so the check cannot pass by accident.

It costs nothing until you ask for it: the image is built once, at build time, and is not
fetched until the layer is switched on.

---

## 5. First five minutes


Everything that floats over the map can be hidden. The small toolbar at the top right of the map
has one button per panel — **Sources**, **Legend**, **Time**, **Progress** — and each panel also
has its own `×`. The state is remembered in your browser. By default **Progress is off**: the
badges are cosmetic and were getting in the way.

**Tour** replays a short three-step walkthrough on demand. It no longer appears by itself.

If you prefer to find your own way:

1. **Red circles are alerts.** Behaviour worth a human look.
2. **Orange circles are exposures.** Geometry only — a vessel near infrastructure. Usually
   completely normal, shown for context.
2d. **Vessels are triangles.** The triangle points where the bow points — reported heading, or
course over ground when heading is absent. A vessel reporting neither is drawn as a circle,
because an arrow pointing at a guess is worse than no arrow. Light blue means making way, grey
means stopped.

Every vessel popup carries two blocks: **Identity** (flag derived from the MMSI prefix, class,
MMSI, with the standing warning that name and class are self-reported) and **How it sits on the
water** — water depth beneath it, whether an anchor could reach the bed there, bow heading,
course over ground, and the **crab angle** between the two, flagged when it exceeds 20°.

3. **Click any alert.** The side panel replaces the list with a full explanation: what the
   indicator is, why this one fired, and — the part that matters — **what it does not prove**.
4. **Click a cable, a depth contour or a Sentinel-1 footprint.** Everything on the map carries
   its own evidence popup.
5. **Open Sources ▸ Build health.** It lists every layer that came back empty and why, in the
   build's own words. Nothing is hidden.

The progress bar and badges at the top track what *you* have looked at. They are cosmetic: they
never change a number, and they live only in your browser.

---

## 6. Time — what instant am I looking at


The bar at the bottom of the map answers this, always:

- **A green `LIVE` badge** means the newest fix in the store is less than five minutes old.
  **An amber `NOT LIVE` badge** means you are looking at the past, and the timestamp next to it
  says exactly when.
- **The green marks under the slider are the coverage windows** — the stretches where polling
  actually ran. Everything between them is a gap where nothing was recorded.
- **The caption spells out the ratio**, e.g. *3 coverage windows, 2.5 h recorded in total across
  a 14 d span.* That is the honest state of this dataset: a span of days with hours of data in it.

### Live mode

**Go live** polls `meri.digitraffic.fi` straight from the browser — the API answers with
`access-control-allow-origin: *`, so no proxy and no key. It refreshes every 60 s and hides the
static last-known-position layer. Press it again to go back offline.

**Going live moves the clock with it.** The moment the first poll lands:

- the timeline extends to the newest position received, so the slider can actually reach the
  present instead of stopping at the end of the last build;
- the cursor jumps there, and every poll afterwards drags it forward — the map is a live scene,
  not a frozen one;
- the view narrows to the last 6 h, because the full dataset spans days of recording gaps and
  the cursor is invisible at that zoom;
- a green band grows on the **AIS recorded** lane. Live polling *is* coverage, and the lane
  would otherwise claim we were blind while watching.

The header line states the one number that matters: **how old the newest position is**, which is
not the same as when the API last answered. A successful poll that returns a fix from 40 minutes
ago means the vessel has not reported for 40 minutes.

**Scrubbing back does not switch live off.** Moving the cursor by hand unhooks it from the
present and a **Back to now** button appears; polling carries on in the background the whole
time. **Latest** re-hooks it.

This is the only part of the viewer that needs the network by default. Everything else stays local.

### The timeline is the control

Below the slider there is **one lane per data source**, in four collapsible groups. The
groups answer different questions, so they fold independently and remember what you left
open.

| Group | What is in it |
|---|---|
| **What we record ourselves** | AIS recorded (our own polling windows), Alerts evaluated (the engine's rolling window), AISHub (idle until there is a key) |
| **Satellite imagery** | Sentinel-1 and Sentinel-2 passes, one tick per acquisition, cloud cover in the tooltip |
| **Weather, sea and ice models** | FMI HARMONIE wind, FMI WAM wave, and the Copernicus Marine datasets grouped by cadence |
| **Charts and infrastructure** | Depth, coastline, cables, ports, wrecks, restricted areas — no time axis, so one lane for all of them |

**The windows are read from each service, never written here.** A cadence typed into the
source goes stale without telling anyone: that is how we spent a while requesting **daily
means** of surface current believing they were hourly. So AIS comes from the polllog, the
Sentinel ticks from the STAC catalogue, Copernicus from the `time` dimension its WMTS
declares, and FMI from the time axis its own answer carries.

**Copernicus is grouped by dataset, not by layer.** Twenty lanes would be noise and also
redundant: layers sharing a dataset share a time axis by definition. Four lanes say the
same thing without repeating it —

| Lane | Cadence | Covers |
|---|---|---|
| CMEMS currents/water · 15 min | 900 s | surface current, sea level |
| CMEMS ice/water · 1 h | 3600 s | ice concentration, thickness and drift, temperature, salinity, mixed layer |
| CMEMS waves · 1 h | 3600 s | all eight wave variables, Stokes drift included |
| CMEMS reanalysis · 1 d | 86400 s | the same for a past day, ending about six weeks behind |

**The line under the lanes is the answer to "can I overlay these?"** It counts how many
time-bearing sources have data at the cursor and names them. If it says one, there is
nothing to overlay at that instant, and it is better to know before turning on four layers
and wondering why three are empty.

Reading a lane:

| Mark | Means |
|---|---|
| Solid band | data for that stretch |
| Tick | a single instant — a satellite acquisition |
| Hatched | **forecast**: past now a model keeps producing values, and a prediction should not look like a measurement |
| `→` or `←` at the edge | data exists, but outside this view. An empty lane reads as "none"; this reads as "beyond". FMI point queries always show `→`, because they start at the next whole hour, which is always after the newest fix |
| `key` | the source works but needs credentials |
| `∞` | no time axis — pair it with anything |

**Click a pass or a window and the cursor jumps to that exact instant.** The vessel
snapshot, the imagery, the forcing layers and the age readouts all follow it. That is how
you reconstruct a moment from several sources at once: click the Sentinel-1 tick, and the
map shows the radar scene plus every AIS position as it stood at that acquisition. Clicking
anywhere else on a lane moves the cursor to that position.

### Moving the cursor

| Control | What it does |
|---|---|
| Slider | Any minute in the dataset span |
| `←` `→` | Jump to the previous / next coverage window. Sliding through a gap only ages the markers, so the arrows skip the void |
| `▶` | Play forward through the current window, one minute per tick |
| **Latest** | Jump to the newest fix |
| **Hide snapshot** | Remove the snapshot layer and leave the static map |
| Date picker | Jump to any day in the store; the slider then spans that day |
| `24h / 7d / all` | How much of the span the slider covers. **24 h by default** — the full span is mostly gap, which made the control useless |

**If the ships did not move when you dragged the slider**, that was a bug, now fixed: the static
`positions` layer sat on top of the snapshot and hid it. The snapshot layer now removes it.

The map draws a **snapshot**: for every vessel, its last fix *at or before the cursor*. Fresh
fixes (under 30 minutes old at that instant) are bright green; anything older is dim and the popup
states its age. The counter reads *"N fresh of M shown"*, so a snapshot made of stale markers
cannot be mistaken for a live picture.

---

## 7. Sentinel-1 and Sentinel-2 on the map

Two modes, and they are different mechanisms on purpose.

| **Follow the time cursor** | What it answers | How it is built |
|---|---|---|
| **off** — coverage | *How does the sea look now, everywhere?* | **One server-side mosaic.** A STAC search is registered with Planetary Computer's `titiler-pgstac`, which composites on the server and returns a single tile endpoint. `sortby: datetime desc`, so where swaths overlap the most recent pass wins |
| **on** — reconstruction | *What did the satellite see at this instant?* | **One named scene**, with its identifier shown. A mosaic here would blend dates and lie about the moment |

Coverage mode used to stitch up to 165 separate tile layers in the browser. That is where
the patchwork seams and the sluggishness came from. The mosaic is **one layer**: measured
on a Gulf view, 1 Leaflet layer, 20 tile requests, 641 kB for the whole viewport.

**Zooming out keeps the imagery.** The tiler has no tiles below zoom 8 — verified, z5 to z7
come back as 0 bytes — so the layer declares `minNativeZoom`, and Leaflet reuses the zoom-8
tiles scaled down rather than asking for tiles that do not exist. Below zoom 6 the layer is
released, because each level out quadruples the tiles needed to fill the view (16 at z9, 169
at z6) and a 10 m pixel at that scale shows nothing.

**Navigation is never restricted.** That is worth stating because it was briefly broken:
declaring the tiler's limit as the layer's `minZoom` made Leaflet apply it to the whole map
and disabled the zoom-out button. The map now pins its own zoom range, so no layer can ever
constrain where you can look. If there is no imagery, there is no imagery — you can still
go wherever you want.

**One thing it does not fix:** brightness still steps between adjacent orbits. That is a
genuine radiometric difference between passes of different dates and incidence angles, not
a rendering fault, and removing it needs normalisation the free tiler does not offer.



Click any Sentinel-1 footprint, then **Show SAR**. The scene is drawn as georeferenced map tiles
from **Microsoft Planetary Computer**, which signs Sentinel-1 GRD with an anonymous SAS token —
free, no account. Verified end to end: a 256×256 VV tile over the Gulf comes back as a valid PNG.

Two notes. The AWS copy of the same data (`s3://sentinel-s1-l1c`) is **requester-pays**, so it is
not the free route. And CDSE scene ids carry a `_XXXX_COG` suffix that Planetary Computer does not
use; the viewer trims the id to its canonical eight fields before asking.

---

## 8. Vessel situation — one click

Click any vessel, on the map or in the list, and the first button is **Vessel situation**.
It is the switch from *what is happening in the Gulf* to *what is happening with this
hull*, and it does everything in one go:

- **The complete known track**, not a slice of it. It used to open at seven days and you
  had to press *All* to see the rest, so the first impression was a truncated voyage with
  no warning.
- **The declared destination in frame.** The map fits the track *and* the port the vessel
  says it is going to. If that is Kaliningrad, the view pulls back to most of the Baltic —
  and that distance is the information.
- **The photograph and particulars**, where a free-licensed photo exists.
- **The radar check running by itself** against every Sentinel-1 pass over the track.

The range buttons are still there to narrow it down afterwards.

### What folds away when it is empty

Two blocks used to take up half the panel to say nothing. Both now collapse to a single
line unless there is something to show:

- **Radar confirmation**, when no pass crosses the track at all.
- **The satellite chip**, when no pass covers the point — and also when a pass covers it
  but the pixels are not there. A Sentinel-1 scene can contain a point by geometry and
  still be blank at it: swath edge, acquisition gap, masked data. The viewer reads the
  image it just loaded and, if it is flat, steps to the next pass before giving up.
  **The two fold together**, so a vessel with no usable imagery costs one line, not half
  a screen.

---

### Arriving from an alert

Opening a vessel from an alert is not the same as opening it from the fleet list, and the
panel says so. The header takes the alert's severity colour — the same ISO 22324 / CAP
scale as the list — and a **Why this alert fired** block sits directly under the range
selector, before anything else.

That block is the alert's own `evidence`, not a re-reading: *silent for 41 min, back at
20:05Z, moved 0.2 NM meanwhile*; *10.2° off its heading, same side in 93% of 14 fixes*;
*279 kn implied against 11.1 kn reported*. Under it comes the section that holds the proof,
already open — the gap list for IND-04 and IND-07, the positions for the rest — with the
one row that fired it highlighted. For position-based indicators you get only the fixes
inside the alert window; the full track stays collapsed further down, because promoting
1,200 rows to point at 19 of them is a wall, not an answer.

On the map, the alert's time window is drawn thick in the severity colour over the track,
with a ring at the alert's own position. **Back to the alert** returns to the detail view.

---

## 8b. Vessel history — the Pathfinder view


Click any snapshot marker, then **Position history**. You get:

- Every recorded position for that vessel, newest first, with time and speed. Click a row to
  centre the map on it.
- The track drawn in amber, with the last position marked.
- **Reporting gaps** over 15 minutes, listed with their duration — and the standing caveat that a
  gap in our store is not proof the vessel went dark. It can be the transponder, the coverage, or
  our own recorder being stopped.

History comes from per-vertex timestamps that `build.py` writes into `tracks.geojson`
(`times` and `sogs`, shaped like `coordinates`). No extra file, no extra request.

---

## 9. The declared route

AIS message 5 carries a `destination` field that the crew types. It is twenty characters of
free text, not an identifier, and in the Gulf all three forms show up at once — `RULED`,
`RU LED`, `ST PETERSBURG` — alongside things that are not a port at all, like `FOR ORDER`
or `HARBOUR ASSISTANCE`.

Open **Position history** and, when the destination resolves, the map draws a **teal dashed
line from the last position to the declared port**. Dashed and teal on purpose: it is a
projection, not a track, and must not be confused with the magenta line of what the vessel
actually did.

### What it is for

Not the arrow. **The angle.**

| Row | What it is |
|---|---|
| Destination (AIS) | What the crew typed, and the port it resolved to |
| Bearing to it | Rhumb-line bearing and distance from the last position |
| Course being made | Bearing of the last real leg of the track — not the COG field, which can be stale |
| **Divergence** | The gap between the two |
| At current speed | Time to destination at the last reported SOG |

**A vessel whose course does not point at its declared destination is doing something
else.** Diverting, waiting, manoeuvring, or lying in the field. Past 35° the block turns
amber. That is not proof of anything — a turn, a waypoint, traffic or weather all produce
it — but it is a cheap, continuous check that costs no extra data and that nothing else in
the tool performs.

### Honest limits

- **Straight line to the port.** It ignores traffic separation schemes, ice, and the
  coastline. It is a bearing, not a passage plan.
- **The destination is unverified.** Nobody checks what the crew types. A vessel intending
  to go dark has every reason to type something plausible, so agreement proves less than
  disagreement does.
- **The port table is hand-curated**, 48 Baltic commercial ports, and resolves **53% of the
  592 tracks** in a typical build. The rest are ferry routes and small harbours. It is
  deliberately not fuzzy-matched against the OSM port layer, because those are mostly guest
  marinas and matching a tanker to a dinghy pontoon would be worse than saying "unresolved".
  When a destination resolves by prefix rather than by exact code, the panel says so.

---

## 10. Reading an alert

The panel leads with the two actions you actually use — **Show on map** and **Position
history** — then the evidence: the satellite chip, and what the place is. Everything
explanatory is folded into one collapsed block headed by the indicator's own title, so a reader
who already knows what an IND-04 is never scrolls past the explanation, and one who does not is
one click away.

### The satellite chip

Click any alert and the panel leads with a **satellite chip**: the slice of the Copernicus
scene centred on that exact point and that exact moment. It is the same thing Skylight shows in
its event panel, and there is nothing proprietary about it — the thumbnail comes from the same
public Sentinel-1, through Planetary Computer's `item/bbox` endpoint, with no account and no
key.

**Verified against Skylight directly.** Taking the point, time and scene from a Skylight
screenshot — 59.8430 N, 25.8335 E, 7 Nov 2026 04:41 UTC, scene
`S1C_IW_GRDH_1SDV_20261107T044122` — the chip renders the same vessel, the same radar return,
the same shape.

### What is on the chip, and why

A thumbnail on its own is decoration. These four things are what make it evidence:

| On the chip | Why it is there |
|---|---|
| **Scale bar** | A 300 m tanker and a 30 m tug look identical without a ruler. The bar is a fixed quarter of the crop, so its length in metres is exact by construction, not estimated |
| **North arrow** | SAR geometry is not intuitive and the crop is not always north-up in the reader's head |
| **Crosshair** | Marks the exact point the alert is about. Without it you are looking at a square of sea |
| **Offset** | `−2.2 d` is the gap between the acquisition and the event. **A large offset means the satellite was not there when it happened** — and the chip is then context, not proof |

Below it: the scene identifier in full, so a third party can reproduce the crop, and **Open in
Copernicus Browser**, which drops you at the same point and date in ESA's own viewer. That link
is the difference between a screenshot and a verifiable claim.

### Using it

- **Sentinel-1 SAR / Sentinel-2 optical** — switch sensor. Radar sees through cloud and the
  Finnish winter night; optical is readable only from roughly March to October above 60°N.
- **← →** step through every pass that actually covers the point, nearest in time first.
- **250 m / 500 m / 1 km / 3 km** change the crop width. 250 m fills the frame with one hull;
  3 km shows what else was around it.

Passes are filtered by the **true scene footprint**, not by its bounding box. A Sentinel-1 swath
is a slanted parallelogram and its axis-aligned bbox can be twice its area, so bbox filtering
offered passes that do not cover the point and rendered a black square. The viewer runs a
point-in-polygon test against the footprint instead.

> **A bug this feature exposed.** The pass catalogue was being queried with the AOI permuted to
> `[lat, lon, lat, lon]` — a box at 59–61° E, 22–30° N, which is the Arabian Sea. The
> Sentinel-1 and Sentinel-2 lanes on the timeline had been showing passes over the wrong part
> of the planet. Fixed, and the viewer now validates the catalogue bbox against the positions
> of the vessels it is actually tracking: a box containing none of them is rejected with an
> error rather than quietly returning scenes from somewhere else.



Every detail view has the same five blocks, in the same order:

1. **Name note**, when the name needs unpacking. `NATO WARSHIP` is not a ship name — see §16.
2. **What is this** — the indicator in one sentence.
3. **Why was it flagged** — the physical reasoning.
4. **What it does not prove** — the honest limit, always shown, never collapsed.
5. **Collapsible detail** — measured evidence, vessel particulars, technical mapping and scores.

The detail opens *inside the panel*, which scrolls. Map popups stay short on purpose: an earlier
build put the whole evidence table in a popup and it ran off the screen.

---

## 11. Colour and ordering of alerts


Colours follow two citable standards rather than taste:

- **ISO 22324:2022** (*Security and resilience — Emergency management — Guidelines for
  colour-coded alerts*): red = danger, act now; yellow = caution, prepare; green = safe. Blue and
  grey are the standard's supplementary colours for information that is **not** a hazard level.
- **CAP** (OASIS Common Alerting Protocol) severity vocabulary with the colour mapping
  harmonised by **EUMETNET Meteoalarm** across EU states: Extreme=red, Severe=orange,
  Moderate=yellow, Minor=green.

**Exposures take the supplementary blue, never a point on the red–green spectrum.** They are
context, and painting them yellow would claim a caution the data does not support.

The band edges are calibrated on this store's real score distribution, not on textbook
0.25/0.50/0.75. Measured over 62 alerts the maximum composite score is 0.317 and the median
0.095, so a textbook scale painted 97 % of them green and discriminated nothing. Current edges
live in one place, `viewer/severity.js` → `SEV_BANDS`, and are **provisional**: they will move
once there are weeks of data.

**Sort by** sits above the list: severity, most recent, score, closest to infrastructure, or
indicator.

---

## 12. Filters — the operator console


The person reading the map is the one who knows which traffic matters today. Everything in this
tab acts **instantly on the build you already have**: no rebuild, no reload, no round trip.

**What it does not do:** it does not change detection. An alert that was never generated cannot
be filtered into existence. The thresholds that decide what becomes an alert live in
`custody/indicators.py`, run at build time, and are shown unchanged at the bottom of the tab.
What you control here is which part of what was detected reaches your eyes.

| Control | What it does | Why it is the one you want |
|---|---|---|
| **Minimum composite score** | Hides everything below the score | The fastest way to go from 250 markers to the ten worth reading |
| **Maximum distance to a cable or pipeline** | Only keeps alerts within that many metres of a trunk corridor | 1 NM (1852 m) is the strict-proximity band; below 500 m you are on the cable |
| **Minimum episode duration** | Drops short episodes | A two-minute slowdown is traffic. Forty minutes over a cable is not |
| **Maximum depth** | Drops alerts in water deeper than this | Physical: if the anchor cannot reach the bed, dragging it is not the hypothesis |
| **Hide self-declared military and service craft** | Removes AIS ship types that declare themselves | This is the NATO WARSHIP switch. See §16 |
| **Indicator** | Per-IND on/off, with live counts | |
| **Severity** | Per-band on/off, ISO 22324 colours | |
| **Detection filters** | Re-admits candidates the build suppressed, by reason | See §14 |
| **Time window for alerts** | Only alerts near the time cursor | Keeps the alert list in sync with the scene you are looking at |

A slider pushed to its top means *no limit*, not *maximum*. **Reset filters** puts everything
back. Nothing here is stored: a reload returns to the full set, deliberately, so that nobody
ever demos a filtered map believing it is the whole picture.

---

## 13. Large files load on demand


The four heaviest layers no longer block the first paint. `restrictions.geojson` alone is 6.9 MB,
`corridors_other` 1.5 MB, `isobaths` 0.8 MB, `ports` 0.3 MB. They now:

- download **in the background** once the map is usable, paced with `requestIdleCallback`;
- or download **immediately** if you tick their checkbox in the Layers tab first;
- show a **progress bar** at the bottom left, read from `Content-Length` via a streaming reader.
  When the server sends no length the bar shows kilobytes received instead of a percentage,
  which is honest and still informative.

Until a layer arrives, its checkbox is listed with *loads on demand*.

---

## 14. Suppressed detections — what the layer is, and is not


A candidate detection that falls inside a port mask, in water too shallow for an anchor to
reach, too close to the coast, or whose crab angle flips sign, is **never emitted as an alert**.
That decision happens at build time, in `custody/indicators.py`.

The **Suppressed detections (audit)** layer is a read-only window onto those decisions.

- **Turning it off hides the markers. Nothing else.** No data is deleted, nothing is recomputed,
  and nothing reappears in the alerts layer.
- **Turning it on does not restore anything either.** The suppressed candidates were never alerts;
  you are looking at a record of what the filter removed, not at live detections.
- To change **what gets detected**, edit `THRESHOLDS` in `custody/indicators.py` and rebuild.
  Every threshold there carries its physical justification and a confidence rating.
- To change **what you see**, use the hot filters in the **Filters** tab. They act instantly on
  the build you already have. See §12.

**The layer is not complete, and says so.** Of 13,732 suppressions in the current build, 695 are
mapped. The per-episode filters are mapped in full — port mask, near-coast, too-shallow, AOI
edge. The two that fire per sample rather than per episode are mapped as a sample: crab-angle
sign flips 1 in 50 of 8,179, and depth-band 1 in 20 of 5,287. Full counts per reason are under
**Filters ▸ Threshold values used by this build**.

---

# Part III — The data

## 15. The seven indicators


| | Name | Type | One-line |
|---|---|---|---|
| **IND-01** | Slow and steady over a cable | alert | 1–5 kn held ≥30 min on a corridor: the anchor-drag speed band |
| **IND-02** | Crabbing | alert | Heading and course disagree, always to the same side |
| **IND-03** | Loitering | exposure | Stayed in a small area. 8 of 10 measured were pilot boats |
| **IND-04** | Stopped reporting | alert | An AIS gap — *in our data*, which is not the same thing |
| **IND-05** | Close to infrastructure | exposure | Within 1 NM of a cable, weighted by depth. Every ferry does this |
| **IND-06** | Met another vessel | exposure | Ship-to-ship away from port. All 15 measured were pilots |
| **IND-07** | Appeared where it could not have got to | alert | Two consecutive fixes imply a speed no hull here can reach. **Detection is arithmetic; the cause is not determined** — MMSI collision, spoofing, decoding error and receiver fault all look identical. One alert per vessel, with the jump count |

Three were **downgraded to exposure by measurement, not opinion**, because benign fixed
infrastructure dominated their output. The Learn tab carries the counts.

---

## 16. What is "NATO WARSHIP"?


A warship of a NATO member operating under an allied task group. **It is not a real ship name:**
it is a generic identity that allied navies broadcast over AIS instead of their own, so merchant
traffic can see them for collision avoidance without learning which unit they are. In the Gulf of
Finland they are usually units of **Baltic Sentry**, the NATO activity set up to protect subsea
cables after the 2023–2025 incidents.

The MMSI prefix still gives the flag: `230` Finland, `265` Sweden, `276` Estonia, `277` Lithuania,
`211` Germany.

**Why it matters more than a footnote.** Two of these warships trigger IND-01 in this very
dataset — one 5.4 m from the Balticconnector, the other 47.5 m from Estlink 1, both at 3.4–5.0 kn
for half an hour. They were *protecting* the cables.

> The kinematic signature of the ship protecting the infrastructure and the ship attacking it is
> identical. No threshold fixes that. It is the single most important thing this prototype
> measured.

---

## 17. Showing the provenance


The **Sources** tab and the strip across the top of the map answer one question explicitly:
*which of this is space data, and whose?* Four tiers, kept apart on purpose:

| Tier | What is in it |
|---|---|
| **EU Space Programme** | Copernicus Sentinel-1 (radar) and Sentinel-2 (optical, true colour). ESA-built, Commission-owned |
| **European open data** | EMODnet Bathymetry — European and open, but surveyed by ship and aircraft, not from orbit |
| **Space-derived — non-EU operator** | Global Fishing Watch. Genuinely derived from satellite AIS and from Sentinel-1, but a US non-profit, so it does not belong in the EU row |
| **Terrestrial — not space data** | AIS from Fintraffic, received by **coastal VHF stations**. OpenStreetMap. Väylävirasto |

That last row matters. Our AIS is **not** satellite AIS, and the strip says so on screen. Claiming
it as space data in front of a space-agency jury would be the fastest way to lose the room.

Each source expands to operator, access route, licence, what it contributes, and its caveat.
Badges show whether it is in use, empty in this build, or not wired in at all.

---

## 17b. Adding another HELCOM layer

The on-demand coastline (§1) is not a one-off: it is a pattern, and the expensive part is
already written. Any **vector** layer on the HELCOM map server can be added the same way,
and most of the useful ones are vector.

**The pattern, and why each piece is there**

1. The host is already in the proxy allowlist (`viewer/server.py`, `ALLOWED`).
2. Query the ArcGIS REST endpoint by **envelope**, not whole: `geometry=w,s,e,n` with
   `geometryType=esriGeometryEnvelope&inSR=4326&outSR=4326&f=json`.
3. Pass **`maxAllowableOffset`** in degrees. The server generalises before sending, which
   is what makes this affordable — the coastline went from 3.7 MB to 254 kB per square on
   that parameter alone. Scale it to the zoom; asking for 8 m of detail to draw at 150 m
   per pixel is spending bandwidth on vertices nobody sees.
4. **Snap the envelope to a fixed grid**, not to the viewport. This is the piece that is
   easy to get wrong and silent when you do: two similar views must produce the *identical*
   URL, or the disk cache never hits and every mouse drag is a fresh download. A smoke
   check guards it.
5. Fetch through **`/cache/geo?u=<url>`** — a GET JSON proxy with a 30-day TTL. These
   datasets do not change between sessions.
6. Gate on zoom. Below a sensible level, do not fetch, and say on screen why not.

`viewer/coasthd.js` is about 120 lines end to end and is the worked example.

**Vector layers worth the next hour**, all confirmed present and queryable:

| Layer | Geometry | What it would answer |
|---|---|---|
| `MADS/Background/11` — Exclusive Economic Zone | polyline | Whose waters is this alert in? The tool currently says *where*, never *whose* |
| `MADS/Background/12` — Territorial waters | polyline | The 12 NM line: the difference between a nuisance and a sovereignty matter |
| `MADS/Background/14` — Depth contours | polyline | HELCOM's own isobaths, against which to check ours |
| `MADS/Shipping/325` — Shipping Accidents | point | Historical incidents, to compare against our own alerts |

One more is worth naming even though it does **not** fit this pattern:
`MADS/Shipping/345` — *2024 All shiptype AIS Shipping Density* — is a **raster**, so it
needs the image path (`/cache/img` or a WMS tile layer), not `/cache/geo`. It is the most
valuable of the lot: a baseline of where ships normally are. Every indicator in this tool
currently asks "is this behaviour odd in itself"; none can yet ask "is this vessel
somewhere vessels do not go", which is a different and often stronger question.

---

## 17c. Licences — what can actually be sold

Every source that enters the product has an entry in **`config/licences.toml`**: the
licence, whether commercial use is permitted, the required attribution, and the verbatim
quote where the wording matters. `tests/test_licences.py` fails if a layer in the build
cites a source that is not in the register, or one marked non-commercial, or one with no
attribution.

**This exists because of a real failure.** HELCOM's depth contours were integrated and
removed on the same day. Their use constraints read:

> These data sets are a piece of scientific work which relies on free interchange of
> scientific data. Therefore the data are available for scientific research only. [...]
> **Any commercial use is prohibited.**

They were replaced by isobaths derived from the EMODnet DTM, which is CC BY 4.0. EMODnet
publishes contours too, but they start at 50 m and the 20 m level is the one that decides
whether an anchor reaches the bed.

**Two lessons worth keeping.** First, **licences vary per dataset on the same server**:
HELCOM's coastline and sub-basins are free with citation, its depth contours are not. The
server is not the licence. Second, the failure was not one of judgement — it was that
there was nowhere for a licence to live, so nobody could notice one had not been checked.

**Three conditions that are easy to miss and do apply here:**

- **EMODnet: "DO NOT USE FOR NAVIGATION."** Custody is surveillance, not navigation: it
  never advises a course, a depth under keel or a route. That is what keeps it inside the
  condition, and it is worth being able to say so.
- **OpenStreetMap is ODbL**, and share-alike attaches to a derived *database*. Custody
  publishes alerts and indicators, not a cable dataset. If a cable layer is ever
  redistributed as data, ODbL comes with it.
- **Wikimedia Commons is a container, not a licence.** Each vessel photograph carries its
  own terms and most require naming the author, so the viewer has to show author and
  licence next to each image rather than a blanket credit.

The three sources of the GNSS-from-orbit recorder (Spire, Swarm, Sentinel-6) are not in
`config/licences.toml`: they feed the CTO's analysis, not the build. Their licences and
the two conditions that bind (Swarm raw never public; Spire after 1-Dec-2026 unsettled)
are in [Part 0-bis](#sources-and-licences).

---

## 18. Copernicus CDSE — what it is, and whether you need it


**CDSE** is the **Copernicus Data Space Ecosystem** (`dataspace.copernicus.eu`), the European
Commission's official front door to Sentinel data. It replaced the old Copernicus Open Access Hub
in 2023. It holds the full archive of Sentinel-1 (radar), Sentinel-2 (optical), Sentinel-3 (ocean
and land) and Sentinel-5P (atmosphere), with a free tier of roughly 12 TB of download per 30 days.

### What it adds to this map

| With no account | With a free account |
|---|---|
| Scene **catalogue** via the public STAC API: which Sentinel-1 passes crossed the Gulf, when, in which mode and polarisation | The same, plus the **GRD product itself** — the radar pixels |
| **Footprints** drawn on the map | Ship detection run on those pixels: bright targets on dark water, matched against AIS to find vessels that are there but not transmitting |
| Public **quicklooks** (not georeferenced) | Georeferenced imagery you can process yourself |

So without an account you get *when and where the satellite looked*. With one you get *what it saw*.

**You may not need it.** The viewer now draws georeferenced Sentinel-1 through **Microsoft
Planetary Computer**, which signs the same Copernicus data with an anonymous token — no account,
no cost. CDSE is still the route if you want to download and process GRD products locally, which
is what automated ship detection needs.

### Creating a CDSE account

1. Go to <https://dataspace.copernicus.eu/> and choose **Register**. It is free and open to
   anyone; no institutional affiliation is required.
2. Confirm the address from the email they send. The account is not usable until you do.
3. Sign in once at <https://browser.dataspace.copernicus.eu/> to check it works.
4. Put the credentials in **`custody_mvp/secrets.env`**:

```
CDSE_USERNAME=you@example.org
CDSE_PASSWORD=whatever"it"is
```

**Not JSON.** The loader takes everything after the first `=` literally, so double quotes, `$`
and spaces need no escaping. A password containing a `"` silently broke the old
`cdse_credentials.json` and the whole Sentinel-1 stage reported *"sin datos STAC"* — the parse
error, not a satellite problem.

Resolution order: environment variables (`CDSE_USERNAME`, `CDSE_PASSWORD`) → `secrets.env` →
legacy JSON. `secrets.env` is `chmod 600` and listed in `.gitignore`.

The client requests an OAuth2 token from
`identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token` with the
documented `cdse-public` client id. **Verified working.**

> **Where your secrets live.** `secrets.env` sits inside a Dropbox folder, so the password is
> synced to Dropbox's servers in plaintext. If that is not acceptable, move the file out of the
> tree and point `CUSTODY_SECRETS` at it, or export the two variables in your shell and delete
> the file.

### A note on identity

Any public API that asks for a `User-Agent` or a `Digitraffic-User` header receives whatever that
header says. This build sends `custody-mvp/0.1 (research prototype)` and
`ais-recorder/1.0 (research prototype)` — no name, no address. If you register with CDSE, that
address goes to the European Commission under their privacy policy, and is sent with every
authenticated request. Nothing else in this software identifies you.

---

## 19. Global Fishing Watch — a second opinion


### What it gives, and what it does not

GFW does **not** hand over raw AIS positions. It hands over **behaviour that has already been
classified**, and that is exactly why it is worth wiring in: it is a second opinion on the same
vessels, from another team, with another model and global coverage.

| Event | What it is | Why it matters here |
|---|---|---|
| `GAP` | An AIS silence their model judges **intentional** | This is our IND-04, computed independently. When GFW and we agree on a gap, the alert stops depending on our uncalibrated threshold |
| `ENCOUNTER` | Two vessels together at sea long enough to count | Corroborates IND-06 |
| `LOITERING` | A vessel hanging around at low speed | A ship loitering over a cable is the scenario |
| `PORT_VISIT` | A port call, confidence 2–4 | Closes the before-and-after of a transit |
| `FISHING` | Fishing activity | Near-empty in the Gulf of Finland. Wired in because it costs one line and the AOI may move |

They also publish **SAR presence**, derived from Sentinel-1, where the valuable field is
`matched = false`: a radar detection with no AIS to pair it with — a dark vessel. That product
is a gridded raster served as zipped CSV rather than GeoJSON, so it is **not wired in yet**; the
endpoint and dataset name are recorded in `custody/gfw.py`.

### Getting a token

1. Go to **globalfishingwatch.org/our-apis/tokens** and register. The token is free; the
   application form asks what you intend to use it for.
2. Create a token and copy it. It is a long JWT.
3. Add one line to **`custody_mvp/secrets.env`** (the same file that holds the CDSE
   credentials, `chmod 600`, gitignored):

   ```
   GFW_TOKEN=eyJhbGciOi...
   ```

4. Check it before rebuilding anything:

   ```bash
   cd software/custody_mvp
   python3 -m custody.gfw
   ```

   It makes one small live query — 90 days of AIS gaps in the Gulf — and prints either the first
   events it found or the exact reason it failed. `401` means the token is wrong or expired;
   `403` means it is valid but has no access to that dataset.

5. Rebuild: `./custody.sh build`. Without the token the build does not fail — the layer is
   written empty and **Sources ▸ Build health** says so, with the URL to fix it. `./custody.sh
   status` also reports whether the key is present, without ever printing its value.

The token is sent only in the `Authorization` header and never reaches the manifest, the logs or
the on-disk cache: `custody/net.py` keys the cache on method, URL and body, and headers are
deliberately outside that key.

### Using it

The layer is under **Layers ▸ Global Fishing Watch behaviour events** and is off by default.
Dashed circles, one colour per event type. Where a GFW event matches one of our alerts — same
MMSI, overlapping time, one hour of slack — the alert popup gains a green
**✓ Corroborated by Global Fishing Watch** line.

```bash
./custody.sh build -- --gfw-days 180                        # wider window (default 90)
./custody.sh build -- --gfw-events GAP,ENCOUNTER            # only these
./custody.sh build -- --gfw-days 0                          # off
```

**Licence: CC BY-SA 4.0, attribution required.** It is in the Sources tab and in the legend.
Note the ShareAlike: it is a stronger obligation than everything else in this build, and it
needs a legal look before any of this becomes a product.

---

### The activity grid — the baseline this tool was missing

GFW's web map paints a heat grid of apparent fishing activity. The technique is worth copying;
**the fishing dataset is not the one you want.** Cables in the Gulf of Finland get cut by a
cargo ship's anchor, not by a trawler.

The same endpoint serves three grids, and the default here is the second one:

| Grid | What a cell holds | Why |
|---|---|---|
| `fishing` | Apparent fishing hours | There is some Polish and Estonian trawling in the Gulf, but it is not the threat |
| **`presence`** *(default)* | Hours of **any** vessel | **The baseline.** See below |
| `sar` | Sentinel-1 detections filtered to `matched = 'false'` | A radar detection with no AIS to pair it with. A dark vessel. The single hardest thing on this list to build yourself |

**Why presence matters more than anything else here.** Every indicator in this tool is
*absolute*: slow over a cable fires an alert, against a threshold we admit is uncalibrated. A
presence grid supplies the other half of the sentence — how much traffic that cell normally
sees. "Below 5 knots" becomes "six times its own average", which survives the question *where
does that number come from?* It is the same gap that killed the earlier value propositions:
without a notion of normal, there is no anomaly, only a threshold.

```bash
./custody.sh build -- --gfw-grid presence,sar       # both
./custody.sh build -- --gfw-grid-res HIGH           # 0.01° instead of 0.1°
./custody.sh build -- --gfw-grid none               # off
```

Layer: **Layers ▸ Global Fishing Watch activity grid**, off by default. Colour is on a log
scale — vessel-hours per cell have a long tail and a linear ramp paints everything the same
shade except the Helsinki–Tallinn lane. Click a cell for its value and the rows behind it.

**One caveat in the code, stated plainly:** GFW does not publish stable column names for the
4wings CSV, so `grid_to_geojson` detects latitude, longitude and the value column by content
rather than assuming names. If it recognises nothing it writes an empty layer and says which
columns it actually got, instead of inventing a grid. The literal header is recorded in the
manifest. Once you have a token, the first build will tell you whether the detection was right.

### Can you build this yourself?

The behaviour classification, no — not usefully. GFW's intentional-gap model is trained on
years of global AIS and validated against known cases; reproducing it from fourteen days of
Gulf of Finland traffic is not a project, it is a thesis. The right move is exactly what is wired
in here: take theirs as an independent second opinion and spend your own effort on what they do
not do, which is the cable-specific physics — depth, anchor reach, corridor proximity, the
legal overlay.

The grid, yes, eventually. A presence baseline from your own recorder is arithmetic once you
have enough history, and it would be yours with no ShareAlike attached. That is an argument for
getting the HELCOM archive: with a full year of Baltic AIS you can compute your own baseline and
stop depending on anyone's licence.

---

## 20. Vessel dossier — size, photos, sanctions

Click a vessel and the panel leads with what is known about the hull itself, before any
behaviour. Three levels, and the manual keeps them apart because they do not deserve equal
trust.

### Level 1 — free, offline, exact

Length, beam and draught come out of **AIS message 5**, which the vessel broadcasts itself.
`referencePointA..D` are the distances from the GPS antenna to bow, stern, port and starboard
(ITU-R M.1371), so **length = A+B** and **beam = C+D**. Draught is `draught/10` in metres.

This was sitting in the store from day one and nothing used it. **1,299 of 1,332 vessels (97%)
now carry exact dimensions, with no network call.** It also drives the size classes in the
Vessels tab, and the cut-offs are not arbitrary: 25 m separates a boat from a ship, 100 m
coastal from deep-sea, and 200 m is where the Aframax and the large box ships start — the hulls
whose anchor can actually break a cable.

### Level 2 — free, online, authoritative

**Sanctions lists, matched by IMO and MMSI.** For a defence product this is worth more than a
photograph: a sanctioned tanker loitering over a cable is not the same event as a ferry doing
the same thing.

| List | What it gives | Confidence |
|---|---|---|
| **US Treasury OFAC SDN** | 1,570 vessels, 1,560 with IMO, 840 with MMSI, in structured XML. Programmes, registered owner, flag on the list, tonnage | **High.** Direct identifier match. US Government work, public domain |
| **EU consolidated list** | IMO numbers extracted from free text | **Low, and labelled as such.** The EU does not type vessels as subjects: the numbers live inside `remark` prose. A lead to check, not a determination |

The current build found **30 vessels in the Gulf on sanctions lists — 26 under
RUSSIA-EO14024**, mostly 240–300 m tankers. That is the shadow fleet, and it was already in
your own recording. A hit paints a red block at the top of the vessel panel and a red stripe on
its card in the list; **Vessels ▸ Sanctioned only** filters to them.

### Level 3 — free, online, partial

**Wikidata and Wikimedia Commons**, queried by IMO over SPARQL. Gives a photograph, gross
tonnage, deadweight and build year. No key, no account, CC0 for the data and a per-file licence
for each image.

Coverage is the honest caveat: **350 of the 400 largest hulls were found, but only 115 had a
photo.** Wikidata covers ferries, warships and famous tankers well and ordinary merchant traffic
badly. It is decoration that happens to be free and correctly licensed, not a source of
particulars.

Photos are routed through the local cache proxy (§2) for two reasons. They are cached on disk,
and — the one that matters — **Wikimedia never learns which vessel the operator is looking at.**
A direct `<img src>` would leak that with every click. They are also requested at 640 px: the
sample image drops from 845 kB to 147 kB.

### Classifying the fleet

The **Vessels** tab turns all of this into facets, and they filter the list instantly with no
rebuild:

- **Type** — the AIS ship-type code folded into families (cargo, tanker, passenger, fishing,
  service, military, sailing, pleasure, high-speed craft…). A typical build of the Gulf gives
  roughly 205 cargo, 102 tanker, 92 service, 50 passenger, 7 military.
- **Size** — `< 25 m`, `25–100 m`, `100–200 m`, `> 200 m`, from the measured length.
- **Flag** — the twelve most common in the current data, by count.
- **Sanctioned only** — one switch.

Every group except Type is collapsed until you open it, and a group with an active filter
re-opens itself so a forgotten filter cannot quietly shrink the list. Sanctioned hulls sort to
the top regardless, because that is the one row you cannot afford to lose in a list of five
hundred. **Reset filters** clears everything.

### Ticked means visible

The switch at the top of the tab — **"Ticked vessels are the visible ones"**, on by default —
makes the facets drive the **map**, not just the list. Untick a flag and those hulls leave the
screen: their markers, their tracks, their last-known positions, their live positions, **and
their alerts**. One predicate decides all of it, so the list and the map can never disagree
about what is being shown.

Filters compose, which is the point. The worked example:

1. Open **Flag**, untick everything except **Russia** → 65 hulls.
2. Tick **Sanctioned only** → **11 hulls**, and the map is now just those eleven.
3. Press **Draw their tracks**.

You get eleven tracks across the Gulf, **sanctioned hulls in red** and everything else on a hue
wheel, each one clickable. The map keeps 13 alert markers — the ones belonging to those eleven
— and drops the rest. That is the question "where is the danger" answered on one screen.

**Zoom to selection** frames the whole selection. **Draw their tracks** is capped at 80 tracks,
sanctioned hulls and longest tracks first; if anything is left out it says how many, because
silently drawing 80 of 500 would read as "this is all of it".

### The map tells you when it is lying by omission

Whenever the filter is hiding anything, an amber banner sits across the top of the map:

> ● **Map filtered — showing 11 of 530 vessels** · 13 alerts among them · Sanctioned only ·
> Flag −40 — *Zoom to selection* · *Draw their tracks* · *Clear filter*

This is not decoration. A filtered map shown to a room reads as the whole picture unless it
says otherwise, and that is a short walk from a demo to a false claim. The banner cannot be
dismissed while a filter is active; **Clear filter** removes both. If you want the facets to
filter the list only and leave the map whole, untick the switch at the top of the tab.

The usual warning applies and is worth repeating: the type is **self-declared**. Service and
military types are *marked*, never filtered out — the vessels most worth looking at are
precisely the ones that might be lying about what they are. See §16.

### Where else this data could come from

| Source | What it has | Why it is not wired in |
|---|---|---|
| **Equasis** | The authoritative free particulars: tonnage, owner, class society, P&I, inspection history | Free **with registration**, but **no API**, and scraping breaks its terms. If this becomes a product it is a licence to negotiate, not a scraper to hide |
| **IHS / S&P Sea-web, Lloyd's List** | The industry reference | Commercial, expensive |
| **MarineTraffic, VesselFinder** | Excellent photos and particulars | Paid API; the free tiers are too thin to build on |
| **THETIS-EU and Paris MoU** | Port State Control inspections and **detentions** by IMO. A recent detention changes how you read an alert | Public and highly relevant, but a web form, no API. **The best remaining free win — worth the scraping conversation with EMSA rather than a scraper** |
| **IMO GISIS** | Official registry | Account required, no API |
| **ITU MARS** | The official MMSI registry | No bulk API |

The flag shown for each vessel is deduced from the **MID**, the first three digits of the MMSI
(ITU-R M.585). The full ITU table lives in `custody/vesselinfo.py` — one source, resolved at
build time. Note what it actually proves: not the real flag state, but **which administration
issued the identifier the vessel claims to have.** Like everything else in AIS, it is
self-declared.

```bash
./custody.sh build -- --no-vessel-info        # skip the network part; dimensions still computed
./custody.sh build -- --wikidata-limit 1000   # query more hulls, largest first
```

---

## 21. The seabed, and the submarine question

### Is there a submarine database? Not the one you are hoping for

**There is no open database of submarine positions, and there will not be one.** Two reasons,
and neither is going to change:

- A submerged submarine cannot broadcast AIS. VHF does not propagate through seawater. It is
  physics, not policy.
- A surfaced one keeps AIS off. Submarine positions are among the most closely held secrets any
  navy has. No NATO or Russian navy publishes them, and anything claiming to show live
  submarine tracks is selling you fabrication.

What **is** open, and is now wired in or reachable:

| Open | What it is | Status here |
|---|---|---|
| **Submarine wrecks** | Hulls on the seabed, surveyed and catalogued | **Integrated.** 3 in the Gulf |
| **Order of battle** | Which boats each navy has: class, name, commissioning | Reachable via Wikidata (CC0), not wired in — it is reference, not a map layer |
| **Surface transits** | A submarine crossing the Danish Straits must surface, and sometimes broadcasts AIS for collision avoidance | Would appear in your own AIS like any other vessel. AIS type 35, "Military ops", is already classified in the Vessels tab |

### What did get integrated

Three layers from **EMODnet Human Activities**, chosen because each answers a question the
viewer was already asking and could not answer. Verified against the Gulf AOI on 10 Nov 2026.

**Shipwrecks — 693, of which 587 are catalogued "dangerous wreck", and 3 are submarines:**

| Wreck | Position | Note |
|---|---|---|
| **U 26** | 23.8333 E, 59.6667 N | German WWI U-boat |
| **NO 9** | 24.8817 E, 59.8692 N | Sunk 22 May 1931 |
| *(unnamed)* | 24.9968 E, 60.0002 N | British |

A wreck matters here for a reason that has nothing to do with history. It is a **permanent
return on radar and sonar and a fixed obstacle on the bottom**. Near one, a SAR detection may be
the wreck rather than a ship, and a vessel stopped on top of it may be diving on it rather than
interfering with a cable. **5 alerts in the current build sit within 500 m of a known wreck**,
and each one now says so.

**National defence areas — 24 declared areas, Finland and Estonia**, each with a link to the
issuing ministry. This is the most useful of the three, because it attacks the NATO WARSHIP
problem head-on: **a warship moving slowly inside a declared defence area is a Tuesday, not an
anomaly.** **18 of 127 alerts** in the current build fall inside one.

Consistent with the rule that runs through this whole tool: the alert is **annotated, never
suppressed**. It still appears, still carries its score, and now carries the sentence that lets
you weigh it. Deciding is the operator's job; hiding the evidence would be making that decision
for them.

**Munitions dumping grounds — 3 Russian conventional-explosive dump sites**, sourced from
HELCOM. Anchoring and bottom contact there are prohibited and dangerous, so a vessel anchoring
inside one reads very differently from one anchoring anywhere else.

### Why is this area special? The popup answers it

"18 of 127 alerts fall inside a declared national defence area" is only useful if you can see
where that comes from and what the area actually is. Click any defence area and the popup
answers both, in this order.

**What is inside it** — computed at build time against the layers this tool already holds, so
every line is reproducible from the same files. For the largest Finnish area, 418 km²:

| | |
|---|---|
| **Subsea infrastructure crossing it** | **Balticconnector** (pipeline) · **Estlink 1** (power, EE) · **BCS North Phase 1** (telecom, Arelion) · **Baltic Sea Submarine Cable** (telecom, CITIC Telecom) · **Eastern Light Sweden–Finland I** (telecom) |
| Wrecks inside | 3 |
| Depth range | 3.1–68.5 m — an anchor reaches the bottom across all of it |
| Distinct vessels seen inside | 6, in the recorded window |

That is the answer to *what is there that someone wants to protect*: the gas interconnector that
was damaged in October 2023 and four telecom and power cables, in water shallow enough to anchor
in throughout.

**Where the designation comes from**, named explicitly rather than implied:

| | |
|---|---|
| Designation | National Defence Area |
| Published by | EMODnet Human Activities |
| Originating authority | Finland (Maritime Spatial Plan) / Estonia (Ministry of Defence) |
| Legal framework | *Aluevalvontalaki 755/2000*, the Finnish Territorial Surveillance Act |

Two buttons go to the originating authority's page and to the statute on Finlex. The popup also
carries a caveat that is in the code for a reason: **the polygon comes from the Maritime Spatial
Plan via EMODnet, not from the statute text.** Treat the boundary as indicative and the specific
article as unverified until you have checked it against Finlex. Finlex is a JavaScript
application with no working open-data endpoint for this act, so it was not machine-verified here.

### The finding this produced

**6 of the 24 defence areas have a trunk cable or pipeline running through them. All 6 have zero
anchoring prohibitions inside.** Across all 24 areas there is exactly one.

A defence designation restricts *military* access. It is not, by itself, a ban on anchoring.
Without a Väylävirasto prohibition inside the polygon, dropping an anchor on top of
Balticconnector is not in itself an offence — and that is the same gap this project found
earlier for the trunk corridors. The popup says so in an amber block whenever an area has a
cable inside and no ban: the tool is not going to let that pass quietly.

### Where it shows up

- **Layers ▸ Defence interest.** The whole group is listed under one heading with its sources
  named on the line beneath — *EMODnet Human Activities · Väylävirasto · HELCOM* — and each
  layer toggles independently: national defence areas, munitions dumping grounds, shipwrecks,
  anchoring bans, other navigation restrictions. Wrecks and defence areas load on demand (693
  wrecks is 192 kB). Submarine wrecks get their own marker so they are findable among the
  other 690.
- **In the alert panel**, immediately below the satellite chip, as **Seabed and declared
  areas** — the chip tells you what the place looked like, this tells you what the place *is*.

```bash
./custody.sh build -- --no-seabed      # skip all three
```

Licence: EMODnet terms, open with attribution. The munitions data originates with HELCOM.

---

## 22. Detecting ships in the SAR image

Yes, those white dots are ships. A metal hull is a corner reflector: it returns far more energy
than the sea around it. The standard algorithm is **CFAR** (Constant False Alarm Rate), and
**Detect ships in this crop** on any Sentinel-1 chip runs it.

### Validated, not asserted

Run against a detection Skylight published — scene `S1C_IW_GRDH_1SDV_20261107T044122`, point
59.8430 N / 25.8335 E — this detector placed a target **55 m** from the position they report.
Same vessel, from a free Copernicus crop, in about a hundred lines of standard library.

### Where it lives now

The loose "detect targets in this crop" button told you very little: a list of bright
things with no context. **The useful version is tied to one vessel's track**, and it is in
the vessel panel as **Radar confirmation of this track** — see below. The per-crop button
is still on the chip for when you want to sweep an area, but the track check is the one
that answers a question.

### How it works, and why it has to work that way

**The name is the design goal, not a description.** Constant False Alarm Rate: keep the rate of
false alarms constant *even though the background changes*. It is a detector of **local
contrast**, not of brightness.

The reason that matters: in a SAR image the absolute brightness of a ship means nothing. What
means something is **how far it stands out from the sea immediately around it**. With wind, the
sea returns far more energy, so a small hull in rough water can be brighter in absolute terms
than a freighter in calm water.

```
        ← bg_px = 12 →
   ███████████████████████     ███  background ring: mean and sigma come from here
   ███████████████████████
   ████▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒████     ▒▒▒  guard band (4 px): ignored
   ████▒▒▒▒▒▒·▒▒▒▒▒▒▒▒████      ·   the pixel under test
   ████▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒████
   ███████████████████████
```

**The guard band exists for one specific reason:** without it the ship enters the estimate of
its own background, raising `mean` and `sigma` until the ship hides itself. The bigger the
vessel the worse it gets — exactly backwards from what you want.

Detection if `v > mean + k·sigma`, then contiguous pixels are grouped into targets.

### Why a global threshold cannot be made to work

Reproduce it yourself — it runs the real `cfar()` against a synthetic sea, calm on one side and
rough on the other, with the **same ship** in both:

```bash
python3 -m custody.sardetect --demo
```

| sea | mean | sigma | ship at mean+8σ |
|---|---|---|---|
| calm | 21.9 | 11.8 | 116 |
| rough | 74.0 | 39.4 | 389 |

| global threshold | pixels | in calm | in rough | ships found (of 2) |
|---|---|---|---|---|
| 120 | 1,890 | 0 | **1,890** | 1 |
| 200 | 78 | 0 | 78 | 1 |
| 300 | 27 | 0 | 27 | 1 |
| 450 | 0 | 0 | 0 | **0** |

No number works: below 450 the rough half floods with false alarms, above it the ship in calm
water disappears. CA-CFAR on the same image finds **both, with zero false alarms**, because it
computed two thresholds 3.3× apart on its own:

```
( 60, 60)  26 px  peak  116   background mu= 22.4 sd= 12.2  ->  local threshold  95.5
(180, 60)  27 px  peak  389   background mu= 74.8 sd= 40.3  ->  local threshold 316.7
```

That is the constant rate: the threshold floats with the clutter, so the proportion of false
alarms stops depending on the weather.

### `k` is the false-alarm dial, and the clutter model moves it more than `k` does

This is the number to quote when somebody asks what your false-positive rate is. Per pixel, for
a threshold of `k` sigmas, assuming **Rayleigh** amplitude clutter:

| `k` | false alarms per pixel | in a 2000×2000 crop |
|---|---|---|
| 4 | 5.5·10⁻⁴ | ~2,200 px |
| 5 | 3.5·10⁻⁵ | ~141 px |
| **6** (the default) | 1.5·10⁻⁶ | **~6 px** |
| 8 | 6.9·10⁻¹⁰ | ~0 px |

**Say the assumption out loud before anyone asks.** At `k=6`, assuming Gaussian clutter gives
9.9·10⁻¹⁰ — **1,500× lower** than Rayleigh. And real sea clutter has heavier tails than Rayleigh
(the K distribution), so the true rate is worse than either row. The model matters more than the
threshold, which is why the operationally useful number — how many wrong flags per week the
customer tolerates — cannot be derived here. It has to be asked.

Then the useful half: **each target is matched against AIS interpolated to the acquisition
instant**, not against the last known fix. A ship at 12 knots covers 370 m in a minute, so
matching against the last fix would manufacture false "dark" vessels wholesale. A target with no
AIS vessel within the match radius is reported as **dark** — the operational definition of what
this whole tool is looking for.

Targets also go on the map: a green ring where AIS explains it, a dashed red ring where nothing
does.

### What it is not

- **A bright target is not necessarily a ship.** A wreck, a buoy, a rock, a platform and a
  clutter spike all look the same. Check the wreck layer (§21) before escalating.
- **Near the coast it is indicative only.** Rock and buildings return as brightly as a hull.
  Targets within 200 m of the DTM coastline are discarded and the panel says how many, but an
  islet that is not in the coastline still gets through. Trust it in open water.
- **The length estimate is an order of magnitude, not a measurement.** Speckle and sidelobes
  widen the target.
- **The crop is uncalibrated DN**, not sigma-nought. Fine for local contrast, not for
  backscatter in dB. Calibrating needs the full product.

### What already exists, if you would rather not build it

| Tool | What it is | Verdict |
|---|---|---|
| **ESA SNAP — Ocean Object Detection** | The reference implementation, CFAR, in ESA's own toolbox. Free, scriptable from the command line with `gpt` | The right answer if you want ESA-blessed provenance for a report. It is a ~1 GB Java install and it wants the full SAFE product, which is why it is not in this build |
| **EMSA CleanSeaNet** | The EU's **operational** SAR service: vessel detection and oil-spill detection, delivered to member-state authorities. Finland is a user | **The one worth a phone call.** Not an open API — access runs through the national contact point, which for Finland is the Border Guard and SYKE. As a Finnish-based company with a defence use case this is a conversation, not a purchase |
| **Global Fishing Watch `sar-presence`** | Sentinel-1 detections already run, with `matched = 'false'` marking the dark ones | Free with the token you already need (§19). Gridded, not point detections |
| **xView3** | A public dataset and challenge for dark-vessel detection, with open-source winning models | The route if you want a learned detector rather than CFAR. Needs a GPU and a training pipeline |
| **This build** | CA-CFAR on a free crop, stdlib only, matched to AIS | Zero dependencies, runs on demand, and you own it |

**The recommendation:** keep CFAR for the live map because it costs nothing and needs no
account, and open the CleanSeaNet conversation in parallel. Do not train a model until you have
a labelled set, and you will not have one until you have the HELCOM archive (§23).

---


### Radar confirmation of a track

Open any vessel's **Position history** and the panel offers **Check against Sentinel-1**.
For every Sentinel-1 pass that crosses the track inside its time window, the viewer crops
1 km around **where AIS says the vessel was at that exact instant** and runs CFAR on it.

The instant matters. AIS positions are interpolated to the acquisition time, not taken from
the last fix: a ship at 12 knots moves 370 m in a minute, so comparing against the last fix
would manufacture misses.

| On the map | Meaning |
|---|---|
| **Cyan ring, `SAR ✓` label** | AIS and radar agree. A cooperative sensor the vessel controls and a non-cooperative one it does not both put it here. **This is the strongest statement the tool can make.** The short dashed line points at the radar target; the offset in metres is in the popup |
| **Amber dashed ring** | The satellite imaged this spot at this instant and found nothing within the match radius |

An amber ring is **not** proof the vessel was absent. Heavy sea, a small hull, an unlucky
look angle — any of them hides a ship. It is the gap that deserves a look, and the panel
says so rather than letting you read it as a finding.

Passes run one at a time, not in parallel: each crop is about two seconds of CFAR on the
server, and firing ten at once only freezes the map for the same total. Results paint as
they arrive. Crops are cached, so re-running a track is near-instant.

---
## 23. Reconstructing the cable incidents

The question behind this whole project: **can this tool replay the day a cable was cut?**

Short answer: **about 70% of it, today, for free — and the missing 30% is one email.**

### The three cases

| Incident | Date | Vessel | What broke |
|---|---|---|---|
| Balticconnector | 8 Oct 2023 | *NewNew Polar Bear* | Gas pipeline FI–EE plus telecom cables |
| C-Lion 1 / BCS East-West | 17–18 Nov 2024 | *Yi Peng 3* | Two telecom cables, Baltic proper |
| **Estlink 2 + 4 telecom** | **25 Dec 2024** | ***Eagle S*** | Power interconnector and four cables. Boarded by Finnish authorities |

Start with **Eagle S**. It is in Finnish territorial waters, inside your AOI, it went to court,
and the Helsinki Court of Appeal revived the case on 27 August 2026 — so there is a public
evidentiary record to check your reconstruction against.

### What you already have, verified

**Sentinel-1, free, no account.** I checked the archive for all three dates:

| Incident | Scenes available |
|---|---|
| Balticconnector, 7–10 Oct 2023 | 4 — including **07 Oct 04:26Z**, the day before |
| C-Lion 1, 17–19 Nov 2024 | 7 — including **17 Nov 16:36Z**, the same day |
| Eagle S, 24–27 Dec 2024 | 5 — **24 Dec 15:41Z** and **27 Dec 04:50Z** |

Note what that last row says. **There is no Sentinel-1 pass over the Gulf on 25 December 2024.**
The satellite was not there when it happened. You get the day before and two days after, which
is enough to show the vessel approaching and leaving, and not enough to image the act. That is
the single most important thing your reconstruction will demonstrate, and it is an argument for
your own constellation rather than against your tool.

Everything else already in the build works on those dates unchanged: cables, bathymetry,
anchoring bans, defence areas, wrecks, the satellite chip, the CFAR detector.

**Port calls from Digitraffic go back to at least 2020** — verified: 106 calls on 10 Jan 2020,
51 on 8 Oct 2023, 53 on 26 Dec 2024. Free, no key, filterable by IMO, MMSI, name and date. Not
positions, but arrival and departure times that bracket a transit.

### What you are missing: historical AIS

**Digitraffic has no historical AIS endpoint.** I checked the OpenAPI spec: `/api/ais/v1/locations`
is current state only. Your recorder holds about two weeks. For December 2024 you need an
archive, and there are three routes.

| Route | What you get | Cost | How long |
|---|---|---|---|
| **1. Global Fishing Watch** | Events and vessel tracks back to 2012, by vessel. Fastest path to *Eagle S* on 25 Dec 2024 | Free with the token you already need | Days |
| **2. HELCOM archive** | **All AIS received by the Baltic states since 2005.** The real prize | Free for research use | Weeks to months |
| **3. Fintraffic direct** | Finnish AIS archive, if they hold and will release one | Unknown — ask | Unknown |

### The plan

**Step 1 — GFW token (days).** You need it anyway for §19. With it, pull *Eagle S* (IMO
9329760) events and track for 20 Dec 2024 – 5 Jan 2025. Enough to put the vessel on the map on
the right day. Start here because it is the only route that can show a result this week.

**Step 2 — HELCOM request (same week, long wait).** Ask the HELCOM Secretariat for the Gulf of
Finland extract for 2024, bbox 22–30.5 E / 59–60.9 N. Contacts already researched: Matthew
Richard (Senior Data Manager), Katarina Viik, Florent Nicolas. Two things to settle in the
**same** email, because the answer changes whether the data is usable:

> *Does the restriction in Appendix 3 apply to the data delivered, or to onward sharing by the
> recipient? Specifically: does the extract include MMSI and IMO, and may a recipient use
> vessel identity internally for analysis without publishing it?*

and

> *Which body now holds the archive? It was with the Danish Maritime Authority and was being
> transferred to the Norwegian Coastal Administration.*

Frame it as Laurea MBA thesis research under Appendix 1. Without identity the extract cannot
reconstruct anything — you would have anonymous dots.

**Step 3 — Fintraffic, in parallel.** They publish the live feed under CC BY 4.0 and are a
state agency. Ask whether an archive exists and on what terms. Cheap to ask; if yes, it is the
cleanest licence of the three and the one closest to your AOI.

**Step 4 — the official record.** The Finnish Safety Investigation Authority (OTKES,
*Onnettomuustutkintakeskus*) publishes marine investigation reports, and the Eagle S
prosecution is public. Use both as ground truth: if your reconstruction disagrees with the
investigation, your reconstruction is wrong, and finding out why is the whole value of the
exercise.

**Step 5 — the code.** Smaller than it looks. `custody/ais.py` already normalises fixes to
`{mmsi, ts, lon, lat, sog, cog, heading}`; a HELCOM or GFW loader has to emit the same shape and
nothing downstream changes. What does need building:

- a `--from` / `--to` flag on `build.py`, so a build can target December 2024 instead of the
  recorder's window;
- a scenario file naming the incident, its window and its AOI, so a reconstruction is a saved
  artefact and not a set of remembered clicks;
- the viewer's time cursor already does the rest, including the satellite chip at the exact
  instant.

### What it will show

Honestly, and this is worth knowing before you promise it to anyone: **a vessel track crossing a
cable at anchor-dragging speed, with no satellite image of the moment.** Sentinel-1 revisits
the Gulf every day or two, and cable incidents take minutes. The reconstruction will be AIS-led
with imagery as corroboration before and after.

That gap is your business case. It is the argument for a dedicated constellation stated in the
language of a case that already went to court — which is a stronger pitch than any slide about
revisit time.

---

## 24. What this tool cannot do


Stated here and in the Learn tab, because a tool that hides its limits is worse than no tool.

- **It cannot establish intent.** See §16.
- **It cannot see a vessel that is not transmitting**, unless satellite radar happens to cover
  that minute. Over the December 2024 Gulf of Finland incident, Sentinel-1 had a **61 h 09 min**
  gap.
- **It cannot separate drift from propulsion.** The Copernicus Marine Baltic model carries an
  **87° RMS error** on surface current direction, validated against seven moorings for the whole
  sea.
- **Its thresholds are not calibrated.** They are first guesses against a few days of traffic.
  Every build says so, under **Filters ▸ Threshold values used by this build**.

---

## 25. Making it yours


**Team or company name** — Settings tab, type it, Save. Stored in your browser, so each person
can set their own. For a shared default, edit `viewer/config.json`:

```json
{ "brand": "Custody", "team": "", "tagline": "Subsea infrastructure watch · Gulf of Finland",
  "defaultLang": "en", "showGamification": true }
```

`team` in Settings overrides `config.json`. **Reset to defaults** clears the name, the language,
the badges and the tour.

**Language** — English and Spanish ship in the box. To add one, copy a block in `viewer/i18n.js`,
translate the values, and add the language-specific halves of `viewer/explain.js`. Missing keys
fall back to English, so a partial translation still works.

**Typeface** — the Ubuntu family that ships with Ubuntu 24.04 (`Ubuntu Sans`, loaded from the
local system, **not** from a CDN, so offline use is unaffected). On a machine without it the stack
degrades to the platform UI font. Numeric evidence stays monospaced so columns line up.

---

## 26. Skylight — can I integrate it, and is it free?

**Free: yes. Integrable into what you are building: no.** Those are two separate answers and
only the second one matters for a startup.

Skylight is run by Ai2 (the Allen Institute for AI) and costs nothing. It has an API, and
roughly 23 platforms integrate it. But its **API Policy** restricts intended users to *"country
government agencies, multilateral organizations, non-profit organizations, or academic
institutions"* pursuing the stated Purpose — reducing IUU fishing, maritime crimes, and ocean
health — and it states plainly that *"the Skylight API is not intended for commercial use."*

The **EULA** closes the door explicitly. You may not use the Skylight Services:

> *"For commercial purposes of any kind, including resale, distribution, or **development of a
> competitive product or service**…"*

You are building a maritime domain awareness product. That is a competitive product, named in
the clause. As a Laurea MBA student you could very plausibly get an **account** for thesis
research — the academic route is open, and using it to study the field is exactly what it is
for. Building your product on top of it is not, and discovering that after shipping would be
the expensive version of this conversation.

### What to do instead

**Use Skylight as a benchmark, and rebuild from the shared upstream.** Its chips come from
Sentinel-1, which is free Copernicus data that ESA publishes for anyone. Its correlation
pipeline — SAR detection matched to AIS — is the genuinely hard part and the thing worth
competing on, not the thumbnail.

That is what §10 does: the chip in this viewer is pulled from the same Sentinel-1 scene Skylight
used, at the same point and instant, through Planetary Computer with no account. The result is
the same vessel.

The same reasoning applies across this build, and it is worth stating once:

| They have | Where it actually comes from | Your route |
|---|---|---|
| SAR vessel chips | Copernicus Sentinel-1 | Direct, free, already built (§10) |
| SAR detections | Sentinel-1 + their detector | Global Fishing Watch `sar-presence` (§19), or your own detector on the GRD |
| AIS correlation | AIS + their matching | Your own: you already record AIS and hold the tracks |
| Night lights | NOAA VIIRS | Free from NOAA, not yet wired in |
| RF detections | Commercial (HawkEye 360, Unseenlabs) | Paid, no free route |

The one thing on that list with no free substitute is RF. Everything else you can reach
yourself, and the parts you build are yours to license.

---

## 27. Where the data comes from


| Source | Licence |
|---|---|
| Fintraffic Digitraffic — AIS positions | CC BY 4.0 |
| OpenStreetMap — subsea cables, pipelines, ports | ODbL |
| EMODnet Bathymetry — DTM, isobaths, coastline | EMODnet terms |
| Copernicus Sentinel-1 — GRD footprints, quicklooks, georeferenced radar tiles | Copernicus |
| Copernicus Sentinel-2 L2A — true-colour optical tiles, on demand | Copernicus |
| Global Fishing Watch — behaviour events and activity grid | **CC BY-SA 4.0 — ShareAlike** |
| US Treasury OFAC SDN — sanctioned vessels | US Government work, public domain |
| EU consolidated financial sanctions list | European Commission |
| Wikidata — vessel particulars | CC0 |
| Wikimedia Commons — vessel photographs | per-file licence, shown with the photo |
| EMODnet Human Activities — wrecks, defence areas, munitions dumps | EMODnet terms, open |
| Väylävirasto — navigation restrictions | CC BY 4.0 |
| Vessel particulars (name, type, destination, draught) | Self-reported over AIS — treat accordingly |

Contains modified Copernicus Sentinel data. Full attribution strings are in Sources ▸ Provenance and licences, and in
the map legend.

---

